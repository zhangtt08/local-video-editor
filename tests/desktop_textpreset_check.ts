// 1.232：五档文字样式预设——只动「长什么样」的那几格，不碰这个人自己的排版。
//
// 判四件事：每一格都在契约的量程里；预设从不带 body / font / text_align / line_spacing；
// 合并之后正文与字体一字未动；界面只从这张表读名字，写只走 setClipText 一条路。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { TEXT_DEFAULTS, TEXT_PRESETS } from "../desktop/src/textStyle";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

// ① 表本身：至少四档、名字不重、每档都有一句说明
assert.ok(TEXT_PRESETS.length >= 4, `只有 ${TEXT_PRESETS.length} 档预设`);
assert.equal(new Set(TEXT_PRESETS.map((preset) => preset.label)).size, TEXT_PRESETS.length, "有两档同名");
assert.ok(TEXT_PRESETS.every((preset) => preset.hint.trim().length > 0), "有预设没有说明");

// ② 每一格都在契约的量程里（数字与颜色逐个查，不靠引擎那一次拒绝）
const COLOR = /^#[0-9A-Fa-f]{6}$/;
const LIMITS: Record<string, [number, number]> = {
  font_size: [0.01, 0.2], outline_width: [0, 0.2],
  shadow_x: [-1, 1], shadow_y: [-1, 1], box_opacity: [0, 1],
};
const ALLOWED = new Set([
  "font_size", "color", "align", "box", "outline_width", "outline_color",
  "shadow_x", "shadow_y", "shadow_color", "box_color", "box_opacity",
]);
for (const preset of TEXT_PRESETS) {
  for (const [key, value] of Object.entries(preset.style)) {
    assert.ok(ALLOWED.has(key), `${preset.label} 带了不该由预设决定的 ${key}`);
    if (key in LIMITS) {
      const [lo, hi] = LIMITS[key];
      assert.ok(typeof value === "number" && value >= lo && value <= hi,
        `${preset.label}.${key} = ${value} 不在 [${lo}, ${hi}]`);
    } else if (key.endsWith("color")) {
      assert.ok(typeof value === "string" && COLOR.test(value), `${preset.label}.${key} 不是 #RRGGBB`);
    } else if (key === "align") {
      assert.ok(["top", "center", "bottom"].includes(String(value)), `${preset.label}.align 认不得`);
    } else if (key === "box") {
      assert.equal(typeof value, "boolean", `${preset.label}.box 不是布尔`);
    }
  }
}

// ③ 这个人自己的排版不许被预设带走：正文、字体、横排、行距
const base = { ...TEXT_DEFAULTS, body: "这一句是人打的", font: "song", text_align: "left" as const, line_spacing: 0.5 };
for (const preset of TEXT_PRESETS) {
  const merged = { ...base, ...preset.style };
  assert.equal(merged.body, base.body, `${preset.label} 把正文改了`);
  assert.equal(merged.font, base.font, `${preset.label} 把字体改了`);
  assert.equal(merged.text_align, base.text_align, `${preset.label} 把横排改了`);
  assert.equal(merged.line_spacing, base.line_spacing, `${preset.label} 把行距改了`);
}

// ④ 五档真的长得不一样：字号至少四种、垫子有开有关、上下位置有区别
assert.ok(new Set(TEXT_PRESETS.map((preset) => preset.style.font_size)).size >= 4, "字号档位太少，预设只是改名");
assert.ok(TEXT_PRESETS.some((preset) => preset.style.box === true) && TEXT_PRESETS.some((preset) => preset.style.box === false),
  "五档里垫子全开或全关");
assert.ok(new Set(TEXT_PRESETS.map((preset) => preset.style.align)).size >= 2, "五档的上下位置全一样");

// ⑤ 界面：只读这张表、写只走 setClipText、名字不另抄一份
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
assert.match(inspector, /import \{ TEXT_PRESETS \} from "\.\.\/textStyle"/, "界面没有读那张表");
assert.match(inspector, /TEXT_PRESETS\.map\(\(preset\) => <button/, "没有把表画成一排按钮");
assert.match(inspector, /setClipText\(clip\.id, preset\.style\)/, "预设没有走那一条写入口");
for (const preset of TEXT_PRESETS) {
  assert.ok(!inspector.includes(`"${preset.label}"`), `界面自己抄了预设名「${preset.label}」——表就不止一张了`);
}
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
assert.match(css, /\.text-presets \{[^}]*flex-wrap: wrap/, "那排胶囊不换行，窄栏里会被挤成一条");
assert.match(css, /\.text-presets \{[^}]*gap: 6px/, "胶囊之间没有间隔");

console.log(`PASS: ${TEXT_PRESETS.length} 档文字预设都在量程里、不碰正文与字体、彼此真的不同，界面只读这一张表`);
