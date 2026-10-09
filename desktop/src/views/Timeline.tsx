import { useEffect, useMemo, useRef, useState } from "react";

import { Icon, IconBtn } from "../ui";
import { TIMEBASE, align, frameTicks, humanDuration, timecode } from "../time";
import { transitionLabel } from "../engine";
import type { Clip, Marker, Project, Track } from "../engine";
import {
  addLibraryItemToTimeline,
  addTrack,
  playhead,
  prefs,
  quantum,
  redoStep,
  removeTrack,
  selectClip,
  setSequenceMark,
  snapTo,
  splitClip,
  timelineEnd,
  toast,
  trimClip,
  undo,
  updateTrack,
  useApp,
  useEdit,
  usePlay,
  selectClips,
  copySelection,
  pasteSelection,
  removeSelection,
  moveSelection,
  splitSelection,
  selectionFor,
  rollClip,
  openSequence,
  cutTrackSilence,
  duckTrack,
  alignTrackLoudness,
  addMarker,
  removeMarker,
  setMarker,
  splitAtMarkers,
  setFadeWindowsForClips,
} from "../store";
import { EMPTY_TRACK_HINT, trackToolBlocker, fadeDragBatch, fadeDragTicks, fadeProperties, fadeWindows, type FadeProperty, type FadeSide } from "../effects";
import { selectionQuantum, timelineTracks } from "../selection";

const HEAD = 112;
const ROW = 56;

type DragMode = "move" | "trim-l" | "trim-r" | "roll-l" | "roll-r";
type Drag = {
  clipId: string;
  mode: DragMode;
  startX: number;
  origin: { position: number; sourceIn: number; duration: number };
  x: number;
  clipIds: string[];
  clipIdSet: Set<string>;
  moveQuantum: number;
  snapQuantum: number;
  minPosition: number;
  edges: number[];
  rowShift: number;
  trimSourceHead: number;
  trimMaxDuration: number;
  roll: {
    leftId: string;
    rightId: string;
    left: { position: number; sourceIn: number; duration: number };
    right: { position: number; sourceIn: number; duration: number };
  } | null;
};

function moveDelta(drag: Drag, ctx: { px: number; snap: boolean; head: number; q: number }): number {
  const raw = drag.origin.position + drag.x / ctx.px * TIMEBASE;
  const snap = { ...ctx, q: drag.snapQuantum, edges: drag.edges };
  const start = ctx.snap ? magnet(raw, snap) : raw;
  const end = ctx.snap ? magnet(raw + drag.origin.duration, snap) - drag.origin.duration : raw;
  const candidate = Math.abs(start - raw) <= Math.abs(end - raw) ? start : end;
  const delta = Math.round((candidate - drag.origin.position) / drag.moveQuantum) * drag.moveQuantum;
  return Math.max(-Math.floor(drag.minPosition / drag.moveQuantum) * drag.moveQuantum, delta);
}

/** 拖拽中的候选几何：不落库，只画出来，松手才变成一条命令。 */
function preview(clip: Clip, drag: Drag | null, ctx: { px: number; q: number; maxDuration: number; edges: number[]; snap: boolean; head: number; staticSource?: boolean }): Clip | null {
  if (!drag || !drag.clipIdSet.has(clip.id)) return null;
  const delta = (drag.x / ctx.px) * TIMEBASE;
  if (drag.mode === "move") {
    return { ...clip, position_ticks: clip.position_ticks + moveDelta(drag, ctx) };
  }
  ctx = { ...ctx, q: drag.moveQuantum, maxDuration: drag.trimMaxDuration };
  if (drag.mode === "roll-l" || drag.mode === "roll-r") {
    if (!drag.roll || (clip.id !== drag.roll.leftId && clip.id !== drag.roll.rightId)) return null;
    const raw = (drag.x / ctx.px) * TIMEBASE;
    let shift = align(raw, ctx.q, 0);
    shift = Math.min(shift, drag.roll.right.duration - ctx.q);
    shift = Math.max(shift, ctx.q - drag.roll.left.duration);
    if (clip.id === drag.roll.leftId) return { ...clip, duration_ticks: drag.roll.left.duration + shift };
    const speed = (clip.speed_percent ?? 100) / 100;
    return {
      ...clip,
      position_ticks: drag.roll.right.position + shift,
      source_in_ticks: ctx.staticSource ? 0 : Math.max(0, drag.roll.right.sourceIn + Math.round(shift * speed)),
      duration_ticks: drag.roll.right.duration - shift,
    };
  }
  if (drag.mode === "trim-l") {
    const speed = (clip.speed_percent ?? 100) / 100;
    const end = drag.origin.position + drag.origin.duration;
    let position = align(drag.origin.position + delta, ctx.q, 0);
    position = Math.max(ctx.staticSource ? 0 : Math.max(0, Math.ceil((drag.origin.position - drag.trimSourceHead / speed) / ctx.q) * ctx.q), Math.min(position, end - ctx.q));
    const shift = position - drag.origin.position;
    return {
      ...clip,
      position_ticks: position,
      source_in_ticks: ctx.staticSource ? 0 : Math.max(0, clip.source_in_ticks + Math.round(shift * speed)),
      // 左缘不能越过素材起点：source_in 已为 0 时时长不再变长。
      duration_ticks: drag.origin.duration - shift,
    };
  }
  const duration = Math.min(
    Math.floor(ctx.maxDuration / ctx.q) * ctx.q,
    Math.max(ctx.q, align(drag.origin.duration + delta, ctx.q, 0))
  );
  return { ...clip, duration_ticks: duration };
}

