# 「不许摆一枚按了没反应的签」——全 App 扫一遍，每枚能点的控件都要有可观察的反应。
#
# 为什么单独一道门：这条规矩第 27 轮就定了（「一条都没勾时不许摆『清掉勾掉的』」），
# 第 41 轮又用同一只手把「存成长图」灰掉。可它一直是**逐例**执行的：谁记得改谁改。
# 这一轮把它变成结构不变量——和第 47 轮「能点但键盘走不到」、第 39 轮「触摸目标尺寸」同一家族。
# 跑出来的第一个成果就是报告页那两枚：没有判定时「复制这段话」「存成长图」都亮着，
# 按下去各自 `return`，一个字都不说（同屏的「记进柜子」倒会说一句「先过一张笺」）。
#
# 规矩：
#   1) 每一枚控件之前**重开一页**（新 context）：上一枚点过的东西会落盘、会留在模块级变量里，
#      不清就会量出「这一枚按了没反应」的假案（写这道门时真的先量出过六个假的）。
#   2) 灰掉的控件跳过（按不动是诚实的回答），但**灰不灰本身也要有证据**：见第 3 节。
#   3) 唯一允许的没反应是「这一组里已经被选中的那一枚」，而且**同一组里必须至少有一枚按了有用**
#      ——否则整组可以一起是死的，而「选中态」这个理由照样成立。
#   4) 覆盖底线：真的扫到 ≥60 枚、≥5 屏、≥5 组。整片扫最容易的骗法就是什么都没扫到却全绿。
#   5) **预置点击序列（PRE）**：每一趟可以先真点几下把界面推到那个状态，再开始量。
#      为什么非要有这一维：有一族控件**只能靠真点两下才到** —— 味笺「忌口」摊开后的 11 枚
#      小签、言笺「挪」之后的 [data-move-to]、「时间」之后的 [data-when-to]、笺册「全文」
#      之后的「收起」、点完删除才浮出的那枚「撤销」。它们的状态是模块级 `let`
#      （wei.js:97 whoOpen / yan.js:26,28 moveOpen,whenOpen / me.js:23 albumOpen,albumView），
#      赋 state 结构上到不了。以前这些枚**一道门都没量过**——「忌口」整表 11 枚里任何一枚
#      按了不说话，全仓没有一只眼睛看得见。
#      两条硬规矩（都是踩过坑的）：
#        5a) 预置步**必须在同一个新 context 里跑完再取基线**。换个 context 取基线等于
#            拿一份干净的界面去比刚点过的界面，量出来的全是假案（规矩 1 的同一个坑）。
#        5b) 预置步点过的那几枚本身也在 KEYS 清单里，**不许计入 dead**：它们的职责是
#            「把界面摊开」，不是「被审的那一枚」。但它们自己也要有证据——预置每一步都
#            当场量一次 SIG，摊不开就红（见第 5 节），免得静悄悄用一套坏掉的预置去审判。
#
# 运行：PYTHONIOENCODING=utf-8 python test/dead_controls.playwright.py
import json
import os
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
KEY = "jian.v1"

checks = []


def check(name, ok, got=""):
    checks.append((ok, name, got))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f"  ->  {got}"))

# 诊断窄跑开关（见 main 里 SCANS 那段）：窄跑时覆盖底线与点名清单必须显式 skip。
ONLY = [s.strip() for s in (os.environ.get("JIAN_DEAD_ONLY") or "").split(",") if s.strip()]
NARROW = bool(ONLY)
# --quick：只跑与场景无关的那几节（§1/§2/§4/§5），把三百来页的全量扫留给需要它的那一次。
# 用它的前提是「注入的靶子在与场景无关的那几节里」——所以被跳过的每一条都必须印出来。
QUICK = "--quick" in sys.argv


def floor(name, ok, got=""):
    """只有全量跑才算数的那几条。窄跑里它们不是「通过」，是「不适用」，要印出来。"""
    if NARROW or QUICK:
        print("  skip " + name + "（" + ("窄跑" if NARROW else "--quick") + "：本跑不扫全量）")
        return
    check(name, ok, got)



BOOT = r"""() => {
  window.__keymap = new Map();
  window.__probe = { confirm: 0, alert: 0, share: 0, file: 0, clip: 0, dl: 0, print: 0, focus: "", scroll: 0 };
  window.confirm = () => { window.__probe.confirm++; return true; };
  window.alert = () => { window.__probe.alert++; };
  navigator.share = () => { window.__probe.share++; return Promise.resolve(); };
  if (navigator.clipboard) navigator.clipboard.writeText =
    (t) => { window.__probe.clip++; window.__clip = t; return Promise.resolve(); };
  const ec = document.execCommand && document.execCommand.bind(document);
  document.execCommand = (c, ...a) => { if (/copy/i.test(c)) window.__probe.clip++; return ec ? ec(c, ...a) : true; };
  const oi = HTMLInputElement.prototype.click, oa = HTMLAnchorElement.prototype.click;
  HTMLInputElement.prototype.click = function () { if (this.type === "file") { window.__probe.file++; return; } return oi.call(this); };
  HTMLAnchorElement.prototype.click = function () { if (this.download) { window.__probe.dl++; return; } return oa.call(this); };
  window.print = () => { window.__probe.print++; };
  window.addEventListener("scroll", () => { window.__probe.scroll++; }, true);
  document.addEventListener("focusin", (e) => {
    window.__probe.focus = e.target.id || (e.target.tagName + "." + (e.target.className || ""));
  }, true);
  window.__h = (s) => {
    let x = 2166136261;
    for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); }
    return (x >>> 0).toString(36);
  };
  // 六个哈希：屏的 HTML、屏上的文字、当前提示、state、落盘那份、原生计数。
  // 注意比的是**内容**不是长度：换一张同样长的笺，长度签名会说「什么都没变」。
  window.SIG = () => JSON.stringify([
    window.__h(document.getElementById("app").innerHTML),
    window.__h(document.body.innerText),
    window.__h((document.querySelector(".toast") || {}).textContent || ""),
    window.__h(JSON.stringify(state)),
    window.__h(localStorage.getItem("jian.v1") || ""),
    window.__h(JSON.stringify(window.__probe)),
  ]);
  window.LIST = (screen) => {
    const sec = document.getElementById(screen);
    if (!sec) return [];
    const clickable = (el) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return false;
      if (typeof el.onclick === "function") return true;
      try { return el.matches("button, summary, [role='button'], [onclick]"); } catch (_) { return false; }
    };
    return [...sec.querySelectorAll("*")].filter(clickable).filter((el) => el.getClientRects().length);
  };
  // 稳定身份：路径 + 文字 + 同名第几枚，外加「同一爹的第几枚」这个组号。
  // 用下标会点错东西：上一枚删掉一张笺，列表就缩短了。
  window.KEYS = (screen) => {
    const path = (el) => {
      const seg = []; let n = el;
      while (n && n.id !== screen && seg.length < 3) {
        seg.unshift(n.tagName.toLowerCase() + (n.id ? "#" + n.id : "") +
          (typeof n.className === "string" && n.className
            ? "." + n.className.trim().split(/\s+/).slice(0, 2).join(".") : ""));
        n = n.parentElement;
      }
      return seg.join(">");
    };
    const label = (el) => ((el.getAttribute("aria-label") || el.textContent || el.value || "")
      .trim().replace(/\s+/g, " ").slice(0, 26));
    const seen = {};
    const pool = new Set(window.LIST(screen));
    return window.LIST(screen).map((el) => {
      const base = path(el) + "|" + label(el);
      seen[base] = (seen[base] || 0) + 1;
      const kk = base + "#" + seen[base];
      // 同一爹下面的可点控件数：这是「这一组里至少有一枚按了对」那条规矩的组号。
      const kids = el.parentElement ? [...el.parentElement.children].filter((c) => pool.has(c)) : [];
      // 组的身份带**全组标签**而不是孩子数：一个被守卫挡回去的 toggle 也是「选中态」，
      // 光看 aria-pressed 会把它放过去（silentscan 抓到 app.js 那句就是这个）。
      // 标签一改这一串就变，白名单会红——那是故意的，逼人回来重看一遍。
      const gid = el.parentElement.id ? "#" + el.parentElement.id : el.parentElement.tagName.toLowerCase();
      // data-* 的名字（不带值）单独报一份：预置维度点名的那些枚大多没有 id，
      // 靠 [data-move-to] / [data-item-cat] 这种属性名才认得出「这一枚到底扫到过没有」。
      const dt = [...el.attributes].filter((a) => a.name.indexOf("data-") === 0)
        .map((a) => a.name).join(",");
      // 身份表：元素 → key。预置步点完就把界面重建了（整片 innerHTML），
      // 拿着元素去问「你刚才那枚叫什么」问不到，所以趁还在的时候登记下来。
      window.__keymap.set(el, kk);
      return {
        key: kk, path: path(el), label: label(el), dt: dt,
        group: gid + "|" + kids.map(label).sort().join("/").slice(0, 90),
        // 只跳**真** disabled。aria-disabled 的那些年都不跳：那一枚照样聚焦、照样按得下去，
        // 所以它必须开口——开不了口就该红，这正是第 57 轮裁决换轨换来的可观察面。
        disabled: el.disabled === true,
        // class 兜底暂时留着：等 #11 把每一组开关态都补上 aria-pressed 之后要砍掉
        // （storeready 的 B1）。留着的时候，「守卫型 toggle 冒充单选」这条缝还开着，
        // 所以 [data-mod] 那一族只能靠 §3 的「当场演一遍让不让出选中位」来挡。
        // v0.6.0：**aria-selected / aria-checked 也算选中**。页签（role="tab"）按 ARIA 的正确
        // 写法就该是 aria-selected，不是 aria-pressed——0.6.0 的衣笺/味笺页签正是这样写的，
        // 而这里只认 aria-pressed 与 class="on"，于是页签组被当成「没有选中态」，
        // 六条页签场景全部误报成「按了没反应」（其实是那枚本来就是当前页签，点了不换是对的）。
        pressed: el.getAttribute("aria-pressed") === "true"
          || el.getAttribute("aria-selected") === "true"
          || el.getAttribute("aria-checked") === "true"
          || /(^|\s)on(\s|$)/.test(el.className),
      };
    });
  };
  // 预置点击序列：按顺序真点几下，把界面摊到要审的那个状态，**每跳都量一次有没有摊开**。
  // 返回每一步的 {selector, key, moved, said}：key 给 5b 用来把它从 dead 账里摘出去，
  // moved 给第 5 节用来证明这套预置不是在做白日梦。
  window.PRE = (steps) => {
    const out = [];
    let p = Promise.resolve();
    steps.forEach((sel) => {
      p = p.then(() => new Promise((res) => {
        const el = document.querySelector(sel);
        if (!el) { out.push({ selector: sel, key: null, moved: false, said: "这一枚找不到" }); return res(); }
        const key = window.__keymap.get(el) || null;
        const s0 = window.SIG();
        el.click();
        setTimeout(() => {
          const moved = window.SIG() !== s0;
          out.push({ selector: sel, key: key, moved: moved,
                     said: ((document.querySelector(".toast") || {}).textContent || "").slice(0, 18) });
          res();
        }, 260);
      }));
    });
    return p.then(() => out);
  };
  return 1;
}"""

