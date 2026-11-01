/** 笺 · 长图之二：年度总结（1080×1920）
 *
 *  从 card.js 里分出来的。分家的理由不是「文件太长不好看」，是**载荷门**
 *  （scripts/test.mjs 的 MAX_FILE_KB = 64）：card.js 长到 74KB 时 test:pkg 红在
 *  「www 载荷 / 安卓 assets 有超过 64KB 的文件」，而那一道红的判据是项目自己定的
 *  ——「单个文件超过这个数，就该问一句『非不可吗』」。
 *
 *  为什么可以分而不伤：三段之间**只有运行期调用，没有解析期依赖**。
 *  card.js 的 CARD / token 是 const，但读它们的地方全在函数体里，函数要到 boot()
 *  之后才跑；所以三份谁先加载都不影响。真正的加载顺序约束只对 state.js 那一族成立
 *  （它在 parse 期就执行 normalizeState）。
 *
 *  内容一个字节没改：这一份就是原来 card.js 里「年度总结长图」那一整段，
 *  连同它下面那三张新长图共用的 tokenLight / CARD_LIGHT_FALLBACK 一起搬过来。
 *  三张新长图在 card-long.js，它反过来要读这里的 tokenLight——那是运行期调用，
 *  而 card-long.js 排在本文之后加载，所以读得到。
 *
 *  硬约束（与 card-long.js、card.js 同一套，改之前先读）：
 *  1. 永远是白天的纸：只走 tokenLight()，不走 token()
 *  2. 数据薄就不画：少于 10 天拒绝生成并说清还差几天
 *  3. 失败一律开口：不许静默
 */

/* ==================== 年度总结长图（v0.6.0 · 笺谱 lane 追加） ====================
 *
 *  这一段的来由：笺谱那一屏的「这一年」要能被**发出去**——发给朋友、贴进群里、
 *  存进相册。它和上面两张衣笺长图是同一族，但有三条自己的硬约束：
 *
 *  1. **永远是白天的纸。** 深色模式下也是浅纸：这张图会被别人看见，
 *     而别人看见的应该是「一张笺」，不是「某台手机的夜间模式」。
 *     所以取色**不走 token()**（它读 getComputedStyle，会跟着 data-theme 翻），
 *     走 tokenLight()——它从 `:root[data-theme="light"]` 那份令牌里读，
 *     读不到就退回上面那张表的默认值。CARD 常量本身也是开机时按当时的主题取的，
 *     所以这里连 CARD 都不能直接用——全部走 light 那一份。
 *
 *  2. **版式像一本杂志的跨页。** 宋体大数字、印章红只做一次强调、留白克制：
 *     一张 1080×1920 的竖纸，从上到下是「报头 → 大标题 → 一句总结 → 月曲线 →
 *     四格数字 → 两条最 → 落款」。
 *
 *  3. **数据薄就不画。** 少于 10 天（stats.js 的 yearThin）时**拒绝生成**并说清还差几天，
 *     绝不用一条编出来的曲线凑满纸面。
 */

/** 长图专用取色：只认「白天的纸」那一份令牌。
 *
 *  为什么不复用 token()：token() 读的是 documentElement 上的计算值，而
 *  `:root[data-theme="dark"]` 会把 --paper / --cream / --ink 全都换掉——夜里存出来的
 *  长图就是黑底浅字（实测过：整张纸 #1b1917，贴进群里像另一个 App）。
 *  这里探一个临时节点、把它钉在 :root[data-theme="light"] 的作用域里量：
 *  用 `all: initial` 隔离继承，再把 data-theme 换到 light 量一次、换回来。
 *
 *  代价是两次强制重排（毫秒级，一屏只存一张图，值）。收益是**深色模式下长图仍然是浅纸**，
 *  而代码里没有第二条纸色定义——纸色还是只有 styles.css 那一处。 */
