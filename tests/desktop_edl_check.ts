// 1.285：EDL 剪辑表——只有一处写法、一条读路由、一个菜单入口，说不出的东西整条拒绝。
//
// 这一档钉的是「谁在写、写什么、拒绝谁」：
// ① 文本只在 `interchange.py` 写（时码、卷名、事件号）；界面与 MCP 都不拼第二份；
// ② 只写它说得准的：一条画面轨、直切、100% 速度、整帧率；其它按名字拒绝并点名；
// ③ 读路由不改 revision；MCP 只读；菜单项受能力位与轨类型管，走同一个 store 函数。
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
const interchange = read("src/agentcut/interchange.py");
const api = read("src/agentcut/http_api.py");
const mcp = read("src/agentcut/mcp_server.py");
const engine = read("desktop/src/engine.ts");
const store = read("desktop/src/store.ts");
const timeline = read("desktop/src/views/Timeline.tsx");
const help = read("desktop/src/views/Help.tsx");

// ① 一份写法。
assert.match(interchange, /def timecode\(ticks: int, fps: int\) -> str:/, "没有时码那一步");
assert.match(interchange, /f"\{hour:02d\}:\{minute:02d\}:\{second:02d}:\{frame:02d\}"/, "时码不是 HH:MM:SS:FF");
assert.match(interchange, /def reel_name\(label: str\) -> str:/, "没有卷名清洗");
assert.match(interchange, /re\.sub\(r"\[\^A-Z0-9\]", "_"/, "卷名没有按 CMX 的字母表清洗");
assert.match(interchange, /"FCM: NON-DROP FRAME"/, "没有不丢帧声明");
assert.match(interchange, /f"\{event\['number'\]:03d\}  \{event\['reel'\]:<8\} V     C        "/, "事件行格式不在这一处");
assert.match(interchange, /"\* FROM CLIP NAME: \{event\['label'\]\}"/, "没有素材名注释");

// ② 拒绝都按名字、都点名。
assert.match(interchange, /"EDL_RATE"/, "分数帧率没有按名字拒绝");
assert.match(interchange, /"EDL_EMPTY"/, "空轨没有按名字拒绝");
assert.match(interchange, /"EDL_UNSUPPORTED"/, "说不出的剪辑没有按名字拒绝");
assert.match(interchange, /clips=refused/, "拒绝没有点名是哪几段");
assert.match(interchange, /if clip\.speed_percent != 100:/, "变速没有被拦住");
assert.match(interchange, /if clip\.transition_in is not None:/, "转场没有被拦住");
assert.match(interchange, /if asset is None or asset\.kind != "video":/, "非画面片段没有被拦住");

// ③ 契约、路由、MCP、两端接线。
assert.match(contracts, /"edl_export": True/, "能力位没下发");
assert.match(api, /@app\.get\("\/v1\/projects\/\{project_id\}\/edl", dependencies=auth\)/, "没有这条读路由");
assert.match(api, /listed = interchange\.build_edl\(project, track_id\)/, "路由没有交回那一份文本");
assert.match(api, /"revision": root\.revision/, "读路由没有带 revision");
assert.match(mcp, /async def project_edl\(/, "MCP 没有 project_edl");
assert.match(engine, /trackEdl\(projectId: string, trackId: string, sequenceId\?: string \| null\)/, "引擎客户端没有 trackEdl");
assert.match(engine, /\/v1\/projects\/\$\{projectId\}\/edl\$\{query\}/, "引擎客户端的路径不对");
assert.match(engine, /EDL_RATE: "/, "没有 EDL_RATE 的中文提示");
assert.match(engine, /EDL_UNSUPPORTED: "/, "没有 EDL_UNSUPPORTED 的中文提示");
assert.match(engine, /EDL_EMPTY: "/, "没有 EDL_EMPTY 的中文提示");
assert.match(store, /export async function copyTrackEdl\(trackId: string\)/, "store 里没有 copyTrackEdl");
assert.match(store, /engine\.trackEdl\(project\.id, trackId, state\.sequenceId\)/, "store 没有走引擎");
assert.match(store, /bridge\.copyText\(listed\.text\)/, "没有把文本交给剪贴板");
assert.match(timeline, /app\.caps\?\.features\?\.edl_export/, "菜单项没有受能力位管");
assert.match(timeline, /label: "复制这一轨的 EDL（剪辑表）"/, "轨道菜单里没有这一项");
assert.match(timeline, /void copyTrackEdl\(track\.id\)/, "菜单项没有调 store");
assert.ok(help.includes('{ key: "剪辑·EDL 剪辑表"'), "帮助页没有这一条");

console.log(
  "PASS: EDL 剪辑表只有一处写法——时码/卷名/事件行都在 interchange.py，拒绝都按名字并点名；" +
    "HTTP 只读、MCP 只读、菜单项受能力位与轨类型管并走同一个 store 函数、帮助页写到边界",
);
