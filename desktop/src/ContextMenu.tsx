/** 1.278：时间线右键菜单——`keymap.ts` 里 `duplicate` 那条命令一直写着「片段右键菜单与工具条」，
 *  但右键菜单从来没长出来过：那条孪生说明是空的，键盘之外只剩工具条一条路。这一档把它补上，
 *  并且只补一个入口、不新造第二套规则：
 *
 *  - 每一项都调工具条 / 检查器已经在调的那个 store 函数，菜单自己不写命令、不算可用性；
 *  - 键位提示读 `keymap()` 与 `chordWords`——改键之后菜单上的字跟着变，不许另抄一份「Ctrl + B」；
 *  - 位置夹在视口里（右下角打开时翻到指针上方），焦点进得去、Escape 出得来，关掉后交回原来那一个元素；
 *  - 苹果那套的写法：抬起来的浮层、14px 圆角、模糊背板、36px 行高，不为它另开一档字号。
 *
 *  为什么用 portal：时间线的滚动容器与片段都有 `overflow`/`transform`，`position: fixed` 在里面会被
 *  裁掉（父级 transform 会新起一个包含块）。菜单挂到 `document.body` 上，夹的是真正的视口。
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./ui";

export type MenuEntry =
  | {
      kind: "item";
      label: string;
      icon?: string;
      hint?: string;
      title?: string;
      disabled?: boolean;
      danger?: boolean;
      run: () => void;
    }
  | { kind: "sep"; id: string };

export type MenuRequest = {
  at: { x: number; y: number };
  /** 一行标题：这一段 / 这一轨是谁。长了截断，不折行。 */
  title?: string;
  entries: MenuEntry[];
  /** 无障碍名：这一份菜单是「片段操作」还是「空白处操作」。 */
  label: string;
  /** 关掉时把焦点交回谁（右键按下的那个片段）。 */
  returnTo?: HTMLElement | null;
};

type Listener = (request: MenuRequest | null) => void;

let listener: Listener | null = null;

export function openContextMenu(request: MenuRequest) {
  listener?.(request);
}

export function closeContextMenu() {
  listener?.(null);
}

const EDGE_PIXELS = 8;

export function ContextMenuHost() {
  const [request, setRequest] = useState<MenuRequest | null>(null);
  useEffect(() => subscribe((next) => setRequest(next)), []);
  if (!request) return null;
  return <ContextMenu request={request} onClose={() => setRequest(null)} />;
}

function subscribe(fn: Listener): () => void {
  listener = fn;
  return () => {
    if (listener === fn) listener = null;
  };
}

function ContextMenu({ request, onClose }: { request: MenuRequest; onClose: () => void }) {
  const box = useRef<HTMLDivElement | null>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  // 位置要按**画出来以后**那个盒子算：先藏着量一次，再摆出来。右边放不下就往左收，
  // 下边放不下就翻到指针上方——两轴都夹在视口里，菜单不会有一半在窗口外。
  // 量的是 offsetWidth/offsetHeight（布局尺寸），不是 getBoundingClientRect：开门动画此刻正停在
  // `scale(.98)`，矩形比真盒子小 2%——右下的那一格会因此把菜单推出视口 7px（真窗口量到过）。
  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    const width = node.offsetWidth;
    const height = node.offsetHeight;
    const left = Math.max(EDGE_PIXELS, Math.min(request.at.x, window.innerWidth - width - EDGE_PIXELS));
    const below = request.at.y + height + EDGE_PIXELS <= window.innerHeight;
    const top = below ? request.at.y : Math.max(EDGE_PIXELS, request.at.y - height);
    setPlace({ left, top });
  }, [request]);

  useEffect(() => {
    opener.current = request.returnTo ?? (document.activeElement as HTMLElement | null);
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) onClose();
    };
    const drag = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) onClose();
    };
    const resign = () => onClose();
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("contextmenu", drag, true);
    window.addEventListener("resize", resign);
    window.addEventListener("blur", resign);
    const wheel = (event: WheelEvent) => {
      if (!box.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("wheel", wheel, { passive: true, capture: true });
    return () => {
      document.removeEventListener("pointerdown", away, true);
      document.removeEventListener("contextmenu", drag, true);
      window.removeEventListener("resize", resign);
      window.removeEventListener("blur", resign);
      document.removeEventListener("wheel", wheel, true);
      const back = opener.current;
      if (back && back.isConnected) back.focus({ preventScroll: true });
    };
  }, [request, onClose]);

  // 焦点要等位置量完、盒子真的 visible 之后再给：藏着的按钮 `.focus()` 是空转，
  // 而右键本来就把焦点留在了那个片段上（`role="button"`），不搬的话键盘根本进不来。
  useEffect(() => {
    if (place) focusStep(box.current, 0);
  }, [place]);

  const choose = (entry: Extract<MenuEntry, { kind: "item" }>) => {
    if (entry.disabled) return;
    onClose();
    entry.run();
  };

  return createPortal(
    <div
      ref={box}
      className="ctx-menu"
      role="menu"
      aria-label={request.label}
      data-ctx-menu="1"
      style={{ left: place?.left ?? request.at.x, top: place?.top ?? request.at.y, visibility: place ? "visible" : "hidden" }}
      onKeyDown={(event) => {
        // 菜单开着的时候，全局快捷键一个字都不许接：在这一层就把事件收下（Escape 由这里关）。
        event.stopPropagation();
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
          return;
        }
        if (event.key === "Tab") {
          event.preventDefault();
          onClose();
          return;
        }
        const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
        if (step) {
          event.preventDefault();
          focusStep(box.current, step);
          return;
        }
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          focusStep(box.current, event.key === "Home" ? -Infinity : Infinity);
        }
      }}
      onContextMenu={(event) => event.preventDefault()}
    >
      {request.title ? <div className="ctx-title" title={request.title}>{request.title}</div> : null}
      {request.entries.map((entry, index) =>
        entry.kind === "sep" ? (
          <div key={entry.id} className="ctx-sep" role="separator" />
        ) : (
          <button
            key={`${entry.label}-${index}`}
            type="button"
            role="menuitem"
            className={`ctx-item${entry.danger ? " danger" : ""}`}
            disabled={entry.disabled}
            title={entry.title}
            onClick={() => choose(entry)}
          >
            <span className="ctx-icon" aria-hidden="true">{entry.icon ? <Icon name={entry.icon} size={14} /> : null}</span>
            <span className="ctx-label">{entry.label}</span>
            {entry.hint ? <span className="ctx-chord mono">{entry.hint}</span> : null}
          </button>
        ),
      )}
    </div>,
    document.body,
  );
}

/** 方向键只在能按的那几项之间走；到头就停在那一头（菜单不循环，与系统菜单一致）。 */
function focusStep(root: HTMLElement | null, step: number) {
  const items = Array.from(root?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not([disabled])') ?? []);
  if (!items.length) return;
  const at = items.indexOf(document.activeElement as HTMLButtonElement);
  if (step === -Infinity) return items[0].focus();
  if (step === Infinity) return items[items.length - 1].focus();
  if (at < 0) return items[0].focus();
  const next = Math.min(items.length - 1, Math.max(0, at + step));
  items[next].focus();
}
