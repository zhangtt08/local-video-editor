"""1.96 把 1.90 之前写成关键帧的淡搬成边窗口：搬完画面必须一个像素都不动。

1.90 改了淡的落点，但没有动老工程：那些淡今天仍是属性曲线上的两条关键帧，检查器那两个数字看不见
它，修剪与分割也不带它走（那正是当年要修的三条毛病）。帮助页给的出路是「先在曲线编辑器里清掉旧点」，
等于把引擎已经知道的事推回给人手。这一版把它做成一条命令 `clip.fade_adopt`。

认出的是老 reducer 留下的那一个形状：每头两个点，边上取 `0.0`、斜坡尽头取这条属性的静止值，插值
`ease`，而且这条属性上没有别的关键帧（老 reducer 先把整条清掉了）。松一点都不接受——夹着别的点、
起点不是 0、形状不是缓入缓出、这一头已经是窗口，全部点名拒绝，并把看到的关键帧逐条带回 details。

「画面不动」不是嘴上说的：
* 算术上，把 `0 -> resting` 做 ease 插值，与把 `resting` 乘上那条 smoothstep 是同一条曲线，于是
  40 个采样点上搬前搬后的 `sample` 必须逐点相同；
* 成片上，同一条时间线渲两遍（搬前、搬后），八个时刻的中心像素逐个比，容差 1 阶。
"""

import tempfile
from pathlib import Path

from fade_check import RATE, SECONDS, asset, build, made_clip, pixel, slate
from fastapi.testclient import TestClient

from agentcut.animation import sample
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    EditorError,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
    capabilities,
)
from agentcut.http_api import create_app
from agentcut.timeline import apply_commands

TOKEN = "fade-adopt-" + "c" * 40


def legacy(in_seconds=1.0, out_seconds=1.0, resting=1.0, offset=0, interpolation="ease", extra=()):
    """一条按 1.89 及以前的 `clip.fade` 写法摆好的片段。"""
    clip = made_clip("v2", "w", "white", None)
    clip.effects.opacity = resting
    clip.animation_offset_ticks = int(offset * T)
    head = clip.animation_offset_ticks
    tail = head + clip.duration_ticks
    keys = []
    if in_seconds:
        keys += [
            Keyframe(property="opacity", at_ticks=head, value=0.0, interpolation=interpolation),
            Keyframe(
                property="opacity",
                at_ticks=head + int(in_seconds * T),
                value=resting,
                interpolation=interpolation,
            ),
        ]
    if out_seconds:
        keys += [
            Keyframe(
                property="opacity",
                at_ticks=tail - int(out_seconds * T),
                value=resting,
                interpolation=interpolation,
            ),
            Keyframe(property="opacity", at_ticks=tail, value=0.0, interpolation=interpolation),
        ]
    keys += list(extra)
    clip.keyframes = sorted(keys, key=lambda k: (k.property, k.at_ticks))
    return clip


def project_of(clip, white, black):
    return Project(
        id="p",
        name="adopt",
        settings=SequenceSettings(width=160, height=90, sample_rate=RATE),
        tracks=[Track(id="v1", kind="video", name="底"), Track(id="v2", kind="video", name="上")],
        assets={"black": black, "white": white},
        clips={"b": made_clip("v1", "b", "black", None), "w": clip},
    )


def validate(target):
    """走一次真正的契约校验（reducer 收的是已验证的命令对象）。"""
    from agentcut.contracts import EditBatch

    return EditBatch.model_validate(
        {
            "request_id": "adopt",
            "expected_revision": target.revision,
            "commands": [{"op": "clip.fade_adopt", "clip_id": "w", "property": "opacity"}],
        }
    ).commands


def adopt_validated(target):
    return apply_commands(target, validate(target))


