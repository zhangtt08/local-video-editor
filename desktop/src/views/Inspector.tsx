import type { Keyframe } from "../engine";
import { useEffect, useId, useRef, useState } from "react";

import {DEFAULT_COLOR, DEFAULT_EFFECTS, DEFAULT_MASK, DEFAULT_PATH, transitionChoices, type AnimatedEffect, type Clip, type LinkStatus, type SampledValues, type ShapeMask, type TransitionKind, BLEND_MODES} from "../engine";

import { Icon, Modal } from "../ui";
import { GradeFields } from "./GradeFields";
import { SpeedFields } from "./SpeedFields";
import { blurMaxPercent, canAnimateMask, EFFECT_FIELDS, FIELD_LABEL, sharpenLimits, stabilizeBlocked } from "../effects";
import { frameTicks, TIMEBASE, align, humanDuration, seconds, ticks } from "../time";
import {
  clearBatch,
  commitBatch,
  moveClip,
  newBatchId,
  removeBatchItem,
  removeClip,
  removeClipRipple,
  duplicateClip,
  detachAudio,
  runDryRun,
  setMode,
  playhead,
  splitClip,
  timelineEnd,
  trimClip,
  updateProjectMeta,
  useApp,
  useEdit,
  usePlay,
  setClipEffects,
  setClipSpeed,
  setClipColor,
  setClipText,
  fadeClip,
  slipClip,
  slideClip,
  setTransition,
  removeTransition,
  setKeyframe,
  setGraphOpen,
  removeKeyframe,
  appInfo,
  copySelection,
  duplicateSelection,
  removeSelection,
  groupSelection,
  linkSelection,
  prefs,
  setClipMask,
  setMaskEditing,
  updateTrack,
  editableProject,
  nestSelection,
  openSequence,
  updateSequence,
  reframeClip, stabilizeClip, trackMask,
  cutSilence,
  autoCaptions,
  normaliseLoudness,
  alignMasterLoudness,
} from "../store";
import { PROJECT_PRESETS } from "../presets";
import { bridge } from "../bridge";
import { toast } from "../store";

/** 检查器：选中什么就解释什么。精确数值默认收起，需要时状态栏一键打开。 */
export function Inspector() {
  const app = useApp();
  const [nestName, setNestName] = useState<string | null>(null);
  const readyProject = editableProject(app);
  const project = editableProject(app, true) ?? app.project;
  const multiple = app.selectedClips.length > 1;
  const clip = multiple ? undefined : project?.clips[app.selectedClip ?? ""];
  const sequence = app.sequenceId ? project?.sequences?.[app.sequenceId] : null;
  const compound = clip ? project?.assets[clip.asset_id]?.sequence_id : null;

  return (
    <div className="panel-scroll">
      {nestName !== null ? <Modal title="预合成选中片段" sub="内部图层、关键帧和声音继续保留，可进入合成编辑。" onClose={() => setNestName(null)} footer={<><button className="btn" onClick={() => setNestName(null)}>取消</button><button className="btn primary" disabled={!nestName.trim() || Boolean(app.busy)} onClick={() => { nestSelection(nestName); setNestName(null); }}>创建预合成</button></>}><label className="panel-label" htmlFor="nest-name">合成名称</label><input className="input" id="nest-name" autoFocus maxLength={256} value={nestName} onChange={(e) => setNestName(e.target.value)} /><p className="hint">合成使用工程画幅和帧率，透明区域保留。轨道混合在内部独立计算；声音一起收进合成。跨层夹着其它镜头时，请一并选择。</p></Modal> : null}
      {sequence ? <section className="insp-section"><span className="panel-label">当前合成</span><fieldset className="effects-fields" disabled={Boolean(app.busy || !readyProject)}><input className="input" key={sequence.id + sequence.name} aria-label="合成名称" defaultValue={sequence.name} maxLength={256} onBlur={(e) => { const name = e.target.value.trim(); if (name && name !== sequence.name) updateSequence({ name }); }} /><NumberField label="合成时长" hint="缩短时不能截断内部片段或已使用的源区间" value={seconds(sequence.duration_ticks)} quantum={project!.settings.timebase * project!.settings.frame_rate.denominator / project!.settings.frame_rate.numerator} min={project!.settings.frame_rate.denominator / project!.settings.frame_rate.numerator} onCommit={(v) => updateSequence({ duration_ticks: ticks(v) })} /></fieldset></section> : null}
      {app.selectedClips.length ? <section className="insp-section"><button className="btn" disabled={Boolean(app.busy || !readyProject)} onClick={() => setNestName(`合成 ${Object.keys(project?.sequences ?? {}).length + 1}`)}>预合成选中片段</button>{compound ? <button className="btn primary" disabled={Boolean(app.busy || app.batch.length)} onClick={() => openSequence(compound)}>进入合成</button> : null}</section> : null}
      {project ? <details className="insp-section" open={!clip && !multiple}><summary className="panel-label">工程设置</summary><ProjectSettings /></details> : null}
      {app.selectedClips.length ? <AssociationFields /> : null}

      {multiple ? <section className="insp-section"><div className="row-title"><span className="panel-label">成组剪辑</span><span className="tag accent">{app.selectedClips.length} 个片段</span></div>
        <p className="hint">拖动任一选中片段移动整组，保留间隔与相对轨道。Ctrl/Shift 点选增减，空白处拖动框选。</p>
        <div className="batch-actions"><button className="btn" onClick={copySelection}>复制</button><button className="btn" onClick={duplicateSelection}>追加副本</button><button className="btn" onClick={() => removeSelection()}>删除</button></div>
        <button className="btn" onClick={() => removeSelection(true)}>涟漪删除整组</button>
        <p className="hint">涟漪删除只关闭所选片段独占的时间；其他镜头使用的转场重叠区间会保留。整组操作可一次撤销。</p>
      </section> : null}

      {!multiple ? <section className="insp-section">
        <div className="row-title">
          <span className="panel-label">片段</span>
          {clip ? <span className="tag mono">{humanDuration(clip.duration_ticks)}</span> : null}
        </div>
        {!clip ? <div className="empty-note tiny">点时间线上的片段，这里可以改它的起止</div> : <><p className="ellipsis" title={clip.text?.body ?? project?.assets[clip.asset_id]?.label}>{clip.text?.body ?? project?.assets[clip.asset_id]?.label}</p><details><summary className="panel-label">时间与剪辑</summary><fieldset className="effects-fields" disabled={Boolean(app.busy || !readyProject || project?.tracks.find((t) => t.id === clip.track_id)?.locked)}><ClipFields clip={clip} /></fieldset></details></>}
      </section> : null}

      {clip ? <SpeedFields key={`speed-${clip.id}`} clipId={clip.id} /> : null}
      {clip?.text ? <TextFields key={`text-${clip.id}`} clip={clip} /> : null}
      {clip ? <TransitionFields key={`transition-${clip.id}`} clip={clip} /> : null}
      {clip ? <EffectsFields key={clip.id} clip={clip} /> : null}
      {clip && project?.tracks.find((t) => t.id === clip.track_id)?.kind === "video" ? <MaskFields key={`mask-${clip.id}`} clip={clip} /> : null}
      {clip && project?.tracks.find((t) => t.id === clip.track_id)?.kind === "video" ? <BlendFields clip={clip} /> : null}
      {clip && project?.assets[clip.asset_id]?.kind !== "audio" ? <ColorFields clip={clip} /> : null}
      {clip && project?.assets[clip.asset_id]?.kind !== "audio" ? <GradeFields clipId={clip.id} /> : null}

      <BatchPanel />
    </div>
  );

}

