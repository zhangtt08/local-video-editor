/**
 * 时间线上拖一枚已有的针：把指针位置折成一条普通 `keyframe.move`。
 *
 * 几何全部借用 `keyframeSnap`（同一份绝对帧格子、同一份像素容差），这里只补时间线上才知道的两件事：
 * 一是「每刻度多少屏幕像素」由时间线的缩放决定，二是撞针的判断。撞针不在这里发明规则——reducer 的
 * `KEYFRAME_COLLISION` 才是权威，这里只是**提前**认出同一结局，好让用户在松手前就看到「那一格已经被
 * 占了」而不是收到一条红字。数值、插值、贝塞尔控制柄原样带走：这一步只改时间。
 */

import { type Clip, type Command, type Keyframe } from "./engine";
import { keyframeTick } from "./keyframeSnap";
import { TIMEBASE } from "./time";

export type KeyframeDrag = {
  clip: Clip;
  /** 片段上那枚被抓住的针（工程里存的刻度，含 `animation_offset_ticks`）。 */
  key: Keyframe;
  /** 指针此刻指到的片段本地刻度，未吸附。 */
  pointer_ticks: number;
  /** 播放头的片段本地刻度。 */
  playhead_ticks: number;
  /** 时间线的缩放：每刻度多少屏幕像素。 */
  px: number;
  snap: boolean;
  quantum: number;
  /** Alt 按住就是复制：原针留在原地，落点上一枚新的（AE / 达芬奇 的那只手）。 */
  duplicate?: boolean;
};

export type KeyframeDragPlan =
  | { kind: "move"; at_ticks: number; command: Command }
  | { kind: "add"; at_ticks: number; command: Command }
  | { kind: "noop" }
  | { kind: "blocked"; at_ticks: number; reason: string };

const seconds = (ticks: number) => (ticks / TIMEBASE).toFixed(3);

export function planKeyframeDrag(drag: KeyframeDrag): KeyframeDragPlan {
  const offset = drag.clip.animation_offset_ticks ?? 0;
  const from = drag.key.at_ticks - offset;
  const siblings = (drag.clip.keyframes ?? [])
    .filter((k) => k.property === drag.key.property && k.at_ticks !== drag.key.at_ticks)
    .map((k) => k.at_ticks - offset);
  const span = drag.clip.duration_ticks;
  const at = keyframeTick(
    drag.pointer_ticks,
    { clip: drag.clip, quantum: drag.quantum, span, plot: (span / TIMEBASE) * drag.px },
    drag.snap,
    { playhead: drag.playhead_ticks, keys: siblings, attract: true },
  );
  if (at === from && !drag.duplicate) return { kind: "noop" };
  if (siblings.includes(at)) {
    return {
      kind: "blocked",
      at_ticks: at,
      reason: `${drag.key.property} 在第 ${seconds(at)} 秒已经有一枚针，${drag.duplicate ? "复制就得先松到一个空格上" : "先松到空格上或在动画曲线里删掉那一枚"}。`,
    };
  }
  // 复制落在原针那一格等于给自己盖一层：什么都不加，但也不算「没动」。
  if (drag.duplicate && at === from) return { kind: "noop" };
  return drag.duplicate
    ? { kind: "add", at_ticks: at, command: { op: "keyframe.set", clip_id: drag.clip.id, keyframe: { ...drag.key, at_ticks: at } } }
    : { kind: "move", at_ticks: at, command: { op: "keyframe.move", clip_id: drag.clip.id, from_ticks: from, keyframe: { ...drag.key, at_ticks: at } } };
}
