import { useRef, useState } from "react";

import type { SpeedPoint } from "../engine";
import { frameTicks, humanDuration } from "../time";
import { editableProject, setClipSpeedCurve, useApp } from "../store";

const MAX_POINTS = 12;
const MAX_RATE = 400;
const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));

const PRESETS: { label: string; shape: (duration: number, step: number) => SpeedPoint[] }[] = [
  { label: "慢入", shape: (d) => [{ at_ticks: 0, percent: 25 }, { at_ticks: d, percent: 100 }] },
  { label: "慢出", shape: (d) => [{ at_ticks: 0, percent: 100 }, { at_ticks: d, percent: 25 }] },
  {
    label: "蒙太奇",
    shape: (d) => [
      { at_ticks: 0, percent: 100 },
      { at_ticks: Math.round(d / 3), percent: 25 },
      { at_ticks: Math.round(d * 2 / 3), percent: 25 },
      { at_ticks: d, percent: 100 },
    ],
  },
  {
    label: "冻结结尾",
    shape: (d, q) => {
      const hold = clamp(Math.round(d * 0.75 / q) * q, q, d - q);
      return [
        { at_ticks: 0, percent: 100 },
        { at_ticks: hold - q, percent: 100 },
        { at_ticks: hold, percent: 0 },
        { at_ticks: d, percent: 0 },
      ];
    },
  },
];

/** Rate over clip time. The engine turns this polyline into the constant-rate pieces both preview and export read. */
function SpeedPad({ points, duration, step, onCommit }: {
  points: SpeedPoint[]; duration: number; step: number; onCommit: (next: SpeedPoint[]) => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const draftRef = useRef<SpeedPoint[] | null>(null);
  const [draft, setDraft] = useState<SpeedPoint[] | null>(null);
  const gesture = useRef<number | null>(null);
  const shown = draft ?? points;

  const bounds = (index: number, source: SpeedPoint[]) => ({
    low: index === 0 ? 0 : source[index - 1].at_ticks + step,
    high: index === source.length - 1 ? duration : source[index + 1].at_ticks - step,
  });
  const snap = (value: number) => clamp(Math.round(value / step) * step, 0, duration);
  const read = (event: { clientX: number; clientY: number }): SpeedPoint => {
    const box = svg.current!.getBoundingClientRect();
    return {
      at_ticks: snap(((event.clientX - box.left) / box.width) * duration),
      percent: Math.round(clamp(1 - (event.clientY - box.top) / box.height, 0, 1) * MAX_RATE),
    };
  };
  const move = (index: number, next: SpeedPoint) => {
    const source = draftRef.current ?? points;
    const { low, high } = bounds(index, source);
    const at = clamp(snap(next.at_ticks), low, Math.max(low, high));
    const percent = clamp(next.percent, 0, MAX_RATE);
    draftRef.current = source.map((point, position) => (position === index ? { at_ticks: at, percent } : point));
    setDraft(draftRef.current);
  };

  const x = (point: SpeedPoint) => (duration ? point.at_ticks / duration : 0) * 200;
  const y = (point: SpeedPoint) => 100 - (point.percent / MAX_RATE) * 100;

  return <div className="speed-pad">
    <svg ref={svg} className="speed-svg" viewBox="0 0 200 100" preserveAspectRatio="none" tabIndex={0} role="img" aria-label="曲线变速编辑器"
      onPointerDown={(e) => {
        const point = read(e);
        let best = 0;
        let distance = Infinity;
        shown.forEach((candidate, index) => {
          const gap = Math.hypot(x(candidate) - point.at_ticks / duration * 200, y(candidate) - (100 - point.percent / MAX_RATE * 100));
          if (gap < distance) { distance = gap; best = index; }
        });
        setSelected(best);
        if (distance > 12) { gesture.current = null; return; }
        gesture.current = best;
        e.currentTarget.setPointerCapture(e.pointerId);
        move(best, point);
      }}
      onPointerMove={(e) => { if (gesture.current !== null) move(gesture.current, read(e)); }}
      onPointerUp={() => {
        const final = draftRef.current;
        if (gesture.current !== null && final) onCommit(final);
        gesture.current = null;
        draftRef.current = null;
        setDraft(null);
      }}
      onPointerCancel={() => { gesture.current = null; draftRef.current = null; setDraft(null); }}
      onDoubleClick={(e) => {
        if (shown.length >= MAX_POINTS) return;
        const point = read(e);
        if (shown.some((candidate) => Math.abs(candidate.at_ticks - point.at_ticks) < step)) return;
        const index = shown.filter((candidate) => candidate.at_ticks < point.at_ticks).length;
        if (index === 0 || index === shown.length) return;
        const next = [...shown.slice(0, index), point, ...shown.slice(index)];
        onCommit(next.map((entry) => ({ ...entry })));
        setSelected(index);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") { gesture.current = null; draftRef.current = null; setDraft(null); return; }
        if (selected === null) return;
        const source = draftRef.current ?? points;
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          const { low, high } = bounds(selected, source);
          const target = clamp(source[selected].at_ticks + (e.key === "ArrowRight" ? step : -step) * (e.shiftKey ? 5 : 1), low, Math.max(low, high));
          onCommit(source.map((point, index) => (index === selected ? { ...point, at_ticks: target } : point)));
        } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          const target = clamp(source[selected].percent + (e.key === "ArrowUp" ? 5 : -5) * (e.shiftKey ? 4 : 1), 0, MAX_RATE);
          onCommit(source.map((point, index) => (index === selected ? { ...point, percent: target } : point)));
        } else if ((e.key === "Delete" || e.key === "Backspace") && source.length > 2) {
          e.preventDefault();
          onCommit(source.filter((_, index) => index !== selected));
          setSelected(null);
        }
      }}>
      <line x1="0" y1={100 - 100 / MAX_RATE * 100} x2="200" y2={100 - 100 / MAX_RATE * 100} className="curve-diagonal" />
      {[25, 50, 75].map((value) => <line key={value} x1="0" y1={100 - value} x2="200" y2={100 - value} className="curve-grid" />)}
      <polyline points={shown.map((point) => `${x(point)},${y(point)}`).join(" ")} className="curve-line" vectorEffect="non-scaling-stroke" />
      {shown.map((point, index) => <circle key={index} cx={x(point)} cy={y(point)} r={index === selected ? 4 : 3} className={index === selected ? "curve-point active" : "curve-point"} vectorEffect="non-scaling-stroke" />)}
    </svg>
    <div className="speed-side">
      {selected !== null && shown[selected] ? <>
        <p className="hint mono">第 {selected + 1} 点 · {humanDuration(shown[selected].at_ticks)} · {shown[selected].percent}%</p>
        <button className="btn tiny" disabled={shown.length <= 2} onClick={() => { onCommit(shown.filter((_, index) => index !== selected)); setSelected(null); }}>删除控制点</button>
      </> : null}
      <p className="hint">横向是片段时间，纵向是 0–400% 速率；双击加控制点，方向键微调，Delete 删除选中点。</p>
    </div>
  </div>;
}

