# AgentCut 协作规则

本项目已交付成品：Python 剪辑引擎 + HTTP/MCP 接口 + Windows 桌面客户端（无边框一体化窗口，见 `desktop/`）。
`README.md` 的「已完成」表是当前事实来源；关键帧、曲线变速与冻结帧、淡入淡出（1.90 起是片段两条边上的窗口 `Clip.fade`，渲染时乘进那条属性曲线：两头共存、不抹掉闪避或手敲的音量点、跟着修剪与分割走；1.91 起时间线上有真正可拖的淡角柄（选中片段后两边各一个，让开最外 7px 的修剪边；能淡哪几头只由 `fadeProperties` 判一次，检查器与角柄共读；上限与检查器同源 `fadeRoom`，所以拖不出引擎必定拒绝的长度；1.92 起拖一次淡的是整组——被拖的那条、一起选中的、以及音画链接的伙伴，各自按自己的长度夹，额度满了的那条整个跳过而不是清成 0）；界面那两行读工程状态，额度只有「片段长度减对面那头」一处来源；1.95 起每条属性还有一个形状（线性 / 缓入 / 缓出 / 缓入缓出，默认就是原来的 smoothstep，老工程一字不差），它不是新算术——淡本来就是一条分段曲线，形状就是那条斜坡用哪种插值，导出与预览读同一份点表，淡出按时间反演镜像；`clip.fade` 可以只带形状不带长度；名字由 `capabilities.fade_shapes` 下发，界面不许自备四个字符串；1.90 之前写在曲线里的老淡照旧渲染，1.96 起可以一条 `clip.fade_adopt` 把它搬成窗口——只认当年那条「从边上的 0 缓到这条属性的静止值、插值全是 ease、属性上没有别的点」的形状，窗口从实际点位置读出（两条斜坡互相越过也搬得动，`in + out <= duration` 由构造保证，所以不需要第二条拒绝），搬完必须删掉被搬走的关键帧，否则同一条淡被乘两次；不符合的一条都不猜，`FADE_ADOPT_SHAPE` 把看到的关键帧逐条交回 `details`，检查器那一行下面据此给「搬成边窗口」按钮；1.97 起整轨一次搬完（`timeline.fade_adopt_track_plan` 逐条调的就是 `_fade_adoption`，所以规划与写入不可能分家；只读路由 `POST /v1/projects/{id}/tracks/{tid}/fade-adopt` 与 MCP `track_fade_adoption` 交回普通命令表，`apply=true` 把它们交成一个批次，一整轨只涨一个 revision；这条属性上没有关键帧的片段根本不出现在报告里，音频上的 opacity 被跳过而不是排成一条必被拒的命令；`422 FADE_ADOPT_NONE` 是没东西可搬时唯一的说法），界面那颗「整轨搬成边窗口」的中文报告走 `FADE_ADOPT_REASONS` 表——键就是引擎那句原话，`tests/fadebatch_check.py` 把两边的句子对起来）、文字字幕、基础调色与串行调色节点（含节点强度 Mix 与每通道混合方式、并联分支节点）、镜头转场（1.59 起九种：叠化/淡黑/闪白 + 四向擦除 + 两种缩放，清单由 capabilities.transition_kinds 下发；1.94 起十三种，多了四种推移 push_from_left/right/top/bottom——整层位移、两层朝相反方向走所以永不重叠，预乘相加不会双计；「滑动」故意不做，它需要一条画面空间的互补 alpha（实测两层一叠就把 (192,32,32) 与 (32,32,192) 叠成 (222,61,220) 的亮边）；同一版还还掉了预览欠的账：擦除过去在浏览器里只是瞬间切换，现在按引擎下发的轴/方向/羽化宽走 clip-path 的中点，推移与转场放大走另外的嵌套包装）、多选组剪辑、持久组合与手动音画链接、嵌套合成（1.74 起九个分析入口按 `sequence_id` 也进得了合成内部：去空白、整轨去空白、统一响度、整轨响度、自动闪避、画面稳定、遮罩跟踪、主体跟随、自动字幕；1.83 的自动调色是第十个，同一条路已用真实 MCP stdio 量过）、自由路径遮罩、矩形/椭圆遮罩关键帧动画、路径遮罩关键帧动画（1.102 起遮罩坐标在导出侧也按**画面框**折算——`alpha_expression` 收 `(偏移x,偏移y,画面宽,画面高)` 把 `X/W` 折进去，自由路径的板子按画面尺寸光栅化后用 `pad=out_w:out_h:bar_x:bar_y:color=该遮罩的中性值` 垫成帧；`contain` 补边交付时形状不再被帧比例拉长、不再滑出画面带，同比例交付的编译串一字未改；1.50 起按曲线整体搬动，形状与尺寸仍按画好的轮廓）、画面里拖遮罩即打关键帧（1.51：有曲线时向导仍在，拖框写当前播放头关键帧，拖路径顶点只改轮廓；1.52：向导还按曲线的尺寸一起缩放，角柄就在看到的边缘上；1.53：轮廓本身可整条拖动，有中心曲线时写成播放头关键帧；1.54：双击加点插在离得最近的那条边上并按贝塞尔精确分裂，不再往顶点列表末尾追加；1.55：路径顶点上限由 `capabilities.mask_vertex_limit` 下发，界面不再自带数字；1.56：选中顶点后画面给出删除/角点/平滑三个操作，到上限时说明原因）、遮罩跟踪（单目标平移与缩放，短遮挡按匀速续跟；路径遮罩只跟平移；1.72 起 `merge` 默认只重写本次窗口的点，跟丢之后可以把遮罩挪回主体上「接着跟」，前面跟好的路径不再被整条抹掉；1.85 起被挡住的那段时间每一帧都在 1/4 尺寸的整幅画面上重新找目标，找回后把猜的那段按两次真实 sighting 校正，回复报 `reacquired_at_ticks` 与 `gap_closure`，猜窗默认 60 帧、上限由 `capabilities.limits.track_max_gap_frames` 下发；1.86 起分析的步长跟着 `clip.speed_percent` 走（唯一说法是 `speed.analysis_rate`），恒定速率的片段量的就是它真正播的那些帧，回复写 `speed_percent` 与 `sample_rate`；1.87 起遮挡猜窗长度与「满画面重找」在检查器里有控件（上限仍只由 `capabilities.limits` 下发，界面唯一的字面量是引擎没回该字段时的兜底），1.88 起「这一次量几帧」只有一个判断与一处数字来源（`effects.ts` 的 `trackWindow`，上下限是 `capabilities.limits.track_min_frames` / `track_max_frames`，与 `MaskTrackRequest.frames` 同源）：够得着就量到片段结尾，量不完就在提示里说清还剩几秒、是被单次上限还是被这条片段的曲线预算收短的（一个带尺寸的跟踪点占 4 条曲线，`Clip.keyframes` 的上限由 `timeline.mask_track_capacity` 从契约字段的 `max_length` 元数据读，与 reframe 的预算同一个读法；收不动了回 422 `MASK_TRACK_BUDGET` 交出 `details` 里的五个数，reducer 对手搓的超预算路径同样点名拒绝），怎么「接着跟」，播放头之后不够最低帧数时按钮是灰的并写明出路；1.93 起那三个旋钮（挡住最多猜几帧 / 满画面重找 / 遮罩随远近缩放）记在应用偏好里，换一个工程、重开一次窗口都还在——有意不写进工程状态：元数据那条路每点一次就涨一个 revision 并清空撤销栈，等于拿编辑历史换一个勾选；1.89 起被曲线预算收短的那支提示不再指一条引擎必定拒绝的路（装满 2000 条曲线的片段容量为 0，「接着跟」必回 `MASK_TRACK_BUDGET`），改说「关掉遮罩随远近缩放再从头重跟」或「切成两段分别跟」这两条实测走得通的出路，画面稳定的锚点显式 `reacquire=False`，因为一次剪辑不该被读成相机平移）、静音检测与去空白（单片段与整轨）、响度表与统一响度（单片段与整轨；1.79 起 MCP 也有 `clip_loudness`/`track_loudness`/`track_silence` 三个同规格只读工具，空轨道与数字静音的拒绝点名）、自动语音字幕（1.61：本地 vosk 模型听写，走 captions.import 落轨，内容寻址 id 防叠轨，replace_track_id 原位替换；合成里的听写已用真实语音与真实导出端到端量过，见 `tests/captions_comp_check.py`）、时间线标记与按标记分割、源画面划动与左右滑移、色彩空间转换节点、自动闪避（口播压配乐，写成音量关键帧）、分析类拒绝点名（1.75：九条分析路由的每条拒绝都带 code、可读句子与非空 details，NOT_FOUND 必点片段/轨道/合成/素材，拒绝不涨 revision，dry 与提交同答）、读路由同样点名（1.76：15 条 GET 的 404/410 各带回它收到的 id，未知的工程 id 不再回 200 空列表）、操作类路由同样点名（1.77：导入失败给 path/suffix/媒体夹，`.cube` 被拒给行号与行数）、片段柔焦（1.64：`effects.blur` 是画面高的比例，同一个半径同时喂 FFmpeg `gblur=…:steps=6` 与浏览器 `filter: blur(…cqh)`，配遮罩即打码/背景虚化；1.98 起它能打关键帧，走的不是那六个标量属性那条式子——`gblur` 的 sigma 不读表达式，所以 `animation.spatial_schedule` 把曲线编译成整帧对齐的常值窗（段数上限由 `capabilities.limits.blur_schedule_segments` 下发，同值相邻段合并，每段取段中点的 `sample`），导出串成多个 `gblur=…:enable='between(t,a,b)'`，1.100 起半径的基准是**画面在交付帧里占的那段高**（`render.picture_height`：`contain` 补边时小于帧高、`cover`/`stretch` 就是帧高），与预览那条 `blur(…cqh)` 量的是同一件事——此前它除的是 `out_h`，于是 16:9 工程导竖屏/方画幅时成片比预览糊了近一倍，64 px 实测带也按帧判出「界面允许、导出会拒」；预览动画的是同一次 `preview_manifest` 里 `spatial.blur` 那份点表（`steps(1, end)`）——阶梯是两端共用的那一份，不是导出偷偷退化；有曲线时 `color_filter` 里不写静态 `blur(…cqh)`，unsharp 挪到 `edge_filter` 才保住「调色 → 柔焦 → 边缘」的同一顺序，没有曲线的片段一字不变；1.99 起动画曲线编辑器的属性列表里有「柔焦」——这一项进不进得了由 `capabilities.features.blur_keyframes` 决定，纵轴仍是画面高的百分比，上下限是 `blur_fraction` 与 `blur_radius_px` 按当前画幅折算出的同一条带（界面唯一的字面量是引擎没回字段时的兜底），「播放头添加」、数值框、拖动写的都是每个属性同一条 `keyframe.set`/`keyframe.move`，客户端不为柔焦另写一套剪辑规则；1.109 起曲线的针落在**片段自己的帧边界**上——`desktop/src/keyframeSnap.ts` 的 `keyframeTick` 收的是片段本身而不是一个刻度数组——这一条按 1.110 的实测口径写：引擎的逐片段不变量（timeline.py:247）会按 `TIME_NOT_ALIGNED` 拒掉停在两帧之间的片段，所以今天格线的相位恒为 0，按片段位置算格子是**构造上的正确**而不是修好的可见缺陷；实测可见的那一半是 `keyframe.set` 不查刻度对齐，Agent 写在两个帧之间的针是合法的，拖动把它落回整帧，除格线外还吸附播放头与这条曲线上没被拖动的针，容差是 4 个屏幕像素所以放大八倍就窄八倍；数值框、「播放头添加」、点空白移播放头三个入口 `attract=false` 只认格线，上下界在吸附之后才夹，所以吸附不会把点送到 reducer 必拒的地方，而命令语义一字未改；1.113 起时间线上的针**按属性分道**——实测过同一秒上两枚针的矩形完全相同、其中一枚 `elementFromPoint` 根本点不到，现在 `keyframeLanes.ts` 的 `needleRows` 按属性第一次出现的顺序分道、`laneCapacity` 按像素算画得下几道，画不下的属性不叠回去而是少画，改成一枚写明「+N / 少了哪几条」的牌子，点它进这条片段的动画曲线；1.114 起同一个抓取按住 Alt 就是复制一枚（`planKeyframeDrag` 的 `duplicate` 分支出来是普通 `keyframe.set`，原针不动、影子跟指针、落在别人身上按「复制得先找个空格」说法拒绝，历史里「复制关键帧」与「拖动关键帧」分得开）；1.115 起界面说到某条动画属性时念的是中文名——`desktop/src/effects.ts` 的 `FIELD_LABEL` 是唯一那张表（检查器关键帧列表 1.65 起就在读它），现在时间线上针的悬停说明与无障碍名、「+N」牌子列的缺谁、撞针那句红字、复制／粘贴的提示、插值下拉的无障碍名都从它出去，契约 id 不再出现在用户眼前；`tests/desktop_keyframename_check.ts` 把这张表的键与 `contracts.py` 里 `EffectProperty`/`MaskProperty`/`SpatialProperty` 三条 Literal 对齐（引擎多一条没起名、界面留一条旧名、两条同名都会红），并且不许任何视图自带第二份名字表；同一版还量到 1.113 那枚「+N」牌子点了没反应——它的 pointerdown 被片段根节点的拖动手势吃掉，`onClick` 执行不到，写在 tooltip 里的那条出路是空的，现在牌子自己收下这次按下，门禁断的就是这层交接；1.116 起同一个抓取多了一只手：按住 Alt **点一下**（移动不到两像素）就是删掉这一枚针——交出去的仍是普通 `keyframe.remove`（刻度按片段本地，与 `keyframe.move` 同一口径），走带 `expected_revision` 的那条链，撤销一次回一枚；撞针那句拒绝因此不再把人支到动画曲线，而是当场说「按住 Alt 点掉那一枚」。Alt 拖是复制、Alt 点是指哪删哪，两只手共用同一个 `duplicate` 判断，引擎、契约、HTTP、MCP 一字未改；1.110 起时间线上那枚菱形可以直接横向拖——`keyframeDrag.ts` 复用同一份 `keyframeSnap` 几何（绝对帧格子、屏幕像素容差、找播放头与同属性邻居），交出去的是片段本地刻度的普通 `keyframe.move`：`animation_offset_ticks` 只折一次、值与插值与控制柄原样带走、同属性占格在松手前就点名、松手回原格就是一条命令都不发，所以既没有新命令也没有新错误码；用 1.110 的 exe 在 Chromium 里真拖一次还量出两处只有几何能暴露的缺陷并修掉了：贴边的针被 7px 修剪边盖住（菱形提到 z-index 5，修剪边仍管上面那截），以及画在离边 6px 的针被抓住时会瞬移到画出来的时间（现在按下时记住抓取偏差）；1.111 起吸附只剩一处开关——曲线编辑器的「时间吸附」读的就是时间线磁吸那份持久偏好 `EditPrefs.snap`（复选框走 `prefs.setSnap(目标值)`，渲染之外走 `editPrefs()`），偏好仍只在 localStorage 而不进工程状态（元数据每写一次就涨 revision、清撤销栈，同 1.93 的口径）；1.112 起这条属性上的节奏可以 Ctrl+C / Ctrl+V 搬走——`keyframeClipboard.ts` 只算出该发哪些普通 `keyframe.set`（一次批次一个 revision），一次只搬一条属性、越界与撞针逐枚跳过并报数、复制记着工程 id 换了就失效、撞针按**片段本地**刻度判（已有的针存的是含 `animation_offset_ticks` 的时钟），落点走 `alignTime(head, false)` 所以粘在播放头的整帧上但不去找邻针、片段降噪（1.78：`effects.denoise` 0–24 dB 一个旋钮，导出加 `afftdn=nr=<db>:nf=-30`，浏览器预览不降噪、界面明说）、片段清晰（1.65：`effects.sharpen` + `effects.sharpen_radius`，两端跑同一条 unsharp 式子 `源 + 量×(源 − 高斯)`，导出用 `split`+`gblur=…:planes=7`+`blend=c*_expr='clip(…,0,255)'`、浏览器用 `feGaussianBlur`+`feComposite arithmetic`，半径与柔焦共用同一条 1–64 px 实测带）、画面稳定（1.66：`POST /v1/projects/{id}/clips/{id}/stabilize` 与 MCP 的 `clip_stabilize`，四个画面锚点的互相关中位数 = 相机位移，减去滑动平均后反向写成 `x`/`y`/`scale` 关键帧，缩放按 `1+2·最大抵消` 盖边、`max_crop` 夹住并如实报告，`strength=0` 一个关键帧都不写；图超过 12 KB 时 `-filter_complex` 自动改走 `-filter_complex_script`；1.67 起同一次测量还用四锚点的 Arun 刚体拟合出相机滚动，反向写成 `rotation` 并按 `1+2·平移+弧度·画幅比` 盖边，低于 0.25°（一个锚点像素的量化）的死区不写；1.86 起采样步长跟着播放速度走（`stabilization.sample_rate` 如实写着比值），所以恒定速率的片段也能稳定，带变速曲线的仍拒绝（没有单一比值可用），界面 `stabilizeBlocked` 守同一条判断；1.68 起对已经带 `x`/`y`/`rotation`/`scale` 关键帧的片段再稳定会被点名拒绝 （`STABILIZE_CONFLICT`，details 点名是哪几条曲线），因为抵消是叠加的，界面按同一条判断先把按钮灰掉并写明出路；1.69 起稳定是片段的一处状态（`Clip.stabilization` 记下强度/点数/抵消量/放大，与曲线同一条批次落库），带记录的片段再按一次是从静态变换**重算并替换**（换强度只要一次点击，同 id 同载荷重新命中回执），强度 0 就是取消稳定，带记录期间 `clip.speed`/`clip.speed_curve` 与 `clip.reframe`（1.70：重构图整条改写同三条曲线）都以 `STABILIZE_LOCKED` 拒绝——抵消是一帧源画面对一个关键帧量的，这是 1.68 那条守卫的镜像洞；1.71 起这条记录是可作废的——`apply_commands` 收尾时若那四条曲线一条不剩就把记录置空，界面与两把锁随之松开）、色阶节点与自动调色（1.83：`levels` 节点是输入黑场／白场＋中间调 gamma，可按通道，仍然是每通道函数，所以链子照旧塌成一张表，256 个输入级逐一比过导出与预览；`POST /clips/{id}/auto-grade` 与 MCP `clip_auto_grade` 读片段自己的帧量百分位黑场白场，写回一条普通 `clip.grade`，再按一次是重算顶替而不是叠一层，量不到画面的按钮是灰的）、标记拖拽移动与改名换色、交付画幅预设与三种适配（补边/裁切/拉伸）、时间线入出点区间与区间导出（裁剪发生在混音与母带处理之后）、四点剪辑（素材入出点 + 时间线入出点四个整数一次解算成一条命令，源长则裁尾、源短则整数百分比改速）、交付方案持久化（预设+适配+范围+文件名存成工程状态 `Project.recipes`，v12）、安全区参考线（`settings.safe_area` 三态，内缩数字只由 `capabilities.safe_area_insets` 下发，纯显示不改导出）、主体跟随重构图（按渲染时钟采样跟好的遮罩路径，换算成 `x`/`y`/`scale` 三条关键帧并在片段的关键帧预算内自适应补点，一个批次一个 revision，跟不到时如实报告夹住的点数与实测最大偏离；1.73 起稳定的关键帧预算也按片段剩余空间自适应抽稀并说明（不再回空的 `PROJECT_LIMIT`））、调色节点图（链子画成输入→节点卡→输出的连线图，拖卡片改顺序仍只写 `clip.color`，无新状态）、批量交付（一次点击多个画幅，整批先编译通过才入队）、交付格式（1.57：mp4/H.264 之外新增 mp4/HEVC+hvc1、webm/VP9+Opus、mov/ProRes 422 HQ+24 位 PCM，容器/编码/采样格式与文件名后缀都由预设一处决定，采样格式走完整条画面链）、纯音频交付（1.58：mp3/wav/flac 三条预设，`codec=null` 让画面链整段不编译，无声时间线按名字拒绝）、交付前复检（1.60：FFmpeg 退出 0 之后，任务用**同一个 FFmpeg 旁边**的 ffprobe 重开产物文件，比对容器、两路流是否齐全、时长（容差 `max(0.150 秒, 两帧)`）并把结尾 0.5 秒解码一遍，不合格就销毁候选文件、以 `OUTPUT_INVALID` 失败且最终名一次都不出现；旁边没有 ffprobe 时照常出货但 `output_checked=false` 并在消息与界面明说未经复检）、母带响度目标与母带限制器（探测渲染量整片混音后写母带增益，真峰值交给 alimiter）、代理回放与缓存配额已实现（1.44 起配额覆盖整个派生缓存：缩略图 + 波形 + 代理，按最久未用整项淘汰、可 dry_run 预演、缺失自动重建；1.80 起这一族与「看成片某一帧」在 MCP 也有同语义工具 `media_cache_read`/`media_cache_prune`/`media_proxies_prune`/`preview_frame`，Agent 能自己确认画面变了没有）；多目标跟踪（长时遮挡 1.85 已能重新找回）、色彩节点图的分层与连线（线性光里的色域矩阵与色彩管理、图层节点的连线与第二路输入；3D LUT 已于 1.103 实现：`.cube` 的 `LUT_3D_SIZE` 由 `/v1/lut/parse` 认出来回 `kind=lut3d`，节点自带 `size³×3` 个格点（超过 17³ 按三线性重采样并留 `resampled_from`），像矩阵那样自成阶段、打断每通道的合并，导出走 `lut3d=file=…:interp=tetrahedral`；浏览器画不出立方体，所以 `features.lut3d_preview=false`、节点上既无 mix 也无 blend，界面写「预览不生效、导出生效」——不给只有一端会执行的强度；界面读的 `preview_grade` 按 `preview:false` 把立方阶段整个拿掉，所以预览不会为它画一个没有数字的原语；1.104 起这份表的存在代价收到一处总量管控：`GRADE_INLINE_SAMPLE_LIMIT`（20 万个采样点，约 1.4 MiB 工程 json）经 `capabilities.grade_limits.max_inline_samples` 下发，`grade_inline_samples()` 按真实载荷数（并联两支各算、停用的仍占地方、嵌套合成也算），reducer 在候选状态上**只拦增长**——已经超额的工程不被冻成只读，拒绝带 `GRADE_INLINE_BUDGET` 与 `samples`/`limit`/`worst_clip_id`/`worst_clip_samples`；1.105 起这个数在写之前就问得到：`GET /v1/projects/{id}/grade-capacity` 与 MCP `grade_capacity` 交回 `samples`/`limit`/`room`/`clips_with_tables`/`worst_clip_*`/`by_clip`/`nested_samples`，它坐在 reducer 用的同一个 `grade_inline_samples()` 上，所以读到的与被拒时看到的不会是两回事（`capabilities.features.grade_capacity` 下发；1.107 起检查器那一行读的就是这份回执，「还放得下几张」由引擎除——`room_cubes`/`room_tables`/`cube_samples`/`table_samples` 都在回执里，渲染层只按 revision 决定要不要显示、把字段填进句子，不做第二次除法））仍待实现（跨通道的求值已经能两端对齐：1.84 的 `matrix` 通道混合节点让链子从「每通道一张表」变成「有序阶段列表」，连续的每通道节点仍合并成一段，导出走 `colorchannelmixer`、预览走 `feColorMatrix`，两端读同一份九个数；1D `.cube` LUT 已于 1.62 实现：文件只由引擎 `parse_1d_cube` 解析一次，界面「+LUT」与 Agent 的 `POST /v1/lut/parse`、`lut_parse` 是同一条路，链子上限走 `capabilities.grade_limits`，超过 1024 行的表重采样并在回复里写 `resampled_from`；1.63 起文字层有字体（本机实际装着的face 由 `capabilities.text_fonts` 下发，缺字体按 `FONT_UNAVAILABLE` 拒绝）、横排对齐、描边、硬阴影、垫子颜色与浓度、行距，全部按「字号的百分之几」同一组数喂 drawtext 与 CSS，1.101 起这组数里的「百分之几」在导出侧量的也是**画面在交付帧里占的那段高/宽**（`render.picture_size`，与 1.100 柔焦同一次计算），竖屏补边时字幕不再压进黑边、不再按整帧放大；drawtext 画不出模糊所以界面也不给这一档），不能声称全面替代 AE / 剪映 / 达芬奇。

