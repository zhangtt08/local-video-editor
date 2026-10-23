/** 复制／粘贴动画关键帧：搬的是节奏，落库仍是普通 `keyframe.set`，一条批次一个 revision。

 边界写在 `keyframeClipboard.ts` 的注释里，这里逐条量：一次只搬一条属性、越界与撞针逐枚跳过并报数、
 复制不跨工程、撞针的判断读的是**片段本地**刻度（已有的针存的是含 `animation_offset_ticks` 的时钟）。
 还断一条我自己差点写错的东西：Ctrl+A 那个守卫的括号——`a || b && c` 与 `(a || b) && c` 不是一回事，
 写漏了括号就成了「按一下 Ctrl 就全选」。

 1.212 起那一层的针也能跨片段搬，所以这里多量一整段：一份复制的身份是（层序, 属性）而不是属性名
 （层的 `scale` 与片段自己的 `scale` 撞名，只认名字就会把针写进另一条曲线上）、值**照搬不重折**
 （引擎那张带子 `LAYER_KEY_LIMITS` 只按属性分，源上被收下过的数在目标上必然还在带内）、撞针按
 那一道曲线判而额度按**整层**判、一枚都没粘上就一条命令都不发（空操作不许进撤销台）。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { copyIdentity, copyKeys, copyMatches, copiedKeys, layerPasteDetail, pasteInto, pasteKeys, pasteLayerKeys, rememberCopy } from "../desktop/src/keyframeClipboard";
import { isCopiedKeys } from "../desktop/src/clipboardStore";
import type { Keyframe } from "../desktop/src/engine";

const TIMEBASE = 70_560_000;
const FRAME = Math.floor(TIMEBASE / 30);
const key = (property: string, at: number, extra: Partial<Keyframe> = {}): Keyframe => ({
  property: property as Keyframe["property"], at_ticks: at, value: 0.5, interpolation: "ease", bezier: null, ...extra,
});
const target = (keys: Keyframe[], duration = FRAME * 10, offset = 0) => ({ id: "c2", duration_ticks: duration, animation_offset_ticks: offset, keyframes: keys });

// 复制的门槛：没选中、跨属性，都不给一份「看起来能粘」的东西。
assert.equal(copyKeys("p1", []), null, "an empty selection copies nothing");
assert.equal(copyKeys("p1", [key("opacity", 0), key("gain", FRAME)]), null, "a mixed selection must not half-copy a curve");
const source = [key("opacity", FRAME * 2), key("opacity", FRAME * 5), key("opacity", FRAME * 6, { value: 0.9, interpolation: "bezier", bezier: { x1: 0.2, y1: 0, x2: 0.8, y2: 1 } })];
const copy = copyKeys("p1", source);
assert.ok(copy && copy.property === "opacity" && copy.base === FRAME * 2 && copy.keys.length === 3, "the first needle is the base the spacing is measured from");
source[0].value = 0.1;
assert.equal(copy!.keys[0].value, 0.5, "the copy is a snapshot, not a live reference into project state");

// 粘贴保持相对节奏，跨片段也照粘（落库的命令是普通 keyframe.set，带目标片段的 id）。
const paste = pasteKeys(target([]), copy, FRAME * 1, "p1");
assert.equal(paste.pasted, 3, "all three land");
assert.deepEqual(paste.commands.map((c) => c.op), ["keyframe.set", "keyframe.set", "keyframe.set"], "one ordinary command per needle");
assert.deepEqual(paste.commands.map((c: any) => c.keyframe.at_ticks), [FRAME, FRAME * 4, FRAME * 5], "the spacing is preserved");
assert.equal((paste.commands[0] as any).clip_id, "c2", "and it goes to the clip in front of the user, not the one copied from");
assert.deepEqual((paste.commands[2] as any).keyframe.bezier, { x1: 0.2, y1: 0, x2: 0.8, y2: 1 }, "handles ride along");
assert.equal(paste.reason, "", "a clean paste has nothing to complain about");

// 越界与撞针：逐枚跳过并数出来，而不是整批失败，也不是悄悄挪位。
const clipped = pasteKeys(target([]), copy, FRAME * 8, "p1");
assert.equal(clipped.pasted, 1, "only the first needle still fits inside the clip");
assert.equal(clipped.dropped, 2, "and the two that fall past the end are counted");
assert.match(clipped.reason, /跳过 2/, `the reason must carry the number: ${clipped.reason}`);
const blocked = pasteKeys(target([key("opacity", FRAME * 1 + 0)]), copy, FRAME, "p1");
assert.equal(blocked.pasted, 2, "the occupied second is skipped, the rest still paste");
assert.equal(blocked.dropped, 1, "and counted");
// 已有的针存的是含偏移的时钟：撞针必须按片段本地刻度判。
const offsetTarget = target([key("opacity", 5_000 + FRAME)], FRAME * 10, 5_000);
const offsetPaste = pasteKeys(offsetTarget, copy, FRAME, "p1");
assert.equal(offsetPaste.pasted, 2, "an existing needle at stored tick 5000+frame blocks local frame");
const nothing = pasteKeys(target(source.map((k) => key("opacity", k.at_ticks))), copy, copy!.base, "p1");
assert.equal(nothing.commands.length, 0, "a fully blocked paste sends nothing");
assert.match(nothing.reason, /没有粘贴/, `and says so: ${nothing.reason}`);

// 复制不跨工程：换了工程就失效，而不是把针粘进别人的片段上。
assert.equal(pasteKeys(target([]), copy, 0, "p2").reason, "换了工程，之前复制的那段已失效");
assert.match(pasteKeys(target([]), null, 0, "p1").reason, /还没有复制/);

// ── 1.212：那一层的针跨片段搬。身份是（层序, 属性），值照搬，额度按整层数。
const OFFSET = 5_000;
const layerCopy = copyKeys("p1", [key("scale", FRAME * 2), key("scale", FRAME * 5), key("scale", FRAME * 6, { value: -0.3, interpolation: "bezier", bezier: { x1: 0.2, y1: 0, x2: 0.8, y2: 1 } })], 0)!;
// 层的 `scale` 与片段自己的 `scale` 撞名：两份复制的身份必须不同，否则就把层的针写进片段自己的曲线。
assert.equal(copyIdentity(layerCopy), "layer0:scale", "a layer copy is identified by ordinal plus property");
assert.equal(copyIdentity(copy!), "opacity", "a clip-own copy keeps the plain name");
assert.ok(copyMatches(layerCopy, { property: "layer0:scale" }, 24), "the layer row matches its own copy");
assert.ok(!copyMatches(layerCopy, { property: "scale" }, 24), "the clip-own 缩放 row must NOT match a layer copy");
assert.ok(!copyMatches(copy!, { property: "layer0:scale" }, 24), "and not the other way round");
assert.ok(!copyMatches(null, { property: "layer0:scale" }, 24), "nothing in hand matches nothing");
assert.ok(!copyMatches(layerCopy, { property: "layer0:scale" }, undefined), "no engine quota means the hand is withheld");
assert.ok(copyMatches(copy!, { property: "opacity" }, undefined), "the quota only gates layer copies");

/** 一段带着「第二路画面」那一层的片段：链里节点的针存的是含偏移的时钟。 */
const layerClip = (keys: any[], duration = FRAME * 10, offset = OFFSET) => ({
  id: "c2", duration_ticks: duration, animation_offset_ticks: offset,
  color: { grade: [{ kind: "layer", enabled: true, asset_id: "a2", keys }] },
} as any);
const gradeKeys = (command: any) => command.grade[0].keys;