/** A typed percentage, kept where the engine would accept it; empty or junk reads back as 0. */
function clampPercent(raw: string, ceiling = 100): number {
  const value = Number(raw);
  return Number.isFinite(value) ? Math.max(0, Math.min(ceiling, Math.round(value))) : 0;
}

function ClipFields({ clip }: { clip: Clip }) {
    const app = useApp();
    const project = editableProject(app, true) ?? app.project;
    if (!project) return null;
    const asset = project.assets[clip.asset_id];
    const track = project.tracks.find((item) => item.id === clip.track_id);
    const q =
      track?.kind === "audio"
        ? Math.round(TIMEBASE / project.settings.sample_rate)
        : Math.round((TIMEBASE * project.settings.frame_rate.denominator) / project.settings.frame_rate.numerator);
    const available =
      asset && asset.kind !== "image" && asset.duration_ticks ? Math.floor((asset.duration_ticks - clip.source_in_ticks) * 100 / (clip.speed_percent ?? 100)) : Number.MAX_SAFE_INTEGER;
    return (
      <>
        <div className="clip-head">
          <span className="ch-name ellipsis" title={clip.text?.body ?? asset?.label}>
            {clip.text?.body ?? asset?.label ?? clip.asset_id}
          </span>
          <span className="ch-kind">{asset?.kind === "sequence" ? "合成" : asset?.kind === "text" ? "文字" : asset?.kind === "image" ? "图片" : asset?.kind === "audio" ? "音频" : "视频"}</span>
        </div>
        <NumberField
          label="开始于"
          hint="这段在时间线上的位置"
          value={seconds(clip.position_ticks)}
          quantum={q}
          min={0}
          onCommit={(value) => moveClip(clip.id, clip.track_id, ticks(value))}
        />
        <NumberField
          label="时长"
          hint={`素材还能提供 ${humanDuration(available)}`}
          value={seconds(clip.duration_ticks)}
          quantum={q}
          min={q / TIMEBASE}
          max={seconds(available)}
          onCommit={(value) => trimClip(clip.id, clip.source_in_ticks, ticks(value))}
        />
        <NumberField
          label="取自素材"
          hint="从素材的第几秒开始用（图片固定 0）"
          value={seconds(clip.source_in_ticks)}
          quantum={1}
          min={0}
          disabled={asset?.kind === "image" || asset?.kind === "text"}
          onCommit={(value) => {
            const newIn = ticks(value);
            // 上限要用“新入点”算：入点后移，素材余量随之缩短。
            const limit =
              asset && asset.kind !== "image" && asset.duration_ticks
                ? Math.floor((asset.duration_ticks - newIn) * 100 / (clip.speed_percent ?? 100) / q) * q
                : clip.duration_ticks;
            trimClip(clip.id, newIn, Math.max(q, Math.min(clip.duration_ticks, limit)));
          }}
        />
        {asset?.kind !== "image" && asset?.kind !== "text" ? <div className="effect-row"><label htmlFor="clip-speed">播放速度</label><select id="clip-speed" className="input" value={(clip.speed_percent ?? 100) / 100} disabled={track?.locked} onChange={(e) => setClipSpeed(clip.id, Number(e.target.value))}>
          {[.25, .5, .75, 1, 1.25, 1.5, 2, 3, 4].map((speed) => <option key={speed} value={speed}>{speed}×</option>)}
          {![25,50,75,100,125,150,200,300,400].includes(clip.speed_percent ?? 100) ? <option value={(clip.speed_percent ?? 100) / 100}>{(clip.speed_percent ?? 100) / 100}×</option> : null}
        </select></div> : null}
        {asset?.kind !== "image" && asset?.kind !== "text" ? <p className="hint">保留音高，变速后自动移动本轨后续片段；动画仍按时间线时间播放。</p> : null}
        <div className="insp-actions">
          <SplitButton clip={clip} />
          <button className="btn" title="复制一段接到本轨末尾（Ctrl+D）" onClick={() => duplicateClip(clip.id)}>
            <Icon name="copy" /> 复制
          </button>
          {asset?.kind === "video" && asset.verified?.has_audio && clip.embedded_audio !== false ? <button className="btn" title="把本段的声音拆成独立声音轨，方便单独淡入淡出或对齐其他音轨" onClick={() => detachAudio(clip.id)}>
            <Icon name="split" /> 拆分内嵌声音
          </button> : null}
          {(asset?.kind === "audio" || (asset?.kind === "video" && asset.verified?.has_audio && clip.embedded_audio !== false)) ? <button className="btn" disabled={Boolean(clip.speed_curve)} title={clip.speed_curve ? "带变速曲线的片段还不能去空白：时间不是线性的，切点会切进字里" : "扫描本段声音，把 0.25 秒以上的停顿剪掉并把后面的内容左移（阈值 -35 dB，切点向内取整帧）"} onClick={() => cutSilence(clip.id)}>
            <Icon name="split" /> 去空白
          </button> : null}
          {(asset?.kind === "audio" || (asset?.kind === "video" && asset.verified?.has_audio && clip.embedded_audio !== false)) ? <button className="btn" disabled={Boolean(clip.speed_curve) || (clip.keyframes ?? []).some((key) => key.property === "gain")} title={clip.speed_curve ? "带变速曲线的片段还不能测响度：时间不是线性的，量到的区间对不上" : (clip.keyframes ?? []).some((key) => key.property === "gain") ? "这段的音量已经由关键帧画过包络，改单个增益听不出来；请直接编辑那些关键帧" : "用 FFmpeg 的 EBU R128 表量这段的积分响度，写入一个线性增益把它统一到 -16 LUFS（真峰值不超过 -1 dBTP）；不加压缩器，动态保持录下来的样子"} onClick={() => normaliseLoudness(clip.id)}>
            <Icon name="volume" /> 统一响度
          </button> : null}
          {app.caps?.features?.speech_captions && (asset?.kind === "audio" || (asset?.kind === "video" && asset.verified?.has_audio && clip.embedded_audio !== false)) ? <button className="btn" disabled={Boolean(clip.speed_curve)} title={clip.speed_curve ? "带变速曲线的片段还不能自动字幕：时间不是线性的，字会对不上画面" : "用本机语音模型听这段的说话，生成一条可编辑的字幕轨；识别在本地完成，不会上传声音"} onClick={() => autoCaptions(clip.id)}>
            <Icon name="captions" /> 自动字幕
          </button> : null}
        </div>
        <div className="insp-actions">
          <button
            className="btn danger-text"
            title="删掉这段，后面的片段自动左移补上空隙（Shift+Delete）"
            onClick={() => removeClipRipple(clip.id)}
          >
            <Icon name="trash" /> 删除并补齐
          </button>
          <button className="btn danger-text" title="只删这一段，留下空隙（Delete）" onClick={() => removeClip(clip.id)}>
            留空隙删除
          </button>
        </div>
      </>
    );
}

