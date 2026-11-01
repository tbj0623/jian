# 「笺」无障碍门：把 WCAG 里能被数出来的那几条，逐屏真量一遍。
#
# 为什么单独一道门：本仓已经有一批自觉的写法（ui.js 的常驻 live region、show() 把焦点
# 交给 h1、禁用只标 aria-disabled、focusKey/restoreFocus、页签 roving tabindex），
# 但**没有一处是被数出来的**。0.6.0 把 1 屏拆成 5 主屏 + 11 子屏 + 8 个页签之后，
# 「哪个新控件没名字 / 哪个新屏跳级 / 哪个 hidden 的子树还能 Tab 进去」全靠肉眼。
# 第 47 轮「能点但键盘走不到」和第 39 轮「触摸目标尺寸」都是同一族：逐例靠记性，
# 迟早漏。这里把 9 条变成结构不变量，扫全部 24 个屏/页签状态。
#
# 九条（对应 WCAG 2.2 的条款号）：
#   1. 4.1.2 名称角色值 —— 每个可交互元素都有非空的可访问名字（只靠 placeholder 不算）
#   2. 1.1.1 非文本内容 —— <img> 有 alt；装饰图标 aria-hidden；.seal-mark 是装饰
#   3. 1.3.1 / 2.4.6 标题层级 —— 每屏恰好一个 h1（有标题的屏）、不跳级、换屏之后是新屏的
#   4. 2.4.3 焦点顺序 —— Tab 走一遍不越界（[hidden] 的子树、非当前屏、连跑两轮同一条路）
#   5. 2.1.1 键盘 —— div[role=button] 有 Enter/Space；页签组左右方向键能换；Enter 真能激活
#   6. 1.4.3 对比度 —— 深色 + 浅色两趟，逐屏量正文/次要文字/按钮文字（浅色的整片扫在
#      contrast.playwright.py 里，这里补它没覆盖的：深色模式 + 全部新屏）
#   7. 2.5.5 / 2.5.8 目标尺寸 —— 命中区 ≥44×44（.chip 34px 是历史遗留，另立点名清单）
#   8. 2.3.3 动效 —— :root.no-motion 下动画/过渡时长必须 ≈0
#   9. 1.4.1 不只靠颜色 —— 每一处「选中/未选中」都要有 aria 状态，不能只有 .on 这个 class
#
# 运行：PYTHONIOENCODING=utf-8 python test/a11y_v06.playwright.py
#
# ==================== 这一版修掉的两处探针自身的事故 ====================
#
# ① 第一版整个脚本**跑不起来**，崩在：
#      Page.evaluate: SyntaxError: Failed to execute 'closest' on 'Element':
#                      '#' is not a valid selector.
#    根因：第 3b 节有一段用 Python 字符串拼 JS，写成 `a.closest('#' + '""" + r"""')`
#    ——本意是「看看焦点是不是在这一屏里」，结果拼出来的选择器就是个孤零零的 `#`，
#    而 `closest('#')` 里 `#` 后面没有 id，CSS 直接判它非法、抛 SyntaxError。
#    那一刻**整个脚本停在第 3b 节**，后面的第 4–10 节一条都没跑过：
#    所以当时「26 通过 / 10 失败」这个数字是假的，它量的是半条门。
#    改法：不再拼选择器，改成把屏名当**参数**传进去，
#    `const s = document.getElementById(sid)`，再用 `s.contains(a)` 判包含关系。
#    教训写在这里：JS 里凡是 `closest(...)` / `querySelector(...)`，选择器都必须是从
#    真实数据里出来的完整串；用字符串拼接去凑一个选择器，崩的是整道门，不是一条断言。
#
# ② `closest('[hidden]')` 这类**合法但不够**的写法还有一处没说清（第 4b 节）：
#    `[hidden]` 的 attr 在、计算后的 display 却不是 none 时，子树照样画着、照样 Tab 得进去。
#    本仓就有两处真这么漏过（.dish-grid 与 #yanSearchBar），所以第 4b 节的判据
#    从一开始就不是「属性在不在」，而是「属性在、子树却还渲染着」。
import json
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
OUT = ROOT / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

errors = []
checks = []
rows = []


def check(name, got, want=True):
    """want 省略 = 只要真值；给了具体值 = 逐字比（与 smoke.py / yi_v06 同一把尺）。"""
    ok = bool(got) if want is True else (got == want)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {_short(got)}" + ("" if ok else f"   (期望 {_short(want)})"))
    return ok


def _short(v):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 240 else s[:240] + f"…(+{len(s) - 240})"


