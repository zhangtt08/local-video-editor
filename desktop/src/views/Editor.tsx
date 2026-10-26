import { useEffect, useRef, useState, type CSSProperties } from "react";

import { Icon } from "../ui";
import { Assets } from "./Assets";
import { CurveEditor } from "./CurveEditor";
import { Preview, PreviewFooter } from "./Preview";
import { Timeline } from "./Timeline";
import { RightPanel } from "../shell/RightPanel";
import { firstRunTimeline, resetLayout } from "../layoutReset";
import { dismissRemote, openProject, openSequence, setView, setGraphOpen, markSplitterTouched, toggleHelp, useApp } from "../store";

const COACH_KEY = "agentcut.coach.dismissed";

/**
 * 编辑工作台：素材与监视器在上，时间线横跨整行，右侧一列从头贯到底。
 * 三格宽度与时间线高度仍由同一条 `agentcut.layout` 记住——换布局不该换掉人的习惯。
 */
export function Editor() {
  const app = useApp();
  const [layout, setLayout] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("agentcut.layout") ?? "null");
      if (Array.isArray(saved) && saved.length === 3 && saved.every((n: unknown) => typeof n === "number" && Number.isFinite(n))) return saved as number[];
    } catch { /* 用默认工作台布局 */ }
    return [300, 340, firstRunTimeline(typeof window === "undefined" ? 0 : window.innerHeight)];
  });
  const drag = useRef<{ axis: number; x: number; y: number; origin: number[] } | null>(null);
  useEffect(() => { try { localStorage.setItem("agentcut.layout", JSON.stringify(layout)); } catch { /* 布局仍然可用 */ } }, [layout]);

  const splitter = (axis: number) => (
    <div
      className={`splitter ${axis === 2 ? "horizontal" : "vertical"}`}
      role="separator"
      tabIndex={0}
      aria-label={axis === 2 ? "调整时间线高度" : axis === 0 ? "调整素材面板宽度" : "调整属性面板宽度"}
      aria-orientation={axis === 2 ? "horizontal" : "vertical"}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        if (axis === 2) markSplitterTouched();
        drag.current = { axis, x: event.clientX, y: event.clientY, origin: layout };
      }}
      onPointerMove={(event) => {
        if (!drag.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
        const d = drag.current;
        const next = [...d.origin];
        const delta = axis === 2 ? d.y - event.clientY : axis === 0 ? event.clientX - d.x : d.x - event.clientX;
        next[axis] = Math.min(axis === 2 ? window.innerHeight - 320 : 480, Math.max(axis === 2 ? 180 : axis === 0 ? 220 : 300, d.origin[axis] + delta));
        setLayout(next);
      }}
      onPointerUp={() => { drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}
      onKeyDown={(event) => {
        const direction = ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : 0;
        if (!direction) return;
        event.preventDefault();
        if (axis === 2) markSplitterTouched();
        const next = [...layout];
        next[axis] = Math.max(axis === 2 ? 180 : axis === 0 ? 220 : 300, Math.min(axis === 2 ? window.innerHeight - 320 : 480, next[axis] + direction * 16));
        setLayout(next);
      }}
    />
  );

  const [coach, setCoach] = useState(() => {
    try {
      return localStorage.getItem(COACH_KEY) !== "1";
    } catch {
      return true;
    }
  });
  const hasClips = Boolean(app.project && Object.keys(app.project.clips).length);

  useEffect(() => {
    if (hasClips) setCoach(false);
  }, [hasClips]);

  return (
    <div
      className={`editor2${app.monitorMode === "source" ? " source-open" : ""}`}
      style={{ "--timeline-height": `${layout[2]}px`, "--assets-w": `${layout[0]}px`, "--right-w": `${layout[1]}px` } as CSSProperties}
    >
      {app.remoteAhead && app.project && app.remoteAhead > app.project.revision ? (
        <div className="remote-banner" role="status" title={`Agent 写到了 r${app.remoteAhead}，你手上这份是 r${app.project.revision}`}>
          <Icon name="robot" size={14} />
          <span>Agent 已更新这条时间线</span>
          <span className="spacer" />
          <button className="btn tiny" onClick={() => void openProject(app.project!.id)} title="载入最新版本，你的未提交批次会保留在批次里">载入最新</button>
          <button className="btn tiny subtle" onClick={() => setView("history")} title="看是谁在什么时候改的">查看变更</button>
          <button className="btn tiny subtle" onClick={dismissRemote} title="继续按当前版本工作">稍后</button>
        </div>
      ) : null}

      <section className="ed-assets" aria-label="素材库"><Assets /></section>
      <div className="ed-vsplit">{splitter(0)}</div>
      <section className="ed-center" aria-label="监视器">
        <Preview key={`${app.project?.id}:${app.sequenceId ?? "root"}`} />
        <PreviewFooter />
      </section>
      <div className="ed-vsplit">{splitter(1)}</div>
      <div className="ed-right"><RightPanel /></div>

      <div className="ed-hsplit">{splitter(2)}</div>
      <section className="ed-timeline" aria-label="时间线工作区">
        <div className="tl-workbench">
          <Icon name="film" size={14} />
          <nav className="sequence-path" aria-label="合成导航">
            <button className="tb-mini" disabled={Boolean(app.busy || app.batch.length || !app.sequenceId)} onClick={() => openSequence(null)}>主时间线</button>
            {app.sequencePath.map((id) => (
              <span key={id}>› <button className="tb-mini" aria-current={id === app.sequenceId ? "page" : undefined} disabled={Boolean(app.busy || app.batch.length)} onClick={() => openSequence(id)}>{app.project?.sequences?.[id]?.name ?? "合成"}</button></span>
            ))}
          </nav>
          <span className={`tag ${app.mode === "batch" ? "accent" : "off"}`} title={app.mode === "batch" ? "动作先进待提交批次，预演通过再写入" : "每个动作立刻写成一条命令批次并提交"}>
            {app.mode === "batch" ? "批次" : "即时"}
          </span>
          <span className="spacer" />
          <div className="seg mini"><button aria-pressed={!app.graphOpen} className={!app.graphOpen ? "active" : ""} onClick={() => setGraphOpen(false)}>时间线</button><button aria-pressed={app.graphOpen} className={app.graphOpen ? "active" : ""} onClick={() => setGraphOpen(true)}>动画曲线</button></div>
          <button className="tb-mini" onClick={() => setLayout(resetLayout(document.querySelector<HTMLElement>(".timeline")?.getBoundingClientRect().height ?? 0))}>重置布局</button>
          <button className="tb-mini" onClick={() => toggleHelp(true)}><Icon name="keyboard" size={12} />快捷键</button>
        </div>
        {app.graphOpen ? <CurveEditor key={`${app.project?.id}:${app.sequenceId ?? "root"}`} /> : <Timeline key={`${app.project?.id}:${app.sequenceId ?? "root"}`} />}
      </section>

      {coach ? (
        <div className="coach coach-float">
          {["导入素材", "拖上时间线", "空格预览", "剪刀分割", "右侧导出"].map((item, index, all) => (
            <span className="coach-step" key={item}>
              <b className="coach-n">{index + 1}</b>
              {item}
              {index < all.length - 1 ? <span className="coach-arrow">›</span> : null}
            </span>
          ))}
          <span className="spacer" />
          <button type="button" className="btn subtle tiny" onClick={() => toggleHelp(true)}>怎么用？</button>
          <button
            type="button"
            className="btn subtle tiny"
            title="不再显示这条引导"
            onClick={() => {
              try {
                localStorage.setItem(COACH_KEY, "1");
              } catch { /* 下次还会显示 */ }
              setCoach(false);
            }}
          >✕</button>
        </div>
      ) : null}
    </div>
  );
}
