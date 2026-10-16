/**
 * 1.185 的壳层检查：链接状态那条轮询必须只点名选中的那几段，并且调用点真的用这条式子。
 *
 * 为什么单独一档：`preview_manifest` 在 1.183 就有了 `clips` 子集，而检查器那个组件读的只有
 * `revision` 与 `links`——这两个键在子集请求里仍按整份工程给。所以「不点名」不是保守，是白付：
 * 每次换选中都把整份清单搬一遍（两万段工程实测 36.54 MB）。这条检查钉式子与调用点两处，
 * 只改一处都会红。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { linkStatusUrl } from "../desktop/src/linkStatusUrl";

// 壳层检查是被打成 mjs 再跑的，`import.meta.url` 会落在 `build/shell-checks/` 那一层——所以按
// 仓库里既有的办法：拿 `process.cwd()` 试几条候选路径，谁存在用谁。
const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const BASE = "http://127.0.0.1:1";

// 1. 点名的形状：一枚一段、重复只留一次、顺序跟着选中走。
const one = linkStatusUrl(BASE, "p1", 7, null, ["c1"]);
assert.ok(one.includes("preview-manifest?"), one);
assert.ok(one.endsWith("revision=7&clips=c1"), one);
const many = linkStatusUrl(BASE, "p1", 7, null, ["c1", "c2", "c1"]);
assert.ok(many.endsWith("revision=7&clips=c1&clips=c2"), many);

// 2. 没有选中就不点名（那是「整份」那条老路，不是空子集）。
assert.ok(!linkStatusUrl(BASE, "p1", 7, null, []).includes("clips="), "空选中不许发 clips=");

// 3. 合成与工程 id 都要跟着走，且段名要转义——不然一枚带 `&` 的 id 就能改写整条查询。
const nested = linkStatusUrl(BASE, "p 1", 12, "s/2", ["a&b"]);
assert.ok(nested.includes("/v1/projects/p%201/"), nested);
assert.ok(nested.includes("clips=a%26b"), nested);
assert.ok(nested.endsWith("&sequence_id=s%2F2"), nested);

// 4. 调用点真的用这条式子，而不是自己再拼一遍。
assert.ok(
  inspector.includes(
    "linkStatusUrl(appInfo.baseUrl(), project.id, project.revision, app.sequenceId, app.selectedClips)"
  ),
  "检查器那条 fetch 没接上 linkStatusUrl"
);
assert.ok(
  !inspector.includes("/v1/projects/${project.id}/preview-manifest"),
  "检查器还在自己拼 preview-manifest 的 URL（两处式子会分家）"
);
// 它读的确实只有 `revision` 与 `links`——点名子集才因此是零语义变化。
assert.ok(inspector.includes("links: value.links"), "这条轮询读的键变了，本档的前提要重看");

console.log(
  "desktop_linksubset_check: 链接状态那条轮询点名选中片段（含转义与去重），调用点与式子都在一处"
);
