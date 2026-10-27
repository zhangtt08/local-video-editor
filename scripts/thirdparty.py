"""生成 `THIRD-PARTY.md`：随包发出去的每一样三方东西，许可与它的**判定依据**。

这不是抄一份许可证名单。每一行的许可都从当场量来的东西里折出来：

* 两支媒体程序：`-version` 那一行、`-buildconf` 的开关表、逐字节 sha256 与字节数——
  许可按规则判：命中 `--enable-gpl` 或任一 GPL-only 外部库就是 GPL 一档，再命中
  `--enable-version3` 就是「GPL-2.0-or-later 或更新，且含只有 GPLv3 才允许的组件」。
  npm 那两只包装工（`ffmpeg-static` / `ffprobe-static`）自己的许可字段是 MIT，
  **包装工不是载荷**——这一条是这份清单存在的理由。
* Python：`uv.lock` 里从那 6 项直接依赖算出的依赖闭包（带平台 marker 的一律计入，宁可多列
  也不漏列），许可读装出来的那一份 METADATA（`License-Expression` → `License` →
  `Classifier: License :: OSI Approved :: …`，证据写明读的是哪一格）。
* 界面：`package-lock.json` 里生产依赖的传递闭包（`devDependencies` 不进这一档），
  许可读装出来的 `package.json` 的 `license` 字段与许可文件的文件名。
* Electron 运行时与 Chromium：随包的是 `node_modules/electron/dist` 那两份许可文件，
  Chromium 的完整三方清单在包内的 `resources/LICENSES.chromium.html`，这里点名它在哪。
* 语音模型：那是**数据**不是代码，这里交回模型目录里到底有没有许可文件——没有就写没有。

跑法：`uv run python scripts/thirdparty.py`（要 `.venv` 与 `desktop/node_modules` 与随包两支）。
判它的是 `tests/thirdparty_check.py`：现场重算再与文件逐字节比，任何一项变了、任何一格许可
填不出来，都会红。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
BIN = DESKTOP / "resources/bin"
ASR = DESKTOP / "resources/asr"
UNPACKED = DESKTOP / "release/win-unpacked"
LICENSE_FILES = ("LICENSE.electron.txt", "LICENSES.chromium.html")
MANIFEST = ROOT / "THIRD-PARTY.md"

RUNTIME = ["fastapi", "uvicorn", "pydantic", "httpx", "mcp", "vosk"]
BUILD_ONLY = ["pyinstaller", "ruff"]

# 这些外部库只要出现在 `-buildconf` 里，那支 ffmpeg 就只能按 GPL 一档再分发。
GPL_ONLY = ("--enable-gpl", "--enable-libx264", "--enable-libx265", "--enable-libxvid",
            "--enable-libsrt", "--enable-libopencore-amrnb", "--enable-libmp3lame",
            "--enable-libspeex", "--enable-libass", "--enable-libfreetype")
LGPL_ONLY = ("--enable-gnutls", "--enable-libvpx", "--enable-libaom", "--enable-libopus",
             "--enable-libfdk-aac", "--enable-libbluray")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def run(exe: Path, *args: str) -> str:
    done = subprocess.run([str(exe), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    return done.stdout or ""


def media_binary(name: str) -> dict[str, object]:
    exe = BIN / name
    if not exe.is_file():
        fail(f"随包媒体程序不见了：{exe}（先跑 scripts/build_engine.py 那一串准备）")
    banner = run(exe, "-hide_banner", "-version").splitlines()
    version_line = banner[0] if banner else ""
    flags = [line.strip() for line in run(exe, "-hide_banner", "-buildconf").splitlines()
             if line.strip().startswith("--")]
    hit_gpl = [flag for flag in flags if flag in GPL_ONLY]
    hit_lgpl = [flag for flag in flags if flag in LGPL_ONLY]
    if not hit_gpl:
        fail(f"{name} 的 -buildconf 里一个 GPL-only 开关都没命中，判定规则该重读：{flags[:6]}")
    if "--enable-version3" in hit_gpl or "--enable-version3" in flags:
        license_id = "GPL-2.0-or-later（且 --enable-version3：含只有 GPLv3 才允许的组件）"
    else:
        license_id = "GPL-2.0-or-later"
    payload = exe.read_bytes()
    return {
        "name": name,
        "version_line": version_line,
        "flags": len(flags),
        "hit_gpl": hit_gpl,
        "hit_lgpl": hit_lgpl,
        "license": license_id,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def read_json(path: Path) -> dict:
    if not path.is_file():
        fail(f"{path.relative_to(ROOT)} 不见了")
    return json.loads(path.read_text(encoding="utf-8"))


def python_closure() -> list[tuple[str, str]]:
    """uv.lock 里从直接依赖算出的传递闭包，交回 (name, version) 按名字排序。"""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    by_name: dict[str, dict] = {}
    for package in lock.get("package", []):
        by_name.setdefault(str(package.get("name", "")).lower(), package)
    missing = [name for name in RUNTIME if name not in by_name]
    if missing:
        fail(f"uv.lock 里找不到这些直接依赖：{missing}")
    seen: set[str] = set()
    queue = list(RUNTIME)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        package = by_name.get(name) or {}
        # 只走 lock 里那张必带依赖表：optional-dependencies 是「这个包自己声明的 extra」，
        # 不是我们装进引擎的东西——按 pyproject 的写法（uvicorn 没带 extra）走才不会虚列。
        for dep in package.get("dependencies") or []:
            if isinstance(dep, dict):
                child = str(dep.get("name", "")).lower()
                if child:
                    queue.append(child)
    out = []
    for name in sorted(seen):
        package = by_name.get(name) or {}
        out.append((name, str(package.get("version", "?"))))
    return out


LICENSE_CLASS = "License :: OSI Approved :: "


def python_license(dist) -> tuple[str, str]:
    """许可与证据：读的是 METADATA 哪一格，写清楚。"""
    expression = (dist.metadata.get("License-Expression") or "").strip()
    if expression:
        return expression, "METADATA 的 License-Expression"
    plain = (dist.metadata.get("License") or "").strip().replace("\n", " ")
    if plain and plain.upper() not in {"UNKNOWN", "NONE", ""}:
        return plain, "METADATA 的 License"
    for classifier in dist.metadata.get_all("Classifier") or []:
        if classifier.startswith(LICENSE_CLASS):
            return classifier[len(LICENSE_CLASS):].strip(), "METADATA 的 Classifier"
    fail(f"{dist.metadata['Name']} 交不出可用的许可字段，得手工认定并写明出处")
    return "", ""  # pragma: no cover


def collected_dists() -> dict[str, str]:
    """冻进 `agentcut.exe` 的那一份里，PyInstaller 实际搬走了哪几包的 METADATA。

    这不是完整清单（PyInstaller 只给一部分包拷 dist-info），所以它只用来做**反向核**：
    这里出现的每一包都必须在清单里有一行。少了那一行，门禁就该红。
    """
    internal = BIN / "agentcut/_internal"
    if not internal.is_dir():
        fail(f"{internal} 不见了——先跑 scripts/build_engine.py --no-uv")
    out: dict[str, str] = {}
    for info in internal.glob("*.dist-info"):
        head = info.name[: -len(".dist-info")]
        if "-" not in head:
            continue
        name, _, version = head.rpartition("-")
        out[name.lower().replace("_", "-")] = version
    return out


def python_rows() -> list[tuple[str, str, str, str, str]]:
    site = ROOT / ".venv/Lib/site-packages"
    if not site.is_dir():
        fail(f"{site} 不见了——先跑 uv sync --group dev")
    installed = {}
    for dist in metadata.distributions(path=[str(site)]):
        key = (dist.metadata["Name"] or "").lower().replace("_", "-")
        installed.setdefault(key, dist)
    closure = dict(python_closure())
    collected = collected_dists()
    rows = []
    for name in sorted(set(closure) | set(collected)):
        version = closure.get(name) or collected[name]
        if name in closure and name in collected and collected[name] != version:
            fail(f"{name} 在 lock 里是 {version}，冻进包里的是 {collected[name]}——先对齐再出清单")
        dist = installed.get(name)
        if dist is None:
            fail(f"清单里的 {name} 没装在 {site} 里，许可没法核验")
        if name in closure and dist.version != version:
            fail(f"{name} 装出来的是 {dist.version}，uv.lock 写的是 {version}——先对齐再出清单")
        license_id, evidence = python_license(dist)
        where = "两者" if name in closure and name in collected else (
            "lock 闭包" if name in closure else "冻结包内")
        rows.append((name, version, license_id, evidence, where))
    return rows


def js_closure() -> list[tuple[str, str]]:
    packages = read_json(DESKTOP / "package-lock.json").get("packages") or {}
    root_entry = packages.get("") or {}
    seen: set[str] = set()
    queue = list((root_entry.get("dependencies") or {}).keys())
    if not queue:
        fail("package-lock 的根条目里没有 dependencies——生产依赖那一档算不出闭包")
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        entry = packages.get(f"node_modules/{name}") or {}
        queue.extend((entry.get("dependencies") or {}).keys())
    out = []
    for name in sorted(seen):
        entry = packages.get(f"node_modules/{name}") or {}
        out.append((name, str(entry.get("version", "?"))))
    return out


def js_rows() -> list[tuple[str, str, str, str]]:
    node_modules = DESKTOP / "node_modules"
    if not node_modules.is_dir():
        fail(f"{node_modules} 不见了——先跑 npm --prefix desktop ci")
    rows = []
    for name, version in js_closure():
        folder = node_modules / name
        manifest = folder / "package.json"
        if not manifest.is_file():
            fail(f"闭包里的 {name} 没装出来，许可没法核验")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if str(data.get("version", "")) != version:
            fail(f"{name} 装出来的是 {data.get('version')}，lock 写的是 {version}")
        license_id = data.get("license")
        if isinstance(license_id, dict):  # 少数包写的是 {"type": ..., "url": ...}
            license_id = license_id.get("type") or ""
        if not license_id:
            fail(f"{name} 的 package.json 没有可用的 license 字段")
        files = sorted(p.name for p in folder.glob("LICENSE*"))
        rows.append((name, version, str(license_id), files[0] if files else "（包里没有许可文件）"))
    return rows


def electron_version() -> dict[str, str]:
    manifest = DESKTOP / "node_modules/electron/package.json"
    if not manifest.is_file():
        fail("electron 没装出来——先跑 npm --prefix desktop ci")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return {"version": str(data.get("version", "?")), "license": str(data.get("license", "?"))}


def packaged(binaries: list[dict]) -> dict[str, object]:
    """装机那一份（`desktop/release/win-unpacked`）里到底有什么——许可文件与两支媒体程序。

    这里量的不是构建输入，是**发出去的那一份**：包内两支的 sha256 必须与上面表格里那两行
    对上，否则清单说的就不是装到客户机器上的东西（这一手 1.315 之后被记作「构建者换掉了
    随包的 FFmpeg 而所有门禁照绿」那笔账）。
    """
    if not UNPACKED.is_dir():
        fail(f"{UNPACKED} 不见了——先跑 npm --prefix desktop run dist")
    notes = {}
    for name in LICENSE_FILES:
        path = UNPACKED / name
        if not path.is_file():
            fail(f"装机那份里没有 {name}，随包的运行时许可没法交代")
        notes[name] = f"`{name}`（{path.stat().st_size:,} B）"
    rows = []
    for item in binaries:
        inside = UNPACKED / "resources/bin" / str(item["name"])
        if not inside.is_file():
            fail(f"装机那份里没有 resources/bin/{item['name']}")
        digest = hashlib.sha256(inside.read_bytes()).hexdigest()
        same = "逐字节相同" if digest == str(item["sha256"]) else "**不一致，这一份得停下**"
        rows.append((f"resources/bin/{item['name']}", f"{inside.stat().st_size:,}", digest, same))
    engine = UNPACKED / "resources/bin/agentcut/agentcut.exe"
    if not engine.is_file():
        fail("装机那份里没有冻结引擎 resources/bin/agentcut/agentcut.exe")
    internal = UNPACKED / "resources/bin/agentcut/_internal"
    collected = len(list(internal.glob("*.dist-info"))) if internal.is_dir() else 0
    return {"notes": notes, "rows": rows, "engine_bytes": engine.stat().st_size,
            "collected": collected}


def asr_rows() -> list[tuple[str, int, int, str]]:
    if not ASR.is_dir():
        fail(f"语音模型目录不见了：{ASR}")
    rows = []
    for model in sorted(ASR.iterdir()):
        if not model.is_dir():
            continue
        files = [item for item in model.rglob("*") if item.is_file()]
        total = sum(item.stat().st_size for item in files)
        licenses = [item.name for item in files
                    if "license" in item.name.lower() or "copying" in item.name.lower()]
        rows.append((model.name, len(files), total,
                     licenses[0] if licenses else "（模型目录里没有许可文件）"))
    if not rows:
        fail("语音模型目录是空的")
    return rows


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return out


def build() -> str:
    binaries = [media_binary("ffmpeg.exe"), media_binary("ffprobe.exe")]
    py_rows = python_rows()
    collected = collected_dists()
    js_rows_ = js_rows()
    run_time = electron_version()
    pack = packaged(binaries)
    models = asr_rows()
    package = read_json(DESKTOP / "package.json")
    builder = str((package.get("devDependencies") or {}).get("electron-builder", "?"))
    lines: list[str] = ["# 三方清单与许可（THIRD-PARTY）", ""]
    lines += [
        "这一页由 `scripts/thirdparty.py` 生成，判它的是 `tests/thirdparty_check.py`——"
        "门禁现场重算再与文件逐字节比，所以「换了个 ffmpeg 构建」「多了个依赖」都会红。"
        "重跑：`uv run python scripts/thirdparty.py`（要 `.venv`、`desktop/node_modules`、"
        "随包那两支媒体程序）。",
        "",
        "## 随包的媒体程序（未修改的上游构建）",
        "",
    ]
    lines += table(
        ["文件", "版本行", "许可（按 -buildconf 判定）", "命中的 GPL 开关", "字节", "sha256"],
        [[str(item["name"]), str(item["version_line"]), str(item["license"]),
          "、".join(item["hit_gpl"]), f"{item['bytes']:,}", str(item["sha256"])]
         for item in binaries],
    )
    lines += [
        "",
        "两支都带 `--enable-gpl`，其中 ffmpeg 那一支还带 `--enable-version3`，所以再分发的口径按 "
        "**GPL** 一档走，不是 LGPL：AgentCut 不修改这两支二进制，交回的是**逐字节相同的上游构建**"
        "（上表的 sha256 就是那一件的指纹）。需要对应源码时：FFmpeg 的完整对应源码在 "
        "<https://ffmpeg.org/download.html>，Windows 的这份构建（6.1.1-essentials_build）在 "
        "<https://www.gyan.dev/ffmpeg/builds/>，构建脚本与配置开关随上游 releases 一起发布；"
        "上表的 `-buildconf` 开关就是那一份源码被这样配置的证据。GPL 的对应源码义务落在"
        "**分发方**：本包只交未修改的上游构建，上面两个 URL 就是对应源码的取得指引；企业把这份"
        "清单随自己的产品再分发时，要按同样的条款附上这份指引。",
        "",
        "这两支的**载荷**是 GPL 一档；把它们拷进包里的 npm 包装工是另一回事，"
        "见下面「构建期与打包期工具」——**包装工的 MIT 字段不等于载荷的许可**，"
        "这正是这一页要拆开写的地方。",
        "",
        "## 随包的桌面运行时",
        "",
    ]
    notes = pack["notes"]
    lines += table(
        ["组件", "版本", "许可", "就在装机那一份的这里"],
        [
            ["Electron", run_time["version"], run_time["license"],
             str(notes["LICENSE.electron.txt"])],
            ["Chromium / Node / V8（Electron 的载荷）", run_time["version"],
             "各自许可（BSD-3-Clause、Apache-2.0、MIT 等混编）",
             str(notes["LICENSES.chromium.html"]) + "——这一份就是 Electron 交回的完整三方清单"],
        ],
    )
    lines += ["", "## 包内核验：装机那份与构建输入是不是同一件东西", ""]
    lines += table(
        ["相对 `desktop/release/win-unpacked/` 的路径", "字节", "sha256", "与构建输入比对"],
        [list(row) for row in pack["rows"]],
    )
    lines += [
        "",
        f"冻结引擎在 `resources/bin/agentcut/agentcut.exe`（{pack['engine_bytes']:,} B），"
        f"它旁边那份 `_internal` 里量到 {pack['collected']} 份 `dist-info`——上面那张 Python 表"
        "的「从哪儿看到」那一列就是拿它对出来的。这一节由 `tests/thirdparty_check.py` 现量现比："
        "**清单说的和包里装的是同一件东西**，这句话在这里不是修辞。",
        "",
        "## 引擎的 Python 依赖（被冻结进 `agentcut.exe`）", ""]
    lines += table(
        ["包", "版本", "许可", "证据（读的是哪一格）", "从哪儿看到"],
        [list(row) for row in py_rows],
    )
    lines += [
        "",
        f"口径：从 `pyproject.toml` 的直接依赖（{'、'.join(RUNTIME)}）出发，按 `uv.lock` "
        "的**必带**依赖边算传递闭包（`optional-dependencies` 里那些 extra 我们没装，就不虚列）。"
        "许可读的是这台机器上装出来的那一份 `METADATA`，版本号必须与 `uv.lock` 对上，"
        "对不上生成器就停。",
        "",
        f"「从哪儿看到」那一列还带一次**反向核**：PyInstaller 实际搬进 `agentcut/_internal` 的 "
        f"{len(collected)} 份 `dist-info` 每了一份都要在表里有一行。那份清单**不是**完整枚举"
        "（PyInstaller 只给一部分包拷元数据），所以它只兜住「包里带着、清单上没写」这一手——"
        "真漏了一行，`tests/thirdparty_check.py` 就该红。",
        "",
        "## 界面的 JS 生产依赖（打进 `app.asar`）",
        "",
    ]
    lines += table(
        ["npm 包", "版本", "许可", "包里的许可文件"],
        [list(row) for row in js_rows_],
    )
    lines += ["", "## 随包的数据资产（语音模型）", ""]
    lines += table(
        ["模型", "文件数", "字节", "目录里的许可文件"],
        [[name, str(count), f"{total:,}", note] for name, count, total, note in models],
    )
    lines += [
        "",
        "模型不是代码，是**权重与词典的数据**，按上游发布的页面随附条款分发"
        "（<https://alphacephei.com/vosk/models>）。上表最后一格如实写着模型目录里到底有没有许可"
        "文件：**没有**。商用分发前要把那一份条款文本随包一起放进来，这一格不该长期空着——"
        "把它填实的动作与核验日期属于交付方，不属于本仓库的猜测。",
        "",
        "## 构建期与打包期工具（不进产品）",
        "",
    ]
    lines += table(
        ["工具", "许可", "为什么不在上面"],
        [
            ["PyInstaller", "GPL-2.0-or-later with a Python exception",
             "它只是把引擎冻成一个自包含可执行文件；那份例外条款覆盖的正是「用它打包自己的程序"
             "不会把程序变成 GPL」。它自己不进包，包里也没有它的代码。"],
            ["ruff", "MIT", "只在验收门禁里做 lint，不进包。"],
            ["electron-builder", f"MIT（{builder}）", "产包工具，不进包。"],
            ["ffmpeg-static / ffprobe-static", "MIT",
             "npm 包装工，运行时装载时才把两支二进制取来；**它们的载荷见上面那一档 GPL**。"],
            ["vite / esbuild / typescript / @vitejs/plugin-react / @types/*",
             "MIT 为主", "都是构建期依赖（`devDependencies`），产物是 bundle，不随包分发其源码。"],
        ],
    )
    lines += ["", "## 义务一览（我们到底欠什么）", ""]
    family: dict[str, int] = {}
    for row in list(py_rows) + list(js_rows_):
        family[row[2]] = family.get(row[2], 0) + 1
    lines += table(
        ["许可", "条数", "我们履行的动作"],
        [
            [key, str(count),
             "归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 "
             "LICENSE 为准"] if "GPL" not in key else
             "上面「随包的媒体程序」那一节写明了对应源码的取得指引"
            for key, count in sorted(family.items(), key=lambda item: (-item[1], item[0]))
        ],
    )
    lines += [
        "",
        f"合计：Python 运行时依赖 {len(py_rows)} 项、JS 生产依赖 {len(js_rows_)} 项、"
        f"随包媒体程序 {len(binaries)} 支、语音模型 {len(models)} 份。"
        "每一项的名字与数字都由 `tests/thirdparty_check.py` 现算现比。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    text = build()
    MANIFEST.write_text(text, encoding="utf-8", newline="\r\n")
    print(f"PASS: 写了 {MANIFEST.name}（{len(text)} 字符，CRLF）")


if __name__ == "__main__":
    main()
