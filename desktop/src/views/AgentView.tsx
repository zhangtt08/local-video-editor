import { useEffect, useState } from "react";

import { bridge } from "../bridge";
import { Icon, Tag } from "../ui";
import { appInfo, boot, copy, loadHistory, loadLibrary, refreshProjects, setView, toggleHelp, useApp } from "../store";

/** Agent 页：一屏内给出「复制这段就能用」的配置，细节收进折叠区。 */
export function AgentView() {
  const app = useApp();
  const base = app.info?.base_url ?? "";
  const token = appInfo.token();
  const [enginePath, setEnginePath] = useState("");

  useEffect(() => {
    void bridge.appInfo().then((info) => setEnginePath(info.enginePath ?? ""));
  }, []);

  useEffect(() => {
    void loadHistory();
    const id = window.setInterval(() => void loadHistory(), 5000);
    return () => window.clearInterval(id);
  }, [app.project?.id, app.project?.revision]);

  const mcp = [
    "{",
    '  "mcpServers": {',
    '    "agentcut": {',
    `      "command": "${enginePath || "C:\\\\AgentCut\\\\resources\\\\bin\\\\agentcut\\\\agentcut.exe"}",`,
    `      "args": ["mcp"],`,
    `      "env": { "AGENTCUT_API_URL": "${base || "http://127.0.0.1:<端口>"}", "AGENTCUT_TOKEN": "${token || "<密钥>"}" }`,
    "    }",
    "  }",
    "}",
  ].join("\n");

  return (
    <div className="page agent">
      <div className="start-head">
        <h1 className="start-title">Agent 接入</h1>
        <span className="spacer" />
        {app.project ? (
          <button className="btn subtle" onClick={() => setView("editor")}>
            <Icon name="film" /> 回到剪辑
          </button>
        ) : null}
      </div>

      <p className="lede">
        桌面界面和你的 Agent 用的是同一套命令、同一个数据库。它改的内容会立刻出现在你的时间线上，你也能一键回到它改之前的版本。
      </p>

      <section className="card">
        <div className="card-title">
          <Icon name="robot" /> 给支持 MCP 的客户端（推荐）
        </div>
        <p className="hint">
          把下面这段贴进 Claude Desktop / Cursor / Qoder 的 MCP 配置，命令路径改成你的 AgentCut 安装目录即可。
        </p>
        <pre className="code-block mono">{mcp}</pre>
        <div className="card-actions">
          <button className="btn primary" onClick={() => void copy(mcp, "MCP 配置")}>
            <Icon name="copy" /> 复制配置
          </button>
          <button className="btn" onClick={() => void copy(`${base}|${token}`, "地址与密钥")}>
            <Icon name="copy" /> 复制地址 + 密钥
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-title">
          <Icon name="link" /> 直接调 HTTP
        </div>
        <div className="kv-list">
          <KV label="接口地址" value={base} onCopy={() => void copy(base, "接口地址")} />
          <KV label="Bearer 密钥" value={token} secret onCopy={() => void copy(token, "密钥")} />
          <KV label="免认证检查" value={`${base}/health`} onCopy={() => void copy(`${base}/health`, "健康检查地址")} />
        </div>
        <p className="hint">
          写入必须带 <span className="mono">request_id</span>（重试不会重复执行）和 <span className="mono">expected_revision</span>
          （别人改过就会冲突，不会覆盖）。先 <span className="mono">dry_run=true</span> 预演，再用同一个 request_id 提交。
        </p>
        <div className="card-actions">
          <button className="btn subtle" onClick={() => void bridge.openExternal(`${base}/docs`)}>
            <Icon name="info" /> 在线接口文档
          </button>
          <button className="btn subtle" onClick={() => void bridge.openExternal(`${base}/openapi.json`)}>
            <Icon name="link" /> OpenAPI
          </button>
          <button className="btn subtle" onClick={() => void bridge.restartEngine().then(() => boot())}>
            <Icon name="refresh" /> 重启引擎
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-title">
          <Icon name="history" /> 最近写入
          <span className="spacer" />
          <span className="tag mono">{app.history.length}</span>
        </div>
        {!app.project ? (
          <p className="hint">打开一个工程后，这里会显示它的真实写入审计（谁在什么时候用哪个 request_id 改的）。</p>
        ) : (
          <table className="table">
            <tbody>
              {app.history.slice(0, 8).map((row) => (
                <tr key={`${row.revision}-${row.request_id}`} className={row.revision === app.project?.revision ? "current" : ""}>
                  <td className="mono">r{row.revision}</td>
                  <td>{OPS[row.operation] ?? row.operation}</td>
                  <td className="mono ellipsis" title={row.request_id}>
                    {row.request_id}
                  </td>
                  <td className="mono dim">{localTime(row.created_at)}</td>
                  <td>
                    <button className="btn subtle" onClick={() => void copy(row.request_id, "request_id")}>
                      <Icon name="copy" size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <details className="card advanced">
        <summary>
          <Icon name="spark" /> 高级：完整命令清单与契约
        </summary>
        <div className="chip-cloud">
          {(app.caps?.commands ?? []).map((item) => (
            <span className="chip mono" key={item}>
              {item}
            </span>
          ))}
        </div>
        <div className="tool-list">
          {Object.entries(app.caps?.features ?? {}).map(([key, value]) => (
            <div className="tool-row" key={key}>
              <span className="mono">{key}</span>
              <Tag tone={value ? "ok" : "off"} mono>
                {value ? "true" : "false"}
              </Tag>
            </div>
          ))}
        </div>
        <p className="hint">
          权威 schema 在 <span className="mono">GET /v1/contracts</span>；界面不另写一套剪辑规则。
          批量上限 {app.caps?.max_commands_per_batch ?? 100} 条，时间基 {app.caps?.timebase?.toLocaleString("en-US") ?? "70,560,000"} tick/s。
        </p>
        <div className="card-actions">
          <button className="btn subtle" onClick={() => void refreshProjects()}>
            <Icon name="refresh" size={12} /> 刷新工程统计
          </button>
          <button className="btn subtle" onClick={() => void loadLibrary()}>
            <Icon name="folder" size={12} /> 刷新素材库
          </button>
          <button className="btn subtle" onClick={() => toggleHelp(true)}>
            <Icon name="keyboard" size={12} /> 帮助
          </button>
        </div>
      </details>
    </div>
  );
}

const OPS: Record<string, string> = { create: "创建工程", edit: "批量命令", restore: "历史恢复", update: "改工程设置" };

function KV({ label, value, secret, onCopy }: { label: string; value: string; secret?: boolean; onCopy?: () => void }) {
  const [reveal, setReveal] = useState(!secret);
  return (
    <div className="kv">
      <span className="kv-label">{label}</span>
      <span className="kv-value mono" title={value}>
        {value ? (reveal ? value : `${value.slice(0, 6)}${"•".repeat(10)}`) : "—"}
      </span>
      {secret ? (
        <button type="button" className="icon-btn tiny" title={reveal ? "隐藏" : "显示"} onClick={() => setReveal(!reveal)}>
          <Icon name={reveal ? "eyeOff" : "eye"} size={12} />
        </button>
      ) : null}
      {onCopy ? (
        <button type="button" className="icon-btn tiny" title={`复制${label}`} onClick={onCopy}>
          <Icon name="copy" size={12} />
        </button>
      ) : null}
    </div>
  );
}

function localTime(value: string) {
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour12: false });
}
