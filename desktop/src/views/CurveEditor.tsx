import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from "react";

import { type AnimationGraph, type Clip, type Keyframe, type LayerKeyframe, type Property, type Bezier } from "../engine";
import { EFFECT_FIELDS, FIELD_LABEL, INTERPOLATIONS, curveBase, layerCurveBase, layerCurveFields, layerKeyCommand, layerKeysOf, layerStepAt, maskAnimFields, spatialAnimFields, type LayerCurveField } from "../effects";
import { TIMEBASE, timecode } from "../time";
import { keyframeTick } from "../keyframeSnap";
import { applyShift, bandEdges, bandEntry, groupShift, quantizeToBand } from "../curveDrag";
import { copyKeys, pasteKeys, rememberCopy, copiedKeys, type CopiedKeys } from "../keyframeClipboard";
import { appInfo, clearBatch, commitBatch, editAtRevision, playhead, prefs, quantum, redoStep, selectClips, setGraphOpen, setMode, toast, undo, useApp, useEdit, usePlay } from "../store";

const LEFT = 58, TOP = 12, WIDTH = 924, HEIGHT = 166;

const DEFAULT_BEZIER: Bezier = { x1: 1 / 3, y1: 0, x2: 2 / 3, y2: 1 };
const interpolationPoint = (point: Keyframe, interpolation: Keyframe["interpolation"]): Keyframe => ({ ...point, interpolation, bezier: interpolation === "bezier" ? point.bezier ?? DEFAULT_BEZIER : null });
const keySignature = (keys: Keyframe[]) => JSON.stringify([...keys].sort((a,b) => a.property.localeCompare(b.property) || a.at_ticks-b.at_ticks).map((k) => [k.property,k.at_ticks,k.value,k.interpolation,k.bezier ? [k.bezier.x1,k.bezier.y1,k.bezier.x2,k.bezier.y2] : null]));

/** A value graph: SVG draws server geometry; gestures submit ordinary timeline commands. */
export function CurveEditor() {
  const app = useApp();
  const project = app.project;
  if (!project) return null;
  const proposed = app.mode === "batch" && app.batch.length > 0;
  const candidate = proposed && app.candidate?.id === project.id && app.candidate.revision === project.revision + 1 && !app.dryRunError ? app.candidate : null;
  const effective = candidate ?? project;
  const clip = effective.clips[app.selectedClip ?? ""];
  const clips = Object.values(effective.clips);
  return <section className="timeline curve-editor" aria-label="动画曲线编辑器">
    <div className="curve-toolbar">
      <b>动画曲线</b>
      <select className="input curve-clip" aria-label="动画片段" value={clip?.id ?? ""} onChange={(e) => { playhead.pause(); selectClips([e.target.value], true); }}>
        <option value="" disabled>选择要编辑的片段</option>
        {clips.map((c) => <option key={c.id} value={c.id}>{effective.tracks.find((t) => t.id === c.track_id)?.name} · {c.text?.body ?? effective.assets[c.asset_id]?.label ?? c.id}</option>)}
      </select>
      <span className="tag">{candidate ? "批次预演" : `r${project.revision}`}</span>
      <span className="spacer" />
      <button className="btn tiny" disabled={!app.undo.length || Boolean(app.busy)} onClick={() => void undo()}>撤销</button>
      <button className="btn tiny" disabled={!app.redo.length || Boolean(app.busy)} onClick={() => void redoStep()}>重做</button>
      <div className="seg mini"><button className={app.mode === "instant" ? "active" : ""} onClick={() => setMode("instant")}>即时</button><button className={app.mode === "batch" ? "active" : ""} onClick={() => setMode("batch")}>批次</button></div>
      {app.batch.length ? <><button className="btn tiny" disabled={Boolean(app.busy)} onClick={clearBatch}>放弃批次</button><button className="btn tiny primary" disabled={Boolean(app.busy || app.dryRunBusy || app.dryRunError)} onClick={() => void commitBatch()}>提交 {app.batch.length} 条</button></> : null}
      <button className="btn tiny subtle" onClick={() => setGraphOpen(false)}>返回时间线</button>
    </div>
    {clip ? <ValueGraph key={`${project.id}/${clip.id}`} clip={clip} audio={effective.tracks.find((t) => t.id === clip.track_id)?.kind === "audio"} disabled={Boolean(app.busy || app.dryRunBusy || (proposed && !candidate) || effective.tracks.find((t) => t.id === clip.track_id)?.locked)} /> : <div className="empty-note">先选一个片段，或从上方菜单选择。这里编辑该片段的时间与属性曲线。</div>}
    {app.dryRunError ? <div className="inline-error">{app.dryRunError}</div> : null}
  </section>;
}

