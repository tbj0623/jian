/** 笺 · 笺谱（统计 / 热力图 / 成就 / 年度总结）
 *
 *  「笺谱」是这一版新增的一屏，回答的是「我用这个 App 的这些日子，到底留下了什么」。
 *  它不在底栏占位（一周看一次就够），从「今日」那一屏进。
 *
 *  五条规矩（写在这里，是因为下面每一段都在还它们的债）：
 *
 *  1. **每一个数字都能反推成分子和分母。** 屏上出现「在穿率 68%」时，
 *     下面必须有一句「37 件里 25 件穿过」。一个不能反推的百分比是假话。
 *  2. **数据少就说薄。** 少于 5 件、少于 5 天时那一块不摆结论，只摆「再记 N 件就有」。
 *     **0 不是结论**：一条都没有时说「还没有」，不说「0%」。
 *  3. **热力图只有一种排法。** 行 = 星期（周一起），列 = 周，五档深浅 + 今天带边框。
 *     照 flomo 那套做不是抄，是省掉一次「用户看不懂这个格子是什么」。它可以横向滚动，
 *     但**打开就必须看见今天**——所以默认滚到最右。
 *  4. **长图永远是白天的纸。** 它要被发出去、贴进群里、存进相册。跟着我这台手机的主题
 *     变黑就毁了（见 card.js 的 tokenLight）。数据薄到画不出来时宁可不生成，也不编。
 *  5. **不算第二遍。** 屏上出现的每一个数，都从 state 现算、只在这里算一次。
 *     落过盘的「进度」在删掉数据之后就是假话，所以 progress 一律现算（见 achievements.js）。
 */

/* ==================== 日期 ==================== */
/* 周一起的星期序号：0=周一 … 6=周日。JS 的 getDay 是 0=周日，这里换一次口径，
   而且**只换这一次**——全屏的日期对齐都读它（衣笺的穿着日历、味笺的这周网格也读）。 */
function weekIdx(ts) {
  const d = new Date(ts).getDay();
  return (d + 6) % 7;
}
/** 把某天往后挪 n 天（按日历日，不是 86400000 的倍数——夏令时那天会错一小时）。 */
function addDays(ts, n) {
  const d = new Date(ts);
  d.setDate(d.getDate() + n);
  return d.getTime();
}
/** 今天 0 点。热力图与日历的格子边界都从它推。 */
function startOfDay(ts) {
  const d = new Date(ts);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}
/** dayStr() 的反向：'2026.09.17' → 那天 0 点的时间戳。
 *  只用来算「点的是哪一天」，日期本身仍然只由 dayStr() 决定（唯一口径）。 */
function dayTs(k) {
  const m = String(k || "").split(".").map(Number);
  if (m.length !== 3 || m.some((x) => !Number.isFinite(x))) return NaN;
  return new Date(m[0], m[1] - 1, m[2]).getTime();
}

/* ==================== 热力图 ==================== */

/** 三档跨度。cell / gap 是**几何**，只有这一份定义：
 *  JS 把它们写进容器上的 --hc / --hg，CSS 只消费变量，不在两处各写一次格子尺寸
 *  （格子多宽同时决定月份刻度的位置，两份数一旦漂开，刻度就和列错开半格）。 */
const HEAT_RANGES = [
  { id: "w6", label: "近 6 周", weeks: 6, cell: 30, gap: 6 },
  { id: "h26", label: "近半年", weeks: 26, cell: 14, gap: 3 },
  { id: "y53", label: "近一年", weeks: 53, cell: 11, gap: 3 },
];
/** 当前看哪一档是**视图态**，不进 state、不进备份（和衣笺的页签同一个口径：
 *  重开回到「近半年」是对的，没人指望这个选择被记住）。 */
let heatRangeId = "h26";
/** 键盘选中的那一天（'YYYY.MM.DD'），也只在内存里。 */
let heatSel = "";

function heatRangeOf() {
  return HEAT_RANGES.find((r) => r.id === heatRangeId) || HEAT_RANGES[1];
}

/** 每日强度：0 = 没动作，1..4 = 有动作且分档。
 *  分档按「当天事件条数」四档，阈值是看历史分布定的（1 / 2-3 / 4-6 / 7+）。 */
function heatLevel(n) {
  if (!n) return 0;
  if (n === 1) return 1;
  if (n <= 3) return 2;
  if (n <= 6) return 3;
  return 4;
}

/** 热力图的原料：按天分桶 + 一列一周的网格。renderHeat 与测试都读它，
 *  不要在别处再按 dayStr 分组算一遍（那是第二份口径，热力图和「有记录天数」会开始对不上）。 */
function heatGrid() {
  const range = heatRangeOf();
  const byDay = {};
  (state.log || []).forEach((e) => { const k = dayStr(e.t); byDay[k] = (byDay[k] || 0) + 1; });
  const today = startOfDay(Date.now());
  // 从「今天所在的这一周」往回推 weeks 周，起点对齐到周一
  const start = addDays(today, -weekIdx(today) - (range.weeks - 1) * 7);
  const cols = [];
  let max = 0, activeN = 0;
  for (let w = 0; w < range.weeks; w++) {
    const days = [];
    for (let d = 0; d < 7; d++) {
      const ts = addDays(start, w * 7 + d);
      const k = dayStr(ts);
      const n = byDay[k] || 0;
      if (n) activeN++;
      if (n > max) max = n;
      days.push({ ts, k, n, lv: heatLevel(n), today: ts === today, future: ts > today });
    }
    cols.push({ days, monday: days[0].ts });
  }
  return { range, cols, byDay, max, activeN, today, start };
}

/** 月份刻度：哪一列开始了一个新的月份，就在那一列顶上标一个「N月」。
 *  间隔不到 3 列时**不标**——宁可少一个刻度，也不要两个月的字叠成一团。 */
function heatMonthMarks(grid) {
  const marks = [];
  let lastMonth = -1, lastCol = -99;
  grid.cols.forEach((c, i) => {
    const m = new Date(c.monday).getMonth();
    if (m === lastMonth) return;
    lastMonth = m;
    if (i - lastCol < 3) return;
    marks.push({ i, text: (m + 1) + "月" });
    lastCol = i;
  });
  return marks;
}

