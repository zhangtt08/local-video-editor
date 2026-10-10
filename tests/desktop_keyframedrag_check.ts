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

import { planKeyframeDrag } from "../desktop/src/keyframeDrag";
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
const drag = (held: Keyframe, pointer: number, keys: Keyframe[], head: number | null, px = PX, snap = true) => planKeyframeDrag({
  clip: clipOf(keys), key: held, pointer_ticks: pointer, playhead_ticks: head === null ? -1 : head - POSITION, px, snap, quantum: FRAME,
});

const held = key("opacity", OFFSET + 30_000);            // 工程里存的刻度 = 本地 30000 + 偏移
const onLine = key("opacity", OFFSET + PHASE);           // 已经在格线上的一枚

// 落库的是普通命令，而刻度是**片段本地**的：偏移必须折掉，reducer 会自己加回来。
const moved = drag(held, 30_000 + PHASE / 2, [held], null);
assert.ok(moved.kind === "move", "a dragged needle produces a move");
assert.equal(moved.command.op, "keyframe.move", "the timeline must not invent a second keyframe command");
assert.deepEqual(Object.keys(moved.command).sort(), ["clip_id", "from_ticks", "keyframe", "op"], "the command carries nothing but the ordinary shape");
assert.equal(moved.command.clip_id, "clip-key");
assert.equal(moved.command.from_ticks, 30_000, "from_ticks is clip-local: the offset was subtracted exactly once");
assert.equal(moved.at_ticks, PHASE, "the drop lands on the clip's own frame line, not on local zero");
assert.ok((POSITION + PHASE) % FRAME === 0, "and that tick is a real output frame");
assert.ok(moved.kind === "move" && moved.command.keyframe.at_ticks === moved.at_ticks, "the command and the report agree");

// 除了时间，一个字段都不许动：值、插值、贝塞尔控制柄原样带走。
const bezier = key("scale", OFFSET + 30_000, { value: 1.25, interpolation: "bezier", bezier: { x1: 0.2, y1: 0, x2: 0.8, y2: 1 } });
const dragged = drag(bezier, 30_000 + PHASE / 2, [bezier], null);
assert.ok(dragged.kind === "move");
assert.deepEqual(dragged.command.keyframe, { ...bezier, at_ticks: PHASE }, "only the time changed");

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
  assert.ok(blocked.reason.includes("opacity"), `the reason must name the property: ${blocked.reason}`);
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
const write = source.split("\n").find((row) => row.trim().startsWith("editAtRevision([next.command]"));
assert.equal(write?.trim(), 'editAtRevision([next.command], project.id, project.revision, "拖动关键帧", app.sequenceId);', "the write is exactly that call through the ordinary edit chain");
// 没拖动就还是「点一下跳过去」：那条判断必须在，且落在 from 上。
assert.match(source, /if \(Math\.abs\(ev\.clientX - event\.clientX\) < 2\) \{ playhead\.pause\(\); playhead\.set\(clip\.position_ticks \+ from\)/, "the tap still jumps to the needle");
assert.match(source, /onPointerDown=\{\(event\) => startKey\(event, k\)\}/, "the diamond carries the gesture instead of a click handler");
assert.equal((source.match(/onClick=\{\(event\) => \{ event\.stopPropagation\(\); selectClip\(clip\.id\)/g) ?? []).length, 0, "the old click-only needle must be gone");
assert.ok(!/Math\.round\([^)\n]*\/ *q\) *\* *q/.test(source), "no second snapping formula may live in the timeline");

console.log(
  "PASS: 时间线上拖针写的是普通 `keyframe.move`——偏移折掉一次、只改时间、回到原格就是 noop、"
    + "同属性邻居占格在松手前就点名（不同属性照吸）、容差跟着屏幕像素走、越界永远夹回可写区间",
);
