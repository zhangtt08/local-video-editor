"""Wipe and zoom transitions: what the exporter promises about a moving edge has to be measurable in
the exported frames.

A wipe is not a cross-fade — the two shots stay opaque and a ramp across the frame decides which
pixel belongs to whom, the outgoing side carrying the complement so the sum stays at one. So the
test finds the boundary in the picture and compares where it actually is with where the compiled
ramp says it must be, in both directions, and checks the middle of the edge is a half-and-half of
the two shots rather than a brighter double-count or a black hole. The zoom is measured the same way
off a known square, and a plain dissolve is re-measured to prove the new kinds left it alone.
"""

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import TRANSITION_KINDS, TransitionKind
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.transitions import WIPE_FEATHER, ZOOM_START, envelopes

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
W, H = 320, 180
CLIP_SECONDS = 2.0
WINDOW = 1.0  # the transition overlaps the last second of the red shot with the first of the blue
RED = (192, 32, 32)
BLUE = (32, 32, 192)


def run(args, timeout=600):
    done = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
    return done.stdout


def sources(folder: Path) -> tuple[Path, Path]:
    red = folder / "red.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0xC02020:s={W}x{H}:r=30:d={CLIP_SECONDS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(red),
        ]
    )
    # The blue shot carries a centred 40x40 white square: its measured width is the zoom factor.
    blue = folder / "blue.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            (
                f"color=c=0x2020C0:s={W}x{H}:r=30:d={CLIP_SECONDS},"
                f"drawbox=x={(W - 40) // 2}:y={(H - 40) // 2}:w=40:h=40:color=white:t=fill"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(blue),
        ]
    )
    return red, blue


def frame(path: Path, at: float) -> bytes:
    return run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        timeout=300,
    )


def row(raw: bytes, y: int) -> list[tuple[int, int, int]]:
    return [
        (raw[(y * W + x) * 3], raw[(y * W + x) * 3 + 1], raw[(y * W + x) * 3 + 2]) for x in range(W)
    ]


def near(pixel, colour, tolerance=28):
    return all(abs(pixel[i] - colour[i]) <= tolerance for i in range(3))


