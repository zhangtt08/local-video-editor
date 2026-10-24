"""One track with nothing on it has to say the same thing in all four track routes.

1.74 taught the analysis endpoints to read a nested composition, and with it came the shape
「this track holds no clips」 in `speech-captions`. The other three never learned it: pointing
/tracks/{id}/silence, /loudness or /duck at a track that exists but is empty answered 200 with
`measured: 0`, and asking to *apply* that claimed the clips were already aligned -- about a track
that holds none. After nesting a clip away, the root's same-named track is exactly that case, so
the answer the editor gets is either a shrug or a false reassurance.

This gate pins the refusal for all four routes, and the control that a track which does have clips
is never refused that way (its own reason -- skippable clips, no quiet stretch -- still has to come
through). No renders: the guard fires before any FFmpeg call, so this runs in about a second.
"""

import tempfile
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
ROUTES = (
    ("silence", "/silence", {"threshold_db": -35.0, "min_silence_ms": 250}),
    ("loudness", "/loudness", {"target_lufs": -16.0}),
    ("duck", "/duck", {"depth_db": 9.0}),
    ("captions", "/speech-captions", {}),
)
HOLDS = "this track holds no clips"
NOT_IN = "track is not in this project"


def write_wav(folder: Path, name: str, amplitude: int) -> Path:
    """A real file the engine can probe: one second at 48 kHz mono, PCM16."""
    path = folder / name
    frames = bytearray()
    for number in range(48_000):
        value = amplitude if number % 2 else -amplitude
        frames += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(bytes(frames))
    assert path.is_file() and path.stat().st_size > 96_000, path.stat()
    return path


