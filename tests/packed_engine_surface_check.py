"""The engine inside the Windows package has to answer for 1.150, not just the source tree.

`released_package_check.py` proves the shipped bytes are the built bytes; this proves those bytes
actually serve the new surface over real HTTP, using fixtures written by the FFmpeg that ships
beside them. It is the difference between "the file is in the ASAR" and "a person clicking the box,
or an Agent calling `clip_color_space`, gets the answer" — and it is the only gate that would notice
a package built from a stale tree, since every other check imports the sources.

Assertions, each one a way this could quietly be missing from the shipped build:
* `/v1/capabilities` says this engine's version, its schema, and offers the auto-source flag;
* the tag table it publishes is the table the engine translates with;
* the read route resolves a real BT.709 file and calls an untagged one `no_color_tags`;
* `auto_source` writes the pair, and asking it of the untagged file is a named 422 that moves
  nothing.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION, COLOR_TRANSFER_TAGS, SCHEMA_VERSION  # noqa: E402
from agentcut.contracts import TIMEBASE as T  # noqa: E402

BIN = ROOT / "desktop/resources/bin"
ENGINE = BIN / "agentcut/agentcut.exe"
FFMPEG = BIN / "ffmpeg.exe"
FFPROBE = BIN / "ffprobe.exe"


def call(base, token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as answer:
            return answer.status, json.loads(answer.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def source(path, colour):
    argv = [
        str(FFMPEG),
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x804020:s=64x36:r=25",
        "-t",
        "1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]
    if colour:
        argv += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    subprocess.run([*argv, str(path)], check=True, capture_output=True, timeout=180)


def start(folder, token):
    proc = subprocess.Popen(
        [
            str(ENGINE),
            "desktop",
            "--port",
            "0",
            "--data-dir",
            str(folder / "data"),
            "--media-root",
            str(folder),
            "--ffmpeg",
            str(FFMPEG),
            "--ffprobe",
            str(FFPROBE),
            "--expose-token",
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, AGENTCUT_TOKEN=token),
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise AssertionError(f"the packed engine died: rc={proc.returncode}")
            continue
        if line.startswith("{"):
            info = json.loads(line)
            return proc, info["base_url"], info
    raise AssertionError("the packed engine never reported a port")


def main():
    for path in (ENGINE, FFMPEG, FFPROBE):
        assert path.is_file(), f"this gate needs the packed build: {path} is missing"
    token = "packedengine" + "0" * 32
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source(folder / "hd.mp4", colour=True)
        source(folder / "bare.mp4", colour=False)
        proc, base, ready = start(folder, token)
        try:
            assert ready["media_ready"] is True, ready
            status, caps = call(base, token, "GET", "/v1/capabilities")
            assert status == 200, status
            print(
                f"   packed engine reports {caps['app_version']} / schema "
                f"{caps['project_schema_version']}"
            )
            assert caps["app_version"] == APP_VERSION, (caps["app_version"], APP_VERSION)
            assert caps["project_schema_version"] == SCHEMA_VERSION
            assert caps["features"]["color_manage_auto"] is True, caps["features"]
            assert caps["color_transfer_tags"] == [
                {"tag": tag, "space": space} for tag, space in COLOR_TRANSFER_TAGS
            ], caps["color_transfer_tags"]

            _, created = call(
                base,
                token,
                "POST",
                "/v1/projects",
                {
                    "request_id": "p",
                    "name": "pkg",
                    "settings": {"width": 64, "height": 36},
                },
            )
            project = created.get("project", created)
            pid, revision = project["id"], project["revision"]

            probes = {}
            for name in ("hd", "bare"):
                status, probe = call(
                    base,
                    token,
                    "POST",
                    "/v1/media/import",
                    {
                        "path": str(folder / f"{name}.mp4"),
                    },
                )
                assert status == 200, (name, probe)
                probes[name] = probe

            commands = [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            ]
            commands += [
                {
                    "op": "asset.import",
                    "asset_id": name,
                    "label": name,
                    "probe_id": probe["id"],
                    "verified": probe["verified"],
                }
                for name, probe in probes.items()
            ]
            commands += [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": name,
                        "asset_id": name,
                        "track_id": "v",
                        "position_ticks": index * T,
                        "duration_ticks": T,
                    },
                }
                for index, name in enumerate(("hd", "bare"))
            ]
            status, seeded = call(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/edits",
                {
                    "request_id": "seed",
                    "expected_revision": revision,
                    "commands": commands,
                },
            )
            assert status == 200, seeded
            revision = seeded.get("project", seeded)["revision"]

            status, hd = call(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/clips/hd/color-space",
                {"sequence_id": None},
            )
            assert status == 200 and hd["space"] == "rec709", (status, hd)
            assert hd["auto_source_would_work"] is True and hd["color_transfer"] == "bt709", hd
            status, bare = call(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/clips/bare/color-space",
                {"sequence_id": None},
            )
            assert status == 200 and bare["space"] is None, (status, bare)
            assert bare["reason"] == "no_color_tags", bare
            print("   read route over the packed build: bt709 -> rec709, untagged -> no_color_tags")

            status, written = call(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/edits",
                {
                    "request_id": "auto",
                    "expected_revision": revision,
                    "commands": [
                        {
                            "op": "clip.color_manage",
                            "clip_id": "hd",
                            "source_space": None,
                            "auto_source": True,
                        }
                    ],
                },
            )
            assert status == 200, written
            state = written.get("project", written)
            chain = state["clips"]["hd"]["color"]["grade"]
            assert [node["input_space"] for node in chain] == ["rec709", "linear"], chain
            assert [node["purpose"] for node in chain] == ["color_manage", "color_manage"], chain

            status, refused = call(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/edits",
                {
                    "request_id": "refuse",
                    "expected_revision": state["revision"],
                    "commands": [
                        {
                            "op": "clip.color_manage",
                            "clip_id": "bare",
                            "source_space": None,
                            "auto_source": True,
                        }
                    ],
                },
            )
            assert status == 422, refused
            error = refused["error"]
            assert error["code"] == "COLOR_SPACE_UNDETECTED", error
            assert error["details"]["reason"] == "no_color_tags", error["details"]
            after = call(base, token, "GET", f"/v1/projects/{pid}")[1]["revision"]
            assert after == state["revision"], (after, state["revision"])
            print(
                "PASS: the engine inside the package serves 1.150 over real HTTP, and its "
                "refusal writes nothing"
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=30,
            )


if __name__ == "__main__":
    main()
