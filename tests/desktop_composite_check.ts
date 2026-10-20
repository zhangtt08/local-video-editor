/** 1.144「叠一层原图」在界面这一侧：一条读两幅画的边，卡片必须说清它是什么、预览不给它画数。

 这条边不是每通道函数，所以两端的算法不一样：导出用 FFmpeg 的 `split` + 两段 `blend`，
 浏览器画不出第二条画面输入。预设表把它交给界面时带的是 `preview:false`——引擎已经在
 `preview_grade` 里整条丢掉这一级，界面就必须把这句说出来，而不是画一张没有数字的原语。
 */

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = REPO_ROOT;
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
// 1.193：这一级现在监视器会画（图像那一段）。卡片那三句断言在下面的 `opBody` 段里——
// 那里才有函数体的切片（旧的那句「卡片明写预览不生效」在这里不再成立，也不再是判据）。

// 引擎那两头：预览整条丢掉这一级；拒绝的句子必须点名走得通的出路。
assert.match(grade, /if stage\["type"\] == "composite":/, "grade-recognises-the-edge");
assert.match(grade, /"composite", "mode": node\.mode, "mix": node\.mix/, "stage-carries-both-knobs");
const renderSrc = readFileSync(SRC + "src/agentcut/render.py", "utf8");
// 1.145：这条边接进了分层那条 Builder，两路共用同一句话。这里钉的是**图真的把 matte 盖回去**
// （`alphamerge` 在分层那条分支里），以及那句拒话与其代号一起退场——留着比没有更坏。
assert.match(renderSrc, /alphamerge\{merged\}/, "layered-path-restores-the-matte");
assert.doesNotMatch(renderSrc, /COMPOSITE_NEEDS_CUT/, "refusal-retired-in-engine");
assert.doesNotMatch(engineSrc, /COMPOSITE_NEEDS_CUT/, "refusal-retired-in-hint-table");
const hints = ["COMPOSITE_LIMIT"].map((code) => {

  const found = engineSrc.match(new RegExp("^\\s{6}" + code + ": \"([^\"]*)\",\\s*$", "m"));
  assert.ok(found, `hint-${code}`);
  return found[1] as string;
});
for (const said of hints) {
  assert.match(said, /另一条/, "hint-names-the-track-exit");
  assert.match(said, /混合方式/, "hint-names-the-blend-exit");
}
// 1.144 的装机教训：那两个控件写在 `MixFields` 里就等于屏幕上没有它们——`MixFields` 只挂在
// 并联节点与它的支上，串行节点走的是 `OpFields`。所以这里断的是**它在哪个函数里**。
const opBody = fields.slice(fields.indexOf("function OpFields"), fields.indexOf("function MixFields"));
assert.match(opBody, /if \(node\.kind === "composite"\)/, "reachable-in-chain-editor");
assert.match(opBody, /aria-label="叠一层原图的混合方式"/, "chain-editor-carries-the-mode");
assert.match(opBody, /这一层的权重/, "chain-editor-carries-the-weight");
// 卡片那一段（1.193 改了口径）：必须说清「图像这一段监视器会画」与「视频那一段还不画」，
// 而且这条边的卡片里不许再留着那条一刀切的「预览不生效、导出生效」——那份字面量现在只属于
// 3D LUT 那一档（上面第 26 行那条旧断言就是因此换掉的，不是放宽：新断言问的是两件具体的事）。
const compositeCard = opBody.slice(opBody.indexOf('if (node.kind === "composite")'));
assert.match(compositeCard, /监视器现在会画/, "card-says-the-monitor-paints-it");
assert.match(compositeCard, /视频素材那一段暂停与逐帧时会画/, "card-names-when-video-paints");
assert.match(compositeCard, /播放中这一级不画/, "card-names-the-video-cost-it-refuses");
assert.doesNotMatch(compositeCard, /预览不生效、导出生效/, "card-still-carries-the-old-blanket-claim");
assert.doesNotMatch(
  fields.slice(fields.indexOf("function MixFields")),
  /if \(node\.kind === "composite"\)/,
  "dead-branch-left-in-mixfields",
);
// 一支里放不进这条边：`GradeBranch` 那张类型表就是唯一的口径（界面与引擎都不许自备第二份）。
const branchHead = contracts.indexOf("GradeBranch = Union[");
assert.ok(branchHead >= 0, "contract-names-the-branch-union");
assert.doesNotMatch(
  contracts.slice(branchHead, contracts.indexOf("class GradeParallel", branchHead)),
  /GradeComposite/,
  "composite-is-not-a-branch",
);
assert.doesNotMatch(engineSrc, /COMPOSITE_NOT_IN_BRANCH/, "no-refusal-for-a-shape-types-reject");
assert.doesNotMatch(engineSrc, /这个工程是多条画面轨合成的/, "no-blanket-multi-track-lie");


console.log(
  "PASS: 「叠一层原图」在界面里认得（名字、按钮、卡片、方式与权重都在）、卡片不再一刀切地说预览不生效，" +
    "引擎的两句拒绝都点名走得通的出路（另一条轨道的混合方式／嵌套合成）",
);
