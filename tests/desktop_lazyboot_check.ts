/** 1.308「打开窗口不等于启动引擎」这一档：外壳即时、引擎只在第一次真使用后于后台起来。
 *
 * 要挡的五件事，都是「看起来对、跑起来错」的那一类：
 * ① 窗口一开就有人替用户起一台引擎进程——机器上多一个看不见的后台服务，正是被要求取消的行为；
 * ② 引擎没起时去读列表：不许回答「还没有工程」（那是假话），也不许拿空地址把请求发出去；
 *    要的是排在同一个入口上等地址落地——这里认的是「真 fetch 一次都没发生」，不是认我自己的重写；
 * ③ 启动失败换成一块全屏门：界面要照常能用，说一次拒绝，下一次点击就是重试；
 * ④ 反复点击拉起好几台引擎；
 * ⑤ 全屏门与开机 spawn 真的从代码里拿掉了。
 * 用的是渲染端真的 store、真的 Engine 客户端、真的那条 fetch——只把桌面外壳（window.desktop）
 * 和 fetch 换成假的，量的就是应用自己那条调用链。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { bridge } from "../desktop/src/bridge";
import * as store from "../desktop/src/store";

declare const REPO_ROOT: string;

const source = (relative: string) => readFileSync(REPO_ROOT + relative, "utf-8");

const ENGINE_BASE = "http://127.0.0.1:8765";
const PROJECT_ROW = { id: "p1", name: "第一部", revision: 3, clips: 2, assets: 1, content_ticks: 70560000 };

/** 每一次真发出去的请求都记在这儿：排队没排住，第一个红就从这条数组里跳出来。 */
const sent: string[] = [];

