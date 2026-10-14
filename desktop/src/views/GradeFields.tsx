import { Fragment, useEffect, useRef, useState } from "react";

import { branchBlend, DEFAULT_COMPOSITE, branchTree, branchWeight, blendsAfterAdd, blendsAfterPick, blendsAfterRemove, chainFieldsFor, mapMixer, mixerAt, NODE_NAMES, cardsFor, moveWithin, resolveMixerPath, weightsAfterAdd, weightsAfterRemove, weightsAfterWeight, type GraphLane } from "../gradeGraph";
import {blendLabel, DEFAULT_TRANSFER, COLOR_SPACES, DEFAULT_CURVE_POINTS, DEFAULT_WHEELS, type GradeBranch, type GradeCapacity, type GradeChannel, type GradeCurvePoint, type GradeNode, type GradeOperation, type GradeParallel, type ColorSpace, type ClipColorSpaceReport, BLEND_MODES, type BlendMode} from "../engine";
import { applyGradeToTrack, editableProject, setClipColor, useApp, applyLut, autoGradeClip, colorManageClip, fetchGradeCapacity, readClipColorSpace } from "../store";
import { autoSourceBlocker, autoSourceOffered, colorSpaceWords, handPickLive, handPickWords, managedPair, managedWords, manageFits, manageSourceValue, manageSpaces, shouldReadColorSpace, taggedCount, transferTagWords, type ColorSpacePhase } from "../colorManage";
import { autoGradeBlocker, gradeCapacityLine } from "../effects";
import { foldBlocker, foldedRow, foldIn, foldWords, usableRows } from "../gamutFold";

const CHANNELS: [GradeChannel, string][] = [["rgb", "主色"], ["red", "红"], ["green", "绿"], ["blue", "蓝"]];
const GREEN_MAGENTA = [0.70710678, -0.70710678, 0];
const BLUE_YELLOW = [0.40824829, 0.40824829, -0.81649758];
/** 链子上限的唯一主人是引擎的 `capabilities.grade_limits`；下面这些数只在引擎没有回该字段时兜底。 */
const FALLBACK_NODES = 8;
const FALLBACK_POINTS = 16;
const FALLBACK_BRANCHES = 4;
const FALLBACK_WEIGHT = 2;
const FALLBACK_LEVELS = { blackMax: 0.9, whiteMin: 0.1, gammaMin: 0.1, gammaMax: 10 };
const FALLBACK_MATRIX_LIMIT = 4;
const FALLBACK_MIXER_DEPTH = 3;
const FALLBACK_TREE_OPERATIONS = FALLBACK_NODES;
/** 通道混合的三行三列与几个起手式：预设只是把九个框填成一组常用数，改完仍然是普通节点。 */
const MATRIX_ROWS = ["输出红", "输出绿", "输出蓝"];
const MATRIX_COLUMNS = ["来自红", "来自绿", "来自蓝"];
const MATRIX_PRESETS: [string, number[]][] = [
  ["恒等", [1, 0, 0, 0, 1, 0, 0, 0, 1]],
  ["灰度 BT.709", [0.2126, 0.7152, 0.0722, 0.2126, 0.7152, 0.0722, 0.2126, 0.7152, 0.0722]],
  ["青橙", [1.05, 0.18, -0.08, -0.06, 1.02, 0.04, -0.12, -0.06, 1.06]],
];

