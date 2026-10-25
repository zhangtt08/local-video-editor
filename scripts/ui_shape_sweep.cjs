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
const CLIP = flag("clip", "");
// 文字层那一屏（1.227）：检查器里那四颗色块、三个下拉与字号那几格，只有选中一条
// **文字**片段才会画出来。以前夹具里没有文字素材，这一整片从来没进过任何一屏的取样。
const TEXTCLIP = flag("text-clip", "");
// 1.245：框点那一帧（`--boxkey <选择器>`）：滚进视野后读输入框的值、状态那一句与当前那一枚。
const BOXKEY = flag("boxkey", "");
// 1.259：主遮罩的软边那一格——◇ 按下去要真写出一条 mask_feather 曲线。
const FEATHER = flag("feather", "");
// 1.261 第 0 步：`--boxgeo 3,7,11` 把候选的命中盒临时画出来，量它的中心点第一次摸到的是谁。
// 交回的是数（`panel` 写 "geo"），所以它不占「该有几屏」那一判。
const BOXGEO = (flag("boxgeo", "") || "").split(",").filter((item) => item !== "").map(Number);
const GEO = path.resolve(flag("geo", path.join(__dirname, "ui_boxkey_geo.js")));
const DBL = path.resolve(flag("dbl", path.join(__dirname, "ui_boxkey_dbl.js")));
// 1.246：调色节点那一屏（`--gradecard <第几张卡>`）：点第二张卡，量它展开的那一格。
const GRADECARD = flag("gradecard", "");
const SIZES = (flag("sizes", "1456x808") || "").split(",");
const OUT = path.resolve(flag("out", "ui_shape_sweep.json"));
const EDGE = flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe");
const SHOTS = flag("shots", "");
// 拍哪一档主题：空 = 不动 localStorage（跟着应用默认走，深色）。非空时在这一趟一开始就把它
// 写进本机偏好并刷新一次——主题只在启动时读一次，不刷新就等于没换。
const THEME = flag("theme", "");
/** 门禁那张「每一屏该画出什么」的表（`PAINTED` 的值），逐条并进下面那一份计数名单。 */
const EXTRA_MARKERS = flag("painted", "") === "" ? [] : JSON.parse(flag("painted", ""));
const EXTRAS = args.reduce((acc, item, index) => (item === "--extra" ? acc.concat(args[index + 1]) : acc), []);
const PROBE = path.resolve(flag("probe", path.join(__dirname, "ui_shape_probe.js")));
// 每一档扫描收尾时若那棵浏览器树还锁着 profile，就把路径记在这儿——量具自己没打扫干净，
// 与「有一屏量不到」是同一类红。
const leaked = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 读引擎那一份状态：界面点过之后，「画出来了」与「写进去了」是两件事。
const engineGet = async (path) => {
  const response = await fetch(new URL(path, ENGINE), { headers: { Authorization: "Bearer " + TOKEN } });
  if (!response.ok) throw new Error(path + " -> " + response.status);
  return await response.json();
};
const enginePost = async (path, payload) => {
  const response = await fetch(new URL(path, ENGINE), { method: "POST",
    headers: { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(payload) });
  if (!response.ok) throw new Error(path + " -> " + response.status + " " + (await response.text()).slice(0, 200));
  return await response.json();
};

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
if (!fs.existsSync(DBL)) {
  console.error("box-key double-click probe missing: " + DBL);
  process.exit(2);
}
execFileSync(process.execPath, ["--check", DBL], { stdio: "pipe" });
if (BOXGEO.length) {
  if (!fs.existsSync(GEO)) {
    console.error("box-key geometry probe missing: " + GEO);
    process.exit(2);
  }
  try {
    execFileSync(process.execPath, ["--check", GEO], { stdio: "pipe" });
  } catch (error) {
    console.error("box-key geometry probe does not parse: " + String(error.stdout || "") + String(error.stderr || ""));
    process.exit(2);
  }
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
    // 1.230：把播放头放到这一格再量/截图。演示那条工程在 0 秒是淡入的第一帧（全黑），
    // 拿它当界面证据会让人以为监视器不画——刻度是工程自己的时钟，深链本来就认这一个参数。
    (flag("tick", "") ? "&tick=" + encodeURIComponent(flag("tick", "")) : "") +
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
    if (THEME !== "") {
      const want = THEME === "light" ? "light" : "dark";
      // 用 CDP 在**新文档的脚本之前**把偏好写下，再刷新一次——直接 evaluate 一句
      // `localStorage.setItem` 会撞上文档还没换过来的那一瞬（file:// 上读 localStorage
      // 是 SecurityError），那一瞬早晚会被下一次采样撞上，所以贴完还得回头看一眼。
      await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `try{localStorage.setItem("agentcut.theme", ${JSON.stringify(want)});}catch(e){}`,
      });
      await cdp.send("Page.reload", {});
      let applied = "";
      for (let wait = 0; wait < 60 && applied !== want; wait += 1) {
        await sleep(250);
        try {
          applied = String((await evaluate("document.documentElement.dataset.theme || ''")) || "");
        } catch {
          applied = "";
        }
      }
      if (applied !== want) throw new Error(`量具没能把主题贴上：要 ${want}，量到 ${applied || "空"}`);
    }
    // 等的是「屏幕上真的有字」，不是某个壳层节点存在——1.205 那一轮「五屏全报量不到」的根因
    // 就是把「能回话」当成了「画出来了」。
    let painted = null;
    for (let attempt = 0; attempt < 100 && !painted; attempt += 1) {
      const count = await evaluate("document.getElementsByTagName('*').length");
      if (count > 40) painted = count;
      else await sleep(300);
    }
    if (!painted) throw new Error("the page never painted anything at " + size);
    const tabsExpression = "Array.from(document.querySelectorAll('nav.tb-tabs button, nav.rail-nav [role=tab], .tabs button')).map(function (n, i) {" +
      "var r = n.getBoundingClientRect(); return {i: i, text: (n.textContent||'').trim().slice(0,20), label: n.getAttribute('aria-label')||'', x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2), selected: n.getAttribute('aria-selected')==='true'||/\\bactive\\b/.test(String(n.className||''))};})";
    let tabs = (await evaluate(tabsExpression)) || [];
    // 深链打开工程是异步的：第一帧可能还停在首页（那里没有右列页签）。等到页签出现再量，
    // 超时才算「这一屏没有页签」——之前这里一次采样就下结论，等于拿落地抖动当缺陷。
    for (let wait = 0; wait < 40 && !tabs.length; wait += 1) {
      await sleep(250);
      tabs = (await evaluate(tabsExpression)) || [];
    }
    if (!tabs.length) throw new Error("no view tabs found on the page at " + size);
    const click = async (x, y) => {
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left" });
    };
    const MARKERS = [".curve-plot", ".scope-panel", ".help", ".mask-guide", ".clip", ".masked-picture",
      ".timeline-clamped",
      // 那两扇弹层各自认自己的标题：只数 `.dialog` 的话，点开一扇错的也算过。
      'div.dialog[aria-label="预合成选中片段"]', 'div.dialog[aria-label="导入 SRT 字幕"]',
      // 文字层那一屏认的是那四颗色块：字在别的屏上一样有，只有色块是这一屏独有的。
      "input[type=color]",
      // 1.245：框点那一帧认的是那一块输入框本身；它的值与那一句由 --boxkey 那一腿单独读。
      "#stack-0-center_x",
      // 1.246：调色节点那一屏认的是第二张卡展开后的那一格矩阵系数。
      "#grade-matrix-0-0",
      // 1.251：复制出来的第三块，它的宽度那一格画出来了才算这一屏画了东西。
      "#stack-2-width",
      // 1.257：框点选了贝塞尔之后，那一行的四格画出来才算这一屏画了东西。
      "div.mask-stack-bezier",
      // 1.259：主遮罩软边那一格（◇ 按下去真写一条曲线，由下面那一腿判）。
      "#mask-feather",
      // 1.252：选中那一块的虚线框。
      ".mask-extra-outline",
      // 1.261：条上那一枚框点现在是一只手——认 button，span 不算（改了才画得出来）。
      "button.clip-boxkey",
      // 门禁那边每一屏认的那处东西由 `--painted` 传进来，这里只并表不另立一份：
      // 加一屏只改 `tests/ui_shape_check.py` 的 PAINTED 一处，这一腿跟着长。
      ...EXTRA_MARKERS];
    const run = async (screen) => {
      const data = await evaluate("(function(){ " + probeSource + " return measureAgentCutUi(); })()");
      // 「点了才画」那一档必须能证明**真的画了东西**：只数文字节点的话，
      // 一颗把页换掉的按钮和一颗什么都没干的按钮量出来一样（92 个节点对 92 个节点），
      // 红绿都不说明问题。这里按类名报每一处浮层的节点数，判据在门禁那边写。
      const markers = await evaluate("(() => { const out = {};" +
        "for (const sel of " + JSON.stringify(MARKERS) + ") {" +
        "out[sel] = document.querySelectorAll(sel).length;} return out; })()");
      // 红的时候要能自查：参考线画不出来有五个条件（有没有画面层、播放头在不在选中的那一段里、
      // 选中是不是恰好一条、那颗按钮按没按下）。把这几条一起带回来，不用再来一趟。
      const state = await evaluate("(() => { const head = document.querySelector('.playhead');" +
        "const sel = document.querySelector('.clip.selected');" +
        "const btn = Array.from(document.querySelectorAll('button'))" +
        ".find((n) => (n.textContent || '').trim() === " + JSON.stringify("画面中编辑") + ");" +
        "let inside = null;" +
        "if (head && sel) { const h = head.getBoundingClientRect(), s = sel.getBoundingClientRect();" +
        " inside = h.left >= s.left - 1 && h.left <= s.right + 1; }" +
        "return { headLeft: head ? Math.round(head.getBoundingClientRect().left) : null," +
        " clipBox: sel ? [Math.round(sel.getBoundingClientRect().left)," +
        " Math.round(sel.getBoundingClientRect().right)] : null, headInsideClip: inside," +
        " selected: document.querySelectorAll('.clip.selected').length," +
        " maskPressed: btn ? btn.getAttribute('aria-pressed') : null }; })()");
      rows.push({ screen, panel: flag("panel", ""), size, data, markers, state });
      if (SHOTS) {
        // 证据要能给人眼复核：判据是量出来的，但「挡住」还是「量具看错」值得留一张图。
        const shot = await cdp.send("Page.captureScreenshot", { format: "png" }, 30000);
        if (shot && shot.data) {
          const file = path.join(SHOTS, (THEME ? THEME + "-" : "") + (flag("panel", "") || "p") + "-" + String(screen).replace(/[\\/:*?"<>|\u0000-\u001f]/g, "") + "-" + size + ".png");
          fs.mkdirSync(SHOTS, { recursive: true });
          fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
        }
      }
    };
    // 1.231：可选地在量之前真选一次下拉（`--choose "<aria-label>=<value>"`）。下拉不是按钮，
    // 点一下只会弹原生的列表；要证明「选了之后真的发出去了一条命令」，就得设值并派发 change。
    const choose = flag("choose", "");
    if (choose) {
      await sleep(1200);
      const outcome = await evaluate("(function(){var spec=" + JSON.stringify(choose) +
        ";var at=spec.indexOf('=');var label=spec.slice(0,at), value=spec.slice(at+1);" +
        "var hit=Array.from(document.querySelectorAll('select'))" +
        ".find(function(n){return (n.getAttribute('aria-label')||'')===label;});" +
        "if(!hit) return 'no select: '+label;hit.value=value;" +
        "hit.dispatchEvent(new Event('change',{bubbles:true}));return 'ok:'+hit.value;})()");
      console.log("choose " + choose + " -> " + outcome);
      await sleep(900);
    }
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
    const tabRetry = [];
    for (let t = 0; t < tabs.length; t += 1) {
      if (tabs[t].selected || !tabs[t].x || !tabs[t].y) continue;
      await click(tabs[t].x, tabs[t].y);
      await sleep(700);
      const lit = await evaluate(tabsExpression);
      let now = (lit || []).find((row) => row.i === t) || {};
      let retried = false;
      if (!now.selected) {
        // 这一档量的是「点了这一颗，那一屏真换过去」。这台机器上页签落地偶尔比 700 ms 慢一拍
        // （套件里 1040x660 的「历史」就这么红过一次，同一份构建单跑是绿的）。再点一次、多等一档：
        // **两次都不亮才算缺陷**，判据一条没放软——「点了没换屏」照样红，只是不再拿一次抖动当结论。
        retried = true;
        tabRetry.push(`${size}:${String(tabs[t].text || tabs[t].label)}`);
        await click(tabs[t].x, tabs[t].y);
        await sleep(1500);
        const again = await evaluate(tabsExpression);
        now = (again || []).find((row) => row.i === t) || {};
      }
      if (!now.selected) {
        rows.push({ screen: String(tabs[t].text || tabs[t].label), panel: flag("panel", ""), size, data: null,
          error: "clicked but the tab never lit" + (retried ? "（两次都不亮）" : "") });
        continue;
      }
      await run(String(now.text || now.label));
    }
    // 补点这件事要看得见：静悄悄重试与没人重试是两回事，红字之外也留一份数。
    rows.push({ screen: "页签补点", panel: "retry", size, data: { count: tabRetry.length, names: tabRetry },
      markers: null, state: null });
    // 浮层那一档：每一颗都从**同一个可复现的起点**出发——编辑页 + 检查器那一列 +
    // 真选中 `--clip` 那条片段 + 检查器里那几段 `<details>` 真展开。
    // 为什么要每颗之前都回一次：上面那几颗里有的是**换页**（动画曲线换编辑页、示波器换右列），
    // Escape 不把页换回来；点顶部标签页还会把选中丢掉。1.223 补「画面中编辑」时被前一颗吃掉、
    // 1.224 补「选中」那一步又被换页吃掉，都是这一条没做到。
    // 1.291：属性页的四档（基础/调色/动画/特效）现在是**真分组**——一次只渲染一档，
    // 所以「找不到那颗按钮」有两种意思：产品上真没有，或者它在这一档之外。
    // 量具自己把这一条分清楚：先按当前页签找，找不到就逐档点过去，找到即停。
    // 四档都点完仍然找不到，才是真的没有——那时照旧报「那颗按钮不在这一屏上」。
    const findSpot = (matcher) => evaluate("(() => { const want = " + JSON.stringify(matcher)
      + ";const list = Array.from(document.querySelectorAll('button, [role=tab], input, select'));"
      + "const hit = list.find((n) => (n.textContent || '').trim() === want"
      + " || (n.getAttribute('aria-label') || '') === want || (n.getAttribute('id') || '') === want);"
      + "if (!hit) return null; const r = hit.getBoundingClientRect();"
      + "return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()");
    const propTabs = () => evaluate("(() => Array.from(document.querySelectorAll('.prop-tab-row button'))"
      + ".map((n) => { const r = n.getBoundingClientRect();"
      + "return {text: (n.textContent || '').trim(), x: Math.round(r.left + r.width / 2),"
      + " y: Math.round(r.top + r.height / 2)}; }).filter((n) => n.text && n.x))()");
    const reveal = async (matcher) => {
      let spot = await findSpot(matcher);
      if (spot) return spot;
      for (const tab of await propTabs()) {
        if (tab.text === matcher) continue;
        await click(tab.x, tab.y);
        await sleep(450);
        spot = await findSpot(matcher);
        if (spot) return spot;
      }
      return null;
    };
    const clickByText = async (name) => {
      const spot = await reveal(name);
      if (!spot) return false;
      await click(spot.x, spot.y);
      await sleep(500);
      return true;
    };
    // 2.0：片段卡先滚进时间线可视区，再取「卡片 ∩ 滚动区」的中心——时间线不再横跨右列，
    // 1040 那一档的卡片可能整张在可视区外，矩形照样给得出，按那个点打下去吃的是别的层。
    const clipSpot = (id) => evaluate("(() => { const el = document.querySelector('.clip[data-id="
      + JSON.stringify(id) + "]'); if (!el) return null;"
      // 只在看不见时才滚，且贴到最近的那一边：居中会把片段左缘（连同针）藏到轨道头底下。
      + "el.scrollIntoView({block: 'nearest', inline: 'nearest'});"
      + "const r = el.getBoundingClientRect();"
      + "const port = document.querySelector('.tl-scroll').getBoundingClientRect();"
      + "const left = Math.max(r.left, port.left + 4), right = Math.min(r.right, port.right - 4);"
      + "const top = Math.max(r.top, port.top + 4), bottom = Math.min(r.bottom, port.bottom - 4);"
      + "if (right <= left || bottom <= top) return null;"
      + "return {x: Math.round((left + right) / 2), y: Math.round((top + bottom) / 2)}; })()");

    // 1.291：按选择器找的那一腿同样要先翻属性页签——那一格现在只在自己那一档里渲染。
    const revealBySelector = async (selector) => {
      const here = () => evaluate("(function(){return Boolean(document.querySelector("
        + JSON.stringify(selector) + "));})()");
      if (await here()) return;
      for (const tab of await propTabs()) {
        await click(tab.x, tab.y);
        await sleep(450);
        if (await here()) return;
      }
    };
    // 2.0：检查器里的按钮先滚进视野，再验一次「那一点真的落在它身上」；被盖住就把盖它那一层
    // 带回来（不是「点了就算数」）。
    const panelSpot = async (selector) => {
      await revealBySelector(selector);
      return evaluate("(function(){var el=document.querySelector("
      + JSON.stringify(selector) + ");if(!el)return {error:'missing'};"
      + "el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();"
      + "var x=Math.round(r.left+r.width/2),y=Math.round(r.top+r.height/2);"
      + "if(!r.width||!r.height)return {error:'collapsed'};"
      + "var top=document.elementFromPoint(x,y);"
      + "return {x:x,y:y,ok: el===top||el.contains(top)||(top&&top.contains(el)),"
      + " disabled: Boolean(el.disabled), pressed: el.getAttribute('aria-pressed'),"
      + " rect: [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)],"
      + " over: top?top.tagName+'.'+String(top.className||'').slice(0,30):null};})()");
    };

    const waitForClip = async (id, timeout = 6000) => {
      const started = Date.now();
      while (Date.now() - started < timeout) {
        const there = await evaluate("Boolean(document.querySelector('.editor2 .clip[data-id="
          + JSON.stringify(id) + "]'))");
        if (there) return true;
        await sleep(250);
      }
      return false;
    };

    const openDetails = async () => {
      await evaluate("(function(){var d=document.querySelectorAll('details');"
        + "for(var i=0;i<d.length;i+=1){d[i].open=true;}return d.length;})()");
      await sleep(400);
    };
    const baseState = async (depth = 0) => {
      // 「动画曲线」那一颗换的是**中间那一页**：换过去之后时间线整个不画了，
      // `.clip` 那些卡片就不在 DOM 里——所以先按那页自己的「返回时间线」回来（没有这颗就跳过）。
      await clickByText("返回时间线");
      if (!(await clickByText("剪辑"))) return "找不到「剪辑」那一页的标签，浮层没有可复现的起点";
      // 2.0：右列那一页在顶栏叫「属性」（页内标题仍是「片段属性」），老量具按「检查器」找，
      // 两个名字都认，找不到才算没量到。
      if (!(await clickByText("检查器")) && !(await clickByText("属性"))) {
        return "点不到「检查器／属性」那一列，浮层量的是别的右列";
      }
      // 要点「点了才画」的那几颗，先得有选中：检查器里那一堆控件只在选中一条片段时存在。
      if (!CLIP) return "没有 --clip，浮层那一档不能确定选中状态";
      if (!(await waitForClip(CLIP))) return "重载之后时间线上还没有 .clip[data-id=" + CLIP + "]";

      // 2.0：时间线不再横跨右列（右栏一列到底），1040 那一档片段可能滚在可视区之外——
      // 矩形照样给得出，但按那个点打下去吃的是别的层。先滚进视野，再取「片段 ∩ 滚动区」的中心。
      const spot = await clipSpot(CLIP);
      if (!spot) return "时间线上找不到片段卡 .clip[data-id=" + CLIP + "]，「点了才画」那一档没有选中可依赖";
      // 遮罩参考线的条件是「选中这一块 + 画面正放着这一块」：深链把播放头停在 0 秒，
      // 那一格是第一条片段，所以光选中不够——按片段的横向位置在标尺上真点一下，把播放头挪进去。
      // 2.0：标尺那一行在窄窗里会被轨道头压在左边，滚动之后 spot.x 可能落在头部底下——
      // 点在那里不会 seek（吃的是头部），播放头留在 0 秒，画面里就不是选中的那一段。
      // 取「标尺 ∩ 滚动区 ∩ 轨道头右侧」的可见带，再按片段中心夹进去；点完验一次时间码。
      const ruler = await evaluate("(() => { const el = document.querySelector('.tl-ruler');" +
        "const port = document.querySelector('.tl-scroll');" +
        "const head = document.querySelector('.tl-head.corner');" +
        "if (!el || !port || !head) return null; const r = el.getBoundingClientRect();" +
        "const p = port.getBoundingClientRect(); const h = head.getBoundingClientRect();" +
        "if (!r.width || !r.height) return null;" +
        "return {y: Math.round(r.top + r.height / 2)," +
        " left: Math.round(Math.max(r.left, p.left, h.right) + 8)," +
        " right: Math.round(Math.min(r.right, p.right) - 8)}; })()");
      if (!ruler) return "找不到标尺 .tl-ruler，播放头挪不进那一段，浮层量的是没画面的状态";
      const seekX = Math.min(Math.max(spot.x, ruler.left), ruler.right);
      await click(seekX, ruler.y);
      await sleep(400);
      // 标尺那一下落在哪一格会被缩放与滚动带偏（1040 档实测差 10 帧，正好落到两枚框点之间）。
      // 先读一次时间码，不在片段中点就用键盘补齐：Home 后按 Shift+→，再一次一帧地补到目标格。
      const state = await engineGet(`/v1/projects/${PROJECT}`);
      const card = state.clips[CLIP];
      const rate = state.settings.frame_rate;
      const frameTicks = 70560000 / rate.numerator * rate.denominator;
      const targetFrame = Math.round((card.position_ticks + card.duration_ticks / 2) / frameTicks);
      const frames = async () => Number(await evaluate("(function(){var t=(document.querySelector('.ph-time')||{}).textContent||'';"
        + "var p=t.trim().split(':');if(p.length!==4)return -1;"
        + "return ((+p[0])*3600+(+p[1])*60+(+p[2]))*" + rate.numerator + "/" + rate.denominator + "+(+p[3]);})()"));
      let now = await frames();
      if (Math.abs(now - targetFrame) > 2) {
        await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Home", code: "Home", windowsVirtualKeyCode: 36 }, 20000);
        await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Home", code: "Home", windowsVirtualKeyCode: 36 }, 20000);
        await sleep(200);
        let guard = 0;
        while ((await frames()) < targetFrame && guard < 400) {
          const jump = (await frames()) + " " + "";
          const remaining = targetFrame - (await frames());
          const shift = remaining >= 10 ? 8 : 0;
          await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39, modifiers: shift }, 20000);
          await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39, modifiers: shift }, 20000);
          await sleep(18);
          guard += 1;
          if (jump === "") break;
        }
        while ((await frames()) > targetFrame) {
          await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 }, 20000);
          await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 }, 20000);
          await sleep(18);
        }
        now = await frames();
      }
      if (now < 0) return "播放头的时间码读不出来";
      // 点片段卡真的选中它；检查器里那些「点了才画」的控件只在这时存在。
      await click(spot.x, spot.y);
      await sleep(600);
      const selected = await evaluate("Boolean(document.querySelector('.clip.selected[data-id="
        + JSON.stringify(CLIP) + "]'))");
      if (!selected) return "点了片段卡但没有 .clip.selected——选中没落上，浮层量的是错的状态";
      // 检查器随选中重挂载（`key={project.id + "/" + clip.id}`），那几段 `<details>` 又合上了，
      // 而「画面中编辑」那颗就藏在合着的段落里——合着的时候它的矩形照样撒谎，所以先开再量。
      await openDetails();
      return null;
    };
    // 浮层那一腿认的是「文字里含这一串」，与上面那一腿的精确同名不是一把尺，所以另开一只。
    const revealPartial = async (text) => {
      const here = () => evaluate("(function(){var want=" + JSON.stringify(text)
        + ";return Array.from(document.querySelectorAll('button, [role=tab]'))"
        + ".some(function(n){return (n.textContent || '').trim().indexOf(want) >= 0;});})()");
      if (await here()) return;
      for (const tab of await propTabs()) {
        await click(tab.x, tab.y);
        await sleep(450);
        if (await here()) return;
      }
    };
    for (const label of EXTRAS) {
      const trouble = await baseState();
      if (trouble) {
        rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error: trouble });
        continue;
      }
      await revealPartial(label);
      const finder = "(() => { const want = " + JSON.stringify(label) + ";" +
        "const nodes = Array.from(document.querySelectorAll('button, [role=tab]'));" +
        "const hit = nodes.find((n) => (n.textContent || '').trim().indexOf(want) >= 0);" +
        "if (!hit) return null;" +
        // 检查器那一列是要滚的：合着/展开之后那颗按钮常在折线以下，矩形照样给得出（矩形会撒谎），
        // 而按那个点打下去吃的是**盖在它上面的那一层**——1.224 的「画面中编辑」就这么点了个空。
        // 所以先滚进视野，再按滚完的位置打，并且打完先验一遍那一点真的落在这颗上。
        "hit.scrollIntoView({block: 'center', inline: 'nearest'});" +
        "const r = hit.getBoundingClientRect();" +
        "const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);" +
        "const top = document.elementFromPoint(x, y);" +
        "return {x, y, covered: !(hit === top || hit.contains(top) || (top && top.contains(hit)))," +
        " over: top ? top.tagName + '/' + String(top.className || '').slice(0, 24) : 'null'}; })()";
      const spot = await evaluate(finder);
      if (!spot) {
        // 「那颗按钮不在这一屏上」要能自查：把这一屏真有的按钮名字带回来，
        // 读的人不必再猜是状态不对、名字不对，还是这颗本来就不该在这儿。
        const here = await evaluate("(() => Array.from(document.querySelectorAll(" +
          "'button, [role=tab]')).map((n) => (n.textContent || '').trim().slice(0, 14))" +
          ".filter(Boolean).slice(0, 40))()");
        const why = await evaluate("(() => ({ selected: document.querySelectorAll('.clip.selected').length," +
          " mask: Boolean(document.querySelector('.mask-section')), charters: document.querySelectorAll('.insp-section').length," +
          " tab: (document.querySelector('.rp-tabs .active') || {}).textContent || null }))()");
        rows.push({ screen: label, panel: flag("panel", ""), size, data: null,
          error: "那颗按钮不在这一屏上 " + JSON.stringify(why) + "；这一屏有的：" + JSON.stringify(here) });
        continue;
      }
      if (spot.covered) {
        // 不许「点了就算开了」：那一层盖着的时候，点下去的是别人，量到的还是这一屏——
        // 这一行必须记成没量到，而不是记成量到了。
        rows.push({ screen: label, panel: flag("panel", ""), size, data: null,
          error: "那颗按钮在 " + spot.x + "," + spot.y + " 被 " + spot.over + " 盖着，点不到" });
        continue;
      }
      await click(spot.x, spot.y);
      await sleep(800);
      await run(label);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }, 20000);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }, 20000);
      await sleep(300);
    }
    // 文字层那一屏：先回到同一个起点，再把选中换到夹具里那条文字片段上。
    // 特意放在「拖高时间线」**之前**——那一拖会把布局改成一个非默认高度，
    // 量出来的就不是所有人开机看到的那一屏。
    if (TEXTCLIP) {
      const trouble = await baseState();
      const rowOf = (error) => rows.push({
        screen: "文字层", panel: flag("panel", ""), size, data: null, error,
      });
      if (trouble) rowOf(trouble);
      else {
        const spot = await clipSpot(TEXTCLIP);
        if (!spot) rowOf("时间线上找不到文字片段卡 .clip[data-id=" + TEXTCLIP +
          "]——夹具里那条文字片段没画出来");
        else {
          await click(spot.x, spot.y);
          await sleep(600);
          await openDetails();
          // 1.291：文字层那四颗色块归「基础」那一档；前面几腿可能把页签翻走了，先翻回来再量。
          await revealBySelector("input[type=color]");
          // 那四颗色块在检查器那一列的折线以下：矩形照样给得出，但探针的 `visible()`
          // 会把「中心点出了滚动格」的那一层判成没画（那是 1.220 定的诚实判据）。
          // 所以先把那一格真滚进视野——不滚的话，这一屏量到 0 颗色块，判据就成了空话。
          const swatch = await evaluate("(function(){var c=document.querySelector('input[type=color]');"
            + "if(!c)return false;c.scrollIntoView({block:'center',inline:'nearest'});return true;})()");
          await sleep(400);
          if (!swatch) {
            const state = await evaluate("(() => ({selected: document.querySelectorAll('.clip.selected').length," +
              " tab: (document.querySelector('.rp-tabs .active') || {}).textContent || null," +
              " body: (document.querySelector('.rp-body') || {}).scrollTop, colors: document.querySelectorAll('input[type=color]').length," +
              " textSection: Array.from(document.querySelectorAll('.insp-section')).some(e => (e.textContent||'').includes('文字内容'))}))()");
            rowOf("选中文字片段之后检查器里没有 input[type=color]——那一屏没画出文字层 " + JSON.stringify(state));
          } else if (!(await evaluate("Boolean(document.querySelector('.clip.selected[data-id=" +
            JSON.stringify(TEXTCLIP) + "]'))"))) {
            rowOf("点了文字片段卡之后 .clip.selected 不是它——那一屏量的是错的状态");
          } else await run("文字层");
        }
      }
    }
    // 1.245：停在框点那一帧时，卡片上那五个数就是那一枚（1.243 明留的证据边界）。
    // 起点仍是 baseState：它把播放头点进选中片段里横坐标正中；夹具 k2 的中间那枚框点正在
    // 片段自己的 2 秒上，所以读数时播放头**正停在框点上**，不是停在两枚之间。
    // 夹具里那一枚是 center_x 0.55、rotation 6，静止值是 0.62 与 0——读到 62/0 就是又在显示静止值。
    if (BOXKEY) {
      const label = "框点那一帧";
      const trouble = await baseState();
      if (trouble) rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error: trouble });
      else {
        const scrolled = await evaluate("(function(){var el=document.querySelector("
          + JSON.stringify(BOXKEY) + ");if(!el)return false;el.scrollIntoView({block:'center'});return true;})()");
        await sleep(400);
        const proof = await evaluate("(function(){"
          + "var c=document.querySelector('#stack-0-center_x');var r=document.querySelector('#stack-0-rotation');"
          + "var f=document.querySelector('#stack-0-feather');"
          + "var n=document.querySelector('.mask-stack-at');"
          + "var cur=document.querySelector('.mask-stack-keylist li.current button');"
          + "return {center:c?c.value:null,rotation:r?r.value:null,feather:f?f.value:null,"
          + "note:n?n.textContent.trim():null,"
          + "current:cur?cur.textContent.trim():null,aria:cur?cur.getAttribute('aria-current'):null};})()");
        // 1.258：那一枚框点自己写着羽化 12%，而这一块静止的是 5%——卡片读的是哪一个，量得出来。
        const bad = !scrolled || !proof || Number(proof.center) !== 55 || Number(proof.rotation) !== 6
          || Number(proof.feather) !== 12
          || !(proof.note || "").includes("改的是这一枚") || proof.aria !== "true";
        if (bad) rows.push({ screen: label, panel: flag("panel", ""), size, data: null,
          error: "卡片没有显示框点那一枚的数：" + JSON.stringify(proof) });
        else await run(label);
      }
    }
    // 1.246：调色节点那一屏——卡片是「点了才画」：点第二张卡，它下面那几格才换成矩阵。
    // 夹具 k2 的链是 [色阶, 矩阵]，第二张卡的第一格系数是 0.95；点错了卡这一格就不会出现。
    if (GRADECARD) {
      const label = "调色节点";
      const trouble = await baseState();
      if (trouble) rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error: trouble });
      else {
        // 1.291：调色节点归「调色」那一档，前面几腿会把页签翻走——先翻回来再点卡。
        await revealBySelector(".gg-card .gg-pick");
        const clicked = await evaluate("(function(){"
          + "var cards=document.querySelectorAll('.gg-card .gg-pick');"
          + "var hit=cards[" + String(Math.max(0, Number(GRADECARD) - 1)) + "];"
          + "if(!hit)return null;hit.scrollIntoView({block:'center'});hit.click();"
          + "return {cards:cards.length,text:(hit.textContent||'').trim()};})()");
        await sleep(500);
        const proof = await evaluate("(function(){"
          + "var el=document.querySelector('#grade-matrix-0-0');if(el)el.scrollIntoView({block:'center'});"
          + "var active=document.querySelector('.gg-card.active .gg-pick b');"
          + "return {value:el?el.value:null,active:active?active.textContent.trim():null};})()");
        const bad = !clicked || !proof || !(proof.active || "").includes("通道混合")
          || Math.abs(Number(proof.value) - 0.95) > 1e-9;
        if (bad) rows.push({ screen: label, panel: flag("panel", ""), size, data: null,
          error: "点了第二张卡，展开的不是矩阵那一格：" + JSON.stringify({ clicked, proof }) });
        else await run(label);
      }
    }
    // 反方向那一判（`--drag-splitter`）：用户**自己**把那条边往上拖，时间线让不动了，
    // 那句「窗口太矮」必须出现。只判「开机不许说」会把它写成「永远不说」——两只手都要钉。
    if (flag("drag-splitter", "") !== "") {
      const grip = await evaluate("(() => { const el = document.querySelector('.splitter.horizontal');"
        + "if (!el) return null; const r = el.getBoundingClientRect();"
        + "return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()");
      if (!grip) {
        rows.push({ screen: "拖高时间线", panel: flag("panel", ""), size, data: null,
          error: "找不到那条边 .splitter.horizontal——反方向那一判没量到" });
      } else {
        await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: grip.x, y: grip.y, button: "left", clickCount: 1 });
        for (let step = 1; step <= 4; step += 1) {
          await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: grip.x, y: grip.y - step * 40, button: "left" });
          await sleep(60);
        }
        await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: grip.x, y: grip.y - 160, button: "left" });
        await sleep(700);
        await run("拖高时间线");
      }
    }
    // 1.259：主遮罩的软边也能打点。界面那一格 ◇ 按下去，引擎里必须真多出一条 mask_feather，
    // 而那颗钮的无障碍名要跟着翻成「删除」——「看得见、按下去写了、说得对」三件事一起判。
    if (FEATHER) {
      const label = "主遮罩软边打点";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) rowOf(trouble);
      else {
        const before = await engineGet(`/v1/projects/${PROJECT}`);
        const was = ((before.clips["k2"] || {}).keyframes || [])
          .filter((k) => k.property === "mask_feather");
        const scrolled = await evaluate("(function(){var el=document.querySelector('#mask-feather');"
          + "if(!el)return false;el.scrollIntoView({block:'center'});return true;})()");
        await sleep(400);
        const hit = await evaluate("(function(){var btn=Array.from(document.querySelectorAll('button'))"
          + ".find((n)=>(n.getAttribute('aria-label')||'')==='添加向内羽化关键帧');"
          + "if(!btn)return null;var r=btn.getBoundingClientRect();"
          + "var f=document.querySelector('#mask-feather');"
          + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),"
          + "value:f?f.value:null,disabled:btn.disabled};})()");
        if (!scrolled || !hit) rowOf("主遮罩那一格没有「向内羽化」或那颗 ◇：软边那一行没画出来"
          + "（scrolled=" + scrolled + " hit=" + JSON.stringify(hit) + "）");
        else if (hit.disabled) rowOf("那颗 ◇ 是灰的，按不下去");
        else {
          await click(hit.x, hit.y);
          await sleep(900);
          const after = await engineGet(`/v1/projects/${PROJECT}`);
          const now = ((after.clips["k2"] || {}).keyframes || [])
            .filter((k) => k.property === "mask_feather");
          const flipped = await evaluate("(function(){var btn=Array.from(document.querySelectorAll('button'))"
            + ".find((n)=>(n.getAttribute('aria-label')||'')==='删除向内羽化关键帧');"
            + "return btn?btn.getAttribute('aria-label'):null;})()");
          const wrote = now.length === was.length + 1
            && now.some((k) => Math.abs(k.value - Number(hit.value) / 100) < 1e-9);
          if (!wrote || flipped !== "删除向内羽化关键帧") {
            rowOf("按下去之后引擎里不是那一条曲线，或那颗钮没翻成「删除」：before=" + was.length
              + " after=" + now.length + " 格子里读的是 " + hit.value + "%"
              + " 键=" + JSON.stringify(now.map((k) => [k.at_ticks, k.value]))
              + " 无障碍名=" + JSON.stringify(flipped));
          } else {
            await run(label);
            // 这一腿改了共享夹具：按原样放回，再重载一次让页面的 revision 跟上（1.252 那一课）。
            await enginePost(`/v1/projects/${PROJECT}/edits`, {
              request_id: `shape-feather-restore-${size}-${Date.now()}`,
              expected_revision: after.revision,
              commands: now.slice(was.length).map((k) => ({
                op: "keyframe.remove", clip_id: "k2", property: "mask_feather",
                at_ticks: k.at_ticks })) });
            await cdp.send("Page.reload", {}, 30000);
            await waitForClip("k2");
          }
        }
      }
    }
    // 1.251：真点一次「复制第 1 块」，再回引擎数块数与框点——这个按钮不该只有源码断言。
    if (flag("dup-extra", "") !== "") {
      const label = "复制再叠遮罩";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) rowOf(trouble);
      else {
        const before = await engineGet(`/v1/projects/${PROJECT}`);
        const spot = await evaluate("(function(){var el=document.querySelector('[aria-label=\"复制第 1 块叠加遮罩\"]');"
          + "if(!el)return null;el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();"
          + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),disabled:el.disabled};})()");
        if (!spot) rowOf("检查器里找不到「复制第 1 块叠加遮罩」");
        else if (spot.disabled) rowOf("那一颗是灰的（块数上限或只读），按不下去");
        else {
          await click(spot.x, spot.y);
          await sleep(900);
          const after = await engineGet(`/v1/projects/${PROJECT}`);
          const was = before.clips["k2"].extra_masks;
          const now = after.clips["k2"].extra_masks;
          const src = was[0];
          const copy = now[now.length - 1];
          await evaluate("(function(){var el=document.querySelector('#stack-2-width');"
            + "if(el)el.scrollIntoView({block:'center'});return !!el;})()");
          await sleep(400);
          const ok = now.length === was.length + 1
            && copy && (copy.keys ?? []).length === (src.keys ?? []).length
            && Math.abs(copy.center_x - Math.min(1, src.center_x + 0.04)) < 1e-9
            && Math.abs(copy.center_y - Math.min(1, src.center_y + 0.04)) < 1e-9;
          if (!ok) rowOf("复制没有按预期落进工程：before=" + was.length + " after=" + now.length
            + " copy=" + JSON.stringify(copy ? [copy.center_x, copy.center_y, (copy.keys ?? []).length] : null)
            + " src=" + JSON.stringify([src.center_x, src.center_y, (src.keys ?? []).length]));
          else {
            await run(label);
            // 这一腿会改共享的夹具：量完把它放回去，下一档窗口与后面的屏看到的还是原样。
            await enginePost(`/v1/projects/${PROJECT}/edits`, { request_id: `shape-dup-restore-${size}-${Date.now()}`,
              expected_revision: after.revision, commands: [{ op: "clip.mask_stack", clip_id: "k2", masks: was }] });
            // 这次放回绕过了界面：重载一次，让页面的 project.revision 跟上引擎，后面的写才不会被 409 拒。
            await cdp.send("Page.reload", {}, 30000);
            await waitForClip("k2");
          }
        }
      }
    }
    // 1.252：选中一块，在画面里拖它那颗柄，回引擎读「改的是哪一枚」。
    if (flag("drag-extra", "") !== "") {
      const label = "画面拖再叠遮罩";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) rowOf(trouble);
      else {
        const pick = await panelSpot('[aria-label=\"在画面里选中第 1 块叠加遮罩\"]');
        if (!pick || pick.error) rowOf("找不到「在画面里选中第 1 块叠加遮罩」" + JSON.stringify(pick || null));
        else if (!pick.ok) rowOf("「在画面里选中第 1 块叠加遮罩」被 " + pick.over + " 盖着，点不到");
        else {
          await click(pick.x, pick.y);
          await sleep(700);
          let picked = await evaluate("(function(){var el=document.querySelector('.mask-guide');"
            + "var b=document.querySelector('[aria-label*=\"取消选中第 1 块\"]');"
            + "return {guide:Boolean(el),pressed:b?b.getAttribute('aria-pressed'):null};})()");
          if (!picked || !picked.guide || picked.pressed !== "true") {
            // 按钮可能还在等上一笔 manifest 落地（disabled 时按下不生效）：等到可按再点一次。
            await sleep(700);
            const again = await panelSpot('[aria-label=\"在画面里选中第 1 块叠加遮罩\"]');
            if (again && !again.error && !again.disabled && again.ok) {
              await click(again.x, again.y);
              await sleep(800);
              picked = await evaluate("(function(){var el=document.querySelector('.mask-guide');"
                + "var b=document.querySelector('[aria-label*=\"取消选中第 1 块\"]');"
                + "return {guide:Boolean(el),pressed:b?b.getAttribute('aria-pressed'):null};})()");
            }
          }
          const before = await engineGet(`/v1/projects/${PROJECT}`);
          // 这一腿三下手都改的是共享夹具里那一枚。不管量成没量成都要放回去——
          // 上一版只在成功那一支放回，一次红就把脏状态带进了下一档窗口（连着两屏假红）。
          const restore = async () => {
            const latest = await engineGet(`/v1/projects/${PROJECT}`);
            await enginePost(`/v1/projects/${PROJECT}/edits`, {
              request_id: `shape-drag-restore-${size}-${Date.now()}`,
              expected_revision: latest.revision,
              commands: [{ op: "clip.mask_stack", clip_id: "k2", masks: before.clips["k2"].extra_masks }],
            });
            // 裸 HTTP 放回绕过界面，页面的 revision 会落后一拍；不重载，下一笔就是 409 被静默拒。
            await cdp.send("Page.reload", {}, 30000);
            await waitForClip("k2");
          };
          const fail = async (message) => { rowOf(message); await restore(); };
          const spot = await evaluate("(function(){var el=document.querySelector('.mask-extra-handle');"
            + "if(!el)return null;var r=el.getBoundingClientRect();"
            + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
          if (!spot) {
            const state = await evaluate("(() => ({guide: Boolean(document.querySelector('.mask-guide'))," +
              " handles: document.querySelectorAll('.mask-extra-handle').length," +
              " selected: document.querySelectorAll('.clip.selected').length," +
              " extraSel: Boolean(document.querySelector('.mask-extra-row.selected'))," +
              " tab: (document.querySelector('.rp-tabs .active') || {}).textContent || null," +
              " layers: document.querySelectorAll('.preview-layer').length," +
              " empty: (document.querySelector('.monitor-empty') || {}).textContent || null," +
              " maskOn: (document.querySelector('button[aria-pressed][class*=btn]') ? Array.from(document.querySelectorAll('button')).filter(b => b.textContent.trim() === '画面中编辑').map(b => b.getAttribute('aria-pressed')) : [])," +
              " monitor: (document.querySelector('.monitor-head .seg button.active') || {}).textContent || null," +
              " time: (document.querySelector('.ph-time') || {}).textContent || null," +
              " pick: " + JSON.stringify(pick) + ", picked: " + JSON.stringify(picked) + "}))()");
            const shot = await cdp.send("Page.captureScreenshot", { format: "png" }, 30000);
            const debugDir = path.dirname(OUT);
            const debugPath = path.join(debugDir, "debug-mask-" + size + ".png");
            fs.mkdirSync(debugDir, { recursive: true });
            fs.writeFileSync(debugPath, Buffer.from(shot.data, "base64"));
            rowOf("选中之后画面里没有 .mask-extra-handle " + JSON.stringify(state));
          }
          else {
            await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: spot.x, y: spot.y, button: "left", clickCount: 1 });
            for (let step = 1; step <= 4; step += 1) {
              await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: spot.x + step * 12, y: spot.y, button: "left" });
              await sleep(60);
            }
            await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: spot.x + 48, y: spot.y, button: "left" });
            await sleep(900);
            const after = await engineGet(`/v1/projects/${PROJECT}`);
            const was = before.clips["k2"].extra_masks[0];
            const now = after.clips["k2"].extra_masks[0];
            const keyAt = 141_120_000;
            const wasKey = (was.keys ?? []).find((k) => k.at_ticks === keyAt);
            const nowKey = (now.keys ?? []).find((k) => k.at_ticks === keyAt);
            const midKey = nowKey;
            const screen = await evaluate("(function(){var el=document.querySelector('.mask-extra-handle');"
              + "if(!el)return null;var r=el.getBoundingClientRect();"
              + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
            const followed = screen && Math.abs(screen.x - (spot.x + 48)) <= 4 && Math.abs(screen.y - spot.y) <= 3;
            const movedKey = wasKey && nowKey
              && Math.hypot(nowKey.center_x - wasKey.center_x, nowKey.center_y - wasKey.center_y) > 0.02;
            const staticSame = Math.abs(now.center_x - was.center_x) < 1e-9
              && Math.abs(now.center_y - was.center_y) < 1e-9;
            const other = JSON.stringify(after.clips["k2"].extra_masks[1]) === JSON.stringify(before.clips["k2"].extra_masks[1]);
            if (!followed || !movedKey || !staticSame || !other) await fail("拖动没有按预期："
              + "key=" + JSON.stringify([wasKey && [wasKey.center_x, wasKey.center_y], nowKey && [nowKey.center_x, nowKey.center_y]])
              + " static=" + JSON.stringify([was.center_x, was.center_y, now.center_x, now.center_y])
              + " time=" + String(await evaluate("(document.querySelector('.ph-time') || {}).textContent || ''"))
              + " screen=" + JSON.stringify(screen) + " spot=" + JSON.stringify(spot));
            else {
              // 同一块再拖右下角：两条边与中心一起变，静止值仍然不动。
              const corner = await evaluate("(function(){var el=document.querySelector("
                + "'[aria-label=\"缩放选中的再叠遮罩（第 1 块·右下）\"]');"
                + "if(!el)return null;var r=el.getBoundingClientRect();"
                + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
              if (!corner) await fail("选中之后没有右下的缩放手柄");
              else {
                await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: corner.x, y: corner.y, button: "left", clickCount: 1 });
                for (let step = 1; step <= 3; step += 1) {
                  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: corner.x + step * 10, y: corner.y, button: "left" });
                  await sleep(60);
                }
                await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: corner.x + 30, y: corner.y, button: "left" });
                await sleep(900);
                const resized = await engineGet(`/v1/projects/${PROJECT}`);
                const resizedKey = ((resized.clips["k2"].extra_masks[0].keys) ?? []).find((k) => k.at_ticks === keyAt);
                const grew = midKey && resizedKey
                  && (Math.abs(resizedKey.width - midKey.width) > 0.02
                    || Math.abs(resizedKey.height - midKey.height) > 0.02);
                const staticSize = Math.abs(resized.clips["k2"].extra_masks[0].width - was.width) < 1e-9
                  && Math.abs(resized.clips["k2"].extra_masks[0].height - was.height) < 1e-9;
                const other2 = JSON.stringify(resized.clips["k2"].extra_masks[1]) === JSON.stringify(before.clips["k2"].extra_masks[1]);
                if (!grew || !staticSize || !other2) await fail("缩放手柄没有按预期："
                  + "key=" + JSON.stringify(midKey && [midKey.width, midKey.height, resizedKey && resizedKey.width, resizedKey && resizedKey.height])
                  + " static=" + JSON.stringify([was.width, was.height]));
                else {
                  // 第三下手：那颗角度柄。判三件事——① 引擎里那一枚的 rotation 真的跟着转（符号与量级），
                  // ② 柄落在**松手那一点**上（1.182 定的「拖多少就是看见多少」，不按屏幕角=盒角猜），
                  // ③ 那块静止的角度与另一块一个字不动。
                  const read = await evaluate("(function(){var corners=document.querySelectorAll('.mask-extra-handle.corner');"
                    + "var rot=document.querySelector('[aria-label^=\"旋转选中的再叠遮罩\"]');"
                    + "if(corners.length!==4||!rot)return null;"
                    + "var sx=0,sy=0;Array.prototype.forEach.call(corners,function(el){var r=el.getBoundingClientRect();"
                    + "sx+=r.left+r.width/2;sy+=r.top+r.height/2;});var cx=sx/4,cy=sy/4;"
                    + "var q=rot.getBoundingClientRect();var hx=q.left+q.width/2,hy=q.top+q.height/2;"
                    + "return {cx:cx,cy:cy,hx:hx,hy:hy};})()");
                  if (!read) await fail("没有四颗角柄或那颗角度柄");
                  else {
                    const vector = [read.hx - read.cx, read.hy - read.cy];
                    const sweep = 20 * Math.PI / 180;
                    const target = { x: read.cx + vector[0] * Math.cos(sweep) - vector[1] * Math.sin(sweep),
                      y: read.cy + vector[0] * Math.sin(sweep) + vector[1] * Math.cos(sweep) };
                    await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed",
                      x: Math.round(read.hx), y: Math.round(read.hy), button: "left", clickCount: 1 });
                    for (let step = 1; step <= 5; step += 1) {
                      const part = step / 5;
                      await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved",
                        x: Math.round(read.hx + (target.x - read.hx) * part),
                        y: Math.round(read.hy + (target.y - read.hy) * part), button: "left" });
                      await sleep(60);
                    }
                    await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased",
                      x: Math.round(target.x), y: Math.round(target.y), button: "left" });
                    await sleep(900);
                    const turned = await engineGet(`/v1/projects/${PROJECT}`);
                    const turnedKey = ((turned.clips["k2"].extra_masks[0].keys) ?? []).find((k) => k.at_ticks === keyAt);
                    const delta = turnedKey && midKey ? turnedKey.rotation - midKey.rotation : null;
                    const probe = "(function(){var corners=document.querySelectorAll('.mask-extra-handle.corner');"
                      + "var rot=document.querySelector('[aria-label^=\"旋转选中的再叠遮罩\"]');"
                      + "if(corners.length!==4||!rot)return null;"
                      + "var sx=0,sy=0;Array.prototype.forEach.call(corners,function(el){var r=el.getBoundingClientRect();"
                      + "sx+=r.left+r.width/2;sy+=r.top+r.height/2;});var cx=sx/4,cy=sy/4;"
                      + "var q=rot.getBoundingClientRect();var hx=q.left+q.width/2,hy=q.top+q.height/2;"
                      + "var a=function(dx,dy){var deg=Math.atan2(dx,-dy)*180/Math.PI;return deg<0?deg+360:deg;};"
                      + "return {got:a(hx-cx,hy-cy),want:a(" + target.x + "-cx," + target.y + "-cy),"
                      + "label:rot.getAttribute('aria-label')};})()";
                    const after = await evaluate(probe);
                    const turnedEngine = delta !== null && Math.abs(delta) > 3 && Math.abs(delta) < 90 && Math.sign(delta) === 1;
                    const screenFollows = after && Math.abs(after.got - after.want) <= 3;
                    const labelSays = Boolean(after && turnedKey && after.label
                      && after.label.indexOf("此刻 " + turnedKey.rotation.toFixed(1) + "°") >= 0);
                    const staticAngle = Math.abs(turned.clips["k2"].extra_masks[0].rotation - was.rotation) < 1e-9;
                    const other3 = JSON.stringify(turned.clips["k2"].extra_masks[1]) === JSON.stringify(before.clips["k2"].extra_masks[1]);
                    if (!turnedEngine || !screenFollows || !labelSays || !staticAngle || !other3) await fail("角度柄没有按预期："
                      + "delta=" + JSON.stringify(delta) + " mid=" + JSON.stringify(midKey && midKey.rotation)
                      + " turned=" + JSON.stringify(turnedKey && turnedKey.rotation)
                      + " screen=" + JSON.stringify(after) + " static=" + JSON.stringify(was.rotation));
                    else {
                      await run(label);
                      await restore();
                    }
                  }
                }
              }
            }
            // 量完再取消选中：后面的屏不该挂着这颗柄。
            await evaluate("(function(){var el=document.querySelector('[aria-label=\"取消选中第 1 块叠加遮罩\"]');"
              + "if(el)el.click();return !!el;})()");
            await sleep(300);
          }
        }
      }
    }
    if (flag("insert-extra", "") !== "") {
      // 1.255：播放头停在两枚框点**之间**时，画面里那一框就是引擎窗表执行的那一格；
      // 拖它 = 在这一帧新打一枚框点（原来那几枚一字不动）。判的是回引擎数 keys 的枚数与那一枚的数。
      const label = "画面打新框点";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) rowOf(trouble);
      else {
        // 把播放头挪到那两枚之间（夹具的键在 0 / 2 / 4 秒，卡片 75% 处就是 3 秒）。
        const where = await evaluate("(function(){var el=document.querySelector('.clip.selected');"
          + "var r=document.querySelector('.tl-ruler');"
          + "if(!el||!r)return null;var b=el.getBoundingClientRect(),s=r.getBoundingClientRect();"
          + "var x=Math.round(b.left+b.width*0.75);"
          + "return {x:Math.min(Math.max(x,s.left+2),s.right-2),ry:Math.round(s.top+s.height/2),"
          + "cy:Math.round(b.top+b.height/2)};})()");
        if (!where) rowOf("找不到选中的片段卡或标尺，播放头挪不到那两枚之间");
        else {
          await click(where.x, where.ry);
          await sleep(500);
          await click(where.x, where.cy);
          await sleep(500);
          const pick = await evaluate("(function(){var el=document.querySelector("
            + "\"[aria-label='在画面里选中第 1 块叠加遮罩']\");"
            + "if(!el)return null;el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();"
            + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
          if (!pick) rowOf("找不到「在画面里选中第 1 块叠加遮罩」");
          else {
            await click(pick.x, pick.y);
            await sleep(700);
            const before = await engineGet(`/v1/projects/${PROJECT}`);
            const restore = async () => {
              const latest = await engineGet(`/v1/projects/${PROJECT}`);
              await enginePost(`/v1/projects/${PROJECT}/edits`, {
                request_id: `shape-insert-restore-${size}-${Date.now()}`,
                expected_revision: latest.revision,
                commands: [{ op: "clip.mask_stack", clip_id: "k2", masks: before.clips["k2"].extra_masks }],
              });
              await cdp.send("Page.reload", {}, 30000);
              await sleep(1200);
            };
            const fail = async (message) => { rowOf(message); await restore(); };
            const wasKeys = before.clips["k2"].extra_masks[0].keys ?? [];
            const drawn = await evaluate("(function(){var el=document.querySelector('.mask-extra-outline');"
              + "if(!el)return null;var r=el.getBoundingClientRect();return {w:r.width,h:r.height};})()");
            const spot = await evaluate("(function(){var el=document.querySelector('.mask-extra-handle');"
              + "if(!el)return null;var r=el.getBoundingClientRect();"
              + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
            if (!drawn || !spot) await fail("停在两枚之间时画面里没有那一框或那颗柄");
            else {
              await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: spot.x, y: spot.y, button: "left", clickCount: 1 });
              for (let step = 1; step <= 3; step += 1) {
                await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: spot.x + step * 10, y: spot.y, button: "left" });
                await sleep(60);
              }
              await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: spot.x + 30, y: spot.y, button: "left" });
              await sleep(900);
              const after = await engineGet(`/v1/projects/${PROJECT}`);
              const nowKeys = after.clips["k2"].extra_masks[0].keys ?? [];
              const second = wasKeys[1];
              const added = nowKeys.filter((key) => !wasKeys.some((old) => old.at_ticks === key.at_ticks));
              const middle = added.filter((key) => key.at_ticks > (wasKeys[0]?.at_ticks ?? 0)
                && key.at_ticks < (wasKeys[wasKeys.length - 1]?.at_ticks ?? Infinity));
              const moved = added.length === 1 && Math.abs(added[0].center_x - (second?.center_x ?? 0)) > 0.02;
              const kept = nowKeys.filter((key) => wasKeys.some((old) => old.at_ticks === key.at_ticks))
                .every((key) => JSON.stringify(key) === JSON.stringify(wasKeys.find((old) => old.at_ticks === key.at_ticks)));
              const other = JSON.stringify(after.clips["k2"].extra_masks[1]) === JSON.stringify(before.clips["k2"].extra_masks[1]);
              if (nowKeys.length !== wasKeys.length + 1 || !middle.length || !moved || !kept || !other) {
                await fail("拖那一框没有新打一枚框点：枚数 " + JSON.stringify([wasKeys.length, nowKeys.length])
                  + " 新那枚 " + JSON.stringify(added) + " 原来那几枚没动=" + JSON.stringify(kept));
              } else {
                await run(label);
                await restore();
              }
            }
            await evaluate("(function(){var el=document.querySelector('[aria-label=\"取消选中第 1 块叠加遮罩\"]');"
              + "if(el)el.click();return !!el;})()");
            await sleep(300);
          }
        }
      }
    }
    if (flag("alt-dup", "") !== "") {
      // 1.256：按住 Alt 拖那一框 = 先复制这一块再拖副本。判四件事：
      // 拖的**途中**画面里有两圈（原框留在原地）、块数 +1、副本带着拖完的中心、
      // 原来那一块与它的框点一字不动。
      const label = "画面Alt拖出副本";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) rowOf(trouble);
      else {
        const pick = await panelSpot("[aria-label='在画面里选中第 1 块叠加遮罩']");
        if (!pick || pick.error) rowOf("找不到「在画面里选中第 1 块叠加遮罩」" + JSON.stringify(pick || null));
        else if (!pick.ok) rowOf("「在画面里选中第 1 块叠加遮罩」被 " + pick.over + " 盖着，点不到");
        else {
          await click(pick.x, pick.y);
          await sleep(700);
          // 上一腿可能还有一写在路上：等它落地再抓这一下，否则 pointerdown 记的版本会过期。
          await sleep(1200);
          const before = await engineGet(`/v1/projects/${PROJECT}`);
          const restore = async () => {
            const latest = await engineGet(`/v1/projects/${PROJECT}`);
            await enginePost(`/v1/projects/${PROJECT}/edits`, {
              request_id: `shape-altdup-restore-${size}-${Date.now()}`,
              expected_revision: latest.revision,
              commands: [{ op: "clip.mask_stack", clip_id: "k2", masks: before.clips["k2"].extra_masks }],
            });
            await cdp.send("Page.reload", {}, 30000);
            await waitForClip("k2");
          };
          const fail = async (message) => { rowOf(message); await restore(); };
          const spot = await evaluate("(function(){var el=document.querySelector('.mask-extra-handle');"
            + "if(!el)return null;var r=el.getBoundingClientRect();"
            + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
          if (!spot) await fail("选中之后画面里没有那颗柄");
          else {
            const alt = 1; // CDP 的 modifiers 位掩码：Alt = 1
            await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: spot.x, y: spot.y,
              button: "left", clickCount: 1, modifiers: alt });
            for (let step = 1; step <= 4; step += 1) {
              await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: spot.x + step * 10, y: spot.y,
                button: "left", modifiers: alt });
              await sleep(60);
            }
            const during = await evaluate("(function(){var rings=document.querySelectorAll('.mask-extra-outline');"
              + "var ghost=document.querySelector('.mask-extra-outline.ghost');"
              + "return {rings:rings.length, ghost:Boolean(ghost)};})()");
            await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: spot.x + 40, y: spot.y,
              button: "left", modifiers: alt });
            await sleep(900);
            const after = await engineGet(`/v1/projects/${PROJECT}`);
            const was = before.clips["k2"].extra_masks;
            const now = after.clips["k2"].extra_masks;
            const copy = now[now.length - 1];
            const source = was[0];
            const grew = now.length === was.length + 1;
            // 播放头停在 2 秒那一枚框点上：拖的是**那一枚**，静止值照旧是模板值——
            // 所以比的是副本那一枚与原来那一枚，不是两个静止中心。
            const copyKey = copy && (copy.keys ?? []).find((k) => k.at_ticks === 141_120_000);
            const sourceKey = (source.keys ?? []).find((k) => k.at_ticks === 141_120_000);
            const moved = Boolean(copyKey && sourceKey)
              && Math.abs(copyKey.center_x - sourceKey.center_x) > 0.02;
            const untouched = JSON.stringify(now[0]) === JSON.stringify(source);
            const carried = copy && (copy.keys ?? []).length === (source.keys ?? []).length
              && copy.shape === source.shape && Math.abs(copy.width - source.width) < 1e-9
              && Math.abs(copy.height - source.height) < 1e-9
              && Math.abs(copy.rotation - source.rotation) < 1e-9;
            const twoRings = during && during.rings === 2 && during.ghost;
            if (!grew || !moved || !untouched || !carried || !twoRings) {
              await fail("Alt 拖副本没有按预期：块数 " + JSON.stringify([was.length, now.length])
                + " 副本那枚 " + JSON.stringify(copyKey && [copyKey.center_x, (copy.keys ?? []).length])
                + " 原来那枚 " + JSON.stringify(sourceKey && sourceKey.center_x)
                + " 原块没动=" + JSON.stringify(untouched) + " 尺寸带过来=" + JSON.stringify(Boolean(carried))
                + " 途中两圈=" + JSON.stringify(during));
            } else {
              await run(label);
              await restore();
            }
            await evaluate("(function(){var el=document.querySelector('[aria-label=\"取消选中第 1 块叠加遮罩\"]');"
              + "if(el)el.click();return !!el;})()");
            await sleep(300);
          }
        }
      }
    }
    if (flag("mask-bezier", "") !== "") {
      // 1.257：把框点换成贝塞尔，再在检查器那一格里拧一根柄。判四件事：
      // 那一行真的画出四个格子（画不出就是「人能选档却不能调」——只有一端会执行的那种）、
      // 写进引擎的是那一条 clip.mask_stack、没动的那三个柄仍是默认那一份、别的一块一字不动。
      // 判据不看那颗 select 的 value（它是被命令式设上去的，说了不算），只看「画没画出那四格」
      // 与「引擎里那一枚变成什么」——这两样才是界面与引擎各自的回答。
      const label = "框点带贝塞尔";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) { rowOf(trouble); } else {
        const before = await engineGet(`/v1/projects/${PROJECT}`);
        const restore = async () => {
          const latest = await engineGet(`/v1/projects/${PROJECT}`);
          await enginePost(`/v1/projects/${PROJECT}/edits`, {
            request_id: `shape-bezier-restore-${size}-${Date.now()}`,
            expected_revision: latest.revision,
            commands: [{ op: "clip.mask_stack", clip_id: "k2", masks: before.clips["k2"].extra_masks }],
          });
          await cdp.send("Page.reload", {}, 30000);
          await sleep(1200);
        };
        const key0 = (doc) => ((doc.clips["k2"].extra_masks[0].keys) ?? [])[0] ?? null;
        const fail = async (message) => { rowOf(message); await restore(); };
        const probe = "(function(){var want='这一段框点的插值';"
          + "var hit=Array.from(document.querySelectorAll('select'))"
          + ".find(function(n){return (n.getAttribute('aria-label')||'')===want;});"
          + "if(!hit)return {seen:'no-select'};"
          + "return {options:Array.from(hit.options).map(function(o){return o.value}),"
          + " disabled:hit.disabled};})()";
        let seen = { options: [] };
        for (let tryNo = 0; tryNo < 14; tryNo += 1) {
          seen = await evaluate(probe);
          if ((seen.options ?? []).indexOf("bezier") >= 0) break;
          await sleep(400);
        }
        if ((seen.options ?? []).indexOf("bezier") < 0) {
          const declared = await engineGet("/v1/capabilities");
          await fail("界面那一格排不出贝塞尔这一档：引擎声明 "
            + JSON.stringify(declared.mask_box_interpolations ?? null)
            + "，页面读到 " + JSON.stringify(seen));
        } else if (seen.disabled) {
          await fail("那一格是灰的（画出来但按不动）：" + JSON.stringify(seen));
        } else {
          await evaluate("(function(){var want='这一段框点的插值';"
            + "var hit=Array.from(document.querySelectorAll('select'))"
            + ".find(function(n){return (n.getAttribute('aria-label')||'')===want;});"
            + "var set=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set;"
            + "set.call(hit,'bezier');hit.dispatchEvent(new Event('change',{bubbles:true}));"
            + "return 'sent';})()");
          let fields = { count: 0, ids: [] };
          for (let tryNo = 0; tryNo < 12 && fields.count !== 4; tryNo += 1) {
            await sleep(400);
            fields = await evaluate("(function(){var list=Array.from(document.querySelectorAll('input'));"
              + "list=list.filter(function(n){return (n.id||'').indexOf('stack-0-bezier-')===0;});"
              + "var any=Array.from(document.querySelectorAll('input'))"
              + ".filter(function(n){return (n.id||'').indexOf('bezier')>=0;})"
              + ".map(function(n){return n.id;});"
              + "if(!list.length)return {count:0,ids:any.slice(0,8)};"
              + "list[0].scrollIntoView({block:'center'});"
              + "return {count:list.length,ids:list.map(function(n){return n.id;})};})()");
          }
          const mid = await engineGet(`/v1/projects/${PROJECT}`);
          if (fields.count !== 4) {
            await fail("选了贝塞尔却没有那四格：" + JSON.stringify([fields, seen, key0(mid)]));
          } else {
            const typed = await evaluate("(function(){var hit=document.querySelector('input[id$=\"-y1\"]');"
              + "if(!hit)return 'no-input';hit.focus();"
              + "var set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
              + "set.call(hit,'150');hit.dispatchEvent(new Event('input',{bubbles:true}));hit.blur();"
              + "return 'ok';})()");
            await sleep(1300);
            const after = await engineGet(`/v1/projects/${PROJECT}`);
            const key = key0(after) ?? {};
            const handles = key.bezier ?? null;
            const wrote = key.interpolation === "bezier"
              && handles && Math.abs(handles.y1 - 1.5) < 1e-9;
            const defaults = handles && Math.abs(handles.x1 - 1 / 3) < 1e-9
              && Math.abs(handles.x2 - 2 / 3) < 1e-9 && Math.abs(handles.y2 - 1) < 1e-9;
            const others = JSON.stringify((after.clips["k2"].extra_masks[0].keys ?? []).slice(1))
              === JSON.stringify((before.clips["k2"].extra_masks[0].keys ?? []).slice(1));
            const otherBlock = JSON.stringify(after.clips["k2"].extra_masks[1])
              === JSON.stringify(before.clips["k2"].extra_masks[1]);
            if (typed !== "ok" || !wrote || !defaults || !others || !otherBlock) {
              await fail("那四格没有按预期写进引擎：" + JSON.stringify([typed,
                { interpolation: key.interpolation, bezier: handles }, { others, otherBlock }]));
            } else {
              await run(label);
              await restore();
            }
          }
        }
      }
    }

    if (flag("drag-boxkey", "") !== "") {
      // 1.261：条上那一枚框点真的拖一次。四件事一起判：
      //   拖的途中那一枚跟着指针走（屏幕跟手）、引擎里恰好一枚的 at_ticks 变了、
      //   那一枚的另外四个数与别的块一字不动、一次抓取只涨一个版本。
      const label = "拖框点";
      const rowOf = (error) => rows.push({ screen: label, panel: flag("panel", ""), size, data: null, error });
      const trouble = await baseState();
      if (trouble) rowOf(trouble);
      else {
        const before = await engineGet(`/v1/projects/${PROJECT}`);
        const spot = await evaluate("(function(){var el=document.querySelectorAll('.clip-boxkey')[1];"
          + "if(!el)return null;el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();"
          + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),left:r.left};})()");
        if (!spot) rowOf("条上没有中间那一枚框点");
        else {
          const restore = async () => {
            const latest = await engineGet(`/v1/projects/${PROJECT}`);
            await enginePost(`/v1/projects/${PROJECT}/edits`, {
              request_id: `shape-boxkey-restore-${size}-${Date.now()}`,
              expected_revision: latest.revision,
              commands: [{ op: "clip.mask_stack", clip_id: "k2", masks: before.clips["k2"].extra_masks }],
            });
            // 放回是裸 HTTP：页面的 revision 不跟着走，下一次真写就会被 409 静默拒（1.252 那一课）。
            await cdp.send("Page.reload", {}, 30000);
            await waitForClip("k2");
          };
          const fail = async (message) => { rowOf(message); await restore(); };
          await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: spot.x, y: spot.y, button: "left", clickCount: 1 });
          for (let step = 1; step <= 3; step += 1) {
            await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: spot.x + step * 16, y: spot.y, button: "left" });
            await sleep(60);
          }
          const moved = await evaluate("(function(){var el=document.querySelectorAll('.clip-boxkey')[1];"
            + "if(!el)return null;return Math.round(el.getBoundingClientRect().left - " + spot.left + ");})()");
          await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: spot.x + 48, y: spot.y, button: "left" });
          await sleep(900);
          const after = await engineGet(`/v1/projects/${PROJECT}`);
          const was = before.clips["k2"].extra_masks;
          const now = after.clips["k2"].extra_masks;
          const changed = [];
          was.forEach((block, bi) => (block.keys ?? []).forEach((key, ki) => {
            const item = now[bi] && (now[bi].keys ?? [])[ki];
            if (JSON.stringify(item) !== JSON.stringify(key)) {
              changed.push({ bi, ki, from: key.at_ticks, to: item ? item.at_ticks : null,
                onlyTime: item ? JSON.stringify(item) === JSON.stringify({ ...key, at_ticks: item.at_ticks }) : false });
            }
          }));
          const rate = before.settings.frame_rate;
          const frame = Math.round(70560000 * rate.denominator / rate.numerator);
          const one = changed.length === 1;
          const movedToFrame = one && changed[0].to % frame === 0 && changed[0].to !== changed[0].from;
          const inRange = one && changed[0].to >= 0 && changed[0].to <= before.clips["k2"].duration_ticks;
          const others = JSON.stringify(now.filter((_, bi) => bi !== (one ? changed[0].bi : -1)))
            === JSON.stringify(was.filter((_, bi) => bi !== (one ? changed[0].bi : -1)));
          const oneVersion = after.revision === before.revision + 1;
          const follows = typeof moved === "number" && Math.abs(moved - 48) <= 4;
          const stillFields = ["position_ticks", "track_id", "duration_ticks", "source_in_ticks"];
          const movedClip = stillFields.filter((key) => before.clips["k2"][key] !== after.clips["k2"][key]);
          const still = movedClip.length === 0;
          if (!one || !movedToFrame || !inRange || !others || !oneVersion || !follows || !still) {
            await fail("拖那一枚没有按预期落库：" + JSON.stringify({
              one, movedToFrame, inRange, others, oneVersion, follows, movedClip, moved, changed }));
          } else {
            await run(label);
            // 1.262：撤销那一手也在真页面上量一次。那颗按钮走的是 `engine.restore`：
            // 恢复旧内容并生成**新**版本，所以判据不是「版本号退回」，而是
            // 「那一串块逐字段回到拖动前」+「版本号比撤销前更大」。
            const undoSpot = await evaluate("(function(){var b=document.querySelector('[aria-label^=\"撤销：\"]');"
              + "if(!b||b.disabled)return null;b.scrollIntoView({block:'center'});var r=b.getBoundingClientRect();"
              + "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
            if (!undoSpot) {
              await fail("撤销那颗按钮按不到（不在 DOM，或是灰的）");
            } else {
              await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: undoSpot.x, y: undoSpot.y, button: "left", clickCount: 1 });
              await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: undoSpot.x, y: undoSpot.y, button: "left" });
              await sleep(1400);
              const back = await engineGet(`/v1/projects/${PROJECT}`);
              const same = JSON.stringify(back.clips["k2"].extra_masks) === JSON.stringify(was);
              const newer = back.revision > after.revision;
              if (!same || !newer) {
                await fail("撤销那一下没有把那一枚带回原来的格：" + JSON.stringify({
                  same, newer, from: before.revision, dragged: after.revision, undone: back.revision,
                }));
              } else {
                rows.push({ screen: label + "·撤销", panel: "undo", size,
                  data: { same, newer, from: before.revision, dragged: after.revision, undone: back.revision },
                  markers: null, state: null });
                await restore();
              }
            }
          }
        }
      }
    }
    // 1.261 第 0 步：那一枚要能拖，先得有一块摸得到的地方。同屏有三样东西在抢卡片顶上那几像素
    // （名字那一行、左右 7px 的修剪边、底下 37px 的针道），没量之前不许写那一个高度。
    if (BOXGEO.length) {
      const trouble = await baseState();
      const geoSource = fs.readFileSync(GEO, "utf8");
      let data = trouble
        ? { present: false, reason: trouble }
        : await evaluate("(function(){ " + geoSource
          + " return measureBoxkeyGeometry(" + JSON.stringify(BOXGEO) + "); })()");
      if (data && data.present) {
        // 画得出来不等于说得出：把辅助技术那棵树也数一遍（role=img 会把子树标成 presentational，
        // 那时这三枚按钮在 AX 树里一个都不出现）。
        await cdp.send("Accessibility.enable", {}, 30000);
        const tree = await cdp.send("Accessibility.getFullAXTree", {}, 30000);
        // 只数**带子上那一排**：它们的无障碍名里都写着「横向拖只改这一枚的时间」。
        // 检查器里那几颗也带「框点」二字（打点、清空、逐块编辑），混进来就数不出「画了几枚、读屏摸得到几枚」。
        const named = (tree.nodes || []).filter((node) => node.role && node.role.value === "button"
          && node.name && String(node.name.value).indexOf("横向拖只改这一枚的时间") !== -1);
        // getFullAXTree 把**被忽略的**节点也交回来：role=img 那棵子树里按钮的 role 还在，只是
        // ignored=true。按「有没有这个 role」数是数不出「读屏看不见」的——M6 那一刀就是这么溜过去的。
        const live = named.filter((node) => !node.ignored);
        const doc = await engineGet(`/v1/projects/${PROJECT}`);
        const ticks = [];
        ((doc.clips["k2"] || {}).extra_masks || []).forEach((block) => {
          (block.keys || []).forEach((key) => ticks.push(key.at_ticks));
        });
        data = {
          ...data,
          axButtons: live.length,
          axIgnored: named.length - live.length,
          engineKeys: ticks.length,
          engineDistinct: new Set(ticks).size,
        };
      }
      rows.push({ screen: "框点命中盒", panel: "geo", size, data, markers: null, state: null });
    }
    // 1.262 第 0 步：空隙里那一次双击落在谁身上、带子接了指针之后卡片还收不收得到按下。
    if (flag("boxdbl", "") !== "") {
      const troubleForDbl = await baseState();
      const dblSource = fs.readFileSync(DBL, "utf8");
      const data = troubleForDbl
        ? { present: false, reason: troubleForDbl }
        : await evaluate("(function(){ " + dblSource + " return measureBoxkeyDblclick(); })()");
      rows.push({ screen: "框点双击落点", panel: "probe", size, data, markers: null, state: null });
    }
    // 1.260：判据自己也要被量一次。「被画遮住」这一支若只会放行、不会拦，就是一把瞎尺
    // （一个不会动的零与没有这一判同罪）。三种摆位各自的数必须不同：
    //   同一张卡里两段字叠着 → 撞墨 1、遮住 0；
    //   两张卡叠着、上面那张画不透明底 → 撞墨 0、遮住 1；
    //   同样两张卡、上面那张底色透明 → 撞墨 1、遮住 0
    //   （放行的是**不透明**那一条，不是「不是同一张卡」那一条——少这一档就分不清两条规矩）。
    if (flag("judge-selftest", "") !== "") {
      for (const variant of ["same_card", "opaque_cover", "transparent_cover"]) {
        const data = await evaluate("(function(){ " + probeSource + ";" + judgeFixture(variant) +
          " return measureAgentCutUi(); })()");
        rows.push({ screen: "判据自检·" + variant, panel: "judge", size, data, markers: null, state: null });
      }
      // 这一段把 `document.body` 换掉了，量完必须把页面恢复回去——留给下一腿一个脏页面，
      // 下一次红读到的就不是产品（1.252 那条「夹具改完要重载」的同一课）。
      await cdp.send("Page.reload", {}, 30000);
      await sleep(1500);
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

/** 1.260：给「字压字」那一条判据造三种摆位。这里只写形状，不写判据——判据住在探针里，
 *  这三份夹具唯一的用处是问它：同一份几何，把上面那一层的不透明底换一换，数会不会跟着变。
 *  尺寸按「CJK 一格 = font-size」算：八格 14px = 112px，两段字的重叠那一整片落在 64..136，
 *  而上面那张卡的盒子 60..280 把它整个盖住。盖不住、算不出绘制次序这些情形都该退回缺陷。
 *  节点是 createElement/textContent 建出来的，不是拼 HTML 串——量具自己不该在引号上出错。 */
const judgeFixture = (variant) => {
  const paint = variant === "transparent_cover" ? "background:rgba(51,51,51,0)" : "background:#333333";
  const cards = variant === "same_card"
    ? [["jd-card", "left:20px;top:20px;width:260px;height:40px;background:#222222",
        [["jd-a", "left:4px;top:6px"], ["jd-b", "left:44px;top:10px"]]]]
    : [["jd-card", "left:20px;top:20px;width:260px;height:40px;background:#222222",
        [["jd-a", "left:4px;top:6px"]]],
       ["jd-top", "left:60px;top:20px;width:220px;height:40px;" + paint,
        [["jd-b", "left:44px;top:10px"]]]];
  return "(function(){ var cards = " + JSON.stringify(cards) + ";"
    + " document.body.textContent = '';"
    + " var root = document.createElement('div');"
    + " root.className = 'jd-root'; root.style.cssText = 'position:absolute;inset:0;font-size:14px';"
    + " cards.forEach(function (card) {"
    + "   var box = document.createElement('div'); box.className = card[0];"
    + "   box.style.cssText = 'position:absolute;' + card[1];"
    + "   card[2].forEach(function (line) {"
    + "     var span = document.createElement('span'); span.className = line[0];"
    + "     span.style.cssText = 'position:absolute;' + line[1];"
    + "     span.textContent = line[0] === 'jd-a' ? '甲在这里写着字甲在这里' : '乙在这里写着字乙在这里';"
    + "     box.appendChild(span); });"
    + "   root.appendChild(box); });"
    + " document.body.appendChild(root); void document.body.offsetHeight; })();";
};

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
