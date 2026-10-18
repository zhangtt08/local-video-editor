/**
 * 1.197 的壳层检查：界面的字与圆角只从那套刻度里取，不再有小字。
 *
 * 为什么单独一档：这一版的活不是「顺手调几个数」。之前 `desktop/src/styles.css` 里有 184 处写死的
 * `font-size: Npx`，最小的一档 9px，10.5px 以下堆着 38 处——同一块信息（素材名 + 时长 + 状态）
 * 用三行小字叠出来，读的人要俯身去看。苹果那套的做法相反：**先定一套字号与圆角的刻度，控件跟着
 * 刻度长高**，最小的那一档只留给「画在图形里」的字（时间线刻度、针牌、徽标）。所以这一档钉的是：
 * 1) 刻度本身在、且最小一档不低于量出来的可读下限；2) 全表没有一处绕过刻度的字面量字号或圆角；
 * 3) 控件给新字号腾出了空间（高度、内边距）；4) 打进发布包的那份 CSS 带着同一套刻度——
 * 源码改了、包里还是旧的那一套，用户看到的仍然是小字。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");

/** 刻度：名字与下限。这里的下限不是拍脑袋——9~10.5px 那一档在 100% 缩放下量不到笔画，
 *  而 11.5px 是时间线最小的一格（针道 12px）还能容下一枚字形的最大档。 */
const SCALE: [string, number][] = [
  ["--fs-micro", 11.5],
  ["--fs-label", 12.5],
  ["--fs-body", 13.5],
  ["--fs-strong", 15],
  ["--fs-title", 18],
  ["--fs-glyph", 20],
  ["--fs-hero", 22],
];
const RADII: [string, number][] = [
  ["--r-xs", 6],
  ["--r-sm", 8],
  ["--r-md", 12],
  ["--r-lg", 15],
];

const tokenValue = (name: string): number => {
  const hit = css.match(new RegExp(`\\${name}: *([\\d.]+)px`));
  assert.ok(hit, `刻度里没有 ${name} 这一档（没有刻度就等于每处各写各的）`);
  return Number(hit![1]);
};
for (const [name, floor] of [...SCALE, ...RADII]) {
  const value = tokenValue(name);
  assert.ok(value >= floor, `${name} 缩到 ${value}px 了，这版定的是不低于 ${floor}px`);
}
let previous = 0;
for (const [name] of SCALE) {
  const value = tokenValue(name);
  assert.ok(value > previous, `${name} 没有比上一档大（刻度成了平级就没有层次了）`);
  previous = value;
}

