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

    written = _write_dirs(args, data_dir)
    cache_dir = written["缓存"]
    output_dir = written["交付"]
    roots = [Path(item) for item in args.media_root] or [data_dir / "media"]
    for item in args.watch_dir:
        # 盯进来的目录本身就是媒体根：不这么做，watcher 收的每一手都会被
        # 「file is outside the allowed media roots」挡在门外——那才是真正难查的那种配置错。
        watched = Path(str(item).strip())
        if watched.is_dir() and watched.resolve() not in [root.resolve() for root in roots]:
            roots.append(watched)
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_binary("ffmpeg", args.ffmpeg)
    ffprobe = _find_binary("ffprobe", args.ffprobe)
    from .asr import model_dirs

    media = MediaService(
        db_file, roots, cache_dir, ffmpeg, ffprobe, asr_dirs=model_dirs([data_dir / "asr"])
    )
    instance = secrets.token_hex(6)
    jobs = JobRuntime(
        db_file,
        ffmpeg,
        output_dir,
        [output_dir, data_dir / "outputs", *roots],
        slots=args.render_slots,
        max_pending=args.max_queue,
        pending_per_actor=args.queue_per_token,
        min_free_mb=args.min_free_mb,
        callback_urls=list(args.callback_url),
        callback_secret=token,
        callback_instance=instance,
        callback_attempts=args.callback_attempts,
        callback_timeout=args.callback_timeout,
    )
    # 这一份 base_url 会被写进流地址那类对外读数里，所以它必须跟着加密走：
    # 一台用 TLS 服务的引擎不能交回 `http://` 的链接让人去撞明文。
    base_url = f"{'https' if args.tls_cert else 'http'}://127.0.0.1:{args.port}"
    info = {
        "instance": instance,
        "app_version": APP_VERSION,
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "cache_dir": str(cache_dir),
        "base_url": base_url,
        "token_file": str(args.token_file),
        "token": token if args.expose_token else None,
        "signature_hint": signature(token, "stream:example"),
        "frozen": bool(getattr(sys, "frozen", False)),
        "callback_urls": list(args.callback_url),
        "watch_dirs": [str(item).strip() for item in args.watch_dir if str(item).strip()],
    }
    return media, jobs, info


def _callback_problems(urls: list[str]) -> list[str]:
    """出站地址只认不带账号的 http/https。

    带 `user:pass@` 的那一种要挡：这一串会原样进台账、进 `/v1/callbacks` 的读数、也进运维的
    截图，等于把一枚口令发到别人看得见的地方。`file:`/`ftp:` 之类更要挡——回执是引擎主动
    发起的出站， scheme 放开就是让配置项变成读本地文件的口子。
    """
    from urllib.parse import urlsplit

    bad: list[str] = []
    for raw in urls or []:
        text = str(raw).strip()
        if not text:
            continue
        parts = urlsplit(text)
        if parts.scheme not in ("http", "https") or not parts.netloc or "@" in parts.netloc:
            bad.append(text)
    return bad


def _write_dirs(args, data_dir: Path) -> dict[str, Path]:
    """这台引擎**自己会往里写**的目录。门与 `build_services` 都读这里，不许各算各的。"""
    return {
        "交付": Path(args.output_dir) if args.output_dir else data_dir / "outputs",
        "缓存": Path(args.cache_dir) if args.cache_dir else data_dir / "media-cache",
    }


def _covers(ancestor: Path, target: Path) -> bool:
    """盯的那个目录是不是就是它、或者是它的父目录——watch 是递归扫的，父目录一样看得见。"""
    try:
        top, inner = ancestor.resolve(), target.resolve()
    except OSError:
        return False
    return top == inner or top in inner.parents


