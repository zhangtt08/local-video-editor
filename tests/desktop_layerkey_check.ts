/**
 * 1.192 的壳层检查：第二路画面那三个数在界面这一头只有一个主人、一把尺、一张名字表。
 *
 * 为什么单独一档：`tests/layerkey_check.py` 量的是**交付文件里的像素**（两窗各盖自己那一片、
 * 清单==窗表==编译串、两腿同一组数）。屏幕这一头的风险是另外三件事——
 * ① 视图自己再算一遍位置（画面上是一回事、文件里是另一回事，就是 1.98 那一族的老账）；
 * ② 刻度折两次（`animation_offset_ticks` 折在界面一次、引擎再一次，针就落在错的格上）；
 * ③ 界面自带一份属性名或额度（引擎改了数，画面上还在允许导出会拒的那一档）。
 * 这一档把这三件事钉成能失败的断言。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const preview = read("desktop/src/views/Preview.tsx", "../../desktop/src/views/Preview.tsx");
const fields = read("desktop/src/views/GradeFields.tsx", "../../desktop/src/views/GradeFields.tsx");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const contracts = read("src/agentcut/contracts.py", "../../src/agentcut/contracts.py");
const timeline = read("src/agentcut/timeline.py", "../../src/agentcut/timeline.py");
const animation = read("src/agentcut/animation.py", "../../src/agentcut/animation.py");

const count = (text: string, needle: string) => text.split(needle).length - 1;

// 1) 那条把「画面框」换成 CSS 的式子只有一个主人：定义在 effects.ts，视图只调用它。
assert.ok(/export const layerStyle = /.test(effects), "layerStyle 不在 effects.ts 里（那就没有唯一主人）");
assert.equal(count(effects, "(0.5 + offsetX) * 100 - scale * 50"), 1, "同一条式子在 effects.ts 里出现了两遍");
for (const [name, text] of [["Preview.tsx", preview], ["GradeFields.tsx", fields]] as const) {
  assert.ok(!/0\.5 \+ (row|node)\.offset_[xy]\) \* 100/.test(text), `${name} 自己抄了一遍位置式子`);
  assert.ok(!/scale \* 50/.test(text), `${name} 自己算了一遍那半幅`);
}
assert.ok(preview.includes("...layerStyle(row.offset_x, row.offset_y, row.scale, row.rotation ?? 0)"), "静态那一行没在用那唯一的式子");

// 2) 动画帧只从引擎那份窗表来，`easing` 一个都不自己补。
//    断的是 `layerFrames` 那一段函数体自己——`easing: point.easing` 这句在别处也用（柔焦、清晰），
//    只问「整份文件里有没有这句」会放过「层这一份自己造了一个 steps」的改动。
assert.ok(/export function layerFrames\(/.test(effects), "浏览器那份窗表动画帧不在 effects.ts 一处");
const layerBody = effects.match(/export function layerFrames\([\s\S]*?\n\}/)?.[0] ?? "";
assert.ok(layerBody.length > 40, "找不到 layerFrames 那一段函数体");
assert.ok(layerBody.includes("easing: point.easing"), "层那一份动画帧的 easing 不是引擎给的那个串");
assert.ok(!/steps\(/.test(layerBody), "层那一份动画帧里界面自己造了一个 steps 串");
assert.ok(layerBody.includes("layerStyle(point.offset_x, point.offset_y, point.scale)"), "层那一份动画帧的位置不是那唯一的式子算的");
// 1.198：这一层自己会淡——`opacity` 只能从窗表那一个数来，界面不许再读静态那一份。
assert.ok(layerBody.includes("opacity: point.mix"), "层那一份动画帧的淡不是从窗表来的");
assert.equal(count(layerBody, "opacity"), 1, "那一帧里 opacity 写了两遍（那就有了第二个主人）");
assert.ok(preview.includes("layerFrames(row.windows)"), "监视器没在读清单里那份窗表");
assert.ok(/if \(!windows\?\.length\) return null;/.test(layerBody), "没有窗的时候界面该走静态那一条，不该造一个点");

// 3) 刻度只折一次：折的那一处在 effects.ts，视图只把播放头交给它。
assert.ok(/export const layerKeyTick = /.test(effects), "折 offset 的那一处不在 effects.ts");
assert.ok(effects.includes("ticks - clip.position_ticks + (clip.animation_offset_ticks ?? 0)"), "折的那一次换了别的算法");
assert.ok(fields.includes("layerKeyTick(clip, play.ticks)"), "检查器没在用那一处唯一的折法");
assert.ok(!/at_ticks: play\.ticks|at_ticks: ticks -/.test(fields), "检查器自己拼了一遍刻度（那就是第二把尺）");

// 4) 能动的是哪三个数、额度几枚，都听引擎下发；老引擎不回就是「不给这一档」。
// 两边都要钉：卡片读的是 `limits` 里那两份（不是自己写的数），而 `limits` 那两份是从
// capabilities 来的——只钉住一头时，把 caps 那一行换成死数照样绿（这一版第一稿就漏在这）。
assert.ok(fields.includes("layerKeyProps: app.caps?.grade_limits?.layer_key_props ?? []"), "可动名单不是从 capabilities 来的");
assert.ok(fields.includes("layerKeyLimit: app.caps?.limits?.layer_key_limit ?? 0"), "针的额度不是从 capabilities 来的");
assert.ok(fields.includes("limits.layerKeyProps ?? []"), "卡片没在读 limits 里那一份名单");
assert.ok(fields.includes("limits.layerKeyLimit ?? 0"), "卡片没在读 limits 里那一个额度");
assert.ok(fields.includes("if (!props.includes(property) || limit <= 0 || tick === null) return null;"), "打点那颗按钮没有只认引擎那份名单");
assert.equal(count(effects, "这一层往左右"), 1, "那一行中文出现了两遍（名字表该只有一张）");
assert.ok(fields.includes("LAYER_KEY_LABEL"), "检查器没在读那张唯一的名字表");
// 1.198：权重那行的名字只许有一张表——层那一支读的是表里那一个数，不再自带字面量。
// 断的是**层那一支**：合成那一级 1.144 起也有一句「这一层的权重」，那是另一个控件、不该被这一条误伤。
const layerBranch = fields.slice(
  fields.indexOf('if (node.kind === "layer")'),
  fields.indexOf('if (node.kind === "composite")')
);
assert.ok(layerBranch.length > 200, "读不到层那一支的卡片（层与合成的先后换了？）");
assert.equal(count(effects, "这一层的权重"), 1, "权重那行的中文名字在名字表里出现了两遍");
assert.ok(!/label="这一层的权重"/.test(layerBranch), "层那一支自己写了一遍权重的名字（名字表该只有一张）");
assert.ok(fields.includes("label={LAYER_KEY_LABEL.mix}"), "权重那一行的标签不是从名字表来的");
assert.ok(fields.includes('dot("mix", node.mix)'), "检查器没给这一层的淡打点的入口（人能打的只有三个数）");

// 5) 引擎这一头：Literal、两个常数、三份 capabilities，一个都不缺。
assert.ok(
  contracts.includes('LayerProperty = Literal["offset_x", "offset_y", "scale", "mix"]'),
  "契约里那四个可动的数换了名单"
);
const labelKeys = [...effects.matchAll(/^  (offset_x|offset_y|scale|mix): "/gm)].map((row) => row[1]);
const literal = contracts.match(/LayerProperty = Literal\[([^\]]+)\]/)![1];
for (const prop of ["offset_x", "offset_y", "scale", "mix"]) {
  assert.ok(literal.includes(`"${prop}"`), `契约的 LayerProperty 少了 ${prop}`);
  assert.ok(labelKeys.includes(prop), `界面那张表少了 ${prop}`);
}
assert.ok(contracts.includes('"mix": (0.0, 1.0)'), "针的权重值域与静态那一个字段不是同一条带");
assert.ok(contracts.includes("LAYER_KEY_LIMIT = "), "针的额度不是契约里那一个数");
assert.ok(contracts.includes("LAYER_SCHEDULE_MAX = "), "段数上限不是契约里那一个数");
assert.ok(contracts.includes('"layer_key_limit": LAYER_KEY_LIMIT'), "额度没随 capabilities 下发");
assert.ok(contracts.includes('"layer_schedule_segments": LAYER_SCHEDULE_MAX'), "段数上限没随 capabilities 下发");
assert.ok(contracts.includes('"layer_key_props": list(get_args(LayerProperty))'), "可动名单没随 capabilities 下发");
assert.ok(contracts.includes('"layer_keyframes": True'), "features 里少了这一档的开关");
assert.ok(/keys: list\[LayerKeyframe\] = \[\]/.test(contracts), "GradeLayer 没带那份针表（或默认不是空表）");

// 6) 三条拒绝各有中文名，越界那一条在 reducer，两条写入路都问一次（调用点，不是只问 helper）。
for (const code of ["LAYER_KEY_RANGE", "LAYER_KEY_CLASH", "LAYER_KEY_LIMIT"]) {
  assert.ok(new RegExp(`^      ${code}: "`, "m").test(engine), `${code} 没有一行中文提示`);
  assert.ok(contracts.includes(`"${code}"`) || timeline.includes(`"${code}"`), `引擎没用 ${code} 说话`);
}
assert.equal(count(timeline, "_check_layer_clock(clip, command"), 2, "越界那一问只在一条写入路上问（两条都得问）");
assert.ok(timeline.includes("_check_layer_clock(clip, command.color.grade)"), "clip.color 那一路没问刻度");
assert.ok(timeline.includes("_check_layer_clock(clip, command.grade)"), "clip.grade 那一路没问刻度");

// 7) 窗表是唯一的权威：三个数一次采样、界面不许自己 walk。
assert.ok(animation.includes("frame_windows(clip, quantum, ceiling, value_at)"), "层没在走那唯一的切段器");
assert.equal(count(animation, "LAYER_KEY_PROPS"), 2, "那一组三元不是只在一处列出来（切段时要用它）");
assert.ok(!/\.animate\([^)]*offset_x/.test(preview), "监视器自己拿三个数补了一遍中间态");

console.log(
  "desktop_layerkey_check: 那一层在界面只有一个主人、一把尺、一张名字表——位置式子只在 effects.ts、窗表只从清单来、" +
  "刻度只折一次、名单与额度都听 capabilities，越界那一条两条写入路都问"
);
