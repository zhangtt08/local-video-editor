/** 针得说中文：属性名只有一处表（`effects.ts` 的 `FIELD_LABEL`），而这张表跟着引擎的词表走。

 缺陷是看出来的：整个界面是中文的，可时间线上那枚菱形 hover 上去写的是 `opacity · 0:01.000`，检查器里
 插值下拉的无障碍名是 `opacity关键帧插值`，撞针的红字是 `opacity 在第 0.113 秒已经有一枚针`，「+N」牌子
 列的也是 `rotation、blur`。同一份状态在关键帧列表里明明已经叫「不透明度」了——名字不是缺的，是漏接的。
 这里断两件事：界面每一句「说到某条属性」的话都从 `FIELD_LABEL` 出去（不再就地插 contract 的 id），以及
 `FIELD_LABEL` 的键与引擎 `contracts.py` 里那三条 `Literal` 一字不差——多一条属性没起名、少一条属性还留着
 旧名，都会在这里红，而不是等用户 hover 出一串英文。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { FIELD_LABEL } from "../desktop/src/effects";
import { planKeyframeDrag } from "../desktop/src/keyframeDrag";

const read = (parts: string[]): string => {
  const path = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(path, `one of ${parts.join(" or ")} must be readable from the check's working directory`);
  return readFileSync(path!, "utf8");
};

// 词表跟着引擎走：契约里那三条 Literal 就是界面能见到的全部属性，一条不多一条不少。
const contracts = read(["../src/agentcut/contracts.py", "src/agentcut/contracts.py"]);
const vocabulary = ["EffectProperty", "MaskProperty", "SpatialProperty"].flatMap((name) => {
  const declared = new RegExp(`^${name} = Literal\\[([^\\]]*)\\]`, "m").exec(contracts);
  assert.ok(declared, `${name} must stay a Literal the check can read`);
  return [...declared[1].matchAll(/"([^"]+)"/g)].map((found) => found[1]);
});
assert.ok(vocabulary.length >= 11, `the contract must still name every animatable property, saw ${vocabulary.length}`);
for (const property of vocabulary) {
  assert.ok(FIELD_LABEL[property], `${property} has no Chinese name — the UI would say the contract id`);
  assert.match(FIELD_LABEL[property], /[\u4e00-\u9fff]/, `${property}'s label must be Chinese`);
}
for (const named of Object.keys(FIELD_LABEL)) {
  assert.ok(vocabulary.includes(named), `${named} is not a property the engine knows: the label table is stale`);
}
assert.equal(new Set(Object.values(FIELD_LABEL)).size, Object.values(FIELD_LABEL).length,
  "two properties sharing one name would make 「那一格已经有一枚针」说不清是哪条曲线");

// 撞针的理由是这条表的实际用法：它交给 toast 的那句话不许再出现英文 id。
const FRAME = Math.floor(70_560_000 / 30);
const held = { property: "opacity" as const, at_ticks: 5_000 + 30_000, value: 0.4, interpolation: "ease" as const, bezier: null };
const neighbour = { ...held, at_ticks: 5_000 + 8_000_000 };
const clip = {
  id: "clip-name", track_id: "t", asset_id: "a", kind: "video", position_ticks: 0,
  duration_ticks: 20 * FRAME, source_in_ticks: 0, source_duration_ticks: 20 * FRAME,
  animation_offset_ticks: 5_000, keyframes: [held, neighbour],
};
const blocked = planKeyframeDrag({
  clip: clip as never, key: held as never, pointer_ticks: 8_000_000, playhead_ticks: -1,
  px: 62, snap: true, quantum: FRAME,
});
assert.equal(blocked.kind, "blocked", "the same-property neighbour must still be what is refused");
if (blocked.kind === "blocked") {
  assert.ok(blocked.reason.includes(FIELD_LABEL.opacity), `the refusal must say 不透明度: ${blocked.reason}`);
  assert.ok(!blocked.reason.includes("opacity"), `the contract id must not reach the user: ${blocked.reason}`);
}

// 接线：每一句说到属性的话都从那张表出去，旧的英文插法一条都不留。
const timeline = read(["desktop/src/views/Timeline.tsx", "src/views/Timeline.tsx"]);
assert.match(timeline, /const label = FIELD_LABEL\[k\.property\] \?\? k\.property;/, "the needle reads its name from the shared table");
assert.match(timeline, /title=\{`\$\{label\} · /, "and the tooltip starts with that name");
assert.match(timeline, /aria-label=\{`拖动\$\{label\}关键帧`\}/, "and so does the accessibility name");
assert.match(timeline, /moreLabels\.join\("、"\)/, "the 「+N」 chip names the rows it could not draw, in Chinese");
assert.match(timeline, /hidden\.map\(\(property\) => FIELD_LABEL\[property\] \?\? property\)/, "片段自己那些画不下的属性仍由 FIELD_LABEL 那一处念名字");
assert.match(timeline, /LAYER_KEY_LABEL\[row\.property\] \?\? row\.property/, "第二路画面那一层的行也由同一张名字表念，时间线不另抄一份");
assert.equal((timeline.match(/\$\{k\.property\} · |拖动\$\{k\.property\}关键帧|hidden\.join/g) ?? []).length, 0, "the raw-id spellings must be gone");

const curve = read(["desktop/src/views/CurveEditor.tsx", "src/views/CurveEditor.tsx"]);
assert.match(curve, /枚 \$\{FIELD_LABEL\[copy\.property\] \?\? copy\.property\} 关键帧/, "the copy toast names the property through the table");
assert.match(curve, /枚 \$\{FIELD_LABEL\[copied\.property\] \?\? copied\.property\} 针/, "and so does the paste button's hint");
assert.equal((curve.match(/枚 \$\{cop(?:ied)?\.property\}/g) ?? []).length, 0, "no raw id in those two sentences");

const inspector = read(["desktop/src/views/Inspector.tsx", "src/views/Inspector.tsx"]);
assert.match(inspector, /aria-label=\{`\$\{FIELD_LABEL\[k\.property\] \?\? k\.property\}关键帧插值`\}/, "the easing dropdown beside each needle is named in Chinese too");

const drag = read(["desktop/src/keyframeDrag.ts", "src/keyframeDrag.ts"]);
assert.match(drag, /const label = FIELD_LABEL\[clash\.property\] \?\? clash\.property;/, "the refusal is built from the same table");
assert.match(drag, /const one = `\$\{label\} 在第 /, "and it says that label first, before anything else in the sentence");
assert.equal((drag.match(/`\$\{drag\.key\.property\}/g) ?? []).length, 0, "and never from the contract id");

// 一处权威：界面不许再自带第二份属性名表（`desktop_blurcurve_check.ts` 已经断过这张表的柔焦那格）。
for (const [file, source] of [["Timeline.tsx", timeline], ["CurveEditor.tsx", curve], ["Inspector.tsx", inspector], ["keyframeDrag.ts", drag]] as const) {
  assert.ok(!/(const|type) [A-Za-z_]*LABEL[A-Za-z_]* *[:=]/.test(source), `${file} must not declare its own label table`);
}

console.log(
  "PASS: 针、复制／粘贴、撞针的红字与「+N」牌子说的都是中文——名字来自唯一那张 `FIELD_LABEL`，"
    + "而这张表的键与引擎契约里的三条 Literal 一字不差（多一条没起名、少一条留旧名都会红）",
);