def _watch_problems(dirs: list[str], written: dict[str, Path]) -> list[str]:
    """盯的地方要真的在、真的是目录、**罩不住引擎自己写出东西的地方**，而且这台真的有 ffmpeg。

    「配了 watch 却没有媒体程序」必须停下，而不是静默什么都不收：那种配置的现场表现是素材一直
    躺在目录里没人管、流水线的另一端在等回执——最难查的缺件都是这种「谁都没报错」的。

    「盯的目录把输出/缓存目录盖住了」同样必须停：watch 是递归扫的，交付件（mp4/mov）与代理
    （也是 mp4）都落在 `ALLOWED_SUFFIXES` 里，于是引擎会把自己刚写出来的东西当新素材再收一遍——
    代理再生成代理，越滚越大，直到撞上输出盘底线。1.324 实测过这一手（watch 目录＝输出目录，
    一刀配方跑完，交付件当场被记成 imported）。这里判「包含」而不是只判「相等」：父目录一样罩住。
    """
    problems: list[str] = []
    cleaned = [str(item).strip() for item in (dirs or []) if str(item).strip()]
    for text in cleaned:
        path = Path(text)
        if not path.is_absolute():
            problems.append(f"{text} 不是绝对路径（引擎按路径记账，相对路径会跟着启动目录一起漂）")
        elif not path.is_dir():
            problems.append(f"{text} 不存在或不是一个目录")
        else:
            for label, target in written.items():
                if _covers(path, target):
                    problems.append(
                        f"{text} 罩住了这台自己写{label}的地方 {target}：{label}件会被当成新素材"
                        "再收一遍（代理还会越滚越大），把写出目录挪到这棵树外面再盯"
                    )
    if cleaned and _find_binary("ffmpeg", "") is None:
        problems.append("这一台找不到 ffmpeg：探测与缓存都是它做的，没有它盯到的文件一个也收不进")
    return problems


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
    # `supervise` 排在解析器之前：它后面跟的是**引擎自己的**参数（`api --port … --watch-dir …`），
    # 拿这台解析器去认只会认出一半。看门人只做一件事：把那些参数原样交给子进程并负责把它拉起。
    if len(sys.argv) > 1 and sys.argv[1] == "supervise":
        from .supervise import main as supervise_main

        raise SystemExit(supervise_main(sys.argv[2:]))
    from .notify import DEFAULT_ATTEMPTS, DEFAULT_TIMEOUT_SECONDS
    from .watch import DEFAULT_GRACE_SECONDS, DEFAULT_INTERVAL_SECONDS

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
    parser.add_argument(
        "--tls-cert",
        default="",
        help="用 TLS 服务这一台：证书（PEM）。给了它就必须同时给 --tls-key",
    )
    parser.add_argument(
        "--tls-key", default="", help="用 TLS 服务这一台：证书对应的私钥（PEM）"
    )
    parser.add_argument(
        "--allow-insecure-remote",
        action="store_true",
        help="明知故犯：绑定到非本机地址时不加密就服务（写操作在整个网段里是明文）",
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
    parser.add_argument(
        "--callback-url",
        action="append",
        default=[],
        help="作业走到终态时，引擎往这里 POST 一份带签名的回执（可重复给多个）；"
        "回执头 X-AgentCut-Signature 是 sha256=<整条 HMAC-SHA256>，密钥就是这台引擎的令牌",
    )
    parser.add_argument(
        "--callback-attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help="一份回执最多投几次，用完还不成就记成 gave_up（读数在 /v1/callbacks 与 metrics）",
    )
    parser.add_argument(
        "--watch-dir",
        action="append",
        default=[],
        help="盯这个目录收素材：新落地且写完的文件按引擎自己那条导入路径收下（可重复给多个）；"
        "这一台会把它当作一个媒体根",
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="多久扫一轮目录（秒）",
    )
    parser.add_argument(
        "--watch-grace",
        type=float,
        default=DEFAULT_GRACE_SECONDS,
        help="文件落地后再静默多久才收（秒）——半拷的文件就在这一步被挡下来",
    )
    parser.add_argument(
        "--callback-timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="单次投递等多久算失败（秒）。投送在后台线程里跑，不占渲染槽",
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

        if holder.get("tls"):
            raise SystemExit(
                f"数据目录 {data_dir} 被一台**用 TLS 服务**的引擎服着（PID {holder['pid']}，"
                f"端口 {holder.get('port')}）。外壳附到它身上这一手还没做：外壳与引擎在同一台"
                "机器上，用 --host 127.0.0.1 不加密地起就够了；要给别的机器用，"
                "走 HTTP/MCP 那扇门。"
            )
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
        # 这一模式**只是桥**：它不读 --data-dir / --media-root，也不会自己起引擎。先把要转发到
        # 哪里说清（stderr，不污染 stdio 的协议流）——不然指错地址时，agent 只会看到对面那一台
        # 引擎的 401，根本不知道自己在跟谁说话（1.327 实测就撞在 8765 上别人的引擎上）。
        print(
            f"agentcut mcp：工具调用转发到 {url}（引擎要另外起；用 AGENTCUT_API_URL 指过去）",
            file=sys.stderr,
            flush=True,
        )
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
    from .watch import Watcher

    loopback = args.host in ("127.0.0.1", "localhost")
    # TLS 的规矩：要么给一对，要么一对都不给——只给一半是配错了，不是选了不加密。
    if bool(args.tls_cert) != bool(args.tls_key):
        raise SystemExit(
            "--tls-cert 与 --tls-key 得一起给：只给一半的 TLS 配置是最容易在半夜发现的那种"
        )
    tls = bool(args.tls_cert)
    if tls:
        for cert_path, name in ((args.tls_cert, "--tls-cert"), (args.tls_key, "--tls-key")):
            if not Path(cert_path).is_file():
                raise SystemExit(f"{name} 指的东西不存在：{cert_path}")
    # 几道门一起判，不许一道把另一道演没了：1.322 只报「得加密」那一句，于是 1.318 那句
    # 「没令牌不许上网」在同一个场景里再也没被说过——serving_check 就是抓红这一手的。
    naked = not loopback and not tls and not args.allow_insecure_remote
    anonymous = not loopback and not os.environ.get("AGENTCUT_TOKEN", "").strip()
    callback_bad = _callback_problems(args.callback_url)
    watch_bad = _watch_problems(args.watch_dir, _write_dirs(args, data_dir))
    if naked or anonymous or callback_bad or watch_bad:
        doors = []
        if callback_bad:
            doors.append("--callback-url 只认不带账号的 http/https，这几条不是："
                         + "、".join(callback_bad))
        if watch_bad:
            doors.append("--watch-dir 指的地方不能用：" + "；".join(watch_bad))
        if naked:
            doors.append(f"要绑到 {args.host} 就得加密——给一对 --tls-cert/--tls-key，"
                         "或者干脆只听本机（反向代理终止 TLS 之后，这一台还是听 127.0.0.1，"
                         "那条路照旧通）。明知故犯要裸跑明文就加 --allow-insecure-remote："
                         "写接口在网段里就是明文")
        if anonymous:
            doors.append("身份——显式交一枚 AGENTCUT_TOKEN：自动生成的那一只只配听本机，"
                         "别把没设防的写接口放到网上")
        raise SystemExit(f"这台引擎过不去：{'；'.join(doors)}")
    db_file = database_path(data_dir)
    # 明知故犯那一手不写也不删租约：它既然选择共享，就不该把原来那台的名字从租约上抹掉——
    # 否则第三台看「没有租约」就堂而皇之进来，而那两台的活儿其实一直在互相改写。
    #
    # 这一手必须排在 `build_services()` **之前**：构造 JobRuntime 就会跑 `_recover()`，
    # 而 `_recover()` 是改写状态的——把 running 判成 INTERRUPTED、删掉那一单的收据，
    # 1.323 起还要为每一条终态欠一次出站回调。过去它只在库里留下痕迹（第二台被拒之后
    # 那些改动照旧留着），现在它会往外发通知：一台本来不该起来的引擎，会替一台正在渲的
    # 机器宣布「这一单中断了」。顺序就是这个意思：先确认这数据目录归我，再动它的活。
    record = (
        lease.acquire(port=args.port, mode=args.mode, tls=tls)
        if not args.allow_shared_data_dir
        else {"pid": os.getpid()}
    )
    if not args.allow_shared_data_dir:
        atexit.register(lease.release)
    media, jobs, info = build_services(args, data_dir, token, db_file)
    watcher = Watcher(
        db_file,
        media,
        [str(item).strip() for item in args.watch_dir if str(item).strip()],
        interval_seconds=args.watch_interval,
        grace_seconds=args.watch_grace,
    )
    tokens = TokenTable(data_dir / "tokens.json")
    audit = None if args.no_audit else AuditLog(data_dir / "audit.jsonl")
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
        watcher=watcher,
    )
    if args.json or args.mode == "desktop":
        ready = {
            "event": "ready",
            "port": args.port,
            "base_url": f"{'https' if tls else 'http'}://{args.host}:{args.port}",
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
            "callbacks": jobs.outbox.summary(),
            "watch": watcher.summary(),
            "tls": tls,
            "pid": record["pid"],
            "lease": str(lease.path),
        }
        print(json.dumps(ready, ensure_ascii=False), flush=True)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        **({"ssl_certfile": args.tls_cert, "ssl_keyfile": args.tls_key} if tls else {}),
    )
    server = uvicorn.Server(config)
    # 投送线程在服务起来之后开：起来了才算这台真的在服这份数据目录。没配地址时 start()
    # 自己会跳过，不留一个空转的线程。
    jobs.outbox.start()
    watcher.start()
    try:
        server.run()
    finally:
        # 先停投送与扫描线程再说「停了」：一台已经宣布自己停了的引擎，不该随后又递出一条回执、
        # 或者把目录里刚落地一半的文件收进账里。
        # 欠着没投出去的那些仍在 `job_outbox` 里，下一台起来的引擎会接着补。
        jobs.outbox.stop()
        watcher.stop()
        print(json.dumps({"event": "stopped", "port": args.port}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
