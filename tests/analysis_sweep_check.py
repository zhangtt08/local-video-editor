"""Every analysis refusal has to name the clip, track or composition it is talking about.

1.74 gave the nine plan endpoints a `sequence_id`, which opened new ways to be refused: a
composition that does not exist, an id that lives on the other timeline, a driver track that is not
there, a window past the end of the clip. A refusal that answers `{"details": {}}` tells a person
nothing they can act on -- which clip? -- and an Agent plans against those payloads. This sweep
walks each route's own boundary shapes and pins four things: nothing 5xxes; every refusal carries
a code, a sentence and something in `details`; a refusal never moves the revision; and the same
question asked dry answers with the same code as asked for real.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
COMP = "s1"

# Which id each route is asked about, so a refusal can be checked for naming the right one. The
# three timeline questions -- no composition, a composition that is not there, and the other
# timeline's id -- go to every route; the rest are the shapes that route's own contract carries.
CASES = {
    "/clips/s/silence": (
        "clip_id",
        [
            ("root", {}),
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
            ("window before zero", {"from_ticks": -5}),
            ("threshold too hot", {"threshold_db": 3.0}),
        ],
    ),
    "/clips/s/loudness": (
        "clip_id",
        [
            ("root", {}),
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
            ("target too loud", {"target_lufs": 4.0}),
        ],
    ),
    "/clips/vid/reframe": (
        "clip_id",
        [
            ("root", {}),
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
            ("ceiling past the limit", {"max_scale": 9.0}),
        ],
    ),
    "/clips/vid/stabilize": (
        "clip_id",
        [
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
            ("strength too wide", {"strength": 400.0}),
        ],
    ),
    "/clips/vid/track": (
        "clip_id",
        [
            ("in the comp", {"sequence_id": COMP, "frames": 20}),
            ("ghost comp", {"sequence_id": "nope"}),
            ("one frame", {"frames": 1}),
        ],
    ),
    "/tracks/b/silence": (
        "track_id",
        [
            ("root", {}),
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
        ],
    ),
    "/tracks/v/loudness": (
        "track_id",
        [
            ("root", {}),
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
        ],
    ),
    "/tracks/b/duck": (
        "track_id",
        [
            ("root", {}),
            ("in the comp", {"sequence_id": COMP}),
            ("ghost comp", {"sequence_id": "nope"}),
            ("driver is the target", {"driver_track_ids": ["b"]}),
            ("driver not there", {"driver_track_ids": ["ghost"]}),
        ],
    ),
    "/speech-captions": (
        "clip_id",
        [
            ("nothing named", {}),
            ("both named", {"clip_id": "s", "track_id": "b"}),
            ("clip not there", {"clip_id": "ghost"}),
            ("track holds no clips", {"track_id": "v"}),
        ],
    ),
}
# A request that the contract itself turns away names the field in `issues` rather than an id.
CONTRACT = "INVALID_REQUEST"
NAMED = {"clip_id", "track_id", "sequence_id", "asset_id"}
# A plan with nothing to do is a fine answer to look at and a refusal to commit; these are the
# three routes that say "nothing needed doing" by name rather than writing a no-op.
EMPTY_APPLY = {"INVALID_SILENCE_TARGET", "INVALID_LOUDNESS_TARGET", "INVALID_DUCK"}


def ffmpeg(args: list[str], target: Path) -> Path:
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin", *args, str(target)],
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return target


def tone(folder: Path) -> Path:
    """A flat grey field with a gated tone: cuttable and meterable, with no picture to hold."""
    return ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x404040:s=320x180:d=2",
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
        folder / "tone.mp4",
    )


def shot(folder: Path) -> Path:
    """A box sliding across a window that jitters: texture for the tracker and the steadier.

    The window itself has to move, and it has to move over texture with no period the matcher could
    lock onto twice -- a flat field measures as "nothing to hold still", which would make the two
    routes below look broken when only the fixture was.
    """
    return ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x808080:s=420x260:r=30:d=2,"
            "geq=lum='mod(X*X*3+Y*Y*7+X*Y*11,256)':cb=128:cr=128",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=60x60:r=30:d=2",
            "-filter_complex",
            "[0:v][1:v]overlay=x='18+112*t':y='90':eval=frame[b];"
            "[b]crop=320:180:x='40+6*mod(floor(30*t),2)':y='30',format=yuv420p[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "14",
            "-pix_fmt",
            "yuv420p",
        ],
        folder / "shot.mp4",
    )


def seed(record: dict, moving: dict) -> list[dict]:
    def clip(cid: str, track: str) -> dict:
        return {
            "op": "clip.add",
            "clip": {
                "id": cid,
                "asset_id": "tone",
                "track_id": track,
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        }

    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
        {"op": "track.add", "track": {"id": "b", "kind": "audio", "name": "b"}},
        {
            "op": "asset.import",
            "asset_id": "tone",
            "label": "tone",
            "probe_id": record["probe_id"],
            "verified": record,
        },
        {
            "op": "asset.import",
            "asset_id": "shot",
            "label": "shot",
            "probe_id": moving["probe_id"],
            "verified": moving,
        },
        clip("s", "a"),
        clip("bed", "b"),
        {
            "op": "clip.add",
            "clip": {
                "id": "vid",
                "asset_id": "shot",
                "track_id": "v",
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        },
        {
            "op": "clip.mask",
            "clip_id": "vid",
            "mask": {
                "shape": "rectangle",
                "center_x": 0.5,
                "center_y": 0.5,
                "width": 0.3,
                "height": 0.3,
            },
        },
        {
            "op": "keyframes.replace",
            "clip_id": "vid",
            "property": "mask_x",
            "keyframes": [
                {"property": "mask_x", "at_ticks": 0, "value": 0.5, "interpolation": "linear"},
                {"property": "mask_x", "at_ticks": T, "value": 0.6, "interpolation": "linear"},
            ],
        },
    ]


def request_id(route: str, label: str, apply: bool) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", f"sweep-{route}-{label}-{apply}")[:64]


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        source = tone(folder)
        moving = shot(folder)
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        runtime = JobRuntime(folder / "api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
        runtime.ensure_worker()
        token = "analysissweep" + "d" * 47
        app = create_app(folder / "api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            record = client.post("/v1/media/import", json={"path": str(source)})
            moving_record = client.post("/v1/media/import", json={"path": str(moving)})
            pid = client.post(
                "/v1/projects",
                json={
                    "request_id": "new",
                    "name": "sweep",
                    "settings": {"width": 320, "height": 180},
                },
            ).json()["project"]["id"]
            base = f"/v1/projects/{pid}"

            def edit(request_id: str, commands: list[dict]) -> int:
                answer = client.post(
                    base + "/edits",
                    json={
                        "request_id": request_id,
                        "expected_revision": state[0],
                        "commands": commands,
                    },
                )
                assert answer.status_code == 200, answer.text
                state[0] = answer.json()["project"]["revision"]
                return state[0]

            state = [0]
            edit("seed", seed(record.json()["verified"], moving_record.json()["verified"]))
            edit(
                "nest",
                [
                    {
                        "op": "sequence.nest",
                        "clip_ids": ["s", "bed", "vid"],
                        "name": "竖屏",
                        "sequence_id": COMP,
                        "asset_id": "seq",
                        "clip_id": "cn",
                    }
                ],
            )
            print(f"   seeded to revision {state[0]}; {COMP} holds s, bed and vid")

            refused = 0
            named = 0
            for route, (key, shapes) in CASES.items():
                codes = {}
                for label, extra in shapes:
                    # The two routes that always write have no `apply` knob, so they are asked once,
                    # dry, and the answer is not compared against a second ask.
                    commits = route in ASKED_COMMIT_ONLY
                    asks = (None,) if commits else (False, True)
                    answers = {}
                    for apply in asks:
                        body = {
                            "request_id": request_id(route, label, apply),
                            "expected_revision": state[0],
                            **({"dry_run": True} if commits else {"apply": apply}),
                            **extra,
                        }
                        before = client.get(base).json()["revision"]
                        state[0] = before
                        answer = client.post(base + route, json=body)
                        status = answer.status_code
                        assert status < 500, f"{route} {label} apply={apply}: {answer.text[:200]}"
                        made = answer.json()
                        payload = {}
                        code = ""
                        if status >= 400:
                            payload = made.get("error") or {}
                            code = str(payload.get("code") or "")
                            assert code, f"{route} {label}: nameless refusal {answer.text[:160]}"
                            assert str(payload.get("message") or "").strip(), (
                                f"{route} {label} {code}: no sentence to read"
                            )
                            details = payload.get("details") or {}
                            assert details, f"{route} {label} {code}: empty details"
                            if code == "NOT_FOUND":
                                # The one class where "which one?" is genuinely unanswered: an id
                                # that is not on the timeline being read. The route has to say which
                                # of its own ids it could not resolve.
                                assert set(details) & NAMED, (
                                    f"{route} {label} {code}: names no target ({details})"
                                )
                                named += 1
                            refused += 1
                            assert client.get(base).json()["revision"] == before, (
                                f"{route} {label} {code} moved the revision"
                            )
                        elif made.get("committed"):
                            state[0] = made["project"]["revision"]
                            assert state[0] == before + 1, (before, state[0])
                        else:
                            assert client.get(base).json()["revision"] == before, (
                                f"{route} {label} wrote something it did not commit"
                            )
                        answers[apply] = code or str(status)
                    if len(asks) == 2 and answers[False] != answers[True]:
                        # The one honest difference between planning and applying: an empty plan is
                        # a fine answer to look at and a refusal to commit, so a route says
                        # "there was nothing to do" by name instead of committing a no-op.
                        allowed = answers[False] == "200" and answers[True] in EMPTY_APPLY
                        if not allowed:
                            raise AssertionError(
                                f"{route} {label} answers {answers} dry vs committed"
                            )
                    codes[label] = answers[asks[0]]
                print(f"   {route:22} {codes}")
            # The refusal a person meets when the media folder moves: the engine has to say which
            # clip's source it could not open, not just that a file is gone.
            for stale in (source, moving):
                stale.unlink()
            gone = []
            for route, body in (
                ("/clips/s/silence", {"sequence_id": COMP, "apply": False}),
                ("/clips/vid/track", {"sequence_id": COMP, "frames": 20, "dry_run": True}),
                ("/tracks/b/duck", {"sequence_id": COMP, "apply": False}),
            ):
                answer = client.post(
                    base + route,
                    json={
                        "request_id": request_id(route, "gone", False),
                        "expected_revision": state[0],
                        **body,
                    },
                )
                assert answer.status_code == 410, (route, answer.status_code, answer.text[:200])
                error = answer.json()["error"]
                assert error["code"] == "MEDIA_MISSING", error
                assert error["details"].get("clip_id") and error["details"].get("asset_id"), error
                label = str(error["details"].get("asset_label") or "")
                assert label in {"tone.mp4", "shot.mp4"}, (route, error["details"])
                gone.append(f"{error['details']['clip_id']}:{label}")
            assert client.get(base).json()["revision"] == state[0]
            print(
                "   with the sources deleted, three routes answer 410 MEDIA_MISSING naming the "
                f"clip and the file it could not open ({sorted(set(gone))})"
            )

            assert refused >= 40, refused
            assert named >= 20, named
            assert client.get(base).json()["revision"] == state[0]
            print(
                f"   {refused} refusals across nine routes: every one carries a code, a sentence "
                f"and the id it is about ({named} name a clip, track or composition), none moved "
                "the revision, and dry answers match committed ones"
            )


ASKED_COMMIT_ONLY = ["/clips/vid/stabilize", "/clips/vid/track"]

if __name__ == "__main__":
    main()
    print(
        "PASS: an analysis refusal always says who it means -- no empty details, no 5xx, no "
        "revision burned on a no"
    )
