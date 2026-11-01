/** 笺 · 味笺
   排桌、忌口、群话术。 */

/* ---------- 味笺 ---------- */

/** 「常一起吃饭的人」那个抽屉是展开还是收着。界面态，不进 state。 */
let peopleSetOpen = false;

/** 这一桌人存成一组档案（名字 + 每个人的忌口快照）。
 *  存的是**快照**不是引用：以后把某人从这桌移走，旧的那一组里他还应该在——
 *  那是「上次一起吃饭时」的那桌人，改了就不是那份记录了。 */
function savePeopleSet() {
  const names = (state.people || []).map((p) => ({ name: p.name, chips: (p.chips || []).slice() }));
  if (!names.length) { toast("这桌还没有人"); return null; }
  const label = names.map((x) => x.name).join("、").slice(0, 20);
  // 一模一样的一组（同样的名字、同样的忌口）不重复存：那一栏会变成一堆同名项
  const dup = (state.peopleSets || []).find((g) =>
    (g.names || []).length === names.length
    && (g.names || []).every((x, i) => x.name === names[i].name
      && (x.chips || []).slice().sort().join("|") === (names[i].chips || []).slice().sort().join("|")));
  if (dup) { toast(`这一桌已经存过了：「${dup.name}」`); return dup; }
  const rec = { id: "p" + newId().slice(1), name: label, names, t: Date.now() };
  state.peopleSets = (state.peopleSets || []).concat([rec]).slice(-PEOPLE_SETS_CAP);
  save(state);
  haptic("LIGHT");
  toast(`存下了这 ${names.length} 个人，下次一键拉回来`);
  return rec;
}

/** 把一组档案拉进这一桌。**按名字去重**：已经有「小周」就不再添一个「小周」；
 *  已存在的那一个保留他自己当前的忌口（那是本人说的，比旧快照可信）。 */
function loadPeopleSet(id) {
  const g = (state.peopleSets || []).find((x) => x.id === id);
  if (!g) { toast("这一组已经不在了"); renderWeiPeople(); return; }
  const names = g.names || [];
  if (!names.length) { toast("这一组里没有名字"); return; }
  const added = [], kept = [];
  names.forEach((x) => {
    if (!x || !x.name) return;
    if ((state.people || []).find((p) => p.name === x.name)) { kept.push(x.name); return; }
    state.people.push({ name: x.name, chips: (x.chips || []).slice() });
    added.push(x.name);
  });
  if (!added.length) {
    toast(`这 ${names.length} 个人都已经在这桌了，忌口按眼下这份算`);
    return;
  }
  let over = 0;
  if (state.people.length > 12) {
    // 上限是「一桌人」的现实上限：再多，排桌表与群话术都不再是人话
    over = state.people.length - 12;
    state.people = state.people.slice(0, 12);
  }
  whoOpen = [];
  save(state);
  renderWeiPeople();
  haptic("LIGHT");
  toast(`拉进来 ${added.length} 个人${kept.length ? `；${kept.length} 个已经在桌上` : ""}${over ? `；一桌最多 12 人，多出来的 ${over} 个没进来` : ""}`);
}

/** 删掉一组档案，带撤销。 */
function forgetPeopleSet(id) {
  const list = state.peopleSets || [];
  const i = list.findIndex((x) => x.id === id);
  if (i < 0) { toast("这一组已经不在了"); renderWeiPeople(); return; }
  const snap = list[i];
  list.splice(i, 1);
  save(state);
  renderWeiPeople();
  toastUndo(`已删掉「${snap.name}」这一组`, () => {
    const l = state.peopleSets || [];
    l.splice(Math.min(i, l.length), 0, snap);
    save(state);
    renderWeiPeople();
  });
}

/** 「常一起吃饭的人」抽屉：把当前这桌存下来、把存过的拉进来。
 *  它放在加人那一行下面，因为它的原料就是上面这桌人。
 *  容器由这里现造并插到 #people 后面——index.html 是 Lead 的文件，
 *  这一块是味笺自己的东西，不该让骨架替它留位置。 */
