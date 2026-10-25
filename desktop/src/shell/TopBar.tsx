import { useState } from "react";

import { chordWords } from "../keymap";
import { Icon } from "../ui";
import {
  keymap,
  openEditorPanel,
  openSequence,
  redoStep,
  refreshWindowState,
  setView,
  toggleHelp,
  undo,
  updateProjectMeta,
  useApp,
  windowControl,
} from "../store";
import { rateLabel } from "../time";

/** 顶栏：面包屑说「你在哪条时间线」，右边是撤销 / 交付档位 / 导出与窗口控制。 */
export function TopBar() {
  const app = useApp();
  const project = app.project;
  const [editing, setEditing] = useState(false);
  const viewLabel = app.view === "home" ? "项目" : app.view === "history" ? "历史" : app.view === "agent" ? "Agent" : "剪辑";
  const height = project?.settings.height ?? 1080;
  const rate = project?.settings.frame_rate;

  return (
    <header className="topbar">
      <div className="crumbs">
        <button type="button" className="crumb" onClick={() => setView("home")}>{viewLabel}</button>
        <span className="crumb-sep">/</span>
        {project ? (
          editing ? (
            <input
              className="crumb-input"
              autoFocus
              defaultValue={project.name}
              maxLength={256}
              aria-label="工程名称"
              onBlur={(event) => {
                const name = event.target.value.trim();
                setEditing(false);
                if (name && name !== project.name) void updateProjectMeta({ name });
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.currentTarget.blur();
                if (event.key === "Escape") { event.currentTarget.value = project.name; event.currentTarget.blur(); }
              }}
            />
          ) : (
            <button type="button" className="crumb-current" onDoubleClick={() => setEditing(true)} title="双击重命名">
              {project.name}
              <Icon name="check" size={11} className="crumb-pencil" />
            </button>
          )
        ) : (
          <span className="crumb-current idle">未打开工程</span>
        )}
        {project && app.sequencePath.length ? (
          <nav className="crumb-seq" aria-label="合成导航">
            <button type="button" className="chip-seq" onClick={() => void openSequence(null)}>主时间线</button>
            {app.sequencePath.map((id) => (
              <span key={id} className="crumb-seq-item">
                <span className="crumb-sep">›</span>
                <button
                  type="button"
                  className={`chip-seq${id === app.sequenceId ? " active" : ""}`}
                  onClick={() => void openSequence(id)}
                >
                  {app.project?.sequences?.[id]?.name ?? "合成"}
                </button>
              </span>
            ))}
          </nav>
        ) : null}
        {app.batch.length ? (
          <span className="batch-dot" title={`批次里还有 ${app.batch.length} 条未提交的命令，先去交付面板或时间线里提交`} aria-label={`${app.batch.length} 条待提交`} />
        ) : null}
      </div>

      <div className="topbar-right">
        <div className="tb-icon-group">
          <button
            type="button"
            className="tb-icon"
            title={`撤销（${chordWords(keymap()["undo"])}）`}
            aria-label="撤销"
            disabled={!app.undo.length || Boolean(app.busy)}
            onClick={() => void undo()}
          >
            <Icon name="undo" size={15} />
          </button>
          <button
            type="button"
            className="tb-icon"
            title={`重做（${chordWords(keymap()["redo"])}）`}
            aria-label="重做"
            disabled={!app.redo.length || Boolean(app.busy)}
            onClick={() => void redoStep()}
          >
            <Icon name="redo" size={15} />
          </button>
        </div>

        <button
          type="button"
          className="tb-chip"
          disabled={!project}
          onClick={() => openEditorPanel("export")}
          title={project ? `${project.settings.width}×${project.settings.height} · ${rate ? rateLabel(rate) : "30/1"}；点开导出面板改交付档` : "先打开一个工程"}
        >
          {height}P
          <Icon name="chevron" size={10} />
        </button>

        <button
          type="button"
          className="tb-export"
          disabled={!project}
          onClick={() => openEditorPanel("export")}
          title={project ? `导出这条时间线（${chordWords(keymap()["export-panel"])}）` : "先打开一个工程"}
        >
          <Icon name="export" size={14} />
          导出
        </button>

        <button
          type="button"
          className={`conn compact ${app.phase === "ready" ? "on" : "off"}`}
          title={app.phase === "ready"
            ? `引擎在线：${app.info?.base_url ?? ""}
版本：${app.caps?.app_version ?? "?"} · schema v${app.caps?.project_schema_version ?? "?"}
点一下看设置与存储`
            : "剪辑引擎未连接，点一下重试"}
          aria-label={app.phase === "ready" ? "引擎在线" : "引擎未连接"}
          onClick={() => (app.phase === "ready" ? toggleHelp(true) : void refreshWindowState())}
        >
          <span className="dot" />
        </button>

        <button type="button" className="tb-icon" title="帮助与快捷键（F1）" aria-label="帮助" onClick={() => toggleHelp(true)}>
          <Icon name="keyboard" size={15} />
        </button>

        <div className="win-controls">
          <button type="button" className="win-btn" title="最小化" aria-label="最小化" onClick={() => void windowControl("minimize")}>
            <Icon name="minimize" size={12} />
          </button>
          <button
            type="button"
            className="win-btn"
            title={app.window.maximized ? "向下还原" : "最大化"}
            aria-label={app.window.maximized ? "向下还原" : "最大化"}
            onClick={() => { void windowControl(app.window.maximized ? "restore" : "maximize").then(() => refreshWindowState()); }}
          >
            <Icon name={app.window.maximized ? "restore" : "maximize"} size={11} />
          </button>
          <button type="button" className="win-btn close" title="关闭 AgentCut" aria-label="关闭" onClick={() => void windowControl("close")}>
            <Icon name="close" size={12} />
          </button>
        </div>
      </div>
    </header>
  );
}
