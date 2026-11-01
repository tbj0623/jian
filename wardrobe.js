/** 笺 · 衣笺的「柜子之外」
 *
 *  yi.js 管的是「过笺」（拿一件想买的比柜子）；这一份管的是衣柜本身：
 *  单品档案页、搭配册、愿望单与冷静期、衣柜统计。
 *
 *  为什么拆出来：yi.js 已经 800 多行，再加四块屏会到 2000 行，没人敢动。
 *  这两个文件共用的只有 state 与几个小工具（swatchEl / compress），都从那边读。
 *
 *  v0.6.0 这一版的三条口径（写在这里，因为它们决定了下面每一屏怎么说话）：
 *
 *  1. **算不出来就说算不出来。** 单次穿着成本 = 价格 ÷ 穿过次数，缺任何一项都不给结论，
 *     也不印 0 或 Infinity 冒充数字（假数字比空白更坏，用户会拿它做决定）。
 *  2. **数据薄就说薄。** 柜里不到 5 件、搭配不到两套、穿着记录不到几笔时，
 *     那一块只摆「再记几笔就有」，不把比例当结论。
 *  3. **每个动作都留得下痕迹，也撤得回。** 记穿与「穿这套」都进 state.log
 *     （热力图 / 成就 / 年度总结读它），破坏性的操作一律带一次反悔。
 */

/* ==================== 小工具：都从既有的那一份读，不另起一套 ==================== */

/** 今天 0 点。日界口径全仓只有 dayStr() 一处（state.js），这里只借它判「哪一天」。 */
const yiToday = () => startOfDay(Date.now());

/** 某件衣服的穿着日历（去重后的时间戳数组）。老数据没有 wearDays 字段。 */
const wearDaysOf = (w) => (Array.isArray(w && w.wearDays) ? w.wearDays : []);

/** 这一件「哪几天穿过」的集合。**wearDays ∪ {上次穿那一天}**：
 *  「今天穿了」这条主路走的是 yi.js 的 applyWear（它只改 worn / lastWorn），
 *  日历若只认 wearDays，刚记的那一天在日历上就是空的——同一屏两个说法。
 *  上次穿那一天是**事实**（它确实穿过），所以把它并进来，而不是回头去编日期。 */
function wearDaySet(w) {
  const set = new Set(wearDaysOf(w).map((t) => dayStr(t)));
  if (w && w.lastWorn && (w.worn || 0) > 0) set.add(dayStr(w.lastWorn));
  return set;
}
function wearsOn(w, ts) { return wearDaySet(w).has(dayStr(ts)); }

/** 日历上有几个点 vs 账上记了几次：两个数可能不等（早先只记次数、没记日子）。
 *  不等时界面上要说出这件事，不能拿其中一个冒充另一个。 */
function wearDayGap(w) {
  const n = wearDaySet(w).size;
  const worn = w.worn || 0;
  return { days: n, worn, gap: Math.max(0, worn - n) };
}

/* ==================== 单品档案 ==================== */
let itemSel = null;        // 当前打开的单品 id
let itemCalMonth = 0;      // 穿着日历翻到第几个月：0 = 这个月，-1 = 上个月
let itemCalOpen = false;   // 日历是否展开（默认收起：它不是这一页的主角）

function openItem(id) {
  itemSel = id;
  itemCalMonth = 0;
  itemCalOpen = false;
  show("yi-item");
}

/** 单次成本的几种「算不出来」要分开说，因为它们各自有各自的下一步：
 *  没价格 → 去填价格；没穿过 → 去记穿；0 元 → 是礼物，不谈成本。 */
function cpwLine(w) {
  const c = cpw(w);
  if (c === null) return "还没记价格。记了才看得到「这件每穿一次值几块钱」。";
  if (c === Infinity) return `记了 ¥${w.price.toFixed(0)}，但一次还没穿过——现在还看不出值不值。`;
  if (c === 0) return "0 元记的（礼物或赠品），谈不上单次成本。";
  return `¥${w.price.toFixed(0)} ÷ ${w.worn} 次 = 每次 ¥${c.toFixed(1)}。`;
}

/** 「这件值不值」一句话。阈值是产品判断，不是统计结论，所以只在算得出时开口。 */
function cpwVerdict(w) {
  const c = cpw(w);
  if (c === null) return "还没记价格，这一页先算不出值不值。";
  if (c === Infinity) return "还看不出值不值——先穿它一次。";
  if (c === 0) return "没花过钱，穿一次就赚一次。";
  if (c < 5) return `一次 ¥${c.toFixed(1)}，这件穿回本了。`;
  if (c <= 100) return `一次 ¥${c.toFixed(1)}，是一件正常衣服的样子。`;
  return `一次 ¥${c.toFixed(1)}，还没穿回本。多穿它，或者下一件别这么买。`;
}

/** 档案里还缺哪几样。缺着不影响过笺（判定只吃品类/颜色/季节），但缺着就答不了「值不值」。 */
function itemMissing(w) {
  const miss = [];
  if (w.price === null || w.price === undefined) miss.push("价格");
  if (!w.boughtAt) miss.push("购入日");
  if (!(w.occasions || []).length) miss.push("场合");
  if (!w.brand) miss.push("品牌");
  return miss;
}

/** 「买了多久」那一句：购入日是事实，就不该只躺在输入框里。 */
function boughtLine(w) {
  if (!w.boughtAt) return "记了购入日，这里会说这件买了多久。";
  const days = Math.max(0, Math.floor((Date.now() - w.boughtAt) / DAY));
  if (days < 31) return `买了 ${days || "不到 1"} 天。`;
  if (days < 365) return `买了 ${Math.floor(days / 30)} 个月。`;
  return `买了 ${Math.floor(days / 365)} 年多。`;
}

/** 单品档案页。它是衣柜的「一页档案」，不是一张表单：
 *  大图 → 名字 → 一行元信息 → 单次成本那句人话 → 穿用记录 → 穿着日历 → 档案表单 → 动作。
 *  价格/购入日/品牌/尺码/场合都是**以后慢慢补**的，所以每一格都允许空着，
 *  空着也不挡任何事——只在「还缺哪几样」那一行说出来。 */
