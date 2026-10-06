# v1 接口约定

权威 schema 在 `GET /v1/contracts`，OpenAPI 在 `/openapi.json`；不要维护另一套手写命令定义。
HTTP 使用 `Authorization: Bearer <AGENTCUT_TOKEN>`。JSON 请求严格校验类型和未知字段。

## 入口

| HTTP | MCP 工具 | 语义 |
|---|---|---|
| GET /v1/capabilities | editor_capabilities | 实际可用能力 |
| GET /v1/contracts | editor_contracts | 权威 JSON Schema |
| POST /v1/projects | project_create | 幂等创建 |
| GET /v1/projects?limit=100&offset=0 | project_list | 分页项目摘要 |
| GET /v1/projects/{id}?revision=N | project_get | 当前或历史项目 |
| GET /v1/projects/{id}/history?limit=100&offset=0 | project_history | 版本审计摘要 |
| POST /v1/projects/{id}/edits | timeline_edit | 批量命令 |
| POST /v1/projects/{id}/restore | project_restore | 历史恢复为新版本 |
| POST /v1/projects/{id}/clips/{c}/silence | clip_silence | 只读扫描静音并取回剪切命令（`apply`/`dry_run` 在该工具里固定为 false） |
| POST /v1/projects/{id}/tracks/{t}/silence | — | 整轨扫描：逐片段报告跳过原因，合并成一条命令计划 |
| POST /v1/projects/{id}/clips/{c}/loudness | — | 响度表读数与建议增益；`apply=true` 时引擎一次写入 |
| POST /v1/projects/{id}/tracks/{t}/loudness | — | 整轨响度对齐：逐片段测量并合并成一次写入 |
| POST /v1/projects/{id}/markers/split | marker_split | 按标记分割：只出普通 `clip.split` 计划，`apply` 才写入 |
| `clip.slip` / `clip.slide`（`/edits`） | timeline_edit | 划动素材窗口 / 左右滑移，两侧相邻段各自补让 |
| POST /v1/projects/{id}/clips/{c}/track | clip_track | 分析画面并把遮罩路径一次写成关键帧（与 `/edits` 同一事务语义） |

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
每批 1..100 条；id 只允许字母、数字、下划线、连字符，最长 64 字符。

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
| GET /v1/projects/{id}/render-plan?preset_id=&revision= | render_plan | 只读编译 RenderPlan 与 FFmpeg 参数预览 |
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
| clip.speed | clip_id, speed_percent, ripple? | 整数 25..400；默认 ripple=true，保留源范围并向下对齐结果时长；音高保持 |
| clip.color | clip_id, color | exposure(-2..2 EV)、contrast(0..2)、saturation(0..2)，默认 0/1/1 |
| clip.text | clip_id, text | 替换文字内容/字号/颜色，只能操作文字片段 |
| clip.fade | clip_id, property, duration_ticks, mode | opacity/gain；in/out/both；替换该属性关键帧，双向时每边不超过片段一半 |
| captions.import | track_id, asset_id, srt, offset_ticks? | 原子创建新字幕轨、文字素材与片段；最多 2000 条，重叠拒绝并整体回滚 |

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
  替换该片段上这个属性的旧关键帧，其它属性不动。存在的理由是 `edits` 的单批上限是 100 条命令——用
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
  （裸文件名、必须 `.mp4`），且**批内不得重名**。
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
