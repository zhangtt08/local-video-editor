# AgentCut

**供人和 Agent 共用的本地剪辑软件。** Python 剪辑引擎 + HTTP/MCP 接口 + 桌面客户端（Windows exe，无边框一体化窗口）。

你和 AI Agent 改的是同一条时间线：界面里的每个动作，最后都变成和 Agent 完全相同的批命令，走同一个服务、同一个数据库。
没有第二套规则，也没有「只有界面能做、Agent 不能做」的操作。

## 已完成（本次交付）

| 能力 | 状态 | 证据 |
|---|---|---|
| 项目/时间线批命令、原子事务、幂等回执、乐观版本、dry-run | 已实现 | `tests/self_check.py` |
| 历史快照与恢复（恢复生成新版本，版本只进不退） | 已实现 | 同上 |
| 真实素材导入与 FFmpeg 探测（含中文/空格路径、越界拒绝、符号链接） | 已实现 | `tests/media_check.py` |
| 缩略图、波形、签名预览流 | 已实现 | 同上，界面直接播放源文件区间 |
| 固定 revision 渲染 + 持久化任务队列 + 取消 | 已实现 | 同上（声画同步由 ffprobe 校验输出时长） |
| 桌面客户端：素材库、真实预览、拖拽/修剪/分割、批次预演、导出、历史、Agent 面板 | 已实现 | `desktop/`，构建产物见下文 |
| 深色工作台、可调整面板、素材/合成双监视器、逐帧与编辑点定位、磁吸、锁轨 | 已实现 | 桌面实际操作验收 |
| 位置、缩放、旋转、透明度、音量关键帧；线性/保持/缓入缓出/可编辑贝塞尔 | 已实现 | `tests/editing_check.py`；真实像素与分割/修剪连续性 |
| 可视数值曲线：Shift 多选/框选、整体移动/删除、拖点改时间/数值、双击加点、缩放、撤销、批次预演 | 已实现 | `tests/curve_check.py` / `tests/keygroups_check.py`、真实 HTTP/MCP 与 1040×660 界面操作；SVG 与渲染共享插值 |
| 0.25–4 倍速、保留音高、同轨涟漪调整 | 已实现 | 同上；导出长度与 440 Hz 音频检查 |
| 曝光、对比度、饱和度 | 已实现 | 同上；灰阶像素与原生 CSS 合成预览 |
| 文字图层、SRT 导入/复制、透明度与音量淡入淡出 | 已实现 | 同上；中文与特殊字符真实导出；界面 SRT 导入→成片 |
| 素材 I/O、目标轨道、插入/覆盖、跨轨同步插入 | 已实现 | `tests/placement_check.py`；HTTP/MCP、真实导出、界面操作与撤销 |
| 交叉溶解/淡黑、透明画中画转场、线性声音交叉淡化 | 已实现 | `tests/transition_check.py`；HTTP/MCP、真实像素与声音、界面预览与导出 |
| 多选/框选、成组移动/删除/分割、跨工程复制粘贴 | 已实现 | `tests/group_check.py`、`tests/desktop_editing_check.ts`；真实界面和原子撤销 |
| 矩形/椭圆遮罩、向内羽化、反转、画面拖动/缩放、候选画面预演 | 已实现 | `tests/mask_check.py`、HTTP/MCP 和实际界面 |
| 画面轨混合：正常/正片叠底/滤色/叠加/变暗/变亮/差值/排除 | 已实现 | `tests/blend_check.py`；遮罩/透明度/转场共同验证 |
| 连续属性/调色/文字编辑、候选检查器与只读候选动画采样 | 已实现 | `tests/patch_check.py`、HTTP/MCP、真实界面；单项移除与整体撤销 |
| 嵌套合成、内部编辑、复用、独立导出、跨工程复制 | 已实现 | `tests/nest_check.py`、`tests/desktop_nest_check.ts`；同工程画幅/帧率、最多 8 层 |
| 串行调色节点：每通道曲线（RGB/红/绿/蓝）、白平衡、RGB 增益（阴影/中间调/亮部）、节点强度 Mix（0–100% 与输入按比例混合） | 已实现 | `tests/grade_check.py`；同一张每通道表同时驱动 FFmpeg `lutrgb` 与浏览器 `feComponentTransfer`，真实 H.264 像素与预览表偏差 ≤1.5 LSB；半强度成片实测落在无调色与满强度之间且明显偏离满强度；工程 schema v10 |
| 时间线入出点区间与区间导出：标尺上一条带子两个可拖手柄（整帧量化、方向键微调、Alt+X 清除），导出面板选「整条时间线 / 入出点区间」 | 已实现 | `tests/marks_check.py`：契约拒绝半写、非整帧与倒序区间；`validate_timeline` 拒绝越过内容的出点（`INVALID_MARKS`、不烧 revision）；渲染图在**混音与母带处理之后**才 `trim=start_frame=60:end_frame=120` + `atrim=start=2:end=4`，所以区间成片与整片是同一次混音而不是重算；真实导出实测整片 6.000 秒、区间 2.000 秒，区间文件首帧是第二段（绿）、音高 879 Hz（整片同点是 439 Hz），且区间第 0.5 秒与整片第 2.5 秒逐通道差 **0 阶**；老载荷（不带 `range`）重放仍是同一张回执，改 `range` 得 409；批量交付两条一条整片一条区间各自落盘 6.000/2.000 秒；界面 I→O→拖手柄→Alt+X 逐笔 r1→r5，1040×660 无横向溢出 |
| 四点剪辑：素材入出点 + 时间线入出点四个整数一次算成一条 `clip.insert` / `clip.overwrite`——源长于目标窗口就裁掉多余的源，源短于窗口就按整数百分比改速铺满（音高不变），`fit=auto` 让这四个数自己决定用哪种；界面在素材监视器取 `I`/`O`、在标尺上取时间线区间，然后一键「四点→时间线区间（插入/覆盖）」 | 已实现 | `tests/fourpoint_check.py`：exact / trimmed / re-timed 三种解算都只产一条命令，12 组不可能的点位组合各自返回说清原因的 `INVALID_FOUR_POINT`（越界 `SOURCE_OUT_OF_BOUNDS`、未验证素材 `UNVERIFIED_ASSET`、轨别不匹配、非整帧、零长、百分比超出 25–400%）；`fit=auto` 由四个数自己决定裁尾还是变速；HTTP 侧 plan / `dry_run` 不写库、一次 apply 恰好一个 revision、同 `request_id` 重放不涨（clip id 由 request_id 派生，因此重试能对上自己的回执）、旧 revision 409、`restore` 是新 revision；真实导出：2 秒素材以 50% 铺满 4 秒窗口，成片 4.000 秒，第 0.5 秒红 / 第 3.5 秒绿，音高 439 Hz → 825 Hz（时间被拉长、音高保持）；裁尾那条覆盖 4–6 秒，最后一帧仍是绿，被裁掉的蓝色尾段从未出现在画面里。界面（1280×800 同源 iframe 真实点击）：素材监视器里 `入点 I` / `出点 O` 取 1–3 秒、时间线标尺取 1–3.03 秒，点「四点→时间线区间（插入）」→ r4→r5 一个 revision，提示条按引擎回包如实写「素材更短，按 98% 变速铺满 2.03 秒 · 读素材 1.99 秒」，库里落库的正是 `position=1.0s, duration=2.0333s, source_in=1.0s, speed_percent=98`，被插入点切开的原片段仍首尾相接 |
| 多目标跟踪与长时遮挡续跟（短遮挡只按匀速补一段、单目标，且不估计旋转）、色彩节点图的分层节点与连线视图（亮度曲线、LUT 导入、色域矩阵与色彩管理）、路径遮罩顶点动画、自动语音字幕 | **未实现** | 完整替代目标仍在推进，见 `docs/optimization.md` |
| 调色节点·并联分支：一个节点里 1–4 支各自从本节点输入重新算，节点输出取各支平均值（每支可换类型、带自己的强度与混合方式，停用一支等于该支直通） | 已实现 | `tests/grade_check.py` 的 parallel 三套：三支表与测试内**独立重写的平均算术**逐格比较最差 **0.434 阶**；同样两个操作串起来的表与并联差 **24.6 阶**（并联不是换名的串行），串行换序改变 **53.2 阶**而并联换支序逐位相同；+0.3/−0.3 色温两支平均在 234/256 档恒等，串行那一队中灰仍偏 **1.04 阶**；成片三档色带九通道对独立参考最大偏差 **2.01 阶**、与串行导出相差 **23.0 阶**；空支/5 支/嵌套并联 422 且不烧版本；变异验收（取最后一支代替均值）当场报 **55.44 阶** |
| 持久组合、音画链接、联动修剪/分割、独立编辑失步提示 | 已实现 | `tests/link_check.py`、真实 HTTP/MCP 与界面验收；工程 schema v5 |
| 涟漪修剪（Shift+拖边缘）与滚动剪辑（Ctrl+拖边缘） | 已实现 | `tests/roll_check.py`，重叠转场保宽，越界整笔拒绝 |
| 闪白转场（dip_white） | 已实现 | 预览与导出同样渲染白色三角包络，`tests/transition_check.py` |
| 拆分内嵌声音轨（clip.detach_audio） | 已实现 | `tests/detach_check.py`，真实 FFmpeg 响度对齐，链接保持同步 |
| 字幕顶/中/下对齐与半透明垫条 | 已实现 | `tests/style_check.py`，像素级导出验证，预览与导出同谱 |
| 工程打包导出/导入（zip 含全部素材） | 已实现 | `tests/bundle_check.py`，重新探测、原子恢复、同请求重试去重，支持空工程/锁轨 |
| 自由路径遮罩：钢笔顶点与贝塞尔控制柄、双击加点、键盘微调/删点、羽化与反转 | 已实现 | `tests/pathmask_check.py`；引擎把同一顶点表扫描成每像素覆盖 PNG 交给 FFmpeg alphamerge，浏览器用同源 SVG `<path>` + 同半径高斯；真实三角/反相/羽化像素与 HTTP/MCP/界面手势验收 |
| 矩形/椭圆遮罩关键帧：位置、宽、高随时间曲线运动，羽化边缘一起移动 | 已实现 | `tests/maskanim_check.py`；引擎把同一条曲线编译进 FFmpeg `geq` 的逐帧 alpha 表达式，浏览器只缩放引擎下发的单位遮罩图；实测白色源在 t=0.1/1.5/2.9 的明暗分界落在曲线给出的位置（亮侧 >200、暗侧 <40），羽化边缘在 0.45 处实测半透明（20–235）并随曲线平移；反相与路径遮罩的关键帧整笔拒绝并回滚 |
| 调色节点·混合方式（normal/正片叠底/滤色/叠加/变暗/变亮/差值/排除，与轨道合成同一套词汇） | 已实现 | `tests/grade_check.py` 的 blend 套：八种方式逐格与**独立写出的 W3C 可分混合公式**比较不超过 0.5 阶；恒等混合（如用提升曲线做变暗）与 `mix=0` 都不产生任何滤镜阶段；导出真实像素 [0,2,10,30,94,253] → 滤色 [61,66,77,105,178,252]、差值 [61,61,59,54,38,0]，两者必须不同；未知混合名被契约拒绝 |
| 调色节点·色彩空间转换（transfer：sRGB / Rec.709·BT.1886 / gamma1.8-2.4 / 线性） | 已实现 | `tests/grade_check.py` 的 transfer 套：七种空间的往返恒等于 0；表与**独立写出的发布函数**（sRGB 分段 + BT.1886 幂）逐格比较不超过 **0.5 个色阶**；导出真实像素六档暗带 [0,2,10,30,94,253] → [0,11,22,40,101,252]，对发布曲线 [0,12,23,42,102,253] 每档不超过 4 阶；mix=0 与 enabled=false 完全旁路；未知空间或缺少一侧空间的节点被契约拒绝 |
| 源画面划动与左右滑移（clip.slip / clip.slide） | 已实现 | `tests/slip_check.py`：划动只改素材起点、位置与时长一动不动；滑移让一侧相邻段让出 N 帧、另一侧收回 N 帧，整条轨总长不变（帧刻度逐条断言）；导出成片再回看像素——同一个时间秒在划动 2 秒前是红 (255,0,1)、之后是蓝 (0,1,255)，红/绿接缝从 2.0 秒精确移到 3.0 秒而片长仍是 5.990 秒；变速曲线、音频链接、相邻段不够长、素材头尾不够都被拒绝并给出原因 |
| 时间线标记与按标记分割（marker.set / marker.remove） | 已实现 | `tests/marker_check.py`，标尺上可见可点可删，磁吸把标记当边缘；标记只能落在当前内容之内（越界 `INVALID_MARKER`），同 id 是移动而不是新增，分割计划只产普通 `clip.split`：边缘/空隙上的标记不产生切点，切完的碎片严丝合缝铺满原片段（帧刻度精确断言），重开与撤销后标记仍在 |
| 标记拖拽移动、双击改名与五种颜色（落点走磁吸，一次提交 = 一个 revision） | 已实现 | `desktop/src/views/Timeline.tsx` 的 `MarkerEditor`；1280×800 同源 iframe 真实指针事件验收（拖动改 `at_ticks`、单击仍跳转、双击弹面板），命令与 Agent 用的 `marker.set` 完全同一条 |
| 交付画幅：竖屏 9:16 与方形 1:1 预设，导出时三种适配（完整保留补边 / 裁切填满 / 拉伸填满），选择记进渲染任务 | 已实现 | `tests/fit_check.py`；三种适配各自导出 1080×1920 实测：源里 60×60 的白方块落地宽高比 **contain 1.000、cover 0.998、stretch 0.317**，顶行均值 **0.0 / 64.0 / 65.8**（只有 contain 有黑边），源最左侧的白色竖条在 contain/stretch 出现在 x=0、在 cover 找不到（x=222 起才是方块）证明真的被裁掉；`fit` 进入渲染指纹（同 request_id 换 fit 得 409），未知适配名 422，任务读回 `fit=cover` |
| 批量交付：一次点击出多个画幅（最多 4 条，各自预设/适配/文件名），整批先编译通过才入队 | 已实现 | `tests/batch_check.py`；一次调用实测导出 1920×1080 + 1080×1920 + 1080×1080 三份；`dry_run` 批次不排队不落盘；重放同 request_id 返回同样三个任务、任务表仍是 3 条；第二条预设名写错 → 422 且任务表**仍是 3 条**（变异测试：去掉预编译后当场报多出 `横版-2.mp4` 的部分排队）；同名两条、5 条一批、`sub/dir.mp4`、无扩展名、未知适配名全部被契约拒绝 |
| 母带响度目标：一次 64×36 探测渲染量出整片真实混音，写一个母带增益对齐 -14 LUFS（真峰值不超 -1 dBTP） | 已实现 | `tests/master_check.py`；探测渲染量到 **-25.9 LUFS**，同一条时间线的完整导出实测 **-25.9 LUFS（相差 0.00 LU）**；点一次对齐后导出实测 **-20.0 LUFS** 对 -20.0 目标（真峰值 -18.5 dBTP）；到不了的目标如实报 `limited_by=gain_range` 只到 -13.86 LUFS；已对齐时再点报 422「already sits」；撤销回到 1.0；探测文件用完即删 |
| 母带限制器：真峰值由 FFmpeg `alimiter`（attack 5 ms / release 80 ms，关掉自动电平）守住，增益不再被峰值上限压住 | 已实现 | `tests/limiter_check.py`；同一条 -3.7 LUFS / 峰值 -2.2 dBTP 的素材，目标 -6 LUFS + 上限 -7 dBTP：**不开限制器**增益被压到 0.5754、只到 -8.5 LUFS（`limited_by=ceiling`）；**开限制器**增益 0.7674 不被压，导出实测 **-7.7 LUFS / 峰值 -6.4 dBTP**（峰值比未处理低 4.2 dB，比被压的方案响 0.8 LU）；端点写入后再探一次，`after` 与真实导出相差 ≤0.3 LU/dB；`ceiling_dbtp=-20` 越界 422；撤销把限制器、上限与母带增益一起还原 |
| 自动闪避（配乐让口播）：用与「去空白」同一个静音扫描找出说话区间，写成音量关键帧 | 已实现 | `tests/duck_check.py`；包络与测试内**独立重写的梯形函数**逐点比较误差 0.0e+00，断点只落在整帧上（4 秒 2 段说话 = 12 个断点，不是 120 个）；说话区间实测精确等于合成的 [(1.0, 2.5), (3.5, 4.5)] 秒；**导出实测**：同一条配乐在无闪避成片里 -13.5 dB，闪避后说话段 -25.5 dB、停顿段 -13.5 dB，12.00 dB 之差对 12.0 dB 请求；再点一次是替换不是叠加（20 dB 重跑后最低点 0.1、无重复时间点）；替换 `gain` 不动 `opacity` 的曲线；四种非法替换（时间倒序、混第二种属性、增益 9.0、空表）全部 422 且不写库；变异测试：把释放斜坡写死 → 门禁止报 0.7239，把「替换」改成「追加」→ 第二次闪避直接 422 PROJECT_LIMIT |
| 响度表与一键统一响度：EBU R128 量积分响度与真峰值，写一个线性增益对齐 -16 LUFS | 已实现 | `tests/loudness_check.py`；相差 12.04 dB 的两条合成音被表量成 12.00 dB；导出闭环：-27.1 LUFS 的片段按建议增益 3.5892 导出后实测 -16.0 LUFS（真峰值 -15.6 dBTP）；峰值上限与 4 倍增益上限都如实报告 `limited_by`，不假装达到目标；静音素材被拒绝而不是得到无穷大增益；整轨一次对齐三段相差 6 dB 的素材得增益 0.9016 / 1.7989 / 3.5892（最响那段被**调低**），导出整片实测 -28.0 LUFS 对 -28.0 目标；音量已被关键帧动画的片段两个端点都跳过并说明原因；表的绝对刻度另由测试内独立实现的 ITU-R BS.1770-4（直接解码 PCM、不经过 FFmpeg）核对，loud/quiet 两段相差 0.00 / +0.04 LU |
| 静音检测与一键去空白：读原片声音找出停顿，剪掉并左移，一次点击 = 一个 revision | 已实现 | `tests/silence_check.py`；FFmpeg `silencedetect` + 标准库，无新依赖；合成音源（440 Hz 音 + 已知静音门 2.0–2.8 / 4.0–4.5 秒）上找到的区间为 2.033–2.8 / 4.033–4.5 秒、全部落在整帧网格上且不越过说话；200% 变速片段里区间按时速减半、低于阈值的短区间不切；返回的是普通 `clip.split` + `clip.ripple_remove` 命令（reducer 仍是唯一规则处），剪后 3 段素材的源时钟精确跳过静音（0→2.033、2.8→1.233、4.5→1.5 秒）；导出实测成片 4.767 秒、再对成片跑一遍静音检测已找不到 0.25 秒以上的停顿；带变速曲线、无音轨、声音被拆走的片段都明确拒绝；Agent 侧用 MCP 的 `clip_silence` 只读取命令、再用 `timeline_edit` 一次写入；整轨一次扫描（`/tracks/{id}/silence`）连片段首尾的停顿一起剪掉并左移，实测两片段轨道成片 3.367 秒、再扫已无 ≥0.25 秒停顿 |
| 遮罩跟踪：逐帧分析画面把遮罩中心与大小写成关键帧，随主体远近缩放、短遮挡按匀速补齐、跟丢即停下并说明 | 已实现 | `tests/tracking_check.py`；纯标准库 + FFmpeg 的归一化互相关块匹配（无新依赖，实测每帧 20–24 ms，尺寸持续变化时约 69 ms）；合成源上 90 帧最大中心误差 2.15 px（320×180 源、256×144 分析画幅），目标第 1.5 秒消失时精确报「1.50 秒跟丢」，1.00–1.60 秒被挡住时匀速补 18 帧并在 1.14 px 内重新找到同一目标；3 秒内长大 3 倍的目标尺寸误差 ≤ 8.2%，关掉尺寸估计后同一目标中心漂到 21.4 px（对比 2.5 px），证明缩放估计确实在起作用；导出实测成片遮罩在 t=0.4/1.1/1.8 跟随物体在 3% 画面内、跟踪结束后停在最后位置，且跟踪得到的尺寸路径在均匀亮场上把成片揭示面积从 2407 像素开到 8447 像素（量得线性比例 1.87 对路径要求的 1.88）；界面一次点击 = 一个 revision |
| 曲线变速：0–400% 速率折线与冻结帧，引擎编译成分段恒定速率 | 已实现 | `tests/speedramp_check.py`、`tests/desktop_speed_check.ts`；同一份分段同时驱动 FFmpeg `setpts/atempo/tpad/apad` 与浏览器 `playbackRate`，实测逐帧读取进度、4.000s 精确时长、440Hz 音高不变、冻结段静音；工程 schema v10 |
| 示波器（直方图/波形/矢量） | 已实现 | `tests/scope_check.ts` / `tests/frame_check.py`，测量真实合成帧并显示采样时间 |
| 代理回放：把已验证素材转码成 640/960/1280p 副本供预览，导出始终使用原片 | 已实现 | `tests/proxy_check.py`；代理按内容哈希寻址缓存在媒体缓存里、经签名地址流式读取，工程 revision 与导出滤镜图逐字节不变；实测 1080p 源转 960p 后体积为原片 1/11.1、同帧三通道均值最大偏差 0.14 LSB；界面切到 960p 后浏览器实际解码 960×540，播放头定位 4.5/0.5/5.9 秒时 `currentTime` 逐位一致 |
| 代理缓存配额：默认 4 GB 上限、构建时淘汰最久未播放的副本、界面显示占用并可一键清理 | 已实现 | `tests/proxyspace_check.py`；实测超限后只剩 1 份且 `used_bytes` 不超过上限、刚播放过的副本在淘汰时存活、清理释放的字节数与磁盘测量一致；源文件、缩略图与波形从不被清理，清理不产生工程 revision |

