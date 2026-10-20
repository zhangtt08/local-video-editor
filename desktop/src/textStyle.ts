/** One text layer's style, shared by both renderers.

The interface draws the caption with these numbers as CSS; the exporter hands the *same* numbers to
FFmpeg's `drawtext`, scaled by the same font size. Everything proportional is expressed in `em` so a
value means one thing in both places: `outline_width: 0.06` is 6 % of the glyph size whether the
browser strokes it or FFmpeg borders it.

It lives apart from the component so the mapping can be asserted without a browser, and the font list
comes from the engine (`capabilities.text_fonts`) — the client never guesses a family name, because a
face the exporter cannot load must not appear in the picker either.
*/

import type { CSSProperties } from "react";

import type { TextStyle } from "./engine";

export type TextFont = { id: string; label: string; family: string };

/** The 1.62 rendering, restated as defaults: an old project reads back with the pixels it had. */
export const TEXT_DEFAULTS = {
  font_size: 0.06,
  color: "#FFFFFF",
  align: "center",
  box: false,
  font: "yahei",
  text_align: "center",
  outline_width: 0.04,
  outline_color: "#000000",
  shadow_x: 0,
  shadow_y: 0,
  shadow_color: "#000000",
  box_color: "#000000",
  box_opacity: 0.45,
  line_spacing: 0.2,
} as const;

/** 1.232：五档文字样式。预设只给「长什么样」的那几格——字号、颜色、上下位置、描边、
 *  阴影与垫子；`body` / `font` / `text_align` / `line_spacing` 是这个人自己的排版，一概不覆盖。
 *  每一格都在契约的量程里（0.01..0.2 的字号与描边、±1 的阴影、0..1 的垫子浓度）。 */
export type TextPreset = { id: string; label: string; hint: string; style: Partial<TextStyle> };

export const TEXT_PRESETS: TextPreset[] = [
  { id: "title", label: "标题", hint: "字号 7.5% 高、米白、细描边、深色垫子", style: {
    font_size: 0.075, color: "#F7F1E3", align: "center", box: true, box_color: "#101418",
    box_opacity: 0.3, outline_width: 0.022, outline_color: "#0B0D10",
    shadow_x: 0.012, shadow_y: -0.02, shadow_color: "#000000" } },
  { id: "subtitle", label: "副标题", hint: "字号 4.2%、浅米、细描边，不垫底", style: {
    font_size: 0.042, color: "#EFE7D8", align: "center", box: false, outline_width: 0.018,
    outline_color: "#0B0D10", shadow_x: 0.008, shadow_y: -0.012, shadow_color: "#000000" } },
  { id: "caption", label: "字幕条", hint: "字号 3.4%、靠下、白字黑描边、半透明黑底", style: {
    font_size: 0.034, color: "#FFFFFF", align: "bottom", box: true, box_color: "#000000",
    box_opacity: 0.55, outline_width: 0.012, outline_color: "#000000",
    shadow_x: 0, shadow_y: 0, shadow_color: "#000000" } },
  { id: "quote", label: "引语", hint: "字号 5%、居中、不描边、轻阴影", style: {
    font_size: 0.05, color: "#F0E6D2", align: "center", box: false, outline_width: 0,
    outline_color: "#0B0D10", shadow_x: 0.01, shadow_y: -0.015, shadow_color: "#000000" } },
  { id: "accent", label: "强调", hint: "字号 8.5%、暖黄、粗描边与硬阴影", style: {
    font_size: 0.085, color: "#FFE08A", align: "center", box: false, outline_width: 0.03,
    outline_color: "#201200", shadow_x: 0.015, shadow_y: -0.025, shadow_color: "#000000" } },
];

export function hexToRgba(color: string, opacity: number): string {
  const value = color.replace("#", "");
  const channels = [0, 2, 4].map((at) => parseInt(value.slice(at, at + 2), 16));
  return `rgba(${channels[0]}, ${channels[1]}, ${channels[2]}, ${opacity})`;
}

/** The band the export draws with `geq`: 1.5 line heights tall, anchored by the vertical alignment. */
export function boxBand(text: TextStyle, heightPercent = 150): string {
  const size = (text.font_size ?? TEXT_DEFAULTS.font_size) * 100;
  const band = size * (heightPercent / 100);
  const align = text.align ?? TEXT_DEFAULTS.align;
  const start = align === "top" ? 8 : align === "bottom" ? 96 - band : (100 - band) / 2;
  const plate = hexToRgba(text.box_color ?? TEXT_DEFAULTS.box_color, boxOpacity(text));
  return `linear-gradient(to bottom, transparent ${start}%, ${plate} ${start}%, ${plate} ${start + band}%, transparent ${start + band}%)`;
}

export function boxOpacity(text: TextStyle): number {
  return text.box === true ? (text.box_opacity ?? TEXT_DEFAULTS.box_opacity) : 0;
}

export function fontFamily(text: TextStyle, fonts: TextFont[]): string {
  const wanted = text.font ?? TEXT_DEFAULTS.font;
  const found = fonts.find((entry) => entry.id === wanted);
  return found ? found.family : "Microsoft YaHei";
}

/** CSS for the caption layer, derived field by field from the same `TextStyle` the exporter reads. */
export function textLayerStyle(text: TextStyle, fonts: TextFont[]): CSSProperties {
  const outlineWidth = text.outline_width ?? TEXT_DEFAULTS.outline_width;
  const shadowX = text.shadow_x ?? TEXT_DEFAULTS.shadow_x;
  const shadowY = text.shadow_y ?? TEXT_DEFAULTS.shadow_y;
  const lineSpacing = text.line_spacing ?? TEXT_DEFAULTS.line_spacing;
  const align = text.align ?? TEXT_DEFAULTS.align;
  const textAlign = text.text_align ?? TEXT_DEFAULTS.text_align;
  const style: CSSProperties = {
    fontSize: `${(text.font_size ?? TEXT_DEFAULTS.font_size) * 100}cqh`,
    color: text.color ?? TEXT_DEFAULTS.color,
    fontFamily: fontFamily(text, fonts),
    lineHeight: String(1 + lineSpacing),
    textAlign,
    alignItems: align === "top" ? "flex-start" : align === "bottom" ? "flex-end" : "center",
    justifyContent: textAlign === "left" ? "flex-start" : textAlign === "right" ? "flex-end" : "center",
    paddingTop: align === "top" ? "8%" : undefined,
    paddingBottom: align === "bottom" ? "8%" : undefined,
  };
  if (outlineWidth > 0) {
    style.WebkitTextStrokeWidth = `${outlineWidth}em`;
    style.WebkitTextStrokeColor = text.outline_color ?? TEXT_DEFAULTS.outline_color;
  }
  if (shadowX !== 0 || shadowY !== 0) {
    style.textShadow = `${shadowX}em ${shadowY}em 0 ${text.shadow_color ?? TEXT_DEFAULTS.shadow_color}`;
  }
  if (text.box) style.background = boxBand(text);
  return style;
}
