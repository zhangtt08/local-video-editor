# AgentCut 协作规则

本项目已交付成品：Python 剪辑引擎 + HTTP/MCP 接口 + Windows 桌面客户端（无边框一体化窗口，见 `desktop/`）。
`README.md` 的「已完成」表是当前事实来源；关键帧、曲线变速与冻结帧、文字字幕、基础调色与串行调色节点（含节点强度 Mix 与每通道混合方式、并联分支节点）、镜头转场（1.59 起九种：叠化/淡黑/闪白 + 四向擦除 + 两种缩放，清单由 capabilities.transition_kinds 下发）、多选组剪辑、持久组合与手动音画链接、嵌套合成（1.74 起九个分析入口按 `sequence_id` 也进得了合成内部：去空白、整轨去空白、统一响度、整轨响度、自动闪避、画面稳定、遮罩跟踪、主体跟随、自动字幕）、自由路径遮罩、矩形/椭圆遮罩关键帧动画、路径遮罩关键帧动画（1.50 起按曲线整体搬动，形状与尺寸仍按画好的轮廓）、画面里拖遮罩即打关键帧（1.51：有曲线时向导仍在，拖框写当前播放头关键帧，拖路径顶点只改轮廓；1.52：向导还按曲线的尺寸一起缩放，角柄就在看到的边缘上；1.53：轮廓本身可整条拖动，有中心曲线时写成播放头关键帧；1.54：双击加点插在离得最近的那条边上并按贝塞尔精确分裂，不再往顶点列表末尾追加；1.55：路径顶点上限由 `capabilities.mask_vertex_limit` 下发，界面不再自带数字；1.56：选中顶点后画面给出删除/角点/平滑三个操作，到上限时说明原因）、遮罩跟踪（单目标平移与缩放，短遮挡按匀速续跟；路径遮罩只跟平移；1.72 起 `merge` 默认只重写本次窗口的点，跟丢之后可以把遮罩挪回主体上「接着跟」，前面跟好的路径不再被整条抹掉）、静音检测与去空白（单片段与整轨）、响度表与统一响度（单片段与整轨）、自动语音字幕（1.61：本地 vosk 模型听写，走 captions.import 落轨，内容寻址 id 防叠轨，replace_track_id 原位替换；合成里的听写已用真实语音与真实导出端到端量过，见 `tests/captions_comp_check.py`）、时间线标记与按标记分割、源画面划动与左右滑移、色彩空间转换节点、自动闪避（口播压配乐，写成音量关键帧）、分析类拒绝点名（1.75：九条分析路由的每条拒绝都带 code、可读句子与非空 details，NOT_FOUND 必点片段/轨道/合成/素材，拒绝不涨 revision，dry 与提交同答）、读路由同样点名（1.76：15 条 GET 的 404/410 各带回它收到的 id，未知的工程 id 不再回 200 空列表）、操作类路由同样点名（1.77：导入失败给 path/suffix/媒体夹，`.cube` 被拒给行号与行数）、片段柔焦（1.64：`effects.blur` 是画面高的比例，同一个半径同时喂 FFmpeg `gblur=…:steps=6` 与浏览器 `filter: blur(…cqh)`，配遮罩即打码/背景虚化）、片段降噪（1.78：`effects.denoise` 0–24 dB 一个旋钮，导出加 `afftdn=nr=<db>:nf=-30`，浏览器预览不降噪、界面明说）、片段清晰（1.65：`effects.sharpen` + `effects.sharpen_radius`，两端跑同一条 unsharp 式子 `源 + 量×(源 − 高斯)`，导出用 `split`+`gblur=…:planes=7`+`blend=c*_expr='clip(…,0,255)'`、浏览器用 `feGaussianBlur`+`feComposite arithmetic`，半径与柔焦共用同一条 1–64 px 实测带）、画面稳定（1.66：`POST /v1/projects/{id}/clips/{id}/stabilize` 与 MCP 的 `clip_stabilize`，四个画面锚点的互相关中位数 = 相机位移，减去滑动平均后反向写成 `x`/`y`/`scale` 关键帧，缩放按 `1+2·最大抵消` 盖边、`max_crop` 夹住并如实报告，`strength=0` 一个关键帧都不写；图超过 12 KB 时 `-filter_complex` 自动改走 `-filter_complex_script`；1.67 起同一次测量还用四锚点的 Arun 刚体拟合出相机滚动，反向写成 `rotation` 并按 `1+2·平移+弧度·画幅比` 盖边，低于 0.25°（一个锚点像素的量化）的死区不写；1.68 起对已经带 `x`/`y`/`rotation`/`scale` 关键帧的片段再稳定会被点名拒绝 （`STABILIZE_CONFLICT`，details 点名是哪几条曲线），因为抵消是叠加的，界面按同一条判断先把按钮灰掉并写明出路；1.69 起稳定是片段的一处状态（`Clip.stabilization` 记下强度/点数/抵消量/放大，与曲线同一条批次落库），带记录的片段再按一次是从静态变换**重算并替换**（换强度只要一次点击，同 id 同载荷重新命中回执），强度 0 就是取消稳定，带记录期间 `clip.speed`/`clip.speed_curve` 与 `clip.reframe`（1.70：重构图整条改写同三条曲线）都以 `STABILIZE_LOCKED` 拒绝——抵消是一帧源画面对一个关键帧量的，这是 1.68 那条守卫的镜像洞；1.71 起这条记录是可作废的——`apply_commands` 收尾时若那四条曲线一条不剩就把记录置空，界面与两把锁随之松开）、标记拖拽移动与改名换色、交付画幅预设与三种适配（补边/裁切/拉伸）、时间线入出点区间与区间导出（裁剪发生在混音与母带处理之后）、四点剪辑（素材入出点 + 时间线入出点四个整数一次解算成一条命令，源长则裁尾、源短则整数百分比改速）、交付方案持久化（预设+适配+范围+文件名存成工程状态 `Project.recipes`，v12）、安全区参考线（`settings.safe_area` 三态，内缩数字只由 `capabilities.safe_area_insets` 下发，纯显示不改导出）、主体跟随重构图（按渲染时钟采样跟好的遮罩路径，换算成 `x`/`y`/`scale` 三条关键帧并在片段的关键帧预算内自适应补点，一个批次一个 revision，跟不到时如实报告夹住的点数与实测最大偏离；1.73 起稳定的关键帧预算也按片段剩余空间自适应抽稀并说明（不再回空的 `PROJECT_LIMIT`））、调色节点图（链子画成输入→节点卡→输出的连线图，拖卡片改顺序仍只写 `clip.color`，无新状态）、批量交付（一次点击多个画幅，整批先编译通过才入队）、交付格式（1.57：mp4/H.264 之外新增 mp4/HEVC+hvc1、webm/VP9+Opus、mov/ProRes 422 HQ+24 位 PCM，容器/编码/采样格式与文件名后缀都由预设一处决定，采样格式走完整条画面链）、纯音频交付（1.58：mp3/wav/flac 三条预设，`codec=null` 让画面链整段不编译，无声时间线按名字拒绝）、交付前复检（1.60：FFmpeg 退出 0 之后，任务用**同一个 FFmpeg 旁边**的 ffprobe 重开产物文件，比对容器、两路流是否齐全、时长（容差 `max(0.150 秒, 两帧)`）并把结尾 0.5 秒解码一遍，不合格就销毁候选文件、以 `OUTPUT_INVALID` 失败且最终名一次都不出现；旁边没有 ffprobe 时照常出货但 `output_checked=false` 并在消息与界面明说未经复检）、母带响度目标与母带限制器（探测渲染量整片混音后写母带增益，真峰值交给 alimiter）、代理回放与缓存配额已实现（1.44 起配额覆盖整个派生缓存：缩略图 + 波形 + 代理，按最久未用整项淘汰、可 dry_run 预演、缺失自动重建）；路径遮罩的顶点与形状动画、多目标与长时遮挡跟踪、柔焦与清晰的逐帧动画（`gblur` 没有逐帧 sigma、只有 `enable` 开关窗，硬给就是导出阶梯 vs 预览平滑，所以两个空间旋钮都不打关键帧）、色彩节点图的分层与连线（亮度曲线、3D LUT、色域矩阵与色彩管理）仍待实现（1D `.cube` LUT 已于 1.62 实现：文件只由引擎 `parse_1d_cube` 解析一次，界面「+LUT」与 Agent 的 `POST /v1/lut/parse`、`lut_parse` 是同一条路，链子上限走 `capabilities.grade_limits`，超过 1024 行的表重采样并在回复里写 `resampled_from`；1.63 起文字层有字体（本机实际装着的face 由 `capabilities.text_fonts` 下发，缺字体按 `FONT_UNAVAILABLE` 拒绝）、横排对齐、描边、硬阴影、垫子颜色与浓度、行距，全部按「字号的百分之几」同一组数喂 drawtext 与 CSS，drawtext 画不出模糊所以界面也不给这一档），不能声称全面替代 AE / 剪映 / 达芬奇。

