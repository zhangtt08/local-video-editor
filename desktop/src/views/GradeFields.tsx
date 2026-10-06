import { useEffect, useRef, useState } from "react";

import {DEFAULT_TRANSFER, COLOR_SPACES, DEFAULT_CURVE_POINTS, DEFAULT_WHEELS, type GradeChannel, type GradeCurvePoint, type GradeNode, type ColorSpace, BLEND_MODES, blendLabel, type BlendMode} from "../engine";
import { editableProject, setClipColor, useApp } from "../store";

const CHANNELS: [GradeChannel, string][] = [["rgb", "主色"], ["red", "红"], ["green", "绿"], ["blue", "蓝"]];
const NODE_NAMES: Record<GradeNode["kind"], string> = {
  curve: "色调曲线",
  white_balance: "白平衡",
  wheels: "RGB 增益",
  transfer: "色彩空间",
};
const GREEN_MAGENTA = [0.70710678, -0.70710678, 0];
const BLUE_YELLOW = [0.40824829, 0.40824829, -0.81649758];
const MAX_NODES = 8;
const MAX_POINTS = 16;

function clamp(value: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, value));
}

function round(value: number) {
  return Math.round(value * 10000) / 10000;
}

function Num({ id, label, value, min, max, step, unit, onCommit }: { id: string; label: string; value: number; min: number; max: number; step: number; unit?: string; onCommit: (value: number) => void }) {
  const [text, setText] = useState(value.toFixed(2));
  const escaped = useRef(false);
  useEffect(() => setText(value.toFixed(2)), [value]);
  return <div className="effect-row"><label htmlFor={id}>{label}</label>
    <input id={id} className="input mono" type="number" min={min} max={max} step={step} value={text} disabled={!Number.isFinite(value)}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (escaped.current) { escaped.current = false; setText(value.toFixed(2)); return; }
        const parsed = Number(text);
        if (text.trim() && Number.isFinite(parsed)) {
          const next = clamp(parsed, min, max);
          if (next !== value) onCommit(next);
          setText(next.toFixed(2));
        } else setText(value.toFixed(2));
      }}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { escaped.current = true; e.currentTarget.blur(); } }} />
    <span className="dim">{unit ?? ""}</span></div>;
}

/** DaVinci-style chroma pad: horizontal is green/magenta, vertical is blue/yellow, one gesture is one revision. */
function WheelPad({ values, base, span, lo, hi, onCommit }: { values: number[]; base: number; span: number; lo: number; hi: number; onCommit: (next: number[]) => void }) {
  const pad = useRef<HTMLDivElement>(null);
  const origin = useRef<number[] | null>(null);
  const draftRef = useRef<number[] | null>(null);
  const [draft, setDraft] = useState<number[] | null>(null);
  const shown = draft ?? values;
  const projection = shown.map((_, index) => {
    const delta = (shown[index] - base) / span;
    return { x: delta * GREEN_MAGENTA[index], y: -delta * BLUE_YELLOW[index] };
  });
  const offset = clamp(Math.hypot(projection.reduce((sum, p) => sum + p.x, 0), projection.reduce((sum, p) => sum + p.y, 0)), 0, 1);
  const angle = Math.atan2(projection.reduce((sum, p) => sum + p.y, 0), projection.reduce((sum, p) => sum + p.x, 0));
  const dot = { left: `${50 + Math.cos(angle) * offset * 46}%`, top: `${50 + Math.sin(angle) * offset * 46}%` };

  const resolve = (event: React.PointerEvent, from: number[]) => {
    const box = pad.current!.getBoundingClientRect();
    const px = clamp(((event.clientX - box.left) / box.width) * 2 - 1, -1, 1);
    const py = clamp(1 - ((event.clientY - box.top) / box.height) * 2, -1, 1);
    const scale = Math.hypot(px, py) > 1 ? 1 / Math.hypot(px, py) : 1;
    return from.map((_, index) => round(clamp(base + span * scale * (px * GREEN_MAGENTA[index] + py * BLUE_YELLOW[index]), lo, hi)));
  };
  const track = (next: number[] | null) => { draftRef.current = next; setDraft(next); };

  return <div className="wheel-pad" ref={pad} role="presentation"
    onPointerDown={(e) => { origin.current = values.slice(); e.currentTarget.setPointerCapture(e.pointerId); track(resolve(e, values)); }}
    onPointerMove={(e) => { if (origin.current) track(resolve(e, origin.current)); }}
    onPointerUp={() => {
      const final = draftRef.current;
      if (origin.current && final && final.some((value, index) => value !== origin.current![index])) onCommit(final);
      origin.current = null;
      track(null);
    }}
    onPointerCancel={() => { origin.current = null; track(null); }}>
    <span className="wheel-dot" style={dot} />
  </div>;
}

