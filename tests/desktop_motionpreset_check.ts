// 1.231：入场 / 出场动画预设只写普通关键帧——没有第二套动画语义。
//
// 这一档跑的是那条纯函数（`motionCommands`）：它交回的每一枚都是 `keyframe.set`，落在整帧上，
// 起点是预设值、终格是片段自己的静态值；出场方向反过来。界面那一侧只钉「表只有一张、写只走
// 一处、一个版本」。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MOTION_PRESETS, motionCommands, motionSpan } from "../desktop/src/motionPresets";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const FRAME = 2_940_000; // 24 fps 的一帧
const SECOND = 70_560_000;
const clip = (effects: Record<string, number>, duration = SECOND) => ({
  id: "c", duration_ticks: duration,
  effects: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, gain: 1, blur: 0, sharpen: 0, sharpen_radius: 0.004, denoise: 0, ...effects },
}) as never;

type Row = { property: string; value: number; interpolation?: string };
const at = (commands: { keyframe?: { at_ticks: number } }[], tick: number): Row[] =>
  commands.filter((command) => command.keyframe?.at_ticks === tick)
    .map((command) => command.keyframe as unknown as Row);
const pairs = (rows: Row[]) => rows.map((row) => [row.property, Number(row.value.toFixed(4))]);

// ① 淡入：只写 opacity 两枚，0 → 静态值
const fade = motionCommands(clip({}), "in", "fade", 0.5, FRAME);
assert.equal(fade.length, 2, `淡入写了 ${fade.length} 条命令`);
assert.ok(fade.every((command) => command.op === "keyframe.set" && command.clip_id === "c"), "只许写关键帧");
assert.deepEqual(pairs(at(fade, 0)), [["opacity", 0]]);
assert.deepEqual(pairs(at(fade, 12 * FRAME)), [["opacity", 1]]);
assert.ok(at(fade, 0).every((row) => row.interpolation === "ease"), "预设不是缓入缓出");

// ② 上浮：透明度与外移一起写，终格回到静态值
const rise = motionCommands(clip({ y: 0.2 }), "in", "rise", 0.5, FRAME);
assert.equal(rise.length, 4, "上浮应当写 opacity 与 y 各两枚");
assert.deepEqual(pairs(at(rise, 0)), [["y", 0.28], ["opacity", 0]]);
assert.deepEqual(pairs(at(rise, 12 * FRAME)), [["y", 0.2], ["opacity", 1]]);

// ③ 放大按静态值算：已经缩到 0.8 的片段从 0.8×0.86 起，仍收在 0.8
const zoom = motionCommands(clip({ scale: 0.8 }), "in", "zoom_in", 0.5, FRAME);
assert.deepEqual(pairs(at(zoom, 0)), [["scale", 0.688], ["opacity", 0]]);
assert.deepEqual(pairs(at(zoom, 12 * FRAME)), [["scale", 0.8], ["opacity", 1]]);

// ④ 位移夹在自己的量程里：x=-0.95 再往左 0.1 只能是 -1
const slide = motionCommands(clip({ x: -0.95 }), "in", "slide_left", 0.5, FRAME);
assert.equal(at(slide, 0).find((row) => row.property === "x")?.value, -1);

// ⑤ 出场：静态值在前、预设值在后（时间反着来）
const out = motionCommands(clip({}), "out", "fade", 0.5, FRAME);
assert.deepEqual(pairs(at(out, SECOND - 12 * FRAME)), [["opacity", 1]]);
assert.deepEqual(pairs(at(out, SECOND)), [["opacity", 0]]);

// ⑥ 已经就是终点：一枚都不写（套两遍不会写出两对等值的针）
assert.deepEqual(motionCommands(clip({ opacity: 0 }), "in", "fade", 0.5, FRAME), []);

// ⑦ 每一枚都落在整帧上；时长短于片段、也短不过一帧
for (const preset of MOTION_PRESETS) {
  const commands = motionCommands(clip({ x: 0.5, y: -0.5 }), "in", preset.id, 0.3, FRAME);
  assert.ok(commands.length > 0, `${preset.label} 一枚都没写`);
  for (const command of commands as unknown as { keyframe: { at_ticks: number } }[]) {
    assert.equal(command.keyframe.at_ticks % FRAME, 0, `${preset.label} 有针落在两帧之间`);
  }
}
assert.equal(motionSpan(0.3, FRAME) % FRAME, 0, "0.3 秒也要折成整帧");
assert.ok(motionSpan(0.001, FRAME) >= FRAME, "再短也至少一帧");
assert.equal(motionCommands(clip({}, 5 * FRAME), "in", "fade", 1.2, FRAME)
  .every((command) => (command.keyframe as { at_ticks: number }).at_ticks <= 5 * FRAME), true, "针落到了片段外");

// ⑧ 界面那一侧：表只有一张、写只走一处、一个版本
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
assert.match(inspector, /import \{ MOTION_PRESETS, motionCommands, motionWords/, "界面没有读那张表");
assert.match(inspector, /<MotionControls clip=\{clip\} locked=\{locked\} \/>/, "那一节没接进检查器");
assert.match(inspector, /editAtRevision\(commands, project\.id, project\.revision,/, "没有走那个一个版本的写入口");
assert.doesNotMatch(inspector, /"上浮"|"下压"|"左滑"/, "界面自己抄了预设的名字——表就不止一张了");

console.log("PASS: 入场/出场预设只写普通关键帧、整帧对齐、终格是静态值、夹在量程里、已经到位就一枚不写");