export type GradeLimits = {
  nodes: number;
  points: number;
  branches: number;
  weightMax: number;
  /** 1.124：一棵树最多几层、一个节点底下最多几个操作，也是引擎下发。 */
  mixerDepth?: number;
  treeOperations?: number;
  blackMax?: number;
  whiteMin?: number;
  gammaMin?: number;
  gammaMax?: number;
  matrixLimit?: number;
};

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
function CurvePad({ points, maxPoints, onCommit }: { points: GradeCurvePoint[]; maxPoints: number; onCommit: (next: GradeCurvePoint[]) => void }) {
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
        if (shown.length >= maxPoints) return;
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

/** 一个操作的编辑控件：曲线、白平衡、色彩空间、RGB 增益、LUT。串行节点与并联分支共用这一套。 */
function OpFields({ node, idPrefix, limits, onReplace, onCommit }: { node: GradeNode; idPrefix: string; limits: GradeLimits; onReplace?: () => void; onCommit: (next: GradeNode) => void }) {
  if (node.kind === "curve") {
    return <div className="grade-body">
      <label className="mask-shape">通道 <select className="input" aria-label="曲线通道" value={node.channel} onChange={(e) => onCommit({ ...node, channel: e.target.value as GradeChannel })}>{CHANNELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <CurvePad points={node.points} maxPoints={limits.points} onCommit={(points) => onCommit({ ...node, points })} />
      <p className="hint">{node.channel === "rgb" ? "主色曲线同时作用于三个通道" : `只改${CHANNELS.find(([value]) => value === node.channel)?.[1]}通道`}，共 {node.points.length} 个点（上限 {limits.points} 个）。</p>
    </div>;
  }
  if (node.kind === "white_balance") {
    return <div className="grade-body">
      <Num id={`${idPrefix}-temp`} label="色温" value={node.temperature * 100} min={-100} max={100} step={1} unit="±" onCommit={(value) => onCommit({ ...node, temperature: round(value / 100) })} />
      <Num id={`${idPrefix}-tint`} label="色调" value={node.tint * 100} min={-100} max={100} step={1} unit="±" onCommit={(value) => onCommit({ ...node, tint: round(value / 100) })} />
      <p className="hint">正值偏暖，色调正值偏绿；按通道增益实现，不做色彩管理转换。</p>
    </div>;
  }
  if (node.kind === "matrix") {
    const limit = limits.matrixLimit ?? FALLBACK_MATRIX_LIMIT;
    const set = (index: number, value: number) => {
      const next = node.coefficients.slice();
      next[index] = round(value);
      onCommit({ ...node, coefficients: next });
    };
    return <div className="grade-body matrix-body">
      <div className="batch-actions">
        {MATRIX_PRESETS.map(([label, coefficients]) => <button key={label} className="btn tiny" onClick={() => onCommit({ ...node, coefficients: coefficients.map((value) => round(value)) })}>{label}</button>)}
      </div>
      {MATRIX_ROWS.map((rowName, row) => <div className="matrix-row" key={rowName}>
        <span className="panel-label">{rowName}</span>
        {[0, 1, 2].map((column) => <Num key={column} id={`${idPrefix}-matrix-${row}-${column}`} label={MATRIX_COLUMNS[column]} value={node.coefficients[row * 3 + column] ?? 0} min={-limit} max={limit} step={0.01} onCommit={(value) => set(row * 3 + column, value)} />)}
      </div>)}
      <p className="hint">每一行说「这个输出通道由多少红、多少绿、多少蓝组成」，九个数直接乘在画面的存储值上，不做线性光换算——所以它是通道混合与风格化偏色的工具，不是色彩管理。导出走 FFmpeg 的 colorchannelmixer，预览走同一组数的 SVG feColorMatrix（滤镜已声明 sRGB 插值），两端读同一份矩阵。想整体去色就点「灰度 BT.709」，想只动一个通道就把别的行留成 0。</p>
    </div>;
  }
  if (node.kind === "levels") {
    const blackMax = Math.round((limits.blackMax ?? FALLBACK_LEVELS.blackMax) * 255);
    const whiteMin = Math.round((limits.whiteMin ?? FALLBACK_LEVELS.whiteMin) * 255);
    return <div className="grade-body">
      <label className="mask-shape">通道 <select className="input" aria-label="色阶通道" value={node.channel} onChange={(e) => onCommit({ ...node, channel: e.target.value as GradeChannel })}>{CHANNELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <Num id={`${idPrefix}-levels-black`} label="输入黑场" value={node.black * 255} min={0} max={blackMax} step={1} unit="/255" onCommit={(value) => onCommit({ ...node, black: round(value / 255), white: Math.max(node.white, round(Math.min(255, value + 1) / 255)) })} />
      <Num id={`${idPrefix}-levels-white`} label="输入白场" value={node.white * 255} min={whiteMin} max={255} step={1} unit="/255" onCommit={(value) => onCommit({ ...node, white: round(value / 255), black: Math.min(node.black, round(Math.max(0, value - 1) / 255)) })} />
      <Num id={`${idPrefix}-levels-gamma`} label="中间调" value={node.gamma} min={limits.gammaMin ?? FALLBACK_LEVELS.gammaMin} max={limits.gammaMax ?? FALLBACK_LEVELS.gammaMax} step={0.05} onCommit={(value) => onCommit({ ...node, gamma: round(value) })} />
      <p className="hint">低于输入黑场的直接压成纯黑，高于输入白场的抬到纯白，中间调在两点之间挪位置，两个端点不动。引擎按发布公式把它采样成每通道一张表，预览的 feComponentTransfer 与导出的 lutrgb 读的是同一条折线，逐点误差不超过一个色阶（tests/autograde_check.py 把 256 级全量比过）。</p>
    </div>;
  }
  if (node.kind === "transfer") {
    return <div className="grade-body">
      <label className="mask-shape">输入色彩空间 <select className="input" aria-label="输入色彩空间" value={node.input_space} onChange={(e) => onCommit({ ...node, input_space: e.target.value as ColorSpace })}>{COLOR_SPACES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="mask-shape">输出色彩空间 <select className="input" aria-label="输出色彩空间" value={node.output_space} onChange={(e) => onCommit({ ...node, output_space: e.target.value as ColorSpace })}>{COLOR_SPACES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <p className="hint">只换算传递函数（gamma / sRGB / BT.1886），不动色域基色也不做矩阵变换：手机素材与屏幕录制是 sRGB，广播时间线是 BT.1886（等于 gamma 2.4），这一节把前者的暗部按发布标准抬到后者。预览与导出共用同一张每通道表，暗部拐点用自适应打点，误差不超过半个色阶。</p>
    </div>;
  }
  if (node.kind === "lut") {
    return <div className="grade-body">
      <p className="hint">正在用「{node.title}」：三个通道各 {node.size} 个采样点，点与点之间线性插值。这张表是引擎解析 .cube 文件得到的，界面不自己读文件，预览和导出读同一组数。</p>
      {onReplace ? <button className="btn tiny" onClick={onReplace}>换一张 LUT</button> : null}
      <p className="hint">1D 表逐通道，所以预览与导出读同一张表。3D LUT（会把红绿蓝互相混在一起的那种）也支持了，但它在浏览器里没有对应的画法——导入它之后预览照旧，导出才生效，节点卡片上写着这一句。</p>
    </div>;
  }
  if (node.kind === "lut3d") {
    return <div className="grade-body">
      <p className="hint">正在用「{node.title}」：{node.size}³ 网格、共 {node.cells.length / 3} 个 RGB 格点，导出交给 FFmpeg 的 3D LUT 滤波并按四面体插值。</p>
      <p className="hint">这一张表按定义跨通道，浏览器没有能画它的原语，所以<b>预览不生效、导出生效</b>——与降噪一样是明说的差别，不是近似。它也没有强度与混合方式：只有一端能执行的强度不是强度。</p>
      {node.resampled_from ? <p className="hint">原文件是 {node.resampled_from}³，超出引擎存进工程状态的网格上限，导入时已按三线性插值重采样到 {node.size}³。</p> : null}
      {onReplace ? <button className="btn tiny" onClick={onReplace}>换一张 LUT</button> : null}
    </div>;
  }
  if (node.kind === "composite") {
    // 第二路画面：这一级的两个控件都在它自己身上，没有通用的「强度」可借——`mix` 是相合的权重，
    // `mode` 是相合的方式，而它必须排在 OpFields 这一层（`MixFields` 只挂在并联节点上，
    // 串行节点走的是这条分发；把它写在 MixFields 里就等于屏幕上根本没有那两个控件）。
    return <div className="grade-body">
      <label className="mask-shape">与原图相合的方式
        <select className="input" aria-label="叠一层原图的混合方式" value={node.mode} onChange={(e) => onCommit({ ...node, mode: e.target.value as BlendMode })}>
          {BLEND_MODES.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
        </select>
      </label>
      <Num id={`${idPrefix}-composite-mix`} label="这一层的权重" value={node.mix * 100} min={0} max={100} step={5} unit="%"
        onCommit={(value) => onCommit({ ...node, mix: round(value / 100) })} />
      <p className="hint">
        这一条边读两幅画：这条链<b>调完的结果</b>与<b>进来的那幅原图</b>。它在链里的位置不改变结果——
        其余节点照常串联，这一级按出现的顺序一次一次把原图叠上去。0% 就是只看原图，100% 就是只看调完的。
      </p>
      <p className="hint">浏览器的一条滤镜链没有第二个画面输入，所以<b>预览不生效、导出生效</b>——
        与 3D LUT 同一个口径：说不出口的差别才是骗人。要看到合成的效果，请把没调色的那份放到另一条
        画面轨上用轨道的混合方式相合。</p>
    </div>;
  }
  if (node.kind === "wheels") {
    return <div className="grade-body wheels-body">
      {([["lift", "阴影", 0, -0.5, 0.5, 0.5], ["gamma", "中间调", 1, 0.1, 10, 0.5], ["gain", "亮部", 1, 0, 4, 0.5]] as const).map(([field, label, base, lo, hi, span]) => <div className="wheel-group" key={field}>
        <WheelPad values={node[field]} base={base} span={span} lo={lo} hi={hi} onCommit={(next) => onCommit({ ...node, [field]: next.map(round) })} />
        <span className="panel-label">{label}</span>
        {(["红", "绿", "蓝"] as const).map((name, index) => <Num key={name} id={`${idPrefix}-${field}-${index}`} label={name} value={node[field][index] - base} min={lo - base} max={hi - base} step={0.01} onCommit={(value) => { const next = node[field].slice(); next[index] = round(value + base); onCommit({ ...node, [field]: next }); }} />)}
      </div>)}
      <p className="hint">圆盘左绿右品红、上黄下蓝，只改彩度；要整体提亮请用右侧数值。达芬奇式的色轮盘面方向一致，但这里不是完整的色彩管理。</p>
    </div>;
  }
  return null;
}

/** 强度与混合方式：节点有自己的一对，并联分支也有，语义相同——都只与该支/该节点的输入比较。 */
function MixFields({ node, idPrefix, label, onCommit }: { node: GradeNode; idPrefix: string; label: string; onCommit: (next: GradeNode) => void }) {
  if (node.kind === "lut3d" || node.kind === "composite") {
    // lut3d：契约里没有 mix 也没有 blend，这里不放控件，比放一个只有一端听的控制诚实。
    // composite：它那两个控件在 `OpFields` 里（串行节点走那条分发），而且契约不许它当一支，
    // 所以到不了这里——写在这里只会让 TS 以为这条通用支路认得它。
    return null;
  }
  return <div className="grade-body">
    {node.kind === "matrix" ? <p className="hint">通道混合没有「混合方式」可选：把矩阵用非线性模式（正片叠底之类）与它的输入混合，结果不再是矩阵，两端就没有同一份数可读了。要减弱效果请用下面的强度。</p> : <label className="mask-shape">混合方式
      <select className="input" aria-label={`${label}混合方式`} value={node.blend ?? "normal"} onChange={(e) => onCommit({ ...node, blend: e.target.value as BlendMode })}>
        {BLEND_MODES.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
      </select>
    </label>}
    <Num id={`${idPrefix}-mix`} label={`${label}强度`} value={(node.mix ?? 1) * 100} min={0} max={100} step={5} unit="%"
      onCommit={(value) => onCommit({ ...node, mix: round(value / 100) })} />
    <p className="hint">强度把该{label === "节点" ? "节点" : "支"}的结果与它的输入按比例混合，0% 等于跳过；达芬奇的 Mix 语义，预览与导出仍共用同一张每通道表。</p>
  </div>;
}

/** 新建一个操作：串行节点与并联分支的起点都一样，全部是「不动画面」的中性值。
 *  LUT 不在其中——一张查找表的内容只能来自文件，没有中性值可给，所以它由「+LUT」走引擎解析导入，
 *  类型上也排除掉：误把 "lut" 传进来会在编译期报错，而不是悄悄建出一个 RGB 增益节点。 */
function newOperation(kind: Exclude<GradeOperation["kind"], "lut">): GradeOperation {
  return kind === "curve"
    ? { kind: "curve", channel: "rgb", points: DEFAULT_CURVE_POINTS.map((point) => ({ ...point })), enabled: true }
    : kind === "white_balance"
      ? { kind: "white_balance", temperature: 0, tint: 0, enabled: true }
      : kind === "transfer"
        ? { kind: "transfer", ...DEFAULT_TRANSFER, enabled: true }
        : kind === "matrix"
        ? { kind: "matrix", coefficients: [1, 0, 0, 0, 1, 0, 0, 0, 1], enabled: true }
        : kind === "levels"
          ? { kind: "levels", channel: "rgb", black: 0, white: 1, gamma: 1, enabled: true }
          : { kind: "wheels", lift: [...DEFAULT_WHEELS.lift], gamma: [...DEFAULT_WHEELS.gamma], gain: [...DEFAULT_WHEELS.gain], enabled: true };
}

/** 一支套一台混频台时，卡片里那一行下面还有几行：同一套 `gg-lane` 样式，深度由嵌套给出。 */
function LaneList({ lanes }: { lanes: GraphLane[] }) {
  return <>{lanes.map((lane, index) => <span key={index} className={`gg-lane${lane.enabled ? "" : " off"}`}>
    {index + 1}. {lane.label}
    {lane.lanes?.length ? <span className="gg-lanes"><LaneList lanes={lane.lanes} /></span> : null}
  </span>)}</>;
}

/** 调色节点：串行链与并联分支，引擎都编译成每通道一张表，预览与导出共用。 */
export function GradeFields({ clipId }: { clipId: string }) {
  const app = useApp();
  const project = editableProject(app);
  const [active, setActive] = useState(0);
  const [branchSlot, setSlot] = useState(0);
  // 1.124：一支自己可以是一台混频台，所以「正在编辑哪一台」是一条支路路径，而不是一个下标。
  const [path, setPath] = useState<number[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const pending = useRef<number | null>(null);
  const dragging = useRef<number | null>(null);
  // 1.107：额度那一行读的是引擎算好的回执，并绑在当前 revision 上——数与版本对不上就不显示，
  //  宁可不写，也不写一个上一次的数。
  const [capacity, setCapacity] = useState<{ value: GradeCapacity; revision: number } | null>(null);
  const capacityProjectId = app.project?.id;
  const capacityRevision = app.project?.revision;
  useEffect(() => {
    if (!capacityProjectId || capacityRevision === undefined) { setCapacity(null); return; }
    let live = true;
    const wanted = capacityRevision;
    void fetchGradeCapacity(capacityProjectId).then((value) => {
      if (live && value) setCapacity({ value, revision: wanted });
    });
    return () => { live = false; };
  }, [capacityProjectId, capacityRevision]);
  const capacityLine = gradeCapacityLine(capacity, capacityRevision);
  const clip = project?.clips[clipId];
  const nodes = clip?.color?.grade ?? [];
  // 上限由引擎下发（1.55 的同一课）：界面不自己数一遍，就不会出现界面允许、引擎拒绝的节点。
  const limits: GradeLimits = {
    nodes: app.caps?.grade_limits?.max_nodes ?? FALLBACK_NODES,
    points: app.caps?.grade_limits?.max_curve_points ?? FALLBACK_POINTS,
    branches: app.caps?.grade_limits?.max_branches ?? FALLBACK_BRANCHES,
    weightMax: app.caps?.grade_limits?.branch_weight_max ?? FALLBACK_WEIGHT,
    mixerDepth: app.caps?.grade_limits?.max_mixer_depth ?? FALLBACK_MIXER_DEPTH,
    treeOperations: app.caps?.grade_limits?.max_tree_operations ?? FALLBACK_TREE_OPERATIONS,
    blackMax: app.caps?.grade_limits?.levels_black_max ?? FALLBACK_LEVELS.blackMax,
    whiteMin: app.caps?.grade_limits?.levels_white_min ?? FALLBACK_LEVELS.whiteMin,
    gammaMin: app.caps?.grade_limits?.levels_gamma_min ?? FALLBACK_LEVELS.gammaMin,
    gammaMax: app.caps?.grade_limits?.levels_gamma_max ?? FALLBACK_LEVELS.gammaMax,
    matrixLimit: app.caps?.grade_limits?.matrix_limit ?? FALLBACK_MATRIX_LIMIT,
  };
  const lutFile = useRef<HTMLInputElement>(null);
  const lutTarget = useRef<number | null>(null);
  const locked = Boolean(app.busy || !project || project.tracks.find((track) => track.id === clip?.track_id)?.locked);
  // 按了只会弹错的按钮不该亮着（1.82 立下的规矩）：能不能量画面只由 effects.ts 一处判断，出路写进 title。
  const assetKind = clip ? project?.assets[clip.asset_id]?.kind : undefined;
  const clipKind = clip ? (clip.text ? "text" : assetKind) : undefined;
  const trackKind = project?.tracks.find((track) => track.id === clip?.track_id)?.kind;
  const autoBlock = autoGradeBlocker(
    clipKind,
    assetKind,
    trackKind,
    Boolean(app.caps?.features.clip_auto_grade)
  );
  const [autoMode, setAutoMode] = useState<"luma" | "rgb">("luma");
  const [autoReplace, setAutoReplace] = useState(true);
  // 1.130：色彩管理那一行。名单、「装不装得下」和「现在套的是哪一对」都问同一份实现
  //  （../colorManage.ts），界面不自己数第二遍；两个下拉菜单的候选来自引擎的 capabilities。
  const spaces = manageSpaces(app.caps?.color_spaces, COLOR_SPACES);
  const spaceLabel = (name: ColorSpace) => spaces.find(([entry]) => entry === name)?.[1] ?? name;
  const managed = managedPair(nodes);
  const managedTagged = taggedCount(nodes);
  // 1.158：基色表那颗「折进来」。九个数字一律从 capabilities.gamut_matrices 搬，这里不出现任何一个
  //  系数、也不出现任何一个档位名（tests/gamutfold_check.py 逐字钉住）；能落的那一格只认色彩管理盖过
  //  章的那一对，不亮的时候每一句都指着一条真走得通的出路（判法在 ../gamutFold.ts，只此一处）。
  const [foldPick, setFoldPick] = useState("");
  const gamutRows = usableRows(app.caps?.gamut_matrices);
  const foldPicked = gamutRows.find((row) => row.id === foldPick) ?? null;
  const folded = foldedRow(nodes, gamutRows);
  const foldBlock = foldBlocker(nodes, gamutRows, limits.nodes)
    ?? (foldPicked ? null : "先在左边选一档，再按这颗——没选档就不知道该写哪九个数字。");
  const [manageSource, setManageSource] = useState<ColorSpace>(managed?.source ?? "srgb");
  const [manageDisplay, setManageDisplay] = useState<ColorSpace>(managed?.display ?? "rec709");
  useEffect(() => {
    setManageSource(managed?.source ?? "srgb");
    setManageDisplay(managed?.display ?? "rec709");
    // 只在换了片段时重读：同一段上刚选的这套空间要留着，好让人换一套再套一次。
  }, [clipId]);
  // 1.150：来源这一头可以多一个回答者——这份文件自己。界面只做两件事：先向引擎要那次只读的回执
  //  （`POST …/color-space`），再把回执原样念出来；「哪个标记算哪条曲线」一次都不在界面里判，
  //  连引擎下发的对照表也只念不算。按钮亮不亮只看引擎那两个字段，理由与出路见 ../colorManage.ts。
  const manageAutoGate = autoSourceOffered(app.caps?.features);
  const [manageAuto, setManageAuto] = useState(false);
  const [spaceRead, setSpaceRead] = useState<ClipColorSpaceReport | null>(null);
  const [spacePhase, setSpacePhase] = useState<ColorSpacePhase>("idle");
  const readSpace = shouldReadColorSpace(manageAutoGate, manageAuto, assetKind === "audio");
  const spaceProjectId = app.project?.id;
  useEffect(() => {
    if (!readSpace || !spaceProjectId) {
      setSpaceRead(null);
      setSpacePhase("idle");
      return;
    }
    let live = true;
    setSpaceRead(null);
    setSpacePhase("asking");
    void readClipColorSpace(spaceProjectId, clipId).then((report) => {
      if (!live) return;
      setSpaceRead(report);
      setSpacePhase(report ? "idle" : "failed");
    });
    return () => { live = false; };
  }, [readSpace, spaceProjectId, clipId]);
  const autoOn = manageAutoGate && manageAuto;
  const manageAutoBlock = autoSourceBlocker(manageAutoGate, manageAuto, spaceRead, spacePhase);
  // 命令里来源那一头写什么：勾了自带标记就是 null（契约要的那个「由文件回答」），否则照人点的。
  const managePicked = manageSourceValue(manageAutoGate, manageAuto, manageSource);
  // 「现在套的就是这一对」——来源那一头按上面那个决定读的是人点的还是文件说的，判断只此一处。
  const manageSame = managed !== null && managed.source === managePicked && managed.display === manageDisplay;
  const spaceLine = colorSpaceWords(spaceRead, spaceLabel, spacePhase);
  const tagTable = autoOn ? transferTagWords(app.caps?.color_transfer_tags, spaceLabel) : null;
  const manageBlock = assetKind === "audio"
    ? "音频片段没有画面可调色，也没有色彩空间可言。要管颜色就选一段画面或图片。"
    : manageAutoBlock !== null
      ? manageAutoBlock
      : managePicked === "linear" && manageDisplay === "linear"
        ? "两端都选了线性：这一对什么都不转，却要占两个节点、记一次历史，引擎会拒收。把「素材从哪里读」改成它真正的空间（屏幕录制通常是 sRGB，广播时间线是 Rec.709）。"
          + (autoOn ? "现在来源那一头是这份文件自己说的，要手工改就先去掉「来源按文件自带标记」那个勾。" : "")
        : !manageFits(nodes, limits.nodes)
          ? `取下已有的一对以后这条链还要 ${nodes.length - managedTagged} 个位置，再放两个就过了每链 ${limits.nodes} 个的上限。先在下面的链子里删掉几个节点，或者这一段干脆不套。`
          : manageSame
            ? "这一段现在就是这个来源、这个输出：再按一次引擎会说「什么也不会变」，所以这颗按钮先不亮。要换一套就改上面两个下拉菜单。"
              + (autoOn ? "来源那一头是这份文件自己说的，要换来源就去掉那个勾手工点一条。" : "")
            : null;

  useEffect(() => {
    if (pending.current !== null && nodes.length > pending.current) {
      setActive(pending.current);
      pending.current = null;
    } else if (active >= nodes.length) {
      setActive(Math.max(0, nodes.length - 1));
    }
  }, [active, nodes.length]);

  const write = (next: GradeNode[]) => setClipColor(clipId, { grade: next });
  const cards = cardsFor(nodes);
  const replace = (index: number, node: GradeNode) => write(nodes.map((entry, position) => position === index ? node : entry));
  const move = (index: number, target: number) => {
    const next = moveWithin(nodes, index, target);
    if (next === nodes) return;
    write(next);
    setActive(Math.min(Math.max(0, target), next.length - 1));
  };
  const add = (
    kind: "curve" | "white_balance" | "wheels" | "levels" | "matrix" | "transfer" | "parallel" | "composite",
  ) => {
    if (nodes.length >= limits.nodes) return;
    const node: GradeNode = kind === "parallel"
      ? { kind: "parallel", branches: [newOperation("white_balance"), newOperation("white_balance")] as GradeBranch[], enabled: true }
      : kind === "composite"
        ? { ...DEFAULT_COMPOSITE }
        : newOperation(kind);
    write([...nodes, node]);
    pending.current = nodes.length;
  };

  /** LUT 节点没有“中性值”可新建：表内容只能来自文件，所以点它就是为了打开文件选择。 */
  const pickLut = (index: number | null) => {
    if (index === null && nodes.length >= limits.nodes) return;
    lutTarget.current = index;
    lutFile.current?.click();
  };

  const head = nodes[active];
  // 路径走不通时自己缩短（换节点、删了一支之后都会这样），所以这里不需要一个 effect 去修它。
  const walked = resolveMixerPath(head, path);
  const current = mixerAt(head, walked);
  const chainFields = chainFieldsFor(head, walked);
  const branches = current?.branches ?? [];
  // Clamped here instead of in an effect, so a stale slot from another node can never edit the wrong branch.
  const slot = Math.min(branchSlot, Math.max(0, branches.length - 1));
  const shown = branches[slot] ?? null;
  /** 每一处写入都从这一个口子下去：改的是路径尽头那台混频台，链上那个节点整体换掉。 */
  const editMixer = (update: (mixer: GradeParallel) => GradeParallel) =>
    head ? replace(active, mapMixer(head, walked, update)) : null;
  // 1.120：并联节点的混频台。权重按位置覆盖每一支——契约要「给就给全」，所以这里从不留半份表：动一支
  // 就补齐整份，而每一支都回到 1 时把这份表整个撤掉（撤掉与交一串 1 是同一个均分，撤掉更诚实，也不会让
  // 老工程的载荷从此多出一串没人要的数）。
  const weightsOn = Boolean(app.caps?.features?.grade_branch_weights);
  const blendsOn = Boolean(app.caps?.features?.grade_branch_blend_modes);
  const setWeight = (node: GradeParallel, index: number, value: number) =>
    editMixer((mixer) => ({ ...mixer, weights: weightsAfterWeight(mixer, index, value) }));
  const setBlend = (node: GradeParallel, index: number, mode: BlendMode) =>
    editMixer((mixer) => ({ ...mixer, blends: blendsAfterPick(mixer, index, mode) }));
  // 一支可以是每通道操作，也可以是另一台混频台（1.124）；跨通道的矩阵与立方表仍然进不来——
  // 并联取各支平均，那种东西混进来就没有一张每通道表可塌，契约同样拒。
  const replaceBranch = (node: GradeParallel, index: number, next: GradeNode) => editMixer((mixer) => ({
    ...mixer,
    branches: mixer.branches.map((entry, position) => (
      position === index && (next.kind === "parallel" || (next.kind !== "matrix" && next.kind !== "lut3d")) ? next : entry
    )),
  }));
  const addBranch = (node: GradeParallel) => {
    editMixer((mixer) => ({ ...mixer, branches: [...mixer.branches, newOperation("white_balance") as GradeBranch], weights: weightsAfterAdd(mixer), blends: blendsAfterAdd(mixer) }));
    setSlot(node.branches.length);
  };
  const removeBranch = (node: GradeParallel) => {
    // 删一支必须把那一格的权重一起删掉：留下的是一份长度对不上的表，而契约会把这一次写入整笔拒掉——
    // 那等于把人困在「删不掉」里，所以形状由 gradeGraph 那一处负责补齐。
    editMixer((mixer) => ({ ...mixer, branches: mixer.branches.filter((_, position) => position !== slot), weights: weightsAfterRemove(mixer, slot), blends: blendsAfterRemove(mixer, slot) }));
    setSlot(Math.max(0, slot - 1));
  };
  // 1.124：进出某一支、把某一支套成一台混频台。套上来的那台先只装这一支自己（一支的平均就是它
  // 本身），所以「套并联」这一步不改画面，加下一支才是改画面——按钮不会偷偷调色调。
  const treesOn = Boolean(app.caps?.features?.grade_mixer_trees);
  const tree = head ? branchTree(head) : { depth: 0, operations: 0 };
  const wrapBlock = !shown || shown.kind === "parallel" ? ""
    : tree.depth + 1 > (limits.mixerDepth ?? FALLBACK_MIXER_DEPTH)
      ? `这棵树到第 ${tree.depth + 1} 层就越过引擎下发的 ${limits.mixerDepth ?? FALLBACK_MIXER_DEPTH} 层上限了：先回上一层，或删掉一支再套。`
      : tree.operations + 1 > (limits.treeOperations ?? FALLBACK_TREE_OPERATIONS)
        ? `这个节点底下已经有 ${tree.operations} 个操作，上限是 ${limits.treeOperations ?? FALLBACK_TREE_OPERATIONS}：先删一支再套。`
        : "";
  const wrapBranch = (node: GradeParallel, index: number) => {
    const branch = node.branches[index];
    if (!branch || branch.kind === "parallel") return;
    editMixer((mixer) => ({
      ...mixer,
      branches: mixer.branches.map((entry, position) => (
        position === index ? { kind: "parallel", enabled: true, mix: 1, blend: "normal" as BlendMode, branches: [entry] } : entry
      )),
    }));
  };
  const enterBranch = (index: number) => {
    setPath([...walked, index]);
    setSlot(0);
  };
  const leaveBranch = () => {
    setPath(walked.slice(0, -1));
    setSlot(0);
  };

  return <details className="insp-section grade-section" open={nodes.length > 0}>
    <summary className="panel-label">调色节点{nodes.length ? ` · ${nodes.length} 个` : ""}</summary>
    <fieldset className="effects-fields" disabled={locked}>
      <div className="batch-actions">
        {(["curve", "white_balance", "wheels", "levels", "matrix", "transfer", "parallel", "composite"] as const).map((kind) => <button key={kind} className="btn tiny" disabled={nodes.length >= limits.nodes} onClick={() => add(kind)}>+{NODE_NAMES[kind]}</button>)}
        {app.caps?.features.lut_import ? <button className="btn tiny" disabled={nodes.length >= limits.nodes} title="选择 .cube 文件（1D 逐通道或 3D 立方查找表），由引擎解析成调色链节点" onClick={() => pickLut(null)}>+LUT</button> : null}
        {app.caps?.features?.grade_apply_track && nodes.length ? <>
          <button className="btn tiny" disabled={Boolean(app.busy)} title="把这条片段现在的整条调色链套到它所在的这条轨上每一段（替换它们原有的链）。装不下的段落不会被悄悄丢掉：引擎一份份报出原因，toast 照实念。" onClick={() => applyGradeToTrack(clipId, "replace")}>套到整轨（替换）</button>
          <button className="btn tiny" disabled={Boolean(app.busy)} title="同上，但是把这条链接到每段已有节点的后面——超过每链节点上限的段落会报出来而不是被写坏。" onClick={() => applyGradeToTrack(clipId, "append")}>套到整轨（追加）</button>
        </> : null}
        <input ref={lutFile} type="file" accept=".cube,text/plain" hidden onChange={(event) => {
          const file = event.target.files?.[0];
          const target = lutTarget.current;
          lutTarget.current = null;
          event.target.value = "";
          if (file) void applyLut(clipId, file, target);
        }} />
      </div>
      <div className="batch-actions grade-auto-row">
        <label className="mask-shape">自动调色
          <select className="input" aria-label="自动调色测量方式" value={autoMode} onChange={(e) => setAutoMode(e.target.value as "luma" | "rgb")}>
            <option value="luma">亮度（一个节点）</option>
            <option value="rgb">分通道（三个节点）</option>
          </select>
        </label>
        <label className="grade-switch"><input type="checkbox" checked={autoReplace} onChange={(e) => setAutoReplace(e.target.checked)} />替换已有色阶</label>
        <button className="btn tiny" disabled={Boolean(autoBlock) || locked}
          title={autoBlock ?? "让引擎读这段素材自己的画面，量出黑场与白场，写成一个色阶节点放在链子最前面；预览与导出读同一张表"}
          onClick={() => void autoGradeClip(clipId, autoMode, 0.005, autoReplace)}>量黑场白场并拉开</button>
        <p className="hint">亮度模式只动整体明暗，不会凭空造出色偏；分通道模式能把偏色的素材拉回中性，但要占三个节点。量到的数会写在提示里，不满意就在上面的色阶卡片里自己改两个点。</p>
      </div>
      <div className="batch-actions grade-auto-row">
        <label className="mask-shape">素材从哪里读
          <select className="input" aria-label="色彩管理来源空间" value={manageSource}
            disabled={!handPickLive(manageAuto, manageAutoGate)} title={handPickWords(manageAuto, manageAutoGate)}
            onChange={(e) => setManageSource(e.target.value as ColorSpace)}>
            {spaces.map(([name, label]) => <option key={name} value={name}>{label}</option>)}
          </select>
        </label>
        <label className="mask-shape">交付按什么输出
          <select className="input" aria-label="色彩管理输出空间" value={manageDisplay} onChange={(e) => setManageDisplay(e.target.value as ColorSpace)}>
            {spaces.map(([name, label]) => <option key={name} value={name}>{label}</option>)}
          </select>
        </label>
        {manageAutoGate ? <label className="grade-switch" title="来源这一头不再由人点名：先问这份文件自带的色彩标记说它是哪条曲线（那一次只读，工程一个字都不写），引擎认得就照它认的那条套，认不出就点名拒绝并把读到的标记贴出来。界面不替你猜一条，也不自己抄一份对照表。">
          <input type="checkbox" aria-label="色彩管理来源按文件自带标记" checked={manageAuto}
            disabled={assetKind === "audio"} onChange={(e) => setManageAuto(e.target.checked)} />来源按文件自带标记
        </label>
          : <p className="hint">这一版引擎不读文件自带的色彩标记（capabilities 里没有 color_manage_auto 这一档），来源只能在「素材从哪里读」里手工点一条；下面那两张下拉菜单照常可用。</p>}
        <button className="btn tiny" disabled={Boolean(manageBlock) || locked || Boolean(app.busy)}
          title={manageBlock ?? "一次写下两个转换节点：素材读进线性光、调色在线性光里做、交付按你选的输出空间写回去。链子中间原有的节点一个不动；再套一次换的是同一对节点，不会叠出第二对。"}
          onClick={() => colorManageClip(clipId, managePicked, manageDisplay, autoOn)}>套上色彩管理</button>
        <button className="btn tiny" disabled={!managedTagged || locked || Boolean(app.busy)}
          title={managedTagged ? "只删引擎自己盖过章的那两个转换节点，中间手工加的曲线、混频台都原样留下。" : "这一段没有引擎盖过章的转换节点，所以这里没有可取的东西。那两个转换节点若是手工加的，请在下面的链子里删。"}
          onClick={() => colorManageClip(clipId, null, manageDisplay)}>取下色彩管理</button>
        {autoOn ? <p className="hint">{spaceLine}</p> : null}
        {tagTable ? <p className="hint dim">{tagTable}</p> : null}
        <p className="hint">{managedWords(managed, managedTagged, spaceLabel)} 同一条曲线在线性光里调与按存储值调，中点落点是两个数——越暗差别越大，而导出的文件读的就是这一份。</p>
      </div>
      <div className="batch-actions grade-auto-row">
        <label className="mask-shape">按表换基色
          <select className="input" aria-label="基色转换档" value={foldPick} onChange={(event) => setFoldPick(event.target.value)}>
            <option value="">（选一档）</option>
            {gamutRows.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
          </select>
        </label>
        <button className="btn tiny" disabled={Boolean(foldBlock) || locked || Boolean(app.busy)}
          title={foldBlock ?? "把引擎算好的那九个数字写成一枚通道混合，落在色彩管理那一对中间。同一格再折一次是换档，不是叠第二枚。"}
          onClick={() => {
            const next = foldPicked ? foldIn(nodes, foldPicked, gamutRows) : null;
            if (next) write(next);
          }}>折进这一格</button>
        <p className="hint">{foldWords(folded)}</p>
        <p className="hint dim">这张表由引擎算（基色矩阵），界面只搬数字：预览那张九宫格与导出那条链子读的是同一枚节点，所以「预览一个色、成片另一个色」在这一步上没有发生的余地。</p>
      </div>

      {nodes.length ? <div className="grade-graph" role="list" aria-label="调色节点链">
        <span className="gg-io">输入</span>
        {cards.map((card) => <Fragment key={card.index}>
          <span className="gg-wire" aria-hidden="true" />
          <div className={`gg-card${card.index === active ? " active" : ""}${card.enabled ? "" : " off"}${hover === card.index ? " over" : ""}`}
            draggable
            onDragStart={(event) => { dragging.current = card.index; event.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(event) => { event.preventDefault(); setHover(card.index); }}
            onDragLeave={() => setHover((current) => (current === card.index ? null : current))}
            onDrop={(event) => {
              event.preventDefault();
              const from = dragging.current;
              setHover(null);
              dragging.current = null;
              if (from !== null && from !== card.index) move(from, card.index);
            }}
            onDragEnd={() => { dragging.current = null; setHover(null); }}>
            <button className="gg-pick" onClick={() => setActive(card.index)} aria-label={`选择${card.label}节点`}>
              <b>{card.label}</b>
              {card.detail ? <em className="dim">{card.detail}</em> : null}
            </button>
            {card.lanes.length ? <div className="gg-lanes" aria-hidden="true"><LaneList lanes={card.lanes} /></div> : null}
            <span className="gg-tools">
              <label className="grade-switch"><input type="checkbox" checked={card.enabled} onChange={(event) => replace(card.index, { ...nodes[card.index], enabled: event.target.checked })} />启用</label>
              <button className="btn tiny" disabled={card.index === 0} onClick={() => move(card.index, card.index - 1)} aria-label="上移节点">↑</button>
              <button className="btn tiny" disabled={card.index === nodes.length - 1} onClick={() => move(card.index, card.index + 1)} aria-label="下移节点">↓</button>
              <button className="btn tiny danger" onClick={() => { write(nodes.filter((_, position) => position !== card.index)); setActive(Math.max(0, card.index - 1)); }} aria-label="移除节点">删</button>
            </span>
            <span className="gg-drag dim">拖动可改顺序</span>
          </div>
        </Fragment>)}
        <span className="gg-wire" aria-hidden="true" />
        <span className="gg-io">输出</span>
      </div> : <p className="hint">曝光、对比度、饱和度之后按顺序执行这些节点。曲线、白平衡、RGB 增益、色彩空间、1D LUT 与并联只改每通道值，预览与导出共用同一张表；通道混合与 3D LUT 按定义跨通道，各自自成一段——其中 3D LUT 浏览器画不出，只有导出生效。</p>}
      {capacityLine ? <p className="hint">{capacityLine}</p> : null}

      {chainFields ? <OpFields node={chainFields} idPrefix="grade" limits={limits} onReplace={chainFields.kind === "lut" || chainFields.kind === "lut3d" ? () => pickLut(active) : undefined} onCommit={(next) => replace(active, next)} /> : null}

      {current?.kind === "parallel" ? <div className="grade-body">
        <div className="batch-actions">
          {current.branches.map((branch, index) => <button key={index} className={`grade-pick${index === slot ? " active" : ""}`} onClick={() => setSlot(index)} aria-label={`选择第 ${index + 1} 支`}>{index + 1}. {NODE_NAMES[branch.kind]}{branch.kind === "parallel" ? ` ${branch.branches.length} 支` : ""}{branch.mix === undefined || branch.mix === 1 ? "" : ` · ${Math.round(branch.mix * 100)}%`}{branchWeight(current, index) === 1 ? "" : ` · ×${branchWeight(current, index)}`}{branchBlend(current, index) === "normal" ? "" : ` · ${blendLabel(branchBlend(current, index))}`}</button>)}
          <button className="btn tiny" disabled={current.branches.length >= limits.branches} onClick={() => addBranch(current)} aria-label="增加一支">+支</button>
          <button className="btn tiny danger" disabled={current.branches.length <= 1} onClick={() => removeBranch(current)} aria-label="删除本支">删支</button>
          {treesOn && shown && shown.kind !== "parallel" ? <button className="btn tiny" disabled={Boolean(wrapBlock)} onClick={() => wrapBranch(current, slot)}
            aria-label="把这一支变成并联" title={wrapBlock || "在这一支里面再摆一台混频台：它先算自己那一台的平均，再作为一支参与上一层"}>套并联</button> : null}
          {treesOn && shown?.kind === "parallel" ? <button className="btn tiny" onClick={() => enterBranch(slot)} aria-label="进入这一支" title="进去编辑这一台混频台自己的支、权重与混合方式">↳进这一支</button> : null}
          {walked.length ? <>
            <button className="btn tiny" onClick={() => leaveBranch()} aria-label="回到上一层混频台">↰上一层</button>
            <span className="dim" role="status">第 {walked.length + 1} 层 / 上限 {limits.mixerDepth ?? FALLBACK_MIXER_DEPTH}</span>
          </> : null}
        </div>
        {shown ? <>
          <OpFields node={shown} idPrefix={`grade-b${slot}`} limits={limits} onCommit={(next) => replaceBranch(current, slot, next)} />
          <MixFields node={shown} idPrefix={`grade-b${slot}`} label="支" onCommit={(next) => replaceBranch(current, slot, next)} />
          {blendsOn ? <>
            <label className="mask-shape">这一支的混合方式
              <select className="input" disabled={!shown.enabled} aria-label={`第 ${slot + 1} 支混合方式`} value={branchBlend(current, slot)}
                onChange={(event) => setBlend(current, slot, event.target.value as BlendMode)}>
                {BLEND_MODES.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
              </select>
            </label>
            <p className="hint">这一支先按所选方式与进到本节点的画面相合，再按权重参与平均；选「正常」时就是原来的加权平均。停用的一支仍是直通，所以这个下拉在停用那一支上是灰的。</p>
          </> : null}
          {weightsOn ? <>
            <Num id={`grade-b${slot}-weight`} label="这一支的权重" value={branchWeight(current, slot)} min={0} max={limits.weightMax} step={0.05}
              onCommit={(value) => setWeight(current, slot, value)} />
            {current.weights?.length ? <button className="btn tiny" onClick={() => setWeight(current, slot, 1)}
              title="把这一支拧回 1。每一支都是 1 时这份权重表整个撤掉，回到均分。">这一支回 1</button> : null}
          </> : null}
          <label className="grade-switch"><input type="checkbox" checked={shown.enabled} onChange={(e) => replaceBranch(current, slot, { ...shown, enabled: e.target.checked })} />启用本支</label>
        </> : null}
        <p className="hint">并联的每一支都从本节点的输入重新开始算，节点输出取各支的加权平均（没给权重就是均分，与不设权重逐位相同）；停用一支等于那支直通，不会改变支数。权重全部拧到 0 时这一节不改画面，而不是交一帧黑。平均的对象仍然是每通道函数，所以整个并联节点还是一张表，预览与导出共用。</p>
      </div> : null}

      {current ? <MixFields node={current} idPrefix="grade" label="节点" onCommit={(next) => replace(active, next)} /> : null}

      {nodes.length ? <button className="btn tiny" onClick={() => write([])}>清空调色节点</button> : null}
    </fieldset>
  </details>;
}
