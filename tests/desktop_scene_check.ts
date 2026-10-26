// 1.282：按镜头切分——颜色检测、一份计划、一个批次；界面只摆按钮，不自己找切点。
//
// 这一档钉的是「谁在判断」与「哪里只有一份」：
// ① 检测在引擎（`scenes.py`）：64×36 RGB 的相邻帧差，**不是** FFmpeg 的 luma-only scene 分
//    （纯红→纯绿在 6.1.1 的 scene 分是 0.0，这一版的差是 0.50，模块头记着这次测量）；
// ② 门槛 / 最短镜头 / 上限只有契约一处，能力表下发；请求模型的带就是同一组常量；
// ③ 计划是普通的 `clip.split`，从右往左；HTTP 只读不写、`apply` 一个批次；
// ④ MCP 的 `clip_scenes` 强制只读，交回的命令由 `timeline_edit` 提交；
// ⑤ 界面按钮受能力位与素材类型管，调 store 那一个函数；store 读能力表的默认值、空计划不写。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};
const count = (text: string, needle: RegExp) => (text.match(needle) ?? []).length;

const contracts = read("src/agentcut/contracts.py");
const scenes = read("src/agentcut/scenes.py");
const api = read("src/agentcut/http_api.py");
const mcp = read("src/agentcut/mcp_server.py");
const engine = read("desktop/src/engine.ts");
const store = read("desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx");
const help = read("desktop/src/views/Help.tsx");

