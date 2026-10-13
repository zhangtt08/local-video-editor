"""Master loudness: the probe-rendered measurement must predict the real export, and applying the
suggested master gain must land the exported file on the platform target."""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.loudness import measure
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECONDS = 4.0
VOICE = 0.5
MUSIC = 0.12


def run(args, timeout=420, cwd=None):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, cwd=cwd, creationflags=0x08000000
    )


def tone(target: Path, amplitude: float) -> None:
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
            f"sine=frequency=440:duration={SECONDS}:sample_rate=48000",
            "-af",
            f"volume={amplitude},aformat=channel_layouts=stereo",
            "-c:a",
            "pcm_s16le",
            str(target),
        ]
    )


def slate(target: Path) -> None:
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
            f"color=c=0x303030:s=320x180:r=30:d={SECONDS}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )


def export(client, project_id: str, out: Path, job_dir: Path) -> None:
    stored = client.get(f"/v1/projects/{project_id}").json()
    plan = compile_render_plan(Project.model_validate(stored), "h264-source-quality")
    job_dir.mkdir(parents=True, exist_ok=True)
    for name, body in plan.text_files.items():
        (job_dir / name).write_text(body, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job_dir,
        capture_output=True,
        timeout=600,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]


def main() -> None:
    import json

    with tempfile.TemporaryDirectory(prefix="agentcut-master-") as scratch:
        folder = Path(scratch)
        tone(folder / "voice.wav", VOICE)
        tone(folder / "music.wav", MUSIC)
        slate(folder / "slate.mp4")
        media = MediaService(
            folder / "master-db.sqlite3", [folder], folder / "master-cache", FFMPEG, FFPROBE
        )
        runtime = JobRuntime(
            folder / "master-api.sqlite3", FFMPEG, folder / "master-out", [folder / "master-out"]
        )
        token = "mastercheck" + "e" * 53
        app = create_app(folder / "master-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["master_loudness"] is True, caps["features"]
            probes = {
                name: client.post("/v1/media/import", json={"path": str(folder / file)}).json()
                for name, file in (
                    ("slate", "slate.mp4"),
                    ("voice", "voice.wav"),
                    ("music", "music.wav"),
                )
            }
            created = client.post(
                "/v1/projects", json={"request_id": "new", "name": "master"}
            ).json()["project"]
            path = f"/v1/projects/{created['id']}"
            commands = [{"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}}]
            for asset, label in (("slate", "画面"), ("voice", "口播"), ("music", "配乐")):
                commands.append(
                    {
                        "op": "asset.import",
                        "asset_id": asset,
                        "label": label,
                        "probe_id": probes[asset]["id"],
                        "verified": probes[asset]["verified"],
                    }
                )
            commands += [
                {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "口播"}},
                {"op": "track.add", "track": {"id": "b", "kind": "audio", "name": "配乐"}},
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "shot",
                        "asset_id": "slate",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": int(SECONDS * T),
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "say",
                        "asset_id": "voice",
                        "track_id": "a",
                        "position_ticks": 0,
                        "duration_ticks": int(SECONDS * T),
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "bed",
                        "asset_id": "music",
                        "track_id": "b",
                        "position_ticks": 0,
                        "duration_ticks": int(SECONDS * T),
                    },
                },
            ]
            seeded = client.post(
                path + "/edits",
                json={"request_id": "seed", "expected_revision": 0, "commands": commands},
            )
            assert seeded.status_code == 200, seeded.text

            scan = path + "/master/loudness"
            assert client.get(path).json()["settings"]["master_gain"] == 1.0

            empty = client.post(
                "/v1/projects/"
                + client.post("/v1/projects", json={"request_id": "bare", "name": "空"}).json()[
                    "project"
                ]["id"]
                + "/master/loudness",
                json={"request_id": "none", "expected_revision": 0},
            )
            assert empty.status_code == 422, empty.text

            read = client.post(
                scan, json={"request_id": "read", "expected_revision": 1, "target_lufs": -20.0}
            )
            assert read.status_code == 200, read.text
            body = read.json()
            assert body["committed"] is False and client.get(path).json()["revision"] == 1
            report = body["master"]
            assert report["current_master_gain"] == 1.0, report
            # These tones sit well below the target, so the suggestion must be a lift.
            assert -40.0 < report["integrated_lufs"] < -20.0, report
            assert 1.0 < report["proposed_master_gain"] <= 4.0, report
            assert report["reaches_target"] is True and report["limited_by"] == "", report
            print(
                f"   probe measured the mix at {report['integrated_lufs']} LUFS "
                f"(peak {report['true_peak_dbtp']} dBTP); target -20 suggests master_gain "
                f"{report['proposed_master_gain']}"
            )

            # The probe must agree with what the meter says about a real export of the same mix.
            before = folder / "export-before.mp4"
            export(client, created["id"], before, folder / "job-before")
            direct = measure(FFMPEG, before)
            drift = abs(direct["integrated_lufs"] - report["integrated_lufs"])
            assert drift <= 0.5, (direct, report, drift)
            print(
                f"   the full-size export measures {direct['integrated_lufs']} LUFS against the "
                f"64x36 probe's {report['integrated_lufs']} LUFS ({drift:.2f} LU apart)"
            )

            applied = client.post(
                scan,
                json={
                    "request_id": "apply",
                    "expected_revision": 1,
                    "apply": True,
                    "target_lufs": -20.0,
                },
            )
            assert applied.status_code == 200, applied.text
            result = applied.json()
            assert result["committed"] is True and result["project"]["revision"] == 2
            gain = result["project"]["settings"]["master_gain"]
            assert abs(gain - report["proposed_master_gain"]) < 1e-6, (gain, report)
            stage = "".join(
                stage
                for stage in compile_render_plan(
                    Project.model_validate(result["project"]), "h264-source-quality"
                ).filters
                if "volume=" in stage and "amix" in stage
            )
            assert f"volume={gain}" in stage, stage
            assert ":eval=frame" in stage, stage

            after = folder / "export-after.mp4"
            export(client, created["id"], after, folder / "job-after")
            landed = measure(FFMPEG, after)
            assert abs(landed["integrated_lufs"] + 20.0) <= 0.5, (direct, landed)
            assert landed["true_peak_dbtp"] <= -0.9, landed
            print(
                f"   after one click the export measures {landed['integrated_lufs']} LUFS against "
                f"the -20.0 target (peak {landed['true_peak_dbtp']} dBTP)"
            )

            again = client.post(
                scan,
                json={
                    "request_id": "again",
                    "expected_revision": 2,
                    "apply": True,
                    "target_lufs": -20.0,
                },
            )
            assert again.status_code == 422, again.text
            assert "already sits" in again.json()["error"]["message"], again.text
            assert client.get(path).json()["revision"] == 2

            dry = client.post(
                scan,
                json={
                    "request_id": "dry",
                    "expected_revision": 2,
                    "apply": True,
                    "dry_run": True,
                    "target_lufs": -24.0,
                },
            )
            assert dry.json()["committed"] is False and client.get(path).json()["revision"] == 2
            assert dry.json()["master"]["proposed_master_gain"] < gain, dry.json()["master"]

            hot = client.post(
                scan,
                json={
                    "request_id": "hot",
                    "expected_revision": 2,
                    "target_lufs": -6.0,
                    "ceiling_dbtp": -1.0,
                },
            )
            assert hot.status_code == 200, hot.text
            held = hot.json()["master"]
            assert held["proposed_master_gain"] <= 4.0 and held["reaches_target"] is False, held
            assert held["limited_by"] in {"ceiling", "gain_range"}, held
            print(
                f"   an unreachable -6 LUFS target reports limited_by={held['limited_by']!r} and "
                f"only reaches {held['predicted_lufs']} LUFS"
            )

            stale = client.post(
                scan,
                json={
                    "request_id": "stale",
                    "expected_revision": 1,
                    "apply": True,
                    "target_lufs": -18.0,
                },
            )
            assert stale.status_code == 409, stale.text
            out_of_range = client.post(
                scan,
                json={"request_id": "oob", "expected_revision": 2, "target_lufs": -2.0},
            )
            assert out_of_range.status_code == 422, out_of_range.text
            assert client.get(path).json()["revision"] == 2, "a refused master scan writes nothing"

            restored_from = client.get(path).json()["revision"]
            history = client.get(path + "/history").json()
            restored = client.post(
                path + "/restore",
                json={
                    "request_id": "undo",
                    "expected_revision": 2,
                    "target_revision": next(
                        item["revision"]
                        for item in history["history"]
                        if item["revision"] < restored_from
                    ),
                },
            )
            assert restored.status_code == 200, restored.text
            back = restored.json()["project"]["settings"]["master_gain"]
            assert back == 1.0, back
            print("   undoing the master change returns master_gain to 1.0")

            probe_dir = Path(media.cache_dir) / "master-probe"
            leftovers = list(probe_dir.glob("*.mp4")) if probe_dir.exists() else []
            assert not leftovers, leftovers
            assert json.dumps(sorted(p.name for p in probe_dir.glob("*"))) == "[]", list(
                probe_dir.glob("*")
            )
            print("   the probe leaves no rendered files behind")
    print(
        "PASS: the probe-rendered measurement matches the real export, one click lands the mix on "
        "target within half a LUFS, the ceiling is reported instead of faked, and undo restores 1.0"
    )


if __name__ == "__main__":
    main()