## 当前停放点（1.143）

- 1.143 是**装机复核真点出来的一个只有点得到才看得见的缺陷**。这一轮不再是读发布包字节：把
  `app.asar` 里取出的渲染层起在 headless Edge 里，用 CDP 选中 OpenEXR 预设、点「开始导出」，
  再回引擎数文件。行为全对（时间码栏 `disabled`、后缀 `.exr`、发出去 `timecode=None`、
  落盘 60 帧、消息写着「共 60 帧…首尾两帧都解得开」）。但同一次点抓出来的是：
  `desktop/src/ui.tsx` 的 `Field` 只把 `hint` 写进 `<label title=…>`——**不悬停就一个字不显示**，
  所以 1.142 那三句话在屏幕上其实不存在。补了一行只在选了序列时出现的可见字
  （`<p className="hint">`：一串文件／声音不在里面／起始时间码也进不去，并点名「再交一份 mp4／mov」那条出口）。
  门禁跟着加严：壳检现在**同时**断「`Field` 的 hint 仍然只是 tooltip」（这条是必须有另一行的凭据）
  与「那一行确实出现且带出口」，发布包可见句子表加两条，4 条变异逐条红在自己那条断言上
  （整行删掉／出口不点名／不说声音／`isSequence` 换成 `alpha`）。教训写死成习惯：
  **界面的说明如果只住在 tooltip 里，就等于没有说明**；验收要在装机那一层读 `innerText`，
  而不是读源码里的字符串。

