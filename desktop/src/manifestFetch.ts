/**
 * 监视器那条 `preview-manifest` 的唯一 URL，与「现在画的是哪几段」的唯一判断。
 *
 * 引擎自 1.183 起收 `clips` 子集，工程级那几个键（`mixed_track_ids`、`links`、`track_blend_modes`、
 * `revision`）在子集请求里仍按整份给——所以点名可视那几段省掉整份清单，却不改变任何一层画面的算法。
 * 检查器那条链接状态轮询共用同一条式子（一个意图一个实现）。
 *
 * 两个函数分得很清，因为两种调用点要的形态不同：`Engine.request` 自己拼 `fetch(`${base}${path}`)`，
 * 给它绝对 URL 就会把前缀拼两次（1.187 那次监视器黑屏就是这个）；裸 `fetch` 那一头才需要带 base 的
 * 完整 URL。所以 `manifestPath` 是唯一的算式，`manifestUrl` 只是它前面加个 base。
 *
 * 这里只声明结构类型，不 import `engine`：那条链会从 engine 绕回来，两边谁都不该依赖谁。
 */

export type MonitorClip = {
  id: string;
  track_id: string;
  position_ticks: number;
  duration_ticks: number;
};
export type MonitorTrack = { id: string; kind: string; hidden: boolean; muted: boolean };
export type MonitorProject = {
  tracks: MonitorTrack[] | Record<string, MonitorTrack>;
  clips: Record<string, MonitorClip>;
};

/**
 * `clipIds` 的三种说法必须彼此分得开：
 * `null` ＝没点名（整份，1.183 以前那条路）；`[]` ＝「这一段都别编译」（`no_clips=1`，列表参数不可能
 * 为空，所以这句需要自己的开关）；非空 ＝只编译被点名的那些段。
 */
export const manifestPath = (
  projectId: string,
  revision: number,
  sequenceId: string | null,
  clipIds: readonly string[] | null
) => {
  const params = [`revision=${revision}`];
  if (clipIds && !clipIds.length) params.push("no_clips=1");
  for (const id of clipIds && clipIds.length ? [...new Set(clipIds)] : []) {
    params.push(`clips=${encodeURIComponent(id)}`);
  }
  if (sequenceId) params.push(`sequence_id=${encodeURIComponent(sequenceId)}`);
  return `/v1/projects/${encodeURIComponent(projectId)}/preview-manifest?${params.join("&")}`;
};

/** 给裸 `fetch` 的那一头：同一个算式，前面多个 base。 */
export const manifestUrl = (
  base: string,
  projectId: string,
  revision: number,
  sequenceId: string | null,
  clipIds: readonly string[] | null
) => `${base}${manifestPath(projectId, revision, sequenceId, clipIds)}`;

/**
 * 播放头那一格里真的会被画出来的那些段：画面轨要没隐藏、声音轨要没静音——与 `Preview.tsx` 里那两个
 * 循环同一判据，判断只写这一处。空隙里什么都没有时交回空集合（式子会把它说成 `no_clips=1`）。
 */
export const monitorClipIds = (project: MonitorProject, ticks: number): string[] => {
  const wanted: string[] = [];
  for (const track of Object.values(project.tracks)) {
    if (track.kind !== "video" && track.kind !== "audio") continue;
    if (track.kind === "video" ? track.hidden : track.muted) continue;
    for (const clip of Object.values(project.clips)) {
      if (clip.track_id !== track.id) continue;
      if (ticks < clip.position_ticks || ticks >= clip.position_ticks + clip.duration_ticks) continue;
      wanted.push(clip.id);
    }
  }
  return wanted;
};

/**
 * 同一版工程里一段片段的编译结果是不变的，所以按 `project` 对象身份合并上一批点名的段就够了：
 * 播放头跨过一格时新段补进来、旧段留着，媒体节点与焦点都不重建；换工程或换版本（新对象）整个重来。
 */
export const mergePlans = <T extends { clips: Record<string, unknown> }>(previous: T, next: T): T => ({
  ...next,
  clips: { ...previous.clips, ...next.clips },
});
