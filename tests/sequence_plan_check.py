"""The analysis tools have to reach the clip the editor is looking at -- inside a comp too.

A nested composition is shown as if it were the timeline: the desktop projects it with
`sequence_view`, and every ordinary edit it submits already carries that `sequence_id`. The nine
plan endpoints never learned this, so pressing 去空白 / 统一响度 / 画面稳定 / 遮罩跟踪 / 主体跟随 /
自动闪避 on a clip inside a composition answered 「片段不在这个工程里」 for a clip that is
very much in the project, and 整轨去空白 on one of its tracks answered a cheerful "nothing to cut"
about a track it had not read at all.

Everything here is measured against real media, because that is the claim worth making: the same
analysis asked of the same clip outside and inside a composition has to agree point for point, and
the write has to land in that composition's own clip map as one revision.
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    ClipStabilizeRequest,
    DuckRequest,
    LoudnessRequest,
    MaskTrackRequest,
    ReframeRequest,
    SilenceRequest,
    SpeechCaptionsRequest,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180
SWEEP = [(0, 0.15), (T, 0.5), (2 * T - T // 30, 0.85)]
COMP = "s1"


def ffmpeg(args: list[str], target: Path) -> Path:
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin", *args, str(target)],
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return target


def plates(folder: Path) -> list[Path]:
    """One sliding box (followable), one gated tone (cuttable), one shaking frame (steadiable)."""
    slider = ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x404040:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=60x60:r=30:d=2",
            "-filter_complex",
            "[0:v][1:v]overlay=x='18+112*t':y=60:eof_action=pass:eval=frame[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ],
        folder / "slider.mp4",
    )
    voice = ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x404040:s={WIDTH}x{HEIGHT}:d=2",
            "-af",
            "volume=enable='between(t,0.4,1.2)':volume=0",
            "-c:a",
            "pcm_s16le",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
        ],
        folder / "voice.mp4",
    )
    # A window that jumps 6 px sideways every other frame over a texture with no period the tracker
    # could lock onto twice: a grid looks identical shifted by one cell, which measures as a steady
    # shot when it is anything but.
    shaky = ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=420x260:r=30:d=1,geq=lum='mod(X*X*3+Y*Y*7+X*Y*11,256)':cb=128:cr=128",
            "-vf",
            f"crop={WIDTH}:{HEIGHT}:x='40+6*mod(floor(30*t),2)':y='30'",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "14",
            "-pix_fmt",
            "yuv420p",
        ],
        folder / "shaky.mp4",
    )
    return [slider, voice, shaky]


def curves(clip: dict, names: set[str]) -> dict[str, list[tuple[int, float]]]:
    """One clip's written points on the named properties."""
    found: dict[str, list[tuple[int, float]]] = {}
    for key in clip["keyframes"]:
        if key["property"] in names:
            found.setdefault(key["property"], []).append((key["at_ticks"], key["value"]))
    return {name: sorted(points) for name, points in found.items()}


def planned(commands: list[dict]) -> dict[str, list[tuple[int, float]]]:
    """What a plan's `keyframes.replace` batch says it will write, in the same shape as `curves`."""
    return {
        command["property"]: sorted(
            (point["at_ticks"], point["value"]) for point in command["keyframes"]
        )
        for command in commands
    }


