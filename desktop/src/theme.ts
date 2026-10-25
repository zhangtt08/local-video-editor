/**
 * 主题只有两档，写在 <html data-theme> 上，样式表的令牌按它切换。
 * 偏好不进工程状态：换一次主题不该涨一个 revision（与 1.93 的旋钮同一条口径）。
 */
export type Theme = "dark" | "light";

const KEY = "agentcut.theme";
const listeners = new Set<() => void>();

function read(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

let current: Theme = read();

export function applyTheme(theme: Theme): void {
  current = theme;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* 隐私模式写不进去，这一档也仍然生效到本次会话结束。 */
  }
  listeners.forEach((fn) => fn());
}

export function theme(): Theme {
  return current;
}

export function toggleTheme(): Theme {
  applyTheme(current === "dark" ? "light" : "dark");
  return current;
}

export function onThemeChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 启动时在渲染第一帧之前把主题贴上，免得先闪一帧深色。 */
export function bootTheme(): void {
  document.documentElement.dataset.theme = current;
}
