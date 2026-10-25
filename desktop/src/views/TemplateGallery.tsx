import { useState } from "react";

import { Modal } from "../ui";
import { MOTION_PRESETS, type MotionPresetId, type MotionSide } from "../motionPresets";
import { STYLE_PRESETS, applyStylePreset } from "../stylePresets";
import { TEXT_PRESETS } from "../textStyle";
import { applyMotionTemplate, applyTextTemplate } from "../templateActions";
import { closeTemplates, useApp } from "../store";

type Tab = "style" | "text" | "motion";

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "style", label: "剪辑风格", hint: "调色与锐化，写在选中的画面上" },
  { id: "text", label: "字幕样式", hint: "字号、颜色、描边、垫子，写在选中的字幕上" },
  { id: "motion", label: "入场 / 出场", hint: "普通关键帧，一次撤销整批退回" },
];

const DURATIONS = [0.3, 0.5, 0.8, 1.2];

/** 模板库：参考图里左侧那一格「模板」。四张风格、五档字幕、七种入出场——全是引擎已有的普通命令。 */
export function TemplateGallery() {
  const app = useApp();
  const [tab, setTab] = useState<Tab>("style");
  const [side, setSide] = useState<MotionSide>("in");
  const [seconds, setSeconds] = useState(0.5);

  return (
    <Modal
      title="模板"
      sub="选中一段画面或一条字幕再点：模板只写普通命令，撤销一次就退回。"
      width={760}
      onClose={closeTemplates}
      footer={
        <>
          <span className="template-hint">
            {app.selectedClips.length ? `已选中 ${app.selectedClips.length} 段` : "还没有选中片段"}
          </span>
          <button type="button" className="btn" onClick={closeTemplates}>关闭</button>
        </>
      }
    >
      <div className="tpl-tabs" role="tablist" aria-label="模板分类">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
            title={item.hint}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "style" ? (
        <div className="tpl-grid style">
          {STYLE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className="tpl-card"
              onClick={() => applyStylePreset(preset.id)}
              title={preset.desc}
            >
              <span
                className="tpl-swatch"
                style={{ ["--sw1" as string]: preset.swatch[0], ["--sw2" as string]: preset.swatch[1] }}
                aria-hidden="true"
              />
              <b>{preset.name}</b>
              <span>{preset.desc}</span>
            </button>
          ))}
        </div>
      ) : null}

      {tab === "text" ? (
        <div className="tpl-list">
          {TEXT_PRESETS.map((preset) => (
            <button key={preset.id} type="button" className="tpl-row" onClick={() => applyTextTemplate(preset.id)} title={preset.hint}>
              <b>{preset.label}</b>
              <span>{preset.hint}</span>
            </button>
          ))}
        </div>
      ) : null}

      {tab === "motion" ? (
        <>
          <div className="tpl-controls">
            <div className="seg mini" role="group" aria-label="入场还是出场">
              <button type="button" className={side === "in" ? "active" : ""} aria-pressed={side === "in"} onClick={() => setSide("in")}>入场</button>
              <button type="button" className={side === "out" ? "active" : ""} aria-pressed={side === "out"} onClick={() => setSide("out")}>出场</button>
            </div>
            <div className="seg mini" role="group" aria-label="动画时长">
              {DURATIONS.map((value) => (
                <button key={value} type="button" className={seconds === value ? "active" : ""} aria-pressed={seconds === value} onClick={() => setSeconds(value)}>
                  {value} 秒
                </button>
              ))}
            </div>
          </div>
          <div className="tpl-grid motion">
            {MOTION_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="tpl-card"
                title={preset.hint}
                onClick={() => applyMotionTemplate(side, preset.id as MotionPresetId, seconds)}
              >
                <b>{preset.label}</b>
                <span>{preset.hint}</span>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </Modal>
  );
}
