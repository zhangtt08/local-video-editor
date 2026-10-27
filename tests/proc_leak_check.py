"""跑完验收不许在机器上攒引擎进程——这一档量的是那个兜底本身。

1.320 实测：一台半途崩掉的 `lease_check` 在机器上留下 4 个还在服务的引擎，它们的
`--data-dir` 指着已经被 atexit 还掉的临时目录，自己不会退。`tests/suite_check.py` 里的
`strays()` / `sweep()` 是那一手的兜底，而**兜底自己也得被量**，三条判据：

① 谓词认得对：一条命令行里只该认出 `%TEMP%\\agentcut-xxxxxxxx` 那一个目录，
   人在仓库里的工程目录（`agentcut` 目录下那个 `data`）不算，exe 路径里那一段 `agentcut`
   也不算（v2 就是从行首一路吃到临时目录，把一台目录还在的引擎认成活口，红在量具自己身上）；
② 正在跑的那一趟不许碰：临时目录还在，就不是活口；
③ 漏下的那一个收得掉：目录已经不在了的，按 PID 连子树收，收完机器上没有残留。

跑法：空闲机器单跑 `uv run python tests/proc_leak_check.py`（要本机 powershell）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import scratch  # noqa: E402
import suite_check as runner  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def predicate_leg() -> None:
    """谓词单测：把四条真实形状的命令行车喂进去，看认出的是哪一个目录。

    合成路径一律用 `D:` 那个假盘，不写任何机器上的主目录（`mediabinary_check` 钉着这条）。
    """
    quoted = (r'"D:\tools\Python312\python.exe" -m agentcut api --port 0 --json'
              r' --data-dir D:\runner\scratch\agentcut-lease-evkff857\engine'
              r' --media-root D:\runner\scratch\agentcut-lease-evkff857')
    check("认出的就是那一个临时目录（media-root 与 data-dir 是同一个，不许多数一份）",
          runner.scratch_roots(quoted) == [r"D:\runner\scratch\agentcut-lease-evkff857"],
          runner.scratch_roots(quoted))

    stub = (r"D:\work\repo\agentcut\.venv\Scripts\python.exe -m agentcut api"
            r" --data-dir D:\runner\scratch\agentcut-ops-1a2b3c4d/engine")
    check("壳那条命令行认出的必须是临时目录本身，不是从行首吃到那里的混合串",
          runner.scratch_roots(stub) == [r"D:\runner\scratch\agentcut-ops-1a2b3c4d"],
          runner.scratch_roots(stub))

    # 中间那段标签自己就占满 8 个字符：认出的是「标签-后缀」整串，不是标签那半截。
    # 少认半截就是认了一个不存在的目录，正在跑的那一趟会被当成活口收掉。
    named = (r"D:\tools\python.exe -m agentcut api --data-dir"
             r" D:\runner\scratch\agentcut-procleak-ab12cd34/engine")
    check("带标签的那一个临时目录认出的是整串，不是标签那半截",
          runner.scratch_roots(named) == [r"D:\runner\scratch\agentcut-procleak-ab12cd34"],
          runner.scratch_roots(named))

    human = (r"D:\work\agentcut\.venv\Scripts\python.exe -m agentcut api"
             r" --data-dir D:\work\project\agentcut\data")
    check("人自己的工程目录一个都不算", runner.scratch_roots(human) == [],
          runner.scratch_roots(human))

    # mkdtemp 的后缀字母表是 `abcdefghijklmnopqrstuvwxyz0123456789_`——**带下划线**。
    # 少认这一点，`agentcut-plimit-ci36g46_` 就会被认成 `agentcut-plimit`（那半截当然不存在），
    # 于是「正在跑的那一趟」被当活口收掉。1.321 的整套验收就是这么红的，
    # 上一轮加的逐 PID 摊开自己点名了这一条。
    under = (r"D:\tools\python.exe -m agentcut api --data-dir"
             r" D:\runner\scratch\agentcut-plimit-ci36g46_/engine")
    check("后缀里带下划线的那一个临时目录要认全",
          runner.scratch_roots(under) == [r"D:\runner\scratch\agentcut-plimit-ci36g46_"],
          runner.scratch_roots(under))


def roots_of(pids: list[int]) -> list[tuple[int, list[str], list[bool]]]:
    """把每一条命中的命令行摊开：认出的是哪个目录、那个目录在不在。

    失败的时候这一列要跟着交回——「一台目录还在的引擎被数成活口」这件事，光看 PID 列表
    说不出是谁认错了。
    """
    wanted = set(pids)
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         runner.STRAY_SCRIPT],
        capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
    )
    rows = []
    for line in (done.stdout or "").splitlines():
        pid, _, command = line.partition(" :: ")
        number = int(pid.strip()) if pid.strip().isdigit() else 0
        if number in wanted:
            found = runner.scratch_roots(command)
            rows.append((number, found, [Path(root).exists() for root in found]))
    return rows


def live_leg() -> None:
    """一条反例 + 一条正例：目录还在的那一趟不许碰，目录没了的必须收掉。"""
    keep = scratch.make("agentcut-procleak-")
    (keep / "engine").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    engine = subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
         "--data-dir", str(keep / "engine"), "--media-root", str(keep)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    # 后缀里带下划线的那一种临时目录真起一台：mkdtemp 的字母表里有 `_`，认不全就会把
    # 这一趟正在跑的引擎当活口收掉——1.321 的整套验收就是这么红的。
    under = Path(tempfile.gettempdir()) / "agentcut-undr-ab12c3_"
    (under / "engine").mkdir(parents=True, exist_ok=True)
    underscore = subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
         "--data-dir", str(under / "engine"), "--media-root", str(under)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    # 正例借一个「不会被建出来」的临时目录：命令行里那个名字在，目录不在——
    # 那正是崩在半路的那一台留下的形状。名字每一趟都新，别的趟留下的假活口不算这一趟的数。
    gone = Path(tempfile.gettempdir()) / f"agentcut-gone-{os.urandom(4).hex()}"
    ghost = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(180)", str(gone / "engine")],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    try:
        found: list[int] = []
        deadline = time.time() + 40.0
        while time.time() < deadline and ghost.pid not in found:
            found = runner.strays()
            if ghost.pid in found:
                break
            time.sleep(1.0)
        check("目录已经不在了的那一个，数得到（等来的，不是睡出来的）",
              ghost.pid in found, roots_of(found + [engine.pid, ghost.pid]))
        check("临时目录还在的那一趟不算活口", engine.pid not in found,
              roots_of(found + [engine.pid, ghost.pid]))
        check("后缀里带下划线的那一趟也不算活口", underscore.pid not in found,
              roots_of(found + [underscore.pid]))
        killed, stuck = runner.sweep()
        check("兜底按 PID 收的就是那一个", ghost.pid in killed, killed)
        check("没有收不掉的", stuck == [], stuck)
        try:
            ghost.wait(timeout=30)
        except subprocess.TimeoutExpired:
            check("假活口收完就该没了", False, ghost.poll())
        else:
            check("假活口收完就该没了", ghost.poll() is not None, ghost.poll())
        check("那一台真引擎没被这一刀打断", engine.poll() is None, (engine.poll(), killed))
        check("后缀带下划线的那一台也没被打断", underscore.poll() is None,
              (underscore.poll(), killed))
    finally:
        for proc in (engine, underscore):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=60)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(under, ignore_errors=True)
    leftover = runner.strays()
    check("这一档自己也不留活口", leftover == [], leftover)


def main() -> None:
    predicate_leg()
    live_leg()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 活口令牌认得对、正在跑的那一趟碰不得、漏下的那一个收得掉，"
          "整套验收跑完机器上不攒引擎进程")


if __name__ == "__main__":
    main()
