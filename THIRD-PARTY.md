# 三方清单与许可（THIRD-PARTY）

这一页由 `scripts/thirdparty.py` 生成，判它的是 `tests/thirdparty_check.py`——门禁现场重算再与文件逐字节比，所以「换了个 ffmpeg 构建」「多了个依赖」都会红。重跑：`uv run python scripts/thirdparty.py`（要 `.venv`、`desktop/node_modules`、随包那两支媒体程序）。

## 随包的媒体程序（未修改的上游构建）

| 文件 | 版本行 | 许可（按 -buildconf 判定） | 命中的 GPL 开关 | 字节 | sha256 |
|---|---|---|---|---|---|
| ffmpeg.exe | ffmpeg version 6.1.1-essentials_build-www.gyan.dev Copyright (c) 2000-2023 the FFmpeg developers | GPL-2.0-or-later（带 --enable-version3：还含只允许 GPLv3 的组件） | --enable-libx264、--enable-libx265、--enable-libxvid | 82,797,568 | 04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00 |
| ffprobe.exe | ffprobe version 4.0.2 Copyright (c) 2007-2018 the FFmpeg developers | GPL-2.0-or-later（带 --enable-version3：还含只允许 GPLv3 的组件） | --enable-libx264、--enable-libx265、--enable-libxvid | 63,059,968 | 4303ec85855340689b1f8aa5d9c1dc06ef3e3090682de3034edc3fca2b0798d5 |

2/2 支带 `--enable-gpl`（其中 2 支还带 `--enable-version3`），所以再分发的口径按 **GPL** 一档走，不是 LGPL；这个数字是从上面那张表的开关里数出来的，不是写死的。AgentCut 不修改这两支二进制，交回的是**逐字节相同的上游构建**（上表的 sha256 就是那一件的指纹）。需要对应源码时：FFmpeg 的完整对应源码在 <https://ffmpeg.org/download.html>，Windows 的这份构建（6.1.1-essentials_build）在 <https://www.gyan.dev/ffmpeg/builds/>，构建脚本与配置开关随上游 releases 一起发布；上表的 `-buildconf` 开关就是那一份源码被这样配置的证据。GPL 的对应源码义务落在**分发方**：本包只交未修改的上游构建，上面两个 URL 就是对应源码的取得指引；企业把这份清单随自己的产品再分发时，要按同样的条款附上这份指引。

这两支的**载荷**是 GPL 一档；把它们拷进包里的 npm 包装工是另一回事，见下面「构建期与打包期工具」——**包装工的 MIT 字段不等于载荷的许可**，这正是这一页要拆开写的地方。

## 随包的桌面运行时

| 组件 | 版本 | 许可 | 就在装机那一份的这里 |
|---|---|---|---|
| Electron | 33.4.11 | MIT | `LICENSE.electron.txt`（1,096 B） |
| Chromium / Node / V8（Electron 的载荷） | 33.4.11 | 各自许可（BSD-3-Clause、Apache-2.0、MIT 等混编） | `LICENSES.chromium.html`（9,170,910 B）——这一份就是 Electron 交回的完整三方清单 |

## 包内核验：装机那份与构建输入是不是同一件东西

| 相对 `desktop/release/win-unpacked/` 的路径 | 字节 | sha256 | 与构建输入比对 |
|---|---|---|---|
| resources/bin/ffmpeg.exe | 82,797,568 | 04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00 | 逐字节相同 |
| resources/bin/ffprobe.exe | 63,059,968 | 4303ec85855340689b1f8aa5d9c1dc06ef3e3090682de3034edc3fca2b0798d5 | 逐字节相同 |

冻结引擎在 `resources/bin/agentcut/agentcut.exe`（9,270,872 B），它旁边那份 `_internal` 里量到 10 份 `dist-info`——上面那张 Python 表的「从哪儿看到」那一列就是拿它对出来的。这一节由 `tests/thirdparty_check.py` 现量现比：**清单说的和包里装的是同一件东西**，这句话在这里不是修辞。