function renderPeopleSets() {
  const anchor = $("#people");
  if (!anchor) return;
  let host = $("#peopleSets");
  if (!host) {
    host = document.createElement("div");
    host.id = "peopleSets";
    anchor.insertAdjacentElement("afterend", host);
  }
  const list = state.peopleSets || [];
  const n = (state.people || []).length;
  const body = list.length
    ? `${list.slice().reverse().map((g) => `
          <div class="pd-item">
            <span class="pd-main"><b class="serif">${esc(g.name)}</b>
              <span class="tiny">${(g.names || []).length} 人 · ${relativeDays(g.t) || "今天"}存的</span></span>
            <button class="chip pd-load" data-pload="${esc(g.id)}" type="button"
                    aria-label="把「${esc(g.name)}」这 ${(g.names || []).length} 个人拉进这桌">拉进来</button>
            <button class="chip hdel pd-del" data-pdel="${esc(g.id)}" type="button"
                    aria-label="删掉「${esc(g.name)}」这一组">删</button>
          </div>`).join("")}
        <button class="btn ghost wide" data-psave="1" type="button" style="margin-top:10px">把眼下这 ${n} 个人存成一组</button>
        <p class="tiny" style="margin-top:8px">存的是名字与忌口的快照：以后改了谁，旧的那一组不会跟着变。</p>`
    : `<p class="tiny pd-empty">还没有存过。把上面这 ${n} 个人存下来，下次吃同一桌就不用重新点忌口。</p>
       <button class="btn ghost wide" data-psave="1" type="button">把这 ${n} 个人存成一组</button>`;
  host.innerHTML = `<details class="drawer people-drawer"${peopleSetOpen ? " open" : ""}>
      <summary>常一起吃饭的人${list.length ? ` · ${list.length} 组` : ""}</summary>
      <div class="drawer-body">${body}</div>
    </details>`;
  $$("#peopleSets [data-psave]").forEach((b) => { b.onclick = () => savePeopleSet(); });
  $$("#peopleSets [data-pload]").forEach((b) => { b.onclick = () => loadPeopleSet(b.dataset.pload); });
  $$("#peopleSets [data-pdel]").forEach((b) => { b.onclick = () => forgetPeopleSet(b.dataset.pdel); });
  const det = host.querySelector("details");
  if (det) det.addEventListener("toggle", () => { peopleSetOpen = det.open; });
}


/** 味笺那一屏的结果区。
 *  排过桌就回看上一桌（存在 state.lastWei 里，整页重开也还在），没排过才给引导。
 *  以前结果只活在 DOM 里：切去衣笺再切回来就没了，重开更是全丢——
 *  而「这桌能不能入口」恰恰是要拿去群里说、要回头再看一眼的东西。 */
function renderWei() {
  const box = $("#weiResult");
  // 进这一屏要把「这一桌人」也重画一遍。以前 renderWeiPeople() 只在 boot 和增删改那几个
  // handler 里调，于是任何一条改了 state.people 却没走这些 handler 的路（这一轮就是被
  // dead_controls 的空态种子撞出来的：people 只剩一个人，屏上还挂着 data-who="1" 那枚签）
  // 都会留下旧 DOM —— 点它不是没反应，是**抛异常**（Cannot read properties of undefined）。
  renderWeiPeople();
  renderWeiHist();
  // 味笺这一屏上不属于「这一页签」的那两枚按钮也要在这里重新绑一次：
  // #newRecipe 与 #wheelBtn 是常驻 DOM（index.html 里在页签容器外面/里面都有），
  // 只要整屏重画过、或者用户是从别的屏切过来的，它们就可能还挂着 boot 时那个 handler。
  //
  // #newRecipe 尤其要紧：app.js 里原来那一个是 `prompt("这道菜叫什么？")`。
  // 那个框在这个壳里**是能用的**（Capacitor 的 BridgeWebChromeClient 真实现了 onJsPrompt），
  // 所以这里的理由不是「按了没反应」，而是它不该出现在这张纸上：Material 弹框 + 英文
  // OK/Cancel、阻塞 WebView、而且只能问一行字，接不上后面填食材与步骤那一步。
  // 覆盖发生在每一次进味笺（不只切到「做菜」页签），所以从排桌页签直接点到它
  // 也不会落回那个原生框。
  bindWeiChrome();
  if (!box) return;
  const w = state.lastWei;
  if (w && w.r) {
    const n = Number(w.n);
    paintWei(w.r, String(w.talk || ""), Number.isFinite(n) ? n : state.people.length,
      `${relativeDays(w.t) || "刚才"}排的一桌 · ${countMenu(w.menu)} 道`);
    markStaleWei();
    return;
  }
  box.innerHTML = `<div class="empty">把菜单贴进来，一行一道，或者一句话说清都行。<br>它会告诉你谁吃不了哪道、这桌还缺什么。</div>`;
}

