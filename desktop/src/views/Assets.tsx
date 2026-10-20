import { useEffect, useRef, useState } from "react";

import { Empty, Icon, IconBtn, Modal } from "../ui";
import { humanDuration, prettyBytes, rateLabel, seconds } from "../time";
import {
  addLibraryItemToTimeline,
  appendAsset,
  importFiles,
  loadLibrary,
  removeAsset,
  selectAsset,
  useApp,
  addTextClip,
  importCaptions,
  openSequence,
} from "../store";

const FILTERS = [
  { value: "all", label: "全部" },
  { value: "video", label: "视频" },
  { value: "image", label: "图片" },
  { value: "audio", label: "音频" },
] as const;

/** 素材库：左边是「本机已经探测过的文件」，右边 tab 是「这个工程引用过的素材」。 */
export function Assets() {
  const app = useApp();
  const [tab, setTab] = useState<"library" | "project">("library");
  const [filter, setFilter] = useState<"all" | "video" | "image" | "audio">("all");
  const [query, setQuery] = useState("");
  const [subtitle, setSubtitle] = useState<string | null>(null);
  // 选文件那一颗走应用自己的按钮：整个界面只有这里原来是浏览器默认的「选择文件 / 未选择文件」，
  // 一个没被刻度管过的原生控件夹在弹层里（另外两处 import 都是 hidden input + 样式按钮）。
  const captionFile = useRef<HTMLInputElement | null>(null);
  const project = app.project;
  const mediaReady = Boolean(app.caps?.features.media_probe);

  useEffect(() => {
    if (mediaReady && !app.library.length) void loadLibrary();
  }, [mediaReady, app.library.length]);

  const library = app.library.filter(
    (item) =>
      (filter === "all" || item.probe.verified.kind === filter) &&
      (!query ||
        `${item.probe.verified.label} ${item.probe.verified.path}`.toLowerCase().includes(query.toLowerCase()))
  );
  const assets = project
    ? Object.values(project.assets).filter(
        (item) =>
          (filter === "all" || item.kind === filter) &&
          (!query || `${item.label} ${item.id}`.toLowerCase().includes(query.toLowerCase()))
      )
    : [];

  return (
    <aside className="panel">
      {subtitle !== null ? <Modal title="导入 SRT 字幕" sub="时间从工程起点计算；每条字幕进入独立文字片段，支持修改和动画。" onClose={() => setSubtitle(null)} footer={<><button className="btn" onClick={() => setSubtitle(null)}>取消</button><button className="btn primary" disabled={!subtitle.trim()} onClick={() => { importCaptions(subtitle); setSubtitle(null); }}>导入字幕</button></>}>
        <input ref={captionFile} type="file" accept=".srt" aria-label="选择 SRT 文件" hidden onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then(setSubtitle); }} />
        <button className="btn" onClick={() => captionFile.current?.click()}>选择字幕文件</button>
        <textarea autoFocus className="input caption-editor" aria-label="SRT 字幕内容" rows={10} maxLength={500000} placeholder="粘贴 SRT 内容，或选择字幕文件" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} />
      </Modal> : null}
      <div className="panel-head">
        <div className="seg mini" role="tablist" aria-label="素材来源">
          <button type="button" className={tab === "library" ? "active" : ""} onClick={() => setTab("library")} title="本机已探测的文件，可直接拖上时间线">
            素材库
          </button>
          <button type="button" className={tab === "project" ? "active" : ""} onClick={() => setTab("project")} title="当前工程已登记的素材：它们决定了片段能取用的范围">
            工程素材
            <span className="tag mono">{project ? Object.keys(project.assets).length : 0}</span>
          </button>
        </div>
        <span className="spacer" />
        <IconBtn icon="refresh" label="重新读取素材库" onClick={() => void loadLibrary()} />
        <IconBtn icon="plus" label="导入素材文件（复制到本地素材库并逐块探测）" onClick={() => void importFiles()} />
      </div>

      <div className="asset-filters" role="tablist" aria-label="按类型筛选">
        <button className="btn" onClick={addTextClip} disabled={!project}>＋ 文字</button>
        <button className="btn" onClick={() => setSubtitle("")} disabled={!project}>字幕</button>
        {FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            className={`btn ${filter === item.value ? "active" : ""}`}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </button>
        ))}
        <input
          className="input asset-search"
          placeholder="搜索素材"
          aria-label="搜索素材"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {query && !library.length && !assets.length ? (
        <div className="asset-noresult">
          没有匹配「{query}」的{tab === "library" ? "素材" : "工程素材"}
          <button className="linklike" onClick={() => setQuery("")}>
            清除搜索
          </button>
        </div>
      ) : null}

      <div className="panel-body">
        {tab === "library" ? (
          !mediaReady ? (
            <Empty
              icon="warning"
              lines={
                <>
                  媒体引擎未就绪，素材库暂不可用
                  <div className="mono dim">media_probe = false · 检查 FFmpeg 与素材目录</div>
                </>
              }
            />
          ) : !library.length ? (
            <Empty
              icon="folder"
              lines={
                <>
                  素材库还是空的
                  <div className="dim" title="文件会被复制进本地素材库，原文件不动。">点右上角 ＋ 加入视频 / 音频 / 图片</div>
                </>
              }
            />
          ) : (
            <div className="asset-grid">
              {library.map((item) => (
                <LibraryCard key={item.probe.id} item={item} />
              ))}
            </div>
          )
        ) : !project ? (
          <Empty icon="film" lines={<>还没有打开工程</>} />
        ) : !assets.length ? (
          <Empty icon="film" lines={<>这个工程还没有素材<div className="dim">从「素材库」把文件拖到时间线，素材会自动登记到这里。</div></>} />
        ) : (
          <div className="asset-list">
            {assets.map((asset) => (
              <div key={asset.id} className={`asset-row${app.selectedAsset === asset.id ? " selected" : ""}`} onClick={() => selectAsset(asset.id)}>
                <span className={`asset-kind ${asset.kind}`}>
                  <Icon name={asset.kind === "video" || asset.kind === "sequence" ? "film" : asset.kind === "audio" ? "music" : "image"} size={13} />
                </span>
                <span className="asset-meta">
                  <span className="asset-name">{asset.label}</span>
                  <span className="asset-sub mono">
                    {asset.id} · {asset.kind === "image" ? "静态图" : asset.duration_ticks ? humanDuration(asset.duration_ticks) : "时长未知"}
                    {asset.kind === "sequence" ? " · 合成" : !asset.verified && asset.kind !== "text" ? " · 未导入" : ""}
                  </span>
                </span>
                <span className="asset-actions" onClick={(e) => e.stopPropagation()}>
                  {asset.sequence_id ? <IconBtn icon="info" label={`进入合成 ${asset.label}`} onClick={() => openSequence(asset.sequence_id!)} /> : null}
                  <IconBtn icon="plus" label="放到时间线末尾" onClick={() => appendAsset(asset.id)} />
                  <IconBtn icon="trash" label="从工程移除这个素材（片段还在用时会被拒绝）" danger onClick={() => removeAsset(asset.id)} />
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="asset-foot">
        {tab === "library" ? (
          <div className="mono dim" title="拖到时间线即可上轨；探测只读元数据与缩略图，不修改原文件。">
            共 {app.library.length} 个素材 · 悬停看不改原文件
          </div>
        ) : (
          <div className="mono dim" title="工程素材记录的是「服务端验证过的文件」，Agent 无法伪造它；verified 记录由 /v1/media/import 产生。">
            verified 记录由 /v1/media/import 产生
          </div>
        )}
      </div>
    </aside>
  );
}

function LibraryCard({ item }: { item: import("../store").LibraryItem }) {
  const app = useApp();
  const info = item.probe.verified;
  const already = Object.values(app.project?.assets ?? {}).some((asset) => asset.verified?.path === info.path);
  const [hover, setHover] = useState(false);
  return (
    <div
      className={`lib-card${already ? " registered" : ""}${app.selectedAsset === item.probe.id ? " selected" : ""}`}
      tabIndex={0}
      role="button"
      aria-label={`预览素材 ${info.label}`}
      onClick={() => selectAsset(item.probe.id)}
      onKeyDown={(event) => { if (event.key === "Enter") selectAsset(item.probe.id); }}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData("application/x-agentcut-asset", info.path);
        event.dataTransfer.effectAllowed = "copy";
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onDoubleClick={() => void addLibraryItemToTimeline(item)}
      title={`${info.path}\n${prettyBytes(info.size_bytes)} · ${info.video_codec ?? info.audio_codec ?? ""}\n拖到时间线上轨，或双击直接放到末尾`}
    >
      <div className="lib-thumb">
        {info.kind === "audio" ? (
          <WaveMini values={item.probe.waveform} />
        ) : item.probe.urls?.thumbnails?.[0] ? (
          <img src={item.probe.urls.thumbnails[hover ? Math.min(1, item.probe.urls.thumbnails.length - 1) : 0]} alt="" loading="lazy" />
        ) : (
          <span className={`asset-kind ${info.kind}`}>
            <Icon name={info.kind === "video" ? "film" : "music"} size={16} />
          </span>
        )}
        <span className="lib-kind mono">
          {info.kind === "video" ? "视频" : info.kind === "audio" ? "音频" : "图片"}
        </span>
        {already ? <span className="lib-flag" title="已登记进当前工程">已入工程</span> : null}
      </div>
      <div className="lib-meta">
        <div className="lib-name">{info.label}</div>
        <div className="lib-sub mono">
          {info.kind === "image" ? `${info.width}×${info.height}` : humanDuration(info.duration_ticks)}
          {info.frame_rate ? ` · ${rateLabel(info.frame_rate)}` : ""}
          {info.has_audio ? " · 有声" : ""}
        </div>
      </div>
      <button
        type="button"
        className="btn tiny lib-add"
        onClick={(event) => { event.stopPropagation(); void addLibraryItemToTimeline(item); }}
        title="把这段素材放到对应轨道的末尾（也可以直接拖到想要的位置）"
      >
        <Icon name="plus" size={11} /> 上轨
      </button>
    </div>
  );
}

function WaveMini({ values }: { values: number[] }) {
  const peak = Math.max(0.0001, ...values);
  const bars: JSX.Element[] = [];
  const count = 34;
  const step = Math.max(1, Math.floor(values.length / count));
  for (let i = 0; i < count; i += 1) {
    const index = Math.min(values.length - 1, i * step);
    const h = 8 + (values[index] / peak) * 84;
    bars.push(<rect key={i} x={i * 3} y={50 - h / 2} width={1.8} height={h} rx={0.9} />);
  }
  return (
    <svg className="wave-mini" viewBox={`0 0 ${count * 3} 100`} preserveAspectRatio="none" aria-hidden="true">
      <g fill="rgba(67,162,115,.6)">{bars}</g>
    </svg>
  );
}

export function durationLabel(ticksValue: number): string {
  return `${seconds(ticksValue).toFixed(3)}s`;
}
