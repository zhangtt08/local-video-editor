import { useState } from "react";

import { Icon } from "../ui";
import {
  alignMulticam,
  alignTrackLoudness,
  autoCaptions,
  autoGradeClip,
  duckTrack,
  openTemplates,
  roughCutTrack,
  splitScenes,
  useApp,
} from "../store";
import { STYLE_PRESETS, applyStylePreset } from "../stylePresets";

/**
 * AI 剪辑面板：每一张卡都调一个真实存在的引擎动作（引擎拒绝时点名原因），不是演示按钮。
 *
 * 屏上那一行只说「现在会怎样 / 还差什么」；怎么算的、上限在哪、被谁拒，全部收进这颗卡
 * 自己的悬停。默认只露四张最常按的，其余在「更多」里——一屏塞不下七件事。
 */
export function AIPanel() {
  const app = useApp();
  const [more, setMore] = useState(false);
  const project = app.project;
  const pictureTracks = project?.tracks.filter((track) => track.kind === "video" && !track.locked) ?? [];
  const audioTracks = project?.tracks.filter((track) => track.kind === "audio" && !track.locked) ?? [];
  const selected = app.selectedClips.map((id) => project?.clips[id]).filter(Boolean) as NonNullable<typeof project>["clips"][string][];
  const selectedPicture = selected.find((clip) => {
    const asset = project?.assets[clip.asset_id];
    return !clip.text && (asset?.kind === "video" || asset?.kind === "image" || asset?.kind === "sequence");
  });
  const selectedWithAudio = selected.find((clip) => {
    const asset = project?.assets[clip.asset_id];
    return !clip.text && (asset?.kind === "audio" || asset?.kind === "video");
  });
  const targetTrack = selectedPicture?.track_id ?? pictureTracks[0]?.id ?? null;

  const cards = [
    {
      id: "rough",
      icon: "spark",
      title: "智能剪辑",
      line: "把这条画面轨收成快节奏的粗剪",
      hover: "按镜头切分，每个镜头只留开头一段，整条轨一次提交。上限与默认每镜留几秒由 capabilities.limits 下发；带变速曲线、音画链接与文字片段逐段跳过并写明原因。",
      run: () => (targetTrack ? roughCutTrack(targetTrack) : undefined),
      enabled: Boolean(targetTrack),
      blocked: "先放一段画面素材到时间线",
      primary: true,
    },
    {
      id: "scenes",
      icon: "split",
      title: "智能分镜",
      line: "在硬切处把这段切开",
      hover: "用颜色差找镜头边界，从右往左切开，避免坐标互相带走；一个批次一个版本。",
      run: () => (selectedPicture ? splitScenes(selectedPicture.id) : undefined),
      enabled: Boolean(selectedPicture),
      blocked: "先选中一段画面片段",
      primary: true,
    },
    {
      id: "captions",
      icon: "captions",
      title: "自动字幕",
      line: "听这段素材的中文语音，落成字幕",
      hover: "本地语音模型听写（不联网），写到字幕轨；同一段素材按内容寻址，不会叠两份。",
      run: () => (selectedWithAudio ? autoCaptions(selectedWithAudio.id) : undefined),
      enabled: Boolean(selectedWithAudio),
      blocked: "先选中一段带声音的片段",
      primary: true,
    },
    {
      id: "grade",
      icon: "image",
      title: "自动调色",
      line: "按这段自己的亮度拉开黑白场",
      hover: "读片段帧的黑白场百分位，写回一条普通 clip.grade；再按一次是重算顶替，不是叠一层。",
      run: () => (selectedPicture ? autoGradeClip(selectedPicture.id) : undefined),
      enabled: Boolean(selectedPicture),
      blocked: "先选中一段画面片段",
      primary: true,
    },
    {
      id: "duck",
      icon: "volume",
      title: "自动闪避",
      line: "口播出现时自动压低配乐",
      hover: "在配乐轨上写一串音量关键帧给对白让路。",
      run: () => (audioTracks[0] ? duckTrack(audioTracks[0].id) : undefined),
      enabled: audioTracks.length > 0 || Boolean(project?.tracks.some((track) => track.kind === "video")),
      blocked: "还没有一条声音轨",
      primary: false,
    },
    {
      id: "loudness",
      icon: "mute",
      title: "统一响度",
      line: "这一轨的片段量到同一个响度",
      hover: "整轨逐段量 LUFS，再拧到目标档；数字静音与空轨按名字拒绝。",
      run: () => (audioTracks[0] ? alignTrackLoudness(audioTracks[0].id) : undefined),
      enabled: audioTracks.length > 0,
      blocked: "还没有一条声音轨",
      primary: false,
    },
    {
      id: "multicam",
      icon: "link",
      title: "多机位对齐",
      line: "按同期声把这几段对齐到同一拍",
      hover: "每段各占一条轨、至少两秒可听的声音；共享声音太弱、挤在同一条轨、带变速曲线都会点名拒绝。基准不动，只移动其它几段。",
      run: () => void alignMulticam(),
      enabled: selected.length >= 2,
      blocked: "先选中两段以上、各占一条轨的片段",
      primary: false,
    },
  ];
  const shown = more ? cards : cards.filter((card) => card.primary);

  return (
    <div className="ai-panel">
      <div className="ai-list">
        {shown.map((card) => (
          <button
            key={card.id}
            type="button"
            className="ai-card"
            disabled={!card.enabled || Boolean(app.busy)}
            title={card.enabled ? card.hover : card.blocked}
            onClick={() => void card.run()}
          >
            <span className="ai-card-icon"><Icon name={card.icon} size={17} /></span>
            <span className="ai-card-text">
              <b>{card.title}</b>
              <span>{card.enabled ? card.line : card.blocked}</span>
            </span>
            <Icon name="chevron" size={13} />
          </button>
        ))}
      </div>

      <button type="button" className="ai-more" aria-expanded={more} onClick={() => setMore(!more)}>
        {more ? "收起" : `更多动作（${cards.length - shown.length}）`}
      </button>

      <div className="ai-sec-head">
        <b>风格</b>
        <button type="button" onClick={() => openTemplates()} title="剪辑风格、字幕样式、入场 / 出场动画">更多</button>
      </div>
      <div className="style-row">
        {STYLE_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="style-card"
            style={{ ["--sw1" as string]: preset.swatch[0], ["--sw2" as string]: preset.swatch[1] }}
            title={`${preset.desc}${selectedPicture ? "" : "（先在时间线上选一段画面）"}`}
            onClick={() => applyStylePreset(preset.id)}
          >
            <span className="style-swatch" aria-hidden="true" />
            <span className="style-name">{preset.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
