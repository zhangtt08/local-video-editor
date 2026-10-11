"""Run the renderer's own acceptance checks, which are written in TypeScript.

`tests/suite_check.py` discovers `tests/*_check.py`, so the shell checks used to sit outside the one
documented entry point: a release could pass "the suite" while the desktop layer was never executed.
This check bundles each `.ts` with the shell's own esbuild and runs it under node, and it fails
loudly when either tool is missing rather than reporting a skip as a pass.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
NODE = "node"
# `scope_check.ts` is the one that is not prefixed `desktop_`; both patterns are shell checks.
PATTERNS = ("desktop_*_check.ts", "scope_check.ts")
ESBUILD_FLAGS = ["--bundle", "--format=esm", "--platform=node", "--log-level=error"]


def esbuild() -> list[str]:
    """The bundler, as an argv prefix that survives `CreateProcess`.

    `node_modules/.bin/esbuild` is a POSIX shell wrapper Windows cannot spawn directly, so the
    native binary is preferred and the package's node entry point is the fallback.
    """
    native = sorted((DESKTOP / "node_modules/@esbuild").glob("*/bin/esbuild.exe"))
    if native:
        return [str(native[0])]
    shim = DESKTOP / "node_modules/esbuild/bin/esbuild"
    if shim.exists():
        return [NODE, str(shim)]
    raise SystemExit(
        "FAIL: esbuild is not installed under desktop/node_modules — run `npm install` in desktop/ "
        "first; the shell checks cannot be executed without it"
    )


def run_one(path: Path, out_dir: Path) -> None:
    bundle = out_dir / f"{path.stem}.mjs"
    built = subprocess.run(
        [*esbuild(), str(path), f"--outfile={bundle}", *ESBUILD_FLAGS],
        cwd=DESKTOP,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert built.returncode == 0, f"esbuild failed for {path.name}:\n{built.stderr[-800:]}"
    executed = subprocess.run(
        [NODE, str(bundle)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    # 一条失败的断言，它那句中文在 node stderr 的**开头**；只截尾巴的话，报上来的是一串
    # `at file:///…` 的路径，看不出到底是哪条断言红了——突变套件正是靠这句话来认「红在
    # 自己那条断言上」。所以失败时两头都留。
    if executed.returncode == 0:
        output = executed.stdout[-600:] + executed.stderr[-400:]
    else:
        output = executed.stdout[-600:] + executed.stderr[:1200] + "\n…\n" + executed.stderr[-300:]
    assert executed.returncode == 0, f"{path.name} failed:\n{output}"
    tail = [line for line in executed.stdout.splitlines() if line.strip()][-1:]
    print(f"    {path.name}: {tail[0] if tail else 'ok'}")


def main() -> None:
    if not DESKTOP.joinpath("package.json").exists():
        raise SystemExit(f"FAIL: no desktop project at {DESKTOP}")
    # 每个 shell check 的 PASS 句子是中文的，还可能带「−」这类 cp936 印不出的字符；
    # 控制台按代码页走就会在 print 当场 UnicodeEncodeError，把一条绿的门禁报成崩溃。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    files = sorted({found for pattern in PATTERNS for found in (ROOT / "tests").glob(pattern)})
    assert files, "no shell checks found"
    out_dir = ROOT / "build" / "shell-checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        run_one(path, out_dir)
    print(f"PASS: {len(files)} shell checks ran under node")


if __name__ == "__main__":
    main()
