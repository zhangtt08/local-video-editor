"""A linked pair's picture edge can move on its own: a J/L cut that the export really shows.

`clip.trim_linked` moves both sides of an audio/video link together, which is what an ordinary trim
of a linked pair means. A J/L cut is the opposite decision: the picture changes shot while the sound
from the previous shot is still playing. That needs one edge of the pair to move by itself while the
link record survives, and it needs the offset to be readable rather than a dead end.

Every claim here is read back either from the reducer's own numbers or from a rendered file: the
control export shows the picture before the cut, the candidate shows the same audio sample under a
different picture. The refusals are asked both dry and for real, and each names the ticks that were
available.
"""

import hashlib
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from agentcut.contracts import TIMEBASE, EditBatch, EditorError, Project, capabilities
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands, link_status

T = TIMEBASE
ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
GREEN_START = 1 * T  # how much of the second shot's source sits before its timeline head


def ffmpeg():
    return ROOT / "desktop/node_modules/ffmpeg-static/ffmpeg.exe"


def ffprobe():
    return ROOT / "desktop/resources/bin/ffprobe.exe"


def run(args, timeout=90):
    return subprocess.run(
        [str(ffmpeg()), "-v", "error", "-y", *args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def probe(path):
    return subprocess.run(
        [
            str(ffprobe()),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=60,
        text=True,
    ).stdout.strip()


def rgb_at(path, at_seconds):
    """One real decoded pixel, averaged over the frame so a stray edge pixel cannot decide it.

    The seek is on the output side: the export only has a keyframe every two seconds, and decoding
    from zero to the asked-for instant is the only way to be sure which frame was read.
    """
    raw = subprocess.run(
        [
            str(ffmpeg()),
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            str(at_seconds),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=60,
        creationflags=0x08000000,
    ).stdout
    return tuple(raw[i] for i in range(3))


def tone_amplitude(path, at_seconds, freq):
    """How much of one exact frequency is in the exported sound at one instant.

    A 0.1 s window of the decoded PCM, correlated with cos/sin at that frequency: an on-tone window
    measures ~1450 counts and an off-tone window measures 0.0 on these two files. FFmpeg's own
    `bandpass` was tried first and still read -31 dB a whole octave away, which is not a number
    anyone can set a threshold against, so the measurement is done here instead.
    """
    wav = path.with_suffix(".%d.wav" % int(at_seconds * 100))
    run(["-i", str(path), "-vn", "-c:a", "pcm_s16le", str(wav)])
    handle = wave.open(str(wav), "rb")
    try:
        rate, channels, frames = handle.getframerate(), handle.getnchannels(), handle.getnframes()
        start = int(at_seconds * rate)
        count = min(int(0.1 * rate), frames - start)
        handle.setpos(start)
        values = struct.unpack("<%dh" % (count * channels), handle.readframes(count))
    finally:
        handle.close()
    mono = values[0::channels]
    real = sum(v * math.cos(2 * math.pi * freq * i / rate) for i, v in enumerate(mono))
    imag = sum(v * math.sin(2 * math.pi * freq * i / rate) for i, v in enumerate(mono))
    return math.hypot(real, imag) / len(mono)


def batch(commands, revision=0, request="jlcut", dry=False):
    return EditBatch.model_validate(
        {
            "request_id": request,
            "expected_revision": revision,
            "commands": commands,
            "dry_run": dry,
        }
    )


def verified(
    path: Path, name: str, kind: str, duration: int, width=None, height=None, sample_rate=None
):
    return {
        "probe_id": name,
        "path": str(path),
        "kind": kind,
        "label": name,
        "size_bytes": path.stat().st_size,
        "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duration_ticks": duration,
        "width": width,
        "height": height,
        # The two picture files were cut with -an: the record has to say so, or the render plan
        # asks FFmpeg for an audio stream that is not in the container.
        "has_audio": sample_rate is not None,
        "audio_sample_rate": sample_rate,
    }


def asset(path, name, kind, duration, width=None, height=None, sample_rate=None):
    return {
        "id": name,
        "kind": kind,
        "label": name,
        "reference": str(path),
        "duration_ticks": duration,
        "verified": verified(path, name, kind, duration, width, height, sample_rate),
    }


def clip(cid, asset_id, track_id, position, duration, source_in=0, link=None):
    return {
        "id": cid,
        "asset_id": asset_id,
        "track_id": track_id,
        "position_ticks": position,
        "duration_ticks": duration,
        "source_in_ticks": source_in,
        "link_id": link,
    }


def refusal(commands, project, revision, label, code, dry):
    """One refusal, asked dry and for real: same code, and the project does not move."""
    try:
        apply_commands(
            project,
            batch(
                commands, revision, request=f"jl-{label}-{'dry' if dry else 'go'}", dry=dry
            ).commands,
        )
        raise AssertionError(f"{label}: expected {code} (dry={dry})")
    except EditorError as err:
        assert err.code == code, f"{label} dry={dry}: got {err.code}, want {code}"
        assert err.message, f"{label}: nameless refusal"
        assert err.details, f"{label} {code}: empty details"
        return err


def main():
    # An Agent discovers commands from the capability list, not from the contract classes: an op
    # that is only in the union is an op nothing can find.
    published = capabilities()["commands"]
    for op in ("clip.link_split_trim", "clips.link_reconcile"):
        assert op in published, f"{op} 不在能力表里：界面与 Agent 都无从知道有这一条"

    with tempfile.TemporaryDirectory(prefix="agentcut-jlcut-") as folder:
        folder = Path(folder)
        red = folder / "red.mp4"
        green = folder / "green.mp4"
        tone_a = folder / "tone440.wav"
        tone_b = folder / "tone880.wav"
        run(
            [
                "-f",
                "lavfi",
                "-i",
                "color=red:s=320x180:r=30:d=2",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(red),
            ]
        )
        run(
            [
                "-f",
                "lavfi",
                "-i",
                "color=#1ec81e:s=320x180:r=30:d=4",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(green),
            ]
        )
        run(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", str(tone_a)])
        run(["-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=2", str(tone_b)])

        project = Project.model_validate(
            {
                "id": "jl",
                "name": "jl cut",
                "settings": {
                    "width": 320,
                    "height": 180,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
                "tracks": [
                    {"id": "v", "kind": "video", "name": "v"},
                    {"id": "a", "kind": "audio", "name": "a"},
                ],
                "assets": {
                    "red": asset(red, "red", "video", 2 * T, 320, 180),
                    "green": asset(green, "green", "video", 4 * T, 320, 180),
                    "tone_a": asset(tone_a, "tone_a", "audio", 2 * T, sample_rate=48000),
                    "tone_b": asset(tone_b, "tone_b", "audio", 2 * T, sample_rate=48000),
                },
                "clips": {
                    # Two shots, each a picture/sound pair that is already linked: the state the
                    # desktop reaches when it puts a clip with embedded audio on the timeline.
                    "vp_a": clip("vp_a", "red", "v", 0, 2 * T),
                    "vp_b": clip("vp_b", "green", "v", 2 * T, 2 * T, GREEN_START),
                    "ap_a": clip("ap_a", "tone_a", "a", 0, 2 * T, link="link_a"),
                    "ap_b": clip("ap_b", "tone_b", "a", 2 * T, 2 * T, link="link_b"),
                },
            }
        )
        linked = apply_commands(
            project,
            batch(
                [
                    {"op": "clips.link", "clip_ids": ["vp_a", "ap_a"], "link_id": "link_a"},
                    {"op": "clips.link", "clip_ids": ["vp_b", "ap_b"], "link_id": "link_b"},
                ]
            ).commands,
        )
        before = link_status(linked)
        assert before["link_a"]["synchronized"] and before["link_b"]["synchronized"], before
        assert before["link_a"]["anchor_clip_id"] == "vp_a", before["link_a"]

        # --- the cut: two split trims, one batch, one revision worth of history -----------------
        cut = [
            {"op": "clip.link_split_trim", "clip_id": "vp_a", "edge": "tail", "delta_ticks": -T},
            {"op": "clip.link_split_trim", "clip_id": "vp_b", "edge": "head", "delta_ticks": -T},
        ]
        dry = apply_commands(linked, batch(cut, 0, request="jl-dry", dry=True).commands)
        after = apply_commands(linked, batch(cut, 0, request="jl-cut").commands)
        assert dry.clips.keys() == after.clips.keys()
        assert (
            after.clips["vp_a"].position_ticks,
            after.clips["vp_a"].duration_ticks,
            after.clips["vp_a"].source_in_ticks,
        ) == (0, T, 0), after.clips["vp_a"]
        assert (
            after.clips["vp_b"].position_ticks,
            after.clips["vp_b"].duration_ticks,
            after.clips["vp_b"].source_in_ticks,
        ) == (T, 3 * T, 0), after.clips["vp_b"]
        # The sound pair never moved, and both links survived being split.
        for cid in ("ap_a", "ap_b"):
            moved = after.clips[cid]
            anchor = linked.clips[cid]
            assert (
                moved.position_ticks,
                moved.duration_ticks,
                moved.source_in_ticks,
            ) == (
                anchor.position_ticks,
                anchor.duration_ticks,
                anchor.source_in_ticks,
            ), (cid, moved)
        assert after.clips["vp_a"].link_id == "link_a" and after.clips["vp_b"].link_id == "link_b"

        split = link_status(after)
        assert not split["link_a"]["synchronized"] and not split["link_b"]["synchronized"]
        # `differences` counts each member against the anchor (the picture), so a cut that shortens
        # the picture reads as the sound being longer -- which is how the desktop has to say it.
        assert split["link_a"]["anchor_clip_id"] == "vp_a", split["link_a"]
        assert split["link_a"]["differences"]["vp_a"] == {
            "position_ticks": 0,
            "source_ticks": 0,
            "duration_ticks": 0,
            "speed_percent": 0,
        }, split["link_a"]
        assert split["link_a"]["differences"]["ap_a"]["duration_ticks"] == T, split["link_a"]
        assert split["link_b"]["differences"]["ap_b"]["position_ticks"] == T, split["link_b"]
        assert split["link_b"]["differences"]["ap_b"]["duration_ticks"] == -T, split["link_b"]

        # --- what the exported file actually contains ---------------------------------------------
        control = compile_render_plan(linked, "h264-source-quality")
        control_out = folder / "control.mp4"
        subprocess.run(
            control.ffmpeg_argv(str(ffmpeg()), str(control_out)),
            capture_output=True,
            check=True,
            timeout=120,
            creationflags=0x08000000,
        )
        plan = compile_render_plan(after, "h264-source-quality")
        cut_out = folder / "cut.mp4"
        subprocess.run(
            plan.ffmpeg_argv(str(ffmpeg()), str(cut_out)),
            capture_output=True,
            check=True,
            timeout=120,
            creationflags=0x08000000,
        )

        # 1.5 s: the control is still on the first shot; after the cut the second shot's picture is
        # up while the first shot's 440 Hz is still running under it.
        control_picture, cut_picture = rgb_at(control_out, 1.5), rgb_at(cut_out, 1.5)
        assert control_picture[0] > 120 and control_picture[1] < 80, control_picture
        assert cut_picture[1] > 120 and cut_picture[0] < 80, cut_picture
        loud, quiet = tone_amplitude(cut_out, 1.5, 440), tone_amplitude(cut_out, 1.5, 880)
        assert loud > 700 and quiet < 0.05 * loud, (loud, quiet)
        # And it flips at the sound seam: 880 Hz only once the second shot's audio starts.
        loud2, quiet2 = tone_amplitude(cut_out, 2.5, 880), tone_amplitude(cut_out, 2.5, 440)
        assert loud2 > 700 and quiet2 < 0.05 * loud2, (loud2, quiet2)
        # The control proves the sound never moved: the same window in the un-cut export carries the
        # same 440 level, so the difference above is the picture, not the audio.
        control_loud = tone_amplitude(control_out, 1.5, 440)
        assert abs(control_loud - loud) < 0.05 * loud, (control_loud, loud)
        assert abs(float(probe(cut_out)) - 4.0) < 0.1, probe(cut_out)

        # --- reconcile: one step back onto the anchor's window -----------------------------------
        settled = apply_commands(
            after,
            batch(
                [{"op": "clips.link_reconcile", "link_id": "link_a"}], 0, request="jl-sync"
            ).commands,
        )
        assert link_status(settled)["link_a"]["synchronized"], link_status(settled)["link_a"]
        assert (
            settled.clips["ap_a"].position_ticks,
            settled.clips["ap_a"].duration_ticks,
        ) == (0, T), settled.clips["ap_a"]
        # The untouched pair keeps its offset: reconciling one link is not a global undo.
        assert not link_status(settled)["link_b"]["synchronized"]

        # link_b's picture now starts a second before its sound's source can reach: the engine says
        # so, and names the member and how far short it is.
        tight = refusal(
            [{"op": "clips.link_reconcile", "link_id": "link_b"}],
            after,
            0,
            "reconcile-head",
            "LINK_RECONCILE_NO_ROOM",
            dry=False,
        )
        assert tight.details["clip_id"] == "ap_b", tight.details
        assert tight.details["wanted_ticks"] == T and tight.details["available_ticks"] == 0, (
            tight.details
        )

        # A third pair, this one with a picture whose source is longer than its sound: growing the
        # picture past the sound makes the reconcile ask the sound for a second it does not have.
        grown = apply_commands(
            after,
            batch(
                [
                    {"op": "clip.add", "clip": clip("vp_c", "green", "v", 4 * T, 2 * T)},
                    {"op": "clip.add", "clip": clip("ap_c", "tone_a", "a", 4 * T, 2 * T)},
                    {"op": "clips.link", "clip_ids": ["vp_c", "ap_c"], "link_id": "link_c"},
                ],
                0,
                request="jl-third",
            ).commands,
        )
        assert link_status(grown)["link_c"]["synchronized"], link_status(grown)["link_c"]
        grown = apply_commands(
            grown,
            batch(
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "vp_c",
                        "edge": "tail",
                        "delta_ticks": T,
                    }
                ],
                0,
                request="jl-grow",
            ).commands,
        )
        assert (grown.clips["vp_c"].duration_ticks, grown.clips["vp_c"].link_id) == (
            3 * T,
            "link_c",
        )
        tail = refusal(
            [{"op": "clips.link_reconcile", "link_id": "link_c"}],
            grown,
            0,
            "reconcile-tail",
            "LINK_RECONCILE_NO_ROOM",
            dry=False,
        )
        assert tail.details["clip_id"] == "ap_c", tail.details
        assert tail.details["wanted_ticks"] == 3 * T and tail.details["available_ticks"] == 2 * T, (
            tail.details
        )

        # --- the refusals, each asked dry and for real -------------------------------------------
        cases = [
            (
                "not-linked",
                project,
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "vp_a",
                        "edge": "tail",
                        "delta_ticks": T,
                    }
                ],
                "LINK_SPLIT_NOT_LINKED",
            ),
            (
                "no-move",
                after,
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "ap_a",
                        "edge": "tail",
                        "delta_ticks": 0,
                    }
                ],
                "LINK_SPLIT_NO_MOVE",
            ),
            (
                "not-aligned",
                after,
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "ap_a",
                        "edge": "tail",
                        "delta_ticks": 3 * 1470 + 1,
                    }
                ],
                "LINK_SPLIT_NOT_ALIGNED",
            ),
            (
                "tail-past-source",
                after,
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "ap_a",
                        "edge": "tail",
                        "delta_ticks": T,
                    }
                ],
                "LINK_SPLIT_NO_ROOM",
            ),
            (
                "head-past-zero",
                after,
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "ap_a",
                        "edge": "head",
                        "delta_ticks": -2 * T,
                    }
                ],
                "LINK_SPLIT_NO_ROOM",
            ),
            (
                "empty",
                after,
                [
                    {
                        "op": "clip.link_split_trim",
                        "clip_id": "ap_a",
                        "edge": "tail",
                        "delta_ticks": -2 * T,
                    }
                ],
                "LINK_SPLIT_EMPTY",
            ),
            (
                "in-sync",
                linked,
                [{"op": "clips.link_reconcile", "link_id": "link_a"}],
                "LINK_IN_SYNC",
            ),
            (
                "missing-link",
                after,
                [{"op": "clips.link_reconcile", "link_id": "nope"}],
                "NOT_FOUND",
            ),
        ]
        measured = {}
        for label, target, commands, code in cases:
            dry_err = refusal(commands, target, 0, label, code, dry=True)
            real_err = refusal(commands, target, 0, label, code, dry=False)
            assert dry_err.details == real_err.details, (label, dry_err.details, real_err.details)
            measured[label] = (code, real_err.details)

        # The room a refused trim asked for has to be the room that really exists, not a guess.
        assert measured["tail-past-source"][1]["available_ticks"] == 0, measured["tail-past-source"]
        assert measured["head-past-zero"][1]["available_ticks"] == 0, measured["head-past-zero"]
        assert measured["not-aligned"][1]["quantum_ticks"] == T // 48000, measured["not-aligned"]
        assert measured["empty"][1]["duration_ticks"] == 2 * T, measured["empty"]

        # A split trim reads its track during the batch, so a clip pointing at a track that is not
        # there has to be named, not raised out of the reducer as a 500.
        ghost = refusal(
            [
                {
                    "op": "clip.add",
                    "clip": clip("vp_ghost", "red", "ghost", 0, T, link="link_a"),
                },
                {
                    "op": "clip.link_split_trim",
                    "clip_id": "vp_ghost",
                    "edge": "tail",
                    "delta_ticks": T,
                },
            ],
            after,
            0,
            "ghost-track",
            "MISSING_REFERENCE",
            dry=False,
        )
        assert ghost.details["clip_id"] == "vp_ghost", ghost.details

        # A locked member track refuses both the split and the reconcile before anything is written.
        locked = apply_commands(
            after,
            batch(
                [{"op": "track.update", "track_id": "a", "locked": True}], 0, request="jl-lock"
            ).commands,
        )
        refusal(
            [
                {
                    "op": "clip.link_split_trim",
                    "clip_id": "ap_a",
                    "edge": "tail",
                    "delta_ticks": T // 48000,
                }
            ],
            locked,
            0,
            "locked-trim",
            "TRACK_LOCKED",
            dry=False,
        )
        refusal(
            [{"op": "clips.link_reconcile", "link_id": "link_a"}],
            locked,
            0,
            "locked-reconcile",
            "TRACK_LOCKED",
            dry=False,
        )

        print(
            "PASS: J/L cut splits one linked edge and the export shows it "
            f"(1.5 s picture {cut_picture} carries 440 Hz at {loud:.0f} counts and 880 Hz at "
            f"{quiet:.1f}; control picture {control_picture} carries the same {control_loud:.0f}; "
            f"refusals {sorted(measured)})"
        )


if __name__ == "__main__":
    main()
