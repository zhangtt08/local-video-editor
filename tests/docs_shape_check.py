"""Markdown tables in the docs have to stay tables.

Every row of these tables is one physical line: `| 能力 | 状态 | 说明 |`. Twice now a patch has
glued two rows onto one line with a ` | | ` in the middle, and a joined row does not fail anything —
it just renders as one row with the second title swallowed into a cell, which is how a README can
say "已实现" about something the reader cannot even find in the table. This check reads the shape,
not the prose: a line that starts like a row must end like a row, and every row of one table must
have the same number of cells as its header.

Backticks are honoured when counting cells, because these tables carry `clip.link_split_trim` and
`a | b` inside code spans. An odd number of backticks on a row line is reported on its own: an
unterminated code span is how a mangled row looks from the inside, and it is the reason the cell
count below cannot be trusted.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "AGENTS.md"] + sorted((ROOT / "docs").glob("*.md"))


def cells(line: str) -> list[str]:
    r"""Split a row on the pipes that are neither inside a code span nor escaped as `\|`."""
    out: list[str] = []
    current = ""
    inside = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line) and line[index + 1] == "|":
            current += "\\|"
            index += 2
            continue
        if char == "`":
            run = 0
            while index + run < len(line) and line[index + run] == "`":
                run += 1
            if run in (1, 3):
                inside = not inside
            current += char * run
            index += run
            continue
        if char == "|" and not inside:
            out.append(current.strip())
            current = ""
            index += 1
            continue
        current += char
        index += 1
    out.append(current.strip())
    return out


def table_blocks(lines: list[str]) -> list[list[tuple[int, str]]]:
    """Contiguous runs of lines that start with a pipe, each with its 1-based line number."""
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith("|"):
            current.append((number, line))
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def check(path: Path) -> list[str]:
    problems: list[str] = []
    data = path.read_bytes()
    text = data.decode("utf-8")
    lines = text.splitlines()
    lone_lf = sum(
        1 for index, char in enumerate(data) if char == 10 and (index == 0 or data[index - 1] != 13)
    )
    if b"\r\n" in data and lone_lf:
        problems.append(f"{path.name}: {lone_lf} line endings are bare LF in a CRLF file")
    for number, line in enumerate(lines, start=1):
        if " | | " in line and line.lstrip().startswith("|"):
            problems.append(f"{path.name}:{number} two rows glued onto one line (` | | `)")
        if not line.lstrip().startswith("|"):
            continue
        if not line.rstrip().endswith("|"):
            problems.append(f"{path.name}:{number} a row starts with a pipe, never ends with one")
        if line.count("`") % 2:
            problems.append(f"{path.name}:{number} an unclosed code span in a table row")
    for block in table_blocks(lines):
        # The header is the authority on how many cells this table has: a glued-on second row makes
        # MORE cells than it should, so comparing rows with each other would blame the honest ones.
        width = len(cells(block[0][1]))
        for number, line in block:
            found = len(cells(line))
            if found != width:
                problems.append(
                    f"{path.name}:{number} this row has {found} cells, the table header has {width}"
                )
    return problems


def duplicate_bullets(path: Path) -> list[str]:
    """同一节里出现两遍一模一样的 bullet——那就是重复的账，不是两条事实。"""
    body = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    problems: list[str] = []
    for section in body.split("\n## ")[1:]:
        title = section.splitlines()[0][:24]
        seen: set[str] = set()
        for line in section.splitlines():
            if not line.startswith("- **"):
                continue
            head = line[:40]
            if head in seen:
                problems.append(f"{path.name}: 节「{title}」里 bullet 出现了两遍：{head}")
            seen.add(head)
    return problems


def duplicate_sections(path: Path) -> list[str]:
    """同一份文档里 `## ` 那一级的标题出现两遍——那是拼接拼重了，不是两节。

    只判 `## ` 这一级：`docs/optimization.md` 里 `### 实测` 这类小节标题在每一节下各有一份，
    量过是真的重（所以那一层不判——判了就是把量具自己的猜法当成文档的事实）。
    """
    body = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    seen: set[str] = set()
    twice: set[str] = set()
    for line in body.splitlines():
        if not line.startswith("## "):
            continue
        if line in seen:
            twice.add(line)
        seen.add(line)
    return [f"{path.name}: 同一级的标题写了两遍：{head[:44]}" for head in sorted(twice)]


def main() -> None:
    missing = [str(path) for path in DOCS if not path.exists()]
    assert not missing, f"docs the gate reads are gone: {missing}"
    row_problems: list[str] = []
    duplicates: list[str] = []
    sections: list[str] = []
    for path in DOCS:
        row_problems += check(path)
        duplicates += duplicate_bullets(path)
        sections += duplicate_sections(path)
    # 那句红字得说清看见的是哪一件事：一条重复的 bullet 不是「表格行坏了」。
    assert not row_problems, f"{len(row_problems)} malformed table rows:\n" + "\n".join(
        row_problems[:20]
    )
    assert not duplicates, f"{len(duplicates)} 条 bullet 在同一年里写了两遍:\n" + "\n".join(
        duplicates[:20]
    )
    assert not sections, f"{len(sections)} 处 `## ` 标题在同一份文档里写了两遍:\n" + "\n".join(
        sections[:20]
    )
    tables = sum(len(table_blocks(path.read_text(encoding="utf-8").splitlines())) for path in DOCS)
    rows = sum(
        len(block)
        for path in DOCS
        for block in table_blocks(path.read_text(encoding="utf-8").splitlines())
    )
    assert tables > 10 and rows > 40, (tables, rows)
    print(f"PASS: {len(DOCS)} documents, {tables} tables, {rows} rows all shaped like rows"
          f"；一节标题与一条 bullet 都只有一份")


if __name__ == "__main__":
    main()
