import type { GamutMatrixPreset, GradeNode } from "./engine";

/** 1.158：把引擎那张基色表接进界面。九个系数只从 `capabilities.gamut_matrices` 来。
 *
 * `gamut.primaries_matrix` 是这九个数的唯一所有者，`tests/gamut_check.py` 已经用色度坐标那条独立路
 * 量过它，也量过「线性进—矩阵—线性出」这一对真导出之后的画面。这个文件里既不出现任何一个系数，也
 * 不出现任何一个档位名：抄一份表就是给同一句话两个答案，而最后落在成片里的是引擎那一个（这条纪律
 * 由 `tests/gamutfold_check.py` 逐字钉住）。
 *
 * 折进去的那一格只承认色彩管理那两个**盖过章**的转换节点。矩阵是乘在存储值上的，只有落在那一对
 * 中间才是在线性光里换基色——契约里 `GradeMatrix` 的说明与界面「套上色彩管理」那句是同一条。所以
 * 没套色彩管理的片段上这颗按钮不亮，并把能走的出路说清楚（不亮着骗人，也不偷偷把人家的链子改了）。
 */

/** 表里能用的行：凑不满九个有限的数就不是一张矩阵，宁可不显示那一档。写成半枚节点会整笔被引擎
 *  拒掉，而下拉菜单里看不见「这一档为什么点不动」——那是把人困在猜里。 */
export function usableRows(published: GamutMatrixPreset[] | undefined): GamutMatrixPreset[] {
  return (published ?? []).filter(
    (row) =>
      Boolean(row) &&
      typeof row.id === "string" &&
      Array.isArray(row.coefficients) &&
      row.coefficients.length === 9 &&
      row.coefficients.every((value) => Number.isFinite(value)),
  );
}

const sameCoefficients = (a: number[], b: number[]): boolean =>
  a.length === b.length && a.every((value, index) => value === b[index]);

const tagged = (node: GradeNode): boolean => node.kind === "transfer" && node.purpose === "color_manage";

/** 色彩管理那一对的下标。方向不对（不是「进线性」与「出线性」）也算不齐——`colorManage.ts` 认人
 *  只认盖章的，这里也一样，不猜哪两个转换节点「看起来像」。 */
function wrapMarks(nodes: GradeNode[]): [number, number] | null {
  const marks = nodes.map((node, index) => (tagged(node) ? index : -1)).filter((index) => index >= 0);
  if (marks.length !== 2) return null;
  const [head, tail] = marks as [number, number];
  const first = nodes[head];
  const last = nodes[tail];
  if (first.kind !== "transfer" || first.output_space !== "linear") return null;
  if (last.kind !== "transfer" || last.input_space !== "linear") return null;
  return [head, tail];
}

/** 那一格里已经有什么：空的就插在「进线性」之后；已经有一枚「表里的某一行」就换掉它（再折一次是
 *  换档，不是叠第二枚）；有别的（手工填的九个数、或者一枚以上）就说不出要换哪一枚，交回 null。 */
export function foldTarget(
  nodes: GradeNode[],
  rows: GamutMatrixPreset[],
): { index: number; replacing: string | null } | null {
  const marks = wrapMarks(nodes);
  if (!marks) return null;
  const [head, tail] = marks;
  const inside = nodes
    .map((node, index) => (node.kind === "matrix" && index > head && index < tail ? index : -1))
    .filter((index) => index >= 0);
  if (inside.length === 0) return { index: head + 1, replacing: null };
  if (inside.length > 1) return null;
  const node = nodes[inside[0]];
  if (node.kind !== "matrix") return null;
  const matched = rows.find((row) => sameCoefficients(row.coefficients, node.coefficients));
  return { index: inside[0], replacing: matched ? matched.id : "hand" };
}

/** 已经按表折过哪一档（状态那一句话用）；那一格里是手工填的数、或者压根没有，都回 null。 */
export function foldedRow(nodes: GradeNode[], rows: GamutMatrixPreset[]): GamutMatrixPreset | null {
  const target = foldTarget(nodes, rows);
  if (!target || !target.replacing || target.replacing === "hand") return null;
  return rows.find((row) => row.id === target.replacing) ?? null;
}

/** 折进去：交回整条新链。格子不通就交回 null，让界面去说那句出路——这里从不硬塞。
 *  认「那一格里是不是表里的某一行」要拿**整张表**去比：只拿这一档去比，会把「从乙档换成甲档」
 *  误判成「那是人手工填的数」而拒掉。 */