/** 菜单里有几道：直接问引擎的切法。以前这里自己抄了一份 split，
 *  引擎改成「菜和话分开」之后它就一直在报 6 道，而桌上只有 4 道。 */
function countMenu(menu) {
  return Engine.menuItems(menu).dishes.length;
}

/** 菜单文本与存着的那一桌不一致时，结果就是旧的了——说出来，并给一次重排。
 *  不自动重排：那是另一次判定，要扣点，得用户自己按。 */
function markStaleWei() {
  const bar = $("#weiStale");
  const w = state.lastWei;
  if (!bar || !w) return;
  // 桌序现在真的看 mode（第 40 轮：家里把硬菜和雷压到最后，同事只压雷），
  // 所以「换了这桌是谁」和「改了菜单」一样，都让屏幕上那一桌变成上一版的。
  // 以前 lastWei.mode 存着没人读，换了模式签屏幕一个字都不提示。
  const menuChanged = $("#menu").value !== w.menu;
  const modeChanged = state.weiMode !== w.mode;
  const cap = bar.querySelector(".tiny");
  if (cap) cap.textContent = menuChanged && modeChanged ? "菜单和这桌的人都换了，这张还是上一版的"
    : modeChanged ? "这桌的人换了，这张还是上一版的"
    : "菜单改过了，这张还是上一版的";
  bar.style.display = menuChanged || modeChanged ? "flex" : "none";
}

/** 排成一桌就记一笔（只记菜单、人数和当时都在忌口什么）。上限 WEI_HIST 在 state.js。
 *  同一份菜单再排一次是把时间挪到最前，不留两行几乎一样的签。
 *  记在扣点那次判定上：点推荐菜触发的免费重跑会改菜单，那种一步步的中间态不值得留。 */
function rememberWei(menu) {
  const chips = [];
  state.people.forEach((p) => (p.chips || []).forEach((c) => { if (!chips.includes(c)) chips.push(c); }));
  const hist = (state.weiHist || []).filter((h) => h && h.menu !== menu);
  state.weiHist = [{ menu, n: state.people.length, t: Date.now(), chips }].concat(hist).slice(0, WEI_HIST);
}

/** 一桌忌口过三项就收起来，写成「忌 辣 蒜 等 4 项忌口」。 */
function weiHistBan(h) {
  const chips = (h && h.chips) || [];
  if (!chips.length) return "没人忌口";
  return `忌 ${chips.slice(0, 2).join(" ")}${chips.length > 2 ? ` 等 ${chips.length} 项忌口` : ""}`;
}

/** 「删」那一枚的名字：按下去**之前**就得说清带走的是哪一桌、几道菜。
 *  口径同 renderWeiPeople 的 delAria —— 可见的那一格旁边本来就写着「哪一天 · 几人 · 几道」
 *  （那是给眼睛的预告），这一句是给读屏器的。删掉的只是这一桌的菜单记录：
 *  笺册里那张 wei（群话术）没动，说成「那一桌没了」就是谎话。 */
function histDelAria(h, when) {
  return `删掉「${when}」那一桌，会带走 ${countMenu(h.menu)} 道菜的菜单`;
}

/** 排过的桌：拿回来重排的那一桌，不必再翻聊天记录找菜单。
 *  签上只写「时间 · 几人 · 几道」——加上忌口那一串实测 277px 宽，360 的纸上
 *  一行只放得下一枚，8 桌就是 370px 的一堵签墙，把「排这桌」推到两屏之外。
 *  忌口没丢：点的那一下在提示里说（那才是用得到它的时刻）。
 *
 *  每一桌左边是「拿回菜单」、右边是「删」（第 65 轮）。这一栏以前只进不出：
 *  唯一的写入口是 rememberWei 的 unshift + slice，没有任何删的入口——误把一整页聊天记录
 *  贴成一桌，它就会一直占着四格之一（一格里存着整份菜单文本），只能靠再排四桌把它挤掉。
 *  两枚签包在 .hpair 那一格里，不直接当 .chips 的兄弟：flex-wrap 之后一枚「删」
 *  可能正好换行挨到别一桌的签后面，那时按下去删的是谁说不清。 */
