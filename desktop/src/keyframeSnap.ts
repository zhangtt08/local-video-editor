/**
 * 曲线编辑器里「拖到的那个位置」怎么变成写进工程的刻度。
 *
 * 格子按**绝对时间线**数：导出时每一帧落在合成时钟的整帧边界上，所以格线的相位由片段自己的
 * `position_ticks` 决定，而不是由「片段本地 0」决定。今天这条相位恒为 0——引擎的逐片段不变量
 * （timeline.py 的 TIME_NOT_ALIGNED：position 与 duration 必须整除所在轨的量子）就拦住了 off-grid
 * 的片段，实测 `clips.move` 半帧即被拒。写在这里是因为它便宜且是唯一正确的算法：不变量哪天松动，
 * 这里不必再想第二遍。看得见的那一半是：Agent 或检查器写在两个帧之间的**针**是合法的，拖着走会把
 * 它落回整帧上。
 *
 * 吸附对象除格线外还有播放头和这条曲线上没被拖动的关键帧（达芬奇 / AE 都这么做：已有那一针靠手是
 * 点不准的）。半径按屏幕像素算，所以放大后容差自动变窄，而不是写死一个刻度数。
 * 剪辑规则仍只有一处权威：这里决定「落在哪一格」，能不能写、撞不撞针，照旧由 reducer 说了算。
 */

export const SNAP_RADIUS_PIXELS = 4;
const PLOT_PIXELS = 924;

export type KeyframeLattice = {
  /** 片段自己：起点决定格线的相位，长度就是引擎会接受的上界。 */
  clip: { position_ticks: number; duration_ticks: number };
  /** 帧（或采样）周期，刻度。 */
  quantum: number;
  /** 当前可见区间的刻度数，用来把屏幕像素换成刻度。 */
  span: number;
  /**
   * 画布的绘图宽度，与 span 同一套坐标（CurveEditor 的 WIDTH=924）。不给就用那个兜底值：
   * 换一套坐标系时这里算出的吸附半径会跟着屏幕比例走，而不是停在旧的像素数上。
   */
  plot?: number;
};

/** 片段起点不在整帧上时，帧格子在片段本地刻度里错开多少。 */
export function latticePhase(positionTicks: number, quantum: number): number {
  if (quantum <= 0) return 0;
  return ((-Math.trunc(positionTicks) % quantum) + quantum) % quantum;
}

/**
 * 把提议的片段本地刻度折成一个可写的刻度。
 *
 * `attract` 关掉时只有格线参与（数值框、按播放头加针：那两个动作要的就是那个精确位置，不该被旁边
 * 一根针拽走）。选出的落点一定在 `[0, duration_ticks]` 内，所以吸附永远不会把点送到引擎必拒的地方。
 */
export function keyframeTick(
  at: number,
  lattice: KeyframeLattice,
  enabled: boolean,
  landmarks: { playhead: number | null; keys: number[]; attract: boolean },
  radiusPixels = SNAP_RADIUS_PIXELS,
): number {
  const duration = lattice.clip.duration_ticks;
  const clamp = (value: number) => Math.max(0, Math.min(duration, value));
  if (!enabled || lattice.quantum <= 0) return clamp(Math.round(at));
  const phase = latticePhase(lattice.clip.position_ticks, lattice.quantum);
  const grid = phase + Math.round((at - phase) / lattice.quantum) * lattice.quantum;
  if (!landmarks.attract) return clamp(grid);
  const tolerance = (radiusPixels * lattice.span) / Math.max(1, lattice.plot ?? PLOT_PIXELS);
  let best = grid;
  let bestDistance = Math.abs(at - grid);
  const marks = [...landmarks.keys, ...(landmarks.playhead === null ? [] : [landmarks.playhead])];
  for (const mark of marks) {
    if (mark < 0 || mark > duration) continue;
    const distance = Math.abs(at - mark);
    if (distance <= tolerance && distance < bestDistance) {
      best = mark;
      bestDistance = distance;
    }
  }
  return clamp(best);
}
