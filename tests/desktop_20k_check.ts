/** 1.131：时间线只画窗口里的那些——窗口算术只有一处，命中判定一个字都不改。
 *
 * 装机量出来的事实是：两万段时打包好的页面画了 0 段，自己那棵进程树涨到 2,994 MB（渲染进程单独
 * 2,370 MB / 10.41 秒用户态 CPU）之后那个进程消失，此后每一次 `Runtime.evaluate` 都在五秒上限内
 * 不回话，而同一时刻引擎答同一条 GET 只用 0.96 秒。所以问题不是算不过来，是一次把两万张卡片全建
 * 出来。窗口化把「建卡片」绑在看得见的宽度上。
 *
 * 1.133 补的是第一次渲染：effect 要等提交以后才量得到视口，所以 1.131 留的「没量到就不裁」这条
 * 规矩等于让首帧把两万张卡片建完（`Debugger.pause` 四轮都停在那一次）。窗口从此必填，量不到时
 * 当作看见 `FIRST_PAINT_PIXELS` 宽。
 *
 * 这里断的是四件事：① 窗口算术的边界（两边各多涂两秒、贴着边缘的段不许一边有一边没有、首帧有界）；
 * ② 挑中的段即便在窗口外也照旧要画——「挑中一整组再横向拖」是既有手感，裁切不许把它裁掉；
 * ③ 框选拖过的时间跨度整个要并进窗口，因为命中判定仍然是按 DOM 矩形数的，那一条链子里的
 *    每一段都必须存在；④ 建多少卡片与段的总数无关（两万段也只建这么多）。
 */

import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

import {
  FIRST_PAINT_PIXELS,
  WINDOW_PAD_TICKS,
  countHidden,
  firstView,
  laneTicks,
  paintClips,
  rulerSeconds,
  rulerStep,
  unionRange,
  WINDOW_NOTE,
} from "../desktop/src/timelineWindow";

const SRC = "C:/Users/Administrator/Desktop/项目/agentcut/";
const timeline = readFileSync(SRC + "desktop/src/views/Timeline.tsx", "utf8");
const harness = SRC + "scripts/renderer_scale.cjs";

const T = 70_560_000; // 一秒的刻度，与契约同一个数
const HEAD = 112;
const ROW = 56;

type Shape = { id: string; position_ticks: number; duration_ticks: number };
const clip = (index: number, seconds: number, length = 1): Shape => ({
  id: `c${index}`,
  position_ticks: seconds * T,
  duration_ticks: length * T,
});

// —— ① 窗口算术 ————————————————————————————
const px = 100; // 一秒 100 像素
const wide = { left: 0, width: 1280 };
const at0 = laneTicks(wide, px, HEAD, 60 * T);
assert.equal(at0.from, 0, "滚到最左时窗口不许伸进负的时间");
assert.ok(
  at0.to > 12.8 * T && at0.to < 12.9 * T + WINDOW_PAD_TICKS,
  `窗口右边那两秒的加涂要在数里看得见：${JSON.stringify(at0)}`,
);

const scrolled = laneTicks({ left: 10_000, width: 1280 }, px, HEAD, 200 * T);
const rawFrom = ((10_000 - HEAD) / px) * T;
const rawTo = ((10_000 - HEAD + 1280) / px) * T;
assert.ok(Math.abs(rawFrom - scrolled.from - WINDOW_PAD_TICKS) < 1, `左边正好多涂两秒：${scrolled.from}`);
assert.ok(Math.abs(scrolled.to - rawTo - WINDOW_PAD_TICKS) < 1, `右边正好多涂两秒：${scrolled.to}`);
assert.deepEqual(laneTicks({ left: 5_000, width: 1280 }, px, HEAD, 20 * T), { from: 20 * T, to: 20 * T }, "滚过头时窗口贴在结尾，不许跑到时间线外面去");
// 1.133：量不到视口的那一帧也有界。1.131 在这里写的是「不裁」，而 effect 要等第一次提交以后才量得到——
// 于是两万段那份工程在**首帧**就把两万张卡片建完（1.132 装机：渲染进程 2,370 MB 之后消失）。
const firstTo = ((FIRST_PAINT_PIXELS - HEAD) / px) * T + WINDOW_PAD_TICKS;
assert.deepEqual(
  laneTicks({ left: 0, width: 0 }, px, HEAD, 30 * T),
  { from: 0, to: firstTo },
  "量不到视口就当看见 FIRST_PAINT_PIXELS 宽：减去轨道名那一栏再除以缩放，两边各多涂两秒",
);
assert.deepEqual(
  laneTicks(firstView(), px, HEAD, 30 * T),
  laneTicks({ left: 0, width: 0 }, px, HEAD, 30 * T),
  "首帧那个默认宽度就是这里读的这一个",
);
assert.deepEqual(
  laneTicks(firstView(), px, HEAD, 3 * T),
  { from: 0, to: 3 * T },
  "三秒的小工程不会因为「当作看见 1200 像素」而少画一段——上限还是时间线自己",
);
assert.deepEqual(laneTicks(wide, 0, HEAD, 30 * T), { from: 0, to: 30 * T }, "唯一的出口是没有比例可换算（px<=0）；缩放被 store 夹在 16..320，那条夹法由 desktop_zoomclamp_check.ts 钉");

