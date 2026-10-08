/** The grade chain as a picture: one card per node, branch lanes inside a parallel node, and the
 *  arithmetic for dragging a card to a new slot.
 *
 * This module owns no state and writes nothing — `clip.color.grade` stays the single source of
 * truth, and the editor that consumes these cards still commits one `clip.color` command per move.
 * It lives apart from the component so the ordering rules can be asserted directly.
 */

import { blendLabel, type GradeNode, type GradeOperation, type GradeParallel } from "./engine";

export const NODE_NAMES: Record<GradeNode["kind"], string> = {
  curve: "色调曲线",
  white_balance: "白平衡",
  wheels: "RGB 增益",
  levels: "色阶",
  matrix: "通道混合",
  transfer: "色彩空间",
  lut: "LUT 查找表",
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

function mixText(node: GradeOperation | GradeParallel): string {
  return node.mix === undefined || node.mix === 1 ? "" : `强度 ${Math.round(node.mix * 100)}%`;
}

function operationText(node: GradeNode): string {
  const parts = [mixText(node)];
  // An imported table says which file it came from and how coarse its grid is, because that is the
  // whole of what the node knows: the card must not look like a control the user can still dial in.
  if (node.kind === "lut") parts.push(`${node.title} · ${node.size} 点`);
  // 色阶卡片报出自己把输入量程的哪一段拉到了满量程，人不用点开也知道这个节点在做什么。
  if (node.kind === "levels") {
    parts.push(`${CHANNEL_SHORT[node.channel] ?? node.channel} ${Math.round(node.black * 255)}→${Math.round(node.white * 255)}`);
  }
  if (node.kind === "matrix") parts.push("跨通道 3×3");
  if ("blend" in node && node.blend && node.blend !== "normal") parts.push(blendLabel(node.blend));
  return parts.filter(Boolean).join(" · ");
}

function laneFor(node: GradeNode): GraphLane {
  return {
    label: NODE_NAMES[node.kind],
    detail: operationText(node),
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
      mix: node.mix === undefined ? 1 : node.mix,
      blend: "blend" in node ? (node.blend ?? "normal") : "normal",
      enabled: node.enabled !== false,
      lanes: parallel ? parallel.branches.map(laneFor) : [],
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
