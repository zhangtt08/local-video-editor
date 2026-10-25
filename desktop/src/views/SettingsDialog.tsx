import { useState } from "react";

import { Modal } from "../ui";
import { applyTheme, theme, type Theme } from "../theme";
import {
  PROXY_WIDTHS,
  clearDerivedCache,
  closeSettings,
  cycleSafeArea,
  editPrefs,
  prefs,
  setProxyWidth,
  setView,
  toggleHelp,
  useApp,
} from "../store";
import { prettyBytes } from "../time";

/** 设置：外观、剪辑习惯、预览与缓存、引擎信息。每一项都落到已有的偏好或工程状态上。 */
export function SettingsDialog() {
  const app = useApp();
  const [look, setLook] = useState<Theme>(theme());
  const [snap, setSnap] = useState(editPrefs().snap);
  const [linked, setLinked] = useState(editPrefs().linkedSelection);
  const project = app.project;
  const safe = project?.settings.safe_area ?? "off";
  const SAFE_LABELS: Record<string, string> = { off: "关", action: "动作安全", title: "字幕安全" };

  return (
    <Modal
      title="设置"
      sub="这些偏好只影响这台机器；工程里的设置（基色、安全框、交付方案）跟着工程走。"
      width={620}
      onClose={closeSettings}
      footer={<button type="button" className="btn primary" onClick={closeSettings}>完成</button>}
    >
      <div className="set-block">
        <div className="set-head"><b>外观</b><span>只进本机偏好，不进工程状态</span></div>
        <div className="set-row">
          <label>主题</label>
          <div className="seg mini" role="group" aria-label="主题">
            <button type="button" className={look === "dark" ? "active" : ""} aria-pressed={look === "dark"} onClick={() => { applyTheme("dark"); setLook("dark"); }}>深色</button>
            <button type="button" className={look === "light" ? "active" : ""} aria-pressed={look === "light"} onClick={() => { applyTheme("light"); setLook("light"); }}>浅色</button>
          </div>
        </div>
      </div>

      <div className="set-block">
        <div className="set-head"><b>剪辑习惯</b><span>时间线与动画曲线共用同一份磁吸偏好</span></div>
        <div className="set-row">
          <label htmlFor="set-snap">时间吸附</label>
          <input id="set-snap" type="checkbox" checked={snap} onChange={(event) => { setSnap(event.target.checked); prefs.setSnap(event.target.checked); }} />
        </div>
        <div className="set-row">
          <label htmlFor="set-linked">联动选择</label>
          <input id="set-linked" type="checkbox" checked={linked} onChange={(event) => { setLinked(event.target.checked); prefs.toggleLinkedSelection(); }} />
        </div>
      </div>

      <div className="set-block">
        <div className="set-head"><b>预览与存储</b><span>只影响预览与磁盘，导出永远用原片</span></div>
        <div className="set-row">
          <label htmlFor="set-proxy">代理分辨率</label>
          <select id="set-proxy" className="input" value={app.proxyWidth} onChange={(event) => void setProxyWidth(Number(event.target.value))}>
            <option value={0}>关闭</option>
            {PROXY_WIDTHS.map((width) => <option key={width} value={width}>{width}p</option>)}
          </select>
        </div>
        <div className="set-row">
          <label>派生缓存</label>
          <span className="set-value mono">{prettyBytes(app.cacheUsage.used_bytes)} / {prettyBytes(app.cacheUsage.limit_bytes || 0)} · {app.cacheUsage.count} 项</span>
          <button type="button" className="btn tiny" disabled={!app.cacheUsage.count} onClick={() => void clearDerivedCache()}>清理</button>
        </div>
        <div className="set-row">
          <label>安全框</label>
          <button type="button" className="btn tiny" disabled={!project} onClick={() => cycleSafeArea()}>{SAFE_LABELS[safe] ?? safe}（点一下换一档）</button>
        </div>
      </div>

      <div className="set-block">
        <div className="set-head"><b>引擎</b><span>同一个本地引擎，人、Agent 与 MCP 共用</span></div>
        <div className="set-row"><label>版本</label><span className="set-value mono">v{app.caps?.app_version ?? "?"} · schema {app.caps?.project_schema_version ?? "?"}</span></div>
        <div className="set-row"><label>接口</label><span className="set-value mono">{app.info?.base_url ?? "未连接"}</span></div>
        <div className="set-row"><label>FFmpeg</label><span className="set-value mono ellipsis" title={app.info?.ffmpeg ?? ""}>{app.info?.ffmpeg || "未找到"}</span></div>
        <div className="set-row">
          <label>下一步</label>
          <span className="set-actions">
            <button type="button" className="btn tiny" onClick={() => { closeSettings(); setView("agent"); }}>Agent 接入</button>
            <button type="button" className="btn tiny subtle" onClick={() => { closeSettings(); toggleHelp(true); }}>区域说明</button>
          </span>
        </div>
      </div>
    </Modal>
  );
}
