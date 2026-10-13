"""验收套件自己不许认识这台机器，也不许用第二份 FFmpeg。

1.152 之前有两处真缺陷，都属于「门禁全绿但交付不可复现」：

- 61 个 Python 检查与 10 个壳层检查把这台机器的绝对路径写死，工程一挪位置，整套验收当场全红；
- 14 处直接指随包目录之外的 FFmpeg（npm 装来的那一份），另有几处把 PATH 当兜底。清掉那一份
  之后，这些检查要么当场跑不起来（WinError 2），要么静默改用 PATH 上那一支（本机 PATH 上
  是 FFmpeg 9），于是「验收测的就是发布包里那支 FFmpeg 的行为」这句话没有依据。

随包的两支在 desktop/resources/bin 那一层，装机版内嵌的就是它们，所以验收也只准用它们。本
文件自己在被扫之列，因此下面那些「禁止出现的字面量」全部由字符拼出来，源码里不留原文。
"""

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "desktop" / "resources" / "bin"

SEP = chr(47)  # 正斜杠
BS = chr(92)  # 反斜杠
DASH = chr(45)
DOT = chr(46)

# 任何形式的「某个用户的主目录」都不许写进可执行源码——换一台机器它同样不该认识。
USER_MARKERS = (f":{BS}Users{BS}", f":{SEP}Users{SEP}", f":{BS}users{BS}", f":{SEP}users{SEP}")
NPM_MARKERS = (f"ffmpeg{DASH}static", f"ffprobe{DASH}static")
MEDIA_TOKENS = (f"ffmpeg{DOT}exe", f"ffprobe{DOT}exe")
BIN_PREFIX = f"desktop{SEP}resources{SEP}bin{SEP}"
DESKTOP_DIR = f"desktop{SEP}"


def executable_sources() -> list[Path]:
    """可执行的验收与产品源码。文档由 docs_shape_check 管，不在本条门禁的话事范围。"""
    found: list[Path] = []
    found += sorted((ROOT / "tests").glob("*.py"))
    found += sorted((ROOT / "tests").glob("*.ts"))
    found += sorted((ROOT / "src" / "agentcut").glob("*.py"))
    found += sorted((ROOT / "scripts").glob("*.py"))
    found += sorted((ROOT / "desktop" / "src").rglob("*.ts"))
    found += sorted((ROOT / "desktop" / "src").rglob("*.tsx"))
    found += sorted((ROOT / "desktop" / "electron").glob("*.ts"))
    assert len(found) > 80, f"扫到的可执行源码只有 {len(found)} 个，扫描面自己缩了就是门禁空了"
    return found


def tree(path: Path) -> ast.Module:
    return ast.parse(path.open(encoding="utf-8", errors="replace").read(), filename=str(path))


