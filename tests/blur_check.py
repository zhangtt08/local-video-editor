"""Soft focus: one radius, two renderers, measured on real pixels.

The knob is `ClipEffects.blur`, a fraction of the frame height, and this check insists on three
things the project cares about: the exporter actually runs the radius it was given (measured from
the edge profile of the rendered frame, not from the request), the preview is handed the same radius
in the only units that stay correct when the panel is smaller than the frame, and a masked blur
stays inside the mask. The contract/refusal cases pin the parts that would otherwise be silent:
an out-of-range value must not burn a revision, and a frame too tall for the verified band must be
refused by name instead of letting FFmpeg quietly clamp the kernel.
"""

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import (
    BLUR_LIMIT,
    BLUR_RADIUS_LIMIT_PX,
    GBLUR_STEPS,
    CreateProject,
    EditBatch,
    Project,
    blur_sigma,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180
BLUR = 0.10
RADIUS = blur_sigma(BLUR, HEIGHT)


def edge_png(path: Path) -> None:
    """A real 320x180 PNG whose left half is white and right half black."""
    row = bytes([255, 255, 255]) * (WIDTH // 2) + bytes([0, 0, 0]) * (WIDTH // 2)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(b"\0" + row for _ in range(HEIGHT))))
        + chunk(b"IEND", b"")
    )


def crossing(profile: list[float], level: float) -> float:
    for x in range(1, len(profile)):
        high, low = profile[x - 1], profile[x]
        if high >= level > low:
            span = high - low
            return (x - 1) + (high - level) / span if span else x - 1
    raise AssertionError(f"level {level} never crossed")


def radius_of(profile: list[int], edge: float) -> float:
    """The standard deviation a step edge was actually blurred by.

    A Gaussian-blurred step crosses 50% at the edge, 84.13% one radius before it and 15.87% one
    after, so three crossings report what the implementation applied.
    """
    hi, lo = max(profile), min(profile)
    assert hi - lo > 100, f"the plate has no contrast left ({lo}..{hi})"
    norm = [(v - lo) / (hi - lo) for v in profile]
    left = crossing(norm, 0.5) - crossing(norm, 0.8413)
    right = crossing(norm, 0.1587) - crossing(norm, 0.5)
    return (left + right) / 2


def main() -> None:
    token = "b" * 48
    with tempfile.TemporaryDirectory(prefix="agentcut-blur-") as temp:
        folder = Path(temp)
        edge_png(folder / "edge.png")
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        store = ProjectStore(media.db_path, media)
        probe = media.import_file(str(folder / "edge.png"))

        def run(argv, **kwargs):
            done = subprocess.run(
                [str(FFMPEG), "-v", "error", *argv],
                capture_output=True,
                creationflags=0x08000000,
                **kwargs,
            )
            assert done.returncode == 0, done.stderr.decode(errors="replace")[-700:]
            return done.stdout

        def edit(project_id, revision, commands, request_id, expect=200):
            body = {
                "request_id": request_id,
                "expected_revision": revision,
                "commands": commands,
            }
            answer = client.post(f"/v1/projects/{project_id}/edits", json=body)
            assert answer.status_code == expect, (expect, answer.text[:400])
            return answer

        project = store.create(
            CreateProject(
                request_id="new",
                name="blur",
                settings={"width": WIDTH, "height": HEIGHT},
            )
        ).project
        seed = [
            {"op": "track.add", "track": {"id": "back", "kind": "video", "name": "back"}},
            {"op": "track.add", "track": {"id": "top", "kind": "video", "name": "top"}},
            {
                "op": "asset.import",
                "asset_id": "edge",
                "label": "edge",
                "probe_id": probe.id,
                "verified": probe.verified.model_dump(),
            },
        ] + [
            {
                "op": "clip.add",
                "clip": {
                    "id": clip_id,
                    "asset_id": "edge",
                    "track_id": track_id,
                    "position_ticks": 0,
                    "duration_ticks": 2 * T,
                },
            }
            for clip_id, track_id in (("sharp", "back"), ("soft", "top"))
        ]
        with TestClient(
            create_app(store.path, token, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            edit(project.id, 0, seed, "seed")
            committed = edit(
                project.id,
                1,
                [{"op": "clip.patch", "clip_id": "soft", "effects": {"blur": BLUR}}],
                "blur",
            )
            stored = Project.model_validate(committed.json()["project"])
            assert stored.clips["soft"].effects.blur == BLUR
            assert stored.clips["sharp"].effects.blur == 0.0

            # Out of the contract's range: refused, and not one revision burned.
            over = edit(
                project.id,
                2,
                [{"op": "clip.patch", "clip_id": "soft", "effects": {"blur": BLUR_LIMIT + 0.01}}],
                "over",
                expect=422,
            )
            assert over.json()["error"]["code"] == "INVALID_REQUEST", over.text
            assert store.get(project.id).revision == 2

            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["clip_blur"] is True
            assert caps["limits"]["blur_fraction"] == BLUR_LIMIT
            assert caps["limits"]["blur_radius_limit_px"] == BLUR_RADIUS_LIMIT_PX

            graph = "\n".join(compile_render_plan(stored, "h264-source-quality").filters)
            assert f"gblur=sigma={RADIUS:.4f}:steps={GBLUR_STEPS}" in graph, (
                "the blur radius never reached the exporter: " + graph[:200]
            )
            assert graph.count("gblur") == 1, "the sharp clip got blurred too"

            manifest = client.get(f"/v1/projects/{project.id}/preview-manifest").json()
            css = manifest["clips"]["soft"]["color_filter"]
            assert css.endswith(f"blur({BLUR * 100:g}cqh)"), css
            # 1cqh is 1% of the frame's rendered height, so the preview number and the exporter
            # number have to be the same fraction of the same frame — not two approximations.
            preview_cqh = float(css[css.rindex("blur(") + 5 : css.rindex("cqh")])
            assert preview_cqh / 100 * HEIGHT == RADIUS
            assert "blur" not in manifest["clips"]["sharp"]["color_filter"]

            def row(project, at=1.0):
                plan = compile_render_plan(project, "h264-source-quality")
                for name, body in plan.text_files.items():
                    (folder / name).write_text(body, encoding="utf-8")
                raw = run(
                    [
                        *plan.input_args,
                        "-filter_complex",
                        ";".join([*plan.filters, f"{plan.audio_label}anullsink"]),
                        "-map",
                        plan.video_label,
                        "-ss",
                        str(at),
                        "-frames:v",
                        "1",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "pipe:1",
                    ],
                    cwd=folder,
                )
                assert len(raw) == WIDTH * HEIGHT * 3, len(raw)
                return [raw[(HEIGHT // 2 * WIDTH + x) * 3] for x in range(WIDTH)]

            # Only the top clip is blurred, so sample the frame where the sharp one is on top:
            # `top` composites over `back`, and the edge under test is the top layer's own edge.
            blurred = radius_of(row(stored), WIDTH / 2 - 0.5)
            off = edit(
                project.id,
                2,
                [{"op": "clip.patch", "clip_id": "soft", "effects": {"blur": 0.0}}],
                "off",
            )
            control = radius_of(row(Project.model_validate(off.json()["project"])), WIDTH / 2 - 0.5)
            assert control < 1.0, f"the unblurred frame already measures {control} px"
            assert abs(blurred - RADIUS) <= 0.08 * RADIUS + 1, (blurred, RADIUS)

            # A shape decides where the blur lands: inside the box it is the blurred picture,
            # outside it the sharp one underneath, unchanged. This is the privacy-mask workflow.
            masked = edit(
                project.id,
                3,
                [
                    {"op": "clip.patch", "clip_id": "soft", "effects": {"blur": BLUR}},
                    {
                        "op": "clip.mask",
                        "clip_id": "soft",
                        "mask": {"shape": "rectangle", "width": 0.5, "height": 1.0, "feather": 0.0},
                    },
                ],
                "masked",
            )
            cut = Project.model_validate(masked.json()["project"])
            inside_box = row(cut)
            plain = row(stored)
            sharp = row(Project.model_validate(off.json()["project"]))
            outside = max(
                abs(inside_box[x] - sharp[x]) for x in list(range(8, 72)) + list(range(248, 312))
            )
            inside = max(abs(inside_box[x] - plain[x]) for x in range(100, 220))
            assert outside <= 3, f"the mask let the blur reach {outside} levels outside the box"
            assert inside <= 3, f"inside the box the blur changed by {inside} levels"

            # One picture track takes the `cut` chain: a second, faster builder for the same
            # picture, and the place a per-clip filter gets forgotten. The preview blurs every
            # layer, so this path has to land on the same radius the layered chain produced. The
            # first 1.64 build shipped exactly this frame sharp, which is why the case is here.
            one = store.create(
                CreateProject(
                    request_id="one", name="one", settings={"width": WIDTH, "height": HEIGHT}
                )
            ).project
            one = edit(
                one.id,
                0,
                [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "edge",
                        "label": "edge",
                        "probe_id": probe.id,
                        "verified": probe.verified.model_dump(),
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "only",
                            "asset_id": "edge",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 2 * T,
                        },
                    },
                    {"op": "clip.patch", "clip_id": "only", "effects": {"blur": BLUR}},
                ],
                "one-seed",
            )
            fast = Project.model_validate(one.json()["project"])
            fast_plan = compile_render_plan(fast, "h264-source-quality")
            assert fast_plan.mode == "cut", fast_plan.mode
            assert f"gblur=sigma={RADIUS:.4f}:steps={GBLUR_STEPS}" in "\n".join(
                fast_plan.filters
            ), "the cut chain dropped the soft focus: " + "\n".join(fast_plan.filters)[:200]
            cut_radius = radius_of(row(fast), WIDTH / 2 - 0.5)
            assert abs(cut_radius - blurred) <= 1.0, (cut_radius, blurred)

            # The encoder is the last thing to touch the picture; the ramp has to survive it.
            out = folder / "blurred.mp4"
            plan = compile_render_plan(cut, "h264-source-quality")
            # `ffmpeg_argv` already names the binary, so this one call does not go through run().
            done = subprocess.run(
                plan.ffmpeg_argv(str(FFMPEG), str(out)),
                cwd=folder,
                capture_output=True,
                creationflags=0x08000000,
            )
            assert done.returncode == 0, done.stderr.decode(errors="replace")[-700:]
            listed = (
                subprocess.run(
                    [
                        str(FFPROBE),
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height",
                        "-of",
                        "csv=p=0",
                        str(out),
                    ],
                    capture_output=True,
                    check=True,
                    creationflags=0x08000000,
                )
                .stdout.decode()
                .strip()
            )
            assert listed == f"{WIDTH},{HEIGHT}", listed
            frame_bytes = WIDTH * HEIGHT * 3
            decoded = run(["-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
            assert len(decoded) >= 11 * frame_bytes, len(decoded)
            tenth = decoded[10 * frame_bytes : 11 * frame_bytes]
            video_radius = radius_of(
                [tenth[(HEIGHT // 2 * WIDTH + x) * 3] for x in range(WIDTH)], WIDTH / 2 - 0.5
            )

            # A frame taller than the measured band must be refused by name, not clamped.
            tall = store.create(
                CreateProject(
                    request_id="tall", name="tall", settings={"width": 320, "height": 280}
                )
            ).project
            tall = store.mutate(
                tall.id,
                EditBatch(
                    request_id="tall-seed",
                    expected_revision=0,
                    commands=seed,
                ),
            ).project
            tall = store.mutate(
                tall.id,
                EditBatch(
                    request_id="tall-blur",
                    expected_revision=tall.revision,
                    commands=[
                        {"op": "clip.patch", "clip_id": "soft", "effects": {"blur": BLUR_LIMIT}}
                    ],
                ),
            ).project
            assert blur_sigma(BLUR_LIMIT, 280) > BLUR_RADIUS_LIMIT_PX
            try:
                compile_render_plan(tall, "h264-source-quality")
            except Exception as refused:
                assert getattr(refused, "code", None) == "BLUR_OUT_OF_RANGE", refused
                assert refused.details["max_blur"] == BLUR_RADIUS_LIMIT_PX / 280
            else:
                raise AssertionError("a 70 px radius was not refused")

            # Receipts must not split when a field the client never heard of is added. The two
            # digests below were captured from the model *before* `blur` existed, so a client
            # retrying a request it made last version still hits its own receipt — including the
            # case where another effect was set and only `blur` is at its default, which is exactly
            # what an all-or-nothing comparison misses.
            def digest(effects):
                clip = {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "t",
                    "position_ticks": 0,
                    "duration_ticks": T,
                }
                if effects is not None:
                    clip["effects"] = effects
                return store._fingerprint(
                    "edit",
                    EditBatch(
                        request_id="d",
                        expected_revision=0,
                        commands=[{"op": "clip.add", "clip": dict(clip)}],
                    ),
                )

            legacy = {
                "x": 0.0,
                "y": 0.0,
                "scale": 1.0,
                "rotation": 0.0,
                "opacity": 1.0,
                "gain": 1.0,
            }
            all_default = "550dda4e22ccfa207e6f3602364f37ae6bca5502cd759b80a2a7aac68e81ad88"
            opacity_half = "e811fc4f4473165670c21e97bab1706741dca77a865a12446532b6c23460c52f"
            assert digest(legacy) == digest(None) == digest({}) == all_default
            assert digest({**legacy, "opacity": 0.5}) == opacity_half
            assert digest({**legacy, "opacity": 0.5, "blur": 0.0}) == opacity_half
            assert digest({**legacy, "opacity": 0.5, "blur": 0.02}) != opacity_half
            assert digest({**legacy, "blur": 0.02}) != all_default

            print(
                f"PASS: blur {BLUR} asks for {RADIUS:.1f} px and the frame measures "
                f"{blurred:.2f} px (unblurred {control:.2f}); the manifest hands the preview the "
                f"same radius as {BLUR * 100:g}cqh; masked to a box the blur stays inside it "
                f"({outside} levels leaked); through H.264 the ramp still measures "
                f"{video_radius:.2f} px; {BLUR_LIMIT} on a 280 px frame is refused as "
                f"BLUR_OUT_OF_RANGE; the single-track cut chain blurs to the same radius "
                f"({cut_radius:.2f} px); pre-1.64 effect receipts still hash the same with or "
                f"without opacity set, and only a real blur value moves it"
            )


if __name__ == "__main__":
    main()