/** Transfer curve editor on the same control points the engine samples into the shared LUT. */
function CurvePad({ points, onCommit }: { points: GradeCurvePoint[]; onCommit: (next: GradeCurvePoint[]) => void }) {
  const svg = useRef<SVGSVGElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const draftRef = useRef<GradeCurvePoint[] | null>(null);
  const [draft, setDraft] = useState<GradeCurvePoint[] | null>(null);
  const gesture = useRef<number | null>(null);
  const shown = draft ?? points;

  const track = (next: GradeCurvePoint[] | null) => { draftRef.current = next; setDraft(next); };

  const at = (event: { clientX: number; clientY: number }): GradeCurvePoint => {
    const box = svg.current!.getBoundingClientRect();
    return {
      x: round(clamp((event.clientX - box.left) / box.width, 0, 1)),
      y: round(clamp(1.5 - ((event.clientY - box.top) / box.height) * 2, -0.5, 1.5)),
    };
  };

  const limits = (index: number, source: GradeCurvePoint[]) => {
    const low = index > 0 ? source[index - 1].x + 0.01 : 0;
    const high = index < source.length - 1 ? source[index + 1].x - 0.01 : 1;
    return { low, high };
  };

  const move = (index: number, next: GradeCurvePoint) => {
    const source = draftRef.current ?? points;
    const { low, high } = limits(index, source);
    track(source.map((point, position) => position === index ? { x: round(clamp(next.x, low, high)), y: round(clamp(next.y, -0.5, 1.5)) } : point));
  };

  return <div className="curve-pad">
    <svg ref={svg} className="curve-svg" viewBox="0 0 100 200" tabIndex={0} role="img" aria-label="调色曲线"
      onPointerDown={(e) => {
        const point = at(e);
        let best = 0;
        let distance = Infinity;
        shown.forEach((candidate, index) => {
          const gap = Math.hypot(candidate.x * 100 - point.x * 100, (1.5 - candidate.y) * 100 - (1.5 - point.y) * 100);
          if (gap < distance) { distance = gap; best = index; }
        });
        setSelected(best);
        if (distance > 9) { gesture.current = null; return; }
        gesture.current = best;
        e.currentTarget.setPointerCapture(e.pointerId);
        move(best, point);
      }}
      onPointerMove={(e) => { if (gesture.current !== null) move(gesture.current, at(e)); }}
      onPointerUp={() => {
        const final = draftRef.current;
        if (gesture.current !== null && final) onCommit(final);
        gesture.current = null;
        track(null);
      }}
      onDoubleClick={(e) => {
        if (shown.length >= MAX_POINTS) return;
        const point = at(e);
        if (shown.some((candidate) => Math.abs(candidate.x - point.x) < 0.02)) return;
        const index = shown.filter((candidate) => candidate.x < point.x).length;
        const next = [...shown.slice(0, index), point, ...shown.slice(index)];
        onCommit(next.map((entry) => ({ x: entry.x, y: entry.y })));
        setSelected(index);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") { track(null); gesture.current = null; return; }
        if (selected === null) return;
        const step = e.shiftKey ? 0.05 : 0.01;
        const source = draftRef.current ?? points;
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          const { low, high } = limits(selected, source);
          const target = clamp(source[selected].x + (e.key === "ArrowRight" ? step : -step), low, high);
          onCommit(source.map((point, index) => (index === selected ? { ...point, x: round(target) } : point)));
        } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          const target = clamp(source[selected].y + (e.key === "ArrowUp" ? step : -step), -0.5, 1.5);
          onCommit(source.map((point, index) => (index === selected ? { ...point, y: round(target) } : point)));
        } else if ((e.key === "Delete" || e.key === "Backspace") && source.length > 2) {
          e.preventDefault();
          onCommit(source.filter((_, index) => index !== selected));
          setSelected(null);
        }
      }}>
      <line x1="0" y1="200" x2="100" y2="0" className="curve-diagonal" />
      {[0.25, 0.5, 0.75].map((value) => <line key={value} x1="0" y1={(1.5 - value) * 100} x2="100" y2={(1.5 - value) * 100} className="curve-grid" />)}
      <polyline points={shown.map((point) => `${point.x * 100},${(1.5 - point.y) * 100}`).join(" ")} className="curve-line" />
      {shown.map((point, index) => <circle key={index} cx={point.x * 100} cy={(1.5 - point.y) * 100} r={index === selected ? 4.5 : 3.5} className={index === selected ? "curve-point active" : "curve-point"} />)}
    </svg>
    <div className="curve-side">
      {selected !== null && shown[selected] ? <>
        <Num id={`curve-x-${selected}`} label="输入" value={shown[selected].x * 100} min={0} max={100} step={1} unit="%"
          onCommit={(value) => {
            const { low, high } = limits(selected, points);
            onCommit(points.map((point, index) => index === selected ? { ...point, x: round(clamp(value / 100, low, high)) } : point));
          }} />
        <Num id={`curve-y-${selected}`} label="输出" value={shown[selected].y * 100} min={-50} max={150} step={1} unit="%"
          onCommit={(value) => onCommit(shown.map((point, index) => index === selected ? { ...point, y: round(clamp(value / 100, -0.5, 1.5)) } : point))} />
        <button className="btn tiny" disabled={shown.length <= 2} onClick={() => { onCommit(shown.filter((_, index) => index !== selected)); setSelected(null); }}>删除控制点</button>
      </> : <p className="hint">拖动控制点，双击加一个点，方向键微调，Delete 删除选中点。</p>}
    </div>
  </div>;
}

