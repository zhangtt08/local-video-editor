/** 交付帧率这张表：界面排的下拉是引擎能力表那一张，发出去的是同一份。

 1.138 让同一条时间线可以交成另一档率（PAL 25、NTSC 29.97、胶片感 23.976…）。这里要断住的
 是三类事故：① 界面自己抄一份表（抄的那份会有一天和引擎不一样，而且拒的是引擎）；② 没选的时候
 还把这个字段发出去——引擎的契约是 `extra="forbid"`，老引擎会因为多一个不认的键整条拒收，所以
 「不选=不发」是兼容问题，不是风格问题；③ 存进方案的那组交付和点「开始导出」发出去的那组不是
 同一组（这是导出面板一直在守的那条规矩）。

 跑的是真 `Engine`（假 `fetch` 收请求），再加上两份源码的接线检查。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = "C:/Users/Administrator/Desktop/项目/agentcut/";

type Sent = { url: string; method: string; body: string | undefined };
const sent: Sent[] = [];
Object.assign(globalThis, {
  fetch: async (url: string, init: { method?: string; body?: string }) => {
    sent.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ job: { id: "j1" }, jobs: [], plan: {} }),
    };
  },
});

const { Engine } = await import("../desktop/src/engine");
const engine = new Engine("http://127.0.0.1:1", "t".repeat(64));
const RATE = { numerator: 25, denominator: 1 };

await engine.render("p1", 7, "h264-1080p", "母版.mp4", undefined, null, "contain", "full", false, null, RATE);
let body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.deepEqual(body.output_frame_rate, RATE, "body-rate-asked");
await engine.render("p1", 7, "h264-1080p", "母版.mp4", undefined, null, "contain", "full", false, null, null);
body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.ok(!("output_frame_rate" in body), "body-rate-omitted-when-unasked");
await engine.render("p1", 7, "h264-1080p", "母版.mp4");
body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.ok(!("output_frame_rate" in body), "body-rate-omitted-by-default");

await engine.renderPlan("p1", "h264-1080p", 7, null, "contain", "full", false, null, RATE);
assert.ok(sent.at(-1)!.url.includes("output_fps=25%2F1"), `query-rate-encoded: ${sent.at(-1)!.url}`);
await engine.renderPlan("p1", "h264-1080p", 7, null, "contain", "full", false, null, {
  numerator: 30_000,
  denominator: 1_001,
});
assert.ok(sent.at(-1)!.url.includes("output_fps=30000%2F1001"), sent.at(-1)!.url);
await engine.renderPlan("p1", "h264-1080p", 7);
assert.ok(!sent.at(-1)!.url.includes("output_fps"), "query-omits-rate");

await engine.renderBatch("p1", 7, [
  { preset_id: "h264-1080p", filename: "a.mp4", fit: "contain", output_frame_rate: RATE },
  { preset_id: "h264-1080p", filename: "b.mp4", fit: "contain" },
]);
const batch = JSON.parse(sent.at(-1)!.body ?? "{}") as { items: Record<string, unknown>[] };
assert.deepEqual(batch.items[0].output_frame_rate, RATE, "batch-one-keeps-its-own-rate");
assert.ok(!("output_frame_rate" in batch.items[1]), "batch-two-stays-untouched");

const engineSrc = readFileSync(SRC + "desktop/src/engine.ts", "utf8");
assert.match(engineSrc, /^\s{6}UNKNOWN_OUTPUT_RATE: "([^"]*)",\s*$/m, "hint-unknown-output-rate");
assert.match(engineSrc, /^\s{6}OUTPUT_RATE_NEEDS_PICTURE: "([^"]*)",\s*$/m, "hint-rate-needs-picture");
assert.ok(/output_frame_rates\?:/.test(engineSrc), "capabilities-carry-the-table");

const store = readFileSync(SRC + "desktop/src/store.ts", "utf8");
assert.ok(
  /engine\.render\(project\.id, project\.revision, presetId, filename, folder, state\.sequenceId, fit, range, transparent, timecode, outputFps\)/.test(
    store,
  ),
  "store-threads-the-rate-to-render",
);
assert.ok(
  /\.renderPlan\(state\.project\.id, presetId, state\.project\.revision, state\.sequenceId, fit, range, transparent, timecode, outputFps\)/.test(
    store,
  ),
  "store-threads-the-rate-to-plan",
);

const panel = readFileSync(SRC + "desktop/src/views/ExportPanel.tsx", "utf8");
// 表只有一份：界面问引擎要，不许把八档抄在这里。
assert.ok(/caps\?\.output_frame_rates/.test(panel), "panel-asks-engine-for-the-table");
for (const literal of ["29.97", "23.976", "59.94"]) {
  assert.ok(!panel.includes(`"${literal}"`) && !panel.includes(`'${literal}'`), `panel-no-copied-${literal}`);
}
assert.ok(
  /renderPlanPreview\(preset\.id, fit, range, matte, sendTimecode, sendFps\)/.test(panel),
  "panel-plan-sends-the-rate",
);
assert.ok(
  /startRender\(preset\.id, finalName, folder \|\| undefined, fit, range, matte, sendTimecode, sendFps\)/.test(
    panel,
  ),
  "panel-export-sends-the-rate",
);
const rateFields = panel.match(/output_frame_rate: sendFps/g) ?? [];
assert.equal(rateFields.length, 2, "panel-recipe-is-exactly-what-is-sent");
assert.ok(/disabled=\{Boolean\(blocked\) \|\| audioOnly \|\| !rateChoices\.length\}/.test(panel), "panel-audio-cannot-carry-a-rate");

console.log(
  `PASS: 交付帧率一张表只有一份（界面问 ${"caps.output_frame_rates"} 要）；选了的发、没选的一个字不写，` +
    `query 里分子/分母编码过，批量各留各的答案，方案里存的就是发出去的那 ${rateFields.length} 条`,
);
