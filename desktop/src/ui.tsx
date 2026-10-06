import { useEffect, useRef, type ReactNode } from "react";

/** 图标全部内联：不引第三方图标字体，窗口里不会出现缺字方框。 */
const PATHS: Record<string, ReactNode> = {
  lock: <><rect x="3" y="7" width="10" height="7" rx="1" /><path d="M5 7V4a3 3 0 0 1 6 0v3" /></>,
  unlock: <><rect x="3" y="7" width="10" height="7" rx="1" /><path d="M5 7V4a3 3 0 0 1 6 0" /></>,
  play: <path d="M4.5 3v10l8.5-5-8.5-5z" fill="currentColor" stroke="none" />,
  pause: <path d="M4.6 3h2.2v10H4.6zM9.4 3h2.2v10H9.4z" fill="currentColor" stroke="none" />,
  prev: <path d="M4 3h1.6v10H4zM12.5 3.2v9.6L6.6 8z" fill="currentColor" stroke="none" />,
  next: <path d="M10.4 3H12v10h-1.6zM3.5 3.2v9.6L9.4 8z" fill="currentColor" stroke="none" />,
  start: <path d="M3 3h1.5v10H3zM13 3 6.6 8 13 13z" fill="currentColor" stroke="none" />,
  end: <path d="M11.5 3H13v10h-1.5zM3 3l6.4 5L3 13z" fill="currentColor" stroke="none" />,
  cursor: <path d="M4 2l8 6.5-3.6.6 2 4-1.7.8-2-4L4 12.4z" fill="currentColor" stroke="none" />,
  razor: (
    <g>
      <circle cx="4" cy="4.2" r="1.8" />
      <circle cx="4" cy="11.8" r="1.8" />
      <path d="M5.6 5.4 13 13M5.6 10.6 13 3.5" />
    </g>
  ),
  magnet: <path d="M3 2.5v6a5 5 0 0 0 10 0v-6M3 2.5h3.4M12.6 2.5H9.2M8 9v4.5" />,
  undo: (
    <g>
      <path d="M6.5 3 3 6.5 6.5 10" />
      <path d="M3 6.5h6.8a3.2 3.2 0 0 1 0 6.4H7" />
    </g>
  ),
  redo: (
    <g>
      <path d="M9.5 3 13 6.5 9.5 10" />
      <path d="M13 6.5H6.2a3.2 3.2 0 0 0 0 6.4H9" />
    </g>
  ),
  plus: <path d="M8 3.2v9.6M3.2 8h9.6" />,
  trash: <path d="M2.5 4h11M6.5 4V2.8h3V4M4 4l.7 9.2h6.6L12 4M6.7 6.8v4M9.3 6.8v4" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  minimize: <path d="M3.5 8h9" />,
  maximize: <rect x="3.5" y="3.5" width="9" height="9" rx="1.2" />,
  restore: (
    <g>
      <rect x="5.2" y="3.2" width="7.6" height="7.6" rx="1.2" />
      <path d="M3.2 5.2v6.1a.9.9 0 0 0 .9.9h6.1" />
    </g>
  ),
  fullscreen: <path d="M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3" />,
  history: (
    <g>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 4.6V8l2.3 1.6" />
    </g>
  ),
  robot: (
    <g>
      <rect x="2.6" y="5" width="10.8" height="8" rx="2" />
      <path d="M8 2.4V5M5.6 8.4h.01M10.4 8.4h.01M6 11h4" />
    </g>
  ),
  export: <path d="M8 11V2.6M4.6 6 8 2.6 11.4 6M2.8 13h10.4" />,
  film: (
    <g>
      <rect x="1.8" y="3.5" width="9" height="9" rx="1.5" />
      <path d="M10.8 7l3.4-2v6l-3.4-2" />
    </g>
  ),
  music: (
    <g>
      <path d="M6 11.5V3.6l6-1.4v8" />
      <circle cx="4.4" cy="11.5" r="1.7" />
      <circle cx="10.4" cy="10.2" r="1.7" />
    </g>
  ),
  image: (
    <g>
      <rect x="2.2" y="2.8" width="11.6" height="10.4" rx="1.5" />
      <circle cx="6" cy="6.4" r="1.1" />
      <path d="M2.8 11.6 6.4 8.4l2.4 2 2.6-2.4 1.8 1.8" />
    </g>
  ),
  folder: <path d="M2.4 4.4h4l1.2 1.6h6v7.6H2.4z" />,
  refresh: (
    <g>
      <path d="M13 8a5 5 0 1 1-1.6-3.7" />
      <path d="M13 2.8V5.4h-2.6" />
    </g>
  ),
  copy: (
    <g>
      <rect x="5.4" y="5.4" width="8" height="8" rx="1.4" />
      <path d="M10.8 3.4a1.4 1.4 0 0 0-1.4-1.4H4a1.4 1.4 0 0 0-1.4 1.4v5.4a1.4 1.4 0 0 0 1.4 1.4" />
    </g>
  ),
  check: <path d="M3.4 8.4 6.4 11.6 12.6 4.8" />,
  warning: (
    <g>
      <path d="M8 2.4 14 12.6H2z" />
      <path d="M8 6.4v3M8 11h.01" />
    </g>
  ),
  info: (
    <g>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7.2v3.6M8 4.9h.01" />
    </g>
  ),
  gear: (
    <g>
      <circle cx="8" cy="8" r="2.4" />
      <path d="M8 1.6v1.8M8 12.6v1.8M14.4 8h-1.8M3.4 8H1.6M12.5 3.5l-1.3 1.3M4.8 11.2l-1.3 1.3M12.5 12.5l-1.3-1.3M4.8 4.8 3.5 3.5" />
    </g>
  ),
  keyboard: (
    <g>
      <rect x="1.4" y="4.2" width="13.2" height="7.6" rx="1.6" />
      <path d="M4 6.6h.01M6.4 6.6h.01M8.8 6.6h.01M11.2 6.6h.01M4.6 9.4h6.8" />
    </g>
  ),
  zoomIn: (
    <g>
      <circle cx="7.2" cy="7.2" r="4.4" />
      <path d="M10.6 10.6 13.6 13.6M5.4 7.2h3.6M7.2 5.4v3.6" />
    </g>
  ),
  zoomOut: (
    <g>
      <circle cx="7.2" cy="7.2" r="4.4" />
      <path d="M10.6 10.6 13.6 13.6M5.4 7.2h3.6" />
    </g>
  ),
  split: (
    <g>
      <path d="M8 1.6v12.8" strokeDasharray="2.4 2" />
      <path d="M2.4 5.2h3.2v5.6H2.4zM10.4 5.2h3.2v5.6h-3.2z" />
    </g>
  ),
  eye: (
    <g>
      <path d="M1.4 8S3.6 4 8 4s6.6 4 6.6 4-2.2 4-6.6 4S1.4 8 1.4 8z" />
      <circle cx="8" cy="8" r="1.9" />
    </g>
  ),
  eyeOff: (
    <g>
      <path d="M2.4 2.4 13.6 13.6" />
      <path d="M5.6 4.8A7.7 7.7 0 0 1 8 4c4.4 0 6.6 4 6.6 4a11 11 0 0 1-2.3 2.8M4.2 6.2 1.4 8s2.2 4 6.6 4a7.4 7.4 0 0 0 2.3-.4" />
    </g>
  ),
  volume: (
    <g>
      <path d="M3 6.2h2.2L8.4 3.6v8.8L5.2 9.8H3z" />
      <path d="M11 6.2a2.6 2.6 0 0 1 0 3.6M12.8 4.4a5 5 0 0 1 0 7.2" />
    </g>
  ),
  mute: (
    <g>
      <path d="M3 6.2h2.2L8.4 3.6v8.8L5.2 9.8H3z" />
      <path d="M11 6.4l3 3.2M14 6.4l-3 3.2" />
    </g>
  ),
  chevron: <path d="M6 4l4 4-4 4" />,
  spark: <path d="M8 2l1.6 4.4L14 8l-4.4 1.6L8 14l-1.6-4.4L2 8l4.4-1.6z" />,
  flag: <path d="M4.2 2.2v10.4M4.2 2.6h7.4l-1.7 2.5 1.7 2.5H4.2z" />,
  link: (
    <g>
      <path d="M7 9.6 5.4 11.2a2.8 2.8 0 0 1-4-4L4.6 4.6M9 6.4l1.6-1.6a2.8 2.8 0 0 1 4 4L11.4 10.4" />
      <path d="M6.2 9.8 9.8 6.2" />
    </g>
  ),
};

