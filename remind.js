/** 笺 · 提醒与每日摘录
 *
 *  言笺原来只有「捞成笺」：把话捞成四类卡片，勾掉、复制。它缺的是**时间**——
 *  一条「周五交报价」捞出来之后，周五没人叫你。
 *
 *  这一份补三件事：
 *  1. **提醒**：一条可以定到某个时刻，到点弹系统通知（安卓本地通知）。
 *     诚实边界必须写在屏幕上：Doze 模式下系统会把闹钟攒着一起发，
 *     所以文案永远写「大约这个点」，不写「准时」；也不申请精确闹钟权限。
 *  2. **重复提醒**：一次 / 每天 / 每周 / 每月。**不自己起 setInterval**——
 *     WebView 在后台会被冻结，自己算时间必然错过。系统只排「下一次」，
 *     这一次发了之后由 catchUpRepeats() 在下次进屏时把下一次排上。
 *  3. **每日摘录**：一天最多一句。它和「笺册」不是一回事——笺册存的是整张笺，
 *     摘录存的是你自己挑出来的那一句。
 *
 *  提醒的数据形状在 state.reminders，和言笺条目（yanCards）分开存：
 *  删掉一条言笺不该把已经定好的提醒一起删掉，那是两件事。
 *
 *  **一项产品立场**：这一整份里没有一处 window.prompt / confirm / alert。
 *  先说准事实：prompt 在笺的原生壳里**是用得了的**（Capacitor 的 BridgeWebChromeClient
 *  真的实现了 onJsPrompt/onJsAlert/onJsConfirm，走 AlertDialog）。问题不是「不能用」，
 *  是**不该用**——Material 弹框配英文 OK/Cancel，和这张纸不是一套东西；
 *  它阻塞 WebView；而且一次只能问一行字，问不出「哪天、几点、隔多久再来一次」。
 *  所以快速添加改成屏内面板（见 renderQuickAdd），摘录改成屏内输入框：
 *  一次把该问的问全，且长得像这张纸上的东西。
 */

/* ==================== 提醒 ==================== */

let reminderPermAsked = false;

/** 到点（或在过去已经过了）的提醒条数：底栏那个小点用它。
 *  口径：**没办完 + 到期时刻在 24 小时内**（含已经过去的）。
 *  已经过期的更该亮红点——底栏小点表达的是「有该办没办的事」，
 *  不是「未来 24 小时有几个闹钟」。没办完且没过期的当然也数进去。 */
function dueToday() {
  const now = Date.now();
  const end = now + 86400000;
  return (state.reminders || []).filter((r) => !r.done && r.at <= end).length;
}
/** 已经过期的条数（屏上要说出来，而不是悄悄压着）。 */
function pastDue() {
  const now = Date.now();
  return (state.reminders || []).filter((r) => !r.done && r.at < now).length;
}

/** 加一条提醒。from: yan（从言笺条目来）/ manual / wei */
function addReminder(text, at, opt) {
  const t = String(text || "").trim().slice(0, 120);
  const ts = Number(at);
  if (!t) { toast("提醒得有个名字"); return null; }
  if (!Number.isFinite(ts) || ts <= Date.now() - 60000) { toast("这个时间已经过去了"); return null; }
  const r = {
    id: "r" + newId().slice(1), text: t, at: ts,
    repeat: (opt && opt.repeat) || "", done: false, fired: false,
    from: (opt && opt.from) || "manual",
  };
  state.reminders.push(r);
  state.reminders.sort((a, b) => a.at - b.at);
  save(state);
  scheduleNative(r);
  logEvent("reminder", "yan", r.text);
  renderRemind();
  paintNavBadges();
  return r;
}

/* ---------- 重复提醒的「下一次」 ---------- */

/** 一条重复提醒的「下一次」：把 from 往后挪一个周期。repeat 为空返回 null。
 *
 *  monthly 走**自然月**，日期钳到月末：1 月 31 日的「每月」是 2 月 28 日，
 *  不是「+30 天」滚到 3 月 3 日。用 setDate(1) 再 setMonth 是因为直接 setMonth
 *  在 1 月 31 日会溢出成 3 月 3 日（JS 的 Date 就是这么算的）。
 *  daily / weekly 用 setDate 加日历天，不用 86400000 的倍数——夏令时那天会错一小时。 */
function runsOn(from, repeat) {
  const t = Number(from);
  if (!Number.isFinite(t)) return null;
  const d = new Date(t);
  if (repeat === "daily") d.setDate(d.getDate() + 1);
  else if (repeat === "weekly") d.setDate(d.getDate() + 7);
  else if (repeat === "monthly") {
    const day = d.getDate();
    d.setDate(1);
    d.setMonth(d.getMonth() + 1);
    // 下个月的天数：getMonth()+1 月的第 0 天就是这个月最后一天
    d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
  } else return null;
  const out = d.getTime();
  return out > t ? out : null;      // 钳到月末也没往前退，才认
}

/** 从 at 一路推到「比 now 晚」的第一次。at 本来就在未来就原样返回。
 *  一直过去很久的每日提醒要连推几百次（一年 365 次），这里一路 while 到底——
 *  上限 4000 只是防一个坏 repeat 把主线程占死，正常数据够不着。 */
