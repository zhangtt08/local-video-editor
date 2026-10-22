/** 框点在条上拖：那一枚的身份是「第几块的 keys 里第几枚」，交出去的仍是一整串 `clip.mask_stack`。
 *
 * 为什么不必新增命令（与 1.110 给片段针那条同一口径）：整串的写入早就存在，
 * `timeline.py` 的 `_apply_mask_stack` 收的是那一串块——拖动只是把其中一格的 `at_ticks` 换掉，
 * 一次抓取一条命令、一个 revision。引擎那边认得的还是 `MASK_KEY_RANGE` 与 `MASK_KEY_CLASH` 两条，
 * 界面这里先按同一条判断把「必定被拒的那一下」拦在发出去之前，而不是把人支去读 422。
 *
 * 刻度按片段本地数（框点存的就是片段本地 `at_ticks`，与主遮罩那五条曲线的含偏移时钟不是一回事），
 * 落点先过 `keyframeTick`：格线、播放头与这一串里没被拖动的那几枚都吸，最后再夹在 `[0, 时长]`。
 */
import { type ShapeMask } from "./engine";
import { TIMEBASE } from "./time";
import { keyframeTick } from "./keyframeSnap";

/** 命中盒自己的方子（与 styles.css 里 `.clip-boxkey` 那两行逐字对得上，门禁钉的是这一对）。
 *  高 5px 不是随手写的：1.261 第 0 步在真页面上量过那张卡片——框点带画在 y 2..6，
 *  名字那一行的**行盒**从 y 5 起、墨从 y 7 起，底下针道画出来的第一枚针在 y 19。
 *  往上过 7 就压住名字的墨，往下过 19 就抢针道；5 是那一条带里唯一不挡任何人的一格。
 *  想要更准的手，检查器那张框点表（1.239）还在——那一格里有整行可点。 */
export const BOX_KEY_HIT_PIXELS = { width: 12, height: 5 };

export type BoxKeyGesture = {
  id: string;
  duration_ticks: number;
  position_ticks: number;
  stack: ShapeMask[];
  /** 第几块再叠遮罩。 */
  block: number;
  /** 这一块自己那一串里的第几枚。 */
  index: number;
  /** 指针那一处换算成的片段本地刻度。 */
  pointer_ticks: number;
  /** 每秒多少像素——吸附半径按屏幕像素算，所以放大八倍容差就窄八倍。 */
  px: number;
  /** 这一轨一帧多长（刻度）。 */
  quantum: number;
  snap: boolean;
  playhead: number | null;
  /** 键盘微调不去吸播放头与邻居，只回自己的格子。 */
  attract: boolean;
};

export type BoxKeyPlan =
  | { kind: "noop" }
  | { kind: "blocked"; at: number; reason: string }
  | { kind: "move"; at: number; masks: ShapeMask[] };

export function planBoxKeyDrag(gesture: BoxKeyGesture): BoxKeyPlan {
  const block = gesture.stack[gesture.block];
  const keys = block?.keys ?? [];
  const held = keys[gesture.index];
  if (!block || !held) return { kind: "noop" };
  const span = gesture.duration_ticks;
  const others = keys.filter((_, index) => index !== gesture.index).map((key) => key.at_ticks);
  const at = keyframeTick(
    gesture.pointer_ticks,
    {
      clip: { position_ticks: gesture.position_ticks, duration_ticks: span },
      quantum: gesture.quantum,
      span,
      plot: (span / TIMEBASE) * gesture.px,
    },
    gesture.snap,
    { playhead: gesture.playhead, keys: others, attract: gesture.attract },
  );
  if (at === held.at_ticks) return { kind: "noop" };
  if (others.includes(at)) {
    return {
      kind: "blocked",
      at,
      reason: "这一帧已经有这一块的另一枚框点——一块盒子的两枚点不许停在同一格。"
        + "先往旁边挪开，或在检查器「再叠的遮罩」那张表里删掉那一枚。",
    };
  }
  const masks = gesture.stack.map((item, index) => (index === gesture.block
    ? { ...item, keys: (item.keys ?? []).map((key, i) => (i === gesture.index ? { ...key, at_ticks: at } : key)) }
    : item));
  return { kind: "move", at, masks };
}