class Api:
    """One way to talk to the engine, so `expected_revision` is never a literal that drifts."""

    def __init__(self, client: TestClient, project_id: str) -> None:
        self.client = client
        self.base = f"/v1/projects/{project_id}"
        self.revision = 0

    def edit(self, request_id: str, commands: list[dict], comp: str | None = None) -> dict:
        body: dict = {
            "request_id": request_id,
            "expected_revision": self.revision,
            "commands": commands,
        }
        if comp:
            body["sequence_id"] = comp
        answer = self.client.post(self.base + "/edits", json=body)
        assert answer.status_code == 200, f"{request_id}: {answer.text}"
        self.revision = answer.json()["project"]["revision"]
        return answer.json()["project"]

    def analyse(self, path: str, request_id: str, body: dict, *, comp: str | None = None) -> dict:
        payload: dict = {"request_id": request_id, "expected_revision": self.revision, **body}
        if comp is not None:
            payload["sequence_id"] = comp
        answer = self.client.post(self.base + path, json=payload)
        assert answer.status_code < 400, f"{request_id}: {answer.status_code} {answer.text}"
        made = answer.json()
        if made.get("committed"):
            self.revision = made["project"]["revision"]
        return made

    def refused(self, path: str, request_id: str, body: dict, *, comp: str | None = None) -> str:
        payload: dict = {"request_id": request_id, "expected_revision": self.revision, **body}
        if comp is not None:
            payload["sequence_id"] = comp
        answer = self.client.post(self.base + path, json=payload)
        assert answer.status_code >= 400, f"{request_id} was accepted: {answer.text}"
        return answer.json()["error"]["code"]


