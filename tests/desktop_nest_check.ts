import assert from "node:assert/strict";
import { Engine, DEFAULT_EFFECTS, type Project, type MutationResult } from "../desktop/src/engine";
import { boot, openProject, openSequence, get, setMode, setClipEffects, runDryRun, clearBatch, editableProject, undo } from "../desktop/src/store";
import { copyClips, pasteCommands } from "../desktop/src/selection";
import { TIMEBASE as T } from "../desktop/src/time";

Object.assign(globalThis, { window: { setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {} }, localStorage: { getItem: () => null, setItem: () => {} }, fetch: async () => new Response("{}") });
const leaf = { id: "inside", asset_id: "image", track_id: "inner", position_ticks: 0, source_in_ticks: 0, duration_ticks: 2*T, effects: DEFAULT_EFFECTS };
const p: Project = { schema_version: 8, id: "p", revision: 1, name: "p", notes: "", settings: { timebase: T, width: 640, height: 360, frame_rate: { numerator: 30, denominator: 1 }, sample_rate: 48000 },
  assets: { image: { id: "image", kind: "image", reference: "metadata", label: "image", duration_ticks: null, verified: null }, nested: { id: "nested", kind: "sequence", reference: "sequence://s", label: "nested", sequence_id: "s", duration_ticks: 2*T, verified: null } },
  tracks: [{ id: "outer", name: "outer", kind: "video", muted: false, hidden: false, volume: 1 }], clips: { outside: { ...leaf, id: "outside", asset_id: "nested", track_id: "outer" } }, sequences: { s: { id: "s", name: "s", duration_ticks: 2*T, tracks: [{ id: "inner", name: "inner", kind: "video", muted: false, hidden: false, volume: 1 }], clips: { inside: leaf } } } };
Engine.prototype.capabilities = async () => ({ features: {}, timebase: T } as never);
Engine.prototype.projects = async () => ({ projects: [] });
Engine.prototype.project = async () => p;
Engine.prototype.assetUrls = async () => ({ assets: {} });
Engine.prototype.jobs = async () => ({ jobs: [] });

async function main() {
  const copied = copyClips(p, ["outside"]);
  assert.deepEqual(copied.assets.map((a) => a.id), ["image", "nested"]);
  assert.equal(copied.sequences?.[0].clips.inside.asset_id, "image");
  const target: Project = { ...p, id: "other", assets: {}, sequences: {}, clips: {}, tracks: [] };
  const commands = pasteCommands(target, copied, 0).commands;
  const nested = commands.find((c) => c.op === "sequence.add")?.sequence as NonNullable<Project["sequences"]>[string];
  const registered = commands.filter((c) => c.op === "asset.register").map((c) => c.asset as typeof p.assets[string]);
  assert.equal(registered.find((a) => a.kind === "sequence")?.sequence_id, nested.id);
  assert(registered.some((a) => a.id === nested.clips.inside.asset_id));
  assert.notEqual(nested.id, "s");
  assert(!pasteCommands(p, copied, 2*T).commands.some((c) => c.op === "sequence.add"), "same project instances share live contents");
  await boot(); await openProject("p"); openSequence("s");
  assert.equal(get().rootProject, p); assert.deepEqual(Object.keys(get().project!.clips), ["inside"]);
  let resolve!: (value: MutationResult) => void;
  const scopes: (string | null | undefined)[] = [];
  Engine.prototype.edit = (_id, _rev, _cmd, _dry, scope) => { scopes.push(scope); return new Promise((done) => { resolve = done; }); };
  setMode("batch"); setClipEffects("inside", { x: .2 }); const running = runDryRun();
  openSequence(null); assert.equal(get().sequenceId, "s", "pending batch blocks scope switch");
  const candidate = structuredClone(p); candidate.revision = 2; candidate.sequences!.s.clips.inside.effects = { ...DEFAULT_EFFECTS, x: .2 };
  resolve({ project: candidate, committed: false, replayed: false }); await running;
  assert.deepEqual(scopes, ["s"]);
  assert.equal(editableProject()?.clips.inside.effects?.x, .2);
  assert.equal(get().rootCandidate?.clips.outside.asset_id, "nested");
  clearBatch(); setMode("instant"); setClipEffects("inside", { y: .3 }); await Promise.resolve();
  openSequence(null); assert.equal(get().sequenceId, "s", "in-flight write blocks scope switch");
  candidate.revision = 2; candidate.sequences!.s.clips.inside.effects!.y = .3;
  resolve({ project: candidate, committed: true, replayed: false });
  for (let i=0;i<20 && get().busy;i++) await Promise.resolve();
  assert.equal(get().sequenceId, "s"); assert.equal(get().project?.clips.inside.effects?.y, .3);
  assert.deepEqual(get().rootProject?.clips, p.clips);
  const restored = { ...p, revision: 3, sequences: {}, clips: { inside: leaf } };
  Engine.prototype.restore = async () => ({ project: restored, committed: true, replayed: false });
  await undo(); assert.equal(get().sequenceId, null); assert.equal(get().project, restored);
  console.log("PASS: nested clipboard dependency remap, live reuse, scoped projection/transport/candidates, pending guards, undo-to-root");
}
void main().catch((error) => { console.error(error); process.exitCode=1; });
