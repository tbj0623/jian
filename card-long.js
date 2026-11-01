/** 笺 · 长图之三：单品 / 搭配 / 摘录（1080×1920）
 *
 *  从 card.js 里分出来的，理由同 card-year.js 的文件头：载荷门（MAX_FILE_KB = 64）。
 *  这一段是三段里最大的一份（约 40KB），单独成文件之后 card.js 回到 17KB，
 *  以后往这里加新长图也不会再顶到那道线。
 *
 *  它依赖 card.js 的 CARD / roundRectPath / drawSpaced / drawVertical / loadImg，
 *  以及 card-year.js 的 CARD_LIGHT_FALLBACK / tokenLight——全部是运行期调用，
 *  三个文件在 index.html 里按 card.js → card-year.js → card-long.js 的顺序加载。
 *
 *  硬约束（三条，改之前先读）：
 *  1. **永远是白天的纸。** 取色只走 tokenLight()，绝不走 token()
 *  2. **版式是纸上的版式。** 宋体标题、字距、细线分栏、竖排、印章红只做一次强调
 *  3. **算不出来就不摆。** 没有价格就不印单次成本，没有购入日就不印「买了多久」；
 *     挡住时按下去必须**开口**（aria-disabled 的钮按得下去，说不出理由就等于回到静默）
 *
 *  2026-10 分家时**一个字节没改**：下面这一整段就是原来 card.js 里从
 *  「三张新长图」那条分界线开始到文件末尾的全部内容。
 */

/* ==================== 三张新长图（v0.6.0 · 长图 lane 追加） ====================
 *
 *  单品档案 / 搭配详情 / 摘录本是这一版新增的三屏，它们各自都要能被**发出去**：
 *  一件衣服的档案像一张吊牌的背面，一套搭配像一页随身穿搭手册，一句摘录像一张书签。
 *
 *  和 drawYearCard 同一族，三条硬约束逐条列在这里（三张图各自会被不同的人改，所以写一遍就够）：
 *
 *  1. **永远是白天的纸。** 取色只走 tokenLight()，绝不走 token()——token() 读的是
 *     documentElement 上的计算值，`:root[data-theme="dark"]` 会把它换成夜纸色（#1b1917）。
 *     长图是发给别人看的：黑底图贴进群里，看起来像另一个 App。这是产品立场，不是 bug。
 *  2. **版式是纸上的版式。** 宋体标题、字距、细线分栏、竖排、印章红只做一次强调、
 *     留白克制——手法全部沿用 drawYearCard 那一版（它是这三张的样板）。
 *  3. **算不出来就不摆。** 没有价格就不印单次成本，没有购入日就不印「买了多久」，
 *     摘录本空着就挡住那枚按钮并说清为什么；挡住时按下去必须**开口**（aria-disabled
 *     的钮按得下去，说不出理由就等于回到静默）。
 *
 *  为什么都追加在这个文件、而不是各屏各写一份：纸、报头、页脚、折行、印章都是同几件东西，
 *  分散到 wardrobe.js / remind.js 里就会漂成三种纸。这里是**只追加**——上面那 9 处测试
 *  盯着的函数一个字没动。
 */

/** 三张新长图共用的一套「白天的纸」。与 yearPalette() 同源（都走 tokenLight），
 *  多取两枚：搭配的「这套的账」要第二枚朱（--seal-2），落款章要纸白（cream）。
 *  兜底值直接用 CARD_LIGHT_FALLBACK 那一份——色值只有 styles.css 一处定义，
 *  这里连兜底都不另抄。 */
function longPaper() {
  const F = CARD_LIGHT_FALLBACK;
  return {
    paper: tokenLight("--paper", F["--paper"]),
    paper2: tokenLight("--paper-2", F["--paper-2"]),
    cream: tokenLight("--cream", F["--cream"]),
    ink: tokenLight("--ink", F["--ink"]),
    soft: tokenLight("--ink-soft", F["--ink-soft"]),
    line: tokenLight("--line", F["--line"]),
    seal: tokenLight("--seal", F["--seal"]),
    seal2: tokenLight("--seal-2", F["--seal-2"]),
    ok: tokenLight("--ok", F["--ok"]),
  };
}

/** 起一张纸：1080×1920 + 纸底 + 竖纹 + 报头 + 一道横线。
 *  三张新图都从它开始——「纸长什么样」只有这一处说法，改纸纹不必改三遍。
 *  尺寸写死在这里，测试与「存图」都按这个数验收。 */
function longSheet(masthead) {
  const P = longPaper();
  const W = 1080, H = 1920, PAD = 88;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  if (!ctx) return { cv, ctx: null, P, W, H, PAD };

  ctx.fillStyle = P.paper;
  ctx.fillRect(0, 0, W, H);
  // 纸纹与 drawYearCard 同一手法：1px 竖线 / 7px，用 paper2 + 半透明。
  // 不用 rgba：长图会被压进微信再转发，半透明细纹在压缩里会糊成一片脏灰。
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = P.paper2;
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 7) {
    ctx.beginPath(); ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, H); ctx.stroke();
  }
  ctx.restore();

  ctx.fillStyle = P.soft;
  ctx.font = `500 26px ${CARD.SANS}`;
  drawSpaced(ctx, masthead, PAD, 116, 8);
  ctx.textAlign = "right";
  ctx.fillText(dayStr(Date.now()), W - PAD, 116);
  ctx.textAlign = "left";
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, 156); ctx.lineTo(W - PAD, 156); ctx.stroke();
  return { cv, ctx, P, W, H, PAD };
}