// 边界：正好压在窗口两边上的段必须画，压不住的必须不画
const range = { from: 10 * T, to: 20 * T };
const edges = [clip(1, 9, 1), clip(2, 10), clip(3, 19), clip(4, 20), clip(5, 21)];
assert.deepEqual(
  paintClips(edges, range).shown.map((item) => item.id),
  ["c1", "c2", "c3", "c4"],
  "两端各算一次：尾点落在 from 上、起点落在 to 上的都要在",
);
assert.equal(paintClips(edges, range).hidden, 1, "窗口外那一段要数得出来");

// —— ② 挑中的段不许被裁掉 ————————————————————————————
const far = [clip(1, 1), clip(2, 100), clip(3, 101)];
const picked = new Set(["c2", "c3"]);
const withSelection = paintClips(far, range, picked);
assert.deepEqual(withSelection.shown.map((item) => item.id), ["c2", "c3"], "选中的即使远在窗口外也照旧画");
assert.equal(withSelection.hidden, 1, "只有没被挑中的那一段算窗口外");
assert.equal(countHidden(far, range, picked), 1, "总数与逐个挑的是同一处算出来的");
assert.equal(countHidden(far, range), 3, "一段都没挑中时，这三条全在窗口外");

// —— ③ 框选那一段跨度要整个并进窗口（命中判定仍按 DOM 矩形）————————————
assert.deepEqual(unionRange(range, { from: 0, to: 5 * T }), { from: 0, to: 20 * T }, "往左拖就往左长");
assert.deepEqual(unionRange(range, { from: 30 * T, to: 40 * T }), { from: 10 * T, to: 40 * T }, "往右拖就往右长");
assert.deepEqual(unionRange(range, null), range, "没在拖的时候窗口就是窗口");
const insideMarquee = paintClips(edges, unionRange(range, { from: 18 * T, to: 25 * T }));
assert.deepEqual(insideMarquee.shown.map((item) => item.id), ["c1", "c2", "c3", "c4", "c5"], "框住的每一条都必须存在，否则按矩形命中的那一步会漏");

// —— ④ 建的卡片数量与段的总数无关 ————————————————————————————
const many = Array.from({ length: 20_000 }, (_, index) => clip(index, index));
const began = performance.now();
const paintedMany = paintClips(many, laneTicks(wide, px, HEAD, 20_000 * T));
const cost = performance.now() - began;
assert.ok(paintedMany.shown.length <= 20, "一秒一段、视口 12.8 秒，最多也就画十几张");
assert.equal(paintedMany.hidden, 20_000 - paintedMany.shown.length, "没画的那些要一个不落地数出来");
assert.ok(cost < 20, `筛两万段本身不该是那个瓶颈：${Math.round(cost)}ms`);
const firstPaint = paintClips(many, laneTicks(firstView(), px, HEAD, 20_000 * T));
assert.ok(
  firstPaint.shown.length <= 20,
  `首帧也要有界——1.132 量到的那次崩溃就在这一次：建了 ${firstPaint.shown.length} 张`,
);
assert.equal(firstPaint.hidden, 20_000 - firstPaint.shown.length, "首帧没画的那些也要一个不落地数出来，那句话才念得出实数");
const pickedMany = paintClips(many, { from: 0, to: T }, new Set(["c19999"]));
assert.equal(pickedMany.shown.length, 3, "窗口一秒：c0 在里面、c1 的起点正好压在右端（两端各算一次）、再加上最右被挑中那一段");
assert.deepEqual(pickedMany.shown.map((item) => item.id), ["c0", "c1", "c19999"], "被挑中的那一段与窗口里的段一起画，顺序还是原样");

