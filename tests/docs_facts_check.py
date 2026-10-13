"""README prints numbers. This file checks every one of them against the table it came from.

The delivery defect this exists for was real and sat in plain sight: README's boundary section
still said "three containers with video, no MXF/DPX post formats yet" long after MXF (1.129) and
OpenEXR/DPX sequences (1.142) shipped, and still said "six keyframed properties" after the mask
box, blur and sharpen joined them. A stale doc is a lie about the product, and nothing in the
suite could notice, because prose is not an assertion target.

So the rule here is narrow on purpose: no count or container list may live in README unless the
engine's own table agrees with it, read at check time.

* every id in ``contracts.OUTPUT_CONTAINERS`` must be named in the export-preset bullet;
* the property/blend counts README states (Chinese numeral or digits) must equal the Literal's
  member count, matched per named type within its own sentence;
* the schema version README states must equal ``contracts.SCHEMA_VERSION``;
* retired false literals may not come back (checked verbatim).

Mutation-tested: dropping a container from the bullet, bumping SCHEMA_VERSION, changing a numeral,
and restoring the old "no MXF/DPX" sentence each turn this red on their own assertion.
"""

import sys
import typing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentcut import contracts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

CN_DIGITS = "零一二三四五六七八九"


def cn_number(value: int) -> str:
    """Spell an integer the way Chinese prose does it, 1..20."""
    if value <= 9:
        return CN_DIGITS[value]
    if value == 10:
        return "十"
    if value < 20:
        return f"十{CN_DIGITS[value - 10]}"
    raise AssertionError(f"README does not use numerals above 19, got {value}")


def bullet(text: str, start: str) -> str:
    """The whole bullet (one line) that begins with ``start``."""
    hits = [line for line in text.splitlines() if line.lstrip("- ").startswith(start)]
    assert len(hits) == 1, f"expected exactly one bullet starting {start!r}, found {len(hits)}"
    return hits[0]


def sentence_after(text: str, name: str) -> list[str]:
    """Every sentence that runs from a mention of ``name`` to the next full stop.

    README may write the type as ``contracts.BlendMode`` or bare, and may name it more than once,
    so each mention contributes a window and only one of them has to carry the count.
    """
    windows: list[str] = []
    index = text.find(name)
    while index >= 0:
        end = text.find("。", index)
        assert end >= 0, f"the `{name}` mention has no ending"
        windows.append(text[index:end])
        index = text.find(name, index + len(name))
    assert windows, f"README never names {name}"
    return windows


def count_of(literal_name: str) -> int:
    value = getattr(contracts, literal_name, None)
    assert value is not None, f"contracts has no {literal_name} any more"
    args = typing.get_args(value)
    assert args, f"{literal_name} is empty"
    return len(args)


