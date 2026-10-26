"""1.311 的装机腿：`recipe_run` 这一刀要在**随包那台引擎**上真跑一次。

源码腿（`recipe_run_check.py`）证明规则对；这一档证明交付出去的二进制里真的有那扇门：
起的是 `desktop/resources/bin/agentcut/agentcut.exe`——就是打进 `AgentCut.exe` 的那一份，
不是 `src/` 下的 Python。三道拒绝也一并走它，因为「契约说能跑」与「这台机器上的 exe 能跑」
是两件事，历史上红过的那几次都是后者。

四道：
① 现场读随包引擎的 `/v1/agent/manifest`：`recipe_run` 的端点就是那条路由，配方的 runnable
   与 why_not 带着 1.311 的形状；
② 真一刀：4 秒源（前 2 秒有声、后 2 秒静）→ 一次 run（render + wait）→ 13 行步骤、
   作业 succeeded、交付文件在盘上、ffprobe 量到的长度对得上计划；
③ 两条拒绝随包同源：不存在的配方 404，开不通的配方 422 带原因；
④ 关掉不留尸：按 PID 收整棵子树，之后那一个 PID 不再活着。
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

ENGINE = ROOT / "desktop/resources/bin/agentcut/agentcut.exe"
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "packagedreciprun" + "f" * 48
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:320]}")


def ask(method: str, base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    with httpx.Client(timeout=180.0, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        reply = client.request(method, base + path, json=payload)
    try:
        body = reply.json()
    except ValueError:
        body = {"raw": reply.text[:200]}
    return reply.status_code, body if isinstance(body, dict) else {"value": body}


def start_engine(folder: Path) -> tuple[subprocess.Popen, str]:
    command = [
        str(ENGINE), "api", "--port", "0", "--json",
        "--data-dir", str(folder), "--cache-dir", str(folder / "cache"),
        "--output-dir", str(folder / "out"), "--media-root", str(folder),
        "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
    ]
    env = dict(os.environ)
    env["AGENTCUT_TOKEN"] = TOKEN
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("ELECTRON_RUN_AS_NODE", None)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, cwd=str(ROOT), creationflags=0x08000000,
    )
    deadline = time.time() + 150
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line and process.poll() is not None:
            raise SystemExit(f"随包引擎没起来（退出码 {process.returncode}）")
        if '"event": "ready"' in line:
            return process, str(json.loads(line.strip())["base_url"])
    process.kill()
    raise SystemExit("随包引擎 150 秒内没有报 ready")


def build_source(folder: Path) -> Path:
    target = folder / "packaged.mp4"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=4",
            "-f", "lavfi", "-i", "sine=frequency=440:r=48000:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
            "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
            "-shortest", str(target),
        ],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )
    return target


def probe_seconds(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=180,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def manifest_leg(base: str) -> None:
    status, contract = ask("GET", base, "/v1/agent/manifest")
    check("随包引擎答了 manifest", status == 200, status)
    rows = {row["name"]: row for row in contract.get("tools") or []}
    entry = (rows.get("recipe_run") or {}).get("endpoint")
    check("随包那一份登记了这扇门",
          entry == {"method": "POST", "path": "/v1/agent/recipes/{recipe_id}/run"}, entry)
    recipes = {row["id"]: row for row in contract.get("recipes") or []}
    check("随包那一份也带着 runnable 的形状",
          recipes.get("cut-from-media", {}).get("runnable") is True
          and any(not row.get("runnable") and row.get("why_not") for row in recipes.values()),
          {key: (row.get("runnable"), bool(row.get("why_not"))) for key, row in recipes.items()})
    features = ((contract.get("capabilities") or {}).get("features") or {})
    check("能力位随包同源", features.get("recipe_run") is True, sorted(features)[:8])


def one_cut_leg(base: str, folder: Path) -> None:
    source = build_source(folder)
    payload = {
        "request_id": "pkg-rr-one",
        "name": "随包一刀",
        "files": [str(source)],
        "threshold_db": -40.0,
        "min_silence_ms": 500,
        "keep_ms": 600,
        "preset_id": "h264-720p-web",
        "filename": "packaged-cut.mp4",
        "render": True,
        "wait_seconds": 100.0,
    }
    status, made = ask("POST", base, "/v1/agent/recipes/cut-from-media/run", payload)
    check("随包引擎一次调用跑完整条配方", status == 200, made)
    if status != 200:
        return
    steps = made.get("steps") or []
    check("步骤就是 13 行", len(steps) == 13, [row.get("step") for row in steps])
    job = made.get("job") or {}
    check("随包那一刀交付成功", job.get("status") == "succeeded", job)
    out = Path(job.get("output_path") or "")
    if out.is_file():
        seconds = probe_seconds(out)
        planned = float(((made.get("plan") or {}).get("plan") or {}).get("duration_seconds") or 0)
        check("交付长度对得上计划", abs(planned - seconds) <= 0.25, (planned, seconds))
        check("剪到了源以内", 0.2 <= seconds < 4.0, seconds)
        print(f"   随包一刀：源 4.00 s → 交付 {seconds:.2f} s（计划 {planned:.2f} s），"
              f"revision {made.get('revision')}，等了 {made.get('waited_ms')} ms")
    else:
        check("交付文件在盘上", False, str(out))


def refusal_leg(base: str, payload: dict) -> None:
    status, body = ask("POST", base, "/v1/agent/recipes/no-such/run", payload)
    check("随包那一份也按 NOT_FOUND 拒未知配方",
          status == 404 and (body.get("error") or {}).get("code") == "NOT_FOUND", (status, body))
    status, body = ask("POST", base, "/v1/agent/recipes/speech-to-captions/run", payload)
    check("随包那一份也带原因拒开不通的配方",
          status == 422 and (body.get("error") or {}).get("code") == "RECIPE_NOT_RUNNABLE"
          and "字幕" in str((body.get("error") or {}).get("message")), (status, body))


def main() -> None:
    if not (ENGINE.is_file() and FFMPEG.is_file() and FFPROBE.is_file()):
        raise SystemExit(
            f"NOT RUN: {ENGINE} 是可再生的构建产物；先执行 "
            "scripts/build_engine.py --verify --no-uv 再跑本检查"
        )
    cleanup = runpy.run_path(str(ROOT / "scripts/build_engine.py"))["kill_tree"]
    with tempfile.TemporaryDirectory(prefix="agentcut-pkgrecip-") as folder:
        directory = Path(folder)
        process, base = start_engine(directory)
        try:
            manifest_leg(base)
            one_cut_leg(base, directory)
            refusal_leg(base, {
                "request_id": "pkg-rr-refuse", "name": "拒绝的形状",
                "files": [str(directory / "packaged.mp4")],
                "preset_id": "h264-720p-web", "filename": "nope.mp4",
            })
        finally:
            pid = process.pid
            cleanup(pid, ENGINE, directory)
            time.sleep(1.0)
            alive = process.poll() is None
            check("随包引擎关掉之后不留尸", not alive, pid)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: recipe_run 在随包引擎上真跑得通——manifest、一刀交付、两条拒绝、不留进程")


if __name__ == "__main__":
    main()