// —— 尺子也只数窗口里的那些（同一个毛病的第二处）————————————————
assert.deepEqual(rulerStep(150), 1, "放大到一秒一像素级别时才给整秒刻度");
assert.deepEqual([rulerStep(70), rulerStep(34), rulerStep(33)], [2, 5, 10], "间隔表只有一份，缩放时不能两头各数一遍");
assert.deepEqual(rulerSeconds({ from: 0, to: T }, 20 * T, px), [0, 2], "一秒 100 像素时刻度两秒一道，只数窗口里的那些");
assert.deepEqual(
  rulerSeconds({ from: 98 * T, to: 104 * T }, 200 * T, px),
  [98, 100, 102, 104],
  "窗口两边各多涂的那两秒也要把外侧的刻度带进来，不能整条尺子跳格",
);
assert.equal(
  rulerSeconds(laneTicks(wide, px, HEAD, 20_000 * T), 20_000 * T, px).length,
  8,
  "两万秒的尺子在这一屏上只出八道刻度，而不是两万道",
);
assert.deepEqual(rulerSeconds({ from: 4 * T, to: 9 * T }, 5 * T, px), [4], "窗口伸到结尾之外时不许把刻度数到时间线外面去");
assert.equal(rulerStep(100), 2, "视图里那一屏用的就是这个间隔");

// —— 那句话 ————————————————————————————————————————
const said = WINDOW_NOTE(19_980);
assert.ok(said.includes("19980") && said.includes("没有画"), `要说得出到底差多少段：${said}`);
assert.ok(said.includes("仍在工程里") && said.includes("滚"), "要说人听得懂的出路：${" + said.slice(0, 60) + "}");

// —— 视图那边只剩「问一处」，不许自己再算一遍 ————————————————
assert.ok(timeline.includes("const painted = paintClips(clips, paint, selectedIds).shown;"), "画哪些只由这一处决定");
assert.ok(timeline.includes("const paintRange = unionRange(laneTicks(view, px, HEAD, contentTicks), marqueeSpan);"), "窗口 = 视口 ∪ 正在拖的框，而且永远是个窗口");
assert.ok(timeline.includes("useState<View>(firstView)"), "首帧就带着一个有界的视口进场，不许是 null");
assert.ok(!timeline.includes("useState<{ left: number; width: number } | null>"), "视口那一格不再有「还没量到」这个状态（框选、拖动那些 null 是别的，不许一起误伤）");
assert.ok(timeline.includes("paint: TickRange;"), "轨道行收的是必填的窗口——留着 null 就是留着那条不裁的路");
assert.ok(timeline.includes("{outside ? <span className=\"tl-window-note\""), "那句话在有差时才出现，判断只在这一处");
assert.ok(timeline.includes("paint={paintRange}"), "整条时间线用的是同一个窗口");
assert.ok(timeline.includes("rulerMarks(contentTicks, px, project, paintRange)"), "尺子跟着同一个窗口走");
assert.ok(timeline.includes("const marks = rulerSeconds(window, total, px);"), "尺子的刻度只由那一处算");
assert.ok(!timeline.includes("px >= 150 ? 1"), "间隔表不许在视图里再抄一份（1.133 删掉的是「没有窗口就从 0 数到底」那条分支顺带抄的那张）");
assert.ok(timeline.includes("setMarqueeSpan(null)"), "松手之后窗口要收回来，不然一次框选就把整条时间线画满了");
assert.ok(timeline.includes("{painted.map((clip) => ("), "卡片按窗口里的那一份建");
assert.ok(timeline.includes("{painted.filter((clip) => clip.transition_in).map("), "转场那颗徽章也跟着窗口，不许在两万段上各建一颗");
assert.ok(!timeline.includes("{clips.map((clip) => ("), "旧的「整条轨全建」那一步不许还留着");
assert.ok(timeline.includes("countHidden(Object.values(project.clips), paintRange, new Set(app.selectedClips))"), "还差多少段也只数一处");
assert.equal(timeline.split("countHidden(").length - 1, 1, "视图里不许出现第二处数法");
assert.ok(timeline.includes('className="tl-window-note"') && timeline.includes('role="status"'), "没画的那些要说出来，不是悄悄少画");
assert.ok(existsSync(harness), "这个缺陷要有一个能量出来的尺：scripts/renderer_scale.cjs");
assert.ok(timeline.includes("const HEAD = 112;") && timeline.includes("const ROW = 56;"),
  "视图那两个几何常量动了，这里的窗口换算就要跟着动，不能各自数一遍");

console.log(`PASS: 窗口算术四处边界都对，两万段只建 ${paintedMany.shown.length} 张卡片（筛 ${Math.round(cost)}ms）`);