function renderYiItem() {
  const body = $("#itemBody");
  if (!body) return;
  const w = (state.wardrobe || []).find((x) => x.id === itemSel);
  if (!w) {
    // 两种空：柜里一件都没有 / 有但没选。前者给入口，后者给回头路——
    // 「这一屏是空的」本身不是答案。
    const any = (state.wardrobe || []).length;
    body.innerHTML = `<div class="empty"><div class="empty-印" aria-hidden="true">衣</div>
      ${any
        ? `这件已经不在柜里了。<br>可能是刚被去掉的。<br>回柜子挑一件看档案。`
        : `柜里还空着，没有可以看的档案。<br>先放几件常穿的进去。`}</div>
      <button type="button" class="btn ghost wide" id="itemToCloset">${any ? "回柜子挑一件" : "去放一件"}</button>`;
    const b = $("#itemToCloset");
    if (b) b.onclick = () => {
      show("yi");
      if (typeof setYiTab === "function") setYiTab("closet");
      if (!any) { const f = $("#fileCloth"); if (f) f.click(); }
    };
    return;
  }
  const seen = typeof Engine !== "undefined" && Engine.seasonOf ? Engine.seasonOf(w) : "";
  const gap = wearDayGap(w);
  const last30 = wearDaysOf(w).filter((t) => Date.now() - t < 30 * DAY).length;
  const cost = cpw(w);
  const miss = itemMissing(w);
  const occ = w.occasions || [];
  const costNum = Number.isFinite(cost) ? `¥${cost.toFixed(1)}` : "—";
  const costUnit = Number.isFinite(cost) ? "每次" : cost === null ? "还没记价格" : "还没穿过，算不出";
  // 主色那一行只在没有照片时才有意义：有照片时第一眼是那件衣服，色值是档案不是画面。
  const toneLine = (() => {
    try {
      const hsl = Engine.rgbToHsl(Engine.hexToRgb(w.color));
      const t = Engine.toneOf(hsl[0], hsl[1], hsl[2]);
      const bucket = typeof colorBucket === "function" ? colorBucket(w.color) : null;
      const name = bucket && !bucket.achromatic ? bucket.name : (bucket && bucket.name) || "";
      return [t, name].filter(Boolean).join(" · ");
    } catch (_) { return ""; }
  })();

  body.innerHTML = `
    <div class="yi-hero">
      <span class="yi-hero-fill" style="background:${cssColor(w.color)}">
        ${w.img ? `<img src="${cssImg(w.img)}" alt="${esc(w.name)}的照片">` : ""}
      </span>
      <span class="yi-hero-mark serif" aria-hidden="true">衣</span>
    </div>
    <h2 class="yi-name serif">${esc(w.name)}</h2>
    <p class="tiny yi-meta">${esc(w.cat)}${seen ? " · " + esc(seen) : ""}${w.brand ? " · " + esc(w.brand) : ""}${w.size ? " · " + esc(w.size) : ""}${toneLine ? " · " + esc(toneLine) : ""}</p>

    <div class="yi-cost">
      <p class="yi-cost-num"><b class="serif">${costNum}</b><small>${costUnit}</small></p>
      <p class="tiny yi-cost-how">单次穿着成本 = 价格 ÷ 穿过次数。不是给衣服打折，是看它被穿了几次。</p>
      <p class="yi-cost-line">${esc(cpwLine(w))}</p>
      <p class="yi-verdict serif">${esc(cpwVerdict(w))}</p>
    </div>

    <p class="tiny yi-wear-line">${w.worn
      ? `穿过 ${w.worn} 次${w.lastWorn ? `，上次 ${relativeDays(w.lastWorn)}` : ""}${last30 ? `，最近 30 天记了 ${last30} 天` : ""}`
      : "还没穿过。第一次记穿之后，这页的数字就开始往下走。"}</p>
    ${gap.gap && gap.days ? `<p class="tiny yi-wear-gap">日历上只画得出 ${gap.days} 天，另外 ${gap.gap} 次是早先只记了次数、没记日子的。</p>` : ""}
    ${(occ.length || (w.tags || []).length) ? `<div class="tagrow" style="margin-top:10px">
      ${occ.map((o) => `<span class="tag">${esc(o)}</span>`).join("")}
      ${(w.tags || []).map((o) => `<span class="tag">${esc(o)}</span>`).join("")}</div>` : ""}
    ${w.note ? `<p class="tiny yi-note">${esc(w.note)}</p>` : ""}

    <div class="row yi-item-acts">
      <button type="button" class="btn" id="itemWear">今天穿了</button>
      <button type="button" class="btn ghost" id="itemCalToggle" aria-expanded="${itemCalOpen}" aria-controls="itemCal">穿着日历</button>
    </div>
    <!-- 长图 lane 追加（v0.6.0）：把这一页存成一张 1080×1920 的纸发出去。
         它单独占一行、不和上面两枚挤：那两枚是「记一笔」，这一枚是「带走一张纸」，
         按错一次的代价不一样。这一枚不删不改上面两枚的任何一行。
         挡着的时候只标 aria-disabled（能聚焦、按得下去、按下去要说话）——
         真 disabled 会把入口对读屏器和键盘整个藏起来，那是本仓反复栽过的那一类。
         .btn 自带 min-height:46px，触摸目标够 44。 -->
    <div class="row" style="margin-top:10px">
      <button type="button" class="btn ghost wide" id="itemSaveCard">存成长图</button>
    </div>
    <p class="tiny" style="margin-top:6px">长图是 1080 × 1920 的一张浅纸：发给谁看都还是这张纸，不会跟着你手机的深色模式变黑。</p>
    <div id="itemCal" class="yi-cal-host"${itemCalOpen ? "" : " hidden"}></div>

    <div class="rule" style="margin:20px 0 14px"></div>
    <p class="tiny">档案<span class="who-none">${miss.length ? `　还空着 ${miss.length} 样：${miss.join("、")}；都可以不填` : "　齐了"}</span></p>
    <div class="field-row" style="margin-top:10px">
      <label class="field"><span>价格</span>
        <input type="text" id="itemPrice" inputmode="decimal" placeholder="多少钱" value="${w.price !== null && w.price !== undefined ? w.price : ""}"></label>
      <label class="field"><span>购入日</span>
        <input type="date" id="itemBought" value="${w.boughtAt ? isoDay(w.boughtAt) : ""}"></label>
    </div>
    <p class="tiny yi-bought" id="itemAge">${esc(boughtLine(w))}</p>
    <div class="field-row">
      <label class="field"><span>品牌</span>
        <input type="text" id="itemBrand" maxlength="20" placeholder="可留空" value="${esc(w.brand || "")}"></label>
      <label class="field"><span>尺码</span>
        <input type="text" id="itemSize" maxlength="10" placeholder="可留空" value="${esc(w.size || "")}"></label>
    </div>
    <div class="field"><span>场合（可多选）</span>
      <div class="chips" id="itemOcc" role="group" aria-label="这件适合的场合">${OCCASIONS.map((o) => `<button type="button" class="chip yi-occ${occ.includes(o) ? " on" : ""}"
        data-occ="${esc(o)}" aria-pressed="${occ.includes(o)}">${esc(o)}</button>`).join("")}</div>
    </div>
    <label class="field"><span>备注</span>
      <input type="text" id="itemNote" maxlength="120" placeholder="一句话记着" value="${esc(w.note || "")}"></label>
    <div class="row"><button type="button" class="btn" id="itemSave">保存档案</button></div>
    <div class="space"></div>
    <div class="row">
      <button type="button" class="btn ghost" id="itemRephoto">换照片</button>
      <button type="button" class="btn ghost" id="itemDel">从柜里去掉</button>
    </div>`;

  /* ---- 场合：点一下即落库。这一格只改 occasions，其余格靠「保存档案」一起交。 ---- */
  $$("#itemOcc [data-occ]").forEach((b) => {
    b.onclick = () => {
      const ocs = new Set(w.occasions || []);
      if (ocs.has(b.dataset.occ)) ocs.delete(b.dataset.occ); else ocs.add(b.dataset.occ);
      w.occasions = [...ocs];
      save(state);
      b.classList.toggle("on", ocs.has(b.dataset.occ));
      b.setAttribute("aria-pressed", String(ocs.has(b.dataset.occ)));
    };
  });

  $("#itemSave").onclick = () => {
    const raw = String($("#itemPrice").value || "").trim().replace(/[^\d.]/g, "");
    const p = raw === "" ? null : Number(raw);
    if (raw !== "" && (!Number.isFinite(p) || p < 0)) { toast("价格得是个 0 以上的数"); return; }
    const bd = $("#itemBought").value;
    // 未来的购入日不是事实：挡下来并说清，别在档案里留一个「2027 年买的」
    if (bd && new Date(bd).getTime() > Date.now()) {
      toast("购入日还没到，等到了再记");
      $("#itemBought").value = w.boughtAt ? isoDay(w.boughtAt) : "";
      return;
    }
    w.price = p;
    w.boughtAt = bd ? new Date(bd).getTime() : null;
    w.brand = $("#itemBrand").value.trim().slice(0, 20);
    w.size = $("#itemSize").value.trim().slice(0, 10);
    w.note = $("#itemNote").value.trim().slice(0, 120);
    save(state);
    renderYiItem();
    renderCloset();
    renderWardrobeStats();
    paintTabCounts();
    toast("档案已记下");
  };

  $("#itemWear").onclick = () => {
    if (wearsOn(w, Date.now())) { toast(`今天已经记过「${w.name}」了，同一天不记两遍`); return; }
    toggleWearDay(w, yiToday());
  };

  $("#itemCalToggle").onclick = () => {
    itemCalOpen = !itemCalOpen;
    const cal = $("#itemCal");
    if (cal) {
      cal.hidden = !itemCalOpen;
      cal.innerHTML = itemCalOpen ? itemCalendarHTML(w) : "";
    }
    $("#itemCalToggle").setAttribute("aria-expanded", String(itemCalOpen));
    if (itemCalOpen) bindItemCal(w);
  };

  $("#itemRephoto").onclick = () => {
    // 补照片认的是 state.clothSel（yi.js 的 rephotoCloth），所以先把它对准这一件
    state.clothSel = w.id;
    save(state);
    const f = $("#fileRephoto");
    if (f) { haptic("LIGHT"); f.click(); }
    else toast("照片入口在柜子里那一件上");
  };

  $("#itemDel").onclick = () => {
    const i = state.wardrobe.findIndex((x) => x.id === w.id);
    if (i < 0) return;
    const snap = state.wardrobe[i];
    state.wardrobe.splice(i, 1);
    if (state.clothSel === snap.id) state.clothSel = null;
    save(state);
    renderCloset();
    renderWardrobeStats();
    paintTabCounts();
    show("yi");
    toastUndo(`已去掉「${snap.name}」`, () => {
      state.wardrobe.splice(Math.min(i, state.wardrobe.length), 0, snap);
      save(state); renderCloset(); renderWardrobeStats(); paintTabCounts();
      toast(`「${snap.name}」回到柜里`);
    });
  };

  const cal = $("#itemCal");
  if (cal) {
    cal.innerHTML = itemCalOpen ? itemCalendarHTML(w) : "";
    if (itemCalOpen) bindItemCal(w);
  }

  /* ---- 长图 lane 追加（v0.6.0）：单品长图 ----
   *  只用 card.js 里新加的那几个函数（drawItemCard / saveLongCard / longFileName），
   *  存图链路复用 saveLongCard——它就是 saveYearCard 那一套（原生 → Filesystem + 系统分享，
   *  浏览器 → 下载），不在这里另写一份 a.click()：那条路在原生壳里什么都不做，
   *  却照样能 toast 一句「已保存」，card.js 与 cookbook.js 都踩过。
   *
   *  画一张图要加载照片，可能失败；失败时必须**开口**。判断放在 onclick 里而不是
   *  进屏时：一件衣服一定有名字（normalizeCloth 保证），所以这一枚永远是可用的；
   *  aria-disabled 只在「这不是一件衣服」这种真的画不出来的状态下才挂。 */
  const saveItem = $("#itemSaveCard");
  if (saveItem) {
    const drawable = typeof drawItemCard === "function" && typeof saveLongCard === "function";
    if (!drawable) saveItem.setAttribute("aria-disabled", "true");
    saveItem.onclick = () => {
      if (!drawable) { toast("长图还没准备好"); return; }
      // 现取一遍：这几张图按的是**此刻**的 w（用户可能刚改完价格还没保存）
      saveLongCard(() => drawItemCard(w), longFileName("衣笺-单品", w.name), saveItem);
    };
  }
}

