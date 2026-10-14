"""排版这一档：宽度按**显示宽度**量（中日韩全角算两格），并把「两行被粘成一行」这个签名钉死。

为什么要有这一档：`pyproject.toml` 写着 `line-length = 100`，可仓库里没有任何门禁跑它——于是
1.156 那次改动把 `contracts.py` 里两行注释粘成了一行（117 格），而且粘进去的那句「最差 1 阶」正是
同一轮别处已经改过口的一个手抄数。它绿着活了一整轮，因为没人量。

口径跟的是**项目自己配的那把尺**，不是我自己另拧的一把：`ruff check`（select E，line-length
100）对三种超长行不出警——整行只有一个不可断的 token（一个 f-string 到底，断行就得改字符串
内容）、行尾是 URL、行尾带 `# type:` / `# fmt:` / `# noqa` 这类 pragma。1.157 当场拿
`ruff check --select E501` 的 JSON 逐行比对过这个判定：src/tests/examples/scripts/agent 上
零漏报（`only_ruff=0`），多出的只有随包 vosk 的三方文件——那本来就不在第一方目录里。
照这把尺量，`src/agentcut/**` 是零违规的，`agent/server.py` 才是欠账的那一处。

两处额度：
- `src/agentcut/**` 是随包引擎，零违规；
- `tests/**`、`agent/**`、`scripts/**`+`examples/**` 的历史长行钉的是**只许降不许升**的上限
  （下面那三个数，当场量出来的）：额度只挡新增，不把已有的东西冻住。
"""

import re
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = tomllib.loads((ROOT / "pyproject.toml").read_bytes().decode("utf-8"))["tool"]["ruff"][
    "line-length"
]
# 历史欠账的上限：只许往下走。这一轮把 tests 的六行收干净了，现在量到 tests 0、agent 27、
# scripts+examples 0（见本档打印的那行）。
CEILINGS = {"tests": 0, "agent": 27, "scripts": 0}
# ruff 对超长行不出警的三种情形，逐字对齐：整行只有一个 token、行尾是 URL、行尾是 pragma。
PRAGMA = re.compile(r"#\s*(type|noqa|fmt|ruff|isort)\b")
# 被粘成一行的注释签名：一个全角标点后面跟着三个以上空格，又出现 `#`。正常的续行注释是
# 「\n    # …」，不会在同一行里再出现第二个 `#` 的引导空格。
JOINED = re.compile(r"[、，。；：）】」』]\s{3,}#")
ENGINE = ("src/agentcut/**/*.py",)
FIRST_PARTY = {
    "tests": ("tests/**/*.py",),
    "agent": ("agent/**/*.py",),
    "scripts": ("scripts/**/*.py", "examples/**/*.py"),
}


def width(line: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in line)


def lines_of(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8", errors="replace").splitlines()


def sources(patterns: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        found.extend(sorted(ROOT.glob(pattern)))
    return [path for path in found if path.is_file() and ".venv" not in path.parts]


def offence(line: str) -> bool:
    """这一行超了格，而且 ruff 会当场报它——断行不改内容就能修，才叫违规。"""
    stripped = line.rstrip()
    if width(stripped) <= LIMIT:
        return False
    chunks = stripped.split()
    if len(chunks) <= 1:
        return False
    if "://" in chunks[-1]:
        return False
    return not PRAGMA.search(stripped)


def over_long(path: Path) -> list[int]:
    return [number for number, line in enumerate(lines_of(path), 1) if offence(line)]


def self_proof() -> None:
    """这把尺自己得能被证伪：四种豁免和一种必抓，逐条判给看；粘行签名正反各判一次。

    没有这一段，「豁免」就是我说了算——`ruff` 的判定与它一致是当场比对过的（模块 docstring），
    比对口径本身却要在这几行里站着，否则下一轮谁都能改宽豁免把这一档调成常绿灯。
    """
    single_token = '        "' + "a" * 95 + '",'
    url_tail = "alpha = beta(gamma, delta)  # 文档见 https://example.com/" + "x" * 60
    pragma_tail = "alpha = beta(gamma, delta)  # type: ignore[arg-type] " + "y" * 60
    breakable = "def measurable(alpha, beta, gamma, delta):  # " + "这条注释是可以断出去的，" * 4
    for label, sample in (
        ("单 token", single_token),
        ("URL 收尾", url_tail),
        ("pragma 收尾", pragma_tail),
        ("可断行", breakable),
    ):
        assert width(sample) > LIMIT, f"样本「{label}」本身没超过 {LIMIT} 格，判它没意义"
    assert offence(single_token) is False, "整行只有一个不可断的 token 也被判成违规了"
    assert offence(url_tail) is False, "以 URL 收尾的行也被判成违规了"
    assert offence(pragma_tail) is False, "带 # type: pragma 的行也被判成违规了"
    assert offence(breakable) is True, "可断行的超长行没被抓到——这一档是空转的"

    # 这个样本自己就是一行粘过的注释——写成拼接，免得本档扫到它（扫描是逐文件的，含本文件）。
    joined = "契约里这一句已经改过口" + "，" + " " * 3 + "# 上一轮的注释被粘了回来"
    assert JOINED.search(joined), "两行被粘成一行是这个签名，它没抓到"
    assert not JOINED.search("契约里这一句已经改过口"), "正常单行注释被当成粘行误报"


def main() -> None:
    assert LIMIT == 100, f"这一档读的是 pyproject 的 line-length，量到 {LIMIT}"
    self_proof()

    engine = sources(ENGINE)
    assert engine, "找不到随包引擎的源码"
    bad = {str(path): over_long(path) for path in engine}
    bad = {path: rows for path, rows in bad.items() if rows}
    assert not bad, f"随包引擎里有超过 {LIMIT} 格、又能靠断行修掉的行：{bad}"

    totals = {}
    for group, patterns in FIRST_PARTY.items():
        rows = 0
        for path in sources(patterns):
            rows += len(over_long(path))
        totals[group] = rows
        ceiling = CEILINGS.get(group)
        if ceiling is not None:
            assert rows <= ceiling, (
                f"{group} 里可修的超长行从 {ceiling} 涨到 {rows}：这一档的额度只挡新增，"
                "要加行请先把旧账一起降下来"
            )

    joined = []
    for path in sources(
        (
            "src/**/*.py",
            "tests/**/*.py",
            "agent/**/*.py",
            "desktop/src/**/*.ts",
            "desktop/src/**/*.tsx",
            "docs/*.md",
            "README.md",
            "AGENTS.md",
        )
    ):
        for number, line in enumerate(lines_of(path), 1):
            if JOINED.search(line):
                joined.append(f"{path}:{number}")
    assert not joined, f"这些行是被粘成一行的两行注释（换行丢了）：{joined}"

    widest = max(
        (
            (width(line.rstrip()), f"{path}:{number}")
            for path in sources(ENGINE + FIRST_PARTY["agent"] + FIRST_PARTY["tests"])
            for number, line in enumerate(lines_of(path), 1)
        ),
        key=lambda pair: pair[0],
    )
    print(
        f"   随包引擎 {len(engine)} 份零违规；可修超长行 tests {totals['tests']}、"
        f"agent {totals['agent']}、scripts {totals['scripts']}（欠账上限 {CEILINGS}）；"
        f"最宽的一行 {widest[0]} 格在 {widest[1]}"
    )
    print(
        f"PASS: 显示宽度按 pyproject 的 {LIMIT} 格量、豁免口径与 ruff 逐行比对过，"
        "随包引擎零违规、历史欠账只许降不许升，并且没有任何一行是两行被粘在一起的"
    )


if __name__ == "__main__":
    main()
