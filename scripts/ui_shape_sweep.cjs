/*
 * 跨屏形状扫描：把渲染层伺服起来（同源代理 /v1 到引擎），一屏一屏真点过去，
 * 每一屏都让 scripts/ui_shape_probe.js 量「画出来的东西」。
 *
 *   node scripts/ui_shape_sweep.cjs --renderer desktop/dist/renderer \
 *     --engine http://127.0.0.1:8765 --token T --project PID \
 *     --sizes 1456x808,1100x620 --out sweep.json
 *
 * 退出码只在「有任何一屏量不到」时非零；判定不在这份文件里做（那属于 tests/ui_shape_check.py），
 * 这里只负责交回数据与「量到没量到」。
 *
 * 三条量具纪律抄自 1.205 / 1.32 那一轮的教训：端口必须先能 bind 才用；附着的页必须与
 * 自己要的 URL 逐字相同；探针独立成文件并在启动前 `node --check` 一次，语法错在启动时炸出来，
 * 不许冒充成「界面没画」。
 */
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf("--" + name);
  return i === -1 ? fallback : args[i + 1];
};
const RENDERER = path.resolve(flag("renderer", "desktop/dist/renderer"));
const ENGINE = flag("engine", "");
const TOKEN = flag("token", "");
const PROJECT = flag("project", "");
const SIZES = (flag("sizes", "1456x808") || "").split(",");
const OUT = path.resolve(flag("out", "ui_shape_sweep.json"));
const EDGE = flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe");
const SHOTS = flag("shots", "");
const PROBE = path.resolve(flag("probe", path.join(__dirname, "ui_shape_probe.js")));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!ENGINE || !TOKEN || !PROJECT) {
  console.error("usage: --engine --token --project are required");
  process.exit(2);
}
if (!fs.existsSync(PROBE)) {
  console.error("probe missing: " + PROBE);
  process.exit(2);
}
try {
  execFileSync(process.execPath, ["--check", PROBE], { stdio: "pipe" });
} catch (error) {
  console.error("probe does not parse: " + String(error.stdout || "") + String(error.stderr || ""));
  process.exit(2);
}
if (!fs.existsSync(path.join(RENDERER, "index.html"))) {
  console.error("renderer missing (build it first: cd desktop && npm run build:renderer): " + RENDERER);
  process.exit(2);
}

function listenable(port) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once("error", () => resolve(false));
    probe.once("listening", () => probe.close(() => resolve(true)));
    probe.listen(port, "127.0.0.1");
  });
}
async function freePort(hint) {
  for (let port = hint; port < hint + 400; port += 1) if (await listenable(port)) return port;
  throw new Error("no free port under " + (hint + 400));
}

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2",
  ".ico": "image/x-icon", ".map": "application/json",
};

// 同源：/v1 转给引擎，别的都是渲染层的文件。浏览器不许为了一次量形状再去处理跨域。
function startHost(port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://127.0.0.1");
      if (url.pathname.startsWith("/v1/") || url.pathname === "/healthz") {
        const upstream = http.request(
          ENGINE.replace(/\/$/, "") + req.url,
          { method: req.method, headers: Object.assign({}, req.headers, { host: new URL(ENGINE).host }) },
          (reply) => {
            res.writeHead(reply.statusCode || 502, reply.headers);
            reply.pipe(res);
          }
        );
        upstream.on("error", () => { res.writeHead(502); res.end("proxy error"); });
        if (req.method !== "GET" && req.method !== "HEAD") req.pipe(upstream);
        else upstream.end();
        return;
      }
      const wanted = url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname);
      const file = path.join(RENDERER, path.normalize(wanted).replace(/^(\.\.[/\\])+/, ""));
      if (!file.startsWith(RENDERER) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        const index = path.join(RENDERER, "index.html");
        res.writeHead(200, { "Content-Type": "text/html" });
        fs.createReadStream(index).pipe(res);
        return;
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function requestJson(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => { try { resolve(JSON.parse(data)); } catch (error) { reject(error); } });
    });
    req.on("error", reject);
    req.setTimeout(15000, () => req.destroy(new Error("timeout")));
  });
}

function connect(webSocketUrl) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webSocketUrl);
    let nextId = 1;
    const pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
    });
    socket.addEventListener("open", () => {
      const api = {
        send: (method, params, budget) =>
          new Promise((resolveCall, rejectCall) => {
            const id = (nextId += 1);
            const timer = setTimeout(() => {
              if (pending.has(id)) { pending.delete(id); rejectCall(new Error("no answer for " + method)); }
            }, budget || 20000);
            pending.set(id, (message) => {
              clearTimeout(timer);
              if (message.error) rejectCall(new Error(method + ": " + JSON.stringify(message.error)));
              else resolveCall(message.result || {});
            });
            socket.send(JSON.stringify({ id, method, params: params || {} }));
          }),
        close: () => { try { socket.close(); } catch {} },
      };
      resolve(api);
    });
    socket.addEventListener("error", reject);
  });
}

