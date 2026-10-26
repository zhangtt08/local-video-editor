import { useRef, useState } from "react";

import { EngineError, type Command } from "../engine";
import { openContextMenu, type MenuEntry } from "../ContextMenu";
import { Icon, Modal } from "../ui";
import {
  applyTimelineImport,
  exportTimelineFcpxml,
  exportTimelineJianying,
  exportTimelineOtio,
  exportTimelineXmeml,
  planTimelineImport,
  toast,
  useApp,
} from "../store";

type Plan = NonNullable<Awaited<ReturnType<typeof planTimelineImport>>>;

const FORMATS: Record<string, string> = {
  otio: "OpenTimelineIO",
  fcpxml: "Final Cut XML",
  xmeml: "Premiere / FCP7 XML",
  edl: "CMX3600 剪辑表",
  jianying: "剪映草稿",
};

/**
 * 交换格式：把这条时间线交给别人的工具，或把别人剪好的一刀读进来。
 *
 * 出口以前是三颗并排的按钮（复制 OTIO / 保存 FCPXML / 保存剪映草稿），再加上这一档的
 * Premiere XML 就是四颗，格子里挤着「保存剪映草稿」这种只有一半宽的字；它们本来就是
 * 同一件事（另存一份工程），收成一颗「保存工程文件」，格式在菜单里各占一行。导入不直接写：先让引擎认格式、交回一份普通命令的计划，
 * 人审过再应用——一个 revision，撤销一次整体退回。这份格式里根本没有的东西
 * （转场、变速、遮罩…）逐类点名，所以「搬来一半」不会被看成「整刀都在」。
 */
