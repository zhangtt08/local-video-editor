"""Run every feature check as its own subprocess so one entry point executes all the acceptance
evidence. `self_check.py` covers the engine seams it starts itself; the per-feature checks used to
be runnable only by hand, which meant a green documented gate said nothing about them.

    uv run python tests/suite_check.py                 # all of them, serially
    uv run python tests/suite_check.py --list          # what would run
    uv run python tests/suite_check.py grade marks     # only matching names
"""

import argparse
import os
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

    emit(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed")
    for name, _ in failures:
        emit(f"  FAILED: {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
