/** 笺 · 共用件：小工具、原生桥、导航
   esc / 色值与图片校验 / toast / 遮罩 / 复制 / 相对日期，Capacitor 桥，以及五屏切换。
   浏览器里 hasNative() 恒为 false，原生那一段全部静默。 */

/* ---------- 小工具 ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}
/** toast 的落点。**live region 必须在内容变化之前就在 DOM 里**，所以「提示区」是一个
 *  常驻的空容器，每条提示挂进它；以前是每次新造一个带 aria-live 的节点——读屏器对一个
 *  刚出现的节点上的文字什么都不念，于是笺点不足、撤销、失败原因这些最需要说给
 *  看不见的人听的话，全 App 一个字都没念出来过（第 38 轮）。 */
function toastHost() {
  let h = $("#toasts");
  if (!h) {
    h = document.createElement("div");
    h.id = "toasts"; h.setAttribute("role", "status"); h.setAttribute("aria-live", "polite");
    document.body.appendChild(h);
  }
  return h;
}
/** 只留一条，后发的覆盖先发的（同时能撤销两件事的界面反而更难解释）。
 *  清空的是常驻容器里的孩子，容器本身永远在那儿——否则 aria-live 就白挂了。 */
function pushToast(n) {
  const h = toastHost();
  while (h.firstChild) h.removeChild(h.firstChild);
  h.appendChild(n);
  return n;
}
function toast(t, ms) {
  const n = document.createElement("div");
  n.className = "toast"; n.textContent = t;
  pushToast(n);
  setTimeout(() => n.remove(), ms || 1800);
}

/** 带「撤销」的 toast：删掉的东西给一次反悔的机会。
 *  有了它，破坏性操作的按钮才可以直接摆在行上（以前只能藏进「整理」模式或者一键清空）。 */
function toastUndo(text, undo) {
  const n = document.createElement("div");
  n.className = "toast act";
  const s = document.createElement("span");
  s.textContent = text;
  const b = document.createElement("button");
  b.type = "button"; b.textContent = "撤销";
  b.onclick = () => { n.remove(); undo(); };
  n.append(s, b);
  pushToast(n);
  setTimeout(() => n.remove(), 5200);   // 比默认那 1.8 秒长得多，才来得及伸手去点
}

/* ---------- 焦点找回 ----------
   四个模块的渲染都是整片 innerHTML 重建。鼠标用户无所谓，键盘用户按一次「今天穿了」
   就会被甩回页首，Tab 得从头再走一遍。渲染前记下焦点所在的身份（id 或它第一个 data-*），
   重建后按同一身份找回来。 */
function focusKey(el) {
  const a = el || document.activeElement;
  if (!a || a === document.body || a === document.documentElement) return null;
  if (a.id) return "#" + CSS.escape(a.id);
  const tag = a.tagName.toLowerCase();
  // 全部 data-* 一起当身份：只用第一个会在「两个人都忌辣」这种重名标签上找回错的那枚
  const attrs = [...a.attributes].filter((at) => at.name.indexOf("data-") === 0);
  if (!attrs.length) return null;
  return tag + attrs.map((at) => `[${at.name}="${CSS.escape(at.value)}"]`).join("");
}
function restoreFocus(key) {
  if (!key) return;
  if (focusKey() === key) return;          // 焦点没丢就别去抢
  const el = $(key);
  if (el) el.focus({ preventScroll: true });  // preventScroll：找回焦点不该把页面滚下去
}
let veilFocus = null;
function veil(on, what) {
  const v = $("#veil");
  if (!v) return;
  if (on && !v.classList.contains("on")) veilFocus = document.activeElement;
  v.classList.toggle("on", !!on);
  // 遮罩占着屏幕时，Tab 和读屏器不能钻进背景继续改表单。
  const app = $("#app"), nav = $("#nav");
  if (app) { app.inert = !!on; app.setAttribute("aria-busy", String(!!on)); }
  if (nav) nav.inert = !!on;
  if (on) {
    const w = $("#veilWhat");
    if (w) w.textContent = what || "正在写这张笺…";
  }
  // 只有这一轮真的可能去等远端，才给「先不等了」。本地引擎几十毫秒就回来，
  // 那时候摆一个放弃按钮是噪音。
  const off = $("#veilOff");
  if (off) off.hidden = !(on && window.JianAPI && JianAPI.remoteOn());
  if (on) {
    v.tabIndex = -1;
    (off && !off.hidden ? off : v).focus({ preventScroll: true });
  } else {
    const previous = veilFocus;
    veilFocus = null;
    const screen = previous && previous.closest && previous.closest(".screen");
    if (previous && previous.isConnected && (!screen || screen.classList.contains("on")))
      previous.focus({ preventScroll: true });
  }
}
function copy(text, okMsg) {
  const done = () => toast(okMsg || "已复制");
  const fail = () => toast("请长按文字复制");
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(fail);
  } else {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      done();
    } catch (_) { fail(); }
  }
}
/* dayStr 已挪到 state.js（连续天数 / 热力图在数据层就要它，而 state 先于 ui 加载）。
   这里不重复定义：两份定义是本仓反复栽的那一族，只留一份真相。 */
