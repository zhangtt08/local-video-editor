export const TIMEBASE = 70_560_000;
export type Fraction = { numerator: number; denominator: number };

export const ticks = (seconds: number): number => Math.round(seconds * TIMEBASE);
export const seconds = (value: number): number => value / TIMEBASE;

export const frameTicks = (rate: Fraction): number =>
  Math.round((TIMEBASE * rate.denominator) / rate.numerator);

export const sampleTicks = (sampleRate: number): number => Math.round(TIMEBASE / sampleRate);

/** 把 tick 对齐到最近的帧/采样边界；direction = -1 向下、0 最近、1 向上。 */
export function align(value: number, quantum: number, direction = 0): number {
  if (quantum <= 0) return value;
  const raw = value / quantum;
  const stepped =
    direction < 0 ? Math.floor(raw) : direction > 0 ? Math.ceil(raw) : Math.round(raw);
  return Math.max(0, stepped * quantum);
}

export function timecode(value: number, rate: Fraction, withFrames = true): string {
  const total = seconds(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = Math.floor(total % 60);
  const base = [hours, minutes, secs].map((item) => String(item).padStart(2, "0")).join(":");
  if (!withFrames) return base;
  const fps = rate.numerator / rate.denominator;
  const frames = Math.floor((total - Math.floor(total)) * fps + 1e-6);
  return `${base}:${String(frames).padStart(2, "0")}`;
}

export function humanDuration(value: number): string {
  const total = seconds(value);
  if (total < 1) return `${Math.round(total * 1000)} 毫秒`;
  if (total < 60) return `${total.toFixed(1)} 秒`;
  const minutes = Math.floor(total / 60);
  const secs = Math.round(total % 60) % 60;
  if (minutes < 60) return `${minutes} 分 ${String(secs).padStart(2, "0")} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

export function rateLabel(rate: Fraction): string {
  const value = rate.numerator / rate.denominator;
  return Math.abs(value - Math.round(value)) < 0.001
    ? `${Math.round(value)} fps`
    : `${value.toFixed(3)} fps`;
}

export const prettyBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

/** Constant-rate piece issued by the engine; the exporter reads the identical list. */
export type RampPiece = { at: number; duration: number; source_at: number; source_duration: number; rate_percent: number };

/** Rate and source offset (seconds) at `at` seconds inside a clip — the segment plan, not an easing. */
export function pacing(
  speedPercent: number,
  ramp: RampPiece[] | null | undefined,
  at: number,
): { rate: number; source: number } {
  const base = speedPercent / 100;
  if (!ramp?.length) return { rate: base, source: Math.max(0, at) * base };
  const piece = ramp.find((mark) => at < mark.at + mark.duration) ?? ramp[ramp.length - 1];
  const rate = piece.rate_percent / 100;
  const source = piece.source_at + Math.max(0, at - piece.at) * rate;
  return { rate, source: Math.min(source, piece.source_at + piece.source_duration) };
}
