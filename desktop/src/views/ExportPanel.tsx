import { useEffect, useState } from "react";

import { bridge } from "../bridge";
import { Btn, Empty, Field, Icon, Tag } from "../ui";
import { humanDuration, prettyBytes, rateLabel, TIMEBASE, timecode } from "../time";
import type { RenderBatchItem, RenderJob } from "../engine";
import {
  cancelJob,
  exportRecipe,
  loadJobs,
  removeRecipe,
  renderPlanPreview,
  saveRecipe,
  startRender,
  startRenderBatch,
  timelineEnd,
  useApp,
} from "../store";
import { codecText, presetIsAudio, FIT_MODES, type RenderFit, type RenderRange } from "../engine";

const POLL_MS = 1500;

/** 勾选「附带竖屏」时那一条用的预设 id：由引擎的预设表定义，这里只引用。 */
const VERTICAL_PRESET = "h264-1080x1920-vertical";

const STATUS: Record<RenderJob["status"], { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "" },
  running: { label: "渲染中", tone: "accent" },
  succeeded: { label: "已完成", tone: "ok" },
  failed: { label: "失败", tone: "warn" },
  cancelled: { label: "已取消", tone: "off" },
};

/** 文件名只留可读字符；引擎会自己补容器后缀，这里不写扩展名。 */
function sanitizeName(name: string): string {
  const cleaned = name
    .replace(/[\\/:*?"<>|.]+/g, " ")
    .trim()
    .replace(/\s+/g, "-");
  return cleaned || "agentcut-export";
}

function progressOf(job: RenderJob): number {
  const raw = job.progress ?? (job.total_ticks > 0 ? job.rendered_ticks / job.total_ticks : 0);
  return Math.max(0, Math.min(1, raw));
}

export function ExportPanel(): JSX.Element {
  const app = useApp();
  const [presetId, setPresetId] = useState("");
  const [fit, setFit] = useState<RenderFit>("contain");
  const [range, setRange] = useState<RenderRange>("full");
  const [alsoVertical, setAlsoVertical] = useState(false);
  const [filename, setFilename] = useState("");
  const [folder, setFolder] = useState("");
  const [recipeName, setRecipeName] = useState("");

  useEffect(() => {
    void loadJobs();
    void bridge.readSettings().then((settings) => {
      if (settings.outputFolder) setFolder(settings.outputFolder);
    });
  }, []);

  useEffect(() => {
    const active = app.jobs.some((job) => job.status === "queued" || job.status === "running");
    if (!active) return;
    const timer = window.setInterval(() => void loadJobs(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [app.jobs]);

  const project = app.project;
  if (!project) {
    return (
      <div className="panel-scroll">
        <Empty
          icon="export"
          lines={
            <>
              <b>还没有打开工程</b>
              <span>导出会把时间线交给服务端 FFmpeg 渲染成一个真实视频文件；先打开一个工程。</span>
            </>
          }
        />
      </div>
    );
  }

  const presets = app.caps?.render_presets ?? [];
  const renderReady = Boolean(app.caps?.features.render);
  const preset = presets.find((item) => item.id === presetId) ?? presets[0] ?? null;
  const end = timelineEnd(project);
  const clips = Object.values(project.clips);
  const unverified = clips.filter((clip) => { const asset = project.assets[clip.asset_id]; return asset?.kind !== "text" && asset?.kind !== "sequence" && !asset?.verified; }).length;
  const blocked =
    !presets.length
      ? "引擎没有返回任何导出预设，无法排队渲染。"
      : !clips.length || end <= 0
        ? "时间线还是空的：先把素材拖到轨道上，才有内容可导出。"
        : unverified
          ? `${unverified} 段片段尚未关联真实素材，请先从素材库导入对应文件。`
          : "";
  const timelineName = app.sequenceId ? project.sequences?.[app.sequenceId]?.name ?? project.name : project.name;
  const outSize = preset?.scale ?? [project.settings.width, project.settings.height];
  // 音频交付没有画面：画幅适配与「附带竖屏」对它都不成立，面板不收起来就会让人以为它们参与了。
  const audioOnly = presetIsAudio(preset);
  const fitHint = audioOnly
    ? "这条交付只有声音，没有画面，也就没有画幅适配一说"
    : outSize[0] / outSize[1] === project.settings.width / project.settings.height
      ? "导出比例与时间线一致，三种适配的结果相同"
      : `时间线 ${project.settings.width}×${project.settings.height} 要放进 ${outSize[0]}×${outSize[1]}，这里决定多出来的部分怎么处理`;
  const vertical = presets.find((item) => item.id === VERTICAL_PRESET) ?? null;
  // 后缀跟着那条交付自己的容器，不再钉死 .mp4：竖屏那条换成 WebM 预设时，文件名也得是 .webm。
  const verticalName = `${(filename.trim() || sanitizeName(timelineName)).replace(/\.[A-Za-z0-9]+$/, "")}-9x16.${vertical?.container ?? "mp4"}`;
  const inTicks = project.settings.in_ticks ?? null;
  const outTicks = project.settings.out_ticks ?? null;
  const marked = inTicks != null && outTicks != null;
  const rangeSeconds = inTicks != null && outTicks != null ? ((outTicks - inTicks) / TIMEBASE).toFixed(2) : "0";
  const timelineSeconds = Math.max(0, ...clips.map((clip) => clip.position_ticks + clip.duration_ticks)) / TIMEBASE;
  const rangeHint = marked
    ? `整条 ${timelineSeconds.toFixed(2)} 秒，或只导出入出点之间的 ${rangeSeconds} 秒（当前：${range === "marks" ? "区间" : "整条"}）`
    : "整条时间线。想只导出一段：把播放头放到起点按 I、放到终点按 O。";
  const finalName = `${(filename.trim() || sanitizeName(timelineName)).replace(/\.[A-Za-z0-9]+$/, "")}.${preset?.container ?? "mp4"}`;
  // 方案存的就是「点开始导出会发出去的那组交付」，所以这里只算一次，界面和方案不会各说一套。
  const pendingItems: RenderBatchItem[] = [
    { preset_id: preset?.id ?? "", filename: finalName, fit, range },
    ...(alsoVertical && vertical && !audioOnly
      ? [{ preset_id: vertical.id, filename: verticalName, fit: "cover" as RenderFit, range }]
      : []),
  ];
  const recipeHint = (project.recipes ?? []).length
    ? "点方案名就按它出货（仍锁定当前 revision，整批先编译通过才入队）；「覆盖」把现在这组设置写回去。"
    : "还没有方案。把画幅、适配和范围选好，存成一个名字，之后就一键复用。";

  async function chooseFolder() {
    const picked = await bridge.pickOutputFolder();
    if (picked.cancelled || !picked.folder) return;
    setFolder(picked.folder);
    // 记住它：下次启动、下一条时间线都写到同一个地方。
    await bridge.setOutputFolder(picked.folder);
  }

  return (
    <div className="panel-scroll">
      <div className="section-head">
        <span className="panel-label">导出 · {app.sequenceId ? timelineName : "主时间线"}</span>
        <span className="spacer" />
        <Tag mono tone={renderReady ? "ok" : "off"}>
          {renderReady ? "渲染就绪" : "渲染不可用"}
        </Tag>
      </div>

      {!app.caps ? (
        <p className="hint">还在读取引擎能力（/capabilities），预设一会儿就出现在这里。</p>
      ) : !renderReady ? (
        <div className="export-unavailable">
          <Icon name="warning" size={16} />
          <div>
            <b>这台机器没有可用的 FFmpeg，导出功能当前不可用。</b>
            <p>
              引擎探测结果：<span className="mono">{app.info?.ffmpeg || "（未找到 ffmpeg）"}</span>
            </p>
            <p>
              剪辑、预览、历史恢复都不受影响。把 ffmpeg 放进 <span className="mono">resources/bin</span>{" "}
              或加入系统 PATH，再重启引擎，这里就会出现可选的预设。
            </p>
          </div>
        </div>
      ) : !preset ? (
        <p className="inline-error">
          <Icon name="warning" size={12} />
          {blocked}
        </p>
      ) : (
        <>
          <Field label="导出预设" hint="预设由服务端定义，界面只负责选择">
            <div className="preset-list" role="radiogroup" aria-label="导出预设">
              {presets.map((item) => {
                const on = item.id === preset.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    className={`preset-row${on ? " active" : ""}`}
                    onClick={() => setPresetId(item.id)}
                  >
                    <span className="pr-dot" aria-hidden="true" />
                    <span className="pr-main">
                      <b>{item.label}</b>
                      <span className="mono dim">
                        {item.container}
                        {item.scale
                          ? ` · ${item.scale[0]}×${item.scale[1]}`
                          : presetIsAudio(item)
                            ? " · 无画面"
                            : ` · 跟随工程 ${project.settings.width}×${project.settings.height}`}{" "}
                        · {codecText(item)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label="画幅适配" hint={fitHint}>
            <div className="fit-row" role="radiogroup" aria-label="画幅适配">
              {FIT_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  role="radio"
                  aria-checked={fit === mode.id}
                  className={`fit-chip${fit === mode.id ? " active" : ""}`}
                  title={audioOnly ? "音频交付没有画面，这一项不参与" : mode.hint}
                  disabled={audioOnly}
                  onClick={() => setFit(mode.id)}
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </Field>

          <Field label="导出范围" hint={rangeHint}>
            <div className="fit-row" role="radiogroup" aria-label="导出范围">
              <button
                type="button"
                role="radio"
                aria-checked={range === "full"}
                className={`fit-chip${range === "full" ? " active" : ""}`}
                title="导出整条时间线"
                onClick={() => setRange("full")}
              >
                整条时间线
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={range === "marks"}
                disabled={!marked}
                className={`fit-chip${range === "marks" ? " active" : ""}`}
                title={marked ? `只导出入点到出点之间的 ${rangeSeconds} 秒` : "先在时间线上按 I 和 O 设入出点，才能只导出区间"}
                onClick={() => { if (marked) setRange("marks"); }}
              >
                入出点区间
              </button>
            </div>
          </Field>

          <Field label="文件名" hint="不用写扩展名，引擎会按容器补上">
            <div className="input-row">
              <input
                className="input"
                value={filename}
                placeholder={sanitizeName(project.name)}
                onChange={(event) => setFilename(event.target.value)}
                aria-label="文件名"
              />
              <span className="mono suffix">.{preset.container}</span>
            </div>
          </Field>

          <Field label="输出文件夹" hint="引擎只允许写进被授权的文件夹">
            <div className="input-row">
              <Btn onClick={() => void chooseFolder()} title="选择引擎允许写入的文件夹">
                <Icon name="folder" size={12} />
                选择文件夹
              </Btn>
              <span
                className="mono ellipsis"
                title={folder || app.info?.output_dir || "引擎默认输出目录"}
              >
                {folder || `默认：${app.info?.output_dir || "引擎输出目录"}`}
              </span>
            </div>
            <p className="hint">
              选择成片的保存位置；不选则使用默认输出文件夹。
            </p>
          </Field>

          <div className="export-summary">
            <span className="panel-label">这次会导出</span>
            <div className="es-grid">
              <b>{humanDuration(end)}</b>
              <span className="mono">{timecode(end, project.settings.frame_rate)}</span>
              <span className="mono dim">{end.toLocaleString("en-US")} tick</span>
              <span>
                {clips.length} 段 · {project.tracks.length} 条轨
              </span>
              <span className="mono">
                {preset.scale?.[0] ?? project.settings.width}×{preset.scale?.[1] ?? project.settings.height}
              </span>
              <span className="mono">{rateLabel(project.settings.frame_rate)}</span>
            </div>
            <p className="es-lock">
              导出锁定 <Tag mono tone="accent">r{project.revision}</Tag>{" "}
              这一刻的快照：之后你或 Agent 再改时间线，也不会改变正在渲染的这个文件。
            </p>
          </div>

          <Field label="交付方案" hint={recipeHint}>
            <div className="recipe-row">
              {(project.recipes ?? []).map((recipe) => (
                <span className="recipe-chip" key={recipe.id}>
                  <button
                    type="button"
                    onClick={() => void exportRecipe(recipe.id, folder || undefined)}
                    disabled={Boolean(blocked) || Boolean(app.busy)}
                    title={`按 r${project.revision} 出货：${recipe.items
                      .map((entry) => `${entry.filename} · ${entry.fit}/${entry.range ?? "full"}`)
                      .join("，")}`}
                  >
                    {recipe.name}
                    <em className="mono dim">{recipe.items.length} 条</em>
                  </button>
                  <button
                    type="button"
                    className="recipe-tiny"
                    onClick={() => saveRecipe(recipe.name, pendingItems, recipe.id)}
                    disabled={Boolean(blocked)}
                    title={`用现在这组设置覆盖「${recipe.name}」：${pendingItems
                      .map((entry) => entry.filename)
                      .join("，")}`}
                  >
                    覆盖
                  </button>
                  <button
                    type="button"
                    className="recipe-tiny"
                    onClick={() => removeRecipe(recipe.id)}
                    title={`删除方案「${recipe.name}」：只删方案，不动时间线，可撤销`}
                  >
                    删
                  </button>
                </span>
              ))}
              <span className="recipe-new">
                <input
                  value={recipeName}
                  onChange={(event) => setRecipeName(event.target.value)}
                  placeholder={timelineName}
                  aria-label="方案名"
                  maxLength={64}
                />
                <button
                  type="button"
                  onClick={() => {
                    saveRecipe(recipeName.trim() || timelineName, pendingItems);
                    setRecipeName("");
                  }}
                  disabled={Boolean(blocked)}
                  title={`存下当前这组：${pendingItems
                    .map((entry) => `${entry.filename}(${entry.fit}/${entry.range})`)
                    .join("，")}`}
                >
                  存为方案
                </button>
              </span>
            </div>
          </Field>

          <div className="export-actions">
            <Btn
              onClick={() => renderPlanPreview(preset.id, fit, range)}
              disabled={!clips.length}
              title="只读：让服务端编译渲染计划，不会写任何文件"
            >
              查看渲染计划
            </Btn>
            {vertical && (
              <label className="batch-row">
                <input
                  type="checkbox"
                  checked={alsoVertical && !audioOnly}
                  onChange={(event) => setAlsoVertical(event.target.checked)}
                  disabled={Boolean(blocked) || audioOnly}
                  title={audioOnly ? "音频交付没有画面，也就没有竖屏那一条" : undefined}
                />
                附带一个 9:16 竖屏（裁切填满），一次交付两个画幅
              </label>
            )}
            <Btn
              variant="primary"
              full
              onClick={() =>
                // 点下去要发出去的就是 pendingItems 那一组，界面不再另写一份交付清单。
                pendingItems.length > 1
                  ? void startRenderBatch(pendingItems, folder || undefined)
                  : void startRender(preset.id, finalName, folder || undefined, fit, range)
              }
              disabled={Boolean(blocked) || Boolean(app.busy)}
              title={blocked || (pendingItems.length > 1
                ? `按 r${project.revision} 导出 ${finalName} 与 ${verticalName}`
                : `按 r${project.revision} 导出 ${finalName}`)}
            >
              <Icon name="export" size={12} />
              开始导出
            </Btn>
          </div>
          {blocked ? (
            <p className="inline-error">
              <Icon name="warning" size={12} />
              {blocked}
            </p>
          ) : null}
        </>
      )}

      <div className="section-head">
        <span className="panel-label">导出任务</span>
        <span className="spacer" />
        <Tag mono>{app.jobs.length}</Tag>
      </div>

      {app.jobs.length ? (
        <div className="job-list">
          {app.jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </div>
      ) : (
        <Empty
          icon="export"
          lines={
            <>
              <b>还没有导出任务</b>
              <span>选好预设点“开始导出”，任务会出现在这里，进度、耗时、失败原因都看得见。</span>
            </>
          }
        />
      )}
    </div>
  );
}

function JobRow({ job }: { job: RenderJob }): JSX.Element {
  const status = STATUS[job.status];
  const ratio = progressOf(job);
  const percent = Math.round(ratio * 100);
  const active = job.status === "queued" || job.status === "running";
  const outPath = job.output_path ?? "";

  return (
    <div className={`job-row ${job.status}`}>
      <div className="job-head">
        <Tag mono tone={status.tone}>
          {status.label}
        </Tag>
        <b className="job-name" title={job.filename}>
          {job.filename}
        </b>
        <span className="spacer" />
        <span className="mono dim" title="锁定提交时的版本">
          r{job.revision}
        </span>
        {job.elapsed_seconds != null ? (
          <span className="mono dim">{job.elapsed_seconds.toFixed(1)} 秒</span>
        ) : null}
        {job.output_size_bytes != null ? (
          <span className="mono dim">{prettyBytes(job.output_size_bytes)}</span>
        ) : null}
        {job.status === "succeeded" && !job.output_checked ? (
          <Tag mono tone="warn">
            未复检
          </Tag>
        ) : null}
      </div>

      {active || job.status === "succeeded" ? (
        <div className="job-bar" title={`已渲染 ${job.rendered_ticks} / ${job.total_ticks} tick`}>
          <span style={{ width: `${percent}%` }} />
          <em className="mono">
            {job.status === "running" ? `${percent}%` : job.status === "queued" ? "等待中" : "完成"}
          </em>
        </div>
      ) : null}

      {outPath ? (
        <div className="mono ellipsis dim" title={outPath}>
          {outPath}
        </div>
      ) : null}

      {job.status === "failed" ? (
        <p className="inline-error">
          <Icon name="warning" size={12} />
          <b className="mono">{job.error_code ?? "RENDER_FAILED"}</b>
          <span>{job.message}</span>
        </p>
      ) : job.message ? (
        <p className="hint">{job.message}</p>
      ) : null}

      <div className="job-actions">
        {job.status === "succeeded" && outPath ? (
          <Btn onClick={() => void bridge.showItem(outPath)} title="在系统文件管理器里选中这个文件">
            <Icon name="folder" size={12} />
            打开位置
          </Btn>
        ) : null}
        {active ? (
          <Btn variant="danger-text" onClick={() => void cancelJob(job.id)} title="中断这次渲染">
            取消
          </Btn>
        ) : null}
      </div>
    </div>
  );
}