function magnet(value: number, ctx: { q: number; edges: number[]; head: number; px: number }) {
  const tolerance = (8 / ctx.px) * TIMEBASE;
  const candidates = [...ctx.edges, ctx.head, 0].map((item) => align(item, ctx.q, 0));
  let best = align(value, ctx.q, 0);
  let bestDistance = Infinity;
  for (const candidate of candidates) {
    const distance = Math.abs(candidate - value);
    if (distance <= tolerance && distance < bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
  }
  return best;
}

export function Timeline() {
  const app = useApp();
  const edit = useEdit();
  const play = usePlay();
  const project = app.project;
  const [drag, setDrag] = useState<Drag | null>(null);
  const [markerDrag, setMarkerDrag] = useState<{ id: string; ticks: number } | null>(null);
  const [markerEdit, setMarkerEdit] = useState<string | null>(null);
  const [dropHint, setDropHint] = useState<{ trackId: string; ticks: number } | null>(null);
  const [marquee, setMarquee] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll || !play.playing) return;
    const x = HEAD + play.ticks / TIMEBASE * edit.pxPerSec;
    if (x > scroll.scrollLeft + scroll.clientWidth - 60 || x < scroll.scrollLeft + HEAD)
      scroll.scrollLeft = Math.max(0, x - HEAD - scroll.clientWidth / 3);
  }, [play.ticks, play.playing, edit.pxPerSec]);
  useEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault(); prefs.zoomBy(event.deltaY < 0 ? 1.15 : 1 / 1.15);
      } else if (event.shiftKey) { event.preventDefault(); scroll.scrollLeft += event.deltaY; }
    };
    scroll.addEventListener("wheel", wheel, { passive: false });
    return () => scroll.removeEventListener("wheel", wheel);
  }, [project?.id]);

  const media = useMemo(() => {
    const map = new Map<string, { thumbs: string[]; wave: number[] }>();
    for (const item of app.library) {
      map.set(item.probe.verified.path, { thumbs: item.probe.urls?.thumbnails ?? [], wave: item.probe.waveform ?? [] });
    }
    return map;
  }, [app.library]);

  if (!project) return null;
  const px = edit.pxPerSec;
  const contentTicks = Math.max(timelineEnd(project) + TIMEBASE * 4, TIMEBASE * 20);
  const width = Math.ceil((contentTicks / TIMEBASE) * px) + 80;
  const ordered = timelineTracks(project);
  const splitTracks = new Set(app.selectedClips.filter((id) => { const c = project.clips[id]; return c && play.ticks > c.position_ticks && play.ticks < c.position_ticks + c.duration_ticks; }).map((id) => project.clips[id].track_id));
  const inTransition = Object.values(project.clips).some((c) => splitTracks.has(c.track_id) && c.transition_in && play.ticks >= c.position_ticks && play.ticks < c.position_ticks + c.transition_in.duration_ticks);
  const canSplit = !inTransition && splitTracks.size > 0;

  // 候选与当前状态的差异都画成幽灵：新增、移动、修剪都能一眼看出预演会带来什么变化。
  const ghosts = app.candidate
    ? Object.values(app.candidate.clips).filter((clip) => {
        const live = project.clips[clip.id];
        return (
          !live ||
          live.position_ticks !== clip.position_ticks ||
          live.duration_ticks !== clip.duration_ticks ||
          live.source_in_ticks !== clip.source_in_ticks ||
          live.track_id !== clip.track_id
        );
      })
    : [];

  return (
    <section className="timeline" aria-label="时间线">
      <div className="tl-toolbar">
        <IconBtn icon="cursor" label="选择工具（V）：拖动片段改位置，拖左右边缘改时长" active={edit.tool === "select"} onClick={() => prefs.setTool("select")} />
        <IconBtn icon="razor" label="分割工具（C）：点片段即在点击处切一刀，切成两段可独立删除" active={edit.tool === "razor"} onClick={() => prefs.setTool("razor")} />
        <button className="btn tiny subtle" disabled={!canSplit} title="在播放头处分割选中片段（Ctrl+B）" onClick={() => splitSelection(playhead.value)}>分割</button>
        <IconBtn icon="copy" label="复制选中片段（Ctrl+C）" disabled={!app.selectedClip} onClick={copySelection} />
        <button className="btn tiny subtle" disabled={!app.clipboardCount} onClick={pasteSelection} title="粘贴到播放头（Ctrl+V）">粘贴</button>
        <IconBtn icon="trash" label="删除选中片段，保留空隙（Delete）" disabled={!app.selectedClip} onClick={() => removeSelection()} />
        <button className="btn tiny subtle" disabled={!app.selectedClip} title="删除并向左补齐本轨后续片段（Shift+Delete）" onClick={() => removeSelection(true)}>涟漪删除</button>
        {app.selectedClips.length > 1 ? <span className="tag accent">{app.selectedClips.length} 段</span> : null}
        <span className="divider-v" />
        <IconBtn icon="magnet" label="磁吸（S）：拖动时自动贴到整帧、相邻片段边缘与标记，避免留下 1 帧缝" active={edit.snap} onClick={() => prefs.toggleSnap()} />
        <IconBtn icon="flag" label="在指针处打一个标记（M）：人和 Agent 用同一个整数刻度说「这里」，标记还会成为磁吸边缘" onClick={() => addMarker()} />
        <IconBtn icon="razor" label="在每个标记处切开落在它里面的片段：一次事务、一次撤销；落在边缘或空隙上的标记不产生切点" disabled={!(app.project?.markers ?? []).length} onClick={() => void splitAtMarkers()} />
        <button className={`btn tiny subtle${edit.linkedSelection ? " active" : ""}`} aria-pressed={edit.linkedSelection} title="联动选择：组合与链接一起选中；音画链接一起修剪、分割。Alt 点选可临时单选。" onClick={() => prefs.toggleLinkedSelection()}>联动</button>
        <span className="divider-v" />
        <IconBtn icon="undo" label="撤销：用历史恢复回到上一步（版本号继续增加，不会倒退）" disabled={!app.undo.length} onClick={undo} />
        <IconBtn icon="redo" label="重做：回到撤销前的那一版（Ctrl+Shift+Z）" disabled={!app.redo.length} onClick={redoStep} />
        <IconBtn
          icon="zoomIn"
          label="适应窗口：把整条时间线放进可视范围"
          onClick={() => prefs.fitTo(timelineEnd(project), (scrollRef.current?.clientWidth ?? 1200) - HEAD)}
        />
        <span className="divider-v" />
        <button className="btn subtle" title="再加一层画面：叠标题、画中画需要第二条画面轨" onClick={() => addTrack("video")}>
          <Icon name="plus" size={12} /> 画面轨
        </button>
        <button className="btn subtle" title="再加一条声音轨：配乐与旁白分开控制音量" onClick={() => addTrack("audio")}>
          <Icon name="plus" size={12} /> 声音轨
        </button>
        <span className="spacer" />
        {app.mode === "batch" ? (
          <span className="tag accent" title="动作先进待提交批次，预演通过再写入">批次模式</span>
        ) : (
          <span className="tag off" title="每个动作立刻写成一条命令批次并提交">即时模式</span>
        )}
        <span className="zoom-ctrl">
          <IconBtn icon="zoomOut" label="缩小（-）" onClick={() => prefs.zoomBy(0.8)} />
          <input type="range" min={16} max={320} value={px} aria-label="时间线缩放" onChange={(event) => prefs.setZoom(Number(event.target.value))} />
          <IconBtn icon="zoomIn" label="放大（+）" onClick={() => prefs.zoomBy(1.25)} />
        </span>
      </div>

      <div className="tl-scroll" ref={scrollRef}>
        <div className="tl-inner" style={{ width: width + HEAD, height: (ordered.length + 1) * ROW + 8 }} onPointerDown={(event) => {
          if (event.button !== 0 || edit.tool !== "select" || (event.target as HTMLElement).closest('.clip, .tl-head, .tl-ruler, .transition-badge')) return;
          const inner = event.currentTarget; const rect = inner.getBoundingClientRect();
          if (event.clientX - rect.left < HEAD) return;
          event.preventDefault();
          const x = event.clientX, y = event.clientY;
          const base = event.ctrlKey || event.metaKey || event.shiftKey ? app.selectedClips : [];
          selectClips(base);
          const move = (ev: PointerEvent) => {
            const left = Math.min(x, ev.clientX), right = Math.max(x, ev.clientX), top = Math.min(y, ev.clientY), bottom = Math.max(y, ev.clientY);
            const bounds = inner.getBoundingClientRect();
            setMarquee({ x: left - bounds.left, y: top - bounds.top, width: right - left, height: bottom - top });
            const ids = Array.from(inner.querySelectorAll<HTMLElement>('.clip[data-id]')).filter((e) => { const r = e.getBoundingClientRect(); return r.left < right && r.right > left && r.top < bottom && r.bottom > top; }).map((e) => e.dataset.id!);
            selectClips([...base, ...ids]);
          };
          const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop); setMarquee(null); };
          window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop); window.addEventListener('pointercancel', stop);
        }}>
          {marquee ? <div className="tl-marquee" style={{ left: marquee.x, top: marquee.y, width: marquee.width, height: marquee.height }} aria-hidden="true" /> : null}
          <div className="tl-row ruler-row">
            <div className="tl-head corner">
              <span className="tkind mono" title="标尺单位：时:分:秒">TC</span>
            </div>
            <div
              className="tl-ruler"
              style={{ width }}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                seek(event.clientX - event.currentTarget.getBoundingClientRect().left);
                const move = (ev: PointerEvent) => seek(ev.clientX - (event.currentTarget as HTMLElement).getBoundingClientRect().left);
                const stop = () => {
                  window.removeEventListener("pointermove", move);
                  window.removeEventListener("pointerup", stop);
                  window.removeEventListener("pointercancel", stop);
                };
                window.addEventListener("pointermove", move);
                window.addEventListener("pointerup", stop);
                window.addEventListener("pointercancel", stop);
              }}
            >
              {rulerMarks(contentTicks, px, project)}
              <RangeHandles project={project} px={px} />
              {(project.markers ?? []).map((mark) => {
                const at = markerDrag?.id === mark.id ? markerDrag.ticks : mark.at_ticks;
                const mq = quantum(project, "video");
                return <span
                  key={mark.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`标记 ${mark.name}`}
                  className={`ruler-marker ${mark.color ?? "amber"}${markerDrag?.id === mark.id ? " dragging" : ""}`}
                  style={{ left: (at / TIMEBASE) * px }}
                  title={`${mark.name} · ${timecode(at, project.settings.frame_rate, false)}：左右拖动移动（磁吸生效），单击跳到这里，双击改名与颜色`}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    if (event.button !== 0) return;
                    const ruler = (event.currentTarget as HTMLElement).parentElement as HTMLElement;
                    const startX = event.clientX;
                    const atClient = (clientX: number) => {
                      const raw = Math.max(0, align(((clientX - ruler.getBoundingClientRect().left) / px) * TIMEBASE, mq, 0));
                      if (!edit.snap) return raw;
                      const edges = [
                        ...Object.values(project.clips).flatMap((c) => [c.position_ticks, c.position_ticks + c.duration_ticks]),
                        ...(project.markers ?? []).filter((other) => other.id !== mark.id).map((other) => other.at_ticks),
                      ];
                      return magnet(raw, { q: mq, edges, head: playhead.value, px });
                    };
                    let moved = false;
                    const move = (ev: PointerEvent) => {
                      if (!moved && Math.abs(ev.clientX - startX) < 3) return;
                      moved = true;
                      setMarkerDrag({ id: mark.id, ticks: atClient(ev.clientX) });
                    };
                    const stop = (ev: PointerEvent) => {
                      window.removeEventListener("pointermove", move);
                      window.removeEventListener("pointerup", stop);
                      window.removeEventListener("pointercancel", stop);
                      setMarkerDrag(null);
                      if (ev.type === "pointercancel") return;
                      if (!moved) { seek(mark.at_ticks); return; }
                      const target = atClient(ev.clientX);
                      if (target !== mark.at_ticks) setMarker(mark, { at_ticks: target });
                    };
                    window.addEventListener("pointermove", move);
                    window.addEventListener("pointerup", stop);
                    window.addEventListener("pointercancel", stop);
                  }}
                  onDoubleClick={(event) => { event.stopPropagation(); setMarkerEdit(mark.id); }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); seek(mark.at_ticks); }
                  }}
                >
                  <i aria-hidden="true" />
                  <b>{mark.name}</b>
                  <em
                    role="button"
                    tabIndex={0}
                    aria-label={`删除标记 ${mark.name}`}
                    title="删除这个标记"
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation();
                      void removeMarker(mark.id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        void removeMarker(mark.id);
                      }
                    }}
                  >
                    ×
                  </em>
                  {markerEdit === mark.id ? <MarkerEditor mark={mark} onDone={() => setMarkerEdit(null)} /> : null}
                </span>;
              })
              }
            </div>
          </div>

          {ordered.map((track, index) => (
            <TrackRow
              key={track.id}
              track={track}
              index={index}
              project={project}
              px={px}
              width={width}
              drag={drag}
              setDrag={setDrag}
              dropHint={dropHint}
              setDropHint={setDropHint}
              media={media}
              ghosts={ghosts.filter((clip) => clip.track_id === track.id)}
            />
          ))}

          {!ordered.length ? (
            <div className="tl-empty">
              <Icon name="film" size={16} />
              还没有轨道：点上方「＋ 画面轨」开始，或先从左侧导入素材
            </div>
          ) : null}

          <div className="playhead" style={{ left: HEAD + (play.ticks / TIMEBASE) * px }}>
            <span className="ph-time mono">{timecode(play.ticks, project.settings.frame_rate)}</span>
          </div>
        </div>
      </div>

      {app.dryRunError ? (
        <div className="tl-warning">
          <Icon name="warning" size={13} />
          <span>批次预演未通过：{app.dryRunError}</span>
        </div>
      ) : null}
    </section>
  );

  function seek(offsetPx: number) {
    playhead.pause();
    const value = (offsetPx / px) * TIMEBASE;
    playhead.set(Math.max(0, Math.min(snapTo(project!, "video", value), contentTicks)));
  }
}