# 每屏一份种子。只摆**用户真能进到的状态**：报告页那份是旧版备份里那张没有 .new 的报告
# ——那一格同时钉住两条：文字仍能复制（不灰），图存不出来（灰）。
SEEDS = {
    "onboard": "() => { state.onboarded = false; save(state); paintNav(); return 1 }",
    "yi": r"""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.points = 40; state.plan = null; state.editCloset = true;
      // 以前这一格写的是 clothSel = 0。衣柜的 id 是 "w1".."w6"（state.js:34），而 state.js:375
      // 那句 `if (s.clothSel !== null && !wardrobe.some(w => w.id === s.clothSel)) clothSel = null`
      // 会把这个 0 判成非法**当场清成 null** —— 于是 #clothActions 整块 14 枚编辑器
      // （六个品类 + 四个季节 + 补图/现拍/今天穿了/…）永远不渲染，门恰好停在空态上。
      state.clothSel = (state.wardrobe[0] || {}).id || null;
      save(state); paintNav(); return state.wardrobe.length }""",
    "yi-report": r"""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.lastReport = { t: Date.now(), stamp: "宜入", quote: "柜子最像的一件：燕麦针织",
                           basis: { name: "燕麦针织", cat: "上衣", wear: "穿过 9 次" }, gap: 12, match: [] };
      // 没有 .new：这是旧版本存下来的那张报告（导入的备份里就会是这样）
      save(state); paintNav(); return !!state.lastReport.new }""",
    "wei": r"""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.points = 40; state.weiMode = "friends";
      state.weiMenu = ""; save(state); paintNav(); return state.people.length }""",
    "yan": r"""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.points = 40; state.yanText = "小红：明天开会。\n小王说：把发票发我。";
      state.yanCards = normCards(Engine.yan(state.yanText));
      save(state); paintNav(); return state.yanCards.length }""",
    "me": r"""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.points = 40; state.plan = null;
      const DAY = 86400000;
      state.album = ["yi", "wei", "yan"].map((t, i) => ({
        type: t, t: Date.now() - i * DAY, quote: "标题" + t,
        text: "整张笺" + t + "的内容要更长一些", stamp: "宜入" }));
      save(state); paintNav(); return state.album.length }""",
}

SCREENS = ["onboard", "yi", "yi-report", "wei", "yan", "me"]

# 第二趟：什么都不摆的出厂空态。第 57 轮那两枚「按了没反应」的章正是空态养出来的——
# 有内容的那一趟里它们要么该亮着、要么被内容盖住，量不到。
EMPTY = r"""() => {
  state.onboarded = true;
  state.modules = { yi: true, wei: true, yan: true };
  state.points = 24; state.plan = null;
  state.wardrobe = []; state.album = []; state.yanCards = [];
  state.yanText = ""; state.weiMenu = ""; state.weiHist = [];
  state.lastReport = null; state.lastNew = null; state.lastWei = null; state.lastYan = null;
  state.people = [{ name: "我", chips: [] }];
  state.clothSel = null; state.editCloset = false;
  save(state); paintNav(); return 1 }"""

# 第三趟：只剩一笺开着。silentscan 抓到 app.js 那句「关掉最后一笺」把改动原样撤回、
# 一句解释都没有——那种 chip 当时正是「选中态」，只凭 class 判豁免会放它过去。
ONE = r"""() => {
  state.onboarded = true; state.modules = { yi: true, wei: false, yan: false };
  state.points = 40; save(state); paintNav(); return 1 }"""

# 引导页 + 一个已经定好的 home：这就是 #14 那块「进屏不照 state 刷就会说谎」的场景。
PREFER = r"""() => {
  state.onboarded = false; state.home = "yan"; save(state); paintNav(); return 1 }"""

# ---- 第 58 轮：把「够不着的那些枚」摆进来 ----
# 下面这些种子不是为了多扫几枚而凑的：silentscan 在任务板 #3 交回一份缺口清单，逐条点名了
# 一批**从来没有任何一道门量过**的控件，这里一条条对着摆进来（对不上的那几条见第 5 节的点名检查）。

# 排过的桌（[data-hist]）：出厂没有历史，所以这四枚从来不在清单上。
HIST = r"""() => {
  state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
  state.points = 40; state.weiMode = "friends"; state.weiMenu = "";
  const DAY = 86400000;
  state.weiHist = [0, 1, 2, 3].map((i) => ({ menu: "宫保鸡丁、白灼菜心、米饭。第" + i + "道",
                                             n: 2 + i, t: Date.now() - i * 2 * DAY, chips: [] }));
  save(state); paintNav(); return state.weiHist.length }"""

# 笺册长过一页（13 张 > me.js:24 ALBUM_PAGE=12）：只有跨过那一格才摆得出
# [data-aall]「看另外 N 张」，也才谈得上「收起」。
LONG_ALBUM = r"""() => {
  state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
  state.points = 40; state.plan = null;
  const DAY = 86400000;
  state.album = Array.from({ length: 13 }, (_, i) => ({
    type: ["yi", "wei", "yan"][i % 3], t: Date.now() - i * DAY,
    quote: "标题" + i, text: "整张笺" + i + "的内容要更长一些，长得值得单独摊开来看",
    stamp: "宜入" }));
  save(state); paintNav(); return state.album.length }"""

# 勾掉一条：#yanPrune 是 yan.js:318 用 hidden 收放的，一条都没勾时它存在但不显示
# （getClientRects 为 0，LIST 不收）——所以这一枚以前从没被量过。
YAN_DONE = r"""() => {
  state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
  state.points = 40; state.yanText = "小红：明天开会。\n小王说：把发票发我。";
  state.yanCards = normCards(Engine.yan(state.yanText));
  if (state.yanCards.length) state.yanCards[0].done = true;
  save(state); paintNav(); return state.yanCards.filter((c) => c.done).length }"""

# 有上一张报告：#openLast（ui.js:379）要求 lastReport.new 为真，而 SEEDS["yi-report"]
# 那份**故意**没有 .new。silentscan 说这一枚全仓零门覆盖。
HAVE_LAST = r"""() => {
  state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
  state.points = 40;
  state.lastReport = { t: Date.now(), new: true, stamp: "宜入",
                       quote: "柜子最像的一件：燕麦针织", gap: 12, match: [] };
  save(state); paintNav(); return !!state.lastReport.new }"""


