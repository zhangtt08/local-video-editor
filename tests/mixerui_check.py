"""1.280：混音台的真页面验收——展开这一节、点 S、拖滑杆，再回引擎读那一笔。

为什么要有这一档：`mixer_check.py` 证明混音算术对；壳检证明源码里只有一套规则。
两者都说不出「检查器里真的有这一节、点 S 真的写进工程、滑杆拖动过程中没有写」。
这一档用真 DOM 与真的鼠标/键盘量这三件事，判据是引擎回执与 DOM 几何。

跑法：空闲机器单跑 `uv run python tests/mixerui_check.py`（要渲染层构建产物、node、Edge、
随包 ffmpeg；缺一样就点名）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION  # noqa: E402

RENDERER = ROOT / "desktop/dist/renderer"
PROBE = ROOT / "scripts/ui_mixer_probe.cjs"
EDGE = Path(
    os.environ.get("AGENTCUT_EDGE", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "mixeruicheck" + "m" * 52
SECOND = 70_560_000
PORT = 0


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(path: str, token: str, payload=None, method="GET"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def tone(folder: Path, name: str, hz: float) -> Path:
    target = folder / name
    done = subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i",
         f"sine=frequency={hz}:sample_rate=48000:duration=2", str(target)],
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-500:]
    return target


def seed(folder: Path) -> str:
    made = request("/v1/projects", TOKEN, {"request_id": "mixerui-new", "name": "混音台"}, "POST")
    pid = made["project"]["id"]
    probes = {}
    for key, file in (("a", folder / "a440.wav"), ("b", folder / "b880.wav")):
        probes[key] = request("/v1/media/import", TOKEN, {"path": str(file)}, "POST")["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "解说"}},
        {"op": "track.add", "track": {"id": "b", "kind": "audio", "name": "配乐"}},
    ]
    for key in ("a", "b"):
        commands.append({
            "op": "asset.import", "asset_id": key, "label": key,
            "probe_id": probes[key]["probe_id"], "verified": probes[key],
        })
        commands.append({
            "op": "clip.add",
            "clip": {"id": "c" + key, "asset_id": key, "track_id": key,
                     "position_ticks": 0, "duration_ticks": 2 * SECOND},
        })
    request(
        f"/v1/projects/{pid}/edits",
        TOKEN,
        {
            "request_id": "mixerui-seed",
            "expected_revision": made["project"]["revision"],
            "commands": commands,
        },
        "POST",
    )
    return pid


def run_engine(data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    process = subprocess.Popen(
        [
            sys.executable, "-m", "agentcut", "api", "--port", str(PORT), "--json",
            "--data-dir", str(data_dir), "--cache-dir", str(data_dir / "cache"),
            "--output-dir", str(data_dir / "out"), "--media-root", str(data_dir),
            "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line and process.poll() is not None:
            fail(f"引擎没起来（退出码 {process.returncode}）：{line[:200]}")
        if '"event": "ready"' in line:
            return process
    fail("引擎 120 秒内没有报 ready")
    raise SystemExit(1)


def stop(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=20)
    except Exception:  # noqa: BLE001 - 收尾失败不该盖掉真正的红
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    global PORT
    for path, why in ((RENDERER, "渲染层没有构建（cd desktop && npm run build:renderer）"),
                      (PROBE, "量具脚本不见了"),
                      (EDGE, "没有 Edge"),
                      (FFMPEG, "随包 ffmpeg 不见了")):
        if not Path(path).exists():
            fail(f"{why}：{path}")
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-mixerui-") as raw:
        folder = Path(raw)
        tone(folder, "a440.wav", 440.0)
        tone(folder, "b880.wav", 880.0)
        engine = run_engine(folder)
        try:
            pid = seed(folder)
            out = folder / "mixer.json"
            shot = folder / "mixer.png"
            ran = subprocess.run(
                [
                    "node", str(PROBE),
                    "--renderer", str(RENDERER),
                    "--engine", f"http://127.0.0.1:{PORT}",
                    "--token", TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--out", str(out),
                    "--shot", str(shot),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=420,
                cwd=str(ROOT),
            )
            if ran.returncode != 0 or not out.is_file():
                fail("量具没跑完：" + (ran.stderr or ran.stdout)[-900:])
            facts = json.loads(out.read_text(encoding="utf-8"))
            summary, rows = facts.get("summary"), facts.get("rows") or []
            assert summary, "检查器里没有「混音台」"
            assert "2 条声音轨" in summary["text"], summary["text"]
            assert facts.get("detailsOpen") is True, "混音台点不开"

            # ① 两行、名字对、M/S/滑杆/百分数都在同一行（一行不叠小字）。
            assert len(rows) == 2, len(rows)
            assert [row["name"] for row in rows] == ["解说", "配乐"], [row["name"] for row in rows]
            for row in rows:
                assert [pill["text"] for pill in row["pills"]] == ["M", "S"], row["pills"]
                pressed = [pill["pressed"] for pill in row["pills"]]
                assert pressed == ["false", "false"], row["pills"]
                assert row["fader"] and row["fader"]["max"] == 400, row["fader"]
                assert abs(row["fader"]["value"] - 100) < 0.5, row["fader"]
                assert row["value"]["text"] == "100%", row["value"]
                centres = [
                    row["pills"][0]["box"], row["pills"][1]["box"],
                    row["fader"]["box"], row["value"]["box"],
                ]
                middles = [(box["top"] + box["bottom"]) / 2 for box in centres]
                assert max(middles) - min(middles) <= 3, (row["name"], middles)
                assert row["rowBox"]["height"] <= 40, row["rowBox"]
            print(
                f"   混音台 {len(rows)} 行：{rows[0]['name']} / {rows[1]['name']}，"
                f"滑杆上限 {rows[0]['fader']['max']}%，一行高 {rows[0]['rowBox']['height']}px"
            )

            # ② 点第二行的 S：引擎里 b 独奏，预览清单里 a 不出声。
            after = facts.get("afterSolo")
            assert after, "点完 S 读不到工程"
            tracks = {track["id"]: track for track in after["tracks"]}
            assert tracks["b"]["solo"] is True and tracks["a"]["solo"] is False, tracks
            assert facts.get("soundEnabled") == {"ca": False, "cb": True}, facts.get("soundEnabled")
            pressed = [row["pills"][1]["pressed"] for row in facts["rowsAfterSolo"]]
            assert pressed == ["false", "true"], pressed
            print(f"   S 之后：b 独奏、预览清单 sound_enabled={facts['soundEnabled']}")

            # ③ 拖动只改本地；松手才写进工程（50%）。
            assert abs(tracks["a"]["volume"] - 1.0) < 1e-6, tracks["a"]
            before = facts.get("projectBeforeCommit")
            assert before, "松手前读不到工程"
            before_tracks = {track["id"]: track for track in before["tracks"]}
            assert abs(before_tracks["a"]["volume"] - 1.0) < 1e-6, before_tracks["a"]
            done = {track["id"]: track for track in facts["afterVolume"]["tracks"]}
            assert abs(done["a"]["volume"] - 0.5) < 1e-6, done["a"]
            print(
                f"   滑杆 100% → 50%：松手前仍是 {before_tracks['a']['volume']:.2f}，"
                f"松手后 {done['a']['volume']:.2f}"
            )

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            stop(engine)

    print(
        f"PASS: 混音台在真页面里画得出来（{APP_VERSION}）——"
        "两行同一行排布（M/S/滑杆/百分数中心差 ≤3px）、"
        "点 S 后引擎独奏而预览清单同时改口、滑杆拖动不提交而松手写成 50%"
    )


if __name__ == "__main__":
    main()
