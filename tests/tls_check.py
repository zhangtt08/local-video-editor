"""TLS 这一档：引擎可以自己用证书服务，且绑定离开本机就默认不许裸跑明文。

1.318 立的规矩是「非本机绑定必须有显式令牌」——那只挡住了没身份的那一路，传输本身仍是明文：
企业内网里 `--host 0.0.0.0` 一起，写操作在网段里就是可读的。这一档补上另外两条腿：

① 一对 `--tls-cert/--tls-key` 就给真加密服务（现造的自签证书，SAN 里写 127.0.0.1），
   ready 行交回 `tls: true`、`base_url` 是 `https://`；
② 拿那枚证书当 CA 真连一次：`/health` 与 `/v1/capabilities` 都 200；
   同一端口用明文 `http://` 打，**不许**拿到 200（否则「加密」只是嘴上说）；
③ 半配好的 TLS 要停下：只给证书不给私钥、或者给的路径不存在；
④ 绑到非本机地址时，没证书又没 `--allow-insecure-remote` 就停下，那句要点名 TLS；
   明知故犯了，1.318 那枚显式令牌的规矩照样在（两道守卫各自独立，别以为一个顶两个）；
⑤ 租约里记下加密与否；`desktop` 附到一台 TLS 引擎上要**说清这一手还没做**，
   而不是把它演成「数据目录被别人占着」；
⑥ 收摊之后那个端口不再答。

跑法：空闲机器单跑 `uv run python tests/tls_check.py`（要本机解释器与 `cryptography`）。
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import scratch  # noqa: E402

from agentcut.serving import LEASE_NAME  # noqa: E402

TOKEN = "tls-check-" + "t" * 40 + "-token"
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def make_cert(folder: Path) -> tuple[Path, Path]:
    """现造一张自签证书：SAN 里必须有 `127.0.0.1`，不然客户端验不过这一手就是空的。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agentcut-tls-check")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName(
            [x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    crt = folder / "server.crt"
    pem = folder / "server.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
    return crt, pem


def env_for(**extra: str) -> dict:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def spawn(folder: Path, *args: str, **env_add: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
         "--data-dir", str(folder / "engine"), "--media-root", str(folder), *args],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env_for(**env_add),
    )


def ready_line(proc: subprocess.Popen, seconds: float = 60.0) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return {}
        line = proc.stdout.readline() if proc.stdout else ""
        if line and '"event": "ready"' in line:
            return json.loads(line)
    return {}


def wait_exit(proc: subprocess.Popen, seconds: float = 40.0) -> tuple[int | None, str]:
    deadline = time.time() + seconds
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.2)
    code = proc.poll()
    out = ""
    if code is not None:
        out = (proc.stdout.read() or "") + (proc.stderr.read() or "")
    return code, out


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=60)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def serving_legs(folder: Path, crt: Path, key: Path) -> None:
    # 令牌走环境那一条路（57 个字符，过 `load_token` 的 32 字下限）：这一档要连的是带身份的门。
    proc = spawn(folder, "--tls-cert", str(crt), "--tls-key", str(key),
                 AGENTCUT_TOKEN=TOKEN)
    ready = ready_line(proc)
    check("给了证书就起得来，ready 行说得出 tls", ready.get("tls") is True, ready)
    check("base_url 得是 https://（交回 http:// 就是让人去撞明文）",
          str(ready.get("base_url", "")).startswith("https://"), ready.get("base_url"))
    base = str(ready.get("base_url", ""))
    port = int(ready.get("port") or 0)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(verify=str(crt), headers=headers, timeout=30.0) as api:
        health = api.get(base + "/health")
        caps = api.get(base + "/v1/capabilities")
        check("拿那张证书当 CA 真连一次：/health 200", health.status_code == 200,
              health.status_code)
        check("TLS 底下读得到能力表", caps.status_code == 200
              and bool((caps.json().get("app_version") or "")), caps.status_code)
        info = api.get(base + "/v1/info").json()
        payload = info.get("info") if isinstance(info.get("info"), dict) else info
        check("TLS 底下 /v1/info 交回的 base_url 也是 https",
              str(payload.get("base_url", "")).startswith("https://"), payload.get("base_url"))
    with httpx.Client(timeout=10.0) as plain:
        try:
            answer = plain.get(f"http://127.0.0.1:{port}/health")
            served = answer.status_code == 200
            error_text = answer.status_code
        except httpx.HTTPError as error:
            served = False
            error_text = type(error).__name__
    check("同一端口用明文打，不许答 200", not served, error_text)
    record = json.loads((folder / "engine" / LEASE_NAME).read_text(encoding="utf-8"))
    check("租约里记下这台是加密服务的", record.get("tls") is True, record)
    attach = subprocess.run(
        [sys.executable, "-m", "agentcut", "desktop", "--port", "0",
         "--data-dir", str(folder / "engine"), "--media-root", str(folder)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=env_for(),
    )
    joined = (attach.stdout or "") + (attach.stderr or "")
    check("外壳附到 TLS 那一台要说清还没做，不许演成「目录被占着」",
          attach.returncode != 0 and "还没做" in joined and "被另一台" not in joined,
          joined[-260:])
    stop(proc)
    deadline = time.time() + 30.0
    alive = True
    while time.time() < deadline:
        try:
            with httpx.Client(verify=str(crt), timeout=2.0) as probe:
                probe.get(f"https://127.0.0.1:{port}/health")
        except httpx.HTTPError:
            alive = False
            break
        time.sleep(0.5)
    check("收摊之后那个端口不再答", not alive, port)


def refusal_legs(folder: Path, crt: Path, key: Path) -> None:
    half = spawn(folder, "--tls-cert", str(crt))
    code, out = wait_exit(half)
    check("只给证书不给私钥要停下", code not in (None, 0) and "--tls-key" in out,
          (code, out[-200:]))
    if code is None:
        stop(half)
    missing = spawn(folder, "--tls-cert", str(folder / "没有这张.crt"), "--tls-key", str(key))
    code, out = wait_exit(missing)
    check("证书路径不存在要停下并点名那一个",
          code not in (None, 0) and "不存在" in out, (code, out[-200:]))
    if code is None:
        stop(missing)
    naked = spawn(folder, "--host", "0.0.0.0")
    code, out = wait_exit(naked)
    check("绑非本机又不加密就停下，那句要点名 TLS",
          code not in (None, 0) and "TLS" in out and "127.0.0.1" in out,
          (code, out[-220:]))
    if code is None:
        stop(naked)
    opted = spawn(folder, "--host", "0.0.0.0", "--allow-insecure-remote")
    code, out = wait_exit(opted)
    check("明知故犯了，1.318 那枚显式令牌的规矩照样在",
          code not in (None, 0) and "AGENTCUT_TOKEN" in out, (code, out[-220:]))
    if code is None:
        stop(opted)


def main() -> None:
    folder = scratch.make("agentcut-tls-")
    crt, key = make_cert(folder)
    (folder / "engine").mkdir(parents=True, exist_ok=True)
    serving_legs(folder, crt, key)
    refusal_legs(folder / "refusals", crt, key)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 给了证书就真加密（明文打同一端口拿不到 200）、租约记 tls、"
          "半配好的 TLS 与裸跑明文的非本机绑定都停在自己门前，两道守卫各自独立")


if __name__ == "__main__":
    main()
