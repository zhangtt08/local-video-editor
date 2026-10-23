/**
 * 1.275: the help modal stops dumping the whole feature encyclopedia under 「快捷键」.
 *
 * The old KEYS array mixed two things: entries with a `·` are feature explanations, entries
 * without one are hand-feel keys. This pins the split (no entry can fall through), the new
 * searchable/grouped 「功能」 tab, the keys tab rendering only hand-feel keys, and the styles
 * taking their type and radius from the shared tokens rather than hard-coded numbers.
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const help = read("desktop/src/views/Help.tsx", "../../desktop/src/views/Help.tsx");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");

const entries = [...help.matchAll(/\{ key: "([^"]+)"/g)].map((match) => match[1]);
const features = entries.filter((key) => key.includes("·"));
const hand = entries.filter((key) => !key.includes("·"));
assert.ok(features.length >= 40, `功能条目只有 ${features.length} 条，像是把 KEYS 整个删了`);
assert.ok(hand.length >= 20, `手感键只有 ${hand.length} 条`);
assert.equal(features.length + hand.length, entries.length, "有一类条目既不在功能里也不在手感键里");

assert.match(help, /const FEATURES = KEYS\.filter\(\(item\) => item\.key\.includes\("·"\)\)/,
  "功能百科不是按「·」从同一张表里分出来的");
assert.match(help, /const HAND_KEYS = KEYS\.filter\(\(item\) => !item\.key\.includes\("·"\)\)/,
  "手感键不是按「·」分出来的");
assert.match(help, /"start" \| "areas" \| "features" \| "keys" \| "concepts"/,
  "页签没有「功能」这一档");
assert.ok(help.includes('onClick={() => setTab("features")}>功能</button>'), "没有「功能」页签的按钮");
assert.match(help, /aria-label="搜索功能说明"/, "没有可搜索的输入框");
assert.match(help, /featureMatches\.length/, "搜索没有按关键词过滤");
assert.match(help, /featureGroups\.map\(\(group\) =>/, "功能条目没有分组");
assert.match(help, /className="help-group"/, "分组不是可折叠的一块");
assert.ok(help.includes('item.key.split("·").slice(1).join("·") || item.key'),
  "组内条目没有去掉重复的主题前缀");
assert.ok(help.includes("没有匹配「"), "搜索为空时没有一句人读得懂的话");
assert.ok(!help.includes("{KEYS.map((item) => ("), "快捷键页签还在摊整张 KEYS 表");
assert.match(help, /\{HAND_KEYS\.map\(\(item\) => \(/, "快捷键页签没有只画手感键");
assert.ok(help.includes("每个功能入口背后的做法与量过的边界在「功能」页签"), "手感键那一节没有指向功能页");
assert.ok(help.includes("命令键位在「快捷键」页签"), "功能页没有把命令键位指回去");

assert.match(css, /\.feature-search \{[^}]*display:\s*flex/, "搜索行没有排成一行");
assert.match(css, /\.feature-search \.input \{[^}]*flex:\s*1 1 auto/, "搜索框没有真正吃掉剩下的宽度");
assert.match(css, /\.feature-search \.hint \{[^}]*flex:\s*0 0 auto/, "条数那一格会把搜索框挤窄");
assert.match(css, /\.help-group \{[^}]*border-radius:\s*var\(--r-sm\)/, "分组没有用共享圆角");
assert.match(css, /\.help-group \{[^}]*background:\s*var\(--panel\)/, "分组没有用面板底色");
assert.match(css, /\.help-count \{[^}]*font-size:\s*var\(--fs-label\)/, "条数没有用共享字号");
const block = css.slice(css.indexOf(".feature-index"), css.indexOf(".help-count") + 200);
assert.ok(!/\bfont-size:\s*\d+(\.\d+)?px/.test(block), "功能索引里写了死字号");
assert.ok(!/\bborder-radius:\s*\d+(\.\d+)?px/.test(block), "功能索引里写了死圆角");

// 1.276：正文里的 `**这一句**` 必须在屏幕上变成粗体，不是留两颗星——四个渲染点共用一处折法。
const count = (text: string, needle: RegExp) => (text.match(needle) ?? []).length;
assert.equal(count(help, /\{richBody\(item\.body\)\}/g), 4, "帮助那四处正文没有都走同一把折法");
assert.doesNotMatch(help, /\{item\.body\}/, "还有一处把正文原样摊在屏幕上（星号会露出来）");
assert.equal(count(help, /export function richBody\(/g), 1, "折粗体的地方不止一处");
assert.match(help, /<strong key=\{`b\$\{step\}`\}/, "粗体那一截不是按 ** 成对折出来的");
console.log(
  "desktop_helpindex_check: PASS: KEYS 按「·」拆成功能百科与手感键，功能页可搜索、按主题折叠、"
  + "快捷键页只留手感键，样式只用共享字号与圆角",
);
