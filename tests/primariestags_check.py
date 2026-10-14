"""1.160 量到的两件事钉成门禁：容器那一格基色能写什么，以及同名两档曲线差多少。

这一轮**不交新能力**——它拦下一条看起来顺理成章、量过才知道会错的路：把「素材自己声明的那档
原色」自动折进工程。拦它的凭据是下面三组当场量的数，不是判断。

1. `color_primaries` 那格能拼出的写法，由随包那支 FFmpeg 6.1.1 当场编一次、当场探针一次，
   分成「写进去读回来同名」「当场拒收」「写了等于没写」三堆。将来任何一张「读素材原色」的表都
   只能从第一堆里取行；谁把第二堆的写法抄进表里，照做的人就会拿到一个根本编不出来的命令。
2. 同一个名字 `rec709` 在引擎里有两条曲线：`grade.GAMMA_BY_SPACE` 给调色链那一对是**纯幂 2.4**
   （BT.1886 那条显示端 EOTF），`gamut.bt709_eotf` 给交付立方体与 1.159 那两级预览表是**分段 0.45**
   （BT.709 摄像机 OETF，也是容器里 `bt709` 那一格本来的意思）。8 位上量：信号域最坏差 27 阶、
   线性域最坏差 18 阶。所以「先按曲线抬进线性光、乘九个系数、再落回信号」这一趟，两端用的曲线
   与中间那一级所假设的曲线不是同一条。
3. 于是那条自动折叠现在**不能交**：`fidelity_1160.py`（在 `agentcut-验收脚本/` 里，可重跑）拿
   一对夹具量过——同一幅颜色分别按 709 与按 P3-D65 存储、容器都写 `bt709` 曲线，把 1.158 那颗
   按钮写下的 `[transfer, matrix, transfer]` 套在 P3 那枚上导出：未折时与基准差 47 阶，折了之后
   仍差 **29** 阶。差的那一截正好在第 2 条那个量级上。把它做成每一段素材的默认动作，等于把这
   29 阶悄悄发给所有人。

所以这里钉住的是：词的表（第一组）、这条分叉还在（第二组，谁统一了它这条就红并要求重新量），
以及那条自动折叠的开关**还没有**契约字段（第三组，真要做时先解决曲线，再让这条门禁跟着改）。
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agentcut import contracts  # noqa: E402
from agentcut.gamut import (  # noqa: E402
    PRIMARIES,
    bt709_eotf,
    bt709_oetf,
    primaries_matrix,
)
from agentcut.grade import GAMMA_BY_SPACE  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"

# 候选写法：FFmpeg 那张枚举表里与本项目有关的每一行，外加两个「看起来像但不存在」的拼法。
SPELLABLE = ("bt709", "smpte170m", "bt470bg", "bt2020", "smpte432", "smpte431", "film", "bt470m")
REFUSED = ("jcac", "echostars", "170m", "p3")
SILENT = "unknown"

# 引擎认识的那几档里，容器这一格确实拼得出、且读回来同名的对应关系（第一组的子集）。
MEASURED_TAGS = {
    "bt709": "rec709",
    "smpte170m": "rec601",
    "bt2020": "rec2020",
    "smpte432": "p3-d65",
}


def run(argv: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(part) for part in argv], input=data, capture_output=True, check=False
    )


def encode(folder: Path, tag: str) -> int:
    """按那一格写法编一片纯色，返回 FFmpeg 的退出码（0 才算这个写法真能拼出来）。"""
    made = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xB45032:s=64x36:r=30:d=0.1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-color_primaries",
            tag,
            "-colorspace",
            "bt709",
            "-color_trc",
            "bt709",
            str(folder / f"prim-{tag}.mp4"),
        ]
    )
    return made.returncode


def read_back(folder: Path, tag: str) -> str | None:
    answer = run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=color_primaries",
            "-of",
            "json",
            str(folder / f"prim-{tag}.mp4"),
        ]
    )
    streams = json.loads(answer.stdout.decode(errors="replace")).get("streams") or [{}]
    return streams[0].get("color_primaries")


def tag_suite(folder: Path) -> dict[str, str]:
    """每一格写法真编一次、真探针一次，把三堆各自的成员钉住。"""
    landed: dict[str, str] = {}
    for tag in SPELLABLE:
        assert encode(folder, tag) == 0, f"{tag} 这一写法随包 FFmpeg 现在编不出来了——那张表要重新量"
        got = read_back(folder, tag)
        assert got == tag, f"{tag} 写进去读回来成了 {got!r}：容器那一格不能这么写"
        landed[tag] = got
    for tag in REFUSED:
        assert encode(folder, tag) != 0, (
            f"{tag} 现在被接受了——第一组那份「拒收」的账要重新量，别把没人认识的名字留在表里"
        )
    assert encode(folder, SILENT) == 0, "unknown 仍然应当编得出去"
    assert read_back(folder, SILENT) is None, (
        "unknown 这一格现在会落进文件：那句「没标记就是没说话」要重新量"
    )
    return landed


def curve_suite() -> tuple[float, float]:
    """同一个名字的两条曲线各自还在，而且它们的差是几十阶那种差。

    量两件事：`signal^2.4` 与 `bt709_eotf(signal)` 差多少（线性域，也就是那一级矩阵所假设的
    「线性光」到底是谁），以及把 2.4 那条抬上去的值交给 `bt709_oetf` 落回来还剩多少差（信号域——
    `[transfer, matrix, transfer]` 那一趟真正走的路径）。
    """
    linear_worst = max(
        abs(bt709_eotf(index / 255.0) - (index / 255.0) ** 2.4) * 255 for index in range(256)
    )
    signal_worst = max(
        abs(bt709_oetf((index / 255.0) ** 2.4) * 255 - index) for index in range(256)
    )
    assert GAMMA_BY_SPACE["rec709"] == 2.4, (
        "调色链那端不再用 2.4 了——这条分叉可能被统一，第二组的账要重新量"
    )
    assert linear_worst > 0.02, (
        f"gamut 那条 bt709 曲线与纯幂 2.4 只差 {linear_worst:.3f} 阶了：统一可能发生在这里，"
        "先重新量再改文档"
    )
    assert signal_worst > 20, f"两条曲线的差只剩 {signal_worst:.1f} 阶了？那分叉的代价要重新量"
    return signal_worst, linear_worst


def scope_suite() -> None:
    """那条自动折叠现在没有任何契约入口：不许半套上路。"""
    assert not hasattr(contracts, "COLOR_PRIMARIES_TAGS"), (
        "契约里出现了「读素材原色」那张表：先钉住曲线那一条（第 2 组），再让这一行跟着改口径"
    )
    assert "auto_primaries" not in contracts.ClipColorManage.model_fields, (
        "`clip.color_manage` 多了 auto_primaries 而曲线那条分叉还没解——每一段素材都会吃到那 29 阶"
    )


CELLS = [
    (200, 60, 40),
    (40, 180, 70),
    (70, 70, 200),
    (128, 128, 128),
    (225, 160, 30),
    (35, 120, 150),
    (165, 45, 160),
    (90, 95, 90),
]
PLATE_W, PLATE_H = 64, 36
TICK = 70_560_000


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def encode_plate(folder: Path, name: str, pixels: bytes) -> Path:
    path = folder / name
    made = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{PLATE_W}x{PLATE_H}",
            "-r",
            "30",
            "-i",
            "pipe:0",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-qp",
            "0",
            "-pix_fmt",
            "yuv444p",
            str(path),
        ],
        data=pixels,
    )
    assert made.returncode == 0, made.stderr[-300:].decode(errors="replace")
    return path


def authored_plates(folder: Path) -> tuple[Path, Path, int]:
    """同一批八格颜色，一份按 709 存、一份按 P3-D65 存；第三个数是两份存储值的最大差。"""
    ref = bytearray()
    for row in range(PLATE_H):
        for _ in range(PLATE_W):
            ref.extend(CELLS[row % len(CELLS)])
    forward = primaries_matrix("rec709", "p3-d65")
    stored = bytearray()
    for index in range(0, len(ref), 3):
        linear = [bt709_eotf(ref[index + channel] / 255.0) for channel in range(3)]
        moved = [
            sum(forward[row][column] * linear[column] for column in range(3)) for row in range(3)
        ]
        for channel in range(3):
            stored.append(round(clamp01(bt709_oetf(clamp01(moved[channel]))) * 255))
    gap = max(abs(a - b) for a, b in zip(bytes(stored), bytes(ref), strict=True))
    # 一帧只有 1/30 秒；两枚片段各要 1 秒，所以把那一帧铺满 30 帧再交编码。
    frames = bytes(ref) * 30, bytes(stored) * 30
    return (
        encode_plate(folder, "ref709.mp4", frames[0]),
        encode_plate(folder, "p3.mp4", frames[1]),
        gap,
    )


def frame(path: Path, at: float) -> bytes:
    probe = path.with_suffix(f".{int(at * 1000)}.rgb")
    made = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            str(at),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            str(probe),
        ]
    )
    assert made.returncode == 0, made.stderr[-400:].decode(errors="replace")
    data = probe.read_bytes()
    probe.unlink()
    return data


def cell_at(data: bytes, row: int) -> tuple[int, int, int]:
    index = (row * PLATE_W + 32) * 3
    return data[index], data[index + 1], data[index + 2]


def worst_between(a: bytes, b: bytes) -> int:
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def landing_suite() -> tuple[int, int, int]:
    """把 1.158 那颗按钮的落点量成门禁：折了之后还差多少阶。

    一条画面轨两枚片段：`c0` 是 709 那枚、不套任何东西（它就是基准），`c1` 是同一批颜色按 P3-D65
    存的那枚，套上 `[transfer, matrix, transfer]`——中间那九个数就是 `gamut.primaries_matrix`。
    两份都交 ProRes 4444（4:4:4，先把色度抽样这条干扰摘掉），再逐格读像素。
    """
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        ref_plate, p3_plate, authored_gap = authored_plates(folder)
        assert authored_gap >= 20, f"两份夹具的存储值只差 {authored_gap} 阶——那对夹具是假的"
        cache = folder / "cache"
        media = MediaService(folder / "pm-media.sqlite3", [folder], cache, FFMPEG, FFPROBE)
        exports = folder / "out"
        exports.mkdir()
        db = folder / "pm.sqlite3"
        runtime = JobRuntime(db, FFMPEG, exports, [exports, folder])
        token = "l" * 48
        app = create_app(db, token, media=media, jobs=runtime)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            probes = {
                key: client.post("/v1/media/import", json={"path": str(plate)}).json()
                for key, plate in (("ref", ref_plate), ("p3", p3_plate))
            }
            made = client.post(
                "/v1/projects",
                json={
                    "request_id": "pm-new",
                    "name": "折叠落点",
                    "settings": {
                        "width": PLATE_W,
                        "height": PLATE_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            pid = made["id"]
            head = {
                "kind": "transfer",
                "input_space": "rec709",
                "output_space": "linear",
                "enabled": True,
                "purpose": "color_manage",
            }
            tail = {
                "kind": "transfer",
                "input_space": "linear",
                "output_space": "rec709",
                "enabled": True,
                "purpose": "color_manage",
            }
            nine = [round(v, 6) for row in primaries_matrix("p3-d65", "rec709") for v in row]
            commands = [{"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}}]
            for index, key in enumerate(("ref", "p3")):
                commands += [
                    {
                        "op": "asset.import",
                        "asset_id": f"a{index}",
                        "label": key,
                        "probe_id": probes[key]["id"],
                        "verified": probes[key]["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": f"c{index}",
                            "asset_id": f"a{index}",
                            "track_id": "v",
                            "position_ticks": index * TICK,
                            "duration_ticks": TICK,
                        },
                    },
                ]
            commands.append(
                {
                    "op": "clip.color",
                    "clip_id": "c1",
                    "color": {
                        "exposure": 0.0,
                        "grade": [
                            head,
                            {"kind": "matrix", "coefficients": nine, "enabled": True},
                            tail,
                        ],
                    },
                }
            )
            seeded = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "pm-seed",
                    "expected_revision": made["revision"],
                    "commands": commands,
                },
            )
            assert seeded.status_code == 200, seeded.text
            revision = seeded.json()["project"]["revision"]
            files: dict[str, Path] = {}
            for mode, request in (("fold", "pm-fold"), ("plain", "pm-plain")):
                if mode == "plain":
                    cleared = client.post(
                        f"/v1/projects/{pid}/edits",
                        json={
                            "request_id": "pm-strip",
                            "expected_revision": revision,
                            "commands": [
                                {
                                    "op": "clip.color",
                                    "clip_id": "c1",
                                    "color": {"exposure": 0.0, "grade": []},
                                }
                            ],
                        },
                    )
                    assert cleared.status_code == 200, cleared.text
                    revision = cleared.json()["project"]["revision"]
                job = client.post(
                    f"/v1/projects/{pid}/renders",
                    json={
                        "request_id": request,
                        "expected_revision": revision,
                        "preset_id": "prores-4444-alpha",
                        "filename": f"{mode}.mov",
                    },
                ).json()["job"]
                state = job
                for _ in range(240):
                    state = client.get(f"/v1/jobs/{job['id']}").json()["job"]
                    if state["status"] in ("succeeded", "failed"):
                        break
                    time.sleep(0.5)
                assert state["status"] == "succeeded", state
                files[mode] = Path(state["output_path"])
            reference = frame(files["fold"], 0.4)
            folded = frame(files["fold"], 1.4)
            unfolded = frame(files["plain"], 1.4)
            fold_error = max(
                abs(a - b)
                for row in range(len(CELLS))
                for a, b in zip(cell_at(folded, row * 4), cell_at(reference, row * 4), strict=True)
            )
            unfold_error = worst_between(unfolded, reference)
    assert fold_error < unfold_error, (
        f"折了({fold_error})比不折({unfold_error})还差：那颗按钮做的不是换基色，整条路要重新查"
    )
    assert authored_gap >= 20 and unfold_error >= authored_gap - 8, (
        f"基准与未折那一份只差 {unfold_error} 阶（夹具自己差 {authored_gap}）：这一测的对照不成立了"
    )
    assert 20 <= fold_error <= 40, (
        f"折叠落点现在差 {fold_error} 阶，不在记档的那一段（20..40）里：那条同名两档曲线的分叉"
        "被动过了——重量一遍，把 1.151/1.152/1.156 那三批交付实测与 1.159 那两级预览表一起重新对表，"
        "别把这里的区间放宽了事"
    )
    return fold_error, unfold_error, authored_gap


def main() -> None:
    for name in ("rec709", "rec601", "rec2020", "p3-d65"):
        assert name in PRIMARIES, f"引擎不再认识 {name}：那四行对应关系要重新量"
    for tag, name in MEASURED_TAGS.items():
        assert tag in SPELLABLE, f"{tag} 不在可拼那一堆里：那张对应表不能留着它"
        assert name in PRIMARIES, f"{name} 不在原色表里：{tag} 那一行没有落点"
    with tempfile.TemporaryDirectory() as scratch:
        landed = tag_suite(Path(scratch))
    scope_suite()
    fold_error, unfold_error, authored_gap = landing_suite()
    signal_worst, linear_worst = curve_suite()
    print(
        f"   容器那一格：{len(landed)} 种写法写进去读回来同名、{len(REFUSED)} 种当场拒收、"
        f"{SILENT} 写了等于没写"
    )
    print(
        f"   同一个 rec709 的两条曲线：信号域最坏差 {signal_worst:.1f} 阶、线性域最坏差 "
        f"{linear_worst:.3f} 阶（2.4 幂 vs 分段 0.45）"
    )
    print(
        f"   那条按钮的落点：夹具两份存储值差 {authored_gap} 阶，未折时与基准差 {unfold_error} 阶，"
        f"折了之后仍差 {fold_error} 阶——分叉还在，所以那条自动折叠没有契约入口"
    )
    print(
        "PASS: 基色那一格的词表由随包 FFmpeg 当场编过也探针过；同名两档曲线那条分叉仍在且差在几十阶"
        "量级，「读素材自己声明的原色就折」这条自动路还没有契约入口——先解曲线，再谈那一档"
    )


if __name__ == "__main__":
    main()
