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
        // 判「在不在屏幕上」要看**中心点**，不能看矩形：滚动线以下的那一枚，矩形还有一半在框里，
        // `elementFromPoint(中心)` 却摸到隔壁那一条toolbar——1.220 展开检查器那九段时，
        // 「整片对齐 -14 LUFS」这颗按钮就被这样记成了「点不到」，而它只是需要往下滚一段。
        var cx = rect.left + rect.width / 2;
        var cy = rect.top + rect.height / 2;
        if (cy <= box.top + 2 || cy >= box.bottom - 2 || cx <= box.left + 2 || cx >= box.right - 2) return false;
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
  // 一块字真正画得出来的矩形：从 Range 报的那一块起，把自己与祖先里每一处会裁剪的框
  // （overflow hidden/clip/auto/scroll）逐层取交。折叠线以外的文本、被省略号截掉的尾巴，
  // 都在这一步消失——它们在 DOM 里排着，在屏幕上读不到。
  var clipInk = function (el, rect) {
    var out = {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom};
    var node = el;
    while (node && node !== document.body) {
      var style = getComputedStyle(node);
      var overflow = style.overflowX + " " + style.overflowY;
      if (/hidden|clip|auto|scroll/.test(overflow)) {
        var box = node.getBoundingClientRect();
        out.left = Math.max(out.left, box.left);
        out.top = Math.max(out.top, box.top);
        out.right = Math.min(out.right, box.right);
        out.bottom = Math.min(out.bottom, box.bottom);
      }
      node = node.parentElement;
    }
    return out;
  };
  // 只比**同一层**里的两块字。弹层起来之后底下那一整片是故意不让读的（那一类由
  // `遮罩后` 那个数说一声），拿它来判「字压字」是把弹层的账记在底下那层上。
  // 这里不能用命中测试：被压住的那一块，命中点本来就不是它——那样判据会
  // 把自己要看的东西全部滤掉（试过一次，76 条一起消失）。
  // 「层」认的是那一个盖住 ≥85% 视口的 fixed/absolute 容器：两边各找一个，
  // 只有同一个（或两边都没有）才放在一起比。
  var layerOf = function (node) {
    var walk = node;
    while (walk && walk !== document.body) {
      var ws = getComputedStyle(walk);
      if (ws.position === "fixed" || ws.position === "absolute") {
        var wb = walk.getBoundingClientRect();
        if (wb.width * wb.height >= innerWidth * innerHeight * 0.85) return walk;
      }
      walk = walk.parentElement;
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
  // 「字压字」那一判的原料：每一块**自己写着字**的节点与它的矩形。
  var textRects = [];
  var radii = {};
  var clipped = [];
  var stacks = [];
  var unreachable = [];
  var scrollAway = [];
  var scrimBehind = [];
  // 「+N」那一格：画不下的针必须有个名字。这里只收真正在屏上的那几枚牌子与它写的数目，
  // 门禁据此判「少画了却没人说」——静悄悄少画一枚针，与点不到的那枚一样是缺陷。
  var chips = [];
  // 画面里那一层（字幕 / 标题）画的是**用户自己的内容**：字号按帧高的百分比来，
  // 应用不该替用户决定它多大。这一层不参与「字号地板 / 不许叠行」那两判，但单独计数，
  // 让读表的人看得见「量具看见了，并且故意没判」。
  var frameText = 0;
  // 下拉里那一行被切：`<select>` 不会自己报「被切」（它的 overflow 算出来是 visible），
  // 1.220 就是靠眼睛看发布包才发现「Rec.709（电视与浏览器…」被竖切在括号前。
  // 这一档把这件事变成量得出来的：按选中的那一行实际要多宽、那一格有多少宽。
  var truncatedSelects = [];
  var measureCanvas = null;
  function textWidth(el, value) {
    if (!measureCanvas) measureCanvas = document.createElement("canvas");
    var ctx = measureCanvas.getContext("2d");
    var font = getComputedStyle(el).font;
    ctx.font = font || "13px sans-serif";
    return ctx.measureText(value).width;
  }
  // 有没有一层盖住整块视口的东西（帮助、导出确认那类遮罩）——只当事实报出来，
  // 不用它去裁剪量测：遮罩自己那一棵里的字同样要量。
  var scrim = null;
  var all = document.getElementsByTagName("*");
  var byTag = {};
  for (var index = 0; index < all.length; index += 1) {
    var el = all[index];
    if (!visible(el)) continue;
    byTag[el.tagName.toLowerCase()] = (byTag[el.tagName.toLowerCase()] || 0) + 1;
    if (el.tagName.toLowerCase() === "select") {
      var chosen = el.options ? el.options[el.selectedIndex] : null;
      var words = chosen ? String(chosen.textContent || "").trim() : "";
      // 24 px 是那一格右边箭头与内边距要占的：只比文字宽度会低估，量出来「放得下」而画出来切。
      var needs = words ? Math.round(textWidth(el, words)) + 24 : 0;
      if (needs && needs > el.clientWidth) {
        truncatedSelects.push({
          label: el.getAttribute("aria-label") || el.name || "",
          text: words.slice(0, 40),
          needs_px: needs,
          box_px: el.clientWidth,
          has_title: Boolean(el.title),
        });
      }
    }
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
    // 画面里那一层（`.caption-layer`）是用户自己的内容：字号与换行由用户定的百分比来，
    // 应用的字号地板管不着它——拿地板去判它，等于应用替用户决定标题多大。
    var inFrame = typeof el.closest === "function" && el.closest(".caption-layer") !== null;
    if (inFrame) frameText += 1;
    if (text && !inFrame) {
      var size = Math.round(parseFloat(style.fontSize) * 10) / 10;
      fontSizes.push({ size: size, text: text.slice(0, 48), tag: el.tagName.toLowerCase(), cls: String(el.className).slice(0, 40) });
      if (textRects.length < 600) {
        // 量的是**墨**，不是盒子：`.clip-label` 那一颗的框是整条片段宽（左对齐 + 省略号），
        // 拿它的矩形去判「字压字」，右边那颗 `未导入` 牌子永远算撞——那是容器的账，
        // 不是读不到的账。所以按直接文本节点各取一份 Range 矩形，再并起来。
        var ink = null;
        for (var ci = 0; ci < el.childNodes.length; ci += 1) {
          var cn = el.childNodes[ci];
          if (cn.nodeType !== 3 || !String(cn.nodeValue || "").trim()) continue;
          var cr = document.createRange();
          cr.selectNodeContents(cn);
          var cb = cr.getBoundingClientRect();
          if (!cb.width && !cb.height) continue;
          if (!ink) {
            ink = {left: cb.left, top: cb.top, right: cb.right, bottom: cb.bottom};
          } else {
            ink.left = Math.min(ink.left, cb.left);
            ink.top = Math.min(ink.top, cb.top);
            ink.right = Math.max(ink.right, cb.right);
            ink.bottom = Math.max(ink.bottom, cb.bottom);
          }
        }
        if (ink) {
          // Range 报的是**排出来的**文本，不是**看得见的**那一段：被省略号截断的那一句，
          // 它的矩形照样伸到整句话的宽度（1.228 第一版就这么把 `第一行标题…` 与右边那颗
          // `4.00s` 判成一对了，而屏幕上它们隔着 5px 的空隙）。所以先按自己的裁剪链
          // 把墨裁到真正画得出来的那一块，裁空了就是没画。
          ink = clipInk(el, ink);
          if (ink && ink.right - ink.left > 0 && ink.bottom - ink.top > 0) textRects.push({el: el, r: ink, layer: layerOf(el),
            text: text.slice(0, 26), cls: String(el.className).slice(0, 30)});
        }
      }
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
    // 「圆润化 / 苹果化」的一条硬判据：控件不许交给操作系统代画。
    // 原生 color 色块与 file 框的 appearance 不是 none，画出来就是系统那套白框方块——
    // 配色、圆角、尺寸全脱离设计刻度，深色界面里唯一还在用浅色控件画的那一格。
    // 只量**看得见**的：藏起来的 file 框（点按钮才开选择器）是正确答案，不算违规。
    var nativeType = tag === "input" ? String(el.getAttribute("type") || "") : "";
    if ((nativeType === "color" || nativeType === "file") && style.appearance !== "none") {
      clipped.push({
        why: "操作系统代画的控件", type: nativeType, appearance: style.appearance || "auto",
        text: String(el.getAttribute("aria-label") || el.id || nativeType).slice(0, 40),
        cls: String(el.className).slice(0, 40),
      });
    }
    // 这一行原来写的是 /[role=(tab|button|checkbox|slider)]/：方括号在正则里是**字符集**，
    // 不是选择器——任何 role 里含 r/o/e/… 的都算命中，于是画面层里那一行说明
    // （role="group"，且整条画面链是 pointer-events:none）被当成「一个点不到的控件」。
    // 尺要量的是「该点到的点不到」，所以这里只认可操作的角色。
    var actionable = /^(tab|button|checkbox|radio|slider|switch|combobox|listbox|option|menuitem|textbox|spinbutton|link)$/.test(el.getAttribute("role") || "");
    var interactive = tag === "button" || tag === "input" || tag === "select" || tag === "textarea" ||
      /^a$/.test(tag) || actionable;
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
        // 命中它的**祖先滚动容器**，而它的矩形确实出了那一格的可视边：这一格被滚到边缘
        // 以下，中心点落在了横向滚动条那一条上。滚一滚就摸得着——与上面「视口外但能滚到」
        // 同一条答案（1.197 定的），所以记进名单说一声，不算点不到。
        // 判据收得很紧：命中的必须是它自己的祖先、那一层真的能滚、矩形确实出边。
        // 1.224 那一类「遮罩盖住按钮」命中的是**兄弟**遮罩，进不了这一支，照样算红。
        if (hit.contains(el)) {
          var hs = getComputedStyle(hit);
          var hb = hit.getBoundingClientRect();
          // 比的是**可视框**（去掉滚动条那一条），不是边框盒：落在自己滚动条上的控件
          // 滚一滚就摸得着，和「被兄弟遮罩盖住」不是一件事。
          var cb = {
            left: hb.left + hit.clientLeft,
            top: hb.top + hit.clientTop,
            right: hb.left + hit.clientLeft + hit.clientWidth,
            bottom: hb.top + hit.clientTop + hit.clientHeight,
          };
          if (/auto|scroll/.test(hs.overflowX + " " + hs.overflowY) &&
              (rect.bottom > cb.bottom + 1 || rect.top < cb.top - 1 ||
               rect.right > cb.right + 1 || rect.left < cb.left - 1)) {
            scrollAway.push((text || el.getAttribute("aria-label") || tag).slice(0, 24));
            continue;
          }
        }
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
  // 「字压字」：两块各自写着字、彼此不包含、矩形横竖都叠进去 ≥3px。
  // 1.227 那张文字层截图就是这么看出来的：转场那块牌子（z-index 6、不透明底）压在
  // 右边那一格的片段名与时长的牌子上，`图板` 只剩 `板` 看得见——几何上「两块都在屏上」，
  // 读起来却少一个字。两块都不透明的字叠在一起，总有一块是读不到的，所以这一判不许例外。
  // 数的是**全部**对：判据是「一处都不许有」，把总数截在 6 就等于给第 7 处发了免罪符。
  // 明细只留前 6 条（读的人只需要知道压的是谁），总数照实交。
  var overlaps = [];
  var overlapCount = 0;
  for (var oa = 0; oa < textRects.length; oa += 1) {
    var ra = textRects[oa].r;
    var ea = textRects[oa].el;
    for (var ob = oa + 1; ob < textRects.length; ob += 1) {
      var rb = textRects[ob].r;
      var eb = textRects[ob].el;
      if (textRects[oa].layer !== textRects[ob].layer) continue;
      if (ea === eb || ea.contains(eb) || eb.contains(ea)) continue;
      var ow = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      var oh = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (ow < 3 || oh < 3) continue;
      overlapCount += 1;
      if (overlaps.length >= 6) continue;
      overlaps.push({
        a: textRects[oa].text, a_cls: textRects[oa].cls,
        b: textRects[ob].text, b_cls: textRects[ob].cls,
        over: [Math.round(ow * 10) / 10, Math.round(oh * 10) / 10],
        boxes: [Math.round(ra.left), Math.round(ra.top), Math.round(ra.right), Math.round(ra.bottom),
          Math.round(rb.left), Math.round(rb.top), Math.round(rb.right), Math.round(rb.bottom)],
      });
    }
  }
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
    // 画面里那一层数到的字节点：不参与判断，但必须看得见它被跳过了。
    frame_text_nodes: frameText,
    text_overlaps: overlaps,
    text_overlap_count: overlapCount,
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
    truncated_selects: truncatedSelects.slice(0, 8),
    truncated_select_count: truncatedSelects.length,
  };
}
