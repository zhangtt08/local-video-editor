/** 1.158 那颗「按表换基色」：九个数字只许从引擎那张表搬，那一格只认色彩管理盖过章的一对。

 这一档要挡的是三种会静悄悄发生的错：① 界面自己抄一份系数（抄的那一份迟早和引擎不一样，落在成片里
 只是「颜色有点偏」）；② 把矩阵挂在没有色彩管理的链子上（矩阵乘的是存储值，那样根本不是在换基色）；
 ③ 再点一次叠出第二枚矩阵（换档必须换的是同一格，否则一条链子上两层基色转换，谁也不知道哪一层算）。
 */

import assert from "node:assert/strict";

import { foldBlocker, foldedRow, foldIn, foldWords, usableRows } from "../desktop/src/gamutFold";
import type { GamutMatrixPreset, GradeNode } from "../desktop/src/engine";

const rows: GamutMatrixPreset[] = [
  {
    id: "row_a", label: "甲档（广色收到电视）", source: "rec2020", target: "rec709",
    source_transfer: "rec709", target_transfer: "rec709",
    coefficients: [0.9, 0.05, 0.05, 0.04, 0.92, 0.04, 0.02, 0.03, 0.95],
  },
  {
    id: "row_b", label: "乙档（电视扩到 UHD）", source: "rec709", target: "rec2020",
    source_transfer: "rec709", target_transfer: "rec709",
    coefficients: [0.62, 0.21, 0.17, 0.2, 0.7, 0.1, 0.05, 0.3, 0.65],
  },
];

const head = (input: string): GradeNode => ({
  kind: "transfer", input_space: input as never, output_space: "linear",
  enabled: true, purpose: "color_manage",
});
const tail = (output: string): GradeNode => ({
  kind: "transfer", input_space: "linear", output_space: output as never,
  enabled: true, purpose: "color_manage",
});
const wrap = (inside: GradeNode[]): GradeNode[] => [head("srgb"), ...inside, tail("rec709")];
const curve = (): GradeNode => ({ kind: "levels", channel: "rgb", black: 0, white: 1, gamma: 1, enabled: true });
const handMatrix = (): GradeNode => ({
  kind: "matrix", coefficients: [1, 0, 0, 0, 1, 0, 0, 0, 1], enabled: true,
});

/** 联合类型上要拿矩阵的字段，先在这儿把形状收窄一次：断言 `kind` 之后再读，读不通就红。 */
function coefficientsAt(nodes: GradeNode[], index: number): number[] {
  const node = nodes[index];
  assert.equal(node.kind, "matrix", `第 ${index + 1} 枚应当是通道混合，实际是 ${node.kind}`);
  return node.kind === "matrix" ? node.coefficients : [];
}
function mixAt(nodes: GradeNode[], index: number): number | undefined {
  const node = nodes[index];
  return node.kind === "matrix" ? node.mix : undefined;
}

// ① 没套色彩管理：这一格不存在，理由必须指着「套上色彩管理」那条真有的出路。
const bare: GradeNode[] = [curve()];
assert.ok(foldBlocker(bare, rows, 8)?.includes("套上色彩管理"), `出路要点名那颗真实的按钮：${foldBlocker(bare, rows, 8)}`);
assert.equal(foldIn(bare, rows[0], rows), null, "不许把矩阵硬挂在没管理的链子上");

// 只有半对（一个盖章节点）时不许当成「齐了」：那是 1.130 立过的认人规矩。
const half: GradeNode[] = [head("srgb"), curve()];
assert.ok(foldBlocker(half, rows, 8)?.includes("取下"), `半对要念出「先取下再套上」：${foldBlocker(half, rows, 8)}`);

// ② 那一格是空的：插在「进线性」之后，写进去的就是表里那九个数字，一个都不改。
const empty = wrap([]);
const foldedOnce = foldIn(empty, rows[0], rows);
assert.ok(foldedOnce, "套了一对就该折得进去");
assert.equal(foldedOnce.length, empty.length + 1, "空的那一格是插一枚，不是替换");
assert.equal(foldedOnce[1].kind, "matrix");
assert.deepEqual(coefficientsAt(foldedOnce, 1), rows[0].coefficients, "九个数字照表搬，界面不重算");
assert.equal(foldedOnce[1].enabled, true);
assert.ok(mixAt(foldedOnce, 1) === undefined, "强度这一格不写：mix 由人自己调，界面不替你定");

