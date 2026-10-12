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

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
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

    assert not problems, "\n".join(problems)
    print(
        f"PASS: {len(contracts.OUTPUT_CONTAINERS)} containers named, schema "
        f"{contracts.SCHEMA_VERSION} quoted, "
        f"{count_of('EffectProperty')}+{count_of('MaskProperty')}+{count_of('SpatialProperty')} "
        f"animated properties and {count_of('BlendMode')} blend modes match the contract"
    )


if __name__ == "__main__":
    main()
