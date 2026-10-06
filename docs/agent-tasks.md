# 可直接交给其他 Agent 的任务书

> 状态更新（2026-10-05）：A、B、D 与 E 的 Windows 部分已有真实实现；C 已完成基础关键帧、变换、淡入淡出、变速、文字字幕、基础调色、镜头转场、多选成组剪辑、持久组合、手动音画链接与联动分割/修剪。复杂合成与高级调色尚未完成。
> 当前事实以 README、capabilities 与 tests/ 中的可运行验收为准。下面保留原任务书作为后续参考，不代表要求重做已完成模块。

## 分工与依赖

| 任务 | 负责范围 | 主要新文件 | 依赖与验收 |
|---|---|---|---|
| A 素材与探测 | 真实文件、源流信息、受信导入 | src/agentcut/media.py | 无前置；真实音视频与坏文件 |
| B 渲染与任务 | 固定快照、编译计划、直切输出 | render.py、jobs.py | A；导出长度、声画同步、取消和重启 |
| C 专业时间线 | 关键帧与具体效果 | animation.py、effects.py | 基于当前契约；渲染对接 B |
| D 桌面审阅 | React 界面与桌面生命周期 | desktop/ | 当前 HTTP；真实预览依赖 A/B |
| E 工程验收 | 打包、兼容、性能、恢复 | tests/、scripts/、CI 配置 | 集成各模块；真实媒体与目标平台 |

共享 `contracts.py`、`projects.py`、`http_api.py` 的跨模块修改由契约协调者统一合并。
每个 Agent 先提交对应接口补丁和验收样例，再写模块实现；不要同时重写主入口或统一模型。
顶层目录只在模块开始实现时创建；没有空目录和假实现。

## 任务 A：受信素材库与媒体探测

复制以下内容给素材 Agent：

> 在这个 AgentCut 仓库实现真实媒体的受信导入与 ffprobe 探测。先读 AGENTS.md、架构和 API 约定。现有 asset.register 仅登记不可信元数据，不能把 reference 直接交给 FFmpeg。保留 Python 核心和统一 HTTP 状态入口。
>
> 新增 media.py，负责配置的导入根目录、真实路径解析、媒体身份、源文件记录、时长、流类型、源 timebase、视频帧率/VFR 标记、音频采样率。识别一个视频中的独立音频流，避免默认丢音。使用 subprocess 参数列表，不使用 shell。初版只支持本地文件，不加入云素材下载。
>
> 源文件记录由服务产生，客户端不能声明 verified=true。文件路径保持在受控目录内，处理符号链接、缺失文件和源文件被替换。哈希按块读取，禁止将整部视频读入内存。探测发生在编辑事务外，成功后再登记可使用的媒体记录及 asset 身份。
>
> 接口提案：POST /v1/projects/{id}/media/import 请求包含 request_id、expected_revision、相对于授权根目录的路径和流选择；结果包含 Asset、MediaInfo、提交后的项目 revision。耗时工作不要长期占用 SQLite 写锁；发生并发冲突时，缓存探测结果可复用，但项目仍须重新提交。接口细节先交契约协调者确认合并。
>
> 补充对应 MCP 工具；thumbnail/waveform/proxy 可后续逐项实现，未实现不声明可用。不要修改 timeline 规则来掩盖源媒体时基问题。
>
> 验收真实视频、音频、图片、VFR 样例、坏文件、缺失源、越界路径、含空格与中文的路径。验证导入重试不会重复登记，冲突不产生半完成项目。更新文档并运行现有自检。

## 任务 B：固定快照渲染与持久化任务

复制以下内容给渲染 Agent：

> 在 AgentCut 实现第一条真实直切视频导出链。先读架构、API 约定和素材模块提供的 MediaInfo。输入是固定 project_id + revision，不能渲染过程中跟随最新时间线。
>
> 新增 render.py 的纯编译函数，将 Project 快照编译为 RenderPlan。初版明确支持哪些轨道、媒体类型、空隙和音频组合；不支持的时间线返回 UNSUPPORTED_RENDER_FEATURE，不能静默忽略轨道、效果或音频。先完成单视频轨道直切，再按验收增加音频混合。不要通过修改原始素材完成剪辑。
>
> 新增 jobs.py 的 SQLite 持久化任务和独立 worker 进程。任务记录保存 request_id、固定 revision、受控 preset、状态、进度、错误和输出身份。API 只排队，不执行长时渲染；编辑事务不持有渲染进程。
>
> 接口提案：POST /v1/projects/{id}/renders 接收 request_id、revision、preset 和授权输出目标；GET /v1/jobs/{job_id} 查询；POST /v1/jobs/{job_id}/cancel 幂等取消。状态 queued/running/succeeded/failed/cancelled。每个请求重试返回同一 job。同步新增 MCP render_start/job_get/job_cancel。先提交契约补丁给协调者。
>
> 初版使用受控 FFmpeg subprocess 参数，禁止任意命令/任意网络协议。拒绝未验证媒体。用临时文件输出，验证成功后原子发布；不要覆盖未经请求指定的已有文件。取消要终止进程树并清理临时输出；worker 崩溃后任务可恢复或明确转失败。
>
> 验收生成 2 段可辨认的测试媒体，拼接顺序、长度、帧率和音轨正确；用 ffprobe 校验输出，并人工或自动检查画面和声画同步。渲染期间修改项目，输出仍对应原 revision。验证重复请求、取消、缺失源、磁盘写失败和进程重启。只有实际可用后设 capabilities.render=true。

