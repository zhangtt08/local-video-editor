"""Render the same frame more than once and prove the answer did not move.

Why this exists: the project has spent many rounds proving the two *ends* agree (the exported
file and the browser preview are pixel-equal). Nothing proved that one end is stable with itself.
The render chain has derived caches — frames, proxies and thumbnails share one cache directory —
and a cache key that forgets one dimension produces two failures that every existing gate walks
right past: the same instant drawn twice gives two different pictures, or two different instants
give the same picture.

So a probe reports three things and lets the caller judge: `stable` (every time re-rendered byte
for byte, in three different orders), `frames` (the hash of exactly the bytes the frame route
would hand back), and `distinct` (how many different pictures those times actually produced —
one is what a constant stub looks like, and it is not a bug report).
"""

from __future__ import annotations

import hashlib
from typing import Callable

from .contracts import EditorError

PASSES = 3
MAX_TIMES = 8


def probe(
    render: Callable[[int], tuple[bytes, int]],
    *,
    times: list[int],
    revision: int,
) -> dict:
    """Re-render each requested tick `PASSES` times in different orders and compare.

    `render(at)` is the same function the frame route calls, so this measures the shipped path
    rather than a second implementation of it. The orders are fixed, not random: a check that is
    not reproducible cannot be cited later.
    """
    cleaned = sorted({int(at) for at in times})
    if not cleaned:
        raise EditorError(
            "STABILITY_NO_TIMES",
            "pass the integer ticks to re-render, for example {at_ticks: [0, 70560000]}",
            422,
        )
    if len(cleaned) > MAX_TIMES:
        raise EditorError(
            "STABILITY_TOO_MANY",
            f"one probe reads at most {MAX_TIMES} frames; split the range and ask again",
            422,
            count=len(cleaned),
            limit=MAX_TIMES,
        )
    orders = [cleaned, list(reversed(cleaned)), cleaned[1:] + cleaned[:1]]
    seen: dict[int, str] = {}
    landed: dict[int, int] = {}
    sizes: dict[int, int] = {}
    mismatched: list[dict] = []
    for order in orders:
        for at in order:
            data, actual = render(at)
            digest = hashlib.sha256(data).hexdigest()
            known = seen.get(at)
            if known is None:
                seen[at] = digest
                landed[at] = actual
                sizes[at] = len(data)
            elif known != digest:
                mismatched.append(
                    {"at_ticks": at, "first": known[:12], "again": digest[:12]}
                )
    return {
        "frames": [
            {
                "at_ticks": at,
                "rendered_at_ticks": landed[at],
                "sha256": seen[at],
                "pixels_bytes": sizes[at],
            }
            for at in cleaned
        ],
        "passes": len(orders),
        "stable": not mismatched,
        "mismatched": mismatched,
        "distinct": len({digest for digest in seen.values()}),
        "revision": revision,
    }
