"""Transparent mastering, measured as alpha bytes in the delivered file.

A person or an Agent asks for a matte so it can be dropped over other footage. Nothing about that
is proven by a filter string: the only statement that matters is what the alpha plane of the
exported file contains where the timeline is empty, where one clip paints, and where a clip is at
half opacity. So this check renders through the real job worker and reads bytes back out of the
files with FFmpeg:

1. the preset table owns the word "alpha". A preset either has room for a transparency band or it
   does not, and both the exporter's refusal and the desktop's checkbox read that one field, so a
   request that would silently export an opaque file is refused by name instead of obeyed wrongly.
2. the alpha is threaded, not just flagged. The same timeline exported with the flag off must read
   255 everywhere (the black plate is opaque) — that control run is what makes the 0 / 255 / ~127
   measurements below mean "the matte survived" rather than "the file has an alpha plane".
3. the whole request surface carries it: the plan dry-run, the single render, the batch, the stored
   job, the idempotency fingerprint and the MCP adapter all speak the same one word.
"""

import asyncio
import json
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project, RenderRequest, capabilities, render_presets
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime, plan_for
from agentcut.mcp_server import create_mcp
from agentcut.media import MediaService
from agentcut.render import compile_render_plan, output_args

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
SECONDS = 2.0
TONE = 440.0
# A bright solid magenta plate: far from black in every plane, so "alpha 255 where the picture is"
# and "the picture really is there" are two separate readings that cannot both be satisfied by an
# all-black render.
FILTER = (
    f"color=c=0xFF00FF:s={SRC_W}x{SRC_H}:r=30:d={SECONDS},"
    "format=yuv444p,"
    f"drawbox=x=40:y=40:w=80:h=60:color=0x00FF00:t=fill"
)
ALPHA_PRESET = "prores-4444-alpha"
ALPHA_WEB_PRESET = "vp9-1080p-web-alpha"
# Positions are counted in frames, not multiplied out of decimal seconds: `int(1.6 * T)` lands one
# tick below a frame boundary and the engine is right to refuse it.
FRAME = T // 30
# Where the timeline puts what: A paints frames 15–45 at full opacity, B paints 48–60 at half.
CLIP_A = (15, 45, 1.0)
CLIP_B = (48, 60, 0.5)
TIMES = {"empty": 6 / 30, "solid": 30 / 30, "half": 54 / 30}


def run(args, timeout=900):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    target = folder / "alpha-source.mp4"
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
            FILTER,
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE}:sample_rate=48000:duration={SECONDS}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-crf",
            "10",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ]
    )
    return target


def portrait_source(folder: Path) -> Path:
    """竖着的 180x320 片源：只有素材自己的比例与交付帧不同时，`contain` 才真的补出边来。"""
    target = folder / "alpha-portrait.mp4"
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
            "color=c=0xFF00FF:s=180x320:r=30:d=2,format=yuv444p,"
            "drawbox=x=30:y=120:w=80:h=60:color=0x00FF00:t=fill",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE}:sample_rate=48000:duration=2",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-crf",
            "10",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ]
    )
    return target


def probe(path: Path, entries: str, stream: str | None = None) -> dict:
    argv = [str(FFPROBE), "-v", "error"]
    if stream:
        argv += ["-select_streams", stream]
    argv += ["-show_entries", entries, "-of", "json", str(path)]
    return json.loads(run(argv).stdout.decode())


def frame_size(path: Path) -> tuple[int, int]:
    got = probe(path, "stream=index,width,height", "v:0")["streams"][0]
    return int(got["width"]), int(got["height"])


