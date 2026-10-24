import { useEffect, useMemo, useRef, useState } from "react";

import { Icon, IconBtn } from "../ui";
import { TIMEBASE, align, frameTicks, humanDuration, timecode } from "../time";
import { countHidden, firstView, laneTicks, paintClips, rulerSeconds, unionRange, WINDOW_NOTE, type TickRange, type View } from "../timelineWindow";
import { transitionLabel } from "../engine";
import type { Clip, Keyframe, Marker, Project, Track } from "../engine";
import { planKeyframeDrag, planLayerNeedleDrag, planLayerNeedleRemoval, planNeedleRemoval } from "../keyframeDrag";
import { BOX_KEY_HIT_PIXELS, planBoxKeyDrag } from "../boxKeyDrag";
import {
  CHIP_KEEP_PIXELS,
  LANE_CLIP_PAD_PIXELS,
  LANE_PITCH_PIXELS,
  NEEDLE_AREA_PIXELS,
  NEEDLE_BOTTOM_PIXELS,
  NEEDLE_HALF_PIXELS,
  SEAM_BADGE_BOTTOM_PIXELS,
  SEAM_BADGE_HEIGHT_PIXELS,
  SEAM_BADGE_MIN_WIDTH_PIXELS,
  laneCapacity,
  needleId,
  needleRows,
  underSeamBadge,
} from "../keyframeLanes";
import { MARQUEE_INSET_PIXELS, type PixelBox, commitPick, draggedEnough, hitsInBand, marqueeBox, togglePick } from "../keyframeMarquee";
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
  editAtRevision,
  setGraphOpen,
  usePlay,
  selectClips,
  copySelection,
  pasteSelection,
  attributeSourceCopy,
  copyAttributes,
  removeSelection,
  moveSelection,
  splitSelection,
  selectionFor,
  duplicateSelection,
  groupSelection,
  linkSelection,
  detachAudio,
  selectAllClips,
  rollClip,
  openSequence,
  cutTrackSilence,
  roughCutTrack,
  duckTrack,
  alignTrackLoudness,
  addMarker,
  removeMarker,
  setMarker,
  splitAtMarkers,
  setFadeWindowsForClips,
  setClipMaskStack,
  keymap,
  ZOOM_MAX,
  ZOOM_MIN,
} from "../store";
import { chordWords, commandLabel } from "../keymap";
import { openContextMenu, type MenuEntry } from "../ContextMenu";
import { canDetachAudio, canLinkClips } from "../clipRules";
import { copyBlocker, pasteBlocker, pasteTargets } from "../attributePaste";
import { AttributeDialog } from "./AttributeDialog";
import { FIELD_LABEL, LAYER_KEY_LABEL, PROPERTY_RANK, layerNeedles, trackToolBlocker, fadeDragBatch, fadeDragTicks, fadeProperties, fadeWindows, type FadeProperty, type FadeSide, type LayerNeedle } from "../effects";
import { selectionQuantum, timelineTracks } from "../selection";

const HEAD = 112;
// 1.228：56 → 68。卡片里那两件事要各占一条带：上面一行说「这一段是什么」（名字与时长），
// 下面 37px 是针道。46px 高的卡片放不下两条带——三道针排满时最上面那道就压进名字那一行
// （扫描量到的 `clip-keyframe|clip-label`）。让步的是行高，不是针道也不是字号。
const ROW = 68;
/** 卡片窄过这个宽度就不画时长那一格（名字比数字要紧）。12.5px 的字、`12.34s` 六格约 46px，
 *  再给名字留出三四个字的余量——这是判断，不是量出来的边界。 */
const CLIP_DURATION_MIN_PIXELS = 96;

type DragMode = "move" | "trim-l" | "trim-r" | "roll-l" | "roll-r";

/**
 * 拖动中那几枚针的落点（刻度都是**片段本地**，与 `planKeyframeDrag` 交出去的同一口径）。
 * `targets` 只装真的在走的那几枚：按住 Alt 复制时原针一格也不动，就不许看起来在动（1.114 定的那条），
 * 而 `blocked` 时只有被抓的那一枚被画到它想去却去不了的那一格上。
 */