def main() -> None:
    text = README.read_text(encoding="utf-8")
    problems: list[str] = []

    # 1. The export-preset bullet must name every container the contract table allows.
    presets = bullet(text, "导出预设就是 `contracts.OUTPUT_CONTAINERS`")
    for container in contracts.OUTPUT_CONTAINERS:
        if container not in presets:
            problems.append(
                f"README's preset bullet does not name container {container!r}, which "
                f"OUTPUT_CONTAINERS still offers"
            )
    named = [c for c in contracts.OUTPUT_CONTAINERS if c in presets]
    assert len(named) == len(contracts.OUTPUT_CONTAINERS), problems

    # 2. Retired false statements must not return.
    for retired in (
        "仍没有 MXF/DPX",
        "三种带画面的容器",
        "已支持六属性关键帧",
        "68 项 *_check.py",
        "53 种命令",
        "渲染层的 6 个 TypeScript 检查",
        "schema v11 兼容读取 v1–v10",
    ):
        if retired in text:
            problems.append(f"README states {retired!r} again, which the engine contradicts")

    # 2b. 1.155：README 与 AGENTS 都不许再说「跟踪与稳定不估计旋转」——`stabilize.py` 从 1.67
    #     起就按四个锚点做 Arun 刚体拟合写 `rotation`。这条双向钉：句子回来红，代码不估了也红。
    retired_roll = "跟踪与稳定不估计旋转"
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for claimed in (text, agents):
        if retired_roll in claimed:
            problems.append(
                f"文档又把稳定说成不估旋转，而 stabilize.py 正在写 rotation：{retired_roll!r}"
            )
    stabilize_src = (ROOT / "src/agentcut/stabilize.py").read_text(encoding="utf-8")
    if "best carries" not in stabilize_src or "rotation" not in stabilize_src:
        problems.append(
            "stabilize.py 不再估 roll 了——那句「不估计旋转」就重新成了实话，"
            "这条门禁与 README 那一行都要跟着改回来"
        )

    # 2c. 1.156：「709 的绿原色在 P3-D65 之外」是 1.153 记反了方向留下的一句假话（那个会夹的动作
    #     属于 P3→709 那张收窄表），而这一档已经在 1.156 量过交出。双向钉：文档再说这句红；
    #     表里这一档哪天没了也红——那时这句话也许重新是实话，得再量一遍，不能让门禁替新实测做主。
    retired_p3 = "709 的绿原色在 P3-D65 之外"
    for claimed in (text, agents):
        if retired_p3 in claimed:
            problems.append(
                f"文档又把 P3-D65 说成要色域压缩，而那一档是量过才交出去的：{retired_p3!r}"
            )
    if "p3-d65" not in contracts.COLOUR_TAG_CODES:
        problems.append(
            "契约表里 p3-d65 这一档没了——那句「绿原色在 P3-D65 之外」也许重新成了实话，"
            "这条门禁、README 那一行与表里那一行都要跟着重新量"
        )

    # 2d. 1.156：重跑验收那一页教人把 win-unpacked 里那支 exe 抄到根目录，而门禁比的是便携版——
    #     照文档做会当场红。这条钉住「文档指的那一支就是门禁读的那一支」，两句任一被改就红。
    portable = 'Copy-Item "desktop/release/AgentCut-便携版.exe" AgentCut.exe'
    if portable not in text:
        problems.append(
            "README 的重新打包那一步不再指向便携版那支 exe，而 released_package_check 比的就是"
            "根目录那份与 desktop/release/AgentCut-便携版.exe 逐字节相同"
        )
    if "desktop/release/win-unpacked/AgentCut.exe AgentCut.exe" in text:
        problems.append(
            "README 又把 win-unpacked 里那支抄到根目录了——那句会让照做的人把门禁弄红"
        )

    # 2e. 1.156：显示端那一条的墙别记错对象——`COLOR_SPACES` 是曲线的词表、不含基色，缺的是
    #     「工程级基色」那个概念。哪天契约里真出现了它（下面那种词表名），这条红，该跟着改的是
    #     AGENTS 第 1 项与这句话本身，而不是让门禁替新一轮设计做主。
    if "里没有宽基色那一档" in agents:
        problems.append(
            "AGENTS 又把「显示端没有宽基色」记在 `COLOR_SPACES` 头上——那是曲线的词表，"
            "工程级基色才是那一档的墙"
        )
    if hasattr(contracts, "COLOR_PRIMARIES"):
        problems.append(
            "契约里出现了工程级基色的词表：显示端对齐不再是说不出口的话，"
            "AGENTS 第 1 项与这条门禁都要跟着重新量"
        )

    # 3. The schema number README quotes must be the live one.
    expected = f"本轮量到的值是 {contracts.SCHEMA_VERSION}"
    if expected not in text:
        problems.append(f"README's schema claim is not {expected!r}")

    # 4. Each named property table's count must match the Literal, inside its own sentence.
    for name in ("EffectProperty", "MaskProperty", "SpatialProperty", "BlendMode"):
        want = count_of(name)
        windows = sentence_after(text, name)
        if not any(str(want) in window or cn_number(want) in window for window in windows):
            problems.append(
                f"README counts {name} as something other than {want} "
                f"({cn_number(want)}); the sentences read: " + " | ".join(w[:60] for w in windows)
            )

    # 5. The delivery-colour row has to count the tags the contract table actually publishes, and
    #    the row has to exist at all: a delivered capability that README stopped talking about is
    #    the same class of lie as a wrong number.
    colour_rows = [line for line in text.splitlines() if "output_colour_tags" in line]
    assert colour_rows, "README never names capabilities.output_colour_tags"
    assert len(colour_rows) == 1, "README names output_colour_tags in more than one place"
    want_tags = len(contracts.COLOUR_TAG_CODES)
    if f"{want_tags} 档" not in colour_rows[0]:
        problems.append(
            f"README's delivery-colour row does not say {want_tags} 档, which is what "
            f"contracts.COLOUR_TAG_CODES publishes"
        )

    assert not problems, "\n".join(problems)
    print(
        f"PASS: {len(contracts.OUTPUT_CONTAINERS)} containers named, schema "
        f"{contracts.SCHEMA_VERSION} quoted, "
        f"{count_of('EffectProperty')}+{count_of('MaskProperty')}+{count_of('SpatialProperty')} "
        f"animated properties and {count_of('BlendMode')} blend modes match the contract, "
        f"{len(contracts.COLOUR_TAG_CODES)} delivery colour tag(s) counted"
    )


if __name__ == "__main__":
    main()
