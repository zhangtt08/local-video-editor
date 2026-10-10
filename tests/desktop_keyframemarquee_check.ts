/** 时间线上的框选：拉一个框挑中一组针，挑中的必须是点得到的那几枚。

 1.113 把针按属性分了道，画不下的属性干脆不画——那枚「+N」的牌子就是这一决定的证据。这一版的框选必须
 尊重同一件事：命中测试读的是屏幕上**真画出来**的矩形，所以框不可能挑中一枚鼠标永远点不到的针；拖动中的
 那枚影子是装饰（`pointer-events: none`），也不许被挑中，否则复制一次就会把「想去的那一格」当成已存在的针。
 坐标一律用视口像素：界面把 `getBoundingClientRect` 交进来，这里不再算第二套位置——同一枚针有两个坐标，
 就是 1.110 修过的那个「瞬移」的换皮。

 断的是几何与接线：往回拉也是同一个框、只在边上擦过不算选中、拉开没拉开的阈值与那枚针的点击同一口径、
 Shift 是加进这一组而不是替换、点一下空处清场并把片段选中（少一个入口不算改手感）、针道左右让开修剪柄与
 淡角柄那两条手占的像素、影子那一条被排除在命中集之外，以及选中标识只有一处在拼。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { LANE_PITCH_PIXELS, NEEDLE_AREA_PIXELS, laneCapacity, needleId } from "../desktop/src/keyframeLanes";
import {
  MARQUEE_INSET_PIXELS, MARQUEE_MIN_PIXELS, commitPick, draggedEnough, hitsInBand, marqueeBox, overlaps, togglePick,
} from "../desktop/src/keyframeMarquee";

const box = (x0: number, y0: number, x1: number, y1: number) => ({ x0, y0, x1, y1 });
/** 合成像素，只为断重叠语义：道距与针盒的高用的是样式表那两份数（12px 道距、12px 针盒），宽度按界面画
 *  出来的那枚菱形取一个示意值——这里断的是「压进框里才算」，不是量出来的矩形，量的事实在下面那条 CSS 检查里。 */
const item = (id: string, x: number, lane: number) => ({ id, box: box(x, 40 - lane * LANE_PITCH_PIXELS, x + 13, 52 - lane * LANE_PITCH_PIXELS) });
const painted = [item("opacity|200", 40, 0), item("x|200", 90, 1), item("gain|900", 150, 0)];

// 往回拉与往前拉是同一个框：不认拖动方向，否则用户从右下角起手的框永远选不中东西。
assert.deepEqual(marqueeBox({ x: 90, y: 40 }, { x: 20, y: 12 }), box(20, 12, 90, 40), "a backwards drag is the same rectangle");
assert.deepEqual(marqueeBox({ x: 20, y: 12 }, { x: 90, y: 40 }), box(20, 12, 90, 40), "and it equals the forwards one");

// 框里就选中，框外就不选，边上擦过也不算——擦过的那枚用户看不出自己挑中了它。
assert.deepEqual(hitsInBand(painted, marqueeBox({ x: 0, y: 0 }, { x: 200, y: 60 })), ["opacity|200", "x|200", "gain|900"], "a band over the whole strip takes every painted needle");
assert.deepEqual(hitsInBand(painted, marqueeBox({ x: 30, y: 30 }, { x: 60, y: 60 })), ["opacity|200"], "a small band takes only the needle it really covers");
assert.deepEqual(hitsInBand(painted, marqueeBox({ x: 53, y: 0 }, { x: 90, y: 60 })), [], "stopping exactly at a needle's left edge is touching, not covering");
assert.ok(overlaps(box(0, 0, 10, 10), box(5, 5, 15, 15)), "one pixel of overlap counts");
assert.ok(!overlaps(box(0, 0, 10, 10), box(10, 0, 20, 10)), "and a shared border does not");
assert.deepEqual(hitsInBand(painted, marqueeBox({ x: 80, y: 20 }, { x: 100, y: 34 })), ["x|200"], "the lane a needle sits in is part of the answer, not just its second");
assert.deepEqual(hitsInBand(painted, marqueeBox({ x: 0, y: 0 }, { x: 200, y: 28 })), [], "a band that stays above every lane picks nothing");
assert.deepEqual(hitsInBand([{ id: "a", box: box(0, 0, 10, 10) }, { id: "a", box: box(0, 0, 10, 10) }], box(0, 0, 20, 20)), ["a"], "the same needle twice is still one needle");

// 拉开没拉开：两像素以内是「点了一下针道」，横竖任一方向都算。
assert.equal(draggedEnough({ x: 10, y: 10 }, { x: 11, y: 10 }), false, "one pixel is a tap");
assert.equal(draggedEnough({ x: 10, y: 10 }, { x: 10, y: 12 }), true, "a thin vertical band is still a band");
assert.equal(MARQUEE_MIN_PIXELS, 2, "the same threshold the needle's own tap uses");

// 落定：不按住 Shift 就整组换成框里这几枚（框到空处就是清场），按住就是加进去。
assert.deepEqual(commitPick(["opacity|200"], ["x|200", "gain|900"], false), ["x|200", "gain|900"], "a plain band replaces the group");
assert.deepEqual(commitPick(["opacity|200"], [], false), [], "banding over nothing clears it");
assert.deepEqual(commitPick(["opacity|200"], ["x|200"], true), ["opacity|200", "x|200"], "Shift adds to what is already picked");
assert.deepEqual(commitPick(["opacity|200"], ["opacity|200"], true), ["opacity|200"], "and never doubles a needle");
assert.deepEqual(togglePick(["opacity|200", "x|200"], "gain|900"), ["opacity|200", "x|200", "gain|900"], "Shift + click joins at the end, the group's order untouched");
assert.deepEqual(togglePick(["opacity|200", "x|200"], "x|200"), ["opacity|200"], "Shift + click again takes it out");