def _plane(path: Path, at: float, video_filter: str) -> tuple[int, int, bytes]:
    """One 8-bit gray plane of one real frame at `at`, plus the width it has to be read at.

    WebM/VP9 keeps its matte in a side channel the *native* decoder does not unfold — measured here:
    `alphaextract` on a native decode fails with "Requested planes not available" while the libvpx
    decoder hands back the alpha plane. The decoder is therefore named for that container.
    """
    width, height = frame_size(path)
    decode = ["-c:v", "libvpx-vp9"] if path.suffix == ".webm" else []
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            *decode,
            "-i",
            str(path),
            "-ss",
            f"{at:.3f}",
            "-frames:v",
            "1",
            "-vf",
            video_filter,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    ).stdout
    assert len(raw) >= width * height, (len(raw), width, height, raw[:40])
    return width, height, raw


def alpha_byte(path: Path, at: float, fx: float, fy: float) -> int:
    """One pixel's alpha, as the delivered file really stores it.

    `alphaextract` moves the alpha plane into a gray stream and 8-bit rawvideo is what the byte is
    read from — nothing in this path re-derives the value from a filter string. Coordinates are
    fractions so the same reading works on the 320x180 project and a preset that scales up.
    """
    width, _, raw = _plane(path, at, "alphaextract")
    return _pixel(raw, width, fx, fy)


def luma(path: Path, at: float, fx: float, fy: float) -> int:
    width, _, raw = _plane(path, at, "format=gray")
    return _pixel(raw, width, fx, fy)


def _pixel(raw: bytes, width: int, fx: float, fy: float) -> int:
    # The planes come back at the file's own size, so a fraction is the only coordinate that means
    # the same spot on the 320x180 project and on a preset that scales up to 1080p.
    height = len(raw) // width
    return raw[min(int(fy * height), height - 1) * width + min(int(fx * width), width - 1)]


def vout(plan) -> str:
    """The filter line that produces the delivered picture — the only one that says what the
    encoder is handed. The audio chain is appended after it, so `filters[-1]` is not it."""
    return next(item for item in plan.filters if item.endswith("[vout]"))


def contract_suite() -> None:
    presets = {item["id"]: item for item in render_presets()}
    flagged = [item["id"] for item in render_presets() if item["alpha"]]
    assert flagged, "no preset can carry a matte, so the feature would be unreachable"
    for name in flagged:
        # The flag has to mean what it says: an alpha pixel format, and a container that stores one.
        assert str(presets[name]["pixel_format"]).startswith("yuva"), presets[name]
        assert presets[name]["container"] in ("mov", "webm"), presets[name]
    for name, item in presets.items():
        if name in flagged:
            continue
        assert not str(item["pixel_format"] or "").startswith("yuva"), f"{name} lies about alpha"
    caps = capabilities(media_ready=True)
    assert caps["alpha_presets"] == flagged, caps["alpha_presets"]

    # The refusal: a preset without room for alpha cannot be asked to deliver one, and the sentence
    # has to name the exits that really exist.
    exits = "、".join(flagged)
    for name in ("h264-source-quality", "audio-mp3", "mxf-mpeg2"):
        try:
            output_args(presets[name], 48_000, 30.0, transparent=True)
        except Exception as error:  # noqa: BLE001 - the code is the assertion
            assert error.code == "TRANSPARENT_NEEDS_ALPHA", (name, error.code)
            assert exits in error.message, (name, error.message)
            assert error.status == 422, error.status
        else:
            raise AssertionError(f"{name} accepted a matte it cannot write")
    assert output_args(presets["h264-source-quality"], 48_000, 30.0)[:2] == ["-c:v", "libx264"]

    # The alpha preset's own knobs: a ProRes profile 4 (the only 4444) and a pixel format with a
    # band in it. Neither is decoration — the encoder is steered by nothing else.
    web = output_args(presets[ALPHA_WEB_PRESET], 48_000, 30.0, transparent=True)
    assert "yuva420p" in web, web
    assert "-b:v" in web, web
    prores = output_args(presets[ALPHA_PRESET], 48_000, 30.0, transparent=True)
    assert prores[prores.index("-profile:v") + 1] == "4", prores
    assert prores[prores.index("-pix_fmt") + 1] == "yuva444p10le", prores
    # The flag decides whether a matte is requested; it does not silently resteer an encoder that
    # was already going to write the same pixels.
    same = output_args(presets[ALPHA_PRESET], 48_000, 30.0)
    assert prores == same, (prores, same)

    # The internal flag for nested sequences must stay internal: the public one skips timeline
    # validation in the child only because the parent already validated it.
    render_src = (ROOT / "src/agentcut/render.py").read_text(encoding="utf-8")
    assert "_transparent=True," in render_src, "nesting lost its own flag"
    assert "alpha_out = transparent or _transparent" in render_src, "the two flags did not merge"
    # Every surface that prints a plan prints the same one: the job view goes through `plan_for`
    # with the job's own range and matte instead of rebuilding it from the defaults.
    api_src = (ROOT / "src/agentcut/http_api.py").read_text(encoding="utf-8")
    block = api_src[api_src.index("def get_job") : api_src.index("def list_jobs")]
    assert "plan_for(" in block, "the job view went around plan_for again"
    assert "transparent=job.transparent" in block, block
    assert "range_mode=job.range" in block, block
    assert "compile_render_plan(" not in block, "the job view rebuilt the plan on defaults"
    print(f"   {len(flagged)} presets carry alpha; every other one is refused by name: {exits}")