- 1.142 加的是**开链交付**（image sequence）：预设表从 18 条长成 20 条，新增 `exr-sequence`
  （OpenEXR，`rgba64le`，16 位带 alpha）与 `dpx-sequence`（DPX，`gbrap10le`，10 位带 alpha），
  `_preset` 多了一个 `sequence` 键，能力表多下发一份 `sequence_presets`——界面与 Agent 读同一张表，
  不许谁自己列。
  **一串文件没有容器**，所以两样东西无处安放，都点名拒而不是「收下之后再什么都不做」：
  起始时间码回 422 `SEQUENCE_NEEDS_CONTAINER`（那句中文要说清「帧号就是位置」并指出 mov／mp4／
  mxf／webm 那条出口），声音则连 `-map [aout]` 都不发出去、`-an` 明写。实测这一拒**一个文件都不落**
  （编译在占目录之前，门禁点过 exports 的清单）。
  **交付复检数的是文件而不是一个文件**：`verify_sequence` 按期望帧数点过（用**交付率**那把尺，
  与 1.139 同一口径）、编号从 000001 起必须连续、首尾两帧先用 ffprobe 认出是画面、再用
  `ffmpeg -f null` **真解码**一遍——ffprobe 只读头，看不出「最后一帧只写了一半」，而这一句既然写进
  docstring 就必须真的做到。发布路径跟着改了三处：帧先落兄弟目录 `名字.part/`，点过数才逐帧 rename
  进最终目录（写坏的序列不会顶着可用的名字）；同名第二次交付往后让成 `名字-2/`（覆盖别人的开链成果
  是不可逆的）；`output_size_bytes` 是那一串文件的总和。
  实测（`tests/sequence_check.py`，套件第 96 项）：三秒红/绿/蓝的源交 EXR 是 **90 个文件**
  （`全片.000001.exr`…`全片.000090.exr`），把整串当一条流 conform 回来逐帧读是 **30 红 / 30 绿 / 30 蓝**
  （顺序、少帧、错号都会在这里露出来）；标 1..2 秒按 25 交 DPX 是 **25 帧、读回来全是绿**；
  alpha 逐帧读回：空洞第 7 帧 **0**、实心第 31 帧 **255**、半透第 55 帧 **133**，同一条时间线关掉
  「背景透明」是 **255..255**——那个对照跑才是「这一层没被烘进画面」的证据。
  这一版被自己的门禁抓到一处真缺陷（不是推测）：把 `-map [aout]` 免掉之后 FFmpeg 直接失败——
  `Filter anull:default has an unconnected output`，实测退出码 4294967274。图里那条 `[aout]` 必须
  **自己落地**（`anullsink`），而且这件事只能在编译时决定：`filtergraph.txt` 是先交给调用方写盘、
  argv 是之后才建的。所以图文本收进 `RenderPlan.render_graph_text()` / `frame_graph_text()` 两处
  唯一来源，argv 与那两个文件都从这里出去。
  界面那一侧三条真话（`tests/desktop_sequence_check.ts`，第 51 个壳检）：预设下面那行念
  「OpenEXR 序列 · 每帧一个文件」而不是留一条空音频的斜杠；时间码那一栏对序列**不起作用**且
  发出去的就是 `null`（念的与发的是同一个值）；文件名那行说明白这是「一个目录加一串编号文件，
  声音不在里面」。规则变了的地方都一起改了：`desktop_timecode_check.ts` 与
  `desktop_timecode_rate_check.ts` 里那条「sendTimecode 只有一个来源」的断言跟着新表达式走，
  `desktop_format_check.ts` 那张编码器名字表跟着 `CODEC_NAMES` 长（`exr`／`dpx`）。
  13 条突变（9 条引擎 + 4 条界面）逐条红在自己那条断言上；其中「同名不让位」那一条是炸在
  `folder.mkdir()` 上（`FileExistsError`），红在提交而不是断言——这一点如实记在这里。
  **一次自我纠正**：第一版 `tests/sequence_check.py` 漏了 `if __name__ == "__main__": main()`，
  它被套件当成通过（两秒就"绿"）。门禁必须真的跑过，光存在不算。
  顺带把契约自洽的两条规矩补严：`preset["audio_codec"] == ""` 只许序列用（`format_check`），
  序列那一条 argv 必须有 `-an` 且不许有 `-ar/-ac`；`alpha` 与像素格式是否真带 alpha 层的等式
  从 `yuva` 一个前缀扩成 `yuva`／`rgba`／`gbrap` 三个。 装机复核的另一半（同一版补量，不改源码）：
  `desktop/electron/main.ts` 把 `--ffmpeg` 指到 `resourcesPath/bin/ffmpeg.exe`（随包那一份，
  82,797,568 字节），所以按同一对组合显式传路——冻结引擎自报 **1.142.0** 交出 **60 个 exr、
  55,493,400 字节**，复检消息仍是「共 60 帧，从 包内.000001 起连续编号，首尾两帧都解得开」，
  再用同一份包内 FFmpeg 把整串 conform 回来逐帧读是 **60/60 绿**。上一轮直接起引擎二进制时
  它自己探路探到了本机 WinGet 的 9.0.2，那一次也过，但不是「装机真正会跑的那一对」——现在两对都有数。

- 1.141 钉的是**交付开关的交叉表**：透明（1.136）× 时间码（1.137）× 交付帧率（1.138）× 标记区间
  （1.139）。每个开关单看都有自己的门禁，**没有一个把它们一起按下**——而 1.139 的教训正是
  「帧数、时长、率全对，只有内容在说谎」。新门禁读的全是落盘文件，且带位置签名（红/绿/蓝各一秒的
  三秒片，**三个满值**纯色：CSS 的 `green` 是 0x008000 半绿，宽松的颜色分类会把 alpha 丢失后被预乘
  压暗成 `0:126:0` 的画面读成「绿」——这个坑本轮亲自踩过一次，改严格分类（一个通道 >150、另两个
  <100，否则记 `其它r:g:b`）之后两条突变才红在该红的那句上）。
  实测：ProRes 4444 透明母版中间格 alpha 不换率 **127**、按 25 交还是 **127**（90 帧→75 帧、
  `avg_frame_rate` 25/1、三段颜色都还在）；四开关一起按的那份 webm 读回 `24000/1001`、**24 帧**、
  1.008 秒、时间码 `00:00:00:23`（大写键、容器标签，所以流与容器两处都读）、alpha 127、**逐帧全是绿**
  = 标里的第 1..2 秒；不写时间码时那一整个标签**不在**文件里；50 fps 透明母版 alpha 仍是 127。
  **这一版没找到新缺陷**，价值是把那一类缺陷永久钉住。`frame_count` 走 `-count_frames`（webm 头里
  没有 `nb_frames`）、时长走容器（webm 流里没有 `duration`）、alpha 用 `alphaextract` 且 webm 必须
  点名 `libvpx-vp9`。门禁 `tests/delivery_matrix_check.py`（套件第 94 项）；5 条突变逐条红在
  自己那条断言上（`alpha_out` 不要求透明平面、worker 丢 `job.transparent`、交付率不参与、帧尺退回
  时间线、时间码不写给 muxer）。写法上的收获记进习惯：**新开关落地时，除了给它自己写门禁，还要把它
  乘进已有开关的交叉表**。

  同一版接着把**画面内容**也乘进去（`tests/grade_matrix_check.py`，套件第 95 项）：片段带 `blur` 与
  `clip.color.exposure`（外加 0.5 不透明度），源改成**中灰**硬边（128，不是纯白——曝光是 128×2^0.5≈181，
  压在 255 上会被裁顶就读不出曝光了），三份交付：不透明@30、透明 ProRes@25、标记 1..2 秒的 webm
  alpha@23.976。量的三件事都从文件里读：柔边宽度按**画面宽的比例**（不同预设交出的画幅不同，px 不可比：
  实测 0.0419 / 0.0418 / 0.0419，px 是 80.5 / 13.4 / 80.5）、灰色平台电平（90 与 181、180，按各自
  alpha 合成之后落回同一个数）、区间那一份的时长仍是标里的 1.008 秒。**这一版被自己的突变组教育了一次**：
  「把 alpha 烘进 RGB」（丢掉透明平面）也能把「合成之后是同一个数」这条断言喂饱——两边都是 90。
  所以补了两条各管一头：平面必须真的在 120..135 之间，且透明母版的 RGB 不发暗（≥150）。补完之后
  2 条突变逐条红（调色那一环掉出画面链 → 红在电平区间；`alpha_out` 不再要求平面 → 红在平面区间）。
  区间帧尺那条突变**不由这一份门禁负责**——它的源在时间上是平的，窗口挪了也读不出差别；那一条由
  1.139 与 1.141 的红/绿/蓝签名门禁钉住。写门禁时要分清「这份能证明什么」，不然绿是假的。

- 1.140 收的是 1.138 的第二条接缝：**时间码那把尺也得跟着交付率走**。1.137 立规矩的理由是
  「FFmpeg 会收下并悄悄改写人打的数字」，而 `checked_timecode` 一直按**时间线**那一档判——1.138 之后
  「一秒有几帧」有了两个答案，那件事就从另一头回来了。这一版不是推测：门禁让 FFmpeg 自己出面
  （不经引擎），在 25 fps 的流上写 `-timecode 00:00:00:29`，它收下，`ffprobe` 读回来是
  **`00:00:01:04`**。反面同样坏：25 的线按 30 交写第 29 帧被拒，而那份文件里第 29 帧明明存在。
  修法是把交付率交给校验（`checked_timecode(timecode, delivery_rate or settings.frame_rate)`），
  帧号上限与丢帧码同判；选了交付率就是那一档，没选与 1.139 之前完全一致。丢帧码实测两头：
  29.97 的线按 25 交写分号**拒**（25 的流没有丢帧），30 的线按 29.97 交写分号**收**。
  界面原来在两处「猜」这条规矩：提示那句「帧号不能超过这条时间线的帧率」与那颗「分号可用」的
  判断——现在提示说「这一条交付画面的帧率」、判断从 `effectiveRate = sendFps ?? timelineRate` 来，
  而且旧那句话由门禁要求**消失**（出现即红）。
  门禁 `tests/timecode_rate_check.py`（套件第 93 项）+ 第 50 个壳层检查
  `tests/desktop_timecode_rate_check.ts`；6 条突变逐条红在自己那条断言上（退回旧算法、拒绝的句子不再
  点名「这一条画面的帧率」、把 25 也说成有丢帧码、面板用时间线判丢帧码、面板旧话回来、引擎提示不再
  点名交付画面）。落盘证据：按 25 交写 `00:00:00:24`，mp4 视频流标签读回来一字没改，`avg_frame_rate`
  是 `25/1`；一次被拒的提交不涨 revision、不排队任务。**装机复核跑的是发布包里那支引擎**
  （`desktop/release/win-unpacked/resources/bin/agentcut/agentcut.exe`，自报 1.140.0）：`GET
  render-plan?timecode=00:00:00:29&output_fps=25` 回 422 且句子是「这一条画面的帧率是 25/1，帧号只能
  00–24，收到 29」，`timecode=00:00:00;15&output_fps=25` 同样 422（TIMECODE_INVALID），而
  `00:00:00:24` 按 25 交成功落盘、`ffprobe` 从视频流标签读回 `00:00:00:24`、`avg_frame_rate` 是
  `25/1`；新 `app.asar` 里那句界面话是「这一条交付画面的帧率」（`tests/released_package_check.py`
  把这两句钉进发布产物）。

- 1.139 修的是 1.138 留下的接缝：**标了入出点又换交付帧率时，那一刀切错了段**。`render.py` 里那句
  `frame = settings.frame_ticks` 用的是**时间线**的一帧，而注释说的流已经按**交付**率归一过了——
  两把尺一直相等时互相圆场，1.138 让它们可以不等。量出来的事实（源是红/绿/蓝各一秒的三秒片，
  30 的线标 1..2 秒）：按 25 交落盘 25 帧里 **20 帧绿 + 5 帧蓝**，按 23.976 交是 **18 绿 + 6 蓝**，
  而 `plan.range.seconds` 照旧写 1.0、`-t` 又把文件截到一秒长——**帧数与时长全对，只有内容在说谎**；
  只看 `nb_frames` 的门禁会为这一版鼓掌。修法是除数换成交付流的帧长（`TIMEBASE × 分母 ÷ 分子`，
  八档都整除）并且两头**向上**取整：向下取整会让第一帧早于入点，把上一段的内容带进交付里——
  宁可少一帧收尾，不可多一帧穿帮。没换率时帧号与 1.139 之前逐字相同（`trim=start_frame=30:end_frame=60`
  专门钉成对照，这一改动不影响没换率的人）。顺带抓到只有极端组合露面的另一条：60 的线标第 1..2 帧
  按 25 交时两头取整撞到同一个帧号，那一刀会成零帧切口——留了「短窗口至少撑成一帧」的兜底
  （实测 `start_frame=1:end_frame=2`），把 `max(…)` 去掉当场红。声音那一头本来按秒
  （`atrim=start=1.000000:end=2.000000`），三个率同一句，所以画面这一刀改完，图与声仍在说同一个窗口。
  门禁 `tests/delivery_range_check.py`（套件第 92 项）**逐帧缩成 1×1 读 RGB**：0..1 秒那窗按
  30／25／23.976 交分别是 30/25/24 帧且**全是红**，1..2 秒那窗全是绿；三个率的时长都还在标的那一秒里
  （1.000/1.000/1.001 秒）。5 条突变逐条红在自己那条断言上：退回旧算法（交出 `30..60` 而不是 `25..50`）、
  入点向下取整（`23..48`，第一帧跑到入点之前）、出点多给一帧（`30..61`）、短窗口兜底没了（零帧切口）、
  音频换成帧号（与画面那句秒不再同一句）。**装机复核跑的是发布包里那支引擎**
  （`desktop/release/win-unpacked/resources/bin/agentcut/agentcut.exe`，自报 1.139.0）：同一份
  红/绿/蓝三秒源标 1..2 秒，按 30／25／23.976 各交一份，逐帧读 RGB 得到
  `30/1 → 30 帧全绿`、`25/1 → 25 帧全绿`、`24000/1001 → 24 帧全绿`（时长 1.000/1.000/1.001 秒）——
  交付包自己交出的就是标里那一秒，一帧不许多、一帧不许少。

- 1.138 交的是「同一条时间线交两版」那一词：交付帧率。时间线的时钟永远是 `TIMEBASE`，但交给谁
  看是另一件事——PAL 机房要 25、NTSC 交 29.97、胶片感要 24／23.976、高帧率要 50／59.94／60。
  这张表是**闭表**（`contracts.OUTPUT_FRAME_RATES` 八档），表外 422 `UNKNOWN_OUTPUT_RATE` 并把八档
  念出来。最容易被「我以为一样」骗过去的四个写法实测被拒：`30000/1000`、`23976/1000`、
  `29970/1000`、`59940/1000`——数值上与表里那几档相等，有理数却不是同一个，落地也就不是那个率。
  换了率只动两件事：`fps=` 那一级重采样、GOP 的秒数按交付率算（实测 `-g 60`→`-g 50`、
  `-keyint_min 25`），片段位置、入出点、遮罩与区间仍按时间线 tick 走，所以计划里 `frame_rate`
  （交付）与 `project_frame_rate`（时间线自己）分开写。留空 = 与 1.138 之前逐字相同（新字段
  不参与）。`audio-mp3/wav/flac` 没有画面，选帧率给 `OUTPUT_RATE_NEEDS_PICTURE`——这一条与 1.137
  的时间码同一个规矩：不许收下之后再什么都不改。率进幂等指纹（只在非空时加入）：同一
  `request_id` 把 50 改成 25 得 409，而不是悄悄重放旧的那份。**实测的产物**：同一条两秒时间线
  交三版，ffprobe 读回 `30/1` 60 帧 2.000 s、`25/1` 50 帧 2.000 s、`24000/1001` 48 帧 2.002 s
  （时长一帧没变）；一次批量两份文件各自 `25/1` 与 `30/1`；八档表内原样通过、八档表外点名拒、
  八种文本形状拒。门禁 `tests/output_rate_check.py`（套件第 91 项）+ 第 49 个壳层检查
  `tests/desktop_output_rate_check.ts`（跑真 `Engine`：选了的发、没选的一个字不写，query 里
  分子/分母编码过，批量各留各的答案，方案里存的就是发出去的那两条）；21 条突变逐条红在
  自己那条断言上（那张表 4 条、编译与落盘 4 条、任务与幂等 2 条、HTTP/MCP 3 条、界面接线 7 条、
  错码中文说法 1 条）。**装机实测（冻结引擎自报 1.138.0，渲染层从新 `app.asar` 抽出）**：页面那颗下拉
  排出的就是引擎那八档（`跟时间线（30/1）`、24、23.976、25、29.97、`30（就是时间线那一档）`、50、
  59.94、60），用页面自己的 `onChange` 选到 25/1 之后那栏读数变成 `25/1`；点「查看渲染计划」toast 原文
  是「已生成渲染计划 按「完整保留」不透明**·交付 25/1 fps** 由服务端编译…」，argv 里 `r=25/1` 也在；
  点「开始导出」落盘的那份 `装机时间码母版.mp4` 用 ffprobe 读回 `avg_frame_rate=25/1`、`nb_frames=50`、
  `duration=2.000000`，任务记录带着 `output_frame_rate {25,1}` 且 succeeded。这一轮还收了两次自己的假阳性：① `parse_frame_rate` 里那道
  「分子/分母上下界」是**死代码**——表外先被拒，永远不会拿这些数去构造 `FrameRate`，突变行
  STILL-GREEN 把它抓了出来，删；② 突变行钉错过一次站点（批量那条真正生效的是构造
  `RenderRequest` 的那处，不是我先打的干跑分支），改锚点之后当场红。

