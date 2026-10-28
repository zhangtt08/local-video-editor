/*
 * 1.281 J/K/L 走带的真页面量具：把渲染层伺服起来，发真的键盘事件（L / J / K），读三件事：
 *
 *   ① 倍率牌：L 一次 1x、再一次 2x；J 变 -1x；K 之后牌子消失；
 *   ② 方向：倒放那 0.6 秒里走带时间码确实变小；K 之后两次采样不再动；
 *   ③ 状态牌是「播放中且速度不是 1」才出现（停止时不留一枚 1x 的假牌子）。
 *
 * 判定不在这里：这里只交回读数，判据属于 tests/shuttle_check.py。
 *
 *   node scripts/ui_shuttle_probe.cjs --renderer desktop/dist/renderer \
 *     --engine http://127.0.0.1:8765 --token T --project PID --out shuttle.json
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
const SIZE = flag("size", "1280x800");
const OUT = path.resolve(flag("out", "ui_shuttle_probe.json"));
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

const READ = `(function () {
  const chip = document.querySelector('.shuttle-chip');
  const code = document.querySelector('.timecode');
  return {
    chip: chip ? chip.textContent.trim() : null,
    chipLabel: chip ? chip.getAttribute('aria-label') : null,
    timecode: code ? code.textContent.trim() : null,
  };
})()`;

function secondsOf(text) {
  const hit = /(\d+):(\d+):(\d+):(\d+)/.exec(text || "");
  if (!hit) return null;
  return Number(hit[1]) * 3600 + Number(hit[2]) * 60 + Number(hit[3]) + Number(hit[4]) / 30;
}

async function main() {
  const [width, height] = SIZE.split("x").map(Number);
  const hostPort = await freePort(8852);
  const debugPort = await freePort(9942);
  const host = await startHost(hostPort);
  const profile = path.join(os.tmpdir(), "agentcut-shuttle-" + Date.now().toString(36));
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
    for (let attempt = 0; attempt < 200; attempt += 1) {
      const clips = await evaluate("document.querySelectorAll('.clip[data-id]').length");
      if (clips > 0) break;
      await sleep(300);
    }
    facts.clipsOnScreen = await evaluate("document.querySelectorAll('.clip[data-id]').length");
    if (!facts.clipsOnScreen) {
      // 全套跑的时候这一手红过一次（单跑永远绿）。只说「没有片段」查不出是页面没起来、
      // 工程没读到还是素材没落地——所以把那一刻页面自己说的话一起交回去。
      const where = await evaluate(
        "(function () { return JSON.stringify({"
        + "clips: document.querySelectorAll('.clip').length,"
        + "lanes: document.querySelectorAll('.lane').length,"
        + "timeline: !!document.querySelector('.timeline'),"
        + "toast: Array.from(document.querySelectorAll('.toast,.error,.banner'))"
        + ".map(function (n) { return n.textContent; }).slice(0, 3),"
        + "body: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 220)"
        + "}); })()"
      );
      throw new Error("时间线上没有片段（等了 60 秒）：那一刻页面是 " + where);
    }
    // 焦点不能停在输入框里，否则键盘会被当成打字。
    await evaluate("document.activeElement && document.activeElement.blur && document.activeElement.blur(); true");

    const press = async (key, code, vk) => {
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: vk }, 20000);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk }, 20000);
    };

    facts.idle = await evaluate(READ);
    await press("l", "KeyL", 76);
    await sleep(400);
    facts.afterL1 = await evaluate(READ);
    await press("l", "KeyL", 76);
    await sleep(400);
    facts.afterL2 = await evaluate(READ);
    const beforeJ = await evaluate(READ);
    await press("j", "KeyJ", 74);
    await sleep(650);
    const afterJ = await evaluate(READ);
    facts.reverse = {
      before: beforeJ.timecode,
      after: afterJ.timecode,
      chip: afterJ.chip,
      beforeSeconds: secondsOf(beforeJ.timecode),
      afterSeconds: secondsOf(afterJ.timecode),
    };
    await press("k", "KeyK", 75);
    await sleep(300);
    const stop1 = await evaluate(READ);
    await sleep(500);
    const stop2 = await evaluate(READ);
    facts.stopped = { first: stop1, second: stop2, equal: stop1.timecode === stop2.timecode };

    // 再从 0 处按 J：不能倒出时间线（时间码停在 0，牌子也不该出现）。
    await evaluate("document.activeElement && document.activeElement.blur && document.activeElement.blur(); true");
    await press("Home", "Home", 36);
    await sleep(200);
    facts.atStart = await evaluate(READ);
    await press("j", "KeyJ", 74);
    await sleep(350);
    facts.reverseAtStart = await evaluate(READ);
  } finally {
    if (cdp) cdp.close();
    try { edge.kill(); } catch {}
    killByProfile(profile);
    try { host.close(); } catch {}
    fs.writeFileSync(OUT, JSON.stringify(facts, null, 2), "utf-8");
  }
  console.log("shuttle probe wrote " + OUT);
}

main().catch((error) => {
  console.error("probe failed: " + (error && error.stack ? error.stack : String(error)));
  process.exit(1);
});
