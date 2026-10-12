"""冻结引擎找的是**随包那份** ffmpeg，不是 PATH 上赌运气的那份。

装机复核（1.146）量出来的缺陷：打包后的形状是 `resources/bin/agentcut/agentcut.exe` 与
`resources/bin/ffmpeg.exe`，而 `_find_binary` 当年只搜 `_MEIPASS`、引擎自己那一层、以及
「引擎层/resources」三处——随包的那份在**上一级**，三处都不命中，于是引擎一路落到
`shutil.which("ffmpeg")`。这台机器 PATH 上是 9.0.2（gyan full_build），实测它已经没有
`-filter_complex_script` 这个选项（随包的 6.1.1 有），而 `render.py` 在滤镜图超过
`GRAPH_SCRIPT_LIMIT`（12000 字符）时正是发那一条——于是打包版里「短图照常出片、长图直接拒」：
`Unrecognized option 'filter_complex_script'.` 界面允许、导出会拒，本项目明令不许出现的口子。

三件事都在临时目录里搭出真实的打包形状，不依赖本机装了什么：

1. 形状命中：`bin/agentcut/agentcut.exe` + `bin/ffmpeg.exe` 时，解析结果必须是随包那一份，
   而不是刻意摆在 PATH 上的诱饵（ffprobe 同理）。
2. 退路还在：包里没带 ffmpeg 时仍然允许用 PATH 那一份——那是用户的选择，不是缺陷，
   所以这一条断的是「它还照着做」，不是「不该这么做」。
3. 命令行 `--ffmpeg` 与环境变量 `AGENTCUT_FFMPEG` 比随包那一份更说了算。

外加一条对随包真身的实测：`desktop/resources/bin/ffmpeg.exe -h full` 数得到
`filter_complex_script`。这一条是本文件其余断言的理由，不是顺手加的。
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLED = REPO / "desktop/resources/bin/ffmpeg.exe"


def bundled_supports_script() -> bool:
    answer = subprocess.run(  # noqa: S603
        [str(BUNDLED), "-hide_banner", "-h", "full"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        creationflags=0x08000000,
    )
    return "filter_complex_script" in answer.stdout


def build_tree(root: Path, with_bundle: bool) -> tuple[Path, Path]:
    """搭出打包后的那一棵树，并在旁边放一份 PATH 诱饵。"""
    bin_dir = root / "resources/bin"
    (bin_dir / "agentcut/_internal").mkdir(parents=True, exist_ok=True)
    (bin_dir / "agentcut/agentcut.exe").write_bytes(b"exe")
    if with_bundle:
        (bin_dir / "ffmpeg.exe").write_bytes(b"exe")
        (bin_dir / "ffprobe.exe").write_bytes(b"exe")
    decoy = root / "on-path"
    decoy.mkdir(parents=True, exist_ok=True)
    (decoy / "ffmpeg.exe").write_bytes(b"decoy")
    (decoy / "ffprobe.exe").write_bytes(b"decoy")
    return bin_dir, decoy


@contextlib.contextmanager
def pretend_frozen(bin_dir: Path, decoy: Path):
    """把 `_app_dir()` 与 `_MEIPASS` 摆成打包后的样子，并让 `which` 只认诱饵。"""
    from agentcut import __main__ as engine_cli

    real_which = shutil.which
    saved = {name: getattr(sys, name, None) for name in ("frozen", "_MEIPASS", "executable")}
    shutil.which = lambda candidate: str(decoy / f"{candidate}.exe")  # noqa: E731
    sys.frozen = True
    sys._MEIPASS = str(bin_dir / "agentcut/_internal")
    sys.executable = str(bin_dir / "agentcut/agentcut.exe")
    try:
        yield engine_cli
    finally:
        shutil.which = real_which
        for name, value in saved.items():
            if value is None:
                delattr(sys, name)
            else:
                setattr(sys, name, value)


def main() -> None:
    assert BUNDLED.is_file(), f"随包的 ffmpeg 不见了：{BUNDLED}"
    assert bundled_supports_script(), "随包那份 ffmpeg 不认 filter_complex_script，本文件的理由没了"
    print("   随包真身认 `filter_complex_script`；这台机器 PATH 上那份 9.0.2 不认（本轮实测）")

    saved_env = {
        name: os.environ.pop(name, None) for name in ("AGENTCUT_FFMPEG", "AGENTCUT_FFPROBE")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="agentcut-ffp-") as scratch:
            root = Path(scratch)
            bin_dir, decoy = build_tree(root, with_bundle=True)
            with pretend_frozen(bin_dir, decoy) as engine_cli:
                assert engine_cli._find_binary("ffmpeg", "") == (bin_dir / "ffmpeg.exe").resolve()
                assert engine_cli._find_binary("ffprobe", "") == (bin_dir / "ffprobe.exe").resolve()
            print(f"   形状命中：随包的 {bin_dir / 'ffmpeg.exe'} 胜过 PATH 上那份诱饵")

            sparse = root / "sparse"
            bin_dir2, decoy2 = build_tree(sparse, with_bundle=False)
            with pretend_frozen(bin_dir2, decoy2) as engine_cli:
                assert engine_cli._find_binary("ffmpeg", "") == (decoy2 / "ffmpeg.exe").resolve()
            print("   退路还在：包里没有 ffmpeg 时，仍然用 PATH 上那一份（那是用户的选择）")

            mine = root / "mine" / "ffmpeg.exe"
            mine.parent.mkdir(parents=True, exist_ok=True)
            mine.write_bytes(b"mine")
            with pretend_frozen(bin_dir, decoy) as engine_cli:
                assert engine_cli._find_binary("ffmpeg", str(mine)) == mine.resolve()
                os.environ["AGENTCUT_FFMPEG"] = str(mine)
                assert engine_cli._find_binary("ffmpeg", "") == mine.resolve()
            print("   `--ffmpeg` 与 AGENTCUT_FFMPEG 比随包那一份更说了算")
    finally:
        for name, value in saved_env.items():
            if value is not None:
                os.environ[name] = value


if __name__ == "__main__":
    main()