- 1.137 交的是母带交接缺的那一词：起始时间码。规矩不能交给 FFmpeg——这台机器上直接调它实测：
  `01:60:00:00` 被进位写成 `02:00:00:00`、`01:02:03.04` 的点被当丢帧写成 `01:02:03;04`、`1:2:3:4`
  一位数字照收、整数 30fps 上分号丢帧码也照写进 mov，而 SMPTE 只在 29.97／59.94 定义丢帧码。
  一份悄悄改写数字的母带比一次拒绝更坏，所以 `contracts.checked_timecode(value, frame_rate)` 是唯一
  那处判断（写法、小时／分／秒、**帧号必须小于这条时间线自己的帧率**、分号只给那两个率），不满足就
  422 `TIMECODE_INVALID` 点名是哪一段；没有画面的预设要时间码得到 `TIMECODE_NEEDS_PICTURE`。
  `RenderRequest.timecode` → `RenderBatchItem.timecode` → `RenderJob.timecode` → worker 重编时写同一个；
  只在非空时进去重指纹（与 `range`／`transparent` 同一个办法）；`render-plan?timecode=`、MCP
  `render_plan`（整串百分号编码）、`GET /v1/jobs/{id}` 那份计划都带它。界面那一栏是纯文本，写法与
  「哪两个率有丢帧码」从 `capabilities.timecode_shape`／`timecode_drop_rates` 拿——视图里不许出现第二个
  正则（门禁断 `{2}` 不许出现），空就是「不写」，发出去的值只有一个 `sendTimecode`。证据是文件本身：
  同一条时间线导 mov／mp4／webm／mxf 四份，按各自真正存放的位置读回（mov／mp4 在**视频流标签**，
  mxf／webm 在**容器标签**，webm 还把键写成大写 `TIMECODE`），四份读回都是原串；29.97 的工程用丢帧码
  导出也一个字没改。新增第 90 项特性检查 `tests/timecode_check.py` 与第 48 个壳层检查
  `tests/desktop_timecode_check.ts`（跑真 `Engine` 收假 `fetch`），16 条突变逐条红在自己的断言上；
  `tests/error_vocabulary_check.py` 在两个新码还没有中文时就先红了。
  **装机实测**：冻结引擎（自报 1.137.0）交出的 mov／mp4／webm／mxf 四份按各自位置读回的都是那一串
  `01:02:03:04`，不带那一栏的对照文件里这个标签整个不在，两种该拒的写法被点名拒掉且 revision 不动、
  任务表一条不许多；从新 asar 解出的渲染层里真敲字 —— 敲进去的串让引擎那条任务成功落盘并被 ffprobe
  在视频流标签读回，清空之后那条任务没有时间码，敲 `01:60:00:00` 页面上是「分钟最多 59，收到 60」。
  最后这一条量出一个老毛病：引擎自己说中文的拒绝过去被界面那句通用提示整句盖掉，现在 `explain()`
  以引擎那句为准（中文时），通用提示只在引擎说的是英文时顶上——`desktop_error_naming_check.ts` 两行
  各自钉住一半。界面那一版差点把
  `../time` 里格式化时间的函数被新状态变量遮住（`const [timecode, …]` 让摘要那行
  「This expression is not callable」），tsc 抓到，门禁从此断这条遮蔽不许回来。

- 1.136 把「透明通道母版」变成请求里的一词，并且按落盘的字节量过。引擎内部早就按 alpha 合成（嵌套
  子合成必须这样，`render.py` 里那个 `_transparent`），但人或 Agent 要一张能叠进 AE / DaVinci / 网页的
  透明母版时没有公开入口。现在：预设自己声明装不装得下（`prores-4444-alpha` = mov / prores_ks profile 4
  / `yuva444p10le` / pcm_s24le；`vp9-1080p-web-alpha` = webm / vp9 / `yuva420p` / opus / 1920×1080），
  `capabilities.alpha_presets` 就是这张表筛出来的，`RenderRequest.transparent` / `RenderBatchItem.transparent`
  → `RenderJob.transparent` → worker 重编计划按它渲染；选了没有 alpha 平面的预设就 422
  `TRANSPARENT_NEEDS_ALPHA` 并把装得下的那几条念出来（`tests/error_vocabulary_check.py` 在引擎刚有这句拒绝、
  界面还没写中文时就先红了，这是它该干的活）。`compile_render_plan` 新增公开的 `transparent`，内部
  `_transparent` 原样留着——两者在 `alpha_out` 一处合流，验证仍只在外层做一次。门禁是新的第 89 项
  Python 检查 `tests/alphamaster_check.py`：**真走 job worker 导出**，再用 FFmpeg 把 alpha 平面写成灰度
  字节按点读——同一条时间线（空一段 / 满不透明一段 / `effects.opacity=0.5` 一段）量到 **0 / 255 / 128**
  （ProRes）与 **0 / 255 / 127**（WebM），而**同一预设不带那个勾的对照导出三处都是 255**；亮度另算一次
  （片段底下 149、空板处 0），所以「alpha 说有画」与「这里真有画」是两次独立读数。顺带量出两件只能
  写下来的事：ffprobe 对 WebM 在流那一层报 `yuv420p`（透明度挂在每个 block 后面的附带通道里，容器元数据
  不反映它），且 FFmpeg 原生 vp9 解码器解不出 alpha 平面（`Requested planes not available`），必须
  `-c:v libvpx-vp9`——因此复检按字节量，而 `-auto-alt-ref 0` 这种「据说必须」的开关在实测证明它改变落盘
  文件之前不写进参数表（第一版写了，量出来不需要，就删了）。界面那侧只有一条路：`engine.matteAllowed(preset,
  audioOnly, requested)` 一处决定那个勾算不算生效，勾本身、待发清单、干跑、开始导出、竖屏副本让路（让路
  时悬停写明原因）读的都是它；新增第 47 个壳层检查 `tests/desktop_alphamaster_check.ts`（跑真 `Engine`
  收假 `fetch` 的请求体与 query）。两条门禁合起来 22 条突变，逐条红在自己的断言上并核对红的是哪一份检查。
  同一批还补了两处同源欠账：`GET /v1/jobs/{id}` 那份计划改走 `plan_for` 并带上任务自己的 `range` 与
  `transparent`（过去它用默认值重算，于是「排队中看到的计划」与「将要渲染的活」可以是两回事），MCP 的
  `render_plan` 把 `range` 与 `transparent` 一起问出去（过去两样都不问）。
  换画幅那一半是第二批量出来的：180×320 的竖屏片源按 `contain` 进 1920×1080 的透明交付，**pillarbox 边读到
  0、画面中间 255**，同一条不透明导出的边 255——我先怀疑轨道链的 `pad=...:color=black` 会压成黑板并改了
  `fit_pre`/`fit_post`，两次量错（一次放的横屏片源根本没补边、一次把 yuva420p 的 U 平面当 alpha 读）之后
  确认那是够不着的死分支，逐字回退，只留按文件量的回归断言与一条「透明计划的串里不许出现不透明 pad」的反向
  断言。**装机实测**：`released_package_check.py` 确认根 `AgentCut.exe` 逐字节等于便携版、asar 带 1.136.0
  与那 11 句人话；冻结引擎自报 1.136.0，量到 0/255/128（ProRes）与 0/255/127（WebM）、对照 255/255/255，
  亮度 149/0，H.264 要透明被点名拒掉且 revision 不动；从新 asar 解出的渲染层真指针点下去：默认那颗勾灰着
  并点名 `prores-4444-alpha`，换 ProRes 行后能用，勾上后竖屏副本让路写明原因，「开始导出」让引擎多了一条
  `transparent=true / succeeded / output_checked=true` 的任务（683134 字节，任务表只多 1 条）。
  这一批落地后 `uv run python tests/suite_check.py`（89 项，空闲机器单独跑）全绿；重新验证只需这条命令、
  `uv run python tests/alphamaster_check.py`、`uv run python tests/desktop_ts_check.py`，以及
  `python scripts/build_engine.py --verify` + `cd desktop && npm run dist` + 把便携版复制回根 `AgentCut.exe`。

