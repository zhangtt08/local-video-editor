"""一键冒烟的门禁：真跑一遍 `scripts/enterprise_smoke.py`，读数一条不许少、一条不许红。

这一档为什么值得存在：企业拿到的不是 183 道 Python 门禁，是**一台机器上的那支 exe**。
冒烟脚本打的全是对外那扇门（`/v1` 与 `agentcut tokens`），而这一档再判它三件事——

① 二十三条腿一条都不许缺席（腿名按 ①…⑫ 那十二个圈号点齐，删一条就红；圈号下面每条腿
   各自有几条，由那个总数钉住——只查圈号的话，⑫ 少一条仍然绿）；
② 每一条都得绿，退出码 0；
③ 反向也判：`--engine` 指到不存在的那一支，脚本要停在「引擎不存在」那一句上、退出码 2，
   而不是把没跑当成跑过（**没有这一腿，前面那条绿灯可以靠一支被砍空的脚本拿到**）。

跑法：空闲机器单跑 `uv run python tests/enterprise_smoke_check.py`。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "scripts/enterprise_smoke.py"
ENGINE = ROOT / "desktop/resources/bin/agentcut/agentcut.exe"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def run_smoke(out: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SMOKE), "--json", str(out), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900, cwd=str(ROOT), env=env,
    )


def main() -> None:
    if not SMOKE.is_file():
        raise SystemExit(f"FAIL: 冒烟脚本不见了：{SMOKE}")
    if not ENGINE.is_file():
        raise SystemExit(f"FAIL: {ENGINE} 不在——先按 README 的重建链产冻结引擎"
                         "（`scripts/build_engine.py --no-uv --verify`）")
    with tempfile.TemporaryDirectory(prefix="agentcut-smokewrap-") as raw:
        folder = Path(raw)
        good = folder / "good.json"
        done = run_smoke(good)
        check("冒烟脚本的退出码是 0", done.returncode == 0,
              (done.returncode, (done.stdout or "")[-400:], (done.stderr or "")[-200:]))
        rows = json.loads(good.read_text(encoding="utf-8")) if good.is_file() else []
        # 23 = 现测的腿数（①②③⑨⑪ 各两条、④ 三条、⑫ 五条，其余一条）。加腿要一起改这里，
        # 删腿会红在这里——只查圈号的话，⑫ 少一条照样绿。
        check("二十三条腿一条都不许缺席", len(rows) >= 23, len(rows))
        red = [row["name"] for row in rows if not row.get("ok")]
        check("每一条都绿", not red, red)
        names = "、".join(str(row["name"]) for row in rows)
        missing = [mark for mark in CIRCLED if mark not in names]
        check("十二个圈号对应的腿都在（删一条就红在这里）", not missing, missing)
        # 交付那一腿必须是**真文件**：读④里那条「交付文件真在盘上」的证据，字节数要过万。
        output_row = next((row for row in rows if "交付文件真在盘上" in str(row.get("name"))), {})
        check("④ 那句说的是一条真在盘上的交付，不是 0 字节",
              bool(output_row.get("ok")) and re.search(r"\d{5,}", str(output_row)),
              output_row)

        empty = folder / "empty.json"
        refusal = run_smoke(empty, "--engine", str(folder / "没有这一支.exe"))
        check("引擎不存在时停在门上（退出码 2，不把没跑当成跑过）",
              refusal.returncode == 2 and "引擎不存在" in (refusal.stdout or ""),
              (refusal.returncode, (refusal.stdout or "")[-200:]))
        check("那一趟不该留下半张结果表", not empty.is_file() or empty.stat().st_size < 8,
              empty.stat().st_size if empty.is_file() else 0)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print(f"PASS: 一键冒烟在随包引擎上跑了 {len(rows)} 条腿全绿（①…⑫ 十二个圈号齐），"
          "引擎不在时它停在门上而不是交回一张空表")


if __name__ == "__main__":
    main()
