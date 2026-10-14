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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentcut import contracts  # noqa: E402
from agentcut.gamut import PRIMARIES, bt709_eotf, bt709_oetf  # noqa: E402
from agentcut.grade import GAMMA_BY_SPACE  # noqa: E402

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


def run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(part) for part in argv], capture_output=True, check=False)


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


def main() -> None:
    for name in ("rec709", "rec601", "rec2020", "p3-d65"):
        assert name in PRIMARIES, f"引擎不再认识 {name}：那四行对应关系要重新量"
    for tag, name in MEASURED_TAGS.items():
        assert tag in SPELLABLE, f"{tag} 不在可拼那一堆里：那张对应表不能留着它"
        assert name in PRIMARIES, f"{name} 不在原色表里：{tag} 那一行没有落点"
    with tempfile.TemporaryDirectory() as scratch:
        landed = tag_suite(Path(scratch))
    signal_worst, linear_worst = curve_suite()
    scope_suite()
    print(
        f"   容器那一格：{len(landed)} 种写法写进去读回来同名、{len(REFUSED)} 种当场拒收、"
        f"{SILENT} 写了等于没写"
    )
    print(
        f"   同一个 rec709 的两条曲线：信号域最坏差 {signal_worst:.1f} 阶、线性域最坏差 "
        f"{linear_worst:.3f} 阶（2.4 幂 vs 分段 0.45）"
    )
    print(
        "PASS: 基色那一格的词表由随包 FFmpeg 当场编过也探针过；同名两档曲线那条分叉仍在且差在几十阶"
        "量级，所以「读素材自己声明的原色就折」这条自动路还没有契约入口——先解曲线，再谈那一档"
    )


if __name__ == "__main__":
    main()