/** 一块「照片或主色」。有照片就是 cover 裁进去，没有就是那块色——
 *  两种情况下版面占同一个位置，不会一半有框、一半塌掉。
 *  颜色缺省时退回 paper2（纸的第二种说法），不另造一个灰。 */
async function longFillBox(ctx, imgSrc, color, x, y, w, h, r, P) {
  const im = await loadImg(imgSrc);
  ctx.save();
  roundRectPath(ctx, x, y, w, h, r);
  ctx.clip();
  if (im && im.width && im.height) {
    const sc = Math.max(w / im.width, h / im.height);
    const dw = im.width * sc, dh = im.height * sc;
    ctx.drawImage(im, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  } else {
    ctx.fillStyle = color || P.paper2;
    ctx.fillRect(x, y, w, h);
  }
  ctx.restore();
  return im;
}

/** 按真实像素折行。wrapZh 是按字数折的（写到第 18 个字就断），中文里混进
 *  「¥1,150」「3 天前」这种半角串时两头都对不齐；长图上的名字与一句话值得按宽度排。 */
function longWrap(ctx, text, maxW, maxLines) {
  const chars = [...String(text == null ? "" : text)];
  const lines = [];
  let buf = "";
  for (const ch of chars) {
    if (ch === "\n") { lines.push(buf); buf = ""; continue; }
    if (buf && ctx.measureText(buf + ch).width > maxW) { lines.push(buf); buf = ch; }
    else buf += ch;
  }
  if (buf) lines.push(buf);
  if (!lines.length) lines.push("");
  if (maxLines && lines.length > maxLines) {
    const cut = lines.slice(0, maxLines);
    cut[maxLines - 1] = cut[maxLines - 1].replace(/…$/, "") + "…";
    return cut;
  }
  return lines;
}

/** 「¥1,150」：长图上的钱要有千分位，不然四位数读起来要数一遍。 */
function longMoney(n) {
  const s = String(Math.round(Number(n) || 0));
  return "¥" + s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 一列竖排在纸上有多高（像素）。和 drawVertical 用同一套单元（Engine.vClusters），
 *  所以「预算够不够」与「画出来多高」是同一个数——两处各算一遍的话，
 *  短句居中会偏、长句会掉出框。 */
function longColHeight(str, step) {
  let adv = 0;
  if (typeof Engine !== "undefined" && Engine.vClusters) {
    for (const c of Engine.vClusters(str)) adv += c.adv;
  } else {
    adv = [...String(str || "")].length;
  }
  return Math.max(0, adv * step);
}

/* ------------------------------------------------------------ 竖排的预算
 *
 *  这一组三个函数只做一件事：**先把「这一块地方能放几个字」算清楚，再决定字号和列数**。
 *  以前三张图各写各的：摘录按字数分三档定字号、搭配/年度把 vTop 写死再算 vPerCol，
 *  每一处都把「可用高」和「字号」当成两个互不相干的前提。于是同一句话在
 *  1006px 里排成 12+5 两列（右列顶到底线、左列只到一半），读的人以为句子被截了；
 *  60 个字的时候 Engine.verticalCols 按格子数截断，尾字悄悄消失、连个省略号都没有。
 *
 *  这里的规矩只有一条：**整句放得下才算排完**。放不下就缩字号，缩到下限还放不下，
 *  就截断——但截断的地方一定画一个看得见的省略号。
 */

/** 一列竖排占多少「格」（整字 1 格，句读 0.6 格）。与 drawVertical 共用同一套单元。 */
function longColCells(str) {
  return longColHeight(str, 1);
}

/**
 * 把一句竖排装进 cellsMax 格 × colsMax 列。返回 { cols, cut }。
 *
 * 分列规则仍然只走 Engine.verticalCols（避头尾那一张表在那里，不能抄第二份），
 * 但它「装不下就静默截尾」——所以每一次分列都拿画出来的字和原文对一遍：
 * 对不上就是被截了，再二分找最长的、带上省略号还能整段放下的前缀。
 * 短句分完列之后还会重新匀一次（12+5 → 9+8）：一列到底、另一列只有半截的梳子形，
 * 是这一版最刺眼的毛病。
 */
function longVerticalFit(text, cellsMax, colsMax) {
  const src = String(text == null ? "" : text);
  const all = [...src];
  const per = Math.max(0, cellsMax - 1);
  const pack = (t) => {
    if (typeof Engine !== "undefined" && Engine.verticalCols) return Engine.verticalCols(t, Math.max(0, per), colsMax);
    const cells = all.slice(0, Math.max(1, cellsMax));
    return [t.length ? cells.join("").slice(0, t.length) : ""];
  };
  const whole = all.join("");
  const first = pack(whole);
  if (first.join("") === whole && first.length <= colsMax) {
    // 匀列：找到「还能整段放下、且列数不变」的最小每列格数
    if (first.length > 1) {
      for (let p = 0; p < per; p++) {
        const c = (typeof Engine !== "undefined" && Engine.verticalCols)
          ? Engine.verticalCols(whole, p, first.length)
          : first;
        if (c.join("") === whole && c.length <= first.length && c.length === first.length) {
          return { cols: c, cut: false };
        }
      }
    }
    return { cols: first, cut: false };
  }
  // 装不下：二分最长的前缀，让它带上省略号之后仍然整段放得下
  const ok = (n) => {
    const t = all.slice(0, n).join("") + "…";
    const c = pack(t);
    return c.join("") === t && c.length <= colsMax;
  };
  let lo = 1, hi = Math.max(0, all.length - 1), best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ok(mid)) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  if (best < 1) {
    const c = pack("…");
    return { cols: c.join("") === "…" ? c : ["…"], cut: true };
  }
  return { cols: pack(all.slice(0, best).join("") + "…"), cut: true };
}

/**
 * 一句话在一个框里怎么排：字号、步距、每列几格、几列、整块多高多宽、从哪一行开始。
 *
 * o = { top, bottom, fontMax, fontMin, colsMax, track, gap, minCells, align }
 *   track    步距 / 字号（默认 1.22；宋体竖排的呼吸感就靠它）
 *   gap      列距 / 字号（默认 1.34；列距与字号成比例，字号一变列距自己跟上）
 *   minCells 少于这么多格就宁可不摆（返回 null）——一句落款挤成三列两个字，
 *            比不摆更难看，也更像 bug
 *   align    "center" 在框里垂直居中 / "bottom" 从框底往上挂
 *
 * 字号是从 fontMax 往下试的：第一个「整句放得下」的字号就是它，所以短句不会被
 * 无谓地缩小，长句也不会为了撑满而溢出。
 */
function longVerticalPlan(text, o) {
  const src = String(text == null ? "" : text).trim();
  if (!src) return null;
  const top = o.top, bottom = o.bottom;
  const avail = bottom - top;
  const colsMax = Math.max(1, o.colsMax || 4);
  const fontMax = Math.max(12, o.fontMax || 64);
  const fontMin = Math.max(12, Math.min(o.fontMin || 40, fontMax));
  const track = o.track || 1.22;
  const gapK = o.gap || 1.34;
  const minCells = Math.max(1, o.minCells || 1);
  let plan = null;
  for (let fp = fontMax; fp >= fontMin; fp -= 2) {
    const step = Math.max(12, Math.round(fp * track));
    const cellsMax = Math.floor((avail - fp) / step) + 1;
    if (cellsMax < minCells) continue;
    const fit = longVerticalFit(src, cellsMax, colsMax);
    const colH = (c) => Math.max(fp, (longColCells(c) - 1) * step + fp);
    const tallest = Math.max(fp, ...fit.cols.map(colH));
    plan = { fp, step, cellsMax, cols: fit.cols, cut: fit.cut, tallest };
    if (!fit.cut && tallest <= avail + 0.5) break;      // 整句放得下，就用这个字号
  }
  if (!plan) return null;

  /* 字距的硬钳位。Engine.verticalCols 数的是「单元」（句读算 0.6 格），
   * 而 longColCells 数的是真实步距——一句话里句读多的时候两者差得出几十像素，
   * 上面那一轮「放得下」就会是乐观的。所以最后再拿**真实高度**验一次：
   * 超了就不缩字号（40px 是能看清的下限），只把字距压紧到刚好装得下。
   * 60 字那一版就是靠这一步从 1424.6 收回 1420 以内的。 */
  const cellsTall = Math.max(1, ...plan.cols.map((c) => longColCells(c)));
  if (plan.tallest > avail + 0.5 && cellsTall > 1) {
    plan.step = Math.max(12, Math.floor((avail - plan.fp) / (cellsTall - 1)));
    plan.tallest = Math.max(plan.fp, (cellsTall - 1) * plan.step + plan.fp);
  }
  plan.pitch = Math.max(plan.fp + 6, Math.round(plan.fp * gapK));
  plan.heights = plan.cols.map((c) => Math.max(plan.fp, (longColCells(c) - 1) * plan.step + plan.fp));
  plan.height = Math.max(plan.fp, ...plan.heights);
  plan.width = (plan.cols.length - 1) * plan.pitch + plan.fp;
  plan.top = top;
  plan.bottom = bottom;
  plan.startY = o.align === "bottom"
    ? Math.round(bottom - plan.height)
    : Math.round(top + Math.max(0, (avail - plan.height) / 2));
  return plan;
}

/** 把排好的竖排画出来：**以第一列的右边界为准向内排**。
 *  rightEdge 是第一列字格的右边线，第二列往左退一个列距；
 *  从前写的是「列的中线 = W − PAD − 字号/2」，右边界正好压在 PAD 那条线上，
 *  字再宽一点就出界——这里改成给右边界也就等于给了一条不会越过的线。 */
function paintVerticalPlan(ctx, plan, rightEdge) {
  const prevAL = ctx.textAlign, prevBL = ctx.textBaseline;
  plan.cols.forEach((col, i) => {
    drawVertical(ctx, col, rightEdge - plan.fp / 2 - i * plan.pitch, plan.startY, plan.step);
  });
  ctx.textAlign = prevAL; ctx.textBaseline = prevBL;
}

/** 实心圆章（落款用）。和 drawYearCard 末尾那枚同一个做法：实心印章红 + 纸白一个字，
 *  微微倾斜——它是「盖上去的」，不是「画的图标」。 */
function longRoundStamp(ctx, P, cx, cy, r, ch) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-10 * Math.PI / 180);
  ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fillStyle = P.seal; ctx.fill();
  ctx.fillStyle = P.cream;
  ctx.font = `500 ${Math.round(r * 0.84)}px ${CARD.SERIF}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(ch, 0, 2);
  ctx.restore();
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
}

/** 方印（藏书印 / 押印）。真实的印章多是方的，圆的那枚在这套纸上专门留给「落款」；
 *  两种形状各自有各自的意思，不混用。 */
function longSquareSeal(ctx, P, cx, cy, size, ch) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-6 * Math.PI / 180);
  const h = size / 2;
  roundRectPath(ctx, -h, -h, size, size, size * 0.14);
  ctx.fillStyle = P.paper; ctx.fill();
  ctx.strokeStyle = P.seal;
  ctx.lineWidth = Math.max(4, Math.round(size * 0.055));
  ctx.stroke();
  ctx.fillStyle = P.seal;
  ctx.font = `500 ${Math.round(size * 0.54)}px ${CARD.SERIF}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(ch, 0, size * 0.02);
  ctx.restore();
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
}

