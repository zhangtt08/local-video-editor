/** 吸附开关只有一个，而且关掉的是同一处：时间线磁吸、快捷键 S、动画曲线复选框共用一份持久偏好。

 1.111 之前曲线编辑器自己 `useState(true)` 数了一份「时间吸附」，而状态栏那颗吸铁石（和 S 键）读的是
 `EditPrefs.snap`——界面上同时存在两个互不相干的开关，关掉一个另一个还亮着，用户没法知道到底吸附了
 没有。这一版把曲线那份局部状态删掉，两处都读同一份偏好；偏好仍只写进 localStorage（不是工程状态：
 元数据那条路每点一次就涨一个 revision 并清空撤销栈，见 AGENTS.md 的 1.93 注）。

 这里跑的是**真 store**（按 desktop_batch_check.ts 的先例用假 window/localStorage 驱动），所以断的是
 行为：翻一处另一处跟着变、落进 localStorage 的那份就是重开窗口时会读回来的那份、以及曲线那份几何
 真的按这同一个布尔值走。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const store = new Map<string, string>();
Object.assign(globalThis, {
  localStorage: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  },
});

const { prefs, editPrefs } = await import("../desktop/src/store");
const { keyframeTick } = await import("../desktop/src/keyframeSnap");
const TIMEBASE = 70_560_000;
const FRAME = Math.floor((TIMEBASE * 1001) / 30000);

// 一处开关：默认开着，翻它的是同一份状态——两个方向都要翻得动，否则那颗按钮就成了「永远开着」。
assert.equal(editPrefs().snap, true, "snapping starts on");
prefs.setSnap(false);
assert.equal(editPrefs().snap, false, "the checkbox's target value is honoured, not a blind flip");
prefs.toggleSnap();
assert.equal(editPrefs().snap, true, "the magnet button and the S shortcut flip the same value on");
prefs.toggleSnap();
assert.equal(editPrefs().snap, false, "and off again — a toggle has to be a toggle in both directions");
prefs.toggleSnap();
assert.equal(editPrefs().snap, true, "two toggles land back where they started");

// 关掉之后，重开窗口读回来的必须是关：写进 localStorage 的那一份就是启动时展开的那一份。
const written = JSON.parse(store.get("agentcut.edit") ?? "{}");
assert.equal(written.snap, true, "the preference is persisted under the one key the shell reads at boot");
prefs.setSnap(false);
assert.equal(JSON.parse(store.get("agentcut.edit") ?? "{}").snap, false, "and it lands there again on the next write");

// 同一份偏好喂给曲线那份几何：开着落在格线上，关掉只取整。
const lattice = { clip: { position_ticks: 0, duration_ticks: 10 * FRAME }, quantum: FRAME, span: 10 * FRAME, plot: 924 };
const none = { playhead: null, keys: [], attract: false };
prefs.setSnap(true);
assert.equal(keyframeTick(FRAME * 3 + 900_000, lattice, editPrefs().snap, none), FRAME * 3, "on: the lattice answers");
prefs.setSnap(false);
assert.equal(keyframeTick(FRAME * 3 + 900_000, lattice, editPrefs().snap, none), FRAME * 3 + 900_000, "off: the raw pointer wins, by the same switch");

// 隐私模式里写不进去也不能崩：偏好当场生效即可。
store.clear();
Object.assign(globalThis, { localStorage: { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } } });
prefs.setSnap(true);
assert.equal(editPrefs().snap, true, "a failing localStorage must not stop the switch from working");

// 界面上不许再留第二份局部状态。
const read = (part: string) => {
  const path = ["desktop/src/views/" + part, "src/views/" + part].map((p) => resolve(process.cwd(), p)).find(existsSync);
  assert.ok(path, `${part} must be readable from the check's working directory`);
  return readFileSync(path!, "utf8");
};
const curve = read("CurveEditor.tsx");
assert.doesNotMatch(curve, /const \[snap, setSnap\]/, "the curve editor may not keep its own snap state");
assert.match(curve, /const edit = useEdit\(\); const snap = edit\.snap/, "it must read the shared preference");
assert.match(curve, /onChange=\{\(e\) => prefs\.setSnap\(e\.target\.checked\)\}/, "and write it back through the same place");
assert.match(curve, /与时间线的磁吸是同一个开关/, "the tooltip must say it is the one switch");
const shell = read("Timeline.tsx");
assert.match(shell, /active=\{edit\.snap\} onClick=\{\(\) => prefs\.toggleSnap\(\)\}/, "the magnet button drives the same value");
const app = read("../App.tsx");
assert.match(app, /key === "s"\) prefs\.toggleSnap\(\)/, "and so does the S shortcut");

console.log("PASS: 吸附只剩一处开关——曲线编辑器读的是那份持久偏好、写回的也是它，关掉两处一起关，"
  + "localStorage 写不进去也照样生效");
