"""Every code the engine can emit has to have a Chinese sentence in the desktop.

`EngineError.explain()` replaces the engine's English message with a Chinese hint and, since 1.75,
weaves in the ids the refusal named. When a code has no hint the function falls back to
`this.message` -- the raw English sentence -- so a person pressing a Chinese button reads English
and has no idea what to do next. 1.81 found 58 such codes by diffing the two lists, which is exactly
what this gate keeps from silently rotting again: add a refusal in Python without adding the hint in
TypeScript and this fails.

No media and no engine: it reads the two sources and compares the vocabularies.
"""

import re
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
SRC = ROOT / "src/agentcut"
ENGINE_TS = ROOT / "desktop/src/engine.ts"

# Codes the desktop is not the surface for: the MCP adapter's own transport failures and job-runner
# states, which never arrive as an EditorError payload in the renderer.
NOT_UI = {
    "API_UNAVAILABLE",
    "MEDIA_UNAVAILABLE",
    "UNAUTHORIZED",
}


def engine_codes() -> set[str]:
    codes: set[str] = set()
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        codes |= set(re.findall(r'EditorError\(\s*(?:\n\s*)?"([A-Z][A-Z_0-9]{2,})"', text))
        codes |= set(re.findall(r'\bcode="([A-Z][A-Z_0-9]{2,})"', text))
        codes |= set(re.findall(r'"code":\s*"([A-Z][A-Z_0-9]{2,})"', text))
    return codes


def hints() -> list[tuple[str, str]]:
    text = ENGINE_TS.read_text(encoding="utf-8")
    block = text[text.index("const hints: Record<string, string> = {") :]
    block = block[: block.index("\n    };")]
    return re.findall(r'^\s{6}([A-Z][A-Z_0-9]{2,}): "([^"]*)",$', block, re.M)


def main() -> None:
    codes = engine_codes()
    pairs = hints()
    keys = [code for code, _ in pairs]
    table = dict(pairs)

    assert len(keys) == len(set(keys)), "duplicate keys in the hints table"
    assert len(codes) > 90, len(codes)

    silent = sorted(code for code in codes if code not in table)
    assert not silent, f"{len(silent)} codes fall through to English: {silent}"

    thin = [code for code, sentence in pairs if code in codes and len(sentence) < 12]
    assert not thin, f"hints too short to be actionable: {thin}"

    english = [
        code for code, sentence in pairs if code in codes and not re.search(r"[一-鿿]", sentence)
    ]
    assert not english, f"hints that are not Chinese: {english}"

    dead = sorted(set(keys) - codes - NOT_UI)
    for code in dead:
        # A hint for a code the engine no longer emits is harmless, but it should be a known one:
        # the MCP adapter and the job runner speak these two, and the renderer sees them too.
        assert code in {"FFMPEG_FAILED", "INTERRUPTED", "NO_OUTPUT", "STALE_REVISION"}, code

    print(
        f"PASS: {len(codes)} engine codes, {len(keys)} Chinese hints, 0 falling through to "
        f"English; {len(dead)} extra hint keys are adapter/job codes"
    )


if __name__ == "__main__":
    main()
