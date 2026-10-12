"""The one place that decides which tone curve a media file says it was authored in.

`clip.color_manage` needs a source end. Until now a person or an Agent had to name it, which is
one more thing to know about a file before touching it — while the file itself often already says
it. FFmpeg's own vocabulary is the source of truth here: a stream can carry four colour tags, and
of those four only `color_transfer` names a tone curve. The matrix coefficients (`color_space`)
describe how Y/R'G'B' is folded, and `color_primaries` describes where the primaries sit; neither
determines gamma, so this module refuses to read them as if they did. A file tagged only with
those comes back undetected, naming what it did say.

Every row of the translation lives in `contracts.COLOR_TRANSFER_TAGS` — measured against this
repo's own bundled FFmpeg — and the same table is handed to clients through
`capabilities.color_transfer_tags`, so a renderer cannot keep a second, drifting copy.
"""

from __future__ import annotations

from agentcut.contracts import COLOR_TRANSFER_TAGS, ColorSpace

# The four keys ffprobe spells on a video stream, in the order a report lists them.
TAG_KEYS = ("color_transfer", "color_space", "color_primaries", "color_range")

_BY_TAG = dict(COLOR_TRANSFER_TAGS)


def space_for_tag(tag: str | None) -> ColorSpace | None:
    """The curve this transfer tag names, or None when the table has no row for it."""
    if tag is None:
        return None
    return _BY_TAG.get(tag)


def tag_report(verified) -> dict:
    """The colour tags this probe record carries, with a key for each one the file did not say.

    `verified` may be None (an asset registered from metadata, or a generated sequence): that is
    reported as an all-`None` tag set rather than an exception, because "the file said nothing" is
    the same answer whether or not a probe ever ran.
    """
    return {key: getattr(verified, key, None) if verified is not None else None for key in TAG_KEYS}


def detect_space(verified) -> tuple[ColorSpace | None, dict]:
    """Resolve the source end from the file's own tags, or refuse with the reason and the evidence.

    The returned report always carries the raw tags, so whoever is refused can see what was read
    rather than being told a name was wrong. Reasons are closed:

    * `detected` — the transfer tag has a row in the table;
    * `no_color_tags` — the file carries no colour tag at all;
    * `no_transfer_tag` — it tags a matrix or primaries but not a tone curve;
    * `unmatched_transfer_tag` — it names a curve this engine has no curve for.
    """
    tags = tag_report(verified)
    transfer = tags["color_transfer"]
    if transfer is not None:
        space = space_for_tag(transfer)
        if space is not None:
            return space, {"reason": "detected", "tag": transfer, **tags}
        return None, {"reason": "unmatched_transfer_tag", "tag": transfer, **tags}
    if all(tags[key] is None for key in TAG_KEYS):
        return None, {"reason": "no_color_tags", "tag": None, **tags}
    return None, {"reason": "no_transfer_tag", "tag": None, **tags}
