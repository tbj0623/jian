/** 笺 · 启动
   只剩事件绑定与开机流程；界面分在 state / ui / yi / wei / yan / me，长图在 card.js。 */

/* ---------- 启动 ---------- */

/** 开机时保险丝有没有真的捞回过数据。「清空本地数据」之后它必须是 false：
 *  true 就等于「那一下没清干净，系统里还留着一份」，「已清空」三个字就不能说。 */
let fuseRefilled = false;

/** 开机要报告的事不止一件，而提示区一次只放得下一条（第 38 轮定的：两条都能撤销的界面
 *  反而更难解释）。所以先攒着，等最后开口的那一条把它带上。
 *  不攒会怎样：第 50 轮那句「已导入」会把「言笺少 3 条」顶掉——而后者报的是**丢了数据**。
 *  一句被另一句吃掉，商店文案里那句「不会悄悄少掉」就当场成了假话。 */
let bootNotes = [];
function joinBootNotes(text) {
  const s = bootNotes.filter(Boolean).join("；");
  bootNotes = [];
  return s ? (text ? `${text}。${s}` : s) : text;
}

/** 引导页这三张卡是这一轮最后查出的一处「状态由 DOM 自己写」：class 与 aria-pressed 以前只在
 *  onclick 里刷，于是 {onboarded:false, home:"yan"} 这样一份备份一导入（normalizeState 把
 *  onboarded 与 home 当两个互不相干的字段），屏上说「衣已选」而 state 里是 yan：描边和读屏器
 *  一起说谎。所以同步挂在**进屏**这一路上（ui.js 的 show），不只挂在 boot —— 以后哪条新路子
 *  走进引导页都不会漏。onclick 也只调这一个函数：只有这一处算「谁被选中」。 */
