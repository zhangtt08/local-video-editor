/**
 * 1.205 的壳层检查：那一层的针在动画曲线编辑器里只有一个主人、一条写路。
 *
 * 为什么单独一档：引擎那一条 `tests/layercurve_check.py` 量的是读路由交回的数等于窗表；
 * 这一档量的是**界面**——它可能自己 walk 一遍窗表、可能把拖到的值写进 `clip.keyframes`
 * （那是片段自己的六个数，层根本读不到）、也可能偷偷用另一条命令写链。三种都只会
 * 在屏幕上看着对、文件里是另一回事。断的都是源文件里那一处实现，不是注释里的一句话。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const editor = read("desktop/src/views/CurveEditor.tsx", "../../desktop/src/views/CurveEditor.tsx");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const contracts = read("src/agentcut/contracts.py", "../../src/agentcut/contracts.py");
const animation = read("src/agentcut/animation.py", "../../src/agentcut/animation.py");

// 1) 名单与量程只听引擎：界面不许自己列「哪几个数能动」，也不许自带上下限。
assert.ok(editor.includes("layerCurveFields(clip, app.caps?.grade_limits?.layer_key_props, app.caps?.grade_limits?.layer_key_bands)"),
  "曲线编辑器那一层的名单不是从 capabilities 来的");
assert.ok(effects.includes("bands: Record<string, [number, number]> | undefined"),
  "层那几行的量程不是引擎下发的那一份");
assert.ok(!/layer_key_(props|bands)\s*\?\?\s*\[[^\]]]/.test(editor), "界面给层的名录或量程写了默认值");
// 名字只有一张表：那一层的每一行都从 LAYER_KEY_LABEL 出去。
assert.ok(effects.includes("LAYER_KEY_LABEL[prop] ?? prop"), "那一行的中文名字不是唯一那张表");
assert.ok(!/label: `第 \$\{layer \+ 1\} 层 · (offset_x|往左右|权重)`/.test(effects), "界面抄了一份第二层的名字");

// 2) 读只有一条路：那一层走新路由，普通曲线走老路由，两边都不自己 walk 窗表。
assert.ok(editor.includes("animationLayerCurve(input, layerField.key, layerField.layer, quantum(project, audio ? \"audio\" : \"video\"))"),
  "那一层的阶梯不是从引擎那条读路由来的（或没把格长交给它）");
assert.ok(editor.includes("animationCurve(input, field.property as Property)"), "普通曲线那条读路被改坏了");
assert.ok(!/curve\.push|steps\(1/.test(editor), "界面自己在拼阶梯");
// 起笔读的是已经算好的那一级，不是第二次插值。
assert.ok(editor.includes("layerStepAt(graph as never"), "播放头那一格的起笔不是读窗表那一级");
assert.ok(effects.includes("export function layerStepAt"), "挑那一级的那处不在 effects.ts（就没有唯一主人）");

// 3) 写只有一处出口：那一层永远是 `clip.grade`，且刻度折回只在一处实现。
assert.ok(editor.includes("const layerWrites = (next: Keyframe[]) => [layerKeyCommand(clip, layerField as LayerCurveField,"),
  "那一层的写入没有汇到一处（四个写点就可能有一个漏）");
for (const op of ["keyframes.move", "keyframe.move", "keyframe.set", "keyframes.remove"]) {
  const sites = editor.split(`op: "${op}"`).length - 1;
  assert.equal(sites, 1, `命令 ${op} 在界面里出现 ${sites} 次（分流没汇到一处）`);
}
assert.ok(effects.includes('return { op: "clip.grade", clip_id: clip.id, grade: next.color?.grade };'),
  "那一层写的不是那一条整链状态写入");
assert.ok(effects.includes("const stamped = keys"), "刻度折回不是在唯一那一处做的");
assert.equal((effects.match(/at_ticks: key\.at_ticks \+ offset/g) ?? []).length, 1, "折回刻度那一处只许有一个主人（1.208 起那份并集也在同一处）");
assert.ok(!/animation_offset_ticks \?\? 0\)\s*;?\s*$/.test(editor.split("\n").filter((line) => line.includes("at_ticks + ")).join("\n")),
  "视图自己在把刻度加回去（那是第二把尺）");

// 4) 这一档的开关与读路由在引擎那一头都在，且五个数各有自己的量程
assert.ok(contracts.includes('"layer_curve": True'), "capabilities 里少了曲线编辑器这一档的开关");
assert.ok(contracts.includes('"layer_key_bands": {'), "契约里没把那份量程交出去");
assert.ok(engine.includes("animationLayerCurve(clip: Clip, property: LayerProperty, layer: number, quantum: number)"),
  "引擎客户端没有那条读路由");
assert.ok(engine.includes("export type LayerProperty = \"offset_x\" | \"offset_y\" | \"scale\" | \"mix\" | \"rotation\";"),
  "界面那份层的属性表与契约不同步（1.198/1.204 各加过一个数，这里必须一起长）");
assert.ok(animation.includes("def layer_graph"), "引擎没有那一条唯一的层阶梯编译");
assert.ok(/^      LAYER_CURVE_TARGET: "这一层的阶梯读不到/m.test(engine),
  "那句拒绝没有一行中文说法（error_vocabulary_check 会把两边对起来）");

// 5) 停用那一层之后不再被数进「第 0 层」：数层只有一处判断
assert.ok(effects.includes('(node) => node.kind === "layer" && node.enabled'),
  "数第几层没按「启用」判断（与 layer_nodes 就不是同一份顺序）");
assert.ok(!editor.includes("clip.color?.grade ?? []), [") && editor.includes("(clip.color?.grade ?? []).filter((node) => node.kind === \"layer\" && node.enabled)"),
  "视图自己数了一遍链里的节点（那是第二处顺序）");

console.log(
  "desktop_layercurve_check: 那一层在曲线编辑器里只有一个主人——名录与量程听 capabilities、" +
  "读只走那条新路由、写只汇到 clip.grade 一处、刻度只折一次、数层只按启用那一份顺序"
);
