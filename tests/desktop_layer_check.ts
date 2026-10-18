/**
 * 1.189 的壳层检查：第二路画面（`layer` 节点）在界面这一头只有一处来源。
 *
 * 为什么单独一档：引擎那一条 `tests/layer_check.py` 量的是**交付文件里的像素**（八种方式逐档对得上、
 * 权重是中点、补边不盖黑边）。这一档量的是屏幕这一头——监视器叠的那几张图、检查器那三个控件、
 * 层数那个上限，都必须读引擎下发的同一份清单与同一个数。界面自己算一遍「大概差不多」的混合，
 * 就是 1.98 那一族（导出与预览各画一张图）的新版本。
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
const graph = read("desktop/src/gradeGraph.ts", "../../desktop/src/gradeGraph.ts");
const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const contracts = read("src/agentcut/contracts.py", "../../src/agentcut/contracts.py");
// 拒绝的句子由引擎说，但说不说在契约那一层还是在 reducer 那一层是各条自己的事：两处都算「在用它」。
const timeline = read("src/agentcut/timeline.py", "../../src/agentcut/timeline.py");

// 1) 监视器：层只从清单来，素材 URL 只从那份 streams 来，两个数一个都不自己算。
assert.ok(preview.includes("(plan?.layer ?? []).map"), "监视器没在读引擎下发的层清单");
assert.ok(
  preview.includes("src={streams[row.asset_id]}"),
  "层的画面不是从那份唯一的素材 URL 表里拿的"
);
// 1.200：画不画得成只听清单那一行说的 `paintable`，视图不许自己去翻素材表猜。
// 那一层画不成时监视器必须说一句（安静地少画一层 = 预览与导出又开始各说各话）。
assert.ok(preview.includes("map((row, index) => row.paintable ? <img"), "那一层画不成时视图还是照画不误");
assert.ok(preview.includes("(plan?.layer ?? []).some((row) => !row.paintable)"), "画不成的那一层没在监视器里说一句");
assert.equal(
  (preview.match(/row\.paintable/g) ?? []).length,
  2,
  `那一层画不画得成在视图里判了 ${(preview.match(/row\.paintable/g) ?? []).length} 次，该恰好两处（画与说）`
);
assert.equal(
  (preview.match(/edge\?\.paintable/g) ?? []).length,
  1,
  "1.193 那条边的判断不该被这一轮搬动"
);
assert.ok(preview.includes('<p className="layer-offline" role="status">'), "那句实话不是 role=status 的一条");
assert.ok(!/assets\[row\.asset_id\]/.test(preview), "视图自己去看素材表了（判断该由引擎一处说）");
assert.ok(css.includes(".layer-offline {"), "那句实话没有样式（画不出来等于没说）");
assert.ok(/\.layer-offline \{[^}]*border-radius: var\(--r-lg\)/.test(css), "那句实话不是 1.199 那一档圆角");
const layerType = /layer\?: \{[^}]*\}\[\]/.exec(engine)?.[0] ?? "";
assert.ok(layerType.length > 40, `读不到清单里那一行的类型：${layerType.slice(0, 40)}`);
assert.ok(
  /paintable: boolean/.test(layerType) && /reason\?: string \| null/.test(layerType),
  "渲染层的类型不认这一行的实话（层那一行的类型没跟着改；合成那条边也带 paintable，别混作一处）"
);
assert.ok(
  preview.includes("mixBlendMode: row.mode, opacity: row.mix"),
  "方式与权重被界面改写过（导出读的是引擎那一份）"
);
assert.ok(
  !/mixBlendMode:\s*"(multiply|screen|overlay|difference)"/.test(preview),
  "监视器自己写死了一个混合方式"
);
// 层只能与这一段自己的画面相合：不 isolate 就会穿到别的轨道底下去。
assert.ok(/\.preview-layer\s*\{[^}]*isolation:\s*isolate/.test(css), ".preview-layer 没有 isolate");
assert.ok(/\.layer-grade\s*\{[^}]*object-fit:\s*fill/.test(css), ".layer-grade 没有铺满它那一块");
// 出界的那部分由容器裁掉——导出那一头是「夹到交付帧里」，两端说的是同一件事。
assert.ok(/\.preview-layer\s*\{[^}]*overflow:\s*hidden/.test(css), ".preview-layer 不裁掉出界的层");

// 2) 检查器：三个控件都在，词表只有一份，层数上限读引擎下发的数。
assert.ok(fields.includes('aria-label="外部画面层的素材"'), "检查器没有那张「叠哪一张画面」的选择");
assert.ok(fields.includes('aria-label="外部画面层的混合方式"'), "检查器没有相合方式的下拉");
assert.ok(fields.includes("-layer-mix"), "检查器没有这一层那根权重");
// 1.190：位置与大小三颗旋钮都在，且上下限读的是引擎下发的那三个数。
for (const id of ["-layer-x", "-layer-y", "-layer-scale"]) {
  assert.ok(fields.includes(id), `检查器少了那一颗：${id}`);
}
assert.ok(fields.includes("layer_offset_max"), "位置与缩放的上下限不是从 capabilities 来的");
assert.ok(!/offset_x: round\(value\/100\)/.test(fields.replace(/\s+/g, "")) || fields.includes("limits.layerOffsetMax"), "界面上限自己写了数");
// 1.192 改了那一行的形状（每行多带自己那份窗表），所以这里问的不再是一整段字面量，
// 而是「那一行到底有没有这四个字段」——把式子换成按字段核，旧的三颗旋钮少一个照样红。
const layerRow = engine.match(/layer\?: \{([^}]*)\}\[\]/)?.[1] ?? "";
for (const field of ["offset_x: number", "offset_y: number", "scale: number", "windows?: LayerWindow[]"]) {
  assert.ok(layerRow.includes(field), `清单那一行少了 ${field}`);
}
assert.ok(preview.includes("row.offset_x") && preview.includes("row.scale"), "监视器没按清单里的位置与大小画这一层");
assert.ok(
  fields.includes('kind === "layer" && enabledLayers >= (limits.layers ?? 0)'),
  "加层那颗按钮没按引擎下发的上限挡"
);
assert.ok(fields.includes("max_layers"), "limits.layers 不是从 capabilities.grade_limits 来的");
assert.ok(
  fields.includes('kind === "lut3d" || node.kind === "composite" || node.kind === "layer"'),
  "通用那条支路还当外部画面层有强度与混合方式可给"
);
// 视图不许自带第二份模式名字表：八种只能从 BLEND_MODES 出去。
const layerBranch = fields.slice(fields.indexOf('if (node.kind === "layer")'), fields.indexOf('if (node.kind === "composite")'));
assert.ok(layerBranch.includes("BLEND_MODES.map"), "层那一格没用引擎下发的那份模式表");
assert.ok(!/"(正片叠底|滤色|叠加|差值)"/.test(layerBranch), "层那一格抄了一份中文模式名");

// 3) 默认值与名字只住在一处，而且契约里有这一格。
assert.ok(graph.includes('layer: "叠一张外部画面"'), "节点名字表里没有外部画面层");
assert.ok(graph.includes("export const DEFAULT_LAYER"), "默认值不在那张唯一的表里");
assert.ok(fields.includes("DEFAULT_LAYER"), "检查器自己写了一份默认值");
assert.ok(contracts.includes('kind: Literal["layer"]'), "契约里没有这一格");
assert.ok(contracts.includes("GRADE_LAYER_LIMIT = "), "上限不是契约里那一个数");
for (const code of ["LAYER_LIMIT", "LAYER_POSITION", "LAYER_ASSET_UNAVAILABLE"]) {
  assert.ok(
    contracts.includes(`"${code}"`) || timeline.includes(`"${code}"`),
    `引擎没在用 ${code} 说话（契约与 reducer 两处都没有）`
  );
  assert.ok(
    new RegExp(`^      ${code}: "`, "m").test(engine),
    `${code} 没有一行中文提示（error_vocabulary_check 会把两边对起来）`
  );
}

// 1.203：那一层会转。这一族的规矩还是「式子只有一处、数只听引擎」，而且钉的是**调用点**——
// 只在 helper 里出现过 `rotation` 不等于监视器真的转了（那一课已经付过一次学费）。
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const styleBody = effects.slice(effects.indexOf("export const layerStyle"), effects.indexOf("export function layerFrames"));
assert.ok(/layerStyle = \(offsetX: number, offsetY: number, scale: number, rotation = 0\)/.test(styleBody), "那一条唯一的式子不接转角");
assert.ok(styleBody.includes("`rotate(${rotation}deg)`"), "式子没有把转角交给 CSS");
assert.ok(styleBody.includes("...(rotation ? { transform"), "0° 也在写 transform：那种层的 DOM 不该被动过");
assert.ok(preview.includes("layerStyle(row.offset_x, row.offset_y, row.scale, row.rotation ?? 0)"), "监视器没把清单里的转角喂进那一条式子");
assert.ok(!/layerStyle\([^)]*offset_x[^)]*,\s*\)/.test(preview), "监视器自己又拼了一遍式子");
// 上限听引擎：卡片读 `limits.layerRotationMax`，而那一份是从 grade_limits 来的——两头都要钉。
assert.ok(fields.includes("layerRotationMax: app.caps?.grade_limits?.layer_rotation_max ?? 0"), "转角的上下限不是从 capabilities 来的");
assert.ok(layerBranch.includes("const rotationMax = limits.layerRotationMax ?? 0;"), "层那一格没读 limits 里那一个上限");
assert.ok(layerBranch.includes('label="这一层转多少度"'), "层那一格没有那颗旋钮");
assert.ok(layerBranch.includes("{rotationMax ? <Num"), "老引擎不回上限时那颗旋钮照样会出现");
assert.ok(engine.includes("layer_rotation_max?: number;"), "能力表的类型里少了这一格");
assert.ok(/kind: "layer"[^}]*rotation\?: number/.test(engine), "界面那份层节点的类型里少了转角");
assert.ok(/layer\?: \{[^}]*rotation\?: number/.test(engine), "监视器清单那一行的类型里少了转角");
assert.ok(contracts.includes("LAYER_ROTATION_MAX = "), "转角的上限不是契约里那一个数");
assert.ok(contracts.includes('"layer_rotation_max": LAYER_ROTATION_MAX'), "上限没随 capabilities 下发");
assert.ok(contracts.includes('"layer_rotation": True'), "features 里少了这一档的开关");
assert.ok(/rotation: Annotated\[float, Field\(ge=-LAYER_ROTATION_MAX, le=LAYER_ROTATION_MAX\)\] = 0\.0/.test(contracts), "GradeLayer 没带那一个默认 0 的转角字段");
// 转角只能静态：它不在引擎那份可动名单里，界面那句「还不能打点」才说得住（说了能做就是谎）。
assert.ok(contracts.includes('LayerProperty = Literal["offset_x", "offset_y", "scale", "mix"]'), "可动名单里混进了转角（界面那句话就过时了）");
assert.ok(layerBranch.includes("还不能打点"), "卡片没说清这一档不能打点");

console.log(
  "desktop_layer_check: 第二路画面在界面只读引擎那份清单与那个数——层从清单来、URL 从 streams 来、方式与权重不改写，且 .preview-layer 隔离"
);
