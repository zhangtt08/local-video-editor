"""字幕一次导入的上限：那个数只有一个主人，而撞上它的人看得见那两个数。

量出来的那一幕（`refusal_numbers_1266b.py`）：引擎那句英文写着 `at most 2000 cues per import`，
界面那句中文是「字幕条数太多了」——人被挡住时既不知道上限是几、也不知道自己递进来几条；
而那个 2000 过去只住在 `subtitles.parse_srt` 的一句英文里，能力表里没有它，Agent 也问不到。

这一档判四件事，缺一件就不算把这句话兑现：
  ① 上限住在契约里，能力表把它下发（`limits.subtitle_cues`）；
  ② 拒绝带着 `cues` 与 `limit` 两个数交回，而且 `cues` 恰好是 `limit + 1`（越界那一格不是猜的）；
  ③ 边界不许多也不少：正好 `limit` 条照常读进来；
  ④ 那句英文句子本身也得带着那两个数（Agent 读的是 `message`，它同样不该再自己数一遍）。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut import contracts, subtitles  # noqa: E402


def stamp(seconds: int) -> str:
    """把整数秒写成 SubRip 那一段 `HH:MM:SS,mmm`（秒位必须是两位，越界就进分与秒）。"""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


def srt(cues: int) -> str:
    """造一份正好 `cues` 条的 SubRip：每条一秒，从第 0 秒排到第 cues 秒。"""
    blocks = []
    for index in range(cues):
        blocks.append(
            f"{index + 1}\n{stamp(index)} --> {stamp(index + 1)}\n第 {index + 1} 条"
        )
    return "\n\n".join(blocks)


def main() -> int:
    limit = contracts.capabilities()["limits"]["subtitle_cues"]
    assert limit == contracts.SUBTITLE_CUE_LIMIT, (
        f"能力下发的上限与契约里那一个不是同一份：{limit} 对 {contracts.SUBTITLE_CUE_LIMIT}"
    )

    # ③ 边界：正好到上限这一份必须读得进来。
    exactly = subtitles.parse_srt(srt(limit), frame_ticks=2_352_000, offset_ticks=0)
    assert len(exactly) == limit, f"读到 {limit} 条这一格被挡了：实际 {len(exactly)} 条"

    # ② 越界一条：拒绝点名，且不涨任何状态（这条路径不写库，纯解析）。
    try:
        subtitles.parse_srt(srt(limit + 1), frame_ticks=2_352_000, offset_ticks=0)
    except contracts.EditorError as error:
        assert error.code == "SUBTITLE_LIMIT", f"拒的不是那一条：{error.code} {error.message}"
        assert error.details.get("limit") == limit, (
            f"拒绝没说上限：{error.details}"
        )
        assert error.details.get("cues") == limit + 1, (
            f"拒绝没点名这一次递进来几条：{error.details}"
        )
        # ④ 句子本身也带那两个数——Agent 读的是 message，不该让它再数一遍。
        assert str(limit) in error.message and str(limit + 1) in error.message, (
            f"引擎那句英文里没有那两个数：{error.message}"
        )
    else:
        raise AssertionError(f"多一条字幕竟然被收下了：{limit + 1} 条")

    # ① 那个数不许在解析这一层被重新写一遍（写第二份就是早晚分家的那一条）。
    source = (ROOT / "src" / "agentcut" / "subtitles.py").read_text(encoding="utf-8")
    assert "SUBTITLE_CUE_LIMIT" in source, "解析这一层不再读契约里那一个数了"
    assert str(limit) not in source, (
        f"subtitles.py 里又写了一份 {limit} 这个字面量，上限就成了两个主人"
    )

    print(
        f"PASS: 一次导入上限 {limit} 条由契约持有、能力表下发，正好 {limit} 条读得进来，"
        f"多一条以 SUBTITLE_LIMIT 点名拒绝并把 cues={limit + 1} 与 limit={limit} 一起交回"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