function nextRunAfter(at, repeat, now) {
  const n = now || Date.now();
  let t = Number(at);
  if (!Number.isFinite(t) || !repeat) return null;
  let guard = 0;
  while (t <= n) {
    const x = runsOn(t, repeat);
    if (!x) return null;
    t = x;
    if (++guard > 4000) return null;
  }
  return t;
}

/** 把已经过了点的重复提醒推到下一次。返回推了几条。
 *
 *  为什么必须有这一步：系统里排的只是「下一次」那一条通知（见 scheduleNative），
 *  它响了之后就没有下一次了。而 App 可能几天没开——不开的时候谁也算不了，
 *  所以只能在**下次打开**时补上。这一步只改 `at` 与 `fired`，不改 `done`：
 *  「这一次发过了」和「这件事办完了」是两件事。
 *
 *  推了几条这件事要留在屏上直到用户动一下提醒：挪了哪个时间点是他没看着的时候
 *  发生的，只说一句就被下一次重画冲掉，等于没说。 */
let catchUpNote = 0;
let catchUpBusy = false;
function catchUpRepeats() {
  if (catchUpBusy) return 0;
  catchUpBusy = true;
  const now = Date.now();
  let n = 0;
  try {
    const list = state.reminders || [];
    list.forEach((r) => {
      if (r.done || !r.repeat || r.at > now) return;
      const nx = nextRunAfter(r.at, r.repeat, now);
      if (!nx) return;
      r.at = nx;
      r.fired = true;
      scheduleNative(r);          // 同一个通知 id 再排一次，等于把旧的换掉
      n++;
    });
    if (n) { state.reminders.sort((a, b) => a.at - b.at); save(state); paintNavBadges(); catchUpNote += n; }
  } finally {
    catchUpBusy = false;
  }
  return n;
}

/* ---------- 快速添加：屏内面板（不是 prompt） ---------- */

/** 面板开着没有；以及面板里选中的重复档。都是界面态，不进 state。 */
let quickOpen = false;
let quickRepeat = "";
/** 展开着「重复」那一排的是哪一条提醒（同言笺的 moveOpen / whenOpen，一屏只摊一排）。 */
let repOpen = "";

/** 从「一小时后 / 今晚 / 明天 / 后天」算一个时刻。
 *  今晚 20:30 已经过了就落到明天的 20:30（不然按下去只会得到一句「已经过去了」）。 */
function quickAt(kind, now) {
  const base = now || Date.now();
  if (kind === "1h") return base + 3600000;
  const d = new Date(base);
  if (kind === "evening") {
    d.setHours(20, 30, 0, 0);
    return d.getTime() > base ? d.getTime() : d.getTime() + 86400000;
  }
  if (kind === "tomorrow") { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d.getTime(); }
  if (kind === "3d") { d.setDate(d.getDate() + 3); d.setHours(9, 0, 0, 0); return d.getTime(); }
  return null;
}

/** 面板的 HTML。整块只在 quickOpen 时出现——不开的时候一枚控件都不摆，
 *  所以「按了没反应」那道门扫不到一堆永远没人点的签。 */
function renderQuickAdd() {
  if (!quickOpen) return "";
  const rep = (v, label) => `<button type="button" class="chip${quickRepeat === v ? " on" : ""}"
      data-rqrep="${v}" aria-pressed="${quickRepeat === v}">${label}</button>`;
  return `<div class="quick-add" id="remindQuick">
    <p class="tiny">新的一条提醒</p>
    <input type="text" id="rqText" maxlength="120" placeholder="提醒什么"
           aria-label="这条提醒要说什么" autocomplete="off" />
    <div class="chips" style="margin-top:10px">
      <button type="button" class="chip" data-rqwhen="1h">一小时后</button>
      <button type="button" class="chip" data-rqwhen="evening">今晚 20:30</button>
      <button type="button" class="chip" data-rqwhen="tomorrow">明天 09:00</button>
      <button type="button" class="chip" data-rqwhen="3d">后天 09:00</button>
    </div>
    <div class="row" style="margin-top:10px">
      <label class="quick-when">哪一天<input type="date" id="rqDay" aria-label="哪一天"></label>
      <label class="quick-when">几点<input type="time" id="rqTime" value="09:00" aria-label="几点"></label>
    </div>
    <p class="tiny" style="margin-top:14px">重复</p>
    <div class="chips" id="rqRepeatRow">
      ${rep("", "只一次")}${rep("daily", "每天")}${rep("weekly", "每周")}${rep("monthly", "每月")}
    </div>
    <div class="row" style="margin-top:14px">
      <button type="button" class="btn ghost" id="rqCancel">算了</button>
      <button type="button" class="btn" id="rqAdd">定下来</button>
    </div>
    <p class="tiny" style="margin-top:8px">到点靠系统通知，省电模式下会被攒着发——所以说的是「大约这个点」。</p>
  </div>`;
}

