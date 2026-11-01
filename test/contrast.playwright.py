# 对比度守门：把每一条真正落在纸上的 DOM 文字按 WCAG 1.4.3 算一遍。
#
# 为什么单独一套：连着两轮都栽在同一类问题上——「再想想」的金字 2.26:1、占位符 2.44:1、
# 已完成的待办行 2.66:1。每一条都是「看着挺淡」，但没有一条是被数出来的。
# 靠注释里的"我算过"不算数，这里每次都真算。
#
# 口径：正文/小字 ≥4.5:1；≥24px 或 ≥18.66px 加粗 ≥3:1（WCAG 大字档）。
# 压在照片上的字（瓷砖标签、首屏角标）背景是图不是色，走另一条显式断言：
# 取 CSS 里那层压暗渐变的真实值，垫在最坏情况（纯白衣物）上算。
#
# 运行：python test/contrast.playwright.py   （要本机 Edge，跟 e2e 同一套）
import pathlib
import sys

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()

errors = []
checks = []


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


# 背景是照片、不是颜色的地方，走下面的显式断言。
# .item .tag 与 .compare .tag、.hero-cloth .cap 以前也在这里——那道显式断言拿渐变最暗的
# 一档当文字所在那一档，量出 6.34:1 就收工；按真实像素复量只有 3.18:1（11px 字要 4.5）。
# 现在这三处换成不透明胶囊，底色是常数，交回整片扫描去量。只剩次数徽章还是半透明的，
# 它底下是照片，走下面的两极端显式断言。
ON_PHOTO = ".item .worn"

MK = """() => {
  window.__mk = (color, name) => {
    const c = document.createElement('canvas');
    c.width = 600; c.height = 800;
    const x = c.getContext('2d');
    x.fillStyle = color; x.fillRect(0, 0, 600, 800);
    return new Promise((r) => c.toBlob((bl) => r(new File([bl], name, { type: 'image/jpeg' })), 'image/jpeg'));
  };
  return true;
}"""


def ratio(fg, bg):
    """两个 #rrggbb 的 WCAG 对比度。"""
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    def lum(h):
        h = h.strip().lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    a, b = lum(fg), lum(bg)
    return round((max(a, b) + 0.05) / (min(a, b) + 0.05), 2)

SWEEP = """(skipSel) => {
  const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  const ratio = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  // getComputedStyle 给的是 rgb()/rgba()；rgba 的 a=0 等于没画
  const rgb = (s) => {
    const m = String(s).match(/rgba?\\(([^)]*)\\)/);
    if (!m) return null;
    const p = m[1].split(",").map((x) => parseFloat(x));
    return { c: [p[0], p[1], p[2]], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg) => fg.c.map((v, i) => v * fg.a + bg[i] * (1 - fg.a));

  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest(skipSel)) continue;
    const tag = el.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'CANVAS' || tag === 'TEXTAREA') continue;
    let text = '';
    for (const n of el.childNodes) if (n.nodeType === 3) text += n.nodeValue;
    if (!text.trim()) continue;                       // 只管自己直接持有的文字，避免一层层重算
    if (!el.getClientRects().length) continue;        // 没渲染（隐藏屏、display:none）
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden') continue;
    const fg = rgb(cs.color);
    if (!fg || fg.a === 0) continue;

    // 祖先链上把不透明度和背景一层层合成出来。
    // 纸纹那种 linear-gradient 直接跳过：它就是 --paper 本身，偏差在 0.1% 以内。
    let op = 1, bg = [255, 255, 255], opaque = false;
    for (let p = el; p && !opaque; p = p.parentElement) {
      const pcs = p === el ? cs : getComputedStyle(p);
      op *= parseFloat(pcs.opacity);
      const b = rgb(pcs.backgroundColor);
      if (b && b.a > 0) { bg = over(b, bg); if (b.a >= 1) opaque = true; }
      if (/url\\(/.test(pcs.backgroundImage)) { opaque = false; bg = null; break; }
    }
    if (!bg) continue;                                 // 底下是图片，不算
    const txt = over({ c: fg.c, a: fg.a }, bg);
    const eff = txt.map((v, i) => bg[i] + (v - bg[i]) * op);   // 整组透明度最后压上去
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const need = (size >= 24 || (size >= 18.66 && weight >= 700)) ? 3 : 4.5;
    const r = ratio(eff, bg);
    if (r < need - 0.005) {
      const key = el.tagName + '|' + el.className + '|' + cs.color + '|' + cs.fontSize;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ sel: (el.id ? '#' + el.id : el.tagName.toLowerCase()) +
                      (el.className ? '.' + String(el.className).trim().split(/\\s+/).join('.') : ''),
                 size: +size.toFixed(1), weight, need, ratio: +r.toFixed(2),
                 color: cs.color, text: text.trim().slice(0, 16) });
    }
  }
  return out;
}"""