export function Icon({ name, size = 14 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name] ?? PATHS.info}
    </svg>
  );
}

/** 应用标识：与安装包图标同源（深色方块 + 白色播放三角 + 蓝色播放头）。 */
export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect width="20" height="20" rx="5" fill="#1c1c21" />
      <path d="M7.2 6.2v7.6l6-3.8-6-3.8z" fill="#fff" />
      <line x1="13.8" y1="4.2" x2="13.8" y2="15.8" stroke="#2b59d8" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export function Btn({
  children,
  onClick,
  variant = "default",
  disabled,
  title,
  active,
  full,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "subtle" | "danger-text" | "danger";
  disabled?: boolean;
  title?: string;
  active?: boolean;
  full?: boolean;
  type?: "button" | "submit";
}) {
  const cls = ["btn", variant !== "default" ? variant : "", active ? "active" : "", full ? "full" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button type={type} className={cls} onClick={onClick} disabled={disabled} title={title}>
      {children}
    </button>
  );
}

export function IconBtn({
  icon,
  label,
  onClick,
  disabled,
  active,
  danger,
}: {
  icon: string;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  active?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      className={`icon-btn${active ? " active" : ""}${danger ? " danger" : ""}`}
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      aria-pressed={active}
    >
      <Icon name={icon} />
    </button>
  );
}

