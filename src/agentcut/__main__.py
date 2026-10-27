"""Composition root: configuration, launch, and the machine-readable ready handshake.

`desktop` mode is what the packaged app runs: it prints one JSON line on stdout once the
loopback API is actually serving, so the Electron shell never has to guess a port.
"""

import argparse
import atexit
import json
import os
import secrets
import shutil
import socket
import sys
import threading
import time
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(os.getcwd()).resolve()


def _find_binary(name: str, override: str) -> Path | None:
    for candidate in (override, os.environ.get(f"AGENTCUT_{name.upper()}", "")):
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    if getattr(sys, "frozen", False):
        # 打包后的目录形状是 `resources/bin/agentcut/agentcut.exe` 与 `resources/bin/ffmpeg.exe`：
        # 随包的媒体工具在**上一级**。少这一条，冻结引擎就会一路落到 PATH 上用户自己那份 ffmpeg，
        # 而那条路是版本赌博——本轮实测这台机器的 PATH 上是 9.0.2，它已经没有
        # `-filter_complex_script` 这一项（6.1.1 有），于是「滤镜图超过 12000 字符的交付」
        # 在打包版里直接拒，短图却照常出片。`_app_dir().parent` 就是那一层；
        # `_internal` 是 PyInstaller onedir 放数据文件的另一处。
        for bundle in (
            Path(sys._MEIPASS),
            _app_dir(),
            _app_dir().parent,
            _app_dir() / "resources",
        ):
            for hit in (bundle / f"{name}.exe", bundle / name / f"{name}.exe"):
                if hit.is_file():
                    return hit.resolve()
    found = shutil.which(name)
    return Path(found).resolve() if found else None


def database_path(data_dir: Path) -> Path:
    """AGENTCUT_DB still wins, so a documented external database path keeps working."""
    override = os.environ.get("AGENTCUT_DB", "")
    return Path(override).resolve() if override else data_dir / "agentcut.sqlite3"


def free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def load_token(token_file: Path, required: bool) -> str:
    from_env = os.environ.get("AGENTCUT_TOKEN", "")
    if len(from_env) >= 32:
        return from_env
    if token_file.is_file():
        stored = token_file.read_text(encoding="utf-8").strip()
        if len(stored) >= 32:
            return stored
    if required:
        raise SystemExit(
            f"no token: set AGENTCUT_TOKEN or create {token_file} with 32+ random characters"
        )
    token = secrets.token_hex(32)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    return token