/** 画热力图。返回热力图的原料 { cols, byDay, activeN, max, range }，供页面上别处复用。 */
function renderHeat(host) {
  if (!host) return null;
  const g = heatGrid();
  const { range } = g;
  const pitch = range.cell + range.gap;
  const colsW = range.weeks * pitch - range.gap;
  const marks = heatMonthMarks(g);

  const markSpans = marks.map((m) => {
    // 最后一个刻度贴着右边缘时改右对齐，否则它会撑宽滚动区、平白多出一截空白
    const left = m.i * pitch + 30 > colsW ? Math.max(0, colsW - 30) : m.i * pitch;
    return `<span style="left:${left}px">${m.text}</span>`;
  }).join("");

  // 行 = 星期。只标一 / 三 / 五：七行全标在 11px 的格子上会糊成一条竖线。
  const dayLabels = ["一", "", "三", "", "五", "", ""]
    .map((t) => `<span>${t}</span>`).join("");

  const cols = g.cols.map((c) => `<div class="heat-week" role="row">${c.days.map((d) => {
    const lv = `l${d.lv}`;
    const cls = ["heat-cell", lv, d.today ? "today" : "", d.future ? "future" : ""].filter(Boolean).join(" ");
    const desc = `${d.k}${d.n ? "，" + d.n + " 笔记录" : "，没有记录"}${d.today ? "（今天）" : ""}`;
    return `<span class="${cls}" role="gridcell" data-heat="${d.k}" title="${desc}" aria-label="${desc}"></span>`;
  }).join("")}</div>`).join("");

  const rangeBtns = HEAT_RANGES.map((r) => `<button type="button" data-heat-range="${r.id}"
    aria-pressed="${r.id === range.id}">${r.label}</button>`).join("");

  // 计数行：一条都没有时不写「0 天有记录」——那正是这一屏不许说的话（0 不是结论）。
  const countText = g.activeN
    ? `${g.activeN} 天有记录`
    : "还没有记录，今天算第一天";

  host.innerHTML = `
    <div class="seg" id="heatRange" role="group" aria-label="热力图看多长">${rangeBtns}</div>
    <div class="heat-wrap" style="--hc:${range.cell}px;--hg:${range.gap}px">
      <div class="heat-days" aria-hidden="true">${dayLabels}</div>
      <div class="heat-scroll" id="heatScroll">
        <div class="heat-months" style="width:${colsW}px" aria-hidden="true">${markSpans}</div>
        <div class="heat" id="heatGrid" role="grid" tabindex="0"
             aria-label="最近 ${range.label}每天的动作热力图：${countText}。方向键选一天，回车或空格看那天的流水">${cols}</div>
      </div>
    </div>
    <div class="heat-legend">
      <span>少</span>${[0, 1, 2, 3, 4].map((l) => `<span class="heat-cell l${l}"></span>`).join("")}<span>多</span>
      <span class="heat-today-hint"><span class="heat-cell today"></span>今天</span>
      <span class="heat-count${g.activeN ? "" : " quiet"}">${countText}</span>
    </div>`;

  // 今天那一列默认要能看见：一直滚到最右（今天永远在最后一列里）。
  const scroll = $("#heatScroll", host);
  if (scroll) scroll.scrollLeft = scroll.scrollWidth;

  const grid = $("#heatGrid", host);
  if (grid) {
    grid.onclick = (e) => {
      const cell = e.target.closest("[data-heat]");
      if (cell) openDayPanel(cell.dataset.heat);
    };
    grid.onkeydown = (e) => onHeatKey(e, grid, g);
  }
  $$("#heatRange [data-heat-range]", host).forEach((b) => {
    b.onclick = () => {
      heatRangeId = b.dataset.heatRange;
      heatSel = "";
      renderHeat(host);
      toast(`${heatRangeOf().label}：${heatGrid().activeN} 天有记录`);
    };
  });
  return { cols: g.cols, byDay: g.byDay, activeN: g.activeN, max: g.max, range: g.range, start: g.start, today: g.today };
}

/** 热力图的键盘：左右挪一周、上下挪一天、回车看那天的流水。
 *  格子本身只有 11px，做成 371 个独立按钮是做不到 44px 触摸目标的——
 *  所以交互挂在**整块图**上（它远大于 44px），焦点在块上、方向键在里面走。 */
function onHeatKey(e, grid, g) {
  const horizontal = e.key === "ArrowLeft" || e.key === "ArrowRight";
  const vertical = e.key === "ArrowUp" || e.key === "ArrowDown";
  if (!horizontal && !vertical && e.key !== "Enter" && e.key !== " ") return;
  e.preventDefault();

  /* 还没有选中时，第一次按键**只负责选中今天**，不移动。
   *
   *  以前这里先把 heatSel 设成今天、紧接着又按方向走一步，于是：
   *  在年视图里按右 → 今天 + 7 天 = 明天 → 撞上「未来不动」→ 直接 return，
   *  paintHeatSel 一次都没被调用。结果是**键盘用户按了方向键，屏幕上什么都没有**：
   *  没有光标、没有高亮、也看不出该按哪。再按一次仍然什么都没有（heatSel 还是今天）。
   *  这条路径从加进来起就没被量过——stats_v06 里没有任何一条断言碰过方向键。
   *
   *  分两步之后：第一次按一定看得见东西（今天被选中并滚进视线），
   *  第二次起才开始走。走不动时也把落点重画一次，保证高亮与 heatSel 永远同真。
   */
  if (!heatSel) {
    heatSel = dayStr(g.today);
    paintHeatSel(grid);
    if (e.key === "Enter" || e.key === " ") openDayPanel(heatSel);
    return;
  }
  if (e.key === "Enter" || e.key === " ") {
    openDayPanel(heatSel);
    return;
  }
  const step = horizontal ? (e.key === "ArrowLeft" ? -7 : 7) : (e.key === "ArrowUp" ? -1 : 1);
  const next = addDays(dayTs(heatSel), step);
  if (next >= g.start && next <= g.today) heatSel = dayStr(next);
  // 走不动也要重画：不然「heatSel 已经变了、屏幕还停在上一格」会悄悄发生一次。
  paintHeatSel(grid);
}

/** 把选中态画出来并把它滚进视线。选中是给键盘用户的，不用透明度表达（会掉 AA）。 */
function paintHeatSel(grid) {
  if (!grid) return;
  $$("[data-heat]", grid).forEach((c) => c.classList.toggle("sel", c.dataset.heat === heatSel));
  const cur = $(`[data-heat="${heatSel}"]`, grid);
  if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest", inline: "nearest" });
}

/* ==================== 屏内小面板 ====================
   成就详情、某一天的流水都用它。**不许用 alert / confirm / toast 代替**：
   一个要读几行字的面板，塞进 3 秒就消失的提示条里等于没写。 */

let infoEl = null;
let infoBack = null;

