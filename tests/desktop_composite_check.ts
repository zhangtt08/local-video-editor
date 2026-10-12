/** 1.144「叠一层原图」在界面这一侧：一条读两幅画的边，卡片必须说清它是什么、预览不给它画数。

 这条边不是每通道函数，所以两端的算法不一样：导出用 FFmpeg 的 `split` + 两段 `blend`，
 浏览器画不出第二条画面输入。预设表把它交给界面时带的是 `preview:false`——引擎已经在
 `preview_grade` 里整条丢掉这一级，界面就必须把这句说出来，而不是画一张没有数字的原语。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = "C:/Users/Administrator/Desktop/项目/agentcut/";
const engineSrc = readFileSync(SRC + "desktop/src/engine.ts", "utf8");
const graph = readFileSync(SRC + "desktop/src/gradeGraph.ts", "utf8");
const fields = readFileSync(SRC + "desktop/src/views/GradeFields.tsx", "utf8");
const contracts = readFileSync(SRC + "src/agentcut/contracts.py", "utf8");
const grade = readFileSync(SRC + "src/agentcut/grade.py", "utf8");

// 契约里有这一级、引擎下发这一条边，界面就必须有名字、有按钮、有卡片——少一处都是「Agent 能写、人看不见」。
assert.match(contracts, /kind: Literal\["composite"\] = "composite"/, "contract-carries-the-edge");
assert.match(engineSrc, /kind: "composite"; mode: BlendMode; mix: number; enabled: boolean/, "shell-types-the-edge");
assert.match(graph, /composite: "叠一层原图",/, "graph-names-the-edge");
assert.match(fields, /"parallel", "composite"/, "button-offers-the-edge");
assert.match(fields, /aria-label="叠一层原图的混合方式"/, "card-lets-you-pick-the-mode");
assert.ok(fields.includes("预览不生效、导出生效"), "card-says-preview-does-not-apply");

// 引擎那两头：预览整条丢掉这一级；拒绝的句子必须点名走得通的出路。
assert.match(grade, /if stage\["type"\] == "composite":/, "grade-recognises-the-edge");
assert.match(grade, /"composite", "mode": node\.mode, "mix": node\.mix/, "stage-carries-both-knobs");
const hints = ["COMPOSITE_NEEDS_CUT", "COMPOSITE_LIMIT"].map((code) => {
  const found = engineSrc.match(new RegExp("^\\s{6}" + code + ": \"([^\"]*)\",\\s*$", "m"));
  assert.ok(found, `hint-${code}`);
  return found[1] as string;
});
for (const said of hints) {
  assert.match(said, /另一条/, "hint-names-the-track-exit");
  assert.match(said, /混合方式/, "hint-names-the-blend-exit");
}

console.log(
  "PASS: 「叠一层原图」在界面里认得（名字、按钮、卡片、方式与权重都在）、卡片明写预览不生效导出生效，" +
    "引擎的两句拒绝都点名走得通的出路（另一条轨道的混合方式／嵌套合成）",
);
