/** 1.99：曲线编辑器里那条柔焦曲线的上限，必须与检查器那一行读到的是同一个数。
 *
 * 柔焦在 1.98 起能打关键帧，但当时只能在检查器按 ◇ 一个点一个点地记，看不见曲线的形状。
 * 这一版把它送进曲线编辑器。风险不在「多一个选项」，在「两处各算一次能拉到多高」：
 * 检查器按 `capabilities.limits.blur_fraction` 与实测过的像素带按画幅高折算取小，
 * 曲线编辑器如果自己写一个 25%，画得出、导出会拒（1.82 之后这条规矩一直是门禁的对象）。
 */

import assert from "node:assert/strict";

import { EFFECT_FIELDS, FIELD_LABEL, MASK_ANIM_FIELDS, blurMaxPercent, curveBase, spatialAnimFields } from "../desktop/src/effects";
import { DEFAULT_EFFECTS, DEFAULT_MASK, type Capabilities } from "../desktop/src/engine";

const caps = (extra: Record<string, unknown> = {}) =>
  ({ features: { clip_blur: true, blur_keyframes: true, ...extra }, limits: { blur_fraction: 0.25, blur_radius_limit_px: 64 } }) as Capabilities;

// 老引擎不回 blur_keyframes：这条曲线根本不该出现在列表里。注意这一条必须带着「模糊本身可用」的
// 两个上限来问——否则它只是被 max<=0 顺手挡掉的，测不到 blur_keyframes 这个开关（突变验证抓出来的洞）。
assert.deepEqual(spatialAnimFields(null, 1080), [], "caps 还没回来时不许有这条");
assert.deepEqual(spatialAnimFields({ features: { clip_blur: true }, limits: { blur_fraction: 0.25, blur_radius_limit_px: 64 } } as Capabilities, 1080), [], "1.98 之前的引擎没有这条曲线，画一条就是给它一个它不实现的旋钮");
// 没有可推的距离（旧引擎不下发两个上限）也不给：给了就是画得出、导出会拒的一条曲线。
assert.deepEqual(spatialAnimFields({ features: { blur_keyframes: true }, limits: {} } as Capabilities, 1080), []);
assert.deepEqual(spatialAnimFields(caps(), 0), [], "画幅高未知就没有这条");

// 有：只有一条，读数与检查器那一行同源。
const one = spatialAnimFields(caps(), 1080);
assert.equal(one.length, 1, "柔焦该只有一条曲线");
assert.equal(one[0].property, "blur");
assert.equal(one[0].label, "柔焦");
assert.equal(FIELD_LABEL.blur, "柔焦", "关键帧列表与时间线的那颗 ◆ 认得这个属性");
// 1080 高时实测带 64 px 折成 5.925%，比 25% 更紧——取的是小那个。
assert.equal(one[0].max, blurMaxPercent(caps(), 1080));
assert.ok(one[0].max < 25 && one[0].max > 5.9 && one[0].max < 5.93, `上限算错了：${one[0].max}`);
// 小画幅反过来：25% 才是那个更紧的数。
const small = spatialAnimFields(caps(), 120);
assert.equal(small[0].max, 25);
assert.equal(small[0].max, blurMaxPercent(caps(), 120));
// 值域换算是百分数：曲线上的高度 × factor 就是检查器里那个数，两处不许各写一套。
assert.equal(small[0].factor, 100);
assert.equal(small[0].unit, "%");
assert.equal(small[0].min, 0);

// 曲线的起笔 = 检查器现在的那个数。1.99 之前柔焦不在曲线编辑器里，`baseOf` 只认得那六个标量属性；
// 若柔焦进来了而起笔仍从 defaults 取，滑杆推到 12% 时画布会把 0 当作基准，第一笔就把柔焦关了。
const blurField = spatialAnimFields(caps(), 1080)[0];
assert.equal(curveBase({}, blurField), 0, "片段没带 effects 时按默认值 0 起笔");
assert.equal(curveBase({ effects: { ...DEFAULT_EFFECTS, blur: 0.12 } }, blurField), 0.12, "起笔读的是 clip.effects.blur");
assert.equal(curveBase({ effects: { ...DEFAULT_EFFECTS, opacity: 0.5 } }, EFFECT_FIELDS[4]), 0.5);
// 遮罩那几条读的是遮罩自己的框，不是 effects。
assert.equal(curveBase({ mask: { ...DEFAULT_MASK, shape: "rectangle", width: 0.6 } }, MASK_ANIM_FIELDS[2]), 0.6, "遮罩宽度曲线从当前宽度起笔");
assert.equal(curveBase({}, MASK_ANIM_FIELDS[0]), 0, "没有遮罩时按 0，不给 NaN");

console.log("PASS: 柔焦曲线的上限与检查器同一次计算（画幅高不同取的那个也不同），老引擎不回就没有这条，属性名认得 ◆，起笔读 clip.effects / clip.mask");
