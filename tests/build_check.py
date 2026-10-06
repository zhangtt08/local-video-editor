"""Build cleanup must leave another instance of the same executable alive."""

import os
import runpy
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    exe = root / "desktop/resources/bin/agentcut/agentcut.exe"
    if not exe.exists():
        raise SystemExit(
            f"NOT RUN: {exe} 是可再生的构建产物；"
            "先执行 uv run python scripts/build_engine.py 再跑本检查"
        )
    cleanup = runpy.run_path(str(root / "scripts/build_engine.py"))["kill_tree"]
    with tempfile.TemporaryDirectory(prefix="agentcut-build-cleanup-") as folder:
        children = []
        try:
            for name in ("verification", "verification-other"):
                directory = Path(folder) / name
                child = subprocess.Popen(
                    [str(exe), "mcp", "--data-dir", str(directory)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={
                        **os.environ,
                        "AGENTCUT_TOKEN": "build-cleanup-check-00000000000000000000",
                    },
                    creationflags=0x08000000,
                )
                children.append((child, directory))
            time.sleep(1)
            assert all(child.poll() is None for child, _ in children)
            child, directory = children[0]
            # A vanished parent also needs cleanup; a directory prefix must not match its sibling.
            cleanup(0, exe, directory)
            child.wait(timeout=5)
            assert children[1][0].poll() is None, "cleanup stopped a different instance"
        finally:
            for child, directory in children:
                if child.poll() is None:
                    cleanup(child.pid, exe, directory)
                child.wait(timeout=5)
                child.stdin.close()
    print("PASS: verification cleanup preserves other instances of the same executable")


if __name__ == "__main__":
    main()
