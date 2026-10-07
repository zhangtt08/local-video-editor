import { textLayerStyle } from "../textStyle";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon, IconBtn } from "../ui";
import { MaskPicture } from "./MaskPicture";
import { TIMEBASE, frameTicks, humanDuration, pacing, rateLabel, timecode } from "../time";
import type { Clip, Effects, GradeTables, PreviewManifest, Project, Track } from "../engine";
import { appInfo, clearProxyCache, clearDerivedCache, cycleSafeArea, editSource, fourPoint, jumpEditPoint, markSource, playhead, PROXY_WIDTHS, selectClip, selectedSource, setMonitorMode, setProxyWidth, setSourceCursor, setSourcePlaying, setSourceRipple, setSourceTarget, timelineEnd, useApp, usePlay } from "../store";

let audioContext: AudioContext | undefined;
const audioNodes = new WeakMap<HTMLMediaElement, GainNode>();
function gainNode(element: HTMLMediaElement): GainNode | undefined {
  try {
    audioContext ??= new AudioContext();
    let node = audioNodes.get(element);
    if (!node) {
      node = audioContext.createGain();
      audioContext.createMediaElementSource(element).connect(node).connect(audioContext.destination);
      audioNodes.set(element, node);
    }
    if (audioContext.state === "suspended") void audioContext.resume();
    return node;
  } catch { return undefined; }
}

/** The server ships the same per-channel table the FFmpeg render uses; SVG exposes it to the compositor. */
function GradeDefs({ plan }: { plan: PreviewManifest | null }) {
  const tables = useMemo(() => {
    const found = new Map<string, GradeTables>();
    const walk = (manifest: PreviewManifest | undefined) => {
      if (!manifest) return;
      for (const clip of Object.values(manifest.clips)) if (clip.grade) found.set(clip.grade.id, clip.grade);
      for (const nested of Object.values(manifest.sequences ?? {})) walk(nested);
    };
    walk(plan ?? undefined);
    return [...found.values()];
  }, [plan]);
  if (!tables.length) return null;
  return <svg className="grade-defs" aria-hidden="true" focusable="false">
    <defs>{tables.map((table) => <filter key={table.id} id={table.id} colorInterpolationFilters="sRGB" x="0" y="0" width="100%" height="100%">
      <feComponentTransfer>
        <feFuncR type="table" tableValues={table.r.join(" ")} />
        <feFuncG type="table" tableValues={table.g.join(" ")} />
        <feFuncB type="table" tableValues={table.b.join(" ")} />
      </feComponentTransfer>
    </filter>)}</defs>
  </svg>;
}

/** 三态循环的显示名；引擎的 `safe_area` 用同一组词。 */
const SAFE_LABELS: Record<"off" | "action" | "title", string> = { off: "关", action: "动作区", title: "字幕区" };

