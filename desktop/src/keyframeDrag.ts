/**
 * 时间线上拖针：把指针位置折成一条普通 `keyframe.move`，拖一整组则是一条普通 `keyframes.move`。
 *
 * 几何全部借用 `keyframeSnap`（同一份绝对帧格子、同一份像素容差），这里只补时间线上才知道的两件事：
 * 一是「每刻度多少屏幕像素」由时间线的缩放决定，二是撞针的判断。撞针不在这里发明规则——reducer 的
 * `KEYFRAME_COLLISION` 才是权威，这里只是**提前**认出同一结局，好让用户在松手前就看到「那一格已经被
 * 占了」而不是收到一条红字。数值、插值、贝塞尔控制柄原样带走：这一步只改时间。
 *
 * 整组（`group`）走的是同一条算术，只多两处：落点先被「整组不许越出片段两头」夹一次（与曲线编辑器
 * 1.117 那份 `clampGroupTimeShift` 同一句），撞针则**逐条属性**判——组里的针跨属性时，一条曲线上的
 * 邻居只管自己那条。命令的条数也是这里定的：一枚用 `keyframe.move`，多枚用 `keyframes.move`，一次
 * 抓取永远只交一条命令、只涨一个 revision；复制那组则交若干 `keyframe.set`（`keyframes.set` 不存在，
 * 而 `keyframe.set` 本来就是「那一格有就盖住、没有就加」，与检查器粘贴那批同一条路）。
 */

import { type Clip, type Command, type Keyframe, type Property } from "./engine";
import { clampGroupTimeShift } from "./curveDrag";
import { FIELD_LABEL, LAYER_KEY_LABEL, layerKeyCommand, layerKeysRead, type LayerNeedleField } from "./effects";
import { needleId } from "./keyframeLanes";
import { keyframeTick } from "./keyframeSnap";
import { TIMEBASE } from "./time";

