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
const { execFileSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const REPO = path.resolve(__dirname, "..");
const flag = (name, fallback) => {
  const at = process.argv.indexOf("--" + name);
  return at >= 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
};
const EXE = path.resolve(flag("exe", path.join(REPO, "desktop/release/win-unpacked/AgentCut.exe")));
// 1.315：外壳拉起引擎用的是 `desktop --port 0`（main.ts 那一行），而 census 过去只认
// `api --port`——于是「关掉之后一台引擎都不许留」这一条永远数不到引擎，绿得没有根据。
// 两种模式都认，且只认那一个可执行文件名的进程：node 的命令行里带着 --exe …\AgentCut.exe，
// 按命令行找会把量具自己数进去。
const ENGINE_LINE = /agentcut\.exe"?\s+(?:desktop|api)\s+--port/i;
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
  // 1.315：同一趟 census 多要一列 WorkingSetSize。计数故意不数 Electron 的帮助进程
  // （--type=…），但**占用必须**把它们算进外壳合计——拿只数主进程的那套去报 MB，
  // 读数会少一大截，那正是「数错=假绿」。引擎按 ImageName + 「 api --port」认，
  // 与关掉之后那次数法同一口径。
  const memoryOnce = function () {
    const census = "Get-CimInstance -Query \"select Name,WorkingSetSize,CommandLine"
      + " from Win32_Process\" | ForEach-Object { \"{0}={1}={2}\" -f $_.Name, "
      + "$_.WorkingSetSize, $_.CommandLine }";
    const listed = execFileSync("powershell", ["-NoProfile", "-Command", census],
      { encoding: "utf8" });
    let shellBytes = 0;
    let helperBytes = 0;
    let engineBytes = 0;
    let shellProcs = 0;
    let helperProcs = 0;
    let engineProcs = 0;
    for (const line of listed.split(/\r?\n/)) {
      const first = line.indexOf("=");
      const second = line.indexOf("=", first + 1);
      if (first < 0 || second < 0) continue;
      const name = line.slice(0, first);
      const bytes = Number(line.slice(first + 1, second)) || 0;
      const command = line.slice(second + 1);
      if (name === "agentcut.exe" && ENGINE_LINE.test(command)) {
        engineProcs += 1;
        engineBytes += bytes;
      } else if (name === "AgentCut.exe" && / --type=/.test(command)) {
        helperProcs += 1;
        helperBytes += bytes;
      } else if (name === "AgentCut.exe") {
        shellProcs += 1;
        shellBytes += bytes;
      }
    }
    const mb = (value) => Math.round((value / 1048576) * 10) / 10;
    return {
      shellMb: mb(shellBytes + helperBytes),
      shellMainMb: mb(shellBytes),
      helperMb: mb(helperBytes),
      engineMb: mb(engineBytes),
      totalMb: mb(shellBytes + helperBytes + engineBytes),
      shellProcs,
      helperProcs,
      engineProcs,
    };
  };
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
    // 1.308 的第一笔账：窗口打开那一刻，界面直接是外壳，没有那块「正在启动本地引擎」的全屏门，
    // 也没有一台引擎被替用户拉起来。令牌由引擎自己写进 user-data-dir——它不在场，才是
    // 「进程真没起」的证据；只看窗口里没有进度条是不够的。
    // 1.317：这一笔过去是「连上就读一次」。整套验收里它红过一次：3.1 秒就答了
    // `{"shell":false,…}`——CDP 连上时页面还没挂载，读到的是一张空页。先等外壳出现再读，
    // 读的仍是「打开那一刻」那一份快照（等的是挂载，不是等引擎）。
    let openState = "{}";
    for (let wait = 0; wait < 80; wait += 1) {
      openState = String(await evaluate(cdp, `(function () {
      var frame = document.querySelector(".app-frame");
      var box = frame ? frame.getBoundingClientRect() : null;
      var title = document.querySelector(".start-title");
      var head = title ? title.getBoundingClientRect() : null;
      return JSON.stringify({
        shell: Boolean(frame),
        shellWidth: box ? Math.round(box.width) : 0,
        bootScreen: Boolean(document.querySelector(".boot-screen")),
        skeleton: document.querySelectorAll(".pt-bar").length,
        headX: head ? Math.round(head.left + head.width / 2) : 0,
        headY: head ? Math.round(head.top + head.height / 2) : 0,
      });
    })()`));
      const seen = JSON.parse(openState);
      if (seen.shell) break;
      await sleep(250);
    }
    const atOpen = JSON.parse(openState);
    facts.openState = atOpen;
    // 外壳什么时候**真画出来**：不看 DOM 里有没有那个节点，而是拿中点做命中测试——
    // 节点在场但没画出来（或被折叠）是两回事。FCP 这类 paint 条目在这个页面量不到，
    // 所以量的是「performance.now() 到哪一秒中点开始落在外壳里」。
    let paintedMs = null;
    for (let wait = 0; wait < 160 && paintedMs === null; wait += 1) {
      paintedMs = await evaluate(cdp, `(function () {
        var frame = document.querySelector(".app-frame");
        if (!frame) return null;
        var b = frame.getBoundingClientRect();
        var hit = document.elementFromPoint(Math.round(b.left + b.width / 2), Math.round(b.top + b.height / 2));
        return (hit && frame.contains(hit)) ? Math.round(performance.now()) : null;
      })()`);
      if (paintedMs === null) await sleep(25);
    }
    facts.shellPaintedMs = paintedMs;
    const paint = JSON.parse(String(await evaluate(cdp, `(function () {
      var nav = performance.getEntriesByType("navigation")[0] || {};
      return JSON.stringify({
        firstContentfulPaintMs: Math.round((performance.getEntriesByName("first-contentful-paint")[0] || {}).startTime || 0),
        domReadyMs: Math.round(nav.domContentLoadedEventEnd || 0),
        lookedAtMs: Math.round(performance.now()),
      });
    })()`)));
    facts.paint = paint;
    if (!atOpen.shell || atOpen.bootScreen) {
      throw new Error("打开窗口那一下该直接出外壳、不带全屏门：" + openState);
    }
    if (fs.existsSync(path.join(PROFILE, "agentcut.token"))) {
      // 1.315：这一条在第一趟 1.315 装机腿里红过一次，第二次又绿——先让它红得带证据：
      // 令牌什么时候写的、那一刻机器上有几台引擎、各自多大。
      let evidence = "";
      try {
        const seen = memoryOnce();
        const when = fs.statSync(path.join(PROFILE, "agentcut.token")).mtime.toISOString();
        evidence = " | token mtime " + when + " | census " + JSON.stringify(seen);
      } catch (censusError) {
        evidence = " | census failed: " + censusError;
      }
      throw new Error("用户还没真使用，引擎令牌就写出来了：说明开机就拉起了进程" + evidence);
    }
    // 用户还没真用的那一刻：外壳与它的帮助进程都在，引擎那一列必须是 0。
    facts.memoryIdle = memoryOnce();
    // 第一次真使用：一次真指针落在首页标题那一行（那里没有可点的控件），引擎这才在后台起来。
    if (!atOpen.headX || !atOpen.headY) throw new Error("首页标题没画出来：外壳不是预期那一屏");
    const pressedAt = Date.now();
    await clickAt(cdp, atOpen.headX, atOpen.headY);
    let firstUseMs = null;
    for (let wait = 0; wait < 120 && firstUseMs === null; wait += 1) {
      await sleep(100);
      const landed = await evaluate(cdp, "Boolean(document.querySelector('.pt-item')"
        + " || document.querySelector('.start-empty'))");
      if (String(landed) === "true") firstUseMs = Date.now() - pressedAt;
    }
    facts.firstUseToListMs = firstUseMs;
    // 真用过之后：给后台那台引擎一点时间把模型与索引起来，再称一次。
    await sleep(1500);
    facts.memoryAfterUse = memoryOnce();

    let body = "";
    // 1.291：版本号不再画在界面上（「引擎在线 v1.290.0」那种小字正是被删掉的东西），
    // 但装机包跑的到底是不是这一版，必须还能核对。构建标记写在 `<html data-app-version>`
    // 上，由 capabilities 落地那一处贴上去——所以这里认的是它，不是屏幕上的一行字。
    // 顺带修掉一枚过期探针：原来那句写死等 1.279.x，从 1.280 起永远等不到，
    // 每一趟都白跑满 60 次 × 1.5 秒（90 秒）才继续。
    const wantVersion = String(WANT_VERSION || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    let marker = "";
    for (let attempt = 0; attempt < 60; attempt += 1) {
      marker = String(await evaluate(
        cdp,
        "document.documentElement.dataset.appVersion || ''",
      ));
      body = String(await evaluate(cdp, "document.body.innerText"));
      if (wantVersion && marker.startsWith(WANT_VERSION)) break;
      await sleep(1500);
    }
    facts.versionMarker = marker;
    facts.versionOnScreen = wantVersion && marker.startsWith(WANT_VERSION) ? marker : null;
    if (!facts.versionOnScreen) {
      throw new Error(
        "真窗口里没有这一版的构建标记（<html data-app-version>）：想要 "
        + (WANT_VERSION || "当前版本") + "，量到的是 " + (marker || "空"),
      );
    }

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
    const reloadedAt = Date.now();
    await evaluate(cdp, "location.reload(); true");
    let reattachMs = null;
    for (let wait = 0; wait < 30 && reattachMs === null; wait += 1) {
      await sleep(200);
      const rows = Number(await evaluate(cdp, "document.querySelectorAll('.pt-item').length || 0"));
      if (rows > 0) reattachMs = Date.now() - reloadedAt;
    }
    facts.reloadToListMs = reattachMs;
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
          if (await evaluate(cdp, "Boolean(document.querySelector('.editor2'))")) { opened = true; break; }
        }
      }
    }
    if (!opened) throw new Error("工程点不开，工作台没出现");
    await sleep(1500);

    facts.editor = await evaluate(cdp, `(function () {
      var host = document.querySelector('.editor2');
      var main = host;
      var panel = document.querySelector('.ed-assets > .panel');
      var timeline = document.querySelector('.ed-timeline');
      var transport = document.querySelector('.transport');
      var wells = document.querySelectorAll('.tl-toolbar .tool-well');
      var heads = document.querySelectorAll('.tl-head:not(.corner) [aria-label]');
      var css = function (node) { return node ? getComputedStyle(node) : null; };
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        panelRadius: panel ? parseFloat(css(panel).borderTopLeftRadius) : 0,
        panelBorder: panel ? css(panel).borderTopWidth : '',
        mathGutter: main ? parseFloat(css(main).columnGap) : 0,
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
    // 1.309：点「关闭」之后不该留一台引擎。先让窗口自己走关掉那一路（与用户点 X 同一条），
    // 再当场数一遍机器上的 agentcut.exe——只杀引导进程会留下一台约 72 MB 的孤儿。
    await evaluate(cdp, "window.desktop.control(\"close\"); true");
    await sleep(5000);
    // 数的是引擎，不是外壳：Windows 的进程名匹配不分大小写，`agentcut.exe` 这个过滤会把
    // AgentCut.exe（外壳）一起算进来；更糟的是**按命令行找会把量具自己数进去**（node 的命令行里
    // 就带着 --exe …\AgentCut.exe）。所以这里认的是进程自己的 ImageName，命令行只用来分「哪一台引擎」。
    // 引擎那一台要**当场**就是 0（关掉软件不该留它，不给宽限）；便携版的外壳有自己的收尾，
    // 所以只给它一条有上限的路：数到 20 秒还在，就是真没退干净。
    const censusOnce = function () {
      const census = "Get-CimInstance -Query \"select Name,CommandLine from Win32_Process\""
        + " | ForEach-Object { \"{0}={1}\" -f $_.Name, $_.CommandLine }";
      const listed = execFileSync("powershell", ["-NoProfile", "-Command", census], { encoding: "utf8" });
      let engine = 0;
      let shell = 0;
      for (const line of listed.split(/\r?\n/)) {
        const name = line.slice(0, line.indexOf("="));
        const command = line.slice(line.indexOf("=") + 1);
        if (name === "agentcut.exe" && ENGINE_LINE.test(command)) engine += 1;
        else if (name === "AgentCut.exe" && !/ --type=/.test(command)) shell += 1;
      }
      return { engine, shell };
    };
    let engineLeft = -1;
    let shellLeft = -1;
    let censusWaitMs = -1;
    try {
      const first = censusOnce();
      engineLeft = first.engine; // 引擎那一台：不留宽限，第一次数到几就是几
      shellLeft = first.shell;
      for (let wait = 0; wait < 20 && shellLeft > 0; wait += 1) {
        await sleep(1000);
        const again = censusOnce();
        shellLeft = again.shell;
        engineLeft = Math.max(engineLeft, again.engine);
        censusWaitMs = (wait + 1) * 1000;
      }
    } catch {
      /* 数不了就留 -1，门禁那一头会把它当失败 */
    }
    facts.engineAfterQuit = engineLeft;
    facts.shellAfterQuit = shellLeft;
    facts.censusWaitMs = censusWaitMs;
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
