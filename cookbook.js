/** 笺 · 菜谱与做饭
 *
 *  味笺原来只有「排这桌」一个动作：贴菜单 → 看谁吃不了 → 复制群话术。做完就没事了。
 *  这一份把它接成一条完整的线：**想吃什么 → 有没有料 → 做完了没有 → 这周排哪一餐**。
 *
 *  数据分两层，这是刻意的：
 *  - **内置菜库**（DISHES，在 engine.js 里）只有名字 + 分类 + 忌口标签。
 *    它不进 state、不占配额、随包走——所以「有哪些菜」这件事不依赖用户填过什么。
 *  - **用户自己录的菜谱**（state.recipes）有食材、步骤、用时。**正文只允许用户自己写**：
 *    从网上抓菜谱既有版权问题，也和「不联网也能用」直接冲突。
 *  所以一道菜可能「有卡」也可能「只有名字」，界面上必须区分得开——
 *  没有卡的菜不许假装能展开步骤。
 *
 *  v0.6.0 的三条界面决定（都是「逛一座库」而不是「看一张表」）：
 *  1. 63 道菜按 荤/素/汤/主食 分组的**卡片网格**，一屏扫得到六到九道，组可折叠；
 *  2. 一切「选一道菜」的交互都走**屏内面板**：周菜单落格、今晚吃什么、新写一道。
 *     这一版之前用的是 prompt/confirm。它们**能用**（Capacitor 的 BridgeWebChromeClient
 *     真实现了 onJsPrompt/onJsConfirm），但三个毛病让它们不适合这里：
 *     ① 是 Material 弹框 + 英文 OK/Cancel，跟这张纸没有一毛钱关系；
 *     ② 阻塞式：框不关，WebView 一个字节都不动；
 *     ③ prompt 只能问一行字，装不下「一个能搜索的菜库面板」。
 *  3. 忌口一律问引擎（Engine.wei），不在这里另抄一份判定。
 */

/* ==================== 内置菜库的读法 ==================== */

/** 全库（按 engine.js 的 DISHES 结构拍平）。Engine.dishesOf 是只读导出。 */
function allDishes() {
  try {
    if (typeof Engine !== "undefined" && typeof Engine.dishesOf === "function") return Engine.dishesOf();
  } catch (e) { console.warn("dishesOf", e); }
  return [];
}

/** 一道菜的用时估计：内置库没有真实烹饪时长，按菜的类型给一个**保守估计**。
 *  这是一句估计，不是数据——所以界面上写「约」。用户自己录的优先。 */
function dishMinutes(d) {
  if (!d) return 0;
  if (d.minutes) return d.minutes;             // 用户自己录的，有真数
  const name = String(d.name || "");
  if (/凉拌|拍黄瓜|白灼|刺身|沙拉|皮蛋/.test(name)) return 10;
  if (/汤|炖|煲|焖|红烧|卤/.test(name)) return 60;
  if (/蒸|烤|焗/.test(name)) return 40;
  if (/炒|爆|熘|煎|拌|焯/.test(name)) return 20;
  return 30;
}

/** 这一桌（所有人忌口并起来）吃不吃得了这道菜，返回踩到的忌口词。
 *
 *  **口径必须与排桌完全同源。** 以前这里读 Engine.dishBans（只看菜库 tags + 菜名里的忌口词），
 *  它比排桌少两层判定：HIDDEN（「宫保」→花生）与 CHIP_MAP（「猪」→猪肉）。
 *  实测 63 道 × 11 种忌口里有 6 组不一致——「白灼菜心」对忌内脏的人，排桌说这是雷（心），
 *  菜谱页却写着「这桌都能吃」。同一件事两个答案，用户只会相信对自己不利的那个。
 *  所以这里直接问 Engine.wei：一次问一道，结果按（忌口组合, 菜名）缓存。 */
let dishBanMemo = new Map();
function dishBansFor(d, people) {
  const chips = [];
  (people || []).forEach((p) => (p.chips || []).forEach((c) => { if (!chips.includes(c)) chips.push(c); }));
  if (!chips.length) return [];
  const name = String((d && d.name) || d || "").trim();
  if (!name) return [];
  return bansByName(name, chips);
}
/** 实际的那一次询问 + 缓存。chips 排序只是为了让同一组忌口有同一个键。 */
function bansByName(name, chips) {
  const key = chips.slice().sort().join(",") + "|" + name;
  if (dishBanMemo.has(key)) return dishBanMemo.get(key).slice();
  let bans = [];
  try {
    const r = Engine.wei(name, [{ name: "这桌", chips }], "friends");
    bans = (r.boom && r.boom[0]) ? String(r.boom[0].why).split(" / ") : [];
  } catch (e) { console.warn("dishBans", e); bans = []; }
  if (dishBanMemo.size > 240) dishBanMemo.clear();   // 上限只是防止换了忌口之后缓存无限长
  dishBanMemo.set(key, bans);
  return bans.slice();
}
function dishSafeFor(d, people) {
  return dishBansFor(d, people).length === 0;
}
/** 这道菜**谁**吃不了：[{name, why}]。逐个人各问一次——排桌问的是「并起来」，这里问的是「是谁」。
 *  代价是一次详情页最多 12 问（缓存命中后近乎免费），换来「小周 不能吃：辣」这种能开口的句子。 */
function dishWhoCannot(d, people) {
  const name = String((d && d.name) || d || "").trim();
  const out = [];
  (people || []).forEach((p) => {
    const chips = (p.chips || []).filter((c) => CHIPS.includes(c));
    const why = chips.length ? bansByName(name, chips) : [];
    if (why.length) out.push({ name: p.name, why });
  });
  return out;
}

/** 命名的那个「正好是库里这一道」：做链接、做「有没有卡」的判断都只认全等——
 *  用包含匹配会把「白切鸡1」链到「白切鸡」上，那是给用户看一道不是他点开的菜。 */
function exactDish(name) {
  const n = String(name || "").trim();
  if (!n) return null;
  return allDishes().find((d) => d.name === n) || null;
}

/** 找一道菜：先按名字精确，再按包含（用户可能写「西红柿炒蛋」而库里是「西红柿炒鸡蛋」）。 */
function findDish(name) {
  const n = String(name || "").trim();
  if (!n) return null;
  const all = allDishes();
  return all.find((d) => d.name === n)
    || all.find((d) => n.includes(d.name) || d.name.includes(n))
    || null;
}
/** 用户自己录的那一道（有步骤/用时的）。 */
function findRecipe(name) {
  const n = String(name || "").trim();
  return (state.recipes || []).find((r) => r.name === n) || null;
}

/* ==================== 做过的菜 ==================== */

/** 菜名 → {n: 做过几次, last: 上次什么时候}。一次性算完，
 *  免得 63 张卡各扫一遍 cookLog（每次重画都来一遍）。 */
function cookLogStats() {
  const m = new Map();
  (state.cookLog || []).forEach((c) => {
    const k = String(c.name || "");
    if (!k) return;
    const e = m.get(k) || { n: 0, last: 0 };
    e.n += 1;
    if (Number(c.t) > e.last) e.last = Number(c.t);
    m.set(k, e);
  });
  return m;
}

/* ==================== 做菜那一页（菜谱库） ==================== */

let dishQuery = "";
let cookPanel = "";        // "" | "new"：屏内「自己写一道」面板
/** 分组折叠。界面态，不进 state：换个设备不该记住「我把汤收起来了」。
 *  默认把主食收起来——它是最不像「菜」的一组，收着才能一屏看见更多荤素。 */