function AssociationFields() {
  const app = useApp(); const edit = useEdit(); const project = app.project!;
  const clips = app.selectedClips.map((id) => project.clips[id]).filter(Boolean);
  const linkIds = [...new Set(clips.map((c) => c.link_id).filter(Boolean))];
  const [status, setStatus] = useState<{ revision: number; project: string; sequenceId: string | null; links: Record<string, LinkStatus> } | null>(null);
  useEffect(() => {
    if (!linkIds.length) return;
    const controller = new AbortController();
    void fetch(`${appInfo.baseUrl()}/v1/projects/${project.id}/preview-manifest?revision=${project.revision}${app.sequenceId ? `&sequence_id=${app.sequenceId}` : ""}`, { headers: { Authorization: `Bearer ${appInfo.token()}` }, signal: controller.signal })
      .then((r) => { if (!r.ok) throw new Error("读取链接状态失败"); return r.json(); })
      .then((value) => setStatus({ revision: value.revision, project: project.id, sequenceId: app.sequenceId, links: value.links }))
      .catch(() => { if (!controller.signal.aborted) setStatus({ revision: project.revision, project: project.id, sequenceId: app.sequenceId, links: {} }); });
    return () => controller.abort();
  }, [project.id, project.revision, app.sequenceId, linkIds.join(",")]);
  const current = status?.revision === project.revision && status.project === project.id && status.sequenceId === app.sequenceId ? status.links : null;
  const kinds = new Set(clips.map((c) => project.assets[c.asset_id]?.kind));
  const canLink = kinds.size === 2 && kinds.has("video") && kinds.has("audio") && clips.every((c) => c.position_ticks === clips[0].position_ticks && c.duration_ticks === clips[0].duration_ticks && (c.speed_percent ?? 100) === (clips[0].speed_percent ?? 100));
  return <section className="insp-section"><div className="row-title"><span className="panel-label">组合与链接</span><button className={`btn tiny subtle${edit.linkedSelection ? " active" : ""}`} aria-pressed={edit.linkedSelection} onClick={() => prefs.toggleLinkedSelection()}>联动{edit.linkedSelection ? "开" : "关"}</button></div>
    <div className="insp-actions"><button className="btn tiny" disabled={clips.length < 2} onClick={() => groupSelection()}>组合</button><button className="btn tiny" disabled={!clips.some((c) => c.group_id)} onClick={() => groupSelection(true)}>取消组合</button></div>
    <div className="insp-actions"><button className="btn tiny" disabled={!canLink} title="先对齐视频与音频的开始、时长和速度；当前源入点差值作为同步基准。" onClick={() => linkSelection()}>链接音画</button><button className="btn tiny" disabled={!linkIds.length} onClick={() => linkSelection(true)}>解除链接</button></div>
    <p className="hint">组合保存在工程里。链接联动移动、分割与修剪；Alt 点选可单选，关闭联动可独立编辑。</p>
    {linkIds.map((id) => { const link = current?.[id!]; return <div key={id} className={`link-status${link && !link.synchronized ? " out-of-sync" : ""}`} role="status">{!link ? current ? "同步状态不可用，请重新打开工程。" : "正在检查同步…" : link.synchronized ? `音画同步 · ${link.clip_ids.length} 段` : "音画已失步：位置、源入点、时长或速度不同。撤销独立改动，或解除链接后重新对齐。"}</div>; })}
  </section>;
}


