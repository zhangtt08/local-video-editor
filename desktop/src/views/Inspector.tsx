import { manifestUrl } from "../manifestFetch";
import type { Keyframe, MaskBoxKey, MaskShapeKeyframe, SpatialProperty } from "../engine";
import { useEffect, useId, useRef, useState } from "react";

import {DEFAULT_COLOR, DEFAULT_EFFECTS, DEFAULT_MASK, DEFAULT_PATH, transitionChoices, type AnimatedEffect, type Capabilities, type Clip, type LinkStatus, type SampledValues, type ShapeMask, type TransitionKind, BLEND_MODES} from "../engine";

import { Icon, Modal } from "../ui";
import { GradeFields } from "./GradeFields";
import { SpeedFields } from "./SpeedFields";
import { blurMaxPercent, boxKeyForPlayhead, canAnimateMask, EFFECT_FIELDS, FIELD_LABEL, fadeAdoptHint, fadeBlocker, fadeProperties, fadeShape, fadeShapeChoices, fadeWindows, fitSpeedPercent, INTERPOLATIONS, maskAnimFields, rememberTrackingDefaults, sharpenLimits, stabilizeBlocked, trackGroup, trackingKnobs, trackWindow, type FadeProperty, type FadeShape, type FadeSide } from "../effects";
import { frameTicks, TIMEBASE, align, humanDuration, offsetWords, seconds, timecode, ticks } from "../time";
import {
  DISPLAY_PRIMARIES,
  foldChoices,
  foldDefault,
  foldProvenance,
  foldWords,
  workingChoices,
  workingProvenance,
  workingWords,
} from "../workingSpace";
import { setFoldTransfer, setWorkingPrimaries } from "../store";
import { linkOffsetSentence } from "../linkOffset";
import { TEXT_PRESETS } from "../textStyle";
import { MOTION_PRESETS, motionCommands, motionWords, type MotionPresetId, type MotionSide } from "../motionPresets";
import {
  adoptFade,
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
  setFade,
  setFadeShape,
  slipClip,
  slideClip,
  setTransition,
  removeTransition,
  setKeyframe,
  setGraphOpen,
  removeKeyframe,
  recordMaskShape,
  removeMaskShape,
  clearMaskShapes,
  appInfo,
  copySelection,
  duplicateSelection,
  removeSelection,
  groupSelection,
  linkSelection,
  reconcileLink,
  prefs,
  setClipMask,
  setClipMaskStack,
  editAtRevision,
  setMaskEditing,
  updateTrack,
  editableProject,
  nestSelection,
  openSequence,
  updateSequence,
  reframeClip, stabilizeClip, trackMasks,
  cutSilence,
  autoCaptions,
  adoptTrackFades,
  normaliseLoudness,
  alignMasterLoudness,
  keymap,
} from "../store";
import { PROJECT_PRESETS } from "../presets";
import { bridge } from "../bridge";
import { toast } from "../store";
import { chordWords } from "../keymap";

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
      {nestName !== null ? <Modal title="预合成选中片段" sub="内部图层、关键帧和声音继续保留，可进入合成编辑。" onClose={() => setNestName(null)} footer={<><button className="btn" onClick={() => setNestName(null)}>取消</button><button className="btn primary" disabled={!nestName.trim() || Boolean(app.busy)} onClick={() => { nestSelection(nestName); setNestName(null); }}>创建预合成</button></>}><label className="panel-label" htmlFor="nest-name">合成名称</label><input className="input" id="nest-name" autoFocus maxLength={256} value={nestName} onChange={(e) => setNestName(e.target.value)} /><p className="hint">合成用工程画幅与帧率，透明区域保留；声音一起收进合成。</p></Modal> : null}
      {sequence ? <section className="insp-section"><span className="panel-label">当前合成</span><fieldset className="effects-fields" disabled={Boolean(app.busy || !readyProject)}><input className="input" key={sequence.id + sequence.name} aria-label="合成名称" defaultValue={sequence.name} maxLength={256} onBlur={(e) => { const name = e.target.value.trim(); if (name && name !== sequence.name) updateSequence({ name }); }} /><NumberField label="合成时长" hint="缩短时不能截断内部片段或已使用的源区间" value={seconds(sequence.duration_ticks)} quantum={project!.settings.timebase * project!.settings.frame_rate.denominator / project!.settings.frame_rate.numerator} min={project!.settings.frame_rate.denominator / project!.settings.frame_rate.numerator} onCommit={(v) => updateSequence({ duration_ticks: ticks(v) })} /></fieldset></section> : null}
      {app.selectedClips.length ? <section className="insp-section"><button className="btn" disabled={Boolean(app.busy || !readyProject)} onClick={() => setNestName(`合成 ${Object.keys(project?.sequences ?? {}).length + 1}`)}>预合成选中片段</button>{compound ? <button className="btn primary" disabled={Boolean(app.busy || app.batch.length)} onClick={() => openSequence(compound)}>进入合成</button> : null}</section> : null}
      {project ? <details className="insp-section" open={!clip && !multiple}><summary className="panel-label">工程设置</summary><ProjectSettings /></details> : null}
      {app.selectedClips.length ? <AssociationFields /> : null}

      {multiple ? <section className="insp-section"><div className="row-title"><span className="panel-label">成组剪辑</span><span className="tag accent">{app.selectedClips.length} 个片段</span></div>
        <p className="hint">拖动任一选中片段移动整组，保留间隔与相对轨道。Ctrl/Shift 点选增减，空白处拖动框选。</p>
        <div className="batch-actions"><button className="btn" onClick={copySelection}>复制</button><button className="btn" onClick={duplicateSelection}>追加副本</button><button className="btn" onClick={() => removeSelection()}>删除</button></div>
        <button className="btn" onClick={() => removeSelection(true)}>涟漪删除整组</button>
        <p className="hint">涟漪删除只关掉这一段独占的时间；别人用的重叠区间保留。</p>
      </section> : null}

      {multiple ? <GroupTrackFields /> : null}
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
    // 1.233：适配时长的目标秒数是这一格自己的草稿（与工程状态无关），说完那句回执就留着给人看。
    const [fitSeconds, setFitSeconds] = useState("5");
    const [fitSaid, setFitSaid] = useState("");
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
        {asset?.kind !== "image" && asset?.kind !== "text" ? <div className="effect-row"><label htmlFor="clip-fit">适配到</label>
          <input id="clip-fit" className="input mono" type="number" min={0.1} step={0.1} value={fitSeconds} disabled={track?.locked} onChange={(event) => setFitSeconds(event.target.value)} />
          <span className="dim">秒</span>
          <button type="button" className="btn tiny" disabled={track?.locked} title="按目标时长反算播放速度：这段消耗的源不变，放不进 25%–400% 时会说明它能放成几秒" onClick={() => {
            const fit = fitSpeedPercent(clip, Number(fitSeconds), frameTicks(project.settings.frame_rate));
            setFitSaid(fit.words);
            if (fit.percent) setClipSpeed(clip.id, fit.percent / 100);
          }}>适配</button>
        </div> : null}
        {fitSaid ? <p className="hint" role="status">{fitSaid}</p> : null}
        {asset?.kind !== "image" && asset?.kind !== "text" ? <p className="hint">保留音高，变速后自动移动本轨后续片段；动画仍按时间线时间播放。</p> : null}
        <div className="insp-actions">
          <SplitButton clip={clip} />
          <button className="btn" title={`复制一段接到本轨末尾（${chordWords(keymap().duplicate)}）`} onClick={() => duplicateClip(clip.id)}>
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
            title={`删掉这段，后面的片段自动左移补上空隙（${chordWords(keymap()["ripple-delete"])}）`}
            onClick={() => removeClipRipple(clip.id)}
          >
            <Icon name="trash" /> 删除并补齐
          </button>
          <button className="btn danger-text" title={`只删这一段，留下空隙（${chordWords(keymap()["delete-selection"])}）`} onClick={() => removeClip(clip.id)}>
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
    void fetch(manifestUrl(appInfo.baseUrl(), project.id, project.revision, app.sequenceId, app.selectedClips), { headers: { Authorization: `Bearer ${appInfo.token()}` }, signal: controller.signal })
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
    <p className="hint">链接联动移动、分割与修剪；只修一边就是 J/L cut，下面的同步状态说差多久。</p>
    {linkIds.map((id) => { const link = current?.[id!]; return <div key={id} className={`link-status${link && !link.synchronized ? " out-of-sync" : ""}`} role="status">{!link ? current ? "同步状态不可用，请重新打开工程。" : "正在检查同步…" : link.synchronized ? `音画同步 · ${link.clip_ids.length} 段` : <>{linkOffsetSentence(link, (clipId) => { const member = project.clips[clipId]; const asset = member ? project.assets[member.asset_id] : undefined; return `${asset?.kind === "audio" ? "声音" : "画面"} ${asset?.label || clipId}`; }, (value) => offsetWords(value, project.settings.frame_rate))}<button className="btn tiny" title="把这一对的其他成员拉回基准片段的窗口，各自保留原来的源入点差值。" onClick={() => reconcileLink(id!)}>拉回同步</button></>}</div>; })}
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
  const [slideFrames, setSlideFrames] = useState(1);
  const effects = clip.effects ?? DEFAULT_EFFECTS;
  const at = Math.round(Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)));
  const offset = clip.animation_offset_ticks ?? 0;
  const project = editableProject(app);
  const asset = (project ?? app.project)?.assets[clip.asset_id];
  const locked = Boolean(app.busy || !project || project.tracks.find((t) => t.id === clip.track_id)?.locked);
  const slidingBlocked = Boolean(clip.speed_curve) || Boolean(clip.link_id);
  const frames = (clip.keyframes ?? []).filter((k) => k.at_ticks >= offset && k.at_ticks <= offset + clip.duration_ticks);
  // 柔焦的 ◇ 从 1.98 起有了：引擎把曲线编译成一格一步的柔焦窗，两端共用那一份窗表；
  // 按钮亮不亮仍按 caps.features.blur_keyframes，界面不凭记忆决定哪颗旋钮能做动画。
  // 上限完全由引擎下发的两个数决定（见 effects.ts 的 blurMaxPercent），界面不自己另写一套。
  const blurMax = blurMaxPercent(app.caps, project?.settings.height ?? 0);
  // 一颗效果旋钮（六个标量 + 柔焦 + 清晰的两颗）只有一条写法：这条属性已经有曲线，就把这一时刻的点
  // 改掉（没有点就补一个），只有完全没曲线时才改静态字段——引擎一旦看到一个点就整体按曲线取值，
  // 这时改静态字段画面根本不会动，界面不能给一个按了没反应的框。
  const knobFrame = (property: AnimatedEffect | SpatialProperty) =>
    frames.find((k) => k.property === property && k.at_ticks === at + offset);
  const commitKnob = (property: AnimatedEffect | SpatialProperty, value: number, statics: () => void) =>
    (clip.keyframes ?? []).some((k) => k.property === property)
      ? setKeyframe(clip.id, { ...knobFrame(property), property, at_ticks: at, value, interpolation: knobFrame(property)?.interpolation ?? interpolation })
      : statics();
  // ◇ 也只有一处写法：认哪一份下发开关（`null` 表示这条本来就能打）、写哪条属性、新点从哪个数起笔，
  // 都由调用方交进来，所以六颗标量与三颗空间旋钮的那只手是同一只。
  const knobButton = (property: AnimatedEffect | SpatialProperty, gate: string | null, label: string, from: number, hint: string) =>
    gate === null || app.caps?.features?.[gate] ? <button type="button" className={`keyframe-btn${knobFrame(property) ? " active" : ""}`}
      aria-label={`${knobFrame(property) ? "删除" : "添加"}${label}关键帧`}
      disabled={outside || play.playing || !sampleReady}
      title={`${knobFrame(property) ? "删除" : "添加"}当前位置的${label}关键帧${hint ? `：${hint}` : ""}`}
      onClick={() => knobFrame(property) ? removeKeyframe(clip.id, property, at) : setKeyframe(clip.id, { property, at_ticks: at, value: from, interpolation })}>◇</button> : null;
  // 降噪只有一条真实的路：导出。浏览器预览没有等价的 FFT 降噪，所以这一行必须自己说明白，
  // 上限由引擎下发（capabilities.limits.denoise_db），界面不另写一套数。
  const carriesAudio = asset?.kind === "audio"
    || (asset?.kind === "video" && asset.verified?.has_audio === true && clip.embedded_audio !== false);
  const denoiseCeiling = app.caps?.limits.denoise_db ?? 0;
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
        const frame = knobFrame(f.property);
        return <div className="effect-row" key={f.property}>
          <label htmlFor={`fx-${f.property}`}>{f.label}</label>
          <EffectInput id={`fx-${f.property}`} value={(frame?.value ?? currentValues[f.property]) * f.factor} min={f.min} max={f.max} step={f.step}
            onCommit={(value) => commitKnob(f.property, value / f.factor, () => setClipEffects(clip.id, { [f.property]: value / f.factor }))} />
          <span className="dim">{f.unit}</span>
          {knobButton(f.property, null, f.label, currentValues[f.property], "")}
        </div>;
      })}
      {blurMax > 0 && asset?.kind !== "audio" ? (() => {
        const shown = (knobFrame("blur")?.value ?? effects.blur ?? 0) * 100;
        return <div className="effect-row">
          <label htmlFor="fx-blur">{FIELD_LABEL.blur}</label>
          <EffectInput id="fx-blur" value={shown} min={0} max={blurMax} step={0.5} onCommit={(value) => commitKnob("blur", value / 100, () => setClipEffects(clip.id, { blur: value / 100 }))} />
          <span className="dim">% 高 · ≈{((shown / 100) * (project?.settings.height ?? 0)).toFixed(1)} px</span>
          {knobButton("blur", "blur_keyframes", FIELD_LABEL.blur, effects.blur ?? 0, "导出把这条曲线编译成一格一步的柔焦窗，预览走的是同一份窗表")}
        </div>;
      })() : null}
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
          <label htmlFor="fx-sharpen">{FIELD_LABEL.sharpen}</label>
          <EffectInput id="fx-sharpen" value={(knobFrame("sharpen")?.value ?? effects.sharpen ?? 0) * 100} min={0} max={sharpen.amount * 100} step={5} onCommit={(value) => commitKnob("sharpen", value / 100, () => setClipEffects(clip.id, { sharpen: value / 100 }))} />
          <span className="dim">%</span>
          {knobButton("sharpen", "sharpen_keyframes", FIELD_LABEL.sharpen, effects.sharpen ?? 0, "导出一格一步地锐化，预览走的是同一份窗表；这一颗与下面的半径共用那张窗表，所以它们总在同一些帧上换档")}
        </div>
        <div className="effect-row">
          <label htmlFor="fx-sharpen-radius">{FIELD_LABEL.sharpen_radius}</label>
          <EffectInput id="fx-sharpen-radius" value={(knobFrame("sharpen_radius")?.value ?? effects.sharpen_radius ?? 0) * 100} min={0} max={sharpen.radiusPercent} step={0.25} onCommit={(value) => commitKnob("sharpen_radius", value / 100, () => setClipEffects(clip.id, { sharpen_radius: value / 100 }))} />
          <span className="dim">% 高 · ≈{((knobFrame("sharpen_radius")?.value ?? effects.sharpen_radius ?? 0) * (project?.settings.height ?? 0)).toFixed(1)} px</span>
          {knobButton("sharpen_radius", "sharpen_keyframes", FIELD_LABEL.sharpen_radius, effects.sharpen_radius ?? 0, "半径就是那一次高斯采样的宽度，与强度同进同一张窗表")}
        </div>
      </> : null}
      {carriesAudio && denoiseCeiling > 0 ? <div className="effect-row">
        <label htmlFor="fx-denoise">降噪</label>
        <EffectInput id="fx-denoise" value={effects.denoise ?? 0} min={0} max={denoiseCeiling} step={1} onCommit={(value) => setClipEffects(clip.id, { denoise: value })} />
        <span className="dim">dB · 只在导出里生效，浏览器预览不降噪</span>
      </div> : null}
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
        <select aria-label={`${FIELD_LABEL[k.property] ?? k.property}关键帧插值`} disabled={locked} value={k.interpolation} onChange={(e) => setKeyframe(clip.id, { ...k, at_ticks: k.at_ticks - offset, interpolation: e.target.value as Keyframe["interpolation"], bezier: e.target.value === "bezier" ? k.bezier : null })}><option value="linear">线性</option><option value="ease">缓入缓出</option><option value="hold">保持</option><option value="bezier">贝塞尔</option></select>
        <button aria-label="删除关键帧" disabled={locked} onClick={() => removeKeyframe(clip.id, k.property, k.at_ticks - offset)}>×</button>
      </div>)}
    </div>
    <MotionControls clip={clip} locked={locked} />
    <details className="slide-controls"><summary className="panel-label">源画面划动与滑移</summary><fieldset disabled={locked} className="effects-fields">
      <div className="effect-row"><label htmlFor="slide-frames">步长</label><input id="slide-frames" className="input" type="number" min={1} max={Math.max(1, Math.floor(clip.duration_ticks / (project ? frameTicks(project.settings.frame_rate) : 1)))} step={1} value={slideFrames} onChange={(e) => setSlideFrames(Math.max(1, Math.round(Number(e.target.value) || 1)))} /><span>帧</span></div>
      <div className="insp-actions">
        <button className="btn tiny" disabled={slidingBlocked} title="只换这段素材播到哪一格：片段位置与时长都不动" onClick={() => slipClip(clip.id, -slideFrames)}>划动 ←</button>
        <button className="btn tiny" disabled={slidingBlocked} title="同上，往后取素材" onClick={() => slipClip(clip.id, slideFrames)}>划动 →</button>
        <button className="btn tiny" disabled={slidingBlocked} title="整段左移：左边相邻段让出这些帧、右边相邻段收回同样多，这条轨总长不变" onClick={() => slideClip(clip.id, -slideFrames)}>滑移 ←</button>
        <button className="btn tiny" disabled={slidingBlocked} title="整段右移：右边让出、左边收回，总长不变" onClick={() => slideClip(clip.id, slideFrames)}>滑移 →</button>
      </div>
      <p className="hint">{slidingBlocked ? "带变速曲线或已链接声音的片段不能划动/滑移：请直接修剪，或先解除链接。" : "划动改素材起点；滑移改这段在时间线上的位置，两侧各自补/让同样的帧数。"}</p>
    </fieldset></details>
    <FadeControls clip={clip} locked={locked} properties={fadeProperties(clip, asset)} />
  </section>;
}