- 已交付并三方验证（源码门禁 + 发布产物 + 真实界面）：1.103 3D LUT、1.104 工程级 inline 查找表预算、1.105 `GET /v1/projects/{id}/grade-capacity` 与 MCP `grade_capacity`、1.106 回执总量不再被前 20 名视图截断。重新验证只需 `uv run python tests/suite_check.py`（空闲机器、单独跑）与 `uv run python tests/gradebudget_check.py`、`uv run python tests/lut3d_check.py`；发布产物里的引擎应自报 1.106.0。
- 已完成的下一个增量（1.107）：把 `grade-capacity` 接进检查器——按 revision 缓存回执，在调色那节显示「已用 X / Y 个采样点，还能放 N 张 17³」，数字只准来自引擎（界面不许自己算），门禁要断那一行的数与 `grade_capacity()` 逐字相同，并用突变证明读的是回执而不是自算。再往后是「整轨套用一条调色」（`clip.grade` 批量 + 用 `room` 前置规划 + 逐片段拒绝点名）——那一条已在 1.108 交付。发布产物里的引擎应自报当前的 `APP_VERSION`（1.115 起是 1.115.0），壳层检查的数目以 `tests/desktop_ts_check.py` 的输出为准（1.115 起 33 个）。
- 1.108 又交付了一条：一条片段的调色链一键套到整轨（`grade-apply` 端点 + MCP `track_grade_apply` + 检查器两颗按钮），规划只问 reducer 会问的三件事，套不满的段落逐段报实数。
- 1.109 交付的是交互层的一处判断：曲线吸附改认绝对帧格子并新增「找针 / 找播放头」，引擎、契约、HTTP、MCP 一字未动，所以 `tests/suite_check.py` 那 80 个 Python 子检查没有新增产品断言，新增的是第 28 个壳层检查 `desktop_keyframesnap_check.ts`（`tests/desktop_ts_check.py` 自动发现，无需注册）。
- 1.110 又是一条纯界面的增量：时间线上直接拖关键帧（`desktop/src/keyframeDrag.ts` + `Timeline.tsx` 的菱形），复用 1.109 的吸附几何，引擎一字未改；新增的门禁是第 29 个壳层检查 `desktop_keyframedrag_check.ts`。
- 1.111 收掉的是界面上那两个互不相干的吸附开关：动画曲线现在读同一份 `EditPrefs.snap`，新增第 30 个壳层检查 `desktop_snappref_check.ts`（驱动真 store），引擎一字未改。
- 1.112 交付的是动画工作流上缺的那一把复制／粘贴（曲线编辑器 Ctrl+C / Ctrl+V），新增第 31 个壳层检查 `desktop_keyframecopy_check.ts`；引擎、契约、HTTP、MCP 仍一字未改——Agent 侧本来就能写 `keyframes.replace`，这一版是把人这边的手感补齐。
- 1.113 修的是一条只有 hit-test 能暴露的旧缺陷：同一秒上的多枚针叠在同一堆像素里，其中一枚鼠标永远点不到；现在一条属性一道，画不下的少画并给出 +N 的回口（`keyframeLanes.ts`）。新增第 32 个壳层检查，引擎一字未改。
- 1.114 给时间线的针加上 Alt 拖复制（同一处 `planKeyframeDrag`，一条 `keyframe.set`，影子与历史标签都分得清），引擎一字未改；壳层检查仍是 32 个，扩的是既有的 `desktop_keyframedrag_check.ts`。
- 1.115 收的是两处欠下的账，都不是新功能：① 界面每一句说到某条动画属性的话都改读唯一那张 `FIELD_LABEL`（时间线针的 tooltip 与无障碍名、「+N」牌子、撞针红字、复制／粘贴提示、检查器插值下拉的无障碍名），契约 id 不再当用户界面用；新增第 33 个壳层检查 `desktop_keyframename_check.ts`，它把这张表的键与 `contracts.py` 的三条 `Literal` 对齐，并禁止任何视图自带第二份名字表。② 1.112 接线时被我用「粘贴按钮」那条断言替换掉的「Ctrl+A 守卫的括号」补了回来，并且扩成三个和弦都断（`a || b && c` 少一层括号就是「按一下 Ctrl 就全选」）；13 个突变＋3 个括号突变逐条打在自己的断言上。③ 同一次装机实测量出 1.113 那枚「+N」牌子点了没反应（pointerdown 被片段的拖动手势吃掉，`onClick` 执行不到，tooltip 里那条「点开进动画曲线」是空话），牌子现在自己收下这次按下，`desktop_keyframelane_check.ts` 断这层交接，另有 2 个突变打在它上面；引擎、契约、HTTP、MCP 一字未改。
- 1.116 给时间线的针加了第二只手：按住 Alt 点一下就是删这一枚（`planNeedleRemoval` → 普通 `keyframe.remove`，片段本地刻度，`editAtRevision` 落库，撤销一次回一枚），并把撞针那句红字的出路从「去动画曲线里删」改成就地「按住 Alt 点掉」——那句拒绝过去指的是一条不在眼前的路。扩展的是既有的 `desktop_keyframedrag_check.ts`（第 33 个壳层检查不变）：Alt 点删对那一枚、普通点一枚都不许多、Alt 真拖仍是复制、命令形状只有那四个键、偏移只折一次。引擎一字未改。
- 1.117 是纯重构＋一条格子上的收口：把曲线编辑器「拖一下」的算术（量化 → 整组按量程与片段两头夹 → 逐枚落值）从组件里抽进 `desktop/src/curveDrag.ts`，行为与装机读数一致（0.5/0.9 两枚一起拖仍是 0.6/1.0），但落值改为再过一次这条属性的步长格子——过去带漂移的草稿（0.17499999999999999 这种）靠引擎替我们抹平，现在草稿就是落库那份。新增第 34 个壳层检查 `desktop_curvevalue_check.ts`；引擎除版本号一字未改。
- 1.117 系列的最后一步：曲线编辑器里最后一处「只能靠读代码判断对错」的算术——数值框那条夹法——也抽进了 `desktop/src/curveDrag.ts`（`bandEntry`），行为一字不变（越界夹回、空串/乱码/Esc 不算改、同值不发命令、**打字的值不过格子**），换来的是九条行为断言 + 三条接线 + 五条能红的突变。引擎与契约未改，版本串仍是 1.117.0。
- 「全面替代剪映 / 达芬奇 / AE」仍未达成，能力接口、README 与帮助页都没有声称它；待实现项见本节下方与 README 表格尾注。
- 1.118 交付的是 AGENTS 与 README 尾注都挂着的那条能力缺口：自由路径遮罩的**形状**能随时间变形。`Clip.mask_shape_keys` 记整条顶点表（矢量，不拆成每顶点四条标量曲线），写入只走新命令 `mask.shape.set` / `mask.shape.remove`；`animation.mask_shape_schedule` 与柔焦共用同一个窗编译器，导出每窗切一张板 `overlay…enable` 叠上，`preview_manifest.mask_shape` 给界面同一份窗表与落位数字：形状两端一起阶梯，盒仍按 `mask_x/mask_y` 连续搬。判断只在 `Clip.mask_shape_problem()`（非路径遮罩、拓扑不同、同一时刻两帧 → `INVALID_MASK`）；额度读契约字段的 `max_length`，第 33 帧回 `MASK_SHAPE_LIMIT` 并点名出路。界面：第一帧即开关（AE 秒表语义），拖顶点／方向键微调记在当前时刻，检查器给帧表（跳、改插值、删、一次清场）与「N / 上限」；插值名字表从曲线编辑器搬进 `effects.ts` 那张唯一的表。门禁抓到一处真缺陷并已修：新增默认字段会让 1.118 之前写的回执在重试时裂成两半（`projects._fingerprint` 现在把空表当没提过）。验证：`tests/maskshape_check.py`（真实成片逐窗量遮罩边缘＝该窗自己的表；解码引擎切的每张 PNG 板核对宽度＝交给界面的窗宽；HTTP 原子性／额度／锁轨／撤销；未记帧的工程编译串与 1.117 逐字相同）＋ `tests/desktop_maskshape_check.ts`（选窗边界、落位数字原样、命令形状、能力门、窗表键与引擎逐字配对），12 条突变各自红在自己那条断言上。壳层检查 35 个（以 `tests/desktop_ts_check.py` 的输出为准）；引擎自报 1.118.0、工程 schema v16。
- 1.119 交付的是「时间线只有单枚针的手」那条欠账（原下一轮入口第 2 条）：针道空处拉框挑中一组，拖组里任意一枚就是整组同时改同一份时间差；Shift 点一枚加进/摘出这一组，Alt 拖复制整组。引擎、契约、HTTP、MCP 一字未改（除版本号）——多枚走引擎本来就有的 `keyframes.move`，一枚仍是 `keyframe.move`，复制那组是同批次若干 `keyframe.set`。三处判断各只有一个主人：整组的时间余量是 `curveDrag.clampGroupTimeShift`（1.117 那份 `groupShift` 的 dt 分支现在就是这一句，门禁把两处对成等式）；撞针照 reducer 的 `occupied - source_ids`（复制时原针仍占位）；命中集读屏幕上真画出来的菱形矩形（画不下的属性与拖动影子都不在里面，所以框挑不到一枚点不到的针）。拒绝那句话点名的是**真的被占的那条曲线**，不是被抓的那一条。验证：`tests/desktop_keyframedrag_check.ts` 新增一节组的行为，`tests/desktop_keyframemarquee_check.ts` 是第 36 个壳层检查，`tests/desktop_keyframelane_check.ts` 与 `desktop_keyframename_check.ts` 各改了一条被这次重构挪了位置的接线断言（仍能红）；26 条突变逐条红在自己那条断言上（改的是 `clampGroupTimeShift` 的调用、复制时把组内原针排除在占位之外、撞针按「抓的那条曲线」判、batch op 换成单条 op、组参数被丢掉、组顶在片尾时仍发命令、界面那边把组交出去的那行、影子所在道、影子与针共用的那句贴边夹法、Alt 复制时源菱形的外观、Shift 挑针、擦边算不算选中、Shift 框选是否替换、两像素阈值、针道左右那 20 像素、样式表里淡角柄的宽、`.clip-needles` 自己写死 left/bottom、针的标识拼法、预留高度的像素数、影子被算进命中集、点空处清场、针道吞掉 pointerdown、以及少画那道属性的 filter）。壳层检查 36 个；引擎自报 1.119.0、工程 schema 仍是 v16。装机实测（1.119 打包产物 + 内置浏览器，冻结引擎自报 1.119.0）量到：整条针道拉框挑中 3/3 枚、只压住底部那一道的细框挑中 2/3 枚、四枚跨两条曲线一起拖时落库位移逐枚都是同一个 70 207 200 tick、三次抓取三个 revision（2→5）。同一次实测改掉了一处真缺陷：命中集原先在按下那一刻快照一次屏幕，而这条时间线是人跟 Agent 共用的——Agent 在你拖着框的时候改写工程，那份快照就留下一枚已经不存在的针，所以命中改成每次 `pointermove` 重新量（看得见什么挑什么）；写路径本身仍由 `expected_revision` 兜住。那份浏览器偏好里磁吸是关的，这条实测因此**不**主张吸附，吸附仍由 `desktop_keyframesnap_check.ts` 与 `desktop_keyframedrag_check.ts` 断。
- 1.120 交付的是调色图上的**并联节点分支权重**（达芬奇混频台那一排旋钮）：`GradeParallel.weights` 按位置覆盖每一支，0..`capabilities.grade_limits.branch_weight_max`（与字段约束同一个 `GRADE_BRANCH_WEIGHT_MAX`），**给就必须给全**——长度对不上的表在 model validator 就拒（422 请求校验，写入没发生），因为两端会算出不同的结果。没给就是均分，且与「交一串 1」逐位相同（`grade_check.weight_math_suite` 把这条兼容钉成断言）；全部为 1 时界面把整份表**撤掉**而不是交一串 1，`projects._fingerprint` 里空表按没提过处理，1.120 之前的回执继续命中自己（`weight_receipt_suite` 断这条）；全部为 0 是「这一节不改画面」而不是黑场（`node_function` 返回 None，编译结果里根本没有这一节）。真实成片：同一条并联节点把暗带红值从均分的 43 推到 2:0 的 87、拉到 0:2 的 2（`weight_media_suite` 那行 print 报的就是这三个数）。界面那一侧的形状判断只有 `gradeGraph` 一处（改一支补齐、加一支补 1、删一支同删那一格），旋钮上限读下发的那个数；第 37 个壳层检查 `tests/desktop_gradeweight_check.ts`。19 条突变（引擎侧 8、界面与契约侧 11）逐条红在自己那条断言的消息上。壳层检查 37 个；引擎自报 1.120.0、工程 schema 仍是 v16。装机实测（1.120 打包产物 + 内置浏览器）：Agent 写 `weights: [2.0, 1.0]` → 界面旋钮读成 2.00、卡片念「加权 ×2/×1」、`max` 是下发的 2；人拧三下从 rev 3 到 rev 6，全回 1 时表被撤成 `weights: []` 且「这一支回 1」消失。
- 1.121 把删除也变成整组的手：时间线上按住 Alt 点挑中的任一枚就是删掉这一组（一条 `keyframes.remove`），只挑中一枚时仍是 1.116 那条 `keyframe.remove`。`planNeedleRemoval` 收的是界面按挑中的算出来那一组，重复的那格先去掉（reducer 对重复选区回 `INVALID_SELECTION`），刻度仍只折一次偏移；删完清掉这一组，免得下次框选挑中一枚已经不存在的针。悬停说明分两种写法（挑中的写「把这 N 枚一起删掉」）。引擎、契约、HTTP、MCP 一字未改（除版本号），壳层检查仍是 37 个，7 条突变逐条红在自己那条断言的消息上；引擎自报 1.121.0、schema 仍是 v16。装机实测（打包 exe + 内置浏览器）：挑中三枚后 Alt 点其中一枚，工程回读 `keyframes` 为空而 revision 2→3；未挑中时 Alt 点一枚只少一枚，悬停文案随「是否在这一组里」分开写。
- 1.122 给并联节点补上第二份位置表 `blends`（达芬奇混频台的 mode + gain）：每一支先按自己的方式与进来的画面相合，再按权重平均。算法不换——用的就是节点级混合那份 `blend_values`，全 normal 与 1.120 **逐位相同**（`grade_check.blend_mode_suite` 断这条），停用那一支的模式不参与（「停用即直通」不能被下拉改掉），形状与权重同规矩（给就给全、全 normal 撤表、空表按没提过进指纹）。词表只有契约 `BlendMode` 一个来源：`desktop_branchblend_check.ts`（第 38 个壳层检查）把它与界面那张 `BLEND_MODES` 逐字对起来。真实成片：一支改 difference 与正常平均差 33.0 级；screen 与独立参考表 ≤0.5 级。15 条突变逐条红在自己那条断言的消息上（界面侧 9、引擎与检查侧 6），另有 2 条改的是「没给表时默认怎么走」那条路径——同一句也是更早那些并联节点断言的食粮，因此由上游门禁接住（harness 打出是谁接的）。「与 1.120 逐位相同」和「screen 对得上独立参考表」这两条是用**换检查自己的载荷**武装的：能红它们的引擎突变必先红更早的断言，只有更早那些断言看不见的那处改动才证明比较真的发生。界面那边停用那一支的下拉是灰的（`disabled={!shown.enabled}`），第 38 个壳层检查断的就是这个属性。引擎自报 1.122.0、schema 仍是 v16。装机实测（1.122 打包产物 + 内置浏览器，冻结引擎自报 1.122.0）：人挑一次「滤色」写出整份 `blends: ["screen","normal"]`、牌上念「1. 色阶 · 滤色」（rev 1→2），关掉这一支自己的「启用本支」后那一格下拉 `disabled` 为真、计算样式淡到 0.7（rev 2→3）；Agent 侧 `blends` 与 `weights` 一起交进去读回同一份数（rev 4），`capabilities` 回 `grade_branch_blend_modes: true`，只交一格的表被冻结的契约按 `matched_weights()` 点名拒、revision 不动。实测踩到的坑记下来：检查器面板里有三个 `.grade-switch`（替换已有色阶 / 启用 / 启用本支），按第一个去点会打到自动调色那个勾选，界面自己也得按文字找。发布产物：`AgentCut.exe`（工程根，逐字节等于 `desktop/release/AgentCut-便携版.exe`）与安装版同一份构建，`app.asar` 与 renderer bundle 里能读到「这一支的混合方式」与那句停用说明；`scripts/build_engine.py --verify` 通过（冻结 exe 冷启动 662 ms、`tools`/`mcp`/`--help` 各就各位）；空闲机单独跑 `tests/suite_check.py` 81/81、`tests/desktop_ts_check.py` 38/38。
- 1.123 交付的是 AGENTS 与 README 都挂着的那条「清晰的逐帧动画」：`sharpen` 与 `sharpen_radius` 进了 `SpatialProperty`，两颗旋钮**共用一张窗表**（`animation.sharpen_schedule`，把 (强度, 半径) 当成一个元组交给 `frame_windows`，任一个变了才换窗），所以不会出现「导出串了第 k 对阶段、预览却没有第 k 步」。上限另给一个更小的数：`SHARPEN_SCHEDULE_MAX = 8`，因为一窗是 `gblur` + `blend` 一对——量过 6 秒 320×180：1 窗 0.47 s、4 窗 1.35 s、8 窗 2.53 s、12 窗 3.68 s、24 窗 7.18 s（1280×720 八窗 2.47 s），每多一窗约 0.29 s。可见代价：4 秒 25 fps 上清晰 13 帧一跳（柔焦 24 段是 5 帧一跳），窗边界只落在整帧上。链式 `blend` 能吃下「关掉就原样交回第一个输入」这件事是**量出来的**（确定性片源，`enable='between(t,0.9,1.3)'`：第 5/25/55 帧与强度 0 的同 hash，只有 31/37 不同），Chromium 那边 `filter` 在 `none` 与 `url(#id)` 之间按 `steps(1, end)` 切换也量过。预览 `clips[*].sharpen` 有两种形状（静态那份一字不变；有曲线是 `{windows, curve}`，零强度那格 `id: null`），有曲线时静态 `url(#…)` 从 `color_filter` 离开——与 1.98 那条「CSS 不能只换共享串里的一项」是同一个理由。成片：128/192 棋盘上相邻像素差的均值沿斜坡从 40.8 涨到 82.2，逐窗与「整段同一对数」的同路渲染差 ≤1.22，零强度两窗读到的就是原片 37.4。门禁 `tests/sharpenkey_check.py`（阶梯／两端同源／编译串／成片）+ 第 39 个壳层检查 `tests/desktop_sharpenkey_check.ts`；`tests/blurkey_check.py` 那句「sharpen 不该能当关键帧属性」随之改成只拒 `denoise`。顺带把九颗效果旋钮的「有曲线就改这一时刻的点」与那只 ◇ 收成一处实现（`Inspector.tsx` 的 `commitKnob`/`knobButton`），壳层检查断的就是这个唯一性。契约除新增两条 id、两个上限字段与一位能力外未改。33 条突变（界面 13、引擎与检查侧 20）逐条红在自己那条断言上；跑出来的一处**空突变**记进检查本身：斜坡那片半径一直是静态值，把 sigma 的来源换成静态值是看不见的，所以「每一窗的半径走到 sigma」只在半径真的变过的那条片段上断（`chain_suite` 的 `held_sigmas`）。发布复验：`scripts/build_engine.py --verify` 通过、根 `AgentCut.exe` 逐字节等于新便携版、asar 里读得到新界面那句话。装机实测（1.123 打包产物 + 内置浏览器，冻结引擎自报 1.123.0）：两颗 ◇ 在（`添加清晰关键帧` / `添加清晰半径关键帧`），人点一下 = 一条 `keyframe.set`（rev 1→2）；Agent 补齐后下发 7 段窗，`.layer-edge` 那条 4000 ms 动画在 200/700/1300/2100/3000 ms 读到五个互不相同的 `url(#sh…)`；改成前 2 秒为 0 的按住斜坡后只剩两段窗、`curve` 首格 `id: null`，同一元素 100/1500 ms 读到 `none`、2100/3800 ms 读到 `url(#shf088f2a8f30a)`。实测脚本改完要**按字节还原**并再跑一次基线（这次跑出一条空突变已记上）。
- 1.135 把那张键位表管到底。1.134 只收了带 Ctrl 的 13 条，V/C/S/X、Delete / Shift+Delete、＋/－ 还写在 `App.tsx` 那条链的后半段——一张表管一半等于没有表：改了键另一半照旧，而帮助页与悬停会开始各说各的。现在表上共 **21 条**（新增工具选择、工具分割、时间磁吸、X 剪开、两种删除、缩放两向）。`chordUsable` 的判断也改准了：1.134 那句「至少要带 Ctrl/⌘ 或 Alt」把工具键一并拒了，而工具键天生是裸的；现在拒的是**只按修饰键**，裸键合法——拦在打字之前的是 `App.tsx` 里 `const typing = …` 那道判断，它跑在分发之前，门禁既断顺序也断它必须是活的。`runKeyCommand` 多了 8 格、条件与那条链一致（工具/磁吸/剪开/缩放要在时间线里，两种删除还要有选中）；App 里只留两个别名：Backspace 走同一条删除、「=」走同一条放大，不占键位也不被改键牵走。悬停一起跟着读表：时间线两颗工具按钮、两种删除、＋/－，检查器的「只删这一段」「删掉这段并补齐」「在播放头处切成两段」。门禁扩到 `tests/desktop_keymap_check.ts`（21 行表、裸键合法、只按修饰键被拒——界面与存储两处都断、typing 判断必须活着且在前、Timeline/TitleBar/Inspector 三份文件不许出现写死的 `（V）（C）（S）（X）（Delete）（Shift+Delete）（Ctrl+…）`）与 `tests/desktop_snappref_check.ts`（「S 快捷键」那条接线改断新的唯一开关，并断 App 不再自己认 S）；19 条突变逐条红在自己那条断言上并核对红的是哪一份 shell check。**装机实测（冻结引擎自报 1.135.0，渲染层从新 `app.asar` 抽出后深链同一份三段工程；信号是工具条两个按钮的 `active` 类与状态栏那行 `NNpx/s`）**：开机「选择 true / 分割 false / 62」→ 按 c「false / true / 62」→ 按 v「true / false / 62」→ 按 － 到 50 → 按 ＋ 到 63；再把「缩小时间线」改成 Ctrl+Alt+M（`agentcut.keys` 只有这一条记录，表上那一行同步念「缩小时间线 Ctrl / ⌘ + Alt + M」），之后按「－」63 一动不动、按 Ctrl+Alt+M 到 50——旧键退休、新键上岗，表上 21 行与工具条、检查器、状态栏的措辞是同一份数。
- 1.134 把命令键位收成了一张能改的表。以前 `App.tsx` 里是一条 if 链、13 个组合键的字面量写在那儿，`Help.tsx` 的快捷键页又把同样的「Ctrl+B」抄了一遍给人看，而人没有地方改（剪映、达芬奇、AE 各有一套默认键，替用户猜一套不合理）。新增 `desktop/src/keymap.ts`：`COMMANDS`（13 条命令的 id、中文名、界面上那颗孪生按钮的名字）、`DEFAULT_MAP`（就是这次改动之前实际在按的那套）、`matchCommand`（唯一的解析处：精确 Shift 的那条赢，其次才是标 "any" 的那条）、`chordFromEvent`/`chordWords`/`chordUsable`/`rebind`/`mergeMap`/`changedFromDefault`（没有修饰键的单键直接拒；冲突要点名被抢的那条；脏存储认不出的形状丢掉而不是让界面崩；落库只写改过的那几条）。`store.ts` 里 `keymap()` 读状态、`remap.set/reset` 写状态并落 `agentcut.keys`，`runKeyCommand` 是唯一的「这条命令此刻该不该做、做什么」的开关；`App.tsx` 只剩一次解析加一次分发。界面上凡是念键名的地方都改成读这张表：帮助页新增「命令键位」那张表（13 行、每行一个「改键」、一行「回到出厂键位」、等按键时那一格写「等按键…」），工具条的分割/复制/粘贴/重做、标题栏的导出、检查器的「复制一段接到本轨末尾」都念当前键位，引擎那句 LINK_IN_SYNC 说明里的「（Ctrl+Z）」去掉——键位现在是人定的，写死的那句会变成假话。方向键微调、I/O/K/J/L、空格、Esc、F1/F9/F10、Ctrl+滚轮**不在**这张表里（跟着焦点与上下文走，做成可配置的只会让那张表看起来谁都能改、其实改了没用），门禁把这条边界钉住。门禁 `tests/desktop_keymap_check.ts`（第 46 个壳层检查，跑真 store：出厂 13 条逐条对、解析六种情形、改键后新旧键各自的命运、落库只有改过那一条、重启读回、冲突点名到「撤销」、被拒时现值不动、脏存储逐形丢掉、回到出厂连存储一起清干净、视图与引擎提示不许留着写死的键名、每条命令在那一个开关里有一格）；14 条突变逐条红在自己那条断言上并核对红的是哪一份 shell check。**装机实测（冻结引擎自报 1.134.0，渲染层从新 `app.asar` 抽出，深链同一份三段工程）**：F1 → 快捷键那一节念出 13 行（首行「撤销 Ctrl / ⌘ + Z · 界面上：标题栏的「撤销」」）；点「改在播放头处剪开的键」后有 1 格写「等按键…」，真按 Ctrl+Alt+J → 那一行变「Ctrl / ⌘ + Alt + J」，`localStorage.agentcut.keys` = `{"split":{"key":"j","shift":false,"ctrl":true,"alt":true}}`，toast「在播放头处剪开 换成 Ctrl / ⌘ + Alt + J」；再点「改复制选中的片段组的键」按 Ctrl+Z → 「改不了这个键：这个键已经是「撤销」的了。复制选中的片段组仍然是 Ctrl / ⌘ + C」，那一行与存储都没动；点「回到出厂键位」→ 回到「Ctrl / ⌘ + B」、存储清成 `{}`；关掉帮助选中一段（`aria-pressed` 回 true、`.clip.selected` 一枚）、推十下 ArrowRight 再按 Ctrl+B → 页面 3 张卡片变 4 张，引擎读回 `revision 3 / clips: 4`——那一下是真的写进了工程。
- 1.133 把两万段那一页画出来了。1.132 用调试器中断抓到的那串栈说的是第一次渲染（`view` 那时还是 null，而 1.131 写的规矩是「没量到视口就不裁」），所以这一版把那条规矩删掉：`timelineWindow.ts` 的 `laneTicks` 收必填视口，量不到就当看见 `FIRST_PAINT_PIXELS`（1200 px），`firstView()` 是 `Timeline.tsx` 里那一格的初值——量到真值以后立刻按实测改，宽窄只影响首帧那一下；`TrackRow` 的 `paint` 改成必填，`paint ? … : clips` 那条三元没了；`rulerMarks` 的窗口也必填，顺带删掉它自带的那第二张间隔表（间隔的唯一主人是 `rulerStep`）。还堵了一条只有读代码才看得见的路：`edit.pxPerSec` 以前把 localStorage 那份偏好**原样**摊进初始状态，而 `px<=0` 是 `laneTicks` 唯一还能「不裁」的出口——现在 `ZOOM_MIN/ZOOM_MAX` 与 `clampZoom` 只有一处，滑杆、`setZoom` 与读回来的那份都过同一个夹子，非数不带走现值。门禁：`tests/desktop_20k_check.ts` 改钉首帧（默认宽度与宽度为 0 同解、三秒的小工程不被默认宽度切掉、两万段在 px=100 与 px=ZOOM_MIN 下首帧都不过界），新增第 45 个壳层检查 `tests/desktop_zoomclamp_check.ts`（跑真 store）；11 条突变逐条红在自己那条断言上，并核对红的是哪一份 shell check。**装机实测（冻结引擎自报 1.133.0，渲染层从新 `app.asar` 抽出，同一台引擎实例 3b3f86eb8f94，工程线上 12,103,211 字节）**：`node scripts/renderer_scale.cjs --url <两万段深链> --budget 90` 在 6.7 s 报 `painted:13, nodes:485`、退出码 0，工具条那句念「窗口外还有 19987 段没有画（它们仍在工程里，也在导出里）」；本次 profile 那棵进程树峰值 843 MB（最大单进程 205 MB）、用户态 CPU 2.21 s——对照 1.132 的 never-painted / 树 2,994 MB / 渲染进程 2,370 MB 后消失。滚动与缩放仍带得动：1,240,440 px 的横向滚动推到 25%/60%/100%，卡片 18/17/9 张、左缘 309,814/744,000/1,239,440 px、那句话的数 19982/19983/19991，三次 DOM 求值分别 1/1/0 ms；缩放推到 320 px/s，滚动宽度涨到 6,401,472 px 而卡片仍是 8 张。同一台引擎里那份三段对照页仍是 7 s 内画出 3 段。这一轮的**第一次采样（2.2 s）被尺子自己标 `WRONG_PAGE` 拒了**——它现在只认 `location.href` 与 `--url` 逐字相同的那一页。另外 `tests/desktop_ts_check.py` 改了失败报告：断言那句中文在 node stderr 的**开头**，以前只截尾巴，报上来的全是 `at file:///…`，看不出红在哪条断言。
- 1.132 交的是「一次读入」那一半的引擎侧，外加把那把量界面的尺修到可以说真话。`projects` 表多三列摘要（`clips`/`assets`/`content_ticks`），写入随文档一起刷新，`PRAGMA user_version` 从 2 走到 3，旧库在打开那一刻把 `clips IS NULL` 的行数一遍补上，于是 `GET /v1/projects` 直接把首页要的数交出去；`store.refreshProjects()` 不再为了算片段数把列表里每个工程整份下载一遍。门禁 `tests/projects_summary_check.py` 打印的是实测原文：300 段那一行 `clips=300 assets=1 content=21168000000 (revision 1)`、「两行列表 260 字节 vs 一份 301 段的工程 201,712 字节」、「旧行在开库时被数出来，user_version=3」、「renderer: refreshProjects asks once, and its type says so」；5 条突变逐条红在自己那条断言上（摘要不再写、时长换成别的数、列根本不建、旧行不数、首页退回逐个下载）。装机复核（冻结引擎自报 1.132.0，渲染层是从新 `app.asar` 里抽出来的那份，深链同一份两万段工程）：1.131 指认的「同一份工程取三次」变成了**一次**（`renderer_scale` 报 `big_responses:1`，那份工程线上实测 12,103,211 字节），可页面照旧一段都没画出来。**这一版真正的收获是那把尺以前在说谎**：DevTools 端口按 `Date.now()%97` 挑，撞上本轮留下的两个僵留 headless Edge（同一个 `9816` 被两个实例占着），`/json/list` 于是答的是**别人的标签页**——这一轮头一次跑出的那句「2 ms 答 clips:3、退出码 0」量的根本不是两万段那一页；进程取样取的又是全机最大的 msedge。两处都改了：端口必须先能 bind 才用、附着的页必须与 `--url` 逐字相同、内存只算本次 profile 那一棵进程树，并且先把引擎那边的片段数与线上字节打出来再谈页面。修好之后重测的真数：对照页（3 段）在 6.7 s 画出 `clips:3 nodes:410`，本次树 14 个进程共 742 MB、最大的一个 180 MB；两万段那一页在 11.7 s 时自己的树 2,994 MB（渲染进程单独 2,370 MB / 10.41 s 用户态 CPU），随后那个进程消失了（同一次采样里进程数 14→8、最大的换了 pid、CPU 从 2.04 s 重新起算），此后 108 秒里 12 次求值全部超时。画不出来那一步这次抓到了名字：调试器中断（`Debugger.pause`，未压缩那份 bundle）四轮停在同一串栈`(anon)<(anon)<TrackRow<…react…`，也就是**第一次渲染**——那时 `view` 还是 null，而 1.131 定的规矩是「没量到视口时不裁」，于是首帧照样把两万张卡片建完，第二次渲染裁到 14 张已经太晚。
- 1.131 做的是「两万段」那条已确认缺陷的第一块：时间线不再按整条时间线的长度建东西。`desktop/src/timelineWindow.ts` 一处算窗口（两边各多涂两秒、没量到视口时不裁、滚过头时贴在结尾），片段卡片与 `rulerMarks` 都问它——后者以前从 0 数到两万秒，是同一个毛病的第二处。被挑中的段即使在窗口外也照旧建，框选拖过的跨度整个并进窗口（于是按 DOM 矩形判定命中的那一步一个字没改），松手收回。量的数：1,280 px 视口 / 一秒 100 px 时两万段只建 14 张卡片（筛 2 ms）、同屏尺子刻度 4 道；门禁 `tests/desktop_20k_check.ts`（12 条突变逐条红在自己那条断言上（窗口与尺子的算术 8 条、视图接线 4 条））。**但两万段还是没画出来**：页面照旧不应答（这一条当时写的「2,923 MB 降到 1,821 MB」在 1.132 撤回：那把尺取的是**全机最大的 msedge 进程**，混进了这台机器上开着的别的浏览器，不是这一页的数；按本次 profile 那一棵进程树重测的数写在下一条）——浏览器网络日志指认剩下的那块是启动把同一份 12,103,495 字节的工程取了三次（外加列表把另一个工程也整个读一遍），留下三份两万对象的图。下一次要有用，就把「一次读入」做对，判据已经在仓库里：`node scripts/renderer_scale.cjs --url <地址> --budget 90`，三段对照工程 2 ms 答 `clips:3, nodes:412` 并退 0，两万段退 1。