/* ---------------------------------------------------------------- 单品长图 */

/** 档案里的三格数字：穿过 / 买了 / 上次穿。
 *  「买了多久」的说法归 wardrobe.js 的 boughtLine（屏幕上那句就是它）——
 *  这里只把「买了」两个字挪到标签上，不拿年月日重算一遍（两份算法迟早差一天）。 */
function longItemFacts(w) {
  const worn = Number(w && w.worn) || 0;
  const bought = (w && w.boughtAt && typeof boughtLine === "function")
    ? String(boughtLine(w)).replace(/^买了\s*/, "").replace(/。$/, "")
    : "";
  const last = (w && w.lastWorn && typeof relativeDays === "function") ? relativeDays(w.lastWorn) : "";
  return [
    { k: "穿过", v: worn ? `${worn} 次` : "还没穿过" },
    { k: "买了", v: bought || "没记购入日" },
    { k: "上次穿", v: last || "没记" },
  ];
}

/** 单品长图（1080×1920）：一件衣服的档案，像一张吊牌的背面。
 *  从上到下：一根绳穿过吊牌孔 → 大图 / 主色 → 名字 → 品牌尺码品类 →
 *  单次成本那句人话 → 三格数字 → 落款。**不写盘、不改 state**，纯画。 */
async function drawItemCard(w) {
  const { cv, ctx, P, W, H, PAD } = longSheet("JIAN · 衣笺 · 单品");
  if (!ctx) return cv;
  const SERIF = CARD.SERIF, SANS = CARD.SANS;

  if (!w) {
    ctx.fillStyle = P.soft; ctx.font = `400 44px ${SERIF}`;
    ctx.textAlign = "center";
    ctx.fillText("这一件已经不在柜里了。", W / 2, 940);
    ctx.textAlign = "left";
    return cv;
  }

  /* ---- 吊牌孔：一根细绳从报头那道线穿下来 ---- */
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(W / 2, 156); ctx.lineTo(W / 2, 204); ctx.stroke();
  ctx.beginPath(); ctx.arc(W / 2, 236, 30, 0, Math.PI * 2);
  ctx.fillStyle = P.paper2; ctx.fill();
  ctx.strokeStyle = P.line; ctx.lineWidth = 2; ctx.stroke();

  /* ---- 大图 / 主色 ---- */
  const HX = PAD, HY = 302, HW = W - PAD * 2, HH = 520;
  await longFillBox(ctx, w.img, w.color, HX, HY, HW, HH, 14, P);
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  roundRectPath(ctx, HX, HY, HW, HH, 14); ctx.stroke();

  /* ---- 压在图角上的那枚吊牌签：品类 · 尺码 ---- */
  const tagText = [w.cat, w.size].filter(Boolean).join(" · ") || "衣";
  ctx.font = `400 26px ${SANS}`;
  const tw = ctx.measureText(tagText).width + 44;
  ctx.fillStyle = P.cream;
  roundRectPath(ctx, HX + 26, HY + HH - 84, tw, 58, 10); ctx.fill();
  ctx.fillStyle = P.ink;
  ctx.fillText(tagText, HX + 26 + 22, HY + HH - 84 + 38);

  /* ---- 名字：这一页的主角。太长就缩字号，不折行（吊牌上的名字不折） ---- */
  let namePx = 86;
  ctx.font = `500 ${namePx}px ${SERIF}`;
  const name = String(w.name || "未命名");
  while (namePx > 46 && ctx.measureText(name).width > W - PAD * 2) {
    namePx -= 4;
    ctx.font = `500 ${namePx}px ${SERIF}`;
  }
  ctx.fillStyle = P.ink;
  ctx.fillText(name, PAD, 976);

  /* ---- 品牌 / 品类 / 季节 / 场合：有哪样说哪样，不印占位符 ---- */
  const seen = (typeof Engine !== "undefined" && Engine.seasonOf) ? Engine.seasonOf(w) : "";
  const meta = [w.brand, w.cat, seen, (w.occasions || []).slice(0, 2).join("、")]
    .filter(Boolean).join(" · ");
  ctx.fillStyle = P.soft;
  ctx.font = `400 28px ${SANS}`;
  if (meta) drawSpaced(ctx, meta, PAD, 1032, 2);

  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, 1086); ctx.lineTo(W - PAD, 1086); ctx.stroke();

  /* ---- 单次成本：这一张图最想说的一句话 ---- */
  const cost = typeof cpw === "function" ? cpw(w) : null;
  const finite = Number.isFinite(cost);
  ctx.fillStyle = P.soft;
  ctx.font = `500 24px ${SANS}`;
  drawSpaced(ctx, "单次穿着成本", PAD, 1152, 6);

  ctx.textAlign = "left";
  if (finite) {
    // 印章红**只点这一处数字**（加上右下那枚章），别的话一律墨色
    ctx.fillStyle = P.seal;
    ctx.font = `500 116px ${SERIF}`;
    const num = `¥${cost.toFixed(1)}`;
    ctx.fillText(num, PAD, 1284);
    const nw = ctx.measureText(num).width;
    ctx.fillStyle = P.soft;
    ctx.font = `400 28px ${SANS}`;
    ctx.fillText("每次", PAD + nw + 18, 1284);
  } else {
    ctx.fillStyle = P.soft;
    ctx.font = `500 116px ${SERIF}`;
    ctx.fillText("—", PAD, 1284);
    ctx.fillStyle = P.soft;
    ctx.font = `400 28px ${SANS}`;
    ctx.fillText(cost === null ? "还没记价格" : "还没穿过，算不出", PAD + 104, 1284);
  }

  /* ---- 那句人话：屏幕上怎么说，图上就怎么说（cpwLine 是唯一出处） ---- */
  const costLine = typeof cpwLine === "function" ? cpwLine(w) : "";
  ctx.fillStyle = P.ink;
  ctx.font = `400 32px ${SERIF}`;
  const ls = longWrap(ctx, costLine, W - PAD * 2, 2);
  ls.forEach((ln, i) => { if (ln) ctx.fillText(ln, PAD, 1352 + i * 50); });

  /* ---- 判词：一道印章红竖线压着的一句，像杂志的编者按 ---- */
  const verdict = typeof cpwVerdict === "function" ? cpwVerdict(w) : "";
  let vy = 1352 + ls.length * 50 + 44;
  if (verdict) {
    const vs = longWrap(ctx, verdict, W - PAD * 2 - 32, 2);
    ctx.fillStyle = P.seal;
    ctx.fillRect(PAD, vy - 36, 5, vs.length * 52 - 6);
    ctx.fillStyle = P.ink;
    ctx.font = `400 36px ${SERIF}`;
    vs.forEach((ln, i) => ctx.fillText(ln, PAD + 32, vy + i * 52));
    vy += vs.length * 52;
  }

  /* ---- 三格数字：穿过 / 买了 / 上次穿 ----
   *  fy 有上限：三格的数字行占 64px，而落款那行字在 H-128。
   *  不加这个钳位，「判词折成两行 + 单次成本那句也折两行」那一版会把
   *  「买了 3 个月」直接画到落款字上——这张纸是要发出去的，压字比少画一格更坏。 */
  const facts = longItemFacts(w);
  const fy = Math.min(H - 232, Math.max(1580, vy + 76));
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, fy - 52); ctx.lineTo(W - PAD, fy - 52); ctx.stroke();
  const colW = (W - PAD * 2) / 3;
  facts.forEach((f, i) => {
    const x = PAD + i * colW;
    ctx.fillStyle = P.soft;
    ctx.font = `500 24px ${SANS}`;
    drawSpaced(ctx, f.k, x, fy, 5);
    ctx.fillStyle = P.ink;
    ctx.font = `400 44px ${SERIF}`;
    ctx.fillText(f.v, x, fy + 64);
  });

  /* ---- 落款：左边两行小字，右边一枚圆章 ---- */
  ctx.fillStyle = P.soft;
  ctx.font = `400 26px ${SANS}`;
  ctx.fillText("单次穿着成本 = 价格 ÷ 穿过次数", PAD, H - 128);
  ctx.fillStyle = P.soft;
  ctx.font = `400 26px ${SERIF}`;
  ctx.fillText("一张短笺，一次决定", PAD, H - 76);
  longRoundStamp(ctx, P, W - PAD - 66, H - 130, 66, "衣");
  return cv;
}