// 1) 字面量：一张表都不许绕过刻度。行号一起交回去，改的人才不用猜。
const offenders: string[] = [];
const lines = css.split(/\r?\n/);
lines.forEach((text, index) => {
  const font = /font-size: *([\d.]+)px/.exec(text);
  if (font) offenders.push(`${index + 1} 行字号 ${font[1]}px`);
  const radius = /border-radius: *([\d.]+)px/.exec(text);
  if (radius) offenders.push(`${index + 1} 行圆角 ${radius[1]}px`);
});
assert.deepEqual(
  offenders,
  [],
  `有 ${offenders.length} 处写死的字号/圆角没走刻度：${offenders.slice(0, 8).join("；")}`
);
// 界面那一侧也不许另开一处（字幕用的是 cqh，跟着画面缩放，不在这一档的范围内）
for (const source of ["desktop/src/textStyle.ts", "desktop/src/views/Preview.tsx", "desktop/src/views/Timeline.tsx"]) {
  const text = read(source, `../../${source}`);
  assert.ok(
    !/fontSize: *["'`][\d.]+px/.test(text) && !/font-size: *[\d.]+px/.test(text),
    `${source} 里另写了一处像素字号（界面上就有两套字号了）`
  );
}

// 2) 控件给新的字腾地方。这些数是这版一起量的：13.5px 的字塞进 28px 的按钮上下就只剩 6px。
const room: [RegExp, number, string][] = [
  [/\.btn\s*\{[^}]*height: *([\d.]+)px/, 32, "按钮"],
  [/\.icon-btn\s*\{[^}]*height: *([\d.]+)px/, 30, "图标按钮"],
  [/\.input\s*\{[^}]*padding: *([\d.]+)px/, 8, "输入框上下"],
  [/\.panel-head\s*\{[^}]*height: *([\d.]+)px/, 38, "面板标题条"],
];
for (const [pattern, floor, where] of room) {
  const hit = css.match(pattern);
  assert.ok(hit, `读不到「${where}」的高度（这一档就没法量它让没让地方）`);
  assert.ok(Number(hit![1]) >= floor, `${where}只有 ${hit![1]}px，这版定的是不低于 ${floor}px`);
}
assert.ok(tokenValue("--tb-h") >= 44, `标题栏只有 ${tokenValue("--tb-h")}px，窗口自己的那排按钮跟着字一起长`);
assert.ok(tokenValue("--sb-h") >= 28, `状态栏只有 ${tokenValue("--sb-h")}px`);

// 3) 圆润：卡片与弹层用最大的那一档，不是每处各写各的
for (const selector of ["\\.card", "\\.status-card", "\\.proj-card", "\\.boot-card", "\\.howto"]) {
  const hit = css.match(new RegExp(`${selector}\\s*\\{[^}]*border-radius: *(var\\(--r-[a-z]+|50%|0)[^}]*\\}`));
  assert.ok(hit, `${selector.replace("\\", "")} 的圆角没走刻度`);
  assert.ok(
    hit![1] === "var(--r-lg)" || hit![1].startsWith("var(--r-lg"),
    `${selector.replace("\\", "")} 用的不是最大的那一档圆角（现在是 ${hit![1]}）`
  );
}
assert.ok(/--edge-hi:/.test(css), "卡片表面那道很淡的顶部高光没了（圆角要靠一道边光才看得出是抬起来的）");

// 4) 1.199：圆润再往里一档——分段控件是一枚胶囊、弹层用同一档大圆角、动效只有一条曲线。
const slot = /\n\.seg \{([^}]*)\}/.exec(css);
assert.ok(slot && /border-radius: var\(--r-pill\)/.test(slot[1]), "分段控件的槽不是那枚胶囊");
const thumb = /\n\.seg button \{([^}]*)\}/.exec(css);
assert.ok(thumb && /border-radius: var\(--r-pill\)/.test(thumb[1]), "分段控件选中那颗不是胶囊（还是方块）");
const lit = /\n\.seg button\.active \{([^}]*)\}/.exec(css);
assert.ok(lit && /var\(--edge-hi\)/.test(lit[1]), "选中那颗没有抬起来（少了那道边光，就只是换了块底色）");
for (const layer of ["toast", "dialog", "help", "boot-card"]) {
  const hit = new RegExp("\\n\\." + layer + " \\{([^}]*)\\}").exec(css);
  assert.ok(hit, `读不到 ${layer} 那一条规则`);
  assert.ok(
    /border-radius: var\(--r-lg\)/.test(hit![1]),
    `${layer} 用的不是最大那一档圆角（弹层该与卡片同一档）`
  );
}
const clipRule = /\n\.clip \{([^}]*)\}/.exec(css);
assert.ok(clipRule && /border-radius: var\(--r-md\)/.test(clipRule[1]), "时间线那一片用的不是这一档的圆角");
assert.ok(
  /\.dialog-backdrop, \.help-backdrop \{[^}]*backdrop-filter: blur\(/.test(css),
  "弹层背后那层纱没有模糊（浮起来的那一层看不出来是浮起来的）"
);
assert.ok(/--dur: \.\d+s/.test(css), "动效没有那一条时长刻度");
assert.ok(/--ease: cubic-bezier\(/.test(css), "动效没有那一条曲线刻度");
const swings = [...css.matchAll(/transition:([^;]*);/g)].map((row) => row[1].trim());
const strays = swings.filter(
  (text) => !text.includes("var(--dur)") && !text.startsWith("none") && !/^width \.3s$/.test(text)
);
assert.deepEqual(strays, [], `还有各写各毫秒的过渡：${strays.slice(0, 3).join(" | ")}`);
assert.ok(swings.length >= 5, `读到 ${swings.length} 条过渡，量具没摆开`);

// 6) 1.201：选中态是软底胶囊而不是那条 2px 下划线、聚焦有一圈软环、按下去有一下反馈、工具条不挤
const tabOn = /\n\.rail-tabs button\.active \{([^}]*)\}/.exec(css);
assert.ok(tabOn && /background: var\(--accent-soft\)/.test(tabOn[1]), "选中的页签没有那一层软底（还是只靠下划线说话）");
assert.ok(tabOn && /border-bottom-color: transparent/.test(tabOn[1]), "选中的页签还在用那条 2px 下划线");
const tabOff = /\n\.rail-tabs button \{([^}]*)\}/.exec(css);
assert.ok(tabOff && /border-radius: var\(--r-pill\)/.test(tabOff[1]), "页签那一颗不是胶囊");
assert.ok(/\.input:focus \{[^}]*box-shadow: 0 0 0 3px var\(--accent-soft\)/.test(css), "输入框聚焦没有那一圈软环");
assert.ok(/\.btn:active \{[^}]*transform: scale\(\.97\)/.test(css), "按下去没有那一下反馈");
const btnSwing = /\.btn \{[^}]*transition:([^;]*)/.exec(css);
assert.ok(btnSwing && /transform var\(--dur\)/.test(btnSwing[1]), "那一下反馈不走刻度那条曲线");
const gapOf = (selector: string) => {
  const hit = new RegExp(selector + "[^}]*gap: *(\\d+)px").exec(css);
  assert.ok(hit, `读不到 ${selector} 那一排`);
  return Number(hit![1]);
};
assert.ok(gapOf("\\.tl-toolbar \\{") >= 5, `时间线工具条那一排只有 ${gapOf("\\.tl-toolbar \\{")}px 间隔，挤成一堆不算圆润`);
assert.ok(/\.tl-toolbar \.divider-v \{[^}]*border-radius: var\(--r-pill\)/.test(css), "工具条里那道竖分隔不是圆的");
assert.ok(/\.lib-thumb \{[^}]*border-radius: var\(--r-md\)/.test(css), "素材缩略图那一块不是 1.199 那一档圆角");

