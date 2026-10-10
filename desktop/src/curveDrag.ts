/**
 * 曲线编辑器里「拖一下」那层算术：数值按这条属性的步长量化，整组一起被属性量程与片段边界夹住。
 *
 * 抽出来不是因为行为要改——它一字不改——而是因为 1.116 之后量过两次才明白：这层判断此前只写在组件里，
 * 没有纯函数可以单测，所以**只有实测、没有门禁**，下一个改它的人不会得到红灯。这里的夹具数字就是那两次
 * 装机实测读回来的：一条片段上不透明度 0.5 与 0.9 两枚一起拖，抓哪一枚、往上拖多远，落库的都是
 * `0.6 / 1.0`——被抓住的那枚想去的 1.4 并没有被单独写出去，而是整组按「离上限最近的那一枚只剩 0.1」
 * 一起只走 0.1。这就是这条链子上唯一的夹法：先量化（步长）、再整组夹（量程与片段两头）、最后逐枚落值。
 */

/**
 * 数值框 / 时间框里的字要交出去之前的一步判断：空串、乱码、NaN 都不算改；按 Esc 之后离开焦点不算改；
 * 越出这条属性的带就先夹回来（`min`/`max` 是**界面上说的那个单位**，除法仍由调用方做）；与当前值一样的
 * 就不发命令。返回 `null` 表示「什么都别写」。打字进来的数**不**过格子——手敲要的就是打的那个值，
 * 格子只属于拖（1.109 定的口径）。
 */
export function bandEntry(
  text: string,
  current: number,
  band: { min: number; max: number },
  cancelled = false,
): number | null {
  if (cancelled || !text.trim()) return null;
  const typed = Number(text);
  if (!Number.isFinite(typed)) return null;
  const bounded = Math.max(band.min, Math.min(band.max, typed));
  return bounded === current ? null : bounded;
}
/** 一条属性的数值带，全部来自 `EFFECT_FIELDS` / `MASK_ANIM_FIELDS` 那几个字段，不另起数。 */
export type ValueBand = { min: number; max: number; step: number; factor: number };

/** 工程里存的是 0..1 这类归一化值，界面说的是「百分之几、几度」：带换算全在这一处。 */
export const bandEdges = (band: ValueBand): { hardMin: number; hardMax: number } => ({
  hardMin: band.min / band.factor,
  hardMax: band.max / band.factor,
});

/** 拖到的数值先落到这条属性的步长格子上，再被量程夹住——所以答案永远在界面允许、引擎也认的带里。 */
export function quantizeToBand(value: number, band: ValueBand): number {
  const { hardMin, hardMax } = bandEdges(band);
  return Math.max(hardMin, Math.min(hardMax, Math.round((value * band.factor) / band.step) * band.step / band.factor));
}

export type CurvePoint = { at_ticks: number; value: number };

/**
 * 整组能走多远，由**这一组自己**的两头决定：时间上不能越出片段，数值上不能越出量程。
 * 抓的那一枚想去 1.4 不重要——旁边那枚只剩 0.1 的余量，整组就只走 0.1。
 */
export function groupShift(points: CurvePoint[], band: ValueBand, durationTicks: number, dt: number, dv: number): { dt: number; dv: number } {
  if (!points.length) return { dt: 0, dv: 0 };
  const times = points.map((point) => point.at_ticks);
  const values = points.map((point) => point.value);
  const { hardMin, hardMax } = bandEdges(band);
  return {
    dt: Math.max(-Math.min(...times), Math.min(durationTicks - Math.max(...times), dt)),
    dv: Math.max(hardMin - Math.min(...values), Math.min(hardMax - Math.max(...values), dv)),
  };
}

/**
 * 落值时逐枚再过一次这条属性的格子。整组的余量是「上限减某枚的值」这种减法算出来的，
 * `1 - 0.9` 在二进制里是 0.09999999999999998，于是加在未选中的那些枚上就写出一个**不在格子上**的数
 * ——1.116 之后那两次装机实测里，工程最终存的是 0.6 与 1.0，因为引擎把漂移抹掉了；把格子放在这一步
 * 重算一次，草稿就等于要落库的那份，不再依赖对面替我们收拾。
 */
export function applyShift<T extends CurvePoint>(points: T[], shift: { dt: number; dv: number }, band: ValueBand): T[] {
  return points.map((point) => ({ ...point, at_ticks: point.at_ticks + shift.dt, value: quantizeToBand(point.value + shift.dv, band) }));
}