def seed(verified: list[dict]) -> list[dict]:
    commands: list[dict] = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {"op": "track.add", "track": {"id": "w", "kind": "video", "name": "w"}},
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
        {"op": "track.add", "track": {"id": "b", "kind": "audio", "name": "b"}},
    ]
    for asset, source, record in zip(("a1", "a2", "a3"), ("slider", "voice", "shaky"), verified):
        commands.append(
            {
                "op": "asset.import",
                "asset_id": asset,
                "label": source,
                "probe_id": record["probe_id"],
                "verified": record,
            }
        )
    for cid, asset, track in (
        ("c", "a1", "v"),
        ("s", "a2", "a"),
        ("bed", "a2", "b"),
        ("sh", "a3", "w"),
    ):
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": cid,
                    "asset_id": asset,
                    "track_id": track,
                    "position_ticks": 0,
                    "duration_ticks": 2 * T if asset != "a3" else T,
                },
            }
        )
    commands.append(
        {
            "op": "clip.mask",
            "clip_id": "c",
            "mask": {
                "shape": "rectangle",
                "center_x": 0.15,
                "center_y": 0.5,
                "width": 2.0,
                "height": 2.0,
            },
        }
    )
    for prop, values in (
        ("mask_x", [value for _, value in SWEEP]),
        ("mask_y", [0.5] * len(SWEEP)),
    ):
        commands.append(
            {
                "op": "keyframes.replace",
                "clip_id": "c",
                "property": prop,
                "keyframes": [
                    {
                        "property": prop,
                        "at_ticks": at,
                        "value": value,
                        "interpolation": "linear",
                    }
                    for (at, _), value in zip(SWEEP, values)
                ],
            }
        )
    return commands


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        sources = plates(folder)
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        runtime = JobRuntime(folder / "api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
        runtime.ensure_worker()
        token = "seqplanchk" + "a" * 50
        app = create_app(folder / "api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            verified = [
                client.post("/v1/media/import", json={"path": str(item)}).json()["verified"]
                for item in sources
            ]
            created = client.post(
                "/v1/projects", json={"request_id": "new", "name": "comp"}
            ).json()["project"]
            api = Api(client, created["id"])
            api.edit("seed", seed(verified))

            # What the same clip's mask path yields on the root timeline, before anything is nested.
            root_plan = api.analyse(
                "/clips/c/reframe", "root-reframe", {"max_scale": 4.0, "apply": False}
            )
            expected = planned(root_plan["commands"])
            assert set(expected) == {"x", "y", "scale"}, expected
            print(
                "   reframe on the root timeline plans "
                f"{sum(len(points) for points in expected.values())} points over x/y/scale"
            )

            document = api.edit(
                "nest",
                [
                    {
                        "op": "sequence.nest",
                        "clip_ids": ["c", "s", "bed", "sh"],
                        "name": "竖屏",
                        "sequence_id": COMP,
                        "asset_id": "seq",
                        "clip_id": "cn",
                    }
                ],
            )
            inside = document["sequences"][COMP]["clips"]
            assert sorted(inside) == ["bed", "c", "s", "sh"], sorted(inside)
            assert list(document["clips"]) == ["cn"], list(document["clips"])
            assert (
                api.refused("/clips/c/reframe", "root-blind", {"max_scale": 4.0, "apply": False})
                == "NOT_FOUND"
            )
            print(
                f"   nested (revision {api.revision}): the comp holds {sorted(inside)}, the root "
                "keeps only its container -- which is why the root call is now honestly a 404"
            )

            followed = api.analyse(
                "/clips/c/reframe",
                "comp-reframe",
                {"max_scale": 4.0, "apply": True},
                comp=COMP,
            )
            landed = curves(
                followed["project"]["sequences"][COMP]["clips"]["c"], {"x", "y", "scale"}
            )
            assert landed == expected, (landed, expected)
            assert curves(followed["project"]["clips"]["cn"], {"x", "y", "scale"}) == {}, (
                "the follow wrote the container clip instead of the one inside the composition"
            )
            print(
                "   主体跟随 inside the composition writes the very same points the root plan "
                f"promised ({sum(len(p) for p in landed.values())} over x/y/scale)"
            )

            steady = api.analyse(
                "/clips/sh/stabilize",
                "comp-stabilize",
                {"strength": 1.0, "max_crop": 0.25},
                comp=COMP,
            )
            stats = steady["stabilization"]
            written = curves(
                steady["project"]["sequences"][COMP]["clips"]["sh"], {"x", "y", "scale"}
            )
            assert stats["written_points"] >= 2, stats
            assert {"x", "y", "scale"} <= set(written), written.keys()
            assert len(written["x"]) == len(written["y"]) == stats["written_points"], (
                {name: len(points) for name, points in written.items()},
                stats["written_points"],
            )
            # The cover zoom is one constant for the whole shot, so it is a pair of endpoints rather
            # than a curve of measured points -- 1.66's own shape, kept inside a comp too.
            assert len(written["scale"]) == 2, written["scale"]
            assert steady["project"]["sequences"][COMP]["clips"]["sh"]["stabilization"]
            print(
                f"   画面稳定 steadied the comp's shaky plate: {stats['written_points']} points "
                f"per curve, measured travel {stats['measured_travel']} px, "
                f"analysed {stats['analysed_frames']} frames"
            )

            path = api.analyse(
                "/mask-track",
                "comp-track",
                {"targets": [{"clip_id": "c", "from_ticks": 0, "frames": 10, "merge": False}]},
                comp=COMP,
            )
            tracked = curves(path["project"]["sequences"][COMP]["clips"]["c"], {"mask_x", "mask_y"})
            assert len(tracked["mask_x"]) >= 2, tracked
            print(
                f"   遮罩跟踪 wrote {len(tracked['mask_x'])} mask points onto the clip inside the "
                "composition"
            )

            quiet = api.analyse(
                "/clips/s/silence",
                "comp-silence",
                {"threshold_db": -40, "min_silence_ms": 100, "apply": True},
                comp=COMP,
            )
            removed = quiet["silence"]["removed_ticks"]
            clips = quiet["project"]["sequences"][COMP]["clips"]
            assert removed > 0, quiet["silence"]
            assert len(clips) > 4, sorted(clips)
            assert "s" not in clips or clips["s"]["duration_ticks"] < 2 * T, clips.get("s")
            print(
                f"   去空白 cut {removed / T:.2f}s of tone out of the comp's own clip and left "
                f"{len(clips)} clips inside it"
            )

            level = api.analyse("/clips/s/loudness", "comp-loudness", {"apply": True}, comp=COMP)
            gained = [
                item
                for item in level["project"]["sequences"][COMP]["clips"].values()
                if item["effects"]["gain"] != 1.0
            ]
            assert gained, "no comp clip carries the measured gain"
            print(
                f"   统一响度 wrote gain {gained[0]['effects']['gain']:.4f} onto {gained[0]['id']} "
                "inside the composition"
            )

            swept = api.analyse(
                "/tracks/b/silence",
                "comp-track-silence",
                {"threshold_db": -40, "min_silence_ms": 100, "apply": True},
                comp=COMP,
            )
            assert swept["silence"]["removed_ticks"] > 0, swept["silence"]
            print(
                f"   整轨去空白 read comp track b ({len(swept['silence']['clips'])} clips) and "
                f"cut {swept['silence']['removed_ticks'] / T:.2f}s -- at the root that track "
                "has no clips at all"
            )

            bed = api.analyse(
                "/tracks/b/duck",
                "comp-duck",
                {"driver_track_ids": ["a"], "depth_db": 12.0, "apply": True},
                comp=COMP,
            )
            ducked = sum(
                len(curves(item, {"gain"}).get("gain", []))
                for item in bed["project"]["sequences"][COMP]["clips"].values()
                if item["track_id"] == "b"
            )
            assert ducked >= 2, bed["duck"]["clips"]
            assert len(bed["duck"]["speech"]) > 0, bed["duck"]
            print(
                f"   自动闪避 ducked the comp's bed with {ducked} gain keyframes against "
                f"{len(bed['duck']['speech'])} speech spans from the driver track in the same comp"
            )

            metered = api.analyse(
                "/tracks/a/loudness", "comp-track-loudness", {"apply": True}, comp=COMP
            )
            assert metered["loudness"]["measured"] >= 1, metered["loudness"]
            print(
                f"   整轨响度 metered {metered['loudness']['measured']} clips of the comp's track a"
                f" and changed {metered['loudness']['changed']}"
            )

            before = api.revision
            dry = api.analyse(
                "/clips/s/loudness",
                "comp-dry",
                {"apply": True, "dry_run": True},
                comp=COMP,
            )
            assert dry["committed"] is False and api.revision == before, dry["committed"]
            replay = api.analyse(
                "/clips/s/loudness", "comp-dry", {"apply": True, "dry_run": True}, comp=COMP
            )
            # A dry run persists nothing, so there is no receipt to hit either: asking twice plans
            # twice, and neither ask moves the revision. That is the honest shape of `dry_run`.
            assert replay["replayed"] is False and api.revision == before, (
                replay["replayed"],
                api.revision,
            )
            print(
                f"   a dry run inside a comp leaves the revision at {before}, and asking again "
                "with the same request_id plans again rather than pretending to remember"
            )

            # A receipt has to remember which timeline the batch was for, because a comp's clip ids
            # are no different from another timeline's. One committed request, retried the way a
            # client that lost the answer would retry it, applies once.
            once = api.analyse(
                "/clips/s/loudness", "comp-loudness-twice", {"apply": True}, comp=COMP
            )
            assert once["committed"] is True and api.revision == before + 1, api.revision
            committed = api.revision
            api.revision = before
            again = api.analyse(
                "/clips/s/loudness", "comp-loudness-twice", {"apply": True}, comp=COMP
            )
            assert again["replayed"] is True and again["project"]["revision"] == committed, (
                again["replayed"],
                again["project"]["revision"],
                committed,
            )
            api.revision = committed
            print(
                f"   retried with the revision it had read, the same request_id replays at "
                f"revision {committed} instead of levelling the comp's audio a second time"
            )

            # The schema an Agent reads is generated from these models, for OpenAPI and for the MCP
            # tools alike, so the field being present is itself the advertisement.
            missing = [
                model.__name__
                for model in (
                    ReframeRequest,
                    SilenceRequest,
                    LoudnessRequest,
                    DuckRequest,
                    MaskTrackRequest,
                    ClipStabilizeRequest,
                    SpeechCaptionsRequest,
                )
                if "sequence_id" not in model.model_json_schema()["properties"]
            ]
            assert not missing, missing
            print(
                "   all seven analysis request contracts (nine routes) carry sequence_id, so an "
                "Agent planning inside a composition does not have to guess whether the endpoint "
                "can reach it"
            )


if __name__ == "__main__":
    main()
    print(
        "PASS: the plan endpoints analyse the timeline they are told about, and their writes land "
        "as one revision inside that nested composition"
    )
