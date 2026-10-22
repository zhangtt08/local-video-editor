/*
 * 框点命中盒的量具（1.261 第 0 步：先量，再写手）。
 *
 * 这一份**只读画出来的东西**：那一条框点带占卡片哪几个像素、名字那一行占哪几格、
 * 左右 7px 的修剪边从哪开始、底下针道画出来的针在哪几格，然后把候选的命中盒按
 * 「以那一枚为中心、高 H 像素」临时画在导引层上（只加一个类，不接任何指针事件），
 * 对盒中心做一次 `elementsFromPoint`，看第一个摸到的是谁。
 *
 * 交回的全是数，判定不在这里做（那属于 tests/ui_shape_check.py 与 1.261 的门禁）。
 * 注入的导引层一定拆掉——留给下一腿一个脏页面，下一次红读到的就不是产品。
 */
function measureBoxkeyGeometry(heights) {
  const card = document.querySelector(".clip.selected");
  if (!card) return { present: false, reason: "没有选中的片段" };
  const band = card.querySelector(".clip-boxkeys");
  const keys = Array.from(card.querySelectorAll(".clip-boxkey"));
  if (!band || !keys.length) {
    return { present: false, reason: "那一条片段没有框点带", band: Boolean(band), keys: keys.length };
  }
  const cr = card.getBoundingClientRect();
  const px = (value) => Math.round(value * 100) / 100;
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      x: px(r.left - cr.left),
      y: px(r.top - cr.top),
      w: px(r.width),
      h: px(r.height),
      right: px(r.right - cr.left),
      bottom: px(r.bottom - cr.top),
      cx: px(r.left + r.width / 2 - cr.left),
      cy: px(r.top + r.height / 2 - cr.top),
    };
  };
  const nameOf = (el) => {
    if (!el) return null;
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean) : [];
    return el.tagName.toLowerCase() + (cls.length ? "." + cls.join(".") : "");
  };
  // 「不许盖住名字那一行」判的是**墨**，不是行盒：13px 的字在 18px 的行盒里本来就有上下留白，
  // 按行盒判会把一格根本不挡字的命中盒判成缺陷（1.228 那把尺学的同一课）。
  function ink(el) {
    if (!el) return null;
    const range = document.createRange();
    range.selectNodeContents(el);
    const r = range.getBoundingClientRect();
    if (!r.width && !r.height) return null;
    return {
      x: px(r.left - cr.left),
      y: px(r.top - cr.top),
      right: px(r.right - cr.left),
      bottom: px(r.bottom - cr.top),
      cx: px(r.left + r.width / 2 - cr.left),
      cy: px(r.top + r.height / 2 - cr.top),
    };
  }
  const top = card.querySelector(".clip-top");
  const label = card.querySelector(".clip-label");
  const duration = card.querySelector(".clip-dur");
  const needles = card.querySelector(".clip-needles");
  const handles = Array.from(card.querySelectorAll(".trim-handle")).map(box);
  const more = card.querySelector(".clip-keyframe-more");
  const cardBox = { w: px(cr.width), h: px(cr.height) };
  // 修剪边各占住卡片里哪一段横坐标：左边那一条的**内缘**、右边那一条的**内缘**。
  // （第一版写的是 max(right) 与 min(x)，把两条边的外缘当成了内缘——于是每一档都「越过修剪边」。）
  const lefts = handles.filter((h) => h.x < cr.width / 2);
  const rights = handles.filter((h) => h.x >= cr.width / 2);
  const edgeLeft = lefts.length ? Math.max(...lefts.map((h) => h.right)) : 0;
  const edgeRight = rights.length ? Math.min(...rights.map((h) => h.x)) : cardBox.w;
  const rects = {
    card: cardBox,
    band: box(band),
    keys: keys.map(box),
    clipTop: box(top),
    label: box(label),
    duration: box(duration),
    needles: box(needles),
    trimHandles: handles,
    moreChip: box(more),
    labelInk: ink(label),
    durationInk: ink(duration),
    topInk: ink(top),
    needlesPainted: Array.from(card.querySelectorAll(".clip-keyframe")).map(box),
  };
  const guides = [];
  const made = [];
  try {
    for (const height of heights) {
      keys.forEach((key, index) => {
        // 导引层按最终会用的那一手同样的摆法：以那一枚的中心为心，宽 11px（与针的菱形同档）。
        const kb = box(key);
        const top1 = px(kb.cy - height / 2);
        const guide = document.createElement("div");
        guide.className = "boxgeo-probe";
        guide.style.position = "absolute";
        guide.style.left = kb.cx + "px";
        guide.style.top = top1 + "px";
        guide.style.width = "11px";
        guide.style.height = height + "px";
        guide.style.marginLeft = "-5.5px";
        guide.style.pointerEvents = "auto";
        guide.style.zIndex = "6";
        card.appendChild(guide);
        made.push(guide);
        const gr = guide.getBoundingClientRect();
        const centre = { x: gr.left + gr.width / 2, y: gr.top + gr.height / 2 };
        const hit = document.elementsFromPoint(centre.x, centre.y) || [];
        const covers = (other) => Boolean(other)
          && other.cy >= top1 - 0.001 && other.cy <= top1 + height + 0.001
          && other.cx >= gr.left - cr.left && other.cx <= gr.right - cr.left;
        const overlaps = (other) => Boolean(other)
          && top1 < other.bottom - 0.001 && top1 + height > other.y + 0.001
          && (gr.left - cr.left) < other.right - 0.001 && (gr.right - cr.left) > other.x + 0.0001;
        guides.push({
          height,
          key: index,
          box: {
            x: px(gr.left - cr.left),
            y: top1,
            right: px(gr.right - cr.left),
            bottom: px(top1 + height),
          },
          crossesLeftEdge: px(gr.left - cr.left) < edgeLeft - 0.001,
          crossesRightEdge: px(gr.right - cr.left) > edgeRight + 0.001,
          coversLabelRow: covers(rects.clipTop),
          overlapsLabelInk: overlaps(rects.labelInk),
          overlapsDurationInk: overlaps(rects.durationInk),
          overlapsNeedleInk: (rects.needlesPainted || []).some(overlaps),
          overlapsMoreChip: overlaps(rects.moreChip),
          crossesTrimHandle: handles.some((h) => overlaps(h)),
          first: nameOf(hit[0]),
          firstIsGuide: hit[0] === guide,
          chain: hit.slice(0, 4).map(nameOf),
        });
      });
    }
  } finally {
    made.forEach((node) => node.remove());
  }
  // 产品那一头现在真的是一只手：把每一枚自己的盒子量一遍——中心点第一次摸到的是谁、
  // 它的盒子挡不挡名字的墨与画出来的针，以及修剪边那一列在盒子底下还摸不摸得到。
  const real = keys.map((el) => {
    const r = el.getBoundingClientRect();
    const centre = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    const hit = document.elementsFromPoint(centre.x, centre.y) || [];
    const rect = { x: px(r.left - cr.left), y: px(r.top - cr.top), right: px(r.right - cr.left), bottom: px(r.bottom - cr.top) };
    // 那一列还摸不摸得到，要在**它自己的那一格**上问：贴左端那一枚的中心是 x=8，而左边那条
    // 修剪边占 1..8——按中心往下打，问的是片段本体不是那一列。
    const columnX = rect.x < edgeLeft - 0.001 ? cr.left + edgeLeft - 2
      : rect.right > edgeRight + 0.001 ? cr.left + edgeRight + 2 : centre.x;
    const below = document.elementsFromPoint(columnX, r.bottom + 12) || [];
    const cross = (other) => Boolean(other)
      && rect.y < other.bottom - 0.001 && rect.bottom > other.y + 0.001
      && rect.x < other.right - 0.001 && rect.right > other.x + 0.001;
    return {
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role"),
      rect,
      pointerEvents: getComputedStyle(el).pointerEvents,
      zIndex: getComputedStyle(el).zIndex,
      first: nameOf(hit[0]),
      firstIsSelf: hit[0] === el,
      handleBelow: nameOf(below[0]),
      overlapsLabelInk: cross(rects.labelInk),
      overlapsDurationInk: cross(rects.durationInk),
      overlapsNeedleInk: (rects.needlesPainted || []).some(cross),
      crossesLeftEdge: rect.x < edgeLeft - 0.001,
      crossesRightEdge: rect.right > edgeRight + 0.001,
      width: px(r.width),
      height: px(r.height),
    };
  });

  return {
    present: true,
    edgeLeft,
    edgeRight,
    bandHeight: parseFloat(getComputedStyle(band).height) || null,
    bandTop: parseFloat(getComputedStyle(band).top) || null,
    bandPointerEvents: getComputedStyle(band).pointerEvents,
    keyPointerEvents: getComputedStyle(keys[0]).pointerEvents,
    keyTag: keys[0].tagName.toLowerCase(),
    domKeys: keys.length,
    bandLabel: band.getAttribute("aria-label") || "",
    rects,
    guides,
    real,
  };
}