function renderWeiHist() {
  const box = $("#weiHist");
  if (!box) return;
  const list = state.weiHist || [];
  if (!list.length) { box.style.display = "none"; box.innerHTML = ""; return; }
  box.style.display = "block";
  box.innerHTML = `<p class="tiny">排过的桌 · 点一下把菜单拿回来</p>
    <div class="chips">${list.map((h, i) => {
      const when = relativeDays(h.t) || "刚才";
      const aria = histDelAria(h, when);
      return `<span class="hpair">
        <button class="chip" data-hist="${i}">${esc(when)} · ${h.n} 人 · ${countMenu(h.menu)} 道</button>
        <button class="chip hdel" data-hdel="${i}" aria-label="${esc(aria)}">删</button></span>`;
    }).join("")}</div>`;
  $$("#weiHist [data-hist]").forEach((b) => { b.onclick = () => recallWei(+b.dataset.hist); });
  $$("#weiHist [data-hdel]").forEach((b) => { b.onclick = () => forgetWei(+b.dataset.hdel); });
}

/** 只是把菜单填回框里，不代按「排这桌」：那是一次新判定、要扣点，得用户自己按。
 *  走 input 事件这一个入口——state.weiMenu、写盘、「这张是上一版的」提示三件事同时更新。 */
function recallWei(i) {
  const h = (state.weiHist || [])[i];
  if (!h) return;
  const el = $("#menu");
  el.value = h.menu;
  el.dispatchEvent(new Event("input"));
  haptic("LIGHT");
  toast(`菜单拿回来了（${weiHistBan(h)}）。要重排点「排这桌」`);
}

/** 删掉排过的一桌：这一栏唯一出去的口子（以前只进不出）。
 *  按快照填回，而且**填回原来那一格**——weiHist 是有序的（新的在最前），
 *  塞回末尾等于把「刚才那一桌」变成「最旧那一桌」，那是另一种弄错。
 *  屏上的 DOM 落后于 state（刚被别的路改过）时不许静默也不许抛：重画一次让用户看见真相。 */
function forgetWei(i) {
  const list = state.weiHist || [];
  const h = list[i];
  if (!h) { renderWeiHist(); toast("那一桌已经不在了"); return; }
  const when = relativeDays(h.t) || "刚才";
  const dishes = countMenu(h.menu);
  const snapshot = { ...h, chips: (h.chips || []).slice() };
  list.splice(i, 1);
  save(state); renderWeiHist();
  toastUndo(`已删掉「${when}」那一桌 · ${dishes} 道菜的菜单（笺册里那张笺没动）`, () => {
    const l = state.weiHist || [];
    l.splice(Math.min(i, l.length), 0, { ...snapshot, chips: snapshot.chips.slice() });
    save(state); renderWeiHist();
    toast(`「${when}」那一桌回到第 ${i + 1} 格（${dishes} 道）`);
  });
}

/** 谁展开了忌口选择器。只是界面态，不进备份（备份里存着展开状态反而怪）。 */
let whoOpen = [];

/** 一个人名字的字数上限，与 state.js 的 normPerson 那一条 slice(0, 20) 同一线。
 *  这里要它是因为界面上得先有 maxlength，用户才知道这格只放 20 字；
 *  两边各写一个 20、由 e2e §58 钉住「填 25 字当场和重开之后都是 20 字」——
 *  哪天上面那行改成 24 而这里没跟着改，红的是那条断言，不是用户的账本。 */
const NAME_MAX = 20;

/** 「移除」那一枚的名字：按下去**之前**就得说清连带带走什么。
 *  这组忌口只挂在这个人身上（engine.js 的 wei() 只读 p.chips 和人数，名字本身不进判定），
 *  所以删人 = 那些忌口一起没，而 toastUndo 只活 5.2 秒。
 *  可见的字还是「移除」两枚（360 的纸上放不下那一整句）：给眼睛的预告是行下那一排
 *  摊着的忌口签——它们就在名字底下，跟着人一起走；这一句是给读屏器的。
 *  渲染与就地改名后刷新都走这一个函数，屏上两处的名字不许有一个改了一个没改。 */
function delAria(name, nBan) {
  return `移除 ${name}` + (nBan ? `，会连带去掉 ${nBan} 项忌口` : "，他没挂忌口");
}