function shortDay(ts) {
  const d = new Date(ts);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}
/** 把时间戳说成人话：今天 / 3 天前 / 2 周前 / 4 个月前。 */
function relativeDays(ts) {
  if (!ts) return null;
  const d = Math.floor((Date.now() - ts) / DAY);
  if (d <= 0) return "今天";
  if (d === 1) return "昨天";
  if (d < 7) return d + " 天前";
  if (d < 30) return Math.floor(d / 7) + " 周前";
  if (d < 365) return Math.floor(d / 30) + " 个月前";
  return Math.floor(d / 365) + " 年前";
}


/* ---------- 原生桥（Capacitor。浏览器里 hasNative() 恒为 false，这一段全部静默） ---------- */

const hasNative = () => !!(window.Capacitor && window.Capacitor.Plugins);

/** 本地/网关隐私说明只保留这一份，避免「册」与「关于笺」各说各话。 */
function dataWhere() {
  return window.JianAPI && JianAPI.remoteOn()
    ? "文字与照片会发往你填的那个地址" : "数据只在这台设备";
}

function nativePlugins() {
  try { return (window.Capacitor && window.Capacitor.Plugins) || null; }
  catch (_) { return null; }
}

/** 「交给系统分享」不等于「已经存好了」。Capacitor 的 Share 面板即使用户划走也照样 resolve，
 *  所以原生这一路能确证的只有「交出去了」；浏览器那一路是真的下载，指到下载里去看。
 *  备份与长图两处共用这一份说法——同一件事在两屏上说成两种话，迟早有一种是假的（第 41 轮）。 */
const SHARE_HANDOFF = "已交给系统的分享：在那一张面板里选保存或发送";
const SHARE_FAILED = "系统的分享没起来，再按一次试试";
function doneMsg(what) {
  return hasNative() ? SHARE_HANDOFF : `已${what}：浏览器的下载里能看到`;
}

/** dataURL → 纯 base64。Filesystem.writeFile 的 data 要不带 data: 头的。 */
function bareBase64(dataUrl) {
  return String(dataUrl || "").replace(/^data:[^,]*,/, "");
}

/** 原生落盘 + 系统分享面板。任何一步失败都往上抛，由调用方回落浏览器路径。 */
async function nativeShareFile(name, data, opts) {
  const plugins = nativePlugins();
  const fs = plugins && plugins.Filesystem;
  const share = plugins && plugins.Share;
  if (!fs || !share) throw new Error("native filesystem/share unavailable");
  await fs.writeFile({ path: name, data, directory: opts.directory, recursive: true, encoding: opts.encoding });
  const uri = await fs.getUri({ path: name, directory: opts.directory });
  await share.share({ title: name, files: [uri.uri] });
}

/** 安卓返回键：先退回上一张纸（衣笺报告 → 衣笺），站在主屏上才退到后台。 */
function registerNativeBack() {
  if (!hasNative()) return;
  try {
    const app = nativePlugins().App;
    if (app && app.addListener) app.addListener("backButton", () => { if (!goBack()) app.minimizeApp(); });
  } catch (e) { console.warn("backButton", e); }
}

/** 状态栏那一排图标，跟着纸走：白天的纸要深色图标，夜里的纸要浅色图标。
 *  不写这一条会怎样：插件的 style 默认是 DEFAULT，而 DEFAULT 是**跟着系统夜间模式走**的
 *  （StatusBar.getStyleForTheme）——手机一开深色模式，系统就给出一副浅色图标，
 *  压在 #f4efe6 这张纸上直接看不见，时间、电量、通知全没了。
 *  0.6.0 起纸有两种说法，所以这里也必须分叉：只要 LIGHT 的话，「夜里的纸」上会压一副深色图标，
 *  同样看不见（lane-android 在原生侧加了兜底监听，但正解在这一行，兜底只当保险丝）。
 *  只调 setStyle 不调 setBackgroundColor：安卓 15 起强制 edge-to-edge，
 *  插件自己标注 setBackgroundColor / overlaysWebView 在 15+ 已失效，
 *  状态栏下面本来就是这张纸（body 背景 + CSS 的 env(safe-area-inset-*) 负责避让）。 */
