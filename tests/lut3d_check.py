"""1.103 3D LUT：导入、契约、多张链、导出与像素都要过，且「预览不生效」是真话。

为什么这一版才做：3D LUT 的输出红取决于输入绿与蓝，就不再是每通道一条曲线，
调色链里那段「连续每通道节点塌成一张表」的捷径对它不成立——所以它像 1.84 的
通道混合那样自成阶段。浏览器没有能画一个立方体的原语，于是这一条只有导出会走它。
项目对这种情形的规矩是明说（1.78 的降噪就这么办），不是给预览配一个看着像的近似。

量什么：
* 解析：`.cube` 两种表头都认，`kind` 由文件自己说；行数不是 size³、混进 DOMAIN
  或矩阵关键字、把 1D 喂给 3D 读取器，各自点名拒绝并带行号；超过网格上限的表
  按三线性重采样并写 `resampled_from`；
* 契约：格点数量与 `size³×3` 不符、`resampled_from` 不比存的网格大、节点带
  mix/blend——都拒；
* 两端各自的说法：`grade_tables` 交出的阶段带 `preview: false` 且不搬 49k 个数，
  导出串里是 `lut3d=file=lut3d-…cube:interp=tetrahedral`，而那张 cube 文件确实在
  作业目录里；
* 成片：一个把红蓝对调的 2³ 立方，压在纯红底上，中间像素量到 R/B 对调（控制组
  是同一条链去掉这个节点）；
* 多张立方（1.124）：链里两张各自成一段、两份表各写一个文件、同一张放两次只写一个文件
  但图里有两段、关掉的那张整个不在场；成片上先后顺序读得出来（对调与轮转不相换位），
  夹在两张中间的单通道曲线走的是「前一张换完之后」的那一路通道；
* 能力：`features.lut3d` 真、`features.lut3d_preview` 假、`grade_limits` 的
  `max_lut3d_size` 与契约同一个数。
"""

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.animation import preview_manifest
from agentcut.contracts import (
    TIMEBASE,
    Clip,
    ClipColor,
    Project,
    SequenceSettings,
    Track,
    capabilities,
)
from agentcut.grade import (
    grade_filter,
    grade_stages,
    grade_tables,
    parse_1d_cube,
    parse_3d_cube,
    parse_cube,
)
from agentcut.http_api import create_app
from agentcut.render import compile_render_plan

REPO = Path(__file__).resolve().parent.parent
FFMPEG = REPO / "desktop" / "resources" / "bin" / "ffmpeg.exe"
WIDTH, HEIGHT, FPS, SECONDS = 160, 90, 25, 1
T = TIMEBASE


def cube(edges: int, transform) -> str:
    rows = []
    for blue in range(edges):
        for green in range(edges):
            for red in range(edges):
                rows.append(
                    " ".join(
                        f"{value:.6f}"
                        for value in transform(
                            red / (edges - 1), green / (edges - 1), blue / (edges - 1)
                        )
                    )
                )
    return f"LUT_3D_SIZE {edges}\n" + "\n".join(rows) + "\n"


def swap_rb(red: float, green: float, blue: float) -> tuple[float, float, float]:
    return blue, green, red


def identity(red: float, green: float, blue: float) -> tuple[float, float, float]:
    return red, green, blue


# 三通道轮转。它与红蓝对调**不相换位**（先对调再轮转 ≠ 先轮转再对调），所以两张立方的先后
# 顺序会写在像素上——这是「链序」唯一能测出来的形状。
def rotate(red: float, green: float, blue: float) -> tuple[float, float, float]:
    return green, blue, red


def cube_files(graph: str) -> list[str]:
    """导出串里点名的 cube 文件名，按它们出现的顺序。

    文件名是表体内容的哈希，不是节点编号：同一张表放两次只会得到一个文件，所以「几个文件」
    和「图里有几段」必须分开数——把它们混成一个数，正好看不见想证的那件事。
    """
    marks = [part for part in graph.split(",") if "lut3d=file=" in part]
    return [part[part.index("file=") + 5 :].split(":")[0] for part in marks]