/** 忌口以前是每人摊开 11 枚小签：三个人就是 33 枚，两屏才滚得完，
 *  而绝大多数人真正忌的只有一两个。改成「已选的挂在行上，全表收进一枚「忌口」」。
 *
 *  名字这一格是**就地可改的输入框**（第 63 轮）。为什么改这个名字不用碰任何旧结果，
 *  是把每一处读名字的地方都查过之后说的：
 *    · engine.js 的 wei() / backend/gateway.py 的 wei 只读 `p.chips` 与 `len(people)`，
 *      「有人不能吃」那一层的 why 是忌口词（`blocked.join(" / ")`），不是人名；
 *    · weiTalk() 生成的那句群话术里一个人名都没有（人数、菜名、缺口）；
 *    · state.lastWei 存的是 {menu, mode, n, t, r, talk}，state.weiHist 是 {menu, n, t, chips}，
 *      笺册里那张 wei 存的是 talk——三份持久化的东西都没有名字这一栏；
 *    · 全 App 只有这一格画 p.name（另外两处 `gone.name` 是提示语，读的是当场那一份）。
 *  屏上唯一可能出现旧名字的地方是用户自己贴进菜单的那一句「阿姨不吃辣」，
 *  它走 notes/inferred 印在笺上，那是他贴的字不是这桌的人，改名不许去动它。
 *  所以这一轮走的是「只改往后的判定，旧结果原样留着」这一条路，而且它天然没有
 *  第二处对不上：旧那张笺上本来就没写着名字。 */
function renderWeiPeople() {
  const fk = focusKey();
  $("#people").innerHTML = state.people.map((p, i) => {
    const open = whoOpen.includes(i);
    const picker = CHIPS.map((c) =>
      `<button class="chip ${p.chips.includes(c) ? "on" : ""}" data-c="${c}" data-who="${i}" aria-pressed="${p.chips.includes(c)}">${c}</button>`
    ).join("");
    const picked = p.chips.map((c) =>
      `<button class="chip on" data-c="${c}" data-who="${i}" aria-pressed="true">${c}</button>`
    ).join("");
    const row = open
      ? `${picker}<button class="chip" data-open="${i}" aria-expanded="true">收起</button>`
      : `${picked || '<span class="tiny who-none">没人忌口</span>'}<button class="chip" data-open="${i}" aria-expanded="false">忌口</button>`;
    const nm = esc(p.name);
    return `
    <div class="card">
      <div class="topbar">
        <input type="text" class="name-edit" data-rename="${i}" value="${nm}" maxlength="${NAME_MAX}"
               aria-label="改「${nm}」的名字" />
        <button class="chip" data-del="${i}" aria-label="${esc(delAria(p.name, p.chips.length))}">移除</button></div>
      <div class="chips">${row}</div>
    </div>`;
  }).join("");
  $$("#people [data-c]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.who;
      const c = b.dataset.c;
      // 万一屏上还挂着某个已经不存在的人的那枚签（DOM 落后于 state），也不许点下去抛异常：
      // 重画一次，让用户看见真相，而不是「按了没反应」。
      const p = state.people[i];
      if (!p) { renderWeiPeople(); return; }
      const arr = p.chips;
      state.people[i].chips = arr.includes(c) ? arr.filter((x) => x !== c) : [...arr, c];
      save(state); renderWeiPeople();
    };
  });
  $$("#people [data-open]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.open;
      whoOpen = whoOpen.includes(i) ? whoOpen.filter((x) => x !== i) : [...whoOpen, i];
      renderWeiPeople();
    };
  });
  // 就地改名：只交这一格，不重建整片。重建会把焦点从正在改名的输入框里抢走，
  // 用 Tab 提交时还会「重建 → 焦点按身份找回同一个输入框」转成死循环（口径同 yi.js #clothName）；
  // 更要紧的是，同一次点击里「先 blur 提交、再点到移除」靠的就是这一格还挂在原来的 DOM 节点上。
  $$("#people [data-rename]").forEach((inp) => {
    const commit = () => {
      const i = +inp.dataset.rename;
      const p = state.people[i];
      // 屏上的 DOM 落后于 state（人少了一个）时不许静默，也不许抛：重画一次让用户看见真相
      if (!p) { renderWeiPeople(); return; }
      const raw = inp.value.trim();
      // 空名字弹回原名并且说清楚是谁改回去的（静默弹回 = 界面动了一下、动的方向像 bug）
      if (!raw) { inp.value = p.name; toast("名字不能空着，已填回原来那个"); return; }
      const v = raw.slice(0, NAME_MAX);
      const old = p.name;
      inp.value = v;                       // 一律把「真正存进去的那一串」写回框里，不留两种口径
      if (v === old) return;               // 一模一样不算改动（同 yi.js 那条判定）
      const dup = state.people.some((x, j) => j !== i && x.name === v);
      p.name = v; save(state);
      // 改完这一格，行上另外两处写着同一个名字的地方跟着一起刷，别留一个旧的在屏上
      inp.setAttribute("aria-label", `改「${v}」的名字`);
      const del = inp.closest(".topbar").querySelector("[data-del]");
      if (del) del.setAttribute("aria-label", delAria(v, p.chips.length));
      toast(raw.length > NAME_MAX ? `名字太长，只留前 ${NAME_MAX} 字：「${v}」`
        : dup ? `改成「${v}」了 · 这桌已经有一个「${v}」，两行会看着一样`
          : `已改名：「${old}」→「${v}」`);
    };
    inp.onchange = commit;
    // 手机上没有 Tab：键盘上按「完成/换行」也算提交（同一入口，走 commit 那一条路）
    inp.onkeydown = (e) => { if (e.key === "Enter") inp.blur(); };
  });
  $$("#people [data-del]").forEach((b) => {
    b.onclick = () => {
      if (state.people.length < 2) { toast("至少留一个人"); return; }
      const i = +b.dataset.del;
      const [gone] = state.people.splice(i, 1);
      whoOpen = [];                    // 序号整体前移，展开状态跟着作废
      save(state); renderWeiPeople();
      // 快照 = 当场那一份人对象 + 那一整组忌口的副本。反悔按快照填回，不是「把人塞回去」：
      // 那几项忌口是下一次排桌要吃的东西，5.2 秒一过就没有第二条路（导出备份除外）。
      const snapshot = { ...gone, chips: (gone.chips || []).slice() };
      const n = snapshot.chips.length;
      toastUndo(`已移除「${snapshot.name}」`
        + (n ? `，连带去掉 ${n} 项忌口（${snapshot.chips.join("、")}）` : "，他没挂忌口"), () => {
        state.people.splice(Math.min(i, state.people.length), 0,
          { ...snapshot, chips: snapshot.chips.slice() });
        save(state); renderWeiPeople();
        toast(`「${snapshot.name}」回到这桌`
          + (n ? `，${n} 项忌口一起回来了` : ""));
      });
    };
  });
  // 抽屉每一轮都跟着这桌人一起画：存过的组数、当前几个人，都是它身上写着的东西。
  // 放在最后是因为它要知道「眼下这桌几个人」——那个数刚刚在上面被改过。
  renderPeopleSets();
  restoreFocus(fk);
}

