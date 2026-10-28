# 企业落地手册（AgentCut）

这页写给两批人：把 AgentCut 装进流水线做运维的人，以及要把剪辑能力接进 Agent 的工程师。
所有命令、旗标与路由名都对着源码里的真名写（`src/agentcut/__main__.py`、
`src/agentcut/http_api.py`、`src/agentcut/agent_contract.py`），不写「大概叫什么」。

## 三个面，一台引擎

| 面 | 怎么起 | 给谁用 |
|---|---|---|
| 桌面 | 双击根目录 `AgentCut.exe`，或 `python -m agentcut desktop` | 人：时间线、调色、检查器 |
| HTTP | `python -m agentcut api` | 程序：`/v1` 那批路由 |
| MCP | `python -m agentcut mcp`（stdio） | Agent：工具名与 HTTP 同源 |

三面共用同一份工程存储、同一本幂等台账、同一套 revision 校验，所以「人改一步、Agent 改一步」
不会出现两种结果。Agent 接进去之前不需要装任何界面：MCP 适配器自己会按需拉引擎。

## 装与起

引擎的数据都集中在一个目录里：工程存储 `agentcut.sqlite3`、能力缓存 `caps.json`、
令牌 `tokens.json`、审计台账 `audit.jsonl`、单实例租约 `engine.lock`。默认落在安装位置旁边的
`data/`，要换就 `--data-dir`。其它要交代的路径：

| 旗标 | 含义 |
|---|---|
| `--media-root`（可重复） | 素材允许的根目录。**不指认的根，引擎读不到**，这是安全边界不是便利项 |
| `--output-dir` | 交付物落点，也是输出盘底线检查的那块盘 |
| `--cache-dir` | 代理与缩略图缓存 |
| `--token-file` | 令牌文件位置，默认在数据目录里 |
| `--host` | 绑定地址，默认 `127.0.0.1`；离开本机就要 TLS 或 `--allow-insecure-remote`（见「传输」那一节） |
| `--tls-cert` / `--tls-key` | 用 TLS 服务：一对 PEM，只给一半或路径不存在都不起 |
| `--allow-insecure-remote` | 明知故犯：非本机绑定裸跑明文（写操作在网段里可读） |
| `--allow-origin`（可重复） | 放行哪个网页来源调这台引擎 |
| `--ffmpeg` / `--ffprobe` | 显式指定媒体程序；不指就用随包那两支（见 `THIRD-PARTY.md`） |
| `--expose-token` | 把令牌交回给调用方；默认不交 |
| `--json` | ready 行改成机器可读的一行 JSON，运维脚本读的就是这一行 |

ready 行现在说得出现场读数：`port`、`base_url`、`bind`、`remote`、`tokens`、`audit`、
`slots`、`max_queue`、`queue_per_token`、`requeued`、`min_free_mb`、`pid`、`lease`。

## 一台数据目录只服一台引擎

`--port 0` 让每台自己挑端口，所以两台机器**从不撞端口**——撞的是同一本 sqlite、同一本台账
与同一枚令牌，两台会互相改写状态。因此数据目录里有一份 `engine.lock`（`pid / port / mode /
started_at`）：

- `api` 模式撞上别人的租约就**停下**，而且是在读令牌**之前**停下——不该动这目录的进程连令牌都
  不碰。那句拒绝点名是谁在服（PID、端口、模式、起于何时）并给两条出路：关掉那一台，或换
  `--data-dir`。
- `desktop` 模式不拒，改成**附上去**：双击第二个窗口报的是那一台的端口与地址，
  `attached_to_pid` 说清附到了谁身上，媒体根与输出根从那一台的 `/v1/info` 现取。附上去那台
  **不写也不删**租约。
- 版本对不上时附上去那台会**停下**：新界面配旧引擎会凑成一件谁也没测过的软件。
- 明知故犯要共目录：`--allow-shared-data-dir`。它照样不碰别人的租约，只是不再拦你。

## 谁能调：具名令牌与作用域

```
python -m agentcut tokens --add-label studio-a --scopes write
python -m agentcut tokens --list
python -m agentcut tokens --revoke-label studio-a
```