def source(folder: Path) -> Path:
    target = folder / "red.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0xE61E14:s={WIDTH}x{HEIGHT}:r={FPS}:d={SECONDS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-qp",
            "0",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


def verified(path: Path) -> dict:
    return {
        "probe_id": "p-red",
        "path": str(path),
        "kind": "video",
        "label": "red",
        "size_bytes": path.stat().st_size,
        "content_sha256": "0" * 64,
        "duration_ticks": SECONDS * T,
        "width": WIDTH,
        "height": HEIGHT,
        "has_audio": False,
        "frame_rate": {"numerator": FPS, "denominator": 1},
    }


def project(path: Path, grade: list[dict]) -> Project:
    return Project(
        id="p",
        name="lut3d",
        settings=SequenceSettings(
            width=WIDTH,
            height=HEIGHT,
            sample_rate=48000,
            frame_rate={"numerator": FPS, "denominator": 1},
        ),
        tracks=[Track(id="v1", kind="video", name="画面")],
        assets={
            "red": {
                "id": "red",
                "kind": "video",
                "label": "red",
                "reference": str(path),
                "duration_ticks": SECONDS * T,
                "verified": verified(path),
            }
        },
        clips={
            "b": Clip(
                id="b",
                asset_id="red",
                track_id="v1",
                position_ticks=0,
                duration_ticks=SECONDS * T,
                color=ClipColor(grade=grade),
            )
        },
    )


def parse_suite() -> None:
    parsed = parse_cube(cube(2, swap_rb))
    assert parsed["kind"] == "lut3d" and parsed["size"] == 2 and len(parsed["cells"]) == 24, parsed
    assert parsed["resampled_from"] is None
    assert parse_cube(cube(8, identity))["kind"] == "lut3d"
    assert parse_cube("LUT_1D_SIZE 2\n0 0 0\n1 1 1\n")["kind"] == "lut"
    # 超限的表不拒绝，重采样并说出来：17³ 是引擎存进工程状态的上限。
    big = parse_cube(cube(33, identity))
    assert big["size"] == 17 and big["resampled_from"] == 33 and len(big["cells"]) == 17**3 * 3, big
    # 恒等表重采样后仍必须是恒等（三线性采样在格点上取的就是原值，误差留在浮点位里）。
    middle = big["cells"][(8 + 17 * (8 + 17 * 8)) * 3 : (8 + 17 * (8 + 17 * 8)) * 3 + 3]
    assert all(abs(a - b) < 0.02 for a, b in zip(middle, [8 / 16, 8 / 16, 8 / 16])), middle

    for text, why in (
        ("LUT_3D_SIZE 2\n0 0 0\n1 1 1\n", "只有 4 行"),
        ("0 0 0\n1 1 1\n", "没有表头"),
        ("LUT_3D_SIZE 2\n" + "0 0 0\n" * 7 + "2 0 0\n", "越界值会被钳位，不该拒"),
        ("LUT_1D_SIZE 2\n0 0 0\n1 1 1\nLUT_3D_SIZE 2\n", "1D 表喂给 3D 读取器"),
        ("LUT_3D_SIZE 2\nDOMAIN_MIN 0.1 0 0\n" + "0 0 0\n" * 8, "非默认 DOMAIN"),
        ("LUT_3D_SIZE 2\nINPUT_MATRIX 1 0 0 0 1 0 0 0 1\n" + "0 0 0\n" * 8, "矩阵关键字"),
    ):
        refused = None
        try:
            parse_3d_cube(text)
        except Exception as error:  # noqa: BLE001
            refused = getattr(error, "code", None), str(error)
        if why.endswith("不该拒"):
            assert refused is None, (why, refused)
            continue
        assert refused and refused[0] == "INVALID_LUT", (why, refused)
    # 拒绝必须说得出行号：界面与 Agent 都靠它指路。缺一行也带声明网格的那一行，读不懂的行同理。
    try:
        parse_3d_cube("LUT_3D_SIZE 2\n" + "0 0 0\n" * 8 + "0.5 0.5\n")
    except Exception as error:  # noqa: BLE001
        assert error.details.get("line") == 10, error.details  # type: ignore[attr-defined]
        assert "cannot read the row" in str(error), str(error)
    else:
        raise AssertionError("读不懂的行本该被点名")
    try:
        parse_3d_cube("LUT_3D_SIZE 2\n0 0 0\n")
    except Exception as error:  # noqa: BLE001
        assert (error.details.get("size"), error.details.get("rows")) == (2, 1), error.details  # type: ignore[attr-defined]
        assert error.details.get("line") == 1, error.details  # type: ignore[attr-defined]
    else:
        raise AssertionError("行数不够本该报 size、rows 与声明它的那一行")
    # 读不出数字的拒绝以前交回空 details：AGENTS 说 .cube 被拒要给行号。
    for text, where, reader in (
        ("LUT_3D_SIZE 2\n0 0 0\nq 1 1\n" + "0 0 0\n" * 5, 3, parse_3d_cube),
        ("LUT_3D_SIZE x\n", 1, parse_3d_cube),
        ("LUT_1D_SIZE 2\n0 0 0\nq 1 1\n", 3, parse_1d_cube),
        ("LUT_1D_SIZE x\n", 1, parse_1d_cube),
    ):
        try:
            reader(text)
        except Exception as error:  # noqa: BLE001
            assert error.details.get("line") == where, (  # type: ignore[attr-defined]
                reader.__name__,
                text[:22],
                error.details,
            )
        else:
            raise AssertionError("读不出的数字本该点名行号")
    # 1D 读取器遇到 3D 文件要指真出路，不是「不支持」。
    try:
        parse_1d_cube(cube(4, identity))
    except Exception as error:  # noqa: BLE001
        assert "parse_cube" in str(error), str(error)
    print("   解析：两种表头都认、超限重采样并说来源、六种坏文件各自点名（行数不够也带行号）")