## 任务 C：关键帧与具体效果

复制以下内容给时间线 Agent：

> 在 AgentCut 增加第一批关键帧能力：transform.position、scale、rotation、opacity 与 audio.gain。先读 contracts.py、timeline.py、架构的时间映射规则；保持整数 tick 和批命令原子性。
>
> 新增 animation.py 的纯关键帧采样函数。数据绑定 clip_id + property，关键帧时间相对 clip 起点。为属性值、范围、维度和插值类型提供严格 schema；先支持 hold/linear，不构建任意脚本效果或动态插件系统。
>
> 契约提案：keyframe.set 和 keyframe.remove 命令；新属性默认值保证无关键帧的旧工程能读取。先把新增 schema、capabilities 和数据库历史兼容方案交协调者合并。不要令已有快照和去重回执无法读取。
>
> 明确定义同一属性同一时刻重复点、首尾采样、超出 clip 范围、移动/修剪/分割的行为。分割后的左右关键帧应保持输出连续：右侧重定位时间，并在切点插入所需边界样本；不能只把列表复制到两半。基于旧语义的回执仍可重放。
>
> RenderPlan 显式携带采样/效果节点，与渲染 Agent 对齐，预览与导出共用同一纯函数。禁止把关键帧采样另写在 UI 或 FFmpeg 拼接字符串里。渲染不支持的新效果应显式报错。
>
> 验收边界插值、图片片段、分割连续性、修剪、非法参数、历史恢复与重复提交；运行全套已有自检。变速、转场、嵌套序列另开范围，不能靠放宽同轨重叠约束冒充支持。

## 任务 D：跨平台桌面审阅界面

复制以下内容给桌面 Agent：

> 为 AgentCut 实现桌面审阅客户端。核心保持 Python，界面只通过 HTTP API 读写项目，禁止直接读写 SQLite。先基于 /v1/contracts 与 OpenAPI 实现 React/TypeScript 界面；桌面壳可选 Electron 或 Tauri，选择前给出最小打包方案，不改剪辑引擎契约。
>
> 首版包括项目列表、素材面板、时间线轨道、片段选中与调整、命令预演/提交、历史恢复以及 Agent 操作结果查看。人工操作转换为已有批命令。显示真实 revision；409 时刷新并让用户重试，不静默覆盖。Token 不写进前端 bundle 或日志。
>
> 先集成真实 API。媒体/预览未实现时明确显示不可用，不能使用随机演示帧冒充真实剪辑效果。接入媒体模块后再实现播放器和代理缓存；预览遵循 RenderPlan，不自行定义关键帧/转场算法。
>
> 桌面进程负责启动 Python API、等待健康检查、传递随机凭证、关闭 worker。开发和打包分别验证；壳不暴露任意 shell 执行接口。首版可轮询状态，不建设投机 WebSocket 总线。
>
> 验收鼠标和键盘操作、焦点和可读标签、不同缩放比例、中文路径、冲突、服务退出/重启及缺失素材。提交时说明界面和底层真实实现的范围，更新启动说明。

## 任务 E：集成验收与分发

复制以下内容给集成 Agent：

> 对 AgentCut 集成结果做可复现验收和分发。保持现有 tests/self_check.py 为最小公共检查，避免只验证 UI 或写与实现一模一样的测试。先跑 HTTP + 官方 MCP 客户端，再验真实媒体与桌面生命周期。
>
> 增加 Windows/macOS/Linux 的可复现依赖和打包流程，锁定 FFmpeg/媒体后端版本。说明不同编解码器和分发许可的边界，不默认能重分发所有 codec。无需引入云部署或复杂 CI 平台。
>
> 验证 schema 迁移前备份、旧工程/历史/回执读取、服务崩溃后的事务恢复、worker 中断状态和输出原子性。SQLite WAL 备份使用 backup API，并验证恢复可读。
>
> 性能使用代表性大工程与长素材，记录 clip/track 数、编辑延迟、磁盘增长、代理成本、预览帧率、导出耗时和峰值内存。发现瓶颈再提出索引、结构共享、缓存或数据库替换，不先搭新架构。
>
> 交付包含可运行包、操作说明、实际支持格式/效果列表和复现命令；所有未实现能力在 capabilities 中保持 false。