function infoKey(e) {
  if (e.key === "Escape") { e.preventDefault(); closeInfoPanel(); }
}

function closeInfoPanel() {
  if (!infoEl) return;
  const back = infoBack;
  infoEl.remove();
  infoEl = null;
  infoBack = null;
  document.removeEventListener("keydown", infoKey, true);
  if (back) restoreFocus(back);
}

/** 打开一个面板：title 是面板标题（进无障碍名字），body 是已经拼好、已经 esc 过的 HTML。
 *  返回面板节点（测试要用）。 */
function openInfoPanel(title, body) {
  closeInfoPanel();
  infoBack = focusKey();
  const el = document.createElement("div");
  el.className = "stats-pop";
  el.innerHTML = `<div class="sp-card" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="sp-bar">
        <span class="sp-title serif">${esc(title)}</span>
        <button type="button" class="sp-close" aria-label="关掉">×</button>
      </div>
      <div class="sp-body">${body}</div>
    </div>`;
  document.body.appendChild(el);
  infoEl = el;
  el.onclick = (e) => { if (e.target === el) closeInfoPanel(); };
  const close = $(".sp-close", el);
  if (close) close.onclick = closeInfoPanel;
  document.addEventListener("keydown", infoKey, true);
  if (close) close.focus({ preventScroll: true });
  return el;
}

/** 某一天的流水。热力图的每一格点开就是这里——一格不点开的话，
 *  它就是一张好看的图，谁也不知道「这几笔」到底是哪几笔。 */
function openDayPanel(k) {
  const ts = dayTs(k);
  if (!Number.isFinite(ts)) return;
  const ev = eventsOn(k).slice().sort((a, b) => b.t - a.t);
  const d = new Date(ts);
  const wn = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  const isToday = k === dayStr(Date.now());
  const head = `${d.getMonth() + 1} 月 ${d.getDate()} 日 · 周${wn}${isToday ? " · 今天" : ""}`;
  const kindName = (k) => (typeof KIND_NAME !== "undefined" && KIND_NAME[k]) || k;
  const hhmm = (t) => `${String(new Date(t).getHours()).padStart(2, "0")}:${String(new Date(t).getMinutes()).padStart(2, "0")}`;
  const body = ev.length
    ? `<p class="tiny">${head} · ${ev.length} 笔</p>
       <div class="day-list">${ev.map((e) => `<div class="day-row">
         <span class="day-time">${hhmm(e.t)}</span>
         <span class="day-kind">${esc(kindName(e.kind))}</span>
         <span class="day-ref">${esc(e.ref || "—")}</span>
       </div>`).join("")}</div>
       <p class="tiny" style="margin-top:12px">热力图的每一格，就是这些笔记录加起来的。</p>`
    : `<p class="tiny">${head} · 没有记录</p>
       <p class="tiny" style="margin-top:10px">这天没在这里留下什么。热力图的每一格，
         都只数「真的做过一件事」的那几笔——打开 App 不算。</p>`;
  openInfoPanel(isToday ? "今天" : head.split(" · ")[0], body);
}

/* ==================== 衣柜 ==================== */

/** 在穿率：穿过的件数 / 柜里件数。没穿过的不算「在穿」——这正是要说的那件事。 */
/** 柜子里是不是还全是出厂那六件。
 *
 *  为什么统计要单独认这件事：种子柜子带穿着记录（9/4/12/2/3/15 次），那是为了让第一次
 *  打开的人一眼看出「常穿」和「久未穿」的区别——**它是说明书，不是用户的账**。
 *  柜子页一行小字标了「示例柜子」，但「笺谱」这一屏和年度长图都把它当真账算：
 *  全新安装进笺谱，实测写着「6 件里 6 件穿过，100% 在穿率」，而那六件的穿着次数
 *  一次都不是用户记的。更糟的是年度长图——那张 1080×1920 会被发进群里。
 *  这正是 README 那条「0 不是结论 / 数据薄就说薄」的反面：这里不是薄，是**不是他的**。
 *
 *  判据**不能只看 id**：测试与真实数据里都会出现 id 叫 w1/w2 的自建衣服
 *  （stats_v06 那两条「薄柜不摆百分比」就用了 w1/w2 造了两件）。只看 id 会把她
 *  自建的两件当成出厂六件，于是那两条断言当场假红——**判据比被判断的东西还粗**。
 *  所以这里认「id 是 w1..w6 且名字也还是出厂那六个名字」：换掉任意一件的名字
 *  就不再是示例柜（那正是 yi.js 教用户做的第一件事）。 */
const SEED_NAMES = { w1: "燕麦针织", w2: "白衬衫", w3: "深蓝阔腿", w4: "奶油半裙", w5: "驼大衣", w6: "白鞋" };
function closetIsSeed() {
  const wd = state.wardrobe || [];
  if (!wd.length || wd.length > 6) return false;
  return wd.every((w) => SEED_NAMES[w.id] === w.name);
}

function wearRate() {
  const wd = state.wardrobe || [];
  const worn = wd.filter((w) => w.worn > 0).length;
  return { total: wd.length, worn, pct: wd.length ? Math.round((worn / wd.length) * 100) : 0 };
}

/** 单次穿着成本（CPW）：价格 ÷ 穿过次数。
 *  没填价格的那件算不出来——**不拿 0 顶替**，返回 null 让界面说「没记价格」。
 *  穿过 0 次时 CPW 是无穷大，返回 Infinity，界面上说「还没穿过，算不出来」。 */
function cpw(w) {
  if (!w || w.price === null || w.price === undefined) return null;
  if (!w.worn) return Infinity;
  return w.price / w.worn;
}
/** 整个柜子的 CPW：总价 ÷ 总穿着次数。只有填过价格的那部分参与，且要在界面上说清参与了几件。 */
function closetCpw() {
  const wd = (state.wardrobe || []).filter((w) => w.price !== null && w.price !== undefined);
  const price = wd.reduce((s, w) => s + (w.price || 0), 0);
  const worn = wd.reduce((s, w) => s + (w.worn || 0), 0);
  return { pieces: wd.length, price, worn, cpw: worn ? price / worn : Infinity };
}

/** 柜子的四个来源数：件数、常穿、最久没穿、没穿过。统计页与「三种颜色」都读它。 */
function closetFacts() {
  const wd = state.wardrobe || [];
  const priced = wd.filter((w) => w.price !== null && w.price !== undefined);
  return {
    wd,
    total: wd.length,
    priced: priced.length,
    value: priced.reduce((s, w) => s + (w.price || 0), 0),
    wornTop: wd.filter((w) => w.worn > 0).sort((a, b) => b.worn - a.worn).slice(0, 3),
    never: wd.filter((w) => !w.worn),
    idle: wd.filter((w) => w.lastWorn).sort((a, b) => a.lastWorn - b.lastWorn).slice(0, 3),
  };
}

