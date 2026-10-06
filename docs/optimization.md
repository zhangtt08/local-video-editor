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

1. 精确剪辑：J/L cut 与四点剪辑仍待实现；涟漪修剪、滚动剪辑与拆分内嵌音轨已完成。持久组合、手动音画链接、多选与复制粘贴已完成；链接要求先对齐位置/时长/速度，不自动分析波形，原视频仍按自身音量播放。剪贴板和素材标记目前仅本次应用会话，尚未跨重启保存。跨工程不同帧率不自动转换；大量新素材/轨道超出 100 条批命令须分组粘贴或先登记素材。20,000 片段是契约上限，尚未验收同等规模的界面性能。
2. 常用成片：更多转场类型与联动音画、曲线变速/冻结、自动语音字幕、字幕样式与批量字幕编辑。
3. AE 合成：数值曲线编辑器已完成；自定义贝塞尔手柄、速度图、多点编辑、路径遮罩/动画、嵌套合成、混合模式、跟踪、效果栈与常见动效。
4. 达芬奇工作流：色轮/曲线/LUT、示波器与色彩管理、专业混音、代理与缓存回放。
5. 真实生产验收：用户的长项目与素材格式、4K 多轨性能、项目备份/打包迁移、更多导出格式、快捷键预设与签名发布。

现阶段适合基础剪辑、画中画、字幕与基础动画；仍不足以覆盖 AE / 剪映 / 达芬奇的全部生产用途。


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