/** 1.231：入场 / 出场动画预设。没有新的引擎语义——每一档只算「头/尾该写哪几枚针」，
 *  交出去的仍是普通 `keyframe.set`，一批一个版本、撤销一次回一步。终格永远是片段自己的静态值，
 *  所以「已经缩到 0.8」的片段套放大，是从 0.8×0.86 起、仍收在 0.8。 */
function MotionControls({ clip, locked }: { clip: Clip; locked: boolean }) {
  const app = useApp();
  const project = editableProject(app);
  const [seconds, setSeconds] = useState(0.5);
  const [said, setSaid] = useState("");
  if (!project) return null;
  const frame = frameTicks(project.settings.frame_rate);
  const shorter = clip.duration_ticks < 2 * frame;
  const apply = (side: MotionSide, id: MotionPresetId | "") => {
    if (!id) return;
    const preset = MOTION_PRESETS.find((item) => item.id === id);
    if (!preset) return;
    const commands = motionCommands(clip, side, preset.id, seconds, frame);
    setSaid(motionWords(commands, clip, side, seconds));
    if (commands.length) {
      editAtRevision(commands, project.id, project.revision, `${side === "in" ? "入场" : "出场"}动画 · ${preset.label}`);
    }
  };
  return <details className="motion-controls"><summary className="panel-label">入场 / 出场动画</summary>
    <fieldset className="effects-fields" disabled={locked || shorter}>
      <div className="effect-row"><label htmlFor="motion-length">时长</label>
        <select id="motion-length" className="input" value={seconds} onChange={(event) => setSeconds(Number(event.target.value))}>
          {[0.3, 0.5, 0.8, 1.2].map((value) => <option key={value} value={value}>{value.toFixed(1)} 秒</option>)}
        </select>
      </div>
      {(["in", "out"] as const).map((side) => <div className="effect-row" key={side}>
        <label htmlFor={`motion-${side}`}>{side === "in" ? "入场" : "出场"}</label>
        <select id={`motion-${side}`} className="input" value="" onChange={(event) => apply(side, event.target.value as MotionPresetId | "")} aria-label={`${side === "in" ? "入场" : "出场"}动画预设`}>
          <option value="">{shorter ? "片段太短" : "选一个预设…"}</option>
          {MOTION_PRESETS.map((preset) => <option key={preset.id} value={preset.id} title={preset.hint}>{preset.label}</option>)}
        </select>
      </div>)}
      {said ? <p className="hint" role="status">{said}</p> : null}
      <p className="hint" title="预设写的是这条曲线开头或结尾的两枚针，终格永远是片段自己的静态值；同一格已有的针会被顶替，别的针一根不动">预设只写头/尾两枚针（缓入缓出），一批一个版本；要撤掉，在下面的关键帧列表里删，或按一次撤销。</p>
    </fieldset>
  </details>;
}