function paintNativeChrome() {
  if (!hasNative()) return;
  try {
    const bar = nativePlugins().StatusBar;
    if (!bar || !bar.setStyle) return;
    // THEME 还没 init 时（boot 极早期）按白天算：第一帧是白纸，错不了
    const night = typeof THEME === "object" && THEME && THEME.dark && THEME.dark();
    Promise.resolve(bar.setStyle({ style: night ? "DARK" : "LIGHT" })).catch(() => { });
  } catch (e) { console.warn("StatusBar", e); }
}

/** 备份保险丝：localStorage 被系统清了，就从 Preferences 捞回上一次的数据。 */
async function restoreNativeBackup() {
  if (!hasNative()) return false;
  try {
    const prefs = nativePlugins().Preferences;
    if (!prefs || !prefs.get) return false;
    const res = await prefs.get({ key: KEY });
    const value = res && res.value;
    if (!value) return false;
    /* 什么时候该从保险丝捞回来：本机那格**空着**，或者**读不懂**。
     *
     *  以前只认前一种。于是 localStorage 里存着一份坏 JSON（写一半断电、别的东西
     *  往同一个键里塞了东西、配额满时被截断）时，开机这条路是：
     *    load() 解析失败 → null → 种出一套示例柜 → 用户随便动一下 → save()
     *  把示例柜写回本机、一秒后又同步进 Preferences——**那份好的备份就这样被覆盖了**。
     *  实测过：好数据在 Preferences 里，开机走一圈之后 Preferences 里也是种子的。
     *
     *  判据扩成「空或解析不出来」：坏掉的那一份本来就没法用，而保险丝里那份是好的。
     *  注意不覆盖「有数据但 schema 老」的情形——那种 migrate() 处理得了，
     *  不该拿备份把它顶掉（备份可能反而更老）。 */
    let empty = false;
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) empty = true;
      else { JSON.parse(raw); empty = false; }
    } catch (_) { empty = true; }
    if (empty) {
      writeStore(value);
      return true;
    }
  } catch (e) { console.warn(e); }
  return false;
}

let backupTimer = null;
const prefsPlugin = () => (hasNative() && nativePlugins().Preferences) || null;
/** 保险丝管的是「localStorage 被系统清了」，所以它存的就该是 localStorage 里那一份，
 *  而不是内存里的 state：导入备份之后没等满那一秒就刷新，存着的会是**上一代**数据。 */
const storeJson = () => { try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; } };
function cancelBackup() { if (backupTimer) { clearTimeout(backupTimer); backupTimer = null; } }
/** 每次 save() 成功后 debounce 1s，把当前数据同步一份进 Preferences；原生失败只 warn。
 *  空的那一份不写：把「本机已经没有数据」当备份存进去，等于亲手擦掉最后一次能救命的机会。 */
function scheduleNativeBackup() {
  const prefs = prefsPlugin();
  if (!prefs || !prefs.set) return;
  if (backupTimer) clearTimeout(backupTimer);
  backupTimer = setTimeout(() => {
    backupTimer = null;
    try {
      const json = storeJson();
      if (json) Promise.resolve(prefs.set({ key: KEY, value: json })).catch((e) => console.warn(e));
    } catch (e) { console.warn(e); }
  }, 1000);
}
/** 立刻把 localStorage 那一份顶上保险丝。凡是「写完就要 location.reload()」的地方都得先走这一步：
 *  刷新不等那 1 秒的定时器，于是新数据进了本机、旧数据留在保险丝里。 */
function flushNativeBackup() {
  cancelBackup();
  const prefs = prefsPlugin();
  const json = storeJson();
  if (!prefs || !prefs.set || !json) return Promise.resolve(false);
  return Promise.resolve(prefs.set({ key: KEY, value: json }))
    .then(() => true).catch((e) => { console.warn(e); return false; });
}
/** 擦掉保险丝那一份。「清空本地数据」只删 localStorage 是不够的：reload 之后
 *  restoreNativeBackup() 看见本机空了，就把刚删掉的整份搬回来，屏幕上却写着「已清空」。
 *  有的壳没有 remove，就用 set 写一个空值——空值在恢复那边算「没有备份」。 */
