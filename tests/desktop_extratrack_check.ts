/**
 * 1.269: one extra mask block gets its own tracker — one route, one store action, one batch.
 *
 * The engine check proves the path; this proves the wire: the button is capability-gated, names
 * why it is off, and writing still goes through the ordinary clip.mask_stack command.
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const store = read("desktop/src/store.ts", "../../desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const help = read("desktop/src/views/Help.tsx", "../../desktop/src/views/Help.tsx");

assert.equal(
  (engine.match(/\/v1\/projects\/\$\{projectId\}\/clips\/\$\{clipId\}\/mask-stack\/\$\{index\}\/track/g) ?? []).length,
  1,
  "再叠遮罩的跟踪路由在壳层只许有一处",
);
assert.match(
  engine,
  /extraMaskTrack\(projectId: string, clipId: string, index: number, body: Record<string, unknown>\)/,
  "engine 里没有 extraMaskTrack",
);
assert.match(engine, /written_keys: number; coarse: boolean;/, "返回类型没把抽稀结果说清楚");

const body = store.slice(
  store.indexOf("export async function trackExtraMask"),
  store.indexOf("/** 划动源画面"),
);
assert.ok(body.length > 0, "找不到 trackExtraMask 的函数体");
assert.equal((body.match(/engine\.extraMaskTrack\(/g) ?? []).length, 1, "这一块只能问引擎一次");
assert.equal((body.match(/submit\(found\.commands as Command\[\], "跟踪这一块遮罩"\)/g) ?? []).length, 1,
  "一次点击必须只提交一个批次");
assert.ok(body.includes("dry_run: true"), "分析没有走只读那一趟");
assert.ok(body.includes("撤销一步整块退回"), "提示里没说撤销会退回什么");
assert.ok(body.includes("主遮罩与别的块没有改动"), "提示里没说哪些东西没动");
assert.ok(body.includes("coarse"), "抽稀把路径压粗时没有说出来");
assert.ok(!/simplif|correlat|ncc/i.test(body), "界面里又长出了一份跟踪/抽稀算术");

assert.match(inspector, /跟踪这一块/, "检查器里没有这颗按钮");
assert.match(inspector, /features\?\.extra_mask_track/, "按钮没按能力表出现");
assert.match(inspector, /clip\.speed_curve[\s\S]{0,200}跟踪这一块/, "带变速曲线的片段没有按名字说明");
assert.match(
  inspector,
  /trackExtraMask\(clip\.id, index, at[,)]/,
  "按钮没有调用那一处唯一实现",
);
assert.match(inspector, /const inside = play\.ticks/, "按钮没有判播放头是否真在这段里");
assert.match(inspector, /!inside/, "播放头不在片段里时按钮没有禁用");

assert.match(help, /mask_stack_track/, "帮助里没写这一档的出处");
assert.match(help, /跟踪这一块/, "帮助里没写这一格是什么");

console.log(
  "desktop_extratrack_check: PASS: 一条再叠遮罩跟踪路由、一处 trackExtraMask、一个批次、"
  + "能力表放行、变速与播放头越界各自说清，界面不算跟踪，帮助写到出处",
);
