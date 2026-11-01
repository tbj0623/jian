/** 笺 · 各模块与「今日/笺谱/册」之间的接线
 *
 *  为什么单独一个文件：这些函数每一个都是「A 屏要跳到 B 屏」这种跨模块的小事——
 *  放进任何一个模块文件都会让那个文件开始 import 别人的概念（衣笺不该知道味笺有什么菜）。
 *  放在这里，依赖方向永远是「接线层 → 模块」，反过来一条都没有。
 *
 *  规矩：这一层**不实现业务**，只做三件事：切屏、挑一个对象传过去、把状态复位。
 *  任何一处出现「算出来」的逻辑，都应该搬回它该在的模块文件里。
 */

/* ==================== 页签（衣笺 / 味笺） ==================== */

/** 衣笺四页签：过笺 / 柜子 / 搭配 / 愿望。切页签不换屏，所以返回键不会在中间乱跳。 */
function setYiTab(tab) {
  const map = { pass: "yiPanePass", closet: "yiPaneCloset", outfit: "yiPaneOutfit", wish: "yiPaneWish" };
  if (!map[tab]) return;
  Object.entries(map).forEach(([k, id]) => { const el = $("#" + id); if (el) el.hidden = k !== tab; });
  $$("#yiTabs [data-yitab]").forEach((b) => {
    const on = b.dataset.yitab === tab;
    b.setAttribute("aria-selected", String(on));
    // roving tabindex：页签组里只有选中的那个在 Tab 序列里（否则 Tab 要过四遍）
    b.tabIndex = on ? 0 : -1;
  });
  if (tab === "closet") { renderCloset(); renderWardrobeStats(); }
  if (tab === "outfit") renderYiOutfit();
  if (tab === "wish") renderWish();
  paintTabCounts();
}
/** 页签上那几个数字：只在有东西时显示（0 不显示，否则一排零看着像坏掉了）。 */
function paintTabCounts() {
  const set = (id, n) => { const el = $(id); if (el) el.textContent = n ? String(n) : ""; };
  set("#yiClosetCnt", (state.wardrobe || []).length);
  set("#yiOutfitCnt", (state.outfits || []).length);
  set("#yiWishCnt", (state.wish || []).filter((w) => !w.done).length);
  set("#weiCookCnt", new Set((state.cookLog || []).map((c) => c.name)).size);
  set("#weiMarketCnt", (state.market || []).filter((m) => !m.done).length);
}

/** 味笺四页签：排桌 / 做菜 / 买菜 / 这周。 */
function setWeiTab(tab) {
  const map = { plan: "weiPanePlan", cook: "weiPaneCook", market: "weiPaneMarket", week: "weiPaneWeek" };
  if (!map[tab]) return;
  Object.entries(map).forEach(([k, id]) => { const el = $("#" + id); if (el) el.hidden = k !== tab; });
  $$("#weiTabs [data-weitab]").forEach((b) => {
    const on = b.dataset.weitab === tab;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  if (tab === "cook") renderCook();
  if (tab === "market") renderMarket();
  if (tab === "week") renderWeiWeek();
  if (tab === "plan") renderWei();
  paintTabCounts();
}

/** 当前页签（记在内存里，不进 state：它是「我正在看哪一页」，重开回到第一页是对的）。 */
let yiTab = "pass", weiTab = "plan";

/* ==================== 跨模块的入口 ==================== */

/** 选中柜里的一件（今日那一屏点「某件很久没穿」用）。 */
function selectCloth(id) {
  const w = (state.wardrobe || []).find((x) => x.id === id);
  if (!w) return;
  state.clothSel = id;
  save(state);
  setYiTab("closet");
  renderCloset();
  if (typeof scrollToClothActions === "function") scrollToClothActions();
  toast(`已选中「${w.name}」`);
}
/** 过笺的照片入口（今日「过第一张笺」用）。 */
function openPhoto() {
  const el = $("#fileNew");
  if (el) el.click();
}
/** 深链带进来的名字：过笺时预填成「想买的这件」。 */
function presetNewName(name) {
  pendingNewName = String(name || "").slice(0, 40);
  toast(`从链接带来一件「${pendingNewName}」，过笺时会用它当名字`);
}
let pendingNewName = "";
/** 深链带进来的文字：填进言笺输入框（不自动捞——那是另一次判定，要扣点）。 */
function presetYanText(text) {
  state.yanText = String(text || "").slice(0, 4000);
  save(state);
  const el = $("#yanText");
  if (el) el.value = state.yanText;
  toast("已经贴进言笺，按「捞成笺」就好");
}
/** 言笺某条被点中时的聚焦（今日那一屏用）：滚到它并闪一下。 */
function focusYanCard(card) {
  if (!card) return;
  const idx = (state.yanCards || []).indexOf(card);
  if (idx < 0) return;
  // 切到「按类型」并清掉筛选，保证那一行真的在屏上（否则「点了一下什么都没发生」）
  state.yanView = "kind";
  state.yanHideDone = false;
  const s = $("#yanSearch"); if (s) s.value = "";
  save(state);
  renderYan();
  setTimeout(() => {
    const rows = $$("#yanOut .row, #yanOut .card");
    const el = rows.find((r) => r.textContent.includes(String(card.line).slice(0, 12)));
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.classList.add("flash");
      setTimeout(() => el.classList.remove("flash"), 1200);
    }
  }, 60);
}
/** 全局搜索把「言笺」那一组点开时用：带上关键词进言笺。 */
function yanSearchFor(q) {
  show("yan");
  const s = $("#yanSearch");
  if (s) { s.value = q; s.dispatchEvent(new Event("input")); }
}

/* ==================== 清空数据（设置页与册共用一个入口） ==================== */

/** 「清空本地数据」的全流程。原来只写在 me.js 里，现在设置页也有一枚——
 *  两处各写一份的下场是「一处清了通知、一处没清」。所以收成一处。 */
function resetAll() {
  if (typeof requestReset === "function") { requestReset(); return; }
  // 兜底：me.js 的 reset 绑定在 #reset 上，直接点它
  const b = $("#reset");
  if (b) b.click(); else toast("清空入口没找到");
}