## 引擎的 Python 依赖（被冻结进 `agentcut.exe`）

| 包 | 版本 | 许可 | 证据（读的是哪一格） | 从哪儿看到 |
|---|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | METADATA 的 License-Expression | lock 闭包 |
| annotated-types | 0.8.0 | MIT | METADATA 的 License-Expression | lock 闭包 |
| anyio | 4.15.1 | MIT | METADATA 的 License-Expression | lock 闭包 |
| attrs | 26.1.0 | MIT | METADATA 的 License-Expression | 两者 |
| certifi | 2026.7.22 | MPL-2.0 | METADATA 的 License | lock 闭包 |
| cffi | 2.1.1 | MIT-0 | METADATA 的 License-Expression | lock 闭包 |
| charset-normalizer | 3.5.2 | MIT | METADATA 的 License | lock 闭包 |
| click | 8.5.0 | BSD-3-Clause | METADATA 的 License-Expression | 两者 |
| colorama | 0.4.6 | BSD License | METADATA 的 Classifier | lock 闭包 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | METADATA 的 License-Expression | 冻结包内 |
| fastapi | 0.142.2 | MIT | METADATA 的 License-Expression | lock 闭包 |
| h11 | 0.16.0 | MIT | METADATA 的 License | lock 闭包 |
| httpcore | 1.0.9 | BSD-3-Clause | METADATA 的 License-Expression | lock 闭包 |
| httpx | 0.28.1 | BSD-3-Clause | METADATA 的 License | lock 闭包 |
| httpx-sse | 0.4.3 | MIT | METADATA 的 License | lock 闭包 |
| idna | 3.20 | BSD-3-Clause | METADATA 的 License-Expression | lock 闭包 |
| jsonschema | 4.26.0 | MIT | METADATA 的 License-Expression | 两者 |
| jsonschema-specifications | 2025.9.1 | MIT | METADATA 的 License-Expression | lock 闭包 |
| mcp | 1.30.0 | MIT | METADATA 的 License | 两者 |
| opentelemetry-api | 1.45.0 | Apache-2.0 | METADATA 的 License-Expression | 两者 |
| pycparser | 3.0 | BSD-3-Clause | METADATA 的 License-Expression | lock 闭包 |
| pydantic | 2.13.5 | MIT | METADATA 的 License-Expression | 两者 |
| pydantic-core | 2.46.5 | MIT | METADATA 的 License-Expression | lock 闭包 |
| pydantic-settings | 2.15.0 | MIT | METADATA 的 License-Expression | lock 闭包 |
| pyjwt | 2.15.1 | MIT | METADATA 的 License-Expression | lock 闭包 |
| python-dotenv | 1.2.4 | BSD-3-Clause | METADATA 的 License | lock 闭包 |
| python-multipart | 0.0.32 | Apache-2.0 | METADATA 的 License-Expression | lock 闭包 |
| pywin32 | 312 | PSF | METADATA 的 License | lock 闭包 |
| referencing | 0.37.0 | MIT | METADATA 的 License-Expression | lock 闭包 |
| requests | 2.34.2 | Apache-2.0 | METADATA 的 License | lock 闭包 |
| rpds-py | 2026.6.3 | MIT | METADATA 的 License-Expression | lock 闭包 |
| srt | 3.5.3 | MIT | METADATA 的 License | lock 闭包 |
| sse-starlette | 3.5.0 | BSD-3-Clause | METADATA 的 License-Expression | lock 闭包 |
| starlette | 1.7.0 | BSD-3-Clause | METADATA 的 License-Expression | lock 闭包 |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | METADATA 的 License | 两者 |
| typing-extensions | 4.16.0 | PSF-2.0 | METADATA 的 License-Expression | lock 闭包 |
| typing-inspection | 0.4.4 | MIT | METADATA 的 License-Expression | lock 闭包 |
| urllib3 | 2.8.0 | MIT | METADATA 的 License-Expression | lock 闭包 |
| uvicorn | 0.54.0 | BSD-3-Clause | METADATA 的 License-Expression | lock 闭包 |
| vosk | 0.3.45 | Apache Software License | METADATA 的 Classifier | 两者 |
| websockets | 17.2 | BSD-3-Clause | METADATA 的 License-Expression | 两者 |