/** 穿着日历（一个月一屏）。返回 HTML；点某一天能补记 / 取消那天。
 *
 *  为什么按月、而不是原来那片「最近 12 周」的 84 个小格：
 *  390 宽上那 84 格每格只有 11px，看得见、点不着。一个月的 7×6 格每格能到 44px 的命中区——
 *  「可点」这件事得先是真的，然后才谈得上好看。 */
function itemCalendarHTML(w) {
  const base = new Date();
  const first = new Date(base.getFullYear(), base.getMonth() + itemCalMonth, 1);
  const year = first.getFullYear(), month = first.getMonth();
  const daysIn = new Date(year, month + 1, 0).getDate();
  const lead = (new Date(year, month, 1).getDay() + 6) % 7;      // 周一起
  const today0 = yiToday();
  const set = wearDaySet(w);
  const heads = ["一", "二", "三", "四", "五", "六", "日"];
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push('<span class="yi-cal-pad" aria-hidden="true"></span>');
  let wornN = 0;
  for (let d = 1; d <= daysIn; d++) {
    const ts = new Date(year, month, d).getTime();
    const on = set.has(dayStr(ts));
    if (on) wornN++;
    const future = ts > today0;
    const isToday = ts === today0;
    cells.push(`<button type="button" class="yi-cal-day${on ? " on" : ""}${isToday ? " today" : ""}${future ? " future" : ""}"
      data-cald="${d}" aria-pressed="${on}"${future ? ' aria-disabled="true"' : ""}
      aria-label="${year}年${month + 1}月${d}日${on ? "，记过穿" : "，没记穿"}${future ? "，还没到" : ""}">${d}</button>`);
  }
  const canNext = itemCalMonth < 0;
  return `<div class="yi-cal">
    <div class="yi-cal-bar">
      <button type="button" class="yi-cal-nav" id="calPrev" aria-label="上一个月">‹</button>
      <span class="yi-cal-title">${year} 年 ${month + 1} 月${wornN ? ` · 记了 ${wornN} 天` : " · 没有记录"}</span>
      <button type="button" class="yi-cal-nav" id="calNext" aria-label="下一个月"${canNext ? "" : ' aria-disabled="true"'}>›</button>
    </div>
    <div class="yi-cal-grid">
      ${heads.map((h) => `<span class="yi-cal-head" aria-hidden="true">${h}</span>`).join("")}
      ${cells.join("")}
    </div>
    <p class="tiny yi-cal-note">${wornN
      ? "点一个已经记过的日子可以取消它；点一个空着的日子补记那天。"
      : "点一天，把那天补记成穿过。往前的日子都能补。"}</p>
  </div>`;
}

