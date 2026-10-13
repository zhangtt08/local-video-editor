/** 「背景透明」这个勾从界面到请求体只有一条路。

 1.136 把引擎内部的 `_transparent`（嵌套合成用）变成了公开的一项交付选择。公开就意味着三处要一致：
 预设表里那个 `alpha` 字段（引擎的拒绝读它）、界面那个勾、以及真发出去的请求。任何一处自己算一遍，
 就会出现「勾着透明、发出去是不透明」或者反过来——文件都写完了才发现，这正是这一批要避免的事。

 这里跑的是真 `Engine`（照 `desktop_zoomclamp_check.ts` 的先例，先把假 fetch 摆好），断的是行为：
 四种组合下 `matteAllowed` 的答案、POST  body 里那个字段确实等于问的、干跑的 query 只在要为真时
 才带上它、批量那一条每一项保留自己的答案。最后是面板那一侧的接线：勾、待发清单、竖屏副本让路、
 还有那句「换哪几条预设」的提示，全读同一处。
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

const { Engine, matteAllowed } = await import("../desktop/src/engine");
const engine = new Engine("http://127.0.0.1:1", "t".repeat(64));

const ALPHA = { id: "prores-4444-alpha", container: "mov", codec: "prores_ks", alpha: true };
const PLAIN = { id: "h264-1080p", container: "mp4", codec: "libx264" };
const AUDIO = { id: "audio-mp3", container: "mp3", codec: null };
const asPreset = (item: Record<string, unknown>) => item as never;

// 那个勾的真值表：只有「预设说装得下」且「真的有画面」且「人确实要」三条同时成立才算生效。
assert.equal(matteAllowed(asPreset(ALPHA), false, true), true, "truth-alpha-yes");
assert.equal(matteAllowed(asPreset(PLAIN), false, true), false, "truth-plain-no");
assert.equal(matteAllowed(asPreset(AUDIO), true, true), false, "truth-audio-no");
assert.equal(matteAllowed(asPreset(ALPHA), false, false), false, "truth-unrequested-no");
assert.equal(matteAllowed(null, false, true), false, "truth-null-preset-no");

// POST 渲染：字段发出去的就是问的那个值，两半都断，否则「默认值」能把漏掉的参数伪装成正确。
await engine.render("p1", 7, ALPHA.id, "母版.mov", undefined, null, "contain", "full", true);
let body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(body.transparent, true, "body-transparent-true");
assert.equal(sent.at(-1)!.method, "POST", "render-is-a-post");
await engine.render("p1", 7, ALPHA.id, "母版.mov", undefined, null, "contain", "full");
body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(body.transparent, false, "body-transparent-false");

// 干跑：query 只在要为真时带上这一个键，其余参数的位置不能因为多了一个键而错位。
await engine.renderPlan("p1", ALPHA.id, 7, null, "contain", "full", true);
assert.ok(sent.at(-1)!.url.includes("transparent=true"), "query-carries-the-flag");
assert.ok(sent.at(-1)!.url.includes("preset_id="), "query-still-names-the-preset");
await engine.renderPlan("p1", ALPHA.id, 7, null, "cover", "marks", false);
assert.ok(!sent.at(-1)!.url.includes("transparent"), "query-omits-an-unasked-matte");
assert.ok(sent.at(-1)!.url.includes("range=marks"), "query-still-carries-range");
assert.ok(sent.at(-1)!.url.includes("fit=cover"), "query-still-carries-fit");

// 批量：每一项保留自己的答案，不是一整批共用一个。
await engine.renderBatch("p1", 7, [
  { preset_id: ALPHA.id, filename: "a.mov", fit: "contain", transparent: true },
  { preset_id: ALPHA.id, filename: "b.mov", fit: "contain" },
]);
const batch = JSON.parse(sent.at(-1)!.body ?? "{}") as { items: Record<string, unknown>[] };
assert.equal(batch.items.length, 2, "both-deliverables-send");
assert.equal(batch.items[0].transparent, true, "batch-item-one-true");
assert.equal(batch.items[1].transparent, undefined, "batch-item-two-untouched");

// 面板那一侧的接线：勾、发出去的值、以及竖屏副本让路，问的都是同一个 matte。
const panel = readFileSync(SRC + "desktop/src/views/ExportPanel.tsx", "utf8");
assert.ok(/const matte = matteAllowed\(preset, audioOnly, transparent\)/.test(panel), "matte-live");
assert.ok(/checked=\{matte\}/.test(panel), "checkbox-matte");
assert.ok(/transparent: matte/.test(panel), "sent-matte");
// 1.137 在同一颗按钮上多带了起始时间码，1.138 再多带交付帧率，1.151 再多带交付色彩标记：
// 这一条断的仍是「交出去的是 matte 这个有效值」，而不是界面另算一次。参数尾巴变了就要同步改这里——
// 这正是这条断言的作用。
assert.ok(
  /renderPlanPreview\(preset\.id, fit, range, matte, sendTimecode, sendFps, sendColourTag\)/.test(panel),
  "dryrun-matte",
);
assert.ok(
    /startRender\(preset\.id, finalName, folder \|\| undefined, fit, range, matte, sendTimecode, sendFps, sendColourTag\)/.test(
      panel
    ),
    "start-matte",
  );
assert.ok(/alsoVertical && vertical && !audioOnly && !matte/.test(panel), "vertical-yields");
assert.ok(panel.includes("背景透明时竖屏那条"), "vertical-reason");
assert.ok(/disabled=\{Boolean\(blocked\) \|\| audioOnly \|\| !preset\?\.alpha\}/.test(panel), "needs-alpha");
assert.ok(panel.includes("装不下透明度"), "names-the-exit");
assert.ok(!/transparent:\s*(true|false)/.test(panel), "stale-literal");
assert.ok(!/const matte = !audioOnly/.test(panel), "no-second-copy");

// 引擎那句新的拒绝有中文，而且说清了换哪一条。
const engineTs = readFileSync(SRC + "desktop/src/engine.ts", "utf8");
const hint = engineTs.match(/^\s{6}TRANSPARENT_NEEDS_ALPHA: "([^"]*)",$/m);
assert.ok(hint, "no-hint");
assert.ok(hint![1].length >= 20, `hint 太短：${hint![1]}`);
assert.ok(hint![1].includes("ProRes 4444"), "hint 要念出真的出路");

console.log(
  "PASS: 透明背景只有一条路——预设的 alpha、面板的勾、请求体里的那个字段，" +
    "四处读的都是 matteAllowed 这一处",
);