PROBE = r"""(args) => {
  const list = window.LIST(args.screen), keys = window.KEYS(args.screen);
  const idx = keys.findIndex((k) => k.key === args.key);
  if (idx < 0) return { err: "这一枚在重开之后不在了" };
  const el = list[idx];
  const s0 = JSON.parse(window.SIG()), p0 = JSON.stringify(window.__probe);
  el.click();
  return new Promise((res) => setTimeout(() => {
    const s1 = JSON.parse(window.SIG());
    res({
      dom: s0[0] !== s1[0], words: s0[1] !== s1[1], toast: s0[2] !== s1[2],
      st: s0[3] !== s1[3], ls: s0[4] !== s1[4],
      native: Object.keys(window.__probe).filter((k) => window.__probe[k] !== JSON.parse(p0)[k]),
      pressed: el.getAttribute("aria-pressed") === "true" || /(^|\s)on(\s|$)/.test(el.className),
      said: ((document.querySelector(".toast") || {}).textContent || "").slice(0, 18),
    });
  }, args.ms));
}"""

# 「这一组到底是不是单选」不靠白名单点名字，靠**看**：去点同组另一枚，回来问这一枚还选不选中。
# 单选组会把选中的位置让出去（脱灰/失去 .on）；多选组里那一枚该还亮着。
# 这一条是为 app.js 那个「关掉最后一笺」补的：那一枚 chip 当时正是选中态，
# 只凭「已选中的那一枚 + 同组有人按对了」这条豁免它刚好溜过去（silentscan 抓到）。
RADIO_PROBE = r"""(args) => {
  const list = window.LIST(args.screen), keys = window.KEYS(args.screen);
  const i = keys.findIndex((k) => k.key === args.key);
  if (i < 0) return { err: "找不到这一枚" };
  // 「选中」的判法必须与 KEYS 里那一处**同一个口径**：页签用的是 aria-selected，
  // 只认 aria-pressed 的话页签组会被读成「一直没选中」。这里两处一起认。
  const on = (el) => el.getAttribute("aria-pressed") === "true"
    || el.getAttribute("aria-selected") === "true"
    || el.getAttribute("aria-checked") === "true"
    || /(^|\s)on(\s|$)/.test(el.className);
  const el = list[i];
  const before = on(el);
  const j = keys.findIndex((k, n) => n !== i && k.group === keys[i].group && !k.disabled);
  if (j < 0) return { before, after: before, sib: false, sibLabel: "", sibOn: false };
  const sibLabel = keys[j].label, meLabel = keys[i].label, gid = keys[i].group.split("|")[0];
  list[j].click();
  return new Promise((res) => setTimeout(() => {
    // 「这一枚还是不是选中的」必须**重开一次 DOM 再找**，两个坑都踩过：
    //  1) 不能拿手上那个节点问。整片重建的那一排（`#yiCats`、忌口展开后的 picker）
    //     节点已 detached，问 className 永远还是「on」→ 真单选被报成「还选着」。
    //  2) 不能拿旧 key 找：key 里带着 class，选中位一让出去 key 就变，必然「找不到」。
    //     也不能拿整条 group 找：group 里带着**全组标签**，重建那一排标签也变了
    //     （空柜的「香菜」与「味 1」两格就是这么假红的）——只认父层那个 gid。
    // 再加一条更硬的判据：**单选的本质是"选中位落到我刚点的那枚同组人身上"**，
    // 所以顺手问兄弟那一枚现在选不选中。目标找不到时，它兜住判断。
    const l2 = window.LIST(args.screen), k2 = window.KEYS(args.screen);
    const find = (lab) => {
      const n = k2.findIndex((x) => x.label === lab && x.group.split("|")[0] === gid);
      return n < 0 ? null : { on: on(l2[n]), pressed: l2[n].getAttribute("aria-pressed") };
    };
    const mine = find(meLabel), his = find(sibLabel);
    res({ before, after: mine ? mine.on : null, sib: true, sibLabel,
          sibOn: his ? his.on : false, gone: !mine });
  }, 260));
}"""

# ---- 第 58 轮：扫描清单 = 三趟种子 + A 类缺口 + 预置点击序列 ----
# 一份场景 = {tag, screen, area, seed, setup, pre}：
#   seed   赋 state（进 page 就跑）；setup 摆 DOM（值、遮罩这类不进 state 的东西）；
#   pre    预置点击序列（模块级 let 只认这个）；area 要审的那片地方的元素 id
#          —— 默认就是这一屏，等网关是 #veil、刚删一张的撤销是 #toasts（都在屏外）。
A_GAPS = [
    {"tag": "排过的桌", "screen": "wei", "area": "wei", "seed": HIST},
    {"tag": "笺册长过一页", "screen": "me", "area": "me", "seed": LONG_ALBUM},
    {"tag": "勾掉一条", "screen": "yan", "area": "yan", "seed": YAN_DONE},
    {"tag": "有上一张", "screen": "yi", "area": "yi", "seed": HAVE_LAST},
    {"tag": "引导页带着偏好", "screen": "onboard", "area": "onboard", "seed": PREFER},
    # 筛空了才浮出的那两枚出路（#clearSearch / #clearYanSearch）：搜索词写在 input 的
    # value 里（yi.js:32 closetQuery、yan.js:174 yanQuery），不在 state 里，只能摆 DOM。
    # v0.6.0：柜子那一整块搬进了「柜子」页签（#yiPaneCloset），默认停在「过笺」——
    # 不先切页签，那个 hidden 容器里的 `getClientRects().length` 是 0，扫不到任何东西，
    # 于是 #clearSearch 与 #addCloth 这两枚点名会红成「一枚都没有实测到」（假红，不是真缺陷）。
    {"tag": "柜里筛空", "screen": "yi", "area": "yi", "seed": SEEDS["yi"],
     "setup": r"""() => { setYiTab("closet"); const s = $("#clothSearch"); if (!s) return 0;
       s.value = "根本没有这个词"; renderCloset(); return 1 }"""},
    {"tag": "言笺筛空", "screen": "yan", "area": "yan", "seed": SEEDS["yan"],
     "setup": r"""() => { const s = $("#yanSearch"); if (!s) return 0;
       s.value = "根本没有这个词"; renderYan(); return 1 }"""},
    # 空柜那支「＋ 放第一件」同样在柜子页签里，同样要先切过去才量得到。
    {"tag": "空柜", "screen": "yi", "area": "yi", "seed": EMPTY,
     "setup": r"""() => { setYiTab("closet"); return 1 }"""},
    # 「先不等了」只在真的可能去等远端时才不 hidden（ui.js:83）。不真发请求，但**必须把
    # 状态摆成真的在飞**：四条 veil(true) 的调用点全都先写了 busy = true（app.js:190、
    # wei.js:190、yan.js:120、yi.js:472），所以 handler 里那句 `if (!busy) return;` 在
    # 真实路径下永远走不到。第一版种子只 veil(true) 不给 busy，量出来的「按了没反应」
    # 是场景自己造的假案 —— 补上 busy 之后这一枚真的会 giveUp + 说一句「先不等了」。
    {"tag": "等着网关", "screen": "yi", "area": "veil", "seed": SEEDS["yi"],
     "setup": r"""() => { window.JianAPI.remoteOn = () => true; JianAPI.warm();
       busy = true; veil(true, "在认这件…"); return !document.getElementById("veilOff").hidden }"""},
]

# 这一组才是 PRE 这一维存在的理由：它们的状态是模块级 `let`，赋 state 结构上到不了。
PRE_SCANS = [
    {"tag": "预置:挪到…", "screen": "yan", "area": "yan", "seed": SEEDS["yan"],
     "pre": ["#yanOut [data-move='0']"]},
    {"tag": "预置:改时间", "screen": "yan", "area": "yan", "seed": SEEDS["yan"],
     "pre": ["#yanOut [data-when='0']"]},
    {"tag": "预置:忌口全表", "screen": "wei", "area": "wei", "seed": SEEDS["wei"],
     "pre": ["#people [data-open='0']"]},
    {"tag": "预置:摊开全文", "screen": "me", "area": "me", "seed": SEEDS["me"],
     "pre": ["#album [data-aopen='0']"]},
    # albumView 也是模块级 let（me.js:23）：「全部 N 张」那枚只在**已经筛到某一笺**
    # 时才画（me.js:59），所以它只能靠先点一次 [data-aview] 才到。
    {"tag": "预置:筛到味笺", "screen": "me", "area": "me", "seed": SEEDS["me"],
     "pre": ["#albumChips [data-aview='wei']"]},
    {"tag": "预置:看另外几张", "screen": "me", "area": "me", "seed": LONG_ALBUM,
     "pre": ["#albumChips [data-aall='1']"]},
    # 「撤销」整族：toast 在 #app 外面（index.html:33），LIST 取屏内元素取不到它，
    # 而它必须先真删掉一张笺才浮得出来 → area 指到 #toasts。
    {"tag": "预置:刚删一张", "screen": "me", "area": "toasts", "seed": SEEDS["me"],
     "pre": ["#album [data-del='0']"]},
]

