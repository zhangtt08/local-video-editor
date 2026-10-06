import { useEffect, useState } from "react";

import { Btn, Empty, Icon, IconBtn, Modal, Tag } from "../ui";
import type { HistoryRow } from "../store";
import { copy, loadHistory, restoreRevision, setView, useApp } from "../store";

const OPERATIONS: Record<string, string> = {
  create: "创建工程",
  edit: "批量命令",
  restore: "历史恢复",
  "bundle.import": "导入工程包",
};

/** created_at 存的是 UTC，补上 Z 再交给 Date，显示成本机时区。 */
function localTime(value: string): string {
  const stamp = value.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export function History(): JSX.Element {
  const app = useApp();
  const [pending, setPending] = useState<HistoryRow | null>(null);
  const project = app.project;

  useEffect(() => {
    void loadHistory();
  }, [project?.id, project?.revision]);

  if (!project) {
    return (
      <div className="page narrow">
        <Empty
          icon="history"
          lines={
            <>
              <b>还没有打开工程</b>
              <span>历史是这条时间线的版本快照：每次写入都会留下 revision 和 request_id，可以回到任意一刻。</span>
            </>
          }
        />
      </div>
    );
  }

  const rows = [...app.history].sort((a, b) => b.revision - a.revision);
  const nextRevision = project.revision + 1;

  return (
    <div className="page narrow">
      <header className="hist-head">
        <div className="hist-head-main">
          <h1 className="page-title">{project.name}</h1>
          <div className="hist-current">
            当前版本 <Tag mono tone="accent">r{project.revision}</Tag>
            <span className="dim">共 {rows.length} 条快照 · 时间均为本地时间</span>
          </div>
        </div>
        <Btn onClick={() => setView("editor")} title="返回时间线继续剪辑">
          回到剪辑
        </Btn>
      </header>

      <p className="hist-restore-note">
        回到某一时刻不会删除历史：会用那一版的内容生成新的 r{nextRevision}，已有的版本号与 Agent 的回执都不受影响。
      </p>

      {rows.length === 0 ? (
        <Empty
          icon="history"
          lines={
            <>
              <b>还没有读取到历史记录</b>
              <span>
                引擎会为每次写入保存快照。若这里一直是空的，点右上角“回到剪辑”做一次改动，或重启引擎后重新打开工程。
              </span>
            </>
          }
        />
      ) : (
        <div className="hist-list">
          {rows.map((row) => {
            const current = row.revision === project.revision;
            return (
              <div key={`${row.revision}-${row.request_id}`} className={`hist-item${current ? " current" : ""}`}>
                <div className="hist-rail" aria-hidden="true">
                  <span className="hist-node" />
                  <span className="hist-line" />
                </div>
                <div className="hist-body">
                  <div className="hist-row1">
                    <span className="hist-rev mono">r{row.revision}</span>
                    <span className="hist-summary">
                      {OPERATIONS[row.operation] ?? row.operation}
                    </span>
                    {current ? <Tag tone="ok">当前</Tag> : null}
                    <span className="spacer" />
                    <span className="hist-time" title={`created_at ${row.created_at}（UTC）`}>
                      {localTime(row.created_at)} <span className="dim">本地时间</span>
                    </span>
                    <Btn
                      onClick={() => setPending(row)}
                      disabled={current}
                      title={current ? "已经是这一版了" : `用 r${row.revision} 的内容生成新版本`}
                    >
                      回到这一刻
                    </Btn>
                  </div>
                  <div className="hist-req">
                    <span className="mono ellipsis" title={`幂等回执：同一个 request_id 重试不会重复执行\n${row.request_id}`}>
                      {row.request_id}
                    </span>
                    <IconBtn icon="copy" label="复制 request_id" onClick={() => void copy(row.request_id, "request_id")} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {pending ? (
        <Modal
          title={`恢复到 r${pending.revision}`}
          sub={`恢复不会删除历史，而是用 r${pending.revision} 的旧内容生成一个新版本 r${nextRevision}，所以 Agent 的重试与回执都不会被打乱。`}
          width={480}
          onClose={() => setPending(null)}
          footer={
            <>
              <Btn onClick={() => setPending(null)}>取消</Btn>
              <Btn
                variant="primary"
                disabled={Boolean(app.busy)}
                onClick={() => {
                  const target = pending.revision;
                  setPending(null);
                  void restoreRevision(target);
                }}
              >
                确认恢复
              </Btn>
            </>
          }
        >
          <div className="hist-confirm">
            <div>
              <span className="dim">操作</span> {OPERATIONS[pending.operation] ?? pending.operation}
            </div>
            <div>
              <span className="dim">时间</span> {localTime(pending.created_at)}（本地时间）
            </div>
            <div className="mono ellipsis" title={pending.request_id}>
              {pending.request_id}
            </div>
            <p>
              <Icon name="warning" size={12} /> 当前 r{project.revision} 的时间线内容会被这一版替换；
              导出任务不受影响，它们仍锁定各自提交时的版本。
            </p>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
