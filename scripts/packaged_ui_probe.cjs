/*
 * 装机的界面那一腿（1.279 起常驻）：开真发布的 AgentCut.exe（隔一份自己的 user-data-dir），
 * 用**它自己的引擎**建一个空工程与一条轨道，再按命中点点开这个工程，量工作台的形状。
 *
 * 跑法（由 `tests/packaged_ui_check.py` 代管）：
 *   node scripts/packaged_ui_probe.cjs --exe <win-unpacked/AgentCut.exe> --profile <dir>  *     --out <json> --shot <png> --version 1.279.0 [--port 9391]
 *
 * 这一档存在的理由：`released_package_check` 只能证明 asar 里带着新的 CSS，证明不了它在
 * 真窗口里画成了圆角卡片；`ui_shape_check` 量的是开发树那份渲染层。判据全是
 * getComputedStyle 与 DOM 计数，照片落盘给人眼复核。
 */
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const REPO = path.resolve(__dirname, "..");
const flag = (name, fallback) => {
  const at = process.argv.indexOf("--" + name);
  return at >= 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
};
const EXE = path.resolve(flag("exe", path.join(REPO, "desktop/release/win-unpacked/AgentCut.exe")));
const PROFILE = path.resolve(flag("profile", path.join(REPO, "build/packaged-ui-profile")));
const OUT = path.resolve(flag("out", path.join(REPO, "build/packaged-ui.json")));
const SHOT = path.resolve(flag("shot", path.join(REPO, "build/packaged-ui.png")));
const WANT_VERSION = flag("version", "");
const PORT = Number(flag("port", "9391"));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function requestJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => { try { resolve(JSON.parse(data)); } catch (error) { reject(error); } });
    }).on("error", reject);
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
    socket.addEventListener("error", () => reject(new Error("cdp socket error")));
    socket.addEventListener("open", () => resolve({
      send: (method, params, budget) => new Promise((resolveCall, rejectCall) => {
        const id = (nextId += 1);
        const timer = setTimeout(() => {
          if (pending.has(id)) { pending.delete(id); rejectCall(new Error("no answer for " + method)); }
        }, budget || 60000);
        pending.set(id, (message) => {
          clearTimeout(timer);
          if (message.error) rejectCall(new Error(method + ": " + JSON.stringify(message.error)));
          else resolveCall(message.result || {});
        });
        socket.send(JSON.stringify({ id, method, params: params || {} }));
      }),
      close: () => { try { socket.close(); } catch {} },
    }));
  });
}

async function evaluate(cdp, expression) {
  // 满载的套件里，渲染进程偶尔慢到第一次求值超时；重试一次比把一整档判红更接近真相。
  let answer;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      answer = await cdp.send(
        "Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, 60000
      );
      break;
    } catch (error) {
      const message = String(error && error.message ? error.message : error);
      if (attempt === 1 || !message.includes("no answer")) throw error;
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
  }
  if (answer.exceptionDetails) throw new Error(JSON.stringify(answer.exceptionDetails).slice(0, 600));
  return answer.result.value;
}

async function clickAt(cdp, x, y) {
  for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
    await cdp.send("Input.dispatchMouseEvent", {
      type, x, y, button: type === "mouseMoved" ? "none" : "left",
      clickCount: type === "mouseMoved" ? 0 : 1, buttons: type === "mouseReleased" ? 0 : 1,
    });
  }
}

