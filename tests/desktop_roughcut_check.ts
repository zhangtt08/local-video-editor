// 1.283：按镜头粗剪——检测仍只有一处，收尾靠普通 trim 的 ripple；界面只多一格秒数。
//
// 这一档钉的是「哪里只有一份、哪一步由谁做」：
// ① 检测复用 `scenes.py` 的颜色差，没有再写第二个检测器；
// ② 计划只有普通 `clip.split` 与带 `ripple=true` 的 `clip.trim`，两者都从右往左；
// ③ 每镜留的默认值与上下限只在契约里，能力表下发，界面不写第二份；
// ④ HTTP 两条路（只读 / apply）、MCP 强制只读、界面一格秒数 + 一颗按钮走同一个 store 函数。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8").replace(/\r\n/g, "\n");
};

const contracts = read("src/agentcut/contracts.py");
const scenes = read("src/agentcut/scenes.py");
const api = read("src/agentcut/http_api.py");
const mcp = read("src/agentcut/mcp_server.py");
const engine = read("desktop/src/engine.ts");
const store = read("desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx");
const help = read("desktop/src/views/Help.tsx");
const timeline = read("desktop/src/views/Timeline.tsx");
const css = read("desktop/src/styles.css");

// ① 检测还是那一处、那一组数。
assert.match(scenes, /def rough_cut_plan\(clip, cuts: list\[dict\], frame_ticks: int, keep_ticks: int\)/,
  "粗剪没有自己的计划函数");
assert.match(scenes, /def keep_ticks_for\(frame_ticks: int, keep_ms: int\) -> int/, "没有把每镜留折到帧上");
assert.match(scenes, /int\(round\(keep_ms \* TIMEBASE \/ 1000 \/ frame_ticks\)\) \* frame_ticks/,
  "每镜留没有落在帧网格上");
assert.ok(!/def _detect|def analyse/.test(scenes.slice(scenes.indexOf("def rough_cut_plan"))),
  "粗剪又写了一份检测");