let cookOpen = null;
let wheelResult = null;
let wheelFresh = false;

const COOK_GROUPS = ["荤", "素", "汤", "主食", "自己录的"];

function cookGroupOf(d) {
  return d.mine ? "自己录的" : (d.kind || "其他");
}

/** 搜索命中：名字 / 忌口标签 / 自己录的食材与步骤。 */
function dishHit(d, q) {
  const key = q.toLowerCase();
  if (String(d.name || "").toLowerCase().includes(key)) return true;
  if ((d.tags || []).some((t) => String(t).toLowerCase().includes(key))) return true;
  const r = findRecipe(d.name);
  if (r) {
    if ((r.items || []).some((x) => String(x).toLowerCase().includes(key))) return true;
    if ((r.steps || []).some((x) => String(x).toLowerCase().includes(key))) return true;
  }
  return false;
}

/** 菜谱卡：一张卡 = 一道菜。卡上只说三件事——名字、约多久、跟这一桌的关系。
 *  做过的菜多一行「做过 N 次」；这桌吃不了的菜多一行忌口。 */
function dishCardHTML(d, stats, people) {
  const r = findRecipe(d.name);
  const mins = dishMinutes({ ...d, minutes: r && r.minutes });
  const made = stats.get(d.name);
  const bans = dishBansFor(d, people);
  const steps = r && (r.steps || []).length;
  return `<button class="dish-card${made ? " is-made" : ""}${bans.length ? " is-ban" : ""}${
    steps ? " has-steps" : ""}" data-dish="${esc(d.name)}" type="button">
    <b class="dc-name serif">${esc(d.name)}</b>
    <span class="dc-meta">约 ${mins} 分钟${steps ? " · 有步骤" : ""}</span>
    ${made ? `<span class="dc-flag">做过 ${made.n} 次</span>` : ""}
    ${bans.length ? `<span class="dc-ban">这桌吃不了 · ${esc(bans.join("、"))}</span>` : ""}
  </button>`;
}

function renderCook() {
  const list = $("#cookList");
  if (!list) return;
  const search = $("#dishSearch");
  if (search && search.value !== dishQuery) search.value = dishQuery;
  lockCookBindings();

  const all = allDishes();
  const mine = state.recipes || [];
  const stats = cookLogStats();
  const q = dishQuery.trim();
  // 用户自己录的、菜库里没有名字的那几道，单独一组（它们同样是一张卡）
  const mineOnly = mine
    .filter((r) => !all.some((d) => d.name === r.name))
    .map((r) => ({ name: r.name, kind: "自己录的", tags: [], mine: true }));
  const rows = all.concat(mineOnly);
  const hit = q ? rows.filter((d) => dishHit(d, q)) : rows;
  if (cookOpen === null) cookOpen = { 荤: true, 素: true, 汤: true, 主食: false, 自己录的: true };
  // 搜索时一律摊开：用户是来找东西的，不是来逛的。
  // 「自己录的」也要能折——它和别的组长得一模一样（同一枚分组头），
  // 长成按钮却点不动，就是「摆了一枚按了没反应的控件」。
  const isOpen = (k) => (q ? true : cookOpen[k] !== false);

  const cooked = new Set((state.cookLog || []).map((c) => c.name));
  const withSteps = rows.filter((d) => {
    const r = findRecipe(d.name);
    return r && ((r.steps || []).length || (r.items || []).length);
  }).length;
  const bansN = rows.filter((d) => dishBansFor(d, state.people).length > 0).length;

  const head = `<div class="cook-sum">
      <p class="cook-sum-line"><b class="serif">${all.length}</b> 道在菜库里<span class="tiny"> · 有食材或步骤的 ${withSteps} 道</span></p>
      <p class="tiny">${bansN
      ? `这桌的忌口会挡住 ${bansN} 道——卡上写着挡在哪一项。`
      : "菜谱正文只由你自己写。没写的那些，这页只给名字与用时估计。"}</p>
    </div>`;

  const groups = COOK_GROUPS.map((k) => ({ kind: k, list: hit.filter((d) => cookGroupOf(d) === k) }))
    .filter((g) => g.list.length);

  const groupsHTML = groups.map((g) => {
    const open = isOpen(g.kind);
    const madeHere = g.list.filter((d) => cooked.has(d.name)).length;
    return `<section class="dish-group" data-group="${esc(g.kind)}">
      <button class="dish-group-head" data-dgtoggle="${esc(g.kind)}" type="button" aria-expanded="${open}">
        <span class="dgh-mark serif" aria-hidden="true">${esc(g.kind === "自己录的" ? "录" : g.kind)}</span>
        <span class="dgh-text"><b class="serif">${esc(g.kind)}</b>
          <span class="tiny">${g.list.length} 道${madeHere ? ` · 做过 ${madeHere}` : ""}</span></span>
        <span class="dgh-toggle" aria-hidden="true">${open ? "－" : "＋"}</span>
      </button>
      <div class="dish-grid"${open ? "" : " hidden"}>
        ${g.list.map((d) => dishCardHTML(d, stats, state.people)).join("")}
      </div>
    </section>`;
  }).join("");

  list.innerHTML = head
    + (wheelResult ? wheelBoxHTML() : "")
    + (cookPanel === "new" ? newRecipePanelHTML() : "")
    + (groupsHTML || `<div class="empty"><div class="empty-印" aria-hidden="true">味</div>
        ${q ? `没有找到「${esc(q)}」。` : "菜库里还没有这一类。"}<br>可以自己写一道。</div>`);

  bindCook();
  wheelFresh = false;
}

/** 页签里那几枚常驻控件的绑定。app.js 在 boot 里绑过一次，这里每次重画再绑一次——
 *  整片 innerHTML 重建之后旧节点被丢弃，不重绑就是「搜过一次之后按钮全死」。 */
function lockCookBindings() {
  bindWeiChrome();
  const ds = $("#dishSearch");
  if (ds) ds.oninput = () => { dishQuery = ds.value; renderCook(); };
}

/** 味笺这一屏的两枚常驻按钮：#wheelBtn 与 #newRecipe。
 *
 *  **为什么单独成一个函数、还要在 renderWei() 里也调一次**：这两枚是 index.html 里的
 *  常驻 DOM（不随页签销毁），而 app.js 在 boot 里给它们各绑过一个 handler。其中
 *  #newRecipe 原来那一个是 `prompt("这道菜叫什么？")`。
 *
 *  注意 prompt 在这个壳里**是能用的**（Capacitor 的 BridgeWebChromeClient 真实现了
 *  onJsPrompt：一个 Material AlertDialog + 一个 EditText + 英文 OK/Cancel）。换掉它不是
 *  因为按下去没反应，而是因为它和这张纸不是同一件东西，而且阻塞 WebView、
 *  也只能问一行字——这里要的是「一个能继续填食材与步骤」的入口。
 *
 *  覆盖是靠 `el.onclick = …` 这个**赋值**而不是 addEventListener：赋值把属性位置上
 *  原来那个函数整个换掉，不会留两条 handler 同时挂着（若当年用的是 addEventListener，
 *  这里就得先 removeEventListener，否则一次点击会既开面板又弹原生框）。
 *  这一点由 test/wei_v06.playwright.py 里「点一次只多一个面板、prompt 计数为 0」钉住。 */
