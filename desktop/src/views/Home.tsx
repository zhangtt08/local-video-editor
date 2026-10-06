import { useEffect, useRef, useState } from "react";

import { bridge } from "../bridge";
import { PROJECT_PRESETS } from "../presets";
import { BrandMark, Icon, Tag } from "../ui";
import { appInfo, boot, copy, createProject, exportBundle, importBundle, retryBundle, importFiles, loadLibrary, openProject, refreshProjects, setView, toggleHelp, useApp } from "../store";

/** 主页只做一件事：让你选一个工程继续，或者一眼看到引擎是否可用。 */
export function Home() {
  const app = useApp();
  const [creating, setCreating] = useState(false);
  const bundleInput = useRef<HTMLInputElement | null>(null);
  const features = app.caps?.features ?? {};
  const ffmpeg = Boolean(app.info?.ffmpeg);

  useEffect(() => {
    if (!app.library.length) void loadLibrary();
  }, [app.library.length]);

  return (
    <div className="start">
      <div className="start-head">
        <h1 className="start-title">工程</h1>
        <span className="tag mono">{app.projects.length}</span>
        <span className="spacer" />
        <button className="btn primary" onClick={() => setCreating(true)}>
          <Icon name="plus" />
          新建工程
        </button>
        <button className="btn" onClick={() => void importFiles()} disabled={!features.media_probe} title={features.media_probe ? "选择视频 / 音频 / 图片，复制进本地素材库并探测" : "未找到 FFmpeg，暂时不能导入"}>
          <Icon name="folder" />
          导入素材
        </button>
        <button className="btn" onClick={() => bundleInput.current?.click()} disabled={!features.media_probe} title="把工程连同全部素材打成 .agentcut.zip，交给同事或备份">
          <Icon name="export" />
          导入工程包
        </button>
        <input
          ref={bundleInput}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void importBundle(file);
          }}
        />
        {app.bundleRetry ? <button className="btn" disabled={Boolean(app.busy)} onClick={() => void retryBundle()} title={`使用同一请求重试 ${app.bundleRetry}，避免重复创建工程`}>重试工程导入</button> : null}
        <button className="btn subtle" onClick={() => setView("agent")} title="把同一个引擎接给你的 AI Agent">
          <Icon name="robot" />
          Agent 接入
        </button>
      </div>

      <div className="start-body">
        <section className="proj-table" aria-label="工程列表">
          {!app.projects.length ? (
            <div className="start-empty">
              <BrandMark size={44} />
              <div className="se-line">还没有工程。一个工程就是一条时间线。</div>
              <button className="btn primary" onClick={() => setCreating(true)}>
                <Icon name="plus" />
                新建第一个工程
              </button>
              <div className="se-hint">默认 1080p 30fps，会自动备好一条画面轨和一条声音轨。</div>
              <div className="se-alt">
                或者先
                <button className="linklike" onClick={() => void importFiles()} disabled={!features.media_probe}>导入素材</button>
                ，
                <button className="linklike" onClick={() => setView("agent")}>看看怎么让 Agent 来剪</button>
              </div>
            </div>
          ) : (
            <>
              <div className="pt-row pt-head">
                <span>名称</span>
                <span className="num">时长</span>
                <span className="num">片段</span>
                <span className="num">素材</span>
                <span className="num">版本</span>
                <span />
              </div>
              {app.projects.map((item) => (
                <div
                  key={item.id}
                  className="pt-row pt-item"
                  role="button"
                  tabIndex={0}
                  onClick={() => void openProject(item.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      void openProject(item.id);
                    }
                  }}
                  title={`打开 ${item.name}\n${item.id}`}
                >
                  <span className="pt-name">
                    <Icon name="film" size={13} />
                    <b>{item.name}</b>
                  </span>
                  <span className="num mono">{item.durationTicks ? (item.durationTicks / 70560000).toFixed(1) + "s" : "—"}</span>
                  <span className="num mono">{item.clips}</span>
                  <span className="num mono">{item.assets}</span>
                  <span className="num mono accent">r{item.revision}</span>
                  <span className="num go">
                    <button
                      type="button"
                      className="row-export"
                      title="导出工程包（含全部素材）"
                      aria-label={`导出《${item.name}》工程包`}
                      onClick={(event) => {
                        event.stopPropagation();
                        void exportBundle(item.id, item.name);
                      }}
                    >
                      <Icon name="export" size={12} />
                    </button>
                    <Icon name="chevron" size={12} />
                  </span>
                </div>
              ))}
            </>
          )}
        </section>

        <aside className="start-side">
          <div className="status-card">
            <div className={`sc-head ${app.phase === "ready" ? "on" : "off"}`}>
              <span className="dot" />
              本地引擎{app.phase === "ready" ? "在线" : "未连接"}
              <span className="spacer" />
              <span className="mono dim">{app.info ? `:${app.info.port}` : ""}</span>
            </div>
            <div className="sc-rows">
              <Row label="FFmpeg" ok={ffmpeg} text={ffmpeg ? "已就绪，可预览与导出" : "未找到，仅能剪辑"} />
              <Row label="素材库" ok={Boolean(app.library.length)} text={app.library.length ? `${app.library.length} 个已探测文件` : "还没有导入文件"} />
              <Row label="输出" ok text={app.info?.output_dir ? shortPath(app.info.output_dir) : "引擎默认目录"} />
            </div>
            <details className="sc-more">
              <summary>连接与存储详情</summary>
              <KV label="接口" value={app.info?.base_url ?? ""} onCopy={() => void copy(app.info?.base_url ?? "", "接口地址")} />
              <KV label="密钥" value={appInfo.token()} secret onCopy={() => void copy(appInfo.token(), "密钥")} />
              <KV label="素材目录" value={(app.info?.media_roots ?? []).join("、")} />
              <KV label="数据库" value={app.info?.data_dir ?? ""} />
              <div className="sc-caps">
                未实现：
                {Object.entries(features)
                  .filter(([, on]) => !on)
                  .map(([key]) => CAP_LABEL[key] ?? key)
                  .join(" · ") || "无"}
              </div>
              <div className="sc-btns">
                <button className="btn subtle" onClick={() => void bridge.pickMediaRoot().then(() => loadLibrary())}>
                  <Icon name="plus" size={12} /> 素材文件夹
                </button>
                <button className="btn subtle" onClick={() => void bridge.restartEngine().then(() => boot())}>
                  <Icon name="refresh" size={12} /> 重启引擎
                </button>
                <button className="btn subtle" onClick={() => void refreshProjects()}>
                  <Icon name="history" size={12} /> 刷新列表
                </button>
              </div>
            </details>
          </div>

          <div className="howto">
            <div className="panel-label">怎么用</div>
            <ol>
              <li>建工程：选画幅与帧率，轨道自动备好</li>
              <li>拖素材上时间线，蓝色画面、绿色声音</li>
              <li>空格预览，剪刀分割，拖边缘改长短</li>
              <li>右侧「导出」出 MP4；「Agent」页让 AI 来剪</li>
            </ol>
            <button className="btn subtle full" onClick={() => toggleHelp(true)}>
              <Icon name="keyboard" size={12} /> 区域说明与快捷键（F1）
            </button>
          </div>
        </aside>
      </div>

      {creating ? <NewProjectDialog onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

const CAP_LABEL: Record<string, string> = {
  keyframes: "关键帧",
  transitions: "转场",
  speed_change: "变速",
  media_probe: "素材探测",
  thumbnails: "缩略图",
  waveform: "波形",
  preview_stream: "预览",
  render: "导出",
  render_jobs: "任务队列",
};

function shortPath(value: string) {
  const parts = value.split(/[\\/]/);
  return parts.length > 3 ? `…\\${parts.slice(-2).join("\\")}` : value;
}

function Row({ label, text, ok }: { label: string; text: string; ok: boolean }) {
  return (
    <div className="sc-row">
      <span className={`sc-dot ${ok ? "ok" : "no"}`} />
      <span className="sc-label">{label}</span>
      <span className="sc-value ellipsis" title={text}>
        {text}
      </span>
    </div>
  );
}

function KV({ label, value, mono, secret, onCopy }: { label: string; value: string; mono?: boolean; secret?: boolean; onCopy?: () => void }) {
  const [reveal, setReveal] = useState(!secret);
  return (
    <div className="kv">
      <span className="kv-label">{label}</span>
      <span className={`kv-value ${mono ? "mono" : ""}`} title={value}>
        {value ? (reveal ? value : `${value.slice(0, 6)}${"•".repeat(10)}`) : "—"}
      </span>
      {secret ? (
        <button type="button" className="icon-btn tiny" title={reveal ? "隐藏" : "显示"} onClick={() => setReveal(!reveal)}>
          <Icon name={reveal ? "eyeOff" : "eye"} size={12} />
        </button>
      ) : null}
      {onCopy ? (
        <button type="button" className="icon-btn tiny" title={`复制${label}`} onClick={onCopy}>
          <Icon name="copy" size={12} />
        </button>
      ) : null}
    </div>
  );
}

function NewProjectDialog({ onClose }: { onClose: () => void }) {
  const app = useApp();
  const [name, setName] = useState("");
  const [preset, setPreset] = useState(PROJECT_PRESETS[0].id);
  const chosen = PROJECT_PRESETS.find((item) => item.id === preset) ?? PROJECT_PRESETS[0];
  return (
    <div className="dialog-backdrop open" onClick={onClose} role="presentation">
      <div className="dialog" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <div className="dialog-head">新建工程</div>
        <div className="dialog-body">
          <div className="form-row">
            <label htmlFor="np-name">工程名称</label>
            <input
              id="np-name"
              className="input"
              autoFocus
              placeholder="例如：城市印象 · 短片"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void submit();
              }}
            />
          </div>
          <div className="form-row">
            <label>画幅与帧率</label>
            <div className="preset-grid">
              {PROJECT_PRESETS.map((item) => (
                <button key={item.id} type="button" className={`preset ${item.id === preset ? "active" : ""}`} onClick={() => setPreset(item.id)}>
                  <b>{item.label}</b>
                  <span className="mono">
                    {item.width}×{item.height} · {item.fps[0] / item.fps[1]} fps
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="dialog-foot">
          <Tag mono>{`1 帧 = ${Math.round((70560000 * chosen.fps[1]) / chosen.fps[0]).toLocaleString("en-US")} tick`}</Tag>
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button className="btn primary" disabled={Boolean(app.busy)} onClick={() => void submit()}>
            创建并进入
          </button>
        </div>
      </div>
    </div>
  );

  async function submit() {
    const project = await createProject(name.trim() || "未命名工程", {
      width: chosen.width,
      height: chosen.height,
      frame_rate: { numerator: chosen.fps[0], denominator: chosen.fps[1] },
      sample_rate: chosen.sample,
    });
    if (project) onClose();
  }
}
