#!/usr/bin/env node
// MCP (Model Context Protocol) stdio 桥 —— 标准实现，把所有项目的 Agent API 暴露为 MCP tools。
// 用法：node <project>/agent/mcp-server.mjs
// 逻辑：读 agent/.endpoint（或 AGENT_BASE_URL）；不通则按 agent/README 里登记的启动命令自动拉起本地服务。
// 本机守卫要求非 GET 带令牌：令牌头名与令牌文件从 GET /api/agent/manifest 的 api 段读
// （manifest 是只读端点，不需要令牌）；AGENT_API_TOKEN 环境变量优先。
import { spawn } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '..');
const PROTOCOL = '2.2.0';
const SERVER_INFO = { name: path.basename(PROJECT_ROOT) + '-agent-api', version: '1.1.0' };

const log = (...a) => process.stderr.write(`[mcp] ${a.join(' ')}\n`);

function endpointFile() {
  const p = path.join(__dirname, '.endpoint');
  return existsSync(p) ? readFileSync(p, 'utf8').trim() : null;
}

// 每次调用现读令牌，不在模块加载时缓存：自动拉起的路上桥先于服务端写好文件，
// 服务端第一次起来之后 manifest 才能给出准确的 token_file。
async function authFor(base) {
  try {
    const r = await fetch(`${base}/api/agent/manifest`, { signal: AbortSignal.timeout(3000) });
    const body = await r.json().catch(() => ({}));
    const api = body?.data?.api || {};
    const header = String(api.token_header || '').trim();
    if (!header) return {};
    if (process.env.AGENT_API_TOKEN) return { header, token: process.env.AGENT_API_TOKEN };
    if (api.token_file && existsSync(api.token_file)) {
      const token = readFileSync(api.token_file, 'utf8').trim();
      if (token) return { header, token };
    }
    return { header };
  } catch { return {}; }
}

async function rpc(base, method, params) {
  const auth = await authFor(base);
  const headers = { 'content-type': 'application/json', ...(auth.header && auth.token ? { [auth.header]: auth.token } : {}) };
  const res = await fetch(`${base}/api/agent/${method === 'tools/list' ? 'tools' : 'tool'}`, {
    method: method === 'tools/list' ? 'GET' : 'POST',
    headers,
    body: method === 'tools/list' ? undefined : JSON.stringify(params),
    signal: AbortSignal.timeout(120_000),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.ok === false) {
    const reason = body?.error?.message || `HTTP ${res.status}`;
    if (res.status === 401) throw new Error(`${reason}（本桥没读到本机令牌：服务没起来、或 AGENT_API_DATA_DIR 与服务端不是同一个目录）`);
    throw new Error(reason);
  }
  return body;
}

async function ensureBase() {
  const candidates = [process.env.AGENT_BASE_URL, endpointFile(), process.env.AGENT_DEFAULT_BASE].filter(Boolean);
  for (const base of candidates) {
    try {
      const r = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(1500) });
      if (r.ok) return base;
    } catch { /* 继续尝试 */ }
  }
  // 自动拉起：约定 agent/launch.json = {"command":"node","args":["agent/server.mjs"],"ready_port":8790}
  const launchFile = path.join(__dirname, 'launch.json');
  if (!existsSync(launchFile)) throw new Error(`Agent 服务未启动且缺少 ${launchFile}；请先运行 npm run agent:serve`);
  const spec = JSON.parse(readFileSync(launchFile, 'utf8'));
  // 把 ready_port 传给服务端（AGENT_PORT）：端口被占时服务端会自动 +1 并写 .endpoint，扫描照样找得到。
  const child = spawn(spec.command, spec.args, { cwd: PROJECT_ROOT, stdio: 'ignore', detached: true, shell: false, env: { ...process.env, AGENT_PORT: String(spec.ready_port || 8790) } });
  child.unref();
  const port = spec.ready_port || 8790;
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500));
    for (let p = port; p < port + 12; p++) {
      try {
        const r = await fetch(`http://127.0.0.1:${p}/api/health`, { signal: AbortSignal.timeout(800) });
        if (r.ok) return `http://127.0.0.1:${p}`;
      } catch { /* 未就绪 */ }
    }
  }
  throw new Error('自动拉起 Agent 服务超时（30s）');
}

let BASE = null;

function msg(id, result) { return { jsonrpc: '2.0', id, result }; }
function err(id, code, message) { return { jsonrpc: '2.0', id, error: { code, message } }; }

async function handle(req) {
  const { id, method, params } = req;
  if (method === 'initialize') {
    return msg(id, { protocolVersion: PROTOCOL, capabilities: { tools: {} }, serverInfo: SERVER_INFO });
  }
  if (method === 'notifications/initialized' || method === 'initialized') return null;
  if (method === 'ping') return msg(id, {});
  if (method === 'tools/list') {
    BASE = BASE || await ensureBase();
    const body = await rpc(BASE, 'tools/list');
    return msg(id, { tools: body.data.map((t) => ({ name: t.name, description: t.description, inputSchema: t.input_schema, annotations: { readOnlyHint: t.risk === 'read', destructiveHint: false, openWorldHint: false } })) });
  }
  if (method === 'tools/call') {
    BASE = BASE || await ensureBase();
    try {
      const body = await rpc(BASE, 'tools/call', { tool: params.name, input: params.arguments || {} });
      return msg(id, { content: [{ type: 'text', text: JSON.stringify(body.data, null, 2) }], isError: false });
    } catch (e) {
      return msg(id, { content: [{ type: 'text', text: `调用失败：${e.message}` }], isError: true });
    }
  }
  return err(id, -32601, `不支持的方法：${method}`);
}

let buf = '';

function write(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let req;
    try { req = JSON.parse(line); } catch { write(err(null, -32700, 'parse error')); continue; }
    // 响应是异步的。切勿在此 process.exit()：stdout 接管道时写是异步缓冲的，
    // 立即退出会丢掉尚未 flush 的 tools/list、tools/call 响应。让事件循环自然排空。
    handle(req).then((out) => { if (out) write(out); })
      .catch((e) => write(err(req.id, -32603, e.message)));
  }
});
log(`bridge ready for ${PROJECT_ROOT}`);
