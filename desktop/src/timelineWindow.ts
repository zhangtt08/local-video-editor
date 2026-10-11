import { TIMEBASE } from "./time";

/** 1.131：时间线只画窗口里的那一段。
 *
 * 装机量出来的事实（`scripts/renderer_scale.cjs`，打包产物 + 冻结引擎，两万段）：页面画了 **0 段**，
 * 渲染进程涨到 2,923 MB 与 14.8 秒用户态 CPU 之后消失，此后每一次 `Runtime.evaluate` 都在 5 秒上
 * 限时内没有回话（连续 200 多秒），而同一时刻引擎答同一条 GET 只用 0.7 秒、照样交出两万段。所以
 * 瓶颈不是「算不过来」，是「一次把两万张卡片全建出来」。窗口化把建卡片这件事绑在看得见的宽度上，
 * 与段的总数无关。
 *
 * 这里只回答「哪些段该建」，坐标还是 `Timeline.tsx` 那一处算：一条卡片的本来的位置是
 * `left = position_ticks / TIMEBASE * px`，所以「看得见」= 这条区间和窗口的像素区间相交。
 */

export type TickRange = { from: number; to: number };

/** 窗口两边各多涂两秒：贴着边缘的段不至于一边有一边没有，拖到边缘时也不会「先到后画」。 */
export const WINDOW_PAD_TICKS = 2 * TIMEBASE;

export function laneTicks(
  view: { left: number; width: number },
  px: number,
  head: number,
  totalTicks: number,
): TickRange {
  if (!(px > 0) || !(view.width > 0)) return { from: 0, to: totalTicks };
  const from = Math.min(totalTicks, Math.max(0, ((view.left - head) / px) * TIMEBASE - WINDOW_PAD_TICKS));
  const to = Math.min(totalTicks, Math.max(0, ((view.left - head + view.width) / px) * TIMEBASE + WINDOW_PAD_TICKS));
  return { from, to: Math.max(from, to) };
}

/** 框选正在拖的时候，窗口要先把那一框的时间跨度整个包进来：拖过的每一条段都得存在，
 *  旧的按 DOM 矩形判定命中的逻辑才继续成立（命中判定本身一个字都不改）。 */
export function unionRange(a: TickRange, b: TickRange | null): TickRange {
  if (!b) return a;
  return { from: Math.min(a.from, b.from), to: Math.max(a.to, b.to) };
}

export type Painted<T> = { shown: T[]; hidden: number };

/** 挑出要建卡片的段。`always` 是必须画的那些：被挑中的段即便在窗口外也要画出来，
 *  否则「挑中一整组再横向拖」这类既有手感会因为裁切而变味。 */
export function paintClips<T extends { id: string; position_ticks: number; duration_ticks: number }>(
  clips: T[],
  range: TickRange,
  always?: Set<string> | null,
): Painted<T> {
  const shown: T[] = [];
  let hidden = 0;
  for (const clip of clips) {
    const end = clip.position_ticks + clip.duration_ticks;
    const inside = end >= range.from && clip.position_ticks <= range.to;
    if (inside || (always?.has(clip.id) ?? false)) shown.push(clip);
    else hidden += 1;
  }
  return { shown, hidden };
}

/** 整个时间线还差多少段没建：那句「窗口外还有 N 段」用的就是这一个数，
 *  不许视图那边再数一遍，否则两处会有一天说出不同的数。 */
export function countHidden<T extends { id: string; position_ticks: number; duration_ticks: number }>(
  clips: T[],
  range: TickRange,
  always?: Set<string> | null,
): number {
  return paintClips(clips, range, always).hidden;
}

export const WINDOW_NOTE = (hidden: number): string =>
  `窗口外还有 ${hidden} 段没有画（它们仍在工程里，也在导出里）：往那个方向滚就出现。`;

/** 尺子上的刻度间隔：一秒一格只在放大到那个程度时才必要，与以前那一处判断同一个表。 */
export function rulerStep(px: number): number {
  return px >= 150 ? 1 : px >= 70 ? 2 : px >= 34 ? 5 : 10;
}

/** 尺子上该出现哪些整秒。以前是「从 0 数到时间线结尾」，两万秒就是两万对 `<span>`——和片段卡片
 *  同一个毛病：建的东西由整条时间线的长度决定，而不是由看得见的宽度决定。 */
export function rulerSeconds(range: TickRange, totalTicks: number, px: number): number[] {
  const step = rulerStep(px);
  const seconds = totalTicks / TIMEBASE;
  const from = Math.max(0, Math.floor(range.from / TIMEBASE / step) * step);
  const to = Math.min(seconds, Math.ceil(range.to / TIMEBASE / step) * step);
  const marks: number[] = [];
  for (let second = from; second <= to; second += step) marks.push(second);
  return marks;
}
