"""The operational routes -- import, caches, restore, jobs, LUT parse -- all name their target.

1.75 named the analysis refusals and 1.76 the reads. What a person still meets in the everyday path
is an import that fails (the file moved, the folder is not allowed, the extension is unknown, the
file is zero bytes) and a `.cube` the engine will not take. Those answers used to carry
`"details": {}` -- the sentence was there, the structured target was not, so an Agent could not tell
a path problem from a type problem without parsing prose, and the import dialog could not point at
the line of a LUT that broke.
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def tone(folder: Path) -> Path:
    target = folder / "tone.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x404040:s=320x180:d=1",
            "-c:a",
            "pcm_s16le",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(target),
        ],
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return target


def cube(rows: int = 3, three_d: bool = False, broken: bool = False) -> str:
    header = 'TITLE "gate"\n'
    size = f"LUT_{'3D' if three_d else '1D'}_SIZE {rows}\n"
    values = (
        "0.0 0.5\n"
        if broken
        else "".join(
            f"{index / rows:.4f} {(index + 1) / rows:.4f} {index / rows:.4f}\n"
            for index in range(rows)
        )
    )
    return header + size + values


# (method, path, body, the key a refusal has to name). `{pid}` / `{probe}` are filled per run.
ASKS = [
    ("POST", "/v1/media/import", {"path": "{work}/missing.mp4"}, "path", "MEDIA_NOT_FOUND"),
    ("POST", "/v1/media/import", {"path": "{work}"}, "path", "MEDIA_TYPE_UNSUPPORTED"),
    ("POST", "/v1/media/import", {"path": "{outside}/x.mp4"}, "media_roots", "MEDIA_NOT_ALLOWED"),
    ("POST", "/v1/media/import", {"path": "{work}/weird.qqq"}, "suffix", "MEDIA_TYPE_UNSUPPORTED"),
    ("POST", "/v1/lut/parse", {"content": "{cube3d}"}, "line", "INVALID_LUT"),
    ("POST", "/v1/lut/parse", {"content": "{cubebroken}"}, "line", "INVALID_LUT"),
    ("POST", "/v1/lut/parse", {"content": "{cubeshort}"}, "rows", "INVALID_LUT"),
    (
        "POST",
        "/v1/projects/ghost/restore",
        {"request_id": "r", "expected_revision": 0, "target_revision": 1},
        "project_id",
        "NOT_FOUND",
    ),
    (
        "POST",
        "/v1/projects/{pid}/restore",
        {"request_id": "r2", "expected_revision": 1, "target_revision": 99},
        "revision",
        None,
    ),
    ("POST", "/v1/jobs/ghost/cancel", {}, "job_id", "NOT_FOUND"),
    ("GET", "/v1/jobs/ghost", {}, "job_id", "NOT_FOUND"),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outer:
        folder = Path(raw).resolve()
        source = tone(folder)
        (folder / "empty.mp4").write_bytes(b"")
        # Outside the media root, but inside a directory this run owns and removes again.
        outside = Path(outer)
        (outside / "x.mp4").write_bytes(b"not a video")
        (folder / "weird.qqq").write_bytes(b"hello")
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        runtime = JobRuntime(folder / "api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
        runtime.ensure_worker()
        token = "opsweep" + "c" * 55
        app = create_app(folder / "api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            imported = client.post("/v1/media/import", json={"path": str(source)}).json()
            pid = client.post("/v1/projects", json={"request_id": "new", "name": "ops"}).json()[
                "project"
            ]["id"]
            seeded = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "c1", "kind": "audio", "name": "c1"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a1",
                            "label": "tone",
                            "probe_id": imported["id"],
                            "verified": imported["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "k",
                                "asset_id": "a1",
                                "track_id": "c1",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text

            # The paths that must keep working, so naming failures cannot become a refusal machine.
            for path in (
                "/v1/media/config",
                "/v1/media/probes",
                "/v1/media/cache",
                "/v1/outputs/roots",
                f"/v1/projects/{pid}/bundle",
            ):
                answer = client.get(path)
                assert answer.status_code == 200, (
                    f"{path} -> {answer.status_code} {answer.text[:120]}"
                )
            for path, body in (
                ("/v1/media/cache/prune", {"dry_run": True}),
                ("/v1/media/proxies/prune", {}),
                ("/v1/ids", {"count": 5}),
                ("/v1/lut/parse", {"content": cube()}),
            ):
                answer = client.post(path, json=body)
                assert answer.status_code == 200, (
                    f"{path} -> {answer.status_code} {answer.text[:160]}"
                )
            good = client.post("/v1/lut/parse", json={"content": cube()}).json()
            assert good["size"] == 3 and len(good["channels"]) == 3, good
            print("   nine honest operational calls still answer 200")

            filled = {
                "{work}": str(folder),
                "{outside}": str(outside),
                "{pid}": pid,
                "{cube3d}": cube(2, three_d=True),
                "{cubebroken}": cube(3, broken=True),
                "{cubeshort}": cube(2).replace("LUT_1D_SIZE 2", "LUT_1D_SIZE 5"),
            }
            named = 0
            problems = []
            for method, path, body, key, code in ASKS:
                payload = {}
                for field, value in body.items():
                    if isinstance(value, str):
                        for mark, replacement in filled.items():
                            value = value.replace(mark, replacement)
                    payload[field] = value
                url = path
                for mark, value in filled.items():
                    url = url.replace(mark, value)
                answer = client.get(url) if method == "GET" else client.post(url, json=payload)
                status = answer.status_code
                if status >= 500:
                    problems.append(f"5xx {method} {url}: {answer.text[:160]}")
                    continue
                if status < 400:
                    problems.append(f"{method} {url} answered {status}; the gate expects a refusal")
                    continue
                error = answer.json().get("error") or {}
                got = str(error.get("code") or "")
                details = error.get("details") or {}
                if code and got != code:
                    problems.append(f"{method} {url}: answered {got}, expected {code}")
                    continue
                if not got or not str(error.get("message") or "").strip():
                    problems.append(f"{method} {url}: nameless refusal {answer.text[:120]}")
                    continue
                if not details:
                    problems.append(f"{method} {url} {got}: empty details")
                    continue
                if key and key not in details:
                    problems.append(f"{method} {url} {got} names no {key}: {details}")
                    continue
                named += 1
                print(f"   {status} {method} {url[:44]:44} {got} {str(details)[:70]}")
            assert not problems, problems
            assert named >= 10, named
            print(
                f"   {named} operational refusals each carry a code, a sentence and the target "
                "they were given (path, suffix, media roots, LUT line, project, revision, job)"
            )
    print(
        "PASS: the operational routes answer with the same named detail as the rest of "
        "the API, and the calls that should work still do"
    )


if __name__ == "__main__":
    main()
