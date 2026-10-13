/** 起始时间码这一栏：界面只负责把字符串交出去，判规矩的是引擎。

 1.137 加了一个自由文本输入。自由文本最容易出两种事故：界面自己写一份正则「好心」先拦一道（于是
 引擎那句点名拒绝永远看不到，而两份规矩会慢慢长歪），以及新变量把 `../time` 里那个 `timecode()`
 格式化函数遮住——这不是假想，`const [timecode, setTimecode]` 就是这么把导出摘要那行调用打挂的
 （tsc 报了「This expression is not callable」）。这里两样都断住。

 跑的是真 `Engine`（假 `fetch` 收请求）：要写的时候 body/query 里有它、不写的时候一个字都不多，
 批量那两条各留各的答案。最后是面板那侧的接线与「不许出现第二个正则」。
 */

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = REPO_ROOT;

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

const TC = "01:02:03;04";

await engine.render("p1", 7, "prores-422hq", "母版.mov", undefined, null, "contain", "full", false, TC);
let body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(body.timecode, TC, "body-timecode-asked");
await engine.render("p1", 7, "prores-422hq", "母版.mov", undefined, null, "contain", "full", false, null);
body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(body.timecode, null, "body-timecode-null-when-unasked");
await engine.render("p1", 7, "prores-422hq", "母版.mov");
body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(body.timecode, null, "body-timecode-default");

await engine.renderPlan("p1", "prores-422hq", 7, null, "contain", "full", false, TC);
assert.ok(sent.at(-1)!.url.includes("timecode=01%3A02%3A03%3B04"), sent.at(-1)!.url);
assert.ok(sent.at(-1)!.url.includes("preset_id="), "query-keeps-the-preset");
await engine.renderPlan("p1", "prores-422hq", 7, null, "contain", "full", false, null);
assert.ok(!sent.at(-1)!.url.includes("timecode"), "query-omits-when-unasked");

await engine.renderBatch("p1", 7, [
  { preset_id: "prores-422hq", filename: "a.mov", fit: "contain", timecode: TC },
  { preset_id: "prores-422hq", filename: "b.mov", fit: "contain" },
]);
const batch = JSON.parse(sent.at(-1)!.body ?? "{}") as { items: Record<string, unknown>[] };
assert.equal(batch.items[0].timecode, TC, "batch-one-keeps-its-own");
assert.equal(batch.items[1].timecode, undefined, "batch-two-untouched");

const panel = readFileSync(SRC + "desktop/src/views/ExportPanel.tsx", "utf8");
assert.ok(!/const \[timecode[,=]/.test(panel), "no-shadow-formatter");
assert.ok(/const \[timecodeText, setTimecodeText\]/.test(panel), "field-state-named");
// 1.142：图像序列没有容器挂时间码，那一栏对它恒为「不写」；念的与发出的仍是同一个值。
assert.ok(
  /const sendTimecode = isSequence \? null : timecodeText\.trim\(\) \|\| null;/.test(panel),
  "one-effective-value",
);
assert.equal((panel.match(/timecode: sendTimecode/g) ?? []).length, 2, "sent-to-both-deliverables");
// 1.138 又在这一串尾巴上加了交付帧率，1.151 再加交付色彩标记：这两条断的是「发出去的就是
// matte/sendTimecode/sendFps/sendColourTag 这些有效值」，参数列表一变就得同步——变了没同步，
// 红的是这两条，而不是没人看见。
assert.ok(/renderPlanPreview\(preset\.id, fit, range, matte, sendTimecode, sendFps, sendColourTag\)/.test(panel), "dryrun-carries");
assert.ok(
  /startRender\(preset\.id, finalName, folder \|\| undefined, fit, range, matte, sendTimecode, sendFps, sendColourTag\)/.test(
    panel
  ),
  "start-carries",
);
assert.ok(panel.includes("timecode_shape"), "shape-from-engine");
assert.ok(panel.includes("timecode_drop_rates"), "drop-rates-from-engine");
assert.ok(!/\{2\}/.test(panel), "no-second-regex");
assert.ok(panel.includes("留空就是不写"), "says-what-empty-means");
assert.ok(/maxLength=\{11\}/.test(panel), "length-is-eleven");

const engineTs = readFileSync(SRC + "desktop/src/engine.ts", "utf8");
for (const code of ["TIMECODE_INVALID", "TIMECODE_NEEDS_PICTURE"]) {
  const hint = engineTs.match(new RegExp(`^\\s{6}${code}: "([^"]*)",\\s*$`, "m"));
  assert.ok(hint, `no-hint:${code}`);
  assert.ok(hint![1].length >= 20, `thin-hint:${code}`);
}
const store = readFileSync(SRC + "desktop/src/store.ts", "utf8");
// 1.138 在两个调用尾巴上又加了 outputFps，1.151 又加了 colourTag：这两条断的是 store 把时间码
// 原样递给引擎，参数多一个就得跟着多一个，谁悄悄不传了会红在这里。
assert.ok(/renderPlan\([\s\S]{0,180}transparent, timecode, outputFps, colourTag\)/.test(store), "store-plan-forwards");
assert.ok(/engine\.render\([\s\S]{0,200}range, transparent, timecode, outputFps, colourTag\)/.test(store), "store-start-forwards");
assert.ok(store.includes("时间码 ${timecode}"), "toast-names-it");

console.log(
  "PASS: 起始时间码从这一栏到请求体只有一条路，界面不写第二份正则、也不遮住那个格式化时间的函数；" +
    "不写的时候参数一个字都不多",
);
