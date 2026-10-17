/**
 * 1.191 的壳层检查：窗口矮下去时，被压缩的必须是时间线，不是监视器。
 *
 * 为什么单独一档：这条不是「顺手调个 CSS」。先按高度逐档扫了一遍（`sweep_1191.cjs`，emulated
 * 视口、宽 1040）：旧形状下视口高 380/460/540 时画面那一块是 2×2（等于没有），620 时 124×70，
 * 700 时 267×150，800 时 396×223——而时间线从头到尾钉着 261 不让。门槛找到之后，再用**同一把尺的
 * 真实窗口**量了前后一对：发布包自己允许的最小窗口（`electron/main.ts` 的 MIN_SIZE = 1040×660，
 * 里面 1016×568）上，旧的固定高让画面那一块只剩 **32×18**，换成这条公式后是 **245×138**——
 * 调色、合层、跟遮罩这些活在第一对数下根本做不下去，而窗口大小是软件自己允许的，用户没做错什么。
 *
 * 所以这一档钉的是「谁让步」这件事只有一处说法：时间线的高度由视口算出来并夹住，
 * 保留多少写在一个变量里；旧的「固定高度 + flex: none」那一条必须不在，
 * source-open 那一档也不能再抄第二个公式。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const shell = read("desktop/electron/main.ts", "../../desktop/electron/main.ts");

const line = (pattern: RegExp, where: string): string => {
  const hit = css.match(pattern);
  assert.ok(hit, where);
  return hit[0];
};

// 1) 一条公式、两个常数：让步的是时间线，保留多少由 `--preview-reserve` 一处说。
const rule = line(
  /\.editor \.timeline \{ height: clamp\(\s*180px,\s*var\(--timeline-height, 300px\),\s*calc\(100dvh - var\(--preview-reserve\)\)\s*\);\s*\}/,
  "时间线的高度不是「按视口夹住」那一条公式（窗口一矮就轮到画面被挤没了）"
);
assert.ok(rule.includes("100dvh"), "公式里没有视口这一项");
assert.ok(
  /\.editor \{[^}]*--preview-reserve: 430px;/.test(css),
  "常态那一档没交代给画面保留多少（430 这个数是在发布包最小窗口 1016×568 那一格量出来的：留出这一截，画面才有 245×138）"
);
assert.ok(
  /\.editor\.source-open \{ --preview-reserve: 510px; \}/.test(css),
  "源片那一档的保留数不在它该在的地方（那一屏多一条取源片的横条）"
);

// 2) 旧形状必须彻底不在：固定高度、以及第二份抄来的 clamp 公式。
assert.ok(
  !/\.editor \.timeline \{ height: var\(--timeline-height/.test(css),
  "又写回了「时间线固定高、绝不让步」那一条"
);
assert.ok(
  !/\.editor\.source-open \.timeline \{ height: clamp/.test(css),
  "同一条公式被抄了两份（两处就会有两个答案，改一处漏一处）"
);
const defines = (css.match(/--preview-reserve:/g) ?? []).length;
assert.equal(defines, 2, `保留数只该定义两处（常态、源片），现在 ${defines} 处`);
const uses = (css.match(/var\(--preview-reserve\)/g) ?? []).length;
assert.equal(uses, 1, `这条公式以外不许再有第二个消费者，现在 ${uses} 处`);

// 3) 画面那一块仍然是「按比例装进盒子」，不是把盒子撑起来。
const monitor = line(/^\.monitor \{[^}]*\}/m, "监视器那条规则不见了");
assert.ok(
  /aspect-ratio: 16 \/ 9/.test(monitor) && /max-height: 100%/.test(monitor),
  "监视器不再是按比例装进那一片（保留再多也会被它顶穿）"
);

// 4) 这一档的数字是从发布包自己的最小窗口来的：那一条动了，这里必须重新量。
const min = shell.match(/const MIN_SIZE = \{ width: (\d+), height: (\d+) \};/);
assert.ok(min, "壳里那条最小窗口尺寸读不出来（这一档的判据就是按它量的）");
assert.deepEqual([Number(min![1]), Number(min![2])], [1040, 660],
  `最小窗口改成 ${min![1]}×${min![2]} 了：那一格的画面得重新量，别照抄 320×180`);

console.log(
  "desktop_previewfloor_check: 窗口矮下去时让步的是时间线——一条按视口夹住的公式、保留数只在 --preview-reserve 一处、旧固定高不在、第二份 clamp 不在，且判据仍钉着发布包那个 1040×660 最小窗口"
);
