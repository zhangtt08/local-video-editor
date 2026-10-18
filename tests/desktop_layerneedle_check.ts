/**
 * 1.206 的壳层检查：片段条上那枚「+N」必须把层的针也算进去，并且只有一个主人。
 *
 * 为什么单独一档：层的针存在 `clip.color.grade` 那条链里，不在 `clip.keyframes` 上。
 * 时间线那一行如果只数 `clip.keyframes`，那一层明明在动、片段条却一个交代都没有——
 * 用户只能把每一颗片段点开进曲线编辑器才知道有没有针。断的都是源文件里那一处实现，
 * 不是注释里的一句话；真页面那一段另有 `page_proof_1206needle.py`。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const timeline = read("desktop/src/views/Timeline.tsx", "../../desktop/src/views/Timeline.tsx");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const lanes = read("desktop/src/keyframeLanes.ts", "../../desktop/src/keyframeLanes.ts");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");

const body = (src: string, name: string) => {
  const at = src.indexOf(`export function ${name}`);
  assert.ok(at !== -1, `找不到 ${name}`);
  const next = src.indexOf("\nexport ", at + 1);
  return src.slice(at, next === -1 ? src.length : next);
};

// ① 层的针那一行只有一处算法，并且是被时间线调用那一处。
const rows = body(effects, "layerKeyedRows");
assert.equal((effects.match(/export function layerKeyedRows/g) ?? []).length, 1, "层行的算法必须只有一处");
assert.match(timeline, /layerKeyedRows\(clip\)/, "时间线没有去数层的针");
assert.match(timeline, /import \{[^}]*layerKeyedRows[^}]*\} from "\.\.\/effects"/s, "时间线没有从 effects 拿那一处");

// ② 口径与曲线编辑器同源：链里**启用**的那几层、按链里的顺序数。
assert.match(rows, /node\.kind !== "layer" \|\| !node\.enabled/, "层行没有按启用与否筛，顺序会与曲线那一份错开");
assert.match(rows, /layer \+= 1/, "层行没有按链里的顺序数层号");

// ③ 刻度夹在本片段的动画窗口内——与片段自己那一条 visible 同一口径，越窗的针不许算进 +N。
assert.match(rows, /clip\.animation_offset_ticks \?\? 0/, "层行没有折掉动画起点");
assert.match(rows, /offset \+ clip\.duration_ticks/, "层行没有按片段长度夹窗口");

// ④ 一格一行的是 (层, 数) 这一对，不是「这一层有针」那种含糊数法。
assert.match(rows, /new Set<LayerProperty>/, "同一层的两个数会被数成一行");
assert.match(rows, /out\.push\(\{ layer, property \}\)/, "层行没有把层号与属性一起交出去");

// ⑤ 「+N」那枚牌子说的是画不下的那些属性：两片来源合起来，标签各归各的表。
assert.match(timeline, /const more = hidden\.length \+ layered\.length/, "+N 没有把层的针加进总数");
assert.match(timeline, /\+\{more\}<\/button>/, "那枚牌子写的还是旧数目");
assert.equal((timeline.match(/clip-keyframe-more/g) ?? []).length, 1, "片段条上不许出现两枚 +N");
assert.match(timeline, /LAYER_KEY_LABEL\[row\.property\]/, "牌子上没有说清是第几层的哪个数");
assert.match(timeline, /`第 \$\{row\.layer \+ 1\} 层 /, "牌子上的层号要与人眼看见的一致（从 1 数）");
assert.match(timeline, /FIELD_LABEL\[property\] \?\? property/, "牌子把片段自己的针弄丢了");

// ⑥ 右端让开的是牌子自己的方子加针伸出去的那一半：针的 `left` 是**中心**（CSS 用 translateX(-50%)），
// 1.112 那句 16px 把它当成左边缘量，牌子上场就会压住一枚针（真页面量到 1 枚，本轮改掉）。
assert.match(timeline, /const keep = more \? CHIP_KEEP_PIXELS \+ NEEDLE_HALF_PIXELS : 6;/, "让位的距离没跟着牌子走");
assert.match(timeline, /Math\.min\(width - keep,/, "针的夹法还在自己算右端，不看那两个数");
assert.match(lanes, /export const CHIP_KEEP_PIXELS = 32;/, "牌子占住的距离不在那一处下发");
assert.match(lanes, /export const NEEDLE_HALF_PIXELS = 10;/, "针自己伸出去的那一半不在那一处下发");
assert.match(css, /\.clip-keyframe-more \{[^}]*right: 8px[^}]*min-width: 24px/, "CSS 与那两个数分家了：牌子会换方子，代码却不知道");

// ⑦ 牌子仍然是一颗真按钮：鼠标点它进曲线编辑器，不停留在提示上。
assert.match(timeline, /onClick=\{\(\) => \{ selectClip\(clip\.id\); setGraphOpen\(true\); \}\}/, "牌子不再带人进曲线编辑器");

console.log("PASS: 片段条上那枚 +N 把层的针算进同一只口径（启用层、链序、窗口内），并且让位、标签、入口都跟着走");
