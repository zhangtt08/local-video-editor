/** 清晰的窗表在浏览器里怎么走：一份窗、一张名字表、一处「有曲线就改点」的判断。

 1.123 让 unsharp 的强度与半径编进**同一张**窗表（`animation.sharpen_schedule`），导出每一窗串一对
 `gblur`+`blend`，预览每一窗换一次 `<filter>`。风险集中在三处：① 两份数字（强度与半径）被分别排窗，
 于是导出串出预览没有的一段；② 界面自己判断「这是静态还是有窗」，两处判断迟早问出不一样的一张表；
 ③ 名字与上限在界面再抄一份，于是画得出导出会拒的斜坡。这个检查把这三处都钉在唯一的来源上，并把
 `SpatialProperty` 与契约那条 `Literal` 对字。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { type Capabilities, type SharpenSpec, type SharpenSteps } from "../desktop/src/engine";
import {
  FIELD_LABEL,
  sharpenFilters,
  sharpenFrames,
  sharpenLimits,
  sharpenSteps,
  spatialAnimFields,
} from "../desktop/src/effects";

const caps = (features: Record<string, boolean>, limits: Record<string, number> = {}): Capabilities =>
  ({
    features: { clip_blur: true, clip_sharpen: true, ...features },
    limits: {
      // 强度上限故意取一个不整齐的数：写死的顶（200）与下发折出来的顶才会分得开。
      blur_fraction: 0.25, blur_radius_limit_px: 64, sharpen_amount: 1.75, sharpen_radius_fraction: 0.25,
      sharpen_radius_default: 0.004, ...limits,
    },
  }) as unknown as Capabilities;
const HEIGHT = 180;

// ① 一格一步的窗：零强度那一窗浏览器也必须什么都不加——导出根本不为它串阶段。
const issued = {
  windows: [
    { id: "sh0001", amount: 0, bbox: [0.002, 0.004], from_ticks: 0, to_ticks: 70560000 },
    { id: "sh0002", amount: 0.5, bbox: [0.011, 0.022], from_ticks: 70560000, to_ticks: 141120000 },
  ],
  curve: [
    { offset: 0, id: null, easing: "steps(1, end)" },
    { offset: 0.5, id: "sh0002", easing: "steps(1, end)" },
  ],
} satisfies SharpenSteps;
assert.deepEqual(sharpenFrames(issued.curve), [
  { filter: "none", offset: 0, easing: "steps(1, end)" },
  { filter: "url(#sh0002)", offset: 0.5, easing: "steps(1, end)" },
], "每一窗换成那一个 def，零强度的那窗换回 none");
assert.deepEqual(sharpenFrames(null), [], "没有窗就不该有动画帧");
assert.deepEqual(sharpenFrames(undefined), []);
assert.deepEqual(sharpenFrames([]), []);
assert.equal(sharpenFrames(issued.curve)[1].easing, "steps(1, end)", "预览不许自己插出中间态");

// ②「静态还是有窗」只问这一次：两个入口对同一种载荷必须给出同一种答案。
const staticSpec = { id: "sh0003", amount: 1, bbox: [0.002, 0.004] };
assert.equal(sharpenSteps(staticSpec as SharpenSpec), null, "静态那片没有窗");
assert.deepEqual(sharpenSteps(issued), issued, "有窗那片原样交回");
assert.equal(sharpenFilters(undefined).length, 0);
assert.deepEqual(sharpenFilters(staticSpec as SharpenSpec), [staticSpec], "静态那一片就一个 def");
assert.deepEqual(sharpenFilters(issued).map((entry) => entry.id), ["sh0001", "sh0002"], "有窗就每一窗一个 def");
assert.equal(new Set(sharpenFilters(issued).map((entry) => entry.id)).size, issued.windows.length, "两张 def 不许共用一个 id");

// ③ 曲线编辑器的属性行：上限来自下发的那两个数，名字来自唯一那张表，开关没下就整行不出现。
const on = caps({ blur_keyframes: true, sharpen_keyframes: true });
const rows = spatialAnimFields(on, HEIGHT);
assert.deepEqual(rows.map((row) => row.property), ["blur", "sharpen", "sharpen_radius"], "三颗空间旋钮一排，顺序稳定");
assert.deepEqual(rows.map((row) => row.label), [FIELD_LABEL.blur, FIELD_LABEL.sharpen, FIELD_LABEL.sharpen_radius], "念的是那张唯一的表");
const amountRow = rows.find((row) => row.property === "sharpen")!;
const radiusRow = rows.find((row) => row.property === "sharpen_radius")!;
assert.equal(amountRow.max, sharpenLimits(on, HEIGHT).amount * 100, "强度的顶就是滑杆那个顶，不是另一处算的");
assert.equal(radiusRow.max, sharpenLimits(on, HEIGHT).radiusPercent, "半径的顶也是：实测像素带与下发比例按画幅折算取小");
assert.ok(radiusRow.max > 0 && amountRow.max > 0);
assert.deepEqual(spatialAnimFields(caps({ blur_keyframes: true }), HEIGHT).map((row) => row.property), ["blur"], "老引擎不回 sharpen_keyframes 就没有这两条");
assert.deepEqual(spatialAnimFields(caps({ sharpen_keyframes: true }), HEIGHT).map((row) => row.property), ["sharpen", "sharpen_radius"]);
assert.equal(spatialAnimFields(null, HEIGHT).length, 0, "没拿到 capabilities 就一条都不给");
assert.equal(spatialAnimFields(on, 0).find((row) => row.property === "sharpen"), undefined, "画幅高都不知道，折不出半径");

const views = (parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `must be readable from the check's working directory: ${parts.join(" or ")}`);
  return readFileSync(found, "utf8");
};

// 接线：预览换的是外层那道包装，而且问的是上面那两处判断，不是自己再问一遍。
const preview = views(["desktop/src/views/Preview.tsx", "src/views/Preview.tsx"]);
assert.match(preview, /const stepped = sharpenSteps\(plan\.sharpen\)/, "有窗没窗由那一份判断说");
assert.match(preview, /if \(stepped && edge\) \{\s*\n\s*const animation = edge\.animate\(sharpenFrames\(stepped\.curve\)/,
  "外层那道包装动画的是引擎下发的同一份窗，而且这段真的挂着");
assert.match(preview, /blurs\.current\.edge = node.*className="layer-edge"/s, "动画挂在那一层 edge 的包装上，即导出里 blend 的位置");
assert.match(preview, /for \(const spec of sharpenFilters\(clip\.sharpen\)\)/, "defs 也走那一份判断");
assert.doesNotMatch(preview, /clip\.sharpen\.id/, "视图不再自己拆开那片清晰");

// 接线：九颗效果旋钮（六条标量 + 柔焦 + 清晰的两颗）共用同一条「有曲线就改这一时刻的点」的判断，
// 也共用同一只 ◇。遮罩那几行写的是另一个对象（整张 mask），那是另一件事，这里不混为一谈。
const inspector = views(["desktop/src/views/Inspector.tsx", "src/views/Inspector.tsx"]);
assert.match(inspector, /const commitKnob = \(property: AnimatedEffect \| SpatialProperty/, "一条判断管这一组旋钮");
assert.match(inspector, /const knobButton = \(property: AnimatedEffect \| SpatialProperty/, "◇ 也只有一处写法");
assert.ok(inspector.includes("commitKnob(f.property"), "六条标量走那条共用的判断");
assert.ok(inspector.includes("knobButton(f.property, null"), "六条标量的 ◇ 也走那颗共用的按钮");
for (const property of ["blur", "sharpen", "sharpen_radius"]) {
  assert.ok(inspector.includes(`commitKnob("${property}"`), `${property} 的值走那条共用的判断`);
  assert.ok(inspector.includes(`knobButton("${property}"`), `${property} 的 ◇ 走那颗共用的按钮`);
}
assert.equal((inspector.match(/k\.property === f\.property/g) ?? []).length, 0, "标量那一行不许再自己问一遍有没有曲线");
assert.equal((inspector.match(/setKeyframe\(clip\.id, \{ \.\.\.knobFrame\(/g) ?? []).length, 1, "这一组旋钮改已有点的那一步只有一处");
assert.ok(inspector.includes('knobButton("sharpen", "sharpen_keyframes"') && inspector.includes('knobButton("sharpen_radius", "sharpen_keyframes"'),
  "两颗清晰旋钮认的是同一份下发开关——它们本来就共用一张窗表");

// 契约与界面的那条 Literal 必须一字不差，否则界面会写一个引擎不认的属性名。
const contracts = views(["src/agentcut/contracts.py", "../src/agentcut/contracts.py"]);
const literal = /SpatialProperty = Literal\[([^\]]*)\]/.exec(contracts.replace(/\r\n/g, "\n"));
assert.ok(literal, "契约里那条 SpatialProperty 要读得到");
const declared = literal[1].split(",").map((entry) => entry.trim().replace(/^"|"$/g, "")).filter(Boolean);
const engine = views(["desktop/src/engine.ts", "src/engine.ts"]);
const mirror = /export type SpatialProperty = ([^;]*);/.exec(engine.replace(/\r\n/g, "\n"));
assert.ok(mirror, "界面的那条联合要读得到");
const mirrored = mirror[1].split("|").map((entry) => entry.trim().replace(/^"|"$/g, "")).filter(Boolean);
assert.deepEqual(mirrored, declared, `界面抄的属性名与引擎那条不一致：${mirrored} 对 ${declared}`);
assert.deepEqual(declared, ["blur", "sharpen", "sharpen_radius"], "可打关键帧的空间属性就是这三个");
assert.match(contracts, /"sharpen_keyframes": True/, "开关与字段同批下发");
assert.match(contracts, /"sharpen_schedule_segments": SHARPEN_SCHEDULE_MAX/, "段数上限由引擎说，界面不自己写一个");
assert.deepEqual(
  ["sharpen", "sharpen_radius"].filter((property) => !Object.keys(FIELD_LABEL).includes(property)),
  [], "新进来的两条属性都得在那张唯一的表里有中文名",
);

console.log("PASS: 清晰的窗表在浏览器只被问一次（静态还是有窗）、名字只出自一张表、上限只出自引擎下发的那两个数");
