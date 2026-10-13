/** 图像序列（EXR／DPX）在界面这一侧：交出的是一串文件，不是一文件。

 1.142 把两条序列加进引擎的预设表之后，界面有三处会开始说谎：① 预设下面那行字把「视频 / 音频」
 两路都念出来，而序列的 `audio_codec` 是空串，念出来就是一条空荡荡的斜杠；② 起始时间码那一栏
 照旧把人填的字符串发出去，而引擎对序列是**点名拒**的——点了「开始导出」才发现白跑一趟；
 ③ 文件名的提示说「引擎会按容器补上」，却没说补上之后得到的是一个目录加一串编号文件。

 跑的是真 `Engine` 导出的那几个函数（`codecText`／`matteAllowed`），再加上面板的接线检查。
 */

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = REPO_ROOT;

type Sent = { url: string; body: string | undefined };
const sent: Sent[] = [];
Object.assign(globalThis, {
  fetch: async (url: string, init: { method?: string; body?: string }) => {
    sent.push({ url: String(url), body: init.body });
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ job: { id: "j1" }, jobs: [], plan: {} }),
    };
  },
});

const { Engine, codecText, matteAllowed } = await import("../desktop/src/engine");
const engine = new Engine("http://127.0.0.1:1", "t".repeat(64));

const EXR = {
  id: "exr-sequence",
  label: "OpenEXR 图像序列（16 位，带 alpha）",
  container: "exr",
  codec: "exr",
  crf: null,
  encoder_preset: null,
  audio_codec: "",
  audio_bitrate: null,
  pixel_format: "rgba64le",
  profile: null,
  scale: null,
  alpha: true,
  sequence: true,
};
const MP4 = { ...EXR, id: "h264-1080p", container: "mp4", codec: "libx264", audio_codec: "aac", sequence: false };

// ① 那一行字不许骗人：序列没有声音那一路，就不念音频。
assert.equal(codecText(EXR as never), "OpenEXR 序列 · 每帧一个文件", "sequence-row-says-sequence");
assert.ok(!codecText(EXR as never).includes(" / "), "sequence-row-has-no-dangling-slash");
assert.equal(codecText(MP4 as never), "H.264 / AAC", "container-row-still-names-audio");
// 序列自己就带 alpha 层，「背景透明」那一勾对它当然有效——这不是新规矩，是不能被猜反。
assert.equal(matteAllowed(EXR as never, false, true), true, "sequence-can-carry-matte");

// ② 发出去的东西不需要任何新字段：preset id 就是全部信息，界面不为序列发明第二个开关。
await engine.render("p1", 3, "exr-sequence", "开链.exr", undefined, null, "contain", "full", false, null, null);
const seqBody = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(seqBody.preset_id, "exr-sequence", "preset-id-is-the-whole-message");
assert.equal(seqBody.filename, "开链.exr", "bare-name-goes-up");
await engine.render("p1", 3, "h264-1080p", "母版.mp4", undefined, null, "contain", "full", false, null, null);
const boxBody = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
// 序列的请求体与容器的请求体键一模一样：多一个键都没有，界面没有为它另开一条路。
assert.deepEqual(Object.keys(seqBody).sort(), Object.keys(boxBody).sort(), "sequence-body-is-container-body");

const engineSrc = readFileSync(SRC + "desktop/src/engine.ts", "utf8");
const panel = readFileSync(SRC + "desktop/src/views/ExportPanel.tsx", "utf8");

// ③ 引擎那句拒绝要有中文提示，而且必须指出走得通的出口（换成带容器的交付）。
const hint = engineSrc.match(/^\s{6}SEQUENCE_NEEDS_CONTAINER: "([^"]*)",\s*$/m);
assert.ok(hint, "hint-sequence-needs-container");
assert.match(hint[1] as string, /帧号就是位置/, "hint-explains-the-numbering");
assert.match(hint[1] as string, /mov／mp4／mxf／webm/, "hint-names-a-real-exit");

// 预设表里那一行 `sequence` 是引擎下发的，界面不另列一份 id 清单。
assert.match(engineSrc, /^\s{2}sequence\?: boolean;$/m, "preset-carries-the-flag");
assert.ok(!/exr-sequence/.test(panel), "panel-does-not-hardcode-a-sequence-list");

// 面板：真正发出去的时间码与念出来的「不写」是同一个值。
assert.match(panel, /const isSequence = Boolean\(preset\?\.sequence\);/, "panel-reads-the-flag");
assert.match(
  panel,
  /const sendTimecode = isSequence \? null : timecodeText\.trim\(\) \|\| null;/,
  "one-effective-timecode",
);
assert.match(panel, /disabled=\{Boolean\(blocked\) \|\| audioOnly \|\| isSequence\}/, "timecode-row-sits-out");
assert.ok(panel.includes("这一栏不起作用"), "panel-says-why-the-row-is-dark");
// 文件名的那行提示要说清补上后缀之后得到的是什么：一个目录加一串编号文件，而且没有声音。
assert.ok(panel.includes("每帧一个文件"), "filename-hint-says-one-file-per-frame");
assert.ok(panel.includes("声音不在里面"), "filename-hint-says-no-audio");

// 1.143：装机复核（在发布包取出的渲染层里真点一次）抓到——`Field` 的 hint 只挂在
// `<label title=…>` 上，鼠标不悬上去就一个字都看不见。序列这三句话不能只在悬停里。
const ui = readFileSync(SRC + "desktop/src/ui.tsx", "utf8");
assert.match(ui, /<label title=\{hint\}>/, "field-hint-is-only-a-tooltip");
assert.match(
  panel,
  /\{isSequence && \(\s*<p className="hint">[\s\S]{0,300}?声音不在里面[\s\S]{0,160}?起始时间码也进不去[\s\S]*?<\/p>\s*\)\}/,
  "sequence-note-is-visible",
);
assert.match(panel, /请再交一份 mp4／mov/, "visible-note-names-the-exit");

console.log(
  "PASS: 序列在界面这一侧说三句真话——预设那行念「OpenEXR 序列 · 每帧一个文件」（不再有空的斜杠），" +
    "时间码那一栏对序列不起作用且发出去的就是 null，文件名提示说明白这是一串文件且不带声音；" +
    "引擎的 SEQUENCE_NEEDS_CONTAINER 有中文提示并点名 mov／mp4／mxf／webm 那条出口",
);