const CARD_LIGHT_FALLBACK = {
  "--paper": "#f4efe6", "--paper-2": "#ebe4d6", "--cream": "#faf7f1",
  "--ink": "#2a2723", "--ink-soft": "#6b645b", "--line": "#d9d0c2", "--seal": "#b54a3c",
  "--seal-2": "#7a611f", "--ok": "#4a6b52",
};
function tokenLight(name, fallback) {
  const root = document.documentElement;
  const was = root.dataset.theme;
  try {
    root.dataset.theme = "light";
    const v = getComputedStyle(root).getPropertyValue(name).trim();
    if (v) return v;
  } catch (_) { /* 掉到兜底 */ }
  finally {
    if (was === undefined) delete root.dataset.theme; else root.dataset.theme = was;
  }
  return CARD_LIGHT_FALLBACK[name] || fallback || "#000";
}

/** 年度长图用的一整套「白天的纸」色。函数而不是常量：一次存图取一次，
 *  中间用户换了主题也不会留下半套旧值（这份东西会被缓存到整页级吗？不会——
 *  每次 drawYearCard 调一次，几微秒）。 */
function yearPalette() {
  return {
    paper: tokenLight("--paper", "#f4efe6"),
    paper2: tokenLight("--paper-2", "#ebe4d6"),
    cream: tokenLight("--cream", "#faf7f1"),
    ink: tokenLight("--ink", "#2a2723"),
    soft: tokenLight("--ink-soft", "#6b645b"),
    line: tokenLight("--line", "#d9d0c2"),
    seal: tokenLight("--seal", "#b54a3c"),
  };
}

/** 一句话总结：从账本里挑一句真话（不是形容词）。竖排的那一行读它。
 *  四条优先级：记了很多天 → 记得最勤的是哪一笺 → 最长连续 → 刚开始。 */
function yearLine(yb) {
  const kinds = yb.kinds || {};
  const top = Object.keys(kinds).sort((a, b) => kinds[b] - kinds[a])[0];
  const kindSay = { wear: "穿衣", cook: "下厨", catch: "捞笺", plan: "排桌", note: "摘录", wish: "忍住" };
  if (yb.days >= 100) return `一年里 ${yb.days} 天，我都在这张笺上留了一笔。`;
  if (top && kinds[top] >= 20) return `这一年，我在这张纸上写了 ${kinds[top]} 次${kindSay[top] || "事"}。`;
  if (yb.best >= 7) return `最长的一次，我连着 ${yb.best} 天回到这里。`;
  return `${yb.year} 年，我把日子攒成了 ${yb.days} 天。`;
}

/** 画年度总结长图（1080×1920）。返回 canvas。
 *  这是**纯同步**的：不加载任何图片（年度总结没有照片），所以不必 await。 */