/** 面板里那一排控件的事件。整片重建之后由 renderRemind 重新绑。 */
function bindQuickAdd() {
  const box = $("#remindQuick");
  if (!box) return;
  const add = (text, at) => {
    const r = addReminder(text, at, { from: "manual", repeat: quickRepeat });
    // addReminder 失败（名字空 / 时间已过）时不收面板：用户还在那一格上，别把他的输入扔了
    if (!r) return;
    quickOpen = false;
    renderRemind();
    toast(`到 ${whenText(r.at)} 会叫你（大约这个点）`);
  };
  $$("#remindQuick [data-rqwhen]").forEach((b) => {
    b.onclick = () => {
      const t = $("#rqText");
      add(t ? t.value : "", quickAt(b.dataset.rqwhen));
    };
  });
  $$("#remindQuick [data-rqrep]").forEach((b) => {
    b.onclick = () => {
      quickRepeat = b.dataset.rqrep;
      // 就地换选中态：重建这一块会把上面刚打的字清掉
      $$("#remindQuick [data-rqrep]").forEach((x) => {
        const on = x.dataset.rqrep === quickRepeat;
        x.classList.toggle("on", on);
        x.setAttribute("aria-pressed", String(on));
      });
    };
  });
  const cancel = $("#rqCancel");
  if (cancel) cancel.onclick = () => { quickOpen = false; renderRemind(); };
  const ok = $("#rqAdd");
  if (ok) ok.onclick = () => {
    const t = $("#rqText");
    const day = $("#rqDay"), hm = $("#rqTime");
    const tv = t ? t.value : "";
    if (!String(tv || "").trim()) { toast("先写一句要提醒什么"); return; }
    if (!day || !day.value) { toast("还没挑哪一天；上面那几枚签也能直接定"); return; }
    const hmv = (hm && hm.value) || "09:00";
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.value);
    const h = /^(\d{1,2}):(\d{2})$/.exec(hmv);
    if (!m || !h) { toast("日期或时间没填全"); return; }
    const d = new Date(+m[1], +m[2] - 1, +m[3], +h[1], +h[2], 0, 0);
    add(tv, d.getTime());
  };
}

/** 打开一条「加提醒」的屏内面板。改之前这里是三个 prompt 连着问。
 *  为什么换掉（不是因为它跑不起来，它跑得起来）：连着三个系统弹框，
 *  每个都是 Material 的英文按钮、都阻塞一次 WebView，而「填数字 1-5 选时间」
 *  这种交互本身就是把键盘当菜单用——三次弹框才问出一件事，每一次都可能被误触关掉，
 *  关掉之后前面填的全丢。面板一次问全，答错还能回头改。 */
function quickAddReminder() {
  quickOpen = true;
  renderRemind();
  const box = $("#remindQuick");
  if (box && box.scrollIntoView) box.scrollIntoView({ block: "start", behavior: "smooth" });
  const t = $("#rqText");
  if (t) t.focus({ preventScroll: true });
}

/* ---------- 提醒总览 ---------- */

/** 通知权限那一句话。异步查，回来再填——查不到的浏览器里说清「装成 App 才有」。 */
function paintPermState() {  const el = $("#remindPermState");
  if (!el) return;
  const p = notifyPlugin();
  if (!p || !p.checkPermissions) {
    el.textContent = "浏览器里没有系统通知；装成 App 之后才有。";
    return;
  }
  Promise.resolve(p.checkPermissions()).then((res) => {
    const now = $("#remindPermState");
    if (!now) return;
    now.textContent = res && res.display === "granted"
      ? "通知权限开着，到点会走系统通知。"
      : res && res.display === "denied"
        ? "通知权限关着。到「设置 → 应用 → 笺 → 通知」里打开才有提醒。"
        : "通知权限还没问过。按下面「检查通知权限」会问一次。";
  }).catch(() => {
    const now = $("#remindPermState");
    if (now) now.textContent = "查不到通知权限的状态。";
  });
}

