/**
 * 时间线上的框选：把「手指拉出来的那个矩形」折成被挑中的针。
 *
 * 只认屏幕上**真画出来**的那几枚矩形——画不下的属性根本没进 DOM（1.113 定的「宁可少画，也不留一枚点不
 * 到的针」），所以框不可能挑中一枚鼠标点不到的针；拖动时那枚影子是装饰（`pointer-events: none`），也不
 * 许被挑中。坐标一律用视口像素（`getBoundingClientRect` 那一份），界面读同一份矩形交进来，这里不掺刻度，
 * 也就不存在「框选用一套坐标、针自己用另一套」的两个落点。
 */

export type PixelBox = { x0: number; y0: number; x1: number; y1: number };

/** 两像素以内算「点了一下」，与时间线那枚针的拖动阈值同一口径。 */
export const MARQUEE_MIN_PIXELS = 2;

/**
 * 针道左右各让开的像素。界面上的边不是装饰：修剪柄占最外 7px，淡入淡出的角柄占 9..18px，
 * 框选的手若压上去，那两个动作就没地方点了。`desktop_keyframemarquee_check.ts` 把这两个数与样式表对起来。
 */
export const MARQUEE_INSET_PIXELS = 20;

export type PaintedNeedle = { id: string; box: PixelBox };

/** 从起点拖到终点：往回拉也是同一个矩形，所以框不认拖动方向。 */
export function marqueeBox(from: { x: number; y: number }, to: { x: number; y: number }): PixelBox {
  return { x0: Math.min(from.x, to.x), y0: Math.min(from.y, to.y), x1: Math.max(from.x, to.x), y1: Math.max(from.y, to.y) };
}

/** 重叠才算选中，且至少压进一像素：只在边上擦过的那枚还在框外，用户也看不出它被挑中了。 */
export function overlaps(item: PixelBox, band: PixelBox): boolean {
  return item.x0 < band.x1 && item.x1 > band.x0 && item.y0 < band.y1 && item.y1 > band.y0;
}

/** 框里这几枚，顺序按画出来的先后（与针道同一份顺序），去重。 */
export function hitsInBand(painted: PaintedNeedle[], band: PixelBox): string[] {
  return [...new Set(painted.filter((item) => overlaps(item.box, band)).map((item) => item.id))];
}

/** 拉一次框的落定：按住 Shift 是「加进这一组」，否则整组换成框里的这几枚（框到空处就是清场）。 */
export function commitPick(base: string[], hits: string[], additive: boolean): string[] {
  return additive ? [...new Set([...base, ...hits])] : hits;
}

/** Shift 点一枚针：在组里就摘出去，不在就加进来——加在末尾，组的先后不改（改了就等于给用户重排）。 */
export function togglePick(base: string[], id: string): string[] {
  return base.includes(id) ? base.filter((picked) => picked !== id) : [...base, id];
}

/** 拉开没拉开：横竖任一方向过两像素都算，所以竖着拖出一条细框也能整道挑中。 */
export function draggedEnough(from: { x: number; y: number }, to: { x: number; y: number }): boolean {
  return Math.abs(to.x - from.x) >= MARQUEE_MIN_PIXELS || Math.abs(to.y - from.y) >= MARQUEE_MIN_PIXELS;
}
