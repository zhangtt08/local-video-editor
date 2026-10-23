import { newId, type Asset, type Clip, type Command, type Project, type Track, type Sequence, type VerifiedMedia } from "./engine";
import { frameTicks, sampleTicks } from "./time";
import { conformPasted, type RateSettings } from "./rateConform";

export type ClipClipboard = {
  projectId: string;
  sequenceId?: string | null;
  clips: Clip[];
  assets: Asset[];
  tracks: Track[];
  sequences?: Sequence[];
  /** 1.273：复制那一刻的工程时钟。粘到另一帧率/采样率的工程时，`rateConform` 按它换算切点；
   *  上一版留下的剪贴板没有这一格，按「同率」处理，行为与 1.272 一字不差。 */
  settings?: RateSettings;
};

/** Selection follows the connected groups/links; edits still submit explicit ids. */
export function relatedClips(project: Project, ids: string[], linksOnly = false): string[] {
  const members = new Map<string, string[]>();
  for (const c of Object.values(project.clips)) for (const key of [linksOnly ? null : c.group_id && `g:${c.group_id}`, c.link_id && `l:${c.link_id}`]) {
    if (key) { const list = members.get(key) ?? []; list.push(c.id); members.set(key, list); }
  }
  const result = new Set(ids.filter((id) => project.clips[id])); const pending = [...result]; const visited = new Set<string>();
  for (let i = 0; i < pending.length; i++) {
    const c = project.clips[pending[i]];
    for (const key of [linksOnly ? null : c.group_id && `g:${c.group_id}`, c.link_id && `l:${c.link_id}`]) {
      if (!key || visited.has(key)) continue; visited.add(key);
      for (const id of members.get(key) ?? []) if (!result.has(id)) { result.add(id); pending.push(id); }
    }
  }
  return [...result];
}

export function timelineTracks(project: Project): Track[] {
  return [...project.tracks.filter((t) => t.kind === "video").reverse(), ...project.tracks.filter((t) => t.kind === "audio")];
}

export function selectionQuantum(project: Project, ids: string[]): number {
  const tracks = new Set(ids.map((id) => project.clips[id]?.track_id));
  return trackQuantum(project, project.tracks.filter((t) => tracks.has(t.id)));
}

export function trackQuantum(project: Project, tracks: Track[]): number {
  let q = 1;
  for (const track of tracks) {
    const step = track.kind === "audio" ? sampleTicks(project.settings.sample_rate) : frameTicks(project.settings.frame_rate);
    let a = q, b = step;
    while (b) { const remainder = a % b; a = b; b = remainder; }
    q = q / a * step;
  }
  return q;
}

export function copyClips(project: Project, ids: string[], sequenceId: string | null = null): ClipClipboard {
  const clips = ids.map((id) => project.clips[id]).filter(Boolean);
  const assets = new Set(clips.map((c) => c.asset_id)); const tracks = new Set(clips.map((c) => c.track_id));
  const sequences = new Map<string, Sequence>();
  const visit = (assetId: string) => {
    const id = project.assets[assetId]?.sequence_id; const sequence = id ? project.sequences?.[id] : null;
    if (!sequence || sequences.has(sequence.id)) return;
    sequences.set(sequence.id, sequence);
    for (const child of Object.values(sequence.clips)) { assets.add(child.asset_id); visit(child.asset_id); }
  };
  clips.forEach((clip) => visit(clip.asset_id));
  const selected = new Set(ids); const incomplete = new Set(Object.values(project.clips).filter((c) => c.link_id && !selected.has(c.id)).map((c) => c.link_id));
  return structuredClone({
    projectId: project.id, sequenceId, sequences: [...sequences.values()],
    clips: clips.map((c) => c.link_id && incomplete.has(c.link_id) ? { ...c, link_id: null, link_source_offset_ticks: 0 } : c),
    assets: Object.values(project.assets).filter((a) => assets.has(a.id)),
    tracks: project.tracks.filter((t) => tracks.has(t.id)),
    settings: { frame_rate: project.settings.frame_rate, sample_rate: project.settings.sample_rate },
  });
}

/** 剪贴板里那份素材在目标工程里的落点：同一份内容（按引擎算出的哈希）算已有；同一个工程里
 *  id、kind、路径、时长都对得上的那份也算——那是复制出去以后没动过的原样。
 *  冷粘贴（上一次运行留下的那份复制）要重新探测的就是「没有落点」的那些，所以这个判断只留一处，
 *  `pasteCommands` 与 `clipboardAssetsToReprobe` 都走它。 */
export function clipboardAssetMatcher(project: Project, copied: ClipClipboard) {
  const media = new Map(Object.values(project.assets).filter((a) => a.verified).map((a) => [`${a.kind}:${a.verified!.content_sha256}`, a]));
  return (asset: Asset): Asset | undefined => {
    const current = copied.projectId === project.id ? project.assets[asset.id] : undefined;
    return asset.verified
      ? media.get(`${asset.kind}:${asset.verified.content_sha256}`)
      : current && current.kind === asset.kind && current.reference === asset.reference && current.duration_ticks === asset.duration_ticks
        ? current
        : undefined;
  };
}

