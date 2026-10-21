/** 时间线的针分道：同一秒上的两枚针不许抢同一堆像素。

 缺陷是量出来的（1.112 的打包 exe + Chromium）：一条片段上 `opacity` 与 `x` 各有一枚针在 1.0 秒时，
 两个按钮的 getBoundingClientRect 完全相同，`elementFromPoint` 在其中一枚的中心回的是另一枚，也就是
 说那一枚鼠标点不到——连「点一下跳过去」都做不到。修法是一条属性一道，画不下的属性不画，改成一枚
 「+N」的牌子指回动画曲线：宁可少画，也不留一枚点不到的针。

 这里断的是分道本身：道号由属性第一次出现的顺序定、同一秒的不同属性必得不同道、容量按像素算、
 超出容量的属性进 hidden（界面据此少画并说明），以及界面真的用上了这两个函数。
 1.115 在这一版里又补了一条只有真点一下才暴露的：那枚牌子把 pointerdown 喂给了片段自己的拖动手势，
 click 因此永远落不到它身上——写在 tooltip 里的那条出路（「点开进动画曲线」）是空的。现在牌子自己收下
 这次按下，门禁断的就是这条交接。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  LANE_CLIP_PAD_PIXELS,
  LANE_PITCH_PIXELS,
  NEEDLE_AREA_PIXELS,
  NEEDLE_BOTTOM_PIXELS,
  NEEDLE_HIT_PIXELS,
  SEAM_BADGE_BOTTOM_PIXELS,
  SEAM_BADGE_HEIGHT_PIXELS,
  laneCapacity,
  needleRows,
  underSeamBadge,
} from "../desktop/src/keyframeLanes";

const key = (property: string) => ({ property: property as never });

// 量到的那一幕：两枚针在同一个刻度上，属性不同。
const both = needleRows([key("opacity"), key("x")], 3);
assert.equal(both.lanes, 2, "two properties must take two lanes");
assert.notEqual(both.rowOf.get("opacity"), both.rowOf.get("x"), "they must not share a row");
assert.deepEqual(both.hidden, [], "both fit, so nothing is hidden");

// 道号按第一次出现的顺序，不按字母表：界面与用户看到的都是同一条先后。
const ordered = needleRows([key("gain"), key("blur"), key("opacity"), key("gain")], 3);
assert.deepEqual([...ordered.rowOf.keys()], ["gain", "blur", "opacity"], "first appearance wins the lane");
assert.equal(ordered.rowOf.get("gain"), 0);
assert.equal(ordered.lanes, 3, "a repeated property does not eat another lane");

// 画不下的属性不许被塞回已有的道里（那就是回到点不到），而是明说少了哪几条。
const tight = needleRows([key("x"), key("y"), key("scale"), key("rotation"), key("blur")], 3);
assert.deepEqual(tight.hidden, ["rotation", "blur"], "the overflow is named, not overlapped");
assert.equal(tight.lanes, 3, "the plot never gets more lanes than it can draw");

// 容量按像素算，且不许算出零道：片段再矮也得能点着一枚针。
assert.equal(laneCapacity(37), 3, "thirty-seven pixels hold three twelve-pixel lanes");
assert.equal(laneCapacity(11), 1, "a clip shorter than one pitch still gets one lane");
assert.equal(laneCapacity(0), 1, "never zero");
assert.equal(laneCapacity(37, LANE_PITCH_PIXELS), 3, "the pitch is the caller's knob, not a hidden literal");
assert.equal(needleRows([], 3).lanes, 0, "no needles, no lanes");

// 1.219：转场牌子占住片段底部那一条带（bottom 1、高 18），所以第 0、1 道在它那一横条里，
// 第 2 道在它之上。横向那一判与纵向分道是同一条规矩：压在底下的那枚不画，交给「+N」说出去。
assert.equal(underSeamBadge(0, 30, 24), true, "第一道、中心 30、牌子 24 宽：抓取盒 20..40 与牌子 0..24 相交");
assert.equal(underSeamBadge(0, 34, 24), false, "中心让到 34（牌子右缘再加半宽）就干净了——贴着边界的那一枚必须点得到");
assert.equal(underSeamBadge(1, 10, 24), true, "第二道也有一部分高度在牌子那一条带里");
assert.equal(underSeamBadge(2, 10, 24), false, "第三道在牌子之上，不受这一判影响");
assert.equal(underSeamBadge(0, 10, 0), false, "没有转场就没有牌子，一枚都不许多藏");
assert.equal(SEAM_BADGE_BOTTOM_PIXELS + SEAM_BADGE_HEIGHT_PIXELS > NEEDLE_BOTTOM_PIXELS + LANE_PITCH_PIXELS, true,
  "牌子那条带至少要盖住第一道，否则这一判是在管一件不存在的事");

// 界面必须真的按这些数画，并且少画的那几条有出路。
const path = ["desktop/src/views/Timeline.tsx", "src/views/Timeline.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the timeline must be readable from the check's working directory");
const source = readFileSync(path!, "utf8");
assert.match(source, /needleRows\(/, "the timeline asks the shared lane splitter");
assert.match(source, /laneCapacity\(/, "and derives how many lanes fit from pixels");
assert.match(source, /bottom: NEEDLE_BOTTOM_PIXELS \+ \(rowOf\.get\(k\.property\) \?\? 0\) \* LANE_PITCH_PIXELS/, "each lane sits at its own bottom offset, counted from the shared constant");
// 只画得了道的针：把 filter 去掉就会又叠回同一堆像素。1.119 起这一份「画出来的那几枚」还要给框选当命中集，
// 所以它先落成一个名字，界面与框选读的都是它——断到那一行本身，去掉 filter 它就变了。
assert.match(source, /const painted = laned\.filter\(\(k\) => rowOf\.has\(k\.property\) && !underBadge\(k\)\);/,
  "画出去的那一枚必须同时过了「有道」与「没压在牌子上」两判——去掉任何一个都会画出一枚点不到的针");
// 1.208：层的针进的是**同一张**道表，所以「画不下的不画」这一句对两只手都成立——两处渲染都必须
// 从 painted 里筛，不许有一排绕过道表自己画（那样就会有两枚针叠在同一堆像素里，正是这一档存在的理由）。
assert.match(source, /const clipPainted = painted\.filter\(\(k\): k is Keyframe => !\("field" in k\)\);/, "片段自己那一排只能画 painted 筛出来的那些");
assert.match(source, /const layerPainted = painted\.filter\(\(k\): k is LayerNeedle => "field" in k\);/, "层那一排同样只能画 painted 筛出来的那些");
assert.doesNotMatch(source, /\{layered\.map\(|layered\.forEach/, "层的针不许绕过道表自己画一排");
assert.match(source, /\{clipPainted\.map\(\(k\) => \{/, "and the diamonds come from that painted set, one name for one fact");
assert.match(source, /\{layerPainted\.map\(\(k\) => \{/, "层的那一排菱形同样只能来自那一份 painted");
assert.doesNotMatch(source, /\{visible\.map\(/, "不许绕过道表直接画片段自己那一排（绕过去就会有两枚针叠在同一堆像素里）");
// 「+N」那枚牌子不许被短路成永不出现：断到它的类型与类名，而不是只断前缀。
assert.match(source, /\{more \? <button type="button" className="clip-keyframe-more"/, "the hidden properties get a named chip instead of an unreachable needle");
assert.match(source, /setGraphOpen\(true\)/, "and clicking that chip opens the curve editor for this clip");
// 「点开进动画曲线」必须真的点得开：片段根节点自己吃了 onPointerDown（那是拖动整条片段的手势），
// 牌子若不把指针交回自己，click 就落在片段上，出路只剩一句提示。装机实测过它点了没反应。
assert.match(source, /onPointerDown=\{\(event\) => event\.stopPropagation\(\)\}[\s\S]{0,60}onClick=\{\(\) => \{ selectClip\(clip\.id\); setGraphOpen\(true\)/,
  "the chip must keep its own click instead of feeding the clip's move gesture");
// 针不许爬到「+N」那块牌子上：牌子上场时右端让开的是它自己的方子（CSS 的 right 8 + min-width 24）
// 再加针伸出去的那一半——1.112 拿 16px 当整块牌子，是把针的 `left`（中心）当成了左边缘。
assert.match(source, /Math\.min\(width - keep,/, "needles reserve the chip's corner");

// 1.219：夹的是**中心**，所以两端都按针自己的半宽夹。写死一个比半宽小的数（原来左端是 6），
// 贴边那一枚就有半个盒子伸出片段之外，`overflow: hidden` 当场把它裁掉——量到的是针从 329 起、
// 片段从 330 起。这一句断的是这一行现在真的按 NEEDLE_HALF_PIXELS 夹两端。
assert.match(source, /const keep = more \? CHIP_KEEP_PIXELS \+ NEEDLE_HALF_PIXELS : NEEDLE_HALF_PIXELS;/,
  "the right-hand reservation is the chip's own box plus the needle's half width, never a guessed literal");
assert.match(source, /Math\.max\(NEEDLE_HALF_PIXELS, \(at \/ clip\.duration_ticks\) \* width\)/,
  "the left end clamps the needle's centre by its own half width, so the box stays inside the clip");
// 那一判只钉夹针这一句：片段自己的最小宽（`Math.max(6, ...)`）是另一件事，别把它算进这笔账。
assert.doesNotMatch(source, /Math\.max\(6, \(at \/ clip\.duration_ticks\)/,
  "夹针的左端不许再用那个比半宽还小的字面 6");

// 转场牌子压在片段左下角那一条带上：抓取盒落进那块矩形的针**不画**，改成「+N」里的一员。
// 断的是画出去的那一行真的问了这个判（上面那一判已经在 `painted` 那一句里钉住），而不是只在模块里备着一个没人调的函数。
assert.match(source, /underSeamBadge\(rowOf\.get\(k\.property\) \?\? 0/, "判它压没压的，是那张道表给出的道号");
assert.match(source, /bottom: SEAM_BADGE_BOTTOM_PIXELS \+ LANE_CLIP_PAD_PIXELS,/, "牌子从片段底往上数，与针同一条尺");
assert.match(source, /width: Math\.max\(SEAM_BADGE_MIN_WIDTH_PIXELS,/, "牌子的最小宽与那一判读同一份数");
assert.match(source, /const more = starved\.length;/, "「+N」数的是没画出来的那几枚针，两处不各数一遍");
assert.match(source, /const rest = \(k: \(typeof laned\)\[number\]\) =>/, "一枚针不拖的时候站哪，只有一个出处");
assert.doesNotMatch(source, /const from = k\.at_ticks - \(clip\.animation_offset_ticks \?\? 0\);/,
  "画的时候不许再自己减一遍偏移——那会有两份「静止位置」的算术");

// 道距必须容得下针的命中盒，否则相邻两道的矩形互相盖住——那就是这次要修的叠像素缺陷的垂直版本。
const cssPath = ["desktop/src/styles.css", "src/styles.css"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(cssPath, "the stylesheet must be readable from the check's working directory");
const css = readFileSync(cssPath!, "utf8");
const rule = css.match(/\.clip-keyframe\s*\{[^}]*\}/);
assert.ok(rule, "the needle rule exists");
const height = /height: *(\d+)px/.exec(rule[0]);
assert.ok(height, "the needle box declares its height");
assert.ok(Number(height[1]) <= 12, `the hit box (${height[1]}px) must not exceed the lane pitch (12px)`);
assert.match(rule[0], /z-index: *5/, "the needle sits above the trim strip, which used to swallow it");
// 1.219：那几个像素只许有一份。CSS 写一遍、判定再数一遍，早晚会对不上——那正是这一档要防的那一类。
assert.equal(Number(height[1]), NEEDLE_HIT_PIXELS, "针的命中盒高度与 keyframeLanes 那个数是同一个");
const needleBottom = /bottom: *(\d+)px/.exec(rule[0]);
assert.ok(needleBottom, "针那一排自己声明离底多少像素");
assert.equal(Number(needleBottom[1]), NEEDLE_BOTTOM_PIXELS, "第一道的下缘与那一判读同一个数");
const clipRule = /\.clip\s*\{[^}]*\}/.exec(css);
assert.ok(clipRule, "片段那一格的规则存在");
for (const side of ["top", "bottom"] as const) {
  const found = new RegExp(`${side}: *(\\d+)px`).exec(clipRule[0]);
  assert.ok(found, `片段的 ${side} 内边距要写明`);
  assert.equal(Number(found[1]), LANE_CLIP_PAD_PIXELS, "牌子从行换算到片段底，靠的就是这一个数");
}
const badgeRule = /\.transition-badge\s*\{[^}]*\}/.exec(css);
assert.ok(badgeRule, "转场牌子的规则存在");
assert.doesNotMatch(badgeRule[0], /top: /, "牌子不许再写那个照着行高猜的 top——那一行由 keyframeLanes 下发");
assert.doesNotMatch(badgeRule[0], /height: /, "它的高度同理只许有一份");

// 1.259：淡角柄也不许盖住针道。扫新那一腿（在画面里点一下「添加向内羽化关键帧」）之后量到的：
// 最左边那一枚针的盒子正压在 `span.fade-handle in` 底下，`elementFromPoint` 回的是柄——
// 针看得见却点不到，正是 1.113 那条「宁可少画，也不留一枚点不到的针」不许留下的形状。
// 让位的是柄（它只服务「拖出一条淡」这一只手），针道那一段高由 `--needle-area` 一处说。
const needleArea = new RegExp("--needle-area: *(\\d+)px").exec(css);
assert.ok(needleArea, "留给针道的那一截高没有一处 CSS 来源");
assert.equal(Number(needleArea[1]), NEEDLE_AREA_PIXELS,
  "CSS 那一档与界面摆针的那一个数分家了（柄让的那一段就不是针道）");
const fadeRule = /\.fade-handle\s*\{[^}]*\}/.exec(css);
assert.ok(fadeRule, "淡角柄那一条规则存在");
assert.match(fadeRule[0], /bottom: var\(--needle-area\)/,
  "柄没有让出针道——它会盖住最左边那一枚针，那枚针就点不到了");
assert.doesNotMatch(fadeRule[0], /bottom: 0/, "同一条规则里不许又写回 bottom: 0");

console.log("PASS: 同一秒上不同属性的针各走一道、道号按第一次出现排、画不下的（含压在转场牌子底下的）明说是哪几条并给出路、容量按像素算且至少一道、淡角柄停在针道之上且那一段高与界面同一个数、那些像素 CSS 与判定同一份");
