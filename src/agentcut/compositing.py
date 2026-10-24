"""Picture-track blending uses native CSS and controlled FFmpeg RGB modes."""

from .contracts import BlendMode, ChromaKey

# The key judges a distance on the 8-bit planes, so the two knobs are fractions of this full scale.

CHROMA_FULL_SCALE = 255.0

# `chroma_row` 交回的那一个通道序号在这儿的读法：0 是红平面、1 是绿、2 是蓝。导出与预览共用
# 这一张表，谁也不许自己排一次序。

CHROMA_SPILL_PLANES = ("r", "g", "b")


def chroma_row(chroma: ChromaKey) -> dict:
    """色度键折成「那一段距离」：两端读的就是这一份数，谁也不许再换算一遍。

    `low`/`high` 是 0..255 平面上的欧氏距离；`soft` 说那一段还在不在（`blend` 拧到 0 就塌成
    一刀，两端同判：`gte` 与 `step` 是同一件事）。`color` 交回 0..255 的三个整数。

    1.277 多交两样：`spill` 是那一条通道压多次（0..1，0 就是 1.276 的那一格），`spill_at` 是
    压哪一条——键色 `color` 里最亮那一条，并列时按 R→G→B 取靠前那一条。两端都只认这两个数，
    谁也不许自己再比一次大小：导出把 `spill_at` 换成那一条平面的式子，画布把它换成一根掩码。
    """
    colour = chroma.color
    rgb = [int(colour[index : index + 2], 16) for index in (1, 3, 5)]
    high = chroma.similarity * CHROMA_FULL_SCALE
    low = max(0.0, (chroma.similarity - chroma.blend) * CHROMA_FULL_SCALE)
    return {
        "color": rgb,
        "low": low,
        "high": high,
        "width": high - low,
        "soft": high > low,
        "spill": chroma.spill,
        "spill_at": rgb.index(max(rgb)),
        "inverted": chroma.inverted,
    }


def blend_track(plan, backdrop: str, picture: str, mode: BlendMode) -> str:
    """Blend RGB using backdrop coverage, then restore the track's alpha.

    Alpha must never go through multiply/screen/etc: masks, gaps and dissolves still
    determine coverage. Track clips/transitions are composed before this operation.
    """
    if mode != "normal":
        (
            base,
            lower,
            lower_alpha,
            coverage,
            colors,
            original,
            alpha,
            mask,
            mixed,
            weighted,
            restored,
        ) = [plan.tag("blend") for _ in range(11)]
        plan.filters.extend(
            [
                f"{backdrop}format=gbrap,split=3{base}{lower}{lower_alpha}",
                f"{lower_alpha}alphaextract{coverage}",
                f"{picture}format=gbrap,split=3{colors}{original}{alpha}",
                f"{alpha}alphaextract{mask}",
                f"{lower}{colors}blend=all_mode={mode}:shortest=1{mixed}",
                f"{original}{mixed}{coverage}maskedmerge{weighted}",
                f"{weighted}{mask}alphamerge,format=rgba{restored}",
            ]
        )
        backdrop, picture = base, restored
    result = plan.tag("trackmix")
    plan.filters.append(
        f"{backdrop}{picture}overlay=eof_action=pass:repeatlast=0:format=auto{result}"
    )
    return result