/* ---------------------------------------------------------------- 搭配长图 */

/** 一套搭配的拼版参数。列数跟件数走（两件并排、三件一列、四件起四列），
 *  但**行距与块高改成按行数分摊给定的高度**——写死 gh 的那一版，「6 件」排成
 *  两行时整块往下长了 610px，把「这套的账」和竖排落款一起挤到了纸外：
 *  6 件那一版两列竖排都只剩 1 格，落款变成「一套衣 / 裳…」两截。
 *  boxTop / boxBottom 是拼版区上下边界，由调用方按「哪里有富余」给出来。 */
function longPieceLayout(n, boxTop, boxBottom) {
  const span = 904;                       // W - PAD*2
  const cols = n <= 1 ? 1 : n === 2 ? 2 : n === 3 ? 3 : 4;
  const gap = cols <= 2 ? 28 : 22;
  const gw = (span - gap * (cols - 1)) / cols;
  const rows = Math.max(1, Math.ceil(Math.max(1, n) / cols));
  // 每件占的那条带：色块 + 名字 + 品类（四列时名字只有 216 宽，字号更小）
  const namePx = cols >= 4 ? 28 : 32;
  const capPx = 24;
  const labelH = cols >= 4 ? 44 : 50;      // 编号行
  const nameH = Math.round(namePx * 1.55);
  const capH = cols < 4 ? Math.round(capPx * 1.9) : 0;
  const gapBetweenRows = cols >= 4 ? 26 : 34;
  const fixed = rows * (labelH + nameH + capH) + (rows - 1) * gapBetweenRows;
  const avail = Math.max(0, (boxBottom - boxTop) - fixed);
  // 色块高度：一行时按比例铺满可用高，两行时对半分；上下限保证「不扁成一条」
  let gh = rows === 1 ? avail : avail / rows;
  gh = Math.max(rows === 1 ? 300 : 190, Math.min(rows === 1 ? 430 : 320, gh));
  const used = rows * (gh + labelH + nameH + capH) + (rows - 1) * gapBetweenRows;
  return { cols, gw, gh, gap, rows, namePx, capPx, labelH, nameH, capH,
           gapBetweenRows, used, nameGap: cols >= 4 ? 44 : 50, capGap: 88 };
}

