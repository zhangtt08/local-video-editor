"""音频降噪：`afftdn=nr=` 必须真的把宽带噪声压下去，而且只在导出里发生。

One knob, one claim: a spoken-word clip recorded in a real room carries a hiss between the
words, and the editor asks for it gone. The claim is only worth making if the delivered file
measures quieter in the band where nothing but noise lives, without eating the voice underneath
it — so this check renders a tone-plus-noise fixture twice and measures the exported file, band by
band. The second claim is about honesty rather than audio: the browser preview has no
equivalent filter, so the preview must keep playing the untouched signal and the interface must say
the reduction is an export-only thing (the master limiter's treatment).
"""

import re
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import DENOISE_LIMIT
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECONDS = 3.0
TONE = 440.0
NOISE_BAND = 6000.0
PRESET = "h264-720p-web"


def run(args, timeout=600):
    return subprocess.run([str(a) for a in args], capture_output=True, check=True, timeout=timeout)


def hiss_source(target: Path) -> None:
    """A 440 Hz tone with a white-noise bed under it, in one container with a picture."""
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE}:duration={SECONDS}:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=white:amplitude=0.03:duration={SECONDS}:sample_rate=48000:r=48000",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x404040:s=320x180:d={SECONDS}",
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]",
            "-map",
            "[a]",
            "-map",
            "2:v",
            "-c:a",
            "pcm_s16le",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            target,
        ]
    )


def band_level(path: Path, freq: float, width: float = 1200.0) -> float:
    """The exported file's RMS inside one band, in dBFS. `astats` reads it back the same way for
    every call, so the only thing that varies between renders is what the filter chain did."""
    done = run(
        [
            FFMPEG,
            "-v",
            "info",
            "-i",
            path,
            "-af",
            f"bandpass=f={freq}:width_type=h:w={width},astats=measure_perchannel=none",
            "-f",
            "null",
            "-",
        ]
    )
    text = done.stderr.decode(errors="replace")
    found = re.search(r"RMS level dB:\s*(-?[\d.]+|inf|-inf)", text)
    assert found, text[-800:]
    value = found.group(1)
    return -120.0 if "inf" in value else float(value)


def seed_commands(verified: dict) -> list[dict]:
    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
        {
            "op": "asset.import",
            "asset_id": "hiss",
            "label": "hiss",
            "probe_id": verified["probe_id"],
            "verified": verified,
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c",
                "asset_id": "hiss",
                "track_id": "v",
                "position_ticks": 0,
                "duration_ticks": int(SECONDS * T),
            },
        },
    ]


