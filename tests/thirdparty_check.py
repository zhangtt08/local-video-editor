"""三方清单的门禁：现场重算一份，再与仓里那一份逐字节比。

为什么这一档要存在：企业接进去的第一道问题不是「能不能跑」，是「你随包发出去的东西都是
什么许可」。这一档把三件事钉住——

① 那份清单**不是手写**的：`scripts/thirdparty.py` 现场重算（跑两支媒体程序的 `-version`
   与 `-buildconf`、读 `uv.lock` 的必带闭包、读装出来的许可字段、量装机那份里的字节），
   与仓里那一份逐字节比。换了个 ffmpeg 构建、多了一个依赖、`_internal` 里多搬了一份
   元数据，都会红在这里。
② 每一行都要交得出许可与「读的是哪一格」；`UNKNOWN` 与空值一律算不合格。
③ GPL 那一档的**源码义务**要写在纸上：判定所依据的开关、上游的两个 URL、以及「义务落在
   分发方」那一句。少一句就红——合规文档里最贵的是含糊。
④ 「清单说的就是包里装的」那一节不许出现「不一致」；装机那份里的 `LICENSE.electron.txt`
   与 `LICENSES.chromium.html` 必须真的存在并被列名。
⑤ 手册（`docs/enterprise.md`）必须指到这一页——一份没人读得到的合规清单等于没有。

跑法：空闲机器单跑 `uv run python tests/thirdparty_check.py`（要 `.venv`、
`desktop/node_modules`、`desktop/release/win-unpacked` 与随包那两支媒体程序）。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import thirdparty  # noqa: E402

MANIFEST = ROOT / "THIRD-PARTY.md"
RUNBOOK = ROOT / "docs/enterprise.md"
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def rows_of(text: str, header: str) -> list[list[str]]:
    """把清单里那张以 `header` 开头的表读成行（列已去掉首尾空管）。"""
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.startswith(f"| {header}"))
    except StopIteration:
        return []
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def buildconf(name: str) -> str:
    exe = ROOT / "desktop/resources/bin" / name
    done = subprocess.run([str(exe), "-hide_banner", "-buildconf"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    return done.stdout or ""


def media_legs(text: str) -> None:
    """媒体那两行不许由生成器说了算：sha256 门禁自己算，档位门禁自己跑一遍 `-buildconf`。

    现场重算再逐字节比，只挡得住「文件与生成器不一致」；判定本身写错时两份**一起错**。
    1.319 那三方版本号一起停旧、1.315 那构建者换掉了随包 FFmpeg 而门禁照绿，都是这一形状。
    """
    for row in rows_of(text, "文件"):
        name = row[0]
        build_input = ROOT / "desktop/resources/bin" / name
        inside = ROOT / "desktop/release/win-unpacked/resources/bin" / name
        if not (build_input.is_file() and inside.is_file()):
            check(f"没法自己算：{name} 的两份都不在", False,
                  (build_input.is_file(), inside.is_file()))
            continue
        digest = hashlib.sha256(build_input.read_bytes()).hexdigest()
        check(f"{name} 的 sha256 要门禁自己算过一遍", digest == row[5], (digest, row[5]))
        check(f"{name} 装机那一份与构建输入必须是同一件东西",
              hashlib.sha256(inside.read_bytes()).hexdigest() == digest, str(inside))
        flags = [line.strip() for line in buildconf(name).splitlines()
                 if line.strip().startswith("--")]
        gpl = thirdparty.GPL_TRIGGER in flags
        check(f"{name} 那一格许可要由门禁自己跑一遍 -buildconf 推出来",
              ("GPL-2.0-or-later" in row[2]) == gpl, (row[2], gpl, len(flags)))
        listed = [item for item in row[3].replace("、", " ").split() if item.startswith("--")]
        check(f"{name} 的佐证列只能列 FFmpeg 点名的 GPL-only 那几个外部库",
              all(item in thirdparty.GPL_EVIDENCE for item in listed), row[3][:120])


def license_legs(text: str) -> None:
    py_rows = rows_of(text, "包")
    check("Python 依赖那张表读得出行", len(py_rows) >= 10, len(py_rows))
    for row in py_rows:
        bad = [cell for cell in row if not cell]
        unknown = any("UNKNOWN" in cell.upper() for cell in row)
        if bad or unknown:
            check(f"这一行交不出许可：{row[0]}", False, row)
    js_rows = rows_of(text, "组件")
    check("运行时那张表列了 Electron 与 Chromium 两行", len(js_rows) == 2, js_rows)
    npm = rows_of(text, "npm 包")
    check("JS 生产依赖那张表读得出行", len(npm) >= 3, len(npm))
    for row in npm:
        check(f"这一行交不出许可：{row[0] if row else row}",
              len(row) == 4 and all(row[:3]), row)
    media = rows_of(text, "文件")
    check("两支媒体程序各有一行", len(media) == 2, media)
    for row in media:
        check(f"{row[0]} 的许可那一格不许留空", bool(row[2].strip()), row[2])
        check(f"{row[0]} 要有 64 位十六进制的 sha256",
              bool(re.fullmatch(r"[0-9a-f]{64}", row[5])), row[5])


def obligation_legs(text: str) -> None:
    for phrase, why in (
        ("--enable-gpl", "GPL 判定所依据的那个开关要留在纸上"),
        ("对应源码义务", "GPL 那一档要说清对应源码的义务落在谁身上"),
        ("ffmpeg.org/download.html", "要给出上游源码的取得指引"),
        ("gyan.dev", "要给出这一份 Windows 构建的出处"),
        ("包装工的 MIT 字段不等于载荷的许可",
         "npm 包装工的许可字段不是载荷的许可，这一句是本档的立论"),
    ):
        check(f"少了这一句：{why}", phrase in text, phrase)


def packaged_legs(text: str) -> None:
    check("包内核验那一节不许出现「不一致」", "不一致" not in text, "不一致")
    inside = rows_of(text, "相对 `desktop/release/win-unpacked/` 的路径")
    check("包内核验要逐字节比那两支", len(inside) == 2, inside)
    for row in inside:
        check(f"{row[0]} 的比对结论要写「逐字节相同」", "逐字节相同" in row[3], row[3])
    for name in thirdparty.LICENSE_FILES:
        check(f"装机那份里的 {name} 要被点名", f"`{name}`" in text, name)


def collected_leg(text: str) -> None:
    """`_internal` 里每一份 dist-info 都得在表里占一行——包里带着、清单上没写，是要红的。"""
    collected = thirdparty.collected_dists()
    names = [row[0] for row in rows_of(text, "包")]
    missing = sorted(name for name in collected if name not in names)
    check("冻结包内的每一份 dist-info 都在清单里有一行", not missing,
          (missing, len(collected)))


def runbook_leg(text: str) -> None:
    check("企业手册要指到这一页", RUNBOOK.is_file() and "THIRD-PARTY.md" in
          RUNBOOK.read_text(encoding="utf-8"), str(RUNBOOK))
    tail = text.rsplit("合计：", 1)
    check("末尾那句合计要在", len(tail) == 2, text[-120:])
    counts = re.findall(r"Python 运行时依赖 (\d+) 项、JS 生产依赖 (\d+) 项", tail[1]) \
        if len(tail) == 2 else []
    check("合计那句读得出两个数", len(counts) == 1, counts)
    if len(counts) == 1:
        py = len(rows_of(text, "包"))
        js = len(rows_of(text, "npm 包"))
        check(f"合计说的 Python 项数要等于那张表的行数（{py}）", int(counts[0][0]) == py, counts)
        check(f"合计说的 JS 项数要等于那张表的行数（{js}）", int(counts[0][1]) == js, counts)


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"FAIL: 清单不见了：{MANIFEST}（先跑 scripts/thirdparty.py）")
    for path, why in (
        (ROOT / ".venv/Lib/site-packages", "先跑 uv sync --group dev"),
        (ROOT / "desktop/node_modules", "先跑 npm --prefix desktop ci"),
        (ROOT / "desktop/release/win-unpacked", "先跑 npm --prefix desktop run dist"),
    ):
        if not path.is_dir():
            raise SystemExit(f"FAIL: {path} 不见了——{why}")
    committed = MANIFEST.read_bytes().decode("utf-8").replace("\r\n", "\n")
    fresh = thirdparty.build()
    if committed != fresh:
        head = next((index for index in range(min(len(committed), len(fresh)))
                     if committed[index] != fresh[index]), 0)
        check("仓里那份清单要等于现场重算的那一份（改依赖就重跑生成器）", False,
              f"第 {head} 个字符起不一致："
              f"仓里 {committed[head:head + 120]!r} / 现场 {fresh[head:head + 120]!r}")
    license_legs(committed)
    media_legs(committed)
    obligation_legs(committed)
    packaged_legs(committed)
    collected_leg(committed)
    runbook_leg(committed)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print(f"PASS: 三方清单现场重算逐字节对上了——媒体程序 "
          f"{len(rows_of(committed, '文件'))} 支（许可按 -buildconf 判定并写明依据的开关）、"
          f"Python 依赖 {len(rows_of(committed, '包'))} 项（每一项都交得出许可与出处）、"
          "包内那两支与构建输入逐字节相同、企业手册指得到这一页")


if __name__ == "__main__":
    main()
