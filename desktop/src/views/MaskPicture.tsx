import { useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import type { Clip, Curve, ExtraMaskWindow, MaskBoxKey, MaskProperty, MaskRotationWindow, MaskShapeWindow, MaskVertex, ShapeMask } from "../engine";
import { TIMEBASE, frameTicks } from "../time";
import { appInfo, commitMaskEdit, moveMaskCentre, playhead, recordMaskShape, setClipMask, setClipMaskStack, setMaskEditing, useApp, usePlay } from "../store";
import { asCorner, asSmooth, nearestEdge, withoutVertex, withVertex } from "../maskOutline";
import { boxVectorFromPointer, rotateAngleFromPointer, rotatedBoxPoints, rotatedCorners, rotatedEdgeMids, rotationWindowAt, stemAngleFromUser } from "../maskGeometry";
import { morphArmed, outlineAt, shapeVariables, shapeWindowAt, shapeWindowIndex } from "../maskShape";
import { boxKeyAt, boxKeyForPlayhead } from "../effects";

const CORNERS = [[-1,-1,"左上"],[1,-1,"右上"],[1,1,"右下"],[-1,1,"左下"]] as const;
// 只有盒子的四个数靠 CSS 变量动。角度不动变量——它动的是引擎下发的整张图（每段窗一张），
// 因为 `mask-image` 不吃图层的 `transform`（1.164 量的），阶梯两端同表才是真的同一件事。
type MaskBoxProperty = Exclude<MaskProperty, "mask_rotation">;
const MASK_VARIABLE: Record<MaskBoxProperty, string> = { mask_x: "x", mask_y: "y", mask_width: "w", mask_height: "h" };
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
// The engine publishes the real cap through capabilities; this only covers the first paint
// before that payload arrives, and must never be raised on its own.
const FALLBACK_VERTEX_LIMIT = 64;
const FALLBACK_ROTATION_LIMIT = 360;

type Gesture = {
  mask: ShapeMask; x: number; y: number;
  corner: readonly [number, number] | null;
  vertex?: number; handle?: "in" | "out"; outline?: boolean;
  // 旋转手柄：起始那一刻指针相对盒心的屏幕角，写下来才做得出「转了多少度」的差值。
  // 屏幕角不是画框角——画框按画面非均匀拉伸，直接拿 0..1 的坐标算 atan2 出来的不是人转的那一下。
  rotate?: boolean; angle0?: number;
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
export function MaskPicture({ clip, image, extra, extraWindows, extraUnits, children, editable = true, follow = false, animation, shape, rotation }: { clip: Clip; image?: string | null; extra?: string[] | null; extraWindows?: (ExtraMaskWindow[] | null)[] | null; extraUnits?: (string | null)[] | null; children: ReactNode; editable?: boolean; follow?: boolean; animation?: { unit: string | null; curves: Record<MaskProperty, Curve> } | null; shape?: MaskShapeWindow[] | null; rotation?: MaskRotationWindow[] | null }) {
  const app = useApp(); const play = usePlay();
  const [draft, setDraft] = useState<ShapeMask | null>(null);
  const [compiled, setCompiled] = useState<{ mask: ShapeMask; image: string } | null>(null);
  const [handleSize, setHandleSize] = useState({ x: 5, y: 9 });
  const [shift, setShift] = useState({ tx: 0, ty: 0, sx: 1, sy: 1 });
  const [active, setActive] = useState<number | null>(null);
  // 1.252：画面里选中的那一块再叠遮罩。只画选中那一块，且只有一颗柄——两种控件不再抢同一片区域。
  const [extraDraft, setExtraDraft] = useState<{ index: number; box: ShapeMask; duplicate?: boolean } | null>(null);
  // 松手那一刻 React 的状态可能还没追上最后一次 move；落库读的是这个 ref（主遮罩那一手也是同一课）。
  const extraDraftRef = useRef<{ index: number; box: ShapeMask; duplicate?: boolean } | null>(null);
  const extraDrag = useRef<{ index: number; keyTick: number | null; insertAt: number | null;
    insertInterp: MaskBoxKey["interpolation"]; x: number; y: number; box: ShapeMask;
    corner: [number, number] | null; angle: number; k: number; rotate: boolean; angle0: number | null;
    duplicate: boolean;
    pointerId: number; element: SVGElement; captured: boolean; inverse: DOMMatrix;
    projectId: string; revision: number; moved: boolean; detach: () => void } | null>(null);
  const draftRef = useRef(draft); draftRef.current = draft;
  const svg = useRef<SVGSVGElement | null>(null);
  const picture = useRef<HTMLDivElement | null>(null);
  const maskAnimations = useRef<Animation[]>([]);
  const drag = useRef<Gesture | null>(null);
  // 1.118: 播放头落在哪一窗，就画哪一窗的轮廓。引擎把形变编译成一格一步的窗，导出切的板与界面画的
  // 图来自同一份表；界面自己不插值，所以绝不会出现导出里没有的那个形状。
  const local = Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks));
  const shapeWindow = draft ? null : shape ? shapeWindowAt(shape, local) : null;
  // 1.165: 会转的盒。引擎把角度曲线切成整帧对齐的窗，这里按播放头挑那一张图——一格一步，两端同步。
  const spun = draft ? null : rotation ? rotationWindowAt(rotation, local) : null;
  const mask = draft ?? (clip.mask && shapeWindow ? { ...clip.mask, vertices: shapeWindow.vertices } : clip.mask);
  const animated = animation && !draft ? animation : null;
  const rotated = Boolean(mask?.rotation) || Boolean(spun);
  const corners = mask && rotated ? rotatedCorners(spun ? { ...mask, width: spun.width, height: spun.height } : mask, (app.project?.settings.height ?? 9) / (app.project?.settings.width ?? 16), spun?.angle) : "";
  // A morph places its plate by the window's own box, so the layer needs the size/position custom
  // properties even when the mask carries no centre curves at all.
  const placed = Boolean(animated || shapeWindow || spun);
  const vertices = outlineAt(shapeWindow, mask);
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
    if (!element || !placed) return;
    const measure = () => {
      const box = element.getBoundingClientRect();
      element.style.setProperty("--mask-lw", String(Math.max(1, box.width)));
      element.style.setProperty("--mask-lh", String(Math.max(1, box.height)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (!animated) return () => { observer.disconnect(); };
    const duration = clip.duration_ticks / TIMEBASE * 1000;
    maskAnimations.current = (Object.keys(animated.curves) as MaskProperty[]).filter((property) => property !== "mask_rotation").map((property) => {
      const effect = element.animate(animated.curves[property].map((point) => ({
        [`--mask-${MASK_VARIABLE[property as MaskBoxProperty]}`]: String(point.value), offset: point.offset, easing: point.easing,
      })), { duration, fill: "both" });
      effect.pause();
      return effect;
    });
    return () => { observer.disconnect(); maskAnimations.current.forEach((running) => running.cancel()); maskAnimations.current = []; };
  }, [animated, placed, clip.duration_ticks]);
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
    const extra = extraDrag.current; extraDrag.current = null; extraDraftRef.current = null; setExtraDraft(null);
    extra?.detach();
    if (extra?.element.hasPointerCapture(extra.pointerId)) extra.element.releasePointerCapture(extra.pointerId);
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
  // 指针相对盒心的**屏幕角**：0 度指向屏幕上，顺时针为正——与引擎那一格的读数同一个方向。
  // 必须先把画框坐标乘回各自那一路的像素比例：0..100 的框是拉伸到画面的，直接 atan2 会量出
  // 另一个角（1.165 烘那张等比图时量的就是这件事）。
  const angleOfBox = (box: ShapeMask | null | undefined, clientX: number, clientY: number) => {
    const matrix = svg.current?.getScreenCTM();
    if (!matrix || !box) return null;
    // 茎画在哪由 `rotatedEdgeMids` 定，所以指针的角度要用同一套除法读回来（1.181）：先除回这一路的
    // 像素比例 a、d，再除掉画幅比那一步变形。旧式子读的是纯屏幕角，在拉伸过的框上比茎的角度小，
    // 于是「拖多少」与「看见多少」成了两件事——实测屏幕 30° 只让茎走 3.6°。
    const k = (app.project?.settings.height ?? 9) / (app.project?.settings.width ?? 16);
    return rotateAngleFromPointer(clientX - (matrix.a * box.center_x * 100 + matrix.e),
      clientY - (matrix.d * box.center_y * 100 + matrix.f), matrix.a, matrix.d, k);
  };
  const angleOf = (event: {clientX: number; clientY: number}) => angleOfBox(mask, event.clientX, event.clientY);
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
    if (gesture.rotate) {
      const angle = angleOf(event);
      if (angle === null || gesture.angle0 === undefined) return gesture.mask;
      let delta = angle - gesture.angle0;
      if (delta > 180) delta -= 360; else if (delta < -180) delta += 360;
      if (Math.abs(delta) > 0.5) gesture.moved = true;
      // 落笔只动角度：中心与两条边各归自己的曲线，转过的盒能不能同时动尺寸由引擎那把开关说了算，
      // 这里不替它决定。夹边用的是下发的那个数，界面不自带上限（拔过界只会让引擎拒一整笔）。
      return { ...gesture.mask, rotation: Math.round(clamp((gesture.mask.rotation ?? 0) + delta, -rotationLimit, rotationLimit) * 10) / 10 };
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
    drag.current = { mask, ...point, corner: null, ...target,
      angle0: target.rotate ? angleOf(event) ?? undefined : undefined,
      projectId: app.project.id, revision: app.project.revision, pointerId: event.pointerId, element, moved: false, captured } as Gesture;
    if (target.vertex !== undefined) setActive(target.vertex);
  };
  const owns = (event: PointerEvent<SVGElement>) => {
    const gesture = drag.current;
    return Boolean(gesture && gesture.pointerId === event.pointerId && (!gesture.captured || gesture.element.hasPointerCapture(event.pointerId)));
  };
  // 已经形变起来的遮罩，拖顶点、拖控制柄、方向键微调都是「记这一帧的形状」；改节点数（双击加点、删点、
  // 角点、自动平滑）动的是画出来的那条轮廓，所以仍写遮罩本身——那里定的是一整段形变的拓扑。
  const write = (value: ShapeMask, morphing = false) => {
    if (disabled || !app.project) return;
    if (morphing && morphArmed(clip)) {
      recordMaskShape(clip.id, value.vertices ?? [], local, undefined, app.project.id, app.project.revision);
      return;
    }
    commitMaskEdit(clip.id, value, local, app.project.id, app.project.revision);
  };
  // The cap comes from the engine and the three vertex ops say why they are dead, so a click is never
  // swallowed: before this, deleting a point needed the keyboard and hitting the cap did nothing silent.
  const vertexLimit = app.caps?.mask_vertex_limit ?? FALLBACK_VERTEX_LIMIT;
  // 旋转的角度上限由引擎下发；这一格只是它没回该字段时的兜底（与顶点数上限同一个写法）。
  const rotationLimit = app.caps?.limits?.mask_rotation_limit ?? FALLBACK_ROTATION_LIMIT;
  // 轮廓遮罩没有盒可转（引擎那句拒收在先），没报 mask_rotation 开关的引擎也不摆这颗手柄。
  const canRotate = Boolean(mask && mask.shape !== "path" && app.caps?.features?.mask_rotation);
  const atCap = mask?.shape === "path" && vertices.length >= vertexLimit;
  const frame = frameTicks(app.project?.settings.frame_rate ?? { numerator: 30, denominator: 1 });
  const localAt = Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks));
  const selectedIndex = app.maskExtraSel?.clipId === clip.id ? app.maskExtraSel.index : null;
  const selectedExtra = selectedIndex === null ? undefined : clip.extra_masks?.[selectedIndex];
  const selectedFrameTick = Math.min(clip.duration_ticks, Math.round(localAt / frame) * frame);
  const selectedKey = selectedExtra
    ? boxKeyForPlayhead(selectedExtra, localAt, selectedFrameTick) : undefined;
  // 这一张画框按画面比例非均匀拉伸：角度换算的唯一那个 k（与主遮罩那一圈读的是同一个数）。
  const pictureRatio = (app.project?.settings.height ?? 9) / (app.project?.settings.width ?? 16);
  // 1.255：停在两枚框点之间时，那一框就是**引擎窗表在这一格执行的那五个数**——
  // 界面不自己插值（那就会画出导出没有的那一格），也不再把框藏起来。
  const selectedWindow = selectedExtra?.keys?.length && !selectedKey && selectedIndex !== null
    ? rotationWindowAt(extraWindows?.[selectedIndex] ?? [], localAt) : null;
  const executedBox = selectedWindow?.box ?? null;
  const extraKeyLimit = app.caps?.limits?.extra_mask_keys ?? 0;
  const canInsert = Boolean(executedBox) && (selectedExtra?.keys?.length ?? 0) < extraKeyLimit;
  // Alt 拖那一手是「复制这一块再拖副本」——块数到顶就许不出这一只手（不是偷偷退回普通拖动）。
  const extraStackLimit = app.caps?.limits?.extra_masks ?? 0;
  const canDuplicate = Boolean(selectedExtra) && (clip.extra_masks?.length ?? 0) < extraStackLimit;
  // 新那一枚接着这一窗的节奏走：插值抄这一窗起点那一枚，不自己编一个。
  const windowOwner = selectedExtra && selectedWindow
    ? boxKeyAt(selectedExtra, selectedWindow.from_ticks) ?? selectedExtra.keys?.[0] : null;
  const extraBox: ShapeMask | null = selectedExtra
    ? (selectedKey ? { ...selectedExtra, center_x: selectedKey.center_x, center_y: selectedKey.center_y,
        width: selectedKey.width, height: selectedKey.height, rotation: selectedKey.rotation ?? 0 }
      : executedBox && canInsert ? { ...selectedExtra, ...executedBox } : selectedExtra)
    : null;
  const extraDrawable = Boolean(visible && selectedExtra && extraBox && !follow && !disabled
    && (!(selectedExtra.keys?.length) || selectedKey || canInsert));
  // 那颗角度柄读的是**画框坐标系里**指针的方向——`rotatedEdgeMids` 那根茎的精确逆。
  // 走按下那一刻那份完整逆矩阵：导引挂在片段自己的旋转/缩放那一摞里，只除 a、d 会把那一摞的转动漏掉。
  const extraPointerAngle = (box: ShapeMask, inverse: DOMMatrix, clientX: number, clientY: number) => {
    const point = new DOMPoint(clientX, clientY).matrixTransform(inverse);
    return stemAngleFromUser(point.x / 100 - box.center_x, point.y / 100 - box.center_y, pictureRatio);
  };
  const beginExtra = (event: PointerEvent<SVGElement>, corner: [number, number] | null, rotate = false) => {
    event.stopPropagation(); event.preventDefault();
    const matrix = svg.current?.getScreenCTM();
    if (!extraDrawable || !selectedExtra || !extraBox || !app.project || !matrix) return;
    playhead.pause();
    const inverse = matrix.inverse();
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(inverse);
    const element = event.currentTarget;
    let captured = true;
    try { element.setPointerCapture(event.pointerId); } catch { captured = false; }
    const gesture = { index: selectedIndex!, keyTick: selectedKey?.at_ticks ?? null,
      insertAt: selectedKey || !canInsert ? null : selectedFrameTick,
      insertInterp: windowOwner?.interpolation ?? "linear",
      duplicate: rotate ? false : event.altKey && canDuplicate,
      x: point.x / 100, y: point.y / 100, box: extraBox, corner, rotate,
      angle0: rotate ? extraPointerAngle(extraBox, inverse, event.clientX, event.clientY) : null,
      angle: extraBox.rotation ?? 0, k: pictureRatio, pointerId: event.pointerId,
      element, captured, inverse, projectId: app.project.id,
      revision: app.project.revision, moved: false, detach: () => {} };
    // 捕获在 SVG 的 rect 上不稳（这个盒子的根是 pointer-events:none）；抓取期间直接在 window 上听，
    // 松手一定收得到，指针走到画面外也不会断。
    const move = (pointer: globalThis.PointerEvent) => {
      if (pointer.pointerId !== gesture.pointerId) return;
      moveExtraAt(pointer.clientX, pointer.clientY);
    };
    const up = (pointer: globalThis.PointerEvent) => {
      if (pointer.pointerId !== gesture.pointerId) return;
      gesture.detach();
      finishExtraAt(pointer.pointerId);
    };
    gesture.detach = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    extraDrag.current = gesture;
    extraDraftRef.current = { index: selectedIndex!, box: extraBox, duplicate: event.altKey && canDuplicate };
    setExtraDraft(extraDraftRef.current);
  };
  const moveExtraAt = (clientX: number, clientY: number) => {
    const gesture = extraDrag.current;
    if (!gesture) return;
    const point = new DOMPoint(clientX, clientY).matrixTransform(gesture.inverse);
    const dx = point.x / 100 - gesture.x, dy = point.y / 100 - gesture.y;
    if (Math.abs(dx) + Math.abs(dy) > .002) gesture.moved = true;
    let box: ShapeMask;
    if (gesture.rotate) {
      // 与主遮罩那颗手柄同一只手：读的是指针相对盒心的屏幕角，落笔只动角度那一格，
      // 中心与两条边各归自己；上限听引擎下发的数，界面不自带。
      const angle = extraPointerAngle(gesture.box, gesture.inverse, clientX, clientY);
      if (angle === null || gesture.angle0 === null) return;
      let delta = angle - gesture.angle0;
      if (delta > 180) delta -= 360; else if (delta < -180) delta += 360;
      if (Math.abs(delta) > 0.5) gesture.moved = true;
      box = { ...gesture.box,
        rotation: Math.round(clamp(gesture.angle + delta, -rotationLimit, rotationLimit) * 10) / 10 };
    } else if (!gesture.corner) {
      box = { ...gesture.box,
        center_x: clamp(gesture.box.center_x + dx, 0, 1),
        center_y: clamp(gesture.box.center_y + dy, 0, 1) };
    } else {
      // 盒自己的角度：先把指针折回未转的盒坐标系（k 那一步也除回来），再按对角那一点算中心与两条边。
      const at = boxVectorFromPointer(point.x / 100 - gesture.box.center_x,
        point.y / 100 - gesture.box.center_y, gesture.angle, gesture.k);
      const ux = gesture.box.center_x + at.x, uy = gesture.box.center_y + at.y;
      const [sx, sy] = gesture.corner;
      const ax = gesture.box.center_x - sx * gesture.box.width / 2;
      const ay = gesture.box.center_y - sy * gesture.box.height / 2;
      box = { ...gesture.box,
        center_x: clamp((ax + ux) / 2, 0, 1),
        center_y: clamp((ay + uy) / 2, 0, 1),
        width: clamp(Math.abs(ux - ax), .01, 2),
        height: clamp(Math.abs(uy - ay), .01, 2) };
    }
    const next = { index: gesture.index, box, duplicate: gesture.duplicate };
    extraDraftRef.current = next;
    setExtraDraft(next);
  };
  const finishExtraAt = (pointerId: number) => {
    const gesture = extraDrag.current;
    if (!gesture || gesture.pointerId !== pointerId) return;
    extraDrag.current = null;
    if (gesture.element.hasPointerCapture(pointerId)) gesture.element.releasePointerCapture(pointerId);
    const draft = extraDraftRef.current;
    const box = draft?.index === gesture.index ? draft.box : null;
    extraDraftRef.current = null;
    setExtraDraft(null);
    if (!gesture.moved || !box) return;
    // 一次抓取一条命令；停在一枚框点上就写回那一枚，否则写静止值。
    const values = gesture.rotate ? { rotation: box.rotation ?? 0 }
      : { center_x: box.center_x, center_y: box.center_y,
        ...(gesture.corner ? { width: box.width, height: box.height } : {}) };
    const mode = gesture.duplicate ? "append" : "replace";
    if (gesture.insertAt !== null) {
      // 停在两枚框点之间：这一拖就是在播放头那一帧**新打一枚**框点，五个数一起带走，
      // 插值抄这一窗起点那一枚——原来那几枚一字不动。
      const at = gesture.insertAt;
      applyExtra(gesture.index, (row) => ({ ...row,
        keys: [...(row.keys ?? []), { at_ticks: at, center_x: box.center_x, center_y: box.center_y,
          width: box.width, height: box.height, rotation: box.rotation ?? 0,
          interpolation: gesture.insertInterp }].sort((a, b) => a.at_ticks - b.at_ticks) }),
      gesture.projectId, gesture.revision, mode);
      return;
    }
    writeExtra(gesture.index, gesture.keyTick, values, gesture.projectId, gesture.revision, mode);
  };
  // 那一块的写入只有一处主人：拖（松手）、停在两枚之间新打一枚、键盘微调，交的都是同一条 `clip.mask_stack`。
  const applyExtra = (index: number, mutate: (row: ShapeMask) => ShapeMask,
    projectId: string, revision: number, mode: "replace" | "append" = "replace") => {
    const stack = clip.extra_masks ?? [];
    const source = stack[index];
    if (!source) return;
    // 「append」就是 Alt 那一手：原来那一串一个不动，副本带着改完的数排在末尾。
    const masks = mode === "append" ? [...stack, mutate(source)]
      : stack.map((row, position) => position === index ? mutate(row) : row);
    setClipMaskStack(clip.id, masks, follow, projectId, revision);
  };
  const writeExtra = (index: number, keyTick: number | null, values: Partial<ShapeMask>,
    projectId: string, revision: number, mode: "replace" | "append" = "replace") => applyExtra(index, (row) => {
      if (keyTick !== null) return { ...row,
        keys: (row.keys ?? []).map((key) => key.at_ticks === keyTick
          ? { ...key, ...values } : key) };
      return { ...row, ...values };
    }, projectId, revision, mode);
  const applyVertex = (next: ShapeMask | null) => {
    if (!next || disabled) return;
    write(next);
    // Stay on the point so the other two ops remain one click away; a delete has nothing left to pick.
    if ((next.vertices?.length ?? 0) < vertices.length) setActive(null);
  };
  const nudgeVertex = (event: React.KeyboardEvent, index: number) => {
    const step = event.shiftKey ? .1 : .01;
    if (!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation(); if (disabled || !mask?.vertices) return;
    svg.current?.focus();
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    write({ ...mask, vertices: mask.vertices.map((entry, position) => position === index ? { ...entry, x: clamp(entry.x + dx, 0, 1), y: clamp(entry.y + dy, 0, 1) } : entry) }, true);
  };
  const pictureImage = draft && compiled ? compiled.image : image;
  // 形变中的那一窗用自己的板框落位：中心曲线照样把它推来推去，因为导出的 overlay x 里加的是同一个
  // offset。没有轮廓帧时，一切与 1.117 之前逐字相同。
  const pictureStyle: CSSProperties = spun
    // 那一张图就是这一窗的角度烘出来的等比图；位置仍由中心两条曲线平移（等比图平移不拧角度）。
    ? { maskImage: spun.image, "--mask-x": mask?.center_x ?? .5, "--mask-y": mask?.center_y ?? .5 } as CSSProperties
    : shapeWindow
    ? { maskImage: shapeWindow.image, ...shapeVariables(shapeWindow), "--mask-x": mask?.center_x ?? .5, "--mask-y": mask?.center_y ?? .5 } as CSSProperties
    : animated
      ? rotated
        // 引擎交的是那张等比的整画面图，这里只把中心两条曲线换成平移；宽/高曲线引擎已经不收。
        ? { maskImage: animated.unit, "--mask-x": mask?.center_x ?? .5, "--mask-y": mask?.center_y ?? .5 } as CSSProperties
        : { maskImage: animated.unit, "--mask-x": mask?.center_x ?? .5, "--mask-y": mask?.center_y ?? .5, "--mask-w": mask?.width ?? 1, "--mask-h": mask?.height ?? 1 } as CSSProperties
      : { maskImage: pictureImage ?? undefined, maskSize: "100% 100%", maskRepeat: "no-repeat" };
  // 1.221：再叠的那几块与主遮罩**相乘**。浏览器这一侧是标准的 `mask-composite: intersect`
  // 叠在同一幅画面上，导出那一侧是同一条 alpha 上多一个括号；两端的图都出自引擎那一份
  // `mask_image`，所以「预览里那个洞」与「成片里那个洞」是同一个洞。
  const primaryImage = spun ? spun.image : shapeWindow ? shapeWindow.image : animated ? animated.unit : pictureImage;
  // 1.238：自己带框点的那一块，引擎把每一窗烘成一张整画面图；这里按播放头挑那一张，
  // 与主遮罩转角的窗表同一个读法（`rotationWindowAt` 只认 from/to）。
  const mainMask = clip.mask;
  const extraPlates = (extra ?? []).map((image, index) => {
    const windows = extraWindows?.[index];
    const window = windows ? rotationWindowAt(windows, local) : null;
    const extraMask = clip.extra_masks?.[index];
    // 1.240：跟随时，不转的那一块用一张单位图，按主遮罩的 `--mask-w/--mask-h` 同比例缩放；
    // 位置 = 主遮罩中心 + 这一块的静止偏移 − 缩放后的一半。转了的那一块不走这一支。
    const unit = Boolean(follow && extraUnits?.[index] && mainMask && extraMask && !extraMask.rotation);
    return {
      image: unit ? extraUnits![index]! : window ? window.image : image,
      own: Boolean(window),
      // 1.241：跟着转了的主遮罩烘出来的那一窗，形状已经在图里，位置仍要按中心平移；
      // 自己带框点的那一窗（follow=false）才是 0,0。
      follow: Boolean(window?.follow),
      unit: unit && !window,
    };
  });
  const layers = [primaryImage, ...extraPlates.map((row) => row.image)].filter(Boolean) as string[];
  // 1.236：`mask-size` 与 `mask-position` 都是**按层**的。这里以前只给一个值，于是主遮罩一动，
  // `mask-position` 就按主遮罩的盒子原点把再叠的那几块一起搬走——预览里的洞与成片里的洞
  // 在中心/宽高曲线下不是同一个（`two_end` 量到过：主遮罩中心 0.515 时预览的再叠块被挪了
  // 0.215，导出那块原地不动）。现在主遮罩一层用自己的方子，再叠的每一层都按自己的整画面图
  // 落在 0,0；它们「只切不动」这句话在两端同时成立。
  const mainSize = shapeWindow
    ? "calc(var(--shape-w) * var(--mask-lw) * 1px) calc(var(--shape-h) * var(--mask-lh) * 1px)"
    : animated && !spun && !rotated
      ? "calc(var(--mask-w) * var(--mask-lw) * 1px) calc(var(--mask-h) * var(--mask-lh) * 1px)"
      : "100% 100%";
  const mainPosition = shapeWindow
    ? "calc((var(--mask-x) + var(--shape-ox) - var(--shape-w) / 2) * var(--mask-lw) * 1px) " +
      "calc((var(--mask-y) + var(--shape-oy) - var(--shape-h) / 2) * var(--mask-lh) * 1px)"
    : spun || (animated && rotated)
      ? "calc((var(--mask-x) - 0.5) * var(--mask-lw) * 1px) " +
        "calc((var(--mask-y) - 0.5) * var(--mask-lh) * 1px)"
      : animated
        ? "calc((var(--mask-x) - var(--mask-w) / 2) * var(--mask-lw) * 1px) " +
          "calc((var(--mask-y) - var(--mask-h) / 2) * var(--mask-lh) * 1px)"
        : "0px 0px";
  // 1.237：跟着走的那几块用主遮罩同一条中心曲线平移——`--mask-x/--mask-y` 减去主遮罩的
  // 静止中心就是「这一帧挪了多少」，它们自己的静止中心仍然烘在自己的图里。大小与角度不跟。
  const followPosition =
    `calc((var(--mask-x) - ${mask?.center_x ?? .5}) * var(--mask-lw) * 1px) ` +
    `calc((var(--mask-y) - ${mask?.center_y ?? .5}) * var(--mask-lh) * 1px)`;
  const extraPosition = follow ? followPosition : "0px 0px";
  const stacked: CSSProperties = layers.length > 1
    ? {
        ...pictureStyle,
        maskImage: layers.join(", "),
        maskSize: [
          mainSize,
          ...extraPlates.map((row, index) => {
            const extraMask = clip.extra_masks?.[index];
            if (!row.unit || !extraMask || !mainMask) return "100% 100%";
            const ratioW = extraMask.width / mainMask.width;
            const ratioH = extraMask.height / mainMask.height;
            return (
              `calc(var(--mask-w) * ${ratioW.toFixed(6)} * var(--mask-lw) * 1px) ` +
              `calc(var(--mask-h) * ${ratioH.toFixed(6)} * var(--mask-lh) * 1px)`
            );
          }),
        ].join(", "),
        maskPosition: [
          mainPosition,
          ...extraPlates.map((row, index) => {
            if (!row.unit) return row.own && !row.follow ? "0px 0px" : extraPosition;
            const extraMask = clip.extra_masks?.[index];
            if (!extraMask || !mainMask) return extraPosition;
            const ratioW = extraMask.width / mainMask.width;
            const ratioH = extraMask.height / mainMask.height;
            const dx = extraMask.center_x - mainMask.center_x;
            const dy = extraMask.center_y - mainMask.center_y;
            const px = dx >= 0 ? `+ ${dx.toFixed(6)}` : `- ${(-dx).toFixed(6)}`;
            const py = dy >= 0 ? `+ ${dy.toFixed(6)}` : `- ${(-dy).toFixed(6)}`;
            return (
              `calc((var(--mask-x) ${px} - 0.5 * var(--mask-w) * ${ratioW.toFixed(6)}) * var(--mask-lw) * 1px) ` +
              `calc((var(--mask-y) ${py} - 0.5 * var(--mask-h) * ${ratioH.toFixed(6)}) * var(--mask-lh) * 1px)`
            );
          }),
        ].join(", "),
        maskRepeat: "no-repeat",
        maskComposite: "intersect",
      }
    : pictureStyle;
  return <>
    <div ref={picture} className={`layer-transform masked-picture${shapeWindow ? " morph-mask" : animated || spun ? (rotated ? " rotated-mask" : " animated-mask") : ""}`} style={stacked}>{children}</div>
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
      onPointerUp={(e) => { const gesture = drag.current; if (!gesture) return; const next = proposed(e); const moved = gesture.moved; cancel(); if (moved) { svg.current?.focus(); const at = Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)); if (morphArmed(clip) && (gesture.vertex !== undefined || gesture.outline)) { recordMaskShape(clip.id, next.vertices ?? [], at, undefined, gesture.projectId, gesture.revision); } else if (gesture.outline && (clip.keyframes ?? []).some((key) => key.property === "mask_x" || key.property === "mask_y")) { moveMaskCentre(clip.id, at, { x: mask.center_x + shift.tx + (next.center_x - mask.center_x), y: mask.center_y + shift.ty + (next.center_y - mask.center_y) }, gesture.projectId, gesture.revision); } else commitMaskEdit(clip.id,next,at,gesture.projectId,gesture.revision); } }} onPointerCancel={cancel} onLostPointerCapture={() => { if (drag.current) cancel(); }}>
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
        {rotated ? <>
          <polygon className="mask-hit" points={corners} onPointerDown={(e) => begin(e, { corner: null })} role="button" tabIndex={0} aria-label="移动遮罩" aria-disabled={disabled} />
          <polygon className="mask-outline" points={corners} />
        </> : <>
        <rect className="mask-hit" x={(mask.center_x - mask.width / 2)*100} y={(mask.center_y - mask.height / 2)*100} width={mask.width*100} height={mask.height*100} onPointerDown={(e) => begin(e, { corner: null })} role="button" tabIndex={0} aria-label="移动遮罩" aria-disabled={disabled} />
        {mask.shape === "ellipse" ? <ellipse className="mask-outline" cx={mask.center_x*100} cy={mask.center_y*100} rx={mask.width*50} ry={mask.height*50} /> : <rect className="mask-outline" x={(mask.center_x-mask.width/2)*100} y={(mask.center_y-mask.height/2)*100} width={mask.width*100} height={mask.height*100} />}
        </>}
        {canRotate ? (() => {
          // 手柄落在「看见的那一个盒」的上边中点外面：有窗表时边是那一窗的边，与参考线同一个盒。
          const ratio = (app.project?.settings.height ?? 9) / (app.project?.settings.width ?? 16);
          const body = spun ? { ...mask, width: spun.width, height: spun.height } : mask;
          const mid = rotatedEdgeMids(body, ratio, spun?.angle ?? mask.rotation);
          const gap = Math.min(0.14, Math.max(0.03, body.height * 0.3));
          const hx = (mid.top.x + mid.out.x * gap) * 100, hy = (mid.top.y + mid.out.y * gap) * 100;
          const at = spun?.angle ?? mask.rotation ?? 0;
          const keyed = (clip.keyframes ?? []).some((key) => key.property === "mask_rotation");
          return <g>
            <line className="mask-rotate-stem" x1={mid.top.x * 100} y1={mid.top.y * 100} x2={hx} y2={hy} />
            <rect className="mask-handle rotate-handle" x={hx - handleSize.x / 2} y={hy - handleSize.y / 2}
              width={handleSize.x} height={handleSize.y} role="button" tabIndex={0}
              aria-label={`旋转遮罩（此刻 ${at.toFixed(1)}°）`}
              aria-disabled={disabled}
              onPointerDown={(e) => begin(e, { rotate: true })}
              onKeyDown={(e) => {
                if (disabled || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
                e.preventDefault(); e.stopPropagation();
                const step = (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 15 : 1);
                write({ ...mask, rotation: Math.round(clamp(at + step, -rotationLimit, rotationLimit) * 10) / 10 });
              }}>
              {/* SVG 的 rect 没有 title 这个属性，说明只能作为子节点挂上去（浏览器原生悬停提示读它）。 */}
              <title>{keyed ? "拖动转这个盒：已经打了角度针，所以写的是播放头这一帧的针；方向键 ±1°，按住 Shift ±15°"
                : "拖动转这个盒：没打角度针，所以改的是遮罩本身那一个角度；方向键 ±1°，按住 Shift ±15°"}</title>
            </rect>
          </g>;
        })() : null}
        <path className="mask-cross" d={`M ${mask.center_x*100-2} ${mask.center_y*100} h 4 M ${mask.center_x*100} ${mask.center_y*100-2} v 4`} />
        {rotated ? null : CORNERS.map(([x,y,label]) => <rect key={label} className="mask-handle" x={(mask.center_x+x*mask.width/2)*100-handleSize.x/2} y={(mask.center_y+y*mask.height/2)*100-handleSize.y/2} width={handleSize.x} height={handleSize.y} role="button" tabIndex={0} aria-label={`缩放遮罩${label}角`} aria-disabled={disabled} onPointerDown={(e) => begin(e,{ corner: [x,y] })} onKeyDown={(e) => {
          if (!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) return;
          e.preventDefault(); e.stopPropagation(); if (disabled) return;
          const step = e.shiftKey ? .1 : .01; svg.current?.focus();
          write({ ...mask, width: clamp(mask.width + (e.key === "ArrowLeft" ? -step*x : e.key === "ArrowRight" ? step*x : 0),.01,2), height: clamp(mask.height + (e.key === "ArrowUp" ? -step*y : e.key === "ArrowDown" ? step*y : 0),.01,2) });
        }} />)}
      </>}
      {extraDrawable && extraBox ? (() => {
        const dragging = extraDraft?.index === selectedIndex ? extraDraft : null;
        const box = dragging ? dragging.box : extraBox;
        const cx = box.center_x * 100, cy = box.center_y * 100;
        const rx = box.width * 50, ry = box.height * 50;
        const hs = { x: Math.max(handleSize.x, 10), y: Math.max(handleSize.y, 10) };
        const angle = box.rotation ?? 0;
        // 这一圈与主遮罩那一圈同一套换算：画框是拉伸的，直接把角度加上去画出来的不是人设的那个盒。
        const points = rotatedBoxPoints(box, pictureRatio, angle);
        const mid = rotatedEdgeMids(box, pictureRatio, angle);
        const top = mid.top;
        // 那颗角度柄沿同一根向外法线摆出去，与主遮罩那颗同一档留白。
        const gap = Math.min(0.14, Math.max(0.03, box.height * 0.3));
        const rx2 = (top.x + mid.out.x * gap) * 100, ry2 = (top.y + mid.out.y * gap) * 100;
        // Alt 那一手在拖的是副本：原来那一框留在原地（淡一档），副本带着柄走。
        const ghost = dragging?.duplicate && extraBox
          ? rotatedBoxPoints(extraBox, pictureRatio, extraBox.rotation ?? 0)
            .map((point) => `${(point.x * 100).toFixed(3)} ${(point.y * 100).toFixed(3)}`).join(", ")
          : null;
        return <g className="mask-extra">
          {ghost ? <polygon className="mask-extra-outline ghost" points={ghost} /> : null}
          <line className="mask-extra-stem" x1={top.x * 100} y1={top.y * 100} x2={rx2} y2={ry2} />
          {box.shape === "ellipse" && !angle
            ? <ellipse className="mask-extra-outline" cx={cx} cy={cy} rx={rx} ry={ry} />
            : <polygon className="mask-extra-outline"
                points={points.map((point) => `${(point.x * 100).toFixed(3)} ${(point.y * 100).toFixed(3)}`).join(", ")} />}
          <rect className="mask-extra-handle" x={top.x * 100 - hs.x / 2} y={top.y * 100 - hs.y / 2}
            width={hs.x} height={hs.y} role="button" tabIndex={0}
            aria-label={`拖动选中的再叠遮罩（第 ${selectedIndex! + 1} 块）`} aria-disabled={disabled}
            onPointerDown={(event) => beginExtra(event, null)}>
            <title>{"拖这颗柄搬这一块的中心；拖四个角改大小（盒自己转着时按未转的盒算）。停在框点上时改的是那一枚，否则改静止值。"
              + (canDuplicate ? "按住 Alt 拖 = 先复制这一块，再拖那一副本。"
                : `已到 ${extraStackLimit} 块上限，Alt 这一手用不了：先在检查器删掉一块。`)}</title>
          </rect>
          <rect className="mask-extra-handle rotate-handle" x={rx2 - hs.x / 2} y={ry2 - hs.y / 2}
            width={hs.x} height={hs.y} role="button" tabIndex={0}
            aria-label={`旋转选中的再叠遮罩（第 ${selectedIndex! + 1} 块·此刻 ${angle.toFixed(1)}°）`}
            aria-disabled={disabled}
            onPointerDown={(event) => beginExtra(event, null, true)}
            onKeyDown={(event) => {
              if (disabled || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
              event.preventDefault(); event.stopPropagation();
              const step = (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 15 : 1);
              const next = Math.round(clamp(angle + step, -rotationLimit, rotationLimit) * 10) / 10;
              if (next === angle || !app.project) return;
              writeExtra(selectedIndex!, selectedKey?.at_ticks ?? null, { rotation: next },
                app.project.id, app.project.revision);
            }}>
            <title>{selectedKey ? "拖这颗柄转这一块：播放头正停在一枚框点上，写的是那一枚的角度；方向键 ±1°，按住 Shift ±15°"
              : "拖这颗柄转这一块：没停在一枚框点上，改的是这一块的静止角度；方向键 ±1°，按住 Shift ±15°"}</title>
          </rect>
          {CORNERS.map(([sx, sy, label], index) => <rect key={label} className="mask-extra-handle corner"
            x={points[index].x * 100 - hs.x / 2} y={points[index].y * 100 - hs.y / 2} width={hs.x} height={hs.y}
            role="button" tabIndex={0} aria-label={`缩放选中的再叠遮罩（第 ${selectedIndex! + 1} 块·${label}）`}
            aria-disabled={disabled} onPointerDown={(event) => beginExtra(event, [sx, sy])}>
            <title>拖这一角改这一块的大小（盒自己转着时按未转的盒算）；停在框点上时改的是那一枚。</title>
          </rect>)}
        </g>;
      })() : null}
    </svg> : null}
    {visible && rotated ? <div className="mask-vertex-panel note" role="group" aria-label="旋转遮罩的说明"
      title={"画面上这框就是转过角度的遮罩盒：拖它只搬中心；宽/高也打针时引擎每窗重烘一张图"
        + "（角度与两条边在同一些帧边界上换），检查器那两格照样能改大小；导出走同一份阶梯。"}
      ><span className="dim">{spun ? `这一格的角度是 ${spun.angle.toFixed(1)}°（${rotation?.length ?? 0} 段窗）` : "转过角度的遮罩盒"} · 拖框只搬中心</span></div> : null}
    {visible && mask?.shape === "path" ? <div className="mask-vertex-panel" role="group" aria-label="顶点操作">
      {atCap ? <span className="dim">顶点 {vertices.length}/{vertexLimit}，已到上限，双击不再加点</span> : null}
      {morphArmed(clip) ? <>
        <span className="dim" title="导出与预览都按引擎这份一格一步的窗执行：这一格里的形状就是成片与预览里的形状">{`轮廓窗 第 ${shapeWindowIndex(shape, local)} / ${shape?.length ?? 0} 格`}</span>
        <button type="button" className="btn tiny" disabled={disabled || !shapeWindow || !app.project} title={shapeWindow ? "把现在看到的这一格轮廓记在播放头这一刻：形状不动，但从此以后可以在它前后继续改。同一时刻再记一次是顶替。" : "拖动中不能记帧：先松开鼠标"} onClick={() => { if (app.project) recordMaskShape(clip.id, vertices, local, undefined, app.project.id, app.project.revision); }}>钉住此刻的轮廓</button>
      </> : null}
      {active !== null ? <>
        <span className="dim">选中顶点 {active + 1}</span>
        <button type="button" className="btn tiny" disabled={disabled || !withoutVertex(mask, active)} title={vertices.length <= 3 ? "只剩三个顶点，不能再删" : "删掉这个顶点"} onClick={() => applyVertex(withoutVertex(mask, active))}>删除顶点</button>
        <button type="button" className="btn tiny" disabled={disabled || !asCorner(mask, active)} title="把两条控制柄收掉，曲线在这个点折断" onClick={() => applyVertex(asCorner(mask, active))}>抹成角点</button>
        <button type="button" className="btn tiny" disabled={disabled || !asSmooth(mask, active)} title="按左右两个顶点补出控制柄" onClick={() => applyVertex(asSmooth(mask, active))}>自动平滑</button>
      </> : null}
    </div> : null}
  </>;
}
