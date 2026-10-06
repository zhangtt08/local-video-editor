/**
 * Colour scopes for the preview monitor: histogram, RGB waveform and vectorscope.
 *
 * All measurement is pure math over RGBA pixels, so `tests/scope_check.ts` can assert
 * it in Node without a browser. The panel only feeds it a frame it already shows.
 */

export type Rgba = { data: Uint8ClampedArray; width: number; height: number };

export type Histogram = {
  /** RGB plus luma, each normalized to 0..1 with `bins` buckets. */
  r: Float32Array;
  g: Float32Array;
  b: Float32Array;
  luma: Float32Array;
  /** 0..1 clipping share per channel, useful for a warning badge. */
  clipped: { r: number; g: number; b: number };
};

export function histogram(frame: Rgba, bins = 64): Histogram {
  const r = new Float32Array(bins);
  const g = new Float32Array(bins);
  const b = new Float32Array(bins);
  const luma = new Float32Array(bins);
  let cr = 0;
  let cg = 0;
  let cb = 0;
  const total = frame.width * frame.height;
  for (let i = 0; i < frame.data.length; i += 4) {
    const red = frame.data[i];
    const green = frame.data[i + 1];
    const blue = frame.data[i + 2];
    if (red === 255) cr += 1;
    if (green === 255) cg += 1;
    if (blue === 255) cb += 1;
    const scale = bins / 256;
    r[Math.min(bins - 1, (red * scale) | 0)] += 1;
    g[Math.min(bins - 1, (green * scale) | 0)] += 1;
    b[Math.min(bins - 1, (blue * scale) | 0)] += 1;
    const y = (0.2126 * red + 0.7152 * green + 0.0722 * blue) | 0;
    luma[Math.min(bins - 1, (y * scale) | 0)] += 1;
  }
  const normalize = (values: Float32Array) => {
    let peak = 0;
    for (const value of values) if (value > peak) peak = value;
    if (peak > 0) for (let i = 0; i < values.length; i += 1) values[i] /= peak;
  };
  normalize(r);
  normalize(g);
  normalize(b);
  normalize(luma);
  return {
    r,
    g,
    b,
    luma,
    clipped: { r: total ? cr / total : 0, g: total ? cg / total : 0, b: total ? cb / total : 0 },
  };
}

export type Waveform = { width: number; height: number; r: Float32Array; g: Float32Array; b: Float32Array };

/** Image columns on the horizontal axis, channel intensity on the vertical axis. */
export function waveform(frame: Rgba, width = 160, height = 90): Waveform {
  const r = new Float32Array(width * height);
  const g = new Float32Array(width * height);
  const b = new Float32Array(width * height);
  const channels = [[r, 0], [g, 1], [b, 2]] as const;
  for (let y = 0; y < frame.height; y += 1) {
    for (let x = 0; x < frame.width; x += 1) {
      const i = (y * frame.width + x) * 4;
      const from = Math.floor((x / frame.width) * width);
      const to = Math.max(from, Math.floor(((x + 1) / frame.width) * width) - 1);
      for (let column = from; column <= to && column < width; column += 1) {
        for (const [values, channel] of channels) {
          const row = Math.round((1 - frame.data[i + channel] / 255) * (height - 1));
          values[column * height + row] += 1;
        }
      }
    }
  }
  for (const values of [r, g, b]) {
    let peak = 0;
    for (const value of values) peak = Math.max(peak, value);
    if (peak > 0) for (let i = 0; i < values.length; i += 1) values[i] /= peak;
  }
  return { width, height, r, g, b };
}

export type Vectorscope = { size: number; grid: Float32Array };

/**
 * Vectorscope: chroma plane around the centre. Rec.601-style offset for familiarity:
 * pure red sits on the 0-degree (right) axis, cyan on 180.
 */
export function vectorscope(frame: Rgba, size = 128): Vectorscope {
  const grid = new Float32Array(size * size);
  let peak = 0;
  for (let i = 0; i < frame.data.length; i += 4) {
    const y = 0.299 * frame.data[i] + 0.587 * frame.data[i + 1] + 0.114 * frame.data[i + 2];
    const cb = 128 - 0.168736 * frame.data[i] - 0.331264 * frame.data[i + 1] + 0.5 * frame.data[i + 2];
    const cr = 128 + 0.5 * frame.data[i] - 0.418688 * frame.data[i + 1] - 0.081312 * frame.data[i + 2];
    const dx = Math.round(((cr - 128) / 128) * (size / 2 - 2));
    const dy = Math.round(((cb - 128) / 128) * (size / 2 - 2));
    const x = size / 2 + dx;
    const yPix = size / 2 + dy;
    if (x < 0 || yPix < 0 || x >= size || yPix >= size) continue;
    // scale the dot by luma like a real vectorscope trace
    const index = yPix * size + x;
    const value = Math.min(1, y / 255);
    grid[index] += value;
    if (grid[index] > peak) peak = grid[index];
  }
  if (peak > 0) for (let i = 0; i < grid.length; i += 1) grid[i] /= peak;
  return { size, grid };
}

export function drawScope(canvas: HTMLCanvasElement, paint: (ctx: CanvasRenderingContext2D, w: number, h: number) => void) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = Math.min(2, globalThis.devicePixelRatio || 1);
  const w = canvas.clientWidth || 160;
  const h = canvas.clientHeight || 90;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  paint(ctx, w, h);
}