function paintModeCards() {
  $$("#onboard .mode-card").forEach((x) => {
    const on = x.dataset.home === state.home;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
}

async function boot() {
  // 原生壳里先把备份保险丝走完（localStorage 空而 Preferences 有备份则恢复），
  // 再画界面。file:// 无 Capacitor，这一步是空操作。
  try {
    if (await restoreNativeBackup()) {
      fuseRefilled = true;
      const restored = load();
      if (restored) state = normalizeState(restored);
    }
  } catch (e) { console.warn(e); }
  registerNativeBack();
  paintNativeChrome();
  /* 把没办完的提醒重新排一遍。以前这一步写在 remind.js 里但**没有任何地方调它**：
     重装之后、系统清过通知队列之后，没到点的提醒一条都不会响——而「我明明设了提醒
     它没响」是这个功能最伤人的失败方式。
     放在这里（数据已经救回来、界面还没画之前）的两个理由：
       · 必须等保险丝恢复完，否则排的是旧的那一份；
       · 排程是异步的、不阻塞首帧，早一点排就能早一点被系统接管。
     浏览器里 notifyPlugin() 为 null，这个函数是空操作。 */
  try { if (typeof rescheduleAll === "function") rescheduleAll(); } catch (e) { console.warn("reschedule", e); }

  paintNav();
  renderCloset();
  renderWeiPeople();
  renderWallet();
  hintEngine();
  // 外观：主题/字号/印章款式要在「数据已经救回来」之后才刷（见 theme.js 末尾那段注释）。
  // 提前刷会拿一份还没恢复的设置去改根节点，屏幕上就是「上一台设备关掉之前的主题」。
  try { THEME.init(); } catch (e) { console.warn("theme", e); }
  // 口志里读不懂的条目没进来：屏幕上少了几条却不是用户删的，得说一声。
  // v0.6.0 新增的九类集合各有自己的 normLoss（备份里形状不对的条目一律丢弃并计数）。
  {
    const bits = [];
    const names = { cards: "言笺", album: "笺册", wish: "愿望单", recipes: "菜谱", outfits: "搭配",
      cook: "做过的菜", market: "买菜清单", weeks: "一周菜单", digest: "摘录",
      reminders: "提醒", log: "行为记录", drafts: "草稿" };
    Object.keys(names).forEach((k) => { if (normLoss[k]) bits.push(`${names[k]}少 ${normLoss[k]} 条`); });
    if (bits.length) bootNotes.push(bits.join("，") + "（备份里这几条形状不对，没放进来）");
  }

  // 深链：H5 看地址里的 #言，原生先看冷启动带进来的 jian://（快捷方式），
  // 之后每次热启动由 appUrlOpen 事件接着。原生这条在浏览器里整段跳过，返回 null。
  let deep = screenOf(location.hash);
  const app = hasNative() ? nativePlugins().App : null;
  if (app) {
    try {
      const l = await app.getLaunchUrl();
      if (l && l.url) deep = screenOf(l.url) || deep;
      if (app.addListener) app.addListener("appUrlOpen", (d) => openDeep(d && d.url));
    } catch (e) { console.warn("deep link", e); }
  }
  // 引导页那三张卡的选中态由 paintModeCards() 统一刷，入口在 ui.js 的 show()（进屏就刷）。
  // 首屏落点。快捷方式进的是「哪一笺」，不是「哪一屏的哪一步」，所以没勾完引导时
  // 仍然先看引导：引导要选的是「打开即是哪一笺」，让快捷方式替它答了会存错偏好。
  const enter = () => { if (!deep || !openDeep(deep)) show(state.home); };
  if (!state.onboarded) show("onboard");
  else enter();
  window.addEventListener("hashchange", () => openDeep(location.hash));

  // 启动画面不在这里管。capacitor.config 里 launchShowDuration=0，SplashScreen 插件全程不参与，
  // 系统那层启动图（Theme.SplashScreen 的纸底 + 印章）由框架自己在「应用第一帧」撤掉。
  // 试过在这里画完后再调 SplashScreen.hide() 来缩短交接：结果是把启动图提前撤走，
  // 露出 WebView 尚未合成的表面 = 实测几秒纯黑，反而更糟。

  $$("#onboard .mode-card").forEach((c) => {
    c.onclick = () => {
      state.home = c.dataset.home;
      paintModeCards();   // 只有一条算「谁被选中」的口径：读 state.home，不读 class
    };
  });
  $("#go").onclick = () => { state.onboarded = true; save(state); paintNav(); enter(); };

  /* ==================== v0.6.0：新屏与页签的接线 ====================
     所有「哪一屏、哪一页签、点了之后干什么」都在这里收口。各模块文件只提供渲染函数，
     绑事件留在 boot() —— 这样「有没有人绑它」可以在一个地方看完。 */

  // 页签：键盘也要走得通（左右方向键在页签之间移动，这是 ARIA tabs 的约定）
  const tabKeys = (host, attr, setter) => {
    $$(host + " [" + attr + "]").forEach((b) => {
      b.onclick = () => setter(b.getAttribute(attr));
      b.onkeydown = (e) => {
        const all = $$(host + " [role=tab]");
        const i = all.indexOf(b);
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const n = all[(i + (e.key === "ArrowRight" ? 1 : all.length - 1)) % all.length];
          n.focus(); setter(n.getAttribute(attr));
        }
      };
    });
  };
  tabKeys("#yiTabs", "data-yitab", (t) => { yiTab = t; setYiTab(t); });
  tabKeys("#weiTabs", "data-weitab", (t) => { weiTab = t; setWeiTab(t); });

  // 返回键（各子页 topbar 上那一枚）。口径同安卓返回键：都是 goBack()。
  ["#backYi", "#backItem", "#backOutfit", "#backDish", "#backWeek", "#backRemind",
    "#backSettings", "#backBadges", "#backYear", "#backSearch", "#backPu"].forEach((sel) => {
      const el = $(sel);
      if (el) el.onclick = () => { if (!goBack()) show(state.home || "yi"); };
    });

  // 衣笺：愿望单
  const addWishBtn = $("#addWish");
  if (addWishBtn) addWishBtn.onclick = () => {
    const w = addWish($("#wishName").value, $("#wishPrice").value);
    if (w) { $("#wishName").value = ""; $("#wishPrice").value = ""; paintTabCounts(); }
  };
  const wishNameEl = $("#wishName");
  if (wishNameEl) wishNameEl.addEventListener("keydown", (e) => { if (e.key === "Enter") $("#addWish").click(); });
  const wishLast = $("#wishFromLast");
  if (wishLast) wishLast.onclick = () => {
    const r = state.lastReport;
    if (!r || !r.new) { toast("还没有过笺的记录，先过一张"); return; }
    const name = r.item && r.item.name ? r.item.name : "想买的这件";
    const w = addWish(name, r.item && r.item.price, r.item && r.item.cat, r.item && r.item.color);
    if (w) { toast(`「${w.name}」进了愿望单，三天后回来看还想不想买`); paintTabCounts(); }
  };

  // 味笺：做菜 / 买菜 / 这周
  const dishSearch = $("#dishSearch");
  if (dishSearch) dishSearch.oninput = () => { dishQuery = dishSearch.value; renderCook(); };
  const wheelBtn = $("#wheelBtn");
  if (wheelBtn) wheelBtn.onclick = spinWheel;
  const newRecipe = $("#newRecipe");
  if (newRecipe) newRecipe.onclick = () => {
    const n = prompt("这道菜叫什么？");
    if (n && String(n).trim()) openRecipeEditor(String(n).trim().slice(0, 30));
  };
  const addMarketBtn = $("#addMarket");
  if (addMarketBtn) addMarketBtn.onclick = () => {
    const v = $("#marketName").value;
    if (!String(v || "").trim()) { toast("先写要买什么"); return; }
    const n = addMarketItems([v], "");
    $("#marketName").value = "";
    if (n) { toast("加进清单了"); haptic("LIGHT"); }
    else toast("这一样已经在清单里");
    paintTabCounts();
  };
  const marketInput = $("#marketName");
  if (marketInput) marketInput.addEventListener("keydown", (e) => { if (e.key === "Enter") $("#addMarket").click(); });

  // 言笺：提醒总览 / 摘一句
  const yanRemind = $("#yanRemindBtn");
  if (yanRemind) yanRemind.onclick = () => show("yan-remind");
  const yanDigest = $("#yanDigestBtn");
  if (yanDigest) yanDigest.onclick = () => {
    // 这里原来是 `prompt("今天想记下哪一句？", 今日推荐句)`。
    // 换成屏内摘录本的真实理由（**不是**「WebView 禁掉了 prompt」——Capacitor 的
    // BridgeWebChromeClient 会把它转成一个原生 AlertDialog，能用的）：
    //  1. 那个原生框是 Material 的，英文 OK / Cancel，配色跟这张纸完全无关；
    //  2. 它只能问一行字，而摘录本来是一整本书（历史每一句、心情四档、复制、删除带撤销）；
    //  3. 它是阻塞式的：框没关，WebView 里一个字节都动不了。
    // 现在交给 remind.js 的 openDigestSheet()：展开言笺纸下面的摘录本、滚过去、把光标放进输入框，
    // 今日推荐那一句变成输入框的 placeholder（原来它是 prompt 的默认值）。
    // 兜底那一句不是摆设：openDigestSheet 要先有 #yanDigestBook 才动得了（摘录本挂在言笺纸里），
    // 没捞过笺的时候那一块还不存在，得让人知道按下去为什么没动静。
    if (typeof openDigestSheet === "function") openDigestSheet();
    else toast("摘录本还没准备好");
  };

  // 册：三个入口
  const openSettings = $("#openSettings");
  if (openSettings) openSettings.onclick = () => show("settings");
  const openSearch = $("#openSearch");
  if (openSearch) openSearch.onclick = () => show("search");
  const openBadges = $("#openBadges");
  if (openBadges) openBadges.onclick = () => show("badges");

  // 今日：抽一笺 / 这一年
  const todayJian = $("#todayJian");
  if (todayJian) todayJian.onclick = () => { renderToday(); toast("换了一笺"); };
  const todayYear = $("#todayYear");
  if (todayYear) todayYear.onclick = () => show("year");

  // 笺谱
  const puBody = $("#puBody");
  if (puBody) { /* 入口在 renderPu 里绑 */ }

  // 全局搜索：敲字即搜
  const gs = $("#globalSearch");
  if (gs) gs.oninput = () => doSearch(gs.value);

  $("#fileCloth").onchange = (e) => { const f = e.target.files[0]; if (f) addClothFile(f); e.target.value = ""; };
  $("#fileNew").onchange = (e) => { const f = e.target.files[0]; if (f) runYi(f); e.target.value = ""; };
  $("#fileCam").onchange = (e) => { const f = e.target.files[0]; if (f) runYi(f); e.target.value = ""; };
  // 补照片走的是「改这一件」而不是「再入柜一件」：目标就是操作条上正选着的那件
  $("#fileRephoto").onchange = (e) => { const f = e.target.files[0]; if (f) rephotoCloth(f); e.target.value = ""; };
  $("#fileRecam").onchange = (e) => { const f = e.target.files[0]; if (f) rephotoCloth(f); e.target.value = ""; };
  $("#scanBtn").onclick = () => $("#fileNew").click();
  $("#camBtn").onclick = () => { haptic("LIGHT"); $("#fileCam").click(); };
  $("#heroCloth").onclick = () => $("#fileNew").click();   // 首屏那块纸本身就是入口
  $("#backYi").onclick = () => show("yi");
  $("#toCloset").onclick = reportToCloset;
  $("#saveCard").onclick = saveCard;
  $("#copyReport").onclick = copyReportText;
  $("#switchStyle").onclick = () => {
    state.reportStyle = state.reportStyle === "mag" ? "card" : "mag";
    save(state);
    updateStyleBtn();
    toast(state.reportStyle === "mag" ? "已换成杂志版式" : "已换回卡片版式");
  };
  $("#editCloset").onclick = () => {
    state.editCloset = !state.editCloset;
    state.clothSel = null;
    save(state); renderCloset();
  };
  $$("[data-closet]").forEach((b) => {
    b.onclick = () => {
      state.closetSort = b.dataset.closet;
      save(state); renderCloset();
    };
  });
  $$("[data-season]").forEach((b) => {
    b.onclick = () => {
      state.closetSeason = b.dataset.season;
      save(state); renderCloset();
    };
  });
  // 柜子搜索：敲一个字重画一次网格，不进 state、不写盘（临时过滤，见 yi.js 的 closetQuery）
  $("#clothSearch").oninput = () => renderCloset();
  // 言笺同一套：搜索框是静态摆在 #yanOut 外面的，重画列表不会碰它，光标不会丢
  $("#yanSearch").oninput = () => yanSearchTick();

  // 单选组的状态不能只写在 class 里：读屏器看不见 .on（口径同 me.js:150-153 那排 data-home）
  $$("[data-weimode]").forEach((x) => {
    const on = x.dataset.weimode === state.weiMode;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  $$("[data-weimode]").forEach((b) => {
    b.onclick = () => {
      state.weiMode = b.dataset.weimode; save(state);
      $$("[data-weimode]").forEach((x) => {
        x.classList.toggle("on", x === b);
        x.setAttribute("aria-pressed", String(x === b));
      });
      markStaleWei();   // 换人要当场说出来：屏幕上那一桌已经过期了（见 wei.js）
    };
  });
  $("#addPerson").onclick = () => {
    const n = ($("#personName").value || "").trim() || "同行";
    state.people.push({ name: n, chips: [] });
    $("#personName").value = "";
    whoOpen = [...whoOpen, state.people.length - 1];   // 刚加的人就是要挑忌口，别让他再找那枚签
    save(state); renderWeiPeople();
  };
  $("#personName").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("#addPerson").click();
  });
  $("#runWei").onclick = runWei;
  // 改一个字就把「这张是上一版的」提示亮起来：只切一个 display，不重画结果
  $("#menu").value = state.weiMenu || "";
  $("#menu").oninput = () => { state.weiMenu = $("#menu").value; saveSoon(); markStaleWei(); };
  $("#yanText").value = state.yanText || "";
  $("#yanText").oninput = () => { state.yanText = $("#yanText").value; saveSoon(); };
  $("#runYan").onclick = runYan;
  $("#demoWei").onclick = () => {
    // 走 input 这一个入口：state.weiMenu、写盘、「这张是上一版的」提示一起更新。
    // 以前直接赋值，填完示例之后那条提示还收着——屏幕上同时有两句话对不上。
    $("#menu").value = "宫保鸡丁\n水煮鱼\n蒜蓉西兰花\n白切鸡\n酸菜鱼\n花生豆腐\n米饭\n另外有人不吃辣";
    $("#menu").dispatchEvent(new Event("input"));
    toast("已填示例，直接排这桌");
  };
  $("#demoYan").onclick = () => {
    $("#yanText").value = state.yanText = "明天下午记得把材料发我。\n药快没了帮我买一盒。\n那就周五见吧。\n时间再说。\n快递到了你拿一下。";
    save(state);
    toast("已填示例，直接捞成笺");
  };
  $("#yanImgBtn").onclick = () => $("#fileYanImg").click();
  // 聊天截图 → 文字：填了网关就真的抄（实测一段七句的截图，快 2.6 秒、慢 14 秒），
  // 没填就照实说没填，不再拿一句含糊的「要接通网关」搪塞。
  $("#fileYanImg").onchange = async (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f || busy) return;
    if (!JianAPI.remoteOn()) {
      toast("这台还没填网关地址，抄不了图。请把图里的字抄下来贴进框里。");
      return;
    }
    busy = true; JianAPI.beginTurn(); veil(true, "在抄图里的字…"); toast("在抄图里的字…");
    const r = await JianAPI.ocr(f);
    veil(false); busy = false;
    if (!r || !(r.text || "").trim()) {
      const why = JianAPI.status("ocr").error;
      toast("这张图没抄出字来" + (why ? "：" + why : "，换一张清楚点的试试"));
      return;
    }
    const el = $("#yanText");
    el.value = (el.value.trim() ? el.value.trim() + "\n" : "") + r.text.trim();
    state.yanText = el.value; save(state);
    haptic("MEDIUM");
    toast("抄好了，点「捞成笺」");
  };

  $$("[data-mod]").forEach((el) => {
    el.onclick = () => {
      const k = el.dataset.mod;
      // 一笺都不留是死屏：底栏只剩「我的」，home 也没处安放。挡回去可以，
      // 但**把自己的改动静默撤回**等于摆一枚按了没反应的章（第 27 轮的规矩，
      // silentscan 审出来的一条真缺陷）——所以挡下的那一路必须把规矩说出来。
      if (state.modules[k] && enabledModules().length === 1) {
        toast("至少留一笺：全关掉之后，底栏就只剩「我的」了");
        return;
      }
      state.modules[k] = !state.modules[k];
      if (!state.modules[state.home]) state.home = enabledModules()[0];
      save(state); paintNav(); renderMe();
    };
  });
  // 只绑「我的」那一屏的那一排：引导页三张卡也叫 data-home，以前这一句把它们一起绑了，
  // 于是引导页上点一下就中两次——改完 home 又跑回来一次 renderMe 加一句「打开即是这一笺」，
  // 那句提示出现在引导页上像句莫名其妙的话，而「进入」按钮还没按。
  $$("#me [data-home]").forEach((el) => {
    el.onclick = () => { state.home = el.dataset.home; save(state); renderMe(); toast("打开即是这一笺"); };
  });
  $$("[data-buy]").forEach((el) => { el.onclick = () => buy(el.dataset.buy); });
  $("#saveApi").onclick = () => {
    const raw = $("#apiUrl").value.trim();
    const r = normApi(raw);
    // 不合格就当场说清「为什么没存」，并且一个字都不抹：
    // 以前这里不校验，填 `192.168.1.5:8787`（漏了 scheme，最常见的写法）的人看见的是
    // 「已记下网关」，重开却被开机那道钳位静默清成空——同一件事两种口径，说成的那次是假的。
    if (raw && !r.url) {
      // 不写 state、不动 endpoint、不 gwReset、不 renderMe：屏幕上原来那一台还作数，
      // 输入框里留着用户敲的那一串（他多半只是想补个 http:// 前缀）。
      toast("没存：" + r.why, 5200);
      return;
    }
    state.apiUrl = r.url;
    window.JIAN_CONFIG.endpoint = state.apiUrl;
  gwReset();                       // 换了一台网关，刚才那句「能干什么」就不作数了
    save(state); hintEngine(); renderMe();
    // 存进去的那一条，下次开机 normApi 必须照样认（同一个判断，两路口径天然一致）
    toast(state.apiUrl
      ? (/^http:\/\//i.test(state.apiUrl)
          ? "已记下网关。这一台走的是 http，不加密——局域网里用可以"
          : "已记下网关")
      : "已改回本地");
  };
  // 「先不等了」：放弃这一轮对远端的等待。api.js 会把在飞的请求掐掉，
  // 并让这一轮后续的每一枪都不再试远端——本地引擎几十毫秒就能给出判定，
  // 不该让用户对着一层静止的遮罩数秒。
  $("#veilOff").onclick = () => {
    if (!busy) return;
    JianAPI.giveUp();
    toast("先不等了");
  };
  $("#exportData").onclick = exportData;
  $("#importData").onclick = () => $("#fileImport").click();
  $("#fileImport").onchange = (e) => { const f = e.target.files[0]; if (f) importData(f); e.target.value = ""; };
  $("#reset").onclick = async () => {
    if (!confirm("清空本机所有笺？柜子和笺册都会没。")) return;
    // 这是全 App 最狠的一下，而且紧跟着就 reload。清空前把整份 JSON 塞进 sessionStorage
    // ——它活得过一次刷新——回来就还有一次撤销。
    try { sessionStorage.setItem(KEY + ".undo", localStorage.getItem(KEY) || ""); } catch (_) {}
    // 保险丝那份必须一起擦，而且要赶在 reload 之前擦完：只删 localStorage 的话，
    // 开机那一步看见本机空了，就把刚删掉的整份搬回来，屏幕上还写着「已清空」。
    // 原生卡住也不能让这个按钮永远不响应，所以只等 2 秒；等不到的那一种，
    // 回来之后由 fuseRefilled 说真话（它量的是「数据到底回来没有」，不是擦的那一下成没成）。
    await Promise.race([eraseNativeBackup(), new Promise((r) => setTimeout(r, 2000))]);
    clearStore(); location.reload();
  };
  /* 页面要走的时候，把排队中的那次改动落盘。
   *
   *  `saveSoon()` 合并的是 600ms 内的连续改动（打字那种高频输入），而用户不会等到
   *  定时器响：实测在言笺里打一句、100ms 后关掉，重开是空的。同类路径还有切到后台
   *  被系统回收、锁屏、从「册」跳到别的 App。
   *
   *  两个事件都挂，因为它们覆盖的场景不一样：
   *   · `pagehide` —— 页面真的要走（关闭、前进后退、bFCache）。这是最后的机会。
   *   · `visibilitychange` 到 hidden —— 切后台/切标签，页面还在但随时可能被回收；
   *     安卓 WebView 里这条比 pagehide 更早也更可靠。
   *  同一个时刻两条都可能触发，但 flushSoon() 第二次是空操作（定时器已经没了），
   *  所以不需要额外的去重标志。
   *
   *  原生壳里另有一条：Capacitor 的 App 插件在切后台时会发 appStateChange。
   *  不重复挂——visibilitychange 在 WebView 里同样会发，两条都挂等于做两遍同一件事。 */
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushSoon();
  });
  window.addEventListener("pagehide", () => flushSoon());


  offerImportUndo();
  offerResetUndo();
  // 上面那两位都没开口（这一次既没导入也没清空）：攒下的报告现在单独说。
  const note = joinBootNotes("");
  if (note) toast(note, 5200);
  // 系统分享进来的文字：冷启动时原生可能比这里更早递进来，先攒着，到这一步才消费。
  // 放在最后是因为它会切屏到言笺——先让「已导入 / 丢过照片」这些开机要说的说完。
  try { flushShare(); } catch (e) { console.warn("share", e); }
  registerOffline();
}

