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
  transfer: "色彩空间",
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

function mixText(node: GradeOperation | GradeParallel): string {
  return node.mix === undefined || node.mix === 1 ? "" : `强度 ${Math.round(node.mix * 100)}%`;
}

function operationText(node: GradeNode): string {
  const parts = [mixText(node)];
  if (node.blend && node.blend !== "normal") parts.push(blendLabel(node.blend));
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
      blend: node.blend ?? "normal",
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
