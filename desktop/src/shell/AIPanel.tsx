import { Icon } from "../ui";
import {
  alignMulticam,
  alignTrackLoudness,
  autoCaptions,
  autoGradeClip,
  duckTrack,
  roughCutTrack,
  splitScenes,
  useApp,
} from "../store";
import { STYLE_PRESETS, applyStylePreset } from "../stylePresets";

/**
 * AI 剪辑面板：每一张卡都调一个真实存在的引擎动作（引擎拒绝时点名原因），
 * 不是演示按钮。能不能按、为什么不能按，全部由此刻的工程状态与能力表决定。
 */
export function AIPanel() {
  const app = useApp();
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
      desc: "按镜头切分再每镜留头，一条画面轨一次粗剪",
      run: () => targetTrack ? roughCutTrack(targetTrack) : undefined,
      enabled: Boolean(targetTrack),
      reason: targetTrack ? "把这条画面轨按镜头粗剪成快节奏" : "先放一段画面素材到时间线",
    },
    {
      id: "scenes",
      icon: "split",
      title: "智能分镜",
      desc: "用颜色差找硬切，从右往左切开，一个批次",
      run: () => selectedPicture ? splitScenes(selectedPicture.id) : undefined,
      enabled: Boolean(selectedPicture),
      reason: selectedPicture ? "只切这一条选中的画面片段" : "先选中一段画面片段",
    },
    {
      id: "captions",
      icon: "captions",
      title: "自动字幕",
      desc: "本地语音模型听写，落到字幕轨",
      run: () => selectedWithAudio ? autoCaptions(selectedWithAudio.id) : undefined,
      enabled: Boolean(selectedWithAudio),
      reason: selectedWithAudio ? "识别这段素材里的中文语音" : "先选中一段带声音的片段",
    },
    {
      id: "grade",
      icon: "image",
      title: "自动调色",
      desc: "读这一段的帧，量出黑白场并写回色阶",
      run: () => selectedPicture ? autoGradeClip(selectedPicture.id) : undefined,
      enabled: Boolean(selectedPicture),
      reason: selectedPicture ? "按这一段自己的亮度分布拉黑白场" : "先选中一段画面片段",
    },
    {
      id: "duck",
      icon: "volume",
      title: "自动闪避",
      desc: "口播压配乐：把音量关键帧写进音乐轨",
      run: () => audioTracks[0] ? duckTrack(audioTracks[0].id) : undefined,
      enabled: audioTracks.length > 0 || Boolean(project?.tracks.some((track) => track.kind === "video")),
      reason: "在配乐轨上写一串音量关键帧，给对白让路",
    },
    {
      id: "loudness",
      icon: "mute",
      title: "统一响度",
      desc: "整轨量一次响度，拧到同一个目标",
      run: () => audioTracks[0] ? alignTrackLoudness(audioTracks[0].id) : undefined,
      enabled: audioTracks.length > 0,
      reason: audioTracks.length ? "这一轨的所有片段量同一个 LUFS" : "还没有一条声音轨",
    },
    {
      id: "multicam",
      icon: "link",
      title: "多机位对齐",
      desc: "两段以上同期声按包络互相关对齐，计划是普通移动",
      run: () => void alignMulticam(),
      enabled: selected.length >= 2,
      reason: selected.length >= 2 ? "按声音把这几段摆到同一个节拍上" : "先选中两段以上、各占一条轨的片段",
    },
  ];

  return (
    <div className="ai-panel">
      <div className="ai-hero">
        <span className="ai-hero-orb" aria-hidden="true" />
        <div>
          <b>Agent 剪辑</b>
          <span>每个动作都写成普通命令：可撤销、可交给 Agent 接着改。</span>
        </div>
      </div>

      <div className="ai-list">
        {cards.map((card) => (
          <button
            key={card.id}
            type="button"
            className="ai-card"
            disabled={!card.enabled || Boolean(app.busy)}
            title={card.reason}
            onClick={() => void card.run()}
          >
            <span className="ai-card-icon"><Icon name={card.icon} size={17} /></span>
            <span className="ai-card-text">
              <b>{card.title}</b>
              <span>{card.reason}</span>
            </span>
            <Icon name="chevron" size={13} />
          </button>
        ))}
      </div>

      <div className="ai-sec-head">
        <b>剪辑风格</b>
        <span>写进选中片段的调色与效果</span>
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

      <div className="ai-foot">
        <Icon name="robot" size={13} />
        <span>这些动作在 Agent 那一侧是同一批命令：<code>timeline_edit</code> / 只读分析路由。</span>
      </div>
    </div>
  );
}
