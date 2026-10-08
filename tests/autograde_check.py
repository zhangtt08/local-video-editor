"""Auto levels: the measurement is real, the node is ordinary, and both renderers agree.

Four claims are insisted on here, because each has been the silent failure elsewhere in this
project:

1. a `levels` node compiles to the same transfer function for FFmpeg and for the browser table —
   measured at **every** one of the 256 input levels against a reference written from the published
   formula, sharing nothing with the shipped sampler;
2. the auto measurement reads the clip's own decoded frames (a fixture built with a known squashed
   range), and the numbers it reports are the numbers that get written;
3. the stretch moves real pixels: the compiled stage, run over the real fixture by the real FFmpeg,
   takes a picture measured at [30, 208] to one measured at near full range;
4. every refusal (no picture, no range, levels already in the chain, node budget) names what it
   refused and burns no revision; `apply=false`, `dry_run` and a replayed request_id write nothing.
"""

import inspect
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut import mcp_server
from agentcut.contracts import (
    AUTO_GRADE_SAMPLES_MAX,
    AUTO_PERCENTILE_MAX,
    ClipColor,
    CreateProject,
    GradeLevels,
    Project,
)
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.grade import grade_filter, grade_tables
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180
CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.6}, {"x": 1.0, "y": 1.0}],
}
# Each fixture squashes the source range with lutrgb, so its own black and white are known before
# any measurement runs: 0.70*255+30 = 208, and the floor is 30.
SQUASH = "lutrgb=r='val*0.70+30':g='val*0.70+30':b='val*0.70+30'"
CAST = "lutrgb=r='val*0.80+40':g='val*0.55+25':b='val*0.70+30'"
SETTINGS = ((0.12, 0.88, 1.0), (0.05, 0.95, 0.6), (0.20, 0.75, 1.7))


def ffmpeg(argv: list[str]) -> bytes:
    done = subprocess.run(
        [str(FFMPEG), "-v", "error", *argv],
        capture_output=True,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-700:]
    return done.stdout


def reference(value: float, black: float, white: float, gamma: float) -> float:
    """Levels, written from the published formula and sharing nothing with the shipped sampler."""
    stretched = (value - black) / (white - black)
    stretched = 0.0 if stretched < 0 else 1.0 if stretched > 1 else stretched
    return stretched ** (1 / gamma)


def luma_bounds(raw: bytes, percentile: float = 0.005) -> list[int]:
    """The 0.5% percentile black and white of one RGB24 block, counted here, not in the engine."""
    counts = [0] * 256
    total = 0
    for offset in range(0, len(raw) - 2, 3):
        luma = (raw[offset] * 77 + raw[offset + 1] * 150 + raw[offset + 2] * 28) // 255
        counts[luma] += 1
        total += 1
    skip = int(round(total * percentile))
    bounds = []
    for order in (range(256), range(255, -1, -1)):
        seen = 0
        for level in order:
            seen += counts[level]
            if seen > skip:
                bounds.append(level)
                break
    assert bounds[0] < bounds[1], f"the picture is flat ({bounds})"
    return bounds


