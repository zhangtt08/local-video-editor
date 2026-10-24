/** 1.278：两条「这件事现在能不能做」的判断只剩一处。
 *
 *  右键菜单要摆「链接音画」「拆出音频」，检查器那两颗按钮早就摆着；如果各写一份条件，
 *  迟早出现「菜单里能点、检查器里灰着」或者反过来——同一件事两个答案。判据本来就只是
 *  工程与片段的几个字段，所以收在这里，两个入口都问它。
 */

import type { Clip, Project } from "./engine";

/** 链接音画的前提：一段画面 + 一段声音，开始、时长与速度都对得上。 */
export function canLinkClips(project: Project, clips: Clip[]): boolean {
  if (clips.length < 2) return false;
  const kinds = new Set(clips.map((clip) => project.assets[clip.asset_id]?.kind));
  const head = clips[0];
  return (
    kinds.size === 2 &&
    kinds.has("video") &&
    kinds.has("audio") &&
    clips.every(
      (clip) =>
        clip.position_ticks === head.position_ticks &&
        clip.duration_ticks === head.duration_ticks &&
        (clip.speed_percent ?? 100) === (head.speed_percent ?? 100),
    )
  );
}

/** 拆出音频的前提：这一段是画面、素材里真有声音、而且没有被标成「没有内嵌声音」。 */
export function canDetachAudio(project: Project, clip: Clip | undefined): boolean {
  if (!clip) return false;
  const asset = project.assets[clip.asset_id];
  return Boolean(asset?.kind === "video" && asset.verified?.has_audio && clip.embedded_audio !== false);
}