/* ==================== 三种颜色 ==================== */

/** 色相 12 桶的名字。分桶边界就是 30° 一格——写下这 12 个词是为了让
 *  「你 41% 的衣服是同一个色系」这句话里的「色系」有个具体的所指。 */
const HUE_NAMES = ["绯红", "赭橙", "姜黄", "草绿", "松绿", "青碧", "天青", "靛蓝", "蓝紫", "紫檀", "绛紫", "胭脂"];

/** 一个颜色落在哪一桶。返回 null 表示「没有色相」（白、灰、黑）——
 *  它们不是「第 13 个色系」，是真的没有色相，必须单独说，否则「你 60% 是同一个色系」
 *  会变成一句因为白衬衫多而形成的废话。
 *
 *  「白」的界线定在 l > 0.90 而不是 0.94：纸本身就是 #f4efe6（l≈0.933），
 *  柜子里最常见的米白 #f4f0ea、纯白 #f5f5f3 都在 0.93–0.96 之间。
 *  卡在 0.94 时 #f2f0ec（l=0.937）会被分进「赭橙」——实测发生过：
 *  6 件同色 + 4 件米白，屏上说出「你 83% 的衣服是同一个色系」，那是假话。
 *  饱和度 0.10 那一档管灰；亮度两头管白与黑。
 *
 *  色相换算**只读 engine.js 那一份**（Engine.rgbToHsl 就是它内部算色差用的同一个函数）。
 *  这里绝不另写一份 hex→hue：分桶边界一旦有两个真相，改一处另一处就开始悄悄漂。 */
function colorBucket(hex) {
  let hsl = null;
  try { hsl = Engine.rgbToHsl(Engine.hexToRgb(hex)); } catch (_) { return null; }
  if (!hsl) return null;
  const [h, s, l] = hsl;
  if (s < 0.10 || l > 0.90 || l < 0.08) {
    return { achromatic: true, name: l > 0.90 ? "白" : l < 0.08 ? "黑" : "灰" };
  }
  return { achromatic: false, idx: Math.floor(h / 30) % 12, name: HUE_NAMES[Math.floor(h / 30) % 12] };
}

/** 从柜子颜色按 hue 分 12 桶取 top3。返回 { total, buckets, achromatic, top, pct }。 */
function colorTones() {
  const wd = state.wardrobe || [];
  const counts = new Array(12).fill(0);
  let achromatic = 0;
  wd.forEach((w) => {
    const b = colorBucket(w.color);
    if (!b) return;
    if (b.achromatic) achromatic++;
    else counts[b.idx]++;
  });
  const buckets = counts.map((n, i) => ({ idx: i, name: HUE_NAMES[i], n })).filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n);
  const top = buckets.slice(0, 3);
  const chromatic = counts.reduce((a, b) => a + b, 0);
  const topN = top.length ? top[0].n : 0;
  return {
    total: wd.length, chromatic, achromatic, top,
    pct: wd.length ? Math.round((topN / wd.length) * 100) : 0,
    topN,
  };
}

/* ==================== 年度总账 ==================== */

/** 一串升序日子里最长的连续段（只折「连续」，不管这些日子属于哪一年）。
 *
 *  为什么不复用 state.js 的现成函数：`activeDays() / eventsBetween() / yearSpan()`
 *  给的是「哪些天有记录」与「哪一段属于这一年」——它们是这一段的原料，
 *  仓里没有把一组日子折成「最长连续」的那个口子。所以只在这里折最后一步，
 *  日的边界仍然只由 dayStr() 定（state.js 第 951 行起那条规矩）：
 *  相邻两天用 dayTs() + addDays() 按日历年走一步、再回 dayStr() 比字符串，
 *  **不**乘 86400000（夏令时那天不是整一天，乘出来的「昨天」会错一小时）。
 *  @param {string[]} keys 'YYYY.MM.DD'，升序、已去重
 *  @returns {number} 最长连续天数；一天都没有时是 0——调用方负责不把 0 当结论印出去。 */
function longestRun(keys) {
  let best = 0, run = 0, prev = "";
  (keys || []).forEach((k) => {
    run = prev && dayStr(addDays(dayTs(prev), 1)) === k ? run + 1 : 1;
    if (run > best) best = run;
    prev = k;
  });
  return best;
}

/** 年度总账：一年里每一类各做了多少、最常穿的那件、最常做的菜、
 *  这一年之内最长的连续天数。年度总结长图与「这一年」那一屏都读它。 */
function yearBook(year) {
  const span = yearSpan(year);
  const ev = eventsBetween(span.from, span.to);
  const kinds = countByKind(ev);
  const dayKeys = ev.map((e) => dayStr(e.t));
  const days = new Set(dayKeys);
  // 这一年之内最长的连续：从**这一年的流水**里现算，不读 state.streak.best。
  // best 是全历史的最高纪录（而且它是**落过盘**的派生数，删掉旧日志也不会回退），
  // 拿它当「今年」的结论，等于把去年连过的 30 天印在今年这张纸上——
  // 年度长图会被发出去，收到的人只会以为今年真的连了 30 天。
  // 没有记录时是 0，下面的 renderYear / yearText 负责换成「还没有连着的日子」。
  const best = longestRun([...days].sort());
  // 最常穿：log 里 wear 的 ref 计数最多的那个 id
  const wearRef = {};
  ev.filter((e) => e.kind === "wear").forEach((e) => { if (e.ref) wearRef[e.ref] = (wearRef[e.ref] || 0) + 1; });
  const topWearId = Object.keys(wearRef).sort((a, b) => wearRef[b] - wearRef[a])[0];
  const topWear = topWearId ? (state.wardrobe || []).find((w) => w.id === topWearId) : null;
  const cookRef = {};
  ev.filter((e) => e.kind === "cook").forEach((e) => { if (e.ref) cookRef[e.ref] = (cookRef[e.ref] || 0) + 1; });
  const topCook = Object.keys(cookRef).sort((a, b) => cookRef[b] - cookRef[a])[0] || "";
  // 按月分桶（12 个数），年度长图要画成一条曲线
  const months = new Array(12).fill(0);
  ev.forEach((e) => { months[new Date(e.t).getMonth()]++; });
  // 第一次用笺：写进档案的那一天；老备份里没有就退回日志里最早的那一笔
  const logFirst = (state.log || []).length ? (state.log || [])[0].t : 0;
  const since = (state.profile && state.profile.since) || logFirst || 0;
  return {
    year: span.year, events: ev.length, kinds, days: days.size,
    months, max: Math.max(...months, 0),
    topWear, topWearN: topWearId ? wearRef[topWearId] : 0,
    topCook, topCookN: topCook ? cookRef[topCook] : 0,
    best,
    since, logFirst,
  };
}

