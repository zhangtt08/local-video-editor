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
| `--token-file` | 令牌文件位置，默认在数据目录里；令牌只能从这一支旗标或环境 `AGENTCUT_TOKEN` 交进来，命令行没有直接写令牌的那一支 |
| `--exit-with-parent` | 传入父进程 PID：它不在了引擎自己退出（默认 0＝不管父进程）。桌面外壳与 agent 的 stdio 桥靠这一手不留孤儿引擎 |
| `--host` | 绑定地址，默认 `127.0.0.1`；离开本机就要 TLS 或 `--allow-insecure-remote`（见「传输」那一节） |
| `--tls-cert` / `--tls-key` | 用 TLS 服务：一对 PEM，只给一半或路径不存在都不起 |
| `--allow-insecure-remote` | 明知故犯：非本机绑定裸跑明文（写操作在网段里可读） |
| `--callback-url`（可重复） | 作业走到终态时把回执 POST 到这儿；只认不带账号的 http/https（见「事件出口」那一节） |
| `--callback-attempts` | 一份回执最多投几次，默认 4；用完还不成就记成 `gave_up` |
| `--callback-timeout` | 单次投递等多久算失败，默认 5 秒；投送在后台线程里跑，不占渲染槽 |
| `--allow-origin`（可重复） | 放行哪个网页来源调这台引擎 |
| `--watch-dir`（可重复） | 盯这个目录收素材：新落地且写完的文件按引擎自己那条导入路收下（见「素材入口」那一节） |
| `--watch-interval` / `--watch-grace` | 多久扫一轮（默认 2 秒）/ 落地后再静默多久才收（默认 2 秒）——半拷的文件挡在这一步 |
| `--ffmpeg` / `--ffprobe` | 显式指定媒体程序；不指就用随包那两支（见 `THIRD-PARTY.md`） |
| `--expose-token` | 把令牌交回给调用方；默认不交 |
| `--json` | ready 行改成机器可读的一行 JSON，运维脚本读的就是这一行 |

ready 行现在说得出现场读数：`port`、`base_url`、`bind`、`remote`、`tokens`、`audit`、
`slots`、`max_queue`、`queue_per_token`、`requeued`、`min_free_mb`、`pid`、`lease`，加上后三档
各自的读数：`tls` 是布尔，`callbacks` 与 `watch` 是**现算的摘要**（配了回执地址的引擎，ready
那一行就答得出它欠着几条；配了目录的那台答得出盯了几处、有几个目录已经不在了）。

## 无人值守：崩了有人接着把它起来

`agentcut supervise` 是常驻的看门人，后面跟的是引擎自己的参数：

```
python -m agentcut supervise -- api --port 8765 --data-dir data --media-root D:\media \
    --output-dir D:\out --watch-dir D:\drop --callback-url https://hook.example/agentcut
```

- **崩了就拉**：子进程退出码非 0（或被杀）就按 1 / 2 / 5 / 30 秒退避重拉，**不设上限**；
  60 秒内崩三次以上按最长那一档等——继续试，不是放弃。桌面外壳那条路第 5 次之后永久放弃，
  而且前提是「有人坐在这台机器前」；服务器上没有那个人。
- **不留孤儿**：子进程带 `--exit-with-parent <看门人 PID>`，看门人没了它自己走。
- **账在数据目录**：`supervisor.json`（state / restarts / last_exit_code / last_uptime_seconds /
  next_delay_seconds / storm）、`server.log`（子进程输出，崩之前那几行是唯一现场）。
  `GET /v1/metrics` 的 `supervisor` 那一格就是那份现读；没人看门时是 `configured: false`。
- **干净收摊**：往数据目录放一个 `supervisor.stop` 文件——看门人停子进程、写 `stopped`、退出 0。
  用文件而不是信号：Windows 上给别的进程发 Ctrl-C 没有可靠写法，而「放一个文件」在服务、
  计划任务与容器里都成立。
