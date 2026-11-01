/** 笺 · 报告长图（1080×1920）
   两种版式的绘制都在这个文件里，和 app.js 一样是传统 <script>（不是 ES module），
   保证 file:// 双击 index.html 仍然可用；因此它必须在 app.js 之前加载——
   boot() 里要给「存成长图 / 复制这段话」绑上这里的函数。
   这里只依赖全局的 esc / toast / veil / copy / dayStr / hasNative / nativeShareFile 和 state。 */

/**
 * 长图上的色只认 styles.css 那一处。以前这里手抄了一份 INK/SOFT/LINE/CREAM 和三枚结论章色，
 * 改一处另一处不会跟着改——和引擎两端漂了 300 例是同一类事故，只不过这次漂的是对比度：
 * 「再想想」在 CSS 里修到 4.50:1 时，这里还会停在 2.26:1。
 */
function token(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

const CARD = {
  W: 1080, H: 1920, PAD: 48,
  SERIF: '"Songti SC","STSong","Noto Serif SC","SimSun",serif',
  SANS: '"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif',
  INK: token("--ink", "#2a2723"), SOFT: token("--ink-soft", "#6b645b"),
  LINE: token("--line", "#d9d0c2"), CREAM: token("--cream", "#faf7f1")
};
const STAMP_COLOR = {
  先别: token("--seal", "#b54a3c"),
  再想想: token("--seal-2", "#7a611f"),
  宜入: token("--ok", "#4a6b52")
};

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function wrapZh(str, n) {
  const lines = []; let buf = "";
  for (const ch of String(str || "")) {
    buf += ch;
    if (buf.length >= n) { lines.push(buf); buf = ""; }
  }
  if (buf) lines.push(buf);
  return lines;
}

/** 真字距：支持 ctx.letterSpacing 就交给它；不支持就逐字 measureText 手排。 */
function drawSpaced(ctx, text, x, y, gap) {
  if ("letterSpacing" in ctx) {
    ctx.save();
    ctx.letterSpacing = gap + "px";
    ctx.fillText(text, x, y);
    ctx.restore();
    return;
  }
  const prevAlign = ctx.textAlign;
  ctx.textAlign = "left";
  let cx = x;
  for (const ch of String(text || "")) {
    ctx.fillText(ch, cx, y);
    cx += ctx.measureText(ch).width + gap;
  }
  ctx.textAlign = prevAlign;
}

/**
 * 逐字竖排：x 为该列的中线，y 为首字顶部，step 为相邻两字的间距。
 * 画完恢复原来的对齐/基线，返回下一行的 y（画完最后一个字的底部）。
 * 句读只占半格：竖排惯例如此，也让挤进列尾的标点放得下——步距系数在 Engine.vCost。
 * 分列禁则（避头尾）在 Engine.verticalCols，那张表能单测。
 */
function drawVertical(ctx, str, x, y, step) {
  const prevAlign = ctx.textAlign, prevBase = ctx.textBaseline;
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  let cy = y;
  // 走 Engine.vClusters 而不是逐字：两个连续数字合成一格横排（纵中横），
  // 「16 个月」不会被拆成 1 和 6 两行。分列禁则用的是同一套单元，预算和画面才对得上。
  for (const c of Engine.vClusters(str)) {
    ctx.fillText(c.t, x, cy);
    cy += step * c.adv;
  }
  ctx.textAlign = prevAlign; ctx.textBaseline = prevBase;
  return cy;
}

function loadImg(src) {
  return new Promise((res) => {
    if (!src) return res(null);
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => res(null);
    im.src = src;
  });
}

function nearWord(gap) {
  return gap < 12 ? "几乎同色" : gap < 30 ? "同色系" : "隔得开";
}

/** 依据行；太长时退回短版本。 */
/** 薄柜子的说法只写一处：屏幕上的附注、长图、复制的话术都得有，
 *  否则「发出去的图」和「自己看到的」不是同一句话。 */
function thinNote(r, short) {
  if (!r || !r.thin) return "";
  const n = r.closetN || 0;
  return short ? ` · 柜里仅 ${n} 件` : `（柜里只有 ${n} 件，这个判定还薄。）`;
}

function basisLine(r, short) {
  if (!r.basis) return "";
  const wear = r.basis.wearShort ? " · " + r.basis.wearShort : "";
  const thin = thinNote(r, short);
  if (short) return `最近的一件：「${r.basis.name}」· 色差 ${r.gap}${wear}${thin}`;
  return `柜里最像的一件：「${r.basis.name}」· 色差 ${r.gap} · ${nearWord(r.gap)}${wear}${thin}`
    + (r.toneLine ? ` ${r.toneLine}` : "");
}

function fitLine(ctx, text, maxW, alt) {
  return ctx.measureText(text).width > maxW ? alt() : text;
}

function drawStamp(ctx, x, y, radius, stamp, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-12 * Math.PI / 180);
  ctx.fillStyle = "rgba(250,247,241,0.90)";
  ctx.beginPath(); ctx.arc(0, 0, radius, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = color; ctx.lineWidth = 6;
  ctx.beginPath(); ctx.arc(0, 0, radius, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = color;
  ctx.font = `500 ${Math.round(radius * 0.58)}px ${CARD.SERIF}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(stamp, 0, 2);
  ctx.restore();
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
}

/** 柜里最近两件的缩略图，两种版式共用。 */
async function drawClosetRows(ctx, r, x, y, boxW, boxH, gap) {
  const items = (r.close || []).slice(0, 2);
  for (let i = 0; i < 2; i++) {
    const it = items[i];
    const bx = x + i * (boxW + gap);
    if (!it) {
      ctx.strokeStyle = CARD.LINE; ctx.lineWidth = 2;
      ctx.setLineDash([8, 8]);
      ctx.strokeRect(bx, y, boxW, boxH);
      ctx.setLineDash([]);
      ctx.fillStyle = CARD.SOFT;
      ctx.font = `400 24px ${CARD.SANS}`;
      ctx.fillText("柜里还没有", bx + 24, y + boxH / 2);
      continue;
    }
    const im = await loadImg(it.img);
    if (im) {
      ctx.save();
      ctx.beginPath(); ctx.rect(bx, y, boxW, boxH); ctx.clip();
      const sc = Math.max(boxW / im.width, boxH / im.height);
      const dw = im.width * sc, dh = im.height * sc;
      ctx.drawImage(im, bx + (boxW - dw) / 2, y + (boxH - dh) / 2, dw, dh);
      ctx.restore();
    } else {
      ctx.fillStyle = it.color || "#d4c4b0";
      ctx.fillRect(bx, y, boxW, boxH);
    }
    ctx.fillStyle = CARD.INK;
    ctx.font = `400 24px ${CARD.SANS}`;
    ctx.fillText(String(it.name || "柜里").slice(0, 10), bx, y + boxH + 38);
  }
}

/** 版式一 · 卡片：图在上，字在下，柜里两件并排在底。 */
async function drawCardStyle(r, n) {
  const { W, H, PAD, SERIF, SANS, INK, SOFT, LINE, CREAM } = CARD;
  const stampColor = STAMP_COLOR[r.stamp] || "#4a6b52";
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.fillStyle = CREAM;
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = SOFT;
  ctx.font = `500 24px ${SANS}`;
  drawSpaced(ctx, "JIAN · 衣笺", PAD, 92, 6);
  ctx.textAlign = "right";
  ctx.fillText(dayStr(Date.now()), W - PAD, 92);
  ctx.textAlign = "left";
  ctx.strokeStyle = LINE; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, 124); ctx.lineTo(W - PAD, 124); ctx.stroke();

  const mx = PAD, my = 150, mw = W - PAD * 2, mh = 830;
  const mainImg = await loadImg(n.img);
  if (mainImg) {
    ctx.save();
    roundRectPath(ctx, mx, my, mw, mh, 10); ctx.clip();
    const sc = Math.max(mw / mainImg.width, mh / mainImg.height);
    const dw = mainImg.width * sc, dh = mainImg.height * sc;
    ctx.drawImage(mainImg, mx + (mw - dw) / 2, my + (mh - dh) / 2, dw, dh);
    ctx.restore();
  } else {
    ctx.fillStyle = n.color || "#d4c4b0";
    roundRectPath(ctx, mx, my, mw, mh, 10); ctx.fill();
  }
  drawStamp(ctx, W - PAD - 108, my + 118, 74, r.stamp, stampColor);

  ctx.fillStyle = INK;
  ctx.font = `500 30px ${SANS}`;
  ctx.fillText(`想买 · ${n.cat || "衣"}`, PAD, 1030);

  ctx.font = `400 42px ${SERIF}`;
  const all = wrapZh(r.quote || "", 17);
  const lines = all.slice(0, 3);
  if (all.length > 3) lines[2] = lines[2].slice(0, -1) + "…";
  lines.forEach((ln, i) => ctx.fillText(ln, PAD, 1105 + i * 66));

  let cursor = 1105 + Math.max(1, lines.length) * 66 + 30;
  if (r.basis) {
    ctx.fillStyle = SOFT;
    ctx.font = `400 26px ${SANS}`;
    ctx.fillText(fitLine(ctx, basisLine(r, false), W - PAD * 2, () => basisLine(r, true)), PAD, cursor);
    cursor += 44;
  }

  const cy = 1458;
  const mates = (r.match || []).slice(0, 3);
  if (mates.length && cursor < cy - 62) {
    ctx.fillStyle = SOFT;
    ctx.font = `400 26px ${SANS}`;
    ctx.fillText(`也能配：${mates.map((x) => x.name).join("、")}`, PAD, cursor);
  }
  ctx.strokeStyle = LINE; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, cy - 44); ctx.lineTo(W - PAD, cy - 44); ctx.stroke();
  ctx.fillStyle = SOFT;
  ctx.font = `500 24px ${SANS}`;
  ctx.fillText("柜里最近的两件", PAD, cy);
  await drawClosetRows(ctx, r, PAD, cy + 24, (W - PAD * 2 - 24) / 2, 230, 24);

  ctx.textAlign = "center";
  ctx.fillStyle = SOFT;
  ctx.font = `400 24px ${SERIF}`;
  ctx.fillText("一张短笺，一次决定", W / 2, H - 58);
  return c;
}

/**
 * 版式二 · 杂志：照片收在左侧，右边缘留出一条纸白，金句竖排成「独立杂志」式的大字。
 * 竖排标题住在纸白里，永远不压照片主体；圆印章也从图上搬下来，与标题同住纸白。
 */
async function drawMagStyle(r, n) {
  const { W, H, PAD, SERIF, SANS, INK, SOFT, LINE, CREAM } = CARD;
  const stampColor = STAMP_COLOR[r.stamp] || "#4a6b52";
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.fillStyle = CREAM;
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = stampColor;
  ctx.fillRect(0, 0, W, 8);

  const imgH = 1180;
  const BAND = 292;              // 右侧纸白的宽度
  const imgW = W - BAND;

  const mainImg = await loadImg(n.img);
  if (mainImg) {
    const sc = Math.max(imgW / mainImg.width, imgH / mainImg.height);
    const dw = mainImg.width * sc, dh = mainImg.height * sc;
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, imgW, imgH); ctx.clip();
    ctx.drawImage(mainImg, (imgW - dw) / 2, (imgH - dh) / 2, dw, dh);
    ctx.restore();
  } else {
    ctx.fillStyle = n.color || "#d4c4b0";
    ctx.fillRect(0, 0, imgW, imgH);
  }

  // 顶栏同样垫一层，否则浅色照片上白字看不见
  const topGrad = ctx.createLinearGradient(0, 0, 0, 140);
  topGrad.addColorStop(0, "rgba(18,16,14,0.44)");
  topGrad.addColorStop(1, "rgba(18,16,14,0)");
  ctx.fillStyle = topGrad;
  ctx.fillRect(0, 8, imgW, 140);

  ctx.fillStyle = "rgba(250,247,241,0.94)";
  ctx.font = `500 24px ${SANS}`;
  drawSpaced(ctx, "JIAN · 衣笺", PAD, 76, 6);
  ctx.textAlign = "right";
  ctx.fillText(dayStr(Date.now()), imgW - 24, 76);
  ctx.textAlign = "left";

  // 纸白与照片之间一道细线，杂志分栏的味道；印章与竖排标题都住在纸白里
  ctx.strokeStyle = LINE; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(imgW + 1, 44); ctx.lineTo(imgW + 1, imgH - 44); ctx.stroke();
  drawStamp(ctx, W - BAND / 2, 186, 84, r.stamp, stampColor);

  // 竖排标题：金句从右往左分列，墨色大字。步距比字高大一点，疏朗才有期刊感
  const fontPx = 48, step = 56, colPitch = 64, maxCols = 4;
  const titleTop = 316, titleBottom = imgH - 44;
  // 预算按「一个字的顶位还能走到几步」算，要减掉字高，否则列尾会掉到照片外面
  const perCol = Math.max(1, (titleBottom - titleTop - fontPx) / step);
  ctx.fillStyle = INK;
  ctx.font = `400 ${fontPx}px ${SERIF}`;
  const cols = Engine.verticalCols(r.quote, perCol, maxCols);
  cols.forEach((line, i) => {
    drawVertical(ctx, line, W - PAD - fontPx / 2 - i * colPitch, titleTop, step);
  });

  let y = imgH + 84;
  ctx.fillStyle = INK;
  ctx.font = `500 30px ${SANS}`;
  ctx.fillText(`想买 · ${n.cat || "衣"}`, PAD, y);

  y += 56;
  if (r.basis) {
    ctx.fillStyle = SOFT;
    ctx.font = `400 26px ${SANS}`;
    ctx.fillText(fitLine(ctx, basisLine(r, false), W - PAD * 2, () => basisLine(r, true)), PAD, y);
    y += 44;
  }
  const mates = (r.match || []).slice(0, 3);
  if (mates.length) {
    ctx.fillStyle = SOFT;
    ctx.font = `400 26px ${SANS}`;
    ctx.fillText(`也能配：${mates.map((x) => x.name).join("、")}`, PAD, y);
    y += 44;
  }

  y += 72;
  ctx.strokeStyle = LINE; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, y - 44); ctx.lineTo(W - PAD, y - 44); ctx.stroke();
  ctx.fillStyle = SOFT;
  ctx.font = `500 24px ${SANS}`;
  ctx.fillText("柜里最近的两件", PAD, y);
  await drawClosetRows(ctx, r, PAD, y + 26, (W - PAD * 2 - 20) / 2, 290, 20);

  ctx.textAlign = "center";
  ctx.fillStyle = SOFT;
  ctx.font = `400 24px ${SERIF}`;
  ctx.fillText("一张短笺，一次决定", W / 2, H - 58);
  return c;
}

/* ==================== 长图落盘：全 App 唯一的一份 ====================
 *
 *  这一条链路以前写了三遍（衣笺报告 / 年度总结 / 三张新长图），三段逐行几乎一样，
 *  只在「怎么拿到 canvas」「文件名」「按钮上那句进行中的话」上不同。这正是本仓反复
 *  栽的那一族：**同一件事两份定义，迟早只剩一份是对的**。事实也是——三条路径各自
 *  独立长出来的，其中两条都曾经犯过同一个错（原生死链之后继续走一次 WebView 里
 *  根本不会发生的下载，然后照样 toast「已保存」）。
 *
 *  所以收成一份 `saveCanvasPng()`，三条路都从它走。它只管一件事：**把一张已经画好的
 *  canvas 交出去，并且如实说交到了哪一步**。画不画得出来、按钮挡不挡，留在各自的调用点
 *  （那是每张图自己的产品判断，不该住在这里）。
 *
 *  参数：
 *    canvas   已经画好的 HTMLCanvasElement（调用方负责画）
 *    name     文件名（用户在分享面板/下载里看到的就是它）
 *    btn      显示「正在写…」并在结束后复原的按钮，可空
 *    busyWord 按钮上那句进行中的话，默认「正在写这张…」
 *  返回 Promise<boolean>：真的交出去了 true，任何一步没走通 false。
 *
 *  三条硬规矩，改之前先读：
 *  1. **原生壳里失败不许回落到下载。** `a.click()` 在 WebView 里什么都不做，
 *     掉下去再 toast「已保存」就是一句假话。这里失败就 `return false` 并说 SHARE_FAILED。
 *  2. **按钮一定要复原。** 三条路以前各写了一遍 reset，其中一条漏过 catch 分支。
 *  3. **toast 说的是「交出去了」，不是「存好了」。** 那句话在 doneMsg() 里，
 *     浏览器与原生两种说法都由它给（第 41 轮）。
 */
async function saveCanvasPng(canvas, name, btn, busyWord) {
  const b = btn || null;
  const label = b ? b.textContent : "";
  const reset = () => { if (b) { b.textContent = label; b.classList.remove("busy"); } };
  if (b) { b.textContent = busyWord || "正在写这张…"; b.classList.add("busy"); }
  if (!canvas || !canvas.width) { reset(); toast("长图没画出来"); return false; }

  if (hasNative()) {
    // App 里没有「下载」这回事：写进缓存目录，交系统分享面板。
    try {
      await nativeShareFile(name, bareBase64(canvas.toDataURL("image/png")), { directory: "Cache" });
      reset();
      toast(doneMsg("保存长图"), 5200);
      return true;
    } catch (e) {
      console.warn(e);
      reset();
      toast(SHARE_FAILED, 5200);
      return false;
    }
  }

  // 浏览器：真的触发一次下载，然后不管成没成都要把按钮复原
  const done = (href, revoke) => {
    const a = document.createElement("a");
    a.download = name;
    a.href = href;
    a.click();
    if (revoke) setTimeout(() => URL.revokeObjectURL(href), 4000);
    reset();
    toast(doneMsg("保存长图"), 5200);
  };
  try {
    if (canvas.toBlob) {
      await new Promise((resolve) => {
        canvas.toBlob((blob) => {
          if (blob) done(URL.createObjectURL(blob), true);
          else done(canvas.toDataURL("image/png"), false);
          resolve();
        }, "image/png");
      });
    } else {
      done(canvas.toDataURL("image/png"), false);
    }
    return true;
  } catch (e) {
    console.warn(e);
    reset();
    toast("长图没存下来");
    return false;
  }
}

async function saveCard() {
  const r = state.lastReport, n = r && r.new;
  // 画不出来的那一张不许静默：这一枚是 aria-disabled（能聚焦、能按下），
  // 按下去就得说得出为什么存不了（真 disabled 会让读屏器连这个问题都问不到）。
  if (!n) { toast("先过一张笺，才存得出长图"); return; }
  // 画这一步可能抛（字体没就绪、图片坏掉），交给 saveCanvasPng 之外的一层兜住：
  // 它只收「已经画好的 canvas」，画的过程出了什么事由这里负责说出来。
  let canvas = null;
  const btn = $("#saveCard");
  try {
    canvas = state.reportStyle === "mag"
      ? await drawMagStyle(r, n)
      : await drawCardStyle(r, n);
  } catch (e) {
    console.warn(e);
    toast("长图没画出来");
    return;
  }
  await saveCanvasPng(canvas, `衣笺-${dayStr(Date.now())}.png`, btn, "正在写这张笺…");
}

/** 一张衣笺的报告说成可复制的那段话。报告页与笺册共用一份：
 *  以前只有报告页能复制，笺册里那行只是「记得有这么回事」，想再发一次只能重拍一张。 */
function reportText(r) {
  if (!r) return "";
  const parts = [`【衣笺】${r.stamp}`, r.quote];
  if (r.basis) {
    let b = `（柜里最像的一件：${r.basis.name} ${r.basis.cat}，色差 ${r.gap}`;
    if (r.basis.wear) b += `，${r.basis.wear}`;
    parts.push(b + "）");
  }
  const thin = thinNote(r, false);
  if (thin) parts.push(thin);                      // 有没有依据都单占一行，别只挂在依据后面
  if (r.toneLine) parts.push(r.toneLine);          // 冷暖调这一句：屏幕上有的，复制出去也得有
  if ((r.match || []).length) parts.push(`也能配：${r.match.map((x) => x.name).join("、")}`);
  parts.push("—— 一张短笺，一次决定");
  return parts.join("\n");
}

function copyReportText() {
  // 早退的条件与「这枚按钮挡不挡」必须是同一句话（yi.js 的 reportCopyable），
  // 两边各写一份的话，总有一天会差出一个「按下去什么都不说」的静默分支。
  // 而且挡下时必须**开口**：aria-disabled 的钮按得下去，说不出理由就等于回到静默。
  if (!reportCopyable()) { toast("还没有一张笺可复制"); return; }
  copy(reportText(state.lastReport), "已复制，去粘给朋友");
}
