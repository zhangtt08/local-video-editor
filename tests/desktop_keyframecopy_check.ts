/** 复制／粘贴动画关键帧：搬的是节奏，落库仍是普通 `keyframe.set`，一条批次一个 revision。

 边界写在 `keyframeClipboard.ts` 的注释里，这里逐条量：一次只搬一条属性、越界与撞针逐枚跳过并报数、
 复制不跨工程、撞针的判断读的是**片段本地**刻度（已有的针存的是含 `animation_offset_ticks` 的时钟）。
 还断一条我自己差点写错的东西：Ctrl+A 那个守卫的括号——`a || b && c` 与 `(a || b) && c` 不是一回事，
 写漏了括号就成了「按一下 Ctrl 就全选」。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { copyKeys, pasteKeys, rememberCopy, copiedKeys } from "../desktop/src/keyframeClipboard";
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

// 那份复制跟着应用走，不跟着组件走。
rememberCopy(copy);
assert.equal(copiedKeys()?.keys.length, 3, "leaving the curve editor and coming back keeps the copy");
rememberCopy(null);
assert.equal(copiedKeys(), null, "and it can be dropped");

// 接线：两个快捷键都走这一处判断，落库走带 expected_revision 的那条链。
const path = ["desktop/src/views/CurveEditor.tsx", "src/views/CurveEditor.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the curve editor must be readable from the check's working directory");
const curve = readFileSync(path!, "utf8");
assert.match(curve, /copyKeys\(project\.id, selectedKeys\)/, "Ctrl+C copies the current selection");
assert.match(curve, /pasteKeys\(clip, copiedKeys\(\), alignTime\(head, false\), project\.id\)/, "Ctrl+V pastes at the playhead, on the shared lattice, without needle attraction");
assert.match(curve, /editAtRevision\(paste\.commands, project\.id, project\.revision, "粘贴动画关键帧", app\.sequenceId\)/, "the whole paste is one ordinary batch");
assert.match(curve, /if \(\(e\.ctrlKey \|\| e\.metaKey\) && e\.key\.toLowerCase\(\) === "a"\)/, "the select-all guard keeps its parentheses");
assert.equal((curve.match(/key\.toLowerCase\(\) === "[cav]"/g) ?? []).length, 3, "copy, paste and select-all are the three chord entries");

console.log("PASS: 复制／粘贴搬的是节奏——一次一条属性、跨片段照粘、越界与撞针逐枚跳过并报数、"
  + "撞针按片段本地刻度判、复制不跨工程、一贴就是一条批次一个 revision");
