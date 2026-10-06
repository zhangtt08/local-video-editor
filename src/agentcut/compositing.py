"""Picture-track blending uses native CSS and controlled FFmpeg RGB modes."""

from .contracts import BlendMode


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