def contract_suite() -> None:
    payload = parse_cube(cube(2, swap_rb))
    node = {key: value for key, value in payload.items() if key != "kind"}
    ClipColor(grade=[{"kind": "lut3d", **node}])
    for broken, why in (
        ({"kind": "lut3d", **{**node, "cells": node["cells"][:-3]}}, "格点数与 size³ 不符"),
        ({"kind": "lut3d", **{**node, "resampled_from": 2}}, "resampled_from 不比存的网格大"),
        ({"kind": "lut3d", **node, "mix": 0.5}, "节点带强度"),
        ({"kind": "lut3d", **node, "blend": "screen"}, "节点带混合方式"),
        ({"kind": "parallel", "branches": [{"kind": "lut3d", **node}]}, "3D 表进并联分支"),
    ):
        try:
            ClipColor(grade=[broken])
        except ValidationError:
            continue
        raise AssertionError(f"契约没拒掉：{why}")
    print(
        "   契约：格点数、重采样来源、mix/blend、并联分支四样都拒，强度与混合方式在节点上根本不存在"
    )


def chain_suite() -> None:
    """两张立方同一条链：都在导出串里、各自的表都在作业目录里、顺序不换人。

    这一段是 1.124 补的。以前只量过一张立方，而「链里有几张」这件事恰好是塌表捷径最容易
    咬人的地方——每通道那段是攒够了一批才 flush 的，立方是自己成一段的，所以两张相邻的立方
    在任何一端被并成一张，画面都会悄悄变一个样子，而契约、能力、单张的成片全都不会红。
    """

    class Plan:
        def __init__(self) -> None:
            self.text_files: dict[str, str] = {}

    def cube_node(text: str) -> dict:
        payload = parse_cube(text)
        return {"kind": "lut3d", **{key: value for key, value in payload.items() if key != "kind"}}

    swapped = cube_node(cube(2, swap_rb))
    # 恒等立方当第二张用：它对像素不动，所以「两张都在」在成片里读得出——但这里要的是它在
    # 图和文件里确实占了一段，不是它把第一段顶掉了。
    plain_cube = cube_node(cube(2, identity))
    curve = {
        "kind": "curve",
        "channel": "rgb",
        "points": [{"x": 0.0, "y": 0.1}, {"x": 1.0, "y": 0.9}],
    }

    for grade, want, why in (
        ([swapped, plain_cube], ["lut3d", "lut3d"], "两张不同的立方"),
        ([swapped, dict(swapped)], ["lut3d", "lut3d"], "同一张立方放两次"),
        ([swapped, curve, plain_cube], ["lut3d", "lut", "lut3d"], "立方把每通道那段打断两次"),
        ([swapped, {**plain_cube, "enabled": False}], ["lut3d"], "关掉的那张整个不在场"),
    ):
        color = ClipColor(grade=grade)
        stages = grade_stages(color)
        assert [stage["type"] for stage in stages] == want, (
            why,
            [stage["type"] for stage in stages],
        )
        plan = Plan()
        graph = grade_filter(color, plan)
        files = cube_files(graph)
        assert len(files) == want.count("lut3d"), (why, files)
        # 图里点名的文件必须真的会被写进作业目录，否则那一阶段在成片里就是原样交回。
        assert all(name in plan.text_files for name in files), (why, files, sorted(plan.text_files))

    # 顺序：文件名的先后不算证据，表体内容才是。第一张的表必须在第一个文件里。
    # 两条各断一次并报出自己差了多少个采样点——两张立方开头几个格点全是 0，只报前三格看不出是谁。
    color = ClipColor(grade=[swapped, plain_cube])
    plan = Plan()
    files = cube_files(grade_filter(color, plan))
    assert len(set(files)) == 2, files
    for position, (name, entry) in enumerate((("第一张", swapped), ("第二张", plain_cube))):
        written = parse_cube(plan.text_files[files[position]])["cells"]
        differ = [index for index, (a, b) in enumerate(zip(written, entry["cells"])) if a != b]
        assert not differ, (position, name, len(differ), differ[:4])
    # 同一张表放两次只写一个文件，但图里必须有两次——文件名是表体的哈希，不是节点的编号。
    twin = Plan()
    twin_graph = grade_filter(ClipColor(grade=[swapped, dict(swapped)]), twin)
    assert len(twin.text_files) == 1 and twin_graph.count("lut3d=file=") == 2, (
        twin_graph,
        sorted(twin.text_files),
    )

    # 1.234：预览这一端由画布画立方——它们带着格点进段表，CSS 那一串里没有滤镜可挂。
    both_preview = preview_manifest(project(Path(__file__), [swapped, plain_cube]))["clips"]["b"]
    both_stages = both_preview["grade"]["stages"]
    assert [stage["type"] for stage in both_stages] == ["lut3d", "lut3d"], both_stages
    assert all(
        stage["preview"] is True and "cells_u8" in stage for stage in both_stages
    ), both_stages
    assert both_preview["webgl"] is True and "url(#" not in both_preview["color_filter"], (
        both_preview["webgl"],
        both_preview["color_filter"],
    )
    drawn = preview_manifest(project(Path(__file__), [swapped, curve, plain_cube]))["clips"]["b"][
        "grade"
    ]["stages"]
    assert [stage["type"] for stage in drawn] == ["lut3d", "lut", "lut3d"], drawn
    print(
        "   多张立方：两张各自成一段且文件各写一份、同一张放两次只写一个文件但图里两段、"
        "关掉那张整个不在场、立方把每通道那段打断两次、预览里几张都带着格点进表"
    )


