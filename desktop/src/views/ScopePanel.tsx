import { useEffect, useRef, useState } from "react";

import { Icon } from "../ui";
import { drawScope, histogram, vectorscope, waveform } from "../scopes";
import { appInfo, useApp, usePlay } from "../store";
import { frameTicks, timecode } from "../time";

type ScopeKind = "histogram" | "waveform" | "vectorscope";
const LABEL: Record<ScopeKind, string> = { histogram: "直方图", waveform: "波形", vectorscope: "矢量" };

/** Measure the same composition graph used for export, with one request in flight. */
export function ScopePanel() {
  const app = useApp();
  const head = usePlay();
  const [kind, setKind] = useState<ScopeKind>("histogram");
  const [note, setNote] = useState("");
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const lastFrame = useRef<ImageData | null>(null);
  const cursor = useRef(head.ticks);
  const selectedKind = useRef(kind);
  cursor.current = head.ticks;
  selectedKind.current = kind;

  useEffect(() => {
    if (canvas.current) render(canvas.current, lastFrame.current, kind);
  }, [kind]);

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const observer = new ResizeObserver(() => render(node, lastFrame.current, selectedKind.current));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const project = app.project;
    const engine = appInfo.engine();
    const node = canvas.current;
    lastFrame.current = null;
    if (node) render(node, null, selectedKind.current);
    if (!project || !engine || !node) return;
    if (app.monitorMode === "source") {
      setNote("切回时间线预览，以测量合成画面");
      return;
    }
    if (!Object.keys(project.clips).length) {
      setNote("时间线上还没有画面");
      return;
    }
    let live = true;
    let inFlight = false;
    let lastTicks = -1;
    let retryAt = 0;
    const controller = new AbortController();
    const tick = async () => {
      const at = Math.floor(cursor.current / frameTicks(project.settings.frame_rate)) * frameTicks(project.settings.frame_rate);
      if (!live || inFlight || lastTicks === at || performance.now() < retryAt) return;
      inFlight = true;
      if (!lastFrame.current) setNote("正在计算合成画面…");
      try {
        const result = await engine.frame(project.id, project.revision, at, AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]), app.sequenceId);
        const bitmap = await createImageBitmap(result.blob);
        try {
          if (!live) return;
          const buffer = document.createElement("canvas");
          buffer.width = bitmap.width;
          buffer.height = bitmap.height;
          const context = buffer.getContext("2d", { willReadFrequently: true });
          if (!context) throw new Error("无法读取合成画面");
          context.drawImage(bitmap, 0, 0);
          lastFrame.current = context.getImageData(0, 0, buffer.width, buffer.height);
          render(node, lastFrame.current, selectedKind.current);
          lastTicks = at;
          setNote(`合成采样 ${timecode(result.atTicks, project.settings.frame_rate)}${cursor.current !== at ? " · 后台更新" : ""}`);
        } finally { bitmap.close(); }
      } catch (error) {
        if (live) {
          lastFrame.current = null;
          render(node, null, selectedKind.current);
          setNote(error instanceof Error ? error.message : "合成画面暂不可用");
          retryAt = performance.now() + 3000;
        }
      } finally { inFlight = false; }
    };
    const timer = setInterval(() => void tick(), 500);
    void tick();
    return () => { live = false; controller.abort(); clearInterval(timer); };
  }, [app.project?.id, app.project?.revision, app.monitorMode, app.sequenceId]);

  return (
    <div className="scope-panel">
      <div className="panel-head rail-tabs">
        {(Object.keys(LABEL) as ScopeKind[]).map((item) => (
          <button key={item} type="button" className={kind === item ? "active" : ""} onClick={() => setKind(item)}>
            <Icon name={item === "vectorscope" ? "spark" : item === "waveform" ? "music" : "info"} size={12} /> {LABEL[item]}
          </button>
        ))}
      </div>
      <div className="scope-body">
        <canvas ref={canvas} className="scope-canvas" role="img" aria-label={`${LABEL[kind]}示波器`} />
        <p className="hint">{note}</p>
      </div>
    </div>
  );
}

