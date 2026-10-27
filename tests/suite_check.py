"""Run every feature check as its own subprocess so one entry point executes all the acceptance
evidence. `self_check.py` covers the engine seams it starts itself; the per-feature checks used to
be runnable only by hand, which meant a green documented gate said nothing about them.

    uv run python tests/suite_check.py                 # all of them, serially
    uv run python tests/suite_check.py --list          # what would run
    uv run python tests/suite_check.py grade marks     # only matching names
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
# Media checks drive real FFmpeg renders; the slowest of them sat near a quarter of an hour.
PER_CHECK_TIMEOUT_SECONDS = 2400


def discover(selectors: list[str]) -> list[Path]:
    found = sorted(path for path in TESTS.glob("*_check.py") if path.name != Path(__file__).name)
    if not selectors:
        return found
    kept = [path for path in found if any(selector in path.stem for selector in selectors)]
    missing = [
        selector for selector in selectors if not any(selector in path.stem for path in found)
    ]
    if missing:
        raise SystemExit(f"no check matches: {', '.join(missing)}")
    return kept


def emit(line: str) -> None:
    # The console on Windows may be GBK while the checks print Chinese.
    sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()


# 门禁的临时地方都建在 `%TEMP%\agentcut-xxxxxxxx` 下面（tests/scratch.py 是唯一入口）。
# 只把「那个目录已经不在了、进程还在服」算活口：那正是漏下的那一手（实测一台崩掉的
# `lease_check` 留下 4 个）；而另一趟正在跑的验收，它的临时目录还在，不该被这一刀收走。
STRAY_SCRIPT = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" |"
    " Where-Object { $_.CommandLine -match"
    " '[\\\\/]agentcut-(?:[a-z0-9]+-)?[a-z0-9]{8}(?![a-z0-9])' } |"
    " ForEach-Object { $_.ProcessId.ToString() + \" :: \" + $_.CommandLine }"
)
SCRATCH = re.compile(r"agentcut-(?:[a-z0-9]+-)?[a-z0-9]{8}(?![a-z0-9])")


def scratch_roots(command: str) -> list[str]:
    """命令行里每一个 `%TEMP%\\agentcut-xxxxxxxx`，走回完整路径（碰到空格或引号就停）。"""
    roots: list[str] = []
    for hit in SCRATCH.finditer(command or ""):
        start = hit.start()
        while start > 0 and command[start - 1] not in (" ", '"', "'"):
            start -= 1
        roots.append(command[start:hit.end()])
    # data-dir 与 media-root 常常指着同一个地方，数一份就够。
    return list(dict.fromkeys(roots))


def strays() -> list[int]:
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", STRAY_SCRIPT],
        capture_output=True, text=True, timeout=180,
    )
    leaked = []
    for line in (done.stdout or "").splitlines():
        pid, _, command = line.partition(" :: ")
        roots = scratch_roots(command)
        # 只要有一个临时地方还在，那就是别人正在跑的那一趟，不许碰。
        if pid.strip().isdigit() and roots and not any(Path(root).exists() for root in roots):
            leaked.append(int(pid.strip()))
    return leaked


def sweep() -> tuple[list[int], list[int]]:
    """先数活口，再按 PID 连子树收；交回「数到的」与「收不掉的」两个读数。"""
    found = strays()
    for pid in found:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=60)
    return found, strays()


def run(path: Path) -> tuple[bool, float, str]:
    started = time.monotonic()
    try:
        done = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(TESTS.parent),
            capture_output=True,
            timeout=PER_CHECK_TIMEOUT_SECONDS,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as expired:
        tail = (expired.stdout or b"") + (expired.stderr or b"")
        return (
            False,
            time.monotonic() - started,
            f"TIMEOUT after {PER_CHECK_TIMEOUT_SECONDS}s\n{tail[-2000:]!r}",
        )
    output = (done.stdout or b"") + (b"\n" if done.stderr else b"") + (done.stderr or b"")
    text = output.decode("utf-8", errors="replace").strip()
    return done.returncode == 0, time.monotonic() - started, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selectors", nargs="*", help="substring filters on check names")
    parser.add_argument("--list", action="store_true", help="print the selected checks and stop")
    arguments = parser.parse_args()

    checks = discover(arguments.selectors)
    if arguments.list:
        for path in checks:
            emit(path.name)
        emit(f"{len(checks)} checks")
        return 0

    failures: list[tuple[str, str]] = []
    for index, path in enumerate(checks, 1):
        emit(
            f"[{index}/{len(checks)}] {path.name} ...",
        )
        ok, seconds, text = run(path)
        emit(f"    {'PASS' if ok else 'FAIL'} {path.name} ({seconds:.1f}s)")
        if not ok:
            failures.append((path.name, text))
            emit("    ---- last output ----")
            for line in text.splitlines()[-40:]:
                emit(f"    {line}")
            emit("    ---------------------")

    found, stuck = sweep()
    if stuck:
        failures.append(("还有引擎收不掉", str(stuck)))
    emit(f"\n门禁引擎活口：数到 {len(found)} 个，收完之后剩 {len(stuck)} 个 {stuck}")
    emit(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    for name, _ in failures:
        emit(f"  FAILED: {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