/** 提醒那一屏：分四段（已过期 / 今天 / 往后 / 办完），每天都读同一份 state.reminders。 */
function renderRemind() {
  const body = $("#remindBody");
  if (!body) return;
  catchUpRepeats();
  const now = startOfDay(Date.now());
  // 那几句「已经排到下一次」说的是「你没看着的时候 AI 把时间挪了」，
  // 所以它必须活到用户真的动一下提醒为止：不能画一次就清（重画一次就没了，
  // 而这一屏在进屏、勾选、改档之后都会重画），也不能一直挂着（久了变成背景噪声）。
  // 清它的时机只有一处：下面四个动作真的改动了提醒的时候。
  const pushed = catchUpNote;
  const tomorrow = addDays(now, 1);
  const list = (state.reminders || []).slice().sort((a, b) => a.at - b.at);
  const open = list.filter((r) => !r.done);
  const done = list.filter((r) => r.done);
  const overdue = open.filter((r) => r.at < Date.now());
  const todayR = open.filter((r) => r.at >= Date.now() && r.at < tomorrow);
  const later = open.filter((r) => r.at >= tomorrow);
  const repeats = open.filter((r) => r.repeat).length;

  const rowOf = (r) => {
    const openRep = repOpen === r.id;
    const others = ["", "daily", "weekly", "monthly"];
    // 铃铛这三档以前只写在 class 上（.on / .past / 都没有），没写 aria。
    // 事故：a11y_v06 第 9 节扫「每一处选中态都要有 aria」，全 App 17 处选中态里
    // **只有这一枚**是空的 —— 其余 16 处（引导页三张卡、各屏的 .chip）都写了 aria-pressed。
    // 也就是说这一行是那个约定唯一的例外，而不是约定本身有问题。
    // .on 是「这条提醒还立着」，.past 是「已经过了点」：前者对应 aria-pressed=true。
    // 只加属性，不动 onclick（铃铛的行为：办完的放回未办、没办的报一次时间）。
    const struck = r.at < Date.now() && !r.done;
    return `<div class="rem-row" data-rem="${esc(r.id)}">
      <span class="grow">
        <b>${esc(r.text)}</b>
        <span class="tiny">${esc(whenText(r.at))}${r.from === "yan" ? " · 从言笺来" : ""}</span>
      </span>
      <span class="rem-acts">
        <button class="bell${struck ? " past" : " on"}" data-rbell="${esc(r.id)}"
          aria-pressed="${!struck}"
          aria-label="${r.repeat ? "重复提醒" : "提醒"}，${esc(textOfRepeat(r))}">${r.repeat ? "↻" : "铃"}</button>
        <button class="stem-chip" data-rrep="${esc(r.id)}" aria-expanded="${openRep}"
          aria-label="这条提醒的重复设置，现在是${esc(textOfRepeat(r))}">${esc(textOfRepeat(r))}</button>
        <button class="stem-chip" data-rdone="${esc(r.id)}">${r.done ? "放回" : "办完了"}</button>
        <button class="stem-chip hdel" data-rdel="${esc(r.id)}" aria-label="删掉这条提醒">删</button>
      </span>
      ${openRep ? `<div class="move-chips">${others.map((k) =>
        `<button type="button" class="chip${r.repeat === k ? " on" : ""}" data-rrep-to="${k}" data-rrep-i="${esc(r.id)}">${k ? repeatName(k) : "只一次"}</button>`
      ).join("")}</div>` : ""}
    </div>`;
  };

  const sec = (title, arr, cls) => arr.length ? `<p class="tiny rem-sec"${cls ? ` style="${cls}"` : ""}>${title}</p>
    <div class="list rem-list">${arr.map(rowOf).join("")}</div>` : "";

  body.innerHTML = `
    <!-- 这一屏（#yan-remind）没有 h1：它是从言笺翻过来的子页，顶栏那行 .brand「言 · 提醒」
         是眉料不是标题，于是读屏器的标题列表里这一屏**没有任何标题**，换屏之后也念不出
         「到了哪儿」。补一个只给读屏器的 h1（.sr-only，不占版面），文字就是这一屏的名字。 -->
    <h1 class="sr-only">提醒</h1>
    <p class="tiny" id="remindPermState">在查通知权限…</p>
    ${pushed ? `<p class="tiny catch-note" style="margin-top:8px">${pushed} 条重复提醒已经排到下一次（上一次的时间已经过了）</p>` : ""}
    <p class="tiny" style="margin-top:8px">提醒：${open.length} 条没办${repeats ? `（其中 ${repeats} 条重复）` : ""}${done.length ? `，${done.length} 条办完了` : ""}</p>
    ${overdue.length ? `<p class="tiny" style="margin-top:10px;color:var(--seal)">已经过去 ${overdue.length} 条</p>` : ""}
    ${renderQuickAdd()}
    ${sec("已经过期", overdue)}
    ${sec("今天之内", todayR)}
    ${sec("往后", later)}
    ${!open.length ? `<div class="empty"><div class="empty-印" aria-hidden="true">铃</div>
      还没有提醒。<br>在言笺里给一条句子点「铃」就能定时间。</div>` : ""}
    ${done.length ? sec(`办完了 · ${done.length}`, done) : ""}
    <div class="space"></div>
    <p class="tiny">到点提醒走的是系统通知。手机在省电模式里，系统会把通知攒着一起发——
      所以这里说的是「大约这个点」。</p>
    <div class="space"></div>
    <div class="row">
      <button class="btn ghost" id="remindPerm">检查通知权限</button>
      <button class="btn ghost" id="remindAdd">${quickOpen ? "收起面板" : "加一条提醒"}</button>
    </div>`;

  paintPermState();
  bindQuickAdd();
  // 用户真的动过提醒了：「时间自己挪过」那句到此为止。
  // 只在这一处清，四个动作都挂在它上面——散在四处等于四处都会漏。
  const usedUpNote = () => { catchUpNote = 0; };
  $$("#remindBody [data-rdone]").forEach((b) => {
    b.onclick = () => {
      const r = state.reminders.find((x) => x.id === b.dataset.rdone);
      if (!r) return;
      usedUpNote();
      r.done = !r.done;
      if (r.done) cancelNative(r);
      else {
        // 放回一条已经过了点的重复提醒：先把时间推到下一次，否则会立刻又显示「已经过去」
        if (r.repeat && r.at <= Date.now()) {
          const nx = nextRunAfter(r.at, r.repeat, Date.now());
          if (nx) r.at = nx;
        }
        scheduleNative(r);
      }
      save(state); renderRemind(); paintNavBadges();
      toast(r.done ? `办完了：${r.text}` : `放回未办：${r.text}`);
    };
  });
  $$("#remindBody [data-rdel]").forEach((b) => {
    b.onclick = () => {
      const i = state.reminders.findIndex((x) => x.id === b.dataset.rdel);
      if (i < 0) return;
      usedUpNote();
      const snap = state.reminders[i];
      cancelNative(snap);
      state.reminders.splice(i, 1);
      save(state); renderRemind(); paintNavBadges();
      toastUndo(`已删掉提醒「${snap.text}」`, () => {
        state.reminders.splice(Math.min(i, state.reminders.length), 0, snap);
        state.reminders.sort((a, b2) => a.at - b2.at);
        save(state); scheduleNative(snap); renderRemind(); paintNavBadges();
      });
    };
  });
  // 重复档：展开 / 收起来
  $$("#remindBody [data-rrep]").forEach((b) => {
    b.onclick = () => {
      repOpen = repOpen === b.dataset.rrep ? "" : b.dataset.rrep;
      renderRemind();
    };
  });
  $$("#remindBody [data-rrep-to]").forEach((b) => {
    b.onclick = () => {
      const r = state.reminders.find((x) => x.id === b.dataset.rrepI);
      if (!r) return;
      usedUpNote();
      r.repeat = b.dataset.rrepTo;
      // 改成重复之后，如果原时间已经过了，就推到下一次——不然它一辈子停在「已经过去」
      if (r.repeat) {
        const nx = nextRunAfter(r.at, r.repeat, Date.now());
        if (nx && r.at <= Date.now()) r.at = nx;
      }
      repOpen = "";
      save(state); cancelNative({ id: r.id }); scheduleNative(r); renderRemind(); paintNavBadges();
      toast(r.repeat ? `改成${repeatName(r.repeat)}了` : "改回只提醒一次了");
    };
  });
  // 铃铛：把一条已经办完的放回（点铃铛本身不改时间，只把它拉回未办）
  $$("#remindBody [data-rbell]").forEach((b) => {
    b.onclick = () => {
      const r = state.reminders.find((x) => x.id === b.dataset.rbell);
      if (!r) return;
      if (r.done) {
        usedUpNote();
        r.done = false; save(state); scheduleNative(r); renderRemind(); paintNavBadges();
        toast(`放回未办：${r.text}`);
        return;
      }
      toast(`${whenText(r.at)}${r.repeat ? ` · ${repeatName(r.repeat)}` : ""}（大约这个点）`);
    };
  });
  const perm = $("#remindPerm");
  if (perm) perm.onclick = () => checkNotifyPermission(true);
  const addBtn = $("#remindAdd");
  if (addBtn) addBtn.onclick = () => {
    quickOpen = !quickOpen;
    renderRemind();
    if (quickOpen) { const t = $("#rqText"); if (t) t.focus({ preventScroll: true }); }
  };
}