未实现的能力在 `GET /v1/capabilities` 中保持 `false`，界面上对应区域会显示"未就绪"而不会用演示画面冒充。

## 本轮加固（2026-10-04）

引擎与界面各做了一轮全量代码审查，修复的问题包括：

- **引擎**：多层时间线下空视频轨导致音轨配对错位（静音判断错轨）；渲染任务补齐 `request_id` 幂等回执与 `expected_revision` 校验（409）；FFmpeg stderr 不再可能塞满管道死锁；异常路径不再遗留孤儿 FFmpeg 进程；并发提交渲染不再可能争抢同一输出文件；`asset.import` 不再信任客户端回显的 verified 字段（以防伪造时长/类型）；波形解码加总超时；MCP `media_import` 超时放宽到 10 分钟；输出根目录持久化。
- **桌面端**：修复无 FFmpeg 配置下导出面板必崩（白屏）；冷启动不再可能拉起两个引擎进程；批次提交冲突时保留批次而不是清空；导入复制失败不再永久卡住 busy；撤销/重做改为恢复成功才动栈，元数据修改不再让重做栈错乱；提交链串行化（键盘连按不再产生假冲突）；引擎假死时请求 20 秒超时而不是永远挂起；启动超时杀进程并逐行扫描 ready 行；最大化关闭后恢复不再四边出屏；原有定位快捷键（本次工作台改为 ←/→ 逐帧，↑/↓ 编辑点）；素材库按内容指纹去重、上限提到 200；时间线左缘修剪受素材起点约束；引擎重启后未提交批次保留。
- 交互/文案：分割按钮跟随播放头实时可用、高频拖拽操作不再弹 toast、`media_probe = true` 调试文案移除、历史页排版修正、素材搜索大小写不敏感、超 1 小时标尺保留时位。

