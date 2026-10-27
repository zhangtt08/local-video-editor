"""1.320 的第一面：一台数据目录只该有一台引擎在服务。

`--port 0` 让每台引擎自己挑端口，所以两台引擎不会撞在端口上——它们撞的是同一份
`agentcut.sqlite3`、同一本 `audit.jsonl` 与同一枚令牌。1.319 记下了后果（一台的渲染线程把另一台
标成 INTERRUPTED 的行改回 succeeded，收据被错的那本删掉），这一档把「谁在服这份数据目录」写成一
行 JSON 的租约，并让第二台**在动任何东西之前**就停下来说清楚。

七道，每道都要能红：

① 正向腿：一台引擎照常起来、`/health` 真答、ready 行交回 `pid` 与 `lease`，租约里写着
   `pid / port / mode / started_at`——加了守卫不许把引擎本身弄死；
② 同一份数据目录上的第二台**被拒**：退出码非零，那句点名第一台的 PID 与两条出路，而且它连令牌
   文件都没碰（内容一字未变）；
③ 第一台被按 PID 停掉之后，第三台在同一份数据目录上照常起来并把**自己的** PID 写进租约——
   陈旧的租约不挡路，否则一次崩溃就把这台机器锁死；
④ 明知故犯那条路是真的：带 `--allow-shared-data-dir` 的第二台起得来、答得出 `/health`；
⑤ `release()` 只放自己那一份：没取过的什么都不做，别人写在同一个位置上的名字不许被抹掉；
⑥ `pid_alive` 的两面：自己的 PID 说在，一个不可能在的 PID 说不在；同一 PID 的租约不算「别人」，
   PID 已经不在的那份也不算占用（否则一次崩溃就把这台机器锁死）；
⑦ 不服务的路不取租约：`agentcut tokens` 那一面不会留下 `engine.lock`；
⑧ 双击第二个窗口不该变成「引擎起不来」：`desktop` 模式遇到在服的引擎就**附上去**——报的是那一台
   的端口、说得清附到了谁身上（`attached_to_pid`）、那个地址真答 `/health`，而且它不把自己的名字
   写到租约上（否则第三台看「没有租约」就进来了）。

写这档门禁时自己也红过一手：那条腿把「附上去没附上去」的证据写成了 `shell.stderr.read()`——
一个还活着的进程的 stderr 永远读不完，整套门禁就挂在那里不动。证据要取自已经关掉的东西。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import reaper
import scratch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.serving import LEASE_NAME, Lease, pid_alive  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def spawn(data_dir: Path, *extra: str) -> subprocess.Popen:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return reaper.note(subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
         "--data-dir", str(data_dir), "--media-root", str(data_dir), *extra],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env,
    ))


def wait_ready(proc: subprocess.Popen, seconds: float = 40.0) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return {}
        line = proc.stdout.readline() if proc.stdout else ""
        if line and '"event": "ready"' in line:
            return json.loads(line)
    return {}


def health(base_url: str) -> object:
    try:
        with urllib.request.urlopen(base_url + "/health", timeout=6) as got:
            return got.status
    except Exception as error:  # noqa: BLE001
        return type(error).__name__


def stop(proc: subprocess.Popen) -> None:
    """按 PID 连子树收掉——留在树上的那支 FFmpeg 会替我们把「停了」演成「还在跑」。"""
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=30)
    try:
        proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=25)


def lease_of(data_dir: Path) -> dict:
    path = data_dir / LEASE_NAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def serving_legs(folder: Path) -> None:
    """①②③④：一台服务、第二台被拒、第一台停了第三台接得上、明知故犯不碰别人的名字。

    比对一律对着 ready 行里那台引擎自己报的 PID：venv 的 `python.exe` 是个拉起的壳，
    `Popen.pid` 与真正在服务的那个进程是两个数——拿壳的 PID 去比，租约就永远「不对」。
    """
    data = folder / "engine"
    data.mkdir(parents=True, exist_ok=True)
    first = spawn(data)
    ready = wait_ready(first)
    serving_pid = ready.get("pid")
    check("第一台照常起来并交回 ready 行", bool(ready), ready)
    check("ready 行说得出租约在哪",
          Path(str(ready.get("lease"))).resolve() == (data / LEASE_NAME).resolve(),
          {k: ready.get(k) for k in ("pid", "lease")})
    check("/health 真答（守卫不许把引擎本身弄死）", health(ready.get("base_url", "")) == 200,
          health(ready.get("base_url", "")))
    record = lease_of(data)
    check("租约写的就是这台在服的引擎，而且那个 PID 是活的",
          record.get("pid") == serving_pid and record.get("port") == ready.get("port")
          and record.get("mode") == "api" and pid_alive(int(record.get("pid") or 0)),
          record)

    token_path = data / "agentcut.token"
    token_before = token_path.read_text(encoding="utf-8") if token_path.is_file() else ""
    second = spawn(data)
    code = second.wait(timeout=40)
    out = (second.stdout.read() or "") + (second.stderr.read() or "")
    check("第二台在同一份数据目录上被拒", code != 0, (code, out[-200:]))
    check("那句点名第一台的 PID 与两条出路",
          str(serving_pid) in out and "--data-dir" in out and "--allow-shared-data-dir" in out,
          out[-320:])
    token_after = token_path.read_text(encoding="utf-8") if token_path.is_file() else ""
    check("被拒那一台连令牌都没碰", token_before == token_after and bool(token_before),
          (len(token_before), len(token_after)))
    check("被拒那一台没把租约抢走", lease_of(data).get("pid") == serving_pid, lease_of(data))

    third = spawn(data, "--allow-shared-data-dir")
    third_ready = wait_ready(third)
    check("明知故犯那条路是真的（带旗标就起得来、答得出 /health）",
          third_ready.get("port") and health(third_ready.get("base_url", "")) == 200,
          third_ready)
    check("明知故犯那一台不碰租约（别人的名字不许被抹掉）",
          lease_of(data) == record, (lease_of(data), record))
    stop(third)
    check("那一台退出之后租约还是原来那台的", lease_of(data).get("pid") == serving_pid,
          lease_of(data))
    stop(first)
    check("第一台按 PID 停掉了", first.poll() is not None, first.poll())

    again = spawn(data)
    again_ready = wait_ready(again)
    check("第一台停了之后第三台接得上（陈旧租约不挡路）", bool(again_ready), again_ready)
    check("接上的那台把自己的 PID 写进了租约",
          lease_of(data).get("pid") == again_ready.get("pid")
          and lease_of(data).get("pid") != serving_pid, lease_of(data))
    stop(again)


def release_leg(folder: Path) -> None:
    """⑤ `release()` 只放自己那一份：没取过的什么都不做，别人写的名字不许被抹掉。"""
    path = folder / "release.lock"
    quiet = Lease(path)
    quiet.release()
    check("没取过的租约，release 什么都不做", not path.exists(), path.exists())

    mine = Lease(path)
    record = mine.acquire(port=1234, mode="api")
    written = json.loads(path.read_text(encoding="utf-8"))
    check("acquire 当场把名字写上",
          written.get("port") == 1234 and written.get("pid") == record["pid"]
          and written.get("mode") == "api", written)
    check("自己正在服的租约不算「别人在服」", mine.holder() is None, mine.holder())
    mine.release()
    check("正常收工把自己那份拿走", not path.exists(), path.exists())

    Lease(path).acquire(port=4321, mode="api")
    stranger = Lease(path)
    stranger.taken = True
    stranger.owner_pid = os.getpid() + 1_000_000
    stranger.release()
    check("不是自己取的租约不许被删掉", path.is_file(), lease_of(folder))
    Lease(path).release()
def alive_leg(folder: Path) -> None:
    """⑥ `pid_alive` 的两面，以及「同一 PID 的租约不算别人」。"""
    check("自己的 PID 说在", pid_alive(os.getpid()) is True, os.getpid())
    check("一个不可能在的 PID 说不在", pid_alive(2_000_000) is False, 2_000_000)
    check("0 与负数不当成活的", pid_alive(0) is False and pid_alive(-1) is False, "0/-1")
    path = folder / "mine.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "port": 1, "mode": "api",
                                "started_at": "now"}), encoding="utf-8")
    check("同一 PID 的租约不算「别人在服」", Lease(path).holder() is None, Lease(path).holder())
    other = folder / "theirs.lock"
    other.write_text(json.dumps({"pid": 2_000_000, "port": 1, "mode": "api",
                                 "started_at": "now"}), encoding="utf-8")
    check("PID 不在了的租约不算占用", Lease(other).holder() is None, Lease(other).holder())
    live = folder / "live.lock"
    sitter = reaper.note(subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        live.write_text(json.dumps({"pid": sitter.pid, "port": 7, "mode": "api",
                                    "started_at": "now"}), encoding="utf-8")
        holder = Lease(live).holder()
        check("别人正在服的租约要认出来并交回是谁",
              bool(holder) and holder.get("pid") == sitter.pid and holder.get("port") == 7,
              holder)
    finally:
        # terminate() 只打得着 venv 那个壳，真在睡的解释器是它的子进程——按 PID 连子树收。
        stop(sitter)
    check("那位走了租约就不算占用", Lease(live).holder() is None, Lease(live).holder())


def quiet_modes_leg(folder: Path) -> None:
    """⑦ 不服务的路不许留下租约。"""
    data = folder / "tokens-mode"
    data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    listed = subprocess.run(
        [sys.executable, "-m", "agentcut", "tokens", "--data-dir", str(data)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=env,
    )
    check("`tokens` 那一面照常答复", listed.returncode == 0, (listed.returncode,
                                                              (listed.stderr or "")[-200:]))
    check("`tokens` 不取租约", not (data / LEASE_NAME).is_file(), lease_of(data))


def attach_leg(folder: Path) -> None:
    """⑧ 双击第二个窗口不该变成「引擎起不来」：桌面模式遇到在服的引擎就附上去。

    附上去报的那个地址必须是**那一台**的：端口、`attached_to_pid` 与 `/health` 三处都对得上。
    """
    data = folder / "attach"
    data.mkdir(parents=True, exist_ok=True)
    first = spawn(data)
    ready = wait_ready(first)
    serving_pid = ready.get("pid")
    check("先起来的那台在服", health(ready.get("base_url", "")) == 200, ready)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    shell = reaper.note(subprocess.Popen(
        [sys.executable, "-m", "agentcut", "desktop", "--port", "0",
         "--data-dir", str(data), "--media-root", str(data)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env,
    ))
    attached = {}
    deadline = time.time() + 40.0
    while time.time() < deadline and not attached:
        if shell.poll() is not None:
            break
        line = shell.stdout.readline() if shell.stdout else ""
        if line and '"event": "ready"' in line:
            attached = json.loads(line)
    check("第二台没被拒，而是附了上去", bool(attached) and shell.poll() is None,
          (attached, shell.poll()))
    check("报的地址就是那一台在服的端口", attached.get("port") == ready.get("port"),
          {k: attached.get(k) for k in ("port", "base_url", "attached_to_pid")})
    check("说得清附到了谁身上", attached.get("attached_to_pid") == serving_pid, attached)
    check("附上去那个地址真答 /health", health(attached.get("base_url", "")) == 200,
          attached.get("base_url"))
    check("附上去的那台自己不取租约（名字还是原来那台的）",
          lease_of(data).get("pid") == serving_pid, lease_of(data))
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(shell.pid)], capture_output=True,
                   timeout=30)
    shell.wait(timeout=25)
    stop(first)


def main() -> None:
    folder = scratch.make("agentcut-lease-")
    try:
        serving_legs(folder)
        release_leg(folder)
        alive_leg(folder)
        attach_leg(folder)
        quiet_modes_leg(folder)
    finally:
        # 先数活口再收：漏了停法要红在自己那一行，兜底收活口只是不让这台机器被攒进程。
        strays = reaper.survivors()
        strays_after = reaper.sweep(stop)
    check("每一腿自己收掉了拉起的引擎（漏一个就是在替这台机器攒进程）",
          not strays and not strays_after, (strays, strays_after))
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 一台数据目录只服一台引擎，第二台在动任何东西之前停下并说清是谁在服、怎么走")


if __name__ == "__main__":
    main()