/** 淡入淡出改的是片段两条边上的窗口（`Clip.fade`）：一头一次提交只动自己那一头，所以淡入与淡出能
 *  同时存在，音量那一行也不会再把自动闪避写下的关键帧顶掉。数字读自工程状态，不是界面自己记的。
 *  能淡哪几头由 `fadeProperties` 说，时间线的淡角柄读的是同一个判断。 */
function FadeControls({ clip, locked, properties }: { clip: Clip; locked: boolean; properties: FadeProperty[] }) {
  const app = useApp();
  const rows = properties.map((property) => ({ property, label: property === "opacity" ? "画面透明度" : "音量" }));
  return <details className="fade-controls"><summary className="panel-label">淡入淡出</summary><fieldset disabled={locked} className="effects-fields">
    {!rows.length ? <p className="hint">这段素材既不显示画面也没有声音，淡入淡出没处可加。</p> : rows.map(({ property, label }) => <div key={property} className="fade-rows">
      <p className="panel-label">{label}</p>
      {(["in", "out"] as const).map((side) => <FadeRow key={side} clip={clip} property={property} side={side} />)}
      {app.caps?.features?.clip_fade_adopt && fadeAdoptHint(clip, property) ? <button className="btn tiny" disabled={locked} title="1.90 之前淡是写成关键帧的：那条淡在这两个数字里看不见，也不会跟着修剪与分割走。点一下把它搬成边窗口——引擎认得它原来那条从 0 缓到静止值的斜坡，搬完画面一个像素都不变；搬不动会点名说为什么（夹了别的点、起点不是 0、已经是窗口）。" onClick={() => adoptFade(clip.id, property)}>搬成边窗口</button> : null}
    </div>)}
    {app.caps?.features?.clip_fade_adopt_track && rows.length ? <button className="btn tiny subtle" disabled={locked || Boolean(app.busy)} title="把这一整条轨上 1.90 之前写成关键帧的淡一次搬成边窗口：先向引擎要一份只读规划，排出的就是普通 clip.fade_adopt 命令，一整轨只写一个版本。搬不动的那段不会被排进来，报告里会说是哪几段、为什么。" onClick={() => adoptTrackFades(clip.track_id)}>整轨搬成边窗口</button> : null}
    <p className="hint">淡加在两条边上，跟着那条边走；切口不算一条边。</p>
  </fieldset></details>;
}

