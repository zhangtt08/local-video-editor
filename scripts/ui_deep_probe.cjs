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
const OUT = path.resolve(flag("out", "ui_deep_probe.json"));
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



const AUDIT = `(function () {
  const viewport = { w: window.innerWidth, h: window.innerHeight };
  const scroller = function (node) {
    const style = getComputedStyle(node);
    return /(auto|scroll|hidden)/.test(style.overflowY + style.overflowX);
  };
  const centre = function (node) {
    const r = node.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    const x = Math.round(r.left + r.width / 2);
    const y = Math.round(r.top + r.height / 2);
    if (x < 0 || y < 0 || x >= viewport.w || y >= viewport.h) return null;
    let parent = node.parentElement;
    while (parent && parent !== document.documentElement) {
      if (scroller(parent)) {
        const pr = parent.getBoundingClientRect();
        if (x < pr.left || x > pr.right || y < pr.top || y > pr.bottom) return null;
      }
      parent = parent.parentElement;
    }
    const style = getComputedStyle(node);
    if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) return null;
    return { x: x, y: y, r: r };
  };
  const label = function (node) {
    return (node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 40);
  };
  const root = ROOT ? document.querySelector(ROOT) : document.body;
  const seen = [];
  const cut = [];
  if (root) {
    for (const node of Array.from(root.querySelectorAll('button'))) {
      const spot = centre(node);
      if (!spot) continue;
      seen.push(node);
      const under = document.elementFromPoint(spot.x, spot.y);
      if (!under || !(under === node || node.contains(under))) {
        cut.push({ what: label(node), why: 'covered', by: under ? (under.tagName + '.' + (under.className || '')) : null });
      }
    }
  }
  const overflow = [];
  if (root) {
    for (const node of Array.from(root.querySelectorAll('.panel-scroll, .help-body, .tl-toolbar, .cmd-list'))) {
      if (!centre(node)) continue;
      if (node.scrollWidth > node.clientWidth + 1) {
        overflow.push({ cls: node.className, client: node.clientWidth, scroll: node.scrollWidth });
      }
    }
  }
  return { scope: SCOPE, root: ROOT, buttons: seen.length, cut: cut, overflow: overflow, viewport: viewport };
})()`

