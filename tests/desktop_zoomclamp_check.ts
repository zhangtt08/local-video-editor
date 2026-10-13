/** 缩放的两端只有一处主人，而且读回来的那份偏好也过同一个夹子。

 `timelineWindow.laneTicks` 现在只剩一个还能交回「整条时间线」的出口：`px <= 0`（没有比例就无从换算）。
 界面里那个比例就是 `edit.pxPerSec`，所以它必须永远在能用的区间内——而 1.132 之前的 `store.ts` 把
 localStorage 里那份偏好**原样**摊进初始状态：一枚写坏的 `agentcut.edit`（0、负数、字符串、NaN）就能
 把「首帧有界」这条新规矩从门缝里退回去，而这台机器上的重开窗口读的就是那一份。

 这里跑的是真 store（照 `desktop_snappref_check.ts` 的先例，先把假 localStorage 摆好再 import），
 断的是行为而不是字面量：坏值进来要落在能用的一端、`setZoom` 两端都夹、脏值不许把现有值带走，
 以及滑杆的 min/max 与夹法读的是同一对常量。最后一条把两半接起来：夹到下限以后，两万段那一屏
 首帧仍然是有界的。
 */

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = REPO_ROOT;

const store = new Map<string, string>([["agentcut.edit", JSON.stringify({ pxPerSec: 0, tool: "select" })]]);
Object.assign(globalThis, {
  localStorage: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  },
});

const { prefs, editPrefs, ZOOM_MIN, ZOOM_MAX } = await import("../desktop/src/store");
const { firstView, laneTicks, paintClips } = await import("../desktop/src/timelineWindow");
const T = 70_560_000;

// 脏值进来：落在能用的一端，而不是原样交给界面。
assert.equal(editPrefs().pxPerSec, ZOOM_MIN, "localStorage 里那枚 0 不许原样变成界面的缩放");
assert.ok(ZOOM_MIN > 0, "下限必须是能换算的数，否则 laneTicks 那条唯一出口就走得通了");
assert.ok(ZOOM_MAX > ZOOM_MIN, "两端不许倒过来");

prefs.setZoom(9999);
assert.equal(editPrefs().pxPerSec, ZOOM_MAX, "往上一样夹住：滑杆与快捷键共用这一处上限");
prefs.setZoom(-5);
assert.equal(editPrefs().pxPerSec, ZOOM_MIN, "往下一样");
const before = editPrefs().pxPerSec;
prefs.setZoom(Number.NaN);
assert.equal(editPrefs().pxPerSec, before, "一个非数不许把用户当前的缩放带走——那是「按一下就没了」");
prefs.setZoom(62.7);
assert.equal(editPrefs().pxPerSec, 63, "落在整数像素上，卡片的位置与尺子的刻度才用同一个数");
prefs.zoomBy(1 / ZOOM_MAX);
assert.equal(editPrefs().pxPerSec, ZOOM_MIN, "连乘缩到尽头也还是那一端，不会穿过 0");

// 落进 localStorage 的那一份就是重开窗口会读回来的那一份：写出去的必须已经是夹过的。
const written = JSON.parse(store.get("agentcut.edit") ?? "{}") as { pxPerSec?: number };
assert.equal(written.pxPerSec, ZOOM_MIN, "写回去的是夹过的数，下次开机读到的就是同一个");

// 视图不许自带第二份数字。
const timeline = readFileSync(SRC + "desktop/src/views/Timeline.tsx", "utf8");
assert.ok(timeline.includes("min={ZOOM_MIN}"), "滑杆的下限就是这一处常量");
assert.ok(timeline.includes("max={ZOOM_MAX}"), "上限也是——否则界面挡的与引擎侧用的不是同一个数");
assert.ok(!/min=\{16\} max=\{320\}/.test(timeline), "旧的那对字面量不许还留在视图里");

// 两半接起来：夹到能用的下限之后，两万段那一屏的首帧仍然有界。
const many = Array.from({ length: 20_000 }, (_, index) => ({
  id: `c${index}`,
  position_ticks: index * T,
  duration_ticks: T,
}));
const first = paintClips(many, laneTicks(firstView(), ZOOM_MIN, 112, 20_000 * T));
// 界是「一屏放得下多少」而不是「工程里有多少」：一秒长的片段在最小缩放下占 ZOOM_MIN 像素，
// 再加上窗口两边各多涂的两秒——一个与段的总数无关的数。
const bound = Math.ceil(1_200 / ZOOM_MIN) + 4;
assert.ok(
  first.shown.length <= bound,
  `缩到最小时首帧也不许把两万张卡片放回来：建了 ${first.shown.length} 张，而一屏放不下 ${bound} 张`,
);
assert.equal(first.hidden, 20_000 - first.shown.length, "少画的那些要数得出来，那句话才念得出实数");

console.log(`PASS: 缩放夹在 ${ZOOM_MIN}..${ZOOM_MAX}，脏值与滑杆共用这一处，两万段的首帧仍然是 ${first.shown.length} 张`);
