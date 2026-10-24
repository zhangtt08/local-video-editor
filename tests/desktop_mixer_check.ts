// 1.280：轨道混音——独奏、静音优先、整轨音量；一条判断、一份数、一处提交。
//
// 这一档钉的是**界面不许长出第二套混音规则**：
// ① 契约里 track 有 solo、track.update 能改它，能力位与音量两端都由引擎下发；
// ② 「这条轨出不出声」只在 `animation.track_audible` 一处判，导出与预览清单都读它；
// ③ 混音台那一节的滑杆只读 `limits.track_volume_max`，拖动只改本地、松手才提交，
//    提交走的是同一条 `track.update`；M/S 两颗按钮也走它；
// ④ 独奏只摆在声音轨上（画面轨的「更多」里没有这一条）；
// ⑤ 样式只用刻度里的字号，一条轨一行。
// 真页面上「点了真的写进工程、预览清单跟着变」由 `tests/mixerui_check.py` 量。
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
const animation = read("src/agentcut/animation.py");
const render = read("src/agentcut/render.py");
const engine = read("desktop/src/engine.ts");
const inspector = read("desktop/src/views/Inspector.tsx");
const timeline = read("desktop/src/views/Timeline.tsx");
const css = read("desktop/src/styles.css");

// ① 契约与能力表。
assert.match(contracts, /class Track\(Contract\):[\s\S]*?\n    solo: bool = False/, "Track 上没有 solo");
assert.match(contracts, /class TrackUpdate\(Contract\):[\s\S]*?\n    solo: bool \| None = None/, "track.update 改不了 solo");
assert.match(contracts, /SCHEMA_VERSION = \(\s*\n\s*33\b/, "schema 没抬到 33");
assert.match(contracts, /"track_mixer": True/, "能力位 track_mixer 没下发");
assert.match(contracts, /"track_volume_max": TRACK_VOLUME_MAX/, "音量上限没有从契约常量下发");
assert.match(contracts, /TRACK_VOLUME_MAX = 4\.0/, "音量上限常量不见了");

// ② 一条判断：导出与预览清单都读 track_audible。
assert.equal(count(animation, /def track_audible\(/g), 1, "track_audible 不止一处");
assert.equal(count(animation, /def solo_track_ids\(/g), 1, "solo_track_ids 不止一处");
assert.match(animation, /def track_audible[\s\S]*?if track\.muted:\s*\n\s*return False[\s\S]*?return not solos or track\.id in solos/, "静音优先/独奏让路那条判断变了形");
assert.match(animation, /def sound_enabled\(clip: Clip, track: Track, project: Project\)[\s\S]*?track_audible\(track, project\)/, "sound_enabled 没读 track_audible");
assert.match(animation, /"sound_enabled": sound_enabled\(clip, track, project\)/, "预览清单没有交同一条判断");
assert.match(render, /track_audible\(track, project\)/, "导出那趟没有读 track_audible");
assert.ok(!/kind == "audio" and not track\.muted/.test(render), "导出还留着自己那份「没静音就出声」");
assert.match(render, /"solo": track\.solo/, "渲染摘要里没有 solo");

// ③ 界面：能力位、上限、提交时机与提交口。
const mixer = inspector.slice(inspector.indexOf("function TrackMixer"), inspector.indexOf("function ProjectSettings"));
assert.ok(mixer.length > 0, "找不到混音台那一节");
assert.match(mixer, /features\?\.track_mixer/, "混音台没有受能力位管");
assert.match(mixer, /limits\?\.track_volume_max/, "滑杆上限没有读能力表");
assert.ok(!/400|200/.test(mixer.replace(/1\.4fr/g, "")), "混音台自己写了 200/400 这一档数");
assert.match(mixer, /onChange=\{\(event\) => setDraft\(Number\(event\.target\.value\)\)\}/, "拖动时不是只改本地值");
assert.match(mixer, /onPointerUp=\{commit\}/, "松手不提交");
assert.match(mixer, /onKeyUp=\{commit\}/, "键盘改完不提交");
assert.match(mixer, /onBlur=\{commit\}/, "失焦不提交");
assert.equal(count(mixer, /updateTrack\(/g), 3, "混音台提交口不是 M / S / 音量那三处");
assert.match(mixer, /\{ volume: want \}, "调整轨道音量"/, "音量没走同一条 track.update");
assert.match(mixer, /solo: !track\.solo/, "S 没走 track.update solo");
assert.match(mixer, /muted: !track\.muted/, "M 没走 track.update muted");

// ④ 独奏只摆在声音轨上。
const menu = timeline.slice(timeline.indexOf("const trackMenu"), timeline.indexOf("  return (", timeline.indexOf("const trackMenu")));
assert.ok(menu.length > 0, "找不到轨道菜单的构造处");
const audioAt = menu.indexOf('if (track.kind === "audio")');
const soloAt = menu.indexOf("取消独奏");
assert.ok(audioAt >= 0 && soloAt > audioAt, "独奏那一条不在「声音轨」那一支里");

// ⑤ 类型与样式。
assert.match(engine, /solo\?: boolean;/, "界面类型里没有 solo");
assert.match(engine, /track_volume_max\?: number/, "能力类型里没有 track_volume_max");
const rule = /\.mixer-row \{([^}]*)\}/.exec(css);
assert.ok(rule, "样式表里没有 .mixer-row");
assert.match(rule![1], /display: grid/, "混音一行不是网格");
assert.match(rule![1], /grid-template-columns:[^;]*26px[^;]*26px/, "M/S 两颗不在同一行");
assert.doesNotMatch(rule![1], /font-size:\s*\d/, "混音行自己写了一档字号");
assert.match(css, /\.mixer-value \{[^}]*font-size: var\(--fs-label\)/, "百分数没有走刻度");

console.log(
  "PASS: 轨道混音只有一套规则——solo 进契约与能力位、静音优先只在 track_audible 一处判、" +
    "预览清单与导出一同读它、滑杆上限读能力表且松手才提交、独奏只摆在声音轨、混音一行不叠小字",
);