// 5) 打进发布包的那份 CSS 带着同一套刻度——源码改了、包里没有，用户看到的还是旧的那一套
const dir = [
  resolve(process.cwd(), "desktop/dist/renderer/assets"),
  resolve(process.cwd(), "../../desktop/dist/renderer/assets"),
].find(existsSync);
assert.ok(dir, "没有构建产物（先跑 npm run build，这一档量的是打包那一份）");
const assets = readdirSync(dir!).filter((name) => name.endsWith(".css"));
assert.equal(assets.length, 1, `构建产物里该有一份 CSS，现在 ${assets.length} 份`);
const packed = readFileSync(resolve(dir!, assets[0]), "utf8");
for (const [name] of SCALE) assert.ok(packed.includes(`${name}:`), `打包的 CSS 里没有 ${name}（那份是旧的）`);
const packedBad = [
  ...new Set((packed.match(/font-size:\s*([\d.]+)px/g) ?? []).map((text) => Number(/([\d.]+)px/.exec(text)![1]))),
].filter((value) => value < tokenValue("--fs-micro"));
assert.deepEqual(packedBad, [], `打包的 CSS 里还有低于刻度的字号：${packedBad.join("、")}px`);
const packedRadius = [
  ...new Set(
    (packed.replace(/border-radius:\s*var\(--r-[a-z]+\)/g, "").match(/border-radius:\s*([\d.]+)px/g) ?? []).map(
      (text) => Number(/([\d.]+)px/.exec(text)![1])
    )
  ),
];
assert.deepEqual(packedRadius, [], `打包的 CSS 里还有写死的圆角：${packedRadius.join("、")}px`);

console.log(
  `desktop_uiscale_check: 界面只从那套刻度里取字与圆角——7 档字号最小 ${tokenValue("--fs-micro")}px、4 档圆角最大 ${tokenValue("--r-lg")}px，` +
    `全表 ${lines.length} 行里没有一处写死的字号/圆角，按钮 ${css.match(/\.btn\s*\{[^}]*height: *([\d.]+)px/)![1]}px 起，` +
    `打包那份 CSS（${assets[0]}）带着同一套刻度`
);
