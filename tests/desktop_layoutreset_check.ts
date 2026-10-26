/**
 * 1.225 的壳层检查：「重置布局」不许自己制造那句抱怨。
 *
 * 1.194 交出「窗口太矮」那一行时，它钉的是「用户拖高过那条边、时间线让不动了要说」；
 * 这一档钉的是它的反面——**应用自己**要了一个装不下的数时，那句话就成了回头抱怨用户。
 * 1040×660 下按一次「重置布局」，扫描量到的就是 `wanted 300 / got 212`（门禁
 * `tests/ui_shape_check.py` 的 `QUIET` 那一判，两档里只有矮的那一档红）。
 *
 * 三件事一起判：
 * ① 那一个「默认高度」只能有一个主人——写死的 300 只许出现在 `layoutReset.ts` 里，
 *    视图里再出现一份就是第二条公式（1.194 那一档壳检钉的就是这个）；
 * ② 回的是**量到的**那一个数：装得下就回默认，装不下就回这一屏给得起的那一档，
 *    量不到（0/NaN）才回默认——不许出现第二条 `calc(100dvh …)`；
 * ③ 视图必须真去读那一个盒子（`.timeline` 就是 `Timeline` 自己在量的那一个），
 *    而不是读 `window.innerHeight` 再减一个魔法数。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { DEFAULT_TIMELINE, firstRunTimeline, resetLayout } from "../desktop/src/layoutReset";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const editor = read("desktop/src/views/Editor.tsx");
const timeline = read("desktop/src/views/Timeline.tsx");

// ② 算术：装得下回默认，装不下回量到的那一档，量不到才回默认。
assert.deepEqual(resetLayout(800), [300, 340, DEFAULT_TIMELINE], "窗口装得下 300 时，重置就该回默认那一档");
assert.deepEqual(resetLayout(212), [300, 340, 212], "1040×660 量到的就是 212——回 212 才不会一按就夹住");
assert.deepEqual(resetLayout(212.6), [300, 340, 213], "量到的数取整一次，别把半像素写进 CSS");
assert.deepEqual(resetLayout(0), [300, 340, DEFAULT_TIMELINE], "量不到（盒子还没挂上）才回默认");
assert.deepEqual(resetLayout(Number.NaN), [300, 340, DEFAULT_TIMELINE], "NaN 不能写进布局");
assert.equal(resetLayout(-500)[2], DEFAULT_TIMELINE, "负数（读坏了）不能写进布局");
assert.deepEqual(resetLayout(212).slice(0, 2), [300, 340], "两只面板的宽度回的是默认，不是跟着窗口缩");

// ① 那一个默认数只许有一个主人。
assert.ok(editor.includes("resetLayout("), "「重置布局」没走那唯一的一处算术");
assert.equal((editor.match(/resetLayout\(/g) ?? []).length, 1,
  "只有那一颗按钮该走「回量到的那一档」——开机那一档要的是默认数本身（它没有可量的盒子）");
assert.ok(editor.includes("firstRunTimeline("),
  "开机那一档没读那唯一的主人（`firstRunTimeline`，另写了一份默认数）");
assert.equal((editor.match(/firstRunTimeline\(/g) ?? []).length, 1,
  "开机默认高度只许一处算术：多一处就是两条规矩");
// 1.298：写死 350 在 808 高的窗口里吃掉上半屏（素材库只剩一行半卡片）。第一次打开按窗口给：
// 0.34、上限 DEFAULT_TIMELINE、下限 240；拖过的人仍以自己存的为准。
assert.equal(firstRunTimeline(808), 275, "808 高的窗口该给时间线 275px");
assert.equal(firstRunTimeline(1080), 350, "大窗口仍封顶在 DEFAULT_TIMELINE");
assert.equal(firstRunTimeline(660), 240, "矮窗口不许低于 240（再低连标尺都放不下）");
assert.equal(firstRunTimeline(Number.NaN), DEFAULT_TIMELINE, "量不到窗口高度时才回默认");
assert.equal(firstRunTimeline(0), DEFAULT_TIMELINE, "0 不是窗口高度，是「没量到」");
// 1.303：只看窗口高会漏掉「这个工程有几条轨」。四条轨要 116 + 4×68 ≈ 390px，按 0.34 给只有 275px，
// 主画面轨就被挤到折线以下——所以两者取大，且仍封顶在 DEFAULT_TIMELINE。
assert.equal(firstRunTimeline(808, 0), firstRunTimeline(808), "不给轨数时与只看窗口高等价");
assert.equal(firstRunTimeline(808, 4), DEFAULT_TIMELINE, "四条轨时按轨道合计算（封顶 DEFAULT_TIMELINE）");
assert.ok(firstRunTimeline(808, 4) > firstRunTimeline(808, 0), "四条轨的首开高度没有比空工程高");
assert.equal(firstRunTimeline(1080, 4), DEFAULT_TIMELINE, "大窗口仍封顶");
assert.equal(firstRunTimeline(808, 1), firstRunTimeline(808, 0), "一条轨时窗口高更宽裕，不该被轨数拉高");
assert.ok(!/\[\s*280\s*,\s*320\s*,\s*300\s*\]/.test(editor), "视图里还留着一份写死的 [300, 340, 300]——一条公式两个主人");
assert.ok(!/--timeline-height[^\n]*300px/.test(editor), "视图里不许再写第二条默认高度");

// ④ 「窗口太矮」只许在**有人真要过**那个数时出现：应用自己那个默认数装不下，
//    该让位的是布局，不是让用户听一句解释（1.225 在 1040×660 量到的就是这一条）。
assert.equal((editor.match(/markSplitterTouched\(\)/g) ?? []).length, 2,
  "两只手（拖与键）都要记下「这是用户要的」——少一只手，那一句话就永远不出现或永远出现");
assert.ok(/axis === 2/.test(editor), "只有时间线那一条边归这一句管，两只竖向的 splitter 不该点亮它");
assert.ok(timeline.includes("app.splitterTouched"),
  "那句「窗口太矮」没听这个旗号——开机就会替应用自己那个数抱怨用户");

// ③ 读的是那一个被量着的盒子，不是 innerHeight 减一个魔法数。
assert.ok(editor.includes('querySelector<HTMLElement>(".timeline")'),
  "重置读的不是 `.timeline` 那一个盒子——`Timeline` 量的就是它，换一处就成了第二个主人");
assert.ok(!/resetLayout\([^)]*innerHeight/.test(editor), "不许拿 innerHeight 减一个数当高度（那是第二条公式）");
assert.ok(timeline.includes('"--timeline-height"') && timeline.includes("getBoundingClientRect().height"),
  "「窗口太矮」那一句的读数口径变了——这一档与它必须量同一个盒子与同一个变量");

// 出路仍然走得通：那一行本身没有被删掉，只是不该由「重置」把它请出来。
assert.ok(timeline.includes("窗口太矮"), "那句诚实的说明不见了——用户拖高过那条边时仍然要说");
assert.ok(timeline.includes("class=\"timeline-clamped\"") || timeline.includes("timeline-clamped"),
  "那一行的类名变了，扫描的 `QUIET` 判据就量不到东西了");

console.log("PASS: 重置布局回的是这一屏量到的那一档，默认高度只有一个主人，那句「窗口太矮」只该由用户拖出来");
