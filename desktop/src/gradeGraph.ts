/** The grade chain as a picture: one card per node, branch lanes inside a parallel node, and the
 *  arithmetic for dragging a card to a new slot.
 *
 * This module owns no state and writes nothing — `clip.color.grade` stays the single source of
 * truth, and the editor that consumes these cards still commits one `clip.color` command per move.
 * It lives apart from the component so the ordering rules can be asserted directly.
 */

import { blendLabel, type BlendMode, type GradeNode, type GradeOperation, type GradeParallel } from "./engine";

export const NODE_NAMES: Record<GradeNode["kind"], string> = {
  curve: "色调曲线",
  white_balance: "白平衡",
  wheels: "RGB 增益",
  levels: "色阶",
  matrix: "通道混合",
  transfer: "色彩空间",
  lut: "LUT 查找表",
  lut3d: "3D LUT",
  parallel: "并联",
};

export type GraphLane = {
  label: string;
  detail: string;
  enabled: boolean;
};

export type GraphCard = {
  index: number;
  kind: GradeNode["kind"];
  label: string;
  detail: string;
  mix: number;
  blend: string;
  enabled: boolean;
  lanes: GraphLane[];
};

const CHANNEL_SHORT: Record<string, string> = { rgb: "全部", red: "红", green: "绿", blue: "蓝" };

/**
 * 1.120：并联节点混频台的形状判断，只有这一处。
 *
 * 契约要权重「给就给全」，因为它是按位置覆盖每一支的：一份长度对不上的表，两端算不出同一个结果。
 * 所以改一支、加一支、删一支都由这里补齐或撤掉，界面不许在别处再数一遍支数。全部回到 1 时交
 * `undefined`：撤掉这份表与交一串 1 是同一个均分，而前者正是 1.120 之前那份载荷。
 */

/**
 * 1.122：每一支还可以自带一个混合方式——先按它把自己与进来的画面相合，再按权重参与平均。
 * 位置表的规矩与权重同一条：给就给全，全是 normal 就把整份撤掉（撤掉就是 1.120 那份载荷）。
 */
export function branchBlend(node: GradeParallel, index: number): BlendMode {
  return alignedBlendModes(node)?.[index] ?? "normal";
}

function alignedBlendModes(node: GradeParallel): BlendMode[] | null {
  return node.blends && node.blends.length === node.branches.length ? node.blends : null;
}

export function blendsAfterPick(node: GradeParallel, index: number, mode: BlendMode): BlendMode[] | undefined {
  const next = node.branches.map((_, position) => branchBlend(node, position));
  next[index] = mode;
  return settle(next, "normal");
}

export function blendsAfterAdd(node: GradeParallel): BlendMode[] | undefined {
  const current = alignedBlendModes(node);
  return current ? settle([...current, "normal"], "normal") : undefined;
}

export function blendsAfterRemove(node: GradeParallel, slot: number): BlendMode[] | undefined {
  const current = alignedBlendModes(node);
  return current ? settle(current.filter((_, position) => position !== slot), "normal") : undefined;
}

export function branchWeight(node: GradeParallel, index: number): number {
  return alignedWeights(node)?.[index] ?? 1;
}

function alignedWeights(node: GradeParallel): number[] | null {
  return node.weights && node.weights.length === node.branches.length ? node.weights : null;
}

function settle<T>(kept: T[], fallback: T): T[] | undefined {
  return kept.every((entry) => entry === fallback) ? undefined : kept;
}

export function weightsAfterWeight(node: GradeParallel, index: number, value: number): number[] | undefined {
  const next = node.branches.map((_, position) => branchWeight(node, position));
  next[index] = value;
  return settle(next, 1);
}

export function weightsAfterAdd(node: GradeParallel): number[] | undefined {
  const current = alignedWeights(node);
  return current ? settle([...current, 1], 1) : undefined;
}

