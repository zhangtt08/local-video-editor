/** 时间线上直接拖针：走的是动画曲线那份格子，落库的是一条普通 `keyframe.move`。

 剪映 / 达芬奇 / AE 都把针画在片段上并且可以直接拖；这里的菱形此前只能点一下跳过去。这一版把拖动接
 在 `keyframeSnap` 那份几何上（绝对帧格子、像素容差、找播放头与邻居），所以时间线与曲线编辑器不可能
 对同一枚针给出两个不同的落点。更要紧的是三件事：`animation_offset_ticks` 必须折掉再交出去（reducer
 自己会加回来，界面重复加就把针送到片段之外）、除了时间以外一个字段都不许改、以及撞针要在松手前认出
 来——那正是 reducer 的 `KEYFRAME_COLLISION`，这里只是不再让用户收到一条红字。

 断的是行为而不是文案：命令的 op 与形状、刻度的空间、值与插值原样带走、被占用的那一格点名说得出办
 法、不同属性的同格不算撞针、缩放变了容差按屏幕像素走、越界的指针永远夹回可写区间。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { planKeyframeDrag, planNeedleRemoval } from "../desktop/src/keyframeDrag";
import { clampGroupTimeShift, groupShift } from "../desktop/src/curveDrag";
import { FIELD_LABEL } from "../desktop/src/effects";
import type { Clip, Keyframe } from "../desktop/src/engine";

const TIMEBASE = 70_560_000;
const FRAME = Math.floor((TIMEBASE * 1001) / 30000);   // 2 354 352
const SAMPLE = Math.floor(TIMEBASE / 48000);            // 1 470
const DURATION = 20 * TIMEBASE;                          // 二十秒：1 411 200 000
const OFFSET = 5_000;                                    // 重构图或分割留下的动画时钟偏移
const POSITION = SAMPLE * 800;                           // 1 176 000：起点不在整帧上
const PHASE = FRAME - POSITION;                          // 1 178 352
const PX = 62;                                           // 时间线默认的每屏秒像素

assert.equal(FRAME, 2_354_352, "frame length by hand: `//` in TS is a comment, not division");
assert.equal(DURATION, 1_411_200_000, "a twenty-second clip, so four screen pixels at 62 px/s is a real distance");

const key = (property: string, at: number, extra: Partial<Keyframe> = {}): Keyframe => ({
  property: property as Keyframe["property"], at_ticks: at, value: 0.4, interpolation: "ease", bezier: null, ...extra,
});
const clipOf = (keys: Keyframe[]): Clip => ({
  id: "clip-key", track_id: "track-1", asset_id: "asset-1", kind: "video",
  position_ticks: POSITION, duration_ticks: DURATION, source_in_ticks: 0, source_duration_ticks: DURATION,
  animation_offset_ticks: OFFSET, keyframes: keys,
} as unknown as Clip);

/** 拖一次：`pointer` 是片段本地刻度，`head` 是播放头的绝对刻度（null 表示不在播放头上）。 */
const drag = (held: Keyframe, pointer: number, keys: Keyframe[], head: number | null, px = PX, snap = true, duplicate = false, group?: Keyframe[]) => planKeyframeDrag({ duplicate, group,
  clip: clipOf(keys), key: held, pointer_ticks: pointer, playhead_ticks: head === null ? -1 : head - POSITION, px, snap, quantum: FRAME,
});

const held = key("opacity", OFFSET + 30_000);            // 工程里存的刻度 = 本地 30000 + 偏移
const onLine = key("opacity", OFFSET + PHASE);           // 已经在格线上的一枚

