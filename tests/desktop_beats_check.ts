/**
 * 1.268: the beat button is one read-only analysis plus one ordinary marker batch.
 *
 * The engine check proves the numbers. This one proves the wire: one route, one store function,
 * capability-gated button, a single submit, and no second copy of the tempo maths in the renderer.
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const store = read("desktop/src/store.ts", "../../desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const help = read("desktop/src/views/Help.tsx", "../../desktop/src/views/Help.tsx");

assert.equal(
  (engine.match(/\/v1\/projects\/\$\{projectId\}\/audio\/beats/g) ?? []).length,
  1,
  "节拍路由在壳层只许有一处",
);
assert.match(engine, /audioBeats\(projectId: string, body: Record<string, unknown>\)/, "engine 里没有 audioBeats 这个方法");
assert.match(engine, /beats: number\[\]; bpm: number \| null;/, "返回类型没把 beats/bpm 写清楚");

assert.match(store, /export async function beatMarks\(clipId: string\)/, "store 里没有唯一的 beatMarks");
const beatBody = store.slice(
  store.indexOf("export async function beatMarks"),
  store.indexOf("/** 划动源画面"),
);
assert.ok(beatBody.length > 0, "找不到 beatMarks 的函数体");
assert.equal((beatBody.match(/op: "marker\.set"/g) ?? []).length, 1, "节拍标记在这个函数里只许写一处命令形状");
assert.equal((store.match(/engine\.audioBeats\(/g) ?? []).length, 1, "节拍分析只能从 beatMarks 调用一次");
assert.match(beatBody, /name: `节拍 \$\{index \+ 1\}`/, "节拍标记没有按序号命名");
assert.match(beatBody, /color: "cyan"/, "节拍标记的颜色没定下来");
assert.equal((beatBody.match(/submit\(commands, "按节拍打点"\)/g) ?? []).length, 1, "一次点击必须只提交一个批次");
assert.ok(beatBody.includes("撤销一步全部退回"), "提示里没说撤销这一步会退回什么");
assert.ok(beatBody.includes("剪刀可按这些标记切分"), "提示里没指下一条走得通的手");
assert.ok(!/autocorr|onset|BPM\s*=|60 \/ \(/.test(beatBody), "界面里又长出了一份节拍算术");

assert.match(inspector, /按节拍打点/, "检查器里没有这颗按钮");
assert.match(inspector, /features\?\.beat_detect/, "按钮没按能力表出现（老引擎会被迫说谎）");
assert.match(inspector, /clip\.speed_curve/, "带变速曲线的片段没有按名字说明为什么不能打点");
assert.match(inspector, /beatMarks\(clip\.id\)/, "按钮没有调用那一处唯一实现");
assert.match(help, /检查器·按节拍打点/, "帮助里没写这一格说的是什么");
assert.match(help, /200%/, "帮助没写清速度如何映射到时间线");

console.log(
  "desktop_beats_check: PASS: 一条只读分析路由、一处 beatMarks、一个批次、能力表放行、"
  + "变速曲线点名拒绝，界面不算节拍，帮助写清 200% 的映射",
);