function FadeRow({ clip, property, side }: { clip: Clip; property: FadeProperty; side: FadeSide }) {
  const id = useId();
  const app = useApp();
  // 形状是「这条属性两头共用」的一个数（淡出那一段由引擎按时间反演镜像），所以两行显示同一个下拉。
  const shapes = fadeShapeChoices(app.caps);
  const committed = fadeWindows(clip)[property][side];
  const [text, setText] = useState((committed / TIMEBASE).toFixed(2));
  const [refused, setRefused] = useState("");
  useEffect(() => { setText((committed / TIMEBASE).toFixed(2)); setRefused(""); }, [committed]);
  const apply = () => {
    const value = Number(text);
    if (!text.trim() || !Number.isFinite(value) || value < 0) { setText((committed / TIMEBASE).toFixed(2)); return; }
    const wanted = ticks(value);
    const blocker = fadeBlocker(clip, property, side, wanted);
    if (blocker) { setRefused(blocker); return; }
    setRefused("");
    if (wanted !== committed) setFade(clip.id, property, side, value);
  };
  return <div className="fade-row"><label htmlFor={id}>{side === "in" ? "淡入" : "淡出"}</label>
    <input id={id} className="input mono" type="number" min={0} max={seconds(clip.duration_ticks)} step={.05} value={text} aria-label={`${property === "gain" ? "音量" : "画面透明度"}${side === "in" ? "淡入" : "淡出"}秒`}
      onChange={(e) => setText(e.target.value)} onBlur={apply}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { setText((committed / TIMEBASE).toFixed(2)); setRefused(""); e.currentTarget.blur(); } }} />
    <span>秒</span>
    {shapes.length ? <select className="input tiny" aria-label={`${property === "gain" ? "音量" : "画面透明度"}淡的形状`} value={fadeShape(clip, property)} title="淡的形状：值沿着窗口靠上静止值的方式。画面与音量各一个，同一条属性的淡入与淡出共用（淡出那一段按时间反演镜像，所以两条边摸起来一样）。列表是引擎 capabilities.fade_shapes 下发的。" onChange={(e) => setFadeShape(clip.id, property, e.target.value as FadeShape)}>{shapes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select> : null}
    {committed > 0 ? <button className="btn tiny" title="取消这一头的淡" onClick={() => setFade(clip.id, property, side, 0)}>取消</button> : null}
    {refused ? <p className="hint blocked">{refused}</p> : null}
  </div>;
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
 * there is no numeric box to edit — the centre curves come from 跟踪主体 or the curve editor.
 * 1.164/1.166：「这条盒属性今天能不能打关键帧」只在 `maskAnimFields` 那一处判（路径只搬中心，
 * 转过角度的盒今天连宽/高也一起给），这里只把那份名单折成检查器要的数字行——所以画面上不会有一颗
 * 按下去被引擎点名拒绝的 ◇。caps 必须一起递过去：1.166 装机量到的那一幕就是没递，角度一非零，
 * 宽/高那两行就凭空消失，而函数自己测是好的。 */
const maskRows = (mask: ShapeMask, caps?: Capabilities | null) => {
  if (mask.shape === "path") return [];
  const allowed = new Set(maskAnimFields(mask, caps).map((row) => row.property));
  return MASK_ROWS.filter((row) => allowed.has(row[4]));
};

/** 一组遮罩跟踪：多选里每段各按自己的长度量，段数上限与窗口都只由 `trackGroup` 那一处判断。
 *  放在「成组剪辑」旁边是有意的——一条片段只有一条遮罩路径，所以「一组」就是叠层上的几段各跟各的
 *  主体；这一节在多选时才出现，正是它该在的地方（放在单段遮罩区里会根本点不到）。 */
function GroupTrackFields() {
  const app = useApp();
  const project = editableProject(app);
  const knobs = trackingKnobs(app.caps?.limits);
  const perFrame = project ? frameTicks(project.settings.frame_rate) : 1;
  const picked = project ? Object.values(project.clips).filter((one) => (app.selectedClips ?? []).includes(one.id) && canAnimateMask(one.mask)) : [];
  const skipped = project ? (app.selectedClips ?? []).length - picked.length : 0;
  const group = trackGroup(picked, perFrame, app.caps?.limits, { reacquire: knobs.sweep, maxGapFrames: knobs.gap, scale: knobs.scale });
  if (!picked.length) {
    return <section className="insp-section"><span className="panel-label">遮罩跟踪</span>
      <p className="hint">多选里没有任何一段带着可以动的遮罩：先在某一段上画好遮罩，再回来一次跟完整组。</p></section>;
  }
  return <section className="insp-section">
    <div className="row-title"><span className="panel-label">遮罩跟踪</span><span className="tag accent">{picked.length} 段</span></div>
    <fieldset className="effects-fields" disabled={Boolean(app.busy)}>
      <div className="batch-actions"><button className="btn" disabled={Boolean(app.busy || group.blocked)} title={group.blocked ?? "每段各自从片段开头量到量得完的地方：一次分析、写进同一个版本，撤销一步整批退回；同一段画面叠几层、各盖一个主体时，它们共用同一趟读片"} onClick={() => trackMasks(group.targets)}>跟踪所选 {picked.length} 段</button></div>
      <p className="hint">三个旋钮沿用应用偏好：挡住最多猜 {knobs.gap} 帧、{knobs.sweep ? "被挡住时整幅重找" : "被挡住时按匀速猜"}、{knobs.scale ? "遮罩随远近缩放" : "遮罩不随远近缩放"}。{skipped ? ` 另有 ${skipped} 段这一批不跟。` : ""}</p>
    </fieldset>
  </section>;
}

function MaskFields({ clip }: { clip: Clip }) {
  const app = useApp();
  const play = usePlay();
  const project = editableProject(app);
  const mask = clip.mask;
  const disabled = Boolean(app.busy || !project || project.tracks.find((t) => t.id === clip.track_id)?.locked);
  const at = Math.round(Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks)));
  const frames = clip.keyframes ?? [];
  const animatable = canAnimateMask(mask);
  // 1.164：角度那一格的上下限是引擎的数；老引擎没有这一格就明说，不摆一颗点了没反应的旋钮。
  const rotationLimit = app.caps?.features.mask_rotation ? app.caps?.limits?.mask_rotation_limit : undefined;
  // 1.165：角度能打折梯关键帧，同样只在这一版引擎报了那条能力时才给 ◇。
  const rotationCurves = Boolean(app.caps?.features.mask_rotation_curves);
  const angleKey = frames.find((key) => key.property === "mask_rotation" && key.at_ticks === at + (clip.animation_offset_ticks ?? 0));
  // 遮挡期间最多猜几帧、要不要在整幅画面上重找：这两个旋钮 Agent 有，人也该有。
  const storedKnobs = trackingKnobs(app.caps?.limits);
  const gapCeiling = storedKnobs.gapCeiling;
  // 三个旋钮记在应用偏好里，换一个工程、重开一次窗口都还在（1.93）。不写进工程状态是有意的：
  // 元数据那条路每点一次就涨一个 revision 并清空撤销栈，等于拿用户的编辑历史换一个勾选。
  const [trackGap, setTrackGapState] = useState(storedKnobs.gap);
  const [trackSweep, setTrackSweepState] = useState(storedKnobs.sweep);
  const [trackScale, setTrackScaleState] = useState(storedKnobs.scale);
  const setTrackGap = (value: number) => { setTrackGapState(value); rememberTrackingDefaults({ gap: value }); };
  const setTrackSweep = (value: boolean) => { setTrackSweepState(value); rememberTrackingDefaults({ sweep: value }); };
  const setTrackScale = (value: boolean) => { setTrackScaleState(value); rememberTrackingDefaults({ scale: value }); };
  // 一次量几帧、量不完时怎么说：判断在 effects.ts 的 trackWindow 里，上下限是引擎的数。
  const perFrame = project ? frameTicks(project.settings.frame_rate) : 1;
  const runOn = trackWindow(Math.floor((clip.duration_ticks - at) / perFrame), at === 0, app.caps?.limits);
  const runAll = trackWindow(Math.floor(clip.duration_ticks / perFrame), true, app.caps?.limits);
  return <details className="insp-section mask-section"><summary className="panel-label">遮罩{mask ? ` · ${{ ellipse: "椭圆", rectangle: "矩形", path: "路径" }[mask.shape]}` : ""}</summary>
    <fieldset className="effects-fields" disabled={disabled}>
      <label className="mask-shape">形状 <select className="input" aria-label="遮罩形状" value={mask?.shape ?? "none"} onChange={(e) => { const shape = e.target.value; if (shape === "none") { setClipMask(clip.id, null); return; } const base = { ...(mask ?? DEFAULT_MASK), shape: shape as ShapeMask["shape"] }; setClipMask(clip.id, shape === "path" ? { ...base, vertices: base.vertices?.length ? base.vertices : DEFAULT_PATH.map((vertex) => ({ ...vertex, handle_out: [...vertex.handle_out] as [number, number], handle_in: [...vertex.handle_in] as [number, number] })) } : { ...base, vertices: null }); }}><option value="none">无</option><option value="ellipse">椭圆</option><option value="rectangle">矩形</option><option value="path">路径</option></select></label>
      {mask ? <>
        {mask.shape === "path" ? <p className="hint">路径顶点 {mask.vertices?.length ?? 0} 个：画面里拖顶点改形状，双击最近那条边加一个点。{app.caps?.features.path_shape_keys ? "轮廓本身也能随时间变形：先记一帧。" : "形状还不能随时间变化。"}</p> : null}
        {mask.shape === "path" && app.caps?.features.path_shape_keys ? <MaskShapeKeys clip={clip} mask={mask} disabled={disabled} at={at} /> : null}
        {(canAnimateMask(mask) ? maskRows(mask, app.caps) : []).map(([field, label, min, max, property]) => {
          const frame = frames.find((k) => k.property === property && k.at_ticks === at + (clip.animation_offset_ticks ?? 0));
          const animated = (clip.keyframes ?? []).some((k) => k.property === property);
          return <div className="effect-row" key={field}><label htmlFor={`mask-${field}`}>{label}</label><EffectInput id={`mask-${field}`} value={(frame?.value ?? mask[field]) * 100} min={min} max={max} step={1} onCommit={(value) => animated ? setKeyframe(clip.id, { property, at_ticks: at, value: value / 100, interpolation: frame?.interpolation ?? "linear" }) : setClipMask(clip.id, { ...mask, [field]: value / 100 })} /><span className="dim">%</span>
            {animatable ? <button type="button" className={`keyframe-btn${frame ? " active" : ""}`} aria-label={frame ? `删除${label}关键帧` : `添加${label}关键帧`} title={`${frame ? "删除" : "添加"}当前位置的${label}关键帧`} disabled={disabled} onClick={() => frame ? removeKeyframe(clip.id, property, at + (clip.animation_offset_ticks ?? 0)) : setKeyframe(clip.id, { property, at_ticks: at, value: mask[field], interpolation: "linear" })}>◇</button> : null}
          </div>;
        })}
        <div className="effect-row"><label htmlFor="mask-feather">向内羽化</label><EffectInput id="mask-feather" value={mask.feather * 100} min={0} max={100} step={1} onCommit={(value) => setClipMask(clip.id, { ...mask, feather: value / 100 })} /><span className="dim">%</span></div>
        {mask.shape === "path" ? null : rotationLimit === undefined ? <p className="hint">这一版引擎没有遮罩角度这一格。</p> : <div className="effect-row"><label htmlFor="mask-rotation">遮罩角度</label><EffectInput id="mask-rotation" value={angleKey?.value ?? mask.rotation ?? 0} min={-rotationLimit} max={rotationLimit} step={1} onCommit={(value) => angleKey ? setKeyframe(clip.id, { property: "mask_rotation", at_ticks: at, value, interpolation: angleKey.interpolation ?? "linear" }) : setClipMask(clip.id, { ...mask, rotation: value })} /><span className="dim">°</span>{rotationCurves && animatable ? <button type="button" className={`keyframe-btn${angleKey ? " active" : ""}`} aria-label={angleKey ? "删除遮罩角度关键帧" : "添加遮罩角度关键帧"} title={angleKey ? "删掉这一刻的遮罩角度关键帧" : "在播放头记一格遮罩角度。导出与预览走同一份按帧对齐的阶梯：引擎把曲线切成几段窗，每窗一张图、一格一步"} disabled={disabled} onClick={() => angleKey ? removeKeyframe(clip.id, "mask_rotation", at + (clip.animation_offset_ticks ?? 0)) : setKeyframe(clip.id, { property: "mask_rotation", at_ticks: at, value: mask.rotation ?? 0, interpolation: "linear" })}>◇</button> : null}</div>}
        <MaskStack clip={clip} disabled={disabled} />
        <label><input type="checkbox" checked={mask.inverted} onChange={(e) => setClipMask(clip.id, { ...mask, inverted: e.target.checked })} />反转遮罩</label>
        <div className="insp-actions"><button className={`btn tiny${app.maskEditing ? " active" : ""}`} aria-pressed={app.maskEditing} onClick={() => setMaskEditing(!app.maskEditing)}>画面中编辑</button>
          {animatable && project ? <button className="btn tiny" disabled={disabled || Boolean(runOn.blocked)} title={runOn.blocked ?? (mask.shape === "path" ? "从播放头开始逐帧分析画面，把轮廓的中心写成关键帧，一直量到片段结尾（单次上限由引擎的 capabilities 下发，量不完会在提示里说清）；路径遮罩只整体搬动，不改形状与大小。主体被挡住时按匀速补一段，同时每一帧都在整幅画面里重新找它，找回后把补的那段按真实位置校正；跟丢时会停下来说明" : "从播放头开始逐帧分析画面，把遮罩中心与大小写成关键帧，一直量到片段结尾（单次上限由引擎的 capabilities 下发，量不完会在提示里说清）；主体被挡住时按匀速补一段，同时每一帧都在整幅画面里重新找它，找回后把补的那段按真实位置校正；跟丢时会停下来说明")} onClick={() => trackMasks([{ clipId: clip.id, fromTicks: at, frames: runOn.frames, merge: true, reacquire: trackSweep, maxGapFrames: trackGap, scale: trackScale }])}>{(clip.keyframes ?? []).some((key) => key.property === "mask_x") ? "接着跟" : "跟踪主体"}</button> : null}
          {animatable && project && (clip.keyframes ?? []).some((key) => key.property === "mask_x") ? <button className="btn tiny subtle" disabled={disabled || Boolean(runAll.blocked)} title={runAll.blocked ?? "整条重跟：从片段开头重新分析，播放头之前已有的路径会被这一段的结果替换"} onClick={() => trackMasks([{ clipId: clip.id, fromTicks: 0, frames: runAll.frames, merge: false, reacquire: trackSweep, maxGapFrames: trackGap, scale: trackScale }])}>从头重跟</button> : null}
          {animatable && project ? <label className="dim" title="被挡住的那段时间最多猜多少帧；猜窗用完还没找回，路径就停在最后一次看到的地方。上限由引擎的 capabilities.limits 下发">挡住最多猜
            <input className="input tiny" type="number" min={0} max={gapCeiling} step={5} value={trackGap} aria-label="遮挡时最多猜几帧"
              onChange={(e) => setTrackGap(Math.max(0, Math.min(gapCeiling, Math.round(Number(e.target.value) || 0))))} />帧
          </label> : null}
          {animatable && project ? <label className="dim" title="开着时，主体被挡住的每一帧都在整幅画面上重新找它；关掉就不会——换个位置回来会被当成跟丢">满画面重找
            <input type="checkbox" checked={trackSweep} aria-label="遮挡时在整幅画面上重新找主体" onChange={(e) => setTrackSweep(e.target.checked)} /></label> : null}
          {animatable && project ? <label className="dim" title="开着时一个跟踪点会写中心 X/Y 加宽高四条曲线，遮罩盒随主体远近变大变小；关掉只写两条中心曲线，同样的曲线预算能多跟一倍长度。路径遮罩的形状与大小按画好的轮廓，引擎对它本来就不估尺寸">遮罩随远近缩放
            <input type="checkbox" checked={trackScale} disabled={mask.shape === "path"} aria-label="跟踪时让遮罩盒随远近缩放" onChange={(e) => setTrackScale(e.target.checked)} /></label> : null}
          {animatable && project ? <button className="btn tiny" disabled={disabled || Boolean(clip.stabilization)} title={clip.stabilization ? "这段画面带着一次稳定：重构图写的就是稳定占用的位移/缩放三条曲线，跑一遍会把稳定悄悄抹掉。先「取消稳定」，再重构图。" : "读取刚跟踪出来的遮罩路径，写入把主体保持在画面正中的平移与缩放曲线；竖屏裁切出货时主体不会跑出画面。放大上限 4 倍，跟不到时会说明"} onClick={() => void reframeClip(clip.id)}>主体跟随重构图</button> : null}
          <button className="btn tiny" onClick={() => setClipMask(clip.id, { ...DEFAULT_MASK, shape: mask.shape, vertices: mask.shape === "path" ? DEFAULT_PATH.map((vertex) => ({ ...vertex, handle_out: [...vertex.handle_out] as [number, number], handle_in: [...vertex.handle_in] as [number, number] })) : null })}>重置遮罩</button></div>
        <p className="hint">遮罩随片段变换；中心、大小与角度都能按◇打点，两端走同一份阶梯。{app.caps?.features.path_shape_keys ? "反相遮罩不打盒关键帧。" : ""}</p>
      </> : null}
    </fieldset>
  </details>;
}