// 落库的是普通命令，而刻度是**片段本地**的：偏移必须折掉，reducer 会自己加回来。
const moved = drag(held, 30_000 + PHASE / 2, [held], null);
assert.ok(moved.kind === "move", "a dragged needle produces a move");
assert.equal(moved.commands.length, 1, "one grabbed needle is one command, not one per property it shares");
assert.equal(moved.commands[0].op, "keyframe.move", "the timeline must not invent a second keyframe command");
assert.equal(moved.shifts.length, 1, "and it reports exactly one needle's landing back to the view");
assert.equal(moved.shifts[0].property, "opacity", "the report names the property so the view can match the diamond");
assert.equal(moved.shifts[0].from, 30_000, "the report's start is clip-local, the same clock as the command");
assert.deepEqual(Object.keys(moved.commands[0]).sort(), ["clip_id", "from_ticks", "keyframe", "op"], "the command carries nothing but the ordinary shape");
assert.equal((moved.commands[0] as { clip_id: string }).clip_id, "clip-key");
assert.equal((moved.commands[0] as { from_ticks: number }).from_ticks, 30_000, "from_ticks is clip-local: the offset was subtracted exactly once");
assert.equal(moved.at_ticks, PHASE, "the drop lands on the clip's own frame line, not on local zero");
assert.ok((POSITION + PHASE) % FRAME === 0, "and that tick is a real output frame");
assert.ok(moved.kind === "move" && (moved.commands[0] as { keyframe: Keyframe }).keyframe.at_ticks === moved.at_ticks, "the command and the report agree");

// 除了时间，一个字段都不许动：值、插值、贝塞尔控制柄原样带走。
const bezier = key("scale", OFFSET + 30_000, { value: 1.25, interpolation: "bezier", bezier: { x1: 0.2, y1: 0, x2: 0.8, y2: 1 } });
const dragged = drag(bezier, 30_000 + PHASE / 2, [bezier], null);
assert.ok(dragged.kind === "move");
assert.deepEqual((dragged.commands[0] as { keyframe: Keyframe }).keyframe, { ...bezier, at_ticks: PHASE }, "only the time changed");

// 松手回原格就是 noop：不许有一次没有意义的网络往返。
assert.equal(drag(onLine, PHASE, [onLine], null).kind, "noop", "back to its own frame line is a no-op");
assert.equal(drag(onLine, PHASE - 100_000, [onLine], null).kind, "noop", "under half a frame rounds back");
assert.equal(drag(onLine, PHASE + FRAME + 900_000, [onLine], null).at_ticks, PHASE + FRAME, "and a bit over one frame is a one-frame step");

// 关掉吸附就按指针的整数刻度走；越界的指针永远夹回 [0, duration]，交出去的一律可写。
const free = drag(held, 123_456.7, [held], null, PX, false);
assert.ok(free.kind === "move" && free.at_ticks === 123_457, "no snap, no lattice");
for (const pointer of [-9 * FRAME, -1, 0, 30_000, DURATION - 3, DURATION, DURATION + FRAME * 7]) {
  for (const snap of [true, false]) {
    const plan = drag(held, pointer, [held], null, PX, snap);
    assert.ok(plan.kind === "move" || plan.kind === "noop", `${pointer}/${snap} must not be blocked: ${plan.kind}`);
    if (plan.kind === "move") {
      assert.ok(Number.isInteger(plan.at_ticks) && plan.at_ticks >= 0 && plan.at_ticks <= DURATION, `${pointer} → ${plan.at_ticks} must stay writable`);
      assert.notEqual(plan.at_ticks, 30_000, "the needle was off the lattice, so it really moves");
    }
  }
}

// 邻居参与吸附，但只有**同一条属性**的邻居算撞针（reducer 按 property+time 判占位）。
const sameRow = key("opacity", OFFSET + 8_000_000);
const blocked = drag(held, 8_000_000 + 100_000, [held, sameRow], null);
assert.ok(blocked.kind === "blocked", "landing on a neighbour of the same property is refused before the round trip");
if (blocked.kind === "blocked") {
  assert.equal(blocked.at_ticks, 8_000_000, "the needle it tried to land on is reported back");
  assert.match(blocked.reason, /[一-鿿]/, "the refusal must be Chinese");
  assert.ok(blocked.reason.includes((8_000_000 / TIMEBASE).toFixed(3)), `the reason must name the occupied second: ${blocked.reason}`);
  assert.ok(blocked.reason.includes("不透明度"), `the reason must name the property in Chinese: ${blocked.reason}`);
  assert.ok(!blocked.reason.includes("opacity"), `the contract id must not leak into that sentence: ${blocked.reason}`);
  // 拒绝得当场给一条走得了的路：这句过去把人支到动画曲线里，现在「按住 Alt 点掉那一枚」就在这条时间线上。
  assert.match(blocked.reason, /按住 Alt 点掉/, `the refusal must name the in-place exit: ${blocked.reason}`);
}
const other = key("gain", OFFSET + 8_000_000);
const crossed = drag(held, 8_000_000 + 100_000, [held, other], POSITION + 8_000_000);
assert.ok(crossed.kind === "move" && crossed.at_ticks === 8_000_000, "a different property may share that second: the playhead lands there anyway");

