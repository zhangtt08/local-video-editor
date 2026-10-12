"""The channel mixer: one 3x3, two renderers, measured on every primary at every level.

A per-channel node can be checked with a grey ramp. A cross-channel node cannot — grey in gives grey
out no matter what the off-diagonal terms are, so a matrix with the green and blue columns swapped
would pass a ramp test unchanged. This file therefore drives **three** 256-pixel plates, one per
primary with the other two at zero, and compares all three output channels of each against a
reference multiply written here, from the published definition of the two filters:

* FFmpeg's `colorchannelmixer`, which the exporter runs;
* SVG's `feColorMatrix type="matrix"`, which the browser composites, fed by the same nine numbers
  through `feColorMatrixValues` (and declared `color-interpolation-filters="sRGB"`, so neither side
  linearises behind the other's back).

It also pins the things that are easy to get wrong and impossible to see: that `mix` folds into the
matrix rather than being dropped, that a zero-strength mixer adds no stage at all, that the stage
order survives compilation, and that a `blend` mode on this node is refused by the contract instead
of being quietly ignored — a non-linear blend of a matrix with its input is not a matrix, so there
would be no single set of numbers left for the two ends to share.
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import (
    MATRIX_LIMIT,
    ClipColor,
    CreateProject,
    GradeMatrix,
    Project,
)
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.grade import ISLAND_IN, ISLAND_OUT, grade_filter, grade_stages, grade_tables
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180

GREY_709 = [0.2126, 0.7152, 0.0722, 0.2126, 0.7152, 0.0722, 0.2126, 0.7152, 0.0722]
SWAP = [0, 1, 0, 0, 0, 1, 1, 0, 0]
WARM = [1.1, 0.08, -0.06, 0, 1.0, 0.02, -0.05, 0.06, 0.92]
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1]
CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.78}, {"x": 1.0, "y": 1.0}],
}


def clamp(value: float) -> float:
    return 0.0 if value < 0 else 255.0 if value > 255 else value


def reference(m: list[float], pixel: tuple[int, int, int]) -> list[int]:
    """One pixel through the matrix, computed here and nowhere else."""
    return [
        round(clamp(row[0] * pixel[0] + row[1] * pixel[1] + row[2] * pixel[2]))
        for row in (m[0:3], m[3:6], m[6:9])
    ]


def plate(primary: int) -> bytes:
    """256 pixels: one channel sweeping 0..255, the other two held at zero."""
    out = bytearray()
    for level in range(256):
        pixel = [0, 0, 0]
        pixel[primary] = level
        out += bytes(pixel)
    return bytes(out)


def through(stage: str, raw: bytes) -> list[list[int]]:
    """Run one compiled stage over a 256x1 plate, and read back all three channels."""
    done = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "256x1",
            "-i",
            "pipe:0",
            "-vf",
            stage,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        input=raw,
        capture_output=True,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-500:]
    out = done.stdout
    assert len(out) == 256 * 3, (len(out), out[:60])
    return [[out[pixel * 3 + channel] for pixel in range(256)] for channel in range(3)]


def matrix(nodes: list) -> dict:
    return {"kind": "matrix", "coefficients": nodes}


def main() -> None:
    # 1. Every primary, every level, every output channel — against the reference multiply.
    for label, coefficients in (("bt709", GREY_709), ("swap", SWAP), ("warm", WARM)):
        stage = grade_filter(ClipColor(grade=[GradeMatrix(coefficients=coefficients)]))
        # 1.149：含跨通道矩阵的链整段走 16 位岛（`ISLAND_IN` 进、`ISLAND_OUT` 出），因为矩阵乘在
        # 线性量上，8 位平面在暗部只剩几个码字（实测同一往返最大差 16 级，进岛后矩阵那份差 0）。
        # 所以这里断的是**新形状**：矩阵必须就在岛内的第一段，而不是裸串开头。
        assert stage.startswith(f"{ISLAND_IN},colorchannelmixer="), stage
        assert stage.endswith(ISLAND_OUT), stage
        for primary in range(3):
            planes = through(stage, plate(primary))
            for level in range(256):
                pixel = [0, 0, 0]
                pixel[primary] = level
                wanted = reference(coefficients, tuple(pixel))
                for channel in range(3):
                    assert abs(planes[channel][level] - wanted[channel]) <= 1, (
                        label,
                        primary,
                        level,
                        channel,
                        planes[channel][level],
                        wanted[channel],
                    )
        print(f"   matrix {label}: 3 plates x 256 levels x 3 channels match the reference")

    # 2. Strength folds into the matrix; zero strength adds no stage at all.
    half = ClipColor(grade=[GradeMatrix(coefficients=GREY_709, mix=0.5)])
    folded = grade_stages(half)[0]["m"]
    wanted = [
        (1.0 if row == column else 0.0)
        + 0.5 * (GREY_709[row * 3 + column] - (1.0 if row == column else 0.0))
        for row in range(3)
        for column in range(3)
    ]
    assert all(abs(a - b) < 1e-9 for a, b in zip(folded, wanted)), folded
    assert grade_filter(ClipColor(grade=[GradeMatrix(coefficients=GREY_709, mix=0.0)])) == ""
    assert grade_tables(ClipColor(grade=[GradeMatrix(coefficients=IDENTITY)])) is None
    assert grade_tables(ClipColor(grade=[GradeMatrix(coefficients=IDENTITY, mix=0.4)])) is None
    print("   mix: folded into the same numbers, and a no-op mixer compiles to nothing")

    # 3. Order is preserved: the two chains differ, and each lists its stages in the run order.
    forward = ClipColor(grade=[CURVE, matrix(GREY_709)])
    reverse = ClipColor(grade=[matrix(GREY_709), CURVE])
    assert [stage["type"] for stage in grade_stages(forward)] == ["lut", "matrix"]
    assert [stage["type"] for stage in grade_stages(reverse)] == ["matrix", "lut"]
    assert grade_filter(forward).startswith(f"{ISLAND_IN},lutrgb=") and "colorchannelmixer" in (
        grade_filter(forward)
    )
    assert grade_filter(reverse).startswith(f"{ISLAND_IN},colorchannelmixer=")
    # 只有跨通道那一段值得进岛：纯曲线链的形状一字不改（它本来就能塌成一张表，中间没有
    # 会被量化吃掉的线性站）。这一条是「不猜、不多动」的界，也是电池的靶。
    assert not grade_filter(ClipColor(grade=[CURVE])).startswith(ISLAND_IN), grade_filter(
        ClipColor(grade=[CURVE])
    )
    assert grade_filter(ClipColor(grade=[CURVE])).startswith("lutrgb=")
    assert grade_tables(forward)["id"] != grade_tables(reverse)["id"]
    forward_planes = through(grade_filter(forward), plate(0))
    reverse_planes = through(grade_filter(reverse), plate(0))
    assert max(abs(a - b) for a, b in zip(forward_planes[0], reverse_planes[0])) > 8, (
        "the two orders rendered the same picture: the chain is not ordered"
    )
    print("   order: curve→mixer and mixer→curve compile and render differently")

    # 4. The contract refuses what the compiler cannot honour on both ends.
    for bad in (
        {"coefficients": [9, 0, 0, 0, 1, 0, 0, 0, 1]},
        {"coefficients": [1, 0, 0]},
        {"coefficients": [1, 0, 0, 0, 1, 0, 0, 0, 1], "blend": "multiply"},
    ):
        try:
            GradeMatrix(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"the contract accepted {bad}")
    assert GradeMatrix(coefficients=[-MATRIX_LIMIT] * 9).coefficients[0] == -MATRIX_LIMIT
    # A parallel branch averages its results into one table, so a cross-channel branch cannot live
    # there. The contract is what keeps that unreachable for the compiler — without this refusal the
    # branch evaluator would meet a node it has no mapping for and the request would be a 500.
    for shape in (
        {"kind": "parallel", "branches": [matrix(GREY_709)]},
        {"kind": "parallel", "branches": [CURVE, matrix(GREY_709)]},
    ):
        try:
            ClipColor(grade=[shape])
        except ValidationError:
            continue
        raise AssertionError(f"the contract accepted a mixer inside a parallel branch: {shape}")
    print("   contract: out-of-range, wrong length and blend are all refused")

    token = "c" * 48
    with tempfile.TemporaryDirectory(prefix="agentcut-matrix-") as temp:
        folder = Path(temp)
        source = folder / "plate.mp4"
        done = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"nullsrc=s={WIDTH}x{HEIGHT}:d=1:r=25,format=rgb24,"
                "geq=r='X*255/(W-1)':g='Y*255/(H-1)':b='128'",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(source),
            ],
            capture_output=True,
        )
        assert done.returncode == 0, done.stderr.decode(errors="replace")[-400:]
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        store = ProjectStore(media.db_path, media)
        probe = media.import_file(str(source))
        project = store.create(
            CreateProject(
                request_id="new", name="matrix", settings={"width": WIDTH, "height": HEIGHT}
            )
        ).project
        with TestClient(
            create_app(store.path, token, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            answer = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a",
                            "label": "plate",
                            "probe_id": probe.id,
                            "verified": probe.verified.model_dump(),
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                    ],
                },
            )
            assert answer.status_code == 200, answer.text[:300]
            revision = answer.json()["project"]["revision"]

            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["grade_matrix"] is True
            assert caps["grade_limits"]["matrix_limit"] == MATRIX_LIMIT

            written = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "mix",
                    "expected_revision": revision,
                    "commands": [
                        {
                            "op": "clip.grade",
                            "clip_id": "c",
                            "grade": [CURVE, matrix(WARM)],
                        }
                    ],
                },
            )
            assert written.status_code == 200, written.text[:300]
            stored = Project.model_validate(written.json()["project"])
            assert [node.kind for node in stored.clips["c"].color.grade] == ["curve", "matrix"]

            # The browser is handed the same nine numbers, in the order the exporter will run them.
            manifest = client.get(f"/v1/projects/{project.id}/preview-manifest").json()
            chain = manifest["clips"]["c"]["grade"]
            assert [stage["type"] for stage in chain["stages"]] == ["lut", "matrix"]
            assert chain["stages"][1]["m"] == WARM
            assert f"url(#{chain['id']})" in manifest["clips"]["c"]["color_filter"]

            # And the exporter's graph carries the mixer, so the stage is in the file, not just in
            # the request.
            graph = "\n".join(compile_render_plan(stored, "h264-source-quality").filters)
            assert "colorchannelmixer=" in graph, graph[:200]

            refused = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "blend-refused",
                    "expected_revision": written.json()["project"]["revision"],
                    "commands": [
                        {
                            "op": "clip.grade",
                            "clip_id": "c",
                            "grade": [dict(matrix(GREY_709), blend="multiply")],
                        }
                    ],
                },
            )
            assert refused.status_code == 422, refused.text[:200]
            in_branch = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "branch-refused",
                    "expected_revision": written.json()["project"]["revision"],
                    "commands": [
                        {
                            "op": "clip.grade",
                            "clip_id": "c",
                            "grade": [{"kind": "parallel", "branches": [matrix(GREY_709)]}],
                        }
                    ],
                },
            )
            assert in_branch.status_code == 422, in_branch.text[:200]
            assert "branches" in in_branch.text, in_branch.text[:200]
            assert store.get(project.id).revision == written.json()["project"]["revision"]
    print("matrix: cross-channel grade compiles once and is read the same by both ends")


if __name__ == "__main__":
    main()
