// How many clips does the packaged renderer actually paint?
//
//   node scripts/renderer_scale.cjs --url <renderer url> [--budget 120]
//
// This is the ruler 1.131 was measured with. Everything it reads is browser-side or OS-side, so it
// keeps reporting even when the page itself cannot answer JavaScript — which is exactly the failure
// it exists to catch: at 20,000 clips the pre-1.131 page painted 0 clips, its render process grew
// to ~2.9 GB and vanished, and every `Runtime.evaluate` timed out for 200+ seconds while the frozen
// engine kept answering the same project read in ~0.7 s.
//
// Exit code is 0 only when the page painted at least one clip and stayed answerable; anything else
// prints the sample timeline and exits 1, so a regression here cannot be mistaken for a green run.
//
// Three things this ruler used to get wrong, all of them found by a run that reported "painted 3
// clips in 2 ms" for a 20,000-clip deep link:
//   * the DevTools port was picked by `Date.now() % 97`. Two of my own earlier headless Edges were
//     sitting on the same port (9816 twice), so `/json/list` answered with a stranger's page.
//     Now the port has to bind before the browser is spawned, and the attached target's URL must
//     equal `--url` byte for byte — the app never rewrites its own query string.
//   * the process sample was "the biggest msedge renderer on the machine", which counted every
//     browser the user has open. Now it is the spawned browser plus its own children.
//   * nothing tied the page to the engine, so a stale page and a real one looked alike. Now the
//     engine is read over HTTP first and its clip count and wire size are printed next to the
//     page's own answer.

const { spawn, execFileSync, execSync } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const index = args.indexOf("--" + name);
  return index === -1 ? fallback : args[index + 1];
};
const URL_TO_LOAD = flag("url", "");
const BUDGET = Number(flag("budget", 120));
if (!URL_TO_LOAD) {
  console.error("usage: node scripts/renderer_scale.cjs --url <renderer url> [--budget seconds]");
  process.exit(2);
}
const WANTED_PORT = Number(flag("port", 0));
const PROFILE = path.join(os.tmpdir(), "agentcut-scale-" + Date.now().toString(36));
const EDGE =
  flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe") ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let PORT = 0;

function listenable(port) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once("error", () => resolve(false));
    probe.once("listening", () => probe.close(() => resolve(true)));
    probe.listen(port, "127.0.0.1");
  });
}

// A port taken by a headless browser from an earlier run is the whole reason this file exists in
// its current shape: `/json/list` on that port answers with the stranger's page, and the stranger
// looks healthy.
async function pickPort() {
  if (WANTED_PORT) return WANTED_PORT;
  for (let candidate = 9800 + (Date.now() % 97); candidate < 9800 + 400; candidate += 1) {
    if (await listenable(candidate)) return candidate;
  }
  throw new Error("no free DevTools port under 10200");
}

function request(url, headers) {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { headers: headers || {} }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject);
    req.setTimeout(60000, () => req.destroy(new Error("engine read timed out")));
    req.end();
  });
}

// What the engine says the project holds. Printed next to what the page says it painted.
async function engineFacts() {
  const page = new URL(URL_TO_LOAD);
  const base = page.searchParams.get("engine");
  const token = page.searchParams.get("token");
  const id = page.searchParams.get("project");
  if (!base || !token || !id) return { skipped: "the url has no engine/token/project" };
  const headers = { Authorization: `Bearer ${token}` };
  const project = await request(`${base.replace(/\/$/, "")}/v1/projects/${id}`, headers);
  const info = await request(`${base.replace(/\/$/, "")}/v1/info`, headers);
  const body = JSON.parse(project.body.toString("utf8"));
  return {
    http: project.status,
    clips: (body.clips || []).length,
    wire_bytes: project.body.length,
    instance: JSON.parse(info.body.toString("utf8")).instance,
    app_version: JSON.parse(info.body.toString("utf8")).app_version,
  };
}

function listTargets() {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: "127.0.0.1", port: PORT, path: "/json/list", method: "GET" }, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve(JSON.parse(data)));
    });
    req.on("error", reject);
    req.setTimeout(15000, () => req.destroy(new Error("timeout")));
    req.end();
  });
}