// 播放头也参与吸附，但落在片段之外就当没有。
assert.equal(drag(held, 5_030_000, [held], POSITION + 5_000_000).at_ticks, 5_000_000, "the playhead grabs within four screen pixels");
assert.ok((drag(held, 5_030_000, [held], POSITION - 6_000).at_ticks! - PHASE) % FRAME === 0, "a playhead before the clip must not pull");
assert.ok((drag(held, 5_030_000, [held], POSITION + DURATION + 6_000).at_ticks! - PHASE) % FRAME === 0, "nor one past the end");

// 容差是屏幕像素：时间线放大八倍后，同样偏 100 000 刻度就不该再吸上去。
const wide = drag(held, 8_000_000 + 100_000, [held, sameRow], null, PX);
const tight = drag(held, 8_000_000 + 100_000, [held, sameRow], null, PX * 60);
assert.equal(wide.kind, "blocked", "at 62 px/s four pixels reach the neighbour");
assert.equal(tight.kind, "move", "sixty times the zoom must narrow the grab, because the radius is in pixels");

const shorter = { ...clipOf([held, sameRow]), duration_ticks: DURATION / 2 };
const half = planKeyframeDrag({ clip: shorter, key: held, pointer_ticks: 8_000_000 + 100_000, playhead_ticks: -1, px: PX, snap: true, quantum: FRAME });
assert.equal(half.kind, "blocked", "the reach is four screen pixels whatever the clip length");
if (half.kind === "blocked") assert.equal(half.at_ticks, 8_000_000, "and it is the same neighbour that catches it");