## 开始前

- 若当前会话安装了 `prompt-engineering-patterns`，先使用该技能，在内部整理执行范围，不扩大用户任务。
- 阅读 `README.md`、`docs/architecture.md`、`docs/api.md`，再读自己的 `docs/agent-tasks.md` 任务书。
- 追踪相关命令的模型、reducer、事务、HTTP、MCP 调用链后再修改。

## 必须保留的约束

- 所有入口使用同一命令语义；MCP 与界面通过 HTTP 服务修改项目。
- 不在客户端、HTTP controller 或 MCP adapter 另写剪辑规则。
- 项目采用整数 tick；不得用浮点秒数保存时间。序列帧率为 numerator/denominator。
- 任何写操作需要 request_id；编辑必须检查 expected_revision。
- 同一事务持久化项目状态、历史和去重回执；禁止成功返回后才异步保存。
- dry-run 不产生持久化变更。恢复必须生成新 revision。
- 新增命令需同步契约、reducer、capabilities、文档和验收；MCP 从契约生成 schema。
- 不直接修改已提交的历史快照；schema 变化必须设计兼容读取或迁移。
- 素材 reference 是不可信元数据。媒体引擎必须使用由服务验证的文件记录。
- 不把任意 shell 命令、FFmpeg 参数、网络 URL 作为 Agent 工具暴露。
- HTTP 只监听回环地址；需要远程访问时另做明确的认证、授权和部署设计。