## 直接用（桌面版）

**双击本目录下的 `AgentCut.exe` 即可打开，不需要安装、不需要 Python、不需要命令行。**

| 文件 | 用途 |
|---|---|
| `AgentCut.exe` | 免安装桌面程序，放哪儿都能跑（本工程根目录，双击即用） |
| `desktop/release/AgentCut-安装版.exe` | 安装向导：桌面快捷方式「AgentCut 剪辑台」、可卸载 |

重新打包：先 `uv run python scripts/build_engine.py --verify`，再 `cd desktop && npm ci && npm run typecheck && npm run dist`，产物在 `desktop/release/`；
自包含引擎由 `uv run python scripts/build_engine.py --verify` 生成到 `desktop/resources/bin/`。
`desktop/release/`（安装版 + 便携版 + `win-unpacked/`）与 `desktop/node_modules/` 都不进版本库，
清理工作目录时不要删 `release/`——上面表格指向的安装版只在那里；删掉后必须重新 `npm run dist` 才能兑现文档里的路径。

1. 首次打开是工程页：新建一个工程 → 导入素材 → 拖上时间线 → 空格预览 → 右侧导出。
2. 素材只会从被授权的素材目录读取；「导入素材」会把文件复制进本地素材库，原文件永不被剪辑破坏。
3. 剪辑动作即刻写成批命令；切到「批次」模式可以先预演（虚线幽灵片段）再整体提交。
4. 「导出」锁定当前 revision：即使 Agent 同时在改时间线，产出的仍是你看中的那一版。
5. 忘了怎么用就按 `F1`：区域说明、快捷键、关键概念都在里面。

