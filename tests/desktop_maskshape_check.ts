/** 1.118 的界面那一半：形变起来的自由路径遮罩，界面只挑引擎点名的那一窗。
 *
 * 三条线都要能红：
 * ① `maskShape.ts` 的纯函数——选窗、取轮廓、落位数字、有没有上秒表；
 * ② 接线——画面里的拖拽交出去的是 `mask.shape.set`，入口只在引擎声明了能力之后才出现，额度读
 *    capabilities 而不是界面自己写死；
 * ③ 契约配对——引擎那份窗表吐哪些键，`MaskShapeWindow` 就得读同样的键，任何一头改名都会红。
 */
import assert from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { morphArmed, outlineAt, shapeVariables, shapeWindowAt, shapeWindowIndex } from "../desktop/src/maskShape";
import type { MaskShapeWindow } from "../desktop/src/engine";

const read = (...parts: string[]) => {
  const path = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(path, `missing source: ${parts.join("/")}`);
  return readFileSync(path, "utf8");
};

const picture = read("desktop/src/views/MaskPicture.tsx");
const preview = read("desktop/src/views/Preview.tsx");
const inspector = read("desktop/src/views/Inspector.tsx");
const store = read("desktop/src/store.ts");
const engine = read("desktop/src/engine.ts");
const styles = read("desktop/src/styles.css");
const effects = read("desktop/src/effects.ts");
const curve = read("desktop/src/views/CurveEditor.tsx");
const animation = read("src/agentcut/animation.py");

const plate = (from: number, to: number, edge: number, extra = {} as Partial<MaskShapeWindow>): MaskShapeWindow => ({
  from_ticks: from,
  to_ticks: to,
  image: `url("#plate-${edge}")`,
  vertices: [
    { x: edge, y: 0, handle_out: [0, 0], handle_in: [0, 0] },
    { x: edge, y: 1, handle_out: [0, 0], handle_in: [0, 0] },
    { x: 0, y: 1, handle_out: [0, 0], handle_in: [0, 0] },
  ],
  width: extra.width ?? edge,
  height: extra.height ?? 1,
  offset_x: extra.offset_x ?? 0,
  offset_y: extra.offset_y ?? 0,
});

const FRAME = Math.floor(70_560_000 / 30);
const windows = [plate(0, 8 * FRAME, 0.1), plate(8 * FRAME, 16 * FRAME, 0.2), plate(16 * FRAME, 24 * FRAME, 0.3)];

// 选窗：落在哪一格就用哪一格；两格共用的那条边界属于后一格——导出把后一张板盖在前一张上，
// 所以半开区间不是界面的偏好，是导出的事实（tests/maskshape_check.py 在真实像素上量过那一刻）。
assert.equal(shapeWindowAt(windows, 0)!.vertices[0].x, 0.1);
assert.equal(shapeWindowAt(windows, 7 * FRAME)!.vertices[0].x, 0.1);
assert.equal(shapeWindowAt(windows, 8 * FRAME)!.vertices[0].x, 0.2, "the shared edge belongs to the later step");
assert.equal(shapeWindowAt(windows, 23 * FRAME)!.vertices[0].x, 0.3);
assert.equal(shapeWindowAt(windows, 99 * FRAME)!.vertices[0].x, 0.3, "past the last window the shape holds");
assert.equal(shapeWindowAt(windows, -5)!.vertices[0].x, 0.1, "before the first one too");
assert.equal(shapeWindowAt(null, 0), null);
assert.equal(shapeWindowAt([], 0), null);
assert.equal(shapeWindowIndex(windows, 8 * FRAME), 2);
assert.equal(shapeWindowIndex(windows, 0), 1);
assert.equal(shapeWindowIndex(null, 0), 0, "no schedule, no step to name");

// 取轮廓：有窗就用窗，没窗才回到画好的那条；界面不在两枚帧之间自己算中间值。
const drawn = { vertices: [{ x: 0.9, y: 0.9, handle_out: [0, 0], handle_in: [0, 0] }] };
assert.equal(outlineAt(windows[1], drawn as never)[0].x, 0.2, "the window's table wins over the stored outline");
assert.equal(outlineAt(null, drawn as never)[0].x, 0.9);
assert.deepEqual(outlineAt(null, null), [], "a clip without a mask has no outline to draw");

// 落位：数字一个都不改，原样交给 CSS。这里多做一次乘法就是界面自己发明位置。
assert.deepEqual(shapeVariables(windows[0]), { "--shape-w": 0.1, "--shape-h": 1, "--shape-ox": 0, "--shape-oy": 0 });
assert.deepEqual(shapeVariables(null), {}, "no window, no extra numbers");

// 秒表：第一枚轮廓帧就是开关，没有第二个勾选。
assert.equal(morphArmed({ mask_shape_keys: [{}] } as never), true);
assert.equal(morphArmed({ mask_shape_keys: [] } as never), false);
assert.equal(morphArmed({} as never), false, "an old project reads as unarmed");