def boundary(raw: bytes, y: int = H // 4) -> tuple[float, list[int]]:
    """Where a revealed left side stops and the shot still covering the right begins."""
    pixels = row(raw, y)
    reds = [x for x, pixel in enumerate(pixels) if near(pixel, RED)]
    blues = [x for x, pixel in enumerate(pixels) if near(pixel, BLUE)]
    assert reds and blues, (max(pixels, key=sum), min(pixels, key=sum))
    assert max(blues) < min(reds), (min(blues), max(blues), min(reds), max(reds))
    # The band between the two pure regions is the feather; its middle column is where the two
    # opaque shots share the pixel exactly, which is what proves they summed to one alpha.
    band = [(x, pixels[x]) for x in range(max(blues) + 1, min(reds))]
    balanced = (
        min(band, key=lambda item: abs(item[1][2] - item[1][0]))[1] if band else pixels[max(blues)]
    )
    return (max(blues) + min(reds)) / 2 / (W - 1), [balanced[0], balanced[1], balanced[2]]


def square_width(raw: bytes, y: int = H // 2) -> int:
    pixels = row(raw, y)
    hits = [x for x, pixel in enumerate(pixels) if pixel[0] > 150 and pixel[1] > 90]
    assert hits, "no bright region at all"
    return max(hits) - min(hits) + 1


def contract_suite() -> None:
    import typing

    literal = sorted(typing.get_args(TransitionKind))
    table = sorted(item["id"] for item in TRANSITION_KINDS)
    assert literal == table, (literal, table)
    assert all(item["label"] for item in TRANSITION_KINDS), TRANSITION_KINDS
    print(f"   {len(table)} transition kinds; the contract Literal and the table name the same set")


def envelope_suite(folder: Path) -> None:
    red, blue = sources(folder)
    project = build_project(red, blue, "wipe_from_left")
    curves = envelopes(project)
    incoming, outgoing = curves["right"], curves["left"]
    assert incoming["wipe"] and incoming["wipe"]["kind"] == "wipe_from_left"
    assert not incoming["wipe"]["invert"], "the incoming shot is the one being revealed"
    assert outgoing["wipe"] and outgoing["wipe"]["invert"], (
        "the outgoing shot carries the complement"
    )
    assert [point["value"] for point in incoming["picture"]] == [1.0, 1.0, 1.0, 1.0], incoming[
        "picture"
    ]
    assert [point["value"] for point in outgoing["picture"]] == [1.0, 1.0, 1.0, 1.0], outgoing[
        "picture"
    ]
    assert incoming["sound"][0]["value"] == 0.0 and incoming["sound"][-1]["value"] == 1.0, incoming[
        "sound"
    ]
    assert outgoing["sound"][0]["value"] == 1.0, outgoing["sound"]
    progress = {round(point["offset"], 4): point["value"] for point in incoming["wipe"]["curve"]}
    assert progress[0.0] == 0.0 and progress[0.5] == 1.0, progress
    assert abs(progress[0.25] - 0.5) < 1e-9, progress
    assert all(point["value"] == 1.0 for point in incoming["scale"]), (
        "a wipe must not resize anything"
    )

    zoomed = envelopes(build_project(red, blue, "zoom_in"))
    scale = {round(point["offset"], 4): point["value"] for point in zoomed["right"]["scale"]}
    assert abs(scale[0.0] - ZOOM_START) < 1e-9 and abs(scale[0.5] - 1.0) < 1e-9, scale
    assert zoomed["right"]["wipe"] is None
    assert zoomed["right"]["picture"][0]["value"] == 0.0, "zoom_in still dissolves in"
    shrunk = envelopes(build_project(red, blue, "zoom_out"))
    tail = {round(point["offset"], 4): point["value"] for point in shrunk["left"]["scale"]}
    assert abs(tail[0.5] - 1.0) < 1e-9 and abs(tail[1.0] - 0.6) < 1e-9, tail
    print(
        "   envelopes: a wipe leaves both picture weights at 1.0 and fades only the sound; "
        f"zoom_in runs {ZOOM_START:g}->1 and zoom_out 1->{1 + (0.6 - 1):g}"
    )


def build_project(red: Path, blue: Path, kind: str):
    from agentcut.contracts import Project, VerifiedMedia
    from agentcut.timeline import validate_timeline

    def verified(path: Path, name: str) -> dict:
        return VerifiedMedia.model_validate(
            {
                "probe_id": name,
                "path": str(path),
                "kind": "video",
                "label": name,
                "size_bytes": path.stat().st_size,
                "content_sha256": "0" * 64,
                "duration_ticks": int(CLIP_SECONDS * T),
                "width": W,
                "height": H,
                "has_audio": False,
            }
        ).model_dump()

    project = Project.model_validate(
        {
            "id": "p",
            "name": "wipe",
            "settings": {
                "width": W,
                "height": H,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "ar": {
                    "id": "ar",
                    "kind": "video",
                    "label": "red",
                    "reference": "r",
                    "duration_ticks": int(CLIP_SECONDS * T),
                    "verified": verified(red, "ar"),
                },
                "ab": {
                    "id": "ab",
                    "kind": "video",
                    "label": "blue",
                    "reference": "r",
                    "duration_ticks": int(CLIP_SECONDS * T),
                    "verified": verified(blue, "ab"),
                },
            },
            "clips": {
                "left": {
                    "id": "left",
                    "asset_id": "ar",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": int(CLIP_SECONDS * T),
                },
                "right": {
                    "id": "right",
                    "asset_id": "ab",
                    "track_id": "v",
                    # The reducer slides the incoming clip back by the overlap when a transition is
                    # set, and the validator only accepts that shape: build it the same way.
                    "position_ticks": int((CLIP_SECONDS - WINDOW) * T),
                    "duration_ticks": int(CLIP_SECONDS * T),
                    "transition_in": {
                        "from_clip_id": "left",
                        "kind": kind,
                        "duration_ticks": int(WINDOW * T),
                    },
                },
            },
        }
    )
    validate_timeline(project)
    return project


def export(folder: Path, project, preset_id: str, name: str) -> Path:
    from agentcut.render import compile_render_plan

    plan = compile_render_plan(project, preset_id)
    work = folder / f"work-{name}"
    work.mkdir(exist_ok=True)
    for file, body in plan.text_files.items():
        (work / file).write_text(body, encoding="utf-8")
    for file, body in plan.binary_files.items():
        (work / file).write_bytes(body)
    out = folder / f"{name}.mp4"
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=work,
        capture_output=True,
        timeout=600,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-700:]
    return out


def media_suite(folder: Path) -> None:
    red, blue = sources(folder)
    expected_edge = {
        0.25: 0.25 * (1 + WIPE_FEATHER),
        0.5: 0.5 * (1 + WIPE_FEATHER),
        0.75: 0.75 * (1 + WIPE_FEATHER),
    }
    left = export(
        folder, build_project(red, blue, "wipe_from_left"), "h264-source-quality", "wipe-left"
    )
    edges = {}
    for at, p in ((1.25, 0.25), (1.5, 0.5), (1.75, 0.75)):
        raw = frame(left, at)
        edge, middle = boundary(raw)
        edges[p] = edge
        # The edge crosses the whole frame in one second, so one frame of seek rounding is
        # 1/30 of the width; the three probes are a quarter-frame apart, far outside that.
        assert abs(edge - expected_edge[p]) < 0.05, (at, edge, expected_edge[p])
        # The most balanced column of the feather band is the two shots sharing one pixel. Half of
        # red plus half of blue is (112,32,112); double-counting would read (224,64,224) and a hole
        # would read black, so the discriminator is coarse — the band is ~6 px wide through a 4:2:0
        # encode, which is why the tolerance is levels rather than exact.
        assert abs(middle[0] - (RED[0] + BLUE[0]) / 2) < 40, (at, middle)
        assert abs(middle[2] - (RED[2] + BLUE[2]) / 2) < 40, (at, middle)
        assert middle[1] < 60, (at, middle)
    assert edges[0.25] < edges[0.5] < edges[0.75], edges
    print(
        "   wipe_from_left: the edge sits at "
        + ", ".join(f"p={p} {edges[p]:.3f} (ramp says {expected_edge[p]:.3f})" for p in edges)
    )

    def blue_share(raw: bytes) -> float:
        pixels = row(raw, H // 4)
        return sum(1 for pixel in pixels if near(pixel, BLUE)) / len(pixels)

    # At the first frame of the window nothing is revealed yet; after it, the incoming shot owns the
    # whole frame. Both ends are what make the middle measurements a travel rather than a jitter.
    assert blue_share(frame(left, 1.0)) < 0.01, blue_share(frame(left, 1.0))
    assert blue_share(frame(left, 2.05)) > 0.97, blue_share(frame(left, 2.05))

    right = export(
        folder, build_project(red, blue, "wipe_from_right"), "h264-source-quality", "wipe-right"
    )
    mirrored = {}
    for at, p in ((1.25, 0.25), (1.5, 0.5), (1.75, 0.75)):
        pixels = row(frame(right, at), H // 4)
        reds = [x for x, pixel in enumerate(pixels) if near(pixel, RED)]
        blues = [x for x, pixel in enumerate(pixels) if near(pixel, BLUE)]
        # The mirror image: the incoming shot is uncovered from the right border, so blue owns the
        # right-hand side and red the left.
        assert max(reds) < min(blues), (at, max(reds), min(blues))
        covered = 1 - (max(reds) + 1) / (W - 1)
        assert abs(covered - p * (1 + WIPE_FEATHER)) < 0.05, (at, covered, p)
        mirrored[p] = covered
    assert mirrored[0.25] < mirrored[0.5] < mirrored[0.75], mirrored
    print(
        "   wipe_from_right: the uncovered share grows "
        + ", ".join(f"p={p} {mirrored[p]:.3f}" for p in sorted(mirrored))
    )

    zoom = export(folder, build_project(red, blue, "zoom_in"), "h264-source-quality", "zoom-in")
    widths = {0.25: None, 0.5: None, 1.0: None}
    for at, p in ((1.25, 0.25), (1.5, 0.5), (2.05, 1.0)):
        widths[p] = square_width(frame(zoom, at))
    assert widths[1.0] == 40, widths
    assert 46 <= widths[0.5] <= 58, widths
    assert widths[0.25] > widths[0.5] > widths[1.0], widths
    print(
        f"   zoom_in: the 40 px square measures {widths[0.25]} / {widths[0.5]} / {widths[1.0]} px "
        f"at p=0.25 / 0.5 / 1 (ramp starts at {ZOOM_START:g}x)"
    )

    plain = export(folder, build_project(red, blue, "dissolve"), "h264-source-quality", "dissolve")
    mid = row(frame(plain, 1.5), H // 4)[W // 2]
    assert (
        abs(mid[0] - (RED[0] + BLUE[0]) / 2) < 26 and abs(mid[2] - (RED[2] + BLUE[2]) / 2) < 26
    ), mid
    whole = row(frame(plain, 1.5), H // 4)
    assert all(near(pixel, mid, 26) for pixel in whole[::17]), "a dissolve must stay spatially even"
    print("   regression: a plain dissolve still cross-fades evenly across the whole frame")


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "wipe-db.sqlite3", [folder], folder / "wipe-cache", FFMPEG, FFPROBE
    )
    runtime = JobRuntime(
        folder / "wipe-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    runtime.ensure_worker()
    token = "wipecheck" + "e" * 55
    app = create_app(folder / "wipe-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        ids = [item["id"] for item in caps["transition_kinds"]]
        assert len(ids) == len(TRANSITION_KINDS) and "wipe_from_top" in ids, ids
        assert caps["features"]["wipe_transitions"] and caps["features"]["zoom_transitions"], caps[
            "features"
        ]
        red, blue = sources(folder)
        probes = {
            name: client.post("/v1/media/import", json={"path": str(path)}).json()
            for name, path in (("red", red), ("blue", blue))
        }
        pid = client.post("/v1/projects", json={"request_id": "new", "name": "wipe"}).json()[
            "project"
        ]["id"]
        path = f"/v1/projects/{pid}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "ar",
                        "label": "red",
                        "probe_id": probes["red"]["id"],
                        "verified": probes["red"]["verified"],
                    },
                    {
                        "op": "asset.import",
                        "asset_id": "ab",
                        "label": "blue",
                        "probe_id": probes["blue"]["id"],
                        "verified": probes["blue"]["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "left",
                            "asset_id": "ar",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(CLIP_SECONDS * T),
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "right",
                            "asset_id": "ab",
                            "track_id": "v",
                            "position_ticks": int(CLIP_SECONDS * T),
                            "duration_ticks": int(CLIP_SECONDS * T),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        for kind in ("wipe_from_top", "wipe_from_bottom", "zoom_out"):
            applied = client.post(
                path + "/edits",
                json={
                    "request_id": f"kind-{kind}",
                    "expected_revision": revision,
                    "commands": [
                        {
                            "op": "transition.set",
                            "clip_id": "right",
                            "from_clip_id": "left",
                            "kind": kind,
                            "duration_ticks": int(WINDOW * T),
                        }
                    ],
                },
            )
            assert applied.status_code == 200, applied.text
            stored = applied.json()["project"]["clips"]["right"]["transition_in"]
            assert stored["kind"] == kind, stored
            revision = applied.json()["project"]["revision"]

        bogus = client.post(
            path + "/edits",
            json={
                "request_id": "bogus",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "transition.set",
                        "clip_id": "right",
                        "from_clip_id": "left",
                        "kind": "wipe_sideways",
                        "duration_ticks": int(WINDOW * T),
                    }
                ],
            },
        )
        assert bogus.status_code == 422, bogus.text
        assert client.get(path).json()["revision"] == revision, (
            "a refused kind must not burn a revision"
        )
        print(f"   {len(ids)} kinds round-trip through the contract; an invented kind is refused")


def main() -> None:
    import tempfile

    contract_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-wipe-") as scratch:
        folder = Path(scratch)
        envelope_suite(folder)
        media_suite(folder)
        http_suite(folder)
    print(
        "PASS: wipes put the edge where the ramp says and the shots sum to one across it, "
        "the zoom scales a known square, and a plain dissolve is unchanged"
    )


if __name__ == "__main__":
    main()
