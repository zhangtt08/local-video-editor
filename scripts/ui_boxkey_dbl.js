/*
 * 1.262 第 0 步（只量，不判）：条上那一排框点的**空隙**里，一次双击到底落在谁身上。
 *
 * 为什么要先量：想把「在播放头那一格打一枚框点」放到条上（与检查器那三颗同一个写入口），
 * 就得让那一排接双击；而 1.242 故意让它 `pointer-events: none`，理由是「接了指针就等于在片段顶上
 * 挖一块拖不动的死区」。同时片段本体自己已经绑了 `onDoubleClick`（Timeline.tsx:1299，进了嵌套合成）。
 * 两只手共用同一片像素就是两个主人——先把命中次序与会不会抢拖动量出来，再决定放不放、放哪。
 *
 * 交回的全是数：每一处候选点的 `elementsFromPoint` 前四层、带子与卡片自己的 pointer-events、
 * 画出来几枚、以及这一条是不是嵌套合成（那句 onDoubleClick 只对它有副作用）。
 */
function measureBoxkeyDblclick() {
  const card = document.querySelector(".clip.selected");
  if (!card) return { present: false, reason: "没有选中的片段" };
  const band = card.querySelector(".clip-boxkeys");
  if (!band) return { present: false, reason: "这一条没有框点带" };
  const cr = card.getBoundingClientRect();
  const br = band.getBoundingClientRect();
  const label = (el) => {
    const cls = typeof el.className === "string" && el.className.trim()
      ? "." + el.className.trim().split(/\\s+/).join(".") : "";
    return el.tagName.toLowerCase() + cls;
  };
  const keys = Array.from(card.querySelectorAll(".clip-boxkey")).map((el) => el.getBoundingClientRect());
  const stackAt = (x, y) => document.elementsFromPoint(x, y).slice(0, 4).map(label);
  const centres = keys.map((r) => Math.round(r.left + r.width / 2 - cr.left)).sort((a, b) => a - b);
  const xs = [];
  for (let i = 0; i + 1 < centres.length; i += 1) xs.push(Math.round((centres[i] + centres[i + 1]) / 2));
  xs.unshift(centres.length ? Math.max(2, centres[0] - 24) : 2);
  xs.push(centres.length ? Math.min(Math.round(cr.width) - 2, centres[centres.length - 1] + 24) : Math.round(cr.width) - 2);
  const cy = Math.round(br.top + br.height / 2);
  const spots = xs.map((dx) => ({ dx, stack: stackAt(cr.left + dx, cy) }));
  // 拖动是从卡片本体起手的：这一处问「带子接了指针之后，卡片还收不收得到按下」。
  const bandHit = spots.length ? spots[0].stack[0] : null;
  return {
    present: true,
    cardClass: label(card),
    bandPointerEvents: getComputedStyle(band).pointerEvents,
    cardPointerEvents: getComputedStyle(card).pointerEvents,
    bandHeight: Math.round(br.height),
    bandTop: Math.round(br.top - cr.top),
    dots: keys.length,
    centres,
    cyFromCardTop: cy - Math.round(cr.top),
    nestedSequence: /合成/.test(card.getAttribute("title") || ""),
    bandHitFirst: bandHit,
    spots,
  };
}