窗口没有系统标题栏：最小化 / 最大化 / 关闭都在软件内部，拖动顶部这一行即可移动窗口，双击切换最大化。
应用图标与标题栏标识同源（`desktop/build/icon.ico`），任务栏、快捷方式、安装向导用的是同一套图形。

## 让 Agent 接进来

桌面版「Agent」标签页里已经备好可复制的配置（密钥、接口地址、MCP JSON、Python 示例）。手工配置如下：

```powershell
# 引擎已经在跑（桌面版会自动启动，端口见 Agent 标签页）
$env:AGENTCUT_TOKEN = '<桌面版生成的同一个 Token>'
$env:AGENTCUT_API_URL = 'http://127.0.0.1:<端口>'
agentcut.exe mcp           # 或 uv run agentcut mcp（源码运行）
```

MCP 客户端配置模板见 [examples/mcp-config.example.json](examples/mcp-config.example.json)。
标准工作流：`editor_capabilities / editor_contracts` → `project_create` → `timeline_edit(dry_run=true)` → 同一 `request_id` 再 `dry_run=false` → `project_get / project_history`。

可执行示例：

```powershell
uv run python examples/agent_workflow.py
```

## 只用引擎（无界面）

```powershell
uv sync --locked
$env:AGENTCUT_TOKEN = uv run python -c "import secrets; print(secrets.token_hex(32))"
uv run agentcut api        # 默认 http://127.0.0.1:8765，只监听回环地址
```

