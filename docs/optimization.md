# 工作台优化与完整替代目标

用户明确要求覆盖全部日常工作：剪映的快速剪辑、达芬奇的专业时间线/调色、AE 的动画合成，人工与 Agent 共用。这里记录实际实现和仍需完成的能力，不把一次界面升级称为全面替代。

## 已落实到代码

- 统一深色工作台，可拖动和键盘调整素材/属性/时间线面板，记住布局。
- 素材监视器与序列监视器，完整素材上轨，逐帧前后、编辑点导航、播放头跟随、安全框、全屏、独立监听静音。
- 修复磁吸候选含自身、左缘只改源入点却不改位置、图片/文字修剪入点错误及纯垂直跨轨拖拽被忽略。
- 锁轨、共享涟漪删除、跨兼容轨移动、一个素材上轨作为一笔可撤销事务。
- 素材独立播放头、I/O 源区间、目标轨道、F9 插入/F10 覆盖；插入可同步未锁轨道，覆盖与分割共用源/动画连续性规则。
- 普通上轨、双击追加和拖入也使用该素材的标记区间，切换回工程素材后仍保留同一文件的标记。
- 交叉溶解与淡黑：后镜头属性面板添加/调整/移除，时间线显示重叠区间，透明画中画正确混合，声音交叉淡化；共享命令支持预演、撤销与固定版本导出。
- Ctrl/Shift 增减多选、空白框选、Ctrl+A 全选/Esc 清除；整组拖动/跨轨移动、微调、共同切点分割、普通/涟漪删除、复制/粘贴/追加副本。保留相对时距与组内转场，跨工程显式重建缺少的素材/轨道，锁轨失败整组回滚，一次撤销恢复。
- 位置/缩放/旋转/透明度/音量关键帧，线性/保持/缓入缓出，分割修剪保持曲线连续，淡入淡出预设。
- 多层视频/图片/文字预览与真实导出，0.25–4 倍速保留音高，曝光/对比度/饱和度。
- 标题与字幕文字编辑、字号、颜色、SRT 文件/粘贴导入、按轨复制 SRT、原生键盘输入取消。
- 同一个 HTTP/MCP 契约覆盖所有新增功能，旧项目、历史与回执兼容。
- 新建/切换工程统一清理旧播放状态并回到起点；导出摘要显示所选预设的实际分辨率。
- 工程中保存平面组合与手动音画链接，Ctrl+G/Shift+Ctrl+G 组合/取消，Ctrl+L/Shift+Ctrl+L 链接/解除，Alt 临时单选与全局联动开关。链接共同分割/修剪；复制使用新关联 id，独立编辑显示失步，锁任一成员轨道拒绝整批联动操作。
- 涟漪修剪（Shift+拖动片段边缘，同轨后续顺移，转场宽度保留）与滚动剪辑（Ctrl+拖边缘，两相邻片段共有接缝平移，总时长不变）；越界/失源整笔拒绝。tests/roll_check.py。
- 闪白转场 dip_white：与淡黑同一套包络，预览与重编码渲染完全同谱。
- 视频内嵌声音可拆为独立声音轨（clip.detach_audio），原视频静音，自动音画链接保持同步；剪辑+检查+真实 FFmpeg 响度对齐覆盖。tests/detach_check.py。
- 字幕新增顶/中/下对齐（align）与半透明垫条（box），预览 CSS 渐变带与导出同一 geq 带对齐；tests/style_check.py 像素级验证。
- 工程打包迁移：GET /v1/projects/{id}/bundle 导出 project.json 与全部素材的单个 zip；POST /v1/bundle 导入时把素材写入本机素材目录并重新 ffprobe，不信任包内路径，命令行/桌面/Agent 走同一条。工程列表每行有导出按钮，顶部有导入工程包。tests/bundle_check.py。
- 示波器面板（直方图 / 波形 / 矢量）测量导出图生成的合成帧，包含叠层、调色、文字、动画与转场，显示实际采样时间。低分辨率后台更新，长工程可能滞后；`tests/scope_check.ts` 验证横向画面位置/纵向通道强度，`tests/frame_check.py` 验证真实合成像素。

## 1.8 修复（2026-10-05）

针对最新 1.7 交付审计修复分离声音预览静音、滚动剪辑绕过链接锁轨、变速与静态源时钟、工程包失败残留/空工程/重复导入、旧文字回执冲突、依赖锁版本与示波器取错画面/波形坐标。包导入保留完整快照，所有数据库写入一起提交；网络失败可用同一请求重试。没有增加运行时依赖。完整替代能力仍按下面清单推进。

## 参考的交互原则

[CapCut 官方 PC 教程](https://www.capcut.com/resource/how-to-use-capcut-on-pc)提供素材→时间线→属性→导出的入口组织；[官方关键帧说明](https://www.capcut.com/help/keyframes-in-capcut-pc)支持属性旁就近添加关键帧的操作方式。
[DaVinci Resolve 官方 Edit 页面](https://www.blackmagicdesign.com/products/davinciresolve/edit)用于研究监视器、精确剪辑、磁吸与检查器工作流。
[官方剪辑师指南](https://documents.blackmagicdesign.com/UserManuals/DaVinciResolveEditorsGuide.pdf)用于研究素材入出点与插入/覆盖的三点剪辑流程和 F9/F10 快捷键。
[Adobe 官方关键帧说明](https://helpx.adobe.com/after-effects/using/keyframes.html)用于研究属性动画、保持和缓动。这些工作流原则用于原创实现，未复制商业软件素材或代码。
[MDN 的 mix-blend-mode 说明](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/mix-blend-mode)用于交叉溶解的 plus-lighter 合成；[FFmpeg 官方滤镜文档](https://ffmpeg.org/ffmpeg-filters.html)用于验证预乘透明度、相加与声音权重。
[Resolve 官方入门指南](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-17-Beginners-Guide.pdf)用于研究联动选择开关与 Alt 临时绕过；[Adobe 官方组合说明](https://helpx.adobe.com/in/premiere/desktop/edit-projects/change-clip-sequence/group-clips.html)与[音画链接说明](https://helpx.adobe.com/uk/premiere/desktop/add-audio-effects/basic-audio-editing/link-audio-and-video-clips.html)用于区分持久组合和同步关联。快捷键属于 AgentCut 当前配置，没有声称与这些软件逐键一致。

## 验证证据

tests/self_check.py：真实 HTTP、官方 MCP stdio、原子事务、并发、重试、恢复、跨重启。
tests/link_check.py：组合/链接持久保存，HTTP 预演/重放，源差值与动画时钟连续，联动修剪、成对分割、跨轨插入的独立左右链接，锁轨、失步拒绝、解除与孤立清理，旧 v3/v4 指纹。self_check.py 用真实官方 MCP stdio 提交组合、链接与联动修剪，并读取权威同步状态。
tests/editing_check.py：旧 schema/回执指纹、排队后继续编辑仍输出原快照、登记元数据不得伪造文件凭证、关键帧/缓动/分割/修剪连续性、锁轨/涟漪、SRT 往返与失败回滚；真实 FFmpeg 像素、中文与特殊字符文本、变速后时长、440 Hz 音高和灰阶色彩。
tests/media_check.py：授权路径、真实导入、缩略图/波形、声画时长、双层合成、图片、空隙、任务取消。
tests/placement_check.py：插入/覆盖边界、同步轨道、锁定、速度与缓动连续性、图片/文字源时钟、跨时钟拒绝、溢出、HTTP 预演与重试。self_check.py 另通过真实 MCP 调用；editing_check.py 导出蓝→红→蓝并检查插入/覆盖成片时长。
tests/transition_check.py：添加/修改/移除、相邻转场、涟漪删除、边界外分割/覆盖引用、非法重叠拒绝、锁轨、v3 指纹；真实 FFmpeg 检查溶解 RGB、半透明画中画、淡黑中点、3 秒输出和 440/880 Hz 声音各约半音量。
tests/group_check.py：共享 delta、跨轨转场、独占区间涟漪删除、声音与画面分割、300 片段单命令添加、重复/缺失 id、锁轨/时钟/类型拒绝、HTTP dry-run/重放/回滚与恢复；self_check.py 另经真实 MCP 调用组移动/删除。
tests/desktop_editing_check.ts：深拷贝剪贴板、组内引用重映射、保留源/动画时钟、跨工程素材与解锁新轨道、混合时钟公倍数、不同源起点的共同 delta；用已有 esbuild 编译后 Node assert 验收。
tests/build_check.py：启动同一自包含引擎的两个隔离实例，构建清理只结束指定实例；修复原先按进程名清理会误停其他剪辑实例的问题。另在完整构建校验期间保留一台在线测试服务，校验后确认它仍响应 1.4.0。
组剪辑界面实测（浏览器运行同一 React 前端）：声画三段粘贴一次 r+1、拖动保持共同 delta，单次撤销恢复；两镜头跨轨仍保留转场，锁其中一轨使三段删除全拒绝；跨工程粘贴可信媒体、框选、Ctrl+A、共同切点分割、连续 10 次微调没有丢步；批次预演显示三段提案而不写库，提交/撤销各生成一个版本。复制/粘贴使用实际界面按钮验收；浏览器工具拦截 Ctrl+C/V 到虚拟剪贴板，因此这两个键组合未在原生 Electron 窗口实测。
转场界面实测：一秒转场使两个两秒镜头衔接为三秒；透明画中画的预览中点与两单镜头原生解码预览平均值一致（每通道误差 ≤3），淡黑全画幅中点为黑色，移除恢复首尾衔接。原生解码与 FFmpeg 的颜色转换仍有差异，不能据此声称完整色彩管理。
本轮界面实测：I/O 取一秒区间、F9 在 2 秒处插入并顺延声音、F10 覆盖、Ctrl+Z 恢复原区间，后台逐 tick 检查实际项目。
1040×660 下源区间与操作按钮无横向溢出，预览画面保留约 278×156；全屏画幅为 16:9，明确的退出按钮与 Esc 均可回到工作台。
桌面 UI 实测：导入 SRT、选择关键帧、修改缩放、Escape 放弃输入、切换 2 倍速、拖拽左边缘、540p 完整导出；目标窗口最小 1040×660。
发布包另通过自包含引擎启动/health/关闭检查及 TypeScript/Vite/Electron 构建。最终打包时间以本次交付说明为准。
本轮 1.2.0 发布包（2026-10-04）通过自包含引擎实测：普通上轨采用标记的 1–2 秒区间；最终工程 r6 导出 H.264/AAC，960×540，视频与音频均为 7.000 秒。便携版已同步至项目根目录 AgentCut.exe，旧 1.1 交付文件保留。
1.3.0 发布包（2026-10-05）：交叉溶解与淡黑已实现，1040×660 无横向溢出、滚动属性面板可修改转场时长；重启自包含引擎后从界面导出 r8，H.264/AAC、960×540，视频与音频均为 3.000 秒，转场中点 RGB 为 (62,127,62)，符合半透明红蓝画中画与绿色底层的合成预期。便携版和安装版已重建，内嵌引擎与验收引擎 SHA256 一致；项目根目录 AgentCut.exe 同步为 1.3.0，旧 1.1/1.2 交付文件保留。
1.4.0 发布包（2026-10-05）：多选/框选与成组剪辑已实现；1040×660 时间线工具栏宽度 1038、内容宽度 1038，无横向溢出，组操作均可见。自包含引擎再次验收整组三段拖动/撤销、追加副本/撤销，逐 tick 检查历史与组内转场重映射。界面导出锁定 r28，H.264/AAC、960×540，视频与音频均为 6.000 秒，溶解中点 RGB (62,0,62)，4.2 秒处配乐 220 Hz 幅度约 0.1247、已结束镜头的 440/880 Hz 均低于 0.000006。便携版 133,126,129 字节、安装版 133,286,836 字节；便携版 SHA256 D41BF50FBAF572DA372AC5FB0A739924CF528BF1051B2CFA1655C375FEE5EED4，已同步项目根目录。验收引擎与发布包内嵌引擎 SHA256 均为 D189B299AC5900A755B9AC8DD9489F75A55546F926E089A9E3AAC001022C02D9；旧 1.1/1.2/1.3 交付文件保留。

1.5.0 发布包（2026-10-05）：工程持久组合与手动音画链接已实现。用自包含 1.5 引擎服务实际 React 界面，保存组合/链接后重载；单击选中两段，拖动一次 r+1，左缘共同修剪 0.5 秒，Ctrl+Shift+G 取消平面组，Ctrl+B 切分成独立左右音画对，Ctrl+G 组合右半段；追加副本生成新组合/链接 id，撤销一次恢复。关闭联动独立拖动视频显示失步，撤销恢复；重新开启联动会扩展当前选择。锁音轨后修剪视频返回 TRACK_LOCKED，工程仍为 r14，解锁为 r15。1040×660 工具栏 clientWidth/scrollWidth 均为 1038，没有横向溢出。原生 Electron 顶层窗口快捷键未在本轮直接实测。

界面固定 r15 导出 H.264/AAC 960×540 30fps，声画均为 2.000 秒；前 0.5 秒画面中央为黑、声音为静音，0.75 秒中央为红。切点前后（0.7/1.3 秒）外录音 220 Hz 幅度 0.124895/0.124797，已静音视频的内嵌 440 Hz 均低于 0.000018。验收脚本逐 tick 比较 r3–r15，校验两次撤销、源差值、分割、复制关联隔离与锁轨拒绝。发布包内 140 个引擎文件与验收引擎一致，SHA256 A16944DDD44D9813E75C89D19C5BA15B37C6ED9C82D28DD651A7CD75CA65FC48；ASAR 版本 1.5.0，全部 3 个 renderer 文件与本轮构建一致。

便携版 133,131,575 字节，SHA256 F0CFA36DA8B541FA2F995E339221B24C67D6A795B2DB822E7AD07789D18D5874；安装版 133,292,295 字节，SHA256 1A0A3EE5630AAFCB90DF74FF5CCA65FF791DAC40C4C4BB097F877FD45015D89B。项目根目录 AgentCut.exe 已同步 1.5，旧 1.1–1.4 交付文件保留。新增能力使用现有契约、reducer、SQLite 和浏览器原生能力，没有增加运行时依赖。

## 后续必须完成，目标仍在进行

本轮：新增工程打包导出/导入；右侧新增示波器面板（直方图/波形/矢量），工程行改为可键盘操作的容器以承载导出按钮。（zip 往返，素材重新探测），桌面端工程列表逐行导出与顶部导入；tests/bundle_check.py 通过。1.7.0 发布包（2026-10-05）：字幕新增顶/中/下对齐与半透明垫条，展现为全宽半透明渐变带，导出走 geq 带与预览渐变带同谱。新增 tests/style_check.py。

1.6.0 发布包（2026-10-05）：新增涟漪修剪（Shift+拖边缘）与滚动剪辑（Ctrl+拖边缘，共产接缝平移、总时长不变、转场保宽、越界整笔拒绝），新增闪白转场 dip_white（预览与导出同一套包络），新增视频内嵌声音拆分为独立音轨（clip.detach_audio，自动音画链接同步、真实 FFmpeg 响度对齐）。`tests/roll_check.py`、`tests/detach_check.py` 新增验收；`tests/self_check.py` / `editing_check.py` / `link_check.py` / `group_check.py` / `transition_check.py` / `media_check.py` / `placement_check.py` 与 esbuild 桌面检查全部通过；内嵌引擎、vite 构建、Electron 打包均完成；便携版已同步项目根目录 AgentCut.exe，旧 1.1–1.5 交付文件保留。

1.126 逐条对账过这张清单：写「已完成」的都点得到模块或检查文件，写「仍未做」的说清它挡在哪一个不变量或哪一个没验收的量上。

1. 精确剪辑：四点剪辑**已交付**（`src/agentcut/fourpoint.py` + `tests/fourpoint_check.py`，成片量过「源长就剪、源短就重新计时、不静默猜」——原文写着「仍待实现」是过时的）。涟漪修剪、滚动剪辑（`roll_check.py`）、滑移（`slip_check.py`）、拆分内嵌音轨（`detach_check.py`）、持久组合/手动音画链接/多选与复制粘贴（`group_check.py`、`link_check.py`、`editing_check.py`）都已完成；链接要求先对齐位置/时长/速度，不自动分析波形，原视频仍按自身音量播放。剪贴板（复制的片段、关键帧节奏、素材上的入出点）自 1.125 起跨重启保存（`tests/desktop_clipboard_check.ts`）：读回先过形状门，冷的那份在粘到别的工程前由当前引擎重新探测缺的素材，探测不到就整批不粘并点名是哪几个。一批编辑命令的上限自 1.126 起是量出来的 2500 条（契约一处，能力表与界面读同一个数）。1.128 起时间线上按住 Alt 拖链接的某一边就是这一条命令（一次抓取，不用先单选；窗口到 (edge, delta) 的换算只有一处，不是单边移动就退回普通修剪）。1.127 交付了音画链接的**分边修剪**（J/L cut）：一条 `clip.link_split_trim` 只动被点名的那一边，伙伴两边不动，链接记录留着；`link_status` 的 `differences` 按「相对基准」报出 ticks，`clips.link_reconcile` 是一次拉回（界面那句中文与那颗按钮共用同一份数，不自己再算），成片量过「画面已经换到下一个镜头、同一段 440 Hz 的幅度一字不差」（`tests/jlcut_check.py` + 第 42 个壳层检查 `tests/desktop_jlcut_check.ts`）。**仍未做的**：跨工程不同帧率的自动转换（刻度按 `TIMEBASE` 走，位置对得上，帧网格与速度换算不自动改）；20,000 片段是契约上限，**引擎侧量过了**（打包引擎 1.129.0，一段一秒、单轨 20,000 段，八批各 2,500 条）：写入加读回从每批 0.40s 涨到 3.09s（中位 1.66s，总 13.3s——每批都要重写并哈希整份工程，所以是超线性的），整份工程 JSON 13.1 MiB，之后一次 GET 读回 0.82s。**界面侧那条缺陷已经在 1.131–1.133 还掉了**：当年量到的是同一份工程在打包好的渲染层里连一次 `document.querySelectorAll('.clip').length` 都读不出来（CDP 求值 15s 超时），首帧把两万张卡片全建出来（1.132：never-painted、0 张、进程树峰值 2,994 MB 后渲染进程消失）；1.133 把「建多少东西」绑到视口而不是时间线长度之后，装机实测同一份工程（12,103,211 字节）painted 于 6.7 s、13 张卡片、485 个 DOM 节点、进程树峰值 843 MB，页面那句「窗口外还有 19987 段没有画（它们仍在工程里，也在导出里）」念的是实数，`tests/desktop_20k_check.ts` 与 `desktop_zoomclamp_check.ts` 把首帧上界与脏偏好钉住。所以「两万段首帧画得出来、滚过去就有了」这句现在讲得出；**仍没量的是**：连续滚动的帧率、以及十万段这种量级（这台机器上没跑过）。
2. 常用成片：13 种转场（清单由 `capabilities.transition_kinds` 下发，`transition_check.py`）、曲线变速与冻结帧（`speedramp_check.py`）、自动语音字幕（`asr_check.py`）、字幕样式与批量编辑（`style_check.py`、`textstyle_check.py`、`captions_comp_check.py`）、片段两头可拖的淡角柄与四种形状（`fade_check.py`、`fadeshape_check.py`、`fadebatch_check.py`）、按标记分割（`marker_check.py`、`marks_check.py`）均已交付。MXF 交付已交付（1.129：`mxf_check.py`，两条预设都真导真读，48 kHz 那条约束按计划阶段点名拒）。DPX／OpenEXR 这类每帧一个文件的序列交付**也已交付**（1.142：`exr-sequence` 与 `dpx-sequence` 两条预设，交付复检从「读一个文件」换成「按帧点货」，`alphamaster_check.py` 与 1.143 的装机真点都量过；`contracts.OUTPUT_CONTAINERS` 现为九个容器，`tests/docs_facts_check.py` 把 README 那一行钉回这张表）。**仍未做的**：MXF 之外的广播封装（没有 AS-11/DPP 一类的机房元数据），也不承诺可再分发全部 codec。
3. AE 合成：时间贝塞尔与自定义手柄（`bezier_check.py`）、dope sheet 的一组针（框选、整组拖、Alt 删、轨道道，`desktop_keyframemarquee/keyframedrag/keyframelane_check.ts`）、路径遮罩与其形状动画（`pathmask_check.py`、`maskshape_check.py`、`maskanim_check.py`）、嵌套合成（`nest_check.py` 量嵌套本身与 `sequence_id` 的预演/重放，`nestfx_check.py` 量合成里的每条滤镜落在同一片像素上，`analysis_sweep_check.py` 量九条分析入口对合成内部的每条拒绝都点名；第十条自动调色由 `self_check.py` 走真实 MCP stdio 量过）、混合模式两端同数（`blend_check.py` 与 1.122 的分支混合）、逐帧柔焦/清晰（`blurkey_check.py`、`sharpenkey_check.py`）已完成。**仍未做的**：① 调色节点的第二路输入（把另一段画面喂进同一个节点）——两支画面进同一个 FFmpeg 阶段与浏览器 canvas 的复合都已逐模式量过并记在 `AGENTS.md`，但那是会把「一条链塌成一张每通道表」这个不变量换掉的架构改动，没有连线形状之前不假装交付；② 多目标跟踪（一个片段现在只有一个遮罩槽位 `Clip.mask`，1.85 的遮挡续跟是一个目标一条轨迹）。
4. 达芬奇工作流：色轮/曲线/色阶/通道混合/1D+3D LUT（`grade_check.py`、`gradelevels_check.py`、`matrix_check.py`、`lut_check.py`、`lut3d_check.py`）、示波器（`tests/scope_check.ts`）、色彩空间转换与每通道表的精度（`grade_check.py`、`gradelevels_check.py`、`curvefidelity_check.py`）、整轨响度/去空白/自动闪避（`loudness_check.py`、`silence_check.py`、`duck_check.py`）、代理与缓存配额（`proxy_check.py`、`proxyspace_check.py`、`cache_check.py`）已完成，调色图还能摆成树（1.124）。**仍未做的**：完整的二通道色彩管理流程里剩下的那一半——一键套叠本身已在 1.130 交付（`clip.color_manage`，一条命令把片段搬进线性光再搬回显示端，`colormanage_check.py` 量过），输入侧的**自动识别**已在 1.150 交付（`auto_source` 读素材自己的 `color_transfer`，`colortags.py` + `colortags_check.py`；只有带实测标记的四种曲线认得出，`gamma18`／`gamma20`／`gamma24` 没有对应的标记，仍要手工选，只标了矩阵系数或基色的文件按 `no_transfer_tag` 点名拒而不是猜）；交付侧的**声明**已在 1.151 交付（`colour_tag` 一条开关同时写容器三样标记与 `zscale` 折叠，`colour_tag_check.py` 八项里 `video_suite` 用真实 mp4 跑真编码并比 RGB 往返）；可调快捷键已在 1.134–1.135 交付（`desktop/src/keymap.ts` 那张表，21 条，界面与历史念同一份）；代码签名仍没有，它要一张证书而不是一个改动。**这一头仍开着的**：标记表今天只有一档（BT.709），第二档要先量 `zscale` 认的基色名与它对应的独立预测；透明母版按 `COLOUR_TAG_NOT_WITH_ALPHA` 有意不带标记；MXF 容器写入的标记是否原样读回只在 mp4 上量过。
5. 真实生产验收：项目备份与打包迁移已交付（`bundle_check.py`）；仍欠用户的长项目与素材格式、4K 多轨性能、快捷键预设与签名发布。

现阶段能覆盖的已经不止基础剪辑、画中画、字幕与基础动画；上面每条「仍未做」都写清了它缺的是哪一个不变量或哪一个没验收的量——不拿看着像的近似当已交付。


## 1.9 动画曲线（2026-10-05）

六属性数值图可拖点调整时间与数值、双击加点、精确输入、切换插值、方向键微调、时间吸附、缩放与平移；即时写入或批次预演/提交均走原有命令事务。拖动一次对应一条历史，碰撞拒绝、Esc 取消、锁轨保护、旧 revision 手势拒绝。原有 property_curve 提取为共享编译器，排序/扫描改为一次遍历，2000 点验收低于 2 秒。没有增加依赖或项目 schema。

参考 [Adobe 官方图形编辑器关键帧交互](https://helpx.adobe.com/uk/after-effects/desktop/animate-in-after-effects/animation-keyframes/editing-moving-copying-keyframes.html)的时间/数值拖动原则，采用原创 React/SVG 实现。`tests/curve_check.py` 独立计算 SVG 三次曲线，与权威采样逐点比对，并检查裁剪偏移、hold 跳变、移动冲突、锁轨/整批回滚、HTTP 只读、真实合成像素与重试去重；`tests/self_check.py` 通过真实 MCP 读曲线与移动重放。

浏览器使用同一 React 前端实测：5 秒/90% 拖到 6 秒/65%，一次 r1→r2；Right/Up 分别 r3/r4，撤销 r5 恢复 65%；移动至已有 10 秒点拒绝且仍 r5，Escape 输入取消；两条 hold/75% 批次一起提交为 r6，双击候选加点后放弃仍 r6。1040×660 控件可见。原生 Electron 窗口控制及安装向导仍未直接操作验收。完整替代目标仍在继续。

1.9.0 发布验收：全部 15 项 Python / 2 项 Node、Ruff、TypeScript 与独立干净构建通过；ASAR 3 个前端/2 个外壳文件、142 个引擎文件逐字节一致。包内引擎实际 HTTP/MCP 图线和移动、界面保存/撤销、10 秒 H.264/AAC 动画声画导出通过。便携版 133,157,399 字节，SHA256 6EE083752B7DADA38EBD62FE41829FDFB43305E9D789CD3D613DB1445728897B；安装版 133,318,112 字节，SHA256 967BF98F0814891BA5C43B2267E1C82F0A2BFA7C3ECB5190E98AE6B1005422AD。根目录入口同步 1.9；1.8 保留。未签名，原生窗口/安装向导未直接验收。

## 1.10 形状遮罩与画面预演

参考 [Adobe 官方遮罩工作流](https://helpx.adobe.com/after-effects/desktop/work-with-transparency-and-compositing/work-with-alpha-channels-and-masks/alpha-channels-masks-mattes.html)，新增原创矩形/椭圆遮罩编辑：属性输入、向内线性羽化、反转、画面中心拖动和四角缩放、方向键/Shift 微调、Esc 取消、移除与撤销。遮罩随片段的缩放/旋转/平移，控制点维持约 10 个屏幕像素。SVG 与 FFmpeg 共用几何编译；不宣称 AE 的自由路径、遮罩动画、Gaussian 羽化或跟踪已经完成。没有新增依赖。

批次的整个候选工程现在编译真实预览计划，颜色/转场/动画/遮罩可以提交前观看。即时拖动松开仅写一个 revision，计划刷新保留媒体节点和键盘焦点；批次放弃不写工程。`tests/mask_check.py` 验证真实矩形/椭圆、羽化/反转像素、只读候选、去重、锁轨、声音拒绝/拆分、分割及 v1–v5 兼容；MCP 实际读取候选并验证未写库。

同一前端在 1040×660 实测：椭圆、50% 向内羽化、拖中间、连续 Right/Down、缩放四角各保存一次；撤销缩放生成新版本并恢复尺寸。矩形+反转两条批次显示候选 r9，放弃仍 r8；旋转 30° 后沿片段局部 X 拖动，中心正确变化，控制点随画面旋转。原生 Electron 顶层窗口与安装向导未直接操作验收。完整替代目标仍在继续。

1.10.0 发布验收：16 项 Python / 2 项 Node、Ruff、TypeScript 与独立干净构建通过；ASAR 3 个前端/2 个外壳文件、142 个引擎文件逐字节一致。冻结 HTTP/MCP 遮罩、候选预演、工程包往返、真实像素和 10 秒声画导出通过；包内界面修改/撤销、拖动一次提交、锁轨保护已验证。便携版 133,164,147 字节，SHA256 AE7E8D3F11E3752CA817060709FE6967D66E04F05672421F6EC28CA40CC47368；安装版 133,324,859 字节，SHA256 940A3E1CAF3F64F94C2DE13C60070DB21EF980E5B77025698AA043D2B41230C6。根目录入口同步 1.10，1.9 保留；原生窗口/安装向导未直接验收，未签名。

## 1.11 画面轨混合模式

新增 8 种整轨混合：正常、正片叠底、滤色、叠加、变暗、变亮、差值、排除；检查器原生选择、候选预览/放弃/提交、撤销和锁轨。转场先合成再混合，遮罩/透明度保留覆盖范围，浏览器画布隔离且黑底。track.update 共用 reducer；schema v7 读取 v1–v6，默认模式兼容旧回执；未新增依赖。修复浏览器状态端口从实际 engine URL 推导。

发布验收：17 项 Python / 2 项 Node、Ruff、TypeScript、独立干净构建通过；8 模式独立公式、羽化/遮罩、不透明度、非线性转场、单轨黑底、原子写入和锁轨覆盖。ASAR 3 个前端/2 个外壳和 142 个引擎文件逐字节一致。正式包内前端+冻结引擎实际保存/撤销、候选放弃、锁轨，HTTP/MCP 和工程包往返、10 秒声画导出通过。根目录同步 1.11，1.10 保留。便携 SHA256 22D82E85B025A25B2ACC2E8AE3A9FCDC4A0D8BA551EA9C2E40970B7C936FEF0C；安装版 306D955CAF3A63BE9BF4FCAAA71C5D559BE54C47FDAFC72D1BEB8BD0B32FF3C2。原生窗口/安装向导未直接验收，未签名。完整色彩管理、逐片段混合、嵌套合成和全面替代目标仍待完成。

## 1.12 连续编辑与候选检查器

clip.patch 在共享 reducer 合并稀疏字段，解决连续 X/Y、曝光/饱和度、正文/字号相互覆盖；批次单项移除真正独立。旧完整替换、schema v7 和旧回执保留。检查器读取候选，待预演时显示上一个有效快照并暂停输入，迟到请求/错误不能篡改当前批次状态；时间字段不再每次重建。只读 HTTP/MCP animation_sample 复用 render sample，为候选关键帧显示和创建提供权威值。未新增依赖。

验收：18 项 Python / 3 项 Node、Ruff、TypeScript、独立干净构建通过；ASAR 3 个前端/2 个外壳和 142 个引擎文件逐字节一致。源码界面六条连续编辑、单项移除、一次撤销与候选动画；正式包内界面六条一次提交 r3、撤销 r4/重做 r5、锁轨 r6/解锁 r7 已实际验证。固定 r3 的 10 秒 H.264/AAC 声画导出、移动后遮罩中心蓝值 101/羽化蓝值 48、声音 -24.1 dB 通过，后续编辑到 r7 未改变导出快照。最小 1040×660 无横向文档溢出，截图 1440×900。根目录同步 1.12，1.11 保留。便携 SHA256 E1654B7CAC9EF49F7142EF725B764159F576560CAECA273C97408919D1395A51；安装版 DE1613D5B505F01DDFA68172F9B199F43023A5C3DCE6A96B3AD8AD386CE81139。原生窗口/安装向导未直接操作验收，未签名；全面替代目标继续推进。


## 1.13 预合成与嵌套时间线

可把完整声画/标题/链接片段收进共享合成，进入编辑、导航返回、复用、内部关键帧、修剪/变速、透明图层混合和声音均接通同一 reducer/HTTP/MCP/预览/导出。schema v8 读取旧版本；默认旧回执兼容，循环/深度/锁轨/不完整关系/层级冲突原子拒绝。根工程与当前编辑投影分离，候选、批次与异步手势绑定合成，跨工程复制重映射嵌套依赖。未新增依赖。

验收：19 项 Python、4 项 Node、Ruff、TypeScript 和独立干净构建通过；ASAR 3 个前端/2 个外壳及 142 个冻结运行时文件逐字节一致。正式包内界面创建 r3、内部改动/撤销/重做 r4–r6、X/Y 关键帧与曲线 r7/r8，通过实际 H.264/AAC 10 秒、300 帧、48 kHz 声画导出；正式 MCP 内部导出固定 r3，后续修改 r4 不改变快照。最小 1040×660 无横向页面溢出。根目录同步 1.13，旧版本保留。便携 SHA256 3C3945A1A4F786A1932C14829AEDB126BEF4C67327EFD00DE4C920D8CC13A12B；安装 D864CA42129B9936BB96B347A6667986ADE59C0CB067AFA34FEE32B96E366693。原生窗口/安装向导未直接操作验收，未签名。独立合成设置、路径/跟踪、专业调色与生产性能及全面替代目标继续推进。


## 1.14 时间贝塞尔与可编辑控制柄

关键帧支持贝塞尔插值、出入控制柄拖动/键盘微调/精确百分比，候选、锁轨、撤销重做与嵌套编辑沿用同一流程。浏览器、HTTP/MCP、FFmpeg 共用曲线契约，裁剪和极值分段保持一致；交叉时间控制柄与退化导数已覆盖。属性范围之外的曲线原子拒绝。schema v9 兼容旧工程和默认回执；检查器改关键帧值保留控制柄。普通选择误判拖动的根因已修复，未新增依赖。

验收：20 项 Python、4 项 Node、Ruff、TypeScript、独立干净构建通过；正式 ASAR 3 个前端/2 个外壳及 142 个冻结运行时逐字节一致。正式界面在嵌套内拖动、撤销/重做、锁轨/解锁、精确输入 r5–r10，UI 固定 r10、MCP 固定 r3 的曲线声画导出通过；10 秒/300 帧/H.264/AAC/48 kHz、三个时刻像素符合独立曲线公式，音量约 -24.1 dB。1040×660 无横向溢出，四个控制输入可见。根目录同步 1.14，旧版本保留。便携 SHA256 87F00AFF8DDE1C22F7A07BD8A561FD4A986EBA10A783B403D71F2724C719AE0F，安装版 0A92696157ED77A0E0189579765649AC3E088DA6571E9EB21D8CAA4AFB5B36C8。未签名，原生窗口/安装向导未直接验收。空间路径、速度图、多关键帧选区、路径跟踪、专业调色与全面替代目标继续推进。


## 1.15 多关键帧选区与原子编辑

Shift 点选、空白框选、Ctrl+A、整体拖动/键盘微调/时间与数值输入、批量插值和删除。整体边界限位与未选点碰撞保护；适合数值包含贝塞尔控制顶点。HTTP/MCP 新增 keyframes.move/remove，每条最多 2000 点，可占用选中点旧位置或交换点；动画时钟、控制柄、幂等、锁轨、事务和历史兼容，schema v9 不变。UI 使用当前片段/属性，Agent 可显式跨属性。

修复撤销后选区误匹配：记录会话内完整快照的选区，未知外部快照清空，不写入工程。最终包验证移动撤销/重做正确恢复三点、删除撤销三点、全选微调撤销五点。21 项 Python、4 项 Node、Ruff、TypeScript、独立构建通过；ASAR 3 个前端/2 个外壳、142 个冻结运行时逐字节一致。原生界面手势验收到 r16、锁轨/碰撞/整体边界保护、父时间线不变，控制柄 220%/-110% 可见，1040×660 无横向溢出。实际 ASAR 界面与 MCP 的 r16/r3 固定快照输出分别 640×360/960×540，10 秒/300 帧/H.264/AAC/48 kHz，通过三个时刻独立像素核验，声音约 -24.1 dB。

根目录已同步 1.15；便携 SHA256 60EDC90A8719F6CFB3D27DA76E42C3D7C3E80F4ECF393E59F64E193949053B33，安装版 D1CC7A28D417253BEF89958622A7FB80F305B0C02052244AABDF269E90D13F36。未签名，原生 Electron 窗口/安装向导未直接验收。空间路径、速度图、路径跟踪、专业调色、自动语音字幕、代理管理与全面替代目标继续推进。

## 1.16 串行调色节点（2026-10-06）

达芬奇的主校色入口改为原创实现：片段按顺序执行最多 8 个调色节点——每通道传递曲线（主色/红/绿/蓝，2..16 个控制点，可超出 0..1 后钳位）、白平衡（色温/色调逐通道增益）、RGB 增益（阴影/中间调/亮部 × 红绿蓝）。界面提供曲线盘拖动、双击加点、方向键微调与删点，色轮盘（左绿右品红、上黄下蓝，只改彩度）与数值输入，节点可停用、上下移动、删除、清空。参考 [Resolve 主校色轮](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-17-Beginners-Guide.pdf) 与 [Adobe 颜色曲线](https://helpx.adobe.com/after-effects/using/color-adjustment-overview.html) 的交互原则，未复制任何商业软件素材或代码。

关键取舍：先用本机 FFmpeg 实测 `curves` 滤镜，确认它对同样控制点做样条插值（x=96 处实测 174，分段线性应为 149），因此不能作为两端共用的权威。grade.py 改为把整条链合成一条每通道折线（65 点栅格并集控制点、近共线合并），再由同一折线导出 FFmpeg `lutrgb` 分段线性表达式与浏览器 `feFuncR/G/B type="table"` 的 256 项表；空链或恒等链不产生滤镜。这样预览与导出是同一个函数，实测 FFmpeg 输出与该表的偏差 ≤1.0 LSB（仅 8 位取整），界面另用独立 JS 参考实现逐点比对，最大偏差 0.862 LSB。没有新增依赖。

契约：新增 `clip.grade` 命令与 `clip.patch.color.grade`，capabilities 增加 `grade_nodes`，工程 schema v10 兼容读取 v1–v9；color 中的默认 `grade` 已从请求指纹剔除，v3/v4/v1.5/v1.7 的旧回执重放继续通过（相应检查同步补上“旧载荷不含 grade”这一步，与 align/box 的既有做法一致）。

验收：`tests/grade_check.py` 覆盖真实 HTTP 的写入/重放/409/dry-run/锁轨/声音拒绝/契约拒绝（降序控制点、超过 8 节点）/单项移除/历史恢复，preview-manifest 表与独立参考实现逐点比对，真实 H.264 三色带（32/128/224）成片按通道测量，以及“旧曲线节点先、白平衡后”的合成顺序与 legacy 色调在前。全量 22 项 Python 检查、4 项 Node 检查、Ruff/格式与 TypeScript 通过。

界面在同一条 HTTP 服务上实测：新增曲线节点 → 双击加控制点 → 一次拖动（同一任务内连发 pointer 事件） → 新增 RGB 增益节点并拖动色轮 → 新增白平衡并用数值输入，工程从 r6 走到 r13，逐笔对应一次修订；撤销按钮回到 r14 并把色温恢复为 0。过程中修掉两个真实缺陷：同一帧内连发 pointerdown/move/up 会丢掉拖拽提交（改用 ref 记录草稿），以及新增节点后被选中索引钳位逻辑立刻弹回上一个节点。浏览器预览确认 `filter: … url(#g602c30fcf45e90bc)` 已作用在画面层，`<filter>` 内三条 `feFunc*` 各 256 项且 `color-interpolation-filters=sRGB`。

仍待完成：色彩节点图（并联/分层/mix 值/串行与层序 UI）、亮度曲线与 LUT 导入、完整色彩管理、路径遮罩与跟踪、自动语音字幕、曲线变速与速度图、代理回放、4K 长工程性能。色轮盘只改彩度，不提供达芬奇的亮度枢轴拖动，整体亮度仍需用数值或曝光；内置浏览器标签页视口为 0×0，本轮界面几何（1040×660 无横向溢出）未重测，界面证据是 DOM/HTTP 级。


1.16.0 发布验收：冻结引擎单独实测通过——`/health` 带 instance、导入真实素材、`clip.grade` 写入 r1、`h264-source-quality` 输出 1920×1080 3.000 秒，三色带九通道实测与独立参考曲线最大偏差 3.49 LSB，同一次 preview-manifest 的 LUT 与参考最大偏差 0.12 LSB；包内 `agentcut.exe mcp` 通过 stdio 写 `clip.grade`（r1→r2），后续编辑不改锁定 r1 的成品字节。ASAR 内 renderer 3 个文件与本地构建逐字节一致，包内引擎 97 个文件。原生窗口本轮首次直接操作：`release/win-unpacked/AgentCut.exe` 与根目录便携版都启动到「AgentCut 剪辑台」1480×900，真实 F1 打开帮助、UIA 点击切换标签、Esc 关闭、点关闭按钮退出后无残留 AgentCut/agentcut 进程。便携版 132,381,691 字节 SHA256 3B7E924D36DA3B785E067DD157C3D6D387B21F99D0A8BC97FAADDA068DD766EC；安装版 132,542,400 字节 SHA256 B508C617318E87879AB6B7B649F0016E6761F82346FB37FA477B540FD183409A；根目录 AgentCut.exe 已同步 1.16。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.16-交付记录.md`。

## 1.17 自由路径遮罩（2026-10-06）

补上 AE 式钢笔遮罩：片段的遮罩可以是 3..64 个顶点的闭合路径，每个顶点带进出贝塞尔控制柄（相对偏移 -1..1，全零即直线段）。界面在画面上直接编辑：拖顶点改形状、拖小方块拉出控制柄、双击加一个点、选中后方向键微调、Delete 删点（少于 3 个拒绝），检查器保留羽化与反转，形状下拉新增「路径」。参考 [Adobe 官方遮罩与路径说明](https://helpx.adobe.com/after-effects/using/creating-shapes-masks.html) 的钢笔交互原则，实现为原创代码，未复制任何商业素材。

一次几何、两份产物：masks.py 把顶点表按弦高自适应细分成折线，用 4 子行偶奇扫描线求每像素覆盖率（边界按亚像素重叠计权，天然抗锯齿），需要羽化时做可分离高斯（半径 = feather×0.25×画面短边像素），再写成灰度 PNG（stdlib zlib，无新依赖）。FFmpeg 侧把这张 PNG 作为 `-f image2 -loop 1` 静止输入，`alphaextract` 取源 alpha、`scale2ref` 对齐帧尺寸、`blend=all_mode=multiply` 相乘、`alphamerge` 合回，因此不透明度动画、缩放/旋转、转场权重与轨道混合继续走既有链路，不必逐像素判定多边形。浏览器侧使用同一顶点表的 SVG `<path>` 数据 URI，viewBox 取 1000 单位等比坐标，使 `feGaussianBlur` 的 stdDeviation 与 PNG 的像素半径一致。空/非路径遮罩保持原 `geq` 表达式与原有矩形/椭圆行为不变。

契约：`ShapeMask.shape` 增加 `"path"` 并新增 `vertices`；`clip.mask`、`clip.patch`、HTTP/MCP、锁轨、事务、历史、拆分/修剪与 `detach_audio` 清副本沿用同一条 reducer。capabilities 增加 `path_masks=true`；工程 schema 仍为 v10，默认 `vertices=null` 从请求指纹剔除，v1–v9 旧遮罩回执继续重放。

验收：`tests/pathmask_check.py` 覆盖几何（三角形面积 0.25、贝塞尔圆角面积大于凸包、内部不透明）、PNG 经 FFmpeg 解码后与栅格逐点一致、反相与羽化斜坡单调、真实成片像素（红/绿三色判定）、嵌套合成内的路径遮罩、HTTP 写入/重放/409/dry-run/锁轨/声音拒绝/降序与重合顶点/少于 3 点拒绝、preview-manifest 与只读 `/v1/mask/preview` 候选、以及旧形状遮罩兼容。全量 23 项 Python 检查、4 项 Node 检查、Ruff/格式与 TypeScript 通过。

界面在同一条 HTTP 服务上实测：选片段 → 形状切到「路径」（r2）→ 双击加顶点（r4）→ 拖动顶点到 0.63/0.48（r3）→ 方向键微调 0.45→0.46（r8）→ Delete 删点回到 3 顶点（r9）→ 拉出出站控制柄 handle_out=[-0.08,-0.39]（r10）→ 羽化数值 30%（r11）→ 撤销恢复羽化到 r12。预览层 `mask-image` 实际携带 `data:image/svg+xml,%3Csvg…%3Cpath` 数据 URI。过程中修掉三个真实缺陷：路径闭合时最后一段取 `point(index+1)` 越界导致整个预览子树崩溃；每次工程更新后选中顶点被 `[clip, …]` 依赖的副作用清空，使键盘改点完全失效（改为只在片段 id 变化时清空）；以及嵌套合成只合并子计划的文本文件、丢掉遮罩 PNG，导致 FFmpeg 打不开输入。另把指针捕获失败改成非致命（记录 captured 标志），否则部分环境一次拖动都无法开始。

性能：大羽化若按全分辨率做精确高斯，核半径会到 200+ 采样，实测一次遮罩编译要 9.2 秒，逐帧取样的合成帧接口不可接受。mask_png 因此按 `MAX_SIGMA=8` 自适应降低模糊网格分辨率（覆盖图直接在该分辨率重算），FFmpeg 的 `scale2ref` 与浏览器矢量各自放大还原；同一顶点表实测降到 0.08–0.4 秒，且成片像素仍呈单调软边。

仍未完成：遮罩随时间动画与跟踪、节点色彩图（并联/分层/mix、亮度曲线、LUT、色彩管理）、自动语音字幕、曲线变速与速度图、代理回放、4K 长工程性能。路径遮罩按帧静态求值，逐帧成本是一次 alpha 合成，未做遮罩缓存。

## 1.18 曲线变速与冻结帧（2026-10-06）

把「变速」从固定倍速升级成剪映式的速率折线：片段可以携带一条 0–400% 的分段线性曲线，0% 即冻结帧。交互面在检查器「曲线变速」：四个预设（慢入/慢出/蒙太奇/冻结结尾）一键起型，折线上拖控制点改时间或速率、双击加点、方向键微调、Delete 删点（至少 2 个），面板标题显示当前点数；图片、文字与嵌套合成会显式说明「曲线变速只适用于视频与音频片段」，而不是让按钮失效没有解释。参考剪映「曲线变速」的预设 + 折线交互与达芬奇变速段的「一段一个恒定速率」编译思路，实现为原创代码。

一次编译、两处消费。`speed.py` 把折线按节点与陡度自适应切成不超过 48 段恒定速率：边界对齐到帧（视频轨）或采样（声音轨）时钟，段间共用累积源位置，所以既不跳帧也不重复；`segments()` 同时给出时间轴窗口、素材窗口与速率，`describe()` 换成秒制给浏览器。`render.py` 据此出图：`split` 出等长流后每段 `trim + setpts=(PTS-STARTPTS)*ratio + fps`，最后 `concat`；速率为 0 的段取 `hold`（窗口里真实存在的最后一帧）再 `tpad=stop_mode=clone`，声音用 `atrim + atempo…` 链，冻结段取一个采样后 `apad` 成静音。preview-manifest 每个片段带只读 `speed` 分段，`Preview.tsx` 经 `time.ts` 的 `pacing()` 设置 `playbackRate`/`currentTime`，速率为 0 时暂停并停在 `hold` 帧。曲线段的素材读取长度改由积分决定：`consumed_source_ticks` 同时用于时间线越界校验与输入 `-t` 窗口，四倍速曲线因此能读满四倍素材（旧实现按固定倍速开窗，会让曲线尾段读空、成片短于片段）。

契约与 reducer：`Clip.speed_curve`（2..64 点，`at_ticks` 严格递增、首点为 0、末点不超过时长，`percent` 0..400）与 `clip.speed_curve {clip_id, points|null}`；`clip.speed` 改基础倍速时等比缩放折线时间轴，素材窗口不变；拆分/修剪以存活窗口为零点重写折线；曲线不得与图片/文字/嵌套、音画链接或转场共存（`INVALID_SPEED`），越界为 `SOURCE_OUT_OF_BOUNDS`。capabilities 增加 `speed_curve=true` 与命令 `clip.speed_curve`，MCP 由契约自动生成 schema；默认 `speed_curve=null` 从请求指纹剔除，v1–v9 回执继续原样重放。

过程中修掉五个真实缺陷：切段后音频链尾部多写一个逗号，使整张滤镜图报「Filter not found」；`fit` 与尾部 `trim` 之间的逗号被吞掉，报「Option not found」；冻结段从窗口末尾之后取帧，导致成片只有运动段那么长；以及 `ramp_*` 里把秒制字符串当浮点做算术。第五个是听感缺陷：声音段原本按采样时钟切分，4 秒 U 形曲线被切成 47 段 83 ms 的碎片，逐段换速的拼接缝会打出咔哒声；改为切分粒度统一由帧时钟决定（源位置仍按采样对齐、总量守恒）后只剩 11 段、最短 333 ms，速率序列与画面对称。`tests/speedramp_check.py` 与 `tests/desktop_speed_check.ts` 都做了变异验收：把导出侧冻结段的取帧位置改回窗口末尾，成片立刻短于片段、像素检查变红；删掉浏览器 `pacing()` 的窗口上界钳制，越界读取被断言抓住。

界面在同一条 HTTP 服务上实测（vite 渲染层 + 引擎）：点片段 → 打开「曲线变速」→ 点「蒙太奇」预设（r2 落库 4 个点）→ 在折线上拖动第二个控制点（一次手势一个 revision，r3，percent 25→60）→ 播放头定位后 `<video>` 的 `playbackRate=0.35`、`currentTime=1.505`，与引擎分段给出的数值逐位一致（片段起点为 0.9）→ 换「冻结结尾」并定位到 00:00:03:15，元素停在 `currentTime=2.966666`（第 89 帧）且 `paused=true`、无「超出浏览器连续播放范围」告警。内置标签页视口为 454×341 且处于隐藏状态，界面几何（1040×660 无横向溢出）本轮未重测，界面证据是 DOM/HTTP 级。

1.18.0 发布验收：`npm run dist` 产出便携版与安装版。包内冻结引擎 `/health` 带 instance、media/render 就绪，capabilities 报 `project_schema_version=10` 且 `features.speed_curve=true`、`commands` 含 `clip.speed_curve`；真实素材导入后写曲线（r1），preview-manifest 给出 9 段（首段 90%），400% 越界曲线被 `SOURCE_OUT_OF_BOUNDS` 拒绝且不落库；`h264-source-quality` 输出 1920×1080 4.000 秒 + AAC，画面红分量 t=0.5/2.0/3.9 为 27.0/79.0/151.0、主频 439 Hz；包内 `agentcut.exe mcp` 通过 stdio 写冻结曲线（r1→r2，百分比 `[100,20,0,0]`），后续编辑不改锁定 revision 的成品字节；ASAR 内 renderer 3 个文件与本地构建逐字节一致，包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900 并由 Windows Graphics Capture 截图确认工作台完整渲染，终止后无 AgentCut/agentcut 残留进程。修复第五个缺陷后重冻结引擎并重新打包，包内引擎与 ASAR 全部重新逐字节比对通过。便携版 132,407,930 字节 SHA256 738CF2D65CF7A58BBE76F34D9FCF91D25F6896E0B62B43ED61CAD5AA12F9452D；安装版 132,568,649 字节 SHA256 6238F9765014C8A8FF5E6777C4CA9624DA0F294CAA01A5824E6BDE59C6FEF893；根目录 AgentCut.exe 已与便携版同步。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.18-交付记录.md`。

仍未完成：遮罩随时间动画与跟踪、色彩节点图（并联/分层/mix 值、亮度曲线、LUT 导入、完整色彩管理）、自动语音字幕、代理回放、4K 长工程性能与签名分发。曲线变速是分段恒定速率的近似（≤48 段），冻结是复制同一帧而非光流补帧，声音在极端速率段仍会被拉伸；曲线不与转场、音画链接、图片/文字/嵌套共存，界面会说明原因而不是静默降级。

## 1.19 调色节点强度（2026-10-06）

给 1.16 的串行调色链补上达芬奇的 Mix 语义：三类节点（曲线 / 白平衡 / RGB 增益）各自带一个 `mix: 0..1`，节点先算出自己的结果，再与该节点的输入按 `out = in + mix*(node(in) - in)` 逐通道线性插值，`mix=0` 等同于跳过该节点。这是路线图里「色彩节点图」中唯一能保持**单张每通道表**这一既有权威形态的子能力（并联/分层、亮度曲线、LUT、色彩管理都要跨通道，仍未实现），所以编译路径完全不变：`grade.py` 在合成折线时对每个启用且 `mix>0` 的节点施加这个插值，FFmpeg `lutrgb` 表达式与浏览器 `feComponentTransfer` 表继续采样自同一条多段线；全链 `mix=0` 与空链一样不产生任何滤镜、不申请 LUT。

契约：`GradeCurve/GradeWhiteBalance/GradeWheels` 增加 `mix`（默认 1.0），命令仍是 `clip.grade` 与 `clip.patch.color.grade`；capabilities 增加 `grade_node_mix=true`；工程 schema 仍为 v10，默认 `mix=1.0` 在请求指纹里剔除，1.16–1.18 写下的不含 `mix` 的节点载荷与回执原样重放（`tests/grade_check.py` 直接对比两种载荷的指纹摘要）。界面在节点下方加「节点强度」数值（0–100%，步进 5），节点列表在非 100% 时把百分比标在名字后。

验收：`tests/grade_check.py` 的独立参考实现同步加入 mix 插值，新增半强度曲线的每通道表实测等于「恒等与满强度」的中点（5 个采样点、三通道，误差 <1e-6）、`mix=0` 时 manifest 的 `grade` 为 `null` 且滤镜图里没有 `lutrgb`、`mix=1.5` 在契约层 422 且整笔不写、旧形状节点与新形状指纹一致；真实成片新增 `halfmix.mp4`：半强度链九通道实测与独立参考最大偏差 ≤4 LSB，且与满强度的偏差 >6 LSB（证明强度真的改变了像素而不是被忽略）。变异验收：把 `grade.py` 的插值退回 `inner(value)`，半强度断言立刻变红（实测 `(40, 0.094117647)`）。

界面在同一条 HTTP 服务上实测（vite 渲染层 + 引擎）：选片段 → 打开「调色节点」→ 新增色调曲线（r2，服务端存下 `mix: 1`）→ 节点强度输入 50（r3，落库 `mix: 0.5`）→ 新增白平衡（r4）→ 色温输入 100（r5）→ 第二个节点强度输入 50（r6）。每笔一个 revision。此状态下 preview-manifest 的 `grade.id` 为 `g063fa2f9378bb35a`，输入 100/255 处三通道表值实测 r=0.450980、g=0.392157、b=0.333333，与「恒等与满强度中点」的独立算术值（1.15×、1.0×、0.85× 再取半）逐位吻合，画面层 `filter` 仍带 `url(#g063fa2f9378bb35a)`；节点列表把强度标成「1. 色调曲线 · 50%」。验收中确认的一处界面事实：React 的 `onBlur` 监听 `focusout`，脚本只派发 `blur` 时数值不会提交（真实浏览器两者都会触发，属测试台架问题，未改产品代码）。

仍未完成：色彩节点图的并联/分层与节点连线视图、亮度曲线、LUT 导入与完整色彩管理、遮罩随时间动画与跟踪、自动语音字幕、代理回放、4K 长工程性能与签名分发。节点强度只作用于该节点自身结果，不提供跨节点的混合模式（正片叠底/滤色等仍只在轨道层）。

1.19.0 发布验收：冻结引擎重编译 `--verify` 通过后重新打包。包内引擎 `/health` 带 instance、media/render 就绪，capabilities 报 `grade_node_mix=true`；写入 `[曲线 mix0.5, 增益 mix0.25, 白平衡 mix0]` 落库强度序列 `[0.5,0.25,0.0]`，preview-manifest 每通道表与独立参考最大偏差 0.182 LSB，`h264-source-quality` 输出 1920×1080 3.000 秒、九通道实测 `[[33,149,228],[26,140,219],[24,136,215]]` 与参考最大偏差 3.13 LSB；包内 `agentcut.exe mcp` 通过 stdio 写 `mix=0.35`（r1→r2 读回一致），后续编辑不改锁定 revision 的成品字节；ASAR 内 renderer 3 个文件与本地构建逐字节一致，包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染，终止后无 AgentCut/agentcut 残留进程。便携版 132,408,939 字节 SHA256 CCD827D66CB0F1A68544ACC5F7300668D3DB475896632C52A7DBA74D4EF446FE；安装版 132,569,650 字节 SHA256 493BF286BDCBDFFA01510DBC12217288EAFEAE4C9EFF492A009900B7BE2D908E；根目录 AgentCut.exe 已与便携版同步。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.19-交付记录.md`。

## 1.20 遮罩关键帧（2026-10-06）

把矩形/椭圆遮罩的盒参数 `mask_x`、`mask_y`、`mask_width`、`mask_height` 纳入既有关键帧体系，而不是另开一套遮罩动画：属性名进 `Property` 联合类型与 `PROPERTY_LIMITS`（中心 0..1、宽高 0.01..2，越界 422 带字段路径），写入仍走 `keyframe.set` / `keyframe.remove` / `keyframe.move`，`clip.patch` 的 `effects` 不接受遮罩属性——遮罩的运动只能由关键帧表达，界面因此能逐属性显示 ◇ 状态。capabilities 增加 `mask_animation=true`，MCP 的 `keyframe.set` schema 由契约自动生成就带上这四个名字。工程 schema 仍为 v10、没有新增默认字段，1.16–1.19 的载荷与回执原样重放。

两侧共用一条曲线的理由是映射可交换：导出把每个动画属性编译成帧时间 `T` 的表达式（`animation.expression` 给每个属性分配一对 `st/ld` 逐帧缓存寄存器，同一帧只求值一次），`masks.alpha_expression(mask, values)` 把盒参数从常量换成表达式，其余公式一字不改——椭圆仍是 `sqrt(pow(x,2)+pow(y,2))`，羽化仍是 `clip((1-r)/feather,0,1)`，`geq` 仍以 `a='alpha(X,Y)*(…)'` 把遮罩乘进素材 alpha，所以软边缘是随盒子平移的斜坡而不是一张静态图。浏览器不重画几何：preview-manifest 下发一张单位遮罩 SVG（圆心 0.5/0.5、盒 1.0/1.0）与每属性的归一化控制点，`MaskPicture` 用四个注册成 `<number>` 的 `@property` 自定义属性经 `calc()` 驱动 `mask-size/mask-position`，图层像素尺寸由 ResizeObserver 写入 `--mask-lw/--mask-lh`。归一化坐标到像素是线性映射，与时间插值可交换，因此每一帧浏览器的遮罩边界与导出的 alpha 边界是同一个数，而不是两套近似。

本轮修掉一个真实交付缺陷：这条规则原本写了两遍——`Clip` 上一个 model validator 加 `validate_timeline` 一处判定。实测在已打关键帧的遮罩上点「反相」或删掉遮罩，客户端收到的却是 `PROJECT_LIMIT「project exceeds the supported contract limits」`：reducer 原地改写字段后 `apply_edits` 末尾要 `Project.model_validate(root.model_dump())` 往返重校验，契约层那份抢先抛出生成式校验错误，被统一压成了与原因无关的「工程超限」；而它声称要保护的原地改写路径根本不会触发它。删掉契约层那份、只保留 `validate_timeline` 调 `clip.mask_animation_problem()` 之后，返回的是 `INVALID_MASK` + `clip_id` + 具体原因，整笔回滚、revision 不动。反相遮罩保留的是盒子外部、盒子的运动无法由同一条 alpha 公式表达，路径遮罩无法逐帧验证边界，两者都明确拒绝并在界面上隐藏 ◇，而不是给一个会骗人的预览。

验收 `tests/maskanim_check.py`：采样曲线 0.25→0.75 每帧递增 0.5/90 且 `mask_y` 保持 0.5；滤镜图的 alpha 分量含 `if(lt((T` 分段、静态遮罩则不含；贝塞尔属性各自展开成 `st(11,T+1);st(10` 与 `st(13,T+1);st(12` 两对寄存器；manifest 的 `mask_curves` 只列出被动画的属性、`mask_unit` 是 100×100 单位的 SVG data URI，无动画遮罩的片段两项均为 `null`；HTTP 一笔写四个点只涨一个 revision、同 request_id 重放不涨、旧 revision 409、dry-run 不写库、`/clips/c/sample` 在第 45 帧给出 mask_x 0.5 与 mask_height 0.55、`/v1/animation/curve?property=mask_height` 给出两点与 `limits=[0.01,2]`；删遮罩/反相/改路径三种写法都返回 `INVALID_MASK` 且工程回到原 revision；带 `animation_offset_ticks` 的修剪片段仍按存活窗口取曲线。真实像素：480×270 白场 3 秒，椭圆中心 0.25→0.75，t=0.1 实测 (0.33)=255、(0.6)=0，t=1.5 两侧都 255 而 0.28/0.72 都 0，t=2.9 翻成 (0.33)=0、(0.6)=255；羽化 0.15 的同一曲线在边缘 0.45 处实测半透明、t=2.9 时 0.65 处已全亮，证明软边缘真的跟着走。变异验收两处：把导出 alpha 退回静态盒，像素断言立刻变红（实测 `(255.0, 0.0)`）；删掉 `validate_timeline` 的判定，`rejection_suite` 立刻报「no mask must reject mask keyframes」。全量门禁：`ruff check`、`ruff format --check`（44 文件）、25 个 Python 检查、5 个桌面 TS 检查与 `npm run typecheck` 全绿。

界面在同一条 HTTP 服务上实测（vite 渲染层 + 引擎，工程「遮罩关键帧验收」，椭圆羽化 0.1，`mask_x` 0.25→0.75 与 `mask_height` 0.8→0.3）：检查器遮罩区四行各带 ◇，其中「中心 X／高度」在播放头 0 处显示为已激活；播放头定位后画面层 `--mask-lw=442.438 / --mask-lh=247.984`，t=0 时 `mask-size=176.975px 198.387px`、`mask-position=22.1219px 24.7984px`（=0.4×442.438、0.8×247.984、(0.25−0.2)×442.438、(0.5−0.4)×247.984）；拖标尺到 00:00:01:15 得 `--mask-x=0.5, --mask-h=0.55` → size `176.975px 136.391px`、position `132.731px 55.7964px`；到 00:00:03:00 得 0.75/0.3 → position `243.341px 86.7944px`、size 高 74.395px；到 00:00:00:23（23 帧）得 0.377778/0.672222，与引擎 `0.25+0.5×23/90` 逐位一致。把「中心 X」在 1.5 秒处输入 60 并提交：一次写入只涨一个 revision（r1→r2），库里 `mask_x` 关键点变成 (0,0.25)(1.5,0.6)(3,0.75) 而静态 `center_x` 仍是 0.25，画面 `--mask-x` 立即 0.6、position 176.975px。两条台架事实记录在案：合成 PointerEvent 的 `pointerId` 不存在时 `setPointerCapture` 会抛错，必须先桩掉才能模拟标尺拖动；内置标签页 454×341 时固定的 300 px 时间线会把预览挤到 0 高，因此数值都在 1280×800 的同源 iframe 里读取。按 Electron 强制的最小窗口 1040×660 实测：编辑区高 594、时间线 300、预览监视器 196×110、画面层 194×108，用户可拖时间线上缘的分隔条把时间线压到下限 180 px（可调范围 180 .. 窗口高−320）换回监视器高度，界面没有横向溢出。

仍未完成：路径遮罩的关键帧动画与遮罩跟踪（两者需要逐帧重栅格化或运动估计）、色彩节点图的并联/分层、亮度曲线、LUT 导入与完整色彩管理、自动语音字幕、代理回放、4K 长工程性能与签名分发。遮罩关键帧只作用于盒参数，`feather` 与 `inverted` 不随时间变化；反相遮罩与路径遮罩上打关键帧会被明确拒绝。

1.20.0 发布验收：冻结引擎重编译 `--verify` 通过（裸启动冷启动 617 ms、`mcp` 模式存活、无 ffmpeg 参数时诚实报告 `media_ready`）。包内引擎 `/v1/info` 报 `app_version=1.20.0` 且 `frozen=true`、`/health` 带 instance，capabilities 报 `project_schema_version=10`、`features.mask_animation=true`、`commands` 含 `keyframe.set` 与 `keyframe.remove`；一笔写四个遮罩关键点得 r1，preview-manifest 的 `mask_curves` 只含 `mask_x`/`mask_height`、`mask_unit` 为单位遮罩 SVG，`/clips/c/sample` 第 45 帧给出 `mask_x=0.5`、`mask_height=0.55`；把遮罩改成反相被 `INVALID_MASK`（422、带 `clip_id`）整笔拒绝，revision 仍为 1 且关键点未丢。`h264-source-quality` 输出 480×270 3.000 秒，八个采样点实测 `(0.1,0.33)=255 (0.1,0.6)=0 (1.5,0.33)=255 (1.5,0.6)=255 (2.9,0.33)=0 (2.9,0.6)=255 (1.5,0.28)=0 (1.5,0.72)=0`，包内引擎导出的遮罩确实随曲线走。包内 `agentcut.exe mcp` 通过 stdio 写 `mask_width` 关键点（r1→r2，读回 `(105840000, 0.7)`），同一通道把 `at_ticks` 传成 `1.5×TIMEBASE` 的浮点被拒（整数 tick 规则在 MCP 边界同样生效）；后续编辑不改锁定 revision 的成片字节。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染（标题栏「引擎在线」、素材库带真实缩略图、三轨时间线、检查器与空监视器提示），`taskkill` 后无 AgentCut/agentcut 残留进程。便携版 132,410,174 字节 SHA256 5219BE8D7A8EED37B13036470097BDF362A7F6C8D78832186C9B06A7E08ACCF1；安装版 132,570,894 字节 SHA256 0D9B7796C6DF9A8618D867019EDA284DE8656664E595FC469B64B81B666498E1；根目录 AgentCut.exe 已与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.20-交付记录.md`。

## 1.21 代理回放（2026-10-06）

预览的瓶颈从来不是时间线，而是浏览器每一帧都要解码原始素材：1080p 尚可，4K 手机素材拖动播放头就掉帧。剪映和达芬奇都用代理解决——把原片转码成小副本只用于播放。本轮补上这一条，并且刻意**不把代理写进工程**：代理是派生文件，写进工程状态会带来三个后果——换机器/换人打开时被偷偷改了画质、请求指纹与回执要跟着变、导出可能误读副本。因此它属于媒体服务，与缩略图、波形同放内容寻址缓存 `<hash[:2]>/<hash>/proxy-<width>.mp4`，旁边一份 json 记录探测得到的真实宽高、时长、帧率与源哈希；状态判定只信这份记录，源文件换了内容就是另一个目录，旧代理自然失效。

转码参数固定：`scale=<width>:<原高>:force_original_aspect_ratio=decrease` 只缩不放、`libx264 -preset veryfast -crf 27 -pix_fmt yuv420p`、`-r num/den` 保持源帧率、GOP 取两秒并 `-sc_threshold 0` 便于随机定位、`-movflags +faststart` 让 moov 前置以便边下边播，有声音才 `-c:a aac 128k` 否则 `-an`。先写临时文件，探测确认时长与源相差不超过两帧才改名入库，否则删除并报 `PROXY_FAILED`。端点三个：`GET .../assets/{id}/proxy?width=` 读状态、`POST` 同路径构建、`GET /v1/assets/{id}/proxy/stream?project_id=&width=&sig=` 以 `proxy:{project}:{asset}:{width}` 签名流式读取；宽度只接受 480/640/960/1280，越界 `INVALID_REQUEST`，非本工程素材 `NOT_FOUND`，文字或未验证素材 `UNVERIFIED_ASSET`，未构建就取流 409。capabilities 的 `proxy_playback` 与 `media_ready` 绑定，没有 ffmpeg 时不声明可用；MCP 不暴露代理工具，Agent 无法用代理改变画质。界面在预览标题行提供「代理」下拉（关闭/640/960/1280），选择记在浏览器本地存储（工作站偏好，不属于工程），就绪后 `app.streams` 用代理地址覆盖原片地址并在监视器标「代理 960p」，构建失败如实回退原片并说明原因。

验收 `tests/proxy_check.py`：1920×1080 30fps 4 秒源 2,868,795 字节转 960×540 代理 259,129 字节（实测小 11.1 倍），代理时长与帧率 `30/1` 与源一致、`has_audio` 为真；同一时刻两侧整帧三通道均值源 `(124.33,129.56,125.72)` 对代理 `(124.44,129.53,125.86)`，最大偏差 0.14 LSB，代理定位到 2.9 秒仍有画面；HTTP 侧构建后工程 revision 不变、`compile_render_plan` 的 argv 逐字节相同、篡改签名 401、未构建宽度 409、非法宽度 `INVALID_REQUEST`、文字素材 `UNVERIFIED_ASSET`、同路径换内容后状态回到 `absent`、第二次构建命中缓存（代理文件 mtime 不变）、新工程引用同一份媒体直接 `ready`。变异验收两处：把 `scale` 换成 `iw:ih`（不缩放）后 `display_width` 断言立刻变红（实测 1920）；去掉代理流的签名比较后篡改签名的断言变红。全量门禁：`ruff check`、`ruff format --check`（45 文件）、26 项 Python 检查、5 项桌面 TS 检查与 `npm run typecheck` 全绿。

界面在同一条 HTTP 服务上实测（vite 渲染层 + 引擎，工程「代理回放验收」，1920×1080 6 秒源）：「代理」下拉给出 关闭/640p/960p/1280p 四档；初始 `<video>` 的 `currentSrc` 是 `/v1/assets/hd/stream`、解码尺寸 1920×1080；选 960p 后引擎完成转码，`currentSrc` 变成 `/v1/assets/hd/proxy/stream?...&width=960&sig=…`、`videoWidth×videoHeight` 实测 960×540、标题行出现「代理 960p」标签；拖标尺到 00:00:04:15 / 00:00:00:15 / 00:00:05:27，`currentTime` 依次为 4.5 / 0.5 / 5.9，与播放头逐位一致；选回「关闭」后 `currentSrc` 回到原片地址、解码尺寸回到 1920×1080、标签消失。代理数值的测量都在 1280×800 的同源 iframe 里读取（内置标签页 454×341 低于应用强制的最小窗口，见 1.20 记录）。

仍未完成：代理的自动生成与清理策略（当前按用户选择构建，缓存只增不减，需要磁盘配额与回收）、4K 长工程导出性能、遮罩跟踪、路径遮罩关键帧、色彩节点图、自动语音字幕、代码签名。代理只影响预览画面：导出与合成帧截图（示波器读的那张由服务端 FFmpeg 从原片生成）都不读代理。
1.21.0 发布验收：冻结引擎重编译 `--verify` 通过后重新打包。包内引擎 `/v1/info` 报 `app_version=1.21.0`、`frozen=true`；capabilities 报 `features.proxy_playback=true` 且 `commands` 里没有任何代理命令；`GET .../assets/hd/proxy?width=960` 初始 `absent`、`width=800` 返回 `INVALID_REQUEST`，`POST` 构建得 960×540 代理 259,129 字节（原片 2,868,795 字节，实测小 11.1 倍）、时长 4.018 秒、`has_audio=true`、帧率 `30/1`；签名流返回 200 且 `Accept-Ranges: bytes`、字节数与记录一致，篡改签名 401，未构建的宽度 409。构建代理后工程 revision 不变、`GET /render-plan` 的 `argv_preview` 与构建前逐字节相同且不含 `proxy-`；`h264-source-quality` 输出 640×360 4.000 秒 + AAC，导出帧左缘/中部实测 253.0/0.0（证明画面按原片解码）。包内 `agentcut.exe mcp` 的 `tools/list` 中没有任何代理工具（`proxy_tools=[]`），`timeline_edit` 写不透明度关键帧 r1→r2 正常，后续编辑不改锁定 revision 的成片字节。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染且预览标题行出现新的「代理 关闭」下拉；`taskkill` 后 `Get-Process AgentCut,agentcut` 再查无残留。便携版 132,414,940 字节 SHA256 1C4DF53A120B6127C8BF2EE18F2C059D8A2821CDDDDF4199BD395A5CC2570444；安装版 132,575,666 字节 SHA256 FCA51AAAD33AD1651B72FFF9E5026029C74F2686B4A628F6783C911D4C0522D1；根目录 AgentCut.exe 已与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.21-交付记录.md`。

## 1.22 代理缓存配额（2026-10-06）

1.21 的代理缓存只增不减：每份副本几十到几百 MB，剪几个 4K 素材就能吃掉几十 GB，而用户没有任何办法看到或收回这块空间。本轮补上配额与回收，并把「谁该被删」这件事交给实际播放来决定。

三条规则。其一，**上限在构建点执行**而不是后台扫描：新代理落盘后立刻统计总量，超限就从最久未使用的一份开始删，并保护刚构建的那份——这样不需要常驻清理线程，也不会出现「刚生成的代理被自己清掉」。默认 4 GiB，用 `AGENTCUT_PROXY_CACHE_BYTES` 覆盖；这是部署者的决定，不进工程。其二，**淘汰顺序跟随播放**：`GET .../proxy/stream` 命中时显式把该文件的 atime 推到当前时间（Windows 上不能指望读取自动更新 atime，必须 `os.utime`），所以编辑器里正在看的那份不会被挤掉。其三，**回收范围只有派生副本**：`proxy-*` 之外的源文件、`tile-*.jpg`、`wave.json`、`cache.json` 永不动，孤儿 sidecar（没有对应视频的 json）在扫描时顺手删除。清理不是编辑：不产生 revision，也不改任何工程数据。

新增两个维护端点：`GET /v1/media/proxies` 汇总 `{limit_bytes, used_bytes, proxies:[{source_sha256,width,size_bytes,used_at}]}`（不暴露服务器绝对路径），`POST /v1/media/proxies/prune` 收 `{max_bytes}`（`null` 用默认上限，负数 422）并返回 `{limit_bytes, used_bytes, freed_bytes, removed[]}`。两个路由都声明在 `/v1/media/{probe_id}` 之前——否则字面路径 `proxies` 会被参数路由吃掉，实测这样才拿到列表而不是「探针不存在」。界面在预览标题行显示「代理占用 x MB / n 份」和「清理代理」按钮，无代理时两者都不出现。

验收 `tests/proxyspace_check.py`：把上限设成第一份代理的字节数 +1000（实测 74,380 字节），构建第二份后缓存只剩 1 份、`used_bytes` 不超过上限、被淘汰的正是更早那份，而源文件、`cache.json` 与 `tile-00.jpg` 都还在；LRU 顺序按使用——先构建 960 再构建 640，然后 `touch_proxy` 把 960 那份推到最新，按第一份的大小清理时释放的恰好是 640 那份、960 存活；孤儿 sidecar 被扫描删除且不计入占用；HTTP 侧 `used_bytes` 与构建响应的 `size_bytes` 一致、列表项字段集合精确为四键、取流后 `used_at` 不下降、`max_bytes=-1` 得 422、清空后再取流得 409、清理后工程 revision 不变且能重新构建。变异验收两处：把淘汰循环的 `reversed(entries)` 改成 `entries`（先删最新）后，释放字节的断言立刻变红（实测被淘汰的是刚播放过的 960 份）；把构建后的配额上限改成 `1<<62`（等于不清理）后，`used_bytes` 118,304 超过上限 74,380 被断言抓住。全量门禁：`ruff check`、`ruff format --check`（46 文件）、27 项 Python 检查、5 项桌面 TS 检查与 `npm run typecheck` 全绿。

界面在同一条 HTTP 服务上实测（vite 渲染层 + 引擎，工程「代理配额验收」，1920×1080 6 秒源）：选 960p 构建完成后，标题行同时出现「代理占用 0.4 MB / 1 份」与「代理 960p」，`<video>` 解码 960×540，服务端 `GET /v1/media/proxies` 报 `used_bytes=378053`、`limit_bytes=4294967296`、`count=1`；点「清理代理」后两个标签与按钮一起消失、`<video>` 回到原片地址并解码 1920×1080、下拉复位为「关闭」、提示条给出「代理缓存已清理 释放 0.4 MB 派生副本；原片、缩略图与工程都未改动。」，服务端复查 `used_bytes=0`、`count=0`。

仍未完成：代理的**自动**构建（仍要用户选档位；理想是导入后台排队，但需要与磁盘配额和 CPU 抢占一起设计）、缩略图/波形的配额（当前只回收代理）、4K 长工程导出性能、遮罩跟踪、路径遮罩关键帧、色彩节点图、自动语音字幕、代码签名。
1.22.0 发布验收：冻结引擎重编译 `--verify` 通过后重新打包。包内引擎 `/v1/info` 报 `app_version=1.22.0`、`frozen=true`；空缓存下 `GET /v1/media/proxies` 精确返回 `{limit_bytes: 4294967296, used_bytes: 0, proxies: []}`；构建 960p 代理得 143,455 字节，清单 `used_bytes` 与之相等、条目字段恰为 `source_sha256/width/size_bytes/used_at` 四键（不含服务器路径）；取流 200 且字节数一致，取流后 `used_at` 不下降；`POST /v1/media/proxies/prune {"max_bytes":0}` 释放 143,455 字节、随后取流 409、`max_bytes:-1` 得 422，工程 revision 与 `render-plan` 的 `argv_preview` 均未改变，且能立即重建。第二个包内实例带 `AGENTCUT_PROXY_CACHE_BYTES=1` 启动：`limit_bytes` 如实为 1，先后构建两份 640p 代理后只剩较新的那份（`used_bytes=44924`），早先那份状态回到 `absent`，而两份 `tile-00.jpg` 缩略图都还在——冻结二进制里环境变量、配额与「只回收代理」三条都成立。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染、预览标题行的「代理 关闭」在位且缓存为空时不显示占用标签；`taskkill` 后无 AgentCut/agentcut 残留进程。便携版 132,419,234 字节 SHA256 ED5CE5337BBCDA38D0FF8A672B1CBE13753F2CA1CD828EF9C9E9501345DBC6F7；安装版 132,579,955 字节 SHA256 F1B9334B38777C0C009C8581E81108259097CFCAE9EAAFF505E2A79C4CEC6E63；根目录 AgentCut.exe 已与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.22-交付记录.md`。

## 1.23 遮罩跟踪（2026-10-06）

1.20 让遮罩会动，但每个位置都得人手动打点：一个跟随主体的局部调整要做几十次「移播放头—点◇—改数值」。剪映和 AE 的遮罩之所以有用，是因为能框住目标点一下就走。本轮补上这一步，并且刻意让它**只产生 1.20 已经支持的东西**——一串遮罩中心关键帧。

算法是块匹配：`decode_luma` 用一条 FFmpeg 管道把素材解成不超过 256 宽的灰度小帧（帧数封顶 900），`track_box` 从遮罩中心取一块边长封顶 √MAX_TEMPLATE（96×54）的模板，在上一帧位置周围做 ±search 的整数 SAD 搜索，逐帧取最小者。代价有界且不需要任何新依赖：纯 Python 下 361 个候选 × 1296 像素的一次搜索实测 4.4 ms/帧。置信度用最近 8 帧代价的中位数判断，超过 `median×2.2+12` 就判定跟丢并**停止**——宁可停下来说明，也不沿着噪声编一条轨迹出来。跟踪只估计平移，不估计缩放与旋转，也从不读代理文件（代理只是预览副本，分析必须看原片）。

写入不另开一条路：分析端点算出 `points` 后，把它们作为**一条** `clip.mask_track` 命令交给 `ProjectStore.mutate`，与 `/edits` 同一事务、同一 `request_id` 去重、同一 `expected_revision` 检查、同一 dry-run 语义；reducer 整体替换 `mask_x`/`mask_y` 关键帧并按首点更新静态中心。于是撤销、历史、锁轨、批次预演、MCP schema 全部继承，1.20 的逐帧 alpha 与浏览器单位遮罩原样生效，没有第二套渲染路径。无遮罩/路径/反相/带变速曲线的片段被 `INVALID_MASK` 拒绝，点超出片段时长被 `INVALID_KEYFRAME` 拒绝，整笔回滚。

过程中修掉一个真实回归：1.22 的 `touch_proxy` 用 `os.utime(path, (time.time(), stat.st_mtime))` 回写修改时间，浮点秒在 NTFS 上往返会扰动 `st_mtime_ns`，被 `tests/proxy_check.py` 的「第二次构建必须命中缓存」断言当场抓住（mtime 变了即判定为重新转码）。改为 `ns=(time.time_ns(), stat.st_mtime_ns)` 后两条代理验收都恢复绿色——这条断言存在的意义正在于此。

验收 `tests/tracking_check.py`（合成源：320×180 暗噪声底 + 22 px 亮块走 `x=0.25+0.5t/3, y=0.5+0.18sin(2πt/3)`，解析轨迹已知）：
- 精度：90 帧全部跟住，最大中心误差 2.81 px（分析分辨率 256×144，归一化 0.0088）；静止画面 20 帧漂移 <0.02；目标在第 1.5 秒消失时，引擎报 `lost_at_ticks=1.50s`、只写前 45 帧。
- 导出：跟踪写入后渲 3 秒成片，t=0.4/1.1/1.8 亮像素质心与物体解析位置差 <3% 画面；t=2.6 已超出跟踪范围，遮罩停在最后位置、物体走出遮罩（亮像素从 >200 降到 43），证明「跟丢即停」真的落到画面上而不是只写在返回值里。
- reducer 与 HTTP：一条命令替换两条中心曲线并按首点更新静态中心；无遮罩/反相/路径/带变速曲线 → `INVALID_MASK`；点超出时长 → `INVALID_KEYFRAME`；`dry_run` 不写、revision 不变；一次跟踪恰好一个 revision；同 `request_id` 重放不涨、旧 revision 409、越过素材末尾 `SOURCE_OUT_OF_BOUNDS`；撤销到旧版本后关键帧随之消失。
- 变异验收两处：把逐帧接受的位置改成「永远等于上一帧位置」（跟踪冻结），合成源上第 9 帧就报跟丢、断言立刻变红；关掉跟丢判定，目标消失后仍报 90 帧全跟、断言变红。两道门禁都能失败。
- 界面（vite 渲染层 + 同一引擎 HTTP，工程「遮罩跟踪验收」）：选中片段 → 遮罩区出现「跟踪主体」→ 点一次：`revision 1→2`，库里 `mask_x` 关键帧 90 个、最后一点在 209,328,000 tick（第 89 帧）值 0.75（解析 0.744），提示「已跟踪 90 帧 遮罩会跟着主体走，导出使用同一份关键帧。」与「跟踪遮罩主体 · r2 已原子写入，历史可回滚。」；播放头定位后画面层 `--mask-x` 在 0/1.5/2.9 秒为 0.25 / 0.5 / 0.734375（解析 0.25 / 0.5 / 0.7333）。
- 全量门禁：`ruff check`、`ruff format --check`（48 文件）、28 项 Python 检查、5 项桌面 TS 检查与 `npm run typecheck` 全绿。

仍未完成：遮挡与多目标跟踪（当前只平移单目标、跟丢即停）、跟踪时的缩放/旋转估计、跟踪结果的分段续跟（跟丢后重新框选继续）、路径遮罩动画、色彩节点图、自动语音字幕、代码签名。
1.23.0 发布验收：冻结引擎重编译 `--verify` 通过后重新打包。包内引擎 `/v1/info` 报 `app_version=1.23.0`、`frozen=true`；capabilities 报 `features.mask_tracking=true` 且 `commands` 含 `clip.mask_track`。对合成运动源（320×180、解析轨迹已知）先 `dry_run`：60 帧在 256×144 分析画幅上跟住，最大中心误差 **1.89 px**，`committed=false` 且 revision 不变；正式写入恰好一个 revision，落库 60 个 `mask_x` 关键点（末点在 59×2,352,000 tick）并把静态中心更新为首点，同 `request_id` 重放不涨、旧 revision 409、900 帧越界 `SOURCE_OUT_OF_BOUNDS`。`h264-source-quality` 输出 320×180 **3.000 秒**，t=1.1 成片里被遮罩揭示的亮像素质心 `(0.433, 0.636)` 对比物体解析位置 `(0.433, 0.634)`（484 个亮像素）——包内引擎的跟踪真的驱动了导出 alpha。包内 `agentcut.exe mcp` 通过 `timeline_edit` 提交手算的两点 `clip.mask_track`（r2→r3，读回 `[(0,0.2),(35280000,0.6)]`，且片段里没有残留其它属性的关键帧）。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染；`taskkill` 后无 AgentCut/agentcut 残留进程。便携版 132,429,381 字节 SHA256 DC3E95175FA9449818C54331F695CC75AF463CF4BAF73EA0823A24B666B00C97；安装版 132,590,105 字节 SHA256 29BF5569366CF21106C1F918CB28B0A2A67493B0D2D067D9F0816B2F336449E1；根目录 AgentCut.exe 已与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.23-交付记录.md`。

## 1.24 遮罩跟踪的缩放估计与遮挡续跟

1.23 的跟踪只平移盒子，跟丢即停，这既不像剪映也不像 AE：主体走近时遮罩框不住它，被短暂挡住时轨迹直接断掉。原因是度量选错了——平均绝对差在**面积等于模板**的窗口上必然取最小，所以它把「变大」看成「不像」。换成归一化互相关后形状才是被比较的量，尺寸于是可以被估计；实测还顺带提高了平移精度（同一运动源，最大中心误差从 2.81 px 降到 **2.15 px**）。

实现要点（`src/agentcut/tracking.py`）：
- 尺寸档位相对**当前**尺寸（`0.85/0.92/1.0/1.09/1.18`）而不是相对第 0 帧，所以几倍的生长是逐帧累计出来的，档位本身不必覆盖全程；模板仍是第 0 帧那块（按当前尺寸重采样后才比较），不会把目标一步步改成遮挡物。
- 每帧只做一次全半径平移搜索（coarse step 2 + fine step 1），尺寸档位只在该中心附近 ±4 内试。这一步把 90 帧生长场景从 18.7 秒降到 **6.2 秒**（69 ms/帧），静止或匀速场景 **20–24 ms/帧**，仍然是纯标准库。
- 可信度阈值从拍脑袋的常数改为相对量：最近 8 帧相关度中位数的 0.8 倍，夹在 0.35 与 0.75 之间。低于阈值不再直接停，而是按匀速外推并记进 `gaps`；遮挡持续到素材末尾仍按老规则截断报 `lost_at`，因为猜一条看不见的路径比停下更糟。
- 契约 `MaskTrackPoint` 增加可选 `width`/`height`，`ClipMaskTrack` 校验「要么全带、要么全不带」：混合路径会被 422 拒绝，而不是静默降回只跟中心让人以为缩放也跟上了。reducer 按路径是否带尺寸重写 2 条或 4 条遮罩曲线，其余属性的关键帧一律不动——手工做的尺寸曲线不会因为一次「只跟中心」的跟踪被偷偷删掉。

验收（`tests/tracking_check.py`，合成源解析轨迹与尺寸已知）：
- 精度：90 帧全跟住，最大中心误差 2.15 px；静止 20 帧漂移 <0.02。
- 跟丢：目标第 1.5 秒消失，引擎报 `lost_at_ticks=1.50s`、只写前 45 帧；相关度从 0.95..0.98 掉到 0.07..0.08，阈值判定有十倍余量，不是卡在边界上。
- 遮挡：1.00–1.60 秒被挡住时匀速补 18 帧、`gaps=[{1.00s,1.60s}]`，恢复后在 **1.14 px** 内重新找到同一目标（1.23 是 1.89 px）。
- 缩放：3 秒长大 3 倍的目标，尺寸比 1.53/1.67、2.21/2.33、2.85/2.93（最大相对误差 8.2%，容差 22%）；同一场景关掉尺寸估计后盒子保持 0.16 宽、中心漂到 **21.4 px**，对比开着尺寸时的 2.5 px——这条 `centre_drift(sized) < centre_drift(fixed)` 断言直接把「缩放估计有没有用」变成可失败的判据。
- reducer：带尺寸的路径落库 4 条曲线共 8 个关键帧、静态盒尺寸更新为首点；混合尺寸路径被 `ValidationError` 拒绝。
- HTTP：`estimate_scale` 默认开，回包 `scale_estimated/predicted_frames/gaps`，写入后 `mask_width` 的时间序列与 `mask_x` 完全对齐；`estimate_scale=false` 的 dry-run 回包里没有 `width` 字段、也不涨 revision。
- 导出：把真实跟踪得到的尺寸路径套到一份均匀亮场上（这样亮像素面积就等于遮罩面积，排除了物体本身生长的干扰），成片里 t=0.3→2.6 秒被遮罩揭示的像素从 **2407 涨到 8447**，量出的线性比例 **1.87**，与路径要求的 **1.88** 差 0.5%——跟踪写入的 `mask_width` 真的打开了导出 alpha，而不只是改了预览。
- 变异验收：把尺寸档位临时改成只有 `1.0`（等于关掉缩放），生长场景第 1 秒就报 `width=0.16` 对 `want=1.667`，断言当场变红；而精度/跟丢/遮挡三项仍然绿，说明新门禁专测缩放、没有和旧门禁糊在一起。

界面（vite 渲染层 + 同一引擎 HTTP，工程「遮罩缩放跟踪验收」，1280×800 同源 iframe）：选中片段 → 「跟踪主体」按钮 title 已说明会写中心与大小、被挡住时按匀速补一段 → 点一次：busy「跟踪遮罩主体…」，随后提示「已跟踪 90 帧 遮罩盒随主体远近变大变小，导出使用同一份关键帧。」+「跟踪遮罩主体 · r2 已原子写入，历史可回滚。」，`revision 1→2`。库里 4 条曲线各 90 帧、全部线性、时刻严格为 2,352,000 的整数倍（整数 tick 未被破坏）；`mask_width` 从 0.16 涨到 0.464（解析 2.93×），`mask_x` 末值 0.7421875 对解析 0.744（0.7 px）。

仍未完成：长时遮挡与多目标续跟（遮挡超过 `max_gap_frames` 仍会截断）、旋转与形变估计、跟踪后重新框选续跟、路径遮罩顶点动画、色彩节点图（并联/分层、亮度曲线、LUT、色彩管理）、自动语音字幕、缩略图与波形的磁盘配额。

1.24.0 发布验收：冻结引擎重编译 `--verify` 通过（`app_version=1.24.0`、`frozen=true`、冷启动 670 ms、`mcp` 模式存活）后重新打包。包内引擎对生长目标（320×180、解析轨迹与尺寸已知）`dry_run` 60 帧：最大中心误差 **2.08 px**、第 1.00 秒尺寸 **1.55×**（解析 1.67×），`committed=false` 且 revision 不变；`estimate_scale=false` 的回包没有 `width` 字段。正式写入恰好一个 revision，落库 60 个 `mask_width` 关键点且与 `mask_x` 时刻逐点对齐（0.160→0.356），混合尺寸路径 422 `INVALID_REQUEST` 且 revision 不变，同 `request_id` 重放不涨、旧 revision 409、900 帧越界 `SOURCE_OUT_OF_BOUNDS`。`h264-source-quality` 输出 320×180 **3.000 秒**，t=1.1 揭示质心 `(0.433,0.636)` 对物体解析 `(0.433,0.634)`（1444 亮像素）；把包内引擎跟踪得到的尺寸路径按数据提交给第二个工程（均匀亮场），成片 t=0.3→2.6 亮像素 **2917→10013**，量得线性比例 **1.85** 对路径要求的 **1.85**——包内写下的 `mask_width` 真的打开了导出 alpha。包内 `agentcut.exe mcp` 用 `timeline_edit` 提交两点含尺寸路径（r2→r3，读回 `mask_x=[(0,0.3),(35280000,0.6)]`、`mask_width=[(0,0.2),(35280000,0.5)]`，四条遮罩曲线齐备）。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染；`taskkill` 后 `tasklist` 查不到残留进程。便携版 132,434,333 字节 SHA256 71FA99C19CD07746FF946763692986BDCC1123CCFD7F5EC03B494B8130D51D09；安装版 132,595,049 字节 SHA256 33B18735FD349DE0FA7651C974F6163475EE30CB942D27012D69B6B717ECB86E；根目录 AgentCut.exe 已与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.24-交付记录.md`。

## 1.25 静音检测与一键去空白

口播和短视频的第一件体力活是剪掉停顿，剪映把它做成一键，Agent 也需要「把这段的空白去掉」这种可组合动作；此前只能手动逐刀。这一版补上它，并且刻意**不新增命令**。

实现只有两处职责（`src/agentcut/silence.py`）：把 FFmpeg `silencedetect` 的输出从素材时间映射回片段时间；把区间翻译成既有的 `clip.split` + `clip.ripple_remove`。听这件事完全交给 `silencedetect`，本模块不重实现能量统计；映射按 `speed_percent` 换算，所以 200% 播放的片段报出来的停顿正是编辑看到的位置。切点向内取整帧（起点向上、终点向下），取整后短于 `min_silence_ms` 的区间不切，贴首尾的区间归入 `edges` 且不自动裁——裁首尾是 `clip.trim` 的语义，不该被一条去空白命令顺带做掉。`cut_plan` 从后往前翻译，于是每个较早的区间仍使用扫描时报告的坐标，而每次删除只移动它之后的内容。

验收（`tests/silence_check.py`，合成音源：440 Hz 正弦 + 已知静音门 2.0–2.8 / 4.0–4.5 秒）：
- 检测：报出 2.033–2.8 与 4.033–4.5 秒，全部落在 1/30 秒整帧网格上；起点不早于真实门（不会切进说话），终点不超过真实门 + 2 帧。
- 阈值：`min_silence_ms=600` 只剩 1 段；`=5000` 时 0 段，且 `apply=true` 的空计划被 `INVALID_SILENCE_TARGET` 拒绝、不白涨 revision。
- 变速：200% 片段里区间按时速减半（0.767→0.367 秒），短区间取整后低于 250 ms 因而不切——把「向内取整」的代价变成可观测的断言。
- 计划：6 条命令 = 2×(split+split+ripple_remove)。剪后 3 段为 (位置 0→2.033, 源 0)、(2.033→3.267, 源 2.8)、(3.267→4.767, 源 4.5)，源时钟精确跳过两段静音；关键帧列表逐字保留；`validate_timeline` 通过。
- HTTP：`apply=false` 只读不涨 revision；`apply=true` + `dry_run` 不写；`apply=true` 恰好一个 revision；剪完再扫一次 `gaps` 为空；同 `request_id` 重放不涨、旧 revision 409；无音轨素材拒绝。顺带证明了一条既有约束：客户端在 `verified` 里伪造 `has_audio`/`kind` 不被采信，引擎读的是自己验证过的记录。
- 导出：成片 4.767 秒（期望 4.767），对成片再跑一遍 `silencedetect` 已找不到 ≥0.25 秒的停顿。
- 变异验收：把 `cut_plan` 改成从左往右应用 → 第二批 split 坐标失效，reducer 当场 `INVALID_SPLIT` 整笔回滚。既证明倒序必要，也证明一份错误的计划不会悄悄损坏工程。
- MCP：新增只读工具 `clip_silence`（`apply`/`dry_run` 在工具侧强制 false）与补上 1.23 起缺的 `clip_track`；对源引擎 stdio 实测 `tools/list` 共 31 个工具、两个新工具都在，`clip_silence` 报出的区间与 HTTP 完全一致（143,472,000–197,568,000 与 284,592,000–317,520,000）、`committed=false`、调用后 revision 仍为 3。适配层仍是薄封装，没有第二条规则。
- 界面（1280×800 同源 iframe 真实点击）：选中片段 → 「去空白」→ 提示「去掉 2 处停顿，共 1.23 秒 后面的内容已左移，切点向内取整帧，不会切进说话。」+「去掉静音空白 · r2 已原子写入，历史可回滚。」，时间线变成 3 段（2.03 / 1.23 / 1.50 秒）；点撤销 → revision 3、单段 6.00 秒恢复。多命令一次编辑在撤销里是一步。

仍未完成：片段首尾静音的自动裁切、跨片段整轨批量去空白（当前一条命令只处理一个片段）、对话/呼吸声的语义区分（只按能量判断）、路径遮罩顶点动画、色彩节点图、自动语音字幕、缩略图与波形的磁盘配额。

1.25.0 发布验收：冻结引擎重编译 `--verify` 通过（`app_version=1.25.0`、`frozen=true`、`mcp` 模式存活）后重新打包。包内引擎 `/v1/info` 报 1.25.0/`frozen=true`，capabilities 报 `features.silence_detection=true` 且 `commands` 里没有任何新命令。对合成音源（440 Hz + 静音门 2.0–2.8 / 4.0–4.5 秒）扫描得 **2.033–2.8 / 4.033–4.5 秒**、共 **1.233 秒**、6 条整帧对齐的命令；`apply=false` 与 `apply=true`+`dry_run` 都不涨 revision；`apply=true` 恰好一个 revision，剪后三段 (源起点, 时长) 为 `[(0, 0), (2.8, 1.233), (4.5, 1.5)]` 秒；再扫一次 `gaps` 与 `commands` 均空，空计划 + `apply=true` 被 `INVALID_SILENCE_TARGET` 拒绝且 revision 不变。`h264-source-quality` 成片 **4.767 秒**（期望 4.767），对成片再跑 `silencedetect` **找不到 ≥0.25 秒的停顿**。包内 `agentcut.exe mcp` 的 `tools/list` 含新工具 `clip_silence`（只读，`committed=false`）与补上的 `clip_track`，随后 `timeline_edit` 提交 split+ripple_remove 使 r2→r3。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染；`taskkill` 后 `tasklist` 查不到残留。便携版 132,440,749 字节 SHA256 A57AF73F899449821A089582B14BE49EBB141760C5B79533067CE696814DA8B0；安装版 132,601,473 字节 SHA256 A119F579B1B0D1FA2B83FF82B3E59A845C5A38EDD6FE252826B73182776A80CC；根目录 AgentCut.exe 已与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.25-交付记录.md`。

## 1.26 整轨去空白

1.25 的「去空白」一次只处理一个片段，而口播的实际形态是一条轨上好几段，且停顿常常贴着片段首尾。这一版加整轨入口，仍然不新增命令。

- 跳过而不是失败：一条轨里混着图片、无音轨素材、带变速曲线或已链接的片段是常态，`silence.unsuitable` 给出统一判定（单片段端点用它拒绝，整轨端点用它跳过并说明原因），所以同一条规则不会在两处给出不同答案。
- 首尾一并裁掉：贴起点的区间翻译成「一次分割 + 删掉左块」，等价于带 ripple 的 `clip.trim`，轨道开头的空洞会合上；贴终点的区间是「一次分割 + 删掉右块」。
- 合并顺序：按片段位置从后往前，每个片段内部也从后往前。删除只移动它之后的内容，所以每个片段用的都是扫描时报告的坐标。
- 只有本轨移动：其它轨道片段保持原位，跨轨对齐仍靠组或音画链接；界面提示与帮助条目都这么写。

验收（`tests/silence_check.py` 新增 `track_suite`，第二份合成音源的静音门贴在 0.0–0.6、2.0–2.6、4.5–6.0 秒）：

- 两个片段（c=素材 0–3 秒、b=素材 3–6 秒接在后面）一次合并出 3 次 `ripple_remove`、共剪 **>2 秒**；剪后三段位置首尾相接从 0 开始：`(c-gap2 @0.000, 源 0.6)`、`(c-gap0 @1.433, 源 2.6)`、`(b @1.833, 源 3.0)`——首片段的前导静音被裁掉并左移、中间停顿被剪掉、尾片段的结尾静音被削掉。
- 导出成片 **3.367 秒**，对成片跑 `silencedetect`（0.25 秒下限）**找不到任何停顿**。
- HTTP：整轨端点默认只读不涨 revision；对已剪过的轨返回 `commands == []` 且逐片段列出 `gaps == []`；无音轨片段以 `skipped` 说明原因；`apply=true` 的空计划被 `INVALID_SILENCE_TARGET` 拒绝；轨道不存在 404。
- 计划翻译单测：贴起点的区间产出「split + ripple_remove(原片段)」两条命令，顺序与 id 都被断言写死。

仍未完成：跨轨同步去空白（要靠组/链接手工对齐）、按语义区分呼吸声与句间停顿、带变速曲线片段的首尾裁切、路径遮罩顶点动画、色彩节点图、自动语音字幕、缩略图与波形的磁盘配额。

1.26.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.26.0`、`frozen=true`、`mcp` 存活）后重新打包。包内引擎整轨扫描两个片段（静音门 0.0–0.6 / 2.0–2.6 / 4.5–6.0 秒）得 `c2` 边区间 `(1.533, 3.0)`、`c1` 内部 `(2.033, 2.6)` 与边区间 `(0.0, 0.6)`，合并 **7 条命令、2.633 秒**；`apply=false` 与 `apply=true`+`dry_run` 不涨 revision；`apply=true` 恰好一个 revision，三段 (位置, 源起点) 精确为 `[(0, 18 帧), (43 帧, 78 帧), (55 帧, 90 帧)]` 且首尾相接；再扫一次 `commands == []`，空计划 `apply=true` 被 `INVALID_SILENCE_TARGET` 拒绝，轨道不存在 404。导出成片 **3.367 秒**（期望 3.367），对成片跑 `silencedetect` **无任何 ≥0.25 秒停顿**。包内 `agentcut.exe mcp` 的 `tools/list` 含 `clip_silence`/`clip_track`，只读工具调用后 revision 不变。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染且轨道标题行出现剪刀按钮；`taskkill` 后 `tasklist` 查不到残留。便携版 132,444,213 字节 SHA256 029774AFA47DEDF262064052DD38E0BD9A727256627991A54717ED5910F539AC；安装版 132,604,923 字节 SHA256 DEB0D5A1C908CEE5B0C0F9A5B8B5E69C7B49D62562ED449806FF5FA17BD84524；根目录 AgentCut.exe 与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.26-交付记录.md`。

## 1.27 响度表与一键统一响度

达芬奇和剪映都有响度目标（-16 / -14 / -23 LUFS），Agent 也需要「把这段的响度统一到 X」这种能量化的动作。这一版加表加一键，写入仍然只有一个数。

- 测量交给 FFmpeg 自带的 `ebur128=peak=true`，本模块只解析 Summary 段。第一版实现解析了整段 stderr，结果读到逐帧运行行里的 `I:`——文件开头还在绝对门以下，量出来是 -70 LUFS 这种**看起来合理的假读数**；改成只读 Summary 后，相差 12.04 dB 的两条合成音被量成 12.00 dB。这条教训写进 `docs/architecture.md`，因为它正是「门禁必须断言产物而不是意图」的又一例。
- 建议增益 `gain = min(10^((target-I)/20), 10^((ceiling-peak)/20), 4)`，并用 `limited_by` 说明到不了目标是因为 `ceiling`（再抬就越过真峰值上限）还是 `gain_range`（4 倍到顶），`reaches_target` 只在 `|predicted - target| ≤ 0.2 LU` 时为真。静音（`I = -inf`）被 `LOUDNESS_FAILED` 拒绝，而不是得到无穷大增益。
- 写入只有 `clip.effects.gain`：线性倍数、不是压缩器，预览与导出乘同一个数，动态保持录下来的样子，剪辑师仍可用关键帧自己画包络。可分析判定沿用 `contracts.audio_scan_problem`（与去空白同一处），`apply=true` 走 `ProjectStore.mutate`。

验收（`tests/loudness_check.py`）：

- 表：loud/quiet 两条合成音量得 -27.1 / -39.1 LUFS、真峰值 -27.1 / -39.1 dBTP，差 **12.00 dB** 对理论 12.04 dB；静音文件被拒绝。
- 增益：loud 段建议 **3.5892** 倍、预测 -16.0 LUFS 且 `limited_by=""`；一个「已经顶着峰值」的段被上限压到 0.9441 倍、只能到 -20.5 LUFS 并如实标 `ceiling`；-60 LUFS 的段被 4 倍上限限制并标 `gain_range`。
- HTTP：`apply=false` 不涨 revision；`apply=true`+`dry_run` 不写；`apply=true` 恰好一个 revision，落库 `effects` 只有 `gain` 变了（`scale/opacity/...` 原样）；同 `request_id` 重放不涨、旧 revision 409、片段不存在 404、目标越界（-31）422；换 -30 目标得到更小增益。
- 导出闭环：把建议增益写进工程后渲染，再量成片得 **-16.0 LUFS**（目标 -16.0，真峰值 -15.6 dBTP）——表读数、增益与渲染三者说的是同一件事。
- 界面（1280×800 同源 iframe 真实点击，工程「统一响度验收」）：点「统一响度」→ 提示「响度 -35.0 → -23.0 LUFS 目标 -16 LUFS，线性增益 4 倍，已到增益上限（4 倍）；预期峰值 -23.06 dBTP。只改音量倍数，不插入压缩器。」+「统一响度 · r2 已原子写入，历史可回滚。」；库里 revision 2、`effects.gain = 4.0`、其余字段未动。这一例恰好演示了限制被如实报告而不是假装达标。
- 门禁同步：`tests/self_check.py` 对 MCP 工具集合是精确相等断言，新增端点/工具时它会当场变红——1.26 加两个工具时就是这样被抓到的；本版不新增工具，断言保持绿色。

仍未完成：整片（多片段混合后）响度测量与自动限幅、响度关键帧自动化、按轨/按工程的响度报告、路径遮罩顶点动画、色彩节点图、自动语音字幕、缩略图与波形的磁盘配额。

1.27.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.27.0`、`frozen=true`、`mcp` 存活）后重新打包。源文件本地量得 **-35.0 LUFS / -35.1 dBTP**，包内引擎的表给出同样读数；目标 -25.0（源 +10 dB）建议增益 **3.1623** 倍、预测 -25.0 LUFS、`limited_by=""`。`apply=false` 与 `apply=true`+`dry_run` 不涨 revision；`apply=true` 恰好一个 revision，落库 `effects` 与「默认值 + 这一个增益」逐字段相等；重放不涨、旧 revision 409、片段 404。渲染成片再量得 **-25.1 LUFS / 真峰值 -24.9 dBTP**（目标 -25.0）——表、增益与导出闭环成立。包内 `agentcut.exe mcp` 的 `tools/list` 含 `clip_silence`/`clip_track`，`timeline_edit` 提交 `clip.effects` 使 r2→r3、`gain=0.5`。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染；`taskkill` 后 `tasklist` 查不到残留。便携版 132,449,045 字节 SHA256 4ED8A4CCAAB336943FD6D325F467C3C40EE71EB97CA6293131A653CA07B2976C；安装版 132,609,759 字节 SHA256 6896CE87578CC07637D7300450FE623704DF89AFC4915E42248ADA1C4F20825B；根目录 AgentCut.exe 与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.27-交付记录.md`。

## 1.28 整轨响度对齐

1.27 的一次一段在真实口播上太慢：一条轨十几个片段就要点十几次。这一版把同一套测量摊到整条轨，一次写入、一次撤销，并且顺手补上一条绝对刻度门禁。

- 端点 `POST /v1/projects/{p}/tracks/{t}/loudness` 沿用 `LoudnessRequest` 载荷与 1.27 的判定（`contracts.audio_scan_problem`），按位置顺序逐片段测量源上的窗口，把建议增益合并成若干条既有 `clip.effects` 命令：不加新命令、不加新 schema、capabilities 也不新增字段（`loudness_metering` 已覆盖）。MCP 侧 `timeline_edit` 早已能提交 `clip.effects`，因此无需新工具。
- **两条自我约束**：建议增益与片段现值相差 ≤0.01 就不产生命令（重复点击得到「已经对齐」而不是又写一版；`apply=true` 而计划为空时返回 `INVALID_LOUDNESS_TARGET`，不产生空 revision）；音量已被关键帧动画的片段被跳过（`loudness.volume_problem`），因为它实际响的是曲线，改静态增益等于没改——单片段端点直接拒绝，整轨端点列入 `skipped` 并带原因。
- **绝对刻度门禁**：`tests/loudness_check.py` 里用 stdlib 直接解码 PCM 并按 ITU-R BS.1770-4 的两级 biquad 手算积分响度，与 FFmpeg 表读数对比。这条与被测实现共享的只有规范文本，所以表里任何常量偏移都会在这里变红，而原有的「相差 12.04 dB 量成 12.00 dB」相对门禁对此完全无感。规范印刷的第二级系数直接代入会把极点放到 1.0008、朴素递推两秒发散，参考实现按临界阻尼取 `r=sqrt(a2)`。

验收（`tests/loudness_check.py`）：

- 表：-27.1 / -39.1 LUFS 相差 12.00 dB（理论 12.04）；**校准**：loud.wav 手算 -27.10、quiet.wav 手算 -39.14，与表读数差 **+0.00 / +0.04 LU**。
- 整轨：三段 -27.1 / -33.1 / -39.1 LUFS 在 -28.0 目标下得增益 **0.9016 / 1.7989 / 3.5892**（最响那段被调低），`apply=false` 不涨 revision，`apply=true` 恰好一个 revision，再扫一次 `commands == []`，空计划 `apply=true` 被 `INVALID_LOUDNESS_TARGET` 拒绝；导出整片实测 **-28.0 LUFS / -27.5 dBTP**。打了音量关键帧的那段被两个端点都跳过并给出同一句原因。
- 界面（1280×800 同源 iframe 真实点击，工程「整轨响度验收」，三段电平 1.0 / 0.5 / 0.125）：表读数 -21.1 / -27.1 / -39.1 LUFS，-16 LUFS 目标下建议 1.7989 / 3.5892 / 4.0（第三段被 4 倍上限挡住）→ 提示「对齐 3 段响度到 -16 LUFS · 1 段受 4 倍增益或真峰值上限限制到不了目标。每段只改音量倍数，不加压缩器；撤销一次全部还原。」+「整轨统一响度 · r2 已原子写入」；库里 `gain` 精确为 1.7989 / 3.5892 / 4.0 且 `opacity/scale/keyframes/position` 一字未动；撤销回 r3 三段全部回到 1.0；再点一次 r4；已对齐状态下再点得到「这条轨已经对齐 3 段已经在 -16 LUFS 附近，无需改动。」且 revision 不动。
- 门禁同步：`npm run typecheck`、`uv run ruff check`、`ruff format --check`（52 文件）与 30 项 Python 检查全绿。

仍未完成：整片混合后的响度目标（母带级限幅与真峰值再分配）、响度关键帧自动化、按工程的响度报告、路径遮罩顶点动画、色彩节点图、自动语音字幕、缩略图与波形的磁盘配额。
1.28.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.28.0`、`frozen=true`、`mcp` 存活、裸启动 621 ms）后重新打包。包内引擎对三段相差 6 dB 的素材在 -28.0 目标下量得 -27.1 / -33.1 / -39.1 LUFS，建议增益 **0.9016 / 1.7989 / 3.5892**（最响那段被调低）；`apply=false` 与 `apply=true`+`dry_run` 不涨 revision，`apply=true` 恰好到 r2 且三段 `effects` 与「默认值 + 这一个增益」逐字段相等；再扫一次 `commands == []`、`changed == 0`，空计划 `apply=true` 被 `INVALID_LOUDNESS_TARGET` 拒绝且 revision 仍为 2，轨道不存在 404。导出整片实测 **-28.0 LUFS / -27.5 dBTP**。给 c1 打音量关键帧后，整轨端点把它列入 `skipped`（原因：`this clip's volume is animated by keyframes…`）、单片段端点同一句拒绝。包内表读数 -27.1 LUFS 对测试内独立解码 PCM 算出的 BS.1770 -27.10 LUFS，差 **+0.00 LU**。包内 `agentcut.exe mcp` 的 `tools/list` 未新增工具（本版无新工具，包内可见 `clip_silence`；完整工具集合的精确相等断言由 `tests/self_check.py` 把关），`timeline_edit` 提交 `clip.effects` 使 r3→r4、`gain=0.5`。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染、轨道标题行含响度按钮；`taskkill /T` 后 `tasklist` 查不到残留。便携版 132,449,645 字节 SHA256 494C55B689A9C4D9533A3BBB9F41B36AA0EE3403EE10BD694459B9C729781256；安装版 132,610,362 字节 SHA256 986904642F7BE766B90B3562D95E09FA9CEEE1A091B92CBFC0C149B8EBAD075D；根目录 AgentCut.exe 与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.28-交付记录.md`。

## 1.29 时间线标记与按标记分割

剪映的「打点」、达芬奇的 marker、AE 的 marker 是同一个东西：在时间轴上留一个「这里」，之后可以吸附、可以切、可以让别人找到。这也是 Agent 最需要的锚点——它没有眼睛，但有整数刻度。这一版把标记做成工程状态、做成两条普通命令、并让标记处能一刀切开。

- `Project.markers`（schema v11）是排好序的 `{id, at_ticks, name, color}` 列表；`marker.set` 按 id 新建或移动改名，`marker.remove` 删除。标记只能落在**当前内容之内**，上界由 `contracts.project_content_ticks` 一处给出——能打在哪、和哪些标记没切到东西，读同一个函数，不会各说各话。顺手把散在四处（`contracts`、`projects`、`timeline`、capabilities）的版本号收成 `contracts.SCHEMA_VERSION` 一个来源，之前每次升 schema 都要手写四处、漏一处就自相矛盾。
- 按标记分割（`markers.split_plan`）只产普通 `clip.split`：源时钟、关键帧、转场、链接全部仍由 reducer 决定。落在片段边缘或空隙里的标记进 `unused`，绝不切出零长片段；同一个片段内的多个切点从右往左发射，前面的坐标才不会被前面那刀挪走。
- 界面：标尺上每个标记是一条竖线加名字（5 种颜色分组），单击跳过去、点 × 删除；工具栏小旗（M）在指针处打点；剪刀按钮在没有标记时是禁用的（点了也不会发生什么，就不给可点）；标记同时是磁吸边缘。
- 兼容读取：v10 快照没有 `markers` 键，读出来就是空列表，不需要迁移脚本；`tests/marker_check.py` 直接断言这一点。

验收（`tests/marker_check.py`，31 项 Python 检查之一）：

- reducer：同 id 是移动不是堆第二个；颜色改得动；越界 `INVALID_MARKER`、删不存在的 id `NOT_FOUND`；一个批次里先加长内容再在新内容里打点可以通过（上界随命令推进）；手写两份同 id 的标记被 `validate_timeline` 拒绝；v10 快照读出空列表。
- 计划：三条片段（v 轨 0-40 帧与 50-80 帧、w 轨 0-100 帧）加三个标记（20 / 40 / 60 帧）得 **5 刀**、`unused` 为空；命令序列逐条断言到帧刻度与生成的右片段 id；切完的碎片首尾相接铺满原片段且没有零长段；轨道过滤后边缘标记落入 `unused`；相差一帧的两个标记仍各自切一刀。
- HTTP：`apply=false` 与 `apply=true`+`dry_run` 都不涨 revision（dry_run 回的是**前瞻**快照，库里仍是原样）；`apply=true` 恰好一个 revision、片段 1→3、标记原地不动；拿旧 revision 再提交被 409 挡住；全部标记都变成边缘后再 `apply=true` 得到 `INVALID_MARKER_SPLIT` 且不烧版本；工程不存在 404；`track_ids` 过滤后计划为空。
- 持久化：重开 SQLite 读到同样的标记；`restore` 回到切之前那一版时标记还在，且恢复本身是新 revision。
- 界面（1280×800 同源 iframe 真实点击，工程「标记验收」，三段 2 秒图片）：指针处点小旗 → `标记 1` 落在 3.533333 秒、提示「打点 · r2 已原子写入」；Agent 用 `marker.set` 写的两个标记在标尺上渲染出名字与 cyan/amber 配色（left 92 / 216 px）；点剪刀 → 3 段变 6 段、r3→r4、提示「在 3 个标记处分割 切点就是标记本身的那一帧」，库里边界精确为 0 / 1.5 / 2 / 3.5 / 3.5333 / 4 / 5 秒且碎片首尾相接；把最后一段左边缘拖到 4.4857 秒处，实际提交 **4.5 秒**——与标记的 `at_ticks` 逐 tick 相等（317520000），证明标记真的是磁吸边缘而不是装饰；点 × 删掉一个标记 → 4 个变 3 个、r7。两个额外的诚实证据：指针跑到内容之外时打点，界面把引擎原文 `INVALID_MARKER · a marker has to sit inside the current content (0..423360000 ticks)` 照实播报；期间另有一路 HTTP 改过工程，界面用旧 revision 拖动被拒并提示「时间线刚被 Agent 或另一次操作改过。界面已自动读取最新版本，请重做这一步。」，没有偷偷写坏数据。
- 门禁同步：`tests/self_check.py` 对 MCP 工具集合是精确相等断言，新增 `marker_split`（只读）时它当场变红后才知道要一起改；四处 `schema_version == 10` 的断言同样被升 v11 抓到并改成 11。

仍未完成：标记的拖拽改位与跨序列归属（目前标记属于工程主时间线）、标记分组/颜色编辑器、路径遮罩顶点动画、色彩节点图、自动语音字幕、整片母带响度目标、缩略图与波形磁盘配额。
1.29.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.29.0`、`frozen=true`、`mcp` 存活）后重新打包。包内引擎 capabilities 报 `project_schema_version=11`、`features.timeline_markers=true`、`commands` 含 `marker.set`/`marker.remove`。三段 2 秒素材 + 三个标记（1 / 2 / 3 秒，其中 2 秒正落在 k0 与 k1 的边缘）：标记按刻度排序存下 `(b1 1.0, b3 2.0, b2 3.0)`；计划给出 **2 刀**、`unused == [2 秒]`、`clips == 2`；`apply=false` 与 `apply=true`+`dry_run` 都不涨 revision（dry_run 回的是前瞻快照，库里仍 3 段）；`apply=true` 恰好 r2，五段边界精确为 (0,1)(1,2)(2,3)(3,4)(4,6) 秒且首尾相接、标记原地不动；再加一个 5 秒标记后拿旧 revision 提交得 409、库里仍是 r3，正确 revision 提交得 r4（6 段）；全部标记都变成边缘后 `apply=true` 得 `INVALID_MARKER_SPLIT` 且不烧版本；越界打点得 `INVALID_MARKER` 且 revision 不动；工程不存在 404。schema v11 工程渲染成片 **6.000 秒**。包内 `agentcut.exe mcp`：`tools/list` 有 `marker_split` 且 `readOnlyHint=true`，调用它回 4 个标记、**零条命令**（都成边缘了），`timeline_edit` 发 `marker.set` 使 r4→r5 并出现在 `project_get` 的标记列表里。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。`release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，Windows Graphics Capture 截图确认工作台完整渲染、工具栏出现小旗与剪刀按钮；`taskkill /T` 后 `tasklist` 查不到残留。便携版 132,456,998 字节 SHA256 5086F73A247A4D5A7BD433DC4A2BD62DE655716A1051D477249036F02353193A；安装版 132,617,725 字节 SHA256 EBEAE9DA4AA4C2AAB897F0DD4696C8E9B0040AC977F109F942F047122DB43633；根目录 AgentCut.exe 与便携版逐字节一致。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.29-交付记录.md`。

## 1.30 源画面划动与左右滑移

修剪只能改片段的头尾，但真实剪辑里更多的问题是「这段素材我想从另一格开始播」和「这一刀的位置要挪，但两边都不能露馅」。达芬奇和 AE 把这两件事做成三个划动工具（slip / slide），剪映用「替换素材」和「拖动让位」表达同一意图。这一版把它们变成两条命令，人和 Agent 用同一套整数刻度。

- `clip.slip`：位置与时长一帧不动，只把素材窗口滑走 N 帧；动画时钟保持原样（关键帧仍贴着时间线上的那一格，这是划动的定义）。
- `clip.slide`：片段沿本轨移动 N 帧，一侧相邻段让出 N 帧、另一侧收回 N 帧，**整条轨总长一帧不变**；被吃进去的那段自己的素材窗口跟着挪，长大的那段素材头尾不够时由 `validate_timeline` 的 `SOURCE_OUT_OF_BOUNDS` 拒绝。
- 两条都复用修剪的唯一入口 `_trim_clip`，所以源时钟、动画偏移、变速曲线切片这些规则不在第二处重新实现一遍；拒绝面（变速曲线、音频链接、缺任一侧相邻段、相邻段太短、`delta == 0`）在 reducer 里明说原因。
- 检查器新增「源画面划动与滑移」面板：步长按帧、四个方向按钮，被禁用的情况直接把原因写在提示里。

验收（`tests/slip_check.py`，33 项 Python 检查之一）：

- reducer：`l(0,0,40) m(40,60,40) r(80,120,40)` 划动 +10 帧 → m 变 `(40,70,40)` 且两侧一字未动；划动 −50 帧 → `(40,10,40)`；滑移 +10 帧 → `l(0,0,50) m(50,60,40) r(90,130,30)`、滑移 −10 帧 → `l(0,0,30) m(30,60,40) r(70,110,50)`，三种状态轨尾都在第 120 帧；带关键帧的片段滑移后 `animation_offset` 跟着走 6 帧、关键帧仍贴片段本地第 10 帧，划动则时钟一字不动。
- 拒绝：`delta == 0`、缺左邻、相邻段短于步长 → `INVALID_SLIDE`；带变速曲线的片段划动/滑移 → `INVALID_SLIP` / `INVALID_SLIDE`；已链接内嵌声音 → `INVALID_SLIP`；越过素材头/尾 → `SOURCE_OUT_OF_BOUNDS`。
- HTTP：一次批次一个 revision（划动 +8 帧与滑移 +5 帧合起来只到 r2，三段边界一次到位）；含非法滑移的批次整批回滚（`revision` 不动、`l.source_in_ticks` 仍是 0）；片段不存在 404、旧 revision 409；重开 SQLite 素材窗口仍在。
- 导出像素（这条才是「真的换了画面」的证据）：红/蓝两色各两秒的素材，同一个时间线第 0.5 秒在划动前是 **(255,0,1)**、划动 2 秒后是 **(0,1,255)**；红/绿/蓝三段各两秒，把中间段滑移 +1 秒后，红/绿接缝从屏幕上的 2.0 秒精确挪到 3.0 秒（2.5 秒处由绿变红、4.5 秒处由蓝变绿、5.5 秒处仍是蓝），成片长度仍是 **5.990 秒**一帧未变。
- 变异测试（证明这些门禁真能失败）：① 让滑移只动相邻段、忘了动本段 → 同轨重叠被 reducer 拒绝；② 让被吃进去的相邻段保留原素材起点（几何完全合法）→ 帧刻度表断言当场报 `[(0,0,141120000), (141120000,169344000,112896000), (254016000,338688000,84672000)]`；③ 让划动忽略偏移量（几何也合法）→ 同一处断言立刻变红。
- 界面（1280×800 同源 iframe 真实点击，工程「划动滑移验收」，三段 40 帧）：选中中间段 → 面板「源画面划动与滑移」出现、四个按钮可用；步长填 10 点「划动 →」→ 提示「划动源画面 后 10 帧 · r2 已原子写入」；步长填 5 点「滑移 →」→ 提示「滑移片段 右 5 帧 · r3 已原子写入」；库里 `l(0,0,45) m(45,70,40) r(85,125,35)`、轨尾仍是第 120 帧。改选最左边那段再点「滑移 →」→ 提示照实给出引擎原因「a slide needs clips touching both ends of this one on the same track」且 revision 仍是 3。

仍未完成：滑移/划动的鼠标手势（目前是指令式按钮 + 命令）、标记拖拽改位、路径遮罩顶点动画、色彩节点图、自动语音字幕、整片母带响度目标、缩略图与波形磁盘配额。
1.30.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.30.0`、`frozen=true`、`mcp` 存活）后重新打包。包内引擎 capabilities 报 `features.slip_slide_editing=true` 且 `commands` 含 `clip.slip`/`clip.slide`。用真实 4 秒素材（前两秒红、之后蓝）建三段：划动 +10 帧得 `[(0,0,40),(40,50,20),(60,60,40)]`（只有中段素材起点变了），再滑移 +5 帧得 `[(0,0,45),(45,50,20),(65,65,35)]`，轨尾仍是第 100 帧一帧不差；把最左段滑移被 `INVALID_SLIDE` 拒绝、把末段划动越过素材尾被 `SOURCE_OUT_OF_BOUNDS` 拒绝，两种拒绝之后 revision 都仍是 3。渲染成片回看像素：第 1.00 秒 (255,0,0)（未动的片段仍是素材开头的红），第 1.90 秒 (0,0,255)（被划动过的中段已播到素材 2 秒之后的蓝）。包内 `agentcut.exe mcp`：`tools/list` 未新增工具（本版无新工具，`marker_split` 仍在），`timeline_edit` 提交 `clip.slip` 使 r3→r4、素材起点回到第 45 帧。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。便携版 132,460,658 字节 SHA256 DC66DDAC66BFA16EC33BDBCC191916F575EB562DEC2E196703B0CB3AB874FBDA；安装版 132,621,377 字节 SHA256 BC3732E1C3E3EDE85EBAA195E646529AE650EB4184556BA04DB2BD3FF5E01C9E；根目录 AgentCut.exe 与便携版逐字节一致。**本轮没有拿到原生截图**：`release/win-unpacked/AgentCut.exe` 确实启动并建出标题为「AgentCut 剪辑台」的窗口（1936×1048，进程树 `taskkill /T` 后 `tasklist` 查不到残留），但桌面此刻没有前台窗口（激活返回 `foregroundHwnd=0`），WebView2 在被遮挡时不出帧，Windows Graphics Capture 与 PrintWindow(`PW_RENDERFULLCONTENT`) 两次都只拿到未着色的白页；同一套外壳与工具栏的原生截图见 1.29 交付记录。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.30-交付记录.md`。


## 1.31 色彩空间转换节点，以及每通道表的打点策略

手机素材、屏幕录制和网页素材是 sRGB，广播时间线是 BT.1886，达芬奇默认工程又是另一种 gamma——同一轨上混着两三种传递函数，暗部就同时对不上。剪映没有这一层，AE 靠解释素材，达芬奇有完整的 CST。这一版给调色节点加一种 `transfer`，只换算传递函数，并且顺手修掉一个更普遍的错误。

- `GradeTransfer{input_space, output_space}`：两侧都是必填的 `"linear" | "srgb" | "gamma18" | "gamma20" | "gamma22" | "gamma24" | "rec709"`；`rec709` 就是黑位不抬升的 BT.1886，数值上等于 gamma 2.4，两个名字都留着因为剪辑者两种说法都用。色域基色、矩阵、文件里的色彩空间标签都不做，capabilities 也只声明 `color_space_transform`，不假装是完整 ICC/ACES 管理。
- **修掉的问题**：每通道表原来固定取 64 个等距打点。sRGB→gamma2.4 在黑位处斜率趋于无穷，等距网格让**浏览器表和 FFmpeg 表达式一起**偏离目标曲线最多 4.83 个色阶——两者互相一致，所以原来那条"预览与导出共用同一张表"的门禁完全看不见这种错。现在打点按中点漂移自适应加密（上限 256 点），验收改成与测试里**独立写出的发布函数**逐格比较。
- 界面：调色节点多一个「+色彩空间」，两个下拉选输入/输出空间，强度滑杆与启用开关沿用其它节点的语义。

验收（`tests/grade_check.py` 的 transfer 套）：

- 数学：七种空间 `encode(decode(v))` 在 0..255 全量程往返最大误差 0.000000 阶；sRGB 0.5 解到线性 0.214041；18% 灰编码成 sRGB 字节 117.65；`rec709` 与 `gamma24` 逐点相等。
- 表：六对空间（srgb↔rec709、linear→srgb、srgb→linear、gamma22→srgb、srgb→gamma18）逐格与独立实现的发布函数比较，最差 **0.343 阶**（修复前 4.83 阶）；编译这六条链共 17 ms。
- 像素：六档暗带源 [0, 2, 10, 30, 94, 253]（源编码本身就把近黑拉低 1–2 阶，所以比较以"真的到达磁盘的数值"为基准）经 srgb→rec709 导出后为 [0, 11, 22, 40, 101, 252]，发布曲线给出 [0, 12, 23, 42, 102, 253]，每档差 ≤4 阶；`mix=0` 与 `enabled=false` 时整条链退化为空滤镜。
- 契约：未知空间名、缺少一侧空间的节点被 `ValidationError` 拒绝。
- 变异测试：① 把自适应打点的容差放宽到不再生效 → 表门禁当场报 `('srgb','rec709', 4.829833465487836)`；② 把发布模块里的 sRGB 解码指数从 2.4 改成 2.2（几何与结构全都合法）→ 同一门禁报 8.13 阶。两条都证明门禁看的是产物而不是意图。
- 界面（1280×800 同源 iframe 真实点击，工程「色彩空间验收」）：选中片段 → 点「+色彩空间」→ 节点行「1. 色彩空间」出现、r1→r2，两个下拉显示 srgb / rec709；预览层样式变为 `filter: brightness(1) contrast(1) saturate(1) url("#g28dc4064c13094ee")`，DOM 里的 `feComponentTransfer` 三条 256 值表与引擎回包逐值相同（第 4 格 0.060949319、第 128 格 0.527924914）；把输出空间改成 gamma22 → r3、滤镜 id 变成 `g9d6c872bc790f0f4`、第 4 格变成 0.047262868，与手算 `encode(gamma22, decode(srgb, 4/255)) = 0.047263` 一致。
- 门禁同步：`npm run typecheck`、`ruff check`、`ruff format --check`（55 文件）与 33 项 Python 检查（含 5 项 esbuild 桌面检查之外的全部）串行全绿。

仍未完成：色域矩阵与 primaries 转换（只换传递函数）、读取素材自带的色彩空间标签、log 曲线（S-Log3/C-Log 等）、路径遮罩顶点动画、色彩节点图（并联/分层）、自动语音字幕、整片母带响度目标、缩略图与波形磁盘配额。

1.31.0 发布验收：冻结引擎 `--verify` 通过后重新打包。包内引擎 capabilities 报 `features.color_space_transform=true`；`clip.grade` 写入 `{kind: transfer, input_space: srgb, output_space: rec709}` 后原样读回。`GET /preview-manifest` 回包给出色阶中性的 256 项表（`r == g == b`），逐格与验收脚本里独立实现的发布函数比较最差 **0.258 阶**，`color_filter` 正是 `brightness(1.0) contrast(1.0) saturate(1.0) url(#g28dc4064c13094ee)`。渲染六档暗带成片：源到盘 [0, 2, 10, 30, 94, 253] → 导出 [0, 11, 22, 40, 101, 252]，发布曲线 [0, 12, 23, 42, 102, 253]，每档差 ≤2；把节点 `enabled=false` 后清单里 `grade` 为空且滤镜不再引用任何表；写入未知空间名 `acescg` 得 422 且不产生 revision。包内 `agentcut.exe mcp`：`tools/list` 未新增工具（`marker_split` 仍在），`timeline_edit` 提交 `clip.grade` 使 r2→r3、输出空间读回 `gamma22`。ASAR 100 条目、renderer 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。便携版 132,463,348 字节 SHA256 69C1B62F2920ACF29DFEE5AA3258A869CA3008DFD3D02CAB7C173C994E650B42；安装版 132,624,053 字节 SHA256 D7A7C48927209BC40C23CC0DB1CB62F947D605FEE772F5C5AE455AC9BC77DCC4；根目录 AgentCut.exe 与便携版逐字节一致。**本轮同样没有原生截图**：打包应用启动并建出「AgentCut 剪辑台」窗口（1936×1048），但前台此刻被另一个桌面应用持有，WebView2 在被遮挡时不出帧（1.30 已确认 WGC 与 PrintWindow 都只能拿到白页），因此沿用 1.29 的外壳截图证据；`taskkill /T` 后 `tasklist` 查不到残留。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.31-交付记录.md`。

## 1.32 调色节点的混合方式，以及恒等滤镜的清理

达芬奇每个节点都有 Composite Mode，AE 的曲线层、调整层也靠混合方式和下层打交道；剪映只有整层不透明度。1.31 之前我们的调色节点只有「正常」一种语义——节点输出总是整体替换当前画面，`mix` 只能按比例往回退。这一版把画面轨早就有的那套混合词汇（`tests/blend_check.py` 验收过的正常/正片叠底/滤色/叠加/变暗/变亮/差值/排除）搬到调色节点上，让「只提亮暗部但不动亮部」这种意图能在节点内部表达，而不是再叠一层轨道。

- 契约：`GradeCurve`/`GradeWhiteBalance`/`GradeWheels`/`GradeTransfer` 四种节点都多一个 `blend: BlendMode`，默认 `"normal"`；`BlendMode` 直接复用轨道合成已有的字面量联合，不新建第二套名字。capabilities 增 `grade_node_blend_modes`。
- **一处权威**：混合公式只在 `grade.py` 实现一次（`blend_values(mode, backdrop, picture)`，逐通道标量、输入输出都在 0..1），浏览器表和 FFmpeg 表达式都由它编译出来。公式取 W3C Compositing 1 的可分形式（`multiply=b*p`、`screen=b+p-b*p`、`overlay` 按 backdrop 是否过半切换、`darken=min`/`lighten=max`、`difference=|b-p|`、`exclusion=b+p-2bp`），因此对每一通道都是**纯标量函数**，天然可塞进每通道表，不需要真正的节点图。
- 语义：混合的 backdrop 是**进入本节点时已经累积的通道值**，picture 是本节点自己的曲线/白平衡/增益/传递函数输出，`mix` 再把混合结果按强度往 backdrop 回退——`value + strength * (blend(value, inner(value)) - value)`。所以「normal + mix=0.5」和「multiply + mix=0.5」是两个不同的东西，前者回退到输入，后者是半强度压暗。
- **顺带修掉的滤镜污染**：自适应打点会留下共线打点，恒等映射（例如用一条只抬阴影的曲线去做 `darken`，或 `mix=0`）过去仍会编译出约 750 字符的 `lutrgb=…val…` 空滤镜；现在 `_expression` 发现整条折线恒等就返回 `val`，链里彻底不出现该阶段。这也让 1.31 那条「空链不添滤镜」的门禁第一次真正能失败。
- 界面：每个节点下方多一个「节点混合方式」下拉（选项文字与轨道合成一致：滤色、正片叠底……），节点行的标题从「1. 色彩空间」变成「1. 色彩空间 · 滤色」，不额外占一层折叠；`BLEND_MODES` 从 `desktop/src/engine.ts` 单点导出，Inspector 的轨道合成与 GradeFields 的节点共用同一份表，删掉了 Inspector 里那份重复的本地副本。

验收（`tests/grade_check.py` 的 blend 套）：

- 数学：八种方式 × 三通道 × 全量程逐格比较，参考实现是测试里**独立写出的 W3C 公式**（不复用被测模块的函数），最大偏差 **≤0.5 个色阶**；`normal` 与 1.31 行为完全一致（回归门）。
- 滤镜：`darken` 配一条只抬升的曲线（结果恒等）与任意节点 `mix=0` 都**不产生任何 lutrgb 阶段**，编译出的滤镜串里不含 `if(lt(val,`。
- 像素：六档灰阶源 [0, 2, 10, 30, 94, 253] 经 `screen` 节点导出为 [61, 66, 77, 105, 178, 252]，经 `difference` 导出为 [61, 61, 59, 54, 38, 0]——两条必须不同（差值在暗部抬起来、亮部归零，滤色相反），实测确实不同；同时 `grade_tables` 下发的浏览器表在同样输入上与成片实测逐格落在容差内。
- 契约：`blend="soft_light"`（W3C 里存在但我们没有实现）被 `ValidationError` 拒绝，不假装支持。
- 变异测试：把 `_exclusion` 换成 `_difference` 的公式（结构、参数、通道几何全都合法）→ 门禁当场报 `('exclusion', 95.62352943176471)`；恢复原式后 `tests/grade_check.py` 重新全绿。上一轮我误改坏 `_screen` 时同一门禁也曾立刻报 `('screen', 255.0)`，证明这条门看的是产物数值而不是实现意图。
- 界面（1280×800 同源 iframe 真实点击）：在已有绿曲线上把混合方式选成「滤色」→ revision r2→r3，`feFuncG` 第 129 格变成 `0.764862699`，与手算 `screen(128/255, curve(128/255))` 一致；改选「差值」→ r4，同一格变成 `0.02596413`；节点行标题同步显示「· 滤色 / · 差值」。
- 门禁同步：`ruff check`、`ruff format --check`（55 文件）、`npm run typecheck`、5 项 esbuild 桌面检查、33 项 Python 检查串行全绿。

仍未完成：真正的并联/分层节点图（本版的 backdrop 仍是"累积到当前的值"，不是第二路输入）、亮度曲线与 LUT 导入、色域矩阵与 primaries 转换、log 曲线、路径遮罩顶点动画、自动语音字幕、整片母带响度目标、缩略图与波形磁盘配额。

1.32.0 发布验收：冻结引擎 `--verify` 通过后重新打包。包内引擎报 `app_version=1.32.0`、`frozen=true`、`features.grade_node_blend_modes=true`（实例 45db422ae069）。八种混合方式逐个经 `clip.grade` 写入并原样读回 `blend`；`GET /preview-manifest` 下发的 256 项浏览器表与验收脚本里**独立写出的 W3C 公式**逐格比较，八种方式最差 **0.047 阶**；`darken` 配一条结果恒等的曲线时清单里 `grade` 为空、`color_filter` 不再引用任何 `url(#…)`。真实导出六档灰阶：`screen` 源 [0, 2, 10, 30, 94, 253] → 成片 [61, 66, 77, 105, 178, 252]（公式给 [64, 67, 78, 106, 179, 255]，每档 ≤3），`difference` → [61, 61, 59, 54, 38, 0]（公式给 [64, 63, 61, 56, 40, 0]，每档 ≤3），两条互不相同。写入未实现的 `soft_light` 得 422 且 revision 不变。包内 `agentcut.exe mcp`：`tools/list` 未新增工具，`timeline_edit` 提交使 r11→r12、节点读回 `('exclusion', 0.5)`。ASAR 100 条目、renderer/shell 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。便携版 132,464,733 字节 SHA256 3EBABC1E9332E64D2D0EE7F0F874664291AC86BAAC7BC9BD65FD336B79A6ED33；安装版 132,625,448 字节 SHA256 EF4507F261108E4C94C1704236CBE4F2FD98643548FBC0EFA13753216AAED34F；根目录 AgentCut.exe 与便携版逐字节一致。**这一轮原生窗口截图拿到了**：`win-unpacked/AgentCut.exe` 用 `Start-Process` 脱离父 shell 启动后，`PrintWindow(flags=2)` 采到 1936×1048 完整画面（标题栏「AgentCut 剪辑台」、素材库 1 条真实素材、画面 2/主画面/声音三轨、检查器 r7、状态栏「吸附 开 · 62px/s」），Windows Graphics Capture 在该窗口非前台、被遮挡时同样出帧；该会话打开的是用户 `%APPDATA%` 里的真实工程，因此只截图并 `CloseMainWindow` 优雅关闭（`tasklist` 查不到残留），未编辑任何用户数据。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.32-交付记录.md`。

## 1.33 自动闪避：口播一响，配乐自己让路

短视频里最高频的一个动作就是"配乐压在人声下面"。剪映把它做成一个开关，达芬奇在 Fairlight 里挂侧链压缩，
而我们原来只能靠人一段段手打音量关键帧。这一版把它做成引擎端点，并且刻意**不发明新的时间线状态**：
闪避的结果就是一串普通的 `gain` 关键帧。

- 说话区间不是新检测：直接调用 `silence.analyse`（FFmpeg `silencedetect`）取它的**补集**。所以"去空白会剪掉的位置"
  与"闪避会抬回来的位置"是同一个答案，两个功能共用一个阈值口径，也共用 `audio_scan_problem` 的拒绝口径。
- 包络是梯形：说话开始 `attack`（默认 150 ms）内下潜到 `10^(-depth/20)`，说完 `hold` 120 ms 再用 600 ms 抬回来；
  两段说话重叠时取更深的一段——这跟真实压缩器的行为一致。
- **在帧网格上采样再简化**：`volume` 表达式每帧只求值一次，所以断点落在整帧上时，导出听到的与算出来的是同一个数。
  采样后用 Ramer–Douglas–Peucker（容差 0.001 幅度 ≈ 0.009 dB）压成断点。4 秒素材两段说话实测 12 个断点，
  而不是 120 个采样点。
- 新增唯一一条命令 `keyframes.replace{clip_id, property, keyframes[]}`：一次写入某个属性的整条曲线。
  动机是具体的——`edits` 单批上限 100 条命令，用 `keyframe.set` 铺一条 60 点包络会吃掉 60 条配额，多片段轨道放不下，
  而"一次编辑决策"必须仍然是一个 revision。校验：属性一致、时间严格递增、值在 `PROPERTY_LIMITS` 内、非空。
- 界面：声音轨标题行一个「自动闪避」按钮，用契约默认值（-9 dB / 0.15 s / 0.6 s）。深度这类参数留在 HTTP/MCP，
  不在轨道行铺一排旋钮；提示里如实报"替换掉 N 个原有的音量关键帧"。

验收（`tests/duck_check.py`）：

- 数学：包络与测试内**独立重写的梯形函数**逐点比较，最大偏差 **0.0e+00**；断点全部落在帧网格上；
  简化后的折线在每个帧时刻与参考的偏差不超过 5e-4 幅度；`depth_gain(6 dB)=0.5011872`、`depth_gain(20 dB)=0.1`；
  `ramp_ticks(1 ms)` 至少一帧，"斜坡不许落在两帧之间"。
- 契约与事务：`apply=false` 完全不写（revision 不变）；`apply=true` 一次点击 r1→r2；同 `request_id` 重放 `replayed=true`
  且 revision 不变；过期 `expected_revision` 得 409；驱动轨=本轨得 422 `INVALID_DUCK`；不存在的驱动轨 404；
  四种非法 `keyframes.replace`（时间倒序、混第二种属性、增益 9.0 越界、空表）全部 422 且不写库；
  替换 `gain` 不动 `opacity` 的曲线。
- 预览同源：写入后用引擎自己的采样口 `sample_values` 读，1.8 s 处增益 0.354813、5.6 s 与 0 s 处 1.0——
  浏览器拿到的就是这条曲线，导出编译的也是它。
- **导出实测（音频）**：口播轨静音后导出，配乐在同一条时间线上：无闪避成片 -13.5 dB，闪避后说话段 **-25.5 dB**、
  停顿段 -13.5 dB，相差 **12.00 dB** 对 12.0 dB 的请求（`volumedetect` 的 mean_volume，窗口 0.9 s / 0.4 s）。
  这条是 A/B：未闪避的同一素材两个窗口相差 <0.4 dB，证明差值来自闪避而不是编码。
- 变异测试：① 把释放斜坡写死成 `return low` → 数学门禁当场报 `worst 0.7239`；② 把 reducer 的"替换"改成"追加"
  → 第二次闪避直接 422 `PROJECT_LIMIT`（关键帧翻倍撞上限）。两次恢复后 `tests/duck_check.py` 重新全绿。
- 界面（1280×800 同源 iframe 真实点击，工程「自动闪避验收」，素材是 6 秒合成音：880 Hz 只在 1.0–2.5 s 与
  3.5–4.5 s 有，其余为数字零）：点配乐轨的「自动闪避」→ r1→r2，`bg` 片段得到 **16 个** `gain` 关键帧，
  时间点（秒）为 0, 1, 1.13, 1.17, 2.6, 2.63, 3.2, 3.23, 3.5, 3.63, 3.67, 4.6, 4.63, 5.2, 5.23, 6
  ——正是两段说话的帧对齐梯形，最低点 0.354813；口播与画面片段仍然 0 个关键帧。把播放头点到 1.8 s
  （时码 00:00:01:24）后，配乐层的 `.gain-sample` 计算样式 opacity = **0.0887033**（= 0.354813 / 4），
  点到 5.6 s（00:00:05:18）回到 0.25（= 满增益 1.0 / 4）；其它图层始终是 0.25，证明只有被闪避的那条轨在动。
- 门禁同步：`ruff check` 与 `ruff format --check`（57 文件）、`npm run typecheck`、5 项 esbuild 桌面检查、
  33 项 Python 检查串行全绿（含新增的 `tests/duck_check.py`）。

仍未完成：真正的侧链压缩（lookahead、反馈、压缩比曲线——这一版是**包络**不是压缩器）、按片段而不是按整轨选驱动、
母带响度目标、路径遮罩顶点动画、色彩节点图（并联/分层、LUT、色彩管理）、自动语音字幕、缩略图与波形磁盘配额。

1.33.0 发布验收：冻结引擎 `--verify` 通过后重新打包（`package_check_133.py` 驱动 `win-unpacked` 内的包内引擎）。包内报 `app_version=1.33.0`、`frozen=true`、`features.audio_ducking=true`、命令表含 `keyframes.replace`（实例 920ad02d81ed）。口播轨静音后导出两次：无闪避成片在说话窗口与停顿窗口都是 **-13.5 dB**（相差 <0.4 dB，证明差值不是编码造成的）；一次点击闪避（`depth_db=12`）后同一配乐在说话窗口 **-25.5 dB**、停顿窗口 -13.5 dB，**12.00 dB** 对 12.0 dB 的请求。`apply=false` 的回包给出说话区间精确等于合成的 [(1.0, 2.5), (3.5, 4.5)] 秒、**16 个**关键帧、最低点 0.354813（-9 dB 契约默认值），且 revision 不变；`apply=true` 使 r2→r3，重放同 `request_id` 返回 `replayed=true` 且不再涨版本，过期 revision 得 409，`depth_db=0.2` 越界得 422 且不写库。包内 `agentcut.exe mcp`：`tools/list` 共 33 个工具、含新增的 `track_duck`，用它做的规划调用不写库（revision 仍为 3），`timeline_edit` 提交 `keyframes.replace` 使 r3→r4 且三个点的值原样读回 [1.0, 0.5, 1.0]。ASAR 100 条目、renderer/shell 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。便携版 132,474,385 字节 SHA256 4BC5231C14EA4B4C6040887ED9FBDECFE79B1E1C2B31CBDF0E0AF7CC7AFA1E69；安装版 132,635,109 字节 SHA256 354D185F32FD85A67B2A595C8C41FE6EFE843C16912B619987F8CBD85C07169D；根目录 AgentCut.exe 与便携版逐字节一致（`cmp` 通过）。原生窗口：`Start-Process` 脱离父 shell 启动包内 `AgentCut.exe`，`PrintWindow(flags=2)` 采到 1936×1048 完整画面（`agentcut-logs/agentcut133_38424.png`），该会话加载的是用户 `%APPDATA%` 下的真实工程，只截图并 `CloseMainWindow()` 优雅关闭，`tasklist` 查不到残留。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.33-交付记录.md`。

## 1.34 标记的拖拽、改名与颜色

1.29 给了标记一个能用的内核（整数刻度、按标记分割、磁吸边缘），但界面上它只有"点一下跳过去"和"点 × 删掉"
两件事：想把它挪半秒，得手打时码；想给它一个说得出口的名字，只能靠 Agent 写命令。剪映和达芬奇的标记都是
**拖**的。这一版纯补交互，引擎一行没改——`marker.set` 从第一天起就允许用同一个 id 移动与改名。

- 拖动：标尺上的标记按住左右拖，落点走**与片段拖动同一套** `magnet`（整帧量化 + 相邻片段边缘 + 其它标记 +
  播放头），松手提交一条 `marker.set`，一个 revision。
- 单击与拖动的区分：位移不足 3 像素仍按单击处理（跳到该处），避免"想跳却顺手挪了半帧"。
- 双击弹出小面板：改名字（≤64 字，与契约一致）+ 五种颜色（amber/cyan/green/red/violet，就是
  `Marker.color` 的字面量），改完即提交并收起。
- 拖动过程中给 `.dragging` 态（半透明 + grabbing 光标），让人知道现在按下的是"移动"而不是"跳转"。

验收（1280×800 同源 iframe 真实指针事件，工程「标记手势验收」：两段 3 秒镜头 + 一个 2.0 秒的"起点"标记）：

- 拖到 3.0 秒处 → `at_ticks` 变成 3.0000 秒、r1→r2；拖到一个**故意不对齐帧**的位置（3.4 秒再偏 7.5 px）→
  落点 3.533333 秒 = 106 帧整，`at_ticks % 2352000 === 0` 为真，证明量化真的在生效。
- 原地按下抬起（位移 0）→ revision 不变、标记不动，仍是"跳过去"。
- 双击 → 面板出现；把名字改成"开头钩子"按回车 → r3→r4，读回 `name=开头钩子`、`at_ticks` 不变。
- 再双击点青色圆点 → r4→r5，`color=cyan`、名字与时间点都保持，面板自动收起，节点 class 变成
  `ruler-marker cyan`。
- 包内回归（`package_check_134.py`）：包内引擎 `1.34.0` + `frozen=true`（实例 2faaf520432d），
  `timeline_markers` 与上一版的 `audio_ducking`、`keyframes.replace` 全部仍在；把上面三个手势对应的命令
  原样发给包内引擎得 r2/r3/r4；未实现的颜色名 `pink` 被 422 拒绝且不涨版本；MCP `timeline_edit` 用同一条
  `marker.set` 把标记改成 ["Agent 改的", 2.5, "violet"]（r4→r5）——人和 Agent 写的确实是同一个命令。
  包内 CSS（`index-BOyw1tFW.css`）实测带 `marker-edit` / `marker-swatch` / `ruler-marker.dragging` 三条规则，
  ASAR 100 条目、renderer/shell 3 个文件与本地构建逐字节一致、包内引擎 97 个文件。
- 门禁同步：`ruff check` 与 `ruff format --check`（57 文件）、`npm run typecheck`、5 项 esbuild 桌面检查、
  33 项 Python 检查串行全绿（引擎侧本轮零改动，跑的是回归）。

仍未完成：标记的纵向拖拽（把标记拖到某条轨上变成该轨的记号）、多标记成组框选拖动、滑移的鼠标手势
（1.30 只有键盘与检查器入口，本轮试过占用 Alt/Shift，发现它们已经被涟漪裁切占了，所以没有硬塞第二个修饰键）。

1.34.0 发布验收：产物便携版 132,475,253 字节 SHA256 36A1C58B4F4C10C20EEB0FE0B73E526920D33673B76E9B9FBA566B1CA8FD96DD；安装版 132,635,961 字节 SHA256 57E80E0DA3F0726BF56B0673F0A15FEB3A1626C9B244B453962C4A12BA9112EF；仓库根目录 AgentCut.exe 与便携版逐字节一致。原生窗口证据：`Start-Process` 脱离父 shell 启动包内 `AgentCut.exe`，`PrintWindow(flags=2)` 采到 1480×900 完整画面（`agentcut-logs/agentcut134_23480.png`，此刻窗口是还原态而非最大化），随后 `CloseMainWindow()` 优雅关闭，`tasklist` 查不到残留；该会话是用户 `%APPDATA%` 下的真实工程，只截图未编辑。未签名，NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.34-交付记录.md`。

## 1.35 交付画幅：竖屏、方形，以及补边 / 裁切 / 拉伸

横时间线发到竖屏平台是这一行最常见的交付动作。剪映把它放在导出面板里（"分辨率 + 智能填充"），达芬奇放在
Deliver 页的 Scale。我们原来只有 `force_original_aspect_ratio=decrease` + 居中 `pad` 一种结果：任何比例的
导出都必然带黑边，想填满只能导出后再压一遍。这一版把三种适配做成引擎参数，并加两个真正用得上的画幅预设。

- `RenderRequest.fit`：`"contain" | "cover" | "stretch"`，默认 `contain`，与升级前的行为逐比特一致。
  - contain：`scale=…:force_original_aspect_ratio=decrease` + 居中 `pad`，一帧不丢，多出来补黑边；
  - cover：`scale=…:force_original_aspect_ratio=increase` + `crop=out_w:out_h`，撑满，**会丢画面**；
  - stretch：裸 `scale=out_w:out_h`，撑满但比例变形。
- 新预设 `h264-1080x1920-vertical`（9:16）与 `h264-1080-square`（1:1）。适配与预设正交：任何带 `scale` 的
  预设都能配三种适配，预设仍然是服务端定义的白名单——界面和 Agent 都不能塞任意 FFmpeg 参数。
- `fit` 存进 `RenderJob`（任务文档是 JSON，旧任务读出来默认 `contain`），并且**进入 `request_id` 的去重指纹**：
  同一个 request_id 换个 fit 会被判成不同载荷并 409，不会静默复用旧回执。这是"回执必须等于它声称做过的事"
  这条约束在渲染路径上的落地。
- `GET /render-plan?fit=cover` 按所选适配编译，Agent 提交前能先看滤镜串；capabilities 增加 `output_fit_modes`。
- 界面：导出面板预设下面一排「完整保留 / 裁切填满 / 拉伸填满」，提示按当前工程比例与目标比例是否一致说清
  这次形变到底是什么（比例一致时直说"三种结果相同"，不装模作样地让人选）。

验收（`tests/fit_check.py`，320×180 灰底源 + 居中的 60×60 白方块 + 最左 3 px 白竖条）：

- 滤镜层：contain 含 `pad=`、cover 含 `increase` 与 `crop=1080:1920` 且不含 `pad=`、stretch 两者都不含；
  三条都以 `setsar=1,format=yuv420p` 收尾。
- **像素层（真实导出 1080×1920 后逐帧解码比较，不依赖滤镜串自证）**：
  - 白方块落地宽高比 contain **1.000**、cover **0.998**、stretch **0.317**——前两种保持正方形，第三种被
    横向压扁成 0.317:1，正是 16:9→9:16 的形变量 (3.375/10.667)；
  - 顶行均值 contain **0.0**、cover **64.0**、stretch **65.8**——只有 contain 真的留了黑边；
  - 源最左侧的白色竖条：contain 与 stretch 在 x=0 找到，cover 找不到（扫描到的第一个白点已在 x=222），
    证明 cover 确实裁掉了画面而不是又补了边。
- 契约与事务：`fit` 进入任务（`job.fit == "cover"`，重开面板读回）；同 request_id 换 fit → 409；
  `fit="smart"` → 422；`render-plan?fit=cover` 的 argv 与提交后的任务一致，不是硬编码默认值。
- 变异测试：把 cover 的 `crop=` 去掉（滤镜串仍然合法、尺寸仍写 1080:1920）→ 门禁当场报出没有 crop 的那条
  stage；恢复后 `tests/fit_check.py` 重新全绿。
- 门禁同步：`ruff check` 与 `ruff format --check`（58 文件）、`npm run typecheck`、5 项 esbuild 桌面检查、
  34 项 Python 检查串行全绿（含新增的 `tests/fit_check.py`）。

仍未完成：竖屏"跟随主体自动重构图"（cover 是居中裁切，不会跟着人走）、安全区/字幕位置随画幅联动、
路径遮罩顶点动画、色彩节点图（并联/分层、LUT、色彩管理）、自动语音字幕、整片母带响度目标。

- 界面（1280×800 同源 iframe 真实点击，工程「交付画幅验收」，320×180 时间线）：导出面板列出 **7 个预设**
  （含「9:16 竖屏（抖音/Shorts 交付）mp4 · 1080×1920」与「1:1 方形（信息流卡片）」）；「画幅适配」一排三个
  chip 渲染为 完整保留 / 裁切填满 / 拉伸填满，点「裁切填满」后 `.fit-chip.active` 就是它；点「查看渲染计划」
  弹出提示 `按「裁切填满」由服务端编译，界面只读：ffmpeg -hide_banner …`；点「开始导出」后任务表读回
  `{fit: "cover", preset_id: "h264-1080x1920-vertical", status: "succeeded"}`，产物实测 **1080×1920**、
  顶行均值 **64.0**（没有黑边，说明 UI 选的适配真的进了渲染）、中心行均值 177.0（白方块在位）。

1.35.0 发布验收：冻结引擎 `--verify` 通过后打包（`package_check_135.py` 驱动 `win-unpacked` 内的包内引擎）。
包内报 `app_version=1.35.0`、`frozen=true`、`features.output_fit_modes=true`、7 个预设含 1080×1920 与 1080×1080
（实例 d7973c28d259）。`GET /render-plan?fit=cover` 的 argv 含 `force_original_aspect_ratio=increase` 与
`crop=1080:1920` 且不含 `pad=`；三种适配各导一次，产物都是 1080×1920，顶行均值 **contain 0.0 / cover 64.0 /
stretch 64.0**；`fit` 进入去重指纹（同 request_id 换 fit → 409），`fit="smart"` → 422；MCP `render_start` 带
`fit=stretch` 提交 1:1 方形导出并 `succeeded`，任务读回 `fit=stretch`，`tools/list` 仍含 1.33 的 `track_duck`。
ASAR 100 条目、`dist` 下 renderer/shell 3 个文件与本地构建逐字节一致、包内 JS 实测含「画幅适配 / 完整保留 /
裁切填满 / 拉伸填满」四个词、包内 CSS 含 `.fit-chip` 规则、包内引擎 97 个文件。产物：便携版 132,476,874 字节
SHA256 67C470C3781A22A8E85BB29C76E1571413A58E8C7D25A1FC9D51345826514A99；安装版 132,637,590 字节
SHA256 121151A48C3EDE86DE7DC30F74132810A5EC60C46286865F3C4C9C25122216CA；根目录 AgentCut.exe 与便携版逐字节一致。
**本轮原生截图没拿到**：`Start-Process` 启动包内 exe 后 26 秒去枚举该 PID 下最大可见窗口，只抓到 160×28 的
隐藏辅助窗口（主窗口那一刻还没挂在这个 PID 上），截图作废删除；原生渲染证据沿用 1.32/1.33/1.34 连续三轮同一
`win-unpacked` 外壳采到的 1936×1048 / 1480×900 完整画面，加上本轮包内 ASAR 与本地构建逐字节一致这一条链。
应用已 `CloseMainWindow()` 关闭，`tasklist` 查不到残留。未签名，NSIS 向导未点击验收。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.35-交付记录.md`。

## 1.36 批量交付：一次点击交多个画幅

1.35 让"同一个片子用什么画幅出去"变成一次选择，但真实交付是**同时**要横版和竖版。客户端循环调 `renders`
也能做到，只是有个坑：第二条失败时第一条已经在排队了，用户拿到的是半份交付。所以批量必须是引擎的责任。

- 新端点 `POST /v1/projects/{id}/renders/batch`，`RenderBatch{request_id, expected_revision, items(1..4), dry_run}`，
  每条 `RenderBatchItem{preset_id, filename, folder?, sequence_id?, fit}`。文件名沿用单条导出的同一套校验
  （抽成 `checked_render_name`，两处共用一条规则），并额外要求**批内不重名**。
- **原子性**：先给每一条编译渲染计划，任何一条编译失败就整批 422、队列里什么都不留下；全部通过才逐条入队。
  这条是这一版唯一的新保证，所以它必须有一条能失败的验收。
- 回执：每条派生 `<request_id>-<index>` 的独立回执。重放同一批返回同一组任务、不重复排队；改其中一条 →
  `IDEMPOTENCY_CONFLICT` 409。整批锁同一个 `expected_revision`。
- capabilities 增 `batch_delivery`；MCP 增 `render_batch`（写型）；界面在导出面板给一个「附带一个 9:16 竖屏
  （裁切填满）」勾选，勾上后主按钮一次交两份（自动命名 `xxx-9x16.mp4`），三画幅全组合留给 Agent，不在面板
  上堆第二排下拉。

验收（`tests/batch_check.py`）：

- 契约：5 条一批被拒（max_length）、两条同名被拒（"own file name"）、`sub/dir.mp4` 被拒（"bare file name"）、
  无扩展名被拒、`fit="smart"` 被拒。
- **真实交付**：一次调用三条（横版 source-quality + 竖版 cover + 方形 contain）实测导出
  **1920×1080 / 1080×1920 / 1080×1080** 三个文件，全部 `succeeded`。
- `dry_run` 批次：回包给出 3 个任务描述与计划，但任务表为空、输出目录里没有 `.mp4`。
- 重放：同 `request_id` 再提交返回**同样的三个 job id**，任务表仍是 3 条（不重复排队）。
- 原子性：把第二条的预设名改成不存在的 `h264-nonexistent` → 422，任务表**仍是 3 条**，坏文件没落盘。
- 冲突：过期 revision → 409；同 request_id 改一条的 fit → 409。
- 变异测试：删掉 submit_batch 里的预编译循环（坏条目改在第二条）→ 门禁当场报
  `['横版-2.mp4', '方形.mp4', '竖版.mp4', '横版.mp4']`——第一条已经被排队、还自动改了名。恢复后重新全绿。
  这条证明"整批要么全排队要么全不排"不是写在文档里的愿望。
- 界面（1280×800 同源 iframe 真实点击，工程「批量交付验收」）：导出面板出现
  `.batch-row` 勾选「附带一个 9:16 竖屏（裁切填满），一次交付两个画幅」；勾选前主按钮 title 是
  `按 r1 导出 批量交付验收.mp4`，勾选后变成 `按 r1 导出 批量交付验收.mp4 与 批量交付验收-9x16.mp4`；
  点一次按钮后输出目录实测落盘两份，ffprobe 分别是 **320×180** 与 **1080×1920**。
- 门禁同步：`ruff check` 与 `ruff format --check`（59 文件）、`npm run typecheck`、5 项 esbuild 桌面检查、
  35 项 Python 检查串行全绿（含新增 `tests/batch_check.py`，`self_check` 的 MCP 工具集合已含 `render_batch`）。

仍未完成：交付模板（把"这三个画幅"存成可复用的配置）、按平台自动选码率上限、cover 的主体跟随重构图、
安全区随画幅联动、母带响度目标、路径遮罩顶点动画、色彩节点图（并联/分层、LUT、色彩管理）、自动语音字幕。

1.36.0 发布验收：冻结引擎 `--verify` 通过后打包（`package_check_136.py` 驱动包内引擎）。包内报
`app_version=1.36.0`、`frozen=true`、`features.batch_delivery=true`、`output_fit_modes=true`（实例
cb7082531318）。一次 `renders/batch` 交两条：实测落盘 **包内横版.mp4 1920×1080** 与
**包内竖版.mp4 1080×1920**，两条任务都 `succeeded`；`dry_run` 批次回 2 个任务描述但任务表为空；重放同
`request_id` 返回同样两个 job id、任务表仍是 2 条；把第二条预设名改成不存在的 `h264-nope` → 422 且任务表
**仍是 2 条**（没有部分排队）。MCP `render_batch` 在 `tools/list` 的 34 个工具里，用它做 dry-run 回包
`committed=false`、`fits=["cover","contain"]`，且没有改变队列长度。ASAR 100 条目、`dist` 下 3 个
renderer/shell 文件与本地构建逐字节一致、包内 JS 实测含「附带一个 9:16 竖屏」「renders/batch」「-9x16.mp4」、
包内 CSS 含 `.batch-row`、包内引擎 97 个文件。产物：便携版 132,480,283 字节
SHA256 3D3660D9B6CDAEF3A598496F93E83E54BEC14AC1650A36A7A45C15590053BD87；安装版 132,640,992 字节
SHA256 BE8C93AA01721654B932D90F841EBA57CD7F2E658B67F4E15E400BED02C72949；根目录 AgentCut.exe 与便携版逐字节
一致。原生窗口：`Start-Process` 启动包内 exe 后等 45 秒（上一轮 26 秒时主窗口还没挂到该 PID 上，只抓到
160×28 的隐藏辅助窗口），`PrintWindow(flags=2)` 采到 **1480×900 完整画面**
（`agentcut-logs/agentcut136_19344.png`：标题栏「AgentCut 剪辑台」、素材库 1 条真实素材、三轨时间线、
检查器 r7、状态栏「吸附 开 · 62px/s」），随后 `CloseMainWindow()` 优雅关闭，`tasklist` 查不到残留；
该会话是用户 `%APPDATA%` 下的真实工程，只截图未编辑。未签名，NSIS 向导未点击验收。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.36-交付记录.md`。

## 1.37 母带响度目标：量的是真混音，不是各段数字相加

1.27/1.28 让"每一段听起来一样响"，1.33 让"配乐给人声让路"，但平台验收看的是**整片**积分响度。
把各段 LUFS 相加得到整片是个猜测：重叠、淡入淡出、闪避、轨道音量、已有的母带增益都会改变答案，
而 K 加权本身还有绝对 -70 LU 与相对 -10 LU 两道门。这一版不做估计，直接去量。

- `loudness.probe_mix(ffmpeg, project, work)`：用 `compile_render_plan(project, "proxy-540p-fast", preview_size=(64,36))`
  走一次**探测渲染**——同一张 `amix` 图、同一条音频链，只是画面缩到 64×36 所以几乎不花时间——再用与逐片段
  测量同一个 `measure()`（FFmpeg `ebur128=peak=true`）读那个文件，读完立刻删除。
- `loudness.master_plan(measured, current, target_lufs, ceiling_dbtp)`：复用 1.27 的 `normalize_gain`
  （真峰值天花板 + 0–4 倍范围），再把它折算成 `settings.master_gain` 的新值；`predicted_lufs` 按**实际会
  写入的那个值**算，所以 `limited_by` 与 `reaches_target` 说的是工程真实会落到的地方。
- 渲染端只加一级：混音之后 `volume=<master_gain>:eval=frame`，`master_gain == 1.0` 时**完全不产生滤镜阶段**
  （与 1.32 那条"恒等不加滤镜"同一个口径）。浏览器预览把同一个数乘进每条声音的增益里。
- 写入走一次 `project.update` → 一个 revision，撤销即回上一个母带增益；已经对齐时再点报 422 `already sits`，
  不写空变更。capabilities 增 `master_loudness`；MCP 增 `master_loudness`；界面在「工程设置」显示母带音量
  并给「整片对齐 -14 LUFS」。`SequenceSettings` 只加了一个带默认值的字段，旧工程读出来是 1.0，schema 仍 v11。
- 顺手修掉一个真缺陷：`projects.update_project` 原来用 `model_copy(update=...)` 把 JSON 字典塞进带类型的
  `settings` 字段再 dump，Pydantic 在对半构造的项目上序列化时会报 `PydanticSerializationUnexpectedValue`；
  现在直接校验合并后的文档，警告消失（这条是母带端点第一次从别的端点内部调用 `project.update` 时暴露的）。

验收（`tests/master_check.py`，口播 0.5 + 配乐 0.12 两条 4 秒正弦 + 一段无声画面）：

- **探测与成片的吻合**：探测渲染量到 **-25.9 LUFS / -24.5 dBTP**，同一条时间线的完整尺寸导出实测
  **-25.9 LUFS**，相差 **0.00 LU**（门禁 ≤0.5 LU）。这条是整版的地基：量错就别谈对齐。
- 闭环：点一次「对齐 -20 LUFS」→ 建议 `master_gain=1.9724` 并写入（r1→r2）→ 再导出实测 **-20.0 LUFS**
  对 -20.0 目标，真峰值 -18.5 dBTP（不越 -1 dBTP 上限）。
- 诚实的上限：目标 -6 LUFS 时 `proposed_master_gain ≤ 4`、`reaches_target=false`、
  `limited_by="gain_range"`，并报出只能到 **-13.86 LUFS**；不假装达标。
- 事务：`apply=false` 与 `dry_run=true` 都不写库（revision 不变）；已对齐时再点 → 422 `already sits at …`
  且 revision 不变；过期 revision → 409；`target_lufs=-2` 越界 → 422；空时间线 → 422。
- 撤销：`restore` 回到对齐前的版本，`settings.master_gain` 回到 1.0。
- 渲染链：写入后的计划里混音阶段确实带 `volume=1.9724:eval=frame`；母带音量为 1.0 时该阶段不存在。
- 卫生：探测目录里不留任何 `.mp4`（用完即删）。
- 变异测试：把渲染端的 `master` 置空（母带增益不再落到滤镜图）→ 门禁在
  `assert f"volume={gain}" in stage` 处当场失败（混音阶段里根本没有母带音量这一级）。恢复后重新全绿。
- 门禁同步：`ruff check` 与 `ruff format --check`（60 文件）、`npm run typecheck`、5 项 esbuild 桌面检查、
  36 项 Python 检查串行全绿（含新增 `tests/master_check.py`，`self_check` 的 MCP 工具集合已含它）。

仍未完成：限制器/压限（母带只有线性增益，峰值压不下来）、探测渲染的增量缓存（长片每次全量跑一遍）、
交付方案持久化、cover 的主体跟随重构图、安全区随画幅联动、路径遮罩顶点动画、色彩节点图
（并联/分层、LUT、色彩管理）、自动语音字幕。

1.37.0 发布验收：冻结引擎 `--verify` 通过后打包（`package_check_137.py` 驱动包内引擎）。包内报
`app_version=1.37.0`、`frozen=true`、`master_loudness=true`、`batch_delivery=true`（实例 aa57f0978eba）。
包内探测渲染量到 **-25.9 LUFS / -24.5 dBTP**，建议母带增益 2.4831（目标 -18）；`apply=false` 不写库；
`apply=true` 使 r1→r2 并写入同一个建议值；随后用包内引擎真实导出一条 `h264-source-quality` 成片，
`ebur128` 实测 **-18.0 LUFS**，对 -18.0 目标（门禁 ≤0.5 LU）——**整条闭环在发布包里跑通**。再点一次对齐
同一目标得 422 `already sits at …` 且版本不变。MCP `master_loudness` 在 35 个工具里，用它做
`apply=true, dry_run=true` 的目标 -24 请求：回包 `committed=false`、建议 1.24453（比当前 2.4831 低，
方向正确），工程版本仍是 2。ASAR 100 条目、`dist` 下 3 个 renderer/shell 文件与本地构建逐字节一致、
包内 JS 实测含「母带音量」「整片对齐」「master/loudness」、包内引擎 97 个文件。产物：便携版 132,483,187
字节 SHA256 25A4562F7A279F86409F9E4D5EEFF7FF9E3A7EE50C2C3BB64E92371F5F6885E7；安装版 132,643,902 字节
SHA256 B86DA98B0B5E55AB7ADC073E0AE4716AFC66D67F275A90006EC38326867B713A；根目录 AgentCut.exe 与便携版
逐字节一致。界面（1280×800 同源 iframe 真实点击，工程「母带响度验收」）：工程设置里显示
「母带音量 1.000」，点「整片对齐 -14 LUFS」→ 工程 revision 1→2、`settings.master_gain=3.9355`，面板随即
显示「母带音量 3.936」（3.9355 ≈ 10^((−14+25.9)/20)，与探测量到的 -25.9 LUFS 自洽）。
**本轮原生截图没拿到**：`Start-Process` 启动包内 exe 后等 45 秒，逐个枚举 5 个 AgentCut 进程的可见窗口，
只有 1 个 160×28 的隐藏辅助窗口可见，主窗口这次没有挂到任何该进程下（1.36 同一脚本 45 秒能拿到
1480×900 完整画面）。原生渲染证据因此沿用 1.32/1.33/1.34/1.36 四轮同一 `win-unpacked` 外壳采到的
1936×1048 / 1480×900 完整画面，加上本轮包内 `dist` 与本地构建逐字节一致这条链；应用已优雅关闭，
`tasklist` 查不到残留。未签名，NSIS 向导未点击验收。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.37-交付记录.md`。

## 1.38 母带限制器：把峰值交给限制器，增益才管得了响度

1.37 交付后第一件被实测出来的事：对已经顶到头的素材，`normalize_gain` 的峰值上限会先把增益压住，
于是"对齐 -14 LUFS"变成一个永远够不到的目标（回包老实地说 `limited_by=ceiling`）。这在语义上没错，
但在实践上等于告诉用户"你这块素材不行"。广播交付的做法是母带挂限制器：峰值由限制器逐样本守住，
增益只管响度。

- `SequenceSettings.master_limiter` / `master_ceiling_dbtp (-12..0，默认 -1.0)`；
  `MasterLoudnessRequest.limiter`。
- 渲染端在母带增益之后追加 `alimiter=limit=10^(ceiling/20):attack=5:release=80:level=disabled`。
  **`level=disabled` 不是可选项**：FFmpeg 的 alimiter 默认开自动电平，会把信号重新顶到上限——
  实测同一素材带自动电平时峰值 0.0 dBFS、关掉后 -1.0 dBFS，即"有上限等于没上限"。
- 打开限制器时，上限不再参与增益钳制（以 `ceiling_dbtp=0` 传进 `normalize_gain`），`limited_by`
  只剩 0–4 倍范围。这才是这一版真正改变的行为，也是验收要量的那一条。
- 写入后引擎**再探测一次**，把 `after`（写入后的实测混音）放进回包；界面提示引用它，不再引用预测值。
- 界面在「工程设置·母带」加「限制器 -7 dBTP」勾选，与「整片对齐」一起提交。
- 预览**不**演限制器：`DynamicsCompressorNode` 与 FFmpeg 的 alimiter 不是同一个东西，
  在预览里放一个近似的、和导出结果不一致的曲线，比承认"预览是线性增益"更糟。这条写进文档与提示。

验收（`tests/limiter_check.py`，素材是 8 倍增益的 440 Hz 正弦——已经削顶，峰值因子只剩 ~1.5 dB）：

- 基线导出实测 **-3.7 LUFS / 峰值 -2.2 dBTP**。
- 目标 -6 LUFS + 上限 -7 dBTP，**不开限制器**：增益被压到 **0.5754**，`limited_by="ceiling"`、
  `reaches_target=false`，只能到 **-8.5 LUFS**。
- 同样的目标与上限，**开限制器**：增益 **0.7674**（= 10^((-6+3.7)/20)，不再被压）、`limited_by=""`；
  滤镜串出现 `alimiter=limit=0.446684:...:level=disabled`，limit 与 10^(-7/20) 相差 <1e-5。
- 真实导出实测 **-7.7 LUFS / 峰值 -6.4 dBTP**：峰值比未处理低 **4.2 dB**、贴在 -7 上限附近
  （真峰值表读到的过冲 0.6 dB 属正常，门禁给 +0.8 的余量），响度比被压增益的方案高 **0.8 LU**。
  素材本身峰值因子太小，-6 LUFS 与 -7 dBTP 在物理上不能同时成立——`after` 如实报了 -7.7，
  没有假装到了 -6。
- 端点的 `after` 探测与真实导出相差 **≤0.3 LU / ≤0.3 dB**（两个方向都断言）。
- 契约：`ceiling_dbtp=-20` 越界 → 422；`alimiter` 只在 `master_limiter=true` 时出现；
  `restore` 回对齐前版本时 `master_limiter=false`、`master_ceiling_dbtp=-1.0`、`master_gain=1.0` 一起还原。
- 门禁同步：`ruff check` 与 `ruff format --check`、`npm run typecheck`、5 项 esbuild 桌面检查、
  37 项 Python 检查串行全绿（含新增 `tests/limiter_check.py`）。

仍未完成：预览端的限制器（刻意不做）、真·LUFS 范围（LRA）与瞬时峰值报告、按平台预设目标值、
探测渲染增量缓存、交付方案持久化、cover 主体跟随重构图、安全区随画幅联动、路径遮罩顶点动画、
色彩节点图（并联/分层、LUT、色彩管理）、自动语音字幕。

1.38.0 发布验收：冻结引擎 `--verify` 通过后打包（`package_check_138.py` 驱动包内引擎，实例 067a626a47a8）。
包内基线导出实测 **-3.7 LUFS / 峰值 -2.2 dBTP**；同一目标 -6 LUFS + 上限 -7 dBTP，**不开限制器**时包内引擎
把增益压到 **0.5754**、只到 **-8.5 LUFS**（`limited_by=ceiling`）；**开限制器**后增益 **0.7674** 不被压，
包内真实导出实测 **-7.7 LUFS / 峰值 -6.4 dBTP**，而端点写入后再探测的那一次报的正是同一组数
（-7.7 / -6.4，相差 0.0）；`render-plan` 的 argv 在 `master_limiter=false` 时不含 `alimiter`，为 true 时含
`alimiter=limit=...:level=disabled`。MCP 的 `master_loudness` inputSchema（`$defs.MasterLoudnessRequest`）
确实暴露 `limiter` 字段，`dry_run` 回包 `committed=false` 且工程版本不变。ASAR 100 条目、`dist` 下 3 个
renderer/shell 文件与本地构建逐字节一致、包内 JS 含「限制器 -7 dBTP / master_limiter / 写入后再量一次」、
包内引擎 97 个文件。产物：便携版 132,484,994 字节 SHA256 4E1DBC5649C2CFFC040B71386945F0947C2E658334B304F6D789F3055EB4F961；
安装版 132,645,713 字节 SHA256 00153431A4C4EBF404AA9A91BA1330FA6D6B83E63465D86EA34472EB2B7441B9；根目录
AgentCut.exe 与便携版逐字节一致。
界面（1280×800 同源 iframe 真实点击，工程「母带限制器验收」）：勾「限制器 -7 dBTP」再点「整片对齐 -14 LUFS」
→ 工程 r1→r2，`settings = {master_gain: 3.9355, master_limiter: true, master_ceiling_dbtp: -7.0}`，面板显示
「母带音量 3.936 限制器 -7 dBTP」。**这一轮的真实点击抓到一个我自己写出来的交付缺陷**：第一版标签写死
「限制器 -7 dBTP」，但请求没带 `ceiling_dbtp`，引擎按契约默认落成 **-1.0**——界面上承诺的上限和实际生效的
不是同一个数。修法是标签与请求共用一个 `MASTER_CEILING_DBTP` 常量，重测后写入值变成 -7.0，标签也补回负号
（第一版渲染成「限制器 7 dBTP」，丢了负号）。提示条文案（"写入后再量一次 …"）本轮**没能在界面上读到**
（toast 几秒后自动消失，我读的时候已经没了），所以这条只作为源码与包内 JS 字符串的证据，不声称看到过。
另外：第一次 `npm run dist` 在下载 Electron 运行时时被服务端中断（got ReadError），产物未更新，重试一次才
成功——本轮时间戳以 21:34 那次为准。原生窗口截图本轮未采（1.37 同一脚本连试两遍只拿到 160×28 隐藏窗口，
说明取样时机不稳；原生渲染证据沿用 1.32/1.33/1.34/1.36 的完整画面 + 本轮 ASAR 逐字节一致）。未签名，
NSIS 向导未点击验收。完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.38-交付记录.md`

## 1.39 调色节点·并联分支（2026-10-07）

达芬奇给每个节点一张图：串行、并联、图层。1.32 给了串行 + 每通道混合方式，1.31 给了传递函数，
但「两支从同一处分开、各调各的、再合起来」一直缺。这一版补上并联节点，并且刻意只做**能保持一张
每通道表**的那种图。

- 契约：`GradeParallel {kind:"parallel", branches:[1..4 个操作], enabled, mix, blend}`，支的取值就是
  `curve`/`white_balance`/`wheels`/`transfer` 四种，各自带 `mix` 与 `blend`；支不得再嵌并联（判别联合
  直接拒绝），所以图只有一层。命令仍是 `clip.grade` / `clip.patch.color.grade`，端点、MCP 工具、
  回执结构一律不变，capabilities 增 `grade_parallel_branches`，工程 schema 仍 v11（`parallel` 是新
  `kind`，旧载荷里没有它，v1–v10 的载荷与回执继续原样重放）。
- 语义：`node_out = mean_j( step_j(in) )`，再按节点自己的 `blend`/`mix` 与 `in` 混合。停用一支**贡献它的
  输入**（达芬奇里被绕过的链输出就是它的输入），所以「一支有效、其余停用」等于该支按 `1/支数` 生效，
  而不是把支数改掉——这条语义被写成一条可执行的等价断言：并联 `[曲线, 停用]` 的表 ≡ 曲线 `mix=0.5` 的表。
- 为什么两端仍然同源：串行是复合、并联是平均、混合方式是 W3C 的逐通道可分函数，三者都不跨通道，
  所以整个图仍塌缩成每通道一条折线。`grade.py` 的改动只有 `node_function` 多一种 `kind`（返回求各支
  `step_function` 后取均值的函数），折线合成、自适应打点、`lutrgb` 表达式、`feComponentTransfer` 表
  一行没动；界面也**不需要**为并联新增第二条预览路径。亮度曲线、LUT、色域矩阵之所以还没做，正是因为
  它们跨通道，需要 3D 查找表，而浏览器侧只有每通道的 `feComponentTransfer`——两端不同源就不能声称
  预览等于导出，宁可显式说未实现。
- 顺带修掉一处会长期复发的缺陷：`app_version` 原本手写在 `__main__.py` 与 `http_api.py` 两处、
  桌面 `package.json` 第三处（1.29 把 schema 版本号收成一处正是同一个教训）。现在三处都读
  `contracts.APP_VERSION`，本轮 `GET /v1/info` 实测报 `app_version=1.39.0`。
- 验收（`tests/grade_check.py` 的 parallel 三套）：三支（色温 +0.8 / 色调 +0.6 / 恒等）浏览器 256 项表
  与测试内**独立重写的平均算术**逐格比较最差 **0.434 阶**；同两个操作串起来的表与并联差 **24.6 阶**；
  串行换序改变 **53.2 阶**，而并联换支序逐位相同（<1e-9）；+0.3/−0.3 色温平均在 234/256 档恒等（顶部
  22 档因 1.09× 削顶），同对节点串行在中灰仍偏 **1.04 阶**；只动红通道的支不改变绿/蓝表；`mix=0` 的
  并联节点不产生任何滤镜阶段；成片三档色带九通道对独立参考最大偏差 **2.01 阶**、与串行导出相差
  **23.0 阶**；HTTP 一笔写图一个 revision、重放不涨、旧 revision 409、`dry_run` 不写、空支/5 支/嵌套
  并联 422 且不烧版本、`restore` 把支数与强度一起还原。变异验收：把 `average` 改成「取最后一支」，
  数学门禁当场报 **55.44 阶**。
- 界面（vite 渲染层 + 同一引擎 HTTP，工程「并联节点界面验收」，真实导入 640×360 4 秒素材）：选片段 →
  「+并联」→ r1→r2，节点行「1. 并联 · 2 支」→「+支」→ r3（三个支标签）→ 支 1 色温 80 → r4 → 支 2
  色调 60 → r5 → 支 1 强度 50 → r6，每笔恰好一个 revision。每一笔后读 DOM `<filter id="g…">` 三条
  `feFunc* tableValues` 与页面内独立重算的三支平均比较，最大偏差 **1.2e-7**；换强度后滤镜 id 由
  `g03025c48aabec4d9` 变成 `g9fb569a043120063` 并再次逐位吻合。随后同一工程提交 `h264-720p-web` 导出，
  任务 `succeeded`，把成片与源在同一时刻逐像素比对（只取两侧都平坦的区域）：**16,955 个像素**按通道
  检查「成片值 = 浏览器表在源值处的输出」，最差 **5 阶**（出现在输入 255 的削顶处）。同一次验证还
  证明了输出根守卫：`folder` 指向未授权目录时服务端返回 `OUTPUT_NOT_ALLOWED`，不写文件。
- 门禁同步：`ruff check`、`ruff format --check`（65 文件）、`npm run typecheck`、38 项 Python 检查
  与 5 项 esbuild 桌面检查全绿；本轮无新命令、无新 MCP 工具、无新依赖。

仍未完成：图层节点（第二路输入取自图中另一个节点，需要节点连线视图与跨节点求值）、亮度曲线与
LUT 导入、色域矩阵与完整色彩管理（三者都要跨通道的 3D 表，浏览器侧只有每通道 `feComponentTransfer`）、
路径遮罩顶点动画、多目标与长时遮挡跟踪、旋转估计、自动语音字幕、缩略图与波形磁盘配额、代码签名。

1.39.0 发布验收：本轮开始时先确认并修掉一条**已发生的交付缺陷**——`desktop/release/` 整个目录（README
「直接用（桌面版）」表格里指向的 `AgentCut-安装版.exe`，以及 1.16–1.38 每一轮都记了 SHA256 的安装版产物）
在本会话之前已被删除，仓库里只剩根目录的便携版；`desktop/node_modules/` 同样不在。便携版经
`sha256sum` 核对与 1.38 记录逐字节一致（`4E1DBC56…F961`，132,484,994 字节），因此缺失的是安装版与
win-unpacked。修法就是按文档里的重建路径重做一遍：`npm ci`（398 包，与锁文件一致）→
`uv run python scripts/build_engine.py --verify` → `npm run dist`。

冻结引擎 `--verify` 通过：`app_version=1.39.0`、`frozen=true`、裸启动冷启动 603 ms、`mcp` 模式存活、
`tools` 与 `--help` 退出 0。发布包验收（`package_check_139.py` 驱动 `release/win-unpacked` 内的包内引擎，
实例 a0af937317b5 / 6ae1904283e9）：capabilities 报 `grade_parallel_branches=true` 且 `commands` 含
`clip.grade`；三支并联（色温 +0.8 强度 50 / 色调 +0.6 / 恒等）一次写入得 r2、`branches` 与强度原样读回、
同 `request_id` 重放不涨版本、空支表 422 且不烧 revision；`GET /preview-manifest` 的 256 项表与验收脚本内
**独立重写的分支平均**（含每支各自钳位）逐格比较最差 **0.273 阶**；真实导出 `h264-720p-web` 与同素材
无调色对照各测三条色带的到达值（30 / 126 / 222），逐通道比较「成片值 = 表在到达值处的输出」最差
**2.0 阶**；ASAR 内实测含「并联」「grade-b」「"parallel"」「branches」四串；包内 `agentcut.exe mcp` 用
`timeline_edit` 写一个两支并联（wheels + white_balance）使 r2→r3 并原样读回。产物：便携版 132,487,482
字节 SHA256 DFD29114392B9CA6B870466DC11E6BB6B4A469B28766700A0AC6DF1D36B47FFD；安装版 132,648,205 字节
SHA256 92E2AAC2F5135CDF21DADA4C8795B27557DE1C9F62A6FF22752D9A18776A2F1E；根目录 `AgentCut.exe` 已与便携版
`cmp` 逐字节一致。原生窗口本轮**再次拿到截图**：`Start-Process` 脱离父 shell 启动包内
`win-unpacked/AgentCut.exe`，45 秒后该 PID 下枚举到 1 个可见窗口「AgentCut 剪辑台」1480×900，
`PrintWindow(flags=2)` 采到完整画面（`agentcut139.png`：标题栏工程名 + r7、素材库 1 条真实素材带缩略图、
画面/主画面/声音三轨、检查器显示母带音量 1.000 与「限制器 -7 dBTP」勾选、状态栏「吸附 开 · 62px/s」），
随后 `CloseMainWindow()` 优雅关闭，`Get-Process AgentCut,agentcut` 查无残留；该会话加载的是用户
`%APPDATA%` 下的真实工程，只截图未编辑。未签名，NSIS 向导未点击验收。

本轮两条台架事实记录在案（都是我的验收写错、不是产品错，改对了才算门禁有效）：① 第一版包内参考实现把
钳位放在**求平均之后**，而产品是每支各自钳位再平均，于是报出 7.31 阶的假偏差；② 第一版成片比较用
「源文件解码值」当表的输入，忽略了图内部 yuv→rgb 与验收脚本解码的到达值不同，报出 4 阶假偏差；改成
「同一次编码、无调色对照的到达值」作输入后，实测 2.0 阶。

全量门禁（本轮结束时）：`ruff check`、`ruff format --check`（65 文件）、38 项 Python 检查（含
`tests/grade_check.py` 的 parallel 三套）串行全绿、5 项 esbuild 桌面检查全绿、`npm run typecheck` 通过。
完整记录见 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.39-交付记录.md`。

## 1.40 时间线入出点与区间导出（2026-10-07）

剪映与达芬奇的「只出这一段」是交付日常里最常用的动作之一：横版整片 + 竖版片段、审片只发中间 20 秒、
把一条长口播按标记切成几段分别出片。1.35 给了画幅三种适配、1.36 给了批量交付，但导出对象只能是整条
时间线。这一版补上区间，并且刻意**不新增编辑命令**：区间是工程设置里的一对整数刻度，导出只是一个参数。

- 契约：`SequenceSettings.in_ticks / out_ticks`（默认 `null`）。要么都给要么都不给、必须整帧、`in < out`；
  出点越过当前内容由 `validate_timeline` 一处判 `INVALID_MARKS`（与 1.29 的标记共用
  `project_content_ticks` 这一个「时间线有多长」的权威）。写入走既有 `POST /v1/projects/{id}` 的
  `settings` 替换，所以一次设点恰好一个 revision，撤销/历史/去重回执全部继承；schema 仍 v11。
- 渲染：`RenderRequest.range: "full" | "marks"`（批量项同名）。`jobs.plan_for()` 是唯一把 `range` 翻成
  刻度的地方，计划预演、排队任务、worker 三处共用；没有点却请求 `marks` 一律 422，不会静默出整片。
- **裁在哪里**很关键：`compile_render_plan` 在 `[vout]`/`[aout]` 之后才 `trim=start_frame:end_frame` +
  `atrim=start:end`，也就是区间成片用的是整片同一张合成图、同一次 `amix`、同一个母带增益与限制器。
  如果反过来「按区间重规划一遍时间线」，淡入淡出、转场权重、母带探测都会跟着变，区间版本就不是整片
  版本的那一段了。画面已 `fps=` 归一化，所以帧号精确；声音用秒。
- 回执：`range` 只在非默认值时进入去重指纹，1.39 及更早的渲染回执继续原样重放；改 `range` 得 409，
  不会把旧文件当成新交付。
- 界面：标尺上一条 `.ruler-range` 带子加两个手柄（拖动走与片段同一套整帧量化，方向键微调一帧、
  Shift 十帧），`I`/`O` 在序列监视器下给时间线打点（素材监视器下仍是素材入出点），`Alt+X` 清除；
  导出面板多一排「整条时间线 / 入出点区间」chip，没有点时后者禁用并把原因写在 title 里。
- 验收（`tests/marks_check.py`，39 项 Python 检查之一）：见 `docs/api.md` 的 1.40 节，关键数字——
  整片 6.000 秒 vs 区间 2.000 秒；区间首帧绿、音高 879 Hz（整片同点 439 Hz）；区间第 0.5 秒与整片
  第 2.5 秒逐通道差 **0 阶**；界面 `I→O→拖手柄→导出→Alt+X` 逐笔 r1→r5，UI 触发的那次导出任务
  `range=marks`、产物 ffprobe 3.067 秒；1040×660 无横向溢出。
- 变异验收（两次都改 `render.py`，跑完 `cmp` 确认逐字节还原）：① 把 `trim` 的 `end_frame=` 换成
  `duration=`（滤镜仍合法、画面仍从头开始）→ `plan_suite` 当场报
  `[vout]trim=start_frame=30:duration=4.000000,setpts=PTS-STARTPTS[vrange]`；② 让区间情况下
  `plan.duration_ticks` 仍等于整片长度 → 同一套里 `assert plan.duration_ticks == 4 * T` 报
  `423360000`。两条都证明门禁看的是产物里的帧窗与时长，而不是实现意图。

仍未完成：四点剪辑（源入出点 + 时间线入出点一次算成插入/覆盖，含按区间长度写变速曲线或裁尾）、
图层节点与连线视图、亮度曲线与 LUT、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、
自动语音字幕、缩略图与波形磁盘配额、代码签名。

1.40.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.40.0`、`frozen=true`、带素材冷启动 676 ms、
裸启动 613 ms、`mcp` 存活、`tools`/`--help` 退出 0）后 `npm run dist` 重新打包。包内验收
（`package_check_140.py` 驱动 `release/win-unpacked` 内引擎，实例 7f7a726814cd）：capabilities 报
`project_schema_version=11`、`timeline_marks=true`、`range_export=true`；没有入出点时请求
`range=marks` 得 422 `INVALID_MARKS` 且不排队任务；`project.update` 写入第 60–120 帧恰好一个 revision
（r2）；`GET /render-plan?range=marks` 的 argv 含 `trim=start_frame=60:end_frame=120` 与
`atrim=start=2.000000:end=4.000000` 且 `duration_seconds=2.0`，不带 `range` 的那一份两者都没有、
`duration_seconds=6.0`；真实导出两份：整片报告 6.000 秒 / ffprobe 6.000 秒，区间报告 2.000 秒 /
ffprobe 2.000 秒，区间首帧为绿段而整片首帧仍为红，区间第 0.2 秒音高 **879 Hz** 对整片同点 **439 Hz**，
区间第 0.5 秒与整片第 2.5 秒逐通道差 **0 阶**。包内 `agentcut.exe mcp`：`tools/list` 与上一版完全相同
的 35 个工具（本版没有新工具），`project_update` 移动入出点 r2→r3 原样读回，`render_start`
带 `range=marks` 出 3.000 秒成片。包内容器核对（`asar_compare.py`）：`app.asar` 内 5 个 renderer/shell
文件与本地构建**逐字节相同**、包内 `agentcut.exe` 与验收用的冻结引擎逐字节相同、ASAR 内
`package.json` 版本 1.40.0，并实测含「入出点区间 / ruler-range-handle / 整条时间线 / in_ticks /
"marks"」五个串。产物：便携版 132,491,248 字节 SHA256 CF56ED1A9B120DF070647A7E2B48A41576FDB65A192226520A374F6705A807BB；
安装版 132,651,956 字节 SHA256 B04C3CB59931C98C6E875F02669DEF64895650B33037FAB2B696EB984464FD3A；
根目录 `AgentCut.exe` 与便携版 `cmp` 逐字节一致。全量门禁：`ruff check`、`ruff format --check`
（66 文件）、39 项 Python 检查（含新增 `tests/marks_check.py`）、5 项 esbuild 桌面检查与
`npm run typecheck` 全绿。

一条必须如实记录的证据边界：本轮也启动了包内 `win-unpacked/AgentCut.exe` 并用 `PrintWindow(flags=2)`
采到 1480×900 的「AgentCut 剪辑台」窗口（该会话是用户 `%APPDATA%` 下的真实工程，只截图未编辑，
`CloseMainWindow()` 后 `Get-Process` 查无残留），但得到的 PNG 与 1.39 那张**逐字节相同**——首页在两个
版本之间确实没有可见差异（新区间 UI 在时间线标尺与导出面板里），所以这张图不能单独作为「1.40 渲染
成功」的证据；包内内容的证据是上面那条 ASAR/引擎逐字节比对。未签名，NSIS 向导未点击验收。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.40-交付记录.md`。

## 1.41 四点剪辑（2026-10-07，引擎与 Agent 入口）

路线图「精确剪辑」一栏最后一件没做的：J/L cut 早已被 1.21 的拆分内嵌音轨 + 独立修剪覆盖（音视频本来
就在不同轨上，各自 `clip.trim` 即可），缺的是四点剪辑——「素材这一格到那一格，放进时间线这一格到那一
格」。1.40 把时间线那一对点做成工程状态，这一版把四个整数解算成一次放置。

- `fourpoint.plan()` 只判定该裁还是该改速，然后产**一条**普通 `clip.insert` / `clip.overwrite`；放置
  是否合法（窗口、锁轨、重叠、时钟）仍然只由 reducer 判，适配层没有第二条规则。
- 三种解算都回传实测数字：`resolution` 为 `exact` / `trimmed` / `re-timed`，`consumed_source_ticks`
  是「实际会读到多少素材」。源长 > 目标长只能裁；源长 < 目标长只能改速，且 `speed_percent` 取整后若与
  请求相差超过一帧就拒绝——不做「悄悄少读一点」的近似，也不假装整数百分比能命中任意比例。
- 端点 `POST /v1/projects/{id}/four-point`（`apply=false` 只给命令），MCP 只读工具 `clip_four_point`，
  capabilities 增 `four_point_editing`；不新增时间线状态、不改 schema。
- **本轮被自己的验收抓出来的缺陷**：clip id 原本用 `uuid4()` 生成，于是同一 `request_id` 重放会构造出
  不同的批命令，指纹对不上自己的回执 → 直接 409。改成 `sha1(request_id)[:12]` 后重放才真正幂等。这条
  正是「回执必须等于它声称做过的事」在新端点上的复发，也说明为什么每个新写入口都要有一条重放断言。

验收（`tests/fourpoint_check.py`）：解算层 exact/trimmed/re-timed 各一条命令并逐字段断言；12 组不可能
点位各自返回说清原因的错误码（非整帧、零长、倒序、轨别不匹配、越界、未验证、百分比出界）；HTTP 层
plan 与 dry-run 不写库、一次 apply 一个 revision、重放不涨、旧 revision 409、`restore` 是新 revision；
成片层 2 秒素材以 50% 铺满 4 秒（4.000 秒、第 0.5 秒红第 3.5 秒绿、音高 439→825 Hz，即时间拉长而音高
保持），裁尾那条覆盖 4–6 秒且被裁掉的蓝色尾段在逐帧采样里从未出现。
门禁：`ruff check`、`ruff format --check`（69 文件）、`tests/suite_check.py` 一次跑完 40 项 Python 检查全绿
（fourpoint 3.2s、grade 5.2s、marks 4.4s、self 76.9s）、5 项 esbuild 桌面检查与 `npm run typecheck` 全绿。
新增的 `tests/suite_check.py` 本身也被变异验证过：放一条故意失败的 `*_check.py` 进去，它打印 FAIL、贴出子进程
末尾输出并以非零码退出；删掉探针后同一入口对真实检查打印 PASS 并返回 0。它存在的意义就是过去「门禁全绿」
只跑了 `self_check.py`，39 个逐功能检查是否真的执行过无从证明。

界面入口已随本版交付（不是待办）：素材监视器 `入点 I` / `出点 O` 取源的两个点，时间线标尺上的区间带取目标的两
个点，「四点→时间线区间（插入）」与「四点→覆盖」两个按钮把四个整数交给 `/four-point`，`fit=auto`，回来的一条
命令走和普通放置同一个 `submit`。1280×800 同源 iframe 真实点击：r4→r5 恰好一个 revision，提示条按引擎回包如实
写「素材更短，按 98% 变速铺满 2.03 秒 · 读素材 1.99 秒」，库里落库的正是 `position=1.0s, duration=2.0333s,
source_in=1.0s, speed_percent=98`，被插入点切开的原片段仍首尾相接，撤销一步回到放置前。这一轮也被自己的验收抓到
一条界面缺陷：按钮先只按 `source.asset` 找素材，从时间线片段进来的路径拿不到，于是对着已登记的素材报「这份素材
还没有登记进工程」；改成与 `editSource` 同一条按 `verified.path` 回查的规则后才通。

1.41.0 发布验收：冻结引擎 `--verify --measure 2` 通过（裸启动 4 次 min 588 ms / median 595 ms / max 680 ms），
重新打包后包内引擎 `/v1/info` 报 `app_version=1.41.0`、`frozen=true`、`media_ready` / `render_ready` 均为真，
`/v1/capabilities` 声明 `four_point_editing`、`project_schema_version=11`。四点在包内实测：源 0–2 秒 → 目标 0–4
秒解为 `re-timed` / 50%，`plan`（`apply=false`）与 `dry_run` 都不写库、读回 revision 不变，一次 apply 恰到一个
revision，**同 `request_id` 重放返回自己的回执**（不新增片段、不涨 revision——这条就是开发期被 `uuid4()` 抓到的
那个缺陷在发布物上的复验），旧 revision 409，源越过素材末尾 422 `SOURCE_OUT_OF_BOUNDS`。包内 MCP 的
`clip_four_point` 在 `tools/list` 里带 `readOnlyHint=true` 且四个点都在 inputSchema 中，调用它解出 `trimmed`
（实际消费 2.00 秒源）而库里 revision 不动。成片：改速那条 4.000 秒、首帧 (254,0,1) 与第 3.8 秒 (254,0,1) 都是红，
440 Hz 音在前段与后段都量得 440 Hz——时间被拉长而音高保持；裁尾那条 2.000 秒、0.1 与 1.9 秒都是 (1,128,3) 绿、
音 879 Hz，被裁掉的蓝色尾段从未进文件。撤销放置本身是新 revision 且不留片段。ASAR 版本号 1.41.0，渲染层 3 个文件
与 `dist/` 逐字节一致、包内引擎与验证过的构建一致（`asar_compare.py`），便携版与根目录 `AgentCut.exe` 逐字节相同
（SHA256 `9c1377c8…3a0e`，132,496,654 字节；安装版 `a8c7431d…5ec7`，132,657,371 字节）。`win-unpacked/AgentCut.exe`
启动到 1480×900「AgentCut 剪辑台」，`CloseMainWindow` 后 `Get-Process` 查不到残留。
**如实记录一条证据边界**：这次的原生截图 PNG 与 1.40 的那张逐字节相同（125,651 字节，MD5 `31270d1b…`）——空工程
启动画面本就与本版无关，所以这张图只证明「发布物能启动并把工作台画出来」，不证明四点按钮的像素；四点界面代码
进入发布物的证据是 ASAR 内的 `四点→时间线区间（插入）` / `四点→覆盖` / `/four-point` 字节级存在，加上那份 ASAR
与本地被真实点击验证过的前端逐字节一致。未签名，NSIS 向导未点击验收。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.41-交付记录.md`。

仍未完成（截至 1.41）：图层节点与连线视图、亮度曲线与 LUT、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、
自动语音字幕、缩略图与波形磁盘配额、交付方案持久化、cover 主体跟随重构图、代码签名。

## 1.42.0 交付方案持久化（2026-10-07，工程 schema v12）

达芬奇的 Deliver 页、剪映的「导出预设」都把「出货的那组选择」留下来。AgentCut 之前只留下选择的一部分：预设表
是引擎里的受控清单，但「这条时间线要出横屏 + 竖屏、竖屏用裁切填满、只出口播区间」这组设置每次都要重填，
Agent 也无法引用它。1.42 把它做成工程状态。

- `Project.recipes`（v12）= `{id, name, items[1..4]}`，`items` 直接复用 `RenderBatchItem`——**没有**再造一个
  「方案条目」模型，方案里存的就是批量交付的输入本身，所以界面和引擎不可能对同一份方案各说一套。
  上限与「一批最多 4 条」对齐：存一份永远发不出去的列表不如不存。
- 两条命令 `recipe.set` / `recipe.remove` 走既有批事务：写入仍要 `request_id` 与 `expected_revision`，仍是一个事务里
  同时落工程、历史与去重回执，`dry_run` 不写库，恢复是一个新 revision。reducer 额外只做一件事：预设 id 不在
  `render_presets()` 里就整笔 422 `INVALID_RECIPE`（点名哪个预设、哪条交付）且不烧 revision——「预设是否存在」这条
  规则仍只有 `render_presets()` 一处，渲染时的 `plan_for` 一字未改。
- 契约 `extra="forbid"` 让方案不能夹带 `crf` 之类的编码器字段：方案记录的是**选择**，不是 FFmpeg 参数。
- 不新增 MCP 工具：两条命令从契约自动出现在 `timeline_edit` 的入参 union 里，`tests/self_check.py` 的工具集合断言
  因此保持不变（它的价值就在于新增工具时当场变红）。
- capabilities 增 `features.delivery_recipes`，与 `batch_delivery` 一样依赖媒体探测——没有 FFmpeg 就没有货可出，
  这时不能声称该能力可用。

界面：导出面板多出一行「交付方案」。芯片主按钮 = 按方案一次排队多条交付（仍锁当前 revision，整批先编译通过才入队），
「覆盖」把面板当前设置写回该方案，「删」只删方案、不动时间线、可撤销。芯片的 `title` 逐条列出 `文件名 · 适配/范围`，
点之前就知道会出几路货；「存为方案」用的就是「开始导出」将要发出去的那组 `pendingItems`（同一处计算，两按钮不会漂移）。

验收（`tests/recipe_check.py`）：契约层 7 组拒绝；事务层含「重放不复制方案」「dry-run 返回候选工程而库里不动」
「未知预设不烧版本」「restore 还原方案列表」「换一个新的 `ProjectStore` 打开同一个 sqlite 文件能读回方案」；
出货层把库里读出的 `items` 原样发给 `/renders/batch`，实测 **1920×1080 与 1080×1920 各 4.000 秒**——这条是「方案不是
装饰」的证据；带 `range=marks` 且没有入出点时整批 422 且队列长度前后相等。界面在 `127.0.0.1:5178` 对真实引擎
（`127.0.0.1:8791`，1.42.0 / schema v12）点击：r1→r2 存方案（芯片「横竖双交付 1 条」），勾「附带 9:16」后「覆盖」
r3→r4、引擎读回该项确实是 2 条、芯片同步显示「2 条」，点方案名一次排队两条都锁 r4，两条成片
1920×1080（2,587,407 字节）与 1080×1920（950,159 字节）各 4.000 秒。

两处如实记录：驱动脚本一开始用 `dispatchEvent(new Event("change"))` 勾复选框，React 在 `click` 上归一化 checkbox，
于是「覆盖」只写进 1 条——是脚本的问题，改成真实 `click()` 后一切对得上；这一步当时没有像素证据（本机 in-app browser
截图返回 `visibilityState=hidden`），界面证据是 DOM 层与引擎回包。发布包的 1480×900 原生截图随后补上了这一块，
见下面的 1.42.0 发布验收——它同时证明标题栏的 `引擎在线 v1.42.0` 真的画出来了。

门禁：`ruff check` / `ruff format --check` 全绿，`tests/suite_check.py` 从 39 项增至 **40 项**（新增 `recipe_check.py`）全绿。
schema 从 v11 升到 v12 时 `grade / link / marker / transition` 四处硬编码 `== 11` 当场变红、逐条改到 12；
`pathmask_check.py` 里那句显式 `"schema_version": 11` 的老载荷**保留**——它测的就是旧快照还能读。

仍未完成（截至 1.42）：图层节点与连线视图、亮度曲线与 LUT、色域矩阵与色彩管理、路径遮罩顶点动画、
多目标与长时遮挡跟踪、旋转估计、自动语音字幕、缩略图与波形磁盘配额、cover 主体跟随重构图、代码签名。

## 1.43.0 安全区参考线（2026-10-07）

「安全框」原来是一个本地 `useState`：刷新即丢、百分比写死在 CSS、Agent 看不见。现在它是
`settings.safe_area`（`off`/`action`/`title`），写入走既有的 `project.update` 路径，因此幂等回执、
乐观版本、历史撤销全都白拿；内缩数字改由 `capabilities.safe_area_insets` 下发，契约里的
`SAFE_AREA_INSETS`（BT.601/709 的 3.5% / 5%）是唯一来源，界面不再自带一套百分比。
新增 `features.safe_area_guides`；不新增命令、端点或 MCP 工具，schema 仍是 v12。

验收 `tests/safearea_check.py`：非法值四组各自拒绝、缺键读作 `off`、一次写一个 revision、重放不涨、
坏名字 422 且不烧版本、旧 revision 409、重开同一个库读回、`restore` 还原；**参考线不得漏进成片**——
`title` 与 `off` 两种状态各导一次，0.2/1.0/1.8 秒逐通道取样完全相同、都是 2.000 秒。界面在真实引擎
（1.43.0）上三态循环 r1→r2→r3，角标显示引擎数字换算出的「动作区 67×38 px」「字幕区 96×54 px」。
如实记一条未覆盖：合成 `keydown` 没触发 Ctrl+Z（快捷键监听器不接受 `isTrusted=false` 的事件），
撤销这条路径由检查里的 `restore` 断言覆盖，不是由浏览器点击覆盖。

1.43.0 发布验收：冻结引擎 `--verify` 通过，重新打包后包内 `/v1/info` 报 `app_version=1.43.0`、`frozen=true`、
`render_ready=true`，`/v1/capabilities` 报 `safe_area_guides=true` 且 `safe_area_insets={action:0.035,title:0.05}`
（与契约里的 `SAFE_AREA_INSETS` 逐位相同）、`app_version` 与 `/v1/info` 一致、`delivery_recipes` 仍在。包内事务实测：
写 `title` 恰到一个 revision（r1→r2）、同 `request_id` 重放返回自己的回执、坏名字 `titles` 422 且既不改动参考线
也不烧版本。成片实测：`title` 与 `off` 两种状态各导一次，0.2/1.0/1.8 秒三处取样都是 (254,0,1) 且完全相同、
时长都是 2.000 秒——参考线在发布物里同样只是界面。ASAR 版本 1.43.0，渲染层与本地构建逐字节一致，
`safe_area_insets` / `safe-guide` / `safe-caption` / `动作区` / `字幕区` / `安全框 · ` 字节级存在。
便携版 132,499,882 字节 SHA256 `1a425908…8177`，安装版 132,660,606 字节 `3215f6b9…0668`，根目录
`AgentCut.exe` 与便携版逐字节相同。`win-unpacked/AgentCut.exe` 原生截图 1480×900 里标题栏右上角清楚写着
「引擎在线 v1.43.0」、监视器工具条写着「安全框 · 关」，PNG MD5 `9ae34bd9…`（与 1.42 的 `c980d6b8…`、
1.39–1.41 三张相同的 `31270d1b…` 都不同）；`CloseMainWindow` 后 `Get-Process` 查不到残留。未签名。


1.42.0 发布验收：冻结引擎 `--verify --measure 2` 通过（裸启动 4 次 min 582 ms / median 594 ms / max 676 ms，staged
97 个文件）。包内 `/v1/capabilities` 报 `app_version=1.42.0` 且与 `/v1/info` 同一个值、`project_schema_version=12`、
`delivery_recipes` 与两条 recipe 命令都在；`dry_run` 返回候选工程而库里 revision 不动，一次保存 r1→r2，同
`request_id` 重放不涨也不复制方案，未知预设 422 `INVALID_RECIPE` 点名 `not-a-preset` 且不烧版本；包内 MCP
`timeline_edit` 的 inputSchema 里确实有 `recipe.set`（本版没新增工具），调用它写入第二个方案 r2→r3。把库里读回的
`items` 原样发给 `/renders/batch`，两条都出货：**1920×1080 / 6.000 秒** 与 **1080×1920 / 6.000 秒**；`restore` 回到
有方案之前留下空列表与新 revision。ASAR 内 `交付方案` / `存为方案` / `recipe.set` 字节级存在，渲染层与本地构建
逐字节一致、ASAR 版本 1.42.0。便携版 132,498,515 字节 SHA256 `f33c7f6d…e2051`，安装版 132,659,233 字节
`6e0b4a23…b51c`，根目录 `AgentCut.exe` 与便携版逐字节相同。

同一版补掉了 1.40/1.41 记录里那条证据边界：capabilities 新增 `app_version`、标题栏徽章显示「引擎在线 v1.42.0」、
`self_check` 断言它等于 `APP_VERSION`（缺字段直接 KeyError）。于是 1.42 的原生截图 MD5 从连续三版相同的
`31270d1b…` 变成 `c980d6b8…`，截图第一次真正具备版本区分力。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.42-交付记录.md`。

## 1.44.0 派生缓存总配额（2026-10-07）

代理早就有 4 GiB 的配额与最久未用淘汰，但缩略图瓦片和波形峰值没有：它们按内容哈希一份份写进缓存目录，
从此没人管。用得越久、素材越多，磁盘上攒的越是可重建的垃圾——而这正是「本地剪辑软件」最容易踩的用户痛点。

- 一份账算整个缓存目录（`GET /v1/media/cache`），预算 `AGENTCUT_CACHE_BYTES`（缺省 6 GiB），
  淘汰单位是一个内容哈希的整个目录（半删会留下说谎的清单），顺序最久未用先走，`keep` 可保护，
  `dry_run` 预演同一份计划而不删一字节。
- **已登记素材根目录里的东西永不作为候选**：缓存目录被配到素材根内部时（本机测试就是这么写的，第一版
  因此一个字节都没删——保护规则当场生效被抓出来），原片不会被当成缓存删掉。
- `cache_path` 在文件缺失时重跑 `build_cache`：这让「派生副本可重建」从一句注释变成被断言的行为。
- **预算在生成时自动执行**：`_build_cache` 写完清单后马上按预算收敛（保护刚生成的那一项）。第一版只做了
  「可以问它要配额」，那不算配额——磁盘不会等人记得点按钮。单条派生本身超过预算时停在「只剩刚生成这一项」，
  不为凑数字牺牲刚做的东西，也不拒绝生成。
- 不新增工程状态、不改 schema、不新增 MCP 工具；capabilities 增 `features.cache_pruning`（依赖媒体）。

验收 `tests/cache_check.py`：清单与磁盘实测逐字节相等（135,322 字节 / 3 项）；`dry_run` 计划释放 65,313 字节
而磁盘分毫未动；预算压线时恰好删掉最久未用那一项、剩余 ≤ 预算；被删的缩略图再请求一次 → 200、584 字节回包、
磁盘重新长出 65,313 字节；`keep` 全覆盖时预算 0 也不删；缓存在素材根内时预算 0 也不删。
门禁：`ruff check` / `ruff format --check` 全绿、`tests/suite_check.py` **42 项**全绿、`npm run typecheck` 全绿。

1.44.0 发布验收：冻结引擎 `--verify` 通过（`mcp` 模式 3 秒内存活），重新打包后包内 `/v1/info` 报
`app_version=1.44.0`、`frozen=true`。两份真实素材导入后 `GET /v1/media/cache` 报 130,604 字节 / 2 项，
与磁盘实测逐字节相等；`dry_run` 预演同一份淘汰计划而磁盘一字节未动；按最久未用那一项的大小压预算，
真删释放 65,306 字节、剩 65,298 字节，被删的正是清单末位那一项（不是最小项——淘汰看新旧不看大小）；
再请求那张被删的缩略图 → 200、584 字节的图，磁盘重新长出 65,306 字节。把缓存目录故意配进已登记素材根
（`--cache-dir <media_root>/cache`）时，预算 0 也**一字节不删**，原片不会被当成缓存清掉。ASAR 版本 1.44.0，
渲染层与本地构建逐字节一致，`清理缓存` / `cachePrune` / `cacheInventory` 字节级存在；根目录 `AgentCut.exe`
与便携版逐字节相同（132,502,651 字节 SHA256 `46b0f825…cc7f`，安装版 132,663,363 字节 `dd0ff8d8…950e6`）。
包内另起一个 `AGENTCUT_CACHE_BYTES=60000` 的实例连做三次导入，缓存只剩最新那一项（65,314 字节）——
自动收敛在发布物里同样生效（一条 2 秒视频的瓦片本身就超过 60,000 预算，引擎不为凑数字删掉刚做的东西）。
界面这一版在 `127.0.0.1:5178` 连 `127.0.0.1:8794` 真实点击验收：工具条显示「缓存 0.1 MB / 1 项」，
点「清理缓存」→ 提示「派生缓存已清空 · 释放 0.1 MB（1 项缩略图 / 波形 / 代理）· 原片与工程未改动」，
标签与按钮随即消失，HTTP 清单与磁盘同时归零。原生截图 MD5 与 1.43 不同（标题栏 `引擎在线 v1.44.0`）。

## 1.45.0 主体跟随重构图（2026-10-07）

「跟踪主体」已经知道主体在哪，`x`/`y`/`scale` 关键帧已经能移动画面，缺的是中间那步换算：人要手工
把几十个点的中心对齐到画面正中。这一步在剪映与达芬奇里是一个按钮，在 AgentCut 里过去只能一个键一个键点。

- `reframe.plan()` 读 `mask_x`/`mask_y` 曲线，写 `x`/`y`/`scale` 三条 `keyframes.replace`，一个批次一个 revision。
- 规律是**量出来的**：合成器把层以画面中心为锚缩放后叠在 `(W-w)/2 + W·x`，于是主体落点
  `0.5 + scale·(cx-0.5) + x`，居中需要 `x = scale·(0.5-cx)`，而盖满画面需要 `scale ≥ 1/(1-2|0.5-cx|)`。
  第一版按 `x = 0.5-cx` 写（漏了 `scale ×`），成片量出主体在 0.06 / 0.13 / 0.94——比不跟随还偏，
  是像素把它打回来的，不是 review。
- `max_scale` 压太低时跟不到，就如实报告：`clamped_points` + 一句「跟到这里就停了」，界面原样显示。
- MCP 多一个只读工具 `clip_reframe`；`tests/self_check.py` 的精确工具集合断言当场变红，逼着文档与断言一起改。
- 能力接口加 `subject_reframe`；不新增工程状态、不改 schema。

验收 `tests/reframe_check.py`：解算逐字段（x=±1.1667 / scale=3.333 / 无夹住；1.5 倍上限时 2/3 个点夹住并警告）；
九组拒绝各有名字；事务层 plan/dry-run 不写库、一次 apply 一个 revision、重放不涨、旧 revision 409、
`restore` 后不留曲线；成片层用真的在动的素材量质心——不跟随 0.18→0.82，跟随后 0.56/0.50/0.40
（平均 < 0.06 偏离中心），左上角 16×16 均值 63/63 说明放大把画面盖满了、没有黑边，时长 2.000 秒。
如实一条：tracked 点上精确，**中间段是遮罩路径自身的线性近似**，所以跟随时长镜头时主体会在两个点之间轻微
漂过几个百分点；这不是缺陷，但也不是「像素级锁死」，提示与文档都这么写。

1.45.0 发布验收：冻结引擎 `--verify` 通过、重新打包后包内报 `app_version=1.45.0` / `subject_reframe=true`；
plan 不写库、一次 apply 一个 revision、重放返回自己的回执；**包内成片量出主体在 0.56 / 0.50 / 0.40**
（不跟随是 0.18 → 0.82），左上角 16×16 均值 63/63 与灰底一致（放大真的盖满了画面、没有黑边）；
包内 MCP `clip_reframe` 带 `readOnlyHint=true`、`max_scale` 在 inputSchema 里，工具侧强制关掉 `apply`，
1.5 倍上限时回「2 个点夹住」并带警告而库里 revision 不动。ASAR 版本 1.45.0、渲染层与本地构建逐字节一致、
`主体跟随重构图` / `reframe` / `followed_points` 字节级存在。便携版 132,508,438 字节 SHA256
`e874212f…f604`，安装版 132,669,148 字节 `478508f3…9021a`，根目录 `AgentCut.exe` 与便携版逐字节相同。
原生截图 MD5 `c0a5f17d…`（标题栏 `引擎在线 v1.45.0`，与 1.42–1.44 三张各不相同）。完整记录见
`C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.45-交付记录.md`。

开发期被像素打回来的一次：第一版按 `x = 0.5 − cx` 反解，成片量出 0.06 / 0.13 / 0.94，比不跟随还偏——
合成器的真实规律是 `落点 = 0.5 + scale·(cx−0.5) + x`，居中要 `x = scale·(0.5−cx)`。这条现在写在
`reframe.py` 的注释里，并被 `tests/reframe_check.py` 的成片断言钉住。

## 1.46.0 调色节点图（2026-10-07）

调色链是一串节点，界面却是一个带 ↑/↓ 的纵向列表：看不出信号流向，也看不出并联的支路从哪儿分出去、
在哪儿合回来——而这正是达芬奇与 AE 的节点图在解决的问题。本版把链子画成图，但**不新增任何状态**：
`clip.color.grade` 仍是唯一权威，Agent 写的顺序和人拖出来的顺序是同一件事。

- 唯一的描述与顺序算术抽到 `desktop/src/gradeGraph.ts`（`cardsFor` / `dropIndex` / `moveWithin`），
  组件只渲染；这样这三条规则可以被 esbuild + Node 的断言直接钉住，而不是只能在浏览器里看。
- 拖放落点夹到 `[0, count-1]`（拖出左右边缘落在首/末位），`moveWithin` 保证纯移动：不改原数组、
  长度不变、元素不变多不少、原地放等于没动——避免「拖一下丢节点」这类最容易发生又最难发现的错。
- 卡片上保留启用开关、↑/↓ 与删除，全部走同一条 `clip.color` 写路径。

验收：`tests/desktop_graph_check.ts` 钉住卡片描述（`强度 50% · 滤色`、`3 支`、支路停用态）、落点夹取与纯移动；
浏览器真实 `DragEvent` 拖放 r1→r2，卡片变成 并联 → 色彩空间 → 白平衡，库里读回同样顺序且每个节点内容一字未丢。

1.46.0 发布验收：冻结引擎 `--verify` 通过、重新打包后包内 `/v1/info` 报 `app_version=1.46.0`、`frozen=true`，
`/v1/capabilities` 仍报 `grade_nodes` / `grade_parallel_branches` 为真、schema v12（本版没动契约）。
包内实测链子的权威没变：写入三节点链（白平衡 50% 滤色 + 3 支并联含一支停用 + srgb→rec709）后，
用与拖动等价的**一条 `clip.grade`** 换序 → 恰到一个 revision、顺序变成 并联 → 色彩空间 → 白平衡、
**每个节点的内容一字未丢**（仍是 3 支、第 2 支仍 `enabled=false`、白平衡仍 50%/screen、色彩空间仍 srgb→rec709）；
把链子塞到超过 8 个节点仍被规则拒绝（422）而不是被截断，且拒绝不烧版本。ASAR 版本 1.46.0、渲染层与本地
构建逐字节一致，`grade-graph` / `gg-card` / `gg-lane` / `gg-io` / `输入` / `输出` / `拖动可改顺序` / `调色节点`
字节级存在。便携版 132,509,177 字节 SHA256 `32b05be7…edd7`，安装版 132,669,880 字节 `c27b2663…eafe`，
根目录 `AgentCut.exe` 与便携版逐字节相同；原生截图 MD5 `2aba08b8…`（标题栏 `引擎在线 v1.46.0`）。
开发期一条被纠正的期望：我原本断言 ASAR 里有模块名 `gradeGraph`，打包器会改标识符名，这个断言本身不成立——
换成必须在产物里存活的 class 名与中文文案，才是能证伪的检查。

## 1.47.0 主体跟随重构图改成按渲染时钟采样（修复 1.45 两处成片级缺陷）

1.45 的解算器把遮罩关键帧一一对齐后直接写平移/缩放关键帧。两处都不成立，都是取中间点的像素实测出来的：

- **两套时钟**：工程里的遮罩关键帧在片段绝对动画时钟上，而 `keyframes.replace` 收片段内 tick、
  reducer 再加回偏移。读绝对、写绝对，等于加两次偏移——任何带偏移的片段，跟随曲线整体晚一个偏移落地。
  `clip.split` 正是产生偏移的操作，「剪一刀再自动重构图」这个竖屏出货最常见的手势原本必然错位。
- **关键帧太稀**：把偏离中心 `d` 的主体居中需要的放大是 `1/(1−2d)`，双曲的。两个关键帧之间拉直线会在
  中段过冲：只有两个关键帧的尾巴在第 1.5 秒把主体甩到画面宽度 0.278 处（偏离 0.22 个画面宽）。

现在每个跟随点都用渲染用的 `animation.sample()` 读该刻遮罩中心真值，再贪心地挑「这条直线代价最大」的
区段取中点补点，直到进容差或用完预算；步进（`hold`）路径保持阶梯不被抹平；只动画一条轴、两轴插值不同
也不再被假拒绝（那是手工配对才有的约束）。

- `ReframeRequest.tolerance`（可选，`0 < x ≤ 0.25`，默认 `contracts.REFRAME_TOLERANCE = 0.01` 画面宽）
  是 Agent 的质量/关键帧权衡，MCP `clip_reframe` 的 schema 从契约自动生成因此同步出现。
- **关键帧预算**：真实跟踪每帧写一条遮罩关键帧，20 秒就是 1200 条，再叠三条同密度的跟随曲线会撑破
  `Clip.keyframes` 的 2000 条上限——计划说可以，写入被拒。种子点先按 `min(48, (上限 − 已有) // 3)`
  均匀抽样（上限从契约字段元数据里读，不另抄一份），再在预算内补点；`keyframes_dropped` /
  `keyframe_budget` 报出省了多少，装不下时警告说清「按均匀采样只跟到多宽」。
- 新增数字 `keyframes_added`、`tolerance`、`worst_offset`（按写出来的曲线重新采样量出的最大偏离，
  不是推测值），界面提示改口径报这个实测数；`reframe.ticks` 与命令的 `at_ticks` 都是片段内 tick。
- 顺带修掉发布入口自身的缺陷：`scripts/build_engine.py` 在 cp936 控制台打印仓库路径（含中文）时抛
  `UnicodeEncodeError`，把文档里那条 `uv run python scripts/build_engine.py --verify` 门槛整个打断。
  现在它自己把 stdout/stderr 重配成 UTF-8（errors=replace），不带 `PYTHONUTF8` 直接跑也能过。
- 不新增工程状态、不改 schema（仍 v12）；一个批次一个 revision；`APP_VERSION` 1.47.0 与
  `desktop/package.json` 同值。

验收（`tests/reframe_check.py`）：解算层——横扫 3 个跟好的点补到 13 个关键帧、最大偏离 0.0082 画面宽，
容差放宽到 0.2 只留 5 个点、代价 0.079（权衡被当场测出方向）；带 `T//3` 偏移的片段写出的片段内 tick
与不偏移时逐点同值；中段剪开的尾巴带上切口处已有的取景（head x=0.269 @ 1.538x）； beyond 路径末端的
片段按最后保持的中心跟；600 帧（1200 条关键帧）压到 48 点、950 帧（1900 条）压到 33 点，合并结果用
`Clip` 模型当场验过装得下；拒绝仍有名字（无遮罩 / 路径遮罩 / 反相遮罩 / 遮罩没动过 / 上限超 4 倍 /
片段不存在）；事务层 plan 与 dry-run 不写库、一次 apply 一个 revision、重放不涨、旧 revision 409、
restore 后不留平移缩放。成片层——全片取 9 个点，跟随后主体 0.46~0.50（最大偏离 0.043 画面宽，含探测
与取整噪声），不跟随 0.18→0.82；剪过的尾巴取 6 个点 0.50→0.46，同窗口不跟随 0.50→0.84；左上角 16×16
均值 63/63 与灰底一致（放大真的盖满画面、没有黑边），时长 2.000 秒；并把引擎自己声称的 `worst_offset`
与像素量出的最大值对齐断言，声称值不能比成片好。

1.47.0 发布验收：冻结引擎 `--verify` **在不设 `PYTHONUTF8` 的控制台上**也通过（`app_version=1.47.0`、
`frozen=true`、裸启动冷启动 609 ms、`mcp` 模式 3 秒存活、`tools`/`--help` 退出 0），随后 `npm run dist`
重新打包。包内验收 `package_check_147.py`（实例 `e46afca13f62`）驱动的是**发布出去的那个引擎**：全片 9 个
探测点跟随后主体 0.49/0.49/0.50/0.50…0.46（最大偏离 0.043 画面宽，引擎声称 0.008233，两者按余量对齐断言），
不跟随 0.18→0.82；`clip.split` 出来的尾巴（偏移 70560000）6 个点 0.50→0.46，同窗口不跟随 0.50→0.84，
且写入的跟随 tick 落在片段窗口内、包含遮罩 tick；`tolerance` 超过 0.25 被契约拒成 422；MCP `clip_reframe`
仍是只读（`readOnlyHint`）、schema 里带 `tolerance`、调用后 revision 不动；`app.asar` 里能读到新的跟随
提示文案（「个关键点」「画面宽」）与 `clips/`…`/reframe` 线路，同时如实断言 `tolerance` **不在**壳层里
（那是 Agent 的旋钮，人的按钮保持默认）。`asar_compare.py`：5 个渲染/壳文件逐字节一致、包内引擎与验证过的
那个一致、ASAR 版本 1.47.0。便携版 132,512,812 字节 SHA256 `3150e301…6bff9193`，安装版 132,673,523 字节
`3ba1b0c7…e049849d`，根目录 `AgentCut.exe` 与便携版逐字节相同；原生截图 MD5
`3766fb95b8687e3d236b270c6657fbe6`（标题栏「引擎在线 v1.47.0」）。套件 44/44（含新收进来的壳层门禁
`tests/desktop_ts_check.py`，它自己用故意失败的探针验过会红），`npm run typecheck` 干净。

界面层（真实浏览器加载构建产物 + 真引擎）：选中 `clip.split` 出来的尾巴点 `主体跟随重构图`，提示写的是
「按跟好的路径采样 7 个关键点（引擎补了 5 个） · 最多放大 3.33 倍 · 主体偏离画面中心最多 0.8% 画面宽」，
报的就是引擎实测口径；从库里读回该片段 7 条跟随 tick 全部落在 `[offset, offset+duration]` 窗口内、
包含窗口内的遮罩 tick，且片段内 tick 无负值（遮罩那条窗口外的 tick 被正确忽略）。撤销再跟随各恰好一个
revision（r2→r3→r4）。

## 1.48.0 缩放与淡入淡出同片段不再崩掉渲染（成片级缺陷修复）

给 1.47 的教训做的门禁：跟随曲线的缺陷之所以能出货，是因为像素检查只在关键帧时刻取样。新写的
`tests/curvefidelity_check.py` 把探测点放到**段内**，并与引擎自己的采样器逐点比对位置 / 面积 / 电平。
它第一次跑就抓到渲染层的硬崩溃——一条片段同时带 `scale` 与 `opacity` 关键帧时 FFmpeg 直接死掉
（0xC0000005 / 0xC0000409，stderr 空），而这只是「放大 + 淡入」这个最普通的动画组合。

- 定位方式是逐属性二分：只 x / 只缩放 / 只透明度各自正常，x+缩放、x+透明度正常，缩放+透明度必崩。
  根因是滤镜顺序：`geq` 按喂给它的画面尺寸分配缓冲，而它被写在 `scale=…:eval=frame` 之后，尺寸每帧一变
  就越界。
- 修法：遮罩 alpha 与不透明度合成**一次**逐像素写入，放在任何会改变尺寸的滤镜之前。乘法可交换，
  `rotate` 的填充本就是透明黑，所以语义不变，还少了一次逐像素遍历。
- 不新增状态、不改 schema（仍 v12）、不改契约；`APP_VERSION` 1.48.0。

验收：`tests/curvefidelity_check.py` 13 个段内探测点一致（ease / bezier / linear 各有覆盖），上层片段
按淡入淡出曲线与下层红轨混合（期望值由权威采样算出，不是假定固定 50%）；独立探针另测得静态 50% 上层盖在
红轨上导出 126/31/31，正是 0.5 混合应有值（丢掉 alpha 会是 64/64/64）。门禁自身被反向验证过：把
`render.py` 的修复 `git stash` 撤掉后该检查以 `FFMPEG_FAILED` 失败。套件 45/45（其余 44 项含遮罩、转场、
调色等真实导出，均未因顺序改动而变红）。

1.48.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.48.0`、`frozen=true`、`mcp` 存活、
`tools`/`--help` 退出 0）后 `npm run dist` 重新打包。包内验收 `package_check_148.py`（实例
`ca9ba3cb8803`）跑的就是**曾经崩掉的那个组合**：一条片段同时带 x / scale / opacity 三套关键帧
（ease、bezier、linear 三种插值）盖在另一条轨道上，导出成功；四个时刻逐点比对像素与引擎权威采样，
全部在 3 个色阶以内——白块 251/244/246 对 (253,249,249)、灰底 66/59/61 对 (67,62,62)、
237/188/188 对 (239,191,191)、95/46/46 对 (96,48,48)、229/157/155 对 (231,158,158)、
110/38/39 对 (113,40,40)、253/249/250 对 (254,252,252)；段内位置 0.586 对权威 0.575（bezier 段）、
0.472 对 0.472（linear 段）。缩放小于 1 的时刻不再采“灰底”，因为那时图层本就不铺满画面——这是正确
行为，检查里写明了原因。`asar_compare.py`：5 个渲染/壳文件逐字节一致、包内引擎与验证过的一致、ASAR
版本 1.48.0。便携版 132,513,551 字节 SHA256 `4f072e68…3c740e7a`，安装版 132,674,277 字节
`56a92458…4388850e`，根目录 `AgentCut.exe` 与便携版逐字节相同；原生截图 MD5
`4e3059c922f514b7ae77686befcb81a1`（标题栏「引擎在线 v1.48.0」）。套件 45/45。

## 1.49.0 渲染失败说清原因（交付缺陷：错误信息本身没用）

1.48 那次定位崩溃，最卡人的不是崩溃本身，而是任务里只有 `FFmpeg 退出码 3221225477：`——冒号后面空的，
因为进程死得连一行错误都没写出来。人对着这句话没法动手，Agent 读 `/v1/jobs/{id}` 也只有一个数字。

- `jobs.describe_exit(return_code, stderr)`：Windows 异常码给出名字（0xC0000005 访问越界、
  0xC00000FD 栈溢出、0xC0000409 运行时检查中止），保留 FFmpeg **末尾** 3000 字符（真正的错误在结尾，
  开头全是编解码器清单），什么都没留下时明说「没有留下任何错误输出」。
- 任务 `message` 换成这句话；`error_code` 仍是 `FFMPEG_FAILED`，契约、schema（v12）、端点都不变。
- `APP_VERSION` 1.49.0。

验收（`tests/renderfail_check.py`）：纯函数逐码断言（三种异常码都认得、长日志只留尾部且不许出现
「退出码 23：」后面空一截、只有空白输出时给出「没有留下任何错误输出」）；再真的删掉素材跑一次导出，
读回的任务消息必须是可读的一句。套件 46/46。

1.49.0 发布验收：冻结引擎 `--verify` 通过（`app_version=1.49.0`、`frozen=true`、`mcp` 存活）后
`npm run dist` 重新打包。包内验收 `package_check_149.py`（实例 `30a9d4e83027`）：删掉素材后包内引擎的
失败消息为 `FFmpeg 退出码 4294967294：[in#0 …] Error opening input: No such file or directory …`，
断言了「有 FFmpeg、有退出码、冒号后不空、且带真实原因」。`asar_compare.py`：5 个渲染/壳文件逐字节一致、
包内引擎与验证过的一致、ASAR 版本 1.49.0。便携版 132,513,401 字节 SHA256 `026c9082…7c39ede1`，
安装版 132,674,119 字节 `4429bb90…50412348`，根目录 `AgentCut.exe` 与便携版逐字节相同；原生截图 MD5
`8cef3d8901405feb3ca1eb78b6cd4bfa`（标题栏「引擎在线 v1.49.0」）。

## 1.49 之后补的门禁：调色链路逐电平核对（不改引擎，改的是「能不能发现」）

1.47/1.48 的教训是同一句话：只在关键帧时刻取样，就看不见关键帧之间的世界。把同样的方法用到调色上，
成本几乎为零——一张 256 级灰度斜坡 + 8 个纯色块，一次生成就提供 792 个比较点。

新增 `tests/gradelevels_check.py`：

- 把 `grade_filter(color)` 编译出的 `lutrgb` 表达式直接作用在**未经编码器**的 RGB 裸数据上，与
  `grade_tables(color)` 给浏览器的 256 项表逐电平比对。实测最大偏差 **1.00 级**（就是 8 bit 量化本身）。
  不经编码器是有意的：先前把真实导出与表对比时，x264 在平滑渐变上自己就挪动 4~5 级，那测的是编解码器，
  不是调色；改成差分后仍有 3~5 级的抖动，换成裸数据路径后归零。
- 链子故意让三条通道各走不同方向：色轮 lift/gamma/gain 不等、红通道 5 点曲线、绿通道 3 点曲线、
  白平衡、一条 mix=0.6 且 blend=screen 的 RGB 曲线、再加 srgb→rec709 转换节点。
- 另跑一次**真实导出**，只证明这一级确实在成片里：红通道 64–192 段平均位移 52.6，表算出来 53.2。
- 反向断言：同一批比较对着「恒等表」算，必须有 300 个以上点不一致（实测 792 个里最大偏差 75 级），
  否则这个门禁就是在量空气。

结论是**没有发现调色缺陷**——每通道一张表的权威在 256 个电平上都成立。这条的价值在于以后它不成立时
会当场变红。套件 47/47，引擎与发布包未变（仍是 1.49.0），因此本轮不重新打包。

同一套方法接着用到变速曲线上：`tests/speedramp_check.py` 原本只在 0.5/1.0/2.0/3.0/3.9 五个点核对
U 形曲线，全在段端附近。现在整段扫 39 个点（每 0.1 秒一个）并与权威 `expected_source` 逐点比，
实测最大偏差 4.6 级（在 2.2 秒处，段中而非段端），断言上限 8 级。曲线编译没有发现缺陷，但这条
扫描以后会在段中错位出现时当场变红。套件 47/47。

## 1.49 之后补的门禁（二）：音量曲线逐窗核对，变速片段按时间线时钟

`gain` 关键帧到 FFmpeg 是 `volume='…':eval=frame`，与画面用的是同一个表达式编译器。以前的音频检查量的是
闪避总量、响度目标、音高，几乎都在整秒上，没人扫过曲线本身。新增 `tests/audiocurve_check.py`：440 Hz
等幅单音走「linear→ease→bezier→hold」四段曲线，导出后每 0.1 秒取一次 RMS 与 `animation.sample` 比，
100% 与 200% 变速各扫 39 个窗。

过程里被自己的夹具骗了两次，都记下来：

- **轨道音量不进入比值**。控制渲染与曲线渲染都乘同一条轨道音量，它在相除时抵消；把它写进期望值会让
  每个窗都差 20%。发现这点靠的是「测量值系统性比期望高」这个形状，而不是把容差放大。
- **夹具不能对引擎撒谎**。`-shortest` 把单音文件截到画面长度，而我手写的 verified 记录声称 8 秒——
  于是 200% 片段读到一半没音源，2.1 秒后静音，看起来像引擎的大缺陷。真相是引擎行为正确：reducer 会拒绝
  「片段超出登记的素材时长」，而真实导入产生的记录不会撒谎。修法是把两条流都做成 8 秒，并在夹具里
  用 ffprobe 断言文件确实有那么长。

容差最终写成「0.02 + 半个窗 × 局部斜率」：平段必须 0.02 内贴合，只有陡坡才允许摊开——这既不是随手放大
常数，也不是把测量噪声合法化。实测 39 窗最差为允许值的 0.18 倍（100%）与 0.09 倍（200%），且 200% 情形
下曲线确实跟着**时间线**走（用整条曲线做时移搜索，最佳位移 −0.005 秒，即半个窗以内）。反向断言：对着
「没有曲线」比，36 个窗不一致。

结论：音量曲线没有发现缺陷，但从此它在任何一个窗上跑偏都会当场变红。套件 48/48。

## 1.50.0 自由路径遮罩会跟着走了（schema v13）

1.49 之前路径遮罩是「一片段一张 PNG」：轮廓画在哪就裁在哪，一旦要动画，契约只能整笔拒绝。而剪映、
AE 的套索/钢笔遮罩最基本的一种动法就是**跟着跟好的轨迹搬动**——遮罩跟踪已经能给出这条轨迹，主体跟随
重构图也已经在读它，唯独导出把它当静态。本轮补这一半，并如实留下另一半（顶点与形状动画）。

- **v13**：`SCHEMA_VERSION` 12→13，每条路径**在批次交回结果前**贴合轮廓（`masks.fit_box`，包围盒含
  贝塞尔控制柄鼓出的部分，取自 `_segments` 的摊平轮廓而不是顶点表），旧工程在 `projects._fitted`
  读取时补算一次；已提交的历史快照不改写。贴合只写一处——`apply_commands` 末尾遍历主时间线、正在
  编辑的序列与所有子序列的片段统一重算 box，因为 `clip.add`/`clip.insert`/`clip.overwrite`/`clips.add`
  带的是整条片段，逐命令补会让同一条轮廓按进入方式落在两个位置。这条不是假想：包内验收首轮就把
  它抓了出来（首版只补 `clip.mask`，经 `clip.add` 进来的遮罩存的还是形状默认 box），现在
  `pathmask_check` 断言两条入口给出完全相同的 box，把那个遍历关掉检查立刻变红（突变验证过）。
  贴合是恒等变换，所以旧素材的画格逐点不变——这条也不是靠推理收下的，`pathmask_check` 里直接比了
  同一轮廓 fit 前/fit 后的成片像素。
- **规则只有一处**：`Clip.mask_animation_problem` 允许路径的 `mask_x/mask_y`，拒绝 `mask_width/
  mask_height` 并说明「能搬动、还不能变形」。reducer、能力接口与界面属性下拉（`maskAnimFields`）都
  从这里派生，不在客户端另写判定。路径遮罩的 box 既然恒等于轮廓，Inspector 就不摆「中心 X/Y」两行
  （写了也会被重算掉）：移动轮廓请在画面里拖顶点，随时间移动交给「跟踪主体」或曲线编辑器里给
  「遮罩中心 X/Y」双击加关键帧。
- **导出**：轮廓按 `unit_path` 烧成一张 PNG（羽化按 `box/patch` 折算，并留 3σ 边距，免得羽化斜坡被
  轮廓自身包围盒切掉），再用 `overlay=x='plane*(curve)':y='…':eval=frame` 在中性底板上逐帧搬动。
  选 overlay 而不是逐帧 scale 是 1.48 测出来的：`scale=…:eval=frame` 之后接 `geq` 会让进程不留一行
  stderr 直接崩，而 overlay 的输出尺寸恒定。反转路径的底板取白，圈外因此照旧保留。
- **跟踪**：`POST /clips/{id}/track` 对路径开放，但只跟平移——`estimate_scale` 被强制关掉，响应的
  `scale_estimated` 如实为 `false`；`clip.mask_track` 只在拿到尺寸点时才写尺寸曲线，所以这条链不会
  产出渲染不了的曲线。

验收：`tests/pathmask_check.py` 新增媒体段——320×180、上红下绿，轮廓画在左半，`mask_x` 从画好位置
线性搬到 0.75，(250,60) 在 0.05 秒仍是绿、0.95 秒已是红，(40,60) 反过来；曲线不动时取到的画面与静态
遮罩逐点一致。把 overlay 的 x/y 钉死成存储中心（等价于撤掉修复的突变）后，这条检查立刻在 0.95 秒
断言上变红，证明它抓的是真行为。`maskanim_check` 断言位置曲线通过、尺寸曲线被 `INVALID_MASK` 点名；
`reframe_check` 断言路径遮罩现在能被跟随，其余拒绝照旧逐条有名；`tracking_check` 断言包内只写
`{mask_x, mask_y}` 且响应 `scale_estimated=false`；`pathmask_check` 另断言 `clip.add` 带进来的整条
片段与 `clip.mask` 就地改的遮罩得到**同一个** box。

界面那半边另有一处先量过：编辑向导不重解曲线，而是从引擎下发曲线正在驱动的那份动画上读回当前播放头
的值（`getComputedStyle(el).getPropertyValue("--mask-x")`）再平移 SVG。这个读法在真实 Chromium 里单独
验过——一条 0.25→0.75 的线性动画在 0/100/250/500/750/900/1000 ms 读回 0.25/0.3/0.375/0.5/0.625/0.7/
0.75，七个点与期望完全一致，且动画覆盖元素自身的内联值。向导因此跟的是预览画面同一份插值，而不是
第二套实现；`tsc --noEmit` 与六个壳层检查一并跑过。

仍未完成：路径遮罩的顶点/形状动画（需逐帧重栅格化）、路径遮罩的尺寸动画、多目标与长时遮挡续跟、
旋转估计。

## 1.51.0 画面里拖遮罩就是打关键帧（2026-10-07）

1.50 把「遮罩能按曲线动」接通了，但画面向导在**有曲线时整块隐藏**：跟踪过的遮罩看得见、拖不动，只能回
Inspector 填数字；而 Inspector 早就按「该属性有曲线就写关键帧」在做，同一个动作两处不一致。这一版把画面
这条路接通，并且把语义按形状分开。

- 向导在有曲线时照常出现，仍按播放头平移（读引擎曲线正在驱动的那份动画值，不重解第二条曲线）。
- `store.commitMaskEdit`：一笔提交。矩形/椭圆里被拖动改变、且**已有曲线**的属性写当前播放头的
  `keyframe.set`，其余属性写 `clip.mask`；路径遮罩的 box 是从顶点算出的派生量，拖动只写轮廓，绝不把中心
  曲线钉在此刻——否则拖一个顶点就等于让遮罩脱离轨迹。
- 引擎侧一行未改（`SCHEMA_VERSION` 仍 13），因为 `keyframe.set` + `clip.mask` 混在一条命令里是契约本来就
  支持的原子批次；这正是「一个行为只有一处权威实现」的落点：判定在客户端只做「哪些属性有曲线」这一件读
  状态的事，写语义仍由 reducer 决定。

验收（真实构建产物 + 包内引擎，深链驱动）：拖框 revision 1→2、新增两条播放头处的位置关键帧
（`at_ticks=2352000`，值 0.6/0.6），原有 0 秒/2 秒端点不动；拖路径顶点 revision 2→3、顶点与贴合盒跟着改，
但关键帧集合仍是原来 4 条；有曲线时 `svg.mask-guide`/`.mask-hit`/4 个角柄实测存在。`tsc --noEmit`、
6 个壳层检查、套件 48/48 全过。

仍未完成（截至 1.51）：路径遮罩的顶点/形状动画、路径遮罩的尺寸动画、多目标与长时遮挡续跟、旋转估计。


## 1.52.0 画面向导跟着曲线的尺寸一起缩放（2026-10-07）

1.51 把「拖动能写关键帧」接通了，但向导只跟着曲线平移：宽度打了关键帧时画面上的框还是基准宽度，
用户抓的角柄不是他看到的遮罩边缘——这是「所见即所得」的一半，另一半不能留。

- 变换写成 `translate(T) scale(S)`：`S = 动画尺寸 / 基准尺寸`，`T = cx_now − S·cx_base − 0.5 + 0.5·S`。
  推导是因为 CSS 的 scale 以元素中心为原点、且 transform 列表先缩放后平移；`S=1` 时式子退化回 1.51
  的纯平移，所以路径遮罩（尺寸不能打关键帧）不受影响。
- 数值全部读自引擎下发曲线正在驱动的那份动画（`--mask-x/y/w/h`），客户端不重算曲线；
  `commitMaskEdit` 里 `mask_width/mask_height` 与位置属性同一条规则：有曲线写当前播放头，没曲线写盒本身。
- 测量：真实构建产物读到动画盒 (0.206667, 0.5, 0.305, 0.406667)，内联变换
  `translate(1.1667%, 0%) scale(1.01667, 1.01667)`；把同一条式子放进 400×200 的可测量 Chromium 盒子里，
  基准框落点 left 29.667 / top 67.333 / width 122 / height 81.333，与期望**四项误差 0**。
  之所以分两处量：这台机器的无头视口把预览列压到 0 宽，页面里量不到几何，只能量式子。
- 引擎与契约一行未改；`tsc --noEmit`、6 个壳层检查、套件 48/48 全过。

仍未完成（截至 1.52）：路径遮罩的顶点/形状与尺寸动画、色域矩阵（见上一节的测量）、多目标与长时遮挡
续跟、旋转估计。

## 1.53.0 路径遮罩能整条拖动（2026-10-07）

1.50–1.52 把「遮罩会动、向导跟着动、拖动写关键帧」接通了，但路径遮罩在画面上**没有整体搬动的手柄**：
只能逐顶点拖，或回曲线编辑器填数。这一版把轮廓本身变成拖动手柄，并按 AE 的语义分两种落笔。

- 命中区用同一条 `d`（顶点仍在上层，先命中顶点就是改形状），拖动预览走引擎的 `maskPreview`。
- 有中心曲线 → 写播放头处的 `mask_x/mask_y` 关键帧（顶点不动，动画留在轨迹上）；没有 → 搬顶点本身，
  贴合盒跟着重算。都是一笔提交、一个 revision。
- 可动范围 `[−最小顶点, 1−最大顶点]` 是**不对称**的：首版按对称范围夹取，结果把轮廓往越界方向放行，
  契约以 `vertices[2].y ≤ 1` 退回、界面显示 `INVALID_REQUEST`。这条被真实拖动跑出来（不是推理），
  也说明「界面上能拖」不等于「引擎收得下」——夹取必须与契约同界。
- 引擎与契约未改；测量见上一段与 README 行。

仍未完成（截至 1.53）：路径遮罩的顶点/形状与尺寸动画、色域矩阵（见 1.52 那节的 FFmpeg 实测）、
多目标与长时遮挡续跟、旋转估计。

## 1.54 双击加点加在哪条边上

`MaskPicture` 的 `onDoubleClick` 一直把新顶点 `push` 到列表末尾。闭合轮廓是按顶点顺序连的，
所以在边 v1→v2 中间点一下，得到的却是 v3→v4→**新点**→v1 的折线——形状自己对折成蝴蝶结，
画面上遮罩瞬间变成另一个区域，而且引擎照单全收（顶点坐标合法，契约无从拒绝）。
现在先找**离得最近的那条边**（曲线按 24 步采样，所以量的是看到的轮廓而不是两端点的连线），
把点插在它两个端点之间，再用 de Casteljau 在该位置精确分裂这条三次贝塞尔：
左半控制点给出前一个顶点的新手柄（`t` 倍），右半给出后一个顶点的新手柄（`1−t` 倍），
中间两个控制点相对新点就是它自己的进出切线。分裂是恒等变换：包内引擎存回的结果里，相邻两顶点的柄
正好缩到原来的 `t` 与 `1−t` 且方向逐字不变，新点的进出两臂共线反向。`t` 夹在 `[0.05, 0.95]`，
否则正好点在已有顶点上时会把邻居的手柄缩成 0（一个平滑点被抹成尖角）。几何搬进
`desktop/src/maskOutline.ts`，`tests/desktop_mask_check.ts` 直接断言。

## 1.52 探过但没收口：色域矩阵节点（记测量，不记功能）

按达芬奇的色彩管理基准页试了一个 `gamut` 节点：display_p3 / Rec.709 / BT.2020 / sRGB 之间做 3×3
线性矩阵（四个空间同为 D65，不含色适应），两端各配自己的传递函数，强度在线性光里插值。引擎侧编译、
浏览器 `feColorMatrix` 阶段、Inspector 节点卡都通了，矩阵数值与公布值一致（Rec.709→P3 线性矩阵
`[0.92092 0.19879 0; 0.03717 1.08255 0; 0.01913 0.08106 1.01952]`）。

`tests/gradelevels_check.py` 的 256 级逐电平核对把它拦了下来，原因是**量化的次数**而不是数学：
矩阵把链子切成两段 `lutrgb`，FFmpeg 每一段都舍到 8 位，而闭合那张表的暗部斜率高达 12.7 阶/级，于是
导出与预览（浏览器 SVG 滤镜链全程浮点、只在链尾量化一次）在阴影里差到 6.6 阶——实测 level 4 的 R
读出 33、表给 39.41；level 5 的 B 读出 50、表给 57.65。这不是能靠放宽容差糊过去的「测量噪声」：
容差由物理推出来是这条链的底线，一旦为它放宽，整条调色链的逐电平核对就失去意义。

试过把带矩阵的链改跑 `gbrp16le`（折线按 257 倍缩放到 0..65535，两端各加一次 `format`），也试过
`gbrpf32le`。**两条都在 FFmpeg 的取整/量程上翻车，测量记在这里，别再猜：**

- `format=rgb24 → format=gbrp16le → format=rgba` 会把 1..11 级压成 0（实测恒等链读回
  `(0,0,0)…(0,0,0)`，而同一测试图不经 16 位时是 `(1,1,1)…(11,11,11)`）——插一次 planar 16 位就换了一次
  量程解释，黑场被吃掉。
- `format=gbrpf32le,lutrgb=r=val` 把第 1 级读成 255（`clip(val*2,0,1)` 读出 1/255）：`lutrgb` 在浮点平面上的
  `val` 域与 8 位不同，表达式里的 0..1 与 0..255 会串。
- 用纯色源单独测 `format=gbrp16le,lutrgb=r='clip(val*2,0,65535)'` 与矩阵都是**对的**（6→12、混合 0.5/0.5
  →53），错的是「rgb24 测试图 → planar 高位深 → 回到 8 位」这条转换路径本身。所以下一步要么把整条
  渲染链的位深与 `color_range` 标签一起管住（工程量大，且要重测所有既有调色门禁），要么先不做跨通道节点。

这份改动连同本节测量存在 git stash（消息即本节标题）。

结论：色域矩阵不进 1.52。能力接口与文档都不声明支持它，`README.md` 的待办那一行照旧。

## 1.57.0 交付格式：容器、编码与采样格式由预设一处决定（2026-10-07）

交付是这一版唯一的主角。以前「导出」只有一个答案（H.264/AAC 装进 MP4，文件名必须 `.mp4`），
`docs/architecture.md` 与 README 的边界都写着「未覆盖其它容器与编解码器」。这一版把它做成预设的事，
不是调用方的事：

- 预设表新增 `audio_codec` / `pixel_format` / `profile` 三个键，`crf`/`encoder_preset`/`audio_bitrate`
  允许为 `null`（ProRes 由 profile 决定、VP9 的 crf 必须配 `-b:v 0`、PCM 没有码率这件事）。
- 新四条：`h265-1080p`、`h265-2160p`（MP4 + `hvc1`）、`vp9-1080p-web`（WebM + Opus）、
  `prores-422hq`（MOV + 24 位 PCM + `yuv444p10le`）。
- `render.output_args(preset, sample_rate, frame_rate)` 是预设→FFmpeg 参数的唯一去处，按 codec 名分派，
  只认 `OUTPUT_CODECS`。调用方交不出任何原始参数位。
- `pixel_format` 走完整条画面链（解码段、`fit_stage`、`[vout]`），不是只写 `-pix_fmt` 的装饰。
- 文件名后缀查 `preset_container()`：`.mp4` / `.mov` / `.webm`；jobs 写文件前的同一处与
  `.part.<容器>` 临时名跟着走。
- capabilities 下发 `output_containers` 与 `features.multi_codec_delivery`；工程 schema 仍 v13，
  预设表纯增量，1.56 之前存的交付方案照读。

### 一个被抓出来的真实交付缺陷

WebM 第一次真跑就崩：FFmpeg 的进度行对 WebM/Opus 的第一拍报 `out_time_us=-6500`
（Opus 编码器前置延迟把音频轨放在零之前；`-progress pipe:1` 实测同一行还给出
`out_time=-00:00:00.006500`）。TIMEBASE 是 70,560,000，于是 `int(-0.0065 * 70560000) = -458640`，
原样存进 `RenderJob` 被 `rendered_ticks >= 0` 拒绝，worker 的兜底把任务判成 `RENDER_CRASHED`，
`finally` 之后临时文件还挂在原地。任何一次 WebM 交付都会撞上。修法：进度是遥测不是时间线的事实，
在**读它**这一处夹住（`max(0, min(duration_ticks, …))`），而不是放宽模型的约束。

撤掉夹住后 `tests/format_check.py` 复现原样报 `input_value=-458640`——这条不是设计出来的题。

### 验证：源码层

`tests/format_check.py`（新增，由 `tests/suite_check.py` 发现）：

- 契约自洽：每条预设的容器/编码/音频编码都必须在 `OUTPUT_CONTAINERS` / `OUTPUT_CODECS` /
  `OUTPUT_AUDIO_CODECS` 里，键集合固定；未知 codec 进 `output_args` 得 422 而不是拼出一条没验证过的命令。
- 参数分派被逐条断言：x264 保留 `-preset/-crf` 且无 `-tag:v`；x265 有 `-tag:v hvc1`；VP9 有
  `-b:v 0` 且没有 `-preset`；ProRes 有 `-profile:v 3` 且没有 `-crf`/`-b:a`；`-movflags` 只在 mp4/mov。
- 同一条 2 秒时间线走真实 HTTP + 任务 worker 各导一份，ffprobe 逐条核对：
  `h264/yuv420p + aac 48000Hz, 2.000s, 440 Hz 探针 0.088`、
  `hevc/yuv420p + aac, 2.000s, 0.088`、`vp9/yuv420p + opus, 2.008s, 0.089`、
  `prores/yuv444p10le + pcm_s24le, 2.000s, 0.088`；容器用 `major_brand`（isom / qt）与
  EBML DocType（WebM 与 MKV 在 ffprobe 里同名，必须读头 64 字节里的 `webm`）区分。
- **采样格式的可证伪证明**：画幅等于源（320×180，不重采样）的红\|蓝色块，在 Cb 平面上量过渡像素——
  ProRes 4:4:4 **0 个**、H.264 4:2:0 **2 个**（平台值 90/240）。把 `fit_stage` 的 `format=` 改回写死
  `yuv420p` 再跑，两边都变成 2（`{'h264': (2,[90,240]), 'prores': (2,[90,240])}`），检查当场红；
  把 `-movflags` 改成不分容器也红。这两条是突变验证过的，不是自我确认。
- 拒绝面：`.mp4` 名字配 WebM 预设 → 422 且消息点名 `.webm`；未知预设仍是 `UNKNOWN_PRESET`，
  不被后缀规则抢走（`tests/batch_check.py` 同步改成按预设查容器，并用一个 WebM 用例覆盖新分支）。
- 界面层：`tests/desktop_format_check.ts`（新增，`desktop_ts_check.py` 跑）断言编码行完全由预设算出、
  未知编码名原样透出、只有非默认采样才写「4:4:4 10-bit」。

### 验证：发布包与界面实点

包内冻结引擎（`desktop/release/win-unpacked`）与源码同版本，见下面的 1.57.0 发布验收。

界面用**构建产物**（`desktop/dist/renderer`）在浏览器里对着包内引擎点击（引擎的 `--token-file`
在少于 32 个字符时会自己重新生成，所以验收脚本从文件里读回真 token，而不是自以为写死了 token）：

- 导出面板给出 11 条预设；四条新行的文字逐字是
  「1080p HEVC/H.265（需播放器支持）mp4 · 1920×1080 · HEVC / AAC」、
  「4K HEVC/H.265 存档mp4 · 3840×2160 · HEVC / AAC」、
  「1080p WebM/VP9（网页与开放分发）webm · 1920×1080 · VP9 / Opus」、
  「ProRes 422 HQ 中间码（后期交接，体积大）mov · 跟随工程 320×180 · ProRes 422 HQ / PCM 24-bit · 4:4:4 10-bit」。
  旧的那行写死的「· H.264 / AAC」已经不在 `app.asar` 里（5,521,552 B，按 UI 文字与类名取针，不按会被改名
  的标识符取）。
- 点 WebM 那条 → 文件名后缀提示立刻变成 `.webm`，点「开始导出」→ 任务行显示
  「已完成 · 交付格式界面验收.webm · C:\…\out\run171148\交付格式界面验收.webm」，磁盘上 39,980 B；
  再点 ProRes 那条 → 后缀 `.mov`、主按钮 title 写「按 r1 导出 交付格式界面验收.mov」，落盘 651,881 B，
  包内 ffprobe 读回 `prores + pcm_s24le, yuv444p10le, 2.000000 秒`。同一份 2 秒片子，ProRes 是 H.264
  那条（56,314 B）的 11.6 倍——标签里的「体积大」是量出来的。
- 包内引擎的 HTTP + MCP stdio 走同一张表：`tools/call render_presets_read` 返回 11 条，四条新预设的
  容器与界面一致（人和 Agent 共用一处定义，不是界面上多一层翻译）。

### 1.57.0 发布验收

- `uv run ruff check src tests examples scripts`、`ruff format --check` 全绿；`npm run typecheck` 通过；
  `tests/suite_check.py` **49/49**（新增 `format_check.py` 一项，单独串行跑完，与打包不争 CPU）；
  `desktop_ts_check.py` 8 项壳层检查（新增 `desktop_format_check.ts`）。
- `scripts/build_engine.py --verify`：冻结引擎 `/v1/info` 报 `app_version=1.57.0`、`frozen=true`、
  media/render 就绪，裸启动冷启动 671 ms；包内引擎 97 个文件。
- `package_check_157.py`（包内引擎，实例 `1c41ef312b2e`）：capabilities 报 schema 13、
  `output_containers=['mp4','mov','webm']`、`features.multi_codec_delivery=true`、11 条预设的
  容器/编码/音频编码/采样格式与表一致；`.mp4` 名字配 WebM 预设在包内得到
  `INVALID_REQUEST` 且 details 里点名「filename must end with .webm for the vp9-1080p-web preset」；
  四份导出实测 `h264/yuv420p+aac 2.000s brand isom 56,314 B`、`hevc/yuv420p+aac 2.000s isom 60,976 B`、
  `vp9/yuv420p+opus 2.008s ebml-webm 39,980 B`、`prores/yuv444p10le+pcm_s24le 2.000s qt 651,881 B`，
  440 Hz 探针 0.088~0.089；红\|蓝 Cb 过渡像素包内也是 ProRes 0 对 H.264 2；MCP stdio 的
  `render_presets_read` 返回同一张 11 条表；`app.asar` 5,521,552 B 里有
  「ProRes 422 HQ / PCM 24-bit / 4:4:4 10-bit / libvpx-vp9 / h264-1080x1920-vertical」这些针，
  写死的「H.264 / AAC」已不在。
- `asar_compare.py`：包内 5 个 renderer/shell 文件与本地构建逐字节一致，包内引擎与验收引擎一致，
  ASAR 版本 1.57.0。
- 便携版 132,521,636 B SHA256 F19D168D1376629513226F4C875F4425195EDFBEB73DB9775CE0C796F1E2BC35；
  安装版 132,682,353 B SHA256 70AA50EE773E972293B5E5E0F99EF8167562C1F0210B76DB555149656E28073F；
  根目录 `AgentCut.exe` 与便携版逐字节一致。未签名，NSIS 向导未点击验收。

### 1.57 没做的事（边界照旧要说清）

- 纯音频交付（MP3/WAV）没有：`compile_render_plan` 现在遇到没有可见画面层的时间线直接
  `EMPTY_TIMELINE`，要出声音就得让画面链整段不编译，另开一轮。
- HEVC 的标签不承诺体积（见上文的 SSIM/尺寸实测）。
- ProRes 那条保住的是 4:4:4 采样与 10 位量化；时间线与调色链本身仍是 8 位精度，不是 10 位动态范围。
- 路径遮罩的顶点/形状动画、多目标与长时遮挡跟踪、旋转估计、色彩节点图的分层与连线
  （亮度曲线、LUT、色彩管理）、自动语音字幕——仍待实现。
- 发布包原生窗口：`win-unpacked/AgentCut.exe` 用 `Start-Process` 脱离父 shell 启动，`PrintWindow(flags=2)`
  采到 1480×900 一帧（PNG 127,127 B，MD5 `bcbd4f49b912e5653328fc20d3f10c0c`，与 1.56 那张不同），
  标题栏裁条放大后逐字读作「导出 · 引擎在线 v1.57.0」；关闭后 `Get-Process AgentCut, agentcut` 无残留。
  这一帧是用户 `%APPDATA%` 里的真实工程，只截图未编辑。

## 1.58.0 纯音频交付：MP3 / WAV / FLAC，画面链整段不编译（2026-10-07）

1.57 把「导出只有一种答案」拆开了，这一版补上交付页的另一半：只要声音。做法不是「渲染视频再抽音频」，
而是让预设说「没有画面」，编译器就真的不建画面链。

- 契约：`codec` / `pixel_format` / `scale` 允许 `null`，三条音频预设
  `audio-mp3`（libmp3lame 192k）、`audio-wav`（pcm_s24le）、`audio-flac`；
  `OUTPUT_CONTAINERS` 加 `mp3/wav/flac`，`OUTPUT_CODECS` 加 `None`。
- 编译：`RenderPlan.mode` 多一种 `"audio"`，`video_label=""`，`ffmpeg_argv` 只剩一个 `-map`；
  区间导出只 `atrim`。`EMPTY_TIMELINE` 从「必须有可见画面层」改成「按交付种类要求相应内容」——
  音频交付要的是**听得见的素材**，只有画面的无声时间线按名字拒绝。
- 界面：`presetIsAudio()` 驱动「画幅适配」与「附带竖屏」灰掉并说明原因，预设行写「仅音频 · MP3」。

### 验证与突变

`tests/audio_check.py`（新增，套件第 50 项）实测：

- 参数层：三条音频预设 `-vn`、无 `-c:v`、无 `-pix_fmt`、无 `-movflags`；mp3 有 `-b:a 192k`，
  wav/flac 没有 `-b:a`（无损谈码率是撒谎）；反过来视频预设没有 `-vn`。
- 画面链真的没建：同一条时间线（有声画面 + **无声**上层 + 配乐轨）里，音频计划 4 段滤镜 / 3 个输入，
  视频计划 11 段；那段无声素材在音频计划的输入里**根本不出现**，在视频计划里出现。
  突变：把跳过条件改成 `if False and audio_only:`（即照常建画面链），检查立刻
  `AssertionError: [vout]`——这条不是自我确认。
- 真实导出（HTTP + worker）：`mp3 48000Hz×2, 3.024s, 73,197 B`、`pcm_s24le 3.000s, 864,102 B`、
  `flac 3.000s, 186,048 B`，每条 ffprobe 只有**一个流**，容器名按 demuxer 核对（不按扩展名）；
  440 Hz 口播 0.085 与 220 Hz 配乐 0.042 都在里面。
- **同一次混音**而不是重算：ebur128 量视频成片 -20.8 LUFS，WAV / FLAC 同为 -20.8，MP3 -21.1
  （有损，差 0.3 LU，容差 0.6）。区间导出实测 1.032 秒对 1.000 秒的标记窗口（MP3 帧填充）。
- 拒绝面：`.mp4` 名字配音频预设、`.mp3` 名字配视频预设，各自 422 并点名要的后缀。
- 壳层：`tests/desktop_format_check.ts` 增加音频三行与 `presetIsAudio` 三态（含 `null` 预设不是音频）。
- 门禁：`ruff check` / `format --check` 全绿，`npm run typecheck` 通过，
  `tests/suite_check.py` **50/50**（单独串行）。

仍未做：MXF/DPX 等后期格式；音频交付仍走同一张混音图，没有独立的总线插件（EQ/压缩）。

### 1.58.0 发布验收

- `scripts/build_engine.py --verify`：冻结引擎 `app_version=1.58.0`、`frozen=true`，media/render 就绪。
- `package_check_158.py`（包内引擎，实例 `7836177e5ee7`）：capabilities 报 14 条预设、
  `output_containers=['mp4','mov','webm','mp3','wav','flac']`、`features.audio_delivery=true`，三条音频
  预设的 `codec/pixel_format/scale` 都是 `null`；真实导出 `mp3 48000Hz×2 3.024s 73,197 B`、
  `wav 3.000s 864,102 B`、`flac 3.000s 184,833 B`，每条**只有一个音频流**、容器名按 demuxer 核对，
  440/220 Hz 都在；ebur128 量包内视频成片 -18.9 LUFS、MP3 -19.1（0.2 LU，有损）；`.mp4` 名字配 MP3
  预设 422 点名 `.mp3`；只有无声画面的时间线出 MP3 被 `EMPTY_TIMELINE` 按名字拒绝；
  `app.asar` 5,522,028 B 里有「仅音频」「libmp3lame」「PCM 24-bit」「FLAC」这些不会被改名的字符串。
- `asar_compare.py`：包内 5 个 renderer/shell 文件与本地构建逐字节一致，ASAR 版本 1.58.0。
- 界面（构建产物点包内引擎）：14 条预设；选中 MP3 那条后行内文字是
  「MP3 音频（口播与配乐交付）mp3 · 无画面 · 仅音频 · MP3」，后缀提示 `.mp3`，
  「完整保留 / 裁切填满 / 拉伸填满」三个芯片 `disabled=true` 且 title 写「音频交付没有画面，这一项不参与」，
  「附带竖屏」勾选同样禁用并说明原因；主按钮 title「按 r1 导出 交付格式界面验收.mp3」，点下去任务行
  「已完成 · 交付格式界面验收.mp3」，磁盘 49,581 B，包内 ffprobe 读回**只有 mp3 一个流**、2.040 秒。
- 原生窗口：`win-unpacked/AgentCut.exe` 的 1480×900 一帧（`AgentCut-1.58-原生窗口.png`，
  MD5 `6a8b5c522ce6a9bee57af1a5352f3025`，与 1.57 的 `bcbd4f49…` 不同），标题栏裁条读作
  「导出 · 引擎在线 v1.58.0」；关闭后无残留。
- 产物：便携版 132,522,770 B SHA256 `ED936434B223A71D06B3FBF62F3412D7BE528816DE3E4FFAD36F6E3E7CC8A0AE`
  （根目录 `AgentCut.exe` 与便携版逐字节一致）；安装版 132,683,482 B SHA256
  `E4F1D0DC3772D19F5617D84ED76D0246FCE59D7361067B61A71047315868BD9C`。未签名，NSIS 向导未点击验收。

## 1.59.0 转场九种：方向擦除 + 缩放，清单归引擎（2026-10-07）

「镜头转场」这一行以前只有三种，而且全是整幅均匀变透明——剪映的「基础」页里最常用的擦除与放大都没有。
这一版补齐九种，并且把「有哪些种类」从界面里拿出来：`capabilities.transition_kinds` 是唯一清单，
下拉框与时间线徽标都读它。

### 设计上的一条硬约束：擦除不是透明度

叠化是标量：两层各乘一个权重、加起来仍是一个 alpha。擦除是空间的——如果照抄叠化、只是把权重换成
「按 x 位置算」，出画那一侧也必须同时按互补的斜坡衰减，否则同一像素被两层重复计数（实测会亮到
224 一档），或者中间漏出一条黑边。所以 `transitions.envelopes()` 对擦除种类**把两侧 picture 权重都
留在 1.0**（只有声音照常淡化），把空间项作为独立的一条 alpha 因子交给 `render` 乘进去，出画侧取互补。
这条不是推演出来的：`tests/wipe_check.py` 在羽化带里挑最平衡的一列量到 (125,25,82)，对半和理论值
(112,32,112) 之内，而重复计数会给出 (224,64,224)、漏空会给出接近黑。

### 实测

- 边界位置：红→蓝两镜头、1 秒重叠，窗口 25%/50%/75% 处实测 0.262 / 0.500 / 0.776，
  编译出的斜坡给 0.255 / 0.510 / 0.765；`wipe_from_right` 镜像 0.266 / 0.505 / 0.781。
  容差 0.05 幅宽是按物理推出来的：边缘一秒走完一整幅，一帧（1/30 秒）的寻址舍入就是 0.033。
- 窗口两端：t=1.0 那一帧蓝色覆盖 0.00，t=2.05 覆盖 1.00——中间三个点因此是一条行程而不是抖动。
- 缩放：源里 40 px 见方的白方块，`zoom_in` 在 p=0.25/0.5/1 实测 56 / 52 / 40 px，收尾精确回到 40。
- 回归：交叉溶解在同一帧整行仍是均匀半和——新种类没有改动老路径。
- 契约：九种全部 `transition.set` → 读回一致；invent 一个 `wipe_sideways` 得 422 且不烧 revision；
  `TransitionKind` 的 `Literal` 与 `TRANSITION_KINDS` 表必须点名同一组 id（只改一处，检查立刻红）。

### 本轮被自己的检查抓出来的两处实现错误

1. `curve_expression` 的时钟：`geq` 用 `T`，`scale` 滤镜用 `t`。把缩放因子按 `T` 交给 `scale`，
   FFmpeg 在整个图上报 `Invalid argument`；改成默认 `t` 才通。
2. 变量遮蔽：缩放那行写成 `size = ...`，把同一函数里表示输出画幅的 `size` 顶掉了，于是后面
   `color=c=black@0:s=<缩放表达式>` 直接开不出来。改名 `size_factor` 并留一行注释说明那个名字已被占用。
两处都是 `tests/wipe_check.py` 第一次真跑导出时暴露的，不是读代码读出来的。

仍未做：推移/滑动类（整层位移，需要给转场窗口内的层加时间相关的 overlay 偏移，另开一轮）、
动态 resize 与路径动画的转场组合、以及既有的路径遮罩顶点动画等项。

### 1.59.0 发布验收

- `scripts/build_engine.py --verify`：冻结引擎 `app_version=1.59.0`、`frozen=true`。
- `package_check_159.py`（包内引擎，实例 `3d2344ce078b`）：capabilities 报 9 种转场与中文标签
  （`wipe_from_top` → 「从上擦除」）与 `wipe_transitions`/`zoom_transitions`；包内导出后用**另一种**量法
  （一行里读作蓝主导的列占比，源码层用的是边界中点）实测：`wipe_from_left` 0.263 / 0.500 / 0.769
  对斜坡 0.255 / 0.510 / 0.765，`wipe_from_bottom` 0.256 / 0.500 / 0.767（竖向取第 60 列，避开白方块），
  `zoom_in` 的 40 px 方块读回 56 / 52 / 40 px；`app.asar` 5,521,954 B 里**没有**「从上擦除」「放大进入」
  这两个新标签（它们只从引擎来），而有兜底的「交叉溶解」与 `.transition-badge` 类名。
- `asar_compare.py`：包内 5 个 renderer/shell 文件与本地构建逐字节一致，ASAR 版本 1.59.0。
- 界面（构建产物点包内引擎）：选中第二个镜头后「方式」下拉列出**九项**且文字与引擎表逐字一致；
  选「从上擦除」→「添加转场」，时间线徽标显示「从上擦除」、aria 写「编辑从上擦除转场」；
  引擎侧存回 `kind=wipe_from_top, duration_ticks=35,280,000`（0.5 秒）、r2→r3、入点滑到 1.5 秒。
- 原生窗口：1480×900 一帧（`AgentCut-1.59-原生窗口.png`，127,137 B，MD5 `61dc5eba084a3510bc398eb44ffc0558`，
  与 1.58 的 `6a8b5c52…`、1.57 的 `bcbd4f49…` 各不相同），标题栏读作「导出 · 引擎在线 v1.59.0」；关闭无残留。
- 产物：便携版 SHA256 `C0FB4987BF9EC27B6785B3111D06EB9E1EEF5429FA8B2EE01697D310F4245022`
  （根目录 `AgentCut.exe` 与便携版逐字节一致）；安装版 SHA256
  `AC24E9E15D60421FFE426E00119E06C365737A89486AADC8F211349D27876175`。未签名，NSIS 向导未点击验收。

## 1.60.0 交付前先复检：FFmpeg 退出 0 不再等于成功（2026-10-07）

「渲染任务 succeeded」原来的判据只有两条：子进程退出码 0、临时文件非空。这两条挡住的是崩溃和空文件，
挡不住**结构与内容不符**：编码器可以高高兴兴地写出一个容器名不对、少一路流、或者长度不对的文件，
而 faststart 的 MP4 甚至可以只写了 30 % 字节却仍带着完整头部。这一版收紧的是成功判定这一层。

### 判据变成四条半，且不合格就不出货

`jobs._run_one` 在 `temp.replace(target)` 之前调用 `verify_output()`，用它旁边那个 ffprobe
（`ffprobe_beside()`，只认同目录，不从 PATH 借）重开候选文件：

1. 读不出流即拒（ffprobe 非零退出或 `streams` 空）；
2. 流的种类按计划：`plan.video_label` 非空必须有 video，纯音频预设必须没有 video，两者都有独立拒因；
   声音流恒必存在（混音以 anullsrc 打底）；
3. `format.format_name` 必须含预设点名的容器（按逗号切成员：webm 报 `matroska,webm`、
   mp4/mov 报 `mov,mp4,m4a,…`）；
4. `format.duration` 与 `plan.duration_ticks` 相差 ≤ `max(0.150 秒, 两帧)`；
4.5 尾部解码：同一个 ffmpeg 从 `时长-0.5` 秒解到结尾，`-v error` 有任何输出即拒。

拒绝时**删掉候选**再落 `failed`，`output_path`/`output_size_bytes` 留空；验收断言导出目录
`glob("*")` 为空，也就是调用者不可能拿到一个半文件。

### 实测

- 七种容器的合法时长偏差（各自真导一份再量）：mp4/mov/wav/flac **0.000** 秒、webm **0.008**、
  mp3 **0.024**（编码器前置延迟）。容差 0.150 秒是最大合法偏差的六倍，也是 30 fps 下两帧的 2.25 倍。
- 尾部解码耗时每份 **0.044–0.066** 秒（320×180/3 秒的样本），相对一次真实导出不值一提。
- **截断写是差量实测出来的**：同一个 faststart MP4 截到 30 % 字节后，ffprobe 仍报两路流、
  `format.duration=3.000000`——元数据四项全部放行；尾部解码报
  `stream 1, offset 0xa4ed: partial file` 与 `Invalid NAL unit size (718 > 650)`，被拒。
  这条不是补出来的故事：先量到元数据放行了，才加的第 4.5 步。
- 三种真跑的任务：量过的写 `已输出 probe.mp4（复检：3.000 秒 / 2 路流（h264/aac）/ mp4，尾部可解码）`
  且 `output_checked=true`；只有 ffmpeg.exe 的目录（硬链接造出来的）写「未经复检：no-probe 目录里没有
  ffprobe」且照常出货；把 ffmpeg.exe 复制成 ffprobe 让探针失灵时任务 `failed`、
  `error_code=OUTPUT_INVALID`、目录里一个文件都不留。
- 门禁不挡合法工作：套件里跑过真实导出的检查全绿——`format_check` 那 4 条视频预设、`audio_check` 的
  3 条音频预设加 1 条视频对照，每一条任务的 `output_checked` 都是 true（这两条断言就是这一版新加的）。

### 本轮被自己的检查抓出来的一处断言错误

`tests/audio_check.py` 的导出循环里第一条是**对照组**（`h264-source-quality`，两路流），我按音频形状
断言消息里是「1 路流」，套件跑第一遍就红在对照组的行号上。改成：`output_checked`/「复检」对所有导出断言，
「1 路流」只对纯音频那三条。失败信息里带着引擎实际写的
`复检：3.000 秒 / 2 路流（h264/aac）/ mp4`，也就是门禁本身没错，是我断言放错了位置。


### 1.60.0 发布验收

- `scripts/build_engine.py --verify`：冻结引擎 `app_version=1.60.0`、`frozen=true`，冷启动到 ready 735 ms，
  `mcp` 模式存活、无 ffmpeg 参数时如实报告；裸启动 media_ready 由 PATH 上的 ffmpeg/ffprobe 兜住。
- 包内引擎（`release/win-unpacked/resources/bin/agentcut/agentcut.exe`，实例随临时目录）：
  `/v1/info` 报 1.60.0/`frozen=true`，capabilities 报 `features.verified_delivery=true`；真实素材导入、
  建工程上轨后 `h264-1080p` 导出，任务 `succeeded` 且 `output_checked=true`，消息写
  `已输出 pkg160.mp4（复检：3.000 秒 / 2 路流（h264/aac）/ mp4，尾部可解码）`，产出文件用包内 ffprobe
  复核为 h264+aac 两路。包内 `agentcut.exe mcp` 经官方 stdio 客户端 `tools/list` 37 个工具，
  `timeline_edit` 写入 r2，工程 revision 实涨。
- ASAR：100 条目；`dist/`+`dist-electron/` 全部 7 个构建产物与本地构建逐字节一致（唯一差异是
  electron-builder 重写的 `package.json`，版本 1.60.0）。
- 原生窗口：`win-unpacked/AgentCut.exe` PrintWindow 抓帧 1480×900
  （`C:/tmp/AgentCut-1.60-原生窗口.png`），自绘标题栏读作「引擎在线 v1.60.0」，工作台完整渲染；
  `taskkill` 后 `Get-Process AgentCut,agentcut` 查无残留。
- 产物：便携版 132,530,580 字节 SHA256 `D5C500EAAE8C54D3AA61A6172CA9F94CC23954F3678729D78AC9994E610231B9`；
  安装版 132,691,299 字节 SHA256 `E5B05B8850D9637BA5042953BA07DE73061962D0B7C68641733B686BC3387CAC`；
  根目录 `AgentCut.exe` 与便携版逐字节一致。未签名，NSIS 向导未点击验收。
- 门禁：`ruff check` / `ruff format --check`（79 文件）、`tests/self_check.py`、`tests/suite_check.py`
  52/52 全绿（含新 `verify_check.py` 与桌面 TS 检查）。

## 1.61.0 自动语音字幕（2026-10-07）

「常用成片」清单里最后一块纯本地就能做的大件：口播素材不用再逐句手打字幕。选中带声音的片段点
「自动字幕」，引擎抽原片声音（16 kHz 单声道 s16le 管道喂给 vosk），词级时间戳换算到时间线 tick
（源秒 ÷ 速度 → 片段本地 tick + 片段位置；变速曲线时间不是线性，与静音扫描同一句拒绝），按
「16 字 / 4 秒 / 0.7 秒停顿」断行，最后把 SubRip 文本交回**既有的** `captions.import` 命令落轨——
轨道、文字素材、片段、帧对齐、2000 条上限、撤销与去重全部是导入器已有的规则，ASR 不另立一条路。

三条实测逼出来的设计：

1. **内容寻址 id**：字幕轨/素材 id 取 `sha256(scope + cues)` 而不是随机数也不是请求 id。第一版用
   `os.urandom`，同 request_id 重放的 payload 变了，去重当场报 IDEMPOTENCY_CONFLICT（自己的套件抓住的）；
   改成含 request_id 后重放好了，但换 request 重跑会叠出第二条一模一样的轨。最终摘要只含 scope 与
   cues：同一段话永远映射同一条轨——重放命中回执，重跑被 reducer 的 DUPLICATE_ID 拒绝，界面用
   `replace_track_id`（引擎出 `clip.remove×N + asset.remove×N + track.remove + captions.import` 一笔事务）
   做成「重新生成」语义，替换后轨 id 与片段 id 都不变（真·原位重生成）。asset.remove 这步是
   实测补的：track.remove 不清素材，同 id 的 import 会被它自己挡住。
2. **非 ASCII 路径**：`Model()` 在任何含非 ASCII 的目录上都加载失败（libvosk 用 ANSI 码页开文件），
   8.3 短路径也救不了中文目录名。运行时回退：ASCII 直用 → GetShortPathName → 复制到
   `%PROGRAMDATA%\AgentCut\asr` 缓存 → 还不行就 503 并指路 AGENTCUT_ASR_MODELS。
3. **片段级拒绝、整轨级跳过**：与静音扫描同一份 `audio_scan_problem` 判定。第一版把显式点名的片段
   也静默跳过了（报成 SPEECH_NOT_FOUND），被 refusal 套件当场纠正——点名的片段必须带着原因 422。

验收 `tests/asr_check.py`（不是冒桩：Windows SAPI 合成真实中文两句、中间 1 秒静音）：识别 ≥2 条线索、
「大家好/剪辑/自动」在文本里、时间全部落在片段内、SRT 重解析条数一致；apply 一个 revision、同
request 重放 replayed=true、换 request 撞 DUPLICATE_ID、dry-run 前瞻不落库；replace 原位重生成同 id
同条数；**成片实测**——纯声音时间线导出后字幕帧有亮像素、前导空帧为 0（黑底上唯一的亮字只可能来自
生成的字幕）；200% 变速同样的文本落在减半窗口；静音/变速曲线/缺模型各按原因拒绝。
界面真机实测（vite 渲染层 + 引擎 1280×800）：选中口播片段 →「自动字幕」按钮按能力出现 → 点一次
r1→r2，时间线上方新增「字幕」轨、4 条紫色片段与语音逐句对齐（截图在案）；重跑走替换不叠轨。

模型分发：中文小模型（vosk-model-small-cn-0.22，66 MB）放 `desktop/resources/asr/`（不入库），
`build_engine.py` 暂存到冻结引擎旁的 `asr/`，随包开箱即用；英语小模型同机制、未随包，
`SUBTITLES_MODEL_MISSING` 会点名放哪里。pyproject 增加 `vosk>=0.3.45,<0.4`（wheel 自带
libvosk.dll，PyInstaller 直接打包），无其它新依赖。

仍未完成：字幕的说话人分离与标点恢复（vosk 小模型不输出标点）、多语言混说、大模型精度
（同音字需人工校对）、路径遮罩顶点动画、色彩节点图的分层与连线（亮度曲线、LUT、色彩管理）、
多目标与长时遮挡跟踪、旋转估计。

### 1.61.0 发布验收

- `scripts/build_engine.py --verify`：冻结引擎 `app_version=1.61.0`、`frozen=true`，冷启动 779 ms、
  `mcp` 模式存活；本轮新增 `--collect-all vosk`——不加它，vosk 的 `__init__` 在冻结包里
  `os.add_dll_directory` 找不到包目录抛 FileNotFoundError，而 `asr_ready()` 只捕 ImportError，
  `/v1/info` 直接 500（第一次构建就是这样红的）；修复同时把 `asr_ready()` 改成捕获一切导入失败，
  语音栈坏了只降级能力、不拖垮信息端点。
- 包内引擎（`release/win-unpacked/resources/bin/agentcut/agentcut.exe`）：`/v1/info` 报
  1.61.0/`frozen=true`，capabilities 报 `verified_delivery` 与 `speech_captions` 双真；对包内随附
  模型（staged 65.1 MB）实测识别真实中文语音 4 条线索、`h264-1080p` 导出 `output_checked=true`
  （复检消息在案）；包内 MCP stdio 38 个工具（含新 `captions_auto`），`timeline_edit` 写入 r2。
- ASAR：100 条目；`dist/`+`dist-electron/` 8 个构建产物与本地构建逐字节一致（唯一差异是
  electron-builder 重写的 `package.json`，版本 1.61.0）。
- 界面真机（vite 渲染层 + 引擎，1280×800）：「自动字幕」按钮按 `capabilities.speech_captions`
  出现在片段区，点击 r1→r2 生成「字幕」轨 4 条与语音逐句对齐的字幕片段（截图在案）。
- 原生窗口：`win-unpacked/AgentCut.exe` PrintWindow 1480×900
  （`C:/tmp/AgentCut-1.61-原生窗口.png`），自绘标题栏「引擎在线 v1.61.0」，工作台完整渲染；
  关闭后无 AgentCut/agentcut 残留进程。
- 产物：便携版 189,720,995 字节 SHA256 `B7B0F91CFC4AA149C8B9E7CA9E220DFE0D961B3A1C07E2B0FB839A83F489B5C1`；
  安装版 189,881,706 字节 SHA256 `0EF53526192AE5D94C2E094DAD201A125473A3348B9E9B0D2E1CD037AF69D2F9`
  （+57 MB 来自随包语音模型与 libvosk）；根目录 `AgentCut.exe` 与便携版逐字节一致。未签名，
  NSIS 向导未点击验收。
- 门禁：`ruff check` / `ruff format --check`（81 文件）、`tests/self_check.py`（含 `captions_auto`
  工具断言）、`tests/suite_check.py` **53/53** 全绿（新 `asr_check.py` 在列）、`npm run typecheck`
  与 8 项桌面 TS 检查全绿。

## 1.62.0 调色节点·1D LUT 查找表导入（2026-10-07）

「常用成片」清单上色彩那一格还缺的最小一块：人们手里已经有 `.cube`。这一节把它接进**既有**的调色节点图——
不新增命令、不新增 schema（仍是 v13）、不给 LUT 单开一条渲染路径，因为架构的不变量是「每个节点都是每通道
函数，整条链塌缩成一张表，`lutrgb` 与浏览器 `feComponentTransfer` 读同一组数」。1D 查找表恰好就是这个形状：
三个通道各一条折线。3D 查找表不是——它的输出红取决于输入的绿与蓝，是跨通道矩阵，硬压成三条独立曲线就是
骗人，所以解析器点名拒绝它，能力接口也只声明 1D 这一件事。

四条被实测逼出来的设计：

1. **`.cube` 只由引擎读一次**。`grade.parse_1d_cube` 是全项目唯一的查找表读者：桌面界面把文件文本 POST 到
   `/v1/lut/parse`，Agent 调 MCP 的 `lut_parse`，回复就是可直接写进 `clip.color.grade` 的 `GradeLUT` 载荷。
   `desktop/` 里没有任何 `.cube` 解析代码（grep 得到），所以「人看到的表」与「Agent 算出的表」不可能不一致
   ——这与「素材 reference 是不可信元数据」是同一条纪律。
2. **上限只有一个主人**。`capabilities.grade_limits = {max_nodes:8, max_branches:4, max_curve_points:16,
   max_lut_samples:1024}` 由引擎下发，界面的节点数、曲线控制点数、并联支数、LUT 采样数全部照这份表限制
   （1.55 的同一课）。`LUT_SAMPLE_LIMIT` 定成 1024 不是随手写的：`.cube` 的 1D 表实际就是 33 / 64 / 256 / 1024
   这几种，上限低于 256 会把人手里现成的文件拒之门外。
3. **重采样必须说出口**。超过 1024 行的表按等距网格线性重采样到 1024（引擎自己也是按分段线性读这张表的），
   回复里带 `resampled_from`＝原文件行数，界面的提示条把它念给人听。不改掉你的数再假装没改。
4. **LUT 节点没有「中性值」**。曲线可以两点恒等、白平衡可以 0/0，一张表的内容只能来自文件，所以界面里
   `newOperation` 的参数类型改成 `Exclude<GradeOperation["kind"], "lut">`：把 `"lut"` 误传进去会在编译期报错，
   而不是像原来那样落到最后的 `else` 里悄悄建出一个 RGB 增益节点。

验收 `tests/lut_check.py`（四个互不相干的角度，因为「读错文件」正是能一路绿灯交付的那种缺陷）：
**构造即事实**——文件内容按公式自己写，读回的三个通道逐值等于那些数（不拿解析器再解析一遍当参考），越界值
夹住、小写关键字/引号标题/注释/CRLF 都能读；**浏览器表** 768 格（256×3）对独立写出的等距线性插值最大
**0.125 阶**；**FFmpeg 自己算的那一遍**把 256 级灰度斜坡直接喂给编译出的 `lutrgb` 串（不经编码器），红/绿/蓝
三条对各自文件的数最大 **1.00 / 1.00 / 1.09 阶**，串长 3443 字符且只含安全字符；**成片实测**六档灰带
[2,18,62,126,194,249] → [0,2,41,137,235,253]，18 个点全部对得住下发的表（≤4 阶，最大位移 41 阶）。
`mix=0` / `enabled=false` 依旧一个滤镜阶段都不加；LUT 与曲线串成链仍是一张表。拒绝：3D、缺 `LUT_1D_SIZE`、
行数比声明少、**行数比声明多**、非默认 DOMAIN、行里字段数不对、数字读不出来，各按原因 422 `INVALID_LUT`；
七种写坏的载荷（size 与通道长度不符、采样点越过 1.0、invented 的 `spectron`、9 个节点、越界 effects、
错类型文字、通道数不对）全部 422 `INVALID_REQUEST` 并带 `details.issues` 指出字段，revision 一动没动。

**这条门禁不是一开始就能红的**：变异测试第一版漏掉一个。把 `_op_function` 里三个通道都读 `channels[0]`
（最像人犯的通道顺序错）当场报 **55.875 阶** ✓；把 `len(samples) != size` 改成 `<`（信任表头、悄悄丢掉多余的
行）却整条检查全绿——原来只测了「行数不够」没测「行数多了」。补上「声明 2 行给了 3 行」这一条，同一处变异
立刻红在 `must be refused` 上；恢复后逐字比对备份一致。

界面真机（构建后的渲染层 + 源码引擎，`?engine=&token=&project=` 深链，真实 HTTP）：选中片段 →「+LUT」按
`capabilities.lut_import` 出现 → 把 `.cube` 交给隐藏的文件输入并派发 `change` → 提示条读作「导入
Harness S-curve / 三个通道各 33 个采样点…」，卡片变成「1. LUT 查找表」写着「Harness S-curve · 33 点」，
预览里凭空多出一个 `<filter id="g0ea8f8bfb6e05778">`（无调色时是 0 个，那是控制态）。权威回读
（`ui_lut_readback_162.py`）：revision 1→2、库里存的正是那 3×33 个数、页面 `feFuncR` 的 256 项**就是**引擎下发的
那张表（按文件的网格位置取样最大 **0.083 阶**），而这个工程真实导出的 H.264 里那块平灰实测 **138.0**，
表说 **138.5**（源 128），三通道一致——LUT 在画面里，不只在请求里。`tests/desktop_graph_check.ts` 钉住卡片
描述：`4. LUT 查找表` + `Film Look 01 · 33 点` + `强度 40%`。

两处随后自己补上的边界：一是 **LUT 作为并联的一支**（契约允许，`GradeBranch` 含 `GradeLUT`）——第一版
`lut_check.py` 只测了串行，补了一条「LUT 支与白平衡支取平均」的断言，最差 **0.247 阶**，仍是每通道一张表；
二是界面「换一张 LUT」原本会把该节点的启用状态、强度和混合方式一起重置成默认值（导入的内容对象里带了
`enabled: true`），改成只换 `title/size/channels` 三项，提示条也改成「第 N 个节点换成 …」，用户给这个节点
设过的东西不该被一次导入抹掉。

### 1.62.0 发布验收

- `scripts/build_engine.py --verify`：冻结引擎 `app_version=1.62.0`、`frozen=true`，带媒体冷启动 722 ms、
  裸启动 642 ms，`mcp` 模式存活；暂存 ffmpeg 79.0 MB / ffprobe 60.1 MB / 中文语音模型 65.1 MB，合计 324.9 MB。
- 包内引擎（`package_check_162.py`，全部在冻结二进制里跑）：`/v1/capabilities` 报 `lut_import=true` 与逐键
  相符的 `grade_limits`，`/v1/contracts` 里有 `LutParse`；`POST /v1/lut/parse` 把 33 点表逐值读回、3D 表按
  `INVALID_LUT` 拒绝、2048 行重采样到 1024 并回报 `resampled_from`；写进 `clip.grade` 后预览表
  `g0ea8f8bfb6e05778` 的 256 项在文件自己的网格点上偏差 **0.083 阶**（与源码引擎那次是同一个 id，哈希自同一
  张表）；`h264-source-quality` 导出 6,159 B、`output_checked=true`，平灰块实测 **[138.0, 138.0, 138.0]**
  对表算 138.5（源 128：既要对得上表，又要对不上原值）；包内 `agentcut.exe mcp` 经官方 stdio 客户端
  `tools/list` **39** 个工具（新增 `lut_parse`），同一个文件内容经 MCP 拿回的 3×33 个数与经 HTTP 的逐值相同，
  3D 那条也带同样的拒绝文本。
- ASAR：5,528,549 字节，needles 是「换一张 LUT」「LUT 查找表」「.cube」「三个通道各」「gg-card」「grade-body」
  与能力名 `lut_import`（都是打包器改不掉的字面量）。
- 原生窗口：`win-unpacked/AgentCut.exe` 经 PrintWindow 抓帧 1480×900
  （`Documents/Codex/2026-10-04/du/outputs/AgentCut-1.62-原生窗口.png`，127,138 字节），标题栏裁条放大四倍读作
  「引擎在线 v1.62.0」，工作台完整渲染；`CloseMainWindow` 后 `tasklist` 查无 AgentCut/agentcut 残留。该次启动
  打开的是用户自己的 `%APPDATA%` 工程，只读不回写（截图与关闭而已）。
- 产物（客户端修好「换一张 LUT 会抹掉节点自己的启用/强度/混合」之后**重新构建并重跑整条包内验收**）：
  便携版 189,730,081 字节 SHA256
  `C4C4FA6D089EE8D6E60B05A3326A4FF3AE897DB508C3C7D4D80B6F5E1FDC92B8`；安装版 189,890,794 字节 SHA256
  `779DBEF44BFE10215E210BE4AE8CA1A5FFD5B1500A8AA49CF8B8AC9BFC2FD439`；`win-unpacked/AgentCut.exe` SHA256
  `38A5599D74AF0BDB54DAD49F78D5B9BE32E73BD7D15E4D43D3C4EA4120C0B53B`；根目录 `AgentCut.exe` 与便携版
  `cmp` 逐字节一致。未签名（electron-builder 的 signtool 步骤是自签占位），NSIS 向导未点击验收。
- 门禁：`ruff check` / `ruff format --check`（82 文件）、`tests/self_check.py`（含 39 工具与 `lut_parse` 注解
  断言）、`tests/suite_check.py` **54/54**（新 `lut_check.py` 在列，构建结束后单独串行复跑）、
  `npm run typecheck` 与 8 项桌面 TS 检查全绿。

### 1.62.0 命令面可靠性扫面（同一版本里的第二道门禁）

LUT 做完后回头问了一个更一般的问题：**人和 Agent 能发出去的 52 种命令里，有没有哪一种能把手感好的
422 变成 500**。这一节就是那次的产物，也是它自己的门禁 `tests/matrix_check.py`：

- 每种命令探三种载荷——只给判别字段；把每个必填字段填成**类型正确但不指向工程里任何东西**的值（契约里
  的 `Identifier` 允许 `"nope"`，所以这种载荷能穿过边界、落到 reducer）；再把每个整数字段单独推到
  `MAX_TICKS`（位置加长度的溢出是这类引擎最经典的 500 来源）。
- 加 19 条只在真实状态下才咬人的语义陷阱（锁轨上的最后一个片段、越界的标记、跨轨 roll、把嵌套画面
  再套一次、无内嵌声音的 detach…）。
- 断言只有一条硬的：**状态码必须小于 500**；每条拒绝都得带 code 与能读的 message；干跑不许改一个字节；
  同一条命令干跑与提交必须给出同一个 code；还要有至少 10 种 code 来自编辑规则而不是契约层的
  `INVALID_REQUEST`——否则说明这一轮扫面根本没碰到 reducer，只是在原地测 pydantic。

实测：140 次探测零 5xx，13 种 reducer 级 code，14 条陷阱干跑与提交一致，合法写入仍落一个 revision。
两条「看着就该拒」的按实测钉成反例：**把嵌套画面再嵌套一次是合法的 depth 2**（`SEQUENCE_CYCLE` 只挡真环），
**`captions.import` 会创建它点名的那条轨**（`track_id` 是要建的名字，不是必须已存在）。变异验证：把
`_unlocked` 的判断短路，`clip.ripple_remove` 那条立刻红在 200 上——这道门禁是能用力的。

顺带澄清一件差点被当成缺陷的事：`clip.patch` 里那份 `Any` 的 `grade` 载荷，先前被判断「会绕过校验、
在 reducer 里抛 pydantic 错误变成 500」。实测六种坏载荷（size 与通道长度不符、采样点越过 1.0、
invented 的 `spectron` 类型、9 个节点、越界 effects、错类型文字）**全部**由契约边界以 422
`INVALID_REQUEST` 拒掉并逐条列出 `details.issues`，把 reducer 换回原样也一模一样——所以这不是缺陷，
也就没有为此加一层重复校验。写错的检查比没写的检查更危险，这一条记在这里。

仍未完成：**3D LUT**（跨通道，需要另一条编译路径与浏览器端的三维取样，塞不进每通道表）、亮度/色度分离曲线、
色彩节点图的分层与连线视图、完整色彩管理（ICC/ACES、色域矩阵与文件标签）、路径遮罩顶点动画、多目标与长时
遮挡跟踪、旋转估计、字幕说话人分离与标点。

## 1.63.0 文字样式：一份数，两遍渲染（2026-10-07）

字幕和花字是剪映类工具最常用的入口，而 1.62 之前的文字层只有「内容 / 字号 / 颜色 / 靠上居中靠下 / 要不要
垫子」五件事。这一节把它扩到 15 个字段：face、横排左中右、描边宽度与颜色、阴影 X/Y 与颜色、垫子颜色与
浓度、行距。三条设计决定不是审美问题，是这套架构的边界：

1. **所有比例都相对字号**。`outline_width: 0.12` 在导出侧是 `borderw=round(0.12*fontsize)`，在浏览器侧是
   `text-stroke-width: 0.12em`——`em` 本身就是字号的倍数，所以两边读的是同一个数，不需要任何换算表，
   也不会出现「预览里描边更粗」。行距同理：CSS `lineHeight = 1 + line_spacing` 对 drawtext
   `line_spacing = round(line_spacing*fontsize)`。
2. **drawtext 画不出的，契约里就不存在**。阴影模糊与字距（letter spacing）被明确拒之门外：浏览器能画
   `text-shadow: 0 0 8px`，drawtext 不能；给了这一档就只有预览里好看、成片里没有。这与 1.62 拒绝 3D LUT
   是同一条理由——宁可少一档，不做「只有预览看得到」的效果。
3. **face 是机器事实，不是字符串**。`capabilities.text_fonts` 只列本机真的存在字体文件的那几个
   （Windows：微软雅黑 / 黑体 / 宋体 / 楷体 / Arial / Consolas），界面按它建选择器，Agent 按它选值；
   点一个本机没有的 face 报 `FONT_UNAVAILABLE`（503）并把可用项列回去，**不静默换脸**。

**踩到并用像素钉住的坑**：`fontfile` 的路径写法。第一版按 `os.path.join` 的结果转义冒号，得到
`C\:\Windows\Fonts\simhei.ttf`；FFmpeg 不报错，但会**悄悄退回默认字面**——于是「黑体」和「宋体」导出后
逐像素完全相同，`tests/textstyle_check.py` 的 `differ > 300` 当场报 **0**。用包内 FFmpeg 把两种写法各跑
一遍比对哈希才确认：能用的是 `C\:/Windows/Fonts/<file>`（正斜杠 + 转义冒号，也就是 1.62 里唯一那个写死的
路径的形状）。修在 `text_font_path` 一处，检查里再加「三种字体三张不同的图」，这条就不会再退回去。

**默认值就是 1.62 的画面**：`outline_width 0.04 / outline_color #000000 / line_spacing 0.2 /
box_opacity 0.45`，所以老工程一字不改仍逐像素相同——`filter_suite` 直接断言默认样式编译出的
`borderw`、`line_spacing`、`x`、`fontfile` 与 1.62 的公式一致，且没有 `shadowx`、没有 `geq` 垫子带。

**回执指纹不能再手写名单**。`clip.patch` 的 `text` 原先写死 `Literal["body","font_size","color","align","box"]`，
1.63 一加字段，界面新控件第一次写入就被契约拒绝（`Input should be 'body', 'font_size'...`）；改成拿
`TextStyle` 复检（`{"body": ".", **text}`），键的白名单与取值范围从此只有一份主人。历史兼容同一处：
`_fingerprint` 里「哪些文字字段属于更晚的时代」现在从 `TextStyle.model_fields` 推导，
`tests/text_receipt_check.py` 的 v1.5 / v1.7 回执都重新命中——但注意它**先红过一次**：第一版我把
`body/font_size/color` 也当成「可丢的默认值」，v1.5 的哈希反而被推走了；规则是「只有晚于该载荷时代
出现的字段才不算请求内容」，1.7 那一份确实显式带了 `align/box`，所以比较旧回执的那一路必须留着它们。

验收 `tests/textstyle_check.py`（五路）+ `tests/desktop_text_check.ts`（CSS 逐字段）：
契约层七个越界样式被拒、默认值等于 1.62；字体层 6 个 face 因为文件真在盘上被下发，把
`FONT_ROOT` 换成空目录后清单为空且请求按 `FONT_UNAVAILABLE` 拒绝；编译层断言 `borderw`/`shadowx`/
`shadowy`/`line_spacing` 都是按字号取整的整数、`x` 随横排取 `w*0.08` / `(w-text_w)/2` /
`w-text_w-w*0.08`、垫子带写出 `geq=r='64':g='64':b='64'` 与 `204/255` 的 alpha、正文只以
`textfile=text-<sha256>.txt` 进命令；**成片实测**（320×180 黑底白字，字号 12%）——描边加粗后红环
**1639 px**、绿色阴影质心相对字形右移 **31.1 px**、垫子带灰阶实测 **64**（要的就是 64）、
左/右对齐文字质心 **70 对 252**、黑体与宋体在 **712 个像素**上不同、楷体与黑体也不同；HTTP 层
15 个字段的样式经 `clip.text` 与 `clip.patch` 原样往返，声音片段与越界宽度被拒且 revision 不动。
### 1.63.0 发布验收

- `scripts/build_engine.py --verify`：冻结引擎 `app_version=1.63.0`、`frozen=true`，带媒体冷启动 755 ms、
  裸启动 657 ms。
- 包内引擎（`package_check_163.py`）：`/v1/capabilities` 回 `text_styling=true` 与 6 个 face（雅黑/黑体/
  宋体/楷体/Arial/Consolas，逐个断言字体文件确实在盘上）；一个 15 字段的样式经 `clip.text` 写入后逐字段
  读回相同；同一工程**先出一版对照成片**（渲染按当前 head 校验，没有「渲染 revision 1」这个旋钮），
  再出样式版，两份都 `output_checked=true`。成片像素实测：红描边 **1665 px**、绿阴影 **573 px** 且质心
  在字形右侧 **46.3 px**、垫子带灰阶 **64**（要的就是 64）；包内 `agentcut.exe mcp` 的 `tools/list` 仍是
  **39** 个工具（1.63 不加端点），而 `timeline_edit` 由契约生成的 schema 里 `text_align`、
  `outline_width`、`shadow_color`、`box_opacity`、`line_spacing` 全在——Agent 看到的字段与人能改的是同一份。
- ASAR：5,533,579 字节，needles 为「描边」「阴影左右」「垫子浓度」「行距」「字体」「caption-layer」
  「text_styling」「drawtext 画不出」。第一条包内检查跑在能力门控之前，`text_styling` 那个 needle 当场
  报缺——因为界面的新控件当时没有按能力隐藏。补上 `app.caps?.features.text_styling` 门控后重建重验：
  新界面遇到不认识这些字段的旧引擎会**整段不显示**，而不是发一份会被契约拒绝的载荷。
- 原生窗口：`win-unpacked/AgentCut.exe` PrintWindow 抓帧 1480×900
  （`Documents/Codex/2026-10-04/du/outputs/AgentCut-1.63-原生窗口.png`），裁条放大四倍读作
  「引擎在线 v1.63.0」；关闭后 `tasklist` 查无 AgentCut/agentcut 残留。**同时记一件自己造成的损害**：
  复制上一版抓屏脚本时把 `162` 全局替换成 `163`，没有命中输出路径里的 `1.62`，于是 1.62 的原生窗口 PNG
  被 1.63 的帧覆盖。已把该文件按真实内容改名为 `AgentCut-1.63-原生窗口.png`（帧内标题栏即证明是 1.63），
  并删除被误标的 1.62 PNG——留着标错的文件比留一张空缺更危险。1.62 的原生窗口截图因此不再在档，
  该版本的验收结论仍由它自己的记录与产物哈希支撑。脚本里的路径已修正，下一版不会再踩。
- 产物：便携版 189,737,243 字节 SHA256
  `FBF3AEAFDF8CDB348D490599A93D80CAC5CD582E86A6D194671EEF63532EA8E2`；安装版 189,897,966 字节 SHA256
  `B9A8F44C773E68DCAC7A750722D37BACB722D655ECDCB6DC7CE83D28CF6E14B2`；根目录 `AgentCut.exe` 与便携版
  逐字节一致。未签名，NSIS 向导未点击验收。
- 门禁：`ruff check` / `ruff format --check`（84 文件）、`tests/self_check.py`、`tests/suite_check.py`
  **56/56**（新 `textstyle_check.py` 在列；构建与界面改动全部落定后单独串行复跑）、`npm run typecheck`
  与 9 项桌面 TS 检查全绿。`tests/patch_check.py` 因样式长了 10 个字段而红过一次——它断言的是旧的 5 字段
  存储形状，改断言时把「未被 patch 的新旋钮停在默认值」写进期望里，而不是把断言删掉。

## 组合片段会不会吞掉逐片段滤镜（2026-10-07，新增门禁 `tests/nestfx_check.py`）

1.62 的 LUT 节点与 1.63 的文字样式都是「逐片段滤镜」，而嵌套合成的内部片段不在 `project.clips` 里，
它们在 `project.sequences[s].clips`——这正是滤镜最容易丢的一层。`nest_check.py` 早已证明 effect、轨道
混合、源入点、变速在组合里逐像素不变，但新加的两类滤镜没有走那条断言。

做法是差分而不是绝对值：同一条纯色画面 + 同一条字幕，一份写在根时间线上，一份 `sequence.nest` 之后
在 `sequence_id=inner` 的作用域里写同样的 `clip.grade` 与同样的样式，三帧逐像素比。**实测 0 级差**，
编译图里 `lutrgb`/`drawtext`/`borderw`/`shadowx` 四项俱在且 `drawtext` 恰好一段——因为
`clip_input()` 对 `kind == sequence` 的条目直接 `compile_render_plan(sequence_view(...))` 递归，
内部片段与根片段共用同一个构建器，没有第二条实现可以走偏。

两道反向断言防它量空气：
- 对照组（同样的画面与文字，去掉全部 1.62/1.63 旋钮）相差 **241 级**——滤镜确实在画面上生效；
- 只把组合内部那张 LUT 表的红通道中间 knot 从 0.4 挪到 0.9，成片动 **85 级**——内部的表是活的。

第二条差点把我自己的探针骗过去：初版把改动放在蓝通道第一个 knot 上，而测试画面蓝值 160/255=0.63
落在 [0.5,1] 段，两段端点没变，于是三帧**逐位相同**，探针当场报「内部 LUT 没生效」。这不怪引擎——
纯色样片每个通道只探测一个点，差分必须扰动那个点真正所属的那一段。门禁的注释里写明了这件事，
免得下一个人再拿一张纯色图去猜段。

变异验证两次都做在真实代码路径上（做完 `git checkout` 还原，`git diff` 为空）：把组合内部片段的
`color.grade` 清空 → 红在 `nested: the LUT node never reached the exporter`；把 `text` 清空 → 红在
`nested: the caption never reached the exporter`。第一版变异写的是 `color = None`，结果崩在
`grade.py` 的 `_polylines` 上（`Clip.color` 并非可空），那是无效变异——它证明的是我改错了形状，
不是门禁有效，因此换成保持形状的 `grade = []` 重做。

`suite_check.py` 靠 `*_check.py` 通配自动收新门禁，无需注册；README 的「嵌套合成」一行补了这三组数字，
门禁计数从 56 项改为 57 项。本轮不改 `APP_VERSION`：没有新能力上线，只是把一条已交付的链路钉住。

## 1.64.0 片段柔焦：把两端的「同一个数」变成实测的「同一个半径」（2026-10-08）

剪映、达芬奇、AE 都有模糊这一挡，工程里却根本没有：`ClipEffects` 只有位置/缩放/旋转/透明度/音量，
`grade` 全是每通道传递函数（不能碰空间），`feather` 只作用于遮罩边缘。做遮罩打码时能裁出形状，
却糊不了形状里面的东西。

取舍先落在「两端能不能是同一个函数」上，因为这条工程的规矩是：给不出同一个函数就不给这个旋钮。
高斯模糊恰好是两端都有原生实现的那一类——FFmpeg 的 `gblur=sigma=`、CSS 的 `filter: blur()`，
而且 CSS 的模糊半径按定义就是标准差。锐化当场被否掉：FFmpeg 的 `unsharp` 用的是窗口卷积
（`luma_size_x` 那套），不是「同一个 sigma 的高斯」，接上就是两个函数共用一个名字。逐帧柔焦也被否掉：
`gblur -h` 显示它的时间线钩子只有 `enable`（开关窗），没有逐帧 sigma，硬做导出是阶梯、预览是平滑。

**先测量，再决定参数。** 用阶跃边沿（左白右黑）取三个交叉点直接反解标准差：50% 在边沿、84.13% 在一个
标准差之前、15.87% 在一个标准差之后。第一版探针画布只有 160×64，σ≥32 时「比值掉到 0.75/0.54」——那是
画布边沿把剖面吃掉了，不是滤波器的性质；把画布放大到 1024×512 后重测，随包的 FFmpeg 在默认
`steps=1` 下标称 1/4/8/16/32/64/128 全部落在 **0.806..0.838 倍**，非常稳；Chromium 的 `blur()` 在
1/4/8/16/32/64/128 上是 **1.196/1.071/0.961/0.977/0.977/0.969/0.969 倍**。也就是说直接把用户填的数
同时喂给两边，成片的实际模糊半径会比分屏里的**锐 19%**。同一个探针扫 `steps`：
`steps=6` 时 FFmpeg 落在 0.954..0.991 倍，正好进到浏览器那一侧的带里。于是导出写
`gblur=sigma=R:steps=6`、预览写 `blur(R×100cqh)`（1cqh = 画面渲染高的 1%，`cqh` 在 `filter:` 里能用
是先在 Chromium 里算过 computed style 才写进方案的），R 由 `contracts.blur_sigma()` 唯一确定。
实测两端相差约 2%（≥8 px 时），以下不到半个像素。

**边界靠拒，不靠夹。** 一致性只在 1..64 px 的实测带里声明；超过就 `BLUR_OUT_OF_RANGE`（422），
`details.max_blur` 直接给出该画幅能承担的比例。界面滑杆的上限不在界面里写死，而是
`blurMaxPercent(caps, 画面高)` 从引擎下发的 `limits.blur_fraction` 与 `limits.blur_radius_limit_px`
取小——`tests/desktop_blur_check.ts` 断言 200/720/1080/2160/4320 五种画幅下给出的上限折算成像素都不超过
64，把 helper 改成只看 fraction 之后该检查立刻红。旧引擎不下发这两个字段时那一行整个不出现。

**加字段会把老回执劈成两半，这次是被变异试出来的。** `_fingerprint` 里原本写着「effects 整份等于
默认就丢掉」，看着像是 1.63 文字那套时代规则的特例，其实是全有或全无：载荷只要设了 `opacity` 就保留
整份 dump，多出来的 `blur: 0.0` 于是进了哈希。第一版 blur_check 只断言「全默认的老载荷仍然命中」，
把 projects.py 换回旧写法后门禁**照样绿**——那条断言测不到真正的坑。改成从删掉 `blur` 字段的同一份代码
里跑出两个锚点摘要（全默认 `550dda4e…`、`opacity=0.5` 的 `e811fc4f…`）再断言之后，才真正咬住：
现在按 1.63 的规则推导「晚于该载荷时代的字段只要还在默认值上就不算请求内容」，两种载荷都命中。

顺带清掉一处 1.63 留下的重复：`ClipPatch.valid_fields` 里 `TextStyle.model_validate` 被写了两遍
（第二次只是把占位 body 换个词），是当时整行编辑合并留下的，删掉一条。

**发布验收抓到的真缺陷：`cut` 快路径根本不知道有柔焦。** 打包后的引擎在 320×180 双轨工程里量到
17.24 px（对），但验收脚本另建了一个**单轨**工程给 `blur=0.25`（70 px，应当被拒），任务却
`succeeded`，成片边沿量到 **0.34 px**——不是拒绝没生效，是模糊压根没进图。查下去：`compile_render_plan`
有两条画面链，`plan.mode == "cut"`（只有一条画面轨、没有任何需要合成的东西）走 `track_chain()`，
那里只拼 `color_filter(clip)` 与 `fit_stage`，逐片段滤镜里只有调色被照顾到；决定走哪条链的谓词把
x/y/scale/rotation/opacity/遮罩/转场/文字/嵌套都列进去了，是一份**手写的名单**，新字段没在里面。
于是预览（每个 DOM 层都吃 CSS `filter`）一直是柔的，导出（快路径）是锐的，而且一声不吭。

修法是把快路径补全，而不是把模糊的工程降级去走慢路径：`fit_stage` 拆成 `fit_pre`（缩放到输出画幅）
与 `fit_post`（转目标像素格式），中间按需插入 `format=rgba,gblur=sigma=R:steps=6`——与分层链同一位置
（缩放之后、转像素格式与遮罩之前），所以两端仍然同一个函数；`blur=0` 时字符串与改动前逐字节相同，
快路径不受任何影响。同一处修改顺带让 70 px 的拒绝在快路径里也真的发生（`blur_clause` 现在两条链都调）。

这条被永久钉住：`tests/blur_check.py` 里新增单轨用例，断言 `plan.mode == "cut"`、断言图里有
`gblur=sigma=18.0000:steps=6`，并且**量出的半径与分层链相差 ≤1 px**（实测两边都是 17.26 px）。
变异验证：把 `stage` 换回 `fit_stage`（即回到缺陷状态）→ 红在
`the cut chain dropped the soft focus: [0:v]scale=320:180:…`，消息直接把丢掉滤镜的那条链打出来。
教训也记下来：给 `ClipEffects` 加字段时，「有没有第二条画面链」不是可以想当然的事——这份名单本身
是架构里的脆弱点，凡靠手写枚举决定行为分叉的地方，新字段都会静默掉出外面。

### 1.64.0 发布验收

冻结引擎 `--verify` 通过后重新打包（`FREEZE=0`、`DIST=0`，产物时间戳确认是这一轮，不是上一版留下的文件——
上一轮的教训：`npm run dist | tail` 把 vite 的失败吞成了 exit 0，盘上的 exe 还是 1.63 的）。

- 包内引擎（实例 `40e39c84617a`）：`app_version=1.64.0`、`frozen=true`、`features.clip_blur=true`、
  `limits.blur_fraction=0.25`、`limits.blur_radius_limit_px=64.0`。
- **成片实测**（320×180，白/黑各半的真实 mp4 素材）：`blur=0.1` 要 18.0 px 半径，交付文件量到
  **17.24 px**；同一片源关掉柔焦量到 **0.34 px**（测量的分辨率）。`preview-manifest` 给界面的是
  `'brightness(1.0) contrast(1.0) saturate(1.0) blur(10cqh)'`，10cqh × 180 px = 18.0 px，与导出侧同一个数。
- **隐私遮罩**：矩形（宽 0.5）圈住中段，遮罩外与「完全不模糊」的成片**逐点相同（0 级差）**，
  遮罩内与「整幅模糊」相同（0 级差）。
- **超出实测带**：另建 320×280 单轨工程给 `blur=0.25`（70 px），提交渲染时 **POST 直接 422**
  `BLUR_OUT_OF_RANGE`，消息写着「blur 0.25 is a 70 px radius at 280 px tall, and the export/preview
  radius match is only verified to 64 px; the most this frame carries is 0.2286」——不是排队后再失败，
  也不是悄悄夹住。这一条正是快路径缺陷的探针：修复前它 `succeeded` 且成片是锐的。
- MCP stdio：`tools/list` 仍 39 个工具（没有新工具，能力在 `timeline_edit` 的 schema 里），生成的
  schema 点名 `blur`。
- `app.asar` 5,535,096 B：`柔焦`、`clip_blur`、`% 高 ·`、`不能打关键帧`、`fx-blur` 全部在包里
  （只用打包后仍然存在的字符串断言）。帮助文案在第一次打包后又改过（把「1%/5%」这类只对低画幅成立的
  说法改成由上限决定的中性描述），于是 renderer 与 asar 重打过一次包——上面所有包内数字与下面的产物
  哈希都是**重打包之后**再跑一遍 `package_check_164.py` 得到的实例 `40e39c84617a`，不是上一份包的残留。
- 界面实机（`ui_blur_164.py`，Playwright Chromium 驱动**构建产物** renderer 对着真引擎）：选中片段后
  出现 `柔焦 | % 高 · ≈0.0 px` 一行，滑杆 `max=25%`＝`min(0.25, 64/180)`——上限来自引擎下发的两个数，
  不是界面自己写的；填 10 回车 → 引擎存下 `blur=0.1` 且**恰好吃掉一个 revision**（r1→r2）；
  浏览器把 `blur(10cqh)` 解析成 **26.8 px**，按 270 px 高的画面应是 27.0 px，差 0.2 px（0.74%，
  即 Blink 三次盒式近似的本征误差，成片侧以 gblur 为准）。截图 `ui164/柔焦界面-040916.png`。这一行跑的
  是第一次 1.64 打包的 renderer，重打包只改了帮助文案，柔焦那一行与上限推导逐字未动。
- 原生窗口：`release/win-unpacked/AgentCut.exe` 用 `Start-Process` 脱离父 shell 启动，`PrintWindow(flags=2)`
  采到 1480×900 的「AgentCut 剪辑台」画面（`AgentCut-1.64-原生窗口.png`，127,145 B），
  `CloseMainWindow` 优雅关闭后 `no AgentCut/agentcut residue`。该会话打开的是用户 `%APPDATA%` 里的真实工程，
  因此只截图与关闭，未编辑任何用户数据。未签名，NSIS 向导未点击验收。
- 产物：便携版 189,738,107 字节 SHA256
  `C86956331B1E854DD50CF5B18B4F461E6C415980176B1BD6EA8297C840FB951E`；安装版 189,898,820 字节 SHA256
  `A1AC20491AA1409BBD0ED02F0D3A01C372C7CC127DE76B704576A4C82E6059FF`；根目录 `AgentCut.exe` 与便携版
  逐字节一致（同一个 SHA256，189,738,107 B）。
- 门禁：`ruff check` 与 `ruff format --check`（86 文件）全绿、`npm run typecheck` 干净、10 项桌面 TS
  检查通过、`tests/self_check.py` 通过，`tests/suite_check.py` 串行 **58/58**（`SUITE=0`；本轮新增的
  `blur_check.py` 与 `nestfx_check.py` 都在列）。打包教训也记一条：`npm run dist | tail` 会把 vite 的
  失败吞成 exit 0，第一次「构建成功」其实是上一版留下的 exe——此后所有构建都写到日志文件里并显式记下
  `EXIT=`，产物 mtime 也一起看。


验收 `tests/blur_check.py`（2.1 秒）：`blur=0.1` 在 180 px 高的画幅上要 18.0 px 的半径，成片边沿剖面
量到 **17.26 px**；关掉柔焦的同一条边沿只量到 **0.34 px**（说明这个测量本身有分辨率，不是噪声）；
过 H.264 之后第 10 帧仍量到 **17.24 px**；矩形遮罩之外与「完全不模糊」逐点相同（**0 级差**）、之内与
「整幅模糊」相同（0 级差），也就是打码真的只糊形状里；编译图里 `gblur` 恰好一次（只糊上面那条轨）；
`preview-manifest` 的 `color_filter` 末尾是 `blur(10cqh)`，折算回像素与 sigma 完全相等，没开柔焦的片段
字符串里没有 `blur`；280 px 高的画幅给 `0.25` 被 `BLUR_OUT_OF_RANGE` 拒；`/v1/capabilities` 报
`features.clip_blur` 与两个 limits。

## 1.65.0 清晰（unsharp mask）：把 1.64 那一次高斯采样反过来用（2026-10-08）

1.64 交付时把锐化列在「不做」里，理由是 FFmpeg 的 `unsharp` 是整数窗口卷积，和浏览器的高斯核对不上。
这轮换个做法：不再找「另一个锐化滤镜」，而是把 1.64 已经实测对齐的那一次 `gblur` 采样反过来用——
`out = clip(src + a·(src − gaussian(src)), 0, 255)`。同一条式子在两端各跑一遍，导出是
`split=2` → `gblur=sigma=R:steps=6:planes=7` → `blend=c0..c2_expr='clip(A+a*(A-B),0,255)'`，
预览是 `<filter>` 里 `feGaussianBlur` + `feComposite operator="arithmetic"`（`k2=1+a, k3=-a`）。
半径仍由 `contracts.spatial_radius()` 一处换算，上限与柔焦共用同一条 1–64 px 实测带。

三条只有实测才能发现的约束，都记进了代码注释：

- `blend` **不做钳位，是按 256 取模回绕**：`255 + 0.8×69` 读回 **54**。所以钳位必须写进表达式里
  `clip(...,0,255)`，而不是指望滤镜兜底；浏览器的 arithmetic 天然钳位，少写一个 `clip` 就是一端亮、
  一端翻成暗色。
- blend 的输出**不能带 pad 标签再接滤镜**：`[x]blend=...[y]tpad=...` 被 lavfi 判成
  「Trailing garbage after a filter」，整条 filtergraph 直接 `Invalid argument`。第一版按「返回
  head + 是否闭合」写的 `chain_join` 因此是多余的，改成让链子始终悬空、由调用方续逗号，
  函数从 `tuple[str, bool]` 收回 `str`，删掉一个只有两个调用点的辅助函数。
- 锐化不能碰 alpha：走到这一步的 alpha 还是均匀的（遮罩 alpha 在之后才乘上去，与预览「先 `filter`
  后 `mask-image`」同序），所以 `gblur` 用 `planes=7`、blend 用 `c3_expr='A'` 就够；这条用「羽化 0.5
  的矩形遮罩下，加与不加锐化的 alpha 斜坡逐点最多差 0 级」钉住，并同时断言形状内部确实变了，
  免得差分量到空气。

验收并入 `tests/blur_check.py`（同一个样片、同一套剖面测量）：`blur=0.1` 先把白|黑硬边铺到
**17.26 px**，再加 `sharpen=2.0`（半径同为 18 px）收到 **9.52 px**——硬边plate上光晕会被钳掉，
所以量的是斜率宽度而不是过冲高度；`cut` 快路径也补了同一条断言（1.64 就是在这条链上静默丢过滤镜）；
`sharpen=2.5` 在契约层 422 且**不烧 revision**；280 px 画幅给 `sharpen_radius=0.25`（70 px）
以 `BLUR_OUT_OF_RANGE` 点名 `sharpen_radius`；预览侧 `bbox` 横竖各折算一次，必须正好等于导出的
sigma；回执锚点再加两条，确认「只写默认值的新键」不会把 1.64 的旧请求劈成两半。

变异验证四处，全部当场红：去掉 `:planes=7` 红在编译图、把 `c3_expr='A'` 换成锐化式子红在
「alpha must be excluded from the blend」、去掉 `clip(` 红在「lost its clamp」、把
`sharpenLimits` 里「像素带 / 画幅高」那一项删掉则 `tests/desktop_blur_check.ts` 红。
第一版 `:planes=7` 的变异用 `perl -i` 改源码时**模式没匹配上**，门禁是绿的——那是一次无效变异，
改用 Edit 工具确认改动落进文件后重跑才真的红；这条教训和「门禁必须能失败」是同一件事。

### 发布验收（1.65.0）

- 冻结引擎：`scripts/build_engine.py` 重新打包（staged 324.9 MB，含随包 ffmpeg/ffprobe），
  `desktop/release/win-unpacked` 与两个产物全部重生成（mtime 同一时刻，避免上一版残留冒充成功）。
- 包内验收 `package_check_165.py`（实例 `00e9d5c28f09`，`/v1/info` 报 `1.65.0`，
  `features.clip_blur` + `features.clip_sharpen` 与四个 limits 全部下发）：交付文件上
  `blur=0.1` 量到 **17.24 px**（对照 0.34 px），再加 `sharpen=2.0`（半径 18 px）收到 **9.75 px**；
  `preview-manifest` 给出 `shf05a35265c9c`，`bbox` 折算 **18.0 × 18.0 px** 与导出的 sigma 相等；
  羽化遮罩下锐化让 alpha 斜坡动 **0 级**、形状内部动 **44 级**；`sharpen=2.5` 422 且 revision 不动；
  280 px 画幅的 70 px 半径两条都点名拒绝（`blur` 与 `sharpen_radius`）；MCP stdio 39 个工具，
  `timeline_edit` 的 schema 点名 `blur`/`sharpen`/`sharpen_radius`；`app.asar` 5,537,513 B 里
  两行中文与 `fx-sharpen` / `fx-sharpen-radius` 的 id 都在。
- 界面验收 `ui_sharpen_165.py`（Playwright 驱动构建后的 renderer）：两行的上限是引擎给的
  （amount 200% = `sharpen_amount`，radius 25.00% = min(25%, 64px/180px)），敲进去两次 Enter 落成
  两个 revision、`sharpen=1.5` / `sharpen_radius=0.1`；DOM 里 `feGaussianBlur` 的
  `stdDeviation='0.05625 0.1'` 在 480×270 的预览框上解析成 **27.0 × 27.0 px**，即画面高的 10%，
  与导出向 180 px 画幅要的 10%（18.0 px）是同一个比例——顺带把「objectBoundingBox 单位下横竖必须
  各算一次、不然核就是椭的」这条钉住（新增的各向同性断言 ±0.5 px）。
- 原生窗口：`release/win-unpacked/AgentCut.exe` 用 `Start-Process` 脱离父 shell 启动，
  `PrintWindow(flags=2)` 采到 1480×900 的「AgentCut 剪辑台」，标题栏右侧写着 **引擎在线 v1.65.0**
  （`AgentCut-1.65-原生窗口.png`），`CloseMainWindow` 优雅关闭后 `no AgentCut/agentcut residue`。
  该会话打开的是用户 `%APPDATA%` 里的真实工程，只截图与关闭，未编辑任何用户数据。未签名，
  NSIS 向导未点击验收。
- 产物：便携版 189,741,176 字节 SHA256
  `93F2BEA48157A5C5C0CB840CBA63BA02FE9B08D9544AE0E4CE9C3DDA7195012F`；安装版 189,901,889 字节
  SHA256 `8A3270AF12D2F4B7F53D8FD27CE625F7C2CAD815EF896DE2EE04C14471BE31BB`。
- 门禁：`ruff check` 与 `ruff format --check`（86 文件）全绿、`npm run typecheck` 干净、10 项桌面 TS
  检查通过、`tests/self_check.py` 通过，`tests/suite_check.py` 串行 **58/58**（`SUITE=0`）。
  本轮被门禁抓到的一次真回归：把 `format=rgba` 无条件塞进 `cut` 快路径，会让每个片段的采样格式链多一段
  `format=rgba`，`tests/format_check.py` 当场红在 ProRes 的
  `setsar=1,fps=30/1,format=yuv444p10le`；改成「只有 blur 或 sharpen 真的开着才转 rgba」，
  两个旋钮都关着时输出串与 1.64 逐字节相同。另记一次流程教训：第一次串行套件是在编辑源码的同时跑的，
  `speedramp_check` 的像素断言被读到半改状态而假红——跑套件期间不再动源码。

## 1.66.0 画面稳定：量出相机在动多少，再把反过来的那点位移写回工程（2026-10-08）

剪映的「平滑」是它的招牌之一，而它在这一层真正可复制的不是 warp，而是那个问题——「这一段画面里，哪些运动是相机造成的」。项目里已经有按归一化互相关跟遮罩的跟踪器（`tracking.track_box`），所以这一轮不引入新依赖：把同一个跟踪器从「跟主体」改成「跟画面」，锚点放在四角内缩处（0.27/0.73），取四个锚点位移的**中位数**。为什么不是均值也不是单点：一个走过画面的主体会把单个锚点带跑，而相机是四个锚点都同意的那个运动。

写入仍是 `keyframes.replace` 的 `x`/`y`/`scale`——与手打关键帧同一条路，所以一个 revision、一份回执、一步撤销，预览与导出天然同曲线，不需要第二个近似。分析需要读媒体，因此入口和 `/track`、`/reframe` 同类（HTTP + MCP 工具 `clip_stabilize`），但**只有引擎能做分析**，写工程仍走同一条事务。

四条只有实测才知道的边界：

- **抵消的是「测到的 − 平滑的」，不是「测到的 − 0」**。把画面钉死在第一帧不是稳定，是冻屏。第一版把滑动窗口半径按 `strength` 缩放，2 秒片段上 30 帧的窗口直接把 20 px/s 的推拉吃掉一截；改成窗口固定为 `min(30, 片段帧数/4)`、`strength` 只缩放**抵消多少**，滑杆两端才各自可解释（0 = 原样，1 = 全抵消）。
- **缩放必须盖住边**：合成器先以画面中心缩放再平移，层仍铺满的条件是 `|x| ≤ (scale−1)/2`，于是缩放取 `1 + 2·最大抵消`，`max_crop` 是它的上限，超出就夹住并在 `clamped_axes`/`warning` 里说还剩多少没抵消。
- **关键帧密度是能力边界**：每帧交替的抖动不可能用 48 个点在 59 帧上抵消——线性插值在跳变之间只会给出错的中间值（实测：48 点时成片抖动 6.4 px，一帧一点后 1.4 px）。所以一帧一个点，上限 `min(240, 片段关键帧预算/3)`。
- **图太长会撑爆命令行**：59 帧 × 3 条曲线的 `if(lt(t,…))` 让 `-filter_complex` 超过 Windows `CreateProcess` 上限（WinError 206「文件名或扩展名太长」）。`RenderPlan.graph_argument()` 在图超过 12 KB 时改走 `-filter_complex_script filtergraph.txt`，`ffmpeg_argv` 与 `frame_argv` 都走这条路；文件仍由 `plan.text_files` 交付，因此**调用方必须先取 argv 再落盘**——决定「要不要走文件」的正是取 argv 这一步（门禁里就先踩了一次：先写文件后取 argv，FFmpeg 报「Error opening file filtergraph.txt」）。

验收 `tests/stabilize_check.py`：样片的裁剪窗口位置是 `t` 的闭式函数（20 px/s 平移 + 每帧 ±8 px 抖动），跟踪还原与写下来的真值最多差 **2.0 px**（分析分辨率本身就是 2.5 px/像素），逐帧符号必须相反；**成片**再量一次，抖动 **11.2 px → 1.4 px**；只有平移没有抖动的第二条样片稳定后保留 **75%** 行程；`strength=0` 一个关键帧都不写、`0.5` 的抵消量正好是一半；音频轨片段、200% 变速、`max_crop=0`、指向不存在的片段、`strength=4` 全部按名字拒绝且不动 revision；`dry_run` 一个字节都不写；同 id 同载荷命中回执、同 id 换载荷被拒。

两条「门禁必须能失败」的教训，都在这轮现场抓到并重做：

- 第一条按像素检查「边上有没有露黑」的写法，把 `zoom` 从 `1+2·最大抵消` 改成 `1.0` 之后**仍然是绿的**——稳定片段下面还压着别的片段，边黑被盖住了。改成直接断言合成器的覆盖不变量（`scale ≥ 1+2·residual` 且每个写入的 `|x|`、`|y|` 不超过 `(scale−1)/2`）后，同一个变异当场红。
- 测量样片第一版是「每像素随机噪声」：H.264 把高频量化掉了，每个块回来时灰度都不一样，跟踪器忠实地把编码噪声当成画面跟——量到的偏移与真值差 0.16 画面宽。换成 24 px 方块 + 圆片的结构板之后，误差落到 2 px。样片说谎时会造出一个并不存在的引擎缺陷，这条与「样片不许说谎」是同一件事。

### 发布验收（1.66.0）

- 冻结引擎：`scripts/build_engine.py` 重新打包（staged 324.9 MB），`desktop/release/win-unpacked` 与两个
  产物全部重生成（mtime 07:38，与上一轮 07:17 的产物不同尺寸，避免旧文件冒充成功）。第一次 `npm run dist`
  以 `EPERM: unlink …/agentcut.exe` 失败——上一轮包内验收留下的三个引擎子进程还占着文件；按 PID
  `Get-CimInstance` 查出来杀掉再重建才通过（`DIST=1` 是被日志记下来的，没有当成成功）。
- 包内验收 `package_check_166.py`（实例 `3ae892b4faae`，`/v1/info` 报 `1.66.0`，
  `features.clip_stabilize` + 两个 limits 下发）：样片抖动 **11.2 px**，`dry_run` 计划 59 个点而
  工程头不动；正式写入 `{'x': 59, 'y': 59, 'scale': 2}`、translation_correction 0.02124、zoom 1.0425；
  **用随包的 FFmpeg 复检交付文件**，抖动降到 **1.5 px**；指向不存在的片段回 `NOT_FOUND` 而不是 500；
  MCP stdio 40 个工具，`clip_stabilize` 的 schema 点名 `strength` 与 `max_crop`；
  `app.asar` 5,540,884 B 带着「画面稳定」按钮、两个输入框与能力门控。
- 界面验收 `ui_stabilize_166.py`（Playwright 驱动构建后的 renderer）：按钮在「变换与动画」里
  （第一版误放在「遮罩」小节且被 `animatable` 门控，无遮罩的片段根本看不到——UI 走查时发现并搬了出来），
  默认 强度 100% / 允许裁切 10%，输入框上限就是引擎下发的 `stabilize_max_crop`（25%）；
  点一次落成**恰好一个 revision**（1 → 2），写入 59+59+2 条关键帧，最大位移 0.0212 画面宽；
  预览清单里 `curves.x` 有 61 个点、首点与存进去的首条关键帧逐位相同。
  （不断言 computed transform：隐藏标签页里 rAF 不跑，那样等于宣称了一个浏览器根本没画的帧。）
- 原生窗口：`release/win-unpacked/AgentCut.exe` 用 `Start-Process` 脱离父 shell 启动，
  `PrintWindow(flags=2)` 采到 1480×900 的「AgentCut 剪辑台」，标题栏右侧写着 **引擎在线 v1.66.0**
  （`AgentCut-1.66-原生窗口.png`），`CloseMainWindow` 优雅关闭后 `no AgentCut/agentcut residue`。
  该会话打开的是用户 `%APPDATA%` 里的真实工程，只截图与关闭，未编辑任何用户数据。未签名，
  NSIS 向导未点击验收。
- 产物：便携版 189,751,716 字节 SHA256
  `301FD17065C67C99F2C29317C63EB3CEC601DDAB0C07FC52A109041401E52246`；安装版 189,912,432 字节
  SHA256 `9B3779EBEC1AE4E0E80E1543A8A5778DCC296758CC0DA79973A57B719112ACA6`。
- 门禁：`ruff check` 与 `ruff format --check` 全绿、`npm run typecheck` 干净、10 项桌面 TS 检查通过、
  `tests/self_check.py` 通过（含 MCP 工具集里点名 `clip_stabilize`），`tests/suite_check.py` 串行
  **59/59**（`SUITE=0`）。本轮被门禁抓到两件事：把「要不要走脚本文件」的决定放在 `ffmpeg_argv()` 里，
  会让先写 `text_files` 的调用方拿到一个不存在的文件（`tracking_check` 当场红在
  「Error opening file filtergraph.txt」），改到编译期决定并拆成渲染/取帧两个文件；以及嵌套合成会把
  子合成的 `filtergraph.txt` 覆盖到父工程同名文件上，合并时按名字跳过。

## 1.67.0 画面稳定补上旋转：一次测量，两个自由度（2026-10-08）

1.66 交付时我在提交说明里写下「只治平移」，这就是这一轮的活：手持画面的难受有一半来自滚（roll），
只把画面钉平而不把水平线钉平，看上去仍然是晃。做法上没有引入第二个跟踪器——四个锚点已经在了，
把它们相对第一帧做一次 Arun 刚体拟合（去质心后 `atan2(Σ p×q, Σ p·q)`）就多出一个角度，
与平移共用同一个滑动窗口、同一个 `strength`、同一条 `keyframes.replace` 写入路径。

一条只有做出来才会知道的边界：**测量分辨不出的旋转不能写**。锚点基线 ~300 px、位移量化到整像素，
一个像素就是 0.19°；第一版没有死区，纯平移的样片量到 ±0.2° 的「滚动」，于是也被写上一条旋转曲线，
`tests/stabilize_check.py` 里那条「20 px/s 的推拉必须活下来」从 75% 掉到 69%。加了 0.25° 死区
（低于它 `roll_correction = 0`、一条旋转关键帧都不写）之后回到 75%。这不是把阈值放松，
是把「这个测量分辨不出来」写进代码：分辨不出来就不要假装纠正了。

缩放随之多一项：把 `w×h` 的层转 θ 后要不露边，高度方向至少 `1 + θ·(w/h)`（θ 弧度），
与平移项相加而不是取大（两者可以同时最坏）。

样片也要讲实话：图版原来只比画幅大 80/60 px，转 1° 就会把旋转后露出的黑角送进裁剪窗口，
量到的就不是相机的转而是图版的边——把图版放大到 900×560（裁剪窗口离图版边 ≥96/80 px）之后，
第三条样片（每帧在 ±0.5° 之间来回转，相对第一帧满摆幅 2°）量到 **2.47°**，
写进去的旋转在最大偏转那一帧与测量反向，**导出成片再量一次旋转抖动 1.58° → 0.17°**。
平移与旋转两条样片共用同一个门禁文件，跑一次就把两个自由度都验了。

### 发布验收（1.67.0）

- 冻结引擎：`scripts/build_engine.py` 必须在改过 `stabilize.py` 之后再跑一次——第一次 1.67 的
  `npm run dist` 只重打了 asar，把 00:57 冻结的旧引擎（还没有 `roll_correction` 这些键）原样装进包里，
  包内验收当场 `KeyError: 'roll_correction'`。重冻结 + 重打包（产物 mtime 09:10）才通过。
- 包内验收 `package_check_167.py`（实例 `c0faefd6272f`，`/v1/info` 报 `1.67.0`）：交付的抖动文件仍是 **11.2 px → 1.5 px**；新加的第三条样片
  （图版每帧在 ±0.5° 之间来回转）在包内量到 **+0.95°**（相对第一帧，真值满摆幅 1°），
  **它导出的文件滚动 0.00° 而不是 0.65°**；MCP stdio 40 个工具、`clip_stabilize` 的 schema 点名
  `strength`/`max_crop`；`app.asar` 5,541,131 B 带着「转了多少」这句新说明。
- 契约表面改名：1.66 的 `residual_after` 名字说的是「剩下多少」，值却是「抵消掉了多少」，
  包内验收第一次按字面理解去断言就撞上了。改成 `translation_correction` / `roll_correction`，
  界面提示、README、api、门禁同步；这不是美化措辞，是一个会误导 Agent 的字段名。
- 原生窗口：`release/win-unpacked/AgentCut.exe` 启动后 `PrintWindow(flags=2)` 采到 1480×900 的
  「AgentCut 剪辑台」，标题栏写「引擎在线 v1.67.0」（`AgentCut-1.67-原生窗口.png`），
  优雅关闭后 `no AgentCut/agentcut residue`。该会话读的是用户 `%APPDATA%` 的真实工程，只截图与关闭。
- 产物：便携版 189,753,404 字节 SHA256
  `94B2C6EB74FAF804AE5D08F8E5F760F1E17A2C6F1329B8B0B726CCAAD1F4B415`；安装版 189,914,115 字节
  SHA256 `188E3D5A0FA4AA7688BBF830682E6B2CEFE729FC28512CD4C8F1A6E0D3FA4613`。
- 门禁：`ruff check` / `ruff format --check`、`npm run typecheck`、10 项桌面 TS、`tests/self_check.py`
  全绿，`tests/suite_check.py` 串行 **59/59**（`SUITE=0`）。

## 1.68.0 二次稳定点名拒绝：把静默出错变成命名的拒绝（2026-10-08）

- 触发方式是组合测试而不是单功能测试：把 1.66 与 1.67 的命令对同一片段连着跑两遍，第二次仍返回
  200、revision 照涨（把守卫摘掉的变异跑出实测：revision 3 → 4，回包里的关键帧数量与第一次一样正常），
  而工程里这时叠着两份同一次测量的抵消——同一份抖动被减了两遍，画面朝反方向偏。单功能的门禁看不见
  这件事，因为每条门禁只按一次。
- 根因是这条命令的语义：抵消**叠在片段已有的 `x`/`y`/`rotation`/`scale` 上**（这样手打运镜不会被
  稳定吃掉），而第二次读的还是同一段源画面。落到工程里，引擎上一次写的曲线和用户手打的完全一样，
  历史快照不能当命令的状态用，所以没有「认出自己是上次写的」这条路。
- 选拒绝而不是选「替换」：替换会把手打的曲线静默清掉，那是另一种丢数据；把输入变成
  `STABILIZE_CONFLICT`（422，`details.properties` 点名曲线，消息给出撤销 / `project_restore` /
  清掉那三条三条走得通的出路）代价只是一次重试，收益是不会再产出错的画面。载荷、命令、
  `capabilities` 都没长（`features.clip_stabilize` 仍是一个开关），MCP 工具描述同步改成
  「按一次；再按会被点名拒绝，出路是……」。
- 界面守同一条判断：`desktop/src/effects.ts` 里新增 `stabilizeBlocked(clip)`，Inspector 用它把
  「画面稳定」按钮灰掉并把同一句话放进 `title`——人点下去不会拿到另一套说法。顺带把这四个拒绝补成
  中文提示（`STABILIZE_INVALID`/`STABILIZE_FAILED`/`STABILIZE_CONFLICT`/`BLUR_OUT_OF_RANGE`）：
  此前弹的是引擎英文原文，在人眼里像程序内部错误；`describe()`/`explain()` 这套映射本来就是
  「拒绝必须给出走得通的出路」的地方。
- 门禁：`tests/stabilize_check.py` 用同一 `request_id` 以同载荷与换载荷两种方式各撞一次，两次都要
  422 `STABILIZE_CONFLICT` 且 revision 与该片段关键帧列表一字不差（1.67 之前这里断的是「同载荷命中
  回执」，那次改动让这条断言变成了假话——回执键的是**派生出来的命令**，二次运行的命令与第一次并不
  相同，所以真正的行为是拒绝；改断言就是改文档）。变异（守卫里 `keyed = []`）红在新增的 422 断言上，
  且回包显示第二次运行确实把 revision 从 3 抬到了 4。
- 新增 `tests/desktop_stabilize_check.ts`（不依赖浏览器，直接驱动 `stabilizeBlocked`）：干净片段
  放行；变速曲线与 200% 速度给同一句带「100%」的说法；已经K过 `scale` 必须点名「缩放」并给出路；
  `mask_x` 与 `opacity` **不许**挡路（稳定不碰这两条）。变异（`STABILIZED` 里删掉 `scale`）红在
  「必须点名曲线」上。桌面 TS 检查从 10 项变 11 项，`tests/desktop_ts_check.py` 按
  `desktop_*_check.ts` 通配自动发现，无需登记。

### 发布验收（1.68.0）

- 先 `scripts/build_engine.py` 重新冻结（改了 `stabilize.py`/`mcp_server.py`/`contracts.py`），再
  `npm run dist`；`DIST=0`。包内引擎实例 `3996f7a80c3b` 的 `/v1/info` 报 `app_version=1.68.0`。
- 包内 HTTP 实测（`package_check_168.py`，只用包里的 FFmpeg 现做样片，不 import 仓库源码）：第一次
  按写 59 点/曲线（`x`/`y`/`scale`）、zoom 1.042；随后三种二次运行——新 request_id 同载荷、同 id
  同载荷、同 id 换 `strength=0.5`——全部 422 `STABILIZE_CONFLICT`，`details.properties` 点名
  `x`/`y`/`scale`，回读的工程 revision 与关键帧列表与第一次写完时一字不差。
- 拒绝消息里给的出路在同一个包里走得通：`POST /restore` 回到稳定前的 revision 生成新 revision、
  关键帧清空，再按一次成功写入（r4，59 点）。
- 包内 MCP `tools/list` 的 `clip_stabilize` 文本含 `STABILIZE_CONFLICT`（Agent 读到的就是这句话），
  包内 `app.asar` 里能搜到 `画面稳定`、`再抵消一遍`、`撤销这一步`、`stabilize-row`（按类名与界面
  文字断言，不按会被打包改名的标识符断言）。
- 构建后的渲染器界面走查（`ui_stabilize_168.py`，引擎实例 `3438bfa07eef`）：干净片段上按钮实测
  62×22 px、可点、title 说明这次按下去会发生什么；写完之后同一个按钮 `disabled`，title 是中文的
  「这段画面已经K了位置 X、位置 Y、缩放：稳定会把同一段抖动再抵消一遍……撤销这一步，或在曲线编辑器
  里清掉这几条，再按一次。」；按 Ctrl+Z 撤销清掉 120 个点（r2 → r3）后按钮恢复可点，把强度改成 50
  再按，落地的最大位移 0.01062 对 100% 的 0.02124——正好一半，拒绝只花一次撤销，没有把功能一起拿掉。
- 截图里发现并修掉的交付缺陷：`.stabilize-row` 原本没有任何样式，「强度 50」后面的 `%` 被挤到下一行，
  读起来像「%允许裁切」这个不存在的字段。补上 `display:flex` + 标签 `white-space:nowrap` 后同一行
  不再断开；这条断言按实时矩形量（单位与数字框在同一行、且落在数字框右侧），把三条规则删掉重新构建
  后界面走查当场失败（`the unit fell onto its own line`），装上规则才通过。
- 门禁：`ruff check` / `ruff format --check`、`npm run typecheck`、11 项桌面 TS、`tests/self_check.py`
  全绿，`tests/suite_check.py` 串行 **59/59**（`SUITE=0`）。
- `release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，标题栏「引擎在线 v1.68.0」
  （`AgentCut-1.68-原生窗口.png`），关闭后 `Get-Process` 查不到 AgentCut/agentcut 残留。便携版
  189,754,039 字节 SHA256 `1BC22F0DB3B0FA8BEADD0271030736AE823AB465D1980A9E76ED16A77C1DC847`；
  安装版 189,914,753 字节 SHA256 `90C65B049EBF1F370F14FA2AAE52E666E5A64146189A21D538D9AF8C349AB9E2`。
  没有自有代码签名证书（打包器只对随包 exe 走默认流程），NSIS 向导未做点击验收。

## 1.69.0 稳定成为片段的状态：再按一次是换一档，不是叠一层（2026-10-08）

- 起点是 1.68 的拒绝换来的一个不好用的流程：想换个强度得先撤销。组合扫查又抓到同一件事的**镜像洞**——
  1.66 写入时拒绝给 200% 变速的片段做稳定，但**稳定完之后**再改速度没人管，抵消会在错的速率下播放：
  危险一模一样，只是从另一扇门走进来（实测：稳定过的片段把速度改成 200% 照样 200，59 个点原样留着，
  时长减半，于是抵消按一半的速率播放）。
- 两件事同一个解：把「这四条曲线是谁写的」变成工程里的状态。`Clip.stabilization`
  （strength / max_crop / points / translation_correction / roll_correction / zoom_to_hide_borders /
  analysed_frames）与 `keyframes.replace` 在同一条批次里落库，所以不存在「曲线清掉了但还说着已稳定」
  的中间态。可选字段带默认 `None`，旧工程读进来就是没有稳定，`SCHEMA_VERSION` 不动（1.64 的
  `effects.blur` 同理）。新命令 `clip.stabilize_record` 的 `record: null` 就是清除；它不需要额外授权：
  它能声称的只是「这四条曲线属于稳定」，而那四条曲线本来就可以手写。
- 有了记录，抵消的基准从「当前曲线」换成「片段的静态变换」：同强度再按一遍逐点一字不差，换强度就是
  换一档，1.0 → 0.5 → 1.0 回到同一批数字；回执也因此重新命中（1.68 那句「同 id 同载荷命中回执」
  对这个路由本来是假的，现在是），强度 0 在带记录的片段上就是「取消稳定」，把写过的点连记录一起清掉。
- 没有记录又已经K过这四条的片段仍然 `STABILIZE_CONFLICT`：引擎没有任何依据说那是它自己写的。
  带记录的片段不允许再改速度（`STABILIZE_LOCKED`，`clip.speed` 与 `clip.speed_curve` 两扇门一起关）；
  取消稳定之后同一句命令就通过——门禁把这条 named exit 从头走到尾。
- 界面：`stabilizeBlocked()` 只在**没有**记录时因曲线挡路（速度那条规则仍然优先），稳定过的片段这一行
  写明「已稳定 · 强度 …· 抵消 …· N 个点」，按钮变成「重新稳定」，旁边多一个「取消稳定」。
- 顺手抓到门禁自己的一个假绿，值得单独记：1.68 为了让强度 0.5 与 `max_crop=0` 各用一条干净片段，加了
  `again`/`tightclip` 两条辅助片段，位置在 `[0, 2s]`，而它们挂在 h1/h2 上——**后加的轨在画面上方**。
  成片抖动断言量的是合成后的那一帧，于是从 1.68 起它量的是辅助片段的画面（11.2 px → 3.1 px，
  数字看着仍然「变好了」，门禁全绿，而 1.66/1.67 的真数是 1.4 px）。把辅助片段挪出被量的窗口、
  并给每次成片测量加上 `topmost()` 守卫（被量窗口最上面必须就是被测片段）之后，回到
  **11.2 px → 1.4 px**、滚动 0.18°。这是「门禁必须能失败」的又一次现场版：断言写的是意图
  （「我在量这条片段」）而不是被量的东西本身，就会绿得毫无意义。

### 发布验收（1.69.0）

- `scripts/build_engine.py` 先重冻结（`FREEZE=0`，staged 324.9 MB），再 `npm run dist`（`DIST=0`）。
  包内引擎实例 `fd7018368532` 的 `/v1/info` 报 `app_version=1.69.0`，`capabilities.commands` 与
  `/openapi.json` 都点名 `clip.stabilize_record`。
- 包内 HTTP 实测（`package_check_169.py`，只用包里的 FFmpeg 现做样片，不 import 仓库源码）：第一次按
  r0→r1 写 59 点/曲线、zoom 1.042、抵消 0.02124，片段上多出与回复逐字相同的记录；再按一次（新
  request_id）曲线逐点一字不差；改成 50% 落 0.01062（正好一半）；再回 100% 又是原来那批数字——
  全程没有撤销。带记录期间 `clip.speed=200` 与 `clip.speed_curve` 都是 422 `STABILIZE_LOCKED` 且
  head 不动；强度 0 一次清掉 120 个点与记录，之后同一句改速度就通过。
- 包内 MCP 文本同时点名 `STABILIZE_CONFLICT`、`STABILIZE_LOCKED` 与 `clip.stabilize_record`；
  `app.asar` 里搜得到「重新稳定」「取消稳定」「已稳定」与类名 `stabilize-state`。
- 构建后的渲染器界面走查（`ui_stabilize_169.py`，实例 `9ad65d123606`）：干净片段按钮 62 px 宽、写着
  「画面稳定」；按完这一行变成「已稳定 · 强度 100% · 抵消 0.021 画面宽 · 59 个点」，按钮改叫
  「重新稳定」并多出「取消稳定」；把强度填成 50 再按，**不撤销**，落地的最大位移 0.01062 对 100% 的
  0.02124，行里同步显示 50%；点「取消稳定」清掉全部点与记录（r4），那一行回到光秃秃的「画面稳定」。
  截图 `稳定一次点击-114315.png`。
- 门禁抓到一处真回归，值得记：`Clip` 多了可选字段 `stabilization` 之后，`clip.add` 的载荷在
  `model_dump` 里多出这个键，回执指纹随之改变——`tests/blur_check.py` 里那组「1.64 之前捕获的摘要
  原样命中」的锚点当场红（`digest(legacy) == digest(None)`），`editing`/`mask` 同一批锚点也红。
  修法是把它交给 `_fingerprint` 既有的「时代」归一化：值为默认的 `stabilization` 不进哈希（老客户端
  重发老请求仍然命中自己的回执），同时三个门禁的夹具按既有约定把新字段一并剥掉。这不是测试的洁癖：
  不修，1.68 写的每一条 `clip.add` 回执在升级后重放都会变成 `IDEMPOTENCY_CONFLICT`。
- `ruff check` / `ruff format --check`、`npm run typecheck`、11 项桌面 TS 全绿，
  `tests/suite_check.py` 串行 **59/59**（`SUITE=0`）。
- `release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，标题栏「引擎在线 v1.69.0」
  （`AgentCut-1.69-原生窗口.png`），关闭后 `Get-Process` 查不到残留。便携版 189,757,758 字节
  SHA256 `41B0CBD7BE81EC7B03A985C64AF77FD256B57666FBCAC33A42AFA9DB97FE56F9`；安装版 189,918,479
  字节 SHA256 `133FBF1741F04BF8DD475FAED6104A53C28D244D0F36F26C06888600DCD985F8`。没有自有代码签名
  证书，NSIS 向导未做点击验收。

## 1.70.0 稳定与重构图不能同时拥有同三条曲线（2026-10-08）

- 找缺陷的方法还是组合，而不是单功能：1.69 给稳定加了记录之后，「谁拥有 `x`/`y`/`scale`」第一次成了
  可以问的问题。一问就撞上主体跟随重构图——它写的正是这三条，而且是整条改写。先稳定再重构图，
  稳定被静默删掉，片段上那条记录还留着：界面写着「已稳定 · 强度 100%」，导出里已经没有抵消，
  速度锁还在为一件不存在的事挡路。
- 修法是一句守卫（`reframe_plan` 见到 `Clip.stabilization` 就 `STABILIZE_LOCKED`），不是新功能：
  反方向（先重构图再稳定）1.68 的守卫本来就管住了，因为重构图留下的曲线没有记录。界面同一条判断
  把「主体跟随重构图」灰掉，`title` 给的是引擎那句话；`STABILIZE_LOCKED` 的中文提示改成同时说清
  变速与重构图两件事。
- 门禁先红后绿：`tests/reframe_check.py` 计划层与 HTTP 层各一条断言，在守卫落地之前跑是红的
  （红的输出就是缺陷的实证），加上守卫之后绿。HTTP 层还要把记录清掉再请求一次，证明消息里说的出路
  真的走得通。
- 顺带记一条流程：在既有 HTTP 门禁中间插入两次会提交的编辑，必须把局部 `revision` 一起推进——
  后面「planning 不写盘」那条断言拿的是旧 head，第一次跑就红在那儿。

### 发布验收（1.70.0）

- `scripts/build_engine.py` 先重冻结（`FREEZE=0`），再 `npm run dist`（`DIST=0`）。包内实例
  `1250e6f6b4b7` 的 `/v1/info` 报 `app_version=1.70.0`，`capabilities` 同时开着
  `clip_stabilize` 与 `subject_reframe`。
- 包内 HTTP 实测（`package_check_170.py`，只用包里的 FFmpeg 与 HTTP）：没有稳定记录时重构图答的是它
  自己的理由（这条片段没有跟好的遮罩路径）`INVALID_REFRAME`；按一次稳定（59 点/曲线 + 记录）之后
  同一条重构图请求 422 `STABILIZE_LOCKED`，回读的工程 revision 一字未动；用
  `clip.stabilize_record` 把记录清掉，同一句请求又回到 `INVALID_REFRAME`——锁确实是唯一挡路的，
  消息里说的出路真的走得通。
- 包内 MCP 文本同时点名 `clip.reframe` 与 `STABILIZE_LOCKED`；`app.asar` 里搜得到
  「主体跟随重构图」「会把稳定悄悄抹掉」「先「取消稳定」，再重构图」（按界面文字与类名断言，
  不按会被打包改名的标识符断言）。
- 门禁：`ruff check` / `ruff format --check`、`npm run typecheck`、11 项桌面 TS 全绿，
  `tests/suite_check.py` 串行 **59/59**（`SUITE=0`）；`tests/reframe_check.py` 计划层与 HTTP 层两条
  新断言在守卫落地前先跑为红（红的输出即缺陷实证），加守卫后为绿。
- `release/win-unpacked/AgentCut.exe` 启动到「AgentCut 剪辑台」1480×900，标题栏「引擎在线 v1.70.0」
  （`AgentCut-1.70-原生窗口.png`），关闭后无残留进程。便携版 189,757,895 字节
  SHA256 `987093A74BD378FDA90098FBF25D525E4060D7AFF368B4C4D431FF2F348F5C5D`；安装版 189,918,614
  字节 SHA256 `2B7D8791783E8E6EE01B5C55F2906070C2D52A42B01340B35FCDDCA1D1D31480`。没有自有代码签名
  证书，NSIS 向导未做点击验收。

## 1.71.0 记录随曲线一起作废（2026-10-08）

- 1.70 之后那条记录开始管事（挡住变速与重构图），于是它必须真话。普通关键帧命令能把它描述的曲线删掉
  而记录不动：片段仍写着「已稳定 · 强度 100%」，画面里一条抵消都没有，变速与重构图还在为一件不存在
  的事被拒。`apply_commands` 的收尾（与路径遮罩补框、转场修复同一处）统一修：记录还在而
  `x`/`y`/`rotation`/`scale` 一条不剩时置空。只在「一条不剩」这一种情况下动手——分割出的两半各自
  留着窗口内的曲线、删掉个别点还剩别的，宁可留着一条不完美的说法也不误删仍然成立的成果。
- 门禁先红后绿：`tests/stabilize_check.py` 里把 `again` 的四条曲线用 `keyframes.remove` 全删空，断言
  `stabilization is null` 且随后 `clip.speed=200` 必须通过；收尾落地前红在
  `the record outlived the curves it described`。
- 一次连带修正：1.70 给 `tests/reframe_check.py` 加的 HTTP 用例只挂了记录没挂曲线，正是 1.71 不再
  允许的状态，于是它被收尾清掉、断言转红。补上一条 `x` 关键帧让夹具像一次真的稳定，收尾之后再按
  `keyframes.remove` 把它取回——夹具本身也要讲实话。
- 发布验收：`build_engine.py` 重冻结（`FREEZE=0`）后 `npm run dist`（`DIST=0`）。包内实例
  `c8d103fd788e` 报 1.71.0：稳定后的片段带着 120 条曲线时改速度 422 `STABILIZE_LOCKED`；用
  `keyframes.remove` 删空之后回读 `stabilization` 为空、同一句改速度 200 通过；再稳定一次然后只删
  一个点，记录仍在——收尾没有越权。`ruff`、`npm run typecheck`、11 项桌面 TS、串行套件
  **59/59**（`SUITE=0`）全绿。便携版 189,758,652 字节 SHA256
  `10E03D842B1CA426C2F9680006F4C674CB7181831DDB385BA4B5235B62EFBE04`；安装版 189,919,369 字节
  SHA256 `7DFCB8D0110CD6CE6188FAFC04EC9AC1E8D648758A67C091487CD7610DA5F40E`。
  另记一句实话：1.70 那节的截图文件名 `AgentCut-1.70-原生窗口.png` 在本轮被一次误跑（跑成了 170 的
  脚本）覆盖成了 1.71 的构建，1.70 的像素证据以当轮日志与哈希为准；1.71 的截图另存为
  `AgentCut-1.71-原生窗口.png`。

## 1.72.0 遮罩跟踪可以接着跟（2026-10-08）

- 缺陷：`clip.mask_track` 把这条遮罩的全部关键帧删掉再写本次窗口的点。于是「跟到一半跟丢，把遮罩
  拖回主体上从这一帧接着跟」这个再自然不过的动作，实际是把前面跟好的路径整条抹掉，遮罩在片段开头
  跳回画好的位置——静默删数据。`from_ticks` 早就有，缺的是写入端的窗口意识。
- 修法：`MaskTrackRequest` 与 `clip.mask_track` 都带 `merge`（默认开）。合并只删本次 tick 区间内的
  点，区间外原样保留；遮罩静态盒取**整条路径最早那一帧**的值（不是最后一次运行的起点），否则播放头
  之前的帧会退回一个刚被搬走的位置。`merge=false` 保留旧语义，界面上就是「从头重跟」。
- 回复里加四个实测数：`kept_frames`/`replaced_frames`（按帧算，尺寸估计开着时每帧 2–4 条曲线）、
  `seam_ticks`、`seam_jump`（两段在接缝处差多少画面宽）。接缝不为零就是真实的不连续，说出来而不是
  用一条直线悄悄连过去。
- 界面：同一个按钮在已有路径的片段上写着「接着跟」（从播放头起，merge 开），旁边多一个「从头重跟」；
  提示语报「保住前面 N 帧的路径，只重写这一段（接缝处差 X 画面宽）」。
- 门禁先红后绿：reducer 层断言 merge 保住窗口外的点、`merge=false` 仍整条替换；HTTP 层跟 40 帧，
  把遮罩盒挪到主体在第 20 帧的真实位置（就是界面上那个动作），再 merge 跟 20 帧，断言 40 个 tick
  一个不缺、`kept_frames=20`、`seam_ticks` 一帧、`seam_jump < 0.012`，并且**所有点仍然落在解析轨迹上**
  （拼接没把路径拧弯）；再跑一次覆盖第 10..19 帧，断言只重写那 10 帧。两条断言在 merge 落地前为红。
- 记两条自己踩的坑：① 在既有 HTTP 门禁中间插入提交会把后面所有 `expected_revision` 字面量顶掉，
  要么改数要么改夹具——这次按行号区间把 8 处 2 改成 5，红一次才知道；② 包内夹具第一次跑断言
  `replaced_frames==20`，实际是 0——因为这条样片第一次只跟了 20 帧，第二次窗口本就不重叠。
  断言要按夹具的真实状态写，不能照抄仓库门禁里的数字。
- 发布验收：`build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）。包内实例 `22cb252d5111`
  报 1.72.0：从第 20 帧接着跟，保住前 20 帧、路径补齐 40 帧、接缝实测 0.0453 画面宽；重跑第 10..19
  帧只替换那 10 帧；`merge=false` 仍整条替换。`ruff`、`npm run typecheck`、11 项桌面 TS、
  串行套件 **59/59**（`SUITE=0`）全绿。原生窗口 1480×900 标题栏「引擎在线 v1.72.0」
  （`AgentCut-1.72-原生窗口.png`），关闭后无残留。便携版 189,760,141 字节 SHA256
  `A41571C24ADA9E6A12C8713630A1687FECE2C0E4F25D842A7945EF5B02F1D91E`；安装版 189,920,861 字节
  SHA256 `74C745D8C8E6AF64FA9FCF25912A9DB8F66FA507C4E14B92A17A86BB5E365966`。

## 1.73.0 关键帧预算按片段剩余空间算（2026-10-08）

- 缺陷由「同一族功能不对称」看出：重构图 1.4x 起就按 `(KEYFRAME_LIMIT - len(clip.keyframes)) // 3`
  自适应补点，稳定却固定写 `min(240, 2000//3)` 个/曲线。跟过遮罩、压过闪避、K 过淡入淡出的片段曲线
  本来就多，再点「画面稳定」会在落库时被契约拒绝，回的是 `PROJECT_LIMIT`「project exceeds the
  supported contract limits」+ 空 `details`——不说哪条片段、不说超多少、不说怎么办。实测：一条挂着
  1950 个 opacity 点的片段，稳定写 59+59+2 → 2070 → 空壳错误。
- 修法与重构图同源：稳定要重写的那四条曲线上的旧点会被整条替换，所以不计入占用；其余曲线计入，
  `scale` 那两个固定点不参与抽稀。`budget = max(2, min(240, (2000 - 其他曲线数 - 2) // 3))`。
  1950 点的片段现在写 16 点/曲线、总计 1984 < 2000，一次点击就成。
- 两种损失必须说话：抽稀了就在 `stabilization.warning` 里写清「只剩 N 个点的位置、量到 M 帧，比一帧
  一个点粗，抖动会剩一些」并给出路；一点位置都没有（`available < 6`）是 `STABILIZE_FAILED`，
  `details` 带 `kept_keyframes` 与 `keyframe_limit` 两个数。界面提示不再把英文原文塞进 toast，改成用
  同样的数字自己拼中文句子（`clamped_axes` 那句一并中文化）。
- 门禁先红后绿：`tests/stabilize_check.py` 新增一条 `crowded` 片段（挂在所有被量窗口之后），先写
  1950 个 opacity 点再稳定，断言 200、`written_points == keyframe_budget == 16`、回读总数 1984、
  回复带抽稀警告。改动前红在那句 `PROJECT_LIMIT` 上。
- 包内实测（`package_check_173.py`，实例 `4d1d0663d3d9`）：1950 曲线的片段抽稀到 16 点/曲线、1984 总
  数、warning 里是「room for 16 of the 60 measured frames」；另一条塞到 1995 点的片段得到
  `STABILIZE_FAILED` 且 `details` 是 `{kept_keyframes: 1995, keyframe_limit: 2000}`，head 不动。
  夹具上的一个实话：第二例必须换一条片段——第一条已经带着自己的 36 条抵消曲线，再往里塞就先把
  `keyframes.replace` 那一批撑爆了。
- `ruff`、`npm run typecheck`、11 项桌面 TS、串行套件 **59/59**（`SUITE=0`）全绿；
  `build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）；原生窗口 1480×900 标题栏
  「引擎在线 v1.73.0」（`AgentCut-1.73-原生窗口.png`），关闭无残留。便携版 189,759,642 字节
  SHA256 `917AC9A5106719BAA4AEEA363FCD8EFF24E376B4A6ACC43B867F74817A7D5ADC`；安装版 189,920,367
  字节 SHA256 `38589F243D1197D116D360DCFA6C16D45E13B34998A0789CEFBA1B2D6C45EAD8`。

## 稳定性记录恒为真：新增 record_check.py 门禁（2026-10-08，仅测试）

- 1.69 起 `Clip.stabilization` 成了承重状态：它是「再按一次是替换」的依据、是变速与重构图的锁、
  也是界面那句「已稳定 · 强度 …」的出处。一句会过期的说法比没有说法更坏，所以这轮不新增功能，
  把「记录必须为真」这条不变量钉成永久门禁 `tests/record_check.py`（不碰媒体，0.2 秒）。
- 四条断言族，全部走 reducer 与计划函数本体，不复制判断：① 8 条普通片段命令（移动/滑移/裁头/
  effects/patch/淡入淡出/手动关键帧/遮罩中心关键帧）之后记录与其四条曲线都还在；② `clip.speed`
  200% 与 50%、`clip.speed_curve`、`reframe.plan` 四条都必须以 STABILIZE_LOCKED 命名拒绝，而
  100% 必须通过（不是改动就不该锁）；③ 用 `keyframes.remove` 清空那四条曲线，记录必须随之消失、
  两把锁必须一起松开（变速回 200% 通过、重构图改由它自己的理由 INVALID_REFRAME 拒绝），只删一个
  点则记录仍在，`clip.stabilize_record` 显式清空不动曲线；④ 分割与嵌套：两半都保住记录，且
  右半在自己的局部 0..30 帧上采样到整条片段当年在同一画面帧上的值（`sample()` 逐项比对，容差
  1e-9），合成内部的片段回答同一条拒绝。
- 变异测试五条红：拆掉 1.71 收尾 → 「the record outlived every curve it described」；拆掉变速锁 →
  「clip.speed 200 was accepted」；拆掉变速曲线锁 → 「clip.speed_curve was accepted」；拆掉重构图锁 →
  「clip.reframe refused as INVALID_REFRAME」；把分割的 `animation_offset_ticks + start` 改成不推进
  时钟 → 相位断言当场红。全部还原后 `git status src` 干净。
- 踩到两条自己的坑，记下来：断言写成「右半最早的 x 点应在局部 0」是错的——曲线存在绝对动画时钟上，
  整条片段前半的那个点本来就留在左半，正确的问法是采样值而不是点的位置；变异脚本用文本模式读写
  源码，把 `reframe.py` 的 LF 换成了 CRLF，`git status` 从此一直显示 M（`git diff` 是空的），改成
  字节读写并从索引 blob 复原。
- 套件因此从 59 项变 60 项，README 那行同时把 matrix 的形状数按实测改成 53。仅测试与文档，不动
  发布物，因此不涨版本号、不重打包。验收：`ruff check`/`format --check` 全绿，串行套件 **60/60**。

## 1.74.0 分析入口进得了嵌套合成（九条路由，工程 schema 不变）

- 缺陷是这样浮出来的：合成在界面里就是「另一条时间线」——客户端用 `sequence_view` 投影，普通
  `timeline_edit` 也早带 `sequence_id`。但九个分析入口（去空白、整轨去空白、统一响度、整轨响度、
  自动闪避、画面稳定、遮罩跟踪、主体跟随、自动字幕）只读根工程的 `clips`/`tracks`。实测（夹具
  与包内各量一次）：片段进了合成之后，`/clips/{id}/silence`、`/loudness`、`/reframe`、
  `/stabilize`、`/track` 一律 404「clip is not in this project」——可它就在这条工程里；
  `/tracks/{id}/silence`、`/loudness`、`/duck` 更坏：根上那条同名轨是空的，于是 200 回一句
  「没什么可切 / 已经对齐」，把读不到当成没有；任何请求带 `sequence_id` 都是 422
  `INVALID_REQUEST`（契约 `extra=forbid`，字段根本不存在）。界面没做任何灰化，所以这六是用户
  每天点得到、每次都不通的按钮。
- 修法不新写一套读取规则：七个请求契约加 `sequence_id: Identifier | None = None`，九条路由改用
  reducer 已有的 `sequence_view(root, request.sequence_id)` 解析 clip/track id，派生批次同样盖上
  `sequence_id`，于是「分析 → 写入」依旧是一条事务、一个 revision；回复里的 `project` 仍是根工程，
  跟其它路由一致。可选字段带默认值，旧请求与旧回执一字不改（`_fingerprint` 本来就剥掉 `None` 的
  `sequence_id`），SCHEMA_VERSION 不动。
- 门禁 `tests/sequence_plan_check.py`（真实媒体）量的不是 200 而是同一件事：同一条遮罩路径先在根
  时间线出计划（39 点），嵌套之后在合成里执行，落库的 `x`/`y`/`scale` 与那批计划**逐点相同**，而外面
  那条容器片段一条关键帧都没多；合成里的 1 秒抖动样片被写上 **29 点/曲线**（量到 30 帧）、遮罩跟踪
  写 10 个点、去空白切掉 **0.77 秒**（片段 4→5）、统一响度落 **2.2387** 倍增益、整轨去空白读到合成
  轨里那 1 条片段（根上同名轨确实是空的）、自动闪避按合成里的 2 段语音在配乐上写 8 个音量关键帧、
  整轨响度量到 2 条改了 1 条；嵌套之后在根上问同一条片段仍然诚实回 404。
- 两条顺手量出来的实话，写下来免得下次当断言用：`dry_run` **不产生回执**，同一个 request_id 再问
  一次就再计划一次（第一次跑门禁就是按「dry run 会命中回执」写的，当场红）；真实提交的那次要按
  客户端重放的方式重发——带着它读过的那个 revision，而不是当前 revision——才命中回执，否则是
  `IDEMPOTENCY_CONFLICT`（指纹里本来就有 `expected_revision`）。
- 变异测试六条红：把 `reframe`/`silence_scan`/`clip_stabilize` 任一路由改回只读根工程 → 对应那步
  404；把 `duck_track`/`silence_track` 的批次戳删掉 → 计划正确但写入找不着片段
  （404 `clip_id: bed, command_index: 0`）；把 `MaskTrackRequest.sequence_id` 从契约里摘掉 → 请求
  422 `INVALID_REQUEST`。全部还原后 `git status src` 只剩本轮该改的三个文件。
- 界面：`store.ts` 九处分析请求自动带上当前合成（`sequence_id: state.sequenceId`，与 `submit` 早就
  在用的同一个值），帮助里新增「合成·分析工具」一条，把「以前是按不动、现在是量的就是你看到的那条
  轨」写清楚。MCP 的 schema 由契约生成，`tests/self_check.py` 另外断言六个工具的 schema 都含
  `sequence_id`——Agent 读的就是这份。
- 本轮没单独端到端量过的一条：自动字幕在合成里的实际听写（改动与其它八条逐字相同、字段在契约里
  可见，但没为它写媒体夹具）。→ 已补测，见文末「验收补测 · 自动字幕在合成里」一节，
  `tests/captions_comp_check.py`。

- 发布验收：`build_engine.py`（`FREEZE=0`，staged 324.9 MB）+ `npm run dist`（`DIST=0`）。包内实例
  `ab9074e6d336` 报 `app_version=1.74.0`，`package_check_174.py` 在**打包后的引擎**上重跑同一序列：
  合成里的跟随写入与根时间线的计划逐点相同（9 个点）、被跟随过的片段再稳定点名拒
  `STABILIZE_CONFLICT`、画面稳定写 59 点/曲线（量到 60 帧）、遮罩跟踪 22 个点、去空白切掉 0.767 秒、
  统一响度 2.2387、整轨去空白同样 0.767 秒、自动闪避 8 个音量关键帧对 2 段语音；dry run 回的是
  预期 revision 10 而库里仍是 9；包内 MCP `tools/list` 的 schema 含 `sequence_id`；asar 里
  `sequence_id:….sequenceId` 出现 10 处，帮助页含「合成·分析工具」。`ruff`、`npm run typecheck`、
  11 项桌面 TS、串行套件 **61/61** 全绿。原生窗口 1480×900 标题栏「引擎在线 v1.74.0」
  （`AgentCut-1.74-原生窗口.png`），关闭无残留。便携版 189,762,223 字节
  SHA256 `FB4FDF5544DAAA2D7547AE700FAD43D2DE5F528319D028C4193DB9DFFC46BA51`；安装版 189,922,939 字节
  SHA256 `759464BD8D3B124C69B3D5A0D4806E881BF63D89BE5B08E9E41C525094B79C65`。未签名，NSIS 向导未点击验收。

## 1.75.0 每一条分析拒绝都点名它说的是谁

- 找缺陷的方法还是组合：1.74 给九个分析入口开了 `sequence_id`，于是多了「合成不存在」「id 在另一条
  时间线上」「窗口越过片段末尾」「driver 指向自己」这些拒绝形状。挨个问一遍（`tests/
  analysis_sweep_check.py` 的前身，九条路由 × 各自边界形状 × dry/提交），当场抓到一批
  `{"code": ..., "message": ..., "details": {}}`：错误码有了，「哪一条？」没人说。具体四处：
  片段不在根时间线上时 `/clips/{id}/silence`、`/loudness` 的 404 是空 details；
  `sequence_view` 对不存在的合成回「sequence does not exist」但不说是哪个 id（这条不止分析入口，
  `timeline_edit` 走的是同一个函数）；跟不到东西时 `TRACK_FAILED` 不说量到几帧、要几帧；素材被挪走
  之后八处 `MEDIA_MISSING` 全是「source file is gone」+ 空 details——四十个素材的工程里没人知道
  该去找哪一个。
- 改的是错误负载不是判断：`clip_id` / `track_id` / `asset_id` / `sequence_id` 进 `details`，
  `TRACK_FAILED` 另带 `matched` 与 `frames`，`MEDIA_MISSING` 同时给片段与素材。一条拒绝的条件都没
  放宽或收紧，`details` 本来就是 `EditorError` 的第四个参数，所以契约、reducer、回执都不动。
- 门禁钉住五件事：不 5xx；每条拒绝有 code、有能读的句子、`details` 非空；`NOT_FOUND` 必须点出一个
  id；拒绝绝不抬 revision；同一个问题 dry 与真实提交答案一致——唯一允许的差别是「空计划」
  （`apply=false` 是 200 给你看，`apply=true` 按名字说「没什么可做」，因为提交一条空批次没有意义）。
  再把样片从磁盘上删掉重问三次：三条路由都回 410 并点名打不开的片段与素材。实测这一轮：
  **47 条拒绝、26 条点名 id、0 个 5xx、0 次 revision 变动**。
- 夹具自己也要讲实话：`vid` 原本挂在「灰底 + 一条 tone」上，稳定与跟踪在那种画面上量不到东西，
  于是门禁先红在 `STABILIZE_FAILED` / `TRACK_FAILED` 上——那不是缺陷，是夹具在撒谎。换成
  「无周期纹理 + 抖动窗口 + 滑动的亮块」之后，稳定回的是 `STABILIZE_CONFLICT`（同一条片段先被
  主体跟随写过 `x`/`y`/`scale`，1.68 的守卫本来就该挡），跟踪 200 写点，门禁量的才是它想量的东西。
- 变异测试五条红：剥掉 `clip_id`（4 处）→「NOT_FOUND: empty details」；剥掉 `sequence_view` 的
  `sequence_id` → ghost comp 当场红；剥掉 `asset_id`（8 处）→ 410 的断言红；只剥掉 `asset_label`（8 处）也红（文件名是这一句里唯一
  人能看懂的部分）；剥掉 duck 的 `track_id=driver_id` → 「driver not there」红。剥掉 duck 的
  `track_id=driver_id` → 「driver not there」红。全部还原后 `git status src` 只剩本轮该改的文件。
- 界面是这件事的另一半：`EngineError.explain()` 原本用中文提示**替换**引擎的英文句子，所以名字即使
  在 `details` 里也看不见。1.75 起它把 `asset_label`/`asset_id`/`clip_id`/`track_id`/`sequence_id`
  织到提示后面（「素材原文件已被移动或删除，请重新导入。（素材 tone.mp4、片段 s）」），没有目标就不加
  空括号；另外补上原先**根本没有中文说明**的 11 个分析错误码（`NOT_FOUND`、`INVALID_SILENCE_TARGET`、
  `INVALID_LOUDNESS_TARGET`、`INVALID_REFRAME`、`INVALID_DUCK`、`DUCK_PLAN_TOO_LARGE`、
  `INVALID_TRACK_TARGET`、`TRACK_FAILED`、`INVALID_SPEED`、`PROJECT_LIMIT`、`TIME_OVERFLOW`）——
  在此之前按「去空白」「自动闪避」「主体跟随」被拒时，提示里就是引擎那句英文。
  `tests/desktop_error_naming_check.ts` 逐条钉住（12 项桌面 TS 之一）。
- 自己踩的坑记一条：给 AGENTS.md 打补丁时用 `decode → replace("\n", "\r\n") → encode` 写回，把
  本来就有的 CRLF 变成了 `\r\r\n`（39 处）。`git diff --stat` 立刻显示 39 增 39 删——按字节改文件
  必须先探测换行符，或者干脆用编辑工具。已从索引 blob 复原。

- 发布验收：`build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）。包内实例 `d341e1bc8040` 报
  `app_version=1.75.0`；`package_check_175.py` 在打包后的引擎上量：不存在的合成 → 404 带
  `sequence_id:"nope"`，不存在的片段 → 404 带 `clip_id:"ghostclip"`，driver 指向不存在的轨 → 404 带
  `track_id:"ghost"`，删掉样片后 → 410 `MEDIA_MISSING` 说出 `tone.mp4` 与片段 `s`、revision 不动；
  包内 MCP schema 仍带 `sequence_id`，asar 里既有中文提示也有 `asset_label`，说明织入真的进了壳层。
  `ruff`、`npm run typecheck`、**12 项**桌面 TS（新增 `desktop_error_naming_check.ts`）、串行套件
  **62/62** 全绿；原生窗口 1480×900 标题栏「引擎在线 v1.75.0」（`AgentCut-1.75-原生窗口.png`），
  关闭无残留。便携版 189,763,030 字节 SHA256
  `270E6BF13208933EE3077C7C900328C905100163719BAF63C2E3AFE723C53CC8`；安装版 189,923,746 字节
  SHA256 `A9B75C75EA17F67135D46C6564653F182CC6C3B3B7747C4FFF5140037653887B`。未签名，NSIS 向导未点击验收。

## 1.76.0 读不存在的 id 也要说清楚是哪个

- 顺着 1.75 的同一把尺子量 `GET` 一侧，先记录现状再动手：13 条读路由对不存在的 id 回
  `{"code":"NOT_FOUND","message":"…","details":{}}`；`GET /v1/projects/{unknown}/jobs` 更糟——回
  200 + 空列表，打错一个字的工程 id 与「这个工程还没导出过」在界面上无法区分，而紧挨着的
  `history` 回的是 404。两条路由对同一个输入给两种答案，本身就是缺陷。
- 修法集中在三个真正说话的地方，不在路由里重复判断：`ProjectStore._load`（工程、历史、字幕、素材
  清单、预览清单、渲染计划、取帧都经它）带上 `project_id` 与 `revision`；`MediaService.get_probe`
  的两条（探测记录、代理流）带上 `probe_id`；字幕导出与片段取样带上 `track_id` / `clip_id`。
  `/projects/{id}/jobs` 改成先读工程，未知工程与其它读路由一致回 404。判断一字未动。
- 门禁 `tests/read_sweep_check.py`：15 条「读不存在的东西」覆盖 project / probe / clip / track /
  asset / sequence 六种 id，每条都必须把它收到的那个值放回 `details`；素材被挪走后 410 点名
  `probe_id`；再加七条正常读（工程、历史、素材清单、任务列表、字幕、探测记录、预览清单）必须仍是
  200——补 `details` 不能把能用的读变成新的拒绝。
- 门禁自己先红在两条上，而且红得对：`/frame` 与 `/assets/{id}/proxy` 我按猜的查询名去问
  （`t=`、少一个 `width`），回来的 422 是契约层的缺字段拒绝、`details` 里是 `issues`——那是正确答案，
  不是缺陷。断言要照接口的真实形状写，于是把两条 ask 改成合法查询串后它们才真的走到 404。
- 变异测试四条红：剥掉 `_load` 的 `project_id` → 一批读路由当场红；剥掉 `get_probe` 的 `probe_id` →
  探测记录与 410 两条红；剥掉字幕导出的 `track_id` → 那条 ask 红；把 `/jobs` 的 `projects.get` 去掉 →
  「未知工程回 200」这条红。
- 发布验收：`build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）。包内实例 `40afe2ceb86f` 报
  `app_version=1.76.0`；`package_check_176.py` 在打包后的引擎上量到七条正常读仍 200、七条失败读各点名
  它收到的 id（project / track / clip / probe / sequence，含那条曾经回空 200 的 `/projects/ghost/jobs`）、
  样片被删后 410 点名 `probe_id`。`ruff`、串行套件 **63/63** 全绿；原生窗口 1480×900 标题栏
  「引擎在线 v1.76.0」（`AgentCut-1.76-原生窗口.png`），关闭无残留。便携版 189,763,321 字节 SHA256
  `DA5A79343AD29CCA14B43532A0E38188485D836EBA6854C947F75CB391337DBB`；安装版 189,924,038 字节
  SHA256 `FF241C45E412553CDAB647A05BFF68D9877D68B43D96772A469A4BE0C09B2EED`。未签名，NSIS 向导未点击验收。

## 1.77.0 操作类路由的拒绝也说清楚

- 1.75 管分析、1.76 管读，这一轮量剩下的操作面：导入素材、缓存清理、恢复历史、任务、`.cube` 解析。
  先把现状记下来再动手（`tests/ops_sweep_check.py` 的前身）：`POST /v1/media/import` 的四条失败
  ——文件不存在、路径不是绝对路径、在允许的素材夹之外、扩展名不认识——`details` 全是 `{}`；
  `POST /v1/lut/parse` 的 `INVALID_LUT` 同样空着：句子写了「读不出这一行」却不说是第几行。
- 改法与前两轮一致：`MEDIA_NOT_FOUND` / `MEDIA_EMPTY` / `MEDIA_PATH_INVALID` 带 `path`（调用方自己给的
  那串），`MEDIA_TYPE_UNSUPPORTED` 带 `path` 与 `suffix`（类型表只认后缀，所以由 `resolve_path` 把路径
  补回去，两处信息一起给），越界那条继续带 `media_roots`——配上 `path` 才知道差在哪个夹子外面；
  `INVALID_LUT` 带解析循环的行号，行数对不上时给 `size` 与 `rows` 两个数。判断一字未动。
- 门禁钉 11 条拒绝 + 9 条正常调用（媒体配置、探测列表、缓存状态、两种 prune、导出根、ids、正常 `.cube`
  解析、工程打包、字幕读回）——补 `details` 不许把能用的调用变成新的拒绝。
- 两条自己踩的坑，都记下来因为它们都曾假装通过：① 第一版门禁把 `{work}` 这类占位符只替换进 URL、
  没替换进请求体，于是引擎真的收到一条相对路径 `"{work}/missing.mp4"`，四条导入用例全部以
  `MEDIA_PATH_INVALID` 收场——看起来"红得合理"，其实量的是自己的打错字；② 变异测试第一次改的是
  `INVALID_LUT` 的**消息文本**而不是 `line=number`，门禁照样绿——那是个无效的变异，不是盲的门禁，
  换成剥掉 `line=number` 之后才真的红。四条红最终为：`path=str(real)`、re-raise 的 `path`+`suffix`、
  `line=number`、`size`/`rows`。
- 发布验收：`build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）。包内引擎报 `app_version=1.77.0`，
  `package_check_177.py` 在打包后的引擎上量到：三条导入失败分别给出 `path`、`path`+`media_roots`、
  `path`+`suffix`；`.cube` 三种被拒分别回 `{'line': 2}`（3D 表）、`{'line': 3}`（读不出的一行
  `'0.0 0.5'`）、`{'size': 5, 'rows': 2}`（行数对不上），正常 1D 表仍解析成功。`ruff`、串行套件
  **64/64** 全绿；原生窗口 1480×900 标题栏「引擎在线 v1.77.0」（`AgentCut-1.77-原生窗口.png`），
  关闭无残留。便携版 189,762,599 字节 SHA256
  `B209B6A940C2AF2E3060DB62C2D734A0E313BDE5A058349E7DA69FBD6C044D20`；安装版 189,923,322 字节
  SHA256 `2FCF7CBC0E1E6C638D9212C9526ED1098422263765D962E579B0C48463162FDF`。未签名，NSIS 向导未点击验收。

## 1.78.0 片段降噪：一个旋钮，只在导出里生效

- 这是本轮第一件新增能力而不是扫缺陷：口播素材的房间底噪是剪映用户最先按的那个按钮，AgentCut 之前
  没有。范围刻意收成一个旋钮（0–24 dB），因为两端一致的代价全在「能不能说清它做了什么」。
- 一个真实的产品决定来自测量而不是文档：`afftdn` 的噪声底 `nf` 用 FFmpeg 默认值 −50 dBFS 时，
  在「440 Hz 音 + 白噪声」的样片上 6 kHz 那条带只从 −46.7 掉到 −47.3 dBFS——0.5 dB，等于给用户一个
  不起作用的旋钮。把 `nf` 钉到 −30 dBFS 之后同一档 nr=12 压掉 8.9 dB、nr=24 压掉 11.3 dB，而音
  只动 0.04 dB。所以产品里 `nf` 不是可选项，是常量，理由写在 `render.py` 的注释与契约里。
- 与 `blur`/`sharpen` 同族：可以 `clip.patch`，不能打关键帧（`EffectField` 有它，`EffectProperty`
  没有），曲线编辑器和 `keyframe.set` 都拿不到它。回执不受影响：`_fingerprint` 的
  `effects_added` 是从模型推导的，新键在默认值上不进哈希，所以 1.64 之前捕获的那批摘要照旧命中。
- 预览不做降噪，就不假装做：滑杆后面写着「只在导出里生效，浏览器预览不降噪」，帮助里单列一条，
  与母带限制器同一待遇。
- 门禁 `tests/denoise_check.py` 量三档渲染（0/12/24）：6 kHz 噪声带 −50.0 → −58.8 → −61.0 dBFS，
  440 Hz 音在三档里最多动 0.06 dB；`afftdn=nr=12.0:nf=-30.0` 在编译出的滤镜图里恰好一级、旋钮回 0
  一级都没有；超上限 422、`keyframe.set` 被拒、能力表下发 24.0。
- 变异测试四条红：把这一级的条件改成永假（旋钮什么都不做）→ 计划里没有 `afftdn`；把 `nf` 换回 FFmpeg
  默认的 −50（也就是「看起来能调其实没用」那个版本）→ 计划里的字符串不再是 `nf=-30.0`；把
  `limits.denoise_db` 改成 240（界面会给出一个引擎不认的上限）→ 红；把 `denoise` 塞进
  `EffectProperty`（假装能逐帧降噪）→ 红在 `PROPERTY_LIMITS` 缺键上。前两条各跑了一次才明白：锚点要按
  ruff 换行后的真实文本写，标识符不能整体替换——`DENOISE_FLOOR_DB` 全文替换会连 import 那行一起换掉，
  变成语法错误，那是无效变异。
- 发布验收：`build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）。包内实例 `1ad35b0e485c` 报
  `app_version=1.78.0`；`package_check_178.py` 用打包后的引擎与随包 FFmpeg 重跑同一序列：能力表下发
  `clip_denoise` 与 `denoise_db = 24.0`，编译计划里恰好是 `afftdn=nr=12.0:nf=-30.0`（旋钮回 0 一级都没有），
  成片 6 kHz 噪声带 −50.2 → −58.8 dBFS（12 dB 档压掉 8.6 dB），440 Hz 音只动 −0.07 dB；asar 里搜得到
  「降噪」「只在导出里生效」与 `denoise`。`ruff`、`npm run typecheck`、12 项桌面 TS、串行套件 **65/65**
  全绿；原生窗口 1480×900 标题栏「引擎在线 v1.78.0」（`AgentCut-1.78-原生窗口.png`），关闭无残留。
  便携版 189,763,137 字节 SHA256 `527CB5590203734B568CAD8A207F3125F367A02A3DED6427687C5A191D9379A9`；
  安装版 189,923,855 字节 SHA256 `D4476C878870E56967E443B025044F6D9A368DFA05EDC6A82B7474F0513041F2`。
  未签名，NSIS 向导未点击验收。

## 验收补测 · 自动字幕在合成里（2026-10-08，不涨版本号、不重打包）

1.74 的收尾留了一条实话：九个分析入口里只有七个用真实媒体端到端量过，自动字幕（`/speech-captions`）
在合成里的听写「改动与其他八条逐字相同」但没写夹具。按这一轮的尺子，那句「逐字相同」是推断而不是证据，
所以本轮不加功能、不涨版本号，只把它量出来。新门禁 `tests/captions_comp_check.py`（真实语音 + 真实导出，
实测 19.6 秒）：

- 夹具是 Windows 语音合成的两句中文（7.769 秒、中间 1 秒静音）加一张 0x404040 灰底画面——灰底里
  一个亮像素都没有，所以成片里的亮字只可能来自字幕。外层先听出 **2** 条 cue；`sequence.nest` 把
  画面与声音一起收进合成 `s1`（顺带量到一条既有约束：nest 拒绝纯音频选择，回
  `INVALID_SELECTION「nesting requires visible picture clips」`）。
- 外层再问同一条片段回 404 且点名 `clip_id=c`；空的同名轨那条点名 `track_id=a1`；不存在的合成那条点名
  `sequence_id=nope`——三条都是 1.75/1.76 的形状，这次是在真听写上量的。
- 带 `sequence_id=s1` 听出的 cue 与外层**逐字逐 tick 相同**，内容寻址的 `subt-…` 轨 id 也相同（同一段
  声音当然还是同一条字幕轨）；dry run 在合成的投影里预览到那 2 条字幕片段而库里仍是 revision 2；apply
  之后 revision 3，字幕轨与 cue 片段只出现在 `sequences[s1]`，外层依旧只有容器片段 `cn`，容器片段一条
  关键帧都没多；重跑（含 dry run）撞 `DUPLICATE_ID`；`replace_track_id` 在合成里原位重生成同 id 同条数。
- 导出外层时间线，复检通过（10 秒 / h264+aac）：两条字幕各自中间帧 **55** 与 **30** 个 >200 的亮像素
  （>235 为 11 与 3），前导、两条之间那 1 秒空隙、结尾三处都是 **0**。断言按实测写下限（≥20 与 >0），
  不是猜的。
- 变异测试五条红，且每条都红在该红的那句上：路由改回 `project = root`（红在合成里那条问句不再点名
  合成）、派生批次丢掉 `sequence_id`（红在 dry run 预览里 0 条 vs 2 条）、404 丢掉 `clip_id`（红在
  `details == {}`）、字幕轨 id 改成随机（红在「轨 id 与外层相同」）、把 cue 片段推到画布外
  `ClipEffects(y=2.0)`（红在像素那句：五个采样点全 0）。
- 自己的两个坑，都属于「假信号」这一类：① 变异脚本给子进程只传了 `PYTHONIOENCODING/PYTHONUTF8/PATH`，
  少了 `SystemRoot` 之类，gate 里的 TestClient 在 `_overlapped` 处崩掉，五条「红」其实全是同一个
  WinError 10106——先怀疑自己的量具，加了「不变异也必须绿」的对照跑之后才拿到真的五条；② 第一条变异把
  `y` 写成 2.4，被契约的 `le=2` 拦在模型层，红是红了但不是那条断言红的，换成 2.0（合法极值）才算数。
- 范围就此收住：这是验收缺口的补齐，不动契约、不动界面（Help 里「合成·分析工具」那条本来就写着自动字幕，
  现在它有证据了），因此不涨版本号、不重打包，发布物仍是 1.78.0。串行套件 **66/66**。

## 1.79.0 Agent 补齐三条音量入口，空轨与静音改为点名拒绝

- 找缺陷的方法还是把两个入口摆在一起对表：拿 capabilities 声明的「分析类」路由去数 MCP 工具，
  `/clips/{c}/loudness`、`/tracks/{t}/loudness`、`/tracks/{t}/silence` 三条在 docs/api.md 那张
  「路由 → 工具」表里明写着 `—`。也就是说人有按钮、Agent 只有母带对齐——1.75/1.76/1.77 三轮都在
  补「拒绝说清楚」，这一轮补的是「入口根本够不着」。修法照 `clip_silence` 的既有形状：三个只读薄
  工具，`apply`/`dry_run` 在工具侧固定 false，命令交回 `timeline_edit`；schema 由契约生成，
  `sequence_id` 自动可见。适配层不写第二条规则。
- 门禁不是「工具存在」而是 Agent 真走一遍：`tests/self_check.py` 新增 `analysis_through_mcp`，
  官方 stdio 客户端 + 真实音频，量到 5 % 的 440 Hz 是 **−47.8 LUFS**、计划 `gain=4.0` +
  `limited_by="gain_range"`，满幅那条是 **−22.2 LUFS**、`gain≈2.04`、`reaches_target=true`；
  整轨 `measured=1/changed=1` 的命令经 `timeline_edit` 落库恰好一个 revision 且 `gain` 与计划逐字
  相等、再扫 `changed=0`；请求里写 `apply=true` 也不写库（读侧工具的承诺）；门控 1 秒静音的整轨扫描
  回 `removed_ticks`≈1.0 秒，剪后同轨合起来 3.0 秒；进合成之后外层那条同名空轨被诚实拒绝，带
  `sequence_id` 的写入只动合成里的片段。
- 顺手抓到两条真缺陷（都来自「把读不到当成没有」这一族）：四条整轨路由里只有自动字幕会说
  「this track holds no clips」，另外三条对空轨回 200 `measured=0`，`apply=true` 时响度那条还会说
  「已经对齐了」——一个片段都没有的轨道被说成对齐了，正是 1.74 修过的毛病在空轨上的残余；改成四条
  同句、同 `track_id`。另一条更硬：纯静音片段点「统一响度」回 **502** 且 `details={}`，根因是 FFmpeg
  对数字静音打印 `Peak: -inf dBFS`，而 `loudness.py` 的正则只认 `-?[\d.]+`，「读不出」被当成引擎故障。
  现在 `-inf` 可解析、且按 ebur128 的静音门限（`SILENCE_FLOOR = -70.0`）把纯静音按 422 点名拒绝，
  `path` 由测量处给、`clip_id`/`asset_id`/`asset_label` 由路由的 `_meter_clip` 补上。
- 自己写出来的两个坑，都记下来因为都属于「假装通过」：① 拒绝负载里塞 `-inf`（我第一版把读数原样
  放进 details）会让 JSON 序列化当场炸——无穷大不可表示，读数只用于判断，不进负载；② 断言里我按
  直觉假设 5 % 的音能抬到 −16，实测被 `MAX_GAIN=4` 夹住，红的那次是断言错而不是引擎错，于是把这条
  改成量真正的产品事实（`gain == 4.0` 且 `limited_by == "gain_range"`）。另外探针脚本里 request_id
  带 `%` 会被 Identifier 拒成 422，也是先怀疑量具才对。
- 界面零改动：`NOT_FOUND` 的中文提示本来就写着「片段或轨道可能在另一个合成里（从面包屑进去）」，
  `explain()` 又把 `track_id` 织进句子；帮助加「Agent·音量与去空白」一条把上面这些数字写进去。
  契约、reducer、capabilities、工程 schema 一字不动（没有新命令、没有新字段），旧回执不受影响。
- 打包验收时又抓到一条同族的：整轨响度路由的 docstring 早就写着「量不了的片段记成 skipped 并说明
  原因」，实现却是测量一失败就整批拒绝——一条纯静音片段能让整条轨的对齐按钮报错。包内第一次跑到
  「一条轨上既有有声片段又有静音片段」才暴露它。现在 422 记成 `skipped` 继续走，5xx 与素材丢失照旧
  上抛；包内实测 `measured=2 / changed=2 / off_target=1`，被跳过那条带着「digital silence」的原因，
  两条有声片段的命令经 `timeline_edit` 落库到 revision 2。单片段路由仍然点名拒绝，因为用户问的就是那一段。
- 新门禁 `tests/empty_track_check.py`（1.1 秒、不渲染，只用 stdlib 写的真 WAV）钉 12 条整轨
  拒绝 + 空/缺失两种句子的分工 + 「有片段的轨绝不被这么说」，外加静音片段的响度拒绝点名（单片段
  路由 422 + `path`/`clip_id`/`asset_label`；整轨路由 200 + `skipped`）与 `SUBTITLES_MODEL_MISSING`
  的新 details。十条变异测试逐条红：三条路由守卫各删一次（各自回 200 `measured=0`）、删自动字幕
  存在性检查（「不存在」被说成「没有片段」）、只删那句的 `track_id`、删 `-inf` 正则分支（502 重现）、
  删静音拒绝的 `path`、把点名包装换成裸 `raise`、删模型缺失的 details、把整轨的 `skipped` 分支换成
  裸 `raise`（红在 `status == 200`）。其中两条是第二轮才补上的：第一轮跑到「删掉 `path`」时门禁居然
  绿了——我把那条断言从片段路由挪到整轨路由时，`path` 就没人检查了。断言跟着代码搬家之后要重新问一遍
  「它还钉得住吗」。
- 发布验收：`build_engine.py`（`FREEZE=0`，staged 324.9 MB）+ `npm run dist`（`DIST=0`）。包内实例
  `0cf86b326fee` 报 `app_version=1.79.0`；`package_check_179.py` 走**打包后的 MCP stdio**（Agent 真正
  用的那条传输）量到：工具 43 个、三条新工具都在且 schema 含 `sequence_id`、`readOnlyHint=true`；
  `clip_loudness` 对 5 % 的 440 Hz 音报 **−47.8 LUFS → gain 4.0（`gain_range`）**、预测 −35.76，与源码树
  里 `tests/self_check.py` 的量值一字不差（同一处权威）；纯静音片段回「this audio is digital silence」
  并点名 `c-silent` 与 `silence.wav`；`track_loudness` 量 2 改 2、跳过那条静音的，命令经 `timeline_edit`
  落到 revision 2；四条整轨路由在包内对空轨/缺轨口径一致（404 + 点名）；asar 里帮助条目
  「Agent·音量与去空白」在。`ruff`、`npm run typecheck`、桌面 TS 检查、串行套件 **67/67** 全绿；
  原生窗口 1480×900 标题栏「引擎在线 v1.79.0」（`AgentCut-1.79-原生窗口.png`），关闭无残留。
  便携版 189,765,714 字节 SHA256 `129756C267DAB0157CAC6B65756E84A0418848F82217F8E6403C4D9CE256F500`；
  安装版 189,926,426 字节 SHA256 `0BB9365C17C5B7C41F7E60A12E1FD041363A779CFA8D9F25E6AC22A3FE0D4F79`。
  未签名，NSIS 向导未点击验收。

## 1.80.0 Agent 看得见成片画面，也管得动派生缓存

- 还是那把尺子：人有按钮、Agent 够不着，就是缺陷。`GET /v1/projects/{id}/frame` 是界面预览每一帧的
  来源，Agent 侧一个工具都没有——它能写关键帧、遮罩、调色节点，却没有任何办法确认画面真的动了；
  `/v1/media/cache` 与两个 prune 同理，缓存配额 1.44 就交付了，界面上有「清理缓存」按钮，Agent 连
  读都读不到。新增 `preview_frame` / `media_cache_read` / `media_cache_prune` / `media_proxies_prune`
  四个工具（43→47），适配层照旧不写规则：帧字节来自 `MediaService.render_frame`，也就是导出用的那条
  编译链，不是第二套预览实现。
- 门禁量的不是「有没有图」，是三条可判定的事实（`tests/self_check.py` 的 `frame_through_mcp`，
  真实素材、官方 stdio 客户端）：① 同一帧取两次逐字节相同——请求多给 1 tick，引擎夹回整帧网格并
  如实报 `at_ticks = 35,280,000`，sha256 与上一张一致；② 片段横向 `x=0.4` 之后同一个 tick 的哈希
  **必须变**，没变就说明这次编辑在画面上是空的；③ 片段进合成后「在合成里取帧」与「在外层看容器」
  是同一幅画，清完派生缓存再取还是同一幅画。缓存侧钉的是「dry run 不删、真删能回来」：read 的
  `used_bytes` 与 prune 报的 `used_bytes_before` 相等，`dry_run=true` 之后不减，真删之后
  `used_bytes <= before - freed` 且那一帧哈希不变。
- 两条我自己猜错的地方，都按实测改回来了，因为它们本来会写成假话：① 我以为 320×180 的工程会回
  320×180 的图，实测回 **256×144**（`render_frame` 把长边压到 256 做传输，宽高比严格保持），于是这句
  写进工具的 docstring 而不是留给用户猜；② 我以为 0.5 秒不是整帧，实测 30fps 下 `TIMEBASE/2` 正好是
  第 15 帧，所以「夹帧」这条要用 `+1 tick` 才量得出来。还有一条比较我写错了对象：拿 t=0 的帧去和
  t=15 帧的比哈希必然不同，那量的不是编辑而是时间——改成先取一份 t=0 的基准再比。
- 界面零改动（帮助新增「Agent·看得见画面」一条），契约、reducer、capabilities、工程 schema 不动。
  docs/api.md 那张「路由 → 工具」表补齐，并且把刻意没有工具的十条路由写清楚理由：它们是给浏览器看的
  字节流或整包 zip（遮罩位图、媒体流、代理读写、工程包），不是一条命令语义；Agent 要判断画面用
  `preview_frame`，要引用素材用 `project_asset_urls` 给的签名 URL。
- 变异测试五条红，且都红在该红的断言上：从 `preview_frame` 的回复里删掉 `sha256` → 哈希那句直接
  `KeyError`；把 `at_ticks` 改成回请求里那个数而不是响应头里真正取样的那个 → 夹帧那句红；把
  `render_frame` 的 `at = at_ticks // frame_ticks * frame_ticks` 去掉 → 同一句红；让
  `media_cache_prune` 无视 `dry_run`（强制 false）→ 「空跑不许删」那句红（`dry_run: false` 出现在
  回包里）；把宽高写死成 0 → 尺寸那句红。控制跑（不变异）必须先绿，这一条是上一轮学到的。
- 发布验收：`build_engine.py`（`FREEZE=0`，staged 324.9 MB）+ `npm run dist`（`DIST=0`）。包内实例
  `f78ef1c0de27` 报 `app_version=1.80.0`；`package_check_180.py` 走打包后的 MCP stdio：工具 47 个、
  四个新工具都在且 `preview_frame` 是只读；对 320×180 的真实工程取帧得 **256×144 PNG、13,584 字节、
  `at_ticks=35,280,000`**，sha256 与本地对同一字节流重算一致；多给 1 tick 夹回同一帧且逐字节相同；
  片段横向 40 % 之后 t=0 的哈希从 `4b2ebf9a…` 变成 `4c0535f6…`，同一帧再取仍然一致（可复现）。
  缓存侧在包内量到的是另一件事：包内验收的缓存目录就注册在素材根里，所以 prune 计划释放 **0 字节**
  ——这正是「绝不删登记素材根里的东西」那条保护在生效；真正删掉字节的路径在源码树门禁里量到
  （283,544 字节整项清掉，删完那一帧哈希不变）。asar 里帮助条目「Agent·看得见画面」在。
  `ruff`、`npm run typecheck`、桌面 TS 检查、串行套件 **67/67** 全绿；原生窗口 1480×900 标题栏
  「引擎在线 v1.80.0」（`AgentCut-1.80-原生窗口.png`），关闭无残留。
  便携版 189,768,122 字节 SHA256 `FDE40554586FEDF60759ED232038572F4B84BE505B554EA009DF4048B68AD108`；
  安装版 189,928,844 字节 SHA256 `6F1F38E73A5F95B9477BEEC3D6E8E77B9B7FBF0D7C07731EEE79753E2D913FB9`。
  未签名，NSIS 向导未点击验收。

## 1.81.0 每一条引擎拒绝都有中文说法

- 找缺陷的方法：把两个面摆在一起对表。这次是「引擎能报的码」×「界面准备好的中文说法」。
  `EngineError.explain()` 在没有提示时 `return this.message`，也就是把引擎写给开发者看的英文原句直接
  端给按中文按钮的人。扫出来：`src/agentcut/*.py` 能报 **116** 个码，`desktop/src/engine.ts` 的提示表
  只有 60 个 key，**58 个码没人管**——`INVALID_SPLIT`、`NOT_ADJACENT`、`DUPLICATE_ID`、
  `REVISION_OVERFLOW`、`OUTPUT_INVALID`、`SPEECH_NOT_FOUND`、`SUBTITLES_MODEL_MISSING`、
  `FONT_UNAVAILABLE`、`MEDIA_PATH_INVALID` 这些点得到、报得出的路径，用户看到的全是英文。
- 逐条补成「发生了什么 + 下一步怎么办」，并且给出路：`INVALID_SPLIT` 说切点要落在片段内部且对齐整帧，
  `SUBTITLES_MODEL_MISSING` 说模型放哪儿（asr 目录或 `AGENTCUT_ASR_MODELS`），`OUTPUT_INVALID` 说候选
  文件已销毁、最终名一次都没出现，`INVALID_REFRAME` 说先画遮罩再按跟踪主体。补完 116 码 / 120 提示、
  0 条落到英文；多出的 4 个 key 是适配层与任务运行器的码，门禁按白名单承认。
- 新门禁 `tests/error_vocabulary_check.py`（不到 1 秒，不碰媒体）把这件事变成永久约束：Python 侧扫
  `EditorError("CODE"…` / `code="CODE"` / `"code": "CODE"`，TypeScript 侧扫提示表 key，断言前者是后者
  子集；另要求每条提示含中文、长度 ≥ 12 字（挡住「知道了」这种废话），并断言 key 不重复。
  `tests/desktop_error_naming_check.ts` 另抽 14 个码走 `explain()` 真跑，确认运行时确实说中文并把引擎
  点名的素材/片段/轨道织进句子。AGENTS.md 的「必须保留的约束」加了一条：新增或改名错误码必须同时补
  界面提示。
- 五条变异测试逐条红：删一条提示 → 点名 `OUTPUT_INVALID`；提示写成英文 → 「not Chinese」；缩成
  「导出失败了。」→ 「too thin」；同 key 写两遍 → 「duplicate keys」；在 Python 里新增一个没人翻译的
  码 → 红在 `INVALID_CAPTIONS_TARGETX`。两头都钉得住：漏界面红，漏引擎也红。
- 包内验收顺带学到一件事：`sub/dir.mp4` 与 `x.mov` 这两种坏文件名都在**契约层**就被拒（422
  `INVALID_REQUEST`，details 里给出 `filename must end with .mp4 …`），`OUTPUT_NAME_INVALID` 是任务层
  更晚的拒绝。所以包内改成量六条真报得出的码：`UNKNOWN_PRESET`、`INVALID_TEXT`、`INVALID_SPLIT`、
  `DUPLICATE_ID`、`MEDIA_PATH_INVALID`、`REVISION_CONFLICT`。还有一个自己的坑：验收脚本原来会把请求体里
  的 `expected_revision` 一律改写成当前值，于是「旧 revision 要 409」这条永远测不到——改成显式的
  `current` / `stale` 标记之后才真的走到 `REVISION_CONFLICT`。
- 契约、reducer、capabilities、工程 schema 与所有错误码本身一字不动——改的只是界面怎么说人话。
- 发布验收：`build_engine.py`（`FREEZE=0`）+ `npm run dist`（`DIST=0`）。包内实例 `e6f5802e3889` 报
  `app_version=1.81.0`；`package_check_181.py` 在打包后的引擎上真跑出六条码拒绝
  （`UNKNOWN_PRESET`、`INVALID_TEXT`、`INVALID_SPLIT`、`DUPLICATE_ID`、`MEDIA_PATH_INVALID`、
  `REVISION_CONFLICT`），每条都带 code、句子与非空 details；asar 里抽 5 条 1.81 新增的中文提示都在。
  `ruff`、`npm run typecheck`、12 项桌面 TS、串行套件 **68/68** 全绿；原生窗口 1480×900 标题栏
  「引擎在线 v1.81.0」（`AgentCut-1.81-原生窗口.png`），关闭无残留。
  便携版 189,771,874 字节 SHA256 `7827DE9AB22889FF076EBF110166514110730DCF288E4702986FA74C01351E8C`；
  安装版 189,932,591 字节 SHA256 `842BA630D1EF89029DAC5D1C45A30FD9F014017C833FDC0B75D4C2D10A0BCEF5`。
  未签名，NSIS 向导未点击验收。

## 1.82.0 空轨上的整轨按钮不再可点

- 这条缺陷是我自己上一轮造出来的：1.79 把「这条轨上没有片段」统一成四条整轨路由的拒绝，答案对了，
  但界面上那三个按钮照旧亮着——人要先按一次、看到弹错，才知道这条轨是空的。按了只会弹错的按钮不该
  亮着，这是这一路修下来反复用的标准（1.75 的「每个拒绝都要指得出出口」的反面：出口在按之前就该给）。
- 修法是加一处判断而不是加三份：`desktop/src/effects.ts` 里的 `trackToolBlocker(trackId, clips)`
  返回 null 或原因句 `EMPTY_TRACK_HINT`，`Timeline.tsx` 的整轨响度 / 整轨去空白 / 自动闪避统一
  `disabled={!!emptyTrack}`、`title` 就是那句原因。句子里给的两条出路都是真能走通的：把素材拖上时间线，
  或者从时间线上方的面包屑进那条预合成——不是「请重试」这种话。
- 门禁两头钉：`tests/desktop_track_gate_check.ts` 测函数（空轨挡、有一条就放行、**别轨的片段不算数**——
  正是嵌套之后外层那条同名空轨的形状、混合时不被别轨否决、句子必须含两条出路）；
  `tests/empty_track_check.py` 读 `Timeline.tsx` 测接线（调用谓词一次、`disabled={!!emptyTrack}` 恰好
  三处、`: EMPTY_TRACK_HINT` 恰好三处、不许留下 `disabled={!clips.length}` 这种会漂移的第二份规则）。
  为什么接线放在 Python 侧：`desktop_ts_check.py` 是用壳层自带的 esbuild 把 `.ts` 打成临时 `.mjs`
  再跑，`import.meta.url` 指向那个临时目录，读不到仓库里的源文件——所以「测函数」归 TS 门禁、
  「测接线」归 Python 门禁，两边都能红。
- 五条变异测试逐条红：谓词恒 null、`clip.track_id` 比成 `clip.id`、`some` 改成 `every`、提示句去掉
  「面包屑」、表头把 `emptyTrack` 写死成 null。前四条红在 TS 门禁，第五条红在 Python 门禁——也就是说
  「函数对但没接上」和「接上了但函数错」都过不了关。
- 引擎侧一字未动：路由、契约、reducer、capabilities 与 1.79 的拒绝完全照旧；这是纯界面诚实性修复。
- 发布验收：`build_engine.py`（`FREEZE=0`，staged 324.9 MB）+ `npm run dist`（`DIST=0`）。包内实例
  `bd6c11881822` 报 `app_version=1.82.0`；`package_check_182.py` 在打包后的引擎上重跑四条整轨路由对空轨的
  拒绝（404 + `this track holds no clips` + `details.track_id`），并在 asar 里读到帮助条目
  「时间线·空轨不给你按」与那句灰化原因（只测能活过压缩的 UI 文本，不测被改名的标识符）。
  `ruff`、`npm run typecheck`、13 项桌面 TS、串行套件 **68/68** 全绿；原生窗口 1480×900 标题栏
  「引擎在线 v1.82.0」（`AgentCut-1.82-原生窗口.png`），关闭无残留——截图确认的是版本与工作台完整渲染，
  灰化本身由门禁在函数与接线两层断言。
  便携版 189,771,146 字节 SHA256 `81DF88E1F44BAD75221CA655847AB03AEDEB7C71809A27D8BD163E1AF57B3C71`；
  安装版 189,931,867 字节 SHA256 `4D8375BEE89FCA3765EE13DEAD217A00CF6E7A3845A77CC42A4E07A2F65B195D`。
  未签名，NSIS 向导未点击验收。

## 1.83.0 色阶节点与自动调色：把「一键拉开层次」接进同一条链

- 待办清单从 1.8 起一直挂着「亮度曲线与色阶、LUT、色彩管理」。逐条核对代码后确认：**每通道的色调曲线
  早就在**（`GradeCurve` + `CurvePad`，1.16 起），缺的是**色阶**（输入黑场／白场＋中间调 gamma，也就是
  Photoshop/达芬奇的 Levels、剪映的「色阶」）和**自动调色**（剪映的「一键增强」是普通人最先按的那个按钮）。
  AGENTS.md 把「亮度曲线」列在仍待实现里是**过时的自我描述**，本轮一并改准：仍缺的其实是跨通道的东西
  （3D LUT、色域矩阵与色彩管理）。
- 新增 `levels` 节点走的是这条链唯一的那条路：它仍然只是**每通道一条函数**，所以整条链继续塌成每通道一张表，
  导出的 `lutrgb` 与浏览器的 `feComponentTransfer` 读同一条折线——**没有为它新增渲染阶段，也没有第二套求值**。
  两个输入点被加进自适应采样网格（`_curve_knots`），否则一条 30→208 的陡拉伸会在拐点之间被弦裁成另一条线。
  写入用的还是既有的 `clip.grade`，所以 reducer、历史、幂等回执、撤销全都照旧。
- 新端点 `POST /clips/{id}/auto-grade` 与 MCP 的 `clip_auto_grade`（write）：引擎用同一支 FFmpeg 把**片段自己的
  源区间**解成最多 24 帧、宽 256 的 rgb24，按 BT.601 权重算亮度直方图，取「两端各只有 `percentile` 份额像素
  落在其外」的级当黑场白场（默认 0.5%，与剪映/PS/达芬奇的一键拉伸同一族规则，而不是 min/max——一个镜面高光
  就能把白点定在 255 从而压扁整张画面）。`mode=luma` 只加一个节点且不会凭空造出色偏；`mode=rgb` 三个分通道
  节点能拉回偏色素材。`apply=false` 只把命令与量到的数交回来，`dry_run` 不写，重放 `request_id` 命中同一回执。
- **量到的数必须进回复**：`frames`、`pixels`、`skipped_pixels`、分析尺寸、逐通道两点都如实报出；画面本来就占满
  所测量程时**不写节点**（`commands: []`、revision 不变），这一形状抄 1.69 的「稳定强度 0 一个关键帧都不写」。
- 再按一次是**重算并顶替**，不是叠一层——和 1.69 给画面稳定定的规矩一致；`replace=false` 时点名 `AUTO_GRADE_CONFLICT`
  并把 positions 报出来。五条拒绝各带 code＋句子＋非空 details 且不涨 revision：`AUTO_GRADE_INVALID`（音频、文字层、
  停在非画面轨上的视频）、`AUTO_GRADE_FAILED`（一帧都解不出来）、`AUTO_GRADE_NO_RANGE`（两点相距不足 16 级，
  details 报 low/high）、`AUTO_GRADE_CONFLICT`、`AUTO_GRADE_LIMIT`（超过 8 个节点，并说明改用 luma 只占 1 个）。
  `tests/error_vocabulary_check.py` 把五条中文说法一并钉住（121 码 / 125 提示，0 条落到英文）。
- 途中量出一个真缺陷，而且是被**图片素材**抓出来的：给单帧 PNG 套 `fps` 滤镜，FFmpeg 退出 0 却**一帧都不输出**
  （实测 `pipe:1` 返回 0 字节，去掉 `fps` 就有 55296 字节），于是自动调色对「给这张照片拉开层次」这种最常见的
  用法只会回 `AUTO_GRADE_FAILED`。修法是给 `decode_rgb` 一个 `spread` 开关，铺开取不到帧时按「不做时间铺开」
  再解一次；`tests/autograde_check.py` 用真实的一真一假平板把这条路钉住。
- 门禁 `tests/autograde_check.py`（约 1 分钟）断的是产物不是意图：三组色阶设置下**256 个输入级逐一**比对
  ①导出的 `lutrgb` 真跑 FFmpeg 的结果、②浏览器拿到的 256 项表、③按发布公式独立写出的参考值，两端差 ≤1 级；
  分通道节点在导出表达式里把 g/b 原样交回（`dict(re.findall(...))=="val"`），浏览器侧绿通道逐点等于输入。
  夹具是**自己声明范围的**：先 `-vf lutrgb='val*0.70+30'` 把一条确定性灰阶斜坡压进 [30,208]，再用本文件自己写的
  百分位计数确认夹具真的是 [30,208]（夹具不老实就会当场红，而不是造出一条莫须有的引擎缺陷）；随后断言引擎
  量回的数与文件自量的数差 ≤2，并且把编译出的节点真喂给同一支 FFmpeg 重跑那条素材——成片量回 [≤4, ≥251]，
  证明拉伸发生在像素上而不是只发生在请求里。
- 界面这一侧沿用 1.82 立下的规矩：**量不到画面的按钮是灰的**，判断只写在一处
  （`effects.ts` 的 `autoGradeBlocker`），灰化和 title 用同一个返回值；`tests/desktop_autograde_check.ts` 逐条测
  那个谓词（视频/图片放行，文字、音频、停在音频轨上的视频各挡一次，引擎未就绪单独一句），
  `tests/autograde_check.py` 再测接线（谓词只被调用一次、`disabled={Boolean(autoBlock) || locked}` 恰好一处、
  title 用的就是同一个值），两头都能红。上限数字一律来自 `capabilities.grade_limits.levels_*`，界面不自己数。
- `self_check.py` 现在通过真实 MCP stdio 调 `clip_auto_grade`：对**嵌在预合成里**的那一段（`sequence_id=mcomp`）
  只要计划，断言 `committed=false`、revision 不变、回来的命令是 `clip.grade` 且第一个节点 `kind=="levels"`，
  并且量到的两点是递增的真实数——Agent 侧的「进得了合成」与「分析不写库」第一次被同一条链路量到。
- 仍没做、也不假装做了的：色阶节点的时间动画（和柔焦/清晰同一类，链子的权威是每通道一张表，逐帧换表就等于
  两套求值）、3D LUT 与色域矩阵/色彩管理（跨通道，会把「一条链塌成一张表」这条不变量打断，需要成对渲染阶段的
  新架构）、自动调色里的中间调自动 gamma（本版只做拉伸，不猜你想要的对比）。
- 发布验收：`scripts/build_engine.py --verify`（冻结引擎冷启 620 ms 报 ready，`tools`/`--help`/`mcp`
  三种模式都活着）+ `npm run dist`。**包内实例**（`package_check_183.py`，跑的是 `desktop/resources/bin/
  agentcut/agentcut.exe`，即打进安装包的那一个二进制）报 `app_version=1.83.0`，capabilities 里
  `grade_levels`/`clip_auto_grade` 为真、`grade_limits.levels_*` 与 `limits.auto_grade_samples_max` 都在；
  用真实 FFmpeg 造一条压进 [30,208] 的素材、经 HTTP 导入并上轨后，`auto-grade` 量回的黑场白场落在
  [26,34]×[202,212]，`apply=true` 写入的第一条节点 `kind=="levels"` 且 `black*255` 与量到的差 <1，
  对音频片段按下去回 `AUTO_GRADE_INVALID`＋`details.asset_kind="audio"`，且**拒绝不涨 revision**（再 GET
  一次工程确认）。打包产物 `app.asar`（5.6 MB）里读到「色阶」「自动调色」「检查器·自动调色」
  「量黑场白场并拉开」「替换已有色阶」与 `AUTO_GRADE_CONFLICT:` 的中文提示——只测能活过打包的 UI 文本。
- 五条变异测试逐条红（每条跑完原文件字节级还原）：`_levels_function` 的 `(value-black)/span` 改成
  `value` → 红在 256 级逐点比对；`MIN_SPAN_LEVELS` 判断改成恒假 → 红在平板素材那条 `AUTO_GRADE_NO_RANGE`；
  路由的 `if not request.apply:` 翻成 `if request.apply:` → 红在「apply=false 不该写库」；
  `autoGradeBlocker` 的引擎未就绪那句改成 `null` → 红在 TS 门禁；界面把
  `disabled={Boolean(autoBlock) || locked}` 换成 `disabled={locked}` → 红在 Python 侧的接线断言。
  也就是说「编译错、判断错、不守计划语义、谓词错、接上了但灰化没走谓词」五种情形都过不了关。
- 门禁：`ruff check`／`ruff format --check` 干净，`npm run typecheck` 干净，14 项桌面 TS 全过
  （新增 `tests/desktop_autograde_check.ts`），`tests/self_check.py` 通过（真实 MCP stdio 里
  `clip_auto_grade` 工具存在、schema 说得出四个旋钮、`readOnlyHint` 为假，并对合成里那段均匀暗板
  如实回 `AUTO_GRADE_NO_RANGE`＋low/high 且不涨 revision）。
- 便携版 189,786,455 字节 SHA256 `117B9613D4655E828AC83FD1BA20A5B27A52B3004C7393C583D7484DE9618591`；
  安装版 189,947,176 字节 SHA256 `77624BA4F1996595A7ABEF05A97F1AE057984F84168DCB8A9C6E68DE49603087`。
  根目录 `AgentCut.exe` 同步为该便携版。未签名，NSIS 向导未点击验收。
- 原生窗口：双击便携版实测，PrintWindow 抓到 1480×900 的工作台完整渲染，标题栏写着
  「引擎在线 v1.83.0」，关闭后残留窗口数 0。截图只证明版本与整窗渲染；色阶卡片与灰化按钮本身
  由上面的门禁在函数与接线两层断言，本轮没有在原生窗口里逐控件点击验收。

## 1.83.1 自动调色量的是片段真正播的那段源

- 缺陷是 1.83 自己带进来的，而且是被自己写下的那句「按片段自己的源入出点」骗过的：路由把
  `clip.duration_ticks` 当成**源**区间长度交给解码器，可 `duration_ticks` 是**时间线**长度。恒定速率下
  片段真正读掉的源是 `duration × speed_percent / 100`（渲染器写 `setpts=(PTS-STARTPTS)/rate` 就是这个
  意思），于是 200% 的片段该读两秒却只读了一秒，量到的黑场白场来自人根本没看到的帧，写回的色阶节点
  是按一段不存在的画面做的拉伸。
- 找到它的方式不是猜，是把同一条链上已有的权威摆在一起对表：`/track` 那条路由早就写着
  `speed = clip.speed_percent / 100`、`start = source_in + from*speed`、`consumed = frames*frame_ticks*speed`，
  而 `speed.consumed_source_ticks(clip, quantum)` 是渲染器与时间线共用的「这条片段一共读掉多少源」，
  连变速曲线都算得出来。自动调色却自己拿了一个时间线数字——同一件事在两处不一致，就是缺陷。
- 修法是把窗口交给那个权威：路由改传 `consumed_source_ticks(clip, settings.frame_ticks)`，并把真正读掉的
  区间如实回在 `auto_grade.measured.window`（`source_in_ticks` / `source_ticks`），人和 Agent 都看得见
  这组数是按哪一段源量出来的。
- 门禁是一段差分测量，不是「参数有没有传」的断言：造一条 2 秒素材，前一秒亮度铺 [20,60]、后一秒铺
  [180,220]（`geq` 用 `gte(T,1)` 按时间分色），同一条素材上放两个 1 秒片段，一个 100%、一个 200%。
  100% 的那个必须只看到自己那一秒（白场 ≤72），200% 的那个必须看到两秒（白场 ≥198），回复里的
  `window.source_ticks` 正好差一倍。带着旧代码跑，200% 那条会退回 [20,60] 当场红——这就是这条门禁
  能够失败的意思。
- 顺带把「谁该拒绝变速」对齐清楚：`/stabilize` 与 `/track` 拒绝变速曲线，是因为它们的抵消按「一帧源画面
  对一个关键帧」算；自动调色不是——它只要求「读片段真正播的那段源」，而这件事 `consumed_source_ticks`
  已经算得准，所以这里不需要新增一条拒绝，只需要一个正确的窗口。

## 1.84.0 通道混合：调色链第一次允许跨通道，权威从一张表变成一份有序阶段列表

- 从 1.8 起「色彩节点图的分层与连线」后面一直挂着三样东西：3D LUT、色域矩阵、色彩管理。逐条读代码后
  确认它们卡在同一个前提上——这条链的**不变量**是「每个节点都是每通道一条函数，所以整条链塌成每通道
  一张表」，而这三样都是跨通道的：输出的红依赖输入的绿和蓝。要往前提一步，必须先让编译器会说「多阶段」。
- 本版做这个前提，并做一个能两端严格对齐的跨通道节点：`matrix` 通道混合（3×3 作用在存储值上）。
  `grade_stages(color)` 把链子编译成有序阶段列表——**连续**的每通道节点仍然合并成一张表（老行为一点不
  少），遇到跨通道节点就断开这一组，把矩阵作为独立阶段插入；`grade_filter` 依次拼出
  `lutrgb=…,colorchannelmixer=…,lutrgb=…`，`grade_tables` 返回 `{"id", "stages":[…]}`，浏览器在同一个
  `<filter>` 里按同一顺序摆出 `feComponentTransfer` / `feColorMatrix` 原语。`color_filter` 里引用的还是
  一个 id（整条链的 id），所以界面侧的引用方式没变。
- 两端为什么能声称一致而不是「差不多」：FFmpeg 的 `colorchannelmixer` 与 SVG 的
  `feColorMatrix type="matrix"` 都是对**存储的 8 位值**做同一个仿射映射，而滤镜上已经写了
  `color-interpolation-filters="sRGB"`，浏览器就不会先做线性化。矩阵只有九个系数，没有常量偏移——
  `colorchannelmixer` 也表达不了偏移，所以契约里就没有偏移这个字段。
- 强度是免费的：`out = in + mix·(M·in − in)` 仍然是矩阵（`I + mix·(M − I)`），所以 `mix` 折进同一份九个数，
  两端继续读同一份。混合方式则**故意不给**：`in × M·in` 这类非线性复合不再是矩阵，一旦允许，两端就没有
  同一份数可读了。契约里 `GradeMatrix` 没有 `blend` 字段，`extra="forbid"` 会当场拒掉带 `blend` 的请求；
  界面上那行说明写在强度上方，而不是把选择器灰在那里让人猜。
- 这不是色彩管理，也不假装是：真正的基色转换发生在线性光里，8 位阶段会在暗部留下断层。这一点写在节点
  卡片的说明、契约的 docstring 和 Help 里，`features.color_space_transform` 的含义不变（只换传递函数）。
- 门禁 `tests/matrix_check.py` 的关键是**不能用灰度板测跨通道**：一条 256 级灰阶上 R=G=B，把绿列和蓝列
  对调也照样通过。所以三组矩阵（BT.709 灰度、列对调、暖调）各驱动三张单基色板（一张只让红从 0 走到 255，
  另两个通道钉在 0），256 级 × 3 输出通道 × 3 板 × 3 矩阵 = 6912 个数与独立写出的参考乘法比对，实测
  ≤1 级。另外断言：`mix=0` 与恒等矩阵编译成空、`mix=0.5` 折进矩阵、曲线与矩阵换序编译成两条不同的链并
  渲染出不同画面（红通道最大差 >8 级）、`blend`／越界／长度不对被契约拒、HTTP 写入后浏览器拿到同一份
  九个系数、导出图里确实带 `colorchannelmixer`。`tests/desktop_matrix_check.ts` 钉住 3×3 → 20 槽的摆法
  （行主序、每行补两个 0、alpha 原样通过）。
- 消费者跟着改的是形状不是语义：`grade_tables` 的返回从 `{id,r,g,b}` 变成 `{id,stages:[…]}`，
  `grade_check.py` / `gradelevels_check.py` / `lut_check.py` / `autograde_check.py` 里读表的地方改为取
  那唯一一段，并把「只有一段」本身写成断言——纯每通道的链子要是被编译器拆成两段，门禁就该红。
- 用老办法又抓到一个自己造出来的洞：把新的 `GradeMatrix` 加进 `GradeBranch`（并联分支的联合）之后，
  **并联里放一个矩阵**就能把引擎打穿——`node_function` 对分支求值时落到 wheels 那条兜底分支，
  `AttributeError: 'GradeMatrix' object has no attribute 'gamma'`，一条 Agent 发得出的 `clip.grade`
  变成 500。修在契约而不是补在编译器里：`GradeBranch` 不含 `matrix`（并联取各支平均，跨通道映射平摊进
  不了任何一张表），请求当场 422 并点名 `branches`；TS 侧 `GradeBranch = Exclude<GradeOperation, GradeMixer>`
  同步跟上，`replaceBranch` 用「既不是并联也不是矩阵」收窄而不是硬转。`tests/matrix_check.py` 把这两种
  形状都断下来——这是「新增一个联合成员」必须连带检查的地方，光看新节点自己跑得通是看不见的。
- 五条变异测试逐条红（每条跑完原文件字节级还原）：`_matrix_of` 折强度时丢掉恒等项 → 红在折数比对；
  矩阵不再断开每通道那一组 → 红在阶段顺序；`colorchannelmixer` 里把 `rg`/`rb` 两个名字对调 →
  红在三张单基色板的逐点比对；`feColorMatrixValues` 的 alpha 行挪一格 → 红在 TS 门禁；
  契约改成允许矩阵带 `blend` → 红在那条「契约必须拒」的断言。
- 验收：`ruff check` 与 `ruff format --check` 干净（99 文件）、`npm run typecheck` 干净、
  **15 项桌面 TS** 全过（新增 `tests/desktop_matrix_check.ts`）、串行套件 **69/69**
  （新增 `tests/matrix_check.py`，`self_check.py` 另断 Agent 的 schema 里能看到 `matrix` 与
  `coefficients`）。`build_engine.py --verify` 冻结引擎 ready；**包内实例**（打进安装包的那一个二进制）
  报 `app_version=1.84.0`，capabilities 有 `grade_matrix` 与 `grade_limits.matrix_limit`，
  写一条 `[curve, matrix]` 后 `preview-manifest` 交回的阶段序列是 `["lut","matrix"]` 且九个系数一字不差，
  带 `blend` 的请求 422 点名 `blend`，真渲染一条灰板后测得 **[143,132,120]**、按参考乘法算的是
  **[143,131,119]**（一路过 H.264，差 ≤1 级）。`app.asar`（5.6 MB）里读到「通道混合」「输出红」
  「来自红」「灰度 BT.709」「跨通道 3×3」「调色节点·通道混合」与那句「不是色彩管理」。
  便携版从 ASCII 路径双击启动实测 1 个窗口、标题「AgentCut 剪辑台」，关闭后残留 0。
- 便携版 189,788,629 字节 SHA256 `B3BCD81DAD6725CEF13CF2EC25075CFBA32867359FCDB1E3AE2ACCC5F6244D8A`；
  安装版 189,949,348 字节 SHA256 `05D6C6A3145058B35973E7C2BF862DFFF3CB805B8D91C7CCF58073E034740C6B`。
  根目录 `AgentCut.exe` 已同步。未签名，NSIS 向导未点击验收；本轮没有在原生窗口里逐控件点击新的通道混合
  卡片（界面侧由 TS 门禁、HTTP 断言与 asar 文本三处钉住）。
- 发布验收：`build_engine.py --verify`（冻结引擎冷启后 ready、`tools`/`--help`/`mcp` 三种模式都活着）
  + `npm run dist`；**包内实例**单独量过一次——同一个二进制、同一条按时间分色的素材，100% 的 1 秒片段
  量到 [18,58]，200% 的 1 秒片段量到 [18,217]，回复里的 `window.source_ticks` 正好差一倍，
  `/v1/info` 报 `app_version=1.83.1`。便携版从 ASCII 路径双击启动实测出现标题为「AgentCut 剪辑台」的窗口，
  关闭后窗口与进程数都归 0（界面代码本轮未改，原生窗口截图沿用 1.83.0 那一张）。
  串行套件 **69/69**、`ruff check`／`format --check`、`npm run typecheck` 全绿。
- 便携版 189,785,387 字节 SHA256 `DA986B733F86E73E366932D70FFC4BBC13D773BFEA7BA3D75F397C32F5A567F2`；
  安装版 189,946,104 字节 SHA256 `89C210742B869A508AB8EA94A7C024C946B71D599F0D2505F0EF65ECFBEEBE53`。
  根目录 `AgentCut.exe` 已同步。未签名，NSIS 向导未点击验收。

## 1.85.0 遮挡久了不是跟丢：被挡住的每一帧都在整幅画面上重新找

缺陷不是新需求，是 `tracking.py` 的模块文档与代码对不上账。文档第 4 行写着「目标藏起来再回来是被
重新找到，而不是被遮挡物改写成别的形状」，而 `track_box` 干的两件事都不支持这句话：猜窗超过
`GAP_LIMIT = 30` 帧就 `break`，把整条路径截到最后一次真实看到的那一帧；遮挡期间的找回只在**匀速外推
点周围 `search*2` 的局部窗口**里搜。两条合起来的后果是：一个人从柱子后面走过去超过一秒，或者主体回来
时不在外推点附近，路径就断掉，界面只说「在第几秒跟丢」——文档承诺的那件事从来没发生过。找它的方式是
把两处摆在一起读：同一个文件里既写着「会被重新找到」，又写着一段 `break`。

修法是加一次**由粗到细的全画面重找**，判据一个字都不换。遮挡期间每一帧，如果局部搜索没够到门槛，
就把这一帧与 frame 0 的锚点模板各按 4 倍盒式平均缩小（`_shrink`），在 1/4 尺寸的小图上把整幅画面扫一遍
（`_sweep`），拿胜出的位置回全分辨率用同一个模板、同一个门槛再判一次，过了才算找回。所以「是不是它」
永远由原来那把尺子决定，小图只负责提出去哪儿看。小图不是省事的近似：223×111 个 1156 像素的窗变成
57×29 个 64 像素的窗，工作量差 270 倍，而真正做决定的还是全分辨率那一次打分。找回之后把速度置零——
一次跨过大半个画面的移动不该被当成相机平移继续外推。

猜的那一段现在有主人了。窗口闭合时，每个猜测点按「离找回点越近挪得越多」线性挪动，起点仍贴着最后一
次真实看到的位置，终点正好落在找回的位置；挪动的最大值以 `gap_closure` 如实回给人和 Agent（实测那条
42 帧遮挡 + 期间横移 48 px 的素材，找回时最多挪了 0.199 个画面宽——这就是「这段路其实在猜」的证据）。
另外三个新数一起进回复：`reacquire`（这次开没开）、`reacquired_frames`、`reacquired_at_ticks`。

数字只有一个主人：`TRACK_GAP_DEFAULT = 60` / `TRACK_GAP_MAX = 240` / `TRACK_REAQUIRE_SCALE = 4` 定义在
`contracts.py`，`tracking.py` 与 `MaskTrackRequest` 都从这里取，`capabilities.limits.track_gap_default` /
`track_max_gap_frames` 把同样的数下发出去。默认猜窗从 30 提到 60 是因为重找让「超过一秒」这件事有了
出路，而不只是因为可以猜得更久。

画面稳定显式不走这一步：`stabilize.py` 给四个锚点传 `reacquire=False, max_gap=ANCHOR_GAP(30)`。锚点是
画面上固定的一块地方，不是物体——允许它跳到「画面里另一处很像的地方」，等于把一次剪辑硬读成相机移动
了两百个像素，那会写出一条谁也看不出错的抖动补偿曲线。这条 opted-out 由门禁的一行源码断言钉住，和
`track_box(reacquire=False)` 的行为对照配成一对。

门禁加了三段，关键全在「对照」而不是「跑通」：

- `reacquisition_suite`：素材是 1.00–2.40 秒被灰条盖住（42 帧，超过原来 30 帧的猜窗）、并且在 1.70 秒
  还横移 0.15 画面宽（48 px）的目标。开着重找：90 帧全部量到、`lost_at_ticks` 为空、2.40 秒处找回、
  `gap_closure` 0.199；对照组同一条素材、同一个 `max_gap_frames=60`，只把 `reacquire` 关掉：停在第 30
  帧并报 1.00 秒跟丢。两条之差只能来自那次整画面扫描，不能来自更宽的猜窗。另断遮挡窗口内的每个猜测点
  都落在两次真实位置张成的区间里（不许外推出画面），以及找回之后 0.1 秒外的点跟的是**移动后**的真值。
  计时也断（90 帧含 42 帧遮挡实测 4.1 秒，上限 120 秒）——这一步不是免费的东西，价格要写在纸上。
- `decoy_suite`：管住这把尺子的两面。目标永远消失、但在别处出现一个**同样大小**的方块 → 会被认出来
  （终点离它 0.40 px）并如实报 `reacquired_frames=1`、`gap_closure` 0.183：画面里有两个一样的东西时机器
  分不开，这不是缺陷，隐瞒才是。换成一个大三倍的平板方块 → 不跟（仍在 1.50 秒报跟丢、只有 45 帧量到），
  证明重找认的是模板形状而不是「任何亮的东西」。同段还断 `stabilize.py` 里确实写着 `reacquire=False`。
- `interface_suite`：`reacquire` / `reacquired_frames` / `reacquired_at_ticks` / `gap_closure` 四个字段必须
  出现在 `engine.ts` 的 `maskTrack` 回复类型里，`store.ts` 的提示必须真的读出「在第几秒找回」和「挪了
  多少画面宽」，按钮 title 与帮助页必须改成描述重找——否则人和 Agent 读到的还是旧故事。

HTTP 段尾部补了同一条素材的两次真写：`reacquire=false` 写不进 45 帧以外，开着写满 90 帧、落库的 `mask_x`
曲线在找回 2 帧之后逐点跟住横移后的真值；`capabilities.limits.track_gap_default/track_max_gap_frames` 被
读回；`max_gap_frames=241` 由契约 422 拒掉且 revision 不动。旧的 0.6 秒短遮挡用例也加了一条新断言：局部
搜索自己找回的目标**不算**一次全局重找（`reacquired_at` 必须为空）——这条断言是为了让「回复里的找回次数」
这个数只能描述它自己说过的事。

六条变异逐条红（每条跑完原文件按 sha256 还原并复验）：`_sweep` 不更新胜出位置 → 红在长遮挡那条
`lost_at_ticks is None`；粗图胜出坐标换算回全分辨率时用错倍数 → 红在同一处；关掉猜窗的落地校正 → 红在
`gap_closure > 0.02`；任何一次闭合都记成重找 → 红在短遮挡新增的那条 `reacquired_at` 为空；把稳定锚点的
`reacquire=False` 去掉 → 红在源码断言；`capabilities` 里的 gap 上限改回写死的 120 → 红在 HTTP 段读回
`track_max_gap_frames == 240` 那条。有一条变异第一次跑没红，于是把它换掉了：原本打算改成「不看全
分辨率分数就接受粗图胜出」，但接受之后仍然要过同一个 `score < floor` 判定，所以那句改动等价于没改——
门禁不为这种假变异作证，改成了上面那条真的会走错的坐标换算。

一次自己造成的假故障值得记下来：这一轮曾把「串行套件 + 冻结引擎构建 + electron-builder 打包 + 包内验收」
四件事同时跑，结果 15 个门禁在 0.5 秒内报 `FileNotFoundError: [WinError 2]`（FFmpeg 起不来）。那不是代码
坏了：把它们串行重跑，69/69 全绿。媒体类门禁的进程创建与 `desktop/resources` 不该和 PyInstaller、
electron-builder 抢同一段时间，以后一律串行。

验收：ruff check 与 format --check 干净（99 文件）、`npm run typecheck` 干净、15 项桌面 TS 全过、串行套件
69/69、`self_check.py` 通过（新增 `clip_track` 的 schema 必须说得出 `reacquire` / `max_gap_frames` /
`estimate_scale` / `search_radius`）；`build_engine --verify` 冻结引擎 ready，包内实例报 `app_version=1.85.0`，
`capabilities` 交回 gap 上限 240 与默认 60，同一条长遮挡素材在包内 HTTP 上 `reacquire=false` 量到 30 帧、
开着量到 90 帧并在 2.40 秒找回（`gap_closure` 0.199），`max_gap_frames=241` 422 且 revision 不动；
`app.asar`（5,573,802 字节）里读到 5 处「重新找」、2 处「重新找到」、「按找回的真实位置校正」以及
`gap_closure` / `reacquired_frames` / `reacquired_at_ticks` 三个字段名；便携版从 ASCII 路径启动实测 1 个窗口、
标题「AgentCut 剪辑台」，关闭后残留窗口 0、进程 0。便携版 189,793,760 字节 SHA256
2E52FAF07D1ADAB12E5CEABCAF22000E88AEF67811BC1170C4FD6EBEEF33C1F2，安装版 189,954,474 字节 SHA256
E977E1479C74C5522312F0627B93C42B8CC488481A2D2CC02D57607BC741D117，根目录 AgentCut.exe 与便携版一字不差；
未签名，NSIS 向导未点击验收，本轮也没在原生窗口里逐控件点一次「跟踪主体」（界面侧由类型、接线与 asar
文本三处钉住）。

仍没做也不假装做了的：多目标跟踪（一次仍只跟一个方框）；重找回仍然拿 frame 0 的锚点模板比对，主体在被挡
期间换了外观（换衣服、转成侧影）不会被认出来——那需要模板更新，而模板更新会让「这条路径到底跟的是谁」
再也说不清；遮挡窗口里的点仍然是猜（`predicted_frames` 与 `gap_closure` 如实报出，猜的最多点被拉到两次
真实 sighting 之间，但不假装是量出来的）；遮罩的旋转仍不估计；路径遮罩仍只跟平移。

## 1.85 补：分割后的片段跟踪有了门禁（引擎一字未动）

重找做完后接着问「这条链上还有哪个数没人验过」，答案是跟踪在**带 `animation_offset_ticks` 的片段**上
从来没被测过：分割出的尾巴同时用三把时钟——分析读的源区间 `source_in_ticks + from·speed`、落库的
关键帧刻度 `offset + 本地刻度`、渲染器采样的动画时钟。之前所有跟踪用例的 offset 都是 0，三把时钟叠成
一把，所以任何一把错位都测不出来。

先用一次性探针量过一次（不留在仓库里，因为它的结论已经由下面的永久断言接管）：把 3 秒的运动素材在
1 秒处切开，尾巴 position/source_in/animation_offset 都是 1 秒，把遮罩画在这段真正先出现的主体位置上，
跟踪 45 帧后导出成片，逐帧量遮罩揭示区的质心：t=1.4 秒 (0.483, 0.536) 对物体 (0.483, 0.537)、t=2.2 秒
(0.617, 0.319) 对 (0.617, 0.321)，都差 0.2 px；t=2.8 秒（最后一个跟踪点 2.467 秒之后）质心落到
(0.704, 0.397) 而物体已在 (0.717, 0.427)，亮像素从 484 掉到 180——这正是「曲线在端点夹住、遮罩停在最后
跟到的地方」应有的样子。结论：这条缝是好的，不需要修。

探针第一次跑出的「误差 131 px」是我自己的夹具不老实：分割后尾巴**继承**了头部曲线的时钟值，而我把期望
写成了 `path_at(本地刻度)`（少加 `source_in`），并且没把遮罩先画到物体上就按默认画在 (0.25, 0.5) 的位置
去跟——于是跟的是一段根本没被框住的画面。两处都是我读错，不是引擎错；把它记下来是因为「报出一个大误差」
和「引擎真有大误差」这两件事在日志里长得一模一样，只能靠先核对夹具来分辨。

于是把结论做成永久断言，进 `tests/tracking_check.py` 的 `http_suite`：分割 → 把遮罩画到尾巴真正先出现的
主体位置（`clip.mask` 一次编辑）→ 走真实路由跟踪 45 帧 → 要求 (1) 落库的 `mask_x` 刻度恰好是
`T + i·frame_ticks`（写在原时钟上，不是本地时钟），(2) 窗口内每一点的 `mask_x` 与 `path_at(1.0 + 本地秒)`
差 < 0.012（实测最大 1.14 px / 320 px 画面）。两条各管一把时钟：刻度错位红第一条，读错源区间红第二条。
变异验过两条都能红：把 `_apply_mask_track` 里的 `offset` 改成 0 → 红在刻度清单（窗口只剩 15 个点）；把
路由的 `start` 改成不含 `source_in_ticks` → 红在逐点值（差到 0.061，即 19 px）。两条跑完原文件按
sha256 还原、复跑全绿。

这条不涨版本号也不动引擎：`src/agentcut/` 一字未改，改的只是门禁与文档，验收是 ruff check / format
--check 干净、`tracking_check.py` 单跑通过、串行套件重跑 69/69。仍未验的：尾巴的 `mask_width/mask_height`
曲线在分割时刻的对齐（本版只断 `mask_x`）；预合成内部片段带 offset 的跟踪（`sequence_id` 路径由 1.74
的门禁覆盖其可达性，时钟对齐没在这里断）。

## 1.86.0 分析的步长 = 播放的步长：200 % 的片段不该量它从没播过的画面

这一条是 1.85 提交之后按「这条链上还有哪个数没人验过」扫出来的，用的还是 1.83.1 那套对表：把同一个事实
在两处的写法摆在一起读。`http_api` 的稳定与跟踪路由都已经知道速率——`start = source_in + from·speed`、
`consumed = frames·frame_ticks·speed`——可 `track_mask` 拿到的采样率仍然是序列率，而写回去的点按**时间线帧**
落库。两件事拼起来就是：一段 200 % 的片段，第 i 个关键帧被要求描述时间线第 i 帧，而第 i 帧其实播的是源片
第 2i 帧。

先量再改。同一条合成素材上放一个 200 % 的片段（1 秒时间线花掉 2 秒源片），跟 30 帧，把落库的 `mask_x` 与
两条假说各自比对：与「源片顺序播放」的位置差 0.92 px，与「时间线真正播出的那些帧」差 **51.86 px**。引擎在
忠实地描述一段观众根本没看到的画面——缺陷确认。

修法是给这件事一个唯一的说法：`speed.analysis_rate(rate, speed_percent)` 返回约过整的比值（30 fps 在
200 % 下是 `15/1`、50 % 下是 `60/1`、400 % 是 `15/2`）。`decode_luma` 用它替掉 `fps=<序列率>`，并把 `-t`
按同一个倍数放大（不然读进来的源只够时间线的前一半）；`track_mask` 与 `stabilize.measure` 各收一个
`speed_percent`，路由传的都是 `clip.speed_percent`；回复多出 `speed_percent` 与 `sample_rate`，人和 Agent
都能看出这次量的是哪批帧。

顺带撤掉一条已经不成立的拒绝。`POST /clips/{id}/stabilize` 之前对 `speed_percent != 100` 回
`STABILIZE_INVALID`，理由写得很老实：「抖动是按一帧对一帧量的，播放速度变了就对不上」——那是当时的事实。
步长修对之后这句话不再成立，所以把拒绝删掉，界面 `stabilizeBlocked` 同步删掉同一半句（引擎与界面必须守
同一条判断，否则按钮灰着的原因和按下去的报错是两套话），门禁从「200 % 被拒」改写成「200 % 放行且量对」。
带**变速曲线**的片段仍然拒绝：速率一直在变，就没有那一个采样比值。

门禁的关键还是差分，不是「跑通」：
- `tests/tracking_check.py` 在同一条素材上放 200 % 与 50 % 两个片段，逐点比对「时间线那一刻播的源帧」上的
  物体位置（实测最差 1.14 px 与 1.56 px），并同时断言它们离「源片顺序播放」的位置分别差 78 px 与 27 px。
  反面陪衬是必需的：只比对正确的假说，任何一条写歪的采样都会红；只比对错误的假说过不了，才叫真量对了。
  另断 `tracked_frames == frames`（`-t` 忘了放大时，回来的点会变少但每个点仍然「对」，只比值的断言抓不住）。
- `tests/stabilize_check.py` 在按公式写的抖动素材上量四个锚点：200 % 时 `len(offsets) == 29`（一秒时间线
  = 30 帧减掉基准帧），最差 2.05 px = 0.8 个分析像素——用的是这条门禁给 100 % 的同一条容差；按源片步长比对
  则差 28.8 px。回复的 `sample_rate` 必须是 `15/1`。
- `tests/desktop_stabilize_check.ts` 钉界面那一半：`speed_percent: 200` 必须放行（`null`），带变速曲线且片段
  已经有自己的稳定记录时，曲线这条规则必须赢过所有权。

两个自己踩到的坑记下来，因为它们长得像引擎缺陷：第一次比对把 `_, h1 = path_at(...)` 写成了取 y 分量，于是
「两条假说都差一百多像素」，差点被当成第三个缺陷；修正后两条假说立刻分开成 0.9 px 与 52 px。另一处是分割
尾巴那条用例，一开始没把遮罩画到尾巴真正先出现的主体上，跟的是根本没被框住的画面。分辨办法只有一个：先核对
夹具与自己的读数，再谈引擎。

已知边界，不粉饰：400 % 在同一条抖动素材上最差 17.29 px（6.9 个分析像素）。这份夹具的色块周期是 24 px，
400 % 下相邻两帧之间画面已经走了十几像素，接近一个色块，锚点偶尔认错隔壁那块——这是内容对采样密度的限制，
不是步长算错（比值再快也不会算出别的数），而 `sample_rate` 如实写着 `15/2`，让人和 Agent 看得出量得稀。

五条变异逐条红（每条跑完原文件按 sha256 还原并复验）：`analysis_rate` 退回序列率 → 红在跟踪那条逐点比对
与稳定的 `(0.046, 0.0039)`（差到 11.8 个分析像素）；`-t` 不按速率放大 → 红在「读到的帧数就是窗口该有的帧数」
（`tracked_frames` 只剩 23，稳定的 `len(offsets)` 变 14）；稳定路由不把 `clip.speed_percent` 交给分析 →
红在回复写着 `15/1` 那条；界面把恒定速率重新灰掉 → 红在 `desktop_stabilize_check.ts` 的 `null` 断言；引擎
重新拒绝非 100 % → 红在「200 % 必须 200 OK」。第 1、2 条特意两头都跑：同一步长在两个分析入口上是同一个
来源，两边都该红，只红一边就说明哪里还留着一份自己算的比值。

验收：ruff check 与 format --check 干净（99 文件）、`npm run typecheck` 干净、15 项桌面 TS 全过、串行套件
69/69、`self_check.py` 通过；`build_engine --verify` 冻结引擎 ready，包内实例报 `app_version=1.86.0`，在包内
HTTP 上 200 % 的片段跟 45 帧写着 `sample_rate=15/1`、`tracked_frames=45`、逐点离它真正播的那些帧 1.14 px（离
它跳过的源帧 78 px），同一个片段点「画面稳定」不再被拒（`dry_run` 回 200 且写着 `15/1`）；`app.asar`
（5,574,087 字节）里读到「恒定速率的片段也能稳定」「带变速曲线的片段还不能稳定」与 `sample_rate` /
`speed_percent` 两个字段名；便携版从 ASCII 路径启动实测 1 个窗口、标题「AgentCut 剪辑台」，关闭后残留窗口 0、
进程 0。便携版 189,796,462 字节 SHA256 07F3199E5827768F8CFD5F75CDB40032F39FB646946DB5C7E1109BDA43994AE2，
安装版 189,957,182 字节 SHA256 A7189208B1D4F39B3DD93BA4B8C86D12B82BBD80000EC33234956E7E3A912ED6，根目录
AgentCut.exe 与便携版一字不差；未签名，NSIS 向导未点击验收，本轮没在原生窗口里逐控件点一次「画面稳定」
（界面侧由 TS 谓词、门禁接线与 asar 文本三处钉住）。仍没做也不假装做了的：包内那条**变速曲线**的拒绝没在
打包后的引擎上单独验过（一次性脚本在这条片段上写曲线时被 `SOURCE_OUT_OF_BOUNDS` 先拦下——2 秒源片装不下
那段区间，是夹具的账算错，不是那条规则的证据；曲线这条拒绝由源码级门禁 `stabilize_check.py` 与
`desktop_stabilize_check.ts` 两处断言）；400 % 的采样密度边界如上；遮罩尺寸曲线在分割时刻的对齐仍未断。

## 1.87.0 跟踪的两个旋钮交到人的手上（引擎一字未动）

1.85 给 `clip_track` 加了 `reacquire`、1.72 加了 `max_gap_frames`，两个都是「人想看结果才能判断对不对」
的旋钮，却只有 Agent 传得到：界面上「跟踪主体」就是一个按钮。这一版不新加任何判断，只是把人缺的那半个
入口补上——同一个请求体、同一套默认值、同一个上限来源。

检查器（Inspector）的遮罩区里，「跟踪主体 / 从头重跟」旁边多了两个控件：**挡住最多猜**（帧，就是
`max_gap_frames`，`min=0`、`max` 与默认都取自 `capabilities.limits.track_max_gap_frames` /
`track_gap_default`）与**满画面重找**（就是 `reacquire`，默认开着，和引擎一致）。`trackMask()` 多收一个可选
`options`：调用方没给值就不把字段放进请求体，所以界面不会因为自己存在而改变 Agent 的行为。提示会说出这次
是哪一档——`reacquire=false` 时明写「换个位置回来会被当成跟丢」，而不是让人事后猜。

门禁仍然钉接线不钉意图（`tests/tracking_check.py` 的 `interface_suite`）：两个按钮都带同一份
`{ reacquire: trackSweep, maxGapFrames: trackGap }`（数两遍，少一个就是漏接）；客户端确实把
`max_gap_frames` / `reacquire` 放进请求体；`240` 在整个 Inspector 里只许出现一次，而且就是那个 `?? 240`
兜底；输入框真的用 `max={gapCeiling}` 夹着；帮助页写着这两个旋钮的名字与作用。

三条变异逐条红（跑完原文件按 sha256 还原并复跑全绿）：把「从头重跟」那份 options 摘掉 → 红在「两个按钮都要
带上旋钮」；把输入框的 `max={gapCeiling}` 换成写死的 `max={240}` → 红在「引擎那个数只许出现在兜底里」；把
客户端的 `max_gap_frames` 不发出去 → 红在「界面摆出来的旋钮必须真的发出去」。三条都是接线的红，不是判断的
红——这一版没有新判断，只有把已有判断交到人手里。

这一版按的是界面，所以界面真的开过一次：把 `vite build --mode development` 产出的渲染层用静态服务器喂给
真实浏览器（Edge 内核），深链 `?engine=&token=&project=` 指向**打包引擎**（`desktop/resources/bin/agentcut`，
`/v1/info` 报 v1.87.0），工程是预先用 HTTP 灌好的那条长遮挡素材。页面顶部写着「引擎在线 v1.87.0」，点中时间线
上的片段后，检查器遮罩区里出现的就是这两个控件：`挡住最多猜` 是 `min=0 max=240 step=5 value=60`（240 来自
`capabilities.limits.track_max_gap_frames`，界面上量到的 `max` 就是它；把 999 敲进去被夹回 240），
`满画面重找` 的复选框是勾着的。然后按开关做了一次真实差分——同一条片段、同一个按钮，只差那个勾：

- 开着点「跟踪主体」：落库 90 条 `mask_x`，从 0 秒到 2.967 秒（revision 2）。
- 关掉点「从头重跟」：落库 30 条，停在 0.967 秒（revision 3）；把猜窗敲到 240 再重来一次仍是 30 条
  （revision 4）——挡住时找不回来这件事不是猜窗不够长，缺的就是那一次整画面重找。

这是本仓库第一次把「界面点了真的有效」写成验收证据而不是边界。指针级点击仍然没做（Qoder 内嵌浏览器这一页
没有可视视口，`click` 报 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`，只有结构快照与脚本可用，事件是通过组件的
React `onClick/onChange` 直接派发的），提示气泡的文案也没在窗口里读到（会话超时前已消失），所以界面侧的
文案与灰化仍由 TS 与 Python 门禁钉住。

其余验收：ruff check 与 format --check 干净、`npm run typecheck` 干净、15 项桌面 TS 全过、串行套件 69/69、
`self_check.py` 通过；`build_engine --verify` 冻结引擎 ready，`app.asar`（5,575,658 字节）里读到「挡住最多猜」
3 处、「满画面重找」、「track_max_gap_frames」、「maxGapFrames」与那句「换个位置回来会被当成跟丢」；便携版从
ASCII 路径启动实测 1 个窗口、标题「AgentCut 剪辑台」，关闭后残留窗口 0、进程 0。便携版 189,796,714 字节
SHA256 500D85059F239EB3A2E664366E7A4ACC3A437776BA5746D5AB2D6083F35218E0，安装版 189,957,435 字节 SHA256
A3B12D68048FEA6AEAE5CE33CA666D9BBD055AE71F11DD67BFECF24F87990E00，根目录 AgentCut.exe 与便携版一字不差；
未签名，NSIS 向导未点击验收。仍未做：把这两个旋钮存进工程状态（现在是一次性的界面状态，撤销一步不会回到
「上一档旋钮」）；引擎侧那条拒绝码没有新增，所以界面中文提示表一字未动。

## 1.88 一次跟踪量到结尾，以及它撞出来的第二道天花板

缺口是 1.87 收尾时自己写在纸上的那条：界面上的 `frames` 是 `Math.max(2, Math.min(300, whole))`。
读一遍就能确认它是缺陷而不是风格问题：300 既不是引擎的数（`MaskTrackRequest.frames` 一直是 `2..900`），
也没人告诉被它截断的人——提示结尾那句「导出使用同一份关键帧」在十二秒片段上描述的是前十秒。

第一步仍然是先量再改（一次性脚本，不进仓库）：同一条 12 秒 160×90 的往返走位素材、同一个片段，
只差请求的窗口——300 帧停在 299 帧刻度，350 帧停在 349 帧刻度，两边的 `lost_at_ticks` 都是 `null`。
所以短窗口停下来说明那是窗口的账，目标从没消失。这一步之后才动代码：

- 数字回到契约：`TRACK_FRAMES_MIN = 2` / `TRACK_FRAMES_MAX = 900` 定义在 `contracts.py`，
  `MaskTrackRequest.frames` 的 `ge`/`le` 与 `capabilities.limits.track_min_frames` / `track_max_frames`
  都从这里取；`http_suite` 还把契约字段的元数据与 capabilities 交回的数摆在一起比，两边各写一份就红。
- 判断回到一处：`effects.ts` 的 `trackWindow(remainingFrames, fromHead, limits)`，两个按钮都走它，
  剩余不足最低帧数时给出灰掉的理由，出路按位置分两种（挪播放头 / 切长一点或在曲线编辑器里加两点）。
  `desktop_trackwin_check.ts` 钉的是「它听传入的数」：换一组 `{8, 30}`，帧数、灰不灰、理由里的数字全变。

然后是在真实界面上点第一下的收获——这也是这次真正修掉的东西：十二秒以上、带尺寸的跟踪按下去拿到的是
`PROJECT_LIMIT`「工程到了契约上限（片段、轨道或关键帧的数量）」。两条一直没对表的数撞上来了：
`Clip.keyframes` 装 2000 条，而一个带尺寸的跟踪点要写 4 条曲线（中心 X/Y 加宽高），于是 900 帧的请求
在数学上永远写不下去。1.87 那个 300 恰好把这条藏在 4×300=1200 里——**一个错得太小的窗口，会让另一条
错的天花板一直不见天日**。这一条值得单独记：修 A 之后才看得见 B，不是因为 B 是 A 造成的。

修法和 1.73 给稳定/重构图立的规矩同一个形状：容量从契约字段的 `max_length` 元数据读（`reframe`、
`stabilize` 已经这么读），不写第二份。`timeline.mask_track_capacity()` 算出这一次还能写几帧（merge 时
窗口之前留下的曲线都算占位，更长的窗口又会吃掉尾部的点，所以逐步放宽再回验），路由据此先收窗口再分析，
回复里给 `budget_frames`；收不动了就 422 `MASK_TRACK_BUDGET`，`details` 交出
`frames_requested`/`capacity_frames`/`curves_per_point`/`keyframe_limit`/`curves_used` 五个数；reducer 对
手搓的超预算路径同样点名拒绝。界面那句「还剩几秒没量」改成拿回复里的 `last_at_ticks` 算，
1.88 早段自己加的 `unreachedTicks` 参数删掉了——界面无权猜引擎跑到哪儿；`desktop/src/engine.ts`
补了新码的中文提示，三条出路都是真能走通的。

验收：ruff check 与 format --check 干净（98 文件）、`npm run typecheck` 干净、16 项桌面 TS 全过、
`tracking_check.py` 单跑通过（新增 window 与 budget 两段真实测量）、`self_check.py` 通过；串行套件 69/69（含 16 项桌面 TS）。
行为侧的永久断言：灌 1600 条 opacity 曲线后再按 350 帧请求，量到 100 帧、`budget_frames=100`、末点落在
99 帧刻度且离物体真值 <0.012 画面宽、dry run 不动 revision；手搓 150 点（600 条 > 剩下的 400 条）
要求 422 且 `details` 里读得出 `curves_per_point=4` 与 `keyframe_limit=2000`。
八条变异各自红（跑完按 sha256 还原并复跑全绿）：界面上限写死、界面不再走那一个判断、`trackWindow`
的上下限不听传入、按钮不再按能不能开跑决定灰不灰、提示不再分支在 `budget_frames` 上、新错误码没有
中文提示、路由不再按容量收窗口（写下去就是谁也不点名的 `PROJECT_LIMIT`）、reducer 不再点名拒绝。
其中第一条在第一次跑时没红，被换掉了：原本只把 `stats.budget_frames` 改名，但句子内部的
`${stats.budget_frames}` 让 `"stats.budget_frames" in store` 照样成立——门禁当时钉的是「提到过这个数」，
不是「按这个数分了支」。这是 [[mutation-must-hit-the-assertion]] 的第 5 条在同一天里的第二次应验。

真实界面与发布包：

把开发构建的渲染层用静态服务器喂给真实浏览器（`npx vite preview --port 5206`），深链指向**打包后的 1.88 引擎**（标题栏实测「引擎在线 v1.88.0」，`capabilities.limits` 交回 `track_min_frames=2` / `track_max_frames=900`），一次灌进三条同一条 17 秒素材的片段，然后只做三件事：

- 8 秒片段（60 fps 序列 = 480 帧）点「跟踪主体」：落库 480 条 `mask_x` + 480 条 `mask_width`（共 1920 条，覆盖 99.8%），提示写着「已跟踪 480 帧…导出使用同一份关键帧」——这句话在 1.87 对这条片段是假话（只会量到 300 帧），现在是真的。
- 16 秒片段（960 帧）点同一个按钮：落库恰好 2000 条曲线（500×4），提示是「这条片段的曲线预算只装得下 500 帧…量到 8.3 秒就停了，后面 7.7 秒遮罩停在最后跟到的位置；把播放头挪过去再点「接着跟」可以续一段，或关掉尺寸估计让一个点少占几条」。
- 路径遮罩的 16 秒片段（一个点只占两条曲线）：落库 900 条 `mask_x`、零条宽高曲线，提示是「单次最多量 900 帧，片段还剩 1.0 秒没分析…」——两句不同的话，各自对上真正拦住它的那道天花板。

「关掉尺寸估计」这条出路也在界面上走通了一遍（同一套代码的源码引擎 + 同一份构建出的渲染层）：把「遮罩随远近缩放」的勾去掉、再点「跟踪主体」，16 秒片段落库 900 条 `mask_x` + 900 条 `mask_y`、宽高曲线一条不写、末点在 14.983 秒（片段 16.0 秒），提示写着「已跟踪 900 帧…单次最多量 900 帧，片段还剩 1.0 秒没分析…」——同一条片段，缩放开着只能量到 500 帧，关掉能量到 900 帧，那句出路在数字上成立。（先前我在这一版记录里写过「界面上点不出来、检查器落库后整块重挂把旋钮弹回默认」，那是**我的探针的错，不是产品的错**：直接调用 `__reactProps$` 上的 `onChange` 不会提交，必须走原生 setter + `input` 事件（数字框）或干脆派发一次 `click`（复选框，别先改 `checked`，那会被点击再翻回去）；把探针修对之后，同一次落库（revision 3）再读，`scaleChecked` 仍是 `false`、`gapValue` 仍是敲进去被夹到的 240，两个 DOM 节点也没被换过。旋钮本身的接线继续由 `interface_suite` 钉（两个按钮都带 `scale: trackScale`、客户端真的发 `estimate_scale`、aria-label 在、帮助页写着）。

便携版从 ASCII 路径启动实测出现标题「AgentCut 剪辑台」的窗口，PrintWindow 抓到 1480×900 的真实帧，裁切放大后标题栏写着「引擎在线 v1.88.0」，关闭后 AgentCut/agentcut 残留 0。`app.asar`（5,578,898 字节）里读到「遮罩随远近缩放」2 处、「跟踪时让遮罩盒随远近缩放」「曲线预算只装得下」「单次最多量」「一直量到片段结尾」「把播放头往前挪」各 1 处，以及 `track_min_frames` / `track_max_frames` / `budget_frames` / `MASK_TRACK_BUDGET`。便携版 189,799,355 字节 SHA256 4A682CAAF8E988B670EFC05FEB0B5BA53EA25F9DE117417E270F64FB2AC8FCB8，安装版 189,960,070 字节 SHA256 885B2A6547CFEE34638230337734464D0AAA41DC1F85CE0D2B00FA63E8BFE413，根目录 AgentCut.exe 与便携版逐字节一致；未签名，NSIS 向导未点击验收。

仍未做，也不假装做了：三个跟踪旋钮（挡住最多猜 / 满画面重找 / 遮罩随远近缩放）是界面状态、不是工程状态——同一次编辑会话里它们会一直留着（实测落库三次之后仍是 240 / 勾着 / 不勾），但换一个工程、重开一次窗口就回到默认，撤销也不会回到上一档；被曲线预算收短的窗口只能靠「接着跟」一段一段续；多目标跟踪、路径遮罩形状与尺寸的动画、3D LUT、线性光色彩管理照旧。

## 1.89 被预算收短的那句提示，指的是一条走不通的路

这一版的缺陷不是量出来的，是**读出来**的：1.88 给「曲线预算收短」写的句子里有半句「把播放头挪过去再点
『接着跟』可以续一段」。把它和 1.88 自己定下的算法摆在一起看就不对了——被预算收短，意思就是这条片段的
曲线已经写到 `Clip.keyframes` 的上限，那么任何一次续写都没有立足的地方，`mask_track_capacity` 在这种片段
上返回 0，接着跟必定拿到 `MASK_TRACK_BUDGET`。换句话说，界面指的那条出路是引擎一定会拒绝的那条。

先量再改（一次性探针，不进仓库，结论由永久断言接管）：一条 17 秒片段跟满 500 个带尺寸的点，落库恰好
2000 条曲线；此后 `mask_track_capacity(clip, 4, merge=True, from=500 帧)` = 0，硬发两个点被拒为
`MASK_TRACK_BUDGET`，`details.curves_room = 0`；同一条片段用 `merge=false` 只写中心（一个点 2 条曲线）
容量回到 1000 帧——这正是「关掉遮罩随远近缩放再从头重跟」这条出路的算术依据，而它在界面上真的可点：
1.88 收尾量过同一条 16 秒片段，开着缩放量到 500 帧、关着量到 900 帧。

改的是那半句话：预算那一支现在明说「预算已经用满，『接着跟』不会再量出新的一帧」，并把两条真走得通的出路
摆出来（关掉缩放从头重跟 / 把片段切成两段分别跟）；帮助页把两道天花板分开写：被单次上限收短才能
「接着跟」，被曲线预算收短不能。引擎一字未动（`MASK_TRACK_BUDGET`、容量算法、`budget_frames` 都是 1.88 就有的），
涨的是界面与门禁，所以版本号照界面惯例进一位。

门禁的关键是**把提示那一整行取出来单独断**，而不是断"文件里出现过某个词"：`interface_suite` 找到含
「曲线预算只装得下」的那一行，要求它不出现「再点『接着跟』」这种给出路的句式、必须出现
「不会再量出新的一帧」这种说明为什么不给的措辞、并且同时出现「从头重跟」与「切成两段」两条实出路。
`reducer_suite` 则把上面那段实测钉成永久断言（装满 → 容量 0 → 续两个点被点名拒绝且 `curves_room == 0`，
中心重写仍能拿回 1000 帧）。第一次写这条门禁时我用的是「该行『不会再量出新的一帧』之前的部分不许出现
『接着跟』」，跑出来当场红——因为产品文案里的「接着跟」正是出现在那半句之前（「『接着跟』不会再量出新的一帧」），
断言把正确的文案判错了。分辨办法是把"提到"与"给出路"分开：给出路的句式是「再点『接着跟』」，
拒绝它的句式是「『接着跟』不会再量出新的一帧」，两者字面不同，门禁必须钉后者放行前者。

另一条留给自己的：1.88 的交付记录里我写过「界面上点不出来，因为检查器每次落库后整块重挂把旋钮弹回默认」。
那是探针的错被当成了产品的错——直接调用 `__reactProps$` 上的 `onChange` 不会提交 React 状态，读数自然回弹。
修好探针（数字框走原生 `value` setter + `input` 事件；复选框只派发一次 `click`，不要先改 `checked`）之后重测：
落库到 revision 3，勾仍是不勾、猜窗仍是被 `max` 夹到的 240，两个 DOM 节点用 `el.__tag` 事后回读也从未被换过。
产品没有这个缺陷，那条"待办"的准确说法是「旋钮是界面状态、不是工程状态：换工程或重开窗口才回默认」。
假话留在记录里比缺失更难查，所以这一版把它连同证据一起改了过来。

## 1.90 淡从曲线搬到片段的两条边上

这条不是新功能，是 1.89 之前一直在那儿、只是没人按过的三件事。找它的方式是读代码而不是试界面：
`clip.fade` 的 reducer 里有一行 `clip.keyframes = [k for k in clip.keyframes if k.property != command.property]`
——为了「再点一次是替换不是叠加」而写的整条清空，把别人的点也清掉了。三件事因此同时成立：淡入之后
点淡出会抹掉淡入（而界面上这就摆着三个并排的按钮）、在自动闪避过的配乐上按一次淡会把闪避整条抹掉、
剪短片段之后淡留在旧刻度上等于没淡。一次性探针实测（同一份 6 秒片段，只差请求）：先 1 秒淡入得
`0s=0, 1s=1`，再点淡出只剩 `5s=1, 6s=0`；闪避形状的六个音量点淡一次之后剩两个；剪到 5 秒之后 5 秒处
的采样是 1.0。

修法是换一处落点，不是加一条规则：淡是片段的**边**的性质，不是曲线上的点。`Clip.fade` 四个整数
（每条属性各一个淡入、一个淡出，从边量起），求值仍只有 `animation` 那一处权威——`sample` 乘、
`expression` 乘，浏览器拿引擎另发的一条包络曲线靠嵌套透明度相乘。于是三条都成了结构上不可能：两头
各自的字段互不侵犯，淡与曲线相乘而不是替换，窗口跟着边走。分割是唯一还需要判断的地方：切口不是观众
看得见的边，所以左半只留淡入、右半只留淡出——照抄母片段的两头会在切口两头各淡一下，那是一幅没人
画过的画面。

`duration_ticks` 从 `gt 0` 放宽到 `ge 0`，0 就是取消它点名的那一头；界面那两行从此读工程状态，不再是
界面自己记的一份（1.88 收尾量过三个跟踪旋钮「同一次会话里留着、换工程回默认」，这两行现在连换工程
都不回）。额度只有一个来源：`片段长度 − 对面那头`；`tests/desktop_fade_check.ts` 钉的是它真的听这两个
数——换一段更长的片段就放行，对面那头缩一半余量就涨一半，否则就等于界面又自己写死了一个上限（1.87
那个 300 正是这么藏住的）。

两道门禁在写的时候各抓出一件真事。第一道：`editing_check` 里那条硬编码的**回执哈希**当场红了——
新增的 `Clip.fade` 字段进了 `model_dump`，于是每一个 1.90 之前写下的 `clip.add` 回执在重放时会算出
第二个哈希。沿用 1.69 给 `stabilization` 立的夹法（没提到淡的载荷必须与之前逐字节相同）之后恢复。
这条不是洁癖：回执对不上，用户重试同一个请求就会写进第二笔。第二道：我第一次把断言写成「浏览器那条
包络的中点应当约等于 0.5」，红在 `1.0` 上——下发的点全落在斜坡的两端与平段的两端，斜坡中间根本没有
点。真正的比法是取出斜坡那一段自己的 `cubic-bezier`，在时间中点上求它的值（0.500 对权威 0.5）。断言
错了会把正确的实现判错，这跟 1.88 那条探针假阴是同一类账。

成片实测（`tests/fade_check.py`，全部真跑 FFmpeg）：黑底上层白块，八个探点逐一与
`地板 + (全亮 − 地板) × alpha` 比，最差差 4.2 阶（允许 6）；只有一层、只带淡的片段确实不再走直通路径
（`plan.mode == "layered"` 且滤镜里有 `geq=`），这是那条「单层不合成」的短路必须跟着改的地方，不然淡
在导出里就是空的。音量走差分：同一条时间线不淡的那一遍做分母，39 个 0.1 秒窗与权威逐窗比，最差只用
掉允许量的 0.23 倍；中间那个 0.25 的音量点在淡之后实测 0.272——它还在，只是被乘上淡，这就是「乘不是
替换」的证据。

仍未做，也不假装做了：时间线上还没有可直接拖的淡角柄（剪映／达芬奇的手感，界面仍要在检查器里填秒数）；
淡不穿过转场重叠区做额外补偿（转场自己那条权重照旧与它相乘）；老工程里写在曲线上的淡不会被自动搬成
窗口（它照旧渲染，只是不出现在那两个数字里，要改用窗口请先在曲线编辑器里清掉旧点）。

## 1.91 淡角柄落到时间线上，以及一个只有装机才会撞上的门禁崩溃

1.90 收尾写下「时间线上还没有可直接拖的淡角柄」。这一版把那条了结，顺手把 1.90 的发布缺陷补掉——
`desktop/resources/bin` 里的冻结引擎是 10:04 的 1.89，而 1.90 的源码是 20:2x 写的，
根目录 `AgentCut.exe`（08:52）又比 `release/AgentCut-便携版.exe`（10:05）差 496 字节：
上一轮交的是源码，包是空的。所以先把工作树复验（ruff 干净、`tests/suite_check.py` 70/70）落库，
再重打引擎与外壳，两件事分开记，别让一次提交同时认领两份证据。

淡角柄不是新语义，是把已有的语义接到手指上，所以它的规矩只有一条：不许新增一处判断。
拖动量从指针到那条边的像素距离换算成 tick，按时间线自己的网格对齐，上限读 `fadeRoom`——
也就是 1.90 那两行一直在用的「片段长度减对面那头」。于是界面上拖不出一个按下去必定被
`INVALID_FADE` 拒绝的长度；夹完与现值相同时一次写入都不发，revision 不涨。

能淡哪几头本来在 Inspector 里就地算了一遍（`picture` / `sound` 两个布尔当 props 传进去）。
时间线要拖同一件事，如果照着再写一遍，就是两处权威——所以抽成 `fadeProperties(clip, asset)`，
Inspector 的 `FadeControls` 改成接 `properties`，两边共读。默认拖的是这段真正能淡的那一头
（画面轨淡不透明度，音轨淡音量），Shift 拖同时淡两头，但只在 `fadeProperties` 给出两档时才给。

门禁是 `tests/desktop_fadehandle_check.ts`。最有分量的一条不是逐值断言，而是一个扫：
四段长度 × 三种对面那头 × 六个原始拖动量 × 两头，每一个夹完再交给 `fadeBlocker` 问一遍
「放不下」，132 次必须次次放行——写死的上限在这里天然活不下来。第一次跑就红了一次，红在
我自己造的假fixture 上：`duration 1s / out 2s` 这种状态引擎存不下来（一次写入要么被拒要么被夹到
片段长度），拿它去断言等于让门禁判一个界面永远遇不到的东西；改成只扫存得下来的状态。
两条变异都咬住了：把 `fadeRoom` 改成无视对面那头，1.90 与 1.91 两道门禁一起红（同源这件事
本身就是可测的）；把网格对齐拆掉，红的是 1.91 那一条。

真正量过的是跑起来的应用：把 `create_app` 与构建好的渲染端各自起在回环端口上，浏览器里
62px/s 下把淡入角柄拖到离边 62px，落库正好 `70560000` tick＝1.00 秒、revision 4→5，
拖动时片段上方实时写着 `1.00s`，检查器那两行同时读回 1.00 与 0.50——另一边 0.5 秒的淡出
一字未动，`gain` 两头仍是 0。把淡出往 2 秒拖（此时淡入已占 2.5 秒）夹成 0.5 秒，正好等于现值，
于是 revision 纹丝不动，这条「不改就不写」也是量出来的。斜坡的宽度跟着状态走（155px 与 31px
对应 2.5 秒与 0.5 秒），角柄用 `elementFromPoint` 命中验证过没被修剪边盖住。

顺带撞出来一个真缺陷，属于门禁自己：`desktop_ts_check.py` 把每个 shell check 的 PASS 句子
原样 `print`，而本机控制台是 cp936。我的句子有一个「−」（U+2212，GBK 里没有这个码位），
一条全绿的门禁就这样崩成 `UnicodeEncodeError`。子进程的输出早就按 UTF-8 解码了，坏的只是
外壳这一端的打印，所以修的是 harness：`sys.stdout/stderr.reconfigure(encoding="utf-8",
errors="replace")`。这不是给我这一句让路——任何一条以后写中文与数学符号的验收都会撞上同一面墙。

仍未做，也不假装做了：音画链接的另一半不会被一起淡（拖的是这条片段自己的窗口，链接伙伴得单独拖，
剪映是一起动的）；淡不穿过转场重叠区做额外补偿；老工程写在曲线上的淡照旧不迁移；角柄只在选中
片段、轨道未锁、宽度够 56px、且引擎下发 `clip_fade_envelopes` 时出现（不选中时斜坡仍照工程状态画）；
时间线缩放极小（网格为 0）时长度落回整数 tick 而不是半个 tick，这条也钉在门禁里。

## 1.92 一次拖的是一组：选中的与音画链接的伙伴一起淡

1.91 的角柄只淡被拖的那一条。这在剪映与达芬奇里都不成立：选好五条、拖一个角，五条一起淡；
一段带链接声音的画面，淡画面就得淡音量，否则口播淡下去配乐还在响。这一版补的就是这两件事，
而且全部发生在界面——引擎的 `clip.fade` 一字未动，一个批次多条命令本来就是它的路。

「一组」= 被拖的那条 ∪ 与它一起被选中的 ∪ 与它们同 `link_id` 的伙伴（链接不传递，一遍就够）。
落库单位从「一条片段两头」变成 `(clipId, property, side, ticks)` 的列表，`setFadeWindows` 退到内部，
对外只有一条 `setFadeWindowsForClips`，标签写着「淡入 N 条片段」，一个批次一个 revision。

两条最容易做错的地方写成了门禁（`tests/desktop_fadebatch_check.ts`）：

* **不许拿被拖那条的长度去夹别人**。三条各 6/3/6 秒的片段一起拖 5 秒，落库是 5 秒与 3 秒——
  每条读自己的 `fadeRoom`。这条断言把「先算一个数再发给全组」这种写法当场抓住。
* **夹不动的那条整个跳过，不许写 0**。`Clip.fade` 里「取消这一头」与「长度是 0」是同一个数字，
  所以替用户清掉那一头是一件他没做过的事。对面那头占满额度的片段，拖动夹出来正好是 0，
  而它现在的淡入也是 0——不写；把它自己的淡入拖回边上，那才是取消，这一次要写。两条都在门禁里。

另外锁定轨道上的片段点名（「所在轨道已锁定」），组里读到不存在的 id 默默跳过（那不是拒绝）。
「既不显示画面也没有声音」这一档本来也准备点名，写门禁时发现它按引擎的规矩根本存不下来
（`kind === "audio"` 一定有音量、其余一定有画面），于是退回成一句注释，不给用户编一条走不到的路。

门禁第一次跑红在我自己的算术上：25 fps 下 1.5 秒是 37.5 帧，网格进到 38 帧＝1.52 秒。
这条现在也写成断言（同一个 fixture 拖 1.6 秒给 1.6，拖 1.5 秒给 1.52），因为「拖动量落不到半个帧上」
正是它该有的行为，而不是我的期望值。

实机量过：两条文字片段都选中（各显示自己的一对角柄），拖**其中一条**的淡入角柄离开 62px，
两条同时落成 1.00 秒、revision 2→3 只涨一次、没有任何提示。

仍未做，也不假装做了：持久组合（`group_id`）的成员不跟着淡——走的是「一起被选中」这条路，
所以只有被选中的那些会动，组合本身不额外扩张；淡不穿过转场重叠区做额外补偿；
老工程写在曲线上的淡照旧不迁移。

## 1.93 三个跟踪旋钮活过了重开窗口，落点是偏好不是工程

1.88 收尾记着一条待办：三个旋钮（挡住最多猜几帧 / 满画面重找 / 遮罩随远近缩放）是界面状态，同一次会话里留着，换一个工程、重开一次窗口就回默认。这一版把它了结，但落点不是当时写的「存进工程状态」——那条路在这个应用里只有一处入口：`updateProjectMeta`，而它每写一次就涨一个 revision 并清空撤销栈（元数据写入让旧撤销链失效，是它一直的行为）。把一次勾选接到它上面，等于用户点一下复选框就丢掉整条编辑历史。那不是持久化，是拿编辑历史换一个偏好。

所以它们与代理宽度同一处：应用偏好。读回来的规矩写成三条能测的东西（`tests/desktop_knobs_check.ts`）：天花板每次仍听引擎的 `capabilities.limits`（存着的数比这台引擎给的大就夹回去，界面不许自带一个上限）、部分写入只碰它点名的那个、以及「没存过」与「存了 0」必须是两个读数。最后这条是门禁第一次跑就咬出来的：`Number(localStorage.getItem(k))` 在键不存在时给的是 `0`，于是空存储读成「一次都不猜」，正好把 1.85 那个合法的 0 帧当成了默认值；改成先按字符串判缺失再换算。

实机量过（`create_app` 与构建好的渲染端各起在回环端口）：给一段带矩形遮罩的片段把猜窗改成 120、取消「满画面重找」，整页重读之后读回来还是 120 与关，没动过的「遮罩随远近缩放」按引擎默认开着；这两次勾选期间工程一直停在 r2，撤销栈没被碰过。

仍未做，也不假装做了：这三个数是应用级偏好，不是工程级——同一台机器上换工程共享一份，Agent 也不读它（Agent 每次请求都自带这三个参数，那是接口该有的样子）；要真做成工程状态，得先给元数据写入找一条不涨 revision、不清撤销栈的路，那是另一件事。

## 1.94 推移上屏，顺手把预览欠擦除的那笔账还了

「推移/滑动类（整层位移，需要给转场窗口内的层加时间相关的 overlay 偏移，另开一轮）」是 1.6 之后一直挂在那条待办。这一轮去看的时候，先撞上的不是它，是**擦除在预览里根本没有画**：`Preview.tsx` 里搜不到 `wipe`，四种擦除在浏览器里就是新画面从窗口第一帧起整幅盖上去——一个瞬间切换。导出是对的（`tests/wipe_check.py` 逐帧量过那条边），被骗的是眼睛。这是读代码读出来的，不是试界面试出来的。

引擎这一侧只动了一处：`transitions.envelopes` 多给一路点表 `motion_x`/`motion_y`（整层偏移，单位就是片段自己 `x`/`y` 用的「画面宽的几分之几」），并把擦除的 `axis`/`flipped`/`feather` 一起下发。导出把它加进已有的 `overlay=x:'(W-w)/2+W*(...)':y=...`，浏览器把它动画到**另外的嵌套包装**上——transform 天生相加、opacity 天生相乘，所以「片段的位移 + 转场的位移」和「淡 × 权重」都不用第二处算术，两端读的是同一份点表。擦除在浏览器只能给硬边，于是取那条斜坡的中点 `progress*(1+feather) - feather/2`：位置对得上，差别只剩成片有 2% 的渐变带，这一处写在帮助里也写在门禁里。

**滑动做不了，而且是有理由的做不了。** 探针量回来：`slide_from_top` 在中段把 (192,32,32) 与 (32,32,192) 叠成了 (222,61,220)——这条导出链把预乘后的各层**相加**（`transitions` 的模块说明与擦除那条互补 alpha 都是为此存在的），两层一重叠就双计成一片亮边。推移两层朝相反方向走、接缝横穿画面，永远不相交，所以它天生安全；滑动要新画面盖住旧画面，就得先有一条**画面空间**的互补 alpha，那是导出与预览两边都要改的一件事。于是四种滑动从契约里撤掉，只交四种推移，理由写进 `TRANSITION_KINDS` 的注释与帮助页——不是「以后再说」，是这一版量过它为什么不成立。

门禁 `tests/motion_check.py`：四种推移的点表算术（进来的 −1→0、出去的 0→+1、另一根轴一字不动、画面权重整段 1.0、音量照旧交叉淡、不许顺手放大，外加「两层方向必须相反」这条不变量）；编译项里确实多了那条随时间走的加法、而溶解没有多算一次；**成片实测** `push_from_left`/`push_from_right`/`push_from_top` 在窗口 25/50/75% 处的接缝分别对得上 0.25/0.5/0.75（容差 3.5% 画宽，方向也钉），两端对照探针 t=0.5s 整幅是旧画面、t=2.5s 整幅是新画面。浏览器那侧 `tests/desktop_wipestyle_check.ts` 钉的是不变量而不是逐个数：同一进度下，进来的那层与出去的那层露出的比例必须**恰好铺满整幅画面**——方向或中点算错，这个和立刻不等于 1。

两条门禁各抓住一次我自己的错：`wipe_from_bottom` 的 `flipped` 我猜成了 false（引擎的表说是 True，表是对的）；`inset()` 的第四个值我漏写了 `%`。第一次跑 `slide_from_top` 报「接缝找不到」时我没有去放宽容差，而是把那一列像素打出来看——看见的是 (222,61,220)，于是有了上面那段「滑动为什么不能做」。

仍未做，也不假装做了：滑动（要画面空间的互补 alpha，两端都要改）；预览的擦除是硬边、成片是 2% 渐变带；转场窗口内的位移不与遮罩跟踪曲线互相补偿；老工程写在曲线上的淡照旧不迁移。

## 1.95 淡有形状了，而且没有新增第二处算术

1.90 把淡搬到片段的两条边上，1.91/1.92 让人在时间线上拖它，但那条斜坡一直只有一种走法（smoothstep）。剪映与达芬奇都能选形状，于是这一版给每条属性一个 `shape`：线性 / 缓入 / 缓出 / 缓入缓出。

值得说的是它**没有**新算术。淡在 1.90 之后本来就是一条普通分段曲线（`fade_curve`），导出 `expression` 编译它、预览动画它，两端读的是同一份点表；「形状」就是那条斜坡用哪种插值——引擎早就有 `linear` / `ease` / `bezier` 三种，`ease_in` 与 `ease_out` 就是两组 CSS 控制点。默认 `ease_in_out` 走的是原来那条 `ease`，所以老工程读进来、渲出去一字不差（`tests/fade_check.py` 全绿就是这句话的证据）。

淡出那一段要把控制点按时间反演镜像（`(x1,y1,x2,y2) -> (1-x2,1-y2,1-x1,1-y1)`），否则「缓入」在两条边上摸起来不是一回事；linear 与 smoothstep 自己就对称，所以镜像恒等式对它们平凡成立，对两种贝塞尔才是真检查——门禁把它写成「从尾部量回来的淡出与从头部量过去的淡入逐点相同」。

`clip.fade` 因此允许只带 `shape` 不带 `duration_ticks`（保留这一头原有的窗口），也允许一次带两者；两者都不给是 422。名字与中文标签由 `capabilities.fade_shapes` 下发，界面下拉列的是它——与 `transition_kinds` 同一条规矩。

两端一致这次是可以数的：把下发给浏览器的那条淡曲线按它自己声明的分段三次贝塞尔求值，与权威 `fade_factor` 在 35 个点上比，最差差 2.44e-08（`tests/fadeshape_check.py`）。成片也量了：四种形状各渲一遍，0.25/0.5/0.75 秒的像素对得上 `255 × 因子`，偏差 4–6 阶，与 1.90 那条实测同量（编码与有限量程的既有偏移，不是形状算错）。

仍未做，也不假装做了：形状是**每条属性一个数**，不是每条边一个（淡出靠镜像而不是独立选择，够用且少一处状态）；老工程写在曲线上的淡仍然不会被自动搬成窗口；淡不穿过转场重叠区做额外补偿。


## 1.96 老淡搬家：一条命令，而不是让人去清关键帧

1.95 那节末尾的「仍未做」里写着「老工程写在曲线上的淡仍然不会被自动搬成窗口」，这一版去还这笔账。触发点不是新功能，是一句我自己写下的话：帮助页里那句「要改用边窗口，请先在曲线编辑器里清掉旧的点」，等于把引擎已经知道的事推回给人手——引擎知道那条斜坡是从 0 缓到静止值，因为**它就是当年写它的那段代码**。

值得记下来的是判断尺度。`clip.fade_adopt` 只认「当年那个 reducer 留下的那一个形状」：每头两个点、边上取 `0.0`、斜坡尽头取这条属性的静止值、插值全是 `ease`、这条属性上再没有别的点、点都落在片段自己范围内（含 `animation_offset_ticks`，所以裁过的片段量的是它真正播的那段）、这一头还不是窗口。松一点都不接受——自动闪避写的梯形、手敲的音量点、被人拖过一半的斜坡，全部拒绝，并把这条属性上看到的关键帧逐条放进 `details`。这不是保守：淡在 1.90 之后是**乘**进曲线的，多乘一次就把一条人敲的音量曲线悄悄抹平成别的形状，那种错没有人能看出来。

算术上先撞到一个假想的洞。我照着 1.90 的规矩在搬之前又写了一次「两头加起来超过片段长度就 `INVALID_FADE`」，写完才反应过来这条分支永远进不去：**窗口是从实际点的位置读出来的**，两条斜坡互相越过时读到的就是它们各自真正占的那两段，`in + out <= duration` 是构造保证的。留着它就是留一条不可达的错误处理（还会让人以为引擎在判一件它没判的事），所以删掉，改在门禁里把这条不变量写成断言——`(3.5, 3.5)`、`(3.9, 3.9)` 这两组叠在一起的淡确实搬得动，`in + out` 恰好等于片段长度。

「搬完画面不动」不能只是嘴上说。两条路都量了：把 `0 → resting` 做 ease 插值，与把 `resting` 乘上那条 smoothstep，是同一条曲线，于是 40 个采样点上搬前搬后的权威 `sample` 逐点相同（最差偏差 0.0e+00）；成片上同一条时间线各渲一遍，八个时刻的中心像素逐个比，容差 1 阶。第三条证据是突变：把形状写成 `linear`、把「删掉被搬走的关键帧」那行换成留着、把窗口读成整条长度——三次 `tests/fadeadopt_check.py` 全变红，说明这三条断言真的在管事，特别是第二条（它就是「乘两次」那个事故）。

界面这一侧照旧要在真实发布包里点一次才算。跑起来才发现我原来的命中测试骗了我：`淡入淡出` 那一行是个默认折叠的 `<details>`，折叠时 `getBoundingClientRect()` 仍然报出按钮的非零矩形（Chromium 保留折叠内容的度量），于是 `elementFromPoint` 回的是**后面那个 section**——如果只断言「按钮存在」，这条会绿着通过，而人第一次点它其实点在别的框上。先按 summary 展开、再滚动、再命中，才拿到 `hitIsBtn: true`；这条教训记在这里，下次做界面探针要先展开再摸。点一次量到的：r1→r2、那两个数字从 0.00 变成 1.00/1.00、片段上四颗关键帧菱形归零、按钮随之消失，音量那一行一字没动（它本来就没有淡），引擎读回 `keyframes=[]` 与两头各 1 秒的窗口、形状 `ease_in_out`。

仍未做，也不假装做了：一次只搬一条属性一个片段，没有「整轨把老淡都搬过来」的批处理；静止值在淡写好之后被改过（例如统一响度把 gain 动了）的那条会被拒绝，出路仍然是整理或删掉那些点、再用时间线的淡角柄重做；淡仍然不穿过转场重叠区做额外补偿。


## 1.97 整轨搬完：规划必须就是那条判断，而不是它的副本

1.96 的提交里我写下「一次只搬一条属性一个片段，没有整轨批处理」当作边界。这一版去补它，路上最值得记的是一件设计上的事，其次是三件我自己探针里的错。

**规划只能是那条判断本身。** 直觉做法是在规划里再写一遍「什么样的关键帧算淡」，因为它只读、快、不必碰 reducer。但那两份规则一旦分家——比如以后调整 ease 的判定——症状是「规划说这十段能搬，交进去因为第三段被拒，十段集体回滚」，而这种回滚在界面上只表现为按钮按下去没反应。所以 `fade_adopt_track_plan` 里没有第二条规则，它逐条调 `_fade_adoption`，拿到同样的 `{in, out}` 或同样的拒绝句子；`apply=true` 交的就是那份命令表。门禁把这条同源性写成可测的：规划报的两个数，落库后必须逐字相等，不多不少。

**没淡的片段不列。** 第一版把每条属性都过一遍，于是 40 段的轨道交回 80 行「这里没有淡」，真正那两行「夹了别的点」被埋在里面。报告的用途是告诉人和 Agent「哪几段要处理、为什么」，所以「这条属性上一条关键帧都没有」根本不构成一句话——跳过它，而不是把它写成一句拒绝。音频片段上的 opacity 是另一回事：它确实有淡的形状，但 reducer 会拒绝（音频没有画面可淡），所以规划必须把它**跳过并说明**，而不是排成一条必被拒的命令拖垮整批。

**一次操作就该是一次操作。** 走 `ProjectStore.mutate` 的一个 `EditBatch`，一整轨只涨一个 revision、只进历史一条、撤销一步回到搬之前。这与 1.92 拖一次淡角柄动整组是同一条承诺。

界面那句中文是这一版里唯一的新文案，也是唯一容易被做错的地方：引擎交回的是句子，整轨报告一次列几十条，直接印英文等于没报告。做法是 `FADE_ADOPT_REASONS`——键就是引擎那句原话——并让 `tests/fadebatch_check.py` 把两边的句子对起来：`inspect.getsource(_fade_adoption)` 扫出所有 `return None, "…"`，缺一条中文就红。这条门禁第一次跑就咬到自己，因为它先是空的：我一开始按 `single._fade_adoption` 去取源码，其实那个模块根本没导入它。同时 `tests/desktop_fadetoast_check.ts` 钉另一半——数取自规划而不是界面自己数、只列前三段、未知原因不许写成空串。四处突变（标题数错、去掉三条上限、未知原因写成空、引擎新加一句拒绝）逐条确认对应门禁变红。

三件探针的错都值得记，因为它们都是「绿着撒谎」那一类：

* `TestClient` 直接 `client.get` 不带 `with`，`app.state.projects` 还没挂上，500 栈一路喷到测试里；上一版的教训（lifespan 必须跑）我这次仍然先踩了一遍才想起来。
* 子进程 Python 在 cp936 控制台下把中文写成 GBK，我按 UTF-8 解码，于是「突变有没有红在点上」的字符串匹配永远 False——差点把一条真的会红的门禁判成空门禁。修法是给子进程 `PYTHONIOENCODING=utf-8`，而不是放宽匹配。
* 界面外壳里我把三段片段的 id 排成 `c1..c3`，实际是 `c0..c2`，`KeyError` 来得干脆，没造成假绿；但同一处如果我把断言写成 `.get(name)`，就会变成「什么都没搬」的假通过。fixture 报错要让它响。

实机量的是发布包里那个引擎：一条轨两段老淡加一段手敲的，点「整轨搬成边窗口」→ r1→r2（一整轨一次写）、c0 的四颗与 c1 的两颗关键帧菱形归零、那两个数字从 0.00 变成 1.00/1.00，手敲那段的三颗一字未动；再点一次，提示是「这条轨没有能搬的淡 / 1 段有淡但搬不动：c2（斜坡不是从 0 走到这条属性的静止值）」，版本不再变；往另一条轨放两段老淡，点一次提示「搬了 2 段淡 / 画面一个像素都不变 / 整轨把老淡搬成边窗口 · r4 / 已原子写入，历史可回滚」。那颗按钮在默认折叠的 `<details>` 里，探针必须先展开再命中——上一版记下的那条规矩这次直接用上了。

仍未做，也不假装做了：规划只按轨道切，没有「整个工程所有轨」的入口（真要做也应该是一次批次，不是 N 次点击）；静止值在淡写好之后被人改过的那段仍然搬不动，出路还是整理或删掉那些点再用淡角柄重做；淡不穿过转场重叠区做额外补偿；3D LUT、线性光色彩管理、分层调色节点图、路径遮罩形状动画与多目标跟踪仍未实现。


## 1.98 柔焦的 ◇：把「导出是阶梯」从拒绝理由变成设计

`contracts` 里那段注释已经写了好几个版本：柔焦与清晰不能打关键帧，因为「`gblur` 没有逐帧半径，只有
`enable` 这个开/关窗，硬给就是导出阶梯、预览渐变」。这一版去实现它，用的正是那句话里被当作缺陷的东西
——**阶梯本身**。两端不再各画一条曲线，而是共享一份窗表：`spatial_schedule` 采样成整帧对齐的常值段，
导出为每段串一个 `gblur=…:enable='between(t,a,b)'`，浏览器把同一份段用 `steps(1, end)` 动画出来。
于是「近似」这个选项根本不存在：要么两端同一张表，要么这条能力不发。

三处判断值得记。

**取中点，不取端点。** 常值段要代表这一段里那条曲线的平均水平，取段起点会让整条斜坡系统性地偏早一
格；写完之后门禁里那条「每段的值必须等于该段中点的 `sample`」就是把这句话钉成断言。第一次跑它把我
自己的错点出来了：我以为「段边界落在整帧上」是显然的，实际 `ceil(span / 24)` 算出来的步长根本不是帧
的倍数（4 秒 25 fps 得到 4.17 帧），于是窗边界会卡在两帧之间——而 `enable` 本来就是逐帧求值的，这条
边界会被静悄悄丢掉。改成先算帧数、再向上取整到整帧，才既整帧又不超上限。

**「按住到末尾才跳变」不该多出一段。** 两点的 `hold` 曲线，跳变正好在 `duration_ticks`——没有任何一帧
会看到第二个值。合并同值之后它只有一段。这条不是我想到要做的，是 fixture 逼出来的：我原本断言它该有
两段，跑出来一段，去看引擎为什么"少"了一段，才发现少的那个值确实没人看得见。**多一段就是多一个画面
上不存在的状态**。

**颜色链里多出来的那一个字段。** 导出顺序是「调色 → 柔焦 → 边缘增强」；预览里 `filter` 只能整个元素
整个元素地套，静态那版把三者塞进同一个字符串，顺序天生对。一旦柔焦要有自己的动画元素，嵌套次序就
变成 `子元素先算、父元素后算`——想保住「调色 → 柔焦 → 边缘」，只能把 unsharp 从那个字符串里拆出来，
放到更外层的元素上。所以有了 `edge_filter`：**只在有曲线时**拆，没有曲线的片段一字不变（这条纪律
让 `blur_check`、`format_check` 那些盯着既有字符串形状的旧门禁没有一行需要改）。

`blur` 进 `Property` 走的是 `mask_*` 那条先例：能关键帧、但不在那六个标量属性里，也就自然不进
`sample_values` 之外的旧通路。值域直接复用静态旋钮的上限（`PROPERTY_LIMITS["blur"] = (0, 0.25)`），
曲线不许爬到点一次按钮都到不了的地方；`denoise`/`sharpen` 仍然进不来，突变验证里有一条专门试这件事。

证据都在门禁里，而且每条都被我故意弄错验证过会红：把预览的 `steps` 换成 `linear`（抹平阶梯）、把
0 值段写成 `blur(1cqh)`（偷偷造出一个画面里没有的模糊）、把采样中点改成起点、把导出的 `enable` 整段
删掉——四次分别让对应的检查变红，还原靠哈希比对。成片那半是差分而不是绝对值：素材换成一张静止的二值
棋盘（第一次我用彩条 + 相邻像素差，测到的其实是压缩噪声——糊上去数字反而涨，那条断言直接把我的度量
设计打回重构），参照是同一条编译路、同一个编码器渲出的「整段都用一个 σ」的片段，于是 20 段的比较里
没有任何近似成分；读到的细节从 13.9 一路降到 0.01，每一段都落在自己那个参照的 10% 里。

实机点出去的那一下也是量过的：零关键帧的棋盘上按 ◇，r1→r2、多一颗 ◆；补上第二个点后重开页面，
`.layer-blur` 上挂着一条 16 段的动画，首段 `blur(0.833333cqh)` 正好等于第一个 5 帧窗中点的采样。

仍未做，也不假装做了：`sharpen` 与其半径仍不能打关键帧（一串窗意味着一串 `split+gblur+blend`，代价
不值）；柔焦当时还没进曲线编辑器，拉焦点靠播放头 + ◇，看不见那条曲线的形状（1.99 已补上，见下一节）；24 段上限是一处引擎常数，
不按片段长度或运动速度自适应；模糊仍是每段一个高斯（段内的连续变化没有表达），这一段说明写在帮助页
里，不写成「已实现逐帧柔焦」。

## 1.99 把柔焦送进曲线编辑器：一次只在界面侧的收口

1.98 给了引擎一条权威窗表，又在检查器放了一颗 ◇。人能记点，但看不见那条曲线的形状——AE 与达芬奇都把
空间属性放进同一条曲线页，剪映的「关键帧」列表里模糊和位置、缩放是并排的。这一版把「柔焦」并入那份属性
清单，同时把两处最容易分家的数字（上下限、起笔）收回一次计算。

**唯一的判断在 `desktop/src/effects.ts`。** `spatialAnimFields(caps, frameHeight)` 返回 0 或 1 条曲线，
条件与检查器滑杆那行完全一致：`capabilities.features.blur_keyframes` 没回、或按当前画幅折算不出正的百分比
上限，就一个字都不加。曲线项的 `max/step/factor/unit` 全从 `blurMaxPercent` 那一次计算来，所以 1080 高是
5.925%、120 高才是 25%——界面里没有第二处写着 25。

**起笔这件事是新引入的语义。** 曲线编辑器的纵轴要包住「这条属性现在是多少」，新加的点才不至于把滑杆已经
调好的值一脚清零。原来 `baseOf` 只认得 `clip.effects` 上那六个标量属性，遮罩另走 `clip.mask`；柔焦进来后
如果沿用旧写法，滑杆推到 12% 再按「播放头添加」写的会是 0，画布也会把 0 当作基准，用户看到的效果是「曲线
把柔焦关了」。因此把它抽成 `curveBase(clip, field)`：带 `field` 的描述符读遮罩自己的框，其余读
`clip.effects`（缺省时回 `DEFAULT_EFFECTS`）。「播放头添加」不猜——它按 `POST /v1/animation/sample` 的返回值
落点，那一份是引擎的权威采样。

**验收。** `tests/desktop_blurcurve_check.ts` 断言：能力开→列表恰好多一条且上限等于 `blurMaxPercent` 在同
一画幅下的得数（1080 与 120 两种画幅各验一次，紧的那个边界会换人）；能力缺（1.98 之前的引擎 / `caps` 还没
回来 / 画幅高未知）→一个字都不多；`curveBase` 对柔焦读 `clip.effects.blur`、对不透明度读 `clip.effects.opacity`、
对遮罩宽度读 `clip.mask.width`，没带 `effects` 或 `mask` 时回默认值而不是 NaN。三处突变（起笔不看 effects、起笔
不看 mask、上限写死 25）逐条确认这条门禁变红，再按 SHA-256 复原。

**实机测量**（1.99 界面 + 发布包里的 1.98 引擎，1280×800 同源 iframe，真实事件）：属性列表
`["位置 X","位置 Y","缩放","旋转","不透明度","音量","柔焦"]`；选「柔焦」后画布标题 `柔焦数值曲线`、刻度单位
`%`；「播放头添加」→ r1→r2，库里的正是 `{"property":"blur","at_ticks":0,"value":0.0}`；数值框
`min=0 max=25 step=0.5`（25 是 180 px 画幅下 `blur_fraction` 与 `blur_radius_px` 折算后更紧的那个），填 12
→ r3 且 `value:0.12`，填 90 → 夹到 25 → r4；同一次 `preview-manifest` 回
`spatial.blur=[{offset:0,value:0.12,easing:"steps(1, end)"}]` 而 `color_filter` 不含静态 `blur(...)`，预览里
`.layer-blur` 挂一条动画、计算样式 `blur(29.76px)`（= 渲染高的 12%）；「删除关键帧」→ r11、0 颗点、动画撤下、
样式回 `none`；滑杆推到 8% 再「播放头添加」→ r13 那颗点写着 `8.0%`，纵轴刻度随之定在 7.0–9.0%。

**仍然没做、也没假装做了的**：在画布上直接拖柔焦的点——Chromium 不为脚本合成的指针事件建立指针捕获
（`setPointerCapture` 当场抛 `NotFoundError`），这条只能由人手完成，而它落笔走的仍是与数值框同一个
`commit()`；`sharpen`/`sharpen_radius` 依旧不能打关键帧（unsharp 式子里半径与强度都没有逐帧形式）；段数上限
仍是引擎下发的一处常数，不按片段长度或运动速度自适应；模糊仍是每段一个高斯，段内的连续变化没有表达。


## 1.100 一次交付缺陷的账：柔焦糊的是画面，还是那一帧

这不是新能力，是把一条早就写进语义的话兑现到导出里。柔焦与清晰半径都写成「画面高的百分比」，帮助页与
`capabilities` 都这么讲，预览也照做：浏览器写 `blur(Ncqh)`，而那个预览框用 `aspect-ratio` 锁着工程比例，
所以 `1cqh` 就是画面的 1%。导出侧却是 `focus_radius(fraction, out_h)`，`out_h` 是交付帧的高。同比例时两者
是同一个数，所以三年没出事；一旦交付画幅被补边——16:9 的timeline导 9:16 或 1:1，这是短视频最常见的动作——
画面在帧里只占一部分高度，成片就比预览糊得多。

先复现再动手（160x90 工程、8 像素二值棋盘、同一编码器）：5% 的旋钮在同比例交付里 σ=4.5，在方画幅交付里
σ=8.0；画面带的相邻像素差从 2.67 掉到 0.10。旋钮归零再跑一遍作控制组，只差 1.7%——所以那 26 倍不是缩放
也不是编码噪声，是那一次除法。顺带还查出一条更硬的：64 px 的实测带同样按帧判，于是 1920x1080 工程交付
1080x1920 时，界面按工程高给到 5.93%，导出按 1920 判会在 3.33% 以上拒绝——正是本项目 AGENTS 里「不给到导出
会拒的数值」那句承诺的反例。

改法只有一处：基准 = 画面在交付帧里实际占的那段高（`render.picture_height`）。`contain` 才可能小于帧高，
`cover`/`stretch` 铺满帧所以不变；放大交付（画面撑满帧）自然回到 `out_h`。柔焦的静态值、阶梯里的每一段、
清晰半径与它的 64 px 守卫，四条都从同一个 `basis` 走，没有第二处除法。同比例、同尺寸的交付算出的 σ 与改前
逐字节相同，这一点交给既有门禁盯着：`blur_check`、`format_check`、`blurkey_check` 都是按编译串的字符串形状
断言的，它们一行没改就跑绿，就是这句话的证据。

新门禁 `tests/focusbasis_check.py` 三段：算术（16:9 进方画幅基准是 90、竖屏 90x160 是 51、放大交付回帧高、
cover/stretch 铺满）；编译串与上限（静态 4.5／方画幅 4.5／竖屏 2.55、清晰半径同一个基准、阶梯峰值 18.0 说明
打关键帧那条路也没漏、1920x1080→1080x1920 下 5% 导得出去而 11% 被 `BLUR_OUT_OF_RANGE` 点名且
`max_radius_fraction` 等于 64/608）；成片差分（控制组 0.983 对实测组 0.945，改前实测组是 0.038）。三处突变
（基准换回 `out_h`、`fit` 判反、守卫把基准乘二）逐条确认这条门禁变红，还原靠 SHA-256 比对——这条门禁第一版
自己有两处错也是跑出来的：我把 `Project` 当 `Clip` 用了（pydantic 当场报没有 `effects`），又凭心算写了
`607`，而 `round(1080*1080/1920)` 是 `608`。

边界照旧写清楚：画面在交付帧里的高度是按**工程比例**算的，不是按某条片段自己的宽高——一条竖屏素材放在
16:9 工程里，它的画面在预览与导出里都仍按工程框折算，这与预览的 CSS 行为一致；片段上的缩放动画会把已经
糊好的画面一起放大，这一点改前改后相同（预览与导出都这样）。本次没动的：段数上限仍是引擎下发的一处常数、
`sharpen` 强度仍不能打关键帧、交付适配本身的其它几何。


## 1.101 字幕压进黑边：同一根因查到的第二半

1.100 修柔焦时我写下「画面在交付帧里的高」这个概念，紧接着就该顺着它把整条画面链查一遍。字幕是下一个：
文字层的底板按交付帧铺，视频画面在 `contain` 下只占中间那条带，于是「靠上 8%」写在帧的 8% 处——竖屏交付时
那里是黑边；字号 6% 按帧高算，画面被缩小后字相对变粗大。1920x1080 工程交 1080x1920 时画面带是 y∈[656,1264]，
而靠上字幕落在 y=153.6，整条压在上黑边里。这不是新算式，是把同一句「比例量的是画面」补到它漏掉的那两处。

改动只在 `render.compile_render_plan` 的文字分支：`fontsize = picture_h * text.font_size`，上下内缩
`bar_y + picture_h*0.08`（靠下取 92% 再减字高），左右内缩按 `picture_w`，垫子那条 alpha 带用同一段坐标。居中
保持 `(h-text_h)/2` 符号式——画面在帧里居中，两种写法同一点，没必要换成数。`picture_height` 现在只是
`picture_size(...)[1]`，柔焦与字幕读的是同一次计算，没有第二处除法。

验收挂在已有门禁上（那里有真实的文字层 fixture）：`tests/textstyle_check.py` 新增 `delivery_suite`——320x180
工程交 320x320 时 fontsize=6%×180、靠上 `y=84.40`（上黑边 70 px 之内不许写）；交 160x320 时 fontsize=6%×90=5.4、
靠下 `y=197.80` 落在画面带 [115,205] 里；居中仍是 `x=(w-text_w)/2`。四处突变（字号回 `out_h`、上/下/左内缩回
符号式）逐条确认这条门禁变红，还原靠 SHA-256 比对。同比例交付只有内缩那几处从 `h*0.08` 变成同值的数
`14.40`，所以按字符串断言的三条旧门禁跟着更新成新数（`style_check` 的 `y=165.60-text_h`、`textstyle_check` 的
`x=25.60` 与 `x=294.40-text_w`）；这两条门禁各自的像素组（底部垫子均值 130 vs 无垫 218、字形落在预期行列）
仍是绿的——这才是「同比例没变」的证据，不是我的一句话。

自己犯的两次错也留在这儿：先把 `y=202.20` 当预期（把 92% 与 8% 减反了），又拿 `fontsize=10.8` 这个字符串去
比，而 FFmpeg 那条串里是 `10.799999999999999` 的浮点原样——改成读出数值再比容差，才算真在断言几何。

边界：画面框按**工程比例**算，所以一条竖屏素材放在 16:9 工程里，它自己的画面仍按工程框折算（与预览 CSS 同行为）；
文字层缩放动画仍会把已经画好的字一起放大，两端一致。没动的：安全区内缩（`capabilities.safe_area_insets`）仍是
按帧显示的参考线、不影响导出；字幕的逐字动画、竖排文字、3D LUT、路径遮罩形状动画、多目标跟踪仍未实现。


## 1.102 遮罩落在黑边上：同一句承诺的第三处欠账

1.100 把柔焦半径、1.101 把字幕字号与内缩归到画面框之后，剩下的同族问题就是遮罩。它的形状坐标
（`center_x/center_y/width/height`）从 1.45 起就是「画面的百分之几」，浏览器把 unit 遮罩图铺在锁着工程比例的
预览框上；导出侧 shape 分支却在 `pad` 之后才跑 `geq`，`W/H` 已经是垫好的帧，path 分支把轮廓光栅化到帧尺寸的
板子上。竖屏或方画幅交付里，用户画在画面上的遮罩会被帧比例拉长、还会滑出画面带——打码打歪、背景虚化糊错地方。

先量，再改。160x90 工程、纯白底、居中 (0.5,0.5) 尺寸 (0.4,0.4) 的矩形遮罩，预览里是一块 64x36 的可见窗。
同比例交付量到行 [27,63]（36 高）；交 160x160 时改前量到行 [48,112]，也就是 64 高——形状被拉成正方形，
中心还偏了。这不是舍入：0.4 的宽度乘的是 160（帧）而不是 90（画面）。

改法是两处：`alpha_expression` 收一个画面框，把 `X/W` 折成 `(X-bar_x)/picture_w`（`Y` 同理）；路径那条按画面
尺寸光栅化板子，再用 `pad=out_w:out_h:bar_x:bar_y:color=中性值` 垫成帧，补丁的 overlay 锚点加同样的偏移。
「中性值」这一笔是必须的：普通遮罩板子外圈是黑（削掉），反相遮罩是白（保留），垫错颜色会让画面带外凭空变成
被保留或被削掉的区域。同比例交付时 `box=None` 且这道 pad 整个不出现，编译串与改前逐字节相同——这句话的证据是
`mask_check`、`maskanim_check`、`pathmask_check` 三条按形状与像素断言的老门禁一行没改就跑绿。

新门禁 `tests/maskbox_check.py` 三段：式子（无补边保持 `X/W`、有补边折进画面框、`box=None` 与裸式子同串）、
编译串（方画幅里板子仍是 `s=160x90`、多出的 `pad=160:160:0:35:color=black`；同比例不多出 pad）、成片
（矩形同比例 行[27,63] 对方画幅 行[62,98]：高都是 36、都在画面带内、上下余量彼此相等；自由路径
行[26,60] 对 行[62,96]：竖向跨度差 ≤2 px）。写这条门禁时自己的 fixture 错了两次：先按 `X/W` 的旧串去断言
新串里带括号的除数（实际是 `((X-0.0000)/160.0000)`，除数不带括号），又忘了路径板子那张 PNG 是
`plan.binary_files`——只写 `text_files` 的话 FFmpeg 报的是「找不到 png」，看着像引擎坏了，其实是我的搬运少了
一步。突变四条（式子回 `X/W`、遮罩框永远 None、板子回帧尺寸、垫子那步不出现）逐条确认这条门禁变红，还原靠
SHA-256 比对。

边界照旧写清楚：画面框按**工程比例**算，所以片段自己的宽高与工程不同（竖屏素材放进 16:9 工程）时，遮罩仍按
工程框折算——这与预览的行为一致，两端同一个数；遮罩跟随片段的位置/缩放关键帧不变（`x`/`y`/`scale` 在遮罩之后
参与合成，补边与缩放动画的相对关系改前改后相同）。没动的：反相遮罩与羽化的算术、`alpha_expression` 的 SVG 侧
（浏览器本来就按画面的 unit 图铺）、跟踪与主体跟随写进曲线的那些数。


## 1.103 一张 3D LUT：把「不支持」的那半句兑现，另一半仍然明说

1.62 那句话是「3D 表会把红绿蓝互相混在一起，就不再是每通道一条曲线」，然后拒绝了它。这句话今天还是对的，
所以这一版没有去伪造一个每通道的近似，而是照 1.84 通道混合开的那个先例，让链条接受**自成阶段**：连续每通道
的节点照旧塌成一张表，遇到跨通道的节点就断开，顺序保留。于是 `曲线 → 3D 表 → 曲线` 编成三段，浏览器与 FFmpeg
读的是同一份阶段序列。

第二个决定是表放在哪儿。工程状态是每次修改都整份快照的东西，一张 33³ 的立方是 35937 个数：要么每版都搬一遍，
要么另起一套内容寻址的文件库（又是一处生命周期）。这里取的是「节点带表、上限 17³、超过就重采样并说出来」——
1.63 对超限 1D 表已经是这个处置，`.cube` 的行本来就按等距网格线性插值读，17³ + 四面体插值对创作型 LUT 的差别
用恒等表量不出来（重采样后逐点差 <0.02）。`resampled_from` 存在节点上而不是只存在回复里，是为了让那个信息跟着
这条 look 一辈子，而不是导入那一刻闪过。

第三个决定是**不假装两端一致**。`features.lut3d=true` 与 `features.lut3d_preview=false` 同时下发；
`preview-manifest` 里根本没有那一段（`preview_grade` 按 `preview: false` 整个拿掉，只剩立方的链连 `url(#…)` 都不写）；节点卡片上写「预览不生效、导出生效」；
节点上没有 `mix` 也没有 `blend`——一个只有一端会执行的强度，给了就是让人对一个看不见的数做决定。这与 1.78
降噪的处理同一条规矩，而那次已经证明：写清楚比给一个近似更值得。

验收 `tests/lut3d_check.py` 断的是四件事：解析（两种表头都认、六种坏文件各说各的原因并带行号/网格/行数、超限
重采样、恒等表重采样后仍恒等）；契约（格点数、`resampled_from`、`mix`/`blend`、并联分支四种都拒）；两端（浏览器
阶段没表体且 `preview:false`、导出串 `lut3d=file=lut3d-<sha>.cube:interp=tetrahedral`、写出的 cube 读回来与存的
逐个数相同、阶段序列必须是 `[lut, lut3d, lut]`、没有 plan 时 `LUT3D_NO_PLAN` 点名）；成片（纯红 231,29,20 经一张
红蓝对调的 2³ 表变成 20,28,230，绿通道不动，控制是同一条链去掉这个节点）。HTTP 一段还确认了 `asset.register`
那条最小链路没有因为新节点多要东西。

自己踩的三处：门禁用例先把「行数不够」的拒绝当成该带 `line`（它带的是 `size`/`rows`，我把断言改成了各自该说的）；
再用 `crop=1:1` 读像素，被 yuv420p 的色度平面挡下（1×1 裁到色度是 0×0），改成 `crop=4:4` 再缩；最后 `TestClient`
那一段用了 `asset.import`，而它按设计需要媒体引擎（AGENTS 里「素材 reference 是不可信元数据」那条），换成
`asset.register` 才是纯状态层的验证。

实测的存储代价（进程内起 HTTP 应用量的，320x180 空工程起步）：一张 17³ 节点的 json 是 101 KiB，同一处上限下 1024 行的 1D 节点是 61 KiB；给 6 个片段各挂一张立方之后 GET 工程 610 KiB、SQLite 4.75 MiB（7 个 revision，摊到每 revision 约 679 KiB），再挂 6 张 1D 之后是 979 KiB 与 14.2 MiB。「每次修改整份快照」这件事 1D 时代就在付，这一版把每节点的代价乘到约 1.7 倍，不是新引入的一类代价。没量到的是跨片段的总量：节点数上限是每条链 8 个，工程里片段数没有乘它的地方，所以一张 101 KiB 的表乘以片段数仍然是一条没有上界的乘法——要收它得给工程级 inline 表预算（一个像 `mask_track_capacity` 那样的额度、带自己的错误码与界面说法），那是一处独立设计，不在这版里顺手改。
`tests/lut3d_check.py` 那五段之外，界面那一步量到的是预览 CSS 串里没有 `url(#…)`（见下一节）。

边界：3D 表只有导出走它，预览保持导入前的样子（界面写着）；不支持 `DOMAIN` 非默认、`INPUT_MATRIX`/`OUTPUT_MATRIX`/
`LUT_TYPE`/`VERTEX_INTERP` 关键字，遇到就点名拒绝而不是半套应用；网格上限 17³ 是引擎下发的一处常数，不按片段数
或内存自适应；线性光色彩管理、分层节点图与第二路输入仍未实现。


## 1.103 补：第一版门禁断的是引擎的意图，不是界面读的那份产物

3D LUT 那一版写完，`tests/lut3d_check.py` 已经全绿，我断的是 `grade_tables` 交出的阶段带
`preview: false` 且不搬表体。这句话在引擎里是真的，但它不是界面读的东西：预览读的是
`preview_manifest.clips[*].grade`，而渲染层那段是 `stage.type === "lut" ? feComponentTransfer : feColorMatrix`
——立方既不是 lut，也没有 `m`，于是它落进 matrix 那条分支，`feColorMatrixValues(undefined)` 直接抛。
换句话说，导入一张 3D LUT 的结果不是「预览保持原样」，是整个预览崩掉。这条是在提交前的产物复检里发现的，
不是用户报的。

补的做法只有一处规则：`grade_tables` 仍然是完整的阶段列表（导出与复检读它），新增 `preview_grade`
是浏览器那一份——按引擎自己写的 `preview: false` 过滤，全被滤掉就返回 `None`，于是
`color_filter` 里的 `url(#id)` 也随之不写。`preview: false` 因此从「一句说明」变成一个真被读的旗子；
判「浏览器能不能画」这件事仍然只在引擎里，渲染层没添第三条分支。

门禁那段改成断产物（`preview_manifest`），而不是断意图：只有一张立方的链，`grade` 必须是 `null`
且 CSS 串里没有 `url(#…)`；曲线→立方→曲线的链，交出的表必须正好是 `["lut","lut"]`，且每个阶段
都带浏览器真能用的数（`r/g/b` 或 `m`）。这条断言先跑了一次红（就是上面那个 `AssertionError`），
再跑第二次绿；突变表也从五处加到七处（不滤立方、滤空了还写 url），逐条确认能红。

「换一张 LUT」那条也顺手补了：原来它无条件做 `{...旧节点, ...新内容}`，同一种表没问题，
跨 1D↔3D 就会把一个 `lut3d` 节点配上 `channels`——契约 `extra="forbid"`，编辑被拒，用户看到的是一个
看不懂的 422。现在按种类分两条：同种只换内容（启用状态、强度、混合方式留着），跨种整节点重写并明说
「强度与混合方式随之回到默认」。这是导入路径的载荷构造，不是第二套剪辑规则。

## 1.103 再补：另一条门禁把我自己的新行为抓出来了

`tests/ops_sweep_check.py`（1.77 那条「操作类路由的每条拒绝都要点名」）在完整跑里红了：
`INVALID_LUT names no line: {'size': 2, 'rows': 2}`。原因就在我这一版里——那份残缺的 3D 表在 1.62
是被 1D 读取器一句「this is a 3D LUT」拒绝的，那句带 `line`；1.103 让它走进 3D 读取器，行数的拒绝只带
`size`/`rows`，于是同一份文件的拒绝丢了行号。工程文档里那条承诺写的是「`.cube` 被拒给行号与行数」，
所以修的是产品：`parse_3d_cube` 记住 `LUT_3D_SIZE` 出现在第几行，行数不符时把那个行号一起交出。
`tests/lut3d_check.py` 现在也直接断这一条（`line == 1`），突变表加到八处（去掉这个 `line=` 就能红）。

教训是上一课的续集：新增一条走同一入口的分支时，旧分支曾经给出的诊断也是契约的一部分；
只在新代码自己的门禁里自证，抓不到这种「换了个拒绝理由就把承诺丢了」的退化。全量门禁里那些
跟本功能无关的扫描型检查（ops_sweep / read_sweep / error_vocabulary）正是为此存在的。

## 1.103 三补：我的复检夹具自己撒了一次谎

发布包第一次跑像素复检，测出来是「什么都没换」：(231,29,20) → (229,28,19)。看着像引擎的交付缺陷，
我先把同一份图在源码树里重跑了一遍（图里确实有 `lut3d=file=…:interp=tetrahedral`，像素也确实没换），
然后才去核对自己写的那张表——`cube_text` 的每个输入顶点写的是 `(r, g, b)`，那是**恒等表**，
注释里却写着「输出 = (b, g, r)」。引擎按一张恒等表正确地什么都不换。

所以修的是夹具：写出 `(b, g, r)`，并且让复检先自证夹具——`cells[3:6] == [0, 0, 1]`
（输入顶点 (1,0,0) 的输出必须是 (0,0,1)），这条不成立就直接红，不必等到像素那一步再猜是谁的错。
项目里那条 `tests/lut3d_check.py` 用的是 `cube(2, swap_rb)`，变换是函数不是抄来的式子，所以它一直是对的；
两份代码写同一个意思，一份用函数一份用手抄，手抄那份错了——这是「夹具不许说谎」的又一个实例。

顺带记下这次真实碰到的两处环境事实：`npm run dist` 在走本机代理时取不到 Electron 的校验文件
（`Client network socket disconnected`，直连 `curl` 同一 URL 回 302），把 `HTTP(S)_PROXY` 清空就好；
复检目录 `engine/` 若不清空，`request_id` 的去重回执会把第二次运行撞成 `IDEMPOTENCY_CONFLICT`。

## 1.103 界面那一步：把「预览不生效」量出来，而不是说出来

打包引擎 + 静态渲染层起一份真工程，选中片段，点「+LUT」把一张 2³ 红蓝对调立方交给界面。量到的四件事：
toast 是「2³ 网格、共 8 个 RGB 格点。这张表按定义跨通道，浏览器画不出它：预览看到的还是导入前的样子，
导出才走它」；节点提示写着 FFmpeg 的 3D LUT 与四面体插值；工程状态里落库的节点是 `kind=lut3d`、24 个数、
没有 `mix` 与 `blend`（revision 从 1 走到 2）；最关键的是预览那一层的 `filter` 计算串是
`brightness(1) contrast(1) saturate(1)`——**没有 `url(#…)`**。这一条是 `preview_grade` 的直接证据：
少了它，这里会挂一个没有任何原语的 `<filter>`，画面整块消失，而门禁当时只看引擎的意图。

用合成 `File` + `dispatchEvent(new Event('change'))` 喂那个隐藏的 `<input type=file>`，比走操作系统的
文件对话框可靠；片段选中要先把 `setPointerCapture` 置空再派发 pointer 序列，否则在这台机器上合成事件会抛。


## 1.104 一张表到底该占多少地方：把 1.103 留下的乘法收到一处

1.103 交出去之后我量了它的代价：一张 17³ 立方是 14739 个采样点、101 KiB 的 json；同一处上限下
一张 1024 行的 1D 是 3072 个采样点、61 KiB。给 6 个片段各挂一张立方，GET 工程 610 KiB、SQLite 4.75 MiB
（7 个 revision，摊到每 revision 约 679 KiB）——因为每次修改都把整份工程快照进历史。那行 README 当时
写的是「跨片段没有总量上限」，这条乘法没有主人：链上 8 个节点是每链的上限，片段数没人管。

这一版给它一处主人：`GRADE_INLINE_SAMPLE_LIMIT = 200000` 个采样点（约 1.4 MiB 工程 json，十三张满格立方
或六十五张 1024 行的 1D 表），只经 `capabilities.grade_limits.max_inline_samples` 下发，界面与 Agent
读同一个数。计数按真实载荷而不是按节点个数：并联两支各算、`enabled=false` 仍占地方（状态里那张表
照样每版搬一遍）、嵌套合成里的片段也算。

第二个决定比数字更重要：**额度只拦增长**。第一版实现是「候选状态超额就拒」，写完门禁才发现那会让
已经超额的工程连改名、加轨、删表都发不出去——而删表是唯一的出路，等于把用户锁在自己上一个错误里。
现在 reducer 先算批前有多少、再算批后有多少，只有「变得更满」才拒。门禁把这条量出来了：
`run(over, [track.add])` 过、`run(over, clip.grade 清空)` 过、`run(over, 再塞一张)` 拒。

验收 `tests/gradebudget_check.py` 断的是四件事实：一处主人（能力下发的数 == contracts 的常数）；
计数是真的（13 张恰好装得下、1D/并联/停用/嵌套各自的数量逐一对上）；越界拒得点名且整批不进（原状态
逐字段等于改前）；HTTP 第 14 张被拒时 revision 一动没动、片段也没多，dry_run 与提交同答，
并且当场把 `worst_clip_id` 那张换成一条曲线之后同一条编辑就过了。六处突变逐条确认能红：额度不作数、
把超额工程冻成只读、拒绝不再点名最占地方的片段、并联不算、嵌套不算、能力与 reducer 用的数不一致。

边界：额度量的是「采样点总数」，不是字节——`.cube` 数字的写法（几位小数）会让字节数浮动，所以界面与
文档一律用采样点说话；一张表自己超限由 1.103 的网格上限先管（`size ≤ 17`），轮不到总量。总量额度
不按工程大小或磁盘自适应，是一处下发的常数。

## 1.104 界面那一步：额度撞上去的时候，人看到的是中文，状态里没有半成品

发布产物里的引擎起一份工程，13 条片段各挂一张 17³，正好 191607 个采样点（额度 200000）。在界面里选中
一条按「+LUT」把同一张立方再交一次——这一条越界。量到的三件事：toast 是那句中文提示（标题
「GRADE_INLINE_BUDGET · 调整画面色彩」），页面里没有漏出引擎的英文原句；回读工程 revision 仍是 1，
那条片段上仍是一个 lut3d 节点，片段数仍是 13——被拒的一步没有留下半成品状态；提示几秒后自动消失，
不是叠三条（第一次数到三个节点是容器加内部元素，不是三个 toast）。

顺手记下复检的做法：把渲染层用 `python -m http.server` 起在 127.0.0.1 上，靠
`?engine=…&token=…&project=…` 连到打包引擎——CORS 那条允许的本机来源正好覆盖这种跑法；界面里
`+LUT` 那个隐藏的 `input[type=file]` 用合成 `File` + `change` 事件喂，比走系统文件对话框可靠。


## 1.105 把「被拒才知道」改成「写之前问得到」

1.104 立了额度，但它只在撞上去的时候说话。对一个人来说这叫惩罚式文档；对 Agent 来说更糟——它要试一次
才知道还剩多少地方，而这一次尝试会涨 revision 或者至少白费一趟往返。所以这一版加一条只读的路由，
把同一个数在写之前交出来。

关键的设计约束是**不许有第二份算式**：`grade_capacity()` 不是重新数一遍，它调的就是 reducer 用来判
额度的 `grade_inline_samples()` 与 `_node_inline_samples()`。读到的数与被拒时的数不可能不一致，
因为它们是同一行代码。分项也补齐了：`by_clip` 只列前 20 个真有表的片段（排序键是「占用从大到小、
同值按 id」，所以同一个工程问两次答案逐字相同），嵌套合成贡献的份额单独记在 `nested_samples`，
于是这条恒等式可以被门禁直接断（后来发现它在超过 20 条片段时会自己断掉，见下一节）。

门禁那段把「预告准不准」量成了两句话：装到第 13 张时 `samples` 是 191607、`room` 是 8393，
小于一张表的 14739——于是紧接着那一次「再挂一张」确实被拒（422 `GRADE_INLINE_BUDGET`）；
而被拒之后重新问一次，回执与之前逐字相同（拒绝不该改动用量）。未知工程 id 点名回 404，
`tests/self_check.py` 的工具清单与只读提示也对上了新工具 `grade_capacity`。

边界先说清楚：这一版是**引擎与 Agent 侧**的可读事实，界面里还没有一个显示它的地方（1.107 已经接进检查器，见下一节）。渲染层现在拿不到
工程级的数（`preview_manifest` 是每条片段一份），把它搬进检查器要在 store 里存一份预览清单——那是
另一处状态与另一处失效逻辑，不该为了加一行字顺手引进来。额度量的仍是采样点而不是字节，理由和 1.104
一样：`.cube` 数字写几位小数会让字节浮动，用点数说话两边才对得上。

还有一处是突变跑出来的，值得单独记：把 nested_samples 硬写成 0，门禁当时是绿的。原因不在产品而在用例——
`capacity_suite` 那份工程没有带表的嵌套合成，`by_clip` 恰好等于总数，那条恒等式于是断不到任何东西。
补的用例做了两件事：三条片段带**不等量**的表（于是不只是「有一个 worst」，而是「worst 取的是最大的那个、
by_clip 的次序对」），再往子合成里挂一张表（于是 nested 非零、恒等式真的把两边绑在一起）。这条补齐后
同一个突变立刻红。教训和 1.103 那次一样：一条恒等式在两份数据上都成立时，它其实什么都没断。

## 1.105 之后：把「换一张 LUT」跨种类那条量到界面上

README 里那句「跨 1D↔3D 整节点重写」当时只有 tsc 与代码读起来对，没在界面里走过。补的量法有个坑：
`+LUT` / 「换一张 LUT」都是先记下目标下标、再调那个隐藏 `input` 的 `click()` 唤起系统对话框，
而对话框没法在这里点。做法是临时把 `HTMLInputElement.prototype.click` 换成对一个 `type=file` 空操作
（记录被调用了一次，正好证明是这颗按钮唤起的选择框、目标下标因此被设上），然后合成 `File` +
`dispatchEvent(new Event('change'))` 喂进去。走的是真接线，不是绕过它。

结果：先交一张 1D，节点 keys 是 blend/channels/enabled/kind/mix/size/title；再按「换一张 LUT」交一张
2³ 立方，节点数仍是 1，kind 变成 lut3d，keys 只剩 cells/enabled/kind/resampled_from/size/title，
`channels`/`mix`/`blend` 一个不留，`enabled` 保住原值，revision 2→3 只涨一次。也就是说 1.103 那条
「跨种类整节点重写」不是纸面规矩：契约 `extra="forbid"`，留着旧字段这一步会被拒，界面确实没留。

## 1.106 自己写的回执自己得能证伪：by_clip 截断到 20，恒等式就只剩 20

1.105 交出去之后回头读那段话，越读越不对：文档写的是「分项加起来等于总数」，而 `by_clip` 只列前 20 名。
也就是说到第 21 条带表的片段起，`sum(by_clip) + nested_samples` 就小于 `samples` —— 一条我在文档里
承诺过、门禁却没覆盖的恒等式（用例最多 4 张表）。这不是假设：代码摆在那儿，截断就在 return 上一行。

修法是给回执一个不被视图污染的总量：`by_clip_samples`（全部根片段的和）与 `other_clips`（还有几条没列出来），
恒等式改成 `by_clip_samples + nested_samples == samples`；`by_clip` 保持前 20 名的便利视图，
但文档明说拿它的部分和对总数是错的。门禁补了一段 25 条带 1D 表的工程：`len(by_clip)==20`、
`other_clips==5`、`clips_with_tables==25`、`by_clip_samples==25×3072`，并且**故意**断
`sum(by_clip) < by_clip_samples` —— 这条一旦哪天变成相等，就说明截断没了或者 20 这个数被动过。
突变确认能红：把 `by_clip_samples` 写成 `sum(listed.values())`（也就是回到截断的和）门禁立刻红。

教训接在 1.103、1.105 那两条后面：一条恒等式要在**它能被破坏的那个数上**断，视图就老老实实叫视图；
文档里写「等于总数」之前先问一句截断在哪。

## 1.107 把额度接到人眼前：一次「界面不许自己算」的写法

1.105/1.106 让回执自洽了，但它只对 Agent 有用。接到界面上最容易犯的错，是拿 `room // cube_samples`
顺手算一个「还放得下几张」——今天它对，明天引擎改满格立方的大小或加一档预算，界面就报一个引擎不认的数，
而且报得很自信。所以这一版把除法留在引擎里：`grade_capacity()` 除了 `room` 之外再给 `room_cubes`、
`room_tables`，并把除数本身（`cube_samples`/`table_samples`）一起交出来，句子只剩填空。

第二处不是可选项而是必须的：这一行绑 revision。回执是异步取的，用户在等待期间又改了一次时间线，
拿旧 revision 的数配新 revision 的句子说出来，就是拿一份工程的用量去说另一份工程——比不显示更糟。
组件里因此记着「这份回执是哪个版本问来的」，对不上就整行不出现。

`tests/desktop_gradecapacity_check.ts` 用一张故意不自洽的回执把这条钉住（界面若自己除，那里会说「1 张」），
引擎侧在 `gradebudget_check.py` 里断同样的字段与实数；两条突变分别打断引擎的换算与界面的填空，各自都让对应
门禁变红。顺手修的是 1.103 留下的一处不对称：那颗「换一张 LUT」的按钮只挂在 1D 节点上，3D 节点想换表
只能先删后加——同一处 `onReplace` 判定漏了一个 kind。

界面那一步量到的是「逐字相同」而不是「看起来对」：选中片段后那一行写 48 / 200000、13 张立方、65 张 1D，
与当场再问一次 `grade-capacity` 拿回的回执做**整句相等**的比较；再在 3D 节点上按「换一张 LUT」换一张 3³ 立方
（这颗按钮是这一版才有的，1.103 只挂在 1D 上），revision 从 1 走到 2，那一行跟着变成 105，仍然是回执的原文。
一次异步取数配一次版本变更，界面上没有出现旧数配新话。

## 1.108 一键套到整轨：规划的边界是「reducer 会怎么说」

这类批量入口最容易写歪的地方，是界面或规划自己判断一遍「装得下」，写入时再被 reducer 拒绝——那就又回到
两份规则。这一版的判据全部借自既有的三处：每链 8 个节点是契约的限制、音频片段没有画面是 reducer 早就拒绝
的组合、工程级查找表额度是 1.104 的 `grade_inline_samples()`。规划按时间线顺序一段一段试，装得下的排进命令
并实时更新余额，装不下的报出「已有几个 / 上限几个」「剩多少采样点 / 这段要几个」，于是「套不满」是一次有名
有据的局部应用，而不是整批回滚后的一个错误码。

MCP 侧照 1.97 整轨搬淡的先例：只读工具 `track_grade_apply` 回同一份规划，Agent 想一次落地就用
`timeline_edit` 交这批命令，或者带 `apply=true` 打这个端点——两条路走的是同一个 reducer 批次。

一处值得记住的工具坑：突变脚本跑完还原，「恢复后再跑」报了红。源码逐字节对（有 SHA-256 断言），红的是
`src/**/__pycache__` 里那份按被突变过的源文件编出来的字节码被复用——还原后的源文件与缓存记录的
mtime/大小关系刚好没触发重编。之后的规矩是：还原之后先删 `__pycache__` 再跑那一次确认。这不是产品问题，
但一次错报会让人怀疑刚交付的东西，成本一样。

## 1.109 曲线的针落在哪一格：吸附的坐标系属于片段，不属于「本地 0」

诊断不是从界面开始的，是从一句合同差异：`_place_clip` 会按受影响轨的量子检查 `start % q`，
而 `clips.move` 只把 `delta_ticks` 加在 `position_ticks` 上（timeline.py:710）。也就是说画面片段
被音画链接组平移之后可以停在两帧之间，而曲线编辑器数的是「本地 0 起算的整数倍帧」。落下的那条线
在导出里不存在：合成时钟按绝对帧走，那一帧取的值来自上一帧。这就是「看着对齐、播出来差一帧」。

改法把坐标系这件事交给数据本身：`keyframeTick()` 的入参是片段（`position_ticks`、`duration_ticks`），
相位在里面算出来，不在调用方算。理由不是好看——一个可以被忘记传的参数就是一个会忘记传的参数，
而这条判断错了不会报错，只会差一帧。顺手接上达芬奇 / AE 早就做了的两件事：吸附播放头、吸附这条曲线上
没被拖动的针。容差按屏幕像素给（4 px 换算成刻度），所以放大八倍容差窄八倍；写死一个刻度数在低倍率下
会把整条曲线变成磁铁，在高倍率下又根本吸不上。

三个入口明确退出吸附：数值框、「播放头添加」、点空白处移播放头。它们要的就是那个精确位置，旁边有一根针
就把敲进去的 3.000 秒拽成 3.0032 秒是耍流氓。「播放头添加」尤其值得说一句：播放头本来就落在格子上
（标尺按同一份量子吸附过），所以对它的原始刻度做吸附是多余的，采样与写针用同一个位置才自洽。
上下界放在吸附之后夹，落点必在 `[0, duration_ticks]`——这样界面不可能送出一条 `INVALID_KEYFRAME`，
而不是送去之后再靠引擎的红字告诉用户「你拖不动」。

两处自己的坑值得写下来，因为它们都伪装成「通过」：

1. TS 里 `A // B` 是行注释而不是整除。第一版检查用 `(TIMEBASE * 1001) // 30000` 算帧长，得到 70 亿，
   所有期望值跟着一起飘。现在常量旁边钉着两条 `assert.equal(FRAME, 2_354_352)`。
2. 第一次跑突变，四条全绿——因为 bundle 是在突变之前构建的，改的是 `.ts` 源文件而不是产物。
   之后每一轮突变都先重新 bundle。另外我把「最近的格线」当成相位本身算了一次期望值，
   实际那条线在片段开始之前，答案被夹回 0：这条断言当时是空的，删掉重写才咬得住。

结论：`tests/desktop_keyframesnap_check.ts` 八次突变全部能红，基线全绿；引擎侧一字未改，
所以这不是一条新的剪辑规则，只是界面终于用对了自己那份几何。
## 1.110 时间线上拖针：同一枚针不许有两个落点

这条增量一开始想写成「给时间线加一套吸附」，写完第一版就停手了——因为 1.109 刚刚把「针应该落在哪一格」
算成一处。如果时间线再数一遍格子，同一枚针在曲线编辑器里落在 12.040 秒、在片段上落在 12.061 秒，
用户只会得到一句「软件自己都不确定」。所以 `planKeyframeDrag()` 里一行吸附算术都没有，它只把时间线
独有的两个量喂给 `keyframeTick`：每刻度多少屏幕像素（由缩放决定，所以容差永远是四个像素，跟片段长度
无关）和这条曲线上没被拖动的邻居。

三处容易写错、也都被断住了：

- 刻度空间。`Clip.keyframes[].at_ticks` 是含 `animation_offset_ticks` 的时钟，而 `keyframe.move` 的
  `from_ticks` 与新 `at_ticks` 是片段本地。界面必须折掉一次——reducer 会加回来。折两次就把针送到片段
  之外，而那条命令本来是被允许的，于是错误要到很远的地方才冒出来。
- 「只改时间」。第一版顺手重建了 keyframe 对象，把 `bezier` 丢了。现在深比较整枚针，除了 `at_ticks`。
- 撞针。reducer 的 `KEYFRAME_COLLISION` 才是权威，界面无需再发明一条规则；但它可以在松手**之前**就认出
  同一结局，把「第 0.113 秒已经有 opacity 的一枚针」说出来，而不是甩一条红字。判断只按同属性——
  不同属性同格是合法的（`gain` 与 `opacity` 并排本来就要能存在）。

工具坑两处，都值得留在日志里：`px` 这个量在界面里是「每屏秒像素」，我第一版按「每刻度多少像素」去算，
容差当场差五个数量级；以及把带反斜杠的正则塞进 `python - <<PY` 的字符串里，Python 先把 `\n` 解释成了
一次真换行，测试文件被写成一条跨行的坏正则——这台机器上这是第二次被 heredoc 的转义咬，落文本一律走
编辑工具。突变跑到底（十二次全红）也才明白：接线断言只写 `editAtRevision([next.command]` 是空的，
必须断那一行**整行等于**什么，否则在它前面挂个副作用也照样绿。
## 1.110 收尾：一次真拖撤回了 1.109 的因果，也暴露了两处只有几何能看见的缺陷

1.109 的理由是读代码读出来的：`_place_clip` 查 `TIME_NOT_ALIGNED`，而 `clips.move` 只把 `delta_ticks`
加上去，所以我断言画面片段能停在两帧之间，吸附因此落在那条渲染里不存在的线上。这一句在写进去的时候
**没有实测**。这次为了验收 1.110，起 1.110 的引擎 exe，把构建好的渲染层用本地 HTTP 服务起来，
用 Playwright Chromium 在 `.clip-keyframe` 上真按下、移动、松开，再回读工程——第一下就撞出三件事：

1. 想复制那条前提就失败了：把片段向右挪半帧，`clips.move` 当场 422 `TIME_NOT_ALIGNED`。原因是
   `apply_commands` 收尾有一处逐片段不变量（timeline.py:247：position 与 duration 必须整除所在轨的
   量子），它对**每一条**命令路径生效，不只是 `_place_clip`。所以 1.109 里那句「看着对齐、导出那一帧
   的值来自上一帧」是错的因果，README / AGENTS / 源码注释都按实测改口径：格子仍按片段位置算（那是
   唯一正确的算法，不变量哪天松动时不必再想第二遍），但看得见的那一半换成实测过的——
   `keyframe.set` 不检查刻度对齐，Agent 写在两个帧之间的针是合法状态，拖动把它落回整帧。
2. 贴边的针点不到：`.trim-handle` 是 7px 宽、`top:0;bottom:0`、z-index 4，菱形也是 z-index 4 且画在它
   之前，于是 `document.elementFromPoint(菱形中心)` 回的是 `SPAN.trim-handle.left`。我那一趟拖拽
   实际裁了片段（duration 从 141 120 000 变成 110 544 000），而工程里的针纹丝不动。纯函数门禁全绿、
   28 个壳层检查全绿、80/80 全绿，都看不见这件事——它只有 hit-test 能暴露。
3. 画在离边 6px 的针（为了让菱形不溢出片段而做的夹取）会被瞬移：按下时我按「画出来的位置」当针的
   时间去算，于是抓 0 刻度的针会把它送到第 6px 对应的时间上。修法是按下时记住这个抓取偏差，松手按它
   落回。

修完再量：菱形中心的 `elementFromPoint` 回的是 `BUTTON.clip-keyframe`；0 刻度的针拖到 30 576 000
（与片段起点相加正好 16 帧整），0.5 秒的针拖到 65 856 000（31 帧整），两次都只涨一个 revision。

给自己记一条规矩：**凡是「因为引擎允许 X，所以界面会出 Y」的因果，写进文档前必须用发布产物把 X 造
出来一次**。读代码得到的因果只能算假设——这次它就是错的，而且错的方向恰好是让改动显得比实际更重要。
## 1.111 一个界面不该有两个同名的开关

这条不是新功能，是把 1.109 自己留下的债收掉：那天给曲线编辑器加吸附时，我在组件里 `useState(true)`
数了一份「时间吸附」，而状态栏那颗吸铁石和 S 键翻的是 `EditPrefs.snap`。两个开关都叫吸附、都不告诉
对方，于是「关掉吸附」这件事在界面上有三种可能的含义。修法是删掉局部状态，两处读同一份偏好——
`prefs.setSnap(value)` 给复选框（它给的是目标值，不是「翻一下」），`editPrefs()` 给渲染之外读同一份。

偏好仍然只落 localStorage，不进工程状态。理由和 1.93 那三个跟踪旋钮一样：写进工程元数据每点一次就涨
一个 revision 并清空撤销栈，那是拿用户的编辑历史换一个勾选，方向不对。

检查按 `desktop_batch_check.ts` 的先例**驱动真 store**（假 window / 假 localStorage），因为这件事的
本体就是状态：断同一个布尔值既喂给 `keyframeTick` 也喂给那颗按钮，断写进 localStorage 的那一份正是
启动时展开的那一份，断 localStorage 抛异常时开关照样生效。

一条值得留下的门禁教训：突变「`toggleSnap` 改成永远 set true」第一次**活了下来**——我的断言序列只翻了
「关→开」一个方向。补上「开→关」与「翻两次回到原地」之后它才红。写 toggle 的测试必须两个方向都翻，
否则测的是一个常量。这已经是本项目第二次撞上「绿灯不等于测到」（上一次是 bundle 没重建）。
## 1.112 复制／粘贴：把人这边缺的手感补齐，命令语义一行不动

Agent 早就有一条属性整条写回去的路（`keyframes.replace`），缺的是人在曲线编辑器里的 Ctrl+C / Ctrl+V。
这一版全部落在客户端：`keyframeClipboard.ts` 算出该发哪些 `keyframe.set`，界面把这一批交给
`editAtRevision` —— 一次事务、一个 revision、一条历史。契约、capabilities、HTTP、MCP 一字未改，
所以「新增命令要同步六处」那条门禁根本不会被触发，这也是判断增量-size 的有用信号：如果一件交互优化
需要新命令，多半说明它在客户端漏了一份权威。

三条边界都是「不猜」：一次只搬一条属性；越界与撞针逐枚跳过并**报数**（不整批失败，也不像某些实现那样
把针往旁边挪一格求成功）；复制记着 `projectId`，换了工程就失效。粘贴落点复用 `alignTime(head, false)`：
格子照绝对帧算，但不找邻针——一把复制来的针如果正好落在已有那一格，它被跳过，而不是粘到隔壁。

两处我自己的错都被工具接住了，值得记：
- 接线时把 `if ((e.ctrlKey || e.metaKey) && key === "a")` 打成 `if (e.ctrlKey || e.metaKey && key === "a")`。
  `&&` 结合更紧，这一改就成「按 Ctrl 就全选」。现在 `desktop_keyframecopy_check.ts` 直接断那个括号存在。
- `pasteKeys` 的 `reason` 声明成 `string | null`，而 `toast(kind, title, detail?)` 收的是
  `string | undefined`：tsc 报在两条 `toast` 调用上。契约里 `reason` 用空串表示「没什么要说」更干净，
  省得每个调用点自己 `?? ""`。

十三次突变逐条能红，其中「粘贴拆成一条一条发」这一条专门盯 revision 数量：一次粘贴只该涨一个。
## 1.112 收尾：按钮点了三次才对，错都在探针自己

「粘贴」按钮在打包 exe + 构建好的渲染层里终于量到正向证据：针从 [1.0s, 2.0s] 变成
[0.4s（正好 12 帧）, 1.0s, 2.0s]，工程只涨一个 revision，回执是「粘贴了 1 枚关键帧，落在播放头起的
整帧上」；把播放头停在针上再点，回的是「没有粘贴：这一段 1 枚都落在片段之外或已有针那一格上」。
灰到亮的条件也在界面上量到了：没复制时 disabled，Ctrl+C 之后标签变成「粘贴 1 枚」。

三次失败全是探针自己的错，每一条都会让人误判产品坏了，所以留在日志里：
1. 读回工程之前先 terminate 了引擎——端口拒绝连接，看着像引擎崩了。
2. 把 `open(...)` 临时对象直接交给 Popen 的 stdout/stderr，文件对象随后被回收，子进程的日志句柄没了，
   于是「静默退出、两个日志 0 字节」。产品没崩，崩的是拿法。
3. 选针这个动作本来就会把播放头带到那枚针上（界面应该这么做），所以我「先挪播放头再选针」的顺序等于把
   粘贴目标钉在一个已被占用的刻度上；正确顺序是 复制 → 挪播放头 → 点按钮。
再加一条读数教训：toast 会自己消失，`sleep(1.8)` 之后再查 innerText 就什么都没有；这一轮是靠把页面发出
的 /v1 请求打出来才确认按钮真的跑了。界面上「没有粘贴」那条拒绝也同样是这么证明的，不是靠猜。

欠账一条，写在这里免得被当成已好：把粘贴按钮接进门禁时，我替换掉了 desktop_keyframesnap_check.ts 里
「Ctrl+A 守卫的括号」那条断言。代码仍是对的，但那个突变保护现在没人守着，下一个人该把它补回来。
## 1.113 一枚点不到的针：只有 hit-test 会告诉你的那类缺陷

时间线上每条片段下沿都画着 ◆，看起来一切正常。给一条片段同时写 `opacity` 与 `x` 的两枚针（同一秒），
两个 `<button>` 的 `getBoundingClientRect()` 一模一样，`elementFromPoint` 在其中一枚的中心回的是另一枚——
那一枚永远点不到，DOM 里存在、CSS 里可见、鼠标够不着。这类事没有任何纯函数门禁能看见：它不是值算错，
是画的位置撞在一起。

修法的取舍值得记下来。横向错开几像素是最省事的，但 13px 宽的对象错开 3px 仍然重叠，等于把缺陷调小而不是
去掉；把针道做到片段外面（另开一条 lane 带）会牵动整条时间线的行高与所有已量化过的布局。留下的做法是
**一条属性一道**，并且诚实面对画不下的情况：片段底部只有那么多像素，超出容量的属性**不画**，改成一枚
「+N」的牌子，悬停写明少了哪几条，点它直接进这条片段的动画曲线。少画是看得见的缺口，叠回去是看不见的
坏——前者可以修，后者会被当成正常。

同一个探针在修前修后各跑一次，数字就是证据：修前两枚针的矩形都是 `[169,710,13,18]`、`reachable` 一个
true 一个 false；修后是 `[169,698]` 与 `[169,686]`（道距 12px），三枚针全 `reachable`，同一像素上的
叠放对数为 0，`unreachable` 空列表。道号按属性第一次出现的顺序定（工程里的针是 `property` 先排序的，
所以这个顺序稳定可复现），不是字母表也不是随机。

一条通则：**界面上「看得见」不等于「点得着」**。凡是新画一个可点的东西，门禁之外还该问一次
`elementFromPoint(中心) === 自己`。
## 1.113 复核：把「+N」点一次，把最坏情况量一遍

分道改完之后还有两件事只是我以为：+N 那块牌子到底能不能把人接到动画曲线；三道 12px 的道在真实的
45px 片段里到底画不画得下（`laneCapacity` 用的是模块里的 37px，界面上没量过）。两条都在打包 exe 里量了：

- 一条片段写五条属性（`opacity`/``rotation`/`scale`/`x`/`y`），片段矩形 45px 高，画出的三枚针矩形
  `[138,710]`、`[169,698]`、`[200,686]`（道距 12px），三枚都在片段之内、`elementFromPoint` 各自的中心
  都回自己；剩下的 `x`、`y` 不画，变成一枚「+2」，悬停点名这两条属性，点下去动画曲线打开在这条片段上。
  溢出像素 0、点不到的针 0。
- 但量出来一个我原先没想到的脆弱点：针的命中盒是 13×18（padding 撑出来的），比道距 12px **还高**，
  相邻两道的矩形其实上下叠了 6px。今天各自中心还点得到，是因为叠的位置差在中心之外；这不是设计，
  是运气。所以下一步要么把命中盒压回 12px 以内，要么把道距抬到 18px——抬道距会让 45px 的片段只剩两道，
  把更多属性推到「+N」后面，压命中盒没有这个代价。
## 1.113 再修一处：命中盒比道距还高，那是同一类缺陷的垂直版本

分道把「同一秒的两枚针叠在一起」修掉了，但复核时量到针的命中盒是 13×18（`padding: 3px 4px` 撑出来的），
而道距只有 12px——相邻两道的矩形上下互相压住 6px。当下没有出事，仅仅因为两枚针的中心相隔 12px 而盒子
只有 6px 的重叠带，鼠标落在中心时恰好还在自己的盒子里。这是运气，不是设计：再多一条属性、再高一个字号，
或者哪天把 padding 改一点，就会出现「看得见的针点不到」，而且这次是垂直方向上出现的。

修法取压命中盒（13×12，正好等于道距），不取加道距（18px）：加道距会让 45px 高的片段只剩两道，把更多
属性推到「+N」后面，等于用可见性换稳度；压盒子两头都不亏。门禁现在直接断这条不变量——样式里
`.clip-keyframe` 声明的 height 必须 ≤ `LANE_PITCH_PIXELS`，界面上有隐藏属性时右端留出 16px 给「+N」牌子，
两边不许互压。

修后重量的数字：三枚针在 y 692 / 704 / 716，针与针矩形重叠面积 0，牌子与针重叠 0，全部在片段内、
全部 `reachable`，点牌子仍然打开动画曲线。全量套件 80/80、32 个壳层检查、tsc 全绿。
## 1.114 Alt 拖复制：同一个抓取动作的第二个意图

1.110 给了「拖着改时间」，AE / 达芬奇 那只手其实还有半个动作：按住 Alt 拖是复制一枚。这一版把它接在
同一个 `planKeyframeDrag` 上（`duplicate` 旗），出来的是普通 `keyframe.set`——原针不动、影子跟着指针、
落在已有针那一格变红并说明「复制得先找个空格」，落在原针自己那一格直说「没有多出一枚」而不是假装成功。
历史里两种意图分得开：`复制关键帧` 与 `拖动关键帧`。

值得记的还是测法。给检查扩断言时我连着错了两处：一处把夹具里的 clip id 写成 `"c1"`（真实是
`"clip-key"`），一处是新写的正则期望与源码实际文本差一个逗号——两条都是**跑出来**才发现的，不是想出来的。
而接线那条断言这次直接收紧成整行匹配（`^\s{6}editAtRevision\(…\);$`），因为 1.112 量过：只断前缀时，
在调用前面再挂一个副作用照样绿。

一条没做的：界面上还没有把「按住 Alt」写成常驻提示，只在针的悬停标题与帮助页里说了。若有人反馈找不到，
下一步该在选中针的时候在脚注里给一句。

## 1.114 装机复核：复制时只有影子该动

Alt 拖在打包 exe 里量通了：影子全程一枚跟指针、原针矩形一步没动、松手多出一枚在 76 帧整的刻度上、只涨一个 revision。第一版没通过——不是逻辑错，是**反馈**错：被拖的那枚原针也加了 `dragging` 样式（字号变大），看起来像它在被移动。探针里那句「原针位置不许变」比断言命令内容更早抓到它，因为界面上「它在动」和「它没在动」就是用户的判据。记一条：新增一个会动的东西时，顺手把「不该动的东西不许看起来在动」也量一次。

## 1.114 补测：影子会不会盖住 +N 牌子（答案是不会，且没改代码）

上一条交付说明里自己留了个没量的点：Alt 拖的影子是 z-index 6，而 1.113 的 +N 牌子排在片段右端，两者随时可能落到同一堆像素上。这次专门量了：一条片段写五条属性（于是有 +N），按住 Alt 把针一路拖到右端，每一步都读 elementFromPoint 与三个矩形——影子与牌子的重叠面积全程 0，牌子始终点得到，画出的三枚针彼此重叠也是 0、始终都点得到；松手后多出的那枚落在 298 704 000（正好 127 帧）。没有需要修的，但这条必须记下来：**「我以为不会撞」和「量过不会撞」是两回事**，尤其是两个都会动的东西。

## 1.114 再补测：批次模式下拖针不偷写工程

上一轮我自己点名没量的两件里的一件：时间线的拖针/复制走 editAtRevision，而「批次」开关在曲线工具栏上——如果时间线在批次模式下仍然直写，就等于在预演/提交那条保证旁边开了第二条安静的写路径。装机实测（1.114 的exe + 构建好的渲染层 + Chromium）：切到批次、回时间线、按住 Alt 把针拖到右边——松手后工程 revision 纹丝不动（还是 1），界面亮出「提交 1 条」，点提交之后 revision 2、针变成两枚，新增那枚落在 206 976 000（正好 88 帧）。结论是批次的语义被完整尊重，不用改代码。

顺手记一条探针经验：界面上有**两颗**「批次」按钮（工作台那条和曲线工具栏那条），Playwright 的 strict 模式会因为名字不唯一直接报错。名字撞车不是缺陷（两处切换的是同一个状态），但自动化必须按容器限定，所以以后选按钮一律先限定到所在面板，别拿可见文字当唯一 id。

## 1.115 界面上的属性名只有一张表

整界面是中文的，可动画属性的名字在四个地方还是契约里的英文：时间线 ◆ 的 tooltip（`opacity · 2.0 秒`）与无障碍名（`拖动opacity关键帧`）、撞针那句红字（`opacity 在第 5.000 秒已经有一枚针…`）、「+N」牌子列的缺谁（`x、y`）、曲线编辑器复制／粘贴的提示，以及检查器插值下拉的无障碍名。而检查器那条关键帧列表从 1.65 起就在读 `effects.ts` 的 `FIELD_LABEL`——**名字不缺，是漏接**。这一版不新增词表，只把那五处接到同一张表上，并把「这张表必须等于引擎的词表」写成门禁：新检查 `desktop_keyframename_check.ts` 读 `contracts.py` 的 `EffectProperty`/`MaskProperty`/`SpatialProperty` 三条 `Literal`，逐条要求有中文名、要求中文名互不相同、要求表里没有契约不认识的那一格，同时禁止 Timeline / CurveEditor / Inspector / keyframeDrag 任何一处再声明第二份 `*LABEL*` 表。撞针那句是实际调用 `planKeyframeDrag` 量的，不是只读源码——它交给 toast 的那句话现在是界面上唯一一处会把属性名念出来的地方。

装机实测（1.115 的引擎自报 `app_version 1.115.0`、`desktop/dist/renderer` + Chromium）读到的原文：六枚针的说明与无障碍名分别是「不透明度／旋转／缩放」；牌子写「画不下的针：位置 X、位置 Y——点开进动画曲线看这条片段的全部针」；拖到同属性那一格时读数「5.000s 已占用」，松手那句「不透明度 在第 5.000 秒已经有一枚针，先松到空格上或在动画曲线里删掉那一枚。」；复制回执「已复制 2 枚 不透明度 关键帧」；按钮说明「把复制的 2 枚 不透明度 针按播放头粘到当前片段…」。八个英文 id 一个都没出现，探针是按 `\b` 词边界找的，不是按子串（否则 `scale` 会被 `scaling` 之类误判）。那一次被拒的确实什么都没写：针仍是 141 120 000 与 352 800 000，revision 还是 1。

## 1.115 量出来的一条真缺陷：「+N」牌子点了没反应

同一次实测里，牌子 tooltip 写着「点开进动画曲线」，而我真点下去之后 `.curve-editor` 十五秒都没出现。原因是片段根节点自己吃了 `onPointerDown={(event) => start(event, "move")}`，牌子没有把这次按下交回自己，于是浏览器的 click 落在共同的祖先（片段）上，按钮的 `onClick` 根本不执行——那条被写进 tooltip 的出路是空的，而且是 1.113 交付时就没验证过的（当时的门禁只断源码里有 `setGraphOpen(true)`，也量过牌子点得到，但没量过「点它会发生什么」）。修法是牌子按下时 `stopPropagation`，与转场牌子、删除标记按钮同一写法。现在门禁断的是这层交接本身（`onPointerDown=…stopPropagation…[\s\S]{0,60}onClick=…setGraphOpen(true)`），实测点它确实进到了动画曲线并显示 opacity 的两枚针。教训一句：**「有个出路」不是出路，点一次才算**。

## 1.115 突变的一条假绿：锚点必须唯一

18 条突变里有三条打在牌子的手势交接上。K1 第一次跑出来是**绿**的——它删的是 `onPointerDown={(event) => event.stopPropagation()}` 这一整行的第一次出现，而这行在时间线里有好几处（转场牌子 :602、删除标记 :354 都有），根本碰不到牌子。把锚点换成牌子独有的那句 tooltip 尾巴（`看这条片段的全部针`}\n + 那行 stopPropagation）之后才红在自己的断言上。这正是既有的「突变必须打中断言」那条规矩的另一半：红不算证明，**证明是「它红在我以为会红的那条消息上」**，所以驱动脚本对每条突变都要求 node 的 stderr 里出现该断言的自定义消息，再逐条恢复并跑绿。

另外把 1.112 欠下的那条账还了：接线粘贴按钮时我替换掉了「Ctrl+A 守卫的括号」那条断言（代码一直是对的，但没人守着它）。现在 `desktop_keyframecopy_check.ts` 既断 select-all 那一行的括号，也断 Ctrl+A/C/V 三处都带括号——`a || b && c` 的结合顺序就是「按一下 Ctrl 就全选／全复制／全粘贴」，三个和弦都得有突变（C1/C2/C3）逐条打中。

## 1.116 Alt 点一下是指哪删哪：拒绝得当场给一条走得了的路

撞针那句拒绝写的是「先松到空格上或在动画曲线里删掉那一枚」——后半句把人从时间线上支走，而 1.115 的实测刚刚证明「写在 tooltip 里的出路」可以整版都是空的（+N 牌子点了没反应）。同样的毛病在拒绝语里也成立：**一条出路只有能在原地走通，才算给出的出路**。所以这一版给时间线的针加第二只手：按住 Alt **点一下**（移动不到两像素）就是删掉这一枚，走的是普通 `keyframe.remove`，刻度按片段本地交（和 `keyframe.move` 同一口径，reducer 自己加回 `animation_offset_ticks`），落库仍是带 `expected_revision` 的那条链，撤销一次回一枚。Alt 拖仍是复制——两只手共用同一个 `event.altKey` 判断，区别只在松手前那两像素。那句拒绝随之改成「先松到空格上，或按住 Alt 点掉那一枚」。

门禁全部扩在既有的 `desktop_keyframedrag_check.ts` 里（壳层检查仍是 33 个）：删对点中的那一枚、命令只有 `op/clip_id/property/at_ticks` 四个键、偏移只折一次、规划不改工程状态里那份记录；接线三条断言是行为而非文字——同一个 `< 2` 分支里既要有「点一下跳过去」也要有 Alt 分支的 `editAtRevision([planNeedleRemoval(clip, key)], …, "删除关键帧", …)`，并且时间线里 `removeKeyframe(` 出现次数必须为 0（store 那条 `submit(...)` 是第二条写路径，绕开了 `expected_revision` 与批次）。六个突变（删掉 Alt 分支 / 改走 store 那条 / 偏移折两次 / 换成一个新 op / 拒绝语又指回动画曲线 / tooltip 不再说这只手）逐条红在自己的消息上，全部恢复后跑绿。

其中一条值得记：「不许出现第二条写路径」那条否定断言，第一次的突变（把 `editAtRevision` 整行**替换**成 `removeKeyframe`）红在的是**前面那条**肯定断言上——被替换后源码里根本没有 editAtRevision 那一行了。要证明否定断言本身有效，得造一个「两条都在」的突变（在 Alt 分支旁边**插入**一句 `removeKeyframe`），让它只能由那条否定断言判红。否定式断言必须配一个不碰肯定断言的突变，否则它是没测过的保险丝。

## 1.116 之后的一次量测：曲线编辑器多针一起拖，会不会把别的针顶出属性量程

怀疑是这样：`CurveEditor.tsx` 拖动的 delta 是 `quantizeValue(抓住的那枚 + dy) - 抓住的那枚`，夹点只夹住**被抓住的那一枚**，然后这一个 delta 加到选区里每一枚上——于是从 0.5 往上拖、旁边那枚 0.9 就可能被要求变成 1.4，而界面明明写着不透明度上限是 1.0。这条怀疑值得量的理由和 1.115 一样：客户端交出去一个引擎未必认的数，就是「界面允许、导出会拒」那一类。

装机量测（1.116 的引擎 + 构建好的渲染层 + Chromium，真鼠标）：**没有这回事**。选区里两枚针（0.5 与 0.9），抓下面那枚 0.5 往上拖 300 屏像素，落库的是 `[(141 120 000, 0.6), (352 800 000, 1.0)]`——两枚都恰好 +0.1，也就是这一版实际是**按整组里离上限最近的那一枚**在夹 delta（0.9 只剩 0.1 的余量，整组就只走 0.1），而不是只夹被抓住的那一枚；工程里没有任何一枚落在 [0,1] 之外，界面上也没有一句拒绝。把方向反过来量（抓 0.9 往上拖）是同一条式子：`0.9→1.0、0.5→0.6`。结论是不需要改代码，这条怀疑到此为止。顺手量到的一条副产品是有用的：拖动时**被抓住的那枚不一定停在指针指的地方**，它跟着整组的余量走，这与 AE 的直觉不同，但那是既有行为，不在这一版的判断里。

没补上的缺口照实说：数值通道（`quantizeValue` 与这层整组夹法）写在组件里，没有纯函数可以单测，所以它只有这两次实测、没有门禁守着——下一次改这块的人不会得到红灯。要补的第一步是把那式子抽成一个纯模块、再加第 34 个壳层检查，而不是先写断言。

## 1.117 把那条式子搬出组件：为了它能有一盏红灯

上一条留下的正是这一条做的：`desktop/src/curveDrag.ts` 收了曲线编辑器「拖一下」的全部算术——先按这条属性下发的步长量化、再让**整组**按自己的两头夹（时间不越出片段，数值不越出量程）、最后逐枚落值；`CurveEditor.tsx` 里那三行原样搬走，一处不留（门禁断组件读的是模块，且 `Math.max(hardMin-Math.min(` 这种第二份夹法不在编辑器里）。夹具数字用的是装机量到的那对：0.5 与 0.9 两枚一起拖，落库 `0.6 / 1.0`。搬的动机不是行为要变，是**这层判断此前没有红灯**——一次只有实测的行为，下一个改它的人不会被告知任何约定。

一处有意的收口：落值这一步现在再过一次格子。过去整组的余量是 `hardMax - value` 这种减法减出来的，`1 - 0.9` 在二进制里是 0.09999999999999998，加在未选中的那些枚上就会写出不落在格子上的草稿，而 1.116 的实测之所以看到 `0.6 / 1.0`，是因为**引擎把漂移抹掉了**。客户端交出去的数与最终存下的数不该是两份东西，所以格子放在这里重算一次。

最值钱的收获是这条门禁自己怎么被证明有效的：要钉住的就是「落回格子」这一条，我造的突变（把 `applyShift` 换回只夹不量化）连试两版都判不出来——先拿不透明度那对数字（`0.5 + (1-0.9)`、`0.9 + (1-0.9)`）在 IEEE 里**恰好**等于 `0.6` 与 `1.0`，看不出差别；断言写的是几个具体得巧的数，而不是不变量。改成断言「每条结果必须等于它自己被量化后的值」，并用柔焦那种 0.5 % 一格的带造出一个真会漂移的数（`0.17499999999999999`），那条突变第一次就红了。教训：断言要写**不变量**；具体数字只在它是量到的那一幕时才有价值（这里的 `0.6 / 1.0` 留着，是因为它就是实测原文，不是因为它能杀突变）。

边界照实说：这一条是重构，界面没有新增可点的东西，所以装机复验用的是同一条探针回测旧行为（抓 0.5 往上拖 300 屏像素，仍写回 `0.6 / 1.0`、没有一枚越界），而不是新功能的实测；数值通道的其余部分（方向键微调、数值框）仍走各自的既有路径。

## 1.117 之后补量：方向键微调那条路

上一条留下的「数值通道的其余部分仍未量」当天就补了。装机探针（1.117 的引擎 + 构建好的渲染层 + Chromium，真按键）在一条 8 秒片段上放一枚不透明度 0.5 的针，选中后连按 7 次 ↑：存回来的是 `0.57`（repr 就是 `0.57`），时间一格没动（`at_ticks` 仍是 211 680 000 = 3.000 秒），revision 从 1 涨到 8（七次各一条，逐次带 expected_revision）。第一次我按的是 →，量到的其实是时间通道——`228 144 000 - 211 680 000 = 16 464 000 = 7 × 2 354 352`（片段 29.97 fps 的 7 帧整），而探针那句「值应当是 0.57」的判定是我自己写错的标签，不是产品的说法；改按 ↑ 才量到数值通道。

这条路之所以干净，是因为 1.117 把 `translate` 整条改走 `applyShift`，落值过格子——方向键每次加的是 `step / factor`（这里是 0.01），一格一格累加正是最容易攒出 `0.5700000000000001` 的那种加法。现在这条也有断言了：`desktop_curvevalue_check.ts` 里连走七次单格、再走一次十倍格（`10/100` 必须得 `0.6`），并断结果仍等于把自己量化后的值。这条补充是测试与实测，没有改产品代码，也没有版本号。

## 1.117 系列的最后一步：数值框那条判断也搬进同一个模块

`CurveNumber` 里那行 `Math.max(min, Math.min(max, next))` 是曲线编辑器最后一处「只有读代码才能知道它对不对」的判断。先按规矩 reproduce：读下来**没有缺陷**——越界会被夹回这条属性的带、空串与 `abc` 都不算改、Esc 之后离开焦点不算改、与当前值相同就不发命令；而打字进来的数**故意不**过格子（手敲要的就是打的那个值，格子只属于拖，1.109 定的口径）。既然没有缺陷，值得搬的理由就只有一个：让它在别人改坏时能红。于是那步判断抽成 `curveDrag.ts` 的 `bandEntry(text, current, band, cancelled)`，组件只留一行调用。

门禁补了九条行为断言（夹上限、夹下限、旋转按自己的带、空串、乱码、同值不发、Esc 不发、`57.4` 原样收下、十倍步长落在 `0.6`）加三条接线（组件读这个模块、把决定权交出去、widget 里不留第二份夹法）。突变五条逐条红在自己的断言上：E1 去掉上下限夹（`150` 就会写进 1.5 交给引擎）、E2 去掉 Esc 守卫、E3 去掉 `isFinite`（`abc` 变成 NaN）、**E4 把打字的值四舍五入到整数**（这条最有针对性：它现在红，说明「手敲不过格子」这个口径是有人守着的，不会被下一个好心人当 bug 修掉）、E5 把内联夹法塞回 widget。`tsc --noEmit` 绿、34 个壳层检查绿、`desktop/dist` 与发布包重构建过、根 `AgentCut.exe` 与便携版逐字节相同；引擎与契约一字未改，所以版本串仍是 1.117.0（这一串是同一批纯搬动，没有用户可见的行为变化，全量 Python 套件仍是 1.117 那次单独跑的 80/80）。

## 1.130 一键色彩管理：把「在线性光里调」变成一次点击，而不是一对必须摆对的节点

达芬奇在项目设置里给的是「素材按 X 解释、时间线按 Y 输出」，剪映给的是「一键」，AE 给的是解释素材的色彩
空间。三家说的是同一件事：源到工作空间、工作空间到显示端，这两步必须成对出现，而且必须让中间的调色发生在
线性光里。AgentCut 以前的形态是**一个** `transfer` 节点：能换算，但成对与顺序都靠人自己摆，摆错了没有
任何东西会说不对称。1.130 把这一对收成一条命令。

真正要设计的是「取下」那一步。最省事的写法是模式匹配——链首链尾各一个转换节点，删掉就完事；那样手工加的
转换节点会被一起删掉，而用户手工加的那两个与命令写的这两个在数据结构上一模一样，只有 `purpose` 这个章不
一样。所以这条命令的取舍是**只认章**：章是命令自己盖的，取下时只删盖过章的，于是「取下以后逐字节回到套上
之前」成为一句可以断言的话；盖过章的只剩一只（有人手工删了另一半）时报 `COLOR_MANAGE_NOT_SET` 并说出该谁
去删，界面那一行也念「不成一对」而不是念「没套上」——后者是一句假话，而用户会照着这句话做事。

第二条要设计的是额度。八个节点是每链上限（由引擎下发，界面照这个数限制），一对占两个。若按「现在还剩几个
空格」判断，满格的八节点链就永远换不了色彩空间：必须先删一个节点，才能加这一对，而这一对本来就是要**顶替**
旧的那一对。所以判断改成「取下旧的这一对以后还剩几个位置」，`COLOR_MANAGE_LIMIT` 交回 `limit/nodes/room`
三个实数：未套且满格是 room 0，七个节点是 room 1，套着的八节点链是 room 2。这与 1.126 给工程查找表额度
定下的「只挡扩张、不锁死」是同一条规矩在节点层面的样子。

第三步是承认这一对本身不是调色。来源与输出选同一个空间时，编译结果里根本没有这一节（`grade_filter` 空串、
`grade_tables` 为 None），导出的六档灰与完全不套逐档相同 [0,15,46,126,207,253]。这句话写进帮助页，是因为
「套了色彩管理」很容易被理解成「画面已经更专业了」；它只把像素搬进线性光，中间没有东西时它什么都不做，只是
白占两个节点。

测到的数（`tests/colormanage_check.py`，都是真实导出与独立写出的公式）：同一条把中点压到 0.28 的主色曲线，
按存储值调带回 [0,6,24,70,186,253]，套上「sRGB 读入 / Rec.709 输出」带回 [0,20,44,103,183,252]，中间那一档差
33 个色阶；256 个输入级逐点对发布的 sRGB 分段函数与 BT.1886 的 2.4 次幂，编译表最多差半个色阶，导出对预测值
每档差在 4 个色阶内。章只是元数据：同一对节点带章与不带章编译出的 stage id 与三条表逐位相同，所以预览与导出
不会因为盖过章而读出两张图。

拒绝都点名给数：`COLOR_MANAGE_NOT_SET`（链上几个节点、没有一个是章）、`COLOR_MANAGE_IDENTITY`（两端都
linear：不转任何东西却要占一次历史）、`COLOR_MANAGE_NO_CHANGE`（已经是这一对空间：再写一遍不改任何东西，所以
不写、revision 也不涨）、`COLOR_MANAGE_LIMIT`（三个实数）、音频片段 `INVALID_COLOR`。四条都有中文句子与下一步，
`error_vocabulary_check.py` 现在数到 142 个码、0 个落到英文。

界面这一侧收成一处：`desktop/src/colorManage.ts` 管「现在套的是哪一对」「还剩不剩两个位置」「盖了几只章」，
`GradeFields.tsx` 那一行只问它；两张下拉菜单的候选来自引擎 `capabilities.color_spaces`（壳层检查逐字核过七个
名字与契约的 `ColorSpace` Literal 一致），交出去的载荷只有那四个字段。13 条界面突变 + 16 条引擎突变逐条红在
自己那条断言上。其中「音频片段那一格」暴露的是**门禁自己**的缺陷：第一版把音频素材放在视频轨上，reducer 先按
轨别拒了 `TRACK_KIND_MISMATCH`，那条 `INVALID_COLOR` 守卫一次都没被执行过——门禁绿着，但它绿的是别的东西。把
夹具的轨改成音频轨之后，删掉守卫才真的让门禁变红（这条与「检查必须能失败」「夹具不许说谎」是同一课）。

顺带修的一条：README 的「已完成」表里有两条是被粘在同一行的（中间一个 ` | | `），也就是更早的补丁把两行写成了
一行——文档表格的形状以前没有任何检查读过，粘行只会让读者看不见那一行，不会让谁失败。补了
`tests/docs_shape_check.py`：每张表的行数、每行是否以竖线收尾、单元格数与表头是否一致，反引号与转义竖线都按
渲染器的读法处理；三条突变各红在自己那条抱怨上（把两行粘回去、少一条收尾竖线、不让它认转义竖线）。

还补了 `tests/released_package_check.py`：它读的是**发出去的字节**而不是源码——根目录 `AgentCut.exe` 与
`release/AgentCut-便携版.exe` 逐字节相同、`app.asar` 里那份 `package.json` 的版本等于契约的 `APP_VERSION`
（这条就是「改了源码忘了重打包」那类中断的探测器）、app 启动的那枚引擎与构建出来的引擎是同一份、asar 里的
renderer bundle 里读得到七句人话与 `clip.color_manage`。四条突变各红在自己那条断言上（数据基准挪一格、
版本比错、根 exe 比成安装版、引擎指到 `elevate.exe`）——第一条还顺手暴露了这个门禁自己的毛病：产物读不出
来时它该说「产物读不出来」，而不是抛一个 JSONDecodeError 让人以为引擎坏了。
## 1.131 两万段：先把「建了多少东西」从时间线长度改绑到视口宽度

这条缺陷以前只能写成「不知道」：页面卡死时会把这台机器上的 CDP 通道一起占住，连一次
`document.querySelectorAll('.clip').length` 都拿不到。现在有了从浏览器进程外取样的尺
（`scripts/renderer_scale.cjs`：网络日志、目标列表、每个 msedge 进程的 CPU 与工作集），
第一次量到了它坏在什么地方。

量到的第一件事实：引擎从来不是瓶颈。两万段一秒一段，八批 2,500 条写入 0.40→2.99 秒，
页面卡死的同时引擎答同一条 `GET /v1/projects/{id}` 用 0.68-0.77 秒并交出全部两万段，
`app.asar` 解出来的那份渲染层在三段对照工程上 2 ms 就答 `clips:3, nodes:412`。
也就是说，尺是好的、包是好的、引擎是好的——坏在两万段这一屏。

量到的第二件事实：坏掉的方式不是「慢慢画」，是「把内存吃掉之后不再说话」。渲染进程涨到
2,923 MB、烧掉 14.83 秒用户态 CPU 之后从进程列表里消失，页面目标还在（`target: alive`），
但此后两百多秒里每一次求值都在 5 秒预算上超时。

于是这一版的改动是「建多少东西」这一处。两处都在按整条时间线数：片段卡片数所有段，
`rulerMarks` 从 0 数到两万秒。两处都改成问同一个窗口（`timelineWindow.ts`：视口两边各多涂
两秒；没量到视口时不裁；滚过头时贴在结尾），被挑中的段即使在窗口外也照样建，框选拖过的
时间跨度整个并进窗口——这样按 DOM 矩形判定命中的那一步一个字都不用改，代价是松手之后要
把这份加宽收回去（门禁里有一条就是钉这个的）。一万两千段的尺子刻度与两万段里 14 张卡片
是同一屏的量。

量到的第三件事实，也是这一版**没做到**的部分：裁切之后页面依旧一段都没画出来，只是从
2,923 MB 降到 1,821 MB / 8.91 秒。浏览器网络日志把矛头指向启动：同一份 12,103,495 字节
的工程被请求了三次（其中两次各收了 12,103,495 字节），`/v1/projects?limit=100` 那份列表
还把另一个工程的完整载荷也读了一遍。留下的是三份两万对象的图，不是两万张卡片。所以
「两万段能用」这句话现在仍然不能说，能说的是：它已经有一个会说话的判据，下一次改动
要么让 `renderer_scale.cjs` 退出码变 0，要么写下它为什么不变。

## 1.132 首页的数从引擎来；那把量界面的尺被修到可以说真话

改的三处：

- `src/agentcut/projects.py`：`projects` 表加 `clips`/`assets`/`content_ticks` 三列，`_persist` 写文档时一并刷新，
  `_add_summary_columns` + `_backfill_summaries` 在开库时把老行（`clips IS NULL`）数一遍补上，`PRAGMA user_version` 2→3。
  `list_projects` 交 `COALESCE(...,0)` 三格。判断只有一处来源（`project_content_ticks`），列表与单份工程读的是同一个函数。
- `desktop/src/store.ts`：`refreshProjects()` 从「列表 + 每个工程整份读一遍」改成一次请求；注释写的是它换掉的那笔账
  （两万段那份工程 12,103,211 字节 × 列表里每一行）。
- `desktop/src/engine.ts`：`projects()` 的类型带出 `clips`/`assets`/`content_ticks`，界面不许再自己数。

门禁 `tests/projects_summary_check.py`（六节：摘要与整份工程一致、迁移、写入刷新、列表载荷 vs 单份载荷、HTTP、渲染层）。
打印出来的数：`list row: big clips=300 assets=1 content=21168000000 ticks (revision 1)`、
`traffic: the list of two projects is 260 bytes, one 301-clip project alone is 201712 bytes`、
`migration: legacy rows are counted once at open, user_version=3`、`renderer: refreshProjects asks once, and its type says so`。
5 条突变逐条红在自己那条断言的消息上。

装机复核跑出来的是**这次最有价值的东西**：那把尺在说谎。

1. `scripts/renderer_scale.cjs` 原先按 `Date.now()%97` 挑 DevTools 端口。本轮留下的两个僵留 headless Edge 实例
   在同一个 9816 上，新起的浏览器 bind 不上，`/json/list` 答的是别人的标签页——它报「2 ms 答 clips:3、退出码 0」，
   量的是上一次那个三段对照页。现在：端口先 bind 成功才用；附着的页 URL 必须与 `--url` 逐字相同（这个应用不改写自己的
   query）；否则明确报「这个浏览器从没打开过所要的那一页，它的标签页是…」。
2. 进程取样原先是「全机工作集最大的 msedge」，这台机器上开着别的浏览器，1.131 记下的 2,923 MB / 1,821 MB 两个数就是这么
   来的（已在 README 与 AGENTS 就地撤回）。现在只算本次 profile 那一棵进程树（按命令行里的 profile 随机后缀认，
   因为 8.3 前缀与全写前缀在同一棵树里混着用），并同时打印引擎侧的片段数与线上字节。
3. 重测的真数：对照页 3 段在 6.7 s 画出 `clips:3 nodes:410`（本次树 14 个进程 742 MB、最大 180 MB）；
   两万段那一页 11.7 s 时 2,994 MB（渲染进程 2,370 MB / 10.41 s CPU），随后渲染进程消失（14→8、换 pid、CPU 从 2.04 s
   重新起算），此后 108 s 里 12 次求值全部超时。`big_responses:1` —— 启动那份 12,103,211 字节的工程现在只取一次。
4. 根因用调试器中断抓到：未压缩 bundle（`npx vite build --minify false --sourcemap --outDir ../dist/debug`）上
   `Debugger.pause` 四轮停在同一串栈 `(anon)<(anon)<TrackRow<…react…`。`view` 在第一次渲染时还是 null，
   而 1.131 的 `laneTicks` 规矩是「没量到视口就不裁」——首帧把两万张卡片建完，第二次渲染才裁到 14 张。
   这一版没有动那条规矩（改动只在引擎侧与首页），但把它记成 1.133 的第一件事：**首帧就有界，并删掉那条不裁的分支**。

## 1.133 首帧就有界：两万段那一页终于画出来了

四处改动，全部由 1.132 那次调试器中断指出来：

- `desktop/src/timelineWindow.ts`：新增 `View` 类型、`FIRST_PAINT_PIXELS = 1200`、`firstView()`；`laneTicks` 收必填 `View`，
  「量不到视口就把整条时间线交回来」那条分支改成「按默认宽度算」，只剩 `px <= 0`（没有比例就无从换算）一个出口。
- `desktop/src/views/Timeline.tsx`：`useState<View>(firstView)`（原来是 `null`，而量视口的 effect 要等第一次提交以后才跑）；
  `paintRange` 不再有 null；`TrackRow` 的 `paint` 改成必填 `TickRange`，那条 `paint ? … : clips` 的三元删掉；
  `rulerMarks` 的窗口必填，顺带删掉它自带的那第二张间隔表（间隔的唯一主人是 `rulerStep`）；滑杆的 min/max 改读
  `ZOOM_MIN/ZOOM_MAX`。
- `desktop/src/store.ts`：`ZOOM_MIN/ZOOM_MAX` 一处定义，`clampZoom` 一个主人——`setZoom`、`zoomBy` 与**从 localStorage
  读回来的那份偏好**都过它；非数（NaN/字符串）不带走现值。这一处不是洁癖：`pxPerSec` 是 `laneTicks` 唯一还能
  「不裁」的那道门，而旧代码把偏好原样摊进初始状态，一枚写坏的 `agentcut.edit` 就够把两万段放回首帧。
- `tests/desktop_ts_check.py`：一条失败断言的那句中文在 node stderr 的**开头**，以前只截尾巴，报上来的全是一串
  `at file:///…`，看不出红在哪条断言——突变套件因此要求「红在自己的消息上」时无从可查。现在失败时两头都留。

门禁：`tests/desktop_20k_check.ts` 改的那几条钉的是首帧（`laneTicks(firstView(), …)` 与「宽度为 0」同解；三秒的小工程
不会被默认宽度切掉；两万段在 `px=100` 与 `px=ZOOM_MIN` 下首帧都不过界），`tests/desktop_zoomclamp_check.ts`
（第 45 个壳层检查，跑真 store：脏值、两端、NaN、写回 localStorage 的那份、滑杆与夹法同源，最后一行把夹法与首帧接起来：
`ZOOM_MIN` 下两万段的首帧仍是 71 张）。11 条突变逐条红在自己那条断言上，并且核对红的是哪一份 shell check。

装机实测（冻结引擎自报 1.133.0，渲染层从新 `app.asar` 抽出，同一个引擎实例 `3b3f86eb8f94`，工程线上 12,103,211 字节）：

| 页 | `renderer_scale` 判语 | 卡片 | DOM 节点 | 本次进程树峰值 | 用户态 CPU |
| --- | --- | --- | --- | --- | --- |
| 两万段（1.132 那份代码） | never-painted | 0 | 无从问 | 2,994 MB（渲染进程 2,370 MB 后进程消失） | 10.41 s |
| 两万段（1.133） | painted，6.7 s 内 | 13 | 485 | 843 MB（最大单进程 205 MB） | 2.21 s |
| 三段对照页（1.133） | painted，7 s 内 | 3 | — | 与上一行同一台引擎 | — |

那一句也在页面上念得出实数：「窗口外还有 19987 段没有画（它们仍在工程里，也在导出里）：往那个方向滚就出现。」
滚动与缩放都还带得动（这一轮的 CDP 探针：推一次滚动，再问一次 DOM）：把 1,240,440 px 的横向滚动推到 25%/60%/100%，
卡片 18/17/9 张、卡片左缘 309,814 / 744,000 / 1,239,440 px、那句话的数随之 19982/19983/19991，三次求值分别 1/1/0 ms；
把缩放推到上限 320 px/s，滚动宽度涨到 6,401,472 px 而卡片仍是 8 张、求值 0 ms。这把尺这一版也继续说真话：
本轮第一次采样（2.2 s）被它自己标成 `WRONG_PAGE` 拒了，它只认 `location.href` 与 `--url` 逐字相同的那一页。

「两万段能用」不等于「五十万段能用」：筛与数的那些 `Object.values(project.clips)` 仍是每条轨道、每次渲染一遍，
五十万段这台机器上没量过。首帧有界这件事现在由两处一起守着：窗口必填 + 缩放有下限。

## 1.134 命令键位成了一张能改的表，界面上念的是同一份

改的四处：

- 新增 `desktop/src/keymap.ts`：`CommandId`（13 条命令）、`COMMANDS`（id + 中文名 + 界面上那颗孪生按钮的名字）、
  `DEFAULT_MAP`（1.134 之前 `App.tsx` 那条 if 链实际在按的键）、`matchCommand`（唯一的解析处：精确 Shift 的那条赢，
  其次才是标 `"any"` 的那条）、`chordFromEvent`（改键时读一次真实按下；只按修饰键不算）、`chordWords`（念给人听的顺序：
  修饰键在前、键在后）、`chordUsable`（没有 Ctrl/⌘ 或 Alt 的单键直接拒——那会抢掉正在打字的人）、`rebind`（冲突点名
  被抢的那条命令）、`mergeMap`（从存储读回来时认不出的形状丢掉而不是让界面崩）、`changedFromDefault`（只写改过的那几条）。
- `desktop/src/store.ts`：`keymap()` 读状态、`remap.set/reset` 写状态并落 `agentcut.keys`，`runKeyCommand` 是
  **唯一一个**「这条命令此刻该不该做、做什么」的开关；条件不对就返回 false，早退顺序与以前那条 if 链一致。
- `desktop/src/App.tsx`：13 个组合键的字面量没了，只剩一次 `matchCommand(keymap(), event)` 与一次 `runKeyCommand`。
- 界面上凡是念键名的地方都改成读这张表：帮助页快捷键那一节新增「命令键位」那张表（13 行、每行一个「改键」按钮、
  一行「回到出厂键位」，等按键时那一格写「等按键…」），时间线工具条的分割/复制/粘贴/重做、标题栏的导出、
  检查器的「复制一段接到本轨末尾」都改念当前键位；引擎错误说明那句 LINK_IN_SYNC 里的「（Ctrl+Z）」去掉——
  键位现在是人自己定的，写死的那句会变成假话。

方向键微调、I/O/K/J/L、空格、Esc、F1/F9/F10、Ctrl+滚轮**不在**这张表里：它们跟着焦点与上下文走，
把它们也做成可配置的，只会让那张表看起来谁都能改、其实改了没用。门禁最后一条把这个边界钉住。

门禁：新增第 46 个壳层检查 `tests/desktop_keymap_check.ts`（跑**真 store**：13 条出厂键逐条对、解析处的六种情形、
改键后新旧键各自的命运、落库只有改过那一条、重启读回、冲突点名到「撤销」、被拒时现值不动、脏存储逐形丢掉、
回到出厂连存储一起清干净、视图与引擎提示里不许留着写死的键名、每条命令在那一个开关里有一格）。
14 条突变逐条红在自己那条断言上，并核对红的是哪一份 shell check。

装机实测（冻结引擎自报 1.134.0；渲染层从新 `app.asar` 抽出后深链同一份三段工程，同一台引擎实例）：
按 F1 开帮助 → 点「快捷键」→ 那张表念出 13 行（第一行「撤销 Ctrl / ⌘ + Z · 界面上：标题栏的「撤销」」，
剪开那行「在播放头处剪开 Ctrl / ⌘ + B」）；点「改在播放头处剪开的键」后界面上确实有 1 格写着「等按键…」，
真按一次 Ctrl+Alt+J 之后那一行变成「Ctrl / ⌘ + Alt + J」，`localStorage.agentcut.keys` 就是
`{"split":{"key":"j","shift":false,"ctrl":true,"alt":true}}`，toast 念「在播放头处剪开 换成 Ctrl / ⌘ + Alt + J」。
再点「改复制选中的片段组的键」并按 Ctrl+Z：得到「改不了这个键：这个键已经是「撤销」的了。复制选中的片段组
仍然是 Ctrl / ⌘ + C」，那一行的键名一个字没变、存储里也没多出东西。点「回到出厂键位」：那一行回
「在播放头处剪开 Ctrl / ⌘ + B」，存储清成 `{}`。关掉帮助，用 pointerdown/pointerup 选中一段（`aria-pressed` 回
true、`.clip.selected` 一枚），推十下 ArrowRight 再按 Ctrl+B：页面从 3 张卡片变 4 张，**引擎**读回
`revision 3`、`clips: 4`——这一下是真的写进了工程，不是界面自己改了自己的显示。

## 1.135 那张表管到工具键、两种删除与缩放

1.134 只把带 Ctrl 的命令放进了表，剩下 V/C/S/X、Delete / Shift+Delete、＋/－ 还写在 `App.tsx` 那条链的
后半段——一张表管一半，等于没有表：一个人改了键，另一半照旧，而帮助页与悬停会开始各说各的。这一版把
那 8 条也搬进来，表上共 21 条。

- `keymap.ts`：新增 `tool-select`(v)、`tool-razor`(c)、`toggle-snap`(s)、`split-at-playhead`(x)、
  `delete-selection`(delete, shift:false)、`ripple-delete`(delete, shift:true)、`zoom-in`(+)、`zoom-out`(-)。
  `chordUsable` 的判断跟着改准：1.134 那句「至少要带 Ctrl/⌘ 或 Alt」其实是把工具键一并拒了，而工具键天生是裸的；
  现在拒的是**只按修饰键**（那会让「按一下 Shift」本身变成一件事），裸键合法——拦在打字之前的那道判断是
  `App.tsx` 里 `const typing = …` 那一条，它跑在分发之前，门禁既断顺序也断它必须是活的条件。
- `store.ts`：`runKeyCommand` 多了这 8 格，条件与以前那条链一致（工具/磁吸/剪开/缩放要在时间线里，两种删除还要有选中）。
- `App.tsx`：那 8 个分支删掉，只留两个**别名**——Backspace 走同一条删除、「=」走同一条放大；它们不占键位，
  也不许被改键牵走（改了键之后它们仍指向那两条命令本身）。
- 悬停与说明改读同一份表：时间线的选择/分割工具、两种删除、＋/－ 缩放，检查器的「只删这一段」与
  「删掉这段并补齐」、「在播放头处切成两段」。

门禁：`tests/desktop_keymap_check.ts` 长到 21 行表、裸键合法、只按修饰键被拒（界面与存储两处都断）、
`typing` 那道判断必须活着且在前、三份视图文件里不许出现 `（V）（C）（S）（X）（Delete）（Shift+Delete）`
或 `（Ctrl+…）` 这样的写死键名；`tests/desktop_snappref_check.ts` 里「S 快捷键」那条接线改断新的唯一开关
（`case "toggle-snap"` 必须调 `prefs.toggleSnap()`），并断 `App.tsx` 不再自己认 S。19 条突变逐条红在
自己那条断言上，并核对红的是哪一份 shell check。

装机实测（冻结引擎自报 1.135.0，渲染层从新 `app.asar` 抽出后深链同一份三段工程；读的是客观信号：
工具条两个按钮的 `active` 类与状态栏那行 `NNpx/s`）：

| 这一步 | 选择工具 active | 分割工具 active | 状态栏 px/s |
| --- | --- | --- | --- |
| 刚开机 | true | false | 62 |
| 按一次 c | false | true | 62 |
| 按一次 v | true | false | 62 |
| 按一次 － | true | false | 50 |
| 按一次 ＋ | true | false | 63 |

再把「缩小时间线」改成 Ctrl+Alt+M（`agentcut.keys` 里就只有这一条
`{"zoom-out":{"key":"m","shift":false,"ctrl":true,"alt":true}}`，表上那一行同步念成
「缩小时间线 Ctrl / ⌘ + Alt + M · 界面上：缩放滑杆与「－」按钮」），关掉帮助后：按「－」——63，一动不动；
按 Ctrl+Alt+M——50。旧键退休、新键上岗，而那张表上 21 行的键名与工具条、检查器、状态栏的措辞是同一份数。

## 1.136 透明通道母版：把「据说必须」的开关和「量出来的字节」分开

引擎早就会让画面带着 alpha 走完合成——嵌套子合成非这样不可，`render.py` 里那个 `_transparent` 就是它。
但人或 Agent 想要一张能叠进 After Effects / DaVinci / 网页的透明母版时，**没有任何公开的入口**：
`RenderRequest` 没有这个词，预设表里没有一条声明自己装得下透明度，导出面板只有「画幅适配」和「导出范围」。
这件事的危险不在于缺一个勾选，而在于它容易被做成一句谎话：加个 `-pix_fmt yuva...` 就宣称支持透明，
而实际上 H.264 那条链根本没有地方放 matting，文件照样出货，用户到合成软件里才发现带着一块黑底。

### 一处声明，一处拒绝，一条路径

`_preset(..., alpha: bool = False)` 是「这条交付装得下透明度」唯一的一处说法，带 `alpha` 的两条：

| 预设 | 容器 / 编码 | 像素格式 | 音频 | 用途 |
| --- | --- | --- | --- | --- |
| `prores-4444-alpha` | mov / prores_ks（profile 4） | `yuva444p10le` | pcm_s24le | AE / DaVinci 合成回环 |
| `vp9-1080p-web-alpha` | webm / libvpx-vp9 | `yuva420p` | libopus 128k | 网页叠加层 |

`capabilities.alpha_presets` 由同一张表筛出来；`render.output_args` 收到 `transparent` 而预设没有 alpha
平面时，在编计划那一步就 422 `TRANSPARENT_NEEDS_ALPHA`，句子把那几条装得下的 id 念出来（音频预设也拒——
它根本没有画面轨）。这一句拒绝刚写出来时 `tests/error_vocabulary_check.py` 立刻红了：界面还没有对应的中文
hint，而「按了中文按钮却读回英文」正是这道门禁存在的理由。参数表里因此**没有** `-auto-alt-ref 0`——见下面
那一节：它是我先写进去、后被自己的测量删掉的。

公开的 `transparent` 与内部的 `_transparent` 在 `alpha_out` 一处合流。两者必须分开：内部那个还兼任
「这是父级已经验证过的嵌套子图，不要再验一次时间线」，直接把它当公开开关会让公开请求跳过
`validate_timeline`。`RenderJob` 带着这个勾，worker 到点重编计划时按它渲染；`transparent` 只在**为真**时
进入去重指纹（与 1.39 的 `range` 同一个办法），所以旧 `request_id` 继续原样重放，把同一个 id 从不透明
改成透明得到 409。

### 复检按字节量，不按字符串量

`tests/alphamaster_check.py`（第 89 项特性检查）不接受任何来自滤镜串的证据。同一条时间线：
0.5–1.5s 一段满不透明、1.6–2.0s 一段 `effects.opacity=0.5`、开头是空的；导出真走 job worker，然后用
FFmpeg 把 alpha 平面写成 8 位灰度 rawvideo，按点读那个字节。

| 交付 | 空处 alpha | 片段底下 alpha | 半透明处 alpha | 亮度（片段底下 / 空板） |
| --- | --- | --- | --- | --- |
| ProRes 4444 + `transparent=true` | 0 | 255 | 128 | 149 / 0 |
| WebM VP9 + `transparent=true` | 0 | 255 | 127 | — |
| **同一预设不带这个勾（对照）** | **255** | **255** | **255** | — |

那张对照行才是前面那些数字有意义的原因：没有它，「alpha=255」既可能是「matting 活下来了」也可能是
「整个文件本来就是不透明的」。亮度单独再量一次，于是「alpha 说这里有画」与「这里真的画了东西」是两次
独立的读数（否则一张全黑但 alpha=255 的画也能过关）。

量 WebM 那一头量出两件只能写进文档的事：

1. **容器元数据会撒谎**：`ffprobe` 在流那一层报的是 `yuv420p`。VP9 的透明度挂在每个 block 后面的附带
   通道里，`pix_fmt` 字符串不反映它——所以按 `pix_fmt` 断言「有 alpha」是一条永远量不到真相的断言。
2. **解码器也会撒谎**：FFmpeg 原生 vp9 解码器根本展不开那个平面，`alphaextract` 报
   `Requested planes not available`；要 `-c:v libvpx-vp9` 才读得出来。门禁的读字节路径因此按容器加解码器。

这两件合起来解释了我先写后删的那行代码：`-auto-alt-ref 0` 是「VP9 带 alpha 必须关掉自动备选参考帧」这条
流传很广的说法。我按它写了参数与注释，然后按字节量了 2 秒 60 帧的真实合成——**没有那个开关**，落盘的
alpha 仍然是 0 / 255 / 127，透明度活到了文件里。既然没有一行断言能证明它改变了产物，它就不该出现在参数表
里（一个改不动任何结果的开关，下一个读代码的人只能选择信注释或信代码，而注释是我写的）。参数表因此回到
「编码器的 knobs 只由预设决定」那一条老规矩，测量结果写在这里。要说清的是这一条只证伪了「必须」，没有
证明「无害」：带它时的字节我没量过。

### 第二条量出来的路：换一个画幅，补出来的边也得是空的

透明母版真正的用途是叠到别的画面上，而那通常意味着**交付帧的比例与时间线不一样**——补边补出来的那两条
到底是不是空的，是同一件事的第二半。这一条我先猜错、再用文件量回来：

- 先按「`contain` 补边会把透明压成黑板」改了 `render.py` 的 `fit_pre` / `fit_post`（轨道链那层的
  `pad=...:color=black` 与每段的 `format={pixel_format}`），并配了一条断言。
- 第一次量确实读到全 255——但那两次量的是我自己的量法：竖屏工程里放的是一段横屏片源，片源比例与交付帧
  一致，根本没有补边可读；我又用 `testsrc2` 单独试了一次，把 yuva420p 的第二个平面当 alpha 读（那是 U
  平面）。两次「缺陷」都是量错，不是编译错。
- 换成一段真正的竖屏片源（180×320）进 1920×1080 的透明交付再量：**pillarbox 边读到 0，画面中间 255，
  同一条不透明导出的边是 255**。也就是说合成那一层的 `pad=...:color=black@0` 本来就补对了，`fit_pre`
  那条改法是够不着的死分支——已逐字回退，只留下这条按文件量的回归断言，以及一条反向断言（透明计划的
  滤镜串里不许出现不透明的 `pad=...:color=black`）。

这一段留下两句话：动手之前先证明量的是产物（第二个平面是 U 不是 A，这类错只有读错时才会显出「缺陷」）；
补边属于「换个画幅才暴露」那一类，所以它必须和主测量一样按字节量，而不是按滤镜串推。

## 1.137 起始时间码：规矩不能交给 muxer，位置不能靠猜

母带交接要带 SMPTE 起始时间码。这件事看起来只是把一串字递给 FFmpeg，实测却不是：

| 输入 | 这台机器上 FFmpeg 直接写出的结果（不经过引擎） |
| --- | --- |
| `01:60:00:00` | `02:00:00:00`（无效的分钟被进位到小时） |
| `01:02:03.04` | `01:02:03;04`（点被当成丢帧标记） |
| `1:2:3:4` | 原样收下（每段一位数字） |
| `01:02:03;04` @ 30/1 | 原样写进 mov（SMPTE 只在 29.97／59.94 定义丢帧码） |

一份把数字改写了的母带比一次拒绝更坏——人到机房才发现对不上带上的字。所以判断在引擎：
`contracts.checked_timecode(value, frame_rate)` 是唯一那处，写法（每段两位、冒号或分号）、小时≤23、
分秒≤59、**帧号必须小于这条时间线自己的帧率**（`round(numerator/denominator)`：30fps 到 29、25fps 到 24）、
分号只给 (30000,1001) 与 (60000,1001)。不满足就 422 `TIMECODE_INVALID`，句子点名是哪一段、收到的是几。
没有画面的预设（mp3／wav／flac）另有一条 `TIMECODE_NEEDS_PICTURE`：时间码是给画面数帧的。

请求侧走的是 1.136 那条已经踩好的路：`RenderRequest.timecode` → `RenderBatchItem.timecode` →
`RenderJob.timecode` → worker 重编时写同一个；只在**非空**时进去重指纹（旧回执原样重放，同一个
`request_id` 改数字得到 409）；`GET /render-plan?timecode=`、MCP 的 `render_plan`（整串百分号编码——
分号在 query 里是有歧义的字符）、以及 `GET /v1/jobs/{id}` 那份计划都带它。

### 位置是每个容器自己的事

`tests/timecode_check.py`（第 90 项特性检查）导同一条时间线的四份交付，然后按**各自真正存放的位置**
把串读回来：

| 容器 | 存在哪一层 | 键 |
| --- | --- | --- |
| mov / mp4 | 视频**流**标签 | `timecode` |
| mxf | **容器**标签 | `timecode` |
| webm | **容器**标签 | `TIMECODE`（大写） |

写这条检查的时候，「读 format tag 里的 timecode」看着就够了——那会让 mov／mp4 那两份实际写在流标签里
的文件被读成「没有时间码」，反过来也一样：只看流标签则 mxf／webm 读不到。四个位置各读各的，才是这份
证据成立的方式。丢帧码那条也一样：29.97 的工程写 `01:02:03;04`、读回 `01:02:03;04`，而整数 30 的
工程同样这一串会被引擎拒掉（对照实验就在同一次检查里：先让 FFmpeg 证明它会照写）。

### 界面那一栏只交出一个值

`ExportPanel` 里那一栏是纯文本，写法与「哪两个率有丢帧码」都从 `capabilities.timecode_shape`／
`timecode_drop_rates` 拿，视图里不许出现第二个正则（门禁断 `{2}` 不出现）。空串一律当「不写」，
发出去的值只有 `sendTimecode` 一处，三处调用（待发清单、干跑、开始导出）用的都是它。

这一栏还留下一个只有 tsc 抓得到的坑：状态最初写成 `const [timecode, setTimecode] = useState("")`，
于是它把 `../time` 里那个格式化时间的 `timecode()` 函数整个遮住，导出摘要那行
`timecode(end, frame_rate)` 变成「调用一个字符串」。改成 `timecodeText` 之后，
`tests/desktop_timecode_check.ts`（第 48 个壳层检查）就多了一条专门断这层遮蔽不许回来的行；
同一份检查跑真 `Engine`、假 `fetch`，断要写时 body／query 里有它、不写时一个参数都不多、
批量两项各留各的答案。两条门禁合起来 16 条突变，逐条红在自己的断言上。

### 装机实测（发布包，不是源码树）

`released_package_check.py` 先确认了看的是同一件东西：根目录 `AgentCut.exe` 与
`release/AgentCut-便携版.exe` 逐字节相同，`app.asar` 带的是 1.136.0（84 个文件），里面装的引擎就是
`build_engine.py` 刚冻出来的那一个，渲染层里 11 句人话（含新的「背景透明 / 空白处留透明 / 装不下透明度 /
ProRes 4444 透明母版」）在产物里读得到。

冻结引擎（`win-unpacked/resources/bin/agentcut/agentcut.exe`，自报 1.136.0）交出的文件按字节量：

| 交付 | 空处 | 片段底下 | 半透明 | 备注 |
| --- | --- | --- | --- | --- |
| ProRes 4444 透明母版 | 0 | 255 | 128 | 复检写着「2.000 秒 / 2 路流（prores/pcm_s24le）/ mov，尾部可解码」 |
| 同预设不透明（对照） | 255 | 255 | 255 | 黑板是不透明的 |
| WebM/VP9 透明 | 0 | 255 | 127 | 读它要 `-c:v libvpx-vp9` |

亮度另量：绿带处 149、空板处 0。H.264 要透明被 `TRANSPARENT_NEEDS_ALPHA` 点名拒掉，句子当场列出
`prores-4444-alpha、vp9-1080p-web-alpha`；拒完之后 revision 仍是 1、任务表仍是 3 条（一条都没多）。

打包渲染层（从新 `app.asar` 解出来，用 Chromium `--headless=new` 真指针事件点）那一段读到的顺序是：
默认 H.264 时那颗勾 `disabled=true`，悬停里写着「装不下透明度」并点名 `prores-4444-alpha`；预设列表 18 行
里有 `ProRes 4444 透明母版（AE / DaVinci 合成回环）` 与 `1080p WebM/VP9 透明（网页叠加层）` 两条；点中
ProRes 那一行之后那颗勾能用；点下去之后竖屏那条 9:16 副本 `disabled=true` 且标题写着「背景透明时竖屏那条
…写不下透明度」；按「开始导出」之后**引擎自己**多了一条任务：`preset_id=prores-4444-alpha`、
`transparent=true`、`status=succeeded`、`output_checked=true`、产物 683134 字节，任务表只多 1 条，
`plan.transparent` 也回真。这一段的证据全部来自引擎回执与元素矩形，不是 DOM 上「看着有个勾」。

### 界面那条路：一个函数决定那个勾算不算生效

`engine.matteAllowed(preset, audioOnly, requested)` 是界面上「背景透明」此刻生不生效的唯一判断。它被问
五次：勾本身（`checked={matte}`）、什么时候灰掉（`!preset?.alpha`，悬停写明「装不下透明度」并念出可换的
那几条）、待发清单里写出去的值（`transparent: matte`）、「查看渲染计划」与「开始导出」两颗按钮。
竖屏那条 9:16 副本是 H.264，透明母版与它不能同时成立，所以要透明时整条被让掉——让路的这件事写在
悬停里，不是悄悄少发一个文件。

`tests/desktop_alphamaster_check.ts`（第 47 个壳层检查）跑真的 `Engine`，把 `fetch` 换成一个记录请求的
假件：真值表五种组合、POST body 里那个字段等于所问（要真也断、默认假也断，否则「漏掉参数」会被默认值
伪装成正确）、干跑的 query 只在要为真时带上这个键且其余参数不错位、批量两项各留自己的答案，最后是
面板那五条接线与「不许出现写死的 `transparent: true`」。两条门禁合起来 22 条突变，逐条红在自己的断言上，
并核对红的是哪一份检查——其中一条（worker 重编计划时丢了那个勾）只有按字节量的那行断言才抓得到，
它把三处 alpha 全读成 255：正是这类「参数还在、画面已经不是那幅画面」的缺陷，只有产物能作证。

同一次改动还补了两处同源欠账：`GET /v1/jobs/{id}` 那份计划过去直接调 `compile_render_plan` 而不带任务的
`range` 与 `transparent`，于是「排队中看到的计划」与「将要渲染的活」可以是两回事——现在它走 `plan_for`，
与提交、worker 同一处；MCP 的 `render_plan` 过去连 `range` 都不问，现在把 `range` 与 `transparent` 一起
带出去，并且门禁把「MCP 拼出的那串 query」原样发给 HTTP 侧，断 `plan.transparent` 真的是真——参数名打错
这种只有两端一起看才会露出来的错，就是这么抓的。

## 1.138 交付帧率：闭表拒掉的是「数值一样而有理数不同」

时间线的时钟与交付的帧率本来就该是两个数。以前两者只能是一个：预设里写着编码，`fps=` 写着
`settings.frame_rate`，谁也不能说「我这条 30 的线要按 25 交出去」。这一版补的就是那一词。

**为什么是闭表而不是「任意正有理数」**：时间线的刻度是 `TIMEBASE = 70_560_000`，一帧必须是整数
tick，否则两端（FFmpeg 与界面）对「第几帧」会慢慢说出不一样答。更实际的是这批率全都有名字：
24／23.976／25／29.97／30／50／59.94／60，写别的号的人不是要交接，是要打错字。表外一律 422，
句子把八档念出来，不让人猜。

**这一轮真正值钱的一条拒**：`30000/1000` 数值上等于 30、`23976/1000` 数值上等于 23.976，
`29970/1000` 与 `59940/1000` 也一样「看着对」。如果判断写成 `numerator/denominator == 30.0`，
这四条全会通过，然后落地的文件的 `avg_frame_rate` 是 `30000/1000`——读的人以为拿到了 29.97。
门禁里这四条各占一次拒绝，判断只看有理数对 `(分子, 分母)`。

**两条被自己的突变组抓出来的东西**：

1. `parse_frame_rate` 一开始带着一道「分子分母都得在 1..240000 / 1..10000」的上下界检查。
   突变行「把上下界不判」跑完是 **STILL-GREEN** ——因为表外的数在 `_require_output_rate`
   那一处就被拒了，永远不会拿它去构造 `FrameRate`。那三行是死代码，删；同时把「表内才构造」
   写进那句 docstring，下一个人不必再补一道判。
2. 批量那条突变行原本钉在干跑分支的 `RenderJob(...)` 构造上（`output_frame_rate=item...` +
   `filename=...` 那个形状），跑出来 STILL-GREEN：真正决定落地文件的是紧接着构造
   `RenderRequest` 的那一处。改锚点之后当场红。同一行字段在文件里出现四次，钉错一处就等于
   没测——这是「突变必须打在门禁真读的那个键上」的又一次实测。

**产物侧的实测**（`tests/output_rate_check.py` 打印的就是这些）：同一条两秒时间线交三版，
ffprobe 读回 `30/1` 60 帧 2.000 s、`25/1` 50 帧 2.000 s、`24000/1001` 48 帧 2.002 s——
**时长没被重采样拉长或剪短**，这是「换率不改内容」的证据；一次批量两份文件各自读回 `25/1`
与 `30/1`，说明每一项带自己的答案而不是共用第一条。GOP 从 `-g 60` 变 `-g 50`、`-keyint_min 25`，
而滤镜节点数（6）与输入参数（12 项）一字不差——换的只有重采样与关键帧间隔。

**与 1.137 同构的一条规矩**：纯音频那三条预设没有画面，帧率无处生效。如果收下之后再什么都不
改，界面就会说「已经交成 25 了」而文件根本不是那回事，所以给 `OUTPUT_RATE_NEEDS_PICTURE`；
不选的时候那条 argv 与以前逐字相同（`-vn` 那一支一个字没动）。

**界面侧只允许有一份表**：那颗下拉的候选来自 capabilities 的 `output_frame_rates`，
`tests/desktop_output_rate_check.ts` 里有一条突变专门把面板改成抄一份自己的表——红在
`panel-asks-engine-for-the-table` 上。另一半是「没选就不发」：引擎契约是 `extra="forbid"`，
多发一个老引擎不认的键会整条拒收，所以 body 与 query 都是「选了才写」。

## 1.139 一个注释里早就写着的答案：那一刀的帧尺是谁的

1.138 落地当天复量时没有碰到的组合，在下一步自己冒出来了：**标了入出点、又换了交付率**。
`render.py` 里切区间那一段的注释是「Frames for the picture (the stream is already `fps=` normalised)」,
而它下面一行写的是 `frame = settings.frame_ticks`——**时间线**的一帧。两把尺一直相等的时候，这句话
和这行代码互相圆场；1.138 让它们可以不等，于是切错了段。

量出来的事实（探针，不是推断）：30 的线标 1..2 秒、源是「红/绿/蓝各一秒」的三秒片，

| 交付率 | 落盘帧 | 逐帧颜色 | 该是多少 |
|---|---|---|---|
| 30（跟时间线） | 30 | 全绿 | 对 |
| 25 | 25 | **20 绿 + 5 蓝** | 入点少 0.2 s、出点多露 0.2 s |
| 23.976 | 24 | **18 绿 + 6 蓝** | 同上，比例更狠 |

`plan.range.seconds` 那时还写着 1.0，`-t` 又把文件截到一秒长——**帧数与时长全对，只有内容在说谎**。
这就是「断言要打在产物上」而不是「打在计划字段上」的又一次理由：任何只看 `nb_frames` 的门禁都会
为这一版鼓掌。

改法是把除数换成交付流的帧长（`TIMEBASE × 分母 ÷ 分子`，八档都整除），两头向上取整。为什么是
向上而不是「四舍五入」：交付帧比时间线帧粗的时候，向下取整会让第一帧**早于**入点（把上一段的内容
带进交付里），向上取整最多让最后一帧的起点略早于出点——宁可少一帧收尾，不可多一帧穿帮。没换率时
两头取整都回到原来那对帧号，`trim=start_frame=30:end_frame=60` 一字不变（门禁专门钉了这条对照）。

顺带抓到一条只有极端组合才露面的：60 的线标「第 1..2 帧」按 25 交时，上下两头向上取整会撞到**同一个
帧号**，那一刀就成了零帧的切口。留了一条兜底：短窗口至少撑成一帧。这条也在门禁里，突变把 `max(…)`
去掉就红。

声音那一头本来就是按秒切的（`atrim=start=1.000000:end=2.000000`），三个率下都是同一句——所以修法
只动画面那一刀；门禁里留了一条「音频那一句必须还是秒」的断言，谁把它也换成帧号会红（这条不是假想，
是突变组里的一行）。

## 1.140 同一条规矩从另一头又回来了

1.137 的全部理由是：FFmpeg 对时间码太宽容，会收下非法写法并**改写成别的数字**。1.138 让「一秒里有
几帧」有了两个答案，而那句校验还钉在时间线那一档上——于是 1.137 拦的那件事换了个入口又进来了。
这次不是推测：门禁里让 FFmpeg 自己出面（不经引擎），在一条 25 fps 的流上写 `-timecode 00:00:00:29`，
它照单收下，`ffprobe` 读回来是 `00:00:01:04`。人打的数被改了，而这正是六版之前立规矩要拦的事。

反面同样要紧：**25 的线按 30 交，写 `00:00:00:29` 被拒**，可那份文件一秒有 30 帧，第 29 帧明明存在。
一条规矩拦过头和放过头都会让人学会「绕过它」，所以这一版两头都钉：三档工程（30／25／29.97）×
该收/该拒各占一格，全在 `tests/timecode_rate_check.py` 里跑真实的 HTTP 与真实的导出文件。

丢帧码是同一处的第二个判断：分号只有 29.97 与 59.94 有定义——这句话现在说的是**交付**那一档。
29.97 的线按 25 交写分号，被拒（文件里根本没有丢帧这回事）；30 的线按 29.97 交写分号，收下。

界面两处跟着改，因为它们原来在猜：提示那句「帧号不能超过这条时间线的帧率」现在说「这一条交付
画面的帧率」，那颗「分号可用」的判断从 `effectiveRate = sendFps ?? timelineRate` 来。旧那句话由门禁
要求**消失**（不是「别再用」，是「出现就红」）——一个说「可以用分号」的界面配一个会拒的引擎，比一个
空着的判断更糟。

工程上的收获写进习惯：**每加一个可以改变产物语义的开关，就把已经存在的、依赖同一语义的规矩再过一遍**。
1.138 只加了交付率，真正欠的是「哪些地方假定过交付率==时间线率」：这次找到的两处（区间帧号 1.139、
时间码 1.140）都是那种「所有计数器都对、只有内容在说谎」的缺陷，只能由读内容/读字节的门禁抓到。

## 1.141 交叉表：把「只在组合里出现」的那一类永久钉住

1.136 透明、1.137 时间码、1.138 交付率、1.139 区间 × 交付率、1.140 时间码 × 交付率——每个开关都有
门禁，**没有一个门禁把它们一起按下**。1.139 那次已经证明「每个开关单看都对，乘在一起才是真产物」，
所以这一版专门补交叉表：ProRes 4444 透明母版 × 25 fps、以及 webm alpha × 标记 1..2 秒 × 时间码 ×
23.976，读的都是落盘的文件。

结果是没有新缺陷（alpha 中间格前后都是 127、24 帧、1.008 秒、时间码读回 `00:00:00:23`），但这一版
值钱的地方在过程中：

1. **颜色名不是满值**。第一次把「红/绿/蓝」写成 `color=red` 之类，`green` 其实是 0x008000（半绿），
   一个 `g > 90 就算绿` 的宽松分类把整段都认成「绿」——包括 alpha 丢掉之后被预乘压暗成
   `0:126:0` 的画面。也就是说：**我第一版的门禁会把要抓的缺陷读成正确**。改成三个满值纯色 +
   严格分类（一个通道 >150、另两个 <100 才算那个纯色，否则留 `其它r:g:b`），两条「透明丢失」的突变
   当场从绿变成 `其它125:0:1 / 0:126:0 / 0:0:125`。
2. 交叉表必须**同时**验内容与数值：`frame_count` 用 `-count_frames` 现数（webm 的头里没有 `nb_frames`），
   时长读容器（webm 的流里也没有 `duration`），alpha 走 `alphaextract` 且 webm 必须点名
   `libvpx-vp9` 才解得开（1.136 量的事实，这里第三次用到）。
3. 5 条突变的红各自落在不同断言上：`alpha_out` 不要求透明平面 → 逐帧颜色；worker 丢 `job.transparent`
   → 同一句逐帧颜色（两条不同代码路径、同一个症状，正是想钉的东西）；交付率不参与 → `avg_frame_rate`；
   帧尺退回时间线 → 四开关那一份的 `set(colours)`；时间码不写给 muxer → 流/容器两处都读回来的那串。

工程结论：**新开关落地时，除了给它自己写门禁，还要把它乘进已有开关的交叉表**——否则下一个
「帧数、时长、率全对，只有内容在说谎」的缺陷要等到装机那天才露头。

### 1.141 续：把画面内容也乘进去，以及一份被自己的突变组纠正的门禁

交叉表只乘了「交付开关」还不够——真正决定这条片子能不能叠回去的是**画面内容**：柔焦宽度、曝光电平、
不透明度。于是加了 `tests/grade_matrix_check.py`：中灰硬边源 + `blur` + `clip.color.exposure` + 0.5
不透明度，交三份（不透明@30、透明 ProRes@25、标记 1..2 秒的 webm alpha@23.976），全部从文件里读数：

- 柔边宽度必须按**画面宽的比例**比。第一版按 px 比，量出 80.6 vs 13.4 差点当成缺陷——那是
  `prores-4444-alpha` 按源尺寸交（320 宽）而 `h264-1080p` 放大到 1920 宽的必然结果。归一之后
  0.0419 / 0.0418 / 0.0419，一致。
- 源必须是**中灰**而不是纯白：曝光压在 255 上会裁顶，那样「曝光有没有落到成片里」根本读不出来。
  顺带纠正一个自己的误解：`ClipEffects.gain` 是**音量**（`Inspector` 那一栏就叫「音量」，导出走音频链），
  画面上的电平是 `clip.color.exposure`——写门禁前先看名字对应的是哪条链，别猜。
- 最值钱的一次纠正来自突变组：「把 alpha 平面不再要求」（`alpha_out` 写死）跑出来是 **STILL-GREEN**。
  原因是我只断了「合成之后是同一个数」——把透明度烘进 RGB（90）和交给平面（181 × 127/255 = 90）
  在数学上给同一个结果，所以一条**丢了透明母版本身**的改动被喂饱了。补了两条各管一头的断言
  （平面必须在 120..135、透明母版的 RGB 不许发暗 ≥150）之后它才红在该红的那句上。
  结论值得记住：**等价于「视觉上一样的两种交付方式」的断言，会放过「其中一种交付方式根本没做」的缺陷**。
  要钉的是「透明度到底住在哪儿」，不是「看起来一样」。
- 还有一条诚实的边界：这一份门禁**不**证明区间切在哪。它的源在时间上是平的（整片同一个边、同一级
  灰），窗口挪 0.2 秒读数不变——所以「帧尺退回时间线」那条突变在这里 STILL-GREEN 是**正确的**，
  那一条由 1.139 与 1.141 的红/绿/蓝签名门禁钉住。每份门禁只声称它证得了的事，否则绿是假的。

## 1.142 交付物变成一串文件之后，「检查」这件事也得跟着换单位

前面每一版的复检都是一个单位：一个文件。图像序列把这个单位换成了帧，于是三件事必须重做，
而不是在原来的函数里加个 `if`。

- **点数而不是读头**。`verify_output` 那套（容器名、两路流、时长、结尾 0.5 秒解码）在序列上
  全都没有对应物：没有容器，没有流，没有时长标签，声音这一路根本不存在。新的
  `verify_sequence` 点的是**文件**：期望帧数按**交付率**算（与 1.139 同一把尺，不是时间线那把），
  编号从 000001 起必须连续，首尾两帧先用 ffprobe 认出是画面、再用 `ffmpeg -f null` 真解码一遍。
  最后这半步是必需的：ffprobe 只读头，「最后一帧只写了个头」在它那里完全正常。
- **发布不再是 `temp.replace(target)`**。一串文件没有「一次原子改名」可用，所以帧先落进兄弟目录
  `名字.part/`，点过数才逐帧 rename 进最终目录，失败与取消只删自己那一串编号的文件、目录真空了
  才删目录。同名第二次交付**往后让**成 `名字-2/`：覆盖别人的开链成果是不可逆的。
- **免掉一条 `-map` 不等于不写声音**。第一版把 `has_audio` 接上、序列不再 `-map [aout]`，
  真实渲染直接失败：`Filter anull:default has an unconnected output`（实测退出码 4294967274）。
  滤镜图里那条 `[aout]` 是个悬着的输出 pad，FFmpeg 在建图阶段就不干。修法是在编译时给序列补一个
  `anullsink`；这件事**只能**在编译时做，因为 `filtergraph.txt` 是先交给调用方写盘、argv 是
  之后才建的——两处各写一份拼串就会出现「文件里有没有 sink」与「命令行里有没有」不一致。
  于是图文本收成两处唯一来源：`render_graph_text()` 与 `frame_graph_text()`。

这一版还给「门禁自己会不会根本没跑」交了一次账：第一版 `tests/sequence_check.py` 写了 `main()`
却忘了 `if __name__ == "__main__": main()`，套件把它当成一项通过，两秒就绿。门禁必须真的跑过，
存在不等于执行。


## 1.144 一条读两幅画的边：先把「一个旋钮两件事」量死再画线

前面的调色节点全是每通道函数，链子怎么长都能塌缩成「每通道一张表」，两端读同一张表。
`composite` 是第一个读两幅画的节点，于是那条「表对表」的捷径到此为止——它必须变成图上的两条边。
两处决定都不是设计出来的，是量出来的：

- 先在 YUV 平面上直接 `blend=all_mode=screen`，中性灰的交付读回来是 (255,150,255)：`blend` 逐平面，
  色度 128 被 screen 抬到 192。**相合必须在 RGB 平面上做**，现在三路各自 `format=gbrp` 再相合。
- 再想用 `blend=all_opacity` 一个旋钮同时表达「方式」和「权重」：实测 `normal` 是干净线性插值
  （0 给第二路、1 给第一路），而 `screen`／`multiply` 在 0 时退回第一路——**一个旋钮两件事一定会谎报**。
  所以编成两段：先按方式相合，再用 `normal` 按权重插值。

参照点也由同一条链自己量（原图 132、调完 184），门禁断的是 `mix=0` 逐值等于原图、`mix=1` 等于
按公式算出的相合值、`mix=0.5` 等于两端中点，外加「链首链尾同像素」「停用等于没挂」。
教训照旧：**先验仪器，再定阈值**——两端都读同一份数的前提，是那份数在两端真的是同一件事。


## 1.146 基色转换表：交一份由引擎算的数，不交那颗按钮

`transfer` 那个节点只管色调曲线，**不动基色**：把 Rec.2020 的素材当 Rec.709 用，gamma 对得上、
色域对不上，同一组存储值落在色域三角形里的另一个位置。1.52 探过一颗 `gamut` 节点、没收口，
账记在那里。这一版收的是**数据那一半**：新增 `src/agentcut/gamut.py`，由 xy 与白点解出每原色
缩放、`M = inv(A_target) · A_source`，把六档常用转换（2020↔709、DCI-P3↔709、Display P3→709、
Rec.601→709）连同两端传递函数名一起交进 `capabilities.gamut_matrices`。矩阵由引擎算，
界面与 Agent 都从这一处读——手抄的九个数迟早和另一侧不一样，而这种不一致在成片里只表现为
「颜色有点偏」，没人会当 bug 报。没有那颗按钮，就不说按钮的谎：界面这一侧这版不接线。

数对不对，`tests/gamut_check.py`（套件第 99 项）两层一起量。

- 表的性质，不引记忆里的发表值：每行和恰为 1（中性灰不动）；每一档正逆往返是恒等（1e-12）；
  **每一列**与「源档那号原色的色度经 XYZ 换算到目标档」成比例——颜色是三维向量的等价类，
  比方向之前必须先归一化，而且用绝对值最大的一维做基准，拿一个接近 0 的系数去除会把误差
  放大成假红（本轮先踩过一次）。
- 但自洽性质有一个共同盲区：它们都是拿实现自己的基色数据反过来核自己。`PRIMARIES` 里把一个
  xy 少抄一位，矩阵和那条射线会用同一份错数据算出来，三条性质全绿、每一档却都偏。所以钉一颗
  **外部锚**，取自本仓库自己的测量记录：1.52 那节记下「与公布值一致」的 709→P3 九个数字
  `[0.92092 0.19879 0; 0.03717 1.08255 0; 0.01913 0.08106 1.01952]`，行和 1.11971——那是整颗
  矩阵乘了同一个 1.12（方向不动，白点被抬到 1.12 再钳位）。把那九个数除以行和就是行和为 1
  的那一份归一化，与本表逐系数差在 7e-6 内（本轮实测九个全对，两个来源对上的是同一颗矩阵）。
  被这颗锚钉住的是 rec709 与 P3 两档的 xy；rec2020、rec601 没有可钉的外部数，只有自洽性质——
  这一句照实印在门禁的打印里，下一版拿 FFmpeg 自己的 `colorspace` 换算补上那一半（仪器就在
  随包的那个 ffmpeg.exe 里，不必引外部表）。
- 记一笔**被门禁拒掉的锚**：我按记忆里的「流通公布值」给 709→Rec.2020 钉了
  `[0.62740 0.06910 0.01639; 0.02640 1.0 0; 0 -0.00550 1.00550]`，restore 后直接红在锚那行。
  一算行和：0.7129、1.0264、1.0——一颗基色转换阵若把两档同一白点相合，必须满足 `M·(1,1,1)=
  (1,1,1)`（两边都是中性白），行和不为 1 的那一份**不可能是这件事的答案**；而它的逆阵方向那份
  流通表 `[1.6605 -0.5876 -0.0728; -0.1246 1.1329 -0.0083; -0.0182 -0.1006 1.1187]` 与本表实测
  `[1.66049 -0.58764 -0.07285; -0.12455 1.13290 -0.00835; -0.01815 -0.10058 1.11873]` 逐系数
  吻合，行和 1.0001、1.0、1.0。至于那份行和 0.71 的表从哪儿来，本轮没有量出来，只记下它的
  「第一行」恰与本表的「第一列」相同（第二行就对不上第二列了），不足以断言是行列次序写反——
  结论只到「它不满足中性白守恒，不能当锚」为止；不能为了让表看起来有锚就把记不清的数钉进去。
- 真走一遍导出（320×180、两段各一秒）：不挂 / 挂 2020→709 / 再挂 709→2020 走一趟来回 /
  同一条链但两个矩阵换成差 1e-6 才等于单位阵（对照组）。实测中灰
  `(130,127,131)→(129,126,130)`（不动，行和为 1 的那件事）、橙红 `(179,79,50)→(216,41,1)`
  （真的换档）。选橙红不选纯 2020 红：后者在 709 里越界，钳位后落回同一条射线，那种「没变」
  是对的，不能当判据。

来回一趟并不恒等：橙的蓝从 50 落到 40。这一笔不该记在矩阵头上，也不该靠放宽容差糊过去，
所以用对照组把它拆开——同一条链自己漂 6 级，矩阵那部分再多漂 4 级，界就定在「不超过这条链
自己的量化成本」。成因是 `transfer` 落进**线性光时那一站仍是 8 位**：存储值 50 线性后只剩
约 7 个码字，暗部一进线性就被量化吃掉一大截。这正是 1.52 拦下 `gamut` 节点的那笔账，
这一次量成了两个数而不是一句推测；要把它消掉，得把整条渲染链的位深与 `color_range` 一起
管住并重测所有既有调色门禁，本版本没做，也不假装做了。

顺带纠 1.52 那节的一处记录：它写「与公布值一致」的九个数字是
`[0.92092 0.19879 0; 0.03717 1.08255 0; 0.01913 0.08106 1.01952]`，行和是 1.11971——那是同一
矩阵每行乘了约 1.12 的另一种归一化，拿它当锚会把整张表钉歪、中性灰跟着漂。锚用行和为 1 那一份。

变异电池九行，每行在自己那条断言上红：逆阵按行拼（转置）、矩阵乘法次序颠倒、源与目标同时
对调绿蓝两号原色、系数只留 2 位小数、Rec.601 白点改 D50（必须拒）、能力表那个键改名、
九个数按列主序写进 `matrix` 节点、两段素材读同一帧（仪表自己骗自己）、Rec.709 红原色 y 少抄一位。
最后两行是本轮新学的：前者钉住「行主序」这一处约定——转置交出去，导出那一层的「中灰不动」
当场红（矩阵换成列主序后行和不再为 1，灰被抬走），后者证明时间读错会把两段素材并成一段；
而 Rec.709 那一处笔误三条自洽性质全绿，只有外部锚抓得到。另外两行量出来
之后退掉了，理由记在脚本里——把对照组换成真单位阵永远绿（单位阵乘在 8 位存储值上不产生舍入，
删掉那两个节点读回的数一模一样，都是 `(177,78,44)`），而「系数整体乘 1.05」本来就是表层的账
（行和不为 1 由 `check_table` 钉住），5% 线性增益在中灰上只动 2 级，导出那一层抓不到也不该抓。

## 1.146 的另一半：装机复核抓出「打包版找不到自己那份 ffmpeg」

挂着上面那张表做装机复核（冻结引擎、真实交付、真实像素）时，第一份不挂调色的交付照常出片，
第二份挂了 `transfer-matrix-transfer` 的直接失败，引擎回话
`FFmpeg 退出码 …：Unrecognized option 'filter_complex_script'. Error splitting the arg`。
两条路只差**滤镜图的长度**：调色那一条把曲线采样成 `lutrgb` 的长表达式，越过
`GRAPH_SCRIPT_LIMIT = 12000` 后 `render.py` 换成发 `-filter_complex_script filtergraph.txt`。
顺着查下去是三件事叠在一起：

- 打包后的形状是 `resources/bin/agentcut/agentcut.exe` 与 `resources/bin/ffmpeg.exe`，
  而 `_find_binary` 的搜索表只有 `_MEIPASS`、引擎自己那一层、`引擎层/resources` 三处——
  随包那份在**上一级**，一处都不命中；`release/win-unpacked` 整棵树里 `find` 也只数得到那一个
  `ffmpeg.exe`。于是冻结引擎一路落到 `shutil.which("ffmpeg")`。
- 这台机器 PATH 上那份是 **9.0.2**（winget 的 gyan full_build）。实测 `-h full` 里
  `filter_complex_script` 出现 0 次；随包的 6.1.1 出现 1 次。短图走 `-filter_complex` 内联，
  两版都认，所以「照常出片」把那台机器一直在用别人的 ffmpeg 这件事藏得严严实实。
- 结论不是「FFmpeg 9 不能用」，而是**发布包不该赌用户装了什么**：引擎该用随包那一份。
  修法是把 `_app_dir().parent` 加进搜索表（一行），新增门禁 `tests/ffmpegpath_check.py`
  在临时目录里搭出真实形状断言三件事：随包那份胜过 PATH 诱饵、包里没带时仍走 PATH（那是用户的
  选择，不是缺陷，所以这条断的是「还照着做」）、`--ffmpeg` 与 `AGENTCUT_FFMPEG` 更说了算。
  变异：把那一行删掉，第一条断言当场红；还原回绿。

还欠一笔，记在这里不藏：引擎现在**没有**验证它拿到的 ffmpeg 认不认自己将要发的每一个选项。
随包那份 6.1.1 认，所以打包版安全；但用户用 `--ffmpeg` 指一份 9.x，长图仍会以那句
`Unrecognized option` 失败——那时候该给的是「你指的这份 ffmpeg 不支持长滤镜图（换随包的那份）」
这样一句能执行的话，而不是 FFmpeg 的原始 stderr。这一条留给下一版，与本表无关、与「界面允许、
导出会拒」这条红线有关。

1.146 的验证账（数字都是这一轮量出来的）：`ruff check`+`ruff format` 干净；全量套件单跑
**100/100 通过**（`tests/suite_check.py`，其间机器上别的东西都没动；新增两项 `gamut_check.py`
10.4 s、`ffmpegpath_check.py` 0.2 s），`npm run typecheck` 与 52 个壳检在其内。
`scripts/build_engine.py --verify` 通过，`npm run dist` 产出 `AgentCut-便携版.exe` 189,903,294 B、
`AgentCut-安装版.exe` 190,064,007 B，根 `AgentCut.exe` 与便携版 `cmp` 逐字节一致
（SHA-256 前缀 `110f7974b25e3926`）。装机复核 `package_check_1146.py` 全 PASS：冻结引擎自报
1.146.0、`gamut_matrices` 六档的九个系数逐字节等于源码现算，**挂调色那一条长滤镜图的交付在打包版里
照常出片**（就是这一句把上面那个缺陷抓出来的，修完后同一条命令回绿），成片像素与源码引擎逐项相同
（中灰 `(130,127,131)→(129,126,130)`、橙红 `(179,79,50)→(216,41,1)`），工程里存回的确实是
`transfer-matrix-transfer` 三个节点，`app.asar` 5,678,773 字节里数不到 `gamut_matrices`——
这一版确实没有那颗按钮。


## 1.147 引擎要先认自己拿到的那份 ffmpeg，再把「不认」说成一句人话

1.146 记下的那条欠账在这一版还掉：引擎从来没验证过**它将要发的选项在不在**那份 ffmpeg 里。
`render.py` 在滤镜图越过 `GRAPH_SCRIPT_LIMIT`（12000 字符——Windows 的 `CreateProcess` 在 ~32 KB
上直接拒，所以长图必须写成脚本文件）时发 `-filter_complex_script`，而 FFmpeg 9 那一支已经没有
这个选项。默认路径现在是安全的（1.146 让打包版真正用上随包的 6.1.1），会撞上的只有操作者自己
把引擎指到别处：`--ffmpeg` 或 `AGENTCUT_FFMPEG`。那种时候最后一句话原本是不肯说出自己名字的
FFmpeg stderr，现在换成 `FFMPEG_NO_GRAPH_SCRIPT`：回执点名是哪一份（版本 + 路径），并说出
回去的那两个名字——拒绝必须给一条真的走得通的路，不许只说「不行」。

量法在 `tests/ffmpeggraph_check.py`：`parse_ffmpeg_help` 读 ffmpeg 自己的自述（两段样本各读对
版本与选项在不在），随包真身实测版本 6.1.1、认那个选项；然后**两头都跑**——把 `GRAPH_SCRIPT_LIMIT`
压到 1 让任何一条滤镜图都走脚本形式，再让能力表说这份 ffmpeg 不认，交付必须失败且那句人话里
有版本、路径、`--ffmpeg`、`AGENTCUT_FFMPEG`；把表恢复成「认」，同一条请求照常出片。只断「会拒绝」
的门禁抓不出把守卫写反的错，所以这半句不是客气话：电池 D 行（认不认都拒）红就红在「照常出片」。

两处测量顺手记下来，免得下一轮再猜：

- `ffmpeg -h full` 把**版本横幅写在 stderr**、选项表写在 stdout。探测第一次只读 stdout，于是
  版本永远解析成「未知」——一句认不出是谁的拒绝等于没说。所以 `ffmpeg_support` 读两路合起来，
  也不带 `-hide_banner`（那条把横幅整个关掉）。
- 探针挂在每次交付前面就是平白 0.2 s 一次，所以按解析出的路径缓存。门禁数得到这件事：连着两次
  `ffmpeg_support` 必须一次子进程都不发（电池 F 行把缓存拆掉，红在 `calls == []`）。

电池 6 行逐条红在自己那条断言上：只读 stdout（版本未知）、选项在不在判反、守卫整个删掉（拒绝没
发生，红的是任务状态）、守卫写反（红在照常出片那半句）、拒绝的话里不再说回去的名字、缓存没了。
还有一条没写进断言的性质也记着：探测的是「这份 ffmpeg 认不认**我们要发的那一个**选项」，不是
通用能力表——将来再依赖别的 FFmpeg 选项时，加的是同一条路上的第二次数，不是猜。


## 1.148（进行中）基色数据的出处锚，以及一处对着权威表念出来的错标签

上一版给表留的那句话是「rec2020、rec601 没有外部锚，只有自洽性质护着」。这一版把那句话划掉：
`tests/gamut_check.py` 现在把五个档的**原色与白点**逐个对着出处念一遍——Rec.709/sRGB
`0.640,0.330 · 0.300,0.600 · 0.150,0.060`、BT.601-6 525（SMPTE-C）
`0.630,0.340 · 0.310,0.595 · 0.155,0.077`、BT.2020 依 **ITU-R BT.2020-2 表 4**
`0.708,0.292 · 0.170,0.797 · 0.131,0.046`、P3 原色 `0.680,0.320 · 0.265,0.690 · 0.150,0.060`，
白点一律 D65 `0.3127,0.3290`。实测：把 BT.2020 绿的 y 从 0.797 改成 0.796，锚当场红；还原回绿——
这一类笔误以前是没有任何一层会报的。

对着出处念还顺出一处**标签说谎**，这一版把它改到它真的做的事：`PRIMARIES` 里那一档原来叫
`p3-dci`、label 写「DCI-P3 → Rec.709（影院母带到电视）」，可它存的是 **P3 原色 + D65 白 + γ2.2**
——真影院 DCI-P3 的白点是影院基准（约 `0.314,0.351`）、传递特性是 **γ2.6**，而本模块对白点不同的
两档是**故意直接拒**的（不做半套色适应）。所以那一档发的不是「影院母带到电视」，而是业界常写的
「DCI-P3 D65」那一档：改名 `p3-d65-g22`、两条 preset 换成 `p3d65g22_to_rec709` /
`rec709_to_p3d65g22`，label 把白点与曲线写在名字里；与 `display-p3` 的差别就只剩曲线那一项，
这一句也照实写进模块的说明。谎话不改成一检验就会一直回来，所以钉成断言：六档的 label 里不许出现
「影院／DCI」，而凡 `source`/`target` 走 `p3*` 档的两条，label 必须带着 `D65` 与 `γ2.2`——
把那句「影院母带」改回去，门禁当场红（电池 A 行量的就是这件事，B 行量「把白点与曲线从名字里
抹掉」同样红）。

另记一条仪器侧的账，下一轮别再从头猜：想用随包的 ffmpeg 当基色换算的第二个 oracle，
`colorspace` 的选项名是 `itrc`/`trc`（**不是** `transfer`/`itransfer`）；2020 的 `space` 值叫
`bt2020nc`、`primaries` 值叫 `bt2020`；更要紧的是 `space`/`ispace` 说的是 **YCbCr↔RGB 的矩阵**，
不是「RGB 基色」——把它写成 `bt2020nc`/`bt709` 时，filter 会拿 gbrp 的三个平面当 Y/Cb/Cr，
红进、出来的三通道相等（实测四路纯色全变灰），看着像坏了，其实是语义错。换成 `ispace=gbr` +
`space=gbr` 之后仍不是纯原色换算（本轮量到：仍出灰、且负分量被钳位）。这条路下一轮要么先把
`-h filter=colorspace` 的三段枚举读全再试，要么改用 `zscale`（这份构建里也在），别在原地换写法试。

1.148 的验证账（数字都是这一轮量出来的）：改名的电池五行逐条红在自己那条断言上（label 念回
「影院母带」、把 `D65`/`γ2.2` 从名字里抹掉、`source` 写回已经不存在的旧档名、BT.2020 绿的 y 少
0.001、数据锚自己抄错），还原回绿；`ruff check`/`ruff format` 干净，`docs_shape_check` 过；
全量套件单跑 **101/101**；`scripts/build_engine.py --verify` 与 `npm run dist` 都过，根
`AgentCut.exe` 与 `release/AgentCut-便携版.exe` 逐字节一致（189,903,262 B）。装机复核
`package_check_1148.py` 全 PASS：冻结引擎自报 **1.148.0**、`gamut_matrices` 六档的 id 就是改名后
那六条、九个系数逐字节等于源码现算，挂基色矩阵那条**长滤镜图**交付在打包版里照常出片，成片像素与
源码引擎逐项相同（灰 `(130,127,131)→(129,126,130)`、橙 `(179,79,50)→(216,41,1)`），
`app.asar` 5,679,010 字节里数不到 `gamut_matrices`（还是没有那颗按钮）。


## 1.149 量出来的路：16 位「线性岛」是无损的，1.52 那笔账是量程不是位深

1.146 留下的最大一笔账是：`transfer` 把画面抬进线性光之后那一站**仍是 8 位**，暗部一进线性
就没了码字（存储值 50 线性后约 7 个码字），基色矩阵来回一趟蓝从 50 掉到 40。1.52 当年试过
`gbrp16le` 与 `gbrpf32le`，两条都翻车，并把结论写成「插一次 planar 高位深就换了一次量程解释，
黑场被吃掉」——那一节因此没收口。这一轮把**量程钉住**再量一次，结果是相反的：

- 阶梯基线（每行一级，R=G=B=0,16,32…240）。
- **8 位平面**上跑「EOTF → OETF」同一条往返：`16 → 0`、`32 → 25`、`48 → 45`，其余各差 1；
  **最大差 16 级**。（这就是今天导出在暗部丢东西的形状。）
- **16 位平面**上跑同一条往返，两端各加一次 `scale=in_range=full:out_range=full` 把量程钉住，
  表达式按 16 位的真实域写（`val` 是 0..65535）：**十六个电平逐个相等，最大差 0**。
- 恒等的高色深链（只换平面、不做曲线）同样是**最大差 0**——也就是说 1.52 量到的「1..11 压成 0」
  不是位深的错，是**没钉量程**的错。那一句「别再猜」应当作废：路是有的，配方就在下面。

所以真正的修法量清楚了，也还没做（记在这儿免得下一轮重新试）：把含跨通道节点的那一段编成
**一座岛**——`format=gbrp16le` + `scale=in_range=full:out_range=full` 进、`scale=…` +
`format=rgba` 出，岛内的 `lutrgb` 表达式要从 0..255 域换成 0..65535 域（`out = 257·f(in/257)`，
`f` 就是现在那张表编出来的式子）。这一句原本是全部风险所在：`_expression` 交回的式子里带
`st(0,…);…` 这种链式写法，把它整条包进 `257*(…)` 到底认不认——本轮**实测掉了**：两种写法都过，
且十六级阶梯逐格原样回来（0,16,32…240 一格不差）：

- `lutrgb=r='257*(st(0,(val/257)/255);255*ld(0))'`（整条包一层）；
- `lutrgb=r='st(0,(val/257)/255);257*255*ld(0)'`（不包，把输出那一项就地乘 257）。

也就是说 FFmpeg 认括号里的 `;` 链式写法，配方落到 `grade_filter` 是一处机械改动：含 `matrix`
或 `lut3d` 的链走岛，岛内每个 `lut` 段把 `val` 就地换成 `(val/257)` 并把输出乘回 257。**但还差
两件必须一起量的事**，量不到就不要动：① 带透明通道的母版走的是 `rgba`，`format=gbrp16le`
会把 alpha 丢掉——岛要用 `gbrap16le` 并给 `lutrgb` 的 `a=` 同一套换算，否则 1.136 那条
ProRes 4444 的 matte 会被悄悄改成不透明；② 岛屿两端的 `format=`/`scale=` 与既有的
`format=rgba` 前后串（遮罩的 `geq`、`blend` 的 `gbrp` 相合、垫边与 setsar）会互相夹住，
所有既有调色门禁（`gradelevels`、`curvefidelity`、`colormanage`、`blend`、`alphamaster`…）
都要在新形状下重测一遍。没先量这两件就把配方落进 `grade_filter`，等于拿那十道门禁当试错板——
那正是本项目不让做的事，所以本轮把风险量光、把改动留到下一轮整段做完。**下一轮就是同一天：改动已经落地。**

落地后的实测（同一支 `gamut_check`、同一条 2020→709 的 trio、同一台机器）：中灰由
`(130,127,131)→(129,126,130)` 变成**逐位相同** `(130,127,131)→(130,127,131)`；同形状对照链自己
漂由 6 级降到 **3 级**，矩阵那一份由 4 级降到 **0 级**。`matrix_check` 在新形状下仍然
「三块板 × 256 电平 × 3 通道逐格对上参考乘法」，而 `blend_check`、`colormanage_check`、
`curvefidelity_check`、`gradelevels_check`、`alphamaster_check`（透明母版那条——alpha 由
`gbrap16le` 带着走，实测没被改出不透明）与 `composite_check` 一字未改全部跑绿。
形状上的两条新规矩由 `matrix_check` 钉住：含矩阵的链必须以岛开头结尾（`ISLAND_IN` /
`ISLAND_OUT`），而**纯曲线链不许进岛**（它本来就能塌成一张表，中间没有会被量化吃掉的线性站）。
岛内每个单通道表按 `out = 257·f(in/257)` 搬到 16 位域，没动的通道整个不写——`lutrgb` 的默认
就是 `val`，在 0..65535 那一站那是同一个数。含 3D LUT 的链没有量过，所以**明确排除在岛外**，
不猜。

两处靶的账，记下来免得下一轮再选错仪器：**量程这一件事只有逐电平的尺抓得到，而且进岛那一头
本来就不压量程**。电池第一次跑「进岛不钉量程」那一行时用 `gamut_check` 当靶，结果空绿——那支
门禁只读两颗颜色（橙 `(179,79,50)`、灰 `(130,127,131)`），量程压不压都看不出来；换成
`matrix_check`（3 块板 × 256 电平 × 3 通道逐格对参考乘法）再量一次，**还是空绿**。也就是说
`format=rgba → format=gbrap16le` 这一向在 FFmpeg 6.1 上不重新解释量程，1.52 当年「1..11 压成 0」
那笔不是进岛这一头的事。进岛那一次 `scale=in_range=full:out_range=full` 因此是**已测量为不需要**
的一环，留着只是把两端的形状写对称、省得下一轮再猜，但它没有背着任何证据。
**出岛那一头本轮没有量**：256 电平逐格相等这一条是**带着**那一次 `scale=` 量出来的，
所以它到底 load-bearing 与否，要由「把 ISLAND_OUT 换成 `format=rgba`」这一行变异说了算——
那一行本轮没跑完，别在这里替它背书。

**那一行随后就跑完了，而且是三方对账，结论比「需不需要」更进一步：**

| 形状 | `matrix_check`（3 板 × 256 电平 × 3 通道） | `gamut_check` | `alphamaster_check` |
| --- | --- | --- | --- |
| 两端都钉（落地的形状） | 绿 | 绿 | 绿 |
| 两端都不钉 | 绿 | 绿 | 绿 |
| **只钉进岛那一头** | 绿 | **红** | 绿 |

也就是说量程这件事是**成对**的：只改一头的假设，FFmpeg 就在另一端按标签重新解释量程，暗部
被吃掉——1.52 那节量到的「`format=rgb24 → format=gbrp16le → format=rgba` 把 1..11 压成 0」
就是这个形状，不是「高位深本身没用」。两端都不钉在这三把尺下也过，但那等于把正确性交给
**源文件带不带 tv 量程标签**这件事——真实 h264 素材带，所以不交给运气，两端都钉。
这条规矩由 `matrix_check` 钉成形状断言（`ISLAND_IN` 必须以那段 `scale=` 结尾、
`ISLAND_OUT` 必须以它开头），不再靠像素碰运气。变异「把 `ISLAND_OUT` 换成裸 `format=rgba`」
实测红在这条形状断言上、还原绿。

**全量套件在新编译路径下单跑：101/101 通过**（`tests/suite_check.py`，跑的时候机器上别的东西
都没动；岛改动之后重跑，一次红都没有——含矩阵的链进了岛，其余链形状一字未改，这件事由
`blend`／`composite`／`curvefidelity`／`gradelevels`／`alphamaster` 这些老门禁原样绿着替它作证）。
**还没做的两件收尾也写在这儿，不含糊**：`build_engine.py --verify` + `npm run dist` + 根
`AgentCut.exe` 的 `cmp` + 冻结引擎装机复核（要加的新判据：挂基色矩阵那条交付在打包版里读回的
中灰必须逐位相同、ProRes 4444 的 matte 逐帧与进岛前相同），以及版本号升 1.149.0——
所以在下一次重建与复核之前，**随包的那份引擎还是没有岛的 1.148**，这句不是谦虚，是事实。

形状上另有两行电池（A 拆岛、E 纯曲线链不许进岛）红在 `matrix_check`，B 行（域换算少搬一次
`val`）红在 `gamut_check`——B 第一次也是空绿，因为那段链里根本没有单通道表，
`_to_16bit_domain` 不会被叫到；靶选错等于没测。

测量脚本与原始读数在仓库外那份证据目录：`QoderBackups/agentcut-logs/highp_probe_1149.py`
（阶梯用 `nullsrc`+`geq` 造，`geq` 没有 `s` 选项，尺寸由前面的源定；行坐标 `Y` 就是阶梯索引）。

1.147 的验证账：`error_vocabulary_check` 把这条新码抓了出来——引擎发出去的每一个码都必须有
一句中文回执，150 个码 / 154 句提示，0 句落回英文；`desktop/src/engine.ts` 的提示表因此多了
`FFMPEG_NO_GRAPH_SCRIPT` 那一行（说的是同一条退路，不是「出错了」）。52 个壳检全过；
全量套件单跑 **101/101**。发布包重建后根 `AgentCut.exe` 与 `release/AgentCut-便携版.exe` 逐字节
一致（189,903,532 B），冻结引擎自报 1.147.0，`package_check_1147.py` 全 PASS。
最要紧的一跑是 `package_check_1147_refusal.py`：把**打包版**引擎用 `--ffmpeg` 指到这台机器 PATH
上那一份 9.0.2（就是 1.146 当年撞上的那一份），挂基色矩阵那条长滤镜图的交付必须以命名拒绝
收场——实测 PASS：ready 行报的就是被指过去的那一份、回执里点名 9.0.2 与路径、说出 `--ffmpeg`
与 `AGENTCUT_FFMPEG` 这两个名字，而 `Unrecognized option` 那句原始 stderr 不再独自当结论。

## 1.150 先修「话说过头」，再把一键色彩管理的输入侧交给素材自己

这一轮的两半都是**对账**，不是新旋钮。

**第一半：文档在说谎。** README 的「边界」写着「三种带画面的容器」「仍没有 MXF/DPX 一类的
后期格式」，而 MXF 是 1.129 交的、OpenEXR/DPX 序列是 1.142 交的，两条都在同一份 README 的
「已完成」表里；同一节写「已支持六属性关键帧」，而遮罩盒那四条（`MaskProperty`）与柔焦/清晰
那三条（`SpatialProperty`）早就在契约里；「工作台升级」写 schema v11，而
`contracts.SCHEMA_VERSION` 是 16；验证那节写 68 项 Python 检查与 6 个 TS 检查，实为
`suite_check.py` 跑的 101 项与 `desktop_ts_check.py` 自己数的 52 项。`docs/optimization.md`
上面那张清单同样落后（把 1.130 的一键色彩管理、1.134–1.135 的可改键位、1.131–1.133 的两万段
首帧还账都仍列为「未做」）。这些不是排版问题：README 的「已完成」表被 AGENTS.md 指为
「当前事实来源」，一句过时的「还没做」会把一个已经能用的能力从用户的视野里抹掉，一句过时的
「只有三种容器」则是对交付面的夸大。
新门禁 `tests/docs_facts_check.py` 不校对文案，只把句子钉回来源：`OUTPUT_CONTAINERS` 那九个
容器逐个必须在预设那一行里念到；README 引用的 schema 数必须等于 `contracts.SCHEMA_VERSION`；
`EffectProperty`／`MaskProperty`／`SpatialProperty`／`BlendMode` 四类在某句话里报出的条数
（中文数词或阿拉伯数字都认）必须等于那条 Literal 的成员数；七条过时说法按原文禁掉。
五条突变逐条红在自己那条断言上——包括**反方向**那一条（把 contracts 改成 17 而 README 不动，
红），而且这条本轮真的红过一次：schema 涨到 17 时它立刻点名了刚写下去的那句「量到的值是 16」。

**第二半：让素材替人回答「我是按哪条曲线写的」。** 达芬奇与 Premiere 的彩色管理流程之所以
能一键，是因为输入侧由文件自带的标记决定；`clip.color_manage`（1.130）此前只把「两端各选一次」
合并成一次点击，来源端仍要人知道这份素材是什么。现在 `auto_source: true` 让引擎自己去读
`color_transfer`。三条只有量出来才说得对的事：

- **四个标记里有三个不能当答案。** `color_space` 是 Y/R'G'B' 的矩阵系数、`color_primaries`
  是基色坐标，两者都不决定 gamma，所以只标了这两样的文件回 `no_transfer_tag` 而不是被猜成
  Rec.709；SD 带子那种 `smpte170m` 在七条曲线里没有对应，回 `unmatched_transfer_tag`。
  翻译表 `COLOR_TRANSFER_TAGS` 只收实测过的行，`gamma18`／`gamma20`／`gamma24` 至今没有
  对应的标记，所以那三条仍要手工选——这不是偷懒，是「不拿看着像的近似当已交付」。
- **写进去的名字与读回来的名字不是同一个。** 用随包 FFmpeg 造素材写 `-color_trc gamma22`，
  ffprobe 读回的是 `bt470m`（同一个存储枚举的两个拼法）；而 `-color_trc unknown` 根本不写
  `color_transfer` 这个键。表里因此钉的是读回的那一拼，`probe_suite` 把这两件事各自钉成一条
  断言；把 `bt470m` 那行删掉，`detect_suite` 立刻红。
- **`auto_source` 不是第二条实现。** 量的是产物而不是意图：`tests/colortags_check.py` 先证
  auto 与手工 `source_space: "rec709"` 写下**同一对节点**，再证两份工程编译出的导出命令串
  逐字节相同，最后在同一次真实导出里取 0.4 s 与 1.4 s 两帧——两帧 RGB 完全相同（132,68,28），
  且都不同于未套色彩管理的源色（128,64,32）。reducer 里 `if command.auto_source` 整条删掉，
  那条红。

回执那一头差点放过一条**不能红的检查**：第一版拿新代码自己两侧对算，默认值填没填都过，
把 `_fingerprint` 的剥离规则整条删掉后 `receipt_suite` 仍然 exit=0。改成钉 1.149 那棵提交树
自己算出的 `3abfc7a3…`（那份模型的 dump 里没有 `auto_source` 这个键）之后才真的会红：删规则
算出 `02556ccb…` 红，还原后绿，`projects.py` 逐字节还原。这就是「断言要落在产物上」的具体
形状——一个只会重复自己意图的门禁，比没有门禁更危险。

验证账：`ruff check`/`format --check` 对 `src tests` 全绿；`colortags_check.py` 与
`docs_facts_check.py` 各成一节门禁（`suite_check.py --list` 当时量到总数 103 项，这两条分别排在
第 17 与第 27 位）；受影响面单跑 `colormanage_check.py`、`editing_check.py`、`grade_check.py`、
`error_vocabulary_check.py`（151 个码 / 155 句中文 / 0 句落回英文，`COLOR_SPACE_UNDETECTED` 那句点名「手工选来源空间」与「+LUT」两条真出路）、
`read_sweep_check.py`、`ops_sweep_check.py` 全绿。引擎自报 1.150.0、工程 schema v17。

**发布包这一头是单独量的，而且中间有一次我自己造的假红**：第一次全量跑我把 PyInstaller 的构建
压在套件尾巴上一起跑，最后三项（`tracking_check`／`verify_check`／`wipe_check`）同时红——
`wipe_check` 的红是它调 FFmpeg 的那一步（构建正把 `resources/bin/ffmpeg.exe` 换掉）。这条不算
交付证据，等机器空下来单独复跑，**103/103 全绿、EXIT=0**。发布包重建后：便携版
189,910,236 B、安装版 190,070,940 B，根目录 `AgentCut.exe` 与便携版 `cmp` 逐字节相同，
`released_package_check.py` 绿（app.asar 带 1.150.0、84 个文件、内嵌引擎就是刚构建那一份）。
所以又把「打包版引擎真的把这条新面答出来」固化成套件的一项（`--list` 现在量到 104 项，它排在
第 73 位）：它启动 `resources/bin/agentcut/agentcut.exe`，用随包
FFmpeg 造一份带 bt709 与一份不带标记的素材，量到 capabilities 报 1.150.0／schema 17／
`color_manage_auto` 为真、只读路由 `bt709 → rec709` 与 `no_color_tags`、`auto_source` 写下
`rec709→linear→rec709`、对没标记那份的写请求回 422 `COLOR_SPACE_UNDETECTED` 且 revision 不动。

## 1.151 交付的那一头可以声明色彩：先把「标签与画面必须一致」量死

上一轮停在「`-colorspace bt709` 只写容器、一个像素都不动」这一个数上。这一轮把那条式子真的接进
交付，接法只有一种是老实的：**同时改两处**——滤镜图最后一步换成
先按预设自己的位深摆成平面 RGB（`format=gbrp`／`gbrp10le`）再 `zscale=matrix=709:range=tv,format=<预设像素格式>,settb=AVTB`，容器写
`-color_primaries`／`-color_trc`／`-colorspace`。字段是 `RenderRequest`／`RenderBatchItem`／
`RenderJob` 上的 `colour_tag`（默认 `null`＝照旧一个标记都不写，argv 逐字节是 1.150 那一份），
MCP 的 `render_plan` 与 `GET …/render-plan` 各多一个同名入参。

### 量到的四个数（`tests/colour_tag_check.py`，`pixels_suite`）

素材那一格在 PNG 里**实拿 RGB (126,63,30)**——不是名义上的 (128,64,32)：`lavfi color=` 落到
PNG 之前已经过了一次折算，所以两个参考预测都必须用**量到的**那格去算，否则门禁会比着一张假想
的素材验证。同一份素材交两次 h264：

| 交付 | 量到的 YUV | BT.601 预测 | BT.709 预测 | 容器回读 |
|---|---|---|---|---|
| 不带标记 | (83,104,158) | (83,104,158) | (80,107,157) | 四键全缺 |
| 带 `bt709` | (80,107,157) | (83,104,158) | (80,107,157) | `color_space`／`primaries`／`transfer` 均 `bt709`，`color_range=tv` |

两份预测都由本文件按公开系数（601：0.299/0.587/0.114；709：0.2126/0.7152/0.0722）独立算出，
不从引擎 import——否则「引擎里那组系数写错了」这一类缺陷永远红不了。带标记那份再走一遍 1.150 的
`detect_space`，读回 `rec709`：引擎认得出自己导出的母版，这一条才是「下游调色间不必猜」的意思。

### 两条 FFmpeg 事实是拿突变撞出来的，不是查表查到的

1. `zscale` 的矩阵表里**没有 `601` 这一拼**。第一次想把「折叠没生效」钉成断言，突变写成
   `zscale=matrix=601:range=tv`，FFmpeg 直接 `Error while filtering: Generic error in an external
   library` 崩在半路——红是红了，却红在渲染而不是红在那条断言上，等于什么都没证明。换成表里真有
   的 `470bg`（601 族在 `zscale` 里的名字是 `470bg`／`bt470bg`／`170m`，`-h filter=zscale` 数出来
   的）才量到「折的是 601、说的是 709」这一对。
2. `range` 不钉 `tv`，有限量程的样本会被交成 `yuvj420p`＋`color_range=pc`：容器上写的三样标记与
   量程就各自说话。所以 `zscale=matrix=…:range=…` 之后必须接一个独立的 `format=`（`zscale` 没有
   `format` 选项，这是上一轮就撞过的），再 `settb=AVTB` 把时间基交回去。

### 三条拒绝各点名一种「带不出去」

`COLOUR_TAG_NEEDS_CONTAINER`（EXR／DPX 是一串文件，没有容器 VUI 可挂）、`COLOUR_TAG_NEEDS_PICTURE`
（MP3／WAV／FLAC 根本没有画面，标记是给画面写的）、`COLOUR_TAG_NOT_WITH_ALPHA`（透明母版把 rgba
一路交给编码器才折，用哪组系数折不由这条图决定——在文件上写 matrix 就是一句与画面无关的话），
外加 `UNKNOWN_COLOUR_TAG` 会回 `known` 列出表里真有什么。每条中文都在 `desktop/src/engine.ts`，
`error_vocabulary_check.py` 这一轮量到 **155 个码 / 159 句中文 / 0 句落回英文**。反方向也钉住：
同一个 alpha 预设**不勾透明**时那份 `format=rgba[vout]` 链逐字未改，`refusals_suite` 两种都断。

### 一次「这条面没人看过」的现行犯

`GET /v1/jobs/{id}` 给排队中／运行中的任务回一份它自己的计划，那份计划是 `plan_for(...)` 现场重
编的——1.51 起就带着 `transparent`／`timecode`，但 `colour_tag` 接上去之后**没有任何断言读过它**：
把 `colour_tag=job.colour_tag` 突变成 `None`，全套检查照绿。这一轮补了两条（`shown["plan"]
["colour_tag"] == "bt709"` 与 `plan.colour_tag` 在 dry-run 摘要里），并且把这条面固定成确定性断言：
`JobRuntime` 只有一个 worker 线程，所以第二次交付在第一次还在编码时必然仍是 queued，读得到。
标记也进了 `RenderPlan.as_dict()`（与 `transparent`／`timecode` 同一位置的理由：读 dry-run 的人不必
从自己发过的字段反推）。

### 幂等回执：抽成一处，钉的是上一版自己算出的数

`jobs.py` 里那段内联的 `canonical = json.dumps([...])` 抽成模块级 `request_fingerprint(project_id,
request)`，行为一字未变。规则照 1.136／1.138／1.142 的老样子：**只有被点名的字段才进哈希**，所以
1.150 之前写的未标记回执逐字重放；同 `request_id` 改要带标记是 409 `IDEMPOTENCY_CONFLICT`，不会
悄悄回一份旧文件。钉住它的那串不是本轮能重算的：把 HEAD 的 `jobs.py` 用 `ast` 解析，从
`_submit_locked` 里取出那条 `canonical` 赋值语句，用**上一版的** `RenderRequest` 求值，得到
`["proj_pin_1","h264-720p-web","show.mp4",null,"contain"]` 与其摘要
`39931bfe33e7b53745dd5d50caa79cb82065636e61bd8a6fdddc4de611a5c4cb`，两条都写进检查里。
第一次跑这条检查还顺手抓到一个假象：把 `JobRuntime` 指到第二个 SQLite 文件时 worker 报
`no such table: history`——真实部署里工程与任务队列本来就是同一个库，**fixture 指错库只会
造出一个并不存在的缺陷**。

### 界面这一头（`tests/desktop_colour_tag_check.ts`，第 54 项壳层检查）

导出面板多一栏「交付色彩标记」，候选整档从 `capabilities.output_colour_tags` 来：界面只读 `id`
与 `label`，`primaries`／`transfer`／`matrix`／`zscale_*` 在客户端类型里是 `unknown`——读它们不
编译得过。带不出去时那行念的是具体那一个原因，并给一条真走得通的出路（换一条 mov／mp4／mxf／webm
带画面的交付、或把「背景透明」去掉），而引擎没有这一档时界面明说「capabilities 里没有
output_colour_tags 这一档」，**导出照常走**：门禁两个方向都判（只知拒绝的门禁本项目交付过一次）。
`colourTagAllowed(preset, audioOnly, isSequence, matte, requested)` 是唯一一处算「这一次真正带得
出去的是哪个值」的地方，控件的 `value`、那行 mono、待发清单两条目、两颗按钮的 title 都读它——
1.150 那轮「两处各算一份」的 bug 不犯第二遍。检查扫整棵 `desktop/src`：四个标记值出现的清单必须
等于一张空表（`rec709` 例外，它是 1.150 就在用的色彩空间 id，不是交付标记）。

### 突变账（每条都要红在自己那条断言的消息上）

| 突变 | 该红在哪 | 结果 |
|---|---|---|
| 容器不写 `-colorspace` | `compile_suite` 的那对 argv | RED |
| 序列那道门禁关掉（`if preset["sequence"]`→`if False`） | `refusal_suite`「accepted a colour tag it cannot carry」 | RED |
| 透明母版那道门禁关掉 | `refusal_suite`「accepted a colour claim it cannot back」 | RED |
| 回执里 `colour_tag` 恒加入 | 「an untagged request no longer replays as the receipt 1.150 wrote」 | RED |
| 回执里删掉 `colour_tag` | 「a tagged master hashed as the untagged one」 | RED |
| render-plan 查询参数不再下传 | `http_suite` 那句 `"zscale=matrix=709"` | RED |
| 摘要不写标记（`row_id_of(tag_row)`→`None`） | `compile_suite` 的 `tagged.summary["colour_tag"]` | RED |
| `as_dict()` 不回标记 | `http_suite` 的 `shown["plan"]["colour_tag"]` | RED |
| `GET /v1/jobs/{id}` 那份计划丢标记 | 同上 | RED |
| 折成 `470bg` 却声明 `bt709` | `pixels_suite` 的 `close(after, want709)` | RED |
| 折成 709 却声明 `bt470bg` | `pixels_suite` 的 `tagged_tags["color_space"] == "bt709"` | RED |

前九条各有一次「写成非法命令」的失败版本（`matrix=601`）红在了别处，见上面那条 FFmpeg 事实；
表里这两条是重做过的合法突变，双向都红：折叠与标记**任一**单独跑偏都会被 `pixels_suite` 抓住。
界面那三条（序列漏判、待发清单不存标记、硬编码 `<option value="bt709">`）也各红在自己那条中文上。

### 界面真点下去，抓到一个全绿门禁抓不到的缺陷

这一节写到这里，`tests/colour_tag_check.py` 七项已经全绿、壳层 54 项全绿、发布包也对了字节。
然后把打包版渲染层起在浏览器里、连上 `resources/bin/agentcut/agentcut.exe`（标题栏念
「引擎在线 v1.151.0」），从时间线上放着一段 **mp4** 的工程点下「开始导出」——任务直接失败：

```
[Parsed_zscale_5] code 3074: no path between colorspaces
Error while filtering: Generic error in an external library
```

原因是这一版所有检查用的素材都是 **PNG**（解码就是 RGB），`zscale` 接得到 RGB 才谈得上「用哪组
系数折」；真实素材解码出来是 YUV，`zscale` 不知道从哪一个空间走到哪一个空间，直接拒绝整条滤镜图。
也就是说：**这一版的主用例——把真实 footage 交成带标记的母版——在界面上根本走不通，而七项检查
一项都没红**。这条缺陷不是断言写松了，是**输入面窄了**：fixture 全走了一条不会坏的路。

修法是在 `zscale` 之前按预设自己的位深把画面摆成平面 RGB（`format=gbrp`／`gbrp10le`，10 位
预设不能降到 8 位），折完再回预设的 YUV 格式。量回来的往返是：素材解码 RGB
(126,63,30) → 带标记母版再解回 **(125,62,29)**，漂移 1 个色阶（8 位取整），容器三样标记
`color_space`／`color_primaries`／`color_transfer` 全部读回 `bt709`、`color_range=tv`；不带标记
那份照旧四键全缺。往返之所以不损观感，是 YUV→RGB 与 RGB→YUV 这两趟系数互逆：
下游按 709 读这份母版，得到的正是源素材按 601 该被读出的那组 RGB。

新增第八项 `video_suite`，走的就是界面那条路（mp4 素材 → 真跑 FFmpeg → 探针读标记 → 解回 RGB
比往返），并把这条面钉成**必须跑一次真编码**的断言，而不是读滤镜串。突变验证：把 `format=` 那一
段从 `fit_post` 里摘掉，`video_suite` 立刻红在 FFmpeg 那句 `no path between colorspaces` 上——
这条检查从此拦得住这个缺陷。同一次真点还确认了三门门禁在界面上的样子：MP3／OpenEXR／
「VP9 透明＋背景透明」三种情况下「交付色彩标记」都是 disabled 且后缀念「不写」，720p 那条是
enabled；选中后导出按钮的 title 念「按 r1 导出 ui1151.mp4，色彩标记 bt709」，发出去的就是那一个值。

**口径改一条**：往后凡新增「交付面」的开关，验收里必须有一段是从**真实素材**（解码后是 YUV 的
视频）跑一次真 FFmpeg，而不是一张 PNG 或一段 argv；`tests/colour_tag_check.py` 的这条注释就是
给下一次看的。

### 仍然开着的

- 表里今天只有一档（BT.709）。第二档（P3-DCI／Rec.2020 之类）要先量 `zscale` 那侧真认的矩阵名，
  再接 `COLOR_SPACES` 里对应的曲线；加一档是改 `OUTPUT_COLOUR_TAGS` 这一处契约表，界面与文档
  跟着数走（`docs_facts_check.py` 现在会数 README 那一行的「N 档」）。
- 透明母版仍不带标记（这是有意的拒绝，不是漏了）。要交带标记的透明母版，得先把那一折从编码器
  手里接回滤镜图。
- MXF 那一侧写进去的标记是否被容器原样读回，本轮只在 mp4 上量过；`refusals_suite` 只保证不会
  交出一张假标签。

### 1.151 的账（全部是量到的，不是推的）

- 引擎 `tests/colour_tag_check.py` 八项（capabilities／compile／pixels／round trip／refusals／
  **video**／http／receipts）单独跑 **7 秒**全绿：小画幅（64×36 源、一秒）加随包 FFmpeg，
  十次真编码就是这么快——速度不是跳过的证据，因为每一行 PASS 里带的都是量回来的数
  （(126,63,30)→(83,104,158)/(80,107,157)、往返漂移 (1,1,1)、回执那串 64 位十六进制）。
- 壳层 `tests/desktop_ts_check.py`：**54 项 shell checks 在 node 下跑过**，`npx tsc --noEmit` 干净。
- 全量套件**空闲机器单独跑：105/105 checks passed，EXIT=0**（18:55→19:12，约 17 分钟）。
  中间没有把构建压在套件上，所以这一份才是可引用的那一份。
- 突变账共 12 条，每条都必须红在自己那条断言的消息上：引擎侧 10 条（容器 trio 不写、序列门禁关、
  透明门禁关、回执恒加入、回执删字段、查询参数不下传、摘要不写标记、`as_dict()` 不回标记、
  `GET /v1/jobs/{id}` 那份计划丢标记、折成 470bg 却声明 bt709 / 折成 709 却声明 bt470bg），
  壳层 2 条（方案 chip 不再复述标记、帮助那一节把七个开关说漏）。
  其中两条**第一次没红在本该红的地方**：一条把 `zscale=matrix=601` 写成了非法值（红在 FFmpeg 而不是
  红在断言，等于没证明），一条 `GET /v1/jobs/{id}` 的那份计划当时根本没有断言看过它——
  两次 MISS 分别是这一轮新增 `video_suite` 与 `plan.colour_tag` 断言的理由。
- 引擎构建 `scripts/build_engine.py --verify`：verification passed，裸冷启动 662 ms。
- Windows 发布包：便携版 **189,915,745 B**、安装版 **190,076,444 B**，根目录 `AgentCut.exe` 与便携版
  `cmp` 逐字节相同，`released_package_check.py` 绿（`app.asar` 带 1.151.0、84 个文件、内嵌引擎就是
  刚构建那一份、渲染层 27 句读得通的中文）；`packed_engine_surface_check.py` 用**打包版引擎**真跑
  HTTP：capabilities 报 1.151.0／schema 17／`colour_tag_delivery` 为真／`output_colour_tags` 等于契约
  那张表，render-plan 不带标记时 argv 里一个声明都没有、带标记时三样标记与 `zscale=matrix=709:range=tv`
  同时出现、`p3-dci` 回 422 `UNKNOWN_COLOUR_TAG` 并列出 `known`。
- 界面真点（服务 `desktop/dist/renderer` + 打包引擎，标题栏「引擎在线 v1.151.0」）：
  「交付色彩标记」下拉念的是引擎下发的两行（不带标记＋那一档），MP3／OpenEXR／
  「VP9 透明＋背景透明」三种场合控件 disabled 且后缀「不写」，720p 那条 enabled；
  存方案后那颗 chip 的 title 是「按 r2 出货：ui1151.mp4 · contain/full 色彩标记 bt709」；
  点「开始导出」交付真实 mp4：任务 `succeeded`、`colour_tag=bt709` 存进任务记录、
  `output_checked=True`，产物探针 `1280×720 yuv420p`＋`color_space/primaries/transfer=bt709`＋
  `color_range=tv`。帮助那一节的那句话在 `index-*.js` 里也量到了（打进包里了，不只是源码里）。
- `error_vocabulary_check.py`：155 个码 / 159 句中文 / 0 句落回英文；`docs_facts_check.py`：
  九个容器点名、schema 17、四类属性与混合模式条数、以及这一轮新加的「README 那一行的 N 档
  必须等于 `COLOUR_TAG_CODES` 的长度」（把 README 那行改成两档，它当场红）。

## 1.152 的账：验收先要能在交付后的树里跑起来，加一档色彩标记要能红

### 三处「门禁全绿但话已经不对」

1. **套件在交付后的那棵树里跑不起来**。按 1.151 的停放点重跑基线，第 13 项 `bundle_check` 当场
   `FileNotFoundError: [WinError 2] 系统找不到指定的文件`。数出来的根因是三类写死：61 个 Python
   检查把这台机器的主目录钉在 `ROOT = Path(r"C:\\Users\\…")`，10 个壳层检查把同一个目录钉在
   `const SRC`，另有 14 处直接指 `desktop/node_modules` 里 npm 装来的 FFmpeg。上一轮按「只留软件与
   功能本身」清掉了 `node_modules` 与 `.venv`，于是 1.151 记的那句「105/105 单独跑全绿」在这棵交付
   树里**已经不可能重跑**——工程挪个位置也是同样的全红。
2. **兜底那条更坏**：`media_check` 与 `self_check` 找 FFmpeg 的顺序是 npm→随包→`shutil.which`。
   npm 那一份被删掉之后，它们会静默改用 PATH 上的 FFmpeg 9，而装机版内嵌的是随包那支 6.1.1；
   「验收测的就是发布包的行为」这句话从此没有依据（本机 PATH 上那支连 `-filter_complex_script`
   都没有，1.146 就是被这一条咬过）。
3. **界面那句拒绝在数档数**：`desktop/src/engine.ts` 的 `UNKNOWN_COLOUR_TAG` 那句写着「目前只有
   BT.709 一档」。表一涨它就是假话，所以改成「档数以那张表为准，引擎那句拒绝还会点名它认识的全部
   档位」——由引擎的话去说，不由界面复述。

### 改法：一处来源，一条门禁

- Python 检查一律 `ROOT = Path(__file__).resolve().parent.parent`；壳层检查的根目录由它自己的
  runner `tests/desktop_ts_check.py` 以 esbuild `--define:REPO_ROOT=…` 注入（`declare const
  REPO_ROOT: string;` 由 runner 认识、`tsc --noEmit` 也过）。
- 媒体验收只准用 `desktop/resources/bin` 那两支——装机版内嵌的就是它们；npm 与 PATH 两条兜底整个
  删掉，缺了就当场红，而不是换一支 FFmpeg 继续绿。
- 新门禁 `tests/mediabinary_check.py`：扫 **242 个**可执行源码（tests/scripts/src/desktop）不许出现
  任何用户主目录形状的绝对路径；对 **107 个**验收文件按语法树判两件事——不许调用 `which(…)` 取媒体
  程序、字符串常量里不许出现 npm 那两份；任何写出来的 `desktop/…ffmpeg.exe|ffprobe.exe` 路径必须落在
  随包那一层。它还真跑那两支把版本首行念出来（`ffmpeg 6.1.1-essentials_build`、`ffprobe 4.0.2`）。
  按 AST 判而不是按文字判是必要的：`tests/ffmpegpath_check.py` 要在临时目录里搭打包形状、把诱饵摆上
  PATH 才证得动引擎自己的搜索顺序，那是产品行为的证据，文字匹配会把它当违规。
- 六条突变各自红在自己那句上：本机路径／npm 那一份／`which` 兜底／随包之外的又一份／随包 ffmpeg 改名
  后存在性那条／把门禁拷到一棵几乎没有源码的树里让扫描面宽度那条红。恢复后门禁立刻回绿。
  其中第一条第一次没红对地方：needle 写的是我以为的消息，而 `docs_facts_check` 实际说的是
  「does not say 1 档」——它当场红了，但我差点把「红在别处」记成「拦不住」。

### 第二档交付色彩标记：先量 zscale 认什么，再写表

1.151 那句「加一档是改 `OUTPUT_COLOUR_TAGS` 一处」是对的，但前提是那一档说得出口。随包 6.1.1 的
`-h filter=zscale` 量回来的枚举名：

- `matrix`：`709` `470bg` `170m` `2020_ncl` `2020_cl`（长拼法 `bt709` `bt470bg` `smpte170m`
  `smpte240m` `bt2020nc` `bt2020c` 同表）；**没有** `601` 这一拼。
- `primaries`：`709` `170m` `2020` `bt470bg` `smpte428` `smpte431` `smpte432` 等。
- 输入侧的拼法是 `primariesin` / `matrixin` / `rangein` / `transferin`（含 `pin` `min` 等短名），
  **没有** `in_primaries`：两次 `Option not found` 都是按别处的习惯猜了这个前缀。

用 64×36 纯色格 (126,63,30) 真编码量的三条路（预测值一律由公开系数在本文件之外独立算一遍）：

| 链 | 量到的 YUV | 独立预测 | 结论 |
|---|---|---|---|
| `zscale=matrix=170m:range=tv` | (83,104,158) | BT.601-6 的 0.299/0.587/0.114 → (83,104,158) | **逐位相同**，可交 |
| `zscale=matrix=2020_ncl:range=tv` | (83,106,157) | 2020-NCL 系数 → (83,106,157) | 折叠精确，但基色仍是 709 |
| `primariesin=709:primaries=2020:matrix=2020_ncl` | (83,110,146) | 先 709→2020 换基色再折 → (90,113,169) | Cr 差 **23 阶**，不可交 |
| `primariesin=709:primaries=432`（P3-D65） | 当场 `no path between colorspaces` | — | 不可交 |

所以这一版加的第二档是 `bt601`：只换**折叠**（`-colorspace smpte170m`），基色与曲线照旧声明 `bt709`，
因为图里那份 RGB 本来就是 709 那套基色。名字要说它真的做的事——`capability_suite` 现在钉着「只要
`matrix` 与 `primaries` 不同，标签里必须出现「折叠」」，另有「任何一档的 primaries/transfer 都必须是
bt709」这条硬断言，理由就是上面那张表：换基色的那句话今天的 FFmpeg 兑不了现。宽色域那一档要做通，
得先把「线性化 → 九个数的基色矩阵 → 重新编码」这三步从 zscale 手里接回引擎自己的滤镜图。

新加的 `tiers_suite` 把「表里每一档」变成会被量的事：逐档编译（容器 trio 与折叠那一句都等于表里的值）、
逐档**真编码**（探针读 `color_space`/`color_primaries`/`color_transfer`/`color_range`）、逐档比独立系数
算出的 YUV、逐档「按自己的标记解回 RGB」（这就是一台老实的色彩管理观看者做的事），并顺手把同一张图
交一份 **MXF** 再读一次——1.151 那句「MXF 那一侧只在 mp4 上量过」现在有了数：`mxf-mpeg2` 交出
`color_space=smpte170m`＋`bt709`＋`bt709`＋`tv` 原样读回。量到的两档：bt709 折成 (80,107,157)、解回
(127,64,30)；bt601 折成 (83,104,158)、解回 (126,63,30)，与源差 (0,0,0)。表里多一档而没人给它独立的
系数出处，这条检查当场红。

六条突变（改的都是 `contracts.OUTPUT_COLOUR_TAGS` 那一行，逐条红在自己那句画上，恢复后立刻回绿）：
矩阵换成没有系数出处的 `bt470bg`、`zscale_matrix` 写成合法但不同的 `2020_ncl`、这一档改名、标签不再
说「折叠」、primaries 谎称 `bt470bg`、整档删掉之后 `docs_facts_check` 红在 README 那句「2 档」。

### 界面真点：打包渲染层连打包引擎（标题栏「引擎在线 v1.152.0」）

把 `desktop/dist/renderer` 服务起来连 `desktop/resources/bin/agentcut/agentcut.exe`，素材是一条**真
YUV mp4**（1.151 那次界面真点抓到缺陷，用的就是这种素材）。「交付色彩标记」那一栏现在念的是引擎下发
的三行：不带标记／BT.709（高清显示端交接母版）／BT.601 折叠（标清与老母版：矩阵按 601，基色与曲线仍
是工程的 709）。选到 bt601 之后导出按钮的 title 是「按 r1 导出 ui1152.mp4，色彩标记 bt601」；点下去
任务 `succeeded`、`colour_tag=bt601` 存进任务记录、`output_checked=True`，产物 320×180 `yuv420p`，
探针读 `color_space=smpte170m`＋`primaries=bt709`＋`transfer=bt709`＋`range=tv`，画面中心按这四样解回
(126,63,30)，与源同一格**差 (0,0,0)**。界面一行代码都没改就念出第二档——那张表是唯一来源，这就是它
应有的样子。

第一次的 fixture 是我自己选的 `testsrc2`（细节丰富的活动图案），量出成片中心与源差 (0,1,4)：不是引擎
的错，是**用错量具**——放大加有损编码之后拿 busy 图案做颜色断言，那 4 级是量化与滤波的账。换成纯色
素材才有上面那句 (0,0,0)。

### 全量套件

- 全量套件**空闲机器单独跑：106/106 checks passed，EXIT=0**（01:02→01:16，约 14 分钟；106 = 1.151 的 105 项加本轮新增的 `tests/mediabinary_check.py`）。这一份才是可引用的那一份：同一套检查在交付后的树里第 13 项就红过一次，红的原因是检查自己写死了本机路径与 npm 那支 FFmpeg。

### 发布包与那一条自己也会过时的门禁

- `scripts/build_engine.py --verify`：verification passed，裸冷启动 **662→654 ms**；`tools` 模式自报
  的 ffmpeg/ffprobe 就是随包那两支（与新门禁同一判断，两条互不引用）。
- Windows 发布包：便携版 **189,915,022 B**、安装版 **190,075,728 B**，根目录 `AgentCut.exe` 与便携版
  SHA256 相同（`9ec80762…5fb6202`）。`released_package_check.py` 绿：asar 带 **1.152.0**、84 个文件、
  内嵌引擎就是刚构建那一份、渲染层 27 句读得通的中文。
- `packed_engine_surface_check.py` 用打包版引擎真跑 HTTP：capabilities 报 1.152.0／schema 17，
  render-plan 逐档问——**它第一次是红的，红在自己身上**：那句 `known == ["bt709"]` 是 1.151 写死的，
  表涨到两档之后它把新档当成违规。这是 1.150「schema 涨到 17 时两处写死 16」那一类的第三次复发，
  所以现在是逐档字面量清单＋「拒绝那句与这张表相符」两条一起钉。

### 仍然开着的

- 宽色域那一档（BT.2020／P3）：按上面那三个数，先把基色转换接回图里再说。
- 交付标记与工程色彩管理的**显示端**对齐：今天两档都恒声明 709 基色，若某条链的显示端选了 rec2020，
  那张 bt709 标签就又成了假话——改这一条要同时改 `capability_suite` 那句 primaries 硬断言的口径。
- 多目标跟踪、跟踪与稳定估计旋转、`lut3d` 的浏览器预览（`features.lut3d_preview` 仍是 false）。
- 随包的 `desktop/resources/bin` 两支与 `release/` 那几个 exe 都不在版本控制里（`*.exe` 被 ignore），
  所以「交付后的树」里跑套件的前置条件是 `npm ci` + `scripts/build_engine.py`；这条要变成长治规矩，
  得把 README 与 AGENTS 的前置说明与 `mediabinary_check` 的那句提示词对齐。


## 1.153 的账：宽色域那一档交出去了，先撤掉一条被量具骗出来的拒绝

这一轮的主线不是加功能加了多少，而是**一次把「自己写的拒绝」拿去重量**，结果那条拒绝是错的。
记下全过程，因为错的不是某个数，是拿错量具去判一个判断。

### 交出去的那一档

- `OUTPUT_COLOUR_TAGS` 第三行 `bt2020`：`primaries=bt2020`、`transfer=bt709`、`matrix=bt2020nc`，
  外加 `shift_from=rec709`／`shift_to=rec2020` 两端的名字。换基色不在 `zscale` 手里做（1.152 量过：
  随包那支 `zscale=primariesin=709:primaries=2020` 交出 (83,110,146)，标准算式预测 (90,113,169)，
  Cr 差 23 阶），而是回到图里：`gamut.delivery_cube` 算一张立方体，`render.primaries_shift_stage`
  把它作为内容寻址的旁路文件 `primaries-<sha16>.cube` 写进作业目录，一站
  `lut3d=file=…:interp=tetrahedral`，折叠再交给 `zscale=matrix=2020_ncl:range=tv`。
- 量回来的三个数（64×36 夹具里那一格 (126,63,30)，随包 FFmpeg 6.1.1）：折出 (81,109,146)，独立算式
  （ITU-R BT.2020 公布的 rec709→rec2020 九个数 + 0.2627/0.6780/0.0593）预测 (82,109,145)，差 (1,0,1)；
  mp4 与 MXF 都读回 `bt2020/bt709/bt2020nc/tv`；按这四样标记解回来 (126,62,28)，与源差 (0,1,2)。

### 那条被撤掉的拒绝，以及它错在哪

- 1.153 上半年，`contracts.colour_tag_presets()` 里给 `bt2020` 加了一条像素格式门槛：只准「10 位 4:4:4」
  的预设挂这一档，别的预设挂了当场 `COLOUR_TAG_NEEDS_WIDE_RASTER`，句子写着「8 位 4:2:0 按四样标记
  解回来实测与源差到 20 个色阶，同一条链在 10 位 4:4:4 上是 6 阶以内」。
- 两个数都来自真实测量，但**量具判的不是那句话**：
  1. 那个「20 阶」是界面那一次真点量到的纯色偏差——而它当时是 **BT.709 编码侧 0.45 与解码侧 1/0.45
     被对调**的签名。把这两个指数重新对调一次（今天已经改对了），纯色立刻又差 20 阶：`flat_suite`
     的变异记录里就是这么写的。所以那 20 阶是引擎的曲线 bug，不是 8 位交付的固有账。
  2. 那个「134 阶」（渐变逐列比在 8 位 4:2:0 上量到的）连**不带任何转换**那一档也量到 126 阶：那条
     渐变每两个像素换一次色度，4:2:0（乃至有损编码器在奈奎斯特上的账）本来就带不动它。用一把自己
     都过不去的尺去拒一档交付，判的是抽样，不是「基色是 2020」这句声明。
- 正确的问法是：**一句基色声明所指的是一个颜色**。于是拿纯色去问，专挑 709 之外、2020 之内的边缘色
  （(20,5,5)、(0,128,0)、(5,5,20)），表里每一种画面格式各取一条代表，按容器那四样标记解回来：
  控制档 0~1 阶，`bt2020` 一律 1 阶，含 8 位 4:2:0 与 VP9 带 alpha 那两条。门槛因此整个撤掉，
  三档现在同进同退——只有「一串图像文件没有容器」与「纯声带没有画面」这两条拒绝还留着。
- 撤拒绝的时候把反向也钉上：`refusal_suite` 现在既查 `mxf-prores-422hq`／`h264-720p-web` 挂了
  `bt2020` 编得出来、图里真的带 `lut3d=file=primaries-`、容器真的写 `-color_primaries bt2020`，
  也查序列与纯声带那两条照旧点名。只查拒不看收，一条把判据写反的守卫照样能全绿——这条规矩是早前
  立的，本轮又用它救回一次。

### 渐变那把尺改了颗粒，分类改成量的

- 图案的颗粒从「逐列一变」改成 **2×2 的块**（`RAMP_BLOCK`），与交付画面最粗的那一档抽样对齐，并把
  宽度翻到 512 让 0..255 那 256 级仍然一级不落。于是同一条尺在 10 位 4:4:4、10 位 4:2:2 上都能用：
  控制档 1~2 阶，`bt2020` 7~8 阶，判据收成「绝对 9 阶、比同一条的控制档多 7 阶」——两个数都是量出来的
  最大加一阶余量，不是拍出来的。
- 「这份像素量得动吗」不再照格式名猜，而是**每轮先跑控制档再分类**：8 位 4:2:0 那份连控制档都解到
  46~62 阶，这一条就明说「量具在这里不成立」，判它的是纯色那把尺。上半年正是那句照名字的猜测，
  把一条本来量得动的 10 位 4:2:2 一起挡在了外面。
- 素材先探再信：`build_ramp_project` 现在把 PNG 逐块读回来比一遍（块内两列两行都必须等于那一块的
  期望值）。第一版就是这一步没做够，把 `floor(X/2)` 写成了 `floor(X,2)`（FFmpeg 当场
  `Error processing filtergraph`）、又把最内层那一条渐变写成了定值，量到的全是素材自己的错。

### 立方体的格数交给数学，不交给 FFmpeg

- 加了一档 `cube_suite`（纯数学，不跑编码）：读引擎写进作业目录的那张 `.cube`，把格点上的值与本文件
  独立算的参考比（最大 0.04 阶），再把「相邻两格中点与两端平均之差」当作插值地板算一遍（0.17 阶），
  判据 0.5 阶。
- 为什么必须由数学判：把格数从 65 一路砍到 9，渐变档量到的最大偏差**始终是 7 阶**（65/33/17/9 全一样），
  那 7 阶是有损编码器在奈奎斯特图案上的账，与插值无关。换句话说，交付侧那把尺看不见这件事，
  让它去判格数等于没判。
- 于是格数 65³ → 33³：插值地板从 0.07 阶变 0.17 阶，仍在判据以内，而每张交付目录少写 6.3 MB 文本
  （7241 KB → 947 KB）。突变验过：改回 9³ 当场红在「0.62 阶 > 0.5」。

### 顺带救回一段从没跑过的门禁

- `capability_suite` 里 `from agentcut import gamut` 之后误缩进写成了一个嵌套
  `def gamut_back(a, b): return …`，于是「引擎算的矩阵 vs 公布表」「反方向 vs 公布前向阵的逆」
  「bt709 曲线往返」三条断言全落在那个 `return` 之后——**绿色了很多轮，一条也没跑过**。
- 捡回来先做突变验证：把引擎矩阵一个系数挪 1%（与公布表差 0.00328）当场红。同一次变异还确认了
  另一条老规矩：互逆的一对错曲线，往返自洽检查抓不到（对调指数后 `capabilities` 全绿），只有拿外部
  公布数算的那把纯色尺抓得到。
- `ramp_rows()` 的注解也撒过一次谎：它返回 `(rows, step)`，签名写着 `list[...]`。签名改对，位深那把
  刻度从此是显式传下去的。

### 当前事实

- 12 个套件全绿：capabilities／compile／pixels／round trip／refusals／video／http／receipts／
  tiers／flat／cube／ramp（`tests/colour_tag_check.py`）。
- `colour_tag_presets()` 三档给的是同一份名单（15 条带画面又有容器的预设），名单本身由预设表算出来，
  不再手写；`capabilities.output_colour_tag_presets` 原样下发。
- 界面那一次真点也量了（打包版 v1.153.0，Chromium 里点「导出」→「开始导出」，预设是**原始画质 H.264**、
  8 位 4:2:0，标记选 BT.2020 宽色）：任务 `succeeded`、复检 True，产物读回
  `bt2020nc/bt2020/bt709 range=tv`，那一格码字 (81,109,146) 与独立预测一致，按它自己写的四样标记解回
  (126,62,28)，与源文件那一格 (125,62,29) 差 (1,0,1)。回读脚本第一次报的是 20 阶——红在量具：它自己另写了
  一份「只折回 RGB、不做基色转换」的数学。改成直接 import 门禁那把尺（`viewer_recovers`）之后才是这组数。
  同一份色彩数学写第二遍，就是这一轮那条假红的成因。
- `gamut.DELIVERY_CUBE_SIZE` 是 33；`APP_VERSION` 是 `1.153.0`；工程 schema 未动（仍是 v17）。

## 1.154 的账：透明母版的色彩声明，以及一次「量具差点把好消息读成坏消息」

- 交出去的能力：带 `colour_tag` 的透明母版把 RGB→YUV 那一折从编码器手里接回图里（
  `format=gbrap…` → 立方体（换基色那一档才加）→ `zscale=matrix=…:range=tv` → `format=<预设 yuva>`），
  于是容器上那三样标记第一次在**带 alpha 的交付**上也是实话。量的两格：
  `prores-4444-alpha` 交出 `yuva=(314,429,628,516)`，8 位尺 (78,107,157) 对 709 预测 (79,107,157) 差 1、
  对 601 预测 (82,104,158) 差 4；`vp9-1080p-web-alpha` 交出 (79,107,157)，与 709 预测逐位相同。
  两次的 alpha 都在（128 → 129 / 130）。
- 撤掉一条拒绝与一个入参：`COLOUR_TAG_NOT_WITH_ALPHA` 从 `render.py`、渲染层提示表与面板的
  `tagBlocker` 三处一起删；`colourTagAllowed` 的 `matte` 入参没了，`tests/desktop_colour_tag_check.ts`
  改钉新的形状，并把「透明也能带标记」这句判断钉在**只有一处**（面板不许自己再判一次）。
- 新档 `alpha_suite` 两边都判：未标记那一路 `format=rgba` 收尾、图里没有 `zscale`（老交付一字不变）；
  带标记那一路容器三样齐全、色度**离 709 的预测比离 601 的近**（判据是这两个预测之差 ≥3，不是某个
  绝对数——ProRes/VP9 自己有损，绝对数说不清），alpha 那一格与 authored 差 ≤8。
- 差点误判的那一次值得记：VP9 的 matte 在 WebM 里走 side channel，`ffprobe` 说 `yuv420p`、
  对原生解码输出用 `alphaextract` 直接报 "Requested planes not available"。用这两样去量会得出
  「透明 webm 交付把 alpha 丢了」，于是要给编码器加 `-auto-alt-ref 0`。`tests/alphamaster_check.py`
  早就写着正确读法（点名 `-c:v libvpx-vp9`），照它量 alpha 完好无损。那条开关被撤回——
  **没有实测支撑的编码器参数不进交付路径**，而这一轮的教训是：读不到某个平面，先怀疑读法，
  再怀疑交付。

## 1.155（文档与门禁）：一句「不估计旋转」被指认为假话

- README 的「还差的那几件」写着「跟踪与稳定不估计旋转」。对着源码量：`stabilize.py` 从 1.67 起就用
  四个画面锚点做 Arun 刚体拟合，把反向的 roll 写成 `rotation` 关键帧，低于 0.19° 的死区不写（那句
  死区说明就写在代码里）。所以这句话**对稳定是错的**，只有遮罩跟踪那一路真的只跟平移与缩放。
  改成「遮罩跟踪不估计旋转」，并把旧句子收进 `tests/docs_facts_check.py` 的过时说法名单。
- 新加的那条双向钉：文档再说那句旧话会红；`stabilize.py` 哪天真的不再估 roll（docstring 与写曲线那两处
  之一没了）也会红。没动引擎与渲染层，发布物一字未改，因此不需要重打包——`released_package_check` 仍然
  拿 `contracts.APP_VERSION` 比 asar，比的是同一个来源。


## 1.156 的账：P3-D65 交出去了，而它交出去的第一步是推翻上一轮自己写下的那个数

- 1.153 在那一档的位置上留了一句「量过才写」的话：蓝通道被夹掉 30 阶、709 的绿原色在 P3-D65
  之外、那是真正的色域压缩才兑得了现。本轮把它重算了一遍，结论是**那个动作属于反方向那张表**：
  `P3→709` 的最小系数是 -0.22494，33³ 的 35937 格里 16412 格掉出 [0,1]，那才是会夹的；
  交付要乘的 `709→P3-D65` 九个系数全非负、每行和 1，同一张格子一格不出界。两张表互为逆阵，
  用反了也仍然自洽——与本轮之前那对调了指数的两条 BT.709 曲线是同一族，那一次靠纯色尺抓到，
  这一次靠「问未钳位的那个数」抓到。
- 这一轮没有把旧结论「圆过去」，而是把新判据钉成两句必须同时成立的话（`cube_suite`）：前向
  必须一格不出界，反向必须真出界。只写前一句，门禁会对任何矩阵都说得通；只写后一句，就没人
  拦得住真的把某档写成收窄方向。出界的松弛度由抄写值自身的 `max|行和-1|` 给（P3 是 2e-05），
  不是拍的——方向错了是 0.22 那个量级，这种松弛度挡不住它，这正是它该有的样子。
- 交出去的东西（数都是当场重量的，随包 FFmpeg 6.1.1）：素材里那一格 (126,63,30) 挂 `p3-d65`
  交出 YUV (80,110,152)，与独立算式逐位相同；容器写 `smpte432`/`bt709`/`bt709`/`tv`，mp4、webm、
  MXF 都原样读回；按这四样解回来是 (127,63,29)，与源差 (1,0,1)。纯色尺逐格式：10 位三份 1 阶、
  8 位 4:2:0 与 VP9 两份 2 阶（判据 4 阶），控制档 0~1 阶；渐变尺最大 7 阶（判据 9 / 比控制档
  多 7）；立方体尺格点 0.01 阶、插值地板 0.06 阶。
- 同一轮里第三次踩到那条老规矩：**门禁写死的清单必须在新能力落地的那一次跟着改**。这一轮有
  四处清单要跟上（`capability_suite` 的基色名→容器枚举名、那句未知标记拒绝点名的字面量清单、
  `packed_engine_surface_check` 的档位清单、`flat_suite`/`refusal_suite` 原来写死的 `bt2020`），
  其中两处是本轮先跑红了才改的——红得对，那一档确实要能被点名出来才算交出去。前一种情形
  （清单没跟着改、门禁照常绿）本轮用一条覆盖断言堵死：档位清单必须等于契约表。
- 顺带把 1.154 那条透明母版的账补齐：`alpha_suite` 从「只带 `bt709` 走一遍」改成表里**每一档**
  都走一遍，宽色那两档另加两句判据（编译串里必须有 `lut3d` 那一站、必须比「不换基色直接折」那个
  预测明显更近）。量到的：ProRes 4444 挂 `p3-d65` 交出 (316,440,607,516)，8 位尺 (79,110,152) 与
  独立预测差 0，按标记解回 (125,62,28)、alpha 129；VP9 那一份差 0、alpha 130；`bt2020` 差 1。
  这一趟先红了一次，红在我的量具上：宽色那档多一张内容寻址的旁路立方体，门禁没替引擎把它落盘，
  FFmpeg 回「Error parsing global options: No such file or directory」。先把量具修对，再说交付。
- 突变验证（每条新断言都红在自己那一句上，控制组绿）：
  1. 把 `cube_suite` 里那份 P3 前向表换成收窄那张（也就是「方向用反」的那次错误）——红在
     「把 16413 格搬出 [0,1]（未钳位的值域 -0.22494~+1.22494，抄写松弛 1e-05）」那一句。为了让
     这句先说出口，本轮把 `cube_suite` 里两句的顺序调了：先问方向（这一档需不需要压缩），
     再问格点抄没抄对。
  2. 把反向那张表写成恒等阵（前向那句于是失去意义）——红在「反方向那张表也不出界……这颗锚
     已经在空转」那一句。
  3. 把那一行的 `primaries` 改回 `bt709`——`capability_suite` 红在「基色声明与要换去的档对不上」。
  4. 把那一行从契约表里删掉——`docs_facts_check` 红在「契约表里 p3-d65 这一档没了」那一句；
     同一份改动也让那句未知标记的点名词与界面/装机版那两份档位清单跟着对不上。
  5. README 把四档写成三档——`docs_facts_check` 红在「delivery-colour row does not say 4 档」。
  6. 数据锚里不给 `p3-d65` 出处——`gamut_check` 红在新加的那条覆盖断言（`{'p3-d65'}` 没锚）。
- 还没做的，按老规矩写在这里：影院 DCI-P3 那一档（白点 0.314,0.351、γ2.6）需要先有色适应那半套，
  本表全 D65，不做半套；显示端与交付标记的对齐仍要等 `COLOR_SPACES` 里有宽基色那一档再说。

## 1.156 的补账：交付那一行报的「最差几阶」由量它的那把尺亲自判

- 交完 P3-D65 那一轮，README 的交付行还写着「四档都按纯色量过……最差 1 阶」。这是本轮自己
  弄出来的过头话：`flat_suite` 逐格式重量到的是 **2 阶**（10 位那三份 1 阶，8 位 4:2:0 与
  VP9 那两份 2 阶），1 阶只是 `bt2020` 自己的账。文档里被别人引用的就是这一个数，所以修法不是
  改句子，是把句子交给量具：`flat_suite` 收尾时读 README 那句「按标记解回最差 N 阶」，要求
  N **等于**本轮重量的最大值，且不超过判据 `FLAT_LIMIT`。四条突变各自红在自己那句上——写成 1 阶
  红、写成 3 阶红、整句删掉红（那个数从此没人对着）、把「709 之外」写回来也红；控制组绿。
- 同一句里还有一处把夹具说错的地方：`FLAT_COLOURS` 是 (20,5,5)／(0,128,0)／(5,5,20)，那是
  **贴着 709 边界的暗饱和纯色**，不是「709 之外」的颜色（纯色夹具本来就 authored 在 709 里）。
  README、AGENTS、`docs/api.md`、`contracts.py` 那两条注释与门禁自己的注释共六处一起改口，
  并把「不许再念 709 之外」钉在同一条断言上：哪天夹具真的换成 709 之外的颜色，这句话会红，
  那时该改的是断言而不是文档。
- 本轮不动引擎行为：`contracts.py` 改的两处是注释，版本号仍 1.156.0，交付的字节按同一版本
  重新构建并逐字节对表（根目录那份仍等于便携版）。文档与门禁的这一笔账由套件里那一项自己复跑。

## 1.156 的又一笔账：发布包里那支 FFmpeg，原来是装机器碰巧有的那一支

- 补完文档接着重建（`build_engine.py --verify` → `npm run dist` → 重抄根 `AgentCut.exe`），
  发现根目录那份从 189,919,996 字节变成 273,264,330 字节——差出来的 83 MB 是随包那两支媒体
  程序：`desktop/resources/bin/ffmpeg.exe` 成了本机 winget 的 **9.0.2 full build**（单支
  227,823,104 字节），而工程锁定的静态包那支是 `6.1.1-essentials_build`（82,797,568）。
  所有门禁当时都是绿的：`--verify` 只验「引擎能不能在 exe 旁边找到一支可用的 FFmpeg」，
  它不验那是哪一支。
- 成因在 `scripts/build_engine.py` 的 `find_source`：`desktop/node_modules` 里找不到就往下退——
  `C:/ffmpeg/bin`、`C:/tools/ffmpeg/bin`、`Program Files`，最后 PATH。本轮先清理再重建，
  `node_modules` 正是被清掉的那一样，于是退路生效；`shutil.copy2` 还把旧时间戳一起搬了过来，
  看上去更像「一直都在」。**发布包内嵌的媒体程序由装机器碰巧有什么决定**，与 1.152 收回来那条
  「门禁不许用第二份 FFmpeg」是同一类缺陷，只是发生在构建这一侧：README、`docs/api.md` 与那一串
  色彩实测数的依据都是随包 6.1.1，换成 9.x 那些数不再成立。
- 修法按同一口径：只准用静态包，三条退路整个删掉；确实要换一支，用 `AGENTCUT_FFMPEG` /
  `AGENTCUT_FFPROBE` 把路径明确交进来。构建每次写 `desktop/resources/bin/media-stamp.json`
  （版本行＋sha256＋字节数＋来源），身份由这张戳说，不由任何人手抄的版本号说——写死「6.1.1」
  迟早变成第五条「门禁里过时的字面量」。
- 门禁两头各钉一处：`tests/mediabinary_check.py` 新增 `media_identity`（四种情形各红一次：戳不存在、
  字节与戳不符、版本行与戳不符、来源不在 `desktop/node_modules/` 那一层；控制组绿），
  `tests/released_package_check.py` 新增「装机 `win-unpacked/resources/bin/` 里那两支与随包的逐字节
  相同」。重建后 `ffmpeg -version` 回到 6.1.1，根 exe 189,920,532 字节且与便携版逐字节相同。
- 这一笔的教训：`--verify` 通过不等于装机的就是量过的。凡是「随包」的东西，要么由来源路径钉住，
  要么由内容摘要钉住；两者都没有，它只是碰巧对。

## 1.156 的第三笔：DCI-P3 那一档的墙量清楚了，而且它不在色适应上

- 停放点原来写的是「要做就得先有色适应那一半，本表全 D65，不做半套」。本轮先把那句话变成数：
  用 Bradford 把 709(D65) 适到 DCI-P3 的影院白 (0.314,0.351)，九个系数是
  0.868578/0.128930/0.002492 · 0.034540/0.961817/0.003643 · 0.016805/0.070766/0.912429，
  全正、每行和 1；33³ 的 35937 格未钳位值域 +0.000000~+1.000000，出界 0 格；纯色往返逐位对得上。
  所以色适应那一半是走得通的，**它不是墙**。
- 真正的墙在容器那三句话上：随包 FFmpeg 6.1.1 的 `-color_trc` 名单是 bt709／unknown／gamma22／
  gamma28／smpte170m／smpte240m／linear／log100／log316／iec61966-2-4／iec61966-2-1／smpte2084／
  smpte428／arib-std-b67——**没有 γ2.6**。实测 `-color_trc gamma26` 在 mp4、MXF、webm 三条路上都
  直接失败（`Undefined constant or missing '(' in 'gamma26'`，产物根本没写成）。影院母版的传递
  特性说不出来，这张文件就不能按自身声明被解回原色，于是那一档仍不交——但这次的理由是量出来的，
  不是猜的，也不是「我们还没做色适应」。
- 顺手把这条规矩推广到所有档：`capability_suite` 新增 `container_tag_names`，从随包 FFmpeg 的
  `-h full` 里**当场读**出 `color_primaries`／`color_trc`／`colorspace` 三份名单（不抄第二份记忆），
  再要求表里每一档声明的三样值都念得出；并钉一句「γ2.6 不在名单里」。这一句是双向的：哪天随包
  那支升级后认得了 γ2.6，门禁当场红，把 DCI-P3 那一档重新拿出来量。突变（各自红在自己那句上，控制组绿）：
  1. 把 `p3-d65` 那行的 `matrix` 写成不存在的 `bt2021` → 红在「档位 p3-d65 声明的 matrix='bt2021' 不在
     随包 FFmpeg 认得的名单里」；
  2. 把 `p3-d65` 那行的 `transfer` 写成 `gamma26` → 红在**前面那一条**「每一档的 transfer 必须是 bt709」上
     （图里那一站两侧都按 709 折，那条本来就先钉着），所以 γ2.6 那句重开的话只能靠模拟容器名单来验；
  3. 模拟一份认 γ2.6 的随包 FFmpeg（把 `gamma26` 塞进读来的名单）→ 红在「墙换了地方，重新量它」那句；
  4. 模拟一份连 `bt709` 都念不出的 FFmpeg（名单只剩 unknown）→ 红在「档位 bt709 声明的 primaries 不在名单里」，
     也就是这份名单一旦被读空，四档一律不放行，而不是照旧绿。

## 1.157（2026-10-14）多目标遮罩跟踪

- 交付：组请求 `POST /mask-track`（MCP `mask_track`）、逐目标的窗口/预算/`merge`、按窗口键共享的
  一次解码、界面「跟踪所选 N 段」，以及 `MASK_TRACK_DUPLICATE` 这条点名拒绝。旧的每片段路由
  `/clips/{clip_id}/track` 删干净，两处入口不留分家。
- 量到的：同一段窗口的 2 个目标 → `decoded_passes=1`、`frames_decoded=60`，第二条目标
  `shared_decode=true`；两个不同窗口 → `decoded_passes=2`；把 `CLIP_KEYFRAME_LIMIT-1` 条曲线灌进
  第二段 → 整组 `MASK_TRACK_BUDGET`，`details` 点名 `clip_id` 与 `target_position`，另一段一条
  `mask_x` 都不许多写、revision 一步都不许多涨；把那段拿掉，同一份请求照旧跟满 60 帧。
- 修掉两处本轮自己写进去的缺陷：`frames_decoded` 一度把 `(width, frames)` 元组的长度当成帧数
  （回执报 2），`plan_mask_track` 还在读目标上已删除的 `sequence_id`（`analysis_sweep_check` 与
  `sequence_plan_check` 当场红，红得对）。
- 修掉一条既有交付缺陷：`contracts.py` 里 `bt2020` 那一段注释被 newline-join 粘成一行（ruff E501
  117 列，仓库没有门禁跑 ruff，所以它活了一轮），而粘进去的那句「最差 1 阶」正是 1.156 已经改过口、
  却漏掉的一处手抄——注释从此不再抄会过期的阶数，那个数只由 `flat_suite` 当场核对 README 那一行。
- 夹具说过一次谎：`drawbox=x=…t` 的 `t` 不按帧重算，两块板子是静止的，跟踪在第一帧就报跟丢。
  换成两路 `overlay` 推盒子之后，反向双板各自跟满 60 帧、最差偏差 0.0067 幅宽；`fixture_suite`
  先把两个盒子单独跟一遍并和解析真值比，之后的判据才站在真实的画面上。
- 测试面：新增 `tests/multitrack_check.py` 与 `tests/desktop_trackgroup_check.ts`；
  `tracking_check`、`analysis_sweep_check`、`sequence_plan_check`、`self_check` 跟着组请求与工具改名走
  （`clip_track` → `mask_track`）。

## 1.157 追加：两把「先量再判」的门禁，和一处故意留下的欠账

- 旋转那一档不再靠感觉。`tests/rotationwall_check.py` 先造一块真在转的板子并自证——30 帧里亮区主轴
  转了 33.28°，作者写进去的是 33.23°（方板的主轴按 90° 折叠，取带符号最大的那一格）——再把两条候选
  路线放在同一块夹具上量：四锚点 Arun 拟合逐帧角增量中位 **15.52°**（作者每帧 1.15°）、30 帧累计
  **445.1°**（真相 33.2°）；把第 0 帧模板按候选角转过去、在已定下的中心上搜绝对角，误差中位
  **3.46°**。判据钉的是这两个测量而不是猜想：`ANCHOR_NOISE_FACTOR = 5.0`（拟合的中位要比作者写进去
  的那一档大 5 倍才算「那是噪声」）与 `SEARCH_MEDIAN_DEGREES = 6.0`（搜索那条路收不进 6° 就不许照着
  建）。
- `tests/stylewidth_check.py` 让排版这一档终于有了门禁，而且量的是项目自己那把尺：读
  `pyproject.toml` 的 `line-length`（钉死 = 100），按显示宽度算（全角两格），豁免口径当场与
  `ruff check --select E501` 的 JSON 逐行比对——第一方目录零漏报，只多报了随包 vosk 的三方文件
  （本来就不在范围内）。三种豁免（整行只有一个不可断的 token、行尾是 URL、行尾是 `# type:` 一类
  pragma）由档内 `self_proof()` 用四条样本行逐条判死，每条样本还先自证「自己确实超过了格」，
  否则判它没意义。
- 这一档当场就把账抓出来一遍：`tests` 里八行可断的超长（其中两行正是本轮新写的 `rotationwall_check`
  自己），加上 `tests/tracking_check.py` 里那个 1.157 改口之后就不再用到的 `MaskTrackRequest` 导入。
  手工拆掉自己的两行、按文档里那条完成标准跑过格式化之后，`ruff check src tests examples` 全绿，
  `CEILINGS` 的 tests 从 6 降到 0，agent 停在当场量的 27，scripts+examples 是 0。
- 故意留下的一处欠账：`ruff format --check src tests examples` 仍报 `contracts.py`、`http_api.py`
  两份引擎文件。这一轮真把它们格式化过，也逐份比对 `ast.dump` 证了改动是 AST 等价的纯空白，然后把
  那两份还原——随包 exe 就是从这两份的当前字节建出来的，源码与发布包要么同一笔一起走，要么别动，
  为几处空行重跑一次 PyInstaller 与 electron-builder 不值。下一轮动引擎时顺手收掉。
- 突变：S1–S5 与 R1–R3 共八次，每一次都红在自己那条断言上（harness 在证据目录
  `agentcut-1157/mutate_style_rotation.py`：每次改完立刻按字节还原，还原失败即整轮作废，末了两份
  对照复跑为绿）。S4 第一次跑红在了「样本行没超过 120 格」那句上——那是 self_proof 先说话，说明
  这把尺确实会自己发现自己被换掉；把 `LIMIT == 100` 那句挪到最前面之后，它红在该红的那句上。

## 1.158 按表换基色：那张基色表有了消费者

1.146 交出 `capabilities.gamut_matrices`（六档、每档九个系数与两端传递函数名）时，第一方代码里没有
一处消费者；1.158 补的就是这一处。判断只写在 `desktop/src/gamutFold.ts` 一个文件里，界面读它，
`tests/desktop_gamutfold_check.ts` 也读它；九个数字的唯一来源仍是 `gamut.primaries_matrix`。

行为要点（详细数字见 `AGENTS.md` 的「四轮前的停放点（1.158）」）：折进去的那一枚普通通道混合节点只落在
色彩管理那一对盖章的转换节点中间；没套那一对、只有半对、那一格里是手工填的数、中间已经有两枚以上、
链子已满——这五种场合各有自己的一句中文，且每句都指着一条此刻真走得通的出路；再点一次是换同一格，
不是叠第二枚。

验收：`tests/gamutfold_check.py`（新增，第 110 项）+ `tests/desktop_gamutfold_check.ts`（第 56 份壳层
检查）+ 打包版真点一次（`agentcut-验收脚本/ui_fold_1158.py`：引擎从 r1 走到 r3，读回
`[transfer, matrix, transfer]` 与首档那九个数字）+ `package_check_1158.py`（冻结引擎自报 1.158.0、
表与源码逐字节相同、随包两支与 npm 那一份同哈希、asar 里数得到按钮）。突变八次全红在自己那句上。

一处值得记住的事故：`scripts/build_engine.py` 先清空 `desktop/resources/bin/` 再检查那两支 FFmpeg 在
不在，于是 `npm ci --ignore-scripts` 之后跑它，会把装机用的 `ffmpeg.exe`/`ffprobe.exe`/`media-stamp.json`
删掉后自己失败。恢复用的是 npmmirror 的 b6.1.1 二进制镜像（82,797,568 B、6.1.1-essentials_build），
重新打戳后随包两支与 `node_modules` 那一份同哈希。下一轮起：**跑引擎构建之前先确认
`desktop/node_modules/ffmpeg-static/ffmpeg.exe` 存在**。

## 1.159 工程级基色：显示端那一半的墙拆了，附一处自己抓出来的折叠缺陷

`AGENTS.md` 从 1.152 起一直挂着「交付标记与工程色彩管理的显示端对齐」那一条，而它欠的就是
**工程以哪档原色工作**这个概念——`COLOR_SPACES` 是曲线的词表，从来不含基色。这一轮把它做完：
`SequenceSettings.working_primaries`（默认 `rec709`，schema 18），名单由 `gamut.WORKING_PRIMARIES`
现算，界面读 `capabilities.working_primaries`，`desktop/src/workingSpace.ts` 一处收着措辞与
`DISPLAY_PRIMARIES` 那唯一一份默认值。

**本轮最大的收获是门禁抓到自己上一版的那个缺陷。** 第一版预览折法只交一个 `matrix` 阶段，浏览器于是把
九个系数乘在 sRGB **存储值**上；这与导出那张立方体（抬进线性光—乘—落回信号）根本不是同一个函数。
`tests/workingprimaries_check.py` 里新放的 `fold_math_suite` 在 73,824 个颜色上比三种算法，把这两个数钉住：
三段折法与真折叠最坏差 **1** 阶（256 格表的插值地板），乘在存储值上最坏差 **71** 阶。修法就是交三段
（`gamut.transfer_tables()` 的两张每通道表夹着那九个数），而不是赌浏览器认得 `linearRGB` 的原语插值。
第二处是读代码读出来的：`preview_grade` 原本在链子为空时直接回 None，于是**没挂调色链的一段**在宽档工程
里一个字都不折——折的是工程那一档，与链子在不在无关，现在也折。

行为要点（详细数字见 `AGENTS.md` 的「三轮前的停放点（1.159）」）：默认档与 1.158 逐字节相同（把键删回
「没写过」也是同一份字节）；同一档就不折（`rec2020` 工程 + `bt2020` 交付的图里没有第二趟立方体）；
`p3-d65` 工程 + `bt2020` 交出的 cube 逐字等于 `gamut.delivery_cube("p3-d65","rec2020")`；选到名单外的档位
是 422 且版本不涨；界面既不算九个数也不抄默认值。

验收：`tests/workingprimaries_check.py`（新增，第 111 项）+ `tests/desktop_workingprimaries_check.ts`
（第 57 份壳检）+ 打包版真点一次（`agentcut-验收脚本/ui_working_1159.py`：引擎从 r1 走到 r2，读回
`["lut","lut","matrix","lut"]`、滤镜 id 变了，屏幕上 3 个 `feComponentTransfer` + 1 个 `feColorMatrix`）
+ `package_check_1159.py`（冻结引擎自报 1.159.0、随包两支与 `node_modules` 同哈希、asar 里数得到那一行）。
16 条突变逐条红在自己那条断言上：M7 与 M10 各把 `transfer_tables` 那两张表中的一张换成恒等表，
M9 把那条曲线的公布常数 β 从 0.099 挪到 0.098，三条都红在「预览那两级表不再是那条公布的 BT.709 曲线
切的」那一族断言上——那把尺是门禁里照公布常数（α=1.099、β=0.099、指数 0.45、线性段斜率 4.5）另写一遍的
BT.709，两张表 512 格逐格比，不读产品那份曲线（第一版的 `exact()` 读的就是它，1.160 那轮把这类耦合量成
过 29 阶）。另有一刀（把设置合并改成深合并）是**惰突变**——契约边界已经把没写的键补成默认值——所以撤掉
那一刀，并在门禁与交付记录里写下为什么。

## 1.160 一条门禁与一垛数：素材原色那条自动路为什么本轮不上路

这一轮从「把 1.159 剩下的那一半做完」开始——让 `clip.color_manage` 也读素材自己声明的那档原色
（`color_primaries`），自动折进工程那一档。量过之后决定**不交**，并把量的凭据钉成门禁
`tests/primariestags_check.py`（套件第 112 项）。数字如下，都能用 `agentcut-验收脚本/` 里那三份脚本重跑。

**词表是编出来、探针出来的。** 随包 FFmpeg 6.1.1 对 `color_primaries` 那一格：8 种写法写进去读回来
同名（`bt709`、`smpte170m`、`bt470bg`、`bt2020`、`smpte432`、`smpte431`、`film`、`bt470m`），4 种当场拒
（`jcac`、`echostars`、`170m`、`p3`），`unknown` 写了等于没写。这张表以后是「读素材原色」唯一的取行范围；
门禁把这四堆钉住，抄进一个拼不出的写法就红。

**真正拦住这一轮的是同名两档曲线。** 调色链那一对的 `rec709` 在 `grade.GAMMA_BY_SPACE` 里是**纯幂 2.4**
（BT.1886 的显示端 EOTF），而交付立方体与 1.159 预览那两级表用的 `gamut.bt709_eotf/oetf` 是**分段 0.45**
（BT.709 的摄像机 OETF，也是容器那一格 `bt709` 本来的意思）。8 位上量：信号域最坏差 27.2 阶、线性域
最坏差 18.475 阶。

于是先做夹具实验（`plates_1160.py` 造一对文件——同一幅颜色分别按 709 与按 P3-D65 存储、两份都写
`bt709` 曲线，夹具里的 3×3 与曲线是独立写的并对过公布的 RGB→XYZ / XYZ→RGB 首行；`fidelity_1160.py`
跑对照）：把 1.158 那颗按钮写下的 `[transfer, matrix, transfer]` 套在 P3 那枚上，交 ProRes 4444
（4:4:4，先把色度抽样这条干扰摘掉）。**未折时与基准差 47 阶；折了之后仍差 29 阶**，而只套那一对、
中间不插矩阵时交出来的与不套一模一样（47 阶原样留着）——那一对自己是自洽的，问题只出在中间那一级
矩阵所假设的「线性光」与两端曲线对不上，量级正落在 27.2 阶那条分叉上。

**结论与挡法**：把「素材说了哪档原色」做成每一段素材的默认折叠，等于把这 29 阶发给所有人，所以本轮
把它挡在契约外面——门禁钉住 `ClipColorManage` 没有 `auto_primaries` 字段、契约里没有
`COLOR_PRIMARIES_TAGS` 那张表；真要交，先解那条分叉（一条问题一个答案），解完必须重跑 1.151/1.152/1.156
那三批交付实测与 1.159 那两级预览表。5 条突变逐条红在自己那条断言上（`mutate_1160.log`），其中 G4
（把 `rec709` 改成 2.2）与 G5（先放 `auto_primaries` 进契约）改的是产品源码，跑完按字节还原并核对
sha256，还原后门禁重新绿。

## 1.161 折叠那一步走哪档曲线：把它从引擎里的一条硬编码，变成工程声明的一格

### 为什么这一轮动的是「谁说话」，不是算术

1.160 量到同一个名字两条曲线：链子里那个 `rec709` 节点按纯幂 2.4 解（`grade.GAMMA_BY_SPACE`，
那是对人眼的显示端建模），容器那一格 `bt709` 本来的意思是 BT.709 的分段曲线（α=1.099、β=0.099、
编码侧指数 0.45），8 位上最坏差 27.2 信号阶／18.475 线性阶；而随包那支 FFmpeg 6.1.1 的 zscale
把 `bt709` 实现成纯幂 2.4（逐格差 0.011 阶）。两条都对——各自回答的是不同的问题，而「这一幅像素
实际是哪条曲线编出来的」引擎不知道。

上一轮据此拒绝的是「替每一段素材自动折」；这一轮交的是**把选择权交出去**：`SequenceSettings`
多一个 `fold_transfer`（schema 19），名单是 `gamut.TRANSFER_CURVES` 那两档，随
`capabilities.fold_transfers` 连同「这一档是谁」那句话一起下发。默认 `bt709` 就是 1.153 以来一直
在用的那一条，所以任何一份旧工程读进来画面不变；要按纯幂 2.4 折，是人（或 Agent）说出来的。

### 落点：量成了配对的两个方向，而不是一句「差 29 阶」

1.160 那个 29 阶是「默认那条折 γ2.4 存的像素」这一对的数，写成区间的样子容易让人以为说的是
曲线本身。这一轮把两个方向都跑了（夹具由门禁自己按公布常数造，两条曲线的指数各写一遍，不读
产品那一份——否则产品曲线一动基准跟着动）：

| 板上像素按 | 声明按 | 与解析期望的最坏差 |
|---|---|---|
| γ2.4 | γ2.4（配对） | 15 阶 |
| γ2.4 | 分段（配错） | 55 阶 |
| 分段 | 分段（配对） | 3 阶 |
| 分段 | γ2.4（配错） | 10 阶 |

期望读的是**板上那同一份整数**再按同一档解析折一次的结果，不是最初那格颜色：后者会被量化的
条件数污染——(255,0,0) 存进 P3-D65 是 (235,62,47)，折回来时绿通道是 −0.042·R + 1.042·G 两个
大数相消，板上半个台阶在这里放大成十几阶，那是夹具的账。第一版就是拿最初那格当期望，量到
「配对差 19 阶」这种没法解释的数，改成同板解析之后才分得清两件事。

于是有一条新的、属于立方体那一级的账记下来：**33³ + tetrahedral 的插值地板跟着曲线走**——
同一批格子在分段那张上 3 阶、在 γ2.4 那张上 15 阶（1.153 当年写的 0.17 阶地板说的是分段那一张）。
本轮没有替它改 `DELIVERY_CUBE_SIZE`，而是把这条写进入口清单：`gamma24` 这一档若要交出去做母带，
格子数得单独重量。

### 两端的形状

- 导出：`render.primaries_shift_stage(plan, row, working, fold_transfer)` →
  `gamut.delivery_cube(工程, 容器, curve=eotf, inverse=oetf)`，那张 33³ 的文本按内容寻址落进作业目录。
- 预览：`grade.preview_grade(color, working_primaries, fold_transfer)` →
  `gamut.transfer_tables(那一档)` 切那两张 256 格的每通道表，折在链子最后的仍是
  「抬光表 → 九个数 → 落回表」三段，滤镜 id 按最终阶段表重算。
- 时钟只有一处：`animation.py` 把 `settings.fold_transfer` 交给 `preview_grade`，嵌套合成读同一份
  工程设置，所以预览不会出现「工程说了、清单没跟上」。
- 名单之外点名拒收：`srgb` 这种本轮没对过表的名字（1.160 量到随包 FFmpeg 的 `iec61966-2-1` 自己
  就与 IEC 的分段差 12.1 阶，所以它进不了名单）在契约边界被 422 拒掉，版本不涨、字也不落库。

### 装机那一份自己认这两档

`package_check_1161.py`：冻结引擎自报 1.161.0／schema 19，`fold_transfers` 与源码
`gamut.fold_transfer_rows()` 逐字节相同；在它手里真建一份宽档工程——默认那一格就是名单第一行，
`fold_transfer=bt709` 时预览滤镜 id `g979dcb830c3d2b94`，改 `gamma24` 变成 `gea387fbf32d15449`，
两张每通道表逐格等于源码 `transfer_tables("gamma24")`；把 `srgb` 写进去回 422 且版本停在 3。
从新 `app.asar` 取出的渲染层里真点一次那一行（`ui_fold_1161.py`）：屏幕上那句话从「按容器那一格
本来的意思」换成「按你选的这一档」，引擎侧 revision **2→3**、存的值 `gamma24`、清单 id 变成
`gea387fbf32d15449`——与上面装机量到的那一对逐字相同，画面上 3 个 `feComponentTransfer` +
1 个 `feColorMatrix` 仍在。bundle 里数得到「折叠曲线」×5、`fold_transfers`×8、`ps-working`×5、
「抬进线性光」×6、`TRANSFER_CURVES`×1，而 `?? "gamma24"` 0 次。

### 一条门禁真的拦住了我

`tests/desktop_colortags_check.ts` 那张「允许清单是空表」红在新写的两句界面说明上——它们抄了
容器标记的字面值 `bt709`。改的是句子（写「BT.709／容器那一格」），不是那条门禁：那张表的唯一
主人叫 `capabilities`，界面念它、不抄它。顺带一条同名的巧合要写清：`gamma24` 在渲染层早就存在，
那是**链子那端曲线表**（`engine.ts` 的 `ColorSpace`）的名字，与这一格只是同拼、不同表，所以不在
禁抄之列——包检那条禁抄名单因此只禁容器标记的值与「自己抄一份默认档」。

### 突变 13 条（`mutate_1161.log`）

F1 契约不拦／F2 契约默认档挪走／F3 导出不看这一格／F4 预览不看这一格／F5 清单丢了这一格／
F6 把 γ2.4 的正方向写成分段那条／F7 能力表不再交这张表／T1 默认档不看名单第一行／T2 视图自己抄
曲线名／T3 store 自己抄曲线名／T4 拒绝那句话不再给出路／T5 默认那句不再提醒分叉／T6 帮助页那一格
改名。两条一开始红在别处：F6 落在「那两个方向不互逆」——那是名单那一段的第一道，比
`fork_suite` 更早也更准，期望锚点跟着改；T2 落在「视图读的是那张表的第一行」——把字面量那条检查
提到它前面，先说该说的话。**没有放宽容差，也没有撤掉任何一条。**

## 1.162 折叠那一路按曲线选编译法：把 1.161 那句「两端同一条」从形状钉到数

### 触发这一轮的，是我自己上一轮交下去的一句话

1.161 的工程面板多了一行「折叠曲线」，交付记录与 README 都写着预览与导出折的是**同一条形状**。
那句话当时钉住的是结构：两端读同一份 `settings.fold_transfer`、同一个函数、同一批系数。
它没有钉住**数**——而两端各自用的是两种不同的近似：

- 导出：一张 33³ 的 `.cube` 交给 FFmpeg 的 `lut3d=…:interp=tetrahedral`；
- 预览：两张 256 格的每通道表交给浏览器的 `feComponentTransfer`（格与格之间线性插值）。

`preview_export_gap_1162.py` 拿同一把尺（期望＝板上那同一份整数按该档解析折一次）在两万个颜色上
量了两端的地板与互差：默认那一条（分段）预览 1 阶、导出 7 阶、互差 7 阶；`gamma24` 预览 8 阶、
导出 23 阶、互差 24 阶。两个数各自都不大，凑在一起就不是「同一个数」了。而 γ2.4 那 8 阶说明
更糟的一件事：**256 格这个数是 1.159 为分段那条曲线量的，γ2.4 沿用它是继承，不是测量。**

### 加格子救不了导出那一级，换编译法才行

先试的是把立方体切密（`cube_interp_estimate.py`，同一条尺）：γ2.4 在 33³ 是 16 阶、49³ 是 7.8 阶、
65³ 又回到 9.6 阶，而 65³ 的文本 7.2 MB——「装得进每一次交付目录」这个前提当场不成立，
而且它对分段那条是有效的（3.4 → 1.7 阶），对 γ2.4 就是不走。

于是拿随包 FFmpeg 把四条路各跑一遍（`fold_routes_1162.py`，八格近饱和的板）：

| 声明的那档 | A 立方体 33³ | B 立方体 65³ | C `zscale→colorchannelmixer→zscale` | D zscale 自己换基色 |
|---|---|---|---|---|
| `bt709` | 3 阶 | 2 阶 | 14 阶 | 14 阶 |
| `gamma24` | 15 阶 | 9 阶 | **4 阶** | 4 阶 |

C 那一行就是本轮交出去的：抬线性与落回交给 zscale，中间那九个数仍是 `gamut.primaries_matrix`
算的那一份（不叫 zscale 自己换基色——那张表的唯一主人是引擎，所以 D 不采纳）。16 位中间量是有
用的：把它撤成 8 位，本轮门禁量到 19 阶（突变 P3 就是这一刀）。

**为什么分段那一条不能走 C**：随包 FFmpeg 的 zscale 把容器那一格实现成纯幂 2.4（1.160 逐格量到
差 0.011 阶），它念不出分段曲线——所以 `FOLD_ROUTES["bt709"]["trc"]` 是 `None`，
`fold_trc("bt709")` 直接抛。表里那个 `route` 不是偏好，是唯一走得通的那一条。

### 路由表必须自己证明自己

门禁 `precision_suite` 不再用我给的绝对容差裁决这件事：它拿**同一个 `render.fold_stage`**（产品
用的就是它，`primaries_shift_stage` 现在只是它的一个薄包装）把两条编译法在同一块板上各跑一遍，
断言「交出去的那一条不比别人那一条差」。对照还要跑**两块板**——放宽（p3-d65→rec2020，九个系数
几乎全正）与收窄（rec2020→p3-d65，一行里两个大数相消）。只在放宽那块上比，两条路都是 1 阶，
等于什么都没证。量到的：γ2.4 收窄板上本路 6 阶、立方体 16 阶；分段那一条另一条路走不通，于是
那条断言换成「唯一走得通的就是交出去的这一条」。

### 数（本轮门禁与装机同口径）

| 声明的那档 | 预览地板 | 导出地板 | 两端互差 | 按另一档声明 | 收窄板：本路／另一条 |
|---|---|---|---|---|---|
| `bt709` | 0 阶 | 1 阶 | 1 阶 | 26 阶 | 3 阶／走不通 |
| `gamma24` | 4 阶 | 1 阶 | 4 阶 | 26 阶 | 6 阶／16 阶 |

预览那两张表按曲线给格数：默认仍是 1.159 定的 256 格（旧工程的清单字节一字不改，门禁逐格钉），
γ2.4 给 1024 格（8 阶 → 4 阶；4096 格只到 3 阶，四倍的清单换一阶不值当）。

### 一处仪器错误，被自己新加的断言抓住

第一版 `precision_suite` 把「产品折到 rec2020」那一段去比「按 rec709 折」的期望，量到 144 阶——
这种数不可能属于产品，它属于仪器接线。改的是把目标那一端作为参数传进去，容差一个字没动。
突变四条一开始红在别处（P2、P3、P4、P8），锚点跟着改到真正先红的那一条：把分段塞进链条会让两档
编出同一条串，于是最先生效的是「换了曲线而导出图一个字没变」——那正是那一格变成摆设的定义。

## 1.163 粘贴属性：把「套到整轨」那一次的模式，搬到人自己挑的类别与目标上

1.108 交的是「一条片段的调色链套到整轨」——一个类别、固定目标集合。这一轮把单位换成人挑的「类别 × 目标」：剪映、达芬奇、AE 三家在那一处给的都是同一句承诺（这一段这几样变成那几段的，而位置不动），缺的是别的类别与「我全选中的是这三段」。

- 判断仍在一处。规划逐目标把候选命令交给 `apply_commands` 重放，整段一起试、试不过再一类一类试；  收下的那些命令就是最终那一批命令，拒的那条带的是 reducer 自己的 code、句子与 details。  这样「界面说的能粘」与「引擎真接受」之间没有第二条路可走。
- 类别之间不连坐，一类之内不写半个：音频段拿到效果·曲线·速率三类，同时被点名  「音频片段没有画面可调色」「遮罩只能用于画面轨」；稳定过的那段只被拒「变速」一类。
- 搬的是属性不是位置：`clip.speed` 走 `ripple=False`，实测那两段的 `position_ticks` 与  `source_in_ticks` 一字未动，而长度按各自速率换算（3 秒那段变 2 秒）。
- 「文字样式」不覆盖别人打的字：粘完 `body` 仍是目标自己那一行，样式（字号／颜色／垫子）跟着走。
- 幂等：已经一样的那一类一条命令都不发，所以粘两次与粘一次落进同一份状态；同一份工程问两次  规划，命令逐字节相同。
- 上限有出处：60 段一次规划在这台机器上实测 0.496 秒（每个目标都要把累积的命令重放一遍，  代价随工程规模涨；两万段那种规模没量过，所以上限仍是 64 而这句话留在账上）。
- 验收：`tests/attributepaste_check.py`（套件第 114 项，14 节）＋  `tests/desktop_attributepaste_check.ts`（第 58 份壳检）。20 条突变逐条红在自己那条断言上  （M1 让 color 不排命令、M2 撤掉幂等判断、M3 覆盖别人的字、M4 把 `ripple` 改回 True、  M5 让遮罩曲线同时进两类、M6 把画面稳定列进名单、M7/M8 让能力表与契约分家、M9 拒绝不再点名类别、  M10 额度不再参与、M11 撤掉路径与载荷的对照；S1-S9 打的是界面自抄中文名、默认勾、契约 id 当界面、  不再报针数、按钮不挂在那一处判断上、路由出现第二个拼法、帮助页与样式缺失）。  其中四条第一轮红在别处（M1/M4/M9 与 S8），改的是**门禁的说法与切分**而不是判据：M1 的锚点换成  「那条链不是来源那一份」，M4 换成「位置被搬属性搬走了」，M9 让门禁读 `row.get("category")`  好让「没点名类别」红在该说的那句上，S8 拆成两条各钉一条样式规则（拆之前那条对任何一条存在都满足，  本来就是不能红的断言）。
- 一处仪器错误：第一版夹具给图像素材写了 `speed_percent=150` 与 `text`，于是每一次规划都被  reducer 整份拒回——拒的是「图像没有播放速率」「画面片段不能带文字」，报的却是别的类别。  夹具改成视频素材与真正的文字片段之后，那些拒绝才真的是在拒这次要搬的东西。


## 1.164 遮罩可旋转：先量清浏览器能不能转，再决定转法

上一轮停放点写着「`mask-image` 与 `clip-path` 两条都真把椭圆转过去了」。那句话量的是**图内部的
`rotate`**（SVG 里那枚椭圆自己转），不是**图层带 `transform: rotate()`**。这一轮要的就是后一头，
量下来是 0.0°：遮罩不吃图层的旋转。所以这一档的写法只能是引擎烘图，界面平移；写进代码之前先量，
量的就是这一句——否则交出去的是一个绿门禁与一个不转的预览。

工程 schema 19→20（`ShapeMask.rotation`，默认 0°，旧工程读进来一字不改）；`clip.mask` 与 MCP
都不必新增入口，界面那一格叫「遮罩角度」，上下限是 `capabilities.limits.mask_rotation_limit`。

三条判断：路径遮罩不带角度；带角度的盒只准打中心曲线（宽/高曲线会把那张等比图拧成别的样子，
句子点名要人转回 0°）；角度本身还不是曲线——每一帧换一张图的代价本轮没量，不做半条路
（**这一条下一档 1.165 兑现了**：量的不是逐帧一张，而是按窗一张，见下面那一节）。

验证账：`tests/maskrot_check.py`（契约、式子原文、那张图的 viewBox 与转角、四条拒绝两头、
预览清单下发的是哪张图、67 个真像素点与一份按定义独立写出的判定逐点对、三档长轴各自歪对
方向）；第 59 份壳检 `tests/desktop_maskrot_check.ts`（那张参考线折回屏幕像素：30° 的长边正好是盒宽、短边正好是盒高——只钉长边那一条时，x 项少画幅比的突变是绿的，这一格才是看得见的；
+30°/−30° 的朝向、界面不许第二份三角换算、上下限只读 capabilities）；
`package_check_1164.py` 八项（冻结引擎自报 1.164.0／schema 20、它答的图与源码逐字节相同、
三段真导出、装机 asar 里那条 CSS 原文、Chromium 画出的与导出的对得上、反相那张、随包两支与
npm 那份同版本同哈希）。突变 23 条逐条红在自己那条断言上。

装机复核的界面那一半也真点了一次：在打包渲染层里选中片段、展开「遮罩」、在「遮罩角度」里敲 30 再 Tab 落笔——引擎那头 revision 1→2、`mask.rotation` 落库 30.0，画面那一层同时换成引擎新下发的那张（`viewBox="0 0 1000.0000 562.5000"`、形状带 `rotate(30.000000 500.0000 281.2500)`、`mask-size:100% 100%`），那颗旋钮的上下限读的就是 `limits.mask_rotation_limit`（−360..360）。（宿主与读数在 `agentcut-验收脚本/ui1164_host.py`、`ui1164-session.json`；`visibilityState` 为 hidden 时合成键事件不进 React，得用真输入事件。）
发布包：便携版 189,955,568 B（sha256 00b455e0d1fb6f6f…，根 `AgentCut.exe` 与它逐字节相同：True）、
安装版 190,116,278 B（82fdd9e1028e2cd2…）。

## 1.165 那枚角度能打关键帧：一份按帧对齐的窗表，两端各读一遍

1.164 欠的那一条在这一档还上了：`MaskProperty` 的第五条 `mask_rotation`，人按检查器那一格旁边的 ◇，
Agent 发同一条 `keyframe.set`。为什么不是连续曲线——`geq` 能给每一帧现算一个角，浏览器不能
（`mask-image` 不吃图层 `transform`，1.164 量的那一头），于是一端连续、一端台阶；这项目 refuse 的就是
这种缝，所以交的是**一份窗表两头读**：`animation.mask_rotation_schedule` 走 1.118/1.123 那一次同一件
`frame_windows`（段数 `limits.mask_rotation_schedule_segments`，本轮 12），导出侧
`rotation_step_expression` 把它串成嵌套 `if(lt(T,秒),角度,…)` 填进 `alpha_expression` 那两个
`cos/sin` 的位置，预览侧清单下发 `mask_rotation_windows`（每窗一张等比图）与同一条 `steps(1, end)`
曲线，界面按整数 tick 落格换图。代价是真的量过的：2 秒 30fps 切满 12 段、每张 845..846 字节、
烘一遍亚毫秒；「每帧一张」那条仍没量绘制代价（隐藏页不跑 rAF，设一次 CSS 不等于画一帧）。

**这一档最值的一笔是：缺陷先在装机包上红，而不是在源码门禁上红。** 换窗那一步原先打在帧起点的
秒数上（`.12f` 打印），而那一帧自己的 `T` 就是同一个秒数——两个浮点数比大小，判的只剩最后一位。
`package_check_1165.py` 拿随包 FFmpeg 导的那条阶梯量到第 15 帧主轴 83.5°，而引擎自己下发的窗表
在那里写 90°；源码门禁当时全绿，因为它取的两个采样点（第 1 秒与第 59/30 秒）都不落在窗边界上。
改法是打在半帧之内（`to_ticks − frame/2`），与界面那头本来就按整数 tick 的落格同一个语义；
补的两条断言把这一格钉住：plan 里每个边界字面量都在那一帧的半帧之内，以及边界那一帧真像素
（第一帧已是新窗的角 41.2°、前一帧还停在旧窗 33.8°）。三条突变各红在一条上（撤掉余量、
换成 `from_ticks`、把 `lt` 改成 `lte`）——「一个采样点落在边界上」才是这条不变量的测量位置，
两端同表这句话才第一次可失败。

两条拒绝两头都跑：轮廓遮罩打角度针按 `INVALID_MASK` 拒（那句点名「轮廓没有盒可转」；静态那一格
1.164 就拒了），转过角度的盒打宽/高针按 1.164 那句拒。界面只判一次：`maskAnimFields(mask, caps)`
不给路径遮罩角度那一行，引擎没报 `mask_rotation_curves` 时不给那颗 ◇——摆一条导出必拒的针与
藏一条已经能用的曲线，是同一种错的两面。

验证账：`tests/maskrot_check.py` 十节（契约、式子原文、那张图、capabilities 字面量、拒绝两头、
预览清单交的是哪张图、1.163 那一路粘贴属性连着角度、67 个真像素点、窗表与阶梯、边界那一帧），
第 59 份壳检 `tests/desktop_maskrot_check.ts`（名单两端 × 三档形状、落格七种落点、接线字面量、
角度不是第五个 CSS 变量）；`package_check_1165.py` 十四项——冻结引擎自报 1.165.0／schema 21、
它答的图与源码逐字节相同、静态三段 −0.0°／30.0°／−45.0°、那一条阶梯第 1 帧 6.4° 与第 15 帧 90.0°
与它自己下发的窗表逐格对上、末一窗那张图喂进 `app.asar` 里那条 `.masked-picture.rotated-mask`
画出 90.0°／占比 0.1000（同刻导出 90.0°）、装机渲染层七枚 1.165 字面量都在、两条拒绝在包上同样红、
随包两支与 npm 那份同版本同哈希。突变 23 条逐条红在自己那条断言上（引擎 11、界面 12）。

工程 schema 20→21：多的只是那条可打关键帧的属性名与默认 0° 那一格，旧工程读进来一字不改；
带角度针的新工程被旧引擎按版本挡下，不会被读成「一直不转」。


## 1.166 转过的遮罩盒也能动尺寸：一步的 value 是一整个盒

1.165 收下那笔欠账的方式是「每窗一张图」，于是 1.164 那条「转过的盒不许打宽/高曲线」的拒绝就站不住了：
它防的是**一张图被非均匀拉伸**，而现在每张图本来就按那一窗的边烘。做法上只动一处——
`animation.mask_box_schedule` 的一步 `value` 从「一个角度」变成 `(角度, 宽, 高)` 这个元组，
`frame_windows` 的等值合并让这三头天然落在同一批帧边界上；导出按 `axis_steps(schedule, i)` 各串一条
`if(lt(T,秒),数,…)`，预览每窗换一张带自己边的图，参考线也跟着那一窗的边走。

判断口径记一句：这一档能不能交，不看「宽/高针落不落得进库」（那是删一条拒绝，一行代码），
看**落进库之后两端画的是不是同一个盒**。门禁因此钉的是三件事：清单里那条宽/高曲线是
`steps(1, end)` 且逐点等于窗表的数；导出式子里除的那个数就是这份台阶（`*2/(if(lt(T,`）；
拔针之后回到一字不剩。`capabilities.features.mask_rotation_size_curves` 让 Agent 与老引擎各自看得见
这一档有没有——老引擎那一头照旧只给中心两行，界面不摆必被拒的按钮。

schema 仍是 21：存的形状没变，只是校验放宽，旧工程照读；带这种针的新工程落到旧引擎会被那句
「set 遮罩角度 back to 0」整笔挡下，而不是读成一半生效。

这一档真正难的是它差点交不出去的那一次。两端的写法原本是「先按连续算一遍、再把那三个属性整个覆盖成
台阶」，覆盖那一步的循环变量叫 `index`——而 `render.py` 那个作用域里 `index` 已经是这条片段的**输入 pad**。
遮蔽之后第一条层链挂着 1 秒那一路输入去 `trim` 2 秒，画面整幅空掉，而 `GET /v1/frame` 交回的是 200 加
一张空帧——它不是报错，它是「成功地为这一帧画了个什么都没有的画面」。修法不是把那行改名，是把两遍合成
一句判断（这个属性在这一窗走台阶、还是走连续），结构上再没有可遮蔽的变量；同时补了一条与本案无关的
**结构门禁**：plan 里每条以 `[n:v]` 开头的层链，它的 `trim=duration` 必须等于那一路输入的 `-t`。
这条门禁独立有价值：它是「画面没了被伪装成画面就是黑的」那一类里目前唯一抓得住的证据，而那条帧路由
本身还欠一次点名的拒绝（记在停放点的下一轮入口）。

## 1.219（2026-10-20）：转场牌子与针道错开、叫停 FFmpeg 有截止时间、标准 Agent API 接回真引擎

- **这一轮三件事都不是重构，是交付缺陷**。
- **① 时间线上那枚转场牌子压在针道上**（1.218 把夹具装满之后量到的两处，当时只记了数没修）：
  `.transition-badge` 的 `top: 33px` 是照一档行高猜的，行高一变就盖住第一条针（实测牌子 [330,579,31,18]
  与针 [329,582,16,12] 相交）。现在牌子的下缘、高度与最小宽都由 `desktop/src/keyframeLanes.ts` 下发，
  「这一枚压没压在牌子底下」(`underSeamBadge`) 与画它读同一份数；被压住的那枚**不画**，改由「+N」那一格
  报出去——沿用「宁可少画，也不留一枚点不到的针」那条规矩的横向版本。同一处还修了夹针的左端：原来写字面 6，
  比针自己的半宽 10px 小，贴边那一枚有半个盒子被 `overflow: hidden` 裁掉。`+N` 的口径也从「条」改成「枚」。
- **② `JobRuntime._kill` 没有截止时间**：这台机器上 `taskkill` 会不回来，于是「取消」一手把渲染线程钉在
  `finally` 之前，其后的作业全停在「排队等待渲染」，那半截 `.part` 留在盘上（两遍实测：431 s、同样三条红）。
  现在 `KILL_TIMEOUT_SECONDS=10`，等不到就退回 `process.kill()`——要的是「它停了」，不是「哪一种停法」。
  同一类账在 `scripts/build_engine.py`（收进程的 taskkill/WMI 那几手没有截止时间，把 `build_check` 与随包引擎
  那一档钉满整套 2400 s 兜底）与 `tests/packed_engine_surface_check.py`（读 ready 行用裸 `readline()`，
  起不来的 exe 不吐字，门禁不是红而是挂 40 分钟）一起收了：三处现在都有截止时间，红的那一句必须是产品那一件事。
- **③ `agent/` 那一层对外 Agent 的标准 API 一行都没跑通过**：它调 `store.create_project` / `store.apply_batch` /
  `p.id`，而引擎那边是 `create` / `mutate` / `list_projects`（交回 dict）；它那张手抄的 `capabilities` 把转场名写成
  `fade_black`/`flash_white`/`wipe_left`…，引擎那张表里叫 `dip_black`/`dip_white`/`wipe_from_left`…，
  照这份名单写命令的 Agent 一定被拒。现在 `agentcut.capabilities` 就是 `contracts.capabilities()` 那一份
  （同源，不再抄第二份），六只工具逐条走真 store，`AGENTCUT_DATA_DIR` 能把库指开。
  新门禁 `tests/agentapi_check.py` 真起 `agent/server.py`、真发 31 条请求：守卫三条（假 Host 403、外来 Origin 403、
  非 GET 无令牌 401）都拒、名单与引擎那张表逐字相同、旧名绝迹、写涨一个版本、dry-run 与被拒那一手都不写库、
  三类拒绝各有名字，并钉住**用户那个 `data/agentcut.sqlite3` 一个字节都没动**。突变复测：把 `fade_black`
  塞回 `handle_capabilities`，两条各自红在自家断言上，还原后绿。
- **夹具不许说谎**：`tests/ui_shape_check.py` 那三段片段原本是 `4 * 2_352_000` 格＝0.13 秒，默认缩放下整条只画
  8 px 宽，把手、针、转场牌子全挤进同一个 8 px——量出来的「重叠」是夹具自己造的。现在按人真正会剪的数走
  （4 秒一段），并把 `transition.set` 加回夹具：「22 屏 green」必须包括转场在场；扫描还新增一条判据——
  少画的那些针**必须有名字**（`clip-keyframe-more` 在场且写 `+N`），静悄悄少画与点不到同罪。
- **风格账收净**：`agent/` 的 27 条 E501 与另 9 条（E402/F401/E731/I001）一起清掉，`tests/stylewidth_check.py`
  的欠账上限三档全 0，`ruff check src tests scripts agent` 第一次全绿。
- **这台机器上冻结引擎的一条新路**：`uv run --with pyinstaller` 会不出声地钉死（两份实测：23 分钟与 75 s 超时，
  零输出、零 CPU；`UV_OFFLINE=1` 也不救），而 `uv pip install --offline pyinstaller` 0.3 s 就把 6.22.3 装进 venv。
  `build_engine.py` 的 `--no-uv` 这一档现在优先用 `sys.executable -m PyInstaller`，不再依赖刚写出来的那个
  控制台壳——实时杀软下新写的 `.exe` 启动子进程会卡在进程创建里。
- **实测**：71 档壳检全绿；`ruff check src tests scripts agent` 与 `stylewidth_check` 同一轮全绿，欠账上限三档全 0；空闲机单跑 `tests/suite_check.py` **132/132**（这一轮新增 `tests/agentapi_check.py`，31 条断言）；`tests/ui_shape_check.py` 22 屏 `SUMMARY green`——地板 12.5px、0 处尖角、0 处文字被切、0 处控件点不到、0 处同一格叠行、4 屏的「+N」有名（画不下的针都有名字，静悄悄少画也算红）。突变复测两处：把旧名字 `fade_black` 塞回 `handle_capabilities`，「与引擎那张表逐字相同」与「抄错的旧名已绝迹」各自红在自家断言上；把 `timeout=KILL_TIMEOUT_SECONDS` 从 `_kill` 摘掉，`media_check` 那一行先红，不用等四百秒。两轮都还原后绿。
- **发布账**：`build_engine --verify` 通过（这一轮走 `--no-uv`：venv 里的 PyInstaller 6.22.3；`uv run --with pyinstaller` 在这台机器上不出声地钉死，两份实测见 `scripts/build_engine.py` 顶上那段）——冻结引擎自报 1.219.0，冷启动 879 ms、裸启动 705 ms（main.ts 预算 15000 ms），随包 ffmpeg 6.1.1 79.0 MB / ffprobe 4.0.2 60.1 MB / vosk 中文模型 65.1 MB，staged 合计 298.8 MB；`npm run dist` 后根 `AgentCut.exe` 与 `release/AgentCut-便携版.exe` `cmp` 逐字节相同（185,132,959 B，sha256 前缀 929c19bef137f778），安装版 185,293,670 B（前缀 0d00b16693640154）；`released_package_check` 绿（asar 1.219.0、84 个文件、51 句人话、随包引擎就是刚构建那一份）；`packed_engine_surface_check` 绿（包里那支引擎真 HTTP 交回 1.219.0，拒绝那一手不写状态）。

## 1.220（2026-10-20）：检查器展开的那一屏进了门禁，下拉那一行不再被竖切

- **两处小字缺陷是从发布包的真实像素里量出来的**，不是从代码里推出来的：
  ① 走带那一行的「代理」标签在 1480×900 下折成「代 / 理」两行（`.proxy-ctl` 是 inline-flex，
  中文哪里都能断行，于是标签被挤到一个字一行）；② 检查器「工程基色」「折叠曲线」两个下拉把引擎给的
  整句**切在括号中间**——实测 `Rec.709（电视与浏览器的默认）` 要 201 px、
  `BT.709 分段曲线（容器那一格本来的意思）` 要 292 px，而那一格只有 215 px。
- **改法是同一条规矩**（1.217 立的那条）：一格只许一行；画的是**名字**（括号前那一段），
  整句挂在这同一颗控件的悬停上；那一格放不下时学着自己用省略号让位，而不是把字竖切。
  短名只有一处算法：`desktop/src/workingSpace.ts` 的 `shortLabel()`，两只下拉都问它
  （`{value, label, short}`），界面不再各切一遍。括号里那些话下面那行灰字本来就在说，一句都没丢。
- **量具补了它自己看不见的三件事**（这一轮真正多出来的能力，不是产品改动）：
  ① `scripts/ui_shape_probe.js` 以前看不见下拉被切：`<select>` 的 `overflow` 算出来是 `visible`，
  「被切」那一判从来轮不到它。现在按选中的那一行实测要多宽（canvas 量字 + 24 px 箭头与内边距）
  与那一格自己的宽度比，交回 `{label, text, needs_px, box_px, has_title}`；
  门禁的判据是**切了又没有整句悬停 = 缺陷**。
  ② 检查器那九段是 `<details>`，合着的时候那一行根本没画到屏幕上，所以旧 22 屏量不到下拉那一行。
  扫描加了 `--open-details`（把每一段真展开再量一屏），门禁要这一屏：22 屏 → **26 屏**。
  ③ 展开那一屏当场照出第三个谎：「整片对齐 -14 LUFS」那颗按钮被记成「点不到」，而它只是**滚到线
  下面去了**——矩形会撒谎，`elementFromPoint(中心)` 摸到的是隔壁的时间线工具条。判可见现在看
  **中心点**在不在滚动容器那个框里，而不是整块矩形沾边就算；要往下滚一段才点得着的控件，
  本来就不是「被挡住」，这一条不是放宽判据，是把量具读错的东西还给量具。
- **突变复测三处**（各自红在自家断言上，还原后绿）：整句画回 option 且摘掉悬停 → 两档视口各红一条，
  数字就是 292 对 215；只把整句画回去、悬停留着 → `下拉被切=2` 而门禁仍绿（切了但有人说得清），
  这一条同时证明收紧可见性判据之后量具**仍然看得见**那一行；新档 `tests/desktop_tierlabel_check.ts`
  数的是整对出现的次数（option 2 处、select 悬停 2 处），只改一只下拉就红在数目上。
- **实测**：72 档壳检全绿（新增 `tests/desktop_tierlabel_check.ts` 那一档，15 条断言数的是整对出现的次数）；`ruff check src tests scripts agent` 与 `stylewidth_check` 仍全绿、欠账三档 0；`tsc --noEmit` 干净（54 份源）；`tests/ui_shape_check.py` **26 屏** `SUMMARY green`——地板 12.5px、0 尖角、0 被切、0 点不到、0 叠行、4 屏的「+N」有名、**下拉被切 0**；空闲机单跑 `tests/suite_check.py` **132/132**。突变三处各自红在自家断言上、还原后绿：整句画回 option 且摘掉悬停 → 两档视口各红一条（数字就是 292 对 215）；只画整句、悬停留着 → `下拉被切=2` 而门禁仍绿（这条同时证明收紧可见性判据之后量具仍看得见那一行）；新壳检数整对次数，只改一只下拉就红在数目上。
- **发布账**：`build_engine --verify`（`--no-uv`，venv 的 PyInstaller 6.22.3）通过：冻结引擎自报 **1.220.0**，冷启动 **814 ms**、裸启动 705 ms（预算 15000 ms），随包 ffmpeg 6.1.1 79.0 MB / ffprobe 4.0.2 60.1 MB / vosk 中文模型 65.1 MB，staged 合计 298.8 MB；`npm run dist` 后根 `AgentCut.exe` 与 `release/AgentCut-便携版.exe` `cmp` 逐字节相同（**185,132,688 B，sha256 前缀 a7d32323ee3fc1a4**），安装版 185,293,395 B（前缀 a6aabd823065fb00）；`released_package_check` 绿（asar 1.220.0、84 个文件、51 句人话、随包引擎就是刚构建那一份）；`packed_engine_surface_check` 绿（包里那支引擎真 HTTP 交回 1.220.0，拒绝那一手不写状态）。

## 1.221（2026-10-20）：一条片段可以再叠几块遮罩，两端的洞出自同一张图

- **合成工作流剩下的最大一块补上了**：`Clip.extra_masks` —— 主遮罩之外再叠最多
  `capabilities.limits.extra_masks`（4）块矩形/椭圆，与主遮罩**取交集**。之前一条片段只有一个洞；
  AE 的 mask intersect、达芬奇那套 garbage matte 叠加，之前在这里做不到。
- **一处写入口**：`clip.mask_stack` 一次交回整串（与 `clip.mask`、`clip.grade` 同一个规矩）。
  不在服务端猜「第几块要换成什么」，也不给同一份状态留第二个主人；Agent 走同一条命令、同一处校验。
- **两端的洞出自同一张图**：导出那条 alpha 本来就是 `alpha(X,Y)*A*B` 乘起来的，多一块就是多一个括号；
  预览清单为每一块各出一张 `mask_image`，浏览器叠成 `mask-image: 图1, 图2; mask-composite: intersect`。
  界面一份都不自己算，也不在浏览器里再乘一次 alpha——那是第二次换算。
- **做不到的两件事写在格子里**：再叠的块不带动画（那五条 `mask_*` 关键帧说的都是主遮罩；
  要它跟着画面走就把这段复制一层，在那一层上画）；不收自由形状（`INVALID_MASK` 点名拒绝并把
  同一句出路带回正文）。两条都有断言钉着。
- **schema 24 → 25**：新增一个带默认值的字段是一次**指纹事件**，不是一次模型事件——
  `projects._fingerprint` 的年份剥离，加上三处各自镜像「这一年认得哪些字段」的夹具
  （`link_check` / `transition_check` / `text_receipt_check`），四处要一起动；
  只改引擎那一处会把红挪到镜像上去。另有三档门禁把 schema 数钉成字面量（`foldcurve`、
  `workingprimaries`、`maskrot`），跟着一起搬到 25。
- **新门禁 `tests/maskstack_check.py`**：量的不是「字段存进去了」，而是那块多出来的洞**真的把画面切掉了**。
  白底板 + 主遮罩留中间 + 再叠一块留右边，逐点取样：`x=0.65`（两块都留）必须白，
  `x=0.30`（主遮罩里、再叠那块外）**由白转黑**——这一条就是对照，没有它任何「遮罩没生效」的回归
  都会绿着过去。另外钉住：清空回到只有主遮罩、清单里 `extra_mask_images` 的张数与存的一致、
  同一 `request_id` 同一份载荷重发不涨版本、超限与自由形状都点名拒绝且不写状态、
  旧行读回就是没有、提空列表与没提是同一份指纹而真多了一块就必须变。
- **壳检 `tests/desktop_maskstack_check.ts`**：写入口只有一处、额度听引擎的、做不到的那件事写在格子里、
  浏览器叠的是引擎那几张图（不自己乘 alpha）、那一行的圆角与字号仍走刻度。
- **证据的边界（记成欠账，不藏着）**：浏览器那一腿证到的是「两层图 + `mask-composite: intersect`
  被 Chromium 认下来」——computed style 读出 `intersect, intersect`、`CSS.supports` 为 true、
  两张图都来自引擎。**没有**做像素级的两端对比：`msedge --headless --screenshot` 在这台机器上
  不出图（两种写法各实测一次，退 0 但不落文件），而 `get_window_state` 只能拍发布包自己打开的
  那份工程，拍不到临时种子工程。1.222 第 1 项就是先把这个取帧路子补上，再回来钉这一格。
- **实测**：73 档壳检全绿（新增 `tests/desktop_maskstack_check.ts`，钉的是写入口只有一处、额度听 `capabilities.limits.extra_masks`、文案留在格子里、浏览器叠的就是引擎那几张图、`mask-composite: intersect` 与样式刻度）；`ruff check src tests scripts agent` 全绿、`stylewidth_check` 欠账三档 0；`tsc --noEmit` 干净（54 份源）；`tests/ui_shape_check.py` **26 屏** `SUMMARY green`——地板 12.5px、0 尖角、0 被切、0 点不到、0 叠行、4 屏的「+N」有名、下拉被切 0、遮罩后取样 108 个点。突变四手，改的都是**产品**不是断言，各自红在自家那一条、还原后重跑绿：① `render.py` 里再叠那块不再乘进 alpha → 红在像素那条，`x=0.30` 回成白 `(254, 252, 253)`，正是「成片没切」的样子；② `contracts.py` 把那条命令的名字换掉 → 红在写的那一手，`INVALID_REQUEST` 把认得的 op 名单整个念出来；③ `animation.py` 的清单不再交第二张图 → 红在 `maskstack_check.py:206` 那条张数断言；④ `MaskPicture.tsx` 把交集叠成并集（`intersect`→`add`）→ 红在壳检那句「浏览器不再取交集，预览就会比成片露得多」。四手前后每支文件都比对 sha256，全部逐字节还原；空闲机单跑 `tests/suite_check.py` **133/133 checks passed**、`suite_rc=0`——132 变 133 多出来的那一档就是 `maskstack_check.py`（新的壳检 `desktop_maskstack_check.ts` 由 `desktop_ts_check.py` 带着跑，所以那一头的数是 72 变 73）。
- **发布账**：`build_engine --verify`（`--no-uv`，venv 的 PyInstaller 6.22.3，冻结 18.9 s）通过：冻结引擎自报 **1.221.0 / schema 25**，冷启动 **827 ms**、裸启动 711 ms（预算 15000 ms），随包 ffmpeg 6.1.1 79.0 MB / ffprobe 4.0.2 60.1 MB / vosk 中文模型 65.1 MB，staged 合计 298.8 MB（`agentcut/` 159.7 MB、216 项）；`npm run dist` 后根 `AgentCut.exe` 与 `desktop/release/AgentCut-便携版.exe` `cmp` 逐字节相同（**185,134,233 B，sha256 前缀 a70ac94322a8fb22**），安装版 185,294,935 B（前缀 985664a6439709aa）；`released_package_check` 绿（asar 1.221.0、84 个文件、51 句人话、随包引擎就是刚构建那一份）；`packed_engine_surface_check` 绿（包里那支引擎真 HTTP 交回 1.221.0 与 schema 25，拒绝那一手不写状态）。

## 1.222（2026-10-20）：预览那个洞与成片那个洞，第一次被逐点对过像素

- **这一轮补的是 1.221 自己记下的欠账**：那一轮浏览器那一腿只证到 computed style 认下
  `mask-composite: intersect`。式子被解析不等于画出来的东西一样——所以这一轮把两端都落成像素。
- **照片腿找到了**：`scripts/two_end_shot.cjs` 伺服渲染层（同源代理 `/v1` 到引擎）、深链进那个工程，
  用 `--headless=new` 的 Edge 经 CDP `Page.captureScreenshot` 只截 `.masked-picture` 那块矩形。
  这台机器上 `msedge --headless --screenshot` 那个命令行写法退 0 但不落文件（1.221 实测两次），
  而 CDP 这条腿出图——`ui_shape_sweep.cjs` 的 `--shots` 早就在用，只是以前留着给人眼复核，
  没拿来当判据。
- **导出那一片是真跑一次渲染任务**：`POST /v1/projects/{id}/renders` → 轮询 `/v1/jobs/{id}` →
  拿回 `output_path`，再用随包 ffmpeg 取第一帧。两端都解成 rgb24，同一把尺。
- **判据是四件事一起成立**（`tests/twoband_check.py`）：① 两端一个格点都不许分歧；
  ② 每一格还要按几何**该亮就亮、该暗就暗**——四类点（两块都留、只主遮罩留、只再叠那块留、
  两块都外）的期望只由两块矩形的坐标算，不看像素，所以「两端一致地全黑」通不过；
  ③ 对照那一趟（只有主遮罩）里「只主遮罩留」那一批点必须亮；④ 再叠之后同一批点必须在两端
  **同时**由亮转暗。③+④ 才是「量具看得见那块多出来的洞」。
- **量具自己先被验过一遍**：拍照之前先证明那一格值得拍——矩形面积 >0（1.218 量到过 0×0 的遮罩层）、
  图解码完、遮罩层数等于引擎交下来的张数、画面**铺满**格子（`object-fit: contain` 上下出黑边时
  「画面坐标」与「遮罩坐标」会错开一截，那种照片两端比不得），而且不许有遮罩编辑的参考线混进来
  （参考线是界面给人看的，导出里没有它）。离任何一条遮罩边不足 3 px 的点按两端各自的分辨率剔除。
- **抖动重试一次，而且要说出口**：上一趟的浏览器还没退干净时附着会断（实测一次红在
  `[object ErrorEvent]`，那是我自己把 WebSocket 的错误事件原样抛了出来）。改法是把那句换成
  「CDP socket error for <那一页的地址>」，并给照片腿加一次重试——重试了几次必须印出来，
  真缺陷会连着抖两次，静悄悄重试只会拿门禁自己的抖动把它喂饱。
- **量具自己那一摊也得打扫**（这一轮顺手抓到的真缺陷）：`ui_shape_sweep.cjs` 收尾那行 `taskkill /pid … /T /F` 早就在那儿，注释还写着「SIGTERM 打不穿 msedge 那一棵树」——可 1.222 的像素门禁跑完之后，这台机器上查着 **880 个 msedge 进程、146 份 profile** 全活着，而且每一份都是 `agentcut-shape-*` / `agentcut-two-end-*`（不是用户自己开着的 Edge，那一份在 `User Data` 下）。父进程一没，crashpad / renderer / utility 就改了亲，`/T` 再也查不到那棵子树。改法两条：① 杀完必须**验**——profile 目录还删得掉才算那棵树真的没了（进程活着会锁着它），删不掉就报 `LEAKED` 并让退出码红；这一判不是假设，修好之前它当场红了两次，把 `agentcut-shape-1456-808-mvgbtsf5` 那两份点了名。② 按 **profile 目录名**点名杀（`Get-CimInstance` 读 `CommandLine -like '*名字*'`），因为主进程写长路径、子进程写 `ADMINI~1` 那种 8.3 短名，比对整条路径会漏。修完实测：两档浏览器门禁各自跑完`msedge=0`、残留 profile `0`，扫描仍是 26 屏 green；全套重跑 134/134 checks passed、suite_rc=0；那一整套跑完之后机器上 `msedge=0`、残留 harness profile 目录 `0`。
- **实测**：`tests/twoband_check.py` 自己那一趟：两端尺寸 **导出 320×180 / 预览 414×232**，**276 个格点零分歧**，四类点（两块都留 24、只主遮罩留 166、只再叠那块留 4、两块都外 82）每一格都按几何该亮该暗；再叠那块把「只主遮罩留」那 166 个点由亮按成暗，预览与导出同时翻。空闲机单跑 `tests/suite_check.py` **134/134 checks passed**、`suite_rc=0`（133 变 134 多出来的那一档就是 `twoband_check.py`，它在那一整套里只用 8.0 s）；`ruff check` 全绿、`stylewidth_check` 欠账三档 0、`tsc --noEmit` 干净（54 份源）、73 档壳检全绿。
- **突变四手**（每一手都改产品；改浏览器的三手每次都重建渲染层并核对产物哈希真的变了，
  还原后再重建核对回到起手那一份）：① `render.py` 里再叠那块不再乘进 alpha → 红在**像素那一条**：`primary_only` 那 166 个格点两端分歧（导出亮、预览暗）；② `MaskPicture.tsx` 把交集改成并集 `add` → 红在 `mask_composite` 那句（读回 `add, add`）；③ `Preview.tsx` 不再把第二张图交给预览 → 红在照片腿那句「那一格没有画到位」（`mask_layers` 只有 1），重试一次还是这样，报的是「重试过一次还是这样」；④ 最刁的一手：`MaskPicture.tsx` 让第二层重复主遮罩那张图——**层数仍是 2、`intersect` 仍在**，名字与式子都骗过去了，红仍然落在像素那条（同一批 166 个点导出暗、预览亮）。四手前后每支文件都比 sha256 逐字节还原；改浏览器那两手每次都重跑 `npm run build:renderer` 并核对产物哈希真的变了（起手 `e19436aa…`，三手各变一份），还原后再重建、核对产物回到起手那一份。
- **发布账**：`build_engine --verify`（`--no-uv`，venv 的 PyInstaller 6.22.3，冻结 19.4 s）通过：冻结引擎自报 **1.222.0 / schema 25**，冷启动 **847 ms**、裸启动 739 ms（预算 15000 ms），随包 ffmpeg 6.1.1 79.0 MB / ffprobe 4.0.2 60.1 MB / vosk 中文模型 65.1 MB，staged 合计 298.8 MB；`npm run dist` 后根 `AgentCut.exe` 与 `desktop/release/AgentCut-便携版.exe` `cmp` 逐字节相同（**185,134,526 B，sha256 前缀 5365d4e0af2e5fa0**），安装版 185,295,225 B（前缀 b5f658ac0060b9db）；`released_package_check` 绿（asar 1.222.0、84 个文件、51 句人话、随包引擎就是刚构建那一份）；`packed_engine_surface_check` 绿（包里那支引擎真 HTTP 交回 1.222.0 与 schema 25）；`ui_shape_check` 仍 **26 屏 green**（地板 12.5px、0 尖角、0 被切、0 点不到、0 叠行、4 屏「+N」有名、下拉被切 0、遮罩后取样 108 个点）。
- **下一轮（1.223）的具体入口**：
  1. 浏览器侧的 3D 立方表（`lut3d_preview` 仍为 false）——新量具正好能钉它：先把
     「预览与导出读同一张表」钉成逐点比对，再把那张表在浏览器里落成真图。
  2. 把两端比对从**亮暗**升级成**数值**（同一处两端各差多少级）——调色链与转场的预览
     保真度就有一条能量化的账了。
  3. 再叠的块跟着画面走：给 `mask_*` 那五条曲线一个「哪一块」的寻址（契约级改动，
     先把「一条片段一条遮罩路径」这句话印在哪些地方列全）。
  4. 扫描还差的两屏：导出确认弹层第二页、「重置布局」之后那一屏；以及「画面中编辑」的
     参考线、调色链卡片菜单这类「点了才画」的。
  5. 遮罩跟踪仍不估计旋转：要交得出去得先破「NCC 在近平坦的角上选不动」，不是再调步长。

## 1.223（2026-10-20）：两端同色——调色链在预览与导出里差几级，第一次被量出来

- **这一档量的是数值，不是亮暗**。1.222 那条 `twoband_check.py` 只比「洞在不在同一处」，
  二值化够用；这一档问「同一个颜色在两端是不是同一个级」。现有的表级比对
  （`gradelevels_check` / `autograde_check` 把 256 个输入级逐点比过公式）证的是
  「两端拿到同一张表」——**表一样不等于画出来一样**：SVG 滤镜在浏览器里是 8 位中间缓冲，
  FFmpeg 那一路是 `lutrgb` + `colorchannelmixer` 在信号域上直接算，这些都在表比对的下游。
- **板子**：512×288 的 PNG，上面 2/3 是一条 256 级横向灰度斜坡（每级 2 px），下面 1/3 是
  六块饱和色。斜坡量每通道自己的函数，色块量**跨通道**——矩阵把红挪到哪儿，
  灰斜坡是看不出来的（突变那一手证明了这句：红在的是色块，不是斜坡）。
- **链子**装三节：一张 1D 查找表 + 一个 3×3 通道混合 + 一档色阶，编译出来是
  `['lut', 'matrix', 'lut']` 三种形状都在同一条链上，顺序也有意义。
- **两档容器各比一遍**（`dpx-sequence` 与 `h264-source-quality`）。这不是冗余：
  DPX 是 RGB 三平面 10 位、没有色度二次采样，H.264 是交付那一档。
  实测两档容器上「预览 vs 导出」的最坏值一样（4 级），而**导出对自己那张表**的差
  只有 RGB 那一档 ≤1 级、YUV 那一档到 4 级——那 4 级是编码器自己的（两次矩阵 + 一次 4:2:0），
  不该记在调色链头上，所以「导出贴表」这一判**只对 RGB 那一档**成立。
- **第三把尺**：把清单里那串编译好的阶段在浮点上自己走一遍。两端互相一致不等于两端都对；
  只有第三把尺能分清哪一端是异类。量出来：导出贴着它（≤1 级），预览那一格差 3~4 级。
- **平色那一趟把「滤镜的锅」与「量具的锅」分开了**（同一轮补的，`--strip`）：把**产品自己那张
  滤镜**贴到一排平色块上拍回来——输入是一整块平色，没有任何缩放掺进来。量出来最差 **2 级**
  （8 级画成 (19,0,6)，表算的是 (21,0,6)；七格全在 2 级以内）。同一张滤镜、同一把尺，
  斜坡那一趟是 4 级——**多出来的那 2 级与「512 宽的画面被画到 ~414 宽」同时出现**，
  所以 1.223 头一版记的「预览保真度差」不是滤镜的缺陷：滤镜已钉在 ≤2 级，
  斜坡那一判仍按实测的 4 级钉住（往上涨就红），但**它含着一份量具的取样几何**，
  这一句写在这里，不让它被当成产品的账。哪一步（缩放核、取样点落在台阶哪一侧）
  贡献了那 2 级，还没量清——量清了才许把斜坡那一判往下压。
- **容差是量出来的，不是拍的**：两端 ≤4 级（777 个通道值 × 两档容器里最坏的那一个），
  导出对表 ≤2 级（8 位量化每段最多 1 级，两段给 2）。
- **新门禁 `tests/twobandlevel_check.py` 的实测**：`tests/twobandlevel_check.py` 自己那一趟（斜坡 8~248 级 + 六块饱和色，每档容器 777 个通道值）：**DPX 那一趟**两端最差 4 级（在斜坡 8 级 b），导出对自己清单里那串阶段最差 **1** 级，预览对表最差 4 级（斜坡 8 级 r）；**H.264 那一趟**两端最差 4 级（斜坡 20 级 b），导出对表最差 4 级——那 4 级是编码器自己带的（两次矩阵 + 一次 4:2:0），所以「导出贴表」这一判只对 RGB 那一档成立。空闲机单跑 `tests/suite_check.py` **135/135 checks passed**、`suite_rc=0`（134 变 135 多出来的那一档就是 `twobandlevel_check.py`，它在那一整套里只用 5.6 s）；`ruff check` 全绿、`stylewidth_check` 欠账三档 0、`tsc --noEmit` 干净（54 份源）、73 档壳检全绿。
- **突变那一手**：一手，改的是产品里那九个数字：`Preview.tsx` 画 `feColorMatrix` 那一行换成恒等矩阵——**原语还在、阶段数没变、清单里那串还是 `['lut','matrix','lut']`**，任何「数一数有没有这个原语」的判据都看不见它。重建渲染层、核对产物哈希真的变了（起手 `e19436aa…` → `87408945…`）之后，这一档当场红：DPX 那一趟 15 个取样点超容差、H.264 那一趟 14 个，**最坏 18 级**，而且红的位置全在饱和色上（`色块 3 通道 0` 导出 (21,250,251) 对预览 (3,255,255)）——正是设计色块要抓的跨通道那一半。还原逐字节相同、再重建核对产物回到起手那一份、门禁重跑绿。
- **发布账**：`build_engine --verify`（`--no-uv`，venv 的 PyInstaller 6.22.3，冻结 18.0 s）通过：冻结引擎自报 **1.223.0 / schema 25**，冷启动 **765 ms**、裸启动 676 ms（预算 15000 ms），随包 ffmpeg 6.1.1 / ffprobe 4.0.2 / vosk 中文模型，staged 合计 298.8 MB；`npm run dist` 后根 `AgentCut.exe` 与 `desktop/release/AgentCut-便携版.exe` `cmp` 逐字节相同（**185,133,638 B，sha256 前缀 84ab1ca95b759c82**），安装版 185,294,344 B（前缀 7ddc279e47056b72）；`released_package_check` 绿（asar 1.223.0、84 个文件、51 句人话、随包引擎就是刚构建那一份）；`packed_engine_surface_check` 绿（包里那支引擎真 HTTP 交回 1.223.0 与 schema 25）；`ui_shape_check` 仍 **26 屏 green**（地板 12.5px、0 尖角、0 被切、0 点不到、0 叠行、4 屏「+N」有名、下拉被切 0、遮罩后取样 108 个点）。
- **顺带量到的机器事实（1.224 的头一项有指望了）**：浏览器侧的 3D 立方表**不是**做不到——
  这台机器上的 headless Edge 报 `WebGL 2.0 (OpenGL ES 3.0 Chromium)`、
  `MAX_3D_TEXTURE_SIZE = 2048`，一张 64³ 的 RGBA8 立方体 `texImage3D` 传得上去，
  片元着色器采样回 `(126, 62, 190)`（与按纹素中心算的期望一致），
  而且**加不加 `--disable-gpu` 都一样**（软件渲染那条路也通）。
  Help 里那句「3D 表按定义跨通道，浏览器没有能画它的原语，所以预览不生效」
  在 WebGL2 面前已经不成立了——但它要换成一句新的话：原语有了，**两端同不同色**还得量，
  而这一档的量具正好能量它。
- **下一轮（1.224）的具体入口**：
  1. 先修这一轮量到的那 3~4 级：查浏览器那一路是表插值语义还是 8 位中间缓冲吃掉的，
     修完把这一档的容差往下压——容差是量出来的，改小它要带着新的实测。
  2. 浏览器侧 3D 立方表（`lut3d_preview`）：WebGL2 那条路已实测可行，
     先把「预览与导出读同一张表」钉成逐点比对（这一档的尺直接复用），
     再决定 tetrahedral 还是 trilinear——两端必须同一档，否则又是一处「只有一端能执行」。
  3. 再叠的块跟着画面走：给 `mask_*` 那五条曲线一个「哪一块」的寻址（契约级改动）。
  4. 扫描还差的两屏：导出确认弹层第二页、「重置布局」之后那一屏。
  5. 遮罩跟踪仍不估计旋转：要交得出去得先破「NCC 在近平坦的角上选不动」。