export function Preview() {
  const app = useApp(); const play = usePlay();
  const proposed = app.mode === "batch" && app.batch.length > 0;
  const candidate = proposed && !app.dryRunError && app.candidate?.id === app.project?.id && app.candidate?.revision === (app.project?.revision ?? 0) + 1 ? app.candidate : null;
  const project = candidate ?? app.project;
  const safe = project?.settings.safe_area ?? "off";
  const insets = app.caps?.safe_area_insets;
  const safeTitle = insets
    ? `安全参考线（当前：${SAFE_LABELS[safe]}）。动作区每边内缩 ${(insets.action * 100).toFixed(1)}%、字幕区 ${(insets.title * 100).toFixed(1)}%，数字由引擎给出；这条选择是工程状态，跟着撤销走，也只影响监视器显示，不改变导出。`
    : "安全参考线：等引擎的 capabilities 返回内缩数字后才能画。";
  const [manifest, setManifest] = useState<{ project: Project; plan: PreviewManifest } | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [monitorMuted, setMonitorMuted] = useState(false);
  const sourceMode = app.monitorMode === "source";
  const sourceEdit = selectedSource();
  const sourceRef = useRef<HTMLMediaElement | null>(null);
  const monitorRef = useRef<HTMLDivElement>(null);
  const end = timelineEnd(project);
  const source = Object.values(project?.assets ?? {}).find((a) => a.id === app.selectedAsset);
  const probe = app.library.find((a) => a.probe.id === app.selectedAsset)?.probe;
  const sourceUrl = source ? app.streams[source.id] : probe?.urls.stream;
  const sourceInfo = source?.verified ?? probe?.verified;
  useEffect(() => {
    const element = sourceRef.current; if (!element) return;
    element.muted = monitorMuted;
    const wanted = app.sourceCursorTicks / TIMEBASE;
    const seek = () => { if (Math.abs(element.currentTime - wanted) > (app.sourcePlaying ? .1 : .0001)) element.currentTime = wanted; };
    if (element.readyState) seek(); else element.addEventListener("loadedmetadata", seek, { once: true });
    if (sourceMode && app.sourcePlaying) void element.play().catch(() => { setSourcePlaying(false); setPreviewError("素材无法播放，请检查格式"); });
    else element.pause();
    return () => element.removeEventListener("loadedmetadata", seek);
  }, [sourceUrl, sourceMode, app.sourceCursorTicks, app.sourcePlaying, monitorMuted]);
  useEffect(() => { const element = sourceRef.current; return () => element?.pause(); }, [sourceUrl, sourceMode]);
  useEffect(() => {
    if (!project) return;
    let disposed = false; setPreviewError("");
    const request = candidate ? appInfo.engine()?.previewCandidate(app.rootCandidate ?? project, app.sequenceId) : appInfo.engine()?.previewManifest(project.id, project.revision, app.sequenceId);
    void request?.then((plan) => {
      if (!disposed) setManifest({ project, plan });
    }).catch(() => { if (!disposed) setPreviewError("预览计划读取失败，请切换工程后重试"); });
    return () => { disposed = true; };
  }, [project]);
  useEffect(() => {
    if (!play.playing) return;
    if (!end || sourceMode) { playhead.pause(); return; }
    let last = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now(); const next = playhead.value + (now - last) / 1000 * TIMEBASE; last = now;
      if (next >= end) { playhead.set(end); playhead.pause(); } else playhead.set(next);
    }, 20);
    return () => window.clearInterval(id);
  }, [play.playing, end, sourceMode]);
  if (!project) return null;
  const visuals: { clip: Clip; track: Track }[] = []; const sounds: { clip: Clip; track: Track }[] = [];
  for (const track of project.tracks) for (const clip of Object.values(project.clips)) {
    if (clip.track_id !== track.id || play.ticks < clip.position_ticks || play.ticks >= clip.position_ticks + clip.duration_ticks) continue;
    if (track.kind === "video" && !track.hidden) visuals.push({ clip, track });
    if (track.kind === "audio" && !track.muted) sounds.push({ clip, track });
  }
  const currentPlan = manifest?.project === project ? manifest.plan : null;
  // Keep media nodes and keyboard focus during a same-project plan refresh.
  const displayPlan = currentPlan ?? (manifest?.project.id === project.id && (manifest.plan.sequence_id ?? null) === app.sequenceId ? manifest.plan : null);
  const ready = Boolean(currentPlan);
  return <section className="preview-col" aria-label="播放器">
    <div className="panel-head monitor-head"><div className="seg mini">
      <button className={!sourceMode ? "active" : ""} onClick={() => setMonitorMode("timeline")}>时间线预览</button>
      <button className={sourceMode ? "active" : ""} disabled={!sourceUrl} onClick={() => setMonitorMode("source")}>素材预览</button>
    </div><span className="spacer" />
      {proposed ? <span className="tag">{candidate ? "批次预演" : app.dryRunError ? "预演未通过" : "正在预演…"}</span> : null}
      {app.caps?.features.proxy_playback ? <label className="proxy-ctl" title="代理回放只影响预览画面，导出始终使用原片">
        <span className="panel-label">代理</span>
        <select className="input" aria-label="代理分辨率" value={app.proxyWidth} onChange={(event) => void setProxyWidth(Number(event.target.value))}>
          <option value={0}>关闭</option>
          {PROXY_WIDTHS.map((width) => <option key={width} value={width}>{`${width}p`}</option>)}
        </select>
      </label> : null}
      {app.proxyUsage.count ? <span className="tag" title="代理是可重建的派生副本，不计入工程">{`代理占用 ${(app.proxyUsage.used_bytes / 1048576).toFixed(1)} MB / ${app.proxyUsage.count} 份`}</span> : null}
      {app.proxyUsage.count ? <button className="btn tiny subtle" onClick={() => void clearProxyCache()} title="删除全部代理副本以释放磁盘；原片与工程不受影响">清理代理</button> : null}
      {app.cacheUsage.count ? <span className="tag" title={`派生缓存上限 ${(app.cacheUsage.limit_bytes / 1073741824).toFixed(1)} GB：缩略图、波形与代理都算在内，超出时引擎按最久未用淘汰`}>{`缓存 ${(app.cacheUsage.used_bytes / 1048576).toFixed(1)} MB / ${app.cacheUsage.count} 项`}</span> : null}
      {app.cacheUsage.count ? <button className="btn tiny subtle" onClick={() => void clearDerivedCache()} title="删除全部派生缓存（缩略图 / 波形 / 代理）以释放磁盘；原片与工程不受影响，下次用到时自动重建">清理缓存</button> : null}
      {app.proxyWidth ? <span className="tag">{app.proxyStatus.done < app.proxyStatus.total ? `生成代理 ${app.proxyStatus.done}/${app.proxyStatus.total}：${app.proxyStatus.label}` : Object.keys(app.proxyActive).length ? `代理 ${app.proxyWidth}p` : "素材已足够小"}</span> : null}
      <button className={`btn tiny subtle${safe === "off" ? "" : " active"}`} onClick={() => cycleSafeArea()} title={safeTitle}>安全框 · {SAFE_LABELS[safe]}</button>
      <IconBtn icon="fullscreen" label="全屏预览" onClick={() => void monitorRef.current?.requestFullscreen()} />
    </div>
    <div ref={monitorRef} className="monitor-wrap"><div className="monitor" style={{ aspectRatio: `${project.settings.width} / ${project.settings.height}`, width: `min(100cqw, calc(100cqh * ${project.settings.width / project.settings.height}))` }}>
      <GradeDefs plan={displayPlan} />
      {sourceMode && sourceUrl ? sourceInfo?.kind === "image" ? <img src={sourceUrl} alt={sourceInfo.label} /> : sourceInfo?.kind === "audio" ? <><audio key={sourceUrl} ref={(node) => { sourceRef.current = node; }} src={sourceUrl} preload="metadata" onTimeUpdate={(e) => setSourceCursor(e.currentTarget.currentTime * TIMEBASE)} onEnded={() => setSourcePlaying(false)} /><div className="monitor-empty"><Icon name="volume" size={32} /><div className="monitor-title">{sourceInfo.label}</div><div className="monitor-sub">标记需要的声音区间，插入或覆盖到目标声音轨</div></div></> : <video key={sourceUrl} ref={(node) => { sourceRef.current = node; }} src={sourceUrl} playsInline preload="metadata" onTimeUpdate={(e) => setSourceCursor(e.currentTarget.currentTime * TIMEBASE)} onEnded={() => setSourcePlaying(false)} onError={() => { setSourcePlaying(false); setPreviewError("素材无法解码"); }} /> : <>
        {displayPlan ? project.tracks.filter((track) => track.kind === "video" && !track.hidden).map((track) => <div key={track.id} className="preview-track" style={{ mixBlendMode: displayPlan.track_blend_modes?.[track.id] ?? "normal" }}>
          {visuals.filter((v) => v.track.id === track.id).map(({ clip }) => <PreviewLayer key={clip.id} clip={clip} track={track} project={project} plan={displayPlan.clips[clip.id]} manifest={displayPlan} streams={app.streams} mixed={displayPlan.mixed_track_ids.includes(track.id)} url={app.streams[clip.asset_id]} ticks={play.ticks} playing={ready && play.playing} monitorMuted={monitorMuted} />)}
        </div>) : null}
        {displayPlan ? sounds.map(({ clip, track }) => <PreviewLayer key={clip.id} clip={clip} track={track} project={project} plan={displayPlan.clips[clip.id]} url={app.streams[clip.asset_id]} ticks={play.ticks} playing={ready && play.playing} monitorMuted={monitorMuted} />) : null}
        {!visuals.length || !ready ? <div className="monitor-empty"><Icon name={previewError ? "warning" : "film"} size={32} /><div className="monitor-title">{previewError || (!ready ? "读取合成预览…" : end ? "此处没有画面" : "从素材库添加第一个镜头")}</div><div className="monitor-sub">{end ? "点击时间线定位，空格播放" : "导入视频、音频或图片，拖到下方时间线"}</div></div> : null}
        {safe !== "off" && insets ? <div className="safe-frame" aria-hidden="true">
          <span className={`safe-guide action${safe === "action" ? " active" : ""}`} style={{ inset: `${insets.action * 100}%` }} />
          <span className={`safe-guide title${safe === "title" ? " active" : ""}`} style={{ inset: `${insets.title * 100}%` }} />
          <span className="safe-cross">+</span>
          <em className="safe-caption mono">{SAFE_LABELS[safe]} {Math.round((safe === "action" ? insets.action : insets.title) * project.settings.width)}×{Math.round((safe === "action" ? insets.action : insets.title) * project.settings.height)} px</em>
        </div> : null}
      </>}
      {sourceMode && previewError ? <div className="layer-error">{previewError}</div> : null}
    </div><button className="btn fullscreen-exit" onClick={() => void document.exitFullscreen()}>退出全屏（Esc）</button></div>
    {sourceMode && sourceEdit ? <div className="source-edit">
      {sourceEdit.kind !== "image" ? <div className="source-range"><input aria-label="素材播放头" type="range" min={0} max={Math.max(0, sourceEdit.end - sourceEdit.q)} step={sourceEdit.q} value={app.sourceCursorTicks} onChange={(e) => { setSourcePlaying(false); setSourceCursor(Number(e.target.value)); }} style={{ background: `linear-gradient(to right, var(--line) ${sourceEdit.start / (sourceEdit.end || 1) * 100}%, var(--accent) ${sourceEdit.start / (sourceEdit.end || 1) * 100}%, var(--accent) ${sourceEdit.stop / (sourceEdit.end || 1) * 100}%, var(--line) ${sourceEdit.stop / (sourceEdit.end || 1) * 100}%)` }} />
        <button className="btn tiny" onClick={() => markSource("in")} title="入点（I）">入点 I</button><button className="btn tiny" onClick={() => markSource("out")} title="出点包含当前帧（O）">出点 O</button><button className="btn tiny subtle" onClick={() => markSource("clear")} title="清除入出点（Alt+X）">清除</button>
      </div> : null}
      <div className="source-actions"><span className="mono source-range-label" title={`源区间 ${sourceEdit.start}–${sourceEdit.stop} ticks；出点为不包含的区间边界`}>{timecode(sourceEdit.start, project.settings.frame_rate)} → {timecode(sourceEdit.stop, project.settings.frame_rate)} · {humanDuration(sourceEdit.stop - sourceEdit.start)}</span><span className="spacer" />
        <select className="input" aria-label="目标轨道" value={sourceEdit.target?.id ?? ""} onChange={(e) => setSourceTarget(e.target.value)}>{sourceEdit.tracks.map((t) => <option key={t.id} value={t.id}>{t.name}{t.locked ? "（锁定）" : ""}</option>)}</select>
        <label className="source-sync"><input type="checkbox" checked={app.sourceRippleAll} onChange={(e) => setSourceRipple(e.target.checked)} />同步未锁轨道</label>
        <button className="btn primary" disabled={!sourceEdit.target || sourceEdit.target.locked || sourceEdit.stop <= sourceEdit.start} onClick={() => editSource("insert")} title="在时间线播放头插入，后续内容顺延（F9）">插入 F9</button>
        <button className="btn" disabled={!sourceEdit.target || sourceEdit.target.locked || sourceEdit.stop <= sourceEdit.start} onClick={() => editSource("overwrite")} title="覆盖目标轨道区间，其余片段保持位置（F10）">覆盖 F10</button>
        <button className="btn" onClick={() => void fourPoint("insert")} title="把上面这段素材区间放进时间线的入出点区间；素材长了裁尾、短了变速，怎么处理的会写在提示里">四点→时间线区间（插入）</button>
        <button className="btn subtle" onClick={() => void fourPoint("overwrite")} title="同上，但覆盖区间内已有的内容，其余片段不动">四点→覆盖</button>
      </div>
    </div> : null}
    <div className="transport">
      <IconBtn icon="start" label="回到起点（Home）" onClick={() => { if (sourceMode) { setSourcePlaying(false); setSourceCursor(0); } else { playhead.pause(); playhead.set(0); } }} />
      <IconBtn icon="prev" label="上一帧（←）" onClick={() => { if (sourceMode) { setSourcePlaying(false); setSourceCursor(app.sourceCursorTicks - frameTicks(project.settings.frame_rate)); } else { playhead.pause(); playhead.set(play.ticks - frameTicks(project.settings.frame_rate)); } }} />
      <button className="play-btn" title="播放 / 暂停（空格）" disabled={sourceMode ? !sourceUrl || sourceEdit?.kind === "image" : !end || !ready} onClick={() => { if (sourceMode) setSourcePlaying(!app.sourcePlaying); else if (play.playing) playhead.pause(); else { if (play.ticks >= end) playhead.set(0); playhead.play(); } }}><Icon name={(sourceMode ? app.sourcePlaying : play.playing) ? "pause" : "play"} size={16} /></button>
      <IconBtn icon="next" label="下一帧（→）" onClick={() => { if (sourceMode) { setSourcePlaying(false); setSourceCursor(app.sourceCursorTicks + frameTicks(project.settings.frame_rate)); } else { playhead.pause(); playhead.set(Math.min(end, play.ticks + frameTicks(project.settings.frame_rate))); } }} />
      <IconBtn icon="end" label={sourceMode ? "素材末帧（End）" : "下一个编辑点（↓）"} onClick={() => { if (sourceMode) { setSourcePlaying(false); setSourceCursor(sourceEdit?.end ?? 0); } else jumpEditPoint(1); }} />
      <span className="timecode mono">{timecode(sourceMode ? app.sourceCursorTicks : play.ticks, project.settings.frame_rate)}</span><span className="timecode-total mono">/ {timecode(sourceMode ? sourceEdit?.end ?? 0 : end, project.settings.frame_rate)}</span>
      <span className="spacer" /><IconBtn icon={monitorMuted ? "mute" : "volume"} label="切换监听静音（不影响导出）" active={monitorMuted} onClick={() => setMonitorMuted(!monitorMuted)} />
      <span className="seq-info mono">{project.settings.width}×{project.settings.height} · {rateLabel(project.settings.frame_rate)}</span>
    </div>
  </section>;
}