/** 1.118：路径遮罩的轮廓帧。界面只列引擎记下的那几帧，改的是其中一枚的形状或插值——「两帧之间怎么过渡」
 * 由引擎算，导出与预览读同一份窗表，所以这里既不数时间也不插值。额度、名字都从 capabilities 出去。 */
/** 1.221：主遮罩之外那几块，与主遮罩取交集。
 *  1.229：每一块自己的五个数（中心、大小、角度）与羽化、反转都在这一格调——1.221 只给了一个
 *  默认矩形：Agent 写得出、人改不动，那不叫两边共用。写仍然只走 `clip.mask_stack` 一整串
 *  （那一处主人），这一格既不碰主遮罩，也不自己算合成。 */
function MaskStack({ clip, disabled }: { clip: Clip; disabled: boolean }) {
  const app = useApp();
  const play = usePlay();
  const limit = app.caps?.limits?.extra_masks ?? 0;
  const keysLimit = app.caps?.limits?.extra_mask_keys ?? 0;
  const rate = app.project?.settings.frame_rate ?? { numerator: 30, denominator: 1 };
  const frame = frameTicks(rate);
  const localTick = () => {
    const raw = play.ticks - clip.position_ticks;
    return Math.max(0, Math.min(clip.duration_ticks, Math.round(raw / frame) * frame));
  };
  // 1.238：一枚框点说的是「这一刻这块盒子的五个数」——打点就是把卡片里现在这五个数记在播放头那一帧上。
  // 1.243：这一帧**已经有**框点时不打点也不覆盖——卡片上那五个数此刻显示的就是那一枚，
  // 再拿静止值盖上去不是「打点」，是把它抹掉。界面把按钮灰掉并写明，函数这里也守一道。
  const stampKey = (index: number) => {
    const item = stack[index];
    const at = localTick();
    const keys = [...(item.keys ?? [])];
    if (keys.some((key) => key.at_ticks === at)) return;
    if (keys.length >= keysLimit) return;
    keys.push({
      at_ticks: at,
      center_x: item.center_x,
      center_y: item.center_y,
      width: item.width,
      height: item.height,
      rotation: item.rotation ?? 0,
      interpolation: "linear",
    });
    keys.sort((left, right) => left.at_ticks - right.at_ticks);
    patch(index, { keys });
  };
  const rotationLimit = app.caps?.limits?.mask_rotation_limit;
  const stack = clip.extra_masks ?? [];
  const at = localTick();
  // 1.247：Agent 写在两帧之间的框点，点开它时播放头精确落在它的 tick 上；按取整后的帧去找会落空。
  const exact = Math.max(0, Math.min(clip.duration_ticks, play.ticks - clip.position_ticks));
  const full = stack.length >= limit;
  const write = (masks: ShapeMask[]) => setClipMaskStack(clip.id, masks);
  const patch = (index: number, part: Partial<ShapeMask>) =>
    write(stack.map((item, position) => (position === index ? { ...item, ...part } : item)));
  // 1.243：停在框点那一帧时，五个数写的是这一枚框点本身（与卡片显示的是同一枚）。
  const patchKey = (index: number, atTick: number, part: Partial<MaskBoxKey>) =>
    patch(index, { keys: (stack[index].keys ?? []).map((key) => key.at_ticks === atTick ? { ...key, ...part } : key) });
  type BoxField = "center_x" | "center_y" | "width" | "height";
  const commitBox = (index: number, atKey: MaskBoxKey | undefined, field: BoxField, value: number) => {
    const next = { [field]: value } as Pick<ShapeMask, BoxField>;
    if (atKey) patchKey(index, atKey.at_ticks, next);
    else patch(index, next);
  };
  return <div className="mask-stack">
    <div className="mask-stack-head"><span>再叠的遮罩</span><span className="dim">{stack.length} / {limit} 块 · 与主遮罩取交集</span></div>
    <label className="mask-stack-follow" title="勾上之后，没打框点的块跟着主遮罩的中心曲线一起平移；主遮罩与它都没转时，大小也按同一比例缩放；主遮罩转了时，角度跟着它转。打了框点的块走自己的窗，勾这里不会删掉那些框点。羽化仍是自己的。主遮罩没有动画时，跟随的块不动。">
      <input type="checkbox" checked={clip.extra_masks_follow ?? false} disabled={disabled || stack.length === 0}
        onChange={(event) => setClipMaskStack(clip.id, stack, event.target.checked)} />跟着主遮罩平移
    </label>
    {stack.map((item, index) => {
      const atKey = boxKeyForPlayhead(item, exact, at);
      const active = atKey?.at_ticks ?? at;
      return <div className="mask-stack-row" key={`stack-${index}`}>
      <div className="mask-stack-title">
        <span className="mask-stack-n">第 {index + 1} 块</span>
        <select className="input tiny" aria-label={`第 ${index + 1} 块叠加遮罩的形状`} value={item.shape} disabled={disabled}
          onChange={(event) => patch(index, { shape: event.target.value as ShapeMask["shape"] })}>
          <option value="rectangle">矩形</option><option value="ellipse">椭圆</option>
        </select>
        <button type="button" className="btn tiny subtle" disabled={disabled} aria-label={`删掉第 ${index + 1} 块叠加遮罩`} onClick={() => write(stack.filter((_, position) => position !== index))}>删掉</button>
        {/* 1.242：这一块此刻怎么动，写在它自己那一行——勾没勾「跟着主遮罩」与有没有框点，
            是两个各自决定它走哪条路的事实，过去只在地下的合成规则里，界面上谁都没说。 */}
        <span className="mask-stack-state dim">{item.keys?.length ? `自己走 · ${item.keys.length} 枚框点` : clip.extra_masks_follow ? "跟随主遮罩" : "静止"}</span>
      </div>
      <div className="mask-stack-grid">
        {MASK_ROWS.map(([field, label, min, max]) => <label className="mask-stack-cell" key={field}>
          <span>{label}</span>
          <EffectInput id={`stack-${index}-${field}`} value={(atKey ?? item)[field] * 100} min={min} max={max} step={1}
            onCommit={(value) => commitBox(index, atKey, field, value / 100)} />
          <span className="dim">%</span>
        </label>)}
        {rotationLimit === undefined ? null : <label className="mask-stack-cell"><span>角度</span>
          <EffectInput id={`stack-${index}-rotation`} value={atKey ? atKey.rotation ?? 0 : item.rotation ?? 0} min={-rotationLimit} max={rotationLimit} step={1}
            onCommit={(value) => atKey ? patchKey(index, atKey.at_ticks, { rotation: value }) : patch(index, { rotation: value })} />
          <span className="dim">°</span>
        </label>}
        <label className="mask-stack-cell"><span>羽化</span>
          <EffectInput id={`stack-${index}-feather`} value={item.feather * 100} min={0} max={100} step={1}
            onCommit={(value) => patch(index, { feather: value / 100 })} />
          <span className="dim">%</span>
        </label>
        <label className="mask-stack-cell mask-stack-invert"><input type="checkbox" checked={item.inverted} disabled={disabled}
          onChange={(event) => patch(index, { inverted: event.target.checked })} />反转这一块</label>
        <div className="mask-stack-keys">
          <button type="button" className="btn tiny subtle" disabled={disabled || keysLimit === 0 || (item.keys?.length ?? 0) >= keysLimit || Boolean(atKey)}
            title={atKey
              ? "这一帧已经有一枚框点——上面五个数改的就是它。要在别的时刻再打一枚，先把播放头挪开。"
              : `把第 ${index + 1} 块现在的中心、大小与角度记在播放头那一帧上；打了框点的块按整帧窗一格一步地动，预览与导出读同一张表。`}
            onClick={() => stampKey(index)}>{atKey ? "这一帧已有框点" : "在播放头打框点"}</button>
          <span className="dim mask-stack-at" title={atKey
            ? "播放头正停在一枚框点上：上面五个数就是这一枚，改哪一个都写回这一枚。"
            : item.keys?.length
              ? "播放头不在这块的任何一枚框点上：上面五个数此刻不参与渲染，它们是下一次「在播放头打框点」会记下的值。"
              : "这块还没有框点：上面五个数就是它在整段里的静止值。"}>
            {item.keys?.length ?? 0} / {keysLimit} 枚框点{atKey ? " · 上面五个数改的是这一枚" : item.keys?.length ? " · 上面五个数是模板值" : ""}
          </span>
          {item.keys?.length ? <button type="button" className="btn tiny subtle" disabled={disabled}
            onClick={() => patch(index, { keys: [] })}>清空框点</button> : null}
        </div>
        {item.keys?.length ? <ul className="mask-stack-keylist">
          {item.keys.map((key) => <li key={key.at_ticks} className={key.at_ticks === active ? "current" : undefined}>
            <button type="button" className="btn tiny mono" aria-current={key.at_ticks === active ? "true" : undefined}
              title={key.at_ticks % frame
                ? `把播放头移到这一枚——它在 ${timecode(key.at_ticks, rate)} 之后 ${offsetWords(key.at_ticks % frame, rate)}，不在整帧上`
                : "把播放头移到这一帧"}
              onClick={() => { playhead.pause(); playhead.set(clip.position_ticks + key.at_ticks); }}>
              {timecode(key.at_ticks, rate)}
              {/* 1.248：两枚框点都显示同一个时间码时，人要能看出它们不是同一刻——差多少写在同一格里。 */}
              {key.at_ticks % frame ? <span className="mask-stack-sub"> +{offsetWords(key.at_ticks % frame, rate)}</span> : null}
            </button>
            <select className="input tiny" aria-label="这一段框点的插值" value={key.interpolation ?? "linear"}
              disabled={disabled}
              onChange={(event) => patch(index, { keys: (item.keys ?? []).map((row) => row.at_ticks === key.at_ticks
                ? { ...row, interpolation: event.target.value as MaskBoxKey["interpolation"] } : row) })}>
              {Object.entries(INTERPOLATIONS).filter(([value]) => value !== "bezier").map(([value, label]) =>
                <option key={value} value={value}>{label}</option>)}
            </select>
            <button type="button" className="btn tiny subtle" disabled={disabled} title="删掉这一枚框点"
              onClick={() => patch(index, { keys: (item.keys ?? []).filter((row) => row.at_ticks !== key.at_ticks) })}>删除</button>
          </li>)}
        </ul> : null}
      </div>
    </div>;
    })}
    <div className="insp-actions"><button className="btn tiny" disabled={disabled || full || limit === 0} title={full ? `最多 ${limit} 块；要再加，先删掉一块` : "这一版引擎不认识「再叠的遮罩」这一格，出路是换一台会回的引擎"} onClick={() => write([...stack, { ...DEFAULT_MASK, shape: "rectangle", feather: 0, vertices: null }])}>再抠一块</button></div>
    {stack.length ? <p className="hint" title="框点按整帧窗一格一步地走，导出与预览读同一张表；打点、改插值与删除在每一块自己那一行。条顶上那排小点就是这些框点的时间。">再叠的这几块与主遮罩取交集；打了框点的块按自己的窗走，其余的可以跟着主遮罩。</p> : null}
  </div>;
}

