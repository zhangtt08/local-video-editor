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
   两道**都**没过时，那一句得同时点名两道——只报一道就是把另一道演没了；
⑤ 租约里记下加密与否；`desktop` 附到一台 TLS 引擎上要**说清这一手还没做**，
   而不是把它演成「数据目录被别人占着」；
⑥ 收摊之后那个端口不再答；
⑦ 反证：同一把明文尺先打在没给证书的引擎上，必须读出 200——否则②那一格会因为连不上而长绿。

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


def get_json(api: httpx.Client, url: str, label: str) -> dict:
    """一次 GET 的三种收场都写成点名的一格：连不上、不是 200、答的不是 JSON。
    抛出去会跳过 stop()，把引擎留成活口，而且只留下一段栈。"""
    try:
        answer = api.get(url)
    except httpx.HTTPError as error:
        check(label, False, f"{type(error).__name__}: {str(error)[:160]}")
        return {}
    check(label, answer.status_code == 200, answer.status_code)
    try:
        return answer.json()
    except ValueError:
        check(label + "（答的不是 JSON）", False, answer.text[:120])
        return {}


def plain_read(port: int) -> tuple[bool, object]:
    """明文探针：200 才算真在服务明文。这一把尺得先被明文那一台校过（见 plaintext_control）。"""
    with httpx.Client(timeout=10.0) as plain:
        try:
            answer = plain.get(f"http://127.0.0.1:{port}/health")
            return answer.status_code == 200, answer.status_code
        except httpx.HTTPError as error:
            return False, type(error).__name__


def calibrate_plain_probe(folder: Path) -> None:
    """⑦ 反证：同一把明文尺打在没给证书的引擎上必须读出 200。

    少了这一格，② 那一句「明文不许答 200」会因为探针根本连不上而长绿——尺得先在已知
    答得出 200 的地方校过一次，才能拿它去证明加密那一台确实不答。
    """
    folder.mkdir(parents=True, exist_ok=True)
    proc = spawn(folder, AGENTCUT_TOKEN=TOKEN)
    try:
        ready = ready_line(proc)
        port = int(ready.get("port") or 0)
        check("当尺用的那一台明文引擎起得来（这一格是⑦的底座）",
              port > 0 and ready.get("tls") is False
              and str(ready.get("base_url", "")).startswith("http://"),
              ready)
        if port:
            served, evidence = plain_read(port)
            check("明文尺读得到 200（读不到就别拿它去证明②）", served, evidence)
    finally:
        stop(proc)


def serving_legs(folder: Path, crt: Path, key: Path) -> None:
    # 令牌走环境那一条路（57 个字符，过 `load_token` 的 32 字下限）：这一档要连的是带身份的门。
    proc = spawn(folder, "--tls-cert", str(crt), "--tls-key", str(key),
                 AGENTCUT_TOKEN=TOKEN)
    port = 0
    try:
        ready = ready_line(proc)
        check("给了证书就起得来，ready 行说得出 tls", ready.get("tls") is True, ready)
        check("base_url 得是 https://（交回 http:// 就是让人去撞明文）",
              str(ready.get("base_url", "")).startswith("https://"), ready.get("base_url"))
        base = str(ready.get("base_url", ""))
        port = int(ready.get("port") or 0)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        with httpx.Client(verify=str(crt), headers=headers, timeout=30.0) as api:
            get_json(api, base + "/health", "拿那张证书当 CA 真连一次：/health 200")
            caps = get_json(api, base + "/v1/capabilities", "TLS 底下读得到能力表")
            if caps:
                check("能力表里带着版本号（TLS 不是只在 /health 上演的样子）",
                      bool(caps.get("app_version") or ""), sorted(caps)[:8])
            info = get_json(api, base + "/v1/info", "TLS 底下读得到 /v1/info")
            if info:
                payload = info.get("info") if isinstance(info.get("info"), dict) else info
                check("TLS 底下 /v1/info 交回的 base_url 也是 https",
                      str(payload.get("base_url", "")).startswith("https://"),
                      payload.get("base_url"))
        served, evidence = plain_read(port)
        check("同一端口用明文打，不许答 200", not served, evidence)
        lease = folder / "engine" / LEASE_NAME
        record = json.loads(lease.read_text(encoding="utf-8")) if lease.is_file() else {}
        check("租约里记下这台是加密服务的（文件都没有就是压根没写）",
              record.get("tls") is True, record or str(lease))
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
    finally:
        stop(proc)
    if port:  # 端口都没起来，上面那几格已经点名红了，别再让⑥拿 0 号端口演一次「不答」
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
    naked = spawn(folder, "--host", "0.0.0.0", AGENTCUT_TOKEN="")
    code, out = wait_exit(naked)
    check("绑非本机又不加密就停下，那句要点名 TLS",
          code not in (None, 0) and "TLS" in out and "127.0.0.1" in out,
          (code, out[-220:]))
    check("两道门都没过时那一句得同时点名两道——加密那道不许把 1.318 的令牌那道演没了"
          "（1.322 空机全套就红在这一手：serving_check 搜不到 AGENTCUT_TOKEN）",
          code not in (None, 0) and "AGENTCUT_TOKEN" in out, (code, out[-220:]))
    if code is None:
        stop(naked)
    opted = spawn(folder, "--host", "0.0.0.0", "--allow-insecure-remote", AGENTCUT_TOKEN="")
    code, out = wait_exit(opted)
    check("明知故犯了，1.318 那枚显式令牌的规矩照样在",
          code not in (None, 0) and "AGENTCUT_TOKEN" in out, (code, out[-220:]))
    if code is None:
        stop(opted)


def main() -> None:
    folder = scratch.make("agentcut-tls-")
    crt, key = make_cert(folder)
    (folder / "engine").mkdir(parents=True, exist_ok=True)
    calibrate_plain_probe(folder / "plain")
    serving_legs(folder, crt, key)
    refusal_legs(folder / "refusals", crt, key)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 明文尺先在明文那台校过 200，再拿它证明给了证书的那一台不答明文；"
          "租约记 tls、半配好的 TLS 与裸跑明文的非本机绑定都停在自己门前，两道守卫各自独立")


if __name__ == "__main__":
    main()
