"""Composition root: configuration, launch, and the machine-readable ready handshake.

`desktop` mode is what the packaged app runs: it prints one JSON line on stdout once the
loopback API is actually serving, so the Electron shell never has to guess a port.
"""

import argparse
import json
import os
import secrets
import shutil
import socket
import sys
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
        for bundle in (Path(sys._MEIPASS), _app_dir(), _app_dir() / "resources"):
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
    media = MediaService(db_file, roots, cache_dir, ffmpeg, ffprobe)
    jobs = JobRuntime(
        db_file,
        ffmpeg,
        output_dir,
        [output_dir, data_dir / "outputs", *roots],
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


def main():
    parser = argparse.ArgumentParser(
        prog="agentcut", description="AgentCut 本地剪辑引擎（HTTP + MCP + 媒体引擎）"
    )
    parser.add_argument(
        "mode", choices=["api", "mcp", "desktop", "tools"], nargs="?", default="api"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=str(_app_dir() / "data"))
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--media-root", action="append", default=[])
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--ffprobe", default="")
    parser.add_argument("--expose-token", action="store_true")
    parser.add_argument("--json", action="store_true", help="print a machine-readable ready line")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    if args.port == 0:
        args.port = free_port()
    if not args.token_file:
        args.token_file = str(data_dir / "agentcut.token")
    args.token_file = Path(args.token_file)
    token = load_token(args.token_file, required=args.mode == "mcp")

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

    db_file = database_path(data_dir)
    media, jobs, info = build_services(args, data_dir, token, db_file)
    app = create_app(db_file, token, media, jobs, info)
    if args.json or args.mode == "desktop":
        ready = {
            "event": "ready",
            "port": args.port,
            "base_url": f"http://127.0.0.1:{args.port}",
            "token_file": str(args.token_file),
            "media_ready": media.enabled,
            "media_roots": media.describe_roots(),
            "render_ready": bool(jobs.ffmpeg),
            "output_roots": jobs.describe_output_roots(),
            "data_dir": str(data_dir),
            "output_dir": str(jobs.output_dir),
            "ffmpeg": str(jobs.ffmpeg or ""),
        }
        print(json.dumps(ready, ensure_ascii=False), flush=True)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        print(json.dumps({"event": "stopped", "port": args.port}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