function bindWeiChrome() {
  const wb = $("#wheelBtn");
  if (wb) wb.onclick = () => spinWheel();
  const nr = $("#newRecipe");
  if (nr) nr.onclick = () => {
    // 从别的页签点到它（#newRecipe 只在「做菜」页签里可见，但键盘/深链/测试都可能先触发）：
    // 先把页签切到位，再开面板——否则面板会画进一个看不见的容器里。
    if (document.querySelector("#weiPaneCook") && document.querySelector("#weiPaneCook").hidden) {
      if (typeof setWeiTab === "function") setWeiTab("cook");
      else { cookPanel = "new"; renderCook(); return; }
    }
    cookPanel = cookPanel === "new" ? "" : "new";
    renderCook();
  };
}

function bindCook() {
  $$("#cookList [data-dish]").forEach((b) => { b.onclick = () => openDish(b.dataset.dish); });
  $$("#cookList [data-dgtoggle]").forEach((b) => {
    b.onclick = () => {
      const k = b.dataset.dgtoggle;
      if (!cookOpen) cookOpen = {};
      cookOpen[k] = cookOpen[k] === false;
      renderCook();
    };
  });
  const again = $("#cookList [data-wheel='again']");
  if (again) again.onclick = () => spinWheel();
  const keep = $("#cookList [data-wheel='keep']");
  if (keep) keep.onclick = () => wheelKeep(wheelResult && wheelResult.name);
  const open = $("#cookList [data-wheel='open']");
  if (open) open.onclick = () => openDish(wheelResult && wheelResult.name);
  const toPlan = $("#cookList [data-wheel='plan']");
  if (toPlan) toPlan.onclick = () => setWeiTab("plan");
  // 「自己写一道」面板
  const mk = $("#cookList #nrGo");
  if (mk) mk.onclick = () => {
    const el = $("#cookList #nrName");
    const name = String((el && el.value) || "").trim().slice(0, 30);
    if (!name) { toast("先给这道菜起个名字"); if (el) el.focus(); return; }
    cookPanel = "";
    openRecipeEditor(name);
  };
  const nrCancel = $("#cookList #nrCancel");
  if (nrCancel) nrCancel.onclick = () => { cookPanel = ""; renderCook(); };
  const nrName = $("#cookList #nrName");
  if (nrName) {
    nrName.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); if (mk) mk.click(); } };
  }
}

/** 「自己写一道」：先只问名字（一步一个问题），再进编辑器。
 *  以前这一枚在 app.js 里用 `prompt("这道菜叫什么？")`。那个框能用，但它是 Material 的、
 *  阻塞的、只能问一行字；而这里问完名字下一步就是填食材与步骤，接不上。 */
function newRecipePanelHTML() {
  return `<div class="cook-panel" id="newRecipePanel">
    <p class="tiny sheet-cap">新写一道</p>
    <label class="field"><span>菜名</span>
      <input type="text" id="nrName" maxlength="30" placeholder="比如：番茄牛腩" autocomplete="off" /></label>
    <div class="row">
      <button class="btn ghost" id="nrCancel" type="button">算了</button>
      <button class="btn" id="nrGo" type="button">接着写食材与步骤</button>
    </div>
  </div>`;
}

/* ==================== 菜谱详情 ==================== */

let dishSel = "";

function openDish(name) {
  dishSel = String(name || "").trim();
  if (!dishSel) return;
  show("wei-dish");
}

function renderWeiDish() {
  const body = $("#dishBody");
  if (!body) return;
  const lib = findDish(dishSel);
  const d = lib || { name: dishSel, kind: "其他", tags: [] };
  const r = findRecipe(d.name);
  const mins = dishMinutes({ ...d, minutes: r && r.minutes });
  const made = cookLogStats().get(d.name) || { n: 0, last: 0 };
  const who = dishWhoCannot(d, state.people);
  const peopleN = (state.people || []).length;
  const dishes = (r && r.steps) ? r.steps.length : 0;
  const items = (r && r.items) ? r.items.length : 0;

  // 「和这桌人的关系」：这一块是详情页的正文，不是附注。说清是谁、不能吃哪样。
  const rel = peopleN
    ? (who.length
      ? `<p class="dish-rel-bad">${who.map((x) => `${esc(x.name)}不能吃（${esc(x.why.join("、"))}）`).join("；")}</p>
         <p class="tiny">整桌一起点时，这道会排进「有人不能吃」那一类。</p>`
      // 不说「都能吃」：笺只知道菜名和菜库记着的成分，不知道后厨的砧板和油。
      // 「按名字看没问题」是它真能保证的那一件事——把承诺说小一点，它才是真的。
      : `<p class="dish-rel-ok">按名字看，这 ${peopleN} 个人没有踩到你记的忌口。</p>`)
    : `<p class="tiny">这桌还没记人，看不出谁吃不了。到「排桌」那一页把人加上。</p>`;

  const lastLine = made.n
    ? `做过 ${made.n} 次${made.last ? ` · 上次 ${relativeDays(made.last) || "今天"}` : ""}`
    : "还没做过";

  const week = currentWeek(false);
  const todayIdx = weekIdx(Date.now());
  const slotBtns = WEEK_NAMES.map((n, i) => {
    const d0 = week && week.days[i] ? week.days[i] : { noon: [], night: [] };
    return `<div class="dish-week-row">
      <span class="dwr-day${i === todayIdx ? " today" : ""}">周${n}${i === todayIdx ? " · 今天" : ""}</span>
      ${WEEK_SLOTS.map((s) => {
      const arr = (d0[s.k] || []);
      return `<button class="dwr-slot${arr.length ? " has" : ""}" data-dishweek="${i}:${s.k}" type="button"
          aria-label="加到周${n}${s.label}${arr.length ? `，现在 ${arr.length} 道` : "，这一格空着"}">${s.label}${arr.length ? ` · ${arr.length}` : ""}</button>`;
    }).join("")}
    </div>`;
  }).join("");

  body.innerHTML = `
    <p class="meta">JIAN · WEI</p>
    <div class="detail-head" style="margin-top:8px">
      <span class="detail-swatch dish-seal serif" aria-hidden="true">味</span>
      <div class="dh-main">
        <h2>${esc(d.name)}</h2>
        <p class="tiny">${esc(d.kind || "菜")}${mins ? ` · 约 ${mins} 分钟` : ""} · ${lastLine}</p>
      </div>
    </div>
    ${(d.tags || []).length ? `<div class="tagrow" style="margin-top:10px">${(d.tags || [])
      .map((t) => `<span class="tag">含 ${esc(t)}</span>`).join("")}</div>` : ""}

    <div class="rule" style="margin:16px 0"></div>
    <p class="tiny sheet-cap">和这桌人的关系</p>
    ${rel}

    <div class="rule" style="margin:16px 0"></div>
    ${r ? `
      <p class="tiny">${r.serves ? `${r.serves} 人份` : ""}${r.level ? ` · 难度 ${"★".repeat(r.level)}` : ""}</p>
      <p class="tiny" style="margin-top:12px">食材${items ? ` · ${items} 样` : ""}</p>
      <div class="dish-items">${items
        ? r.items.map((it) => `<span class="tag">${esc(it)}</span>`).join("")
        : `<span class="tiny">还没写食材。</span>`}</div>
      <p class="tiny" style="margin-top:16px">步骤${dishes ? ` · ${dishes} 步` : ""}</p>
      <ol class="steps">${dishes
        ? r.steps.map((s) => `<li>${esc(s)}</li>`).join("")
        : `<li class="tiny">还没写步骤。</li>`}</ol>
      <div class="row" style="margin-top:16px">
        <button class="btn ghost" id="editRecipe" type="button">改菜谱</button>
        <button class="btn ghost" id="toMarket" type="button">去记要买</button>
      </div>
    ` : `
      <p class="quote serif">这道菜在菜库里，但还没有步骤。</p>
      <p class="tiny">菜谱正文只由你自己写：从网上抓既有版权问题，也和「不联网也能用」冲突。</p>
      <div class="space"></div>
      <button class="btn ghost wide" id="writeRecipe" type="button">写这道菜的步骤</button>
    `}

    <div class="rule" style="margin:16px 0"></div>
    <p class="tiny sheet-cap">加进这周的某一餐</p>
    <div class="dish-week">${slotBtns}</div>

    <div class="space"></div>
    <button class="btn wide" id="cookIt" type="button">今天做了这道</button>
    <p class="tiny" style="margin-top:8px">${made.n ? `按下去记第 ${made.n + 1} 次。` : "记一笔，这一道就算做过一次。"}</p>`;

  const write = $("#writeRecipe");
  if (write) write.onclick = () => openRecipeEditor(d.name);
  const edit = $("#editRecipe");
  if (edit) edit.onclick = () => openRecipeEditor(d.name);
  const mk = $("#toMarket");
  if (mk) mk.onclick = () => {
    const r2 = findRecipe(d.name);
    if (!r2 || !(r2.items || []).length) { toast("这道菜还没写食材，没东西可买"); return; }
    const added = addMarketItems(r2.items, d.name);
    toast(added ? `已把 ${added} 样放进买菜清单` : "这几样清单里都有");
    show("wei");
    setWeiTab("market");
  };
  $$("#dishBody [data-dishweek]").forEach((b) => {
    b.onclick = () => {
      const [i, slot] = String(b.dataset.dishweek).split(":");
      if (addToWeek(Number(i), slot, d.name)) renderWeiDish();
    };
  });
  const cookIt = $("#cookIt");
  if (cookIt) cookIt.onclick = () => {
    state.cookLog.push({ id: "c" + newId().slice(1), name: d.name, t: Date.now(), stars: 0,
      note: "", people: (state.people || []).length });
    if (state.cookLog.length > COOK_CAP) state.cookLog = state.cookLog.slice(-COOK_CAP);
    save(state);
    logEvent("cook", "wei", d.name);
    haptic("MEDIUM");
    renderWeiDish();
    paintTabCounts();
    toast(`记下了：今天做了 ${d.name}`);
  };
}