// 选中标识只有一处在拼：针属于「哪条曲线的哪一格」，所以它是工程里那个刻度，不是画出来的像素。
assert.equal(needleId({ property: "opacity", at_ticks: 200 } as never), "opacity|200", "a needle is identified by its curve and its tick, not by either alone");
const sources = ["desktop/src", "src"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(sources, "the renderer must be readable from the check's working directory");
const holders: string[] = [];
for (const entry of readdirSync(sources!, { recursive: true })) {
  const file = resolve(sources!, entry);
  if (!statSync(file).isFile() || !/\.(ts|tsx)$/.test(entry)) continue;
  if (readFileSync(file, "utf8").includes("${key.property}|")) holders.push(entry.replace(/\\/g, "/"));
}
assert.deepEqual(holders, ["keyframeLanes.ts"], `one place may spell a needle's identity, found ${holders.join(", ")}`);

// 针道那条带盖得住它承诺的三道，且左右让开别人的手：修剪柄在最外 7px，淡角柄从 9px 起再占 9px。
const cssPath = ["desktop/src/styles.css", "src/styles.css"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(cssPath, "the stylesheet must be readable from the check's working directory");
const css = readFileSync(cssPath!, "utf8");
const pixels = (selector: string, property: string) => {
  const pattern = new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{[^}]*${property}: *(\\d+)px`);
  const match = pattern.exec(css);
  assert.ok(match, `${selector} must declare ${property} in pixels`);
  return Number(match[1]);
};
const reach = Math.max(
  pixels(".trim-handle", "width"),
  pixels(".fade-handle.in", "left") + pixels(".fade-handle", "width"),
  pixels(".fade-handle.out", "right") + pixels(".fade-handle", "width"),
);
assert.ok(MARQUEE_INSET_PIXELS > reach, `the band must start past the trim and fade hands (${reach}px), not on them (${MARQUEE_INSET_PIXELS}px)`);
const strip = /\.clip-needles\s*\{([^}]*)\}/.exec(css);
assert.ok(strip, "the needle band has its own rule");
assert.match(strip[1], /bottom: *0/, "it starts at the clip's own bottom, where the lanes live");
assert.doesNotMatch(strip[1], /left:|right:|height:/, "and its geometry comes from the constants the view inlines, not from a second copy in CSS");
assert.match(strip[1], /z-index: *1/, "below the diamonds, so grabbing a needle is still grabbing a needle");
assert.equal(laneCapacity(NEEDLE_AREA_PIXELS), 3, "the reserved height holds three lanes");
assert.ok((laneCapacity(NEEDLE_AREA_PIXELS) - 1) * LANE_PITCH_PIXELS + LANE_PITCH_PIXELS <= NEEDLE_AREA_PIXELS, "and the band reaches the deepest lane it draws");

// 接线：命中集来自屏幕上真画出来的菱形，影子被排除，框子的坐标换到片段自己的坐标系里再画。
const path = resolve(sources!, "views/Timeline.tsx");
const source = readFileSync(path, "utf8");
assert.match(source, /\.clip-keyframe:not\(\.ghost\)/, "a copy's ghost must not be pickable — it is where a needle wants to go, not a needle");
assert.match(source, /setPicked\(commitPick\(base, hitsInBand\(paintedBoxes\(\), area\), additive\)\)/,
  "the hit set is measured again on every move: an Agent may rewrite the project while the human is mid-drag, and a snapshot taken at pointerdown would leave a phantom needle picked");
assert.doesNotMatch(source, /const painted = paintedBoxes\(\);/, "no once-per-grab snapshot may survive — one measurement, taken live");
assert.match(source, /const rect = node\.getBoundingClientRect\(\);[\s\S]{0,20}return \[\{ id, box: \{ x0: rect\.left/, "and the rects are the browser's own, in viewport pixels");
assert.match(source, /data-key-id=\{id\}/, "each diamond carries the identity the band answers with");
assert.match(source, /const id = needleId\(key\);/, "the drag and the band spell that identity the same way");
assert.match(source, /setBand\(\{ x0: area\.x0 - rect\.left, y0: area\.y0 - rect\.top/, "the band is painted in the clip's own box, so it cannot land off at the window's corner");
assert.match(source, /\{painted\.length \? <span className="clip-needles"/, "no needles, no band: the clip's own gestures keep that whole area");
assert.match(source, /style=\{\{ left: MARQUEE_INSET_PIXELS, right: MARQUEE_INSET_PIXELS, height: NEEDLE_AREA_PIXELS \}\}/, "the band's geometry is the two shared constants, inlined");
assert.match(source, /onPointerDown=\{startMarquee\}/, "and the band is the one that starts the grab");
assert.match(source, /setPicked\(additive \? base : \[\]\);\s*\n\s*selectClip\(clip\.id\);/, "a tap in the band clears the group and still selects the clip");
const handler = /const startMarquee = \(event: React\.PointerEvent\) => \{[\s\S]*?\n  \};/.exec(source);
assert.ok(handler, "the band's gesture is readable as one function");
assert.doesNotMatch(handler[0], /preventDefault\(\)/, "the band must not swallow the pointerdown, or double-clicking there stops opening a nested clip");
assert.match(handler[0], /if \(razor \|\| event\.button !== 0 \|\| track\.locked/, "and it stands aside for the razor, the right button and a locked track");

console.log("PASS: 框里那几枚针被挑中——往回拉同一个框、擦边不算、影子不算、点空处清场仍选片段、针道让开修剪与淡角柄、坐标只有一套");
