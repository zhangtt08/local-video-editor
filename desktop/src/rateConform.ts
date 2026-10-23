import type { Asset, Clip, Project, Track } from "./engine";
import { TIMEBASE, frameTicks, sampleTicks } from "./time";

/** 粘贴跨帧率时唯一的一处换算：切点先落到目标工程的帧格，再按相邻切点算回时长。
 *
 *  为什么不是「把每一段四舍五入」：同一段素材切成七段时，七个各自取整的时长会留下
 *  半帧的缝或叠；这里量的是**切点**，相邻两段共用同一个切点，所以重排之后仍然首尾相接。
 *  为什么不是「按比例缩放整段」：30 → 25 fps 的素材不需要变速，画面是按目标时钟采样的；
 *  变的是剪点落在哪一格，不是这段内容播多快。
 *
 *  一处例外会整批拒绝：带变速曲线的片段。曲线的点在源时钟上，换格子既保不住曲线形状，
 *  也保不住切点，与其猜一个近似，不如让用户先改成恒定速度或在原工程出片。
 */

export type RateSettings = {
  frame_rate: { numerator: number; denominator: number };
  sample_rate: number;
};

export type ConformResult = {
  clips: Clip[];
  changed: boolean;
  note: string | null;
  refusal: string | null;
};

const rateText = (settings: RateSettings) =>
  `${settings.frame_rate.numerator}/${settings.frame_rate.denominator}`;

const milliseconds = (ticks: number) => `${Math.round((ticks / TIMEBASE) * 1000)} ms`;

/** Cut points that land on one source frame but not one target frame are rounded once, per track.
 *
 *  Pixel and sound are measured on different grids; a frame is a whole number of samples for every
 *  rate this project ships, so a linked pair shares the picture grid instead of drifting apart by a
 *  sample. Tracks with no linked clip keep their own grid (audio stays on samples).
 */
