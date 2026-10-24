// 1.281：J/K/L 走带——倒放、倍速、变速静音；速度阶梯只有一处。
//
// 这一档钉的是「一条规则」与「两头都读它」：
// ① `shuttle.ts` 里那个纯函数是唯一的速度阶梯（1→2→4→8，换方向从 1 开始，上限 8）；
// ② `playhead` 的 rate 是唯一的状态：play(rate) 开、pause() 回到 1、setRate 只改速度；
// ③ 预览的时钟乘 rate、两端各自停住；倒放时元素不往前播（HTML 没有负播放率），逐格 seek；
// ④ 变速与倒放静音（元素 muted + 增益乘 0），成片与预览都不是 2× 的声音；
// ⑤ 键位：J 倒放、K 停、L 正放；源监视器里 J/K/L 只走「停/放」两条，不偷时间线的播放头；
// ⑥ 界面上那枚倍率牌读的是 play.rate，帮助页写着这三个键。
// 真页面「按 L 两次是 2×、按 J 变 -1×、按 K 停下」由 `tests/shuttle_check.py` 量。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { SHUTTLE_MAX, shuttleRate } from "../desktop/src/shuttle";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};
const count = (text: string, needle: RegExp) => (text.match(needle) ?? []).length;

const store = read("desktop/src/store.ts");
const preview = read("desktop/src/views/Preview.tsx");
const app = read("desktop/src/App.tsx");
const help = read("desktop/src/views/Help.tsx");
const css = read("desktop/src/styles.css");
const shuttle = read("desktop/src/shuttle.ts");

// ① 纯函数：阶梯与方向。
assert.equal(count(shuttle, /export function shuttleRate/g), 1, "速度阶梯不止一处");
assert.equal(SHUTTLE_MAX, 8, SHUTTLE_MAX);
assert.equal(shuttleRate(false, 1, 1), 1, "停着按 L 不是 1×");
assert.equal(shuttleRate(false, 1, -1), -1, "停着按 J 不是 -1×");
assert.equal(shuttleRate(true, 1, 1), 2, "1× 时再按 L 不是 2×");
assert.equal(shuttleRate(true, 2, 1), 4, "2× 时再按 L 不是 4×");
assert.equal(shuttleRate(true, 8, 1), 8, "8× 还能再翻");
assert.equal(shuttleRate(true, -4, -1), -8, "倒放 -4× 时再按 J 不是 -8×");
assert.equal(shuttleRate(true, 4, -1), -1, "换方向没有从 1× 重新开始");

// ② 状态：rate 只有一份。
assert.match(store, /type PlayState = \{ ticks: number; playing: boolean; rate: number \}/, "PlayState 里没有 rate");
assert.match(store, /let play: PlayState = \{ ticks: 0, playing: false, rate: 1 \}/, "初值不是 1×");
assert.match(store, /play\(rate = 1\) \{\s*setPlay\(\{ playing: true, rate \}\);/, "play(rate) 没把速度写进去");
assert.match(store, /pause\(\) \{\s*setPlay\(\{ playing: false, rate: 1 \}\);/, "pause 没把速度交回 1");
assert.match(store, /setRate\(rate: number\) \{\s*setPlay\(\{ rate \}\);/, "没有 setRate");

// ③ 时钟：乘 rate，两端各自停。
const ticker = preview.slice(preview.indexOf("if (!play.playing) return;"), preview.indexOf("}, [play.playing, play.rate, end, sourceMode]);"));
assert.ok(ticker.length > 0, "找不到走带时钟");
assert.match(ticker, /TIMEBASE \* play\.rate/, "时钟没有乘走带速度");
assert.match(ticker, /play\.rate > 0 && next >= end/, "正放到头没停");
assert.match(ticker, /play\.rate < 0 && next <= 0/, "倒放到头没停");
assert.match(preview, /\}, \[play\.playing, play\.rate, end, sourceMode\]\);/, "时钟没跟着 rate 重启");

// ④ 元素：正放乘 |rate|，倒放不往前播，变速静音。
assert.match(preview, /const reverse = rate < 0;/, "没有倒放判断");
assert.match(preview, /element\.playbackRate = Math\.min\(16, Math\.max\(\.0625, pace\.rate \* clockRate \* Math\.abs\(rate\)\)\);/, "播放率没有乘 |rate|");
assert.match(preview, /const frozen = pace\.rate <= 0 \|\| reverse;/, "倒放没有冻住元素");
assert.match(preview, /element\.muted = monitorMuted \|\| track\.muted \|\| rate !== 1;/, "变速/倒放没有静音");
assert.match(preview, /\* \(rate === 1 \? 1 : 0\) \* \(parentGain\?\.\(\) \?\? 1\)/, "增益没有在变速时归零");
assert.match(preview, /rate=\{play\.rate\}/, "时间线的层没有拿到走带速度");
assert.match(preview, /rate=\{rate\}/, "嵌套合成没有把走带速度传下去");
assert.match(preview, /role="status" aria-label=\{"播放速度 " \+ play\.rate \+ " 倍"\}/, "倍率牌没有无障碍名");
assert.match(preview, /\{play\.rate\}x<\/span>/, "倍率牌没有读 play.rate");
assert.match(css, /\.shuttle-chip \{ font-weight: 700; \}/, "倍率牌没有样式");

// ⑤ 键位：J/K/L 与源监视器。
assert.match(app, /if \(key === "j" \|\| key === "k" \|\| key === "l"\) \{ event\.preventDefault\(\); setSourcePlaying\(key === "l"\); return; \}/, "源监视器没有接住 J");
assert.match(app, /if \(key === "k"\) \{ event\.preventDefault\(\); playhead\.pause\(\); return; \}/, "K 没有停");
assert.match(app, /if \(key === "j" \|\| key === "l"\) \{/, "J/L 没有处理");
assert.match(app, /playhead\.setRate\(shuttleRate\(true, playhead\.rate, direction\)\);/, "再按没有走同一条速度阶梯");
assert.match(app, /if \(direction < 0 && playhead\.value <= 0\) return;/, "在 0 处按 J 会倒着跑出去");
assert.match(app, /import \{ shuttleRate \} from "\.\/shuttle";/, "App 没有引入速度阶梯");

// ⑥ 帮助页写着这三个键。
assert.ok(help.includes('{ key: "J / K / L", body: "倒放 / 停 / 正放；同一个方向再按一次 2×、4×、8×'), "帮助页没有 J/K/L");

console.log(
  "PASS: J/K/L 走带只有一套规则——台阶在 shuttle.ts（1→2→4→8、换向从 1 起）、rate 在 playhead 一处、" +
    "时钟乘它且两端停住、元素按 |rate| 播且变速静音、倒放逐格 seek、键位与帮助页同说这三个键",
);