function rulerMarks(total: number, px: number, project: Project) {
  const secondsTotal = total / TIMEBASE;
  const step = px >= 150 ? 1 : px >= 70 ? 2 : px >= 34 ? 5 : 10;
  const overHour = secondsTotal >= 3600;
  const items: JSX.Element[] = [];
  for (let s = 0; s <= secondsTotal; s += step) {
    const x = s * px;
    items.push(<span key={`m${s}`} className="ruler-tick big" style={{ left: x }} />);
    items.push(
      <span key={`l${s}`} className="ruler-label mono" style={{ left: x + 3 }}>
        {/* 超过 1 小时后保留时位，否则 01:00:00 会和 00:00 显示成一样 */}
        {overHour
          ? timecode(s * TIMEBASE, project.settings.frame_rate, false)
          : timecode(s * TIMEBASE, project.settings.frame_rate, false).slice(3)}
      </span>
    );
  }
  return items;
}

function TrackRow({
  track,
  index,
  project,
  px,
  width,
  drag,
  setDrag,
  dropHint,
  setDropHint,
  media,
  ghosts,
}: {
  track: Track;
  index: number;
  project: Project;
  px: number;
  width: number;
  drag: Drag | null;
  setDrag: (value: Drag | null) => void;
  dropHint: { trackId: string; ticks: number } | null;
  setDropHint: (value: { trackId: string; ticks: number } | null) => void;
  media: Map<string, { thumbs: string[]; wave: number[] }>;
  ghosts: Clip[];
}) {
  const app = useApp();
  const edit = useEdit();
  const clips = Object.values(project.clips).filter((item) => item.track_id === track.id);
  const emptyTrack = trackToolBlocker(track.id, clips);
  const selectedIds = useMemo(() => new Set(app.selectedClips), [app.selectedClips]);
  const q = quantum(project, track.kind);

  return (
    <div className={`tl-row${track.kind === "audio" ? " audio-row" : ""}`} style={{ height: ROW }}>
      <div className={`tl-head${track.kind === "audio" ? " audio-track" : ""}`} style={{ top: (index + 1) * ROW }}>
        <div className="tl-head-main">
          <span className="tname" title={`轨道 id：${track.id}`}>{track.name}</span>
          <span className="tkind">{track.kind === "video" ? "画面" : "音频"}</span>
        </div>
        <div className="tl-head-btns">
          <button type="button" className={`icon-btn tiny${track.locked ? " active" : ""}`} aria-label={track.locked ? "解锁轨道" : "锁定轨道"}
            title={track.locked ? "解锁轨道" : "锁定轨道：保护这一轨的剪辑"}
            onClick={() => updateTrack(track.id, { locked: !track.locked }, "切换轨道锁定")}><Icon name={track.locked ? "lock" : "unlock"} size={12} /></button>
          {track.kind === "video" ? (
            <IconBtn
              icon={track.hidden ? "eyeOff" : "eye"}
              label={track.hidden ? "显示这一层画面" : "隐藏这一层画面：预览与导出都会跳过它"}
              onClick={() => updateTrack(track.id, { hidden: !track.hidden }, track.hidden ? "显示轨道" : "隐藏轨道")}
            />
          ) : (
            <IconBtn
              icon={track.muted ? "mute" : "volume"}
              label={track.muted ? "取消静音" : "静音这条声音轨：导出时不写入它的声音"}
              onClick={() => updateTrack(track.id, { muted: !track.muted }, track.muted ? "取消静音" : "静音轨道")}
            />
          )}
          <IconBtn
            icon="volume"
            label={
              !emptyTrack
                ? "逐片段测量这条轨的响度，一次写入各自的增益把它们统一到 -16 LUFS（只改音量倍数，不加压缩器）"
                : EMPTY_TRACK_HINT
            }
            disabled={!!emptyTrack}
            onClick={() => alignTrackLoudness(track.id)}
          />
          <IconBtn
            icon="split"
            label={
              !emptyTrack
                ? "剪掉这条轨上所有 0.25 秒以上的停顿并把后面的内容左移：只影响本轨，其它轨保持原位"
                : EMPTY_TRACK_HINT
            }
            disabled={!!emptyTrack}
            onClick={() => cutTrackSilence(track.id)}
          />
          {track.kind === "audio" ? (
            <IconBtn
              icon="volume"
              label={
                !emptyTrack
                  ? "自动闪避：别的声音轨说话时，这条轨按 9 dB 让路，写成音量关键帧（说话结束后 0.6 秒抬回来），只改本轨"
                  : EMPTY_TRACK_HINT
              }
              disabled={!!emptyTrack}
              onClick={() => duckTrack(track.id)}
            />
          ) : null}
          <IconBtn icon="trash" label="删除轨道（必须先清空它上面的片段）" danger onClick={() => removeTrack(track.id)} />
        </div>
      </div>
      <div
        className={`tl-lane${track.kind === "audio" ? " audio-track" : ""}`}
        data-track-id={track.id}
        style={{ width }}
        onDragOver={(event) => {
          if (track.locked) return;
          if (!event.dataTransfer.types.includes("application/x-agentcut-asset")) return;
          event.preventDefault();
          const left = event.currentTarget.getBoundingClientRect().left;
          setDropHint({ trackId: track.id, ticks: Math.max(0, ((event.clientX - left) / px) * TIMEBASE) });
        }}
        onDragLeave={() => setDropHint(null)}
        onDrop={(event) => {
          event.preventDefault();
          if (track.locked) return;
          const raw = event.dataTransfer.getData("application/x-agentcut-asset");
          setDropHint(null);
          const item = app.library.find((entry) => entry.probe.verified.path === raw);
          if (!item) {
            if (raw) toast("error", "找不到这个素材", "素材库可能已经刷新，重新拖一次。");
            return;
          }
          const kind = item.probe.verified.kind;
          if (track.kind === "video" && kind === "audio") {
            toast("warn", "音频不能放在画面轨", "把它拖到绿色的声音轨。");
            return;
          }
          if (track.kind === "audio" && kind !== "audio") {
            toast("warn", "画面素材不能放在声音轨", "把它拖到蓝色的画面轨。");
            return;
          }
          const left = event.currentTarget.getBoundingClientRect().left;
          void addLibraryItemToTimeline(item, track.id, snapTo(project, track.kind, Math.max(0, ((event.clientX - left) / px) * TIMEBASE)));
        }}
      >
        {clips.map((clip) => (
          <ClipBlock
            key={clip.id}
            clip={clip}
            track={track}
            project={project}
            px={px}
            q={q}
            drag={drag}
            setDrag={setDrag}
            selected={selectedIds.has(clip.id)}
            razor={edit.tool === "razor"}
            snap={edit.snap}
            thumb={media.get(project.assets[clip.asset_id]?.verified?.path ?? "")}
            edges={[
              ...clips.filter((other) => other.id !== clip.id).flatMap((other) => [other.position_ticks, other.position_ticks + other.duration_ticks]),
              ...(project.markers ?? []).map((mark) => mark.at_ticks),
            ]}
          />
        ))}
        {ghosts.map((clip) => (
          <div
            key={clip.id}
            className="clip ghost"
            style={{ left: (clip.position_ticks / TIMEBASE) * px, width: Math.max(10, (clip.duration_ticks / TIMEBASE) * px) }}
            title="Agent 预演候选片段：还没提交，只是给你看一眼效果"
          >
            <span className="ghost-tag">提案</span>
            <span className="clip-label">{project.assets[clip.asset_id]?.label ?? clip.asset_id}</span>
          </div>
        ))}
        {clips.filter((clip) => clip.transition_in).map((clip) => <button key={`transition-${clip.id}`} type="button" className="transition-badge"
          style={{ left: clip.position_ticks / TIMEBASE * px, width: Math.max(24, clip.transition_in!.duration_ticks / TIMEBASE * px) }}
          title={`${transitionLabel(app.caps, clip.transition_in!.kind)} · ${humanDuration(clip.transition_in!.duration_ticks)}，点击编辑`}
          aria-label={`编辑${transitionLabel(app.caps, clip.transition_in!.kind)}转场`}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => { selectClip(clip.id); playhead.pause(); playhead.set(clip.position_ticks + clip.transition_in!.duration_ticks / 2); }}>{transitionLabel(app.caps, clip.transition_in!.kind)}</button>)}
        {dropHint?.trackId === track.id ? (
          <span className="drop-indicator" style={{ left: (dropHint.ticks / TIMEBASE) * px }} title={`放在 ${timecode(dropHint.ticks, project.settings.frame_rate)}`} />
        ) : null}
        {!clips.length && !ghosts.length ? (
          <span className="lane-hint">{track.kind === "video" ? "把左侧素材拖进来 →" : "配乐 / 旁白放这里 →"}</span>
        ) : null}
      </div>
    </div>
  );
}