export function conformPasted(
  clips: Clip[],
  tracks: Track[],
  project: Project,
  source: RateSettings | undefined,
  assets: Asset[],
): ConformResult {
  const target: RateSettings = {
    frame_rate: project.settings.frame_rate,
    sample_rate: project.settings.sample_rate,
  };
  if (!source) return { clips, changed: false, note: null, refusal: null };
  const sourceFrame = frameTicks(source.frame_rate);
  const targetFrame = frameTicks(target.frame_rate);
  const sourceSample = sampleTicks(source.sample_rate);
  const targetSample = sampleTicks(target.sample_rate);
  if (sourceFrame === targetFrame && sourceSample === targetSample) {
    return { clips, changed: false, note: null, refusal: null };
  }
  const curved = clips.find((clip) => clip.speed_curve && clip.speed_curve.length);
  if (curved) {
    return {
      clips: [],
      changed: false,
      note: null,
      refusal:
        `「${labelOf(curved, assets)}」带变速曲线。曲线的点按源时钟采，跨帧率重排没有一条能同时` +
        "保住曲线形状与剪点的映射；先把这段改成恒定速度，或者在原工程里出片。",
    };
  }

  const kind = new Map(tracks.map((track) => [track.id, track.kind]));
  const quantumOf = (trackId: string, clip: Clip) =>
    kind.get(trackId) === "audio" && !clip.link_id ? targetSample : targetFrame;

  const byTrack = new Map<string, Clip[]>();
  for (const clip of clips) {
    const list = byTrack.get(clip.track_id) ?? [];
    list.push(clip);
    byTrack.set(clip.track_id, list);
  }

  // Every start and end is a cut point; both neighbours look up the same rounded value. A linked
  // pair raises the grid of the cut it touches to the picture grid, so both members land on one
  // number; an unlinked neighbour on the same audio track keeps the sample grid at its own cuts.
  const boundary = new Map<string, number>();
  for (const [trackId, list] of byTrack) {
    const cuts = new Map<number, number>();
    for (const clip of list) {
      const quantum = quantumOf(trackId, clip);
      for (const tick of [clip.position_ticks, clip.position_ticks + clip.duration_ticks]) {
        cuts.set(tick, Math.max(cuts.get(tick) ?? 0, quantum));
      }
    }
    let previous = Number.NEGATIVE_INFINITY;
    for (const tick of [...cuts.keys()].sort((left, right) => left - right)) {
      const quantum = cuts.get(tick)!;
      let snapped = Math.round(tick / quantum) * quantum;
      if (snapped < previous + quantum) snapped = previous + quantum;
      boundary.set(`${trackId}:${tick}`, snapped);
      previous = snapped;
    }
  }

  const known = new Map<string, Asset>();
  for (const asset of assets) known.set(asset.id, asset);
  for (const asset of Object.values(project.assets)) {
    if (!known.has(asset.id)) known.set(asset.id, asset);
  }

  let snappedClips = 0;
  let maxShift = 0;
  let sourceShifts = 0;
  let refusal: string | null = null;
  const next = clips.map((clip) => {
    const start = boundary.get(`${clip.track_id}:${clip.position_ticks}`)!;
    const end = boundary.get(
      `${clip.track_id}:${clip.position_ticks + clip.duration_ticks}`,
    )!;
    const duration = Math.max(0, end - start);
    if (start !== clip.position_ticks || duration !== clip.duration_ticks) snappedClips += 1;
    maxShift = Math.max(
      maxShift,
      Math.abs(start - clip.position_ticks),
      Math.abs(end - clip.position_ticks - clip.duration_ticks),
    );
    let sourceIn = clip.source_in_ticks;
    const asset = known.get(clip.asset_id);
    const speed = clip.speed_percent ?? 100;
    if (duration > clip.duration_ticks && asset?.duration_ticks != null) {
      // Rounding a cut up can ask for a sliver more source than the file has. Sliding the source
      // window back by that sliver keeps the out point and only shows a touch more head; a clip
      // already pinned at the file's first frame has nowhere to go and refuses the whole paste.
      // Same ceiling as `speed.base_source_ticks`, so this check and the reducer agree on the end.
      const endSource = sourceIn + Math.ceil((duration * speed) / 100);
      if (endSource > asset.duration_ticks) {
        const room = endSource - asset.duration_ticks;
        if (sourceIn >= room) {
          sourceIn -= room;
          sourceShifts += 1;
        } else {
          refusal =
            `「${labelOf(clip, assets)}」按目标帧格取整后会比素材结尾多要 ${milliseconds(room)}，` +
            "而它的源入点已经贴着素材第一帧。先把这段修短，或者在原工程里出片。";
        }
      }
    }
    return { ...clip, position_ticks: start, duration_ticks: duration, source_in_ticks: sourceIn };
  });
  if (refusal) return { clips: [], changed: false, note: null, refusal };

  const byId = new Map(next.map((clip) => [clip.id, clip]));
  let transitions = 0;
  let fades = 0;
  let droppedKeys = 0;
  const fixed = next.map((clip) => {
    let transition = clip.transition_in ?? null;
    if (transition) {
      const left = byId.get(transition.from_clip_id);
      const quantum = targetFrame;
      let duration = Math.round(transition.duration_ticks / quantum) * quantum;
      const room = left
        ? Math.min(left.duration_ticks, clip.duration_ticks) - quantum
        : 0;
      duration = Math.min(duration, room);
      if (duration < quantum) {
        transition = null;
      } else if (duration !== clip.transition_in!.duration_ticks) {
        transition = { ...clip.transition_in!, duration_ticks: duration };
      }
      if (transition?.duration_ticks !== clip.transition_in?.duration_ticks) transitions += 1;
    }

    let fade = clip.fade ?? null;
    if (fade) {
      const limit = (inside: number, outside: number, room: number) => {
        const within = Math.min(inside, room);
        return [within, Math.min(outside, Math.max(0, room - within))] as const;
      };
      const [opacityIn, opacityOut] = limit(
        fade.opacity_in_ticks,
        fade.opacity_out_ticks,
        clip.duration_ticks,
      );
      const [gainIn, gainOut] = limit(fade.gain_in_ticks, fade.gain_out_ticks, clip.duration_ticks);
      if (
        opacityIn !== fade.opacity_in_ticks ||
        opacityOut !== fade.opacity_out_ticks ||
        gainIn !== fade.gain_in_ticks ||
        gainOut !== fade.gain_out_ticks
      ) {
        fades += 1;
        fade = {
          ...fade,
          opacity_in_ticks: opacityIn,
          opacity_out_ticks: opacityOut,
          gain_in_ticks: gainIn,
          gain_out_ticks: gainOut,
        };
      }
    }

    const within = <K extends { at_ticks: number }>(keys: K[] | undefined, end: number) => {
      if (!keys?.length) return keys;
      const kept = keys.filter((key) => key.at_ticks >= 0 && key.at_ticks <= end);
      droppedKeys += keys.length - kept.length;
      return kept;
    };
    const keyframes = within(clip.keyframes, clip.duration_ticks);
    const shapes = within(clip.mask_shape_keys, clip.duration_ticks);
    const extra = clip.extra_masks?.map((mask) => ({
      ...mask,
      keys: within(mask.keys, clip.duration_ticks) ?? [],
    }));
    const layerEnd = (clip.animation_offset_ticks ?? 0) + clip.duration_ticks;
    const grade = clip.color?.grade;
    const color = clip.color && grade
      ? {
          ...clip.color,
          grade: grade.map((node) =>
            node.kind === "layer" && node.keys?.length
              ? { ...node, keys: within(node.keys, layerEnd) ?? [] }
              : node,
          ),
        }
      : clip.color;
    return {
      ...clip,
      transition_in: transition,
      fade,
      ...(keyframes ? { keyframes } : {}),
      ...(shapes ? { mask_shape_keys: shapes } : {}),
      ...(extra ? { extra_masks: extra } : {}),
      ...(color ? { color } : {}),
    };
  });

  const parts = [
    `${rateText(source)} → ${rateText(target)} fps`,
    ...(sourceSample !== targetSample
      ? [`${source.sample_rate} → ${target.sample_rate} Hz`]
      : []),
  ];
  const detail = [
    snappedClips
      ? `${snappedClips} 段按目标帧格重排，最远挪了 ${milliseconds(maxShift)}`
      : "切点本来就落在目标帧格上",
    ...(transitions ? [`${transitions} 条转场被夹短`] : []),
    ...(fades ? [`${fades} 条淡被夹短`] : []),
    ...(sourceShifts ? [`${sourceShifts} 段的源入点前移了不到一帧`] : []),
    ...(droppedKeys ? [`丢弃 ${droppedKeys} 枚落到新时长之外的针`] : []),
  ];
  return {
    clips: fixed,
    changed: snappedClips > 0 || transitions > 0 || fades > 0 || droppedKeys > 0,
    note: `${parts.join("，")}：${detail.join("；")}。`,
    refusal: null,
  };
}

function labelOf(clip: Clip, assets: Asset[]): string {
  const asset = assets.find((item) => item.id === clip.asset_id);
  return asset?.label ?? clip.id;
}
