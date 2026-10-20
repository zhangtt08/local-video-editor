/**
 * 入场 / 出场动画预设：一条片段开头或结尾的几枚普通关键帧。
 *
 * 这里**不是**第二套动画引擎：预设只算出「该在哪一格写什么值」，交出去的仍是普通的
 * `keyframe.set`，一次一批、一个 revision、撤销一次回一步。导出与预览读的还是引擎那份曲线。
 *
 * 每种预设只描述动画起点那一格（终格永远是片段自己的静态值），所以「片段已经缩到 0.8」
 * 这类状态不会被预设抹平：放大那一档从 0.8×0.86 起，收在 0.8。
 */
import type { Clip, Command } from "./engine";
import { TIMEBASE } from "./time";

export type MotionSide = "in" | "out";

export type MotionPresetId = "fade" | "rise" | "drop" | "zoom_in" | "zoom_out" | "slide_left" | "slide_right";

/** 下拉里的顺序：先最常用的，再是位移与缩放。名字只说人看得见的效果。 */
export const MOTION_PRESETS: { id: MotionPresetId; label: string; hint: string }[] = [
  { id: "fade", label: "淡入淡出", hint: "只动透明" },
  { id: "rise", label: "上浮", hint: "从下方 8% 处漂上来，同时淡入" },
  { id: "drop", label: "下压", hint: "从上方 8% 处落下来，同时淡入" },
  { id: "zoom_in", label: "放大", hint: "从 86% 放大到位，同时淡入" },
  { id: "zoom_out", label: "缩小", hint: "从 114% 收到位，同时淡入" },
  { id: "slide_left", label: "左滑", hint: "从左边 10% 处滑进来，同时淡入" },
  { id: "slide_right", label: "右滑", hint: "从右边 10% 处滑进来，同时淡入" },
];

type Four = { x: number; y: number; scale: number; opacity: number };

const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));

/** 起点那一格的四个数；没提到的属性保持静态值（那条曲线因此一根针都不写）。 */
const START: Record<MotionPresetId, (base: Four) => Partial<Four>> = {
  fade: () => ({ opacity: 0 }),
  rise: (base) => ({ opacity: 0, y: clamp(base.y + 0.08, -1, 1) }),
  drop: (base) => ({ opacity: 0, y: clamp(base.y - 0.08, -1, 1) }),
  zoom_in: (base) => ({ opacity: 0, scale: clamp(base.scale * 0.86, 0.05, 4) }),
  zoom_out: (base) => ({ opacity: 0, scale: clamp(base.scale * 1.14, 0.05, 4) }),
  slide_left: (base) => ({ opacity: 0, x: clamp(base.x - 0.1, -1, 1) }),
  slide_right: (base) => ({ opacity: 0, x: clamp(base.x + 0.1, -1, 1) }),
};

/** 预设自己的时长只在这里换算成一帧的整数倍：引擎按帧判对齐，半帧的窗口会被整批拒掉。 */
export function motionSpan(durationSeconds: number, frame: number): number {
  return Math.max(frame, Math.round((durationSeconds * TIMEBASE) / frame) * frame);
}

/**
 * 一条片段的一次入场（或出场）动画要写的命令。
 *
 * 入场：起点那格写预设值、`span` 那一格写静态值（之后一直保持）。
 * 出场：`duration - span` 那一格写静态值、末格写预设值。
 * 只有值真的不同才写——「淡入」套在已经全透明的片段上不该写两枚等值的针。
 */
export function motionCommands(
  clip: Clip,
  side: MotionSide,
  preset: MotionPresetId,
  durationSeconds: number,
  frame: number,
): Command[] {
  const span = Math.min(motionSpan(durationSeconds, frame), clip.duration_ticks);
  const base: Four = {
    x: clip.effects?.x ?? 0,
    y: clip.effects?.y ?? 0,
    scale: clip.effects?.scale ?? 1,
    opacity: clip.effects?.opacity ?? 1,
  };
  const start: Four = { ...base, ...START[preset](base) };
  const atStart = side === "in" ? 0 : clip.duration_ticks - span;
  const atEnd = side === "in" ? span : clip.duration_ticks;
  const commands: Command[] = [];
  for (const property of ["x", "y", "scale", "opacity"] as const) {
    if (start[property] === base[property]) continue;
    // 入场：起点是预设值、终点回到静态值；出场反过来（静态值在前、预设值收在末格）。
    const from = side === "in" ? start[property] : base[property];
    const to = side === "in" ? base[property] : start[property];
    commands.push({
      op: "keyframe.set",
      clip_id: clip.id,
      keyframe: { property, at_ticks: atStart, value: from, interpolation: "ease" },
    });
    commands.push({
      op: "keyframe.set",
      clip_id: clip.id,
      keyframe: { property, at_ticks: atEnd, value: to, interpolation: "ease" },
    });
  }
  return commands;
}

/** 界面给人看的那一句：写了几条曲线、覆盖哪几格。空命令时说明为什么没动。 */
export function motionWords(commands: Command[], clip: Clip, side: MotionSide, seconds: number): string {
  if (!commands.length) return "这段的静态值已经就是预设的终点，没有要写的针。";
  const properties = new Set(commands.map((command) => (command.keyframe as { property: string }).property));
  return `${side === "in" ? "入场" : "出场"}：${seconds.toFixed(2)} 秒、${properties.size} 条曲线、${commands.length} 枚针`;
}