// 接线：界面挑窗、画窗里那条轮廓、把窗里的板贴上去；拖动交出去的是形状帧，不是遮罩本身。
assert.match(picture, /const shapeWindow = draft \? null : shape \? shapeWindowAt\(shape, local\) : null;/);
assert.match(picture, /const vertices = outlineAt\(shapeWindow, mask\);/);
assert.match(picture, /maskImage: shapeWindow\.image, \.\.\.shapeVariables\(shapeWindow\)/);
assert.match(picture, /masked-picture\$\{shapeWindow \? " morph-mask"/);
assert.match(picture, /recordMaskShape\(clip\.id, next\.vertices \?\? \[\], at, undefined, gesture\.projectId, gesture\.revision\)/);
assert.match(picture, /morphArmed\(clip\) && \(gesture\.vertex !== undefined \|\| gesture\.outline\)/, "a vertex or outline drag on an armed mask records a shape frame");
assert.match(picture, /if \(morphing && morphArmed\(clip\)\)/);
assert.match(picture, /recordMaskShape\(clip\.id, value\.vertices \?\? \[\], local/, "arrow-key nudges record too");
// 1.51 那条「拖整条轮廓 = 写中心关键帧」没有被删掉，只是让位于已经上秒表的遮罩。
assert.match(picture, /} else if \(gesture\.outline && \(clip\.keyframes \?\? \[\]\)\.some\(\(key\) => key\.property === "mask_x"/);
assert.match(preview, /shape=\{plan\?\.mask_shape\}/, "the monitor gets the engine's window list");
assert.match(preview, /animation=\{plan\?\.mask_curves && \(plan\.mask_unit \|\| plan\.mask_shape\)/, "the box curves still animate while the shape steps");

// 入口只在引擎声明了能力之后出现；额度是引擎的数，界面那份只是没回字段时的兜底。
assert.match(inspector, /features\.path_shape_keys \? <MaskShapeKeys/, "the outline section is capability-gated");
assert.match(inspector, /features\.path_shape_keys \? "轮廓本身也能随时间变形/);
assert.match(inspector, /轮廓本身也能随时间变形：先记一帧/); // 1.209：那一句收成了一行，说的是同一件事
assert.match(inspector, /const limit = app\.caps\?\.limits\?\.mask_shape_keys \?\? 32;/);
assert.match(inspector, /还没有轮廓帧/, "an unarmed mask is told how to start");

// 交出去的命令：一次一帧，清场一批；逐条发会撞自己的 revision。
assert.match(store, /"mask\.shape\.set"/);
assert.match(store, /"mask\.shape\.remove"/);
assert.match(store, /editAtRevision\(locals\.map\(\(at\) => \(\{ op: "mask\.shape\.remove", clip_id: clipId, at_ticks: at \}\)\)/, "clearing is one batch");
assert.match(store, /at_ticks: atTicks,\s*vertices,\s*interpolation:/);

// 插值那四个名字仍只有一张表：轮廓帧与曲线编辑器共读 effects.ts 那一处。
assert.match(effects, /export const INTERPOLATIONS = \{ linear: "线性", ease: "缓入缓出", hold: "保持", bezier: "贝塞尔" \} as const;/);
for (const [name, source] of [["CurveEditor", curve], ["Inspector", inspector], ["store", store], ["engine", engine], ["MaskPicture", picture]] as const) {
  assert.ok(!/const INTERPOLATIONS = \{/.test(source), `${name} carries a second interpolation table`);
}
assert.match(curve, /import \{[^}]*INTERPOLATIONS[^}]*\} from "\.\.\/effects"/);
assert.match(inspector, /Object\.entries\(INTERPOLATIONS\)/);

// 落位那条式子在 CSS 里，用的全是引擎给的数；界面不在 style 里自己拼位置。
assert.match(styles, /\.masked-picture\.morph-mask \{/);
assert.match(styles, /mask-position: calc\(\(var\(--mask-x\) \+ var\(--shape-ox\) - var\(--shape-w\) \/ 2\)/);

// 契约配对：引擎那份窗表写哪些键，界面就只读那些键。
const block = animation.slice(animation.indexOf("mask_shape.append("));
const emitted = [...block.slice(0, 1200).matchAll(/^ +"([a-z_]+)":/gm)].map((match) => match[1]);
const declared = /export type MaskShapeWindow = \{([^}]*)\}/.exec(engine)?.[1] ?? "";
for (const key of ["from_ticks", "to_ticks", "image", "vertices", "width", "height", "offset_x", "offset_y"]) {
  assert.ok(emitted.includes(key), `the engine no longer emits ${key} in a shape window`);
  assert.ok(declared.includes(`${key}:`), `MaskShapeWindow does not declare ${key}`);
}
assert.doesNotMatch(declared, /scale_x/, "a scale the exporter does not apply must not survive in the UI");

console.log(
  "PASS: 形变轮廓的界面只挑引擎点名的那一窗（边界归后一格），拖出去的是 mask.shape.set，入口跟着 capabilities 走，窗表的键与引擎逐字对上",
);
