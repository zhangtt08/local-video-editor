// 1.288：多机位对齐——相关峰只有一个算法、一份计划，说不准的不动。
//
// 这一档钉的是「怎么算、谁在动、何时拒绝」：
// ① 包络是 10 毫秒一格，互相关在每个重叠窗口里**各自去均值**（否则静音段两个常数相关恒为 1.0，
//    会把真正的峰挤掉——这一条是实测抓出来的）；
// ② 偏移折到帧上，计划是普通 clip.move；弱峰、同轨、变速、越界与同拍各自按名字拒绝；
// ③ 读路由不改 revision、MCP 只读、按钮受能力位管并走同一个 store 函数。
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
const sync = read("src/agentcut/sync.py");
const api = read("src/agentcut/http_api.py");
const mcp = read("src/agentcut/mcp_server.py");
const engine = read("desktop/src/engine.ts");
const store = read("desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx");
const help = read("desktop/src/views/Help.tsx");

// ① 包络与相关：一处算法，静音不冒充峰。
assert.match(sync, /DECODE_RATE = 1000/, "解码采样率不在模块里");
assert.match(sync, /HOP = 10/, "包络格长不在模块里");
assert.match(sync, /CELLS|MIN_OVERLAP_CELLS/, "没有最短重叠");
assert.match(sync, /left_mean = sum\(reference\[start:end\]\) \/ count/, "重叠里没有各自去均值");
assert.match(sync, /right_mean = sum\(other\[start \+ lag : end \+ lag\]\) \/ count/, "另一侧没有去均值");
assert.match(sync, /if left_energy <= 1e-12 or right_energy <= 1e-12:/, "平坦段没有按没有信息处理");
assert.match(sync, /return cross \/ math\.sqrt\(left_energy \* right_energy\)/, "相关没有归一化");
assert.match(sync, /int\(round\(lag_ticks\(lag\) \/ frame_ticks\)\) \* frame_ticks/, "偏移没有折到帧上");

// ② 契约、拒绝与命令。
assert.match(contracts, /class SyncRequest\(Contract\):/, "契约里没有 SyncRequest");
assert.match(contracts, /clip_ids: Annotated\[list\[Identifier\], Field\(min_length=2, max_length=8\)\]/, "片段数没有上下限");
assert.match(contracts, /SYNC_MIN_SCORE = 0\.5/, "弱峰门槛不在契约里");
assert.match(contracts, /"multicam_sync": media_ready/, "能力位没下发");
assert.match(contracts, /"sync_min_score": SYNC_MIN_SCORE/, "门槛没进能力表");
assert.match(sync, /"op": "clip\.move"/, "计划里不是普通 clip.move");
assert.match(sync, /before zero/, "越界没有自己的说法");
assert.match(api, /@app\.post\("\/v1\/projects\/\{project_id\}\/sync", dependencies=auth\)/, "没有这条路由");
assert.match(api, /problem = audio_scan_problem\(project, clip\)/, "路由没有读共用的声音守卫");
assert.match(api, /if clip\.speed_percent != 100:/, "变速没有按名字拒绝");
assert.match(api, /two of these clips sit on one track/, "同轨没有按名字拒绝");
assert.match(api, /"SYNC_WEAK"/, "弱峰没有按名字拒绝");
assert.match(api, /"SYNC_OUT_OF_RANGE"/, "越界没有按名字拒绝");
assert.match(api, /"SYNC_ALIGNED"/, "同拍没有按名字拒绝");
assert.match(api, /commands=commands,  # type: ignore\[arg-type\]/, "apply 没有把同一份计划交给 reducer");
assert.match(mcp, /async def clips_sync\(/, "MCP 没有 clips_sync");
assert.match(mcp, /"apply": False, "dry_run": False/, "MCP 没有强制只读");

// ③ 客户端、界面与提示。
assert.match(engine, /syncPlan\(projectId: string, body: Record<string, unknown>\)/, "引擎客户端没有 syncPlan");
assert.match(engine, /\/v1\/projects\/\$\{projectId\}\/sync/, "引擎客户端的路径不对");
for (const code of ["INVALID_SYNC_TARGET", "SYNC_WEAK", "SYNC_TARGET", "SYNC_OUT_OF_RANGE", "SYNC_ALIGNED", "SYNC_FAILED"]) {
  assert.ok(engine.includes(`${code}: "`), `没有 ${code} 的中文提示`);
}
assert.match(store, /export async function alignMulticam\(\)/, "store 里没有 alignMulticam");
assert.match(store, /engine\.syncPlan\(project\.id, \{/, "store 没有走引擎的规划");
assert.match(store, /clip_ids: state\.selectedClips\.slice\(0, 8\)/, "没有把选中的机位发出去");
assert.match(store, /submit\(commands as Command\[\], `对齐 \$\{commands\.length\} 路机位`\)/, "计划没有整批提交");
// 真窗口抓到过：路由回执包在 `sync` 里，store 直接读顶层只会报「操作失败」。
assert.match(store, /const commands = planned\.sync\.commands;/, "store 没有拆开 sync 回执");
assert.match(inspector, /app\.caps\?\.features\?\.multicam_sync/, "按钮没有受能力位管");
assert.match(inspector, /void alignMulticam\(\)/, "按钮没有调 store");
assert.ok(help.includes('{ key: "剪辑·多机位对齐"'), "帮助页没有这一条");

console.log(
  "PASS: 多机位对齐只有一处算法与一份计划——10 毫秒包络、重叠内各自去均值、偏移折到帧、" +
    "计划是普通 clip.move；弱峰/同轨/变速/越界/同拍各自按名字拒绝，读路由与 MCP 只读，" +
    "按钮受能力位管并走同一个 store 函数",
);
