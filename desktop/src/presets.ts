export type Preset = {
  id: string;
  label: string;
  width: number;
  height: number;
  fps: [number, number];
  sample: number;
};

/** 起手预设：只列能被整数 tick 精确表示的帧率，避免建完工程才发现对不齐。 */
export const PROJECT_PRESETS: Preset[] = [
  { id: "1080p30", label: "1080p 30fps", width: 1920, height: 1080, fps: [30, 1], sample: 48000 },
  { id: "1080p25", label: "1080p 25fps（PAL）", width: 1920, height: 1080, fps: [25, 1], sample: 48000 },
  { id: "1080p24", label: "1080p 24fps（电影感）", width: 1920, height: 1080, fps: [24, 1], sample: 48000 },
  { id: "720p30", label: "720p 30fps（轻量）", width: 1280, height: 720, fps: [30, 1], sample: 48000 },
  { id: "vertical", label: "竖屏 1080×1920 30fps", width: 1080, height: 1920, fps: [30, 1], sample: 48000 },
  { id: "4k30", label: "4K 30fps", width: 3840, height: 2160, fps: [30, 1], sample: 48000 },
];
