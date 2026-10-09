/** 遮罩跟踪的三个旋钮要活得过「换一个工程」「重开一次窗口」。
 *
 * 1.87 给人复现了这三个控件，1.88 量清它们是界面状态：同一次会话里留着，换一个工程或重开窗口
 * 就回默认。这一版把它们记进应用偏好。为什么不记进工程状态：元数据那条路（`updateProjectMeta`）
 * 每写一次就涨一个 revision 并清空撤销栈，等于拿用户的编辑历史换一个勾选。
 *
 * 门禁钉的是读回来的规矩，不是「有没有调 localStorage」：
 * 上限只由引擎的 `capabilities.limits` 给——存着的数比这台引擎的天花板大，读出来必须夹回去；
 * 存坏了一个数（NaN、负数）要退回引擎给的默认，而不是把 0 帧当成「猜 0 帧」；
 * 两个开关没存过就是开着的，只有明确的 "0" 才算关。
 */

import assert from "node:assert/strict";

const store = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
  setItem: (key: string, value: string) => void store.set(key, String(value)),
  removeItem: (key: string) => void store.delete(key),
};

const { readTrackingDefaults, rememberTrackingDefaults } = await import("../desktop/src/effects");

const GAP = "agentcut.trackGap";
const SWEEP = "agentcut.trackSweep";

// 没存过：用引擎给的默认，两个开关都是开的。
assert.deepEqual(readTrackingDefaults(60, 240), { gap: 60, sweep: true, scale: true }, "空存储回引擎默认");

// 存过就留着——「换一个工程、重开一次窗口」在读回来的就是这一条。
rememberTrackingDefaults({ gap: 120, sweep: false, scale: false });
assert.deepEqual(readTrackingDefaults(60, 240), { gap: 120, sweep: false, scale: false }, "三个旋钮都要活过下一次读");

// 天花板听引擎的：同一份存储，换一台天花板更低的引擎，读出来被夹回去。
assert.equal(readTrackingDefaults(60, 90).gap, 90, "上限是引擎的数，不是界面写死的");
assert.equal(readTrackingDefaults(60, 240).gap, 120);

// 只改一个不许动另外两个。
rememberTrackingDefaults({ gap: 30 });
assert.deepEqual(readTrackingDefaults(60, 240), { gap: 30, sweep: false, scale: false }, "部分写入只碰它点名的那个");

// 存坏的数退回默认：NaN 与负数都不许变成「猜 0 帧」这种看起来合法的值。
store.set(GAP, "abc");
assert.equal(readTrackingDefaults(60, 240).gap, 60, "读不懂的数回引擎默认");
store.set(GAP, "-5");
assert.equal(readTrackingDefaults(60, 240).gap, 60);
store.set(GAP, "");
assert.equal(readTrackingDefaults(60, 240).gap, 60, "空串是没存过，不是「猜 0 帧」——`Number(null)` 恰好是 0，这一条就是它咬人的地方");
// 0 是存得下来的合法值（一次都不猜），不能被当成「没存过」。
store.set(GAP, "0");
assert.equal(readTrackingDefaults(60, 240).gap, 0, "0 帧是明确的设置，不是缺失");

// 开关只认明确的 "0"；别的都算开着——引擎的默认就是 true。（先把先前写下的 "0" 撤掉，
// 这一条要测的是「没存过」，不是「存过 false」。）
store.delete("agentcut.trackScale");
store.set(SWEEP, "");
assert.deepEqual(readTrackingDefaults(60, 240), { gap: 0, sweep: true, scale: true });
// 而存成 "0" 就是关：同一个键，存过与没存过必须读得出差别。
rememberTrackingDefaults({ scale: false });
assert.equal(readTrackingDefaults(60, 240).scale, false, "明确的关闭要留着");

// 存储不可用（隐私模式抛错）时界面照常工作，读回默认、写不炸。
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceeded");
  },
};
assert.deepEqual(readTrackingDefaults(75, 240), { gap: 75, sweep: true, scale: true }, "存不下也要能读出来");
rememberTrackingDefaults({ gap: 1 });

console.log("PASS: 三个跟踪旋钮活过下一次读、天花板听引擎的、存坏的数回默认、0 帧算明确设置、存储抛错也不影响界面");