`/health` 免认证，其余 `/v1/*` 需要 Bearer Token。数据库路径由 `AGENTCUT_DB` 覆盖。

## 开发

仓库只保留源码与成品（`node_modules`、`.venv`、`desktop/resources/bin` 引擎副本均不入库，需要时按下面命令再生）：

```powershell
# 引擎
uv sync --locked
uv run python -m agentcut desktop --port 0 --data-dir data --media-root data/fixtures `
  --ffmpeg desktop/resources/bin/ffmpeg.exe `
  --ffprobe desktop/resources/bin/ffprobe.exe --expose-token --json

# 界面（浏览器里跑同一套 UI，window.desktop 缺失时自动降级为纯 HTTP 外壳）
cd desktop && npm install && npx vite --port 5178
cd desktop && npm run dev                           # 起 Electron 窗口（用仓库 .venv 跑引擎）
cd desktop && npm run dist                          # 产出 release/*.exe

# 打包用的自包含引擎（PyInstaller onedir → desktop/resources/bin/）
uv run python scripts/build_engine.py --verify
uv run --with pillow python scripts/build_icon.py   # 重新生成图标集
```

## 目录

```text
src/agentcut/    contracts.py timeline.py projects.py http_api.py mcp_server.py
                 media.py（探测/缩略图/波形/流） render.py（RenderPlan） jobs.py（持久化任务）
desktop/         electron/（无边框窗口 + 引擎生命周期） src/（React 界面） build/（图标） resources/bin/（引擎+FFmpeg）
design/          旧静态设计稿；现行深色工作台以 desktop/src/ 为准
examples/        Agent 调用示例与 MCP 配置模板
docs/            architecture / api / decisions / agent-tasks / validation
tests/           self_check.py（HTTP + MCP） suite_check.py（逐个跑 39 项 *_check.py） media_check.py（真实媒体） editing_check.py（编辑/动画/字幕/变速/像素）
scripts/         build_engine.py（打包引擎） build_icon.py（生成图标）
```

