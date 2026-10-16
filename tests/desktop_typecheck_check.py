"""Type-check the renderer and the Electron shell with the desktop's own tsc.

Why this gate exists: `npm run build` is `vite build` + `esbuild`, and neither one looks at types —
esbuild strips them. So the desktop layer could (and did, at 1.187) carry a property read that the
declared type does not have, while every other entry point stayed green: the shell checks bundle and
run under node, `released_package_check` reads needles out of the asar, and the suite never asked
TypeScript a question. That round's monitor went black in the packaged window.

Like `desktop_ts_check.py`, this fails loudly when the tool is missing: a skipped type check is not
a passed one.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
TSC = DESKTOP / "node_modules/typescript/bin/tsc"
NODE = "node"
# The floor is there to catch a broken `include` in tsconfig.json (a check that silently covers
# nothing is the failure mode), not to track growth. Measured at 1.187: 51 in src, 3 in electron.
MIN_SOURCES = 50


def typed_sources() -> list[Path]:
    return sorted(
        path
        for folder in ("src", "electron")
        for path in (DESKTOP / folder).rglob("*")
        if path.suffix in (".ts", ".tsx") and path.is_file()
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not TSC.exists():
        raise SystemExit(f"FAIL: {TSC} is not installed — run `npm install` in desktop/ first")
    sources = typed_sources()
    assert len(sources) >= MIN_SOURCES, (
        f"only {len(sources)} typed sources found; tsconfig's include no longer covers the desktop"
    )
    executed = subprocess.run(
        [NODE, str(TSC), "--noEmit", "-p", "tsconfig.json"],
        cwd=DESKTOP,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (executed.stdout + executed.stderr).strip()
    assert executed.returncode == 0, f"tsc reported problems:\n{output[:2000]}"
    print(f"PASS: tsc --noEmit is clean over {len(sources)} renderer and shell sources")


if __name__ == "__main__":
    main()