function EffectsFields({ clip }: { clip: Clip }) {
  const app = useApp();
  const play = usePlay();
  const [interpolation, setInterpolation] = useState<Keyframe["interpolation"]>("linear");
  const [stabilizeStrength, setStabilizeStrength] = useState(100);
  const [stabilizeCrop, setStabilizeCrop] = useState(10);
  // The ceiling the contract allows, so the box can never offer what the engine would refuse.
  const cropCeiling = Math.round((app.caps?.limits?.stabilize_max_crop ?? 0.25) * 100);
  const [sampled, setSampled] = useState<{ at: number; clip: Clip; values: SampledValues } | null>(null);
  const [fade, setFade] = useState(.5);
  const [slideFrames, setSlideFrames] = useState(1);
  const [fadeProperty, setFadeProperty] = useState<"opacity" | "gain">("opacity");
  const effects = clip.effects ?? DEFAULT_EFFECTS;
  const at = Math.round(Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)));
  const offset = clip.animation_offset_ticks ?? 0;
  const project = editableProject(app);
  const asset = (project ?? app.project)?.assets[clip.asset_id];
  const locked = Boolean(app.busy || !project || project.tracks.find((t) => t.id === clip.track_id)?.locked);
  const slidingBlocked = Boolean(clip.speed_curve) || Boolean(clip.link_id);
  const frames = (clip.keyframes ?? []).filter((k) => k.at_ticks >= offset && k.at_ticks <= offset + clip.duration_ticks);
  // 柔焦这一行没有 ◇ 关键帧按钮：导出侧的 gblur 没有逐帧半径，界面不能假装能给它做动画。
  // 上限完全由引擎下发的两个数决定（见 effects.ts 的 blurMaxPercent），界面不自己另写一套。
  const blurMax = blurMaxPercent(app.caps, project?.settings.height ?? 0);
  const sharpen = sharpenLimits(app.caps, project?.settings.height ?? 0);
  const stabBlock = stabilizeBlocked(clip);
  const outside = play.ticks < clip.position_ticks || play.ticks > clip.position_ticks + clip.duration_ticks;
  useEffect(() => {
    if (!project || play.playing || !clip.keyframes?.length) return;
    let disposed = false;
    const timer = window.setTimeout(() => { void appInfo.engine()?.animationSample(clip, at).then((result) => {
      if (!disposed) setSampled({ at, clip, values: result.values });
    }).catch(() => { if (!disposed) setSampled(null); }); }, 100);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [clip, project, at, play.playing]);
  const currentValues: Record<AnimatedEffect, number> = sampled?.at === at && sampled.clip === clip ? sampled.values : effects;
  const sampleReady = !clip.keyframes?.length || Boolean(sampled?.at === at && sampled.clip === clip);
  return <section className="insp-section effects-section">
    <div className="row-title"><span className="panel-label">{asset?.kind === "audio" ? "声音" : "变换与动画"}</span><span className="spacer" />
      <button className="btn tiny subtle" disabled={locked} title="重置静态属性；保留已设置的关键帧" onClick={() => setClipEffects(clip.id, DEFAULT_EFFECTS)}>重置属性</button></div>
    <fieldset disabled={locked || !sampleReady} className="effects-fields">
      {EFFECT_FIELDS.filter((f) => asset?.kind !== "audio" || f.property === "gain").map((f) => {
        const frame = frames.find((k) => k.property === f.property && k.at_ticks === at + offset);
        return <div className="effect-row" key={f.property}>
          <label htmlFor={`fx-${f.property}`}>{f.label}</label>
          <EffectInput id={`fx-${f.property}`} value={(frame?.value ?? currentValues[f.property]) * f.factor} min={f.min} max={f.max} step={f.step}
            onCommit={(value) => (clip.keyframes ?? []).some((k) => k.property === f.property) ? setKeyframe(clip.id, { ...frame, property: f.property, at_ticks: at, value: value / f.factor, interpolation: frame?.interpolation ?? interpolation }) : setClipEffects(clip.id, { [f.property]: value / f.factor })} />
          <span className="dim">{f.unit}</span>
          <button type="button" className={`keyframe-btn${frame ? " active" : ""}`} aria-label={frame ? `删除${f.label}关键帧` : `添加${f.label}关键帧`}
            disabled={outside || play.playing || !sampleReady}
            title={`${frame ? "删除" : "添加"}当前位置的${f.label}关键帧`}
            onClick={() => frame ? removeKeyframe(clip.id, f.property, at) : setKeyframe(clip.id, { property: f.property, at_ticks: at, value: currentValues[f.property], interpolation })}>◇</button>
        </div>;
      })}
      {blurMax > 0 && asset?.kind !== "audio" ? <div className="effect-row">
        <label htmlFor="fx-blur">柔焦</label>
        <EffectInput id="fx-blur" value={(effects.blur ?? 0) * 100} min={0} max={blurMax} step={0.5} onCommit={(value) => setClipEffects(clip.id, { blur: value / 100 })} />
        <span className="dim">% 高 · ≈{(effects.blur * (project?.settings.height ?? 0)).toFixed(1)} px</span>
      </div> : null}
          {app.caps?.features?.clip_stabilize && asset?.kind !== "audio" ? <span className="stabilize-row">
            <button className="btn tiny" disabled={Boolean(app.busy) || stabBlock !== null}
              title={stabBlock ?? (clip.stabilization ? "这段已经稳定过：再按一次按下面的强度重算一遍，替换掉上一次的抵消，不会叠两层" : "让引擎读这段画面，量出相机自己的抖动，再写入反过来的平移与缩放把它抵消；强度 0 表示不动画面，允许裁切是愿意为消抖让画面放大多少。撤销一步回到稳定前")}
              onClick={() => void stabilizeClip(clip.id, stabilizeStrength / 100, stabilizeCrop / 100)}>{clip.stabilization ? "重新稳定" : "画面稳定"}</button>
            {clip.stabilization ? <button className="btn tiny subtle" disabled={Boolean(app.busy)} title="把这条稳定摘掉：引擎写过的位移/缩放/旋转关键帧连同它的记录一起清掉，画面回到拍下来的样子" onClick={() => void stabilizeClip(clip.id, 0, stabilizeCrop / 100)}>取消稳定</button> : null}
            <label className="dim">强度
              <input className="input tiny" type="number" min={0} max={100} step={5} value={stabilizeStrength}
                aria-label="稳定强度" onChange={(e) => setStabilizeStrength(clampPercent(e.target.value))} />%
            </label>
            <label className="dim">允许裁切
              <input className="input tiny" type="number" min={0} max={cropCeiling} step={1} value={stabilizeCrop}
                aria-label="稳定允许裁切" onChange={(e) => setStabilizeCrop(clampPercent(e.target.value, cropCeiling))} />%
            </label>
            {clip.stabilization ? <span className="dim stabilize-state" role="status">已稳定 · 强度 {Math.round(clip.stabilization.strength * 100)}% · 抵消 {clip.stabilization.translation_correction.toFixed(3)} 画面宽 · {clip.stabilization.points} 个点{clip.stabilization.roll_correction ? ` · 转动 ${clip.stabilization.roll_correction.toFixed(2)}°` : ""}</span> : null}
          </span> : null}
            {sharpen.amount > 0 && asset?.kind !== "audio" ? <>
        <div className="effect-row">
          <label htmlFor="fx-sharpen">清晰</label>
          <EffectInput id="fx-sharpen" value={(effects.sharpen ?? 0) * 100} min={0} max={sharpen.amount * 100} step={5} onCommit={(value) => setClipEffects(clip.id, { sharpen: value / 100 })} />
          <span className="dim">%</span>
        </div>
        <div className="effect-row">
          <label htmlFor="fx-sharpen-radius">清晰半径</label>
          <EffectInput id="fx-sharpen-radius" value={(effects.sharpen_radius ?? 0) * 100} min={0} max={sharpen.radiusPercent} step={0.25} onCommit={(value) => setClipEffects(clip.id, { sharpen_radius: value / 100 })} />
          <span className="dim">% 高 · ≈{((effects.sharpen_radius ?? 0) * (project?.settings.height ?? 0)).toFixed(1)} px</span>
        </div>
      </> : null}
    </fieldset>
    <div className="animation-head"><span className="panel-label">关键帧</span><span className="spacer" />
      <button className="btn tiny subtle" onClick={() => setGraphOpen(true)}>曲线编辑</button>
      <select className="input" aria-label="新关键帧插值" value={interpolation} onChange={(e) => setInterpolation(e.target.value as Keyframe["interpolation"])}><option value="linear">线性</option><option value="ease">缓入缓出</option><option value="hold">保持</option><option value="bezier">贝塞尔</option></select></div>
    <p className="hint">移动播放头，点 ◇ 记录属性。选中已有关键帧后修改数值。</p>
    <div className="keyframe-list">
      {frames.sort((a, b) => a.at_ticks - b.at_ticks).map((k) => <div key={`${k.property}-${k.at_ticks}`} className="keyframe-item">
        <button onClick={() => { playhead.pause(); playhead.set(clip.position_ticks + k.at_ticks - offset); }}>
          <span className="keyframe-dot">◇</span>{FIELD_LABEL[k.property] ?? k.property}<span className="mono">{((k.at_ticks - offset) / TIMEBASE).toFixed(2)}s</span>
        </button>
        <select aria-label={`${k.property}关键帧插值`} disabled={locked} value={k.interpolation} onChange={(e) => setKeyframe(clip.id, { ...k, at_ticks: k.at_ticks - offset, interpolation: e.target.value as Keyframe["interpolation"], bezier: e.target.value === "bezier" ? k.bezier : null })}><option value="linear">线性</option><option value="ease">缓入缓出</option><option value="hold">保持</option><option value="bezier">贝塞尔</option></select>
        <button aria-label="删除关键帧" disabled={locked} onClick={() => removeKeyframe(clip.id, k.property, k.at_ticks - offset)}>×</button>
      </div>)}
    </div>
    <details className="slide-controls"><summary className="panel-label">源画面划动与滑移</summary><fieldset disabled={locked} className="effects-fields">
      <div className="effect-row"><label htmlFor="slide-frames">步长</label><input id="slide-frames" className="input" type="number" min={1} max={Math.max(1, Math.floor(clip.duration_ticks / (project ? frameTicks(project.settings.frame_rate) : 1)))} step={1} value={slideFrames} onChange={(e) => setSlideFrames(Math.max(1, Math.round(Number(e.target.value) || 1)))} /><span>帧</span></div>
      <div className="insp-actions">
        <button className="btn tiny" disabled={slidingBlocked} title="只换这段素材播到哪一格：片段位置与时长都不动" onClick={() => slipClip(clip.id, -slideFrames)}>划动 ←</button>
        <button className="btn tiny" disabled={slidingBlocked} title="同上，往后取素材" onClick={() => slipClip(clip.id, slideFrames)}>划动 →</button>
        <button className="btn tiny" disabled={slidingBlocked} title="整段左移：左边相邻段让出这些帧、右边相邻段收回同样多，这条轨总长不变" onClick={() => slideClip(clip.id, -slideFrames)}>滑移 ←</button>
        <button className="btn tiny" disabled={slidingBlocked} title="整段右移：右边让出、左边收回，总长不变" onClick={() => slideClip(clip.id, slideFrames)}>滑移 →</button>
      </div>
      <p className="hint">{slidingBlocked ? "带变速曲线或已链接声音的片段不能划动/滑移：时间不是线性的，让出来的帧在两侧含义不同。请直接修剪，或先解除链接。" : "划动改这段素材的起点；滑移改这段在时间线上的位置，两侧相邻片段各自补/让同样的帧数，整条轨不变长——两侧都得有相邻片段才滑得动，素材头尾不够时引擎会拒绝并说明原因。"}</p>
    </fieldset></details>
    <details className="fade-controls"><summary className="panel-label">快速淡入淡出</summary><fieldset disabled={locked} className="effects-fields">
      <div className="effect-row"><label htmlFor="fade-duration">时长</label><input id="fade-duration" className="input" type="number" min={.01} max={seconds(clip.duration_ticks)} step={.1} value={fade} onChange={(e) => setFade(Number(e.target.value))} /><span>秒</span></div>
      {asset?.kind !== "audio" ? <select className="input" aria-label="淡入淡出属性" value={fadeProperty} onChange={(e) => setFadeProperty(e.target.value as "opacity" | "gain")}><option value="opacity">画面透明度</option><option value="gain">音量</option></select> : null}
      <div className="insp-actions">{([['in','淡入'],['out','淡出'],['both','双向']] as const).map(([mode,label]) => <button key={mode} className="btn tiny" disabled={!Number.isFinite(fade) || fade <= 0 || ticks(fade) * (mode === 'both' ? 2 : 1) > clip.duration_ticks} onClick={() => fadeClip(clip.id, asset?.kind === 'audio' ? 'gain' : fadeProperty, fade, mode)}>{label}</button>)}</div>
      <p className="hint">替换该属性的关键帧，使用缓入缓出曲线。</p>
    </fieldset></details>
  </section>;
}