/** 时间的说法：今天 20:30 / 明天 09:00 / 3 天后 / 10月21日 09:00。 */
function whenText(at) {
  const d = new Date(at);
  const today = startOfDay(Date.now());
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const dayDiff = Math.round((startOfDay(at) - today) / 86400000);
  if (at < Date.now()) return `已经过了 · ${shortDay(at)} ${hm}`;
  if (dayDiff === 0) return `今天 ${hm}`;
  if (dayDiff === 1) return `明天 ${hm}`;
  if (dayDiff < 7) return `${dayDiff} 天后 ${hm}`;
  return `${shortDay(at)} ${hm}`;
}
function repeatName(r) {
  return { daily: "每天", weekly: "每周", monthly: "每月" }[r] || "";
}
function textOfRepeat(r) {
  return r.repeat ? repeatName(r.repeat) : "一次";
}

/* ---------- 与言笺条目打通 ---------- */

/** 给一条言笺条目定提醒：它的 when 直接当默认时间。 */
function remindYanCard(card, at) {
  const ts = Number(at) || (card && card.when && card.when.at) || (Date.now() + 3600000);
  const r = addReminder(card.line, ts, { from: "yan" });
  if (r) toast(`到 ${whenText(ts)} 会叫你（大约这个点）`);
  return r;
}

/* ==================== 每日摘录 ==================== */

/** 摘录的心情：0 = 没标。用字不用 emoji——这张纸上不摆表情包。 */
const DIGEST_MOODS = ["没标", "轻", "沉", "亮", "重"];
function digestMoodName(v) {
  const i = Number(v) || 0;
  return DIGEST_MOODS[i >= 0 && i < DIGEST_MOODS.length ? i : 0];
}

/** 一天最多一条摘录：同一天再写就覆盖当天那条（那不是「新增」，是「我改主意了」）。
 *  **覆盖必须在界面上说清**：摘录本里今天那一句上面写着「再写会换掉它」。 */