/** 日历上的交互。翻月只重画日历那一块（整页重画会把焦点从日历里踢出去）。 */
function bindItemCal(w) {
  const prev = $("#calPrev"), next = $("#calNext");
  if (prev) prev.onclick = () => { itemCalMonth -= 1; redrawItemCal(w); };
  if (next) next.onclick = () => {
    if (itemCalMonth >= 0) { toast("这已经是这个月了"); return; }
    itemCalMonth += 1; redrawItemCal(w);
  };
  $$("#itemCal [data-cald]").forEach((b) => {
    b.onclick = () => {
      const d = Number(b.dataset.cald);
      const now = new Date();
      const ts = new Date(now.getFullYear(), now.getMonth() + itemCalMonth, d).getTime();
      if (ts > yiToday()) { toast("还没到的那一天不算穿过"); return; }
      toggleWearDay(w, ts);
    };
  });
}

function redrawItemCal(w) {
  const cal = $("#itemCal");
  if (!cal) return;
  const fk = focusKey();
  cal.innerHTML = itemCalendarHTML(w);
  bindItemCal(w);
  restoreFocus(fk);
}

/** 补记 / 取消某一天。worn 与 wearDays 是一笔账的两面，必须一起改：
 *  - 补记：次数 +1，那天进 wearDays；比「上次穿」更晚时，上次穿也挪过来。
 *  - 取消：次数 −1，那天出 wearDays；取消的正是「上次穿」时，退到剩下最晚的那天。
 *  撤销按快照整份填回（次数、上次穿、日历三处同源），不各撤各的。 */
function toggleWearDay(w, ts) {
  const before = { worn: w.worn || 0, lastWorn: w.lastWorn || null, days: wearDaysOf(w).slice() };
  const list = wearDaysOf(w).slice();
  const key = dayStr(ts);
  const at = list.findIndex((t) => dayStr(t) === key);
  const impliedByLast = !!w.lastWorn && dayStr(w.lastWorn) === key && at < 0;
  if (at >= 0 || impliedByLast) {
    if (at >= 0) list.splice(at, 1);
    w.worn = Math.max(0, (w.worn || 0) - 1);
    if (w.lastWorn && dayStr(w.lastWorn) === key) {
      const rest = list.slice().sort((a, b) => b - a);
      w.lastWorn = rest.length ? rest[0] : null;
    }
    if (!w.worn) { w.worn = 0; w.lastWorn = null; }
  } else {
    list.push(ts);
    list.sort((a, b) => a - b);
    w.worn = Math.min(9999, (w.worn || 0) + 1);
    if (!w.lastWorn || ts > w.lastWorn) w.lastWorn = ts;
  }
  w.wearDays = list.slice(-400);
  commitWear(w, before, (at >= 0 || impliedByLast)
    ? `取消了 ${shortDay(ts)} 那次穿着`
    : `补记了 ${shortDay(ts)} 穿了「${w.name}」`);
}

/** 一笔穿着账写回：落盘 + 重画三处 + 记流水 + 给一次反悔。
 *  logEvent 与 checkBadges 一起走：热力图/年度总结读 log，成就也读 log。 */
function commitWear(w, before, msg) {
  save(state);
  logEvent("wear", "yi", w.id);
  checkBadges();
  paintTabCounts();
  const onItem = document.querySelector(".screen.on");
  if (onItem && onItem.id === "yi-item") renderYiItem();
  renderCloset();
  renderWardrobeStats();
  toastUndo(msg, () => {
    w.worn = before.worn;
    w.lastWorn = before.lastWorn;
    w.wearDays = before.days;
    save(state);
    if (document.querySelector(".screen.on").id === "yi-item") renderYiItem();
    renderCloset();
    renderWardrobeStats();
    paintTabCounts();
  });
}

/** 柜子里那枚「今天穿了」按完之后要补的两件事（yi.js 只负责改数，fun 在这里收口）：
 *  记一笔流水、查一遍新章。次数没变（当天已记过 / 减到 0 被挡）时不记流水——
 *  流水只记「真的发生了什么」。 */
function afterWearAction(w, beforeWorn) {
  if ((w.worn || 0) !== beforeWorn) logEvent("wear", "yi", w.id);
  checkBadges();
  paintTabCounts();
}

/* ==================== 搭配册 ==================== */
let outfitSel = null;
let outfitOcc = "";       // 列表的场合筛选："" = 全部

function openOutfit(id) { outfitSel = id; show("yi-outfit"); }

/** 一套里的单品（跳过已经不在柜里的）；missing = 有几件已经从柜里去掉了。 */
function outfitPieces(o) {
  const ids = (o && o.ids) || [];
  const items = ids.map((id) => (state.wardrobe || []).find((w) => w.id === id)).filter(Boolean);
  return { items, missing: ids.length - items.length };
}

/** 搭配这一块在两个容器里各画各的：
 *  - 页签里（#outfitList）画**列表**，点某一套才进子页；
 *  - 子页（#outfitBody）只画**那一套**。
 *  ui.js 的 RENDER 表把 "yi-outfit" 映射到本函数，所以它必须自己认得出当前在哪一屏。 */
function renderYiOutfit() {
  const scr = document.querySelector(".screen.on");
  if (scr && scr.id === "yi-outfit") drawOutfitDetail();
  else drawOutfitList();
}