/** 菜谱编辑器：名字固定（从菜名进来），填用时/份量/食材/步骤。 */
function openRecipeEditor(name) {
  const r = findRecipe(name) || { name, minutes: 0, level: 0, serves: 2, items: [], steps: [] };
  dishSel = name;
  // 从「做菜」页直接写一道时，先把这张纸翻出来（不然往一个看不见的屏里画）
  if (!document.querySelector("#wei-dish.on")) show("wei-dish");
  const body = $("#dishBody");
  body.innerHTML = `
    <p class="meta">JIAN · WEI</p>
    <h1 class="serif" style="font-size:26px;margin:6px 0 12px">${esc(name)}</h1>
    <p class="tiny">这一步写的是你自己的做法。写到哪儿算哪儿，下次再补也行。</p>
    <div class="space"></div>
    <div class="field-row">
      <label class="field"><span>用时（分钟）</span>
        <input type="text" id="rcMinutes" inputmode="numeric" value="${r.minutes || ""}" placeholder="30"></label>
      <label class="field"><span>几人份</span>
        <input type="text" id="rcServes" inputmode="numeric" value="${r.serves || 2}"></label>
    </div>
    <label class="field"><span>难度（0-3）</span>
      <input type="text" id="rcLevel" inputmode="numeric" value="${r.level || 0}"></label>
    <label class="field"><span>食材（一行一样）</span>
      <textarea id="rcItems" placeholder="鸡蛋 2 个&#10;番茄 1 个">${esc((r.items || []).join("\n"))}</textarea></label>
    <label class="field"><span>步骤（一行一步）</span>
      <textarea id="rcSteps" placeholder="番茄切块&#10;鸡蛋打散">${esc((r.steps || []).join("\n"))}</textarea></label>
    <div class="row">
      <button class="btn ghost" id="rcCancel" type="button">取消</button>
      <button class="btn" id="rcSave" type="button">存下</button>
    </div>`;
  $("#rcCancel").onclick = () => renderWeiDish();
  $("#rcSave").onclick = () => {
    const lines = (id) => String($(id).value || "").split("\n").map((x) => x.trim()).filter(Boolean);
    const rec = {
      id: r.id || "k" + newId().slice(1),
      name,
      minutes: Math.max(0, Math.min(600, Number($("#rcMinutes").value) || 0)),
      serves: Math.max(1, Math.min(20, Number($("#rcServes").value) || 2)),
      level: Math.max(0, Math.min(3, Number($("#rcLevel").value) || 0)),
      items: lines("#rcItems").slice(0, 30),
      steps: lines("#rcSteps").slice(0, 30),
      t: Date.now(),
    };
    const i = (state.recipes || []).findIndex((x) => x.name === name);
    if (i >= 0) state.recipes[i] = rec;
    else {
      state.recipes.push(rec);
      if (state.recipes.length > RECIPE_CAP) state.recipes = state.recipes.slice(-RECIPE_CAP);
    }
    dishBanMemo.clear();        // 改了菜名/食材之后，「这桌能不能吃」要重问一遍
    save(state);
    logEvent("recipe", "wei", name);
    renderWeiDish();
    toast(rec.items.length || rec.steps.length ? "菜谱存下了" : "存下了（食材和步骤还空着）");
  };
}

/* ==================== 今晚吃什么（转盘） ==================== */

/** 抽签的池子：先保证这桌人能吃；再从「没做过」里抽。 */
function wheelPool() {
  const all = allDishes();
  const made = new Set((state.cookLog || []).map((c) => c.name));
  const safe = all.filter((d) => dishSafeFor(d, state.people));
  const fresh = safe.filter((d) => !made.has(d.name));
  return { all, safe, fresh, made };
}

function wheelBoxHTML() {
  const w = wheelResult;
  if (!w) return "";
  if (w.empty) {
    return `<div class="wheel-box" id="wheelBox">
      <div class="wheel-empty">
        <p class="serif" style="font-size:20px">抽不出来</p>
        <p class="tiny">${esc(w.why)}</p>
        <div class="row" style="margin-top:10px">
          <button class="btn ghost" data-wheel="again" type="button">再试一次</button>
          <button class="btn ghost" data-wheel="plan" type="button">去核对这些人的忌口</button>
        </div>
      </div>
    </div>`;
  }
  const dy = Number(w.dy) || 0;
  const last = (w.col || []).length - 1;
  return `<div class="wheel-box" id="wheelBox">
    <div class="wheel-stage">
      <div class="wheel-track${wheelFresh ? " spin" : ""}"
           style="--wheel-dy:-${dy}px;transform:translateY(-${dy}px)">
        ${(w.col || []).map((n, i) => `<span class="${i === last ? "pick" : ""}">${esc(n)}</span>`).join("")}
      </div>
      <div class="wheel-pick" aria-hidden="true"></div>
    </div>
    <div class="wheel-out">
      <p class="tiny">今晚就它？</p>
      <p class="wheel-name serif" id="wheelPick">${esc(w.name)}</p>
      <p class="tiny">${esc(w.sub)}</p>
      <div class="row" style="margin-top:12px">
        <button class="btn ghost" data-wheel="again" type="button">再抽一次</button>
        <button class="btn" data-wheel="keep" type="button">就它了</button>
      </div>
      <div class="bar" style="justify-content:flex-start;margin:10px 0 0">
        <button class="chip" data-wheel="open" type="button">看这道</button>
      </div>
    </div>
  </div>`;
}