function ClipBlock({
  clip,
  track,
  project,
  px,
  q,
  drag,
  setDrag,
  selected,
  razor,
  snap,
  thumb,
  edges,
}: {
  clip: Clip;
  track: Track;
  project: Project;
  px: number;
  q: number;
  drag: Drag | null;
  setDrag: (value: Drag | null) => void;
  selected: boolean;
  razor: boolean;
  snap: boolean;
  thumb?: { thumbs: string[]; wave: number[] };
  edges: number[];
}) {
  const app = useApp();
  const asset = project.assets[clip.asset_id];
  const kind = track.kind === "audio" ? "audio" : asset?.kind === "text" ? "text" : asset?.kind === "image" ? "image" : "video";
  const shown = preview(clip, drag, {
    px,
    q,
    snap,
    edges,
    head: playhead.value,
    staticSource: asset?.kind === "image" || asset?.kind === "text",
    maxDuration:
      asset && asset.kind !== "image" && typeof asset.duration_ticks === "number"
        ? Math.floor((asset.duration_ticks - clip.source_in_ticks) * 100 / (clip.speed_percent ?? 100))
        : Number.MAX_SAFE_INTEGER,
  });
  const position = shown?.position_ticks ?? clip.position_ticks;
  const duration = shown?.duration_ticks ?? clip.duration_ticks;
  const width = Math.max(6, (duration / TIMEBASE) * px);

  // 淡角柄：拖这条边离开多远，这一头就淡多久，写回 `Clip.fade` 的那一头。音轨淡的是音量，画面轨淡的是
  // 不透明度；Shift 拖把两者一起淡。上限与检查器那两行同源（`fadeRoom`），所以拖不出一条引擎必定拒绝的淡。
  const box = useRef<HTMLDivElement>(null);
  const [fadeDrag, setFadeDrag] = useState<{ side: FadeSide; raw: number } | null>(null);
  const fadeOptions = fadeProperties(clip, asset);
  const wantedProperty: FadeProperty = track.kind === "audio" ? "gain" : "opacity";
  const primary: FadeProperty = fadeOptions.includes(wantedProperty) ? wantedProperty : fadeOptions[0] ?? "gain";
  const fades = fadeWindows(clip);
  const shownFade = (property: FadeProperty, side: FadeSide) =>
    fadeDrag && fadeDrag.side === side ? fadeDragTicks(clip, property, side, fadeDrag.raw, q) : fades[property][side];
  const canFade =
    selected && !track.locked && !razor && width >= 56 && fadeOptions.length > 0
    && Boolean(app.caps?.features?.clip_fade_envelopes);

  const startFade = (event: React.PointerEvent, side: FadeSide) => {
    if (razor || event.button !== 0 || track.locked || !box.current) return;
    event.stopPropagation();
    event.preventDefault();
    selectClip(clip.id, false, false);
    const both = event.shiftKey;
    const rect = box.current.getBoundingClientRect();
    const edge = side === "in" ? rect.left : rect.right;
    const rawOf = (clientX: number) => (Math.abs(clientX - edge) / px) * TIMEBASE;
    const move = (ev: PointerEvent) => setFadeDrag({ side, raw: rawOf(ev.clientX) });
    const stop = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      setFadeDrag(null);
      if (ev.type === "pointercancel" || Math.abs(ev.clientX - event.clientX) < 2) return;
      // 落库的是一组：被拖的这条 + 一起选中的 + 与它们音画链接的伙伴，各自按自己的长度夹。
      const { ops, skipped } = fadeDragBatch(project, clip.id, side, rawOf(ev.clientX), q, both, selected ? selectionFor(app.selectedClips) : []);
      if (skipped.length) {
        const nameOf = (id: string) => {
          const other = project.clips[id];
          return other?.text?.body ?? project.assets[other?.asset_id ?? ""]?.label ?? id;
        };
        toast("warn", `${skipped.length} 条片段没有被淡`, skipped.map((s) => `${nameOf(s.clipId)}：${s.why}`).join("；"));
      }
      if (ops.length) setFadeWindowsForClips(ops);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  const start = (event: React.PointerEvent, modeIn: DragMode) => {
    if (razor || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    let mode = modeIn;
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      if (mode === "trim-l" && !event.shiftKey) mode = "roll-l";
      else if (mode === "trim-r" && !event.shiftKey) mode = "roll-r";
      else if (mode === "move" && (event.shiftKey || event.ctrlKey || event.metaKey)) { selectClip(clip.id, true, event.altKey); return; }
    }
    const clipIds = mode === "move" && selected && !event.altKey ? selectionFor(app.selectedClips) : selectionFor([clip.id], event.altKey, mode !== "move");
    const clipIdSet = new Set(clipIds);
    if (mode === "move") selectClips(clipIds, true); else selectClip(clip.id, false, event.altKey);
    if (track.locked) return;
    const rows = timelineTracks(project);
    const anchorRow = rows.findIndex((t) => t.id === track.id);
    let roll: Drag["roll"] = null;
    if (mode === "roll-l" || mode === "roll-r") {
      const seamLeft = mode === "roll-l"
        ? Object.values(project.clips).find((c) => c.track_id === track.id && c.id !== clip.id && c.position_ticks < clip.position_ticks && c.position_ticks + c.duration_ticks >= clip.position_ticks)
        : clip;
      const seamRight = mode === "roll-l"
        ? clip
        : Object.values(project.clips).find((c) => c.track_id === track.id && c.id !== clip.id && c.position_ticks > clip.position_ticks && c.position_ticks <= clip.position_ticks + clip.duration_ticks);
      if (!seamLeft || !seamRight) { toast("warn", "滚动剪辑需要接头的两个相邻片段"); return; }
      clipIds.length = 0;
      clipIds.push(seamLeft.id, seamRight.id);
      clipIdSet.clear();
      clipIdSet.add(seamLeft.id);
      clipIdSet.add(seamRight.id);
      roll = {
        leftId: seamLeft.id,
        rightId: seamRight.id,
        left: { position: seamLeft.position_ticks, sourceIn: seamLeft.source_in_ticks, duration: seamLeft.duration_ticks },
        right: { position: seamRight.position_ticks, sourceIn: seamRight.source_in_ticks, duration: seamRight.duration_ticks },
      };
    }
    const origin: Drag = {
      clipId: clip.id,
      mode,
      startX: event.clientX,
      origin: { position: clip.position_ticks, sourceIn: clip.source_in_ticks, duration: clip.duration_ticks },
      x: 0,
      clipIds,
      clipIdSet,
      moveQuantum: selectionQuantum(project, clipIds),
      snapQuantum: q,
      minPosition: Math.min(...clipIds.map((id) => project.clips[id].position_ticks)),
      edges: [
        ...Object.values(project.clips).filter((c) => !clipIdSet.has(c.id)).flatMap((c) => [c.position_ticks, c.position_ticks + c.duration_ticks]),
        ...(project.markers ?? []).map((mark) => mark.at_ticks),
      ],
      rowShift: 0,
      trimSourceHead: Math.min(...clipIds.map((id) => project.clips[id].source_in_ticks)),
      trimMaxDuration: Math.min(...clipIds.map((id) => { const c = project.clips[id]; const a = project.assets[c.asset_id]; return a?.duration_ticks ? Math.floor((a.duration_ticks - c.source_in_ticks) * 100 / (c.speed_percent ?? 100)) : Number.MAX_SAFE_INTEGER; })),
      roll,
    };
    const candidate = (ev: PointerEvent): Drag => {
      const targetId = Array.from(document.querySelectorAll<HTMLElement>('.tl-lane[data-track-id]')).find((e) => { const r = e.getBoundingClientRect(); return ev.clientX >= r.left && ev.clientX < r.right && ev.clientY >= r.top && ev.clientY < r.bottom; })?.dataset.trackId;
      const targetRow = rows.findIndex((t) => t.id === targetId);
      return { ...origin, x: ev.clientX - event.clientX, rowShift: mode === "move" && targetRow >= 0 ? targetRow - anchorRow : 0 };
    };
    setDrag(origin);
    const move = (ev: PointerEvent) => {
      setDrag(candidate(ev));
    };
    const stop = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      const cancelled = ev.type === "pointercancel";
      const delta = ev.clientX - event.clientX;
      setDrag(null);
      if (cancelled || (mode === "move" ? Math.hypot(delta, ev.clientY - event.clientY) : Math.abs(delta)) < 2) return;
      const finalDrag = candidate(ev);
      const final = preview(clip, finalDrag, {
        px,
        q,
        snap,
        edges,
        head: playhead.value,
        staticSource: asset?.kind === "image" || asset?.kind === "text",
        maxDuration:
          asset && asset.kind !== "image" && typeof asset.duration_ticks === "number"
            ? Math.floor((asset.duration_ticks - clip.source_in_ticks) * 100 / (clip.speed_percent ?? 100))
            : Number.MAX_SAFE_INTEGER,
      });
      if (!final) return;
      if (mode === "move") {
        moveSelection(clipIds, final.position_ticks - clip.position_ticks, clip.id, rows[anchorRow + finalDrag.rowShift]?.id ?? track.id);
      } else if (finalDrag.roll) {
        const raw = (delta / px) * TIMEBASE;
        let shift = align(raw, finalDrag.moveQuantum, 0);
        shift = Math.min(shift, finalDrag.roll.right.duration - finalDrag.moveQuantum);
        shift = Math.max(shift, finalDrag.moveQuantum - finalDrag.roll.left.duration);
        if (shift !== 0) rollClip(finalDrag.roll.leftId, finalDrag.roll.rightId, shift);
      } else {
        trimClip(clip.id, final.source_in_ticks, final.duration_ticks, final.position_ticks, event.altKey, event.shiftKey);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  return (
    <div
      ref={box}
      className={`clip ${kind}${selected ? " selected" : ""}${shown ? " dragging" : ""}${fadeDrag ? " fading" : ""}`}
      style={{ left: (position / TIMEBASE) * px, width, transform: shown && drag?.mode === "move" ? `translateY(${drag.rowShift * ROW}px)` : undefined }}
      data-id={clip.id}
      role="button"
      tabIndex={0}
      aria-label={`选择片段 ${clip.text?.body ?? asset?.label ?? clip.asset_id}`}
      aria-pressed={selected}
      onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); event.stopPropagation(); selectClip(clip.id, event.ctrlKey || event.metaKey || event.shiftKey, event.altKey); } }}
      title={`${asset?.label ?? clip.asset_id}\n时长 ${humanDuration(duration)}\n位置 ${position.toLocaleString("en-US")} tick`}
      onPointerDown={(event) => start(event, "move")}
      onDoubleClick={() => { if (asset?.sequence_id && !razor) openSequence(asset.sequence_id); }}
      onClick={(event) => {
        if (track.locked || event.ctrlKey || event.metaKey || event.shiftKey) return;
        if (!razor) return;
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
        splitClip(clip.id, clip.position_ticks + ((event.clientX - rect.left) / rect.width) * clip.duration_ticks, event.altKey);
      }}
    >
      <span className="strip" />
      {kind === "video" && thumb?.thumbs.length ? (
        <span className="filmstrip">
          {thumb.thumbs.slice(0, Math.max(1, Math.floor(width / 28))).map((url, index) => (
            <img key={index} src={url} alt="" draggable={false} loading="lazy" />
          ))}
        </span>
      ) : null}
      {kind === "audio" && thumb?.wave.length ? <WaveBars values={thumb.wave} width={width} /> : null}
      <span className="clip-label">{clip.text?.body ?? asset?.label ?? clip.asset_id}</span>
      {clip.group_id || clip.link_id ? <span className="clip-association" title={`${clip.group_id ? "持久组合" : ""}${clip.link_id ? " · 音画链接" : ""}`}>{clip.group_id ? "▣" : ""}{clip.link_id ? "↔" : ""}</span> : null}
      <span className="clip-dur mono">{(duration / TIMEBASE).toFixed(2)}s</span>
      {asset?.sequence_id ? <span className="ghost-tag" title="双击进入合成编辑内部图层">合成</span> : asset && !asset.verified && asset.kind !== "text" ? <span className="ghost-tag unverified" title="只有元数据、没有真实文件，无法预览和导出">未导入</span> : null}
      {(clip.keyframes ?? []).filter((k) => k.at_ticks >= (clip.animation_offset_ticks ?? 0) && k.at_ticks <= (clip.animation_offset_ticks ?? 0) + clip.duration_ticks).map((k) => <button
        key={`${k.property}-${k.at_ticks}`} type="button" className="clip-keyframe"
        style={{ left: Math.min(width - 6, Math.max(6, ((k.at_ticks - (clip.animation_offset_ticks ?? 0)) / clip.duration_ticks) * width)) }}
        title={`${k.property} · ${humanDuration(k.at_ticks - (clip.animation_offset_ticks ?? 0))}`}
        aria-label={`跳到${k.property}关键帧`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => { event.stopPropagation(); selectClip(clip.id); playhead.pause(); playhead.set(clip.position_ticks + k.at_ticks - (clip.animation_offset_ticks ?? 0)); }}>◆</button>)}
      {(["opacity", "gain"] as FadeProperty[]).flatMap((property) => (["in", "out"] as FadeSide[]).map((side) => {
        const length = shownFade(property, side);
        if (!length) return null;
        return <span key={`${property}-${side}`} className={`fade-wedge ${property} ${side}`} style={{ width: Math.max(2, Math.min(width - 2, (length / TIMEBASE) * px)) }} aria-hidden="true" />;
      }))}
      {fadeDrag ? <span className="fade-readout mono">{(shownFade(primary, fadeDrag.side) / TIMEBASE).toFixed(2)}s</span> : null}
      {canFade ? (["in", "out"] as FadeSide[]).map((side) => <span
        key={side}
        className={`fade-handle ${side}`}
        role="button"
        tabIndex={-1}
        aria-label={`拖动${side === "in" ? "淡入" : "淡出"}角柄`}
        title={`拖着角柄走：这段${primary === "gain" ? "音量" : "画面"}淡${side === "in" ? "入" : "出"}多久，拖回边上取消（现在 ${(fades[primary][side] / TIMEBASE).toFixed(2)} 秒）。${fadeOptions.length > 1 ? "Shift 拖同时淡画面与音量。" : ""}修剪请拖最外面的边。`}
        onPointerDown={(event) => startFade(event, side)}
      />) : null}
      <span className="trim-handle left" title="拖动改变源入点（从素材的哪一秒开始）；Shift 涟漪修剪，Ctrl 滚动剪辑" onPointerDown={(event) => start(event, "trim-l")} />
      <span className="trim-handle right" title="拖动改变时长；Shift 涟漪修剪，Ctrl 滚动剪辑" onPointerDown={(event) => start(event, "trim-r")} />
    </div>
  );
}