async function main() {
  const [width, height] = SIZE.split("x").map(Number);
  const hostPort = await freePort(8846);
  const debugPort = await freePort(9936);
  const host = await startHost(hostPort);
  const profile = path.join(os.tmpdir(), "agentcut-deep-" + Date.now().toString(36));
  const url = "http://127.0.0.1:" + hostPort + "/?engine=" + encodeURIComponent(ENGINE) +
    "&token=" + encodeURIComponent(TOKEN) + "&project=" + encodeURIComponent(PROJECT);
  const edge = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-port=" + debugPort, "--window-size=" + width + "," + height,
    "--user-data-dir=" + profile, url,
  ], { stdio: "ignore" });

  const facts = { viewport: { width, height }, url, scopes: {} };
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
    const audit = async (scope, rootSelector) => {
      const expression =
        "(function(){ const SCOPE = " + JSON.stringify(scope) +
        "; const ROOT = " + JSON.stringify(rootSelector || null) + "; return " + AUDIT + "; })()";
      facts.scopes[scope] = await evaluate(expression);
    };
    const press = async (x, y, modifiers) => {
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1, modifiers: modifiers || 0 });
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1, modifiers: modifiers || 0 });
    };
    const escape = async () => {
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      await sleep(300);
    };
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const clips = await evaluate("document.querySelectorAll('.clip:not(.ghost)').length");
      if (clips >= 2) break;
      await sleep(300);
    }
    const spots = await evaluate(`(function () {
      return Array.from(document.querySelectorAll('.clip:not(.ghost)')).slice(0, 2).map(function (node) {
        node.scrollIntoView({ block: 'nearest' });
        const r = node.getBoundingClientRect();
        return { x: Math.round(r.left + Math.min(r.width - 12, 40)), y: Math.round(r.top + 12) };
      });
    })()`);
    if (!spots || spots.length < 2) throw new Error("时间线上不足两段");
    await press(spots[0].x, spots[0].y, 0);
    await sleep(400);
    await evaluate("document.querySelectorAll('.panel-scroll details').forEach(function (d) { d.open = true; });");
    await sleep(600);
    await audit("clip");
    await press(spots[1].x, spots[1].y, 2);
    await sleep(600);
    await audit("multi");
    if (SHOT) {
      await cdp.send("Page.captureScreenshot", { format: "png" }, 30000).then((shot) => {
        if (shot && shot.data) fs.writeFileSync(SHOT, Buffer.from(shot.data, "base64"));
      }).catch(() => {});
    }

    const more = await evaluate(`(function () {
      const node = document.querySelector('[aria-label="这条轨的其它操作"]');
      if (!node) return null;
      const r = node.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    })()`);
    if (more) {
      await press(more.x, more.y, 0);
      await sleep(500);
      await audit("track-menu", '[role="menu"]');
      await escape();
    }

    const clipSpot = await evaluate(`(function () {
      const node = document.querySelector('.clip:not(.ghost)');
      if (!node) return null;
      const r = node.getBoundingClientRect();
      return { x: Math.round(r.left + Math.min(r.width - 12, 40)), y: Math.round(r.top + 12) };
    })()`);
    if (clipSpot) {
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: clipSpot.x, y: clipSpot.y, button: "right", buttons: 2, clickCount: 1 });
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: clipSpot.x, y: clipSpot.y, button: "right", buttons: 0, clickCount: 1 });
      await sleep(500);
      await audit("clip-menu", '[role="menu"]');
      await escape();
    }

    const helpButton = await evaluate(`(function () {
      const hit = Array.from(document.querySelectorAll('button'))
        .find(function (n) { return (n.textContent || '').indexOf('快捷键') >= 0; });
      if (!hit) return null;
      const r = hit.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    })()`);
    if (!helpButton) throw new Error("找不到打开帮助的「快捷键」按钮");
    await press(helpButton.x, helpButton.y, 0);
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (await evaluate("Boolean(document.querySelector('.help-body'))")) break;
      await sleep(250);
    }
    if (!(await evaluate("Boolean(document.querySelector('.help-body'))"))) {
      throw new Error("帮助页没有打开");
    }
    const featuresTab = await evaluate(`(function () {
      const hit = Array.from(document.querySelectorAll('.help .seg button'))
        .find(function (n) { return (n.textContent || '').trim() === '功能'; });
      if (!hit) return null;
      const r = hit.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    })()`);
    if (!featuresTab) throw new Error("帮助页没有「功能」页签");
    await press(featuresTab.x, featuresTab.y, 0);
    await sleep(500);
    await audit("help", ".help");
    const searched = await evaluate(`(function () {
      const field = document.querySelector('.help-body input[type="search"], .help-body input');
      if (!field) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(field, '粗剪');
      field.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    if (searched) {
      await sleep(500);
      await evaluate("document.querySelectorAll('.help-body details').forEach(function (d) { d.open = true; });");
      await sleep(300);
      await audit("help-search", ".help");
    }
    await escape();
    await sleep(300);

    for (const pair of [["导出", "export"], ["示波器", "scopes"], ["检查器", "inspector"]]) {
      const picked = await evaluate(`(function () {
        const hit = Array.from(document.querySelectorAll('.rail-tabs button'))
          .find(function (n) { return (n.textContent || '').indexOf(${JSON.stringify(pair[0])}) >= 0; });
        if (!hit) return null;
        const r = hit.getBoundingClientRect();
        return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
      })()`);
      if (!picked) continue;
      await press(picked.x, picked.y, 0);
      await sleep(600);
      await audit(pair[1]);
    }
  } finally {
    if (cdp) cdp.close();
    try { edge.kill(); } catch {}
    killByProfile(profile);
    try { host.close(); } catch {}
    fs.writeFileSync(OUT, JSON.stringify(facts, null, 2), "utf-8");
  }
  console.log("deep probe wrote " + OUT);
}

main().catch((error) => {
  console.error("probe failed: " + (error && error.stack ? error.stack : String(error)));
  process.exit(1);
});