# 压在照片上的**半透明**底：照片是什么颜色不知道，所以把两个极端（纯黑、纯白）
# 各合成一遍，取差的那个。这比「跳过它」诚实，也比拿渐变最暗一档当文字那一档诚实。
OVER_PHOTO = """(sel) => {
  const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  const parse = (s) => { const m = String(s).match(/rgba?\\(([^)]*)\\)/); return m ? m[1].split(',').map(parseFloat) : null; };
  const ratio = (a, b) => { const la = lum(a), lb = lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); };
  const el = document.querySelector(sel);
  if (!el) return null;
  const cs = getComputedStyle(el);
  const fg = parse(cs.color), bg = parse(cs.backgroundColor);
  if (!fg || !bg) return null;
  const fa = fg.length > 3 ? fg[3] : 1, ba = bg.length > 3 ? bg[3] : 1;
  const one = (extreme) => {
    const real = bg.slice(0, 3).map((v, i) => v * ba + extreme * (1 - ba));      // 半透明底压在照片上
    const txt = fg.slice(0, 3).map((v, i) => v * fa + real[i] * (1 - fa));       // 字再压在这个底上
    return +ratio(txt, real).toFixed(2);
  };
  const onBlack = one(0), onWhite = one(255);
  return { onBlack, onWhite, worst: Math.min(onBlack, onWhite), size: parseFloat(cs.fontSize) };
}"""

PLACEHOLDER = """() => {
  // 以前只量 document.querySelector('input[type=text]') 的那一个——也就是搜到的**第一个**，
  // 而且只在白天量。夜里的占位符于是从来没被数过：它压在 #1b1917 上是 3.38:1，
  // 而占位符在这个 App 里是说明书（「把菜单一行一道贴进来」「怎么称呼」），不是装饰。
  // 现在：把所有可见的带 placeholder 的输入框/textarea 都量一遍，并且按**它自己的**
  // 实际底色算（--cream 卡片底与 --paper 屏底都可能）。
  const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (k) => 0.2126 * f(k[0]) + 0.7152 * f(k[1]) + 0.0722 * f(k[2]);
  const parse = (s) => { const m = String(s).match(/rgba?\\(([^)]*)\\)/); return m ? m[1].split(',').map(parseFloat) : null; };
  const opaqueBg = (el) => {
    // 从元素自己往上找第一个不透明底色；一路透明就落到 body。
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && (c.length < 4 || c[3] >= 0.999)) return c.slice(0, 3);
    }
    const b = parse(getComputedStyle(document.body).backgroundColor);
    return b ? b.slice(0, 3) : [255, 255, 255];
  };
  const out = [];
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if (!el.getClientRects().length) continue;              // 收起来的不管
    if (getComputedStyle(el).visibility === 'hidden') continue;
    const p = getComputedStyle(el, '::placeholder');
    const fg = parse(p.color);
    if (!fg) continue;
    const bg = opaqueBg(el);
    const a = fg.length > 3 ? fg[3] : 1;
    const mix = fg.slice(0, 3).map((v, i) => v * a + bg[i] * (1 - a));
    const la = lum(mix), lb = lum(bg);
    out.push({
      who: (el.id || el.getAttribute('placeholder') || el.tagName).slice(0, 18),
      r: +((Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)).toFixed(2),
    });
  }
  return out;
}"""

