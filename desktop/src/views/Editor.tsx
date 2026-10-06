import { useEffect, useRef, useState, type CSSProperties } from "react";

import { Icon } from "../ui";
import { Assets } from "./Assets";
import { ExportPanel } from "./ExportPanel";
import { Inspector } from "./Inspector";
import { Preview, PreviewFooter } from "./Preview";
import { ScopePanel } from "./ScopePanel";
import { Timeline } from "./Timeline";
import { CurveEditor } from "./CurveEditor";
import { dismissRemote, openProject, openSequence, setView, setEditorPanel, setGraphOpen, toggleHelp, useApp } from "../store";

const COACH_KEY = "agentcut.coach.dismissed";

export function Editor() {
  const app = useApp();
  const tab = app.editorPanel;
  const [layout, setLayout] = useState(() => {
    try { const saved = JSON.parse(localStorage.getItem("agentcut.layout") ?? "null");
      if (Array.isArray(saved) && saved.length === 3 && saved.every((n: unknown) => typeof n === "number" && Number.isFinite(n))) return saved as number[];
    } catch { /* Use the standard workbench layout. */ }
    return [280, 320, 300];
  });
  const drag = useRef<{ axis: number; x: number; y: number; origin: number[] } | null>(null);
  useEffect(() => { try { localStorage.setItem("agentcut.layout", JSON.stringify(layout)); } catch { /* Layout still works. */ } }, [layout]);
  const splitter = (axis: number) => <div className={`splitter ${axis === 2 ? "horizontal" : "vertical"}`}
    role="separator" tabIndex={0} aria-label={axis === 2 ? "调整时间线高度" : axis === 0 ? "调整素材面板宽度" : "调整属性面板宽度"}
    aria-orientation={axis === 2 ? "horizontal" : "vertical"}
    onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); drag.current = { axis, x: event.clientX, y: event.clientY, origin: layout }; }}
    onPointerMove={(event) => { if (!drag.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
      const d = drag.current; const next = [...d.origin];
      const delta = axis === 2 ? d.y - event.clientY : axis === 0 ? event.clientX - d.x : d.x - event.clientX;
      next[axis] = Math.min(axis === 2 ? window.innerHeight - 320 : 460, Math.max(axis === 2 ? 180 : axis === 0 ? 220 : 280, d.origin[axis] + delta)); setLayout(next);
    }}
    onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
    onKeyDown={(event) => { const direction = ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : 0;
      if (direction) { event.preventDefault(); const next = [...layout]; next[axis] = Math.max(axis === 2 ? 180 : axis === 0 ? 220 : 280, Math.min(axis === 2 ? window.innerHeight - 320 : 460, next[axis] + direction * 16)); setLayout(next); } }} />;
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
    <div className={`editor${app.monitorMode === "source" ? " source-open" : ""}`} style={{ "--timeline-height": `${layout[2]}px` } as CSSProperties}>
      <div className="workbench-bar"><Icon name="film" size={14} /><nav className="sequence-path" aria-label="合成导航"><button className="btn tiny subtle" disabled={Boolean(app.busy || app.batch.length || !app.sequenceId)} onClick={() => openSequence(null)}>主时间线</button>{app.sequencePath.map((id) => <span key={id}>› <button className="btn tiny subtle" aria-current={id === app.sequenceId ? "page" : undefined} disabled={Boolean(app.busy || app.batch.length)} onClick={() => openSequence(id)}>{app.project?.sequences?.[id]?.name ?? "合成"}</button></span>)}</nav><span className="spacer" />
        <div className="seg mini"><button aria-pressed={!app.graphOpen} className={!app.graphOpen ? "active" : ""} onClick={() => setGraphOpen(false)}>时间线</button><button aria-pressed={app.graphOpen} className={app.graphOpen ? "active" : ""} onClick={() => setGraphOpen(true)}>动画曲线</button></div>
        <button className="btn tiny subtle" onClick={() => setLayout([280, 320, 300])}>重置布局</button>
        <button className="btn tiny subtle" onClick={() => toggleHelp(true)}><Icon name="keyboard" size={12} />快捷键</button>
      </div>
      {app.remoteAhead && app.project && app.remoteAhead > app.project.revision ? (
        <div className="remote-banner" role="status">
          <Icon name="robot" size={13} />
          <span>
            Agent 已把这条时间线改到 <b className="mono">r{app.remoteAhead}</b>（你看到的是 r{app.project.revision}）
          </span>
          <span className="spacer" />
          <button className="btn tiny" onClick={() => void openProject(app.project!.id)} title="载入最新版本，你的未提交批次会保留在批次里">
            载入最新
          </button>
          <button className="btn tiny subtle" onClick={() => setView("history")} title="看是谁在什么时候改的">
            查看变更
          </button>
          <button className="btn tiny subtle" onClick={dismissRemote} title="继续按当前版本工作">
            稍后
          </button>
        </div>
      ) : null}
      {coach ? <Coach onClose={() => {
        try {
          localStorage.setItem(COACH_KEY, "1");
        } catch {
          /* 隐私模式写不进就算了，下次还会显示 */
        }
        setCoach(false);
      }} /> : null}
      <div className="editor-main" style={{ gridTemplateColumns: `minmax(220px, min(${layout[0]}px, 27vw)) 5px minmax(280px, 1fr) 5px minmax(280px, min(${layout[1]}px, 31vw))` }}>
        <Assets />
        {splitter(0)}
        <div className="center-col">
          <Preview key={`${app.project?.id}:${app.sequenceId ?? "root"}`} />
          <PreviewFooter />
        </div>
        {splitter(1)}
        <aside className="panel right">
          <div className="panel-head rail-tabs">
            <button type="button" className={tab === "inspect" ? "active" : ""} onClick={() => setEditorPanel("inspect")} title="选中片段后在这里看并改它的时间">
              <Icon name="info" size={12} /> 检查器
            </button>
            <button type="button" className={tab === "export" ? "active" : ""} onClick={() => setEditorPanel("export")} title="把这条时间线导出成视频文件">
              <Icon name="export" size={12} /> 导出
            </button>
            <button type="button" className={tab === "scope" ? "active" : ""} onClick={() => setEditorPanel("scope")} title="像调色师一样看直方图、波形和矢量">
              <Icon name="spark" size={12} /> 示波器
            </button>
          </div>
          {tab === "inspect" ? <Inspector /> : tab === "scope" ? <ScopePanel /> : <ExportPanel />}
        </aside>
      </div>
      {splitter(2)}
      {app.graphOpen ? <CurveEditor key={`${app.project?.id}:${app.sequenceId ?? "root"}`} /> : <Timeline key={`${app.project?.id}:${app.sequenceId ?? "root"}`} />}
    </div>
  );
}

const STEPS = ["导入素材", "拖上时间线", "空格预览", "剪刀分割", "右侧导出"];

function Coach({ onClose }: { onClose: () => void }) {
  return (
    <div className="coach">
      {STEPS.map((item, index) => (
        <span className="coach-step" key={item}>
          <b className="coach-n">{index + 1}</b>
          {item}
          {index < STEPS.length - 1 ? <span className="coach-arrow">›</span> : null}
        </span>
      ))}
      <span className="spacer" />
      <button type="button" className="btn subtle" onClick={() => toggleHelp(true)} title="区域说明与快捷键（F1）">
        怎么用？
      </button>
      <button type="button" className="btn subtle" onClick={onClose} title="不再显示这条引导">
        ✕
      </button>
    </div>
  );
}
