/**
 * 1.291 的壳层检查：界面不许把「怎么实现的」画在人脸上，也不许把十几段控件堆成一列。
 *
 * 用户这一轮的原话是「排版没有呼吸感太拥挤了」「本地引擎部署这种小字没必要增加，徒增廉价感」。
 * 那两句话各自对应一类可判的不变量：
 *
 * ① **分组只有一处决定。** 属性页那四档（基础 / 调色 / 动画 / 特效）现在是真的各画各的：
 *   `InspGroup` 是唯一的名册，`Inspector` 收一个 `group`，每一段都要过它。页签只负责改这一个值——
 *   如果还留着「点一下滚到那一段」的锚点词表，那就是两套真相（页签说一档、滚动说另一档）。
 * ② **旧表面不许复活。** 参考图那一套之外不再留第二套壳：旧的 `TitleBar` 已经删了，
 *   它带的那几个类（`.rev-chip` / `.chip-batch` / `.rail-live` / `.rail-user` / `.ai-hero` / `.ai-foot`）
 *   在源与样式里都必须没有主人。留着就是「样式表里长出一圈没人读的规则」。
 * ③ **实现细节只许活在悬停里。** 引擎在线/版本号、revision 计数、`timeline_edit` 这类命令名、
 *   「包络互相关」「从右往左」这类算法说法，都不许成为屏上的字。这条判的是 AIPanel 那三格
 *   字符串的**分工**：`hover:` 里可以有，`line:` 与 `blocked:` 里不能有。
 * ④ **一屏只露该露的。** AI 那一张列默认四张卡，其余在「更多」后面；引擎状态只剩顶栏一颗灯。
 *
 * 这一档量的是源里的**结构**（谁判断、判断几处、谁还有主人）；屏上到底长什么样、
 * 有没有小字压小字，由 `tests/ui_shape_check.py` 在真页面上量。两边不重复也不互相顶替。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const inspector = read("desktop/src/views/Inspector.tsx");
const rightPanel = read("desktop/src/shell/RightPanel.tsx");
const aiPanel = read("desktop/src/shell/AIPanel.tsx");
const leftRail = read("desktop/src/shell/LeftRail.tsx");
const topBar = read("desktop/src/shell/TopBar.tsx");
const app = read("desktop/src/App.tsx");
const styles = read("desktop/src/styles.css");

// —— ① 分组只有一处决定 ————————————————————————————————————————————————
assert.ok(
  /export type InspGroup = "basic" \| "color" \| "motion" \| "fx"/.test(inspector),
  "分区名册不在 Inspector 里（四档各自为政，页签与渲染就会分家）",
);
assert.ok(
  inspector.includes("export function Inspector({ group = \"basic\" }: { group?: InspGroup })"),
  "Inspector 没收 group，或默认档不是 basic：那一列又会回到全部堆在一起",
);
assert.ok(
  inspector.includes("const show = (...groups: InspGroup[]) => groups.includes(group);"),
  "「这一段属于哪一档」必须有唯一一处判断，不许每段各写一次 group ===",
);
assert.ok(
  (inspector.match(/show\("/g) ?? []).length >= 12,
  "分段判断太少——多半是有段落没被页签管住，仍然常驻在这一列里",
);
assert.ok(
  /<EffectsFields key=\{`basic-\$\{clip\.id\}`\} clip=\{clip\} group="basic" \/>/.test(inspector)
  && /group="motion" \/>/.test(inspector) && /group="fx" \/>/.test(inspector),
  "变换 / 关键帧 / 特效三档必须来自同一个 EffectsFields，只是 group 不同（另写一套就会算出两套数）",
);
assert.ok(rightPanel.includes("<Inspector group={propTab} />"),
  "页签没把当前档交给 Inspector：那点一下只会滚动，不会真的分组");
assert.ok(!rightPanel.includes("scrollIntoView"),
  "页签还在用「滚到那一段」那一套：锚点与分组是两套真相，留一个");
assert.ok(!/words:\s*\[/.test(rightPanel),
  "RightPanel 里还留着锚点词表（哪一段该被哪颗页签找到，写死了两份）");
assert.ok(!/PROPERTY_TABS = \[/.test(rightPanel),
  "页签名册必须带类型（id: InspGroup），否则 Inspector 多一档这里不会红");

// —— ② 旧表面不许复活 ————————————————————————————————————————————————
assert.ok(!existsSync(resolve(process.cwd(), "desktop/src/TitleBar.tsx")),
  "旧的 TitleBar 又回来了：1.289 已经按参考图换成 LeftRail + TopBar，不留第二套壳");
assert.ok(!/[Tt]itleBar/.test(app),
  "App 还引着旧标题栏");
// 判「这条类还有没有主人」得先看真正的规则，不能把注释里提到的名字算成一条规则——
// 下面那段「为什么删」的说明就写着这些类名，算进来就成了数针也数注释。
const cssRules = styles.replace(/\/\*[\s\S]*?\*\//g, "");
for (const dead of [".ai-hero", ".ai-foot", ".rev-chip", ".chip-batch", ".rail-live", ".rail-user", ".rail-avatar"]) {
  assert.ok(!cssRules.includes(dead), `${dead} 在样式表里还留着——它的主人已经删了，这类规则只会越长越多`);
  assert.ok(!leftRail.includes(dead.slice(1)) && !topBar.includes(dead.slice(1)) && !aiPanel.includes(dead.slice(1)),
    `${dead} 还被某个视图引用：样式已删，画出来就是没样式的裸元素`);
}

// —— ③ 实现细节只许活在悬停里 ————————————————————————————————————————————————
// 屏上那两格（line / blocked）与悬停那一格（hover）的分工，就是这一轮要的东西。
const Jargon = ["包络", "互相关", "从右往左", "capabilities", "clip.grade", "clip.patch",
  "timeline_edit", "reducer", "revision", "LUFS", "百分位", "一个批次", "一个版本"];
const visibleFields = [...aiPanel.matchAll(/^\s{6}(?:line|blocked): "(.*)",$/gm)].map((m) => m[1]);
assert.ok(visibleFields.length >= 14,
  `没读出 AIPanel 屏上那几格（读到 ${visibleFields.length} 条）——这个判据会空转`);
const leaked = visibleFields.filter((text) => Jargon.some((word) => text.includes(word)));
assert.deepEqual(leaked, [], "AI 卡的可见那一行里混进了实现说法：把这些句子挪回 hover 那一格");
assert.ok(
  [...aiPanel.matchAll(/^\s{6}hover: "(.*)",$/gm)].some((m) => Jargon.some((word) => m[1].includes(word))),
  "悬停那一格里也没有出处与上限——那说明这些字是被删掉了，不是被收进了悬停",
);
// 版本号、引擎状态这类「本地部署」的话，不许出现在左栏与顶栏的文字里。
assert.ok(!/引擎在线|引擎未连接|app_version|v\$\{|本地引擎/.test(leftRail),
  "左栏又要把引擎版本画在人脸上了");
assert.ok(!/rev-chip|project\.revision/.test(topBar),
  "顶栏不许再打印 revision 计数（它在历史那一屏有地方说）");
assert.ok(/class(Name)?=.*conn/.test(topBar),
  "引擎状态得留一颗灯——删字可以，把人看不见的状态一起删掉不行");

// —— ④ 一屏只露该露的 ————————————————————————————————————————————————
const primaries = (aiPanel.match(/primary: true/g) ?? []).length;
assert.equal(primaries, 4, `AI 面板默认该露四张卡（参考图那一张列），现在写了 ${primaries} 张`);
assert.equal((aiPanel.match(/primary: false/g) ?? []).length, 3,
  "另外三张要留在「更多」后面——一张都不留就没有收口这回事");
assert.ok(aiPanel.includes("const shown = more ? cards : cards.filter((card) => card.primary);"),
  "「露几张」必须是一处判断，别在渲染里再写一遍");
assert.ok(aiPanel.includes("aria-expanded={more}"),
  "那颗「更多」得把自己开合的状态报给读屏，不然它只是一句装饰");
// 呼吸感：属性段落的内边距不许被压回 14px 那一档（那是「没有呼吸」量出来的那一档）。
const sectionPadding = styles.match(/^\.insp-section \{ padding: (\d+)px/m);
assert.ok(sectionPadding && Number(sectionPadding[1]) >= 18,
  `.insp-section 的竖向内边距回到了 ${sectionPadding?.[1]}px——四档分页之后不需要再靠挤来塞东西`);
// 曾经有一档「让 AI 列表更紧凑」的补丁，专门把 gap 压小；卡片收口之后它不该再存在。
assert.ok(!/\.ai-panel \{ gap: 10px/.test(styles),
  "那条把 AI 列表压紧凑的旧补丁还在：默认只剩四张卡，呼吸位交回令牌那一档");

const shellFiles = readdirSync(resolve(process.cwd(), "desktop/src/shell")).filter((f) => f.endsWith(".tsx"));
assert.deepEqual(shellFiles.sort(), ["AIPanel.tsx", "LeftRail.tsx", "RightPanel.tsx", "TopBar.tsx"],
  "壳层的文件名册变了——新加一块表面就得同时进这一档检查");

console.log("PASS: 呼吸感这一轮的四处不变量都在——分区只有一处判断（Inspector 收 group、页签只改那一个值）、"
  + `旧壳与它的六个类都没有主人、AI 卡的可见行不含 ${Jargon.length} 个实现说法（黑话只在 hover）、默认 ${primaries} 张卡收口、`
  + "引擎状态只剩顶栏一颗灯");
