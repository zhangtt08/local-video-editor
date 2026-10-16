/**
 * 1.185 的壳层检查：链接状态那条轮询必须只点名选中的那几段，并且调用点真的用这条式子。
 *
 * 为什么单独一档：`preview_manifest` 在 1.183 就有了 `clips` 子集，而检查器那个组件读的只有
 * `revision` 与 `links`——这两个键在子集请求里仍按整份工程给。所以「不点名」不是保守，是白付：
 * 每次换选中都把整份清单搬一遍（两万段工程实测 36.54 MB）。这条检查钉式子与调用点两处，
 * 只改一处都会红。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { manifestUrl, mergePlans, monitorClipIds } from "../desktop/src/manifestFetch";

// 壳层检查是被打成 mjs 再跑的，`import.meta.url` 会落在 `build/shell-checks/` 那一层——所以按
// 仓库里既有的办法：拿 `process.cwd()` 试几条候选路径，谁存在用谁。
const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const BASE = "http://127.0.0.1:1";

// 1. 点名的形状：一枚一段、重复只留一次、顺序跟着选中走。
const one = manifestUrl(BASE, "p1", 7, null, ["c1"]);
assert.ok(one.includes("preview-manifest?"), one);
assert.ok(one.endsWith("revision=7&clips=c1"), one);
const many = manifestUrl(BASE, "p1", 7, null, ["c1", "c2", "c1"]);
assert.ok(many.endsWith("revision=7&clips=c1&clips=c2"), many);

// 2. 没有选中就不点名（那是「整份」那条老路，不是空子集）。
assert.ok(!manifestUrl(BASE, "p1", 7, null, null).includes("clips="), "null＝没点名，不许发 clips=");
assert.ok(manifestUrl(BASE, "p1", 7, null, []).includes("no_clips=1"), "空数组要说是 no_clips=1");

// 3. 合成与工程 id 都要跟着走，且段名要转义——不然一枚带 `&` 的 id 就能改写整条查询。
const nested = manifestUrl(BASE, "p 1", 12, "s/2", ["a&b"]);
assert.ok(nested.includes("/v1/projects/p%201/"), nested);
assert.ok(nested.includes("clips=a%26b"), nested);
assert.ok(nested.endsWith("&sequence_id=s%2F2"), nested);

// 4. 调用点真的用这条式子，而不是自己再拼一遍。
assert.ok(
  inspector.includes(
    "manifestUrl(appInfo.baseUrl(), project.id, project.revision, app.sequenceId, app.selectedClips)"
  ),
  "检查器那条 fetch 没接上 linkStatusUrl"
);
assert.ok(
  !inspector.includes("/v1/projects/${project.id}/preview-manifest"),
  "检查器还在自己拼 preview-manifest 的 URL（两处式子会分家）"
);
// 它读的确实只有 `revision` 与 `links`——点名子集才因此是零语义变化。
assert.ok(inspector.includes("links: value.links"), "这条轮询读的键变了，本档的前提要重看");

// 1.187：监视器那条也走同一处式子，而「可视集合」只有一份判断。
type ProjectArg = Parameters<typeof monitorClipIds>[0];
const F = Math.floor(70_560_000 / 30);
const seen = {
  tracks: [
    { id: "v", kind: "video", hidden: false, muted: false },
    { id: "a", kind: "audio", hidden: false, muted: false },
    { id: "h", kind: "video", hidden: true, muted: false },
    { id: "m", kind: "audio", hidden: false, muted: true },
  ],
  clips: {
    first: { id: "first", track_id: "v", position_ticks: 0, duration_ticks: 4 * F },
    second: { id: "second", track_id: "v", position_ticks: 4 * F, duration_ticks: 4 * F },
    voice: { id: "voice", track_id: "a", position_ticks: 0, duration_ticks: 8 * F },
    secret: { id: "secret", track_id: "h", position_ticks: 0, duration_ticks: 8 * F },
    quiet: { id: "quiet", track_id: "m", position_ticks: 0, duration_ticks: 8 * F },
  },
} as unknown as ProjectArg;

assert.deepEqual(monitorClipIds(seen, 2 * F), ["first", "voice"], "落点上的画面与声音都要点名");
assert.deepEqual(monitorClipIds(seen, 5 * F), ["second", "voice"], "跨过一格换成后一段");
assert.deepEqual(monitorClipIds(seen, 9 * F), [], "空隙里交回空集合，由式子说成 no_clips=1");
assert.ok(!monitorClipIds(seen, 2 * F).includes("secret"), "隐藏轨上的段不画，也不该点名");
assert.ok(!monitorClipIds(seen, 2 * F).includes("quiet"), "静音轨上的段不出声，也不该点名");

// 1.188：索引版与一份独立的暴力扫必须在**每一格**上答同一个数组。
// 为什么要在检查里再写一份扫法：这一档的判断是「哪几段这一格会被画出来」，而产品那份现在走了
// 二分＋前缀最大值；没有对照的话，「快」与「算错了」长得一模一样。转场允许同轨两段占住同一格
// （`CLIP_OVERLAP` 那句要的是显式转场，不是不许重叠），所以候选不止一条——只取「起点最大的那条」
// 那种写法会悄悄少画一层，而少画一层在画面上就是「这段没动画」。
const bruteForce = (project: ProjectArg, ticks: number): string[] => {
  const rows: { clip: { id: string; position_ticks: number; duration_ticks: number }; track: string }[] = [];
  const byId = new Map<string, { kind: string; hidden: boolean; muted: boolean }>();
  for (const track of Object.values(project.tracks)) byId.set(track.id, track);
  for (const clip of Object.values(project.clips)) {
    const track = byId.get(clip.track_id);
    if (!track || (track.kind !== "video" && track.kind !== "audio")) continue;
    if (track.kind === "video" ? track.hidden : track.muted) continue;
    if (ticks >= clip.position_ticks && ticks < clip.position_ticks + clip.duration_ticks) {
      rows.push({ clip, track: clip.track_id });
    }
  }
  const order = Object.values(project.tracks).map((track) => track.id);
  rows.sort((a, b) => order.indexOf(a.track) - order.indexOf(b.track) || a.clip.position_ticks - b.clip.position_ticks);
  return rows.map((row) => row.clip.id);
};

const build = (seed: number, tracks: number, clips: number, overlap: boolean): ProjectArg => {
  let state = seed;
  const next = (limit: number) => {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    return state % limit;
  };
  const rows: ProjectArg = {
    tracks: Array.from({ length: tracks }, (_, index) => ({
      id: `t${index}`,
      kind: index % 2 ? "audio" : "video",
      hidden: index === 2,
      muted: index === 3,
    })),
    clips: {},
  };
  for (let index = 0; index < clips; index += 1) {
    const track = `t${index % tracks}`;
    const id = `k${index}`;
    (rows.clips as Record<string, unknown>)[id] = {
      id,
      track_id: track,
      position_ticks: next(400) * F,
      duration_ticks: (1 + next(6)) * F,
    };
  }
  if (overlap) {
    // 同一条轨道上两段同时占住第 10 格：转场那一段的重叠。
    (rows.clips as Record<string, unknown>).wide = { id: "wide", track_id: "t0", position_ticks: 4 * F, duration_ticks: 10 * F };
    (rows.clips as Record<string, unknown>).narrow = { id: "narrow", track_id: "t0", position_ticks: 9 * F, duration_ticks: 2 * F };
  }
  return rows;
};

for (const [seed, tracks, clips, overlap] of [[7, 1, 200, false], [11, 4, 120, true], [23, 6, 400, true]] as const) {
  const model = build(seed, tracks, clips, overlap);
  for (let tick = -2; tick < 420; tick += 1) {
    const asked = tick * F;
    assert.deepEqual(
      monitorClipIds(model, asked),
      bruteForce(model, asked),
      `种子 ${seed} 的第 ${tick} 格：索引与暴力扫分家了`
    );
  }
}

const overlapped = build(3, 2, 6, true);
assert.deepEqual(
  monitorClipIds(overlapped, 10 * F).filter((id) => id === "wide" || id === "narrow").sort(),
  ["narrow", "wide"],
  "转场那一格里两段都得点名（只留一条就是少画一层）"
);

const nullSet = manifestUrl(BASE, "p1", 3, null, null);
assert.ok(!nullSet.includes("clips="), "null 才是「没点名＝整份」");
assert.equal(
  manifestUrl(BASE, "p1", 3, null, []),
  `${BASE}/v1/projects/p1/preview-manifest?revision=3&no_clips=1`
);

const shape = { clips: {} as Record<string, unknown>, revision: 9, mixed_track_ids: [] as string[] };
const merged = mergePlans(
  { ...shape, clips: { first: 1, shared: "旧" } },
  { ...shape, revision: 10, clips: { second: 2, shared: "新" } }
);
assert.deepEqual(Object.keys(merged.clips).sort(), ["first", "second", "shared"], "旧段要留住");
assert.equal(merged.clips.shared, "新", "同一段以这次答回的为准");
assert.equal(merged.revision, 10, "工程级那几个键取这一次的");

const preview = read("desktop/src/views/Preview.tsx", "../../desktop/src/views/Preview.tsx");
assert.ok(preview.includes("monitorClipIds(project, play.ticks)"), "监视器没在算可视集合");
assert.ok(preview.includes("mergePlans(previous.plan, plan)"), "补取时没合并，跨过一格会闪掉旧段");
assert.ok(preview.includes("[project, wantedKey, candidate]"), "失效键不是可视集合的签名（会每帧发一次）");
assert.ok(!preview.includes("linkStatusUrl"), "监视器还在用被取代的那条式子");

// 1.187 那次真窗口黑屏的根因：`Engine.request` 自己拼 `fetch(`${base}${path}`)`，给它绝对 URL
// 就会把前缀拼两次。URL 字符串本身长得对，所以这条必须钉在调用点上，不然同一课还会再来。
const engineSrc = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
assert.ok(
  engineSrc.includes("manifestPath(projectId, revision, sequenceId, clipIds)"),
  "engine.ts 必须把相对路径交给 request"
);
assert.ok(
  !/manifestUrl\(\s*this\.baseUrl/.test(engineSrc) && !engineSrc.includes("manifestUrl(this.baseUrl"),
  "engine.ts 不许把绝对 URL 交给 request（base 会被拼两次）"
);

console.log(
  "desktop_linksubset_check: 链接状态那条轮询点名选中片段（含转义与去重），调用点与式子都在一处"
);