type NeedleHeld = { anchor: string; at: number; blocked: boolean; duplicate: boolean; layer: boolean; targets: { id: string; from: number; at: number }[] };
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
  // 1.163「粘贴属性」：对话框只在人点开时存在，回执里的数每次改勾都重新问一次引擎。
  const [attributeOpen, setAttributeOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // 1.131：卡片只建窗口里的那些。view 是这条横向滚动的当前视口，marqueeSpan 是框选正在拖的那一段
  // 时间跨度——被框住的每一条都必须存在，旧的按 DOM 矩形判定命中的逻辑才一个字都不用改。
  // 1.133：初值不是 null 而是「当作看见 FIRST_PAINT_PIXELS 宽」。effect 要等第一次提交以后才量得到，
  // 所以 null 那一帧就是首帧——两万段那份工程把它读成「不裁」，于是两万张卡片在首帧建完。
  const [view, setView] = useState<View>(firstView);
  const [marqueeSpan, setMarqueeSpan] = useState<TickRange | null>(null);
  // 1.230：还有几条轨落在折线以下。卡片加高到 68px 之后，四条轨在默认高度里放不下，
  // 而滚动条是覆盖式的——不说一声，人只会以为那条音轨没了（演示里就是这么被量到的）。
  const [below, setBelow] = useState(0);
  const [above, setAbove] = useState(0);
  useEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    const measure = () => {
      setView({ left: scroll.scrollLeft, width: scroll.clientWidth });
      const box = scroll.getBoundingClientRect();
      let lower = 0;
      let upper = 0;
      scroll.querySelectorAll<HTMLElement>(".tl-row:not(.ruler-row)").forEach((row) => {
        const rect = row.getBoundingClientRect();
        if (rect.bottom > box.bottom + 1) lower += 1;
        if (rect.top < box.top - 1) upper += 1;
      });
      setBelow(lower);
      setAbove(upper);
    };
    measure();
    scroll.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    return () => {
      scroll.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
    };
  }, [project?.id, project?.tracks.length]);

  // 1.194：窗口矮下去时让步的是这条时间线（`.editor .timeline` 那条 clamp），可夹到下限以后
  // 往上拖那条边就不再起作用——这句得说出来，不然用户以为拖坏了。要的那一个数读的是同一个
  // CSS 变量（`--timeline-height`，自定义属性会继承下来），量到的是真的盒子；这里不出现 180
  // 那个下限，也不写第二条 `calc(100dvh …)`——抄一份就成了第二条公式，改一处会漏一处。
  const rootRef = useRef<HTMLElement | null>(null);
  const [room, setRoom] = useState<{ wanted: number; got: number } | null>(null);
  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const measure = () => {
      const wanted = Number(getComputedStyle(node).getPropertyValue("--timeline-height").replace("px", "").trim());
      const got = node.getBoundingClientRect().height;
      setRoom(Number.isFinite(wanted) && got > 0 ? { wanted, got } : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [project?.id, app.monitorMode]);
  // 只有**有人真要过**那个数，这一句才是对用户说的：应用自己那一档默认数装不下时，
  // 该让位的是布局，不是让用户听一句解释（1.225 在最小窗里量到的就是这一条）。
  const clamped = room && room.wanted - room.got > 1 && app.splitterTouched ? room : null;

  // 1.230：选中哪一段，就把它所在的那一行带进视野。横向一个像素都不许变——横向是「看时间」
  // 的那一维，为了露出整行而滚到别处，会把播放头那一格甩出屏幕（所以先记下、滚完放回去）。
  useEffect(() => {
    const scroll = scrollRef.current;
    const clip = project && app.selectedClips.length ? project.clips[app.selectedClips[0]] : null;
    if (!scroll || !clip) return;
    const row = project!.tracks.findIndex((track) => track.id === clip.track_id);
    const target = row < 0 ? undefined : scroll.querySelectorAll<HTMLElement>(".tl-row:not(.ruler-row)")[row];
    if (!target) return;
    const left = scroll.scrollLeft;
    target.scrollIntoView({ block: "nearest", inline: "nearest" });
    scroll.scrollLeft = left;
  }, [app.selectedClips, project?.id]);

  // 加了一条轨就把它露出来：人点了「＋ 画面轨」却没看见新行，只会再点一次。
  const trackCount = useRef(project?.tracks.length ?? 0);
  useEffect(() => {
    const count = project?.tracks.length ?? 0;
    const scroll = scrollRef.current;
    if (scroll && count > trackCount.current) {
      const rows = scroll.querySelectorAll<HTMLElement>(".tl-row:not(.ruler-row)");
      const left = scroll.scrollLeft;
      rows[rows.length - 1]?.scrollIntoView({ block: "nearest", inline: "nearest" });
      scroll.scrollLeft = left;
    }
    trackCount.current = count;
  }, [project?.tracks.length]);


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
  // 窗口 = 当前视口（两边各多涂两秒）∪ 正在拖的那一框。首帧也有界：见上面 `useState(firstView)` 那句。
  const paintRange = unionRange(laneTicks(view, px, HEAD, contentTicks), marqueeSpan);
  const outside = countHidden(Object.values(project.clips), paintRange, new Set(app.selectedClips));
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

  const attributeSource = attributeSourceCopy();
  const attributeTargets = attributeSource ? pasteTargets(attributeSource.clipId, app.selectedClips) : [];
  const attributeStop = copyBlocker(project, app.selectedClips, app.caps?.features);
  const attributePasteStop = pasteBlocker(attributeSource, project, attributeTargets, app.caps?.features);
  const attributeSourceClip = attributeSource ? project?.clips[attributeSource.clipId] : undefined;
  const attributeSourceLabel = attributeSourceClip
    ? project?.assets[attributeSourceClip.asset_id]?.label || attributeSourceClip.id
    : "";

  return (
    <section ref={rootRef} className="timeline" aria-label="时间线">
      {clamped ? <p className="timeline-clamped" role="status">窗口太矮：这条时间线已经让到这一屏的下限（你要 <b className="mono">{Math.round(clamped.wanted)} px</b>，现在只剩 <b className="mono">{Math.round(clamped.got)} px</b>），往上拖那条边不会再变高——把窗口拉高，或退出「素材预览」那一屏（它比常态多占一截画面的高度）。</p> : null}
      <div className="tl-toolbar">
        <span className="tool-well" role="group" aria-label="工具">
          <IconBtn icon="cursor" label={`选择工具（${chordWords(keymap()["tool-select"])}）：拖动片段改位置，拖左右边缘改时长`} active={edit.tool === "select"} onClick={() => prefs.setTool("select")} />
          <IconBtn icon="razor" label={`分割工具（${chordWords(keymap()["tool-razor"])}）：点片段即在点击处切一刀，切成两段可独立删除`} active={edit.tool === "razor"} onClick={() => prefs.setTool("razor")} />
        </span>
        <span className="tool-well" role="group" aria-label="剪辑">
          <button className="btn tiny subtle" disabled={!canSplit} title={`在播放头处分割选中片段（${chordWords(keymap().split)}）`} onClick={() => splitSelection(playhead.value)}>分割</button>
          <IconBtn icon="copy" label={`复制选中片段（${chordWords(keymap().copy)}）`} disabled={!app.selectedClip} onClick={copySelection} />
          <button className="btn tiny subtle" disabled={!app.clipboardCount} onClick={pasteSelection} title={`粘贴到播放头（${chordWords(keymap().paste)}）`}>粘贴</button>
          <button
            className="btn tiny subtle"
            disabled={Boolean(attributeStop)}
            title={attributeStop ?? "把这一段当前的调色链、效果与变换、关键帧、遮罩、淡、变速、文字样式记下来，再粘到别的段上（达芬奇 / 剪映那句「粘贴属性」）"}
            onClick={copyAttributes}
          >
            复制属性
          </button>
          <button
            className="btn tiny subtle"
            disabled={Boolean(attributePasteStop)}
            title={attributePasteStop ?? `把记下的那几类粘到选中的 ${attributeTargets.length} 段上（来源自己不算目标）`}
            onClick={() => setAttributeOpen(true)}
          >
            粘贴属性
          </button>
          <IconBtn icon="trash" label={`删除选中片段，保留空隙（${chordWords(keymap()["delete-selection"])}）`} disabled={!app.selectedClip} onClick={() => removeSelection()} />
          <button className="btn tiny subtle" disabled={!app.selectedClip} title={`删除并向左补齐本轨后续片段（${chordWords(keymap()["ripple-delete"])}）`} onClick={() => removeSelection(true)}>涟漪删除</button>
        </span>
        {app.selectedClips.length > 1 ? <span className="tag accent">{app.selectedClips.length} 段</span> : null}
        <span className="tool-well" role="group" aria-label="吸附与标记">
          <IconBtn icon="magnet" label={`磁吸（${chordWords(keymap()["toggle-snap"])}）：拖动时自动贴到整帧、相邻片段边缘与标记，避免留下 1 帧缝`} active={edit.snap} onClick={() => prefs.toggleSnap()} />
          <IconBtn icon="flag" label="在指针处打一个标记（M）：人和 Agent 用同一个整数刻度说「这里」，标记还会成为磁吸边缘" onClick={() => addMarker()} />
          <IconBtn icon="razor" label="在每个标记处切开落在它里面的片段：一次事务、一次撤销；落在边缘或空隙上的标记不产生切点" disabled={!(app.project?.markers ?? []).length} onClick={() => void splitAtMarkers()} />
          <button className={`btn tiny subtle${edit.linkedSelection ? " active" : ""}`} aria-pressed={edit.linkedSelection} title="联动选择：组合与链接一起选中；音画链接一起修剪、分割。Alt 点选可临时单选。" onClick={() => prefs.toggleLinkedSelection()}>联动</button>
        </span>
        <span className="tool-well" role="group" aria-label="历史与视图">
          <IconBtn icon="undo" label="撤销：用历史恢复回到上一步（版本号继续增加，不会倒退）" disabled={!app.undo.length} onClick={undo} />
          <IconBtn icon="redo" label={`重做：回到撤销前的那一版（${chordWords(keymap().redo)}）`} disabled={!app.redo.length} onClick={redoStep} />
          <IconBtn
            icon="zoomIn"
            label="适应窗口：把整条时间线放进可视范围"
            onClick={() => prefs.fitTo(timelineEnd(project), (scrollRef.current?.clientWidth ?? 1200) - HEAD)}
          />
        </span>
        <span className="tool-well" role="group" aria-label="加轨道">
          <button className="btn subtle" title="再加一层画面：叠标题、画中画需要第二条画面轨" onClick={() => addTrack("video")}>
            <Icon name="plus" size={12} /> 画面轨
          </button>
          <button className="btn subtle" title="再加一条声音轨：配乐与旁白分开控制音量" onClick={() => addTrack("audio")}>
            <Icon name="plus" size={12} /> 声音轨
          </button>
        </span>
        <span className="spacer" />
        {app.mode === "batch" ? (
          <span className="tag accent" title="动作先进待提交批次，预演通过再写入">批次模式</span>
        ) : (
          <span className="tag off" title="每个动作立刻写成一条命令批次并提交">即时模式</span>
        )}
        <span className="zoom-ctrl">
          <IconBtn icon="zoomOut" label={`缩小（${chordWords(keymap()["zoom-out"])}）`} onClick={() => prefs.zoomBy(0.8)} />
          <input type="range" min={ZOOM_MIN} max={ZOOM_MAX} value={px} aria-label="时间线缩放" onChange={(event) => prefs.setZoom(Number(event.target.value))} />
          <IconBtn icon="zoomIn" label={`放大（${chordWords(keymap()["zoom-in"])}）`} onClick={() => prefs.zoomBy(1.25)} />
        </span>
      </div>
        {outside ? <span className="tl-window-note" role="status">{WINDOW_NOTE(outside)}</span> : null}
        {above ? <button type="button" className="tl-window-note tl-more-tracks" title="上面还有几条轨在折线以外：点一下滚回最上面那条（滚动条也能拖）。选中任意片段时，它所在的那一行会自动滚进来" onClick={() => scrollRef.current?.scrollTo({ top: 0 })}>上面还有 {above} 条轨</button> : null}
        {below ? <button type="button" className="tl-window-note tl-more-tracks" title="这条时间线比这几条轨矮：点一下滚到最下面那条（滚动条也能拖）。选中任意片段时，它所在的那一行会自动滚进来" onClick={() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })}>下面还有 {below} 条轨</button> : null}
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
            setMarqueeSpan({
              from: Math.max(0, ((left - bounds.left - HEAD) * TIMEBASE) / px),
              to: Math.max(0, ((right - bounds.left - HEAD) * TIMEBASE) / px),
            });
            const ids = Array.from(inner.querySelectorAll<HTMLElement>('.clip[data-id]')).filter((e) => { const r = e.getBoundingClientRect(); return r.left < right && r.right > left && r.top < bottom && r.bottom > top; }).map((e) => e.dataset.id!);
            selectClips([...base, ...ids]);
          };
          const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop); setMarquee(null); setMarqueeSpan(null); };
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
              {rulerMarks(contentTicks, px, project, paintRange, play.ticks)}
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
              paint={paintRange}
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
      {attributeOpen ? <AttributeDialog targets={attributeTargets} sourceLabel={attributeSourceLabel} onClose={() => setAttributeOpen(false)} /> : null}
    </section>
  );

  function seek(offsetPx: number) {
    playhead.pause();
    const value = (offsetPx / px) * TIMEBASE;
    playhead.set(Math.max(0, Math.min(snapTo(project!, "video", value), contentTicks)));
  }
}