function drawYearCard(yb, wr, c) {
  const P = yearPalette();
  const W = 1080, H = 1920, PAD = 88;
  const SERIF = CARD.SERIF, SANS = CARD.SANS;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;         // 写死尺寸：测试与「存图」都按这个数验收
  const ctx = cv.getContext("2d");
  if (!ctx) return cv;

  /* ---- 纸 ---- */
  ctx.fillStyle = P.paper;
  ctx.fillRect(0, 0, W, H);
  // 一道极淡的纸纹：竖线 1px / 7px，和 styles.css 的 body 背景同一个手法。
  // 用 paper2 而不是 rgba：长图会被压缩转发，半透明细纹在压缩里会糊成一片脏灰。
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = P.paper2;
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 7) {
    ctx.beginPath(); ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, H); ctx.stroke();
  }
  ctx.restore();

  /* ---- 报头：JIAN · 2026 ---- */
  ctx.fillStyle = P.soft;
  ctx.font = `500 26px ${SANS}`;
  drawSpaced(ctx, "JIAN · 笺谱", PAD, 116, 8);
  ctx.textAlign = "right";
  ctx.fillText(String(yb.year), W - PAD, 116);
  ctx.textAlign = "left";
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, 156); ctx.lineTo(W - PAD, 156); ctx.stroke();

  /* ---- 大标题 ---- */
  ctx.fillStyle = P.ink;
  ctx.font = `400 132px ${SERIF}`;
  drawSpaced(ctx, "这一年", PAD, 336, 10);

  /* ---- 一句话总结（正文，宋体，两行以内） ----
   *  按字数硬折会把最后一行折成三个字（「捞笺。」独占一行）——杂志不会那样断行。
   *  所以按宽度折，两行时再按**显示宽度**把断点挪到中间：两行等长，读起来是一句话
   *  而不是两截。从前按「17 字」这种字数折，「一年里 153 天，我 / 都在…」里的
   *  数字是半角，两行的实际像素宽差了 200px 还多——「等长」是看起来等长，不是数出来。 */
  ctx.fillStyle = P.soft;
  ctx.font = `400 40px ${SERIF}`;
  const line = yearLine(yb);
  const sumMaxW = W - PAD * 2;
  let sumLines = longWrap(ctx, line, sumMaxW, 2);
  if (sumLines.length === 2) {
    const chars = [...line];
    let bestI = 1, bestD = Infinity;
    for (let i = 1; i < chars.length; i++) {
      const a = chars.slice(0, i).join(""), b = chars.slice(i).join("");
      if (ctx.measureText(a).width > sumMaxW || ctx.measureText(b).width > sumMaxW) continue;
      const d = Math.abs(ctx.measureText(a).width - ctx.measureText(b).width);
      if (d < bestD) { bestD = d; bestI = i; }
    }
    sumLines = [chars.slice(0, bestI).join(""), chars.slice(bestI).join("")];
  }
  sumLines.forEach((ln, i) => ctx.fillText(ln, PAD, 424 + i * 58));

  /* ---- 三个大数字：笔 / 天 / 连续 ---- */
  const statY = 610;
  const cols = [
    { n: yb.events, unit: "笔", cap: "记下来的事" },
    { n: yb.days, unit: "天", cap: "有记录的日子" },
    { n: yb.best, unit: "天", cap: "最长连续" },
  ];
  const colW = (W - PAD * 2) / 3;
  cols.forEach((s, i) => {
    const x = PAD + i * colW;
    ctx.fillStyle = i === 0 ? P.seal : P.ink;   // 印章红**只点一次**：第一个数字
    ctx.font = `500 96px ${SERIF}`;
    ctx.textAlign = "left";
    ctx.fillText(String(s.n), x, statY);
    const nw = ctx.measureText(String(s.n)).width;
    ctx.fillStyle = P.soft;
    ctx.font = `400 28px ${SANS}`;
    ctx.fillText(s.unit, x + nw + 8, statY);
    ctx.font = `400 24px ${SANS}`;
    ctx.fillStyle = P.soft;
    ctx.fillText(s.cap, x, statY + 44);
  });

  /* ---- 十二个月：折线 + 底部的点 ---- */
  /* ---- 十二个月：折线 + 底部的点 ----
   *  折线画在 chartL..chartR 的**内侧**：从前点画在线的两个端点上，1 月那个点
   *  和 12 月那个点的圆边各探出去 5px，比正文的 PAD 还靠外（108 / 1005）。
   *  把可画区收进 16px，点和它的描边就都落在纸里了。 */
  const chartTop = 800, chartH = 340, chartInset = 16;
  const chartL = PAD + chartInset, chartR = W - PAD - chartInset, chartW = chartR - chartL;
  const maxM = Math.max(1, ...(yb.months || [0]));
  // 顶点留 12% 的余量：12 个月都一样多的那一年，折线会正好贴着框顶，
  // 下面的淡色面积铺成一个满框的实心块——看着像一个未加载的占位图。
  const chartPeak = chartH * 0.88;
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, chartTop + chartH); ctx.lineTo(W - PAD, chartTop + chartH); ctx.stroke();
  const pts = (yb.months || []).map((n, i) => ({
    x: chartL + (chartW / 11) * i,
    y: chartTop + chartH - (n / maxM) * chartPeak,
    n,
  }));
  // 折线下面的淡色面积：让「哪几个月在动」一眼看得出来。
  // 用 globalAlpha 而不是 rgba：纸色仍然只有 styles.css 那一处定义，
  // 这里只是把纸纹那层的同一个手法（半透明铺色）用在面积上。
  // 12 个月一样多的那一年，面积会铺成一个方框——半透明之后它读作「一片没起伏」，
  // 而不是一张没加载出来的占位图。
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.lineTo(chartR, chartTop + chartH);
  ctx.lineTo(chartL, chartTop + chartH);
  ctx.closePath();
  ctx.save();
  ctx.globalAlpha = 0.62;
  ctx.fillStyle = P.paper2;
  ctx.fill();
  ctx.restore();
  // 折线本身
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.strokeStyle = P.seal; ctx.lineWidth = 4;
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.stroke();
  // 每个月一个点；最高的那个点更大一点
  pts.forEach((p) => {
    const big = p.n === maxM && p.n > 0;
    ctx.beginPath();
    ctx.arc(p.x, p.y, big ? 9 : 5, 0, Math.PI * 2);
    ctx.fillStyle = big ? P.seal : P.cream;
    ctx.fill();
    ctx.strokeStyle = P.seal; ctx.lineWidth = big ? 0 : 3;
    if (!big) ctx.stroke();
  });
  // 月份刻度：1 / 3 / 6 / 9 / 12，别的会挤。
  // 两头的刻度改成左/右对齐在「PAD 到线端」之间：居中放在端点上的那一版，
  // 「1」和「12」各有一半探到 PAD 外面（81 和 1005），比正文还靠边。
  ctx.fillStyle = P.soft;
  ctx.font = `400 24px ${SANS}`;
  [0, 2, 5, 8, 11].forEach((i) => {
    const w = ctx.measureText(`${i + 1}`).width;
    const x = Math.max(PAD, Math.min(W - PAD - w, pts[i].x - w / 2));
    ctx.textAlign = "left";
    ctx.fillText(`${i + 1}`, x, chartTop + chartH + 44);
  });
  ctx.textAlign = "left";
  ctx.fillStyle = P.soft;
  ctx.font = `400 24px ${SANS}`;
  ctx.fillText("每个月记了多少笔", PAD, chartTop - 34);

  /* ---- 几条「最」----
   *  左栏从 PAD 到 PAD+500，右栏（竖排落款 + 落款章）从 ~900 起。
   *  「最」的条数不定（没记的就不印），所以这一块的高度**算出来**再决定
   *  竖排落款的起点：从前 vTop 写死 1292，四条「最」的时候最后一条会掉到
   *  竖排的下面去，右边那一列几乎顶到页脚。 */
  const listX = PAD, valX = PAD + 200, rowStep = 62, listTop = 1300;
  ctx.strokeStyle = P.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, listTop - 28); ctx.lineTo(W - PAD, listTop - 28); ctx.stroke();
  // 右栏从 ~870 起（竖排落款 + 落款章都在那儿），左栏的「值」不许长进去：
  // 一件名字很长的衣服（「燕尾服式样的深灰色羊毛大衣」）在 34px 下能到 700px 宽，
  // 从前它就直接画到竖排落款身上去了。
  const valMaxW = W - PAD - 150 - valX;
  const two = [
    yb.topWear ? { k: "穿得最多", v: `${yb.topWear.name} · ${yb.topWearN} 次` } : null,
    yb.topCook ? { k: "做得最多", v: `${yb.topCook} · ${yb.topCookN} 次` } : null,
    wr && wr.total ? { k: "柜里", v: `${wr.total} 件，${wr.worn} 件穿过` } : null,
    Number.isFinite(c && c.cpw) ? { k: "单次成本", v: `¥${c.cpw.toFixed(1)}` } : null,
  ].filter(Boolean);
  let y = listTop;
  two.forEach((row) => {
    ctx.fillStyle = P.soft;
    ctx.font = `400 28px ${SANS}`;
    ctx.fillText(row.k, listX, y);
    ctx.fillStyle = P.ink;
    ctx.font = `500 34px ${SERIF}`;
    ctx.fillText(longWrap(ctx, row.v, valMaxW, 1)[0], valX, y);
    y += rowStep;
  });
  if (!two.length) {
    ctx.fillStyle = P.soft;
    ctx.font = `400 28px ${SANS}`;
    ctx.fillText("这一年还没有记下「最常做」的那几件事。", listX, y);
    y += rowStep;
  }
  const listBottom = y - rowStep;

  /* ---- 竖排落款：一句总结，从右往左 ----
   *  右栏的上沿 = 左边那几条「最」的底边 + 40：左栏写得长，落款就往下让；
   *  右栏的下沿 = 落款章的顶边 − 30。中间这段高度整块交给 longVerticalPlan，
   *  用 40px 排两列、每列最多 8 格（26 个字含两个半角句读要 24 格，正好两列）。
   *  从前这里是「vTop 写死、vBottom = H − 190、perCol 用除法」：26 个字被切成
   *  10+10+6 三列（maxCols 却是 2，第三列直接被丢掉），也不管内文到底几列。 */
  const stampR = 52, stampCy = H - 218;
  const vBottom = stampCy - stampR - 26;
  const vTop = Math.min(Math.max(listBottom + 40, 1240), vBottom - 260);
  const vPlan = longVerticalPlan("一张短笺，一次决定。", {
    top: vTop, bottom: vBottom, fontMax: 40, fontMin: 32, colsMax: 2,
    minCells: 4, track: 1.2, gap: 1.3, align: "bottom",
  });
  if (vPlan) {
    ctx.fillStyle = P.ink;
    ctx.font = `400 ${vPlan.fp}px ${SERIF}`;
    paintVerticalPlan(ctx, vPlan, W - PAD);
  }

  /* ---- 落款章：一枚实心印章红圆，白字「笺」----
   *  圆心在 H − 218、半径 52，占 H − 270 .. H − 166；
   *  页脚的字基线 H − 84、字顶约 H − 110 —— 两者之间永远有 56px 的空。
   *  从前章固定在 H − 128（占到底 H − 76），页脚刚好写在那个区间里，
   *  章底就压在「2026 年 · … 存」这一行的字身上。 */
  const stampX = W - PAD - stampR;
  ctx.save();
  ctx.translate(stampX, stampCy);
  ctx.rotate(-10 * Math.PI / 180);
  ctx.beginPath(); ctx.arc(0, 0, stampR, 0, Math.PI * 2);
  ctx.fillStyle = P.seal; ctx.fill();
  ctx.fillStyle = P.cream;
  ctx.font = `500 44px ${SERIF}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("笺", 0, 2);
  ctx.restore();
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";

  /* ---- 页脚：谁的日子、哪天画的 ---- */
  ctx.fillStyle = P.soft;
  ctx.font = `400 26px ${SANS}`;
  ctx.fillText(`${yb.year} 年 · ${dayStr(Date.now())} 存`, PAD, H - 84);
  return cv;
}

/** 存年度长图。落盘那一段走 card.js 的 saveCanvasPng（全 App 唯一一份）：
 *  原生壳→Filesystem + 系统分享，浏览器→下载，失败一律开口，按钮一定会复原。
 *  这里只保留「这一张怎么画」和「画不出来怎么说」——那是这一张图自己的判断。 */
async function saveYearCard(yb, wr, c, btn) {
  const b = btn || $("#yearSave");
  let canvas = null;
  try {
    canvas = drawYearCard(yb, wr, c);
  } catch (e) {
    console.warn(e);
    toast("长图没画出来");
    return false;
  }
  return saveCanvasPng(canvas, `笺-这一年-${yb.year}.png`, b);
}

