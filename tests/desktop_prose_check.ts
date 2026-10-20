/**
 * 面板上那一行只说「这一格现在怎么了」，长段说明必须在帮助里，来历必须在悬停里。
 *
 * 为什么单独一档：圆润化做了六档，管的都是字号、圆角与颜色；**话的长度**没人管，于是检查器那一列
 * 长出了一段三四行、比正文小一号、还用着最暗一档字色的灰字（最长的一段 450 多个汉字）——用户说的
 * 「拒绝用小字堆信息」，本体就是这里。把长度钉进门禁才有意义：今天收成一行的那一格，明天有人
 * 顺手再补两句就又回去了，而所有旧断言都不会红。
 *
 * 1.210 补了量具的两个瞎处：
 * ① 只读 `className="hint"` 那一种写法。`hint dim`、`hint blocked`、`hint mono` 全都不匹配，
 *    于是「同一格再补一行灰字」这条最常见的长法，门禁一条都看不见——本轮装机复核看到的那两格
 *    四到六行灰字，就是这么长出来的。现在按前缀匹配，并把源文件改成**动态枚举**：新增一个视图
 *    不需要谁记得把它加进名单。同一条尺还漏过一次第三种写法：`className="hint" title=…`
 *    ——属性跟在类名后面时 `hint[^"]*">` 就断了（本轮挂上悬停之后当场少了一条），所以现在匹到
 *    `>` 为止，属性写几个都算。
 * ② 只数源码里写死的字。住在 `workingWords()` / `colorSpaceWords()` 里、由函数拼出来的那些句子
 *    一个字都没被数过。现在把它们**叫起来量**：数源码写在哪儿是数给门禁看的，人看的是屏幕上占几行。
 *
 * 判据是量出来的，不是拍的：本轮把渲染层里每一条可见说明（含 hint 的每一种变体）都数了一遍，
 * 收完之后最长的那一条是 57 字。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
// 那些住在模块里、由函数拼出来的句子——把它们叫起来量。
import { foldProvenance as spaceFoldProvenance, foldWords as spaceFoldWords, workingProvenance, workingWords } from "../desktop/src/workingSpace";
import { foldProvenance as gamutFoldProvenance, foldWords as gamutFoldWords } from "../desktop/src/gamutFold";
import { colorSpaceWords, managedWords } from "../desktop/src/colorManage";
import type { ClipColorSpaceReport, ColorSpace } from "../desktop/src/engine";

declare const REPO_ROOT: string;

const root = REPO_ROOT.endsWith("/") ? REPO_ROOT : `${REPO_ROOT}/`;
const read = (rel: string) => {
  const found = resolve(root, rel);
  assert.ok(existsSync(found), `找不到源文件：${rel}`);
  return readFileSync(found, "utf8");
};

// 上限不是口味：342px 那一列去掉内边距约 318px，正文那一档一个汉字约 13.5px，一行约 23 字。
// 60 字 = 那一列里两行半，也是「一句拒绝 + 一条此刻真走得通的出路」说完整所需的长度
// （本轮量到的最长一条是色彩管理问失败那句，56 字）。来历不算：它不在这一行里说。
const LIMIT = 60;
const cjk = (text: string) => (text.match(/[\u3400-\u9fff]/g) ?? []).length;

// ② 叫起来量：面板那一行每一条分支返回的话都不许超过同一上限。
const rows = [{ id: "bt709", label: "BT.709 分段曲线（容器那一格的本意）" }, { id: "gamma", label: "纯幂 2.4" }];
const spaces = new Map<string, string>([["srgb", "sRGB"], ["rec709", "Rec.709"], ["gamma22", "gamma 2.2"]]);
const spaceLabel = (space: ColorSpace) => spaces.get(space) ?? String(space);
const receipt = (fields: Partial<ClipColorSpaceReport>): ClipColorSpaceReport =>
  ({ space: null, reason: "no_color_tags", auto_source_would_work: false, color_transfer: null,
    color_space: null, color_primaries: null, color_range: null, tag: null, ...fields }) as ClipColorSpaceReport;
const spoken: [string, string][] = [
  ["工程基色·没下发名单", workingWords("rec709", undefined)],
  ["工程基色·不在名单里", workingWords("dci_p3", ["rec709"])],
  ["工程基色·就是 Rec.709", workingWords("rec709", ["rec709", "dci_p3"])],
  ["工程基色·别的档", workingWords("dci_p3", ["rec709", "dci_p3"])],
  ["折叠曲线·没下发名单", spaceFoldWords("bt709", undefined)],
  ["折叠曲线·不在名单里", spaceFoldWords("xyz", rows)],
  ["折叠曲线·默认那一档", spaceFoldWords("bt709", rows)],
  ["折叠曲线·换了一档", spaceFoldWords("gamma", rows)],
  ["基色折叠表·没折过", gamutFoldWords(null)],
  ["基色折叠表·折过了", gamutFoldWords({ label: "灰度 BT.709" } as never)],
  ["色彩管理·没套", managedWords(null, 0, spaceLabel)],
  ["色彩管理·只剩一枚", managedWords(null, 1, spaceLabel)],
  ["色彩管理·套着", managedWords({ source: "srgb", display: "rec709" } as never, 2, spaceLabel)],
  ["自带标记·还没问", colorSpaceWords(null, spaceLabel, "idle")],
  ["自带标记·正在问", colorSpaceWords(null, spaceLabel, "asking")],
  ["自带标记·问失败", colorSpaceWords(null, spaceLabel, "failed")],
  ["自带标记·认出来了", colorSpaceWords(receipt({ space: "srgb", tag: "iec61966-2-1" }), spaceLabel, "idle")],
  ["自带标记·引擎拒了", colorSpaceWords(receipt({ reason: "unmatched_transfer_tag", color_transfer: "smpte2084" }), spaceLabel, "idle")],
];
const spokenLong = spoken.filter(([, text]) => cjk(text) > LIMIT).map(([name, text]) => `${name} ${cjk(text)} 字`);
assert.ok(spoken.length >= 18, `只叫出 ${spoken.length} 句，量具没摆开`);
assert.deepEqual(spokenLong, [], `模块拼出来的面板句子超过 ${LIMIT} 字：${spokenLong.join("；")}`);

// ①′ 面板文件是枚举出来的，不是手写的名单：新增一个视图就自动进这把尺。
const panelFiles = [
  ...readdirSync(resolve(root, "desktop/src/views"))
    .filter((name) => name.endsWith(".tsx") && name !== "Help.tsx")
    .map((name) => `desktop/src/views/${name}`),
  ...readdirSync(resolve(root, "desktop/src"))
    .filter((name) => name.endsWith(".tsx"))
    .map((name) => `desktop/src/${name}`),
];
assert.ok(panelFiles.length >= 12, `只枚举到 ${panelFiles.length} 个面板文件，这一档就没管住整个界面`);

// ①″ 视图里写死的面板说明：`hint` 的每一切变体都算（只认 `className="hint"` 就是上一轮那两处瞎之一）。
const long: string[] = [];
let counted = 0;
for (const rel of panelFiles) {
  const source = read(rel);
  for (const hit of source.matchAll(/<p className="hint[^"]*"[^>]*>([\s\S]*?)<\/p>/g)) {
    // 花括号里的是表达式（数值、条件、函数调用），不是给人读的那行字；只数写死的汉字。
    const visible = hit[1].replace(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/g, "").replace(/<[^>]+>/g, "");
    const size = cjk(visible);
    counted += 1;
    if (size > LIMIT) {
      const line = source.slice(0, hit.index).split(/\r?\n/).length;
      long.push(`${rel.split("/").pop()}:${line} 那一条有 ${size} 个字`);
    }
  }
}
assert.ok(counted >= 60, `只读到 ${counted} 条面板说明，量具没摆开（这一档就没法证明长度被管住了）`);
assert.deepEqual(long, [], `有 ${long.length} 条面板说明超过 ${LIMIT} 个字：${long.join("；")}`);

// ③ 来历不许占面板上第二行灰字：那一格只有一条 `<p className="hint…">`，来历挂在它的 `title` 上。
// 这一条钉的是「一处一行」这个形状，不是某一串字——谁再把第二段说明摆回眼前，不管写多短都会红。
const inspector = read("desktop/src/views/Inspector.tsx");
const grade = read("desktop/src/views/GradeFields.tsx");
const cellCount = (source: string, marker: string) => {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `找不到那一格的起点「${marker}」`);
  const block = source.slice(start, source.indexOf("</div>", start));
  return (block.match(/<p className="hint/g) ?? []).length;
};
for (const marker of ["ps-working", "按表换基色"]) {
  const source = marker === "ps-working" ? inspector : grade;
  assert.equal(cellCount(source, marker), 1, `「${marker}」那一格有 ${cellCount(source, marker)} 行灰字——一格只许一行`);
}
const cells: [string, string, string][] = [
  ["workingProvenance", inspector, "工程基色那一行"],
  ["foldProvenance", inspector, "折叠曲线那一行"],
  ["foldProvenance", grade, "按表换基色那一行"],
];
for (const [fn, source, name] of cells) {
  assert.equal(source.split(`${fn}(`).length - 1, 1, `${name}：${fn} 只许出现在那一行的 title 上，一次`);
  assert.match(source, new RegExp(`<p className="hint[^"]*" title=\\{${fn}\\(`), `${name}的来历挂在悬停里，不是写在眼前`);
}
// 搬走的字必须还在，而且**在这一格的悬停里**——不是在那个月旦文件里随便哪行注释里。
// 所以量的是这三个函数返回的那句话：把返回串改短、或把某件事实删掉，都会红（整文件 `includes` 会连注释一起数，那样不红）。
for (const [name, text, needles] of [
  ["工程基色的来历", workingProvenance("p3-d65", ["rec709", "p3-d65"]), ["primaries_matrix", "抬进线性光—乘—落回", "立方体", "交付", "每一段自己的色彩管理"]],
  ["折叠曲线的来历", spaceFoldProvenance("bt709", rows), ["纯幂 2.4", "逐字节相同"]],
  ["基色折叠的来历", gamutFoldProvenance({ label: "灰度 BT.709" } as never), ["gamut_matrices", "同一枚节点", "预览一个色、成片另一个色"]],
] as [string, string, string[]][]) {
  for (const needle of needles) {
    assert.ok(text.includes(needle), `${name}里少了「${needle}」——那是搬丢了，不是收短了`);
  }
}
assert.ok(!inspector.includes("预览里那一趟折叠是引擎算的九个系数"), "那行第二句灰字又回到面板上了");
assert.ok(!grade.includes("这张表由引擎算（基色矩阵）"), "那行第二句灰字又回到面板上了");

// 收下来的字必须还在——搬去帮助，不是删掉。名字对不上就红，谁搬空了谁负责。
const MOVED_NAMES = ["检查器·那几行为什么只写一句", "检查器·遮罩关键帧与角度", "调色·节点", "合成·第二路画面", "时间线·划动与滑移", "检查器·音画链接与组合", "合成·叠一层原图", "检查器·文字样式", "调色·执行顺序与并联"];
const help = read("desktop/src/views/Help.tsx");
for (const name of MOVED_NAMES) {
  assert.ok(help.includes(`{ name: "${name}"`), `帮助「区域说明」里没有「${name}」这一条——长段是被删了，不是被搬走的`);
}
const moved = ["colorchannelmixer", "feComponentTransfer", "LAYER_POSITION", "LAYER_KEY_RANGE", "J/L cut", "mask_rotation_schedule_segments"];
for (const needle of moved) {
  assert.ok(help.includes(needle), `「${needle}」这条判断原来写在面板上，现在帮助里也找不到它了`);
}

// 1.210 起来历分两个去处：一类的在**同一格的悬停**里，其余在这页的其它条目。帮助里那条讲去向的话
// 必须两个都说到——只说「都在这页其它条目里」就成了假话（改了去处却没改这句，是本仓犯过不少次的错）。
const where = /name: "检查器·那几行为什么只写一句"[^\n]*/.exec(help);
assert.ok(where, "帮助里没有「检查器·那几行为什么只写一句」那一条");
assert.ok(where![0].includes("挂在同一格的悬停里"), `帮助那条没说到悬停这个去处：${where![0].slice(0, 180)}`);
assert.ok(where![0].includes("这一页的其它条目里"), "帮助那条把「其余在这页的其它条目里」那半句丢了");