# ---- 0.6.0：这一版新增的九张纸 + 两组页签 ----
# 为什么必须补这一节：§3 那三趟种子只扫 `onboard/yi/yi-report/wei/yan/me` 这六**屏**，
# 而 0.6.0 把衣笺与味笺各拆成了四个页签（其余三个 `hidden`，一屏都扫不到），
# 又新加了九张子屏。实测缺口：味笺 lane 自己临时清扫 147 枚控件时抓出了一个真缺陷
# （「自己录的」分组头长得像折叠按钮却点不动）——**共享门禁一条都没覆盖到**。
# 这里把九张纸 + 六个页签逐张摆进来，让「每枚能点的控件都要有可观察的反应」这条
# 结构不变量覆盖整份 App，而不是覆盖它的一半。
V06_SEED = r"""() => {
  const DAY = 86400000, now = Date.now();
  state.onboarded = true;
  state.modules = { yi: true, wei: true, yan: true };
  state.points = 40; state.plan = null;
  // 衣柜：给两件，档案页才有东西可编辑（价格/购入日/场合都填上，CPW 那条才有结论）
  state.wardrobe = [
    { id: "v1", name: "白衬衫", cat: "上衣", color: "#f2ede2", style: "通勤", note: "",
      price: 260, boughtAt: now - DAY * 90, brand: "无印", size: "M",
      occasions: ["通勤", "正式"], tags: ["常穿"], worn: 18, lastWorn: now - DAY * 2, wearDays: [] },
    { id: "v2", name: "黑牛津鞋", cat: "鞋", color: "#2a2723", style: "通勤", note: "",
      price: 890, boughtAt: now - DAY * 400, brand: "", size: "42",
      occasions: ["通勤"], tags: [], worn: 40, lastWorn: now - DAY * 1, wearDays: [] }
  ];
  state.clothSel = "v1"; state.editCloset = false;
  state.wish = [{ id: "w1", name: "羊绒围巾", price: 480, color: "#8f6d15", why: "想要很久了",
                  t: now - DAY * 20, done: false }];
  state.outfits = [{ id: "o1", name: "上班那套", ids: ["v1", "v2"], occasion: "通勤",
                     t: now - DAY * 5, worn: 2, lastWorn: now - DAY * 3 }];
  state.yanCards = normCards(Engine.yan("小红：明天开会前把发票发我。\n小王说：下周买两盒猫罐头。"));
  if (state.yanCards.length) state.yanCards[0].done = false;
  state.reminders = [{ id: "r1", text: "交电费", at: now + DAY, repeat: "", done: false,
                       fired: false, from: "言笺" }];
  state.digest = [{ t: now - DAY, text: "好日子是自己过出来的。", from: "自己", mood: "平" }];
  state.recipes = [{ id: "x1", name: "番茄炒蛋", minutes: 15, level: "简单", serves: 2,
                     items: ["番茄 2 个", "鸡蛋 3 个"], steps: ["打蛋", "炒"], t: now - DAY * 10 }];
  state.cookLog = [{ id: "c1", name: "番茄炒蛋", t: now - DAY * 3, stars: 4, note: "", people: 2 }];
  state.market = [{ id: "m1", name: "番茄", kind: "蔬菜", qty: "2 个", done: false, t: now },
                  { id: "m2", name: "鸡蛋", kind: "蛋奶", qty: "3 个", done: true, t: now - DAY }];
  state.weeks = [{ id: "k1", start: now, days: [{ noon: ["番茄炒蛋"], night: [] }], note: "" }];
  state.people = [{ id: "p1", name: "小红", chips: ["辣"] }, { id: "p2", name: "小王", chips: [] }];
  state.log = [
    { t: now - DAY, kind: "wear", mod: "yi", ref: "v1", v: 1 },
    { t: now - DAY * 2, kind: "cook", mod: "wei", ref: "番茄炒蛋", v: 1 },
    { t: now - DAY * 3, kind: "yan", mod: "yan", ref: "言笺", v: 1 }
  ];
  state.profile = { nick: "小笺", line: "把话说清楚，把日子过明白", since: now - DAY * 40 };
  state.streak = { last: dayStr(now), days: 3, best: 5 };
  save(state); paintNav(); paintTabCounts(); return state.wardrobe.length }"""

# 页签那六个场景：切页签不会换屏，所以 screen 仍是 yi / wei，只是把隐藏的那一片摊出来。
# setup 里顺手把页签上的数字刷一遍（paintTabCounts），否则「做菜 1」那枚计数器的状态
# 与页签不同步，扫出来的是「点了没反应」。
V06_TABS = [
    ("衣笺:柜子", "yi", "closet"), ("衣笺:搭配", "yi", "outfit"), ("衣笺:愿望", "yi", "wish"),
    ("味笺:做菜", "wei", "cook"), ("味笺:买菜", "wei", "market"), ("味笺:这周", "wei", "week"),
]
# 九张子屏：每一张都指定入口函数与它要的那个对象，摆好之后正好是「用户真能进到的状态」。
V06_SCREENS = [
    ("单品档案", "yi-item", '() => { openItem("v1"); return 1 }'),
    ("搭配详情", "yi-outfit", '() => { openOutfit("o1"); return 1 }'),
    ("菜谱详情", "wei-dish", '() => { openDish("番茄炒蛋"); return 1 }'),
    ("这周菜单", "wei-week", '() => { show("wei-week"); return 1 }'),
    ("提醒总览", "yan-remind", '() => { show("yan-remind"); return 1 }'),
    ("设置", "settings", '() => { show("settings"); return 1 }'),
    ("章", "badges", '() => { show("badges"); return 1 }'),
    ("这一年", "year", '() => { show("year"); return 1 }'),
    ("找东西", "search", '() => { show("search"); return 1 }'),
    ("今日", "today", '() => { show("today"); return 1 }'),
    ("笺谱", "pu", '() => { show("pu"); return 1 }'),
]
V06_GAPS = [
    {"tag": tag, "screen": scr, "area": scr, "seed": V06_SEED,
     "setup": '() => { set%sTab("%s"); return 1 }' % ("Yi" if scr == "yi" else "Wei", tab)}
    for tag, scr, tab in V06_TABS
] + [
    {"tag": tag, "screen": scr, "area": scr, "seed": V06_SEED, "setup": js}
    for tag, scr, js in V06_SCREENS
]


def open_fresh(browser, seed):
    """一枚控件一页：新 context 的 localStorage 是干净的，上一枚落盘的东西不会漏进来。"""
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_function("() => typeof state !== 'undefined' && typeof show === 'function'")
    pg.evaluate(BOOT)
    pg.evaluate(seed)
    pg.wait_for_timeout(120)
    return ctx, pg


def arm(browser, sc):
    """开一页并把它推到该场景的起点：种子 → 进屏 → 摆 DOM → 跑完预置点击。
    返回 (ctx, page, 预置步报告)。规矩 5a 就落在这里：预置步跑完之后的这一页
    才是「摊开以后」的那个状态，基线必须从它身上取，而且不许换 context 取。"""
    ctx, pg = open_fresh(browser, sc["seed"])
    pg.evaluate("(s) => show(s)", sc["screen"])
    pg.wait_for_timeout(150)
    if sc.get("setup"):
        pg.evaluate(sc["setup"])
        pg.wait_for_timeout(150)
    # 先把屏上这一批的身份登记进 __keymap：预置步一点完界面就整片重建，
    # 那一枚元素已经从 DOM 上掉下来了，事后再问「你叫什么」问不回来。
    pg.evaluate("(s) => window.KEYS(s)", sc["screen"])
    rep = pg.evaluate("(a) => window.PRE(a)", sc.get("pre") or [])
    return ctx, pg, rep



