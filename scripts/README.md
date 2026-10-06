# scripts/

打包/验收用的本地脚本，不属于引擎运行时。

## build_engine.py — 生成桌面外壳要用的自包含引擎

仓库根目录一行命令（重建 `desktop/resources/bin/` 并做实机验收）：

```bash
uv run python scripts/build_engine.py --verify
```

没有 uv 时：`.venv/Scripts/python.exe scripts/build_engine.py --verify`（Windows）。

做了什么：

1. `uv run --with pyinstaller --no-sync pyinstaller ...` 在临时工具环境里冻结引擎；
   `pyinstaller` 只存在于这个临时环境，不进 `pyproject.toml` / `uv.lock`。
   入口是 `scripts/engine_entry.py`（`agentcut.__main__` 用相对导入，不能直接当脚本冻结；
   它同时把 stdout/stderr 强制成 UTF-8，因为冻结后的引导器无视 `PYTHONIOENCODING`，
   否则含中文的路径会以 cp936 输出，Electron 侧 `toString("utf-8")` 会得到乱码）。
2. 落地 `desktop/resources/bin/agentcut/agentcut.exe`（`--onedir`，约 31 MB，含 `_internal/`），
   并复制 `ffmpeg.exe` / `ffprobe.exe`（来自 `desktop/node_modules/ffmpeg-static`、
   `ffprobe-static/bin/win32/x64`）。`--layout onefile` 改成单文件 `bin/agentcut.exe`。
3. `--verify` 按 `desktop/electron/main.ts` 的方式生成进程：读 stdout 的 JSON `ready` 行、
   计时冷启动、真实 `GET /health` 与带 Bearer 的 `GET /v1/info`，再补测 `tools` / `--help` /
   `mcp` 三种模式，最后杀掉进程并确认端口不再应答。`--measure N` 多跑 N 次取冷启动分布。

实测（本机，OneDir）：冷启动 ready 行 min 564 ms / median 574 ms / max 578 ms，main.ts 的预算是
15000 ms。OneFile 约 800-830 ms，但 `child.kill()` 只杀引导器父进程，引擎子进程会继续占着端口，
所以默认用 OneDir。

## 注意

- `desktop/package.json` 的 `extraResources` 现在是 `filter: ["**/*.exe"]`，只会拷走 exe 而丢掉
  OneDir 的 `_internal/`。要打包安装版，需要把它改成 `filter: ["**/*"]`（或用 `--layout onefile`）。
- `desktop/resources/bin/` 与 `build/` 已在 `.gitignore` 里；`npm run dist` 之前先跑一次本脚本。
- 上一次运行残留的引擎进程会锁住 exe 导致重建失败，脚本会先清掉 `desktop/resources/bin/` 下的
  进程再删目录（见日志里的 `cleanup: killed ...`）。

## build_icon.py — 从 SVG 重新生成应用图标

`desktop/build/icon.svg` 是图标的唯一母版；`icon.ico`（16/24/32/48/64/128 BMP + 256 PNG）和
`desktop/build/icons/` 里的 PNG 都是它的派生物。改了母版就跑：

```bash
uv run --with pillow python scripts/build_icon.py
```

Pillow 只活在这个临时工具环境里，不进 `pyproject.toml` / `uv.lock`。光栅化用 Chromium
（有 playwright 就走 API，否则退回 `chrome.exe --headless --screenshot`），每个尺寸都按目标像素
网格直接矢量出图，16px 不是缩放出来的。脚本最后会自己解析 ICONDIR、用 Pillow 再解一遍每个
entry 并与源 PNG 逐像素比对、打印 16/24/32px 的字符画，验证不通过就非零退出。
`desktop/package.json` 的 `build.win.icon` 已经指向 `build/icon.ico`，无需改配置。

