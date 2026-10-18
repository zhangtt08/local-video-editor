import type { ClipColorSpaceReport, ColorSpace, ColorTransferTag, GradeNode } from "./engine";

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
  return `只剩 ${tagged} 枚盖过章的节点，不成一对：按「套上」配一对，按「取下」删掉那一枚。`;
}

/** 1.150：来源这一头改由素材文件自己回答。界面只做界面该做的三件事：
 *  ① 决定这一档在不在、这一行该不该去问文件、那张来源下拉菜单还归不归人管；
 *  ② 把引擎那次只读的回执念成一句中文——认出来了就念它认出来的那条曲线，被拒绝了就照引擎给的
 *     理由说，并把文件里实际读到的那几个标记原样点出来；
 *  ③ 把引擎随 capabilities 下发的对照表念给人看。
 *  「哪个标记算哪条曲线」不在这里判，也不在这里查表：那是引擎 `colortags.detect_space` 一处的事，
 *  写命令那条路（`clip.color_manage` 的 `auto_source`）走的也是同一处。界面抄一份表，就是同一句话
 *  有了两个答案，而最后落在成片里的是引擎那一个——所以这整个文件里不许出现任何一个标记值。
 */

/** 回执里那四个原始标记的字段名，顺序照引擎列的那一份。字段名不是标记值：这里念得出字段叫什么，
 *  却一个标记值都不认识——认得它们是引擎那一处的事。 */
const TAG_FIELDS = ["color_transfer", "color_space", "color_primaries", "color_range"] as const;

/** 引擎那句拒绝的理由，界面只翻成中文，不改它的意思。没听过的理由照原样念出来，不悄悄换成一句
 *  顺耳的——换成顺耳的那句，就是界面在替这份素材编一个引擎并没有给出的答案。 */
const REFUSAL_WORDS: Record<string, string> = {
  no_color_tags: "一个色彩标记都没写",
  no_transfer_tag: "写了基色或量程，却没有写传递函数（那才是曲线）",
  unmatched_transfer_tag: "写的那条曲线不在引擎那张表里",
};

/** 那次只读的进度：没问过、正在问、问过但引擎没给回执。三种都得说得出，不许把「问失败了」
 *  念成「这文件没标记」——那是两句不同的话，出路也不同。 */
export type ColorSpacePhase = "idle" | "asking" | "failed";

/** 引擎有没有下发「按文件自带标记」这一档。没有就没有：界面不许假装能读。 */
export function autoSourceOffered(features: Record<string, boolean> | undefined): boolean {
  return Boolean(features?.color_manage_auto);
}

/** 这一行现在要不要去问这份文件。三个条件都得成立：引擎有这一档、人勾了它、而且这段真是画面。
 *  音频那段去问，引擎回的是 INVALID_COLOR——明知必定被拒绝的一次请求不该发出去（1.82 的规矩，
 *  按钮不许亮着骗人，读也一样）。 */
export function shouldReadColorSpace(offered: boolean, chosen: boolean, audio: boolean): boolean {
  return offered && chosen && !audio;
}

/** 那张「素材从哪里读」下拉菜单还归不归人管。勾了自带标记就先灰着（契约不许两头都答），
 *  但**引擎没这一档时必须亮着**：只知拒绝的门禁会把手工这条唯一的出路一起关死。 */
export function handPickLive(chosen: boolean, offered: boolean): boolean {
  return !offered || !chosen;
}

/** 灰掉时要说的出路；引擎没这一档时说的是手工那条路，不能提那个勾——提了就是骗人去找
 *  一个根本不存在的控件。 */
export function handPickWords(chosen: boolean, offered: boolean): string {
  if (!offered) return "素材按哪条曲线读入，在这里手工选一条：屏幕录制多是 sRGB，广播时间线是 Rec.709，SD 带子多是 gamma 2.4。";
  return chosen
    ? "勾了「来源按文件自带标记」，来源这一头就交给这份文件自己回答了；想在这里手工点名，先把那个勾去掉。"
    : "不勾上面那个勾就在这里手工点一条；勾上它，来源改由这份文件自己的标记回答（读不出曲线时引擎会点名拒绝，不会替你猜一条）。";
}