function EffectInput({ id, value, min, max, step, onCommit }: { id: string; value: number; min: number; max: number; step: number; onCommit: (value: number) => void }) {
  const [text, setText] = useState(value.toFixed(1));
  const escaped = useRef(false);
  useEffect(() => setText(value.toFixed(1)), [value]);
  return <input id={id} className="input mono" type="number" min={min} max={max} step={step} value={text}
    onChange={(e) => setText(e.target.value)} onBlur={() => { if (escaped.current) { escaped.current = false; setText(value.toFixed(1)); return; } const n = Number(text); if (text.trim() && Number.isFinite(n)) { const clamped = Math.min(max, Math.max(min, n)); if (clamped !== value) onCommit(clamped); setText(clamped.toFixed(1)); } else setText(value.toFixed(1)); }}
    onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { escaped.current = true; e.currentTarget.blur(); } }} />;
}

/** Numeric mask rows: field, label, min, max, keyframe property. */
const MASK_ROWS = [['center_x', '中心 X', 0, 100, 'mask_x'], ['center_y', '中心 Y', 0, 100, 'mask_y'], ['width', '宽度', 1, 200, 'mask_width'], ['height', '高度', 1, 200, 'mask_height']] as const;

/** A free-form outline is positioned by its vertices, and its box is always the drawn bounds, so
 * there is no numeric box to edit — the centre curves come from 跟踪主体 or the curve editor. */
const maskRows = (mask: ShapeMask) => (mask.shape === "path" ? [] : MASK_ROWS);

function MaskFields({ clip }: { clip: Clip }) {
  const app = useApp();
  const play = usePlay();
  const project = editableProject(app);
  const mask = clip.mask;
  const disabled = Boolean(app.busy || !project || project.tracks.find((t) => t.id === clip.track_id)?.locked);
  const at = Math.round(Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)));
  const frames = clip.keyframes ?? [];
  const animatable = canAnimateMask(mask);
  return <details className="insp-section mask-section"><summary className="panel-label">遮罩{mask ? ` · ${{ ellipse: "椭圆", rectangle: "矩形", path: "路径" }[mask.shape]}` : ""}</summary>
    <fieldset className="effects-fields" disabled={disabled}>
      <label className="mask-shape">形状 <select className="input" aria-label="遮罩形状" value={mask?.shape ?? "none"} onChange={(e) => { const shape = e.target.value; if (shape === "none") { setClipMask(clip.id, null); return; } const base = { ...(mask ?? DEFAULT_MASK), shape: shape as ShapeMask["shape"] }; setClipMask(clip.id, shape === "path" ? { ...base, vertices: base.vertices?.length ? base.vertices : DEFAULT_PATH.map((vertex) => ({ ...vertex, handle_out: [...vertex.handle_out] as [number, number], handle_in: [...vertex.handle_in] as [number, number] })) } : { ...base, vertices: null }); }}><option value="none">无</option><option value="ellipse">椭圆</option><option value="rectangle">矩形</option><option value="path">路径</option></select></label>
      {mask ? <>
        {mask.shape === "path" ? <p className="hint">路径顶点 {mask.vertices?.length ?? 0} 个：画面中拖顶点改形状（拖动即整体搬动轮廓），拖小方块改曲线控制柄，双击在最近的那条边上加一个点，选中后方向键微调、Delete 删除，或点画面下方出现的小面板用「删除顶点 / 抹成角点 / 自动平滑」。向内羽化按画面短边折算成高斯半径。轮廓按画好的形状与大小裁切：要让它随时间移动就点「跟踪主体」，或在曲线编辑器里给「遮罩中心 X/Y」双击加关键帧；形状与大小本身还不能随时间变化。</p> : null}
        {(canAnimateMask(mask) ? maskRows(mask) : []).map(([field, label, min, max, property]) => {
          const frame = frames.find((k) => k.property === property && k.at_ticks === at + (clip.animation_offset_ticks ?? 0));
          const animated = (clip.keyframes ?? []).some((k) => k.property === property);
          return <div className="effect-row" key={field}><label htmlFor={`mask-${field}`}>{label}</label><EffectInput id={`mask-${field}`} value={(frame?.value ?? mask[field]) * 100} min={min} max={max} step={1} onCommit={(value) => animated ? setKeyframe(clip.id, { property, at_ticks: at, value: value / 100, interpolation: frame?.interpolation ?? "linear" }) : setClipMask(clip.id, { ...mask, [field]: value / 100 })} /><span className="dim">%</span>
            {animatable ? <button type="button" className={`keyframe-btn${frame ? " active" : ""}`} aria-label={frame ? `删除${label}关键帧` : `添加${label}关键帧`} title={`${frame ? "删除" : "添加"}当前位置的${label}关键帧`} disabled={disabled} onClick={() => frame ? removeKeyframe(clip.id, property, at + (clip.animation_offset_ticks ?? 0)) : setKeyframe(clip.id, { property, at_ticks: at, value: mask[field], interpolation: "linear" })}>◇</button> : null}
          </div>;
        })}
        <div className="effect-row"><label htmlFor="mask-feather">向内羽化</label><EffectInput id="mask-feather" value={mask.feather * 100} min={0} max={100} step={1} onCommit={(value) => setClipMask(clip.id, { ...mask, feather: value / 100 })} /><span className="dim">%</span></div>
        <label><input type="checkbox" checked={mask.inverted} onChange={(e) => setClipMask(clip.id, { ...mask, inverted: e.target.checked })} />反转遮罩</label>
        <div className="insp-actions"><button className={`btn tiny${app.maskEditing ? " active" : ""}`} aria-pressed={app.maskEditing} onClick={() => setMaskEditing(!app.maskEditing)}>画面中编辑</button>
          {animatable && project ? <button className="btn tiny" disabled={disabled} title={mask.shape === "path" ? "从播放头开始逐帧分析画面，把轮廓的中心写成关键帧；路径遮罩只整体搬动，不改形状与大小。主体被挡住时按匀速补一段，跟丢时会停下来说明" : "从播放头开始逐帧分析画面，把遮罩中心与大小写成关键帧；主体被挡住时按匀速补一段，跟丢时会停下来说明"} onClick={() => { const rate = project.settings.frame_rate; const whole = Math.floor(((clip.duration_ticks - at) * rate.numerator) / (TIMEBASE * rate.denominator)); trackMask(clip.id, at, Math.max(2, Math.min(300, whole))); }}>{(clip.keyframes ?? []).some((key) => key.property === "mask_x") ? "接着跟" : "跟踪主体"}</button> : null}
          {animatable && project && (clip.keyframes ?? []).some((key) => key.property === "mask_x") ? <button className="btn tiny subtle" disabled={disabled} title="整条重跟：从片段开头重新分析，播放头之前已有的路径会被这一段的结果替换" onClick={() => { const rate = project.settings.frame_rate; const whole = Math.floor((clip.duration_ticks * rate.numerator) / (TIMEBASE * rate.denominator)); trackMask(clip.id, 0, Math.max(2, Math.min(300, whole)), false); }}>从头重跟</button> : null}
          {animatable && project ? <button className="btn tiny" disabled={disabled || Boolean(clip.stabilization)} title={clip.stabilization ? "这段画面带着一次稳定：重构图写的就是稳定占用的位移/缩放三条曲线，跑一遍会把稳定悄悄抹掉。先「取消稳定」，再重构图。" : "读取刚跟踪出来的遮罩路径，写入把主体保持在画面正中的平移与缩放曲线；竖屏裁切出货时主体不会跑出画面。放大上限 4 倍，跟不到时会说明"} onClick={() => void reframeClip(clip.id)}>主体跟随重构图</button> : null}
          <button className="btn tiny" onClick={() => setClipMask(clip.id, { ...DEFAULT_MASK, shape: mask.shape, vertices: mask.shape === "path" ? DEFAULT_PATH.map((vertex) => ({ ...vertex, handle_out: [...vertex.handle_out] as [number, number], handle_in: [...vertex.handle_in] as [number, number] })) : null })}>重置遮罩</button></div>
        <p className="hint">遮罩随片段变换；矩形/椭圆拖中间移动、拖四角缩放，羽化占半径比例。中心与大小可按◇打关键帧，「跟踪主体」会一次写入整条路径。路径遮罩按画好的轮廓裁切，可以打「中心 X / 中心 Y」关键帧、也可以跟踪，但轮廓的形状与大小还不能随时间变化；反相遮罩不支持关键帧。声音保持原样。</p>
      </> : null}
    </fieldset>
  </details>;
}


