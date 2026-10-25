
import { BrandMark, Icon } from "../ui";
import {
  openEditorPanel,
  openSettings,
  openTemplates,
  setAssetFilter,
  setCaptionsOpen,
  setRailFocus,
  setView,
  toggleHelp,
  useApp,
} from "../store";
import { prettyBytes } from "../time";

/**
 * 左侧导航栏：一颗导航项就是一个真实去处（视图、素材筛选或面板），
 * 不放没接线的按钮。主题切换放在用户卡片上方，偏好只进 localStorage。
 */
export function LeftRail() {
  const app = useApp();

  const project = app.project;
  const inEditor = app.view === "editor" && Boolean(project);
  const usage = app.cacheUsage.limit_bytes > 0
    ? Math.min(1, app.cacheUsage.used_bytes / app.cacheUsage.limit_bytes)
    : 0;

  const go = (fn: () => void) => () => fn();
  const openAssets = (filter: "all" | "audio") => {
    setAssetFilter(filter);
    setRailFocus(filter === "audio" ? "voice" : "assets");
    if (project) setView("editor");
    requestAnimationFrame(() => document.querySelector<HTMLInputElement>(".asset-search")?.focus());
  };

  const items = [
    { key: "home", label: "项目", icon: "folder", active: app.view === "home", view: true, onClick: go(() => setView("home")) },
    { key: "assets", label: "素材", icon: "image", active: inEditor && app.railFocus === "assets", onClick: () => openAssets("all") },
    { key: "edit", label: "剪辑", icon: "film", active: inEditor && app.railFocus === "edit", view: true, onClick: go(() => { if (project) { setRailFocus("edit"); setView("editor"); } }) },
    { key: "voice", label: "配音", icon: "music", active: inEditor && app.railFocus === "voice", onClick: () => openAssets("audio") },
    {
      key: "captions",
      label: "字幕",
      icon: "captions",
      active: false,
      onClick: () => {
        if (!project) return;
        setView("editor");
        setCaptionsOpen(true);
      },
    },
    {
      key: "export",
      label: "导出",
      icon: "export",
      active: inEditor && app.railFocus === "export",
      onClick: () => {
        if (!project) return;
        setRailFocus("export");
        openEditorPanel("export");
      },
    },
    { key: "history", label: "历史", icon: "history", active: app.view === "history", view: true, onClick: go(() => setView("history")) },
    { key: "agent", label: "Agent", icon: "robot", active: app.view === "agent", view: true, onClick: go(() => setView("agent")) },
  ];

  return (
    <aside className="rail" aria-label="主导航">
      <div className="rail-brand">
        <BrandMark size={30} />
        <div className="rail-brand-text">
          <b>AgentCut</b>
          <span>AI Video Editor</span>
        </div>
      </div>

      <nav className="rail-nav" role="tablist" aria-label="主视图">
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`rail-item${item.active ? " active" : ""}`}
            role={(item as { view?: boolean }).view ? "tab" : undefined}
            aria-selected={(item as { view?: boolean }).view ? item.active : undefined}
            aria-current={item.active ? "page" : undefined}
            onClick={item.onClick}
            title={project || item.key === "home" || item.key === "history" || item.key === "agent" ? item.label : "先打开一个工程"}
          >
            <span className="rail-icon"><Icon name={item.icon} size={16} /></span>
            <span className="rail-label">{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="rail-tools">
        <button type="button" className="rail-item" onClick={() => openTemplates()} title="模板：剪辑风格、字幕样式、入场 / 出场动画">
          <span className="rail-icon"><Icon name="grid" size={16} /></span>
          <span className="rail-label">模板</span>
        </button>
        <button type="button" className="rail-item" onClick={() => toggleHelp(true)} title="区域说明、快捷键与功能百科（F1）">
          <span className="rail-icon"><Icon name="keyboard" size={16} /></span>
          <span className="rail-label">工具</span>
        </button>
        <button type="button" className="rail-item" onClick={() => openSettings()} title="外观、剪辑习惯、预览与存储、引擎信息">
          <span className="rail-icon"><Icon name="gear" size={16} /></span>
          <span className="rail-label">设置</span>
        </button>
      </div>

      <div className="spacer" />

      <div className="rail-storage" title={`派生缓存（缩略图 + 波形 + 代理）：${prettyBytes(app.cacheUsage.used_bytes)} / ${prettyBytes(app.cacheUsage.limit_bytes)}\n${app.cacheUsage.count} 个缓存项`}>
        <div className="storage-ring" style={{ ["--fill" as string]: `${Math.round(usage * 100)}%` }} aria-hidden="true">
          <span />
        </div>
        <div className="storage-text">
          <b>存储空间</b>
          <span>{prettyBytes(app.cacheUsage.used_bytes)} / {prettyBytes(app.cacheUsage.limit_bytes || 200 * 1024 * 1024 * 1024)}</span>
        </div>
      </div>
    </aside>
  );
}