function addDigest(text, from, mood) {
  const t = String(text || "").trim().slice(0, 200);
  if (!t) { toast("还没写内容"); return null; }
  const today = dayStr(Date.now());
  const same = (state.digest || []).find((d) => dayStr(d.t) === today);
  if (same) {
    same.text = t; same.from = String(from || "").slice(0, 40); same.mood = Number(mood) || 0;
    save(state);
    logEvent("note", "yan", t);
    toast("今天这一句换成了新的");
    paintDigestBody();
    return same;
  }
  const d = { t: Date.now(), text: t, from: String(from || "").slice(0, 40), mood: Number(mood) || 0 };
  state.digest.push(d);
  save(state);
  logEvent("note", "yan", t);
  paintDigestBody();
  return d;
}

/** 每天的「一句」：手写一句，或者从今天捞出来的言笺里挑一句最像「值得记」的。 */
function dailyLine() {
  const today = dayStr(Date.now());
  const mine = (state.digest || []).find((d) => dayStr(d.t) === today);
  if (mine) return { text: mine.text, mine: true };
  const cards = (state.yanCards || []).filter((c) => c.k === "还没说清" || c.k === "已定");
  const pick = seededPick(cards, 1, "digest")[0];
  return pick ? { text: pick.line, mine: false } : null;
}

/* ---------- 摘录本（言笺页内的一块折叠区） ---------- */

/** 写这一句时选中的心情；与「摘录本」这个 details 的展开态一起，都是界面态。 */
let digestMood = 0;
/** 摘录本摊开着没有。不进 state（「我正看着哪里」是界面态），但要在重画之间记住：
 *  不然每按一下铃铛它就自己合上，正在写的那一句也跟着没了。 */
let digestOpen = false;

/** 摘录本那一块的外壳。由 yan.js 的 renderYan 插进言笺那张纸里——
 *  它是言笺的东西（一句话），不该长成第二个子页。 */
function digestSheetHTML() {
  const n = (state.digest || []).length;
  return `<div class="rule"></div>
    <details class="drawer digest-book" id="yanDigestBook"${digestOpen ? " open" : ""}>
      <summary>摘录本${n ? ` · ${n} 句` : ""}</summary>
      <div class="drawer-body" id="digestBody"></div>
    </details>`;
}

/** 把这块折叠区接上：展开态记进 digestOpen，摊开时现画内容（合着时不白扫 60 条）。 */
function bindDigestSheet() {
  const det = $("#yanDigestBook");
  if (!det) return;
  if (det.open) paintDigestBody();
  det.addEventListener("toggle", () => {
    digestOpen = det.open;
    if (det.open) paintDigestBody();
  });
}

/** 把摘录本里那一块重画（只动 #digestBody，不动整屏：details 的展开态、
 *  以及上面输入框里还没提交的字，都不该被重画冲掉）。 */
