import { useState } from "react";

import { BrandMark, Icon } from "./ui";
import { chordWords } from "./keymap";
import { TIMEBASE } from "./time";
import { appInfo, boot, keymap, refreshWindowState, setView, openEditorPanel, toast, toggleHelp, updateProjectMeta, useApp, windowControl } from "./store";

const TABS = [
  { view: "home", label: "项目", icon: "folder", hint: "所有工程都在这里：一个工程就是一条时间线" },
  { view: "editor", label: "剪辑", icon: "film", hint: "素材、画面、时间线——人工审校与调整的主工作区" },
  { view: "history", label: "历史", icon: "history", hint: "每一次写入都可回滚，revision 只进不退" },
  { view: "agent", label: "Agent", icon: "robot", hint: "把同一个引擎接给你的 AI：密钥、MCP 配置、实时写入审计" },
] as const;

/**
 * 无边框窗口的自制标题栏：最小化 / 最大化 / 关闭画在软件里，
 * 和导航、连接状态、版本徽章共用同一行，让窗口看起来是一个整体产品而不是网页。
 */
export function TitleBar() {
  const app = useApp();
  const [editing, setEditing] = useState(false);
  const project = app.project;
  const live = app.phase === "ready";
  const base = app.info?.base_url ?? "";

  return (
    <header className="titlebar">
      <div className="tb-left">
        <span className="brand">
          <BrandMark size={18} />
          AgentCut
        </span>
        <span className="tb-sep" />
        {editing && project ? (
          <RenameInput name={project.name} onDone={() => setEditing(false)} />
        ) : project ? (
          <button
            type="button"
            className="tb-project"
            onClick={() => setView("editor")}
            onDoubleClick={() => setEditing(true)}
            title={`工程 id：${project.id}\n双击重命名`}
          >
            {project.name}
            <span className="tb-project-id mono">{project.id}</span>
          </button>
        ) : (
          <span className="tb-project idle">未打开工程</span>
        )}
        {project ? (
          <span className="rev-chip mono" title="当前 revision：每次写入 +1，历史只进不退">
            r{project.revision}
          </span>
        ) : null}
      </div>

      <nav className="tb-tabs" aria-label="主视图">
        {TABS.map((tab) => {
          const enabled = tab.view === "home" || tab.view === "agent" || Boolean(project);
          return (
            <button
              key={tab.view}
              type="button"
              className={`tb-tab${app.view === tab.view ? " active" : ""}`}
              onClick={() => setView(enabled ? tab.view : "home")}
              title={enabled ? tab.hint : "先打开一个工程"}
            >
              <Icon name={tab.icon} size={13} />
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div className="tb-right">
        {project ? <button className="btn primary tiny" title={`导出视频（${chordWords(keymap()["export-panel"])}）`} onClick={() => openEditorPanel("export")}><Icon name="export" size={12} />导出</button> : null}
        <button
          type="button"
          className={`conn ${live ? "on" : "off"}`}
          title={
            live
              ? `引擎在线：${base}\n版本：${app.caps?.app_version ?? "（尚未读到 capabilities）"} · 工程 schema v${app.caps?.project_schema_version ?? "?"}\nFFmpeg：${app.info?.ffmpeg || "未找到"}\n素材目录：${(app.info?.media_roots ?? []).length} 个\n1 秒 = ${TIMEBASE.toLocaleString("en-US")} tick`
              : "剪辑引擎未连接，点击重试"
          }
          onClick={() => (live ? toast("info", "引擎在线", base) : void boot())}
        >
          <span className="dot" />
          {live ? `引擎在线${app.caps?.app_version ? ` v${app.caps.app_version}` : ""}` : "未连接"}
        </button>
        <button type="button" className="win-btn" title="帮助与快捷键（F1）" onClick={() => toggleHelp(true)}>
          <Icon name="keyboard" size={13} />
        </button>
        <span className="tb-sep tall" />
        <div className="win-controls">
          <button type="button" className="win-btn" title="最小化" aria-label="最小化" onClick={() => void windowControl("minimize")}>
            <Icon name="minimize" size={12} />
          </button>
          <button
            type="button"
            className="win-btn"
            title={app.window.maximized ? "向下还原" : "最大化"}
            aria-label={app.window.maximized ? "向下还原" : "最大化"}
            onClick={() => {
              void windowControl(app.window.maximized ? "restore" : "maximize").then(() => refreshWindowState());
            }}
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

function RenameInput({ name, onDone }: { name: string; onDone: () => void }) {
  const [text, setText] = useState(name);
  return (
    <input
      className="tb-input"
      value={text}
      autoFocus
      aria-label="工程名称"
      onChange={(event) => setText(event.target.value)}
      onBlur={() => {
        const trimmed = text.trim();
        if (trimmed && trimmed !== name) void updateProjectMeta({ name: trimmed });
        onDone();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") (event.target as HTMLInputElement).blur();
        if (event.key === "Escape") onDone();
      }}
    />
  );
}

export function tokenHint() {
  return appInfo.token() ? "密钥已就绪" : "未配置密钥";
}
