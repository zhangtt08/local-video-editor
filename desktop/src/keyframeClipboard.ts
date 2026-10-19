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
 * - 1.212 起那一层的针也能搬，但**一份复制的完整身份是（第几层, 哪个数）**：层的 `scale` 与片段
 *   自己的 `scale` 同名，只认名字就会把层的针粘进片段自己的曲线上（曲线列表当初就是为此把键拼成
 *   `layer0:scale`）。粘出去**值照搬、不重折**——`LAYER_KEY_LIMITS` 那张带子只按属性分（引擎下发的
 *   `grade_limits.layer_key_bands` 就是它），源上被引擎收下过的数在目标上必然还在带内，重折反而
 *   会多出第二个值域、与检查器那个框就不是同一件事了。落库仍只有 `layerKeyCommand` 那一条 `clip.grade`，
 *   额度（`limits.layer_key_limit`，按整层数）越过去的逐枚跳过并报数。
 */

import { type Clip, type Command, type Keyframe, type LayerKeyframe, type LayerProperty, type Property } from "./engine";
import { layerKeyCommand, layerKeysRead, layerNeedleProperty, type LayerNeedleField } from "./effects";

export type CopiedKeys = { projectId: string; property: Property; layer?: number; base: number; keys: Keyframe[] };

export type PasteTarget = {
  id: string;
  duration_ticks: number;
  animation_offset_ticks?: number;
  keyframes?: Keyframe[];
};

/** 两份粘贴交回同一份形状，所以回执、跳过数与「一条批次一次事务」那条链只有一处判断。 */
export type Paste = { commands: Command[]; dropped: number; pasted: number; reason: string };

/** 一份复制的身份：层的针要连着层序一起认，片段自己的那六个数不带层序。 */
export const copyIdentity = (copy: Pick<CopiedKeys, "property" | "layer">) =>
  copy.layer === undefined ? copy.property : layerNeedleProperty(copy.layer, copy.property as LayerProperty);

/** 「这份复制现在能不能粘到这一行」只有这一处主人：身份要整个对上，那一层还要引擎报过针数额度
 *  （没报就不粘——额度是那一层整层的，缺了这个数就不知道第几枚该跳过，宁可当场少给一只手）。 */
export function copyMatches(copy: CopiedKeys | null, field: { property: string }, limit: number | undefined): boolean {
  if (!copy || copyIdentity(copy) !== field.property) return false;
  return copy.layer === undefined || typeof limit === "number";
}

/** 指针按下 Ctrl+C：没有选中就什么都不是，属性不一致也当没选中（避免搬出一半节奏）。
 *  `layer` 给了就是那一层的针，身份连着层序一起存（`copyIdentity` 读的就是它）。 */
export function copyKeys(projectId: string | null | undefined, keys: Keyframe[], layer?: number): CopiedKeys | null {
  if (!projectId || !keys.length) return null;
  const property = keys[0].property;
  if (keys.some((k) => k.property !== property)) return null;
  const base = Math.min(...keys.map((k) => k.at_ticks));
  return { projectId, property, ...(layer === undefined ? {} : { layer }), base, keys: keys.map((k) => ({ ...k })) };
}

export function pasteKeys(target: PasteTarget, copy: CopiedKeys | null, at: number, projectId: string | null | undefined): Paste {
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

/** 粘干净之后那一句要说的差别（不是回执，是这一只手新引入的那一处「看着一样、其实不同」）：
 *  层的针按层序搬到另一段上，那个数照搬不重折，两边的第 N 层却未必是同一个画面。 */
export const layerPasteDetail = (layer: number) =>
  `第 ${layer + 1} 层那个数照搬过去、没有重折（引擎那张带子只按属性分）：两边的第 ${layer + 1} 层不是同一个画面，同一个数落在各自画上未必是同一个位置。`;

/**
 * 1.212：那一层的针粘到另一段上。与 `pasteKeys` 同一份算术（第一枚是基准、间距照搬），三处不同：
 * 一是撞针按**那一层那一道曲线**判（引擎的 `LAYER_KEY_CLASH` 认的是「同一格同一条属性两枚」）；
 * 二是额度按**整层**数（`LAYER_KEY_LIMIT` 数的是这一层所有属性的针，不是这一道曲线），所以越过去的
 * 枚数照样逐枚跳过并报数，不整批失败、也不悄悄挪位；三是落库仍只有 `layerKeyCommand` 那一条
 * `clip.grade`——交回的是「这一道原有全部针 ＋ 粘进来的那几枚」，同层别的数一字不动。
 * 一枚都没粘上就**一条命令都不发**：写一份没改的链会在撤销台上留一步空操作（1.211 量过那一笔）。
 */
export function pasteLayerKeys(target: Clip, copy: CopiedKeys | null, at: number, projectId: string | null | undefined, limit: number): Paste {
  if (!copy) return { commands: [], dropped: 0, pasted: 0, reason: "还没有复制过层的针：先选中那一层的针，按 Ctrl+C" };
  if (!projectId || copy.projectId !== projectId) {
    return { commands: [], dropped: 0, pasted: 0, reason: "换了工程，之前复制的那段已失效" };
  }
  const field: LayerNeedleField = { layer: copy.layer ?? 0, key: copy.property as LayerProperty };
  const whole = layerKeysRead(target, field);
  const sameCurve = whole.filter((key) => key.property === field.key);
  const taken = new Set(sameCurve.map((key) => key.at_ticks));
  const room = Math.max(0, limit - whole.length);
  const added: Keyframe[] = [];
  let dropped = 0;
  for (const key of copy.keys) {
    const tick = at + (key.at_ticks - copy.base);
    if (tick < 0 || tick > target.duration_ticks || taken.has(tick) || added.length >= room) {
      dropped++;
      continue;
    }
    taken.add(tick);
    added.push({ ...key, at_ticks: tick });
  }
  const reason = !added.length && dropped
    ? `${dropped} 枚都落在片段之外、已有针那一格，或这一层 ${limit} 枚的额度之外，没有粘贴——上方「动画片段」换个针少一点的，或先删掉几枚`
    : dropped ? `粘贴 ${added.length} 枚，跳过 ${dropped} 枚（片段之外、已有针那一格，或那一层 ${limit} 枚的额度）` : "";
  const commands = added.length ? [layerKeyCommand(target, field, [...sameCurve, ...added] as unknown as LayerKeyframe[])] : [];
  return { commands, dropped, pasted: added.length, reason };
}

/** 粘贴走哪条路只由**那份复制自己**说：带层序的就是那一层的针（`clip.grade`），否则是片段自己的
 *  `keyframe.set`。视图不许再数一遍「这是哪一层」。 */
export function pasteInto(target: Clip, copy: CopiedKeys | null, at: number, projectId: string | null | undefined, limit: number | undefined): Paste {
  return copy?.layer === undefined
    ? pasteKeys(target, copy, at, projectId)
    : pasteLayerKeys(target, copy, at, projectId, limit ?? 0);
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
