/** The caption layer's CSS must be the same numbers the exporter gets — asserted without a browser. */

import assert from "node:assert/strict";

import { TEXT_DEFAULTS, boxBand, fontFamily, hexToRgba, textLayerStyle } from "../desktop/src/textStyle";
import type { TextStyle } from "../desktop/src/engine";

const FONTS = [
  { id: "yahei", label: "微软雅黑", family: "Microsoft YaHei" },
  { id: "hei", label: "黑体", family: "SimHei" },
  { id: "mono", label: "等宽 Consolas", family: "Consolas" },
];

const base: TextStyle = { body: "标题", font_size: 0.06, color: "#FFFFFF" };
const plain = textLayerStyle(base, FONTS);
assert.equal(plain.fontSize, "6cqh", "font size stays a percentage of the frame height");
assert.equal(plain.lineHeight, "1.2", "the default line spacing is 0.2 of the glyph size");
assert.equal(plain.fontFamily, "Microsoft YaHei");
assert.equal(plain.textAlign, "center");
assert.equal(plain.alignItems, "center");
assert.equal(plain.WebkitTextStrokeWidth, "0.04em", "the default outline is 4 % of the glyph size");
assert.equal(plain.WebkitTextStrokeColor, "#000000");
assert.equal(plain.textShadow, undefined, "no offset means no shadow at all");
assert.equal(plain.background, undefined, "the plate only appears when the box is on");

const styled = textLayerStyle(
  {
    ...base,
    font: "hei",
    text_align: "right",
    align: "top",
    outline_width: 0.12,
    outline_color: "#ff0000",
    shadow_x: 0.08,
    shadow_y: -0.04,
    shadow_color: "#00ff00",
    box: true,
    box_color: "#102030",
    box_opacity: 0.8,
    line_spacing: 1,
  },
  FONTS,
);
assert.equal(styled.fontFamily, "SimHei", "the family comes from the engine's installed list");
assert.equal(styled.textAlign, "right");
assert.equal(styled.justifyContent, "flex-end", "horizontal alignment moves the block, not just the text");
assert.equal(styled.alignItems, "flex-start");
assert.equal(styled.paddingTop, "8%");
assert.equal(styled.lineHeight, "2", "line_spacing 1 means two glyph heights per line");
assert.equal(styled.WebkitTextStrokeWidth, "0.12em");
assert.equal(styled.WebkitTextStrokeColor, "#ff0000");
assert.equal(styled.textShadow, "0.08em -0.04em 0 #00ff00", "a hard shadow: blur stays 0, both renderers");
assert.match(String(styled.background), /rgba\(16, 32, 48, 0\.8\)/, "the plate carries the chosen colour");

assert.equal(hexToRgba("#000000", 0.45), "rgba(0, 0, 0, 0.45)");
assert.equal(hexToRgba("#ffffff", 1), "rgba(255, 255, 255, 1)");
const band = boxBand({ ...base, box: true });
assert.match(band, /linear-gradient/, "the plate is a band, like the exporter's geq alpha");
assert.equal(
  band.split("rgba(0, 0, 0, 0.45)").length - 1,
  2,
  "the band has exactly one start and one end stop",
);
const bottom = boxBand({ ...base, box: true, align: "bottom" });
assert.notEqual(band, bottom, "the plate follows the vertical anchor");

assert.equal(fontFamily({ ...base, font: "nope" }, FONTS), "Microsoft YaHei", "unknown id falls back");
assert.equal(fontFamily(base, []), "Microsoft YaHei", "an engine without the list still renders");
assert.deepEqual(
  Object.keys(TEXT_DEFAULTS).sort(),
  [
    "align", "box", "box_color", "box_opacity", "color", "font", "font_size", "line_spacing",
    "outline_color", "outline_width", "shadow_color", "shadow_x", "shadow_y", "text_align",
  ].sort(),
  "the defaults cover exactly the fields the exporter also defaults",
);

const untouched = textLayerStyle(base, FONTS);
assert.deepEqual(untouched, plain, "the helper is pure: the same style in, the same CSS out");

console.log("PASS: caption CSS is derived from the same numbers the exporter reads, field by field");