function drawOutfitList() {
  const host = $("#outfitList");
  if (!host) return;
  const all = state.outfits || [];
  if (!all.length) {
    host.innerHTML = `<div class="empty"><div class="empty-印" aria-hidden="true">搭</div>
      还没有存下来的搭配。<br>从柜子里挑两三件，存成一套——下次「今天穿什么」就不用再想一遍。</div>
      <button type="button" class="btn ghost wide" id="newOutfit">挑几件搭一套</button>`;
    const nb = $("#newOutfit");
    if (nb) nb.onclick = startNewOutfit;
    return;
  }
  const shown = outfitOcc ? all.filter((o) => o.occasion === outfitOcc) : all;
  const used = [...new Set(all.map((o) => o.occasion).filter(Boolean))];
  host.innerHTML = `
    <p class="tiny">已存 ${all.length} 套${outfitOcc ? `，其中「${esc(outfitOcc)}」${shown.length} 套` : ""}</p>
    ${used.length ? `<div class="chips yi-filter" role="group" aria-label="按场合筛搭配">
      <button type="button" class="chip${outfitOcc ? "" : " on"}" data-occf="" aria-pressed="${!outfitOcc}">全部</button>
      ${used.map((u) => `<button type="button" class="chip${outfitOcc === u ? " on" : ""}" data-occf="${esc(u)}"
        aria-pressed="${outfitOcc === u}">${esc(u)}</button>`).join("")}
    </div>` : ""}
    <div class="stack" style="margin-top:10px">${shown.length ? shown.map((o) => {
      const { items, missing } = outfitPieces(o);
      return `<div class="card yi-outfit-card" data-outfit="${esc(o.id)}">
        <button type="button" class="yi-outfit-open" data-oopen="${esc(o.id)}" aria-label="打开搭配「${esc(o.name)}」">
          <span class="yi-outfit-top">
            <b class="serif">${esc(o.name)}</b>
            <span class="tiny">${esc(o.occasion || "没标场合")}${o.worn ? ` · 穿过 ${o.worn} 次` : " · 还没穿过"}</span>
          </span>
        </button>
        <div class="yi-swatches">${items.map((w) => `<button type="button" class="yi-swatch"
          data-oswatch="${esc(w.id)}" aria-label="打开「${esc(w.name)}」的档案"
          style="background:${cssColor(w.color)}">${w.img ? `<img src="${cssImg(w.img)}" alt="">` : ""}</button>`).join("")}
          ${missing ? `<span class="tiny yi-miss">另有 ${missing} 件已从柜里去掉</span>` : ""}</div>
        ${o.note ? `<p class="tiny" style="margin-top:8px">${esc(o.note)}</p>` : ""}
        <div class="bar yi-outfit-acts">
          <button type="button" class="chip" data-owear="${esc(o.id)}">今天穿这套</button>
          <button type="button" class="chip hdel" data-odel="${esc(o.id)}">删</button>
        </div>
      </div>`;
    }).join("") : `<div class="empty">这个场合下还没有搭配。<br>换一个场合，或者点下面再搭一套。</div>`}</div>
    <div class="space"></div>
    <button type="button" class="btn ghost wide" id="newOutfit">再搭一套</button>`;

  const nb = $("#newOutfit");
  if (nb) nb.onclick = startNewOutfit;
  $$("#outfitList [data-occf]").forEach((b) => {
    b.onclick = () => { outfitOcc = b.dataset.occf; drawOutfitList(); };
  });
  $$("#outfitList [data-oopen]").forEach((b) => { b.onclick = () => openOutfit(b.dataset.oopen); });
  // 一套里那几枚色块：点进单品档案。它们是自己的按钮（不是父按钮里的一枚 span）——
  // 按钮里套按钮，HTML 解析器会把外层咬断，点色块就变成「什么也没发生」。
  $$("#outfitList [data-oswatch]").forEach((s) => {
    s.onclick = () => openItem(s.dataset.oswatch);
  });
  $$("#outfitList [data-owear]").forEach((b) => {
    b.onclick = () => {
      const o = state.outfits.find((x) => x.id === b.dataset.owear);
      if (o) wearOutfit(o, false);
    };
  });
  $$("#outfitList [data-odel]").forEach((b) => {
    b.onclick = () => delOutfit(b.dataset.odel);
  });
}

/** 子页：一套的详情。 */
function drawOutfitDetail() {
  const body = $("#outfitBody");
  if (!body) return;
  const all = state.outfits || [];
  const o = all.find((x) => x.id === outfitSel) || all[0];
  if (!o) {
    body.innerHTML = `<div class="empty"><div class="empty-印" aria-hidden="true">搭</div>
      这一套已经不在了。<br>回搭配册看看还有哪几套。</div>`;
    return;
  }
  outfitSel = o.id;
  const { items, missing } = outfitPieces(o);
  body.innerHTML = `
    <h2 class="yi-name serif">${esc(o.name)}</h2>
    <p class="tiny yi-meta">${esc(o.occasion || "没标场合")}${o.worn ? ` · 穿过 ${o.worn} 次${o.lastWorn ? `，上次 ${relativeDays(o.lastWorn)}` : ""}` : " · 还没穿过"}${missing ? ` · ${missing} 件已从柜里去掉` : ""}</p>
    <div class="yi-pieces">${items.length ? items.map((w) => `
      <button type="button" class="yi-piece" data-piece="${esc(w.id)}" aria-label="打开「${esc(w.name)}」的档案">
        <span class="yi-piece-c" style="background:${cssColor(w.color)}">${w.img ? `<img src="${cssImg(w.img)}" alt="">` : ""}</span>
        <span class="yi-piece-n">${esc(w.name)}</span>
        <span class="tiny">${w.cat}${w.worn ? ` · 穿 ${w.worn} 次` : " · 还没穿过"}</span>
      </button>`).join("") : `<p class="tiny">这一套里的单品都已经从柜里去掉了。</p>`}</div>
    ${o.note ? `<p class="tiny" style="margin-top:10px">${esc(o.note)}</p>` : ""}
    <div class="space"></div>
    <button type="button" class="btn wide" id="outfitWear">${items.length > 1 ? `今天穿这套（一次记 ${items.length} 件）` : "今天穿这套"}</button>
    <p class="tiny" style="margin-top:8px">按下会给其中每一件各记一次穿——一套四件就是四笔，不是一笔。撤销会把四件一起退回。</p>
    <!-- 长图 lane 追加（v0.6.0）：把这一套存成一张 1080×1920 的纸。
         刻意摆在「今天穿这套」**下面**、与「回搭配册 / 删掉这套」隔开一段：
         它是「带走一张纸」，不是「动这套搭配」。这一块不动上面任何一枚按钮。
         一件都没有时（items 空、整屏只剩那句空话）这一枚标 aria-disabled，
         但照样能聚焦、能按下、按下去会说清楚为什么画不出来。 -->
    <div class="space"></div>
    <button type="button" class="btn ghost wide" id="outfitSaveCard"${items.length ? "" : ` aria-disabled="true"`}>存成长图</button>
    <p class="tiny" style="margin-top:6px">长图是 1080 × 1920 的一张浅纸：${items.length ? "几件并排、场合与穿用记录都在上面。" : "这一套里一件都点不出来，所以画不成。"}</p>
    <div class="space"></div>
    <div class="row">
      <button type="button" class="btn ghost" id="outfitBack">回搭配册</button>
      <button type="button" class="btn ghost" id="outfitDel">删掉这套</button>
    </div>`;
  $$("#outfitBody [data-piece]").forEach((b) => { b.onclick = () => openItem(b.dataset.piece); });
  $("#outfitWear").onclick = () => wearOutfit(o, true);
  $("#outfitBack").onclick = () => { show("yi"); if (typeof setYiTab === "function") setYiTab("outfit"); };
  $("#outfitDel").onclick = () => { delOutfit(o.id); };

  /* ---- 长图 lane 追加（v0.6.0）：搭配长图 ----
   *  存图复用 card.js 的 saveLongCard（= saveYearCard 那条链路），不另写一份。
   *  画不出来（一件都没有 / 函数没装好）时必须**开口**：aria-disabled 的钮
   *  按得下去，说不出理由就等于回到静默——那是本仓第 57 轮裁决换轨换来的规矩。 */
  const saveOutfit = $("#outfitSaveCard");
  if (saveOutfit) {
    const drawable = items.length > 0 && typeof drawOutfitCard === "function" && typeof saveLongCard === "function";
    saveOutfit.onclick = () => {
      if (!items.length) { toast("这一套里的单品都已经不在柜里，画不成"); return; }
      if (typeof drawOutfitCard !== "function" || typeof saveLongCard !== "function") { toast("长图还没准备好"); return; }
      saveLongCard(() => drawOutfitCard(o), longFileName("衣笺-搭配", o.name), saveOutfit);
    };
    if (!drawable) saveOutfit.setAttribute("aria-disabled", "true");
  }
}


/** 「今天穿这套」：给这一套里**每一件**各记一次穿（logEvent 每件一笔 + worn+1），整套也记一笔。
 *  一次记四件，就不能说成「记了一次」；撤销也是四件一起退。 */