- **和前面几档的关系**：宕机期间丢进 `--watch-dir` 的素材，起来之后会被补收（账是活的）；
  宕机前欠着的回执，起来之后接着投（次数接着数）；被 SIGKILL 留下的陈旧 `engine.lock`，
  新的那一台接得回来——这三条门禁里都是真杀真等量出来的。

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
python -m agentcut tokens
python -m agentcut tokens --revoke-label studio-a
```

第二行什么都不给就是列出全部——没有单独一支「列令牌」的旗标，`python -m agentcut tokens` 本身就是那张表。

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

## 事件出口：渲完了引擎自己来说

调用方不必再守着 `GET /v1/jobs/{id}` 轮询——`--callback-url` 一给，作业走到终态
（`succeeded` / `failed` / `cancelled`）时引擎就 POST 一份回执过来。回执头三样：
`X-AgentCut-Event: agentcut.job.terminal`、`X-AgentCut-Signature: sha256=<整条 HMAC-SHA256>`
（密钥就是这台引擎的令牌，接收端拿同一枚重算，就能判断正文有没有被改过）、
`X-AgentCut-Delivery: <job_id>-<第几次尝试>`。正文里只有引擎**量到过**的东西：哪一单、
哪一档、什么状态、失败码、落地文件叫什么与多大、有没有复检过、渲染耗时与帧数、哪一台投的。
`request_id` 不在回执里——那一格属于提交时那本凭据，不属于作业，对账请用 `job_id`。

三条行为值得记住：

- **欠账不会被弄丢。** 出站记录与作业状态写在**同一个事务**里，进程正好死在两步之间也不会
  出现「库里成功了但没人知道」；A 那台欠着被杀掉，B 那台在同一个数据目录上接着补投，
  投递次数从上一次接着数。
- **投不出去会认栽，而且说得出为什么。** `pending` / `delivered` / `gave_up` 三态在
  `GET /v1/callbacks` 与 `GET /v1/metrics` 的 `callbacks` 那一格里现算，`last_error` 存的是
  `HTTP 500` 还是 `URLError: …`，不用去翻日志。
- **没配地址就没有这一面。** `callbacks.configured` 是 `false`：表不建、线程不起，
  默认行为与 1.322 完全一致。

地址写错就停在自己门前：`file:`、`ftp:`、`user:pass@host` 这几种都不起（带账号的那一串会
原样进台账与读数，等于把一枚口令发到别人看得见的地方）。这一手与「非本机绑定要加密」
「非本机绑定要令牌」是三道独立的门，**同一趟都过不去时那一句把它们一起点名**。

判它的是 `tests/callback_check.py`：真引擎、真渲染、真取消、真重启；接收端先 503 两次再 200
（投到第三次才成）、一直 500 就按上限认栽、签名用这台引擎的令牌重算验得回而篡改过的验不过，
外加一腿把 `_save()` 炸在提交那一刻——作业行与那条欠账一起回滚，才算「事务性」三个字。

## 素材入口：把片子丢进目录，引擎自己收

`--watch-dir` 一给（可重复），引擎就盯着那个目录——子目录一并扫，一轮到底：新落地的文件被探出
时长/画幅/声轨、建好缩略图与波形、记进媒体库并交回一个能直接用的 `probe_id`。**盯的目录自动成为
一个媒体根**，不用两边各写一遍。读数在 `GET /v1/watch`（MCP `agent_watch`）与 `/v1/metrics` 的
`watch` 那一格。

| 旗标 | 说什么 |
|---|---|
| `--watch-dir`（可重复） | 盯哪个目录收素材；必须是**存在的绝对目录**，否则引擎不起 |
| `--watch-interval` | 多久扫一轮，默认 2 秒 |
| `--watch-grace` | 落地后再静默多久才收，默认 2 秒 |

两道闸缺一不可：

- **两趟稳定观察。** 第一次看见只记一笔观察（`pending`）；大小或时间戳一变就重新等。半拷的文件
  就是在这一步被挡下来的——外部 watcher 最常犯的错正是「看到文件就收」。
- **静默期。** 两趟观察一致还不够：mtime 一直在刷新说明还在写。过完 `--watch-grace` 才真收。

每一手的账都在表里：`pending`（在等）/ `imported`（收了，带 `probe_id`）/ `failed`（按名字拒，
`MEDIA_EMPTY`、探测不过之类）。不支持的后缀只计数（`ignored_unsupported`）不记失败——旁挂的
`.srt` 不是错误。文件名就是中文、带空格、带方括号与 `#` 也照收（门禁里就是这么丢的：它走的还是
rglob → 记账 → 探测那一条路）。为什么用轮询而不用目录事件：事件订阅在无人值守的机器上会因句柄、
共享权限与休眠悄悄丢通知，而「丢了通知」的现场表现就是素材没进来，那是最难查的一类缺件。
扫描成本有读数：1000 个已收过的文件一趟 **76 ms**（整趟共用一条 sqlite 连接；一文件一条连接的
旧写法在同一台机器上是 445 ms）。

**盯的目录不许罩住引擎自己写东西的地方。** watch 是递归扫的，交付件（mp4/mov）与代理（也是
mp4）都落在可收的扩展名里——`--watch-dir` 等于 `--output-dir`、或者是它的父目录时，引擎会把
自己刚写出来的东西当新素材再收一遍，代理再生成代理，越滚越大，直到撞上输出盘底线。实测过：
watch 目录＝输出目录，一刀配方跑完，那份 46 KB 的交付件当场被记成 `imported`。所以这一手与
「目录不存在」「相对路径」「给的是文件」并列在启动的门上，`--cache-dir` 同理；与写出目录**同级**
的目录照常起得来（门禁里正反两腿都有）。