/** 搭配长图（1080×1920）：一套搭配，像一页随身穿搭手册。
 *  从上到下：场合签 → 名字 → 件数/次数 → 几件的拼版（01 02 03 编号是印章红）
 *  → 这套的账 → 备注 → 竖排落款 + 落款章。 */
async function drawOutfitCard(o) {
  const { cv, ctx, P, W, H, PAD } = longSheet("JIAN · 衣笺 · 搭配");
  if (!ctx) return cv;
  const SERIF = CARD.SERIF, SANS = CARD.SANS;

  const wd = (typeof state !== "undefined" && state.wardrobe) || [];
  const ids = (o && o.ids) || [];
  const items = ids.map((id) => wd.find((x) => x.id === id)).filter(Boolean);
  const missing = Math.max(0, ids.length - items.length);

  if (!o) {
    ctx.fillStyle = P.soft; ctx.font = `400 44px ${SERIF}`;
    ctx.textAlign = "center";
    ctx.fillText("这一套已经不在了。", W / 2, 940);
    ctx.textAlign = "left";
    return cv;
  }

  /* ---- 场合签：它决定这套什么时候穿，所以摆在名字上面 ---- */
  const occ = o.occasion || "没标场合";
  ctx.font = `400 26px ${SANS}`;
  const ow = ctx.measureText(occ).width + 52;
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  roundRectPath(ctx, PAD, 206, ow, 58, 29);
  ctx.fillStyle = P.paper2; ctx.fill(); ctx.stroke();
  ctx.fillStyle = P.ink;
  drawSpaced(ctx, occ, PAD + 26, 245, 4);

  /* ---- 名字：宋体大字，最多两行 ---- */
  ctx.fillStyle = P.ink;
  ctx.font = `500 96px ${SERIF}`;
  const title = longWrap(ctx, o.name || "一套", W - PAD * 2, 2);
  if (title.length > 1) ctx.font = `500 80px ${SERIF}`;
  const titleStep = title.length > 1 ? 96 : 0;
  title.forEach((ln, i) => ctx.fillText(ln, PAD, 372 + i * titleStep));

  /* ---- 一行事实：几件 / 穿过几次 / 上次 ---- */
  const facts = [`${items.length} 件`];
  facts.push(o.worn ? `穿过 ${o.worn} 次` : "还没穿过");
  if (o.lastWorn && typeof relativeDays === "function") facts.push(`上次 ${relativeDays(o.lastWorn)}`);
  if (missing) facts.push(`${missing} 件已从柜里去掉`);
  const metaY = 372 + Math.max(0, title.length - 1) * titleStep + 64;
  ctx.fillStyle = P.soft;
  ctx.font = `400 28px ${SANS}`;
  drawSpaced(ctx, facts.join(" · "), PAD, metaY, 2);

  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  const ruleY = metaY + 54;
  ctx.beginPath(); ctx.moveTo(PAD, ruleY); ctx.lineTo(W - PAD, ruleY); ctx.stroke();

  /* ---- 分栏小标：「这一套」------ 
   *  从前这一行画在 ruleY + 66，而第一件色块的编号 01 画在 gy − 16 = ruleY + 94，
   *  两个 24px / 30px 的基线只差 22px —— 01 直接压在「套」字的右下角上。
   *  现在小标独占一行（基线 ruleY + 50），编号有自己的一条抬头线（色块上方 18px），
   *  二者之间隔着 46px 的空，任何字号都压不上。 */
  const labelBaseline = ruleY + 50;
  ctx.fillStyle = P.soft;
  ctx.font = `500 24px ${SANS}`;
  drawSpaced(ctx, "这一套", PAD, labelBaseline, 8);

  /* ---- 拼版：编号是印章红，名字与品类是墨色 ----
   *  这一张纸是**从两头往中间排**的：
   *    底（右栏）：日期基线 H−76 → 落款章（圆心 H−218、半径 56）→ 竖排落款（底边 1478）
   *    底（左栏）：这套的账 + 备注，整块坐在 H−76 之上
   *    顶：报头 156 → 场合签 → 名字 → 一行事实 → 分隔线 → 小标
   *  中间剩下的那段就是拼版区，全部给它。从前拼版区的下界是「预留一个估的上限」
   *  算出来的，两件/三件的搭配只用到 1200 就没了，下面空出 380px；六件又反过来
   *  把「这套的账」挤到落款头上。现在 gh 由 boxBottom 精确分摊，多出来的高度全在
   *  色块上，纸不会被掏空。
   *
   *  左栏/右栏在这里的分界：竖排落款占 x 900..992，所以左栏的文字一律 ≤ 860。
   *  从前「这套的账」那条细线横贯整张纸、正好从竖排落款的字身上穿过去。 */
  const shown = items.slice(0, 8);
  const labelBottom = ruleY + 50;
  const boxTop = labelBottom + 46;
  const accountTop = 1478;                            // 左栏「这套的账」不许越过这条线
  const L = longPieceLayout(shown.length || 1, boxTop, accountTop - 40);
  let bottom;
  if (!shown.length) {
    // 一件都不剩：不摆空拼版，把这个位置换成一句说明（空白要有理由）
    ctx.fillStyle = P.soft;
    ctx.font = `400 34px ${SERIF}`;
    ctx.fillText("这一套的几件都已经不在柜里了。", PAD, boxTop + 40);
    bottom = boxTop + 72;
  } else {
    let gy = boxTop + L.labelH;
    for (let i = 0; i < shown.length; i++) {
      const col = i % L.cols;
      if (i && col === 0) gy += L.gh + L.labelH + L.nameH + L.capH + L.gapBetweenRows;
      const x = PAD + col * (L.gw + L.gap);
      const it = shown[i];
      // 编号：01 / 02 … 印章红只在这排编号和最后的章上用。
      // 基线与色块顶隔开 labelH，和小标那一行彻底分开。
      ctx.fillStyle = P.seal;
      ctx.font = `500 30px ${SERIF}`;
      ctx.fillText(String(i + 1).padStart(2, "0"), x, gy - 18);
      await longFillBox(ctx, it.img, it.color, x, gy, L.gw, L.gh, 12, P);
      ctx.strokeStyle = P.line; ctx.lineWidth = 2;
      roundRectPath(ctx, x, gy, L.gw, L.gh, 12); ctx.stroke();
      ctx.fillStyle = P.ink;
      ctx.font = `400 ${L.namePx}px ${SERIF}`;
      const nm = longWrap(ctx, it.name || "未命名", L.gw, 1)[0];
      ctx.fillText(nm, x, gy + L.gh + L.nameGap);
      if (L.capH) {
        ctx.fillStyle = P.soft;
        ctx.font = `400 ${L.capPx}px ${SANS}`;
        ctx.fillText(String(it.cat || "衣"), x, gy + L.gh + L.capGap);
      }
    }
    // 拼版的真实底边 = 最后一个色块的底 + 名字 + 品类
    bottom = gy + L.gh + L.nameH + (L.capH ? L.capH : 0);
  }

  /* ---- 这套的账：算得出来才印。缺一件的价格就明说算不出来，不编一个均价 ----
   *  这一块钉在 accountTop 上（从纸底往上的第四段），不从拼版底边顺下来：
   *  顺下来的那一版，两件的搭配账贴在 1300、六件的账压在 1700，同一张纸两种重心。
   *  拼版把整段高度吃干净，于是这里恒等于 accountTop —— 留 20px 只是兜底。
   *  分隔线只画左栏那 820px，**不横穿右栏的竖排落款**。 */
  const acctRuleY = Math.max(bottom + 20, accountTop);
  const acctRight = 860;
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, acctRuleY); ctx.lineTo(acctRight, acctRuleY); ctx.stroke();
  let acctY = acctRuleY + 50;
  ctx.fillStyle = P.soft;
  ctx.font = `500 24px ${SANS}`;
  drawSpaced(ctx, "这套的账", PAD, acctY, 8);
  acctY += 44;
  const priced = shown.filter((it) => Number.isFinite(Number(it.price)) && it.price !== null && it.price !== undefined);
  ctx.font = `400 32px ${SERIF}`;
  if (shown.length && priced.length === shown.length) {
    const total = priced.reduce((s, it) => s + Number(it.price), 0);
    ctx.fillStyle = P.ink;
    const line1 = `合计 ${longMoney(total)}`;
    ctx.fillText(line1, PAD, acctY);
    const w1 = ctx.measureText(line1).width;
    if (o.worn) {
      ctx.fillStyle = P.soft;
      ctx.font = `400 28px ${SANS}`;
      ctx.fillText(`· 穿过 ${o.worn} 次，每次 ${longMoney(total / o.worn)}`, PAD + w1 + 16, acctY);
    }
    acctY += 46;
  } else if (shown.length) {
    ctx.fillStyle = P.soft;
    const lack = shown.length - priced.length;
    ctx.fillText(`有 ${lack} 件还没记价格，这套的账先算不出来。`, PAD, acctY);
    acctY += 46;
  }

  /* ---- 备注（有就当一句引文，没有就把版面留着——空白也是版式） ---- */
  if (o.note) {
    acctY += 22;
    ctx.fillStyle = P.seal;
    ctx.fillRect(PAD, acctY - 28, 5, 42);
    ctx.fillStyle = P.ink;
    ctx.font = `400 36px ${SERIF}`;
    const ns = longWrap(ctx, o.note, acctRight - PAD - 32, 2);
    ns.forEach((ln, i) => ctx.fillText(ln, PAD + 32, acctY + i * 50));
    acctY += (ns.length - 1) * 50 + 28;
  }

  /* ---- 竖排落款：从右往左，**以列的右边界为准向内排**。
   *  底边钉在 1478（落款章上沿之上 44px），两列各 5–6 格、34px；
   *  从前这里是 maxCols = 2 却按高度只给到 4 格，26 个字的落款会被切成三列
   *  而第三列被丢掉——「一套衣裳，一种日子。」只剩「一套衣裳，」。
   *  从右边界向内排的那一条也在这里：右边线就是 W − PAD，不再靠
   *  「中线 = W − PAD − 字号/2」凑，列距变大时最后一列不会顶出纸外。 */
  const stampR = 56, stampCy = H - 218, vBottom = 1478;
  const vPlan = longVerticalPlan("一套衣裳，一种日子。", {
    top: 1100, bottom: vBottom, fontMax: 36, fontMin: 32, colsMax: 2, minCells: 3,
    track: 1.34, gap: 1.34, align: "bottom",
  });
  if (vPlan) {
    ctx.fillStyle = P.ink;
    ctx.font = `400 ${vPlan.fp}px ${SERIF}`;
    paintVerticalPlan(ctx, vPlan, W - PAD);
  }
  longRoundStamp(ctx, P, W - PAD - stampR, stampCy, stampR, "搭");

  /* ---- 页脚：左一句落款，右一个日子。
   *  左边那句是**同一条摘录的横排复述**，和右上的竖排撞在一起读着像两句话；
   *  那张纸的右边已经有竖排了，页脚只留日子——左右各一句本来就没有需要。 ---- */
  ctx.fillStyle = P.soft;
  ctx.font = `400 26px ${SANS}`;
  ctx.textAlign = "right";
  ctx.fillText(`${dayStr(Date.now())} 存`, W - PAD, H - 76);
  ctx.textAlign = "left";
  return cv;
}

