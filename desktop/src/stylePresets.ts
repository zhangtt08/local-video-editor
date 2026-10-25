import type { Command, Effects } from "./engine";
import { editAtRevision, get, toast } from "./store";

/**
 * 剪辑风格模板：只写引擎已经有的两件事——片段色彩（`clip.patch.color`）与效果
 * （`clip.patch.effects`）。一次点击把所有选中片段写进**一个批次**，一个 revision。
 * 这里没有一个「只活在界面里」的字段：导出的就是这些数。
 */
export type StylePreset = {
  id: string;
  name: string;
  desc: string;
  swatch: [string, string];
  color: { exposure: number; contrast: number; saturation: number };
  effects?: Partial<Pick<Effects, "sharpen" | "sharpen_radius" | "blur" | "denoise">>;
};

export const STYLE_PRESETS: StylePreset[] = [
  {
    id: "japanese",
    name: "日系清新",
    desc: "提亮、压饱和、轻微柔化",
    swatch: ["#ffd7e6", "#b9e4ff"],
    color: { exposure: 0.16, contrast: 0.95, saturation: 0.86 },
    effects: { sharpen: 0.12, sharpen_radius: 0.003 },
  },
  {
    id: "cinema",
    name: "电影感",
    desc: "压高光、加对比、锐一点",
    swatch: ["#2a3350", "#e2a15c"],
    color: { exposure: -0.08, contrast: 1.18, saturation: 0.92 },
    effects: { sharpen: 0.28, sharpen_radius: 0.004 },
  },
  {
    id: "urban",
    name: "都市氛围",
    desc: "冷调、低饱和、深对比",
    swatch: ["#3b4a63", "#8ea6c8"],
    color: { exposure: -0.04, contrast: 1.1, saturation: 0.78 },
  },
  {
    id: "product",
    name: "产品展示",
    desc: "通透、饱和、边缘清晰",
    swatch: ["#e8e4ff", "#8b5cf6"],
    color: { exposure: 0.1, contrast: 1.06, saturation: 1.12 },
    effects: { sharpen: 0.34, sharpen_radius: 0.005 },
  },
];

export function applyStylePreset(id: string): void {
  const state = get();
  const project = state.project;
  const preset = STYLE_PRESETS.find((item) => item.id === id);
  if (!project || !preset) return;
  const ids = state.selectedClips.filter((clipId) => {
    const clip = project.clips[clipId];
    if (!clip) return false;
    const asset = project.assets[clip.asset_id];
    return asset ? asset.kind === "video" || asset.kind === "image" || asset.kind === "sequence" : Boolean(clip.text);
  });
  if (!ids.length) {
    toast("info", "先选中要套风格的片段", "调色写在片段上：选一段画面，再点这张风格卡。");
    return;
  }
  const commands: Command[] = ids.map((clipId) => ({
    op: "clip.patch",
    clip_id: clipId,
    color: { ...preset.color },
    ...(preset.effects ? { effects: preset.effects } : {}),
  } as Command));
  editAtRevision(commands, project.id, project.revision, `套用风格「${preset.name}」`);
  toast("ok", `已套用「${preset.name}」`, `${ids.length} 段画面写进一个批次；撤销一次就能整体退回。`);
}