/** 够不够画一年：少于 10 天就说薄（不够的日子画出来的曲线是假的）。 */
function yearThin(b) {
  return !b || b.days < 10;
}
/** 还差几天才画得出：屏上、面板里、拒绝生成时说的必须是同一个数。 */
function yearShort(b) {
  return Math.max(0, 10 - ((b && b.days) || 0));
}

/* ==================== 统计块 ==================== */

/** 一枚统计格：一个大数字 + 一个单位 + 一行说明。全屏只用这一个拼法。 */
function statCell(n, unit, label) {
  return `<div class="stat"><b>${n}<small>${unit}</small></b><span>${esc(label)}</span></div>`;
}

/** 一块统计的外壳：标题 + 格子 + 「这些数是怎么来的」。
 *  note 是**必须**的：没有反推句的百分比在这个屏上不许出现。 */
function statBlock(mark, title, cells, note) {
  return `<section class="stat-block">
      <h2 class="sb-head"><span class="sb-mark serif" aria-hidden="true">${esc(mark)}</span>${esc(title)}</h2>
      ${cells.length ? `<div class="stat-grid${cells.length === 3 ? " three" : ""}">${cells.join("")}</div>` : ""}
      ${note ? `<p class="sb-note">${note}</p>` : ""}
    </section>`;
}

/** 一块「还没有东西」的统计：说下一步做什么，不说 0。 */
function thinBlock(mark, title, say) {
  return `<section class="stat-block thin">
      <h2 class="sb-head"><span class="sb-mark serif" aria-hidden="true">${esc(mark)}</span>${esc(title)}</h2>
      <p class="sb-note">${say}</p>
    </section>`;
}

/* ---------- 四块：衣 / 味 / 言 / 时 ---------- */

function closetBlock() {
  const f = closetFacts();
  const wr = wearRate();
  const c = closetCpw();
  if (!f.total) {
    return thinBlock("衣", "衣柜", "柜子还空着。过一张笺、点一下「进柜子」，这里才会开始有话说。");
  }
  // 还全是出厂那六件：一个数都不摆。那六件的穿着次数不是用户记的，算出来的在穿率、
  // 单次成本、最久没穿全是别人的账——说「先换成自己的」比说「100% 在穿率」诚实。
  if (closetIsSeed()) {
    return thinBlock("衣", "衣柜",
      "柜里还是那六件示例衣服（它们带着示例的穿着记录，是为了让你一眼看出「常穿」和「久未穿」长什么样）。"
      + "换成自己的第一件之后，这里才开始算你自己的账。");
  }
  const cells = [statCell(wr.worn, `/ ${wr.total} 件`, "穿过")];
  // 少于 5 件时不摆百分比：3 件里 2 件穿过 = 67%，这个数没有说服力，也不该被截图发出去。
  if (wr.total >= 5) cells.push(statCell(wr.pct, "%", "在穿率"));
  if (f.priced) cells.push(statCell(`¥${Math.round(f.value)}`, "", `${f.priced} 件记了价`));

  const bits = [];
  if (wr.total >= 5) {
    bits.push(`${wr.total} 件里 ${wr.worn} 件穿过，${wr.total - wr.worn} 件一次没穿。`
      + `在穿率 = 穿过的件数 ÷ 柜里件数。`);
  } else {
    bits.push(`柜里只有 ${wr.total} 件（还差 ${5 - wr.total} 件到 5 件）——先攒几件，`
      + `这个比例才说明得了什么。3 件里 2 件穿过不是结论，是巧合。`);
  }
  if (f.priced) {
    if (Number.isFinite(c.cpw)) {
      bits.push(`单次穿着成本 ¥${c.cpw.toFixed(1)}：${f.priced} 件记了价，共 ¥${Math.round(c.price)}，穿过 ${c.worn} 次。`);
    } else {
      bits.push(`${f.priced} 件记了价、共 ¥${Math.round(c.price)}，但一次都还没记过穿着——单次成本还算不出来。`);
    }
  } else {
    bits.push("还没给任何一件记价格。记了才看得到「这件每穿一次值几块钱」。");
  }
  if (f.never.length) bits.push(`${f.never.length} 件一次没穿过。`);

  // 常穿 / 最久没穿：各取前三。data 不够就不摆那一行。
  const extra = [];
  if (f.wornTop.length) {
    extra.push(`<p class="sb-line">最常穿：${f.wornTop.map((w) => `${esc(w.name)} ${w.worn} 次`).join("、")}</p>`);
  }
  if (f.idle.length) {
    const days = (w) => Math.floor((Date.now() - w.lastWorn) / 86400000);
    extra.push(`<p class="sb-line">最久没穿：${f.idle.map((w) => `${esc(w.name)} ${days(w)} 天`).join("、")}</p>`);
  }
  return statBlock("衣", "衣柜", cells, bits.join("") ) + (extra.length ? `<div class="sb-extra">${extra.join("")}</div>` : "");
}

function weiBlock() {
  const log = state.cookLog || [];
  if (!log.length) {
    return thinBlock("味", "味笺", "还没记过「今天做了这道」。做一顿、记一笔，这里会有你的口味。");
  }
  const names = new Set(log.map((c) => c.name));
  const byName = {};
  log.forEach((c) => { byName[c.name] = (byName[c.name] || 0) + 1; });
  const topName = Object.keys(byName).sort((a, b) => byName[b] - byName[a])[0];
  const cells = [
    statCell(names.size, "道", "做过的菜"),
    statCell(log.length, "次", "下厨记录"),
  ];
  const bits = [];
  if (names.size >= 5) {
    bits.push(`${log.length} 次下厨，做过 ${names.size} 道不同的菜。`);
  } else {
    bits.push(`才做过 ${names.size} 道菜（还差 ${5 - names.size} 道到 5 道）——`
      + `现在说「你最常做什么」还太早，多做几道，口味才看得出来。`);
  }
  if (topName) bits.push(`做得最多的是「${esc(topName)}」，${byName[topName]} 次。`);
  return statBlock("味", "味笺", cells, bits.join(""));
}

