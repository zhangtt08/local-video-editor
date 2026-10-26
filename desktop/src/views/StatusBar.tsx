import { Icon, IconBtn } from "../ui";
import { TIMEBASE } from "../time";
import { playhead, prefs, timelineEnd, useApp, useEdit, usePlay } from "../store";

/** 底部状态栏：默认只说人话，精确 tick 数值收在「精确数值」开关里。 */
export function StatusBar() {
  const app = useApp();
  const edit = useEdit();
  const play = usePlay();
  const project = app.project;
  const clip = project?.clips[app.selectedClip ?? ""] ?? null;
  const asset = clip ? project?.assets[clip.asset_id] : null;
  const end = timelineEnd(project);
  const frame = Math.round(
    (TIMEBASE * (project?.settings.frame_rate.denominator ?? 1)) / (project?.settings.frame_rate.numerator ?? 30)
  );

  // 首页（项目列表）不是编辑器：那里写「播放头 0.00s · 吸附 开 · 62px/s · 起点」说的是另一个界面的状态。
  const inEditor = app.view === "editor" && Boolean(project);

  return (
    <footer className="statusbar">
      {inEditor ? (
        <span className="status-item mono" title="播放头位置">
          {(play.ticks / TIMEBASE).toFixed(2)}s
        </span>
      ) : (
        <span className="status-item" title="本机工程总数">
          {app.projects.length} 个工程
        </span>
      )}
      {edit.showTicks ? (
        <>
          <span className="sep" />
          <span className="status-item mono dim" title="全工程统一时间基：所有时间都用整数 tick 保存，不用浮点秒">
            时间基 {TIMEBASE.toLocaleString("en-US")} tick/s · 1 帧 = {frame.toLocaleString("en-US")} tick
          </span>
        </>
      ) : null}
      <span className="spacer" />
      {!inEditor ? null : app.busy ? (
        <span className="status-item busy">
          <span className="spinner" />
          {app.busy}
        </span>
      ) : app.selectedClips.length > 1 ? <span className="status-item">选中 <b>{app.selectedClips.length}</b> 个片段</span> : clip && asset ? (
        <span className="status-item" title={`片段 id：${clip.id}`}>
          <b>{asset.label}</b> · {(clip.duration_ticks / TIMEBASE).toFixed(2)}s
        </span>
      ) : project ? (
        <span className="status-item dim">
          {end > 0
            ? `${Object.keys(project.clips).length} 段 · ${(end / TIMEBASE).toFixed(1)}s`
            : "从左侧素材库拖一段进来开始"}
        </span>
      ) : null}
      {inEditor ? (
        <>
          <span className="sep" />
          <span className="status-item" title="按 S 切换：开启后拖动会自动贴到整帧">
            吸附 <b>{edit.snap ? "开" : "关"}</b>
          </span>
          <span className="sep" />
          <span className="status-item mono" title="时间线缩放">
            {edit.pxPerSec}px/s
          </span>
          <span className="sep" />
          <IconBtn
            icon="info"
            label={edit.showTicks ? "隐藏精确数值" : "显示精确数值（tick）：与 Agent 对时时有用"}
            active={edit.showTicks}
            onClick={prefs.toggleTicks}
          />
          <button type="button" className="status-item link" title="播放头回到起点（Home）" onClick={() => playhead.set(0)}>
            <Icon name="start" size={11} /> 起点
          </button>
        </>
      ) : null}
    </footer>
  );
}