/* ---------------------------------------------------------------- 摘录长图 */

/** 摘录长图（1080×1920）：一句话 + 日期 + 印章，极简，像一张书签。
 *
 *  为什么竖排：书签是竖的，中文在竖条上本来就该竖着读；drawMagStyle 已经证明这套
 *  竖排件（Engine.verticalCols + drawVertical 的禁则与句读半格）能用在长图上——
 *  这里直接复用，不另写一份分列规则。 */
function drawQuoteCard(d) {
  const { cv, ctx, P, W, H, PAD } = longSheet("JIAN · 言笺 · 摘录");
  if (!ctx) return cv;
  const SERIF = CARD.SERIF, SANS = CARD.SANS;
  const text = String((d && d.text) || "").trim();

  /* ---- 一圈细框：这是一张「书签」，不是一张壁纸 ---- */
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  roundRectPath(ctx, 56, 196, W - 112, H - 196 - 64, 18);
  ctx.stroke();

  /* ---- 日期：书签上总得写着是哪一天 ---- */
  const ds = dayStr((d && d.t) || Date.now());
  ctx.fillStyle = P.soft;
  ctx.font = `400 26px ${SANS}`;
  ctx.textAlign = "center";
  drawSpaced(ctx, ds.split(".").join(" · "), W / 2, 274, 6);

  /* ---- 一道短竖线：把日期和正文隔开，也把视线引下去 ---- */
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(W / 2, 316); ctx.lineTo(W / 2, 382); ctx.stroke();

  /* ---- 正文：竖排，先算预算再排版 ----------------------------------------
   *  区间是 480..1420：上面那句日期 + 短竖线占到 382，下面「—— 出处 · 心情」
   *  的基线在 1508、方印从 1624 起，正文整块必须落在它们之间。
   *  从前这里是「按字数分三档定字号 + 按固定 step 硬往下排」：17 个字被切成
   *  12+5 两列，右列一路顶到底线、左列只到一半，读起来像句子被截断了；
   *  60 / 100 个字时 Engine.verticalCols 按格子数截尾，末尾连省略号都没有。
   *  现在交给 longVerticalPlan：字号从 64 往下试，第一个「整句放得下」的就是它，
   *  缩到 40 还放不下才截断，并且截断处一定有省略号。 */
  const top = 480, bottomLimit = 1420;
  ctx.fillStyle = P.ink;
  const plan = longVerticalPlan(text, {
    top, bottom: bottomLimit, fontMax: 64, fontMin: 40, colsMax: 4,
    track: 1.25, gap: 1.42, align: "center",
  });
  if (!plan || !plan.cols.length) {
    ctx.fillStyle = P.soft;
    ctx.font = `400 52px ${SERIF}`;
    ctx.fillText("这一句还空着。", W / 2, 940);
  } else {
    ctx.fillStyle = P.ink;
    ctx.font = `400 ${plan.fp}px ${SERIF}`;
    // 整块以纸的中线为轴：最右一列的右边线 = (W + 整块宽)/2，
    // 于是 left = (W − 整块宽)/2、right = (W + 整块宽)/2，两边余量永远相等。
    // 列距与字号成比例，整块再宽也不会越过 PAD（4 列 × 1.42 × 40 ≈ 228 < 452）。
    const rightEdge = (W + plan.width) / 2;
    paintVerticalPlan(ctx, plan, rightEdge);
  }

  /* ---- 出处与心情：有才印。两个都没有，这一段整块不出现 ---- */
  const bits = [];
  if (d && d.from) bits.push(`—— ${d.from}`);
  const mood = d && typeof digestMoodName === "function" ? digestMoodName(d.mood) : "没标";
  if (mood && mood !== "没标") bits.push(mood);
  if (bits.length) {
    ctx.fillStyle = P.soft;
    ctx.font = `400 30px ${SERIF}`;
    ctx.fillText(bits.join("  ·  "), W / 2, 1540);
  }

  /* ---- 方印：一枚真正的藏书印，压在日期的反面（下方） ---- */
  longSquareSeal(ctx, P, W / 2, 1690, 132, "笺");

  ctx.fillStyle = P.soft;
  ctx.font = `400 26px ${SERIF}`;
  ctx.fillText("一张短笺，一次决定", W / 2, 1832);
  ctx.textAlign = "left";
  return cv;
}

