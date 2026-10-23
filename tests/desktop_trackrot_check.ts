/**
 * 1.271: in-plane rotation is a stored knob, a request field, and a curve the reducer writes.
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const contracts = read("src/agentcut/contracts.py", "../../src/agentcut/contracts.py");
const timeline = read("src/agentcut/timeline.py", "../../src/agentcut/timeline.py");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const store = read("desktop/src/store.ts", "../../desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const help = read("desktop/src/views/Help.tsx", "../../desktop/src/views/Help.tsx");

assert.match(contracts, /"mask_track_rotation": True/, "能力表没有报旋转跟踪");
assert.match(contracts, /estimate_rotation: bool = False/, "目标上没有旋转开关");
assert.match(contracts, /every tracked point must carry a rotation, or none of them/,
  "一条路径的旋转点必须整条都有或整条都没有");
assert.match(timeline, /MASK_TRACK_ALL_CURVES = \(\*MASK_TRACK_SIZED_CURVES, "mask_rotation"\)/,
  "从头重跟必须把旋转曲线也算作被替换的一族");
assert.match(timeline, /values \|= \{"mask_rotation": "rotation"\}/, "reducer 没有写 mask_rotation");

assert.match(effects, /rotate: "agentcut.trackRotate"/, "旋钮没有自己的存储键");
assert.match(effects, /rotate: localStorage\.getItem\(KNOB_KEYS\.rotate\) === "1"/,
  "旋转估计默认必须是关的（只有明确写过 1 才算开）");
assert.match(effects, /rotate\?: boolean/, "跟踪目标类型没有旋转");

const mapping = store.slice(store.indexOf("export async function trackMasks"), store.indexOf("/** 划动源画面"));
assert.match(mapping, /estimate_rotation: target\.rotate/, "请求没有把旋钮交出去");
const extra = store.slice(store.indexOf("export async function trackExtraMask"), store.indexOf("/** 划动源画面"));
assert.match(extra, /estimateRotation\?: boolean/, "再叠块没有可选的旋转参数");
assert.match(extra, /estimate_rotation: estimateRotation/, "再叠块没有把旋转交出去");

assert.match(inspector, /mask_track_rotation/, "界面没有按能力表出示旋钮");
assert.match(
  inspector,
  /features\?\.mask_track_rotation \? <label className="dim" title="开着时每一个跟踪点/,
  "旋钮没有按能力表出示",
);
assert.match(inspector, /旋转也跟/, "检查器里没有这个旋钮");
assert.match(inspector, /aria-label="跟踪时估计画面里的旋转"/, "旋钮没有无障碍名");
assert.match(inspector, /disabled=\{mask\.shape === "path"\}[\s\S]{0,200}跟踪时估计画面里的旋转/,
  "路径遮罩没有禁用旋转估计");
assert.match(inspector, /rotate: app\.caps\?\.features\?\.mask_track_rotation \? trackRotate : undefined/,
  "主遮罩的请求没有带上旋钮");
assert.match(inspector, /trackExtraMask\(clip\.id, index, at, app\.caps\?\.features\?\.mask_track_rotation/,
  "再叠块没有带上同一个旋钮");
assert.ok(help.includes("旋转也跟"), "帮助里没写这个旋钮");
assert.ok(!help.includes("旋转不会被估计"), "帮助里还留着旧话");

console.log(
  "desktop_trackrot_check: PASS: 能力表、契约、reducer、旋钮、请求与帮助都说到同一件事——"
  + "旋转默认关，开启后写 mask_rotation，路径遮罩不给这一手",
);