function weiTalk(r, mode, n) {
  const boom = (r.boom || []).map((x) => x.dish);
  const safe = r.safe || [];
  const ok = safe.slice(0, 5);
  const head = {
    friends: `这桌先排过了。`,
    // 「两个人」以前是写死的：这句是要粘进群里的，四个人而话里说两个人，
    // 骗的是朋友的胃。人数就在这儿传进来（同一屏那行「N 人 · 现有…」用的也是它）。
    couple: `今晚按 ${n} 个人的胃来。`,
    home: `家里这桌，硬菜和雷放后面。`,
    work: `同事这桌，先保全员能入口。`
  }[mode];
  const line1 = boom.length ? `避开：${boom.join("、")}。` : `没有硬雷。`;
  // 屏上「按菜名看不出问题」那一节列的是全部，话术里只带前五道。不写「等 N 道」，
  // 粘到群里的人以为就这五道——而结果页明明还列着六道。
  const line2 = ok.length ? `可以点：${ok.join("、")}${safe.length > ok.length ? ` 等 ${safe.length} 道` : ""}。`
    : `建议先问一圈忌口。`;
  const line3 = r.plan && Object.keys(r.plan.gap || {}).length
    ? `这桌还差 ${Object.entries(r.plan.gap).map(([k, v]) => k + " " + v + " 道").join("、")}。`
    : "";
  return [head, line1, line2, line3].filter(Boolean).join("");
}

