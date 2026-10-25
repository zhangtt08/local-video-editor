import { useRef, useState } from "react";

import { EngineError, type Command } from "../engine";
import { Icon, Modal } from "../ui";
import {
  applyTimelineOtio,
  exportTimelineFcpxml,
  exportTimelineOtio,
  planTimelineOtio,
  toast,
  useApp,
} from "../store";

type Plan = NonNullable<Awaited<ReturnType<typeof planTimelineOtio>>>;

/**
 * 交换格式：OTIO 进出、FCPXML 交出。
 * 导出是只读的；导入先交回普通命令（先清空受影响的轨道，再逐段 clip.add），
 * 审过之后走同一条批次——一个 revision，撤销一次整体退回。
 */
export function ExchangeSection() {
  const app = useApp();
  const file = useRef<HTMLInputElement | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState("");
  const features = app.caps?.features ?? {};
  const canOtio = Boolean(features.otio_export);
  const canFcpxml = Boolean(features.fcpxml_export);
  const canImport = Boolean(features.otio_import);

  const read = async (picked: File) => {
    setBusy("读 OTIO…");
    try {
      const document = JSON.parse(await picked.text()) as Record<string, unknown>;
      const planned = await planTimelineOtio(document);
      if (planned) setPlan(planned);
    } catch (error) {
      if (error instanceof EngineError) toast("error", "这份 OTIO 不能导入", error.explain());
      else toast("error", "这份文件不是 OTIO JSON", String(error));
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="exchange" aria-label="交换格式">
      <div className="exchange-head">
        <b>交换格式</b>
        <span>给 DaVinci／Final Cut／另一个 Agent 的时间线</span>
      </div>
      <div className="exchange-actions">
        <button
          type="button"
          className="exchange-btn"
          disabled={!canOtio || Boolean(app.busy)}
          onClick={() => void exportTimelineOtio()}
          title={canOtio ? "整个时间线复制成 OpenTimelineIO JSON：轨道、空隙、每一段的完整记录" : "这台引擎不下发 OTIO 导出"}
        >
          <Icon name="copy" size={14} />
          <span><b>复制 OTIO</b><em>OpenTimelineIO JSON</em></span>
        </button>
        <button
          type="button"
          className="exchange-btn"
          disabled={!canFcpxml || Boolean(app.busy)}
          onClick={() => void exportTimelineFcpxml()}
          title={canFcpxml ? "保存 FCPXML 1.9 到本机：Final Cut 与达芬奇都读得进" : "这台引擎不下发 FCPXML 导出"}
        >
          <Icon name="export" size={14} />
          <span><b>保存 FCPXML</b><em>直切 spine，略去的片段会说明</em></span>
        </button>
        <button
          type="button"
          className="exchange-btn"
          disabled={!canImport || Boolean(app.busy)}
          onClick={() => file.current?.click()}
          title={canImport ? "读一份 OTIO JSON，先出计划再应用" : "这台引擎不下发 OTIO 导入"}
        >
          <Icon name="folder" size={14} />
          <span><b>{busy || "导入 OTIO"}</b><em>按文件名匹配合格的素材</em></span>
        </button>
        <input
          ref={file}
          type="file"
          accept=".otio,.json,application/json"
          hidden
          aria-label="选择 OTIO 文件"
          onChange={(event) => {
            const picked = event.target.files?.[0];
            event.target.value = "";
            if (picked) void read(picked);
          }}
        />
      </div>
      <p className="exchange-hint">
        导入会先清空它接管的轨道，再按 OTIO 的空隙与源入点逐段加回；找不到的素材、同名两份素材、轨道数不够都按名字拒绝，一个字节都不写。
      </p>

      {plan ? (
        <Modal
          title="这份 OTIO 会这样落到时间线"
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
                  applyTimelineOtio(plan.commands as Command[]);
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
              {plan.clips} 段画面/声音 · {plan.text_clips} 段文字 · {plan.gaps} 个空隙 · {plan.commands.length} 条命令
            </div>
            {plan.dropped.transitions || plan.dropped.markers || plan.dropped.effects ? (
              <div className="exchange-plan-note warn">
                这份文件里的转场 {plan.dropped.transitions} 个、标记 {plan.dropped.markers} 个、效果{" "}
                {plan.dropped.effects} 个不随导入进来（OTIO 的转场语义与这里的时间线不同，先不猜）。
              </div>
            ) : null}
          </div>
        </Modal>
      ) : null}
    </section>
  );
}