function WaveBars({ values, width }: { values: number[]; width: number }) {
  const count = Math.max(4, Math.floor(width / 3));
  const peak = Math.max(0.0001, ...values);
  const step = values.length / count;
  const bars: JSX.Element[] = [];
  for (let i = 0; i < count; i += 1) {
    const index = Math.min(values.length - 1, Math.floor(i * step));
    const h = 6 + (values[index] / peak) * 84;
    bars.push(<rect key={i} x={i * 3} y={50 - h / 2} width={1.7} height={h} rx={0.8} />);
  }
  return (
    <svg className="wave" viewBox={`0 0 ${count * 3} 100`} preserveAspectRatio="none" aria-hidden="true">
      <g fill="rgba(67,162,115,.55)">{bars}</g>
    </svg>
  );
}

/** 标记的名字与颜色：一次点击 = 一条 marker.set，和 Agent 用的是同一个命令。 */
/** 标尺上的入出点区间：一条带子加两个可拖的手柄，落点走整帧量化。 */
function RangeHandles({ project, px }: { project: Project; px: number }) {
  const [draft, setDraft] = useState<{ side: "in" | "out"; ticks: number } | null>(null);
  const from = project.settings.in_ticks;
  const to = project.settings.out_ticks;
  if (from == null || to == null) return null;
  const mq = quantum(project, "video");
  const shown = {
    in: draft?.side === "in" ? draft.ticks : from,
    out: draft?.side === "out" ? draft.ticks : to,
  };
  const commit = (side: "in" | "out", ticks: number) => {
    setDraft(null);
    void setSequenceMark(side, ticks);
  };
  return <>
    <span
      className="ruler-range"
      style={{ left: (shown.in / TIMEBASE) * px, width: Math.max(0, ((shown.out - shown.in) / TIMEBASE) * px) }}
      title={`导出区间 ${(shown.in / TIMEBASE).toFixed(2)} – ${(shown.out / TIMEBASE).toFixed(2)} 秒`}
      aria-hidden="true"
    />
    {(["in", "out"] as const).map((side) => <span
      key={side}
      role="slider"
      tabIndex={0}
      aria-label={side === "in" ? "入点" : "出点"}
      aria-valuenow={shown[side]}
      className={`ruler-range-handle ${side}${draft?.side === side ? " dragging" : ""}`}
      style={{ left: (shown[side] / TIMEBASE) * px }}
      title={`${side === "in" ? "入点" : "出点"} ${(shown[side] / TIMEBASE).toFixed(2)} 秒 · 左右拖动改区间（整帧），方向键微调，Alt+X 清除`}
      onPointerDown={(event) => {
        event.stopPropagation();
        if (event.button !== 0) return;
        const ruler = event.currentTarget.parentElement as HTMLElement;
        const startX = event.clientX;
        let moved = false;
        const at = (clientX: number) => Math.max(0, align(((clientX - ruler.getBoundingClientRect().left) / px) * TIMEBASE, mq, 0));
        const move = (ev: PointerEvent) => {
          if (Math.abs(ev.clientX - startX) > 2) moved = true;
          setDraft({ side, ticks: at(ev.clientX) });
        };
        const stop = (ev: PointerEvent) => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", stop);
          window.removeEventListener("pointercancel", stop);
          if (moved) commit(side, at(ev.clientX));
          else setDraft(null);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
        window.addEventListener("pointercancel", stop);
      }}
      onKeyDown={(event) => {
        const step = (event.shiftKey ? 10 : 1) * frameTicks(project.settings.frame_rate);
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          commit(side, shown[side] + (event.key === "ArrowRight" ? step : -step));
        } else if (event.key === "Escape") {
          setDraft(null);
        }
      }}
    />)}
  </>;
}

function MarkerEditor({ mark, onDone }: { mark: Marker; onDone: () => void }) {
  const [name, setName] = useState(mark.name);
  const colours: NonNullable<Marker["color"]>[] = ["amber", "cyan", "green", "red", "violet"];
  const commit = () => { setMarker(mark, { name }); onDone(); };
  return <span className="marker-edit" onPointerDown={(event) => event.stopPropagation()}>
    <input
      className="input"
      aria-label="标记名称"
      value={name}
      maxLength={64}
      autoFocus
      onChange={(event) => setName(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") { event.preventDefault(); commit(); }
        if (event.key === "Escape") { event.preventDefault(); onDone(); }
      }}
    />
    {colours.map((colour) => <button
      key={colour}
      type="button"
      className={`marker-swatch ${colour}${mark.color === colour ? " active" : ""}`}
      aria-label={`标记颜色 ${colour}`}
      title={colour}
      onClick={() => { setMarker(mark, { color: colour }); onDone(); }}
    />)}
    <button type="button" className="btn tiny" onClick={commit}>好</button>
    <button type="button" className="btn tiny" onClick={onDone}>取消</button>
  </span>;
}