## 验证

```powershell
uv run ruff check src tests examples scripts
uv run ruff format --check src tests examples scripts
uv run python tests/self_check.py      # 真实 HTTP + 官方 MCP stdio，临时库，跑完即清理
uv run python tests/suite_check.py     # 逐个跑 tests/*_check.py（每项一个子进程），任一失败非零退出
uv run python tests/suite_check.py --list
uv run python tests/suite_check.py grade marks fourpoint   # 只跑名字含这些子串的
```

`tests/suite_check.py` 存在的原因：`self_check.py` 只覆盖它自己拉起的链路，而逐功能验收散在 39 个 `tests/*_check.py` 里，
过去只能手动一个个跑——于是「门禁全绿」并不能证明这些检查真的执行过。该入口对每项打印 `PASS/FAIL` 与耗时，
失败时贴出子进程的末尾输出，任一失败以非零码退出（用一条故意失败的探针验证过它确实会红）。

`media_check.py` 需要 FFmpeg：脚本会先找 `desktop/resources/bin`（随包分发的二进制），再找 `desktop/node_modules`，
也可用 `AGENTCUT_FFMPEG` / `AGENTCUT_FFPROBE` 指定。

## 边界

- 只监听 `127.0.0.1`；没有多用户授权、远程访问、云素材、第三方插件沙箱。
- 同轨重叠只允许明确的两镜头转场；画面轨支持上下层合成和 8 种混合模式，已支持六属性关键帧。
- 历史保存每次全量快照，频繁编辑大工程会让数据库变大；未做结构共享与压缩。
- 安装包未做代码签名，首次运行 Windows 可能提示 SmartScreen。
- 导出为 H.264/AAC MP4 预设；未覆盖其它容器与编解码器，也不承诺可再分发全部 codec。

## 工作台升级

详见 [本次升级与完整替代目标](docs/optimization.md)。项目 schema v11 兼容读取 v1–v10 历史与旧请求回执；左缘修剪、音画联动、涟漪删除和变速均由服务统一执行。