async function sweepOne(size, hostPort, probeSource) {
  const [width, height] = size.split("x").map(Number);
  const debugPort = await freePort(9900 + (size.length * 7) % 90);
  const profile = path.join(os.tmpdir(), "agentcut-shape-" + size.replace("x", "-") + "-" + Date.now().toString(36));
  const url = "http://127.0.0.1:" + hostPort + "/?engine=http%3A%2F%2F127.0.0.1%3A" + hostPort +
    "&token=" + encodeURIComponent(TOKEN) + "&project=" + encodeURIComponent(PROJECT) +
    (flag("clip", "") ? "&clip=" + encodeURIComponent(flag("clip", "")) : "") +
    (flag("panel", "") ? "&panel=" + encodeURIComponent(flag("panel", "")) : "");
  const edge = spawn(
    EDGE,
    ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--remote-debugging-port=" + debugPort, "--window-size=" + width + "," + height,
      "--user-data-dir=" + profile, url],
    { stdio: "ignore" }
  );
  const rows = [];
  try {
    let target = null;
    for (let attempt = 0; attempt < 80 && !target; attempt += 1) {
      await sleep(400);
      let pages = [];
      try { pages = ((await requestJson("http://127.0.0.1:" + debugPort + "/json/list")) || []).filter((i) => i.type === "page"); } catch {}
      target = pages.find((item) => item.url === url);
      if (!target && pages.length && attempt > 40) throw new Error("attached page is someone else's: " + pages.map((p) => p.url).join(" "));
    }
    if (!target) throw new Error("the renderer never opened a page target for " + url);
    const cdp = await connect(target.webSocketDebuggerUrl);
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    const evaluate = async (expression) => {
      const answer = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, 30000);
      if (answer.exceptionDetails) throw new Error("probe threw: " + JSON.stringify(answer.exceptionDetails).slice(0, 300));
      return answer.result ? answer.result.value : null;
    };
    // 等应用真把工程读进来：状态栏那一条只有加载完才有项目名。
    // 等的是「屏幕上真的有字」，不是某个壳层节点存在——1.205 那一轮「五屏全报量不到」的根因
    // 就是把「能回话」当成了「画出来了」。
    let painted = null;
    for (let attempt = 0; attempt < 100 && !painted; attempt += 1) {
      const count = await evaluate("document.getElementsByTagName('*').length");
      if (count > 40) painted = count;
      else await sleep(300);
    }
    if (!painted) throw new Error("the page never painted anything at " + size);
    const tabsExpression = "Array.from(document.querySelectorAll('nav.tb-tabs button, [role=tab], .tabs button')).map(function (n, i) {" +
      "var r = n.getBoundingClientRect(); return {i: i, text: (n.textContent||'').trim().slice(0,20), label: n.getAttribute('aria-label')||'', x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2), selected: n.getAttribute('aria-selected')==='true'||/\\bactive\\b/.test(String(n.className||''))};})";
    const tabs = (await evaluate(tabsExpression)) || [];
    if (!tabs.length) throw new Error("no view tabs found on the page at " + size);
    const click = async (x, y) => {
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left" });
    };
    const run = async (screen) => {
      const data = await evaluate("(function(){ " + probeSource + " return measureAgentCutUi(); })()");
      rows.push({ screen, panel: flag("panel", ""), size, data });
      if (SHOTS) {
        // 证据要能给人眼复核：判据是量出来的，但「挡住」还是「量具看错」值得留一张图。
        const shot = await cdp.send("Page.captureScreenshot", { format: "png" }, 30000);
        if (shot && shot.data) {
          const file = path.join(SHOTS, (flag("panel", "") || "p") + "-" + String(screen).replace(/[\\/:*?"<>|\u0000-\u001f]/g, "") + "-" + size + ".png");
          fs.mkdirSync(SHOTS, { recursive: true });
          fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
        }
      }
    };
    // 名字要跟着「哪一颗真亮着」走，不能按名单的第 0 颗猜——深链会直接把应用带到编辑器，
    // 那一行挂错名字，读表的人就会以为「项目」那一屏长这个样子。
    const lit = tabs.find((row) => row.selected) || tabs[0];
    await run(String(lit.text || lit.label || "boot"));
    for (let t = 0; t < tabs.length; t += 1) {
      if (tabs[t].selected || !tabs[t].x || !tabs[t].y) continue;
      await click(tabs[t].x, tabs[t].y);
      await sleep(700);
      const lit = await evaluate(tabsExpression);
      const now = (lit || []).find((row) => row.i === t) || {};
      if (!now.selected) {
        rows.push({ screen: String(tabs[t].text || tabs[t].label), size, data: null, error: "clicked but the tab never lit" });
        continue;
      }
      await run(String(now.text || now.label));
    }
    cdp.close();
  } finally {
    try { edge.kill("SIGTERM"); } catch {}
    try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3 }); } catch {}
  }
  return rows;
}

async function main() {
  const hostPort = await freePort(18899);
  const host = await startHost(hostPort);
  const probeSource = fs.readFileSync(PROBE, "utf8");
  const all = [];
  try {
    for (const size of SIZES) all.push(...(await sweepOne(size, hostPort, probeSource)));
  } finally {
    host.close();
  }
  fs.writeFileSync(OUT, JSON.stringify(all, null, 1), "utf8");
  const screens = all.filter((row) => row.data).length;
  console.log("screens measured: " + screens + " of " + all.length + " -> " + OUT);
  if (!screens) process.exit(1);
}

main().catch((error) => { console.error("sweep failed: " + String(error && error.message ? error.message : error)); process.exit(1); });