/**
 * 导入之后那句「换回来了」的反悔。槽是 importData 在**写盘成功之后**才占的，
 * 所以读到就该说清楚：本机这一份已经是文件里那份了，里面有多少件/多少条也一并报出来。
 * 事前对话框不是这个 App 的路子（清空本地数据也是先做再给一次反悔）；
 * 而且报的是「落进来之后」的数，不是文件里声称的数——外来那份会被 normalizeState 洗一遍。
 */
function offerImportUndo() {
  let snap = null, at = "";
  try {
    snap = sessionStorage.getItem(KEY + ".importundo");
    at = sessionStorage.getItem(KEY + ".importat") || "";
    if (snap !== null) {
      sessionStorage.removeItem(KEY + ".importundo");
      sessionStorage.removeItem(KEY + ".importat");
    }
  } catch (_) { }
  if (snap === null) return;
  const n = (state.wardrobe || []).length, m = (state.yanCards || []).length, a = (state.album || []).length;
  const when = /^\d+$/.test(at) ? `这份是 ${dayStr(+at)} 导出的` : "这份备份没写导出时间";
  toastUndo(joinBootNotes(`已导入：柜里 ${n} 件 · 言笺 ${m} 条 · 笺册 ${a} 张（${when}）`), () => {
    try {
      state = normalizeState(JSON.parse(snap));
      save(state); paintNav(); show(state.onboarded ? state.home : "onboard");
      toast("换回导入前那份了");
    } catch (_) { toast("反悔没成功，重新打开就好"); }
  });
}

