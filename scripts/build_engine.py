#!/usr/bin/env python3
"""Rebuild the self-contained Windows engine bundle that the Electron shell spawns.

One-line usage from the repository root (either works):

    uv run python scripts/build_engine.py --verify
    .venv/Scripts/python.exe scripts/build_engine.py --verify

What it does, from scratch, every run:

1. Runs PyInstaller in an ephemeral tool environment (`uv run --with pyinstaller --no-sync`).
   The project's locked dependency set stays untouched: pyinstaller is never added to
   pyproject.toml or uv.lock.
2. Stages the result in `desktop/resources/bin/` exactly where `desktop/electron/main.ts` looks:
   `bin/agentcut/agentcut.exe` (onedir, default) or `bin/agentcut.exe` (`--layout onefile`),
   plus `bin/ffmpeg.exe` and `bin/ffprobe.exe` copied out of `desktop/node_modules`.
3. With `--verify`, spawns the staged exe the same way main.ts does, times the JSON "ready" line,
   calls GET /health for real, and confirms the port stops answering after the process is killed.

Stdlib only, so it runs before any Python environment is set up beyond the project venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# The repository path carries non-ASCII on this machine, and a cp936 console raises
# UnicodeEncodeError while printing it — which would kill the documented
# `uv run python scripts/build_engine.py --verify` gate over a progress line.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
BUILD_DIR = ROOT / "build" / "engine"
DEST = ROOT / "desktop" / "resources" / "bin"
ENGINE_NAME = "agentcut"

IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def step(message: str) -> None:
    print(f"[build] {message}", flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"[build] ERROR: {message}")


def find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / f"uv{EXE}",
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / f"uv{EXE}",
    ):
        if candidate.is_file():
            return str(candidate)
    return ""


# --------------------------------------------------------------------------- engine build
def build_engine(layout: str, use_uv: bool) -> Path:
    """Run PyInstaller and return the directory that holds `agentcut(.exe)`."""
    work = BUILD_DIR / "work"
    dist = BUILD_DIR / "dist"
    for target in (work, dist):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    argv = [
        "--noconfirm",
        "--clean",
        "--console",
        "--log-level=WARN",
        f"--{layout}",
        "--name",
        ENGINE_NAME,
        "--paths",
        str(ROOT / "src"),
        # vosk's own __init__ runs os.add_dll_directory on its package folder; without the folder
        # (and the dll it expects beside it) the frozen import raises FileNotFoundError and every
        # capability query would 500. Collect the whole package so it looks like a normal install.
        "--collect-all",
        "vosk",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(BUILD_DIR),
        str(SCRIPTS / "engine_entry.py"),
    ]
    uv = find_uv() if use_uv else ""
    if uv:
        # Ephemeral tool env layered on the project venv: the frozen app analyses the *project*
        # dependencies while pyinstaller itself stays out of pyproject.toml / uv.lock.
        command = [
            uv,
            "run",
            "--with",
            "pyinstaller",
            "--no-sync",
            "pyinstaller",
            *argv,
        ]
    elif shutil.which("pyinstaller"):
        command = [shutil.which("pyinstaller"), *argv]
    else:
        fail(
            "neither `uv` nor a `pyinstaller` on PATH was found; install uv "
            "(https://docs.astral.sh/uv/) or `pip install pyinstaller` in a tool venv"
        )
    step("running: " + " ".join(command))
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=ROOT, shell=False)
    if proc.returncode != 0:
        fail(f"PyInstaller exited with code {proc.returncode}")
    step(f"PyInstaller finished in {time.perf_counter() - started:.1f}s")

    bundle = dist / ENGINE_NAME
    exe = bundle / f"{ENGINE_NAME}.exe" if layout == "onedir" else dist / f"{ENGINE_NAME}.exe"
    if not exe.is_file():
        fail(f"expected engine executable at {exe} after build, not found")
    return exe if layout == "onefile" else bundle


# --------------------------------------------------------------------------- media binaries
def find_source(kind: str) -> Path:
    """Stage the media binaries the project pins; there is deliberately no fallback to this machine.

    这里原来在 `desktop/node_modules` 找不到就往下退：`C:/ffmpeg/bin`、`Program Files`、最后 PATH。
    退路的代价本轮量到了：清掉 `node_modules` 之后重建，`--verify` 照常绿，而装机的包里那支 FFmpeg
    换成了本机 winget 的 9.0.2 full build（218 MB，静态包那一支是 6.1.1，82 MB）——文档里 zscale
    的折叠、矩阵拼法与色度标记的每一个数都是随包 6.1.1 量的。发布包不能取决于装机器碰巧有什么，
    所以这里只剩两条路：用静态包，或者点名拒绝。确实要换一支（比如专门验 9.x 的行为差异），
    用 `AGENTCUT_FFMPEG` / `AGENTCUT_FFPROBE` 把路径明确交进来，戳里会记下它来自哪里。
    """
    modules = ROOT / "desktop" / "node_modules"
    candidates = [
        modules / "ffmpeg-static" / f"{kind}.exe",
        modules / "ffprobe-static" / "bin" / "win32" / "x64" / "ffprobe.exe",
        modules / "ffprobe-static" / "bin" / "win32" / "ia32" / "ffprobe.exe",
    ]
    override = os.environ.get(f"AGENTCUT_{kind.upper()}_BIN", "").strip()
    if override:
        chosen = Path(override)
        if chosen.name == f"{kind}.exe" and chosen.is_file():
            step(f"staged {kind}.exe from the explicit AGENTCUT_{kind.upper()}_BIN override")
            return chosen.resolve()
        fail(
            f"AGENTCUT_{kind.upper()}_BIN 指向的不是可执行的 {kind}.exe：{override}"
            "——要换一支就给它正确的路径，别让它悄悄退回去"
        )
    for candidate in candidates:
        # never hand back the wrong binary just because the folder was searched in order
        if candidate.name == f"{kind}.exe" and candidate.is_file():
            return candidate.resolve()
    if not IS_WINDOWS:
        # 开发机上没有 .exe 这一说，跟着 PATH 走是原来的行为，Windows 交付路径不受影响。
        which = shutil.which(kind)
        if which:
            return Path(which).resolve()
    fail(
        f"没有可随包的 {kind}.exe：先 `npm --prefix desktop ci`（ffmpeg-static / ffprobe-static）。"
        "本脚本不再从 C:/ffmpeg、Program Files 或 PATH 找退路——装机的那支必须是验收量过的那支；"
        f"确实要换一支，用 AGENTCUT_{kind.upper()}_BIN 明确交进来。"
    )
    return Path()  # unreachable, keeps mypy/ruff happy


def binary_version(path: Path) -> str:
    """Run the staged binary once: a copy that cannot execute is not an artifact."""
    try:
        proc = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=(0x08000000 if IS_WINDOWS else 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"UNEXECUTABLE ({type(error).__name__})"
    first = (proc.stdout or proc.stderr).splitlines()
    return first[0][:100] if first else f"no output (exit {proc.returncode})"


def stage_media(sources: dict[str, Path]) -> list[Path]:
    """Copy the pinned media binaries in, then write down exactly what they are.

    那张 `media-stamp.json` 是「装机的那支就是验收量的那支」这句话的可判版本：
    `tests/mediabinary_check.py` 拿它去对随包那两支的字节与版本行。谁手工换过 exe 却没重跑构建，
    或者换的那支不是静态包里的，当场红。
    拿它去对随包那两支的字节与版本行，谁手工换过 exe 而没重跑构建，当场红。
    """
    staged = []
    stamp: dict[str, dict[str, object]] = {}
    for kind in ("ffmpeg", "ffprobe"):
        source = sources[kind]
        target = DEST / f"{kind}.exe"
        shutil.copy2(source, target)
        note = " [32-bit build]" if "ia32" in str(source) else ""
        step(f"staged {kind}.exe {human(target.stat().st_size)} <- {source}{note}")
        version = binary_version(target)
        step(f"        {kind}.exe -version -> {version}")
        try:
            shown = str(source.relative_to(ROOT)).replace(chr(92), "/")
        except ValueError:
            shown = str(source)
        stamp[kind] = {
            "version_line": version,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size,
            "source": shown,
        }
        staged.append(target)
    body = json.dumps(stamp, ensure_ascii=False, indent=2) + "\n"
    (DEST / "media-stamp.json").write_text(body, encoding="utf-8")
    step("wrote media-stamp.json (版本行 + sha256 + 字节数 + 来源，随那两支一起进包)")
    return staged


def stage_asr_models() -> None:
    """Copy any local speech model next to the staged engine so the frozen exe can find it.

    Models are data, not code: the repo keeps them in `desktop/resources/asr/` (never committed).
    A missing model is not an error — the engine reports `speech_captions` as unavailable and says
    so, rather than shipping a half-copied model that pretends to recognise speech.
    """
    source_root = ROOT / "desktop" / "resources" / "asr"
    if not source_root.is_dir():
        step("no speech models staged (desktop/resources/asr is absent)")
        return
    staged_any = False
    for model in sorted(source_root.iterdir()):
        if not (model / "am").is_dir() or not (model / "graph").is_dir():
            continue
        target = DEST / "agentcut" / "asr" / model.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(model, target)
        size = human(sum(f.stat().st_size for f in target.rglob("*") if f.is_file()))
        step(f"staged speech model {model.name} {size}")
        staged_any = True
    if not staged_any:
        step("desktop/resources/asr holds no complete model folders; nothing staged")


# --------------------------------------------------------------------------- staging
def stage_engine(exe_or_bundle: Path, layout: str) -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    if layout == "onefile":
        target = DEST / "agentcut.exe"
        shutil.copy2(exe_or_bundle, target)
        return target
    target = DEST / "agentcut"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(exe_or_bundle, target)
    return target / "agentcut.exe"


def report() -> None:
    step(f"artifacts under {DEST}")
    for item in sorted(DEST.iterdir()):
        label = item.name if item.is_file() else f"{item.name}/"
        if item.is_file():
            size = human(item.stat().st_size)
            detail = ""
        else:
            entries = list(item.rglob("*"))
            size = human(sum(f.stat().st_size for f in entries if f.is_file()))
            detail = f" ({len(entries)} entries)"
        print(f"        {label}  {size}{detail}")
    total = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    step(f"total staged size {human(total)}")


# --------------------------------------------------------------------------- verification
def port_is_dead(port: int) -> bool:
    """True once nothing serves the port. On this machine a dead port hangs instead of
    refusing, so a connect timeout is the expected proof of shutdown."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
    except OSError as error:
        step(f"port {port} is closed: {type(error).__name__}: {error}")
        return True
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            step(f"port {port} STILL ANSWERS: {response.read().decode()[:120]}")
    except urllib.error.HTTPError as error:
        step(f"port {port} STILL ANSWERS: HTTP {error.code}")
    except OSError as error:
        step(f"port {port} takes TCP but serves no HTTP: {type(error).__name__}")
        return True
    return False