def sweep(page):
    """量之前先把动画推到终点。

    为什么必须这一步：`.screen.on` 的入场是一条 opacity 动画，`show()` 之后 300ms
    它可能还差最后一点点没走完。SWEEP 会把祖先链上的 opacity 乘进对比度，
    于是 `0.99989` 这种残值把 4.573:1 的印章红乘成 4.47——**红的是门自己的时序**，
    不是那条颜色。这一条在注入实验里露过头（改的是占位符，却连带炸出一条 seal-mark），
    单独重跑又绿。假红比不量更坏：它会教人去修一条没坏的规则。
    getAnimations().finish() 是确定性的（不是"再等久一点"那种赌）：
    动画一旦 finish，opacity 就停在 1。"""
    page.evaluate("() => document.getAnimations().forEach((a) => { try { a.finish(); } catch (_) {} })")
    return page.evaluate(SWEEP, ON_PHOTO)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.clock.install(time="2026-09-17T10:00:00")
    page.goto(URL)
    page.wait_for_timeout(600)

    print("\n--- 引导页 ---")
    bad = sweep(page)
    check("引导页全部过 AA", bad, [])

    page.click("#go")
    page.wait_for_timeout(400)

    print("\n--- 衣笺（空首屏 + 种子柜）---")
    bad = sweep(page)
    check("衣笺全部过 AA", bad, [])

    print("\n--- 衣笺报告（印章、金句、附注、对比框）---")
    page.evaluate(MK)
    page.evaluate("async () => { const f = await window.__mk('#d8d2c6', 'tee.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport !== null", timeout=15000)
    page.wait_for_timeout(400)
    bad = sweep(page)
    check("衣笺报告全部过 AA", bad, [])

    print("\n--- 味笺排桌 ---")
    page.evaluate("() => show('wei')")
    page.wait_for_timeout(200)
    page.evaluate("""() => {
      document.querySelector('#menu').value = '宫保鸡丁\\n水煮鱼\\n蒜蓉西兰花\\n白切鸡\\n花生豆腐\\n米饭';
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }, { name: '阿姨', chips: [] }];
      save(state); renderWeiPeople();   // 忌口收成一行是新的默认态，展开态也扫一遍
      whoOpen = [2]; renderWeiPeople();
      runWei();
    }""")
    page.wait_for_function("() => document.querySelector('#weiResult').innerHTML.trim().length > 0", timeout=15000)
    page.wait_for_timeout(300)
    bad = sweep(page)
    check("味笺全部过 AA", bad, [])

    print("\n--- 言笺（含一条已完成）---")
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(200)
    page.evaluate("""() => {
      document.querySelector('#yanText').value =
        '明天下午记得把材料发我。\\n药快没了帮我买一盒。\\n那就周五见吧。\\n时间再说。';
      runYan();
    }""")
    page.wait_for_function("() => (state.yanCards || []).length > 0", timeout=15000)
    page.evaluate("""() => {
      const c = state.yanCards.find((x) => x.k === '待办') || state.yanCards[0];
      c.done = true; save(state); renderYan();
    }""")
    page.wait_for_timeout(300)
    check("能勾出已完成行", page.eval_on_selector_all(".check.done", "els => els.length") > 0, True)
    bad = sweep(page)
    check("言笺全部过 AA", bad, [])

    print("\n--- 我的 ---")
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    bad = sweep(page)
    check("我的全部过 AA", bad, [])

    print("\n--- 撤销那条提示（墨底上的淡白字 + 下划线按钮）---")
    page.evaluate("() => toastUndo('已删掉这一条', () => {})")
    page.wait_for_timeout(200)
    check("确实扫到了这枚按钮", page.evaluate("() => document.querySelectorAll('.toast.act button').length"), 1)
    bad = sweep(page)
    check("撤销提示过 AA", bad, [])

    print("\n--- 等远端那层遮罩（只在操作中出现，平时那一遍整片扫根本看不见它）---")
    # 它是 fixed 浮层，第 13 节的 BLEED/TRUNC 都按 .screen 里的元素量，天然跳过；
    # 平时又挂着 display:none，整片扫描也扫不到。「只做过某个动作才露面的面」得自己造出来量，
    # 这一类盲点在第 16 轮的窄屏那一节已经栽过一次。
    page.evaluate("() => { window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9';"
                  " JianAPI.beginTurn(); veil(true, '在认这一笺…'); }")
    page.wait_for_timeout(200)
    check("遮罩确实亮起来了", page.evaluate("() => !!document.querySelector('.veil-card').offsetParent"), True)
    bad = sweep(page)
    check("遮罩上的字全部过 AA", bad, [])
    # 那颗章的两端都取自真实动画的关键帧，再配它**真实的字号与字重**一起判。
    # 只量静止色的话，把 font-weight:700 摘掉照样绿——而那一摘就让它从大字档掉回正文档，
    # 淡到的那一档（--seal-2 对纸 4.20:1）就不够了。
    marks = page.evaluate("""() => {
      const m = document.querySelector('.veil-mark');
      const hex = (s) => { const p = String(s).match(/rgba?\\(([^)]*)\\)/)[1].split(',').map(parseFloat);
        return '#' + p.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join(''); };
      const one = () => { const c = getComputedStyle(m); return {
        color: hex(c.color), size: parseFloat(c.fontSize),
        weight: parseInt(c.fontWeight, 10) || 400 }; };
      const paper = hex(getComputedStyle(document.querySelector('.veil-card')).backgroundColor);
      const out = [one()];
      const a = (m.getAnimations() || [])[0];
      if (a && a.effect) { const d = a.effect.getTiming().duration || 1800;
                           const st = a.playState; a.pause(); a.currentTime = d / 2;
                           out.push(one()); if (st === 'running') a.play(); }
      return { samples: out, paper };
    }""")
    for i, r in enumerate((marks or {}).get("samples") or []):
        big = r["size"] >= 24 or (r["size"] >= 18.66 and r["weight"] >= 700)
        rr = ratio(r["color"], marks["paper"])
        check(f"遮罩那颗章第 {i + 1} 态 {r['size']}px/粗 {r['weight']} → {rr}:1"
              f"（{'大字档' if big else '正文档'}要 ≥{3 if big else 4.5}）",
              rr >= (3 if big else 4.5) - 0.005, True)
    check("真的取到了动画中间那一态（只一个样点就是白测）",
          len((marks or {}).get("samples") or []), 2)
    page.evaluate("() => { veil(false); window.JIAN_CONFIG.endpoint = ''; }")

    print("\n--- 搜索命中的那一小截：只在搜的时候存在，整片扫扫不到它 ---")
    # 上面遮罩那一节立的规矩：「只做过某个动作才露面的面」要自己造出来量。
    # <mark> 是第 49 轮新加的一层底，平时 DOM 里根本没有这个元素，
    # 不加这一节，28 项对比度全绿说的也只是「没有高亮的时候」。
    page.evaluate("""() => {
      window.__c49 = JSON.stringify(state.yanCards);
      state.yanCards = [{ k: '待办', line: '买两节五号电池', when: null, done: false, moved: false, wset: false }];
      save(state); show('yan');
      const s = $('#yanSearch'); s.value = '电池';
      s.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    # 这一页的表是冻住的（上面 clock.install），而搜索现在是「计数立刻、列表晚 140 毫秒」：
    # 拿 300ms 墙钟去等一条只有假表才会走的延时，量到的是「还没画」。拨表才是等的那件事。
    page.clock.run_for(200)
    mk = page.evaluate("""() => {
      const m = document.querySelector('#yanOut mark');
      if (!m) return null;
      const cs = getComputedStyle(m);
      const hex = (s) => { const p = String(s).match(/rgba?\\(([^)]*)\\)/)[1].split(',').map(parseFloat);
        return '#' + p.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join(''); };
      return { color: hex(cs.color), bg: hex(cs.backgroundColor), size: parseFloat(cs.fontSize),
               txt: m.textContent };
    }""")
    check("命中真的标出来了（取不到 mark 这一节就是白测）", mk is not None, True)
    if mk:
        rr = ratio(mk["color"], mk["bg"])
        check(f"高亮上的字「{mk['txt']}」{mk['size']}px 对它的底 {mk['bg']} → {rr}:1（正文档要 ≥4.5）",
              rr >= 4.495, True)
    page.evaluate("""() => {
      const s = $('#yanSearch'); if (s) { s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true })); }
      state.yanCards = JSON.parse(window.__c49); delete window.__c49; save(state); renderYan();
    }""")

    print("\n--- 压在照片上的半透明底：照片颜色不知道，两个极端都量 ---")
    page.evaluate("() => show('yi')")
    page.wait_for_timeout(300)
    for sel, where in ((".item .worn", "柜格次数徽章"),):
        r = page.evaluate(OVER_PHOTO, sel)
        if r is None:
            print(f"        （{where}当前没渲染，跳过）")
            continue
        need = 3 if (r.get("size") or 0) >= 24 else 4.5
        check(f"{where}：最坏照片上 {r.get('worst')}:1（纯黑底 {r.get('onBlack')}、纯白底 {r.get('onWhite')}）",
              (r.get("worst") or 0) >= need, True)
    # 瓷砖标签、报告对比框、首屏角标现在是实底胶囊：底色是常数，交给整片扫描去量。
    # 这三条钉的是「胶囊别被人顺手摘掉」——摘掉之后整片扫描会自己红，这里先点名说清楚。
    pill = page.evaluate("""() => {
      const g = (s) => { const e = document.querySelector(s); if (!e) return null;
        const c = getComputedStyle(e).backgroundColor.match(/rgba?\\(([^)]*)\\)/);
        return c ? c[1].split(',').map(parseFloat) : null; };
      return { tag: g('.item .tag'), compare: g('.compare .tag'), cap: g('.hero-cloth .cap') };
    }""")
    for key, where in (("tag", "柜中瓷砖标签"), ("compare", "报告对比框标签"), ("cap", "首屏角标")):
        c = (pill or {}).get(key)
        ok = bool(c) and (len(c) < 4 or c[3] >= 1)
        check(f"{where}有自己的不透明底（不是靠照片上的渐变）", ok, True)

    print("\n--- 长图：墨色必须还是这套 token ---")
    # card.js 已经不再自己抄一份十六进制，全从 CSS 变量里取。
    # 这条断言盯的是「有人图省事在 card.js 里硬写回一个色」——那样导出图和 App 就不是一张纸了。
    pal = page.evaluate("""() => {
      const g = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
      return { ink: CARD.INK, cream: CARD.CREAM, soft: CARD.SOFT, stamps: STAMP_COLOR,
               t: { ink: g('--ink'), cream: g('--cream'), soft: g('--ink-soft'),
                    seal: g('--seal'), seal2: g('--seal-2'), ok: g('--ok') } };
    }""")
    check("长图墨色 = --ink", pal["ink"].lower(), pal["t"]["ink"].lower())
    check("长图纸色 = --cream", pal["cream"].lower(), pal["t"]["cream"].lower())
    check("长图淡墨 = --ink-soft", pal["soft"].lower(), pal["t"]["soft"].lower())
    check("三枚印章色 = 三个 token",
          [pal["stamps"]["先别"].lower(), pal["stamps"]["再想想"].lower(), pal["stamps"]["宜入"].lower()],
          [pal["t"]["seal"].lower(), pal["t"]["seal2"].lower(), pal["t"]["ok"].lower()])
    for name, c in (("淡墨", pal["soft"]), ("先别红", pal["stamps"]["先别"]),
                    ("再想想金", pal["stamps"]["再想想"]), ("宜入绿", pal["stamps"]["宜入"])):
        check(f"长图上「{name}」压纸白 {ratio(c, pal['cream'])}:1", ratio(c, pal["cream"]) >= 4.5, True)

    print("\n--- 占位符（两张纸 × 每一屏）---")
    # 这一节以前只量「搜到的第一个 input」和「白天的纸」，于是一个真缺陷整套门都没看见：
    # 占位符的颜色当时写死成 #7a7062，夜里压在 #1b1917 上只有 3.38:1。
    # 现在把四屏都走一遍、两套主题各量一次，每一条都按输入框**自己的**底色算。
    #
    # 为什么自证前提要按「合计」而不是按每一屏：衣笺默认停在过笺页，它的搜索框在柜子页签下，
    # 所以 yi 这一屏本来就是 0 个。第一版按屏断言 ≥1，当场假红两条。
    # 三条能看到占位符的屏是 味（称呼 / 贴菜单）/ 言（贴聊天）/ 册（网关地址）。
    for theme in ("light", "dark"):
        page.evaluate("(t) => { THEME.set('theme', t); }", theme)
        worst, seen = [], 0
        for scr in ("yi", "wei", "yan", "me"):
            page.evaluate("(s) => show(s)", scr)
            page.wait_for_timeout(180)
            page.evaluate("() => document.getAnimations().forEach((a) => { try { a.finish(); } catch (_) {} })")
            rows = page.evaluate(PLACEHOLDER) or []
            seen += len(rows)
            for r in rows:
                if r["r"] < 4.5:
                    worst.append(f"{theme}/{scr}/{r['who']} {r['r']}:1")
        check(f"{theme} 纸上真的量到了占位符（<3 个就是空过一轮）", seen >= 3, True)
        check(f"{theme} 纸上所有占位符都过 AA（<4.5 的逐个列出）", worst, [])
    page.evaluate("() => THEME.set('theme', 'auto')")

    print("\n--- 运行时错误 ---")
    real = [e for e in errors if "favicon" not in e.lower()]
    check("无 JS 报错", real, [])

    print("\n--- 挡着的按钮：灰的必须是壳，不是字（第 57 轮）---")
    # 上面那一节量报告页时是走真 过笺 进去的，三枚按钮全都「可用」，
    # 所以本轮新加的 `.btn[aria-disabled="true"]` 那三档灰**从来没被任何一道门量过**——
    # 我引的 4.61/5.09/9.73:1 只是自己算的数。这一节把它变成实测。
    # 用「旧版那张没有 .new 的报告」这个真能出现的状态（导入的备份就是这形状）：
    # 复制那枚不挡（旧报告也有字可复制），存图与记柜挡着——两副颜色一趟全量到。
    page.evaluate("""() => {
      state.lastReport = { t: Date.now(), stamp: '宜入', quote: '柜子最像的一件：燕麦针织',
                           basis: { name: '燕麦针织', cat: '上衣', wear: '穿过 9 次' }, gap: 12, match: [] };
      save(state); show('yi-report'); paintReport();
    }""")
    page.wait_for_timeout(300)
    nblock = page.evaluate("""() => [...document.querySelectorAll('#yi-report .btn[aria-disabled="true"]')]
      .filter((b) => b.getClientRects().length && b.textContent.trim()).length""")
    check("这一屏确实量到了挡着的按钮（0 枚就是白测）", nblock >= 2, True)
    # 整片扫描只回「不合格的那些」，空表既可能是"全都过"也可能是"什么都没量到"——
    # 所以自己先数一遍这一屏到底有几处带字的元素在场上（第 54 轮同一把尺）。
    seen = page.evaluate("""() => [...document.querySelectorAll('#yi-report *')].filter((el) => {
      let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
      return t.trim() && el.getClientRects().length;
    }).length""")
    check("这一屏确实有字可量（少于 8 处就是对着空表自证）", seen >= 8, True)
    check("挡着的那两枚字仍过 AA（旧口径 opacity .4 只有 2.30:1）",
          sweep(page), [])

    bad = [c for c in checks if not c[0]]
    print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
    for ok, name, got, want in bad:
        print(f"   ✗ {name}  ->  {got}   (期望 {want})")
    ctx.close()

sys.exit(1 if bad else 0)
