/**
 * 1.274: the second picture may be footage. This pins the interface's half of the contract:
 * the picker offers video only when the engine says `layer_video`, the monitor draws a video
 * layer only while paused/stepping (the engine's `motion`) and seeks it to the clip clock, and
 * the manifest type carries `kind`/`motion`. The engine's own halves are pinned by
 * `tests/layervideo_check.py` (export pixels, short-source refusal, manifest values).
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
const render = read("src/agentcut/render.py", "../../src/agentcut/render.py");
const animation = read("src/agentcut/animation.py", "../../src/agentcut/animation.py");
const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const fields = read("desktop/src/views/GradeFields.tsx", "../../desktop/src/views/GradeFields.tsx");
const preview = read("desktop/src/views/Preview.tsx", "../../desktop/src/views/Preview.tsx");
const help = read("desktop/src/views/Help.tsx", "../../desktop/src/views/Help.tsx");

assert.match(contracts, /"layer_video": True/, "能力表没有报视频层");
assert.match(timeline, /def _check_layer_sources\(project, grade, clip\)/, "写入检查没收片段时长");
assert.match(timeline, /if asset\.kind not in \("image", "video"\)/, "写入仍只收图像");
assert.match(timeline, /reason="too_short"/, "短素材没有自己的原因");
assert.equal(
  (timeline.match(/_check_layer_sources\(candidate, [^)]*clip\)/g) ?? []).length, 2,
  "两条写入路都要把片段交给同一处检查",
);
assert.match(render, /if asset\.kind == "video":/, "导出的视频层没有单独那一条输入");
assert.match(render, /plan\.input_args \+= \["-t", sec\(clip\.duration_ticks\), "-i", asset\.verified\.path\]/,
  "视频层输入没有用片段时长裁");
assert.match(render, /"-loop",\s*\n\s*"1",/, "图像那条腿的 -loop 1 被删了");
assert.match(render, /reason="too_short"/, "编译期没有兜住「片段后来变长」");
assert.match(animation, /row\["kind"\] = asset\.kind/, "清单没有交 kind");
assert.match(animation, /"always" if asset\.kind == "image" else "paused"/, "清单没有交 motion");
assert.match(animation, /reason"\] = False, "too_short"/, "清单没有把短素材说成画不成");
assert.match(engine, /kind\?: "image" \| "video" \| null; motion\?: "always" \| "paused" \| null/,
  "PreviewManifest 类型没有这两格");

assert.match(fields, /app\.caps\?\.features\?\.layer_video === true/, "界面没有按能力表列视频");
assert.match(fields, /row\.kind === "image" \|\| \(videos && row\.kind === "video"\)/,
  "素材下拉没有把视频算进候选");
assert.ok(fields.includes("（视频）"), "下拉里没标出哪一条是视频");
assert.ok(fields.includes("视频层从素材第一帧开始播"), "检查器没有说出视频层的起点");
assert.ok(fields.includes("暂停/逐帧"), "检查器没有说监视器什么时候画视频层");
assert.ok(fields.includes("外部画面层的素材"), "下拉的无障碍名被改了");

assert.match(preview, /if \(!compositeLive\(row\.motion, playing\)\) return null;/, "视频层没有问唯一的播放时机判断");
assert.match(preview, /row\.kind === "video"/, "监视器没有按 kind 分视频与图像");
assert.match(preview, /className="layer-grade" muted playsInline preload="auto"/, "视频层元素不是静音的内联播放");
assert.match(preview, /node\.currentTime = target;/, "暂停的视频层没有 seek 到片段时钟");
assert.ok(help.includes("1.274 起这一层可以是一段视频"), "帮助里没写视频层");
assert.ok(help.includes("too_short"), "帮助里没写短素材的拒绝");

console.log(
  "desktop_layervideo_check: PASS: 素材下拉按能力表列视频、监视器按 motion 只在暂停时画并 seek、"
  + "清单类型与帮助都说到视频层的起点/短素材/预览边界",
);