function wearOutfit(o, fromDetail) {
  const { items } = outfitPieces(o);
  if (!items.length) { toast("这一套里的单品都已经不在柜里了"); return; }
  const fresh = items.filter((w) => !wearsOn(w, Date.now()));
  if (!fresh.length) { toast(`这 ${items.length} 件今天都记过了，同一天不记两遍`); return; }
  const snaps = fresh.map((w) => ({ w, worn: w.worn || 0, lastWorn: w.lastWorn || null, days: wearDaysOf(w).slice() }));
  const oSnap = { worn: o.worn || 0, lastWorn: o.lastWorn || null };
  const today = yiToday();
  fresh.forEach((w) => {
    const list = wearDaysOf(w).slice();
    list.push(today);
    list.sort((a, b) => a - b);
    w.wearDays = list.slice(-400);
    w.worn = Math.min(9999, (w.worn || 0) + 1);
    w.lastWorn = today;
    logEvent("wear", "yi", w.id);
  });
  o.worn = (o.worn || 0) + 1;
  o.lastWorn = today;
  logEvent("outfit", "yi", o.id);
  checkBadges();
  save(state);
  paintTabCounts();
  if (fromDetail) drawOutfitDetail(); else drawOutfitList();
  renderCloset();
  renderWardrobeStats();
  haptic("MEDIUM");
  const skipped = items.length - fresh.length;
  toastUndo(`一次记 ${fresh.length} 件${skipped ? `（有 ${skipped} 件今天已经记过）` : ""}`, () => {
    snaps.forEach((s) => { s.w.worn = s.worn; s.w.lastWorn = s.lastWorn; s.w.wearDays = s.days; });
    o.worn = oSnap.worn; o.lastWorn = oSnap.lastWorn;
    save(state);
    if (document.querySelector(".screen.on").id === "yi-outfit") drawOutfitDetail();
    else drawOutfitList();
    renderCloset(); renderWardrobeStats(); paintTabCounts();
  });
}

function delOutfit(id) {
  const i = (state.outfits || []).findIndex((x) => x.id === id);
  if (i < 0) return;
  const snap = state.outfits[i];
  state.outfits.splice(i, 1);
  if (outfitSel === id) outfitSel = null;
  save(state);
  paintTabCounts();
  if (document.querySelector(".screen.on").id === "yi-outfit") { show("yi"); if (typeof setYiTab === "function") setYiTab("outfit"); }
  else drawOutfitList();
  toastUndo(`已删掉「${snap.name}」这一套`, () => {
    state.outfits.splice(Math.min(i, state.outfits.length), 0, snap);
    save(state); paintTabCounts(); drawOutfitList();
  });
}

/** 挑几件搭一套：在页签里就地摊开的选择面板（不新开屏，返回栈就不会再深一层）。
 *  场合可以顺手标上——它是「按场合筛」那一排签唯一的来源。 */
function startNewOutfit() {
  const wd = state.wardrobe || [];
  const host = $("#outfitList");
  if (!host) return;
  if (!wd.length) { toast("柜里还没有衣服，先放几件进去"); return; }
  const picked = new Set();
  let occ = "";
  host.innerHTML = `<p class="tiny">挑 2–4 件。选好之后给它起个名字、标个场合。</p>
    <div class="closet yi-pick" id="outfitPick" style="margin-top:10px">${wd.map((w) => `
      <button type="button" class="item yi-pick-item" data-pick="${esc(w.id)}" aria-pressed="false"
        aria-label="选「${esc(w.name)}」">
        <span class="yi-pick-c" style="background:${cssColor(w.color)}">${w.img ? `<img src="${cssImg(w.img)}" alt="">` : ""}</span>
        <span class="tag">${esc(w.name)}</span>
      </button>`).join("")}</div>
    <p class="tiny yi-pick-count" id="pickCount" aria-live="polite">还没挑</p>
    <input type="text" id="outfitName" placeholder="给这套起个名字（可留空）" maxlength="20" aria-label="搭配名字">
    <div class="field" style="margin-top:12px"><span>场合</span>
      <div class="chips" id="outfitOcc" role="group" aria-label="这套的场合">${["", ...OCCASIONS].map((oc) => `<button type="button"
        class="chip${oc === "" ? " on" : ""}" data-oc="${esc(oc)}" aria-pressed="${oc === ""}">${oc || "不标"}</button>`).join("")}</div>
    </div>
    <div class="row">
      <button type="button" class="btn ghost" id="outfitCancel">取消</button>
      <button type="button" class="btn" id="outfitSave">存下这套</button>
    </div>`;
  const sync = () => {
    const el = $("#pickCount");
    if (!el) return;
    const n = picked.size;
    el.textContent = n ? `已挑 ${n} 件${n === 1 ? "（至少两件）" : n > 4 ? "（最多四件）" : ""}` : "还没挑";
  };
  $$("#outfitPick [data-pick]").forEach((b) => {
    b.onclick = () => {
      const id = b.dataset.pick;
      if (picked.has(id)) picked.delete(id); else picked.add(id);
      b.setAttribute("aria-pressed", String(picked.has(id)));
      b.classList.toggle("on", picked.has(id));
      sync();
    };
  });
  $$("#outfitOcc [data-oc]").forEach((b) => {
    b.onclick = () => {
      occ = b.dataset.oc;
      $$("#outfitOcc [data-oc]").forEach((x) => {
        x.classList.toggle("on", x === b);
        x.setAttribute("aria-pressed", String(x === b));
      });
    };
  });
  $("#outfitCancel").onclick = () => drawOutfitList();
  $("#outfitSave").onclick = () => {
    if (picked.size < 2) { toast("至少挑两件才算一套"); return; }
    if (picked.size > 4) { toast("一套最多四件"); return; }
    const name = String($("#outfitName").value || "").trim().slice(0, 20) || "一套";
    state.outfits.push({
      id: "o" + newId().slice(1), name, ids: [...picked], occasion: occ,
      note: "", t: Date.now(), worn: 0, lastWorn: null,
    });
    save(state);
    logEvent("outfit", "yi", name);
    checkBadges();
    paintTabCounts();
    drawOutfitList();
    toast(`「${name}」存下了`);
  };
}

/* ==================== 愿望单 ==================== */

/** 冷静期到了、还没决定的那些。打开衣笺时页签上那个小点、愿望页那句提醒都读它。 */
function wishRipe() {
  const now = Date.now();
  return (state.wish || []).filter((w) => {
    if (w.done) return false;
    const days = Math.floor((now - w.t) / DAY);
    return w.cool > 0 && days >= w.cool;
  });
}

/** 累计忍住的金额：只有「决定了不买」且记了价格的才计入。
 *  没记价格的愿望省下的钱说不清数额——把它算进总额就是编数字。 */
function wishSaved() {
  const list = (state.wish || []).filter((w) => w.done && !w.bought && w.price !== null && w.price !== undefined);
  return { pieces: list.length, money: list.reduce((s, w) => s + (w.price || 0), 0) };
}