const PS = path.join(os.tmpdir(), "agentcut-scale.ps1");
fs.writeFileSync(
  PS,
  "param([string]$Profile)\n" +
    "$rows = @(Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Profile) } | ForEach-Object {" +
    " $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue;" +
    " if ($p) { [pscustomobject]@{Id=$_.ProcessId; User=[math]::Round($_.UserModeTime/1e7,2); Work=[math]::Round($p.WorkingSet64/1MB,0)} } })\n" +
    "[pscustomobject]@{top=($rows | Sort-Object Work -Descending | Select-Object -First 1); total_mb=[math]::Round(($rows | Measure-Object Work -Sum).Sum,0);" +
    " total_cpu=[math]::Round(($rows | Measure-Object User -Sum).Sum,2); n=$rows.Count} | ConvertTo-Json -Compress",
  "utf8"
);

// Only the processes started from this run's profile directory. Chromium's renderers carry the
// browser's `--user-data-dir` in their own command line, so the profile's random suffix is the
// reliable label — matched on the suffix because the same directory is spelled with an 8.3 prefix
// by the launcher and in full form by the children. ParentProcessId is not reliable (it missed the
// renderers and reported the 176 MB browser while the renderer was growing past a gigabyte), and
// "the biggest msedge on the machine" was worse still: that is the user's browser, not this
// measurement.
function biggestRenderer() {
  try {
    const raw = execFileSync("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS, "-Profile", path.basename(PROFILE)], {
      encoding: "utf8",
      timeout: 90000,
    }).trim();
    if (!raw) return { n: 0 };
    const row = JSON.parse(raw);
    return { n: row.n, own_total_mb: row.total_mb, own_total_cpu: row.total_cpu, top_id: row.top ? row.top.Id : null, top_mb: row.top ? row.top.Work : null };
  } catch (error) {
    return { error: String(error.message).slice(0, 60) };
  }
}

