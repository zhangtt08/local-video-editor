"""量具在 `%TEMP%` 里建的 Edge profile 目录，必须自己删掉——这一档判的是形状。

1.321 那两天里量到两台数字：这台机器的 `%TEMP%` 积了 **346 个** `agentcut-*` 目录、
**7.2 GB**（手工清掉），同一天之后再清一次又是 30 个 / 755 MB。原因是量具收了尾——
按 PID 连子树杀掉 Edge——却没还那一份 profile 目录：Python 那一侧有 `tests/scratch.py`
兜着（建了就走 atexit 删），Node 那一侧没人管。

判据只有两条，都是读源码就能判的：

① 每一份建在 `os.tmpdir()` 下的目录（`fs.mkdtempSync(...)` 或 `path.join(os.tmpdir(), ...)`），
   在同一个文件里必须有一次 `fs.rmSync(那一个变量`——只杀进程不删目录就红；
② 每一支带 `--user-data-dir=` 的量具，那个 profile 变量同样要有一次 `fs.rmSync`
   （由外部 `--profile` 传进来的也算：那一格照样要在自己文件里删）。

反向也钉：把某一支的 `fs.rmSync` 删掉，这一档必须红在那一支的名字上（不然这条判据
只是修辞）。红的时候交回「哪个文件、哪个变量、缺哪一条」。

跑法：`uv run python tests/temp_hygiene_check.py`（纯静态，不用起浏览器）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FAILURES: list[str] = []

# 建在临时目录下的那一些变量名
CREATED = [
    re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*fs\.mkdtempSync\("),
    re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*path\.join\(\s*os\.tmpdir\(\)"),
]
# 传进 Edge 的那一些变量名
LAUNCHED = [
    re.compile(r'--user-data-dir="\s*\+\s*([A-Za-z_$][\w$]*)'),
    re.compile(r'--user-data-dir=\$\{\s*([A-Za-z_$][\w$]*)\s*\}'),
    re.compile(r'"--user-data-dir=" \+ ([A-Za-z_$][\w$]*)'),
]


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def names(patterns: list[re.Pattern], text: str) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


HELPER = re.compile(r"function\s+(\w+)\s*\(\s*(\w+)\s*\)\s*\{(.*?)\n\}", re.S)


def deleted(variable: str, text: str) -> bool:
    """还了没有：要么就地 `fs.rmSync(变量`，要么把它交给一个「会 rmSync 自己参数」的帮手。

    量具普遍是 `killByProfile(profileDir)` 这种形状——外层变量叫 `profile`，帮手参数叫
    `profileDir`。只认前一种就会把已经改好的量具读成没还；所以这里两头都认，
    但帮手必须**在同一个文件里**被以那个变量调用过，才算数。
    """
    if re.search(r"fs\.rmSync\(\s*" + re.escape(variable) + r"\s*[,)]", text):
        return True
    for match in HELPER.finditer(text):
        name, param, body = match.groups()
        if not re.search(r"fs\.rmSync\(\s*" + re.escape(param) + r"\s*[,)]", body):
            continue
        if re.search(r"\b" + re.escape(name) + r"\(\s*" + re.escape(variable) + r"\s*[\),]", text):
            return True
    return False


def main() -> None:
    paths = sorted(SCRIPTS.glob("*.cjs"))
    if len(paths) < 5:
        FAILURES.append(f"scripts/ 下只读到 {len(paths)} 份 .cjs，这把尺扫了个空")
    watched = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        # 建出来的与传给 Edge 的可能是同一个变量：一个变量报一次就够。
        wanted = names(CREATED, text)
        for variable in names(LAUNCHED, text):
            if variable not in wanted:
                wanted.append(variable)
        if not wanted:
            continue
        watched += 1
        for variable in wanted:
            check(f"{path.name} 在临时地方写的 `{variable}` 没有还（只杀进程不删，"
                  f"这台机器的 %TEMP% 就是这么攒到 346 个 / 7.2 GB 的）",
                  deleted(variable, text), variable)
    check("这把尺至少看着几份量具（一份都没看着就是扫了个空）", watched >= 5, watched)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print(f"PASS: {watched} 份 Node 量具建的临时目录与 Edge profile 都有对应的 "
          "fs.rmSync——建在哪儿就得还在哪儿")


if __name__ == "__main__":
    main()
