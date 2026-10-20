/*
 * 两端对比的照片腿（1.222）：把渲染层伺服起来（同源代理 /v1 到引擎），深链进那个工程，
 * 只把 `.masked-picture` 那一格拍成一张 PNG，并交出它的矩形、遮罩层数与「铺没铺满」。
 *
 *   node scripts/two_end_shot.cjs --renderer desktop/dist/renderer \
 *     --engine http://127.0.0.1:8765 --token T --project PID --clip CID --out preview.png
 *
 * 这一档存在的理由：1.221 那轮「浏览器那一腿只证到 computed style」是**证据的缺口**——
 * 遮罩在导出里是乘起来的 alpha，在预览里是叠起来的 mask-image，两边到底是不是同一个洞，
 * 只有拍到同一格画面的像素才算证过。`--headless=new` 的 Edge 加 CDP `Page.captureScreenshot`
 * 是这台机器上实测能出图的那条腿（`scripts/ui_shape_sweep.cjs` 的 `--shots` 早就在用），
 * 而 `msedge --screenshot` 那个命令行写法不出图。
 *
 * 拍之前先证明那一格值得拍：矩形面积>0（1.218 量到过 0x0 的遮罩层）、图解码完了、
 * 遮罩层数等于引擎交下来的张数、画面**铺满**了格子（`object-fit: contain` 在上下有黑边时
 * 会把「画面坐标」与「遮罩坐标」错开一截，那种照片两端比不得），而且不许有遮罩编辑的
 * 参考线混进来（参考线是界面给人在看的，导出里没有它）。
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
const CLIP = flag("clip", "");
const OUT = path.resolve(flag("out", "two_end_preview.png"));
const SIZE = (flag("size", "1456x808") || "").split("x").map(Number);
const LAYERS = Number(flag("layers", "1"));
// 清单交了几段表、几段矩阵、每张表几项——传进来就判，不传就不判（平色那一趟不判）。
const TABLES = flag("tables", "") === "" ? null : Number(flag("tables", ""));
const MATRICES = flag("matrices", "") === "" ? null : Number(flag("matrices", ""));
const TABLE_VALUES = flag("table-values", "") === "" ? null : Number(flag("table-values", ""));
// `--strip 8,20,34` 给一串平色：这一趟不拍画面，拍「产品自己那张滤镜作用在平色上」的一排格子。
const STRIP = (flag("strip", "") || "").split(",").filter((v) => v !== "").map(Number);
const EDGE = flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!ENGINE || !TOKEN || !PROJECT || !CLIP) {
  console.error("usage: --renderer --engine --token --project --clip --out are required");
  process.exit(2);
}
if (!fs.existsSync(path.join(RENDERER, "index.html"))) {
  console.error("renderer missing (build it first: cd desktop && npm run build:renderer): " + RENDERER);
  process.exit(2);
}
if (!fs.existsSync(EDGE)) {
  console.error("no browser to shoot with: " + EDGE + " (set --edge)");
  process.exit(2);
}

// 杀干净那一棵浏览器树：`taskkill /T` 打不穿它（Edge 的 crashpad/renderer 会改亲），
// 所以按这一份 profile 的名字点名杀；只比对目录名，因为主进程是长路径、子进程是 `ADMINI~1`
// 那种 8.3 短名。名字是本脚本自己用 Date.now().toString(36) 造的，只有字母数字与短横。
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
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".ico": "image/x-icon",
  ".map": "application/json",
};

// 同源：/v1 转给引擎，别的都是渲染层的文件。照片腿不许为了一次比对去处理跨域。
function startHost(port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://127.0.0.1");
      if (url.pathname.startsWith("/v1/") || url.pathname === "/healthz") {
        const upstream = http.request(
          ENGINE.replace(/\/$/, "") + req.url,
          { method: req.method, headers: Object.assign({}, req.headers, { host: new URL(ENGINE).host }) },
          (reply) => { res.writeHead(reply.statusCode || 502, reply.headers); reply.pipe(res); }
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
    socket.addEventListener("error", () => reject(new Error("CDP socket error for " + webSocketUrl)));
  });
}

// 一次问清：那一格在哪、有几层遮罩、图解码完没有、画面铺满格子没有。
const WAIT = `(function(){
  var el = document.querySelector('.masked-picture');
  if (!el) return {state: 'no-layer'};
  var r = el.getBoundingClientRect();
  var cs = getComputedStyle(el);
  var layers = (cs.maskImage || cs.webkitMaskImage || 'none')
    .split(/,(?![^(]*\\))/)
    .filter(function (s) { var v = s.trim(); return v !== '' && v !== 'none'; }).length;
  var media = el.querySelector('img, video, canvas');
  var natural = media ? (media.tagName === 'CANVAS' ? [media.width, media.height]
    : [media.naturalWidth || media.videoWidth || 0, media.naturalHeight || media.videoHeight || 0]) : [0, 0];
  var loaded = !media || (media.tagName === 'VIDEO'
    ? (media.readyState >= 2 && natural[0] > 0)
    : (media.complete && natural[0] > 0));
  var m = media ? media.getBoundingClientRect() : r;
  var aspect = function (w, h) { return h > 0 ? w / h : 0; };
  var fill = natural[0] > 0 && r.width > 0 &&
    Math.abs(m.width - r.width) <= 1.5 && Math.abs(m.height - r.height) <= 1.5 &&
    Math.abs(aspect(natural[0], natural[1]) - aspect(r.width, r.height)) <= 0.01;
  // 预览那几张表**只从清单来**：数一数量到的滤镜里有几段表、几段矩阵、每张表几项。
  // 像素那一判比的是数值，看不见「多了一段/少了一段但数值恰好没变」；这一判看得见。
  var grade = Array.prototype.filter.call(document.querySelectorAll('filter'), function (f) {
    return f.getElementsByTagName('feComponentTransfer').length
      + f.getElementsByTagName('feColorMatrix').length > 0;
  });
  var tables = 0, matrices = 0, sizes = [];
  grade.forEach(function (f) {
    tables += f.getElementsByTagName('feComponentTransfer').length;
    matrices += f.getElementsByTagName('feColorMatrix').length;
    Array.prototype.forEach.call(f.getElementsByTagName('feFuncR'), function (el) {
      sizes.push((el.getAttribute('tableValues') || '').trim().split(/\\s+/).filter(Boolean).length);
    });
  });
  return {state: 'seen',
    rect: {x: r.x, y: r.y, width: r.width, height: r.height},
    mask_layers: layers,
    grade_ids: grade.map(function (f) { return f.id; }),
    tables: tables, matrices: matrices, table_sizes: sizes,
    mask_composite: cs.maskComposite || cs.webkitMaskComposite || '',
    media: media ? media.tagName.toLowerCase() : 'none',
    natural: natural, loaded: loaded, fill: fill,
    guide: Boolean(document.querySelector('.mask-guide'))};
})()`;

// 平色那一排：把**产品自己那张滤镜**贴到一整排平色块上，块与块之间留缝。
// 斜坡那一趟量的是「缩放之后的画面」，这一趟量的是「滤镜本身」——没有任何重采样掺进来。
const STRIP_BUILD = (levels) => `(function(){
  var f = document.querySelector('filter');
  if (!f) return {error: '页面上没有 <filter>'};
  var old = document.getElementById('two-end-strip');
  if (old) old.remove();
  var box = document.createElement('div');
  box.id = 'two-end-strip';
  box.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;white-space:nowrap;' +
    'line-height:0;font-size:0;background:#000;padding:0;margin:0';
  ${JSON.stringify(levels)}.forEach(function (v) {
    var out = document.createElement('div');
    out.style.cssText = 'display:inline-block;vertical-align:top;width:40px;height:40px;margin:0;' +
      'background:rgb(' + v + ',' + v + ',' + v + ');filter:url(#' + f.id + ')';
    box.appendChild(out);
  });
  document.body.appendChild(box);
  return {filter_id: f.id, cells: ${JSON.stringify(levels)}.length,
    primitives: Array.prototype.map.call(f.children, function (p) { return p.tagName; })};
})()`;

async function main() {
  const hostPort = await freePort(12900 + (process.pid % 400));
  const debugPort = await freePort(9900 + (process.pid % 300));
  const profile = path.join(os.tmpdir(), "agentcut-two-end-" + Date.now().toString(36));
  const url = "http://127.0.0.1:" + hostPort + "/index.html?engine=http%3A%2F%2F127.0.0.1%3A" + hostPort +
    "&token=" + encodeURIComponent(TOKEN) + "&project=" + encodeURIComponent(PROJECT) +
    "&clip=" + encodeURIComponent(CLIP);
  const host = await startHost(hostPort);
  const edge = spawn(
    EDGE,
    ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--remote-debugging-port=" + debugPort, "--window-size=" + SIZE[0] + "," + SIZE[1],
      "--user-data-dir=" + profile, url],
    { stdio: "ignore" }
  );
  let code = 0;
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
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: SIZE[0], height: SIZE[1], deviceScaleFactor: 1, mobile: false });
    const evaluate = async (expression) => {
      const answer = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, 30000);
      if (answer.exceptionDetails) throw new Error("probe threw: " + JSON.stringify(answer.exceptionDetails).slice(0, 300));
      return answer.result ? answer.result.value : null;
    };
    let seen = null;
    let last = null;
    for (let attempt = 0; attempt < 150 && !seen; attempt += 1) {
      last = await evaluate(WAIT);
      if (last && last.state === "seen" && last.loaded && last.fill && !last.guide &&
          last.rect.width * last.rect.height > 4096 && last.mask_layers >= LAYERS) seen = last;
      else await sleep(200);
    }
    if (!seen) throw new Error("那一格没有画到位：" + JSON.stringify(last).slice(0, 400));
    if (seen.mask_layers !== LAYERS) {
      throw new Error("遮罩层数是 " + seen.mask_layers + "，引擎交的是 " + LAYERS + " 张图");
    }
    // 预览那几张表只从清单来：段数、类型、每张表的项数，一条一条对。
    if (TABLES !== null && seen.tables !== TABLES) {
      throw new Error("预览画了 " + seen.tables + " 段表，清单交的是 " + TABLES
        + " 段（滤镜 id：" + JSON.stringify(seen.grade_ids) + "）");
    }
    if (MATRICES !== null && seen.matrices !== MATRICES) {
      throw new Error("预览画了 " + seen.matrices + " 段矩阵，清单交的是 " + MATRICES
        + " 段（滤镜 id：" + JSON.stringify(seen.grade_ids) + "）");
    }
    if (TABLE_VALUES !== null && seen.table_sizes.some((n) => n !== TABLE_VALUES)) {
      throw new Error("有表的 tableValues 不是 " + TABLE_VALUES + " 项，实测 "
        + JSON.stringify(seen.table_sizes));
    }
    if (STRIP.length) {
      // 平色那一趟：不拍 `.masked-picture`，拍刚铺出来的那一排格子。
      const built = await evaluate(STRIP_BUILD(STRIP));
      if (!built || built.error) throw new Error("平色格子铺不出来：" + JSON.stringify(built));
      await sleep(400);
      const strip = await cdp.send("Page.captureScreenshot", {
        format: "png",
        clip: { x: 0, y: 0, width: 40 * STRIP.length, height: 40, scale: 1 },
        captureBeyondViewport: false,
      }, 30000);
      if (!strip || !strip.data) throw new Error("CDP 回了没有图（平色）");
      fs.mkdirSync(path.dirname(OUT), { recursive: true });
      fs.writeFileSync(OUT, Buffer.from(strip.data, "base64"));
      console.log(JSON.stringify({ out: OUT, strip: built, levels: STRIP,
        png_bytes: fs.statSync(OUT).size }));
    } else {
      const shot = await cdp.send("Page.captureScreenshot", {
        format: "png",
        clip: { x: seen.rect.x, y: seen.rect.y, width: seen.rect.width, height: seen.rect.height, scale: 1 },
        captureBeyondViewport: false,
      }, 30000);
      if (!shot || !shot.data) throw new Error("CDP 回了没有图");
      fs.mkdirSync(path.dirname(OUT), { recursive: true });
      fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
      console.log(JSON.stringify({
        out: OUT, rect: seen.rect, mask_layers: seen.mask_layers,
        mask_composite: seen.mask_composite, media: seen.media,
        natural: seen.natural, png_bytes: fs.statSync(OUT).size,
      }));
    }
  } catch (error) {
    console.error(String(error && error.message ? error.message : error));
    code = 1;
  } finally {
    // `edge.kill()` 只打死父进程：crashpad / renderer / utility 全成孤儿（1.222 在这台机器上
    // 量到一次门禁跑完留着 880 个 msedge 进程）。taskkill /T 走进程树，杀完还要**验**——
    // profile 目录删得掉，才说明那棵树真的没了（进程活着会锁着它）。
    try {
      execFileSync("taskkill", ["/PID", String(edge.pid), "/T", "/F"], { stdio: "ignore" });
    } catch {
      try { edge.kill(); } catch {}
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
      code = 1;
    }
    host.close();
  }
  process.exit(code);
}

main();