// ② 计划是普通命令、从右往左、收尾带 ripple。
assert.match(scenes, /"op": "clip\.split",\n\s+"clip_id": clip\.id,/, "计划里没有普通 split");
assert.match(scenes, /right_clip_id": f"\{clip\.id\}-rough\{number:02d\}"/, "右半段的 id 不稳定");
assert.match(scenes, /"op": "clip\.trim",/, "计划里没有普通 trim");
assert.match(scenes, /"ripple": True/, "收尾没有让后段左移");
assert.match(scenes, /clip\.source_in_ticks \+ start \* clip\.speed_percent \/\/ 100/,
  "留下的头读的源没有按恒定速度折算");
assert.match(scenes, /for offset, at in enumerate\(reversed\(points\)\)/, "split 不是从右往左");
assert.match(scenes, /for number in range\(total, -1, -1\)/, "trim 不是从右往左");

// ③ 默认值与上下限只在契约。
assert.match(contracts, /ROUGH_KEEP_MS_DEFAULT = 1500/, "每镜留的默认值不在契约里");
assert.match(contracts, /ROUGH_KEEP_MS_MIN = 100/, "每镜留的下限不在契约里");
assert.match(contracts, /ROUGH_KEEP_MS_MAX = 30000/, "每镜留的上限不在契约里");
assert.match(contracts, /class RoughCutRequest\(Contract\):[\s\S]*?keep_ms: Annotated\[[\s\S]*?ROUGH_KEEP_MS_DEFAULT/,
  "请求模型没有读那一组常量");
assert.match(contracts, /"rough_cut": media_ready/, "能力位没下发");
assert.match(contracts, /"rough_keep_ms_default": ROUGH_KEEP_MS_DEFAULT/, "默认值没进能力表");
assert.match(contracts, /"rough_keep_ms_min": ROUGH_KEEP_MS_MIN/, "下限没进能力表");
assert.match(contracts, /"rough_keep_ms_max": ROUGH_KEEP_MS_MAX/, "上限没进能力表");
assert.ok(!/ROUGH_KEEP_MS_DEFAULT = 1500/.test(scenes), "scenes 又写了一份 1500");

// ④ HTTP / MCP / 界面。
assert.match(api, /@app\.post\("\/v1\/projects\/\{project_id\}\/clips\/\{clip_id\}\/rough-cut"/,
  "没有这条路由");
assert.match(api, /problem = picture_scan_problem\(project, clip\)/, "路由没有读共用的图片守卫");
assert.match(api, /"INVALID_ROUGH_TARGET"/, "错类型没有按名字拒绝");
assert.match(api, /if request\.apply and not commands:[\s\S]*?"ROUGH_NONE"/, "没可切时没有按名字拒绝");
assert.match(api, /if not request\.apply:[\s\S]*?"committed": False/, "只读那一支没有 committed: False");
assert.match(api, /commands=commands,  # type: ignore\[arg-type\]/, "apply 没有把同一份计划交给 reducer");
assert.match(mcp, /async def clip_rough_cut\(/, "MCP 没有 clip_rough_cut");
assert.match(mcp, /"apply": False, "dry_run": False/, "MCP 没有强制只读");
assert.match(engine, /roughCutPlan\(projectId: string, clipId: string, body: Record<string, unknown>\)/,
  "引擎客户端没有 roughCutPlan");
assert.match(engine, /\/v1\/projects\/\$\{projectId\}\/clips\/\$\{clipId\}\/rough-cut/, "引擎客户端的路径不对");
assert.match(engine, /rough_keep_ms_default\?: number/, "能力表的默认值没有进类型");
assert.match(engine, /INVALID_ROUGH_TARGET: "/, "没有这句中文提示");
assert.match(engine, /ROUGH_NONE: "/, "没有这句中文提示");
assert.match(store, /export async function roughCut\(clipId: string, keepMs: number\)/, "store 里没有 roughCut");
assert.match(store, /engine\.roughCutPlan\(project\.id, clipId, \{/, "store 没有走引擎的规划");
assert.match(store, /keep_ms: keepMs/, "store 没有把每镜留发出去");
assert.match(store, /threshold: state\.caps\.limits\.scene_threshold_default \?\? 0\.18/, "门槛没有读能力表");
assert.match(store, /if \(!commands\.length\) \{[\s\S]*?没有写入任何东西/, "空计划没有说清不写");
assert.match(store, /submit\(commands as Command\[\], `粗剪：每镜留 \$\{\(keepMs \/ 1000\)\.toFixed\(1\)\} 秒`\)/,
  "计划没有整批提交");
assert.match(inspector, /app\.caps\?\.features\?\.rough_cut && asset\?\.kind === "video" && !asset\.sequence_id/,
  "那一格没有受能力位与素材类型管");
assert.match(inspector, /rough_keep_ms_default \?\? 1500/, "默认秒数没有读能力表");
assert.match(inspector, /void roughCut\(clip\.id, Math\.round\(wanted \* 1000\)\)/, "按钮没有调 store");
assert.match(inspector, /id="rough-keep"/, "没有那格秒数");
assert.ok(help.includes('{ key: "剪辑·按镜头粗剪"'), "帮助页没有这一条");
// 1.284：整轨入口——同一条路由的整轨版、菜单项、store 函数与能力位。
assert.match(api, /@app\.post\("\/v1\/projects\/\{project_id\}\/tracks\/\{track_id\}\/rough-cut"/,
  "没有整轨那条路由");
assert.match(api, /key=lambda item: -item\.position_ticks/, "整轨没有从右往左排");
assert.match(api, /scanned\.append\(\{"clip_id": clip\.id, "skipped": problem\}\)/, "不能扫的片段没有带原因跳过");
assert.match(mcp, /async def track_rough_cut\(/, "MCP 没有 track_rough_cut");
assert.match(engine, /roughCutTrackPlan\(projectId: string, trackId: string, body: Record<string, unknown>\)/,
  "引擎客户端没有 roughCutTrackPlan");
assert.match(engine, /\/v1\/projects\/\$\{projectId\}\/tracks\/\$\{trackId\}\/rough-cut/, "整轨路径不对");
assert.match(store, /export async function roughCutTrack\(trackId: string\)/, "store 里没有 roughCutTrack");
assert.match(store, /keepMs = state\.caps\.limits\.rough_keep_ms_default \?\? 1500/, "整轨没有读能力表的默认秒数");
assert.match(store, /submit\(commands as Command\[\], `粗剪整轨：\$\{done\} 段`\)/, "整轨没有整批提交");
assert.match(inspector, /row-action/, "检查器那两行没有按内容给按钮留宽");
assert.match(timeline, /label: "按镜头粗剪这一轨"/, "轨道菜单里没有这一项");
assert.match(timeline, /roughCutTrack\(track\.id\)/, "菜单项没有调 store");
assert.ok(help.includes('{ key: "剪辑·整轨粗剪"'), "帮助页没有整轨那一条");
// 1.283 真窗口量到过：这一行的第四格是按钮，沿用 26px 那一格会把「粗剪」推出面板。
assert.match(inspector, /className="effect-row row-action">\s*<label htmlFor="rough-keep"/, "粗剪那一行没按内容给最后一列留宽");
assert.match(inspector, /className="effect-row row-action"><label htmlFor="clip-fit"/, "适配到那一行也没修");
assert.match(css, /\.effect-row\.row-action \{ grid-template-columns: 76px minmax\(56px, 1fr\) 18px auto; \}/,
  "样式表里没有 row-action 的列宽");

console.log(
  "PASS: 按镜头粗剪只有一套检测与一份计划——检测复用颜色差，计划是右到左的普通 split + 带 ripple 的 trim、" +
    "每镜留的默认值与上下限只在契约并从能力表下发、HTTP 只读与 apply 两条路、MCP 强制只读、" +
    "界面一格秒数 + 一颗按钮走同一个 store 函数且空计划不写",
);
