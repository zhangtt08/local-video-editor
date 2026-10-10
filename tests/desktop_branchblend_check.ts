/** 分支混合方式：一份位置表、一张名字表、一个开关。

 1.122 让并联节点的每一支先按自己的方式与进来的画面相合，再按权重参与平均。语义上它不换算法（用的还是
 节点级混合那份 `blend_values`），形状上它也不换规矩（`blends` 与 `weights` 同一条「给就给全」）。风险因此
 全在两个地方：形状被在第二处重算（那就总有一处会忘记对齐支数），以及名字在界面里被再抄一份（那就有模式的
 id 引擎不认识）。这个检查把这两处都钉在唯一的来源上，并把 `BLEND_MODES` 与契约里那条 `Literal` 对字。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { BLEND_MODES, type BlendMode, type GradeParallel } from "../desktop/src/engine";
import { blendsAfterAdd, blendsAfterPick, blendsAfterRemove, branchBlend, cardsFor } from "../desktop/src/gradeGraph";

const curve = (extra: Record<string, unknown> = {}) => ({ kind: "curve", channel: "rgb", points: [{ x: 0, y: 0 }, { x: 1, y: 1 }], enabled: true, ...extra });
const graph = (branches: unknown[], blends?: BlendMode[]): GradeParallel =>
  ({ kind: "parallel", branches, enabled: true, mix: 1, blend: "normal", ...(blends ? { blends } : {}) }) as unknown as GradeParallel;

// 没给表就是每支正常；长度不对的表不许半读（那会把第三支的方式安到第二支头上）。
assert.equal(branchBlend(graph([curve(), curve()]), 1), "normal", "an unwritten branch composites normally");
assert.equal(branchBlend(graph([curve(), curve()], ["screen", "multiply"]), 1), "multiply", "an aligned table is read by position");
assert.equal(branchBlend(graph([curve(), curve()], ["screen"]), 0), "normal", "a half table is not read at all");

// 挑一个方式：补齐整份；全是 normal 就整份撤掉——撤掉与交一串 normal 是同一个结果，而撤掉才是 1.122
// 之前那份载荷，回执指纹才能继续把老请求认成同一次。
assert.deepEqual(blendsAfterPick(graph([curve(), curve()]), 1, "screen"), ["normal", "screen"], "the first pick materialises the whole table");
assert.equal(blendsAfterPick(graph([curve(), curve()], ["normal", "screen"]), 1, "normal"), undefined, "back to all-normal withdraws the table");
assert.deepEqual(blendsAfterPick(graph([curve(), curve()], ["difference", "screen"]), 0, "overlay"), ["overlay", "screen"], "a second pick keeps the other slot");

// 加一支补一个 normal，删一支把那一格一起删：留下的表必须仍然覆盖每一支。
assert.equal(blendsAfterAdd(graph([curve(), curve()])), undefined, "no table, still no table");
assert.deepEqual(blendsAfterAdd(graph([curve(), curve()], ["normal", "screen"])), ["normal", "screen", "normal"], "an added branch joins as normal");
assert.deepEqual(blendsAfterRemove(graph([curve(), curve(), curve()], ["screen", "multiply", "normal"]), 1), ["screen", "normal"], "the surviving slots keep their modes");
assert.deepEqual(blendsAfterRemove(graph([curve(), curve()], ["normal", "screen"]), 0), ["screen"], "removing the normal slot still leaves the table");
assert.equal(blendsAfterRemove(graph([curve(), curve()], ["normal", "screen"]), 1), undefined, "with only normal left the table goes");
for (const [blends, slot] of [[["screen", "normal", "multiply"], 1], [["normal", "screen"], 0]] as [BlendMode[], number][]) {
  const before = graph([curve(), curve(), curve()], blends);
  const after = blendsAfterRemove(before, slot);
  assert.ok(after === undefined || after.length === before.branches.length - 1, "a removal never leaves a table longer than the graph");
}

// 卡片把那一个方式念出来（用唯一那张表的名字），没给表时什么都不念。
assert.match(cardsFor([graph([curve(), curve()], ["normal", "screen"])])[0].lanes[1].detail, /滤色/, "the lane says how that branch composites");
assert.doesNotMatch(cardsFor([graph([curve(), curve()], ["normal", "normal"])])[0].lanes[0].detail, /滤色|正常/, "normal is the absence, not a label");

const view = ["desktop/src/views/GradeFields.tsx", "src/views/GradeFields.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(view, "the inspector must be readable from the check's working directory");
const fields = readFileSync(view, "utf8");
assert.match(fields, /const blendsOn = Boolean\(app\.caps\?\.features\?\.grade_branch_blend_modes\)/, "the dropdown waits for the engine to say it composites per branch");
assert.match(fields, /\{blendsOn \? <>/, "and it is behind that gate, not merely labelled by it");
assert.match(fields, /blends: blendsAfterPick\(node, index, mode\)/, "a pick writes through the shared shape decision");
assert.match(fields, /blends: blendsAfterAdd\(node\)/, "adding a branch goes through it too");
assert.match(fields, /blends: blendsAfterRemove\(node, slot\)/, "and so does removing one");
assert.match(fields, /value=\{branchBlend\(current, slot\)\}/, "the select shows that branch's own mode, read from the same place");
assert.match(fields, /disabled=\{!shown\.enabled\} aria-label=\{`第 \$\{slot \+ 1\} 支混合方式`\}/, "a disabled branch greys the dropdown, because its mode genuinely does not apply");
assert.match(fields, /onChange=\{event => setBlend\(current, slot, event\.target\.value as BlendMode\)\}|onChange=\{\(event\) => setBlend\(current, slot, event\.target\.value as BlendMode\)\}/, "and one change is one write");
assert.equal((fields.match(/"multiply"|"screen"|"overlay"|"difference"|"exclusion"/g) ?? []).length, 0, "the inspector must not carry its own copy of the mode names");
assert.equal((fields.match(/>\s*(滤色|正片叠底|叠加|差值|排除|变暗|变亮)\s*</g) ?? []).length, 0, "and no option label is spelled here instead of coming from the shared table");
assert.match(fields, /blendLabel\(branchBlend\(current, index\)\)/, "the branch chip spells the mode through that one table");
assert.match(fields, /BLEND_MODES\.map\(\(\[value, name\]\) => <option key=\{value\} value=\{value\}>\{name\}<\/option>\)/, "the options come from the single table");

// 名字表与契约那条 Literal 必须一字不差地对上，否则界面会交出一个引擎不认的模式。
const contracts = ["src/agentcut/contracts.py", "../src/agentcut/contracts.py"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(contracts, "the contract must be readable from the check's working directory");
const python = readFileSync(contracts, "utf8");
const literal = /BlendMode = Literal\[\s*([^\]]*?)\s*\]/.exec(python.replace(/\r\n/g, "\n"));
assert.ok(literal, "the contract's blend vocabulary must be readable");
const declared = literal[1].split(",").map((entry) => entry.trim().replace(/^"|"$/g, "")).filter(Boolean);
assert.deepEqual(declared, BLEND_MODES.map(([value]) => value), "every mode the engine accepts is offered, and only those");
assert.match(python, /"grade_branch_blend_modes": True/, "the feature flag ships with the field, not after it");
assert.match(python, /blends: Annotated\[list\[BlendMode\], Field\(max_length=GRADE_BRANCH_LIMIT\)\]/, "the table is bounded by the branch limit, like the weights");

console.log("PASS: 分支混合方式只有一份名字表（与契约 Literal 对上）、一条形状判断（gradeGraph），下拉只在下发开关为真时出现");