/** 调色节点：一条串行链，引擎把它编译成每通道一张表，预览与导出共用。 */
export function GradeFields({ clipId }: { clipId: string }) {
  const app = useApp();
  const project = editableProject(app);
  const [active, setActive] = useState(0);
  const pending = useRef<number | null>(null);
  const clip = project?.clips[clipId];
  const nodes = clip?.color?.grade ?? [];
  const locked = Boolean(app.busy || !project || project.tracks.find((track) => track.id === clip?.track_id)?.locked);

  useEffect(() => {
    if (pending.current !== null && nodes.length > pending.current) {
      setActive(pending.current);
      pending.current = null;
    } else if (active >= nodes.length) {
      setActive(Math.max(0, nodes.length - 1));
    }
  }, [active, nodes.length]);

  const write = (next: GradeNode[]) => setClipColor(clipId, { grade: next });
  const replace = (index: number, node: GradeNode) => write(nodes.map((entry, position) => position === index ? node : entry));
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= nodes.length) return;
    const next = nodes.slice();
    next.splice(target, 0, next.splice(index, 1)[0]);
    write(next);
    setActive(target);
  };
  const add = (kind: GradeNode["kind"]) => {
    if (nodes.length >= MAX_NODES) return;
    const node: GradeNode = kind === "curve"
      ? { kind: "curve", channel: "rgb", points: DEFAULT_CURVE_POINTS.map((point) => ({ ...point })), enabled: true }
      : kind === "white_balance"
        ? { kind: "white_balance", temperature: 0, tint: 0, enabled: true }
        : kind === "transfer"
          ? { kind: "transfer", ...DEFAULT_TRANSFER, enabled: true }
          : { kind: "wheels", lift: [...DEFAULT_WHEELS.lift], gamma: [...DEFAULT_WHEELS.gamma], gain: [...DEFAULT_WHEELS.gain], enabled: true };
    write([...nodes, node]);
    pending.current = nodes.length;
  };

  const current = nodes[active];

  return <details className="insp-section grade-section" open={nodes.length > 0}>
    <summary className="panel-label">调色节点{nodes.length ? ` · ${nodes.length} 个` : ""}</summary>
    <fieldset className="effects-fields" disabled={locked}>
      <div className="batch-actions">
        {(["curve", "white_balance", "wheels", "transfer"] as const).map((kind) => <button key={kind} className="btn tiny" disabled={nodes.length >= MAX_NODES} onClick={() => add(kind)}>+{NODE_NAMES[kind]}</button>)}
      </div>
      {nodes.length ? <div className="grade-list" role="list">
        {nodes.map((node, index) => <div className="grade-row" key={index} role="listitem">
          <button className={`grade-pick${index === active ? " active" : ""}`} onClick={() => setActive(index)} aria-label={`选择${NODE_NAMES[node.kind]}节点`}>{index + 1}. {NODE_NAMES[node.kind]}{node.blend && node.blend !== "normal" ? ` · ${blendLabel(node.blend)}` : ""}{node.mix === undefined || node.mix === 1 ? "" : ` · ${Math.round(node.mix * 100)}%`}</button>
          <label className="grade-switch"><input type="checkbox" checked={node.enabled} onChange={(e) => replace(index, { ...node, enabled: e.target.checked })} />启用</label>
          <button className="btn tiny" disabled={index === 0} onClick={() => move(index, -1)} aria-label="上移节点">↑</button>
          <button className="btn tiny" disabled={index === nodes.length - 1} onClick={() => move(index, 1)} aria-label="下移节点">↓</button>
          <button className="btn tiny danger" onClick={() => { write(nodes.filter((_, position) => position !== index)); setActive(Math.max(0, index - 1)); }} aria-label="移除节点">删</button>
        </div>)}
      </div> : <p className="hint">曝光、对比度、饱和度之后按顺序执行这些节点。曲线、白平衡、RGB 增益与色彩空间都只改每通道值，预览与导出共用同一张表。</p>}

      {current?.kind === "curve" ? <div className="grade-body">
        <label className="mask-shape">通道 <select className="input" aria-label="曲线通道" value={current.channel} onChange={(e) => replace(active, { ...current, channel: e.target.value as GradeChannel })}>{CHANNELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <CurvePad points={current.points} onCommit={(points) => replace(active, { ...current, points })} />
        <p className="hint">{current.channel === "rgb" ? "主色曲线同时作用于三个通道" : `只改${CHANNELS.find(([value]) => value === current.channel)?.[1]}通道`}，共 {current.points.length} 个点。</p>
      </div> : null}

      {current?.kind === "white_balance" ? <div className="grade-body">
        <Num id="grade-temp" label="色温" value={current.temperature * 100} min={-100} max={100} step={1} unit="±" onCommit={(value) => replace(active, { ...current, temperature: round(value / 100) })} />
        <Num id="grade-tint" label="色调" value={current.tint * 100} min={-100} max={100} step={1} unit="±" onCommit={(value) => replace(active, { ...current, tint: round(value / 100) })} />
        <p className="hint">正值偏暖，色调正值偏绿；按通道增益实现，不做色彩管理转换。</p>
      </div> : null}

      {current?.kind === "transfer" ? <div className="grade-body">
        <label className="mask-shape">输入色彩空间 <select className="input" aria-label="输入色彩空间" value={current.input_space} onChange={(e) => replace(active, { ...current, input_space: e.target.value as ColorSpace })}>{COLOR_SPACES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="mask-shape">输出色彩空间 <select className="input" aria-label="输出色彩空间" value={current.output_space} onChange={(e) => replace(active, { ...current, output_space: e.target.value as ColorSpace })}>{COLOR_SPACES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <p className="hint">只换算传递函数（gamma / sRGB / BT.1886），不动色域基色也不做矩阵变换：手机素材与屏幕录制是 sRGB，广播时间线是 BT.1886（等于 gamma 2.4），这一节把前者的暗部按发布标准抬到后者。预览与导出共用同一张每通道表，暗部拐点用自适应打点，误差不超过半个色阶。</p>
      </div> : null}

      {current?.kind === "wheels" ? <div className="grade-body wheels-body">
        {([["lift", "阴影", 0, -0.5, 0.5, 0.5], ["gamma", "中间调", 1, 0.1, 10, 0.5], ["gain", "亮部", 1, 0, 4, 0.5]] as const).map(([field, label, base, lo, hi, span]) => <div className="wheel-group" key={field}>
          <WheelPad values={current[field]} base={base} span={span} lo={lo} hi={hi} onCommit={(next) => replace(active, { ...current, [field]: next.map(round) })} />
          <span className="panel-label">{label}</span>
          {(["红", "绿", "蓝"] as const).map((name, index) => <Num key={name} id={`grade-${field}-${index}`} label={name} value={current[field][index] - base} min={lo - base} max={hi - base} step={0.01} onCommit={(value) => { const next = current[field].slice(); next[index] = round(value + base); replace(active, { ...current, [field]: next }); }} />)}
        </div>)}
        <p className="hint">圆盘左绿右品红、上黄下蓝，只改彩度；要整体提亮请用右侧数值。达芬奇式的色轮盘面方向一致，但这里不是完整的色彩管理。</p>
      </div> : null}

      {current ? <div className="grade-body">
        <label className="mask-shape">混合方式
          <select className="input" aria-label="节点混合方式" value={current.blend ?? "normal"} onChange={(e) => replace(active, { ...current, blend: e.target.value as BlendMode })}>
            {BLEND_MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <Num id={`grade-mix-${active}`} label="节点强度" value={(current.mix ?? 1) * 100} min={0} max={100} step={5} unit="%"
          onCommit={(value) => replace(active, { ...current, mix: round(value / 100) })} />
        <p className="hint">强度把该节点的结果与它的输入按比例混合，0% 等于跳过该节点；达芬奇的 Mix 语义，预览与导出仍共用同一张每通道表。</p>
      </div> : null}

      {nodes.length ? <button className="btn tiny" onClick={() => write([])}>清空调色节点</button> : null}
    </fieldset>
  </details>;
}