/** 存这三张新长图。落盘那一段走 card.js 的 `saveCanvasPng()`（全 App 唯一一份）——
 *  这一条链路以前抄了三遍，每一句收尾话都有过事故（原生壳里 a.click() 什么都不做，
 *  却照样 toast「已保存」），抄三遍就等于给三次犯同一个错的机会。
 *
 *  这里只剩「先画出来」这一步：画的时候可能抛（照片没加载完、字体没就绪），
 *  而那是这几张图自己的事。失败必须开口，也不许让按钮永远停在 busy。 */
async function saveLongCard(makeCanvas, name, btn) {
  let canvas = null;
  try {
    canvas = await makeCanvas();
  } catch (e) {
    console.warn(e);
    if (btn) btn.classList.remove("busy");
    toast("长图没画出来");
    return false;
  }
  return saveCanvasPng(canvas, name, btn, "正在写这一张…");
}

/** 三枚按钮各自的一句话：文件名决定用户在分享面板/下载里看到什么。
 *  「衣笺-单品-燕麦针织-2026.10.18.png」比「长图.png」有用得多——
 *  群里的图是按文件名找的。 */
function longFileName(kind, who) {
  const safe = String(who || "").replace(/[\\/:*?"<>|\s]+/g, "").slice(0, 20) || "笺";
  return `${kind}-${safe}-${dayStr(Date.now())}.png`;
}