async function runWei(opts = {}) {
  const menu = $("#menu").value;
  if (!menu.trim()) { toast("先贴菜单"); return; }
  if (busy) return;
  if (!opts.free && !spend(1, "wei")) return;
  busy = true;
  JianAPI.beginTurn();
  veil(true, "在排这一桌…");
  toast("排桌中…");
  let raw = null, r = null;
  try {
    raw = await JianAPI.wei(menu, state.people, state.weiMode);
    r = cleanWeiResult(raw);
    if (!r) throw new Error("回话不是一张桌");
    state.weiMenu = menu;
    const talk = weiTalk(r, state.weiMode, state.people.length);
    // 存下这一桌：切走再回来、整页重开，都还能看见（renderWei 读的就是这份）
    state.lastWei = { menu, mode: state.weiMode, n: state.people.length, t: Date.now(), r, talk };
    // 点推荐菜会重跑一次排桌（不扣点），那种重跑不该往笺册里再塞一封几乎一样的
    if (!opts.free) {
      state.album.unshift({ type: "wei", t: Date.now(), quote: talk, text: talk });
      rememberWei(menu);
    }
    save(state);
    paintWei(r, talk, state.people.length);
    renderWeiHist();
    hintEngine("wei");   // 这一桌是网关排的还是本地排的，顶栏当下就该跟着换
  } catch (e) {
    if (!opts.free) refund(1, "wei");
    toast(raw === null ? "这一桌没排成，笺点已退回" : "网关回的不是一张桌，笺点已退回");
  } finally {
    // 与衣笺/言笺同一副骨架：收尾写在 try 外面的话，处理途中一抛就是「遮罩永久挂着」
    busy = false;
    veil(false);
  }
}

/** 结果页上的一个菜名：菜库里有的那一道做成按钮（点进菜谱详情），没有的仍是纯文字。
 *  **只认名字全等**——用包含匹配会把「白切鸡1」链到「白切鸡」上，那是给用户看一道不是他点开的菜。
 *  textContent 保持原名不变：e2e 第 5 节那一批断言量的是「这一行写着哪道菜」，不是它是什么标签。 */
function dishNameHTML(name) {
  const n = String(name || "");
  const d = (typeof exactDish === "function") ? exactDish(n) : null;
  if (!d) return esc(n);
  return `<button class="dish-link" type="button" data-dishlink="${esc(n)}"
      aria-label="看「${esc(n)}」这张菜谱卡">${esc(n)}</button>`;
}

/** 把排好的一桌画出来。runWei 与「回看上一桌」共用这一份：
 *  持久化的意义就是回来还能看见，画两遍的话两边迟早长得不一样。 */