function BlendFields({ clip }: { clip: Clip }) {
  const app = useApp();
  const project = editableProject(app);
  const track = (editableProject(app, true) ?? app.project)?.tracks.find((t) => t.id === clip.track_id);
  if (!track) return null;
  const disabled = Boolean(app.busy || !project || track.locked);
  return <details className="insp-section"><summary className="panel-label">轨道合成 · {BLEND_MODES.find(([mode]) => mode === (track.blend_mode ?? 'normal'))?.[1]}</summary>
    <fieldset className="effects-fields" disabled={disabled}><label className="mask-shape">混合 <select className="input" aria-label="画面轨混合模式" value={track.blend_mode ?? 'normal'} onChange={(e) => updateTrack(track.id,{blend_mode:e.target.value as typeof track.blend_mode},'调整轨道混合模式')}>{BLEND_MODES.map(([mode,label]) => <option key={mode} value={mode}>{label}</option>)}</select></label>
    <p className="hint">作用于「{track.name}」整轨，与下方画面混合。遮罩和透明度控制覆盖范围；同轨转场先合成再混合。</p></fieldset>
  </details>;
}

function ColorFields({ clip }: { clip: Clip }) {
  const app = useApp(); const color = clip.color ?? DEFAULT_COLOR;
  const project = editableProject(app);
  const locked = Boolean(app.busy || !project || project.tracks.find((t) => t.id === clip.track_id)?.locked);
  return <details className="insp-section"><summary className="panel-label">画面色彩</summary>
    <fieldset className="effects-fields" disabled={locked}>
      {([['exposure', '曝光', -2, 2, 1], ['contrast', '对比度', 0, 200, 100], ['saturation', '饱和度', 0, 200, 100]] as const).map(([property, label, min, max, factor]) => <div className="effect-row" key={property}>
        <label htmlFor={`color-${property}`}>{label}</label><EffectInput id={`color-${property}`} min={min} max={max} step={property === 'exposure' ? .1 : 1} value={color[property] * factor} onCommit={(value) => setClipColor(clip.id, { [property]: value / factor })} /><span className="dim">{factor === 100 ? '%' : 'EV'}</span>
      </div>)}
      <button className="btn tiny" onClick={() => setClipColor(clip.id, DEFAULT_COLOR)}>重置色彩</button>
    </fieldset>
  </details>;
}

function TextFields({ clip }: { clip: Clip }) {
  const app = useApp(); const text = clip.text!;
  const [body, setBody] = useState(text.body);
  useEffect(() => setBody(text.body), [text.body]);
  const project = editableProject(app);
  const locked = Boolean(app.busy || !project || project.tracks.find((t) => t.id === clip.track_id)?.locked);
  return <section className="insp-section"><span className="panel-label">文字内容</span><fieldset className="effects-fields" disabled={locked}>
    <textarea className="input caption-editor" aria-label="文字内容" rows={3} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} onBlur={() => { if (body.trim() && body !== text.body) setClipText(clip.id, { body }); else if (!body.trim()) setBody(text.body); }} />
    <div className="effect-row"><label htmlFor="text-size">字号</label><EffectInput id="text-size" min={1} max={20} step={.1} value={text.font_size * 100} onCommit={(value) => setClipText(clip.id, { font_size: value / 100 })} /><span className="dim">% 高</span></div>
    <div className="effect-row"><label htmlFor="text-color">颜色</label><input id="text-color" type="color" value={text.color} onChange={(e) => setClipText(clip.id, { color: e.target.value })} /></div>
    <div className="effect-row"><label htmlFor="text-align">位置</label><select id="text-align" className="input" value={text.align ?? "center"} onChange={(e) => setClipText(clip.id, { align: e.target.value as typeof text.align })}><option value="top">靠上</option><option value="center">居中</option><option value="bottom">靠下</option></select></div>
    <div className="effect-row"><label htmlFor="text-box">字块垫子</label><input id="text-box" type="checkbox" checked={Boolean(text.box)} onChange={(e) => setClipText(clip.id, { box: e.target.checked })} /></div>
    {app.caps?.features.text_styling ? <>
      <div className="effect-row"><label htmlFor="text-font">字体</label><select id="text-font" className="input" value={text.font ?? "yahei"} onChange={(e) => setClipText(clip.id, { font: e.target.value })}>{(app.caps?.text_fonts ?? []).map((face) => <option key={face.id} value={face.id}>{face.label}</option>)}</select></div>
      <div className="effect-row"><label htmlFor="text-halign">横排</label><select id="text-halign" className="input" value={text.text_align ?? "center"} onChange={(e) => setClipText(clip.id, { text_align: e.target.value as typeof text.text_align })}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></div>
      <div className="effect-row"><label htmlFor="text-outline">描边</label><EffectInput id="text-outline" min={0} max={20} step={0.5} value={(text.outline_width ?? 0.04) * 100} onCommit={(value) => setClipText(clip.id, { outline_width: value / 100 })} /><span className="dim">% 字号</span></div>
      <div className="effect-row"><label htmlFor="text-outline-color">描边色</label><input id="text-outline-color" type="color" value={text.outline_color ?? "#000000"} onChange={(e) => setClipText(clip.id, { outline_color: e.target.value })} /></div>
      <div className="effect-row"><label htmlFor="text-shadow-x">阴影左右</label><EffectInput id="text-shadow-x" min={-100} max={100} step={1} value={(text.shadow_x ?? 0) * 100} onCommit={(value) => setClipText(clip.id, { shadow_x: value / 100 })} /><span className="dim">% 字号</span></div>
      <div className="effect-row"><label htmlFor="text-shadow-y">阴影上下</label><EffectInput id="text-shadow-y" min={-100} max={100} step={1} value={(text.shadow_y ?? 0) * 100} onCommit={(value) => setClipText(clip.id, { shadow_y: value / 100 })} /><span className="dim">% 字号</span></div>
      <div className="effect-row"><label htmlFor="text-shadow-color">阴影色</label><input id="text-shadow-color" type="color" value={text.shadow_color ?? "#000000"} onChange={(e) => setClipText(clip.id, { shadow_color: e.target.value })} /></div>
      <div className="effect-row"><label htmlFor="text-box-color">垫子色</label><input id="text-box-color" type="color" value={text.box_color ?? "#000000"} onChange={(e) => setClipText(clip.id, { box_color: e.target.value })} /></div>
      <div className="effect-row"><label htmlFor="text-box-opacity">垫子浓度</label><EffectInput id="text-box-opacity" min={0} max={100} step={5} value={(text.box_opacity ?? 0.45) * 100} onCommit={(value) => setClipText(clip.id, { box_opacity: value / 100 })} /><span className="dim">%</span></div>
      <div className="effect-row"><label htmlFor="text-line-spacing">行距</label><EffectInput id="text-line-spacing" min={0} max={200} step={5} value={(text.line_spacing ?? 0.2) * 100} onCommit={(value) => setClipText(clip.id, { line_spacing: value / 100 })} /><span className="dim">% 字号</span></div>
      <p className="hint">这些数在预览与导出里是同一组：描边、阴影偏移、行距与垫子浓度都按「字号的百分之几」换算，FFmpeg 的 drawtext 与浏览器各画一遍。阴影没有「模糊」这一档——drawtext 画不出模糊，给了就只有预览里看得到、成片里没有，所以不做。</p>
    </> : null}
    <button className="btn tiny" onClick={() => { const project = app.project; if (!project) return; void appInfo.engine()?.captions(project.id, project.revision, clip.track_id, app.sequenceId).then(async ({ srt }) => { const copied = await bridge.copyText(srt); toast(copied ? "ok" : "warn", copied ? "本轨字幕已复制为 SRT" : "无法访问剪贴板"); }).catch(() => toast("error", "字幕导出失败")); }}>复制本轨 SRT</button>
  </fieldset></section>;
}