// 明说的差别不许跟着长段一起被搬走：这三句必须还在面板上看得见。
assert.ok(grade.includes("预览与导出读同一张表") && grade.includes("只在导出里生效"), "跨通道那张表「什么时候预览、什么时候只在导出里生效」那句被搬走了——那是 1.143/1.193 明说的差别，必须留在面板上");
assert.ok(grade.includes("共用同一张窗表"), "层针「位置、大小与淡共用同一张窗表」这句被搬走了——它是那一层能不能打点的正面回答");
assert.ok(inspector.includes("切口不算一条边"), "淡那句「切口不算一条边」被搬走了——那是分割之后为什么不会凭空淡一下的答案");
// 1.143 立的那条规矩：这一格交付出去的到底是什么，不许只活在悬停里。
// 钉的是**那一行里**有这三件事实，不是整个文件某处有——整文件 `includes` 会在别处数到同一个词就放过。
const exportPanel = read("desktop/src/views/ExportPanel.tsx");
const seqStart = exportPanel.indexOf("{isSequence && (");
assert.ok(seqStart > 0, "找不到序列那一行的起点");
const seqNote = exportPanel.slice(seqStart, exportPanel.indexOf("</p>", seqStart));
for (const needle of ["每帧一个文件", "声音不在里面", "起始时间码也进不去"]) {
  assert.ok(seqNote.includes(needle), `序列那一行眼前那句少了「${needle}」——搬进悬停就是 1.143 那条规矩的复发`);
}

