import assert from "node:assert/strict";
import { Engine, DEFAULT_EFFECTS, type Project, type MutationResult, type Command } from "../desktop/src/engine";
import { boot, openProject, get, setMode, setClipEffects, runDryRun, clearBatch, editableProject } from "../desktop/src/store";
import { TIMEBASE as T } from "../desktop/src/time";

// Only transport is controlled: this exercises the real store's scheduling and stale responses.
Object.assign(globalThis, {
  window: { setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {} },
  localStorage: { getItem: () => null, setItem: () => {} },
  fetch: async () => new Response(JSON.stringify({ media_ready: false, render_ready: false })),
});
const p: Project = { schema_version: 7, id: "p", revision: 1, name: "p", notes: "", settings: { timebase: T, width: 640, height: 360, frame_rate: { numerator: 30, denominator: 1 }, sample_rate: 48000 }, assets: {}, tracks: [], clips: { c: { id: "c", asset_id: "a", track_id: "v", position_ticks: 0, duration_ticks: T, source_in_ticks: 0, effects: DEFAULT_EFFECTS } } };
Engine.prototype.capabilities = async () => ({ features: {}, timebase: T } as never);
Engine.prototype.projects = async () => ({ projects: [] });
Engine.prototype.project = async () => p;
Engine.prototype.assetUrls = async () => ({ assets: {} });
Engine.prototype.jobs = async () => ({ jobs: [] });

type Pending = { revision: number; commands: Command[]; resolve: (value: MutationResult) => void; reject: (e: Error) => void };
const pending: Pending[] = [];
Engine.prototype.edit = (_id, revision, commands) => new Promise((resolve, reject) => pending.push({ revision, commands, resolve, reject }));
const result = (x: number, y = 0): MutationResult => ({ project: { ...p, revision: 2, clips: { ...p.clips, c: { ...p.clips.c, effects: { ...DEFAULT_EFFECTS, x, y } } } }, committed: false, replayed: false });

async function main() {
  await boot(); await openProject("p"); setMode("batch");
  setClipEffects("c", { x: .1 });
  assert(get().dryRunBusy);
  const old = runDryRun();
  assert.deepEqual(pending[0].commands, [{ op: "clip.patch", clip_id: "c", effects: { x: .1 } }]);
  setClipEffects("c", { y: .2 }); const newer = runDryRun();
  pending[0].resolve(result(.1)); await old;
  assert(get().dryRunBusy, "old response must not unlock controls while the latest request is pending");
  assert.equal(get().candidate, null);
  pending[1].resolve(result(.1, .2)); await newer;
  assert.equal(editableProject()?.clips.c.effects?.y, .2);
  assert(!get().dryRunBusy);
  setClipEffects("c", { x: .3 });
  assert.equal(editableProject(), null);
  assert.equal(editableProject(get(), true)?.clips.c.effects?.x, .1, "keep validated display while waiting");
  const staleFailure = runDryRun();
  setClipEffects("c", { y: .4 }); const latest = runDryRun();
  pending[3].resolve(result(.3, .4)); await latest;
  pending[2].reject(new Error("old transport failure")); await staleFailure;
  assert.equal(editableProject()?.clips.c.effects?.y, .4);
  assert.equal(get().dryRunError, "");
  const clearing = runDryRun(); clearBatch();
  pending[4].reject(new Error("late failure after discard")); await clearing;
  assert(!get().dryRunBusy && !get().dryRunError && get().candidate === null);
  assert.equal(get().project, p);
  setMode("instant"); setClipEffects("c", { x: .5 }); setClipEffects("c", { y: .6 });
  await Promise.resolve();
  assert.equal(pending.length, 6, "the second instantaneous request waits for the first");
  assert.deepEqual(pending[5].commands, [{ op: "clip.patch", clip_id: "c", effects: { x: .5 } }]);
  pending[5].resolve({ ...result(.5), committed: true });
  for (let i = 0; i < 20 && pending.length < 7; i++) await Promise.resolve();
  assert.equal(pending[6].revision, 2);
  assert.deepEqual(pending[6].commands, [{ op: "clip.patch", clip_id: "c", effects: { y: .6 } }]);
  const both = result(.5, .6); both.project.revision = 3;
  pending[6].resolve({ ...both, committed: true });
  for (let i = 0; i < 20 && get().project?.revision !== 3; i++) await Promise.resolve();
  assert.equal(get().project?.clips.c.effects?.x, .5);
  assert.equal(get().project?.clips.c.effects?.y, .6);
  console.log("PASS: sparse commands, latest dry-run, stable pending display, discard, late failures, instant queue");
}
void main().catch((error) => { console.error(error); process.exitCode = 1; });