def reducer_suite() -> None:
    white = {
        "id": "white",
        "kind": "video",
        "label": "w",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    black = {
        "id": "black",
        "kind": "video",
        "label": "b",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    before = project_of(legacy(), white, black)
    after = adopt_validated(before)
    clip = after.clips["w"]
    assert clip.fade is not None, "搬完要有边窗口"
    assert clip.fade.window("opacity") == (T, T), clip.fade.window("opacity")
    assert clip.fade.opacity_shape == "ease_in_out"
    assert not [k for k in clip.keyframes if k.property == "opacity"], (
        "被搬走的关键帧必须删掉，否则淡被乘两次"
    )
    # 算术上的「画面不动」。
    worst = 0.0
    for index in range(1, 41):
        at = int(index * SECONDS * T / 40)
        gap = abs(sample(before.clips["w"], "opacity", at) - sample(clip, "opacity", at))
        worst = max(worst, gap)
        assert gap < 1e-12, (
            at,
            sample(before.clips["w"], "opacity", at),
            sample(clip, "opacity", at),
        )
    # 裁过的片段（animation_offset 非零）按自己那条边量。
    cropped = project_of(legacy(offset=1.0), white, black)
    cropped_after = adopt_validated(cropped)
    assert cropped_after.clips["w"].fade.window("opacity") == (T, T), cropped_after.clips["w"].fade
    for index in range(1, 41):
        at = int(index * SECONDS * T / 40)
        assert (
            abs(
                sample(cropped.clips["w"], "opacity", at)
                - sample(cropped_after.clips["w"], "opacity", at)
            )
            < 1e-12
        )
    # 静止值不是 1 也认得（老 reducer 写的就是 `clip.effects[prop]`）。
    ducked = project_of(legacy(resting=0.4), white, black)
    ducked_after = adopt_validated(ducked)
    assert ducked_after.clips["w"].fade.window("opacity") == (T, T)
    for index in range(1, 41):
        at = int(index * SECONDS * T / 40)
        assert (
            abs(
                sample(ducked.clips["w"], "opacity", at)
                - sample(ducked_after.clips["w"], "opacity", at)
            )
            < 1e-12
        )
    print(
        f"   搬得动：两头各 1 秒、关键帧清空、形状记成缓入缓出，40 点采样逐点相同（最差 {worst:.1e}"
        "）"
    )

    def refused(target, why, expect="FADE_ADOPT_SHAPE"):
        try:
            adopt_validated(target)
            raise AssertionError(f"{why}：不该搬得动")
        except EditorError as error:
            assert error.code == expect, (why, error.code)
            assert error.details, (why, error.details)
            assert error.details.get("clip_id") == "w", (why, error.details)
            assert error.status == 422, (why, error.status)
        return target

    refused(
        project_of(
            legacy(
                extra=[
                    Keyframe(
                        property="opacity", at_ticks=int(2.4 * T), value=0.7, interpolation="ease"
                    )
                ]
            ),
            white,
            black,
        ),
        "夹着别的关键帧",
    )
    refused(project_of(legacy(interpolation="linear"), white, black), "直线斜坡不是当年那个形状")
    # 只有一头的淡搬得动（老 reducer 的 mode=in/out 就是这种），静止值不是 1 也认得。
    one_sided = adopt_validated(
        project_of(legacy(in_seconds=0, out_seconds=1, resting=0.3), white, black)
    )
    assert one_sided.clips["w"].fade.window("opacity") == (0, T), one_sided.clips["w"].fade
    # 而两头都不在边上出发的斜坡不是淡：那是一条手 K 的曲线，不许半搬。
    refused(
        project_of(
            legacy(
                in_seconds=0,
                out_seconds=0,
                extra=[
                    Keyframe(property="opacity", at_ticks=T, value=0.0, interpolation="ease"),
                    Keyframe(property="opacity", at_ticks=2 * T, value=1.0, interpolation="ease"),
                ],
            ),
            white,
            black,
        ),
        "两头都没有从边上出发的淡",
    )
    # 别的属性上有关键帧不是拒绝的理由：搬的是 opacity，gain 那条曲线要原样留着。
    alongside = project_of(
        legacy(
            extra=[Keyframe(property="gain", at_ticks=int(2 * T), value=0.5, interpolation="ease")]
        ),
        white,
        black,
    )
    moved = adopt_validated(alongside)
    assert moved.clips["w"].fade.window("opacity") == (T, T), moved.clips["w"].fade
    assert [(k.property, k.at_ticks, k.value) for k in moved.clips["w"].keyframes] == [
        ("gain", int(2 * T), 0.5)
    ], moved.clips["w"].keyframes
    empty = project_of(made_clip("v2", "w", "white", None), white, black)
    refused(empty, "这条属性上根本没有关键帧")
    windowed = adopt_validated(project_of(legacy(), white, black))
    refused(windowed, "已经搬过一次，不许再搬")
    # 两头叠在一起也搬得动：窗口是从实际点位置读出来的，`in + out <= duration` 由构造保证，
    # 所以这里不需要再判一次放不下——斜坡互相越过时，读到的就是它们真正占的那两段。
    for in_s, out_s in ((2.5, 2.5), (3.5, 3.5), (3.9, 3.9), (0.2, 0.2)):
        overlapped = adopt_validated(
            project_of(legacy(in_seconds=in_s, out_seconds=out_s), white, black)
        )
        win_in, win_out = overlapped.clips["w"].fade.window("opacity")
        assert win_in + win_out <= SECONDS * T, (in_s, out_s, win_in, win_out)
        source = project_of(legacy(in_seconds=in_s, out_seconds=out_s), white, black)
        for index in range(1, 41):
            at = int(index * SECONDS * T / 40)
            before = sample(source.clips["w"], "opacity", at)
            after = sample(overlapped.clips["w"], "opacity", at)
            assert abs(before - after) < 1e-12, (in_s, out_s, at, before, after)
        # 叠过来的那段不算淡：窗口读的是各自真正占的区间。
        assert (win_in, win_out) == (
            int(min(in_s, SECONDS - out_s) * T),
            int(min(out_s, SECONDS - in_s) * T),
        ), (
            in_s,
            out_s,
            win_in,
            win_out,
        )
    print("   搬不动的四种都点名（带 clip_id、属性与逐条关键帧）；叠在一起的两头由实际点位置读出")


def http_suite() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        head = {"Authorization": f"Bearer {TOKEN}"}
        # 两道门都要照实走：TrustedHostMiddleware 只放行 127.0.0.1，所以 base_url 得跟着改；
        # 工程仓库是 lifespan 挂上去的，不进 `with` 就没有 `app.state.projects`。
        with TestClient(
            create_app(root / "db.sqlite", TOKEN), base_url="http://127.0.0.1", headers=head
        ) as client:
            caps = client.get("/v1/capabilities").json()
            assert "clip.fade_adopt" in caps["commands"], caps["commands"]
            assert caps["features"]["clip_fade_adopt"] is True, caps["features"]
            created = client.post(
                "/v1/projects", json={"request_id": "make", "name": "adopt"}
            ).json()
            pid = created["project"]["id"]
            white = {
                "id": "white",
                "kind": "video",
                "label": "w",
                "reference": "r",
                "duration_ticks": SECONDS * T,
            }
            clip = {
                "id": "w",
                "track_id": "v1",
                "asset_id": "white",
                "position_ticks": 0,
                "source_in_ticks": 0,
                "duration_ticks": SECONDS * T,
                "keyframes": [
                    {"property": "opacity", "at_ticks": 0, "value": 0.0, "interpolation": "ease"},
                    {"property": "opacity", "at_ticks": T, "value": 1.0, "interpolation": "ease"},
                ],
            }
            seeded = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": created["project"]["revision"],
                    "commands": [
                        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}},
                        {"op": "asset.register", "asset": white},
                        {"op": "clip.add", "clip": clip},
                    ],
                },
            ).json()
            assert "project" in seeded, seeded
            revision = seeded["project"]["revision"]
            dry = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "dry",
                    "expected_revision": revision,
                    "dry_run": True,
                    "commands": [{"op": "clip.fade_adopt", "clip_id": "w", "property": "opacity"}],
                },
            ).json()
            assert dry["committed"] is False, dry
            assert dry["base_revision"] == revision, dry
            assert dry["project"]["clips"]["w"]["fade"]["opacity_in_ticks"] == T, dry["project"]
            assert dry["project"]["revision"] == revision + 1, "预览给的是将要落库的那个号"
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision, (
                "dry run 不落库"
            )
            bad = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "bad",
                    "expected_revision": revision,
                    "commands": [
                        {"op": "clip.fade_adopt", "clip_id": "nope", "property": "opacity"}
                    ],
                },
            )
            assert bad.status_code == 404, bad.text[:200]
            assert bad.json()["error"]["code"] == "NOT_FOUND", bad.json()
            assert "nope" in str(bad.json()["error"]["details"]), bad.json()
            still = client.get(f"/v1/projects/{pid}").json()
            assert still["revision"] == revision, "被拒的写入不许涨版本"
            assert [k["at_ticks"] for k in still["clips"]["w"]["keyframes"]] == [0, T], (
                "被拒的写入不许动片段"
            )
            ok = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "go",
                    "expected_revision": revision,
                    "commands": [{"op": "clip.fade_adopt", "clip_id": "w", "property": "opacity"}],
                },
            ).json()
            adopted = ok["project"]["clips"]["w"]
            assert adopted["fade"]["opacity_in_ticks"] == T, adopted["fade"]
            assert adopted["fade"]["opacity_out_ticks"] == 0, adopted["fade"]
            assert adopted["fade"]["opacity_shape"] == "ease_in_out", adopted["fade"]
            assert adopted["keyframes"] == [], adopted["keyframes"]
            # 搬过一次就不是「老的关键帧淡」了：第二次点名拒绝，并且同样不涨版本。
            twice = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "twice",
                    "expected_revision": ok["project"]["revision"],
                    "commands": [{"op": "clip.fade_adopt", "clip_id": "w", "property": "opacity"}],
                },
            )
            assert twice.status_code == 422, twice.text[:200]
            assert twice.json()["error"]["code"] == "FADE_ADOPT_SHAPE", twice.json()
            assert twice.json()["error"]["details"], "拒绝必须交出看到的东西"
            assert (
                client.get(f"/v1/projects/{pid}").json()["revision"] == ok["project"]["revision"]
            ), "被拒的写入不许涨版本"
            # 回执重放不搬第二次：同一个 request_id 再来一次，看到的还是那次提交的结果。
            again = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "go",
                    "expected_revision": revision,
                    "commands": [{"op": "clip.fade_adopt", "clip_id": "w", "property": "opacity"}],
                },
            ).json()
            assert again["project"]["revision"] == ok["project"]["revision"], again["project"]
            print("   HTTP：命令在契约里、dry run 不落库、点不到与搬不动的都点名且不涨版本")


def media_suite(folder: Path) -> None:
    white = slate(folder, "aw", "0xFFFFFF", False)
    black = slate(folder, "ab", "0x000000", False)
    white_asset = asset(white, "white", "video", False)
    black_asset = asset(black, "black", "video", False)
    before = project_of(legacy(), white_asset, black_asset)
    after = adopt_validated(before)
    first, _ = build(before, folder, "adopt-before.mp4")
    second, _ = build(after, folder, "adopt-after.mp4")
    for at in (0.0, 0.25, 0.5, 1.0, 1.5, 2.5, 3.5, SECONDS - 0.05):
        left, right = pixel(first, at), pixel(second, at)
        assert abs(left - right) <= 1, (at, left, right)
    print("   成片：同一条时间线搬前搬后各渲一遍，八个时刻的中心像素逐个相同（容差 1 阶）")


def main() -> None:
    caps = capabilities()
    assert caps["features"]["clip_fade_adopt"] is True
    reducer_suite()
    http_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-fadeadopt-") as scratch:
        media_suite(Path(scratch))
    print(
        "PASS: 老的关键帧淡可以一条命令搬成边窗口，算术与成片两边都量到「画面没动」，"
        "搬不动的六种点名拒绝"
    )


if __name__ == "__main__":
    main()