- 1.130 交付的是「一键色彩管理」——它一直挂在下一轮入口第 1 条里：`clip.color_manage {clip_id, source_space, display_space}` 一次写下 `source→linear` 与 `linear→display` 两个转换节点，并给这两个都盖章 `purpose: "color_manage"`；`source_space: null` 是**按章**取下，所以「取下以后逐字节回到套上之前」是有门禁撑的一句话，而不是靠猜哪两个节点像是色彩管理。中间原有的节点一个不动；再套一次顶替同一对而不是叠第二对，这条也有断言。为什么要它：调色节点作用在**存储值**上，同一条曲线在线性光与在 sRGB 上是两张图——六档灰实测按存储值调 [0,6,24,70,186,253]、套上「sRGB 读入 / Rec.709 输出」调 [0,20,44,103,183,252]（中档差 33 级），而编译表对独立写出的 sRGB 分段函数与 BT.1886 最多差半个色阶；两端选同一个空间时这一对编译成「不存在」，导出与完全不套逐档相同。`COLOR_MANAGE_LIMIT` 算的是「取下旧的以后还剩几个位置」而不是数空格——这是 1.126 那条「额度只挡扩张、不锁死」的规矩在节点层面的样子（套着的八节点链还能换空间）。界面那两张下拉菜单的候选来自 `capabilities.color_spaces`（与契约 `ColorSpace` Literal 一处定义，壳层检查逐字核过），「现在套的是哪一对」「还剩不剩两个位置」「只剩一只章」三句判断只写在 `desktop/src/colorManage.ts` 一处。29 条突变（引擎 16 + 界面 13）逐条红在自己那条断言上；其中音频片段那一格在第一版门禁里根本走不到（音频素材放上了视频轨，先被 `TRACK_KIND_MISMATCH` 挡住），修正夹具之后那条守卫才被证明是承重的。同时修掉 README 表格里两条被粘在同一行的行，并补了 `tests/docs_shape_check.py`——文档表格的形状以前没有任何检查读过。发布验收：空闲机单独跑 `tests/suite_check.py` **87/87**（新增 `docs_shape_check.py` 与 `released_package_check.py` 两份门禁），`tests/desktop_ts_check.py` 43 份壳层检查全过（含新的 `desktop_colormanage_check.ts`），`ruff check`/`format` 与 `npm run typecheck` 干净，`scripts/build_engine.py --verify` 通过，`npm run dist` 后根 `AgentCut.exe` 与便携版逐字节相同。