function NestedPreview({ id, project, manifest, streams, ticks, playing, monitorMuted, parentGain, clockRate }: {
  id: string; project: Project; manifest: PreviewManifest; streams: Record<string, string>; ticks: number; playing: boolean; monitorMuted: boolean; parentGain: () => number; clockRate: number;
}) {
  const sequence = project.sequences?.[id]; const plan = manifest.sequences?.[id];
  const byTrack = useMemo(() => {
    const rows = new Map<string, Clip[]>();
    for (const clip of Object.values(sequence?.clips ?? {})) { const list = rows.get(clip.track_id) ?? []; list.push(clip); rows.set(clip.track_id, list); }
    return rows;
  }, [sequence]);
  if (!sequence || !plan) return <div className="layer-error">合成不存在或预览计划未就绪</div>;
  return <div className="preview-sequence">{sequence.tracks.filter((t) => t.kind === "video" ? !t.hidden : !t.muted).map((track) => <div key={track.id} className="preview-track" style={{ mixBlendMode: plan.track_blend_modes?.[track.id] ?? "normal" }}>
    {(byTrack.get(track.id) ?? []).filter((c) => ticks >= c.position_ticks && ticks < c.position_ticks + c.duration_ticks).map((clip) => <PreviewLayer key={clip.id} clip={clip} track={track} project={project} plan={plan.clips[clip.id]} manifest={manifest} streams={streams} url={streams[clip.asset_id]} ticks={ticks} playing={playing} monitorMuted={monitorMuted} parentGain={parentGain} clockRate={clockRate} interactive={false} mixed={plan.mixed_track_ids.includes(track.id)} />)}
  </div>)}</div>;
}

