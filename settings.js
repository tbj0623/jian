/** 笺 · 设置与全局搜索
 *
 *  这两块放同一个文件，因为它们都是「跨屏的东西」：
 *  设置调的是全局外观与通知；搜索关的是全部数据。
 *
 *  设置页为什么从「册」里拆出来：原来那一屏既是钱包、又是模块开关、又是网关、又是备份、
 *  又是隐私、又是笺册——六件事挤一屏，加第七件就没有地方放了。拆开之后
 *  「册」只管我的东西（钱包/笺册/数据），「设置」只管调节（外观/通知/关于）。
 */

/* ==================== 设置 ==================== */

function renderSettings() {
  const body = $("#settingsBody");
  if (!body) return;
  const s = state.settings || {};
  const dark = THEME.dark();
  const sysDark = THEME.systemIsDark();
  const notifyOn = s.notify !== false;
  body.innerHTML = `
    <p class="tiny">外观</p>
    <div class="list" style="margin-top:8px">
      <div class="rowbtn plain" style="cursor:default">
        <span class="grow"><b>主题</b><span class="sub">纸有两种说法：白天的纸、夜里的纸</span></span>
      </div>
      <div style="padding:10px 14px 14px">
        <div class="seg" id="setTheme">
          <button data-theme-pick="auto" aria-pressed="${s.theme === "auto"}">跟随系统</button>
          <button data-theme-pick="light" aria-pressed="${s.theme === "light"}">白天的纸</button>
          <button data-theme-pick="dark" aria-pressed="${s.theme === "dark"}">夜里的纸</button>
        </div>
        <p class="tiny" style="margin-top:8px">现在是${dark ? "夜里的纸" : "白天的纸"}；系统现在是${sysDark ? "暗" : "亮"}。长图永远是白天的纸——那是发给别人看的。</p>
      </div>
      <div style="padding:0 14px 14px">
        <p class="tiny" style="margin-bottom:6px">字号</p>
        <div class="seg" id="setFont">
          <button data-font-pick="s" aria-pressed="${s.font === "s"}">小</button>
          <button data-font-pick="m" aria-pressed="${s.font === "m"}">标准</button>
          <button data-font-pick="l" aria-pressed="${s.font === "l"}">大</button>
        </div>
        <p class="tiny" style="margin-top:8px">系统字号也会叠在上面——调它之前先把系统那个放回中间。</p>
      </div>
      <div style="padding:0 14px 14px">
        <p class="tiny" style="margin-bottom:6px">印章</p>
        <div class="seg" id="setSeal">
          <button data-seal-pick="classic" aria-pressed="${s.sealStyle === "classic"}">经典</button>
          <button data-seal-pick="thin" aria-pressed="${s.sealStyle === "thin"}">细线</button>
          <button data-seal-pick="solid" aria-pressed="${s.sealStyle === "solid"}">实底</button>
        </div>
      </div>
      <label class="rowbtn plain" style="cursor:default">
        <span class="grow"><b>动效</b><span class="sub">关掉之后所有过渡立刻完成</span></span>
        <input type="checkbox" class="switch" id="setMotion" ${s.motion === false ? "" : "checked"}>
      </label>
      <label class="rowbtn plain" style="cursor:default">
        <span class="grow"><b>触感</b><span class="sub">落章、记穿、勾掉的时候给一记</span></span>
        <input type="checkbox" class="switch" id="setHaptic" ${s.haptic === false ? "" : "checked"}>
      </label>
    </div>

    <p class="tiny" style="margin-top:22px">通知</p>
    <div class="list" style="margin-top:8px">
      <label class="rowbtn plain" style="cursor:default">
        <span class="grow"><b>到点提醒</b><span class="sub">${notifyOn ? "开着的" : "关着的"}</span></span>
        <input type="checkbox" class="switch" id="setNotify" ${notifyOn ? "checked" : ""}>
      </label>
      <button class="rowbtn" id="setPerm">
        <span class="grow"><b>检查通知权限</b><span class="sub">安卓 13 起要在系统里允许</span></span>
      </button>
      <button class="rowbtn" id="setRemindAll">
        <span class="grow"><b>提醒总览</b><span class="sub" id="setRemindSub">${(state.reminders || []).filter((r) => !r.done).length} 条没办</span></span>
      </button>
    </div>
    <p class="tiny" style="margin-top:8px">通知会被系统的省电策略攒着发，所以是「大约这个点」。</p>

    <p class="tiny" style="margin-top:22px">关于</p>
    <div class="list" style="margin-top:8px">
      <button class="rowbtn" id="setPrivacy">
        <span class="grow"><b>隐私政策</b><span class="sub">数据去哪儿、网关是什么</span></span>
      </button>
      <button class="rowbtn" id="setAbout">
        <span class="grow"><b>关于笺</b><span class="sub" id="aboutVer">版本 ${esc(JIAN_CONFIG.version)}</span></span>
      </button>
    </div>

    <div class="space"></div>
    <p class="tiny" id="settingsNote">${dataNote()}</p>
    <div class="space"></div>
    <button class="chip" id="setResetAll">清空本地数据</button>`;
  bindSettings();
}

