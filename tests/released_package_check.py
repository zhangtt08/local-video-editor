"""The Windows package is a deliverable, so the artifact itself gets checked, not just the sources.

Every other gate in this suite reads the source tree. None of them can see the thing a person
double-clicks: `AgentCut.exe`, the `app.asar` inside it, and the frozen engine binary that ships
beside it. Twice the release chain was interrupted between a source edit and the rebuild, leaving a
package that *predates* the claim made about it — a stale `AgentCut.exe` next to fresh sources looks
perfectly green to every other check in this directory.

So this check reads the shipped bytes:

1. the root `AgentCut.exe` must be byte-for-byte the portable build in `desktop/release/`, because
   the docs promise that double-clicking either one runs the same thing;
2. the `app.asar` inside `win-unpacked` must carry the same version the contracts carry — the asar
   was packed from sources that already had the new version in `package.json`, so a mismatch means
   the package was not rebuilt after the bump;
3. the engine binary the app launches must be byte-identical to the one the app's own resource tree
   stages, and it must be the one the build script froze;
4. the renderer bundle inside that asar must contain the sentences a person actually reads. Strings
   survive minification; identifiers do not, so the assertions are all on visible Chinese text.

Nothing here is skipped quietly: if the artifacts are missing the gate names the two commands that
produce them. A "skip" that lets a release go out unverified is the failure mode this file exists to
prevent.
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
DESKTOP = ROOT / "desktop"
RELEASE = DESKTOP / "release"
ROOT_EXE = ROOT / "AgentCut.exe"
PORTABLE = RELEASE / "AgentCut-便携版.exe"
UNPACKED = RELEASE / "win-unpacked"
ASAR = UNPACKED / "resources/app.asar"
STAGED_ENGINE = DESKTOP / "resources/bin/agentcut/agentcut.exe"
SHIPPED_ENGINE = UNPACKED / "resources/bin/agentcut/agentcut.exe"

# Read from the built artifact, in the shipped person's own words. An identifier renamed by the
# bundler would prove nothing, so none of these are identifiers.
RENDERER_SENTENCES = (
    "套上色彩管理",
    "取下色彩管理",
    "素材从哪里读",
    "交付按什么输出",
    "色彩管理套叠",
    "两端都选了线性：这一对什么都不转",
    " 个盖过章的转换节点，不成一对",  # a template literal ships as its static parts
    # 1.136：透明母版在人眼前就是这三句话——那个勾、它灰掉时的出路、以及引擎拒绝后的中文说明。
    "背景透明",
    "空白处留透明",
    "装不下透明度",
    "ProRes 4444 透明母版",
    # 1.138：交付帧率在人眼前就是这一栏、这一句出路，以及「不选」的原话。
    "交付帧率",
    "跟时间线",
    "就是时间线那一档",
    "可交的帧率是引擎那张闭表",
    # 1.140：时间码那把尺要说清是哪一条交付的画面。
    "这一条交付画面的帧率",
    "是你选的交付率",
    # 1.142：图像序列在人眼前要说清三件事——交出的是一串文件、声音不在里面、时间码进不去。
    "每帧一个文件",
    "声音不在里面",
    "这一栏不起作用",
    "帧号就是位置",
)
RENDERER_LITERALS = (
    "clip.color_manage",
    '"color_manage"',
    # The code the desktop must translate, still present as the key it is looked up by.
    "TRANSPARENT_NEEDS_ALPHA",
    "UNKNOWN_OUTPUT_RATE",
    "OUTPUT_RATE_NEEDS_PICTURE",
    "SEQUENCE_NEEDS_CONTAINER",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(path: Path, how: str) -> None:
    if not path.exists():
        raise SystemExit(f"FAIL: {path} is missing — {how}")


def asar_entries(data: bytes) -> tuple[int, dict[str, tuple[int, int]]]:
    """Parse the asar header: returns where the file data starts and every file's (size, offset).

    A corrupt or unexpectedly-shaped header is reported as that, rather than as a traceback from the
    JSON decoder: the artifact being unreadable is itself the finding this gate exists to surface.
    """
    block = struct.unpack("<I", data[4:8])[0]
    text = struct.unpack("<I", data[12:16])[0]
    try:
        header = json.loads(data[16 : 16 + text].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(
            f"app.asar no longer parses as the layout this check reads: {error}"
        ) from error
    found: dict[str, tuple[int, int]] = {}

    def walk(node: dict, prefix: str) -> None:
        for name, item in node.get("files", {}).items():
            path = f"{prefix}/{name}"
            if "files" in item:
                walk(item, path)
            else:
                found[path] = (int(item["size"]), int(item["offset"]))

    walk(header, "")
    return 8 + block, found


def main() -> None:
    build = "`cd desktop && npm run dist`"
    engine = "`uv run python scripts/build_engine.py --verify`"
    for path, how in (
        (PORTABLE, build),
        (ROOT_EXE, f"then copy the portable build to the project root: `cp {PORTABLE} {ROOT_EXE}`"),
        (ASAR, build),
        (STAGED_ENGINE, engine),
        (SHIPPED_ENGINE, build),
    ):
        require(path, how)

    assert digest(ROOT_EXE) == digest(PORTABLE), (
        "AgentCut.exe is not the portable build it should be"
    )

    data = ASAR.read_bytes()
    base, files = asar_entries(data)
    size, offset = files["/package.json"]
    try:
        packed = json.loads(data[base + offset : base + offset + size].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(
            f"the /package.json inside app.asar is not readable at the offset its header claims "
            f"(data starts at {base}): {error}"
        ) from error

    sys.path.insert(0, str(ROOT / "src"))
    from agentcut.contracts import APP_VERSION

    assert packed["version"] == APP_VERSION, (packed["version"], APP_VERSION)

    assert digest(STAGED_ENGINE) == digest(SHIPPED_ENGINE), (
        "the app ships a different engine than the one built"
    )

    bundles = sorted(
        path for path in files if path.startswith("/dist/renderer/assets/") and path.endswith(".js")
    )
    assert bundles, sorted(files)[:8]
    body = ""
    for path in bundles:
        size, offset = files[path]
        body += data[base + offset : base + offset + size].decode("utf-8", errors="replace")
    for sentence in RENDERER_SENTENCES:
        assert sentence in body, f"the shipped renderer never says: {sentence}"
    for literal in RENDERER_LITERALS:
        assert literal in body, f"the shipped renderer never carries: {literal}"
    assert "待补" not in body, "the shipped renderer still says 'not measured yet'"

    main_js = files.get("/dist-electron/main.js")
    assert main_js, sorted(files)[:8]
    size, offset = main_js
    shell = data[base + offset : base + offset + size].decode("utf-8", errors="replace")
    assert "engine" in shell and "token" in shell, (
        "the desktop shell no longer knows how to start an engine"
    )

    print(
        f"PASS: AgentCut.exe == portable build, app.asar carries {APP_VERSION} with {len(files)}"
        " files, the shipped engine is the built one, and the renderer says"
        f" {len(RENDERER_SENTENCES)} sentences a person can read"
    )


if __name__ == "__main__":
    main()