export function ExchangeSection() {
  const app = useApp();
  const file = useRef<HTMLInputElement | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState("");
  const features = app.caps?.features ?? {};
  const canOtio = Boolean(features.otio_export);
  const canFcpxml = Boolean(features.fcpxml_export);
  const canJianying = Boolean(features.jianying_export);
  const canXmeml = Boolean(features.xmeml_export);
  const canImport = Boolean(features.interchange_import);
  const blocked = Boolean(app.busy);
  const canSave = !blocked && (canOtio || canFcpxml || canJianying || canXmeml);

  const saveMenu = (anchor: HTMLElement) => {
    const rect = anchor.getBoundingClientRect();
    const entries: MenuEntry[] = [
      {
        kind: "item", icon: "copy", label: "OpenTimelineIO",
        disabled: blocked || !canOtio,
        title: "整条时间线复制成 OTIO JSON：轨道、空隙、每一段的完整记录；别的工具读它最省事",
        run: () => void exportTimelineOtio(),
      },
      {
        kind: "item", icon: "export", label: "FCPXML 1.9",
        disabled: blocked || !canFcpxml,
        title: "Final Cut 与达芬奇都读得进；说不进 spine 的段逐条列在文件的 omitted 里，并置 complete=false",
        run: () => void exportTimelineFcpxml(),
      },
      {
        kind: "item", icon: "export", label: "Premiere / FCP7 XML",
        disabled: blocked || !canXmeml,
        title: "整帧时码、每条轨的直切；文字层要生成器、变速段要时基映射，这两类逐条点名、不照写",
        run: () => void exportTimelineXmeml(),
      },
      { kind: "sep", id: "after-xml" },
      {
        kind: "item", icon: "export", label: "剪映草稿",
        disabled: blocked || !canJianying,
        title: "draft_content.json：微秒区间、素材表、每条轨的片段；搬不过去的逐条点名",
        run: () => void exportTimelineJianying(),
      },
    ];
    openContextMenu({
      at: { x: rect.left, y: rect.bottom + 4 },
      title: "保存工程文件", label: "保存工程文件", returnTo: anchor, entries,
    });
  };

  const read = async (picked: File) => {
    setBusy("在读…");
    try {
      const text = await picked.text();
      const document = picked.name.toLowerCase().endsWith(".json") ? JSON.parse(text) as Record<string, unknown> : text;
      const planned = await planTimelineImport(document);
      if (planned) {
        setPlan(planned);
        if (!planned.complete) {
          toast("warn", `已读出 ${FORMATS[planned.format] ?? planned.format}`,
            `${planned.omitted.length} 类东西这一版搬不过来，弹窗里逐类列着；没搬之前时间线一个字没动。`);
        }
      }
    } catch (error) {
      if (error instanceof EngineError) {
        toast("error", "这份工程读不进来", error.explain());
      } else {
        toast("error", "这份文件读不出内容", String(error));
      }
    } finally {
      setBusy("");
    }
  };

  const leftOut = plan ? Object.entries(
    plan.omitted.reduce<Record<string, number>>((acc, item) => {
      acc[item.kind] = (acc[item.kind] ?? 0) + 1;
      return acc;
    }, {}),
  ) : [];

  return (
    <section className="exchange" aria-label="交换格式">
      <div className="exchange-head">
        <b>交换格式</b>
      </div>
      <div className="exchange-actions">
        <button
          type="button"
          className="exchange-btn"
          disabled={!canSave}
          onClick={(event) => saveMenu(event.currentTarget)}
          title={canSave
            ? "整条时间线另存一份工程文件：OpenTimelineIO、FCPXML 1.9、Premiere / FCP7 XML、剪映草稿。每种格式说不进的东西，保存后逐条点名"
            : "这台引擎不下发工程导出"}
        >
          <Icon name="export" size={14} />
          <span><b>保存工程文件</b></span>
        </button>
        <button
          type="button"
          className="exchange-btn"
          disabled={!canImport || Boolean(app.busy)}
          onClick={() => file.current?.click()}
          title={canImport
            ? "读一份别的软件导出的工程：OTIO、FCPXML、Premiere/FCP7 XML、CMX3600 剪辑表、剪映明文草稿。引擎自己认格式，先出计划再应用；素材按文件名对到本机已核过的媒体夹，对不上就整份按名字拒绝"
            : "这台引擎不下发工程导入"}
        >
          <Icon name="folder" size={14} />
          <span><b>{busy || "导入工程"}</b></span>
        </button>
        <input
          ref={file}
          type="file"
          accept=".otio,.json,.fcpxml,.xml,.edl,.txt"
          hidden
          aria-label="选择要读进来的工程文件"
          onChange={(event) => {
            const picked = event.target.files?.[0];
            event.target.value = "";
            if (picked) void read(picked);
          }}
        />
      </div>

      {plan ? (
        <Modal
          title={`这份${FORMATS[plan.format] ?? plan.format}会这样落到时间线`}
          sub="审过再应用：一批普通命令、一个 revision；撤销一次整体退回。"
          width={520}
          onClose={() => setPlan(null)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setPlan(null)}>取消</button>
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  applyTimelineImport(plan.commands as Command[], FORMATS[plan.format] ?? plan.format);
                  setPlan(null);
                }}
              >
                应用这 {plan.clips} 段
              </button>
            </>
          }
        >
          <div className="exchange-plan">
            {plan.tracks.map((track) => (
              <div key={track.track_id} className="exchange-plan-row">
                <Icon name={track.kind === "audio" ? "music" : "film"} size={13} />
                <b>{track.name}</b>
                <span>{track.clips} 段</span>
              </div>
            ))}
            <div className="exchange-plan-note">
              {plan.clips} 段 · {plan.text_clips} 段文字 · {plan.gaps} 个空隙 · {plan.commands.length} 条命令
            </div>
            {leftOut.length ? (
              <div className="exchange-plan-note warn">
                {leftOut.map(([kind, count]) => `${kind} ${count} 处`).join("、")}
                这一版搬不过来（那份格式里没有对应的说法）；工程里的东西一个没动。
              </div>
            ) : null}
          </div>
        </Modal>
      ) : null}
    </section>
  );
}