function yanBlock() {
  const all = state.yanCards || [];
  if (!all.length) {
    return thinBlock("言", "言笺", "还没有言笺。把一段聊天贴进言笺、捞成笺，这里会说办完率。");
  }
  const done = all.filter((x) => x.done).length;
  const pct = Math.round((done / all.length) * 100);
  const cells = [statCell(all.length, "条", "捞下来的")];
  // 一条都没勾掉时不摆 0%：那是一个 0 当作结论，而这个屏不许这么说话。
  if (done > 0) cells.push(statCell(pct, "%", "办完率"));
  else cells.push(statCell("还没勾掉一条", "", "办完率"));

  const bits = [];
  bits.push(done > 0
    ? `${all.length} 条里 ${done} 条办完了，${all.length - done} 条还挂着。办完率 = 办完的条数 ÷ 捞下来的条数。`
    : `${all.length} 条都还挂着，一条也没勾掉。勾掉一条，这里就有办了完率。`);
  // 最常说的人名：who / speaker 两处都算（言笺里那句「小红：明天开会」两种都存得到）
  const people = {};
  all.forEach((c) => { [c.who, c.speaker].filter(Boolean).forEach((n) => { people[n] = (people[n] || 0) + 1; }); });
  const topPerson = Object.keys(people).sort((a, b) => people[b] - people[a])[0];
  if (topPerson) bits.push(`最常提到「${esc(topPerson)}」，${people[topPerson]} 条。`);
  return statBlock("言", "言笺", cells, bits.join(""));
}

function timeBlock() {
  const days = activeDays().length;
  const now = new Date();
  const monthFrom = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const monthTo = new Date(now.getFullYear(), now.getMonth() + 1, 1).getTime();
  const monthN = eventsBetween(monthFrom, monthTo).length;
  if (!days) {
    return thinBlock("时", "时间", "一笔记录都还没有。今天做一件小事，这里就会记下第一格。"
      + "五年后再看，这一格就是起点。");
  }
  const cells = [
    statCell(state.streak.days || 0, "天", "连续"),
    statCell(state.streak.best || 0, "天", "最长连续"),
    statCell(days, "天", "有记录"),
  ];
  const bits = [`${days} 天有记录，累计 ${(state.log || []).length} 笔。`];
  if (monthN) bits.push(`这个月 ${monthN} 笔。`);
  else bits.push(`这个月还一笔都没记——现在补一件也来得及。`);
  if (days < 5) bits.push(`（才 ${days} 天，还差 ${5 - days} 天到 5 天，连续天数这个数才开始有意思。）`);
  return statBlock("时", "时间", cells, bits.join(""));
}

/* ---------- 三种颜色 ---------- */

function colorBlock() {
  const t = colorTones();
  if (!t.total) {
    return thinBlock("色", "你的三种颜色", "柜子还空着，颜色说不出来。");
  }
  if (!t.chromatic && !t.achromatic) {
    return thinBlock("色", "你的三种颜色", "柜里的颜色还没读出来。给每件挑个颜色，这里就画得出你的色系。");
  }
  const swatch = (b) => `<div class="tone-item">
      <span class="tone-dot" style="background:${hueHex(b.idx)}" aria-hidden="true"></span>
      <b class="serif">${esc(b.name)}</b>
      <span class="tiny">${b.n} 件</span>
    </div>`;
  const top = t.top.length ? t.top.map(swatch).join("") : "";
  const bits = [];
  if (t.topN && t.top.length) {
    bits.push(`你 ${t.pct}% 的衣服是同一个色系（${esc(t.top[0].name)}，${t.topN} 件）。`);
  }
  if (t.achromatic) {
    bits.push(`另有 ${t.achromatic} 件是白/灰/黑这类没有色相的——它们不算「同色系」，`
      + `但一件白衬衫配什么都行，这大概也是你把它留在柜子里的原因。`);
  }
  if (t.chromatic >= 5 && t.top.length >= 3) {
    bits.push(`按色相分 12 档，前三个是上面这些。`);
  }
  return `<section class="stat-block">
      <h2 class="sb-head"><span class="sb-mark serif" aria-hidden="true">色</span>你的三种颜色</h2>
      <div class="tone-row">${top || `<p class="tiny">没有带色相的衣服。</p>`}</div>
      <p class="sb-note">${bits.join("")}</p>
    </section>`;
}
/** 色系那一枚色点：用 hue 反推出一个饱和度适中的颜色，仅用于显示。
 *  不写死色值表（12 个 hex 是 12 处将来会漂的东西），用 HSL 现算。 */
function hueHex(idx) {
  const h = (idx * 30 + 15) % 360;
  return `hsl(${h} 34% 58%)`;
}

/* ==================== 笺谱那一屏 ==================== */

function renderPu() {
  // 兜底：导入备份 / 换机之后，章数要对得上（正常路径由 logEvent 触发 checkBadges）
  if (typeof checkBadges === "function") { try { checkBadges(); } catch (_) {} }

  const heatHost = $("#puHeat");
  const heat = renderHeat(heatHost);
  const body = $("#puBody");
  if (!body) return;

  const blocks = [];
  blocks.push(timeBlock());
  blocks.push(closetBlock());
  blocks.push(weiBlock());
  blocks.push(yanBlock());
  blocks.push(colorBlock());

  const badges = (state.badges || []).slice().sort((a, b) => b.t - a.t);
  const defs = typeof BADGE_DEFS !== "undefined" ? BADGE_DEFS : [];
  const last = badges[0] ? defs.find((d) => d.id === badges[0].id) : null;
  const badgeSub = badges.length
    ? `已攒 ${badges.length} / ${defs.length || "?"} 枚`
      + (last ? ` · 最近是「${esc(last.name)}」` : "")
    : `一枚都还没有 · 点开看看怎么攒`;

  blocks.push(`
    <p class="tiny pu-more">往下看</p>
    <div class="list">
      <button class="rowbtn" data-pulink="badges"><span class="grow"><b>章</b><span class="sub">${badgeSub}</span></span></button>
      <button class="rowbtn" data-pulink="year"><span class="grow"><b>这一年</b><span class="sub">画成一张能发出去的长图</span></span></button>
      <button class="rowbtn" data-pulink="search"><span class="grow"><b>找东西</b><span class="sub">一次搜遍柜子、言笺、菜谱、摘录</span></span></button>
    </div>`);

  body.innerHTML = blocks.join("");
  $$("#puBody [data-pulink]").forEach((b) => { b.onclick = () => show(b.dataset.pulink); });
  return heat;
}

