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

const { spawn, execFileSync, execSync } = require("node:child_process");
const fs = require("node:fs");
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
const PORT = Number(flag("port", 9800 + (Date.now() % 97)));
const PROFILE = path.join(os.tmpdir(), "agentcut-scale-" + Date.now().toString(36));
const EDGE =
  flag("edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe") ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
  "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue;" +
    " if ($p) { [pscustomobject]@{Id=$_.ProcessId; User=[math]::Round($_.UserModeTime/1e7,2); Work=[math]::Round($p.WorkingSet64/1MB,0);" +
    " R=[bool]($_.CommandLine -match '--type=renderer')} } } | Sort-Object Work -Descending | Select-Object -First 3 | ConvertTo-Json -Compress",
  "utf8"
);

function biggestRenderer() {
  try {
    const raw = execFileSync("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS], { encoding: "utf8", timeout: 90000 }).trim();
    const list = JSON.parse(raw);
    const rows = Array.isArray(list) ? list : [list];
    const top = rows[0] || {};
    return { id: top.Id, work_mb: top.Work, cpu_seconds: top.User };
  } catch (error) {
    return { error: String(error.message).slice(0, 60) };
  }
}

async function main() {
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
      try {
        target = (await listTargets()).find((item) => item.type === "page" && item.url.includes("index.html"));
      } catch {}
    }
    if (!target) throw new Error("the packaged renderer never opened a page target");

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
      "JSON.stringify({clips: document.querySelectorAll('.clip').length, nodes: document.getElementsByTagName('*').length," +
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
      const alive = await listTargets().catch(() => []);
      const page = alive.find((item) => item.type === "page");
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
      watched: watched.filter((row) => row[0] === "resp" || row[0] === "console" || row[0] === "throw").slice(0, 40),
      big_responses: watched.filter((row) => row[0] === "done" && row[2] > 1_000_000).length,
      nodes: last.answer ? last.answer.nodes : null,
      note: last.answer ? last.answer.note : null,
      worst_process: samples.map((item) => item.proc).filter(Boolean).sort((a, b) => (b.work_mb || 0) - (a.work_mb || 0))[0],
    })
  );
  process.exit(verdict === "painted" ? 0 : 1);
}

main().catch((error) => {
  console.error("FAILED:", error && error.message ? error.message : error);
  process.exit(1);
});
