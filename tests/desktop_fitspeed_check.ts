// 1.233：变速「适配到几秒」——按目标时长反算播放速度，放不下就点名它能放成几秒。
//
// 这一档跑纯函数：倍率怎么算、整帧怎么折、越界怎么拒、带曲线为什么拒、已经合适为什么不动。
// 界面那一侧只钉「一条写入口、一个回执」。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fitSpeedPercent } from "../desktop/src/effects";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const SECOND = 70_560_000;
const FRAME = 2_940_000; // 24 fps
const clip = (seconds: number, speed = 100, curve: { at_ticks: number; percent: number }[] | null = null) =>
  ({ id: "c", duration_ticks: Math.round(seconds * SECOND), speed_percent: speed, speed_curve: curve }) as never;

// ① 4 秒按 100% 放进 8 秒：50%
const half = fitSpeedPercent(clip(4), 8, FRAME);
assert.equal(half.percent, 50);
assert.match(half.words, /100% → 50%/, "回执没说速度从多少变到多少");
assert.match(half.words, /从 4\.00 秒变成 8\.00 秒/, "回执没说时长怎么变");

// ② 4 秒按 200%（消耗 8 秒源）放进 8 秒：100%
assert.equal(fitSpeedPercent(clip(4, 200), 8, FRAME).percent, 100);

// ③ 贴着上限也算得出来：4 秒放进 1 秒正好 400%
assert.equal(fitSpeedPercent(clip(4), 1, FRAME).percent, 400);

// ④ 越界拒绝，并点名这段能放成几秒（4 秒的源：400% 下 1 秒、25% 下 16 秒）
const tooShort = fitSpeedPercent(clip(4), 0.5, FRAME);
assert.equal(tooShort.percent, undefined, "放不进去还给了个倍率");
assert.match(tooShort.words, /25%–400%/, "拒绝没说量程");
assert.match(tooShort.words, /1\.00–16\.00 秒/, "拒绝没说这段能放成几秒");
const tooLong = fitSpeedPercent(clip(4), 20, FRAME);
assert.equal(tooLong.percent, undefined);
assert.match(tooLong.words, /1\.00–16\.00 秒/);

// ⑤ 已经合适：给回同一个数，回执说不用改
const same = fitSpeedPercent(clip(4), 4, FRAME);
assert.equal(same.percent, 100);
assert.match(same.words, /不用改/);

// ⑥ 带曲线变速：没有单一倍率，先拒并说清出路
const curved = fitSpeedPercent(clip(4, 100, [{ at_ticks: 0, percent: 100 }, { at_ticks: SECOND, percent: 50 }]), 8, FRAME);
assert.equal(curved.percent, undefined);
assert.match(curved.words, /先关掉曲线/);

// ⑦ 目标折成整帧：8.01 秒在 24fps 上落到 8.00 秒（192 帧），倍率仍是 50
const snapped = fitSpeedPercent(clip(4), 8.01, FRAME);
assert.equal(snapped.percent, 50);
assert.match(snapped.words, /8\.00 秒/);

// ⑧ 零与负数不装懂
assert.match(fitSpeedPercent(clip(4), 0, FRAME).words, /大于零/);
assert.match(fitSpeedPercent(clip(4), -3, FRAME).words, /大于零/);

// ⑨ 界面：一处写、一处回执，曲线那一段仍归曲线编辑器
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
assert.match(inspector, /import \{[^}]*fitSpeedPercent[^}]*\} from "\.\.\/effects"/, "界面没有读那个函数");
assert.match(inspector, /id="clip-fit"/, "没有目标时长那一格");
assert.match(inspector, /fitSpeedPercent\(clip, Number\(fitSeconds\), frameTicks\(/, "没有按当前帧率去算");
assert.match(inspector, /if \(fit\.percent\) setClipSpeed\(clip\.id, fit\.percent \/ 100\)/, "算出来没有交给那一条写入口");
assert.match(inspector, /\{fitSaid \? <p className="hint" role="status">\{fitSaid\}<\/p> : null\}/, "回执没画出来");
assert.equal((inspector.match(/setClipSpeed\(/g) ?? []).length >= 1, true, "播放速度那一处不见了");

console.log("PASS: 适配时长按源消耗反算倍率、折成整帧、越界点名能放成几秒、带曲线先拒、已经合适不动");
