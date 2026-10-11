/** 1.134：命令键位只剩一张表，而且它能改。
 *
 * 以前 `App.tsx` 里是一条 if 链，每个组合键的字面量写在那儿，`Help.tsx` 的快捷键页又把同样的
 * 「Ctrl+B」抄了一遍给人看——两处会有一天说出不同的键，而人没有地方改（剪映、达芬奇、AE 都能改键，
 * 这三家的默认表还互相不一样，替用户猜一套不合理）。这里把「哪个组合键做哪件事」收成一处：
 *
 *  - `COMMANDS` 是能改的那些**命令**，每条都有 id、中文名字，以及界面上已经存在的那个孪生按钮
 *    （`twin`）——键盘从来不是唯一的路，改键也不会把那条路改掉；
 *  - `DEFAULT_MAP` 就是 1.134 之前 `App.tsx` 实际在按的那套键；
 *  - `matchCommand` 是唯一的解析处：先按精确的 Shift 状态配，再接受标了 `shift: "any"` 的那条,
 *    所以 Ctrl+Z 与 Ctrl+Shift+Z 能分到两件事，而 Ctrl+Shift+A 仍然就是全选；
 *  - `rebind` 只回答「这个键现在归谁」，冲突要说清楚抢的是哪条命令，不许悄悄把另一条挤掉。
 *
 * 方向键微调、I/O/K/J/L、空格、Esc、F1/F9/F10 这些**不在**这里：它们是跟着焦点与上下文走的手感，
 * 不是命令，把它们也做成可配置只会让那张表看起来谁都能改、其实改了也没用。
 */

export type Chord = {
  /** `event.key` 的小写形式；功能键保持 `f1`…`f12`，空格是 ` `。 */
  key: string;
  ctrl?: boolean;
  alt?: boolean;
  /** true / false 是「必须按成这样」；"any" 是「Shift 不参与这条命令的判断」。 */
  shift?: boolean | "any";
};

export type CommandId =
  | "undo"
  | "redo"
  | "duplicate"
  | "select-all"
  | "copy"
  | "paste"
  | "split"
  | "export-panel"
  | "marker"
  | "group"
  | "ungroup"
  | "link"
  | "unlink";

export type Command = { id: CommandId; label: string; twin: string };

/** 每条命令在界面上的孪生：改键不许让这件事变成「只有键盘能做」。 */
export const COMMANDS: readonly Command[] = [
  { id: "undo", label: "撤销", twin: "标题栏的「撤销」" },
  { id: "redo", label: "重做", twin: "标题栏的「重做」" },
  { id: "duplicate", label: "追加整组副本", twin: "片段右键菜单与工具条的「复制」" },
  { id: "select-all", label: "选中全部片段", twin: "时间线空白处框选" },
  { id: "copy", label: "复制选中的片段组", twin: "工具条的「复制」" },
  { id: "paste", label: "粘贴到播放头", twin: "工具条的「粘贴」" },
  { id: "split", label: "在播放头处剪开", twin: "工具条那颗「剪开」" },
  { id: "export-panel", label: "打开导出面板", twin: "底部工作台的「导出」" },
  { id: "marker", label: "在播放头记一个标记", twin: "标尺上「记标记」" },
  { id: "group", label: "组合", twin: "工具条的「组合」" },
  { id: "ungroup", label: "取消组合", twin: "工具条的「取消组合」" },
  { id: "link", label: "音画链接", twin: "工具条的「链接」" },
  { id: "unlink", label: "解除音画链接", twin: "工具条的「取消链接」" },
];

/** 1.134 之前 `App.tsx` 那条 if 链按的就是这套。 */
export const DEFAULT_MAP: Readonly<Record<CommandId, Chord>> = {
  undo: { key: "z", ctrl: true, shift: false },
  redo: { key: "z", ctrl: true, shift: true },
  duplicate: { key: "d", ctrl: true, shift: "any" },
  "select-all": { key: "a", ctrl: true, shift: "any" },
  copy: { key: "c", ctrl: true, shift: "any" },
  paste: { key: "v", ctrl: true, shift: "any" },
  split: { key: "b", ctrl: true, shift: "any" },
  "export-panel": { key: "m", ctrl: true, shift: "any" },
  marker: { key: "m", shift: "any" },
  group: { key: "g", ctrl: true, shift: false },
  ungroup: { key: "g", ctrl: true, shift: true },
  link: { key: "l", ctrl: true, shift: false },
  unlink: { key: "l", ctrl: true, shift: true },
};

export type KeyEvent = {
  key: string;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  metaKey: boolean;
};

/** 改键时从一次真实按下里读出组合键。只按下了修饰键还没有键，就交回 null 让界面继续等。 */
export function chordFromEvent(event: KeyEvent): Chord | null {
  const key = event.key.toLowerCase();
  if (!key || key === "shift" || key === "control" || key === "alt" || key === "meta" || key === "capslock") return null;
  const chord: Chord = { key, shift: event.shiftKey };
  if (event.ctrlKey || event.metaKey) chord.ctrl = true;
  if (event.altKey) chord.alt = true;
  return chord;
}