function eraseNativeBackup() {
  cancelBackup();
  const prefs = prefsPlugin();
  if (!prefs) return Promise.resolve(true);      // 浏览器：本来就没有第二份，视作擦干净了
  const done = (p) => Promise.resolve(p).then(() => true).catch((e) => { console.warn(e); return false; });
  try {
    if (prefs.remove) return done(prefs.remove({ key: KEY }));
    if (prefs.set) return done(prefs.set({ key: KEY, value: "" }));
  } catch (e) { console.warn(e); }
  return Promise.resolve(false);
}

/* ---------- 导航 ---------- */

// 原生返回键的去处。安卓用户的预期是「返回先退回上一张纸，站在主屏上才退到后台」，
// 而以前 backButton 一律 minimizeApp()：从衣笺报告按返回，整个 App 直接消失。
// 全 App 只有一条真正的子页（yi → yi-report）；底栏那些是平级目的地，按安卓惯例另起一段路。
//
// v0.6.0：子页从 1 张涨到 9 张（报告、单品详情、菜谱详情、搭配详情、提醒总览、
// 设置、成就、年度总结、全局搜索）。SUB_OF 仍然是「这张纸是从哪张纸翻过来的」这**一个**口径，
// 新增子页只在这里加一行——不要在各自的渲染里另写一套返回逻辑（那是第二份定义）。
const SUB_OF = {
  "yi-report": "yi",
  "yi-item": "yi",
  "yi-outfit": "yi",
  "wei-dish": "wei",
  "wei-week": "wei",
  "yan-remind": "yan",
  "settings": "me",
  "pu": "today",
  "badges": "pu",
  "year": "pu",
  "search": "me",
};
let backStack = [];

/** 返回键按下去：先回上一张纸。回到栈底时返回 false，调用方决定退后台。 */
function goBack() {
  const prev = backStack.pop();
  if (!prev) return false;
  show(prev, true);
  return true;
}

/** 底栏那五枚：id → 图标字 + 标签。图标字是宋体的单字小印，不是 emoji。
 *  五枚是「人一天里真的会做的五件事」：今天要看的三件 → 穿什么 → 吃什么 → 记什么 → 我的档。
 *  「笺谱」（统计/成就/年度总结）收进「今日」那一屏的顶部，不占底栏——它一周看一次就够。 */
const NAV_ITEMS = [
  { id: "today", mark: "今", label: "今日" },
  { id: "yi", mark: "衣", label: "衣笺" },
  { id: "wei", mark: "味", label: "味笺" },
  { id: "yan", mark: "言", label: "言笺" },
  { id: "me", mark: "册", label: "册" },
];
/** 子页归到哪一枚底栏签（报告归衣笺、设置归册…）。取不到的屏不点亮任何一枚。 */
const NAV_OF = {
  today: "today",
  yi: "yi", "yi-report": "yi", "yi-item": "yi", "yi-outfit": "yi",
  wei: "wei", "wei-dish": "wei", "wei-week": "wei",
  yan: "yan", "yan-remind": "yan",
  pu: "today", badges: "pu", year: "pu",
  me: "me", settings: "me", search: "me",
};