function paintDigestBody() {
  const box = $("#digestBody");
  if (!box) return;
  const all = (state.digest || []).slice().sort((a, b) => b.t - a.t);
  const today = dayStr(Date.now());
  const hasToday = all.some((d) => dayStr(d.t) === today);
  const rows = all.map((d, i) => `<div class="digest-row">
      <span class="dg-date">${esc(dayStr(d.t).slice(5).replace(".", "·"))}</span>
      <span class="dg-main">
        <span class="dg-text">${esc(d.text)}</span>
        ${d.from ? `<span class="tiny">${esc(d.from)}</span>` : ""}
      </span>
      <span class="dg-acts">
        <button class="stem-chip" data-dgmood="${i}" aria-label="改这一句的心情，现在是${esc(digestMoodName(d.mood))}">${esc(digestMoodName(d.mood))}</button>
        <button class="stem-chip" data-dgcopy="${i}">复制</button>
        <!-- 长图 lane 追加（v0.6.0）：一句摘录 = 一张书签，所以入口就摆在那一句旁边。
             .stem-chip 自带 44px 热区，够得着；这一枚不改上面那三枚的任何一行。 -->
        <button class="stem-chip" data-dgsave="${i}" aria-label="把这一句存成一张长图">存图</button>
        <button class="stem-chip hdel" data-dgdel="${i}" aria-label="删掉这一句">删</button>
      </span>
    </div>`).join("");

  box.innerHTML = `
    ${all.length ? `<div class="stack digest-stack">${rows}</div>`
      : `<p class="tiny">还没有摘录。一天一句就够——只留你真的想再看一遍的。</p>`}
    <div class="space"></div>
    <label class="field"><span>${hasToday ? "今天这一句（再写会换掉上面那条今天的）" : "今天这一句"}</span>
      <input type="text" id="dgNew" maxlength="200" autocomplete="off"
             placeholder="今天想记下哪一句" aria-label="今天想记下哪一句" />
    </label>
    <div class="chips" id="dgMoodRow">
      ${DIGEST_MOODS.map((m, i) => `<button type="button" class="chip${digestMood === i ? " on" : ""}"
        data-dgmood-pick="${i}" aria-pressed="${digestMood === i}">${m}</button>`).join("")}
    </div>
    <div class="row" style="margin-top:12px">
      <button class="btn ghost" id="dgSave">记下来</button>
    </div>
    <!-- 长图 lane 追加（v0.6.0）：把最新那一句存成一张 1080×1920 的书签。
         摘录本空着时这一枚被标 aria-disabled —— 但**照样能聚焦、能按下**，
         按下去会说清楚「先写一句」；真 disabled 会让读屏器连这个问题都问不到。 -->
    <div class="row" style="margin-top:10px">
      <button class="btn ghost wide" id="dgSaveCard"${all.length ? "" : ` aria-disabled="true"`}>把最新一句存成长图</button>
    </div>
    <p class="tiny" style="margin-top:6px">长图是 1080 × 1920 的一张浅纸，一句话、一个日子、一枚印——像一张书签，不会跟着你手机的深色模式变黑。</p>`;


  $$("#digestBody [data-dgmood-pick]").forEach((b) => {
    b.onclick = () => {
      digestMood = +b.dataset.dgmoodPick;
      // 就地换选中态：这一块重建会把上面输入框里刚打的字清掉
      $$("#digestBody [data-dgmood-pick]").forEach((x) => {
        const on = +x.dataset.dgmoodPick === digestMood;
        x.classList.toggle("on", on);
        x.setAttribute("aria-pressed", String(on));
      });
    };
  });
  const saveBtn = $("#dgSave");
  if (saveBtn) saveBtn.onclick = () => {
    const t = $("#dgNew");
    const v = t ? t.value : "";
    if (!String(v || "").trim()) { toast("还没写内容"); return; }
    const d = addDigest(v, "", digestMood);
    if (d && t) t.value = "";
    if (d) toast("记进摘录了");
  };
  const newIn = $("#dgNew");
  if (newIn) newIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); const b = $("#dgSave"); if (b) b.click(); }
  });
  $$("#digestBody [data-dgcopy]").forEach((b) => {
    b.onclick = () => {
      const d = all[+b.dataset.dgcopy];
      if (d) copy(d.text, "已复制这一句");
    };
  });
  $$("#digestBody [data-dgmood]").forEach((b) => {
    b.onclick = () => {
      const d = all[+b.dataset.dgmood];
      if (!d) return;
      // 点一下换一档：没标 → 轻 → 沉 → 亮 → 重 → 没标
      d.mood = ((Number(d.mood) || 0) + 1) % DIGEST_MOODS.length;
      save(state); paintDigestBody();
      toast(d.mood ? `这句的心情改成了「${digestMoodName(d.mood)}」` : "这句的心情清掉了");
    };
  });
  $$("#digestBody [data-dgdel]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.dgdel;
      const d = all[i];
      if (!d) return;
      const at = state.digest.indexOf(d);
      if (at < 0) return;
      state.digest.splice(at, 1);
      save(state); paintDigestBody();
      // 摘录那条徽章读的就是条数，删了要跟着收
      toastUndo(`已删掉「${String(d.text).slice(0, 14)}」这一句`, () => {
        state.digest.splice(Math.min(at, state.digest.length), 0, d);
        save(state); paintDigestBody();
      });
    };
  });

  /* ---- 长图 lane 追加（v0.6.0）：摘录长图 ----
   *  两处入口，走同一个函数：行上那一枚「存图」（存这一句），
   *  以及底下那枚 wide 的「把最新一句存成长图」。
   *  存图链路复用 card.js 的 saveLongCard（= saveYearCard 那一套：
   *  原生 → Filesystem + 系统分享，浏览器 → 下载），这里不另写第二份下载逻辑。
   *
   *  空的时候两枚都说话（toast），**不静默**：aria-disabled 的钮按得下去。 */
  const saveDigest = (d, btn) => {
    if (!d) { toast("先写一句，才存得出这张书签"); return; }
    if (typeof drawQuoteCard !== "function" || typeof saveLongCard !== "function") {
      toast("长图还没准备好"); return;
    }
    saveLongCard(() => drawQuoteCard(d), longFileName("言笺-摘录", String(d.text).slice(0, 12)), btn);
  };
  $$("#digestBody [data-dgsave]").forEach((b) => {
    b.onclick = () => saveDigest(all[+b.dataset.dgsave], b);
  });
  const dgCard = $("#dgSaveCard");
  if (dgCard) {
    dgCard.onclick = () => saveDigest(all[0], dgCard);   // all 是倒序的，[0] 就是最新那一句
    // 空着也照样能按：按下去由 saveDigest 发言，而不是提前把钮收起来
    dgCard.setAttribute("aria-disabled", all.length ? "false" : "true");
  }
}

/** 「摘一句」那一枚按钮的入口（app.js 的 #yanDigestBtn 走这里）。
 *  以前它是一句 prompt：**能弹出来**（Capacitor 实现了 onJsPrompt），
 *  但一次只能问一行字，而且问完就没有下文——改不了、删不掉、看不到昨天那句。
 *  现在展开摘录本、滚过去、把光标放进输入框。 */
function openDigestSheet() {
  const det = $("#yanDigestBook");
  if (!det) { show("yan"); toast("先捞一张笺，摘录本就在那张纸下面"); return; }
  det.open = true;
  digestOpen = true;
  paintDigestBody();
  if (det.scrollIntoView) det.scrollIntoView({ block: "start", behavior: "smooth" });
  const t = $("#dgNew");
  if (t) t.focus({ preventScroll: true });
}