function MaskShapeKeys({ clip, mask, disabled, at }: { clip: Clip; mask: ShapeMask; disabled: boolean; at: number }) {
  const app = useApp();
  const limit = app.caps?.limits?.mask_shape_keys ?? 32;
  const keys = clip.mask_shape_keys ?? [];
  const offset = clip.animation_offset_ticks ?? 0;
  const drawn = (mask.vertices ?? []).map((vertex) => ({ ...vertex, handle_out: [...vertex.handle_out] as [number, number], handle_in: [...vertex.handle_in] as [number, number] }));
  const held = keys.some((key) => key.at_ticks - offset === at);
  const full = keys.length >= limit && !held;
  const rate = app.project?.settings.frame_rate ?? { numerator: 30, denominator: 1 };
  return <div className="mask-shape-keys">
    <div className="insp-actions">
      <button className={`btn tiny${held ? " active" : ""}`} disabled={disabled || full} title={full ? `这条遮罩已经记满 ${limit} 帧轮廓：先删掉一帧，或把这段切成两个片段分别做形变` : "把画好的轮廓记在播放头这一刻（同一时刻再按一次是顶替，不是插入第二帧）。有了第一帧，之后在画面里拖顶点就是继续变形。"} onClick={() => recordMaskShape(clip.id, drawn, at)}>{held ? "更新这一帧" : "记轮廓帧"}</button>
      {keys.length ? <button className="btn tiny subtle" disabled={disabled} title="一次删掉这条遮罩的全部轮廓帧（一批命令、一次撤销）：形状回到画出来的那一条" onClick={() => clearMaskShapes(clip.id, keys.map((key) => key.at_ticks - offset))}>清掉全部</button> : null}
    </div>
    {keys.length ? <>
      <p className="hint">{`轮廓帧 ${keys.length} / ${limit}：导出与预览都按引擎那份一格一步的窗执行，界面不自己插值。要改某一帧，把播放头移到那一帧，再在画面里拖顶点。`}</p>
      <ul className="mask-shape-list">{keys.map((key) => {
        const local = key.at_ticks - offset;
        return <li key={key.at_ticks}>
          <button type="button" className="btn tiny mono" title="把播放头移到这一帧" onClick={() => { playhead.pause(); playhead.set(clip.position_ticks + local); }}>{timecode(local, rate)}</button>
          <select className="input tiny" aria-label="这一帧轮廓的插值" value={key.interpolation} disabled={disabled} onChange={(e) => recordMaskShape(clip.id, key.vertices, local, e.target.value as MaskShapeKeyframe["interpolation"])}>{Object.entries(INTERPOLATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <button type="button" className="btn tiny subtle" disabled={disabled} title="删掉这一帧的形状；删到一枚不剩，遮罩就用画出来的那条轮廓" onClick={() => removeMaskShape(clip.id, local)}>删除</button>
        </li>;
      })}</ul>
    </> : <p className="hint">还没有轮廓帧：按上面那颗起第一帧，之后拖顶点改的就是那一刻。</p>}
  </div>;
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
    <div className="text-presets" role="group" aria-label="文字样式预设">
      {TEXT_PRESETS.map((preset) => <button key={preset.id} type="button" className="btn tiny subtle" title={preset.hint} disabled={locked} onClick={() => setClipText(clip.id, preset.style)}>{preset.label}</button>)}
    </div>
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
      <p className="hint">这些数预览与导出是同一组：都按「字号的百分之几」换算。</p>
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
      title={`在播放头处切成两段（${chordWords(keymap()["split-at-playhead"])}）`}
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
      <div className="ps-working">
        <label className="mask-shape">工程基色
          <select
            className="input"
            aria-label="工程基色"
            value={project.settings.working_primaries ?? DISPLAY_PRIMARIES}
            disabled={Boolean(app.busy) || workingChoices(app.caps?.working_primaries).length === 0}
            onChange={(event) => setWorkingPrimaries(event.target.value)}
            title={workingChoices(app.caps?.working_primaries).find((choice) => choice.value === (project.settings.working_primaries ?? DISPLAY_PRIMARIES))?.label ?? ""}
          >
            {workingChoices(app.caps?.working_primaries).map((choice) => (
              <option key={choice.value} value={choice.value} title={choice.label}>{choice.short}</option>
            ))}
          </select>
        </label>
        <p className="hint" title={workingProvenance(project.settings.working_primaries, app.caps?.working_primaries)}>{workingWords(project.settings.working_primaries, app.caps?.working_primaries)}</p>
      </div>
      <div className="ps-working">
        <label className="mask-shape">折叠曲线
          <select
            className="input"
            aria-label="折叠曲线"
            value={project.settings.fold_transfer ?? foldDefault(app.caps?.fold_transfers)}
            disabled={Boolean(app.busy) || foldChoices(app.caps?.fold_transfers).length === 0}
            onChange={(event) => setFoldTransfer(event.target.value)}
            title={foldChoices(app.caps?.fold_transfers).find((choice) => choice.value === (project.settings.fold_transfer ?? foldDefault(app.caps?.fold_transfers)))?.label ?? ""}
          >
            {foldChoices(app.caps?.fold_transfers).map((choice) => (
              <option key={choice.value} value={choice.value} title={choice.label}>{choice.short}</option>
            ))}
          </select>
        </label>
        <p className="hint" title={foldProvenance(project.settings.fold_transfer, app.caps?.fold_transfers)}>{foldWords(project.settings.fold_transfer, app.caps?.fold_transfers)}</p>
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
  "clip.link_split_trim": "分边修剪（J/L cut）",
  "clips.link_reconcile": "拉回音画同步",
  "transition.set": "镜头转场",
  "transition.remove": "移除转场",
  "clip.effects": "片段属性",
  "clip.mask": "调整遮罩",
  "clip.mask_track": "跟踪遮罩主体",
  "mask.shape.set": "记录遮罩轮廓",
  "mask.shape.remove": "删除遮罩轮廓",
  "clip.speed": "片段变速",
  "clip.color": "画面色彩",
  "clip.color_manage": "色彩管理套叠",
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


