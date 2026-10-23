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

ROOT = Path(__file__).resolve().parent.parent
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
    # 1.276：色度键在人眼前就是这四句——挂上、看遮罩、摘掉，以及画不出来时那一句实话。
    "挂上抠像",
    "看遮罩",
    "摘掉键",
    "预览画不出这个色度键",
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
    # 1.163「粘贴属性」在人眼前就是这两颗按钮与那一句来源说明。
    "复制属性",
    "粘贴属性",
    "还没有复制过属性",
    # 1.164「遮罩可旋转」在人眼前就是这一格、那两句出路，以及那张等比图的类名。
    "遮罩角度",
    "这一版引擎没有遮罩角度这一格",
    "宽/高那两条也一样能打",
    "mask_rotation_size_curves",
    "转过角度的遮罩盒",
    "检查器·遮罩角度",
    "rotated-mask",
    "mask_rotation_limit",
    # 1.165：那颗 ◇ 的两个名字、画面下方那句「此刻吃哪一窗」，以及那份窗表的 key。
    "删除遮罩角度关键帧",
    "添加遮罩角度关键帧",
    "这一格的角度是",
    "mask_rotation_windows",
    "按帧对齐的阶梯",
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
    # 1.143：这三句不能只在悬停里（Field 的 hint 只写进 title），面板上要有一行看得见的字。
    "起始时间码也进不去",
    "请再交一份 mp4／mov",
    # 1.144：第二路画面输入在人眼前是名字、是两个控件、也是一句明说的差别。
    "叠一层原图",
    "与原图相合的方式",
    "这一层的权重",
    # 1.193：这一级的「差别」换成两句各自属实的——图像那一段监视器会画，视频那一段还不画。
    # 1.234：立方表也能预览了，面板上那句换成「同一张表 + 什么时候只在导出里生效」。
    "监视器现在会画",
    "视频素材那一段暂停与逐帧时会画",
    "播放中这一级不画",
    "预览与导出读同一张表",
    "只在导出里生效",
    # 1.194：窗口矮到时间线让不动了，这一句必须看得见（1.191 明留的那句「还没做」）。
    "已经让到这一屏的下限",
    # 1.212：层针跨片段搬。钉四句：判断本身（照搬不重折）、明说的那个差别（两边不是同一个画面）、
    # 缺额度时那句拒绝、以及粘不动时点名的那两个下拉。
    # 模板字面量在包里存的是它的静态那几段，所以钉的是段、不是整句。
    "层那个数照搬过去、没有重折",
    "层不是同一个画面",
    "引擎没报那一层的针数额度",
    "跟当前这一行不是同一条曲线",
    # 1.242：再叠遮罩的那几块在条上与检查器里各有一句实话——顶边那排小点是什么、每一块怎么动、
    # 以及框点与「跟着主遮罩」谁说了算。模板字面量只钉它静态的那两段。
    "自己走 · ",
    " 枚框点",
    "跟随主遮罩",
    "再叠的这几块与主遮罩取交集",
    "打了框点的块走自己的窗，勾这里不会删掉那些框点",
    "条顶上那排小点就是这些框点的时间",
    # 1.243：停在框点那一帧时，卡片上那五个数改的是哪一枚——三句各自说清一种状态，
    # 灰掉的那颗按钮也得把出路写在眼前。
    "这一帧已有框点",
    " 个数改的是这一枚",
    " 个数是模板值",
    "播放头正停在一枚框点上",
    # 1.244：框点越尾时那句自己的话——不能套用曲线针那句「仍在工程里」。
    "枚再叠遮罩的框点落在那段自己的长度之外——没有搬过来（框点不能停在段尾之后）",
    # 1.257：框点选了贝塞尔，眼前就得有那四格——名字与那句「写回的仍是同一条命令」是
    # 人与 Agent 共用的说法，藏在悬停里等于没有。
    "这一枚框点到下一枚之间按贝塞尔走",
    "出点数值",
    "入点时间",
    # 1.258：打点那颗按钮把「记的是哪几个数」写在眼前——软边现在也在这一串里。
    "中心、大小、角度与软边",
    "遮罩羽化",
)
RENDERER_LITERALS = (
    "clip.color_manage",
    '"color_manage"',
    # The code the desktop must translate, still present as the key it is looked up by.
    "TRANSPARENT_NEEDS_ALPHA",
    "UNKNOWN_OUTPUT_RATE",
    "OUTPUT_RATE_NEEDS_PICTURE",
    "SEQUENCE_NEEDS_CONTAINER",
    "COMPOSITE_LIMIT",
    "attribute-plan",
    "attribute_categories",
    "ATTRIBUTE_PASTE_LIMIT",
    "mask-stack-bezier",
    # 1.276：那条命令、那句中文提示与那两个默认值的键名——包里那份必须还认得。
    "clip.chroma",
    "INVALID_CHROMA",
    "chroma_similarity_default",
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

    for media in ("ffmpeg.exe", "ffprobe.exe"):
        staged_media = DESKTOP / f"resources/bin/{media}"
        shipped_media = UNPACKED / f"resources/bin/{media}"
        require(staged_media, engine)
        require(shipped_media, build)
        assert digest(staged_media) == digest(shipped_media), (
            f"the package ships a different {media} than the one staged beside the engine"
        )

    assert digest(STAGED_ENGINE) == digest(SHIPPED_ENGINE), (
        "the app ships a different engine than the one built"
    )

    # 1.163 装机复核抓到的一类空交付：`stage_asr_models()` 找不到模型时只打一行 step 就继续，
    # 于是 `npm run dist` 照常绿、包里的引擎自报 `speech_captions=false`，而 README 那句
    # 「自动语音字幕」成了空话。这一条把「随包的语音模型」钉成与暂存那一份同一堆，且不许为空。
    staged_asr = DESKTOP / "resources/bin/agentcut/asr"
    shipped_asr = UNPACKED / "resources/bin/agentcut/asr"
    require(staged_asr, engine)
    require(shipped_asr, build)
    complete = sorted(
        model.name
        for model in staged_asr.iterdir()
        if (model / "am").is_dir() and (model / "graph").is_dir()
    )
    assert complete, f"{staged_asr} 里没有一份完整的语音模型（要 `am` 与 `graph` 两个目录）"
    shipped_names = sorted(item.name for item in shipped_asr.iterdir() if item.is_dir())
    assert shipped_names == complete, (
        f"包里那几份模型与暂存的那几份不是同一堆：{shipped_names} vs {complete}"
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
    # 1.242：这句话在 1.237/1.238 之后就是假话（框点与跟随都能让那几块动起来）。源码里由
    # desktop_maskstack_check 钉着它不许回来；这里钉的是**装进包的那一份**里也没有它——
    # 一句过时的实话比没有句子更坏，因为它会替一条已经不存在的限制做主。
    assert "只切不动" not in body, "the shipped renderer still says the extra masks never move"
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
        f"，随包的语音模型 {len(complete)} 份与暂存那一堆同名"
    )


if __name__ == "__main__":
    main()