async function api(base, token, route, payload, method = "GET") {
  const response = await fetch(new URL(route, base), {
    method,
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(route + " -> " + response.status + " " + (await response.text()).slice(0, 300));
  return await response.json();
}

async function main() {
  if (!fs.existsSync(EXE)) throw new Error("no packaged exe at " + EXE);
  fs.rmSync(PROFILE, { recursive: true, force: true });
  fs.mkdirSync(PROFILE, { recursive: true });
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const child = spawn(EXE, ["--user-data-dir=" + PROFILE, "--remote-debugging-port=" + PORT],
    { detached: true, stdio: "ignore", cwd: path.dirname(EXE), env });
  child.unref();
  let cdp = null;
  const facts = {};
  try {
    let target = null;
    for (let attempt = 0; attempt < 90 && !target; attempt += 1) {
      await sleep(2000);
      try {
        const list = await requestJson("http://127.0.0.1:" + PORT + "/json/list");
        target = list.find((page) => page.type === "page" && /index\.html|renderer/.test(page.url || ""))
          || list.find((page) => page.type === "page" && page.webSocketDebuggerUrl);
      } catch {}
    }
    if (!target) throw new Error("packaged app never surfaced a debuggable page");
    cdp = await connect(target.webSocketDebuggerUrl);
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    let body = "";
    for (let attempt = 0; attempt < 60; attempt += 1) {
      body = String(await evaluate(cdp, "document.body.innerText"));
      if (/1\.279\.\d/.test(body)) break;
      await sleep(1500);
    }
    const versionPattern = new RegExp(WANT_VERSION.replace(/\./g, "\\.") + "[0-9]*", "g");
    facts.versionOnScreen = (body.match(versionPattern) || [])[0] || null;
    if (!facts.versionOnScreen) throw new Error("真窗口里念不出 " + (WANT_VERSION || "当前版本"));

    // 引擎自己的令牌：Electron 把它写在 userData 里（这里就是 --user-data-dir 那一份）。
    let token = "";
    for (let attempt = 0; attempt < 40 && !token; attempt += 1) {
      const file = path.join(PROFILE, "agentcut.token");
      if (fs.existsSync(file)) token = fs.readFileSync(file, "utf-8").trim();
      else await sleep(500);
    }
    if (!token) throw new Error("打包应用的引擎令牌没出现");
    // 基址读窗口自己那句「引擎在线」的悬停说明——那是应用对用户说的同一句事实，不另猜端口。
    let base = "";
    for (let attempt = 0; attempt < 20 && !base; attempt += 1) {
      const title = String(await evaluate(cdp, "(document.querySelector('.conn') || {}).title || ''"));
      const hit = title.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (hit) base = hit[0];
      else await sleep(500);
    }
    if (!base) throw new Error("窗口没说自己的引擎地址");
    facts.engineBase = base;
    facts.engineVersion = (await api(base, token, "/v1/info")).app_version;

    const made = await api(base, token, "/v1/projects", { request_id: "packaged-ui-probe", name: "装机工作台" }, "POST");
    await api(base, token, `/v1/projects/${made.project.id}/edits`, {
      request_id: "packaged-ui-track",
      expected_revision: made.project.revision,
      commands: [{ op: "track.add", track: { id: "v", kind: "video", name: "画面" } }],
    }, "POST");

    // 刷新首页（不要点新建），工程卡片出现之后按命中点真的点开它。
    await evaluate(cdp, "location.reload(); true");
    let opened = false;
    for (let attempt = 0; attempt < 40 && !opened; attempt += 1) {
      await sleep(800);
      const spot = await evaluate(cdp, `(function () {
        var row = document.querySelector('.pt-item');
        if (!row) return null;
        var r = row.getBoundingClientRect();
        return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
      })()`);
      if (spot) {
        await clickAt(cdp, spot.x, spot.y);
        for (let wait = 0; wait < 30; wait += 1) {
          await sleep(500);
          if (await evaluate(cdp, "Boolean(document.querySelector('.editor'))")) { opened = true; break; }
        }
      }
    }
    if (!opened) throw new Error("工程点不开，工作台没出现");
    await sleep(1500);

    facts.editor = await evaluate(cdp, `(function () {
      var host = document.querySelector('.editor');
      var main = document.querySelector('.editor-main');
      var panel = document.querySelector('.editor-main > .panel');
      var timeline = document.querySelector('.editor .timeline');
      var transport = document.querySelector('.transport');
      var wells = document.querySelectorAll('.tl-toolbar .tool-well');
      var heads = document.querySelectorAll('.tl-head:not(.corner) [aria-label]');
      var css = function (node) { return node ? getComputedStyle(node) : null; };
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        panelRadius: panel ? parseFloat(css(panel).borderTopLeftRadius) : 0,
        panelBorder: panel ? css(panel).borderTopWidth : '',
        mathGutter: main ? parseFloat(css(main).paddingLeft) : 0,
        timelineRadius: timeline ? parseFloat(css(timeline).borderTopLeftRadius) : 0,
        transportRadius: transport ? parseFloat(css(transport).borderTopLeftRadius) : 0,
        tools: wells.length,
        trackButtons: heads.length,
        timelineWidth: timeline ? Math.round(timeline.getBoundingClientRect().width) : 0,
        bodyFont: parseFloat(css(document.body).fontSize),
      };
    })()`);
    facts.toolLabels = await evaluate(cdp,
      "Array.from(document.querySelectorAll('.tl-toolbar .tool-well')).map(function(n){return n.getAttribute('aria-label')||'';})");
    facts.trackHeadNames = await evaluate(cdp,
      "Array.from(document.querySelectorAll('.tl-head:not(.corner) [aria-label]')).map(function(n){return n.getAttribute('aria-label');})");

    // 截图是一次「证据」而不是判据本身：真窗口有时在忙时会晚半拍回，重试三次再认输。
    let shot = null;
    for (let attempt = 0; attempt < 3 && !shot; attempt += 1) {
      try {
        shot = await cdp.send("Page.captureScreenshot", { format: "png" }, 60000);
      } catch (error) {
        if (attempt === 2) throw error;
        await sleep(1200);
      }
    }
    if (shot && shot.data) {
      await fs.promises.writeFile(SHOT, Buffer.from(shot.data, "base64"));
    }
    facts.shot = SHOT;
    await fs.promises.writeFile(OUT, JSON.stringify(facts, null, 2), "utf-8");
    console.log("packaged ui probe wrote " + OUT);
  } finally {
    if (cdp) cdp.close();
    try { process.kill(child.pid, "SIGKILL"); } catch {}
    // Electron 会再拉起自己的子进程；按 PID 树收干净，别留下一个占着端口的窗口。
    try {
      require("node:child_process").execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "pipe" });
    } catch {}
  }
}

main().catch((error) => {
  console.error("packaged ui probe failed: " + (error && error.stack ? error.stack : String(error)));
  process.exit(1);
});
