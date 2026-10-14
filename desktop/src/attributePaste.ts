/** 1.163「粘贴属性」界面这一侧唯一的一处判断。
 *
 * 名单、上限、哪一类有东西、哪一段接不下——这些都不是界面说了算，全读引擎交回来的那一份
 * （`capabilities.attribute_categories` 与那份规划回执）。这个模块只排对话框、只念回执，
 * 不重算任何一个数，也不自己再列一遍类别的名字：1.158 与 1.161 两次都因为界面自抄名单被门禁红过。
 */

import type { AttributeCategory, AttributeCategoryReport, AttributePlan } from "./engine";
import { errorHint } from "./engine";
import type { AttributeCopy } from "./clipboardStore";
import { humanDuration } from "./time";

/** 对话框里的一行：勾、中文名、那句「这一类搬什么」、以及这一段在这一类里真有多少东西。 */
export type AttributeRow = {
  id: string;
  label: string;
  note: string;
  hasContent: boolean;
  count: string;
};

/** 这一类在来源那一段上有多少东西，只念引擎报的那几个数。 */
function countWords(row: AttributeCategoryReport): string {
  const number = (key: string) => Number(row[key] ?? 0);
  switch (row.category) {
    case "color":
      return `链上 ${number("nodes")} 个节点，曝光／对比度／饱和度改过 ${number("adjusted") ? "一处以上" : "没有"}`;
    case "effects":
      return `改了 ${((row.fields as string[]) ?? []).length} 个旋钮`;
    case "animation":
      return `${number("curves")} 条曲线、${number("keyframes")} 枚针`;
    case "mask":
      return row.shape
        ? `${String(row.shape)}，另有 ${number("curves")} 条遮罩曲线、${number("outlines")} 帧轮廓`
        : `没有画遮罩${number("curves") ? `，但有 ${number("curves")} 条遮罩曲线` : ""}`;
    case "fade": {
      const windows = (row.windows as number[][]) ?? [];
      const ticks = windows.flat();
      return ticks.some((value) => value > 0)
        ? windows.map((pair) => `${humanDuration(pair[0])}→${humanDuration(pair[1])}`).join(" · ")
        : "两头都没有淡";
    }
    case "speed":
      return `${number("speed_percent")}%${number("curve_points") ? `，另有 ${number("curve_points")} 个速率点` : ""}`;
    case "text":
      return row.has_text ? `样式改过 ${number("adjusted")} 项（文字内容不搬）` : "这一段不是文字";
    default:
      return row.has_content ? "有内容" : "没有内容";
  }
}

/** 名单只来自能力表；老引擎没这一档，对话框就一行都排不出来（那颗按钮跟着不亮）。 */
export function dialogRows(
  categories: AttributeCategory[] | undefined,
  report: AttributeCategoryReport[] | undefined,
): AttributeRow[] {
  const seen = new Map((report ?? []).map((row) => [row.category, row]));
  return (categories ?? []).map((row) => {
    const found = seen.get(row.id);
    return {
      id: row.id,
      label: row.label,
      note: row.note,
      hasContent: found ? found.has_content === true : false,
      count: countWords(found ?? { category: row.id, label: row.label, note: row.note, has_content: false }),
    };
  });
}

/** 默认勾「有东西的那些类」——没东西的类勾上是把目标清空，那是要人自己点的决定。 */
export function defaultTicked(rows: AttributeRow[]): string[] {
  return rows.filter((row) => row.hasContent).map((row) => row.id);
}

/** 目标就是现在选中的那些，来源自己不算目标（引擎那句拒绝也这么说）。 */
export function pasteTargets(source: string, selected: string[]): string[] {
  return [...new Set(selected)].filter((clipId) => clipId !== source);
}

/** 灰掉的那颗按钮必须点名一条真走得通的出路（1.89 立过的规矩）。null 才是能点。 */
export function copyBlocker(
  project: { id: string } | null,
  selected: string[],
  features: Record<string, boolean> | undefined,
): string | null {
  if (!features?.attribute_paste) {
    return "这一版引擎没有「粘贴属性」这一档。升级引擎后再用；工程与命令本身不受影响。";
  }
  if (!project) return "先打开一个工程。";
  if (selected.length === 0) return "先在时间线上选中一段——复制属性认的是「这一段」。";
  if (selected.length > 1) {
    return `现在选中了 ${selected.length} 段。复制属性一次只认一个来源：留一段在主选中（单击它），其余可以先当目标。`;
  }
  return null;
}

export function pasteBlocker(
  stored: AttributeCopy | null,
  project: { id: string } | null,
  targets: string[],
  features: Record<string, boolean> | undefined,
): string | null {
  const blocked = copyBlocker(project, project ? [stored?.clipId ?? ""] : [], features);
  if (!stored) return "还没有复制过属性：先选中一段，点「复制属性」。";
  if (blocked) return blocked;
  if (!project || stored.projectId !== project.id) {
    return `复制来的那一段住在工程 ${stored.projectId} 里，和当前工程不是一个：回到它那边再粘，或在这里重新复制一次。`;
  }
  if (!targets.length) {
    return "选中要粘上去的片段（Shift 点加选，或在空白处拉框挑一组），来源自己不算目标。";
  }
  return null;
}

/** 类别 id → 中文名，读的是引擎在这份回执里同时交回的那张表（1.115 那条规矩：
 *  契约 id 不当用户界面用，界面也不许自己再列一份名单）。 */
function labelOf(plan: AttributePlan, id: string | null): string {
  if (!id) return "这一类";
  const found = plan.all_categories.find((row) => row.category === id) ?? plan.categories.find((row) => row.category === id);
  return found ? String(found.label ?? id) : id;
}

/** 一句拒绝的写法只有一处：对话框里预览的那几行与粘完之后那支提示用的是同一句。 */
export function refusalLines(plan: AttributePlan): string[] {
  return plan.refusals.map(
    (row) => `${row.clip_id} 拿不到「${labelOf(plan, row.category)}」：${errorHint(row.code) || row.message}`,
  );
}

/** 那份规划回执念成人话的一句标题与一句详情。数字全部来自引擎，这里不做第二次除法。 */
export function pasteSaid(plan: AttributePlan, targets: number): { title: string; detail: string } {
  const wrote = plan.written.length;
  const same = plan.unchanged.length;
  const title = wrote
    ? `已粘贴属性 · ${wrote} 段（选了 ${targets} 段）`
    : same
      ? "这些片段已经和来源一样"
      : "这一段没能粘进任何一类";
  const parts: string[] = [];
  if (wrote) {
    parts.push(plan.written.map((row) => `${row.clip_id}：${row.categories.length} 类`).join("、"));
  }
  if (same) parts.push(`${same} 段本来就是这份数，一条命令都没为它发`);
  parts.push(...refusalLines(plan));
  if (plan.beyond_tail_keyframes) {
    parts.push(
      `另有 ${plan.beyond_tail_keyframes} 枚针落在那段自己的长度之外——仍在工程里，只是那一帧之后不渲染`,
    );
  }
  return { title, detail: `${parts.join("。")}。一次写入只涨一个版本，撤销一步整批回来。` };
}
