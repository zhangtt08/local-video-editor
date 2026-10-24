"""1.280：轨道混音——独奏（solo）、静音优先、整轨音量，导出与预览清单同一个判据。

为什么要有这一档：`Track.volume` 从第一版就在契约里、导出与预览也一直乘它，可界面上
从来没有一根滑杆；「独奏」则连字段都没有。这一档把它们做成人和 Agent 共用的一件事：
一条 `track.update`（HTTP 与 MCP 同一个 `timeline_edit`），一条判断
（`animation.track_audible`），导出、预览清单、运行摘要读的都是它。

判据里最要紧的三条，都是「另一头会给出不同答案」的那种：
* 独奏 A 之后，成片里 440 Hz 还在、880 Hz 掉到听不见——不是「声音变小了」而是「没被混进来」；
* 静音优先于独奏：又静音又独奏的那条轨不出声，于是整条时间线没有可听的东西，
  音频交付按名字拒绝（`EMPTY_TIMELINE`，句子里有 audible）；
* 整轨音量 50% 的成片里，同一条 440 Hz 的幅度落在默认值的一半附近（0.4…0.6），
  不是「界面改了、混音没变」。
"""

from __future__ import annotations

import math
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.animation import sound_enabled, track_audible  # noqa: E402
from agentcut.contracts import APP_VERSION, SCHEMA_VERSION, TRACK_VOLUME_MAX  # noqa: E402
from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.render import compile_render_plan  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECONDS = 2.0
A_HZ, B_HZ = 440.0, 880.0


def run(args, timeout=300):
    done = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
    return done.stdout


def tone(folder: Path, name: str, hz: float) -> Path:
    target = folder / name
    run([str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i",
         f"sine=frequency={hz}:sample_rate=48000:duration={SECONDS}", str(target)])
    return target


def amplitude(path: Path, hz: float) -> float:
    """One exact frequency's amplitude in a decoded PCM window (0.1 s at 0.5 s).

    The correlation is the same yardstick `jlcut_check` uses: band-pass filters leak a whole octave
    away on these synthetic tones, so a threshold on them says nothing.
    """
    wav = path.with_suffix(".probe.wav")
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin", "-i", str(path),
        "-vn", "-c:a", "pcm_s16le", str(wav),
    ])
    handle = wave.open(str(wav), "rb")
    try:
        rate, channels, frames = handle.getframerate(), handle.getnchannels(), handle.getnframes()
        start = int(0.5 * rate)
        count = min(int(0.1 * rate), frames - start)
        handle.setpos(start)
        values = struct.unpack("<%dh" % (count * channels), handle.readframes(count))
    finally:
        handle.close()
    mono = values[0::channels]
    real = sum(v * math.cos(2 * math.pi * hz * i / rate) for i, v in enumerate(mono))
    imag = sum(v * math.sin(2 * math.pi * hz * i / rate) for i, v in enumerate(mono))
    return math.hypot(real, imag) / len(mono)


def runtime_for(folder: Path):
    media = MediaService(folder / "mx-db.sqlite3", [folder], folder / "mx-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "mx-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "mixercheck" + "m" * 52
    app = create_app(folder / "mx-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def seed(client: TestClient, tone_a: Path, tone_b: Path) -> tuple[str, int]:
    created = client.post(
        "/v1/projects",
        json={"request_id": "mx-new", "name": "混音", "settings": {"width": 320, "height": 180}},
    ).json()["project"]
    path = f"/v1/projects/{created['id']}"
    probes = {}
    for name, file in (("a", tone_a), ("b", tone_b)):
        probes[name] = client.post("/v1/media/import", json={"path": str(file)}).json()["verified"]
        assert probes[name]["has_audio"] is True, probes[name]
    duration = int(SECONDS * T)
    commands = [
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "解说"}},
        {"op": "track.add", "track": {"id": "b", "kind": "audio", "name": "配乐"}},
    ]
    for name in ("a", "b"):
        commands.append({
            "op": "asset.import",
            "asset_id": name,
            "label": name,
            "probe_id": probes[name]["probe_id"],
            "verified": probes[name],
        })
        commands.append({
            "op": "clip.add",
            "clip": {
                "id": "c" + name, "asset_id": name, "track_id": name,
                "position_ticks": 0, "duration_ticks": duration,
            },
        })
    seeded = client.post(
        path + "/edits",
        json={"request_id": "mx-seed", "expected_revision": 0, "commands": commands},
    )
    assert seeded.status_code == 200, seeded.text
    return path, seeded.json()["project"]["revision"]