def silent_wav(folder: Path) -> Path:
    return write_wav(folder, "silent.wav", 0)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        media = MediaService(
            folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE, asr_dirs=[]
        )
        exports = folder / "exports"
        exports.mkdir()
        jobs = JobRuntime(folder / "db.sqlite3", FFMPEG, exports, [exports, folder])
        jobs.ensure_worker()
        token = "t" * 32
        with TestClient(
            create_app(folder / "db.sqlite3", token, media=media, jobs=jobs),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            probe = client.post("/v1/media/import", json={"path": str(silent_wav(folder))}).json()
            assert probe["verified"]["has_audio"] is True, probe
            beep = client.post(
                "/v1/media/import", json={"path": str(write_wav(folder, "beep.wav", 12_000))}
            ).json()
            assert beep["verified"]["has_audio"] is True, beep
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "new",
                    "name": "空轨",
                    "settings": {
                        "width": 320,
                        "height": 180,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            pid = created["id"]
            seeded = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "声音"}},
                        {
                            "op": "track.add",
                            "track": {"id": "empty", "kind": "audio", "name": "空的"},
                        },
                        {
                            "op": "asset.import",
                            "asset_id": "w",
                            "label": "w",
                            "probe_id": probe["id"],
                            "verified": probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "w",
                                "track_id": "a",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                        {"op": "track.add", "track": {"id": "m", "kind": "audio", "name": "混合"}},
                        {
                            "op": "asset.import",
                            "asset_id": "k",
                            "label": "k",
                            "probe_id": beep["id"],
                            "verified": beep["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "ct",
                                "asset_id": "k",
                                "track_id": "m",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "cs",
                                "asset_id": "w",
                                "track_id": "m",
                                "position_ticks": T,
                                "duration_ticks": T,
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            revision = seeded.json()["project"]["revision"]

            def ask(path: str, track: str, body: dict, request_id: str):
                payload = {"request_id": request_id, "expected_revision": revision, **body}
                if path == "/speech-captions":
                    # 自动字幕 is a project-level route that names the track in the body.
                    payload["track_id"] = track
                    return client.post(f"/v1/projects/{pid}/speech-captions", json=payload)
                return client.post(f"/v1/projects/{pid}/tracks/{track}{path}", json=payload)

            refusals = 0
            for name, path, body in ROUTES:
                ghost = ask(path, "nope", body, f"ghost-{name}")
                assert ghost.status_code == 404, (name, ghost.status_code, ghost.text)
                assert ghost.json()["error"]["message"] == NOT_IN, (name, ghost.json())
                assert ghost.json()["error"]["details"] == {"track_id": "nope"}, (
                    name,
                    ghost.json(),
                )
                vacant = ask(path, "empty", body, f"vacant-{name}")
                assert vacant.status_code == 404, (name, vacant.status_code, vacant.text)
                assert vacant.json()["error"]["message"] == HOLDS, (name, vacant.json())
                assert vacant.json()["error"]["details"] == {"track_id": "empty"}, (
                    name,
                    vacant.json(),
                )
                # Applying an empty plan must not be the way this comes back either.
                pushed = ask(path, "empty", dict(body, apply=True), f"apply-{name}")
                assert pushed.status_code == 404, (name, pushed.text)
                assert pushed.json()["error"]["message"] == HOLDS, (name, pushed.json())
                refusals += 3

            # The control doubles as the reason this fixture is digital silence: a clip whose window
            # holds nothing used to answer 502 with empty details -- FFmpeg prints `-inf dBFS` for
            # the peak and no float regex matched it. It now answers 422 and names the clip.
            for name, path, body in ROUTES:
                occupied = ask(path, "a", body, f"occupied-{name}")
                assert occupied.status_code != 502, (name, occupied.status_code, occupied.text)
                assert HOLDS not in occupied.text, (name, occupied.text)
                if name == "loudness":
                    # The whole-track button reports the unreadable clip instead of refusing for it,
                    # so one silent clip cannot stop the rest of the track being aligned.
                    report = occupied.json()["loudness"]
                    assert occupied.status_code == 200, (name, occupied.text)
                    assert report["measured"] == 0 and report["changed"] == 0, report
                    assert [item["clip_id"] for item in report["clips"]] == ["c"], report
                    assert "digital silence" in report["clips"][0]["skipped"], report
                else:
                    assert occupied.status_code in (200, 410, 422), (name, occupied.text)
                    if name == "captions":
                        # This deployment has no model folder, so the refusal must say which
                        # language and where it looked -- it used to answer with empty details.
                        error = occupied.json()["error"]
                        assert error["code"] == "SUBTITLES_MODEL_MISSING", error
                        assert error["details"]["language"] == "zh", error
                        assert error["details"]["expected_model"], error
                        assert isinstance(error["details"]["searched_dirs"], list), error
                    elif occupied.status_code != 200:
                        assert occupied.json()["error"]["details"], (name, occupied.json())

            mixed = client.post(
                f"/v1/projects/{pid}/tracks/m/loudness",
                json={"request_id": "mixed", "expected_revision": revision},
            )
            assert mixed.status_code == 200, mixed.text
            report = mixed.json()["loudness"]
            assert report["measured"] == 1 and report["changed"] == 1, report
            assert [item["clip_id"] for item in report["clips"] if "skipped" in item] == ["cs"], (
                report
            )
            assert [c["clip_id"] for c in report["commands"]] == ["ct"], report
            print(
                "   one silent clip on a track is reported, not fatal: the audible clip still "
                "gets its gain"
            )

            single = client.post(
                f"/v1/projects/{pid}/clips/c/loudness",
                json={"request_id": "clip-silent", "expected_revision": revision},
            )
            assert single.status_code == 422, single.text
            assert "digital silence" in single.json()["error"]["message"], single.json()
            assert single.json()["error"]["details"]["clip_id"] == "c", single.json()
            assert single.json()["error"]["details"]["asset_label"] == "silent.wav", single.json()
            assert single.json()["error"]["details"]["path"].endswith("silent.wav"), single.json()

            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            # The predicate is worthless if the header does not call it: pin the wiring too, so the
            # grey-out cannot drift from the refusal (1.82).
            wiring = (ROOT / "desktop/src/views/Timeline.tsx").read_text(encoding="utf-8")
            assert "const emptyTrack = trackToolBlocker(track.id, clips)" in wiring, (
                "the track header must ask the shared predicate, not guess"
            )
            # 1.279 起那几件事（统一响度 / 剪掉停顿 / 自动闪避）从轨道头收进了「更多」菜单；
            # 1.284 又多了整轨粗剪（只在画面轨上摆）。判据跟着形状走——四条菜单项都读同一个
            # `emptyTrack`，标题都交回它的原话。
            assert wiring.count("disabled: !!emptyTrack,") == 4, "four whole-track menu entries"
            assert wiring.count("title: emptyTrack ??") == 4, "each gated entry carries the reason"
            assert "disabled={!clips.length}" not in wiring, "a second, drifting copy of the rule"
            print(
                f"PASS: {refusals} track refusals name the track, all four routes agree on "
                f"「{HOLDS}」, a track with one clip is never refused that way (revision stays "
                f"{revision}); the header greys the four whole-track buttons out on an empty "
                f"track too"
            )


if __name__ == "__main__":
    main()