const lifted = pasteInto(layerClip([]), layerCopy, FRAME * 1, "p1", 24);
assert.equal(lifted.pasted, 3, "all three ride over");
assert.deepEqual(lifted.commands.map((c: any) => c.op), ["clip.grade"], "a layer paste is the one whole-chain command, never keyframe.set");
assert.deepEqual(lifted.commands.map((c: any) => c.clip_id), ["c2"], "and it names the clip in front of the user");
assert.deepEqual(gradeKeys(lifted.commands[0]).map((k: any) => k.at_ticks), [OFFSET + FRAME, OFFSET + FRAME * 4, OFFSET + FRAME * 5], "spacing preserved, offset folded back exactly once");
// 值照搬：一个数都不重折、不夹、不量化——带子只按属性分，源上被引擎收下过的数在目标上还在带内。
assert.deepEqual(gradeKeys(lifted.commands[0]).map((k: any) => k.value), [0.5, 0.5, -0.3], "the numbers are copied, not re-folded");
assert.deepEqual(gradeKeys(lifted.commands[0])[2].bezier, { x1: 0.2, y1: 0, x2: 0.8, y2: 1 }, "handles ride along here too");
assert.equal(lifted.reason, "", "a clean layer paste has nothing to complain about");

// 同层别的数一字不动（那是 `layerKeyCommand` 的契约，粘贴这一路也照样守）。
const neighbours = pasteInto(layerClip([{ property: "offset_x", at_ticks: OFFSET + FRAME * 4, value: 0.2 }]), layerCopy, FRAME * 1, "p1", 24);
assert.equal(gradeKeys(neighbours.commands[0]).length, 4, "the layer's other property keeps its needle");
assert.deepEqual(gradeKeys(neighbours.commands[0]).find((k: any) => k.property === "offset_x"), { property: "offset_x", at_ticks: OFFSET + FRAME * 4, value: 0.2 }, "and that needle is written back untouched");
// 撞针按**那一道曲线**判：别的数占了那一格不算撞（引擎 LAYER_KEY_CLASH 认的是同一格同一条属性两枚）。
assert.equal(neighbours.pasted, 3, "a neighbouring property on the same tick does not block the paste");
// 同一道的针就挡：逐枚跳过并报数。
const clash = pasteInto(layerClip([{ property: "scale", at_ticks: OFFSET + FRAME * 4, value: 0.1 }]), layerCopy, FRAME * 1, "p1", 24);
assert.equal(clash.pasted, 2, "the occupied second is skipped");
assert.equal(clash.dropped, 1, "and counted");
assert.match(clash.reason, /跳过 1/, `the reason carries the number: ${clash.reason}`);
// 越出片段两头：与片段自己那一路同一个判法。
const overrun = pasteInto(layerClip([]), layerCopy, FRAME * 8, "p1", 24);
assert.equal(overrun.pasted, 1, "only the first still fits");
assert.equal(overrun.dropped, 2, "the rest fall past the end");
// 额度按**整层**数（这一层所有属性加起来的针），不是按这一道曲线。
const crowded = layerClip([{ property: "offset_x", at_ticks: OFFSET + FRAME, value: 0.2 }, { property: "mix", at_ticks: OFFSET + FRAME * 2, value: 0.4 }]);
const tight = pasteInto(crowded, layerCopy, 0, "p1", 3);
assert.equal(tight.pasted, 1, "the layer has room for one more needle in total");
assert.equal(tight.dropped, 2, "and the other two are skipped, not squeezed in");
assert.match(tight.reason, /那一层 3 枚的额度/, `the reason names the ceiling it ran into: ${tight.reason}`);
// 一枚都没粘上就一条命令都不发：撤销台上不许留一步「写了但什么都没改」（1.211 量过那一笔）。
assert.equal(pasteInto(crowded, layerCopy, 0, "p1", 2).commands.length, 0, "a quota already spent sends nothing");
assert.match(pasteInto(crowded, layerCopy, 0, "p1", 2).reason, /没有粘贴/, "and says so");
assert.match(pasteLayerKeys(layerClip([]), null, 0, "p1", 24).reason, /还没有复制过层的针/, "nothing in hand names the hand that would fill it");
assert.equal(pasteInto(layerClip([]), layerCopy, 0, "p2", 24).reason, "换了工程，之前复制的那段已失效", "a layer copy does not cross projects either");
// 说差别的那一句带得住层序，也带得住「照搬不重折」这个判断。
assert.match(layerPasteDetail(1), /第 2 层那个数照搬过去、没有重折/, "the difference sentence is about the number, not the gesture");
assert.match(layerPasteDetail(1), /不是同一个画面/, "and it says why the same number is not the same picture");

