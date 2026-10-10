/** 时间线的针分道：同一秒上的两枚针不许抢同一堆像素。

 缺陷是量出来的（1.112 的打包 exe + Chromium）：一条片段上 `opacity` 与 `x` 各有一枚针在 1.0 秒时，
 两个按钮的 getBoundingClientRect 完全相同，`elementFromPoint` 在其中一枚的中心回的是另一枚，也就是
 说那一枚鼠标点不到——连「点一下跳过去」都做不到。修法是一条属性一道，画不下的属性不画，改成一枚
 「+N」的牌子指回动画曲线：宁可少画，也不留一枚点不到的针。

 这里断的是分道本身：道号由属性第一次出现的顺序定、同一秒的不同属性必得不同道、容量按像素算、
 超出容量的属性进 hidden（界面据此少画并说明），以及界面真的用上了这两个函数。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { laneCapacity, needleRows, LANE_PITCH_PIXELS } from "../desktop/src/keyframeLanes";

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

// 界面必须真的按这些数画，并且少画的那几条有出路。
const path = ["desktop/src/views/Timeline.tsx", "src/views/Timeline.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the timeline must be readable from the check's working directory");
const source = readFileSync(path!, "utf8");
assert.match(source, /needleRows\(/, "the timeline asks the shared lane splitter");
assert.match(source, /laneCapacity\(/, "and derives how many lanes fit from pixels");
assert.match(source, /bottom: 1 \+ \(rowOf\.get\(k\.property\) \?\? 0\) \* LANE_PITCH_PIXELS/, "each lane sits at its own bottom offset");
// 只画得了道的针：把 filter 去掉就会又叠回同一堆像素，所以断到链式调用的下一环。
assert.match(source, /visible\.filter\(\(k\) => rowOf\.has\(k\.property\)\)\.map\(\(k\) => \{/, "needles of hidden properties must not be drawn at all");
// 「+N」那枚牌子不许被短路成永不出现：断到它的类型与类名，而不是只断前缀。
assert.match(source, /\{hidden\.length \? <button type="button" className="clip-keyframe-more"/, "the hidden properties get a named chip instead of an unreachable needle");
assert.match(source, /setGraphOpen\(true\)/, "and clicking that chip opens the curve editor for this clip");

console.log("PASS: 同一秒上不同属性的针各走一道、道号按第一次出现排、画不下的明说是哪几条并给出路、容量按像素算且至少一道");