def kill_tree(pid: int, exe: Path, engine_dir: Path) -> None:
    """Stop this verification tree, including an orphaned onefile child in its test directory."""
    if not IS_WINDOWS:
        return
    capture = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, **capture)
    executable = str(exe.resolve()).replace("'", "''")
    directory = re.escape(str(engine_dir))  # Match the actual argv, including Windows short paths.
    argument = (r'--data-dir\s+"?' + directory + r'"?(?:\s|$)').replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | Where-Object { "
        f"$_.ExecutablePath -eq '{executable}' -and $_.CommandLine -match '{argument}' "
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False, **capture)


def kill_staged_engines() -> None:
    """A leaked engine (crashed app, previous --onefile run) keeps the staged exe file locked and
    would block the rebuild, so clear only processes whose image lives under the staging dir."""
    if not IS_WINDOWS:
        return
    script = (
        'Get-Process | Where-Object { $_.Path -like "%s*" } | '
        "ForEach-Object { Stop-Process -Id $_.Id -Force; 'killed ' + $_.Id + ' ' + $_.Path }" % DEST
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            step(f"cleanup: {line.strip()}")


def read_ready_line(child: subprocess.Popen, stderr_path: Path, deadline: float) -> str:
    """stdout.readline() blocks, so a reader thread keeps the 15s budget honest.

    stderr goes to a file (not a pipe) because an unread pipe can deadlock the child once
    uvicorn starts complaining.
    """
    from queue import Empty, Queue

    lines: Queue = Queue()

    def pump() -> None:
        for line in child.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    while time.perf_counter() < deadline:
        try:
            line = lines.get(timeout=0.2)
        except Empty:
            if child.poll() is not None:
                break
            continue
        if line.strip().startswith("{"):
            return line
    child.kill()
    tail = ""
    if stderr_path.is_file():
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    fail(
        f"no JSON ready line within 15s (exit code {child.poll()}); "
        f"main.ts would time out here\n{tail}"
    )
    return ""


def get_json(url: str, token: str = "") -> dict:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
    step(f"GET {url} -> HTTP {response.status} {body[:600]}")
    return json.loads(body)


def spawn_engine(exe: Path, run_dir: Path, media_flags: list[str]) -> dict:
    """Start the staged engine exactly like startBackend() and collect the handshake + probes.

    Returns {latency_ms, ready, health, info, port, exit_code}.
    """
    engine_dir = run_dir / "engine"
    media_dir = run_dir / "media"
    engine_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    token_file = engine_dir / "agentcut.token"
    argv = [
        str(exe),
        "desktop",
        "--port",
        "0",
        "--data-dir",
        str(engine_dir),
        "--token-file",
        str(token_file),
        "--output-dir",
        str(run_dir / "outputs"),
        "--media-root",
        str(media_dir),
        "--json",
        *media_flags,
    ]
    started = time.perf_counter()
    stderr_path = run_dir / "engine-stderr.log"
    stderr_file = stderr_path.open("w", encoding="utf-8")
    child = subprocess.Popen(  # noqa: S603 - argv is built from staged, repo-local paths only
        argv,
        cwd=str(engine_dir),
        stdout=subprocess.PIPE,
        stderr=stderr_file,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(0x08000000 if IS_WINDOWS else 0),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    try:
        ready = json.loads(read_ready_line(child, stderr_path, started + 15))
        latency = (time.perf_counter() - started) * 1000
        port = int(ready["port"])
        health = get_json(f"http://127.0.0.1:{port}/health")
        token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
        # /v1/info needs the Bearer token: proves FastAPI + pydantic + sqlite survived freezing.
        info = get_json(f"http://127.0.0.1:{port}/v1/info", token=token)
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        step(f"engine process exited with code {child.returncode}")
        stderr_file.close()
    return {
        "latency_ms": latency,
        "port": port,
        "pid": child.pid,
        "exe": exe,
        "engine_dir": engine_dir,
        "ready": ready,
        "health": health,
        "info": info,
        "exit_code": child.returncode,
    }


def check_shutdown(run: dict, layout: str) -> None:
    """main.ts stops the engine with child.kill("SIGTERM"), which on Windows is TerminateProcess
    on the process it spawned. With --onedir that is the engine itself; with --onefile the
    bootloader re-execs a child and the server outlives the kill."""
    if port_is_dead(run["port"]):
        return
    if layout == "onefile":
        step(
            "KNOWN --onefile LEAK: the bootloader parent exited but the frozen child kept "
            f"serving port {run['port']}. Cleaning it up with taskkill /T."
        )
        kill_tree(run["pid"], run["exe"], run["engine_dir"])
        if not port_is_dead(run["port"]):
            fail("could not clear the orphaned --onefile engine process")
        return
    fail(f"--{layout} engine survived the kill on port {run['port']}")


def check_cli_variants(exe: Path, run_dir: Path, media_flags: list[str]) -> None:
    """The packaged exe has to answer the whole `python -m agentcut` surface, not just `desktop`."""
    engine_dir = run_dir / "engine"
    common = ["--data-dir", str(engine_dir), "--token-file", str(engine_dir / "agentcut.token")]

    proc = subprocess.run(
        [str(exe), "tools", *common, *media_flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(engine_dir),
        check=False,
    )
    payload = json.loads(proc.stdout)
    step(f"`tools` mode -> exit {proc.returncode} {json.dumps(payload, ensure_ascii=False)[:220]}")
    if proc.returncode or not {"ffmpeg", "ffprobe", "data_dir"} <= payload.keys():
        fail("`tools` mode is broken in the frozen build")
    if Path(payload["ffmpeg"]) != DEST / "ffmpeg.exe" or Path(payload["ffprobe"]) != (
        DEST / "ffprobe.exe"
    ):
        fail(f"`tools` mode did not honour the staged binaries: {payload}")

    proc = subprocess.run(
        [str(exe), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    step(f"`--help` -> exit {proc.returncode}, first line: {proc.stdout.splitlines()[0][:90]}")
    if proc.returncode:
        fail("--help failed in the frozen build")

    # `mcp` speaks stdio, so "still alive after 3s with an open stdin and no traceback" is the
    # observable contract. DEVNULL is not a valid test: an MCP client holds the pipe open.
    stderr_path = run_dir / "mcp-stderr.log"
    with stderr_path.open("w", encoding="utf-8") as sink:
        child = subprocess.Popen(
            [str(exe), "mcp", *common],
            stdout=subprocess.DEVNULL,
            stderr=sink,
            stdin=subprocess.PIPE,
            cwd=str(engine_dir),
            creationflags=(0x08000000 if IS_WINDOWS else 0),
        )
        time.sleep(3)
        alive = child.poll() is None
        if not alive:
            child.wait(timeout=5)
        if child.stdin:
            child.stdin.close()
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if not alive:
        fail(f"`mcp` mode exited with {child.returncode}: {stderr_text[-800:]}")
    if "Traceback" in stderr_text:
        fail(f"`mcp` mode logged a traceback: {stderr_text[-800:]}")
    step(f"`mcp` mode alive after 3s (pid {child.pid}); stderr tail: {stderr_text[-160:].strip()}")
    if IS_WINDOWS:
        kill_tree(child.pid, exe, engine_dir)
    else:
        child.kill()
    child.wait(timeout=10)


def verify(exe: Path, layout: str, runs: int = 1) -> None:
    from tempfile import gettempdir

    base = Path(gettempdir()) / "agentcut-engine-check"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)

    media_flags = ["--ffmpeg", str(DEST / "ffmpeg.exe"), "--ffprobe", str(DEST / "ffprobe.exe")]
    step(f"spawning {exe} desktop --port 0 ... {' '.join(media_flags)}")
    run = spawn_engine(exe, base / "with-media", media_flags)
    check_shutdown(run, layout)
    ready, health, info = run["ready"], run["health"], run["info"]
    step(f"cold-start to ready line: {run['latency_ms']:.0f} ms (main.ts budget 15000 ms)")
    step(f"ready line: {json.dumps(ready, ensure_ascii=False)}")

    if ready.get("event") != "ready" or not run["port"]:
        fail("ready line is not the handshake main.ts expects")
    # The repo path contains Chinese characters: had the exe emitted cp936 bytes, utf-8 decoding
    # would leave replacement characters exactly where that path is.
    for key in ("ffmpeg", "data_dir", "output_dir", "token_file"):
        value = str(ready.get(key, ""))
        if "\ufffd" in value:
            fail(f"ready field {key!r} is not utf-8 clean: {value!r}")
    if Path(ready.get("ffmpeg", "")) != DEST / "ffmpeg.exe":
        fail(f"--ffmpeg not honoured, engine reports {ready.get('ffmpeg')!r}")
    if health.get("status") != "ok":
        fail(f"/health did not report ok: {health}")
    if not (ready.get("media_ready") and ready.get("render_ready")):
        fail(f"staged ffmpeg/ffprobe not reported ready: {ready}")
    if not (health.get("media_ready") and health.get("render_ready")):
        fail(f"/health disagrees about media readiness: {health}")
    if not info.get("frozen"):
        fail(f"bundled engine reports frozen={info.get('frozen')!r}: not a self-contained exe")
    if not info.get("capabilities"):
        fail("bundled engine reports no capabilities")

    # Second pass: without the media flags the handshake must honestly report what it can find.
    # _find_binary() in a frozen build also looks next to the executable, so a --onefile exe that
    # sits in the same folder as ffmpeg/ffprobe legitimately still reports ready.
    step("spawning the same exe without --ffmpeg/--ffprobe to check honest flags")
    bare = spawn_engine(exe, base / "no-media", [])
    check_shutdown(bare, layout)
    from_path = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    from_side = (exe.parent / "ffmpeg.exe").is_file() and (exe.parent / "ffprobe.exe").is_file()
    expected = from_path or from_side
    step(
        f"bare ready line: media_ready={bare['ready'].get('media_ready')} "
        f"render_ready={bare['ready'].get('render_ready')} "
        f"(ffmpeg+ffprobe on PATH: {from_path}, beside the exe: {from_side})"
    )
    if bare["ready"].get("render_ready") is not expected:
        fail(f"render_ready is not truthful without explicit --ffmpeg: {bare['ready']}")
    step(f"bare cold-start {bare['latency_ms']:.0f} ms")

    check_cli_variants(exe, base / "with-media", media_flags)

    if runs > 1:
        samples = [run["latency_ms"], bare["latency_ms"]]
        for index in range(runs):
            again = spawn_engine(exe, base / f"repeat-{index}", media_flags)
            check_shutdown(again, layout)
            samples.append(again["latency_ms"])
            step(f"repeat {index + 1}/{runs}: {again['latency_ms']:.0f} ms")
        samples.sort()
        mid = samples[len(samples) // 2]
        step(
            f"cold-start over {len(samples)} launches: min {samples[0]:.0f} ms, "
            f"median {mid:.0f} ms, max {samples[-1]:.0f} ms"
        )
    step("verification passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild desktop/resources/bin from scratch.")
    parser.add_argument("--layout", choices=["onedir", "onefile"], default="onedir")
    parser.add_argument(
        "--skip-engine", action="store_true", help="only re-stage the media binaries"
    )
    parser.add_argument("--verify", action="store_true", help="spawn the staged exe and probe it")
    parser.add_argument(
        "--measure", type=int, default=1, metavar="N", help="extra cold-start samples for --verify"
    )
    parser.add_argument("--keep", action="store_true", help="keep previous staging contents")
    parser.add_argument("--no-uv", action="store_true", help="use a pyinstaller already on PATH")
    args = parser.parse_args()

    if not IS_WINDOWS:
        step("non-Windows host: produced bundle is only usable for smoke checks")

    # 先把那两支定下来，再动 DEST。1.158 就是这么丢过一次证据的：`npm ci --ignore-scripts`
    # 留下的 ffmpeg-static 是空的，而原本的顺序是先 rmtree(DEST) 再 stage_media()，于是清掉了
    # 装机用的 ffmpeg / ffprobe / media-stamp（三名都不在 git 里）才报「没有可随包的 ffmpeg.exe」。
    # 缺输入应当一步都不毁；真要换一支，用 AGENTCUT_FFMPEG_BIN / AGENTCUT_FFPROBE_BIN 交进来。
    sources = {kind: find_source(kind) for kind in ("ffmpeg", "ffprobe")}

    if DEST.exists() and not args.keep:
        kill_staged_engines()
        step(f"clearing {DEST}")
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)

    exe = None
    if not args.skip_engine:
        exe = build_engine(args.layout, use_uv=not args.no_uv)
        exe = stage_engine(exe, args.layout)
        step(f"staged engine executable {exe} ({human(exe.stat().st_size)})")

    stage_media(sources)
    stage_asr_models()
    report()
    if args.verify:
        if not exe:
            exe = (
                DEST / "agentcut" / "agentcut.exe"
                if args.layout == "onedir"
                else DEST / "agentcut.exe"
            )
        if not exe.is_file():
            fail(f"--verify asked for {exe} which is not staged")
        verify(exe, args.layout, runs=args.measure)


if __name__ == "__main__":
    main()
