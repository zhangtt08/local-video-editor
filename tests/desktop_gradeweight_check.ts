/** 并联节点的混频台：权重表「给就给全」这一条形状，只有 gradeGraph 一处主人。

 1.120 给并联节点一份按位置覆盖每一支的权重。契约不收长度对不上的表——因为那是一份两端算不出同一个
 结果的载荷。所以界面这边每一次改支数、每一次拧旋钮都必须把表补齐或整份撤掉；这类判断埋在组件里就
 没有纯函数可单测，下一个改它的人不会得到红灯（1.117 已经为此把曲线的拖拽算术搬出来过一次）。

 断的是形状与来源：没给表就是均分、表长度不对时不许半读、回到全 1 要把整份表撤掉（撤掉就是 1.120
 之前那份载荷）、加一支补一个 1、删一支把那一格一起删掉；界面那个上限是从 `capabilities.grade_limits`
 下来的，而契约里那个上限与字段约束用的是同一个常量——这两条都在下面钉住。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { branchWeight, cardsFor, weightsAfterAdd, weightsAfterRemove, weightsAfterWeight } from "../desktop/src/gradeGraph";
import type { GradeParallel } from "../desktop/src/engine";

const curve = (extra: Record<string, unknown> = {}) => ({ kind: "curve", channel: "rgb", points: [{ x: 0, y: 0 }, { x: 1, y: 1 }], enabled: true, ...extra });
const node = (branches: unknown[], weights?: number[]): GradeParallel =>
  ({ kind: "parallel", branches, enabled: true, mix: 1, blend: "normal", ...(weights ? { weights } : {}) }) as unknown as GradeParallel;

// 没给表就是均分；给了一份长度不对的表也不许半读——那会把第 3 支的权重当成第 2 支的。
assert.equal(branchWeight(node([curve(), curve()]), 1), 1, "an unweighted graph is the mean");
assert.equal(branchWeight(node([curve(), curve()], [2, 1, 1]), 1), 1, "a misaligned table is not read at all");
assert.equal(branchWeight(node([curve(), curve()], [2, 0.5]), 1), 0.5, "an aligned table is read positionally");
assert.equal(branchWeight(node([curve(), curve()], [2, 0.5]), 0), 2);

// 拧一支：补齐整份；全部回到 1 就整份撤掉——撤掉与交一串 1 是同一个均分，而前者正是老工程那份载荷。
assert.deepEqual(weightsAfterWeight(node([curve(), curve()]), 0, 2), [2, 1], "the first knob move materialises the whole table");
assert.equal(weightsAfterWeight(node([curve(), curve()], [2, 1]), 0, 1), undefined, "back to all-one withdraws the table");
assert.deepEqual(weightsAfterWeight(node([curve(), curve()], [2, 0.5]), 1, 0.4), [2, 0.4], "a second move keeps the other slot");

// 加一支补一个 1，删一支把那一格一起删：留下的表必须仍然覆盖每一支，否则契约会把这一次写入整笔拒掉。
assert.equal(weightsAfterAdd(node([curve(), curve()])), undefined, "no table, still no table after a branch is added");
assert.deepEqual(weightsAfterAdd(node([curve(), curve()], [2, 1])), [2, 1, 1], "an added branch joins at 1");
assert.equal(weightsAfterRemove(node([curve(), curve(), curve()], [2, 1, 1]), 0), undefined, "removing the one weighted slot leaves plain branches, so the table goes");
assert.equal(weightsAfterRemove(node([curve(), curve()], [2, 1]), 0), undefined, "leaving only all-one slots withdraws the table");
assert.deepEqual(weightsAfterRemove(node([curve(), curve(), curve()], [2, 1, 3]), 1), [2, 3], "the surviving slots keep their positions");
for (const [weights, slot] of [[[2, 1, 3], 1], [[2, 1], 0], [[2, 1, 3], 2]] as [number[], number][]) {
  const before = node([curve(), curve(), curve()], weights);
  const after = weightsAfterRemove(before, slot);
  const branches = before.branches.length - 1;
  assert.ok(after === undefined || after.length === branches, `删掉第 ${slot} 支之后表还剩 ${after?.length} 格，而支数是 ${branches}`);
}

const view = ["desktop/src/views/GradeFields.tsx", "src/views/GradeFields.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(view, "the inspector must be readable from the check's working directory");
const fields = readFileSync(view, "utf8");
// 旋钮的上限是引擎下发的那个数，界面不自己数一遍；这一处也确实是那条字段在用。
assert.match(fields, /weightMax: app\.caps\?\.grade_limits\?\.branch_weight_max \?\? FALLBACK_WEIGHT/, "the ceiling comes from capabilities.grade_limits, with the house fallback");
assert.match(fields, /min=\{0\} max=\{limits\.weightMax\} step=\{0\.05\}/, "the knob is clamped by the downlinked ceiling");
// 只有引擎说这一版有混频台，才摆出这一排旋钮。
assert.match(fields, /const weightsOn = Boolean\(app\.caps\?\.features\?\.grade_branch_weights\)/, "the control waits for the engine to say it honours weights");
assert.match(fields, /\{weightsOn \? <>/, "and it is behind that gate, not merely labelled by it");
// 写出去的是那一处形状判断的结果，而不是组件自己拼的一份。
assert.match(fields, /weights: weightsAfterWeight\(mixer, index, value\)/, "a knob move submits the shared shape decision");
assert.match(fields, /weights: weightsAfterAdd\(mixer\)/, "adding a branch goes through it too");
assert.match(fields, /weights: weightsAfterRemove\(mixer, slot\)/, "and so does removing one");
assert.equal((fields.match(/weights: /g) ?? []).length, 3, "exactly three places may write that table, all of them the shared decision");
// 卡片报出「加权」，均分时不报——一张都不存在的表不该被念出来。
assert.match(cardsFor([node([curve(), curve()], [2, 1])])[0].detail, /加权 ×2\/×1/, "the card says the mixer is off the mean");
assert.doesNotMatch(cardsFor([node([curve(), curve()])])[0].detail, /加权/, "and says nothing when there is no table");

// 契约里那个上限与字段约束用的是同一个常量，并且就是下发的那一个——不然界面放行、引擎拒绝。
const contracts = ["src/agentcut/contracts.py", "../src/agentcut/contracts.py"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(contracts, "the contract must be readable from the check's working directory");
const python = readFileSync(contracts, "utf8");
assert.match(python, /GradeBranchWeight = Annotated\[float, Field\(ge=0, le=GRADE_BRANCH_WEIGHT_MAX\)\]/, "the field's bound is the published constant");
assert.match(python, /"branch_weight_max": GRADE_BRANCH_WEIGHT_MAX/, "and the downlinked ceiling is that same constant");
assert.match(python, /"grade_branch_weights": True/, "the feature flag ships with the field, not after it");

console.log("PASS: 权重表的形状只有 gradeGraph 一处主人——补齐、撤表、加支补一、删支同删，界面用下发的上限，契约用同一个常量");
