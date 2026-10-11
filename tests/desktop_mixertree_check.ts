/** 混频台的树：一条支路路径、一处写入口、一份层数与操作数的数法。

 1.124 让一支自己也能是一台混频台。算式一点没多（每通道函数的平均还是每通道函数，一棵树照样塌成
 每通道一张表），新增的只有三件事：① 「正在编辑哪一台」从下标变成一条路径；② 树要有界，而界限由
 引擎下发；③ 每一层的权重与混合方式是各层自己的那份表。风险因此全在「路径与层的对齐」上：走错一层
 就会把上层的旋钮写到下层那台头上，或者把一份长度对不上的表交出去。这里把路径、写入与数法钉在唯一
 的几处，并把界面的 `GradeBranch` 与契约那条 `Union` 对字。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { branchBlend, branchTree, cardsFor, chainFieldsFor, mapMixer, mixerAt, resolveMixerPath } from "../desktop/src/gradeGraph";
import type { GradeBranch, GradeNode, GradeParallel } from "../desktop/src/engine";

const curve = (extra: Record<string, unknown> = {}): GradeNode =>
  ({ kind: "curve", channel: "rgb", points: [{ x: 0, y: 0 }, { x: 1, y: 1 }], enabled: true, mix: 1, blend: "normal", ...extra }) as unknown as GradeNode;
const balance = (temperature = 0.2): GradeNode =>
  ({ kind: "white_balance", temperature, tint: 0, enabled: true, mix: 1, blend: "normal" }) as unknown as GradeNode;
const mixer = (branches: GradeNode[], extra: Record<string, unknown> = {}): GradeParallel =>
  ({ kind: "parallel", branches, enabled: true, mix: 1, blend: "normal", ...extra }) as unknown as GradeParallel;

const leafOnly = mixer([curve(), balance()]);
const nested = mixer([mixer([curve(), balance()], { weights: [2, 1] }), curve()], { weights: [1, 2] });

// 路径：尽头那台才是正在编辑的那台；走不通的路径原样走回去，不猜用户想改谁。
assert.equal(mixerAt(nested, []), nested, "空路径就是链上那台");
assert.deepEqual(mixerAt(nested, [0])?.weights, [2, 1], "走进去读到的是里层那份表");
assert.equal(mixerAt(nested, [1]), null, "叶子不是混频台，进去只能是空");
assert.equal(mixerAt(curve(), []), null, "链上那个节点不是并联时没有台可编辑");
assert.deepEqual(mixerAt(nested, [3]), null, "越界的支号不许编辑别的支");
assert.deepEqual(resolveMixerPath(nested, [0, 0]), [0], "走不通的路径缩到能走的那一层");
assert.deepEqual(resolveMixerPath(leafOnly, [5, 1]), [], "一台没有下层的混频台：路径整体作废");
assert.deepEqual(resolveMixerPath(undefined, [0]), [], "节点被删了也不能崩");

// 该摆谁的控件：`current` 在 1.124 换成了「路径尽头那台混频台」，链上那些节点因此一度整块丢了
// 自己的控件（曲线点、强度、混合方式、换一张表都摸不到）——装机实测抓到的，这里钉住。
const cube = { kind: "lut3d", title: "t", size: 2, cells: [0, 0, 0, 1, 1, 1], enabled: true } as unknown as GradeNode;
const chainCurve = curve();
assert.equal(chainFieldsFor(chainCurve, []), chainCurve, "链上挑中一条曲线就摆它自己的控件");
assert.equal(chainFieldsFor(cube, [])?.kind, "lut3d", "3D 表也要摆出自己那一段（说预览不生效，而不是没有面板）");
assert.equal(chainFieldsFor(nested, []), null, "混频台走自己那块面板，不是节点的控件");
assert.equal(chainFieldsFor(nested, [0]), null, "进到里层时外层节点的控件不许压在下面");
assert.equal(chainFieldsFor(chainCurve, [0]), null, "路径非空就不摆外层控件：这一步本不该发生，发生了也不能画");
assert.equal(chainFieldsFor(undefined, []), null, "节点没了也不崩");

// 写入：只有一处下去，且改的是被点名的那一层——上层那份表一个字都不动。
const edited = mapMixer(nested, [0], (target) => ({ ...target, weights: [1, 1] })) as GradeParallel;
assert.deepEqual(edited.weights, [1, 2], "上层的权重表没被碰到");
assert.deepEqual((edited.branches[0] as GradeParallel).weights, [1, 1], "改的是路径尽头那一台");
assert.deepEqual(mapMixer(nested, [1], (target) => ({ ...target, weights: [3, 3] })), nested, "路径落在叶子上就不写：交回的树与原样等价");
assert.deepEqual(mapMixer(nested, [5], (target) => ({ ...target, weights: [3, 3] })), nested, "支号越界也不写");
assert.deepEqual(mapMixer(nested, [0, 7], (target) => ({ ...target, weights: [3, 3] })), nested, "里层的越界支号同样不写");
const leaf = curve();
assert.equal(mapMixer(leaf, [], (target) => target), leaf, "叶子节点原样交回");
const deeper = mixer([mixer([curve(), curve(), curve()]), curve(), curve()], { weights: [1, 1, 1] });
assert.deepEqual(branchTree(nested), { depth: 2, operations: 5 }, "一层套一层的数法与契约同一个说法");
assert.deepEqual(branchTree(curve()), { depth: 0, operations: 1 }, "叶子是 0 层 1 个操作");
assert.deepEqual(branchTree(deeper), { depth: 2, operations: 7 }, "一台混频台自己也是一个操作（与契约 branch_tree 同一数法）");

// 每一层各用各的表：里层的支数不能拿去问外层的方式，反过来也不行。
assert.equal(branchBlend(nested, 0), "normal", "外层没给表就是正常");
assert.equal(branchBlend(nested, 1), "normal", "外层第二支读外层的表");
const withModes = mixer([mixer([curve(), curve()], { blends: ["screen", "multiply"] }), curve()], { blends: ["difference", "normal"] }) as GradeParallel;
assert.equal(branchBlend(withModes, 0), "difference", "外层那一支按外层自己的方式");
assert.equal(branchBlend(withModes.branches[0] as GradeParallel, 1), "multiply", "里层读里层那份");
const half = mixer([mixer([curve(), curve()], { blends: ["screen"] }), curve()], { blends: ["normal", "normal"] }) as GradeParallel;
assert.equal(branchBlend(half.branches[0] as GradeParallel, 0), "normal", "长度对不上的半份表不许被按位置读");
assert.equal(branchBlend(half, 1), "normal", "外层那份是齐的，正常读");

// 卡片把套上来的那台画成一栏套一栏，不然树上多出来的那一层在界面上是隐形的。
const cards = cardsFor([nested, curve()]);
assert.equal(cards[0].lanes.length, 2, "外层两支");
assert.deepEqual(cards[0].lanes[0].lanes?.map((lane) => lane.label), ["色调曲线", "白平衡"], "里层那两支也要看得见");
assert.match(cards[0].lanes[0].detail, /并联|加权 ×2\/×1/, "套上来的那台得说出自己是什么");
assert.equal(cards[1].lanes.length, 0, "叶子卡片没有栏");
assert.equal(cards[0].lanes[0].enabled, true, "栏的启用状态跟着那一层自己");

const read = (parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `must be readable from the check's working directory: ${parts.join(" or ")}`);
  return readFileSync(found, "utf8");
};

// 接线：一层以下的事全走 `gradeGraph` 那两处，视图不再自己走树。
const fields = read(["desktop/src/views/GradeFields.tsx", "src/views/GradeFields.tsx"]);
assert.match(fields, /const editMixer = \(update: \(mixer: GradeParallel\) => GradeParallel\)/, "写入口只有一处");
assert.equal((fields.match(/editMixer\(/g) ?? []).length, 6, "五处写 + 一处定义：没有第二处 replace");
assert.match(fields, /const walked = resolveMixerPath\(head, path\)/, "路径先被走通再用，界面不自己截");
assert.match(fields, /const current = mixerAt\(head, walked\)/, "正在编辑的那台由路径说，不由下标说");
assert.match(fields, /replace\(active, mapMixer\(head, walked, update\)\)/, "写下去的是整台换掉后的那个节点");
assert.match(fields, /const treesOn = Boolean\(app\.caps\?\.features\?\.grade_mixer_trees\)/, "树的开关听引擎的");
assert.match(fields, /max_mixer_depth \?\? FALLBACK_MIXER_DEPTH/, "层数上限读下发的那个数");
assert.match(fields, /max_tree_operations \?\? FALLBACK_TREE_OPERATIONS/, "操作数上限也读下发的");
assert.match(fields, /aria-label="进入这一支"/, "有一只手真的进得去");
assert.match(fields, /aria-label="回到上一层混频台"/, "也出得来");
assert.match(fields, /aria-label="把这一支变成并联"/, "套一台的手在界面上");
assert.match(fields, /disabled=\{Boolean\(wrapBlock\)\}[\s\S]{0,200}title=\{wrapBlock \|\|/, "按不动时说的是真走得到的出路");
assert.doesNotMatch(fields, /depth[^\n]*[><=]\s*3\b/, "视图不自己写死层数");
assert.match(fields, /<LaneList lanes=\{lane\.lanes\}/, "栏套栏用同一处渲染，不复制一份");
// 「该摆谁的控件」只许有一处判断：视图再自己写一遍 `current.kind !== "parallel"` 就是把链上节点
// 的控件挂在混频台上，1.124 那次丢控件正是这么来的。
assert.match(fields, /chainFieldsFor\(head, walked\)/, "视图用的是那一处判断");
assert.doesNotMatch(fields, /current && current\.kind !== "parallel"/, "不许拿混频台的那个 current 当链上节点");

// 契约与界面的那条支路词汇必须同义：一支要么是每通道操作，要么是另一台混频台。
const contracts = read(["src/agentcut/contracts.py", "../src/agentcut/contracts.py"]);
assert.match(contracts, /GradeBranch = Union\[\s*\n?\s*GradeCurve,[\s\S]*?"GradeParallel",\s*\]/, "契约那条 Union 收得下一台混频台");
assert.match(contracts, /"max_mixer_depth": GRADE_MIXER_DEPTH/, "层数由契约下发");
assert.match(contracts, /"grade_mixer_trees": True/, "开关与字段同批下发");
const engine = read(["desktop/src/engine.ts", "src/engine.ts"]);
assert.match(engine, /export type GradeBranch = GradeLeaf \| GradeParallel;/, "界面那条也是同一个意思");
assert.match(engine, /max_mixer_depth\?: number;/, "界面类型里有这两个下发字段");
assert.match(engine, /max_tree_operations\?: number;/);

console.log("PASS: 混频台的树只有一条路径走法、一处写入口、一份层数数法，层与层的表各是各的");