export function weightsAfterRemove(node: GradeParallel, slot: number): number[] | undefined {
  const current = alignedWeights(node);
  return current ? settle(current.filter((_, position) => position !== slot), 1) : undefined;
}

function mixText(node: GradeOperation | GradeParallel): string {
  // 3D 表没有强度可标（契约里就没有那个字段），所以先问它在不在。
  return "mix" in node && node.mix !== undefined && node.mix !== 1 ? `强度 ${Math.round(node.mix * 100)}%` : "";
}

function operationText(node: GradeNode): string {
  const parts = [mixText(node)];
  // An imported table says which file it came from and how coarse its grid is, because that is the
  // whole of what the node knows: the card must not look like a control the user can still dial in.
  if (node.kind === "parallel" && node.weights && node.weights.length === node.branches.length) {
    // 卡片要说这张表真的存在：均分时没有表，有表就一定不为 1 的某一支在偏置。
    parts.push(`加权 ${node.weights.map((weight) => `×${weight}`).join("/")}`);
  }
  if (node.kind === "lut") parts.push(`${node.title} · ${node.size} 点`);
  // 3D 表在卡片上就把「预览不生效」写出来：这是一张只有导出会走它的表，不是近似。
  if (node.kind === "lut3d")
    parts.push(
      `${node.title} · ${node.size}³ 网格 · 仅导出生效` +
        (node.resampled_from ? ` · 由 ${node.resampled_from}³ 重采样` : ''),
    );
  // 色阶卡片报出自己把输入量程的哪一段拉到了满量程，人不用点开也知道这个节点在做什么。
  if (node.kind === "levels") {
    parts.push(`${CHANNEL_SHORT[node.channel] ?? node.channel} ${Math.round(node.black * 255)}→${Math.round(node.white * 255)}`);
  }
  if (node.kind === "matrix") parts.push("跨通道 3×3");
  if ("blend" in node && node.blend && node.blend !== "normal") parts.push(blendLabel(node.blend));
  return parts.filter(Boolean).join(" · ");
}

function laneFor(node: GradeNode, blend: BlendMode = "normal"): GraphLane {
  return {
    label: NODE_NAMES[node.kind],
    // 分支自己那个混合方式要说得出来：它改的是这一支怎么与进来的画面相合，看不出来就等于没交付。
    detail: [operationText(node), blend === "normal" ? "" : blendLabel(blend)].filter(Boolean).join(" · "),
    enabled: node.enabled !== false,
  };
}

/** Cards in chain order, each carrying what the picture needs to say out loud. */
export function cardsFor(nodes: GradeNode[]): GraphCard[] {
  return nodes.map((node, index) => {
    const parallel = node.kind === "parallel" ? (node as GradeParallel) : null;
    return {
      index,
      kind: node.kind,
      label: `${index + 1}. ${NODE_NAMES[node.kind]}`,
      detail: parallel
        ? [`${parallel.branches.length} 支`, operationText(node)].filter(Boolean).join(" · ")
        : operationText(node),
      mix: "mix" in node ? (node.mix ?? 1) : 1,
      blend: "blend" in node ? (node.blend ?? "normal") : "normal",
      enabled: node.enabled !== false,
      lanes: parallel ? parallel.branches.map((branch, index) => laneFor(branch, branchBlend(parallel, index))) : [],
    };
  });
}

/** Where a card lands when it is dropped on slot `over`. Clamped, because a drag can end past the end. */
export function dropIndex(count: number, over: number): number {
  if (count <= 0) return 0;
  return Math.min(count - 1, Math.max(0, over));
}

/** Remove-and-insert. Same length, same elements, one position changed. */
export function moveWithin<T>(list: T[], from: number, to: number): T[] {
  if (from < 0 || from >= list.length) return list.slice();
  const target = dropIndex(list.length, to);
  if (target === from) return list.slice();
  const next = list.slice();
  next.splice(target, 0, next.splice(from, 1)[0]);
  return next;
}