/** 页签上那个「冷静期到了」的小点。挂在按钮的 data-ripe 上（样式在 styles-yi.css），
 *  不新增 DOM id —— index.html 是 Lead 的，页签计数是 wire.js 的，这一块不越界。 */
function paintWishRipe() {
  const b = $('#yiTabs [data-yitab="wish"]');
  if (!b) return;
  const n = wishRipe().length;
  if (n) b.setAttribute("data-ripe", String(n));
  else b.removeAttribute("data-ripe");
  const base = "愿望";
  b.setAttribute("aria-label", n ? `${base}，有 ${n} 件冷静期到了` : base);
}

/** 愿望单的核心不是「记下来」，是**冷静期**：加进去时定几天，到期回来看一眼「还想买吗」。
 *  三天是默认值——短到不至于忘，长到能退烧。 */
function renderWish() {
  const list = $("#wishList");
  const note = $("#wishNote");
  if (!list) return;
  const all = state.wish || [];
  const open = all.filter((w) => !w.done);
  const done = all.filter((w) => w.done);
  const ripe = wishRipe();
  const saved = wishSaved();
  if (note) {
    const bits = [];
    if (!all.length) bits.push("还没有想买的东西。看中一件，先放进来冷静三天。");
    else {
      bits.push(`在想 ${open.length} 件${done.length ? `，已经决定 ${done.length} 件` : ""}。`);
      bits.push(ripe.length
        ? `其中 ${ripe.length} 件冷静期到了，往下看看还想不想买。`
        : "冷静期到了会在这儿和页签上叫你回来看一眼。");
      if (saved.pieces) bits.push(`已经有 ${saved.pieces} 件决定不买，省下 ¥${saved.money.toFixed(0)}。`);
    }
    note.textContent = bits.join("");
  }
  const cardOf = (w) => {
    const days = Math.floor((Date.now() - w.t) / DAY);
    const left = w.cool - days;
    const isRipe = !w.done && w.cool > 0 && left <= 0;
    return `<div class="card yi-wish-card${isRipe ? " ripe" : ""}" data-wish="${esc(w.id)}">
      <div class="bar yi-wish-top">
        <b class="serif">${esc(w.name)}</b>
        <span class="tiny">${esc(w.cat)}${w.price !== null && w.price !== undefined ? ` · ¥${w.price.toFixed(0)}` : " · 没记价格"}</span>
      </div>
      <p class="tiny yi-wish-state">${w.done
        ? (w.bought ? `已决定：买了（想了 ${days} 天）` : `已决定：不买了${w.price !== null && w.price !== undefined ? `，省下 ¥${w.price.toFixed(0)}` : ""}`)
        : isRipe ? `冷静了 ${days} 天，够久了。还想买吗？`
          : `还要冷静 ${left} 天（第 ${days} / ${w.cool} 天）`}</p>
      ${w.note ? `<p class="tiny" style="margin-top:6px">${esc(w.note)}</p>` : ""}
      <div class="bar yi-wish-acts">
        ${w.done
          ? `<button type="button" class="chip" data-wundo="${esc(w.id)}">放回在想</button>`
          : `<button type="button" class="chip" data-wpass="${esc(w.id)}">去过笺</button>
             <button type="button" class="chip" data-wbuy="${esc(w.id)}">买了</button>
             <button type="button" class="chip" data-wdrop="${esc(w.id)}">不买了</button>`}
        <button type="button" class="chip hdel" data-wdel="${esc(w.id)}">删</button>
      </div>
    </div>`;
  };
  list.innerHTML = open.map(cardOf).join("") + done.map(cardOf).join("");
  const byId = (id) => (state.wish || []).find((x) => x.id === id);
  $$("#wishList [data-wbuy]").forEach((b) => {
    b.onclick = () => {
      const w = byId(b.dataset.wbuy);
      if (!w) return;
      w.done = true; w.bought = true; save(state);
      logEvent("wish", "yi", w.name); checkBadges();
      renderWish(); paintTabCounts(); renderWardrobeStats();
      toast(`记下了：${w.name}（想了 ${Math.floor((Date.now() - w.t) / DAY)} 天）`);
    };
  });
  $$("#wishList [data-wdrop]").forEach((b) => {
    b.onclick = () => {
      const w = byId(b.dataset.wdrop);
      if (!w) return;
      w.done = true; w.bought = false; save(state);
      logEvent("wish", "yi", w.name); checkBadges();
      renderWish(); paintTabCounts(); renderWardrobeStats();
      // 「省下 ¥N」是这个 App 唯一会夸人的地方，而它只夸真的省下来的钱
      toast(w.price !== null && w.price !== undefined ? `不买了，省下 ¥${w.price.toFixed(0)}` : "不买了。这一件没进柜子");
    };
  });
  $$("#wishList [data-wundo]").forEach((b) => {
    b.onclick = () => {
      const w = byId(b.dataset.wundo);
      if (!w) return;
      w.done = false; w.bought = false; save(state);
      renderWish(); paintTabCounts(); renderWardrobeStats();
    };
  });
  $$("#wishList [data-wpass]").forEach((b) => { b.onclick = () => wishToPass(b.dataset.wpass); });
  $$("#wishList [data-wdel]").forEach((b) => {
    b.onclick = () => {
      const i = (state.wish || []).findIndex((x) => x.id === b.dataset.wdel);
      if (i < 0) return;
      const snap = state.wish[i];
      state.wish.splice(i, 1);
      save(state); renderWish(); paintTabCounts();
      toastUndo(`已删掉「${snap.name}」`, () => {
        state.wish.splice(Math.min(i, state.wish.length), 0, snap);
        save(state); renderWish(); paintTabCounts();
      });
    };
  });
  paintWishRipe();
}

/** 愿望 → 过笺：把名字、品类、颜色带过去，判定仍然要用一张照片重取颜色。
 *  带过去的是「要问的那件」，不是一块空白首屏。 */
function wishToPass(id) {
  const w = (state.wish || []).find((x) => x.id === id);
  if (!w) return;
  state.yiCat = CATS.includes(w.cat) ? w.cat : state.yiCat;
  if (typeof presetNewName === "function") presetNewName(w.name);
  state.lastNew = { name: w.name, cat: w.cat, color: w.color, img: "", price: w.price, wishId: w.id };
  save(state);
  if (typeof setYiTab === "function") setYiTab("pass");
  if (typeof paintHero === "function") paintHero();
  if (typeof renderCats === "function") renderCats();
  toast(`带着「${w.name}」去过笺。判定要用一张照片重取颜色，名字和品类已经带过去了。`, 3400);
}

/** 加一件想买的。名字必填，价格可空（价格只用于「省下多少」那一句）。 */
function addWish(name, price, cat, color) {
  const nm = String(name || "").trim().slice(0, 40);
  if (!nm) { toast("先写个名字"); return null; }
  const p = price === "" || price === null || price === undefined ? null : Number(price);
  if (p !== null && (!Number.isFinite(p) || p < 0)) { toast("价格得是个 0 以上的数"); return null; }
  const w = {
    id: "s" + newId().slice(1), name: nm, cat: CATS.includes(cat) ? cat : CATS[0],
    color: color || "#c8c8c8", price: p, t: Date.now(), cool: 3, note: "", done: false, bought: false,
  };
  state.wish.push(w);
  save(state);
  renderWish();
  logEvent("wish", "yi", nm);
  checkBadges();
  paintTabCounts();
  return w;
}

