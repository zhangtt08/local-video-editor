"""The engine inside the Windows package has to answer for 1.151, not just the source tree.

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
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import (  # noqa: E402
    APP_VERSION,
    COLOR_TRANSFER_TAGS,
    OUTPUT_COLOUR_TAGS,
    SCHEMA_VERSION,
)
from agentcut.contracts import TIMEBASE as T  # noqa: E402

BIN = ROOT / "desktop/resources/bin"
ENGINE = BIN / "agentcut/agentcut.exe"
FFMPEG = BIN / "ffmpeg.exe"
FFPROBE = BIN / "ffprobe.exe"

# 包里那支 exe 从「按下」到「说出端口」最多允许这么久；超过就是红，不是等。
# 冷启动实测 774 ms（1.218 那份），这里留的是量级的余量，不是「先等等看」。
START_DEADLINE_SECONDS = 90


def stop(proc):
    """收尾只有一只手：terminate → 等 → kill → 连子树一起 taskkill。"""
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        # 这台机器上 taskkill 会自己卡住（1.219 实测：`tasklist`、`Get-CimInstance` 与它一起不动，
        # 而那支 exe 恰好就是起不来的那一份）。收尾不能把红的那一句换成一句 traceback——
        # 「九十分钟到点」这一档要说的是端口没来，不是收尾失败。
        pass


def _wait_briefly(proc):
    """它已经不再吐字了：给它几秒自己退出，别把「还在收尾」当成「活着」。"""
    try:
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        return False


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
    # 那一行 ready 必须**在截止时间内**读到。以前这里是 `proc.stdout.readline()`：包里的 exe 一旦
    # 起不来又不吐字，这一句就永远不返回——门禁不是红，是挂了 40 分钟，被整套的 2400 s 兜住才报
    # TIMEOUT（1.219 实测到这件事：`--help` 都不回话的一份 exe，把整条验收链钉在原地）。
    # 改成读线的线程把每一行放进队列，主线程按截止时间取；到点就是红，红的这一句里带着它真正吐出的
    # 那几行，不用再来一次 40 分钟才知道它说了什么。
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        try:
            for line in proc.stdout:
                lines.put(line)
        except (OSError, ValueError) as failure:
            lines.put(f"the reader gave up: {failure}\n")
        lines.put("")

    threading.Thread(target=pump, daemon=True).start()
    seen: list[str] = []
    deadline = time.time() + START_DEADLINE_SECONDS
    while time.time() < deadline:
        try:
            line = lines.get(timeout=max(0.05, deadline - time.time()))
        except queue.Empty:
            break
        if line == "":
            # 字都吐完了也没有 ready：等它自己退出，别把「已经死了」读成「还在起」。
            stopped = proc.poll() is not None or _wait_briefly(proc)
            stop(proc)
            raise AssertionError(
                f"the packed engine died before reporting a port: rc={proc.returncode} "
                f"stopped={stopped}; it said: {' | '.join(seen)[:400] or '(nothing)'}"
            )
        seen.append(line)
        if line.startswith("{"):
            info = json.loads(line)
            return proc, info["base_url"], info
    stop(proc)
    raise AssertionError(
        f"the packed engine never reported a port within {START_DEADLINE_SECONDS}s; "
        f"rc={proc.poll()}; it said: {' | '.join(seen)[:400] or '(nothing)'}"
    )


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
            assert caps["features"]["colour_tag_delivery"] is True, caps["features"]
            assert caps["output_colour_tags"] == [dict(item) for item in OUTPUT_COLOUR_TAGS], caps[
                "output_colour_tags"
            ]
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
            # 1.151 over the shipped binary: the same query surface has to reach the plan that adds
            # both the container claim and the fold, and an id outside the table is refused by name.
            plan_base = (
                f"/v1/projects/{pid}/render-plan?preset_id=h264-720p-web"
                f"&revision={state['revision']}"
            )
            status, untagged = call(base, token, "GET", plan_base)
            assert status == 200, untagged
            argv = " ".join(untagged["argv_preview"])
            assert "-colorspace" not in argv and "zscale=matrix" not in argv, argv[-260:]
            assert untagged["plan"]["colour_tag"] is None, untagged["plan"]
            # 每一档都要在装机版那支引擎上单独问一遍：容器 trio 与折叠那一句都是钉死的字面量，
            # 表里加一档而这里不跟着加，那条「点名的出路与表相符」当场就红。
            tiers = [
                (
                    "bt709",
                    ("-color_primaries bt709", "-color_trc bt709", "-colorspace bt709"),
                    "zscale=matrix=709:range=tv",
                ),
                (
                    "bt601",
                    ("-color_primaries bt709", "-color_trc bt709", "-colorspace smpte170m"),
                    "zscale=matrix=170m:range=tv",
                ),
                (
                    "bt2020",
                    ("-color_primaries bt2020", "-color_trc bt709", "-colorspace bt2020nc"),
                    "zscale=matrix=2020_ncl:range=tv",
                ),
                (
                    "p3-d65",
                    ("-color_primaries smpte432", "-color_trc bt709", "-colorspace bt709"),
                    "zscale=matrix=709:range=tv",
                ),
            ]
            assert [item[0] for item in tiers] == [str(row["id"]) for row in OUTPUT_COLOUR_TAGS], (
                "装机版这一档点名的档位与契约表不符：加一档而不在这儿量它，等于没量"
            )
            for code, claims, fold in tiers:
                status, tagged = call(base, token, "GET", f"{plan_base}&colour_tag={code}")
                assert status == 200, (code, tagged)
                argv = " ".join(tagged["argv_preview"])
                for claim in claims:
                    assert claim in argv, (code, claim, argv[-320:])
                assert fold in argv, (code, fold, argv[-320:])
                if code in {"bt2020", "p3-d65"}:
                    # 换基色那两档必须真带一站基色转换；只写标签不转换，就是 1.152 拒过的那种谎。
                    assert "lut3d=file=primaries-" in argv, (code, "少了基色那一站", argv[-320:])
                assert tagged["plan"]["colour_tag"] == code, (code, tagged["plan"])
            status, unknown = call(base, token, "GET", f"{plan_base}&colour_tag=p3-dci")
            assert status == 422, unknown
            assert unknown["error"]["code"] == "UNKNOWN_COLOUR_TAG", unknown
            assert unknown["error"]["details"]["known"] == [item[0] for item in tiers], (
                "那句拒绝点名的出路与表里那几档不符：" + str(unknown["error"]["details"])
            )
            print(
                "   render-plan over the packed build: untagged argv carries no claim, "
                "each published tier adds its own trio + fold, an unknown id is refused"
            )
            print(
                f"PASS: the engine inside the package serves {caps['app_version']} over real HTTP, "
                "and its refusal writes nothing"
            )
        finally:
            stop(proc)


if __name__ == "__main__":
    main()
