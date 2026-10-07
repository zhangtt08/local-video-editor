import { useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import type { Clip, Curve, MaskProperty, MaskVertex, ShapeMask } from "../engine";
import { TIMEBASE } from "../time";
import { appInfo, commitMaskEdit, moveMaskCentre, playhead, setClipMask, setMaskEditing, useApp, usePlay } from "../store";
import { nearestEdge, withVertex } from "../maskOutline";

const CORNERS = [[-1,-1,"左上"],[1,-1,"右上"],[-1,1,"左下"],[1,1,"右下"]] as const;
const MASK_VARIABLE: Record<MaskProperty, string> = { mask_x: "x", mask_y: "y", mask_width: "w", mask_height: "h" };
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
// The engine publishes the real cap through capabilities; this only covers the first paint
// before that payload arrives, and must never be raised on its own.
const FALLBACK_VERTEX_LIMIT = 64;

type Gesture = {
  mask: ShapeMask; x: number; y: number;
  corner: readonly [number, number] | null;
  vertex?: number; handle?: "in" | "out"; outline?: boolean;
  projectId: string; revision: number; pointerId: number; element: SVGElement; moved: boolean;
  captured: boolean;
};

function outline(vertices: MaskVertex[]) {
  if (!vertices.length) return "";
  const point = (index: number) => [vertices[index].x * 100, vertices[index].y * 100] as const;
  const parts = [`M ${point(0)[0]} ${point(0)[1]}`];
  for (let index = 0; index < vertices.length; index += 1) {
    const current = vertices[index];
    const next = vertices[(index + 1) % vertices.length];
    const leaving = current.handle_out[0] || current.handle_out[1];
    const entering = next.handle_in[0] || next.handle_in[1];
    if (!leaving && !entering) {
      parts.push(`L ${point((index + 1) % vertices.length)[0]} ${point((index + 1) % vertices.length)[1]}`);
      continue;
    }
    const first = [(current.x + current.handle_out[0]) * 100, (current.y + current.handle_out[1]) * 100];
    const second = [(next.x + next.handle_in[0]) * 100, (next.y + next.handle_in[1]) * 100];
    const target = point((index + 1) % vertices.length);
    parts.push(`C ${first[0]} ${first[1]} ${second[0]} ${second[1]} ${target[0]} ${target[1]}`);
  }
  parts.push("Z");
  return parts.join(" ");
}

/** Geometry-only handles; the server compiles the actual alpha image during a gesture. */
export function MaskPicture({ clip, image, children, editable = true, animation }: { clip: Clip; image?: string | null; children: ReactNode; editable?: boolean; animation?: { unit: string; curves: Record<MaskProperty, Curve> } | null }) {
  const app = useApp(); const play = usePlay();
  const [draft, setDraft] = useState<ShapeMask | null>(null);
  const [compiled, setCompiled] = useState<{ mask: ShapeMask; image: string } | null>(null);
  const [handleSize, setHandleSize] = useState({ x: 5, y: 9 });
  const [shift, setShift] = useState({ tx: 0, ty: 0, sx: 1, sy: 1 });
  const [active, setActive] = useState<number | null>(null);
  const draftRef = useRef(draft); draftRef.current = draft;
  const svg = useRef<SVGSVGElement | null>(null);
  const picture = useRef<HTMLDivElement | null>(null);
  const maskAnimations = useRef<Animation[]>([]);
  const drag = useRef<Gesture | null>(null);
  const mask = draft ?? clip.mask;
  const animated = animation && !draft ? animation : null;
  const vertices = mask?.vertices ?? [];
  const pendingBatch = app.mode === "batch" && app.batch.length > 0;
  const candidateReady = !app.dryRunError && app.candidate?.id === app.project?.id && app.candidate?.revision === (app.project?.revision ?? 0) + 1;
  const disabled = Boolean(app.busy || app.dryRunBusy || app.project?.tracks.find((t) => t.id === clip.track_id)?.locked || (pendingBatch && !candidateReady));
  // A keyframed box mask is edited through its numeric curves, so the canvas guide stands down. A
  // free-form outline is different: its vertices are the shape itself and the curves only translate
  // it, so hiding the guide would make a tracked outline impossible to correct. It stays visible and
  // is moved to where the cut actually lands at this frame.
  const visible = Boolean(editable && mask && app.maskEditing && !play.playing && app.selectedClips.length === 1 && app.selectedClip === clip.id);
  useEffect(() => {
    const element = picture.current;
    maskAnimations.current.forEach((effect) => effect.cancel());
    maskAnimations.current = [];
    if (!element || !animated) return;
    const measure = () => {
      const box = element.getBoundingClientRect();
      element.style.setProperty("--mask-lw", String(Math.max(1, box.width)));
      element.style.setProperty("--mask-lh", String(Math.max(1, box.height)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    const duration = clip.duration_ticks / TIMEBASE * 1000;
    maskAnimations.current = (Object.keys(animated.curves) as MaskProperty[]).map((property) => {
      const effect = element.animate(animated.curves[property].map((point) => ({
        [`--mask-${MASK_VARIABLE[property]}`]: String(point.value), offset: point.offset, easing: point.easing,
      })), { duration, fill: "both" });
      effect.pause();
      return effect;
    });
    return () => { observer.disconnect(); maskAnimations.current.forEach((running) => running.cancel()); maskAnimations.current = []; };
  }, [animated, clip.duration_ticks]);
  useEffect(() => {
    const at = Math.max(0, (play.ticks - clip.position_ticks) / TIMEBASE * 1000);
    for (const effect of maskAnimations.current) effect.currentTime = at;
    // The guide has to sit where the cut actually is, so it reads the same animated box the picture
    // is masked with instead of solving the engine's curve a second time: the browser's own
    // interpolation of that curve is the only authority. A box mask also *resizes* over time, so
    // the guide scales as well as moves — otherwise the corner handle you grab is not the edge you
    // see. translate(T) + scale(S) about the centre maps a base coordinate u to
    // 0.5 + S(u-0.5) + T, and that has to equal cx_now + S(u-cx_base), hence T below.
    const element = picture.current;
    if (!element || !animated || !mask) {
      setShift((old) => (old.tx || old.ty || old.sx !== 1 || old.sy !== 1 ? { tx: 0, ty: 0, sx: 1, sy: 1 } : old));
      return;
    }
    const style = getComputedStyle(element);
    const centre = { x: Number(style.getPropertyValue("--mask-x")), y: Number(style.getPropertyValue("--mask-y")) };
    const size = { w: Number(style.getPropertyValue("--mask-w")), h: Number(style.getPropertyValue("--mask-h")) };
    const sx = mask.width ? size.w / mask.width : 1;
    const sy = mask.height ? size.h / mask.height : 1;
    const tx = centre.x - sx * mask.center_x - 0.5 + 0.5 * sx;
    const ty = centre.y - sy * mask.center_y - 0.5 + 0.5 * sy;
    setShift((old) => (
      Math.abs(old.tx - tx) + Math.abs(old.ty - ty) + Math.abs(old.sx - sx) + Math.abs(old.sy - sy) < 0.001
        ? old : { tx, ty, sx, sy }
    ));
  }, [play.ticks, clip.position_ticks, animated, mask]);
  useEffect(() => {
    if (!visible || !svg.current) return;
    const measure = () => {
      const matrix = svg.current?.getScreenCTM(); if (!matrix) return;
      const x = 10 / Math.max(.001, Math.hypot(matrix.a,matrix.b)), y = 10 / Math.max(.001,Math.hypot(matrix.c,matrix.d));
      setHandleSize((old) => Math.abs(old.x-x)+Math.abs(old.y-y)<.01 ? old : {x,y});
    };
    const observer = new ResizeObserver(measure); observer.observe(svg.current);
    const frame = requestAnimationFrame(measure);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [visible, clip, play.ticks]);
  const cancel = () => {
    const gesture = drag.current; drag.current = null; setDraft(null);
    if (gesture?.element.hasPointerCapture(gesture.pointerId)) gesture.element.releasePointerCapture(gesture.pointerId);
  };
  useEffect(() => { cancel(); }, [clip.id, disabled, visible]);
  useEffect(() => { setActive(null); }, [clip.id]);
  useEffect(() => () => { drag.current = null; }, []);
  useEffect(() => {
    if (!draft) { setCompiled(null); return; }
    let live = true, busy = false; let sent: ShapeMask | null = null;
    const frame = app.project?.settings;
    const read = () => {
      const latest = draftRef.current;
      if (!latest || sent === latest || busy) return;
      sent = latest; busy = true;
      void appInfo.engine()?.maskPreview(latest, frame?.width, frame?.height).then((value) => {
        if (live) setCompiled({ mask: latest, image: value.mask_image });
      }).catch(() => { if (live) setCompiled(null); }).finally(() => { busy = false; });
    };
    read(); const timer = window.setInterval(read,60);
    return () => { live = false; window.clearInterval(timer); };
  }, [Boolean(draft)]);
  const locate = (event: {clientX: number; clientY: number}) => {
    const matrix = svg.current?.getScreenCTM();
    if (!matrix) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return { x: point.x / 100, y: point.y / 100 };
  };
  const proposed = (event: PointerEvent<SVGElement>) => {
    const gesture = drag.current!; const point = locate(event); if (!point) return gesture.mask;
    const dx = point.x - gesture.x, dy = point.y - gesture.y;
    if (Math.abs(dx) + Math.abs(dy) > .005) gesture.moved = true;
    if (gesture.outline) {
      const list = gesture.mask.vertices ?? [];
      if (!list.length) return gesture.mask;
      // 整条轮廓只能在这 0..1 的画框里搬：可动的范围是 [−最小顶点, 1−最大顶点]，两侧不对称。
      const xs = list.map((entry) => entry.x), ys = list.map((entry) => entry.y);
      const clampDelta = (delta: number, low: number, high: number) => Math.min(high, Math.max(low, delta));
      const mx = clampDelta(dx, -Math.min(...xs), 1 - Math.max(...xs));
      const my = clampDelta(dy, -Math.min(...ys), 1 - Math.max(...ys));
      return {
        ...gesture.mask,
        vertices: list.map((entry) => ({ ...entry, x: entry.x + mx, y: entry.y + my })),
      };
    }
    if (gesture.vertex !== undefined) {
      const list = gesture.mask.vertices ?? [];
      const current = list[gesture.vertex];
      if (!current) return gesture.mask;
      const next: MaskVertex = gesture.handle
        ? { ...current, [gesture.handle === "out" ? "handle_out" : "handle_in"]: [
            clamp(point.x - current.x - gesture.x + current[gesture.handle === "out" ? "handle_out" : "handle_in"][0], -1, 1),
            clamp(point.y - current.y - gesture.y + current[gesture.handle === "out" ? "handle_out" : "handle_in"][1], -1, 1),
          ] as [number, number] }
        : { ...current, x: clamp(point.x, 0, 1), y: clamp(point.y, 0, 1) };
      return { ...gesture.mask, vertices: list.map((entry, index) => index === gesture.vertex ? next : entry) };
    }
    if (!gesture.corner) return { ...gesture.mask, center_x: clamp(gesture.mask.center_x + dx,0,1), center_y: clamp(gesture.mask.center_y + dy,0,1) };
    const [sideX,sideY] = gesture.corner;
    const anchorX = gesture.mask.center_x - sideX * gesture.mask.width / 2, anchorY = gesture.mask.center_y - sideY * gesture.mask.height / 2;
    return { ...gesture.mask, center_x: clamp((anchorX + point.x) / 2,0,1), center_y: clamp((anchorY + point.y) / 2,0,1), width: clamp(Math.abs(point.x - anchorX),.01,2), height: clamp(Math.abs(point.y - anchorY),.01,2) };
  };
  const begin = (event: PointerEvent<SVGElement>, target: Partial<Gesture>) => {
    event.stopPropagation(); event.preventDefault(); event.currentTarget.focus();
    if (disabled || !mask || !app.project) return;
    playhead.pause(); const point = locate(event); if (!point) return;
    const element = event.currentTarget;
    let captured = true;
    try { element.setPointerCapture(event.pointerId); } catch { captured = false; }
    drag.current = { mask, ...point, corner: null, ...target, projectId: app.project.id, revision: app.project.revision, pointerId: event.pointerId, element, moved: false, captured } as Gesture;
    if (target.vertex !== undefined) setActive(target.vertex);
  };
  const owns = (event: PointerEvent<SVGElement>) => {
    const gesture = drag.current;
    return Boolean(gesture && gesture.pointerId === event.pointerId && (!gesture.captured || gesture.element.hasPointerCapture(event.pointerId)));
  };
  const write = (value: ShapeMask) => {
    if (disabled || !app.project) return;
    commitMaskEdit(clip.id, value, Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)), app.project.id, app.project.revision);
  };
  const nudgeVertex = (event: React.KeyboardEvent, index: number) => {
    const step = event.shiftKey ? .1 : .01;
    if (!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation(); if (disabled || !mask?.vertices) return;
    svg.current?.focus();
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    write({ ...mask, vertices: mask.vertices.map((entry, position) => position === index ? { ...entry, x: clamp(entry.x + dx, 0, 1), y: clamp(entry.y + dy, 0, 1) } : entry) });
  };
  const pictureImage = draft && compiled ? compiled.image : image;
  const pictureStyle: CSSProperties = animated
    ? { maskImage: animated.unit, "--mask-x": mask?.center_x ?? .5, "--mask-y": mask?.center_y ?? .5, "--mask-w": mask?.width ?? 1, "--mask-h": mask?.height ?? 1 } as CSSProperties
    : { maskImage: pictureImage ?? undefined, maskSize: "100% 100%", maskRepeat: "no-repeat" };
  return <>
    <div ref={picture} className={`layer-transform masked-picture${animated ? " animated-mask" : ""}`} style={pictureStyle}>{children}</div>
    {visible && mask ? <svg ref={svg} className={`mask-guide${disabled ? " locked" : ""}`} viewBox="0 0 100 100" preserveAspectRatio="none" role="group" aria-label="画面遮罩编辑器" tabIndex={0}
      style={shift.tx || shift.ty || shift.sx !== 1 || shift.sy !== 1 ? { transform: `translate(${(shift.tx * 100).toFixed(4)}%, ${(shift.ty * 100).toFixed(4)}%) scale(${shift.sx.toFixed(6)}, ${shift.sy.toFixed(6)})` } : undefined}
      onDoubleClick={(event) => {
        if (mask.shape !== "path" || disabled || !mask.vertices) return;
        if (mask.vertices.length >= (app.caps?.mask_vertex_limit ?? FALLBACK_VERTEX_LIMIT)) return;
        const raw = locate(event); if (!raw) return;
        const point = { x: clamp(raw.x, 0, 1), y: clamp(raw.y, 0, 1) };
        setActive(nearestEdge(mask.vertices, point).edge + 1);
        write(withVertex(mask, point));
      }}
      onClick={(e) => e.stopPropagation()} onKeyDown={(e) => {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); if (drag.current) cancel(); else setMaskEditing(false); return; }
        if (["Delete","Backspace"].includes(e.key)) {
          e.preventDefault(); e.stopPropagation(); if (disabled) return;
          if (mask.shape === "path" && active !== null && (mask.vertices?.length ?? 0) > 3) {
            write({ ...mask, vertices: (mask.vertices ?? []).filter((_, index) => index !== active) });
            setActive(null);
            return;
          }
          setClipMask(clip.id,null); return;
        }
        if (active !== null && mask.shape === "path") return;
        if (!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) return;
        e.preventDefault(); e.stopPropagation(); if (disabled) return;
        const step = e.shiftKey ? .1 : .01; svg.current?.focus();
        write({ ...mask, center_x: clamp(mask.center_x + (e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0),0,1), center_y: clamp(mask.center_y + (e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0),0,1) });
      }} onPointerMove={(e) => { if (owns(e)) setDraft(proposed(e)); }}
      onPointerUp={(e) => { const gesture = drag.current; if (!gesture) return; const next = proposed(e); const moved = gesture.moved; cancel(); if (moved) { svg.current?.focus(); const at = Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)); if (gesture.outline && (clip.keyframes ?? []).some((key) => key.property === "mask_x" || key.property === "mask_y")) { moveMaskCentre(clip.id, at, { x: mask.center_x + shift.tx + (next.center_x - mask.center_x), y: mask.center_y + shift.ty + (next.center_y - mask.center_y) }, gesture.projectId, gesture.revision); } else commitMaskEdit(clip.id,next,at,gesture.projectId,gesture.revision); } }} onPointerCancel={cancel} onLostPointerCapture={() => { if (drag.current) cancel(); }}>
      {mask.shape === "path" ? <>
        <path className="mask-hit" d={outline(vertices)} role="button" tabIndex={0} aria-label="移动整条路径" aria-disabled={disabled}
          onPointerDown={(e) => begin(e, { outline: true })} />
        <path className="mask-outline" d={outline(vertices)} />
        {vertices.map((vertex, index) => <>
          <line key={`out-${index}`} className="mask-tangent" x1={vertex.x*100} y1={vertex.y*100} x2={(vertex.x+vertex.handle_out[0])*100} y2={(vertex.y+vertex.handle_out[1])*100} />
          <line key={`in-${index}`} className="mask-tangent" x1={vertex.x*100} y1={vertex.y*100} x2={(vertex.x+vertex.handle_in[0])*100} y2={(vertex.y+vertex.handle_in[1])*100} />
        </>)}
        {vertices.map((vertex, index) => <>
          {active === index || vertex.handle_out[0] || vertex.handle_out[1] || vertex.handle_in[0] || vertex.handle_in[1] ? <>
            <rect key={`ho-${index}`} className={`mask-handle-point${active === index ? " active" : ""}`} x={(vertex.x+vertex.handle_out[0])*100-handleSize.x/2} y={(vertex.y+vertex.handle_out[1])*100-handleSize.y/2} width={handleSize.x} height={handleSize.y} role="button" tabIndex={0} aria-label={`出站控制柄 ${index+1}`} aria-disabled={disabled} onPointerDown={(e) => begin(e, { vertex: index, handle: "out" })} />
            <rect key={`hi-${index}`} className={`mask-handle-point${active === index ? " active" : ""}`} x={(vertex.x+vertex.handle_in[0])*100-handleSize.x/2} y={(vertex.y+vertex.handle_in[1])*100-handleSize.y/2} width={handleSize.x} height={handleSize.y} role="button" tabIndex={0} aria-label={`入站控制柄 ${index+1}`} aria-disabled={disabled} onPointerDown={(e) => begin(e, { vertex: index, handle: "in" })} />
          </> : null}
          <circle key={`v-${index}`} className={`mask-vertex${active === index ? " active" : ""}`} cx={vertex.x*100} cy={vertex.y*100} r={handleSize.x*0.7} role="button" tabIndex={0} aria-label={`遮罩顶点 ${index+1}`} aria-disabled={disabled}
            onPointerDown={(e) => begin(e, { vertex: index })}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setActive(index); } nudgeVertex(e, index); }} />
        </>)}
      </> : <>
        <rect className="mask-hit" x={(mask.center_x - mask.width / 2)*100} y={(mask.center_y - mask.height / 2)*100} width={mask.width*100} height={mask.height*100} onPointerDown={(e) => begin(e, { corner: null })} role="button" tabIndex={0} aria-label="移动遮罩" aria-disabled={disabled} />
        {mask.shape === "ellipse" ? <ellipse className="mask-outline" cx={mask.center_x*100} cy={mask.center_y*100} rx={mask.width*50} ry={mask.height*50} /> : <rect className="mask-outline" x={(mask.center_x-mask.width/2)*100} y={(mask.center_y-mask.height/2)*100} width={mask.width*100} height={mask.height*100} />}
        <path className="mask-cross" d={`M ${mask.center_x*100-2} ${mask.center_y*100} h 4 M ${mask.center_x*100} ${mask.center_y*100-2} v 4`} />
        {CORNERS.map(([x,y,label]) => <rect key={label} className="mask-handle" x={(mask.center_x+x*mask.width/2)*100-handleSize.x/2} y={(mask.center_y+y*mask.height/2)*100-handleSize.y/2} width={handleSize.x} height={handleSize.y} role="button" tabIndex={0} aria-label={`缩放遮罩${label}角`} aria-disabled={disabled} onPointerDown={(e) => begin(e,{ corner: [x,y] })} onKeyDown={(e) => {
          if (!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) return;
          e.preventDefault(); e.stopPropagation(); if (disabled) return;
          const step = e.shiftKey ? .1 : .01; svg.current?.focus();
          write({ ...mask, width: clamp(mask.width + (e.key === "ArrowLeft" ? -step*x : e.key === "ArrowRight" ? step*x : 0),.01,2), height: clamp(mask.height + (e.key === "ArrowUp" ? -step*y : e.key === "ArrowDown" ? step*y : 0),.01,2) });
        }} />)}
      </>}
    </svg> : null}
  </>;
}
