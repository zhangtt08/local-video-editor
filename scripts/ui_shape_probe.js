/*
 * 跨屏形状量具的探针：量「画出来的东西」，不量源码里写了什么。
 *
 * 这一档为什么存在（1.210 的 27px/25 行、1.211 的 68px/5 行都是它抓到的，而源码里的字数
 * 根本看不出来）：字号、圆角、被竖着切掉的文字、点不到的控件、同一格里叠了几行灰字——
 * 全是几何事实。返回纯数据，判定留在跑它的那一侧。
 *
 * 两条量具自己的教训也钉在这里：① 语法错必须由 `node --check` 在启动时炸出来，不能被
 * Runtime.evaluate 回空吞掉（1.205 那轮五屏全报「量不到」的根因）；② Set 不是 array-like，
 * 要 Array.from。
 */
function measureAgentCutUi() {
  var SMALL = 12.5; // 面板上任何一条可见的字都不许低于这一档
  var inClosedDetails = function (el) {
    var node = el.parentElement;
    while (node) {
      if (node.tagName === "DETAILS" && !node.open) return true;
      node = node.parentElement;
    }
    return false;
  };
  var visible = function (el) {
    var rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    var node = el;
    while (node && node.nodeType === 1) {
      var style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") return false;
      if (Number(style.opacity) === 0) return false;
      if (node.tagName === "DETAILS" && !node.open) return false;
      // 矩形不撒谎地报出「滚动线以外」的内容：它确实在 DOM 里有位置，但屏幕上看不见、
      // 摸不着，拿它判「点不到」是把量具的错觉记在产品账上（与「合上的 details 也有矩形」同一类）。
      if (node !== el && /auto|scroll|hidden|clip/.test(style.overflowY + " " + style.overflowX)) {
        var box = node.getBoundingClientRect();
        if (rect.bottom <= box.top + 2 || rect.top >= box.bottom - 2 ||
            rect.right <= box.left + 2 || rect.left >= box.right - 2) return false;
      }
      node = node.parentElement;
    }
    return inClosedDetails(el) ? false : true;
  };
  // 只有 overflow:hidden/clip 才算「切」；折叠线上方的可滚动容器里的字不是缺陷——
  // 所以要一路往上找，先碰到的若是滚动容器，这一条就不算被切。
  var clipper = function (el) {
    var node = el.parentElement;
    while (node && node !== document.body) {
      var style = getComputedStyle(node);
      var overflow = style.overflowX + " " + style.overflowY;
      if (/auto|scroll/.test(overflow)) return null;
      if (/hidden|clip/.test(overflow)) return node;
      node = node.parentElement;
    }
    return null;
  };
  var textOf = function (el) {
    var out = "";
    for (var i = 0; i < el.childNodes.length; i += 1) {
      var child = el.childNodes[i];
      if (child.nodeType === 3) out += child.nodeValue;
    }
    return out.replace(/\s+/g, " ").trim();
  };
  var fontSizes = [];
  var radii = {};
  var clipped = [];
  var stacks = [];
  var unreachable = [];
  var scrollAway = [];
  var scrimBehind = [];
  // 「+N」那一格：画不下的针必须有个名字。这里只收真正在屏上的那几枚牌子与它写的数目，
  // 门禁据此判「少画了却没人说」——静悄悄少画一枚针，与点不到的那枚一样是缺陷。
  var chips = [];
  // 有没有一层盖住整块视口的东西（帮助、导出确认那类遮罩）——只当事实报出来，
  // 不用它去裁剪量测：遮罩自己那一棵里的字同样要量。
  var scrim = null;
  var all = document.getElementsByTagName("*");
  var byTag = {};
  for (var index = 0; index < all.length; index += 1) {
    var el = all[index];
    if (!visible(el)) continue;
    byTag[el.tagName.toLowerCase()] = (byTag[el.tagName.toLowerCase()] || 0) + 1;
    if (String(el.className).indexOf("clip-keyframe-more") >= 0) {
      var chipBox = el.getBoundingClientRect();
      chips.push({
        text: textOf(el).slice(0, 8),
        box: [Math.round(chipBox.left), Math.round(chipBox.top), Math.round(chipBox.width), Math.round(chipBox.height)],
      });
    }
    var style = getComputedStyle(el);
    var radius = style.borderRadius;
    if (radius && radius !== "0px") {
      radius
        .split(",")
        .map(function (part) { return part.trim().split(" ")[0]; })
        .forEach(function (value) {
          if (/%/.test(value)) { radii["pct"] = (radii["pct"] || 0) + 1; return; }
          var px = Math.round(parseFloat(value) * 10) / 10;
          if (!isNaN(px)) radii[String(px)] = (radii[String(px)] || 0) + 1;
        });
    }
    var text = textOf(el);
    if (text) {
      var size = Math.round(parseFloat(style.fontSize) * 10) / 10;
      fontSizes.push({ size: size, text: text.slice(0, 48), tag: el.tagName.toLowerCase(), cls: String(el.className).slice(0, 40) });
      var lineHeight = parseFloat(style.lineHeight) || size * 1.2;
      var lines = Math.max(1, Math.round(el.getBoundingClientRect().height / lineHeight));
      if (size < SMALL && lines >= 2) {
        clipped.push({ why: "小字多行", size: size, lines: lines, text: text.slice(0, 48), cls: String(el.className).slice(0, 40) });
      }
      var holder = clipper(el);
      if (holder) {
        var inner = el.getBoundingClientRect();
        var box = holder.getBoundingClientRect();
        if (inner.bottom > box.bottom + 1.5 || inner.top < box.top - 1.5) {
          clipped.push({
            why: "被容器切掉", size: size, text: text.slice(0, 48),
            cls: String(el.className).slice(0, 40),
            box: [Math.round(el.getBoundingClientRect().top), Math.round(el.getBoundingClientRect().bottom)],
            clip_box: [Math.round(box.top), Math.round(box.bottom)],
            clip_by: holder.tagName.toLowerCase() + "." + String(holder.className || "").split(/\s+/)[0],
          });
        }
      }
    }
    var cls = " " + String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || "") + " ";
    if (/ hint/.test(cls)) {
      var parent = el.parentElement;
      var siblings = parent ? parent.querySelectorAll("[class*=hint]") : [];
      var shown = 0;
      for (var s = 0; s < siblings.length; s += 1) if (visible(siblings[s])) shown += 1;
      if (shown >= 2) {
        stacks.push({ cell: String((parent && parent.className) || "").slice(0, 40), lines: shown, text: text.slice(0, 40) });
      }
    }
    var tag = el.tagName.toLowerCase();
    var interactive = tag === "button" || tag === "input" || tag === "select" || tag === "textarea" ||
      /^a$/.test(tag) || /[role=(tab|button|checkbox|slider)]/.test(el.getAttribute("role") || "");
    if (interactive && !el.disabled && el.type !== "hidden" && el.getAttribute("aria-hidden") !== "true") {
      var rect = el.getBoundingClientRect();
      var cx = Math.round(rect.left + rect.width / 2);
      var cy = Math.round(rect.top + rect.height / 2);
      if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) {
        // 窄窗里那一排横向滚（1.197 定的答案）：能滚到就不算「点不到」，
        // 但要在名单里说一声，让人知道这一屏要靠滚动才摸得着它。
        var scroller = el.parentElement;
        var scrollable = false;
        while (scroller && scroller !== document.body) {
          var ss = getComputedStyle(scroller);
          if (/auto|scroll/.test(ss.overflowX + " " + ss.overflowY)) { scrollable = true; break; }
          scroller = scroller.parentElement;
        }
        if (!scrollable) {
          unreachable.push({ why: "在视口外也滚不到", tag: tag, text: (text || el.getAttribute("aria-label") || "").slice(0, 40) });
        } else {
          scrollAway.push((text || el.getAttribute("aria-label") || tag).slice(0, 24));
        }
        continue;
      }
      var hit = document.elementFromPoint(cx, cy);
      // 只有「命中的就是它自己或它的孩子」才算摸得到。命中它的**祖先**说明有一层
      // （常常是伪元素那张透明遮罩）盖在它上面——那一下点到的是遮罩，不是这个控件。
      if (hit && hit !== el && !el.contains(hit)) {
        var trail = [];
        var walk = el.parentElement;
        while (walk && walk !== document.body && trail.length < 5) {
          var name = String(walk.className || "").trim().split(/\s+/)[0] || walk.tagName.toLowerCase();
          trail.push(walk.tagName.toLowerCase() + (name ? "." + name : ""));
          walk = walk.parentElement;
        }
        var over = hit.getBoundingClientRect();
        // 前五项「挡住」的控件各带一份祖先链：哪一格没夹住自己的内容，看这一份就知道，
        // 不用再去猜。
        var chain = [];
        if (unreachable.length < 5) {
          var climb = el.parentElement;
          while (climb && climb !== document.body && chain.length < 8) {
            var cs = getComputedStyle(climb);
            var cb = climb.getBoundingClientRect();
            chain.push(
              (climb.tagName.toLowerCase() + "." + String(climb.className || "").split(/\s+/)[0]) +
              "[" + cs.overflowY + "/" + cs.position + "/" +
              Math.round(cb.left) + "," + Math.round(cb.top) + "," + Math.round(cb.right) + "," + Math.round(cb.bottom) + "]"
            );
            climb = climb.parentElement;
          }
        }
        // 挡住它的东西（或它的祖先）盖住整块视口，而控件不在那一棵里——这就是「在模态后面」，
        // 帮助那一层自己就是这样的：遮罩 + 一张浮在上头的面板，面板里的 li 也会先被命中。
        var owner = hit;
        var behindModal = false;
        while (owner && owner !== document.body) {
          var os = getComputedStyle(owner);
          if (os.position === "fixed" || os.position === "absolute") {
            var ob = owner.getBoundingClientRect();
            if (ob.width * ob.height >= innerWidth * innerHeight * 0.85) {
              behindModal = !owner.contains(el);
              if (!scrim && behindModal) {
                scrim = owner.tagName.toLowerCase() + "." + String(owner.className || "").split(/\s+/)[0];
              }
              break;
            }
          }
          owner = owner.parentElement;
        }
        if (behindModal) {
          // 不是缺陷，但要留名：哪天某一屏不该有模态却有了，这一行会说出来。
          scrimBehind.push((text || el.getAttribute("aria-label") || tag).slice(0, 24));
        } else unreachable.push({
          why: "被别的元素挡住", tag: tag, text: (text || el.getAttribute("aria-label") || "").slice(0, 40),
          over: hit.tagName.toLowerCase() + "." + String(hit.className || "").slice(0, 30),
          box: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)],
          over_box: [Math.round(over.left), Math.round(over.top), Math.round(over.width), Math.round(over.height)],
          trail: trail.join("<"),
          chain: chain,
        });
      }
    }
  }
  var minSize = null;
  for (var f = 0; f < fontSizes.length; f += 1) {
    if (minSize === null || fontSizes[f].size < minSize) minSize = fontSizes[f].size;
  }
  var smallest = fontSizes
    .filter(function (row) { return row.size === minSize; })
    .slice(0, 4)
    .map(function (row) { return row.size + "px " + row.text; });
  var sharp = Object.keys(radii).filter(function (key) {
    var px = Number(key);
    return key !== "pct" && px > 0 && px < 6;
  });
  var seen = {};
  var uniqueStacks = stacks.filter(function (row) {
    var id = row.cell + "|" + row.lines;
    if (seen[id]) return false;
    seen[id] = true;
    return true;
  });
  // 版面本身也要交回数字：两格叠在一起时，「点不到」的根因在布局，不在那一个控件。
  var LAYOUT = [".editor-main", ".panel", ".panel.right", ".timeline", ".tl-scroll", ".tl-inner",
    ".tl-lane", ".monitor-wrap", ".statusbar", ".titlebar", ".assets"];
  var boxes = {};
  for (var b = 0; b < LAYOUT.length; b += 1) {
    var found = document.querySelector(LAYOUT[b]);
    if (!found) continue;
    var box = found.getBoundingClientRect();
    boxes[LAYOUT[b]] = [Math.round(box.left), Math.round(box.top), Math.round(box.right), Math.round(box.bottom)];
  }
  return {
    href: location.href,
    scrim: scrim,
    behind_scrim_count: scrimBehind.length,
    layout_boxes: boxes,
    viewport: { width: innerWidth, height: innerHeight },
    nodes: all.length,
    painted_tags: byTag,
    text_nodes: fontSizes.length,
    min_font: minSize,
    smallest_sample: smallest,
    radius_steps: Object.keys(radii).sort(function (a, b) { return String(a).localeCompare(String(b), "en", { numeric: true }); }),
    sharp_corners: sharp,
    clipped: clipped.slice(0, 12),
    clipped_count: clipped.length,
    hint_stacks: uniqueStacks.slice(0, 12),
    hint_stack_count: uniqueStacks.length,
    unreachable: unreachable.slice(0, 12),
    unreachable_count: unreachable.length,
    scroll_away: scrollAway.slice(0, 10),
    scroll_away_count: scrollAway.length,
    chips: chips.slice(0, 8),
    chip_count: chips.length,
  };
}