def dotted(node: ast.expr) -> str:
    """把 `shutil.which` 这类点号写法拼回一个字符串，好判后缀。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def constants(module: ast.Module) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(module):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((getattr(node, "lineno", 0), node.value))
    return found


def bundled_binaries() -> dict[str, str]:
    """真跑一次随包的那两支，把版本首行原样带回来，不只是「文件在不在」。"""
    banner: dict[str, str] = {}
    for name in ("ffmpeg", "ffprobe"):
        path = BIN_DIR / f"{name}.exe"
        assert path.is_file(), (
            f"随包 {name} 不在 {path}：媒体验收没有可跑的 FFmpeg。"
            "装机版内嵌的就是这一支，先执行 npm ci 与 scripts/build_engine.py"
        )
        done = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        assert done.returncode == 0, f"{path} 跑 -version 退出码 {done.returncode}"
        head = (done.stdout or done.stderr or "").splitlines()
        first = head[0].strip() if head else ""
        verb = f"{name} version"
        assert first.lower().startswith(verb), f"{path} 的 -version 首行不是版本行：{first!r}"
        banner[name] = first
    return banner


def user_paths(files: list[Path]) -> list[str]:
    hits = []
    for path in files:
        text = path.open(encoding="utf-8", errors="replace").read()
        for marker in USER_MARKERS:
            if marker in text:
                line = 1 + text[: text.index(marker)].count("\n")
                hits.append(f"{path.relative_to(ROOT)}:{line} 写死了某个用户的主目录")
    return hits


def second_ffmpeg(checks: list[Path]) -> list[str]:
    """按语法树判，不按文字判。

    `tests/ffmpegpath_check.py` 要在临时目录里搭出打包形状、把诱饵摆上 PATH，才证得动引擎自己的
    搜索顺序，那是产品行为的一条证据。被禁的是验收**自己去 PATH 或 npm 那一份取媒体程序**来跑，
    所以这里只认两种写法：调用 `which(…)`（参数是字面量还是变量都算），以及字符串常量里出现
    npm 的那两份。
    """
    hits = []
    for path in checks:
        module = tree(path)
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and dotted(node.func).endswith("which"):
                name = dotted(node.func)
                hits.append(f"{path.relative_to(ROOT)}:{node.lineno} 从 PATH 找媒体程序（{name}）")
        for line, value in constants(module):
            for marker in NPM_MARKERS:
                if marker in value:
                    hits.append(
                        f"{path.relative_to(ROOT)}:{line} 从随包目录之外取 FFmpeg（{marker}）"
                    )
    return hits


def stray_media_paths(checks: list[Path]) -> list[str]:
    """写出来的 desktop/…媒体程序路径必须落在随包那一层，别处一律算第二份 FFmpeg。"""
    hits = []
    for path in checks:
        for line, value in constants(tree(path)):
            if DESKTOP_DIR not in value:
                continue
            tail = value[value.index(DESKTOP_DIR) :]
            if any(token in tail for token in MEDIA_TOKENS) and not tail.startswith(BIN_PREFIX):
                hits.append(f"{path.relative_to(ROOT)}:{line} 指向随包之外的媒体程序：{tail[:60]}")
    return hits


STAMP_FILE = f"media{DASH}stamp{DOT}json"
STATIC_PREFIX = f"desktop{SEP}node_modules{SEP}"


def media_identity(banner: dict) -> list[str]:
    """随包那两支 FFmpeg 的身份，由构建时留下的那张戳说话。

    本轮量到的缺陷：`scripts/build_engine.py` 在 `desktop/node_modules` 被清掉的时候，会从
    `C:/ffmpeg/bin` 或 PATH 拿一支顶上——`--verify` 照常绿，而装机的包里换成了本机 winget 的
    9.0.2 full build。文档里每一个 zscale 与折叠的实测数都是随包 6.1.1 量的，所以「发布包里的
    媒体程序就是验收量的那支」必须由字节与版本行来判，而不是由构建脚本的礼貌退路来保证。
    """
    stamp_path = BIN_DIR / STAMP_FILE
    if not stamp_path.is_file():
        return [
            f"随包目录没有 {STAMP_FILE}：那两支的身份没人记过，包里是什么全看装机器碰巧有什么"
        ]
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for kind in ("ffmpeg", "ffprobe"):
        row = stamp.get(kind)
        if row is None:
            hits.append(f"戳里没有 {kind} 那一行")
            continue
        exe = BIN_DIR / f"{kind}.exe"
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            hits.append(
                f"{kind}.exe 的字节与戳不符：现在 {digest[:12]}…，戳记的是 {row['sha256'][:12]}…"
                "（换过 exe 却没重跑构建）"
            )
        line = str(banner[kind])
        if line.split()[2] != str(row["version_line"]).split()[2]:
            hits.append(f"{kind}.exe 的版本行与戳不符：{line!r} 对 {row['version_line']!r}")
        source = str(row["source"]).replace(BS, SEP)
        if not source.startswith(STATIC_PREFIX):
            hits.append(
                f"戳记的来源不在静态包那一层，而是 {source!r}——那是一支碰巧装在这台机器上的媒体程序"
            )
    return hits


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    files = executable_sources()
    checks = [path for path in files if path.suffix == ".py" and path.parent.name == "tests"]
    banner = bundled_binaries()
    print(f"    随包 FFmpeg：{banner['ffmpeg']}")
    print(f"    随包 FFprobe：{banner['ffprobe']}")
    for label, hits in (
        ("本机用户目录路径", user_paths(files)),
        ("随包目录之外的 FFmpeg", second_ffmpeg(checks)),
        ("随包目录之外的媒体程序路径", stray_media_paths(checks)),
        ("随包媒体程序与那张身份戳", media_identity(banner)),
    ):
        assert not hits, f"{label}没被拦住：\n  " + "\n  ".join(hits)
    print(
        f"PASS: {len(files)} 个可执行源码既不认这台机器，也不用第二份 FFmpeg"
        f"（随包两支 {banner['ffmpeg'].split()[2]} 与 {banner['ffprobe'].split()[2]}，"
        f"其中 {len(checks)} 个验收受媒体程序那两条规矩约束）"
    )


if __name__ == "__main__":
    main()