def both_ends_suite() -> None:
    target = project(
        Path(__file__),
        [
            {
                "kind": "lut3d",
                **{k: v for k, v in parse_cube(cube(2, swap_rb)).items() if k != "kind"},
            }
        ],
    )
    tables = grade_tables(target.clips["b"].color)
    stage = tables["stages"][0] if isinstance(tables, dict) else tables[0]
    assert stage["type"] == "lut3d" and stage["preview"] is True, stage
    # 2³ 的格子、每格三字节——画布按红最快读进 3D 纹理。
    assert len(base64.b64decode(stage["cells_u8"])) == 2 * 2 * 2 * 3, stage
    assert "lut3d" in json.dumps(tables, ensure_ascii=False)

    class Plan:
        def __init__(self) -> None:
            self.text_files: dict[str, str] = {}

    plan = Plan()
    graph = grade_filter(target.clips["b"].color, plan)
    name = next(iter(plan.text_files))
    assert graph == f"lut3d=file={name}:interp=tetrahedral", graph
    body = plan.text_files[name]
    assert body.startswith('TITLE "LUT"') and "LUT_3D_SIZE 2" in body, body[:80]
    assert parse_cube(body)["cells"] == target.clips["b"].color.grade[0].cells, (
        "写出去又读回来不是同一张表"
    )

    node_for_grade = target.clips["b"].color.grade[0].model_dump(exclude_none=False)
    # 顺序是这一版的设计点：3D 表必须像矩阵那样打断「连续每通道节点塌成一张表」那一段。
    both = ClipColor(
        grade=[
            {
                "kind": "curve",
                "channel": "rgb",
                "points": [{"x": 0.0, "y": 0.2}, {"x": 1.0, "y": 0.8}],
            },
            node_for_grade,
            {
                "kind": "curve",
                "channel": "rgb",
                "points": [{"x": 0.0, "y": 0.1}, {"x": 1.0, "y": 0.9}],
            },
        ]
    )
    mixed_tables = grade_tables(both)
    kinds = [stage["type"] for stage in mixed_tables["stages"]]
    assert kinds == ["lut", "lut3d", "lut"], kinds
    plan_two = Plan()
    mixed_graph = grade_filter(both, plan_two)
    assert (
        mixed_graph.index("lutrgb") < mixed_graph.index("lut3d") < mixed_graph.rindex("lutrgb")
    ), mixed_graph
    assert len(plan_two.text_files) == 1, plan_two.text_files
    try:
        grade_filter(target.clips["b"].color)
    except Exception as error:  # noqa: BLE001
        assert getattr(error, "code", "") == "LUT3D_NO_PLAN", error
    else:
        raise AssertionError("没有 plan 时本该点名拒绝")

    # 界面真正读的是 preview_manifest 里那份阶段表。1.234 起立方由画布画：它带着格点进表，
    # 并且这一条片段的 CSS 滤镜串里**一个字都不许再挂**（画布已经把基础调色与整条链算过一遍）。
    solo = preview_manifest(target)["clips"]["b"]
    assert solo["webgl"] is True and solo["color_filter"] == "", (
        solo["webgl"],
        solo["color_filter"],
    )
    assert [stage["type"] for stage in solo["grade"]["stages"]] == ["lut3d"], solo["grade"]
    assert "cells_u8" in solo["grade"]["stages"][0], solo["grade"]["stages"][0]
    assert solo["color_basics"] and len(solo["color_basics"]) == 3, solo["color_basics"]
    mixed = preview_manifest(project(Path(__file__), both.grade))["clips"]["b"]
    drawn = mixed["grade"]["stages"]
    assert "lut3d" in [stage["type"] for stage in drawn], drawn
    assert mixed["webgl"] is True and "url(#" not in mixed["color_filter"], mixed["color_filter"]
    # 第二路画面那种链画布接不下来：立方退回「只在导出里生效」，而**别的那几段仍要留在 CSS
    # 滤镜里**——`webgl` 若只看「链上有没有立方」，这一条片段的整条调色会在预览里悄悄消失。
    edged = [
        {"kind": "curve", "channel": "rgb", "points": [{"x": 0.0, "y": 0.2}, {"x": 1.0, "y": 0.8}]},
        node_for_grade,
        {"kind": "composite", "mode": "screen", "mix": 0.5},
    ]
    edged_row = preview_manifest(project(Path(__file__), edged))["clips"]["b"]
    assert edged_row["webgl"] is False, edged_row["webgl"]
    assert edged_row["color_basics"] is None, edged_row["color_basics"]
    assert "url(#" in edged_row["color_filter"], edged_row["color_filter"]
    assert all("cells_u8" not in stage for stage in edged_row["grade"]["stages"]), (
        edged_row["grade"]
    )
    cube_lines = len(body.splitlines()) - 4
    print(
        f"   两端：预览带格点进画布、CSS 清空（表体 {cube_lines} 行只在导出里），"
        "第二路画面那种链接不下立方时别的段仍留在 CSS 里"
    )


