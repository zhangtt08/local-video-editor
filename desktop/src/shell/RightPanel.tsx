import { useEffect, useRef, useState } from "react";

import { Icon } from "../ui";
import { setEditorPanel, useApp } from "../store";
import { AIPanel } from "./AIPanel";
import { ExportPanel } from "../views/ExportPanel";
import { Inspector, type InspGroup } from "../views/Inspector";
import { ScopePanel } from "../views/ScopePanel";

type Tab = "ai" | "inspect" | "export" | "scope";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "ai", label: "AI 剪辑", icon: "spark" },
  { id: "inspect", label: "属性", icon: "info" },
  { id: "export", label: "导出", icon: "export" },
  { id: "scope", label: "示波器", icon: "image" },
];

const PROPERTY_TABS: { id: InspGroup; label: string }[] = [
  { id: "basic", label: "基础" },
  { id: "color", label: "调色" },
  { id: "motion", label: "动画" },
  { id: "fx", label: "特效" },
];

/** 右侧工作区：AI 动作、片段属性、交付与示波器共用一列，顶部页签是同一件事的四个入口。 */
export function RightPanel() {
  const app = useApp();
  const [tab, setTab] = useState<Tab>(() => {
    // 深链点名了哪一页就落在哪一页（`?panel=inspect` 也算），否则默认落在 AI 剪辑。
    const asked = new URLSearchParams(location.search).get("panel");
    if (asked === "inspect" || asked === "export" || asked === "scope" || asked === "ai") return asked;
    // 默认落在 AI 剪辑（参考图那一列）；属性页一键就到，量具打开工程后会自己切过去。
    return "ai";
  });
  const [propTab, setPropTab] = useState<InspGroup>("basic");

  const seenPanel = useRef(app.editorPanel);
  useEffect(() => {
    // 挂载那一次不抢：默认落在 AI 剪辑，链接里真点名过（export/scope/inspect）才跟着走。
    if (seenPanel.current === app.editorPanel) return;
    seenPanel.current = app.editorPanel;
    setTab(app.editorPanel === "inspect" ? "inspect" : app.editorPanel === "export" ? "export" : "scope");
  }, [app.editorPanel]);

  const choose = (next: Tab) => {
    setTab(next);
    if (next !== "ai") setEditorPanel(next);
  };

  return (
    <aside className="right-panel">
      <div className="rp-tabs" role="tablist" aria-label="右侧工作区">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => choose(item.id)}
            title={item.id === "ai" ? "把重复劳动交给引擎：粗剪、字幕、调色、对齐" : item.label}
          >
            {item.id === "ai" ? <span className="rp-spark"><Icon name="spark" size={12} /></span> : null}
            {item.label}
          </button>
        ))}
      </div>

      {tab === "inspect" ? (
        <div className="prop-tabs" role="group" aria-label="片段属性分区">
          <b>片段属性</b>
          <div className="prop-tab-row">
            {PROPERTY_TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={propTab === item.id}
                className={propTab === item.id ? "active" : ""}
                onClick={() => setPropTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rp-body">
        {tab === "ai" ? (
          <AIPanel />
        ) : tab === "export" ? (
          <ExportPanel />
        ) : tab === "scope" ? (
          <ScopePanel />
        ) : (
          <Inspector group={propTab} />
        )}
      </div>
    </aside>
  );
}