function spinWheel() {
  const { all, safe, fresh } = wheelPool();
  if (!all.length) { toast("菜库是空的"); return; }
  if (!safe.length) {
    wheelResult = { empty: true,
      why: `这桌的忌口盖住了全部 ${all.length} 道菜。先核对一下每个人的忌口，或者换一桌人再抽。` };
    renderCook();
    haptic("LIGHT");
    return;
  }
  const pool = fresh.length ? fresh : safe;
  const pick = pool[Math.floor(Math.random() * pool.length)] || pool[0];
  // 滚动那一列：垫几道，最后落到抽中的那道。样式里一格 54px。
  const col = [];
  const seedPool = pool.length >= 2 ? pool : all;
  for (let i = 0; i < 12; i++) col.push(seedPool[i % seedPool.length].name);
  col.push(pick.name);
  const dy = Math.max(0, 54 * (col.length - 1) - 68);
  const madeN = (state.cookLog || []).filter((c) => c.name === pick.name).length;
  const mins = dishMinutes(pick);
  const r = findRecipe(pick.name);
  const sub = [mins ? `约 ${mins} 分钟` : "", pick.kind || "",
    madeN ? `做过 ${madeN} 次` : "没做过",
    r ? "有步骤" : "只有名字",
    fresh.length ? `从 ${fresh.length} 道没做过的里抽` : `从 ${safe.length} 道能吃的里抽`]
    .filter(Boolean).join(" · ");
  wheelResult = { name: pick.name, sub, col, dy };
  wheelFresh = true;
  renderCook();
  haptic("LIGHT");
}

/** 「就它了」：排进这一周第一个空着的那一餐。满了就照实说。 */
function wheelKeep(name) {
  const nm = String(name || "").trim();
  if (!nm) { toast("还没有抽到菜"); return; }
  const todayIdx = weekIdx(Date.now());
  const w = currentWeek(false);
  for (let step = 0; step < 7; step++) {
    const i = (todayIdx + step) % 7;
    for (const s of WEEK_SLOTS) {
      const arr = w && w.days[i] ? (w.days[i][s.k] || []) : [];
      if (arr.length < 4 && !arr.includes(nm)) {
        addToWeek(i, s.k, nm);
        return;
      }
    }
  }
  // 一周都排满了：不静默，也不偷偷挤掉别人的菜
  toast("这周的午饭晚饭都排满了，先删掉一两道再排");
}

/* ==================== 这周（一周菜单） ==================== */

const WEEK_NAMES = ["一", "二", "三", "四", "五", "六", "日"];
const WEEK_SLOTS = [{ k: "noon", label: "午饭" }, { k: "night", label: "晚饭" }];
let weekPick = null;      // {day, slot}：正在给哪一格挑菜
let weekQuery = "";       // 挑菜面板里的搜索词（临时过滤，不进 state）

/** 本周的周一 0 点。 */
function weekStart(ts) {
  const t = startOfDay(ts || Date.now());
  return addDays(t, -weekIdx(t));
}
/** 拿到当前这张周菜单（没有就建一张空的，但不落盘——落盘发生在真正填菜的时候）。 */
function currentWeek(create) {
  const start = weekStart();
  let w = (state.weeks || []).find((x) => x.start === start);
  if (!w && create) {
    w = { start, days: Array.from({ length: 7 }, () => ({ noon: [], night: [] })), note: "" };
    state.weeks.push(w);
    if (state.weeks.length > WEEK_CAP) state.weeks = state.weeks.slice(-WEEK_CAP);
  }
  return w || null;
}

/** 这一周排了几道（含重复）。空着返回 0。 */
function weekDishCount(w) {
  if (!w) return 0;
  let n = 0;
  (w.days || []).forEach((d) => { n += (d.noon || []).length + (d.night || []).length; });
  return n;
}

/** 一周菜单的那块纸。两个地方共用：味笺「这周」页签（#weekGrid）与整周摊开屏（#weekBody）。
 *  一份生成器、两处挂载——不然两个界面上「这周排了几道」迟早对不上。 */
function weekPaneHTML(opts) {
  const o = opts || {};
  const w = currentWeek(false);
  const todayIdx = weekIdx(Date.now());
  const total = weekDishCount(w);
  const dishDays = (w && w.days ? w.days : [])
    .filter((d) => (d.noon || []).length + (d.night || []).length).length;
  const shop = o.full ? weekShopping() : null;

  const dayHTML = WEEK_NAMES.map((n, i) => {
    const d = w && w.days[i] ? w.days[i] : { noon: [], night: [] };
    const isToday = i === todayIdx;
    return `<div class="wk-day${isToday ? " today" : ""}">
      <div class="wk-day-head">
        <b class="serif">周${n}</b>
        <span class="tiny">${shortDay(addDays(weekStart(), i))}${isToday ? " · 今天" : ""}</span>
      </div>
      ${WEEK_SLOTS.map((s) => {
      const arr = d[s.k] || [];
      // aria-label 里的菜名必须和下面那行正文一样过 esc()：菜名可以是用户自己写的
      // （「自己写一道」最多 40 张），里面出现尖括号或引号时，不转义就会当场把
      // 这个属性咬断——属性一断，后面的 type/class 全被当成新的属性解析。
      // 同一个函数里正文转了、属性没转，正是最难被「看起来对了」骗过去的那种。
      const dishNames = arr.join("、");
      return `<button class="wk-slot${arr.length ? " has" : ""}" data-wkpick="${i}:${s.k}" type="button"
          aria-label="周${n}${s.label}${arr.length ? "：" + esc(dishNames) : "，空着，点一下排菜"}">
        <span class="wk-cap">${s.label}</span>
        <span class="wk-body">${arr.length ? esc(dishNames) : "还没排"}</span>
        <span class="wk-plus" aria-hidden="true">＋</span>
      </button>`;
    }).join("")}
    </div>`;
  }).join("");

  const shopHTML = shop ? `<div class="wk-shop">
      <p class="tiny sheet-cap">这周要买</p>
      ${shop.items.length
      ? `<div class="dish-items">${mergeShopPreview(shop.items).map((x) =>
        `<span class="tag">${esc(x)}</span>`).join("")}</div>`
      : `<p class="tiny">这周排的菜还都没有食材记录。</p>`}
      ${shop.missing.length ? `<p class="tiny" style="margin-top:8px">${shop.missing.length} 道还没写食材：${esc(shop.missing.join("、"))}</p>` : ""}
      ${shop.repeat.length ? `<p class="tiny" style="margin-top:6px">重复排的：${esc(shop.repeat.join("、"))}（食材只算一次）</p>` : ""}
    </div>` : "";

  const pick = weekPick ? weekPickHTML(weekPick) : "";
  return `<div class="week-pane${o.full ? " full" : ""}">
    ${o.full ? `<h1 class="sr-only">这周</h1>` : ""}
    <div class="wk-top">
      <div>
        <p class="tiny">${shortDay(weekStart())} — ${shortDay(addDays(weekStart(), 6))}</p>
        <p class="wk-sum"><b class="serif">${total}</b> 道排在这周${total ? `<span class="tiny"> · ${dishDays} 天有安排</span>` : " · 还空着"}</p>
      </div>
      ${o.full ? "" : `<button class="chip" data-weekfull="1" type="button">整周摊开</button>`}
    </div>
    ${pick}
    <div class="wk-days">${dayHTML}</div>
    ${shopHTML}
    <div class="space"></div>
    <div class="row">
      <button class="btn ghost" data-weekmarket="1" type="button">这一周变成买菜清单</button>
    </div>
    <p class="tiny" style="margin-top:8px">清单只算你写过食材的菜；没写的会当场告诉你哪几道还没写。</p>
  </div>`;
}

