"""1.326 占用这一档：装机包里都有什么、外壳每个进程占多少、空闲会不会自己涨、窗口多久出来。

为什么单列一档：1.315 量过「合计 332 / 用过 422 / 引擎 81 MB」并钉了额度，但那一档的口径是
**一个总数**——它看不出 97 MB 的 GPU 进程、也看不出 55 个语言包里 53 个永远用不上。这一档把
「组成」和「分数」都量出来，并且只挡增长、不当目标值：

① 装机包（win-unpacked）不许超过 535 MB；语言包只许两个（zh-CN / en-US）且 ≤ 1.5 MB；
② 包里不许有 source map、不许出现两份一样的大文件（>1 MB）——这两种都是「白装一遍」；
③ 外壳空闲时：主进程 ≤ 110 MB、渲染进程 ≤ 115 MB、GPU ≤ 120 MB、工具进程 ≤ 70 MB、合计 ≤ 400 MB；
④ 空闲 8 秒与 25 秒两次读数相差 ≤ 15 MB（泄漏先在这里红，而不是等用户投诉）；
⑤ 冷启动到渲染进程出现 ≤ 3 秒。

量法：真起 `win-unpacked/AgentCut.exe`（一份临时 profile），用 CIM 按命令行分角色读 WorkingSetSize。
这个 agent shell 导出了 `ELECTRON_RUN_AS_NODE=1`，不清掉它 exe 只当解释器跑一下就退——量到的会是
「0 个进程」，这一手在 1.315 的装机腿上栽过一次。

跑法：空闲机器单跑 `uv run python tests/footprint_check.py`（要 win-unpacked；先按 README 重建）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNPACKED = ROOT / "desktop" / "release" / "win-unpacked"
EXE = UNPACKED / "AgentCut.exe"
FAILURES: list[str] = []
# 1.326 实测 523.9 MB（语言包 55→2、cryptography 不再进包之后）。
# 535 留 ~2% 抖动，但 55 个语言包回来（+39 MB）这种退化一定过不去。
LIMIT_TOTAL_MB = 535.0
LIMIT_LOCALES_MB = 1.5
LIMIT = {"main": 110.0, "renderer": 115.0, "gpu": 120.0, "utility": 70.0}
LIMIT_SHELL_MB = 400.0
LIMIT_DRIFT_MB = 15.0
LIMIT_COLD_START_S = 3.0


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def census() -> list[dict]:
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='AgentCut.exe'\" | "
        "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.WorkingSetSize, $_.CommandLine }"
    )
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    rows = []
    for line in (done.stdout or "").splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        pid, wss, cmd = int(parts[0]), int(parts[1] or 0), parts[2]
        kind = "main"
        for token, label in (("--type=renderer", "renderer"), ("--type=gpu-process", "gpu"),
                             ("--type=utility", "utility"), ("--type=crashpad", "crashpad")):
            if token in cmd:
                kind = label
        if "desktop --port" in cmd or " api --port" in cmd:
            kind = "engine"
        rows.append({"pid": pid, "kind": kind, "mb": round(wss / 1048576, 1)})
    return rows


def total_mb(rows: list[dict], kind: str | None = None) -> float:
    return round(sum(row["mb"] for row in rows if kind is None or row["kind"] == kind), 1)


def composition() -> None:
    total = size(UNPACKED) / 1048576
    check(f"① 装机包（win-unpacked）不超过 {LIMIT_TOTAL_MB:.0f} MB", total <= LIMIT_TOTAL_MB,
          f"{total:.1f} MB")
    paks = sorted(UNPACKED.glob("locales/*.pak"))
    names = sorted(pak.name for pak in paks)
    locals_mb = sum(size(pak) for pak in paks) / 1048576
    check("① 语言包只剩中文与英文", names == ["en-US.pak", "zh-CN.pak"], names)
    check(f"① 语言包总大小不超过 {LIMIT_LOCALES_MB} MB", locals_mb <= LIMIT_LOCALES_MB,
          f"{locals_mb:.1f} MB")
    maps = sorted(UNPACKED.rglob("*.map"))
    check("② 包里没有 source map", maps == [], [str(p.name) for p in maps[:4]])
    # 按**内容**判重，不按文件名：改个名字的同一份文件同样是白占地方（第一版只看
    # (name, size)，一把「复制成另一个名字」的刀就漏过去了——这条规矩是那把刀逼出来的）。
    seen: dict[str, list[str]] = {}
    for item in UNPACKED.rglob("*"):
        if not item.is_file() or size(item) <= 1048576:
            continue
        hasher = hashlib.sha256()
        try:
            with item.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    hasher.update(block)
        except OSError:
            continue
        seen.setdefault(hasher.hexdigest(), []).append(str(item))
    dupes = {key: paths for key, paths in seen.items() if len(paths) > 1}
    check("② 包里没有两份一样的大文件（按内容判，不按文件名）", not dupes,
          {key[:12]: [Path(path).name for path in paths[:3]]
           for key, paths in list(dupes.items())[:3]})
    print(f"   装机包 {total:.1f} MB；语言包 {len(paks)} 个 / {locals_mb:.1f} MB；"
          f"source map {len(maps)} 个；重复大文件 {len(dupes)} 组")


def memory_and_start() -> None:
    # 套件那一趟跑的就是这一版（profile 放仓库根）；落在仓库根的那个目录已在 .gitignore 里。
    profile = ROOT / ".footprint-profile"
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    started = time.time()
    proc = subprocess.Popen([str(EXE), f"--user-data-dir={profile}"], cwd=str(EXE.parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        cold = 0.0
        deadline = time.time() + 60
        while time.time() < deadline:
            if any(row["kind"] == "renderer" for row in census()):
                cold = round(time.time() - started, 2)
                break
            time.sleep(0.2)
        check(f"⑤ 冷启动到渲染进程出现不超过 {LIMIT_COLD_START_S:.0f} 秒",
                0 < cold <= LIMIT_COLD_START_S,
              cold)
        first: list[dict] = []
        second: list[dict] = []
        for index, wait in enumerate((8.0, 17.0)):
            time.sleep(wait if index == 0 else wait - 8.0)
            rows = census()
            if index == 0:
                first = rows
            else:
                second = rows
            print(f"   {8 if index == 0 else 25}s 读数：合计 {total_mb(rows)} MB · "
                  + " · ".join(f"{kind} {total_mb(rows, kind)}" for kind in
                               ("main", "renderer", "gpu", "utility")))
        for kind, ceiling in LIMIT.items():
            got = total_mb(second, kind)
            check(f"③ 外壳 {kind} 空闲不超过 {ceiling:.0f} MB", 0 < got <= ceiling, got)
        shell = total_mb(second)
        check(f"③ 外壳空闲合计不超过 {LIMIT_SHELL_MB:.0f} MB", 0 < shell <= LIMIT_SHELL_MB, shell)
        drift = round(abs(total_mb(second) - total_mb(first)), 1)
        check(f"④ 空闲 8 秒到 25 秒不涨过 {LIMIT_DRIFT_MB:.0f} MB",
              total_mb(first) > 0 and drift <= LIMIT_DRIFT_MB,
              (total_mb(first), total_mb(second)))
        engines = [row for row in second if row["kind"] == "engine"]
        check("④ 还没真用的时候外壳不拉引擎", engines == [], engines)
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=90)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    if not EXE.is_file():
        raise SystemExit(f"FAIL: {EXE} 不在——先按 README 的重建链产一份")
    composition()
    memory_and_start()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 装机包组成（语言包两个、无 source map、无重复大文件）与外壳内存（每进程额度 + "
          "空闲不涨）都量在额度内，冷启动到渲染进程也在 3 秒以内")


if __name__ == "__main__":
    main()
