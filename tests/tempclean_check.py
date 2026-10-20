"""1.226：验东西的那一手，不许往用户的地方堆垃圾。

1.225 跑发布账时量到的：`%TEMP%` 里留着 110 个 `agentcut-*` 目录、合计 24.7 MB——
一天两趟全套的量。起因是 14 档门禁各用 `tempfile.mkdtemp` 建一个地方，建了就不管：
`mkdtemp` 不像 `TemporaryDirectory`，它没有「用完就删」这一半。

两件事一起判，缺一不可：
① **真的跑一档门禁**，跑之前数一遍、跑之后再数一遍——多出来的那一个就是没还的。
   只查源码字面（下面那条）挡不住「用了 helper 但 helper 自己坏了」；
   只跑一趟又挡不住下一轮新加一档不用 helper 的。
② 源码里除了 `tests/scratch.py` 自己，任何一档都不许再直接 `tempfile.mkdtemp`。

判据是「相等」，不是「小于某个数」：这台机器上别人也可能在同一时刻建 `agentcut-*`，
但那是**另一个进程的一生**——本档只在自己这一趟的前后各数一次，中间除了那趟门禁
什么都不做，所以多出来的必然是那趟留下的。（真要撞上并发，红的是这一档，
报出来的数会带着两边的清单，看得见是谁。）
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
PROBE = "maskbox_check.py"  # 快、真起引擎、真建一个临时地方——三样都占
PREFIX = "agentcut-"


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def listed() -> list[str]:
    temp = Path(tempfile.gettempdir())
    return sorted(p.name for p in temp.iterdir() if p.is_dir() and p.name.startswith(PREFIX))


def main() -> None:
    # ② 字面：helper 之外一律不许直接建。认的是**调用形状**（带括号），
    #    不是那个词——这一档自己的说明里也要提它一次，认词就成了自己抓自己。
    #    那一个 needle 拆两截写：整串留在这里，本档就会把自己认成违规的那一个。
    call = "tempfile.mkdtemp" + "("
    offenders = [path.name for path in sorted(TESTS.glob("*_check.py"))
                 if call in path.read_text(encoding="utf-8")]
    helper = TESTS / "scratch.py"
    if not helper.is_file():
        fail("tests/scratch.py 不在——那一个「建了会还」的口没了")
    if offenders:
        fail("这些档还在直接 tempfile.mkdtemp（建了不还）：" + ", ".join(offenders))
    if "mkdtemp" not in helper.read_text(encoding="utf-8"):
        fail("tests/scratch.py 里已经没有 mkdtemp——那一个口是空的，①那条判据也就没人可验")

    # ① 真跑一趟，前后各数一次。
    before = listed()
    answer = subprocess.run(
        [sys.executable, str(TESTS / PROBE)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900, cwd=str(ROOT),
    )
    after = listed()
    if answer.returncode != 0:
        fail(f"探针那趟门禁自己红了（这一档不替它背）：{answer.stdout[-300:]}{answer.stderr[-300:]}")
    left = [name for name in after if name not in before]
    if left:
        fail(f"跑完 {PROBE} 之后 %TEMP% 里多出 {len(left)} 个 {PREFIX}* 目录没被还："
             + ", ".join(left[:6]))
    print(f"PASS: 跑完一档真门禁，{PREFIX}* 目录一个没多（跑前 {len(before)}、跑后 {len(after)}）；"
          "helper 之外没有第二处直接建临时地方")


if __name__ == "__main__":
    main()