def decoded(path: Path) -> bytes:
    return ffmpeg(
        [
            "-i",
            str(path),
            "-vf",
            f"scale={WIDTH // 2}:{HEIGHT // 2}:flags=area,format=rgb24",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )


def exported_levels(stage: str, ramp: Path) -> list[int]:
    """What the exporter's own expression does to each of the 256 input levels."""
    raw = ffmpeg(
        [
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "256x1",
            "-i",
            str(ramp),
            "-vf",
            stage,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    return [raw[offset] for offset in range(0, 256 * 3, 3)]


def main() -> None:
    token = "a" * 48
    with tempfile.TemporaryDirectory(prefix="agentcut-auto-") as temp:
        folder = Path(temp)
        ramp = folder / "ramp.rgb"
        ramp.write_bytes(b"".join(bytes([level, level, level]) for level in range(256)))

        # 1. Both renderers, all 256 levels, against the formula.
        for black, white, gamma in SETTINGS:
            color = ClipColor(grade=[GradeLevels(black=black, white=white, gamma=gamma)])
            stage = grade_filter(color)
            compiled = grade_tables(color)
            assert stage and compiled, f"levels {black}/{white}/{gamma} compiled to nothing"
            assert len(compiled["stages"]) == 1 and compiled["stages"][0]["type"] == "lut", compiled
            tables = compiled["stages"][0]
            got = exported_levels(stage, ramp)
            for level in range(256):
                want = round(255 * reference(level / 255, black, white, gamma))
                assert abs(got[level] - want) <= 1, (
                    f"{black}/{white}/{gamma} level {level}: {got[level]} != {want}"
                )
                assert abs(round(255 * tables["r"][level]) - want) <= 1, f"preview level {level}"

        # A per-channel stretch touches one channel and hands the other two straight through.
        red_only = ClipColor(grade=[GradeLevels(channel="red", black=0.2, white=0.8)])
        stage = grade_filter(red_only)
        passed_through = dict(re.findall(r"([rgb])='([^']*)'", stage))
        assert passed_through.get("g") == "val" and passed_through.get("b") == "val", stage
        pulled = exported_levels(stage, ramp)
        for level in (8, 64, 200):
            want = round(255 * reference(level / 255, 0.2, 0.8, 1.0))
            assert abs(pulled[level] - want) <= 1, f"red level {level}: {pulled[level]} != {want}"
        tables = grade_tables(red_only)["stages"][0]
        assert tables["type"] == "lut" and len(grade_tables(red_only)["stages"]) == 1
        assert tables["g"] == [round(index / 255, 9) for index in range(256)], "green moved"

        # 2. A neutral node adds no stage; the contract refuses an impossible one.
        neutral = ClipColor(grade=[GradeLevels()])
        assert grade_filter(neutral) == "" and grade_tables(neutral) is None
        for bad in (
            {"black": 0.6, "white": 0.4},
            {"white": 0.05},
            {"gamma": 0.05},
            {"black": 0.95},
        ):
            try:
                GradeLevels(**bad)
            except ValueError:
                continue
            raise AssertionError(f"the contract accepted {bad}")

        def video(name: str, chain: str) -> Path:
            """A deterministic horizontal grey ramp, then squashed by `chain`.

            `gradients` picks its colours at random, so the fixture's own range would be a guess.
            A ramp written from pixel coordinates has every input level exactly once per row, which
            is what makes the percentile maths below a claim rather than a hope.
            """
            path = folder / name
            ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"nullsrc=s={WIDTH}x{HEIGHT}:d=2:r=25,format=rgb24,"
                    "geq=r='X*255/(W-1)':g='X*255/(W-1)':b='X*255/(W-1)'",
                    "-vf",
                    chain,
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(path),
                ]
            )
            return path

        def audio(name: str) -> Path:
            path = folder / name
            ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(path)])
            return path

        squashed, cast, tone = (
            video("squashed.mp4", SQUASH),
            video("cast.mp4", CAST),
            audio("tone.m4a"),
        )
        flat = folder / "flat.png"
        ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x808080:s={WIDTH}x{HEIGHT}",
                "-frames:v",
                "1",
                str(flat),
            ]
        )

        # The fixtures are what they claim to be, measured with this file's own counter.
        before = luma_bounds(decoded(squashed))
        assert 24 <= before[0] <= 36 and 200 <= before[1] <= 214, f"fixture drifted: {before}"

        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        store = ProjectStore(media.db_path, media)
        probes = {
            name: media.import_file(str(path))
            for name, path in (("sq", squashed), ("ct", cast), ("au", tone), ("fl", flat))
        }
        project = store.create(
            CreateProject(
                request_id="new", name="auto", settings={"width": WIDTH, "height": HEIGHT}
            )
        ).project
        seed = (
            [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
            ]
            + [
                {
                    "op": "asset.import",
                    "asset_id": key,
                    "label": key,
                    "probe_id": probe.id,
                    "verified": probe.verified.model_dump(),
                }
                for key, probe in probes.items()
            ]
            + [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": clip_id,
                        "asset_id": asset_id,
                        "track_id": track_id,
                        "position_ticks": position,
                        "duration_ticks": duration,
                    },
                }
                for clip_id, asset_id, track_id, position, duration in (
                    ("wide", "sq", "v", 0, 2 * T),
                    ("cast", "ct", "v", 2 * T, 2 * T),
                    ("snd", "au", "a", 0, 2 * T),
                    ("plate", "fl", "v", 4 * T, T),
                )
            ]
            + [{"op": "clip.grade", "clip_id": "wide", "grade": [CURVE]}]
        )

        with TestClient(
            create_app(store.path, token, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:

            def edit(revision: int, commands: list, request_id: str, expect: int = 200):
                answer = client.post(
                    f"/v1/projects/{project.id}/edits",
                    json={
                        "request_id": request_id,
                        "expected_revision": revision,
                        "commands": commands,
                    },
                )
                assert answer.status_code == expect, (expect, answer.text[:400])
                return answer

            def auto(clip_id: str, revision: int, request_id: str, **fields):
                return client.post(
                    f"/v1/projects/{project.id}/clips/{clip_id}/auto-grade",
                    json={"request_id": request_id, "expected_revision": revision, **fields},
                )

            edit(0, seed, "seed")

            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["grade_levels"] is True
            assert caps["features"]["clip_auto_grade"] is True
            limits = caps["grade_limits"]
            assert (limits["levels_black_max"], limits["levels_white_min"]) == (0.9, 0.1)
            assert (limits["levels_gamma_min"], limits["levels_gamma_max"]) == (0.1, 10.0)
            assert caps["limits"]["auto_grade_samples_max"] == AUTO_GRADE_SAMPLES_MAX
            assert caps["limits"]["auto_grade_percentile_max"] == AUTO_PERCENTILE_MAX

            # Plan only: the numbers come from the clip's frames, and nothing is written.
            planned = auto("wide", 1, "plan", mode="luma", percentile=0.0)
            assert planned.status_code == 200, planned.text[:400]
            proposal = planned.json()
            assert proposal["committed"] is False
            assert store.get(project.id).revision == 1, "apply=false wrote to the project"
            measured = proposal["auto_grade"]["measured"]
            low, high = measured["bounds"]["luma"]
            assert abs(low - before[0]) <= 2 and abs(high - before[1]) <= 2, (measured, before)
            assert measured["frames"] >= 2 and measured["pixels"] > 0
            commands = proposal["commands"]
            assert len(commands) == 1 and commands[0]["op"] == "clip.grade"
            nodes = commands[0]["grade"]
            # The measured node goes in FRONT: it normalises the picture, then the look runs on it.
            assert nodes[0]["kind"] == "levels" and nodes[0]["channel"] == "rgb"
            assert (
                abs(nodes[0]["black"] * 255 - low) < 1 and abs(nodes[0]["white"] * 255 - high) < 1
            )
            assert [node["kind"] for node in nodes] == ["levels", "curve"], nodes

            # Apply: one revision, the chain preserved. Pressing again replaces, it does not stack.
            applied = auto("wide", 1, "apply", mode="luma", percentile=0.0, apply=True)
            assert applied.status_code == 200, applied.text[:400]
            assert (
                applied.json()["project"]["revision"] == 2 and store.get(project.id).revision == 2
            )
            chain = Project.model_validate(applied.json()["project"]).clips["wide"].color.grade
            assert [node.kind for node in chain] == ["levels", "curve"]
            assert chain[0].black == nodes[0]["black"] and chain[0].white == nodes[0]["white"]
            again = auto("wide", 2, "again", mode="luma", percentile=0.05, apply=True)
            assert again.json()["project"]["revision"] == 3, again.text[:300]
            kinds = [
                node["kind"] for node in again.json()["project"]["clips"]["wide"]["color"]["grade"]
            ]
            assert kinds == ["levels", "curve"], f"the second press stacked: {kinds}"

            # A replayed request_id is the same receipt, not a fourth revision.
            replay = auto("wide", 2, "again", mode="luma", percentile=0.05, apply=True)
            assert replay.json()["project"]["revision"] == 3 and replay.json()["replayed"] is True
            assert store.get(project.id).revision == 3
            # dry_run on a fresh id is accepted and writes nothing.
            dry = auto("wide", 3, "dry", mode="luma", percentile=0.0, apply=True, dry_run=True)
            assert dry.status_code == 200, dry.text[:300]
            assert store.get(project.id).revision == 3

            # replace=false refuses by position rather than compounding two stretches.
            clash = auto("wide", 3, "clash", mode="luma", percentile=0.0, replace=False)
            assert clash.status_code == 422, clash.text[:300]
            problem = clash.json()["error"]
            assert problem["code"] == "AUTO_GRADE_CONFLICT", problem
            assert problem["details"]["positions"] == [0]
            assert "clip.grade" in problem["message"] or "levels" in problem["message"].lower()
            assert store.get(project.id).revision == 3, "a refusal burned a revision"

            # Per-channel mode measures three bounds, and a cast fixture must not agree on them.
            rgb_plan = auto("cast", 3, "rgb", mode="rgb", percentile=0.0).json()
            levels_nodes = [n for n in rgb_plan["commands"][0]["grade"] if n["kind"] == "levels"]
            assert len(levels_nodes) >= 2, rgb_plan["auto_grade"]["measured"]
            blacks = {node["channel"]: node["black"] for node in levels_nodes}
            assert max(blacks.values()) - min(blacks.values()) > 0.02, blacks

            # The window has to be the source the clip *plays*, not the timeline length — 1.83
            # shipped that confusion, and this pair is what tells the two apart: at 200 % a
            # one-second clip consumes two seconds, so it must see the bright second the 100 %
            # clip never reaches.
            halves = folder / "halves.mp4"
            ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"nullsrc=s={WIDTH}x{HEIGHT}:d=2:r=25,format=rgb24,"
                    "geq=r='20+40*Y/(H-1)+160*gte(T,1)'"
                    ":g='20+40*Y/(H-1)+160*gte(T,1)'"
                    ":b='20+40*Y/(H-1)+160*gte(T,1)'",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(halves),
                ]
            )
            halves_probe = media.import_file(str(halves))
            current = store.get(project.id).revision
            seeded = edit(
                current,
                [
                    {
                        "op": "asset.import",
                        "asset_id": "hs",
                        "label": "halves",
                        "probe_id": halves_probe.id,
                        "verified": halves_probe.verified.model_dump(),
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "slow",
                            "asset_id": "hs",
                            "track_id": "v",
                            "position_ticks": 6 * T,
                            "duration_ticks": T,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "fast",
                            "asset_id": "hs",
                            "track_id": "v",
                            "position_ticks": 7 * T,
                            "duration_ticks": T,
                            "speed_percent": 200,
                        },
                    },
                ],
                "halves-seed",
            )
            at = seeded.json()["project"]["revision"]
            slow = auto("slow", at, "auto-slow", mode="luma", percentile=0.0).json()
            fast = auto("fast", at, "auto-fast", mode="luma", percentile=0.0).json()
            slow_bounds = slow["auto_grade"]["measured"]["bounds"]["luma"]
            fast_bounds = fast["auto_grade"]["measured"]["bounds"]["luma"]
            assert slow_bounds[1] <= 72, f"100 % should read only its own second: {slow_bounds}"
            assert fast_bounds[1] >= 198, f"200 % reads twice the source: {fast_bounds}"
            slow_window = slow["auto_grade"]["measured"]["window"]
            fast_window = fast["auto_grade"]["measured"]["window"]
            assert fast_window["source_ticks"] == 2 * slow_window["source_ticks"], (
                slow_window,
                fast_window,
            )
            assert slow_window["source_in_ticks"] == fast_window["source_in_ticks"] == 0

            # No picture to measure, on either side of the definition.
            silent = auto("snd", 3, "snd", mode="luma")
            assert silent.status_code == 422, silent.text[:300]
            assert silent.json()["error"]["code"] == "AUTO_GRADE_INVALID"
            assert silent.json()["error"]["details"]["asset_kind"] == "audio"
            moved = edit(
                store.get(project.id).revision,
                [
                    {
                        "op": "clip.move",
                        "clip_id": "cast",
                        "track_id": "a",
                        "position_ticks": 4 * T,
                    }
                ],
                "move",
            )
            moved_to = moved.json()["project"]["revision"]
            wrong = auto("cast", moved_to, "wrong", mode="luma")
            assert wrong.status_code == 422, wrong.text[:300]
            assert wrong.json()["error"]["code"] == "AUTO_GRADE_INVALID"
            assert wrong.json()["error"]["details"]["track_id"] == "a"

            # A flat picture has no range: either the named refusal, or numbers and no node.
            # A fresh request_id: the store dedupes writes by request_id per project, so reusing the
            # import's id here would replay that receipt instead of measuring anything.
            flat_answer = auto("plate", moved_to, "auto-flat", mode="luma")
            if flat_answer.status_code == 422:
                detail = flat_answer.json()["error"]
                assert detail["code"] == "AUTO_GRADE_NO_RANGE", detail
                assert detail["details"]["high"] - detail["details"]["low"] < 16
                assert store.get(project.id).revision == moved_to
            else:
                assert "auto_grade" in flat_answer.json(), flat_answer.text[:400]
                assert flat_answer.json()["auto_grade"]["nodes"] == []

            # 3. The compiled stage moves real pixels: the fixture becomes full-range.
            stored = store.get(project.id)
            written = [c for c in stored.clips["wide"].color.grade if c.kind == "levels"][0]
            stage = grade_filter(stored.clips["wide"].color)
            assert "lutrgb=" in stage
            stretched = folder / "stretched.mp4"
            ffmpeg(
                [
                    "-i",
                    str(squashed),
                    "-vf",
                    stage,
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(stretched),
                ]
            )
            after = luma_bounds(decoded(stretched))
            assert after[0] <= 4 and after[1] >= 251, (
                f"the stretch did not widen the picture: {before} -> {after}"
            )
            assert written.gamma == 1.0

            # The graph the exporter will run carries the stage, and the preview is handed the same
            # numbers the exporter's expression produced at the same levels.
            graph = "\n".join(compile_render_plan(stored, "h264-source-quality").filters)
            assert "lutrgb=" in graph, graph[:200]
            manifest = client.get(f"/v1/projects/{project.id}/preview-manifest").json()
            handed = manifest["clips"]["wide"]["grade"]["stages"][0]
            assert handed["type"] == "lut" and handed["id"].startswith("l")
            exported = exported_levels(stage, ramp)
            for level in range(256):
                assert abs(round(255 * handed["r"][level]) - exported[level]) <= 1, level

            # The Agent reaches the same seam: the MCP adapter carries a typed tool for this route.
            adapter = inspect.getsource(mcp_server)
            assert "async def clip_auto_grade" in adapter, "the Agent has no auto-grade tool"
            assert "/clips/{clip_id}/auto-grade" in adapter, "the tool points somewhere else"

        # Wiring, asserted from Python because the TS harness bundles a temp copy and cannot read
        # the repository — the split 1.82 established. One predicate, one grey-out rule.
        source = (ROOT / "desktop/src/views/GradeFields.tsx").read_text(encoding="utf-8")
        assert source.count("autoGradeBlocker(") == 1, (
            "the block must be decided in exactly one place"
        )
        assert source.count("disabled={Boolean(autoBlock) || locked}") == 1
        assert source.count("autoBlock ??") == 1, "the tooltip must come from the same predicate"
        assert "autoGradeClip(clipId, autoMode" in source, "the button is not wired to the route"
        hints = (ROOT / "desktop/src/engine.ts").read_text(encoding="utf-8")
        for code in (
            "AUTO_GRADE_INVALID",
            "AUTO_GRADE_FAILED",
            "AUTO_GRADE_NO_RANGE",
            "AUTO_GRADE_CONFLICT",
            "AUTO_GRADE_LIMIT",
        ):
            assert f"{code}:" in hints, f"{code} has no Chinese sentence"
        graph = (ROOT / "desktop/src/gradeGraph.ts").read_text(encoding="utf-8")
        assert 'levels: "色阶"' in graph, "the node picker does not know the levels card"
    print("autograde: compile fidelity, measurement, receipts, refusals and export all verified")


if __name__ == "__main__":
    main()