/* ==================== 原生通知（安卓） ==================== */

/** Capacitor 的 LocalNotifications 只在原生壳里存在；浏览器里静默。
 *  这里所有调用都必须 try/catch：通知没排上不该毁掉用户刚做的动作。 */
function notifyPlugin() {
  if (!hasNative()) return null;
  try { return nativePlugins().LocalNotifications || null; } catch (_) { return null; }
}
/** 通知 id 必须是 32 位 int：用字符串哈希，稳定且不撞。 */
function notifId(id) {
  let h = 0;
  const s = String(id || "");
  for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) | 0; }
  return Math.abs(h) || 1;
}

/** 排一条通知。重复提醒也只排**下一次**那一条：系统里那条响了之后就没有了，
 *  由 catchUpRepeats() 在下次打开 App 时补——**不自己起定时器**：
 *  WebView 在后台会被冻结，自己算时间必然错过。
 *
 *  `isExactNotification: false` 这一行不是可选的：插件的默认值是 true，
 *  而这一版**刻意没有申请 SCHEDULE_EXACT_ALARM**（它是 Play 的受限权限，
 *  我们承诺的也只是「大约这个点」）。少了这一行，安卓 12+ 每次排一条提醒都会
 *  先把用户甩进系统「闹钟和提醒」设置页，从那里回来才继续排——那不是提醒，
 *  那是每定一条提醒就打断用户一次。 */
function scheduleNative(r) {
  // App 内关掉通知必须阻止所有新排程；取消旧队列还不够，后续新增/修改提醒也会走这里。
  if (state.settings && state.settings.notify === false) return;
  const p = notifyPlugin();
  if (!p || !p.schedule) return;
  const one = {
    id: notifId(r.id), title: "笺 · 提醒", body: r.text,
    schedule: { at: new Date(r.at), allowWhileIdle: true },
    isExactNotification: false,
    smallIcon: "ic_stat_jian", channelId: "jian-remind",
  };
  try {
    Promise.resolve(p.schedule({ notifications: [one] })).catch((e) => console.warn("notify", e));
  } catch (e) { console.warn("notify", e); }
}
function cancelNative(r) {
  const p = notifyPlugin();
  if (!p || !p.cancel) return;
  try { Promise.resolve(p.cancel({ notifications: [{ id: notifId(r.id) }] })).catch(() => { }); } catch (_) { }
}
/** 清空全部通知（「清空本地数据」时必须调，否则清完之后还会弹）。 */
function cancelAllNative() {
  const p = notifyPlugin();
  if (!p || !p.cancelAll) return;
  try { Promise.resolve(p.cancelAll()).catch(() => { }); } catch (_) { }
}

/** 请求通知权限。Android 13+ 是运行时权限，拒绝一次之后系统不再弹框，只能去设置里开。
 *  所以拒绝之后给的是**出路**不是「再试一次」——这条逻辑必须保留，
 *  它对着的是 Android 13 的真实行为，不是我们的偏好。 */
function checkNotifyPermission(explicit) {
  const p = notifyPlugin();
  if (!p || !p.checkPermissions) {
    if (explicit) toast("浏览器里没有系统通知；装成 App 之后才有");
    return Promise.resolve(false);
  }
  return Promise.resolve(p.checkPermissions()).then((res) => {
    if (res && res.display === "granted") {
      if (explicit) toast("通知权限已开");
      return true;
    }
    if (res && res.display === "denied" && reminderPermAsked) {
      // 已经问过一次还被拒：系统不会再弹，只能指路
      toast("通知被系统关着。到「设置 → 应用 → 笺 → 通知」里打开");
      return false;
    }
    reminderPermAsked = true;
    return Promise.resolve(p.requestPermissions()).then((r2) => {
      const ok = r2 && r2.display === "granted";
      if (explicit) toast(ok ? "通知权限已开" : "没开通知权限，到系统设置里可以打开");
      return ok;
    }).catch(() => false);
  }).catch(() => false);
}

/** 开机时把没办完的提醒重新排一遍。
 *  为什么必须重排：系统的通知队列不跨重装、也可能被用户手动清掉；
 *  而「我明明设了提醒它没响」是这个功能最伤人的失败方式。
 *  重复提醒先补到下一次（catchUpRepeats），否则开机排的是一条早就过期的通知。
 *
 *  **它以前是死代码**：全仓只有这一处定义、零个调用点（用计数打点确认过 called: 0）。
 *  于是「开机重排」这句注释描述的事从来没发生过——重装之后、系统清过队列之后，
 *  那些没到点的提醒一条都不会响，除非用户自己进一趟「提醒」总览（那才走到 catchUpRepeats）。
 *  现在由 app.js 的 boot() 在数据恢复之后调它。 */
function rescheduleAll() {
  const p = notifyPlugin();
  if (!p) return;
  // 重启恢复时也遵守用户的选择，并清掉系统里可能残留的旧通知。
  if (state.settings && state.settings.notify === false) { cancelAllNative(); return; }
  catchUpRepeats();
  (state.reminders || []).filter((r) => !r.done && r.at > Date.now()).forEach(scheduleNative);
}
