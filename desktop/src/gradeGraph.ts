/** The grade chain as a picture: one card per node, branch lanes inside a parallel node, and the
 *  arithmetic for dragging a card to a new slot.
 *
 * This module owns no state and writes nothing — `clip.color.grade` stays the single source of
 * truth, and the editor that consumes these cards still commits one `clip.color` command per move.
 * It lives apart from the component so the ordering rules can be asserted directly.
 */

import { blendLabel, type BlendMode, type GradeBranch, type GradeNode, type GradeOperation, type GradeParallel } from "./engine";

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
  composite: "叠一层原图",
  layer: "叠一张外部画面",
};

/** 「叠一层原图」点下去得到什么：正片叠底 · 一半。这张默认值住在这里，视图不许自带
 *  混合方式的名字（`tests/desktop_branchblend_check.ts` 数着那些字面量）。 */
export const DEFAULT_COMPOSITE: { kind: "composite"; mode: BlendMode; mix: number; enabled: boolean } =
  { kind: "composite", mode: "multiply", mix: 0.5, enabled: true };

/** 「叠一张外部画面」点下去得到什么：方式与权重是引擎下发的词表，素材那一格由界面
 *  填工程里第一张验过的图——视图不许自带第二份名字，也不许自己拼 URL。 */
export const DEFAULT_LAYER: {
  kind: "layer"; asset_id: string; mode: BlendMode; mix: number;
  offset_x: number; offset_y: number; scale: number; enabled: boolean;
} = { kind: "layer", asset_id: "", mode: "multiply", mix: 0.5, offset_x: 0, offset_y: 0, scale: 1, enabled: true };

export type GraphLane = {
  label: string;
  detail: string;
  enabled: boolean;
  /** 1.124：一支自己是一台混频台时，它下面那些支也各有自己的名字与状态。 */
  lanes?: GraphLane[];
};

/**
 * 1.124：一支可以是一台混频台，于是「正在编辑哪一台」不再是一个下标，而是一条支路路径。
 * 路径的走法只在这里：界面拿它进出，写入拿它定位，别处不许再自己走一遍树。
 */
export type GradePath = number[];

export function mixerAt(node: GradeNode | null | undefined, path: GradePath): GradeParallel | null {
  let current = node && node.kind === "parallel" ? (node as GradeParallel) : null;
  for (const index of path) {
    if (!current) return null;
    const branch = current.branches[index];
    current = branch && branch.kind === "parallel" ? (branch as GradeParallel) : null;
  }
  return current;
}

/** 沿路径下去，把那一台混频台换成 `update` 的结果；路径走不通就原样交回，不猜用户想改谁。
 *  支路的返回类型仍是 `GradeBranch`，所以改写一棵树不会在半路把类型放宽成任意节点。 */
function walkBranch(
  branch: GradeBranch,
  path: GradePath,
  update: (mixer: GradeParallel) => GradeParallel,
): GradeBranch {
  if (branch.kind !== "parallel") return branch;
  if (!path.length) return update(branch);
  const [head, ...rest] = path;
  if (branch.branches[head] === undefined) return branch;
  return {
    ...branch,
    branches: branch.branches.map((entry, index) =>
      index === head ? walkBranch(entry, rest, update) : entry,
    ),
  };
}

export function mapMixer(
  node: GradeNode,
  path: GradePath,
  update: (mixer: GradeParallel) => GradeParallel,
): GradeNode {
  if (node.kind !== "parallel") return node;
  return path.length ? walkBranch(node, path, update) : update(node);
}

/** 一条支路路径走不通时能走多远算多远：换了一个节点、删了一支之后，路径自己缩短，
 *  而不是让检查器变成一片空白——人总得看得见还剩哪几层。 */
export function resolveMixerPath(node: GradeNode | null | undefined, wanted: GradePath): GradePath {
  const walked: GradePath = [];
  let current = node && node.kind === "parallel" ? (node as GradeParallel) : null;
  for (const index of wanted) {
    const branch = current?.branches[index];
    if (!current || !branch || branch.kind !== "parallel") break;
    current = branch as GradeParallel;
    walked.push(index);
  }
  return walked;
}

/**
 * 检查器这一格该摆**谁**的控件。挑进某一支之后（路径非空），尽头那台混频台才是被编辑的对象，
 * 它自己的支、权重与混合方式在另一块面板上；只有站在链子上挑中一个非混频台节点时，才给它摆
 * 这个节点自己的控件（曲线点、强度、混合方式、换一张表）。路径与链子共用一个 `current` 的名字
 * 时，这条判断就会把链上节点的控件整块吃掉——1.124 装机复核抓到过。
 */
export function chainFieldsFor(head: GradeNode | null | undefined, walked: GradePath): GradeNode | null {
  return !walked.length && head && head.kind !== "parallel" ? head : null;
}

/** 一棵树里的操作数与混频台层数：与契约 `branch_tree` 同一个数法，界面前置判断用。 */
export function branchTree(node: GradeNode | GradeBranch): { depth: number; operations: number } {
  if (node.kind !== "parallel") return { depth: 0, operations: 1 };
  let depth = 0;
  let operations = 1;
  for (const branch of node.branches) {
    const child = branchTree(branch);
    depth = Math.max(depth, child.depth);
    operations += child.operations;
  }
  return { depth: depth + 1, operations };
}

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
  // 1.234：立方表现在预览也画（画布上同一张表、同一档四面体插值），卡片不再说「仅导出生效」；
  // 「什么时候只在导出里生效」由下面那一行说明按这一条链的实际情况讲。
  if (node.kind === "lut3d")
    parts.push(
      `${node.title} · ${node.size}³ 网格 · 预览与导出同一张表` +
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
  const nested = node.kind === "parallel" ? (node as GradeParallel) : null;
  return {
    label: NODE_NAMES[node.kind],
    // 分支自己那个混合方式要说得出来：它改的是这一支怎么与进来的画面相合，看不出来就等于没交付。
    detail: [operationText(node), blend === "normal" ? "" : blendLabel(blend)].filter(Boolean).join(" · "),
    enabled: node.enabled !== false,
    // 套上来的那台混频台也要说话：它的每一支叫什么、偏不偏置，卡片上就得看得见，不然「一层壳」
    // 在界面上就只是一个图标。
    ...(nested ? { lanes: nested.branches.map((branch, index) => laneFor(branch, branchBlend(nested, index))) } : {}),
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