/** 挑菜面板：点某天某格之后出现在周格上面。
 *  **不用 prompt/confirm**：它们在这个壳里能用（Capacitor 真实现了 onJsPrompt/onJsConfirm），
 *  但一个只能问一行字、还是阻塞式的 Material 弹框，装不下「一个能搜索的菜库面板」。
 *  这一格要的是「搜 → 看见约多久、这桌谁不能吃 → 点一下落格」，三件事 prompt 一件都做不到。
 *  面板里能做三件事：搜、选一道落进那一格、把这一格已有的某道删掉。 */
function weekPickHTML(pk) {
  const w = currentWeek(false);
  const day = Number(pk.day), slot = pk.slot;
  const arr = w && w.days[day] ? (w.days[day][slot] || []) : [];
  const q = weekQuery.trim();
  const all = allDishes();
  const mineOnly = (state.recipes || []).filter((r) => !all.some((d) => d.name === r.name))
    .map((r) => ({ name: r.name, kind: "自己录的", tags: [], mine: true }));
  const pool = all.concat(mineOnly);
  const rows = (q ? pool.filter((d) => dishHit(d, q)) : pool).slice(0, 120);
  const label = `周${WEEK_NAMES[day]} · ${slot === "noon" ? "午饭" : "晚饭"}`;
  return `<div class="wk-pick">
    <div class="wkr-head">
      <b class="serif">${label}</b>
      <button class="chip" data-wkclose="1" type="button">收起</button>
    </div>
    ${arr.length ? `<p class="tiny">这一格已经有 ${arr.length} 道（一天最多四道）：</p>
      <div class="chips" style="margin:6px 0 10px">${arr.map((n, k) =>
      `<button class="chip wk-rm" data-wkrm="${day}:${slot}:${k}" type="button" aria-label="从${label}删掉 ${esc(n)}">${esc(n)} ✕</button>`).join("")}</div>`
      : `<p class="tiny">这一格还空着。</p>`}
    <label class="field" style="margin-top:8px"><span>从菜库里挑一道</span>
      <input type="text" class="wk-search" value="${esc(weekQuery)}"
             placeholder="搜菜名、食材、忌口" autocomplete="off" aria-label="搜菜库里的一道菜" /></label>
    <div class="wk-opt-wrap">
      ${rows.length ? rows.map((d) => {
      const mins = dishMinutes(d);
      const bad = dishBansFor(d, state.people);
      return `<button class="wk-opt${bad.length ? " bad" : ""}" data-wkadd="${esc(d.name)}" type="button">
          <b class="serif">${esc(d.name)}</b>
          <span class="tiny">约 ${mins} 分钟${bad.length ? ` · 这桌吃不了（${esc(bad.join("、"))}）` : ""}</span>
        </button>`;
    }).join("") : `<p class="tiny">没有搜到。换个词，或者先自己写一道。</p>`}
    </div>
  </div>`;
}

/** 把食材行按「同名同单位」粗并一遍给预览看（真合并发生在 addMarketItems，这里有 bug 也不会伤到数据）。 */
function mergeShopPreview(items) {
  const out = [];
  (items || []).forEach((raw) => {
    const s = String(raw || "").trim();
    if (!s) return;
    if (!out.includes(s)) out.push(s);
  });
  return out.slice(0, 24);
}

/** 往某一天某一餐加一道菜。返回是否真的加上了（调用方据此决定要不要重画）。 */
function addToWeek(dayIdx, slot, name) {
  const d0 = Number(dayIdx);
  const nm = String(name || "").trim().slice(0, 20);
  const s = slot === "noon" ? "noon" : "night";
  if (!Number.isFinite(d0) || d0 < 0 || d0 > 6) return false;
  if (!nm) return false;
  const w = currentWeek(true);
  const d = w.days[d0] || (w.days[d0] = { noon: [], night: [] });
  const arr = d[s] || (d[s] = []);
  if (arr.length >= 4) { toast("一天最多四道"); return false; }
  if (arr.includes(nm)) { toast(`周${WEEK_NAMES[d0]}${s === "noon" ? "午饭" : "晚饭"}已经有「${nm}」`); return false; }
  arr.push(nm);
  save(state);
  toast(`周${WEEK_NAMES[d0]}${s === "noon" ? "午饭" : "晚饭"}加上「${nm}」`);
  return true;
}

/** 删掉某天某餐的第 k 道。带撤销——周菜单排到一半删错一道，不该从头再排。 */
function removeFromWeek(dayIdx, slot, k) {
  const w = currentWeek(false);
  const d = w && w.days[dayIdx];
  if (!d) return false;
  const arr = d[slot] || [];
  const i = Number(k);
  if (!arr[i]) return false;
  const name = arr[i];
  arr.splice(i, 1);
  save(state);
  toastUndo(`已从周${WEEK_NAMES[dayIdx]}${slot === "noon" ? "午饭" : "晚饭"}删掉「${name}」`, () => {
    const w2 = currentWeek(true);
    const d2 = w2.days[dayIdx] || (w2.days[dayIdx] = { noon: [], night: [] });
    const a2 = d2[slot] || (d2[slot] = []);
    a2.splice(Math.min(i, a2.length), 0, name);
    save(state);
    refreshWeekViews();
  });
  return true;
}

/** 「这周」页签（#weekGrid）与整周摊开屏（#weekBody）都挂这一份纸。
 *  **区别只有「整周摊开」那一枚**：两处内容的真实来源必须是同一份。
 *
 *  为什么 renderWeiWeek 两个容器都要画：wire.js 的 setWeiTab("week") 调的就是它，
 *  而那时人在味笺主屏、要看的容器是 #weekGrid。以前它无条件只画 #weekBody，
 *  于是「这周」页签看得见、里面一片空白——页签是活的，内容却画到了另一张纸上。
 *  两块纸之间没有重复 id（面板与格子一律走 data-* 与 class），同时存在不会打架。 */
function renderWeekGrid() {
  const host = $("#weekGrid");
  if (!host) return;
  host.innerHTML = weekPaneHTML({});
  bindWeekPane(host);
}

/** 整周摊开那一屏（#wei-week / #weekBody），以及味笺页签里那一块。 */
function renderWeiWeek() {
  const body = $("#weekBody");
  if (body) {
    body.innerHTML = weekPaneHTML({ full: true });
    bindWeekPane(body);
  }
  renderWeekGrid();
}

/** 谁在屏上就重画谁：两边都挂同一份生成器，但重复 id 会让选择器打架，所以只重画当前那一屏。 */
function refreshWeekViews() {
  const on = document.querySelector(".screen.on");
  if (on && on.id === "wei-week") renderWeiWeek();
  else renderWeekGrid();
}

