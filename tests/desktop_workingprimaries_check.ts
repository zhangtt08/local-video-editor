/** 1.159 工程基色的显示端：名单只认引擎下发的那一份，默认档不许声称折了，默认值只许写在一处。
 *
 * 这一档要挡的是三种静悄悄发生的错：① 界面抄一份可选名单（引擎拒收的名字仍摆在下拉菜单里，用户点了
 * 就吃 422，而那句 422 只在引擎侧红）；② 把「工程按 Rec.709 解释」那一档的话术写成也会折叠（默认档
 * 与旧版逐字节相同这条承诺就假了）；③ 在视图里各写一份 `"rec709"` 兜底（哪天引擎把默认改了，视图那份
 * 还留着，界面显示的档位与引擎实际用的档位分家）。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { feColorMatrixValues } from "../desktop/src/engine";
import {
  DISPLAY_PRIMARIES,
  foldsForDisplay,
  workingChoices,
  workingWords,
} from "../desktop/src/workingSpace";

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;

const module = readFileSync(REPO_ROOT + "desktop/src/workingSpace.ts", "utf8");
const view = readFileSync(REPO_ROOT + "desktop/src/views/Inspector.tsx", "utf8");
const store = readFileSync(REPO_ROOT + "desktop/src/store.ts", "utf8");

// 监视器那一端不跟引擎商量：浏览器画布就是 sRGB。
assert.equal(DISPLAY_PRIMARIES, "rec709", "显示端那一档写死了要改这里，别让引擎替监视器决定");

// 默认档不折，其余档折——「rec709 工程与 1.159 之前逐字节相同」这句全靠这一条。
assert.equal(foldsForDisplay(undefined), false, "老工程没有这一档，就按默认档走");
assert.equal(foldsForDisplay("rec709"), false, "与监视器同档还折，凭空多一层矩阵");
for (const wide of ["p3-d65", "rec2020", "rec601"]) {
  assert.equal(foldsForDisplay(wide), true, `${wide} 比监视器宽，预览必须折`);
}

// 名单来自引擎：没下发就是空的，认不得的名字照原样念，不替引擎添一档。
assert.deepEqual(workingChoices(undefined), [], "老引擎不回这张表时不许凭空列出可选项");
assert.deepEqual(workingChoices([]), [], "空名单就是空的");
const only = workingChoices(["rec709"]);
assert.equal(only.length, 1, "界面不许把中文名表里的档位当成可选名单");
assert.equal(only[0].value, "rec709");
const fresh = workingChoices(["rec709", "sstv-1"]);
assert.equal(fresh.length, 2, "引擎新认得的档位要能出现，不然用户被界面挡住");
assert.ok(fresh[1].label.includes("sstv-1"), `认不得的名字要照原样念：${fresh[1].label}`);
assert.ok(fresh[1].label.includes("还没有中文名"), `要说清这是界面没跟上：${fresh[1].label}`);
for (const choice of fresh) {
  assert.ok(["rec709", "sstv-1"].includes(choice.value), "可选项只能是引擎下发的那些");
}

// 三句话各自守住各自的事实。
const plain = workingWords("rec709", ["rec709", "p3-d65"]);
assert.ok(plain.includes("逐字节相同"), `默认档要说清与旧版一致：${plain}`);
assert.ok(!plain.includes("九个系数"), `默认档不许声称折了一级：${plain}`);
const wide = workingWords("p3-d65", ["rec709", "p3-d65"]);
assert.ok(wide.includes("primaries_matrix"), `那九个数要说是引擎算的：${wide}`);
assert.ok(wide.includes("线性光"), `要说清折的是「抬进线性光—乘—落回」那三趟，不是一个矩阵：${wide}`);
assert.ok(wide.includes("立方体"), `要说清这与导出那张立方体同一条形状：${wide}`);
assert.ok(wide.includes("交付"), `导出折到哪一档要说清由谁决定：${wide}`);
assert.ok(wide.includes("每一段自己的色彩管理"), `不许把素材那一档的判断揽过来：${wide}`);
const stale = workingWords("display-p3", ["rec709", "p3-d65"]);
assert.ok(stale.includes("改不进去"), `名单里没有就要说这一档改不进去：${stale}`);
assert.ok(stale.includes("拒收"), `要说清引擎会拒收：${stale}`);
assert.ok(stale.includes("working_primaries"), `要点名那张表：${stale}`);
assert.ok(stale.includes("出路"), `拒绝必须给一条此刻真走得通的路：${stale}`);
// 引擎整个没下发这张表：这一档既不存在也折不动，说的必须还是默认档那句。
const noTable = workingWords("rec709", undefined);
assert.ok(noTable.includes("逐字节相同"), `老引擎也要说清按默认档走：${noTable}`);
assert.ok(!noTable.includes("九个系数"), `没有那张表就不许声称折了一级：${noTable}`);
assert.ok(noTable.includes("出路"), `这条路走不通时要点名走得通的那条：${noTable}`);
assert.equal(workingWords(undefined, undefined).includes("逐字节相同"), true, "双缺省时也是默认档的话");

// 兜底值只许写在 workingSpace 一处：视图与 store 都读那个常量。
assert.ok(
  module.includes(`export const DISPLAY_PRIMARIES = "${DISPLAY_PRIMARIES}"`),
  "默认档必须由那个常量声明，界面各处才谈得上「只读它」",
);
const viewBlock = view.slice(view.indexOf("ps-working"), view.indexOf("</div>", view.indexOf("ps-working")));
assert.ok(viewBlock.length > 0, "那一格要在工程面板里");
assert.ok(!viewBlock.includes('?? "rec709"'), `视图不许自己抄默认值：${viewBlock.slice(0, 200)}`);
assert.ok(viewBlock.includes("DISPLAY_PRIMARIES"), "视图读的是那个常量");
assert.ok(viewBlock.includes("workingChoices(app.caps?.working_primaries)"), "下拉菜单读的是能力表");
const setterBlock = store.slice(store.indexOf("setWorkingPrimaries"), store.indexOf("\n}", store.indexOf("setWorkingPrimaries")));
assert.ok(!setterBlock.includes('?? "rec709"'), `store 不许自己抄默认值：${setterBlock}`);
assert.ok(setterBlock.includes("DISPLAY_PRIMARIES"), "store 读的也是那个常量");
assert.ok(!/coefficients:\s*\[\s*-?\d/.test(module), "显示端不抄九个数");
assert.ok(!module.includes("primaries_matrix("), "折叠不在界面里算");

// 引擎新加的那一级必须在屏幕上画得出来：20 个数就是那九个数摆进 RGB 三行，alpha 原样带走。
const preview = readFileSync(REPO_ROOT + "desktop/src/views/Preview.tsx", "utf8");
assert.ok(
  preview.includes("feColorMatrixValues(stage.m)"),
  "预览只画 lut 的话，宽档那一级折叠就成了引擎说了、屏幕不画",
);
const nine = [1.2249, -0.2249, 0, 0.0332, 0.9668, 0, 0.0171, 0.0724, 0.9105];
const twenty = feColorMatrixValues(nine);
assert.equal(twenty.length, 20, "feColorMatrix 那一格是 20 个数");
assert.deepEqual(twenty.slice(15), [0, 0, 0, 1, 0], "alpha 必须原样通过——折叠不动透明通道");
const paint = (v: number): number[] => {
  const out: number[] = [];
  for (let row = 0; row < 3; row += 1) {
    out.push(
      twenty[row * 5] * v + twenty[row * 5 + 1] * v + twenty[row * 5 + 2] * v + twenty[row * 5 + 3] * v,
    );
  }
  return out.map((value) => Math.round(value * 1e9) / 1e9);
};
assert.deepEqual(paint(0.5), [0.5, 0.5, 0.5], "每行和为 1 的矩阵乘不动中性轴");

console.log(
  `PASS: 工程基色的可选名单只来自 capabilities.working_primaries（没下发就是空的，认不得的照原样念）；`
    + `${DISPLAY_PRIMARIES} 这一档预览一个字都不折、其余档必须折；三句话各自说清各自的范围；`
    + "默认值只写在 workingSpace 一处，视图与 store 都读它，界面既不算九个数也不写 primaries_matrix",
);