`tokens.json` 里只存 `secret_sha256`，明文只在发的那一刻出现一次。作用域是 `read` / `write` /
`both`；用只读的令牌做写操作会得到 403 `SCOPE_DENIED`，点名是谁（哪枚令牌）被拒。吊销当场生效，
不需要重启引擎。

**绑定离开本机就必须有显式令牌**：`--host 0.0.0.0`（或任何非本机地址）时，自动生成的那枚令牌
不够用，必须把 `AGENTCUT_TOKEN` 设成一个显式值，否则引擎不起。跨源访问由 `--allow-origin`
单独放行。

## 传输：本机可以明文，跨机默认必须加密

| 想要的样子 | 怎么起 |
|---|---|
| 只听本机（默认） | `agentcut api` —— 明文环回，桌面外壳与本地桥都走这一条 |
| 交给反向代理终止 TLS | 代理那侧收公网，这一台还是 `--host 127.0.0.1`（推荐：证书轮转、SNI、访问日志都在代理） |
| 引擎自己收 TLS | `agentcut api --host 0.0.0.0 --tls-cert /etc/agentcut/server.crt --tls-key /etc/agentcut/server.key` |
| 明知故犯跑明文 | 再加 `--allow-insecure-remote` —— 写操作在整个网段里就是明文，这一句写在拒绝里也写在这里 |

三条规矩值得记住：`--tls-cert` 与 `--tls-key` **必须一起给**（只给一半是配错了，不是选了不加密，
引擎直接不起着并说清缺哪一半）；给了就要**文件真的在**（路径不存在同样停下）；开了 TLS 之后
ready 行交回 `tls: true`、`base_url` 变成 `https://`，`/v1/info` 与流地址也跟着换成 https——
一台加密服务的引擎不该再交回 `http://` 的链接让人去撞明文。判它的是
`tests/tls_check.py`：现造一张自签证书（SAN 里写 `127.0.0.1`）、真连一次，还要**用明文打同一个
端口拿不到 200**，否则「加密」只是嘴上说——而这把明文尺先在没给证书的那一台上读出过 200，
它才有资格说这一台读不出。跨机绑定连身份（`AGENTCUT_TOKEN`）也缺时，拒绝的那一句会**同时点名
两道门**：只报一道，另一道就被演没了。

桌面外壳附不到一台 TLS 引擎上（这一手还没做，引擎会停下并说明原因，而不是演成
「数据目录被别人占着」）：外壳与引擎在同一台机器上，本机的明文环回就够了；
要给别的机器用，走 HTTP/MCP 那扇门。

## 谁做了什么：引擎自己记的台账

`audit.jsonl` 一行一条**动作**（写操作，加上被拒的 401/403），带 `seq`、谁（令牌标签）、
叫什么路由、参数摘要与结果。读操作不记——心跳式轮询会把台账冲成噪音。查它两条路：
`GET /v1/agent/audit` 或 MCP `agent_audit`。`--no-audit` 可以关掉，但那是主动放弃可追溯性。

## 吞吐、额度与重启

| 旗标 | 默认 | 拒的时候说什么 |
|---|---|---|
| `--render-slots` | `api` 2 路 / `desktop` 1 路（传 0 走这个默认） | — |
| `--max-queue` | 64 | 429 `QUEUE_FULL`，details 带 `pending / limit / incoming` |
| `--queue-per-token` | 16 | 429 `QUOTA_EXCEEDED`，多带一个 `actor`（哪枚令牌） |
| `--min-free-mb` | 2048 | 503 `OUTPUT_DISK_TIGHT`，点名 `root / free_bytes / reserve_bytes` |

重启不丢活：没开始的单子接回队列自己渲完；渲到一半被打断的单子标 `INTERRUPTED`，**同时放开它的
幂等凭据**，所以同一个 `request_id` 可以重投（不放开就永远渲不出第二遍）。ready 行里的
`requeued` 就是开机那一刻找回来的单数。

输出盘只守底线不猜体积：CRF 产物大小没有可信的第三方来源，编个常数等于把猜测写成度量。
`/v1/metrics` 里如果某一行带着 `needed_bytes` 与 `basis: "measured …"`，那是这台引擎**真渲过
同一预设**之后量出来的字节/秒；没渲过就不报数。

## 运维读数与作业

