"""Frozen entry point for the AgentCut engine (used only by the PyInstaller build).

Two reasons this shim exists instead of handing `src/agentcut/__main__.py` to PyInstaller:

* `agentcut.__main__` uses relative imports, so it cannot run as a top-level frozen script; and
* a frozen bootloader ignores `PYTHONIOENCODING` / `PYTHONUTF8` (PyInstaller configures the
  interpreter with `use_environment = 0`), so `print(json.dumps(..., ensure_ascii=False))` would go
  out in the ANSI code page -- cp936 on this machine -- and Electron's `chunk.toString("utf-8")`
  would garble every path that contains Chinese characters. Forcing UTF-8 on the standard streams
  here keeps the packaged CLI byte-for-byte compatible with `python -m agentcut`.

The CLI surface itself is untouched: this calls the same `main()` the console script uses.
"""

import sys

from agentcut.__main__ import main


def _force_utf8() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # already detached / not a text stream
                pass


if __name__ == "__main__":
    _force_utf8()
    main()
