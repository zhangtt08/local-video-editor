/**
 * 时间线上针的分道：同一秒上的两枚针不许画在同一堆像素里。
 *
 * 实测（1.112 的打包 exe + 构建好的渲染层）：一条片段上 `opacity` 与 `x` 各有一枚针落在 1.0 秒时，
 * 两个按钮的矩形一模一样，`document.elementFromPoint` 在其中一个的中心上回的是另一个——那一枚鼠标点
 * 不到，连「点一下跳过去」都做不到。修法不是把它们横向错开几像素（13px 宽的对象错开照样重叠），而是
 * 一条属性一道：谁先出现谁在第一道，超出画得下的道数的属性**不画**，改成一枚 `+N` 的牌子，点它进动画
 * 曲线——宁可少画，也不留一枚点不到的针。
 */

import type { Keyframe, Property } from "./engine";

export const LANE_PITCH_PIXELS = 12;
/** 片段底部留给针道的像素高（`.clip` 的上下内边距之外），界面不许在别处再数一遍。 */
export const NEEDLE_AREA_PIXELS = 37;

export type NeedleRows = { rowOf: Map<Property, number>; lanes: number; hidden: Property[] };

/** 按属性第一次出现的顺序分道；超过 `capacity` 条的属性进 `hidden`（界面据此画 `+N`，不画点不到的针）。 */
export function needleRows(keys: { property: Property }[], capacity: number): NeedleRows {
  const order: Property[] = [];
  for (const key of keys) if (!order.includes(key.property)) order.push(key.property);
  const rowOf = new Map<Property, number>();
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
export const needleId = (key: Keyframe): string => `${key.property}|${key.at_ticks}`;

