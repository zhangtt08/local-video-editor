/** A refusal the interface shows has to say which file, clip, track or composition it means.

 `explain()` deliberately replaces the engine's English message with a Chinese sentence naming the
 next action. That is only useful if the sentence still carries the target: "素材原文件已被移动或删除"
 across a library of forty assets asks the editor to guess. 1.75 put `clip_id` / `asset_id` /
 `asset_label` / `track_id` / `sequence_id` into every analysis refusal's `details`, and this pins
 that the shell weaves them in — and stays silent when there is nothing to name.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

declare const REPO_ROOT: string;

import { EngineError, errorHints, saidRefusal } from "../desktop/src/engine";
import { refusalLines } from "../desktop/src/attributePaste";

const missing = new EngineError(
  "MEDIA_MISSING",
  "source file is gone",
  { clip_id: "s", asset_id: "tone", asset_label: "tone.mp4" },
  410,
);
const shown = missing.explain();
assert.ok(shown.includes("素材原文件已被移动或删除"), `the Chinese hint must survive, got: ${shown}`);
assert.ok(shown.includes("tone.mp4"), `the refusal must name the file, got: ${shown}`);
assert.ok(shown.includes("片段 s"), `and the clip that could not read it, got: ${shown}`);
assert.ok(!shown.includes("素材 tone（"), `the asset id must not repeat behind its own name: ${shown}`);

const ghost = new EngineError("NOT_FOUND", "clip is not in this project", { clip_id: "s" }, 404);
const where = ghost.explain();
assert.ok(where.includes("片段 s"), `a missing clip must be named: ${where}`);
assert.ok(where.includes("合成"), `and the way back to it must be said in Chinese: ${where}`);
assert.ok(!/^[a-z ]+$/.test(where), `an analysis refusal must not reach the editor in English: ${where}`);

// The eleven codes the analysis routes answer with had no Chinese sentence at all before 1.75, so
// the toast showed the engine's English text. Each one now has to say what to do instead.
for (const code of [
  "NOT_FOUND",
  "INVALID_SILENCE_TARGET",
  "INVALID_LOUDNESS_TARGET",
  "INVALID_REFRAME",
  "INVALID_DUCK",
  "DUCK_PLAN_TOO_LARGE",
  "INVALID_TRACK_TARGET",
  "TRACK_FAILED",
  "INVALID_SPEED",
  "PROJECT_LIMIT",
  "TIME_OVERFLOW",
  // 1.81: a sample from every family that used to fall through to English. The vocabulary gate
  // checks all 116 codes exist; this checks the runtime path actually speaks Chinese for them.
  "MEDIA_NOT_FOUND",
  "MEDIA_PATH_INVALID",
  "PROBE_NOT_FOUND",
  "LOUDNESS_FAILED",
  "SPEECH_NOT_FOUND",
  "SUBTITLES_MODEL_MISSING",
  "INVALID_SPLIT",
  "INVALID_MARKER_SPLIT",
  "NOT_ADJACENT",
  "DUPLICATE_ID",
  "REVISION_OVERFLOW",
  "OUTPUT_INVALID",
  "UNKNOWN_PRESET",
  "FONT_UNAVAILABLE",
]) {
  const said = new EngineError(code, "source file is gone", {}, 422).explain();
  assert.notEqual(said, "source file is gone", `${code} still shows the engine's English`);
  assert.ok(/[一-鿿]/.test(said), `${code} must answer in Chinese: ${said}`);
  assert.ok(said.length > 12, `${code} is too thin to act on: ${said}`);
}

const bare = new EngineError("TRACK_LOCKED", "track is locked", {}, 422);
assert.equal(
  bare.explain(),
  "轨道已锁定，请解锁或选择其他目标轨道。",
  `a hint with nothing to name must not grow empty brackets: ${bare.explain()}`,
);

// 引擎自己已经说中文的那一类拒绝（时间码点名是哪一段数字不对），具体那半句不能被通用提示盖掉。
const specific = new EngineError(
  "TIMECODE_INVALID",
  "时间码 '01:60:00:00' 不能用：分钟最多 59，收到 60。写法 HH:MM:SS:FF",
  { value: "01:60:00:00" },
  422
);
assert.ok(specific.explain().includes("分钟最多 59"), `the engine's own detail was overwritten: ${specific.explain()}`);
// 引擎只说英文时，中文那句仍是人看到的——这条是 1.75 以来的老规矩，不许被上面那半句带走。
const english = new EngineError("TRACK_LOCKED", "track is locked", {}, 422);
assert.equal(english.explain(), "轨道已锁定，请解锁或选择其他目标轨道。", "english message lost its hint");

const unknown = new EngineError("SOMETHING_NEW", "the engine said this", {}, 422);
assert.equal(unknown.explain(), "the engine said this", "an unhinted code shows the engine's words");

// 1.265：`PROJECT_LIMIT` 过去交回的是「project exceeds the supported contract limits」加一份空的
// details，而界面那句中文给的出路是「把长段落拆成几条片段」——那一下只会让片段更多。两头现在都改：
// 引擎点名是哪一格与两个数，界面念出那一格、两个数，并且只指真减得下数的出路。
const crowded = new EngineError(
  "PROJECT_LIMIT",
  "clips rejected by the contract: Dictionary should have at most 20000 items after validation, not 20001",
  { contract_path: "clips", reason: "too_long", max_length: 20000, actual_length: 20001 },
  422,
);
const advice = crowded.explain();
assert.ok(advice.includes("最多 20000"), `那两个数得让人看得见：${advice}`);
assert.ok(advice.includes("现在要存 20001"), `这一次要存的数也得带出来：${advice}`);
assert.ok(advice.includes("这一格片段"), `契约字段名要念成中文那一面：${advice}`);
assert.ok(!advice.includes("clips"), `不许把契约里的字段名原样印给人：${advice}`);
assert.ok(!advice.includes("拆成几条片段"), `不许再指那条只会让片段更多的手：${advice}`);
assert.ok(advice.includes("删掉"), `上限那句得说一条真减得下数的出路：${advice}`);
// 反向：数字不在 details 里时不许编一个数出来。
const plain = new EngineError("PROJECT_LIMIT", "no numbers here", {}, 422);
assert.ok(!plain.explain().includes("最多"), `没有数就不许说一句带数的话：${plain.explain()}`);

// 1.266：上限那一对数到人眼前——不止契约那一格。
// 量具（`refusal_numbers_1266b.py`）量到的是：引擎在 `details` 里给了 `limit` 与「现在几个」，
// 而界面那句中文一个数都没提。这一节把「织进去」与「故意不织」两头都钉住。
const full = new EngineError(
  "MASK_SHAPE_LIMIT",
  "this mask already carries 32 outlines: delete one, or split the clip and animate each part",
  { clip_id: "c", outlines: 32, limit: 32, at_ticks: 70560000 },
  422,
);
const fullSaid = full.explain();
assert.ok(fullSaid.includes("轮廓帧：最多 32，现在 32"), `轮廓帧那两个数得看得见：${fullSaid}`);
assert.ok(fullSaid.includes("片段 c"), `还得点名是哪一条片段：${fullSaid}`);
assert.ok(!fullSaid.includes("at_ticks"), `内部刻度名不许进人眼：${fullSaid}`);

const budget = new EngineError(
  "GRADE_INLINE_BUDGET",
  "the project's inline lookup tables would hold 214000 samples and the budget is 200000",
  // 夹具挑的是真可能出现的那一格：一张 66³ 的表自己就顶穿了额度，所以「最占地方那一张」
  // 与「整份工程加起来」是两个都越过上限的数——织错了就是给人一个假的实际数。
  { samples: 214000, limit: 200000, worst_clip_id: "c", worst_clip_samples: 240000 },
  422,
);
const budgetSaid = budget.explain();
// 先判那一个 hazards：织错数时红的必须是这一句，而不是下面那句「得说出来」。
// 顺序也是判据的一部分（1.120 那一课）——把这条放在后面，织错数就只红在邻近的那句上，读的人看不出是谁坏。
assert.ok(!budgetSaid.includes("现在 240000"), `不许把「哪张表最占地方」那一个数织成实际数：${budgetSaid}`);
assert.ok(budgetSaid.includes("采样点：最多 200000，现在 214000"), `整份额度那两个数得说出来：${budgetSaid}`);

// 故意不织的那一格：`nodes=6` 没越过 `limit=8`，可这一格的真理由是「还剩 0 个位置、这一对要 2 个」。
// 界面要是把「最多 8，现在 6」织上去，那句话与这句拒绝自己就互相矛盾了。
const manage = new EngineError(
  "COLOR_MANAGE_LIMIT",
  "the pair needs two of the 8 slots a chain may hold, and this chain still keeps 6 nodes",
  { clip_id: "c", limit: 8, nodes: 6, room: 0 },
  422,
);
const manageSaid = manage.explain();
assert.ok(!manageSaid.includes("最多 8"), `放不下不等于越界，不许织这一对数：${manageSaid}`);
assert.ok(/[一-鿿]/.test(manageSaid), `不织数也得说中文：${manageSaid}`);

// 引擎自己说中文时不能再补一遍：那两个数已经在那句里了，第二次出现就是同一句话讲两次。
const double = new EngineError(
  "LAYER_KEY_LIMIT",
  "这一层带了 25 枚针，引擎收的是 24 枚：少钉几枚",
  { keys: 25, limit: 24 },
  422,
);
const doubleSaid = double.explain();
assert.equal(doubleSaid, double.message, `引擎已经说中文又把数补一遍：${doubleSaid}`);

// 「粘贴属性」那一行报的拒绝：过去它优先用界面那张提示表，于是引擎那句带两个数的中文被顶掉。
// 现在它与 `explain()` 共用同一处说法——这条断言量的就是「同一处」。
const pastePlan = {
  all_categories: [{ category: "mask", label: "遮罩" }],
  categories: [{ category: "mask", label: "遮罩" }],
  refusals: [
    {
      clip_id: "c2",
      category: "mask",
      code: "MASK_SHAPE_LIMIT",
      message: "this mask already carries 32 outlines",
      details: { clip_id: "c2", outlines: 32, limit: 32 },
    },
  ],
};
const [pasteLine] = refusalLines(pastePlan as unknown as Parameters<typeof refusalLines>[0]);
assert.ok(pasteLine.includes("轮廓帧：最多 32，现在 32"), `粘贴那行也得带出两个数：${pasteLine}`);
assert.ok(
  pasteLine.endsWith(saidRefusal("MASK_SHAPE_LIMIT", "this mask already carries 32 outlines",
    { clip_id: "c2", outlines: 32, limit: 32 })),
  `粘贴那行与界面别处的报错不再是两句话：${pasteLine}`,
);
const chineseEngine = {
  all_categories: [],
  categories: [],
  refusals: [{
    clip_id: "c9", category: null, code: "TRACK_LOCKED",
    message: "这条片段所在的轨道被锁住了，先解锁再改", details: {},
  }],
};
const [engineLine] = refusalLines(chineseEngine as unknown as Parameters<typeof refusalLines>[0]);
assert.ok(engineLine.includes("先解锁再改"), `引擎自己说中文时那一句不能被通用提示顶掉：${engineLine}`);

// 契约路径不再念给人听：那张提示表是全仓唯一面向人的句子表，里面一处点分路径都不许有。
// 这一判认的是「两个 ASCII 标识符中间一个点」那个形状，不是任何带点的东西——
// `MEDIA_PATH_INVALID` 那句里的 `a.mp4` 是给人看的文件名例子，把它当违规就是把尺子架错了地方。
const CONTRACT_PATH = /[a-z_]{3,}\.[a-z_]{5,}/;
for (const [code, sentence] of Object.entries(errorHints())) {
  assert.ok(!CONTRACT_PATH.test(sentence), `${code} 那句里印了契约路径：${sentence}`);
  assert.ok(!sentence.includes("/v1/"), `${code} 那句里印了接口路由：${sentence}`);
}

// 同一件事管到**界面上会念出来的那几处句子**（检查器状态行与 toast），不是只管提示表：
// 1.266 第二半量到的那四处就是住在 `gamutFold` / `CurveEditor` 的返回字符串里。
// 判法按「那一个键名在这份文件里一次都不出现」——属性访问写的是 `caps?.limits?.…`（点号前带 `?`），
// 本来就不是这个形状，所以这一判不会误伤代码；注释一起改口，是为了让反向钉简单（1.265 那课：
// 数针的尺会数到注释，那就让注释与句子说同一句话）。
// 帮助页（`Help.tsx`）故意不在这张表里：那一页是本仓写下「这句话的出处是哪一张表」的地方，
// 28 处键名是它既定写法；要不要把那一页也收成不印键名，是 1.267 要定的判断，不是这里顺手改的口径。
const renderer = (relative: string): string => {
  const path = REPO_ROOT.endsWith("/") ? REPO_ROOT + relative : `${REPO_ROOT}/${relative}`;
  return readFileSync(path, "utf8");
};
for (const [file, keys] of [
  ["desktop/src/gamutFold.ts", ["capabilities.gamut_matrices"]],
  ["desktop/src/views/CurveEditor.tsx",
    ["grade_limits.layer_key_bands", "capabilities.limits.layer_key_limit"]],
] as const) {
  const source = renderer(file);
  for (const key of keys) {
    assert.ok(!source.includes(key), `${file} 又把契约键名念给人看：${key}`);
  }
}
// 帮助页那次改口针对的是**写死的段数**（64 住在契约里，界面抄第二份就会与它分家）。
assert.ok(!renderer("desktop/src/views/Help.tsx").includes("一次最多搬 64 段"),
  "帮助页又把段数写死了一遍");

console.log(
  "PASS: the shell weaves the named file, clip, track or composition into every Chinese hint, the "
  + "eleven analysis refusals all answer in Chinese with a way out, nothing is added when the "
  + "engine named no target, the ceiling pair reaches the person (and is withheld where it would "
  + "contradict the refusal), the paste report says it with the same one implementation, and no "
  + "hint prints a contract path, the same rule holds for the inspector and toast sentences that "
  + "return a refusal, and the help page no longer copies a ceiling the contract owns",
);