function PreviewLayer({ clip, track, project, plan, url, ticks, playing, monitorMuted, mixed = false, manifest, streams = {}, interactive = true, parentGain, clockRate = 1 }: {
  clip: Clip; track: Track; project: Project; plan: PreviewManifest["clips"][string] | undefined; url?: string; ticks: number; playing: boolean; monitorMuted: boolean; mixed?: boolean; manifest?: PreviewManifest; streams?: Record<string, string>; interactive?: boolean; parentGain?: () => number; clockRate?: number;
}) {
  const elementRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const wrappers = useRef<Partial<Record<keyof Effects, HTMLElement | null>>>({});
  const blends = useRef<Partial<Record<"picture" | "sound" | "black" | "white", HTMLElement | null>>>({});
  const animations = useRef<Animation[]>([]); const [error, setError] = useState("");
  const asset = project.assets[clip.asset_id]; const isAudio = track.kind === "audio"; const isImage = asset?.kind === "image";
  const relative = (ticks - clip.position_ticks) / TIMEBASE;
  const pace = pacing(clip.speed_percent ?? 100, plan?.speed, relative);
  const effectiveRate = pace.rate * clockRate;
  useLayoutEffect(() => {
    if (!plan) return;
    const created: Animation[] = [];
    for (const property of Object.keys(plan.curves) as (keyof Effects)[]) {
      const wrapper = wrappers.current[property]; if (!wrapper) continue;
      const frames = plan.curves[property].map(({ value, offset, easing }) => ({ offset, easing,
        ...(property === "opacity" || property === "gain" ? { opacity: property === "gain" ? value / 4 : value } : {
          transform: property === "x" ? `translateX(${value * 100}%)` : property === "y" ? `translateY(${value * 100}%)` : property === "scale" ? `scale(${value})` : `rotate(${value}deg)`,
        }) }));
      const animation = wrapper.animate(frames, { duration: plan.duration_ms, fill: "both" }); animation.pause(); created.push(animation);
    }
    for (const name of ["picture", "sound", "black", "white"] as const) {
      const wrapper = blends.current[name]; if (!wrapper) continue;
      const animation = wrapper.animate(plan.transition[name].map(({ value, offset, easing }) => ({ opacity: value, offset, easing })), { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    }
    animations.current = created;
    return () => { created.forEach((a) => a.cancel()); animations.current = []; };
  }, [plan]);
  useLayoutEffect(() => { for (const animation of animations.current) animation.currentTime = relative * 1000; }, [relative, plan]);
  useEffect(() => {
    const element = elementRef.current; if (!element) return;
    element.playbackRate = Math.min(16, Math.max(.0625, pace.rate * clockRate));
    element.preservesPitch = true;
    const frozen = pace.rate <= 0;
    const target = clip.source_in_ticks / TIMEBASE + pace.source;
    const synchronize = () => { if (!playing || frozen || Math.abs(element.currentTime - target) > 0.15) element.currentTime = target; };
    if (element.readyState) synchronize(); else element.addEventListener("loadedmetadata", synchronize, { once: true });
    element.muted = monitorMuted || track.muted;
    if (playing) {
      if (asset?.verified?.has_audio) {
        const gain = wrappers.current.gain;
        const sound = blends.current.sound;
        const value = (gain ? Number(getComputedStyle(gain).opacity) * 4 : 1) * (sound ? Number(getComputedStyle(sound).opacity) : 1) * track.volume * (project.settings.master_gain ?? 1) * (plan?.sound_enabled ? 1 : 0) * (parentGain?.() ?? 1);
        const node = gainNode(element);
        if (node && audioContext) node.gain.setValueAtTime(value, audioContext.currentTime); else element.volume = Math.min(1, value);
      }
      if (frozen) element.pause(); else if (element.paused) void element.play().catch(() => setError("媒体无法播放，请检查素材格式"));
    } else element.pause();
    return () => element.removeEventListener("loadedmetadata", synchronize);
  }, [relative, playing, clip.source_in_ticks, clip.speed_percent, clip.embedded_audio, isAudio, track.muted, track.volume, monitorMuted, asset?.verified?.has_audio, plan, parentGain, clockRate]);
  useEffect(() => { const element = elementRef.current; return () => element?.pause(); }, []);
  // 文字层的 CSS 由 textStyle.ts 从同一份 TextStyle 算出，界面不再自己拼一遍。
  const textFonts = useApp().caps?.text_fonts ?? [];
  const inheritedGain = () => {
    const gain = wrappers.current.gain; const sound = blends.current.sound;
    return (gain ? Number(getComputedStyle(gain).opacity) * 4 : 1) * (sound ? Number(getComputedStyle(sound).opacity) : 1) * track.volume * (plan?.sound_enabled ? 1 : 0) * (parentGain?.() ?? 1);
  };
  const media = asset?.sequence_id && manifest ? <NestedPreview id={asset.sequence_id} project={project} manifest={manifest} streams={streams} ticks={clip.source_in_ticks + Math.floor((ticks - clip.position_ticks) * (clip.speed_percent ?? 100) / 100)} playing={playing} monitorMuted={monitorMuted || track.muted || !plan?.sound_enabled} parentGain={inheritedGain} clockRate={clockRate * (clip.speed_percent ?? 100) / 100} /> : clip.text ? <div className="caption-layer" style={textLayerStyle(clip.text, textFonts)}><span>{clip.text.body}</span></div> : !url ? <div className="layer-error">「{asset?.label}」素材离线或未导入</div> : isImage ? <img src={url} alt={asset?.label} /> : isAudio ? <audio ref={(node) => { elementRef.current = node; }} crossOrigin="anonymous" src={url} preload="auto" onError={() => setError("音频无法解码")} /> : <video ref={(node) => { elementRef.current = node; }} crossOrigin="anonymous" src={url} playsInline preload="auto" onError={() => setError("视频无法解码")} />;
  return <><div className={`preview-layer${isAudio ? " audio-layer" : ""}`} style={{ mixBlendMode: mixed ? "plus-lighter" : "normal" }} onClick={interactive ? () => selectClip(clip.id) : undefined}>
    <div ref={(node) => { wrappers.current.gain = node; }} className="gain-sample" aria-hidden="true" />
    <div ref={(node) => { blends.current.sound = node; }} className="gain-sample" aria-hidden="true" />
    <div ref={(node) => { blends.current.picture = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.opacity = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.x = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.y = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.scale = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.rotation = node; }} className="layer-transform"><MaskPicture clip={clip} image={plan?.mask_image} editable={interactive} animation={plan?.mask_curves && plan.mask_unit ? { unit: plan.mask_unit, curves: plan.mask_curves } : null}><div className="layer-transform" style={{ filter: plan?.color_filter }}>{media}</div></MaskPicture></div></div></div></div></div></div>
    {error || playing && pace.rate > 0 && (effectiveRate < .0625 || effectiveRate > 16) ? <div className="layer-error">{error || "叠加速度超出浏览器连续播放范围，请暂停逐帧预览或导出检查"}</div> : null}
  </div>{!isAudio && plan?.transition.black.some((point) => point.value > 0) ? <div ref={(node) => { blends.current.black = node; }} className="transition-black" style={{ mixBlendMode: "plus-lighter" }} aria-hidden="true" /> : null}{!isAudio && plan?.transition.white?.some((point) => point.value > 0) ? <div ref={(node) => { blends.current.white = node; }} className="transition-white" aria-hidden="true" /> : null}</>;
}

export function PreviewFooter() {
  const app = useApp(); const play = usePlay();
  return <div className="preview-foot"><span className="mono">{humanDuration(Math.max(0, timelineEnd(app.project) - play.ticks))} 剩余</span><span className="spacer" /><span>合成预览 · 位置 / 缩放 / 旋转 / 透明度 / 音量</span></div>;
}
