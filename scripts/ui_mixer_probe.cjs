/*
 * 1.280 混音台的真页面量具：把渲染层伺服起来（同源代理 /v1 到引擎），点开检查器里的
 * 「混音台」，按命中点点 S、拖滑杆，再把三件只有真 DOM 才量得到的事实收回来：
 *
 *   ① 这一节画出来了几行、每行的名字/M/S/滑杆/百分数在不在同一行（矩形同一 y）；
 *   ② 点 S 之后引擎里那条轨真的 solo=true，预览清单里另一条轨 sound_enabled=false；
 *   ③ 滑杆改到 50% 松手之后引擎里 volume=0.5（拖动过程中不提交）。
 *
 * 判定不在这里：这里只交回读数与「量到没量到」，判据属于 tests/mixerui_check.py。
 *
 *   node scripts/ui_mixer_probe.cjs --renderer desktop/dist/renderer \
 *     --engine http://127.0.0.1:8765 --token T --project PID --out mixer.json --shot mixer.png
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
const SIZE = flag("size", "1456x808");
const OUT = path.resolve(flag("out", "ui_mixer_probe.json"));
const SHOT = flag("shot", "");
const EDGE = flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe");

if (!ENGINE || !TOKEN || !PROJECT) {
  console.error("usage: --engine --token --project are required");
  process.exit(2);
}
if (!fs.existsSync(path.join(RENDERER, "index.html"))) {
  console.error("renderer missing (build it first: cd desktop && npm run build:renderer)");
  process.exit(2);
}
execFileSync(process.execPath, ["--check", __filename], { stdio: "pipe" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function killByProfile(profileDir) {
  const needle = path.basename(profileDir);
  const script = "$ErrorActionPreference='SilentlyContinue';" +
    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" |" +
    " Where-Object { $_.CommandLine -like '*" + needle + "*' } |" +
    " ForEach-Object { Stop-Process -Id $_.ProcessId -Force }";
  try {
    execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
      { stdio: "ignore", timeout: 90000 });
  } catch {}
  // 杀完进程把这一份 Edge profile 还掉：只杀不删，一趟全套就在 %TEMP% 里留下几十个
  // `agentcut-*`（这台机器实测积到 346 个 / 7.2 GB）。刚退出的 Edge 可能还攥着句柄，
  // 所以带重试；删不掉也不报错——那是量具的抖动，不是产品的缺陷。
  try {
    fs.rmSync(profileDir, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 });
  } catch {}
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
  for (let port = hint; port < hint + 300; port += 1) if (await listenable(port)) return port;
  throw new Error("no free port under " + (hint + 300));
}

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2",
  ".ico": "image/x-icon", ".map": "application/json",
};

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
          },
        );
        upstream.on("error", () => { res.writeHead(502); res.end("proxy error"); });
        if (req.method !== "GET" && req.method !== "HEAD") req.pipe(upstream);
        else upstream.end();
        return;
      }
      const wanted = url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname);
      const file = path.join(RENDERER, path.normalize(wanted).replace(/^(\.\.[/\\])+/, ""));
      if (!file.startsWith(RENDERER) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(200, { "Content-Type": "text/html" });
        fs.createReadStream(path.join(RENDERER, "index.html")).pipe(res);
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
      resolve({
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
      });
    });
    socket.addEventListener("error", reject);
  });
}

async function projectState() {
  const response = await fetch(new URL("/v1/projects/" + encodeURIComponent(PROJECT), ENGINE), {
    headers: { Authorization: "Bearer " + TOKEN },
  });
  if (!response.ok) throw new Error("project read -> " + response.status);
  const body = await response.json();
  return body.project ?? body;
}

const ROW_READ = `(function () {
  return Array.from(document.querySelectorAll('.mixer-row')).map(function (row) {
    const name = row.querySelector('.mixer-name');
    const pills = Array.from(row.querySelectorAll('.mixer-pill'));
    const fader = row.querySelector('.mixer-fader');
    const value = row.querySelector('.mixer-value');
    const rect = function (node) { const r = node.getBoundingClientRect(); return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height) }; };
    return {
      name: name ? name.textContent.trim() : '',
      pills: pills.map(function (p) { return { text: p.textContent.trim(), pressed: p.getAttribute('aria-pressed'), box: rect(p) }; }),
      fader: fader ? { value: Number(fader.value), max: Number(fader.max), box: rect(fader) } : null,
      value: value ? { text: value.textContent.trim(), box: rect(value) } : null,
      rowBox: rect(row),
    };
  });
})()`;

async function main() {
  const [width, height] = SIZE.split("x").map(Number);
  const hostPort = await freePort(8846);
  const debugPort = await freePort(9936);
  const host = await startHost(hostPort);
  const profile = path.join(os.tmpdir(), "agentcut-mixer-" + Date.now().toString(36));
  const url = "http://127.0.0.1:" + hostPort + "/?engine=" + encodeURIComponent(ENGINE) +
    "&token=" + encodeURIComponent(TOKEN) + "&project=" + encodeURIComponent(PROJECT);
  const edge = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-port=" + debugPort, "--window-size=" + width + "," + height,
    "--user-data-dir=" + profile, url,
  ], { stdio: "ignore" });

  const facts = { viewport: { width, height }, url };
  let cdp = null;
  try {
    let target = null;
    for (let attempt = 0; attempt < 90 && !target; attempt += 1) {
      await sleep(400);
      let pages = [];
      try { pages = ((await requestJson("http://127.0.0.1:" + debugPort + "/json/list")) || []).filter((i) => i.type === "page"); } catch {}
      target = pages.find((item) => item.url === url);
    }
    if (!target) throw new Error("the renderer never opened a page target");
    cdp = await connect(target.webSocketDebuggerUrl);
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    const evaluate = async (expression) => {
      const answer = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, 30000);
      if (answer.exceptionDetails) throw new Error("probe threw: " + JSON.stringify(answer.exceptionDetails).slice(0, 400));
      return answer.result ? answer.result.value : null;
    };
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const tracks = await evaluate("document.querySelectorAll('.tl-head:not(.corner)').length");
      if (tracks > 0) break;
      await sleep(300);
    }
    // 2.0：右列默认是「AI 剪辑」，检查器在「属性」那一页；量具先切过去。
    await evaluate("(function(){var b=Array.from(document.querySelectorAll('.rp-tabs button')).find(" +
      "function(n){return (n.textContent||'').indexOf('属性')>=0;});if(b){b.click();return true;}return false;})()");
    await sleep(500);
    // 混音台是检查器里的一节 <details>：点摘要真的展开它。
    const summary = await evaluate(`(function () {
      const nodes = Array.from(document.querySelectorAll('.insp-section > summary'));
      const hit = nodes.find(function (n) { return (n.textContent || '').indexOf('混音台') >= 0; });
      if (!hit) return null;
      const details = hit.parentElement;
      const r = hit.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
        open: details.open, text: hit.textContent.trim(),
        left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top) };
    })()`);
    facts.summary = summary;
    if (!summary) throw new Error("检查器里没有「混音台」这一节");
    if (!summary.open) {
      // 工程设置那一节默认展开，会把混音台推到折叠线以下——先把它滚进视野再按命中点。
      const spot = await evaluate(`(function () {
        const nodes = Array.from(document.querySelectorAll('.insp-section > summary'));
        const hit = nodes.find(function (n) { return (n.textContent || '').indexOf('混音台') >= 0; });
        if (!hit) return null;
        hit.scrollIntoView({ block: 'center' });
        const r = hit.getBoundingClientRect();
        return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
      })()`);
      await sleep(350);
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: spot.x, y: spot.y, button: "left", buttons: 1, clickCount: 1 });
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: spot.x, y: spot.y, button: "left", buttons: 0, clickCount: 1 });
      await sleep(400);
    }
    facts.rows = await evaluate(ROW_READ);
    facts.detailsOpen = await evaluate(`(function () {
      const nodes = Array.from(document.querySelectorAll('.insp-section > summary'));
      const hit = nodes.find(function (n) { return (n.textContent || '').indexOf('混音台') >= 0; });
      return hit ? hit.parentElement.open : null;
    })()`);
    await cdp.send("Page.captureScreenshot", { format: "png" }, 30000).then((shot) => {
      if (SHOT && shot && shot.data) fs.writeFileSync(SHOT, Buffer.from(shot.data, "base64"));
    }).catch(() => {});

    // 点第二行的 S：引擎里那条轨 solo=true，另一条在预览清单里 sound_enabled=false。
    const sButton = await evaluate(`(function () {
      const rows = document.querySelectorAll('.mixer-row');
      const row = rows[1]; if (!row) return null;
      const btn = Array.from(row.querySelectorAll('.mixer-pill')).find(function (b) { return b.textContent.trim() === 'S'; });
      if (!btn) return null;
      const r = btn.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), pressed: btn.getAttribute('aria-pressed') };
    })()`);
    facts.sButton = sButton;
    if (!sButton) throw new Error("第二行没有 S 按钮");
    await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: sButton.x, y: sButton.y, button: "left", buttons: 1, clickCount: 1 });
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: sButton.x, y: sButton.y, button: "left", buttons: 0, clickCount: 1 });
    await sleep(1200);
    facts.afterSolo = await projectState();
    const manifest = await fetch(new URL("/v1/projects/" + encodeURIComponent(PROJECT) + "/preview-manifest", ENGINE), {
      headers: { Authorization: "Bearer " + TOKEN },
    }).then((r) => r.json());
    facts.soundEnabled = Object.fromEntries(Object.entries(manifest.clips).map(([key, plan]) => [key, plan.sound_enabled]));
    facts.rowsAfterSolo = await evaluate(ROW_READ);

    // 滑杆改到 50%：先只改本地（input），再松手（keyup）提交。
    facts.fader = await evaluate(`(function () {
      const row = document.querySelectorAll('.mixer-row')[0];
      const fader = row && row.querySelector('.mixer-fader');
      if (!fader) return null;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(fader, '50');
      fader.dispatchEvent(new Event('input', { bubbles: true }));
      return { value: fader.value, max: fader.max };
    })()`);
    await sleep(350);
    facts.projectBeforeCommit = await projectState();
    await evaluate(`(function () {
      const row = document.querySelectorAll('.mixer-row')[0];
      const fader = row && row.querySelector('.mixer-fader');
      if (fader) fader.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'ArrowLeft' }));
      return true;
    })()`);
    await sleep(1200);
    facts.afterVolume = await projectState();
  } finally {
    if (cdp) cdp.close();
    try { edge.kill(); } catch {}
    killByProfile(profile);
    try { host.close(); } catch {}
    fs.writeFileSync(OUT, JSON.stringify(facts, null, 2), "utf-8");
  }
  console.log("mixer probe wrote " + OUT);
}

main().catch((error) => {
  console.error("probe failed: " + (error && error.stack ? error.stack : String(error)));
  process.exit(1);
});
