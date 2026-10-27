# v1 接口约定

权威 schema 在 `GET /v1/contracts`，OpenAPI 在 `/openapi.json`；不要维护另一套手写命令定义。
HTTP 使用 `Authorization: Bearer <AGENTCUT_TOKEN>`。JSON 请求严格校验类型和未知字段。

## 入口

| HTTP | MCP 工具 | 语义 |
|---|---|---|
| GET /v1/capabilities | editor_capabilities | 实际可用能力 |
| GET /v1/contracts | editor_contracts | 权威 JSON Schema |
| GET /v1/agent/manifest | 资源 agentcut://manifest | 一份机器可读的 agent 契约（1.307）：全部路由 + 全部 MCP 工具（含 inputSchema 与只读位）+ 能力表 + 错误形状 + 三条剪辑配方；桥与文档都从这一份派生，不再各抄一份 |
| POST /v1/projects | project_create | 幂等创建 |
| GET /v1/projects?limit=100&offset=0 | project_list | 分页项目摘要 |
| GET /v1/projects/{id}?revision=N | project_get | 当前或历史项目 |
| GET /v1/projects/{id}/history?limit=100&offset=0 | project_history | 版本审计摘要 |
| POST /v1/projects/{id}/edits | timeline_edit | 批量命令 |
| POST /v1/projects/{id}/restore | project_restore | 历史恢复为新版本 |
| POST /v1/projects/{id}/clips/{c}/silence | clip_silence | 只读扫描静音并取回剪切命令（`apply`/`dry_run` 在该工具里固定为 false） |
| POST /v1/projects/{id}/sync | clips_sync | 多机位对齐（1.288）：2–8 段按共享声音的归一化互相关算偏移（10 毫秒包络、重叠内去均值、折到帧），交回普通 `clip.move` 计划；弱峰/同轨/变速/越界/同拍按名字拒绝，`apply` 才写入，工具侧固定只读 |
| GET /v1/projects/{id}/edl?track_id={t} | project_edl | 一条画面轨的 CMX3600 剪辑表（1.285）：整帧不丢帧，直切、100% 速度、视频片段；转场/变速/非画面/分数帧率按名字拒绝并点名，读一遍不改 revision |
| POST /v1/projects/{id}/tracks/{t}/rough-cut | track_rough_cut | 整轨粗剪（1.284）：逐片段右到左取同一份粗剪计划（1.286 起同样接受 `place=head|lively|center` 与 `transition_ms`），合并成一个批次；不能扫的片段带原因跳过，一条都剪不动时 `ROUGH_NONE`；`apply` 才写入，工具侧固定只读 |
| POST /v1/projects/{id}/clips/{c}/rough-cut | clip_rough_cut | 按镜头粗剪（1.283；1.286 起 `place=head|lively`、1.287 起还可 `center`；1.287 起 `transition_ms` 给接缝叠化）：同一套颜色差找硬切，每个镜头只留前 `keep_ms`（默认 1500，100–30000），计划是从右往左的普通 `clip.split` + 带 `ripple` 的 `clip.trim`；`apply` 才写入，工具侧固定只读 |
| POST /v1/projects/{id}/clips/{c}/scenes | clip_scenes | 按镜头切分（1.282）：引擎用**颜色差**找硬切（64×36 RGB 相邻帧差；纯红→纯绿 scene 分是 0.0、这里是 0.50），门槛/最短镜头/切点上限只在契约里（`capabilities.limits.scene_*`）；交回普通 `clip.split` 计划，`apply` 才写入，工具侧固定只读 |
| POST /v1/projects/{id}/audio/beats | audio_beats | 只读听节拍（1.268）：`asset_id` 按素材 1:1，`clip_id` 按片段的恒定速度映射回时间线；交回 `beats` ticks 与可选的 `bpm`，写入仍走 `marker.set`，切点仍由 `marker_split` 决定 |
| POST /v1/projects/{id}/tracks/{t}/silence | track_silence | 整轨扫描：逐片段报告跳过原因，合并成一条命令计划（1.79 起有工具；`apply`/`dry_run` 在该工具里固定为 false，命令交回 `timeline_edit` 写入） |
| POST /v1/projects/{id}/clips/{c}/color-space | clip_color_space | 只读：这份素材自己说的色调曲线（`space`），或点名为什么认不出（`reason` + 四个原样标记）；1.150 起有工具，读一遍 revision 不动 |
| POST /v1/projects/{id}/clips/{c}/loudness | clip_loudness | 响度表读数与建议增益；`apply=true` 时引擎一次写入（1.79 起有工具，工具侧固定只读，命令交回 `timeline_edit`） |
| POST /v1/projects/{id}/tracks/{t}/loudness | track_loudness | 整轨响度对齐：逐片段测量并合并成一次写入（1.79 起有工具；`sequence_id` 让它在合成里量那条同名轨） |
| POST /v1/projects/{id}/markers/split | marker_split | 按标记分割：只出普通 `clip.split` 计划，`apply` 才写入（1.270 起也可用 `at_ticks` 直接点名切点，节拍那一趟不必先写标记） |
| POST /v1/projects/{id}/speech-captions | captions_auto | 本地语音识别成字幕线索并取回 `captions.import` 计划（`apply`/`dry_run` 在该工具里固定为 false） |
| `clip.slip` / `clip.slide`（`/edits`） | timeline_edit | 划动素材窗口 / 左右滑移，两侧相邻段各自补让 |
| POST /v1/projects/{id}/mask-track | mask_track | 一组目标一起分析画面，每个遮罩各把自己的路径写成关键帧：读同一段窗口的目标只解码一次，整组落进一个批次（与 `/edits` 同一事务语义）；1.271 起每个目标可选 `estimate_rotation`，点的 `rotation` 写成 `mask_rotation` 曲线；1.272 起角度按上一帧的转向预测，累计满 ±360° 时 `angle_limit_at_ticks` 与 `lost_at_ticks` 同时点名停下那一帧 |
| POST /v1/projects/{id}/clips/{c}/mask-stack/{i}/track | mask_stack_track | 只跟再叠遮罩里的一块（1.269）：写回一条普通的 `clip.mask_stack`，别的块与主遮罩一字不动；路径按 `extra_mask_keys` 抽稀，`track.coarse` 说明额度先于容差用尽；1.271 起可选 `estimate_rotation`，框点的 `rotation` 也一起估；1.272 起同样报 `angle_limit_at_ticks`，累计满 ±360° 时停下并点名那一帧 |
| GET /v1/projects/{id}/frame | preview_frame | 取成片的一帧：导出渲染器算出的 PNG（长边压到 256 便于传输，宽高比不变），附 `sha256` 与真正取样的 tick；`sequence_id` 取合成里的画面 |
| GET /v1/media/cache | media_cache_read | 派生缓存清单：条目、字节、上限 |
| POST /v1/media/cache/prune | media_cache_prune | 按预算整项淘汰派生缓存（LRU），`dry_run` 先看会删什么、`keep` 保护正在看的哈希 |
| POST /v1/media/proxies/prune | media_proxies_prune | 只清播放代理，原片与工程文件不动 |

另有十条路由刻意没有 MCP 工具，因为它们是**给浏览器看的字节流或整包文件**，不是一条命令语义：`POST /v1/mask/preview`（界面用来画遮罩的位图）、`GET /v1/media/{probe_id}/stream` 与 `/file/{name}`、`GET /v1/assets/{asset_id}/stream` 与 `/proxy/stream`（`<img>`/`<video>` 直接放的流，Agent 侧由 `project_asset_urls` 给签名 URL）、`GET`/`POST /v1/projects/{id}/assets/{id}/proxy`（代理的读取与重建）、`GET /v1/projects/{id}/bundle` 与 `POST /v1/bundle`（整个工程 zip 的下载与上传）。这不是缺口：Agent 要判断画面用 `preview_frame`，要引用素材用签名 URL，要搬工程仍走界面或 CLI。

MCP Resource 为 `project://{id}`，返回当前 JSON 项目。MCP 工具结果有 structuredContent 和兼容文本；工具失败设置 isError=true，文本中包含领域错误代码。edit/restore 使用 destructiveHint=true，因为可能删除或替换现有剪辑内容。

项目列表按 id 排序，历史按 revision 倒序；limit 为 1..100。历史 created_at 是 UTC 数据库时间，不是用户本地时间。

## 批量命令示例

默认 30 fps：一秒为 70,560,000 ticks，一帧为 2,352,000 ticks。

```json
{
  "request_id": "edit-20261003-001",
  "expected_revision": 0,
  "dry_run": true,
  "commands": [
    {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "主画面"}},
    {"op": "asset.register", "asset": {
      "id": "a1", "kind": "video", "label": "演示素材",
      "reference": "media://demo", "duration_ticks": 705600000
    }},
    {"op": "clip.add", "clip": {
      "id": "c1", "asset_id": "a1", "track_id": "v1",
      "position_ticks": 0, "source_in_ticks": 141120000, "duration_ticks": 211680000
    }}
  ]
}
```

从演示素材源位置第 2 秒取 3 秒，放在时间线起点。reference 只是字符串元数据，未读取文件。
HTTP body 就是以上对象；MCP 调用参数为 `{"project_id":"项目id", "request":以上对象}`。
create/restore 的 MCP 参数同样将 HTTP 请求体放在 `request` 字段中。

## 命令语义

组编辑能力为 `capabilities.features.multi_clip_editing=true`；HTTP/MCP 均接受以下组命令。每组 1..20,000 个片段，项目仍受既有总量限制；批次仍最多 100 条命令。

| op | 参数主体 | 结果 |
|---|---|---|
| clips.add | clips: Clip[] | 一次添加全部片段；可使用组内转场引用，素材/轨道须先登记 |
| clips.move | clip_ids, delta_ticks, track_map={} | 所有片段增加同一个有符号 delta；track_map 仅映射所选片段的原轨道 |
| clips.remove | clip_ids, ripple=false | 删除全部；ripple 时仅关闭各轨所选片段独占区间，保留转场中其他片段仍使用的区间 |
| clips.split | clip_ids, at_ticks, right_clip_ids | 每个片段在同一绝对切点分割，right_clip_ids 的键须恰好等于 clip_ids |

clip_ids 不得重复；不存在、锁轨、越界、未对齐或最终重叠均整批回滚。移动/添加不改变源时间与动画偏移；移动保留仍有效的组内转场。分割点必须在每个指定片段内部，转场内部拒绝；界面会先筛选实际跨过播放头的所选片段。非法选择/轨道映射分别为 INVALID_SELECTION / INVALID_TRACK_MAP。clips.add 超過 100 个片段仍只占一条命令；跨工程粘贴缺少的素材/轨道会另外占用登记命令。

| op | 参数主体 | 结果 |
|---|---|---|
| track.add | track | 追加轨道，重复 id 拒绝 |
| asset.register | asset | 登记元数据，重复 id 拒绝 |
| clip.add | clip | 添加明确源范围的片段 |
| clip.insert | clip, ripple_track_ids? | 在 position_ticks 腾出 duration_ticks；切开跨越插入点的片段并顺延后续 |
| clip.overwrite | clip | 替换目标轨道 [position, position+duration)；保留两侧内容，不移动其他区间 |
| clip.move | clip_id, track_id, position_ticks | 移动，可换兼容轨道；不 ripple |
| clip.trim | clip_id, source_in_ticks, duration_ticks, position_ticks? | 同时调整位置、入点、时长；省略 position 时保持旧位置。ripple=true 同轨后续顺位右移 |
| clip.trim_linked | 字段同 clip.trim | 对全部同步成员应用同一源增量，ripple 逐轨顺位后续 |
| 交付预设（1.129） | `mxf-prores-422hq`、`mxf-mpeg2` | MXF 容器：ProRes 422 HQ 或 MPEG-2（`-q:v`）＋PCM 24 位 48 kHz；混音不是 48 kHz 时计划阶段回 `MXF_NEEDS_48K`，只按容器判，mp4/mov 不受影响 |
| clip.link_split_trim | clip_id, edge, delta_ticks | J/L cut：只动这一边，伙伴两边不动，链接记录保留；edge 是 head/tail，delta 向右为正（ticks） |
| clips.link_reconcile | link_id | 把其余成员拉回基准片段的窗口，各自保留原来的源入点差值；已经同步时拒绝 |
| clip.color_manage | clip_id, source_space, display_space, auto_source | 一次写下 source→linear 与 linear→display 两个转换节点并盖章；`source_space: null` 取下这一对，链子中间不动；`auto_source: true` 让来源端由素材自带的 `color_transfer` 回答（1.150），认不出按 `COLOR_SPACE_UNDETECTED` 点名拒 |
| clip.roll | clip_id, other_clip_id, delta_ticks | 滚动剪辑：相邻两片段共用接缝平移，总时长不变；超出源范围整笔拒绝 |
| clip.detach_audio | clip_id, audio_clip_id, track_id | 视频内嵌声音拆到指定音轨，原视频静音，自动成对音画链接 |

## 工程打包（迁移 / 备份）

| 方法与路径 | 说明 |
|---|---|
| GET /v1/projects/{id}/bundle | 一个 zip：project.json + media/<asset_id>.<ext> 全部素材；素材缺失返回 410 |
| POST /v1/bundle?request_id=ID（请求体即 zip 二进制） | 流式上传并重新探测素材，原子保存完整快照、探测记录、历史与回执；返回 MutationResult，新工程 revision=0；非法包返回 422 |

工程包 schema=1。上传与导出最多 32 GiB，解包最多 64 GiB，project.json 最多 128 MiB；超限返回 413。素材写入服务生成的隔离目录，不使用包内绝对路径。失败清理本次文件且不留下半成品工程；同一 request_id 和相同 ZIP 字节重试返回同一工程，换字节返回 409。空工程、锁定轨道、组合/链接、文字及工程元数据直接按快照恢复，不作为编辑命令重放。旧客户端应更新调用和响应格式。

导入不会信任包里的路径：解包文件写入本机第一个素材目录，再由媒体引擎重新 ffprobe 产生 verified 记录。
| clip.split | clip_id, at_ticks, right_clip_id | 在时间线绝对位置分割，原 id 留给左半 |
| clip.remove | clip_id | 移除片段；不关闭时间线空隙 |
| transition.set | clip_id, from_clip_id, kind, duration_ticks | 在两个连续画面镜头间添加或修改重叠转场；kind 为 dissolve / dip_black / dip_white |
| transition.remove | clip_id | 移除该镜头的入场转场，恢复与前镜头首尾衔接 |

可以一批同时移动多个片段，最终状态合法即可。源素材必须在分割命令前已经登记。
插入默认只顺延目标轨道；ripple_track_ids 可明确指定同步轨道，必须唯一、包含目标轨道、全部存在且未锁定。位置与时长须在每条受影响轨道上对齐；不兼容的帧/采样时钟返回 TIME_NOT_ALIGNED，整批拒绝。
插入/覆盖使用 Clip 的明确源入点与时长，保留存活区间的源时钟、变速和动画时钟。新右片段 id 为 op + 新片段 id + 原片段 id 的确定性摘要，dry-run 与提交一致，可从返回 Project 读取。部分修剪只有一个存活区间时保留原 id；无需新增 schema 字段。
每批 1..2500 条（1.126 起，随 `capabilities.max_commands_per_batch` 下发）；id 只允许字母、数字、下划线、连字符，最长 64 字符。

## 版本、去重与预演

成功结果：

```json
{"project": {"id": "...", "revision": 1, "...": "完整项目"},
 "committed": true, "replayed": false, "base_revision": 0}
```

- 每个成功编辑/恢复都将 revision 加 1，即使命令没有改变最终可见内容。创建 revision 为 0，base_revision 为 null。
- 创建的 request_id 在整个数据库中去重；编辑/恢复在项目内去重。编辑和恢复共享同一项目请求命名空间。
- 请求指纹包含操作类型、expected_revision 和完整命令内容；JSON 对象键顺序不影响指纹，命令列表顺序影响。
- 重放返回第一次提交时的快照，`replayed=true`；它可能比当前项目旧。要查看现在的状态，再调用 project_get。
- 同一 request_id 携带不同 payload：409 IDEMPOTENCY_CONFLICT。
- dry_run 不保存回执、历史或项目。结果 committed=false，project.revision 是候选版本，不代表数据库已提交。
- dry_run 后提交可复用同一 request_id，仅将 dry_run 改为 false；如果其他人已提交，得到 REVISION_CONFLICT。
- 已提交请求再用相同 id dry-run，会返回 REQUEST_ALREADY_COMMITTED；要做新的预演需新 id。
- 失败请求不保存成功回执；修正失败后可复用 id，但不确定是否已成功时必须原样重试。

restore 参数：`request_id`、`expected_revision`、`target_revision`。恢复完整旧内容，版本计数按当前版本继续增加。

## 错误

HTTP 错误主体：`{"error":{"code":"...","message":"...","details":{}}}`。
命令执行阶段错误带 command_index；最终时间线校验错误带相关 clip id，可能关联多条命令。

| code | HTTP | Agent 处理方式 |
|---|---|---|
| UNAUTHORIZED | 401 | 检查当前服务 Token |
| INVALID_REQUEST | 422 | 按 schema 修正字段和类型 |
| REVISION_CONFLICT | 409 | 读取最新项目，重新规划并使用新 id |
| IDEMPOTENCY_CONFLICT | 409 | 不要用已有 id 表示不同写入 |
| REQUEST_ALREADY_COMMITTED | 409 | 新预演使用新 id |
| NOT_FOUND | 404 | 检查项目、片段或历史版本 |
| DUPLICATE_ID | 422 | 重新选择对象 id |
| MISSING_REFERENCE | 422 | 登记素材/轨道并检查引用 |
| TRACK_KIND_MISMATCH | 422 | 使用对应媒体种类的轨道 |
| SOURCE_OUT_OF_BOUNDS | 422 | 修正素材范围 |
| TIME_NOT_ALIGNED | 422 | 按 details.quantum_ticks 对齐 |
| INVALID_SPLIT | 422 | 切点必须严格落在片段内部 |
| INVALID_SOURCE_RANGE | 422 | 图片源入点恒为 0 |
| CLIP_OVERLAP | 422 | 调整同轨道范围或改用另一轨道 |
| TIME_OVERFLOW / PROJECT_LIMIT | 422 | 降低时间/对象规模 |
| REVISION_OVERFLOW | 409 | 达到版本上限 |
| STORAGE_UNAVAILABLE | 503 | 原请求原样重试，持续失败时检查存储 |

MCP 的连接故障使用 API_UNAVAILABLE。HTTP 超时可能发生在提交之后，不能自动换 request_id。
不可信 Host 在协议入口被拒绝为 HTTP 400，可能是纯文本；MCP 将非领域 HTTP 错误映射为 API_ERROR。

## 契约演进

当前接口 /v1、项目 schema_version=9、数据库 user_version=2 是三个独立版本。
可兼容新增响应字段应提供默认值；未知请求字段当前会拒绝。改变已有命令含义不能静默发布。
影响历史读取的 schema 修改必须设计迁移；影响已存回执的修改还须验证旧请求重放。
先实现并验收功能，再把 capabilities 设为 true。

### schema v5：持久组合与音画链接

Clip 新增 `group_id=null`、`link_id=null`、`link_source_offset_ticks=0`；前两项是 Identifier，源差值为 ±MAX_TICKS 内整数。旧 schema 1–4 无需修改历史快照即可读取。clip.add/insert/overwrite 与 clips.add 的新增默认字段不参与旧回执指纹，保留 v1–v4 请求重放；当前新写入使用 schema 9。

- `clips.group {clip_ids, group_id}`：至少两段设置新的平面组合；null 解除所选片段涉及的完整组合。没有嵌套合成含义。
- `clips.link {clip_ids, link_id}`：至少包含 timed video 与 audio，开始、时长、速度相同。将当前源入点差值记为同步基准；null 解除涉及的完整链接。已有 id 不得与选择外成员隐式合并。此操作不会分析波形、自动对齐、抽取内嵌声音或改变音量。
- `clip.trim_linked {clip_id, source_in_ticks, duration_ticks, position_ticks?}`：使用锚点片段的源入点增量和最终位置/长度修剪整个音画链接，保持源差值与各自动画时钟。无链接时等同 clip.trim；链接已经失步时返回 LINK_OUT_OF_SYNC。所有成员必须未锁轨，最终时钟和源范围统一验证，失败整批不写入。
- `clip.color_manage {clip_id, source_space, display_space, auto_source}`（1.130，1.150 起可 `auto_source`）：一键色彩管理。写下的不是「一个节点」而是**一对**：`source_space → linear` 放在链首，`linear → display_space` 放在链尾，两个都带 `purpose: "color_manage"`；链子中间的原样穿过，一个节点不多删。取下是同一命令把 `source_space` 写成 `null`，它按章删人——只删这条命令自己写过的那两个，所以「取下之后链子回到套上之前」是一句可以逐字节比的话（`tests/colormanage_check.py` 就是这么断的），而手工加的那两个转换节点不在它的职权里：报 `COLOR_MANAGE_NOT_SET` 并说出该谁去删。再套一次顶替同一对（不会叠第二对）；空间没变回 `COLOR_MANAGE_NO_CHANGE`，两端都线性回 `COLOR_MANAGE_IDENTITY`，装不下回 `COLOR_MANAGE_LIMIT` 并交回 `limit/nodes/room`——算的是「取下这一对以后还剩几个位置」，所以满格的八节点链只要那对是套上去的，换一套空间仍然过得去（未套的满格链 room 为 0、七个节点为 1）。候选空间由 `capabilities.color_spaces` 下发，与契约的 `ColorSpace` Literal 同一处定义，壳层检查逐字核过。这条命令只换算传递函数：不动基色、不做矩阵、不读文件的色彩空间标签，不是 ICC/ACES。音频片段回 `INVALID_COLOR`。MCP 那边是同一个口子：`timeline_edit` 把这条命令原样交给 reducer，没有第二份实现。
- `FFMPEG_NO_GRAPH_SCRIPT`（1.147，渲染任务的失败回执）：这条交付的滤镜图超过 `GRAPH_SCRIPT_LIMIT`（12000 字符），只能写成脚本文件交给 `-filter_complex_script`，而**引擎实际拿到的那份 ffmpeg 不认那个选项**（FFmpeg 9 那一支没有；随包的 6.1.1 实测有）。回执里点名是哪一份（版本 + 路径）并说出退路：去掉 `--ffmpeg` 与 `AGENTCUT_FFMPEG` 这两处指向再导一次。为什么不是 FFmpeg 的原始 stderr：`Unrecognized option 'filter_complex_script'.` 既不说是谁，也不说怎么办——1.146 的装机复核就是被这句话绊住的，而它当时同时意味着「打包版一直在用用户机器上碰巧装的那份 ffmpeg」。探测读的是 ffmpeg 自己的 `-h full` 自述（版本横幅在 stderr、选项表在 stdout，两路合起来才读得到版本），按解析出的路径缓存，一次交付不多花那 0.2 s。实测口径见 `tests/ffmpeggraph_check.py`（套件第 101 项）：把限度压到 1 逼出脚本形式，两头都要跑——不认时必须失败且说清是谁、回去的那两个名字；认的时候同一条请求照常出片。
- `capabilities.gamut_matrices`（1.146，1.148 改过两处说法）：基色（primaries）转换表，六档（2020↔709、P3-D65(γ2.2)↔709、Display P3→709、Rec.601→709），每档交 `id/label/source/target/source_transfer/target_transfer/coefficients`（九个系数，行=输出通道、列=输入通道，行主序）。**这一版不接影院 DCI-P3**：那一档的白点是影院基准（约 `0.314,0.351`）、传递特性是 γ2.6，而本表对白点不同的两档是直接拒的（不做半套色适应）；原先名叫 `p3-dci`、label 写着「影院母带到电视」的那一档，存的其实是 P3 原色 + D65 白 + γ2.2，1.148 起改叫 `p3-d65-g22`（preset id 为 `p3d65g22_to_rec709` / `rec709_to_p3d65g22`），`tests/gamut_check.py` 从此断言 label 里不许出现「影院／DCI」、走 `p3*` 档的两条必须把 `D65` 与 `γ2.2` 写在名字里。矩阵由 `src/agentcut/gamut.py` 从 xy 与白点现算，**不是**手抄的表：谁抄这九个数，谁就和另一侧迟早不一致，而这种不一致在成片里只表现为「颜色有点偏」。用它的正确写法是把九个数放进一个 `matrix` 节点，并在它前后各挂一个 `transfer` 把画面抬进线性光再落回目标档（与 `clip.color_manage` 从 1.130 起写下的那一对同形）；`matrix` 那九个数是直接乘在**存储值**上的，单独挂它做基色转换是错的。白点不同的两档会被 `primaries_matrix` 直接拒（本表全 D65，没有色适应那一半）。这一版**没有**界面按钮、也没有新的编辑命令：只有这份表，以及 `tests/gamut_check.py`（套件第 99 项）对它算的账——三条自洽性质加一颗外部锚，加上真导出四份交付实测：中灰 `(130,127,131)→(129,126,130)` 不动、橙红 `(179,79,50)→(216,41,1)` 换档；来回一趟不恒等（蓝 50→40），同形状的对照链自己漂 6 级、矩阵那份再多漂 4 级，成因是 `transfer` 落进线性光那一站仍是 8 位——量化成本记在这里，不靠放宽容差糊过去。
- `clip.link_split_trim {clip_id, edge, delta_ticks}`（1.127）：J/L cut。`edge` 是 head 或 tail，`delta_ticks` 是这一边沿时间线向右的移动量（可为负），只有被点名的这一位动，链接里其余成员两边都不动，`link_id` 与各自的 `link_source_offset_ticks` 原样留着——所以剪完得到的是一段**有意为之**的失步，由 `link_status` 的 `differences` 按「相对基准」报出 ticks。绝对窗口在这一条命令里算出来后交给和普通修剪同一条 `_trim_clip`，动画时钟偏移与变速曲线的切片因此不可能和别的修剪分家。拒绝都是点名的：没有链接 `LINK_SPLIT_NOT_LINKED`、delta 为 0 `LINK_SPLIT_NO_MOVE`、落不在该轨自己的格子上 `LINK_SPLIT_NOT_ALIGNED`（视频按 `frame_ticks`、音频按 `timebase/sample_rate`，与验证器同一个函数）、剪到不留一格 `LINK_SPLIT_EMPTY`、往左够不到 `LINK_SPLIT_NO_ROOM`（交回 `available_ticks`，是这条片段真有的那点源/位置余量，不是猜的）。锁定成员所在的轨先被 `TRACK_LOCKED` 挡下。界面里对应的鼠标入口是一双手：时间线上按住 Alt 拖这条链接的某一边（1.128 起），`desktop/src/splitTrim.ts` 一处把拖动所要的窗口读回 (edge, delta_ticks)，且只在重算回去正好等于所要窗口时才发这条，否则退回普通 `clip.trim`；历史里念「分边修剪（J/L cut）」。
- `clips.link_reconcile {link_id}`（1.127）：把除基准以外的成员逐个拉回基准片段的窗口（位置与时长取基准，源入点取 `基准源入点 - 基准偏移 + 自己的偏移`），一次一条命令、一个 revision。基准由 `link_status` 那唯一一处决定（有画面就用画面），界面念差值用的也是同一份 `differences`，所以「哪一路跑了、跑了多久」和「拉回哪儿」不会是两回事。已经同步时返回 `LINK_IN_SYNC` 而不是写一笔空账；某个成员回不去时 `LINK_RECONCILE_NO_ROOM` 点名是哪一段、缺多少 ticks（往回不够源，还是往后不够源），`LINK_RECONCILE_NOT_ALIGNED` 说明基准那一格落在别的轨的格子上，出路是先修剪基准。
- clips.split 仍明确提供全部片段 id。同一链接在同一绝对切点的右半段使用相同确定性新链接 id；左半段保留原链接。跨轨 insert 共用切分规则。仅分割其中一段时右半段的孤立链接被移除，未切的原链接显示失步。
- 删除后不足两段的组合、缺少 video 或 audio 的链接在最终批状态清理，包括残留源差值。清理仅移除无意义的关联，不移动仍存活的片段。

`GET /v1/projects/{id}/preview-manifest?revision=…` 与 MCP preview_manifest 返回 `links`：每个 link_id 包含 clip_ids、anchor_clip_id、synchronized 与 differences（逐段 position_ticks/source_ticks/duration_ticks/speed_percent）。锚点优先 video；任何位置、源基准、长度或速度差异都报告失步，不自动重设基准。

客户端「联动」开关默认开启，记住偏好；Alt 临时单选/拖动，关闭开关可独立剪辑。组合/链接选择使用连接闭包，Agent 仍需在 clips.move/remove/split 中明确列出所需成员。复制产生新组合/链接 id，未完整复制的音画链接被移除。全组解除需要所有实际受影响轨道未锁定。

片段采用精确帧/采样时钟；手动链接不放宽对齐约束。界面使用相关轨道的公共量化步长，某些分数帧率与采样率组合的最小共同步长会大于一帧。独立速度/转场/覆盖只影响明确指定的轨道，可能失步，当前不提供自动修复。

### schema v4：真实镜头转场

兼容读取 v1/v2/v3；新编辑与恢复写为 v4，旧历史不改写。Clip 新增可空的 transition_in：from_clip_id、kind、duration_ticks。旧 clip.add / clip.insert / clip.overwrite 回执指纹忽略新增空字段，原有默认字段的处理保持不变。

transition.set 的 clip_id 是后一个镜头，from_clip_id 是同一画面轨上紧邻的前镜头。首次添加必须首尾衔接；正时长须对齐序列帧且短于两段镜头。添加时将后镜头及本轨后续片段向前移动该时长，不改变消费的源区间；修改时按新旧时长差移动，移除时反向恢复首尾衔接。其他轨道位置保持，尚无联动音画转场。

同轨重叠只允许明确引用、准确匹配的两镜头转场；三镜头重叠拒绝为 TRANSITION_EDIT_CONFLICT。交叉溶解按轨道相加预乘透明像素，保留画中画与底层画面。淡黑在重叠区间中点呈整画幅黑色，两种转场声音均线性交叉淡化。

移动、修剪、变速会更新仍存活的实际重叠时长，无重叠或前镜头被删除时移除引用。转场重叠区间内部的分割、插入和覆盖拒绝；边界外编辑保留源与动画时钟，并把出场转场引用转给相应存活片段。涟漪删除只关闭扣除入/出场重叠后的独占区间。非法引用、锁轨和不合法最终状态使整批回滚。

preview-manifest 给出 mixed_track_ids 与每片段 transition.picture/sound/black 原生曲线，界面不另写转场采样规则。tests/transition_check.py 检查编辑、旧回执、透明合成真实像素、输出时长和两种频率的音量斜坡；tests/self_check.py 通过实际 MCP 调用设置与移除。

preview-manifest 有一条只读子集：`?clips=<id>`（可重复，一次最多 `capabilities.features.preview_manifest_clips_max`＝256 段）与 MCP `preview_manifest(clips=[…])` 只编译被点名的那些片段；`clips` 之外的键仍按整份工程给（`track_blend_modes`、`links`、`mixed_track_ids`、`revision`），不带 `clips` 的请求与 1.183 之前逐字节相同，桌面合成器发的就是这一条。未知段名回 404 `NOT_FOUND` 并在 `details.clip_ids` 点名，空白段名被 `Identifier` 的模式先拒（422），超过上限回 422 `INVALID_REQUEST` 带 `requested` 与 `limit`。筛发生在 `preview_manifest` 与 `transitions.envelopes` 内部，而 `outgoing` 那本索引读的是全部片段——被留下那段的淡尾住在邻段的 `transition_in` 里，不会因邻段没被点名而消失；`tests/previewsubset_check.py` 钉的就是这三条加上「子集条目逐字节等于整份里的同一条」。两万段工程上整份实测 1,274 ms / 36.54 MB，点名 8 段 17 ms / 0.01 MB。

preview-manifest 的「显式零段」另有说法（1.187）：`?no_clips=1`（MCP `preview_manifest(no_clips=True)`）编译**一段都不带**的空清单，用于播放头落在空隙里的时候——列表参数至少要有一个值，所以 `clips=` 交不回「零段」这一句。三种口径彼此互斥且分得开：不带 `clips`＝整份，`clips` 非空＝只编译被点名的那些段，`no_clips=1`＝一段都不编译；`clips` 与 `no_clips` 同时出现回 422 `INVALID_REQUEST`，句子里写着三种合法问法，`details.named` 报收到几段。开关由 `capabilities.features.preview_manifest_no_clips` 下发；HTTP 与 MCP 两个入口同一说法（`tests/self_check.py` 走真 MCP stdio 量过那三条：点名只回那一段、`no_clips` 回空清单而工程级键仍在、两者同到被 `INVALID_REQUEST` 拒）。桌面端的监视器就是这一档的第一个调用者：它按播放头那一格会被画出的段点名（画面轨未隐藏、声音轨未静音），工程级那几个键仍按整份给，所以画面算法与整份请求逐字节相同。随包引擎在 2000 段工程上实测：整份 3,714,138 字节 / 597 ms、点名一段 1,995 字节 / 99 ms、`no_clips=1` 140 字节 / 68 ms；`tests/previewsubset_check.py` 钉三种口径、二者同到的拒绝与「拒了之后整份仍可取」。

那一层现在有自己的位置与大小（1.190）：`GradeLayer` 多三个数——`offset_x`、`offset_y`（按**画面框**说，0 = 画面中心，±`capabilities.grade_limits.layer_offset_max`＝1 就是层心挪到边外）、`scale`（1 = 铺满画面框，范围 `layer_scale_min`..`layer_scale_max`＝0.05..4）。三个数都有默认值，v22 那一行的链里没有它们，读进来就是「中心 + 铺满」，与 1.189 的行为逐字节相同（工程 schema 22→23）。导出走「目标矩形 → 夹到交付帧 → 层按自己完整的尺寸缩好后再裁出相交那一片 → 裁底、相合、插值、叠回」：直接缩到交集会把出界部分的比例拉回来，那不是「被裁掉」；被裁掉的始终是**层自己出界的那部分**——既不把框挪回画面里，也不把整张挤进相交那块（`tests/layer_check.py` 用一张左半 64、右半 192 的带子图量的就是这一句：纯灰板子分不出这两种做法，而监视器那一片截图的左半均值 208、右半 64 与导出裁的是同一件事）；整层都在帧外时那一路输入与那两段 blend 一个都不开（`tests/layer_check.py` 钉的是编译串里既没有 `blend=all_mode=screen` 也没有那张图的 `-i`）。浏览器画的是同一组数：`.layer-grade` 的 `width/height = scale×100%`、`left/top = (0.5+offset)×100% − scale×50%`，出界部分由 `.preview-layer` 的 `overflow: hidden` 裁掉。开关是 `capabilities.features.grade_layer_placement`。

`clip.color.grade` 多一种节点：`{"kind":"layer","asset_id":…,"mode":…,"mix":…,"enabled":…}`（1.189）。它是这条链的第二路画面，但读的是**工程里另一张图**——与已有的 `composite`（读这条链自己进来的那幅画）唯一的差别就是这一件，所以相合的方式与权重用的是同一份词表（`BlendMode` 八种、`mix` 0..1）。三条判断都在契约与 reducer：一条链最多 `capabilities.grade_limits.max_layers`（＝3）层，超了回 422 `LAYER_LIMIT` 带 `count`/`limit`；层必须排在链尾，它后面还有会改画面的节点回 422 `LAYER_POSITION` 带 `following`（导出按顺序相合、浏览器按同一顺序画层，中间隔着节点两端就不是同一幅画）；`asset_id` 指向的素材必须存在、是图像、且带着引擎验过的媒体，否则 422 `LAYER_ASSET_UNAVAILABLE` 带 `reason`（`missing`/`kind`/`unverified`）——`clip.grade` 与 `clip.color` 两条写入路问的是同一个函数，编译那一头也兜同一句（素材后来被删不会得到一次 KeyError 或一次「静默少叠一层」）。开关由 `capabilities.features.grade_layer` 下发，工程 schema 21→22（旧工程的链里没有这一格，读进来一字不改；带层的工程会被老引擎按版本挡下）。预览与导出读同一份清单：`preview-manifest` 每个片段多一个 `layer` 数组（`asset_id`/`mode`/`mix`，按链里的顺序），监视器把它画成 `.preview-layer` 里最后那几张 `.layer-grade` 图（`mix-blend-mode` + `opacity`，且 `.preview-layer` 带 `isolation: isolate`，不然会穿到别的轨道底下去）。`normal` 那一档在编译时换操作数：FFmpeg 的 `blend=all_mode=normal` 交回**第一个**输入，而 CSS 交回**上面那一层**，把层放第一位两端才说同一句话。实测（`tests/layer_check.py`，随包 FFmpeg，八种逐条）：底片交付 128、层交付 200，读回 normal 200／multiply 100／screen 228／overlay 201／darken 128／lighten 200／difference 72／exclusion 128，逐条与按这两个端点现算的 W3C 值相差 ≤6（八个值至少六种不同，「方式被忽略」那一整类由这条兜住）；`mix=0` 回 128、`mix=0.5` 是端点与 `mix=1` 的中点、停用与没挂逐字节相同；`contain` 补边时边带像素与不挂层**逐字节相同**而画面里叠上了。

那一层现在可以自己带针（1.192）：`GradeLayer` 多一个 `keys`，每枚是 `{"property":"offset_x"|"offset_y"|"scale"|"mix","at_ticks":…,"value":…,"interpolation":"linear"|"hold"|"ease"|"bezier","bezier":…}`。刻度与 `Clip.keyframes` 同一把尺——存的是含 `animation_offset_ticks` 的时钟；而链是一次**状态写入**（`clip.color` 收进来什么就存什么），所以写的时候不挪针：隐式 rebase 会让 dry-run、粘贴属性与撤销各数出一个落点。落在这段之外的针回 422 `LAYER_KEY_RANGE`（带 `clip_id`/`property`/`at_ticks`/`animation_offset_ticks`/`duration_ticks`，`clip.grade` 与 `clip.color` 两条写入路都问 `timeline._check_layer_clock`），同一格给同一条属性钉两枚回 422 `LAYER_KEY_CLASH`，一枚一层超过 `capabilities.limits.layer_key_limit`（＝24）回 422 `LAYER_KEY_LIMIT`——三条都点名出路，不抽稀、不静默夹到边上。三个数在**同一次** `animation.frame_windows` 里换值（一次采样那组三元），所以「挪到哪」与「多大一块」永远踩同一批整帧边界；最多切几段由 `capabilities.limits.layer_schedule_segments`（＝8）下发，每一段是一路 `crop` + 两段 `blend` + 一次 `overlay:enable`，比柔焦那一段只多一个 `gblur` 贵，因此比 `blur_schedule_segments` 更小：30 帧片段上 15 枚互不相同的针实测落回 8 窗。能动的那三个数由 `capabilities.grade_limits.layer_key_props` 交回，开关是 `capabilities.features.layer_keyframes`，工程 schema 23→24（v23 的链里没有 `keys`，读进来就是空表，编译串与 1.190 逐字节相同）。`preview-manifest` 每一行多带自己那份 `windows`（`offset`/`easing`/`offset_x`/`offset_y`/`scale`），监视器把它画成 `steps(1, end)` 的动画帧——窗表是唯一权威，界面不许补中间态。实测（`tests/layerkey_check.py`，随包 FFmpeg 真导出，期望由两处自己量的端点现算）：带子图（左半交付 64、右半 192）当层、底片交付 128，`offset_x` 从 −0.5 到 +0.5 两枚 hold 针，前一窗读到 [192, 128]、后一窗读到 [128, 64]——盖住的那一片换了边，没盖到的那一侧仍逐点等于底片；而按 1.190 那条裁法，`offset_x=-0.5` 那窗露出的正是带的**右**半。同一档还钉「清单==窗表==编译串里那几次 `overlay:enable`」「一枚针（整段同值）与静态那一个数交回同一组矩形」与「`keys` 缺席读回逐字节相同」。

1.198 起这一层自己会淡：`mix` 是第四个能动的数，与位置、大小在**同一次**切段里换值（`animation.LAYER_KEY_PROPS` 是那一份名单的唯一说法，`frame_windows` 一次采样四个数，所以「挪到哪」「多大一块」「淡到几分」踩的是同一批格子）。值域 `LAYER_KEY_LIMITS["mix"] = (0.0, 1.0)` 与静态那一个 `GradeLayer.mix` 同一条带——「在检查器里拧」与「打一枚针」不会给出两套合法区间。编译串：`blend=all_mode=normal:all_opacity=<当窗那一个 mix>`，矩形仍只读前三个数（`layer_rect(*values[:3])`）；**没有针的那一层交回的就是静态那一个数**，所以旧工程的串一字不改（`tests/layer_check.py` 八档逐模式照旧）。清单 `preview-manifest` 那行的 `layer[i].windows` 每窗多一个 `mix`，浏览器 `effects.layerFrames` 把它写成那一帧的 `opacity`——`tests/desktop_layerkey_check.ts` 钉的是「`opacity` 只从窗表来、层那一支不许自带第二份名字表、检查器有第四枚打点入口」。`capabilities.grade_limits.layer_key_props` 由 `get_args(LayerProperty)` 一处算出，界面那份名单与它逐字对齐。可证的部分：真导出真解码下两枚针（1.0/0.0）编译串两次 `all_opacity` = `['1','0']`，画面上早格 31、晚格 128（底片 128、静态满的那份 31），一枚钉在静态值上的针去掉 `:enable` 后与不钉那份逐字节相同；真页面 9/9 场景绿，界面两格 computed `opacity` 1 → 0.25 而位置两格一字不动，截图整幅均值 212 → 104（差 108，这把尺要求 ≥20）。仍欠：层的针在曲线编辑器里看不见，层还不能旋转。

1.200：第二路画面那一行的实话由引擎一处说。`preview-manifest` 的 `layer[i]` 多两个字段——`paintable`（布尔）与 `reason`（`missing` / `kind` / `unverified`，能画时是 `null`），由 `animation.layer_rows(clip, project, quantum)` 一处算出：素材不在工程里、不是图像、没有引擎验过的媒体记录，三种各回各的 `reason`，问的就是导出那三条 `LAYER_ASSET_UNAVAILABLE` 同一件事。那一行**不会因为画不成就被整条撤掉**（界面要能说出是哪一层），但视图不许再去翻素材表——`Preview.tsx` 只读 `row.paintable`。同一版把源头堵住：`asset.remove` 现在也扫链尾启用中的层，删一张只有层在用的素材回 `ASSET_IN_USE`（422，`details` 带 `asset_id`、`clip_id`、`layer_holders`，中文句子点名「哪一段还在用」并给两条出路：换一张已导入的图，或把那一层从链上摘掉）；没人用的素材照旧删得掉。旧工程文件里已经悬空的那一层仍然会走到 `paintable: false`，而导出对整条链照旧拒绝——两端从此是同一句话。

1.203：那一层会转。`GradeLayer` 多一个 `rotation`（单位度，顺时针为正，`|rotation| <= capabilities.grade_limits.layer_rotation_max`（180），默认 `0.0`——0 就是 1.190 那张矩形，老工程读进来编译串一字未改，串里也不出现 `rotate=` 与 `maskedmerge`）。`capabilities.features.layer_rotation=true` 是这一档的开关。`preview-manifest` 的 `layer[i]` 因此多一个 `rotation`，界面把它交给 `layerStyle(...)` 的第 4 个参数（`transform: rotate(θdeg)`，绕元素自己的中心；`rotation=0` 时这个键根本不写）。导出与预览按**同一个外接框**裁：`render.layer_rect` 在转角不为 0 时交回 `|w·cos|+|h·sin|`、`|w·sin|+|h·cos|` 那一只（中心不动），编译那一条腿是 `scale → format=rgba → rotate=a='θ*PI/180':ow:oh:fillcolor=none → 需要时 crop → split=2 → blend=all_mode=… → maskedmerge(底, 相合结果, alpha×mix) → overlay`；`maskedmerge` 取代了原来的 `blend=all_mode=normal:all_opacity=mix`，因为 `blend` 看不见 alpha——透明角也会被 `all_opacity` 算进权重（`multiply` 那一档会量成 0）。转角在这一档只能静态（当时那份可动名单还没有它）；1.204 把它加进了名单，见下面那一段。验证：`tests/layerrotate_check.py`（逐档量中心与四角的像素、方向、一处说法、逐窗、越界两路都拒）与 `desktop_layer_check.ts`；真页面 45° 与 0° 两档的 computed 矩阵、外接框与像素复测见 `AGENTS.md`「量过的账」。

1.204：那一个转角也能打点。`LayerProperty` 长成五个数（`offset_x, offset_y, scale, mix, rotation`），`LAYER_KEY_LIMITS["rotation"]` 就是静态那一条带（`±LAYER_ROTATION_MAX`），所以「在检查器里拧」与「落一枚针」不会给出两套合法区间；`capabilities.grade_limits.layer_key_props` 由 `get_args` 自动多这一项，界面那张名字表跟着长。窗表现在每窗五个数：`animation.layer_curve` 多交一个 `rotation`，`render.apply_layers` 逐窗取 `window["value"][4]` 传给那一条腿——**0° 的那一窗不出现 `rotate`**（1.203 那条静态规矩在逐窗这一腿同样说话，实测串里 `rotate` 与 `maskedmerge` 各一次而窗数是二）。浏览器那一份 `layerFrames` 每帧都自己写 `transform: rotate(θdeg)`，包括 0°：少写一帧，那一格会回落到元素行内的静态角度，两端就不是同一格。写针的口子没有新增：仍是 `clip.grade` 那一条整链状态写入，越界由 `_check_layer_clock` 与契约字段两头按名字拒（`clip.grade` 与 `clip.color` 两路都问），一枚针钉在静态同一个角度时编译串摘掉 `enable` 与没有针逐字节相同。验证：`tests/layerrotkey_check.py`（两窗两个角度的方向差、段起点头一格的边界取样、五个数一处说法、越界两路拒、钉在静态值不改画面）与 `desktop_layer_check.ts`；真页面两档 `?tick=` 量的就是上面那句「跟着窗表而不是跟着静态」。

1.205：那一层的针进了动画曲线编辑器。新只读路由 `POST /v1/animation/layer_curve`（`clip`、`property`（`LayerProperty` 五个数之一）、`layer`（这一路的第几层，从 0 数）、`quantum`）回 `{property, layer, asset_id, duration_ticks, limits, path, curve, keys}`：`path` 由 `animation.path_from` 从同一份阶梯拼出（只有 `M/H/V`，段起头那一格就跳），`keys[].at_ticks` 已折掉 `animation_offset_ticks`——只折一次，往返不漂；`limits` 直接就是 `LAYER_KEY_LIMITS[prop]`，与静态检查器同一条带，界面不再有第二个值域。`quantum < 1` 或 `layer` 越界报 `LAYER_CURVE_TARGET`（422，正文点名层号、这一路一共几层与那个 `quantum`）；被关掉的层照样在名单里，越界判断按整条 `grade.layers` 走，不按可见的那几层。MCP 有同名工具 `animation_layer_curve`。`capabilities.grade_limits` 多一条 `layer_key_bands`（五个数各一条带，来源就是 `LAYER_KEY_LIMITS`），`capabilities.features` 多 `layer_curve`。写回仍然只有 `clip.grade` 那一条整链状态命令：1.212 起曲线编辑器**也给**层针做跨片段复制粘贴——一份复制的身份是（第几层, 哪个数），`scale`、`rotation` 这两个名字与片段自己那六个数撞名，只认名字就会把层的针写进片段自己的曲线上；那个数**照搬、不重折**，因为带子就是 `LAYER_KEY_LIMITS[prop]` 这一条、只按属性分（`grade_limits.layer_key_bands` 就是它下发的那一份），源上被引擎收下过的数换一段必然还在带内，重折反而多出第二个值域。越界、撞同一格同一属性、以及越过 `limits.layer_key_limit`（按整层数）逐枚跳过并报数；一枚都没粘上就一条命令都不发。不新增命令、不新增错误码。

1.206：那一层的针在时间线片段条上也有交代。界面新增一处 `effects.layerKeyedRows(clip)`：链里启用的层、按链里的顺序数层号、刻度夹在 `animation_offset_ticks` 到 `+ duration_ticks` 那一段内，一行交回一个 `(layer, property)` 对——片段条上那枚「+N」与它的悬停文字都只问这一处要，不再各自数一遍。这一轮不新增任何路由、命令或错误码：层的针仍住在 `clip.color.grade` 那条链里，写它们的口子仍只有 `clip.grade` 一条，牌子本身只是导航（点它是 `selectClip` + 开曲线，实测点完之后引擎那份工程的层针、片段针与静态那个 25.0 一字未动）。同轮修掉一笔 1.112 的旧账：针的 `left` 是**中心**（`.clip-keyframe` 用 `translateX(-50%)`），而那句夹法把 16px 当成整块牌子的宽度，于是针的右半边从没让开过；现在让开的距离由 `keyframeLanes.CHIP_KEEP_PIXELS = 32`（等于 CSS 给牌子的 `right: 8px` + `min-width: 24px`）与 `NEEDLE_HALF_PIXELS = 10` 两处下发，两边都钉在门禁里，代码与样式不许分家。真页面复测：牌子 **+2**、针道里 2 枚、压在牌子底下的针从 1 枚变成 0 枚、牌子中心命中它自己、点进去是这一颗片段的曲线（那一层五行都在，画布 1454×112）。

「叠一层原图」这条边现在监视器也会画（1.193）：`preview-manifest` 每个片段多一个 `composite`，形状是 `{mode, mix, paintable}`，由 `animation.composite_row` 一处算出——`mode`/`mix` 与 `grade.composite_stages` 逐字相同（导出与界面读同一份，没有第二次换算），`paintable` 要三样都成立：素材查得到、`kind == "image"`、`asset.verified` 那一次真的探测在记录里，缺一就是假。开关是 `capabilities.features.composite_preview`；一条链最多一条这一级（`COMPOSITE_LIMIT`，1.144 起），界面才敢只读一行。这一级仍带 `preview:false` 也照旧从 `preview_grade` 那份**滤镜**阶段表里整条丢掉——它不是滤镜原语，混进 `color_filter` 就等于让「已调色」那一层自己与原图相合两次，导出可没有这一份。它走的是 DOM：底层画这条链进来的那幅原图，上面套一个 `opacity=mix` 的隔离容器（`isolation: isolate`），容器内「已调色」作底、原图按 `mix-blend-mode` 相合，展开正是导出那两步的 `(1-mix)·raw + mix·mode(graded, raw)`；`normal` 那一档要交换容器里那两层，判断只在 `effects.compositeSwap` 一处（FFmpeg 的 `normal` 交回**第一个**输入、CSS 的交回**上面那一层**）。界面那一头的条件只许问两句（`edge?.paintable && url`）：前者是引擎的答案，多问「这段素材是什么」就是第二个判断；后者是引擎问不到的那件事——文件这一会儿还在不在原地。实测（构建后的监视器截图 vs 随包引擎导出的同一格，同一块 640×360 纯色板、曝光 0.5、`mix` 0.5）：八种方式逐通道最大差 normal 1／multiply 4／screen 1／overlay 1／darken 1／lighten 1／difference 2／exclusion 2，上限 8 是这把尺自己的抖（yuv420p 往返 ±6，见 `tests/composite_check.py` 的 `greys`；CSS 混合 ±2，本轮逐档量过），八档在画面上读出 7 个不同的数（`graded` 三个通道都不低于 `raw` 时逐点取大就等于 `graded`，normal 与 lighten 于是同值）。权重那一格也真的在动：multiply 的 0／0.5／1 三格读数是 (40,179,118)／(24,177,97)／(9,177,77)，0↔1 跨度 41 级，中间那格与两端线性中点逐通道差 ≤1。**视频那一段还不画，代价是量出来的**：同一条边挂到视频素材上清单答 `paintable:false`，预览读数与不挂这条边的那一段逐通道差 0（确实一个字都没画），与导出差 78 级，而导出那两段自己差 74 级——所以这是「还没画」而不是「画得差不多」。两档新门禁：`tests/compositepreview_check.py` 与第 65 档壳检 `tests/desktop_compositepreview_check.ts`，19 把突变逐条红在自己那句上。

`POST /v1/projects/{id}/edits` 多一种回执形状：`?receipt=slim`（MCP `timeline_edit` 的同名参数）只交回 `receipt`、`project_id`、`revision`、`base_revision`、`committed`、`replayed` 这六个数，不再代带整份工程；默认仍是 `full`，也就是桌面客户端要的那份权威状态。`revision` 就是写完之后的那一版，可以直接当下一笔的 `expected_revision`；`dry_run` 与幂等重放在两种形状下语义一致（`committed` 假／`replayed` 真，工程不涨）。`receipt` 取别的值回 422 `INVALID_REQUEST`，句子里写着 `full` 与 `slim` 两种合法取值，被拒那一笔不留版本。开关由 `capabilities.features.edit_receipt_slim` 下发。200 段工程上实测整份 171307 字节 → slim 142 字节；`tests/editreceipt_check.py` 钉这些，随包引擎自己复测过同样的数。



## 媒体与导出接口

这些端点在 `capabilities.features` 里以 `media_probe` / `thumbnails` / `waveform` / `preview_stream` /
`render` / `render_jobs` / `straight_cut_compositing` / `layered_overlay` 如实声明；FFmpeg 缺失时它们为 `false`，调用返回 `MEDIA_UNAVAILABLE`。

| HTTP | MCP 工具 | 语义 |
|---|---|---|
| GET /v1/media/config | media_config | 授权的素材根目录、缓存目录、ffmpeg/ffprobe 路径、允许的扩展名 |
| POST /v1/media/import | media_import | 探测并缓存一个绝对路径（必须位于授权根内），返回 probe 记录 + 签名 URL |
| GET /v1/media/probes | — | 已探测记录摘要（界面素材库用它） |
| GET /v1/media/{probe_id} | media_probe | 单条 probe 详情（含缩略图列表、波形数组、签名 URL） |
| GET /v1/media/{id}/file/{name} | — | 缓存条目（缩略图 / wave.json），需 `sig` |
| GET /v1/media/{id}/stream | — | 源文件字节流，支持 Range，需 `sig` |
| GET /v1/assets/{asset_id}/stream?project_id= | — | 工程内素材的源文件流，需 `sig` |
| GET /v1/projects/{id}/asset-urls | project_asset_urls | 一次性给出全部素材的签名播放地址 |
| GET /v1/render-presets | render_presets_read | 受控输出预设（调用方只能选，不能传编码器参数） |
| GET /v1/projects/{id}/render-plan?preset_id=&revision=&fit=&range=&transparent=&timecode=&output_fps=&colour_tag= | render_plan | 只读编译 RenderPlan 与 FFmpeg 参数预览（1.136：`transparent=true` 问的就是真导出会用的那组词，回包 `plan.transparent` 原样答；1.138：`output_fps=25` 或 `30000%2F1001` 问的是「交成另一档率」，回包 `plan.frame_rate` 是交付率、`plan.project_frame_rate` 是时间线自己的率；1.151：`colour_tag=bt709` 问的是「这张母版声明自己是哪一抹颜色」，回包 `plan.colour_tag` 原样答，`argv_preview` 里同时看得到 `zscale=matrix=709:range=tv` 与容器那三样标记） |
| POST /v1/projects/{id}/renders | render_start | 按 `expected_revision` 排队渲染（revision 不符返回 409）；同一 `request_id` 重放返回原 job，换 payload 返回 409 IDEMPOTENCY_CONFLICT |
| GET /v1/jobs/{job_id} | job_status | 状态 `queued/running/succeeded/failed/cancelled` + 进度 |
| GET /v1/projects/{id}/jobs | job_list | 该工程最近的任务 |
| POST /v1/jobs/{job_id}/cancel | job_cancel | 幂等取消，终止进程树并清理临时输出 |
| POST /v1/outputs/roots | output_root_add | 授权一个输出目录（越界路径直接拒绝） |
| GET /v1/outputs/roots | output_roots_read | 已授权输出目录 |

`asset.import` 命令携带的 `verified` 记录必须与服务端 probe 完全一致（`probe_id` 相同），客户端不能自行声明 `verified=true`。
渲染输入固定为 `(project_id, revision, preset_id)`：任务排队后时间线再变化，worker 仍从不可变历史读取原快照并完成导出。


## schema v3：人工与 Agent 共用的编辑能力

旧项目 v1/v2 可直接读取；新编辑写为 v3，历史不改写。新字段的默认值不改变 v1/v2 幂等回执指纹。

| op | 参数 | 语义 |
|---|---|---|
| track.update | track_id, locked? | 锁定轨道；片段编辑统一返回 TRACK_LOCKED，仍可解锁 |
| clip.ripple_remove | clip_id | 删除并向左移动该轨后续片段，作为一笔事务 |
| clip.effects | clip_id, effects | 替换静态 x/y/scale/rotation/opacity/gain；未列字段采用默认值 |
| keyframe.set | clip_id, keyframe | property、at_ticks、value、interpolation；at_ticks 是当前片段内相对时间 |
| keyframe.move | clip_id, from_ticks, keyframe | 原子移动已有关键帧并修改数值/插值；时间相对可见片段，目标已占用拒绝 |
| keyframe.remove | clip_id, property, at_ticks | 删除当前片段相对位置的关键帧 |
| mask.shape.set | clip_id, keyframe | 记一帧自由路径遮罩的轮廓：`at_ticks` 是片段内相对时间，`vertices` 是整条顶点表（与 `clip.mask.vertices` 同拓扑）；同一时刻再写是顶替，不是插入第二帧 |
| mask.shape.remove | clip_id, at_ticks | 删掉这一刻的轮廓；删到一枚不剩，遮罩就回到画好的那条轮廓 |
| clip.speed | clip_id, speed_percent, ripple? | 整数 25..400；默认 ripple=true，保留源范围并向下对齐结果时长；音高保持 |
| clip.color | clip_id, color | exposure(-2..2 EV)、contrast(0..2)、saturation(0..2)，默认 0/1/1 |
| clip.text | clip_id, text | 替换文字内容/字号/颜色，只能操作文字片段 |
| clip.fade | clip_id, property, duration_ticks?, mode, shape? | opacity/gain；in/out/both；1.90 起写的是片段两条边上的窗口（不再动关键帧）；两头之和不超过片段长度；1.95 起 `duration_ticks` 可以省略（只改形状），`shape` 取 `linear/ease_in/ease_out/ease_in_out`，两者都不给则 422 |
| captions.import | track_id, asset_id, srt, offset_ticks? | 原子创建新字幕轨、文字素材与片段；最多 `capabilities.limits.subtitle_cues`（契约 `SUBTITLE_CUE_LIMIT`，1.266 起这个数只在那一处），越过按 `SUBTITLE_LIMIT` 拒绝并把 `cues` 与 `limit` 一起交回，重叠拒绝并整体回滚 |

效果 x/y 以画布宽高为单位，正方向右/下；scale 默认 1；rotation 为度；opacity 为 0..1，gain 为 0..4。
关键帧插值 linear / hold / ease，ease 为平滑三次缓入缓出。第一帧之前/末帧之后保持端点值。分割及左缘修剪通过 animation_offset_ticks 保持原曲线连续；内部存储关键帧时间含此偏移，命令时间仍相对当前片段。
变速仍以整数 tick 保存时间：源消耗为 ceil(duration_ticks * speed_percent / 100)，分割源入点按整 tick 取下界；关键帧保持时间线时钟，速度改变不会自动拉伸动画。

文字素材使用 asset.register 的 kind=text、reference=generated:text；不用伪造 verified 记录。clip.add 同时带 text={body,font_size,color}。
body 最长 4000 字符，不接受 NUL；font_size 是画布高度比例 0.01..0.2；color 为 #RRGGBB；align 为 top/center/bottom，box 为半透明垫条；图片和文字入点恒为 0、速度恒为 100。
Windows 中文输出使用系统 Microsoft YaHei，正文通过 UTF-8 文件传入 drawtext，关闭表达式扩展，正文不能成为 FFmpeg 命令。

| HTTP | MCP | 用途 |
|---|---|---|
| GET /v1/projects/{id}/preview-manifest?revision=N | preview_manifest | 后端生成原生动画曲线与色彩 CSS，浏览器不重写采样规则 |
| POST /v1/animation/curve?property=P | animation_curve | Clip 请求体；只读编译数值图 path、curve、limits、相对时间 keys，可传 dry-run 候选片段，无数据库写入/媒体读取 |
| GET /v1/projects/{id}/frame?at_ticks=T&revision=N | — | 同一 FFmpeg 导出图生成的合成 PNG，长边不超过 256；按序列帧向下取整，X-Frame-Ticks / X-Project-Revision 标明实际采样快照 |
| GET /v1/projects/{id}/clips/{clip}/sample?at_ticks=T&revision=N | clip_sample | 返回当前位置六属性的权威值 |
| GET /v1/projects/{id}/captions/{track}?revision=N | captions_export | 返回 revision 与纯文本 SRT |

新错误包括 TRACK_LOCKED、INVALID_RIPPLE_TRACKS、INVALID_KEYFRAME、INVALID_SPEED、INVALID_COLOR、INVALID_TEXT、INVALID_FADE、INVALID_SUBTITLE、SUBTITLE_LIMIT，均为 422。

preview-manifest 每个片段的 sound_enabled 是权威发声开关：声音轨不受 embedded_audio=false 抑制，静音轨一律不发声；画面轨才用 embedded_audio 控制内嵌声音。滚动剪辑会拒绝已失步或轨道配对不全的链接，并检查每个链接成员轨道的锁定；源入点移动按素材速度计算，图片/文字保持源入点为 0。
SRT 时间量化到序列帧；原文字换行保留，基础 b/i/u/font 标记去除。未实现语音识别、卡拉 OK 字幕或任意字体导入。


## 1.9 动画曲线编辑

`keyframe.move` 在共享 reducer 中检查锁轨、原点与目标冲突，再原子替换一个点；目标时刻已有同属性点返回 `KEYFRAME_COLLISION`（422），原点不存在返回 `KEYFRAME_NOT_FOUND`（404），失败不改项目。保持原整数 tick 语义与裁剪偏移，不重写历史/旧回执。

`animation_curve` 提供 MCP structuredContent，path 的 x 为 0..1、y 为属性值；curve 复用预览的权威曲线，ease 保留裁剪段切线。界面只缩放 SVG、提交普通命令，不另写插值器。拖动松开只写一次，Esc/丢失指针取消；批次候选重新 dry-run 后才允许继续编辑。当前为六属性数值图，未实现速度图、自定义贝塞尔手柄或多点选择。

## 1.10 形状遮罩与候选预览

新写入/恢复使用 schema v6，兼容 v1–v5 快照，旧 clip.mask 缺省为 null；读取旧历史不重写。clip.add/insert/overwrite/clips.add 中默认 mask=null 不参与旧回执指纹。

`{"op":"clip.mask","clip_id":"c1","mask":{"shape":"ellipse","center_x":0.5,"center_y":0.5,"width":0.6,"height":0.6,"feather":0.25,"inverted":false}}`：设置或替换；mask=null 移除。shape 为 rectangle/ellipse，中心 0..1，宽高 0.01..2，feather 0..1，均为有限数。其余字段具有示例中的默认值。遮罩相对适配工程的完整画布，随片段变换，乘以已有透明度；不影响声音。羽化占半宽/半高的向内比例，矩形为两轴渐变乘积，椭圆为径向渐变。只允许画面轨；锁轨拒绝，声音轨返回 INVALID_MASK/422，整批回滚。

| HTTP | MCP 工具 | 语义 |
|---|---|---|
| POST /v1/preview-manifest | preview_candidate(project) | 验证完整候选 Project、返回只读预览计划，不写项目/历史/回执 |
| POST /v1/mask/preview | — | ShapeMask 请求体，返回只读 mask_image（原生 SVG data URL），供拖动草稿 |
| POST /v1/lut/parse | lut_parse | `LutParse{content}`（.cube 文本，≤512 KiB）请求体；引擎唯一的 LUT 解析器按文件自己的表头返回可直接放进 `clip.color.grade` 的载荷（`kind` 是 `lut` 或 `lut3d`），只读、不写项目 |

已提交 GET preview-manifest 与候选 POST 返回每片段 mask_image，null 表示无遮罩；动画/颜色/转场亦按候选编译。MCP timeline_edit 的 clip.mask 仍从同一契约生成，不暴露自定义 SVG、FFmpeg 参数或路径执行。服务端媒体仍使用已验证记录。capabilities 新增 shape_masks=true；尚未实现自由路径、遮罩动画/跟踪、多遮罩堆叠。

## 1.11 画面轨混合

Track 新增 blend_mode="normal"，track.update 可设置 normal/multiply/screen/overlay/darken/lighten/difference/exclusion。只允许画面轨使用非 normal；声音轨返回 INVALID_BLEND_MODE/422。设置混合模式检查锁轨，TRACK_LOCKED/422；解锁需先执行 track.update locked=false。完整批次仍原子、dry-run 只读、回执可重放。作用于整轨，其片段/转场先在透明画布合成，再与下方完整画面混合；遮罩/透明度控制 alpha 覆盖。声音、静音/隐藏规则保持原语义。

新写入/恢复 schema v7，兼容读取 v1–v6；track.add 默认 normal、track.update 默认 blend_mode=null 不参与旧回执指纹。已提交/候选 preview-manifest 新增 track_blend_modes（画面轨 id→原生 CSS 模式）；capabilities.track_blend_modes=true。MCP timeline_edit 自动从同一 Track/TrackUpdate 契约生成。

本轮实现常用 RGB 模式，未实现逐片段混合、HSL 色相/颜色模式或线性光/HDR 色彩管理。

## 1.12 连续属性编辑与候选采样

`clip.patch` 仅修改 effects/color/text 中给出的字段，至少提供一个非空对象。例如 `{"op":"clip.patch","clip_id":"c1","effects":{"x":0.2}}` 后接 `{"op":"clip.patch","clip_id":"c1","effects":{"y":0.3}}` 同时保留 X/Y；移除第一条后 X 保持原值。effects 的字段为 x/y/scale/rotation/opacity/gain，color 为 exposure/contrast/saturation，text 为 body/font_size/color/align/box，类型/范围复用原模型。空修改、非法键、null 字段值、越界/错误类型在契约边界拒绝。声音素材不允许 color；非文字片段不允许 text。锁轨、expected_revision、原子回滚和幂等回执使用同一 reducer/事务。

旧 clip.effects / clip.color / clip.text 继续完整替换，未提供字段仍采用默认值；不会改变既有回执或历史。项目仍为 schema v7。capabilities.clip_property_patches=true，commands 增加 clip.patch，MCP timeline_edit schema 自动包含新命令。

POST `/v1/animation/sample?at_ticks=T` 请求体为 Clip，返回 `{"values":{"x":...,"y":...,"scale":...,"rotation":...,"opacity":...,"gain":...}}`；MCP `animation_sample(clip,at_ticks)` 为只读工具。T 是片段相对整数 tick，范围 0..duration_ticks，裁剪偏移计入同一权威 sample。可直接读取 dry-run 候选，不读取媒体，不写项目/历史/回执。原 GET clips/{id}/sample 保持 revision 返回并复用相同采样函数。

检查器读取已验证且版本匹配的候选片段/轨道；预演待完成、失败或过期时暂停继续改数值。静态属性仅发所改字段，动画值由候选采样接口读取，不使用已提交旧值创建候选关键帧。

## 1.13 嵌套合成

工程 schema v9，兼容读取 v1–v8；`Project.sequences` 默认为空。Sequence 为 `{id,name,duration_ticks,tracks,clips}`，共享根工程的素材、画幅、帧率和采样率。合成素材为 `{id,kind:"sequence",sequence_id,label,reference,duration_ticks,verified:null}`，duration 必须等于合成时长；reference 仅为元数据。合成片段放在画面轨，同时包含内部声音，可修剪、分割、变速、遮罩、动画和转场。

- `sequence.nest(clip_ids,sequence_id,asset_id,clip_id,name)`：移入完整选区，原位置放一个合成片段；在最高选中画面轨上方新建正常混合/音量 1 的轨道，原空轨保留。选区必须含可见画面，不可截断组合、音画链接或转场；选中层之间存在重叠未选镜头时返回 NEST_LAYER_CONFLICT。
- `sequence.add(sequence)`：登记完整合成；可在同一批次登记其合成素材与依赖。末尾验证所有引用、时钟和循环。
- `sequence.update(sequence_id,name?,duration_ticks?)`：稀疏更新；同步所有指向它的素材标签/时长。缩短不能使内部片段或任何引用源范围越界。
- `sequence.remove(sequence_id)`：拒绝仍被引用或正在编辑的合成；成功时一并移除指向它的合成素材。

EditBatch 可指定 `sequence_id`，缺省/null 修改主时间线。例如 `{"request_id":"inner-1","expected_revision":3,"sequence_id":"intro","commands":[{"op":"clip.patch","clip_id":"title","text":{"body":"新标题"}}]}`。返回整个根工程和新 revision；内部/主时间线共享原子事务、dry-run、409、回执、历史和恢复。素材操作仍属于整个工程；删除素材检查所有范围。

GET preview-manifest、frame、clips/{id}/sample、captions/{track}、render-plan 和 POST preview-manifest 接受只读 query `sequence_id`；RenderRequest/RenderJob 接受 `sequence_id`，缺省/null 为主时间线。任务固定工程 revision 和合成 id；旧任务缺少字段时仍按主时间线执行。preview-manifest.sequences 提供各合成内部相同权威曲线计划。对应 MCP preview_manifest / preview_candidate / captions_export / clip_sample / render_plan 增加同名参数；timeline_edit 与 render_start 自动使用新版契约。

限制：最多 1,000 合成、8 层、根+内部和展开图各不超过 20,000 片段；循环返回 SEQUENCE_CYCLE，层数返回 SEQUENCE_DEPTH，内部越界返回 SEQUENCE_OUT_OF_BOUNDS，被引用合成返回 SEQUENCE_IN_USE。范围错误返回 NOT_FOUND，全部失败不写状态/历史/回执。


### 贝塞尔关键帧（schema v9）

`keyframe.set/move` 的 `keyframe.interpolation="bezier"` 可携带 `bezier:{x1,y1,x2,y2}`，控制点相对当前点到同属性下一点的时间/数值区间。省略控制点等于 `(1/3,0,2/3,1)`；时间 x1/x2 为 0..1（可交叉），数值 y1/y2 为 -4..4。允许回弹，但曲线极值必须在属性有效范围内，否则整批 422。其它插值携带非空 bezier 被拒绝；切换类型时清空控制点。末点无后续区间，参数保留以供后续加点。旧关键帧默认 bezier=null，不改变旧默认回执。

服务统一反解时间三次曲线；FFmpeg 使用原生 root，逐像素透明度只按帧计算一次。浏览器裁剪段按精确三次曲线拆分，以保证 CSS 控制点有效并保持回弹极值，SVG 共用计划。键盘/输入/一次拖动仍由 keyframe.move 写入原事务；原生连续播放精度取决于浏览器实现，导出采样已使用独立几何验证。


### 关键帧多选编辑（1.15，工程 schema v9 不变）

`keyframes.move {clip_id,moves:[{from_ticks,keyframe}]}` 原子替换 1..2000 个已有点。原时间与目标时间均相对可见片段，源属性取 keyframe.property。一次移除全部选中源点再添加全部目标，允许占用选区内旧位置及互换；源点重复返回 INVALID_SELECTION、缺失返回 KEYFRAME_NOT_FOUND、目标重复或撞到未选中点返回 KEYFRAME_COLLISION，越过片段范围返回 INVALID_KEYFRAME。控制柄和插值按传入 Keyframe 保留；最终曲线越界仍原子拒绝。

`keyframes.remove {clip_id,keyframes:[{property,at_ticks}]}` 原子删除 1..2000 个点，重复选择拒绝；不存在的点沿用单点删除的幂等语义。所有点属于同一片段，可包含不同属性。两个命令复用原锁轨、整数动画偏移、嵌套范围、dry-run、版本检查、回执和历史；一组 2000 点仍只算一条命令。旧单点命令保持可用，MCP 自动使用同一 schema。

界面在当前片段的当前属性内框选，Shift 点选或追加框选，Ctrl+A 全选可见片段内该属性全部点。拖动、方向键和时间/数值输入对选区施加共同位移，保留相对间距；整体遇到片段/属性边界会停止，碰到未选中的点不会覆盖。混合插值显示明确状态，切换一次应用到整个选区。单选保留贝塞尔控制柄，适合数值包含控制柄的纵向位置。

## 1.16 调色节点（工程 schema v10）

`clip.grade {clip_id, grade:[GradeNode…]}` 整体替换片段的串行调色链（最多 8 个节点）。`clip.patch` 的 `color` 也接受 `grade` 键，可与曝光等字段分次写入；`clip.color` 仍是完整替换，`ClipColor.grade` 默认为空数组。声音片段沿用 `INVALID_COLOR` 拒绝。

节点按 `kind` 判别，全部是每通道函数：
- `curve {channel: rgb|red|green|blue, points:[{x:0..1, y:-0.5..1.5}], enabled}`，x 必须严格递增，2..16 点；控制点之外按端值保持。
- `white_balance {temperature:-1..1, tint:-1..1, enabled}`，按 `(1+0.30T+0.10K, 1-0.20K, 1-0.30T+0.10K)` 缩放 RGB。
- `wheels {lift:[3](-0.5..0.5), gamma:[3](0.1..10), gain:[3](0..4), enabled}`，逐通道 `out=gain*in^(1/gamma)+lift`。

`grade.py` 把整条链合成一条每通道折线（65 点基准栅格并集控制点，近共线合并），再从同一折线导出两份产物：FFmpeg `lutrgb` 分段线性表达式，与 preview-manifest 中每片段 `grade:{id,r,g,b}` 的 256 项表（浏览器 `feComponentTransfer type="table"`）。空链或恒等链不产生任何滤镜，`grade` 为 `null`。执行顺序固定在曝光/对比度/饱和度之后。节点值只以数值形式进入表达式，渲染 argv 不接受调用方提供的滤镜文本。

capabilities：`project_schema_version=10`、`commands` 增加 `clip.grade`、`features.grade_nodes=true`。旧 `color` 字典中的默认 `grade` 在请求指纹里剔除，v1–v9 回执与历史无需重写即可读取和重放。preview-manifest 每个片段新增只读 `grade`，界面把它注入 `<filter id>` 定义，因此浏览器合成与导出使用同一张表；实测通道表与独立参考实现的最大偏差 0.862 LSB（`g602c30fcf45e90bc` 那次运行）。


## 1.17 自由路径遮罩

`clip.mask` 的 `ShapeMask` 新增 `shape="path"` 与 `vertices`（3..64 个 `MaskVertex`）。顶点为 `{x:0..1, y:0..1, handle_out:[dx,dy], handle_in:[dx,dy]}`，控制柄是相对顶点的偏移（-1..1）；两端都为 `[0,0]` 时该段是直线，否则按三次贝塞尔求值。矩形/椭圆不允许携带顶点，路径必须至少 3 个互不重合的顶点，否则契约层 422。`feather` 对路径按画面短边折算成高斯半径（`feather*0.25*min(W,H)` 像素），`inverted` 在模糊之后取反。

masks.py 把同一顶点表编译成两份产物：浏览器用的 SVG `<path>` 数据 URI（1000 单位等比 viewBox，`feGaussianBlur` 用同一半径），以及 FFmpeg 用的灰度 PNG（自适应细分 + 4 子行偶奇扫描线覆盖 + 可分离高斯）。渲染图里该片段先 `split`，`alphaextract` 取源 alpha，PNG 输入经 `scale2ref` 对齐帧尺寸后 `blend=all_mode=multiply`，再 `alphamerge` 合回，因此源透明度、不透明度动画、缩放/旋转与转场权重继续按原语义叠加。`POST /v1/mask/preview` 增加 `frame_width/frame_height` 查询参数以给出等比预览。

capabilities 增加 `path_masks=true`；工程 schema 仍为 v10，默认 `vertices=null` 已从请求指纹剔除，v1–v9 的旧遮罩载荷与回执原样重放。`tests/pathmask_check.py` 覆盖几何面积、贝塞尔弯曲、反相、羽化斜坡、真实成片像素、HTTP 原子性/锁轨/候选只读与旧形状兼容。


## 1.18 曲线变速与冻结帧（工程 schema v10）

`clip.speed_curve {clip_id, points}` 用 `points` 整体替换片段的速率折线；`points=null` 关闭曲线回到固定倍速。`SpeedPoint` 为 `{at_ticks: 0..duration_ticks, percent: 0..400}`，至少 2 个、至多 64 个点，`at_ticks` 严格递增、首点必须为 0、末点不得超过片段时长，违反即在契约层 422。曲线是相对百分比：`percent=100` 表示按素材原速播放，`percent=0` 表示冻结，`percent=400` 表示四倍速读取。

时间线校验按曲线积分算出片段真正读取的素材长度（`consumed_source_ticks`，对齐到帧或采样时钟），因此：图片/文字/嵌套合成携带曲线返回 `INVALID_SPEED`，与音画链接或转场同时存在返回 `INVALID_SPEED`，超出素材末尾返回 `SOURCE_OUT_OF_BOUNDS`。`clip.split` 与修剪会把曲线重新以 surviving 窗口为零点重写，两半读取窗口之和与整段一致（误差不超过一帧）。`clip.speed` 改基础倍速时按同一比例缩放时间轴并等比换算片段长度，素材窗口保持不变，百分比形状不动。

`speed.py` 把折线编译成不超过 48 段恒定速率，每段的 timeline/source 都对齐到帧（或音频采样）时钟，相邻段共用累积源位置，因此既不漏帧也不重复。切分粒度统一按**帧时钟**决定：声音段也只在画面的切换点改速率，否则 4 秒 U 形曲线会被切成 47 段 83 ms 的碎片，逐段换速的拼接缝会打出咔哒声；实测同样守恒的前提下降到 11 段、最短段 333 ms，速率序列 `[94,81,69,56,44,31,44,56,69,81,94]` 与画面对称一致。`render.py` 据此生成图：同一路解码流 `split`，每段 `trim+setpts=(PTS-STARTPTS)*ratio+fps` 后 `concat`；速率为 0 的段用 `hold` 位置（窗口里真实存在的最后一帧）取一帧再 `tpad=stop_mode=clone`，音频对应 `atrim+atempo…` 链与 `apad` 静音。输入 `-t` 取帧时钟与采样时钟两种积分里的较大值，声画共用同一个读取窗口，四倍速曲线能读满 4 倍素材。

preview-manifest 每个片段新增只读 `speed`：`describe(segments(...))` 的秒制分段（`at/duration/source_at/source_duration/rate_percent`）。浏览器 `time.ts` 的 `pacing()` 直接读这份列表切换 `playbackRate` 与 `currentTime`，冻结段落 `rate=0` 时暂停并保持在 `hold` 帧，导出与预览因此是同一份近似而不是两套。capabilities 增加 `speed_curve=true` 与 `commands` 中的 `clip.speed_curve`；默认 `speed_curve=null` 已从请求指纹剔除，v1–v9 回执与历史无需重写。

验收见 `tests/speedramp_check.py`（分段不变量、HTTP 原子性/重放/锁轨/六类拒绝、分割与基础倍速交互、真实 H.264 逐帧进度、冻结静音、四倍速输入窗口）与 `tests/desktop_speed_check.ts`（浏览器 `pacing()` 与引擎分段的一致性）。实测：4 s 片段、100%→25%→100% 曲线导出时长 4.000000 s，t=2.0 s 画面红分量 79.0（曲线读到的 1.267 s 素材理论值 80.7，线性误读会是 127.5），该处 440 Hz 单音测得 439 Hz（音高未随慢放改变）；冻结段结尾 0.2 s 窗口的平均采样幅值为 0.0（同一片段运动段为 1840.8），2.2/2.6/3.0/3.5/3.95 s 五点红分量全为 124.0（同一帧）。界面里播放头停在 00:00:02:09 时 `<video>` 的 `playbackRate=0.35`、`currentTime=1.505`，与引擎分段给出的 0.35 / 1.505 完全一致；选「冻结结尾」预设后停在 00:00:03:15 时 `currentTime=2.966666`（第 89 帧）且 `paused=true`。


## 1.19 调色节点强度（工程 schema v10）

三类调色节点（`curve` / `white_balance` / `wheels`）各自新增 `mix: 0..1`，默认 `1.0`。语义与达芬奇的 Mix 旋钮一致：节点先算出自己的结果，再按 `mix` 与**该节点的输入**逐通道线性插值，`out = in + mix * (node(in) - in)`；`mix=0` 等同于该节点不生效。

编译仍是一次成表：`grade.py` 在合成每通道折线时对每个启用且 `mix>0` 的节点施加这个插值，因此 FFmpeg `lutrgb` 表达式与浏览器 `feComponentTransfer` 表继续来自同一条多段线，没有新增第二套算法。全链 `mix=0`（或全部停用）时 `grade_tables` 返回 `null`、`grade_filter` 返回空串，滤镜图里不出现 `lutrgb`。

capabilities 增加 `features.grade_node_mix=true`；命令与端点不变（仍走 `clip.grade` / `clip.patch.color.grade`）。默认 `mix=1.0` 在请求指纹里剔除，因此 1.16–1.18 写下的不含 `mix` 的节点载荷与回执原样重放，工程 schema 仍为 v10。界面在节点下方提供「节点强度」数值输入（0–100%，步进 5），节点列表在非 100% 时标注百分比。并联/分层节点、亮度曲线、LUT 导入与色彩管理仍未实现。


## 1.20 遮罩关键帧（工程 schema v10）

矩形/椭圆遮罩的盒参数成为可动画属性：`mask_x`、`mask_y`（`0..1`）与 `mask_width`、`mask_height`（`0.01..2`），越界仍是 422 并带字段路径。写入只走既有的 `keyframe.set` / `keyframe.remove`，不新增命令；`clip.patch` 的 `effects` 仍只接受画面变换属性，遮罩的运动必须由关键帧表达。

约束写在唯一权威处 `validate_timeline`，三种情形返回 `INVALID_MASK`（带 `clip_id`，整笔回滚）：片段没有遮罩、遮罩是自由路径、遮罩被反相。反相遮罩保留的是盒子外部，盒子的运动无法由同一条 alpha 公式表达，因此明确拒绝而不是给一个会骗人的预览；路径遮罩要等跟踪实现后再谈动画。这条规则只有一份实现：契约层原先另加的 model validator 已删除，它会绕过 reducer 的错误码，把「遮罩不能反相」压成含糊的 `PROJECT_LIMIT`，而 in-place 修改本来也不会触发它。

导出侧 `geq` 的 alpha 分量按 `T`（帧时间）编译：四个属性的曲线各自展开成一对 `st/ld` 逐帧缓存寄存器，`masks.alpha_expression(mask, values)` 把盒参数替换为这些表达式；羽化仍是同一个 `clip((1-r)/feather,0,1)`，所以软边缘随盒子平移。

预览侧 `preview-manifest` 每个片段新增只读 `mask_curves`（属性 → 归一化控制点，`offset` 为片段内时间比例）与 `mask_unit`（引擎下发的单位遮罩 SVG data URI：圆心 0.5/0.5、盒 1.0/1.0），无动画遮罩时两者为 `null`。`MaskPicture` 用四个 `@property <number>` 自定义属性 `--mask-x/y/w/h`（WAAPI 逐帧求值、`fill: both`）驱动 `mask-size: calc(var(--mask-w)*var(--mask-lw)*1px)` 与 `mask-position: calc((var(--mask-x) - var(--mask-w)/2)*var(--mask-lw)*1px)`，图层像素尺寸由 ResizeObserver 写进 `--mask-lw/--mask-lh`。归一化线性映射与时间插值可交换，因此浏览器与 `geq` 是同一公式的两侧，而不是两套近似。

只读端点同样接受遮罩属性：`GET /v1/projects/{id}/clips/{c}/sample` 的 `values` 里出现 `mask_x`…`mask_height`，`POST /v1/animation/curve?property=mask_height` 返回该属性的控制点与 `limits`。capabilities 增加 `features.mask_animation=true`，命令表不变，MCP schema 由契约的 `Property` 联合类型自动生成。没有新增默认字段，工程 schema 仍为 v10，1.16–1.19 的载荷与回执原样重放。遮罩跟踪、路径遮罩动画与色彩节点图仍未实现。

## 1.21 代理回放（工程 schema v10，不改变工程状态）

代理不是剪辑命令：没有新增 `commands` 条目，不动工程状态，也不需要 `request_id` / `expected_revision`（与 `POST /v1/media/import` 同属媒体服务）。

- `GET /v1/projects/{project_id}/assets/{asset_id}/proxy?width=480|640|960|1280` 返回 `{state: absent|ready|not_needed|not_video, width, display_width, display_height, size_bytes, duration_ticks, frame_rate, has_audio, source_sha256, content_sha256, path, stream}`，`stream` 只在 `ready` 时给出（已带签名）。
- `POST /v1/projects/{project_id}/assets/{asset_id}/proxy` 载荷 `{"width": 960}` 构建代理并返回同一结构；命中缓存时直接 `ready`，不重复转码。
- `GET /v1/assets/{asset_id}/proxy/stream?project_id=&width=&sig=` 以 `Accept-Ranges: bytes` 流式返回代理，签名规则是 `proxy:{project}:{asset}:{width}`；不匹配 401，未构建 409 `PROXY_UNAVAILABLE`。
- 拒绝情形：宽度不在四档内 `INVALID_REQUEST`；素材不属于该工程 `NOT_FOUND`；文字或未验证素材 `UNVERIFIED_ASSET`；转码失败或代理时长不覆盖源 `PROXY_FAILED`。
- capabilities 增加 `features.proxy_playback`，与媒体就绪绑定（没有可用 ffmpeg 时为 `false`）。

代理只服务预览：构建不产生 revision，`render-plan`、`preview-manifest` 与导出滤镜图逐字节不变；代理按**源内容哈希**寻址，换掉素材文件后旧代理自然失效，不同工程引用同一份媒体共享同一份代理。界面「代理」下拉（关闭/640/960/1280）是工作站偏好，写在浏览器本地存储里，不属于工程，因此 Agent 无法通过它偷偷改变别人看到的画质。

## 1.22 代理缓存配额（工程 schema v10，仍不改工程状态）

在 1.21 的三个端点之外新增两个只读/维护端点，仍然不是剪辑命令：

- `GET /v1/media/proxies` → `{limit_bytes, used_bytes, proxies: [{source_sha256, width, size_bytes, used_at}]}`。`used_at` 取代理文件 atime/mtime 的较大者；不返回服务器绝对路径。声明在 `/v1/media/{probe_id}` 之前，避免字面路径被参数路由吃掉。
- `POST /v1/media/proxies/prune` 载荷 `{"max_bytes": int|null}`（`null` 用引擎默认上限，负数 422）→ `{limit_bytes, used_bytes, freed_bytes, removed: [{source_sha256, width, size_bytes}]}`。

配额默认 4 GiB，可用 `AGENTCUT_PROXY_CACHE_BYTES` 覆盖（部署者决定，不是工程属性）。执行点在构建成功之后：新代理落盘即检查总量，超限就从**最久未使用**的那份开始删，并保护刚构建的那一份。取流时 `touch_proxy` 会把该代理的 atime 推到当前时间，因此"最近看过"的副本不会被淘汰——淘汰顺序跟随实际播放，而不是构建顺序。清理只针对 `proxy-*` 派生文件：源文件、缩略图 `tile-*.jpg`、波形 `wave.json` 与 `cache.json` 从不在回收范围内；发现没有对应视频的孤儿 `proxy-*.json` 时顺手删除。清理不产生 revision，也不改变任何工程数据。

界面在预览标题行显示「代理占用 0.4 MB / 1 份」与「清理代理」按钮（无代理时两者都不出现）；清理后回到原片播放、下拉复位为「关闭」，并提示实际释放的字节数。

## 1.23 遮罩跟踪（工程 schema v10）

新命令 `clip.mask_track`：载荷 `{clip_id, points: [{at_ticks, center_x, center_y}]}`，2..2000 个点、`at_ticks` 严格递增且不超过片段时长（否则 `INVALID_KEYFRAME`）。reducer 用它整体替换该片段的两条遮罩中心关键帧（`mask_x`/`mask_y`，线性插值，按片段的动画时钟换算存储），并把静态 `center_x/center_y` 更新为第一个点——因此撤销、锁轨、批次预演、回执去重与 1.20 的遮罩关键帧规则全部沿用同一条链路。没有遮罩、路径遮罩、反相遮罩或带变速曲线的片段返回 `INVALID_MASK`（带 `clip_id`，整笔回滚）：跟踪只平移盒子，无法表达缩放/旋转，也无法跟随变速后的素材时间。

分析端点 `POST /v1/projects/{project_id}/clips/{clip_id}/track`，载荷 `{request_id, expected_revision, from_ticks?, frames=120(2..900), search_radius=10(2..16), dry_run?}`。它先做媒体分析（只读 `asset.verified` 里服务端验证过的文件，绝不接受客户端路径），再走与 `/edits` 完全相同的 `mutate` 事务，返回 `MutationResult` 外加 `tracking`：`{analysis_width, analysis_height, sampled_frames, tracked_frames, first_at_ticks, last_at_ticks, lost_at_ticks, points}`。`dry_run=true` 只分析不写入（revision 不变）；同一 `request_id` 重放不涨 revision；旧 revision 得 409；跟踪范围越过素材末尾得 `SOURCE_OUT_OF_BOUNDS`；起点不在片段内或素材不是已验证视频得 `INVALID_TRACK_TARGET`。

分析结果按帧给出，`points[i].at_ticks = from_ticks + i * frame_ticks`，值域钳在 0.001..0.999。`lost_at_ticks` 非空表示引擎在那里跟丢了目标，之后的点不会写入——界面提示「在 x.xx 秒处跟丢，遮罩停在最后找到的位置」，而不是继续猜。capabilities 增加 `features.mask_tracking`（与媒体就绪绑定）并把 `clip.mask_track` 列入 `commands`，MCP 的 schema 由契约自动生成，因此 Agent 既可以调用分析端点，也可以把自己算好的路径直接作为一条命令提交。工程 schema 仍为 v10，没有新增默认字段，1.16–1.22 的载荷与回执原样重放。

## 1.24 遮罩跟踪的缩放与遮挡续跟（工程 schema v10）

`clip.mask_track` 的每个点现在可以带 `width`/`height`（0.01..2，与 `mask_width`/`mask_height` 同一值域）。整条路径都带尺寸时，reducer 一并重写四条遮罩曲线，并把静态盒尺寸更新为首点；一条都不带时行为与 1.23 完全一致，只重写中心两条——你手工做的尺寸曲线不会被悄悄删掉。带一半不带一半由契约拒绝（`INVALID_REQUEST`，字段路径指向 `commands[0].points`），因为静默降回「只跟中心」会让人以为缩放也跟上了。

分析端点载荷新增 `estimate_scale=true` 与 `max_gap_frames=30`（0..120）；`tracking` 回包新增 `predicted_frames`、`scale_estimated`、`gaps:[{from_ticks,to_ticks}]`，`estimate_scale` 时每个点多 `width`/`height` 两个字段。被短暂遮挡的那几帧仍会给出点（按最后可信速度匀速外推），`gaps` 标出是哪一段；遮挡一直持续到素材末尾则仍按 1.23 的规则截断并报 `lost_at_ticks`。界面提示改为说明「补了几帧、是否随远近变大变小、在第几秒跟丢」。

匹配度量从平均绝对差换成归一化互相关。差的度量永远偏爱面积等于模板的窗口，因此分不清「主体变大了」与「主体走了」；归一化相关衡量形状，尺寸才成为可估计的量。做法是先用当前尺寸的模板做完整平移搜索，再在该中心附近按 `0.85/0.92/1.0/1.09/1.18` 的档位小范围试尺寸——档位相对**当前**尺寸，因此 3 秒内长大 3 倍的目标能被持续跟上。可信度下限也不再是常数：取最近 8 帧相关度中位数的 0.8 倍，并夹在 0.35 与 0.75 之间，达不到就转入匀速外推。工程 schema 仍为 v10，没有新增默认字段，1.16–1.23 的载荷与回执原样重放。旋转仍未被估计。

## 1.25 静音检测与去空白（工程 schema v10，不新增命令）

新端点 `POST /v1/projects/{project_id}/clips/{clip_id}/silence`，载荷 `{request_id, expected_revision, threshold_db=-35(-80..-6), min_silence_ms=250(80..5000), from_ticks=0, to_ticks?, apply=false, dry_run=false}`。回包的 `silence` 是 `{gaps:[{from_ticks,to_ticks,length_ticks}], edges:[…], scanned_from_ticks, scanned_to_ticks, threshold_db, min_silence_ticks, frame_ticks, removed_ticks, commands:[…]}`，`gaps` 用**片段时间**（不是素材时间）表达。

没有新增命令：`commands` 完全由既有的 `clip.split` + `clip.ripple_remove` 组成，reducer 仍是唯一决定「剪一刀对源时钟、关键帧、转场与链接意味着什么」的地方，客户端拿到命令可以改完再自己提交。`apply=false`（默认）只分析不写入，也不需要新 revision；`apply=true` 让引擎把这批命令按 `request_id` + `expected_revision` 走与 `/edits` 完全相同的事务，于是 dry-run 不写、同 `request_id` 重放不涨、旧 revision 409 这些既有语义原样继承。`apply=true` 而计划为空时返回 `INVALID_SILENCE_TARGET`，不会白涨一个 revision。

切点规则写在 `silence.py` 一处：静音区间向内取整帧（起点向上、终点向下），所以永远不会把说话切掉；取整后短于 `min_silence_ms` 的区间不切；贴着片段首尾的区间归入 `edges`，本版本不自动裁首尾——那是 `clip.trim` 的语义，不该由一条去空白命令顺带做掉。恒定 `speed_percent` 支持（检测在素材时间上做，再按时速映射回片段时间），带变速曲线的片段、无音轨素材、声音已被拆成链接片段的镜头一律 `INVALID_SILENCE_TARGET` 并说明原因。检测读的是 `asset.verified` 里服务端验证过的文件，客户端在 `verified` 上写的 `has_audio`/`kind` 不被采信（验收里就试过：改字段不会让无声音频通过，也不会让有声音频被误判）。capabilities 增加 `features.silence_detection`（与媒体就绪绑定），`commands` 表不变。MCP 新增 `clip_silence`——只读工具，`apply`/`dry_run` 在工具侧固定为 false，命令交回给 `timeline_edit` 写入——并补上 1.23 起就缺的 `clip_track`，让只走 stdio 的 Agent 也能用这两个分析端点（工具的 schema 仍由同一份契约生成，不在适配层重写规则）。界面「去空白」一次点击 = 一个 revision。工程 schema 仍为 v10。

## 1.26 整轨去空白（工程 schema v10，不新增命令）

`POST /v1/projects/{project_id}/tracks/{track_id}/silence` 接受与单片段端点相同的 `SilenceRequest` 载荷（`from_ticks`/`to_ticks` 改为逐片段生效），回包 `silence` 为 `{clips:[{clip_id, gaps, edges, removed_ticks, commands} | {clip_id, skipped}], removed_ticks, commands}`。语义差别只有一处：**不能扫的片段被跳过并说明原因，而不是让整笔失败**——一条口播轨里混着图片、B-roll 与已链接片段是常态。跳过判定与单片段端点共用 `silence.unsuitable`，同一条规则不会在两处给出不同答案。

计划仍全部由 `clip.split` + `clip.ripple_remove` 组成，按片段位置**从后往前**合并，因此每个片段使用的都是扫描时的坐标，而每次删除只移动它之后的内容。片段首尾的静音在这里一并裁掉（`trim_edges` 对整轨端点恒为裁切）：贴起点的区间用「一次分割 + 删掉左块」实现，等价于一次带 ripple 的 `clip.trim`，所以轨道开头的空洞会合上。**只有本轨移动**——其它轨道的片段保持原位，跨轨对齐仍要靠组或音画链接，界面提示里也这么写。轨道不存在 404；`apply=true` 而计划为空 `INVALID_SILENCE_TARGET`；写入走 `ProjectStore.mutate`，dry-run / 重放 / revision 语义与单片段端点一致。时间线轨道标题行新增剪刀按钮，一次点击 = 一个 revision。

## 1.27 响度表与一键统一响度（工程 schema v10，不新增命令）

新端点 `POST /v1/projects/{project_id}/clips/{clip_id}/loudness`，载荷 `{request_id, expected_revision, target_lufs=-16(-30..-6), ceiling_dbtp=-1(-9..0), apply=false, dry_run=false}`。回包 `loudness`：`{integrated_lufs, true_peak_dbtp, lra_lu, gain, predicted_lufs, predicted_peak_dbtp, limited_by, reaches_target, target_lufs, ceiling_dbtp}`。

测量交给 FFmpeg 自带的 `ebur128`（只读它的 Summary 段——逐帧运行行里也有 `I:`，开头还在绝对门以下，读错了会得到 -70 LUFS），本版本不实现任何响度标准。**写入的只有一个线性增益**：`clip.effects.gain`，所以预览与导出乘的是同一个数，也不引入压缩器——动态保持录下来的样子，这比偷偷压平更符合剪辑软件的职责。`limited_by` 如实说明为什么到不了目标：`ceiling` 表示再抬就会越过真峰值上限，`gain_range` 表示 4 倍增益已到顶，空串表示正好落在目标上；`reaches_target` 是 `|predicted - target| ≤ 0.2 LU`。静音素材（积分响度 -inf）被 `LOUDNESS_FAILED` 拒绝，而不是得到一个无穷大的增益。

判定哪些片段能分析仍用同一个 `audio_scan_problem`（与去空白共用），所以无音轨、图片/文字、带变速曲线或已链接的片段在这里得到同样的答复。`apply=true` 走 `ProjectStore.mutate`：一次一个 revision、dry-run 不写、同 `request_id` 重放不涨、旧 revision 409。capabilities 增加 `features.loudness_metering`（与媒体就绪绑定），`commands` 表不变，MCP 未新增工具（`timeline_edit` 已能提交 `clip.effects`）。工程 schema 仍为 v10。

## 1.28 整轨响度对齐（工程 schema v10，不新增命令）

`POST /v1/projects/{project_id}/tracks/{track_id}/loudness` 沿用同一份 `LoudnessRequest` 载荷，回包
`loudness = {clips:[{clip_id, integrated_lufs, true_peak_dbtp, lra_lu, gain, predicted_lufs, predicted_peak_dbtp, limited_by, reaches_target} | {clip_id, skipped}], measured, changed, off_target, target_lufs, commands}`。
每条命令仍是既有的 `clip.effects`，一次 `apply` = 一个 revision；`apply=false` 只出报告不写入。

两条规则让这个功能不会骗人：

- **已经对齐的片段不产生命令**。建议增益与该片段当前 `effects.gain` 相差 ≤ 0.01 时不写，所以重复点第二次会得到「已经对齐」而不是悄悄再写一遍；`apply=true` 而全部无需改动时返回 `INVALID_LOUDNESS_TARGET`，不产生空 revision。
- **音量已被关键帧动画的片段被跳过**（`loudness.volume_problem`）。这种片段实际响的是关键帧曲线，改静态增益听不出来，所以单片段端点直接拒绝、整轨端点列入 `skipped` 并给出原因，而不是给一个改了等于没改的数字。

`off_target` 统计被 4 倍增益上限或真峰值上限挡住、到不了目标的段数，界面提示照实播报；被跳过的段数也一并说明。时间线轨道标题行新增「响度对齐」按钮，与 1.27 的单片段按钮共用同一个目标与上限默认值。capabilities 不新增字段（`loudness_metering` 已覆盖），`commands` 表不变，MCP 无需新增工具。工程 schema 仍为 v10。

## 1.29 时间线标记与按标记分割（工程 schema v11）

`Project.markers` 是排好序的 `{id, at_ticks, name, color}` 列表（v11 新增；v10 快照读出来就是空列表，不需要迁移脚本）。
两条新命令：`marker.set` 按 id 新建或移动改名（同 id 不会堆出第二个标记），`marker.remove` 删除不存在的 id 返回 `NOT_FOUND`。
标记只能落在**当前内容之内**——上界是 `contracts.project_content_ticks`，也就是标尺末尾那帧，越界即 `INVALID_MARKER`；
这条判定和分割计划共用同一个函数，所以「能打在哪」与「哪些标记没切到」永远不会各说各话。

`POST /v1/projects/{project_id}/markers/split` 沿用 `MarkerSplitRequest`（可选 `track_ids` 过滤），回包
`markers = {markers, splits, clips, unused, content_ticks, commands}`，命令全是既有 `clip.split`：
落在片段边缘或空隙里的标记进入 `unused` 而不是切出零长片段，一个片段内的多个切点按从右往左发射，
所以前面的坐标始终指片段当前的位置。`apply=true` 一次一个 revision，计划为空时返回
`INVALID_MARKER_SPLIT`（不烧版本）；`apply=false` 只出计划，MCP 的 `marker_split` 工具就是这个只读形态。

标记绑在工程上而不是片段上：涟漪删除让内容左移时标记留在原地，这是它作为时间参照的意义（界面提示里也这么说）。
capabilities 增加 `features.timeline_markers`（不依赖媒体），`commands` 表加两条，工程 schema 从 v10 升到 v11，
`contracts.SCHEMA_VERSION` 从此是唯一来源（`projects.py`、`timeline.py`、capabilities 都读它，不再各写各的字面量）。

## 1.30 源画面划动与左右滑移（工程 schema v11，不新增状态）

两条命令补上「修剪之外」的那两种改动，人和 Agent 用的是同一套整数刻度：

- `clip.slip`：`source_offset_ticks` 可正可负，片段的位置与时长**完全不动**，只有素材窗口滑动。
  相邻片段不受任何影响，所以对口型、找同一镜头里的另一段画面不会牵动别的东西。动画时钟保持原样
  （关键帧仍贴着时间线上的这一格），这正是划动的含义。
- `clip.slide`：`delta_ticks` 把片段沿本轨移动，一侧相邻段让出 N 帧、另一侧收回 N 帧，
  **整条轨的总长一帧不变**；被吃掉的相邻段自己的素材窗口跟着挪（它开始/结束得更晚或更早），
  长大的那侧素材头尾不够时由 `validate_timeline` 的 `SOURCE_OUT_OF_BOUNDS` 拒绝。

两条都走普通 `/edits`，所以一次批次一个 revision、失败整批回滚；没有新端点、没有新 MCP 工具
（`timeline_edit` 已能提交），capabilities 的 `commands` 增加两条、`features.slip_slide_editing=true`。
拒绝面都是明说的：带变速曲线（时间非线性）、已链接内嵌声音（两侧含义不同）、滑移时缺任一侧相邻段、
相邻段短于步长、`delta_ticks == 0`。检查器里新增「源画面划动与滑移」面板，步长按帧，
上述情况按钮直接禁用并在提示里写原因。工程 schema 仍是 v11。

## 1.31 色彩空间转换节点（工程 schema v11，不新增命令）

调色节点里多一种 `transfer`：`{kind: "transfer", input_space, output_space, enabled, mix}`，两个空间都是必填的
`"linear" | "srgb" | "gamma18" | "gamma20" | "gamma22" | "gamma24" | "rec709"` 之一。它只换算**传递函数**：
先把输入按该空间的 EOTF 解到线性光，再按输出空间的 OETF 编码回去，三个通道共用同一条曲线。
`rec709` 就是黑位不抬升的 BT.1886，数值上等于 gamma 2.4，两个名字都留着是因为剪辑者两种说法都会用。
色域基色、矩阵、文件里的色彩空间标签都不在这一节范围内，capabilities 也只声明 `color_space_transform`，
不声称完整 ICC/ACES 管理。

命令仍是 `clip.grade`（整串节点替换），HTTP/MCP/界面共用同一条 reducer 路径；`mix` 与 `enabled` 的语义
与其它节点一致（`mix=0` 或 `enabled=false` 时整条链可以退化成空滤镜，引擎不添加 `lutrgb` 阶段）。

顺带修掉一个更普遍的问题：每通道表原来固定取 64 个等距打点，sRGB→gamma2.4 这类曲线在黑位处斜率趋于无穷，
固定网格让浏览器表与 FFmpeg 表达式**一致地偏离目标函数最多 4.8 个色阶**（两者互相一致，所以原来的
"预览与导出一致"门禁完全发现不了）。现在打点会按中点漂移自适应加密（上限 256 个），
浏览器表与发布函数逐格比较不超过 0.5 个色阶，编译一条链仍是毫秒级。工程 schema 仍是 v11。

## 1.32 调色节点的混合方式（工程 schema v11，不新增命令）

每个调色节点多一个字段 `blend: BlendMode`（默认 `normal`，即 1.31 之前的行为），取值与轨道合成共用同一个
`BlendMode` 枚举：`normal / multiply / screen / overlay / darken / lighten / difference / exclusion`。
语义是「把这个节点的输出与它自己的输入按该模式混合」，再按 `mix` 比例回退，公式照 W3C 可分混合模式实现：

    out = in + mix * (blend(in, node(in)) - in)

因为两个操作数都只依赖同一个通道的输入值，整条链仍然等价于每通道一张表——浏览器 `feComponentTransfer`
与导出 `lutrgb` 继续读同一份多项折线，混合方式不会引入只有导出才看得见的效果。
`blend="darken"` 配上只会提亮的曲线等价于恒等，这时引擎**不加任何滤镜阶段**（不只是表变成恒等，
表达式也折叠成 `val`），这条在验收里是单独断言。

命令仍是 `clip.grade`；capabilities 增加 `grade_node_blend_modes`；界面在节点体里多一个「混合方式」下拉，
节点行标题会显示「色调曲线 · 滤色 · 50%」。真正的并联分支（两条独立路径互相混合）仍不在这一版：
这里混合的是节点的输出与它的输入。工程 schema 仍是 v11。

## 1.33 自动闪避（工程 schema v11，新增一条批量关键帧命令）

口播压配乐是剪辑里最高频的一个动作，剪映把它做成一个开关，达芬奇用 Fairlight 的 sidechain。这一版把它做成
引擎的一个端点：人点一下，Agent 调同一个 HTTP/MCP 接口，写进时间线的都是**普通的音量关键帧**，所以预览、
导出、撤销、二次编辑全都沿用既有机制，没有第二套"闪避状态"。

```
POST /v1/projects/{id}/tracks/{music_track}/duck
{
  "request_id": "duck-1", "expected_revision": 7,
  "driver_track_ids": ["voice"],        // 省略 = 除本轨以外的全部声音轨
  "depth_db": 9.0,                       // 1–36，按幅度 10^(-depth/20) 换算
  "attack_ms": 150, "hold_ms": 120, "release_ms": 600,
  "threshold_db": -35.0, "min_silence_ms": 250,
  "apply": false, "dry_run": false
}
```

- 说话区间不是新造的检测：直接调用 `silence.analyse`（FFmpeg `silencedetect`），取它的**补集**。因此
  「去空白」会剪掉的地方，正是闪避会抬回来的地方，两个功能共用同一个阈值语义。
- 回包 `duck.speech` 是绝对时间轴刻度上的说话窗口；`duck.commands` 是**每条片段一条**
  `keyframes.replace`。客户端可以先看命令再决定（`apply=false` 完全不写），也可以改命令后用 `edits` 提交。
- `keyframes.replace{clip_id, property, keyframes[]}` 是这一版新增的唯一命令：一次写入某个属性的整条曲线，
  替换该片段上这个属性的旧关键帧，其它属性不动。存在的理由是 `edits` 的单批上限当时只有 100 条命令（1.126 起是量出来的 2500 条，见下）——用
  `keyframe.set` 铺一条 60 点的包络会占掉 60 条配额，几十个片段的轨道会直接放不下，而"一次编辑决策"必须
  仍然是**一个 revision**。校验：所有点的属性必须与命令的 `property` 一致、时间严格递增、值落在
  `PROPERTY_LIMITS` 内、列表非空，任一不满足整批 422 且不写库。
- 包络在**帧网格**上采样再做 Ramer–Douglas–Peucker 简化（容差 0.001 幅度 ≈ 0.009 dB）。理由是
  `volume` 表达式每帧只求值一次，所以断点落在整帧上时导出听到的与算出来的是同一个数；简化掉的只是
  帧与帧之间，而那里两边都是线性插值。两段说话、4 秒素材实测产出 12 个断点（不是 120 个）。
- 与 `loudness` 端点一样，`audio_scan_problem` 是唯一的拒绝口径：没有声音、带变速曲线、已链接的片段会被
  跳过并在回包里说明原因，而不是被猜一个值。
- capabilities 增加 `audio_ducking`（依赖媒体引擎）与命令 `keyframes.replace`；MCP 新增 `track_duck`
  （写型工具，`apply`/`dry_run` 语义与 HTTP 一致）。界面在声音轨标题行给一个「自动闪避」按钮，用契约默认值
  （-9 dB / 0.15 s / 0.6 s），深度等参数留在 HTTP/MCP 里调，不在轨道行铺一排旋钮。
- 已知边界：这是**包络**而不是压缩器——没有侧链反馈、没有 lookahead，说话开始前那 0.15 秒的音头会先原样
  出来一点；驱动轨是整轨一起听的，不能只对某一段口播闪避（用 `driver_track_ids` 选轨）。工程 schema 仍是 v11。


## 1.34 标记拖拽与改名（不新增命令、不改 schema）

引擎侧一行未改：`marker.set` 从 1.29 起就允许用同一个 id 移动与改名，`marker.remove` 删除。这一版补的是
桌面端的手势——标尺上的标记可以左右拖动（落点用与片段拖动同一套 `magnet`：整帧、相邻片段边缘、其它标记、
播放头），移动不足 3 像素仍按单击处理跳到该处，双击弹出改名与颜色面板（amber/cyan/green/red/violet，
与 `Marker.color` 的字面量一致）。人和 Agent 写进工程的仍是同一条命令、同一个整数刻度。


## 1.35 交付画幅与三种适配（渲染任务多一个字段，工程 schema 不变）

横时间线要发到竖屏平台，是交付时最常见的一次形变。这一版把它做成引擎参数，而不是让人在导出后再压一遍。

```
POST /v1/projects/{id}/renders
{ "request_id": "r", "expected_revision": 4, "preset_id": "h264-1080x1920-vertical",
  "filename": "竖屏.mp4", "fit": "cover" }        // contain(默认) | cover | stretch
```

- `contain`：`scale=…:force_original_aspect_ratio=decrease` + 居中 `pad`，一帧不丢，多出来补黑边。
- `cover`：`scale=…:force_original_aspect_ratio=increase` + `crop=out_w:out_h`，撑满画幅，**会丢画面**。
- `stretch`：裸 `scale=out_w:out_h`，撑满但比例变形。
- 新预设 `h264-1080x1920-vertical`（9:16）与 `h264-1080-square`（1:1）。适配与预设正交：任何带 `scale` 的预设都能配三种适配。
- `fit` 存在 `RenderJob` 上（任务文档是 JSON，旧任务读出来默认 `contain`，行为与升级前完全一致），并且进入
  `request_id` 的去重指纹——同一个 request_id 换个 fit 会被判为不同载荷并 409，不会静默复用旧回执。
- `GET /v1/projects/{id}/render-plan?fit=cover` 会按所选适配编译，Agent 可以先看滤镜串再提交。
- capabilities 增加 `output_fit_modes`。界面在导出面板给一排「完整保留 / 裁切填满 / 拉伸填满」，
  并在提示里说清当前是哪种形变关系。工程 schema 仍是 v11。


## 1.36 批量交付（新增一个端点，不改工程 schema）

同一条片子发多个平台是常态，而"逐个调 `renders`"这个客户端循环有个坑：第二条失败时第一条已经在排队了。
所以批量是引擎的责任。

```
POST /v1/projects/{id}/renders/batch
{
  "request_id": "deliver", "expected_revision": 4, "dry_run": false,
  "items": [
    { "preset_id": "h264-source-quality",   "filename": "横版.mp4", "fit": "contain" },
    { "preset_id": "h264-1080x1920-vertical", "filename": "竖版.mp4", "fit": "cover"   },
    { "preset_id": "h264-1080-square",       "filename": "方形.mp4", "fit": "contain" }
  ]
}
```

- 1–4 条，每条 `{{preset_id, filename, folder?, sequence_id?, fit}}`；文件名沿用单条导出的同一套校验
  （裸文件名；1.35 起必须 `.mp4`，1.57 起后缀必须是该预设的容器——`.mp4`/`.mov`/`.webm`），且**批内不得重名**。
- 原子性：先给每一条编译渲染计划，任何一条编译失败就整批 422，队列里什么都不会出现；全部通过才逐条入队。
- 回执：每条派生一个 `{{request_id}}-{{index}}` 的独立回执，所以重放同一批返回同样的任务集合、不会重复排队；
  改了其中一条会撞 `IDEMPOTENCY_CONFLICT`（409）。
- `dry_run: true` 只回 `{jobs, plans}` 描述，不写库、不落盘、不占输出名。
- 所有条目锁同一个 `expected_revision`，一次交付对应一个确定的时间线快照。
- capabilities 增加 `batch_delivery`；MCP 增加 `render_batch` 工具；界面在导出面板给一个「附带一个 9:16 竖屏
  （裁切填满）」勾选，勾上后主按钮一次交两份（自动命名 `xxx-9x16.mp4`），三种画幅的全组合留给 Agent。
- 工程 schema 仍是 v11。


## 1.37 母带响度目标（工程设置多一个字段，不新增命令）

1.27/1.28 管的是"每一段听起来一样响"，1.33 管的是"配乐给人声让路"，但平台要求的是**整片**的积分响度
（抖音/B 站大致 -14 ~ -9 LUFS，广播 -23/-24）。这一版补上母带这一层。

```
POST /v1/projects/{id}/master/loudness
{ "request_id": "m", "expected_revision": 7,
  "target_lufs": -14.0,      // -30 .. -6
  "ceiling_dbtp": -1.0,      // -9 .. 0
  "apply": false, "dry_run": false }
```

- **量的是真混音，不是各段数字相加**：`loudness.probe_mix` 用 `preview_size=(64,36)` 走一次极小的探测渲染
  （同一个 `compile_render_plan`、同一张 `amix` 图），再用和逐片段测量同一个 `ebur128` 读那个文件。重叠、
  淡入淡出、1.33 的闪避、轨道音量与当前母带增益全都自动算进去。实测：探测量到 -25.9 LUFS，同一条时间线
  的完整导出实测 -25.9 LUFS，相差 0.00 LU。
- 结果写进 `settings.master_gain`（0–4，默认 1.0），渲染时挂在混音之后的最后一级
  `volume=<master_gain>:eval=frame`，等于 1.0 时**完全不产生滤镜阶段**；浏览器预览把同一个数乘进每条声音
  的增益里，所以听到的和导出的是同一个母带音量。
- 上限仍然诚实：`normalize_gain` 的真峰值天花板与 0–4 倍范围会给出 `limited_by`，够不到目标时
  `reaches_target=false` 并报出实际能到的 `predicted_lufs`，不假装达标。
- 写入走一次 `project.update`，所以是一个 revision，撤销即回到上一个母带增益；已经对齐时再点报 422
  `already sits at ...`，而不是写一个空变更。
- capabilities 增加 `master_loudness`；MCP 增加 `master_loudness` 工具；界面在「工程设置」显示当前母带音量
  并给一个「整片对齐 -14 LUFS」按钮。工程 schema 仍是 v11（`SequenceSettings` 加了一个带默认值的字段，
  旧工程读出来就是 1.0）。
- 已知边界：这是**线性母带增益**，不是限制器/压限器——它不会把峰值压下来，峰值不够就少降一点目标；
  探测渲染按整片长度跑，长片要等几秒；`dry_run` 只报建议值不写库。


## 1.38 母带限制器（`master/loudness` 多一个开关，不新增命令）

1.37 的诚实之处是"够不到目标就说不"，但真原因往往是**峰值上限先挡住了增益**。广播交付的标准做法是
在母带挂一个限制器：峰值交给它，响度交给增益。

- `MasterLoudnessRequest` 多一个 `limiter: bool = false`；`SequenceSettings` 多
  `master_limiter: bool` 与 `master_ceiling_dbtp: float (-12..0，默认 -1.0)`。
- 渲染端在母带增益之后追加 `alimiter=limit=10^(ceiling/20):attack=5:release=80:level=disabled`。
  `level=disabled` 是必须的：FFmpeg 的 alimiter 默认开自动电平，会把信号又顶回上限，那样峰值表读到的
  还是上限，等于没有上限（实测：同一素材关自动电平后峰值 -1.0 dBFS，开着自动电平的那次是 0.0 dBFS）。
- **打开限制器时，峰值上限不再参与增益的钳制**（`ceiling_dbtp` 以 0 传进 `normalize_gain`），因为上限
  由限制器逐样本守住；`limited_by` 于是只反映 0–4 倍增益范围。这是这一版真正改变的行为。
- 写入后引擎**再探测一次**并把结果放进 `master.after`，所以"预测"升级成"写入后实测"；界面上的提示
  直接引用这组数。
- capabilities 增 `master_limiter`；MCP 的 `master_loudness` 自动带上 `limiter` 字段（schema 由契约生成）；
  界面在「工程设置·母带」加一个「限制器 -7 dBTP」勾选，与「整片对齐」一起提交。
- 已知边界：限制器只在**导出**里生效——浏览器预览仍只用线性增益（`DynamicsCompressorNode` 的近似与
  FFmpeg 的 alimiter 不是同一个东西，宁可少做也不在预览里演一个不一样的结果）；它是最后一道天花板，
  不是响度最大化器，素材本身峰值因子太小时（例如已削顶的声音，crest ≈1.5 dB）目标照样到不了，
  这时 `after` 会如实显示到了多少。


## 1.39 调色节点·并联分支（工程 schema v11，不新增命令）

`GradeParallel {kind: "parallel", branches: [1..4 个操作], enabled, mix, blend}` 是第五种节点：每一支
（branch）都从**本节点的输入**重新开始算，节点的输出是各支结果的平均值，然后按节点自身的 `blend`
与 `mix` 与该输入混合。支的取值集合就是其余四种节点（`curve` / `white_balance` / `wheels` /
`transfer`），各自带自己的 `mix` 与 `blend`；支不允许再嵌 `parallel`（契约层 422），所以图只有一层，
求值仍是每通道的复合函数。

为什么平均值也是每通道函数：串行是复合、并联是平均、混合方式是逐通道可分函数（W3C Compositing 1
的八种），三者都不跨通道，所以**整个节点图仍然塌缩成每条通道一张表**。`grade.py` 因此在
`node_function` 里为并联节点返回一个求各支 `step_function` 后取均值的函数，折线合成、自适应打点、
`lutrgb` 表达式与 `feComponentTransfer` 表的路径一行没改，预览与导出继续是同一个函数而不是两个近似。
停用一支按达芬奇的语义**贡献它的输入**（相当于该支直通），所以「一支有效、两支停用」等于该支的
`mix=1/3`，而不是把支数改掉——`tests/grade_check.py` 直接用「并联 [曲线, 停用] 与 曲线 mix=0.5 的
两张表相同」来钉住这条语义。

契约与能力：命令仍是 `clip.grade` / `clip.patch.color.grade`，端点、MCP 工具与回执结构都没变（schema
由契约自动生成 `branches`）；capabilities 增 `features.grade_parallel_branches=true`。工程 schema 仍为
v11，`parallel` 是新增的 `kind`，旧载荷里没有它，因此 v1–v10 的载荷与回执继续原样重放。

验收（`tests/grade_check.py` 的 parallel 三套）：
- 数学：三支（色温 +0.8 / 色调 +0.6 / 恒等）浏览器 256 项表与测试内**独立重写的平均算术**逐格比较，
  最差 **0.434 个色阶**；同样这两个操作**串行**的表与并联的表相差 **24.6 个色阶**，证明并联不是换名的
  串行；串行的顺序颠倒会改变结果 **53.2 个色阶**，而并联换支顺序逐格完全相同（<1e-9）。
- 语义：+0.3 与 −0.3 色温两支的平均在 256 档里除顶部 22 档（1.09× 开始削顶的那一段）之外逐档恒等，
  同一对节点串起来则中灰偏 **1.04 个色阶**——平均与复合在这一例上是能被量出来的两种东西。
- 滤镜：`mix=0` 的并联节点不产生任何 `lutrgb` 阶段；三支分别只动红通道时绿/蓝表逐档仍是恒等。
- 成片：三档色带（32/128/224）导出后九个通道实测与独立参考平均最大偏差 **2.01 个色阶**，并与串行
  导出的同一档位相差 **23.0 个色阶**。
- 事务与契约：一笔写图只涨一个 revision、同 `request_id` 重放不涨、旧 revision 409、`dry_run` 不写库、
  空支表 / 5 支 / 嵌套并联全部 422 且不烧版本、`restore` 回到写图前一支支数与强度一起还原。
- 变异验收：把 `average` 从「取均值」改成「取最后一支」，数学门禁当场报 **55.44 个色阶**。

界面在同一条 HTTP 服务上实测（vite 渲染层 + 引擎，工程「并联节点界面验收」，真实导入的 640×360 4 秒
素材）：选片段 → 点「+并联」→ r1→r2，节点行显示「1. 并联 · 2 支」→ 点「+支」→ r3，出现三个支标签
→ 支 1 色温输入 80 → r4 → 支 2 色调输入 60 → r5 → 支 1 强度输入 50 → r6，每笔一个 revision。
每一笔之后读 DOM 里 `<filter id="g…">` 的三条 `feFunc* tableValues`（256 项）与页面内**独立重算**的
三支平均比较：三档支参数下最大偏差 **1.2e-7**（即逐位相同），换强度后滤镜 id 从 `g03025c48aabec4d9`
变成 `g9fb569a043120063` 且再次逐位吻合。随后用同一个工程提交 `h264-720p-web` 导出（任务
`succeeded`，产物 `ui-parallel.mp4`），把成片与源文件在同一时刻逐像素对比：只取两侧都平坦的区域，
**16,955 个像素**按通道检查「成片值是否等于浏览器表在源值处的输出」，最差 **5 个色阶**（出现在输入
255 的削顶处，那里表本身就是 1.056→1.0 的钳位）。同一次验证还顺带证明了一条既有守卫：把 `folder`
指到未授权的输出根之外，服务端返回 `OUTPUT_NOT_ALLOWED` 而不是写出文件。

仍未完成：图层节点（第二路输入取自图中另一个节点，需要节点连线视图与跨节点求值）、亮度曲线与
LUT 导入、色域矩阵与色彩管理（这三者都需要跨通道的 3D 查找表，而浏览器侧目前只有每通道的
`feComponentTransfer`，两端不同源就不能声称预览等于导出）、路径遮罩顶点动画、自动语音字幕、
缩略图与波形磁盘配额、代码签名。


## 1.40 时间线入出点与区间导出（工程 schema v11，不新增命令）

剪映和达芬奇都能「只出这一段」：标尺上打一入一出两个点，导出面板选区间。这一版把它做成**工程设置里的一对整数刻度**加一个渲染参数，不新增任何编辑命令。

- `SequenceSettings.in_ticks / out_ticks`（`int | None`，默认都是 `null`）：要么都给、要么都不给；必须落在整帧上（`% frame_ticks == 0`）；`in < out`。越过当前内容的出点由 `validate_timeline` 一处判定，返回 `INVALID_MARKS`（422，带 `in_ticks`/`out_ticks`），整笔不写、revision 不动——与 1.29 的标记同一口径：能打在哪、能导到哪，读同一个 `project_content_ticks`。
- 写入走既有的 `POST /v1/projects/{id}`（`settings` 整体替换，与 1.37 的母带增益同一条路），所以一次设点 = 一个 revision，撤销、历史、去重回执全部继承；MCP 的 `project_get` 读得到，也不需要新工具。
- `RenderRequest.range: "full" | "marks"`（默认 `full`）与 `RenderBatchItem.range` 同名；`GET /render-plan?range=marks` 只读预演。`jobs.plan_for()` 是唯一把 `range` 翻成刻度的地方（`marked_range(project)`），渲染计划、排队任务与 worker 三处共用，所以「面板上看到的区间」与「落盘的区间」不可能不同源。没有入出点却请求 `range=marks` 直接 422 `INVALID_MARKS`，不会静默出一版整片。
- 裁剪位置是刻意的：`compile_render_plan` 在 `[vout]`/`[aout]` **之后**追加 `trim=start_frame=N:end_frame=M,setpts=PTS-STARTPTS` 与 `atrim=start=S:end=E,asetpts=PTS-STARTPTS`；画面已经过 `fps=` 归一化所以帧号精确，声音用秒。也就是说区间成片走的是整片同一张合成图、同一次 `amix`、同一个母带增益与限制器，不是重算一遍的近似。`plan.duration_ticks` 改成区间长度，输出 `-t` 跟着变，`plan.range` 回显 `{in_ticks,out_ticks,seconds}`。
- 回执兼容：`range` 只在**不等于 `full`** 时进入去重指纹，因此 1.39 及更早写下的渲染回执继续原样重放（实测同一 `request_id` 重放 `replayed=true` 且 job id 不变）；把 `range` 改成 `marks` 得到 409 `IDEMPOTENCY_CONFLICT`，不会静默复用旧文件。
- 工程 schema 仍为 v11：两个新字段带默认值，旧工程读出来就是 `null`，无需迁移。capabilities 增 `timeline_marks` 与 `range_export`。

验收（`tests/marks_check.py`，素材由 FFmpeg 生成红/绿/蓝三段各 2 秒、440/880/1320 Hz 各一段）：

- 契约：半写区间、非整帧、`in == out`、`in > out` 全部 `ValidationError`；不设点时 `in_ticks is None`。
- 计划：`range_ticks` 越出时间线（超总长、零长、负起点）都被拒；`start_frame=30:end_frame=150` 精确对应 1–5 秒。
- HTTP：出点越过内容 → 422 `INVALID_MARKS` 且 revision 不动；设点一次一个 revision；`render-plan?range=marks` 的 argv 含 `trim=start_frame=60:end_frame=120` 与 `atrim=start=2.000000:end=4.000000`，整片计划里两者都没有；`plan.duration_seconds` 分别是 2.0 与 6.0；清除区间一个 revision；无点时 `range=marks` 得 422 且不排队任务；`restore` 回到设点那一版时区间一起回来（新 revision）。
- 成片：整片 6.000 秒、区间 2.000 秒（ffprobe），区间文件更小；区间首帧是绿段（G>90、R<40）而整片首帧仍是红；区间第 0.2 秒音高 **879 Hz**、整片同点 **439 Hz**（过零率测得）；区间第 0.5 秒与整片第 2.5 秒逐通道最大差 **0 阶**——区间成片就是那一段，不是重新编译的另一版。
- 批量：一次两条（整片 + 区间）实测落盘 6.000 秒与 2.000 秒两个文件。
- 界面（vite 渲染层 + 同一引擎 HTTP，1280×800 同源 iframe 真实按键/指针事件）：`Home` + 60 次 `→` 后按 `I` → r1→r2（库里 `in_ticks` 恰为第 60 帧）；再 60 次 `→` 按 `O` → r3（`out_ticks` 第 120 帧）；标尺出现 `.ruler-range`（`left:124px; width:124px`，62 px/秒）与两个手柄；按住「入点」手柄左拖约 1 秒松手 → r4，`left` 变 57.8667px（第 28 帧，整帧量化）而出点不动；导出面板「入出点区间」chip 由禁用变可用，选中后点「查看渲染计划」，提示条原样读出服务端回包「按「完整保留」由服务端编译，**区间 0.93–4.00 秒**」；点「开始导出」→ 任务 `range=marks`、`total_ticks=216384000`，产物 ffprobe **3.067 秒** 1920×1080 H.264 + AAC；`Alt+X` → r5，区间带消失、chip 回到禁用。1040×660 下 `scrollWidth == clientWidth == 1040`（无横向溢出），五个 chip（三种画幅 + 两种范围）宽度 70/82 全部可见。
- 门禁同步：`ruff check`、`ruff format --check`（66 文件）、`npm run typecheck`、39 项 Python 检查与 5 项 esbuild 桌面检查。本轮无新命令、无新 MCP 工具、无新依赖、无 schema 变更。

仍未完成：四点剪辑（源入出点 + 时间线入出点一次算成插入/覆盖命令，含按区间长度写变速曲线或裁尾）、图层节点与连线视图、亮度曲线与 LUT、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、自动语音字幕、缩略图与波形磁盘配额、代码签名。


## 1.41 四点剪辑（`POST /v1/projects/{id}/four-point`，不新增时间线状态）

达芬奇与 Premiere 的四点剪辑是同一句话：「把素材的这一格到那一格，放进时间线的这一格到那一格」。人用 `I`/`O` 在素材监视器和标尺上各点两下（1.40 已经给了时间线那一对），Agent 直接给四个整数。

- 请求 `FourPointRequest {request_id, expected_revision, asset_id, track_id, source_in_ticks, source_out_ticks, dest_in_ticks, dest_out_ticks, fit: "trim"|"speed" = "trim", mode: "insert"|"overwrite" = "insert", ripple_track_ids?, apply, dry_run}`。`fourpoint.plan()` 只判定该裁还是该改速，然后产出**一条**普通 `clip.insert` / `clip.overwrite`；放置是否合法（素材窗口、锁轨、重叠、时钟）仍然只由 reducer 判，适配层没有第二条规则。
- 三种解算：源长 = 目标长 → `resolution: "exact"`；源长 > 目标长 → 裁尾（`"trimmed"`，`consumed_source_ticks` 等于目标长），此时请求 `fit=speed` 会被拒（改速只能把短素材拉长，不能凭空变短）；源长 < 目标长 → `speed_percent = round(100*源/目标)`（`"re-timed"`），若该百分比落在 25–400% 之外、或取整后实际读到的素材与请求相差超过一帧，一律拒绝并说明差多少，不做「悄悄少读一点」的近似。
- 四个点都必须落在整帧上（`% frame_ticks == 0`），否则 `INVALID_FOUR_POINT` 并带上要求的模数；素材必须是引擎自己验证过的记录（否则 `UNVERIFIED_ASSET`）；轨别必须与素材 kind 匹配；源出点越过素材末尾是 `SOURCE_OUT_OF_BOUNDS`。
- **幂等**：生成的 clip id 是 `sha1(request_id)[:12]`，不是随机数——重试必须重建出逐字节相同的批命令，否则它会跟自己的回执相冲。这一条是本轮被验收当场抓出来的：第一版用 `uuid4()`，同一 `request_id` 重放直接 409。
- MCP 新增只读工具 `clip_four_point`（工具侧强制 `apply=false`、`dry_run=false`），Agent 看过 `commands` 与 `four_point` 里的实测数字后再用 `timeline_edit` 一次写入；capabilities 增 `four_point_editing`；工程 schema 仍 v11，不新增任何时间线字段。

验收（`tests/fourpoint_check.py`，素材为红/绿/蓝各 2 秒 + 440/880/1320 Hz 各一段）：

- 解算：exact / trimmed / re-timed 各产一条命令，字段逐一断言（`duration_ticks`、`source_in_ticks`、`speed_percent`、`consumed_source_ticks`）；12 组不可能的点位组合各自返回预期的错误码；未验证素材在另一份工程里测 `UNVERIFIED_ASSET`；`mode=overwrite` 不携带 `ripple_track_ids`。
- 契约：负点位、非整数、`fit="stretch"`、`mode="paste"` 全部 `ValidationError`。
- 事务：`apply=false` 与 `apply=true, dry_run=true` 都不写库；一次 apply 恰好一个 revision；同 `request_id` 重放 `replayed=true` 且版本不动；旧 revision 409；`restore` 回到放置前是新 revision 且时间线清空。
- 成片：源 1–3 秒以 50% 铺进 0–4 秒 → 导出 4.000 秒，第 0.5 秒红（素材 1.25 秒）、第 3.5 秒绿（素材 2.75 秒），音高 439 Hz → 825 Hz（时间被拉长而音高保持，沿用 atempo 的既有语义）；源 2–6 秒裁尾进 4–6 秒 → 覆盖段最后一帧仍是绿，被裁掉的蓝色尾段从未出现在画面里。
- 门禁同步：`ruff check`、`ruff format --check`（68 文件）、40 项 Python 检查（含新增 `tests/fourpoint_check.py`）与 5 项 esbuild 桌面检查；`tests/self_check.py` 的 MCP 工具集合断言加上 `clip_four_point`（这条断言存在的意义就是新工具不会悄悄漏出文档）。

仍未完成：图层节点与连线视图、亮度曲线与 LUT、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、自动语音字幕、缩略图与波形磁盘配额、代码签名。

## 1.42 交付方案持久化（工程 schema v12，新增两条命令）

出货的一组设置——预设、画幅适配、导出范围、文件名——过去只活在导出面板的临时 state 里：每次交付都要重选，
Agent 也没法说「按上次那份竖屏方案出」。现在它是工程状态。

- `Project.recipes` 是 `{id, name, items[1..4]}` 列表（v12 新增；v11 及更早的快照里没有这个键，读出来就是空列表，
  不需要迁移脚本）。`items` 复用**同一个** `RenderBatchItem`，不是第二个「方案条目」类型——方案里存的就是批量
  交付的输入。上限与一批最多 4 条对齐，避免存下一份永远发不出去的列表。
- 命令 `recipe.set`（按 id 建或原地换）与 `recipe.remove`。方案只存选择：`extra="forbid"` 的契约让任何多余的
  编码器字段（比如 `crf`）在解析阶段就被拒绝，渲染时仍然按预设表重新校验。
- reducer 里拒绝未知预设：422 `INVALID_RECIPE`，消息点名是哪个预设、哪条交付，**不烧 revision**。为什么放在写入时：
  一份永远不会出货的方案是个陷阱，等用户点出货才发现就晚了；而出货时的校验（`plan_for`）一个字都没改，
  「预设是否存在」这一条规则仍只有 `render_presets()` 一处来源。
- `range: "marks"` 的方案条目在没有入出点时仍然整批拒绝（沿用 1.40 的 `INVALID_MARKS`），有入出点时出区间——
  方案不改变出货语义，只是把那组选择记住。
- capabilities：`features.delivery_recipes`（依赖媒体，因为没有 FFmpeg 就没有货可出）、`commands` 增两条。
  同时 capabilities 文档新增 `app_version`（就是 `contracts.APP_VERSION`，与 `/v1/info`、OpenAPI 文档同一个来源）：
  Agent 读这一份文档就能知道**是哪个构建在回答**，配合 `project_schema_version` 一起看即可。桌面标题栏的「引擎在线」
  徽章现在显示 `引擎在线 v1.42.0`，悬停说明里补上「版本 · 工程 schema vN」——过去只有 revision，用户与验收都无法
  从界面上分辨跑的是哪个构建。`tests/self_check.py` 断言 `capabilities["app_version"] == APP_VERSION`（字段缺失
  直接 KeyError，不会静默通过）。
  MCP 不新增工具——这两条命令走既有的 `timeline_edit`，schema 由契约生成，因此新 op 自动出现在工具入参里。
- 界面：导出面板「交付方案」一行——芯片上主按钮按方案一次排队多条交付（仍锁定当前 revision），「覆盖」把面板
  当前的设置写回该方案，「删」只删方案不动时间线且可撤销。芯片上的 `title` 逐条写出 `文件名 · 适配/范围`，
  所以点之前就知道会出几路货。

验收（`tests/recipe_check.py`）：

- 契约：空列表、5 条、重名文件、带路径的文件名、非 `.mp4`、超 64 字的名字、多余的 `crf` 字段全部 `ValidationError`；
  `EditBatch` 能把 `recipe.set` / `recipe.remove` 解析成对应命令类（这就是 HTTP 与 MCP 走的那条解析路径）。
- 事务：一次写一个 revision、同 `request_id` 重放不涨也不复制方案、`dry_run` 返回**候选**工程（revision+1）而库里
  一个字都不变、旧 revision 409、`recipe.remove` 不存在的 id 404、未知预设 422 且不烧版本、`restore` 把方案列表
  还原成当时的样子且是新 revision、同一个 sqlite 文件用新的 `ProjectStore` 重新打开能读回方案（证明是持久状态，
  不是内存装饰）、删掉最后一个方案留下空列表而不是缺键。
- 出货（关键一条）：把库里存下的 `items` 原样发给 `/renders/batch`，两条交付真的各自出片——实测
  1920×1080 与 1080×1920 各 4.000 秒；带 `range=marks` 的方案在没有入出点时整批 422 且**不排队任务**
  （用队列长度前后相等来断言，而不是断言「列表为空」——那时前面成功的任务本来就在列表里），有入出点时出 2.000 秒区间。
- 界面（`127.0.0.1:5178` 对 `127.0.0.1:8791` 的真实引擎点击）：存方案 r1→r2 并出现芯片「横竖双交付 1 条」；
  勾选「附带 9:16」后点「覆盖」，芯片变「2 条」、库里那条方案真的变成 2 项（r3→r4）；点方案名一次排队两条、
  两条都锁 r4，成片实测 1920×1080（2,587,407 字节）与 1080×1920（950,159 字节）各 4.000 秒。
  这一轮我自己的驱动脚本先误判过一次：用 `dispatchEvent(new Event("change"))` 勾复选框，React 的 checkbox
  是在 `click` 上归一化的，于是「覆盖」只写进 1 项——是脚本的问题，不是产品的；换成真实 `click()` 后
  引擎侧读回 2 项，芯片同步显示「2 条」。
- 门禁同步：`ruff check`、`ruff format --check`、`tests/suite_check.py` 全绿；工程 schema 从 v11 升到 v12 时，
  `grade / link / marker / transition` 四处硬写的 `== 11` 断言当场变红——这正是它们存在的意义，逐条改到 12 而不是放宽。

## 1.43 安全区参考线（工程 schema 仍 v12，不新增命令）

达芬奇与剪映都会在监视图上画动作区/字幕区，用来判断「竖屏出货时字幕会不会被平台 UI 盖住」。AgentCut 过去有一个
本地 `useState` 的「安全框」开关：刷新就丢、数字写死在 CSS 里、Agent 完全看不见。本版把它变成工程状态：

- `SequenceSettings.safe_area: "off" | "action" | "title" = "off"`。写入仍走 `POST /v1/projects/{id}` 的
  `settings`（与母带音量、入出点同一条路径），因此天然带上 `expected_revision`、幂等回执、历史与撤销，
  **不新增命令、不新增端点、不新增 MCP 工具**。
- 内缩数字只有一处来源：`contracts.SAFE_AREA_INSETS = {action: 0.035, title: 0.05}`（ITU-R BT.601/709 的
  3.5% / 5%），通过 `capabilities.safe_area_insets` 发给界面。CSS 里那两个写死的百分比被删掉了。
- 路径遮罩的顶点上限 `MASK_VERTEX_LIMIT`（当前 64）同样只由契约持有，通过 `capabilities.mask_vertex_limit` 发给界面：画面的「双击加点」在到达上限时不再加点，而界面自己不再保存这个数字（1.55 前 `MaskPicture` 里另写了一个 64，两边可以各自漂移）。契约侧的边界由 `PathVertices` 的 `max_length` 把住：64 个顶点的轮廓收，65 个退 `ValidationError`。
- capabilities 增 `features.safe_area_guides`（不依赖媒体：它只是监视器上的参考线）。
- 语义边界：**它只影响界面**。同一时刻的两种状态各导一次文件，逐通道取样完全相同——这条是断言出来的，
  不是声明出来的（`tests/safearea_check.py`）。

验收：契约层四组非法值各自 `ValidationError`、缺键读作 `off`；事务层一次写一个 revision、重放不涨、坏名字 422
且不烧版本、旧 revision 409、重新打开同一个库读回该值、`restore` 还原参考线；成片层 `title` 与 `off` 两次导出
在 0.2/1.0/1.8 秒的像素完全相同且都是 2.000 秒；界面层三态循环 r1→r2→r3、角标显示 67×38 px 与 96×54 px、
选中那条实线高亮。工程 schema 仍是 v12（新增的是一个带默认值的显示字段，旧工程读出来就是 `off`）。

仍未完成：图层节点与连线视图、亮度曲线与 LUT、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、
自动语音字幕、cover 主体跟随重构图、4K 长工程性能、代码签名。

## 1.44 派生缓存总配额（不新增工程状态）

缩略图与波形是**每个内容哈希一份**、写进缓存目录就再也不管的东西：过去的配额只管代理（`AGENTCUT_PROXY_CACHE_BYTES`），
所以一个长期使用的剪辑台会被 filmstrip 瓦片和波形峰值慢慢填满磁盘，而那些数据全部可以重建。

- `GET /v1/media/cache` → `{limit_bytes, used_bytes, entries:[{digest, size_bytes, files, used_at, has_proxy}]}`。
  一份账算的是**整个缓存目录**（瓦片 + 波形 + 清单 + 代理），数字来自磁盘实测。
- `POST /v1/media/cache/prune` → `{max_bytes?, keep?, dry_run?}`。默认预算是 `cache_limit_bytes()`
  （`AGENTCUT_CACHE_BYTES`，缺省 6 GiB）。淘汰单位是**一个内容哈希的整个目录**，因为那是可重建的单位：
  只删瓦片会留下 `cache.json` 声称文件还在（清单说谎），半删的目录比不删更糟。顺序是最久未用先走，
  `keep` 里的哈希不参与，**已登记素材根目录里的任何东西永不参与**（缓存目录被配到素材根里时也不会误删原片）。
- `dry_run` 返回同一份计划但不删任何东西——破坏性的磁盘操作必须能预演，这与工程侧的 dry-run 一脉相承。
- 被删的条目在下次被请求时自动重建：`cache_path` 发现清单里的文件不在，就重新跑一遍 `build_cache`。
  这条是「派生副本可重建」这句话的实现与验收点。
- **预算在生成时自动执行**：`_build_cache` 写完清单后立刻按当前预算收敛（保护刚生成的那一项），
  不需要谁记得去调 prune。一条限制要说清：单个内容哈希的派生文件本身可能大于预算，此时缓存停在
  「只剩刚生成这一项」的状态——引擎不会为了凑数字把刚做的东西删掉，也不会拒绝生成。
- capabilities 增 `features.cache_pruning`（依赖媒体）。不新增工程状态、不改 schema（仍 v12）、不新增 MCP 工具。

验收（`tests/cache_check.py`）见 README 对应行的数字。界面：监视器工具条在原有「代理占用 / 清理代理」旁加
「缓存 X MB / N 项」与「清理缓存」（后者等价于 `max_bytes: 0`，提示里写明原片与工程不动、下次用到自动重建）。

仍未完成：图层节点与连线视图、亮度曲线、LUT 导入、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、
自动语音字幕、cover 主体跟随重构图、4K 长工程性能、代码签名。

## 1.45 主体跟随重构图（不新增工程状态，新增一个只读 MCP 工具）

剪映的「智能重构图」与达芬奇的 reframe 是同一个动作：跟着主体把画面居中，好让 16:9 的原始时间线
裁成 9:16 时主体还在。AgentCut 已经有「跟踪主体」（遮罩路径），也有 `x`/`y`/`scale` 关键帧，缺的只是
把前者换算成后者的那一步——人得手工对齐几十个时间点。

- `POST /v1/projects/{id}/clips/{clip_id}/reframe`，请求 `{request_id, expected_revision, max_scale=2.0, apply, dry_run}`。
  读片段上已跟踪的 `mask_x` / `mask_y` 曲线，写回 `x` / `y` / `scale` 三条 `keyframes.replace`——**三条命令一个批次，
  一个 revision**，落库仍只由 reducer 判合法性。
- 数学按合成器的真实规律反解：层以画面中心为锚缩放后再叠在 `(W-w)/2 + W·x`，所以主体落点是
  `0.5 + scale·(cx-0.5) + x`。要居中就得 `x = scale·(0.5-cx)`；放大后的层仍能盖满画面的条件是
  `|x| ≤ (scale-1)/2`，合起来 `scale ≥ 1/(1-2|0.5-cx|)`。这条规律不是推出来的，是**用真实导出量出来的**：
  第一版按 `x = 0.5-cx` 写，成片里主体反而跑得更偏（0.06 / 0.13 / 0.94），才把 `scale ×` 这一项补上。
- `max_scale`（1–4）是**放大天花板**：压太低时某些点跟不到，引擎不假装跟上了——回包 `clamped_points` 计数、
  `warning` 说明「跟到这里就停了」，界面把这句话原样显示。
- 拒绝都有名字：没有遮罩、路径遮罩、反相遮罩、没有中心曲线、两轴关键帧不同步、两轴插值不一致、
  上限越界、片段不存在、音频片段、带变速曲线（路径是按素材时间量的）。
- MCP 新增**只读**工具 `clip_reframe`（强制 `apply=false`），Agent 先看数字再用 `timeline_edit` 落一次写入。
  `tests/self_check.py` 的精确工具集合断言因此当场变红——这正是它存在的意义。
- capabilities 增 `features.subject_reframe`；不新增工程状态、不改 schema（仍 v12）。

验收（`tests/reframe_check.py`）：解算层逐字段断言（0.15→0.85 的横扫 → x=±1.1667、scale=3.333、
`clamped_points=0`；上限 1.5 倍 → 2/3 个点被夹住并给出警告）；事务层 plan/dry-run 不写库、一次 apply 一个
revision、重放不涨、旧 revision 409、`restore` 后不留平移/缩放曲线；成片层用一段**真的在动**的素材
（白块在灰底上从左滑到右）量主体质心：不跟随 0.18 / 0.50 / 0.82，跟随后 0.56 / 0.50 / 0.40
（平均偏离中心 < 0.06；tracked 点上精确，中间是遮罩路径自身的线性近似——这一点如实写进提示与文档），
左上角 16×16 均值 63/63 与灰底相同（放大真的把画面盖满、没有黑边），时长 2.000 秒。

仍未完成：图层节点与连线视图、亮度曲线、LUT 导入、色域矩阵与色彩管理、路径遮罩顶点动画、多目标与长时遮挡跟踪、
自动语音字幕、cover 主体跟随的**多画幅同时**输出、4K 长工程性能、代码签名。

## 1.46 调色节点图（不新增状态，纯界面）

调色链早就是「一串节点 + 并联支」，但界面是一个纵向列表加 ↑/↓：看不出信号往哪儿流，也看不出并联的
支路是从哪儿分出去、又在哪儿合回来。本版把它画成图。

- `desktop/src/gradeGraph.ts` 是唯一的描述与顺序算术：`cardsFor(nodes)` 把节点变成卡片（标签、
  `强度 50% · 滤色`、并联的 `3 支` 与每条支路的停用态），`dropIndex` 把拖放落点夹进 `[0, count-1]`，
  `moveWithin` 是纯的 remove+insert（不改原数组、长度不变、原地放等于没动）。组件只渲染它，不自己算。
- 拖卡片改顺序 → 一条 `clip.color` → 一个 revision；↑/↓、启用开关、删除都还在卡片上，走同一条写路径。
- **没有任何新的工程状态**：链子还是 `clip.color.grade` 那个列表，schema 仍 v12，不新增命令、端点或工具。
  所以 Agent 写的顺序与人拖出来的顺序是同一件事，`tests/grade_check.py` 的权威断言一字未改就继续成立。

验收：`tests/desktop_graph_check.ts`（esbuild + Node assert）钉住卡片描述、落点夹取与纯移动；浏览器
`DragEvent` + `DataTransfer` 真实拖放 r1→r2，卡片顺序变成 并联 → 色彩空间 → 白平衡，库里读回同样顺序且
每个节点内容一字未丢（3 支、第 2 支停用、白平衡 50% 滤色、srgb→rec709）。

仍未完成：亮度曲线、LUT 导入、色域矩阵与色彩管理（这三项要跨通道，塌不进现有的每通道一张表）、
路径遮罩顶点动画、多目标与长时遮挡跟踪、自动语音字幕、多画幅同时跟随、4K 长工程性能、代码签名。

## 1.47 主体跟随重构图跟的是采样后的路径（修复 1.45 的两处交付缺陷）

1.45 的解算器把遮罩关键帧一一对齐后直接写成平移/缩放关键帧，两处都不成立，而且是成片实测出来的：

- **两套时钟**。工程里存的遮罩关键帧在片段的绝对动画时钟上（`animation_offset_ticks + 片段内 tick`），
  而 `keyframes.replace` 收的是**片段内** tick、由 reducer 再加回偏移。解算器读绝对、写绝对，
  reducer 又加一次：任何带偏移的片段，跟随曲线整体晚一个偏移落地。`clip.split` 恰恰就是产生偏移的
  操作——把已跟踪的片段剪一刀再自动重构图（竖屏出货最常见的手势）原本必然错位。
- **关键帧太稀**。把主体居中需要的放大倍数是 `1/(1-2·|0.5−中心|)`，是双曲的，不是线性的。两段之间
  用直线连接，中间就会过冲：实测一段只有两个关键帧的尾巴，在第 1.5 秒把主体甩到画面宽度 0.278 处
  （偏离中心 0.22 个画面宽，比不跟随好不了多少）。

现在解算器**按渲染时钟采样**：每个点用 `animation.sample()` 读该时刻遮罩中心的真值（渲染用的就是它，
两者不可能再各说一套），再把窗口内需要的平移/缩放写成关键帧；随后贪心地挑出"当前这条直线代价最大"
的那一段取中点补点，直到补无可补、或偏离中心已经进了容差、或到达 48 个关键帧的上限。

- `ReframeRequest` 新增可选 `tolerance`（`0 < x ≤ 0.25`，默认 `contracts.REFRAME_TOLERANCE = 0.01`
  个画面宽）：这是 Agent 唯一能调的质量/关键帧数量权衡，MCP 的 `clip_reframe` schema 从契约自动生成，
  因此同步出现。数字只有一个来源，界面与 Agent 拿到的是同一个默认。
- 返回的 `reframe` 数字加了 `keyframes_added`（引擎补了多少点）、`tolerance`、`worst_offset`
  （按写出来的曲线实际采样出的最大偏离中心距离，不是推测值）。界面提示直接报这个实测口径。
- 时钟口径：`reframe.ticks` 与命令里的 `at_ticks` 都是**片段内** tick，和 `keyframes.replace` 一致。
- 顺带去掉两条因"手工配对关键帧"才存在的假拒绝：只动画一条轴（另一轴按静止中心跟随）、
  两轴插值方式不同（各自按自己的曲线跟）。`hold` 路径保持阶梯（补点不会把台阶抹平成斜坡）。
- **关键帧预算**：真实跟踪每帧写一条遮罩关键帧，20 秒就是 1200 条，再叠三条同样密的跟随曲线会  撑破 `Clip.keyframes` 的 2000 条上限——计划说可以、写入被拒。种子点先按`min(48, (上限 − 已有) // 3)` 均匀抽样（上限数字从契约字段元数据里读，不另写一份），再在预算内  贪心补点；`reframe.keyframes_dropped` / `keyframe_budget` 报出省了多少、预算是多少，  装不下时警告里说清「按均匀采样跟到 X 宽」。
- 不新增工程状态、不改 schema（仍 v12）；写入仍是一个批次一个 revision，仍只有 reducer 决定什么是
  合法关键帧。`APP_VERSION` 1.47.0（`desktop/package.json` 同值，标题栏徽标即它）。

## 1.48 同一片段的缩放 + 淡入淡出不再让渲染进程崩掉（成片级缺陷修复）

新增的门禁 `tests/curvefidelity_check.py` 不再只在关键帧时刻取样，而是**在关键帧之间**密集探测，
并把像素量出来的位置 / 面积 / 电平与引擎自己的采样器 `animation.sample()` 逐点比对。它第一次跑就抓到
渲染层的硬崩溃：

- 复现：一条片段同时带 `scale` 与 `opacity` 关键帧（缩放 + 淡入淡出，最普通的动画组合），且它在多轨
  时间线的上层。
- 现象：FFmpeg 进程直接死掉，任务失败 `FFMPEG_FAILED`，退出码 3221225477（0xC0000005）/
  3221226356（0xC0000409），**stderr 一个字节都没有**——所以界面只能报「渲染失败」，人拿不到任何线索。
- 定位：逐属性二分（只 x、只缩放、只透明度各自都正常；x+缩放、x+透明度正常；缩放+透明度必崩）。
  原因在滤镜顺序：不透明度的 `geq` 写在按帧改尺寸的 `scale=…:eval=frame` **之后**，`geq` 是按喂给它的
  画面尺寸分配缓冲的，尺寸每帧一变就越界。
- 修法：把遮罩与不透明度合成**一次** alpha 通道写入，放在任何会改变尺寸的滤镜之前。乘法可交换，
  `rotate` 的填充本来就是透明黑（乘不乘透明度都是 0），所以语义不变，还少了一次逐像素遍历。

不新增状态、不改 schema（仍 v12）、不改契约。`APP_VERSION` 1.48.0。

新门禁同时钉住三件事：13 个关键帧之间的探测点与权威采样一致（位置 / 面积 / 电平各有容差）；上层片段
按它自己的淡入淡出曲线与下层真实混合（检查用 `animation.sample` 读出该时刻的 alpha，算出应有的 RGB 再与
像素比，而不是假定一个固定 50%）；以及它对旧渲染器会红——用 `git stash` 把修复撤掉后，该检查以
`FFMPEG_FAILED` 失败，证明它抓的是真缺陷而不是自我确认。另有一次独立探针：静态 50% 不透明度的上层盖在
红色轨道上，导出量到 126/31/31，正是 0.5 混合该有的值（若 alpha 被丢掉会是 64/64/64）。

## 1.49 渲染失败终于说得清（不改契约，只改那句人话）

1.48 定位崩溃时，任务里只有一句 `FFmpeg 退出码 3221225477：`——冒号后面是空的，因为进程连一行错误
都没来得及写。人对着这句话什么也做不了，Agent 读 `/v1/jobs/{id}` 也只能拿到一个数字。

- `jobs.describe_exit(return_code, stderr)`：把 Windows 的异常码翻译成名字（0xC0000005 访问越界、
  0xC00000FD 栈溢出、0xC0000409 运行时检查中止），保留 FFmpeg 实际输出的**末尾** 3000 字符（错误在结尾，
  开头是编解码器清单），没有输出时明说「没有留下任何错误输出」。
- 任务 `message` 用这句话，`error_code` 仍是 `FFMPEG_FAILED`，不改契约、不改 schema（仍 v12）、
  不新增端点。`APP_VERSION` 1.49.0。

验收（`tests/renderfail_check.py`）：纯函数逐码断言，包括长日志只留尾部且不许出现「退出码 23：」后面
空着；再真删素材跑一次导出，读回的任务消息必须是可读的一句（实测：
`FFmpeg 退出码 4294967294：[in#0 …] Error opening input: No such file or directory …`）。

## 1.50 自由路径遮罩会跟着走了（schema v13）

路径遮罩从前是「一片段一张 PNG」：轮廓画在哪就裁在哪，一旦给它打关键帧，契约直接拒绝。剪映和 AE
都能把套索圈住的主体沿轨迹搬动，这一步补上，并且只补真实的那一半。

- `SCHEMA_VERSION` 12 → **13**：v13 给每条路径一个**贴合轮廓的 box**（`masks.fit_box`，宽高取轮廓
  自身包围盒，中心取包围盒中心，含贝塞尔控制柄鼓出来的部分）。贴合只有一处，发生在
  `apply_commands` 交回结果之前：遍历主时间线、正在编辑的序列以及所有子序列的片段，把路径遮罩的
  box 重算一遍，所以整条片段经 `clip.add`/`clip.insert`/`clip.overwrite`/`clips.add` 进来，与经
  `clip.mask` 就地改遮罩，不可能落在两个位置——这一点是被真实验收逼出来的：包内引擎最初只补了
  `clip.mask`，`clip.add` 带的遮罩仍存着形状默认 box。旧工程在 `projects._fitted` 读取时补一次，
  不改写已提交的历史快照。贴合是恒等变换——同一张轮廓栅格化后逐点一致，验收里直接比像素。
- 关键帧规则（唯一权威 `Clip.mask_animation_problem`）：路径遮罩**接受** `mask_x`/`mask_y`，
  **拒绝** `mask_width`/`mask_height`，报 `INVALID_MASK` 并说清「能搬动、还不能变形」。矩形/椭圆
  仍是四条全开；反相遮罩照旧不能做关键帧。
- 导出编译：轮廓烧成**一张** PNG（`unit_path` 把顶点映射到单位方块，羽化按 `box/patch` 折算，
  并按 3σ 加边距，避免羽化斜坡被轮廓自身的包围盒切掉），再用
  `overlay=x='…':y='…':eval=frame` 在一张中性底板上逐帧搬动；底板颜色按反转取黑或白，所以
  反转路径遮罩依旧保留圈外。之所以是 overlay 而不是逐帧 `scale`：1.48 已经量到过，
  `scale=…:eval=frame` 之后接 `geq` 会让 FFmpeg 不带一句 stderr 直接崩，而 overlay 的
  输出尺寸恒定。预览端 `mask_unit` 对路径给出同一张单位轮廓 SVG，浏览器用
  `--mask-x/--mask-y/--mask-w/--mask-h` 摆它，与导出同源。
- 「跟踪主体」端点对路径遮罩开放，但**只跟平移**：`estimate_scale` 被强制关掉，响应里
  `scale_estimated` 如实为 `false`，能力接口不谎报。`clip.mask_track` reducer 只在拿到尺寸点时
  才写 `mask_width/mask_height`，因此这条路径不会写出渲染不了的曲线。
- 主体跟随重构图（`clip_reframe` / `reframe.plan`）不再区分形状：只要遮罩有中心曲线就跟，路径
  遮罩跟踪之后同样能一键把主体锁回画面正中。
- 界面：路径遮罩的 box 恒等于画好的轮廓，所以 Inspector 不再给它摆「中心 X / 中心 Y」数值行（写了
  也会被批次末尾的统一重算抹回轮廓位置——那是个假控件）；移动轮廓请在画面里拖顶点，随时间移动交给
  「跟踪主体」或曲线编辑器里给「遮罩中心 X/Y」双击加关键帧。曲线编辑器的属性下拉按形状过滤
  （`maskAnimFields`），路径只剩两条位置曲线；「反转遮罩」与羽化照旧可用。编辑向导的顶点层跟着裁切
  走：它从引擎下发曲线正在驱动的那份动画上读回播放头值，再平移 SVG，不重解第二条曲线。

验收（`tests/pathmask_check.py` 新增媒体段）：320×180、1 秒、上层红下层绿，轮廓画在左半。
`mask_x` 从画好的位置线性搬到 0.75 之后，(250,60) 在 0.05 秒是绿、0.95 秒是红，而 (40,60) 反过来；
把曲线写成不动（0.25→0.25）时，取到的画面与静态遮罩逐点一致。反向验证：把 overlay 的 x/y 钉死成
存储中心（撤掉本次修复的等价突变），该检查立刻在 0.95 秒那条断言上变红。
`tests/maskanim_check.py` 另断言路径遮罩的位置曲线通过校验、尺寸曲线被 `INVALID_MASK` 点名拒绝；
`tests/reframe_check.py` 断言路径遮罩现在能被跟随，而无反相/无遮罩等拒绝仍逐条有名。

## 1.53 路径遮罩能整条拖动（AE 式：拖动即当前时刻的搬动）

1.50 让路径遮罩能按曲线搬动，1.51/1.52 让向导跟着裁切走，但**画面上没有搬动整条轮廓的手柄**：
只能一个个顶点拖，或者回曲线编辑器填数。剪映和 AE 都是「在框里按住就走」，这一步补上。

- 轮廓自身成为拖动手柄（`.mask-hit` 走同一条 `d`，顶点仍在上层，先命中顶点就是改形状）。
- 落笔按有没有中心曲线分两种语义（`store.moveMaskCentre` / `commitMaskEdit`，都是一笔一个 revision）：
  - 没有曲线：搬顶点本身，贴合盒跟着重算，遮罩从此处开始就在新的地方；
  - 有曲线（跟踪过或手动打过）：**不搬顶点**，把这次位移写成播放头处的 `mask_x/mask_y` 关键帧——
    动画仍留在轨迹上，只是这一帧换了位置，正是 AE 拖动控制点的行为。
- 可动范围是不对称的 `[−最小顶点, 1−最大顶点]`（轮廓不许被推出画框）；越界由契约退回并显示原因。
- 引擎、契约、schema 都没动。

验收（真实构建产物 + 包内引擎，深链驱动）：无曲线片段拖 +40/+20 px → 顶点整体搬到
(0.5,0.3)/(0.9,0.3)/(0.5,1.0)、贴合盒 (0.3,0.55)→(0.7,0.65)；带中心曲线片段同一拖动 → 顶点不动、
播放头处 `mask_x/mask_y` 由 0.2/0.5 变 0.3/0.55；两次拖动各产生一个 revision。首版把夹取方向写反，
被契约以 `vertices[2].y ≤ 1` 退回（界面如实显示 `INVALID_REQUEST`），改对后拖动全程无错误。

## 1.52 画面向导跟着曲线的尺寸一起缩放（还是客户端，引擎一行没改）

1.51 让拖动能写关键帧，但向导只跟着曲线**平移**：宽度打了关键帧时，画面上的框还是基准宽度，
用户抓的角柄不是他看到的遮罩边缘。这一版把缩放也接上。

- 向导的变换是 `translate(T) scale(S)`，`S` 是动画尺寸 / 基准尺寸，`T = cx_now − S·cx_base − 0.5 + 0.5·S`
  （CSS 以元素中心为原点在缩放后再平移，解出来就是这个式子）。`S=1` 时退化回 1.51 的纯平移。
- 数值来源仍是引擎下发的那份动画：读 `--mask-x/--mask-y/--mask-w/--mask-h` 的当前插值，不在客户端
  重算曲线。路径遮罩的尺寸不能打关键帧（1.50 的规则），所以它的 `S` 恒为 1。
- 拖动写回沿用 `commitMaskEdit`：`mask_width/mask_height` 有曲线时写当前播放头的关键帧，没有时写盒本身。

验收：在真实构建产物里读到动画盒 `(0.206667, 0.5, 0.305, 0.406667)`（基准盒 `0.2/0.5/0.3/0.4`），
生成的内联变换是 `translate(1.1667%, 0%) scale(1.01667, 1.01667)`；把**同一条式子**放进一个可测量的
Chromium 盒子（400×200，见 `agentcut-验收脚本/guide_transform_152.html`）里量基准框的落点，
得到 left 29.667 / top 67.333 / width 122 / height 81.333，与按动画盒算出的期望**四项误差 0**。
无头视口把预览列压到 0 宽，所以几何在页面里量不到——这一步把「式子对不对」和「盒子有没有宽度」分开，
两边各自可测。

## 1.51 画面里拖遮罩就是打关键帧（客户端行为，不改契约）

1.50 让遮罩能按曲线动，却留下一个交互窟窿：`MaskPicture` 的向导在**有曲线时整块隐藏**，跟踪过的遮罩
就再也拖不动了；而 Inspector 的数值行早就做了「该属性有曲线就写关键帧」，画面上却没有——同一个动作在
两处行为不一致，用户只能回面板填数字。

- 向导在遮罩打了关键帧后**照常出现**，并跟着此刻的裁切平移（读的是引擎下发曲线正在驱动的那份动画值）。
- 落笔处按形状分流（`store.commitMaskEdit`，一笔提交、一个 revision）：
  - 矩形/椭圆：拖动改变了**已有曲线**的属性 → 写当前播放头的 `keyframe.set`；没打关键帧的属性 → 写
    `clip.mask`。两者在同一条命令里，所以引擎的 `expected_revision` 与撤销都按一次编辑算。
  - 路径：顶点是轮廓本身，box 是从顶点算出来的派生量——拖动只写 `clip.mask`，**不**顺手把中心曲线
    钉在当前时刻（否则拖一个顶点，整个遮罩就不再跟曲线走了）。
- 契约、reducer、能力接口都不变（`APP_VERSION` 1.51.0，`SCHEMA_VERSION` 仍 13）。

验收（发布包界面 + 包内引擎，`?engine/&token/&project` 深链驱动真实构建产物）：
- 拖框：工程 revision 1→2；`clips.box.keyframes` 多出 `mask_x`/`mask_y` 各一条，`at_ticks=2352000`
  （第 1 帧 = 播放头），值 0.6/0.6 正是拖到的位置；0 秒与 2 秒的原有端点原样保留。
- 拖路径顶点：revision 2→3；顶点从 (0.1,0.2) 移到 (0.505,0.405)，贴合盒重算为
  `center=(0.3025,0.55) size=(0.405,0.7)`，而关键帧集合仍是原来的 4 条——派生量没有变成用户意图。
- 向导可用性：打了位置曲线后 `svg.mask-guide`、`.mask-hit` 与 4 个 `.mask-handle` 实测都在。
- `npm run typecheck`、6 个壳层检查、`tests/suite_check.py` 48/48 全过。

仍未完成：路径遮罩的**顶点/形状动画**（要逐帧重栅格化）、路径遮罩的尺寸动画、多目标与长时遮挡
跟踪、旋转估计。


## 1.57 交付格式：容器、编码与采样格式都由预设决定（工程 schema 不变）

「导出」以前只有一种答案：H.264/AAC 装进 MP4。这一版把交付的三件事——容器、视频/音频编码、
采样格式——交给预设表，并把「文件名后缀必须是该预设的容器」写成一条规则。

```
POST /v1/projects/{id}/renders
{ "request_id": "r", "expected_revision": 4, "preset_id": "vp9-1080p-web",
  "filename": "网页版.webm" }        // 后缀跟着容器：.mp4 / .mov / .webm
```

- 预设多出三个键：`audio_codec`、`pixel_format`、`profile`；`crf`/`encoder_preset`/`audio_bitrate`
  改成可以为 `null`——ProRes 由 profile 决定质量，VP9 的 crf 必须配 `-b:v 0`，PCM 无所谓码率。
  `GET /v1/render-presets` 与 `capabilities.render_presets` 原样下发，界面只念不写。
- 新增预设：`h265-1080p`、`h265-2160p`（MP4 + `hvc1`，让 QuickTime 和剪辑软件认）、
  `vp9-1080p-web`（WebM + Opus）、`prores-422hq`（MOV + 24 位 PCM，`yuv444p10le`）。
- `render.output_args(preset, sample_rate, frame_rate)` 是**唯一**把预设变成 FFmpeg 参数的地方，
  按 codec 名字分派，只认 `OUTPUT_CODECS` 那张闭表；不在表里的 codec 直接 422，不会拼出一条没验证过的
  命令。调用方自始至终只能给 `preset_id`，拿不到任何原始参数位（AGENTS.md「不把 FFmpeg 参数作为工具暴露」）。
- `pixel_format` 不是只写进 `-pix_fmt` 的装饰：它同时是解码段、`fit_stage` 与 `[vout]` 的 `format=`。
  只在编码参数上写 4:4:4 而画面链中途压成 4:2:0，等于换个壳子撒谎。
- 契约侧 `checked_render_name` 的后缀由 `preset_container(preset_id)` 查表得到，单条与批量共用这一条
  规则；未知 `preset_id` 不在这里抢错误，仍由 `render.preset_by_id` 报 `UNKNOWN_PRESET`。
  `jobs` 写文件前的同一处检查与 `.part.<container>` 临时名也改为跟随容器。
- capabilities：新增 `output_containers`（`mp4/mov/webm`）与 `features.multi_codec_delivery`
  （与其余渲染能力一样按 `media_ready` 声明）。
- 工程 schema 仍是 v13，`Recipe`/`RenderBatchItem` 的形状没变，旧预设 id 与旧回执照读；预设表是
  纯增量，1.56 之前存的交付方案不动。

验收与实测：见 `tests/format_check.py`（契约自洽 + 参数分派 + 真实导出四份 + Cb 平面色差宽度）与
`tests/desktop_format_check.ts`（界面那一行完全由预设算出）。

**本轮抓到的一个真实交付缺陷**：FFmpeg 给 WebM/Opus 的第一条进度行是 `out_time_us=-6500`
（Opus 编码器前置延迟把音频轨放到零之前），换算成整数 tick 是 -458640；`RenderJob` 的
`rendered_ticks >= 0` 当场拒绝，worker 把任务判成 `RENDER_CRASHED`，而 `finally` 之后临时文件还挂在
原地。任何一条 WebM 导出都会撞上它。修法是在读遥测这条边界上夹住——进度不是时间线的事实，不能原样
写进带约束的状态里。这个缺陷不是设计出来的题，是新写的检查第一次真跑 VP9+Opus 时抓出来的。

**没测的就不说**：HEVC 的标签不写「体积更小」。在一段 2 秒 1080p 合成测试片段（`testsrc2`）上实测
x264 crf 23 得 SSIM 0.996313 / 1,409,249 B，x265 crf 24 得 0.996687 / 1,734,249 B，x265 crf 26 得
0.995211 / 1,425,982 B——这段素材上 HEVC 并不省体积。实拍素材上通常更省，但本轮没有量过，
所以预设只声明编码格式，不承诺体积。

仍未完成：纯音频交付（MP3/WAV，需要让「没有画面的时间线」也能编译）、MXF/DPX 一类后期格式、
路径遮罩的顶点/形状动画、多目标与长时遮挡跟踪、旋转估计、色彩节点图的分层与连线。


## 1.58 纯音频交付：`codec=null` 表示根本没有画面链（工程 schema 不变）

「只要声音」是交付页的常规出口（口播、配乐、进混音台），以前这里根本没有出口：`compile_render_plan`
遇到没有可见画面层的时间线就报 `EMPTY_TIMELINE`，而所有预设都强制 `-c:v`。

```
POST /v1/projects/{id}/renders
{ "request_id": "r", "expected_revision": 4, "preset_id": "audio-mp3",
  "filename": "口播.mp3" }        // 容器 mp3 / wav / flac，后缀仍是预设的事
```

- 三条新预设：`audio-mp3`（libmp3lame 192k）、`audio-wav`（pcm_s24le）、`audio-flac`。它们的
  `codec`、`pixel_format`、`scale` 都是 `null`，这是「没有画面」在契约里的唯一写法。
- `OUTPUT_CONTAINERS` 加 `mp3/wav/flac`，`OUTPUT_CODECS` 加 `None`，`OUTPUT_AUDIO_CODECS` 加
  `libmp3lame/flac`；`render.output_args` 对 `codec is None` 只给 `-vn` 与音频参数，不给
  `-c:v`/`-pix_fmt`/`-movflags`。
- `RenderPlan.mode` 多一种取值 `"audio"`：画面链**整段不编译**（不是编完再丢弃），所以 `ffmpeg_argv`
  只有一个 `-map`，输入里只出现有声素材。区间导出（`range=marks`）此时只 `atrim`，不再 `trim` 画面。
- 只有画面、没有声音的时间线：按名字拒绝 `EMPTY_TIMELINE`「an audio deliverable needs audible
  material」；同一条时间线出画面照旧。
- capabilities 新增 `output_containers` 的三个音频容器与 `features.audio_delivery`。
- 界面：`presetIsAudio()` 为真时，「画幅适配」三个芯片灰掉并写明「音频交付没有画面」，「附带竖屏」
  同样灰掉，预设那行写「仅音频 · MP3」而不是编一个不存在的编码器；主按钮要发的清单仍只算一次
  （`pendingItems`），灰掉的那条不会偷偷混进批次。

验收：`tests/audio_check.py`（参数分派 / 画面链没建 / 无声时间线拒绝 / 三份真实导出 + 单流 +
两个音都在 + 与视频成片同一次混音的 LUFS / 区间音频 / 后缀互斥）与
`tests/desktop_format_check.ts`（音频行的文字与 `presetIsAudio` 的三态）。


## 1.59 转场扩到九种：方向擦除与缩放（工程 schema 不变）

以前只有叠化、淡黑、闪白三种，全都是「整幅均匀变透明」。这一版加上空间揭示与尺寸变化，
并把种类清单交给引擎。

- `Transition.kind` 与 `transition.set.kind` 共用一个 `TransitionKind`，新增
  `wipe_from_left` / `wipe_from_right` / `wipe_from_top` / `wipe_from_bottom`（按揭示边缘**从哪条边框
  开始**命名，避开「向左擦除到底往哪走」的歧义）与 `zoom_in` / `zoom_out`。
- `capabilities.transition_kinds` 下发 `{id,label}` 列表；界面的下拉框与时间线上的转场徽标都读这张表，
  老引擎（没有这个字段）才退回三条。**新增一种转场不需要改界面**：reducer 认了、编译得出，下拉框就有。
- 数学全在 `transitions.py`：`envelopes()` 除原有的 picture/sound/black/white 之外多给两条——
  `wipe`（`{kind, invert, curve}`，两侧共用同一条 0→1 进度）与 `scale`（缩放因子折线）。
  擦除**不碰画面权重**：两侧都保持 1.0，只有声音照常交叉淡化；`render` 把 `wipe_expression()` 出来的
  空间斜坡乘进那一层的 alpha，出画那一侧取互补，于是同一像素上两层加起来仍是一个 alpha。
- 边界不是硬边：`WIPE_FEATHER=0.02` 幅宽的渐变带，`edge = p·(1+feather)`，正好在窗口结束时抵达对边。
- 缩放走 `scale` 滤镜的时间表达式（时钟是 `t`，不是 `geq` 的 `T`），`zoom_in` 从 1.6× 收到 1×、
  `zoom_out` 从 1× 收到 0.6×，都与叠化同时发生。
- 没有新增输入、没有新滤镜依赖，`fit` / 遮罩 / 母带处理链路不变；工程 schema 仍是 v13，
  1.58 之前存的转场（三种）照读照放。

验收：`tests/wipe_check.py`（契约与表同源、包络不动画面权重、成片量边界位置、羽化带半和证明
alpha 相加为一、缩放量已知方块、叠化回归、九种往返与未知种类拒绝）与
`tests/desktop_format_check.ts`（下拉列的是引擎表、未知 id 原样显示）。

## 1.60 交付前先复检：`succeeded` 现在意味着文件被量过（工程 schema 不变）

以前任务成功的判据是「FFmpeg 退出码 0」加上「临时文件非空」。这一版在把 `.part.<容器>` 命名成
最终文件**之前**，用它旁边的那个 ffprobe 重新打开产物，按渲染计划逐项核对。

- `RenderJob` 多一个布尔字段 `output_checked`（默认 false）。它是三种真实状态之一：
  `true` 且 `message` 带实测值（`已输出 x.mp4（复检：3.000 秒 / 2 路流（h264/aac）/ mp4，尾部可解码）`）；
  `false` 且 `message` 写明「未经复检：… 目录里没有 ffprobe」；或 `false` 加 `status=failed` 与
  `error_code=OUTPUT_INVALID`。界面在已完成但 `output_checked=false` 的任务行上给「未复检」黄标。
- 复检只认**同一个 FFmpeg 旁边**的 ffprobe（`ffprobe_beside()`），不从 PATH 借，也不用 `--ffprobe` 那一份：
  换一个构建的 demuxer 来量这台机器上写出的容器，量的是别人的实现而不是这次编码的事实；
  `--ffprobe` 是入库素材用的探针，两个用途分开，谁也不绑架谁。旁边没有就不量，并如实说出来。
- 核对四件事，全部按 `error_code=OUTPUT_INVALID` 拒绝并**销毁候选文件**（最终名一次都不出现，导出目录
  里不留 `.part.`）：
  1. 读得出流（ffprobe 非零退出、或 JSON 里 `streams` 为空即拒）；
  2. 流的种类对得上计划——`plan.video_label` 非空必须有视频流，纯音频预设（`-vn`）必须没有视频流，
     两种情况都各有一条拒因；声音流恒必存在（混音以 anullsrc 打底，`[aout]` 总在）；
  3. `format.format_name` 必须包含预设点名的容器（webm 读作 `matroska,webm`，mp4/mov 读作
     `mov,mp4,…`，所以按逗号切开取成员，不按扩展名）；
  4. `format.duration` 与 `plan.duration_ticks` 相差不得超过 `max(0.150 秒, 两帧)`。实测七种容器的
     合法偏差是 mp4/mov/wav/flac 0.000、webm 0.008、mp3 0.024 秒（编码器前置延迟），容差是它们的六倍。
- 第四条查不出截断写，所以再加一次**尾部解码**：用同一个 ffmpeg 从 `时长-0.5 秒` 起把两路流解到结尾
  （`-f null`），`-v error` 下有任何输出即拒。这条不是猜测：一个只写了 30 % 字节的 faststart MP4，
  头部仍报两路流与 3.000000 秒，元数据四项全部放行，是尾部解码的 `partial file` +
  `Invalid NAL unit size` 把它拦下来的。代价实测每份 0.044–0.066 秒。
- `capabilities.verified_delivery` 按 `media_ready` 声明；纯音频预设的复检只看声音流，画面链本来就没编译。
- 渲染计划、命令行、容器选择、母带链一律不变；这是成功判定这一层的收紧，不是新的剪辑能力。
  工程 schema 仍是 v13，`RenderJob` 的 JSON 是加法（旧任务快照读回来 `output_checked=false`）。

验收：`tests/verify_check.py`（六类坏文件各按原因拒、截断那条用差量实测证明元数据会放行、
`ffprobe_beside` 只认同目录、三个真跑的任务分别量过/无探针/探针失灵且失败后目录为空、
`verified_delivery` 下发；三处变异各让对应断言红一次）；`tests/format_check.py` 与
`tests/audio_check.py` 的每份真实导出现在都断言 `output_checked is True`。

## 1.61 自动语音字幕（2026-10-07）

新端点 `POST /v1/projects/{project_id}/speech-captions`，载荷 `{request_id, expected_revision,
clip_id?|track_id?（二选一）, language="zh"|"en", max_chars=16(4..60), replace_track_id?,
apply=false, dry_run=false}`。引擎把选中片段（或整条轨逐个片段）的原片声音抽成 16 kHz 单声道，
交给本机 vosk 模型识别（词级时间戳），按行长/时长/停顿断行成字幕线索，换算到时间线 tick
（速度线性换算，带变速曲线的片段与静音扫描一样被拒绝/跳过）。回包 `speech` 是
`{cues:[{from_ticks,to_ticks,text}], srt, command, commands, language, model, clips:[…skipped…]}`；
`commands` 是落库计划：`replace_track_id` 给出时先 `clip.remove`×N + `asset.remove`×N +
`track.remove` 再 `captions.import`，否则只有 `captions.import` 一条——新字幕轨与素材的 id 由
scope+cues 的摘要决定（不含 request_id），同一段话永远映射同一条轨：重放走回执去重，换
request_id 重跑会被 reducer 以 DUPLICATE_ID 拒绝而不是叠出第二条一样的轨。`apply=true` 时引擎
按既有 EditBatch 语义一次写入；`dry_run` 只出前瞻快照。识别不出任何语句报 `SPEECH_NOT_FOUND`，
模型缺失报 `SUBTITLES_MODEL_MISSING`（422，点名语言与放置目录），vosk 未安装报
`SUBTITLES_UNAVAILABLE`（503）；模型目录查找顺序：`AGENTCUT_ASR_MODELS` → 冻结引擎旁的
`asr/` → 数据目录 `asr/`；路径含非 ASCII 时运行时复制到 `%PROGRAMDATA%\AgentCut\asr` 再加载
（libvosk 的 ANSI 文件 I/O 打不开中文路径，实测确认）。`capabilities.speech_captions` 按
`media_ready && vosk 可导入 && 至少一个模型在盘` 声明。MCP 只读工具 `captions_auto`
（`apply`/`dry_run` 固定 false）。验收 `tests/asr_check.py`：SAPI 合成真实中文语音 → 识别断言
（≥2 条线索、关键短语在文本里、时间落在片段内、SRT 重解析条数一致）→ apply 一个 revision、
重放 replayed、换 request 撞 DUPLICATE_ID、dry-run 不落库、replace 原位重生成同 id 轨 →
真实导出帧里有字幕亮像素、前导空帧没有 → 200% 速度下同样的文本落在减半的时间上 →
无声素材/变速曲线/双语种缺模型各按原因拒绝。

## 1.62 LUT 查找表导入（`.cube` 1D，工程 schema 仍是 v13）

调色节点里多一种 `lut`：`{kind: "lut", title, size, channels:[[r…],[g…],[b…]], enabled, mix, blend}`，
三个通道各一条折线，`channels[c].length == size`（契约校验），`size` 2..`LUT_SAMPLE_LIMIT`（1024），
采样点取值 0..1。它仍是**每通道函数**，所以整条链照旧塌缩成一张每通道表，`lutrgb` 与浏览器
`feComponentTransfer` 读同一组数——这是不做「3D LUT」的唯一原因：3D 表的输出红取决于输入的绿与蓝，
那是跨通道矩阵，不再是每通道一条曲线，硬压成三条就是骗人。

`.cube` 文本**只由引擎的 `grade` 解析器读一次**（1.62 时是 `parse_1d_cube`；1.103 起 `/v1/lut/parse` 走 `parse_cube`，由表头分派到 1D 或 3D）。客户端（桌面界面）与 Agent 都不自己解释文件：
`POST /v1/lut/parse`（MCP 只读工具 `lut_parse`）收 `LutParse{content}`（1..512 KiB 文本），回
`{title, size, channels}`，那就是一份可直接写进 `clip.color.grade` 的载荷（1.103 起同一端点对 3D 立方表回 `{title, size, cells, resampled_from}` 并带 `kind:"lut3d"`）；超过 1024 行的表按等距网格
重采样，并在回复里带上 `resampled_from`（原文件的行数），界面把它说给人听，不静默改数。解析规则：
只认 `LUT_1D_SIZE`（大小写都读），`TITLE` 可带引号可含空格，`#` 注释与空行跳过，CRLF 可用，行内三个数
按 R G B 顺序、越界值夹到 0..1；`DOMAIN_MIN/MAX` 非默认、声明行数与实际不符、读不出数字、
行列数不对，各自 422 `INVALID_LUT` 并写明原因（新错误码只有这一个，走既有 EditorError 信封）。`LUT_3D_SIZE` 从 1.103 起不再是这一串的拒绝项而是另一种表：见本文末 1.103 一节。
`GET /v1/contracts` 现在也回 `LutParse` 的 schema。

命令层不新增任何一条：写入仍然是 `clip.grade`（整串替换）或 `clip.patch` 的 `color.grade`，HTTP/MCP/界面
共用同一条 reducer 路径，`mix`（0..1 与输入按比例混合）与 `blend`（八种可分混合）与其它节点完全同义，
`mix=0` 或 `enabled=false` 时连滤镜阶段都不产生。

上限的唯一主人是 `capabilities.grade_limits = {max_nodes: 8, max_branches: 4, max_curve_points: 16,
max_lut_samples: 1024}`，界面从这份表限制节点数、曲线控制点数、并联支数与 LUT 采样数，不再自带数字
（1.55 的同一课）；`features.lut_import=true`。验收 `tests/lut_check.py` 与
`tests/desktop_graph_check.ts`：解析层用「自己按公式写出来的文件」逐值核对（构造即事实，不拿解析器再
解析一遍），768 格浏览器表对独立写出的等距线性插值最大 0.125 阶，编译出的 `lutrgb` 串喂给 FFmpeg 自己
的求值器（256 级灰度斜坡、不经编码器）三条通道各 1.00/1.00/1.09 阶，真实 H.264 成片六档灰带
[2,18,62,126,194,249] → [0,2,41,137,235,253] 十八个点全部对得住下发的表，parse 回复直接进 `clip.grade`
往返 17×3 个采样点一字不差，七种写坏的载荷 422 且 revision 不动，3D/缺 size/行数不符/非默认 DOMAIN/
读不出数字/行列数不对各按原因拒绝，2048 行的文件重采样到 1024 并写明 `resampled_from`。

## 1.63 文字样式（工程 schema 仍是 v13）

`TextStyle` 在原有 `body / font_size / color / align / box` 之外长到 15 个字段，全部是**字号的比例**：
`font`（face id）、`text_align`（left|center|right）、`outline_width`（0..0.2）、`outline_color`、
`shadow_x`/`shadow_y`（-1..1）、`shadow_color`、`box_color`、`box_opacity`（0..1）、`line_spacing`（0..2）。
颜色一律 `#rrggbb`。命令不变：还是 `clip.text`（整份替换）与 `clip.patch` 的 `text`（按字段改），
后者不再手写键清单，而是拿 `TextStyle` 复检（`{"body": ".", **text}`），所以字段再长也不会漏。

导出侧编译成 `drawtext`：`fontsize=out_h*font_size`、`borderw=round(outline_width*fontsize)`、
`bordercolor`、`shadowx/shadowy=round(offset*fontsize)`、`shadowcolor`、`line_spacing=round(...)`、
`x` 按横排取 `w*0.08` / `(w-text_w)/2` / `w-text_w-w*0.08`；`box` 仍然用 `geq` 的 alpha 带表达
（drawtext 自带的垫子不可靠），带色与浓度由 `box_color`/`box_opacity` 决定。界面侧 `desktop/src/textStyle.ts`
把**同一组数**写成 CSS（`em` 单位、`lineHeight = 1 + line_spacing`、`text-shadow` 模糊位固定 0、
`linear-gradient` 的垫子带），因此不存在「只有预览里有」的效果。

**没有的两档**：阴影模糊与字距（letter spacing）。drawtext 画不出这两样，给了就只有浏览器看得到，
所以不做——与 1.62 拒绝 3D LUT 是同一条理由。

字体：`GET /v1/capabilities` 新增 `text_fonts = [{id, label, family}]`，只列**本机真的存在字体文件**的
face（Windows 下微软雅黑/黑体/宋体/楷体/Arial/Consolas）。`fontfile` 路径必须写成
`C\:/Windows/Fonts/<file>`：正斜杠加转义冒号。反斜杠形式（`C\:\Windows\...`）不报错，drawtext 会
悄悄退回默认字面，两种字体逐像素相同——这是本轮实测踩到并用像素钉住的坑，`text_font_path` 一次
转换、`tests/textstyle_check.py` 断言三种字体三张不同的图。点了一个本机没有的 face 报
`FONT_UNAVAILABLE`（503）并列出可用项，绝不静默换脸。

`features.text_styling=true`。默认值等于 1.62 的渲染（4% 黑描边、0.2 行距、115/255 黑垫），
老工程读回来逐像素不变；`_fingerprint` 按「晚于该载荷时代的字段不算请求内容」的规则自动兼容
（从 `TextStyle.model_fields` 推导，不再手写 align/box 两个名字），所以 v1.5/v1.7 的文字回执照旧命中。
验收 `tests/textstyle_check.py`（契约、字体可用性、编译串、成片像素、HTTP 往返五路）与
`tests/desktop_text_check.ts`（CSS 逐字段）：描边加粗后红环 1639 px、阴影质心右移 31.1 px、
垫子灰阶实测 64（要 64）、左/右质心 70 对 252、黑体与宋体在 712 个像素上不同。

## 1.64 片段柔焦：一个半径，两端同高斯（工程 schema 仍是 v13）

`ClipEffects` 新增 `blur: float`，取值 `0..0.25`（`capabilities.limits.blur_fraction`），语义是
**画面高的比例**：真正的半径 `R = blur × 画面高`，由 `contracts.spatial_radius()` 一处定义，导出与预览
都从这里取数，谁也不许自己换单位。命令不变，仍然只有 `clip.patch` 的 `effects`——为此把「可写入的
效果字段」与「可打关键帧的属性」分开了：契约里 `EffectProperty`（六条可动画）与
`EffectField = EffectProperty | "blur"`（七条可 patch）各管各的，客户端的 `AnimatedEffect` 同构。
`Keyframe` 的 `property` 仍只接受那六条，所以 `blur` 天然没有关键帧。

编译落点：`render.focus_stages()` 在片段已经缩放到输出画幅之后、遮罩 alpha 之前插入
`,gblur=sigma=R:steps=6`；`blur=0` 时整段不出现。画面链有两条——需要合成的走分层链，单轨且没有
任何东西要合成的走 `cut` 快路径——两处都在同一个位置插入同一个串（快路径的 `fit_stage` 因此拆成
`fit_pre`/`fit_post`，中间按需塞 `format=rgba,gblur=…`），因为「谁决定走哪条链」是一份手写枚举，
新字段很容易静默掉出外面：1.64 的发布验收就是这么抓到「单轨工程导出是锐的、预览是柔的」的。
预览侧 `preview_manifest` 的 `color_filter` 追加
`blur(blur×100cqh)`——1cqh 正好是画面渲染高的 1%，所以两端的数字是同一个半径。层级顺序也是同一个：
CSS 先 `filter` 后 `mask-image`，FFmpeg 先 `gblur` 后 `geq a=`，因此「遮罩里柔、遮罩外原样」这条
打码语义两端一致。

**为什么写 `steps=6`**：用随包的 FFmpeg 与 Chromium 实测（阶跃边沿取 50% / 84.13% / 15.87% 三个
交叉点，即直接量标准差）。`gblur=sigma=S` 在默认 `steps=1` 下的实际半径只有 **0.81×S**（S=1/4/8/16/32/64/128
量到 0.838/0.817/0.805/0.813/0.814/0.813/0.806），而 CSS `blur(Rpx)` 是 0.96–1.07×R；换成 `steps=6`
后 FFmpeg 落在 **0.954..0.991×S**，与浏览器在 ≥8 px 时相差约 2%、以下相差不到半个像素。
所以这不是「猜的系数」，是把两个实现拉到同一个半径上的实测选择。

超过 **64 px** 的半径是拒的，不是夹的：`BLUR_OUT_OF_RANGE`（422），`details` 里点名是哪个旋钮
（`blur` 或 `sharpen_radius`）、`radius` 与 `max_radius_fraction`（= 64 / 画面高），因为一致性只在那个带里量过。界面滑杆的上限用同一个函数算
（`desktop/src/effects.ts` 的 `blurMaxPercent`，取 `blur_fraction` 与 `blur_radius_limit_px/画面高`
的小者），因此不存在「界面给得出、引擎拒得了」。旧引擎不下发这两个字段时该行直接隐藏。

**回执兼容**：加一个带默认值的字段会改变载荷的 dump，`_fingerprint` 里原来的「effects 整份等于
默认就丢掉」是全有或全无的比较，对**设了 opacity 却没提 blur** 的老载荷会多带一个键、把回执劈成
两半。现在按 1.63 文字样式同一条时代规则推导：晚于该载荷时代的字段只要还在默认值上就不算请求内容
（1.64 之前的六个键名在 `projects.py` 里列出，其余从 `ClipEffects.model_fields` 取默认值）。
两个锚点摘要（全默认 `550dda4e…ad88`、opacity=0.5 `e811fc4f…c52f`）由删掉 `blur` 字段后的同一份代码
跑出，写在 `tests/blur_check.py` 里。

`capabilities`：`features.clip_blur=true`，`limits.blur_fraction=0.25`，
`limits.blur_radius_limit_px=64.0`；MCP 的 `timeline_edit` schema 会点名 `blur`（`self_check` 断言）。

验收 `tests/blur_check.py`：要 18.0 px（`blur=0.1`，180 px 高）的成片量到 **17.26 px**，同一条边沿
关掉柔焦只量到 **0.34 px**（证明这个测量本身有分辨率），过 H.264 后第 10 帧仍 **17.24 px**；矩形遮罩外
与不模糊版本逐点相同（**0 级差**）、遮罩内与全模糊版本相同（0 级差）；`gblur` 在编译图里恰好出现一次
（只糊上面那条轨）；`color_filter` 给的 `10cqh` 折算回像素与 sigma 完全相等；280 px 高的画幅给 0.25
被 `BLUR_OUT_OF_RANGE` 拒。变异验证：`steps=6`→`1` 时量到 14.57 px 当场红；去掉滤镜段时红在
「the blur radius never reached the exporter」；把 `blurMaxPercent` 的上限只按 fraction 算时
`tests/desktop_blur_check.ts` 当场红。**没有做**的：逐帧柔焦（`gblur` 只有 `enable` 这种开关窗，
导出会变成阶梯）。锐化在 1.65 补上，但仍不走 FFmpeg 的 `unsharp`（那是整数窗口卷积，和预览的
高斯不是同一个核对不上），而是用同一次 `gblur` 采样做 unsharp mask。

## 1.65 清晰（unsharp mask）：同一个高斯，两端同一条式子（工程 schema 仍是 v13）

`ClipEffects` 再加两个键：`sharpen: float`（`0..2.0`，`capabilities.limits.sharpen_amount`）与
`sharpen_radius: float`（`0..0.25`，默认 `0.004`，即画面高的 0.4%）。语义仍是**画面高的比例**，
半径同样只由 `contracts.spatial_radius()` 一处给出，命令也只有 `clip.patch` 的 `effects`。

一条式子在两端各跑一遍：

```
out = clip(source + sharpen * (source - gaussian(source)), 0, 255)
```

导出是 `split=2` → `[b]gblur=sigma=R:steps=6:planes=7` → `[a][b]blend=c0_expr='clip(A+a*(A-B),0,255)'`
（c1/c2 同式），预览是 `<filter>` 里 `feGaussianBlur` + `feComposite operator="arithmetic"`
`k2=1+a, k3=-a`。两处都必须写 `clip(...,0,255)`：实测 `blend` 不做钳位而是**按 256 取模回绕**
（255+0.8×69 读回 54），浏览器的 arithmetic 天然钳位，少一个 `clip` 就是一端亮一端翻转。
`planes=7` 与 `c3_expr='A'` 是为了不碰 alpha：走到这一步的 alpha 还是均匀的，遮罩 alpha 在之后才乘上去。
半径上限沿用 1.64 那条实测带（同一个 `gblur` 采样），超了就 `BLUR_OUT_OF_RANGE` 点名 `sharpen_radius`；
强度越界是契约的事，`INVALID_REQUEST`（422），且**不烧 revision**。

`capabilities`：`features.clip_sharpen=true`，`limits.sharpen_amount=2.0`、
`limits.sharpen_radius_fraction=0.25`、`limits.sharpen_radius_default=0.004`；
`timeline_edit` 的 MCP schema 点名 `sharpen`（`self_check` 断言）。界面两行的上限由
`desktop/src/effects.ts` 的 `sharpenLimits(caps, 画面高)` 算，与柔焦共用同一个像素带，旧引擎不下发
`clip_sharpen` 时两行一起隐藏。

验收（并入 `tests/blur_check.py`）：`blur=0.1` 先把边沿铺到 **17.26 px**，再加 `sharpen=2.0`
（半径同 18 px）收到 **9.52 px**——样片是白|黑硬边，光晕会钳位，所以诚实的量法是斜率宽度而不是
过冲高度；羽化 0.5 的矩形遮罩下，加与不加锐化的 alpha 斜坡逐点最多差 **0 级**，而形状内部确实变了
（反向断言，防止量空气）；`planes=7`、`clip(A+2.0*(A-B),0,255)`、恰好一个 `c3_expr='A'`、
`split=2` 与 `blend=c0_expr=` 都在编译图里，**两条画面链各自都查**（`cut` 快路径也补了一条）；
预览侧 `bbox` 折算回像素与导出的 sigma 完全相等（横纵各查一次，`objectBoundingBox` 单位下 1 就是整框）；
`sharpen=2.5` 在 HTTP 层 422 且 revision 不动；280 px 画幅给 `sharpen_radius=0.25`（70 px）被点名拒绝；
回执锚点再加两条：`{...,"sharpen":0.0}` 仍命中 1.64 的摘要，只写默认 `sharpen_radius` 也命中。
变异验证：把 `:planes=7` 去掉红在图里、把 `c3_expr='A'` 换成锐化式子红在「alpha must be excluded」、
把 `clip(` 去掉红在「lost its clamp」、把 `sharpenLimits` 的像素带项删掉则
`tests/desktop_blur_check.ts` 当场红。**没有做**的：锐化关键帧（与柔焦同理，导出只有开关窗）、
边缘相关锐化（`guided`/`boxblur` 那条核函数在浏览器没有对应实现）。

## 1.66 画面稳定：把相机的位移量出来，再反向写成关键帧（工程 schema 仍是 v13）

入口是 `POST /v1/projects/{id}/clips/{clip}/stabilize`，载荷 `ClipStabilizeRequest`：
`request_id`、`expected_revision`、`strength`（`0..1`）、`max_crop`（`0..0.25`，
`capabilities.limits.stabilize_max_crop`）、`dry_run`。MCP 的对应工具是 `clip_stabilize`。
它和 `/track`、`/reframe` 同一类：**分析需要读媒体，所以只有引擎能做；写入仍然是一条普通的
`EditBatch`**（`keyframes.replace` 的 `x`/`y`/`scale`），于是一个 revision、一份回执、一步撤销，
跟手打关键帧没有区别。回复里的 `stabilization` 是决策依据：量到的行程、抵消后还剩多少、放大多少倍
盖边、多少个轴被 `max_crop` 夹住。

测量复用 1.65 之前就在的归一化互相关跟踪器（`tracking.track_box`，`scale=False`），但锚点放在
画面自身的四角内缩处（0.27/0.73），取四个锚点位移的**中位数**：一个走过主体的锚点会被主体带跑，
而相机是四个锚点共同的那个运动。 offsets 相对第一帧，符号与画面位移一致（窗口往右裁 = 画面往左走）。

抵消的是「测到的减去平滑的」，不是「测到的减去零」。把画面钉死在第一帧不是稳定，是冻屏：镜头本来
就该走位，要摘掉的是叠在上面的抖动。平滑是居中滑动平均，窗口半径 `min(30, 片段帧数/4)`——超过
四分之一条片段的窗口会把摄影师走过的推拉也当成抖动抹掉（第一版就是 30 帧固定窗口量到 2 秒片段上，
把平移吃掉一大截）。`strength` 缩放**抵消多少**，不缩放窗口宽度：滑杆两端因此都是可解释的
（0 = 原样，1 = 全抵消），而改窗口宽度等于偷偷改「什么算 intended motion」。

边上不能露黑：合成器先按 `scale` 以画面中心缩放、再平移 `x`，所以层仍然铺满画面的条件是
`|x| ≤ (scale−1)/2`，于是缩放取 `1 + 2·最大抵消`，`max_crop` 是这个比例的上限；超出就夹住并在
`clamped_axes`/`warning` 里说明还剩多少没抵消。这条不变量由 `tests/stabilize_check.py` 直接断言
（每个写入的 `|x|` 与 `|y|` 都不超过 `(scale−1)/2`）——先前用「左边缘有多少纯黑像素」来断言，
把缩放改成 1.0 之后门禁仍然是绿的：稳定片段下面还压着别的片段，边黑被盖住了，那个检查根本不可能失败。

**关键帧密度是能力边界**：一个每帧交替的抖动，无法用 48 个点在 59 帧上抵消掉——线性插值在跳变之间
只会给出错的中间值。所以写入按「一帧一个点」，上限 `min(240, 片段关键帧预算/3)`；预算不够时才均匀
抽稀。代价随之出现：59 帧 × 3 条曲线的 `if(lt(t,…))` 表达式让 `-filter_complex` 超过 Windows
`CreateProcess` 的命令行上限（实测 WinError 206），因此 `RenderPlan.graph_argument()` 在图超过
12 KB 时改走 `-filter_complex_script filtergraph.txt`，文件仍由 `plan.text_files` 交付
（`ffmpeg_argv` 与 `frame_argv` 都走这条路；调用方必须先取 argv 再落盘，因为决定走文件的是 argv）。

拒绝都是按名字的：不在画面轨上的片段、非视频素材、`speed_percent != 100`（抖动是一帧对一帧量的，
速度一变对不上，与变速曲线同理）→ `STABILIZE_INVALID`；指向不存在的片段 → `NOT_FOUND`；
`strength`/`max_crop` 越界 → 契约层 `INVALID_REQUEST`；匹配不上的帧太少 → `STABILIZE_FAILED`；
片段已经带 `x`/`y`/`rotation`/`scale` 关键帧**而且没有稳定记录** → `STABILIZE_CONFLICT`（1.68 引入，1.69 起带记录的片段改为替换，见下）；带记录的片段改速度 → `STABILIZE_LOCKED`。
`strength=0` 不写任何关键帧（每帧一个 0 值点是往工程里倒垃圾，不是更温和的稳定），此时回复不带
revision 变化、只带测量结果。

## 1.67 画面稳定补上旋转：同一个跟踪器，刚体拟合出相机的滚动

命令与载荷不变（`clip.stabilize` 只有 `strength` 与 `max_crop`），但引擎量的不再只是平移：
四个锚点这一帧的位置与第一帧的位置做一次 Arun 刚体拟合（去质心后 `atan2(Σ p×q, Σ p·q)`），
得到的角度就是相机绕光轴的滚动，单位度、相对第一帧。取四个锚点的拟合而不是任意两点的连线，
是因为单对基线只有 ~300 px，一个像素的量化就是 0.19°，中位数与最小二乘在这里都不是装饰。

抵消仍与平移同一条规矩：`rotation` 关键帧写的是「测到的 − 平滑的」的反号，平滑窗口与 `strength`
与平移共用，所以一段边走边转的镜头不会只治一样。缩放多出一项：把 `w×h` 的图层转 θ 角后要不露边，
高度方向至少要 `1 + θ·(w/h)`（θ 用弧度），于是
`zoom = 1 + 2·最大平移 + 弧度·画幅比`，两项相加而不是取大，因为两者可以同时到最坏。

**0.25° 的死区**：低于一个像素量化（0.19°）的“滚动”是测量自己的颗粒，不是相机。第一版没有死区，
于是纯平移的样片也被写上一条旋转曲线，行程保留率从 75% 掉到 69%——死区不是把阈值调松，
而是把「这个测量分辨不出来」这件事写进代码。分辨不出来就不写，回复里的 `roll_correction`
也就是 0，界面与 Agent 都能看到「这段没有滚动」。

回复的 `stabilization` 多两个数：`measured_roll`（量到的最大相对滚动，度）与
`roll_correction`（抵消掉的旋转，度）。`capabilities` 不变（`features.clip_stabilize` 一个开关
管住平移与旋转，因为它们是同一次测量）。

验收（并入 `tests/stabilize_check.py`）：第三条样片把整块图版每帧在 ±0.5° 之间来回转，
相对第一帧的满摆幅是 2°，量到 **2.47°**（图版比画幅大 130/100 px，1° 的转动不会把旋转后露出的
黑角送进裁剪窗口——这是把图版放大到 900×560 的原因，否则量到的是黑边噪声）；写进去的
`rotation` 在最大偏转那一帧与测量反向；**导出成片再量一次，旋转抖动 1.58° → 0.17°**；
平移那条样片的行程保留率回到 75%；把旋转符号翻过来的变异红在反向断言上。

## 1.68 二次稳定点名拒绝：抵消只算一次，出路写在回复里

发现的经过是把 1.66/1.67 的两条命令串起来跑：对同一片段按两次「画面稳定」，第二次仍然 200，
工程涨一个 revision，读回来看上去一切正常——但画面向反方向偏。原因是这条命令的语义：
抵消是**叠在片段已有的 `x`/`y`/`rotation`/`scale` 上的**（这样手打的运镜不会被稳定吃掉），
而第二次测量读的还是同一段源画面，于是同一份抖动被减了两遍。

引擎没法区分「我上一次写的」和「用户手打的」——落到工程里它们就是同一种东西（关键帧），
历史快照也不是给命令当状态用的。所以 1.68 起这种输入直接 422 `STABILIZE_CONFLICT`，
`details.properties` 点名是哪几条曲线，消息里给出真正走得通的出路：撤销这一步（界面）、
`project_restore` 回到稳定前的 revision（Agent）、或在曲线编辑器里清掉那几条，然后按一次。
`STABILIZE_CONFLICT` 不是新的载荷、也不是新的开关，它只是把一个原本会静默出错的输入变成一次
命名的拒绝——功能接口 `features.clip_stabilize` 因此仍然只有一个开关。

界面按同一条判断（`desktop/src/effects.ts` 的 `stabilizeBlocked`）：曲线还没动、按钮就先灰掉，
`title` 说的是引擎会给的那句话，而不是另一套说法。同一次改动把稳定与柔焦的四种拒绝补成中文提示
（`STABILIZE_INVALID`/`STABILIZE_FAILED`/`STABILIZE_CONFLICT`/`BLUR_OUT_OF_RANGE`），
之前它们弹的是引擎原文（英文），人看着像程序内部错误。

验收分两层：`tests/stabilize_check.py` 用同一个 `request_id` 以同载荷、换载荷两种方式各撞一次，
两次都必须 422 `STABILIZE_CONFLICT`，且 revision 与该片段的关键帧列表一字不差；把守卫摘掉
（`keyed = []`）的门禁变异红在这两条断言上。`tests/desktop_stabilize_check.ts` 不问浏览器，
直接驱动 `stabilizeBlocked`：干净片段放行、变速与曲线片段各给一条带出路的说法，
而 `mask_x`/`opacity` 这类稳定根本不碰的曲线**不许**挡路（把 `STABILIZED` 里的 `scale` 删掉的
变异红在「必须点名曲线」那条断言上）。

## 1.69 稳定成为片段的状态：再按一次是换一档，不是叠一层

1.68 用一次拒绝把一个静默出错的输入挡了下来，代价是「换个强度」这件事变得要先撤销。1.69 把它变成
正常操作：`Clip.stabilization` 记下这一次运行的 `strength`/`max_crop`/`points`/
`translation_correction`/`roll_correction`/`zoom_to_hide_borders`/`analysed_frames`，写命令与
`keyframes.replace` 在同一条批次里，所以一个 revision 要么两条曲线和记录一起有、要么一起没有。

有了这条记录，引擎才分得清「这四条曲线是我上次写的」和「是用户手打的」：
- **带记录**：抵消从片段的**静态**变换（`effects.x`/`y`/`scale`/`rotation`）重算，写出来的就是
  这一次测量的结果 —— 同强度再按一遍得到逐点一字不差的曲线（回执也因此重新命中：同 id 同载荷
  命中 `replayed`，同 id 换载荷是 `IDEMPOTENCY_CONFLICT`），换强度就是换一档，强度 0 是「取消稳定」，
  把引擎写过的点连同记录一起清掉。
- **没有记录但已经K过这四条**：仍然 `STABILIZE_CONFLICT`，因为叠加会把同一段抖动抵消两遍，而引擎
  没有任何依据说那不是你打的。出路还是那三条（撤销 / `project_restore` / 清掉那几条），门禁断言
  清掉那一个手动点之后同一次按下去就成功。

带记录的片段同时不再允许改速度：`clip.speed`（非 100%）与 `clip.speed_curve` 以
`STABILIZE_LOCKED` 拒绝。理由与 1.66 拒绝给变速片段做稳定是同一条——抵消按「一帧源画面对一个关键帧」
量，速度一变就按错的速率播放。这是 1.68 那条守卫的**镜像洞**：写入时查了速度，写完之后再改速度
却没人管，同一件危险的事从另一扇门走了进来。

契约面：新命令 `clip.stabilize_record`（`record: Stabilization | None`，null 即清除）、
`Clip.stabilization` 可选字段（旧工程读进来就是 `None`，不需要迁移）、`SCHEMA_VERSION` 不动。
这条命令不需要额外授权：它能声称的只是「这四条曲线属于稳定」，而手写这四条曲线本来就已经可以。
界面：稳定过一次之后这一行写明「已稳定 · 强度 …· 抵消 …· N 个点」，按钮变成「重新稳定」，
旁边多一个「取消稳定」；`stabilizeBlocked()` 只在**没有**记录时因曲线挡路，速度那条规则仍然优先。

验收（`tests/stabilize_check.py`）：记录与曲线同 revision；1.0 再按一遍曲线逐点相同；
1.0 → 0.5 → 1.0 回到同一批数字且 0.5 恰为一半；带记录时手动K进去的 x 点被替换掉（不是叠加）；
强度 0 清掉全部 120 个点与记录、之后同一片段就能改速度；带记录时 `clip.speed` 与
`clip.speed_curve` 都是 `STABILIZE_LOCKED` 且不动 head；没有记录的手动曲线是
`STABILIZE_CONFLICT` 并点名 `x`，清掉那一个点后同一次按下去成功；同 id 同载荷命中回执。
另加一条对所有成片断言都成立的守卫：`topmost()` 断言被量的那段窗口最上面就是被测片段——1.68 加的
辅助片段压在上面的轨上，把成片抖动断言变成了对另一幅画面的测量（1.4 px 变 3.1 px 而门禁照绿），
挪开并加守卫后回到 11.2 px → **1.4 px**、滚动 0.18°。

## 1.70 稳定与重构图不能同时拥有同三条曲线

1.69 让稳定有了记录，于是能说出「这四条曲线是我的」。`clip.reframe`（主体跟随重构图）写的也正是
`x`/`y`/`scale`，而且是**整条改写**（值从跟好的遮罩路径直接算出来，不叠加）。两个功能前后跑一次，
后跑的那个会把前一个的成果静默删掉，而片段上那条稳定记录还留着——界面写着「已稳定 · 强度 100%」，
导出里却已经没有抵消了，速度锁也还在为一件不存在的事挡路。

1.70 起 `reframe_plan` 在带 `Clip.stabilization` 的片段上抛 `STABILIZE_LOCKED`（422），消息点名出路：
先取消稳定（强度 0 或 `clip.stabilize_record` 传 null），再做重构图，之后想要稳定就再按一次。
反方向不需要新代码：重构图写过的片段带着 `x`/`y`/`scale` 关键帧而**没有**稳定记录，稳定的守卫
（1.68）本来就会拒绝它。界面按同一条判断把「主体跟随重构图」灰掉，`title` 说的是引擎会给的那句话。

验收（并入 `tests/reframe_check.py`）：计划层——给一条跟好的片段挂上稳定记录，`reframe_plan` 必须以
`STABILIZE_LOCKED` 拒绝；HTTP 层——同一条命令 422 且 head 不动，把记录用 `clip.stabilize_record`
清掉之后同一次请求返回 200。两条断言在守卫落地前都是红的（先红后绿，红的那次就是缺陷的实证）。

## 1.71 记录随曲线一起作废

`Clip.stabilization` 说的是「引擎写过抵消，这四条曲线是它的」。1.70 之后它还会拦住变速与重构图，
于是它必须真话。而关键帧是可以被普通命令删掉的：`keyframes.remove`、曲线编辑器里全选删除、
`clips.add` 的粘贴丢掉某条曲线——记录不会跟着动。结果是片段上写着「已稳定 · 强度 100%」，
画面里一条抵消都没有，而改速度和重构图还在为一件不存在的事被拒。

`apply_commands` 的收尾（与路径遮罩补框、转场修复同一处）现在统一修一次：某条记录还在、
而 `x`/`y`/`rotation`/`scale` 四条曲线一条都不剩时，记录置空。只在这一种情况下动手，
所以分割（两半各自留着窗口内的曲线）与删掉个别点（还剩别的）都不会误伤——宁可留着一条不完美的
说法，也不误删一个仍然成立的成果。

验收（并入 `tests/stabilize_check.py`）：稳定过的片段用 `keyframes.remove` 把那四条曲线全部删空，
回读必须 `stabilization is null`，随后同一句 `clip.speed=200` 必须通过。这条断言在收尾落地前是红的
（`the record outlived the curves it described`），红了的那次输出就是缺陷的实证。

## 1.72 遮罩跟踪可以接着跟：一次跑不完的一段，分几次跟完

`POST /v1/projects/{id}/clips/{id}/track` 早就支持 `from_ticks`（从片段中间某帧起跟），但写入的
`clip.mask_track` 会把这条遮罩的**全部**关键帧删掉再写新的那一段。于是「跟到第 40 帧跟丢了，把遮罩
拖回主体上，从第 40 帧接着跟」这个动作，实际效果是把前 40 帧已经跟好的路径整条抹掉——遮罩在片段开头
跳回画好的位置。这是静默删数据，不是简化。

1.72 起 `MaskTrackRequest` 与 `clip.mask_track` 命令都带 `merge`（默认开）：
- **merge=true**：只重写本次分析窗口覆盖的那些 tick，窗口之外的点原样保留。遮罩的静态盒保持**整条路径
  最早那一帧**的位置（不是最后一次运行的起点），否则播放头之前的帧会退回一个刚被搬走的位置。
- **merge=false**：旧语义，整条替换 —— 界面上的「从头重跟」。

回复的 `tracking` 多了四个数：`kept_frames` / `replaced_frames`（保住与重写了几帧，按帧数而不是按曲线
数，尺寸估计开着时每帧有两条到四条曲线）、`seam_ticks`（新窗口与上一段最后 sighting 隔了几帧）、
`seam_jump`（两段在接缝处相差多少画面宽，`hypot(dx,dy)`）。接缝不为零是真实的不连续，界面把它说出来，
而不是悄悄插一条直线过去。

界面：同一个按钮在已有路径的片段上改叫「接着跟」（从播放头起，merge 开），旁边多一个「从头重跟」
（`from_ticks=0`、merge 关）；提示语里报「保住前面 N 帧的路径，只重写这一段（接缝处差 X 画面宽）」。

验收（并入 `tests/tracking_check.py`）：reducer 层——先跟 0..1 帧，再 merge 一段 1..2 帧，断言第 0 帧
那个点还在、窗口内的点被替换、`merge=false` 仍然整条替换；HTTP 层——40 帧的路径跟到第 20 帧后，
把遮罩盒挪到主体在第 20 帧的真实位置（这就是界面上「把遮罩盖住主体再点接着跟」），再 merge 跟 20 帧，
断言 40 个 tick 一个不缺、`kept_frames=20`、`replaced_frames=20`、`seam_ticks` 是一帧、
`seam_jump` 小于 0.012 画面宽，并且**全部 40 个点仍然落在解析轨迹上**（拼接没有把路径拧弯）；
`merge=false` 的那一次则只剩后 20 帧。两条断言在 merge 落地前都是红的。

## 1.73 关键帧预算按片段剩余空间算：挤满的片段也能稳，只是会说清楚

每个片段的曲线总数上限是 2000（`Clip.keyframes` 的契约长度）。重构图早就按剩余空间自适应补点
（`room = (KEYFRAME_LIMIT - len(clip.keyframes)) // 3`），稳定没有：它固定写
`min(240, 2000 // 3)` 个点。于是跟过遮罩、压过闪避、K 过淡入淡出的片段——曲线本来就多——再点一次
「画面稳定」，整批命令在落库时被契约拒绝，回的是 `PROJECT_LIMIT`「project exceeds the supported
contract limits」，`details` 是空的：不说哪条片段、不说超了多少、也不说能怎么办。实测：一条已经挂着
1950 个不透明关键帧的片段，稳定写 59+59+2 个点 → 2070 → `PROJECT_LIMIT`。

1.73 起稳定的预算与重构图同源：稳定要重写的那四条曲线（`x`/`y`/`rotation`/`scale`）上的旧点会被替换，
所以不计入占用；其余曲线计入，`scale` 那两个固定点也不参与抽稀。
`budget = max(2, min(240, (2000 - 其他曲线数 - 2) // 3))`。上一条 1950 点的片段现在写
16 点/曲线，总计 1984 < 2000，一次点击就成功。

剩下两种情况必须说话，不能沉默：
- **抽稀了**（`budget < 量到的帧数`）：`stabilization.warning` 说明「只剩 N 个点的位置、量到 M 帧，
  比一帧一个点粗，抖动会剩一些」，并给出两条出路（清掉别的曲线 / 只稳一小段）。界面提示用同样的两个
  数字自己拼中文句子，不再把英文原文塞进提示里；`clamped_axes` 那句也一并中文化。
- **真的一点位置都没有**（`available < 6`）：`STABILIZE_FAILED`，`details` 带上
  `kept_keyframes` 与 `keyframe_limit` 两个数，消息里说的是「这条片段已占 N 条曲线、上限 2000」。

验收（并入 `tests/stabilize_check.py`）：给一条干净片段先写 1950 个 `opacity` 点，再稳定 —— 必须
200，`written_points == keyframe_budget == (2000-1950)//3 == 16`，回读关键帧总数 1984 < 2000，
并且回复里带着那条抽稀警告。这条断言在预算改动前是红的，红的输出就是 `PROJECT_LIMIT` 本身。

## 1.74 九个分析入口进得了嵌套合成（工程 schema 不变）

预合成把片段搬进 `Project.sequences`，界面却把合成当时间线来显示：客户端用 `sequence_view` 投影，
普通的 `timeline_edit` 早就带着 `sequence_id`。分析类入口没有这个参数，于是合成里的片段一按就撞墙——
实测（`tests/sequence_plan_check.py` 的夹具，包内再量一次）：

| 入口 | 修之前（片段已在合成里） |
| --- | --- |
| `POST /clips/{id}/silence`、`/loudness`、`/reframe` | 404 `NOT_FOUND`「clip is not in this project」——可它就在这条工程里 |
| `POST /clips/{id}/stabilize`、`/track` | 404 `NOT_FOUND` |
| `POST /tracks/{id}/silence`、`/loudness`、`/duck` | 200 且 commands 为空：读的是根时间线上那条同名的空轨，回一句「没什么可切/可闪」 |
| 任何请求带上 `sequence_id` | 422 `INVALID_REQUEST`（契约 `extra=forbid`，字段根本不存在） |

1.74 起七个请求契约（`ReframeRequest`/`SilenceRequest`/`LoudnessRequest`/`DuckRequest`/
`MaskTrackRequest`/`ClipStabilizeRequest`/`SpeechCaptionsRequest`，共九条路由）都带
`sequence_id: Identifier | None = None`：路由用 reducer 已有的同一个 `sequence_view` 投影来解析
clip/track id（不另写一套读取规则），派生的批次也一并盖上 `sequence_id`，所以「分析 → 写入」仍是一条
事务、一个 revision；回复里的 `project` 依旧是根工程，客户端自己按当前视图投影。可选字段带默认值，
旧请求与旧回执一字不改（`_fingerprint` 早就把 `None` 的 `sequence_id` 剥掉）。

验收量的是「同一个片段在两头得到同一个答案」，而不只是 200：
- 同一条遮罩路径，先在根时间线上出计划（39 个点），嵌套之后再在合成里执行，落库的 `x`/`y`/`scale`
  与那批计划**逐点相同**，而合成外面那条容器片段一条关键帧都没多；
- 合成里那条 1 秒抖动样片被稳定写上 **29 点/曲线**（量到 30 帧），遮罩跟踪写进合成内部的片段
  （10 个点），去空白从合成自己的片段里切掉 **0.77 秒**、片段数从 4 变 5，统一响度把 **2.2387** 倍增益
  落在里面的片段上，整轨去空白读到合成轨上那 1 条片段同样切掉 0.77 秒（根上这条轨是空的），
  自动闪避按合成里的口播给出 **2** 段语音、在配乐上写 **8** 个音量关键帧；
- 拒绝仍然诚实：嵌套之后在根时间线上问同一条片段，回的还是 404；
- `dry_run` 不留痕（revision 不动），而且**不产生回执**——同一个 request_id 再问一次就再计划一次；
  真实提交的那次按客户端重放的方式（带着它读过的那个 revision）再发一次，命中回执、revision 不变，
  不会把合成的响度压两遍；
- `tests/self_check.py` 另外断言 MCP 的六个工具 schema 里都有 `sequence_id`——Agent 读的就是这份 schema。

补测的一条（`tests/captions_comp_check.py`，真实音频 + 真实导出）：自动字幕（`/speech-captions`）在合成里的听写
不再靠「改动与其他八条逐字相同」推断。同一段 Windows 语音合成的中文两句（7.769 秒，中间 1 秒静音）配一张
0x404040 灰底画面，先在外层时间线听出 **2** 条cue（`大家好欢迎来到剪辑教学` / `今天我们学习自动侧目`），再把
两条片段 `sequence.nest` 进合成 `s1`：外层问同一条片段回 404 且点名 `clip_id=c`（空的同名轨点名 `track_id=a1`，
不存在的合成点名 `sequence_id=nope`）；带 `sequence_id=s1` 再问，听出的 cue 与外层**逐字逐 tick 相同**，
内容寻址的 `subt-…` 轨 id 也相同；dry run 在合成的投影里预览到那 2 条字幕片段、库里仍是 revision 2；
apply 之后 revision 3，字幕轨与 cue 片段只出现在 `sequences[s1]` 里，外层依旧只有容器片段 `cn`；
换 request_id 重跑（含 dry run）撞 `DUPLICATE_ID`；`replace_track_id` 在合成里原位重生成同 id 同条数（revision 4）。
最后导出外层时间线：`comp-captions.mp4` 复检通过（10 秒 / h264+aac），两条字幕各自的中间帧量到 55 与 30 个
>200 的亮像素（>235 为 11 与 3），而前导、两条之间的那 1 秒空隙与结尾三处都是 0——灰底本身一个亮像素都没有，
所以这些字只可能来自合成里那条字幕轨。

## 1.75 每一条分析拒绝都点名它说的是谁

1.74 让九个分析入口能进嵌套合成，同时也开出了新的拒绝形状：合成不存在、id 在另一条时间线上、
窗口越过片段末尾、driver 指向自己。这些拒绝里有一批是 `{"code": "...", "message": "...",
"details": {}}`——错误码有了，可「哪一条？」没人说。实测（`tests/analysis_sweep_check.py` 的夹具，
改动前先跑一遍记录现状）：

- `/clips/{id}/silence`、`/clips/{id}/loudness` 对不在根时间线上的片段回 404，`details` 是空的；
- `sequence_view` 对不存在的合成回 404「sequence does not exist」，不说是哪个 `sequence_id`
  （这条不只影响分析入口，`timeline_edit` 走的是同一个函数）；
- `/clips/{id}/track` 跟不到东西时回 422 `TRACK_FAILED`「too few frames matched to track」，
  不说量到了几帧、也不说是哪条片段；
- 素材文件被挪走之后（真实场景：移动素材夹），八处 `MEDIA_MISSING`「source file is gone」全部
  `details:{}`——四十个素材的工程里没人知道该去找哪一个。

1.75 起这些拒绝都带着目标：`clip_id` / `track_id` / `asset_id` / `sequence_id`，`TRACK_FAILED` 另带
`matched` 与 `frames` 两个数，`MEDIA_MISSING` 同时给 `clip_id`、`asset_id` 与 `asset_label`（就是文件
名——四十个素材的工程里，能认出来的只有名字）。改的是错误负载，不是
判断：没有任何一条拒绝的条件被放宽或收紧，`details` 也只是 `EditorError` 已有的第四个参数，因此契约、
reducer、回执都不动。

新门禁把这件事钉住（九条路由 × 各自的边界形状，47 条拒绝）：不 5xx；每条拒绝有 code、有能读的句子、
`details` 非空；`NOT_FOUND` 必须点出一个 id；拒绝绝不抬 revision；同一个问题 dry 与真实提交答案一致
——唯一允许的差别是「空计划」：`apply=false` 看着是 200，`apply=true` 时按名字说「没什么可做」
（`INVALID_SILENCE_TARGET` / `INVALID_LOUDNESS_TARGET` / `INVALID_DUCK`），因为提交一条空批次没有意义。
再把样片从磁盘上删掉重问三次：三条路由都回 410 并点名打不开的片段与素材。

界面这一侧同时补了两件事：`EngineError.explain()` 现在把 `details` 里的名字织进中文提示
（「素材原文件已被移动或删除，请重新导入。（素材 tone.mp4、片段 s）」），没有名字时不加空括号；原先
**根本没有中文说明**的 11 个分析错误码（`NOT_FOUND`、`INVALID_SILENCE_TARGET`、
`INVALID_LOUDNESS_TARGET`、`INVALID_REFRAME`、`INVALID_DUCK`、`DUCK_PLAN_TOO_LARGE`、
`INVALID_TRACK_TARGET`、`TRACK_FAILED`、`INVALID_SPEED`、`PROJECT_LIMIT`、`TIME_OVERFLOW`）各补一句
能照着做的中文——在此之前按「去空白」「自动闪避」「主体跟随」被拒时，提示里就是引擎那句英文。
`tests/desktop_error_naming_check.ts` 逐条钉住。

## 1.76 读不存在的 id 也要说清楚是哪个（工程 schema 不变）

1.75 把「拒绝点名」做到了九个分析入口，`GET` 一侧还是老样子。实测（`tests/read_sweep_check.py`
先记录现状）：13 条读路由对不存在的 id 回 `{"code":"NOT_FOUND","message":"...","details":{}}`——
调用方刚把 id 传进去，日志里却看不出是哪一次查找失败；更不一致的是
`GET /v1/projects/{unknown}/jobs` 回 **200 + 空列表**，一个打错字的工程 id 看起来就跟「这个工程还
没导出过」一模一样，而旁边的 `history` 回的是 404。

1.76 起三处集中修：`ProjectStore._load` 的 404 带 `project_id` 与 `revision`（覆盖工程、历史、字幕、
素材清单、预览清单、渲染计划、取帧这一整批路由），`MediaService.get_probe` 的两条带 `probe_id`，
字幕导出与片段取样的 404 带 `track_id` / `clip_id`；`/projects/{id}/jobs` 改为先读工程，未知工程与
其它读路由一样回 404。判断没有变化，只是把已经传进来的 id 放回 `details`。

门禁钉三件事：15 条「读不存在的东西」每条都点名它给的那个 id（project / probe / clip / track /
asset / sequence 六种都覆盖到）；素材文件被挪走后 410 说得出是哪个 `probe_id`；七条正常读
（工程、历史、素材清单、任务列表、字幕、探测记录、预览清单）仍然 200——补 details 不能把能用的读
变成新的拒绝。

## 1.77 操作类路由的拒绝也说清楚（工程 schema 不变）

同一把尺子量剩下的面：导入素材、缓存清理、恢复历史、任务与 `.cube` 解析。实测（先把现状记下来再动手）：
`POST /v1/media/import` 的四条失败——文件不存在、路径不是绝对路径、在允许的素材夹之外、扩展名不认识
——`details` 全是 `{}`；`POST /v1/lut/parse` 的 `INVALID_LUT` 同样空着，句子写了「读不出这一行」却不说是
第几行，用户手里那份 `.cube` 只能从头翻。

1.77 起：`MEDIA_NOT_FOUND` / `MEDIA_EMPTY` / `MEDIA_PATH_INVALID` 带 `path`（就是调用方自己给的那串），
`MEDIA_TYPE_UNSUPPORTED` 带 `path` 与 `suffix`，越界那条继续带 `media_roots`（配上 `path` 才知道差在哪），
`INVALID_LUT` 带 `line`（解析循环里的行号）与 `size` / `rows`（行数对不上时给两个数）。判断一字未动，
`EditorError` 的 `**details` 本来就在。

`tests/ops_sweep_check.py`：11 条操作类拒绝每条都要有 code、句子与目标（path / suffix / media_roots /
line / size+rows / project_id / revision / job_id 都覆盖到），九条正常调用（媒体配置、探测列表、缓存
状态、两种 prune、导出根、ids、`.cube` 正常解析、工程打包、字幕读回）必须仍 200。变异测试四条红：
把 `path=str(real)`、re-raise 里的 `path`+`suffix`、`line=number`、`size`/`rows` 任一个剥掉，门禁当场红。

## 1.78 片段降噪：一个旋钮，只在导出里生效

`ClipEffects.denoise`（0–24 dB，默认 0）是又一个「可 patch、不可打关键帧」的效果键，与
`blur`/`sharpen` 同一族：导出侧在每条片段的音频链上、增益之前插一级
`afftdn=nr=<db>:nf=-30.0`；`nf` 固定而不是用 FFmpeg 默认的 −50 dB——实测在「440 Hz 音 + 白噪声」
的样片上，默认噪声底只让这个旋钮压掉 0.5 dB（等于挂个假旋钮），钉到 −30 dBFS 才做到 8.9 dB。
`capabilities` 下发 `features.clip_denoise` 与 `limits.denoise_db = 24.0`，界面滑杆的上限就取自这里。

浏览器预览不做降噪（没有等价的 FFT 降噪可跑），所以这一级与母带限制器同等待遇：**只在导出里生效，
界面必须说出来**——滑杆后面写着「dB · 只在导出里生效，浏览器预览不降噪」，帮助里单列一条。

验收 `tests/denoise_check.py` 量的就是那句承诺：同一条时间线渲染三次，只差旋钮，
6 kHz 噪声带 −50.0 → −58.8 → −61.0 dBFS（0 / 12 / 24），440 Hz 音最多动 0.06 dB；
旋钮回 0 时编译出的滤镜图里一个 `afftdn` 都没有；超上限 422 `INVALID_REQUEST`；
`keyframe.set` 想给 `denoise` 打关键帧被拒。

## 1.79 Agent 补齐三条音量入口，空轨道与静音片段改为点名拒绝

- 一条真正的入口不对称（不是新能力）：`/clips/{c}/loudness`、`/tracks/{t}/loudness`、
  `/tracks/{t}/silence` 有 HTTP 路由、有界面按钮、capabilities 也声明可用，MCP 里却没有工具——
  Agent 能对齐母带（`master_loudness`）、能扫一条片段的停顿（`clip_silence`），就是不能量片段响度、
  不能整轨对齐、不能整轨去空白。AGENTS.md 要求「所有入口使用同一命令语义」，所以工具是薄封装：
  `clip_loudness` / `track_loudness` / `track_silence` 三个新工具与 `clip_silence` 同规格，
  `apply`/`dry_run` 在工具侧固定 false，把计划里的普通命令交回 `timeline_edit` 写入；schema 由
  契约生成（`LoudnessRequest`/`SilenceRequest` 已带 `sequence_id`），适配层没有第二条规则。
  工具集合 40 → 43，`tests/self_check.py` 那句 `assert set(tools) == expected` 是唯一权威清单。
- Agent 路径实测（真实音频、只走 MCP stdio）：5 % 的 440 Hz 音量到 **−47.8 LUFS**，计划给
  `gain=4.0` + `limited_by="gain_range"`——撞到 `MAX_GAIN` 就说撞到上限，不假装到了 −16；
  满幅那条量到 **−22.2 LUFS**，`gain≈2.04`、`reaches_target=true`、预测 −16.0。整轨对齐回
  `measured=1 / changed=1`，把返回命令经 `timeline_edit` 提交正好一个 revision，落库 `gain` 与计划
  逐字相等；再扫一次 `changed=0`。整轨去空白对 1 秒门控静音回 `removed_ticks`≈1.0 秒，剪后同轨
  片段合起来 3.0 秒。工具侧强制只读：请求里写 `apply=true` 也拿不到写入（`committed=false`、
  revision 不动）。带 `sequence_id` 的整轨对齐把增益写进合成里的片段，外层容器片段一条不动。
- 拒绝一致性（`tests/empty_track_check.py`，1.1 秒，不渲染）：四条整轨路由（含自动字幕）现在对
  「存在但没有片段的轨道」一律 404 `this track holds no clips` + `track_id`，对「根本不存在的轨道」
  一律 404 `track is not in this project` + `track_id`。此前只有自动字幕有这句（它还没有存在性检查，
  把两种情况混成一句），另外三条对空轨回 200 `measured=0`，`apply=true` 时更糟——回
  「已经对齐了」，而那条轨上一个片段都没有。片段进合成之后，外层那条同名空轨就是这个场景。
- 一条被控件自己掩住的 5xx：纯静音片段点「统一响度」以前回 **502 `LOUDNESS_FAILED`** 且
  `details={}`。原因在 FFmpeg 对数字静音打印 `Peak: -inf dBFS`，`loudness.py` 的浮点正则匹配不了
  `-inf`，于是「读不出」被当成引擎故障。现在 `-inf` 可解析，且积分响度不高于 `SILENCE_FLOOR = -70.0`
  （ebur128 对静音的门限值）时按 422 点名拒绝：`this audio is digital silence, so there is no loudness
  to match`，`details` 带 `path`，路由再把 `clip_id` / `asset_id` / `asset_label` 补上——
  一处测量、一处点名，不在路由里重写判断。`-inf` 不进 JSON，所以拒绝负载里只给文件与片段，不给
  那个无穷大读数。
- 顺带点名：模型目录缺失时 `SUBTITLES_MODEL_MISSING` 现在带 `language`、`expected_model`、
  `searched_dirs`（真正搜过的那几个目录）、`installed_languages`。
- 界面不需要新代码：1.75 起的中文提示里 `NOT_FOUND` 那句话本来就写着「片段或轨道可能在另一个合成里
  （从时间线上方的面包屑进去再操作）」，而 `explain()` 会把 `track_id` 织到句子后面；帮助新增
  「Agent·音量与去空白」一条。契约、reducer、capabilities、工程 schema 都不动（没有新命令、没有新字段）。
- 整轨的一侧还有一个真实的连带缺陷：路由的 docstring 早就写着「量不了的片段会被记成 skipped 并说明
  原因」，但实现里测量一失败就整批拒绝——一条纯静音的片段能让整条轨的对齐按钮报错。现在测量返回的 422
  按 `skipped` 记录并继续，其余片段照样拿到建议增益（5xx 与素材丢失仍照原样上抛，那是另一回事）；单片段
  路由点名拒绝不变，因为用户问的就是那一段。实测：一条轨上并排放「能量的」与「纯静音的」两个片段，
  `measured=1 / changed=1`，命令里只有前者，`clips` 里那条带着「digital silence」的原因。
- 变异测试十条红，且每条红在该红的断言上：三条路由的空轨守卫逐个删掉 → 各自的空轨用例回到
  200 `measured=0`；删掉自动字幕的存在性检查 → 「不存在的轨道」被说成「没有片段」；只删那条拒绝里的
  `track_id` → `details == {}`；把峰值正则的 `-inf` 分支去掉 → 502 重现；从静音拒绝里删掉 `path` →
  `KeyError`；把路由的点名包装换成裸 `raise` → `clip_id` 消失；删掉 `SUBTITLES_MODEL_MISSING` 的新
  details → `language` 消失；把整轨的 `skipped` 分支换成裸 `raise` → 一条静音片段又能拖垮整轨，红在
  那句 `status == 200`。全部还原后 `git status src` 只剩本轮该改的文件。


## 1.80 Agent 看得见成片画面，也管得动派生缓存

- 还是那句尺子：人有按钮、Agent 够不着，就是缺陷。`GET /v1/projects/{id}/frame` 是界面预览每一帧的
  来源，Agent 侧却一个工具都没有——它能写关键帧、遮罩、调色，却没有任何办法确认画面真的动了；
  `/v1/media/cache` 与两个 prune 也一样，缓存配额是 1.44 就交付的能力，界面有「清理缓存」按钮，
  Agent 连读都读不到。
- 新增四个工具：`preview_frame`（只读）、`media_cache_read`（只读）、`media_cache_prune`、
  `media_proxies_prune`。工具集合 43 → 47，`tests/self_check.py` 的精确相等断言继续把关。适配层
  仍不写规则：帧字节来自 `MediaService.render_frame`，也就是导出用的那条编译链，不是第二套预览。
- 为什么值得给 Agent 一帧：`tests/self_check.py` 的 `frame_through_mcp` 量的不是「有没有图」，
  而是三条可判定的事实。① 同一帧取两次必须一模一样——请求 `TIMEBASE/2 + 1` 时引擎报回
  `at_ticks = 35,280,000`（正是 0.5 秒那一帧）且 sha256 与上一张逐字节相同；② 把片段横向 `x=0.4`
  之后，同一个 tick 的哈希必须变（没变就说明这次编辑在画面上是空的）；③ 片段进合成之后，
  在合成里取的帧与在外层看容器的帧是同一幅画（哈希相等），清完派生缓存再取还是同一幅画。
- 实测的形状写进 docstring，不让人猜：320×180 的工程，回的是 **256×144** PNG（长边 256 的传输上限，
  宽高比严格保持），`bytes` 14,455，`revision` 就是渲染那一次的 revision。
- 缓存一侧钉的是「dry run 不删、真删能回来」：`media_cache_read` 的 `used_bytes` 与 prune 报的
  `used_bytes_before` 相等；`dry_run=true` 之后库里的字节数不减（`>=`，因为同进程其它请求可能新增），
  真删之后 `used_bytes <= before - freed`，且随后那一帧的哈希与删之前一致——派生数据删得掉也长得回来。
- 界面零改动（帮助新增「Agent·看得见画面」一条）。契约、reducer、capabilities、工程 schema 不动。

## 1.81 每一条引擎拒绝都有中文说法（缺一条就红）

- 界面上按的是中文按钮，弹出来的却是英文原句——这是交付缺陷，不是翻译问题。`EngineError.explain()`
  在没有提示时会 `return this.message`，也就是把引擎写给开发者看的那句话直接端给用户。把两边的词表
  对起来量：`src/agentcut/*.py` 里能报出的码 **116** 个，`desktop/src/engine.ts` 的提示表只有 60 个
  key，**58 个码没人管**（`INVALID_SPLIT`、`NOT_ADJACENT`、`DUPLICATE_ID`、`REVISION_OVERFLOW`、
  `OUTPUT_INVALID`、`SPEECH_NOT_FOUND`、`SUBTITLES_MODEL_MISSING`、`FONT_UNAVAILABLE`、
  `MEDIA_PATH_INVALID`…），全是点得到、报得出的路径。
- 逐条补成「发生了什么 + 下一步怎么办」的中文句子，并且给出路（例如 `INVALID_REFRAME` 说要先画遮罩
  再按跟踪主体、`SUBTITLES_MODEL_MISSING` 说模型放哪儿、`OUTPUT_INVALID` 说候选文件已销毁、最终名
  一次都没出现）。现在 116 个码 / 120 条提示、0 条落到英文；多出的 4 个 key 是适配层与任务运行器的
  码（`FFMPEG_FAILED`/`INTERRUPTED`/`NO_OUTPUT`/`STALE_REVISION`），门禁按白名单承认它们。
- 新门禁 `tests/error_vocabulary_check.py`（不到 1 秒，不碰媒体）把这件事变成永久约束：从 Python 侧
  扫 `EditorError("CODE"…` / `code="CODE"` / `"code": "CODE"`，从 TypeScript 侧扫提示表的 key，断言
  前者是后者子集；同时要求每条提示含中文、长度 ≥ 12 字（挡住「知道了」这种废话），并断言 key 不重复。
  `tests/desktop_error_naming_check.ts` 另抽 14 个码走 `explain()` 真跑，确认运行时确实说中文、
  并且把引擎点名的素材/片段/轨道织进句子。
- 五条变异测试逐条红：删掉一条提示 → 「fall through to English」点名 `OUTPUT_INVALID`；把提示写成
  英文 → 「not Chinese」；缩成「导出失败了。」→ 「too thin」；把同一条 key 写两遍 → 「duplicate
  keys」；在 Python 里新增一个没人翻译的码 → 红在 `INVALID_CAPTIONS_TARGETX` 上。也就是说这条约束
  两头都钉得住：漏了界面红，漏了引擎也红。
- 契约、reducer、capabilities、工程 schema 与所有错误码本身一字不动——改的只是界面怎么说人话。


## 1.82 空轨上的整轨按钮不再可点

- 1.79 把「这条轨上没有片段」变成了四条整轨路由统一的拒绝，这是对的；但界面上那三个按钮照旧可点，
  于是人要先按一次、看到弹错，才知道这条轨是空的。按了只会弹错的按钮不该亮着。
- `desktop/src/effects.ts` 里加了 `trackToolBlocker(trackId, clips)` 与它的原因句
  `EMPTY_TRACK_HINT`（「先把素材拖上时间线；如果片段都进了预合成，从面包屑进去那条合成再操作」——
  两条出路都是真的能走通的），`Timeline.tsx` 的整轨响度、整轨去空白、自动闪避三个按钮统一用它：
  灰化 `disabled={!!emptyTrack}`，`title` 就是那句原因。规则只有一处，界面不另写一份判断。
- 门禁两头都钉：`tests/desktop_track_gate_check.ts` 测函数本身（空轨挡、有一条就放行、**别轨的片段
  不算数**——正是嵌套之后外层那条同名空轨的形状、混合情况不被别轨否决）与提示句里必须出现的两个出路；
  `tests/empty_track_check.py` 读 `Timeline.tsx` 断言接线（调用谓词一次、`disabled={!!emptyTrack}`
  恰好三处、`: EMPTY_TRACK_HINT` 恰好三处、不留 `disabled={!clips.length}` 这种会漂移的第二份规则）。
- 五条变异测试逐条红：谓词恒返回 null、把 `clip.track_id` 比成 `clip.id`、`some` 改成 `every`、
  提示句去掉「面包屑」这条出路、表头不走谓词写死成 null。前四条红在 TS 门禁，第五条红在 Python 门禁。
- 引擎侧一字未动：路由、契约、reducer、capabilities 与 1.79 的拒绝完全照旧。

## 1.83 色阶节点与自动调色：把「一键拉开层次」接进同一条链（工程 schema 仍是 v13）

新增一个调色节点 `levels`：`channel`（`rgb` / `red` / `green` / `blue`）、`black`、`white`（输入量程
的两个点，0..1，`white` 必须高于 `black`；可填范围由 `capabilities.grade_limits.levels_*` 下发）、
`gamma`（0.1–10）。它仍然只是每通道一条函数，所以整条链照旧塌成每通道一张表：`grade_filter` 出
FFmpeg 的 `lutrgb`，`grade_tables` 出浏览器 `feComponentTransfer` 的 256 项表，两者从同一条折线采样。
两个输入点被加进采样网格（`_curve_knots`），否则一条陡拉伸会在拐点之间被弦裁成另一条线。写入
不需要新命令——用的就是既有的 `clip.grade`，所以 reducer、历史、回执与撤销全都照旧。

新端点 `POST /v1/projects/{id}/clips/{clip}/auto-grade`，载荷 `AutoGradeRequest`：`request_id`、
`expected_revision`、`sequence_id`、`percentile`（0–0.10，默认 0.005）、`samples`（1–24，默认 12）、
`mode`（`luma` / `rgb`）、`replace`、`apply`、`dry_run`。MCP 的对应工具是 `clip_auto_grade`
（`annotations=write`）。它和 `/stabilize`、`/reframe` 是同一类：**读画面只有引擎能做，写入仍然是
一条普通批次**，于是一个 revision、一份回执、一步撤销，`dry_run` 什么都不留，`apply=false` 只把
命令交回来看。

测量在 `autograde.py`：用同一支 FFmpeg 把**片段真正播掉的那段源**解成不超过 `samples` 帧、宽 256 的
rgb24（区间长度取自 `speed.consumed_source_ticks(clip, frame_ticks)`，与渲染器、时间线同一个权威：
200% 的片段读两秒源，100% 的读一秒，变速曲线也算得出来），
按 BT.601 权重算亮度直方图，取「两端各只有 `percentile` 份额像素落在其外」的那两个级。为什么用
百分位而不是 min/max：一个镜面高光或一个坏点就能把白点定在 255，于是整张画面被压扁——剪映、
达芬奇和 Photoshop 的一键拉伸同样是百分位拉伸。`frames`、`pixels`、`skipped_pixels`、分析尺寸与
逐通道量到的两个数都进回复，人和 Agent 都看得到依据，不是只看一个结果。

拒绝全部点名（1.75 的规矩：每条带 code、可读句子与非空 details，拒绝不涨 revision）：
`AUTO_GRADE_INVALID`（音频、文字层，或停在非画面轨上的视频——量不到帧，也渲染不出帧）、
`AUTO_GRADE_FAILED`（一帧都解不出来，例如源文件被替换）、`AUTO_GRADE_NO_RANGE`（量到的两点相距
不足 16 级，details 把 low/high 报给你）、`AUTO_GRADE_CONFLICT`（`replace=false` 而链上已有色阶节点，
positions 指出是哪几个）、`AUTO_GRADE_LIMIT`（加上这几支超过 `grade_limits.max_nodes`，并说明改用
luma 只占一个节点）。画面本来就占满所测量程时**不写节点**：`commands` 为空、revision 不变，
只把量到的数交回来——这一条与 1.69 的「稳定强度 0 就是取消」同一个形状。

单帧素材（一张图片）在这里是个真坑：`fps` 滤镜喂给它会把那唯一一帧直接丢掉，量到 0 帧。
`decode_rgb` 因此带一个 `spread` 开关，取不到帧时按「不做时间铺开」再解一次；
`tests/autograde_check.py` 用真实的 FFmpeg 把这条路钉住。

## 1.84 通道混合节点：链子的权威从「每通道一张表」变成「有序阶段列表」（工程 schema 仍是 v13）

新增节点 `matrix`：`coefficients` 是九个系数、行主序（输出红/绿/蓝各一行，每行「来自红、来自绿、来自蓝」），
范围 `[-capabilities.grade_limits.matrix_limit, +limit]`（默认 4），外加 `enabled` 与 `mix`。**没有**
`blend` 字段，也**没有**常量偏移：前者是因为矩阵与非线性混合模式的复合不再是矩阵（两端就没有同一份数可
读），后者是因为 FFmpeg 那一侧的 `colorchannelmixer` 表达不了偏移。`extra="forbid"` 会把带 `blend` 的请求
当场拒掉，界面把这句话写在强度上方而不是给一个灰掉的选择器。

写入仍然只用既有的 `clip.grade`，所以 reducer、历史、幂等回执、撤销照旧；能力开关是
`features.grade_matrix`，系数范围由 `capabilities.grade_limits.matrix_limit` 下发。

编译的产物形状变了：`grade_stages(color)` 返回有序阶段列表——**连续**的每通道节点合并成一段
`{"type":"lut", r/g/b 折线}`，跨通道节点断开这一组并插入 `{"type":"matrix","m":[九个系数]}`。
`grade_filter` 依次拼成 `lutrgb=…,colorchannelmixer=…,lutrgb=…`；`grade_tables` 返回
`{"id": "g<hash>", "stages": [{"type":"lut","id":"l…","r","g","b"} | {"type":"matrix","id":"m…","m"}]}`，
`preview_manifest` 的 `clips[*]["grade"]` 就是这份列表，`color_filter` 引用的仍是整条链的一个 id。
浏览器在同一个 `<filter color-interpolation-filters="sRGB">` 里按同一顺序摆 `feComponentTransfer` 与
`feColorMatrix`（后者要 20 个数，由 `feColorMatrixValues` 把 3×3 行主序摆成每行补两个 0、alpha 原样通过）。

两端可比的原因是它们做的是同一件事：`colorchannelmixer` 与 `feColorMatrix type="matrix"` 都是对存储的
8 位值做同一个仿射映射，且 sRGB 插值声明挡住了浏览器的线性化。强度不额外花钱：
`out = in + mix·(M·in − in)` 仍是矩阵（`I + mix·(M − I)`），所以 `mix` 折进同一份九个数。

它**不是**色彩管理：基色转换发生在线性光里，8 位阶段会在暗部留下断层。`features.color_space_transform`
的含义不变（`transfer` 节点仍然只换传递函数）。仍缺的是 3D LUT（浏览器没有对应的跨通道原语）与线性光的
高位深阶段对。

并联分支**不能**装这个节点：`GradeBranch` 里没有 `matrix`。并联的输出是各支的平均，把跨通道映射平摊进
一张每通道的表里就是骗人，而让编译器在分支求值路上撞见一个没有映射的节点更是 500 —— 所以这条路在契约
上就不存在，请求会 422 并点名 `branches`。

## 1.85 遮挡久了不再是跟丢：被挡住的那段时间，每一帧都在整幅画面里重新找（工程 schema 仍是 v13）

`POST /v1/projects/{id}/clips/{id}/track` 与 MCP 的 `clip_track` 新增 `reacquire`（默认真），`max_gap_frames`
的默认从 30 提到 60、上限 240，两个数字都由 `capabilities.limits.track_gap_default` /
`track_max_gap_frames` 下发，界面与 Agent 不自己数一遍。回复多出四个数：`reacquire`（这次开没开）、
`reacquired_frames`、`reacquired_at_ticks`（在第几帧找回，已按 `from_ticks` 平移成片段本地刻度）、
`gap_closure`（被挡住那一段的猜测最后被挪了多少个画面宽，取窗口内最大值）。

算法只多了一步，判据一个都没换：正常帧走的还是「以模板做归一化互相关、按最近若干帧的置信度打折定
门槛」那一条；只有当**已经处于遮挡窗口内**且局部搜索没够到门槛时，才把这一帧和 frame 0 的锚点模板各
按 4 倍盒式平均缩小，在小图上把**整幅画面**扫一遍（门禁那条素材的模板是 34×34：全图逐窗是
(256−34+1)×(144−34+1) = 223×111 个窗、每窗 1156 像素，共 2860 万次乘法；缩成 64×36 后是 (64−8+1)×(36−8+1)
= 57×29 个窗、每窗 64 像素，共 10.6 万次——少 270 倍，而且只在被挡住的帧上跑），拿小图的胜出位置当猜
测点，回到全分辨率用同一个模板、同一个门槛再判一次；过了才算找回。所以决定「是不是它」的永远是原来
那把尺子，小图只负责提出去哪儿看。找回之后速度置零——一次跨过大半个画面的移动不该被当成相机平移继续
外推。

找回一次就把那一段猜测落地：窗口内每个猜测点按「离找回点越近挪得越多」线性挪动，终点正好落在真实看
到的那个位置，起点仍贴着最后一次真实看到的位置。`gap_closure` 报的就是这次挪动的最大值——它是「这段
路我们其实在猜」的量化证据，不是装饰：实测 42 帧遮挡 + 期间横移 48 px 的素材，找回时把匀速外推的那
一段最多挪了 0.199 个画面宽。

画面稳定明确**不**走这一步：`stabilize.py` 给四个锚点调 `track_box(..., reacquire=False, max_gap=30)`。
锚点是画面上一块固定的地方，不是物体——允许它跳到「画面里另一处很像的地方」，等于把一次剪辑硬读成相
机移动了两百个像素。这既是一条注释，也是 `tests/tracking_check.py` 的一行断言。

门禁的关键是那条对照：同一条素材、同一个 `max_gap_frames=60`，只把 `reacquire` 关掉，跟踪就停在第 30
帧、如实报 1.00 秒跟丢；开着就 90 帧全部量到、2.40 秒找回。差别只能来自那一次整幅画面的扫描，而不是
更宽的猜窗。另外两条断言管住这把尺子的两面：一个**同样大小**的方块在别处出现会被认出来（离中心 0.40 px）
并如实报 `reacquired_frames=1`——这本来就不该骗人，画面里有两个一样的东西时机器分不开；一个大三倍的平
对方块不会被跟（仍在 1.50 秒报跟丢、只有 45 帧量到），证明这一步跟的是模板的形状而不是「任何亮东西」。
`max_gap_frames` 越过 240 由契约当场 422，revision 不动。

## 1.86 分析的步长 = 播放的步长：变速片段量的就是你看到的那些帧（工程 schema 仍是 v13）

新函数 `speed.analysis_rate(rate, speed_percent)` 是这件事唯一的好说法：一段 200 % 的片段每秒时间线花掉
两秒源片，所以要「看到多少就量多少」，采样率就得是 `rate / speed`。返回约过整数比（30 fps 在 200 % 下是
`15/1`，在 50 % 下是 `60/1`，400 % 是 `15/2`），两个分析入口都用它：
`decode_luma(..., speed_percent=100)` 把 `fps=` 换成这个比值，并把 `-t` 一并放大成 `duration × speed`
（否则读进来的源只够时间线的前一半）。`track_mask` 与 `stabilize.measure` 各自收一个 `speed_percent`，
路由传的都是 `clip.speed_percent`。

回复多了两个可核对的数：遮罩跟踪的 `tracking.speed_percent` / `tracking.sample_rate`，画面稳定的
`stabilization.speed_percent` / `stabilization.sample_rate`。它们在说同一件事——这次量的是哪些帧。

**画面稳定从此接受恒定速率的片段。** 之前 `POST /clips/{id}/stabilize` 对 `speed_percent != 100` 回
`STABILIZE_INVALID`，理由写得很老实（「抖动是按一帧对一帧量的，播放速度变了就对不上」），那是当时的事实。
采样步长修对之后这句话不再成立，所以拒绝删掉、界面的 `stabilizeBlocked` 同步删掉同一半句（引擎与界面必须
守同一条判断，否则按下去拿到的是另一套说法），带**变速曲线**的仍然拒绝：速率一直在变，就没有那一个步长。

`tests/tracking_check.py` 用同一条素材把两种步长摆在一起比：200 % 的片段跟 45 帧，落库的每条 `mask_x`
与「时间线在那一刻播的那个源帧」上的物体位置差 ≤1.14 px，而与「源片自己顺序播放」的位置差 78 px；50 % 的
片段同样两条各自成立（1.56 px 对 27 px）。`tests/stabilize_check.py` 在同一块按公式写的抖动素材上量四个
锚点：200 % 时最差 2.05 px（0.8 个分析像素，与该门禁给 100 % 用的同一条容差），按源片步长比对则差 28.8 px
——所以这条断言不是在说「量到了个差不多的数」，而是在说「量的是这一批帧，不是那一批」。两个门禁都留了
反面陪衬（foil），因为只比对的假说能过、只比对错的假说过不了，才叫量对了。

界面这一侧的判断只剩一条：`stabilizeBlocked` 现在只挡**带变速曲线的**片段，说法里给了出路（改成恒定速率，
例如 100 %）；`tests/desktop_stabilize_check.ts` 把两面都钉住——200 % 必须放行（`null`），带曲线且片段已经
带着自己的稳定记录时，曲线这条规则必须赢过所有权。

已知边界，不粉饰：400 % 在同一条抖动素材上最差 17.29 px（6.9 个分析像素）。原因是这份夹具的色块周期是
24 px，而 400 % 下相邻两帧之间画面已经走了十几像素，接近一个色块，锚点偶尔会认错隔壁那块——这是内容对
采样密度的限制，不是步长算错（步长再快也不会算出别的数），所以 `sample_rate` 如实写着 `15/2`，让人和
Agent 都能看出量得稀。

## 1.87 跟踪的两个旋钮交到人的手上（引擎一字未动）

`max_gap_frames` 与 `reacquire` 从 1.72 / 1.85 起就是 Agent 能传的参数，人却没有地方传：界面上「跟踪主体」
只有一个按钮。这一版把那两个旋钮搬进检查器的遮罩区，就在「跟踪主体 / 从头重跟」旁边：

- **挡住最多猜**（帧）——就是 `max_gap_frames`：主体被挡住时最多按匀速外推多少帧，用完还没找回，路径就停在
  最后一次看到的地方。`min=0`、`max` 与默认值都取自 `capabilities.limits.track_max_gap_frames` /
  `track_gap_default`，界面上那个数字的唯一主人是引擎，不是写死的字面量（引擎没回该字段时才有兜底值）。
- **满画面重找**——就是 `reacquire`：开着时，被挡住的每一帧都会在整个画面上重新找主体；关掉就不会，主体换个
  位置回来会被当成跟丢。默认开着，和引擎的默认一致。

`trackMask()` 多收一个可选的 `options`，只有调用方真的给了值才把字段放进请求体（不传就跟以前一样由引擎取
默认，界面不会因为自己的存在而改变 Agent 的行为）。提示里如实说出这次是哪一档：`reacquire=false` 时写明
「满画面重找这次是关着的，换个位置回来会被当成跟丢」。

`tests/tracking_check.py` 的 `interface_suite` 钉接线而不是钉意图：两个按钮都带同一份
`{ reacquire: trackSweep, maxGapFrames: trackGap }`（数两遍）、客户端确实把 `max_gap_frames` / `reacquire`
发出去、上限来自 `app.caps?.limits?.track_max_gap_frames` 且整个 Inspector 里 `240` 只出现一次（就是那个
`?? 240` 兜底）、输入框的 `max={gapCeiling}` 真的用着它，以及帮助页写着这两个旋钮的名字。

## 1.88 一次跟踪量到片段结尾，量不完的话由界面自己说清

`/clips/{id}/track` 的 `frames` 一直是 `2..900`（`MaskTrackRequest`），可从 1.72 起到 1.87 为止，界面自己
在 Inspector 里数了一遍：`Math.max(2, Math.min(300, whole))`。两个数都不是引擎给的，而 300 那一个是真的会
咬人的——十二秒的片段在 30 fps 下是 360 帧，点一次「跟踪主体」只量了前十秒，剩下两秒遮罩停在最后一次跟到
的位置，而提示结尾写着「导出使用同一份关键帧」。人不看帧数只看提示，就会被这句话骗过去。

这一版把「这一次量几帧」收成一个判断、一个数字来源：

- `contracts.py` 里新增 `TRACK_FRAMES_MIN = 2` / `TRACK_FRAMES_MAX = 900`，`MaskTrackRequest.frames` 的
  `ge`/`le` 与 `capabilities.limits.track_min_frames` / `track_max_frames` 都从这里取——请求契约与能力接口
  不可能再各写一个数（`tests/tracking_check.py` 会把两边读出来的上下限摆在一起比）。
- 界面一侧新增 `effects.ts` 的 `trackWindow(remainingFrames, fromHead, limits)`：够得着就整条量到结尾
  （`frames = min(上限, 剩余)`），量不完时把 `unreachedFrames` 如实交回调用方，剩余不足最低帧数就给出灰掉的
  理由。Inspector 两个按钮都走这一个函数，不再自己数帧。
- 提示跟着判断走：`lost_at_ticks === null` 而这一次没量完时，说的是「单次最多量 N 帧，片段还剩 X.X 秒没分析，
  那段里遮罩停在最后跟到的位置；把播放头挪过去再点「接着跟」就能续上」；量完了才说「导出使用同一份关键帧」。
  开不了跑时按钮是灰的，`title` 写着为什么，出路按位置分两种——播放头之后不够帧数就说「把播放头往前挪一些」，
  从片段开头重跟不够帧数就说「把这段切长一点，或在曲线编辑器里给遮罩中心加两个关键帧」。

`tests/desktop_trackwin_check.ts` 钉的是「它真的听传入的数」：换一组 `{track_min_frames: 8, track_max_frames: 30}`，
帧数、没量完的差额、灰不灰、理由里的数字全都跟着变；两个按钮的接线与那句披露由 `interface_suite` 钉住
（`Math.min(300` 与 `Math.max(2, Math.min(` 都不许再出现在 Inspector 里，`900` 在 `effects.ts` 只许出现一次，
就是那个 `?? 900` 兜底）。行为侧的永久断言在 `http_suite`：一条 12 秒、160×90 的往返走位素材，同一片段两次
dry run 只差请求的窗口——`frames=300` 量到 299 帧刻度、`frames=350` 量到 349 帧刻度，两次之差恰好 50 帧，
而 `lost_at_ticks` 两边都是 `null`（目标从没消失，短窗口停下来说明那是窗口的账，不是跟丢的账）；350 帧那次
越过 300 的那 49 个点仍然是真 sighting，逐点离合成真值最差 1.32 px（0.0083 画面宽，断言 <0.012）。

夹具在这里欠了一次账，记下来因为它长得像引擎缺陷：第一次把这条素材改成 160×90 时只缩了画面、没缩那个亮方块
（仍是 22 px），于是方块比钉住它的相关窗口还宽——方块内部是一整片 245 的均匀值，一个更小的窗口在里面任何一个
位置都能打出同样的分数。报出来的路径整体偏 7 px、尺寸估到 0.124，看上去像「长窗口跟不住」，实际是夹具让目标
失去了唯一的位置。把方块按画幅同比缩到 11 px 后，同一条素材直连 `track_mask` 整跑最差 0.96 px，走 HTTP 路由的那 49 个点最差 1.32 px。分辨办法还是那一条：先核对夹具与自己的
读数，再谈引擎。

### 1.88 的第二道天花板：这条片段的曲线还装不装得下

把界面改成「量到结尾」之后，第一次在真实界面上点十二秒以上的片段就撞出了下一件事：请求被
`PROJECT_LIMIT` 拒了——「工程到了契约上限（片段、轨道或关键帧的数量）」。原因不是界面，也不是跟踪，是两条
一直各说各话的数：`Clip.keyframes` 的上限是 2000 条，而一个**带尺寸的**跟踪点要写 4 条曲线（中心 X/Y 加宽高），
所以 900 帧的请求在数学上永远写不下去（4×900 = 3600）。1.87 及以前那个 300 反而一直没碰到它，因为
4×300 = 1200 恰好装得下——错的窗口把错的天花板藏住了。

修法仍然是「一个行为一处权威」：

- `timeline.py` 里 `CLIP_KEYFRAME_LIMIT` 从契约字段的 `max_length` 元数据读出来（和 `reframe` 的关键帧预算同一
  个读法，不另写一份），`mask_track_capacity(clip, curves_per_point, merge, from_ticks, frame_ticks)` 算出这一次
  还能写几帧：不是本次结果能改写的曲线都算占位（merge 时窗口之前的都留下），一条更长的窗口又会把尾部的点
  吃掉，所以是逐步放宽再回验，而不是解一次方程。
- `/clips/{id}/track` 先按这个容量把 `frames` 收短再分析，回复里多一个 `budget_frames` 说清这次真正写得到几帧。
  收短到不足契约下限（`track_min_frames`）时不再假装能跑，回 422 `MASK_TRACK_BUDGET`，`details` 里带着
  `frames_requested` / `capacity_frames` / `curves_per_point` / `keyframe_limit` / `curves_used` 这五个数。
- reducer 那一侧同样点名拒绝（`clip.mask_track` 里 `kept + tracked` 超上限），所以手搓一条超预算的路径拿到的是
  带算式的 `MASK_TRACK_BUDGET`，而不是 pydantic 的长度检查。界面 `desktop/src/engine.ts` 补了这条码的中文提示，
  出路写的是真能走通的三条：切成短片段分别跟、删掉不要的关键帧、关掉尺寸估计（一个点少占两条）。
- 提示这句话不再由界面自己数帧：尾巴 = `clip.duration_ticks − 回复的 last_at_ticks − 一帧`，被曲线预算收短和被
  单次上限收短是两套话，前者还会说「关掉尺寸估计能让一个点少占几条」。1.87 那种「界面自己算还剩几秒」的
  `unreachedTicks` 参数整个删掉了——界面无权猜引擎跑到哪儿。

门禁：`http_suite` 先用 `keyframes.replace` 给一条 12 秒片段灌 1600 条 opacity 曲线，再按 350 帧请求，要求
`tracked_frames == budget_frames == 100`、最后一个点落在 99 帧刻度、且那个点仍与物体真值差 <0.012 画面宽、
dry run 不动 revision；再手搓一条 150 点的路径（150×4 = 600 > 剩下的 400）要求 422 `MASK_TRACK_BUDGET` 并逐条
读出 `details` 里的 `curves_per_point` 与 `keyframe_limit`。三条变异各自红：路由不再按容量收窗口 → 红在那句
`status_code == 200`（写下去就是通用 PROJECT_LIMIT）；reducer 不再点名 → 红在 `code == "MASK_TRACK_BUDGET"`；
界面不再分支在 `budget_frames` 上 → 红在 `interface_suite` 新增的那两条（分支与插值各钉一处，只提到名字不算）。
MCP 的 `clip_track` docstring 也写了这道天花板，Agent 与人在这里读到的必须是同一句话。

### 1.88 的第三只旋钮：遮罩随远近缩放

那句拒绝的出路里写着「关掉尺寸估计让一个点少占几条」，可 1.87 的界面上并没有这个开关——`estimate_scale` 从
1.72 起就是 Agent 能传的参数，人只能看着引擎给的那句话自己去猜怎么办。出路必须真能走通，所以这只旋钮也交到
人手上：检查器遮罩区里第三个勾「遮罩随远近缩放」，默认开着（与引擎一致），路径遮罩下是灰的并说明为什么
（轮廓的形状与大小按画好的轮廓走，引擎对它本来就不估尺寸）。`trackMask()` 的 `options.scale` 只有调用方给了值
才把 `estimate_scale` 放进请求体，Agent 不传时行为一字不变。

同一次改动把「从头重跟」的语义钉准：`merge=false` 现在清掉**全部四条**遮罩运动曲线，而不是只清这次写出的那
两条。之前的行为留了个洞——先跟出一条带尺寸的路径（2000 条曲线装满），再关掉缩放从头重跟（一个点只写两条），
旧的 `mask_width`/`mask_height` 会原样留在片段上，于是遮罩盒继续沿一条已经不再量它的旧路径呼吸。按钮写的是
「整条重跟」，reducer 就得按那句话做。`mask_track_capacity` 也按同一条判断读容量（整条重写时把四条都算作可清空），
所以这条出路在数字上是真的：同一条 16 秒片段，缩放开着只能量到 500 帧，关着能量到 900 帧（单次的上限）。

`tests/tracking_check.py` 的 `reducer_suite` 断这条语义：先写一条带尺寸的路径，再 `merge=false` 写一条只有中心的
路径，剩下的曲线集合必须恰好是 `{mask_x, mask_y}`、总数 4 条；并断 `mask_track_capacity(..., merge=False)` 大于
`merge=True` 的同一个窗口——否则界面那句出路就是空头支票。`interface_suite` 断两个按钮都带 `scale: trackScale`、
客户端真的发 `estimate_scale`、aria-label 在、帮助页写着这只旋钮。

## 1.89 预算用满时，「接着跟」不再是那句出路

1.88 的提示在被曲线预算收短的那一支里写着「把播放头挪过去再点「接着跟」可以续一段，或关掉尺寸估计让
一个点少占几条」。前半句是错的，而且是可证的错：被预算收短意味着这条片段的曲线已经写到 2000 条上限，
`mask_track_capacity` 在这种片段上返回 **0**，接着跟只会拿到一次 `MASK_TRACK_BUDGET`（实测：一条 17 秒
片段跟满 500 个带尺寸的点 = 恰好 2000 条曲线，此后 `mask_track_capacity(clip, 4, merge=True, from=500 帧)`
= 0，硬发两个点被拒为 `MASK_TRACK_BUDGET`，`details.curves_room = 0`）。也就是说，界面把一条引擎一定会
拒绝的路指给了人——按 1.82 立下的规矩，每一句拒绝都必须指出真能走通的出路，这一句没有。

同一支句子现在说的是两条走得通的路：**关掉「遮罩随远近缩放」再点「从头重跟」**（一个点从 4 条曲线降到
2 条，实测同一条片段从 500 帧变成 900 帧，被单次上限接住；`mask_track_capacity(clip, 2, merge=False)`
= 1000，正是这条路的算术依据），或者**把片段切成两段分别跟**。帮助页把两道天花板分开写清楚：被单次上限
收短时可以挪播放头接着跟，被曲线预算收短时接着跟会被点名拒绝、别再指望它。

引擎侧一字未动（`MASK_TRACK_BUDGET` 与容量算法都是 1.88 就有的），涨的是界面与门禁：
`interface_suite` 现在把提示里那一整行取出来单独断——不许出现「再点「接着跟」」这种**给出路**的句式、
必须出现「不会再量出新的一帧」这句**说明为什么不给**、必须同时出现「从头重跟」与「切成两段」两条实出路；
`reducer_suite` 把上面那段实测钉成永久断言（装满 2000 条 → 容量 0 → 两个点的续跟被 `MASK_TRACK_BUDGET`
拒掉且 `curves_room == 0`，同时 `merge=false` 的中心重写仍能拿回 1000 帧的容量）。

## 1.90 `clip.fade` 换了一处落点：淡是片段两条边上的窗口

命令名、字段名、`property`（`opacity` / `gain`）、`mode`（`in` / `out` / `both`）都没变，变的是**它写
到哪里**：1.89 及以前 `clip.fade` 把淡写成该属性的关键帧，写之前先把这条曲线整个清掉；现在它写
`Clip.fade`——一份与曲线并列的片段状态，四个整数（`opacity_in_ticks` / `opacity_out_ticks` /
`gain_in_ticks` / `gain_out_ticks`），单位是 tick，从片段自己的两条边量起。工程 schema 因此进 v14，
`capabilities.features.clip_fade_envelopes` 是这条新语义的说法。

行为上的四条差别，都是先量出来才改的：

| 场景 | 1.89 | 1.90 |
| --- | --- | --- |
| 先淡入 1 秒、再淡出 2 秒 | 只剩 `5s=1, 6s=0`，淡入被抹掉 | `fade.gain_in_ticks=1s` 与 `gain_out_ticks=2s` 都在，`Clip.keyframes` 一条不写 |
| 片段已有闪避/手敲的六个音量点 | 淡一次把六点清成两点 | 六点原样保住，导出与预览按 `曲线 × 淡` 走（3.5 秒处 0.250＝0.25×1.0，6 秒处 0.0） |
| 淡完之后把片段剪短 | 淡停在旧刻度上，落在新结尾之外，等于没淡 | 淡从新的边量起 |
| 淡完之后分割 | 切口两边各留一份淡，中间凭空淡一下 | 左半保住淡入、右半保住淡出，切口两头都是 1.0 |

`duration_ticks` 的类型从 `Duration`（`gt=0`）放宽到 `Ticks`（`ge=0`）：**0 就是取消它点名的那一头**
（`mode=both` 清两头，之后 `Clip.fade` 回到 `null`）。两头加起来仍不能超过片段长度，超了回
`422 INVALID_FADE`，`details` 给 `clip_id` / `clip_duration_ticks` / `fade_in_ticks` / `fade_out_ticks` /
`room_ticks`（这一头还能要多少）；音频素材点 `opacity` 回 `INVALID_FADE` 并带 `asset_kind`。
窗口比片段长时不会报错，被夹到片段自己的长度（`fade_windows` 是唯一的夹法），因为修剪随时可能把
片段弄短，而一条倒着走的淡不是任何人要的。

求值只有一处权威：`animation.sample` 乘、`animation.expression` 也乘（编译出的 FFmpeg 式子形如
`(曲线)*(…3-2*…)`，`volume=` 与 `geq` 的 alpha 各自带上它），浏览器用的是引擎在同一次
`preview_manifest` 里**另发的一条包络曲线**（`clips[id].fade = {opacity, gain}`，值为 1.0 的那段就是
平段），靠嵌套 `opacity` 相乘。所以 `clips[id].curves["opacity"]` 仍是未被乘的那条曲线——它在曲线
编辑器里画的就是它自己。只有一层、只带淡的片段也不再走「直通」渲染路径：`compile_render_plan`
会把它按合成来编（`geq` 的 alpha 里才有地方乘这条包络）。

`clip.fade` 从此不再动 `Clip.keyframes`，因此它与 `Clip.stabilization` 那把锁、与曲线预算
（`MASK_TRACK_BUDGET` / reframe）互不影响；老工程写在曲线里的淡一个点都不用改，照旧渲染。


## 1.95 淡有形状了：一条命令可以同时带长度与形状

1.90 把淡搬到片段的边上，但那条斜坡只有一种走法（smoothstep）。这一版给每条属性一个 `shape`：`linear` / `ease_in` / `ease_out` / `ease_in_out`，默认 `ease_in_out` 就是原来那一条，所以老工程读进来、渲出去一字不差。它不是新算术：淡本来就是一条普通分段曲线（`fade_curve`），导出编译它、预览动画它，两端读同一份点表；形状就是那条斜坡用哪种插值。淡出那一段按时间反演镜像控制点，所以同一个形状在两条边上摸起来是一样的（`tests/fadeshape_check.py` 把这条镜像恒等式与 35 点两端一致都钉了）。

`clip.fade` 因此允许只带 `shape`（保留这一头原有的窗口长度），也允许一次同时带长度与形状；两者都不给是 422。`capabilities.fade_shapes` 下发 `{id,label}` 表，界面的下拉列的是它——与 `transition_kinds` 同一条规矩，界面不许自己写四个名字。`features.clip_fade_shapes` 是这条能力的说法；老引擎不回时那一行根本不出现。

## 1.96 老工程里写在曲线上的淡，可以一条命令搬到边上

1.90 改了 `clip.fade` 的落点，但没有动老工程：那些淡今天仍是属性曲线上的关键帧，检查器那两个数字看不
见它，修剪与分割也不带着它走。帮助页给的出路是「先在曲线编辑器里清掉旧点」，等于把引擎已经知道的事
推回给人手。新增 `{"op":"clip.fade_adopt","clip_id":"c1","property":"opacity"}`：认出**那一个**形状，
把它写成 `Clip.fade` 的窗口，并删掉被搬走的那几条关键帧（不删就会乘两次）。工程 schema 仍是 v15——
它写的是一份早已存在的 `FadeEnvelope`，只是来源换成了曲线。

认出的条件一条都不放宽（`timeline._fade_adoption`）：

- 这条属性上的点，去掉两头之后必须一条不剩（夹着任何人手敲的点就拒绝，并把多余的 `at_ticks` 交回）；
- 每条边的值只能是 `0.0` 或这条属性的静止值（`clip.effects` 上的那个数），起点必须是 `0.0`；
- 插值必须全是 `ease`——那是当年那条淡留下的形状，所以搬完记成 `shape="ease_in_out"`；
- 点必须落在片段自己的范围内（相对时间含 `animation_offset_ticks`，所以裁过的片段量的是它真正播的那段）；
- 这一头已经是窗口就不再搬第二次（`clip.fade` 上窗口非零 → 拒绝）。

窗口长度从**实际点的位置**读：淡入 = 边上那个 0 到下一个点的距离，淡出 = 上一个点到结尾的距离。两条
斜坡互相越过时（`in + out > duration`）不报错，各自读自己真正占的那一段，因此 `in + out <= duration`
是构造保证的，不需要第二条拒绝。什么都不符合时回 `422 FADE_ADOPT_SHAPE`，`details` 点名 `clip_id`、
`property`、片段长度、静止值，并把这条属性上看到的关键帧逐条带回；片段 id 不存在照旧是 `404 NOT_FOUND`
且带 `clip_id`。两种拒绝都不涨 revision，`dry_run` 只回一份将要落库的预览（`committed=false`、
`base_revision` 是当前的、`project.revision` 是下一个号）。

「搬完画面不动」是被量过的，不是嘴上说的（`tests/fadeadopt_check.py`）：把 `0 → resting` 做 ease 插值
与把 `resting` 乘上那条 smoothstep 是同一条曲线，于是 40 个采样点上搬前搬后的 `animation.sample` 逐点
相同（最差偏差 0.0e+00）；同一条时间线用真实 FFmpeg 各渲一遍，八个时刻的中心像素逐个比，容差 1 阶。
`capabilities.features.clip_fade_adopt` 与 `capabilities.commands` 里的 `"clip.fade_adopt"` 是这条能力的
说法，MCP 的 schema 由契约生成，因此 `timeline_edit` 直接收得到它。界面在检查器那一行给一个
「搬成边窗口」按钮，只有 `fadeAdoptHint` 认为**可能**搬得动时才出现（它只断言必要条件，最终判断仍留给引擎）。


## 1.97 整轨一次搬完：规划只读，写入仍然是那一处

1.96 的 `clip.fade_adopt` 一次搬一条属性一个片段。老素材通常不是一段而是一整轨，所以这一版加一条
只读规划，人那侧是检查器里的「整轨搬成边窗口」，Agent 那侧是同一件事：

| HTTP | MCP | 语义 |
|---|---|---|
| `POST /v1/projects/{id}/tracks/{tid}/fade-adopt` | `track_fade_adoption` | 走一遍这条轨，能搬的排成普通 `clip.fade_adopt` 命令，搬不动的连原因与实际看到的关键帧一起交回 |

请求体是 `FadeAdoptTrackRequest`：`request_id`、`expected_revision`、可选 `sequence_id`、`apply`、
`dry_run`。`apply=false`（MCP 工具固定如此，并且 `readOnlyHint=true`）不落库，`committed=false`，
交回的就是当前工程与命令表；`apply=true` 把这批命令交成一个 `EditBatch` 走 `ProjectStore.mutate`，
所以**一整轨只涨一个 revision、只进历史一条**，`dry_run=true` 给的是将要落库的那个号（`base_revision`
仍是当前的）。规划与写入用的是同一条判断——`timeline.fade_adopt_track_plan` 逐条调 `clip.fade_adopt`
背后的 `_fade_adoption`——界面与 Agent 都不许有第二套规则，否则「规划说能搬、reducer 拒绝」会把整批
一起回滚。

报告形状：`fade_adoption = {track_id, clips[], adopted, skipped, commands[]}`。`clips` 按片段的
`position_ticks` 排（界面与 Agent 读到的顺序就是时间线从上到下），每项要么是能搬的
`{clip_id, property, in_ticks, out_ticks, shape, keyframe_count}`，要么是搬不动的
`{clip_id, property, skipped, ...details}`（details 就是 `FADE_ADOPT_SHAPE` 那一条的五个字段）。
**这条属性上根本没有关键帧的片段不出现在报告里**——整轨报告的价值是「哪几段、为什么」，列 N 条
「这里没有淡」就把它埋了。音量轨上的 opacity 被跳过的原因单列一句（`audio has no opacity to fade`），
并且不会被排成一条 reducer 必定拒绝的命令。

拒绝：轨道不存在 `404 NOT_FOUND`（带 `track_id`）；这条轨上没有片段 `404`（同一句带 `track_id`）；
`apply=true` 而一条都排不出来时 `422 FADE_ADOPT_NONE`，`details` 给 `track_id`、`inspected` 与逐条
`skipped`。三种都不涨 revision。`capabilities.features.clip_fade_adopt_track` 是这条能力的说法。

界面那句中文报告（`搬了 N 段淡` / `这条轨没有能搬的淡`）由 `desktop/src/effects.ts` 的
`fadeAdoptSummary` 生成，原因走 `FADE_ADOPT_REASONS` 那张表：键就是引擎那句原话。
`tests/fadebatch_check.py` 把两边的句子对起来（新增一条拒绝而表里没配就红），
`tests/desktop_fadetoast_check.ts` 管另一半：数取自规划而不是界面自己数的、只列前三段、
未知原因不许写成空串。

`tests/fadebatch_check.py` 量的三件事：规划交回的命令交给 reducer 后，落库的窗口逐条等于规划报的两个
数、形状是 `ease_in_out`、该删的关键帧删干净而另一条属性的点一个不动；只读规划不落库、`apply=true`
一次只涨一个版本、没得搬与被拒都不写版本；成片上三段老淡一次搬完，18 个时刻的中心像素逐个相同
（最差偏差 0 阶）。实机点过三次（发布包里的引擎 + 构建好的渲染端，量在 1280×800 同源 iframe 里做）：一条画面轨上两段
老淡加一段手敲的，点「整轨搬成边窗口」后 r1→r2 只涨一个版本，四颗与两颗关键帧菱形归零、那两个数字从
0.00 变成 1.00/1.00，手敲那段的三颗一字未动；再点一次提示「这条轨没有能搬的淡 / 1 段有淡但搬不动：
c2（斜坡不是从 0 走到这条属性的静止值）」，版本不再变；往另一条轨再放两段老淡，点一次提示「搬了 2 段
淡 / 画面一个像素都不变 / 整轨把老淡搬成边窗口 · r4 / 已原子写入，历史可回滚」，r3→r4。那颗按钮在折叠的
`<details>` 里，所以探针先展开、再滚动、再用 `elementFromPoint` 命中——按钮的矩形在折叠时也报非零，
只断言「存在」会绿着通过。


## 1.98 柔焦能打关键帧了：阶梯是唯一的那份权威

`{"op":"keyframe.set","clip_id":"c1","keyframe":{"property":"blur","at_ticks":…,"value":0…0.25,
"interpolation":"linear|hold|ease|bezier"}}` 从这一版起被接受，`clip.patch` 与 `capabilities` 同步。
它不是把「预览渐变、导出阶梯」这个已知不一致藏起来——恰恰相反，阶梯被抬成两端共用的唯一表：

- `animation.spatial_schedule(clip, "blur", quantum)` 把曲线采样成**整帧对齐**的常值窗：步长至少一帧，
  并且不超过 `capabilities.limits.blur_schedule_segments`（现在是 24）段——短于 24 帧的片段一帧一段，
  更长的自动把步长加宽而不是拒绝；相邻同值合并成一段，所以「按住到片段末尾才跳变」只有一段
  （那一值没有任何一帧会看到，多排一段就是撒谎）。每段取的是那段**中点**的权威 `sample`。
- 导出（`render.focus_stages`）为每一段非零窗串一个 `gblur=sigma=R:steps=6:enable='between(t,a,b)'`；
  `gblur` 的 sigma 不读表达式，`enable` 是它唯一的逐帧钩子，这是全部机制的来源。
- 预览拿的是引擎在同一次 `preview_manifest` 里下发的 `clips[id].spatial.blur` 点表——逐段一点、
  `easing` 就是 `steps(1, end)`。`color_filter` 里那个静态 `blur(Ncqh)` 在有曲线时**不出现**，
  并且此时 unsharp 挪到新的 `edge_filter` 字段，好让浏览器的嵌套顺序仍然是「调色 → 柔焦 → 边缘」，
  与导出一致。没有曲线的片段一字不变。

`blur` 于是进了 `Property`（与 `mask_*` 同一类：能关键帧但不是那六个标量属性之一），值域仍是
`PROPERTY_LIMITS["blur"] = (0, BLUR_LIMIT)`——曲线不许爬到静态旋钮到不了的地方，超了就是契约层的
`ValidationError`。`clip.effects.blur` 在有曲线时是被**取代**而不是叠加：`sample`、导出与预览三家都
只认一条路，这一条与 1.90 那次「淡乘进曲线」的教训同源。

验收（`tests/blurkey_check.py`，全绿）：

* 阶梯算术：段与段首尾相接、覆盖整段、不超上限、每段值等于该段中点的 `sample`、边界落在整帧上
  （4 秒 25 fps 的那条 0→0.25 排成 20 段、步长 5 帧）；12 帧的短片段正好 12 段；`hold` 合并。
* 两端同源：下发的点表逐条等于窗的偏移与值、`easing` 是 `steps(1, end)`；编译串里
  `gblur=sigma=…:enable='between(t,a,b)'` 的**段数等于非零段数**，`sigma` 逐段等于
  `focus_radius(值)`，两个秒数逐段等于那一段的边界（按导出形状正则抓，不按逗号切——`enable` 自己带逗号）。
* 成片差分：素材是一张静止的二值棋盘（各帧内容相同），参照是**同一条编译路、同一个编码器**渲出来的
  「整段都用这一个 σ」的片段。20 段逐段与自己的参照对得上（容差 0.5 绝对或 10% 相对，来自编码噪声
  而不是期望），细节从 13.9 单调降到 0.01，开头那三段之内就能看出在糊。
* 契约层：`blur` 现在能当关键帧属性，`denoise`/`sharpen` 仍然不能，超上限的曲线值在契约就被拒。

界面：柔焦那一行的右边多一个 ◇（按 `capabilities.features.blur_keyframes` 出现，界面不凭记忆决定
哪颗旋钮能做动画）。移动播放头、调数值、按 ◇ 记一个点；已经有曲线的片段，滑杆改的是**当前那个点**。
实机在发布包引擎上点过：一段零关键帧的棋盘，按 ◇ → r1→r2、片段上多一颗 ◆、按钮文案变成「删除柔焦
关键帧」；再补一个 3 秒处 0.25 的点之后重读页面，`.layer-blur` 这一层挂着一条 16 段阶梯动画，首段是
`blur(0.833333cqh)`（正好是第一个 5 帧窗中点的采样值），末段 `blur(25cqh)`，计算样式已经真的在糊。

仍未做，也不假装做了：`sharpen`/`sharpen_radius` 仍不能打关键帧（那条 unsharp 式子里半径与强度都没有
逐帧形式，一串窗意味着一串 `split+gblur+blend` 三元组，代价与收益不划算）；`blur` 当时还没进曲线编辑器
（那里列的是六个标量属性），拉焦点要靠播放头 + ◇（1.99 已把它送进曲线编辑器，见下一节）；段数上限是引擎下发的一处常数，不按片段长度自适应。

## 1.99 柔焦进曲线编辑器：没有新路由，只有列表里多的一项

这一版**不增加命令、不增加错误码、不增加路由**。`keyframe.set` / `keyframe.move` 从 1.98 起就接受
`{"property":"blur", …}`，值域仍是契约里的 `0…0.25`（占画面高的比例），Agent 与界面写的还是同一条
reducer 分支；改的只是界面此前只在检查器给一个 ◇ 按钮，现在「动画曲线」的属性列表里也有「柔焦」。

调用方需要知道的仍是引擎下发的那几个数，客户端不自带：

- `capabilities.features.blur_keyframes` —— 没回这个字段（1.98 之前的引擎）时界面根本不提供这条曲线。
  它是界面提示，不是引擎的许可：老工程直接发 `blur` 关键帧照样收。
- `capabilities.limits.blur_fraction` 与 `limits.blur_radius_px` —— 曲线纵轴的上下限由这两个数按
  `settings.height` 折算后取小，与检查器那行滑杆调用的是同一个函数（1080 高时是 5.925%，120 高时才是 25%），
  所以画不出「界面允许、导出会拒」的那一段。
- `POST /v1/animation/sample`（「播放头添加」读的那一条）的字典按 `ClipEffects.model_fields` 给全，
  `values["blur"]` 就是滑杆现在的那个数，曲线上的新点由此起笔而不是从 0。

写进去之后仍然按 1.98 那一条走：`preview-manifest` 里的 `spatial.blur` 与 `compile_render_plan` 里那一串
`gblur=…:enable='between(t,a,b)'` 出自同一张整帧对齐的窗表，两端不是近似而是同一份点表。


## 1.100 柔焦与清晰的基准是画面高，不是交付帧高

这不是新命令、新字段或新错误码：`effects.blur` / `effects.sharpen_radius` 的语义本来就是「画面高的
百分比」，`capabilities.limits.blur_fraction` 与 `blur_radius_px` 也是按这个语义下发的。改的是导出侧那一次
除法——它此前除的是交付帧的高。

对调用方意味着两件事：

- 同一颗旋钮在竖屏 / 方画幅（`fit="contain"`）交付里，成片画面现在与预览一样柔；`cover` 与 `stretch` 铺满
  帧，所以数值不变。工程与交付同比例时，编译出的滤镜串与改前一字不差。
- `BLUR_OUT_OF_RANGE` 现在按画面高判：`details.max_radius_fraction` 是 `64 / 画面高`，拒绝的句子点名的是
  画面（`… px radius on a 608 px picture …`）。1920x1080 工程交付 1080x1920（contain）时画面高 608 px，
  界面按工程高允许的 5% 现在导得出去；11% 仍被拒绝。


## 1.101 字幕的字号与内缩：量的是画面框，不是交付帧

延续 1.100 那条根因。文字层的底板是按交付帧铺的（`color=black@0:s={out_w}x{out_h}`），而同一帧里的视频画面
在 `contain` 适配下只占中间那条带，所以此前 `fontsize=out_h×text.font_size` 与 `y=h*0.08` 这类写法在竖屏/方画幅
交付里相对画面放大、并且会写进黑边。现在两处都按 `render.picture_size(out_w, out_h, 工程宽高, fit)` 那个框算：

- `fontsize = 画面高 × text.font_size`（`text.font_size` 的语义仍是「画面高的比例」，契约值域 0.01–0.2 不变）；
- 靠上 `y = (帧高-画面高)/2 + 画面高×0.08`，靠下 `y = 同一条 92% 处 - text_h`；左右内缩同理按画面宽；
- 居中仍是 `x=(w-text_w)/2`、`y=(h-text_h)/2`（画面在帧里居中，两种写法同一点）；
- 垫子（`box`）那条 alpha 带的上下沿也换成同一段画面坐标。

工程与交付同比例时（`fit` 是 `cover`/`stretch`，或画幅本来就一致）画面高就是帧高，字号与居中位置与改前相同；
只有内缩那几处从 `h*0.08` 变成同值的数，所以按字符串断言的旧门禁随之更新，像素级那两组对照没有变化。


## 1.102 遮罩的坐标：画面的百分之几，不是交付帧的

`clip.mask` 的 `center_x/center_y/width/height`（以及 `mask_x/mask_y/mask_width/mask_height` 那四条曲线）
归一化的对象一直是**画面**：浏览器把它铺在锁着工程比例的那个预览框上（`mask-image` 的 unit 图），检查器与
向导也按这个比例换算。导出此前不是：shape 分支的 `geq` alpha 用 `X/W`、`Y/H`，而这段 alpha 跑在
`scale=…:force_original_aspect_ratio=decrease,pad=out_w:out_h` 之后，`W/H` 是垫好的交付帧；自由路径分支把轮廓
光栅化到 `raster_size(out_w, out_h)` 的板子上。工程与交付同比例时两者相等，`contain` 补边时差着一个比例因子。

现在：

- `masks.alpha_expression(mask, values=None, box=None)` 收画面框 `(offset_x, offset_y, width, height)`
  （帧像素），把 `X/W` 折成 `(X-offset_x)/width`；`box=None`（画面填满帧）时产出的串与 1.45 以来逐字节相同。
- 自由路径的板子按画面尺寸光栅化，然后 `pad=out_w:out_h:offset_x:offset_y:color=中性值` 垫成帧——
  中性值取该遮罩自己的值（反相遮罩垫白、普通遮罩垫黑），所以画面带外不会凭空多出一块被保留或被削掉的区域；
  同比例时这一步整个不出现在图里。补丁的 overlay 锚点同样加上那两个偏移。
- 羽化（`feather`）与路径的顶点都跟着板子走，因此不需要另一次除法。

契约与命令没变，工程 schema 仍是 v15；这是导出侧一次几何归位，不是新能力。


## 1.103 3D LUT：`POST /v1/lut/parse` 现在两种表都认

没有新路由、没有新命令，改的是那一条解析路由能说什么。`LutParse.content` 里的 `.cube` 由**文件自己的表头**决定
回复形状：

- `LUT_1D_SIZE` → `{"kind":"lut","title","size","channels":[[…],[…],[…]]}`，与 1.62 以来一字一样；
- `LUT_3D_SIZE` → `{"kind":"lut3d","title","size","cells":[r,g,b,…],"resampled_from":int|null}`，
  `cells` 是 `size³×3` 个 0..1 的数，红最快、蓝最慢（`.cube` 的行序），超过
  `grade_limits.max_lut3d_size`（当前 17）的网格由引擎按三线性插值重采样，并把原始边长写进
  `resampled_from`——不是静默降级。

回复原样进 `clip.color.grade` 就是一条节点（`enabled` 自定），reducer 与契约负责拒绝：格点数与 `size³×3` 不符、
`resampled_from` 不比存的网格大、带 `mix`/`blend`、或塞进 `parallel` 分支，都是 422。坏文件的拒绝带
`line`/`size`/`rows`，`INVALID_LUT` 一个码不混用。

1.234 起预览也生效：`grade_tables` 交出的立方阶段带 `cells_u8`（红最快、每格三字节的 base64，
17³ 是 14,739 字节）与 `preview: true`，界面读的 `preview_grade` 不再把这一段拿掉；
`preview-manifest` 那一行同时给 `webgl: true` 与 `color_basics`（曝光/对比/饱和三个数），
`color_filter` 清空——整条链由 `desktop/src/gradeCanvas.ts` 的 WebGL2 画布按同一张表、
同一档四面体插值走一遍。两种时候仍交不出立方：画面是文字层或嵌套合成（没有 `TexImageSource`），
或链上还有第二路画面（`composite`/`layer` 要两个输入）——那时 `webgl` 为假、`color_basics` 为 `null`，
CSS 滤镜串保留其余各段（立方那一级照旧只在导出里生效），不会把整条调色悄悄丢掉。
导出侧 `compile_render_plan` 把节点写成作业目录里的 `lut3d-<sha>.cube` 并产出
`lut3d=file=lut3d-<sha>.cube:interp=tetrahedral`。`capabilities` 两条并放：
`features.lut3d=true`、`features.lut3d_preview=true`。
它没有强度也没有混合方式，理由写在契约里：只有一端能执行的强度不是强度——与 1.78 的降噪同一个规矩。


## 1.104 工程级 inline 查找表预算

没有新路由。改的是「什么样的编辑会被拒」：`clip.grade`（以及任何带动表的 `clip.add`／批量命令）在
reducer 的候选状态上算一次全工程的采样点总数——1D 节点是三条通道各一行，3D 节点是 `size³×3`，
并联分支的每支各算，`enabled=false` 不算删除（表还随状态快照），嵌套合成里的片段同样算。
总数超过 `capabilities.grade_limits.max_inline_samples`（当前 200000，一处主人是 contracts 的
`GRADE_INLINE_SAMPLE_LIMIT`）**且这一步让工程更满**时，回 422 `GRADE_INLINE_BUDGET`，`details` 交出
`samples`/`limit`/`worst_clip_id`/`worst_clip_samples`。「只拦增长」是刻意的：否则一次越界会把那份工程
冻成只读，连删表的编辑都发不出去——而删表正是唯一的出路。

MCP 没有新工具（`timeline_edit` 从契约生成，自动带上这条判断）；`POST /v1/preview-manifest` 那份候选
工程走同一个 reducer，同一条判断。

## 1.105 额度先问得到：`GET /v1/projects/{id}/grade-capacity`

只读，MCP 那边是 `grade_capacity(project_id)`。回执：

- `samples`：全工程 inline 查找表占的采样点数——与 `clip.grade` 被拒时 details 里那一个是同一个函数算的；
- `limit`：等于 `capabilities.grade_limits.max_inline_samples`（200000），不是第二处常数；
- `room`：`max(0, limit - samples)`；一张 17³ 是 14739 个，所以 `room < 14739` 就是说「再挂一张必被拒」；
- `clips_with_tables`、`worst_clip_id`、`worst_clip_samples`：哪条片段最占地方，腾地方的时候知道动谁；
- `by_clip`：前 20 个真有表的片段（按占用从大到小、同值按 id 排，所以同一个工程两次问答案一样）；
- `by_clip`：占用最高的前 20 条真有表的片段（按占用降序、同值按 id，所以同一个工程两次问逐字相同）；它只是视图，**不要**拿它的部分和去对总数；
- `by_clip_samples`：**全部**根片段上的表加起来是多少（不截断），`other_clips` 说清还有几条带表的片段没列进 `by_clip`；
- `nested_samples`：嵌套合成贡献的份额。恒等式是 `by_clip_samples + nested_samples == samples`。

`sequence_id` 不接受——额度属于整份工程，不属于某一条时间线。未知的工程 id 按既有规矩点名回 404 并带回
它收到的 id。

## 1.107 那一行额度读数：界面只念引擎给的字

`GET /v1/projects/{id}/grade-capacity` 的回执多了四个字段，全部由 `grade_capacity()` 一处算：
`room_cubes`、`room_tables`（还放得下几张满格 3D 立方 / 满格 1D 表）、`cube_samples`、`table_samples`
（一张满格表是多少采样点，取自 `LUT3D_SIZE_LIMIT` 与 `LUT_SAMPLE_LIMIT`）。

检查器调色那一节按 `project.revision` 取一次回执并显示这一行；版本一变就清空重取，所以显示的数要么属于
当前这份工程、要么整行不出现。渲染层没有任何一处对 `room` 做除法——`tests/desktop_gradecapacity_check.ts`
就是拿一张**故意不自洽**的回执（`room` 明明还够一张立方而 `room_cubes=0`）来断这一点的。

同时修掉 1.103 的一处不对称：`换一张 LUT` 那颗按钮此前只在 1D 节点上出现，3D 节点拿不到它。

## 1.108 整轨套一条调色：`POST /v1/projects/{id}/tracks/{tid}/grade-apply`

收 `GradeApplyTrackRequest{request_id, expected_revision, clip_id, mode, sequence_id?, apply, dry_run}`。
`mode` 是 `replace`（每段最后就是这条链）或 `append`（接到每段已有节点后面）。

回执 `grade_application`：`nodes`/`chain_samples` 是要套过去的链，`targets` 是同轨其它片段数，
`applied`/`skipped` 是两个结果各多少段，`room_samples` 是套完后工程还剩多少查找表额度，
`clips` 逐段给 `nodes`+`added_samples` 或给 `skipped`（中文原因 + 实数），`commands` 是可直接提交的
普通 `clip.grade` 命令。`apply=false` 只回规划；`apply=true` 把这批命令当一次编辑写入（一个 revision、
一条历史）。空链 → 422 `GRADE_APPLY_NONE`；一段都套不上 → 422 `GRADE_APPLY_EMPTY_TRACK`，两者 details 都点名。


### 1.118 自由路径遮罩的形状动画

`Clip.mask_shape_keys` 是一条**矢量**关键帧表：一枚帧带整条顶点表（`{at_ticks, vertices, interpolation, bezier}`），
不是每顶点四条标量曲线——64 个顶点会摊成 256 条曲线，还会让一个顶点与它的两条控制柄各自走各自的过渡。
过渡的算术仍只有一处：`animation.vertices_at` 把区间两端交给 `_interpolate`（标量曲线用的同一个走法），
所以「线性／保持／缓入缓出／贝塞尔」在形状上与在数值上意义相同。

导出与预览读**同一份窗表**。`animation.mask_shape_schedule` 把这条矢量曲线编译成一格一步的窗（与柔焦 1.98
共用同一个编译器 `frame_windows`），段数上限是 `capabilities.limits.mask_shape_schedule_segments`；导出每窗切一张灰度板，
用 `overlay=x='…':y='…':eval=frame:enable='between(t,a,b)'` 依次叠进遮罩板，`preview_manifest` 的 `mask_shape`
给界面同一串窗（每窗一张单位轮廓图，加上落位用的 `width/height/offset_x/offset_y`）。形状两端一起阶梯，
而遮罩盒仍按 `mask_x`/`mask_y` 曲线连续搬动——阶梯是窗表给的，运动仍是曲线。两窗共享的那条边界属于**后一窗**
（导出把后一张板盖在前一张上），界面按同一口径选窗；`tests/maskshape_check.py` 在成片像素上量过那一刻。

判断只有一处：`Clip.mask_shape_problem()`，由 `clip.mask_animation_problem()` 第一道问，回 `INVALID_MASK`。
它管三件事：只有自由路径遮罩能记轮廓帧、每一帧的顶点数必须等于画好的轮廓、同一时刻只能有一帧。
拓扑不同之所以点名拒绝，是因为形变只改位置不改拓扑：加点、删点、抹角点、自动平滑改的都是那条静态轮廓。
额度写在契约字段的 `max_length` 上（`capabilities.limits.mask_shape_keys`，reducer 用 `CLIP_MASK_SHAPE_LIMIT`
从同一处读，两边不可能漂移），写满时回 `MASK_SHAPE_LIMIT` 并给出「删一帧／把这段切成两个片段」两条出路；
同一时刻的顶替不算增长，所以记满之后仍能改某一帧而不必先删。

兼容：未记轮廓帧的工程编译串与 1.117 逐字相同（`maskshape_check` 断这条）；新字段的空表在回执指纹里按
「没提过」处理，所以 1.118 之前写下的请求重试仍命中自己那张回执（`blur_check`/`mask_check` 那两组常数指纹）。

### 1.119 时间线的一组针：框选与整组拖动

这一版全在界面手势层，契约、HTTP、MCP 一字未改。一次抓多枚针写的仍是引擎本来就有的 `keyframes.move`
（`moves: [{from_ticks, keyframe}]`，刻度按片段本地交，reducer 自己加回 `animation_offset_ticks`），只挑中
一枚时仍是 `keyframe.move`，复制那一组则是同一批次里若干条 `keyframe.set`——一次抓取一条命令（或一个批次）、
一个 revision、一步撤销整组回来。Agent 侧本来就能写这几条，这版补的是人这边的手感。

界面上的三条判断各只有一处来源：整组在时间上的余量走 `curveDrag.clampGroupTimeShift`（曲线编辑器 1.117 用的
就是这一句，`desktop_keyframedrag_check.ts` 把两处对成一个等式，谁另起一份夹法就红）；撞针按 reducer 的同一句
（`occupied - source_ids`：普通拖动时组内那些格先腾空，复制时原针留在原地所以照样占位）；框选的命中集读的是
屏幕上真画出来的那些菱形矩形，所以画不下的属性与拖动中的影子都不在里面。拒绝那句话点名的是**真的被占的那条
曲线**，不是被抓的那一条——判错属性就会把人支去删一枚无辜的针。

实测改掉的一处：框选的命中集原先在 pointerdown 那一刻快照一次屏幕。这条时间线是人跟 Agent 共用的，Agent 在拖着框的时候改写工程，那份快照就指向一枚已经不存在的针——所以命中改成每次 `pointermove` 都重新量（看得见什么挑什么）。写路径本身仍由 `expected_revision` 兜住：拖动中途工程被人改过，松手那一次会被引擎整笔拒回，不会静默覆盖。

### 1.120 并联节点的分支权重

`GradeParallel.weights` 是一份**按位置覆盖每一支**的浮点表（`0..capabilities.grade_limits.branch_weight_max`，
字段约束与下发的那个数共用同一个常量 `GRADE_BRANCH_WEIGHT_MAX`）。它编译成的仍是每通道的一张表：并联节点的
输出由「各支的平均」改成「各支的加权平均」，没给权重时每个位置按 1 计——乘 1.0 在二进制里是精确的，所以
默认路径与 1.119 那条除法逐位相同，`tests/grade_check.py` 把这条兼容钉成断言而不是说明。

三条形状规矩：

- **给就必须给全**。长度与支数不符的表在 pydantic 的 model validator 里就被拒（422 请求校验，写入根本没发生），
  因为那份载荷在两端会算出不同的结果；界面侧由 `gradeGraph` 那一份判断负责补齐（加一支补 1、删一支同删那一格）。
- **全部为 1 等于没有这张表**。界面在这种情况下把 `weights` 整个撤掉而不是交一串 1：撤掉才是 1.120 之前那份
  载荷的样子，也让 `projects._fingerprint` 里「空表按没提过处理」那条规矩把老回执保住（`weight_receipt_suite` 断这条）。
- **全部为 0 是「这一节不改画面」**，不是黑场：分支本来就是对该节点输入做的那一映射，一份都不加就是什么都不加，
  编译结果里根本没有这一节（`node_function` 此时返回 None）。

没有新的错误码，所以 `error_vocabulary_check` 那张中文词表不必动；能力位是 `capabilities.features.grade_branch_weights`
加 `capabilities.grade_limits.branch_weight_max`，界面两个都读到才摆出这一排旋钮。真实成片一侧，同一条并联节点把暗带的红值从均分的 43 推到 2:0 的 87、拉到 0:2 的 2（`weight_media_suite`
那行 print 报的就是这三个数）。

仍未做：另一段画面作为节点的**第二路输入**（连线）。导出侧怎么把两支画面喂进同一个 FFmpeg 阶段已经量过并记在
`AGENTS.md`，但那要把「一条链塌成一张每通道表」这个不变量换掉，属于架构改动，不在这一版假装交付。

### 1.122 并联节点的分支混合方式

`GradeParallel.blends` 是第二份按位置的表：每一支的结果先按自己的方式与进到本节点的那个值相合，再按权重参与
平均。它用的仍是节点级混合那一份 `blend_values`（`normal` 原样交回该支结果），所以全 normal 与不设这张表
逐位相同，1.120 那份编译结果一个字都不动。停用或不动本通道的那一支交回进来的值本身，它的模式不参与——
「停用即直通」不留下一个能改语义的下拉。

形状与权重同一条规矩：给就必须给全（长度不符在 model validator 就拒，422 请求校验，写入没发生），全是
normal 时界面把整份表撤掉而不是交一串 normal，`projects._fingerprint` 把空表按「没提过」处理，1.122 之前
写下的回执继续命中自己。模式词表只有契约那条 `BlendMode` 一个来源，界面的 `BLEND_MODES` 与它逐字对齐
（`desktop_branchblend_check.ts` 把两份对起来），能力位是 `capabilities.features.grade_branch_blend_modes`。

真实成片：把其中一支改成 `difference`，交付画面与正常平均差 33.0 级；换成 `screen` 时编译表与检查里那份
独立参考 `predict` 差 ≤0.5 级。仍未做：另一段画面作为节点的**第二路输入**（连线）。

### 1.123 清晰的强度与半径可以打关键帧

`SpatialProperty` 从 `Literal["blur"]` 扩到 `Literal["blur", "sharpen", "sharpen_radius"]`，也就是
`Keyframe.property` 多认两条 id；取值带与静态字段同一条带（`PROPERTY_LIMITS["sharpen"] = (0.0,
SHARPEN_LIMIT)`、`PROPERTY_LIMITS["sharpen_radius"] = (0.0, BLUR_LIMIT)`），所以一条曲线到不了一个点击
到不了的地方。没有新命令、没有新错误码：写的还是 `keyframe.set` / `keyframe.remove`，读的还是
`GET /v1/projects/{id}/clips/{id}/sample`。

排窗的方式与柔焦同一条，但**两颗旋钮共用一组断点**：`animation.sharpen_schedule(clip, quantum, limit)`
把 (强度, 半径) 当成一个元组交给 `frame_windows`，任一个变了才换窗，两个都没变的相邻窗合并。各排各的
窗就会出现「导出串了第 k 对阶段、预览却没有第 k 步」那种两端各说各话的时刻，所以这不是省代码而是这条
不变量的唯一写法。只动强度时半径原样读静态字段（`sample` 的回退就是 `base_value`）。

上限是另一个数：`capabilities.limits.sharpen_schedule_segments`（`SHARPEN_SCHEDULE_MAX = 8`）。柔焦一窗
是一条 `gblur`，清晰一窗是 `split` 之外的一对 `gblur` + `blend`。量过（6 秒 320×180，本机 FFmpeg，
libx264 ultrafast）：1 窗 0.47 秒、4 窗 1.35 秒、8 窗 2.53 秒、12 窗 3.68 秒、24 窗 7.18 秒——线性，
每多一窗约 0.29 秒；1280×720 八窗 2.47 秒。八段封顶把一颗动画旋钮收在静态的约五倍以内。于是可见的
代价是台阶更粗：4 秒 25 fps 的片段上清晰是 13 帧一跳，柔焦（24 段）是 5 帧一跳；窗边界只落在整帧上，
曲线落在两个边界之间的跳变要到下一个边界才生效，这一点两端一致。

编译串（`render.focus_stages`）：一次 `split=N+1` 把画面交给链条与 N 条模糊支路，每一窗一条
`gblur=sigma=…:steps=6:planes=7:enable='between(t,a,b)'`，然后 N 个 `blend` 链式相接，
`c0..c2_expr='clip(A+量*(A-B),0,255)'`、`c3_expr='A'`、同一个 `enable` 窗。成立的前提是**关掉的
那一步原样交回第一个输入**：用确定性的片源逐帧比过，`enable='between(t,0.9,1.3)'` 之下，第 5、25、55
帧与「强度 0」的同一张图 hash 一致，只有第 31、37 帧不同——`blend` 与 `gblur` 都带 timeline 支持。
强度为 0 的那一窗根本不串阶段。

预览：`preview_manifest` 的 `clips[*].sharpen` 有两种形状——没有曲线时还是那份 `{id, amount, bbox}`
（一字不变），有曲线时是 `{windows, curve}`：每一窗一个内容寻址的 `<filter>`（同一对数复用同一个
def），`curve` 逐点 `{offset, id, easing}`，强度 0 的那一格 `id` 是 `null`。界面把**外层那道包装**的
整个 `filter` 用 `steps(1, end)` 在这些 def 与 `none` 之间切；CSS 不能只换共享 `filter` 串里的一项，
这也是引擎在有曲线时把静态 `url(#…)` 从 `color_filter` 里拿走的同一个理由。Chromium 量过：
`filter` 在 `none` 与 `url(#id)` 之间按 `steps(1, end)` 逐格切换（第 100 ms 读到 `none`，第 3000 ms
读到 `url("#id")`）。

真实成片：128/192 的二值棋盘（纯黑纯白一夹就顶满，量不出过冲），沿斜坡相邻像素差的均值从 40.8 涨到
82.2，逐窗与「整段都用这一对数」的同路渲染差在 1.22 以内，零强度的两窗读到的就是原片 37.4。门禁：
`tests/sharpenkey_check.py`（阶梯、两端同源、编译串、成片四节）与第 39 个壳层检查
`tests/desktop_sharpenkey_check.ts`（`sharpenFrames`/`sharpenFilters`/`sharpenSteps`、属性行的上限与
名字、九颗旋钮共用同一条判断，以及 `SpatialProperty` 在契约与界面逐字对齐）。能力位
`capabilities.features.sharpen_keyframes`；老引擎不回这一位时，曲线编辑器与那两颗 ◇ 都不出现。


### 1.124 并联的一支可以又是一台混频台（树）

`GradeBranch` 现在收 `GradeParallel`：一台混频台的某一支自己可以再是一台混频台。这不是新的算式——
每通道函数的平均仍是每通道函数，所以一棵树照样塌成每通道一张表，`grade.node_function` 一直是经
`step_function` 解析每一支的，递归本就成立。改动在三处：

1. **界面上的位置从下标变成路径**。`desktop/src/gradeGraph.ts` 的 `mixerAt(node, path)`、
   `mapMixer(node, path, update)` 与 `resolveMixerPath(node, path)` 是唯一的走树处：路径走不通就缩短到
   能走的那一层（换节点、删支之后都这样），而不是把检查器变成空白。检查器里 `current` 就是路径尽头那台
   混频台，所有写入经过一个 `editMixer`，`replace` 只在最外层用一次。
2. **树要有界，而界不再是「不许嵌套」**。`GRADE_MIXER_DEPTH = 3`（一层套一层的混频台层数）与
   `GRADE_NODE_LIMIT = 8`（一个链节点底下包括所有层在内的操作数）在 `GradeParallel.bounded_tree` 里检查，
   两个数都随 `capabilities.grade_limits.max_mixer_depth` / `max_tree_operations` 下发；能力位是
   `features.grade_mixer_trees`。越界是请求校验失败（422），写入没有发生，revision 不动。跨通道的
   `matrix` 与 `lut3d` 仍然进不了支路——那种东西平均不进一张每通道表。
3. **每一层各用各的位置表**。`weights` 与 `blends` 仍按「给就给全」挂在**那一台**上，里层的表不改外层，
   所以「把这一支变成并联」先造一台只装这一支自己的混频台：一支的平均就是它本身，那一步画面不变，
   「+支」才是叠加第二路。

跟着树走还有两处判断：`grade._leaf_operations` 让采样网格接住藏在第二层、第三层里的折点（不然那条陡峭
曲线只能被弦线近似，两端就不是同一张表），`autograde._holds_levels` 让自动调色问「这条链上有没有人已经在
拉黑白场」时把嵌套里的那台也看过。

量过的数（`tests/grade_check.py` 的 `tree_suite`）：里层权重从 2:1 换成 1:2，编译表动 4.5 级；一台只装一支
的混频台与不套时表逐位相同；三层收、四层按 `nest` 拒、一棵树 11 个操作按 `operations` 拒；真实成片六档灰带
[0, 2, 10, 30, 94, 253] 变成 [40, 42, 46, 58, 101, 253]，与独立写出的那份递归参考最大差 2.5 级。界面那侧的
一条路径走法、一处写入口、一份数法由第 40 个壳层检查 `tests/desktop_mixertree_check.ts` 钉住。

同一条链里还可以有多张 3D LUT，一段接一段按链序走（`tests/lut3d_check.py` 的 `chain_suite` 与
`media_suite`）：`grade_stages` 让每张立方自己成一段，`grade_filter` 为每张写一个以表体哈希命名的
`.cube`——同一张表放两次只写一个文件，但导出串里仍是两段。顺序是在成片上量的，用的是两张**不相换位**
的 2³ 置换（红蓝对调、三通道轮转）：纯红 (231, 29, 20) 走 P+Q 得 (27, 230, 18)、走 Q+P 得 (230, 18, 28)，
两者都落在整数置换的理想值 2 级以内；同一张放两次得 (229, 28, 19)，回到原片。夹在两张中间的那条单通道
曲线读的是「前一张换完之后」的那一路通道：夹在中间是 (28, 230, 39)，挪到链首是 (27, 209, 18)。
1.234 起预览那一端每张立方都带着自己的格点进 `preview_manifest`、同一条画布按链序走一遍
（`features.lut3d_preview` 为真）；画不出来的那两种链（文字/嵌套合成、带第二路画面）上，
卡片才写「仅导出生效」并说明原因。卡片上仍没有强度可标——`GradeLut3D` 契约里就没有 `mix` 字段：
只有一端能执行的强度不是强度。

## 1.136 透明通道母版：`transparent` 是请求里的一词，不是滤镜串里的一句承诺

引擎早就会在内部把画面按 alpha 合成（嵌套子合成必须这样），但人想要一张能叠进 AE / DaVinci / 网页
的透明母版时，没有任何公开的入口。现在有了：**预设自己声明装不装得下透明度，请求要，编译器把整条
画面链按 alpha 走完，落盘的 alpha 平面是被量过的**。

- `contracts._preset(..., alpha: bool = False)` 是「装得下」唯一的一处说法。带 `alpha` 的两条：
  `prores-4444-alpha`（mov / prores_ks / profile 4 / `yuva444p10le` / pcm_s24le）与
  `vp9-1080p-web-alpha`（webm / libvpx-vp9 / `yuva420p` / opus 128k / 1920×1080）。
  `capabilities.alpha_presets` 就是这张表筛出来的那份 id 列表，界面那个勾与引擎那句拒绝读的是同一处。
- `RenderRequest.transparent` / `RenderBatchItem.transparent`（默认 `false`）→ `RenderJob.transparent`
  → worker 到点重编计划时按它渲染。`GET /v1/projects/{id}/render-plan?transparent=true` 回包
  `plan.transparent` 原样答，MCP 的 `render_plan` 也把 `transparent` 与 `range` 一起带上（此前它连
  `range` 都没问，于是「干跑是绿的、真导出不是那个东西」有一条真实的路）。
- 拒得干脆：`output_args` 见到 `transparent` 而预设没有 alpha 平面，直接 422
  `TRANSPARENT_NEEDS_ALPHA`，句子把那几条能装的预设念出来（音频预设也算——它根本没有画面轨）。
  这不是「提示一下」：H.264 的 `yuv420p` 里没有地方放 matting，答应了只会悄悄导出一块黑底。
- 指纹与回执：`transparent` 只在为真时进入去重指纹（与 1.39 的 `range` 同一个办法），所以旧
  `request_id` 继续原样重放，而把同一个 id 从不透明改成透明会得到 409。

量过的数（`tests/alphamaster_check.py`，真走 job worker 导出再用 FFmpeg 把 alpha 平面读成灰度字节）：
同一条时间线（0.5–1.5s 一段满不透明、1.6–2.0s 一段 `effects.opacity=0.5`、开头 0.2s 处是空的）——
ProRes 4444 透明母版在空处读到 **0**、片段底下 **255**、半透明那段 **128**；WebM/VP9 那一条是
**0 / 255 / 127**；**同一预设不带这个勾的对照导出三处都是 255**（黑底板是不透明的），这组对照才是
前面那些数字有意义的原因。亮度也一起量了：片段底下 149、空板处 0，于是「alpha 说这里有画」与
「这里真有画」是两次独立的读数。

换交付比例那一半也量过：把一段 180×320 的竖屏片源按 `contain` 进 1920×1080 的透明交付，**pillarbox 的
边读到 alpha 0、画面中间 255**，同一条不透明导出的边读到 255。合成层的补边用的就是 `black@0`，所以
「空白处留空」不会因为改了交付比例而变成一条带底的黑板——这一条是按文件量的，不是按滤镜串推的。

WebM 这一条还量出两件必须写下来的事：**ffprobe 在流那一层报的是 `yuv420p`**（透明度挂在每个 block
后面的附带通道里，容器元数据不反映它），而 FFmpeg 的**原生 vp9 解不出 alpha 平面**
（`alphaextract` 报 `Requested planes not available`），要 `-c:v libvpx-vp9` 才拿得到。复检因此是按
字节量的，不是按 `pix_fmt` 字符串量的——`-auto-alt-ref 0` 那类「据说必须」的开关也不写进参数表，
除非有一行断言能证明它真的改变了落盘的文件。

界面那侧只有一条路：`engine.matteAllowed(preset, audioOnly, requested)` 决定那个勾此刻算不算生效，
勾、待发清单、干跑按钮、开始导出按钮、以及竖屏副本要不要让路，问的都是这一个函数（竖屏那条是
H.264，装不下透明度，于是整条被让掉并在悬停里说清为什么）。第 47 个壳层检查
`tests/desktop_alphamaster_check.ts` 跑真的 `Engine`（假 `fetch` 收请求）断这些行为。

## 1.137 起始时间码：`timecode` 是一词，规矩在引擎，位置按容器读

- `RenderRequest.timecode` / `RenderBatchItem.timecode` / `RenderJob.timecode`（默认 `null` = 不写）。
  写法只有一种：`HH:MM:SS:FF`，分隔符 `:`（非丢帧）或 `;`（丢帧，**只有 30000/1001 与 60000/1001**）。
  判它的是 `contracts.checked_timecode(value, frame_rate)`——一处，`compile_render_plan` 在编计划时问，
  所以干跑、排队、worker 三条路用的是同一条规矩。
- 为什么规矩不能交给 FFmpeg（这台机器上直接调它实测）：`01:60:00:00` 会被进位写成 `02:00:00:00`；
  `01:02:03.04` 的点被当丢帧标记写成 `01:02:03;04`；`1:2:3:4`（一位数字）照收；整数 30fps 上
  `01:02:03;04` 也照样写进 mov。这些一律 422 `TIMECODE_INVALID`，句子点名是哪一段、收到的是几。
  没有画面的预设（mp3/wav/flac）另给 `TIMECODE_NEEDS_PICTURE`。
- `GET /v1/projects/{id}/render-plan?timecode=01%3A02%3A03%3A04` 会按它编译并回 `plan.timecode`；
  MCP 的 `render_plan` 收同名参数并把整串百分号编码（分号在 query 里有歧义）；
  `GET /v1/jobs/{id}` 那份计划也带任务自己的 `timecode`。指纹只在非空时加入这一项，
  所以旧回执原样重放，同一个 `request_id` 换数字得到 409。
- capabilities 下发 `timecode_shape` 与 `timecode_drop_rates`：界面那一栏是纯文本，
  不写第二份正则，也不自己认哪两个率有丢帧码。
- 复检读的是**文件**，而且按每个容器真正存放的位置读：`mov` 与 `mp4` 在视频**流**标签、
  `mxf` 与 `webm` 在**容器**标签，webm 那个键是大写 `TIMECODE`（见 `tests/timecode_check.py`）。
  只按 `pix_fmt`/某一个标签位置去猜，会把「有」读成「没有」。

## 1.138 交付帧率：一张八档闭表，同一条时间线可以交两版

时间线自己的帧率和交出去的帧率是两件事。PAL 机房要 25、NTSC 交 29.97、胶片感要 24／23.976、
高帧率要 50／59.94／60，而剪辑的刻度始终是 `TIMEBASE = 70_560_000`。所以 `output_frame_rate`
只换重采样那一级（`fps=` 与 GOP 的秒数），片段位置、入出点、遮罩与区间仍按时间线的 tick 走。

- 闭表在 `contracts.OUTPUT_FRAME_RATES`：24、23.976（`24000/1001`）、25、29.97（`30000/1001`）、
  30、50、59.94（`60000/1001`）、60。表外一律 422 `UNKNOWN_OUTPUT_RATE`，句子把那八档念出来。
  **数值相等而有理数不同也算表外**：`30000/1000` 不是 29.97，`23976/1000` 不是 23.976，
  收下它们会得到一个「以为是那个率」的文件，所以拒。
- 请求字段：`RenderRequest.output_frame_rate`（`{"numerator":25,"denominator":1}`）、
  `RenderBatchItem` 同名、`RenderJob` 也带一份——worker 到点重编计划时写的还是同一个率。
  旧任务文档没有这一行，读回来是 `None`。
- HTTP 的 query 侧收文本：`GET /v1/projects/{id}/render-plan?output_fps=30000%2F1001`，
  由 `contracts.parse_frame_rate` 交给同一处判断；MCP 的 `render_plan` 收 `output_fps` 字符串并把
  那道斜杠百分号编码。留空 = 不写这个字段 = 跟时间线自己的率一致。
- 计划文档里两个率分开写：`frame_rate` 是**交付**的率，`project_frame_rate` 是**时间线**的率。
  没选的时候计划与 1.138 之前逐字相同（新字段不参与，除非它被用上）。
- `audio-mp3`／`audio-wav`／`audio-flac` 没有画面，帧率无处生效，所以给的是
  `OUTPUT_RATE_NEEDS_PICTURE`——不许收下之后再什么都不改。
- 幂等指纹只在非空时加入这一项：同一个 `request_id` 把 50 改成 25 得到 409，而不是悄悄重放；
  旧回执照原样重放。一次拒绝不写状态、不涨 revision、不排队。
- capabilities 下发 `output_frame_rates`（八档，带 `label`）：界面那颗下拉排的就是这一份，
  抄第二份表的 mutation 会红（`tests/desktop_output_rate_check.ts`）。
- 证据读的是**文件**：同一条两秒时间线交 30／25／23.976 三版，ffprobe 读回
  `avg_frame_rate` 分别是 `30/1`（60 帧、2.000 s）、`25/1`（50 帧、2.000 s）、
  `24000/1001`（48 帧、2.002 s）；一次批量两份文件各自是 `25/1` 与 `30/1`
  （见 `tests/output_rate_check.py`）。

## 1.139 标记区间的那一刀用交付流的帧尺

1.138 之后，`range=marks` 与 `output_frame_rate` 同时出现时切错了段：`render.py` 里那句
`trim=start_frame=…:end_frame=…` 的除数是 `settings.frame_ticks`（**时间线**的一帧），而送进这一刀的
流已经按**交付**率归一过了。实测（30 的线标 1..2 秒、按 25 交）落盘 20 帧绿 + 5 帧蓝——入点前少一截、
出点后多露一截，`plan.range.seconds` 却还写着 1.0。按 23.976 交是 18 帧绿 + 6 帧蓝。

- 现在的除数是交付流的帧长（`TIMEBASE × 分母 ÷ 分子`，八档都整除），**两头都向上取整**：第一帧不早于
  入点，最后一帧的起点仍早于出点（`end_frame` 是开区间）。没换交付率时帧号与 1.139 之前逐字相同
  （30 的线标 1..2 秒仍是 `start_frame=30:end_frame=60`）。
- 交付帧率比时间线粗、而标记窗口又短到不足一帧交付时，两头会撞到同一个帧号；那一刀被撑成**一帧**
  而不是交出一个零帧的切口（实测：60 的线标第 1..2 帧、按 25 交 → `start_frame=1:end_frame=2`）。
- 声音那一头本来就用秒（`atrim=start=1.000000:end=2.000000`），三个交付率下同一句——图与声不必共用
  一把帧尺，但必须说同一个窗口。
- 证据读的是**内容**：每秒一个纯色的三秒源，标 0..1 与 1..2 秒两个窗口，按 30／25／23.976 各交一份，
  逐帧缩成 1×1 读 RGB——窗口里一帧都不许多带别的颜色（实测 30/1 30 帧全绿、25/1 25 帧全绿、
  24000/1001 24 帧全绿；开头那窗全是红）。见 `tests/delivery_range_check.py`。

## 1.140 时间码的尺子跟着交付率走

1.137 定这条规矩的理由是「FFmpeg 会收下并悄悄改写人打的数字」。1.138 之后「一秒有几帧」有了两个
答案，而 `checked_timecode` 还在按**时间线**那一档判，于是同一件事从另一头回来了。

- 实测（本门禁里由 FFmpeg 自己作证，不经过引擎）：一条 25 fps 的流上写 `-timecode 00:00:00:29`，
  它**收下**，落盘读回来是 `00:00:01:04`——那一串被按 25 重数了一遍。
- 现在判它的是**这一条交付画面的帧率**：`compile_render_plan` 先把 `output_frame_rate` 判过，再把
  那档率交给 `checked_timecode`；没选交付率时与 1.139 之前完全一致（时间线那一档）。
- 帧号上限与丢帧码（分号）都跟着它：29.97 的线按 25 交写 `00:00:00;15` 被拒（25 的流上没有丢帧这
  回事），30 的线按 29.97 交写同一串被收下。反面案例同样修好：25 的线按 30 交写 `00:00:00:29` 现在
  收下——文件里确实有第 29 帧。
- 拒绝的句子点名是哪一条率：`这一条画面的帧率是 25/1，帧号只能 00–24，收到 29`。
- 界面那两处必须说同一件事：提示从「这条时间线的帧率」改成「这一条交付画面的帧率」，那颗
  「分号可用」的判断从 `effectiveRate = sendFps ?? timelineRate` 来。旧那句话由门禁要求**消失**
  （`tests/desktop_timecode_rate_check.ts`）。
- 落盘证据：按 25 交、写 `00:00:00:24`，`ffprobe` 从 mp4 的视频流标签读回来还是 `00:00:00:24`，
  `avg_frame_rate` 是 `25/1`；一次被拒的提交不写 revision、不排队任务。

## 1.142 图像序列交付（OpenEXR / DPX）

预设表多两条，交付物从「一个文件」变成「一串文件」，所以接口上有五处要说清楚：

- `GET /v1/capabilities` 的 `sequence_presets` 点名哪几条是序列（`["exr-sequence", "dpx-sequence"]`），
  与 `alpha_presets`、`output_frame_rates` 同一性质：界面与 Agent 读的就是这一份，不许自己列。
  这两条预设的 `audio_codec` 是空串——闭表里只有序列可以填空（`tests/format_check.py` 钉住这一点）。
- 渲染计划（`GET /v1/projects/{id}/render-plan` 与提交后的 `plan`）多两个键：
  `sequence`（这一条交出的是一串文件）与 `audio`（这一条带不带声音）。`argv_preview` 里
  序列那一条是 `-c:v exr -pix_fmt rgba64le -an`，且**没有** `-map [aout]`。
- `filename` 仍要带容器后缀（`.exr`／`.dpx`），否则契约层 422 点名要的后缀。作业存下来的
  `filename` 与 `output_path` 是**名字模板**：`全片.%06d.exr`。落盘得到的是目录 `全片/`，
  里面是 `全片.000001.exr` 起的一串；`output_size_bytes` 是这一串的总和。
- 起始时间码对序列是 422 `SEQUENCE_NEEDS_CONTAINER`（不是静默丢掉）：一串图像文件没有容器可以挂
  时间码，帧号就是位置。拒绝发生在编译阶段，所以**一个文件和目录都不会被建出来**。
- 复检换了算法：序列按**文件**点货——帧数等于「这段时长 × 交付率」，编号从 000001 起连续，
  首尾两帧先用 ffprobe 认出是画面、再用 `ffmpeg -f null` 真解码一遍。任务消息因此写
  「已输出 全片/（复检：共 90 帧，从 全片.000001 起连续编号，首尾两帧…都解得开）」。

实测口径见 `tests/sequence_check.py`（套件第 96 项）：三秒红/绿/蓝交 EXR 是 90 个文件、conform
回来 30 红 / 30 绿 / 30 蓝；1..2 秒的窗口按 25 交 DPX 是 25 帧全是绿；带空洞与半透明的时间线交
透明 EXR，逐帧 alpha 读回 0 / 255 / 133，而关掉「背景透明」的同一条是 255..255。


## 1.145 第二路画面输入接进分层合成（`COMPOSITE_NEEDS_CUT` 退场）

- 上面 1.144 那条「多条画面轨合成的工程拒 `COMPOSITE_NEEDS_CUT`」在本版**整条撤销**：分层那条 Builder 里
  每个片段本来就有自己的一条链（编译成 `[layerN]` 再 overlay 到 `[base]`），所以「这条链进来的那幅画」
  在分层里同样定义得清楚。代号、`engine.ts` 里那句中文话、门禁与壳检的相应断言一起撤走——规则变了
  却留着老断言，它只会变绿或变含糊。留下来的只有「并联的某一支里放不进这条边」，那一头由
  `GradeBranch` 类型表单处口径拦（表里没有 composite，`extra="forbid"` 就是 `INVALID_REQUEST`）。
- 语义与 cut 那一路逐字相同：`mix=0` 逐值等于这条链的输入、`mix=1` 等于按 `mode` 相合的结果、
  中间是两端的中点；这一级在链里的位置不影响结果。
- 分层那一路多守一件只有字节能回答的事：相合**不许动 matte**。融合点放在遮罩与不透明度之前，
  两条支共用同一份几何，原图那条支的 alpha 用 `alphamerge` 盖回相合的结果，于是透明母版里
  `mix` 拧到任何一端，交付文件的 alpha 都与不挂这一级时逐帧相同。实测（片段不透明度 0.5、
  prores-4444-alpha）：灰度 130 / 183 / mix=0 130 / mix=1 221（公式 220）/ mix=0.5 175，
  五份 alpha 全是 133；冻结引擎那一路 192 / 236 / 131，三份 alpha 133。

## 1.144 调色链的第二路画面输入（节点 `composite`）

- 契约新增一种节点：`{"kind":"composite","mode":<8 种混合方式之一>,"mix":0..1,"enabled":bool}`，
  写在 `clip.color.grade` 那条列表里，命令仍是普通的 `clip.color`（HTTP 与 MCP 都不加新 op、新路由）。
- 语义只有一句：**这一级把「链调完的结果」与「进来的那幅原图」相合，它在链里的位置不影响结果**。
  `mix` 是那层的权重（0=只看原图，1=只看相合结果），`mode` 是相合方式。
- 一条链最多一条这样的边：第二条拒 `COMPOSITE_LIMIT`（422，点名两条出路）。
  走到分层合成的工程拒 `COMPOSITE_NEEDS_CUT`（422，出路：把没调色的那份放另一条画面轨上、
  用那条轨道的混合方式相合，或者把这一级去掉再导）。两句都点名出路，都不涨 revision、不排队任务、不落文件。
- **这一句拒绝点名的是真的原因**，不是笼统的「你的工程是合成」：走到分层的原因有十条
  （要透明通道 / 没有画面轨 / 多条画面轨 / 轨道混合方式不是 normal / 文字或图像序列素材 /
  挂了遮罩 / 有转场 / 有不透明度淡入淡出 / 有画面动画关键帧 / 改了位置・缩放・旋转・不透明度），
  回执把它们逐条交回 `details.reasons`，句子按「因为：…；…」念出来，属性名与素材类别都念中文。
  实测：单条画面轨上只改一次不透明度，`details.reasons` 就是
  `["片段 c 改了「不透明度」"]` 且句子里**没有**「多条画面轨」；同一条工程改要透明母版交，
  两条原因同时在场。
- 这一条边只能挂在**链的最外层**：`GradeParallel.branches` 收的是 `GradeBranch` 那张类型表，里面没有
  `composite`，所以把它塞进并联的某一支是 `INVALID_REQUEST`（422，pydantic 的 `extra="forbid"` 拦下 `mode`）。
  界面这一侧同一件事也只有一处口径：这一级的「方式／权重」住在 `OpFields`（串行节点的旋钮都从那里出去），
  不在 `MixFields`（只挂在并联节点与它的支上）——写在错的一侧，引擎与契约都还全对，屏幕上就是没有这两个控件。
- 预览这一端（1.193 起会画）：`capabilities.features.grade_composite` 与 `composite_preview` 都为真。
  这一级仍带 `preview:false`，也照旧从 `preview_grade` 那份**滤镜**阶段表里整条丢掉——浏览器的滤镜链
  没有第二个画面输入，混进 `color_filter` 就等于让「已调色」那一层自己与原图相合两次，导出可没有这一份。
  它改从 `preview-manifest` 每一行的 `composite`（`{mode, mix, paintable}`，由
  `animation.composite_row` 一处算出）出去：底层画原图，上面套一个 `opacity=mix` 的隔离容器，容器内
  「已调色」作底、原图按 `mix-blend-mode` 相合，展开正是导出那两步的 `(1-mix)·raw + mix·mode(graded, raw)`。
  `normal` 那一档要交换容器里那两层的次序（判断只在 `effects.compositeSwap` 一处）：FFmpeg 的 `normal`
  交回**第一个**输入、CSS 的交回**上面那一层**，与 1.189 为图层量过的那条是同一件事。
  `paintable` 只由素材是什么决定（图像真、视频假、素材引用悬着也假），界面不许自己再问第二遍——
  那是第二个判断，迟早与引擎不一致。卡片因此是两句各自属实的：图像那一段监视器会画，视频那一段还不画。
- 导出这一端编成滤镜图里的两刀：`split` 出原图那一路（只做同样的适配、不调色），
  三路各自 `format=gbrp` 后 `blend=all_mode=<mode>`，再 `blend=all_mode=normal:all_opacity=<mix>`。
  这两段都是量出来的必要性：YUV 平面上直接 screen 会把中性灰改成品红，单个 `all_opacity`
  在非 `normal` 方式下会把「0 权重」谎报成另一幅画。
- 干跑（`GET /v1/projects/{id}/render-plan`）的 `argv_preview` 里能看到 `split=` 与两段 `blend=`；
  工程里没有这一级时图里一个 `blend=` 都没有（既有交付的输出逐字不变）。

## 1.151 交付色彩标记：`colour_tag` 是一词，标记与折叠必须一起写下

`RenderRequest.colour_tag` 声明的是**这一条交付的画面是什么颜色**：`RenderBatchItem` 同名、
`RenderJob` 也带一份，三处都是 `Annotated[str | None, Field(max_length=24)] = None`。留空就是
容器上一个色彩标记都不写——那是 1.151 之前所有交付的含义；显式写 `null` 也是同一件事，所以新
客户端多带一个空键不会把老回执劈成两份。这一词的落点有两处，只写其中一处就是谎话。

- 为什么「只写标记」是谎话（本机随包 FFmpeg 6.1.1 实测，`tests/colour_tag_check.py`）：
  `-colorspace bt709` 往容器里写一个名字，一个像素都不动。RGB→YUV 那一折发生在**编码器的 swscale
  上下文**里，而它用的是 **BT.601**：夹具里那一格实测是 RGB `(126,63,30)`，不带标记交出去的
  `h264-720p-web` 折成 YUV `(83,104,158)`——正是 601 的预测；709 的预测是 `(80,107,157)`。两个
  预测都由门禁拿公开的系数另算一遍再比，不从引擎导入，否则填错矩阵的代码会跟自己的断言对上。
  所以在老那张图上写 `bt709`，就是对着一张 601 折出来的画面宣称另一组系数，而容器是下游唯一
  读得到的地方。
- 这一档改的两处，缺一个都不成立：① 画面链的最后一步从 `format=<预设像素格式>,settb=AVTB`
  变成「先按预设自己的位深摆成平面 RGB（`format=gbrp`／`gbrp10le`），再 `zscale=matrix=709:range=tv,format=<预设像素格式>,settb=AVTB`」——折叠交给 `zscale` 在图里
  做，因为 `-pix_fmt` 那一步落在编码器的 swscale 上下文，那里读不到矩阵选项；② 容器写
  `-color_primaries`／`-color_trc`／`-colorspace`，三个值取自表里的 `primaries`／`transfer`／
  `matrix`。不声明时 argv 与滤镜串跟 1.151 之前逐字相同（这一项不参与，除非它被用上）。
- 两条 FFmpeg 的事实是拿突变试出来的，记在这里免得下一次重新试：`zscale` **没有** `format`
  选项，像素格式要另挂一级 `format=`；`zscale` 的矩阵表里**没有** `601` 这一拼，601 族的值是
  `470bg`／`bt470bg`／`170m`。`range` 也不能不说：留在 `input` 会把 RGB 源的满量程一路带过去，
  有限量程的样本交回来是 `yuvj420p` 加 `color_range=pc`——那是同一类谎的第二句容器声明。
- 表在 `contracts.OUTPUT_COLOUR_TAGS`，一行一档，七个键：
  `{id,label,primaries,transfer,matrix,zscale_matrix,zscale_range}`；可点的名字由它派生
  （`COLOUR_TAG_CODES`），同一件事不写第二遍。**今天这张表只有一行**：`bt709`，
  label「BT.709（高清显示端交接母版）」。表外一律 422 `UNKNOWN_COLOUR_TAG`
  （判在 `colour_tag_row`，也就是编计划那一步，干跑、排队、worker 三条路同一条规矩），
  details 带回 `colour_tag` 与 `known`（实测 `p3-dci` 回 `known == ["bt709"]`），
  句子把可选的那几档念出来、再说一句「或者干脆留空」。
- 带不出去的情况各点名拒绝，不静默收下之后再什么都不改；连同上面那句 `UNKNOWN_COLOUR_TAG`，
  四处都是 422：
  - `COLOUR_TAG_NEEDS_CONTAINER`（`colour_flags`）——`exr-sequence`／`dpx-sequence` 交出的是一串
    图像文件，没有容器 VUI 可以挂这三样；EXR／DPX 自己带的是逐帧的像素格式说明，不是这三样。
    details 带 `preset_id` 与 `colour_tag`。
  - `COLOUR_TAG_NEEDS_PICTURE`（`colour_flags`）——`audio-mp3`／`audio-wav`／`audio-flac` 只有
    声音，标记是给画面写的。这一问排在 `output_args` 最前面，所以后面那几条先 `return` 的分支
    也照样挡得住。
  - `COLOUR_TAG_NOT_WITH_ALPHA`（`compile_render_plan` 分层那一路；**1.154 起这一条已删除**）——透明母版是把 rgba 一路带到
    编码器才折的，用哪一组系数折不由这条图说，容器写任何 matrix 都会与画面不符；句子给两条出路：
    交不透明的那份并带上标记，或者这一份留空。同一预设（`vp9-1080p-web-alpha`）不勾透明时那条
    alpha 链一字未改，仍带 `format=rgba[vout]`。
- `plan.colour_tag` 也写进 dry-run 那份文档：`RenderPlan.summary` 与 `as_dict()` 各多这一个键，
  没声明时是 `null`。读计划的人要能从计划本身看出这份文件会带那三样容器标记，而不是从自己发出去
  的那个字段猜——与 1.136 的 `transparent`、1.137 的 `timecode` 同一条规矩。
- HTTP：`GET /v1/projects/{id}/render-plan` 多一个可选 query `colour_tag`；`POST …/renders` 在
  请求体里收它，`POST …/renders/batch` 每一项各收自己那一个答案。MCP 的 `render_plan` 工具多同名
  参数，非空才拼进 query。界面留空时连这个键都不发（`tests/desktop_colour_tag_check.ts` 钉住这一
  条）——契约是 `extra="forbid"`，多发一个不认的键会让 1.151 之前的引擎整条拒收。
- `GET /v1/jobs/{id}` 在任务还排着的时候回的是任务自己那份计划（同一个 `plan_for`，带任务那一词），
  所以 `plan.colour_tag` 念的是这一条交付声明过的话；两份并排实测：带标记那条排着时读回来
  `plan.colour_tag` 与 `job.colour_tag` 都是 `bt709`，落地后任务文档存的仍是 `bt709`，
  未标记那条 `job.colour_tag` 是 `null`。
- 回执：指纹改由模块级纯函数 `jobs.request_fingerprint(project_id, request)` 算，`colour_tag`
  **只在被点名时**加入那个数组。所以 1.151 之前写的未标记回执原样重放——门禁把 1.150 那次提交
  自己的 `canonical` 串与它的 sha256 钉成两个常量来比，不是让 1.151 重算一遍再点头；显式 `null`
  仍算同一份。同一个 `request_id` 改要带标记是 409 `IDEMPOTENCY_CONFLICT`：那是一次不同的交付，
  不许悄悄回一份已经排队的旧文件。一次拒绝不写状态、不涨 revision、不排队。
- capabilities 下发 `output_colour_tags`（整张表原样交出去，与 `alpha_presets`、
  `sequence_presets`、`output_frame_rates` 同一性质：界面与 Agent 读的就是这一份，不许自己列）与
  `features.colour_tag_delivery=true`。工程 schema 仍是 v17（这一轮没动），`APP_VERSION` 是
  `1.151.0`。界面那一栏一个值都不抄：`tests/desktop_colour_tag_check.ts` 逐行扫 `desktop/src`，
  并断言界面连 `primaries`／`transfer`／`matrix` 都不读——读了就是界面在算色彩数学。
- 为什么要写这三样：带标记的母版靠的是**文件自己那一句自我介绍**——DaVinci 或另一个 Agent 拿到的
  是这个文件，不是这一次对话。实测 1.150 的 `colortags.detect_space` 把 AgentCut 自己交出的那份
  带标记母版认成 `rec709`（于是 `clip.color_manage` 的 `auto_source` 接得上自己导的片），同一
  夹具不带标记那份回 `no_color_tags`；ffprobe 从带标记那份读回 `color_space`、`color_primaries`、
  `color_transfer` 三样都是 `bt709`，画面格式仍是 `yuv420p`。
- 边界说清楚：**1.153 起这张表有三档**（`bt709`／`bt601`／`bt2020`），1.156 起是四档（多一条 `p3-d65`），加一档不是界面的事。它是 `OUTPUT_COLOUR_TAGS` 这张
  契约表多一行，连带要定 `zscale` 的那两个拼法，且 `COLOR_TRANSFER_TAGS[row["transfer"]]` 必须
  仍在 `COLOR_SPACES` 里（capabilities 套件钉住这一条：标记承诺了一条引擎算不出来的曲线，比少一档
  更糟）。面板那边什么都不必改，它排的就是引擎下发的那张表。
- 证据是十二个套件：capabilities／compile／pixels／round trip／refusals／http／receipts／tiers／flat／cube／ramp
  （`tests/colour_tag_check.py`），加界面那一份 `tests/desktop_colour_tag_check.ts`。


## 1.153 交付色彩标记的第三档：换基色在图里做，判它兑不兑得了现要用纯色

- 第三行 `bt2020` 比前两档多两件事：图里多一站立方体，容器多一句基色声明。立方体由
  `gamut.delivery_cube` 算——两端基色的九个系数出自 `gamut.primaries_matrix`（色度坐标那条独立路
  已由 `tests/gamut_check.py` 量过），曲线出自 `gamut.bt709_eotf`／`bt709_oetf`，即容器声明的那一档；
  文本按 `.cube` 既定次序（红变化最快）写成 33³ 张格，`render.primaries_shift_stage` 把它落成作业
  目录里的 `primaries-<sha16>.cube`，图里那一站是 `lut3d=file=…:interp=tetrahedral`。旁路文件走的是
  oversized filter graph 早就在用的 `plan.text_files`，所以同一次导出里两张一样的表只写一份。
- 为什么不用 `colorchannelmixer`：那一站乘的是**存储值**，而基色转换必须在线性光里做。1.152 实测
  「进线性 → colorchannelmixer → 回 709」这一对在 16 位上仍与标准算式差 3–7 阶。
- `capabilities.output_colour_tags` 与 `output_colour_tag_presets` 一起下发，后者每一档给的是
  「这一档带得出去的预设 id」。四档给的是**同一份名单**（15 条有画面又有容器的预设）：能不能挂标记
  只由容器与画面说话。界面 `colourTagAllowed` 与引擎 `render.colour_flags` 读同一份判断，因此
  界面不存在「这一档在这条预设上能不能兑」的第二份算法。
- 拒绝仍是那三条，且都在**能问出这句话的地方**问：图像序列 → `COLOUR_TAG_NEEDS_CONTAINER`
  （EXR／DPX 没有容器 VUI），纯声带 → `COLOUR_TAG_NEEDS_PICTURE`（标记是给画面写的），
  透明母版当年 → `COLOUR_TAG_NOT_WITH_ALPHA`（1.154 起不再拒，见本节末）（rgba 一路带到编码器才折，用哪组系数折不由这条图决定）。
  `COLOUR_TAG_NEEDS_WIDE_RASTER` 这一条**已删除**：撑它的两个数事后证明是量具的账而不是标签的账
  （详见 `docs/optimization.md` 的 1.153 一节），换成由 `tests/colour_tag_check.py` 的纯色档正面判。
- 判这一档真假的两把尺，各判各的：
  1. `flat_suite`——一句基色声明所指的是**一个颜色**，所以拿贴着 709 边界的暗饱和纯色去量（三片：(20, 5, 5)／(0, 128, 0)／(5, 5, 20)）：每一种画面格式
     取一条代表，按容器那四样标记解回来，判据 4 阶（实测 1 阶）。
  2. `ramp_suite`——立方体是插值的，所以格与格之间也要量：图案是 2×2 的块（与最粗的那一档抽样对齐），
     判据是与同一条预设上「不带转换那一档」的差（实测多 5~6 阶，判据 7 阶）与绝对 9 阶。哪一份像素
     量得动由控制档当场决定，量不动的就明说并交给前一把尺。
  3. `cube_suite`——格数不经过 FFmpeg：格点值与独立参考比（0.04 阶）、相邻格中点与两端平均之差算插值
     地板（0.17 阶），判据 0.5 阶。渐变那把尺看不见这件事（65³ 与 9³ 在它上面量到的一模一样），所以
     这件事必须由数学判。
- 这一档（P3-D65）当时**宁可空着**，写下的数是「蓝通道被夹掉 30 阶」。1.156 重算发现那一句
  把方向记反了：那个动作属于 P3→709 那张收窄的表（最小系数 -0.22494，33³ 的 35937 格里
  16412 格出界），而交付要乘的 709→P3-D65 九个系数全非负、同一张格子一格不出界。这一档
  已于 1.156 交出，见下面那一节。

## 1.154 透明母版也可以声明色彩：折叠改由图里那一趟做

- `transparent=true` 与 `colour_tag` 从「二选一」变成「可以同时」。收尾那一段现在是有条件的两条：
  带标记时 `format=gbrap10le[,lut3d=file=primaries-…],zscale=matrix=…:range=tv,format=<预设 yuva>`，
  不带标记时仍是 `format=rgba`——**未标记那一路的编译串一字未改**，老工程与老回执不受影响。
- 为什么以前必须拒：`format=rgba` 交给编码器后，RGB→YUV 那一折发生在编码器的 swscale 上下文，
  它用的是 BT.601（量的：`yuva=(329,417,632)`），容器上写 `bt709` 就是对着一张 601 折出来的画面宣称
  另一组系数。`zscale` 接**带 alpha 的平面 RGB** 时会照声明的系数折、并把 alpha 平面原样带走，
  所以这句话现在能兑现：ProRes 4444 与 VP9/webm 两条透明预设都量过（色度逐位或差 1 阶对上 709 预测，
  alpha 那一格 128 → 129 / 130）。
- 量 alpha 必须用对尺：`ffprobe` 对 VP9 的 matte 报 `yuv420p`，原生解码器 `alphaextract` 会失败；
  要点名 `-c:v libvpx-vp9` 再取平面（`tests/alphamaster_check.py` 与 `tests/colour_tag_check.py`
  的 `alpha_suite` 都是这一把）。
- 拒绝剩下两条：`COLOUR_TAG_NEEDS_CONTAINER`（EXR／DPX 序列没有容器 VUI）与
  `COLOUR_TAG_NEEDS_PICTURE`（mp3／wav／flac 没有画面）。`COLOUR_TAG_NOT_WITH_ALPHA` 已从引擎与
  渲染层删除，界面那三条布尔收成两条（`colourTagAllowed(preset, audioOnly, isSequence, requested)`）。


## 1.156 交付色彩标记的第四档：P3-D65，以及一次「把自己上一轮的实测结论推翻」

- 这一档与 `bt2020` 同形：图里多一站引擎自算的 33³ 立方体（`gamut.delivery_cube`，
  `lut3d=file=primaries-<sha16>.cube:interp=tetrahedral`），容器多一句基色声明；差别只在两端——
  `shift_from=rec709`、`shift_to=p3-d65`（`gamut.PRIMARIES` 新增那一档：P3 原色
  `0.680,0.320 · 0.265,0.690 · 0.150,0.060` 配 D65 白，曲线名写 `rec709`，因为它配的就是容器声明
  的那一条），折叠与曲线照旧是 BT.709 那一组。
- 标签写的是 `smpte432`／`bt709`／`bt709`（`-color_primaries`／`-color_trc`／`-colorspace`）：
  随包 FFmpeg 6.1.1 实测 mp4、webm、MXF 三份都原样读回那三样。基色换到 P3 而折叠仍按
  0.2126/0.7152/0.0722 折——这不是省事，是这一条链真做的事，标签只写真做了的事；一台老实的
  观看者按这四样解回来，落到的是源色（见下一条），所以这句话是可兑的。
- 量到的数（`tests/colour_tag_check.py` 当场重量）：素材那一格 (126,63,30) 挂 `p3-d65` 交出
  YUV (80,110,152)，与「先按 709→P3-D65 换基色、再按 BT.709 系数折」独立算出的 (80,110,152)
  逐位相同；按标记解回 (127,63,29)，与源差 (1,0,1)。纯色尺 `flat_suite`：10 位三份最差 1 阶、
  8 位 4:2:0 与 VP9 那两份 2 阶（判据 4 阶），同一些像素的控制档自己是 0~1 阶。渐变尺
  `ramp_suite`：最大 7 阶（判据 9 阶、比控制档多 7 阶）。立方体尺 `cube_suite`：这一档格点
  与独立参考差 0.01 阶、插值地板 0.06 阶。
- **上一轮那句「P3-D65 要做真正的色域压缩」是怎么错的**：那一次量的动作属于反方向那张表。
  两张表互为逆阵，各自都自洽——纯色往返、恒等控制组都查不出来，与 1.153 那对调了指数的两条
  BT.709 曲线是同一族缺陷。这次没有靠「再想一遍」翻案，靠的是把未钳位的算式摆到台面上：
  `709→P3-D65` 的九个系数是 0.82246/0.17754/0、0.03319/0.96681/0、0.01708/0.07240/0.91052，
  全非负、每行和 1，33³ 的 35937 格没有一格掉出 [0,1]；反向那张最小系数 -0.22494，同一张格子
  有 16412 格出界。几何上也只有这一个答案：两档同蓝原色、同 D65 白点，P3 只是把红与绿往外推，
  所以 709 的整张三角形本来就在 P3 之内。
- `cube_suite` 因此加了双向判据，而且两句必须同时成立：这一档的前向必须**一格不出界**（这才是
  「不需要压缩」这句话的可量版本），它的逆必须**真出界**（否则前向那句对任何矩阵都成立，锚就
  在空转）。判「出界」的松弛度取抄写值自身的 `max|行和-1|`（P3 那张是 2e-05），不是拍的；
  方向用反是 0.22 那个量级，松弛度挡不住它，也不该挡住。
- 加一档动的四处清单（每一处都是「写死的清单必须跟着新能力改」那条老规矩）：
  `capability_suite` 的「基色表名 → 容器枚举名」清单认 `p3-d65 → smpte432`；
  「未知标记」那句拒绝点名的字面量清单走到四档；`packed_engine_surface_check` 那份档位清单
  加一行并新增「档位清单必须等于契约表」的覆盖断言；`flat_suite` 与 `refusal_suite` 原来把
  `bt2020` 写死，现在读 `SHIFT_CODES`（表里所有带 `shift_to` 的行），所以第二条宽色域不可能
  挂在表里而没人量。
- 透明母版（`alpha_suite`）现在逐档走一遍：ProRes 4444 挂 `p3-d65` 交出
  yuva=(316,440,607,516)，8 位尺那一格 (79,110,152) 与这一档的独立预测差 **0**，按自己那四样
  标记解回 (125,62,28)（authored (125,62,29)），alpha 129；VP9/webm 那一份 (79,110,152) 同样差 0、
  alpha 130；`bt2020` 那两格差 1。宽色那一档在透明母版上另带两句判据：编译串里必须有 `lut3d`
  那一站，而且必须比「不换基色直接折」那个预测明显更近（一张恒等立方体蒙不过去）；引擎那张
  旁路立方体在门禁这一侧也要落盘，不然 FFmpeg 只回「No such file or directory」。
- 界面一字未改：那一栏排的就是 `capabilities.output_colour_tags`，档名、标签、能挂哪些预设
  全从引擎那张表下来（`tests/desktop_colour_tag_check.ts` 逐行扫 `desktop/src`，标记值出现的
  清单仍是空表）。

## 1.157 多目标遮罩跟踪：一组目标一次跑完

`POST /v1/projects/{project_id}/mask-track`（MCP 的 `mask_track`）取代了每片段那一条
`/clips/{clip_id}/track`。载荷是 `{request_id, expected_revision, sequence_id?, targets, dry_run?}`，
`targets` 有 1..`capabilities.limits.track_max_targets`（契约 `TRACK_TARGET_LIMIT`）项，每项写着
`{clip_id, from_ticks=0, frames=120(2..900), search_radius=10(2..16), estimate_scale=true,`
`max_gap_frames=60(0..240), reacquire=true, merge=true}`。`sequence_id` 留在请求一级：一个批次只落在
一处合成里，所以整组共读它，目标不许各自挑合成。

回执里的 `tracking` 变成 `{target_count, decoded_passes, frames_decoded, targets: [...]}`。每一项就是
1.85–1.88 那一份单目标回执（`sampled_frames`、`tracked_frames`、`predicted_frames`、
`reacquired_at_ticks`、`gap_closure`、`scale_estimated`、`budget_frames`、`kept_frames`、`seam_jump`、
`lost_at_ticks`、`points` 都在），另加 `clip_id`、`target_position` 与 `shared_decode`（这一项是否搭了
前面某个目标已经读好的那一趟）。`decoded_passes` 是真正解码了几趟：量到的两份都写在
`tests/multitrack_check.py`——同一段窗口的两个目标是 1 趟 60 帧，两个不同窗口的是 2 趟。

拒绝都点名，而且整组一起站住：同一段排两个目标回 422 `MASK_TRACK_DUPLICATE`（`details.clip_ids`）；
某一段的曲线预算装不下下一帧回 422 `MASK_TRACK_BUDGET`（`details` 带着 `clip_id`、`target_position`
和原来那五个数）。两种判定都在解码之前完成，revision 一步不涨，另一段一条曲线都不许多写；把挤不动
的那段从组里拿掉，同一份请求照旧交得出整条路径。写入仍是 N 条普通 `clip.mask_track` 命令进一个
`EditBatch`：一个版本、一步撤销整批退回，reducer 那一站一字未改。

界面：多选里遮罩区会出现「跟踪所选 N 段」，每段量几帧仍由 `effects.ts` 的 `trackGroup` 逐段去问
`trackWindow`（一处判断，太短那段沿用同一句话），段数上限来自 `capabilities.limits.track_max_targets`。
没有可动画遮罩的段被跳过时报出几段，而不是让整组看起来像「都跟过了」。
## 1.158 按表换基色：`gamut_matrices` 的那九个数有了消费者（工程 schema 仍 v17）

1.146 把基色转换表交出去（六档、每档九个系数加两端传递函数名），1.158 给它接上界面那一颗按钮，
**没有新命令、没有新字段、没有 schema 变更**：折进来写的是早就存在的 `clip.grade`，节点是早就存在的
`matrix`，位置是 `clip.color_manage` 那一对的中间。

选择这一档的候选名单来自 `capabilities.gamut_matrices`，那九个系数也来自同一处——`gamut.primaries_matrix`
是唯一的算法所有者。因此界面不许出现档位名、系数或任何兜底数字，`tests/gamutfold_check.py` 把这条
字面量纪律逐字数过；`desktop/src/gamutFold.ts` 是唯一的判断处（哪一格能放、什么时候不能、说完还指
一条走得通的出路），`tests/desktop_gamutfold_check.ts` 判那四种场合的正反两面。

那一次点击交的是**一个批次**：先 `clip.color_manage` 套上「进线性 / 出线性」那一对（若还没套），
再 `clip.grade` 整条链交回，落到工程里的 `[transfer, matrix, transfer]` 与能力表那九个数一字不差，
版本只涨一格。被引擎拒掉的那一种（系数越过 `matrix_limit`）当场 422、版本不涨、链子留空——上面那些
「收下了」才不是因为没在检查。

边界照实说：只换基色，不替你判断素材的曲线（那是 `clip.color_manage` 与 `auto_source` 的事）；
没套色彩管理的链子上这颗按钮不亮；那一格里已经有人手工填了九个数时界面不覆盖，只把出路说出来；
老引擎不回 `gamut_matrices` 时这一档名单是空的，按钮不亮并说明「这一版引擎没把表交下来」。

## 1.159 工程级基色：`working_primaries`（工程 schema v18）

新字段一个：`SequenceSettings.working_primaries: str = "rec709"`。**没有新命令**——它写在
`POST /v1/projects`（新建时可给）或 `POST /v1/projects/{id}` 的 `settings` 里，走的就是原来那条元数据
更新（一次一个 revision，撤销即回）。Agent 与界面走同一条路由、同一处校验。

可选名单只有一个主人：`gamut.WORKING_PRIMARIES`，由 `gamut.PRIMARIES` 现算——「曲线恰为 rec709 的那几档」，
本轮量到 4 档：`rec709`、`rec601`、`rec2020`、`p3-d65`。**`display-p3` 不在名单里**，因为它的传递特性是
sRGB 而不是 rec709，而这一档只管原色不管曲线（素材自己从哪档来仍是 `clip.color_manage` 与 `auto_source`
的判断）。名单随 `capabilities.working_primaries` 下发；`SequenceSettings.known_working_primaries` 拒名单外
的名字，句子把名单整个念出来（422 VALIDATION，revision 不涨、不落半个字）。

预览这一端：`GET /v1/projects/{id}/preview-manifest` 里每段 `grade.stages` 在链子最后多出**三段**——
`{"type":"lut"}`（每通道表，把信号抬进线性光）→ `{"type":"matrix","m":[九个数]}` → `{"type":"lut"}`
（落回信号）。九个数是 `gamut.primaries_matrix(工程档, "rec709")`，两张表是
`gamut.transfer_tables()` 按同一条 bt709 曲线切的 256 格——与 `gamut.delivery_cube` 那张立方体同一条
函数。这不是可选的写法：把九个数直接乘在存储值上（也就是只交一个 `matrix` 阶段）与真折叠最坏差 71 阶，
`tests/workingprimaries_check.py` 的 `fold_math_suite` 在 73,824 个颜色上把这两个数当场量出来。三段与
精确折叠最坏差 1 阶（256 格的插值地板）。默认档（`rec709`，或整个键不出现）一条不加，回包与 1.158
逐字节相同；没挂调色链的那一段在宽档工程里也会多出这三段。`grade.id` 按加了这三段之后的整份阶段列表
重算——浏览器认 id 不认内容。

导出这一端：`render.primaries_shift_stage(plan, row, working)` 的源端读 `settings.working_primaries`
（工程没说仍用这张表自己声明的 `shift_from`，两张宽色表写的都是 rec709）；源端等于容器那一档就一个字
都不加。于是 `working=rec2020 + colour_tag=bt2020` 的图里没有 `lut3d=file=primaries-`（`zscale=matrix=2020_ncl`
照旧在），`working=p3-d65 + colour_tag=bt2020` 落进作业目录的那张 cube 逐字等于
`gamut.delivery_cube("p3-d65", "rec2020")`。成片实测：橙 (116,55,35)→(124,51,28)，中灰仍是灰（最大通道差
4），两份文件的视频流都读回 `color_primaries=bt2020`。

界面：`desktop/src/workingSpace.ts` 一处收着 `DISPLAY_PRIMARIES`（浏览器画布就是 sRGB，这一句不跟引擎
商量）、可选名单的读法与三句话；检查器工程面板那一行「工程基色」下拉列的就是能力表那份，认不得的名字
照原样念。九个系数与名单都不在界面里，界面也不调用 `primaries_matrix`——`tests/desktop_workingprimaries_check.ts`
把这几条逐字数过，视图与 store 都必须读那个常量而不是自己抄一个 `"rec709"`。

兼容：1.159 之前写的工程没有这个键，读进来按 `rec709` 解释，预览与导出的画面一字不变（这条门禁钉的就是
「把键删回没写过的样子，回包与默认档基线逐字节相同」）。schema 由 17 涨到 18，`ge=1` 起的历史文档照常读。

## 1.161 折叠那一步走哪档曲线：`fold_transfer`（工程 schema v19）

新增一处工程状态：`SequenceSettings.fold_transfer`，默认 `bt709`。它说的是同一件事的两头——
「把换基色那九个数乘在线性光上」之前，按哪条曲线把存储值抬进线性光、乘完再按同一条落回信号。
可选名单只有一个主人：`gamut.TRANSFER_CURVES`，随 `GET /v1/capabilities` 的 `fold_transfers`
下发，每行是 `{id, label}`，`label` 就是那句「这一档是谁」；界面不自列名单、不自抄默认档，
默认读那张表的第一行。

- `bt709`（默认）：BT.709 的分段曲线（α=1.099、β=0.099、编码侧指数 0.45、线性段斜率 4.5），
  也就是容器里那一格本来的意思。选它，预览与导出与 1.161 之前**逐字节相同**。
- `gamma24`：纯幂 2.4（BT.1886 那条显示端建模）。调色链里那个 `rec709` 节点用的就是它
  （`grade.GAMMA_BY_SPACE`），而随包 FFmpeg 6.1.1 的 zscale 把容器那一格也实现成它（逐格差
  0.011 阶）。注意 `gamma24` 这个词在 `ColorSpace` 那张**曲线**表里早就有，两处同拼不同表。

写入走既有的 `POST /v1/projects/{id}`（整份设置替换、一次一个版本、撤销即回），Agent 走同一条
命令与同一处校验；名单之外的名字（如 `srgb`）回 422，话里带着那两档，版本不涨、字也不落库。
消费者两处：`render.primaries_shift_stage` 据此切 `gamut.delivery_cube(工程, 容器, curve, inverse)`
那张 33³ 的立方体，`grade.preview_grade(color, primaries, fold_transfer)` 据此切
`gamut.transfer_tables(那一档)` 那两张 256 格的每通道表——两端同一条，滤镜 id 跟着变。

量到的数（`tests/foldcurve_check.py`，第 113 项；夹具按公布常数自造，不读产品那两条曲线）：
两档在抬光那张表上最坏差 18.475 阶，33³ 的 35,937 格里 35,524 格被折成不同的数；落点按「板上
那同一份整数、按同一档解析折一次」为期望——γ2.4 存的像素配对差 15 阶、配错 55 阶，分段存的
分别是 3 阶与 10 阶。装机复核：`package_check_1161.py` 在冻结引擎手里量出默认即第一行、
`bt709 → gamma24` 时预览滤镜 id `g979dcb830c3d2b94 → gea387fbf32d15449` 且两张表逐格等于源码，
`srgb` 被拒且版本不动；从新 `app.asar` 取出的渲染层里真点一次那一行，引擎 revision 2→3。

兼容：1.161 之前写的工程没有这个键，读进来按 `bt709` 解释，预览清单与导出立方体一字不变（门禁
与装机各量一遍「把键删回没写过的样子，回包与默认档基线逐字节相同」）。schema 由 18 涨到 19，
`ge=1` 起的历史文档与旧请求回执同规则。

## 1.162 折叠那一路按曲线选编译法（`fold_transfer` 的消费端，工程 schema 仍 v19）

契约没有变化：`SequenceSettings.fold_transfer` 仍是那一格，`capabilities.fold_transfers` 仍是那份名单
（`bt709`、`gamma24`，默认取第一行）。这一轮改的是**引擎拿到那一格之后怎么编译**，以及预览那两张
表的格数。

- `bt709` → 立方体：`gamut.delivery_cube(工程, 容器, curve=分段 eotf, inverse=分段 oetf)` 那张 33³ 的
  表交给 `lut3d=file=…:interp=tetrahedral`，按内容寻址落进作业目录。走不了链条那一路：随包
  FFmpeg 的 zscale 念不出分段曲线（`gamut.fold_trc("bt709")` 抛 ValueError）。
- `gamma24` → 链条：`format=gbrp16le, zscale=transferin=bt709:transfer=linear,
  colorchannelmixer=<那九个数>, zscale=transferin=linear:transfer=bt709, format=<平面 RGB>`。
  九个数仍出自 `gamut.primaries_matrix`（`primaries_mix_expression` 只是把它写成选项串），不叫
  zscale 自己换基色。16 位中间量是要件的：撤成 8 位，收窄那块板上从 6 阶退到 19 阶。
- 预览：`gamut.transfer_tables(那一档)` 的格数由 `FOLD_ROUTES[…]["preview_cells"]` 给——
  `bt709` 仍是 1.159 定的 256 格（旧工程的清单字节一字不改），`gamma24` 是 1024 格。

量的口径只有一句：期望＝**板上那同一份整数**按该档解析折一次。本轮交回的数（`tests/foldcurve_check.py`
的 `precision_suite`）：`bt709` 预览 0 阶／导出 1 阶／两端互差 1 阶／按另一档声明 26 阶，收窄那块板
本路 3 阶而另一条路走不通；`gamma24` 预览 4 阶／导出 1 阶／互差 4 阶／声明另一档 26 阶，收窄板上
本路 6 阶、立方体 16 阶。编译法对照用的是产品自己的 `render.fold_stage`，两条路各跑一遍，
断言是「交出去的那一条不比别人那一条差」——所以这张表红起来的意思是「路由要重新量」，
而不是「某个绝对容差被越过」。

Agent 侧不需要任何新接口：`GET /v1/projects/{id}/render-plan` 交回的滤镜串里就能看到这一档走的是
哪一路（装机复核那条读的就是这个路由）。

## 1.163 粘贴属性：一段的几类属性，一次粘到选中的那些段

| HTTP | MCP | 语义 |
|---|---|---|
| `POST /v1/projects/{id}/clips/{id}/attribute-plan` | `clip_attribute_plan` | 把来源那一段在人勾中的类别上排成普通命令；接不下的那段连着 reducer 自己的 code 与句子交回 |

请求体是 `AttributePlanRequest{request_id, expected_revision, source_clip_id, target_clip_ids, categories, sequence_id?}`。路由是只读的（MCP 工具 `readOnlyHint=true`，也不写库）：回执 `attribute_plan` 里 `commands` 就是将要提交的那一批普通命令（`clip.color`、`clip.effects`、`keyframes.replace`／`keyframes.remove`、`clip.mask`、`clip.mask_stack`、`mask.shape.set`／`mask.shape.remove`、`clip.fade`、`clip.speed`／`clip.speed_curve`、`clip.text`），由调用方交给 `POST /edits`——所以写入仍只有那一处。`written` 逐段列出真被排进命令的类别，`unchanged` 是「已经一样」的那些段，`refusals` 每条带 `clip_id`、`category` 与 reducer 那句 `code`／`message`／`details`；`beyond_tail_keyframes` 是落在目标段尾之外的针数（仍在工程里，那一帧之后不渲染），`dropped_extra_keys` 是落在目标段尾之外、因而**没有搬过来**的再叠遮罩框点数（框点不能停在段尾之后，块本身照搬；1.244 起「遮罩」这一类连那几块各自的框点与跟随一起搬）。回执只有 `committed` 与 `attribute_plan` 两个键：这一条不改状态，所以 1.180 起不再代带整份工程（两万段的工程上那是 12 MB 正文），与同族那条只读规划路由 `fade-adopt` 同一种形状。

类别名单只有一个主人：`contracts.ATTRIBUTE_CATEGORIES`，随 `capabilities.attribute_categories`（id／label／note）下发，额度走 `capabilities.limits.attribute_paste_targets`，开关是 `features.attribute_paste`。规划不重写规则：`attributes.attribute_plan` 把整串候选命令一次交给 `apply_commands`，那一次被拒才逐段、逐类重问（1.179；一次编辑的上限按真正落进去的条数重新数，退回时预筛留下的那几条拒绝整个作废），因此「计划」与「提交」不可能分家，而一类之内要么整类写进去要么整类不写。「变速」那一条发的是 `ripple=False`：这一段自己的长度按速率换算，后面的片段不被推开。「文字样式」只搬样式，`body` 仍是目标自己打的那行字。画面稳定与转场不在名单里（前者是那一段素材量出来的相机运动，后者属于这一段与邻居之间的那对关系）。


## 1.164 遮罩可旋转：一枚屏幕角度，导出转取样点、预览转引擎自己烘的那张图

`ShapeMask` 多一个字段：

| 字段 | 范围 | 意思 |
| --- | --- | --- |
| `rotation` | ±360°（`capabilities.limits.mask_rotation_limit` 下发同一个数） | 矩形/椭圆遮罩盒的角度，**屏幕角**：正数顺时针，与 `effects.rotation`（画面旋转）同一个读法。默认 0°，老工程不带这一格也读得进来 |

写它仍然是 `clip.mask` 那一条命令（整枚遮罩一次写），Agent 与人是同一个入口；MCP 没有新工具，
`clip_patch`/`clip.mask` 直接带得动。开关是 `capabilities.features.mask_rotation`。

角度落在三处，一次算清：

- 导出：`masks.alpha_expression` 把**取样点**绕盒心转回 `rotation` 再判在不在里面。盒子的两条比例
  是各自对着画面宽与画面高的，所以先要折成同一个单位——式子里那个比值，有画面框时是
  `框高/框宽`（1.102 那次计算），没有框时是 `H/W`。角度写成静态那一格时 `cos/sin` 在引擎里就化成
  常数，不叫 FFmpeg 每帧现算；打上关键帧之后（1.165）那两个位置换成同一份阶梯的表达式，见下一节。
- 预览：`masks.cover_svg_image` 烘一张 `viewBox` 比例就等于画面比例的整画面图，形状带着
  `transform="rotate(角度 盒心x 盒心y)"`。界面那条 `.masked-picture.rotated-mask` 只做两件事：
  `mask-size:100% 100%`（等比，不拧角度）与按 `--mask-x/--mask-y` 平移。
- 参考线：`desktop/src/maskGeometry.ts` 的 `rotatedCorners` 把四个角折回画框坐标，画向导用；
  它不算任何「能不能」的判断。

三条拒绝与它们各自的出路：

| 情形 | 码 | 句子给的出路 |
| --- | --- | --- |
| 路径遮罩带角度 | 422（契约） | 只有矩形或椭圆的盒能转；要转形状就重画轮廓 |
| 转过的盒要打 `mask_width`/`mask_height` 曲线 | ~~`INVALID_MASK`~~（1.166 起这条撤了） | 每窗重烘一张等比图，那扇窗的角度与两条边一起换 |
| 角度超过 ±360° | 422（契约） | 转一圈以上还是同一枚盒子 |

中心曲线照旧能搬转过的盒子：一张等比图被平移，两端是同一个位移。量过的证据（`tests/maskrot_check.py`
+ `package_check_1164.py`）：三段真导出的主轴 −0.0°／30.0°／−45.0°；装机引擎那张图喂进装机那条 CSS，
Chromium 画出 30.0°／占比 0.0998，与同一档导出的 30.0°／0.0997 对得上；零角度那一路交出的字节
与 1.163 一字未改（门禁把那句原文钉住，而不是再算一遍）。

**为什么预览不走「转图层」那条路**：这一轮在同一族 Chromium 上量过被遮罩元素带
`transform: rotate()` 的画法——外层转、内层反着转回来，computed style 两个矩阵都在，
画出来的遮罩主轴仍是 0.0°。所以 `mask-image` 不吃图层旋转，那条看着最省的连续旋转路子在这一档
走不通；要连续转角度，就得每帧换一张图（1.118 那种按窗阶梯是退一步的确定做法），那笔代价 1.164 没量——
1.165 量的正是退一步那一条，见下一节。

工程 schema 19→20：带角度的工程若被旧引擎读到，会按版本挡下来，而不是把角度悄悄抹平。

## 1.165 那枚角度能打关键帧：两端执行同一份按帧对齐的窗表

`MaskProperty` 多第五条：`mask_rotation`。写它仍是普通的 `keyframe.set`／`keyframe.remove`，
人是检查器那一格旁边的 ◇，Agent 是同一条命令；开关是 `capabilities.features.mask_rotation_curves`，
段数上限是 `capabilities.limits.mask_rotation_schedule_segments`（本轮 12）。

它不是一条连续曲线，因为两端画不出同一件连续的事：导出能给 `geq` 每帧现算一个角，浏览器不能
（`mask-image` 不吃图层旋转，1.164 量的），一端连续、一端台阶就是这项目 refuse 的那条缝。所以
**一份窗表两头读**：

- `animation.mask_box_schedule(clip, quantum, limit)` 走的是 1.118/1.123 那一次同一件
  `frame_windows`：每窗一个常数角，短于上限的片段按帧精确，长于上限的按一个两边都能核对的数变粗。
- 导出侧 `animation.rotation_step_expression(schedule, frame_ticks)` 把这份表串成
  `if(lt(T,秒),角度, if(lt(T,秒),角度, …))`，写进 `alpha_expression` 那两个 `cos/sin` 的位置。
- 预览侧清单多一个 key：`mask_rotation_windows`（`from_ticks`／`to_ticks`／`angle`／`image`，
  `image` 就是那一窗烘好的那张等比图），界面按**整数 tick** 落格换图；同一条曲线也下发，
  每点是 `steps(1, end)`，与那 12 段一格不差。

**换窗那一步落在帧的中间，不落在帧的起点。** 装机复核抓到过一次两端差一格：边界原先打成
`to_ticks / TIMEBASE` 的秒数（`.12f`），而那一帧自己的 `T` 就是同一个秒数——两个浮点数比大小，
判的只剩最后一位，第 14 帧量到 83.5° 而窗表说 90°。现在打在 `to_ticks - frame/2`，与界面那头
本来就按整数 tick 的落格同一个语义。`tests/maskrot_check.py` 新增的那一节钉的就是这一格：
边界第一帧已是新窗的角、前一帧还停在旧窗（量到 41.2°／34.0°），突变「把余量撤掉」红在这条断言上。

两条拒绝与它们各自的出路（`Clip.mask_animation_problem`，reducer 之后一次判）——1.166 起这里只剩轮廓那一条：

| 情形 | 码 | 句子给的出路 |
| --- | --- | --- |
| 路径遮罩打角度针 | `INVALID_MASK` | 轮廓自己带形状，没有盒可转；要转就换矩形/椭圆，否则按轮廓帧记形状 |
| 转过角度的盒打 `mask_width`/`mask_height` 针 | ~~`INVALID_MASK`~~（1.166 起这条撤了） | 照样打：那三条数走同一份窗表，`features.mask_rotation_size_curves` 报这一档 |

界面那一侧的名单同出一处：`maskAnimFields(mask, caps)` 不给路径遮罩角度那一行，也不在这一版引擎
没报 `mask_rotation_curves` 时摆那颗 ◇。中心曲线照旧能搬转过的盒子。

### 编译期的两道结构拒绝（1.167 与 1.168）

这两条码不是「你写错了什么」，是引擎接线错了的证明——它们防的是 1.166 那次「成片整幅空掉而任务退 0、
`GET /v1/frame` 仍回 200」。`compile_render_plan` 收尾跑一次 `validate_plan_inputs(plan)`，
导出、帧路由、批量交付与任务队列走的是同一道门（拒绝点在 `compile_render_plan`，
HTTP 的每一帧与每个任务都从它出来）。调用它的是四个入口：渲染任务（`jobs.py`）、取帧
（`media.render_frame`）、响度探针（`loudness.py`）与嵌套合成的子图（`render.py` 自己）。
MCP 的 `preview_frame` 打到的是同一条 HTTP 路由，而它的 `raw()` 把路由交回的 `error` **原样**
递成工具错误——码、句子与 `details` 都不换名字，所以 Agent 看到的码与人看到的是同一个，不需要为
MCP 另写一份词汇表。这三条接线（路由、渲染、原样递回）现在都由 `tests/planinput_check.py` 钉着，
免得「函数对、调用点不对」。装机那一份（1.168.0）实测还补了一句形状上的话：错误文本是
`Error executing tool preview_frame: {"code": "NOT_FOUND", "details": {"project_id": "does-not-exist", …}}`
——外面那层前缀是 MCP SDK 加的，不是本仓代码加的，因此客户端要解析的是消息**尾部那段 JSON**，
不是整条文本。1.169 对着随包那份实测补齐：同一个请求 `result.isError` 为 `true`，文本尾部那段 JSON 的
`code` 与 `details` 与 HTTP 的 404 体逐字相同，成功那一路交回真实 PNG 的 `sha256` 与落格后的 `at_ticks`
——客户端按 `isError` 分支即可，那层前缀只是 SDK 的文本包装，不是引擎要改的东西。两侧结果形状也量清了：
**成功的**工具结果键是 `content` + `isError` + `structuredContent`，**失败的**只有 `content` + `isError`
（没有 `structuredContent`），所以领域错误码要从文本尾部那段 JSON 读。

| 情形 | 码 | 句子给的出路 |
| --- | --- | --- |
| 某一路声明过的输入，图上没有任何层链读它 | `PLAN_INPUT_UNREFERENCED`（500，details 带 `pad` 与那一格的秒数） | 换一份交付预设，或把这一段单独导一次；还出现就把片段 id 与这段时间告诉我们 |
| 同一路**真实素材**的输入被两条层链同时读 | `PLAN_INPUT_DOUBLE_READ`（500，details 带 `pad` 与 `chain_count`） | 同一个素材本应一段一路；把其中一段换个素材或挪到别的轨再导，还出现就把这两段的 id 告诉我们 |

生成的一路（黑底画布 `color=…`、`nullsrc`、`anullsrc`、`sine=`）不参与第二道判断——它本来就要被反复合成。
判断「哪一路是生成的」看的是它自己的源字符串前缀，**不是它的编号**：探针量到过 `0` 号其实是 `red.mp4`。

还有一条**故意不做**的，写在明处免得下一轮又当成规矩交出去：「每条层链 `trim=duration` 不得超过它那一
路声明的 `-t`」。它看起来同样严格，第一次进 116 项套件就把 `tests/fourpoint_check.py` 打红——四点点位
与变速那一路会在拉伸后的时间轴上合法地 trim 得比源窗长。它只在 `tests/planinput_check.py` 里被量下来，
并断言那份 plan 照样编译得过去。

工程 schema 20→21：多的是那条可打关键帧的属性名与那格默认 0° 的角度，旧工程读进来一字不改；
带角度针的新工程被旧引擎按版本挡下，不会被读成「一直不转」。

## 1.173 记一句会被误会的数：针数不等于窗数

一条转过角度的盒上打 12 枚角度针 + 12 枚宽针（每 4 帧一枚，片段 60 帧，`capabilities.limits.
mask_rotation_schedule_segments` 当前是 12），`GET /v1/projects/{id}/preview-manifest` 交回的
`mask_rotation_windows` 实测是 **10 窗**（角度 4.375°…77.0°、宽 0.281…0.800、每窗一张 base64 长
845..846 字的图，清单里那条台阶 20 个点）。窗是按帧对齐后**等值合并**出来的，不是按针数点出来的：
段数上限是「最多能切几段」，不是「打几枚针就有几段」。

给 Agent 的两条实操口径：想核对端一致性，读清单里的 `steps(1, end)` 点数与 `mask_rotation_windows`
的 `from_ticks`/`to_ticks`，别看针数；想把窗数推到上限，改针的**时刻分布**（让相邻针的角度与宽都不同、
并且别落在同一段里），而不是堆针数——多打的针若与邻居同值，会被合并掉，不报错也不占额度。

## 1.272 遮罩跟踪：角度按上一帧的转向预测，一圈是硬边界

`estimate_rotation` 的角度搜索不再只以上一帧的角度为中心：跟踪器记住上一帧量到的角增量 `spin`，
每帧先按 `angle + spin` 预测，模板按预测角先定位、再在预测附近 ±6°（步长 2°）细找。窄找的
相关系数低于 0.55、第一帧、以及刚结束遮挡的那一帧，改在预测两侧 ±45° 内按 5° 粗扫、再按 1° 细化。
两条 mask-track 回执都多一格 `angle_limit_at_ticks`（绝对 tick，和 `lost_at_ticks` 一样按
`from_ticks` 平移）：它非空表示累计转角撞到 `mask_rotation` 的 ±360° 契约边界，跟踪在那一帧停下；
它与 `lost_at_ticks` 同时指向那一帧，但说法不同——提示与帮助会把它念成「转满一圈」，并给出
「把这一圈之后的镜头切开分别跟」这条真出路，而不是「跟丢」。

实测（`tests/trackfast_check.py`，白杆+白点夹具、FFmpeg `rotate` 表达式给定角度）：
13.7°/帧 20 帧全中、最差 1.10°；15°/帧反向逐帧误差 0.00°；静止全 0；25°/帧写到 350°、
第 15 帧停下；30°/帧与 40°/帧都能走到 360°。写回的角度都在 ±360° 内，reducer 不拒。
仍不做：3D/透视旋转、一帧超过 ±45° 的粗扫跨度、一条曲线里的多圈旋转、路径遮罩的角度。

## 1.289 交换格式（OTIO / FCPXML）

* `GET /v1/projects/{project_id}/otio?sequence_id=` — 整条时间线为 OpenTimelineIO JSON。轨道、Gap 与每段的 `source_range` 都是真的；每段还带着自己的 `metadata.agentcut.clip`，所以经这一份文件往返不会把调色、遮罩与关键帧压成一张剪辑表。只读。
* `GET /v1/projects/{project_id}/fcpxml?sequence_id=` — Final Cut Pro XML 1.9。`omitted` 逐条点名这一版写不进 spine 的片段（文字层、变速、转场），`complete` 为假时读者就知道这是一份直切近似。只读。
* `POST /v1/projects/{project_id}/otio/import` — 请求体 `{document, sequence_id?, apply?, request_id?, expected_revision?, dry_run?}`。默认只规划：先为它接管的每条轨道生成 `clip.remove`，再按 Gap 推进的绝对位置逐段生成 `clip.add`。素材按文件名匹配本工程已验证的素材；匹配不到（`OTIO_MEDIA_UNMATCHED`）、一个名字两份素材（`OTIO_MEDIA_AMBIGUOUS`）、轨道比工程多（`OTIO_TRACK_COUNT`）、源窗口越界（`OTIO_CLIP_RANGE`）都整份拒绝。`apply=true` 要带 `request_id` 与 `expected_revision`，写入走普通 `/edits`：一个 revision、一次撤销整体退回。

MCP：`project_otio`、`project_fcpxml`（只读），`otio_import_plan`（强制只读，把命令交回 `timeline_edit`）。能力位：`features.otio_export` / `otio_import` / `fcpxml_export`。

### 1.292 工程格式进口：一个入口，四种读法

* `POST /v1/projects/{project_id}/import` — 请求体 `{document, format?, sequence_id?, apply?, request_id?, expected_revision?, dry_run?}`。`document` 是**文本**（OTIO 与剪映草稿也可以直接给 JSON 对象）；`format` 可以省略，引擎按文档自己写的东西认（`OTIO_SCHEMA` 前缀、根元素、CMX3600 事件行、`tracks` + `materials` 同时在场），认不出来按 `INTERCHANGE_UNKNOWN` 拒绝并说明可以显式传 `format`。回执总是带 `format`（认成了谁）与 `omitted` / `complete`（这一版没能搬过来的东西，逐类点名），所以读者知道交回来的是整刀还是一半。
  * 支持的读法：`otio`、`fcpxml`（1.x 单文件；`<spine>` 的 `layer` 折成画面轨、`<lane>` 折成声音轨、`<title>` 落成文字片段、`<gap>` 只推位置不算片段）、`xmeml`（FCP7 / Premiere「导出 XML」：`<in>/<out>` 是源窗口、`<start>/<end>` 是记录窗口，`<media>` 与直接挂在 `<sequence>` 下两种写法都读）、`edl`（CMX3600：`rec_in` 落位置、`src_in..src_out` 落源窗口与时长，`* FROM CLIP NAME:` 用来对素材）、`jianying`（剪映 / CapCut 明文 `draft_content.json`：微秒制的 `target_timerange` / `source_timerange`，`material_id` 对到 `materials.videos|audios|texts`）。
  * 位置一律按文档写的**绝对值**落，不做累加游标，所以一个 layer / lane / channel 里的空隙不会把后面所有段推移。
  * 拒绝口径：素材名匹配不到（`{FCPXML|XMEML|EDL|JIANYING}_MEDIA_UNMATCHED`）、一个名字两份素材（`INTERCHANGE_MEDIA_AMBIGUOUS`）、源窗口越界（`INTERCHANGE_CLIP_RANGE`）、轨道比工程多（`*_TRACK_COUNT`）、整份没有可导入的片段（`*_EMPTY`）、没交文档（`INTERCHANGE_NO_DOCUMENT`）。丢帧时码（`EDL_DROP_FRAME`）、分数帧率工程（`EDL_RATE`）、自称 encrypted 或压根不是 JSON 的剪映 6+ 草稿（`JIANYING_ENCRYPTED`）**整条拒绝而不是猜一套算术**。
  * 这一版明确搬不过来的东西进 `omitted` 而不是被静默丢掉：转场、插件效果、变速（FCPXML 的 `speed`、xmeml  clipitem 里的 `rate`、EDL 的 `D`/`W`/`K` 事件、草稿的 `speed` 与 `animations`）、遮罩形状、FCPXML 的复合 `<asset>`（内层 `<spine>`）、xmeml 里没有 `<file>` 的生成器。
  * 两个 XML 读法收的是外部文本，所以解析之前先设防：出现 `<!ENTITY`（内实体放大与外部实体的唯一入口）按 `{FCPXML|XMEML}_MALFORMED_ENTITIES` 拒绝，`<!DOCTYPE … SYSTEM|PUBLIC>` 按 `{FCPXML|XMEML}_MALFORMED_EXTERNAL_DTD` 拒绝。这条路由只收 document 文本、不接受文件路径，不成为媒体导入之外第二条读文件的口子。
  * `apply=true` 要带 `request_id` 与 `expected_revision`，写入走普通 `/edits`：一个 revision、一次撤销整体退回。默认只规划。

MCP：`interchange_import_plan`（强制只读，`apply` / `dry_run` 关掉，把 `commands` 交回 `timeline_edit` 提交）。能力位：`features.interchange_import`。`.prproj` / Resolve 的 `.drb` / `.blend` / `.aep` 没有可靠的公开解析器，因此**不做**；这些软件都能导 FCPXML / EDL / OTIO，走上面这一条门。


## 1.293 文稿面：一句话说完哪里有人说话，删一句等于删一段

* `GET /v1/projects/{project_id}/transcript?sequence_id=&merge_gap_ms=350&silence_ms=600` — 把这条时间线**说话的形状**一次读完：按时间排序的短语、短语之间的空档、以及各自的毫秒与绝对 tick。只读，不解码任何媒体，一个字都不写。
  * 短语来自工程里**已经落地**的字幕片段（`captions.import` / 语音识别写进来的那一份），所以 Agent 读到的与人在字幕轨上看到的是同一句话、同一个入点；这一条不是第二套口径。
  * 合成一句要同时满足两条：间隔 ≤ `merge_gap_ms`（默认 350）与合起来 ≤ 120 字（`transcript.MAX_TEXT_CHARS`）；`clip_ids` 记下这一句吃掉的所有字幕片段 id，所以「一句」与「哪几段字幕」两头都对得上。
  * `silences` 只报 ≥ `silence_ms`（默认 600）的空档，给的是 `from_ticks` / `to_ticks`：这是「两句话之间能下刀的位置」，不是静音检测的结论。要按真实静音下刀仍是 1.25 那条 `audio/silence`。
  * 回执带 `phrase_count` / `silence_count` / `caption_clips`（合并前有几条字幕）/ `speech_ticks`（说话总时长）/ `covered_to_ticks`（最后一句落在哪）/ 本轮生效的两个阈值，还有 `revision`；Agent 拿这些数就能决定要不要读第二遍，不用自己数。
  * 没有可读文本按 `TRANSCRIPT_EMPTY` 拒绝，句子给的出路是「先对带人声的片段跑一次语音识别」，不是「参数错」。
* `POST /v1/projects/{project_id}/transcript/cut` — 请求体 `{spans:[{from_ticks,to_ticks}], sequence_id?, apply?, request_id?, expected_revision?, dry_run?}`。默认只规划，交回的是**普通命令**：`clip.split` + `clip.ripple_remove`；整段落进窗口的字幕片段直接 `clip.remove`，不会被切成零长。
  * 删一句话与删一段静音是同一条代数，所以这里**复用** `silence.cut_plan(clip, gaps, edges=True)` 而不是再写一份。`from_ticks` / `to_ticks` 是绝对时间线上的位置：每个片段先把窗口换算到自己的局部坐标，再落到帧格——起点向上取整、终点向下取整，刀口两边留下的都是完整帧，不会剩半帧；换算后不前进的窗口直接不管，所以一小段亚帧的空档不会凭空多一条命令。
  * 同一个窗口碰到的画面、人声、音乐、字幕在**同样的边界**上各切各的，轨道不会因为删了一句而互相错开；`clips[]` 逐条报哪个片段被切掉多少 tick、是不是整段删除、那一条生成了几条命令。
  * 片段按 `-position_ticks` 从**右往左**处理，因此左边那些刀落下去之后，还没处理的片段的 `position_ticks` 仍然有效——与整轨去空白同一个约定。
  * `removed_ticks` 是**时间线因此短了多少**，不是各轨被切掉的总和：三条轨同删一句一秒的话，是一秒的空档，不是三秒。重叠与相接的窗口先并成一个，所以两句之间那点空隙不会被算两遍。
  * 不猜的拒绝：`TRANSCRIPT_NO_SPANS`（没给窗口，或窗口不是 `{from_ticks,to_ticks}` 对象）、`TRANSCRIPT_SPAN`（窗口不向前 / 起点为负）、`TRANSCRIPT_NOTHING_TO_CUT`（这些窗口碰到的片段全被拒，`details.skipped` 逐条点名）。跳过是带理由的：所在轨被锁（`track … is locked`）、片段带变速曲线（时间在这一段里不是线性的）——两者都进 `skipped[]`，**其它轨道照切**，不会为了一段锁着的音频把整刀放弃。
  * `apply=true` 要带 `request_id` 与 `expected_revision`，写入走普通 `/edits`：一个 revision、`/restore` 一次整体退回。

MCP：`timeline_transcript`、`transcript_cut_plan`（两者强制只读，`apply` / `dry_run` 关在门外；`transcript_cut_plan` 把 `commands` 交回 `timeline_edit` 提交）。能力位：`features.transcript_view` / `features.transcript_cut`。

界面那一侧这是右侧第五页「文稿」：一行一句，勾上就是待删，页头那句报本次会删几句、另有几处空档，按钮只写「剪掉」。这一页存在的理由与上面同一句——**要看见说了什么，不该先把整条时间线当帧读回来**。

## 1.295 帧级确定性自检：同一端自己稳不稳，也要量一次

* `POST /v1/projects/{project_id}/frame-stability` — 请求体 `{at_ticks: [整数 tick], sequence_id?}`。
  把这几个时刻各重画三遍（正序 / 倒序 / 错位），交回 `{frames: [{at_ticks, rendered_at_ticks,
  sha256, pixels_bytes}], passes, stable, mismatched, distinct, revision}`。只读，一个字都不写。
  * `stable` 只说一件事：**同一时刻三趟逐字节相同**。`mismatched` 逐条点名是哪一时刻、第一次与
    再画一次的哈希前缀各是什么。
  * `distinct` 是这些时刻**实际画出几张不同的图**。它不是判据而是事实：八枚时刻画出一张图，正是
    「缓存键里少了时刻这一维」的样子；而一段纯色素材画出同一张图也不是 bug——所以这一格只报数，
    由调用方按自己的夹具判断，引擎不替人猜。
  * `rendered_at_ticks` 是落格之后真正画的那一 tick，与 `GET /v1/frame` 的 `X-Frame-Ticks` 同一个数。
  * 上限一次 8 帧（`stability.MAX_TIMES`），由**引擎**说而不是 pydantic：那条 422 体是英文的
    「String should match pattern」，人和 Agent 都读不到「分成几批问」这条出路。
  * 两条拒绝：`STABILITY_NO_TIMES`（没交落点）、`STABILITY_TOO_MANY`（一次要画的帧数超过上限，
    `details` 带着 `count` 与 `limit`）。
* MCP：`frame_stability`（只读）。能力位：`features.frame_stability`——它**跟着媒体引擎走**
  （`media_ready`），不是永远为真：这一档要真的重画，没有 FFmpeg 就没有结论可报。

这一档存在的理由与 1.293 那条文稿面是同一句话的两半：文稿面让 Agent 不必读帧就知道**说了什么**，
这一档让它一次调用就知道**这台引擎还稳不稳**。项目以前量了很多「两端一致」（导出与预览逐像素对得
上），但同一端自己稳不稳没有门禁——派生缓存（帧、代理、缩略图共用一套目录）只要少写一个键维度，
当时整套门禁没有一档会红。

## 1.296 一张总览图：一次调用看完这条剪辑，而不是六次

`preview_frame` 回答「这一时刻长什么样」；要看**整条剪辑顺不顺**，Agent 以前只能按 N 个时刻各调一次。
`GET /v1/projects/{project_id}/overview?count=6&from_ticks=&to_ticks=&sequence_id=` 一次交回一张
接触印相（contact sheet）：

* 每一格都是 `GET /v1/frame` 会交回的**同一张 PNG**，由 FFmpeg 的 `tile` 拼起来——这里不重新实现
  任何合成，画面里缺了一道调色，总览图上就缺同一道。
* 格子按**阅读顺序**排（先左到右，再换行），每一格来自哪一 tick 由响应头 `X-Overview-Cells` 逐格
  报出，网格形状由 `X-Overview-Grid` 报出（六格就是 `3x2`：先取平方根定列，再定行）。
* 落点是**两端各留半格**的：一条时间线最容易是黑帧的地方就是第一帧与最后一帧，一张第一格就黑的
  总览图不给任何新信息。落点仍一律落在帧格上，与取帧那条路同一个算术。
* 2–12 格由**引擎**判（`OVERVIEW_COUNT`），窗口倒着写或落在时间线之外判 `OVERVIEW_RANGE`；拼不出来
  按 `OVERVIEW_STITCH_FAILED` 回并说明「帧本身仍可一帧一帧读」，**不退化成只交第一格**。
* 能力位 `features.timeline_overview` 跟着 `media_ready` 走；MCP 一只只读工具 `timeline_overview`，
  交回 `png_base64` + `grid` + `cells` + 宽高 + `sha256` + `revision`。

一句要说准的话：**省的是往返与附件数，不是像素。** 实测六格总览图 96,142 字节，而逐帧读是 6 次、
每次约 14,202 字节（合计约 85 KB）——总字节几乎相同，因为格子的总面积就是那六帧的面积。少的是
五次往返与五张要各自进上下文的附件。

## 1.307 一份机器可读的 agent 契约：三条门收成一条

同一个引擎以前有三条 agent 路：HTTP `/v1`、MCP 适配器、`agent/` 那台「Agent API 标准」桥。
前两条是薄的（MCP 每只工具都是 HTTP 的转发），第三条却是**手写的六只工具、还绕过 HTTP 直接开
SQLite**：产品后来加的媒体、渲染、字幕、遮罩、交换格式一共六十多只，它一只都没有——同一句
`timeline_edit` 走两条路会得到两种深度。这一档把三条收成一条：事实只写一次，其余都从它派生。

* **契约**：`src/agentcut/agent_contract.py`。路由表读 FastAPI 自己的 `app.routes`（连每条路由
  的 path / query / body 参数名一起读，来自 `route.dependant`）；工具表读 FastMCP 当场报的
  `list_tools()`（名字、描述、inputSchema、只读位）。两张都是**跑起来才有的事实**。
* **派发**：`TOOL_ENDPOINTS` 登记「这只工具走哪条路由」，`resolve()` 按路由自己的签名把参数分成
  path / query / body。GET 上那一整个请求模型（`timeline_transcript` 的 `merge_gap_ms` 那一类）
  摊平成查询参数——不摊平就会把 `request` 当成一个查询键发出去。这一条不是推测：门禁里
  `dispatch_alignment` 就是这么抓它的。
* **配方**：`RECIPES` 三条（从素材到粗剪交付 / 口播转字幕并按句剪 / 把别人剪好的一刀搬过来再交付），
  只有一份，HTTP 契约、MCP prompts 与文档读的都是它。
* **读路由**：`GET /v1/agent/manifest`（能力位 `features.agent_manifest`）一次交回版本、鉴权说明、
  错误形状、能力表、85 条路由、72 只工具与三条配方。
  框架自己的 `/openapi.json` 与 `/docs` 也开着（本机回环），但它只看得见 HTTP 一侧：MCP 工具、
  只读位与三条配方只有这份契约说得出——要「一次问清」就读契约，不要读 OpenAPI。
* **MCP 原语补齐**：资源 `agentcut://manifest`（同一份契约）+ 三只 prompt
  （`recipe_cut_from_media` / `recipe_speech_to_captions` / `recipe_imitate_imported_edit`）。
  只会说 MCP 的 agent 也能问到「一条片子按什么次序剪完」。
* **桥改成派生**：`agent/tools.py` 的 TOOLS 由契约生成（73 只 = 72 只引擎工具 + 桥自己的
  `status`），每只 handler 都经 HTTP 打引擎——同一个令牌、同一套 revision 与幂等、同一个媒体根目录
  守卫。它按 `AGENTCUT_API_URL` + 令牌文件找人，没人应答才自己拉起一台**自己那一份**引擎（只杀
  自己拉起的进程，绝不动桌面端那台）。`agent/mcp-server.mjs` 一个字没改就跟着变宽：它本来就是从
  桥的 manifest 派生 MCP 工具名单的通用壳。

调用形状（桥这一侧，非 GET 一律要 `x-agentcut-token`）：
```text
GET  http://127.0.0.1:8780/api/agent/manifest      # 工具名单 + 令牌头与令牌文件
POST http://127.0.0.1:8780/api/agent/tool          # {"tool": "agentcut.project_create",
                                                   #  "input": {"request": {...}}}
```

验收在 `tests/agent_contract_check.py`：契约自洽（72 只都登记路由、路由都在真表里、配方不引用
幽灵工具）、`/v1/agent/manifest` 与离线构造逐字相同、桥的名单/schema/读写性与契约相同、每只工具
经 `resolve()` 落在登记的那条路由上、12 组真调用两只门面答案与拒绝 code 一致、一条真剪辑经桥跑完
（建工程→导素材→加轨加段→2 秒处切开→dry_run 不写库→排队交付，ffprobe 验出 4.00 秒两条流），
外加第三道门 `agent/server.py` 起桥读名单并建一次工程；再用一条真 stdio MCP 会话读到三只
prompt 与 `agentcut://manifest`，资源交回的工具表与路由表与 HTTP 契约逐字同一份。
**6 条突变各自红在自家断言上**，
跑完按字节还原并核对 sha256。

## 1.310 一次调用等到交付：`GET /v1/jobs/{job_id}/wait`

`render_start` 交回 job id 之后，以前只能自己一秒一次打 `job_status`。这一条把「等到跑完」放回服务端：
`timeout`（0..120 秒，默认 30）与 `poll`（0.05..2 秒，默认 0.25）都在查询里，越界 422。
到终态或到自己超时都交回**同一份作业文档**——`job` 与在飞时那份 `plan`——外加两个字段：
`waited_ms` 等了多久、`timed_out` 是不是还在跑。超时不是错误，也不是失败：调用方可以换更长的
`timeout` 再来一次，等本身不动作业（`tests/jobwait_check.py` 量过：`timeout=0.05` 说 timed_out，
随后一次长等仍到 `succeeded`）。

契约、MCP 与桥同一份：`agent_contract` 登记 `job_wait`，MCP 多一只 `job_wait(job_id, timeout, poll)`，
配方那一步从「轮询到 succeeded」改成「一次调用等到终态」。能力位 `features.job_wait`。



## 1.311 一刀跑完一条配方：`POST /v1/agent/recipes/{recipe_id}/run`

配方此前只能被**读**：`GET /v1/agent/manifest` 与 MCP 的 `recipe_*` prompt 交回 13 步，
调用方自己把 13 次请求串起来，每步都得带上一步交回的 `expected_revision`。这一版让引擎
自己走完这张表——对外还是一个 JSON 请求体，对内是同一批路由。

```
POST /v1/agent/recipes/cut-from-media/run
{
  "request_id": "cut-2026-10-26-a",
  "name": "粗剪一条",
  "files": ["D:/media/a.mp4", "D:/media/b.mp4"],
  "threshold_db": -40.0, "min_silence_ms": 500,
  "keep_ms": 500,
  "preset_id": "h264-720p-web", "filename": "cut.mp4",
  "render": true, "wait_seconds": 90.0
}
```

`scene_threshold` / `min_scene_ms` 不给就用引擎自己的默认（0.18 / 400 毫秒），`threshold_db`
那一档的量程与 `keep_ms` 也和单独叫那两刀时是同一份模型，不是这一刀另开的量程。

* 走的是同一批门：引擎用 `httpx.ASGITransport` 打自己，带着同一条 bearer 令牌。reducer、
  revision 校验、素材根授权、幂等凭据一步都绕不过，所以一刀跑完与逐步调用不会有两种结果。
* 交回 `steps`，13 行，一行一个步骤名——就是契约里的工具名，带 `called`（哪扇门）。
  `timeline_overview` 与 `preview_frame` 交回的是 PNG，这一刀不替人看图，所以它们的行是
  `ran: false` 并在 `why` 里说清该单独叫哪一只。
* 整刀幂等：同一个 `request_id` 再叫，`project_create` 交回它当时的凭据，后面写步一律标
  「已经跑过」，然后读回工程现在的 revision 与那一单交付。不会出现第二次落库或第二单渲染。
* `render=false` 停在粗剪：工程与两刀落库都是真的，只有排队交付那一步留给调用方；
  `wait_seconds` 与 `job_wait` 同量程（0..120），0 就是「排完就走」。
* 只有 `cut-from-media` 开了这一刀。另两条在 `recipes()` 里带 `runnable: false` 与 `why_not`，
  叫它们拿 422 `RECIPE_NOT_RUNNABLE`（带原因与 `runnable`），配方名不存在拿 404（带全部三条）。
* 越界的素材路径停在 `media_import` 那一步——它在建工程之前，所以不会留下半个空工程；
  错误信封里 `details.called` 说的就是停下的那扇门。
* MCP 同一只：`recipe_run(recipe_id, request)`；桥（`/api/agent/tool`）从契约里派生同一只。
  能力位 `features.recipe_run`，跟媒体引擎在场与否走同一判断。
## 1.312 三条配方都开了这一刀：`recipe_run` 的另外两扇门

1.311 只开 `cut-from-media`。这一版把 `speech-to-captions` 与 `imitate-imported-edit` 也接上，
并把「哪一条要哪些参数」从模型移到配方口径里：`files` / `preset_id` / `filename` 变成可选形状，
缺什么由 `recipe_run` 在建工程之前按名字拒（422 `RECIPE_PARAM_MISSING`，`details.missing`
点名缺的那几样、`details.required` 给出整张清单）。`recipes()` 因此不再带 `why_not`，
每条改带一句 `params`。

`speech-to-captions`（15 步，`request_id` 贯穿）：

```
POST /v1/agent/recipes/speech-to-captions/run
{
  "request_id": "cut-voice-1", "name": "口播一条", "files": ["D:/media/talk.wav"],
  "language": "zh", "caption_max_chars": 16,
  "filler_patterns": ["嗯", "就是说"], "cut_gap_ms": 600,
  "preset_id": "h264-720p-web", "filename": "voice.mp4", "render": true, "wait_seconds": 90.0
}
```

* 「剪哪几行」是数据不是代码：`filler_patterns` 命中的那一句、`cut_gap_ms` 长过那档的句间静音，
  段的位置一律取自 `GET /v1/projects/{id}/transcript` 那份 `phrases` / `silences`，一刀里没有第二处判断。
* 这条要本机备着语音模型（`features.speech_captions`）。没备着时 `captions_auto` 那一行是
  `ran: false` 并说明为什么，其余步骤照走完——不假装出了字幕。
* 回执里 `captions_export` 那行给 `srt_chars`；`include_text: true` 才带全文（几 MB 不该默认塞进一刀）。

`imitate-imported-edit`：`interchange_document` 是那一份工程文件的正文，格式仍由引擎认
（`interchange_format` 只在你想强制时给），`files` 是那份文档指着的素材。两处门槛是真门槛，
配方文本已写明：

1. 读那一边按**名字**认素材，只肯用这台引擎已经验过的，所以素材要先探测并登记成这个工程的
   asset——否则交回来的 `clip.add` 指着别的工程里的 id；
2. 读那一边要求**轨道先存在**：五种格式各有一句 `*_TRACK_COUNT`，并把缺的条数直接数给你
   （`wanted` 有 `{video,audio}` 与单个整数两种形状）。这一刀按它数的条数补 `track.add`
   再读一次，最多六轮；一轮补不出进展就把那份拒绝原样抛出，不静悄悄猜。

实测（同一份源码与随包二进制各跑一遍）：口播 7.77 s 真中文素材 → cue 2 条、SRT 88 字、
交付 7.07 s；把自己导出的 FCPXML 搬回来 → 落库 2 条命令、两份交付 115,866 B / 166,062 B。

1.313 起，`cut-from-media` 与 `speech-to-captions` 多一步 `master_loudness`：
给了 `loudness_target_lufs` 才落混音（引擎走的是导出那同一张音频图测出来的数，写一次
`project.update`、涨一个 revision），没给就那一行 `ran: false` 点名缺的是哪一样——
一刀不替人决定片子该多响。门禁拿 FFmpeg 自己的 `ebur128` 量交付文件：目标 -16.0、
实测 -16.1 LUFS；把那一步偷偷跳过，同一档立刻量到 -21.7 并红。

## 1.314 交付对不对：`GET /v1/jobs/{job_id}/verify`

`output_checked` 那句的意思只是「有个探测在旁边认同这个文件读得开」。这一扇门把「对不对」收回引擎：
它拿 `ffprobe` 读那个文件（长度、画幅、帧率、有没有声轨），拿 `loudness.measure`（FFmpeg 自己的
EBU R128 表）读它的响度与真峰值，再和**这个作业当时编出来的那张计划**逐条对——`plan_for` 就是
worker 要渲染的那一份，所以「期望」不是这一档现编的数。

* 交回 `verdict` 与 `checks[]`，每条带 `expected` / `measured`；不合格不抛异常：文件被删了仍然
  200，假在 `file` 那一条，后面写着「没有可读的文件，后面的量法都无从下手」。
* `target_lufs`（-30..-6）不给就不判响度，那一条的 `expected` 写「报告，不判」——这一扇门不替人
  决定片子该多响；给了才判，允差 1.5 LU。`ceiling_dbtp`（-9..0）另钉真峰值，允差 0.5 dB。
* `duration_tolerance` 默认 0.25 s，与 `recipe_run` 里那一格用的是同一档。

三条配方把它接成最后一步（1.316 起按配方顺序交回 **16 / 18 / 17** 行步骤，多出来的是`render_batch`）。搬别人那一刀走批量交付，所以
那一格逐条验——两条交付就交回两个 `job_id` 与两个 verdict，不会只验第一条就当全对；`verify=false`
就不验，那一行 `ran: false` 说清为什么。MCP 同名工具 `deliver_verify`，能力位 `deliver_verify`。

门禁最要紧的一条不是「验出来的数对」，而是**把交付换成另一条片子**：2.00 s / 1280x720 那条改名
收起来，原位置放 3 秒 320x180 的那一片，再叫同一扇门——它必须转为假，假在 `duration` 与
`resolution`，而实测数只能是 3.0 s 与 320x180。这一条把「实测 = 复述计划」那类写法钉死：变异台
真把 `round(read["seconds"], 3)` 改成 `expected_seconds`，交回的 `measured` 就成了 2.0，当场红。

## 1.316 批量交付那一档：`deliver_items` 不再是一条「点了没反应」的路

交付形状两种，择一：

* **单预设**：`preset_id` + `filename`——`render_plan` 编译、`render_start` 排队；
* **批量**：`deliver_items`（1..4 条，每条自带 `preset_id` / `filename`，可各自 `fit`）——
  `render_batch` 一次排完，`job_wait` 逐条等到终态，`deliver_verify` 逐条验。

1.316 之前第二种形状是静默空转：配方里没有 `render_batch` 这一步，`render_start` 以
「这一刀走批量交付」跳过，`job_wait` 与 `deliver_verify` 接着以「没有交付作业可验」跳过——
HTTP 200、时间线剪好、一个文件都没有；而只交 `deliver_items` 还会被 `preset_id`/`filename`
的必填挡在 422。现在两条媒体配方（`cut-from-media` **16** 步、`speech-to-captions`
**18** 步）里 `render_batch` 是真的一步：给了 items 就排，没给就那一行 `ran: false`
并指出单预设走上面两步。

实测：一条 3 秒素材只要 `deliver_items`，一趟排三条——`h264-720p-web` 1280×720、
`h264-1080x1920-vertical` 1080×1920（`fit: cover`）、`h264-1080-square` 1080×1080（`cover`），
三条 `succeeded`，三条 verdict 全真，ffprobe 量到的画幅与预设一字不差。

## 1.317 第四条配方：`reframe-for-platform`——跟着主体走的多画幅

口播与单主体画面要同时发横屏、竖屏、方形时，竖屏那一版不能只靠居中裁。这条配方把三扇已有的门
串成一次调用：

1. `timeline_edit` 落素材；给了 `subject_box`（`[cx, cy, w, h]`，0..1）就在同一批里给片段安上
   起始方框（`clip.mask`，一个 revision）；
2. `mask_track` 沿那个方框把主体的路径跟出来（整组一个 revision，交回
   `tracking.targets[].tracked_frames`）；
3. `clip_reframe` 把路径折成 `x/y/scale` 的跟拍关键帧（`max_scale` 1..4、`tolerance` ≤0.25，
   超限与跟不上都由 `reframe.plan` 点名说清）；
4. `render_batch` 按 `deliver_items` 一次排完（竖屏/方形建议 `fit: "cover"`），`job_wait` 等到终态，
   `deliver_verify` 逐条验画幅。

不给 `subject_box` 就不猜要跟谁：跟拍那两步明写 `ran: false`，多画幅照裁。这条配方
**13** 步，按配方顺序交回 **16 / 18 / 17 / 13** 行步骤日志。

这一轮同时修掉一个真缺陷：**数字静音的交付会让整条验交付抛异常**（`LOUDNESS_FAILED`）——静音轨、
纯动画这类片子本来就没有可量的响度。现在那一条是 `_check("loudness", "有声音可量", None, True,
note=…)`，verdict 照常成立，响度报「报不了」而不是把整趟打成 422。

## 1.318 谁能调、谁做了：具名令牌、作用域与一本动作台账

前面每一扇门都只认「带不带那枚共享密钥」。企业把剪辑交给流水线时，这不够：**谁能调**要能一只只
发、一只只吊销，**只读的行不行**要有人判，**谁做了什么**要引擎自己记一本账。这一档把这三件事做进
引擎，不改任何一条既有路由的语义。

* `agentcut tokens --add-label 名字 --scopes read|write|both` 现发一只密钥，**只印那一次**；
  数据目录里的 `tokens.json` 存的是 `secret_sha256`（64 位十六进制摘要），搜不到密钥本身。
  `agentcut tokens` 列名字、作用域与状态，`--revoke-label 名字` 当场吊销那一只，别人的照旧。
* 桌面端那枚自动生成的共享令牌也在表里，标 `local`、作用域齐全——本机那个界面不需要第二套身份。
* `SCOPE_DENIED`（403）：只读令牌做任何非 `GET/HEAD/OPTIONS` 的写都拒，`details.actor` 点名是
  哪一只令牌。审片与 BI 用的那只不该能改片子。
* 台账就是数据目录里那个 `audit.jsonl`，一行一次动作：`seq`（递增）、`ts`、`actor`、`method`、
  `path`、`status`、`duration_ms`，写与 401/403 都落，`request_id` / `project_id` 从载荷与路径里
  取。**纯读不落**——桌面端一直在轮询，全记就等于把动作埋进心跳里。企业可以把这个文件整本搬走。
* `GET /v1/agent/audit?limit=&actor=&project_id=` 与 MCP 同名工具 `agent_audit` 读的就是这本账
  （只读令牌也读得动）；台账关着时那扇门回 503 `AUDIT_UNAVAILABLE`，而不是回一本空账说「没人做过」。
* `--host` / `--allow-origin` 是服务化的两面：默认仍是 `127.0.0.1` 加 Origin 白名单。**要把引擎绑到
  非本机地址，必须先把 `AGENTCUT_TOKEN` 设成一个显式值**——自动生成的那枚只配听本机，否则一句
  `agentcut api --host 0.0.0.0` 就把一台能改片子的引擎挂到了局域网。`--no-audit` 关掉台账。
* 引擎那行 ready 事件多了四个现场读数：`bind`、`remote`、`tokens`、`audit`，外壳与运维脚本读的是
  同一行。

门禁是 `tests/serving_check.py`（五道），变异台六刀每刀红在自己的断言上：作用域不判了、读也记进
台账、吊销不生效、台账一行都不写、非本机绑定不再要显式令牌、`tokens.json` 里存明文密钥。最后那刀
值得记一句：原来的断言只看「有没有 `secret_sha256` 这个键」，六刀里唯一一把真能骗过它的正是
`_hash()` 直接 `return secret`——断言当场改成「必须是 64 位十六进制，且文件里搜不到任何一只发出去
的密钥」。

## 1.319 重启不丢活、同时渲几路、额度按名字拒

`deliver_verify` 会把一条交付验成一句答案，但如果引擎在交付排着的时候重启，那条答案根本等不到——
开工前先量了一眼（六单全投进去、按 PID 停掉引擎、在同一本库上重建 runtime、再按同一批 `request_id`
重投），读数是这样的：

* 六单全在，其中**五单根本没开始过**；重启之后六单一律 `failed / INTERRUPTED`；
* 同一批 `request_id` 重投：六次 HTTP 200，交回的是**同样那六个死作业**（`same_dead_job`
  六次为真），新文件零个——幂等凭据把「这一次请求」钉死在当年那个没渲成的作业上，自动流水线
  一次重启就永久卡住。

这一档把两种命运分开：

* **`queued`（没开始过）**：开机时重新入队，状态还是 `queued`，而且**由开机那台 runtime 自己渲完**——
  不需要谁再投一次；文件名在提交那一刻就占下了，接回来不会与别人抢。
* **`running`（渲到一半）**：还是 `INTERRUPTED`，但**那条收据一起删掉**。幂等在这里的说法是
  「同一个请求最多渲一次」，不是「那个失败的作业永远代表这个请求」；于是同一个 `request_id` 重投
  拿到的是一个新作业，并且真渲得出文件。ready 行与 `GET /v1/info` 都交回 `requeued`——找回来了几单。

`--render-slots` 是同时开几支 FFmpeg。槽数按用法定，不是按「机器能开多少」定：`desktop` 一槽（坐在
机器前的人不该被交付抢走 CPU，这条与 1.315 钉的占用额度是同一件事），`api` 两槽。这台 16 逻辑核上
量过的读数是四单 20 秒噪点竖屏交付：

| 槽数 | 四单总墙钟 | 相对一槽 |
|---|---|---|
| 1 | 25.14 s | 1.00 |
| 2 | 19.77 s | 1.27 |
| 3 | 18.88 s | 1.33 |

第三槽只再多 5%——一支 FFmpeg 自己就用满核，所以没有把默认值继续往上涨。三次跑法的交付总字节数
一字不差（528,526,476 B），并发没改动画片。

额度是「一个调用方最多压多少单」，两条都在**提交那一步**按名字拒（429），不等 FFmpeg 起来才说不行：

* `QUEUE_FULL`：`--max-queue`（默认 64）——`details` 交回 `pending` / `limit` / `incoming`；
* `QUOTA_EXCEEDED`：`--queue-per-token`（默认每只具名令牌 16 单）——`details` 多一个 `actor`，
  点名是谁家压的；别的令牌照投，不互相挡。
* **重放不占额度**：队列压满时重试同一个 `request_id` 照样拿回原来那一单——被挡回去的话，调用方
  只会以为那一单交付丢了，而它其实好好地排在里面。

`GET /v1/info` 多了一格 `queue`：`slots` / `live_slots` / `max_pending` / `pending_per_actor` /
`pending` / `requeued`，读的就是 runtime 自己那本数，不是抄的第二份。

门禁 `tests/ops_check.py` 五道：槽数（默认一槽、0 与 99 都夹回能用的范围、三槽真起三条线程）、
额度（压满被拒且点名、排空后还投得进、别人家不占名额、重放不占额度）、重启的两半命运
（半 A 用一台**不起线程**的 runtime 把三单钉在 `queued`，半 B 用真子进程引擎——先等它的确进入
`running` 再投第二单、再当场按 PID 连子树停掉），`/v1/info` 那一格与 runtime 自洽，契约面不因
`actor` 参数长出新东西。变异台七刀：排队那几单又被算成中断、中断那单的收据不放开、找回的单没人拉、
额度整个不判、重放也占额度、`info` 里的槽数是抄的常数、槽数不夹。

写这条门禁时撞到自己一次：两条腿都用了 `ops-render-0` 这个 `request_id`，于是「重启找回排队单」
那一腿读到的 `succeeded` 其实是上一条腿留下的交付——量具自己也得按名字分账，否则它测的是别人的
成绩单。现在每条腿有自己的前缀（`ops-tight-`、`ops-actor-`、`ops-boot-`、`ops-live-`）。


## 1.320 一台数据目录只服一台引擎：`GET /v1/metrics` 与输出盘底线

1.319 记下过一句「两台 runtime 共用一本库时，状态两头都会说谎」，当时它只是量尺上的意外；
这一档把它变成引擎界会挡的事。

* `engine.lock`（数据目录里一行 JSON）说的是**谁在服这份数据目录**：`pid / port / mode /
  started_at`。第二台引擎在**读令牌之前**就停下，那句点名是谁在服（PID、端口、模式、起于何时）
  与两条出路：`--data-dir` 换一个，或 `--allow-shared-data-dir` 明知故犯（它不写也不删租约——
  把别人的名字抹掉，第三台就会看「没有租约」堂而皇之进来）。
* `desktop` 模式遇到在服的引擎**不拒而是附上去**：双击第二个窗口不该变成「引擎起不来」。ready 行
  报的是那一台的端口与地址，`attached_to_pid` 说清附到了谁身上，读数（媒体根、输出根、
  `media_ready`…）一律从那一台的 `/v1/info` 现取，不抄第二份。**版本对不上时必须停下**——
  新界面配旧引擎会凑成一件谁也没测过的软件，这一条 1.319 已经用哈希核过一次。
* 引擎自己的 PID 也进了 ready 行（`pid`），运维脚本第一次能按名字收进程，而不是按镜像名。

`GET /v1/metrics?recent=1..500`（MCP 同名工具 `agent_metrics`，能力面三面同源）交回三张表：

* `queue`：`pending` / `slots` / `live_slots` / `max_pending` / `pending_per_actor` / `requeued`
  ——读的就是 runtime 自己那本数；
* `jobs`：`by_status`（五种状态各几单）、`failure_codes`（失败栽在哪些码上、各几次）、
  `duration_seconds` 的 `p50 / p95 / max`、`delivered_bytes`（真交付文件的字节数，量文件不估）；
* `outputs`：每块输出根的 `free_bytes / total_bytes / reserve_bytes`。

耗时那三个数取的是入库时间戳（秒的分辨率），所以短单子会读成 0 秒——读数说得出多少就说多少。

输出盘守的是**底线**，不是体积：`--min-free-mb`（默认 2048）低于就拒在排队之前，
503 `OUTPUT_DISK_TIGHT`，`details` 点名 `root / free_bytes / reserve_bytes`。为什么不是「按体积
预估」：CRF 编码的产物大小没有别处的可信来源，编一个常数等于把猜测写成度量。所以拒绝里那个
`needed_bytes` + `basis: "measured … B/s of preset …"` **只在这台引擎真渲过同一预设之后**才出现，
用的是那几单实测的字节/秒中位数；没渲过就说没渲过。

这一档顺手修掉一个真缺陷，而且是 metrics 那条腿读出来的：**取消一个还在排队的交付只返回一个
`cancelled` 对象、不写库**——于是 `/v1/jobs/{id}` 与 `job_wait` 里那一单永远算「还在排」，
`/v1/metrics` 也看不见它。现在取消会落进那本账（`by_status.cancelled` 当场多一格）。

门禁是 `tests/lease_check.py`（八道：服务、被拒、陈旧租约接得上、明知故犯不碰名字、`release()`
只放自己那份、`pid_alive` 两面、桌面模式附上去、`tokens` 一面不取租约）与
`tests/ops2_check.py`（五道，含反向腿：底线设 0 时正常出货不许被挡住）。变异台七刀：租约不认人、
第二个窗口不附上去、`release` 谁的都删、metrics 的槽数是抄的、底线不判、没渲过也编体积、
取消又不写库——每刀红在自家断言上，源码逐字节还原。