`GET /v1/metrics`（MCP 同名 `agent_metrics`）三张表全部现数：`queue`（在等 / 槽 / `live_slots` /
额度 / `requeued`）、`jobs`（按状态计数、失败码分布、耗时分位、真交付字节）、`outputs`（每块根的
磁盘用量）。作业侧：`POST /v1/projects/{id}/renders` 投单、`GET /v1/jobs/{id}` 读、
`POST /v1/jobs/{id}/cancel` 取消（排队中的取消会**落库**，不是只回一个对象），
`GET /v1/jobs/{id}/verify` 让引擎自己拿 ffprobe 与 EBU R128 验收那份交付。

## Agent 怎么接

只有一个真源：`GET /v1/agent/manifest`。工具名、参数、路由、作用域、配方全在那里，
HTTP、MCP 与本地桥三面对同一张表核验（`tests/agent_contract_check.py` 判的就是这件事）。
**条数不写在这页上**——现场读 manifest，写死的数字下一档就会说谎。

一条片子从头到尾一刀跑完：`POST /v1/agent/recipes/{recipe_id}/run`（MCP 同名 `recipe_run`）。
配方里的每一步都走引擎自己那张路由表、同一条 bearer 令牌、同一条 revision 校验与幂等台账，
所以「一把跑完」与「逐步调用」不会有两种结果。整刀幂等：同一个 `request_id` 再叫一次，
写步一律标「已经跑过」并读回当时的工程与那一单交付。缺参数在建工程之前就 422
`RECIPE_PARAM_MISSING`，点名缺哪样。

接入清单：MCP 客户端把 `python -m agentcut mcp` 当 stdio 服务器起；或直接把 HTTP
基址与令牌交给编排器。两条路都需要 `--media-root` 指到素材真的在那里的根。

## 备份、迁移与还原

数据目录整体就是状态：`agentcut.sqlite3`（工程与历史）、`tokens.json`、`audit.jsonl`、
`caps.json`、以及 `--output-dir` 与 `--cache-dir` 指向的目录。工程可导出成 FCPXML /
FCP7 XML / EDL / 剪映草稿，也能搬回来——所以「备份」最小可用的一份就是那个 sqlite。
换机器：拷贝数据目录 + 用同一个版本的包（`/v1/info` 里的 `app_version` 与包内那份必须一致）。
一台数据目录在同一时刻只服一台引擎，这条对备份也成立：别把正在服务的那本 sqlite 拷成第二台
的活动目录。

## 现在还没做的（别按做过的样子接）

| 项 | 现状 |
|---|---|
| 传输加密 | 引擎侧已给（`--tls-cert/--tls-key`，见上一节）。**没有**的是：桌面外壳附到一台 TLS 引擎上（会停下并说明），以及证书自动轮转（交给代理或运维的定时重启） |
| 多租户与权限模型 | 只有「具名令牌 + read/write 作用域」，没有工程级 ACL、没有用户目录接入 |
| 完成通知 | 没有 webhook / 回调，调用方轮询 `GET /v1/jobs/{id}` 或 `job_wait` |
| 目录监听入库 | 没有 watch folder，素材要靠 `POST /v1/media/import` 或界面导入 |
| 语音模型许可文本 | `THIRD-PARTY.md` 里那一格如实写着模型目录里**没有**许可文件，商用再分发前要补 |
| 界面里的许可入口 | 这一页与 `THIRD-PARTY.md` 在仓库与包里，界面上还没有读它的位置 |

## 一键冒烟

`python scripts/enterprise_smoke.py` 在一台目标机上做 go/no-go：引擎起得起、租约守得住、
真素材一刀配方跑到交付、`deliver_verify` 逐条过、台账写得出那一行、`/v1/metrics` 读得出数、
只读令牌被拒得对、吊销之后立刻不认、输出盘底线拒得对。它交回一张表与一个退出码，
判它的门禁是 `tests/enterprise_smoke_check.py`。

## 三方许可

随包发出去的每一样三方东西、它们的许可与**判定依据**（两支媒体程序是现场跑 `-buildconf`
判的，不是抄的）、以及「装机那份与构建输入是不是同一件东西」的逐字节核验，都在
`THIRD-PARTY.md`。生成器是 `scripts/thirdparty.py`，门禁是 `tests/thirdparty_check.py`。