/** 交进命令的来源那一头。勾了自带标记就交 null——`auto_source: true` 配 `source_space: null`
 *  才是契约认的那一个意思；而 null 且没有 auto_source 仍然是「把这一对取下来」，一个字节都不多。 */
export function manageSourceValue(
  offered: boolean,
  chosen: boolean,
  picked: ColorSpace,
): ColorSpace | null {
  return offered && chosen ? null : picked;
}

/** 文件自己写出的那几个标记，照引擎的字段名原样念；没写的那个念成「没写」。 */
export function tagsAsRead(report: ClipColorSpaceReport): string {
  return TAG_FIELDS.map((field) => `${field}=${report[field] ?? "没写"}`).join("、");
}

/** 这一行那句「这份文件到底说了什么」。三种情形都要说得出：还没问、认出来了、被拒绝了。
 *  认出来那一句里的曲线名就是引擎回执 `space` 那一个，一个字都不换。 */
export function colorSpaceWords(
  report: ClipColorSpaceReport | null,
  label: (space: ColorSpace) => string,
  phase: ColorSpacePhase,
): string {
  if (report === null) {
    if (phase === "asking") return "正在问这份文件自带的色彩标记（那一次只读，工程一个字都不写）……";
    if (phase === "failed") {
      return "刚才问过，引擎那一次没给回执（原因已经照引擎的原话贴在右上角）。这一行不亮「套上」：" +
        "出路是去掉那个勾手工选来源，或者重新勾上再问一次。";
    }
    return "还没问过这份文件：勾上「来源按文件自带标记」就问，问完这一行写它到底说了什么。";
  }
  if (report.space !== null) {
    return `这份文件自己说它的来源是 ${label(report.space)}（引擎读到的标记：${report.tag ?? "没写"}）。` +
      "套上时来源那一头写的就是这一条，和刚才报的是同一个答案。";
  }
  const why = REFUSAL_WORDS[report.reason]
    ?? `引擎给的理由是 ${report.reason}，这一版界面还没听过，照原样念`;
  return `这份文件${why}，引擎定不出曲线，所以「按文件自带标记」在它身上用不了。` +
    `它实际写出的标记是：${tagsAsRead(report)}。`;
}

/** 勾了「按文件自带标记」之后，这颗「套上」该不该亮，不亮的时候说什么。
 *  亮不亮只看引擎那两个东西：有没有回执、回执里那句 `auto_source_would_work`。
 *  绝不看标记自己推——从标记推出「应该也能用」的那一步，就是界面在替引擎做决定。 */
export function autoSourceBlocker(
  offered: boolean,
  chosen: boolean,
  report: ClipColorSpaceReport | null,
  phase: ColorSpacePhase,
): string | null {
  if (!offered || !chosen) return null;
  if (report === null) {
    return phase === "asking"
      ? "还在问这份文件自己怎么说：来源那一头等它的答案，所以这颗按钮先不亮。稍等一下再按；不想等就去掉那个勾，手工点一条来源。"
      : "这一行还没拿到这份文件的回执，所以不亮「套上」——引擎没给出来源，界面不许替它填一个。" +
        "去掉那个勾就能手工选来源；重新勾上就是再问一次。";
  }
  if (report.auto_source_would_work) return null;
  return `${tagsAsRead(report)}——引擎读了这些标记还是定不出曲线，这条走不通。` +
    "出路就在这一行：去掉「来源按文件自带标记」那个勾，在「素材从哪里读」里手工点一条" +
    "（屏幕录制多是 sRGB，广播时间线是 Rec.709，SD 带子多是 gamma 2.4），或者用「+LUT」把厂家给的查找表套上再调。";
}

/** 引擎那张对照表怎么念：每个标记念成「标记 → 曲线」。念出来是让人看见引擎认得哪几条，
 *  界面不许拿它再算一次。返回值只可能是话，不可能是某个色彩空间——这条是这整个文件存在的理由。 */
export function transferTagWords(
  tags: ColorTransferTag[] | undefined,
  label: (space: ColorSpace) => string,
): string | null {
  if (!tags || tags.length === 0) return null;
  return `引擎认得的曲线标记：${tags.map((entry) => `${entry.tag}→${label(entry.space)}`).join("、")}。`;
}
