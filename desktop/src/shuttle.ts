/** 1.281：J/K/L 的速度阶梯只有一处——按一次 1×，同一个方向再按就是 2× / 4× / 8×。
 *
 *  反方向从 1× 重新开始（达芬奇那一手）；K 不是这里的事：它把速度交回 1 并停下。
 *  纯函数，界面与检查读的是同一份，不各自写一串 if。
 */
export const SHUTTLE_MAX = 8;

export function shuttleRate(playing: boolean, rate: number, direction: 1 | -1): number {
  if (!playing || Math.sign(rate) !== direction) return direction;
  return direction * Math.min(SHUTTLE_MAX, Math.abs(rate) * 2);
}
