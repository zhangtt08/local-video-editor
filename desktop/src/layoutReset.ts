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

/** `measured` 是点下去那一刻 `.timeline` 真量到的高度（像素）；量不到时回默认。 */
export function resetLayout(measured: number): [number, number, number] {
  const room = Math.round(measured);
  return [300, 340, room > 0 ? Math.min(DEFAULT_TIMELINE, room) : DEFAULT_TIMELINE];
}