export function holdsModifier(chord: Chord, event: KeyEvent): boolean {
  // Windows 上 Ctrl 与 Win 各来一次是两件事：Mac 的 ⌘ 走 metaKey，Windows/Linux 走 ctrlKey，
  // 界面那句话写「Ctrl / ⌘」，这里也只认这两个之一。
  const wantCtrl = chord.ctrl ?? false;
  const wantAlt = chord.alt ?? false;
  if (wantCtrl && !(event.ctrlKey || event.metaKey)) return false;
  if (!wantCtrl && (event.ctrlKey || event.metaKey)) return false;
  if (wantAlt !== event.altKey) return false;
  return true;
}

/** 唯一的解析处：精确 Shift 的那条赢，其次才是标了 "any" 的那条。 */
export function matchCommand(map: Record<CommandId, Chord>, event: KeyEvent): CommandId | null {
  const key = event.key.toLowerCase();
  if (!key || key === "shift" || key === "control" || key === "alt" || key === "meta") return null;
  let loose: CommandId | null = null;
  for (const item of COMMANDS) {
    const chord = map[item.id];
    if (!chord || chord.key.toLowerCase() !== key || !holdsModifier(chord, event)) continue;
    if (chord.shift === "any" || chord.shift === undefined) {
      if (!loose) loose = item.id;
    } else if (chord.shift === event.shiftKey) {
      return item.id;
    }
  }
  return loose;
}

/** 这个名字给冲突的那句话用；界面不许自己拼第二份。 */
export function commandLabel(id: CommandId): string {
  const found = COMMANDS.find((item) => item.id === id);
  return found ? found.label : id;
}

export function chordWords(chord: Chord): string {
  const parts: string[] = [];
  if (chord.ctrl) parts.push("Ctrl / ⌘");
  if (chord.alt) parts.push("Alt");
  if (chord.shift === true) parts.push("Shift");
  const key = chord.key;
  const named: Record<string, string> = { " ": "空格", arrowleft: "←", arrowright: "→", home: "Home", end: "End" };
  parts.push(named[key] ?? (key.length === 1 ? key.toUpperCase() : key.replace(/^f/, "F")));
  return parts.join(" + ");
}

/** 一个能用的组合键：有 key，且带 Ctrl/⌘ 或 Alt。裸键留给正在打字的人。 */
export function chordUsable(chord: Chord): string | null {
  if (!chord || typeof chord.key !== "string" || chord.key.length === 0) return "这条组合键没有键。";
  if (!chord.ctrl && !chord.alt) return "至少要带 Ctrl / ⌘ 或 Alt：没有修饰键的单键会给正在打字的人抢掉。";
  return null;
}

export function rebind(
  map: Record<CommandId, Chord>,
  id: CommandId,
  chord: Chord,
): { ok: true; map: Record<CommandId, Chord> } | { ok: false; why: string; takes: CommandId | null } {
  const unusable = chordUsable(chord);
  if (unusable) return { ok: false, why: unusable, takes: null };
  for (const item of COMMANDS) {
    if (item.id === id) continue;
    const other = map[item.id];
    if (!other || other.key.toLowerCase() !== chord.key.toLowerCase()) continue;
    if ((other.ctrl ?? false) !== (chord.ctrl ?? false) || (other.alt ?? false) !== (chord.alt ?? false)) continue;
    // 一个占着 Shift 两种状态的位置（`undo` 用 false、`redo` 用 true），另一条标 "any" 的键会整个盖住它们。
    const clashes =
      chord.shift === "any" ||
      chord.shift === undefined ||
      other.shift === "any" ||
      other.shift === undefined ||
      other.shift === chord.shift;
    if (clashes) return { ok: false, why: `这个键已经是「${commandLabel(item.id)}」的了。`, takes: item.id };
  }
  return { ok: true, map: { ...map, [id]: chord } };
}

/** 从 localStorage 读回来那一份：只认认识 id 与形状对的键，其余丢掉而不是让界面崩。 */
export function mergeMap(raw: unknown): Record<CommandId, Chord> {
  const out: Record<CommandId, Chord> = { ...DEFAULT_MAP };
  if (!raw || typeof raw !== "object") return out;
  for (const item of COMMANDS) {
    const value = (raw as Record<string, unknown>)[item.id];
    if (!value || typeof value !== "object") continue;
    const given = value as Record<string, unknown>;
    const key = typeof given.key === "string" ? given.key.toLowerCase() : "";
    if (!key) continue;
    const shift = given.shift === "any" ? "any" : typeof given.shift === "boolean" ? given.shift : ("any" as const);
    const chord: Chord = { key, shift };
    if (given.ctrl === true) chord.ctrl = true;
    if (given.alt === true) chord.alt = true;
    if (chordUsable(chord)) continue;
    out[item.id] = chord;
  }
  return out;
}

/** 存的时候只写与人改过的那几条，默认表不占 localStorage。 */
export function changedFromDefault(map: Record<CommandId, Chord>): Partial<Record<CommandId, Chord>> {
  const out: Partial<Record<CommandId, Chord>> = {};
  for (const item of COMMANDS) {
    const chord = map[item.id];
    const base = DEFAULT_MAP[item.id];
    if (chord.key !== base.key || (chord.ctrl ?? false) !== (base.ctrl ?? false) || (chord.alt ?? false) !== (base.alt ?? false) || chord.shift !== base.shift) {
      out[item.id] = chord;
    }
  }
  return out;
}