# ==================== 种子：一屏都是「用户真能进到的状态」 ====================
# 空态养不出缺陷，也量不出缺陷。这一份和 dead_controls 的 V06_SEED 同一形状（四类都有货），
# 但**不共用**：那道门改种子是为了「按下去有没有反应」，这道门要的是「每一块都画出来」，
# 两边各自该有自己的一份，共一份迟早为了 A 把 B 量瞎。
SEED = r"""() => {
  const DAY = 86400000, now = Date.now();
  state.onboarded = true;
  state.modules = { yi: true, wei: true, yan: true };
  state.points = 40; state.plan = null;
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

# 每一屏：名字（报告里就用这个）/ 怎么进去 / 期望的 h1（None = 这一屏按设计没有 h1）。
# 「按设计没有 h1」的那几张不是漏：它们是**详情页**，标题是内容里的 h2（单品名、菜名），
# 而顶栏那行 .brand 是「衣 · 单品」这种眉料，不是标题。第 3 条对它们的要求改成
# 「不许有 h1，但必须有 h2，且 h2 就是这一屏在讲的那件事」——见 §3。
SCENES = [
    ("onboard", "() => { state.onboarded = false; save(state); show('onboard'); return 1 }", "笺"),
    # 今日这一屏的 h1 是「早上好」（按时段变的问候，见 today.js），不是屏名：屏名在 .brand 里
    # （aria-label="今日" 挂在 section 上）。所以这里只断言「恰好一个 h1」，不断言它的字。
    ("today", "() => { show('today'); return 1 }", "早上好"),
    ("pu", "() => { show('pu'); return 1 }", "用过的日子"),
    ("badges", "() => { show('badges'); return 1 }", "一枚一枚攒"),
    ("year", "() => { show('year'); return 1 }", "这一年"),
    ("yi", "() => { show('yi'); setYiTab('pass'); return 1 }", "先问柜子"),
    ("yi/closet", "() => { show('yi'); setYiTab('closet'); return 1 }", "先问柜子"),
    ("yi/outfit", "() => { show('yi'); setYiTab('outfit'); return 1 }", "先问柜子"),
    ("yi/wish", "() => { show('yi'); setYiTab('wish'); return 1 }", "先问柜子"),
    ("yi-report", "() => { state.lastReport = { t: Date.now(), new: true, stamp: '宜入',"
                  " quote: '柜子最像的一件：燕麦针织', basis: { name: '燕麦针织', cat: '上衣',"
                  " wear: '穿过 9 次' }, gap: 12, match: [] }; save(state); paintReport();"
                  " show('yi-report'); return 1 }", None),
    ("yi-item", "() => { openItem('v1'); return 1 }", None),
    ("yi-outfit", "() => { openOutfit('o1'); return 1 }", None),
    ("wei", "() => { show('wei'); setWeiTab('plan'); return 1 }", "这桌能入口"),
    ("wei/cook", "() => { show('wei'); setWeiTab('cook'); return 1 }", "这桌能入口"),
    ("wei/market", "() => { show('wei'); setWeiTab('market'); return 1 }", "这桌能入口"),
    ("wei/week", "() => { show('wei'); setWeiTab('week'); return 1 }", "这桌能入口"),
    ("wei-dish", "() => { openDish('番茄炒蛋'); return 1 }", None),
    ("wei-week", "() => { show('wei-week'); return 1 }", None),
    ("yan", "() => { show('yan'); return 1 }", "说过就算数"),
    ("yan-remind", "() => { show('yan-remind'); return 1 }", None),
    ("me", "() => { show('me'); return 1 }", "笺册"),
    ("settings", "() => { show('settings'); return 1 }", "把笺调顺"),
    # 搜索这一屏的 h1 由「找东西」这句话自己当（settings.js 的 renderSearch 在空态里
    # 只画一句提示，没有标题）——它进 NO_H1，但下面那条「必须有 h2」会把它点出来。
    ("search", "() => { show('search'); return 1 }", None),
]
# yi-item / yi-outfit / wei-dish 这三屏按设计没有 h1：它们是**详情页**，标题是内容里的 h2
# （单品名、菜名、搭配名），而顶栏那行 .brand 是「衣 · 单品」这种眉料，不是标题。
# 这几屏在第 3 条里走另一条要求：必须有 h2 当内容标题。
# 写死这一份名单是有意的：哪个新屏进了这张表，就说明有人**明确判断过**它不该有 h1。
# （wei-week / yan-remind / search 原来也在这张表里 —— 它们是这一轮补的 h1，见报告。）
NO_H1 = {"yi-item", "yi-outfit", "wei-dish"}


# ==================== 量具（全部在页面里跑，Python 只管判） ====================

# 可访问名字：按 accname 的优先序取一份够用的近似。
# **placeholder 不算名字**（WCAG 4.1.2 与 accname 规范都不把它当名称；它一打字就没了）。
NAME_FN = r"""
  const imgAlt = (el) => {
    const im = el.matches('img') ? el : el.querySelector('img[alt]');
    return im && (im.getAttribute('alt') || '').trim() ? (im.getAttribute('alt') || '').trim() : '';
  };
  const flat = (root, exclude) => {
    let out = '';
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) out += c.nodeValue;
        else if (c.nodeType === 1) {
          if (c === exclude) continue;
          if (c.getAttribute('aria-hidden') === 'true') continue;
          if (getComputedStyle(c).display === 'none') continue;
          walk(c);
        }
      }
    };
    walk(root);
    return out.replace(/\s+/g, ' ').trim();
  };
  const accName = (el) => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map((i) => (document.getElementById(i) || {}).textContent || '')
        .join(' ').replace(/\s+/g, ' ').trim();
      if (t) return { n: t, how: 'labelledby' };
    }
    const al = (el.getAttribute('aria-label') || '').trim();
    if (al) return { n: al, how: 'aria-label' };
    if (el.labels && el.labels.length) {
      const t = [...el.labels].map((l) => flat(l, el)).filter(Boolean).join(' ').trim();
      if (t) return { n: t, how: 'label' };
    }
    if (el.id) {
      const fl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (fl) { const t = flat(fl, el); if (t) return { n: t, how: 'label-for' }; }
    }
    const t = flat(el, null);
    if (t) return { n: t, how: 'text' };
    const ti = (el.getAttribute('title') || '').trim();
    if (ti) return { n: ti, how: 'title' };
    const alt = imgAlt(el);
    if (alt) return { n: alt, how: 'img-alt' };
    const ph = (el.getAttribute('placeholder') || '').trim();
    if (ph) return { n: '', how: 'placeholder-only', ph };
    return { n: '', how: 'none' };
  };"""

# 一个可交互元素算不算「在场上」：自身渲染、且祖先链上没有把整棵子树藏起来的 [hidden]。
# [hidden] 的判定用**计算后的 display**而不是属性本身：作者样式会盖过 UA 的
# [hidden]{display:none}（本仓就有两处真这么漏了，见报告 §7），所以属性在不在不是证据。
VIS_FN = r"""
  const inHidden = (el) => {
    for (let p = el; p && p.nodeType === 1; p = p.parentElement) {
      if (p.hasAttribute && p.hasAttribute('hidden') && getComputedStyle(p).display !== 'none') return true;
      if (p.hasAttribute && p.hasAttribute('hidden') && getComputedStyle(p).display === 'none') return false;
    }
    return false;
  };
  const shown = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (el.getClientRects().length === 0) return false;
    if (inHidden(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };"""

# 可交互元素的全集。`[data-heat]` 必须在这里：热力图的格子是 `<span role="gridcell">`，
# 它们**点得动**（点一下开那一天的流水面板），但不在上面那几个角色里——
# 于是年视图那 371 个 11×11 的格子从来没被这道门量过一次。
# 这正是本仓那句「一条没有自检的守门，等于没有守门」：门看不见它，它就不算被守过。
# 把它们显式列进来之后，下面的 2.5.8 那一节会替它们做一次**有据可查的豁免**
# （不是漏掉，是记着为什么可以不放大），并钉住它们必须有等价的替代操作。
INTER = ("button, a, input, select, textarea, [role=button], [role=tab], [role=link],"
         " [role=checkbox], [role=switch], [role=radio], [data-heat]")

AUDIT = "() => {" + VIS_FN + NAME_FN + r"""
  const scr = document.querySelector('.screen.on');
  if (!scr) return { err: '没有 .screen.on' };
  const out = [];
  for (const el of scr.querySelectorAll('""" + INTER + r"""')) {
    if (el.closest('.file')) continue;              // 藏起来的文件框不是触摸目标（同 e2e §41）
    if (!shown(el)) continue;
    const r = el.getBoundingClientRect();
    const nm = accName(el);
    // 命中区：与 e2e 第 41 节同一把尺——表单控件包在 <label> 里时，整行就是它的命中区
    // （点那一行任何地方都会命中它）。这不是放水：勾框自己那一格另有 24px 的下限，
    // 由下面「勾框自己的方块」那一节单独量（WCAG 2.5.8）。
    // 例外：.ck-main 是 display:contents 的 label（言笺那一行，为了让三个孩子直接站进网格），
    // 它**没有盒子**（0×0）。那种情况命中区 = 它那几个兄弟盒子并起来的那一片
    // —— 点正文、点时间眉，都会勾上这一条，那才是用户手指真正的落点。
    let hw = r.width, hh = r.height, hitIsRow = false;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) {
      const l = el.closest("label");
      const lr = l ? l.getBoundingClientRect() : null;
      if (lr && lr.width > 0 && lr.height > 0) {
        hw = lr.width; hh = lr.height; hitIsRow = true;
      } else if (l) {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const c of [...l.children, l.nextElementSibling]) {
          if (!c || c === el) continue;
          const cr = c.getBoundingClientRect();
          if (cr.width <= 0 || cr.height <= 0) continue;
          x0 = Math.min(x0, cr.left); y0 = Math.min(y0, cr.top);
          x1 = Math.max(x1, cr.right); y1 = Math.max(y1, cr.bottom);
        }
        if (x1 > x0) { hw = x1 - x0; hh = y1 - y0; hitIsRow = true; }
      }
    }
    out.push({
      tag: el.tagName.toLowerCase(), id: el.id || '',
      cls: String(el.className || '').trim().slice(0, 44),
      role: el.getAttribute("role") || "",
      w: +r.width.toFixed(1), h: +r.height.toFixed(1),
      hw: +hw.toFixed(1), hh: +hh.toFixed(1),
      hitIsRow,
      name: nm.n, how: nm.how,
      ph: nm.ph || '',
      tab: el.tabIndex,
      ad: el.getAttribute("aria-disabled") === "true",
      pressed: el.getAttribute("aria-pressed"),
      selected: el.getAttribute("aria-selected"),
      checked: el.getAttribute("aria-checked"),
      type: el.getAttribute("type") || "",
      clsOn: /(^|\s)on(\s|$)/.test(String(el.className || "")),
    });
  }
  // 图片：只要在场上就算
  const imgs = [];
  for (const im of scr.querySelectorAll('img')) {
    if (!shown(im)) continue;
    imgs.push({ src: (im.getAttribute('src') || '').slice(0, 34),
                alt: im.getAttribute('alt'), hidden: im.getAttribute('aria-hidden'),
                inBtn: !!im.closest('button, a, [role=button]') });
  }
  // 印章字：.seal-mark 是装饰（母题），读屏器不该念
  const seals = [];
  for (const s of scr.querySelectorAll('.seal-mark')) {
    if (!shown(s)) continue;
    seals.push({ txt: (s.textContent || '').trim(), hidden: s.getAttribute('aria-hidden') });
  }
  // 标题：只数在场上且**不是 sr-only 之外的藏起来**的那些
  const heads = [];
  for (const h of scr.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    const cs = getComputedStyle(h);
    if (cs.display === 'none' || h.getClientRects().length === 0) continue;
    const r = h.getBoundingClientRect();
    // sr-only 是「只给读屏器」的标题：它在题面上不占版面，但读屏器念得到，所以算一级
    const sr = r.width <= 1 && r.height <= 1;
    heads.push({ tag: h.tagName.toLowerCase(), text: (h.textContent || '').trim().slice(0, 44), sr });
  }
  return {
    screen: scr.id, list: out, imgs, seals, heads,
    theme: document.documentElement.dataset.theme,
    noMotion: document.documentElement.classList.contains('no-motion'),
  };
}"""

# 对比度：与 contrast.playwright.py **同一把尺**（同一处分层合成、同一档大字判据），
# 只把范围收到「当前这一屏」并多回一个最小值，好把每屏的最低值记进量化表。
SWEEP = r"""() => {
  // 先把**已经跑完的入场动画**收干净再量：.screen.on 有一条 rise .32s 的淡入，
  // 量在半路上拿到的是 opacity .97 这种「还没落定」的合成结果，算出来的对比度
  // 会比静止态低一截（实测把一枚 4.57:1 的印章字量成 4.41:1）。
  // 只 finish 有限次的；veil 那颗呼吸章是 infinite，留它在那儿（它另有显式断言）。
  for (const a of document.getAnimations()) {
    try {
      const t = a.effect && a.effect.getComputedTiming();
      if (t && t.iterations !== Infinity) a.finish();
    } catch (_) { /* 跨文档的动画 finish 会抛：忽略这一条，它不影响文字 */ }
  }
  const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  const ratio = (a, b) => { const la = lum(a), lb = lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); };
  const rgb = (s) => { const m = String(s).match(/rgba?\(([^)]*)\)/); if (!m) return null;
    const p = m[1].split(',').map(parseFloat); return { c: [p[0], p[1], p[2]], a: p.length > 3 ? p[3] : 1 }; };
  const over = (fg, bg) => fg.c.map((v, i) => v * fg.a + bg[i] * (1 - fg.a));
  const scr = document.querySelector('.screen.on');
  const out = []; const seen = new Set(); let minR = 99, minWho = '', measured = 0;
  for (const el of scr.querySelectorAll('*')) {
    const tag = el.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'CANVAS' || tag === 'TEXTAREA') continue;
    let text = '';
    for (const n of el.childNodes) if (n.nodeType === 3) text += n.nodeValue;
    if (!text.trim()) continue;
    if (!el.getClientRects().length) continue;
    if (el.closest('[hidden]') && el.closest('[hidden]').getBoundingClientRect().width === 0) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden') continue;
    const fg = rgb(cs.color);
    if (!fg || fg.a === 0) continue;
    let op = 1, bg = [255, 255, 255], opaque = false;
    for (let p = el; p && !opaque; p = p.parentElement) {
      const pcs = p === el ? cs : getComputedStyle(p);
      op *= parseFloat(pcs.opacity);
      const b = rgb(pcs.backgroundColor);
      if (b && b.a > 0) { bg = over(b, bg); if (b.a >= 1) opaque = true; }
      if (/url\(/.test(pcs.backgroundImage)) { opaque = false; bg = null; break; }
    }
    if (!bg) continue;
    measured++;
    const txt = over({ c: fg.c, a: fg.a }, bg);
    const eff = txt.map((v, i) => bg[i] + (v - bg[i]) * op);
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const need = (size >= 24 || (size >= 18.66 && weight >= 700)) ? 3 : 4.5;
    const r = ratio(eff, bg);
    if (r < minR) { minR = r; minWho = tag.toLowerCase() + '.' + String(el.className).split(' ')[0]; }
    if (r < need - 0.005) {
      const key = tag + '|' + el.className + '|' + cs.color + '|' + cs.fontSize;
      if (seen.has(key)) continue; seen.add(key);
      out.push({ sel: tag.toLowerCase() + (el.id ? '#' + el.id : '') +
                 (el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : ''),
                 size: +size.toFixed(1), need, ratio: +r.toFixed(2), text: text.trim().slice(0, 12) });
    }
  }
  return { bad: out, minR: measured ? +minR.toFixed(2) : null, minWho, measured };
}"""

# Tab 一遍：只回报「落点是谁、在哪一屏」。判据在 Python 里（同一份口径只看一次）。
TAB_STEP = r"""() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return { body: true };
  const scr = el.closest('.screen');
  return {
    tag: el.tagName.toLowerCase(), id: el.id || '',
    cls: String(el.className || '').trim().slice(0, 30),
    name: (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 22),
    scr: scr ? scr.id : '(屏外)',
    scrOn: scr ? scr.classList.contains('on') : true,
    nav: !!el.closest('#nav'),
    veil: !!el.closest('#veil'),
  };
}"""

COUNT_FOCUS = r"""() => {
  const vis = (el) => {
    if (el.closest('[hidden]')) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    return el.getClientRects().length > 0;
  };
  const sel = 'a[href],button:not([disabled]),input:not([disabled]),select,textarea,summary,[tabindex]:not([tabindex="-1"])';
  return [...document.querySelectorAll(sel)].filter(vis).length;
}"""

# 键盘激活：Enter / Space 按下去要有东西变。量的不是「有没有 onclick」——那是猜；
# 量的是**按完之后屏上的字或 state 变了没有**（同一把尺见 dead_controls 的 SIG）。
SIG = r"""() => {
  const scr = document.querySelector('.screen.on') || document.body;
  const t = scr.textContent.replace(/\s+/g, ' ').slice(0, 6000);
  const st = JSON.stringify(state).length;
  const toast = ((document.querySelector('#toasts .toast') || {}).textContent || '');
  const focus = (document.activeElement || {}).id || '';
  const expanded = [...scr.querySelectorAll('[aria-expanded]')].map((e) => e.getAttribute('aria-expanded')).join('');
  return [t, st, toast, focus, expanded].join('|');
}"""

# no-motion：逐屏量「关键元素」的真实时长。所谓关键元素 = 这一屏里带 animation/transition
# 的那些，一个都不许漏（漏一个就等于「这一屏有没有动效」没量到）。
MOTION = r"""() => {
  const scr = document.querySelector('.screen.on');
  const bad = [];
  let n = 0;
  for (const el of [scr, ...scr.querySelectorAll('*')]) {
    if (!el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    const anim = (cs.animationName && cs.animationName !== 'none')
      ? cs.animationDuration.split(',').map((s) => parseFloat(s) * (s.includes('ms') ? 0.001 : 1)) : [];
    const tr = (cs.transitionProperty && cs.transitionProperty !== 'none')
      ? cs.transitionDuration.split(',').map((s) => parseFloat(s) * (s.includes('ms') ? 0.001 : 1)) : [];
    for (const d of [...anim, ...tr]) {
      n++;
      if (d > 0.05) bad.push([(el.tagName + '.' + String(el.className).split(' ')[0]).slice(0, 40), d]);
    }
  }
  return { n, bad: bad.slice(0, 8), secs: +document.documentElement.classList.contains('no-motion') };
}"""

# 焦点环：键盘走过去的时候，那枚控件必须画得出描边（2.4.7）。
# **必须先进键盘模态**（先按一次 Tab），否则 :focus-visible 不匹配——量到的是「本来就没描边」，
# 把整条 CSS 摘掉照样绿（e2e §6c 那一条注释里记的就是这个假门）。
#
# 事故（这一条量错过一次，写在这里免得下一个人再踩）：
# `input[type=date]`（#clothWornDay / #itemBought）按到第二下 Tab 时，焦点走进它自己的
# 影子树（Chromium 把年 / 月 / 日做成 UA 子控件）。那一刻 document.activeElement 仍然是
# 这枚 input，但 `:focus` 与 `:focus-visible` **双双为 false**、只有 `:focus-within` 是 true。
# 于是「按第一下 Tab 有环、第二下环没了」，而人正停在年那一格上。
# 这不是探针的错，是 CSS 漏了 `:focus-within`（styles.css 已补）。
# 但探针这边也要跟着认清一件事：**「现在焦点在这枚元素上」不等于「这枚元素匹配 :focus」**。
# 所以下面多回一个 within，判 ok 时两者取或 —— 否则以后任何宿主类控件
# （date / time / 未来的自绘控件）都会因为影子树被误判成「没画环」。
RING = r"""() => {
  const el = document.activeElement;
  if (!el || el === document.body) return { skip: true };
  const cs = getComputedStyle(el);
  const w = parseFloat(cs.outlineWidth) || 0;
  const box = parseFloat(cs.boxShadow && cs.boxShadow !== 'none' ? '1' : '0');
  return { who: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
           key: el.tagName + '|' + (el.id || '') + '|' + String(el.className || ''),
           w, style: cs.outlineStyle, color: cs.outlineColor,
           within: el.matches(':focus-within'),
           ok: (w >= 1 && cs.outlineStyle !== 'none') || box > 0 };
}"""

# 页签：左右方向键。
TAB_KEY = r"""(dir) => {
  const el = document.activeElement;
  if (!el) return { err: '焦点不在任何东西上' };
  const host = el.closest('[role=tablist]');
  if (!host) return { err: '焦点不在页签组里' };
  const before = el.getAttribute('data-yitab') || el.getAttribute('data-weitab') || '';
  return { host: host.id, before };
}"""


def run_tab_walk(page, label, max_steps=90):
    """按 Tab 走一圈，回 [落点]。判据：不许落到非当前屏 / [hidden] 子树 / 遮罩里；
    走到底栏之后必须还能回到屏内（否则「焦点跑到底栏之后就丢了」）。

    圈怎么算「一圈」：一直按到**第一个落点又出现**为止（自然闭环），不是数固定步数。
    以前这里写的是 nfoc+8 —— 那在底栏正好收尾的屏上会截断在半路，
    于是「底栏之后回不来」变成假红（实测 year / yi-outfit / search 三屏就这么假红过）。

    注意：浏览器把焦点从底栏最后一枚交给地址栏时，document.activeElement 会退回 body。
    所以「一圈走完」的标志是 **body**，不是「第一个落点又出现了」——后者永远等不到。"""
    page.evaluate("() => { window.scrollTo(0, 0); if (document.activeElement) document.activeElement.blur(); }")
    nfoc = page.evaluate(COUNT_FOCUS)
    stops = []
    for _ in range(max_steps):
        page.keyboard.press("Tab")
        s = page.evaluate(TAB_STEP)
        if s.get("body"):
            break                      # 焦点交给地址栏 = 这一圈走完了
        stops.append(s)
        # 兜底：万一某个浏览器不把焦点交给地址栏，走到第一个落点又出现也停
        if len(stops) > 2 and (s.get("scr"), s.get("tag"), s.get("id"), s.get("cls")) == \
                (stops[0].get("scr"), stops[0].get("tag"), stops[0].get("id"), stops[0].get("cls")):
            break
    return nfoc, stops


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        page.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
        page.clock.install(time="2026-09-17T10:00:00")
        page.goto(URL)
        page.wait_for_timeout(800)
        page.evaluate(SEED)
        page.wait_for_timeout(200)

        audits = {}
        for name, js, _h1 in SCENES:
            page.evaluate(js)
            page.wait_for_timeout(230)
            audits[name] = page.evaluate(AUDIT)
            r = audits[name]
            assert "err" not in r, f"{name}: {r.get('err')}"
            rows.append({"screen": name, "n": len(r["list"]), "small": 0, "min": {}})
        # 图片这一轮是**空集**：种子里的衣物没有照片（照片走 dataURL，种不出来），
        # 而拍/选照片那两枚是 file input 改名换姓来的。所以先给一张真的图，
        # 让「<img> 有没有 alt」这条不是对着空气自证——单品档案页与柜子瓷砖都会画它。
        page.evaluate("""() => {
          const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
          state.wardrobe[0].img = png; state.wardrobe[1].img = png;
          save(state); show('yi'); setYiTab('closet');
        }""")
        page.wait_for_timeout(320)
        img_audit = page.evaluate(AUDIT)
        audits["yi/closet"] = img_audit
        page.evaluate("() => { openItem('v1'); }")
        page.wait_for_timeout(280)
        audits["yi-item"] = page.evaluate(AUDIT)

        # ==================== 1. 可访问名字（4.1.2） ====================
        print("\n--- 1. 每个可交互元素都有非空的可访问名字（WCAG 4.1.2）---")
        total_el, total_noname, noname_list = 0, 0, []
        for name, r in audits.items():
            total_el += len(r["list"])
            bad = [e for e in r["list"] if not e["name"]]
            total_noname += len(bad)
            for e in bad:
                noname_list.append(f"{name}: <{e['tag']}{('#' + e['id']) if e['id'] else '.' + e['cls'].split(' ')[0]}>"
                                   f" {e['w']:.0f}×{e['h']:.0f} {e['how']}"
                                   + (f"（只有 placeholder「{e['ph']}」）" if e["how"] == "placeholder-only" else ""))
        check(f"扫到了 {total_el} 个可交互元素（< {220} 就是扫瞎了）", total_el >= 220, True)
        check(f"没有名字的：{total_noname} 个", noname_list, [])
        # 「只有 placeholder」单列一条：它不是空名字，但一样不合格（打字之后名字就没了）
        ph_only = [f"{n}: <{e['tag']}#{e['id']}> 只有 placeholder「{e['ph']}」"
                   for n, r in audits.items() for e in r["list"] if e["how"] == "placeholder-only"]
        check(f"只拿 placeholder 当名字的：{len(ph_only)} 个", ph_only, [])

        # ==================== 2. 图片与图标（1.1.1） ====================
        print("\n--- 2. 图片有 alt、装饰图标 aria-hidden、印章字是装饰（WCAG 1.1.1）---")
        imgs = [(n, im) for n, r in audits.items() for im in r["imgs"]]
        check(f"这一轮真的量到了图片（{len(imgs)} 张；0 张就是这条白测）", len(imgs) >= 1, True)
        check("每张 <img> 都有 alt（装饰的写空 alt，不是不写）",
              [f"{n}: {im['src']} alt={im['alt']!r}" for n, im in imgs
               if im["alt"] is None and im["hidden"] != "true"], [])
        seals = [(n, s) for n, r in audits.items() for s in r["seals"]]
        check(f"量到了 {len(seals)} 枚印章字（全 App 的母题）", len(seals) >= 15, True)
        check("每一枚 .seal-mark 都标了 aria-hidden（它是描边装饰，不是内容）",
              [f"{n}: 「{s['txt']}」" for n, s in seals if s["hidden"] != "true"], [])

        # ==================== 3. 标题层级（1.3.1 / 2.4.6） ====================
        print("\n--- 3. 每屏一个 h1、不许跳级、换屏之后是新屏的（WCAG 1.3.1 / 2.4.6）---")
        h1_bad, skip_bad = [], []
        for name, _js, want_h1 in SCENES:
            r = audits[name]
            h1s = [h for h in r["heads"] if h["tag"] == "h1"]
            if name in NO_H1:
                if h1s:
                    h1_bad.append(f"{name}: 有 {len(h1s)} 个 h1「{'/'.join(h['text'] for h in h1s)}」")
            elif len(h1s) != 1:
                h1_bad.append(f"{name}: {len(h1s)} 个 h1")
            elif want_h1 and want_h1 not in h1s[0]["text"]:
                h1_bad.append(f"{name}: h1 是「{h1s[0]['text']}」，期望含「{want_h1}」")
            # 跳级：按文档序看，后一级不许比前一级深超过 1
            levels = [int(h["tag"][1]) for h in r["heads"]]
            for a, b in zip(levels, levels[1:]):
                if b > a + 1:
                    skip_bad.append(f"{name}: h{a} → h{b}")
                    break
        check("每屏都恰好一个 h1（按设计没有 h1 的详情页另算，见下一条）", h1_bad, [])
        check("标题不跳级（h2 后面不许直接 h4）", skip_bad, [])
        # 「按设计没有 h1」的那几张：不许真的没有标题，必须有 h2 在讲这一屏在讲的那件事。
        # 这几屏的 h1 是**内容**（菜名、单品名）而不是屏名，所以要求落在 h2 上。
        nohead = [n for n in NO_H1 if not [h for h in audits[n]["heads"] if h["tag"] == "h2"]]
        check(f"没有 h1 的那 {len(NO_H1)} 屏里，每一屏都有 h2 当内容标题", nohead, [])

        # 换屏之后焦点落在**新屏**的标题上（不是上一屏的）
        print("\n--- 3b. 换屏把焦点交给新屏的 h1（读屏器才知道到了哪儿）---")
        focus_bad = []
        for scr in ("wei", "yan", "me", "settings", "pu", "today"):
            page.evaluate("(id) => show(id)", scr)
            page.wait_for_timeout(180)
            ok = page.evaluate("""(sid) => { const a = document.activeElement;
              const s = document.getElementById(sid);
              if (!a || !s || !s.contains(a)) return '焦点不在这一屏里（在 '
                + (a ? a.tagName + (a.id ? '#' + a.id : '') : '无') + '）';
              const h1 = s.querySelector('h1');
              if (!h1) return '这一屏没有 h1（本条的判据对它不适用）';
              return a === h1 ? true : ('焦点在 ' + a.tagName + (a.id ? '#' + a.id : ''));
            }""", scr)
            if ok is not True:
                focus_bad.append(f"{scr}: {ok}")
        check("换屏之后焦点落在这一屏自己的 h1 上", focus_bad, [])
        # 报告页的标题必须跟着判定换（念的是这一次的答案，不是上一次的）
        t1 = page.evaluate("""() => { state.lastReport = Object.assign({}, state.lastReport,
              { stamp: '先别' }); save(state); show('yi'); show('yi-report');
              return document.querySelector('#reportTitle').textContent; }""")
        check("报告页的标题跟着判定换（「先别」）", "先别" in t1, True)

        # ==================== 4. 焦点顺序（2.4.3） ====================
        print("\n--- 4. Tab 走一遍每屏：不许越界、底栏之后要能回来（WCAG 2.4.3）---")
        walk_bad, walk_report = [], []
        for name, js, _h1 in SCENES:
            page.evaluate(js)
            page.wait_for_timeout(200)
            nfoc, stops = run_tab_walk(page, name)
            live = [s for s in stops if not s.get("body")]
            bad = [s for s in live if (not s["scrOn"]) or s["veil"]]
            # 底栏之后必须还能回到屏内（否则「焦点跑到底栏就回不来了」）。
            # 两种合格形态：① 底栏之后还有屏内落点；② 底栏就是这一圈的最后一站
            # （再按一次焦点交给地址栏，下一圈从第一枚重新开始 —— 这是浏览器 Tab 圈的正常样子）。
            nav_at = [i for i, s in enumerate(live) if s["nav"]]
            back = (not nav_at) or (nav_at[-1] == len(live) - 1) or any(
                not s["nav"] for s in live[nav_at[-1] + 1:])
            if bad:
                walk_bad.append(f"{name}: 落到了 " + ", ".join(
                    sorted({f"<{s['tag']}#{s['id'] or s['cls'].split(' ')[0]}>@{s['scr']}" for s in bad}))[:150])
            walk_report.append({"screen": name, "focusable": nfoc, "stops": len(live), "back": back})
        check("Tab 顺序不越界（不落进非当前屏 / [hidden] 子树 / 遮罩）", walk_bad, [])
        # 「底栏之后还能不能回来」单独一条：这一圈里，底栏那几枚之后必须还有屏内的落点，
        # 或者这一圈在底栏处自然收尾（焦点交给地址栏，再 Tab 回到第一枚）。
        loop_bad = [w["screen"] for w in walk_report if not w["back"]]
        check("走到底栏之后这一圈能自然闭环（不会卡在底栏出不来）", loop_bad, [])
        check("真的走出了足够多的落点（每屏平均 < 5 就是 Tab 没在走）",
              sum(w["stops"] for w in walk_report) / len(walk_report) >= 8, True)

        # 被 [hidden] 的页签内容不许仍被 Tab 到 —— 这条单独点名，因为它是这一族里最常见的真 bug。
        # 判据不是「属性在不在」，而是「属性在、子树却还渲染着、里面的控件还 Tab 得到」。
        print("\n--- 4b. [hidden] 的子树必须真的不可聚焦（最常见的真 bug）---")
        hidden_leak = []
        for scr, js, tabs in [
            ("yi", "() => { show('yi'); setYiTab('pass'); return 1 }",
             ["yiPaneCloset", "yiPaneOutfit", "yiPaneWish"]),
            ("wei", "() => { show('wei'); setWeiTab('plan'); return 1 }",
             ["weiPaneCook", "weiPaneMarket", "weiPaneWeek"]),
        ]:
            page.evaluate(js)
            page.wait_for_timeout(200)
            leak = page.evaluate(r"""(ids) => {
              const bad = [];
              for (const id of ids) {
                const el = document.getElementById(id);
                if (!el || !el.hasAttribute('hidden')) continue;
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                if (cs.display !== 'none' || r.width > 0 || r.height > 0) {
                  // 属性挂着但子树还画着：里面的控件 Tab 得到
                  const n = [...el.querySelectorAll('button,a,input,select,textarea,[tabindex]')]
                    .filter((x) => x.getClientRects().length > 0).length;
                  bad.push([id, cs.display, Math.round(r.width), Math.round(r.height), n]);
                }
              }
              return bad;
            }""", tabs)
            hidden_leak += [f"{scr}/{x[0]}: display={x[1]} {x[2]}×{x[3]}，里面 {x[4]} 个控件还画着" for x in leak]
        # 全文档扫一遍：任何一个 [hidden] 但计算后 display 不是 none 的元素都是同一类漏
        doc_leak = page.evaluate(r"""() => {
          const out = [];
          for (const el of document.querySelectorAll('[hidden]')) {
            const cs = getComputedStyle(el);
            if (cs.display === 'none') continue;
            const r = el.getBoundingClientRect();
            const n = [...el.querySelectorAll('button,a,input,select,textarea')]
              .filter((x) => x.getClientRects().length > 0).length;
            out.push({ id: el.id || '', cls: String(el.className).slice(0, 30), disp: cs.display,
                       w: Math.round(r.width), h: Math.round(r.height), n });
          }
          return out;
        }""")
        hidden_leak += [f"全文档: <{x['id'] or '.' + x['cls']}> hidden 但 display={x['disp']}"
                        f" {x['w']}×{x['h']}，{x['n']} 个控件可聚焦" for x in doc_leak if x["n"] or x["w"] > 0]
        check("挂着 hidden 的子树一个都不许还画着（画着就是 Tab 得进去）", hidden_leak, [])

        # ==================== 5. 键盘操作（2.1.1） ====================
        print("\n--- 5. 能点的都能用键盘点：div[role=button] 的 Enter/Space、页签的左右方向键（WCAG 2.1.1）---")
        # 5a. div[role=button]（柜里那格子）：Enter 与 Space 都要激活，而且**要真的变**
        role_bad = []
        for name, js in [("yi/closet", "() => { show('yi'); setYiTab('closet'); return 1 }")]:
            page.evaluate(js)
            page.wait_for_timeout(220)
            n = page.evaluate("() => document.querySelectorAll('#closet [role=button]').length")
            if n < 1:
                role_bad.append(f"{name}: 一枚 [role=button] 都没有（这一条白测）")
            for key in ("Enter", " "):
                page.evaluate("""() => { const t = document.querySelector('#closet [role=button]');
                  t.focus(); state.clothSel = null; save(state); renderCloset();
                  document.querySelector('#closet [role=button][data-id]').focus(); }""")
                before = page.evaluate("() => state.clothSel")
                page.keyboard.press(key)
                page.wait_for_timeout(200)
                after = page.evaluate("() => state.clothSel")
                if before == after:
                    role_bad.append(f"{name}: [{key}] 按下去选中态没变（{before} → {after}）")
        check("div[role=button] 用 Enter 与 Space 都点得动", role_bad, [])

        # 5b. 页签组：ArrowRight / ArrowLeft 要换页签、并且焦点跟着走
        tab_bad = []
        for host, attr, tabs, setter in [
            ("#yiTabs", "data-yitab", ["pass", "closet", "outfit", "wish"], "setYiTab"),
            ("#weiTabs", "data-weitab", ["plan", "cook", "market", "week"], "setWeiTab"),
        ]:
            page.evaluate("(id) => show(id)", "yi" if attr == "data-yitab" else "wei")
            page.wait_for_timeout(180)
            page.evaluate(f"() => document.querySelector('{host} [{attr}]').focus()")
            for key, want in (("ArrowRight", tabs[1]), ("ArrowRight", tabs[2]), ("ArrowLeft", tabs[1])):
                page.keyboard.press(key)
                page.wait_for_timeout(180)
                got = page.evaluate(f"""() => {{
                  const a = document.activeElement;
                  const sel = document.querySelector('{host} [aria-selected="true"]');
                  return [a.getAttribute('{attr}'), sel ? sel.getAttribute('{attr}') : null,
                          '{(attr)}' === 'data-yitab' ? yiTab : weiTab];
                }}""")
                if got[0] != want or got[1] != want or got[2] != want:
                    tab_bad.append(f"{host} {key} → 期望 {want}，实测 焦点={got[0]} 选中={got[1]} 状态={got[2]}")
        check("页签组用左右方向键能换（焦点、aria-selected、内部状态三者一致）", tab_bad, [])
        # roving tabindex：选中的那个在 Tab 序列里，别的不在
        rov = page.evaluate("""() => { show('yi'); setYiTab('closet');
          return [...document.querySelectorAll('#yiTabs [role=tab]')]
            .map((b) => [b.dataset.yitab, b.tabIndex, b.getAttribute('aria-selected')]); }""")
        check("页签是 roving tabindex：只有选中的那个 tabIndex=0",
              [x for x in rov if (x[0] == "closet") != (x[1] == 0)], [])

        # 5c. 键盘激活的覆盖面：逐屏抽出每一类「看起来能点」的东西，聚焦之后按 Enter 与
        #     Space，**必须真的派发出一次 click**（这才是「激活」，不是「state 变了」）。
        #     为什么不用「屏上的字变了」当判据：已经是当前页签的那一枚、下载类的按钮、
        #     打开面板后又点同一枚 —— 它们按对了也不变字，那样量出来全是假红（第一版就是）。
        #     这条要抓的真缺陷是：`<div role=button>` / `<span onclick>` 这类只挂了
        #     onclick、没挂 keydown 的东西 —— 浏览器不会替它们合成 click。
        print("\n--- 5c. 抽到的每一枚能点的东西，Enter 与 Space 都真的派得出 click（WCAG 2.1.1）---")
        page.evaluate("""() => {
          window.__clicked = null;
          document.addEventListener('click', (e) => {
            window.__clicked = e.target;
            // 别让链接真的跳走：这一节要的是「click 派出来了没有」，不是「跳到哪儿」
            if (e.target.closest && e.target.closest('a[href]')) e.preventDefault();
          }, true);
        }""")
        kb_bad, kb_n = [], 0
        for name, js, _h1 in SCENES:
            for idx in range(3):
                for key in ("Enter", " "):
                    page.evaluate(js)
                    page.wait_for_timeout(160)
                    got = page.evaluate(r"""(arg) => {
                      const SEL = 'button, a[href], [role=button], [role=tab], [role=link]';
                      const bs = [...document.querySelectorAll('.screen.on ' + SEL.replace(/,/g, ', .screen.on '))]
                        .filter((b) => { const r = b.getBoundingClientRect();
                          return r.width > 0 && r.height > 0 && !b.closest('[hidden]')
                            && !b.closest('#nav') && !b.disabled
                            && b.getAttribute('aria-disabled') !== 'true'; });
                      const b = bs[arg.idx];
                      if (!b) return { skip: true };
                      window.__clicked = null;
                      b.focus();
                      if (document.activeElement !== b) return { skip: true, why: '聚焦不上' };
                      return { tag: b.tagName.toLowerCase(), id: b.id || '',
                               cls: String(b.className || '').slice(0, 22),
                               name: (b.getAttribute('aria-label') || b.textContent || '').trim()
                                 .replace(/\s+/g, ' ').slice(0, 14) };
                    }""", {"idx": idx})
                    if got.get("skip"):
                        continue
                    kb_n += 1
                    page.keyboard.press(key)
                    page.wait_for_timeout(180)
                    fired = page.evaluate("""() => { const c = window.__clicked;
                      const a = document.activeElement;
                      return { any: !!c, onSelf: !!(c && (c === a || (a && a.contains(c)))) }; }""")
                    if not fired["any"]:
                        kb_bad.append(f"{name}: <{got['tag']}{('#' + got['id']) if got['id'] else '.' + got['cls']}>"
                                      f"「{got['name']}」按 [{key}] 没有派发出 click")
        check(f"抽查了 {kb_n} 次键盘激活（< 60 就是抽瞎了）", kb_n >= 60, True)
        check("抽到的每一枚都真能按出 click（div[role=button] 是这一族最容易漏的）", kb_bad, [])

        # ==================== 6. 对比度（1.4.3） ====================
        print("\n--- 6. 深色 + 浅色两趟，逐屏量对比度（WCAG 1.4.3）---")
        # 浅色那一趟的主体在 contrast.playwright.py（33 条）里；这里**两趟都量**，
        # 因为那道门只扫 5 屏，而 0.6.0 新加的 11 张子屏它一张都没扫过。
        for theme in ("light", "dark"):
            page.evaluate("(t) => THEME.set('theme', t)", theme)
            page.wait_for_timeout(320)
            bad_all, mins = [], {}
            for name, js, _h1 in SCENES:
                page.evaluate(js)
                page.wait_for_timeout(220)
                r = page.evaluate(SWEEP)
                mins[name] = r["minR"]
                for x in r["bad"]:
                    bad_all.append(f"[{theme}] {name}: {x['sel']} {x['size']}px {x['ratio']}:1"
                                   f"（要 {x['need']}）「{x['text']}」")
                if name in [row["screen"] for row in rows]:
                    for row in rows:
                        if row["screen"] == name:
                            row.setdefault("min", {})[theme] = r["minR"]
                if r["measured"] < 3:
                    bad_all.append(f"[{theme}] {name}: 只量到 {r['measured']} 处带字元素（等于对着空屏自证）")
            if theme == "dark":
                check("深色模式：24 个屏/页签状态的每一处文字都过 AA", bad_all, [])
                worst = min((v, k) for k, v in mins.items() if v)
                print(f"        深色最低的一屏：{worst[1]} {worst[0]}:1")
                dark_mins = mins
            else:
                check("浅色模式：同上（这道门自己也量一遍，不只信 contrast 那道）", bad_all, [])
                light_mins = mins
        for row in rows:
            row["min"] = {"light": light_mins.get(row["screen"]), "dark": dark_mins.get(row["screen"])}
        page.evaluate("() => THEME.set('theme', 'light')")
        page.wait_for_timeout(220)

        # ==================== 7. 触摸目标（2.5.5 / 2.5.8） ====================
        print("\n--- 7. 命中区 ≥44×44（WCAG 2.5.5；.chip 34px 是历史遗留，另立清单）---")
        # .chip 不改（任务书里明说的历史遗留），但**列全**：除了 .chip 还有哪些低于 44。
        # 这一条要的是「还有哪些」——把 .chip 滤掉之后剩下的必须为空。
        # 命中区口径与 e2e 第 41 节同一把尺：表单控件在 <label> 里时整行都算（点哪儿都命中）。
        # 勾框自己那一格另算 2.5.8 的 24px，见下面那条。
        small_bad, small_chip, small_n = [], [], 0
        tiny_box = []
        heat_cells = []
        for name, _js, _h1 in SCENES:
            r = audits[name]
            n_here = 0
            for e in r["list"]:
                # 勾框自己那一格（2.5.8 的 24px）：只算**真的在场上**的那些，
                # 并跳过 .switch（那是自己画的开关，可见的胶囊是 46×28，另有它那一档）。
                if (e["type"] == "checkbox" and e["w"] > 0 and e["h"] > 0
                        and "switch" not in e["cls"].split() and min(e["w"], e["h"]) < 24):
                    tiny_box.append(f"{name}: <input type=checkbox> {e['w']:.0f}×{e['h']:.0f}")
                if e["ad"]:
                    continue                    # 明说「此刻不许用」的那几枚不算（按不动是诚实的）
                # 被一条更小的**不换行容器**裁过的字是真的按不准；但「宽高都是 0」的那几枚
                # 不是触摸目标（它们是 display:none / 被 hidden 收起来的），
                # 而我们的 shown() 用 getClientRects 判可见 —— 0 尺寸的跳过，别拿来充数。
                if e["hw"] <= 0 or e["hh"] <= 0:
                    continue
                if e["hw"] >= 44 and e["hh"] >= 44:
                    continue
                # 热力图格子：文档密度要求（371 格放一张年历）与 24px 目标尺寸天然冲突。
                # WCAG 2.5.8 的 spacing 例外本来就承认这种情形，而笺另外还要满足
                # 「有等价的替代操作」——格子确实是 focusable 的（键盘方向键走、
                # 回车开面板，stats_v06 第 1 节钉着）。所以这里把它们**从缺陷清单里摘出来
                # 单独计数**，不是放水：数量与豁免理由都在报告里，谁想偷偷改大改小，
                # 下面的「热力图格子有替代操作」那条会先炸。
                if e["role"] == "gridcell":
                    heat_cells.append(f"{name}: {e['w']:.0f}×{e['h']:.0f}")
                    continue
                small_n += 1
                n_here += 1
                is_chip = "chip" in e["cls"].split() or e["cls"].startswith("chip ")
                tag = (f"{name}: <{e['tag']}{('#' + e['id']) if e['id'] else '.' + (e['cls'].split(' ')[0] or '?')}>"
                       f" {e['hw']:.0f}×{e['hh']:.0f}「{e['name'][:14]}」")
                (small_chip if is_chip else small_bad).append(tag)
            for row in rows:
                if row["screen"] == name:
                    row["small"] = n_here
        check("低于 44×44 的一共 %d 个（其中 .chip %d 个，明确不改）" % (small_n, len(small_chip)),
              small_n, len(small_chip) + len(small_bad))
        check(f"除 .chip 之外，低于 44×44 的：{len(small_bad)} 个", small_bad, [])
        check("勾框自己那一格不小于 24×24（WCAG 2.5.8；整行点得到不等于那一格够大）", tiny_box, [])

        # 热力图格子：量得到，且必须量得到**替代操作**。
        # 这一条防的不是「格子太小」（那是产品已经接受的取舍：371 格要看一整年），
        # 是「小到按不准、又没有别的路」——WCAG 2.5.8 的 spacing 例外只管间距，
        # 真正让这件事可以被接受的是「键盘也能走到、也能打开」。哪天有人把
        # grid tabindex 拿掉、或者把方向键处理删了，键盘用户就再也打不开任何一天，
        # 而格子**看起来一切正常**。这一条就是那时候炸的。
        print(f"        热力图格子（已按 2.5.8 spacing 例外豁免，共 {len(heat_cells)} 格量到）")
        heat_ok = page.evaluate("""() => {
          const g = document.querySelector('#heatGrid');
          if (!g) return '没有热力图';
          if (!g.hasAttribute('tabindex')) return '热力图本身不能聚焦，键盘走不进去';
          const cells = [...g.querySelectorAll('[data-heat]')];
          if (!cells.length) return '热力图没有格子';
          // 方向键 + 回车这条替代路径：模拟按下 → 必须有 sel 落点
          g.focus();
          g.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
          const sel = g.querySelector('[data-heat].sel');
          if (!sel) return '方向键按下去没有选中任何一格（替代操作不存在）';
          return 'ok';
        }""")
        check("热力图有等价的键盘操作（2.5.8：格子小可以，但必须走得到、开得了）", heat_ok, "ok")
        if small_chip:
            print(f"        .chip 那 {len(small_chip)} 个（历史遗留，本轮不动）：")
            for s in small_chip[:24]:
                print("          " + s)

        # ==================== 7.4 焦点不被固定底栏遮住（2.4.11） ====================
        # 底栏是 fixed 的，压在页面下方 96px。`#app` 的 padding-bottom 只保证
        # 「滚到最底时最后一行不被盖住」，管不了**滚动到某个元素**这件事：
        # 键盘 Tab 或 scrollIntoView 把焦点带到下面时，浏览器按「贴视口底边」算，
        # 而视口底边正是底栏所在的地方——焦点落进底栏底下，用户看得见底栏、
        # 看不见自己站在哪儿。实测 237 次 Tab 里 17 次落进去。
        # 修法是 html { scroll-padding-bottom }（W3C 给这件事列的 C43）。
        # 这一条量两件事：那个值真的算出来了（不是被 var() 解析成 0），
        # 以及在一个长屏上，屏幕内的可点元素滚进视野之后没有一个是压在底栏下的。
        print("\n--- 7.4 焦点不被固定底栏遮住（WCAG 2.4.11）---")
        sp = page.evaluate("""() => {
          const v = getComputedStyle(document.documentElement).scrollPaddingBottom;
          return { raw: v, px: parseFloat(v) || 0 };
        }""")
        check("html 有 scroll-padding-bottom，且不是 0（var(--sab) 没把它解析没）",
              sp["px"] >= 90, True)
        # 拿一屏足够长、可点元素又多的：言笺 60 条
        obscured = page.evaluate("""() => {
          state.onboarded = true;
          state.yanCards = Array.from({ length: 60 }, (_, i) => ({
            k: '待办', line: '第七点四节用来把这一屏撑长的第 ' + i + ' 条',
            t: Date.now() - i * 60000, who: '', slot: '', done: false, doneAt: null, archivedAt: null
          }));
          save(state); show('yan');
          const nav = document.querySelector('.nav').getBoundingClientRect();
          const els = [...document.querySelectorAll('.screen.on button, .screen.on input,'
            + ' .screen.on [tabindex="0"], .screen.on a[href]')];
          const bad = [];
          for (const el of els) {
            const r0 = el.getBoundingClientRect();
            if (r0.width <= 0 || r0.height <= 0) continue;
            el.scrollIntoView({ block: 'nearest' });
            const b = el.getBoundingClientRect();
            // 只有「整块都能滚上来、却仍压在底栏下」才算数：
            // 比视口还高的元素滚到顶也还是会被底栏压住，那是版式问题，不是滚动问题。
            if (b.height > 0 && b.height < nav.top && b.bottom > nav.top + 1) {
              bad.push((el.id || el.className || el.tagName).toString().slice(0, 28));
            }
          }
          return bad;
        }""")
        check("长屏上没有一个可点元素滚上来之后压在底栏底下", obscured, [])

        # ==================== 7.5 字号三档（1.4.4 的延伸） ====================
        # 设置里有「小 / 中 / 大」三档，README 把它写成一个功能。但 `--fs-scale` 以前
        # 只作用在 `body` 一条上，而全仓 203 处 font-size 都写死了 px——实测「册」屏
        # 105 个文字元素里只有 4 个会随档位变化。用户把字号调到「大」，绝大多数文字
        # **纹丝不动**：这不是审美问题，是一个明写着却做不到的承诺。
        #
        # 这一条量两件事，缺一不可：
        #   1. 大档真的比小档大（不然就是没生效）；
        #   2. 中档逐像素等于「没有 --fs-scale 时」的值（不然 .98 这种微差会在
        #      不知道什么时候把整套像素断言连带推翻）。
        print("\n--- 7.5 字号三档（小/中/大真的会变，中档逐像素不变）---")
        font_probe = page.evaluate("""() => {
          const measure = () => {
            const els = [...document.querySelectorAll('.screen.on *')].filter(e => {
              const t = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
              return t && e.getClientRects().length;
            });
            return els.map(e => parseFloat(getComputedStyle(e).fontSize));
          };
          const root = document.documentElement;
          const was = root.dataset.font || 'm';
          const out = {};
          for (const scr of ['me', 'today', 'wei']) {
            show(scr);
            root.dataset.font = 'm'; const m = measure();
            root.dataset.font = 's'; const s = measure();
            root.dataset.font = 'l'; const l = measure();
            let changed = 0, grew = 0;
            for (let i = 0; i < m.length; i++) {
              if (Math.abs(s[i] - l[i]) > 0.01) changed++;
              if (l[i] > s[i] + 0.01) grew++;
            }
            out[scr] = { total: m.length, changed, grew };
          }
          // 中档恒等：把 --fs-scale 强制成 1，逐条比
          show('me'); root.dataset.font = 'm';
          const a = measure();
          root.style.setProperty('--fs-scale', '1');
          const b2 = measure();
          root.style.removeProperty('--fs-scale');
          let sameAtM = true;
          for (let i = 0; i < a.length; i++) if (a[i] !== b2[i]) { sameAtM = false; break; }
          root.dataset.font = was;
          out.sameAtM = sameAtM;
          out.mCount = a.length;
          return out;
        }""")
        for scr in ("me", "today", "wei"):
            d = font_probe[scr]
            check("字号三档在「%s」上真的生效（%d 个文字元素里 %d 个会变）"
                  % (scr, d["total"], d["changed"]), d["changed"] == d["total"] and d["total"] > 0, True)
            check("大档确实比小档大（不是只换了 class）", d["grew"] == d["total"], True)
        check("中档逐像素不变（%d 个元素与「没有 --fs-scale」时逐条相同）" % font_probe["mCount"],
              font_probe["sameAtM"], True)

        # ==================== 8. 减少动态（2.3.3） ====================
        print("\n--- 8. :root.no-motion 下动画/过渡时长 ≈0（WCAG 2.3.3）---")
        page.evaluate("() => { state.settings.motion = false; save(state); THEME.apply(); }")
        page.wait_for_timeout(260)
        check("no-motion 真的挂上了（否则下面量的是空气）", page.evaluate(
            "() => document.documentElement.classList.contains('no-motion')"), True)
        motion_bad, motion_n = [], 0
        for name, js, _h1 in SCENES:
            page.evaluate(js)
            page.wait_for_timeout(240)
            r = page.evaluate(MOTION)
            motion_n += r["n"]
            if r["bad"]:
                motion_bad.append(f"{name}: " + ", ".join(f"{x[0]} {x[1]:.3f}s" for x in r["bad"]))
        check(f"量到了 {motion_n} 处带时长的地方（0 处就是没量到）", motion_n >= 30, True)
        check("no-motion 下没有一处时长超过 0.05s", motion_bad, [])
        # 反向自证：把 no-motion 摘掉，必须**量得出**非零时长（否则上面那条是空断言）
        page.evaluate("() => { document.documentElement.classList.remove('no-motion'); show('yi'); }")
        page.wait_for_timeout(120)
        live = page.evaluate(MOTION)
        check("摘掉 no-motion 之后真的量得到非零时长（否则第 8 条是空断言）",
              any(d > 0.05 for _w, d in live["bad"]) or live["n"] > 0, True)
        page.evaluate("() => { state.settings.motion = true; save(state); THEME.apply(); }")
        page.wait_for_timeout(200)

        # ==================== 9. 状态不只靠颜色（1.4.1） ====================
        print("\n--- 9. 每一处「选中」都有 aria 状态，不只有 .on 这个 class（WCAG 1.4.1）---")
        # 判据：凡是 class 里有 .on 的按钮，必须同时带 aria-pressed / aria-selected /
        # aria-checked 三者之一。只有 class 的 = 读屏器与色盲用户都看不出它被选中了。
        state_bad, state_n = [], 0
        # 这一节**自己重新拍一遍**，不复用第 1 节之前那份快照：中间隔了 8 节
        # （主题切过两趟、动效关过一次、Tab 走过 24 圈、按键点过一堆按钮），
        # 上一节就把言笺那枚「按类型」点掉了 —— 拿旧快照去和现在的 DOM 对账，
        # 差出来的那一个不是漏扫，是这八节自己改的状态（实测 17 vs 18）。
        # 所以这里先把种子重铺一遍，再**同一刻**拍快照 + 计数：两边看到的是同一屏。
        page.evaluate(SEED)
        page.wait_for_timeout(200)
        state_audits = {}
        for _n, _js, _h in SCENES:
            page.evaluate(_js)
            page.wait_for_timeout(150)
            state_audits[_n] = page.evaluate(AUDIT)
            for e in state_audits[_n]["list"]:
                if not e["clsOn"]:
                    continue
                state_n += 1
                if not (e["pressed"] or e["selected"] or e["checked"]):
                    state_bad.append(f"{_n}: <{e['tag']}{('#' + e['id']) if e['id'] else '.' + e['cls'].split(' ')[0]}>"
                                     f"「{e['name'][:14]}」只有 class=on，没写 aria-*")
        # 门里的自证阈值原来是 >= 20。事故：全 App 的选中态**一共只有 17 处**
        # （9 屏里的 16 枚 .chip / .mode-card，加提醒那一屏的 1 枚铃铛），
        # 所以那一条从来没有可能通过——它不是在量产品，而是在量一个凭印象写下的数。
        # 现在只留下限（>= 12，证明「没扫瞎」），真正的判据是下面那条「每一处都写了 aria」。
        check(f"量到了 {state_n} 处选中态（< 12 就是没量到）", state_n >= 12, True)
        # 逻辑上的自证：光有总量不够，只在一屏里凑出 17 个也是一种扫瞎。
        spread = [n for n in state_audits if any(e["clsOn"] for e in state_audits[n]["list"])]
        check(f"选中态分布在 {len(spread)} 屏上（< 5 屏就是只扫到了一处）", len(spread) >= 5, True)
        check("每一处选中态都写进了 aria（读屏器与色盲用户读得到）", state_bad, [])
        # 页签用的是 aria-selected 而不是 aria-pressed —— 这两种在 ARIA 里不是同义词
        sel_wrong = page.evaluate("""() => [...document.querySelectorAll('[role=tab]')]
          .filter((b) => b.getAttribute('aria-selected') === null)
          .map((b) => b.textContent.trim().slice(0, 10));""")
        check("每一枚 role=tab 都有 aria-selected（不是只写 aria-pressed）", sel_wrong, [])

        # ==================== 10. 焦点可见（2.4.7） ====================
        print("\n--- 10. 键盘走到每一枚控件都画得出焦点环（WCAG 2.4.7）---")
        # 先进键盘模态：鼠标点过之后 :focus-visible 不匹配，会量成「本来就没描边」。
        page.evaluate("() => show('yi')")
        page.wait_for_timeout(200)
        page.keyboard.press("Tab")
        page.wait_for_timeout(120)
        check("真的进了键盘模态（否则这一节量的是空气）", page.evaluate(
            "() => (document.activeElement || document.body).matches(':focus-visible')"), True)
        ring_bad, ring_n = [], 0
        for name, js, _h1 in SCENES:
            page.evaluate(js)
            page.wait_for_timeout(200)
            page.evaluate("() => { window.scrollTo(0, 0); document.activeElement && document.activeElement.blur(); }")
            nfoc = page.evaluate(COUNT_FOCUS)
            seen = set()
            for _ in range(min(nfoc, 24)):
                page.keyboard.press("Tab")
                r = page.evaluate(RING)
                if r.get("skip"):
                    continue
                # 同一枚控件被连按两次不算第二个落点：<input type="date"> 在 Chromium 里
                # Tab 会先落进整个控件、再落进它内部的日/月/年子格，第二次 activeElement 还是
                # 那个 <input>，但 :focus-visible 不再匹配、描边读成 none。那不是缺焦点环
                # —— 第一趟已经量到 2px 实线了。判据落在「是不是同一枚」上，不靠猜元素类型。
                if r["key"] in seen:
                    continue
                seen.add(r["key"])
                ring_n += 1
                if not r["ok"]:
                    ring_bad.append(f"{name}: {r['who']} outline={r['style']} {r['w']}px")
        check(f"量到了 {ring_n} 个焦点落点（< 100 就是走瞎了）", ring_n >= 100, True)
        check("每一个落点都画得出焦点环", ring_bad, [])

        # ==================== 量化表 ====================
        print("\n--- 每屏量化表 ---")
        print(f"{'屏':14s} {'可交互':>6s} {'缺名字':>6s} {'<44':>5s} {'对比最低(浅)':>12s} {'(深)':>7s}")
        for row in rows:
            miss = len([e for e in audits[row["screen"]]["list"] if not e["name"]])
            print(f"{row['screen']:14s} {row['n']:6d} {miss:6d} {row.get('small', 0):5d}"
                  f" {str(row.get('min', {}).get('light')):>12s} {str(row.get('min', {}).get('dark')):>7s}")
        # 量化表的自证：一张全零的表既可能是「都好」也可能是「什么都没量到」
        check("量化表不是空的：至少 20 屏量到了东西",
              len([r for r in rows if r["n"] > 0]) >= 20, True)

        # ==================== 运行时 ====================
        print("\n--- 运行时错误 ---")
        real = [e for e in errors if "favicon" not in e.lower()]
        check("无 JS 报错", real, [])

        ctx.close()
        browser.close()

    bad = [c for c in checks if not c[0]]
    print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败  （共 {len(checks)} 条）")
    for ok, name, got, want in bad:
        print(f"   ✗ {name}\n      实测 {_short(got)[:600]}\n      期望 {_short(want)[:200]}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
