/*
 * 1.278 时间线右键菜单的真页面量具：把渲染层伺服起来（同源代理 /v1 到引擎），用真的鼠标右键
 * 打开菜单，读它画出来的样子与它交出去的那一笔，再把两件只有真 DOM 才量得到的事实收回来：
 *
 *   ① 右键落在没选中的片段上 → 那一段被选中（不是「菜单开了、选中没变」）；
 *   ② 菜单第一次打开时焦点就在第一项上（键盘用户进得去）；Escape 关掉后焦点交回那个片段；
 *   ③ 菜单整个盒子在视口里（右下角打开时翻到指针上方，不许一半在窗口外）；
 *   ④ 点「追加整组副本」→ 引擎 revision 涨一、片段数 +1，菜单自己关掉；
 *   ⑤ 空白处右键是另一份菜单（粘贴 / 全选 / 标记），标题写明是哪一轨。
 *
 *  判定不在这份文件里：这里只负责交回读数与「量到没量到」，判据属于 tests/contextmenu_check.py。
 *
 *   node scripts/ui_menu_probe.cjs --renderer desktop/dist/renderer \
 *     --engine http://127.0.0.1:8765 --token T --project PID --out menu.json
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
const OUT = path.resolve(flag("out", "ui_menu_probe.json"));
const EDGE = flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe");

if (!ENGINE || !TOKEN || !PROJECT) {
  console.error("usage: --engine --token --project are required");
  process.exit(2);
}
if (!fs.existsSync(path.join(RENDERER, "index.html"))) {
  console.error("renderer missing (build it first: cd desktop && npm run build:renderer)");
  process.exit(2);
}
for (const file of [__filename]) execFileSync(process.execPath, ["--check", file], { stdio: "pipe" });

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
  return await response.json();
}

const MENU_READ = `(function () {
  const menu = document.querySelector('[data-ctx-menu="1"]');
  if (!menu) return null;
  const box = menu.getBoundingClientRect();
  const items = Array.from(menu.querySelectorAll('[role="menuitem"]')).map(function (node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return {
      label: (node.querySelector('.ctx-label') || node).textContent.trim(),
      hint: node.querySelector('.ctx-chord') ? node.querySelector('.ctx-chord').textContent.trim() : '',
      disabled: node.disabled === true,
      font: parseFloat(style.fontSize),
      height: Math.round(rect.height),
      x: Math.round(rect.left + rect.width / 2),
      y: Math.round(rect.top + rect.height / 2),
    };
  });
  const title = menu.querySelector('.ctx-title');
  const active = document.activeElement;
  return {
    role: menu.getAttribute('role'),
    label: menu.getAttribute('aria-label'),
    title: title ? title.textContent.trim() : '',
    titleFont: title ? parseFloat(getComputedStyle(title).fontSize) : 0,
    rect: { left: Math.round(box.left), top: Math.round(box.top), right: Math.round(box.right), bottom: Math.round(box.bottom), width: Math.round(box.width), height: Math.round(box.height) },
    radius: parseFloat(getComputedStyle(menu).borderTopLeftRadius),
    items: items,
    focused: active ? (active.getAttribute('role') || active.tagName.toLowerCase()) : '',
    focusedLabel: active && active.querySelector('.ctx-label') ? active.querySelector('.ctx-label').textContent.trim() : '',
    focusedClass: active ? String(active.className || '').slice(0, 70) : '',
    focusedText: active ? String(active.textContent || '').trim().slice(0, 40) : '',
  };
})()`;

// 菜单刚挂上去时，自动聚焦要等一次 React 提交；满载的机器上那一下会慢半拍，
// 所以读之前先等焦点真的落到菜单项上，而不是读一次就判红。上限从两秒放宽到八秒：
// 1.319 整套验收里这一格红过一次（焦点还停在片段上，而那一段的缩略图正在解码），
// 单独重跑就过——两秒不够一台正在满载的机器把一次 React 提交排完。
// 等不到位照样红，只是交回的读数里现在写着等了多久。
async function readMenuSettled(read) {
  const started = Date.now();
  let result = await read();
  for (let wait = 0; wait < 80 && !(result && result.focused === "menuitem"); wait += 1) {
    await sleep(100);
    result = await read();
  }
  if (result) result.settledInMs = Date.now() - started;
  return result;
}

async function main() {
  const [width, height] = SIZE.split("x").map(Number);
  const hostPort = await freePort(8840);
  const debugPort = await freePort(9930);
  const host = await startHost(hostPort);
  const profile = path.join(os.tmpdir(), "agentcut-menu-" + Date.now().toString(36));
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
      const clips = await evaluate("document.querySelectorAll('.clip[data-id]').length");
      if (clips > 0) break;
      await sleep(300);
    }
    facts.clipsOnScreen = await evaluate("document.querySelectorAll('.clip[data-id]').length");
    const clip = await evaluate(`(function () {
      const node = document.querySelector('.clip[data-id]');
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return { id: node.getAttribute('data-id'), pressed: node.getAttribute('aria-pressed'),
        rect: { left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) } };
    })()`);
    if (!clip) throw new Error("no clip on screen");
    facts.clip = clip;
    const before = await projectState();
    facts.before = { revision: before.revision ?? before.project?.revision, clips: Object.keys(before.project?.clips ?? before.clips ?? {}).length };

    const click = async (x, y, button) => {
      const buttons = button === "right" ? 2 : 1;
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, buttons, clickCount: 1 });
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, buttons, clickCount: 1 });
    };
    const key = async (keyName, code) => {
      const vk = keyName === "Escape" ? 27 : keyName === "ArrowDown" ? 40 : keyName === "ArrowUp" ? 38 : 0;
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: keyName, code, windowsVirtualKeyCode: vk }, 20000);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: keyName, code, windowsVirtualKeyCode: vk }, 20000);
    };

    // ① 真鼠标右键：菜单画出来、焦点在第一项、那一段被选中。
    // 矩形要在**按下去的那一刻**量：缩略图解码完会把轨道行长高，早先测的那一份 rect 会把点
    // 落到片段外面——菜单画不出来，而读数量到的只是「没有菜单」，看不出自己点错了地方。
    // 所以按之前先确认这一点真的落在这段 clip 上，落不到就重测（最多五秒），并把点到的东西交回。
    const safeId = String(clip.id || '');
    if (!/^[A-Za-z0-9_.-]{1,64}$/.test(safeId)) throw new Error('unexpected clip id: ' + safeId);
    const centreOf = `(function () {
      const node = document.querySelector('.clip[data-id=\"${safeId}\"]');
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      const x = Math.round(rect.left + rect.width / 2);
      const y = Math.round(rect.top + rect.height / 2);
      const hit = document.elementFromPoint(x, y);
      const owner = hit && hit.closest ? hit.closest('.clip[data-id]') : null;
      return { x: x, y: y, hit: owner ? owner.getAttribute('data-id') : String(hit ? hit.className : 'none') };
    })();`;
    let spot = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      spot = await evaluate(centreOf);
      if (spot && spot.hit === clip.id) break;
      await sleep(250);
    }
    if (!spot) throw new Error("clip left the screen: " + clip.id);
    facts.rightClickAt = { x: spot.x, y: spot.y };
    facts.rightClickHit = spot.hit;
    // 关掉菜单有五只手（pointerdown / contextmenu / wheel / resize / blur）。看不见是哪一只
    // 关的，就只能猜「菜单没画出来」——所以在按下去之前把五只手都记下账。
    await evaluate(`window.__triggers = []; window.__t0 = performance.now();
      [['pointerdown', document], ['contextmenu', document], ['wheel', document],
       ['resize', window], ['blur', window]].forEach(function (pair) {
        pair[1].addEventListener(pair[0], function (event) {
          if (window.__triggers.length > 24) return;
          const node = event.target;
          window.__triggers.push({ kind: pair[0], ms: Math.round(performance.now() - window.__t0),
            on: String((node && (node.className || node.tagName)) || 'none').slice(0, 40) });
        }, true);
      }); 0`);
    await click(spot.x, spot.y, "right");
    await sleep(350);
    // 菜单在 window blur 时自己关掉（人把焦点挪走就是这个语义）。这台机器上会有别的会话抢前台，
    // headless 的窗口因此可能「刚画出来就被关掉」——那不是被测件的缺陷，是量具没把「页面有焦点」
    // 当成前提。所以：拿不到菜单就先看清焦点、把窗口提到前面再按一次，并把试了几次交回。
    facts.menuAttempts = 0;
    facts.menuTrail = [];
    facts.menu = null;
    for (let attempt = 0; attempt < 6 && !facts.menu; attempt += 1) {
      facts.menuAttempts += 1;
      if (attempt > 0) {
        // 上一轮被 blur 关掉了：把窗口提到前面、拿回焦点，再按一次。
        await cdp.send("Page.bringToFront");
        await evaluate("window.focus()");
        const back = await evaluate(centreOf);
        await click((back || spot).x, (back || spot).y, "right");
        await sleep(300);
      }
      facts.menu = await readMenuSettled(() => evaluate(MENU_READ));
      facts.menuTrail.push({
        attempt: facts.menuAttempts,
        menu: facts.menu ? 'box' : null,
        focus: await evaluate("document.hasFocus()"),
        triggers: await evaluate("(window.__triggers || []).slice(-3)"),
      });
    }
    facts.windowFocused = await evaluate("document.hasFocus()");
    facts.triggers = await evaluate("window.__triggers || []");
    if (!facts.menu) {
      throw new Error("菜单一次都没能留住（这台机器上有别的应用在抢前台焦点）；最后几次读数 "
        + JSON.stringify(facts.menuTrail).slice(-420));
    }    facts.selectedAfterRightClick = await evaluate("document.querySelectorAll('.clip[data-id][aria-pressed=\"true\"]').length");
    facts.clipPressedAfterRightClick = await evaluate(`(document.querySelector('.clip[data-id="${clip.id}"]') || {}).getAttribute && document.querySelector('.clip[data-id="${clip.id}"]').getAttribute('aria-pressed')`);

    // ② 按方向键真的在能按的项之间走。
    await key("ArrowDown", "ArrowDown");
    await sleep(120);
    facts.afterArrowDown = await evaluate("document.activeElement && document.activeElement.querySelector('.ctx-label') ? document.activeElement.querySelector('.ctx-label').textContent.trim() : ''");
    await key("ArrowUp", "ArrowUp");
    await sleep(120);
    facts.afterArrowUp = await evaluate("document.activeElement && document.activeElement.querySelector('.ctx-label') ? document.activeElement.querySelector('.ctx-label').textContent.trim() : ''");

    // ③ 点「追加整组副本」：一条真命令，菜单自己关掉，引擎那一头涨一个版本。
    const duplicate = (facts.menu?.items || []).find((item) => item.label.indexOf("副本") >= 0);
    if (!duplicate) throw new Error("no duplicate entry in the menu: " + JSON.stringify(facts.menu));
    facts.duplicateItem = duplicate;
    await click(duplicate.x, duplicate.y, "left");
    await sleep(900);
    facts.menuAfterRun = await evaluate(MENU_READ);
    const after = await projectState();
    facts.after = { revision: after.revision ?? after.project?.revision, clips: Object.keys(after.project?.clips ?? after.clips ?? {}).length };

    // ④ 再开一次，Escape 关掉，焦点交回那个片段。矩形照样当场重测（上面那一手刚加过一段）。
    const againSpot = await evaluate(centreOf);
    await click((againSpot || spot).x, (againSpot || spot).y, "right");
    await sleep(300);
    facts.menuBeforeEscape = await evaluate(MENU_READ);
    await key("Escape", "Escape");
    await sleep(250);
    facts.menuAfterEscape = await evaluate(MENU_READ);
    facts.focusAfterEscape = await evaluate("(document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-id')) || document.activeElement.tagName.toLowerCase()");

    // ⑤ 空白处：真的点在一片没有片段的地方。时间线现在只占「素材 + 监视器」那两列，
    // 空白尾段常在可视区之外——先滚到最右，找一格命中点确实是轨道的，量完再滚回 0。
    await evaluate("var s=document.querySelector('.tl-scroll'); if(s){s.scrollLeft=s.scrollWidth;} true");
    await sleep(350);
    let laneSpot = await evaluate(`(function () {
      const lanes = Array.from(document.querySelectorAll('.tl-lane[data-track-id]'));
      for (const lane of lanes) {
        const rect = lane.getBoundingClientRect();
        const top = Math.max(rect.top, 0), bottom = Math.min(rect.bottom, window.innerHeight);
        if (bottom - top < 20) continue;
        for (let x = Math.round(Math.max(rect.left, 0)) + 120; x < Math.min(rect.right, window.innerWidth) - 20; x += 24) {
          const y = Math.round((top + bottom) / 2);
          const hit = document.elementFromPoint(x, y);
          if (hit === lane) return { x: x, y: y, track: lane.getAttribute('data-track-id') };
        }
      }
      const lanes2 = Array.from(document.querySelectorAll('.tl-lane[data-track-id]'));
      const sample = lanes2.slice(0, 3).map(function (lane) {
        const r = lane.getBoundingClientRect();
        const y = Math.round((Math.max(r.top, 0) + Math.min(r.bottom, window.innerHeight)) / 2);
        const hits = [];
        for (let x = Math.round(Math.max(r.left, 0)) + 120; x < Math.min(r.right, window.innerWidth) - 20; x += 120) {
          const el = document.elementFromPoint(x, y);
          hits.push(x + ':' + (el ? el.tagName + '.' + String(el.className || '').slice(0, 18) : 'null'));
        }
        return { rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], hits: hits };
      });
      return { none: true, lanes: lanes2.length, sample: sample };
    })()`);
    if (laneSpot && laneSpot.none) facts.laneDebug = laneSpot;
    if (laneSpot && laneSpot.none) laneSpot = null;
    facts.laneSpot = laneSpot;
    if (laneSpot) {
      await click(laneSpot.x, laneSpot.y, "right");
      await sleep(300);
      facts.laneMenu = await readMenuSettled(() => evaluate(MENU_READ));
      await key("Escape", "Escape");
      await sleep(150);
    }

    // ⑥ 轨道头：「更多」那颗按钮打开同一份浮层；轨道名进标题，三颗按钮就够了。
    facts.trackHeadButtons = await evaluate("document.querySelectorAll('.tl-head [aria-label]').length");
    const trackButton = await evaluate(`(function () {
      const btn = document.querySelector('.tl-head [aria-label="这条轨的其它操作"]');
      if (!btn) return null;
      const r = btn.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    })()`);
    facts.trackButton = trackButton;
    if (trackButton) {
      await click(trackButton.x, trackButton.y, "left");
      await sleep(300);
      facts.trackMenu = await readMenuSettled(() => evaluate(MENU_READ));
      await key("Escape", "Escape");
      await sleep(150);
      facts.trackMenuAfterEscape = await evaluate(MENU_READ);
    }

    // ⑦ 夹在视口里：在右下角那一格按下右键，菜单要翻到指针上方，整个盒子仍在窗口内。
    await evaluate(`(function () {
      const node = document.querySelector('.clip[data-id]');
      if (!node) return false;
      node.dispatchEvent(new MouseEvent('contextmenu', {
        bubbles: true, cancelable: true, view: window,
        clientX: window.innerWidth - 4, clientY: window.innerHeight - 4,
      }));
      return true;
    })()`);
    await sleep(300);
    facts.cornerMenu = await readMenuSettled(() => evaluate(MENU_READ));
    facts.cornerTarget = await evaluate("({ w: window.innerWidth, h: window.innerHeight })");
    await key("Escape", "Escape");
    // 机器忙时 React 的卸载会慢一拍：等它真的落定（最多两秒），而不是死等 150 毫秒再认输。
    let settledMs = null;
    for (let wait = 1; wait <= 20 && settledMs === null; wait += 1) {
      await sleep(100);
      if ((await evaluate(MENU_READ)) === null) settledMs = wait * 100;
    }
    facts.menuDismissedMs = settledMs;
    facts.menuAtEnd = await evaluate(MENU_READ);
  } finally {
    if (cdp) cdp.close();
    try { edge.kill(); } catch {}
    killByProfile(profile);
    try { host.close(); } catch {}
    fs.writeFileSync(OUT, JSON.stringify(facts, null, 2), "utf-8");
  }
  console.log("probe wrote " + OUT);
}

main().catch((error) => {
  console.error("probe failed: " + (error && error.stack ? error.stack : String(error)));
  process.exit(1);
});