def media_suite(folder: Path) -> None:
    path = source(folder)
    node = {
        "kind": "lut3d",
        **{k: v for k, v in parse_cube(cube(2, swap_rb)).items() if k != "kind"},
    }

    def render(grade: list[dict], name: str) -> tuple[int, int, int]:
        plan = compile_render_plan(project(path, grade), "h264-source-quality")
        job = folder / f"job-{name}"
        job.mkdir(exist_ok=True)
        for file, body in plan.text_files.items():
            (job / file).write_text(body, encoding="utf-8")
        for file, blob in plan.binary_files.items():
            (job / file).write_bytes(blob)
        out = folder / name
        done = subprocess.run(
            plan.ffmpeg_argv(str(FFMPEG), str(out)),
            cwd=job,
            capture_output=True,
            timeout=420,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
        raw = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-ss",
                "0.5",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-vf",
                "crop=4:4:80:44,scale=1:1:flags=area,format=rgb24",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=300,
        ).stdout
        return raw[0], raw[1], raw[2]

    plain = render([], "plain.mp4")
    swapped = render([node], "lut.mp4")
    red, green, blue = plain
    assert red > 180 and blue < 70, plain
    # 2³ 立方把红蓝对调：同一条链、同一个编码器，唯一的差别就是那个节点。
    assert swapped[2] > 180 and swapped[0] < 70, (plain, swapped)
    assert abs(swapped[1] - green) < 24, (plain, swapped)

    # 1.124：两张立方同一条链，成片里两张都走了，而且按链序走。
    # 断言的期望值不是猜的：置换对整数三元组是精确的，所以「先 P 再 Q」的理想结果就是把
    # 上面那次实测的 plain 通道按同一个置换重排——留给编码与四舍五入的余量量出来是 2 级。
    rotated = {
        "kind": "lut3d",
        **{k: v for k, v in parse_cube(cube(2, rotate)).items() if k != "kind"},
    }
    red_curve = {
        "kind": "curve",
        "channel": "red",
        "points": [{"x": 0.0, "y": 0.1}, {"x": 1.0, "y": 0.9}],
    }
    twice = render([dict(node), dict(node)], "twice.mp4")
    forward = render([node, rotated], "forward.mp4")
    backward = render([rotated, node], "backward.mp4")
    curve_between = render([node, red_curve, rotated], "curve_between.mp4")
    curve_before = render([red_curve, node, rotated], "curve_before.mp4")

    def near(a: tuple[int, int, int], b: tuple[int, int, int], budget: int) -> bool:
        return all(abs(one - two) <= budget for one, two in zip(a, b))

    # 同一张立方放两次必须回到原片。只走第一段的话这里读到的是对调值，不是原片。
    assert near(twice, plain, 6), (plain, twice)
    assert not near(twice, swapped, 6), (swapped, twice)
    want_forward = rotate(*swap_rb(*plain))
    want_backward = swap_rb(*rotate(*plain))
    # 两条链的理想结果差得越远，这一断言越咬得住；源画面万一三通道靠在一起就要说出来。
    assert max(abs(a - b) for a, b in zip(want_forward, want_backward)) > 60, (
        want_forward,
        want_backward,
    )
    assert near(forward, want_forward, 8), (plain, want_forward, forward)
    assert near(backward, want_backward, 8), (plain, want_backward, backward)
    # 夹在两张立方中间的那条单通道曲线走的是「前一张立方换完之后」的那一路通道：
    # 挪到链首就不是同一幅画了。两头都断，才排除了「曲线被并进某一张立方里、两边都一样」。
    assert max(abs(a - b) for a, b in zip(curve_between, curve_before)) > 12, (
        curve_between,
        curve_before,
    )
    assert not near(curve_between, forward, 8), (forward, curve_between)
    print(
        f"   成片：纯红 {plain} 经这张 3D LUT 变成 {swapped}（R/B 对调，绿通道不动）；"
        f"同两张立方 {twice} 走回原片，{forward} 与 {backward} 各按自己的链序落点，"
        f"曲线夹在中间 {curve_between} 与放在链首 {curve_before} 不是一幅画"
    )