/** 分割按钮自己订阅播放头：可用状态实时刷新，又不让整个检查器跟着每帧重画。 */
function SplitButton({ clip }: { clip: Clip }) {
  const play = usePlay();
  const inside = play.ticks > clip.position_ticks && play.ticks < clip.position_ticks + clip.duration_ticks;
  return (
    <button
      className="btn"
      title="在播放头处切成两段（X）"
      disabled={!inside}
      onClick={() => splitClip(clip.id, playhead.value)}
    >
      <Icon name="razor" /> 分割
    </button>
  );
}

function TransitionFields({ clip }: { clip: Clip }) {
  const app = useApp(); const project = editableProject(app, true) ?? app.project;
  const [kind, setKind] = useState<TransitionKind>(clip.transition_in?.kind ?? "dissolve");
  const [duration, setDuration] = useState((clip.transition_in?.duration_ticks ?? TIMEBASE / 2) / TIMEBASE);
  useEffect(() => {
    setKind(clip.transition_in?.kind ?? "dissolve");
    setDuration((clip.transition_in?.duration_ticks ?? TIMEBASE / 2) / TIMEBASE);
  }, [clip.transition_in?.kind, clip.transition_in?.duration_ticks]);
  if (!project) return null;
  const track = project.tracks.find((t) => t.id === clip.track_id);
  if (track?.kind !== "video") return null;
  const previous = Object.values(project.clips).filter((c) => c.track_id === clip.track_id && c.position_ticks < clip.position_ticks).sort((a, b) => b.position_ticks - a.position_ticks)[0];
  if (!previous || (!clip.transition_in && previous.position_ticks + previous.duration_ticks !== clip.position_ticks)) return null;
  const q = Math.round(TIMEBASE * project.settings.frame_rate.denominator / project.settings.frame_rate.numerator);
  const max = (Math.min(previous.duration_ticks, clip.duration_ticks) - q) / TIMEBASE;
  const locked = Boolean(track.locked || app.busy || !editableProject(app));
  return <section className="insp-section"><div className="row-title"><span className="panel-label">入场转场</span><span className="tag">{clip.transition_in ? "已应用" : "首尾衔接"}</span></div>
    <div className="field"><label htmlFor={`transition-kind-${clip.id}`}>方式</label><select id={`transition-kind-${clip.id}`} className="input" value={kind} disabled={locked} onChange={(e) => setKind(e.target.value as typeof kind)}>{transitionChoices(app.caps).map((choice) => (
                      <option key={choice.id} value={choice.id}>
                        {choice.label}
                      </option>
                    ))}</select></div>
    <NumberField label="转场时长" hint="两个镜头重叠的时间，需短于每个镜头" value={duration} quantum={q} min={q / TIMEBASE} max={max} disabled={locked || max <= 0} onCommit={setDuration} />
    <div className="row"><button className="btn primary" disabled={locked || max <= 0 || duration <= 0 || duration > max} onClick={() => setTransition(clip.id, previous.id, kind, duration)}>{clip.transition_in ? "更新转场" : "添加转场"}</button>{clip.transition_in ? <button className="btn" disabled={locked} onClick={() => removeTransition(clip.id)}>移除</button> : null}</div>
    <p className="hint">与前一镜头重叠，本轨后续片段向前衔接；其他轨道保持位置。移除转场后恢复首尾衔接。</p>
  </section>;
}

function NumberField({
  label,
  hint,
  value,
  quantum,
  min,
  max,
  disabled,
  onCommit,
}: {
  label: string;
  hint: string;
  value: number;
  quantum: number;
  min?: number;
  max?: number;
  disabled?: boolean;
  onCommit: (secondsValue: number) => void;
}) {
  const inputId = useId();
  const edit = useEdit();
  const [text, setText] = useState(value.toFixed(6));
  const escaped = useRef(false);
  useEffect(() => setText(value.toFixed(6)), [value]);
  const commit = () => {
    if (escaped.current) { escaped.current = false; setText(value.toFixed(6)); return; }
    if (text === value.toFixed(6)) return;
    const parsed = Number(text);
    if (!text.trim() || !Number.isFinite(parsed)) {
      setText(value.toFixed(6));
      return;
    }
    let next = Math.max(min ?? 0, parsed);
    if (max !== undefined) next = Math.min(max, next);
    const aligned = align(next * TIMEBASE, quantum, 0) / TIMEBASE;
    setText(aligned.toFixed(6));
    if (Math.abs(aligned - value) * TIMEBASE >= .5) onCommit(aligned);
  };
  return (
    <div className="field">
      <label htmlFor={inputId} title={hint}>{label}</label>
      <div className="val">
        <input
          className="num mono"
          id={inputId}
          value={text}
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") (event.target as HTMLInputElement).blur();
            if (event.key === "Escape") { escaped.current = true; event.currentTarget.blur(); }
          }}
        />
        <span className="sec mono">
          {edit.showTicks ? `${Math.round(Number(text || "0") * TIMEBASE).toLocaleString("en-US")} tick` : "秒"}
        </span>
      </div>
    </div>
  );
}

/** 界面上写的那个 -7 dBTP 就是真正提交的那个值：标签与请求共用这一个常量。 */
const MASTER_CEILING_DBTP = -7;