function show(id, isBack) {
  if (!isBack) {
    const cur = document.querySelector(".screen.on");
    if (cur && cur.id !== id) {
      if (SUB_OF[id] === cur.id) backStack.push(cur.id);
      else backStack = [];
    }
  }
  $$(".screen").forEach((s) => s.classList.toggle("on", s.id === id));
  // 当前页以前只有一枚印章红的点（class .on）——那是**画**给眼睛的，读屏器问「我在哪一笺」
  // 得不到回答。aria-current 是那条问题的答案，跟着描边一起换。
  $$(".nav button").forEach((b) => { b.classList.remove("on"); b.removeAttribute("aria-current"); });
  const navId = NAV_OF[id];
  if (navId && $(`#nav-${navId}`)) {
    const nb = $(`#nav-${navId}`);
    nb.classList.add("on");
    nb.setAttribute("aria-current", "page");
  }
  $("#nav").style.display = id === "onboard" ? "none" : "flex";
  // 注意：scrollTo **不在这里**，挪到了渲染之后。理由见那个 RENDER 表下面那一段注释。
  if (id === "onboard") paintModeCards();   // 引导页不许带着旧描边开屏（见 app.js）
  // 每一屏的渲染入口收成一张表：show() 里再堆 if 会越堆越长，而漏掉一条的症状是
  // 「切过去是上一版的画面」——这种错没有报错、只有用户看得出来。
  // 值都是函数名字符串：这些函数分布在后面才加载的文件里，直接引用会在 parse 期就命中 TDZ。
  const RENDER = {
    me: "renderMe",
    yi: "renderYi",
    yan: "renderYan",
    wei: "renderWei",
    pu: "renderPu",
    today: "renderToday",
    "yi-report": "enterReport",
    "yi-item": "renderYiItem",
    "yi-outfit": "renderYiOutfit",
    "wei-dish": "renderWeiDish",
    "wei-week": "renderWeiWeek",
    "yan-remind": "renderRemind",
    settings: "renderSettings",
    badges: "renderBadges",
    year: "renderYear",
    search: "renderSearch",
  };
  const fn = RENDER[id];
  if (fn && typeof window[fn] === "function") {
    try { window[fn](); } catch (e) { console.warn("render " + id, e); }
  }
  // 每换一屏都要重问一遍顶栏那行：它说的是「你现在这张笺是谁算的」。
  // 以前只在进衣笺时刷新，人从言笺切到味笺，看到的还是上一屏留下的答案。
  hintEngine();
  // 换屏要把焦点交给这一屏：读屏器才会念出「衣笺报告 / 味笺」这块区域的名字，
  // 键盘用户也不会还停在刚点过的底栏按钮上、Tab 从头再走一遍。
  const scr = $("#" + id);
  if (scr && scr.classList.contains("on")) {
    const lead = scr.querySelector("h1") || scr;
    if (!lead.hasAttribute("tabindex")) lead.setAttribute("tabindex", "-1");
    lead.focus({ preventScroll: true });
  }
  /* 滚回页首放在**渲染之后**。
   *
   *  以前这一行在 RENDER 之前：那时屏幕上还是上一屏的 DOM（这一屏刚被 .on 打开、
   *  内容还没重建），浏览器为了执行 scrollTo 要把整篇重排一次；RENDER 把内容换掉之后
   *  又要重排一次。言笺 200 条时整篇有 44,358px 高，实测两次全量同步布局占掉
   *  切屏 196ms 里的 178ms（renderYan 自己只要 18ms）。
   *  挪到后面只量一次，而结果完全一样——用户看到的都是「新的一屏从顶上看起」。
   *
   *  focus 那一句不用挪：它本来就带 preventScroll，不会触发布局。 */
  if (id !== "onboard") window.scrollTo({ top: 0 });
  paintNavBadges();
}

/** 进衣笺那一屏要刷的两件事（renderYi 在 yi.js 里，它会把柜子与「上一张报告」一起刷）。 */
function renderYi() { renderCloset(); lastLink(); }
/** 进报告页只刷两件轻的：整片 paintReport 不能重跑（会再落一次章）。 */
function enterReport() { paintReportTitle(); paintReportActions(); }

function enabledModules() {
  return ["yi", "wei", "yan"].filter((k) => state.modules[k]);
}

/** 底栏那枚「言笺」上的小点：今天到期的提醒 / 还没办的事。
 *  没有就是没有——不摆一个永远亮着的红点（那是「狼来了」）。
 *  这一函数在整个 App 里是唯一一处写 nav 徽标的地方。 */
function paintNavBadges() {
  const b = $("#nav-yan");
  if (!b) return;
  let n = 0;
  try {
    if (typeof dueToday === "function") n = dueToday();
  } catch (_) { n = 0; }
  const old = b.querySelector(".nav-dot");
  if (old) old.remove();
  if (n > 0) {
    const d = document.createElement("i");
    d.className = "nav-dot";
    d.setAttribute("aria-label", `今天有 ${n} 件到期`);
    b.appendChild(d);
  }
}

/* ---------- 深链 ----------
   三条路合成一条：桌面长按图标出来的快捷方式（jian://screen/yan）、H5 地址里的 #yan、
   以及热启动时原生递过来的 appUrlOpen。只认主屏，认不出就不动界面。 */

/** 从一串地址里挑出要打开的那一屏；没有就返回 null。
 *  关键词后面只许接分隔符或结尾（负向前瞻，不是允许集）：#yi-report 是子页，
 *  第一版把 "-" 写进了分隔符集合，于是它被认成了主屏 yi。
 *  v0.6.0 新增 today / pu 两条入口（快捷方式「今日一笺」与「笺谱」）。 */
