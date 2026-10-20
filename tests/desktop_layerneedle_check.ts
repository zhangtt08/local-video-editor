/**
 * 1.206 立的那只口径，1.208 把它从「只数」扩成「能拖」：片段条上层的针与片段自己的针进同一张道表。
 *
 * 为什么单独一档：层的针存在 `clip.color.grade` 那条链里，不在 `clip.keyframes` 上。时间线那一行
 * 如果只数 `clip.keyframes`，那一层明明在动、条上却一个交代都没有（1.206 治的就是这个）。
 * 1.208 起这一层不再只是被数进去：画得下的那几枚就画在条上、能横向拖时间，写回去的还是那一条
 * `clip.grade` 整链替换。所以这一档钉的是三件事：**只有一个主人**（`layerNeedles` 那一处）、
 * **只有一张道表**（画不下的才进 +N，两处不许各数一遍）、**只有一条写口**（不许长出第二种落库）。
 * 1.206 那份 `layerKeyedRows` 已经删掉——它数的那一行如今由道表的 `hidden` 交回，留着就是第二个主人。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const timeline = read("desktop/src/views/Timeline.tsx", "../../desktop/src/views/Timeline.tsx");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const drag = read("desktop/src/keyframeDrag.ts", "../../desktop/src/keyframeDrag.ts");
const lanes = read("desktop/src/keyframeLanes.ts", "../../desktop/src/keyframeLanes.ts");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");

const body = (src: string, name: string) => {
  const at = src.indexOf(`export function ${name}`);
  assert.ok(at !== -1, `找不到 ${name}`);
  const next = src.indexOf("\nexport ", at + 1);
  return src.slice(at, next === -1 ? src.length : next);
};

// ① 每一枚层的针只有一处算法，并且是时间线调用那一处；那个数行的旧主人必须已经不在。
const needles = body(effects, "layerNeedles");
assert.equal((effects.match(/export function layerNeedles/g) ?? []).length, 1, "层的针的算法必须只有一处");
assert.equal((effects.match(/function layerKeyedRows/g) ?? []).length, 0, "1.206 那个数行的主人还在——道表已经数过一遍，留着就是两个主人");
assert.match(timeline, /const layered = layerNeedles\(clip\);/, "时间线没有去问那一处要层的针");
assert.match(timeline, /import \{[^}]*layerNeedles[^}]*\} from "\.\.\/effects"/s, "时间线没有从 effects 拿那一处");

// ② 口径与曲线编辑器同源：链里**启用**的那几层、按链里的顺序数。
assert.match(needles, /node\.kind !== "layer" \|\| !node\.enabled/, "没有按启用与否筛，顺序会与曲线那一份错开");
assert.match(needles, /layer \+= 1/, "没有按链里的顺序数层号");

// ③ 刻度夹在本片段的动画窗口内——与片段自己那一条 visible 同一口径，越窗的针不许出现。
assert.match(needles, /clip\.animation_offset_ticks \?\? 0/, "没有折掉动画起点");
assert.match(needles, /offset \+ clip\.duration_ticks/, "没有按片段长度夹窗口");
assert.match(needles, /at_ticks: key\.at_ticks - offset/, "条上的位置用的不是片段本地的刻度，贴边那枚会画错");

// ④ 一道曲线的名字只有一处拼法：曲线编辑器与条上的针说的是同一道，不能各拼各的。
// 「不许出现第二遍」这一条只数代码——第一版把它数到了自己那句解释拼法的注释上，红得莫名其妙。
const effectsCode = effects.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
assert.match(effects, /export const layerNeedleProperty = \(layer: number, key: LayerProperty\) => `layer\$\{layer\}:\$\{key\}`;/, "复合键的拼法不在那一处");
assert.match(effects, /property: layerNeedleProperty\(layer, prop as LayerProperty\)/, "曲线编辑器没有用那一处拼名字");
assert.equal((effectsCode.match(/`layer\$\{layer\}:\$\{[a-z]+\}`/g) ?? []).length, 1, "复合键被拼了第二遍——两处会有一天对不上");

// ⑤ 「+N」数的是**画不下的那些行**：片段自己的与层的在同一张道表里分道，谁画不下谁进牌子。
assert.match(timeline, /const laned = \[\.\.\.visible, \.\.\.layered\];/, "层的针没有进同一张道表（分开两张就会出现两枚针叠在一起）");
assert.match(timeline, /needleRows\(laned, laneCapacity\(NEEDLE_AREA_PIXELS\)\)/, "分道问的不是那一处容量算术");
assert.match(timeline, /const more = starved\.length;/, "+N 还在自己数一遍（1.219 起它数的是没画出来的那几枚针，含被转场牌子压住的）");
assert.match(timeline, /\+\{more\}<\/button>/, "那枚牌子写的还是旧数目");
assert.equal((timeline.match(/clip-keyframe-more/g) ?? []).length, 1, "片段条上不许出现两枚 +N");
assert.match(timeline, /LAYER_KEY_LABEL\[row\.field\.key\] \?\? row\.field\.key/, "牌子上没有说清是第几层的哪个数");
assert.match(timeline, /`第 \$\{row\.field\.layer \+ 1\} 层 /, "牌子上的层号要与人眼看见的一致（从 1 数）");
assert.match(timeline, /FIELD_LABEL\[property as keyof typeof FIELD_LABEL\] \?\? property/, "牌子把片段自己的针弄丢了");

// ⑥ 右端让开的是牌子自己的方子加针伸出去的那一半（1.206 量对的那笔旧账，一字不改仍要钉住）。
assert.match(timeline, /const keep = more \? CHIP_KEEP_PIXELS \+ NEEDLE_HALF_PIXELS : NEEDLE_HALF_PIXELS;/, "让位的距离没跟着牌子走（1.219 起两端都按针自己的半宽夹）");
assert.match(timeline, /Math\.min\(width - keep,/, "针的夹法还在自己算右端，不看那两个数");
assert.match(lanes, /export const CHIP_KEEP_PIXELS = 32;/, "牌子占住的距离不在那一处下发");
assert.match(lanes, /export const NEEDLE_HALF_PIXELS = 10;/, "针自己伸出去的那一半不在那一处下发");
assert.match(css, /\.clip-keyframe-more \{[^}]*right: 8px[^}]*min-width: 24px/, "CSS 与那两个数分家了：牌子会换方子，代码却不知道");

// ⑦ 牌子仍然是一颗真按钮：点它进曲线编辑器。
assert.match(timeline, /onClick=\{\(\) => \{ selectClip\(clip\.id\); setGraphOpen\(true\); \}\}/, "牌子不再带人进曲线编辑器");

// ⑧ 1.208 那一档的正题：画得下的那枚层针能在条上拖时间，而写只有一条路。
assert.match(timeline, /className=\{`clip-keyframe layer-needle/, "层针没有自己的那一档外观（与片段自己的针混成一种，人不知道拖的是谁）");
assert.match(timeline, /onPointerDown=\{\(event\) => startLayerKey\(event, k\)\}>◈<\/button>/, "层针不能被拖");
assert.match(css, /\.clip-keyframe\.layer-needle \{ color: var\(--clip-image-stripe\); \}/, "层针的颜色没走刻度");
// 框选的那只手挑中的是「一条曲线上的几枚针」，层针的曲线在检查器与动画曲线里各有名字：混进这一组
// 就会有一枚针被两条路同时改，所以框里根本不收它。
assert.match(timeline, /\.clip-keyframe:not\(\.ghost\):not\(\.layer-needle\)/, "框选没有把层针让出去（拖整组会同时改到一枚写不进 keyframes.move 的针）");
const hand = body(drag, "planLayerNeedleDrag");
assert.match(hand, /keyframeTick\(/, "层针的落点没走那一份共用的吸附");
assert.match(hand, /clampGroupTimeShift\(\[drag\.from\], span, at - drag\.from\)/, "层针没有夹在片段两头内");
assert.match(hand, /commands: \[layerKeyCommand\(drag\.clip, drag\.field, next\)\]/, "层针写的不是那一条 clip.grade——界面上就会出现第二种落库");
assert.match(hand, /const next = drag\.duplicate/, "复制与拖动在哪一路分岔只许有一处判断");
assert.match(hand, /\[\.\.\.sameCurve, \.\.\.sameCurve\.filter\(\(key\) => key\.at_ticks === drag\.from\)\.map\(\(key\) => \(\{ \.\.\.key, at_ticks: to \}\)\)\]/, "复制那一路不许自己编一个数：它搬的是抓住那一枚的值与插法");
assert.match(hand, /: sameCurve\.map\(\(key\) => \(key\.at_ticks === drag\.from \? \{ \.\.\.key, at_ticks: to \} : key\)\)/, "交回的不是那一道曲线的全部针（与曲线编辑器同一个契约）");
// 1.211：条上那两只手的主人只许有一个——落点、撞针、复制与删的算术都在 `planLayerNeedle*` 这两处。
const removal = body(drag, "planLayerNeedleRemoval");
assert.match(removal, /layerKeysRead\(clip, field\)/, "删那一枚之前读的仍是那一份共用的读法");
assert.match(removal, /layerKeyCommand\(clip, field, sameCurve\.filter\(\(key\) => key\.at_ticks !== at\)\)/, "删走的仍是那一条 clip.grade，交回的是这一道的其余针");
assert.match(removal, /if \(!sameCurve\.some\(\(key\) => key\.at_ticks === at\)\) return null;/, "那一枚不在就一条命令都不发（撤销台上不许留一步空操作）");
assert.doesNotMatch(removal, /op: "keyframe\./, "删层针也不许冒充片段自己的那两条命令");
assert.equal((drag.match(/export function planLayerNeedle/g) ?? []).length, 2, "层针的规划只有「拖（含复制）」与「删」这两处主人，别在界面里再算一遍");
// 1.208 顺手还清的一笔旧账：写一层的一个数，不许把同层别的数的针抹掉。
// 1.204~1.207 那一路是整层覆盖，曲线编辑器的夹具只喂过一道曲线，所以直到条上画出两枚不同数的针才量到。
assert.match(effects, /const others = \(node\.keys \?\? \[\]\)\.filter\(\(key\) => key\.property !== field\.key\);/, "同层别的数的针没有被留下来");
assert.match(effects, /keys: \[\.\.\.others, \.\.\.stamped\]\.sort\(\(a, b\) => a\.at_ticks - b\.at_ticks\)/, "写回去的不是「别的数 + 这一道」那份并集");
assert.doesNotMatch(hand, /op: "keyframe\./, "层针不许冒充片段自己的那两条命令（引擎只认 clip.grade）");

console.log(
  "PASS: 层的针与片段自己的针进同一张道表（启用层、链序、窗口内、复合键一处拼法），画不下的才进 +N，" +
    "画得下的那枚在条上能拖时间，写的还是那一条 clip.grade"
);
