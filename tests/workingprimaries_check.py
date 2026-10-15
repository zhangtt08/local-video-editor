"""1.159 工程基色：这一档原色是谁声明的、预览与导出各折哪一趟，正反都量。

四件事各钉一处：

1. **名单只有一个主人。** `capabilities.working_primaries` 交的就是 `gamut.WORKING_PRIMARIES`——
   即 `gamut.PRIMARIES` 里曲线恰为交付那一档（rec709）的名字。契约、界面、这条门禁都读它。选了
   不在名单里的（`display-p3` 的原色是 P3，但曲线是 sRGB，所以它不在）要被点名拒绝，话里带着名单。
2. **默认档一字不改，宽档折的是同一趟形状。** 不带这个字段的旧载荷读进来就是 rec709；把 rec709
   明写进去与根本不写，预览清单逐字节相同。选了宽档才在链子最后多出「每通道表 → matrix → 每通道表」
   这三段（没挂调色链的那一段也要多，折的是工程那一档，与链子在不在无关）：中间那九个系数就是
   `gamut.primaries_matrix(working, "rec709")`，两端那两张表就是 `gamut.transfer_tables()`，与导出
   那张立方体同一条形状（抬进线性光—乘九个数—落回信号）。把九个数直接乘在**存储值**上不是同一件事，
   `fold_math_suite` 就是为它放的。而且滤镜 id 跟着变——id 不变的话浏览器会把两张不同的图挂在同一个
   `<filter id>` 上（它认 id 不认内容）。
3. **导出折的是「工程 → 容器声明的那档」。** 同一份工程、同一个 `colour_tag=bt2020`：
   working=rec709 与 working=p3-d65 交出的立方体不是同一张（`delivery_cube` 两端不同），真出的
   两片也不同色；而 working=rec2020 配 `bt2020` 是同一档，图里就不该再有 `lut3d=` 那一趟——凭空
   多一层矩阵正是自洽检查看不见的那种错。灰在这趟里必须还是灰（每行和为 1）。
4. **写它是一次设置。** `POST /v1/projects/{id}` 那条：一次一个版本；被拒的那一次不涨版本、
   也不留半个字。
"""

import subprocess
import tempfile
import time
from pathlib import Path
from random import Random

from fastapi.testclient import TestClient

from agentcut.contracts import SCHEMA_VERSION, ClipColor, Project, capabilities
from agentcut.contracts import TIMEBASE as T
from agentcut.gamut import (
    PRIMARIES,
    WORKING_PRIMARIES,
    delivery_cube,
    primaries_matrix,
    transfer_tables,
    working_collapse,
)
from agentcut.grade import preview_grade
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-source-quality"
CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.28}, {"x": 1.0, "y": 1.0}],
}


