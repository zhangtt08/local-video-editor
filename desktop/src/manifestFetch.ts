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
 *
 * 顺序：轨道按工程里那份 `tracks` 的顺序，同一条轨道内按起点。这个顺序只影响 query 里段名的先后，
 * 引擎按集合处理（`manifestPath` 去重），所以它不是语义，只是可复现。
 *
 * 每一段在每一格里都会被画一遍，所以这里不能是「每条轨道 × 每个片段」的扫描：两万段一条轨道实测
 * 一次 4.2 ms（一帧预算的 25%），八条轨道一次 33.9 ms（两帧多）。改成按轨道分桶 + 起点排序 +
 * 「最远伸到哪」的前缀最大值，一次问话只二分到那一小段候选上（`tests/desktop_linksubset_check.ts`
 * 拿一份逐段暴力扫出来的表与它对每一格，含转场重叠那一格）。索引挂在 `project` 对象身份上，
 * 与 `mergePlans` 用的是同一条假设：换一版工程就是新对象，整个重来。
 */
const indexCache = new WeakMap<MonitorProject, Map<string, Bucket>>();

type Bucket = {
  /** 起点，升序。 */
  start: number[];
  /** 与 `start` 等长的前缀最大值：到这里为止，哪一段最远伸到哪个刻度。 */
  reach: number[];
  /** 与上面两条一一对应的段。 */
  clip: MonitorClip[];
};

const firstAbove = (values: number[], limit: number) => {
  // 第一条 > limit 的下标；全都不大于就交回长度。
  let low = 0;
  let high = values.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (values[mid] > limit) high = mid;
    else low = mid + 1;
  }
  return low;
};

const lastAtMost = (values: number[], limit: number) => {
  // 最后一条 <= limit 的下标；一条都不满足就交回 -1。
  let low = 0;
  let high = values.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (values[mid] <= limit) {
      found = mid;
      low = mid + 1;
    } else high = mid - 1;
  }
  return found;
};

const bucketsOf = (project: MonitorProject): Map<string, Bucket> => {
  const cached = indexCache.get(project);
  if (cached) return cached;
  const rows = new Map<string, { clip: MonitorClip; end: number }[]>();
  for (const clip of Object.values(project.clips)) {
    const list = rows.get(clip.track_id);
    const row = { clip, end: clip.position_ticks + clip.duration_ticks };
    if (list) list.push(row);
    else rows.set(clip.track_id, [row]);
  }
  const built = new Map<string, Bucket>();
  for (const [trackId, list] of rows) {
    list.sort((a, b) => a.clip.position_ticks - b.clip.position_ticks);
    const start: number[] = [];
    const reach: number[] = [];
    const clip: MonitorClip[] = [];
    let far = -1;
    for (const row of list) {
      start.push(row.clip.position_ticks);
      clip.push(row.clip);
      far = row.end > far ? row.end : far;
      reach.push(far);
    }
    built.set(trackId, { start, reach, clip });
  }
  indexCache.set(project, built);
  return built;
};

export const monitorClipIds = (project: MonitorProject, ticks: number): string[] => {
  const buckets = bucketsOf(project);
  const wanted: string[] = [];
  for (const track of Object.values(project.tracks)) {
    if (track.kind !== "video" && track.kind !== "audio") continue;
    if (track.kind === "video" ? track.hidden : track.muted) continue;
    const bucket = buckets.get(track.id);
    if (!bucket) continue;
    // 落在这那一格的段一定满足「起点 <= 这一格」且「结束 > 这一格」；前者给上界，后者靠前缀最大值
    // 给下界——两头一夹就是候选，转场那一小段重叠（同轨两段同时占住这一格）也不会被少算。
    const from = firstAbove(bucket.reach, ticks);
    const to = lastAtMost(bucket.start, ticks);
    for (let index = from; index <= to; index += 1) {
      const clip = bucket.clip[index];
      if (ticks < clip.position_ticks + clip.duration_ticks) wanted.push(clip.id);
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
