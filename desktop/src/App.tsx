import { useEffect } from "react";

import { bridge } from "./bridge";
import { ContextMenuHost } from "./ContextMenu";
import { shuttleRate } from "./shuttle";
import { LeftRail } from "./shell/LeftRail";
import { TopBar } from "./shell/TopBar";
import { AgentView } from "./views/AgentView";
import { Editor } from "./views/Editor";
import { HelpOverlay } from "./views/Help";
import { Home } from "./views/Home";
import { History } from "./views/History";
import { StatusBar } from "./views/StatusBar";
import { TemplateGallery } from "./views/TemplateGallery";
import { SettingsDialog } from "./views/SettingsDialog";
import { Icon } from "./ui";
import { matchCommand } from "./keymap";
import {
  dismissToast,
  keymap,
  playhead,
  prefs,
  refreshWindowState,
  runKeyCommand,
  timelineEnd,
  toggleHelp,
  useApp,
  jumpEditPoint,
  editSource,
  markSequence,
  markSource,
  selectedSource,
  setSourceCursor,
  setSourcePlaying,
  selectClips,
  removeSelection,
  nudgeSelection,
} from "./store";
import { TIMEBASE } from "./time";

export function App() {
  const app = useApp();
  useGlobalKeys();

  useEffect(() => {
    const onFocus = () => void refreshWindowState();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  // 没有全屏门：外壳第一帧就画出来，引擎在后台等用户真的用了才起（store.openShell）。
  const needsProject = app.view === "editor" || app.view === "history";
  const view = needsProject && !app.project ? "home" : app.view;

  return (
    <div className="app-frame">
      <LeftRail />
      <div className="app-main">
        <TopBar />
        <div className="app-body">
          {view === "home" ? <Home /> : null}
          {view === "editor" ? <Editor /> : null}
          {view === "history" ? <History /> : null}
          {view === "agent" ? <AgentView /> : null}
        </div>
        <StatusBar />
      </div>
      <ResizeHandles />
      <ToastHost />
      <ContextMenuHost />
      {app.showHelp ? <HelpOverlay /> : null}
      {app.templatesOpen ? <TemplateGallery /> : null}
      {app.settingsOpen ? <SettingsDialog /> : null}
      {app.busy || app.phase === "boot" ? (
        <div className="busy-pill" role="status">
          <span className="spinner" />
          {app.busy || "正在准备"}
        </div>
      ) : null}
    </div>
  );
}

function useGlobalKeys() {
  const app = useApp();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[role="dialog"]')) return;
      const typing =
        !!target && (target.tagName === "INPUT" && (target as HTMLInputElement).type !== "range" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (typing || app.showHelp && event.key !== "Escape" && event.key !== "F1") return;
      if (app.view === "editor" && (event.key === "F9" || event.key === "F10")) { event.preventDefault(); editSource(event.key === "F9" ? "insert" : "overwrite"); return; }
      if (target?.tagName === "SELECT") return;
      if (event.key === " ") {
        // 焦点停在按钮上时按空格会双重触发（原生激活 + 播放切换），先摘掉焦点。
        if (target && target.tagName === "BUTTON") target.blur();
        event.preventDefault();
        if (app.monitorMode === "source") { setSourcePlaying(!app.sourcePlaying); return; }
        if (playhead.playing) playhead.pause();
        else { if (playhead.value >= timelineEnd(app.project)) playhead.set(0); playhead.play(); }
        return;
      }
      // 1.134：命令键位是一张能改的表，解析只有一处（`keymap.matchCommand`），做的事也只有
      // `store.runKeyCommand` 那一个开关。条件不对就交回原路（返回 false），这条链的早退顺序
      // 与以前那条 if 链一致。
      const command = matchCommand(keymap(), event);
      if (command && runKeyCommand(command, event)) {
        event.preventDefault();
        return;
      }
      if (event.key === "F1") {
        event.preventDefault();
        toggleHelp();
        return;
      }
      if (event.key === "Escape") {
        if (document.fullscreenElement) { void document.exitFullscreen(); return; }
        if (app.showHelp) toggleHelp(false);
        else { prefs.setTool("select"); selectClips([]); }
        return;
      }
      if (app.view !== "editor" || !app.project) return;
      const key = event.key.toLowerCase();
      // 带修饰的那些已经全在表里了（上面那一次 `matchCommand`），这里只剩不带修饰的手感键。
      if (event.ctrlKey || event.metaKey) return;
      if (app.monitorMode !== "source" && (key === "i" || key === "o")) { event.preventDefault(); markSequence(key === "i" ? "in" : "out"); return; }
      if (app.monitorMode !== "source" && key === "x" && event.altKey) { event.preventDefault(); markSequence("clear"); return; }
      if (app.monitorMode === "source") {
        const source = selectedSource();
        if (key === "i" || key === "o") { event.preventDefault(); markSource(key === "i" ? "in" : "out"); return; }
        if (key === "x" && event.altKey) { event.preventDefault(); markSource("clear"); return; }
        if (key === "arrowleft" || key === "arrowright" || key === "home" || key === "end") {
          event.preventDefault(); setSourcePlaying(false);
          const frame = TIMEBASE * app.project.settings.frame_rate.denominator / app.project.settings.frame_rate.numerator;
          setSourceCursor(key === "home" ? 0 : key === "end" ? source?.end ?? 0 : app.sourceCursorTicks + frame * (event.shiftKey ? 10 : 1) * (key === "arrowleft" ? -1 : 1));
          return;
        }
        if (key === "j" || key === "k" || key === "l") { event.preventDefault(); setSourcePlaying(key === "l"); return; }
      }
      if ((key === "arrowleft" || key === "arrowright") && !event.altKey) {
        event.preventDefault();
        playhead.pause();
        const frame = TIMEBASE * app.project.settings.frame_rate.denominator / app.project.settings.frame_rate.numerator;
        playhead.set(Math.min(timelineEnd(app.project), playhead.value + frame * (event.shiftKey ? 10 : 1) * (key === "arrowleft" ? -1 : 1)));
        return;
      }
      if (key === "arrowup" || key === "arrowdown") { event.preventDefault(); playhead.pause(); jumpEditPoint(key === "arrowup" ? -1 : 1); return; }
      if (key === "k") { event.preventDefault(); playhead.pause(); return; }
      if (key === "j" || key === "l") {
        // 1.281：达芬奇那一手——J 倒放、K 停、L 正放；同一个方向再按一次就是 2× / 4× / 8×。
        // 速度阶梯只在 `shuttle.ts` 一处；这里只管「从停着开始」与「到头/到头反向」两件事。
        event.preventDefault();
        const direction = key === "l" ? 1 : -1;
        if (!playhead.playing) {
          if (direction > 0 && playhead.value >= timelineEnd(app.project)) playhead.set(0);
          if (direction < 0 && playhead.value <= 0) return;
          playhead.play(direction);
          return;
        }
        playhead.setRate(shuttleRate(true, playhead.rate, direction));
        return;
      }
      // 1.135：V/C/S/X、Delete/Shift+Delete、+/- 都进了那张表（上面那一次 `matchCommand` 已经把它们
      // 交给 `runKeyCommand`）。这里只剩两个**别名**：Backspace 删与「=」放大是同一件事的第二只手，
      // 它们不单独占一个键位，所以既不出现在那张表里，也不许被改键牵走。
      if (key === "backspace" && app.selectedClip) {
        event.preventDefault();
        removeSelection(event.shiftKey);
        return;
      }
      if (key === "=" && runKeyCommand("zoom-in", event)) {
        event.preventDefault();
        return;
      }
      if (event.altKey && (key === "arrowleft" || key === "arrowright") && app.selectedClip) {
        event.preventDefault();
        const frame = app.project.settings.frame_rate.numerator
          ? Math.round((TIMEBASE * app.project.settings.frame_rate.denominator) / app.project.settings.frame_rate.numerator)
          : 2352000;
        const step = (event.shiftKey ? TIMEBASE : frame) * (key === "arrowleft" ? -1 : 1);
        nudgeSelection(step);
      } else if (key === "home") playhead.set(0);
      else if (key === "end") playhead.set(timelineEnd(app.project));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [app.view, app.project, app.selectedClip, app.selectedClips, app.showHelp, app.monitorMode, app.sourceCursorTicks, app.sourcePlaying]);
}

const EDGES = ["top", "right", "bottom", "left", "top-right", "bottom-right", "bottom-left", "top-left"];

function ResizeHandles() {
  return (
    <div className="resize-handles" aria-hidden="true">
      {EDGES.map((edge) => (
        <span
          key={edge}
          className={`rz rz-${edge}`}
          onPointerDown={(event) => {
            if (!bridge.resize) return;
            const element = event.currentTarget;
            element.setPointerCapture(event.pointerId);
            let lastX = event.clientX;
            let lastY = event.clientY;
            const move = (ev: PointerEvent) => {
              void bridge.resize(edge, ev.clientX - lastX, ev.clientY - lastY);
              lastX = ev.clientX;
              lastY = ev.clientY;
            };
            const stop = () => {
              element.releasePointerCapture(event.pointerId);
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", stop);
              window.removeEventListener("pointercancel", stop);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", stop);
            window.addEventListener("pointercancel", stop);
          }}
        />
      ))}
    </div>
  );
}

function ToastHost() {
  const app = useApp();
  if (!app.toasts.length) return null;
  return (
    <div className="toast-host" role="status" aria-live="polite">
      {app.toasts.map((item) => (
        <button key={item.id} type="button" className={`toast ${item.kind}`} onClick={() => dismissToast(item.id)}>
          <Icon name={item.kind === "ok" ? "check" : item.kind === "error" ? "warning" : "info"} size={13} />
          <span className="toast-text">
            <b>{item.title}</b>
            {item.detail ? <em>{item.detail}</em> : null}
          </span>
        </button>
      ))}
    </div>
  );
}