- 1.129 把交付格式接进了那张闭合预设表：`OUTPUT_CONTAINERS` 多一项 `mxf`，两条新预设 `mxf-prores-422hq`（prores / `yuv422p10le` / PCM 24 位）与 `mxf-mpeg2`（mpeg2video / `-q:v 5` / `yuv420p`），界面与 Agent 读的都是 `capabilities().output_containers` 与同一份预设清单，没有第二处格式表；文件名后缀与交付前复检都从预设的 container 来。MPEG-2 的旋钮是量化器不是 crf，所以 `_preset` 多了一个 `quality`，`output_args` 多一条分支——把 crf 交下去会得到 `-crf None`（这条是被突变量出来的，不是想象）。MXF 只接受 48 kHz 音频轨：这台 FFmpeg 在 44.1 kHz 上直接 `only 48khz is implemented` 拒写文件头，于是 `output_args` 一处按计划阶段就回 `MXF_NEEDS_48K`（点预设、点当前采样率、给两条出路），且只按容器判——同一份 44.1 kHz 工程改投 mp4 照旧排得出计划。真机量过：两条预设各导出一条 2 秒成片，ffprobe 的 `format_name` 含 mxf、视频 codec 分别是 prores 与 mpeg2video、`pix_fmt` 与预设一字不差、音频 48000 Hz pcm_s24le、时长都 2.000 秒（658 KiB / 634 KiB），尾部一帧解出来正好 320×180×3 字节。门禁 `tests/mxf_check.py`（表、argv、两条真实导出、两路拒绝、mp4 不受影响），4 条突变逐条红在自己那条断言上；`MXF_NEEDS_48K` 也进了引擎错误码中文表（138 个码 0 个落到英文）。**发布复验（冻结引擎 1.129.0）**：真实任务队列各出一条母带，ProRes 684,601 字节、MPEG-2 654,905 字节，两条都 `succeeded` 且 `output_checked` 为真，任务自报的复检句里容器是 mxf、两路流分别是 prores/pcm_s24le 与 mpeg2video/pcm_s24le、2.000 秒尾部可解码；文件名少 `.mxf` 被契约拒，44.1 kHz 求 MXF 计划回 `MXF_NEEDS_48K` 并点出预设 id，同一工程投 mp4 照旧 200。两处既有门禁的封闭清单计数随之改动（预设 14→16 条、预设键多一个 `quality`）——这两条本来就是「加一种交付必须是一次看得见的改动」
- 1.128 把 1.127 那条有名字的命令接到鼠标上：边把手把 `event.altKey` 交给 `trimClip`，`desktop/src/splitTrim.ts` 一处把拖动所要的窗口读回 (edge, delta_ticks)，判据是**重算回去必须正好是所要的那个窗口**——片头动了但源没跟着走、两头一起动、一格没动、只是划动源窗口、源与时长都动而位置没说，五种都退回普通 `clip.trim`，所以那条被命名的命令不会说得比做得多；涟漪与整对联动移动根本走不到这里（`!ripple && bypass && clip.link_id` 一处判断），历史里这一步念「分边修剪（J/L cut）」。壳层检查把 9 种窗口各判一次，并钉住三处交接（边把手交 altKey、换算只有一处、op 在渲染层只出现一次）；7 条突变逐条红在自己那条断言上，其中「源与时长都动而位置没说」这一格是补出来的——少了它，删掉那条守卫仍然 9 条全绿，也就是门禁当时说不出这条守卫为什么在。两个边把手的悬停说明各自写上手势本身（「Alt 只动这一边（音画链接时就是 J/L cut）」，壳层检查数的是两处）。**装机实测抓到一句假话**：真按 Alt 拖过两次之后，声音比画面长的正是 2,275,560 ticks——不足一帧，而检查器那句念「比基准长 00:00:00:00」。音频按采样走、采样格比帧格细，这种差是真的存在，时间码却把它读成「什么都没差」。差值的格式化因此收成一处 `time.ts:offsetWords`（够一帧用时间码，不足一帧用毫秒／微秒），视图那一处只准走它，壳层检查钉住「同一句里不许留着会念零的那一个」，并钉四种量法：整秒、32.3 毫秒、负数、一个采样（21 微秒）；打包产物里重读到的是「以画面 pic 为基准 · 声音 tone：比基准长 32.3 毫秒」。突变一共 11 条，逐条红在自己那条断言上（第 9 条是读了输出才认下的：它红在 `actual: '32250 微秒'` 对 `expected: '32.3 毫秒'`，正是那条断言）。
- 1.127 交的是「链接只能整对动」这一笔账：`clip.link_split_trim {clip_id, edge, delta_ticks}`只动被点名那一位的 head 或 tail（delta 向右为正），伙伴两边不动，`link_id` 和各自的`link_source_offset_ticks` 原样留着，所以剪完是一段**有意为之**的失步，由 `link_status` 的`differences` 按「相对基准」报出 ticks——基准那一处由 `_link_anchor` 一人决定（`link_status` 与`clips.link_reconcile` 走同一个函数，界面念差值也读同一份 `differences`，不许有第二套）。绝对窗口在这条命令里算完就交给普通修剪同一条 `_trim_clip`，动画时钟偏移与变速曲线的切片因此不可能分家。「拉回同步」= `clips.link_reconcile {link_id}`：除基准外每个成员回到基准的窗口，源入点用「基准源入点 - 基准偏移 + 自己的偏移」，一条命令一个 revision；已经同步回 `LINK_IN_SYNC` 而不是写一笔空账，回不去回 `LINK_RECONCILE_NO_ROOM`（点名哪一段、缺多少 ticks：往回不够源还是往后不够源）。拒绝都是点名的，且 `available_ticks` 是量出来的余量不是猜的：`LINK_SPLIT_NOT_LINKED`、`LINK_SPLIT_NO_MOVE`、`LINK_SPLIT_NOT_ALIGNED`（视频按 `frame_ticks`、音频按 `timebase/sample_rate`，与新抽出的 `track_quantum` 同一个函数——验证器原来那两处内联算法也一并收成它，外加 `clip_source_end`一处管「这段窗口在源里到哪里」）、`LINK_SPLIT_EMPTY`、`LINK_SPLIT_NO_ROOM`；锁成员所在轨先被`TRACK_LOCKED` 挡下。界面没加第四只手：鼠标入口就是既有的 Alt 单选 + 拖那一路，检查器那句中文改读`desktop/src/linkOffset.ts`（一处，视图不许自带时基常量、不许在引擎的数上再做算术），历史里两条新 op各有中文名。**成片量的那一刀**：两个两秒镜头各带自己的声音，把前一个的画面尾剪短一秒、后一个的画面头向左多要一秒（源里有这一秒），这一刀就是同一批次里的两条命令；导出后 1.5 秒处画面从 (255,0,0) 变成(29,200,31)，而那一刻 440 Hz 与 FFmpeg 解出来的 PCM 相关幅度切前切后都是 1446 counts、880 Hz 是 0.0——控制组就是同一条时间线不剪再导一次，两边同窗同算法，所以差的只有画面。量的这台 FFmpeg 的 `bandpass`在差一整个八度处仍报 -31 dB，故频率这条断言改用 PCM 上的余弦相关，不用滤镜带通。门禁`tests/jlcut_check.py`（两条命令各配一次真实导出、九条拒绝 dry 与提交同答、能力表里两条 op 必须下发——只在契约类里出现而不在能力表里出现的命令，Agent 是找不到的）与第 42 个壳层检查`tests/desktop_jlcut_check.ts`；16 条突变逐条红在自己那条断言上（红在哪一条都看了输出，不是数个数）。这轮新加的门禁还抓到一个只长在新代码上的真缺陷：分边修剪要在批次**中途**读自己那条轨，指到一条不存在的轨时裸 `next()` 抛出的是 StopIteration，HTTP 那边就是 500——现在 `_clip_track` 和验证器回同一个 `MISSING_REFERENCE` 并点名片段，检查里那条 ghost-track 的 case 断的就是它。**发布复验（1.127 打包产物，冻结引擎自报 1.127.0，根 `AgentCut.exe` 与便携版 `cmp` 一致，189,869,491 字节）**：能力表下发两条新 op；Agent 侧一次修剪批次把工程从 1 推到 2，画面 0–1 秒、声音 0–2 秒，`preview-manifest` 的 `differences` 报的就是那一秒（基准自己那条恒为零）；对源不够长的那条链接点拉回，得到 422 `LINK_RECONCILE_NO_ROOM` + `{clip_id: ap_b, wanted_ticks: 70560000, available_ticks: 0}`，工程停在 2。界面侧从 `app.asar` 取出渲染层跑真点：单击画面片段就按联动选中这一对（`vp_a`+`ap_a`），检查器念「以画面 red 为基准 · 声音 tone440：比基准长 00:00:01:00」——念素材的名字，不念内部 id（`asset?.label || clipId` 一处兜底，壳层检查钉住这条）；点「拉回同步」得到「音画同步 · 2 段」，历史写「拉回音画同步 · r7已原子写入」，6→7 一次。
- 1.126 把「一批能装多少条编辑命令」从三处字面量收成一个量出来的数。契约的 `EditBatch`、能力表的 `max_commands_per_batch` 与界面那句「新素材与轨道过多」原来各写着 100，于是界面挡的与引擎挡的不是一回事。曲线是在这台机器上量的（一次写入 + 读回整份工程）：250 条 0.05s、1000 条 0.21s、2500 条 0.57s、5000 条 1.32s，累计 8750 段时工程 JSON 5.7 MiB；定 2500 是把「一秒内写完读回」那一格落成数字，只有 `MAX_COMMANDS_PER_BATCH` 这一处，能力表和界面读它。界面在没有能力表时不猜数，直接让引擎去拒（它那句一定比界面猜的准）。门禁 `tests/editing_check.py:batch_cap_suite`：契约与能力表同一个数、到上限收、多一条点名拒；突变一条红（把能力表抄回第二份字面量）——把常数本身改大是量出来的判断，测试不代劳。装机实测（打包引擎自报 1.126.0，能力表下发 2500；渲染层取自 app.asar）：在 150 段、150 个素材的工程里多选 148 段一次复制（存储里 178 KiB、148 段 148 素材），整页换新进程打开空工程点「粘贴」——这一组要 150 条命令，旧的 100 上限会当场拒掉；现在它一次进去：那个工程从 revision 0 到 1，148 段、148 个素材、一条轨全在。
- 1.125 交付的是「复制不该只活一次」：`README`/`optimization` 都写着剪贴板仅本次应用会话，现在三份都跟着这台机器走——片段复制、关键帧节奏、素材上那对入出点，写进 `localStorage` 前先过形状门（`clipboardStore.isClipClipboard` / `isCopiedKeys` / `isSourceMarks`），认不得的一律当没复制过，而不是拼出一条对不上原因的引擎拒绝；node 里没有 `localStorage` 这个全局，所以读写都过 `browserStore()` 一道判断，壳层检查照跑。真正要花工夫的是跨工程那笔账：`asset.import` 只认**这台引擎**发过的那张探测记录，所以上一次运行留下的那份复制在粘之前，要把目标工程里没有落点的素材重探一遍——「算不算已有」与 `pasteCommands` 共用 `clipboardAssetMatcher` 一处判断（不许有第二套），要探的路径取 `verified.path`。第一版取的是 `reference`（`asset.import` 之后引擎在那儿存的是 probe_id），`/v1/media/import` 当场回 422，装机实测第一次点粘贴就是这么红的。装机实测（打包引擎自报 1.125.0 + 从 `app.asar` 取出的渲染层）：工程 A 里点「复制选中片段」落进存储 1431 字节、带 probe `871be121cde14820`；整页换新进程打开空工程 B，「粘贴」不用重新复制就是可点的，点下去 B 从 revision 0 到 1，新轨新段新素材的 probe 变成 `daa560c9b9ec432a` 而 `content_sha256` 还是同一份 `5e52cd41…`——重探真跑了、用的也是这张新记录；再把素材改名、开第三个工程点粘贴，界面回「这份复制里的 1 个素材现在读不到 板（…\media\board.mp4）。把文件放回原来的位置、或先把它们导入目标工程，或回原工程重新复制一次再粘。」，那个工程一个字都没动。门禁 `tests/desktop_clipboard_check.ts`（第 41 个壳层检查）：形状门、往返、坏 JSON、清空真删、要探哪些与探哪儿、视图那一处读写；6 条突变逐条红在自己那条断言上。
- 1.124 给调色图加的是**结构**而不是新算式：并联的一支可以又是一台混频台（`GradeBranch` 收了 `GradeParallel`），树仍塌成每通道一张表，`node_function` 的递归早就在了。真正的改动是三处：支路路径（`gradeGraph.mixerAt`/`mapMixer`/`resolveMixerPath`，走不通就缩短，检查器不会变空白）、有界的树（`GRADE_MIXER_DEPTH = 3` 层混频台，一棵树的操作数仍吃 `GRADE_NODE_LIMIT = 8`，两个数走 `capabilities.grade_limits`）、每一层自己的 `weights`/`blends`；「把这一支变成并联」先只装这一支自己，所以那一步不改画面。跨通道的矩阵与 3D 表仍然进不了支路。跟着树走的还有采样网格（`grade._leaf_operations`）与自动调色那句「有没有人已经在拉黑白场」（`autograde._holds_levels`）。量的数：里层权重换向让表动 4.5 级；一层壳逐位不变；三层收、四层按 `nest` 拒、11 个操作按 `operations` 拒，拒了不涨 revision；成片六档灰带 [0, 2, 10, 30, 94, 253] → [40, 42, 46, 58, 101, 253]，与独立递归参考最大差 2.5 级。门禁 `tests/grade_check.py:tree_suite` + 第 40 个壳层检查 `tests/desktop_mixertree_check.ts`；旧的两条「嵌套必拒」口径改成「跨通道必拒、越深必拒」。同一条链里多张 3D LUT 一并量了：`grade_stages` 每张自己成一段，`grade_filter` 按表体哈希为每张写一个 `.cube`（同一张放两次只写一个文件、导出串里仍是两段）；顺序在成片上定住，用的是两张不相换位的 2³ 置换（纯红 (231,29,20)：先对调再轮转 (27,230,18)，反过来 (230,18,28)，同一张放两次 (229,28,19) 回到原片，都在整数置换的理想值 2 级以内），夹在两张中间的那条单通道曲线读的是「前一张换完之后」的那一路通道（夹在中间 (28,230,39)，挪到链首 (27,209,18)）；预览几张都不进 `preview_manifest`，界面上每张立方各写一张卡片、且卡片上没有强度可标（`GradeLut3D` 契约里就没有 `mix`，`lut3d_preview` 为假是原因）。门禁 `tests/lut3d_check.py:chain_suite` 与 `tests/desktop_graph_check.ts` 的立方卡片；这一段配套的突变引擎侧 8 条、界面侧 3 条，逐条红在自己那条断言上。**发布复验（1.124 打包产物，冻结引擎自报 1.124.0，根 `AgentCut.exe` 与便携版 `cmp` 一致）**：Agent 侧写一棵树加两张立方，读回外层 ×1/×2、里层 ×2/×1 与里层自己那份混合表；`render-plan` 的 argv 里有两段 `lut3d=file=`，控制组是同一条链把两张立方 `enabled` 关掉再导一次，整帧 57600 个像素里 43722 个被换过、最大单通道差 231 级；`preview-manifest` 交回的浏览器阶段里没有立方那一段。界面侧从 `app.asar` 里取出渲染层跑真点：外层卡片写「2 支 · 加权 ×1/×2」，里层栏写「2. 并联 → 1. 色调曲线 / 2. 色调曲线」，`↳进这一支` 进去后 `#grade-b0-weight` 读的是里层那份 2.00，`↰上一层` 回来读外层的 1.00；点「套并联」= 一条命令、revision 1→2，新那台只带它自己那一支、权重表为空（均分），画面不改。**这一轮抓到一个真回归**：`current` 改成「路径尽头那台混频台」之后，链上非混频台节点的整块控件（曲线点、强度、混合方式、换一张表）整块消失——装机实测里点立方卡片什么面板都不出来才发现。收成一处 `chainFieldsFor(head, walked)`，视图只准走它，`tests/desktop_mixertree_check.ts` 同时断那张表与视图里那一处调用；四条突变各红各的（返回 null、丢 `walked` 判、丢并联判、视图改成自己算路径）。修复重打包（渲染层包 `index-BcIgbZX8.js`）后再从 asar 里取出来点一遍：链上的曲线卡片出曲线编辑器，立方卡片出「预览不生效、导出生效」那一段且面板里 `input/select` 计数为 0。
## 下一轮的具体入口（截至 1.126，仍未开工）

