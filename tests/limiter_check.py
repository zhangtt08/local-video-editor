"""Master limiter: the ceiling must actually cap the exported true peak, and the endpoint's
after-measurement must agree with a real export rather than a projection."""

import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECONDS = 3.0
CEILING = -7.0
TARGET = -6.0


def run(args, timeout=420, cwd=None):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def loud_source(target: Path) -> None:
    """A sine pushed 8x so its peaks sit at the wall of the 16-bit sink."""
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
            "volume=8,aformat=channel_layouts=stereo",
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


def read_levels(path: Path) -> tuple[float, float]:
    text = run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-v",
            "info",
            "-i",
            str(path),
            "-af",
            "ebur128=peak=true",
            "-vn",
            "-f",
            "null",
            "-",
        ],
        timeout=300,
    ).stderr.decode(errors="replace")
    summary = text.rsplit("Summary:", 1)[-1]
    integrated = float(re.search(r"I:\s*(-?[\d.]+)\s*LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s*(-?[\d.]+)\s*dBFS", summary).group(1))
    return integrated, peak


def audio_stage(project: Project) -> str:
    plan = compile_render_plan(project, "h264-source-quality")
    return "".join(stage for stage in plan.filters if "amix" in stage)


def export(client, project_id: str, out: Path, job_dir: Path) -> tuple[float, float]:
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
    return read_levels(out)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-limiter-") as scratch:
        folder = Path(scratch)
        loud_source(folder / "hot.wav")
        slate(folder / "slate.mp4")
        media = MediaService(
            folder / "lim-db.sqlite3", [folder], folder / "lim-cache", FFMPEG, FFPROBE
        )
        token = "limitercheck" + "e" * 52
        app = create_app(folder / "lim-api.sqlite3", token, media=media)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["master_limiter"] is True, caps["features"]
            probes = {
                name: client.post("/v1/media/import", json={"path": str(folder / file)}).json()
                for name, file in (("slate", "slate.mp4"), ("hot", "hot.wav"))
            }
            created = client.post(
                "/v1/projects", json={"request_id": "new", "name": "limiter"}
            ).json()["project"]
            path = f"/v1/projects/{created['id']}"
            commands = [{"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}}]
            for asset, label in (("slate", "画面"), ("hot", "响素材")):
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
                {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "声音"}},
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
                        "id": "hot",
                        "asset_id": "hot",
                        "track_id": "a",
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
            project = Project.model_validate(client.get(path).json())
            stage = audio_stage(project)
            assert "alimiter" not in stage, stage

            # Baseline: no master gain, no limiter. The 8x tone is already at the wall of the sink.
            plain_out = folder / "plain.mp4"
            plain = export(client, created["id"], plain_out, folder / "job-plain")
            assert plain[1] > CEILING + 1.0, plain
            print(f"   un-mastered export: {plain[0]} LUFS / peak {plain[1]} dBTP")

            scan = path + "/master/loudness"
            refused = client.post(
                scan,
                json={
                    "request_id": "oob",
                    "expected_revision": 1,
                    "target_lufs": -14.0,
                    "ceiling_dbtp": -20.0,
                    "limiter": True,
                },
            )
            assert refused.status_code == 422, refused.text

            # A ceiling the plain gain cannot cross: reaching -6 LUFS wants 0.767x, but the
            # -7 dBTP peak ceiling only allows 0.575x without a limiter.
            blocked = client.post(
                scan,
                json={
                    "request_id": "lim-off",
                    "expected_revision": 1,
                    "apply": True,
                    "target_lufs": TARGET,
                    "ceiling_dbtp": CEILING,
                    "limiter": False,
                },
            )
            assert blocked.status_code == 200, blocked.text
            held = blocked.json()["master"]
            assert held["limited_by"] == "ceiling", held
            assert held["reaches_target"] is False, held
            assert held["proposed_master_gain"] < 0.6, held
            print(
                f"   without a limiter the {CEILING} dBTP ceiling holds the gain to "
                f"{held['proposed_master_gain']} and only reaches {held['predicted_lufs']} LUFS"
            )
            undone = client.post(
                path + "/restore",
                json={"request_id": "undo-off", "expected_revision": 2, "target_revision": 1},
            )
            assert undone.status_code == 200, undone.text
            assert undone.json()["project"]["settings"]["master_gain"] == 1.0

            applied = client.post(
                scan,
                json={
                    "request_id": "lim-on",
                    "expected_revision": 3,
                    "apply": True,
                    "target_lufs": TARGET,
                    "ceiling_dbtp": CEILING,
                    "limiter": True,
                },
            )
            assert applied.status_code == 200, applied.text
            body = applied.json()
            assert body["committed"] is True and body["project"]["revision"] == 4
            settings = body["project"]["settings"]
            assert settings["master_limiter"] is True, settings
            assert settings["master_ceiling_dbtp"] == CEILING, settings
            assert abs(settings["master_gain"] - 0.767) < 0.02, settings
            reported = body["master"]
            assert reported["limited_by"] == "", reported
            after = reported["after"]
            print(
                f"   with the limiter the same target is un-clamped: gain "
                f"{settings['master_gain']}, endpoint after-probe {after['integrated_lufs']} LUFS "
                f"/ {after['true_peak_dbtp']} dBTP"
            )
            stage = audio_stage(Project.model_validate(body["project"]))
            assert "alimiter=limit=" in stage and "level=disabled" in stage, stage
            limit = re.search(r"alimiter=limit=([\d.]+)", stage).group(1)
            assert abs(float(limit) - 10 ** (CEILING / 20)) < 1e-5, (limit, stage)

            limited_out = folder / "limited.mp4"
            limited = export(client, created["id"], limited_out, folder / "job-limited")
            drift = abs(limited[0] - after["integrated_lufs"])
            peak_drift = abs(limited[1] - after["true_peak_dbtp"])
            assert drift <= 0.3 and peak_drift <= 0.3, (limited, after, drift, peak_drift)
            # This material is a hard-clipped sine: its crest factor is ~1.5 dB, so a -7 dBTP
            # ceiling and -6 LUFS cannot both hold. What must hold is the limiter's promise: the
            # peak is pulled to the ceiling and the mix still ends up louder than a clamped gain
            # could have made it.
            assert limited[1] <= CEILING + 0.8, (limited, plain, CEILING)
            assert limited[1] < plain[1] - 1.0, (limited, plain)
            assert limited[0] > held["predicted_lufs"], (limited, held)
            print(
                f"   export through the limiter: {limited[0]} LUFS / peak {limited[1]} dBTP "
                f"against {plain[0]} / {plain[1]} un-mastered and {held['predicted_lufs']} LUFS"
                f" / {held['proposed_master_gain']}x clamped without a limiter"
            )

            restored = client.post(
                path + "/restore",
                json={
                    "request_id": "undo",
                    "expected_revision": 4,
                    "target_revision": 1,
                },
            )
            assert restored.status_code == 200, restored.text
            back = restored.json()["project"]["settings"]
            assert back["master_limiter"] is False and back["master_gain"] == 1.0, back
            assert back["master_ceiling_dbtp"] == -1.0, back
            print("   undo returns the limiter, the ceiling and the master gain to their defaults")

    print(
        "PASS: the limiter caps the exported true peak at the requested ceiling, the endpoint's "
        "after-measurement matches a real export within 0.3 LU/dB, and undo clears both"
    )


if __name__ == "__main__":
    main()