def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        print("--- 1. 报告页三枚按钮：挡住要标出来，而且要说得出为什么 ---")
        # 这一节从前问的是 `.disabled`。第 57 轮裁决换轨：真 disabled 对读屏器与键盘是
        # **隐形**的（第 50 节那道键盘门就是把灰钮算成「够不着」，两条牙当场打起来），
        # 所以入口按钮只标 aria-disabled——能聚焦、能按下、按下去必须说话。
        ctx, pg = open_fresh(browser, SEEDS["onboard"])
        pg.evaluate("() => { state.lastReport = null; show('yi-report'); return 1 }")
        pg.wait_for_timeout(150)
        marked = pg.evaluate("""() => ["copyReport", "saveCard", "toCloset"].map((id) => {
            const b = document.getElementById(id);
            return [id, !!b && b.getAttribute("aria-disabled") === "true", !!b && b.disabled === true];
        })""")
        check("没有判定，这三枚当场就被标成「此刻不许用」（标在进屏时算，不等一次判定才刷）：" + str(marked),
              len(marked) == 3 and all(m for _, m, _ in marked), marked)
        check("而且没有一枚被**真** disabled —— 那等于把入口对用户藏起来",
              not any(d for _, _, d in marked), marked)
        for bid in ["copyReport", "saveCard", "toCloset"]:
            ctxS, pgS = open_fresh(browser, SEEDS["onboard"])
            pgS.evaluate("() => { state.lastReport = null; show('yi-report'); return 1 }")
            pgS.wait_for_timeout(120)
            t = pgS.evaluate("""(id) => { document.getElementById(id).click();
              return new Promise((r) => setTimeout(() =>
                r(((document.querySelector('.toast') || {}).textContent) || ''), 280)); }""", bid)
            ctxS.close()
            check(f"标了「不许用」的 {bid} 按下去说得出原因：「{t}」", bool(t), "（一个字都不说）")
        ctx.close()

        print("\n--- 2. 旧版那张报告（没有 .new）：文字仍可复制，图存不出来 ---")
        ctx2, pg2 = open_fresh(browser, SEEDS["yi-report"])
        pg2.evaluate("() => show('yi-report')")
        pg2.wait_for_timeout(150)
        check("复制这段话没被挡（旧报告也有字可复制）——两条条件不许被并成一条",
              pg2.evaluate("() => document.getElementById('copyReport').getAttribute('aria-disabled')") == "false",
              pg2.evaluate("() => document.getElementById('copyReport').getAttribute('aria-disabled')"))
        check("存成长图被挡（画不出那张图），但仍聚焦得到、按得下去",
              pg2.evaluate("() => { const b = document.getElementById('saveCard');"
                           " return [b.getAttribute('aria-disabled'), b.disabled]; }"),
              ["true", False])
        clip = pg2.evaluate("""() => { document.getElementById('copyReport').click();
          return new Promise((r) => setTimeout(() => r([window.__probe.clip,
            ((document.querySelector('.toast') || {}).textContent || '').trim()]), 300)); }""")
        # file:// 不是安全上下文，navigator.clipboard 常常根本没有——app 会退回 execCommand。
        # 两条路都被桩接住了，所以问的是「复制这件事发生了没有 + 它说了什么」，不问走的是哪条。
        check("按它真的复制到东西：" + str(clip[1]),
              clip[0] > 0 and "已复制" in clip[1], clip)
        ctx2.close()

        print("\n--- 2b. 屏上「选中的那枚」必须与 state 说同一句话 ---")
        # #14 修的是这个：引导页三张卡以前是全 App 唯一「状态只由 onclick 写、进屏不照 state 刷」
        # 的一组。normalizeState 把 onboarded 与 home 当两个互不相干的字段，所以一份
        # {onboarded:false, home:"yan"} 的备份一导入，屏上就会说「衣已选」而 state 是 yan。
        # 没有这一格，那个修复是**测不到**的（扫「点下去有没有反应」也抓不到开局就说谎）。
        ctxB, pgB = open_fresh(browser, PREFER)
        pgB.evaluate("() => show('onboard')")
        pgB.wait_for_timeout(150)
        agree = pgB.evaluate("""() => {
          const sel = [...document.querySelectorAll("#onboard .mode-card")]
            .filter((c) => c.getAttribute("aria-pressed") === "true")
            .map((c) => c.dataset.home);
          return [sel, state.home, document.querySelectorAll("#onboard .mode-card.on").length];
        }""")
        check("引导页上选中的那张卡，就是 state.home 说的那张：" + str(agree),
              agree[0] == [agree[1]] and agree[2] == 1, agree)
        ctxB.close()

        print("\n--- 3. 全 App 扫：每枚能点的控件都要有可观察的反应 ---")
        # 三趟种子。后两趟不是凑数：这一轮那两枚静默的章是空态养出来的，而
        # 「把最后一笺关掉」那句静默只有「只剩一笺」这一趟量得到。
        MODES = [("有内容", SEEDS, SCREENS),
                 ("空态", {s: EMPTY for s in SCREENS}, SCREENS),
                 ("只剩一笺", {s: ONE for s in ["me", "yi"]}, ["me", "yi"])]
        SCANS = [{"tag": tag, "screen": scr, "area": scr, "seed": seeds[scr], "pre": []}
                 for tag, seeds, scr_list in MODES for scr in scr_list]
        SCANS += [dict({"pre": [], "setup": None, "area": s["screen"]}, **s) for s in A_GAPS + PRE_SCANS]
        # 0.6.0 新增的六张页签 + 十一张子屏（见 V06_GAPS 上面那段说明）。
        # 不并进上面那一行是因为它们各自带 setup，且「扫到过没有」要单独点名（§6）。
        SCANS += [dict({"pre": []}, **s) for s in V06_GAPS]
        # 诊断用的窄跑：JIAN_DEAD_ONLY=标签子串（逗号分隔）。认证某一条注入时不必把三百来页全跑一遍。
        # 窄跑时所有「覆盖底线 / 点名清单」一律显式 skip —— 不然一次窄跑的绿会被当成全量的绿，
        # 那就是把这道门自己最恨的那种假绿又造出来一遍。
        if QUICK:
            print("--quick：跳过全量扫（§3 的每一枚、§6 的点名清单都不在本跑范围内；§1/§2/§4/§5 照跑）")
            SCANS = []
        if NARROW:
            keep = [s for s in SCANS if any(o in s["tag"] or o == s["screen"] for o in ONLY)]
            print("诊断窄跑：只扫 " + "/".join(ONLY) + "（%d 个场景，覆盖底线与点名清单本跑不适用）"
                  % len(keep))
            SCANS = keep
        # 预置步的账：每跳的 {场景, selector, key, moved}，以及「不许计入 dead」那批 key。
        step_log, preset_keys, scanned = [], set(), {}
        rows, groups = [], {}
        for sc in SCANS:
            tag, scr, area = sc["tag"], sc["screen"], sc["area"]
            done = set()
            while True:
                # 规矩 5a：每一枚都重开一页，并在这**同一页**里把预置步跑完，再取基线。
                ctx3, pg3, rep = arm(browser, sc)
                for st in rep:
                    st["tag"] = tag
                    step_log.append(st)
                    if st.get("key"):
                        preset_keys.add(st["key"])
                cand = [k for k in pg3.evaluate("(s) => window.KEYS(s)", area)
                        if k["key"] not in done and not k["disabled"] and k["key"] not in preset_keys]
                if not cand:
                    ctx3.close()
                    break
                k = cand[0]
                done.add(k["key"])
                scanned[tag] = scanned.get(tag, 0) + 1
                groups.setdefault(tag + "|" + scr + "|" + k["group"], []).append(k["key"])
                try:
                    r = pg3.evaluate(PROBE, {"screen": area, "key": k["key"], "ms": 260})
                except Exception as e:
                    # 「点下去把页面重开了」（清空本地数据那一句）确实是反应；但把**任何**异常
                    # 都记成反应，就等于给每一次探针崩溃发一张绿条——所以只认导航这一种说法。
                    msg = str(e).strip().replace("\n", " ")[:110]
                    if "context was destroyed" in msg or "navigation" in msg.lower():
                        r = {"dom": True, "words": True, "toast": False, "st": True, "ls": True,
                             "native": ["reload"], "pressed": k["pressed"], "said": ""}
                    else:
                        r = {"err": "探针炸了 → " + type(e).__name__ + " " + msg}
                finally:
                    ctx3.close()
                if "err" in r:
                    rows.append((tag, scr, k, "ERR", ""))
                    continue
                moved = bool(r["dom"] or r["words"] or r["toast"] or r["st"] or r["ls"] or r["native"])
                why = "选中态" if r["pressed"] else "不是选中态"
                if not moved:
                    # 「这一组是不是单选」不靠 class 猜，当场演一遍：点同组另一枚，
                    # 看它让不让出选中的位置。让出去 = 真单选；还选着 = 那是个开关，
                    # 开关按了没反应就是缺陷，不许拿「已选中」当理由。
                    # 注意这一页**也得同样跑完预置步**（arm），否则拿没摊开的界面去比
                    # 摊开过的那一枚，同组根本找不到人——那就是自己造出来的假案。
                    ctx4, pg4, _ = arm(browser, sc)
                    try:
                        ex = pg4.evaluate(RADIO_PROBE, {"screen": area, "key": k["key"]})
                    except Exception as e:
                        # 不许吞：吞掉之后「探针自己炸了」和「这一枚真不是单选」长得一模一样，
                        # 上一跑 31 条红全是从这个空 dict 里来的（红的是我的探针，不是产品）。
                        ex = {"_err": type(e).__name__ + " "
                              + (str(e).strip().splitlines() or [""])[0][:80]}
                    ctx4.close()
                    # 单选成立 = 我点之前它是选中的，且「选中位真的动了」：
                    # 要么它自己不再选中，要么（它随重建换了一排、按标签找不回来时）
                    # 选中位落到了我刚点的那枚兄弟身上。只认前者会把整片重建的那几排全判成假。
                    单选 = bool(ex.get("before")) and bool(ex.get("sib")) and (
                        ex.get("after") is False or (ex.get("gone") and ex.get("sibOn") is True))
                    if ex.get("_err"):
                        why = "豁免探针自己炸了 → " + ex["_err"]
                    elif 单选 and ex.get("gone"):
                        why = "单选组：重建之后按标签找不回来，但选中位落到了同组「%s」上" % ex.get("sibLabel", "?")
                    elif 单选:
                        why = "单选组：让出了选中位（点同组「%s」之后不再选中）" % ex.get("sibLabel", "?")
                    else:
                        why = ("单选组：让出了选中位（点同组「%s」之后不再选中）" % ex.get("sibLabel", "?")
                               if 单选 else
                               "不是单选组：点同组「%s」之后它 %s" % (
                                   ex.get("sibLabel", "没找到同组"),
                                   "还选着" if ex.get("after") else "状态没读出来"))
                rows.append((tag, scr, k, "动" if moved else "没反应", why))
                # 逐枚报一行：这一节要跑三百来页、十几分钟，中间什么都不印的话
                # 「在跑」和「卡死了」看起来一模一样（上一跑就白等过一轮）。
                print(f"    {rows[-1][3]:>3} [{tag}/{scr}] {k['label'][:22]:<22} {rows[-1][4]}", flush=True)

        dead = [x for x in rows if x[3] == "没反应"]
        errs = [x for x in rows if x[3] == "ERR"]
        for tag, s, k, _, why in dead:
            check(f"[{tag}/{s}] 「{k['label']}」按了没反应，唯一的出路是它真是单选组的当前值：{why}",
                  why.startswith("单选组"), k["path"])
        floor(f"没反应的一族（{len(dead)} 枚）每一枚都由「同组另有一枚按了对、且它把选中位让了出来」证成单选",
              all(x[4].startswith("单选组") for x in dead),
              [(x[0], x[1], x[2]["label"]) for x in dead if not x[4].startswith("单选组")][:6])
        floor(f"扫过之后没有一枚控件是「重开之后不见了」（{len(errs)} 枚）", not errs, errs[:3])
        moved_n = len([1 for r in rows if r[3] == "动"])
        floor(f"覆盖底线：真的扫到 ≥60 枚（实测 {len(rows)} 枚，其中 {moved_n} 枚按了对）",
              moved_n + len(dead) >= 60, len(rows))
        floor("覆盖底线：六屏都扫到了", len({x[1] for x in rows}) >= 5, {x[1] for x in rows})
        floor("覆盖底线：三趟种子各自都扫到了东西", len({x[0] for x in rows}) >= 3, {x[0] for x in rows})
        floor("覆盖底线：真的比过「同一组里至少一枚按了对」（组数 ≥5）", len(groups) >= 5, len(groups))
        floor("这一道门认得报告页那三枚（扫到过 #copyReport）",
              any(x[2]["path"].count("#copyReport") for x in rows), True)

        print("\n--- 4. 底栏跟着「哪几笺开着」走（paintNav 唯一量得到的那面）---")
        # 上面那一整片扫只取 section **里面**的东西，而 #nav 在 #app 外面（index.html:261），
        # 所以「把 paintNav() 从某个 handler 里删掉」这种改动到现在为止一道门都量不到。
        # 这一节就是 injections 提的那条反向缺口。
        #
        # v0.6.0 改了三件事，这条断言跟着改（都是口径，不是放宽）：
        #  1. 底栏从四枚变**五枚**，多了打头的「今日」；
        #  2. 每枚是「小印 + 标签」两段，`textContent` 会拼成「衣衣笺」——
        #     现在读 aria-label（那正是读屏器与语音控制认的那一句，也与看得见的字同一个）；
        #  3. 「我的」改名叫「册」。
        for mods in [{"yi": True, "wei": True, "yan": True},
                     {"yi": True, "wei": False, "yan": False},
                     {"yi": False, "wei": True, "yan": False}]:
            seed = ("() => { state.onboarded = true; state.modules = %s; save(state); paintNav(); return 1 }"
                    % json.dumps(mods))
            ctx5, pg5 = open_fresh(browser, seed)
            txt = pg5.evaluate(
                "() => [...document.querySelectorAll('#nav button')]"
                ".map(b => b.getAttribute('aria-label') || b.textContent.trim())")
            want = ["今日"] + [m for m, k in [("衣笺", "yi"), ("味笺", "wei"), ("言笺", "yan")] if mods[k]] + ["册"]
            check("开着 " + "、".join(want) + " 时底栏就这几枚：" + str(txt), txt == want, want)
            # 顺带钉一条更本质的：每枚按钮都必须说得出自己的名字（读屏器与语音控制的入口）。
            # 注意这里要的是 `nameless == 0`，不是把计数直接当 ok 传：0 是假值，
            # 传进去会被当成「不通过」，而它其实是「一枚都没有漏」——全 App 最标准的那种反逻辑。
            nameless = pg5.evaluate(
                "() => [...document.querySelectorAll('#nav button')]"
                ".filter(b => !(b.getAttribute('aria-label') || '').trim()).length")
            check("底栏每一枚都有一句无障碍名字（不然读屏器只能念「衣衣笺」这种拼串）",
                  nameless == 0, nameless)
            ctx5.close()
        browser.close()

    print("\n--- 5. 四条静态不变量（纯读文件，不起浏览器）---")
    # 注释先剥掉：第一版没剥，结果它把我自己那句「以前是 .btn[disabled]{opacity:.4}」的
    # 说明文字当成了违规现场。扫文本得先证明它读的是代码区。
    css = re.sub(r"/\*.*?\*/", "", (ROOT / "styles.css").read_text(encoding="utf-8"), flags=re.S)
    dis_rules = [ln.strip() for ln in css.splitlines()
                 if ("[disabled]" in ln or "[aria-disabled" in ln) and "{" in ln]
    check("禁用态的选择器里不许出现 opacity（opacity .4 实测把字压到 2.30:1，"
          "那是「读不出为什么按不动」）：" + str(dis_rules),
          len(dis_rules) >= 1 and not [r for r in dis_rules if "opacity" in r], dis_rules)
    src = {f: (ROOT / f).read_text(encoding="utf-8") for f in
           ["config.js", "engine.js", "api.js", "state.js", "ui.js", "card.js",
            "yi.js", "wei.js", "yan.js", "me.js", "app.js"]}
    wrote = [(f, i) for f, t in src.items() for i, ln in enumerate(t.splitlines(), 1)
             if re.search(r"\.disabled\s*=", ln)]
    check("产品源码里不再有任何一处写 `el.disabled =`（入口只准标 aria-disabled，"
          "真 disabled 对读屏器是隐形的）", not wrote, wrote)
    # 只堵 JS 赋值不够：模板里写一枚 `disabled="${…}"` 同样是把入口藏起来，而它一个
    # `.disabled =` 都不含 —— 第 59 轮那发注入（I11）就是从这条门走出去的。
    # `(?<![-\w])` 是为了不把 aria-disabled 一起抓进来（它含有 "disabled=" 这个尾巴）。
    hidden = [(f, i, ln.strip()[:52]) for f, t in src.items()
              for i, ln in enumerate(t.splitlines(), 1)
              if re.search(r'(?<![-\w])disabled\s*=', ln) and not ln.strip().startswith("//")]
    check("模板里也不许写**真**的 disabled 属性（`disabled=\"${…}\"` 一出现，那枚入口对"
          "读屏器和键盘就没了；要挡请用 aria-disabled，它还能聚焦、还能按下去听一句为什么）",
          not hidden, hidden)
    pat = re.compile(r'classList\.toggle\(\s*"on"|class="chip \$\{[^"\n]*\? "on"')
    aria = re.compile(r"aria-(pressed|checked|expanded|current)")
    only_class = []
    for f, t in src.items():
        lines = t.splitlines()
        for i, ln in enumerate(lines, 1):
            if pat.search(ln) and not aria.search("\n".join(lines[max(0, i - 4):i + 3])):
                only_class.append((f, i, ln.strip()[:48]))
    # 豁免按名字列死，一枚一个理由 —— 数量与名字一起核，多一枚少一枚都红：
    #   ui.js 那枚是 #veil（index.html 里 role="status" 的遮罩），根本不是控件；
    #   yi.js 那枚是 #editCloset，它的状态由按钮自己的文字说（「整理 ↔ 完成」），
    #     再加一枚 aria-pressed 等于讲两遍，还可能互相矛盾。
    CLASS_ONLY_OK = {("ui.js", 'v.classList.toggle('), ("yi.js", 'ed.classList.toggle(')}
    matched = sorted([(f, p) for f, _, s in only_class for (f2, p) in CLASS_ONLY_OK
                      if f == f2 and s.startswith(p)])
    check("「开关态只写在 class 里」的残留正好是点名的那两枚豁免：" + str(only_class),
          len(only_class) == len(CLASS_ONLY_OK) == len(matched)
          and sorted(set(matched)) == sorted(CLASS_ONLY_OK), (sorted(set(matched)), len(only_class)))

    print("\n--- 6. 预置点击序列这一维：摊开的那几跳自己要有证据，点名的那些枚要真的扫到 ---")
    # 这一节守的是第 5 条规矩的两面：预置步不许是坏掉的（第 5a/5b 的坑），
    # 而「加了十来个场景」这件事不许实际上什么也没多扫到（整片扫最容易的骗法）。
    print("     预置步逐跳：" + " / ".join(
        "%s %s%s" % (st["tag"], st["selector"], "" if st.get("moved") else " ←没摊开") for st in step_log))
    broke = [st for st in step_log if not st.get("moved")]
    floor("预置点击的每一跳都真的把界面往前推了一步（%d 跳全中）" % len(step_log),
          len(step_log) >= 7 and not broke, [(st["tag"], st["selector"]) for st in broke])
    dead_keys = {x[2]["key"] for x in rows if x[3] == "没反应"}
    check("预置步点过的那几枚一律**不计入 dead**（账上摘出去 %d 枚，dead 里一枚都没有）"
          % len(preset_keys), not (dead_keys & preset_keys), sorted(dead_keys & preset_keys)[:4])
    empty_runs = [sc["tag"] for sc in SCANS if not scanned.get(sc["tag"])]
    floor("每一个新摆进来的场景都真的量到了东西（不是空跑一趟）：" + str(empty_runs),
          not empty_runs, empty_runs)
    new_rows = [x for x in rows if x[0] not in {m[0] for m in MODES}]
    moved_new = len([1 for x in new_rows if x[3] == "动"])
    floor("A 类缺口 + PRE 这两组一共新扫到 ≥40 枚（实测 %d 枚，其中 %d 枚按了对）"
          % (len(new_rows), moved_new), len(new_rows) >= 40, len(new_rows))

    # 点名：silentscan 那份清单上每一枚，都要在这一次的实测清单上找得出来。
    # 这一组是这一维全部的牙——上面那些底线只证明「门在动」，证明不了「这一枚被看过」。
    #
    # 每一枚写清**按什么认它**，三个槽各自独立、给了就必须对上（AND）：
    #   dts   = data-* 的属性名（最准，预置那一批大多只有这个）
    #   ids   = 路径里的 #id（#yanPrune / #openLast 这种有 id 没属性的）
    #   label = 按钮上的字（「全部」「收起」「撤销」这种既没 id 也没专属属性的）
    #   intag = 出自哪一个场景（「全部」「撤销」在别的屏上也有同名的人，只按字会张冠李戴）
    # 上一版把 #id 塞进 label 槽里比，于是「只有 #id」那五枚永远匹配不上——
    # 报出来的是假红（那五枚其实扫到了），和漏扫长得一模一样，最难查的那种。
    CALL = [
        ("#clothActions 那块编辑器（品类签）", ["data-item-cat"], [], None, None),
        ("#clothActions 那块编辑器（季节签）", ["data-item-season"], [], None, None),
        ("排过的桌 [data-hist]", ["data-hist"], [], None, None),
        ("笺册翻页 [data-aall]", ["data-aall"], [], None, None),
        ("筛到某一笺之后那枚「全部 N 张」", ["data-aview"], [], "全部", None),
        ("清掉勾掉的 #yanPrune", [], ["yanPrune"], None, None),
        ("看上一张报告 #openLast（此前全仓零门覆盖）", [], ["openLast"], None, None),
        ("柜里筛空那枚出路 #clearSearch", [], ["clearSearch"], None, None),
        ("言笺筛空那枚出路 #clearYanSearch", [], ["clearYanSearch"], None, None),
        ("等网关那枚「先不等了」#veilOff", [], ["veilOff"], None, None),
        # intag 从「空态」改成「空柜」：0.6.0 把柜子搬进页签之后，「空态」那一趟的 yi
        # 停在「过笺」上，那一枚根本不在屏里（量不到的假红）。现在有一个专门先切到
        # 「柜子」页签的空柜场景，点名要认的是那一次扫到的。
        ("空柜那支 #addCloth", [], ["addCloth"], None, "空柜"),
        ("挪到…摊开后的 [data-move-to]", ["data-move-to"], [], None, None),
        ("改时间摊开后的 [data-when-to]", ["data-when-to"], [], None, None),
        ("味笺忌口全表 [data-c]", ["data-c"], [], None, "预置:忌口全表"),
        ("摊开全文之后的「收起」", ["data-aopen"], [], "收起", None),
        ("toastUndo 那枚「撤销」（在 #app 外面，屏内扫描取不到）", [], [], "撤销", "预置:刚删一张"),
    ]

    def called_for(name, dts, ids, lab, intag):
        def ok(x):
            if intag and x[0] != intag:
                return False
            k = x[2]
            have = set(d for d in (k.get("dt") or "").split(",") if d)
            if dts and not (set(dts) & have):
                return False
            if ids and not any(("#" + i) in (k.get("path") or "") for i in ids):
                return False
            if lab and lab not in (k.get("label") or ""):
                return False
            return True
        return ok

    miss = []
    for name, dts, ids, lab, intag in CALL:
        hit = [x for x in rows if called_for(name, dts, ids, lab, intag)(x)]
        floor("点名：这一枚以前从没被扫到过，现在扫到了 —— " + name
              + ("（实测 %d 枚，来自 %s）" % (len(hit), sorted({x[0] for x in hit})[:2])),
              bool(hit), "一枚都没有实测到")
        if not hit:
            miss.append(name)
    floor("点名的 %d 枚全部真的被量到过（漏掉的：%s）" % (len(CALL), miss or "无"), not miss, miss)

    print("\n--- 7. 隐私政策这一处入口（第 62 轮）：网址看得见、按得动、按了要说话 ---")
    # 第 60 轮那一页政策真的上线了，可应用里没有任何一处指得到它：商店页填的那格用户看不见，
    # 侧载进来的、以及自己在「册」里填了外部网关地址（数据就不再只在这台设备）的用户，
    # 更没有地方可查。这一节盯四件事：
    #   ① 这条 URL 在运行时源码里只有 config.js 一份（抄第二份，商店材料/政策页 canonical 迟早对不上）；
    #   ② 网址本身在屏上读得到——一枚只写着「隐私政策」的按钮不算数；
    #   ③ 链子既不许把系统那一跳掐掉（preventDefault），也不许静默：Capacitor 8 安卓侧没有重写
    #      onCreateWindow，target=_blank 走的是同窗导航 → Bridge.launchIntent → ACTION_VIEW，
    #      而那里那个 ActivityNotFoundException 是被吞掉的（源码一句 TODO）——设备上没装浏览器时
    #      点下去真的什么都不发生，所以那一句「没弹出就复制」是唯一给得出的出路；
    #   ④ 复制那一枚真的走到剪贴板，并且说话。
    cfg_txt = (ROOT / "config.js").read_text(encoding="utf-8")
    html_txt = (ROOT / "index.html").read_text(encoding="utf-8")
    m_pull = re.search(r'privacyUrl:\s*"([^"]+)"', cfg_txt)
    PU = m_pull.group(1) if m_pull else None
    check("config.js 的 JIAN_CONFIG 里有 privacyUrl 这一条（运行时读的那一份）", bool(PU),
          "config.js 里找不到 privacyUrl")
    RUNTIME_FILES = ["config.js", "engine.js", "api.js", "state.js", "ui.js", "card.js",
                     "yi.js", "wei.js", "yan.js", "me.js", "app.js", "index.html",
                     "styles.css", "manifest.json", "sw.js"]
    hits = [(f, (ROOT / f).read_text(encoding="utf-8").count(PU or "\0")) for f in RUNTIME_FILES]
    check("那条网址的字面在运行时源码里只出现一次，而且就在 config.js（"
          "me.js 抄一份、index.html 写死一份，第三个人来改就只能改对两处）：" + str([h for h in hits if h[1]]),
          [h for h in hits if h[1]] == [("config.js", 1)], hits)
    check("index.html 只留一个空容器，整块由 me.js 按 config 渲染",
          'id="privacyBox"' in html_txt and (PU or "\0") not in html_txt,
          [html_txt.count("privacyBox"), PU])

    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)

        def priv_page(seed):
            c = br.new_context(viewport={"width": 390, "height": 844})
            # 那一页挡成本地假页：这一节量的是「这一跳指到哪儿、按下去说不说话」，
            # 不是 GitHub 今天活着没有（政策页自己的门是 test/privacy_page.playwright.py）。
            c.route(re.compile("^" + re.escape(PU or "\0")),
                    lambda r: r.fulfill(status=200, content_type="text/html", body="<p>stub</p>"))
            pg = c.new_page()
            pg.goto(URL, wait_until="domcontentloaded")
            pg.wait_for_function("() => typeof state !== 'undefined' && typeof show === 'function'")
            pg.evaluate(seed)
            pg.evaluate("() => show('me')")
            pg.wait_for_timeout(150)
            return c, pg

        for tag, seed in [("有内容", SEEDS["me"]), ("出厂空态", EMPTY)]:
            c7, pg7 = priv_page(seed)
            got = pg7.evaluate("""(pu) => {
              const a = document.getElementById("privacyLink");
              const note = document.getElementById("storageNote"), rst = document.getElementById("reset");
              const pos = (x, y) => !!(x && y) && !!(x.compareDocumentPosition(y) & Node.DOCUMENT_POSITION_FOLLOWING);
              return {
                has: !!a, text: a ? a.textContent.trim() : "", visible: !!a && a.getClientRects().length > 0,
                href: a ? a.getAttribute("href") : "", target: a ? a.getAttribute("target") : "",
                rel: a ? String(a.getAttribute("rel") || "") : "", inMe: !!a && !!a.closest("#me"),
                hitH: a ? Math.round(a.getBoundingClientRect().height) : 0,
                // 位置这一条量**链子本身**，不量容器：容器在而里面什么都没渲染，
                // 照样是「入口没了」（P9 那一发就是这么露出来的）。
                nearData: pos(note, a) && pos(a, rst),
                said: ((document.querySelector(".toast") || {}).textContent || ""),
              };
            }""", PU)
            check(f"[{tag}] 这一屏读得到那条网址本身（链上的字就是 URL，不是「隐私政策」四个字）："
                  f"「{got['text']}」", got["has"] and got["text"] == PU and got["visible"] and got["inMe"], got)
            check(f"[{tag}] 链子指的就是 config.js 那一条，而且 target=_blank + rel 带 noopener",
                  got["href"] == PU and got["target"] == "_blank" and "noopener" in got["rel"], got)
            check(f"[{tag}] 入口就摆在「数据只在这台设备」那一句与「清空本地数据」之间（不许藏到别处）",
                  got["nearData"], got)
            check(f"[{tag}] 这一枚的命中区不低于 32px（它是这一屏唯一那条真的去打开的路）",
                  got["hitH"] >= 32, got["hitH"])
            if tag != "有内容":
                c7.close()
                continue
            # ③ 不许掐掉系统那一跳：dispatchEvent 返回 false == 有人 preventDefault 了
            dp = pg7.evaluate("""() => {
              const el = document.getElementById("privacyLink");
              return el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
            }""")
            pg7.wait_for_timeout(400)
            for extra in list(c7.pages)[1:]:
                extra.close()
            check("按那枚链不许 preventDefault —— 掐掉默认行为之后「打开」就永远是一句空话",
                  dp is True, dp)
            pop, pop_err = None, ""
            # 这一条以前是「点完再读 .toast」，在 file:// + 弹窗这一跳上必然读空——
            # 实测过一次，把时序量出来了：toast 在点击后 ~1.2s 挂上，~8.2s 自己摘掉
            # （ms=5200 的提示 + 1.8s 的余量），而 `page.click()` 要等新窗口那一跳走完
            # 才返回，实测 12s 以上。等它返回时提示早就没了，读到的是 ""。
            # 那不是产品不讲话，是**量法撞时序**（lane-today 在干净 HEAD 上复现过同一现象）。
            # 所以在点之前先把「说了什么」按 pushToast 那一刻记下来，点完再读账本：
            # 断言强度一点没降（仍然要求非空、仍然要求含「复制」这个出路），
            # 只是不再要求那句话说的时候恰好有人在看表。
            pg7.evaluate("""() => {
              window.__said = [];
              const log = () => {
                const t = (document.querySelector('.toast') || {}).textContent || '';
                if (t) window.__said.push(t);
              };
              new MutationObserver(log).observe(document.getElementById('toasts'),
                { childList: true, subtree: true });
              log();
            }""")
            try:
                with c7.expect_page(timeout=8000) as pi:
                    pg7.click("#privacyLink")
                pop = pi.value
            except Exception as e:
                # 「窗口根本没浮出来」就是要报的那件红事，不许让 expect_page 的超时
                # 把下面几条一起炸没（P4 那一发第一版就是整节中断，只有结果行没有账）。
                pop_err = type(e).__name__ + " " + (str(e).strip().splitlines() or [""])[0][:70]
            heard = pg7.evaluate("() => window.__said || []")
            said = heard[-1] if heard else ""
            check("按那枚链真的浮出一个窗口、指的就是那一条（App 自己那张 WebView 没离开）",
                  pop is not None and pop.url == PU, pop_err or (pop.url if pop else "没有窗口浮出"))
            check("按那枚链同时说一句话，而且那句话给出得了的出路（设备上没装浏览器时"
                  f" launchIntent 是静默失败的）：「{said}」",
                  bool(said.strip()) and "复制" in said, said)
            if pop:
                pop.close()
            # 先把上一句提示清掉：#toasts 只有一个槽（ui.js 的 pushToast 换掉旧的那一条），
            # 不清的话链子那一句还挂着，「复制这一枚说了话」会量到上一句——P12 第一版
            # 就是这么假绿过一次：那枚按钮按下去一个字都不说，门却记了它一句绿。
            pg7.evaluate("() => { const h = document.getElementById('toasts'); if (h) h.replaceChildren(); }")
            clip = pg7.evaluate("""() => {
              window.__clip = [];
              if (navigator.clipboard) navigator.clipboard.writeText =
                (t) => { window.__clip.push(t); return Promise.resolve(); };
              const ec = document.execCommand && document.execCommand.bind(document);
              document.execCommand = (c, ...a) => {
                if (/copy/i.test(c)) window.__clip.push(String(document.activeElement
                  && document.activeElement.value || ""));
                return ec ? ec(c, ...a) : true;
              };
              document.getElementById("copyPrivacyUrl").click();
              return new Promise((r) => setTimeout(() => r([window.__clip,
                ((document.querySelector(".toast") || {}).textContent || "")]), 320));
            }""")
            check("「复制这段网址」按下去真的复制到了那一条（走 ui.js 现成的 copy()）：" + str(clip[0]),
                  bool(clip[0]) and clip[0][-1] == PU, clip)
            check(f"而且它说了话：「{clip[1]}」", bool(clip[1].strip()), clip)
            c7.close()
        br.close()

    for pid in ["#privacyLink", "#copyPrivacyUrl"]:
        hit = [x for x in rows if pid.strip("#") in (x[2]["path"] or "")]
        floor(f"全量扫真的扫到过这一枚入口 {pid}（实测 {len(hit)} 次，来自 "
              f"{sorted({x[0] for x in hit})[:3]}）——不许只靠 §7 自己点自己",
              bool(hit) and all(x[3] == "动" for x in hit), [(x[0], x[3]) for x in hit])

    bad = [c for c in checks if not c[0]]
    print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
    return 1 if bad else 0


assert "EXEMPT" not in main.__code__.co_varnames, (
    "EXEMPT 这个名字已经退休：它一度同时是 JS 探针与 §5 白名单（局部赋值 → UnboundLocalError → 被 except 吞 → 单选豁免静默失效）。函数体内再赋一次同名值，Python 就把它"
    "当整函数的局部变量，于是 evaluate(EXEMPT) 每次抛 UnboundLocalError、被 except 吞成「探针炸了」，"
    "单选豁免整节静默失效（ariaudit 用 AST 抓到的，2026-09-23）。")


if __name__ == "__main__":
    # line_buffering：这一跑要十几分钟，不逐行冲出去的话日志全程是空的，
    # 只能干等最后一刻（上一跑就是这样，白等了四分钟才知道该看的东西一条没落盘）。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    raise SystemExit(main())