/* ==================== 成就 ==================== */

/** 勋章定义在 achievements.js；这一屏只负责画。
 *  每一枚必须**说得出是怎么来的**——点开一枚没解锁的章，要看到「还差 3 次」。 */
function renderBadges() {
  const grid = $("#badgeGrid");
  const note = $("#badgeNote");
  if (!grid) return;
  // 兜底：导入备份 / 换机之后，章数要对得上（正常路径由 logEvent 触发）
  if (typeof checkBadges === "function") { try { checkBadges(); } catch (_) {} }

  const got = new Map((state.badges || []).map((b) => [b.id, b.t]));
  const all = typeof BADGES === "function" ? BADGES() : [];
  const unlocked = all.filter((b) => got.has(b.id)).length;
  if (note) note.textContent = `已攒 ${unlocked} / ${all.length} 枚。点一枚看看它怎么来。`;

  const NEW_MS = 7 * 86400000;
  const progs = new Map(all.map((b) => [b.id, typeof badgeProgress === "function" ? badgeProgress(b) : null]));
  const recent = (state.badges || []).slice().sort((a, b) => b.t - a.t).slice(0, 3)
    .map((x) => ({ rec: x, def: all.find((d) => d.id === x.id) })).filter((x) => x.def);

  const recentHtml = recent.length ? `<div class="badge-recent">
      <p class="tiny">最近解锁</p>
      <div class="br-row">${recent.map(({ rec, def }) => `<span class="br-item${Date.now() - rec.t < NEW_MS ? " is-new" : ""}">
          <b class="serif" aria-hidden="true">${esc(def.mark)}</b>
          <span>${esc(def.name)}</span>
          <span class="tiny">${dayStr(rec.t)}</span>
        </span>`).join("")}
      </div>
    </div>` : "";

  const groups = (typeof BADGE_GROUPS !== "undefined" ? BADGE_GROUPS : ["衣", "味", "言", "时"]);
  const groupHtml = groups.map((g) => {
    const list = all.filter((b) => b.group === g);
    if (!list.length) return "";
    const on = list.filter((b) => got.has(b.id)).length;
    const cells = list.map((b) => {
      const when = got.get(b.id);
      const isOn = !!when;
      const p = progs.get(b.id);
      const fresh = isOn && Date.now() - when < NEW_MS;
      const pct = p && p.need ? Math.max(0, Math.min(100, Math.round((Math.min(p.now, p.need) / p.need) * 100))) : 0;
      const label = isOn
        ? `${b.name}，已解锁，${dayStr(when)}`
        : `${b.name}，还没解锁${p && p.hint ? "，" + p.hint : ""}`;
      return `<button type="button" class="badge ${isOn ? "unlocked" : "locked"}${fresh ? " is-new" : ""}"
          data-badge="${esc(b.id)}" aria-label="${esc(label)}">
          <span class="bg-mark" aria-hidden="true">${esc(b.mark)}</span>
          <span class="bg-name">${esc(b.name)}</span>
          ${isOn ? "" : `<span class="bg-prog" aria-hidden="true"><i style="width:${pct}%"></i></span>`}
        </button>`;
    }).join("");
    return `<div class="badge-group"><span class="bgg-name serif">${esc(g)}</span>
        <span class="tiny">${on} / ${list.length}</span></div>${cells}`;
  }).join("");

  grid.innerHTML = recentHtml + groupHtml;
  $$("#badgeGrid [data-badge]").forEach((el) => {
    el.onclick = () => {
      const b = all.find((x) => x.id === el.dataset.badge);
      if (b) openBadgePanel(b, got.get(b.id), progs.get(b.id));
    };
  });
}

/** 一枚章的详情面板：名字、怎么来的、解锁日期，或者「还差多少」的进度条。 */
function openBadgePanel(b, when, prog) {
  const n = (state.badges || []).length;
  const idx = (state.badges || []).findIndex((x) => x.id === b.id);
  const p = prog || (typeof badgeProgress === "function" ? badgeProgress(b) : { ok: false, now: 0, need: 1, hint: "还算不出来" });
  const pct = p.need ? Math.max(0, Math.min(100, Math.round((Math.min(p.now, p.need) / p.need) * 100))) : 0;
  const body = `
    <div class="bp-head">
      <span class="bp-mark serif ${when ? "on" : ""}" aria-hidden="true">${esc(b.mark)}</span>
      <div class="bp-main">
        <p class="bp-name serif">${esc(b.name)}</p>
        <p class="tiny">${esc(b.how)}</p>
      </div>
    </div>
    ${when
      ? `<p class="bp-when">${dayStr(when)} 得的。第 ${idx + 1} 枚 / 共 ${n} 枚。</p>
         <p class="tiny">章没有声音也没有弹窗——它只在你回来翻的时候在这里。</p>`
      : `<div class="bp-prog">
           <div class="meter"><i style="width:${pct}%"></i></div>
           <p class="bp-hint">${esc(p.hint || "还没开始")}</p>
           <p class="tiny">已经 ${p.now} / ${p.need}。</p>
         </div>
         <p class="tiny">章只在「真的做到」那一刻落下，不会因为你点开这一页就先给你。</p>`}`;
  openInfoPanel(when ? "已解锁的章" : "还没解锁的章", body);
}

/* ==================== 年度总结 ==================== */