function ProjectSettings() {
  const app = useApp();
  const project = app.project;
  const [notes, setNotes] = useState(project?.notes ?? "");
  const [limiter, setLimiter] = useState(project?.settings.master_limiter ?? false);
  useEffect(() => setNotes(project?.notes ?? ""), [project?.notes, project?.id]);
  if (!project) return null;
  const fps = project.settings.frame_rate.numerator / project.settings.frame_rate.denominator;
  const preset = PROJECT_PRESETS.find(
    (item) => item.width === project.settings.width && item.height === project.settings.height && item.fps[0] === project.settings.frame_rate.numerator
  );
  return (
    <>
      <div className="ps-title">
        <b className="ellipsis" title={project.id}>
          {project.name}
        </b>
        <span className="tag accent mono" title="当前版本：每次写入 +1，历史只进不退">
          r{project.revision}
        </span>
      </div>
      <div className="ps-meta">
        <span>{preset ? preset.label : `${project.settings.width}×${project.settings.height} · ${fps} fps`}</span>
        <span className="dim">
          {Object.keys(project.clips).length} 段 · {project.tracks.length} 轨 · {humanDuration(timelineEnd(project))}
        </span>
      </div>
      <div className="ps-master">
        <span>母带音量 <b className="mono">{(project.settings.master_gain ?? 1).toFixed(3)}</b></span>
        <label className="ps-limiter" title="打开后真峰值由母带限制器守住（FFmpeg alimiter，attack 5 ms / release 80 ms，关掉自动电平），母带增益就不再被峰值上限压住">
          <input
            type="checkbox"
            checked={limiter}
            disabled={Boolean(app.busy)}
            onChange={(event) => setLimiter(event.target.checked)}
          />
          限制器 {MASTER_CEILING_DBTP} dBTP
        </label>
        <button
          className="btn tiny"
          disabled={!Object.keys(project.clips).length}
          title="让引擎先用一次 64×36 的探测渲染量出整片响度（含重叠、淡入淡出、闪避与当前母带音量），再写一个母带增益把它对齐到 -14 LUFS，并在勾选时打开母带限制器"
          onClick={() => void alignMasterLoudness(-14, limiter, MASTER_CEILING_DBTP)}
        >
          整片对齐 -14 LUFS
        </button>
      </div>
      <textarea
        className="input ps-notes"
        rows={2}
        placeholder="备注：写给同事和 Agent 看的说明，例如「旁白第 12 秒进」"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        onBlur={() => {
          if (notes !== project.notes) void updateProjectMeta({ notes });
        }}
      />
    </>
  );
}

function BatchPanel() {
  const app = useApp();
  const edit = useEdit();
  const empty = !app.batch.length;
  return (
    <section className="insp-section">
      <div className="row-title">
        <span className="panel-label">提交方式</span>
        <span className="spacer" />
        <div className="seg mini">
          <button type="button" className={app.mode === "instant" ? "active" : ""} onClick={() => setMode("instant")} title="每个动作立刻写入，最省心">
            即时
          </button>
          <button type="button" className={app.mode === "batch" ? "active" : ""} onClick={() => setMode("batch")} title="动作先攒成一批，可整体预演与提交——和 Agent 的用法一致">
            批次
          </button>
        </div>
      </div>

      {empty ? (
        <p className="hint">
          {app.mode === "batch"
            ? "剪辑动作会先攒在这里，时间线上以虚线「提案」显示，预演通过再提交。"
            : "每个动作会立刻写入一条命令；想先看效果再落库，切到「批次」。"}
        </p>
      ) : (
        <>
          <div className="cmd-list">
            {app.batch.map((command, index) => (
              <div key={`${index}-${JSON.stringify(command)}`} className="cmd-chip">
                <span className="op">{labelOf(command)}</span>
                <span className="arg mono">{summarize(command)}</span>
                <button type="button" className="rm" title="从批次里去掉这条" onClick={() => removeBatchItem(index)}>
                  ✕
                </button>
              </div>
            ))}
          </div>
          {edit.showTicks ? (
            <pre className="json-box mono">{`POST /edits  request_id: ${newBatchId(app.batch.length)}  expected_revision: ${app.project?.revision ?? 0}`}</pre>
          ) : null}
          {app.dryRunError ? (
            <div className="inline-error">
              <Icon name="warning" size={13} /> {app.dryRunError}
            </div>
          ) : app.candidate ? (
            <div className="inline-ok">
              <Icon name="check" size={13} /> 预演通过，候选 r{app.candidate.revision}，还没写入
            </div>
          ) : null}
          <div className="batch-actions">
            <button className="btn" onClick={clearBatch} title="丢弃批次，不动时间线">
              放弃
            </button>
            <button className="btn" disabled={app.dryRunBusy} onClick={() => void runDryRun()} title="服务端真跑一遍校验，不写库">
              预演
            </button>
            <button className="btn primary" disabled={Boolean(app.busy)} onClick={() => void commitBatch()} title="一次性原子提交整批命令">
              提交 {app.batch.length} 条
            </button>
          </div>
        </>
      )}
    </section>
  );
}

const OPS: Record<string, string> = {
  "clips.add": "粘贴片段组",
  "clips.move": "成组移动",
  "clips.remove": "删除片段组",
  "clips.split": "成组分割",
  "clips.group": "持久组合",
  "clips.link": "音画链接",
  "clip.trim_linked": "联动修剪",
  "transition.set": "镜头转场",
  "transition.remove": "移除转场",
  "clip.effects": "片段属性",
  "clip.mask": "调整遮罩",
  "clip.mask_track": "跟踪遮罩主体",
  "clip.speed": "片段变速",
  "clip.color": "画面色彩",
  "clip.text": "文字内容",
  "clip.fade": "淡入淡出",
  "captions.import": "导入字幕",
  "clip.ripple_remove": "涟漪删除",
  "keyframe.set": "设置关键帧",
  "keyframe.remove": "删除关键帧",
  "keyframe.move": "移动关键帧",
  "track.add": "新建轨道",
  "track.remove": "删除轨道",
  "track.update": "改轨道",
  "asset.import": "登记素材",
  "asset.register": "登记素材",
  "asset.remove": "移除素材",
  "clip.add": "加片段",
  "clip.insert": "插入素材",
  "clip.overwrite": "覆盖素材",
  "clip.move": "移动片段",
  "clip.trim": "改长短",
  "clip.split": "分割",
  "clip.remove": "删片段",
};

function labelOf(command: Record<string, unknown>): string {
  if (command.op === "sequence.nest") return "预合成";
  if (command.op === "sequence.update") return "合成设置";
  if (command.op === "clip.patch") return command.effects ? "片段属性" : command.color ? "画面色彩" : "文字内容";
  return OPS[String(command.op)] ?? String(command.op);
}

function summarize(command: Record<string, unknown>): string {
  if (command.op === "clip.patch") {
    const labels: Record<string,string> = { exposure: "曝光", contrast: "对比度", saturation: "饱和度", grade: "调色节点", body: "正文", font_size: "字号", color: "颜色", align: "位置", box: "垫条" };
    return Object.keys((command.effects ?? command.color ?? command.text) as object).map((key) => EFFECT_FIELDS.find((f) => f.property === key)?.label ?? labels[key] ?? key).join("、");
  }
  const clip = command.clip as { id?: string; track_id?: string; position_ticks?: number; duration_ticks?: number } | undefined;
  if (command.op === "track.add") return (command.track as { name: string }).name;
  if (command.op === "clips.add") return `${(command.clips as unknown[]).length} 个片段`;
  if (String(command.op).startsWith("clips.")) return `${(command.clip_ids as string[]).length} 个片段${command.op === "clips.move" ? ` · ${(Number(command.delta_ticks) / TIMEBASE).toFixed(2)}s` : command.op === "clips.remove" && command.ripple ? " · 涟漪删除" : ""}`;
  if (command.op === "asset.import" || command.op === "asset.register") return String(command.label ?? command.asset_id);
  if (["clip.add", "clip.insert", "clip.overwrite"].includes(String(command.op))) return `${clip?.id} → ${(command.clip as { track_id: string }).track_id} @${(((clip?.position_ticks ?? 0) as number) / TIMEBASE).toFixed(2)}s`;
  if (command.op === "clip.move") return `→ ${String(command.track_id)} @${(Number(command.position_ticks) / TIMEBASE).toFixed(2)}s`;
  if (command.op === "clip.trim") return `${(Number(command.duration_ticks) / TIMEBASE).toFixed(2)}s`;
  if (command.op === "clip.split") return `@${(Number(command.at_ticks) / TIMEBASE).toFixed(2)}s`;
  return String(command.clip_id ?? command.track_id ?? command.asset_id ?? "");
}