def wait(client: TestClient, job_id: str) -> dict:
    status: dict = {}
    for _ in range(1200):
        status = client.get("/v1/jobs/" + job_id).json()
        if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
            break
    return status


def render(client: TestClient, path: str, revision: int, body: dict) -> dict:
    response = client.post(path + "/renders", json=body)
    assert response.status_code == 200, response.text
    summary = wait(client, response.json()["job"]["id"])["job"]
    assert summary["status"] == "succeeded", summary
    assert summary["output_checked"] is True, summary
    return summary


def media_suite(folder: Path) -> dict:
    media = MediaService(
        folder / "alpha-db.sqlite3", [folder], folder / "alpha-cache", FFMPEG, FFPROBE
    )
    runtime = JobRuntime(
        folder / "alpha-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    runtime.ensure_worker()
    token = "alphacheck" + "e" * 56
    app = create_app(folder / "alpha-api.sqlite3", token, media=media, jobs=runtime)
    outputs: dict[str, Path] = {}
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        clip = source(folder)
        probe_body = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "matte",
                # Canvas equals source: the matte below is the composite's, not a scale filter's.
                "settings": {
                    "width": SRC_W,
                    "height": SRC_H,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        commands = [
            {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "v1"}},
            {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "v2"}},
            {
                "op": "asset.import",
                "asset_id": "a",
                "label": "a",
                "probe_id": probe_body["id"],
                "verified": probe_body["verified"],
            },
        ]
        for index, (start, end, opacity) in enumerate((CLIP_A, CLIP_B)):
            commands.append(
                {
                    "op": "clip.add",
                    "clip": {
                        "id": f"c{index}",
                        "asset_id": "a",
                        "track_id": f"v{index + 1}",
                        "position_ticks": start * FRAME,
                        "duration_ticks": (end - start) * FRAME,
                        # Half opacity is a clip effect, and it is the matte's own knob: the
                        # exporter multiplies the alpha plane by exactly this number.
                        "effects": {"opacity": opacity},
                    },
                }
            )
        seeded = client.post(
            path + "/edits",
            json={"request_id": "seed", "expected_revision": 0, "commands": commands},
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        project = Project.model_validate(seeded.json()["project"])

        # ---- the graph: the matte is threaded through, not merely promised
        opaque = compile_render_plan(project, ALPHA_PRESET)
        matte_plan = compile_render_plan(project, ALPHA_PRESET, transparent=True)
        assert opaque.summary["transparent"] is False, opaque.summary
        assert matte_plan.summary["transparent"] is True, matte_plan.summary
        assert opaque.summary["pixel_format"] == "yuva444p10le", opaque.summary
        # The picture chain's last stage is what the encoder is handed; the audio tail comes after
        # it, so the `[vout]` line has to be found by name rather than by position.
        assert "format=yuva444p10le[vout]" in vout(opaque), vout(opaque)
        assert "format=rgba[vout]" in vout(matte_plan), vout(matte_plan)
        canvas = [item for item in matte_plan.input_args if item.startswith("color=c=")]
        assert any("black@0" in item for item in canvas), canvas
        assert not any("black@0" in item for item in opaque.input_args if item.startswith("color="))
        assert matte_plan.mode == "layered", matte_plan.mode
        assert "-pix_fmt" in matte_plan.output_args
        assert matte_plan.output_args[matte_plan.output_args.index("-pix_fmt") + 1] == (
            "yuva444p10le"
        )
        # plan_for (the HTTP/MCP dry-run path) reaches the same compiler.
        assert plan_for(project, ALPHA_PRESET, transparent=True).summary["transparent"] is True
        # 换一个画幅交付：补边发生在合成那一层，用的就是 black@0，所以补出来的黑带不会偷偷变不透明。
        # 这条只说清来源；真正作证的是下面那两个文件读数（同形状不透明导出读到的是 255）。
        barred = compile_render_plan(
            project, ALPHA_PRESET, preview_size=(180, 320), transparent=True
        )
        assert barred.mode == "layered", barred.mode
        assert any("pad=" in item and "color=black@0" in item for item in barred.filters), (
            barred.filters[:4]
        )
        # 反向也要断：轨道链那层先铺的黑板过去就是在这里把补边压回不透明的。
        assert not any("pad=" in item and "color=black," in item for item in barred.filters), [
            item for item in barred.filters if "pad=" in item
        ]
        assert "format=rgba[vout]" in vout(barred), vout(barred)
        print(
            "   the transparent plan paints over a black@0 canvas and ends in rgba; "
            "the same preset without the flag ends in yuva444p10le"
        )

        # ---- HTTP: the dry-run answers the query, and a refusal costs nothing
        dry = client.get(path + f"/render-plan?preset_id={ALPHA_PRESET}&transparent=true").json()
        assert dry["plan"]["transparent"] is True, dry["plan"]
        assert "-pix_fmt" in dry["argv_preview"]
        plain = client.get(path + f"/render-plan?preset_id={ALPHA_PRESET}").json()
        assert plain["plan"]["transparent"] is False, plain["plan"]
        before = client.get(path).json()["revision"]
        jobs_before = client.get(path + "/jobs?limit=50").json()["jobs"]
        refused = client.post(
            path + "/renders",
            json={
                "request_id": "wrong-preset",
                "expected_revision": revision,
                "preset_id": "h264-source-quality",
                "filename": "骗人的.mp4",
                "transparent": True,
            },
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "TRANSPARENT_NEEDS_ALPHA", refused.text
        assert ALPHA_PRESET in refused.json()["error"]["message"], refused.text
        assert client.get(path).json()["revision"] == before, "a refusal wrote state"
        assert client.get(path + "/jobs?limit=50").json()["jobs"] == jobs_before, refused.text

        # ---- the real files, measured a byte at a time
        matte = render(
            client,
            path,
            revision,
            {
                "request_id": "ship-matte",
                "expected_revision": revision,
                "preset_id": ALPHA_PRESET,
                "filename": "透明母版.mov",
                "transparent": True,
            },
        )
        control = render(
            client,
            path,
            revision,
            {
                "request_id": "ship-control",
                "expected_revision": revision,
                "preset_id": ALPHA_PRESET,
                "filename": "同一预设不透明.mov",
            },
        )
        web = render(
            client,
            path,
            revision,
            {
                "request_id": "ship-web",
                "expected_revision": revision,
                "preset_id": ALPHA_WEB_PRESET,
                "filename": "透明网页.webm",
                "transparent": True,
            },
        )
        outputs[ALPHA_PRESET] = Path(matte["output_path"])
        outputs["control"] = Path(control["output_path"])
        outputs[ALPHA_WEB_PRESET] = Path(web["output_path"])
        assert matte["transparent"] is True, matte
        assert control["transparent"] is False, control
        # What the container says about the stream. ProRes states its alpha plane in the metadata;
        # WebM/VP9 does not (measured: `pix_fmt` reads yuv420p there even though the matte is in the
        # file), which is exactly why the byte measurement below, not this probe, is the evidence.
        expected = {
            "matte": ("prores", "yuva444p10le"),
            "control": ("prores", "yuva444p10le"),
            "web": ("vp9", None),
        }
        for name, job in (("matte", matte), ("control", control), ("web", web)):
            got = probe(Path(job["output_path"]), "stream=index,codec_name,pix_fmt", "v:0")[
                "streams"
            ][0]
            codec, pix_fmt = expected[name]
            assert got["codec_name"] == codec, (name, got)
            if pix_fmt:
                assert got["pix_fmt"] == pix_fmt, (name, got)

        measured = {
            name: {
                label: alpha_byte(Path(job["output_path"]), at, 0.04, 0.04)
                for label, at in TIMES.items()
            }
            for name, job in (("matte", matte), ("web", web), ("control", control))
        }
        # ProRes 4444 is visually lossless in alpha: the plate really is empty, the clip really is
        # opaque, and half opacity really is half.
        assert measured["matte"]["empty"] <= 2, measured
        assert measured["matte"]["solid"] >= 250, measured
        assert 118 <= measured["matte"]["half"] <= 138, measured
        # VP9 is lossy and its matte rides in a side channel, so the bands are wider here: the
        # reading still says the alpha survived the whole round trip (the native decoder cannot
        # even unfold it — see `_plane`).
        assert measured["web"]["empty"] <= 8, measured
        assert measured["web"]["solid"] >= 245, measured
        assert 105 <= measured["web"]["half"] <= 150, measured
        # The control run is what makes those numbers mean the matte: with the flag off the same
        # preset, the same timeline reads fully opaque everywhere — including the empty stretch.
        assert all(value >= 250 for value in measured["control"].values()), measured
        # And where alpha says "picture here", there is a picture.
        lit = luma(outputs[ALPHA_PRESET], TIMES["solid"], 0.3, 0.5)
        dark = luma(outputs[ALPHA_PRESET], TIMES["empty"], 0.3, 0.5)
        assert lit > 20, (lit, dark)
        print(
            "   measured alpha bytes (empty / solid / half): "
            f"matte {measured['matte']['empty']} {measured['matte']['solid']} "
            f"{measured['matte']['half']}, web {measured['web']['empty']} "
            f"{measured['web']['solid']} {measured['web']['half']}, "
            f"control {measured['control']['empty']} {measured['control']['solid']} "
            f"{measured['control']['half']}; luma under the clip {lit} vs over the plate {dark}"
        )

        # ---- idempotency: the flag is part of the request, not a decoration
        replay = client.post(
            path + "/renders",
            json={
                "request_id": "ship-matte",
                "expected_revision": revision,
                "preset_id": ALPHA_PRESET,
                "filename": "透明母版.mov",
                "transparent": True,
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["job"]["id"] == matte["id"], replay.json()["job"]
        flipped = client.post(
            path + "/renders",
            json={
                "request_id": "ship-matte",
                "expected_revision": revision,
                "preset_id": ALPHA_PRESET,
                "filename": "透明母版.mov",
                "transparent": False,
            },
        )
        assert flipped.status_code == 409, flipped.text
        assert flipped.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT", flipped.text

        # ---- batch: each item keeps its own answer, and dry-run shows it before anything is paid
        batch = client.post(
            path + "/renders/batch",
            json={
                "request_id": "mixed",
                "expected_revision": revision,
                "dry_run": True,
                "items": [
                    {"preset_id": ALPHA_PRESET, "filename": "b1.mov", "transparent": True},
                    {"preset_id": ALPHA_PRESET, "filename": "b2.mov"},
                ],
            },
        )
        assert batch.status_code == 200, batch.text
        flags = [item["transparent"] for item in batch.json()["jobs"]]
        assert flags == [True, False], flags
        plans = [item["transparent"] for item in batch.json()["plans"]]
        assert plans == [True, False], plans
        refused_batch = client.post(
            path + "/renders/batch",
            json={
                "request_id": "mixed-bad",
                "expected_revision": revision,
                "items": [
                    {"preset_id": ALPHA_PRESET, "filename": "ok.mov", "transparent": True},
                    {
                        "preset_id": "h264-source-quality",
                        "filename": "bad.mp4",
                        "transparent": True,
                    },
                ],
            },
        )
        assert refused_batch.status_code == 422, refused_batch.text
        assert refused_batch.json()["error"]["code"] == "TRANSPARENT_NEEDS_ALPHA", (
            refused_batch.text
        )
        # All-or-nothing: the batch that refused its second item queued neither file.
        queued = client.get(path + "/jobs?limit=50").json()["jobs"]
        assert len(queued) == len(jobs_before) + 3, [item["job"]["id"] for item in queued]

        # ---- 换一个画幅：补出来的边在透明母版里也得是空的（量的文件，不是量的滤镜串）
        pclip = portrait_source(folder)
        probe2 = client.post("/v1/media/import", json={"path": str(pclip)}).json()
        portrait = client.post(
            "/v1/projects",
            json={
                "request_id": "portrait",
                "name": "竖着要透明",
                "settings": {
                    "width": 180,
                    "height": 320,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
            },
        ).json()["project"]
        ppath = f"/v1/projects/{portrait['id']}"
        pseed = client.post(
            ppath + "/edits",
            json={
                "request_id": "portrait-seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "v1"}},
                    {
                        "op": "asset.import",
                        "asset_id": "p",
                        "label": "p",
                        "probe_id": probe2["id"],
                        "verified": probe2["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "cp",
                            "asset_id": "p",
                            "track_id": "v1",
                            "position_ticks": 15 * FRAME,
                            "duration_ticks": 30 * FRAME,
                        },
                    },
                ],
            },
        )
        assert pseed.status_code == 200, pseed.text
        presion = pseed.json()["project"]["revision"]
        with_bars = render(
            client,
            ppath,
            presion,
            {
                "request_id": "ship-bars",
                "expected_revision": presion,
                "preset_id": ALPHA_WEB_PRESET,
                "filename": "透明竖屏.webm",
                "fit": "contain",
                "transparent": True,
            },
        )
        no_bars = render(
            client,
            ppath,
            presion,
            {
                "request_id": "ship-bars-flat",
                "expected_revision": presion,
                "preset_id": ALPHA_WEB_PRESET,
                "filename": "同一竖屏不透明.webm",
                "fit": "contain",
            },
        )
        bar_alpha = alpha_byte(Path(with_bars["output_path"]), TIMES["solid"], 0.02, 0.5)
        pic_alpha = alpha_byte(Path(with_bars["output_path"]), TIMES["solid"], 0.5, 0.5)
        flat_bar = alpha_byte(Path(no_bars["output_path"]), TIMES["solid"], 0.02, 0.5)
        assert bar_alpha <= 8, (bar_alpha, pic_alpha, flat_bar)
        assert pic_alpha >= 245, (bar_alpha, pic_alpha, flat_bar)
        # 不透明那一条边上读到的就是 255 的黑板——这一行说明上面那个 0 是补边的功劳，不是没补。
        assert flat_bar >= 250, (bar_alpha, pic_alpha, flat_bar)
        print(
            f"   竖屏 9:16 进 16:9 的透明交付：pillarbox 边 {bar_alpha}、画面中间 {pic_alpha}，"
            f"同一条不透明导出的边是 {flat_bar}"
        )

        # ---- the MCP adapter asks the same question with the same words
        server = create_mcp("http://127.0.0.1:1", token)
        tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
        captured: list[tuple[str, str, dict | None]] = []

        async def spy(method: str, api_path: str, payload: dict | None = None, timeout: float = 60):
            captured.append((method, api_path, payload))
            return {"ok": True}

        for name in ("render_plan", "render_start"):
            fn = tools[name].fn
            assert "call" in fn.__code__.co_freevars, fn.__code__.co_freevars
            fn.__closure__[fn.__code__.co_freevars.index("call")].cell_contents = spy
        asyncio.run(
            tools["render_plan"].fn(
                project_id=created["id"],
                preset_id=ALPHA_PRESET,
                revision=revision,
                range="marks",
                transparent=True,
            )
        )
        asyncio.run(
            tools["render_start"].fn(
                project_id=created["id"],
                request=RenderRequest(
                    request_id="mcp-1",
                    expected_revision=revision,
                    preset_id=ALPHA_PRESET,
                    filename="mcp.mov",
                    transparent=True,
                ),
            )
        )
        plan_call = next(item for item in captured if "render-plan" in item[1])
        assert "transparent=true" in plan_call[1], plan_call
        assert "range=marks" in plan_call[1], plan_call
        start_body = captured[-1][2]
        assert start_body["transparent"] is True, start_body
        # The query the adapter builds is the query the API answers: replayed for real here. A
        # `range=marks` string is checked above (this timeline has no marks, and the engine is
        # right to refuse one), so the replay asks with the range the project actually has.
        asyncio.run(
            tools["render_plan"].fn(
                project_id=created["id"],
                preset_id=ALPHA_PRESET,
                revision=revision,
                transparent=True,
            )
        )
        replayable = [item for item in captured if "render-plan" in item[1]][-1]
        assert "transparent=true" in replayable[1], replayable
        assert "range" not in replayable[1], replayable
        query = replayable[1].split("?", 1)[1]
        answered = client.get(f"/v1/projects/{created['id']}/render-plan?{query}").json()
        assert answered["plan"]["transparent"] is True, answered["plan"]
        print(f"   MCP dry-run builds {plan_call[1]} and the API answers {replayable[1]}")
        return outputs


def packaged_surface() -> None:
    """The desktop reads the preset table instead of restating it."""
    panel = (ROOT / "desktop/src/views/ExportPanel.tsx").read_text(encoding="utf-8")
    engine = (ROOT / "desktop/src/engine.ts").read_text(encoding="utf-8")
    assert "TRANSPARENT_NEEDS_ALPHA" in engine, "no Chinese sentence for the new refusal"
    assert "checked={matte}" in panel and "const matte = " in panel, "the checkbox is not effective"
    assert "transparent: matte" in panel, "the panel does not send what the checkbox says"
    stale = re.findall(r"transparent:\s*(true|false)", panel)
    assert not stale, f"a hard-coded transparent literal in the panel: {stale}"
    assert "alpha?: boolean" in engine, "Preset lost the field the refusal reads"


def main() -> None:
    import tempfile

    contract_suite()
    packaged_surface()
    with tempfile.TemporaryDirectory(prefix="agentcut-alpha-") as scratch:
        media_suite(Path(scratch))
    print(
        "PASS: a transparent master exported by the job worker is measured to hold its matte "
        "(empty 0, opaque 255, half ~127) where the same preset without the flag reads 255 "
        "everywhere, and every surface that renders asks with the same one word"
    )


if __name__ == "__main__":
    main()