export function foldIn(
  nodes: GradeNode[],
  row: GamutMatrixPreset,
  rows: GamutMatrixPreset[],
): GradeNode[] | null {
  if (usableRows([row]).length !== 1) return null;
  const target = foldTarget(nodes, usableRows(rows));
  if (!target || target.replacing === "hand") return null;
  const node = { kind: "matrix", coefficients: [...row.coefficients], enabled: true } as GradeNode;
  return target.replacing
    ? nodes.map((entry, index) => (index === target.index ? node : entry))
    : [...nodes.slice(0, target.index), node, ...nodes.slice(target.index)];
}

/** 这颗按钮该不该亮；不亮的时候说什么。每一句都得指一条真走得通的出路。 */
export function foldBlocker(
  nodes: GradeNode[],
  rows: GamutMatrixPreset[],
  nodeLimit: number,
): string | null {
  if (rows.length === 0) {
    return (
      "这一版引擎没有把基色表交下来（capabilities 里没有 gamut_matrices），界面不自己抄一份系数。" +
      "要现在就折：按「+通道混合」添一枚节点，把 ITU 那两档原色算出的九个数填进那张九宫格。"
    );
  }
  if (wrapMarks(nodes) === null) {
    const stamped = nodes.filter((node) => tagged(node)).length;
    if (stamped === 0) {
      return (
        "这一段还没套色彩管理。矩阵是乘在存储值上的，只有落在「线性进—线性出」那一对中间才是在换基色，" +
        "单独挂在链子上只会把画面调偏。先在上面按「套上色彩管理」，再回来折这一档。"
      );
    }
    return (
      `这一段只有 ${stamped} 个盖过章的转换节点，不成一对，说不清哪一格是线性光。` +
      "先按「取下色彩管理」把还盖着章的那个删掉，再按「套上色彩管理」配齐一对，然后回来折。"
    );
  }
  const target = foldTarget(nodes, rows);
  if (target === null) {
    return (
      `这一对中间已经有 ${countMatricesInside(nodes)} 枚通道混合，界面不知道要换哪一枚，所以哪一枚都不动。` +
      "先在链子那张卡片上删掉不要的那枚（留下想要换掉的那枚），再折。"
    );
  }
  if (target.replacing === "hand") {
    return (
      "这一对中间那枚通道混合的九个数不在这张表里（是手工填的）。界面不覆盖人手工写的数——" +
      "要改它请点开那张九宫格自己改，或者先删掉那枚节点，再按这一档折进来。"
    );
  }
  if (target.replacing) return null;
  if (nodes.length >= nodeLimit) {
    return (
      `这条链已经满了（引擎下发的每链上限 ${nodeLimit} 个节点），折进来要占一格。` +
      "先删掉一枚不要的节点，或者把某几枚套进并联支路里腾出这一格。"
    );
  }
  return null;
}

/** 那一对中间有几枚通道混合（拒绝那句要报数，不报一个猜来的数）。 */
function countMatricesInside(nodes: GradeNode[]): number {
  const marks = wrapMarks(nodes);
  if (!marks) return 0;
  const [head, tail] = marks;
  return nodes.filter((node, index) => node.kind === "matrix" && index > head && index < tail).length;
}

/** 折过之后那一行说什么。没折过就说不许说「已经」；折过就把换档与叠加这两件事分清楚。 */
export function foldWords(row: GamutMatrixPreset | null): string {
  if (!row) {
    return (
      "这一段现在没按那张表折过基色；挑一档按「折进这一格」。"
    );
  }
  return (
      `这一段已经按表折了「${row.label}」；再点同一档是换掉那一枚节点。`
    );
}

/** 同一格的悬停：那一行不说的来历——那九个数谁算的、两端读的是不是同一枚节点。
 *  1.210：这些话原来各占面板上一行灰字，与上面那句同属「这一格现在怎样」和「它的来历」两件事，
 *  拆开之后一行留在眼前、来历挂在这格的 `title` 上（`desktop_prose_check` 钉着这里不许长出第二行灰字）。 */
export function foldProvenance(row: GamutMatrixPreset | null): string {
  if (!row) {
    return (
      "这一格里还没有通道混合。折进来那九个数字由引擎算（基色矩阵，随 capabilities.gamut_matrices 交下来），"
      + "界面一份都不抄，也不在这里自己算矩阵。"
    );
  }
  return (
    `「${row.label}」那九个数字由引擎算（基色矩阵，随 capabilities.gamut_matrices 交下来），界面只搬过来；`
    + "预览那张九宫格与导出那条链子读的是同一枚节点，所以「预览一个色、成片另一个色」在这一步上没有发生的余地。"
  );
}