function screenOf(url) {
  const m = String(url || "").match(/(?:^|[#/?&])(yi|wei|yan|me|pu|today)(?![\w-])/);
  return m ? m[1] : null;
}

function openDeep(url) {
  const id = screenOf(url);
  if (!id) return false;
  if (id !== "me" && id !== "pu" && id !== "today" && !state.modules[id]) {
    // 快捷方式是静态清单，它不知道用户在「我的」里关掉了哪一笺。
    // 硬开一笺会让底栏没有对应的那枚按钮、返回栈也说不清，不如直接送去能打开它的地方。
    show("me"); toast("这一笺已经关掉了，在下面重新打开"); return true;
  }
  // 快捷方式可以带参数：jian://screen/yi?new=衬衫 —— 只带一个名字，绝不带图（图会撑爆配额）
  try {
    const q = String(url || "").split("?")[1] || "";
    const p = new URLSearchParams(q);
    const nm = (p.get("new") || "").trim().slice(0, 40);
    if (nm && id === "yi" && typeof presetNewName === "function") presetNewName(nm);
    const txt = (p.get("text") || "").slice(0, 4000);
    if (txt && id === "yan" && typeof presetYanText === "function") presetYanText(txt);
  } catch (_) { /* 地址不是我们造的：忽略参数，照样进屏 */ }
  show(id); return true;
}

/** 底栏：五枚。哪几笺被关掉，对应的那几枚就不摆（关掉的笺不该在底栏留一个洞）；
 *  「笺谱」与「册」永远在。 */
function paintNav() {
  const nav = $("#nav");
  nav.innerHTML = "";
  nav.classList.add("nav5");
  const off = { yi: !state.modules.yi, wei: !state.modules.wei, yan: !state.modules.yan };
  NAV_ITEMS.filter((it) => !off[it.id]).forEach((it) => {
    const b = document.createElement("button");
    b.id = `nav-${it.id}`;
    b.type = "button";
    // 无障碍名字 = 看得见的那个字。图标那枚标了 aria-hidden，读屏器本来就不会念它，
    // 但**显式**写一份 aria-label 有两件事是 textContent 给不了的：
    //  1. 语音控制（「点衣笺」）按名字匹配，它不认 aria-hidden 之外的拼法；
    //  2. 测试不必去猜「这枚按钮的文字是几段拼起来的」——`textContent` 现在会是
    //     「衣衣笺」（图标字 + 标签），按它比对的断言全成了假红。
    b.setAttribute("aria-label", it.label);
    const ico = document.createElement("span");
    ico.className = "nav-ico"; ico.setAttribute("aria-hidden", "true"); ico.textContent = it.mark;
    const lab = document.createElement("span");
    lab.className = "nav-lab";
    lab.textContent = it.label;
    b.append(ico, lab);
    b.onclick = () => show(it.id);
    nav.appendChild(b);
  });
  paintNavBadges();
}

function hintEngine(task) {
  const el = $("#engineHint");
  if (!el) return;
  // 说的是「你现在看的这张笺其实是谁算的」，不是「三条路最近的整体近况」。
  // 不带参数时按当前那一屏推：以前这里调的是不带参的 status()——衣笺早前走通过网关，
  // 人站在味笺页上，这一张明明是本地规则算的，顶栏照样写着「网关」。
  const scr = document.querySelector(".screen.on");
  const id = task || ({ "yi": "yi", "yi-report": "yi", "wei": "wei", "yan": "yan" }[scr ? scr.id : ""] || "");
  const s = JianAPI.status(id || undefined);
  el.textContent = !s.on ? "本地"
    : s.via === "remote" ? "网关"
    : s.via === "local" ? (s.error ? "回落本地" : "本地")
    : s.via === "fell-back" ? "回落本地"
    : "网关未试";
  if (s.error) el.title = s.error;
}

/** 触感：原生壳里给一记，浏览器里静默。style = LIGHT / MEDIUM / HEAVY。
 *  以前只有落章那一处，且每处都自己写一遍 hasNative + try/catch。 */
function haptic(style) {
  if ((state.settings || {}).haptic === false || !hasNative()) return;
  try {
    const h = nativePlugins().Haptics;
    if (h && h.impact) Promise.resolve(h.impact({ style: style || "LIGHT" })).catch(() => { });
  } catch (e) { console.warn("haptics", e); }
}

function lastLink() {
  const el = $("#lastReportLink");
  if (!el) return;
  if (state.lastReport && state.lastReport.new) {
    el.innerHTML = `<button class="chip" id="openLast">看上一张报告</button>`;
    $("#openLast").onclick = () => { paintReport(); show("yi-report"); };
  } else el.textContent = "";
}
