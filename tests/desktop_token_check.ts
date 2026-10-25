/**
 * 1.207 的壳层检查：样式表的**引用完整性**——刻度名、过渡时长、一处规则里的重复属性。
 *
 * 为什么单独一档：圆润化做了四档（1.197~1.202），量的都是「字与圆角从刻度里取」。这一轮把尺子
 * 转向刻度**本身**：`var(--x)` 里的 x 不存在时，浏览器不会报错，只会把那条声明作废，于是那一处
 * 表面悄悄回到继承值——界面画错了，而所有断言照旧绿。实测这一档抓到的三笔都是这种情况：
 * `--muted`、`--panel-2`、`--ink-1`、`--warn` 这四个刻度在样式表里没有主人（`--warn` 尤其坏，
 * 它看着像 `--warn-soft` 的同族，其实没人定义过）；`.asset-actions` 写的是 `transition: opacity
 * .var(--dur)`——多了那个点，整条声明解析不过，悬停那排按钮从来就没有过淡入；`.busy-pill` 在同一条
 * 规则里写了两次 `box-shadow`，第二次把第一次的边光抹掉了。
 * 还有一笔是**浅色底**：`.preset` 与 `.preset-row` 的 `background: #fff`，而字继承正文那档近白
 * （`--ink` = #eceef1），对比 1.07:1——交付面板上没被选中的导出预设，整行字是看不见的。浅色底在
 * 深色界面里不是风格问题，是「同一处判断没有主人」：底色与字色必须成对来自同一套刻度。
 *
 * 这一档能红：把上面任何一笔改回去，它就在自己那条断言上红（本轮逐条量过）。
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const css = readFileSync(resolve(REPO_ROOT, "desktop/src/styles.css"), "utf8");
/** 注释不参与判断：`/* … *\/` 里的 var() 与声明都不算一处引用。 */
const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
const lineOf = (index: number) => code.slice(0, index).split(/\r?\n/).length;

// ---------- 1) 每一个 var(--x) 都得有主人（@property 交回 initial-value 也算主人） ----------
const defined = new Set<string>();
for (const hit of code.matchAll(/(--[a-z][a-z0-9-]*)\s*:/g)) defined.add(hit[1]);
for (const hit of code.matchAll(/@property\s+(--[a-z][a-z0-9-]*)/g)) defined.add(hit[1]);

