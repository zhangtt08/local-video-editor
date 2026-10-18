/** 1.163「粘贴属性」那一排勾。
 *
 * 名单、每一类在来源上有多少东西、选中的这几段里谁接得下——都读引擎那一份规划回执。这个视图只排
 * 版面、只念回执：不自己列类别，不自己数段，不在引擎的数上再做一遍算术（1.158、1.161 两次都是
 * 界面自抄名单被门禁红的）。改一个勾就再问一次，所以人看到的那几个数永远是当下这一份。
 */

import { useEffect, useState } from "react";
import { askAttributeRows, pasteAttributes } from "../store";
import { defaultTicked, refusalLines, type AttributeRow } from "../attributePaste";
import type { AttributePlan } from "../engine";
import { Modal } from "../ui";

export function AttributeDialog({
  targets,
  sourceLabel,
  onClose,
}: {
  targets: string[];
  sourceLabel: string;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<AttributeRow[]>([]);
  const [plan, setPlan] = useState<AttributePlan | null>(null);
  const [ticked, setTicked] = useState<string[]>([]);
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    let alive = true;
    void askAttributeRows().then((answer) => {
      if (!alive || !answer) return;
      setRows(answer.rows);
      setPlan(answer.plan);
      setTicked(defaultTicked(answer.rows));
      setAsked(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  const toggle = (id: string) => {
    const next = ticked.includes(id) ? ticked.filter((one) => one !== id) : [...ticked, id];
    setTicked(next);
    // 一个都不勾时不必去问引擎（那一次没有要搬的东西），按钮也跟着灰着。
    if (next.length) {
      void askAttributeRows(next).then((answer) => {
        if (!answer) return;
        setRows(answer.rows);
        setPlan(answer.plan);
      });
    }
  };

  const wrote = plan?.written.length ?? 0;
  const said = plan ? refusalLines(plan) : [];
  const limit = plan?.target_limit ?? null;

  return (
    <Modal
      title="粘贴属性"
      sub={`来源：${sourceLabel} · 目标：选中的 ${targets.length} 段${limit ? `（一次最多 ${limit} 段）` : ""}`}
      onClose={onClose}
      width={520}
      footer={
        <>
          <button
            className="btn primary"
            disabled={!asked || !ticked.length || !wrote}
            title={
              !ticked.length
                ? "一个类别都没勾就没有要搬的东西：至少勾一样（引擎那句 ATTRIBUTE_NONE 说的就是这件事）。"
                : !wrote
                  ? "选中的这几段都接不下勾中的这几类：上面逐条写着是哪一段、哪一类、为什么。"
                  : `把这 ${ticked.length} 类写到那 ${wrote} 段上：一次批次、一个版本，撤销一步整批回来。`
            }
            onClick={() => {
              void pasteAttributes(ticked);
              onClose();
            }}
          >
            粘贴到 {wrote} 段
          </button>
          <button className="btn subtle" onClick={onClose}>
            取消
          </button>
        </>
      }
    >
      {rows.map((row) => (
        <div key={row.id} className="attribute-row">
          <label className="grade-switch" title={row.note}>
            <input
              id={`attribute-${row.id}`}
              type="checkbox"
              checked={ticked.includes(row.id)}
              onChange={() => toggle(row.id)}
            />
            {row.label}
            <span className="count">{row.count}</span>
          </label>
          <p className="hint">{row.note}</p>
        </div>
      ))}
      {said.length ? (
        <div className="attribute-refusals" role="status">
          {said.slice(0, 6).map((line) => (
            <p key={line} className="hint">
              {line}
            </p>
          ))}
          {said.length > 6 ? <p className="hint">另有 {said.length - 6} 条，粘完那支提示里逐条都在。</p> : null}
        </div>
      ) : null}
      {plan?.unchanged.length ? (
        <p className="hint">
          {plan.unchanged.length} 段在这几类上已经是这一份数，不会为它们发一条命令。
        </p>
      ) : null}
      <p className="hint" title="画面稳定交的是那一段量出来的相机运动，转场交的是这一段与邻居之间的那对关系——两类都不是「这几段共用的那一份数」，所以不搬，也不冒充能搬。">
        搬的是这几类本身，那几段在时间线上的位置一个字不动；画面稳定与转场不在这份名单里。
      </p>
    </Modal>
  );
}