这一节只登记挡在某个不变量、或挡在某个还没验收的量上的活；已交付能力的逐条对账在 `docs/optimization.md`（1.126 对过一遍：写已完成的都点得到模块或检查文件）。下面两项在 1.120–1.126 之间没有被顺带做掉，所以还在这里。

1.118 交付的是**能力**缺口（路径遮罩的形状动画），1.119 是**手感**缺口（时间线上一次抓一组针），1.120 回到调色图上补了
并联节点的分支权重（混频台那一排旋钮）。还欠着的，按"先能力、后手感"排：

1. **色彩节点图的分层与连线**（README 尾注、帮助页、本文件都写着未实现）：图层节点的连线与第二路输入，以及线性光里的**基色/色域矩阵**那一半。传递函数那一半的色彩管理已由 1.130 的 `clip.color_manage` 交付（一对盖过章的转换节点：素材读进线性光、中间在线性光里调、交付按显示端写回去），仍没做的是 display_p3 / BT.2020 之间的 3×3（跨通道，塌不进「一条链塌成一张每通道表」这条不变量）、按文件标签自动判定来源的 ICC/ACES，以及 HDR 传递函数。地基已在 1.84（有序阶段列表）与 1.103（3D LUT 自成阶段）里；缺的是“节点有第二路输入”这一维。
   **这一维已经量过了（1.119 之后，本机 `desktop/resources/bin/ffmpeg.exe`，两片 2×2 实色 PNG 复合再读回像素）**：
   - 两支画面喂进同一个阶段就是 `split` 出来两条标签链，再 `[A][B]blend=all_mode=<模式>`：`screen` 把 (192,32,32) 与 (32,32,192) 叠成 **(200,59,199)**（解析解 (200,60,200)，差的 1 是这次量法的往返），`addition` → (223,62,222)，`multiply` → (23,3,23)，`overlay` → (145,6,46)，`difference` → (159,2,160)。先 `format=gbrp` 两条各走一遍再 blend，数一模一样；`format=rgba` 也一样。
   - **`blend` 的表达式里 A/B 是 0..255 的原始采样值，不是归一化的**。`all_expr='clip(A+B,0,255)'` 与 `all_mode=addition` 逐字节相同（223,62,222）；按归一化写的 `1-(1-A)*(1-B)` 出 (255,126,189)（错得离谱但不报错），而把结果留在 0..1 的 `1-(1-A/255)*(1-B/255)` 直接出 **(0,0,0)**——写错尺度是**静默出黑画**，不是报错。所以模式清单与算式都得引擎持有，界面不许自己拼 expr。
   - **两支尺寸必须预先对齐**：`[4x4][2x2]blend` 在 configure 阶段就死（`bottom parameters (size 2x2)`），而且只在真跑 FFmpeg 时才报——所以第二路输入进 reducer 时就要把尺寸/格式对齐当作写入条件，不能推到导出时才试。
   动契约之前剩下的只有一条没量：预览侧（浏览器）拿什么复现这些模式——CSS `mix-blend-mode` 的名字与 FFmpeg `blend` 的名字不是一一对应（例如 overlay/difference 的 Alpha 处理不同），这条要在 `preview_manifest` 出面之前先逐模式量过，量不齐的模式就别下发（与「滑动的『滑』故意不做」同一口径）。
   **这条也量过了（同一对实色，浏览器 canvas `globalCompositeOperation` 逐模式读回像素，与 FFmpeg 那份对照）**：
   - 先做一次**空量**钉住量法本身的偏差：`color=` 那片实色经 PNG 再读回来是 (191,32,31)／(32,30,191)／(254,127,0)——每通道差 0..2；而 `blend(x,self)` 用 `lighten` 原样返回同一组数，所以偏差在**夹具的取色路径**上，不在 blend 上。上面那张表要先按这个还原再看。
   - 还原之后两端一致：screen 两端都是 (200,60,200)；FFmpeg `addition` 与浏览器 `lighter` 都是 (224,64,224)（两端都在 255 饱和）；multiply (24,4,24)；overlay (145,8,48)；difference (160,0,160)；min/darken (32,32,32)。**所以模式清单可以两端共一份**：引擎下发 id 与 FFmpeg 的 `all_mode=` 名，界面把同一个 id 映到同名的 canvas/CSS 复合词；没逐端对过数字的那几个（color-dodge、hard-light 这类）不下发。
   - （1.120 把并联节点的分支权重交付了：`GradeParallel.weights`，见停放点那一条。剩下的还是这一条第二路输入。）
   - 一条还没量的边界留着：第二路**带透明度**时两端是否还一致——1.94 那条「两层一叠就把 (192,32,32) 与 (32,32,192) 叠成 (222,61,220) 的亮边」的前车之鉴就是预乘 Alpha，这条要在支持半透明第二路之前先量。
2. **多目标跟踪**（长时遮挡 1.85 已能重新找回，但一次还是一个目标）。曾经的另一半「清晰的逐帧动画」已在 1.123 交付：两端都认的算式就是那份共用的窗表（`animation.sharpen_schedule`），不要再按 1.98 那句「没有逐帧形式」拒绝。
3. **两万段画得出来（1.133）、命令键位一张表管到底（1.134 + 1.135，共 21 条）**。这一节剩下的两条：五十万段这种量级这台机器上没量过（筛与数仍是每条轨道、每次渲染把 `Object.values(project.clips)` 走一遍，两万段实测筛 2 ms、每一次 DOM 求值 0-1 ms，但那不是五十万段的证据）；表外面故意留着一批跟着焦点与监视器走的键（方向键与 Home/End 挪播放头、I/O 与 Alt+X 进出点、K/L 播与停、空格、Esc、F1/F9/F10、滚轮那两条，以及 Backspace 与「=」两个别名）——同一个键在两个监视器上是两件事，把它们塞进表里只会让那张表看起来谁都能改、其实改了没用。要扩得先把「按上下文分叉的键」定义清楚。**1.138 发布前在 1.137 那份包上复量过两万段**（冻结引擎自报 1.137.0，渲染层从那份 `app.asar` 抽出，同一台实例）：`node scripts/renderer_scale.cjs --url <两万段深链> --budget 90` 在 7 s 报 `painted:13, nodes:487`、退出码 0，工具条那句照旧念「窗口外还有 19987 段没有画」，本次 profile 那棵进程树峰值 817 MB（最大单进程 207 MB）、用户态 CPU 2.22 s，页面每一次 `Runtime.evaluate` 2 ms 内回话；启动读整份工程**只有一次**（`big_responses:1`，那份工程线上 12,103,211 字节）。另外用网络日志独立数过一遍：`GET /v1/projects/{id}` 在一次启动里恰好 1 次（1.131 记的三次早已不存在），列表那一条每 4 秒 426 字节的摘要，不带任何工程正文。

4. 复验口径照旧：`uv run python tests/suite_check.py` 空闲机器单独跑，壳层 `uv run python tests/desktop_ts_check.py`（数目以它的输出为准，不靠记忆），新断言一律配突变且**每条突变要红在自己断言的消息上**；突变脚本改完源码要**按字节还原**（这些 `.ts`/`.tsx`/`.css` 是 CRLF，Python 文本模式写回会把整份文件换成 LF），跑完再逐条重跑一次确认恢复；发布物 `uv run python scripts/build_engine.py --verify` + `cd desktop && npm run dist` 后根 `AgentCut.exe` 与便携版 `cmp`，界面类改动再用打包 exe + Chromium 真点真拖。

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
- 新增命令需同步契约、reducer、capabilities、文档和验收；MCP 从契约生成 schema。新增或改名一个错误码，必须同时补 `desktop/src/engine.ts` 的中文提示——`tests/error_vocabulary_check.py` 会把两边的词表对起来，缺一条就红。
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