const orphan: string[] = [];
for (const hit of code.matchAll(/var\((--[a-z][a-z0-9-]*)(\s*,)?/g)) {
  // 有兜底值的引用不会画错：`var(--text, #e8e2d6)` 那几处是内嵌的调色板示例，自带 fallback。
  if (hit[2]) continue;
  if (!defined.has(hit[1])) orphan.push(`${lineOf(hit.index!)} 行 var(${hit[1]})`);
}
assert.deepEqual(orphan, [], `有 ${orphan.length} 处引用了没有主人的刻度，那一处表面会静悄悄回到继承值：${orphan.slice(0, 10).join("；")}`);

// ---------- 2) 过渡与动效：时长只有刻度那一档，且不许写成 `.var(--dur)` ----------
const badTiming: string[] = [];
for (const hit of code.matchAll(/(?:transition|animation)\s*:\s*([^;}]+)/g)) {
  for (const part of hit[1].split(",")) {
    const text = part.trim();
    if (!text || /^none(\s*!important)?$/.test(text)) continue;
    // 持续转的加载指示器（spinner、启动条）本来就不是「一次交互的动效」，它要 linear + infinite。
    if (/infinite/.test(text)) continue;
    // 进度条那一条是数据驱动的宽度，1.199 起就是它自己的例外，已经钉在 uiscale 那一档里。
    if (/^width \.3s$/.test(text)) continue;
    assert.ok(
      /(?:^|\s)var\(--dur\)(?:\s|$)/.test(text) &&
        /(?:^|\s)var\(--ease\)(?:\s|$)/.test(text) &&
        !/\.\s*var\(/.test(text),
      `${lineOf(hit.index!)} 行那条动效没有同时从 --dur 与 --ease 取（或是把刻度写成了 .var）：${text}`
    );
    badTiming.push(text);
  }
}
assert.ok(badTiming.length >= 6, `只读到 ${badTiming.length} 条走刻度的动效，量具没摆开（这一档就没法证明刻度在用）`);

// ---------- 3) 一条规则里不许写两遍同一个属性：后写的那条会静悄悄抹掉前一条 ----------
const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
const dupProperty: string[] = [];
const lightBackground: string[] = [];
for (const rule of code.matchAll(ruleRe)) {
  const selector = rule[1].trim().replace(/\s+/g, " ");
  if (selector.startsWith("@") || /^--/.test(selector)) continue;
  const seen = new Map<string, number>();
  for (const raw of rule[2].split(";")) {
    const decl = raw.trim();
    const hit = /^([-a-z]+)\s*:/.exec(decl);
    if (!hit) continue;
    const name = hit[1];
    if (name.startsWith("--")) continue;
    if (seen.has(name)) dupProperty.push(`${selector} 的 ${name}（${seen.get(name)} 与 ${lineOf(rule.index! + (rule[2] ? rule[0].indexOf(rule[2]) : 0))} 行各写一次）`);
    else seen.set(name, lineOf(rule.index!));
    // 浅色底：深色界面里 `background: #fff` 配继承的近白正文，等于把那一段字藏起来。
    const bg = /(^|[^-])\bbackground(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8})\b/.exec(decl);
    if (bg) {
      const hex = bg[2].replace("#", "");
      const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex.slice(0, 6);
      const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
      const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
      const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      // 同一处规则里自己声明了深色的字，那才是真的浅色底卡片；否则字继承正文近白那一档。
      // 两档主题之后：浅色主题规则里的 var(--ink*) 本身就是深色；深色主题仍只认字面深色。
      const lightTheme = /^html\[data-theme="light"\]/.test(selector);
      const inkToken = /\bcolor\s*:\s*var\(--ink(?:-[23])?\)/.test(rule[2]);
      const darkInk =
        (/\bcolor\s*:\s*#[0-9a-fA-F]{3,8}/.test(rule[2]) &&
          !/(color\s*:\s*#(e|f|d|c)[0-9a-fA-F]{2})/i.test(rule[2])) ||
        (lightTheme && inkToken);
      // 例外只有「盛不住字的图形」：伪元素画的那根线、色轮上那颗点，里面不会有正文。
      const graphic = /::/.test(selector) || selector === ".wheel-dot";
      if (luminance > 0.5 && !darkInk && !graphic) lightBackground.push(`${selector} 的 ${bg[2]}（相对亮度 ${luminance.toFixed(2)}）`);
    }
  }
}
assert.deepEqual(dupProperty, [], `有 ${dupProperty.length} 条规则把同一个属性写了两遍：${dupProperty.slice(0, 6).join("；")}`);
assert.deepEqual(lightBackground, [], `有 ${lightBackground.length} 处浅色底配继承来的近白正文：${lightBackground.slice(0, 6).join("；")}`);

// ---------- 4) 刻度自己的层次：抬起来的表面必须一档比一档亮，字必须一档比一档大 ----------
const tokenValue = (name: string): string => {
  const hit = code.match(new RegExp(`\\${name}: *([^;]+)`));
  assert.ok(hit, `刻度里没有 ${name}`);
  return hit![1].trim();
};
const hexLuminance = (text: string): number => {
  const hex = text.replace("#", "").slice(0, 6);
  assert.equal(hex.length, 6, `${text} 不是六位十六进制，这一档算不了亮度`);
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
};
const ladder = ["--bg", "--sunk", "--panel", "--elev", "--float"].map((name) => [name, hexLuminance(tokenValue(name))] as const);
for (let i = 1; i < ladder.length; i += 1) {
  assert.ok(
    ladder[i][1] > ladder[i - 1][1],
    `${ladder[i][0]} 没有比 ${ladder[i - 1][0]} 亮（${ladder[i][1].toFixed(3)} vs ${ladder[i - 1][1].toFixed(3)}）——苹果的层次靠抬起来的表面，不亮一档就等于没浮起来`
  );
}
for (const [name, value] of ladder) {
  assert.ok(value < 0.12, `${name} 的亮度到了 ${value.toFixed(3)}，表面那一档不许亮过这个数（再亮就不是深色界面了）`);
}
const contrast = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
const inks = ["--ink", "--ink-2", "--ink-3"].map((name) => [name, hexLuminance(tokenValue(name))] as const);
for (let i = 1; i < inks.length; i += 1) {
  assert.ok(inks[i - 1][1] > inks[i][1], `${inks[i][0]} 比 ${inks[i - 1][0]} 还亮，那三档字色就没有层次了`);
}
// 尺子是对比度，不是亮度：1.207 第一版把这条写成「亮度不低于 0.35」，`--ink-3` 当场红——
// 那条判据是我编的，量不到任何东西；真正的下限是「这块字压在面板上还读不读得出来」。
for (const [name, value] of inks) {
  const ratio = contrast(value, hexLuminance(tokenValue("--panel")));
  assert.ok(ratio >= 4.5, `${name} 压在 --panel 上只有 ${ratio.toFixed(2)}:1，4.5:1 是「还能读」的那条线`);
}
const surfaces = new Map<string, number>();
for (const hit of code.matchAll(/(--(?:bg|panel|elev|elev-2))\s*:\s*(#[0-9a-fA-F]{6})/g)) {
  surfaces.set(hit[1], hexLuminance(hit[2]));
}
assert.ok(surfaces.has("--elev"), "刻度里没有 --elev：悬停与选中那一档没有主人，样式表里就会长出十几处各写各的 #2b2e34");

console.log(
  `desktop_token_check: 样式表引用完整——${defined.size} 个刻度名全部有主人，` +
    `${badTiming.length} 条动效都从 --dur/--ease 取（没有一处 .var），` +
    `没有一条规则重复属性，浅色底 0 处，表面亮度阶梯 ${ladder.map(([n, v]) => `${n} ${v.toFixed(3)}`).join(" < ")}，` +
    `三档字色压在面板上的对比度 ${inks.map(([n, v]) => `${n} ${contrast(v, hexLuminance(tokenValue("--panel"))).toFixed(1)}:1`).join("、")}`
);