## 分工

- 契约协调者负责 `contracts.py`、`projects.py`、`http_api.py` 的跨模块变更合并。
- 模块 Agent 先在任务书中约定接口，再实现模块；共享文件修改写成最小补丁交协调者合并。
- 一个行为只有一处权威实现；先重用已有代码，不创建通用插件框架、第二套事件总线或投机接口。
- 当前 SQLite facade 允许直接使用 stdlib sqlite3；出现第二种存储实现时再提取 port。
- 验收用现有自检入口。新增业务需要最小可运行检查，无需引入测试框架。

## 完成标准

运行 `uv run ruff check src tests examples`、`uv run ruff format --check src tests examples` 和 `uv run python tests/self_check.py`。
`self_check.py` 只覆盖它自己拉起的 HTTP/MCP 链路，逐功能的验收在 `tests/*_check.py` 里；一并运行 `uv run python tests/suite_check.py`（可加名字子串只跑相关的几个，例如 `tests/suite_check.py grade marks`），任一子检查失败该入口以非零码退出。渲染层自己的 TypeScript 检查（`tests/desktop_*_check.ts`、`tests/scope_check.ts`）由 `tests/desktop_ts_check.py` 用 desktop 自带的 esbuild + node 跑，因此也在这个入口里——「门禁全绿」不再依赖有人手动去跑壳层检查。
涉及媒体输出时另验真实媒体、流元数据及声画同步。
交付说明须列明实际完成、验证证据及未完成的边界；功能未实现时能力接口不得声明可用。