async function main() {
  PORT = await pickPort();
  const engine = await engineFacts();
  console.log("engine says: " + JSON.stringify(engine));
  const edge = spawn(
    EDGE,
    ["--headless=new", `--remote-debugging-port=${PORT}`, "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--user-data-dir=${PROFILE}`, URL_TO_LOAD],
    { stdio: "ignore" }
  );
  const started = Date.now();
  const samples = [];
  const watched = [];
  let socket = null;
  let verdict = "never-painted";
  try {
    let target = null;
    for (let attempt = 0; attempt < 120 && !target; attempt += 1) {
      await sleep(500);
      let pages = [];
      try {
        pages = (await listTargets()).filter((item) => item.type === "page");
      } catch {}
      target = pages.find((item) => item.url === URL_TO_LOAD);
      if (!target && pages.length) {
        const foreign = pages.map((item) => item.url).join(" ").slice(0, 160);
        if (attempt > 20) throw new Error(`this browser never opened the asked-for page; its tabs are: ${foreign}`);
      }
    }
    if (!target) throw new Error("the packaged renderer never opened a page target for this url");

    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", reject, { once: true });
    });
    let nextId = 1;
    const pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        pending.get(message.id)(message);
        pending.delete(message.id);
      }
    });
    const send = (method, params, budget) =>
      new Promise((resolve, reject) => {
        const id = (nextId += 1);
        const timer = setTimeout(() => {
          if (pending.has(id)) {
            pending.delete(id);
            reject(new Error("no answer"));
          }
        }, budget);
        pending.set(id, (message) => {
          clearTimeout(timer);
          resolve(message);
        });
        socket.send(JSON.stringify({ id, method, params: params || {} }));
      });
    const evaluate = async (expression, budget) => {
      const answer = await send("Runtime.evaluate", { expression, returnByValue: true }, budget);
      return answer.result && answer.result.result ? answer.result.result.value : null;
    };

    await send("Runtime.enable", {}, 20000);
    await send("Page.enable", {}, 20000);
    // When the page cannot answer JavaScript, the only remaining witnesses are the browser's own
    // request log and its console: did the project ever arrive, and did anything throw?
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.method === "Network.responseReceived") {
        const info = message.params.response || {};
        // Sizes are what identify the culprit: a 12 MB answer that keeps arriving is a poll, not a fetch.
        if ((Number(info.encodedDataLength) || 0) > 1_000_000 || /\/v1\//.test(String(info.url || ""))) {
          watched.push(["resp", String(info.url || "").replace(/^http:\/\/[^/]+/, "").slice(0, 70), info.status, Math.round((Number(info.encodedDataLength) || 0) / 1024)]);
        }
      }
      if (message.method === "Network.loadingFinished") {
        watched.push(["done", message.params.requestId, message.params.encodedDataLength]);
      }
      if (message.method === "Network.loadingFailed") {
        watched.push(["failed", message.params.requestId, message.params.errorText]);
      }
      if (message.method === "Log.entryAdded") {
        watched.push(["console", message.params.entry.level, String(message.params.entry.text).slice(0, 160)]);
      }
      if (message.method === "Runtime.exceptionThrown") {
        const detail = message.params.exceptionDetails || {};
        watched.push(["throw", String(detail.text).slice(0, 120), String((detail.exception && detail.exception.description) || "").slice(0, 240)]);
      }
    });
    await send("Network.enable", {}, 20000);
    await send("Log.enable", {}, 20000);
    try {
      await send("Emulation.setFocusEmulationEnabled", { enabled: true }, 20000);
      await send("Page.setWebLifecycleState", { state: "active" }, 20000);
    } catch {}

    const probe =
      "JSON.stringify({href: location.href, clips: document.querySelectorAll('.clip').length, nodes: document.getElementsByTagName('*').length," +
      " lanes: document.querySelectorAll('.tl-lane').length, note: (document.querySelector('.tl-window-note')||{}).textContent||null})";
    while (Date.now() - started < BUDGET * 1000) {
      const began = Date.now();
      let answer = null;
      let failure = "";
      try {
        answer = JSON.parse(await evaluate(probe, 5000));
      } catch (error) {
        failure = "TIMEOUT";
      }
      if (answer && answer.href !== URL_TO_LOAD) {
        failure = "WRONG_PAGE";
        answer = null;
      }
      const alive = await listTargets().catch(() => []);
      const page = alive.find((item) => item.url === URL_TO_LOAD);
      samples.push({ at_ms: Date.now() - started, probe_ms: Date.now() - began, answer, failure, target: page ? "alive" : "GONE", proc: biggestRenderer() });
      console.log(JSON.stringify(samples[samples.length - 1]));
      if (answer && answer.clips > 0) {
        verdict = "painted";
        break;
      }
      await sleep(4000);
    }
  } finally {
    if (socket) socket.close();
    try {
      execSync(`taskkill /PID ${edge.pid} /T /F`, { stdio: "ignore" });
    } catch {}
    try {
      fs.rmSync(PROFILE, { recursive: true, force: true, maxRetries: 3, retryDelay: 300 });
      fs.rmSync(PS, { force: true });  // 那支临时 powershell 脚本同理：写在临时地方就得还
    } catch {}
  }

  const last = samples[samples.length - 1] || {};
  const painted = last.answer ? last.answer.clips : null;
  console.log(
    JSON.stringify({
      verdict,
      samples: samples.length,
      seconds: Math.round((Date.now() - started) / 1000),
      painted,
      engine,
      watched: watched.filter((row) => row[0] === "resp" || row[0] === "console" || row[0] === "throw").slice(0, 40),
      big_responses: watched.filter((row) => row[0] === "done" && row[2] > 1_000_000).length,
      nodes: last.answer ? last.answer.nodes : null,
      note: last.answer ? last.answer.note : null,
      own_process_peak: samples.map((item) => item.proc).filter(Boolean).sort((a, b) => (b.own_total_mb || 0) - (a.own_total_mb || 0))[0],
    })
  );
  process.exit(verdict === "painted" ? 0 : 1);
}

main().catch((error) => {
  console.error("FAILED:", error && error.message ? error.message : error);
  process.exit(1);
});