/** 上一次「清空本地数据」之后回来，给一次反悔的机会（快照只活一次，点没点都作废）。 */
function offerResetUndo() {
  let snap = null;
  try {
    snap = sessionStorage.getItem(KEY + ".undo");
    if (snap) sessionStorage.removeItem(KEY + ".undo");
  } catch (_) { }
  if (!snap) return;
  if (fuseRefilled) {
    // 刚点过「清空」，可开机时保险丝又把整份搬回来了：这时候说「已清空」是第二遍骗人。
    // 反悔那枚签也不给——数据本来就没丢，没什么可还的。
    toast(joinBootNotes("没清干净：系统里那份备份又把数据搬回来了。柜子和笺册都还在，再清一次试试"), 6000);
    return;
  }
  toastUndo(joinBootNotes("本机数据已清空"), () => {
    try {
      state = normalizeState(JSON.parse(snap));
      save(state); paintNav(); show(state.onboarded ? state.home : "onboard");
      toast("回来了");
    } catch (_) { toast("反悔没成功，重新打开就好"); }
  });
}

/** 离线可用：只在浏览器的 http(s) 下注册。
 *  原生壳里资源本来就打进 APK，再套一层 SW 缓存只会变成「更新了却还是旧界面」的客服噩梦。 */
function registerOffline() {
  if (hasNative()) return;
  if (!/^https?:$/.test(location.protocol)) return;      // file:// 双击打开那条路保持原样
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => { });   // 注册不上也不影响任何功能
  });
}

document.addEventListener("DOMContentLoaded", boot);
