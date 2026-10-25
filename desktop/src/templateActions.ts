import type { Command } from "./engine";
import { motionCommands, type MotionPresetId, type MotionSide } from "./motionPresets";
import { TEXT_PRESETS } from "./textStyle";
import { editAtRevision, get, toast } from "./store";

/** 模板库里的字幕样式：只改「长什么样」的那几格，正文与字体不动（与检查器那一排同一个来源）。 */
export function applyTextTemplate(id: string): void {
  const state = get();
  const project = state.project;
  const preset = TEXT_PRESETS.find((item) => item.id === id);
  if (!project || !preset) return;
  const clip = state.selectedClips
    .map((clipId) => project.clips[clipId])
    .find((item) => Boolean(item?.text));
  if (!clip) {
    toast("info", "先选中一条文字片段", "模板写在这一条的字幕样式上：选中字幕后回来点。");
    return;
  }
  editAtRevision(
    [{ op: "clip.patch", clip_id: clip.id, text: preset.style } as Command],
    project.id,
    project.revision,
    `套用字幕样式「${preset.label}」`,
  );
  toast("ok", `已套用「${preset.label}」`, "字号、颜色、描边、阴影与垫子一起写；正文与字体不动。");
}

/** 入场 / 出场动画：只算出普通的 keyframe.set，一次一个批次，撤销一次回一步。 */
export function applyMotionTemplate(side: MotionSide, id: MotionPresetId, seconds: number): void {
  const state = get();
  const project = state.project;
  if (!project) return;
  const frame = project.settings.timebase * project.settings.frame_rate.denominator / project.settings.frame_rate.numerator;
  const commands: Command[] = [];
  for (const clipId of state.selectedClips) {
    const clip = project.clips[clipId];
    if (!clip) continue;
    const asset = project.assets[clip.asset_id];
    if (!asset) continue;
    if (!["video", "image", "sequence"].includes(asset.kind)) continue;
    commands.push(...motionCommands(clip, side, id, seconds, frame));
  }
  if (!commands.length) {
    toast("info", "没有可以写的片段", "先选中一段画面：已经处在预设终点的那几段不会写等值的针。");
    return;
  }
  editAtRevision(commands, project.id, project.revision, `${side === "in" ? "入场" : "出场"}动画`);
  toast(
    "ok",
    `已写 ${commands.length} 枚关键帧`,
    `${side === "in" ? "入场" : "出场"} ${seconds.toFixed(2)} 秒；终格是片段自己的静态值，一次撤销整批退回。`,
  );
}