export type KeyframeDrag = {
  clip: Clip;
  /** 片段上被指针抓住的那一枚针（工程里存的刻度，含 `animation_offset_ticks`）。 */
  key: Keyframe;
  /** 跟着一起走的整组，必须包含 `key`；不给就是只拖抓住的这一枚（1.110 的旧行为，一字未变）。 */
  group?: Keyframe[];
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

/** 组里这一枚从哪一格走到哪一格，两端都是**片段本地**刻度；界面据此画影子，不许自己再算一遍。 */
export type KeyframeShift = { property: Property; from: number; at: number };

export type KeyframeDragPlan =
  | { kind: "move"; at_ticks: number; shifts: KeyframeShift[]; commands: Command[] }
  | { kind: "add"; at_ticks: number; shifts: KeyframeShift[]; commands: Command[] }
  | { kind: "noop" }
  | { kind: "blocked"; at_ticks: number; reason: string };

/**
 * Alt + 点一下（没有拖动）就是删掉这一枚，或删掉挑中的这一组：Premiere 的那只手，加上 1.119 那组针。
 * 交出去的仍是普通 `keyframe.remove` / `keyframes.remove`，刻度按**片段本地**交（与拖动同一口径，reducer
 * 自己加回偏移）。之所以在时间线上给这一条，是因为撞针那句拒绝原本只能把人支到动画曲线里去——
 * 「按住 Alt 点掉那一枚」就在眼前，出路得落在原地。重复的那一格先去掉：reducer 对重复的选区回
 * `INVALID_SELECTION`，而指针一次只会点在一枚上。
 */
export function planNeedleRemoval(clip: Clip, keys: Keyframe[]): Command {
  const unique = new Map<string, { property: Property; at_ticks: number }>();
  for (const key of keys) {
    unique.set(needleId(key), { property: key.property, at_ticks: key.at_ticks - (clip.animation_offset_ticks ?? 0) });
  }
  const positions = [...unique.values()];
  if (positions.length === 1) {
    return { op: "keyframe.remove", clip_id: clip.id, property: positions[0].property, at_ticks: positions[0].at_ticks };
  }
  return { op: "keyframes.remove", clip_id: clip.id, keyframes: positions };
}

const seconds = (ticks: number) => (ticks / TIMEBASE).toFixed(3);

/**
 * 1.208：第二路画面那一层的针也能在片段条上拖。几何用的是**同一批原语**（同一份吸附、同一份
 * 「不许越出片段两头」），只有一处不同：写回去的还是那一条 `clip.grade` 整链替换——引擎没有、
 * 也不需要「挪一枚层针」这条命令，所以交回的是**这一层的全部针**，别的属性一字不动，
 * 一次抓取一条命令、只涨一个 revision。撞针仍只是提前认出引擎 `LAYER_KEY_CLASH` 那个结局。
 */
export type LayerNeedleDrag = {
  clip: Clip;
  field: LayerNeedleField;
  /** 抓住的那一枚在哪一格（片段本地刻度）。 */
  from: number;
  /** 按住 Alt 拖着这一枚是**复制**一枚（原针留在原地），普通拖动是把它挪走。与上面 ◆ 那一只手同一口径。 */
  duplicate: boolean;
  pointer_ticks: number;
  playhead_ticks: number;
  px: number;
  snap: boolean;
  quantum: number;
};

export function planLayerNeedleDrag(drag: LayerNeedleDrag): KeyframeDragPlan {
  const span = drag.clip.duration_ticks;
  const keys = layerKeysRead(drag.clip, drag.field);
  const sameCurve = keys.filter((key) => key.property === drag.field.key);
  // 复制时原针留在原地，所以那一格也算被占着；普通拖动则这一枚先腾空（与 `planKeyframeDrag` 同一句判断）。
  const obstacles = sameCurve
    .filter((key) => drag.duplicate || key.at_ticks !== drag.from)
    .map((key) => key.at_ticks);
  const at = keyframeTick(
    drag.pointer_ticks,
    { clip: drag.clip, quantum: drag.quantum, span, plot: (span / TIMEBASE) * drag.px },
    drag.snap,
    { playhead: drag.playhead_ticks, keys: obstacles, attract: true },
  );
  const shift = clampGroupTimeShift([drag.from], span, at - drag.from);
  if (drag.duplicate ? at === drag.from : shift === 0) return { kind: "noop" };
  const to = drag.duplicate ? at : drag.from + shift;
  if (obstacles.includes(to)) {
    const label = LAYER_KEY_LABEL[drag.field.key] ?? drag.field.key;
    return {
      kind: "blocked",
      at_ticks: to,
      reason: `第 ${drag.field.layer + 1} 层的${label}在第 ${seconds(to)} 秒已经有一枚针，${drag.duplicate ? "复制就得先松到一个空格上" : "先松到空格上，或按住 Alt 点掉那一枚"}。`,
    };
  }
  // 交回的是**那一道曲线的全部针**（同层别的数由 `layerKeyCommand` 原样留着），与曲线编辑器同一个契约。
  // 复制那一路是把抓住那一枚的值与插法原样多写一份到新格子——不是第二次插值。
  const next = drag.duplicate
    ? [...sameCurve, ...sameCurve.filter((key) => key.at_ticks === drag.from).map((key) => ({ ...key, at_ticks: to }))]
    : sameCurve.map((key) => (key.at_ticks === drag.from ? { ...key, at_ticks: to } : key));
  return {
    kind: drag.duplicate ? "add" : "move",
    at_ticks: to,
    shifts: [{ property: drag.field.key as Property, from: drag.from, at: to }],
    commands: [layerKeyCommand(drag.clip, drag.field, next)],
  };
}

/**
 * 1.211：按住 Alt 点一下删掉那一枚层针。写的还是那一条 `clip.grade`——引擎没有也不需要「删一枚层针」
 *  这条命令，所以交回的是「这一道去掉那一枚之后的全部针」，同层别的数一字不动（与拖动同一处主人）。
 *  那一枚已经不在了就回 `null`：撤销台上不该留一步什么都不改的历史。
 */
export function planLayerNeedleRemoval(clip: Clip, field: LayerNeedleField, at: number): Command | null {
  const sameCurve = layerKeysRead(clip, field).filter((key) => key.property === field.key);
  if (!sameCurve.some((key) => key.at_ticks === at)) return null;
  return layerKeyCommand(clip, field, sameCurve.filter((key) => key.at_ticks !== at));
}

const local = (key: Keyframe, offset: number) => key.at_ticks - offset;

export function planKeyframeDrag(drag: KeyframeDrag): KeyframeDragPlan {
  const offset = drag.clip.animation_offset_ticks ?? 0;
  const group = drag.group?.length ? drag.group : [drag.key];
  const froms = group.map((key) => local(key, offset));
  const anchorFrom = local(drag.key, offset);
  const members = new Set(group.map(needleId));
  // 复制时原针留在原地，所以组里那些枚也算占了格；普通拖动则整组先腾空，组内的格子不算邻居（与 reducer
  // 的 `occupied - source_ids` 同一句判断）。
  const obstacles = (drag.clip.keyframes ?? []).filter((key) => drag.duplicate || !members.has(needleId(key)));
  const span = drag.clip.duration_ticks;
  const at = keyframeTick(
    drag.pointer_ticks,
    { clip: drag.clip, quantum: drag.quantum, span, plot: (span / TIMEBASE) * drag.px },
    drag.snap,
    { playhead: drag.playhead_ticks, keys: obstacles.filter((key) => key.property === drag.key.property).map((key) => local(key, offset)), attract: true },
  );
  // 抓的那一枚想去 `at`，整组却未必走得到：先看这一组自己的两头还剩多少余量。
  const shift = clampGroupTimeShift(froms, span, at - anchorFrom);
  if (shift === 0) return { kind: "noop" };
  const shifts = group.map((key, index) => ({ property: key.property, from: froms[index], at: froms[index] + shift }));
  const taken = obstacles.map((key) => ({ property: key.property, at: local(key, offset) }));
  const clash = shifts.find((move) => taken.some((slot) => slot.property === move.property && slot.at === move.at));
  if (clash) {
    const label = FIELD_LABEL[clash.property] ?? clash.property;
    const one = `${label} 在第 ${seconds(clash.at)} 秒已经有一枚针，${drag.duplicate ? "复制就得先松到一个空格上" : "先松到空格上，或按住 Alt 点掉那一枚"}。`;
    return { kind: "blocked", at_ticks: at, reason: group.length > 1 ? `${group.length} 枚一起走，可是${one}` : one };
  }
  if (drag.duplicate) {
    return {
      kind: "add",
      at_ticks: anchorFrom + shift,
      shifts,
      commands: shifts.map((move, index) => ({ op: "keyframe.set", clip_id: drag.clip.id, keyframe: { ...group[index], at_ticks: move.at } })),
    };
  }
  const moves = shifts.map((move, index) => ({ from_ticks: move.from, keyframe: { ...group[index], at_ticks: move.at } }));
  return {
    kind: "move",
    at_ticks: anchorFrom + shift,
    shifts,
    commands: [moves.length === 1
      ? { op: "keyframe.move", clip_id: drag.clip.id, from_ticks: moves[0].from_ticks, keyframe: moves[0].keyframe }
      : { op: "keyframes.move", clip_id: drag.clip.id, moves }],
  };
}