// 跨重启那份复制的形状：带了层序就必须是个从 0 数过去的整数，半份都不算（`pasteInto` 按它分流）。
assert.ok(isCopiedKeys({ projectId: "p1", property: "scale", layer: 0, base: 0, keys: [] }), "a layer copy round-trips");
assert.ok(isCopiedKeys({ projectId: "p1", property: "opacity", base: 0, keys: [] }), "and so does the plain one");
assert.ok(!isCopiedKeys({ projectId: "p1", property: "scale", layer: -1, base: 0, keys: [] }), "a negative ordinal is not a layer");
assert.ok(!isCopiedKeys({ projectId: "p1", property: "scale", layer: 1.5, base: 0, keys: [] }), "nor is a fraction");
assert.ok(!isCopiedKeys({ projectId: "p1", property: "scale", layer: "0", base: 0, keys: [] }), "nor a string");

// 那份复制跟着应用走，不跟着组件走。
rememberCopy(copy);
assert.equal(copiedKeys()?.keys.length, 3, "leaving the curve editor and coming back keeps the copy");
rememberCopy(null);
assert.equal(copiedKeys(), null, "and it can be dropped");

// 接线：两个快捷键都走这一处判断，落库走带 expected_revision 的那条链。
const path = ["desktop/src/views/CurveEditor.tsx", "src/views/CurveEditor.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the curve editor must be readable from the check's working directory");
const curve = readFileSync(path!, "utf8");
assert.match(curve, /const pasteNow = \(\) => \{[\s\S]{0,240}pasteInto\(clip, copied, alignTime\(head, false\), project\.id, layerKeyLimit\)/, "paste is one function: playhead落点、走共享格子、不找邻针，走哪条路由那份复制自己说");
assert.match(curve, /editAtRevision\(paste\.commands, project\.id, project\.revision, "粘贴动画关键帧", app\.sequenceId\)/, "the whole paste is one ordinary batch");
// 量出来的那条：复制完焦点还留在针上，紧跟的 Ctrl+V 会被浏览器吃掉，所以复制必须把焦点交回画布。
assert.match(curve, /rememberCopy\(copy\);[\s\S]{0,40}svg\.current\?\.focus\(\);/, "copy hands focus back to the plot so the very next Ctrl+V lands");
// 鼠标必须也有一条路：自动化里 Chromium 会吃掉 Ctrl+V（实测一次到达、一次不到达），快捷键不能是唯一入口。
assert.match(curve, /onClick=\{pasteNow\}>粘贴/, "a paste button must exist next to the chord");
assert.match(curve, /disabled=\{disabled \|\| !copyMatches\(copied, field, layerKeyLimit\)\}/, "and it is grey unless a copy whose **whole identity** (层序＋属性) matches the current row is in hand");
// 1.212：那一路拒绝必须真的不在了——「这一层的针还不能跨片段搬」是本轮要做掉的那件事，
// 留着它就说明接线只是看着像改了（整文件某处还有这个词不算数：认的是那一句 toast）。
assert.doesNotMatch(curve, /这一层的针还不能跨片段搬/, "the refusal this round replaced must be gone");
assert.match(curve, /copyKeys\(project\.id, selectedKeys, layerField\?\.layer\)/, "copy carries the layer ordinal, not just the property name");
assert.match(curve, /toast\(paste\.dropped \? "warn" : "info"[\s\S]{0,220}layerPasteDetail\(copied\.layer\)\)/, "a clean layer paste says the difference out loud");
assert.equal((curve.match(/粘贴动画关键帧/g) ?? []).length, 1, "the chord and the button share one implementation");
// 层的额度听引擎的，界面不许自带一个数（`LAYER_KEY_LIMIT` 变了这里就得跟着红）。
assert.match(curve, /const layerKeyLimit = app\.caps\?\.limits\?\.layer_key_limit;/, "the quota is read from capabilities, not hardcoded");
// 1.266：那一处拒绝不再把契约键名念给人看（`capabilities.limits.layer_key_limit` 换成了
// 「那一个数随能力表交下来」），所以这个数从 2 收到 1——**读的那一处**仍是唯一的一处。
// 上一版把 2 钉着，钉的正是「拒绝里再念一遍键名」那个旧形状。
assert.equal((curve.match(/layer_key_limit/g) ?? []).length, 1, "and read in exactly one place, nowhere named to a person");
// 复制、粘贴、全选是这一层的三个和弦入口；Ctrl+A 那个守卫的括号必须留着，
// 否则 `a || b && c` 的结合顺序会变成「按一下 Ctrl 就全选」。
assert.match(curve, /if \(\(e\.ctrlKey \|\| e\.metaKey\) && e\.key\.toLowerCase\(\) === "a"\)/, "the select-all guard keeps its parentheses");
// 同一类错误有三个入口，所以三个都断：漏掉括号的就是 `a || (b && c)`，按一下 Ctrl 就全选／全复制／全粘贴。
assert.equal((curve.match(/if \(\(e\.ctrlKey \|\| e\.metaKey\) && e\.key\.toLowerCase\(\) === "[acv]"\)/g) ?? []).length, 3,
  "all three chords must guard with parentheses");
assert.equal((curve.match(/key\.toLowerCase\(\) === "[cav]"/g) ?? []).length, 3, "copy, paste and select-all are the three chord entries");

console.log("PASS: 复制／粘贴搬的是节奏——一次一条属性、跨片段照粘（层的针连着层序一起认，值照搬不重折）、"
  + "越界与撞针逐枚跳过并报数、那一层的额度按整层数、一枚都没粘上就一条命令都不发、"
  + "撞针按片段本地刻度判、复制不跨工程、一贴就是一条批次一个 revision");