def http_suite(folder: Path) -> None:
    token = "lut3d-" + "b" * 44
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(
        create_app(folder / "db.sqlite3", token), base_url="http://127.0.0.1", headers=headers
    ) as client:
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "lut3d-new",
                "name": "表",
                "settings": {
                    "width": WIDTH,
                    "height": HEIGHT,
                    "frame_rate": {"numerator": FPS, "denominator": 1},
                },
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["project"]["id"]
        reply = client.post("/v1/lut/parse", json={"content": cube(4, swap_rb)}, headers=headers)
        assert reply.status_code == 200, reply.text
        payload = reply.json()
        assert payload["kind"] == "lut3d" and payload["size"] == 4, payload
        bad = client.post(
            "/v1/lut/parse", json={"content": "LUT_3D_SIZE 3\n0 0 0\n"}, headers=headers
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_LUT", bad.text
        assert bad.json()["error"]["details"].get("size") == 3, bad.text
        revision = created.json()["project"]["revision"]
        applied = client.post(
            f"/v1/projects/{project_id}/edits",
            json={
                "request_id": "lut3d-node",
                "expected_revision": revision,
                "commands": [
                    {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "a1",
                            "kind": "video",
                            "label": "红",
                            "reference": "r",
                            "duration_ticks": SECONDS * T,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c1",
                            "asset_id": "a1",
                            "track_id": "v1",
                            "position_ticks": 0,
                            "source_in_ticks": 0,
                            "duration_ticks": SECONDS * T,
                        },
                    },
                    {
                        "op": "clip.patch",
                        "clip_id": "c1",
                        "color": {
                            "grade": [
                                {
                                    "kind": "lut3d",
                                    **{k: v for k, v in payload.items() if k != "kind"},
                                }
                            ]
                        },
                    },
                ],
            },
            headers=headers,
        )
        assert applied.status_code == 200, applied.text
        stored = applied.json()["project"]["clips"]["c1"]["color"]["grade"][0]
        assert stored["kind"] == "lut3d" and stored["size"] == 4 and stored["enabled"] is True, (
            stored
        )
        refused = client.post(
            f"/v1/projects/{project_id}/edits",
            json={
                "request_id": "lut3d-refuse",
                "expected_revision": applied.json()["project"]["revision"],
                "commands": [
                    {
                        "op": "clip.patch",
                        "clip_id": "c1",
                        "color": {
                            "grade": [
                                {"kind": "lut3d", "title": "t", "size": 2, "cells": [0.0, 0.0, 0.0]}
                            ]
                        },
                    }
                ],
            },
            headers=headers,
        )
        assert refused.status_code == 422, refused.text
        caps = client.get("/v1/capabilities", headers=headers).json()
        assert caps["features"]["lut3d"] is True and caps["features"]["lut3d_preview"] is True, (
            caps["features"]
        )
        assert caps["grade_limits"]["max_lut3d_size"] == 17, caps["grade_limits"]
    print(
        "   HTTP：解析回复带 kind、坏文件点名带 details、节点落库读回一字不差、超限格点数被契约拒"
    )


def main() -> None:
    parse_suite()
    contract_suite()
    chain_suite()
    both_ends_suite()
    published = capabilities()
    assert (
        published["features"]["lut3d"] is True and published["features"]["lut3d_preview"] is True
    )
    with tempfile.TemporaryDirectory(prefix="agentcut-lut3d-") as scratch:
        folder = Path(scratch)
        media_suite(folder)
        http_suite(folder)
    print("PASS: 3D LUT 导入即节点、契约拒得点名、导出真换像素、预览带着同一张表的格点进画布")


if __name__ == "__main__":
    main()