function renderYear() {
  const body = $("#yearBody");
  if (!body) return;
  if (typeof checkBadges === "function") { try { checkBadges(); } catch (_) {} }
  const yb = yearBook();
  // 种子柜子不参与年度账：那六件的穿着次数是示例，不是用户记的。
  // 年度长图会把这几个数画成 1080×1920 发出去——「柜里 6 件，6 件穿过」发到群里，
  // 收到的人不会知道那是出厂示例。传一个空的 wr，屏上和长图一起闭嘴。
  const wr = closetIsSeed() ? { total: 0, worn: 0, pct: 0 } : wearRate();
  const c = closetCpw();
  const thin = yearThin(yb);
  const short = yearShort(yb);

  /* 12 个月的柱：最高的那根实心，其余淡；下面标 1 / 6 / 12 月。
     用 CSS 柱而不是 canvas：每根柱都能带 aria-label，读屏器念得出来。 */
  const maxM = Math.max(1, ...yb.months);
  const bars = yb.months.map((n, i) => `<div class="ym-col" aria-label="${i + 1} 月 ${n} 笔">
      <span class="ym-num">${n || ""}</span>
      <span class="ym-bar${n === maxM && n > 0 ? " top" : ""}" style="height:${Math.max(n ? 3 : 1, Math.round((n / maxM) * 100))}%"></span>
      <span class="ym-label">${i + 1}</span>
    </div>`).join("");

  /* 往年今日：同一个月日、但不是今年的那些笔。零成本的回访钩子，今年没有就不摆。 */
  const md = dayStr(Date.now()).slice(5);
  const yNow = dayStr(Date.now()).slice(0, 4);
  const pastHits = (state.log || []).filter((e) => {
    const k = dayStr(e.t);
    return k.slice(5) === md && k.slice(0, 4) !== yNow;
  });
  const pastHtml = pastHits.length
    ? `<details class="drawer"><summary>往年今日 · ${pastHits.length} 笔</summary>
        <div class="drawer-body">${pastHits.slice(-8).reverse().map((e) => {
          const kn = (typeof KIND_NAME !== "undefined" && KIND_NAME[e.kind]) || e.kind;
          return `<p class="sb-line">${dayStr(e.t)} · ${esc(kn)}${e.ref ? " · " + esc(e.ref) : ""}</p>`;
        }).join("")}</div></details>`
    : "";

  body.innerHTML = `
    <article class="report year-report">
      <p class="meta">JIAN · ${yb.year}</p>
      <h1 class="serif year-h1">这一年</h1>
      ${thin
        ? `<p class="quote serif">这一年才记了 ${yb.days} 天，还画不出一张像样的账。</p>
           <p class="tiny">再记 <b>${short}</b> 天，这张纸就立得住了。它不会替你编数字——
             10 天是这张图的下限，少于 10 天的曲线是假的。</p>`
        : `<p class="quote serif">你在笺上留下了 ${yb.events} 笔记录，分布在 ${yb.days} 个日子里。</p>`}
      <div class="rule"></div>
      ${thin ? "" : `<div class="year-months" role="img" aria-label="${yb.year} 年每个月记了多少笔">${bars}</div>
        <p class="tiny year-axis">1 月 — 12 月 · 最高的是 ${yb.months.indexOf(maxM) + 1} 月（${maxM} 笔）</p>
        <div class="rule"></div>`}
      <div class="stat-grid three">
        ${statCell(yb.kinds.wear || 0, "次", "记了穿搭")}
        ${statCell(yb.kinds.cook || 0, "次", "下厨")}
        ${statCell(yb.kinds.catch || 0, "张", "捞成笺")}
      </div>
      <p class="sb-note">${yb.topWear
        ? `穿得最多的是「${esc(yb.topWear.name)}」，${yb.topWearN} 次。`
        : (yb.kinds.wear
          // 有穿着记录、但对不上柜里任何一件：那件已经从柜里去掉了（或备份里只带来了日志）。
          // 这时候说「还没记过穿搭」是假话——这一版里「没数据」与「数据对不上」必须分开说。
          ? `这一年记了 ${yb.kinds.wear} 次穿搭，但那些衣服已经不在柜里了，点不出是哪一件。`
          : "这一年还没记过穿搭。")}</p>
      ${yb.topCook ? `<p class="sb-note">做得最多的是「${esc(yb.topCook)}」，${yb.topCookN} 次。</p>` : ""}
      ${wr.total ? `<p class="sb-note">柜里 ${wr.total} 件，${wr.worn} 件穿过${wr.total >= 5 ? `（在穿率 ${wr.pct}%）` : ""}。</p>` : ""}
      ${Number.isFinite(c.cpw) ? `<p class="sb-note">单次穿着成本 ¥${c.cpw.toFixed(1)}（${c.pieces} 件记了价）。</p>` : ""}
      <p class="sb-note">${yb.days
        // 这一年的流水一天都没有时不要印「0 天」：0 在这里不是结论，是「还没有」。
        // （yearBook().best 现在只数今年，全历史那个最高纪录在「时间」那一块，
        //   它读的仍是 state.streak.best——那里问的就是「有史以来」。）
        ? `今年最长连续 ${yb.best} 天。`
        : `今年还没有连着的日子——今天记上一笔，这里就开始数了。`}
        第一次在笺上留字是 ${yb.since ? dayStr(yb.since) : "还没记"}。</p>
      ${pastHtml}
      <p class="signoff"><span>${yb.year} · 笺</span></p>
    </article>
    <div class="row">
      <button class="btn ghost" id="yearCopy">复制这段字</button>
      <button class="btn" id="yearSave">存成一张长图</button>
    </div>
    <p class="tiny year-foot">长图是 1080 × 1920 的一张浅纸——发给谁看都还是这张纸，不会跟着你手机的深色模式变黑。</p>`;

  const copyBtn = $("#yearCopy");
  if (copyBtn) copyBtn.onclick = () => { copy(yearText(yb, wr), "已复制这一年的账"); };
  const saveBtn = $("#yearSave");
  if (saveBtn) {
    if (thin) saveBtn.setAttribute("aria-disabled", "true");
    saveBtn.onclick = () => {
      // 挡下时必须**开口**：aria-disabled 的钮按得下去，说不出理由就等于回到静默。
      if (thin) { toast(`这张账还太薄：再记 ${short} 天就能存图`); return; }
      if (typeof saveYearCard !== "function") { toast("长图还没准备好"); return; }
      saveYearCard(yb, wr, c, saveBtn);
    };
  }
}

/** 年度总结的纯文字版：复制出去、存长图都用它，两处不许各写一份。 */
function yearText(yb, wr) {
  const bits = [`${yb.year} 年，我在笺上留下了 ${yb.events} 笔记录，分布在 ${yb.days} 个日子里。`];
  if (yb.kinds.wear) bits.push(`记了 ${yb.kinds.wear} 次穿搭。`);
  if (yb.topWear) bits.push(`穿得最多的是「${yb.topWear.name}」，${yb.topWearN} 次。`);
  if (yb.kinds.cook) bits.push(`下厨 ${yb.kinds.cook} 次。`);
  if (yb.topCook) bits.push(`做得最多的是「${yb.topCook}」。`);
  if (yb.kinds.catch) bits.push(`捞了 ${yb.kinds.catch} 张言笺。`);
  if (wr && wr.total) bits.push(`柜里 ${wr.total} 件，${wr.worn} 件穿过。`);
  // 与屏上同一句口径：今年一天都没有时不写「最长连续 0 天」。
  if (yb.days) bits.push(`今年最长连续 ${yb.best} 天。`);
  else bits.push(`今年还没有连着的日子。`);
  if (yb.since) bits.push(`第一次在笺上留字是 ${dayStr(yb.since)}。`);
  return bits.join("");
}