判它的是 `tests/watchfolder_check.py`（34 格）：真引擎真目录真丢文件；HTTP 那一路导入与 watch
这一路对同一份文件必须给出**同一件东西**（指纹、时长、画幅、缩略图数一致）；A 收过的 B 不许重收、
A 没看见的 B 要补上；配错目录（不存在/相对路径/是文件/罩住写出目录）不起，且与「非本机要加密」
「非本机要令牌」在同一句话里一起点名；中点放一份中文名、带空格与方括号的素材，必须走通同一条
路；1000 个已收过的文件一趟扫描给得出毫秒读数。十一把变异刀逐条红在自家那一句上（静默期、去重、
媒体根、地址判据、线程不起、自喂那道门的恒真与恒假两个方向、退回一文件一连接、跳过非 ASCII
文件名、MCP 那只工具交回空壳，以及 1.323 那把「新门不许把老门演没了」现在同时红三档）。

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

接入清单——一台没人盯的机器，最小五步：

1. 起引擎：`--host` / `--port`，身份用 `AGENTCUT_TOKEN` 或 `--token-file` 交进来（命令行不接受直接
   写在参数里的令牌）；跨机还要 `--tls-cert` 与 `--tls-key`，否则它不起。
2. `--watch-dir` 指到素材真正落地的目录（子目录一并收），第一段路不用再写外部脚本。
3. 编排器或直接拿 HTTP 基址 + 令牌，或把 `python -m agentcut mcp` 当 stdio 服务器起。
4. 一条片子一刀跑完：`recipe_run`（`POST /v1/agent/recipes/{recipe_id}/run`），带 `request_id` 幂等。
5. `--callback-url` 给一个收得到 POST 的地址，渲完了引擎自己把终态推过来，签名可验。

每一步都有读数可核：`/v1/watch`（收了几个、为什么没收）、`/v1/callbacks`（投了几次、最后一次错在
哪里）、`/v1/metrics`（队列、槽、额度、输出盘）。走界面导入或 `POST /v1/media/import` 的那条路，
仍然需要 `--media-root` 指到素材真的在那里的根；`--watch-dir` 那个目录是引擎自己并进媒体根的。

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
| 无人值守 | 进程级已给（`agentcut supervise`，见上一节）。**没有**的是：开机自启/装成系统服务（交给计划任务、服务包装器或容器编排的 `restart: always`），也没有多机 HA——一台数据目录只服一台引擎这条不变 |
| 传输加密 | 引擎侧已给（`--tls-cert/--tls-key`，见上一节）。**没有**的是：桌面外壳附到一台 TLS 引擎上（会停下并说明），以及证书自动轮转（交给代理或运维的定时重启） |
| 多租户与权限模型 | 只有「具名令牌 + read/write 作用域」，没有工程级 ACL、没有用户目录接入 |
| 目录监听入库 | 已给（见「素材入口」那一节）。还没做的是：写完与否只看大小与 mtime 两个读数，写入端若提前盖上源文件的时间戳，理论上可能在写完前就被收；文件被删掉之后，台账里那一行不回收 |
| 语音模型许可文本 | `THIRD-PARTY.md` 里那一格如实写着模型目录里**没有**许可文件，商用再分发前要补 |
| 界面里的许可入口 | 这一页与 `THIRD-PARTY.md` 在仓库与包里，界面上还没有读它的位置 |

## 一键冒烟

`python scripts/enterprise_smoke.py` 在一台目标机上做 go/no-go：引擎起得起、租约守得住、
真素材一刀配方跑到交付、`deliver_verify` 逐条过、台账写得出那一行、`/v1/metrics` 读得出数、
只读令牌被拒得对、吊销之后立刻不认、输出盘底线拒得对、事件出口没配就说得出没配而配错就起不来、
丢进 `--watch-dir` 的那一份被这台引擎自己收了且从正常读路径读得回来。它交回一张表与一个退出码，
判它的门禁是 `tests/enterprise_smoke_check.py`（腿数与圈号钉在那一档：删一条腿就红在那里）。

## 三方许可

随包发出去的每一样三方东西、它们的许可与**判定依据**（两支媒体程序是现场跑 `-buildconf`
判的，不是抄的）、以及「装机那份与构建输入是不是同一件东西」的逐字节核验，都在
`THIRD-PARTY.md`。生成器是 `scripts/thirdparty.py`，门禁是 `tests/thirdparty_check.py`。
