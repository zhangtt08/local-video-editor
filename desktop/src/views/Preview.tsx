import { textLayerStyle } from "../textStyle";
import { mergePlans, monitorClipIds } from "../manifestFetch";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon, IconBtn } from "../ui";
import { openContextMenu, type MenuEntry } from "../ContextMenu";
import { MaskPicture } from "./MaskPicture";
import { TIMEBASE, frameTicks, humanDuration, pacing, rateLabel, timecode } from "../time";
import type { AnimatedEffect, BlendMode, Clip, GradeTables, PreviewManifest, Project, Track } from "../engine";
import { feColorMatrixValues } from "../engine";
import { chromaNeedsCanvas, gradeNeedsCanvas, paintGrade } from "../gradeCanvas";
import { blurFrames, compositeLive, compositeSwap, layerFrames, layerStyle, sharpenFilters, sharpenFrames, sharpenSteps, wipeClipPath } from "../effects";
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
/** The `<filter>` elements the engine's `color_filter` strings point at: grade tables and, since
 * 1.65, the unsharp mask. Both are declared by the engine and only drawn here, so the numbers in the
 * exporter's `lutrgb` / `blend` expressions and the ones the browser composites are the same ones. */
function FilterDefs({ plan }: { plan: PreviewManifest | null }) {
  const found = useMemo(() => {
    const tables = new Map<string, GradeTables>();
    const sharpens = new Map<string, { id: string; amount: number; bbox: [number, number] }>();
    const walk = (manifest: PreviewManifest | undefined) => {
      if (!manifest) return;
      for (const clip of Object.values(manifest.clips)) {
        if (clip.grade) tables.set(clip.grade.id, clip.grade);
        // 有窗的那片清晰每一窗一个 def：与导出串的每一对阶段是同一批数（1.123）。
        for (const spec of sharpenFilters(clip.sharpen)) sharpens.set(spec.id, spec);
      }
      for (const nested of Object.values(manifest.sequences ?? {})) walk(nested);
    };
    walk(plan ?? undefined);
    return { tables: [...tables.values()], sharpens: [...sharpens.values()] };
  }, [plan]);
  if (!found.tables.length && !found.sharpens.length) return null;
  return <svg className="grade-defs" aria-hidden="true" focusable="false">
    <defs>{found.tables.map((table) => <filter key={table.id} id={table.id} colorInterpolationFilters="sRGB" x="0" y="0" width="100%" height="100%">
      {table.stages.map((stage) => stage.type === "lut" ? <feComponentTransfer key={stage.id}>
        <feFuncR type="table" tableValues={stage.r.join(" ")} />
        <feFuncG type="table" tableValues={stage.g.join(" ")} />
        <feFuncB type="table" tableValues={stage.b.join(" ")} />
      </feComponentTransfer> : stage.type === "matrix" ? <feColorMatrix key={stage.id} type="matrix" values={feColorMatrixValues(stage.m).join(" ")} /> : null)}
    </filter>)}
      {found.sharpens.map((spec) => <filter key={spec.id} id={spec.id} colorInterpolationFilters="sRGB" primitiveUnits="objectBoundingBox" x="-2%" y="-2%" width="104%" height="104%">
        {/* Same formula the exporter compiles: 源 + 量×(源 − 高斯(源)). The arithmetic composite
            clamps by definition, which is what `clip(...,0,255)` is for in the FFmpeg expression. */}
        <feGaussianBlur in="SourceGraphic" stdDeviation={`${spec.bbox[0]} ${spec.bbox[1]}`} result="shb" />
        <feComposite in="SourceGraphic" in2="shb" operator="arithmetic" k1="0" k2={1 + spec.amount} k3={-spec.amount} k4="0" />
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
  // 只在「主时间线、非候选、工程里没有嵌套合成」时收窄：子合成的刻度换算不在这档里，判不准就不收窄。
  const narrow = !candidate && !app.sequenceId && !Object.keys(project?.sequences ?? {}).length;
  const wantedIds = narrow && project ? monitorClipIds(project, play.ticks) : null;
  const wantedKey = wantedIds ? wantedIds.join(",") : "";
  useEffect(() => {
    if (!project) return;
    let disposed = false; setPreviewError("");
    const request = candidate ? appInfo.engine()?.previewCandidate(app.rootCandidate ?? project, app.sequenceId) : appInfo.engine()?.previewManifest(project.id, project.revision, app.sequenceId, wantedIds);
    void request?.then((plan) => {
      // 同一版工程里一段的编译结果不变，所以合并上一批：跨过一格补新段时旧段不消失。
      if (!disposed) setManifest((previous) => previous && previous.project === project ? { project, plan: mergePlans(previous.plan, plan) } : { project, plan });
    }).catch(() => { if (!disposed) setPreviewError("预览计划读取失败，请切换工程后重试"); });
    return () => { disposed = true; };
  }, [project, wantedKey, candidate]);
  useEffect(() => {
    if (!play.playing) return;
    if (!end || sourceMode) { playhead.pause(); return; }
    let last = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      const next = playhead.value + (now - last) / 1000 * TIMEBASE * play.rate;
      last = now;
      if (play.rate > 0 && next >= end) { playhead.set(end); playhead.pause(); }
      else if (play.rate < 0 && next <= 0) { playhead.set(0); playhead.pause(); }
      else playhead.set(next);
    }, 20);
    return () => window.clearInterval(id);
  }, [play.playing, play.rate, end, sourceMode]);
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

  /** 预览与缓存的那些动作：代理档位、清理代理、清理缓存。与「设置」里那一档同一批 store 函数。 */
  const monitorMenu = (anchor: HTMLButtonElement) => {
    const rect = anchor.getBoundingClientRect();
    const entries: MenuEntry[] = [];
    if (app.caps?.features.proxy_playback) {
      entries.push({
        kind: "item", label: `代理 · 关闭${app.proxyWidth ? "" : " ✓"}`, icon: "film",
        title: "代理只影响预览画面，导出始终使用原片",
        run: () => void setProxyWidth(0),
      });
      for (const width of PROXY_WIDTHS) {
        entries.push({
          kind: "item", label: `代理 · ${width}p${app.proxyWidth === width ? " ✓" : ""}`, icon: "film",
          run: () => void setProxyWidth(width),
        });
      }
      entries.push({ kind: "sep", id: "cache" });
    }
    if (app.proxyUsage.count) {
      entries.push({
        kind: "item", icon: "trash",
        label: `清理代理（${(app.proxyUsage.used_bytes / 1048576).toFixed(1)} MB / ${app.proxyUsage.count} 份）`,
        title: "代理是可重建的派生副本，不计入工程",
        run: () => void clearProxyCache(),
      });
    }
    if (app.cacheUsage.count) {
      entries.push({
        kind: "item", icon: "trash",
        label: `清理派生缓存（${(app.cacheUsage.used_bytes / 1048576).toFixed(1)} MB / ${app.cacheUsage.count} 项）`,
        title: "缩略图、波形与代理都算在内；原片与工程不受影响，下次用到时自动重建",
        run: () => void clearDerivedCache(),
      });
    }
    openContextMenu({
      at: { x: rect.left, y: rect.bottom + 4 },
      title: "预览与缓存", label: "预览与缓存", returnTo: anchor, entries,
    });
  };

  return <section className="preview-col" aria-label="播放器">
    <div className="panel-head monitor-head"><div className="seg mini">
      <button className={!sourceMode ? "active" : ""} onClick={() => setMonitorMode("timeline")}>时间线预览</button>
      <button className={sourceMode ? "active" : ""} disabled={!sourceUrl} onClick={() => setMonitorMode("source")}>素材预览</button>
    </div><span className="spacer" />
      {proposed ? <span className="tag">{candidate ? "批次预演" : app.dryRunError ? "预演未通过" : "正在预演…"}</span> : null}
      {/* 代理分辨率、代理占用、清理代理、缓存占用、清理缓存以前是六颗控件排在监视器标题那一行上，
          把「预览模式」挤到一边。它们都是「设置」里已有的那一档，这里只留一只手：
          一个 ⋯ 打开同一份动作，正在生成代理时那枚小胶囊仍报进度。 */}
      {app.proxyWidth && app.proxyStatus.done < app.proxyStatus.total ? (
        <span className="tag" title="代理正在为预览生成缩略副本；导出始终使用原片">
          {`${app.proxyStatus.done}/${app.proxyStatus.total}`}
        </span>
      ) : null}
      <button
        type="button"
        className="icon-btn"
        aria-label="预览与缓存"
        title="代理分辨率、派生缓存与清理——设置里也有同一档"
        onClick={(event) => monitorMenu(event.currentTarget)}
      >
        <Icon name="more" />
      </button>
      <button className={`btn tiny subtle${safe === "off" ? "" : " active"}`} onClick={() => cycleSafeArea()} title={safeTitle}>安全框 · {SAFE_LABELS[safe]}</button>
      <IconBtn icon="fullscreen" label="全屏预览" onClick={() => void monitorRef.current?.requestFullscreen()} />
    </div>
    <div ref={monitorRef} className="monitor-wrap"><div className="monitor" style={{ aspectRatio: `${project.settings.width} / ${project.settings.height}`, width: `min(100cqw, calc(100cqh * ${project.settings.width / project.settings.height}))` }}>
      <FilterDefs plan={displayPlan} />
      {sourceMode && sourceUrl ? sourceInfo?.kind === "image" ? <img src={sourceUrl} alt={sourceInfo.label} /> : sourceInfo?.kind === "audio" ? <><audio key={sourceUrl} ref={(node) => { sourceRef.current = node; }} src={sourceUrl} preload="metadata" onTimeUpdate={(e) => setSourceCursor(e.currentTarget.currentTime * TIMEBASE)} onEnded={() => setSourcePlaying(false)} /><div className="monitor-empty"><Icon name="volume" size={32} /><div className="monitor-title">{sourceInfo.label}</div><div className="monitor-sub">标记需要的声音区间，插入或覆盖到目标声音轨</div></div></> : <video key={sourceUrl} ref={(node) => { sourceRef.current = node; }} src={sourceUrl} playsInline preload="metadata" onTimeUpdate={(e) => setSourceCursor(e.currentTarget.currentTime * TIMEBASE)} onEnded={() => setSourcePlaying(false)} onError={() => { setSourcePlaying(false); setPreviewError("素材无法解码"); }} /> : <>
        {displayPlan ? project.tracks.filter((track) => track.kind === "video" && !track.hidden).map((track) => <div key={track.id} className="preview-track" style={{ mixBlendMode: displayPlan.track_blend_modes?.[track.id] ?? "normal" }}>
          {visuals.filter((v) => v.track.id === track.id).map(({ clip }) => <PreviewLayer key={clip.id} clip={clip} track={track} project={project} plan={displayPlan.clips[clip.id]} manifest={displayPlan} streams={app.streams} mixed={displayPlan.mixed_track_ids.includes(track.id)} url={app.streams[clip.asset_id]} ticks={play.ticks} playing={ready && play.playing} rate={play.rate} monitorMuted={monitorMuted} />)}
        </div>) : null}
        {displayPlan ? sounds.map(({ clip, track }) => <PreviewLayer key={clip.id} clip={clip} track={track} project={project} plan={displayPlan.clips[clip.id]} url={app.streams[clip.asset_id]} ticks={play.ticks} playing={ready && play.playing} rate={play.rate} monitorMuted={monitorMuted} />) : null}
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
      {!sourceMode && play.playing && play.rate !== 1 ? <span className="tag accent mono shuttle-chip" role="status" aria-label={"播放速度 " + play.rate + " 倍"}>{play.rate}x</span> : null}
      <span className="spacer" /><IconBtn icon={monitorMuted ? "mute" : "volume"} label="切换监听静音（不影响导出）" active={monitorMuted} onClick={() => setMonitorMuted(!monitorMuted)} />
      <span className="seq-info mono">{project.settings.width}×{project.settings.height} · {rateLabel(project.settings.frame_rate)}</span>
    </div>
  </section>;
}

function NestedPreview({ id, project, manifest, streams, ticks, playing, monitorMuted, parentGain, clockRate, rate }: {
  id: string; project: Project; manifest: PreviewManifest; streams: Record<string, string>; ticks: number; playing: boolean; monitorMuted: boolean; parentGain: () => number; clockRate: number; rate: number;
}) {
  const sequence = project.sequences?.[id]; const plan = manifest.sequences?.[id];
  const byTrack = useMemo(() => {
    const rows = new Map<string, Clip[]>();
    for (const clip of Object.values(sequence?.clips ?? {})) { const list = rows.get(clip.track_id) ?? []; list.push(clip); rows.set(clip.track_id, list); }
    return rows;
  }, [sequence]);
  if (!sequence || !plan) return <div className="layer-error">合成不存在或预览计划未就绪</div>;
  return <div className="preview-sequence">{sequence.tracks.filter((t) => t.kind === "video" ? !t.hidden : !t.muted).map((track) => <div key={track.id} className="preview-track" style={{ mixBlendMode: plan.track_blend_modes?.[track.id] ?? "normal" }}>
    {(byTrack.get(track.id) ?? []).filter((c) => ticks >= c.position_ticks && ticks < c.position_ticks + c.duration_ticks).map((clip) => <PreviewLayer key={clip.id} clip={clip} track={track} project={project} plan={plan.clips[clip.id]} manifest={manifest} streams={streams} url={streams[clip.asset_id]} ticks={ticks} playing={playing} monitorMuted={monitorMuted} parentGain={parentGain} clockRate={clockRate} rate={rate} interactive={false} mixed={plan.mixed_track_ids.includes(track.id)} />)}
  </div>)}</div>;
}

function PreviewLayer({ clip, track, project, plan, url, ticks, playing, monitorMuted, mixed = false, manifest, streams = {}, interactive = true, parentGain, clockRate = 1, rate = 1 }: {
  clip: Clip; track: Track; project: Project; plan: PreviewManifest["clips"][string] | undefined; url?: string; ticks: number; playing: boolean; monitorMuted: boolean; mixed?: boolean; manifest?: PreviewManifest; streams?: Record<string, string>; interactive?: boolean; parentGain?: () => number; clockRate?: number; rate?: number;
}) {
  const elementRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  // 1.234：链上有立方表时画面改由一块 WebGL2 画布画（同一张表、同一档四面体插值），
  // 视频/图片原件只是源——它仍要播（提供时钟与声音），只是不再直接画到屏幕上。
  const imageRef = useRef<HTMLImageElement | null>(null);
  const gradeCanvas = useRef<HTMLCanvasElement | null>(null);
  const wrappers = useRef<Partial<Record<AnimatedEffect, HTMLElement | null>>>({});
  const fades = useRef<Partial<Record<"opacity" | "gain", HTMLElement | null>>>({});
  // 1.98: 柔焦的曲线编译成一格一步的窗，浏览器只把那份窗动画到这一层 `filter` 上。
  const blurs = useRef<Partial<Record<"blur" | "edge", HTMLElement | null>>>({});
  // 1.192：第二路画面那几张图按引擎的窗表自己挪位置，每一张一个动画。
  const layers = useRef<(HTMLElement | null)[]>([]);
  const blends = useRef<Partial<Record<"picture" | "sound" | "black" | "white", HTMLElement | null>>>({});
  // 转场搬的是整层：位移、放大与那条擦除各占一层包装，全部由引擎下发的点表驱动。
  // 嵌套的 transform 天生相加、嵌套的 opacity 天生相乘，所以预览与导出读同一份数就得到同一条边。
  const moves = useRef<Partial<Record<"motion_x" | "motion_y" | "zoom" | "reveal", HTMLElement | null>>>({});
  const animations = useRef<Animation[]>([]); const [error, setError] = useState("");
  const asset = project.assets[clip.asset_id]; const isAudio = track.kind === "audio"; const isImage = asset?.kind === "image";
  const canvasGrade = plan && gradeNeedsCanvas(plan.grade) ? plan.grade : null;
  // 1.276：键也走同一块画布。要不要走由 `chromaNeedsCanvas` 一处说，界面不再自己判「这段有没有键」。
  const canvasChroma = plan && chromaNeedsCanvas(plan.chroma) ? plan.chroma : null;
  // 画布的失败不藏着：拿不到 WebGL2 或着色器编不过时，画面退回未套 LUT 的原件并明说，
  // 而不是留一块黑（黑会被当成「这段就是黑的」）。
  const [canvasFailed, setCanvasFailed] = useState(false);
  const canvasLive = (canvasGrade !== null || canvasChroma !== null) && !canvasFailed;
  // 「看遮罩」由应用状态一处说（检查器那颗勾），这里只负责把它交给画布。
  const chromaMatte = useApp().chromaMatte;
  const relative = (ticks - clip.position_ticks) / TIMEBASE;
  const pace = pacing(clip.speed_percent ?? 100, plan?.speed, relative);
  const effectiveRate = pace.rate * clockRate;
  // 淡的当前倍数：由引擎下发的包络曲线驱动的那层 div 读出，界面自己不数时间。
  const fadeValue = (name: "opacity" | "gain") => {
    const node = fades.current[name];
    return node ? Number(getComputedStyle(node).opacity) : 1;
  };
  useLayoutEffect(() => {
    if (!plan) return;
    const created: Animation[] = [];
    for (const property of Object.keys(plan.curves) as AnimatedEffect[]) {
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
    // 整层位移与转场放大：与片段自己的 x/y/scale 各走一层包装，相加由嵌套 transform 完成，
    // 所以预览不必重算任何一条曲线——它动画的就是引擎下发的那份点表。
    for (const { channel, node, identity, transform } of [
      { channel: "motion_x", node: moves.current.motion_x, identity: 0, transform: (value: number) => `translateX(${value * 100}%)` },
      { channel: "motion_y", node: moves.current.motion_y, identity: 0, transform: (value: number) => `translateY(${value * 100}%)` },
      { channel: "scale", node: moves.current.zoom, identity: 1, transform: (value: number) => `scale(${value})` },
    ] as const) {
      const curve = plan.transition[channel];
      if (!node || !curve?.some((point) => point.value !== identity)) continue;
      const animation = node.animate(curve.map(({ value, offset, easing }) => ({ offset, easing, transform: transform(value) })), { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    }
    // 擦除露出的是空间：clip-path 的硬边走引擎那条斜坡的中点（羽化宽由引擎下发，界面不写死）。
    const wipe = plan.transition.wipe; const reveal = moves.current.reveal;
    if (wipe && reveal) {
      const animation = reveal.animate(wipe.curve.map(({ value, offset, easing }) => ({ offset, easing, clipPath: wipeClipPath(wipe, value) })), { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    }
    // 淡入淡出走自己的一条包络曲线，与上面那条属性曲线相乘（嵌套 opacity 天生就是乘法），
    // 所以一次淡不会把音量关键帧或闪避曲线抹掉——引擎侧的 `expression` 乘的是同一条曲线。
    for (const name of ["opacity", "gain"] as const) {
      const curve = plan.fade?.[name]; const wrapper = fades.current[name];
      if (!curve || !wrapper) continue;
      const animation = wrapper.animate(curve.map(({ value, offset, easing }) => ({ offset, easing, opacity: value })), { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    }
    // 柔焦：与导出同一份窗表，每段一步（`steps(1, end)`），所以预览里也不会出现导出没有的中间态。
    for (const name of ["blur"] as const) {
      const curve = plan.spatial?.[name]; const wrapper = blurs.current[name];
      if (!curve || !wrapper) continue;
      const animation = wrapper.animate(blurFrames(curve), { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    }
    // 清晰（1.123）：同一份窗表，每一窗换成那一个 `<filter>`，零强度的那窗换回 `none`。换的是整条
    // `filter`——CSS 不能只动共享串里的一项，这也是引擎把静态 url 挪出 `color_filter` 的同一个理由。
    const stepped = sharpenSteps(plan.sharpen); const edge = blurs.current.edge;
    if (stepped && edge) {
      const animation = edge.animate(sharpenFrames(stepped.curve), { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    }
    // 第二路画面按窗挪动（1.192）：动画帧就是引擎那份窗表换的数，一格一步，
    // 与导出那几次 `overlay:enable` 守同一批格子；没有窗的一张都不挂动画（走静态那条式子）。
    (plan?.layer ?? []).forEach((row, index) => {
      const node = layers.current[index];
      const frames = layerFrames(row.windows);
      if (!node || !frames) return;
      const animation = node.animate(frames, { duration: plan.duration_ms, fill: "both" });
      animation.pause(); created.push(animation);
    });
    animations.current = created;
    return () => { created.forEach((a) => a.cancel()); animations.current = []; };
  }, [plan]);
  useLayoutEffect(() => { for (const animation of animations.current) animation.currentTime = relative * 1000; }, [relative, plan]);
  // 视频层停在片段本地时间那一格：暂停时换播放头就 seek，播放中这一层根本不挂载。
  useLayoutEffect(() => {
    (plan?.layer ?? []).forEach((row, index) => {
      const node = layers.current[index];
      if (row.kind !== "video" || !(node instanceof HTMLVideoElement)) return;
      if (!Number.isFinite(node.duration) || node.duration <= 0) return;
      const target = Math.min(Math.max(0, relative), Math.max(0, node.duration - 0.001));
      if (Math.abs(node.currentTime - target) > 0.04) node.currentTime = target;
    });
  }, [relative, plan]);
  useEffect(() => {
    const element = elementRef.current; if (!element) return;
    // 1.281：走带速度乘进这条元素的播放率（正放 2x/4x/8x）；倒放时元素不往前播，
    // 每一格由下面那条 synchronize 把它 seek 到播放头那一帧——HTML 视频没有负的播放率。
    const reverse = rate < 0;
    element.playbackRate = Math.min(16, Math.max(.0625, pace.rate * clockRate * Math.abs(rate)));
    element.preservesPitch = true;
    const frozen = pace.rate <= 0 || reverse;
    const target = clip.source_in_ticks / TIMEBASE + pace.source;
    const synchronize = () => { if (!playing || frozen || Math.abs(element.currentTime - target) > 0.15) element.currentTime = target; };
    if (element.readyState) synchronize(); else element.addEventListener("loadedmetadata", synchronize, { once: true });
    // 变速/倒放不出声：2x 的音频与成片不是一条声音（DaVinci 也是静音走带）。
    element.muted = monitorMuted || track.muted || rate !== 1;
    if (playing) {
      if (asset?.verified?.has_audio) {
        const gain = wrappers.current.gain;
        const sound = blends.current.sound;
        const value = (gain ? Number(getComputedStyle(gain).opacity) * 4 : 1) * (sound ? Number(getComputedStyle(sound).opacity) : 1) * fadeValue("gain") * track.volume * (project.settings.master_gain ?? 1) * (plan?.sound_enabled ? 1 : 0) * (rate === 1 ? 1 : 0) * (parentGain?.() ?? 1);
        const node = gainNode(element);
        if (node && audioContext) node.gain.setValueAtTime(value, audioContext.currentTime); else element.volume = Math.min(1, value);
      }
      if (frozen) element.pause(); else if (element.paused) void element.play().catch(() => setError("媒体无法播放，请检查素材格式"));
    } else element.pause();
    return () => element.removeEventListener("loadedmetadata", synchronize);
  }, [relative, playing, rate, clip.source_in_ticks, clip.speed_percent, clip.embedded_audio, isAudio, track.muted, track.volume, monitorMuted, asset?.verified?.has_audio, plan, parentGain, clockRate]);
  useEffect(() => { const element = elementRef.current; return () => element?.pause(); }, []);
  // 文字层的 CSS 由 textStyle.ts 从同一份 TextStyle 算出，界面不再自己拼一遍。
  const textFonts = useApp().caps?.text_fonts ?? [];
  const inheritedGain = () => {
    const gain = wrappers.current.gain; const sound = blends.current.sound;
    return (gain ? Number(getComputedStyle(gain).opacity) * 4 : 1) * (sound ? Number(getComputedStyle(sound).opacity) : 1) * fadeValue("gain") * track.volume * (plan?.sound_enabled ? 1 : 0) * (parentGain?.() ?? 1);
  };
  const media = asset?.sequence_id && manifest ? <NestedPreview id={asset.sequence_id} project={project} manifest={manifest} streams={streams} ticks={clip.source_in_ticks + Math.floor((ticks - clip.position_ticks) * (clip.speed_percent ?? 100) / 100)} playing={playing} monitorMuted={monitorMuted || track.muted || !plan?.sound_enabled} parentGain={inheritedGain} clockRate={clockRate * (clip.speed_percent ?? 100) / 100} rate={rate} /> : clip.text ? <div className="caption-layer" style={textLayerStyle(clip.text, textFonts)}><span>{clip.text.body}</span></div> : !url ? <div className="layer-error">「{asset?.label}」素材离线或未导入</div> : isImage ? <img ref={imageRef} className={canvasLive ? "grade-source-hidden" : undefined} crossOrigin="anonymous" src={url} alt={asset?.label} /> : isAudio ? <audio ref={(node) => { elementRef.current = node; }} crossOrigin="anonymous" src={url} preload="auto" onError={() => setError("音频无法解码")} /> : <video ref={(node) => { elementRef.current = node; }} className={canvasLive ? "grade-source-hidden" : undefined} crossOrigin="anonymous" src={url} playsInline preload="auto" onError={() => setError("视频无法解码")} />;
  // 「叠一层原图」这条边（1.193）：导出那两步是 `(1-mix)·raw + mix·mode(graded, raw)`，浏览器用
  // 两层就画得出来——底层原图，上面一个 `opacity=mix` 的隔离容器，容器内「已调色」作底、原图按
  // `mix-blend-mode` 相合。`normal` 那一档要交换容器里那两层的顺序（`compositeSwap` 一处判断）：
  // FFmpeg 的 normal 交回第一个输入、CSS 的交回上面那一层。
  const graded = <div ref={(node) => { blurs.current.edge = node; }} className="layer-edge" style={{ filter: plan?.edge_filter ?? undefined }}><div ref={(node) => { blurs.current.blur = node; }} className="layer-blur"><div className="layer-transform" style={{ filter: plan?.color_filter }}>{media}{canvasLive ? <canvas ref={gradeCanvas} className="grade-canvas" aria-hidden="true" /> : null}{canvasGrade && canvasFailed ? <div className="layer-error grade-fallback">预览画不出这张立方表（这台浏览器没有可用的 WebGL2），画面按未套 LUT 显示；导出不受影响</div> : null}{canvasChroma && !canvasGrade && canvasFailed ? <div className="layer-error grade-fallback">预览画不出这个色度键（这台浏览器没有可用的 WebGL2），画面按未抠显示；导出不受影响</div> : null}</div></div></div>;
  // 1.196：视频那一段的「原图」不是第二路解码，而是把已经解码好的那一帧拓进一张 canvas。
  // 本轮量过（AGENTS 1.195 那一节）：暂停与逐帧时两路逐格 0 差，而播放中再开一路解码会把主线程
  // 的动画帧率打掉一半（rAF 181→94）——所以引擎对视频交回 `motion:"paused"`，播放中这一级不画。
  // 这一摞里那幅原图会出现**两次**（底下一次、容器里一次），所以拓帧要按盒子扫一遍所有画布：
  // 第一版只拿了一个 ref，两个 `<canvas>` 共用它就只有一张被画过，另一张是空的——预览与导出
  // 差 87 级量的就是这件事（比不画的 78 级还差），这一版按 `querySelectorAll` 逐张拓。
  const layerBox = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const source = elementRef.current as HTMLVideoElement | null;
    if (!source || isImage) return;
    const paint = () => {
      if (!source.videoWidth) return;
      for (const canvas of layerBox.current?.querySelectorAll<HTMLCanvasElement>("canvas.composite-raw") ?? []) {
        canvas.width = source.videoWidth;
        canvas.height = source.videoHeight;
        const context = canvas.getContext("2d");
        if (context) {
          context.clearRect(0, 0, canvas.width, canvas.height);
          context.drawImage(source, 0, 0);
        }
      }
    };
    paint();
    source.addEventListener("seeked", paint);
    source.addEventListener("loadeddata", paint);
    return () => {
      source.removeEventListener("seeked", paint);
      source.removeEventListener("loadeddata", paint);
    };
  }, [relative, playing, url, isImage]);
  // 1.234：立方表那条链画在画布上。画布的**内部分辨率跟着源的大小走**（按这一格等比缩，
  // 最多两倍），CSS 再按 `object-fit: contain` 装进这一格——所以它和原来的 <video>/<img>
  // 在同一格里占的是同一块画面，补边与遮罩坐标一个字都不用改。
  // 换帧：视频播放时按 rAF、暂停/逐帧时按 seeked 与 loadeddata；图片只画一次（load）。
  useEffect(() => { setCanvasFailed(false); }, [canvasGrade?.id, canvasChroma]);
  useEffect(() => {
    const canvas = gradeCanvas.current;
    const source = (elementRef.current ?? imageRef.current) as HTMLVideoElement | HTMLImageElement | null;
    if (!canvas || (!canvasGrade && !canvasChroma) || !source) return;
    let frame = 0;
    const draw = () => {
      const box = canvas.parentElement?.getBoundingClientRect();
      const width = (source as HTMLVideoElement).videoWidth || (source as HTMLImageElement).naturalWidth || 0;
      const height = (source as HTMLVideoElement).videoHeight || (source as HTMLImageElement).naturalHeight || 0;
      if (!width || !height) return;
      const scale = Math.min((box?.width ?? width) / width, (box?.height ?? height) / height, 2);
      // 1.235：播放时这一支每帧都跑；`canvas.width = …` 每次都重新分配并清空整块缓冲，
      // 尺寸没变就不该付这笔钱（量过：640×360 的片子在 412×232 的画布上，改与不改都是
      // 60.2 帧/秒、间隔 p50/p95/max 16.7/16.7/16.8 ms——所以这是省下来的浪费，不是换来的流畅）。
      const nextWidth = Math.max(2, Math.round(width * scale));
      const nextHeight = Math.max(2, Math.round(height * scale));
      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
      }
      // 同一份源可能因为跨源而拒绝上传（量到过：`<img>` 少一个 crossOrigin，texImage2D 抛
      // SecurityError，画布留在黑底）；抛出来的失败与返回假的失败走同一条退路。
      let painted = false;
      try {
        painted = paintGrade(canvas, source, canvasGrade, plan?.color_basics ?? [1, 1, 1], canvasChroma, chromaMatte);
      } catch {
        painted = false;
      }
      if (!painted) setCanvasFailed(true);
    };
    draw();
    const events = ["loadeddata", "loadedmetadata", "seeked", "timeupdate", "load"];
    for (const name of events) source.addEventListener(name, draw);
    if (playing && source instanceof HTMLVideoElement) {
      const loop = () => { draw(); frame = requestAnimationFrame(loop); };
      frame = requestAnimationFrame(loop);
    }
    return () => {
      for (const name of events) source.removeEventListener(name, draw);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [canvasGrade?.id, plan?.color_basics, canvasChroma, chromaMatte, playing, url]);

  const rawAt = (blend?: BlendMode) => <div className="layer-transform">{isImage ? <img className="composite-raw" alt="" aria-hidden="true" src={url} style={blend ? { mixBlendMode: blend } : undefined} /> : <canvas className="composite-raw" aria-hidden="true" style={blend ? { mixBlendMode: blend } : undefined} />}</div>;
  const edge = plan?.composite;
  // 画不画得了只听清单里那一行：`paintable` 是「这一段有没有第二幅画」，`motion` 是「什么时候
  // 画得成」（判断只在 `compositeLive` 一处），`&& url` 问的是引擎问不到的那件事——文件这一会儿
  // 还在不在原地。除此之外多问一句「这段素材是什么」就是第二个判断。
  const picture = edge?.paintable && url && compositeLive(edge.motion, playing) ? <div className="composite-stack">{rawAt()}<div className="composite-top" style={{ opacity: edge.mix }}>{compositeSwap(edge.mode) ? <>{rawAt()}{graded}</> : <>{graded}{rawAt(edge.mode)}</>}</div></div> : graded;
  return <><div ref={(node) => { layerBox.current = node; }} className={`preview-layer${isAudio ? " audio-layer" : ""}`} style={{ mixBlendMode: mixed ? "plus-lighter" : "normal" }} onClick={interactive ? () => selectClip(clip.id) : undefined}>
    <div ref={(node) => { wrappers.current.gain = node; }} className="gain-sample" aria-hidden="true" />
    <div ref={(node) => { fades.current.gain = node; }} className="gain-sample" aria-hidden="true" />
    <div ref={(node) => { blends.current.sound = node; }} className="gain-sample" aria-hidden="true" />
    <div ref={(node) => { blends.current.picture = node; }} className="layer-transform"><div ref={(node) => { moves.current.reveal = node; }} className="layer-transform"><div ref={(node) => { moves.current.motion_x = node; }} className="layer-transform"><div ref={(node) => { moves.current.motion_y = node; }} className="layer-transform"><div ref={(node) => { moves.current.zoom = node; }} className="layer-transform"><div ref={(node) => { fades.current.opacity = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.opacity = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.x = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.y = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.scale = node; }} className="layer-transform"><div ref={(node) => { wrappers.current.rotation = node; }} className="layer-transform"><MaskPicture clip={clip} image={plan?.mask_image} extra={plan?.extra_mask_images} extraWindows={plan?.extra_mask_windows} extraUnits={plan?.extra_mask_units} follow={Boolean(plan?.extra_masks_follow)} editable={interactive} animation={plan?.mask_curves && (plan.mask_unit || plan.mask_shape) ? { unit: plan.mask_unit ?? null, curves: plan.mask_curves } : null} shape={plan?.mask_shape} rotation={plan?.mask_rotation_windows}>{picture}</MaskPicture></div></div></div></div></div></div></div></div></div></div></div>
    {(plan?.layer ?? []).map((row, index) => {
      if (!row.paintable) return null;
      // 1.274：视频层多开一路解码，播放中不画（1.195 量过：rAF 181 → 94）；暂停与逐帧时
      // 把那一格 seek 到片段本地时间再画，导出每一帧都画。什么时候画得成只问 `compositeLive`。
      if (!compositeLive(row.motion, playing)) return null;
      const style = { mixBlendMode: row.mode, opacity: row.mix, ...layerStyle(row.offset_x, row.offset_y, row.scale, row.rotation ?? 0) };
      const ref = (node: HTMLElement | null) => { layers.current[index] = node; };
      return row.kind === "video"
        ? <video key={`${row.asset_id}-${index}`} ref={ref} className="layer-grade" muted playsInline preload="auto" aria-hidden="true" src={streams[row.asset_id]} style={style} />
        : <img key={`${row.asset_id}-${index}`} ref={ref} className="layer-grade" alt="" aria-hidden="true" src={streams[row.asset_id]} style={style} />;
    })}
    {(plan?.layer ?? []).some((row) => !row.paintable) ? <p className="layer-offline" role="status">第二路画面有一层现在画不成（那一层指的素材不在工程里、不是图像，或没有引擎验过的媒体记录）：导出会整条拒绝这一段——在那一层的「叠哪一张画面」里换一张已导入的图，或把那一层从链上摘掉。</p> : null}
    {error || playing && pace.rate > 0 && (effectiveRate < .0625 || effectiveRate > 16) ? <div className="layer-error">{error || "叠加速度超出浏览器连续播放范围，请暂停逐帧预览或导出检查"}</div> : null}
  </div>{!isAudio && plan?.transition.black.some((point) => point.value > 0) ? <div ref={(node) => { blends.current.black = node; }} className="transition-black" style={{ mixBlendMode: "plus-lighter" }} aria-hidden="true" /> : null}{!isAudio && plan?.transition.white?.some((point) => point.value > 0) ? <div ref={(node) => { blends.current.white = node; }} className="transition-white" aria-hidden="true" /> : null}</>;
}

export function PreviewFooter() {
  const app = useApp(); const play = usePlay();
  return <div className="preview-foot"><span className="mono" title="合成预览：直接在画面里拖就是位置，角柄是缩放，转一圈是旋转，检查器里的透明度与音量同样落在这一格画面上。">{humanDuration(Math.max(0, timelineEnd(app.project) - play.ticks))} 剩余</span><span className="spacer" /></div>;
}