function paintWei(r, talk, n, note) {
  const kinds = r.kinds || {};
  const plan = r.plan || { want: {}, gap: {} };
  const add = r.add || [];
  const dupes = r.dupes || [];
  // 上一桌是第十轮之前存的也会走到这里：没有这两项就当没有，别炸回看
  const notes = r.notes || [];
  const inferred = r.inferred || [];
  const gapLine = Object.keys(plan.gap || {}).length
    ? `还差：${Object.entries(plan.gap).map(([k, v]) => `${k} ${v} 道`).join("、")}。`
    : "结构够了。";
  // 「其他」这一类以前算了没人读：一桌「可乐、果盘、冰淇淋、坚果」在屏上写的是
  // 「现有 荤 0 / 素 0 / 汤 0 / 主食 0」——人列了四道，笺说他一道没有。为零的不占字数，
  // 但不为零的必须露面，否则那行总数就对不上。
  const haveLine = ["荤", "素", "汤", "主食"].map((k) => `${k} ${kinds[k] || 0}`).join(" / ")
    + (kinds["其他"] ? ` / 其他 ${kinds["其他"]}` : "");
  const wantLine = ["荤", "素", "汤", "主食"].map((k) => (plan.want[k] ? `${k} ${plan.want[k]}` : null)).filter(Boolean).join(" / ");

  const fk = focusKey();   // 点「推荐菜」会重跑排桌、整片重建结果，焦点同样要找回
  $("#weiResult").innerHTML = `
    <div class="bar" id="weiStale" style="display:none">
      <span class="tiny">菜单改过了，这张还是上一版的</span>
      <button class="chip" id="reWei">按现在的重排</button>
    </div>
    <div class="sheet">
      <p class="meta">JIAN · WEI</p>
      <span class="seal-mark lg serif" aria-hidden="true">味</span>
      ${note ? `<p class="tiny">${esc(note)}</p>` : ""}
      <p class="tiny sheet-cap">复制到群</p>
      <p class="quote serif">${esc(talk)}</p>
      <button class="btn wide" id="copyWei">复制这段话</button>
      <!-- 长图：给「截图比复制好看」的场合。图上的每一句都来自这一屏，
           算不出来的（比如没有判定）在一开始就挡住并说明。 -->
      <div class="menu-card-row">
        <button class="btn ghost" id="saveMenuCard">存成菜单长图</button>
      </div>
      <div class="rule"></div>
      <p class="tiny sheet-cap">排桌</p>
      <p>${n} 人 · 现有 ${haveLine}</p>
      <p class="tiny" style="margin-top:6px">家常口径：${wantLine}。${gapLine}</p>
      ${add.length ? `
        <p class="tiny sheet-cap" style="margin-top:14px">可以加这几道 · 点一下就进菜单</p>
        <div class="chips" style="margin-top:8px">
          ${add.map((d) => `<button class="chip soft" data-add="${esc(d.name)}">${esc(d.name)}</button>`).join("")}
        </div>` : ""}
    ${notes.length ? `
      <div class="rule"></div>
      <p class="tiny sheet-cap">没当成菜的那几句</p>
      ${notes.map((x) => `<p class="note-line">${esc(x)}</p>`).join("")}
      ${inferred.length ? `
        <p class="tiny" style="margin-top:8px">这句里写着忌口：<b>${esc(inferred.map((x) => x.chip).join("、"))}</b>——已经替这一桌避开了。
        给谁忌的，点上面那个人的「忌口」补上签，下次就不用再说一遍。</p>` : `
        <p class="tiny" style="margin-top:8px">这几句是安排，不是菜名，所以没算进上面的桌。</p>`}` : ""}
    ${dupes.length ? `
      <div class="rule"></div>
      <p class="tiny sheet-cap">可能重了</p>
      ${dupes.map((d) => `<p>${d.dishes.length} 道都有「${esc(d.main)}」：${esc(d.dishes.join("、"))}</p>`).join("")}
      <p class="tiny" style="margin-top:6px">可以换掉其中一道。</p>` : ""}
    ${(r.order || []).length ? `
      <div class="rule"></div>
      <p class="tiny sheet-cap">上菜顺序</p>
      <div class="serving">
        ${r.order.map((x, i) => `
          <div class="line">
            <span class="idx">${i + 1}</span>
            <span class="stage">${esc(x.label)}</span>
            <span class="dish">${dishNameHTML(x.dish)}</span>
          </div>`).join("")}
      </div>
      <p class="tiny" style="margin-top:10px">硬的压后，汤饭收尾。</p>` : ""}
      <div class="rule"></div>
      <p class="tiny sheet-cap">雷区（有人不能吃）</p>
      <div class="list">${(r.boom || []).map((x) => `<div class="todo"><b>避开</b><div>${esc(x.dish)}<div class="tiny">${esc(x.why)}</div></div></div>`).join("") || "<p class='tiny'>没有硬雷</p>"}</div>
    ${(r.risk || []).length ? `
      <p class="tiny sheet-cap" style="margin-top:14px">谨慎（含敏感成分，这桌没人忌口）</p>
      <div class="list">${(r.risk || []).map((x) => `<div class="todo"><b>留意</b><div>${esc(x.dish)}<div class="tiny">${esc(x.why)}</div></div></div>`).join("")}</div>` : ""}
      <p class="tiny sheet-cap" style="margin-top:14px">按菜名看不出问题</p>
      <p>${esc((r.safe || []).join("、") || "—")}</p>
      <p class="tiny" style="margin-top:10px">这一层只看菜名和菜库记着的成分，后厨用什么油、哪张砧板、同一口锅刚炒过什么，笺看不见。真有人过敏（尤其重的），下筷前和做饭的人再确认一句。</p>
    </div>`;

  $("#copyWei").onclick = () => copy(talk, "已复制，去粘到群里");
  const smc = $("#saveMenuCard");
  if (smc) smc.onclick = () => saveMenuCard();
  // 结果里那几道菜：菜库里有卡的，点菜名进菜谱详情（在结果页就地看完，不用回头找）
  $$("#weiResult [data-dishlink]").forEach((b) => {
    b.onclick = () => openDish(b.dataset.dishlink);
  });
  const rw = $("#reWei");
  if (rw) rw.onclick = () => runWei();          // 重排是一次新判定：照常扣点，由用户按
  $$("#weiResult [data-add]").forEach((b) => {
    b.onclick = () => {
      const el = $("#menu");
      const cur = el.value.trim();
      el.value = cur ? cur + "\n" + b.dataset.add : b.dataset.add;
      runWei({ free: true });   // 同一次排桌里的追加，不再扣点
    };
  });
  restoreFocus(fk);
}