async function fakeFetch(input: string | URL) {
  const url = String(input);
  sent.push(url);
  const body = url.endsWith("/v1/capabilities")
    ? { app_version: "1.308.0", timebase: 70560000, features: { media_probe: true } }
    : url.startsWith(ENGINE_BASE + "/v1/projects")
      ? { projects: [PROJECT_ROW] }
      : {};
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

const listeners: { type: string; fn: (event: unknown) => void }[] = [];
let starts = 0;
let asks = 0;
let spawnFails = true;
// 主进程那侧的事实：引擎在不在这台机器上跑着。窗口刚开时答案必须是「不在」。
let live: { running: boolean; info?: unknown } = { running: false };

const fakeShell = {
  async startEngine() {
    starts += 1;
    if (spawnFails) return { ok: false, error: "引擎起不来：数据目录被占用" };
    const info = { port: 8765, base_url: ENGINE_BASE, token: "tk" };
    live = { running: true, info };
    return { ok: true, info };
  },
  async engineStatus() {
    asks += 1;
    return live;
  },
  async token() {
    return "tk";
  },
  async control() {
    return { maximized: false, fullscreen: false };
  },
  async windowState() {
    return { maximized: false, fullscreen: false };
  },
  async resize() {
    return null;
  },
  async openMedia() {
    return { cancelled: true };
  },
  async pickOutputFolder() {
    return { cancelled: true };
  },
  async setOutputFolder(folder: string) {
    return { ok: true, folder };
  },
  async readSettings() {
    return { outputFolder: "", mediaFolders: [] };
  },
  async pickMediaRoot() {
    return { cancelled: true };
  },
  async showItem() {
    return false;
  },
  async openExternal() {
    return false;
  },
  async copyText() {
    return true;
  },
  async restartEngine() {
    return { ok: false };
  },
  async appInfo() {
    return { version: "test", electron: "test", userData: "", library: [], enginePath: "" };
  },
  onEngineReady() {
    return () => {};
  },
  onEngineError() {
    return () => {};
  },
  onMediaProgress() {
    return () => {};
  },
};

Object.assign(globalThis, {
  window: {
    addEventListener: (type: string, fn: (event: unknown) => void) => {
      listeners.push({ type, fn });
    },
    removeEventListener: (type: string, fn: (event: unknown) => void) => {
      const at = listeners.findIndex((row) => row.type === type && row.fn === fn);
      if (at >= 0) listeners.splice(at, 1);
    },
    setTimeout: () => 1,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    dispatchEvent: () => true,
  },
  localStorage: { getItem: () => null, setItem: () => {} },
  location: { search: "" },
  document: { documentElement: { dataset: {} as Record<string, string> } },
  fetch: fakeFetch,
  // 桌面外壳在场：isNative() 当场读这一个对象，不是 import 那一刻记死的快照。
  desktop: fakeShell,
});
// 渲染端只经 bridge 这一个入口拿桌面能力：把假外壳装在它身上，量的就是应用自己那条调用链。
Object.assign(bridge, fakeShell);

function gesture(type: "pointerdown" | "keydown", expectListener = true) {
  const rows = listeners.filter((row) => row.type === type);
  if (expectListener) assert.ok(rows.length, `界面该还挂着第一次真使用的监听（${type}）`);
  for (const row of rows) row.fn({ target: null });
}

async function rest() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  // ① 打开窗口：外壳出来了，一台引擎都没起，一个请求都没发出去。
  await store.openShell();
  await rest();
  assert.equal(starts, 0, "openShell 不该替用户起引擎进程");
  assert.equal(store.get().phase, "idle", "没被用过之前，界面状态该是 idle");
  assert.equal(sent.length, 0, "引擎没起时一个请求都不许发出去");
  assert.equal(asks, 1, "外壳该问一句「那台还在不在」，问过而不在，就不能自己起一台");

  // ② 引擎还没起时读列表：排在队上等，不许先回答一个空列表骗人。
  const queued = store.refreshProjects().catch(() => undefined);
  await rest();
  assert.equal(sent.length, 0, "排队的读取不许把请求发到一个还不存在的地址上");
  assert.equal(store.get().projects.length, 0, "引擎没应答时不该有任何工程被读回来");
  assert.equal(starts, 0, "读列表本身不算「用户真的用了」，不能因此起进程");

  // ③ 第一次真使用（一次 pointerdown）才起进程——这一台起不来。
  gesture("pointerdown");
  const alsoA = store.ensureEngine();
  const alsoB = store.ensureEngine();
  assert.equal(starts, 1, `同一时刻点多少下，都只起一台（量到 ${starts} 台）`);
  await Promise.all([alsoA.catch(() => undefined), alsoB.catch(() => undefined)]);
  await rest();
  await rest();
  assert.equal(starts, 1, "第一次真使用才该起引擎，且只起一台");
  assert.notEqual(store.get().phase, "failed", "起不来不该换成一块全屏门");
  assert.equal(store.get().phase, "idle", "起不来要退回 idle，等下一次点击重试");
  assert.ok(store.get().toasts.some((row) => row.kind === "error"), "起不来要当场说一次");
  assert.equal(sent.length, 0, "起不来时那条排队的读取也不许编出工程");
  await queued;

  // ④ 下一次点击就是重试：真起来了，排在后面的请求这才落地。
  spawnFails = false;
  gesture("keydown");
  await rest();
  await rest();
  assert.equal(store.get().phase, "ready", "重试成功后界面该读到引擎");
  assert.deepEqual(sent.map((url) => url.replace(ENGINE_BASE, "")), ["/v1/capabilities", "/v1/projects?limit=100"],
    "地址落地后该按能力、工程列表的顺序发请求，一次不多");
  assert.equal(store.get().projects.length, 1, "工程要在那条排队读取落地后被读回来");
  assert.equal(store.get().projects[0].id, "p1");
  assert.equal((globalThis as unknown as { document: { documentElement: { dataset: Record<string, string> } } })
    .document.documentElement.dataset.appVersion, "1.308.0", "构建标记该由 capabilities 落地");

  // ⑤ 就绪之后再多点几下，也不该再多起一台（前面共起过两次：一次失败、一次成功）。
  gesture("pointerdown", false);
  gesture("keydown", false);
  await rest();
  assert.equal(starts, 2, "就绪之后再点不该重起引擎");

  // ⑥ 界面重载（刷新、深链跳转）之后：那台已经被用户用起来的引擎该直接接回去，
  // 既不再起一台，也不许再要人点一下才看见自己的工程。
  await store.openShell();
  await rest();
  assert.equal(starts, 2, "重载后接回的是同一台引擎，不该再起第二台");
  assert.equal(store.get().phase, "ready", "重载后第一眼就该重新看见工程列表");
  assert.equal(store.get().projects.length, 1, "接回去那一趟要把列表读回来");

  // ⑦ 全屏门真的从界面上拿掉了：不留组件、不留样式、主进程也不再开机就 spawn。
  const app = source("desktop/src/App.tsx");
  assert.ok(!/BootScreen|FailedScreen|boot-screen/.test(app), "App.tsx 还留着启动门");
  assert.ok(!/\.boot-screen|\.boot-card/.test(source("desktop/src/styles.css")), "启动门的样式还留在表里");
  const electronMain = source("desktop/electron/main.ts");
  const readyBlock = electronMain.slice(electronMain.indexOf("app.whenReady()"));
  assert.ok(!/startBackend\(/.test(readyBlock.slice(0, 400)), "whenReady 还在开机就拉引擎");
  assert.ok(/let engineWanted = false;/.test(electronMain), "崩溃监督该认「用户真要用过」这一个开关");

  console.log(`desktop_lazyboot_check: 外壳即时出、${starts} 次启动尝试、${sent.length} 条请求都在地址落地之后`);
}

await main();
