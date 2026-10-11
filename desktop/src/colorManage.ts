import type { ColorSpace, GradeNode } from "./engine";

/** 1.130：一键色彩管理的界面侧读法。
 *
 * 引擎用 `clip.color_manage` 一次写下两个转换节点，并给这两个都盖章 `purpose: "color_manage"`；
 * 取下时只删自己盖章的那两个。所以界面这边唯一的诚实读法就是照章认人：不猜「哪两个转换节点看起来
 * 像是色彩管理」，也不自己数链子的首尾。这一条与 `desktop_jlcut_check.ts` 立下的老规矩同一个意思：
 * 一句话不许有两份实现。
 */

export type ManagedPair = { source: ColorSpace; display: ColorSpace };

/** 这一段现在的色彩管理状态；盖章的节点不足两个、或者方向不对，都算「不齐」而不是「没有」。 */
export function managedPair(nodes: GradeNode[] | undefined): ManagedPair | null {
  const tagged = (nodes ?? []).filter((node) => node.kind === "transfer" && node.purpose === "color_manage");
  if (tagged.length !== 2) return null;
  const head = tagged[0];
  const tail = tagged[tagged.length - 1];
  if (head.kind !== "transfer" || tail.kind !== "transfer") return null;
  if (head.output_space !== "linear" || tail.input_space !== "linear") return null;
  return { source: head.input_space, display: tail.output_space };
}

export function taggedCount(nodes: GradeNode[] | undefined): number {
  return (nodes ?? []).filter((node) => node.kind === "transfer" && node.purpose === "color_manage").length;
}

/** 这一条链还套得上下两个节点吗？算法与引擎那侧一句不差：先把旧的这一对取下来，再看还剩几个位置。
 *  已经套着的片段重新套一次永远装得下——换的是同两个节点，不是新增两个。 */
export function manageFits(nodes: GradeNode[] | undefined, limit: number): boolean {
  return (nodes ?? []).length - taggedCount(nodes) + 2 <= limit;
}

/** 引擎下发的名单才是可以写进命令的名单。界面那份中文标签只是翻译：名单里出现一个没翻译过的名字，
 *  就照原样念出来——把这一项悄悄丢掉，等于用户在下拉菜单里找不到引擎认得的某个空间。 */
export function manageSpaces(
  published: ColorSpace[] | undefined,
  labels: [ColorSpace, string][],
): [ColorSpace, string][] {
  const known = new Map<string, string>(labels);
  const names = published ?? labels.map(([name]) => name);
  return names.map((name) => [name, known.get(name) ?? `（引擎新认得的 ${name}，这里还没有中文名）`]);
}

/** 状态那一句话。三种情形都得说出来：没套过、套着完整的一对、只剩一只盖过章的节点（大概是有人手工
 *  删了另一半）。把第三种念成「没套上」就是一句假话，而引擎恰好对这三种各有说法。 */
export function managedWords(
  pair: ManagedPair | null,
  tagged: number,
  label: (space: ColorSpace) => string,
): string {
  if (pair) {
    return `这一段以 ${label(pair.source)} 读入、在线性光里调色、按 ${label(pair.display)} 输出。`;
  }
  if (tagged === 0) return "这一段没有套色彩管理：调色按存储值算，不在线性光里。";
  return (
    `这一段只剩 ${tagged} 个盖过章的转换节点，不成一对（多半是手工删掉了另一半）。` +
    "按「套上」会重新配成一对，按「取下」会把还盖着章的那个删掉。"
  );
}