// ③ 再点一次同一档：换的是同一格，链子不涨。
const again = foldIn(foldedOnce, rows[0], rows);
assert.equal(again.length, foldedOnce.length, "同一档再折一次不许叠第二枚");
assert.deepEqual(coefficientsAt(again, 1), rows[0].coefficients);
// 换成另一档也是同一格：只拿这一档去比会把「换档」误判成「手工填的数」而拒掉。
const swapped = foldIn(again, rows[1], rows);
assert.ok(swapped, "从甲档换成乙档是换档，不是往格子里塞第二枚");
assert.equal(swapped.length, again.length, "换档不涨节点数");
assert.deepEqual(coefficientsAt(swapped, 1), rows[1].coefficients);
assert.equal(foldedRow(swapped, rows)?.id, "row_b");

// 折过之后再说得出「已按哪一档折过」：这一句读的就是那一格里的实际数字。
assert.equal(foldedRow(foldedOnce, rows)?.id, "row_a");
const sentence = foldWords(foldedRow(foldedOnce, rows));
assert.ok(sentence.includes(rows[0].label), `状态要念引擎给的那档名字：${sentence}`);
assert.ok(!foldWords(null).includes("已经"), "没折过就不许说「已经」");

// 那一格里已经是手工填的数：不覆盖，并指着「自己改或先删掉」这条出路。
const withHand = wrap([handMatrix()]);
assert.ok(foldBlocker(withHand, rows, 8)?.includes("手工"), `手工填的数要说清是谁写的：${foldBlocker(withHand, rows, 8)}`);
assert.ok(foldBlocker(withHand, rows, 8)?.includes("九宫格"), `出路要点名那张能改数的表：${foldBlocker(withHand, rows, 8)}`);
assert.equal(foldIn(withHand, rows[0], rows), null, "界面不覆盖人手工写的九个数");

// 两枚以上：说不清换哪一枚就一枚都不动，并把数报出来。
const twoInside = wrap([handMatrix(), { ...handMatrix(), coefficients: [0.5, 0.2, 0.3, 0.3, 0.5, 0.2, 0.2, 0.3, 0.5] }]);
assert.ok(foldBlocker(twoInside, rows, 8)?.includes("2 枚"), `要报出真实枚数：${foldBlocker(twoInside, rows, 8)}`);

// 链子满了：插入被挡，但**换掉已有那一枚**仍然放行——只挡会长大的那一种。
const full = wrap([foldedOnce[1]]);
const padded: GradeNode[] = [...Array.from({ length: 6 }, () => curve()), tail("rec709")];
padded.unshift(head("srgb"));
assert.equal(padded.length, 8, "这份夹具正好占满每链 8 个的位置");
assert.ok(foldBlocker(padded, rows, 8)?.includes("节点"), `满了要说是节点满了：${foldBlocker(padded, rows, 8)}`);
assert.equal(foldBlocker(full, rows, 8), null, "已经折过的格子换成另一档，不占新位置，不该被上限挡住");

// 表里那一档的系数残缺（半行）：那一档就不许出现在可点的名单里。
const brokenRows = [...rows, { ...rows[0], coefficients: [1, 2, 3] }];
assert.equal(usableRows(brokenRows).length, 2, "凑不满九个数的行不是一张矩阵，宁可不显示");
assert.equal(usableRows(undefined).length, 0, "老引擎不回这张表时，名单是空的");

// 引擎没下发这张表：不许自己编系数，出路指向那条手工填数的路。
const noTable = foldBlocker(empty, [], 8);
assert.ok(noTable?.includes("gamut_matrices"), `要点名引擎那个字段：${noTable}`);
assert.ok(noTable?.includes("+通道混合"), `要给一条此刻真走得通的路：${noTable}`);

console.log(
  "PASS: 基色折叠只搬引擎的九个数——没套色彩管理就没有那一格并点名「套上色彩管理」，再点一次换的是同一枚"
    + "而不是叠第二枚，手工填的数不覆盖且出路点名「九宫格」，半行不进名单，满了只挡会涨的那一种",
);