// ① 检测的单位与那条反证。
assert.match(scenes, /SAMPLE_FPS = 30/, "采样率不在模块里");
assert.match(scenes, /SAMPLE_W, SAMPLE_H = 64, 36/, "采样尺寸不在模块里");
assert.match(scenes, /def _difference\(previous: bytes, frame: bytes\) -> float/, "没有颜色差那一步");
assert.match(scenes, /total \/ \(_FRAME_BYTES \* 255\)/, "差值没有按 0..1 归一");
assert.match(scenes, /format=rgb24/, "解码的不是 RGB");
assert.ok(!/select='gt\(scene/.test(scenes), "又用回了 FFmpeg 的 scene 分");
assert.match(scenes, /luma-only|只看亮度/, "模块头没写清为什么不用 FFmpeg 的 scene 分");
assert.match(scenes, /red→green|红→绿|纯红到纯绿/, "模块头没写那次实测");

// ② 常量只有一份、两条读法同一个数。
assert.match(contracts, /SCENE_THRESHOLD_DEFAULT = 0\.18/, "门槛默认值不在契约里");
assert.match(contracts, /SCENE_THRESHOLD_MIN = 0\.02/, "门槛下限不在契约里");
assert.match(contracts, /SCENE_THRESHOLD_MAX = 0\.9/, "门槛上限不在契约里");
assert.match(contracts, /SCENE_MIN_MS_DEFAULT = 400/, "最短镜头不在契约里");
assert.match(contracts, /SCENE_MAX_CUTS = 200/, "切点上限不在契约里");
assert.match(scenes, /SCENE_THRESHOLD_DEFAULT,/, "scenes 没有读契约的门槛");
assert.ok(!/DEFAULT_THRESHOLD = 0\.18/.test(scenes), "scenes 自己又写了一份 0.18");
assert.match(contracts, /class SceneRequest\(Contract\):[\s\S]*?threshold: Annotated\[\s*\n?\s*float, Field\(ge=SCENE_THRESHOLD_MIN, le=SCENE_THRESHOLD_MAX\)\s*\n?\s*\] = SCENE_THRESHOLD_DEFAULT/, "请求模型的带不是那组常量");
assert.match(contracts, /"scene_split": media_ready/, "能力位没下发（应与静音一样受媒体引擎管）");
assert.match(contracts, /"scene_threshold_default": SCENE_THRESHOLD_DEFAULT/, "门槛默认值没进能力表");
assert.match(contracts, /"scene_max_cuts": SCENE_MAX_CUTS/, "上限没进能力表");

// ③ 计划是普通命令、从右往左；HTTP 的两条路。
assert.match(scenes, /"op": "clip.split"/, "计划里不是普通 clip.split");
assert.match(scenes, /sorted\(cuts, key=lambda item: -item\["at_ticks"\]\)/, "计划没有从右往左");
assert.match(api, /@app\.post\("\/v1\/projects\/\{project_id\}\/clips\/\{clip_id\}\/scenes"/, "没有这条路由");
assert.match(api, /problem = picture_scan_problem\(project, clip\)/, "路由没有读共用的图片守卫");
assert.match(api, /if request\.apply and not commands:[\s\S]*?"SCENE_NONE"/, "没有切点时的 apply 不是按名字拒绝");
assert.match(api, /if not request\.apply:[\s\S]*?"committed": False/, "只读那一支没有 committed: False");
assert.match(api, /commands=commands,  # type: ignore\[arg-type\]/, "apply 没有把同一份计划交给 reducer");
assert.match(mcp, /async def clip_scenes\(/, "MCP 没有 clip_scenes");
assert.match(mcp, /"apply": False, "dry_run": False/, "MCP 没有强制只读");

// ④ 界面：能力位、素材类型、store 那一个函数、空计划不写。
assert.match(inspector, /app\.caps\?\.features\?\.scene_split && asset\?\.kind === "video" && !asset\.sequence_id/, "按钮没有受能力位与素材类型管");
// 1.282：片段操作（含这颗按钮）住在「时间与剪辑」里；那一节默认折叠的话，选中片段的人根本看不见它。
// 1.298：那一节不再套一层折叠（属性页本来就是「一次只渲染一档」，再套一层是第三层），
// 所以判据从「必须写成 <details open>」换成「没有任何一处把它折起来」——藏起来仍然是红的。
assert.match(inspector, /时间与剪辑/, "片段操作那一节的标题不见了");
assert.doesNotMatch(
  inspector,
  /<details(?![^>]*\bopen\b)[^>]*>\s*<summary[^>]*>时间与剪辑/,
  "片段操作默认藏在折叠里"
);
assert.match(inspector, /onClick=\{\(\) => void splitScenes\(clip\.id\)\}/, "按钮没有调 store");
assert.match(inspector, /disabled=\{Boolean\(clip\.speed_curve\)\}/, "带速度曲线的片段按钮没有灰");
assert.match(store, /export async function splitScenes\(clipId: string\)/, "store 里没有 splitScenes");
assert.match(store, /engine\.scenePlan\(project\.id, clipId, \{/, "store 没有走引擎的规划");
assert.match(store, /threshold: state\.caps\.limits\.scene_threshold_default \?\? 0\.18/, "门槛没有读能力表");
assert.match(store, /min_scene_ms: state\.caps\.limits\.scene_min_ms_default \?\? 400/, "最短镜头没有读能力表");
assert.match(store, /if \(!commands\.length\) \{[\s\S]*?没有写入任何东西/, "空计划没有说清不写");
assert.match(store, /submit\(commands as Command\[\], `按镜头切成 \$\{pieces\} 段`\)/, "计划没有整批提交");
assert.match(engine, /scenePlan\(projectId: string, clipId: string, body: Record<string, unknown>\)/, "引擎客户端没有 scenePlan");
assert.match(engine, /\/v1\/projects\/\$\{projectId\}\/clips\/\$\{clipId\}\/scenes/, "引擎客户端的路径不对");
assert.equal(count(inspector, /splitScenes/g), 2, "按钮与 import 各一处，别处不该再调");
assert.ok(help.includes('{ key: "剪辑·按镜头切分"'), "帮助页没有这一条");

console.log(
  "PASS: 按镜头切分只有一套判断——颜色检测在引擎（64×36 RGB，不是 luma-only scene 分）、" +
    "门槛/上限只在契约并从能力表下发、计划是普通的 clip.split（右到左）、HTTP 只读与 apply 两条路、" +
    "MCP 强制只读、界面按钮走同一个 store 函数且空计划不写",
);