/** 数据规模那一句：设置页和「册」都印它，所以只有一份定义。 */
function dataNote() {
  const wd = (state.wardrobe || []).length;
  const yc = (state.yanCards || []).length;
  const ab = (state.album || []).length;
  const store = storageInfo();
  return `柜 ${wd} 件 · 言 ${yc} 条 · 笺册 ${ab} 张 · 用了 ${store.kb} KB`
    + `（上限约 ${Math.round(SHED_AT / 1024)} KB）`;
}

function bindSettings() {
  $$("#setTheme [data-theme-pick]").forEach((b) => {
    b.onclick = () => { THEME.set("theme", b.dataset.themePick); renderSettings(); toast(`主题：${b.textContent.trim()}`); };
  });
  $$("#setFont [data-font-pick]").forEach((b) => {
    b.onclick = () => { THEME.set("font", b.dataset.fontPick); renderSettings(); };
  });
  $$("#setSeal [data-seal-pick]").forEach((b) => {
    b.onclick = () => { THEME.set("sealStyle", b.dataset.sealPick); renderSettings(); };
  });
  const mo = $("#setMotion");
  if (mo) mo.onchange = () => { THEME.set("motion", mo.checked); toast(mo.checked ? "动效开着" : "动效已关"); };
  const ha = $("#setHaptic");
  if (ha) ha.onchange = () => { state.settings.haptic = ha.checked; save(state); haptic("LIGHT"); };
  const no = $("#setNotify");
  if (no) no.onchange = () => {
    state.settings.notify = no.checked;
    save(state);
    if (!no.checked) { cancelAllNative(); toast("提醒不再弹通知（已经定的时间还在）"); }
    else {
      // 重新打开时补排未来的提醒；权限没给就不向系统下发。
      checkNotifyPermission(true).then((granted) => {
        if (granted && state.settings.notify !== false) rescheduleAll();
      });
    }
    renderSettings();
  };
  const perm = $("#setPerm");
  if (perm) perm.onclick = () => checkNotifyPermission(true);
  const ra = $("#setRemindAll");
  if (ra) ra.onclick = () => show("yan-remind");
  const pv = $("#setPrivacy");
  if (pv) pv.onclick = () => {
    const url = JIAN_CONFIG.privacyUrl;
    copy(url, "隐私政策网址已复制。粘到浏览器里打开");
    try { window.open(url, "_blank", "noopener"); } catch (_) { }
  };
  const ab = $("#setAbout");
  if (ab) ab.onclick = () => toast(`笺 ${JIAN_CONFIG.version} · ${dataWhere()} · 不联网也能用`, 3200);
  const rs = $("#setResetAll");
  if (rs) rs.onclick = () => { if (typeof resetAll === "function") resetAll(); };
}

/* ==================== 全局搜索 ==================== */

/** 一次搜遍五类东西。**不自己写一遍筛选**——每一类都调用它原本那个筛选函数
 *  （柜子问 closetQuery、言笺问 yanShown），否则就是第二份定义。
 *  这里只做一件事：把五类结果排成一组带标题的列表，命中处标 <mark>。 */
function searchAll(q) {
  const key = String(q || "").trim().toLowerCase();
  if (!key) return [];
  const hit = (s) => String(s || "").toLowerCase().includes(key);
  const out = [];

  // 柜子
  const clothes = (state.wardrobe || []).filter((w) =>
    hit(w.name) || hit(w.cat) || hit(w.brand) || hit(w.note) || (w.tags || []).some(hit) || (w.occasions || []).some(hit));
  if (clothes.length) out.push({ title: "柜子", kind: "yi", items: clothes.map((w) => ({
    text: w.name, sub: [w.cat, w.brand, w.worn ? `穿过 ${w.worn} 次` : ""].filter(Boolean).join(" · "),
    act: () => openItem(w.id),
  })) });

  // 言笺
  const yans = (state.yanCards || []).filter((c) => hit(c.line) || hit(c.k) || hit(c.who));
  if (yans.length) out.push({ title: "言笺", kind: "yan", items: yans.slice(0, 40).map((c) => ({
    text: c.line, sub: [c.k, c.who, c.done ? "已办" : ""].filter(Boolean).join(" · "),
    act: () => show("yan"),
  })) });

  // 笺册
  const slips = (state.album || []).filter((a) => hit(a.quote) || hit(a.text));
  if (slips.length) out.push({ title: "笺册", kind: "me", items: slips.slice(0, 30).map((a) => ({
    text: a.quote || String(a.text).slice(0, 40), sub: dayStr(a.t), act: () => show("me"),
  })) });

  // 菜谱（内置 + 自己录的）
  const recipes = (state.recipes || []).filter((r) => hit(r.name) || (r.items || []).some(hit) || (r.steps || []).some(hit));
  const dishHits = allDishes().filter((d) => hit(d.name) || (d.tags || []).some(hit));
  const merged = new Map();
  dishHits.forEach((d) => merged.set(d.name, { text: d.name, sub: d.kind || "菜库", act: () => openDish(d.name) }));
  recipes.forEach((r) => merged.set(r.name, { text: r.name, sub: "自己录的菜谱", act: () => openDish(r.name) }));
  if (merged.size) out.push({ title: "菜谱", kind: "wei", items: [...merged.values()].slice(0, 30) });

  // 摘录
  const digs = (state.digest || []).filter((d) => hit(d.text) || hit(d.from));
  if (digs.length) out.push({ title: "摘录", kind: "yan", items: digs.slice(0, 30).map((d) => ({
    text: d.text, sub: dayStr(d.t) + (d.from ? " · " + d.from : ""), act: () => show("yan"),
  })) });

  // 提醒
  const rems = (state.reminders || []).filter((r) => hit(r.text));
  if (rems.length) out.push({ title: "提醒", kind: "yan", items: rems.slice(0, 30).map((r) => ({
    text: r.text, sub: whenText(r.at) + (r.done ? " · 已办" : ""), act: () => show("yan-remind"),
  })) });

  return out;
}

