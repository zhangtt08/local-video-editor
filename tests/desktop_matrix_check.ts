/** 浏览器这一侧只多做一步：把九个数的 3x3 摆成 feColorMatrix 要的 20 个数。
 *
 * 摆错一位，红通道的系数就会去参与绿色的输出，而导出端（FFmpeg 的 colorchannelmixer）读的是同一个
 * 3x3 —— 这一步没有对齐，两端就会各自显示一张不同的画，而且没人会报错。这里逐位钉住布局：三行三列
 * 行主序、每行补两个 0（没有常量偏移）、最后一行是 alpha 原样通过。
 */

import assert from "node:assert/strict";

import { feColorMatrixValues } from "../desktop/src/engine";

const layout = feColorMatrixValues([1, 2, 3, 4, 5, 6, 7, 8, 9]);
assert.equal(layout.length, 20, "feColorMatrix wants exactly twenty numbers");
assert.deepEqual(layout, [1, 2, 3, 0, 0, 4, 5, 6, 0, 0, 7, 8, 9, 0, 0, 0, 0, 0, 1, 0]);

// 恒等矩阵必须摆成 SVG 的默认行为：输出等于输入，alpha 不动。
assert.deepEqual(feColorMatrixValues([1, 0, 0, 0, 1, 0, 0, 0, 1]), [
  1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0,
]);

// 灰度 BT.709：三行相同，每行和为 1 —— 白像素进去还是白，这是通道混合最容易写错的一格。
const grey = [0.2126, 0.7152, 0.0722];
const mixed = feColorMatrixValues([...grey, ...grey, ...grey]);
assert.deepEqual(mixed.slice(0, 3), grey);
assert.deepEqual(mixed.slice(5, 8), grey);
assert.deepEqual(mixed.slice(10, 13), grey);
for (const row of [0, 5, 10]) assert.equal(mixed.slice(row, row + 3).reduce((a, b) => a + b, 0), 1);

console.log("desktop_matrix_check: the 3x3 lands in the twenty-slot feColorMatrix layout");