/** 曲线变速：一条折线，引擎编译成分段恒定速率，导出与预览共用同一份分段。 */
export function SpeedFields({ clipId }: { clipId: string }) {
  const app = useApp();
  const project = editableProject(app);
  const clip = project?.clips[clipId];
  const asset = clip ? project?.assets[clip.asset_id] : undefined;
  const track = project?.tracks.find((entry) => entry.id === clip?.track_id);
  const points = clip?.speed_curve ?? null;
  const locked = Boolean(app.busy || !project || track?.locked);
  if (!clip || !asset || !project) return null;
  if (asset.kind === "image" || asset.kind === "text" || Boolean(asset.sequence_id))
    return <details className="insp-section speed-section">
      <summary className="panel-label">曲线变速</summary>
      <p className="hint">曲线变速只适用于视频与音频片段；图片、文字和嵌套合成按整段速率播放。</p>
    </details>;
  const step = frameTicks(project.settings.frame_rate);
  const duration = Math.max(step, Math.round(clip.duration_ticks / step) * step);
  const write = (next: SpeedPoint[] | null) => setClipSpeedCurve(clipId, next);
  const snap = (list: SpeedPoint[]) => {
    const kept: SpeedPoint[] = [];
    for (const point of list) {
      const entry = {
        at_ticks: clamp(Math.round(point.at_ticks / step) * step, 0, clip.duration_ticks),
        percent: clamp(point.percent, 0, MAX_RATE),
      };
      // Offsets must strictly increase, and the head and tail of the curve are load-bearing.
      if (kept.length && entry.at_ticks <= kept[kept.length - 1].at_ticks) continue;
      kept.push(entry);
    }
    return kept;
  };

  return <details className="insp-section speed-section" open={Boolean(points)}>
    <summary className="panel-label">曲线变速{points ? ` · ${points.length} 个点` : ""}</summary>
    <fieldset className="effects-fields" disabled={locked}>
      <div className="batch-actions">
        {PRESETS.map((preset) => <button key={preset.label} className="btn tiny" onClick={() => write(snap(preset.shape(duration, step)))}>{preset.label}</button>)}
        {points ? <button className="btn tiny danger" onClick={() => write(null)}>关闭曲线</button> : null}
      </div>
      {points ? <>
        <SpeedPad points={points} duration={clip.duration_ticks} step={step} onCommit={(next) => write(snap(next))} />
        <p className="hint">变速后的素材读取长度由引擎校验，超出素材会在写入时就拒绝。基础「播放速度」仍会等比缩放这条曲线。</p>
      </> : <p className="hint">未启用。选一个预设开始，或先在上方设置基础播放速度。</p>}
    </fieldset>
  </details>;
}