function rulerMarks(total: number, px: number, project: Project, window: TickRange, playTicks: number) {
  const secondsTotal = total / TIMEBASE;
  const overHour = secondsTotal >= 3600;
  const items: JSX.Element[] = [];
  // 1.131：尺子也只数窗口里的那些——两万秒的刻度以前和卡片一样全建，那是同一个毛病的第二处。
  // 1.133：窗口是必填的。这里原来还留着一份「没有窗口就从 0 数到结尾」的分支，连带抄了第二张
  // 间隔表；间隔的唯一主人是 `timelineWindow.rulerStep`，那条分支一删，这张表也就没人重抄了。
  const marks = rulerSeconds(window, total, px);
  // 播放头那颗时间泡压在刻度读数上（1.228 量到的第一处字压字：`00:00` 被
  // `00:00:00:00` 盖掉 26.6×14px）。让位的应该是刻度——泡里写的是同一件事，而且更精确。
  // 宽度按等宽字 0.6em 估（12.5px → 7.6px/字）再各留 4px 余量；估准没有不由这里说了算，
  // 扫描那一档量的是**墨**（Range 矩形），叠着没让开就会红。
  const mono = 7.6;
  const bubbleLeft = (playTicks / TIMEBASE) * px + 7 - 4;
  const bubbleRight = bubbleLeft + 11 * mono + 12 + 8;
  for (const s of marks) {
    const x = s * px;
    items.push(<span key={`m${s}`} className="ruler-tick big" style={{ left: x }} />);
    // 超过 1 小时后保留时位，否则 01:00:00 会和 00:00 显示成一样
    const label = overHour
      ? timecode(s * TIMEBASE, project.settings.frame_rate, false)
      : timecode(s * TIMEBASE, project.settings.frame_rate, false).slice(3);
    const labelLeft = x + 3;
    if (labelLeft + label.length * mono > bubbleLeft && labelLeft < bubbleRight) continue;
    items.push(
      <span key={`l${s}`} className="ruler-label mono" style={{ left: labelLeft }}>
        {label}
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
  paint,
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
  paint: TickRange;
}) {
  const app = useApp();
  const edit = useEdit();
  const clips = Object.values(project.clips).filter((item) => item.track_id === track.id);
  const emptyTrack = trackToolBlocker(track.id, clips);
  const selectedIds = useMemo(() => new Set(app.selectedClips), [app.selectedClips]);
  // 挑中的段即便在窗口外也照旧画出来：一整组被挑着横向拖是既有手感，裁切不许把它裁掉。
  const q = quantum(project, track.kind);
  const painted = paintClips(clips, paint, selectedIds).shown;

  /** 1.278：空白处右键——粘贴、全选、标记、按标记切开。每一项都调工具条那颗按钮在调的那个函数，
   *  键位提示读 `keymap()`（改键之后这里跟着改），不另写一份键名。 */
  const laneMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const keys = keymap();
    openContextMenu({
      at: { x: event.clientX, y: event.clientY },
      title: `${track.name} · 空白处`,
      label: "时间线空白处操作",
      returnTo: event.currentTarget,
      entries: [
        { kind: "item", label: commandLabel("paste"), icon: "copy", hint: chordWords(keys.paste), disabled: !app.clipboardCount, run: pasteSelection },
        { kind: "item", label: commandLabel("select-all"), hint: chordWords(keys["select-all"]), run: selectAllClips },
        { kind: "sep", id: "marks" },
        { kind: "item", label: commandLabel("marker"), icon: "flag", hint: chordWords(keys.marker), title: "在播放头写一个普通标记；人与 Agent 用同一个整数刻度", run: () => addMarker() },
        { kind: "item", label: "在每个标记处切开", icon: "razor", disabled: !(project.markers ?? []).length, title: "落在片段内部的标记才切；落在边缘或空隙上的不算", run: () => void splitAtMarkers() },
      ],
    });
  };

  /** 1.279：轨道头原先挤着七颗 20px 图标（112px 的格里放不下），现在只留三颗：
   *  锁定、显隐/静音、更多。分析类动作（统一响度、去空白、自动闪避）与删除收进这一份菜单——
   *  仍是同一个 store 函数、同一个 ContextMenu，不为「更多」再造一套弹层。 */
  const trackMenu = (anchor: HTMLButtonElement) => {
    const rect = anchor.getBoundingClientRect();
    const entries: MenuEntry[] = [
      {
        kind: "item", label: "统一这一轨的响度", icon: "volume", disabled: !!emptyTrack,
        title: emptyTrack ?? "逐片段测量这条轨的响度，一次写入各自的增益把它们统一到 -16 LUFS（只改音量倍数，不加压缩器）",
        run: () => alignTrackLoudness(track.id),
      },
      {
        kind: "item", label: "剪掉这一轨的停顿", icon: "razor", disabled: !!emptyTrack,
        title: emptyTrack ?? "剪掉这条轨上所有 0.25 秒以上的停顿并把后面的内容左移：只影响本轨，其它轨保持原位",
        run: () => cutTrackSilence(track.id),
      },
    ];
    if (track.kind === "video" && app.caps?.features?.rough_cut) {
      // 粗剪是画面上的事：声音轨不摆这一项，空轨时与另外三项一样灰掉并交回同一句原因。
      entries.unshift({
        kind: "item", label: "按镜头粗剪这一轨", icon: "razor", disabled: !!emptyTrack,
        title: emptyTrack ?? "这条轨上每一段画面都只留每个镜头的前 1.5 秒（默认值来自能力表），把留下的头接起来：一次提交一个版本、只动本轨；单段的秒数在检查器里改",
        run: () => roughCutTrack(track.id),
      });
    }
    if (track.kind === "audio") {
      // 独奏只摆在声音轨上：画面轨没有这一颗（它的内嵌声音在别人独奏时一律让路）。
      entries.unshift(
        {
          kind: "item", label: track.solo ? "取消独奏" : "独奏（其它声音让路）", icon: "volume",
          title: "有任意一条声音轨独奏时，其余声音（含画面轨的内嵌声音）都让路；被静音的轨即使独奏也不出声。整轨音量与 M/S 也在检查器的「混音台」里",
          run: () => updateTrack(track.id, { solo: !track.solo }, track.solo ? "取消独奏" : "独奏这条轨"),
        },
        { kind: "sep", id: "solo" },
      );
      entries.push({
        kind: "item", label: "自动闪避（给说话让路）", icon: "volume", disabled: !!emptyTrack,
        title: emptyTrack ?? "这条轨按 9 dB 让路，写成音量关键帧（说话结束后 0.6 秒抬回来），只改本轨",
        run: () => duckTrack(track.id),
      });
    }
    entries.push(
      { kind: "sep", id: "delete" },
      { kind: "item", label: "删除这条轨道", icon: "trash", danger: true, title: "必须先清空它上面的片段", run: () => removeTrack(track.id) },
    );
    openContextMenu({
      at: { x: rect.left, y: rect.bottom + 4 },
      title: `${track.name} · 轨道操作`,
      label: "轨道操作",
      returnTo: anchor,
      entries,
    });
  };

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
          <button
            type="button"
            className="icon-btn tiny"
            aria-label="这条轨的其它操作"
            title="这条轨的其它操作：统一响度、剪掉停顿、自动闪避、删除轨道"
            onClick={(event) => trackMenu(event.currentTarget)}
          >
            <Icon name="more" size={12} />
          </button>
        </div>
      </div>
      <div
        className={`tl-lane${track.kind === "audio" ? " audio-track" : ""}`}
        data-track-id={track.id}
        style={{ width }}
        onContextMenu={laneMenu}
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
        {painted.map((clip) => (
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
            <div className="clip-top"><span className="clip-label">{project.assets[clip.asset_id]?.label ?? clip.asset_id}</span><span className="ghost-tag">提案</span></div>
          </div>
        ))}
        {painted.filter((clip) => clip.transition_in).map((clip) => <button key={`transition-${clip.id}`} type="button" className="transition-badge"
          style={{
            left: clip.position_ticks / TIMEBASE * px,
            width: Math.max(SEAM_BADGE_MIN_WIDTH_PIXELS, clip.transition_in!.duration_ticks / TIMEBASE * px),
            bottom: SEAM_BADGE_BOTTOM_PIXELS + LANE_CLIP_PAD_PIXELS,
            height: SEAM_BADGE_HEIGHT_PIXELS,
          }}
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

  // 时间线上直接拖针：几何与动画曲线共用同一份 keyframeSnap（绝对帧格子 + 像素容差 + 找播放头/找邻居），
  // 落库的仍是一条普通 `keyframe.move`（挑中一组则是 `keyframes.move`，一次抓取仍只有一条命令、一个 revision）。
  // 移动不到两像素就还是原来的「点一下跳过去」，所以不新增快捷键、也不新增命令；撞针在这里提前认出来
  // （reducer 的 KEYFRAME_COLLISION 是同一条判断的权威说法）。
  const [keyDrag, setKeyDrag] = useState<NeedleHeld | null>(null);
  const [boxKeyDrag, setBoxKeyDrag] = useState<{ block: number; index: number; at: number; blocked: string | null } | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [band, setBand] = useState<PixelBox | null>(null);

  /** 屏幕上真画出来的那几枚针的矩形——框选挑中的必须是点得到的，画不下的那几属性压根不在这里。 */
  const paintedBoxes = (): { id: string; box: PixelBox }[] => Array.from(
    box.current?.querySelectorAll<HTMLElement>(".clip-keyframe:not(.ghost):not(.layer-needle)") ?? [],
  ).flatMap((node) => {
    const id = node.dataset.keyId;
    if (!id) return [];
    const rect = node.getBoundingClientRect();
    return [{ id, box: { x0: rect.left, y0: rect.top, x1: rect.right, y1: rect.bottom } }];
  });

  const startMarquee = (event: React.PointerEvent) => {
    if (razor || event.button !== 0 || track.locked || !box.current || !app.caps?.features?.keyframes) return;
    event.stopPropagation();
    const node = box.current;
    const origin = { x: event.clientX, y: event.clientY };
    const base = picked;
    const additive = event.shiftKey;
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      setBand(null);
    };
    const move = (ev: PointerEvent) => {
      const area = marqueeBox(origin, { x: ev.clientX, y: ev.clientY });
      const rect = node.getBoundingClientRect();
      // 每次都重新量屏幕：Agent 与人共用这条时间线，框拖到一半时工程可以被另一边改写（实测就是这么发现的），
      // 按下那一刻的快照会挑中一枚已经不存在的针。看得见什么就挑中什么，不允许拿着幻影去拖。
      setPicked(commitPick(base, hitsInBand(paintedBoxes(), area), additive));
      setBand({ x0: area.x0 - rect.left, y0: area.y0 - rect.top, x1: area.x1 - rect.left, y1: area.y1 - rect.top });
    };
    const up = (ev: PointerEvent) => {
      // 没拉开就还是「点了一下针道」：整组清掉（按住 Shift 点空处等于什么都没加），并把这条片段选中，
      // 与以前 pointerdown 落在片段身上那一笔的行为对齐——少一个入口不算改手感。
      if (!draggedEnough(origin, { x: ev.clientX, y: ev.clientY })) {
        stop();
        setPicked(additive ? base : []);
        selectClip(clip.id);
        return;
      }
      stop();
      move(ev);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };

  const startKey = (event: React.PointerEvent, key: Keyframe) => {
    event.stopPropagation();
    if (razor || event.button !== 0 || track.locked || !box.current || !app.caps?.features?.keyframes) return;
    event.preventDefault();
    const node = box.current;
    const id = needleId(key);
    if (event.shiftKey) { setPicked(togglePick(picked, id)); return; }
    const group = picked.includes(id) ? (clip.keyframes ?? []).filter((member) => picked.includes(needleId(member))) : [key];
    if (!picked.includes(id)) setPicked([id]);
    const offset = clip.animation_offset_ticks ?? 0;
    const from = key.at_ticks - offset;
    // 贴边的针为了看得见会被画在离边 6px 处，画的位置与它真正的时间不是一回事：抓住时记住这一点
    // 偏差，松手就按它落回去，否则「抓最左边那枚针」会把它瞬移到画出来的位置上。
    const grab = ((event.clientX - box.current.getBoundingClientRect().left) / px) * TIMEBASE - from;
    const duplicate = event.altKey;
    const plan = (clientX: number) => planKeyframeDrag({
      clip, key, group, px, snap, quantum: q, duplicate,
      pointer_ticks: ((clientX - node.getBoundingClientRect().left) / px) * TIMEBASE - grab,
      playhead_ticks: playhead.value - clip.position_ticks,
    });
    const held = (next: ReturnType<typeof planKeyframeDrag>): NeedleHeld => next.kind === "noop"
      ? { anchor: id, at: from, blocked: false, duplicate, layer: false, targets: [] }
      : next.kind === "blocked"
        ? { anchor: id, at: next.at_ticks, blocked: true, duplicate, layer: false, targets: [{ id, from, at: next.at_ticks }] }
        : { anchor: id, at: next.at_ticks, blocked: false, duplicate, layer: false,
          targets: next.shifts.map((member, index) => ({ id: needleId(group[index]), from: member.from, at: member.at })) };
    const move = (ev: PointerEvent) => setKeyDrag(held(plan(ev.clientX)));
    const stop = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      setKeyDrag(null);
      selectClip(clip.id);
      if (ev.type === "pointercancel") return;
      if (Math.abs(ev.clientX - event.clientX) < 2) {
        // 没拖动就还是「点一下跳过去」；按住 Alt 点则是删掉这一枚，走的仍是带 expected_revision 的那条链。
        if (duplicate) editAtRevision([planNeedleRemoval(clip, group)], project.id, project.revision, group.length > 1 ? `删除 ${group.length} 枚关键帧` : "删除关键帧", app.sequenceId);
        setPicked([]);
        playhead.pause(); playhead.set(clip.position_ticks + from); return;
      }
      const next = plan(ev.clientX);
      if (next.kind === "noop") { if (duplicate) toast("warn", "没有多出一枚针", "复制的落点就在原针那一格上，先往旁边挪一点再松手。"); return; }
      if (next.kind === "blocked") { toast("warn", group.length > 1 ? `这一组 ${group.length} 枚走不到那里` : "那一格已经有一枚针", next.reason); return; }
      // 一次抓取只交一次：一组针落在同一条命令（或同一批次）里，撤销一步就整组回来。
      editAtRevision(next.commands, project.id, project.revision, group.length > 1 ? `${duplicate ? "复制" : "拖动"} ${group.length} 枚关键帧` : duplicate ? "复制关键帧" : "拖动关键帧", app.sequenceId);
      setPicked([]);
      playhead.pause(); playhead.set(clip.position_ticks + next.at_ticks);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  /** 1.208：第二路画面那一层的针也在这条道上拖。抓取、吸附、让位与上面那一只手同一批原语
   *  （`planLayerNeedleDrag`），差别只在落库：写的还是那一条 `clip.grade` 整链替换，
   *  所以这里只交回命令，不新造第二份折刻度。
   *  1.211 把 1.208 故意欠下的两只手补上了：**按住 Alt 拖是复制一枚**（原针留下，落点上有别人的针就当场
   *  说清是复制走不通），**按住 Alt 点一下是删掉这一枚**（`planLayerNeedleRemoval`，与拖动同一条落库链）。
   *  仍不给的只有一只：Shift 挑组——组的语义是「一条曲线上的几枚针一起走」，而层针在检查器与动画曲线里
   *  各有自己的名字，混进那一组就会有一枚针被两条路同时改。 */
  const startLayerKey = (event: React.PointerEvent, needle: LayerNeedle) => {
    event.stopPropagation();
    if (razor || event.button !== 0 || track.locked || !box.current || !app.caps?.features?.keyframes) return;
    event.preventDefault();
    const node = box.current;
    const id = needleId(needle);
    const from = needle.at_ticks;
    const duplicate = event.altKey;
    const grab = ((event.clientX - node.getBoundingClientRect().left) / px) * TIMEBASE - from;
    const plan = (clientX: number) => planLayerNeedleDrag({
      clip, field: needle.field, from, px, snap, quantum: q, duplicate,
      pointer_ticks: ((clientX - node.getBoundingClientRect().left) / px) * TIMEBASE - grab,
      playhead_ticks: playhead.value - clip.position_ticks,
    });
    const held = (next: ReturnType<typeof planLayerNeedleDrag>): NeedleHeld => next.kind === "noop"
      ? { anchor: id, at: from, blocked: false, duplicate, layer: true, targets: [] }
      : next.kind === "blocked"
        ? { anchor: id, at: next.at_ticks, blocked: true, duplicate, layer: true, targets: [{ id, from, at: next.at_ticks }] }
        : { anchor: id, at: next.at_ticks, blocked: false, duplicate, layer: true, targets: [{ id, from, at: next.at_ticks }] };
    const move = (ev: PointerEvent) => setKeyDrag(held(plan(ev.clientX)));
    const stop = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      setKeyDrag(null);
      selectClip(clip.id);
      if (ev.type === "pointercancel") return;
      if (Math.abs(ev.clientX - event.clientX) < 2) {
        // 点一下（没拖动）仍是「把播放头跳到那一格」；按住 Alt 点一下是删掉这一枚——与上面 ◆ 那一只手
        // 同一个入口、同一条带 expected_revision 的落库链，只是写的还是那一条 `clip.grade`。
        if (duplicate) {
          const gone = planLayerNeedleRemoval(clip, needle.field, from);
          if (gone) editAtRevision([gone], project.id, project.revision, `删掉第 ${needle.field.layer + 1} 层的关键帧`, app.sequenceId);
          else toast("warn", "那一枚已经不在了", "这一格上没有这一层的这根针了：右边那一层卡片下面那一排 ◇ 里能看到还剩哪几枚。");
        }
        playhead.pause(); playhead.set(clip.position_ticks + from); return;
      }
      const next = plan(ev.clientX);
      if (next.kind === "noop") { if (duplicate) toast("warn", "没有多出一枚针", "复制的落点就在原针那一格上，先往旁边挪一点再松手。"); return; }
      if (next.kind === "blocked") { toast("warn", "那一格已经有一枚针", next.reason); return; }
      editAtRevision(next.commands, project.id, project.revision, duplicate ? `复制第 ${needle.field.layer + 1} 层的关键帧` : `拖动第 ${needle.field.layer + 1} 层的关键帧`, app.sequenceId);
      playhead.pause(); playhead.set(clip.position_ticks + next.at_ticks);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  /** 1.261：条上那一枚框点现在也是一只手。换算、吸附与「必定被拒的那一下先拦在发出去之前」
   *  都收在 `planBoxKeyDrag` 一处；落库仍走那唯一的一个写入口 `setClipMaskStack`（一次交回整串，
   *  一个批次一个版本），所以这一手既没有新命令、也没有新错误码。
   *  抓取期间在 window 上听 move/up/cancel（1.252 那一课：SVG/绝对定位小盒子上 pointer capture
   *  不可靠，松手收不到就永远不落库）。 */
  const startBoxKey = (event: React.PointerEvent, block: number, index: number, at: number) => {
    event.stopPropagation();
    if (razor || event.button !== 0 || track.locked || !box.current) return;
    event.preventDefault();
    const node = box.current;
    // 抓取期间工程可以被另一边改写：记住按下那一刻的那份工程与版本，松手按它写——
    // 版本对不上就拒（409），而不是拿旧的那一串把别人的改动顶掉（画面里那一手同一口径）。
    const projectId = project.id;
    const revision = project.revision;
    // 画出来的那一格与它真正的时间不是一回事（贴边那枚会被让位）：按下时记住抓取偏差，
    // 松手按它落回去，否则「抓最左边那一枚」会把它瞬移到画出来的位置上（1.110 同一课）。
    const grab = ((event.clientX - node.getBoundingClientRect().left) / px) * TIMEBASE - at;
    const plan = (clientX: number) => planBoxKeyDrag({
      id: clip.id,
      duration_ticks: clip.duration_ticks,
      position_ticks: clip.position_ticks,
      stack: clip.extra_masks ?? [],
      block,
      index,
      pointer_ticks: ((clientX - node.getBoundingClientRect().left) / px) * TIMEBASE - grab,
      px,
      quantum: q,
      snap,
      playhead: playhead.value - clip.position_ticks,
      attract: true,
    });
    const move = (ev: PointerEvent) => {
      const next = plan(ev.clientX);
      setBoxKeyDrag({ block, index, at: next.kind === "noop" ? at : next.at, blocked: next.kind === "blocked" ? next.reason : null });
    };
    const stop = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      setBoxKeyDrag(null);
      if (ev.type === "pointercancel") return;
      // 原地松手就还是「点一下跳过去」：一枚都不写，也不留一条空命令。
      if (Math.abs(ev.clientX - event.clientX) < 2) {
        selectClip(clip.id);
        playhead.pause();
        playhead.set(clip.position_ticks + at);
        return;
      }
      const next = plan(ev.clientX);
      if (next.kind === "noop") return;
      if (next.kind === "blocked") {
        toast("warn", "那一格已经有另一枚框点", next.reason);
        return;
      }
      setClipMaskStack(clip.id, next.masks, undefined, projectId, revision);
      selectClip(clip.id);
      playhead.pause();
      playhead.set(clip.position_ticks + next.at);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  /** 那一枚的键盘孪生：方向键 ±1 帧、Shift 方向键 ±10 帧（与旋转手柄那一只手同一档）。
   *  键盘不去吸播放头与邻居——按的就是那一格，`attract` 关掉。 */
  const nudgeBoxKey = (event: React.KeyboardEvent, block: number, index: number, at: number) => {
    if (razor || track.locked) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    event.stopPropagation();
    const step = (event.shiftKey ? 10 : 1) * q * (event.key === "ArrowRight" ? 1 : -1);
    const next = planBoxKeyDrag({
      id: clip.id,
      duration_ticks: clip.duration_ticks,
      position_ticks: clip.position_ticks,
      stack: clip.extra_masks ?? [],
      block,
      index,
      pointer_ticks: at + step,
      px,
      quantum: q,
      snap,
      playhead: playhead.value - clip.position_ticks,
      attract: false,
    });
    if (next.kind === "noop") return;
    if (next.kind === "blocked") {
      toast("warn", "那一格已经有另一枚框点", next.reason);
      return;
    }
    setClipMaskStack(clip.id, next.masks);
    playhead.pause();
    playhead.set(clip.position_ticks + next.at);
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

  /** 1.278：片段右键。右键落在没选中的一段上就先选中它（达芬奇 / 剪映 / AE 都是这一手）；
   *  落在已选中的一段上则保留整组——菜单读的是**当前选择**，多选之后右键，删除与复制仍按整组走。
   *  每一项都调工具条 / 检查器已经在调的那个 store 函数，这一处不新造命令、也不自己算能不能用。 */
  const clipMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!selected) selectClip(clip.id);
    const ids = selected ? selectionFor(app.selectedClips) : selectionFor([clip.id]);
    const members = ids.map((id) => project.clips[id]).filter(Boolean);
    const keys = keymap();
    const inside = playhead.value > clip.position_ticks && playhead.value < clip.position_ticks + clip.duration_ticks;
    const entries: MenuEntry[] = [
      {
        kind: "item", label: commandLabel("split-at-playhead"), icon: "razor", hint: chordWords(keys["split-at-playhead"]),
        disabled: !inside, title: inside ? "剪开之后两段各自保留自己那一截，撤销一步整批退回" : "先把播放头停在这一段里面",
        run: () => splitSelection(playhead.value),
      },
      { kind: "item", label: commandLabel("copy"), icon: "copy", hint: chordWords(keys.copy), run: copySelection },
      { kind: "item", label: commandLabel("paste"), hint: chordWords(keys.paste), disabled: !app.clipboardCount, run: pasteSelection },
      { kind: "item", label: commandLabel("duplicate"), hint: chordWords(keys.duplicate), run: duplicateSelection },
      { kind: "sep", id: "cut" },
      { kind: "item", label: commandLabel("delete-selection"), icon: "trash", hint: chordWords(keys["delete-selection"]), run: () => removeSelection() },
      { kind: "item", label: commandLabel("ripple-delete"), hint: chordWords(keys["ripple-delete"]), danger: true, run: () => removeSelection(true) },
      { kind: "sep", id: "association" },
      { kind: "item", label: commandLabel("group"), hint: chordWords(keys.group), disabled: members.length < 2, run: () => groupSelection() },
      { kind: "item", label: commandLabel("ungroup"), hint: chordWords(keys.ungroup), disabled: !members.some((member) => member.group_id), run: () => groupSelection(true) },
      { kind: "item", label: commandLabel("link"), icon: "link", hint: chordWords(keys.link), disabled: !canLinkClips(project, members), title: "先对齐画面与声音的开始、时长和速度", run: () => linkSelection() },
      { kind: "item", label: commandLabel("unlink"), hint: chordWords(keys.unlink), disabled: !members.some((member) => member.link_id), run: () => linkSelection(true) },
    ];
    if (canDetachAudio(project, clip)) {
      entries.push({ kind: "item", label: "拆出音频", icon: "music", title: "把这一段的声音拆成独立声音轨，方便单独淡入淡出或对齐其他音轨", run: () => detachAudio(clip.id) });
    }
    if ((clip.keyframes ?? []).length) {
      entries.push(
        { kind: "sep", id: "curves" },
        { kind: "item", label: "打开动画曲线", icon: "spark", title: "这一段上已经有针：进动画曲线改值、改插值或整组复制", run: () => { selectClip(clip.id); setGraphOpen(true); } },
      );
    }
    openContextMenu({
      at: { x: event.clientX, y: event.clientY },
      title: clip.text?.body ?? asset?.label ?? clip.id,
      label: "片段操作",
      returnTo: event.currentTarget,
      entries,
    });
  };

  // 转场那块牌子占住左下角多宽——**唯一的出处**：牌子自己与让位的那枚针都读这一个数。
  // 1.228：名字与时长不再读它——它们搬到了卡片上面那一行，牌子在下、字在上，两条带不重叠。
  const seamWidth = clip.transition_in
    ? Math.min(width, Math.max(SEAM_BADGE_MIN_WIDTH_PIXELS, (clip.transition_in.duration_ticks / TIMEBASE) * px))
    : 0;
  // 1.242：再叠的那几块遮罩自己的框点不在针道里（针道说的是片段与第二路画面那一层的属性），
  // 但它们的**时间**得在条上看得见：卡片顶边排一串 3px 的点，只标时间、不接指针——
  // 接了就等于在片段顶上挖出一块拖不动的死区，而这里没有可拖的东西。
  const boxKeyRows = (clip.extra_masks ?? [])
    .map((mask, index) => ({ index, times: (mask.keys ?? []).map((key) => key.at_ticks) }))
    .filter((row) => row.times.length);
  // 1.261：同一格上落了两块（复制那一手就会这样）时只画得下一枚——两枚盒子像素完全相同，
  // 低的那一枚就成了「看得见、点不到」（1.213 给针立的那条规矩在这里同一件事）。
  // 少画的那几枚必须有名字：带子的悬停与那一枚自己的悬停都点名它，出路是检查器那一块那一行。
  const drawn = new Map<number, number>();
  const shadowed: { index: number; at: number }[] = [];
  for (const row of boxKeyRows) {
    for (const at of row.times) {
      if (drawn.has(at)) shadowed.push({ index: row.index, at });
      else drawn.set(at, row.index);
    }
  }
  const shadowWords = shadowed.map((item) => `第 ${item.index + 1} 块的 ${humanDuration(item.at)}`).join("、");
  const boxKeyWords = [...drawn.keys()].map((at) => `第 ${drawn.get(at)!} 块的 ${humanDuration(at)}`).join("、")
    + (shadowed.length ? `；没有画出来的：${shadowWords}` : "");

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
      title={`${asset?.label ?? clip.asset_id}\n时长 ${humanDuration(duration)}\n位置 ${position.toLocaleString("en-US")} tick${boxKeyRows.length ? `\n再叠的遮罩框点：${boxKeyWords}（条顶上那排小点；打点、改插值与删除在检查器「再叠的遮罩」那一格）` : ""}`}
      onPointerDown={(event) => start(event, "move")}
      onContextMenu={clipMenu}
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
      <div className="clip-top">
        <span className="clip-label">{clip.text?.body ?? asset?.label ?? clip.asset_id}</span>
        {asset?.sequence_id ? <span className="ghost-tag" title="双击进入合成编辑内部图层">合成</span> : asset && !asset.verified && asset.kind !== "text" ? <span className="ghost-tag unverified" title="只有元数据、没有真实文件，无法预览和导出">未导入</span> : null}
        {clip.group_id || clip.link_id ? <span className="clip-association" title={`${clip.group_id ? "持久组合" : ""}${clip.link_id ? " · 音画链接" : ""}`}>{clip.group_id ? "▣" : ""}{clip.link_id ? "↔" : ""}</span> : null}
        {/* 时长只在卡片放得下时出现：窄片上它会把名字挤没，而名字是这一段唯一的身份。
            时间码在悬停、检查器与工具条里都还有，少这一格不是少一处信息。 */}
        {width >= CLIP_DURATION_MIN_PIXELS ? <span className="clip-dur mono">{(duration / TIMEBASE).toFixed(2)}s</span> : null}
      </div>
      {(() => {
        // 一条属性一道：同一秒上的两枚针画在同一堆像素里，其中一枚就点不到（实测过）。
        // 画不下的属性宁可不画，也不许叠回去——改成一枚 +N 的牌子把人带回动画曲线。
        const visible = (clip.keyframes ?? []).filter((k) => k.at_ticks >= (clip.animation_offset_ticks ?? 0) && k.at_ticks <= (clip.animation_offset_ticks ?? 0) + clip.duration_ticks);
        // 1.208：第二路画面那一层的针进的是**同一张分道表**——「一条属性一道」这句话对它同样成立，
        // 所以不分两套道，也不许有两处「画得下几道」的算术。
        const layered = layerNeedles(clip);
        const laned = [...visible, ...layered];
        const { rowOf, hidden } = needleRows(laned, laneCapacity(NEEDLE_AREA_PIXELS), PROPERTY_RANK);
        // 转场牌子占住片段左下角那一条带（那几个数在 keyframeLanes，界面画与这一判读同一份）：
        // 抓取盒落进那块矩形的那枚针不画——「宁可少画，也不留一枚点不到的针」那条规矩的横向版本。
        // 那块带多宽读上面同一个 `seamWidth`：牌子、针、片段名与时长用的是一个数，
        // 以前只有针读它，于是时长那格与牌子叠在一起。
        // 一枚针不拖的时候站在哪：层的针按自己那份刻度，片段自己的针要减掉动画窗的偏移。
        // 这一句是唯一的出处——画的时候、判牌子压没压的时候，都问它，不许两处各算一遍。
        const rest = (k: (typeof laned)[number]) => ("field" in k ? k.at_ticks : k.at_ticks - (clip.animation_offset_ticks ?? 0));
        const underBadge = (k: (typeof laned)[number]) => seamWidth > 0
          && underSeamBadge(rowOf.get(k.property) ?? 0, Math.min(width - NEEDLE_HALF_PIXELS, Math.max(NEEDLE_HALF_PIXELS, (rest(k) / clip.duration_ticks) * width)), seamWidth);
        const painted = laned.filter((k) => rowOf.has(k.property) && !underBadge(k));
        const starved = laned.filter((k) => !painted.includes(k));
        const clipPainted = painted.filter((k): k is Keyframe => !("field" in k));
        const layerPainted = painted.filter((k): k is LayerNeedle => "field" in k);
        const laneOf = new Map(painted.map((k) => [needleId(k), rowOf.get(k.property) ?? 0]));
        // 「+N」数的是**枚**：道表画不下的那些针，加上被转场牌子压住的那些针，两处不各数一遍。
        // 牌子里列的属性名去重——同一条属性上少了两枚针，说的是同一件事。
        const more = starved.length;
        const moreLabels = [...new Set([...hidden, ...starved.map((k) => k.property)])].map((property) => {
          const row = layered.find((k) => k.property === property);
          return row ? `第 ${row.field.layer + 1} 层 · ${LAYER_KEY_LABEL[row.field.key] ?? row.field.key}` : FIELD_LABEL[property as keyof typeof FIELD_LABEL] ?? property;
        });
        // 针与它的影子共用这一句夹法：贴边那枚要看得见；牌子上场时右端让开的是**它自己的方子**
        // 加针自己伸出去的那一半——1.112 那句 16px 把 left 当成了针的左边缘，量错了一整枚针的宽度。
        // 1.219：左端也按针自己的半宽夹（原来是字面 6，比半宽小，于是半个盒子伸出片段被裁掉）。
        const keep = more ? CHIP_KEEP_PIXELS + NEEDLE_HALF_PIXELS : NEEDLE_HALF_PIXELS;
        const needleX = (at: number) => Math.min(width - keep, Math.max(NEEDLE_HALF_PIXELS, (at / clip.duration_ticks) * width));
        return <>
          {painted.length ? <span className="clip-needles" style={{ left: MARQUEE_INSET_PIXELS, right: MARQUEE_INSET_PIXELS, height: NEEDLE_AREA_PIXELS }}
            title="在针道的空处拉一个框，框里的针一起挑中：整组拖就是同时改同一份时间差。按住 Shift 点一枚是加进这一组或从组里摘出去。"
            onPointerDown={startMarquee} /> : null}
          {boxKeyRows.length ? <span className="clip-boxkeys" role="group" aria-label={`再叠的遮罩框点：${boxKeyWords}`}>
            {boxKeyRows.flatMap((row) => row.times.map((at, keyIndex) => {
              if (drawn.get(at) !== row.index) return [];   // 同一格只画第一枚，其余在悬停里有名字
              const held = Boolean(boxKeyDrag) && boxKeyDrag?.block === row.index && boxKeyDrag?.index === keyIndex;
              // 拖的那一枚跟着指针走（屏幕跟手是这一手的判据之一），松手才按落点落库。
              const live = held && boxKeyDrag ? boxKeyDrag.at : at;
              const name = `第 ${row.index + 1} 块 · 框点 ${humanDuration(at)}`;
              // 命中盒那一个数只有一个主人：`BOX_KEY_HIT_PIXELS`——样式表里不许再抄一遍宽高。
              const style = { left: `${(live / clip.duration_ticks) * 100}%`, width: BOX_KEY_HIT_PIXELS.width, height: BOX_KEY_HIT_PIXELS.height };
              if (razor || track.locked) return <span key={`${row.index}-${at}`} className="clip-boxkey static" style={style}
                title={`${name} · 这一轨${track.locked ? "锁住了" : "正等着划刀"}，拖不动；打点、改时刻与删除在检查器「再叠的遮罩」那一格`} />;
              return <button key={`${row.index}-${at}`} type="button"
                className={`clip-boxkey${held ? " held" : ""}${held && boxKeyDrag?.blocked ? " blocked" : ""}`}
                style={style}
                aria-label={`${name}，横向拖只改这一枚的时间`}
                title={`${name} · 横向拖只改这一枚的时间；方向键 ±1 帧，Shift 方向键 ±10 帧${held && boxKeyDrag?.blocked ? " · 那一格已经有另一枚，先挪开" : ""}${shadowed.some((item) => item.at === at) ? ` · 还有 ${shadowWords} 停在同一格，条上只画得下一枚，那几块在检查器各自那一行改` : ""}`}
                onPointerDown={(event) => startBoxKey(event, row.index, keyIndex, at)}
                onKeyDown={(event) => nudgeBoxKey(event, row.index, keyIndex, at)} />;
            }))}
          </span> : null}
          {band ? <span className="clip-marquee" style={{ left: band.x0, top: band.y0, width: Math.max(0, band.x1 - band.x0), height: Math.max(0, band.y1 - band.y0) }} aria-hidden="true" /> : null}
          {clipPainted.map((k) => {
            const from = rest(k);
            const id = needleId(k);
            const target = keyDrag && !keyDrag.duplicate ? keyDrag.targets.find((item) => item.id === id) : undefined;
            const refused = Boolean(keyDrag?.blocked && (keyDrag.anchor === id || keyDrag.targets.some((item) => item.id === id)));
            const at = target ? target.at : from;
            const label = FIELD_LABEL[k.property] ?? k.property;
            const hint = picked.includes(id)
              ? `这一枚在挑中的 ${picked.length} 枚里，拖它就是整组一起走；Shift 点一下从组里摘出去，按住 Alt 点一下把这 ${picked.length} 枚一起删掉`
              : "横向拖可以改时间，按住 Alt 拖是复制一枚，按住 Alt 点一下是删掉这一枚，Shift 点一下是加进一组针";
            return <button
              key={`${k.property}-${k.at_ticks}`} data-key-id={id} type="button"
              className={`clip-keyframe${target ? " dragging" : ""}${refused ? " blocked" : ""}${picked.includes(id) ? " selected" : ""}`}
              style={{ left: needleX(at), bottom: NEEDLE_BOTTOM_PIXELS + (rowOf.get(k.property) ?? 0) * LANE_PITCH_PIXELS }}
              title={`${label} · ${humanDuration(from)}${keyDrag ? ` → ${humanDuration(at)}` : ` · ${hint}`}`}
              aria-label={`拖动${label}关键帧`}
              aria-disabled={track.locked || razor || !app.caps?.features?.keyframes}
              onPointerDown={(event) => startKey(event, k)}>◆</button>;
          })}
          {layerPainted.map((k) => {
            const id = needleId(k);
            const target = keyDrag ? keyDrag.targets.find((item) => item.id === id) : undefined;
            const refused = Boolean(keyDrag?.blocked && keyDrag.anchor === id);
            const at = target ? target.at : rest(k);
            const label = `第 ${k.field.layer + 1} 层 · ${LAYER_KEY_LABEL[k.field.key] ?? k.field.key}`;
            return <button
              key={id} data-key-id={id} type="button"
              className={`clip-keyframe layer-needle${target ? " dragging" : ""}${refused ? " blocked" : ""}`}
              style={{ left: needleX(at), bottom: NEEDLE_BOTTOM_PIXELS + (rowOf.get(k.property) ?? 0) * LANE_PITCH_PIXELS }}
              title={`${label} · ${humanDuration(k.at_ticks)}${keyDrag ? ` → ${humanDuration(at)}` : " · 横向拖只改这一枚的时间；按住 Alt 拖是复制一枚，按住 Alt 点一下是删掉这一枚。要改那一个数，就在右边这一层卡片下面那一排里改——◇ 那一条就是这一层的针"}`}
              aria-label={`拖动${label}关键帧`}
              aria-disabled={track.locked || razor || !app.caps?.features?.keyframes}
              onPointerDown={(event) => startLayerKey(event, k)}>◈</button>;
          })}
          {keyDrag?.duplicate ? keyDrag.targets.filter((item) => item.at !== item.from).map((item) => <span
            key={item.id} className={`clip-keyframe ghost${keyDrag.blocked ? " blocked" : ""}`}
            style={{ left: needleX(item.at), bottom: NEEDLE_BOTTOM_PIXELS + (laneOf.get(item.id) ?? 0) * LANE_PITCH_PIXELS }}
            aria-hidden="true">{keyDrag.layer ? "◈" : "◆"}</span>) : null}
          {more ? <button type="button" className="clip-keyframe-more" aria-label={`${more} 枚针没有画在这里`}
            title={`画不下的针：${moreLabels.join("、")}——点开进动画曲线看这条片段的全部针（层上的针在这条道上能拖时间，改值与删针在那条曲线的阶梯上）`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => { selectClip(clip.id); setGraphOpen(true); }}>+{more}</button> : null}
        </>;
      })()}
      {keyDrag ? <span className={`key-readout mono${keyDrag.blocked ? " blocked" : ""}`}>{(keyDrag.at / TIMEBASE).toFixed(3)}s{keyDrag.blocked ? " 已占用" : ""}{keyDrag.targets.length > 1 ? ` ×${keyDrag.targets.length} 枚` : ""}</span> : null}
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
      <span className="trim-handle left" title="拖动改变源入点（从素材的哪一秒开始）；Shift 涟漪修剪，Ctrl 滚动剪辑；Alt 只动这一边（音画链接时就是 J/L cut）" onPointerDown={(event) => start(event, "trim-l")} />
      <span className="trim-handle right" title="拖动改变时长；Shift 涟漪修剪，Ctrl 滚动剪辑；Alt 只动这一边（音画链接时就是 J/L cut）" onPointerDown={(event) => start(event, "trim-r")} />
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