// 那一行走的是正文那一档，不是最暗那一档：小字 + 灰到看不清才是「堆信息」。
const css = read("desktop/src/styles.css");
const cssCode = css.replace(/\/\*[\s\S]*?\*\//g, ""); // 注释里引用旧写法不算一处违规（本轮的说明就引了一次）
const hintRule = /\n\.hint \{([^}]*)\}/.exec(cssCode);
assert.ok(hintRule, "读不到 .hint 那一条规则");
assert.match(hintRule![1], /font-size: var\(--fs-body\)/, "面板说明还停在比正文小一号的那一档");
assert.match(hintRule![1], /color: var\(--ink-2\)/, "面板说明还在用最暗那一档字色");
// 任何一条命中 `.hint` 的覆盖规则都不许再把字号调小：1.209 把基尺定在 --fs-body，
// 而 `.ps-working .hint` 那一处把它压回 --fs-label——装机读数 12.5px 就是这么来的（本轮量到的）。
const shrunk: string[] = [];
for (const rule of cssCode.matchAll(/([^\n{}]+)\{([^}]*)\}/g)) {
  const selector = rule[1].trim();
  if (!/(^|[\s,>+~(])\.hint\b/.test(selector)) continue;
  if (selector === ".hint") continue; // 基尺那一条就是它自己，上面已经量过它了
  if (/font-size\s*:/.test(rule[2])) shrunk.push(`${selector} → ${/font-size\s*:\s*([^;]+)/.exec(rule[2])![1].trim()}`);
}
assert.deepEqual(shrunk, [], `这些规则把面板说明的字号又压小了：${shrunk.join("；")}`);
// 更前一层的洞：尺认的是 `.hint` 这个**类名**，而「面板说明」是一件事。1.211 之前首页那句
// 「默认 1080p 30fps…」用的是 `.se-hint`（--fs-label + --ink-3），换个名字就整条躲过这把尺。
// 判的是「另起一个 -hint 类名又把字压小」这件事本身：`.tl-hint` 只排个版、不动字号，不算；
// `.lane-hint` 是空轨上那一句占位提示（画在道里的 7 个字，不是一段要读的说明），本轮明着放它一马。
const aliases: string[] = [];
for (const rule of cssCode.matchAll(/\.([a-z]+-hint)\s*\{([^}]*)\}/g)) {
  if (rule[1] === "lane-hint") continue;
  if (/font-size\s*:/.test(rule[2])) aliases.push(`.${rule[1]} → ${/font-size\s*:\s*([^;]+)/.exec(rule[2])![1].trim()}`);
}
assert.deepEqual(aliases, [], `这些类名在扮演「面板上那一行说明」却不走 .hint 那一档：${aliases.join("；")}`);
assert.ok(!cssCode.includes(".se-hint"), ".se-hint 又回来了：那一条正是把首页那句压成小字灰字的元凶");
assert.match(read("desktop/src/views/Home.tsx"), /<p className="hint">默认 1080p 30fps/, "首页那句要走正文那一档（它以前是 .se-hint）");
// 几何这一半：那一行说明要自己占一整行。flex 行不换行时汉字会被挤到一格一个字——
// 本轮装机量到 .grade-auto-row 里那条说明是 27px 宽、25 行高。字收短了而形状没修，用户看到的还是那堆竖排小字。
assert.match(cssCode, /\.batch-actions \{[^}]*flex-wrap: wrap/, "那一行是 flex 却没有换行——说明会被挤成竖排");
assert.match(cssCode, /\.batch-actions > \.hint \{[^}]*flex: 1 1 100%/, "面板说明没有被安排成自己占一整行");
// 基尺那一条自己也要会占一行：1.211 的跨屏扫描在导出面板量到 68px/5 行，那一处不是 `.batch-actions`，
// 补在一处不如写在基尺上——从此任何 flex 容器里的说明默认自己占一行。
assert.match(hintRule![1], /flex: 0 0 100%/, "面板说明的基尺没有「自己占一整行」这一项");
assert.match(hintRule![1], /min-width: 0/, "没写 min-width：flex 项会被内容撑破，长句仍可能溢出");
assert.match(cssCode, /\.scope-body \.hint \{[^}]*flex: none/, "示波器旁那一行的例外必须是明写的例外，不能靠碰巧");
// grid 那一半：`.field` 是 `68px | 1fr` 两列，说明作为第三个子元素会被排到**下一行的 68px 标签列**里
// （1.211 扫描在导出面板量到的就是这一处：68px 宽、画 5 行）。
assert.match(cssCode, /\.field > \.hint \{[^}]*grid-column: 1 \/ -1/, "字段格里的说明没有被排到整行");

console.log(
  `desktop_prose_check: ${panelFiles.length} 个面板文件里 ${counted} 条说明最长 ${LIMIT} 字以内（含 hint 的切变体、含函数拼出来的那 ${spoken.length} 句），` +
    "来历挂在那一格的 title 上、一格只许一行灰字，" +
    `收下来的长段都在帮助那 ${MOVED_NAMES.length} 条里，三句「明说的差别」仍留在面板上`
);
