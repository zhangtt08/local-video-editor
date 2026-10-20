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
const EXTRAS = args.reduce((acc, item, index) => (item === "--extra" ? acc.concat(args[index + 1]) : acc), []);
const PROBE = path.resolve(flag("probe", path.join(__dirname, "ui_shape_probe.js")));
// 每一档扫描收尾时若那棵浏览器树还锁着 profile，就把路径记在这儿——量具自己没打扫干净，
// 与「有一屏量不到」是同一类红。
const leaked = [];
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

// 杀干净那一棵浏览器树：`taskkill /T` 打不穿它（Edge 的 crashpad/renderer 会改亲，父进程一没
// 就查不到子树），所以按**这一份 profile 的名字**去点名杀。路径两端的写法不一致
// （主进程是长路径、子进程是 `ADMINI~1` 那种 8.3 短名），故只比对目录名——名字是本脚本自己
// 用 `Date.now().toString(36)` 造的，只有字母数字与短横。
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
    // 检查器里那几段是 `<details>`：合着的时候那一行根本没画到屏幕上（矩形会撒谎），
    // 所以「下拉那一行被切」「灰字叠行」在合着的屏上量不到。--open-details 把每一段真展开再量一次，
    // 1.220 就是这张屏发现「折叠曲线」那一档被竖切在括号前。
    if (flag("open-details", "") !== "") {
      const opened = await evaluate("(function(){var d=document.querySelectorAll('details');"
        + "for(var i=0;i<d.length;i+=1){d[i].open=true;}return d.length;})()");
      await sleep(600);
      await run("展开" + opened + "段");
    }
    for (let t = 0; t < tabs.length; t += 1) {
      if (tabs[t].selected || !tabs[t].x || !tabs[t].y) continue;
      await click(tabs[t].x, tabs[t].y);
      await sleep(700);
      const lit = await evaluate(tabsExpression);
      const now = (lit || []).find((row) => row.i === t) || {};
      if (!now.selected) {
        rows.push({ screen: String(tabs[t].text || tabs[t].label), panel: flag("panel", ""), size, data: null, error: "clicked but the tab never lit" });
        continue;
      }
      await run(String(now.text || now.label));
    }
    // 浮层那一档：先回到编辑器（示波器与动画曲线都住在右侧那一列与编辑器里），
    // 再按名字真点那一颗；点开了才量，点不开就记一条「没开起来」——不许当成跳过。
    const back = (await evaluate(tabsExpression) || []).find((row) => /剪辑|编辑/.test(row.text));
    if (back && EXTRAS.length) {
      await click(back.x, back.y);
      await sleep(600);
    }
    for (const label of EXTRAS) {
      const finder = "(() => { const want = " + JSON.stringify(label) + ";" +
        "const nodes = Array.from(document.querySelectorAll('button, [role=tab]'));" +
        "const hit = nodes.find((n) => (n.textContent || '').trim().indexOf(want) >= 0);" +
        "if (!hit) return null; const r = hit.getBoundingClientRect();" +
        "return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()";
      const spot = await evaluate(finder);
      if (!spot) {
        rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error: "那颗按钮不在这一屏上" });
        continue;
      }
      await click(spot.x, spot.y);
      await sleep(800);
      await run(label);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }, 20000);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }, 20000);
      await sleep(300);
    }
    cdp.close();
  } finally {
    // Windows 上 SIGTERM 打不穿 msedge 那一棵树：留着它，下一档扫描就会撞上同一个 profile
    // 与同一批占着的端口。taskkill /T 才是「这一棵真的没了」。
    // 但**说了杀掉不等于杀掉了**：1.222 在这台机器上量到一次门禁跑完留着 880 个 msedge 进程、
    // 146 份 profile，而上面那行 taskkill 早就在这儿了——事后按 profile 名去查，那一棵还有 8 个
    // 进程活着（父进程已没、子进程改亲，`/T` 查不到；至于是哪一种走漏的没量，也不影响这一判）。
    // 所以杀完要**验**：profile 目录还删得掉，才说明那棵树真的没了（进程活着会锁着它）。
    // 删不掉就报出来，让退出码红。
    try {
      execFileSync("taskkill", ["/PID", String(edge.pid), "/T", "/F"], { stdio: "ignore" });
    } catch {
      try { edge.kill("SIGTERM"); } catch {}
    }
    killByProfile(profile);
    let cleaned = false;
    for (let attempt = 0; attempt < 12 && !cleaned; attempt += 1) {
      try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3 }); } catch {}
      cleaned = !fs.existsSync(profile);
      if (!cleaned) await sleep(250);
    }
    if (!cleaned) {
      console.error("LEAKED profile still held: " + profile);
      leaked.push(profile);
    }
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
    // 浏览器留下的 keep-alive 连接会让这个 node 进程永远不退出（900 秒就是这么烧掉的）。
    if (typeof host.closeAllConnections === "function") host.closeAllConnections();
    host.close();
  }
  fs.writeFileSync(OUT, JSON.stringify(all, null, 1), "utf8");
  const screens = all.filter((row) => row.data).length;
  console.log("screens measured: " + screens + " of " + all.length + " -> " + OUT);
  if (leaked.length) {
    console.error("LEAKED " + leaked.length + " browser tree(s) still holding a profile: " + leaked.join(" "));
    process.exit(1);
  }
  if (!screens) process.exit(1);
  process.exit(0);
}

main().catch((error) => { console.error("sweep failed: " + String(error && error.message ? error.message : error)); process.exit(1); });