export function Tag({ children, tone = "", mono }: { children: ReactNode; tone?: string; mono?: boolean }) {
  return <span className={`tag ${tone}${mono ? " mono" : ""}`}>{children}</span>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="field">
      <label title={hint}>{label}</label>
      {children}
    </div>
  );
}

export function Modal({
  title,
  sub,
  children,
  footer,
  onClose,
  width = 460,
}: {
  title: string;
  sub?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    const controls = () => Array.from(element?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]') ?? []);
    controls().find((node) => node.hasAttribute('autofocus'))?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close.current(); }
      if (event.key === 'Tab') { const nodes = controls(); const index = nodes.indexOf(document.activeElement as HTMLElement);
        if (event.shiftKey && index <= 0 || !event.shiftKey && index === nodes.length - 1) { event.preventDefault(); nodes[event.shiftKey ? nodes.length - 1 : 0]?.focus(); }
      }
    };
    element?.addEventListener('keydown', key);
    return () => { element?.removeEventListener('keydown', key); previous?.focus(); };
  }, []);
  return (
    <div className="dialog-backdrop open" onClick={onClose} role="presentation">
      <div
        ref={dialog}
        className="dialog"
        style={{ width }}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="dialog-head">{title}</div>
        {sub ? <div className="dialog-sub">{sub}</div> : null}
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Seg({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="seg" role="tablist">
      {options.map((item) => (
        <button
          key={item.value}
          type="button"
          className={item.value === value ? "active" : ""}
          onClick={() => onChange(item.value)}
          role="tab"
          aria-selected={item.value === value}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon, lines }: { icon: string; lines: ReactNode }) {
  return (
    <div className="empty-note">
      <div className="empty-icon">
        <Icon name={icon} size={22} />
      </div>
      {lines}
    </div>
  );
}

export function JsonView({ value, collapse = 6 }: { value: unknown; collapse?: number }) {
  const text = JSON.stringify(value, null, 2);
  const lines = text.split("\n");
  const clipped = lines.length > collapse ? lines.slice(0, collapse).join("\n") + "\n  …" : text;
  return <pre className="json-box mono">{highlight(clipped)}</pre>;
}

/** 极简 JSON 高亮：逐段切成 React 节点，不使用 innerHTML。 */
export function highlight(text: string) {
  const pattern = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?)/g;
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const [full, , colon, num] = match;
    if (num !== undefined) nodes.push(<span key={key++} className="n">{full}</span>);
    else if (colon) nodes.push(<span key={key++} className="k">{full}</span>);
    else nodes.push(<span key={key++} className="s">{full}</span>);
    last = match.index + full.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}