/* ==================== 衣柜统计（柜子页底部那一块） ==================== */

/** 统计那一块的原料全部现算、不落盘。任何一项算不出来（没价格 / 没穿过）都由 cpw 说
 *  「算不出来」，不许拿 0 顶替。颜色分桶读 stats.js 的 colorBucket（全仓只有那一份
 *  hue → 桶 的换算，色相本身只有 engine.js 的 rgbToHsl 一份）。 */
function yiClosetFacts() {
  const wd = state.wardrobe || [];
  const byCat = {};
  wd.forEach((w) => { byCat[w.cat] = (byCat[w.cat] || 0) + 1; });
  const cats = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
  const bucket = new Map();
  let achromatic = 0;
  wd.forEach((w) => {
    let b = null;
    try { b = typeof colorBucket === "function" ? colorBucket(w.color) : null; } catch (_) { b = null; }
    if (!b) return;
    if (b.achromatic) { achromatic++; return; }
    bucket.set(b.name, (bucket.get(b.name) || 0) + 1);
  });
  const colors = [...bucket.entries()].sort((a, b) => b[1] - a[1]);
  const wornTop = wd.filter((w) => w.worn > 0).sort((a, b) => b.worn - a.worn).slice(0, 3);
  const idle = wd.filter((w) => w.lastWorn).sort((a, b) => a.lastWorn - b.lastWorn).slice(0, 3);
  const never = wd.filter((w) => !w.worn);
  return { wd, total: wd.length, cats, colors, achromatic, wornTop, idle, never };
}

function renderWardrobeStats() {
  const host = $("#wardrobeStats");
  if (!host) return;
  paintWishRipe();
  const f = yiClosetFacts();
  if (!f.total) { host.innerHTML = ""; return; }
  const wr = wearRate();
  const c = closetCpw();
  const saved = wishSaved();
  const thin = f.total < 5;              // 少于 5 件：比例不当结论（与引擎的 thin 同一档）
  const catLine = f.cats.map(([k, v]) => `${k} ${v}`).join(" / ");
  const colorLine = f.colors.length
    ? f.colors.slice(0, 4).map(([k, v]) => `${k} ${v}`).join(" / ")
      + (f.achromatic ? ` / 黑白灰 ${f.achromatic}` : "")
    : "";
  const topColor = f.colors[0];
  const colorPct = topColor ? Math.round((topColor[1] / f.total) * 100) : 0;

  const blocks = [];
  blocks.push(`<div class="rule" style="margin:22px 0 14px"></div>
    <p class="tiny">这一柜</p>
    <div class="stat-grid" style="margin-top:8px">
      <div class="stat"><b>${f.total}<small>件</small></b><span>${esc(catLine)}</span></div>
      <div class="stat"><b>${wr.pct}<small>%</small></b><span>在穿率（${wr.worn} / ${wr.total} 件穿过）</span></div>
    </div>
    <p class="tiny yi-thin">${thin
      ? `柜里只有 ${f.total} 件，这些比例还说明不了什么——再放几件进来，它才开始说话。`
      : `${f.total} 件里 ${wr.worn} 件穿过${f.never.length ? `，${f.never.length} 件一次没穿` : "，没有一件是白买的"}。`}</p>`);

  /* 单次成本：算不出来时说清缺的是哪一样，并给出下一步 */
  blocks.push(`<p class="tiny yi-block-title">单次穿着成本</p>
    <p class="yi-stat-line">${Number.isFinite(c.cpw)
      ? `一件平均 <b>¥${c.cpw.toFixed(1)}</b>（${c.pieces} 件记了价格、共 ¥${c.price.toFixed(0)}，累计穿过 ${c.worn} 次）`
      : c.pieces
        ? `${c.pieces} 件记了价格、共 ¥${c.price.toFixed(0)}，但还没记过穿着——单次成本算不出来。点开柜里一件，按「今天穿了」。`
        : "还没给任何一件记价格。记了才看得到「这件每穿一次值几块钱」。"}</p>`);

  /* 颜色分布：薄柜子不说「你 41% 的衣服是同一个色系」 */
  if (colorLine) {
    blocks.push(`<p class="tiny yi-block-title">颜色</p>
      <p class="yi-stat-line">${esc(colorLine)}</p>
      <p class="tiny yi-thin">${thin || !topColor
        ? "件数还少，谈不上「你的色系」。"
        : colorPct >= 40
          ? `${colorPct}% 的衣服落在「${esc(topColor[0])}」这一个色系里——买新衣服前可以想一想。`
          : `最多的是「${esc(topColor[0])}」，${topColor[1]} 件，${colorPct}%。柜子还算杂。`}</p>`);
  }

  /* 最常穿 / 最久没穿：两列，名字可以点进档案 */
  blocks.push(`<p class="tiny yi-block-title">最常穿</p>
    <div class="yi-top3">${f.wornTop.length ? f.wornTop.map((w) => `
      <button type="button" class="yi-top3-row" data-stat-item="${esc(w.id)}" aria-label="打开「${esc(w.name)}」的档案">
        <span class="yi-dot" style="background:${cssColor(w.color)}" aria-hidden="true"></span>
        <span class="yi-top3-name">${esc(w.name)}</span>
        <span class="tiny">${w.worn} 次${w.lastWorn ? ` · ${relativeDays(w.lastWorn)}` : ""}</span>
      </button>`).join("") : `<p class="tiny">还没有记过穿。柜子里选一件，点「今天穿了」。</p>`}</div>
    <p class="tiny yi-block-title">最久没穿</p>
    <div class="yi-top3">${f.idle.length ? f.idle.map((w) => `
      <button type="button" class="yi-top3-row" data-stat-item="${esc(w.id)}" aria-label="打开「${esc(w.name)}」的档案">
        <span class="yi-dot" style="background:${cssColor(w.color)}" aria-hidden="true"></span>
        <span class="yi-top3-name">${esc(w.name)}</span>
        <span class="tiny">${relativeDays(w.lastWorn)}</span>
      </button>`).join("") : `<p class="tiny">没有记录，说不清哪件最久没穿。</p>`}</div>`);

  /* 忍住的金额 */
  blocks.push(`<p class="tiny yi-block-title">忍住的</p>
    <p class="yi-stat-line">${saved.pieces
      ? `在愿望单里决定不买的有 <b>${saved.pieces}</b> 件，一共省下 <b>¥${saved.money.toFixed(0)}</b>。`
      : "还没有「决定不买」的记录。愿望单里放三天，回来还想要再说。"}</p>`);

  host.innerHTML = blocks.join("");
  $$("#wardrobeStats [data-stat-item]").forEach((b) => { b.onclick = () => openItem(b.dataset.statItem); });
}

/* 开机时先把页签那个小点刷一遍（boot 里没有人会调衣柜的渲染函数，
   而第一个能进到「愿望」页的动作要等到用户点页签）。这里只读 state，不写盘。 */
window.addEventListener("load", () => {
  try { paintWishRipe(); } catch (_) { /* 还没画出界面时也没什么可标的 */ }
});
