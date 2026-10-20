/**
 * 时间线上针的分道：同一秒上的两枚针不许画在同一堆像素里。
 *
 * 实测（1.112 的打包 exe + 构建好的渲染层）：一条片段上 `opacity` 与 `x` 各有一枚针落在 1.0 秒时，
 * 两个按钮的矩形一模一样，`document.elementFromPoint` 在其中一个的中心上回的是另一个——那一枚鼠标点
 * 不到，连「点一下跳过去」都做不到。修法不是把它们横向错开几像素（13px 宽的对象错开照样重叠），而是
 * 一条属性一道：谁先出现谁在第一道，超出画得下的道数的属性**不画**，改成一枚 `+N` 的牌子，点它进动画
 * 曲线——宁可少画，也不留一枚点不到的针。
 */

export const LANE_PITCH_PIXELS = 12;
/** 片段底部留给针道的像素高（`.clip` 的上下内边距之外），界面不许在别处再数一遍。 */
export const NEEDLE_AREA_PIXELS = 37;
/** 第一道针离片段底多少像素：`.clip-keyframe` 的 `bottom` 就是它，往上一道一道叠。 */
export const NEEDLE_BOTTOM_PIXELS = 1;
/** 一枚针自己的命中盒有多高：CSS 里 `.clip-keyframe` 的 `height` 必须与它同数，不然相邻两道互盖。 */
export const NEEDLE_HIT_PIXELS = 12;

/** ◆ 那一枚的盒子有一半在 `left` 之外（CSS 用 `translateX(-50%)` 把它钉在中心），所以夹的必须是
 *  中心：`left + 这一半` 才是针的右边缘。1.112 起这句把 16px 当成了整块牌子的宽度，量错了。
 *  1.219：两端都按这一半夹。左端原来写的是字面 6，比针自己的半宽还小——贴边那一枚有半个盒子伸出
 *  片段之外，`overflow: hidden` 当场裁掉（量到的是针 329 起、片段 330 起），右端同理越过接缝去踩邻段。 */
export const NEEDLE_HALF_PIXELS = 10;
/** 「+N」那块牌子从右边缘往里占住的距离：CSS 给它 `right: 8` 与 `min-width: 24`，两处必须一起改。 */
export const CHIP_KEEP_PIXELS = 32;

/** 转场牌子占住片段底部那一条带：`.transition-badge` 的 `bottom`/`height` 由这里下发。
 *  1.218 之前它写的是 `top: 33px`——那是照着一档行高猜的，行高一变它就压到针道上（实测：牌子
 *  [330,579,31,18] 正好盖住那条片段第一枚针 [329,582,16,12]）。改成从片段底往上数，两处同一条尺。 */
export const SEAM_BADGE_BOTTOM_PIXELS = 1;
export const SEAM_BADGE_HEIGHT_PIXELS = 18;
/** 片段在自己的那一行里上下各留多少像素（CSS `.clip` 的 `top`/`bottom`）：牌子长在行上、针长在片段上，
 *  要把「离片段底」这一句说准，就必须有这个数——门禁断的就是 CSS 与它同数。 */
export const LANE_CLIP_PAD_PIXELS = 5;
/** 牌子最短多宽：转场再短也要点得着它（CSS 那句 `min-width` 的同一份数）。 */
export const SEAM_BADGE_MIN_WIDTH_PIXELS = 24;

/** 这一枚针会不会压在转场牌子底下：抓取盒（第 `row` 道那一横条，中心 `centre`，左右各伸半宽）
 *  与牌子那块矩形相交就不相容。规矩与分道那一条相同——**宁可少画，也不留一枚点不到的针**：
 *  画不下的那枚进「+N」那一格，出路还是点开动画曲线。 */
export function underSeamBadge(row: number, centre: number, badgeWidth: number): boolean {
  if (badgeWidth <= 0) return false;
  const low = NEEDLE_BOTTOM_PIXELS + row * LANE_PITCH_PIXELS;
  if (low >= SEAM_BADGE_BOTTOM_PIXELS + SEAM_BADGE_HEIGHT_PIXELS) return false;
  if (low + NEEDLE_HIT_PIXELS <= SEAM_BADGE_BOTTOM_PIXELS) return false;
  return centre - NEEDLE_HALF_PIXELS < badgeWidth;
}

/** 一道曲线叫什么：片段自己的属性名，或第二路画面那一层的复合键（`layer0:rotation`）。
 *  1.208 起两样都进同一张分道表——一条属性一道这一句对两者都成立，所以不必分两套道。 */
export type LaneKey = string;

export type NeedleRows = { rowOf: Map<LaneKey, number>; lanes: number; hidden: LaneKey[] };

/** 按属性第一次出现的顺序分道；超过 `capacity` 条的属性进 `hidden`（界面据此画 `+N`，不画点不到的针）。 */
export function needleRows(keys: { property: LaneKey }[], capacity: number): NeedleRows {
  const order: LaneKey[] = [];
  for (const key of keys) if (!order.includes(key.property)) order.push(key.property);
  const rowOf = new Map<LaneKey, number>();
  order.slice(0, Math.max(0, capacity)).forEach((property, index) => rowOf.set(property, index));
  return { rowOf, lanes: rowOf.size, hidden: order.slice(Math.max(0, capacity)) };
}

/** 画得下几道：留给针的像素高除以道距，至少一道。 */
export function laneCapacity(availablePixels: number, pitch = LANE_PITCH_PIXELS): number {
  return Math.max(1, Math.floor(availablePixels / pitch));
}

/**
 * 一组的身份：针属于「哪条曲线的哪一格」，所以选中标识用工程里存的那个刻度，不用画出来的像素。
 * 拖动之后刻度会变，一次抓取落库就把这一组清掉——留着那串旧刻度，下一次框选会挑中一枚已经不在那儿的针。
 */
export const needleId = (key: { property: LaneKey; at_ticks: number }): string => `${key.property}|${key.at_ticks}`;