def run(args, timeout=900) -> bytes:
    return subprocess.run(
        [str(arg) for arg in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    ).stdout


def rgb_at(path: Path, at: float) -> tuple[int, int, int]:
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-vf",
            "scale=1:1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    return (raw[0], raw[1], raw[2])


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def flatten(matrix: list[list[float]]) -> list[float]:
    return [round(value, 6) for row in matrix for value in row]


def vocabulary_suite() -> None:
    published = capabilities()["working_primaries"]
    assert published == list(WORKING_PRIMARIES), (published, WORKING_PRIMARIES)
    derived = tuple(name for name, entry in PRIMARIES.items() if entry[2] == "rec709")
    assert WORKING_PRIMARIES == derived, (
        f"名单不再是从 PRIMARIES 现算的：{WORKING_PRIMARIES} vs {derived}"
    )
    assert {"rec709", "p3-d65", "rec2020"} <= set(published), published
    assert "display-p3" not in published, (
        "display-p3 的曲线是 sRGB，不是交付那一档；它进名单就等于宣称这里也管曲线"
    )
    assert working_collapse("rec709") is None, "同一档必须不折"
    assert working_collapse("p3-d65") == flatten(primaries_matrix("p3-d65", "rec709")), (
        "预览折的那九个系数不是 primaries_matrix 算的那一份"
    )
    for name in published:
        if working_collapse(name) is None:
            continue
        numbers = working_collapse(name)
        assert len(numbers) == 9, name
        assert all(abs(sum(numbers[row * 3 : row * 3 + 3]) - 1.0) < 1e-5 for row in range(3)), (
            f"{name} 的某一行和不是 1：灰会被推走"
        )
    assert SCHEMA_VERSION == 20, SCHEMA_VERSION
    assert capabilities()["project_schema_version"] == 20

    decode, encode = transfer_tables()
    assert len(decode) == len(encode) == 256, (len(decode), len(encode))
    assert decode[0] == 0.0 and abs(decode[-1] - 1.0) < 1e-9, (
        f"抬进线性光那张表两端不是 0 与 1，而是 {(decode[0], decode[-1])}："
        "预览那两步会把最亮的一格推下去，曲线的常数或那两级表的切法被改过"
    )
    assert all(later > earlier for earlier, later in zip(decode, decode[1:])), (
        "抬进线性光那张表不单调，预览那两步会把颜色折回退"
    )
    assert all(later > earlier for earlier, later in zip(encode, encode[1:])), (
        "落回信号那张表不单调，预览那两步会把颜色折回退"
    )
    plain = ClipColor(exposure=0.0, contrast=1.0, saturation=1.0)
    assert preview_grade(plain, "rec709") is None, (
        "默认档下没挂调色链的一段不该凭空多出一个滤镜定义——那是一份旧工程里没出现过的字节"
    )
    bare = preview_grade(plain, "p3-d65")
    assert bare is not None and [stage["type"] for stage in bare["stages"]] == [
        "lut",
        "matrix",
        "lut",
    ], "没挂调色链的那一段在宽档工程里也必须折：折的是工程那一档，与链子在不在无关"


def anchor_eotf(signal: float) -> float:
    """公布常数写死的 BT.709 摄像机曲线（α=1.099、β=0.099、指数 0.45、线性段斜率 4.5）。

    这条门禁的尺**不读产品那份曲线**：第一版的 `exact()` 直接 import `gamut.bt709_eotf/oetf` 算
    「真折叠」，于是产品曲线一动，基准与被测一起动——本仓把这类耦合量成过 29 阶的偏差，也定过
    「自己当自己的尺」这条戒。两张表另有一条断言拿这把尺逐格量（`table_suite`）。
    """
    if signal <= 0.081:
        return signal / 4.5
    return ((signal + 0.099) / 1.099) ** (1 / 0.45)


def anchor_oetf(light: float) -> float:
    """`anchor_eotf` 的逆。两条各写一次指数，别对调——1.153 就对调过一次。"""
    if light < 0.018:
        return 4.5 * light
    return 1.099 * light**0.45 - 0.099


def table_suite() -> int:
    """预览那两张表必须逐格等于这把独立的尺；返回比过的格数。"""
    decode, encode = transfer_tables()
    anchor_decode = [round(anchor_eotf(index / 255.0), 9) for index in range(256)]
    anchor_encode = [round(anchor_oetf(index / 255.0), 9) for index in range(256)]
    assert decode == anchor_decode, (
        "预览那两级表不再是那条公布的 BT.709 曲线切的：曲线的出处被换过，1.153/1.156/1.159 那几批"
        "交付实测要一起重量，别只把这条断言改成新曲线"
    )
    assert encode == anchor_encode, "落回信号那张表对不上那条公布曲线，同上"
    return 2 * len(decode)


def fold_math_suite() -> tuple[int, int, int]:
    """预览那三段与导出那张立方体必须是同一条函数——把九个数乘在存储值上不是。

    这一条是本轮自己抓出来的缺陷放出来的门禁：第一版预览只交一个 `matrix` 阶段，浏览器就把九个系数
    乘在 sRGB 存储值上——那种做法与真折叠差多少，由下面这两个数当场量出来（25³ 的格子加六万个固定
    种子的随机色，一起跑）。现在交的是「每通道表 → 九个数 → 每通道表」，两端那两张表就是
    `transfer_tables()` 切的 256 格。
    """
    matrix = primaries_matrix("p3-d65", "rec709")
    decode, encode = transfer_tables()
    size = len(decode)

    def sample(table: list[float], signal: float) -> float:
        position = max(0.0, min(1.0, signal)) * (size - 1)
        low = int(position)
        high = min(low + 1, size - 1)
        return table[low] * (1 - (position - low)) + table[high] * (position - low)

    def middle(linear: list[float]) -> list[float]:
        return [sum(row[column] * linear[column] for column in range(3)) for row in matrix]

    def folded(pixel: tuple[int, int, int]) -> list[int]:
        mid = middle([sample(decode, value / 255.0) for value in pixel])
        return [round(sample(encode, max(0.0, min(1.0, value))) * 255) for value in mid]

    def exact(pixel: tuple[int, int, int]) -> list[int]:
        mid = middle([anchor_eotf(value / 255.0) for value in pixel])
        return [round(anchor_oetf(max(0.0, min(1.0, value))) * 255) for value in mid]

    def on_stored(pixel: tuple[int, int, int]) -> list[int]:
        mid = middle([value / 255.0 for value in pixel])
        return [round(max(0.0, min(1.0, value)) * 255) for value in mid]

    worst_fold = 0
    worst_stored = 0
    grid = 255 // 23
    samples = [
        (red, green, blue)
        for red in range(0, 256, grid)
        for green in range(0, 256, grid)
        for blue in range(0, 256, grid)
    ]
    rng = Random(20261014)
    samples += [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(60000)]
    for pixel in samples:
        wanted = exact(pixel)
        worst_fold = max(
            worst_fold, max(abs(a - b) for a, b in zip(folded(pixel), wanted, strict=True))
        )
        worst_stored = max(
            worst_stored, max(abs(a - b) for a, b in zip(on_stored(pixel), wanted, strict=True))
        )
    assert worst_fold <= 2, (
        f"预览那三段与精确折叠差到 {worst_fold} 阶：两端那两张表不是按同一条曲线切的"
    )
    assert worst_stored >= 20, (
        f"乘在存储值上与真折叠只差 {worst_stored} 阶了？那「同一条形状」这句话要重新量，"
        "这条门禁跟着重新判"
    )
    return worst_fold, worst_stored, len(samples)


def http_suite() -> dict[str, tuple[int, int, int]]:
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        for name, colour in (("orange", "0xB45032"), ("grey", "0x808080")):
            run(
                [
                    FFMPEG,
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={colour}:s={SRC_W}x{SRC_H}:r=30:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv444p",
                    "-r",
                    "30",
                    str(folder / (name + ".mp4")),
                ]
            )
        media = MediaService(folder / "wp.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        exports = folder / "exports"
        runtime = JobRuntime(folder / "wp-api.sqlite3", FFMPEG, exports, [exports, folder])
        token = "w" * 48
        app = create_app(folder / "wp-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            probes = {
                name: client.post(
                    "/v1/media/import", json={"path": str(folder / f"{name}.mp4")}
                ).json()
                for name in ("orange", "grey")
            }
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "wp-new",
                    "name": "工程基色",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            assert created["settings"]["working_primaries"] == "rec709", created["settings"]
            path = f"/v1/projects/{created['id']}"
            commands = [{"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}}]
            for index, name in enumerate(("orange", "grey")):
                commands += [
                    {
                        "op": "asset.import",
                        "asset_id": f"a{index}",
                        "label": name,
                        "probe_id": probes[name]["id"],
                        "verified": probes[name]["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": f"c{index}",
                            "asset_id": f"a{index}",
                            "track_id": "v",
                            "position_ticks": index * T,
                            "duration_ticks": T,
                        },
                    },
                ]
            commands += [
                {
                    "op": "clip.color",
                    "clip_id": clip_id,
                    "color": {"exposure": 0.0, "grade": [CURVE]},
                }
                for clip_id in ("c0", "c1")
            ]
            seed = client.post(
                path + "/edits",
                json={"request_id": "wp-seed", "expected_revision": 0, "commands": commands},
            )
            assert seed.status_code == 200, seed.text
            state = {"revision": seed.json()["project"]["revision"]}
            counter = {"n": 0}

            def manifest() -> dict:
                return client.get(path + "/preview-manifest").json()["clips"]["c0"]["grade"]

            def set_working(working: str | None) -> None:
                settings = dict(client.get(path).json()["settings"])
                if working is None:
                    settings.pop("working_primaries")
                else:
                    settings["working_primaries"] = working
                counter["n"] += 1
                answer = client.post(
                    path,
                    json={
                        "request_id": f"wp-set-{counter['n']}",
                        "expected_revision": state["revision"],
                        "settings": settings,
                    },
                )
                assert answer.status_code == 200, answer.text
                state["revision"] = answer.json()["project"]["revision"]

            def shape(grade: dict) -> tuple[str, list[str], list[list[float]], list[list[float]]]:
                stages = grade["stages"]
                return (
                    grade["id"],
                    [stage["type"] for stage in stages],
                    [stage["m"] for stage in stages if stage["type"] == "matrix"],
                    [stage["r"] for stage in stages if stage["type"] == "lut"],
                )

            baseline = shape(manifest())
            assert baseline[1] == ["lut"] and baseline[2] == [], (
                f"默认档的预览清单该只有一张每通道表，实际 {baseline}"
            )
            set_working("rec709")
            assert shape(manifest()) == baseline, (
                "把默认档明写出来就改了清单——那旧工程的字节从此不稳定"
            )
            set_working("p3-d65")
            widened = shape(manifest())
            assert widened[1] == ["lut", "lut", "matrix", "lut"], (
                f"宽档只该多那一趟三段折叠：{widened[1]}"
            )
            decode, encode = transfer_tables()
            assert widened[3][1:] == [decode, encode], (
                "折在链子最后那两张表不是 gamut.transfer_tables 切的那两张"
            )
            assert widened[2] == [flatten(primaries_matrix("p3-d65", "rec709"))], (
                f"预览里那一级不是引擎算的九个数：{widened[2]}"
            )
            assert widened[0] != baseline[0], (
                "多了一级折叠而滤镜 id 没变——浏览器认 id，两张图会共用同一个 filter"
            )
            before = state["revision"]
            bad = client.post(
                path,
                json={
                    "request_id": "wp-bad",
                    "expected_revision": before,
                    "settings": {
                        **dict(client.get(path).json()["settings"]),
                        "working_primaries": "display-p3",
                    },
                },
            )
            assert bad.status_code == 422, bad.text
            assert "display-p3" in bad.text, bad.text[:300]
            assert client.get(path).json()["revision"] == before, "被拒的那一次涨了版本"
            assert client.get(path).json()["settings"]["working_primaries"] == "p3-d65"

            # 旧写法（这个键整个不出现）必须回到默认档那一份字节：「默认值不改任何一份旧工程的画面」
            # 这句承诺只有在这一格被删回去、预览与基线逐字节相同时才成立。
            set_working(None)
            assert shape(manifest()) == baseline, (
                "把这一格删回「没写过」的样子，预览没回到默认档那份字节——旧工程的画面被新字段改了"
            )
            assert client.get(path).json()["settings"]["working_primaries"] == "rec709", (
                "没写过这一档的工程读出来不是 rec709，那默认值就只是文档里的一句话"
            )

            graphs: dict[str, str] = {}
            cubes: dict[str, str] = {}
            for working in ("rec709", "p3-d65", "rec2020"):
                set_working(working)
                project = Project.model_validate(client.get(path).json())
                plan = compile_render_plan(project, PRESET, colour_tag="bt2020")
                graphs[working] = "\n".join(plan.filters)
                names = [key for key in plan.text_files if key.startswith("primaries-")]
                cubes[working] = "".join(plan.text_files[key] for key in sorted(names))
            assert "lut3d=file=primaries-" in graphs["rec709"], graphs["rec709"][:400]
            assert "lut3d=file=primaries-" in graphs["p3-d65"], graphs["p3-d65"][:400]
            assert "primaries-" not in graphs["rec2020"], (
                "工程已是 Rec.2020、容器也声明 bt2020：再折一次就是凭空多一层矩阵"
            )
            assert "zscale=matrix=2020_ncl" in graphs["rec2020"], graphs["rec2020"][:400]
            assert graphs["rec709"] != graphs["p3-d65"], "换了基色而导出图一个字没变，这设置是摆设"
            assert cubes["rec709"] != cubes["p3-d65"], "两张交付立方体一模一样——两端没换"
            assert cubes["p3-d65"] == delivery_cube("p3-d65", "rec2020"), (
                "图里那张立方体不是 delivery_cube(工程, 容器) 算的那一份"
            )

            delivered: dict[str, tuple[int, int, int]] = {}
            for working in ("rec709", "p3-d65"):
                set_working(working)
                job = client.post(
                    path + "/renders",
                    json={
                        "request_id": f"wp-deliver-{working}",
                        "expected_revision": state["revision"],
                        "preset_id": PRESET,
                        "filename": f"wp-{working}.mp4",
                        "colour_tag": "bt2020",
                    },
                )
                assert job.status_code == 200, job.text
                done = wait(client, job.json()["job"]["id"])
                assert done["status"] == "succeeded", done
                out = Path(done["output_path"])
                delivered[working] = rgb_at(out, 0.4)
                grey = rgb_at(out, 1.4)
                # 灰必须还是灰：折叠是每行和为 1 的矩阵，推不动中性轴。容差 5 不是拍的——
                # 33^3 立方体的插值地板加上有损编码，本轮实测这一趟的偏差是 (74,71,75) 的 4 阶。
                assert max(abs(grey[0] - grey[1]), abs(grey[1] - grey[2])) <= 5, (
                    f"{working}：中灰被折成了彩色 {grey}"
                )
                probed = run(
                    [
                        FFPROBE,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=color_primaries,color_space,color_transfer",
                        "-of",
                        "default=nw=1",
                        str(out),
                    ]
                ).decode("utf-8", "replace")
                # 基色标签在流上不在容器上——`-show_format` 永远读不到它，那样这条是空转的。
                assert "color_primaries=bt2020" in probed, f"容器那一档基色没写进流：{probed!r}"
            moved = max(
                abs(a - b) for a, b in zip(delivered["rec709"], delivered["p3-d65"], strict=True)
            )
            assert moved >= 3, f"换基色后交付的橙一模一样：{delivered}"
            return delivered


def main() -> None:
    # 尺子先立起来：`table_suite` 拿独立的公布曲线逐格量那两张表，跑在别的断言前面，
    # 这样「曲线常数被换过」红在那条说清出处的断言上，而不是某一条只报元组的结构检查。
    cells = table_suite()
    vocabulary_suite()
    worst_fold, worst_stored, samples = fold_math_suite()
    delivered = http_suite()
    print(f"   预览那两级表逐格对过独立的公布曲线：{cells} 格")
    print(
        "   名单 " + "、".join(WORKING_PRIMARIES) + f"（schema {SCHEMA_VERSION}）；"
        f"p3-d65→rec709 首行 {[round(v, 4) for v in (working_collapse('p3-d65') or [])[:3]]}"
    )
    print(
        f"   {samples} 个颜色上比过：预览那三段与精确折叠最坏差 {worst_fold} 阶，把九个数乘在存储值"
        f"上最坏差 {worst_stored} 阶——所以交的是三段，不是一个矩阵"
    )
    print(
        f"   交付的橙：rec709 工程 {delivered['rec709']} vs p3-d65 工程 {delivered['p3-d65']}；"
        "同一档不折、灰仍是灰"
    )
    print(
        "PASS: 名单由 gamut 现算、契约与界面都读它；默认档预览一字不改（把这一格删回「没写过」"
        "也是同一份字节，没挂链子的一段也不凭空多个滤镜），宽档折的是「每通道表→九个数→每通道表」"
        f"那三段、与导出立方体同一条形状（乘在存储值上量到最坏 {worst_stored} 阶）；"
        "滤镜 id 跟着变；导出折的是工程→容器那一档（同一档就不折），两张立方体与两片画面确实不同，"
        "灰仍是灰；被拒的选择既不涨版本也不落库"
    )


main()