def update(client: TestClient, path: str, revision: int, request: str, **track):
    body = {"op": "track.update", "track_id": track.pop("track_id"), **track}
    done = client.post(
        path + "/edits",
        json={"request_id": request, "expected_revision": revision, "commands": [body]},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def read_project(client: TestClient, path: str) -> dict:
    body = client.get(path).json()
    return body.get("project", body)


def render(client: TestClient, project: dict, folder: Path, name: str) -> Path:
    from agentcut.contracts import Project

    plan = compile_render_plan(Project.model_validate(project), "audio-wav")
    target = folder / name
    run(plan.ffmpeg_argv(str(FFMPEG), str(target)))
    return target


def main() -> None:
    caps = None
    with tempfile.TemporaryDirectory(prefix="agentcut-mixer-") as raw:
        folder = Path(raw)
        tone_a, tone_b = tone(folder, "a440.wav", A_HZ), tone(folder, "b880.wav", B_HZ)
        app, token = runtime_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            path, revision = seed(client, tone_a, tone_b)

            # ① 能力与契约：混音是能力位下的一格；音量两端只从契约常量来。
            assert caps["features"]["track_mixer"] is True, caps["features"]
            assert caps["limits"]["track_volume_max"] == TRACK_VOLUME_MAX, caps["limits"]
            assert caps["project_schema_version"] == SCHEMA_VERSION, caps["project_schema_version"]
            assert SCHEMA_VERSION >= 33, SCHEMA_VERSION

            # ② 默认：两条都在。
            project = read_project(client, path)
            mix_path = render(client, project, folder, "mix.wav")
            base_a, base_b = amplitude(mix_path, A_HZ), amplitude(mix_path, B_HZ)
            assert base_a > 1000 and base_b > 1000, (base_a, base_b)

            # ③ 独奏 A：440 还在、880 没了；预览清单同一句话说 B 不出声。
            project = update(client, path, revision, "mx-solo", track_id="a", solo=True)
            assert project["tracks"][0]["solo"] is True, project["tracks"]
            solo_path = render(client, project, folder, "solo.wav")
            solo_a, solo_b = amplitude(solo_path, A_HZ), amplitude(solo_path, B_HZ)
            assert solo_a > base_a * 0.8, (solo_a, base_a)
            assert solo_b < base_b * 0.05, (solo_b, base_b)
            manifest = client.get(path + "/preview-manifest").json()
            flags = {key: plan["sound_enabled"] for key, plan in manifest["clips"].items()}
            assert flags == {"ca": True, "cb": False}, flags
            revision = project["revision"]

            # ④ 静音优先于独奏：又静音又独奏 = 一条可听的都没有，音频交付按名字拒绝。
            project = update(client, path, revision, "mx-solo-mute", track_id="a", muted=True)
            assert project["tracks"][0]["solo"] is True and project["tracks"][0]["muted"] is True
            try:
                from agentcut.contracts import Project

                compile_render_plan(Project.model_validate(project), "audio-wav")
            except Exception as error:  # noqa: BLE001 - the named refusal is the evidence
                assert getattr(error, "code", None) == "EMPTY_TIMELINE", type(error).__name__
                assert "audible" in str(error), str(error)
            else:
                raise AssertionError("muted+soloed produced an audible deliverable")
            revision = project["revision"]

            # ⑤ 清掉静音、取消独奏、把 A 的音量拧到 50%：成片里 440 的幅度落在默认的一半附近。
            project = update(client, path, revision, "mx-unmute", track_id="a", muted=False)
            project = update(
                client, path, project["revision"], "mx-unsolo", track_id="a", solo=False
            )
            project = update(client, path, project["revision"], "mx-half", track_id="a", volume=0.5)
            assert abs(project["tracks"][0]["volume"] - 0.5) < 1e-6, project["tracks"][0]
            half_path = render(client, project, folder, "half.wav")
            half_a, half_b = amplitude(half_path, A_HZ), amplitude(half_path, B_HZ)
            ratio = half_a / base_a
            assert 0.4 <= ratio <= 0.6, (half_a, base_a, ratio)
            assert half_b > base_b * 0.8, (half_b, base_b)

            # ⑥ 越界由契约点名，不烧版本：4.0 是上限，0 是下限。
            for bad in (4.01, -0.01):
                refused = client.post(
                    path + "/edits",
                    json={
                        "request_id": f"mx-bad-{bad}",
                        "expected_revision": project["revision"],
                        "commands": [{"op": "track.update", "track_id": "a", "volume": bad}],
                    },
                )
                assert refused.status_code == 422, (bad, refused.status_code)
            assert read_project(client, path)["revision"] == project["revision"]

            # ⑦ 同一件事在纯函数上也说一遍（导出与预览共用的那一条判断）。
            from agentcut.contracts import Project

            model = Project.model_validate(project)
            tracks = {track.id: track for track in model.tracks}
            assert track_audible(tracks["a"], model) is True
            assert track_audible(tracks["b"], model) is True
            model.tracks[0].solo = True
            assert track_audible(tracks["a"], model) is True
            assert track_audible(tracks["b"], model) is False
            assert sound_enabled(model.clips["cb"], tracks["b"], model) is False
            model.tracks[0].muted = True
            assert track_audible(tracks["a"], model) is False
            print(
                f"   {base_a:.0f}/{base_b:.0f} → 独奏 A 后 {solo_a:.0f}/{solo_b:.0f}"
                f"（880 只剩 {solo_b / base_b:.1%}）；50% 音量后 {half_a:.0f}"
                f"（默认的 {ratio:.2f}）；静音+独奏按 EMPTY_TIMELINE 拒绝"
            )

    print(
        f"PASS: 轨道混音（{APP_VERSION}，schema {SCHEMA_VERSION}）——"
        "独奏让其它声音让路且预览清单同判、静音优先于独奏、"
        "整轨音量 50% 落在默认的一半、越界不烧版本"
    )


if __name__ == "__main__":
    main()