function renderSearch() {
  const input = $("#globalSearch");
  const body = $("#searchBody");
  if (!input || !body) return;
  const h = $("#searchHist");
  if (h) {
    h.innerHTML = (state.searchHist || []).map((k) => `<button class="chip" data-shist="${esc(k)}">${esc(k)}</button>`).join("");
    $$("#searchHist [data-shist]").forEach((b) => {
      b.onclick = () => { input.value = b.dataset.shist; doSearch(b.dataset.shist); };
    });
  }
  const run = () => doSearch(input.value);
  input.oninput = run;
  input.onchange = run;
  if (input.value.trim()) doSearch(input.value);
  else body.innerHTML = `<h1 class="sr-only">找东西</h1>
    <div class="empty"><div class="empty-印" aria-hidden="true">找</div>
    搜一句话、一件衣服、一道菜、一个人名。<br>柜子、言笺、笺册、菜谱、摘录一次搜遍。</div>`;
}

function doSearch(q) {
  const body = $("#searchBody");
  if (!body) return;
  const key = String(q || "").trim();
  if (!key) { body.innerHTML = `<p class="tiny">还没有输入。</p>`; return; }
  const groups = searchAll(key);
  if (!groups.length) {
    body.innerHTML = `<h1 class="sr-only">找东西</h1>
      <div class="empty"><div class="empty-印" aria-hidden="true">找</div>
      没找到「${esc(key)}」。<br>试试更短的一段字。</div>`;
    return;
  }
  // 两处空态都补了那个只给读屏器的 h1（这一屏本来一个标题都没有）。
  // 有结果时也补上：同一个屏在两个分支里一个有标题一个没有，读屏器的标题列表会时有时无。
  body.innerHTML = `<h1 class="sr-only">找东西</h1>` + groups.map((g) => `
    <p class="tiny" style="margin:16px 0 8px">${esc(g.title)} · ${g.items.length}</p>
    <div class="list">${g.items.map((it, i) => `<button class="rowbtn" data-g="${esc(g.title)}" data-i="${i}">
      <span class="grow"><b>${markHit(it.text, key)}</b><span class="sub">${esc(it.sub || "")}</span></span>
    </button>`).join("")}</div>`).join("");
  groups.forEach((g) => {
    $$(`#searchBody [data-g="${CSS.escape(g.title)}"]`).forEach((b) => {
      b.onclick = () => {
        const it = g.items[Number(b.dataset.i)];
        // 记搜索历史：只在真的点开了一条时记（每敲一个字都记等于没记）
        const hist = state.searchHist || (state.searchHist = []);
        if (!hist.includes(key)) hist.push(key);
        while (hist.length > SEARCH_HIST) hist.shift();
        save(state);
        if (it && typeof it.act === "function") it.act();
      };
    });
  });
}

/** 命中处标一层印泥淡底。和言笺的 hitMark 同一套做法，但那个函数带筛选状态，
 *  这里只处理纯文本高亮，不共用（共用会把它绑死在言笺的 state 上）。 */
function markHit(text, key) {
  const s = String(text || "");
  const k = String(key || "").trim();
  if (!k) return esc(s);
  const i = s.toLowerCase().indexOf(k.toLowerCase());
  if (i < 0) return esc(s);
  return esc(s.slice(0, i)) + "<mark>" + esc(s.slice(i, i + k.length)) + "</mark>" + esc(s.slice(i + k.length));
}