// 接上线才作数：时间线只认这一处判断，且不许留下第二份吸附算术。
const path = ["desktop/src/views/Timeline.tsx", "src/views/Timeline.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the timeline must be readable from the check's working directory");
const source = readFileSync(path!, "utf8");
assert.match(source, /planKeyframeDrag\(\{/, "the timeline must ask the shared planner where the needle lands");
// 指针读数必须由「片段自己的左边」与「当前缩放」两个量决定：少掉 px 就等于在别的缩放层级上拖不准。
assert.match(source, /const grab = \(\(event\.clientX - box\.current\.getBoundingClientRect\(\)\.left\) \/ px\) \* TIMEBASE - from/, "the grip must be measured at pointerdown, in ticks");
assert.match(source, /pointer_ticks: \(\(clientX - node\.getBoundingClientRect\(\)\.left\) \/ px\) \* TIMEBASE - grab/, "and the drag must subtract it, so a needle clamped at the edge does not teleport to where it is painted");
assert.match(source, /playhead_ticks: playhead\.value - clip\.position_ticks/, "and the playhead must be handed over in the same local clock");
// 落库只允许是那一行：不许在它前面挂第二个副作用，也不许绕开带 expected_revision 的那条链。
// 1.119 起交出去的是 `next.commands`（一枚时它只有一条），历史那一行按抓了几枚分开写。
assert.match(source, /^\s{6}editAtRevision\(next\.commands, project\.id, project\.revision, group\.length > 1 \? `\$\{duplicate \? "复制" : "拖动"} \$\{group\.length} 枚关键帧` : duplicate \? "复制关键帧" : "拖动关键帧", app\.sequenceId\);$/m, "the write is exactly that one call through the ordinary edit chain, and the history line counts the needles it moved");
assert.equal((source.match(/editAtRevision\(/g) ?? []).length, 2, "the needle path has exactly two writes: the drag and the Alt + tap removal, and no second side effect");
// 没拖动就还是「点一下跳过去」，而按住 Alt 点一下是删掉这一枚——两条都断到同一个分支里，
// 因为把删除接在另一个入口上就等于在时间线上开第二条写路径。
assert.match(source,
  /if \(Math\.abs\(ev\.clientX - event\.clientX\) < 2\) \{[\s\S]{0,240}if \(duplicate\) editAtRevision\(\[planNeedleRemoval\(clip, group\)\], project\.id, project\.revision, group\.length > 1 \? `删除 \$\{group\.length} 枚关键帧` : "删除关键帧", app\.sequenceId\);[\s\S]{0,80}setPicked\(\[\]\);[\s\S]{0,160}playhead\.pause\(\); playhead\.set\(clip\.position_ticks \+ from\); return;[\s\S]{0,40}\}/,
  "the tap still jumps to the needle, and Alt + tap removes the grabbed group through the very same edit chain, then drops the selection");
assert.equal((source.match(/removeKeyframe\(/g) ?? []).length, 0, "the timeline must not open store's own delete path as a second write chain");
assert.match(source, /按住 Alt 点一下是删掉这一枚/, "and the needle says so on hover");
assert.match(source, /按住 Alt 点一下把这 \$\{picked\.length} 枚一起删掉/, "and a picked diamond promises the group removal in its own hover text");
assert.match(source, /onPointerDown=\{\(event\) => startKey\(event, k\)\}/, "the diamond carries the gesture instead of a click handler");
assert.equal((source.match(/onClick=\{\(event\) => \{ event\.stopPropagation\(\); selectClip\(clip\.id\)/g) ?? []).length, 0, "the old click-only needle must be gone");
assert.ok(!/Math\.round\([^)\n]*\/ *q\) *\* *q/.test(source), "no second snapping formula may live in the timeline");


// Alt 拖是复制：原针不动、落点上一枚新的；落在原针那一格不算「多出一枚」，落在别人身上按撞针拒并说是复制。
const onThird = PHASE + 3 * FRAME;                        // 这一格本来就在格线上
const dup = drag(held, onThird, [held], null, PX, true, true);
assert.equal(dup.kind, "add", "an Alt drag plans an added needle, not a move");
assert.equal(dup.commands.length, 1, "copying one needle is one command");
const dupCommand = (dup as { commands: { op: string; clip_id: string; keyframe: Keyframe }[] }).commands[0];
assert.equal(dupCommand.op, "keyframe.set", "the copy is an ordinary keyframe.set");
assert.equal(dupCommand.clip_id, "clip-key", "and it goes to this clip");
assert.equal(dupCommand.keyframe.at_ticks, onThird, "it lands on the frame line the pointer asked for");
assert.equal(dupCommand.keyframe.value, held.value, "value, easing and handles ride along");
assert.equal(dupCommand.keyframe.interpolation, held.interpolation, "the copy is the same shape");
assert.equal(held.at_ticks, OFFSET + 30_000, "the original stays exactly where it was");
assert.equal(drag(held, 30_000, [held], null, PX, false, true).kind, "noop", "duplicating onto the original second adds nothing");
const clash = drag(held, 8_025_000, [held, key("opacity", OFFSET + 8_000_000)], null, PX, true, true);
assert.ok(clash.kind === "blocked" && /复制/.test((clash as { reason: string }).reason),
  `the refusal must say a copy needs a free second: ${clash.kind}`);
// 普通拖动不许被复制的分支污染：没有 Alt 就还是 keyframe.move。
const plain = drag(held, onThird, [held], null);
assert.equal((plain as { commands: { op: string }[] }).commands[0].op, "keyframe.move", "no Alt, no add");

// Alt 点一下是删：命令是普通 `keyframe.remove`，刻度按片段本地交（与拖动同一口径），不碰工程里那份记录。
const removal = planNeedleRemoval(clipOf([held, sameRow]), [held]) as { op: string; clip_id: string; property: string; at_ticks: number };
assert.equal(removal.op, "keyframe.remove", "the tap deletes through the ordinary command, no new op");
assert.deepEqual(Object.keys(removal).sort(), ["at_ticks", "clip_id", "op", "property"], "and carries nothing but the documented shape");
assert.equal(removal.clip_id, "clip-key", "it names this clip");
assert.equal(removal.property, "opacity", "and this property, so a neighbour on another curve survives");
assert.equal(removal.at_ticks, 30_000, "the offset is folded exactly once, the same clock the move command uses");
assert.equal(held.at_ticks, OFFSET + 30_000, "planning does not mutate project state");
// 1.121：Alt 点掉挑中的那一组——多条针走的是引擎本来就有的 `keyframes.remove`，一次点一个 revision。
const groupRemoval = planNeedleRemoval(clipOf([held, sameRow]), [held, sameRow]) as unknown as { op: string; clip_id: string; keyframes: { property: string; at_ticks: number }[] };
assert.equal(groupRemoval.op, "keyframes.remove", "a picked group is removed with the engine's own batch op, not N single removes");
assert.deepEqual(Object.keys(groupRemoval).sort(), ["clip_id", "keyframes", "op"], "and it carries nothing but the documented batch shape");
assert.deepEqual(groupRemoval.keyframes, [{ property: "opacity", at_ticks: 30_000 }, { property: "opacity", at_ticks: 8_000_000 }], "each tick is clip-local, folded exactly once, in the order they were grabbed");
const doubled = planNeedleRemoval(clipOf([held, sameRow]), [held, held]) as { op: string; property: string };
assert.equal(doubled.op, "keyframe.remove", "a needle listed twice is still one needle — the reducer refuses a duplicated selection outright");
assert.deepEqual((planNeedleRemoval(clipOf([held, sameRow]), [held, sameRow, held]) as unknown as { keyframes: unknown[] }).keyframes.length, 2, "the batch dedupes too, so the same grab never trips INVALID_SELECTION");
assert.equal(held.at_ticks, OFFSET + 30_000, "planning a removal still does not touch the project's own record");


// ---- 1.119：一次抓一组（框选挑中的那几枚一起走）----------------------------------------------
// 三枚针分属两条属性：不透明度两枚（本地 2 帧、5 帧）加位置一枚（3 帧）。这一节关的是「整组」那三条
// 只靠读代码判断对错的算术：夹余量、逐条属性判撞针、以及抓几枚就交几条落点。吸附先关掉，指针读数
// 就是它报的那一格，免得把夹法的功劳记到格线头上。
const F = FRAME;
const a1 = key("opacity", OFFSET + 2 * F);
const a2 = key("opacity", OFFSET + 5 * F);
const b1 = key("x", OFFSET + 3 * F);
const trio = [a1, a2, b1];
const gdrag = (anchor: Keyframe, pointer: number, keys: Keyframe[], group: Keyframe[], duplicate = false) => planKeyframeDrag({
  clip: clipOf(keys), key: anchor, group, pointer_ticks: pointer, playhead_ticks: -1, px: PX, snap: false, quantum: F, duplicate,
});

const together = gdrag(a1, 6 * F, trio, trio);
assert.ok(together.kind === "move", "three picked needles still plan one gesture");
assert.equal(together.shifts.length, 3, "one landing reported per needle, so the third is not silently left behind");
assert.equal(together.commands.length, 1, "one grab is one command, so undo takes the whole group back in one step");
assert.equal(together.commands[0].op, "keyframes.move", "more than one needle uses the engine's own batch move, not N single moves");
const batch = (together.commands[0] as { op: string; clip_id: string; moves: { from_ticks: number; keyframe: Keyframe }[] });
assert.deepEqual(Object.keys(batch).sort(), ["clip_id", "moves", "op"], "and carries nothing but the documented batch shape");
assert.equal(batch.moves.length, 3, "every needle in the group is carried, none silently dropped");
assert.deepEqual(batch.moves.map((move) => move.keyframe.property), ["opacity", "opacity", "x"], "the group may span properties, each move keeps its own");
assert.deepEqual(batch.moves.map((move) => move.from_ticks), [2 * F, 5 * F, 3 * F], "each needle's start is its own clip-local tick");
assert.deepEqual(batch.moves.map((move) => move.keyframe.at_ticks), [6 * F, 9 * F, 7 * F], "the same delta lands on all three");
assert.deepEqual(batch.moves.map((move) => move.keyframe.value), [0.4, 0.4, 0.4], "values ride along untouched");
assert.equal(together.shifts.length, 3, "the view is told three landings, in the order it handed them over");
assert.deepEqual(together.shifts.map((shift) => shift.at), [6 * F, 9 * F, 7 * F], "and the report is the same numbers the command writes");
assert.deepEqual(together.shifts.map((shift) => shift.from), [2 * F, 5 * F, 3 * F], "each with its own start, so only the moving diamonds look like they move");

// 整组的余量由这一组自己的两头决定：抓的那一枚想去 598 帧，可 5 帧那枚先撞上片尾（这条片段是 599.4 帧长，
// 所以尾巴那一格不是整数帧——夹的是真边界，不是「凑整后的帧数」）。
const rightEdge = gdrag(a1, 598 * F, trio, trio);
assert.ok(rightEdge.kind === "move");
assert.equal(rightEdge.at_ticks, DURATION - 3 * F, "the anchor is reported where the group can actually land, not where the pointer wished");
assert.deepEqual((rightEdge as { kind: "move" }).shifts.map((shift) => shift.at), [DURATION - 3 * F, DURATION, DURATION - 2 * F], "the last of them stops exactly on the clip's own end");
const leftEdge = gdrag(a1, -1 * F, trio, trio);
assert.ok(leftEdge.kind === "move" && leftEdge.at_ticks === 0 && leftEdge.shifts[2].at === F, "and the head is the same wall on the other side");

// 顶在片段尾巴上的一组：一格也走不了，那就是 noop，不是「拒绝」。
const wall = [key("opacity", OFFSET + DURATION - F), key("opacity", OFFSET + DURATION)];
assert.equal(gdrag(wall[0], DURATION, wall, wall).kind, "noop", "a group pressed against the end does not emit a round trip that changes nothing");

// 撞针逐条属性判：另一条曲线上的邻居不算占位，同一条曲线上的邻居算，而且明说是这一组走不过去。
const onOther = [a1, a2, b1, key("gain", OFFSET + 6 * F)];
assert.ok(gdrag(a1, 6 * F, onOther, [a1, a2]).kind === "move", "a neighbour on another curve may share that tick with a moved group");
const blocker = [a1, a2, b1, key("opacity", OFFSET + 9 * F)];
const refused = gdrag(a1, 6 * F, blocker, trio);
assert.ok(refused.kind === "blocked", "a neighbour on the same curve as one of the moved needles is refused before the round trip");
if (refused.kind === "blocked") {
  assert.ok(refused.reason.includes("3 枚一起走"), `the refusal says a group was moving: ${refused.reason}`);
  assert.ok(refused.reason.includes("不透明度"), `and which curve it tripped on, in Chinese: ${refused.reason}`);
  assert.ok(refused.reason.includes((9 * F / TIMEBASE).toFixed(3)), `and the occupied second: ${refused.reason}`);
  assert.ok(!refused.reason.includes("opacity"), `the contract id must not leak into that sentence: ${refused.reason}`);
  assert.match(refused.reason, /按住 Alt 点掉/, "and the in-place exit is still named");
}
// 撞的是组里**另一条曲线**上那枚：红字得点名那一条，而不是被抓的这一条。判错属性就会把人支去删一枚无辜的针。
const otherCurve = [a1, a2, b1, key("x", OFFSET + 7 * F)];
const refusedX = gdrag(b1, 7 * F, otherCurve, trio);
assert.ok(refusedX.kind === "blocked" && refusedX.reason.includes(FIELD_LABEL.x) && !refusedX.reason.includes("不透明度"),
  `the refusal names the curve that is actually occupied (${FIELD_LABEL.x}), not the grabbed one: ${refusedX.kind} / ${JSON.stringify(refusedX)}`);
// 同一件事的反面：抓的是不透明度那一枚，撞的却是组里位置那一条。判属性时若拿「抓的那一条」去比整组，
// 这一枚就悄悄走过去、由引擎回一条红字——界面前置判断的意义就没了。
const crossedGroup = [a1, a2, b1, key("x", OFFSET + 8 * F)];
const refusedCross = gdrag(a1, 7 * F, crossedGroup, trio);
assert.ok(refusedCross.kind === "blocked" && refusedCross.reason.includes(FIELD_LABEL.x),
  `a group is refused by the curve one of ITS needles lands on: ${refusedCross.kind} / ${JSON.stringify(refusedCross)}`);

// 复制一组：原针一枚都不动，所以组里自己的那几枚也算占了格。
const copied = gdrag(a1, 6 * F, trio, [a1, a2], true);
assert.ok(copied.kind === "add" && copied.commands.length === 2, "copying two picked needles writes two copies");
assert.deepEqual((copied as { commands: { op: string }[] }).commands.map((command) => command.op), ["keyframe.set", "keyframe.set"], "each an ordinary keyframe.set, the same command the checker's paste uses");
assert.deepEqual((copied as { commands: { keyframe: Keyframe }[] }).commands.map((command) => command.keyframe.at_ticks), [6 * F, 9 * F], "landing on the delta, originals untouched");
assert.equal(a1.at_ticks, OFFSET + 2 * F, "planning a copy still does not move the project's own needle");
const ontoItself = gdrag(a1, 5 * F, trio, [a1, a2], true);
assert.ok(ontoItself.kind === "blocked", "a copy may not land on a needle that is staying put — even one from its own group");
assert.match((ontoItself as { reason: string }).reason, /复制/, "and it says a copy needs a free second");

// 夹余量只许有一处权威：曲线编辑器 1.117 那份 groupShift 的时间分支，就是时间线现在用的这一句。
const BAND = { min: 0, max: 100, step: 5, factor: 100 };
const points = [{ at_ticks: 2 * F, value: 0.3 }, { at_ticks: 5 * F, value: 0.6 }, { at_ticks: 3 * F, value: 1 }];
for (const want of [-900_000, -2 * F, 0, 4 * F, 596 * F, 700 * F]) {
  assert.equal(groupShift(points, BAND, DURATION, want, 0).dt, clampGroupTimeShift(points.map((point) => point.at_ticks), DURATION, want),
    `the curve editor and the timeline must clamp the same group the same way at ${want}`);
}

// 接上线：时间线把手上那一整组交给同一个 planner，画影子只画 planner 说了会走的那几枚。
assert.match(source, /clip, key, group, px, snap, quantum: q, duplicate/, "the timeline hands the whole picked group to the shared planner");
assert.match(source, /const group = picked\.includes\(id\) \? \(clip\.keyframes \?\? \[\]\)\.filter\(\(member\) => picked\.includes\(needleId\(member\)\)\) : \[key\]/,
  "the group comes from the project's own needles, not from what happens to be on screen");
assert.match(source, /if \(!picked\.includes\(id\)\) setPicked\(\[id\]\)/, "grabbing a needle outside the group makes it the group, the way AE does");
assert.match(source, /if \(event\.shiftKey\) \{ setPicked\(togglePick\(picked, id\)\); return; \}/, "Shift + click joins or leaves the group instead of dragging");
assert.match(source, /targets: next\.shifts\.map\(\(member, index\) => \(\{ id: needleId\(group\[index\]\), from: member\.from, at: member\.at \}\)\)/,
  "every landing the planner reports is drawn, in the order the group was handed over");
assert.match(source, /const target = keyDrag && !keyDrag\.duplicate \? keyDrag\.targets\.find\(\(item\) => item\.id === id\) : undefined/, "a copy's source diamonds must not look like they move");
assert.match(source, /bottom: 1 \+ \(laneOf\.get\(item\.id\) \?\? 0\) \* LANE_PITCH_PIXELS/, "and a copy's ghost rides its own needle's lane, not lane zero");
assert.equal((source.match(/Math\.min\(width - 6 - \(hidden\.length \? 16 : 0\)/g) ?? []).length, 1, "needles and ghosts share one clamp, so a ghost can never sit on the +N chip");
assert.match(source, /picked\.includes\(id\) \? " selected" : ""/, "the picked needles are the ones that look picked");
assert.equal((source.match(/keyDrag\.property/g) ?? []).length, 0, "the drag state no longer pretends one needle is the whole gesture");
assert.match(source, /\$\{duplicate \? "复制" : "拖动"\} \$\{group\.length} 枚关键帧/, "the history line counts the needles that moved");

console.log(
  "PASS: 时间线上拖针写的是普通 `keyframe.move`——偏移折掉一次、只改时间、回到原格就是 noop、"
    + "同属性邻居占格在松手前就点名（不同属性照吸）、容差跟着屏幕像素走、越界永远夹回可写区间；"
    + "1.119 起一次抓一组走同一条算术：整组被自己两头夹、撞针逐条属性判、一枚一条命令、复制那组把原针也算占位；"
    + "1.121 起 Alt 点一下删掉挑中的那一组（一批一条 `keyframes.remove`，重复的那格先去掉）",
);