def client_for(folder: Path):
    media = MediaService(folder / "dn-db.sqlite3", [folder], folder / "dn-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "dn-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "denoisechk" + "e" * 51
    app = create_app(folder / "dn-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def render(client: TestClient, path: str, revision: int, name: str) -> Path:
    queued = client.post(
        path + "/renders",
        json={
            "request_id": "render-" + name.replace(".", "-"),
            "expected_revision": revision,
            "preset_id": PRESET,
            "filename": name,
        },
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()["job"]
    status = {}
    for _ in range(600):
        status = client.get("/v1/jobs/" + job["id"]).json()["job"]
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    assert status["status"] == "succeeded", status
    return Path(status["output_path"])


def contract_suite(folder: Path) -> int:
    """What the contract and the compiled filter graph promise, without touching FFmpeg."""
    app, token = client_for(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        source = folder / "hiss.mp4"
        hiss_source(source)
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        assert probe["verified"]["has_audio"] is True, probe
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "denoise",
                "settings": {"width": 320, "height": 180},
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": seed_commands(probe["verified"]),
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["clip_denoise"] is True, caps["features"]
        assert caps["limits"]["denoise_db"] == DENOISE_LIMIT, caps["limits"]

        def set_denoise(request_id: str, value: float) -> tuple[int, str]:
            answer = client.post(
                path + "/edits",
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "commands": [
                        {
                            "op": "clip.effects",
                            "clip_id": "c",
                            "effects": {
                                "x": 0.0,
                                "y": 0.0,
                                "scale": 1.0,
                                "rotation": 0.0,
                                "opacity": 1.0,
                                "gain": 1.0,
                                "denoise": value,
                            },
                        }
                    ],
                },
            )
            code = "" if answer.status_code < 400 else answer.json()["error"]["code"]
            return answer.status_code, code

        status, _ = set_denoise("dn-12", 12.0)
        assert status == 200, _
        stored = client.get(path).json()["clips"]["c"]["effects"]["denoise"]
        assert stored == 12.0, stored
        # The knob is a ceiling, not a suggestion: past the measured band the contract refuses.
        status, code = set_denoise("dn-over", DENOISE_LIMIT + 6)
        assert (status, code) == (422, "INVALID_REQUEST"), (status, code)
        # ...and it is not an animatable property: there is no per-frame noise gate to keyframe.
        keyed = client.post(
            path + "/edits",
            json={
                "request_id": "dn-key",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "keyframe.set",
                        "clip_id": "c",
                        "keyframe": {"property": "denoise", "at_ticks": 0, "value": 6},
                    }
                ],
            },
        )
        assert keyed.status_code >= 400, keyed.text
        print(
            "   contract: 12 dB stores, out-of-range refuses as INVALID_REQUEST, and a denoise "
            "keyframe is refused -- the ceiling is the advertised "
            f"{DENOISE_LIMIT} dB"
        )
        # The compiled graph carries exactly one `afftdn`, and only while the knob is up.
        plan = client.get(f"{path}/render-plan?preset_id={PRESET}&revision={revision + 1}").json()
        text = str(plan)
        assert "afftdn=nr=12.0:nf=-30.0" in text, text[:400]
        zero = client.get(f"{path}/render-plan?preset_id={PRESET}&revision={revision}").json()
        assert "afftdn" not in str(zero), str(zero)[:400]
        print("   the exported filter graph gains one afftdn stage, and loses it at 0 dB")
        return revision + 1


def media_suite(folder: Path) -> None:
    """The claim in one sentence: the noise band drops, the voice band does not.

    Three renders of one timeline, differing only in the knob (0 / 12 / 24 dB), so the control
    is the same project and the ordering of reductions is measured, not assumed.
    """
    media = MediaService(folder / "dn-db.sqlite3", [folder], folder / "dn-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "dn-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "denoisechk" + "e" * 51
    app = create_app(folder / "dn-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        listed = client.get("/v1/projects").json()["projects"]
        pid = next(item["id"] for item in listed if item["name"] == "denoise")
        path = f"/v1/projects/{pid}"
        current = client.get(path).json()["revision"]
        levels = {}
        for knob in (0.0, 12.0, 24.0):
            answer = client.post(
                path + "/edits",
                json={
                    "request_id": f"dn-set-{int(knob)}",
                    "expected_revision": current,
                    "commands": [
                        {
                            "op": "clip.effects",
                            "clip_id": "c",
                            "effects": {
                                "x": 0.0,
                                "y": 0.0,
                                "scale": 1.0,
                                "rotation": 0.0,
                                "opacity": 1.0,
                                "gain": 1.0,
                                "denoise": knob,
                            },
                        }
                    ],
                },
            )
            assert answer.status_code == 200, answer.text
            current = answer.json()["project"]["revision"]
            file = render(client, path, current, f"denoise-{int(knob)}.mp4")
            levels[knob] = (band_level(file, NOISE_BAND), band_level(file, TONE, 200.0))
        control, middle, top = levels[0.0], levels[12.0], levels[24.0]
        assert middle[0] < control[0] - 6.0, (control, middle)
        assert top[0] < middle[0] - 1.0, (middle, top)
        assert max(abs(x[1] - control[1]) for x in (middle, top)) < 1.0, levels
        print(
            f"   exported files measured: the 6 kHz noise band goes {control[0]:.1f} → "
            f"{middle[0]:.1f} → {top[0]:.1f} dBFS at 0 / 12 / 24 dB of knob "
            f"({control[0] - top[0]:.1f} dB off at the top), while the 440 Hz tone stays inside "
            f"{abs(middle[1] - control[1]):.2f} dB ({control[1]:.1f} → {middle[1]:.1f} → "
            f"{top[1]:.1f})"
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        contract_suite(folder)
        media_suite(folder)
    print(
        "PASS: 片段降噪 is one knob the exporter honours -- the noise band in the delivered file "
        "drops by a measured margin while the voice under it stays put, the graph carries no stage "
        "at 0 dB, and the contract keeps it out of the keyframe vocabulary"
    )


if __name__ == "__main__":
    main()