def build_services(args, data_dir: Path, token: str, db_file: Path):
    from .contracts import APP_VERSION
    from .http_api import signature
    from .jobs import JobRuntime
    from .media import MediaService

    cache_dir = Path(args.cache_dir) if args.cache_dir else data_dir / "media-cache"
    output_dir = Path(args.output_dir) if args.output_dir else data_dir / "outputs"
    roots = [Path(item) for item in args.media_root] or [data_dir / "media"]
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_binary("ffmpeg", args.ffmpeg)
    ffprobe = _find_binary("ffprobe", args.ffprobe)
    from .asr import model_dirs

    media = MediaService(
        db_file, roots, cache_dir, ffmpeg, ffprobe, asr_dirs=model_dirs([data_dir / "asr"])
    )
    jobs = JobRuntime(
        db_file,
        ffmpeg,
        output_dir,
        [output_dir, data_dir / "outputs", *roots],
        slots=args.render_slots,
        max_pending=args.max_queue,
        pending_per_actor=args.queue_per_token,
        min_free_mb=args.min_free_mb,
    )
    base_url = f"http://127.0.0.1:{args.port}"
    info = {
        "instance": secrets.token_hex(6),
        "app_version": APP_VERSION,
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "cache_dir": str(cache_dir),
        "base_url": base_url,
        "token_file": str(args.token_file),
        "token": token if args.expose_token else None,
        "signature_hint": signature(token, "stream:example"),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    return media, jobs, info


def parent_watchdog(pid: int, interval: float = 2.0) -> None:
    """父进程不在了，引擎自己走。

    Windows 上 `TerminateProcess` 不给子进程任何收尾机会，靠父进程的 atexit 或
    `taskkill /T` 都不牢靠：桥被强杀之后引擎会一直挂在机器上（实测一次门禁留下 24 台）。
    所以「跟谁一起死」这件事由引擎自己盯——每两秒问一次那个 PID 还在不在。
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        still_active = 259
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            os._exit(0)
        code = wintypes.DWORD()
        while True:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                break
            if code.value != still_active:
                break
            time.sleep(interval)
    else:
        while True:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(interval)
    os._exit(0)


def held_message(data_dir: Path, holder: dict) -> str:
    return (
        f"数据目录 {data_dir} 已经被另一台 AgentCut 引擎服着（PID {holder.get('pid')}，"
        f"端口 {holder.get('port')}，模式 {holder.get('mode')}，起于 "
        f"{holder.get('started_at')}）。两台引擎共用一份工程、一本台账与一枚令牌会互相改写"
        "状态：先关掉那一台，或给这一台换一个 --data-dir；明知故犯就加 --allow-shared-data-dir"
    )


def holder_info(holder: dict, token_file: Path) -> dict | None:
    """问一句那台在服的引擎「你是谁、你服成什么样」。

    附上去的每个读数都必须来自它自己，不是这里抄一份——不然外壳看到的是这台壳以为的样子。
    """
    import urllib.request

    token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
    url = f"http://127.0.0.1:{holder.get('port')}/v1/info"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=8) as got:
            payload = json.loads(got.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def main():
    parser = argparse.ArgumentParser(
        prog="agentcut", description="AgentCut 本地剪辑引擎（HTTP + MCP + 媒体引擎）"
    )
    parser.add_argument(
        "mode", choices=["api", "mcp", "desktop", "tools", "tokens"], nargs="?", default="api"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="绑定地址。默认只听本机；要交给别的机器上的 agent 用，才显式改这里",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="允许哪个网页来源调这台引擎（可重复）；不给就只放行桌面端与本机",
    )
    parser.add_argument("--add-label", default="", help="发一枚具名令牌，例：studio-a")
    parser.add_argument(
        "--scopes", default="write", help="配 --add-label：read / write / both（默认 write）"
    )
    parser.add_argument("--revoke-label", default="", help="吊销一枚具名令牌，立刻生效")
    parser.add_argument("--no-audit", action="store_true", help="不写 audit.jsonl 台账")
    parser.add_argument(
        "--render-slots",
        type=int,
        default=0,
        help="同时开几支 FFmpeg 渲交付（1-8）。0 是按用法定：`api` 两槽（16 核实测四单交付 "
        "25.14 s → 19.77 s，1.27 倍），`desktop` 一槽——坐在机器前的人不该被交付抢走 CPU",
    )
    parser.add_argument(
        "--max-queue",
        type=int,
        default=64,
        help="待渲队列最多压几单，超了按名字拒（QUEUE_FULL）",
    )
    parser.add_argument(
        "--queue-per-token",
        type=int,
        default=16,
        help="一只具名令牌名下最多压几单，超了按名字拒（QUOTA_EXCEEDED）",
    )
    parser.add_argument(
        "--allow-shared-data-dir",
        action="store_true",
        help="明知故犯：让两台引擎共用同一份工程、台账与令牌（状态会互相改写，1.319 量到过）",
    )
    parser.add_argument(
        "--min-free-mb",
        type=int,
        default=2048,
        help="输出盘至少留多少 MB 才肯再排新交付（盘满时拒在排队前，不是渲到一半才失败）",
    )
    parser.add_argument("--data-dir", default=str(_app_dir() / "data"))
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--media-root", action="append", default=[])
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--ffprobe", default="")
    parser.add_argument("--expose-token", action="store_true")
    parser.add_argument("--json", action="store_true", help="print a machine-readable ready line")
    parser.add_argument(
        "--exit-with-parent",
        type=int,
        default=0,
        help="父进程 PID：它不在了引擎自己退出（无人值守的 agent 用完不该留一台引擎）",
    )
    args = parser.parse_args()

    # 槽数按用法定，不是按「机器能开多少」定：桌面端一槽是为了编辑时的手感；服务化两槽是量出来的
    # 1.27 倍（四单 20 秒噪点竖屏交付，1 / 2 / 3 槽 = 25.14 / 19.77 / 18.88 秒——第三槽只再多 5%，
    # 因为一支 FFmpeg 自己就用满核）。
    if args.render_slots == 0:
        args.render_slots = 2 if args.mode == "api" else 1

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    from .serving import LEASE_NAME, Lease

    # 一台数据目录只服一台引擎。`--port 0` 让每台自己挑端口，所以两台不会撞在端口上——它们撞的是
    # 同一份工程、一本台账与同一枚令牌，而那正是 1.319 量到的那种状态翻脸。检查放在读令牌之前：
    # 第二台连令牌都不该去碰。
    lease = Lease(data_dir / LEASE_NAME)
    holder = lease.holder() if args.mode in ("api", "desktop") else None
    if holder and not args.allow_shared_data_dir and args.mode == "api":
        raise SystemExit(held_message(data_dir, holder))
    if args.port == 0:
        args.port = free_port()
    if not args.token_file:
        args.token_file = str(data_dir / "agentcut.token")
    args.token_file = Path(args.token_file)
    if holder and not args.allow_shared_data_dir and args.mode == "desktop":
        # 双击第二个窗口不该变成「引擎起不来」：租约在谁手上就照着那一台报地址，读数全部
        # 从它自己嘴里取。版本对不上时必须停下——新界面配旧引擎会凑成一件谁也没测过的软件。
        from .contracts import APP_VERSION

        attached = holder_info(holder, args.token_file)
        if attached is None:
            raise SystemExit(held_message(data_dir, holder))
        if attached.get("app_version") != APP_VERSION:
            raise SystemExit(
                f"数据目录 {data_dir} 被另一台**不同版本**的引擎服着（它报 "
                f"{attached.get('app_version')}，这一份是 {APP_VERSION}）——先关掉那一台，"
                "或给这一台换一个 --data-dir"
            )
        print(
            json.dumps(
                {
                    "event": "ready",
                    "port": int(holder["port"]),
                    "base_url": attached.get("base_url")
                    or f"http://127.0.0.1:{holder['port']}",
                    "token_file": str(args.token_file),
                    "media_ready": attached.get("media_ready"),
                    "media_roots": attached.get("media_roots") or [],
                    "render_ready": attached.get("render_ready"),
                    "output_roots": attached.get("output_roots") or [],
                    "data_dir": str(data_dir),
                    "output_dir": attached.get("output_dir") or "",
                    "ffmpeg": attached.get("ffmpeg") or "",
                    "bind": "127.0.0.1",
                    "remote": False,
                    "attached_to_pid": int(holder["pid"]),
                    "lease": str(lease.path),
                    "pid": os.getpid(),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.exit_with_parent > 0:
            threading.Thread(
                target=parent_watchdog, args=(args.exit_with_parent,), daemon=True
            ).start()
        while True:
            time.sleep(3600)
    if args.mode == "tokens":
        from .serving import TokenTable

        table = TokenTable(data_dir / "tokens.json")
        if args.add_label:
            scopes = {"read": ["read"], "write": ["write"], "both": ["read", "write"]}.get(
                args.scopes
            )
            if scopes is None:
                raise SystemExit(f"--scopes 只认 read / write / both，给的是 {args.scopes}")
            row, secret = table.add(args.add_label, scopes)
            print(
                json.dumps(
                    {"issued": row["label"], "scopes": row["scopes"], "token": secret},
                    ensure_ascii=False,
                )
            )
            return
        if args.revoke_label:
            ok = table.revoke(args.revoke_label)
            print(
                json.dumps(
                    {"revoked": args.revoke_label if ok else None, "tokens": table.summary()},
                    ensure_ascii=False,
                )
            )
            if not ok:
                raise SystemExit(f"没有叫 {args.revoke_label} 的活令牌")
            return
        print(json.dumps({"tokens": table.summary()}, ensure_ascii=False))
        return
    token = load_token(args.token_file, required=args.mode == "mcp")
    if args.exit_with_parent > 0:
        threading.Thread(
            target=parent_watchdog, args=(args.exit_with_parent,), daemon=True
        ).start()

    if args.mode == "mcp":
        from .mcp_server import create_mcp

        url = os.environ.get("AGENTCUT_API_URL", f"http://127.0.0.1:{args.port}")
        create_mcp(url, token).run(transport="stdio")
        return

    if args.mode == "tools":
        print(
            json.dumps(
                {
                    "ffmpeg": str(_find_binary("ffmpeg", args.ffmpeg) or ""),
                    "ffprobe": str(_find_binary("ffprobe", args.ffprobe) or ""),
                    "data_dir": str(data_dir),
                },
                ensure_ascii=False,
            )
        )
        return

    import uvicorn

    from .http_api import create_app
    from .serving import AuditLog, TokenTable

    loopback = args.host in ("127.0.0.1", "localhost")
    if not loopback and not os.environ.get("AGENTCUT_TOKEN", "").strip():
        raise SystemExit(
            f"要绑到 {args.host} 就得自己交一枚令牌（AGENTCUT_TOKEN）——自动生成的那一只"
            "只配听本机，别把没设防的写接口放到网上"
        )
    db_file = database_path(data_dir)
    media, jobs, info = build_services(args, data_dir, token, db_file)
    tokens = TokenTable(data_dir / "tokens.json")
    audit = None if args.no_audit else AuditLog(data_dir / "audit.jsonl")
    # 明知故犯那一手不写也不删租约：它既然选择共享，就不该把原来那台的名字从租约上抹掉——
    # 否则第三台看「没有租约」就堂而皇之进来，而那两台的活儿其实一直在互相改写。
    record = (
        lease.acquire(port=args.port, mode=args.mode)
        if not args.allow_shared_data_dir
        else {"pid": os.getpid()}
    )
    if not args.allow_shared_data_dir:
        atexit.register(lease.release)
    app = create_app(
        db_file,
        token,
        media,
        jobs,
        info,
        tokens=tokens,
        audit=audit,
        bind_host=args.host,
        allow_origins=args.allow_origin or None,
    )
    if args.json or args.mode == "desktop":
        ready = {
            "event": "ready",
            "port": args.port,
            "base_url": f"http://{args.host}:{args.port}",
            "token_file": str(args.token_file),
            "media_ready": media.enabled,
            "media_roots": media.describe_roots(),
            "render_ready": bool(jobs.ffmpeg),
            "output_roots": jobs.describe_output_roots(),
            "data_dir": str(data_dir),
            "output_dir": str(jobs.output_dir),
            "ffmpeg": str(jobs.ffmpeg or ""),
            "bind": args.host,
            "remote": not loopback,
            "tokens": [row["label"] for row in tokens.summary() if not row["revoked_at"]],
            "audit": None if audit is None else str(audit.path),
            "slots": jobs.slots,
            "max_queue": jobs.max_pending,
            "queue_per_token": jobs.pending_per_actor,
            "requeued": len(jobs.requeued),
            "min_free_mb": args.min_free_mb,
            "pid": record["pid"],
            "lease": str(lease.path),
        }
        print(json.dumps(ready, ensure_ascii=False), flush=True)
    config = uvicorn.Config(
        app, host=args.host, port=args.port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        print(json.dumps({"event": "stopped", "port": args.port}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
