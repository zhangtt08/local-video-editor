/** 「重置布局」写回的那三个数。
 *
 * 面板回默认；时间线那一格回的是**这一屏量到的**那一个高度，不是写死的 300。
 * 为什么：`.editor .timeline` 那条 clamp 会在矮窗里让步——写死 300 等于应用自己
 * 要了一个装不下的数，紧接着那句「窗口太矮」就回头抱怨用户（1.225 在 1040×660
 * 量到的就是这一条：重置之后 `wanted 300 / got 212`）。
 * 这里读的是 `Timeline` 已经在读的那一个盒子，不写第二条 `calc(100dvh …)`——
 * 抄一份就成了第二条公式，改一处会漏一处。
 */
export const DEFAULT_TIMELINE = 350;

/** 没人拖过时，第一次打开工作台的时间线有多高。
 *
 * 写死 350 在 808 高的窗口里会吃掉上半屏：素材库只剩一行半卡片，看着像坏了而不是像能滚。
 * 这一档按窗口高度给（0.34，上限仍是 `DEFAULT_TIMELINE`、下限 240），拖过的人仍以自己存的为准——
 * 它只决定「第一次打开长什么样」，不参与 `resetLayout` 那条以量到的盒子为准的规矩。
 */
export function firstRunTimeline(viewport: number, tracks = 0): number {
  if (!Number.isFinite(viewport) || viewport <= 0) return DEFAULT_TIMELINE;
  // 只看窗口高会漏掉一半事实：四条轨的时间线要 116 + 4×68 ≈ 390px 才装得下，
  // 按 0.34 给只有 275px —— 主画面轨就被挤到折线以下，而它恰恰是要编辑的那一条。
  const byWindow = Math.round(viewport * 0.34);
  const byTracks = tracks > 0 ? RULER_BAND_PIXELS + tracks * TRACK_ROW_PIXELS : 0;
  return Math.max(240, Math.min(DEFAULT_TIMELINE, Math.max(byWindow, byTracks)));
}

/** 时间线卡片里除轨道以外的那一截：工位行 34 + 工具行 54 + 标尺 28。 */
export const RULER_BAND_PIXELS = 116;
/** 一条轨的高度，与 `Timeline.ROW` 同一个数（那一处是引擎侧的常量，这里是布局侧的）。 */
export const TRACK_ROW_PIXELS = 68;


/** `measured` 是点下去那一刻 `.timeline` 真量到的高度（像素）；量不到时回默认。 */
export function resetLayout(measured: number): [number, number, number] {
  const room = Math.round(measured);
  return [300, 340, room > 0 ? Math.min(DEFAULT_TIMELINE, room) : DEFAULT_TIMELINE];
}