口径：从 `pyproject.toml` 的直接依赖（fastapi、uvicorn、pydantic、httpx、mcp、vosk）出发，按 `uv.lock` 的**必带**依赖边算传递闭包（`optional-dependencies` 里那些 extra 我们没装，就不虚列）。许可读的是这台机器上装出来的那一份 `METADATA`，版本号必须与 `uv.lock` 对上，对不上生成器就停。

「从哪儿看到」那一列还带一次**反向核**：PyInstaller 实际搬进 `agentcut/_internal` 的 10 份 `dist-info` 每了一份都要在表里有一行。那份清单**不是**完整枚举（PyInstaller 只给一部分包拷元数据），所以它只兜住「包里带着、清单上没写」这一手——真漏了一行，`tests/thirdparty_check.py` 就该红。

## 界面的 JS 生产依赖（打进 `app.asar`）

| npm 包 | 版本 | 许可 | 包里的许可文件 |
|---|---|---|---|
| js-tokens | 4.0.0 | MIT | LICENSE |
| loose-envify | 1.4.0 | MIT | LICENSE |
| react | 18.3.1 | MIT | LICENSE |
| react-dom | 18.3.1 | MIT | LICENSE |
| scheduler | 0.23.2 | MIT | LICENSE |

## 随包的数据资产（语音模型）

| 模型 | 文件数 | 字节 | 目录里的许可文件 |
|---|---|---|---|
| vosk-model-small-cn-0.22 | 14 | 68,292,271 | （模型目录里没有许可文件） |

模型不是代码，是**权重与词典的数据**，按上游发布的页面随附条款分发（<https://alphacephei.com/vosk/models>）。上表最后一格如实写着模型目录里到底有没有许可文件：**没有**。商用分发前要把那一份条款文本随包一起放进来，这一格不该长期空着——把它填实的动作与核验日期属于交付方，不属于本仓库的猜测。

## 构建期与打包期工具（不进产品）

| 工具 | 许可 | 为什么不在上面 |
|---|---|---|
| PyInstaller | GPL-2.0-or-later with a Python exception | 它只是把引擎冻成一个自包含可执行文件；那份例外条款覆盖的正是「用它打包自己的程序不会把程序变成 GPL」。它自己不进包，包里也没有它的代码。 |
| ruff | MIT | 只在验收门禁里做 lint，不进包。 |
| electron-builder | MIT（^26.0.0） | 产包工具，不进包。 |
| ffmpeg-static / ffprobe-static | MIT | npm 包装工，运行时装载时才把两支二进制取来；**它们的载荷见上面那一档 GPL**。 |
| vite / esbuild / typescript / @vitejs/plugin-react / @types/* | MIT 为主 | 都是构建期依赖（`devDependencies`），产物是 bundle，不随包分发其源码。 |

## 义务一览（我们到底欠什么）

| 许可 | 条数 | 我们履行的动作 |
|---|---|---|
| MIT | 25 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| BSD-3-Clause | 10 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| Apache-2.0 | 3 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| Apache Software License | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| Apache-2.0 OR BSD-3-Clause | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| BSD License | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| MIT-0 | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| MPL-2.0 | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| MPL-2.0 AND MIT | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| PSF | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |
| PSF-2.0 | 1 | 归属与全文见各包自己的许可文件；这一页把每一格的名字与出处列出来，随包文本以各包内的 LICENSE 为准 |

合计：Python 运行时依赖 41 项、JS 生产依赖 5 项、随包媒体程序 2 支、语音模型 1 份。每一项的名字与数字都由 `tests/thirdparty_check.py` 现算现比。