/** 冷粘贴前必须由这台引擎重新探一遍的素材：带探测记录、走的是真实文件路径、而目标工程里没有落点。
 *  `sequence://` 那种由嵌套时间线自己带进去，不需要探测。
 *  要探的是 `verified.path`——`reference` 是 `asset.import` 之后引擎给的那个 probe_id，不是文件路径，
 *  拿它去探测会被引擎回一句「这不是我认识的素材」。 */
export type ClipboardReprobe = { asset: Asset; path: string };

export function clipboardAssetsToReprobe(project: Project, copied: ClipClipboard): ClipboardReprobe[] {
  const match = clipboardAssetMatcher(project, copied);
  return copied.assets
    .filter((asset) => asset.verified && !match(asset) && !asset.reference.startsWith("sequence://"))
    .map((asset) => ({ asset, path: asset.verified?.path ?? asset.reference }));
}

/** 把这次探测出来的记录换回剪贴板：只动 `verified`，标签、路径、kind 那些原样留着。 */
export function reviveClipboardAssets(copied: ClipClipboard, fresh: Record<string, VerifiedMedia>): ClipClipboard {
  return { ...copied, assets: copied.assets.map((asset) => (fresh[asset.id] ? { ...asset, verified: fresh[asset.id] } : asset)) };
}

/** Build explicit commands; the engine validates media, clocks, locks and overlaps. */
export function pasteCommands(project: Project, copied: ClipClipboard, at: number, direction = 0, sequenceId: string | null = null): { commands: Command[]; ids: string[]; note?: string; refusal?: string } {
  const commands: Command[] = []; const assets = new Map<string, string>(); const tracks = new Map<string, string>();
  const matchAsset = clipboardAssetMatcher(project, copied);
  const sequences = new Map((copied.sequences ?? []).map((s) => [s.id, copied.projectId === project.id && project.sequences?.[s.id] ? s.id : newId("seq-")]));
  for (const asset of copied.assets) {
    const existing = matchAsset(asset);
    const id = existing?.id ?? newId("a-"); assets.set(asset.id, id);
    if (existing) continue;
    commands.push(asset.verified ? { op: "asset.import", asset_id: id, label: asset.label, probe_id: asset.verified.probe_id, verified: asset.verified } : { op: "asset.register", asset: { ...asset, id, verified: null, ...(asset.sequence_id ? { sequence_id: sequences.get(asset.sequence_id), reference: `sequence://${sequences.get(asset.sequence_id)}` } : {}) } });
  }
  for (const sequence of copied.sequences ?? []) {
    const id = sequences.get(sequence.id)!;
    if (id === sequence.id) continue;
    commands.push({ op: "sequence.add", sequence: { ...sequence, id, clips: Object.fromEntries(Object.values(sequence.clips).map((c) => [c.id, { ...c, asset_id: assets.get(c.asset_id)! }])) } });
  }
  for (const track of copied.tracks) {
    const existing = copied.projectId === project.id && (copied.sequenceId ?? null) === sequenceId ? project.tracks.find((t) => t.id === track.id) : undefined;
    const id = existing?.id ?? newId(track.kind === "video" ? "v-" : "a-"); tracks.set(track.id, id);
    if (!existing) commands.push({ op: "track.add", track: { ...track, id, locked: false } });
  }
  const ids = new Map(copied.clips.map((c) => [c.id, newId("c-")]));
  const groups = new Map<string, string>(); const links = new Map<string, string>();
  for (const c of copied.clips) { if (c.group_id && !groups.has(c.group_id)) groups.set(c.group_id, newId("g-")); if (c.link_id && !links.has(c.link_id)) links.set(c.link_id, newId("l-")); }
  const origin = Math.min(...copied.clips.map((c) => c.position_ticks));
  const q = trackQuantum(project, copied.tracks);
  const offset = (at - origin) / q;
  const delta = Math.max(-Math.floor(origin / q), direction > 0 ? Math.ceil(offset) : Math.round(offset)) * q;
  const shifted = copied.clips.map((clip) => ({ ...clip, position_ticks: clip.position_ticks + delta }));
  // 1.273：切点先落到目标工程的格子上，再算回时长。同一帧率的粘贴原样返回，串一字不改。
  const conformed = conformPasted(shifted, copied.tracks, project, copied.settings, copied.assets);
  if (conformed.refusal) return { commands: [], ids: [], refusal: conformed.refusal };
  const clips = conformed.clips.map((clip): Clip => ({ ...clip, id: ids.get(clip.id)!, asset_id: assets.get(clip.asset_id)!, track_id: tracks.get(clip.track_id)!,
    group_id: clip.group_id ? groups.get(clip.group_id)! : null, link_id: clip.link_id ? links.get(clip.link_id)! : null, link_source_offset_ticks: clip.link_id ? clip.link_source_offset_ticks ?? 0 : 0,
    transition_in: clip.transition_in && ids.has(clip.transition_in.from_clip_id) ? { ...clip.transition_in, from_clip_id: ids.get(clip.transition_in.from_clip_id)! } : null }));
  commands.push({ op: "clips.add", clips });
  return { commands, ids: [...ids.values()], ...(conformed.note ? { note: conformed.note } : {}) };
}
