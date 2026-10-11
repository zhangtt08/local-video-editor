/**
 * 复制／粘贴动画关键帧：AE 与剪映都这么做——把一条属性上的一段节奏搬到同一片段的别处，或搬到
 * 另一条片段上。这里只写「算出该发哪些命令」这一步，落库仍是普通 `keyframe.set`，一条批次一次事务
 * 一个 revision，引擎那边没有第二条规则。
 *
 * 三条刻意的边界：
 * - 复制的是**一条属性**（`keyframe.set` 本来就一针一属性；跨属性搬节奏需要映射，那条路不通就不猜）。
 * - 粘出去越界或撞上已有针的那几枚，逐枚**报数跳过**，而不是整批失败，也不悄悄挪到别处——与 1.108
 *   「套不满的轨是一次有名字的局部应用」同一口径。
 * - 复制不跨工程：换了工程之前那份就失效（和 store 里 pendingEdits 记 projectId 同一个理由）。
 */

import { type Command, type Keyframe, type Property } from "./engine";

export type CopiedKeys = { projectId: string; property: Property; base: number; keys: Keyframe[] };

export type PasteTarget = {
  id: string;
  duration_ticks: number;
  animation_offset_ticks?: number;
  keyframes?: Keyframe[];
};

/** 指针按下 Ctrl+C：没有选中就什么都不是，属性不一致也当没选中（避免搬出一半节奏）。 */
export function copyKeys(projectId: string | null | undefined, keys: Keyframe[]): CopiedKeys | null {
  if (!projectId || !keys.length) return null;
  const property = keys[0].property;
  if (keys.some((k) => k.property !== property)) return null;
  const base = Math.min(...keys.map((k) => k.at_ticks));
  return { projectId, property, base, keys: keys.map((k) => ({ ...k })) };
}

export function pasteKeys(target: PasteTarget, copy: CopiedKeys | null, at: number, projectId: string | null | undefined):
  { commands: Command[]; dropped: number; pasted: number; reason: string } {
  if (!copy) return { commands: [], dropped: 0, pasted: 0, reason: "还没有复制过关键帧" };
  if (!projectId || copy.projectId !== projectId) {
    return { commands: [], dropped: 0, pasted: 0, reason: "换了工程，之前复制的那段已失效" };
  }
  const offset = target.animation_offset_ticks ?? 0;
  const taken = new Set(
    (target.keyframes ?? []).filter((k) => k.property === copy.property).map((k) => k.at_ticks - offset),
  );
  const commands: Command[] = [];
  let dropped = 0;
  for (const key of copy.keys) {
    const tick = at + (key.at_ticks - copy.base);
    if (tick < 0 || tick > target.duration_ticks || taken.has(tick)) {
      dropped++;
      continue;
    }
    taken.add(tick);
    commands.push({ op: "keyframe.set", clip_id: target.id, keyframe: { ...key, at_ticks: tick } });
  }
  const reason = !commands.length && dropped
    ? `这一段 ${dropped} 枚都落在片段之外或已有针的那一格上，没有粘贴`
    : dropped ? `粘贴 ${commands.length} 枚，跳过 ${dropped} 枚（越界或那一格已有针）` : "";
  return { commands, dropped, pasted: commands.length, reason };
}

/**
 * 这份复制跟着应用走而不是跟着组件走：离开动画曲线再回来，那段节奏还在。1.125 起它还跟着这台
 * 机器走——重启后回到同一个工程，那段节奏照样能粘（`pasteKeys` 仍然按工程判，换了工程就按失效处理）。
 * 它不进工程状态（写了就涨 revision、清撤销栈）。
 */
import { KEYS_KEY, isCopiedKeys, readBrowser, writeBrowser } from "./clipboardStore";

let last: CopiedKeys | null = readBrowser(KEYS_KEY, isCopiedKeys);
export function rememberCopy(copy: CopiedKeys | null): void {
  last = copy;
  writeBrowser(KEYS_KEY, copy);
}
export function copiedKeys(): CopiedKeys | null {
  return last;
}