function bindWeekPane(host) {
  // 搜索框是每次重画都在的那一个：整片 innerHTML 重建过，所以要重新绑
  const q = host.querySelector(".wk-search");
  if (q) q.oninput = () => { weekQuery = q.value; repaintWeekHost(host); };
  const close = host.querySelector("[data-wkclose]");
  if (close) close.onclick = () => { weekPick = null; weekQuery = ""; repaintWeekHost(host); };
  host.querySelectorAll("[data-wkpick]").forEach((b) => {
    b.onclick = () => {
      const [i, k] = String(b.dataset.wkpick).split(":");
      weekPick = { day: Number(i), slot: k };
      weekQuery = "";
      repaintWeekHost(host);
    };
  });
  host.querySelectorAll("[data-wkadd]").forEach((b) => {
    b.onclick = () => {
      if (!weekPick) return;
      if (addToWeek(weekPick.day, weekPick.slot, b.dataset.wkadd)) repaintWeekHost(host);
    };
  });
  host.querySelectorAll("[data-wkrm]").forEach((b) => {
    b.onclick = () => {
      const [i, k, n] = String(b.dataset.wkrm).split(":");
      if (removeFromWeek(Number(i), k, Number(n))) repaintWeekHost(host);
    };
  });
  const openFull = host.querySelector("[data-weekfull]");
  if (openFull) openFull.onclick = () => show("wei-week");
  const mk = host.querySelector("[data-weekmarket]");
  if (mk) mk.onclick = () => weekToMarket();
}

function repaintWeekHost(host) {
  const full = host.id === "weekBody";
  host.innerHTML = weekPaneHTML({ full });
  bindWeekPane(host);
}

/* ==================== 菜单长图（1080×1920） ====================
   排完一桌，最常发生的事是「发到群里」。复制文字已经有了；长图是给那些
   「截图比复制好看」的场合——一桌菜、谁不能吃、上菜顺序，一张纸说完。

   两条硬规矩（和 card.js 一致）：
   1. **长图永远是白天的纸**：它是发给别人看的，夜里存一张黑底图贴到群里像另一个 App。
      所以取色只走 token()，不读 data-theme 的最终值以外的东西——token 读的是根节点变量，
      夜里那份会被覆盖，所以这里在画之前临时把 data-theme 归到 light 再取一次。
   2. 版式是「一本杂志的内页」：纸底、宋体标题、印章红数字、底下一条落款。
*/

/** 长图上的色：先在 light 主题下取一遍，取完还原。
 *  不这样做的话，夜里存出来的是一张黑底长图（theme.js 会把 --cream 换成夜纸色）。 */
function menuCardTokens() {
  const root = document.documentElement;
  const prev = root.dataset.theme;
  root.dataset.theme = "light";
  const t = {
    cream: token("--cream", "#faf7f1"),
    paper: token("--paper", "#f4efe6"),
    ink: token("--ink", "#2a2723"),
    soft: token("--ink-soft", "#6b645b"),
    line: token("--line", "#d9d0c2"),
    seal: token("--seal", "#b54a3c"),
  };
  if (prev) root.dataset.theme = prev; else delete root.dataset.theme;
  return t;
}

/** 长图的内容模型：只放这一屏上真的说得出的东西。算不出来的不摆。 */
function menuCardData(r, talk, n, note) {
  const boom = (r && r.boom) || [];
  const risk = (r && r.risk) || [];
  const safe = (r && r.safe) || [];
  const order = (r && r.order) || [];
  const plan = (r && r.plan) || {};
  const gap = plan.gap || {};
  const want = plan.want || {};
  const kinds = (r && r.kinds) || {};
  return {
    talk: String(talk || ""),
    note: String(note || ""),
    n: Number(n) || 0,
    haveLine: ["荤", "素", "汤", "主食"].map((k) => `${k} ${kinds[k] || 0}`).join(" / "),
    wantLine: ["荤", "素", "汤", "主食"].map((k) => (want[k] ? `${k} ${want[k]}` : null)).filter(Boolean).join(" / "),
    gapLine: Object.keys(gap).length
      ? "还差：" + Object.entries(gap).map(([k, v]) => `${k} ${v} 道`).join("、")
      : "结构够了",
    boom: boom.map((x) => ({ dish: x.dish, why: x.why })),
    risk: risk.map((x) => ({ dish: x.dish, why: x.why })),
    safe,
    order: order.map((x) => ({ label: x.label, dish: x.dish })),
  };
}

