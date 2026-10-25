import { useCallback, useEffect, useState } from "react";

import { Icon } from "../ui";
import { cutTranscript, playhead, readTranscript, toast, useApp } from "../store";
import { EngineError } from "../engine";

type Phrase = Awaited<ReturnType<typeof readTranscript>> extends infer T
  ? T extends { phrases: (infer P)[] } ? P : never : never;

/** 秒表那样的短句首时间，读起来比一串 tick 快。 */
function stamp(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/**
 * 文稿：这条时间线「说了什么」按说的顺序排开。
 *
 * 点一句就把播放头放到那句上；勾几句再按「剪掉」，交回的是与手动剪完全相同的普通命令
 * ——一个版本、撤销一步整体退回。空档只报数量与位置，不占第二行说明。
 */
export function TranscriptPanel() {
  const app = useApp();
  const [phrases, setPhrases] = useState<Phrase[]>([]);
  const [holes, setHoles] = useState(0);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [empty, setEmpty] = useState("");

  const load = useCallback(async () => {
    setEmpty("");
    try {
      const view = await readTranscript();
      if (!view) return;
      setPhrases(view.phrases);
      setHoles(view.silence_count);
    } catch (error) {
      setPhrases([]);
      setHoles(0);
      setEmpty(error instanceof EngineError ? error.explain() : "读不出文稿");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, app.project?.revision, app.sequenceId]);

  const toggle = (index: number) => () => {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const cut = async () => {
    const spans = phrases.filter((phrase) => picked.has(phrase.index))
      .map((phrase) => ({ from_ticks: phrase.from_ticks - 1, to_ticks: phrase.to_ticks + 1 }));
    if (!spans.length) return;
    try {
      const done = await cutTranscript(spans);
      setPicked(new Set());
      if (done) {
        toast("ok", `剪掉 ${spans.length} 句`,
          done.skipped ? `${done.skipped} 个片段被跳过，原因在回执里。` : "撤销一步可以整体退回。");
        await load();
      }
    } catch (error) {
      toast("error", "这一刀没剪成",
        error instanceof EngineError ? error.explain() : String(error));
    }
  };

  if (empty) {
    return (
      <div className="transcript">
        <div className="tr-empty">
          <Icon name="captions" size={20} />
          <b>还没有可读的字幕</b>
          <span>{empty}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="transcript">
      <div className="tr-head">
        <b>{phrases.length} 句</b>
        {holes ? <span title="句与句之间够长的空档，也可以当成剪口">{holes} 处空档</span> : null}
        <span className="spacer" />
        <button
          type="button"
          className="btn tiny primary"
          disabled={!picked.size || Boolean(app.busy)}
          onClick={() => void cut()}
          title="把勾掉的这几句从所有轨上一起剪掉：画面、声音、字幕在同一些边界上断开，右边自动收拢"
        >
          {app.busy ? "在剪…" : `剪掉 ${picked.size || ""}`.trim()}
        </button>
      </div>
      <ul className="tr-list">
        {phrases.map((phrase) => (
          <li key={phrase.index} className={picked.has(phrase.index) ? "picked" : ""}>
            <button
              type="button"
              className="tr-check"
              role="checkbox"
              aria-checked={picked.has(phrase.index)}
              aria-label={`选择第 ${phrase.index} 句`}
              onClick={toggle(phrase.index)}
            >
              {picked.has(phrase.index) ? <Icon name="check" size={12} /> : null}
            </button>
            <button
              type="button"
              className="tr-body"
              title={`第 ${phrase.index} 句 · ${stamp(phrase.from_ms)}–${stamp(phrase.to_ms)} · 点击跳到这一句`}
              onClick={() => { playhead.pause(); playhead.set(phrase.from_ticks); }}
            >
              <span className="tr-time mono">{stamp(phrase.from_ms)}</span>
              <span className="tr-text">{phrase.text}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