function ValueGraph({ clip, audio, disabled }: { clip: Clip; audio: boolean; disabled: boolean }) {
  const app = useApp(); const play = usePlay(); const project = app.project!;
  const options = [...EFFECT_FIELDS.filter((f) => !audio || f.property === "gain"), ...maskAnimFields(clip.mask, app.caps), ...(audio ? [] : spatialAnimFields(app.caps, project.settings.height)), ...layerCurveFields(clip, app.caps?.grade_limits?.layer_key_props, app.caps?.grade_limits?.layer_key_bands)];
  const [property, setProperty] = useState<string>(() => audio ? "gain" : clip.keyframes?.[0]?.property ?? "opacity");
  const field = options.find((f) => f.property === property) ?? options[0];
  /** 1.205：那一层的针住在链里，不住在 `clip.keyframes`——针的来源、起笔值、草稿与写入
   *  都按这一个判断走，别处不再数第二遍「这是哪一层」。 */
  const layerField = "layer" in field ? field as LayerCurveField : null;
  const layerNode = layerField
    ? (clip.color?.grade ?? []).filter((node) => node.kind === "layer" && node.enabled)[layerField.layer]
    : undefined;
  // 链里那个节点上的针：`GradeNode` 是联合类型，只有层那一支带 `keys`，所以这一处收口成一次 cast
  // （别处只读 `layerKeys`，不再各自钻 `node.keys`）。
  const layerKeys = (layerNode as unknown as { keys?: LayerKeyframe[] } | undefined)?.keys ?? [];
  const allKeys = (layerField ? layerKeys : clip.keyframes ?? []) as typeof clip.keyframes;
  const keyName = layerField ? layerField.key : field.property;
  // `field.property` 现在是复合身份（那一层的写成「层 0·rotation」），要交回引擎的地方都用真名。
  const propName = field.property as Property;
  const layerOptions = options.filter((f) => "layer" in f);
  const [selectedAt, setSelectedAt] = useState<number | null>(null);
  const [selection, setSelection] = useState<number[]>([]);
  const selectionMemory = useRef(new Map<string, { times: number[]; at: number | null }>());
  const [drafts, setDrafts] = useState<Keyframe[] | null>(null);
  const [box, setBox] = useState<{ x: number; y: number; right: number; bottom: number } | null>(null);
  const [result, setResult] = useState<{ base: Clip; property: string; graph: AnimationGraph } | null>(null);
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(1); const [pan, setPan] = useState(0);
  const [fit, setFit] = useState(true); const edit = useEdit(); const snap = edit.snap;
  const [newInterpolation, setNewInterpolation] = useState<Keyframe["interpolation"]>("ease");
  const svg = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ point: Keyframe; points: Keyframe[]; x: number; y: number; revision: number; projectId: string; moved: boolean; element: SVGCircleElement; pointerId: number; clientX: number; clientY: number; handle?: 0 | 1; right?: Keyframe } | null>(null);
  const marquee = useRef<{ x: number; y: number; base: number[]; pointerId: number; clientX: number; clientY: number } | null>(null);
  const clipPathId = useId().replace(/:/g, "");
  const offset = clip.animation_offset_ticks ?? 0;
  const signaturePrefix = `${field.property}/${offset}/${clip.duration_ticks}/`;
  const signature = useMemo(() => signaturePrefix+keySignature(allKeys ?? []), [allKeys, signaturePrefix]);
  useEffect(() => {
    const saved = selectionMemory.current.get(signature);
    if (saved) { selectionMemory.current.delete(signature); selectionMemory.current.set(signature, saved); setSelection(saved.times); setSelectedAt(saved.at); }
    else { setSelection([]); setSelectedAt(null); }
    const limit = app.undo.length+app.redo.length+2;
    while (selectionMemory.current.size > limit) selectionMemory.current.delete(selectionMemory.current.keys().next().value!);
  }, [signature, app.busy, app.dryRunBusy]);
  const keys = useMemo(() => ((allKeys ?? []) as typeof clip.keyframes ?? []).filter((k) => k.property === keyName && k.at_ticks >= offset && k.at_ticks <= offset + clip.duration_ticks).map((k) => ({ ...k, at_ticks: k.at_ticks - offset })).sort((a, b) => a.at_ticks - b.at_ticks), [allKeys, keyName, offset, clip.duration_ticks]);
  const selected = keys.find((k) => k.at_ticks === selectedAt);
  const selectionSet = useMemo(() => new Set(selection), [selection]);
  const selectedKeys = useMemo(() => keys.filter((k) => selectionSet.has(k.at_ticks)), [keys, selectionSet]);
  const draft = drafts?.[Math.max(0, drag.current?.points.findIndex((k) => k.at_ticks === selectedAt) ?? 0)];
  const point = draft ?? selected;
  const nextPoint = selected ? keys[keys.indexOf(selected) + 1] : undefined;
  const controls = point?.bezier ?? DEFAULT_BEZIER;
  const canHandle = selectedKeys.length === 1 && point?.interpolation === "bezier" && nextPoint && nextPoint.value !== point.value;
  const sources = drag.current?.points ?? selectedKeys;
  const sourceTimes = useMemo(() => new Set(sources.map((k) => k.at_ticks)), [sources]);
  const draftTimes = useMemo(() => new Set(drafts?.map((k) => k.at_ticks)), [drafts]);
  const collision = Boolean(drafts && keys.some((k) => !sourceTimes.has(k.at_ticks) && draftTimes.has(k.at_ticks)));
  const input = useMemo(() => drafts && !collision ? (layerField
    // 那一层的草稿不写进 `clip.keyframes`：折刻度与挑出「第几层」只有一处实现（`layerKeysOf`），
    // 预演与提交读的因此是同一条链，不会出现「屏幕上那一格与文件里那一格不是同一个数」。
    ? layerKeysOf(clip, layerField, drafts as never[])
    : { ...clip, keyframes: [...(clip.keyframes ?? []).filter((k) => !(k.property === field.property && sourceTimes.has(k.at_ticks-offset))), ...drafts.map((k) => ({ ...k, at_ticks: k.at_ticks + offset }))] }) : clip, [clip, drafts, collision, field.property, offset, sourceTimes, layerField]);

  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      // 普通曲线走那条老读法；那一层走新的那一条——两条都只有一处调用，界面不自己 walk 窗表。
      const request = layerField
        ? appInfo.engine()?.animationLayerCurve(input, layerField.key, layerField.layer, quantum(project, audio ? "audio" : "video"))
        : appInfo.engine()?.animationCurve(input, field.property as Property);
      void request?.then((graph) => {
        if (live) { setResult({ base: clip, property: field.property, graph: graph as AnimationGraph }); setError(""); }
      }).catch((e) => { if (live) { setResult(null); setError(e instanceof Error ? e.message : "曲线读取失败"); } });
    }, draft ? 100 : 0);
    return () => { live = false; window.clearTimeout(timer); };
  }, [input, clip, field.property, layerField]);
  const graph = result?.base === clip && result.property === field.property ? result.graph : null;
  // Keep the value scale fixed while dragging so a moving point cannot move its own ruler.
  const values = useMemo(() => {
    const points = (((allKeys ?? []) as typeof clip.keyframes ?? []).filter((k) => k.property === keyName)).sort((a, b) => a.at_ticks-b.at_ticks);
    return points.flatMap((k, i) => k.interpolation === "bezier" && points[i+1] ? [k.value, k.value+(points[i+1].value-k.value)*(k.bezier ?? DEFAULT_BEZIER).y1, k.value+(points[i+1].value-k.value)*(k.bezier ?? DEFAULT_BEZIER).y2] : [k.value]).concat(layerField ? layerCurveBase(clip, layerField) : curveBase(clip, field as never));
  }, [clip, keyName, allKeys, field, layerField]);
  const band = { min: field.min, max: field.max, step: field.step, factor: field.factor };
  const { hardMin, hardMax } = bandEdges(band);
  const padding = Math.max((Math.max(...values) - Math.min(...values)) * .12, (hardMax - hardMin) * .04);
  const low = fit ? Math.min(...values) - padding : hardMin;
  const high = fit ? Math.max(...values) + padding : hardMax;
  const valueSpan = Math.max(.00001, high - low);
  const span = Math.max(1, Math.floor(clip.duration_ticks / zoom));
  const start = Math.min(pan, clip.duration_ticks - span);
  const q = quantum(project, audio ? "audio" : "video");
  const head = Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks));
  const x = (at: number) => LEFT + (at - start) / span * WIDTH;
  const y = (value: number) => TOP + (high - value) / valueSpan * HEIGHT;
  const valueLabel = (value: number) => `${(value * field.factor).toFixed(field.property === "rotation" ? 0 : 1)}${field.unit}`;
  const alignTime = (at: number, attract = true) => keyframeTick(at, { clip, quantum: q, span, plot: WIDTH }, snap, { playhead: head, keys: attract ? keys.filter((k) => !sourceTimes.has(k.at_ticks)).map((k) => k.at_ticks) : [], attract });
  const quantizeValue = (value: number) => quantizeToBand(value, band);
  const locate = (event: { clientX: number; clientY: number }) => {
    const rect = svg.current!.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width * 1000, y: (event.clientY - rect.top) / rect.height * 212 };
  };
  const seek = (at: number) => { playhead.pause(); playhead.set(clip.position_ticks + at); };
  const chooseSelection = (times: number[], at: number | null) => {
    selectionMemory.current.delete(signature);
    selectionMemory.current.set(signature, { times, at }); setSelection(times); setSelectedAt(at);
  };
  const rememberEdit = (from: Keyframe[], next: Keyframe[]) => {
    const fromTimes = new Set(from.map((k) => k.at_ticks));
    const kept = layerField
      ? (layerKeys as unknown as NonNullable<typeof clip.keyframes>).filter((k) => !(k.property === keyName && fromTimes.has(k.at_ticks-offset)))
      : (clip.keyframes ?? []).filter((k) => !(k.property === propName && fromTimes.has(k.at_ticks-offset)));
    const after = [...kept, ...next.map((k) => ({ ...k, at_ticks: k.at_ticks+offset }))];
    selectionMemory.current.delete(signature);
    selectionMemory.current.set(signature, { times: from.length ? from.map((k) => k.at_ticks) : selection, at: selectedAt });
    const target = { times: next.map((k) => k.at_ticks), at: next[Math.max(0,from.findIndex((k) => k.at_ticks === selectedAt))]?.at_ticks ?? null };
    selectionMemory.current.delete(signaturePrefix+keySignature(after));
    selectionMemory.current.set(signaturePrefix+keySignature(after), target);
    setSelection(target.times); setSelectedAt(target.at);
  };
  const selectPoint = (at: number, additive = false) => {
    const next = additive ? selection.includes(at) ? selection.filter((t) => t !== at) : [...selection, at] : [at];
    chooseSelection(next, next.includes(at) ? at : next[next.length-1] ?? null);
    return keys.filter((k) => next.includes(k.at_ticks));
  };
  const translate = (points: Keyframe[], dt: number, dv: number) => applyShift(points, groupShift(points, band, clip.duration_ticks, dt, dv), band);
  /** 1.205：写针只有一处分流。普通曲线交回那几条 `keyframe*` 命令，那一层交回把整条链改写的
   *  `clip.grade`（刻度折回去只在那一处实现里做）。加、拖、移、删四个写点全从这里出命令，
   *  所以不会出现「有一处忘了分流、界面上能拖而写进的是别的数」。 */
  const layerWrites = (next: Keyframe[]) => [layerKeyCommand(clip, layerField as LayerCurveField, next as unknown as LayerKeyframe[])];
  const moveCommands = (from: Keyframe[], next: Keyframe[]) => layerField
    ? layerWrites(next)
    : [{ op: "keyframes.move", clip_id: clip.id, moves: next.map((keyframe, i) => ({ from_ticks: from[i].at_ticks, keyframe })) }];
  const shiftCommands = (from: number, key: Keyframe) => layerField
    ? layerWrites(keys.map((k) => k.at_ticks === from ? key : k))
    : [{ op: "keyframe.move", clip_id: clip.id, from_ticks: from, keyframe: key }];
  const addCommands = (key: Keyframe) => layerField
    ? layerWrites([...keys.filter((k) => k.at_ticks !== key.at_ticks), key])
    : [{ op: "keyframe.set", clip_id: clip.id, keyframe: { ...key, property: field.property } }];
  const removeCommands = (targets: Keyframe[]) => layerField
    ? layerWrites(keys.filter((k) => !targets.some((t) => t.at_ticks === k.at_ticks)))
    : [{ op: "keyframes.remove", clip_id: clip.id, keyframes: targets.map((k) => ({ property: k.property, at_ticks: k.at_ticks })) }];
  const commitPoints = (from: Keyframe[], next: Keyframe[], revision = project.revision, projectId = project.id) => {
    if (disabled || !from.length) return;
    const fromTimes = new Set(from.map((k) => k.at_ticks)), nextTimes = new Set(next.map((k) => k.at_ticks));
    if (keys.some((k) => !fromTimes.has(k.at_ticks) && nextTimes.has(k.at_ticks))) { toast("warn", "这个时间已有关键帧", "选区未修改，也不会覆盖未选中的点。"); return; }
    if (JSON.stringify(from) === JSON.stringify(next)) return;
    rememberEdit(from, next);
    editAtRevision(moveCommands(from, next), projectId, revision, "编辑动画曲线", app.sequenceId);
    setSelection(next.map((k) => k.at_ticks)); const at = next[Math.max(0, from.findIndex((k) => k.at_ticks === selectedAt))].at_ticks; setSelectedAt(at); seek(at);
  };
  const commit = (from: number, next: Keyframe, revision = project.revision, projectId = project.id) => {
    if (disabled) return;
    if (keys.some((k) => k.at_ticks !== from && k.at_ticks === next.at_ticks)) { toast("warn", "这个时间已有关键帧", "放大曲线后选一个空位置，原关键帧未修改。"); return; }
    if (selected && from === next.at_ticks && selected.value === next.value && selected.interpolation === next.interpolation && JSON.stringify(selected.bezier ?? null) === JSON.stringify(next.bezier ?? null)) return;
    if (selected) rememberEdit([selected], [next]);
    editAtRevision(shiftCommands(from, next), projectId, revision, "编辑动画曲线", app.sequenceId);
    setSelection([next.at_ticks]); setSelectedAt(next.at_ticks); seek(next.at_ticks);
  };
  const cancel = () => {
    const gesture = drag.current;
    drag.current = null; setDrafts(null); setBox(null);
    const rectangle = marquee.current; marquee.current = null;
    if (rectangle && svg.current?.hasPointerCapture(rectangle.pointerId)) svg.current.releasePointerCapture(rectangle.pointerId);
    if (gesture?.element.hasPointerCapture(gesture.pointerId)) gesture.element.releasePointerCapture(gesture.pointerId);
  };
  useEffect(() => { cancel(); }, [clip, field.property, disabled]);
  useEffect(() => () => { drag.current = null; }, []);
  const proposedPoint = (event: PointerEvent<SVGCircleElement>) => {
    const gesture = drag.current!; const position = locate(event);
    if (gesture.handle !== undefined && gesture.right) {
      const control = gesture.handle === 0 ? ["x1", "y1"] as const : ["x2", "y2"] as const;
      const at = start + (position.x - LEFT) / WIDTH * span;
      const value = high - (position.y - TOP) / HEIGHT * valueSpan;
      const next = { ...(gesture.point.bezier ?? DEFAULT_BEZIER), [control[0]]: Math.max(0, Math.min(1, (at - gesture.point.at_ticks) / (gesture.right.at_ticks - gesture.point.at_ticks))), [control[1]]: Math.max(-4, Math.min(4, (value - gesture.point.value) / (gesture.right.value - gesture.point.value))) };
      gesture.moved ||= Math.abs(event.clientX - gesture.clientX) + Math.abs(event.clientY - gesture.clientY) > 3;
      return [{ ...gesture.point, bezier: next }];
    }
    let dx = position.x - gesture.x, dy = position.y - gesture.y;
    if (event.shiftKey) { if (Math.abs(dx) >= Math.abs(dy)) dy = 0; else dx = 0; }
    if (Math.abs(event.clientX - gesture.clientX) + Math.abs(event.clientY - gesture.clientY) > 3) gesture.moved = true;
    return translate(gesture.points, alignTime(gesture.point.at_ticks + dx / WIDTH * span)-gesture.point.at_ticks, quantizeValue(gesture.point.value - dy / HEIGHT * valueSpan)-gesture.point.value);
  };
  const add = (at: number, value: number, attract = true) => {
    if (disabled) return;
    at = attract ? alignTime(at) : Math.max(0, Math.min(clip.duration_ticks, Math.round(at)));
    if (keys.some((k) => k.at_ticks === at)) { selectPoint(at); seek(at); return; }
    editAtRevision(addCommands({ property: propName, at_ticks: at, value: quantizeValue(value), interpolation: newInterpolation, bezier: null }), project.id, project.revision, "编辑动画曲线", app.sequenceId);
    rememberEdit([], [{ property: propName, at_ticks: at, value: quantizeValue(value), interpolation: newInterpolation, bezier: null }]);
    setSelection([at]); setSelectedAt(at); seek(at);
  };
  const remove = () => {
    if (!selectedKeys.length || disabled) return;
    svg.current?.focus();
    rememberEdit(selectedKeys, []);
    editAtRevision(removeCommands(selectedKeys), project.id, project.revision, "删除动画选区", app.sequenceId);
    setSelection([]); setSelectedAt(null);
  };
  const [copied, setCopied] = useState<CopiedKeys | null>(copiedKeys());
  // 粘贴只有一处实现：按钮和 Ctrl+V 走同一个函数，落点、跳过与回执都是同一条判断。
  const pasteNow = () => {
    const paste = pasteKeys(clip, copied, alignTime(head, false), project.id);
    if (!paste.commands.length) { toast("warn", "没有粘贴", paste.reason); return; }
    editAtRevision(paste.commands, project.id, project.revision, "粘贴动画关键帧", app.sequenceId);
    toast(paste.dropped ? "warn" : "info", `粘贴了 ${paste.pasted} 枚关键帧`, paste.dropped ? paste.reason : "落在播放头起的整帧上。");
  };
  const atHead = () => {    // 播放头本身就落在格子上（标尺按同一份量子吸附），所以这里写的就是看到的那个位置：
    // 吸附不参与，否则相邻的针会把新针拽走，采到的值与落下的时间就对不上了。
    if (layerField) {
      // 那一层没有 `animationSample` 可问（那条路只认片段自己那六个数）：起笔读的是引擎那份
      // 阶梯在播放头这一格**已经算好的那一级**，界面不第二次插值。
      const step = layerStepAt(graph as never, clip.duration_ticks ? head / clip.duration_ticks : 0);
      add(head, step ?? layerCurveBase(clip, layerField), false);
      return;
    }
    void appInfo.engine()?.animationSample(clip, head).then((sample) => {
      add(head, sample.values[propName], false);
    }).catch(() => toast("error", "当前位置采样失败"));
  };
  const zoomTo = (factor: number) => {
    cancel(); const next = Math.max(1, Math.min(64, zoom * factor));
    const nextSpan = Math.max(1, Math.floor(clip.duration_ticks / next));
    setZoom(next); setPan(Math.max(0, Math.min(clip.duration_ticks - nextSpan, Math.round((point?.at_ticks ?? head) - nextSpan / 2))));
  };
  const jump = (direction: number) => {
    const index = keys.findIndex((k) => k.at_ticks === selectedAt);
    const key = keys[Math.max(0, Math.min(keys.length - 1, index < 0 ? direction < 0 ? keys.length - 1 : 0 : index + direction))];
    if (key) { selectPoint(key.at_ticks); seek(key.at_ticks); }
  };

  return <>
    <div className="curve-controls">
      <select className="input" aria-label="曲线属性" value={field.property} onChange={(e) => { cancel(); selectionMemory.current.clear(); setProperty(e.target.value); setSelection([]); setSelectedAt(null); }}>
        <optgroup label="片段自身">{options.filter((f) => !("layer" in f)).map((f) => <option key={f.property} value={f.property}>{f.label}</option>)}</optgroup>
        {layerOptions.length ? <optgroup label="第二路画面">{layerOptions.map((f) => <option key={f.property} value={f.property}>{f.label}</option>)}</optgroup> : null}
      </select>
      {layerField ? <p className="hint">这一行画的就是<b>导出执行的那批格子</b>：一级台阶是一个 `enable` 区间，拖动写回的仍是那一条 `clip.grade`——监视器与文件读同一份窗表，界面不第二次插值。</p> : null}
      <button className="btn tiny" disabled={!keys.length} onClick={() => jump(-1)}>上一关键帧</button><button className="btn tiny" disabled={!keys.length} onClick={() => jump(1)}>下一关键帧</button>
      <button className="btn tiny" disabled={disabled || (app.mode === "batch" && app.batch.length > 0)} onClick={atHead}>播放头添加</button>
      <button className="btn tiny" disabled={disabled || !selectedKeys.length} onClick={remove}>{selectedKeys.length > 1 ? `删除 ${selectedKeys.length} 点` : "删除关键帧"}</button>
      <button className="btn tiny" disabled={disabled || !copied || copied.property !== field.property} title={copied ? `把复制的 ${copied.keys.length} 枚 ${FIELD_LABEL[copied.property] ?? copied.property} 针按播放头粘到当前片段；落在片段之外或已有针那一格的会跳过` : "先选中同一条属性上的针，按 Ctrl+C 或点上面的复制"} onClick={pasteNow}>粘贴 {copied ? copied.keys.length : 0} 枚</button>
      <label title="与时间线的磁吸是同一个开关（状态栏那颗吸铁石、快捷键 S）：关掉两处一起关。拖到的位置落在整帧上，并会找播放头与这条曲线上没被拖动的针；数值框与「播放头添加」照精确位置写。"><input type="checkbox" checked={snap} onChange={(e) => prefs.setSnap(e.target.checked)} />时间吸附</label>
      <span className="spacer" />
      <button className="btn tiny" disabled={zoom === 1} onClick={() => zoomTo(.5)}>缩小曲线</button><button className="btn tiny" disabled={zoom === 64} onClick={() => zoomTo(2)}>放大曲线</button>
      <button className={`btn tiny${fit ? " active" : ""}`} aria-pressed={fit} onClick={() => { cancel(); setFit(!fit); }}>适合数值</button>
      <button className="btn tiny" onClick={() => { cancel(); setZoom(1); setPan(0); setFit(true); }}>完整片段</button>
    </div>
    <div className="curve-plot">
      <svg ref={svg} viewBox="0 0 1000 212" preserveAspectRatio="none" role="group" tabIndex={0} aria-label={`${field.label}数值曲线`} onPointerDown={(e) => {
          if (e.button !== 0 || (e.target as Element).closest(".curve-key,.curve-handle")) return;
          cancel(); const p = locate(e); e.currentTarget.focus(); e.currentTarget.setPointerCapture(e.pointerId);
          marquee.current = { ...p, base: e.shiftKey ? selection : [], pointerId: e.pointerId, clientX: e.clientX, clientY: e.clientY };
        }}
        onPointerMove={(e) => { const m = marquee.current; if (!m || !e.currentTarget.hasPointerCapture(e.pointerId)) return; const p = locate(e); if (Math.abs(e.clientX-m.clientX)+Math.abs(e.clientY-m.clientY)>3) setBox({ x: Math.min(m.x,p.x), y: Math.min(m.y,p.y), right: Math.max(m.x,p.x), bottom: Math.max(m.y,p.y) }); }}
        onPointerUp={(e) => { const m = marquee.current; if (!m) return; const p = locate(e); if (Math.abs(e.clientX-m.clientX)+Math.abs(e.clientY-m.clientY)>3) {
          const next = [...new Set([...m.base, ...keys.filter((k) => k.at_ticks >= start && k.at_ticks <= start+span && x(k.at_ticks)>=Math.min(m.x,p.x) && x(k.at_ticks)<=Math.max(m.x,p.x) && y(k.value)>=Math.min(m.y,p.y) && y(k.value)<=Math.max(m.y,p.y)).map((k) => k.at_ticks)])];
          chooseSelection(next, next[0] ?? null);
        } else { chooseSelection(m.base, m.base[0] ?? null); seek(alignTime(start+(p.x-LEFT)/WIDTH*span, false)); } cancel(); }}
        onPointerCancel={cancel} onLostPointerCapture={() => { if (marquee.current) cancel(); }}
        onDoubleClick={(e) => { if ((e.target as Element).closest(".curve-key,.curve-handle")) return; const p = locate(e); if (p.x < LEFT || p.x > LEFT + WIDTH || p.y < TOP || p.y > TOP + HEIGHT) return; add(start + (p.x - LEFT) / WIDTH * span, high - (p.y - TOP) / HEIGHT * valueSpan); }}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); e.stopPropagation(); cancel(); chooseSelection(keys.map((k) => k.at_ticks), keys[0]?.at_ticks ?? null); return; }
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") {
            e.preventDefault(); e.stopPropagation();
            if (layerField) {
              // 复制/粘贴那条 clipboard 认的是片段自己的针；这条阶梯住在链里，硬搬会把两回事混成
              // 一份数，所以这一档明说不做，并给一条现在就走得通的路（检查器逐枚钉）。
              toast("warn", "这一层的针还不能跨片段搬", "这条阶梯住在调色链里，clipboard 认的是片段自己的针。要在另一段上也动它：选中那一层，按播放头逐枚钉。");
              return;
            }
            const copy = copyKeys(project.id, selectedKeys);
            rememberCopy(copy); setCopied(copy);
            svg.current?.focus();   // 针上还留着焦点时，紧跟的 Ctrl+V 会被 Chromium 当成页面粘贴吃掉：复制完把焦点交回画布
            if (copy) toast("info", `已复制 ${copy.keys.length} 枚 ${FIELD_LABEL[copy.property] ?? copy.property} 关键帧`, "Ctrl+V 会按播放头粘到当前片段；换了属性或换了工程就失效。");
            else toast("warn", "没有可复制的选区", "选中同一属性上的针再复制——一次只能搬一条属性。");
            return;
          }
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") {
            e.preventDefault(); e.stopPropagation();
            pasteNow();
            return;
          }
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); chooseSelection([], null); return; }
          if (["Delete", "Backspace"].includes(e.key)) { e.preventDefault(); e.stopPropagation(); remove(); return; }
          if (selectedKeys.length && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
            e.preventDefault(); e.stopPropagation(); const multiplier = e.shiftKey ? 10 : 1;
            svg.current?.focus();
            commitPoints(selectedKeys, translate(selectedKeys, (e.key === "ArrowLeft" ? -q : e.key === "ArrowRight" ? q : 0)*multiplier, (e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0)*field.step/field.factor*multiplier));
          }
        }}>
        <defs><clipPath id={clipPathId}><rect x={LEFT} y={TOP} width={WIDTH} height={HEIGHT} /></clipPath></defs>
        {[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}><line x1={LEFT} x2={LEFT + WIDTH} y1={TOP + ratio * HEIGHT} y2={TOP + ratio * HEIGHT} className="curve-grid" /><text x={LEFT - 8} y={TOP + ratio * HEIGHT + 4} textAnchor="end">{valueLabel(high - ratio * valueSpan)}</text><line x1={LEFT + ratio * WIDTH} x2={LEFT + ratio * WIDTH} y1={TOP} y2={TOP + HEIGHT} className="curve-grid" /><text x={LEFT + ratio * WIDTH} y={202} textAnchor={ratio === 0 ? "start" : ratio === 1 ? "end" : "middle"}>{((start + span * ratio) / TIMEBASE).toFixed(2)}s</text></g>)}
        <g clipPath={`url(#${clipPathId})`}>
          {graph ? <path className="curve-line" d={graph.path} transform={`matrix(${WIDTH * clip.duration_ticks / span} 0 0 ${-HEIGHT / valueSpan} ${LEFT - start / span * WIDTH} ${TOP + high / valueSpan * HEIGHT})`} /> : null}
          <line className="curve-head" x1={x(head)} x2={x(head)} y1={TOP} y2={TOP + HEIGHT} />
        </g>
        {keys.filter((k) => k.at_ticks >= start && k.at_ticks <= start + span).map((k) => <circle key={k.at_ticks} className={`curve-key${selectionSet.has(k.at_ticks) ? " selected" : ""}`} cx={x(k.at_ticks)} cy={y(k.value)} r={6} role="button" tabIndex={0} aria-label={`${field.label}关键帧 ${timecode(k.at_ticks, project.settings.frame_rate)} ${valueLabel(k.value)}`} aria-pressed={selectionSet.has(k.at_ticks)} aria-disabled={disabled}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); selectPoint(k.at_ticks, e.shiftKey); seek(k.at_ticks); } }}
          onPointerDown={(e) => { e.stopPropagation(); if (e.button !== 0) return; const points = e.shiftKey ? selectPoint(k.at_ticks, true) : selectionSet.has(k.at_ticks) ? selectedKeys : selectPoint(k.at_ticks); setSelectedAt(points.some((p) => p.at_ticks === k.at_ticks) ? k.at_ticks : points[0]?.at_ticks ?? null); seek(k.at_ticks); e.currentTarget.focus(); if (disabled || !points.some((p) => p.at_ticks === k.at_ticks)) return; const p = locate(e); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { point: k, points, ...p, revision: project.revision, projectId: project.id, moved: false, element: e.currentTarget, pointerId: e.pointerId, clientX: e.clientX, clientY: e.clientY }; }}
          onPointerMove={(e) => { if (!drag.current || !e.currentTarget.hasPointerCapture(e.pointerId)) return; setDrafts(proposedPoint(e)); }}
          onPointerUp={(e) => { const gesture = drag.current; if (!gesture) return; const next = proposedPoint(e); const moved = gesture.moved; cancel(); if (moved) { svg.current?.focus(); commitPoints(gesture.points, next, gesture.revision, gesture.projectId); } }}
          onPointerCancel={cancel} onLostPointerCapture={() => { if (drag.current) cancel(); }}><title>{timecode(k.at_ticks, project.settings.frame_rate)} · {valueLabel(k.value)} · {INTERPOLATIONS[k.interpolation]}</title></circle>)}
        {canHandle && point && nextPoint ? ([0, 1] as const).map((handle) => {
          const cx = x(point.at_ticks + (nextPoint.at_ticks-point.at_ticks) * (handle === 0 ? controls.x1 : controls.x2));
          const cy = y(point.value + (nextPoint.value-point.value) * (handle === 0 ? controls.y1 : controls.y2));
          const anchor = handle === 0 ? point : nextPoint;
          return <g key={`handle-${handle}`}><line className="curve-tangent" x1={x(anchor.at_ticks)} y1={y(anchor.value)} x2={cx} y2={cy} />
            <circle className="curve-handle" cx={cx} cy={cy} r={5} role="button" tabIndex={0} aria-label={handle === 0 ? "贝塞尔出点控制柄" : "贝塞尔入点控制柄"} aria-disabled={disabled}
              onPointerDown={(e) => { e.stopPropagation(); e.currentTarget.focus(); if (disabled || e.button !== 0) return; const location = locate(e); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { point, points: [point], right: nextPoint, handle, ...location, revision: project.revision, projectId: project.id, moved: false, element: e.currentTarget, pointerId: e.pointerId, clientX: e.clientX, clientY: e.clientY }; }}
              onPointerMove={(e) => { if (drag.current?.handle !== handle || !e.currentTarget.hasPointerCapture(e.pointerId)) return; setDrafts(proposedPoint(e)); }}
              onPointerUp={(e) => { const gesture = drag.current; if (!gesture || gesture.handle !== handle) return; const next = proposedPoint(e)[0]; const moved = gesture.moved; cancel(); if (moved) commit(gesture.point.at_ticks, next, gesture.revision, gesture.projectId); }}
              onPointerCancel={cancel} onLostPointerCapture={() => { if (drag.current) cancel(); }}
              onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); return; } if (!disabled && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); e.stopPropagation(); const axis = e.key === "ArrowLeft" || e.key === "ArrowRight" ? handle === 0 ? "x1" : "x2" : handle === 0 ? "y1" : "y2"; const step = (e.shiftKey ? .1 : .01) * (e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 1); commit(point.at_ticks, { ...point, bezier: { ...controls, [axis]: Math.max(axis.startsWith("x") ? 0 : -4, Math.min(axis.startsWith("x") ? 1 : 4, controls[axis] + step)) } }); } }} />
          </g>;
        }) : null}
        {drafts?.map((k, i) => <circle key={i} className={`curve-draft${collision ? " collision" : ""}`} cx={x(k.at_ticks)} cy={y(k.value)} r={7} />)}
        {box ? <rect className="curve-selection" x={box.x} y={box.y} width={box.right-box.x} height={box.bottom-box.y} /> : null}
      </svg>
      {!graph || error ? <span className="curve-status" role="status">{error || "正在计算曲线…"}</span> : null}
    </div>
    <fieldset disabled={disabled || Boolean(draft)} className="curve-bezier-fields">{selectedKeys.length === 1 && selected?.interpolation === "bezier" ? <>
      <span>当前点 → 下一点</span>
      {(["x1", "y1", "x2", "y2"] as const).map((axis) => <label key={axis}>{({ x1: "出点时间", y1: "出点数值", x2: "入点时间", y2: "入点数值" })[axis]} <CurveNumber label={`贝塞尔${axis}`} value={(selected.bezier ?? DEFAULT_BEZIER)[axis]*100} step={1} min={axis.startsWith("x") ? 0 : -400} max={axis.startsWith("x") ? 100 : 400} onCommit={(value) => commit(selected.at_ticks, { ...selected, bezier: { ...(selected.bezier ?? DEFAULT_BEZIER), [axis]: value/100 } })} />%</label>)}
      <span className="hint">{!nextPoint ? "末点暂无后续区间" : nextPoint.value === selected.value ? "两点数值相同，此段保持不变" : "拖动控制柄调整节奏；越界曲线会拒绝保存"}</span>
    </> : <span className="hint">{selectedKeys.length > 1 ? `已选 ${selectedKeys.length} 个关键帧 · 拖动或输入时间/数值整体平移，插值会应用到全部选中点。` : "Shift 点选 / 拖空白框选 / Ctrl+A 全选；单选贝塞尔点可编辑控制柄。"}</span>}</fieldset>
    <div className="curve-footer">
      <span className="mono">{point ? `${(point.at_ticks / TIMEBASE).toFixed(3)}s · ${valueLabel(point.value)}` : `${keys.length} 个关键帧`}</span>
      {selected ? <fieldset disabled={disabled || Boolean(draft)} className="curve-fields">
        <label>时间 <CurveNumber label="关键帧时间（秒）" value={selected.at_ticks / TIMEBASE} step={q / TIMEBASE} min={0} max={clip.duration_ticks / TIMEBASE} onCommit={(value) => commitPoints(selectedKeys, translate(selectedKeys, alignTime(value*TIMEBASE, false)-selected.at_ticks, 0))} /></label>
        <label>数值 <CurveNumber label="关键帧数值" value={selected.value * field.factor} step={field.step} min={field.min} max={field.max} onCommit={(value) => commitPoints(selectedKeys, translate(selectedKeys, 0, value/field.factor-selected.value))} /></label>
        <select className="input" aria-label="选中关键帧插值" value={selectedKeys.every((k) => k.interpolation === selected.interpolation) ? selected.interpolation : ""} onChange={(e) => commitPoints(selectedKeys, selectedKeys.map((k) => interpolationPoint(k, e.target.value as Keyframe["interpolation"])))}><option value="" disabled>混合插值</option>{Object.entries(INTERPOLATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      </fieldset> : <select className="input" aria-label="曲线新关键帧插值" value={newInterpolation} onChange={(e) => setNewInterpolation(e.target.value as Keyframe["interpolation"])}>{Object.entries(INTERPOLATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>}
      {zoom > 1 ? <input type="range" aria-label="曲线横向位置" min={0} max={clip.duration_ticks - span} step={1} value={start} onChange={(e) => { cancel(); setPan(Number(e.target.value)); }} /> : null}
      <span className="spacer" /><span className="hint">{collision ? "时间已被占用，松开不会覆盖" : disabled ? "锁轨或提交中，当前不可编辑" : draft ? "候选选区 · 松开保存，Esc 取消" : "框选/Shift 多选 · 方向键微调 · Shift 锁轴/10 倍步长 · Ctrl+C 复制、Ctrl+V 按播放头粘贴"}</span>
    </div>
  </>;
}

function CurveNumber({ label, value, step, min, max, onCommit }: { label: string; value: number; step: number; min: number; max: number; onCommit: (value: number) => void }) {
  const [text, setText] = useState(String(Number(value.toFixed(6)))); const cancelled = useRef(false);
  useEffect(() => setText(String(Number(value.toFixed(6)))), [value]);
  return <input className="input mono" aria-label={label} type="number" value={text} step={step} min={min} max={max} onChange={(e) => setText(e.target.value)} onBlur={() => {
    const next = bandEntry(text, value, { min, max }, cancelled.current);
    if (next !== null) onCommit(next);
    cancelled.current = false; setText(String(Number(value.toFixed(6))));
  }} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { cancelled.current = true; e.currentTarget.blur(); } }} />;
}