/** 画这张长图。返回 canvas；画不出来就抛（调用方负责说一句人话）。 */
function drawMenuCard(data, tokens) {
  const W = 1080, H = 1920, PAD = 72;
  const SERIF = (typeof CARD !== "undefined" && CARD.SERIF) || '"Songti SC","Noto Serif SC","STSong","SimSun",serif';
  const SANS = (typeof CARD !== "undefined" && CARD.SANS) || '"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif';
  const T = tokens || menuCardTokens();
  const wrap = (s, n) => (typeof wrapZh === "function" ? wrapZh(s, n) : [String(s || "")]);
  const spaced = (ctx, text, x, y, gap) => {
    if (typeof drawSpaced === "function") return drawSpaced(ctx, text, x, y, gap);
    ctx.fillText(text, x, y);
  };

  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.fillStyle = T.cream;
  ctx.fillRect(0, 0, W, H);
  // 纸边：一圈比纸深一点点
  ctx.fillStyle = T.paper;
  ctx.fillRect(0, 0, W, 12);

  // 顶栏
  ctx.fillStyle = T.soft;
  ctx.font = `500 26px ${SANS}`;
  spaced(ctx, "JIAN · 味笺", PAD, 118, 8);
  ctx.textAlign = "right";
  ctx.fillText(typeof dayStr === "function" ? dayStr(Date.now()) : "", W - PAD, 118);
  ctx.textAlign = "left";
  ctx.strokeStyle = T.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, 152); ctx.lineTo(W - PAD, 152); ctx.stroke();

  // 标题 + 印章
  ctx.fillStyle = T.ink;
  ctx.font = `500 72px ${SERIF}`;
  ctx.fillText("这桌能入口", PAD, 268);
  ctx.fillStyle = T.soft;
  ctx.font = `400 26px ${SANS}`;
  ctx.fillText(`${data.n} 人 · 现有 ${data.haveLine}`, PAD, 320);

  // 印章：右上角，微微倾斜
  ctx.save();
  ctx.translate(W - PAD - 70, 236);
  ctx.rotate(-10 * Math.PI / 180);
  ctx.strokeStyle = T.seal; ctx.lineWidth = 5;
  ctx.beginPath(); ctx.arc(0, 0, 70, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = T.seal;
  ctx.font = `500 52px ${SERIF}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("味", 0, 4);
  ctx.restore();
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";

  // 群话术：这是这张图的主角。行高 64，最多六行，超了截断加省略号。
  let y = 420;
  ctx.fillStyle = T.ink;
  ctx.font = `400 40px ${SERIF}`;
  const talkLines = wrap(data.talk, 22).slice(0, 6);
  talkLines.forEach((ln, i) => {
    const last = i === talkLines.length - 1 && wrap(data.talk, 22).length > 6;
    ctx.fillText(last ? ln.slice(0, -1) + "…" : ln, PAD, y);
    y += 64;
  });
  y += 16;

  // 一条细线 + 「这桌的账」
  ctx.strokeStyle = T.line; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();
  y += 52;
  ctx.fillStyle = T.soft;
  ctx.font = `500 26px ${SANS}`;
  ctx.fillText("这桌的账", PAD, y);
  y += 44;
  ctx.fillStyle = T.ink;
  ctx.font = `400 30px ${SANS}`;
  ctx.fillText(`家常口径 ${data.wantLine || "—"} · ${data.gapLine}`, PAD, y);
  y += 56;

  // 雷区（第一优先：有人不能吃）
  if (data.boom.length) {
    ctx.fillStyle = T.seal;
    ctx.font = `500 26px ${SANS}`;
    ctx.fillText(`有人不能吃 · ${data.boom.length} 道`, PAD, y);
    y += 46;
    ctx.fillStyle = T.ink;
    ctx.font = `400 34px ${SANS}`;
    data.boom.slice(0, 5).forEach((x) => {
      ctx.fillText(`${x.dish}（${x.why}）`, PAD, y);
      y += 50;
    });
    if (data.boom.length > 5) {
      ctx.fillStyle = T.soft;
      ctx.font = `400 26px ${SANS}`;
      ctx.fillText(`还有 ${data.boom.length - 5} 道，在 App 里看`, PAD, y);
      y += 44;
    }
  } else {
    ctx.fillStyle = T.soft;
    ctx.font = `400 30px ${SANS}`;
    ctx.fillText("没有硬雷", PAD, y);
    y += 50;
  }

  // 谨慎层
  if (data.risk.length && y < 1300) {
    y += 8;
    ctx.fillStyle = T.soft;
    ctx.font = `500 24px ${SANS}`;
    ctx.fillText(`谨慎 · 含敏感成分，这桌没人忌口（${data.risk.length} 道）`, PAD, y);
    y += 42;
    ctx.fillStyle = T.ink;
    ctx.font = `400 30px ${SANS}`;
    data.risk.slice(0, 3).forEach((x) => {
      ctx.fillText(`${x.dish}（${x.why}）`, PAD, y);
      y += 44;
    });
  }

  // 上菜顺序：底部一条时间轴
  const oy = Math.max(y + 40, 1330);
  if (data.order.length && oy < 1700) {
    ctx.strokeStyle = T.line; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(PAD, oy - 34); ctx.lineTo(W - PAD, oy - 34); ctx.stroke();
    ctx.fillStyle = T.soft;
    ctx.font = `500 26px ${SANS}`;
    ctx.fillText("上菜顺序", PAD, oy);
    let ox = PAD, oyy = oy + 56;
    data.order.slice(0, 10).forEach((x, i) => {
      const label = `${i + 1} ${x.dish}`;
      ctx.font = `400 30px ${SANS}`;
      const w = ctx.measureText(label).width + 26;
      if (ox + w > W - PAD) { ox = PAD; oyy += 62; }
      ctx.fillStyle = T.paper;
      ctx.fillRect(ox, oyy - 34, w, 50);
      ctx.fillStyle = T.ink;
      ctx.fillText(label, ox + 12, oyy);
      ox += w + 12;
    });
  }

  // 第三层。措辞与屏幕上那一处（wei.js 的「按菜名看不出问题」）必须同一句话：
  // 同一件事在两个地方说成两种话，迟早有一种是假的。长图里空间有限，
  // 但「按菜名」这三个字是这句承诺的边界，省不得。
  if (data.safe.length) {
    ctx.fillStyle = T.soft;
    ctx.font = `400 28px ${SANS}`;
    const line = `按菜名看不出问题：${data.safe.join("、")}`;
    const ls = wrap(line, 30).slice(0, 3);
    let sy = H - 190;
    ls.forEach((ln, i) => {
      ctx.fillStyle = i === ls.length - 1 && wrap(line, 30).length > 3 ? T.soft : T.soft;
      ctx.fillText(ln, PAD, sy + i * 40);
    });
  }

  // 落款
  ctx.textAlign = "center";
  ctx.fillStyle = T.soft;
  ctx.font = `400 26px ${SERIF}`;
  ctx.fillText("一张短笺，一次决定", W / 2, H - 72);
  ctx.textAlign = "left";
  return c;
}

/** 存这张长图。链路与衣笺的 saveCard 同一套（原生 → 系统分享；浏览器 → 下载），
 *  但那段代码在 card.js 里、属于别人的文件，所以这里按同一个口径重写一遍收尾文案。 */
async function saveMenuCard() {
  const w = state.lastWei;
  if (!w || !w.r) { toast("先排一桌，才存得出这张图"); return; }
  const btn = $("#saveMenuCard");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.textContent = "正在写这张纸…"; btn.classList.add("busy"); }
  const restore = () => {
    if (btn) { btn.textContent = label; btn.classList.remove("busy"); }
  };
  const done = (href, revoke) => {
    const a = document.createElement("a");
    a.download = `味笺-${dayStr(Date.now())}.png`;
    a.href = href;
    a.click();
    if (revoke) setTimeout(() => URL.revokeObjectURL(href), 4000);
    restore();
    toast(typeof doneMsg === "function" ? doneMsg("保存长图") : "已保存长图", 5200);
  };
  try {
    const canvas = drawMenuCard(menuCardData(w.r, w.talk, w.n, ""));
    if (hasNative()) {
      try {
        const name = `味笺-${dayStr(Date.now())}.png`;
        await nativeShareFile(name, bareBase64(canvas.toDataURL("image/png")), { directory: "Cache" });
        restore();
        toast(doneMsg("保存长图"), 5200);
        return;
      } catch (e) {
        console.warn(e);
        restore();
        toast(SHARE_FAILED, 5200);
        return;
      }
    }
    if (canvas.toBlob) {
      canvas.toBlob((blob) => {
        if (blob) done(URL.createObjectURL(blob), true);
        else done(canvas.toDataURL("image/png"), false);
      }, "image/png");
    } else {
      done(canvas.toDataURL("image/png"), false);
    }
  } catch (e) {
    console.warn(e);
    restore();
    toast("长图没画出来");
  }
}

/* ==================== 一周菜单 → 买菜清单 ==================== */

/** 把这一周要买的汇总出来。**只算写过食材的菜**，并如实报告三件事：
 *  排了几道、哪几道是重复排的（食材只算一次）、哪几道还没写食材。 */
function weekShopping() {
  const w = currentWeek(false);
  const dishes = [];
  (w && w.days ? w.days : []).forEach((d) => {
    [...(d.noon || []), ...(d.night || [])].forEach((nm) => { if (nm) dishes.push(nm); });
  });
  const uniq = [...new Set(dishes)];
  const repeat = uniq.filter((nm) => dishes.filter((x) => x === nm).length > 1);
  const missing = [];
  const items = [];
  uniq.forEach((nm) => {
    const r = findRecipe(nm);
    if (!r || !(r.items || []).length) { missing.push(nm); return; }
    (r.items || []).forEach((it) => items.push(it));
  });
  return { dishes, uniq, repeat, missing, items };
}

function weekToMarket() {
  const s = weekShopping();
  if (!s.dishes.length) { toast("这一周还是空的，先在格子里排几道"); return; }
  if (!s.items.length) {
    toast(`这一周 ${s.uniq.length} 道菜还没有食材记录——先去菜谱写上食材`, 5200);
    return;
  }
  const added = addMarketItems(s.items, "这周");
  const bits = [added ? `已把 ${added} 样放进买菜清单` : "这几样清单里都有"];
  if (s.repeat.length) {
    const nm = s.repeat[0];
    const n = s.dishes.filter((x) => x === nm).length;
    bits.push(`「${nm}」这周排了 ${n} 次，食材只算一次`);
  }
  if (s.missing.length) {
    bits.push(`${s.missing.length} 道还没写食材：${s.missing.slice(0, 3).join("、")}${s.missing.length > 3 ? " 等" : ""}`);
  }
  toast(bits.join("；"), 6000);
  show("wei");
  setWeiTab("market");
}