function render(canvas: HTMLCanvasElement, frameData: ImageData | null, kind: ScopeKind) {
  if (!frameData) {
    drawScope(canvas, (ctx, w, h) => {
      ctx.fillStyle = "#12131a";
      ctx.fillRect(0, 0, w, h);
    });
    return;
  }
  if (kind === "histogram") {
    const result = histogram({ data: frameData.data, width: frameData.width, height: frameData.height }, 64);
    drawScope(canvas, (ctx, w, h) => {
      ctx.fillStyle = "#0e0f14";
      ctx.fillRect(0, 0, w, h);
      const channels: [Float32Array, string][] = [
        [result.r, "rgba(255,96,96,.85)"],
        [result.g, "rgba(96,255,140,.85)"],
        [result.b, "rgba(120,170,255,.85)"],
        [result.luma, "rgba(235,235,245,.75)"],
      ];
      ctx.strokeStyle = "rgba(255,255,255,.06)";
      for (let i = 1; i < 4; i += 1) {
        ctx.beginPath();
        ctx.moveTo((i * w) / 4, 0);
        ctx.lineTo((i * w) / 4, h);
        ctx.stroke();
      }
      for (const [values, color] of channels) {
        ctx.strokeStyle = color;
        ctx.beginPath();
        values.forEach((value, index) => {
          const x = (index / (values.length - 1)) * w;
          const y = h - value * (h - 2);
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
    });
    return;
  }
  if (kind === "waveform") {
    const result = waveform({ data: frameData.data, width: frameData.width, height: frameData.height }, 120, 68);
    drawScope(canvas, (ctx, w, h) => {
      ctx.fillStyle = "#0b1410";
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(255,255,255,.07)";
      for (let i = 1; i < 4; i += 1) {
        ctx.beginPath();
        ctx.moveTo(0, (i * h) / 4);
        ctx.lineTo(w, (i * h) / 4);
        ctx.stroke();
      }
      const plot = (values: Float32Array, color: string) => {
        ctx.fillStyle = color;
        for (let x = 0; x < result.width; x += 1) {
          for (let y = 0; y < result.height; y += 1) {
            if (values[x * result.height + y] <= 0) continue;
            ctx.fillRect((x / result.width) * w, (y / result.height) * h, w / result.width + 0.6, h / result.height + 0.6);
          }
        }
      };
      plot(result.r, "rgba(255,90,90,.55)");
      plot(result.g, "rgba(90,255,140,.55)");
      plot(result.b, "rgba(120,170,255,.55)");
    });
    return;
  }
  const scope = vectorscope({ data: frameData.data, width: frameData.width, height: frameData.height }, 96);
  drawScope(canvas, (ctx, w, h) => {
    ctx.fillStyle = "#0c0c14";
    ctx.fillRect(0, 0, w, h);
    const radius = Math.min(w, h) / 2 - 4;
    ctx.strokeStyle = "rgba(255,255,255,.14)";
    for (const ratio of [0.33, 0.66, 1]) {
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, radius * ratio, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(w / 2 - radius, h / 2);
    ctx.lineTo(w / 2 + radius, h / 2);
    ctx.moveTo(w / 2, h / 2 - radius);
    ctx.lineTo(w / 2, h / 2 + radius);
    ctx.stroke();
    ctx.fillStyle = "rgba(150,255,190,.85)";
    const cell = radius * 2 / (scope.size - 1);
    for (let y = 0; y < scope.size; y += 1) {
      for (let x = 0; x < scope.size; x += 1) {
        const value = scope.grid[y * scope.size + x];
        if (value < 0.12) continue;
        ctx.globalAlpha = 0.25 + value * 0.75;
        ctx.fillRect(w / 2 + (x - scope.size / 2) * cell, h / 2 + (y - scope.size / 2) * cell, cell + 0.5, cell + 0.5);
      }
    }
    ctx.globalAlpha = 1;
  });
}
