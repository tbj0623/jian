# 端到端验证：用本机 Edge 驱动真实 index.html 跑完整流程
# 运行：pip install playwright  然后  python test/e2e.playwright.py
# 不需要下载 Chromium，直接复用系统 Edge（channel="msedge"）
import base64
import json
import pathlib
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
URL = (JIAN / "index.html").as_uri()

MK = """() => {
  window.__mk = (color, name) => {
    const c = document.createElement('canvas');
    c.width = 600; c.height = 800;
    const x = c.getContext('2d');
    x.fillStyle = color; x.fillRect(0, 0, 600, 800);
    x.fillStyle = 'rgba(255,255,255,0.20)'; x.fillRect(0, 470, 600, 330);
    x.fillStyle = 'rgba(0,0,0,0.06)'; x.fillRect(0, 0, 600, 120);
    return new Promise((r) => c.toBlob((bl) => r(new File([bl], name, { type: 'image/jpeg' })), 'image/jpeg'));
  };
  window.__dl = null;
  const orig = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.download) { window.__dl = this.href; return; }
    return orig.call(this);
  };
  HTMLAnchorElement.prototype.__origClick = orig;
  return true;
}"""

errors = []
checks = []


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


"""0.6.0 起，衣笺和味笺都从「一屏」拆成了「四个页签、同一屏」。

衣笺：#yiPanePass 过笺 / #yiPaneCloset 柜子 / #yiPaneOutfit 搭配 / #yiPaneWish 愿望，
默认停在 pass，其余三个带 hidden。味笺：#weiPanePlan 排桌 / #weiPaneCook 做菜 /
#weiPaneMarket 买菜 / #weiPaneWeek 这周，默认停在 plan。

为什么不切页签就会超时（这是本文件里九成改动的唯一原因）：
`show('yi')` 只切**屏**，不切页签——它把 #yi 摆到 `.screen.on`，而 #closet / #clothSearch
还锁在 `hidden` 的 #yiPaneCloset 里。Playwright 的 actionability 判断对隐藏元素不点击，
于是 `page.click("[data-closet='idle']")` 会白等 30 秒再抛 TimeoutError；报错原文是
「locator resolved to <button …> - element is not visible」，那句 `element is not visible`
就是「测试还停在 0.5.x 的单页假设上」的证据，不是产品坏了。

用 `page.evaluate` 调产品自己的 setYiTab/setWeiTab（而不是 `page.click('#yiTabs …')`）：
这两个函数本来就要渲染对应页签（renderCloset / renderCook / renderWeiWeek…），点页签
按钮走的是同一个入口；用 evaluate 是因为点页签在「页签被别的屏盖住」的中间态里也会超时，
而这几节里有好几处正处在那种中间态里。
"""
YI_TAB = {"pass": "yiPanePass", "closet": "yiPaneCloset", "outfit": "yiPaneOutfit", "wish": "yiPaneWish"}
WEI_TAB = {"plan": "weiPanePlan", "cook": "weiPaneCook", "market": "weiPaneMarket", "week": "weiPaneWeek"}


def yi_tab(page, tab="closet"):
    """进衣笺并切到某个页签。0.6.0 起四个页签只有一个可见，
    不切的话对 #closet / #clothSearch 的每一次点击都会因为「元素不可见」而超时——
    那不是产品坏了，是**测试还停在 0.5.x 的单页假设**上。"""
    page.evaluate("(t) => { show('yi'); setYiTab(t); }", tab)
    page.wait_for_timeout(150)


def wei_tab(page, tab="plan"):
    """进味笺并切到某个页签。同理：`show('wei')` 之后屏上只有排桌，
    对 #cookList / #weekGrid 的任何读写都会读到 hidden 子树里那个「看不见但有」的节点。"""
    page.evaluate("(t) => { show('wei'); setWeiTab(t); }", tab)
    page.wait_for_timeout(150)


def wait_ok(cond, ms, note, on=None):
    """等一个条件；等不到就报一条**点名**的 FAIL，而不是把 Python 异常抛出去。
    抛出去守门自检也算「抓到」，但它只能说「e2e 崩了」——看不出是哪条行为坏了。
    `on`：另开的页面（窄屏那一节有自己的 context），不传就用主页面。"""
    try:
        (on if on is not None else page).wait_for_function(cond, timeout=ms)
        return True
    except Exception:
        check(f"等不到：{note}", False, True)
        return False


def toast_text():
    """提示是要*读*的，不是要*等*的：`inner_text('.toast')` 在没有提示时会傻等 30 秒再抛，
    于是「它压根没说」这一种最该被抓到的情况，报出来的是「e2e 崩了」。"""
    return page.evaluate("() => { const t = document.querySelector('.toast'); return t ? t.textContent : '（没有提示）'; }")


def press(p, sel):
    """按一枚**被挡着**的控件（只标了 `aria-disabled`，不是真 disabled）。
    Playwright 的 actionability 判断把 `aria-disabled` 也算成 "not enabled"，于是
    `page.click()` 会白等 30 秒再抛 TimeoutError —— 而浏览器自己、读屏器、键盘 Enter
    都照样能把这一下送进去（这正是第 57 轮换轨要的效果：挡着但不藏起来）。
    所以「挡着的钮按下去要吐一句原因」这类断言必须走这条路按，不能用 page.click。"""
    p.eval_on_selector(sel, "el => el.click()")


def wait_toast(sub, ms=8000, why=None):
    """等一句**带特定字样**的提示出来再读。固定 sleep 有两个方向的坏：
    等短了读不到（假红，还会把别的注入「顶」成 ok），或者断言的是「没变化」
    ——那种情况下等不到反而是假绿。所以凡是靠提示定胜负的，先等到它。"""
    return wait_ok("() => { const t = document.querySelector('.toast');"
                   " return !!t && t.textContent.indexOf(" + json.dumps(sub, ensure_ascii=False) + ") >= 0; }",
                   ms, why or ("提示里出现「" + sub + "」"))


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 430, "height": 940}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

    # 时钟钉在周四：言笺样例的「这周四/周四前」要落进「今天」分组，不钉则整套用例只有周四/周五能通过
    page.clock.install(time="2026-09-17T10:00:00")

    page.goto(URL)
    page.wait_for_timeout(600)
    # 首屏那一跳：0.6.0 把衣笺拆成四个页签（过笺/柜子/搭配/愿望），默认停在**过笺**，
    # 而这一份 e2e 是 0.5.x 时代写的，它假设 show('yi') 之后 #closet 就在屏上。
    # 现在不在——于是所有对 [data-closet] / #clothSearch / #closet .item 的操作
    # 都会因为「元素不可见」而 30 秒超时（实测第一处红在 4b 节）。
    # 那不是产品坏了，是**测试还停在单页假设**上。默认落到「柜子」页签，
    # 后面每一节若需要别的页签（过笺 / 搭配 / 愿望）再各自显式切。
    page.evaluate("() => { setYiTab('closet'); }")
    page.wait_for_timeout(150)
    # 拆成多个 <script> 之后，跨文件的加载顺序是契约：state.js 在 parse 期就调 normalizeState，
    # 里面用到 cssColor。这类错只会在运行时炸，node --check 看不出来——所以一开页就先查一遍。
    check("加载期无 JS 报错", [e for e in errors if "pageerror" in e], [])
    check("关键全局都在", page.evaluate(
        "() => [state, boot, runYi, runWei, runYan, renderMe, saveCard, paintHero, show, toast]"
        ".every(x => typeof x === 'function' || (x && typeof x === 'object'))"), True)

    print("\n--- 1. 引导页 ---")
    check("引导页可见", page.is_visible("#onboard"))
    check("导航栏隐藏", not page.is_visible("#nav"))
    page.click("#go")
    page.wait_for_timeout(400)
    check("进入后停在默认首页", page.evaluate("() => document.querySelector('.screen.on').id"), "yi")
    check("底栏出现", page.is_visible("#nav"))

    page.evaluate(MK)

    print("\n--- 2. 衣笺过笺 ---")
    # 这一节问的全是「过笺」那一页：#heroCloth / #heroName / #heroInner 都在 #yiPanePass 里。
    # 0.6.0 之后只切屏不切页签的话，默认虽然也停在 pass，但只要前面任何一节把页签留在
    # 柜子/搭配/愿望上，这里量到的就是 hidden 子树里那个「看不见但有」的节点。
    yi_tab(page, "pass")
    page.evaluate("() => { state.yiCat = '上衣'; save(state); renderCats(); }")
    page.wait_for_timeout(250)
    page.screenshot(path=str(OUT / "page-yi.png"), full_page=True)
    # 首屏那块大纸是「要过笺的那件」的槽位：没选图时是未蘸墨的印 + 邀请，不是柜里第一件
    check("首屏是按钮（键盘可达）", page.evaluate("() => document.querySelector('#heroCloth').tagName"), "BUTTON")
    check("未选图时处于 asking 态", page.evaluate("() => document.querySelector('#heroCloth').classList.contains('asking')"), True)
    check("未选图时提示可见", page.is_visible("#heroCloth .ask"))
    check("未选图时槽位是空的", page.evaluate("() => document.querySelector('#heroInner').innerHTML"), "")
    check("首屏带 aria-label", bool(page.get_attribute("#heroCloth", "aria-label")))
    page.evaluate("async () => { const f = await window.__mk('#d8d2c6', 'tee.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport !== null", timeout=15000)
    r = page.evaluate("() => state.lastReport")
    check("印章", r["stamp"], "先别")
    check("命中最像的柜中件", r["basis"]["name"] if r.get("basis") else None, "燕麦针织")
    check("色差为数字", isinstance(r.get("gap"), int))
    print("        金句：" + r["quote"])
    # 选过图之后提示必须让位——曾经「点这张纸，放照片」压在照片上
    # 换回 pass 页签再量：#heroCloth 是过笺那一页的槽位，藏在别的页签里时
    # `is_visible` 会一律回答 False，下面两条「提示不再压在照片上」就成了假绿。
    yi_tab(page, "pass")
    page.wait_for_timeout(300)
    check("选过图后 asking 态解除", page.evaluate("() => document.querySelector('#heroCloth').classList.contains('asking')"), False)
    check("选过图后提示不再压在照片上", page.is_visible("#heroCloth .ask"), False)
    check("选过图后槽位有内容", bool(page.evaluate("() => document.querySelector('#heroInner').innerHTML")))
    check("首屏显示的是刚挑的那件", page.inner_text("#heroName").split("换一张")[0].strip(), "想买的这件")
    check("占住的槽位标了「换一张」", page.is_visible("#heroName .swap"))
    check("没选图时不给「换一张」", page.evaluate(
        "() => { const keep = state.lastNew; state.lastNew = null; paintHero(); const s = !!document.querySelector('#heroName .swap'); state.lastNew = keep; paintHero(); return s; }"), False)
    # 角标有实底（照片上压字的对比度靠它），可「没选图」时那一格是空的——
    # 空的实底就是首屏左下角一颗悬着的墨点。商店截图里第一眼看到的就是它。
    check("没选图时角标整个不占位（空实底不许露出来）", page.evaluate(
        "() => { const keep = state.lastNew; state.lastNew = null; paintHero();"
        " const d = getComputedStyle(document.querySelector('#heroName')).display;"
        " state.lastNew = keep; paintHero(); return d; }"), "none")
    page.evaluate("() => show('yi-report')")
    page.wait_for_timeout(250)
    check("报告页有收束语", "一张短笺，一次决定" in page.inner_text("#yi-report .signoff"))
    page.wait_for_timeout(200)

    print("\n--- 3. 衣笺报告页 ---")
    page.wait_for_selector("#yi-report", state="attached")
    page.screenshot(path=str(OUT / "page-yi-report.png"), full_page=True)
    check("报告页可见", page.evaluate("() => document.querySelector('.screen.on').id"), "yi-report")
    check("附注已填", bool(page.inner_text("#reportNote").strip()))
    print("        附注：" + page.inner_text("#reportNote"))
    # 薄柜子的判定几乎不会错，但也几乎没用——判定要自己说出来，界面、长图、复制同一口径
    check("六件的种子柜不说自己薄", "还薄" in page.inner_text("#reportNote"), False)
    thin_note = page.evaluate("""() => {
      const keep = state.wardrobe;
      state.wardrobe = keep.slice(0, 3);
      state.lastReport = Object.assign({}, state.lastReport, Engine.yi(state.lastReport.new, state.wardrobe));
      paintReport();
      const t = document.querySelector('#reportNote').textContent;
      state.wardrobe = keep;
      state.lastReport = Object.assign({}, state.lastReport, Engine.yi(state.lastReport.new, keep));
      paintReport();
      return t;
    }""")
    check("三件的柜子会在附注里说薄", "这个判定还薄" in thin_note, True)
    check("薄到什么程度带着件数", "柜里只有 3 件" in thin_note, True)
    check("判定自己带着厚度这个属性", page.evaluate("() => typeof Engine.yi(state.lastReport.new, []).thin"), "boolean")
    # 屏幕上说了、发出去的那份没说，等于没说：三处共用 card.js 里的 thinNote
    check("复制出去的话也带着这句薄", page.evaluate("""() => {
      const keep = state.wardrobe;
      const rep = Object.assign({}, state.lastReport, Engine.yi(state.lastReport.new, keep.slice(0, 3)));
      const t = reportText(rep);
      return /还薄/.test(t) && /柜里只有 3 件/.test(t);
    }"""), True)
    check("六件的柜子复制出去时不说薄", page.evaluate(
        "() => !/还薄/.test(reportText(state.lastReport))"), True)

    print("\n--- 4. 报告长图 ---")
    page.evaluate("() => saveCard()")
    page.wait_for_function("() => window.__dl !== null", timeout=20000)
    png = page.evaluate("""async () => {
      const blob = await (await fetch(window.__dl)).blob();
      return await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(blob); });
    }""")
    raw = base64.b64decode(png.split(",", 1)[1])
    (OUT / "card-yi-1080x1920.png").write_bytes(raw)
    # 读回尺寸
    size = page.evaluate("""async () => {
      const blob = await (await fetch(window.__dl)).blob();
      const bmp = await createImageBitmap(blob);
      return [bmp.width, bmp.height];
    }""")
    check("长图尺寸", f"{size[0]}x{size[1]}", "1080x1920")
    check("长图体积合理(>60KB)", len(raw) > 60000)
    print(f"        已写出 card-yi-1080x1920.png  {len(raw)//1024} KB")

    print("\n--- 4c. 杂志版长图 ---")
    page.evaluate("() => document.querySelector('#switchStyle').click()")
    page.wait_for_timeout(400)
    check("版式按钮切到杂志", page.inner_text("#switchStyle"), "版式 · 杂志")
    check("版式记进 state", page.evaluate("() => state.reportStyle"), "mag")
    page.evaluate("() => { window.__dl = null; saveCard(); }")
    page.wait_for_function("() => window.__dl !== null", timeout=20000)
    png2 = page.evaluate("""async () => {
      const blob = await (await fetch(window.__dl)).blob();
      return await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(blob); });
    }""")
    raw2 = base64.b64decode(png2.split(",", 1)[1])
    (OUT / "card-yi-mag-1080x1920.png").write_bytes(raw2)
    size2 = page.evaluate("""async () => {
      const blob = await (await fetch(window.__dl)).blob();
      const bmp = await createImageBitmap(blob);
      return [bmp.width, bmp.height];
    }""")
    check("杂志版尺寸", f"{size2[0]}x{size2[1]}", "1080x1920")
    check("杂志版与卡片版是两张不同的图", len(raw2) != len(raw))
    print(f"        卡片版 {len(raw)//1024} KB / 杂志版 {len(raw2)//1024} KB")
    page.evaluate("() => document.querySelector('#switchStyle').click()")
    page.wait_for_timeout(250)
    check("切回卡片版", page.evaluate("() => state.reportStyle"), "card")

    print("\n--- 4d. 示例提示、能配、复制 ---")
    # #closetNote 在柜子页签里（过笺那一页另有一份同名的摘要，读的不是这个节点）。
    # 不切页签的话这一条量的是 hidden 子树——`inner_text` 照样有字，红绿全看运气。
    yi_tab(page, "closet")
    page.evaluate("() => { state.clothSel = null; save(state); renderCloset(); }")
    page.wait_for_timeout(300)
    note_txt = page.inner_text("#closetNote")
    check("首次打开提示这是示例柜子", "示例柜子" in note_txt)
    print("        " + note_txt)

    page.evaluate("() => { paintReport(); show('yi-report'); }")
    page.wait_for_timeout(300)
    match_txt = page.inner_text("#reportMatch")
    check("报告页列出了能配的", "也能配柜里的" in match_txt)
    print("        " + match_txt)

    page.click("#copyReport")
    page.wait_for_timeout(500)
    toast_txt = page.evaluate("() => { const t = document.querySelector('.toast'); return t ? t.textContent : ''; }")
    check("复制文案有反馈", "复制" in toast_txt)
    print("        toast：" + toast_txt)

    print("\n--- 4b. 柜子：穿着记忆 ---")
    # 这一整节量的是柜子：#closet 的瓷砖、[data-closet='idle'] 这排筛、"#wearIt" 操作条。
    # 0.6.0 把柜子挪进了 #yiPaneCloset（默认 hidden），所以 show('yi') 之后
    # `page.click("[data-closet='idle']")` 会报 "element is not visible" 白等 30 秒。
    yi_tab(page, "closet")
    page.evaluate("() => { state.clothSel = null; state.closetSort = 'freq'; save(state); renderCloset(); }")
    page.wait_for_timeout(300)
    check("每件都有穿着角标", page.eval_on_selector_all("#closet .worn", "els => els.length"), 6)
    print("        摘要：" + page.inner_text("#closetNote"))
    check("摘要提到件数", "件" in page.inner_text("#closetNote"))

    freq_first = page.eval_on_selector("#closet .item[data-id] .tag", "el => el.textContent")
    check("「常穿」排第一 = 白鞋(15次)", freq_first, "白鞋")
    page.click("[data-closet='idle']")
    page.wait_for_timeout(300)
    idle_first = page.eval_on_selector("#closet .item[data-id] .tag", "el => el.textContent")
    check("「久未穿」排第一 = 驼大衣", idle_first, "驼大衣")
    print(f"        常穿第一：{freq_first} / 久未穿第一：{idle_first}")

    page.click("#closet .item[data-id]")
    page.wait_for_timeout(250)
    check("点一件后出现操作条", page.is_visible("#wearIt"))
    sel = page.evaluate("() => state.clothSel")
    before = page.evaluate("(id) => state.wardrobe.find(w => w.id === id).worn", sel)
    page.click("#wearIt")
    page.wait_for_timeout(300)
    after = page.evaluate("(id) => state.wardrobe.find(w => w.id === id).worn", sel)
    check("「今天穿了」计数 +1", after - before, 1)
    check("记录后收起了操作条内容", page.evaluate("() => document.querySelector('#clothActions .action-head') !== null"), True)
    page.screenshot(path=str(OUT / "page-yi-closet.png"), full_page=True)

    page.evaluate("() => { state.clothSel = null; state.closetSort = 'idle'; save(state); renderCloset(); }")
    page.wait_for_timeout(300)
    flags = page.evaluate("""() => {
      const out = {};
      document.querySelectorAll('#closet .item[data-id]').forEach((el) => {
        const name = el.querySelector('.tag').textContent;
        const w = el.querySelector('.worn');
        out[name] = w ? (w.classList.contains('idle') ? 'idle' : 'fresh') : 'none';
      });
      return out;
    }""")
    check("奶油半裙(96天) 标记久未穿", flags.get("奶油半裙"), "idle")
    check("驼大衣(刚记录) 不是久未穿", flags.get("驼大衣"), "fresh")
    check("白鞋(今天) 标记常穿", flags.get("白鞋"), "fresh")
    check("深蓝阔腿(1天前) 标记常穿", flags.get("深蓝阔腿"), "fresh")

    page.evaluate("() => { state.wardrobe = []; save(state); renderCloset(); }")
    page.wait_for_timeout(250)
    check("空柜有空状态", page.is_visible("#closet .empty"))
    page.evaluate("() => { state.wardrobe = seedWardrobe(); save(state); renderCloset(); }")
    page.wait_for_timeout(200)

    print("\n--- 4b. 柜子按季节筛 ---")
    # 紧接着上一节，页签本来就该还在柜子上；显式写一遍是因为 `[data-season="冬"]` 这排
    # chip 与其他几页同名元素不共存——窄跑这一节时上一节不会先跑，页签会停在 pass。
    yi_tab(page, "closet")
    page.evaluate("() => { state.closetSeason = '冬'; save(state); renderCloset(); }")
    page.wait_for_timeout(250)
    winter = page.eval_on_selector_all("#closet .item[data-id] .tag", "els => els.map(e => e.textContent)")
    check("冬筛只剩燕麦针织和驼大衣", sorted(winter), ["燕麦针织", "驼大衣"])
    page.evaluate("() => { state.closetSeason = '夏'; save(state); renderCloset(); }")
    page.wait_for_timeout(250)
    check("夏筛空柜给专属空态", page.inner_text("#closet .empty").strip().startswith("这一季"))
    page.click('[data-season="冬"]')
    page.wait_for_timeout(250)
    check("点冬季 chip 选中态生效", page.eval_on_selector('[data-season="冬"]', "el => el.classList.contains('on')"), True)
    check("chip 点击过滤成功", page.eval_on_selector_all("#closet .item[data-id]", "els => els.length"), 2)
    page.click('[data-season="all"]')
    page.wait_for_timeout(250)
    check("点全部恢复 6 件", page.eval_on_selector_all("#closet .item[data-id]", "els => els.length"), 6)
    page.evaluate("() => { state.closetSeason = 'all'; save(state); renderCloset(); }")

    print("\n--- 4e. 判定抛错时，报告与照片不会错配 ---")
    # runYi 先把新照片放上首屏再去跑判定。以前结论存在 lastReport、照片存在 lastNew，
    # 判定一抛错就成了「新照片 + 老结论」；现在报告自带那张照片，两者不可能各走各的。
    old_color = page.evaluate("() => state.lastReport.new.color")
    pts = page.evaluate("() => state.points")
    page.evaluate("""() => {
      window.__yi = JianAPI.yi;
      JianAPI.yi = async () => { throw new Error('网关炸了'); };
      window.__mk('#3a5f8a', 'blue.jpg').then((f) => runYi(f));
    }""")
    page.wait_for_function(
        "() => [...document.querySelectorAll('.toast')].some(t => t.textContent.includes('笺点已退回'))",
        timeout=15000)
    check("抛错后报告仍是原来那张照片", page.evaluate("() => state.lastReport.new.color"), old_color)
    # 首屏留的是刚挑的那张（可以直接重试），但它没有冒充报告的照片
    check("失败那张仍留在首屏，能直接重试",
          page.evaluate("() => state.lastNew.color !== state.lastReport.new.color"), True)
    check("笺点退回", page.evaluate("() => state.points"), pts)
    page.evaluate("() => { paintReport(); show('yi-report'); }")
    page.wait_for_timeout(250)
    check("报告页对比框第一格就是报告自带的那张",
          page.evaluate("() => { const i = document.querySelector('#reportCompare img'); return !!i && i.src === state.lastReport.new.img; }"),
          True)
    # 长图那条路径单独验：saveCard 传给画布的必须是报告自带的那张，不是首屏新换的
    check("存长图时喂给画布的是报告自带的照片", page.evaluate("""async () => {
      let got = null;
      const real = drawCardStyle;
      window.drawCardStyle = async (r, n) => { got = n; return real(r, n); };
      await saveCard();
      window.drawCardStyle = real;
      return got === state.lastReport.new && got !== state.lastNew;
    }"""), True)
    page.evaluate("() => { JianAPI.yi = window.__yi; }")
    page.wait_for_timeout(250)

    print("\n--- 5. 味笺排桌 ---")
    # 排桌的输入框 #menu 与结果 #weiResult 都在 #weiPanePlan 里；0.6.0 起味笺默认停在
    # plan，但上一节刚切去衣笺、这一节只 show('wei') 的话，#menu 会落在别的页签留下的
    # hidden 状态里（`page.click`/`fill` 超时，`inner_text` 则是读到看不见的旧内容）。
    wei_tab(page, "plan")
    page.wait_for_timeout(200)
    page.evaluate("""() => {
      state.people = [
        { name: '我', chips: ['花生'] },
        { name: '小周', chips: ['辣'] },
        { name: '阿姨', chips: ['海鲜'] },
        { name: '同行', chips: ['香菜'] }
      ];
      save(state); renderWeiPeople();
      document.querySelector('#menu').value = '宫保鸡丁\\n水煮鱼\\n蒜蓉西兰花\\n白切鸡\\n酸菜鱼\\n花生豆腐\\n米饭\\n西红柿蛋汤';
      runWei();
    }""")
    page.wait_for_function("() => document.querySelector('#weiResult').innerHTML.trim().length > 0", timeout=15000)
    page.wait_for_timeout(400)
    check("结果条目数(4雷区+1留意)", page.eval_on_selector_all("#weiResult .todo", "els => els.length"), 5)
    check("有复制按钮", page.is_visible("#copyWei"))
    talk = page.inner_text("#weiResult .quote")
    print("        群话术：" + talk)
    check("结构够了就不硬塞推荐", page.eval_on_selector_all("#weiResult [data-add]", "els => els.length"), 0)

    # 换一份明显缺菜的菜单，看它推不推具体菜
    page.evaluate("() => { document.querySelector('#menu').value = '宫保鸡丁\\n白切鸡'; runWei({ free: true }); }")
    page.wait_for_function("() => document.querySelectorAll('#weiResult [data-add]').length > 0", timeout=10000)
    page.wait_for_timeout(400)
    dish_names = page.eval_on_selector_all("#weiResult [data-add]", "els => els.map(e => e.textContent)")
    check("缺口大时给出具体菜", len(dish_names) > 0)
    print("        推荐：" + "、".join(dish_names))
    check("推荐里没有花生/辣/海鲜",
          len([d for d in dish_names if any(k in d for k in ("花生", "宫保", "辣", "水煮", "虾", "鱼", "蟹", "贝"))]), 0)
    check("推荐里不含桌上已有的菜", len([d for d in dish_names if d in ("宫保鸡丁", "白切鸡")]), 0)
    check("结果里有上菜顺序区块", "上菜顺序" in page.inner_text("#weiResult"))

    menu_before = page.evaluate("() => document.querySelector('#menu').value.split('\\n').filter(Boolean).length")
    pts_before = page.evaluate("() => state.points")
    page.click("#weiResult [data-add]")
    page.wait_for_timeout(800)
    menu_after = page.evaluate("() => document.querySelector('#menu').value.split('\\n').filter(Boolean).length")
    pts_after = page.evaluate("() => state.points")
    check("点一下推荐菜进了菜单", menu_after - menu_before, 1)
    check("同一次排桌内加菜不再扣点", pts_after, pts_before)

    # 散文菜单：一句话里既有菜也有「有人不吃辣」。整句当菜名是笑话，忌口被静默丢掉
    # 是把人吃坏的错——实测旧分词两样都犯：蒜蓉虾躺在「全员安全」里。
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: [] }, { name: '同行', chips: [] }];
      save(state); renderWeiPeople();
      document.querySelector('#menu').value = '周五晚上三个人来吃饭，准备番茄牛腩、清炒时蔬、蒜蓉虾，还有一个凉拌黄瓜。有人不吃辣，另外一个对海鲜有点忌讳。';
      runWei({ free: true });
    }""")
    wait_ok("() => state.lastWei && (state.lastWei.r.notes || []).length > 0", 20000, "散文菜单排完了（notes 有货）")
    page.wait_for_timeout(400)
    dishes = page.eval_on_selector_all("#weiResult .serving .dish", "els => els.map(e => e.textContent)")
    check("四道菜进了上菜顺序，整句话没混进来", "、".join(dishes), "凉拌黄瓜、清炒时蔬、番茄牛腩、蒜蓉虾")
    check("话里的忌口真的算进这一桌", page.evaluate("() => state.lastWei.r.bans.join()"), "辣,海鲜")
    check("忌了海鲜之后蒜蓉虾进雷区", page.evaluate("() => state.lastWei.r.boom.map(x => x.dish).join()"), "蒜蓉虾")
    check("蒜蓉虾不再躺在「按菜名看不出问题」那一层里",
          page.evaluate("() => state.lastWei.r.safe.join()"), "清炒时蔬")
    wei_sheet = page.inner_text("#weiResult")
    check("没当成菜的那几句原样回显", "没当成菜的那几句" in wei_sheet and "有人不吃辣" in wei_sheet, True)
    check("忌口是从哪句话来的，屏上说得出", "这句里写着忌口" in wei_sheet, True)
    check("复制给群里的话不出现两个句号", "。。" in page.inner_text("#weiResult .quote"), False)
    check("排过的桌标的道数就是桌上这几道", page.evaluate("() => countMenu(document.querySelector('#menu').value)"), 4)
    # 「他最爱吃辣」是给这一桌加分，不是划雷区
    check("爱吃辣不算忌辣", page.evaluate(
        "() => Engine.wei('米饭\\n宫保鸡丁\\n他最爱吃辣', [{name:'我',chips:[]}]).bans.join()"), "")
    # 空格与括号：整行被当成一句话时三道菜一道没算，句里的「牛腩」「蒜蓉」反倒被当成忌牛忌蒜
    check("空格分开的三道菜都算进桌", page.evaluate(
        "() => Engine.wei('番茄牛腩 蒜蓉虾 清炒时蔬（有人对虾过敏）', [{name:'我',chips:[]}]).order.length"), 3)
    check("括号里那句只忌海鲜，不忌牛不忌蒜", page.evaluate(
        "() => Engine.wei('番茄牛腩 蒜蓉虾 清炒时蔬（有人对虾过敏）', [{name:'我',chips:[]}]).bans.join()"), "海鲜")

    dup_menu = page.evaluate("() => Engine.wei('水煮鱼\\n清蒸鲈鱼', [{name:'我',chips:[]}]).dupes.length")
    check("重复主料检测可用", dup_menu, 1)
    page.screenshot(path=str(OUT / "page-wei.png"), full_page=True)

    # 菜库的 tags 要一路走到界面上才算数：小笼包 / 干煸四季豆 的名字里不含原料字，
    # 只有 DISHES 这张表知道它含猪肉 / 辣。以前 wei() 只读 HIDDEN 与 CHIP_MAP，
    # 于是忌猪肉的人看到的是「没有硬雷」——而推荐那一栏从来不推小笼包。
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['猪肉', '辣'] }];
      save(state); renderWeiPeople();
      document.querySelector('#menu').value = '小笼包\\n干煸四季豆\\n米饭';
      runWei({ free: true });
    }""")
    page.wait_for_function("() => document.querySelectorAll('#weiResult .todo').length > 0", timeout=10000)
    page.wait_for_timeout(400)
    rows = page.eval_on_selector_all("#weiResult .todo", "els => els.map(e => e.textContent.replace(/\\s+/g, ' ').trim())")
    check("菜库说含猪肉，界面上就得写着猪肉", len([x for x in rows if "小笼包" in x and "猪肉" in x]), 1)
    check("两个成分都按表内序写到行里", len([x for x in rows if "干煸四季豆" in x and "辣 / 猪肉" in x]), 1)
    check("忌猪肉的桌不会说「没有硬雷」", len([x for x in rows if "没有硬雷" in x]), 0)

    # 同一层的另外两条口径也得在界面上看见：忌「清淡」时菜库说辣的照样进雷区
    # （只看菜名的话「手撕包菜」只会落在谨慎层），三杯鸡的米酒对忌酒的人也是雷区。
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['清淡', '酒'] }];
      save(state); renderWeiPeople();
      const el = document.querySelector('#menu');
      el.value = '手撕包菜\\n三杯鸡\\n白米饭';
      runWei({ free: true });
    }""")
    wait_ok("() => state.lastWei && /三杯鸡/.test(state.lastWei.menu)", 20000,
            "排完这一桌，state.lastWei 带着菜单回来")
    page.wait_for_timeout(400)
    rows2 = page.eval_on_selector_all("#weiResult .todo", "els => els.map(e => e.textContent.replace(/\\s+/g, ' ').trim())")
    check("忌清淡：菜库说辣的那道在界面上进了雷区", len([x for x in rows2 if "手撕包菜" in x and "清淡" in x]), 1)
    check("三杯鸡的米酒：忌酒的人在界面上看得见", len([x for x in rows2 if "三杯鸡" in x and "酒" in x]), 1)

    print("\n--- 6. 言笺捞笺 ---")
    page.evaluate("() => { show('yan'); }")
    page.wait_for_timeout(200)
    page.evaluate("""() => {
      document.querySelector('#yanText').value =
        '明天下午记得把材料发我。\\n药快没了帮我买一盒。\\n那就周五见吧。\\n时间再说。\\n快递到了你拿一下。\\n小王让我周四前把报价发过去。';
      runYan();
    }""")
    page.wait_for_function("() => (state.yanCards || []).length > 0", timeout=15000)
    page.wait_for_timeout(400)
    cards = page.evaluate("() => state.yanCards")
    check("捞出条数", len(cards), 6)
    check("带时间标签的条数", len([c for c in cards if c["when"]]), 3)
    for c in cards:
        print(f"        · {c['k']}｜{c['when']['text'] if c['when'] else '—'}｜{c['line']}")
    check("复制的整张笺包含全部分组", page.evaluate("""() => {
      const t = (function () {
        const cards = state.yanCards || [];
        return document.querySelector('#yanOut').innerText;
      })();
      return ['待办','要买','已定','还没说清'].filter(k => t.includes(k)).length;
    }"""), 4)
    check("人名不重复显示", page.evaluate("() => document.querySelector('#yanOut').innerText.includes('发过去 · 小王')"), False)
    check("复制整张笺按钮", page.is_visible("#copyYan"))

    check("言笺默认按类型", page.evaluate("() => state.yanView"), "kind")
    kind_labels = page.eval_on_selector_all("#yanOut .bar p", "els => els.map(e => e.textContent)")
    check("类型视图四个分组都在",
          len([k for k in kind_labels if k in ("待办", "要买", "已定", "还没说清")]), 4)
    print("        类型分组：" + " / ".join([k for k in kind_labels if k in ("待办", "要买", "已定", "还没说清")]))

    page.click("#yanOut [data-yanview='time']")
    page.wait_for_timeout(450)
    check("切到按时间", page.evaluate("() => state.yanView"), "time")
    time_labels = page.eval_on_selector_all("#yanOut .bar p", "els => els.map(e => e.textContent)")
    print("        时间分组：" + " / ".join(time_labels))
    check("出现「今天」分组", "今天" in time_labels)
    check("出现「明天」分组", "明天" in time_labels)
    check("出现「没写时间」分组", "没写时间" in time_labels)
    check("今天排在没写时间之前", time_labels.index("今天") < time_labels.index("没写时间"))
    check("明天排在没写时间之前", time_labels.index("明天") < time_labels.index("没写时间"))
    page.screenshot(path=str(OUT / "page-yan-time.png"), full_page=True)
    page.click("#yanOut [data-yanview='kind']")
    page.wait_for_timeout(300)
    check("切回按类型", page.evaluate("() => state.yanView"), "kind")
    page.evaluate("() => document.querySelector('#copyYan').click()")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "page-yan.png"), full_page=True)

    print("\n--- 6b. 说话人徽章 ---")
    page.evaluate("""() => {
      state.yanCards = normCards(Engine.yan('小红：明天开会。\\n明天：交房租。\\n小王说：把发票发我。\\n小王让我周四前把报价发过去。\\n小李说要去接孩子。\\n记得把材料发我。'));
      state.yanView = 'kind'; save(state); renderYan();
    }""")
    page.wait_for_timeout(300)
    badges = page.eval_on_selector_all("#yanOut .speaker", "els => els.map(e => e.textContent)")
    check("冒号句标出说话人小红", any("小红" in t for t in badges), True)
    check("「某某说」徽章不带说字", all(not t.endswith("说") for t in badges), True)
    check("时间词开头不标徽章（六条里只有四条盖签）", len(badges), 4)
    # 三种写法都得剥：「小王：」「小王说：」「小王让我…」（最后这种第 20 轮漏了，
    # 截图里看到的是「小王小王让我周四前…」——徽章从 who 来，speaker 是空的）
    # 选择器是 .ck-body 而不是 `.check > div`：第 38 轮把整行的 label 缩回「复选框 + 眉料 + 正文」，
    # 正文成了 label 的孩子（动作那几枚按钮挪到 label 外面当兄弟），孩子不再是孩子。
    def body_of(nm):
        return page.evaluate("""(nm) => { const d = [...document.querySelectorAll('#yanOut .check .ck-body')].find(x => {
          const s = x.querySelector('.speaker'); return s && s.textContent === nm; });
          if (!d) return '没找到那张';
          return [...d.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(); }""", nm)
    check("「小王：」那种剥完只剩「开会」", body_of("小红"), "开会")
    check("光杆「小王让我…」也剥（不再出现小王小王）", body_of("小王").startswith("让我"), True)
    check("「小李说要去…」剥掉名字和「说」", body_of("小李"), "要去接孩子")
    # 徽章已经写着名字了，正文再留一遍就是把同一个名字在屏上摆两次。
    # 去前缀只发生在显示这一处：line 与复制整张笺要留着原话。
    check("盖了签的那几张，名字不出现两遍", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .check .ck-body')]"
        ".filter(d => d.querySelector('.speaker')).every(d => { const n = d.querySelector('.speaker').textContent;"
        " return !d.textContent.startsWith(n + n); })"), True)
    check("每一行剥完都不许是空白", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .check .ck-body')].every(d => d.textContent.trim().length > 0)"), True)
    # 兜底那一格：整条正文就是名字本身，剥完会什么都不剩——宁可名字出现两次
    page.evaluate("""() => {
      state.yanCards = state.yanCards.concat([{ k: '待办', line: '小王', when: null, who: null, speaker: '小王', done: false }]);
      save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    check("剥完会空的那条退回原话，不给一行空白", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .check .ck-body')].some(d => d.textContent.trim() === '小王小王')"), True)
    page.evaluate("""() => {
      state.yanCards = normCards(Engine.yan('小红：明天开会。\\n明天：交房租。\\n小王说：把发票发我。\\n小王让我周四前把报价发过去。\\n小李说要去接孩子。\\n记得把材料发我。'));
      save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    check("数据里还是原话（复制整张笺要它）", page.evaluate(
        "() => state.yanCards.some(c => c.line.startsWith('小红：'))"), True)
    check("光杆那种的数据也没被改", page.evaluate(
        "() => state.yanCards.some(c => c.line === '小王让我周四前把报价发过去')"), True)
    check("复制出来的整张笺也带着原话", page.evaluate("() => yanText().includes('小红：明天开会')"), True)
    check("追问引用不带说话人前缀", page.evaluate(
        "() => Engine.yan('小王：下周项目要评审了，材料我周三之前给你。').ask.indexOf('小王：') < 0"), True)
    # 「3 条 · 已勾 0」被右边的签挤到折行时，掉到下一行的应该是签，不是这句话
    check("眉料那句没被折成两行", page.evaluate(
        "() => { const p = document.querySelector('#yanOut .bar p.tiny'); return p.getBoundingClientRect().height < 22; }"), True)
    page.screenshot(path=str(OUT / "page-yan-speaker.png"), full_page=True)

    print("\n--- 6c. 换屏要把焦点交给这一屏（读屏器才念得出它是谁）---")
    for scr in ("wei", "yan", "me"):
        page.evaluate("(id) => show(id)", scr)
        page.wait_for_timeout(150)
        check(f"show('{scr}') 之后焦点落在这一屏里", page.evaluate(
            f"() => (document.activeElement || document.body).closest('#{scr}') !== null"), True)
    # 那个焦点是给读屏器的，不是给眼睛的：描边要按掉。以前 2px 印章红绕着引导页的
    # 「笺。」画出一个框，在没有 h1 的那一屏绕整屏一圈、只在屏幕底边露出一条全宽红线。
    # 但这条断言第一版是**假门**：前面用鼠标点过，:focus-visible 就不匹配了，
    # 于是它量到的是「本来就没描边」，把 CSS 那条规则整个摘掉照旧绿（守门自检当场抓出来）。
    # 所以先进键盘模态，再断言 :focus-visible 确实匹配上了——量不到就说量不到，
    # 不许把「没进入那个状态」当成「通过」。
    page.evaluate("() => show('onboard')")
    page.wait_for_timeout(150)
    page.keyboard.press("Tab")          # 最近一次交互是键盘 → 之后的程序性 focus 才算 focus-visible
    page.wait_for_timeout(120)
    page.evaluate("() => document.querySelector('#onboard h1').focus()")
    page.wait_for_timeout(120)
    check("真的进了键盘模态（否则下面两条量的是空气）", page.evaluate(
        "() => (document.activeElement || document.body).matches(':focus-visible')"), True)
    check("程序性焦点不带印章红描边", page.evaluate("""() => {
      const a = document.activeElement;
      if (!a || a === document.body) return '焦点没落到任何元素上';
      const cs = getComputedStyle(a);
      return cs.outlineStyle === 'none' || parseFloat(cs.outlineWidth) === 0 ? true : cs.outlineWidth + ' ' + cs.outlineColor;
    }"""), True)
    page.evaluate("() => { state.onboarded = true; show('yan'); }")
    page.wait_for_timeout(150)
    check("衣笺报告那一屏（没有 h1）也不画描边", page.evaluate("""() => {
      show('yi');
      const a = document.activeElement;
      const cs = getComputedStyle(a);
      return a.classList.contains('screen') || a.closest('.screen')
        ? (cs.outlineStyle === 'none' || parseFloat(cs.outlineWidth) === 0) : '焦点不在屏内';
    }"""), True)

    print("\n--- 6d. 类别猜错了能挪：不用删，也不用忍 ---")
    pts_before = page.evaluate("() => state.points")
    page.evaluate("""() => {
      state.points = 90;
      state.yanCards = normCards(Engine.yan('记得买一箱牛奶。\\n那就周五见吧。\\n药快没了。\\n下周三之前把方案交了。'));
      state.yanView = 'kind'; state.yanHideDone = false; save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(350)
    def cards_kinds():
        return page.evaluate("() => state.yanCards.map(c => c.k + '｜' + c.line)")
    def n_kind(lst, k):
        return sum(1 for x in lst if x.split("｜")[0] == k)
    before = cards_kinds()
    from_k = before[0].split("｜")[0]
    check("每行一枚「挪」", page.eval_on_selector_all("#yanOut .mover", "els => els.length"), len(before))
    check("平时不摊开选择器", page.eval_on_selector_all("#yanOut .move-chips .chip", "els => els.length"), 0)
    page.click("#yanOut .mover")
    page.wait_for_timeout(300)
    chips = page.eval_on_selector_all("#yanOut .move-chips .chip", "els => els.map(e => e.textContent)")
    to_k = page.evaluate("() => document.querySelector('#yanOut .move-chips .chip').dataset.moveTo")
    check("点一下长出三枚签（不含它自己那一类）", len(chips), 3)
    check("选择器里没有当前类别", any(from_k in c for c in chips), False)
    check("展开时那枚「挪」标成已展开", page.get_attribute("#yanOut .mover", "aria-expanded"), "true")
    check("点「挪」不会顺手把这一条勾上", page.evaluate("() => state.yanCards.some(c => c.done)"), False)
    page.click("#yanOut .move-chips .chip")
    page.wait_for_timeout(350)
    after = cards_kinds()
    check("卡片真的换了类别", after[0].split("｜")[0], to_k)
    check("原话一个字没改", after[0].split("｜")[1], before[0].split("｜")[1])
    check("原来那一类少了一条、新那一类多了一条",
          [n_kind(after, from_k), n_kind(after, to_k)],
          [n_kind(before, from_k) - 1, n_kind(before, to_k) + 1])
    check("挪过的行标成「已挪」", page.inner_text("#yanOut .mover"), "已挪")
    check("挪完选择器收回去", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 0)
    # 行号不变量：挪类别只改 k，不许把 data-yi 的下标挪位（§21 同一条坑）
    check("下标还是按全量排，没跟着类别重排", page.eval_on_selector_all(
        "#yanOut [data-yi]", "els => els.map(e => +e.dataset.yi)"), [0, 1, 2, 3])
    check("撤销提示在眼前", page.is_visible(".toast.act button"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("撤销回到原类别", page.evaluate("() => state.yanCards[0].k"), from_k)
    check("撤销之后「已挪」标记也清掉", page.evaluate("() => !!state.yanCards[0].moved"), False)
    # 挪一次，再贴同一段聊天：被挪过的那条不该按原类别又冒出一张
    page.evaluate("() => { document.querySelector('#yanText').value = '记得买一箱牛奶。\\n那就周五见吧。\\n药快没了。\\n下周三之前把方案交了。'; }")
    page.click("#yanOut .mover")
    page.wait_for_timeout(250)
    page.click("#yanOut .move-chips .chip")
    page.wait_for_timeout(300)
    moved_line = page.evaluate("() => state.yanCards[0].line")
    page.evaluate("() => runYan()")
    wait_ok("() => !document.querySelector('.veil.on')", 20000, "第二次捞笺跑完（遮罩收了）")
    page.wait_for_timeout(500)
    check("挪过的句子不会被按原类别再加一张", page.evaluate(
        "(l) => state.yanCards.filter(c => c.line === l).length", moved_line), 1)
    check("四条还是四条，一条没多", page.evaluate("() => state.yanCards.length"), 4)
    # 展开着的时候删掉别条，下标整体前移——选择器留着就会指到另一条上
    page.evaluate("() => { document.querySelectorAll('#yanOut .mover')[2].click(); }")
    page.wait_for_timeout(250)
    check("第三条的选择器展开了", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 1)
    page.evaluate("() => document.querySelectorAll('#yanOut .drop')[0].click()")
    page.wait_for_timeout(300)
    check("删掉一条之后展开态作废（不然选择器会指到别的条上）",
          page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 0)
    page.evaluate("() => document.querySelector('.toast.act button').click()")
    page.wait_for_timeout(300)
    page.evaluate("(p) => { state.points = p; save(state); }", pts_before)
    page.wait_for_timeout(200)

    print("\n--- 6e. 时间也是猜的：猜错的日期比猜错的类别更看不见 ---")
    yan_keep = page.evaluate("() => JSON.stringify(state.yanCards)")
    page.evaluate("""() => {
      state.yanCards = normCards(Engine.yan('记得买一箱牛奶。\\n下周三之前把方案交了。'));
      state.yanView = 'kind'; state.yanHideDone = false;
      save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(300)
    def wtimer():
        return page.locator("#yanOut .wtimer").first
    check("每行一枚「时间」", page.eval_on_selector_all("#yanOut .wtimer", "els => els.length"), 2)
    check("平时不摊开", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 0)
    check("没改过的行不写「已定时」", wtimer().inner_text(), "时间")
    wtimer().click()
    page.wait_for_timeout(250)
    labels = page.eval_on_selector_all("#yanOut [data-when-to]", "els => els.map(e => e.textContent)")
    check("点一下长出五枚快捷签 + 一枚「清掉」", labels, ["今天", "明天", "后天", "大后天", "下周一", "清掉"])
    check("还给了一个原生日期框", page.eval_on_selector_all("#yanOut input[type=date]", "els => els.length"), 1)
    check("展开时那枚「时间」标成已展开", page.get_attribute("#yanOut .wtimer", "aria-expanded"), "true")
    check("这一条原本是引擎猜的「下周三」", page.evaluate("() => state.yanCards[0].when.text"), "下周三")
    page.locator("#yanOut [data-when-to='后天']").first.click()
    page.wait_for_timeout(300)
    check("点「后天」盖掉了引擎的答案", page.evaluate("() => state.yanCards[0].when.text"), "后天")
    check("算出来就是「此刻 + 2 个日历天」，保留时分秒（与 parseTime 同口径）", page.evaluate("""() => {
      const a = new Date(state.yanCards[0].when.at), b = new Date();
      b.setDate(b.getDate() + 2);
      return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }"""), True)
    check("行上标成「已定时」", wtimer().inner_text(), "已定时")
    check("改完那排签收回去", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 0)
    check("焦点留在这一行的「时间」上（不然键盘用户被甩回页首）",
          page.evaluate("() => document.activeElement.dataset.when"), "0")
    check("整张笺里带着改过的时间", "（后天）" in page.evaluate("() => yanText()"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("撤销把引擎的「下周三」还回来", page.evaluate("() => state.yanCards[0].when.text"), "下周三")
    check("撤销之后标记也退回「时间」", wtimer().inner_text(), "时间")
    # 挑一天：日期框给的是 yyyy-mm-dd，写出来的 text 与引擎的「X月X日」同格式
    wtimer().click()
    page.wait_for_timeout(250)
    page.locator("#yanOut input[type=date]").first.fill("2026-12-03")
    page.wait_for_timeout(300)
    check("挑的一天写成了「12月3日」", page.evaluate("() => state.yanCards[0].when.text"), "12月3日")
    check("at 落在 2026-12-03 那天", page.evaluate("() => { const d = new Date(state.yanCards[0].when.at); return [d.getFullYear(), d.getMonth(), d.getDate()]; }"),
          [2026, 11, 3])
    page.click(".toast.act button")
    page.wait_for_timeout(250)
    # 只填了一半（把框清空）不该顺手把原时间抹掉
    wtimer().click()
    page.wait_for_timeout(250)
    page.evaluate("() => { const el = document.querySelector('#yanOut input[type=date]'); el.value = ''; el.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(250)
    # 读的时候不许直接 `.when.text`：守卫被摘掉那一发（注入）会让 `when` 变成 null，
    # 于是 evaluate 里抛 TypeError，这一格报成「崩在无断言处」而不是红。
    # 崩了也算「拦到」是假象——任何让套件挂起的改动都会白拿一次认证（本项目栽过两次）。
    check("没挑完日期不许把原时间抹掉", page.evaluate(
        "() => (state.yanCards[0].when || {}).text || '（原时间被抹掉了）'"), "下周三")
    # 这一格以前写的是「不该留一条提示」——因为那时候应用**什么都不说**，而 e2e 把它当默认行为钉住了。
    # 第 58 轮把这条静默改成会说话（挡住就要说，同第 57 轮的口径），所以这里真正要钉的是
    # 两件事：**要说清为什么没改**，以及**不许冒出一条「撤销」**（什么都没改，撤销个什么）。
    check("没挑完要说清为什么没改（不是闷着不动）", "日期没填全" in toast_text(), True)
    check("但没挑完不该凭空冒出一条撤销提示", page.evaluate(
        "() => !!document.querySelector('.toast.act button')"), False)
    # 「下周一」按 ISO 走：钉住的时钟是周四，下周一就是 4 天后
    page.evaluate("() => { document.querySelectorAll('#yanOut .wtimer')[1].click(); }")
    page.wait_for_timeout(250)
    page.locator("#yanOut [data-when-to='下周一']").first.click()
    page.wait_for_timeout(300)
    check("「下周一」真的落在周一", page.evaluate("() => new Date(state.yanCards[1].when.at).getDay()"), 1)
    check("周四说的下周一是 4 天后", page.evaluate("() => dayLabel(state.yanCards[1].when.at)"), "4 天后")
    # 清掉：when 与 wset 一起走，不然那一行永远写着「已定时」
    page.evaluate("() => { document.querySelectorAll('#yanOut .wtimer')[1].click(); }")
    page.wait_for_timeout(250)
    page.locator("#yanOut [data-when-to='']").first.click()
    page.wait_for_timeout(300)
    check("「清掉」把时间摘了", page.evaluate("() => state.yanCards[1].when === null"), True)
    check("摘掉之后 wset 也回 false", page.evaluate("() => state.yanCards[1].wset"), False)
    check("摘掉之后那行退回「时间」", page.locator("#yanOut .wtimer").nth(1).inner_text(), "时间")
    page.evaluate("() => { state.yanView = 'time'; renderYan(); }")
    page.wait_for_timeout(250)
    check("按时间视图里它落进「没写时间」那一组", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .bar p.tiny')].map(e => e.textContent).includes('没写时间')"), True)
    page.evaluate("() => { state.yanView = 'kind'; renderYan(); }")
    page.wait_for_timeout(250)
    # 一屏只摊一排签：两排同时摊着，行上的 × 与下标都不知道归谁。
    # 反方向那一条**不能再点一次「挪」**：点一下它就自己收起来了，那时「不清」和「清」
    # 画出来一模一样，注入躲进去看不见——第一版就是这么漏的，靠守门自检抓回来。
    page.locator("#yanOut .wtimer").first.click()
    page.wait_for_timeout(250)
    page.locator("#yanOut .mover").first.click()
    page.wait_for_timeout(250)
    check("开「挪」把「时间」那排收掉了", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 1)
    check("摊着的那排确实是「挪到…」", page.evaluate("() => !!document.querySelector('#yanOut [data-move-to]')"), True)
    page.evaluate("() => document.querySelectorAll('#yanOut .wtimer')[0].click()")
    page.wait_for_timeout(250)
    check("摊着「挪」时点「时间」，也只剩一排", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 1)
    check("留下的是「时间」那一排", page.evaluate(
        "() => [!!document.querySelector('#yanOut [data-when-to]'), !!document.querySelector('#yanOut [data-move-to]')]"), [True, False])
    page.evaluate("() => document.querySelectorAll('#yanOut .wtimer')[1].click()")
    page.wait_for_timeout(250)
    # 展开着删掉别条：下标整体前移，时间那排也必须作废（§6d 同一条坑）
    page.evaluate("() => document.querySelectorAll('#yanOut .drop')[0].click()")
    page.wait_for_timeout(300)
    check("删一条把两排展开态一起作废", page.eval_on_selector_all("#yanOut .move-chips", "els => els.length"), 0)
    page.evaluate("() => document.querySelector('.toast.act button').click()")
    page.wait_for_timeout(250)
    check("点日期框不会顺手勾掉这一条", page.evaluate("() => state.yanCards.every(c => !c.done)"), True)
    print("\n--- 6f. 勾掉的可以只清掉勾掉的（以前只有「清空这张」一起扔）---")
    page.evaluate("""() => {
      state.yanCards = normCards(Engine.yan('记得买一箱牛奶。\\n下周三之前把方案交了。\\n药快没了。\\n那就周五见吧。'));
      state.yanCards.forEach(c => { c.done = false; });
      state.yanView = 'kind'; state.yanHideDone = false; save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(300)
    n_all = page.evaluate("() => state.yanCards.length")
    album_before = page.evaluate("() => state.album.length")
    check("一条都没勾时这枚不出现（不摆一个按了没用的按钮）", page.is_visible("#yanPrune"), False)
    page.evaluate("() => { state.yanCards[0].done = true; state.yanCards[2].done = true; save(state); renderYan(); }")
    page.wait_for_timeout(300)
    check("勾了两条就出现，并写着条数", page.inner_text("#yanPrune"), "清掉勾掉的 2")
    seq_before = page.evaluate("() => state.yanCards.map(c => (c.done ? '×' : '·') + c.line)")
    page.evaluate("() => document.querySelectorAll('#yanOut .mover')[1].click()")
    page.wait_for_timeout(250)
    check("清之前先摊开着一排签", page.evaluate("() => document.querySelectorAll('#yanOut .move-chips').length"), 1)
    page.click("#yanPrune")
    page.wait_for_timeout(350)
    check("只剩没办的两条", page.evaluate("() => state.yanCards.length"), n_all - 2)
    check("留下的两条都没勾", page.evaluate("() => state.yanCards.every(c => !c.done)"), True)
    check("下标整体变了，两排展开态一起作废", page.evaluate("() => document.querySelectorAll('#yanOut .move-chips').length"), 0)
    check("提示说的是「笺册里那张没动」", "笺册里那张没动" in toast_text(), True)
    check("笺册一条没少（清的是当前这张，不是存档）", page.evaluate("() => state.album.length"), album_before)
    # 只看条目那几行：追问那句是「引用」，它提到清掉的句子不算没清干净
    check("复制整张笺的条目里已经没有清掉的那两条", page.evaluate("""(gone) => {
      const items = yanText().split(String.fromCharCode(10)).filter(l => l.startsWith('· '));
      return items.length === 2 && items.every(l => !gone.some(g => l.includes(g)));
    }""", [seq_before[0][1:], seq_before[2][1:]]), True)
    page.click(".toast.act button")
    page.wait_for_timeout(350)
    check("撤销把两条了结的放回原位（顺序与勾掉前一字不差）",
          page.evaluate("() => state.yanCards.map(c => (c.done ? '×' : '·') + c.line)"), seq_before)
    check("撤销之后还是那四条", page.evaluate("() => state.yanCards.length"), n_all)
    page.evaluate("() => { state.yanCards.forEach(c => { c.done = false; }); save(state); renderYan(); }")
    page.wait_for_timeout(200)

    page.evaluate("(k) => { state.yanCards = JSON.parse(k); save(state); renderYan(); }", yan_keep)
    page.wait_for_timeout(200)
    page.evaluate("() => { show('me'); }")
    page.wait_for_timeout(300)
    check("导出按钮", page.is_visible("#exportData"))
    check("导入按钮", page.is_visible("#importData"))
    # 笺册用报告同一副骨架：一枚模块小印 + 眉 + 右对齐日期 + 宋体正文
    check("笺册条目带模块小印", page.evaluate("() => document.querySelectorAll('#album .slip .seal-mark').length"),
          page.evaluate("() => document.querySelectorAll('#album .slip').length"))
    check("笺册日期右对齐成眉", page.evaluate("() => !!document.querySelector('#album .slip .slip-date')"))
    check("结论章不再套引号", page.evaluate(
        "() => [...document.querySelectorAll('#album .slip-stamp')].every(e => !e.textContent.includes('「'))"), True)
    check("结论章走印章红", page.evaluate(
        "() => { const e = document.querySelector('#album .slip-stamp'); return !!e && getComputedStyle(e).color === 'rgb(181, 74, 60)'; }"),
        page.evaluate("() => !!document.querySelector('#album .slip-stamp')"))
    check("笺点显示(24-2-1-1)", page.inner_text("#points"), "20")
    page.screenshot(path=str(OUT / "page-me.png"), full_page=True)

    print("\n--- 8. 模块开关 ---")
    # v0.6.0：底栏那五枚每枚都是「小印 + 标签」两段（`.nav-ico` + 标签），
    # 所以 `textContent` 拼出来是「味味笺」——拿它比「味笺」的断言从此一律假红。
    # 现在读按钮的**无障碍名字**（aria-label，与看得见的标签同一个字），
    # 那也正是读屏器与语音控制认的那一句；这比去点第二个 span 更贴近「用户看到什么」。
    NAVNAMES = "els => els.map(e => e.getAttribute('aria-label') || e.textContent.trim())"
    page.evaluate("() => { document.querySelector('[data-mod=\"wei\"]').click(); }")
    page.wait_for_timeout(300)
    navs = page.eval_on_selector_all("#nav button", NAVNAMES)
    check("关掉味笺后底栏不含味笺", "味笺" not in navs)
    check("默认首页自动改到可用模块", page.evaluate("() => state.home") in ("yi", "yan"))
    page.evaluate("() => { document.querySelector('[data-mod=\"wei\"]').click(); }")
    page.wait_for_timeout(200)
    check("开回味笺", "味笺" in page.eval_on_selector_all("#nav button", NAVNAMES))

    print("\n--- 8b. 测试订阅（折叠着，展开才点得到）---")
    # 这一块以前是四个大按钮顶着「衣笺 19」的价签占满「我的」首屏：演示版根本不扣钱，
    # 点一下还 +16。现在收进折叠，标签说的是它真正做的事——那这条路径就得有测试看着。
    check("订阅块默认收起", page.is_visible('[data-buy="wei"]'), False)
    page.click(".topup summary")
    page.wait_for_timeout(200)
    check("点标题能展开", page.is_visible('[data-buy="wei"]'), True)
    page.evaluate("() => { state.points = 5; state.plan = null; state.modules.wei = false; save(state); renderMe(); paintNav(); }")
    page.click('[data-buy="wei"]')
    page.wait_for_timeout(300)
    check("开味笺：模块打开", page.evaluate("() => state.modules.wei"), True)
    check("开味笺：plan 记成 wei", page.evaluate("() => state.plan"), "wei")
    # 送多少由「这次真的从关到开了几笺」决定。以前是写死的 16：那四枚签买完之后还留在原处，
    # 再点一次又送 16，连点两下就是 32——一个谁都能撞见的印钞机。
    check("开味笺：这次只从关到开了「味」一笺 → 送 8 点（不是写死的 16）",
          page.evaluate("() => state.points"), 13)
    check("开味笺：底栏跟着有味笺",
          "味笺" in page.eval_on_selector_all("#nav button", NAVNAMES))
    check("已订阅的那笺不再扣点",
          page.evaluate("() => { const b = state.points; return [spend(2, 'wei'), state.points === b]; }"), [True, True])
    check("没订阅的那笺照样扣点",
          page.evaluate("() => { const b = state.points; return [spend(2, 'yan'), state.points, b - 2]; }"), [True, 11, 11])
    # 再点同一枚：以前这里会再送 16 点。
    page.click('[data-buy="wei"]')
    page.wait_for_timeout(300)
    re5 = page.evaluate("""() => ({ p: state.points, plan: state.plan,
      said: (document.querySelector('.toast') || {}).textContent || null })""")
    check("再点一次「开味笺」：一个点都不再送（以前连点两下就是 32）",
          [re5["p"], re5["plan"]], [11, "wei"])
    check("再点一次也给一句实话，不是照样报「已开、送 16 点」",
          re5["said"], "这一笺已经开着了，没再送点")
    # 先把三笺都关掉，再点「开全笺」。默认它们是开着的，不关就量不到这一步做了什么——
    # 这条断言第一次就是这样的假绿：注入把 forEach 整行删掉，e2e 照样全绿（守门自检抓的）。
    page.evaluate("""() => {
      state.modules = { yi: false, wei: false, yan: false };
      save(state); renderMe(); paintNav();
    }""")
    page.wait_for_timeout(250)
    # 0.5.x：底栏四枚（衣 / 味 / 言 / 册），三笺关完之后只剩「册」一枚。
    # 0.6.0：底栏五枚（今 / 衣 / 味 / 言 / 册），「今日」与「册」永远在、关不掉——
    # 所以三笺全关之后是**两枚**（今 + 册），而关掉的那三笺各自不摆。
    # 这条断言问的是「关掉的笺不在底栏留洞」，不是「只许剩一枚」；
    # 所以把期望从 [1, "册"] 改成 [2, "册"]，并**加一条**把「今日」也钉住——
    # 放宽成「不数枚数」就等于把这条门删了（多一枚关不掉的「今日」正是本轮的新事实）。
    check("三笺能关到全关（底栏只剩「今日」与「册」）",
          page.evaluate("() => [document.querySelectorAll('#nav button').length,"
                        " document.querySelector('#nav-me').getAttribute('aria-label'),"
                        " [...document.querySelectorAll('#nav button')]"
                        ".map(b => b.getAttribute('aria-label')).join()]"),
          [2, "册", "今日,册"])
    page.click('[data-buy="all"]')
    page.wait_for_timeout(300)
    check("开全笺：三笺都从关到开 → 一笺 8 点、共送 24",
          page.evaluate("() => [state.plan, state.points]"), ["all", 35])
    check("开全笺：钱包显示不限", page.inner_text("#points"), "不限")
    check("开全笺：订阅名跟着变", page.inner_text("#planName"), "全笺")
    # 「已开全笺」这句以前只改订阅名，不动 modules：底栏还是短的，桌面快捷方式点进来
    # 照旧被 openDeep 挡回「这一笺已经关掉了」。名字承诺了开关做不到的事。
    check("开全笺：三笺的开关真的都开了",
          page.evaluate("() => [state.modules.yi, state.modules.wei, state.modules.yan]"),
          [True, True, True])
    check("开全笺：底栏五枚都在", page.evaluate("() => document.querySelectorAll('#nav button').length"), 5)
    # 全笺开着的时候点单笺：屏幕上写的是「开」，把它降成单笺会让另外两笺重新开始扣点，
    # 那是反方向的。所以只补开、不降级。
    page.click('[data-buy="yi"]')
    page.wait_for_timeout(300)
    down = page.evaluate("""() => ({ plan: state.plan, p: state.points,
      mods: [state.modules.yi, state.modules.wei, state.modules.yan],
      said: (document.querySelector('.toast') || {}).textContent || null })""")
    check("全笺开着时点「开衣笺」：订阅没被悄悄降级成单笺",
          [down["plan"], down["mods"]], ["all", [True, True, True]])
    check("全笺开着时点单笺：也不重复送点，并且说的是「全笺不变」",
          [down["p"], down["said"]], [35, "衣笺本来就开着，全笺不变"])
    labels = page.eval_on_selector_all("[data-buy]", "els => els.map(e => e.textContent)")
    rule = page.inner_text(".topup p")
    check("四枚签不再在标签里承诺一个固定数额（送多少由这次开了几笺决定）",
          labels, ["开衣笺", "开味笺", "开言笺", "三笺全开"])
    check("规则那一行说的就是代码做的事：一笺 8 点、已经开着的不重复给",
          ["8 点" in rule, "不重复给" in rule], [True, True])
    page.evaluate("() => { const t = document.querySelector('.toast'); if (t) t.remove(); }")
    page.evaluate("() => openDeep('yan')")
    check("开全笺之后深链到言笺不再被挡", "已经关掉" in toast_text(), False)
    check("而且真的落到了言笺那一屏", page.evaluate("() => !!document.querySelector('#yanOut')"), True)
    page.evaluate("() => { state.plan = null; state.points = 20; save(state); renderMe(); }")

    print("\n--- 10. 老数据迁移 ---")
    page.evaluate("""() => {
      localStorage.setItem('jian.v1', JSON.stringify({
        onboarded: true, modules: { yi: true, wei: true, yan: true }, home: 'yi',
        points: 7, plan: null,
        wardrobe: [{ id: 'x1', name: '旧衣服', cat: '上衣', color: '#888888' }],
        people: [{ name: '我', chips: [] }], album: [], yiCat: '上衣'
      }));
    }""")
    page.reload()
    page.wait_for_timeout(800)
    check("老数据能正常打开", page.evaluate("() => state.points"), 7)
    # 0.5.x 的 SCHEMA 是 2；0.6.0 加了九个集合（wish / recipes / outfits / cook / market /
    # weeks / digest / reminders / log / drafts）与 settings，SCHEMA 升到 3（state.js 顶部）。
    # 这条问的是「一份没有 schema 的老备份会被补上**当前**那个版本」，不是「永远是 2」——
    # 所以期望值跟着产品走，并且**顺手把它钉在 state.js 的那一个常量上**：
    # 以后谁再升 SCHEMA 而忘了这里，这一格会先红一次，逼他确认迁移那段跟上了。
    cur_schema = int(re.search(r"const SCHEMA = (\d+);",
                              (JIAN / "state.js").read_text(encoding="utf-8")).group(1))
    check("补上 schema 版本", page.evaluate("() => state.schema"), cur_schema)
    check("旧衣服补上穿着字段", page.evaluate("() => state.wardrobe[0].worn"), 0)
    check("补上报告版式", page.evaluate("() => state.reportStyle"), "card")
    # reload 之后回到默认的衣笺「过笺」页签，柜子那一格是 hidden 的——不切过去，
    # `is_visible` 一律回答 False，这一条就成了「迁移把柜子弄没了」的假红。
    yi_tab(page, "closet")
    check("迁移后柜子能渲染", page.is_visible("#closet .item[data-id]"))

    print("\n--- 11. 存储占用与空状态 ---")
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    note = page.inner_text("#storageNote")
    check("显示本机占用", "已用" in note)
    print("        " + note)
    page.evaluate("() => { state.yanCards = []; state.yanAsk = ''; save(state); show('yan'); }")
    page.wait_for_timeout(350)
    check("言笺有引导空状态", page.is_visible("#yanOut .empty"))
    page.evaluate("() => { document.querySelector('#weiResult').innerHTML = ''; }")
    # 味笺切回排桌页签：#weiResult 挂在 #weiPanePlan 里，停在别的页签上量到的是
    # 一个 hidden 子树里的空壳（`is_visible` 会说 False，看着像「空状态没画出来」）。
    wei_tab(page, "plan")
    page.wait_for_timeout(350)
    check("味笺有引导空状态", page.is_visible("#weiResult .empty"))
    page.evaluate("() => { show('yan'); document.querySelector('#yanText').value = '今天天气不错'; runYan(); }")
    page.wait_for_timeout(1500)
    check("捞空时给替代提示", page.is_visible("#yanOut .empty"))
    check("捞空不写进笺册", page.evaluate("() => state.album.filter(a => a.type === 'yan').length"), 0)

    print("\n--- 11.4 上限真的动手时，要说它动了手 ---")
    # 两条路径以前都不说：36 件的柜子切掉整件（连穿着记录一起），
    # 2.8MB 的主动裁剪把第 13 件之后的照片清成色块——而屏幕上还写着「已用 56%」。
    keep = page.evaluate("() => JSON.parse(JSON.stringify(state.wardrobe))")
    page.evaluate("() => { state.wardrobe = []; for (let i = 0; i < 40; i++) state.wardrobe.push({ id: 'x' + i, name: '衣' + i, cat: '上衣', color: '#888888', worn: 0, lastWorn: null }); save(state); }")
    page.wait_for_timeout(300)
    check("柜子超上限只留 36 件", page.evaluate("() => state.wardrobe.length"), 36)
    check("整件被丢掉要说丢了几件", "丢掉 4 件" in toast_text(), True)
    page.evaluate("() => { state.wardrobe = []; for (let i = 0; i < 20; i++) state.wardrobe.push({ id: 'y' + i, name: '照片衣' + i, cat: '上衣', color: '#888888', worn: 1, lastWorn: null, img: 'data:image/jpeg;base64,' + 'A'.repeat(160000) }); save(state); }")
    page.wait_for_timeout(400)
    check("吃紧时第 13 件之后的照片被清掉", page.evaluate(
        "() => state.wardrobe.filter(w => w.img).length"), 13)
    big = toast_text()
    check("清掉几件照片要说得出数", "清掉 7 件旧照片" in big, True)
    check("并且说清楚衣服本身还在", "衣服、颜色、记录都还在" in big, True)
    # toast() 只在真被调用时才造元素，1.8 秒自己消失——所以「先清干净再存一次、看有没有冒出来」
    # 是确定的，不靠等多久。
    page.evaluate("() => { document.querySelectorAll('.toast').forEach(t => t.remove()); }")
    page.evaluate("() => { state.wardrobe = []; for (let i = 0; i < 20; i++) state.wardrobe.push({ id: 'z' + i, name: '小衣' + i, cat: '上衣', color: '#888888', worn: 0, lastWorn: null }); save(state); }")
    page.wait_for_timeout(250)
    check("没丢东西的那次保存不许弹「丢东西」", page.evaluate("() => !!document.querySelector('.toast')"), False)
    page.evaluate("(k) => { state.wardrobe = k; save(state); }", keep)
    page.wait_for_timeout(300)
    check("恢复原柜", page.evaluate("() => state.wardrobe.length"), len(keep))

    print("\n--- 11.5 导入备份要先验货再落盘 ---")
    page.evaluate("() => show('me')")
    page.wait_for_timeout(250)
    before_n = page.evaluate("() => state.wardrobe.length")
    before_first = page.evaluate("() => state.wardrobe[0].name")

    dialogs = []
    # 一个页面只挂一个 dialog 处理器：sync API 里挂两个会互相抢，第二个 accept 时直接炸绿线程
    page.on("dialog", lambda d: (dialogs.append(d.type),
                                 d.accept() if d.type == "confirm" else d.dismiss()))

    bad_files = {
        "数组.json": "[1,2]",
        "空对象.json": "{}",
        "缺柜子.json": '{"modules":{"yi":true}}',
        "柜子不是数组.json": '{"modules":{"yi":true},"wardrobe":"没有柜子"}',
        "modules 是数组.json": '{"modules":[],"wardrobe":[]}',
    }
    for fname, payload in bad_files.items():
        fp = OUT / fname
        fp.write_text(payload, encoding="utf-8")
        page.set_input_files("#fileImport", str(fp))
        # 这一格断言的是「什么都没变」——文件还没读完时它照样绿，那是假绿。
        # 所以先等到那句拒绝真的说出来，再去看柜子有没有被动过。
        wait_toast("这不是笺的备份文件", 8000, "假备份「" + fname + "」被挡下时给的提示")
        check(f"假备份「{fname}」被挡下，柜子件数没变", page.evaluate("() => state.wardrobe.length"), before_n)
    check("挡下后原柜子第一件还在", page.evaluate("() => state.wardrobe[0].name"), before_first)
    check("给了提示", "这不是笺的备份文件" in page.inner_text("body"))

    # 真备份 + 恶意色值：导入要成功，但色值进不了 DOM 属性
    evil = '#c8c8c8" onload="alert(1)'
    fp = OUT / "带注入的备份.json"
    fp.write_text(json.dumps({
        "onboarded": True, "home": "yi", "modules": {"yi": True, "wei": True, "yan": True},
        "points": 33, "plan": None, "schema": 2,
        "wardrobe": [{"id": "e1", "name": "注入色", "cat": "上衣", "color": evil, "worn": 1, "lastWorn": None}],
        "people": [{"name": "我", "chips": []}], "album": [], "yanCards": [],
    }, ensure_ascii=False), encoding="utf-8")
    page.set_input_files("#fileImport", str(fp))
    # 导入会 reload 整页。以前这里固定等 1.2 秒——机器一忙就没回来，于是这一格报红，
    # 而守门自检抓任何一条注入时都可能被它抢先「顶」成 ok（假认证，见 NEXT.md 第 31 轮）。
    # 等的是「新页面确实带着这份备份起来了」，不是等多久。
    wait_ok("() => typeof state !== 'undefined' && state.points === 33", 20000, "导入之后页面重开并读回备份")
    check("合法备份导入成功", page.evaluate("() => state.points"), 33)
    wait_ok("() => !!document.querySelector('#closet .item[data-id]')", 8000, "导入的那件渲染出来")
    # 导入会 reload，页签回到默认的「过笺」。断言问的是「那件衣服有没有画出来」，
    # 而瓷砖只长在柜子页签里——不切过去，`is_visible` 量的是 hidden 子树（恒 False）。
    yi_tab(page, "closet")
    check("导入的衣物渲染出来了", page.is_visible("#closet .item[data-id]"))
    sw = page.get_attribute("#closet .swatch", "style") or ""
    check("恶意色值被回落成安全灰", sw, "background:#c8c8c8")

    # 导入的那一刻，防抖写盘可能还排在后面（用户刚在菜单框里打过字）。
    # 那次防抖落盘的是**旧的那份 state**，会把刚导入的备份整个盖掉：
    # 提示说「导入成功」，重启之后却发现什么都没变。importBackup 先 cancelSoon() 就是为了这个。
    page.evaluate("() => { show('wei'); const el = document.querySelector('#menu');"
                  " el.value = el.value + 'X'; el.dispatchEvent(new Event('input')); }")
    pend = page.evaluate("() => savePending()")
    page.set_input_files("#fileImport", str(fp))
    # 合法备份会 reload：等的是「新页面带着这份备份起来了」（points 是导入那份里的 33），
    # 不是等多久——固定 1.5 秒在忙机器上会读在重开之前，那一格假红，
    # 而守门自检会把这条红当成「它抓住了别的注入」。
    wait_ok("() => typeof state !== 'undefined' && state.points === 33", 20000, "带注入的备份导入后页面重开")
    page.wait_for_timeout(400)
    check("导入之前确实有一次防抖写排在后面（否则这条是白测）", pend, True)
    check("打字之后导入仍然作数（防抖没把旧 state 盖回来）", page.evaluate("() => state.points"), 33)
    check("导入的那件衣服也还在柜里", page.evaluate("() => state.wardrobe.map(w => w.name).join()"), "注入色")
    check("没有被注入出 onload 属性", page.evaluate("() => document.querySelectorAll('[onload]').length"), 0)
    check("没有弹出脚本对话框", dialogs, [])

    # 脏数据：导入校验只管 wardrobe 是不是数组，管不到每一项。
    # id 要进 data-id 属性、worn 要进 title 属性，所以每一项都得在 normalizeState 里收干净。
    dirty = OUT / "脏数据备份.json"
    dirty.write_text(json.dumps({
        "onboarded": True, "home": "不存在的一页", "modules": {"yi": True, "wei": True},
        "points": "一大把", "plan": "全笺", "schema": 2,
        "closetSort": "倒着来", "closetSeason": "春天", "yanView": "别的", "reportStyle": "报纸",
        "apiUrl": "javascript:alert(3)",
        "wardrobe": [
            {"id": 'x" onerror="alert(4)', "name": "脏", "cat": "飞船", "color": "红色",
             "worn": "abc", "lastWorn": "昨天", "season": "乱填", "img": "javascript:alert(5)"},
            "根本不是对象",
            None,
        ],
        "people": [{"name": 123, "chips": "辣"}, {"name": "", "chips": ["辣", "不存在忌口"]}],
        "album": "不是数组", "yanCards": None,
    }, ensure_ascii=False), encoding="utf-8")
    page.set_input_files("#fileImport", str(dirty))
    # 同上：等「那份脏备份真的起来了」（第一件就是备份里那件「脏」，被洗完之后还在），
    # 不等固定秒数。别拿「件数 == 1」当锚点——洗掉几条不是这一格要问的事。
    wait_ok("() => typeof state !== 'undefined' && state.wardrobe[0] && state.wardrobe[0].name === '脏'",
            20000, "脏备份导入后页面重开")
    page.wait_for_timeout(400)
    # 同 §11.5 上一处：reload 之后停回过笺页签，柜子瓷砖在 #yiPaneCloset 里。
    yi_tab(page, "closet")
    check("脏备份照样能开，没崩", page.is_visible("#closet .item[data-id]"))
    check("没被注入出事件属性", page.evaluate("() => document.querySelectorAll('[onerror],[onload]').length"), 0)
    check("id 重新生成过", page.evaluate("() => /^w[0-9a-z]+$/.test(state.wardrobe[0].id)"), True)
    check("worn 收成数字", page.evaluate("() => state.wardrobe[0].worn"), 0)
    check("外来品类回落合法值", page.evaluate("() => state.wardrobe[0].cat"), "上衣")
    check("非法 season 交给 seasonOf 推断", page.evaluate("() => !('season' in state.wardrobe[0])"), True)
    check("非法色值回落成灰", page.evaluate("() => state.wardrobe[0].color"), "#c8c8c8")
    check("非法 img 被丢掉", page.evaluate("() => 'img' in state.wardrobe[0]"), False)
    check("柜子还是三件（外来项补默认而不是丢弃）", page.evaluate("() => state.wardrobe.length"), 3)
    check("笺点不是 NaN", page.evaluate("() => Number.isFinite(state.points)"), True)
    check("plan 不在值域内回落 null", page.evaluate("() => state.plan === null"), True)
    check("home 回落合法页", page.evaluate("() => ['yi', 'wei', 'yan'].includes(state.home)"), True)
    check("开关缺失的模块补成关", page.evaluate("() => state.modules.yan"), False)
    check("javascript: 接口地址被清空", page.evaluate("() => state.apiUrl"), "")
    check("chips 必须是数组", page.evaluate("() => Array.isArray(state.people[0].chips)"), True)
    check("值域外的忌口词被滤掉", page.evaluate("() => state.people[1].chips"), ["辣"])
    check("album / yanCards 回落成数组",
          page.evaluate("() => Array.isArray(state.album) && Array.isArray(state.yanCards)"), True)
    check("脏数据也没弹脚本框", dialogs, [])
    # 每一屏都得还能点得动，别让一处脏字段把整个 App 卡死。
    # 0.5.x 是五屏（引导 + 衣/味/言/册），`.screen` 一共 6 个；
    # 0.6.0 加了今日 / 笺谱 / 单品 / 搭配 / 菜谱 / 这周 / 提醒 / 设置 / 章 / 这一年 / 找东西，
    # `.screen` 现在 17 个（index.html 里逐个数出来的）。这条问的是「脏数据没把屏拆掉」，
    # 不是「永远是 6 个」——所以改成先把屏数从 index.html 数出来，再逐屏切一遍；
    # 每一屏都真的 show 一次，比只数个数更咬得住「脏值把某一屏弄崩」。
    n_screens = len(re.findall(r'<section class="screen"', (JIAN / "index.html").read_text(encoding="utf-8")))
    ids = page.evaluate("() => [...document.querySelectorAll('.screen')].map(s => s.id)")
    for screen in ids:
        page.evaluate("(id) => show(id)", screen)
        page.wait_for_timeout(60)
    check("脏数据下每一屏仍可切换（屏数跟着 index.html 走）",
          [len(ids), n_screens, page.evaluate("() => document.querySelector('.screen.on').id")],
          [n_screens, n_screens, ids[-1]])
    (OUT / "脏数据备份.json").unlink(missing_ok=True)

    # ---------- 落盘必须取消排在后面的那次防抖 ----------
    # 「导入备份忘了取消防抖」这一类缺陷在浏览器里是观察不到的：importData 写完立刻
    # location.reload()，那个 600ms 定时器跟着文档一起消失（实测 Location.prototype.reload
    # 不可拦截，插不进这一步）。所以这道门改成钉在它依赖的那个保证上——writeStore／
    # clearStore 落盘前先取消——用不经过 reload 的确定性断言守着。导入、清空、原生备份
    # 回写走的是同一个入口：保证成立，三条路一起成立。
    page.evaluate("() => { show('wei'); const el = document.querySelector('#menu');"
                  " el.value = el.value + '甲'; el.dispatchEvent(new Event('input')); }")
    pend = page.evaluate("() => savePending()")
    check("打字之后确实排着一次防抖（否则下面这条是白测）", pend, True)
    page.evaluate("() => writeStore(JSON.stringify(Object.assign({}, state, { points: 77 })))")
    page.wait_for_timeout(900)   # 没取消的话，那次防抖就在这 900ms 里把旧的那份盖回来
    check("writeStore 落盘之后，排着的防抖不会把旧 state 盖回来",
          page.evaluate("() => JSON.parse(localStorage.getItem('jian.v1')).points"), 77)

    page.evaluate("() => { const el = document.querySelector('#menu');"
                  " el.value = el.value + '乙'; el.dispatchEvent(new Event('input')); }")
    pend = page.evaluate("() => savePending()")
    check("再造一次防抖（清空那条不能是白测）", pend, True)
    page.evaluate("() => clearStore()")
    page.wait_for_timeout(900)
    check("clearStore 之后数据真的没了（按了清空就真没了）",
          page.evaluate("() => localStorage.getItem('jian.v1') || ''"), "")
    page.evaluate("() => save(state)")   # 把这一节的数据还回去，后面的屏要用
    page.wait_for_timeout(120)

    for f in list(bad_files) + ["带注入的备份.json"]:
        (OUT / f).unlink(missing_ok=True)
    page.evaluate("""() => {
      localStorage.setItem('jian.v1', JSON.stringify({
        onboarded: true, modules: { yi: true, wei: true, yan: true }, home: 'yi',
        points: 7, plan: null, schema: 2,
        wardrobe: [{ id: 'x1', name: '旧衣服', cat: '上衣', color: '#888888', worn: 0, lastWorn: null }],
        people: [{ name: '我', chips: [] }], album: [], yanCards: []
      }));
    }""")
    page.reload()
    page.wait_for_timeout(700)

    print("\n--- 11.6 被本机清掉的照片，现在真能补回来（第 21 轮那句话的兑现）---")
    page.evaluate(MK)
    # 补照片的两个入口（#rephotoBtn / #recamBtn）长在柜子的操作条里，操作条在
    # #yiPaneCloset 里。只 show('yi') 的话 #clothActions 是 hidden 的空壳，
    # 下面 `querySelector('#rephotoBtn').click()` 仍然点得动，但「两枚入口都在」
    # 这类可见性断言会假红——它们是量在屏上的东西，就得先把屏摆到那一页。
    yi_tab(page, "closet")
    page.evaluate("() => { state.clothSel = null; renderCloset(); renderClothActions(); }")
    page.wait_for_timeout(250)
    check("没选中任何一件时，操作条是空的", page.evaluate("() => document.querySelector('#clothActions').innerHTML.trim()"), "")
    check("这时候直接补图说的是先点中哪一件", page.evaluate("""() => {
      const f = new File([new Uint8Array([255, 216, 255, 217])], 'x.jpg', { type: 'image/jpeg' });
      rephotoCloth(f); const t = document.querySelector('.toast'); return t ? t.textContent : '（没有提示）';
    }"""), "先点中柜里那一件")
    # 柜里再多一件，并且**选中的是第二件**：补照片要是找错了目标（比如照搬入柜
    # 那样往 wardrobe[0] 上写），下面那两条「另一件没被动过」就会红。
    page.evaluate("""() => {
      state.wardrobe.push({ id: 'x2', name: '第二件', cat: '裤装', color: '#123456',
                            worn: 3, lastWorn: Date.now() - 86400000 });
      state.clothSel = 'x2'; save(state); renderCloset();
    }""")
    page.wait_for_timeout(250)
    n_before = page.evaluate("() => state.wardrobe.length")
    # 选中那件**没有照片**的（第二件），操作条上该长出两枚补照片的入口
    page.evaluate("() => { state.clothSel = state.wardrobe[1].id; save(state); renderCloset(); }")
    page.wait_for_timeout(300)
    check("两枚入口都在", page.eval_on_selector_all("#clothActions #rephotoBtn, #clothActions #recamBtn", "els => els.length"), 2)
    check("相册那枚开的是 #fileRephoto（不是再入柜那个）", page.evaluate("""() => {
      const i = document.querySelector('#fileRephoto'); let hit = 0;
      const orig = i.click.bind(i); i.click = () => { hit++; };
      document.querySelector('#rephotoBtn').click(); i.click = orig; return hit; }"""), 1)
    check("拍照那枚开的是带 capture 的输入框（否则设备上永远只会起相册）", page.evaluate("""() => {
      const i = document.querySelector('#fileRecam'); let hit = 0;
      const orig = i.click.bind(i); i.click = () => { hit++; };
      document.querySelector('#recamBtn').click(); i.click = orig;
      return [hit, i.getAttribute('capture')]; }"""), [1, "environment"])
    snap = page.evaluate("() => { const w = state.wardrobe[1]; return [w.name, w.cat, w.color, w.worn, w.lastWorn, 'img' in w]; }")
    check("这件本来就没有照片", snap[5], False)
    page.evaluate("""() => {
      window.__mk('#3f6f5f', '大图.jpg').then((f) => {
        const dt = new DataTransfer(); dt.items.add(f);
        const el = document.querySelector('#fileRephoto');
        el.files = dt.files; el.dispatchEvent(new Event('change'));
      });
    }""")
    page.wait_for_function("() => !!(state.wardrobe[1] && state.wardrobe[1].img)", timeout=15000)
    page.wait_for_timeout(400)
    after = page.evaluate("() => { const w = state.wardrobe[1]; return [w.name, w.cat, w.color, w.worn, w.lastWorn, w.img.slice(0, 11)]; }")
    check("补上之后名字、品类、主色、穿着记录一个字没动", after[:5], snap[:5])
    check("照片进来了，而且是 JPEG", after[5], "data:image/")
    check("柜里件数没变（补照片不是又入柜一件）", page.evaluate("() => state.wardrobe.length"), n_before)
    check("另一件一个字没动（目标就是选中的那件）", page.evaluate(
        "() => [state.wardrobe[0].name, 'img' in state.wardrobe[0], state.wardrobe[0].worn]"), ["旧衣服", False, 0])
    dims = page.evaluate("""() => new Promise((res) => {
      const i = new Image(); i.onload = () => res([i.width, i.height]); i.src = state.wardrobe[1].img; })""")
    check("和入柜同一档压缩：长边就是 320（800 的原图不会被整张塞进配额）", max(dims), 320)
    check("瓷砖从色块变成了照片", page.evaluate(
        "() => !!document.querySelector('#closet .item[data-id=\"' + CSS.escape(state.wardrobe[1].id) + '\"] img')"), True)
    check("给了一次反悔", page.is_visible(".toast.act button"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(400)
    check("撤销之后是真「没有」，不是留一个空键", page.evaluate("() => 'img' in state.wardrobe[1]"), False)
    check("瓷砖回到色块", page.evaluate(
        "() => !document.querySelector('#closet .item[data-id=\"' + CSS.escape(state.wardrobe[1].id) + '\"] img')"), True)
    # 换掉一张已有的照片：撤销要回到**上一张**，而不是把原来的弄丢
    page.evaluate("""() => {
      window.__mk('#3f6f5f', '第一张.jpg').then((f) => {
        const dt = new DataTransfer(); dt.items.add(f);
        const el = document.querySelector('#fileRephoto'); el.files = dt.files; el.dispatchEvent(new Event('change'));
      });
    }""")
    page.wait_for_function("() => !!state.wardrobe[1].img", timeout=15000)
    page.wait_for_timeout(400)
    first_img = page.evaluate("() => state.wardrobe[1].img")
    page.evaluate("""() => {
      window.__mk('#b54a3c', '第二张.jpg').then((f) => {
        const dt = new DataTransfer(); dt.items.add(f);
        const el = document.querySelector('#fileRephoto'); el.files = dt.files; el.dispatchEvent(new Event('change'));
      });
    }""")
    page.wait_for_timeout(900)
    check("换照片的提示说的是「换掉」而不是「补上」", "已换掉" in toast_text(), True)
    second_img = page.evaluate("() => state.wardrobe[1].img")
    check("第二张真的换上了", second_img != first_img, True)
    page.click(".toast.act button")
    page.wait_for_timeout(400)
    check("撤销之后不是把它清空", page.evaluate("() => state.wardrobe[1].img === null"), False)
    check("撤销回到的是上一张，逐字节就是原来那张", page.evaluate("(u) => state.wardrobe[1].img === u", first_img), True)
    # 补上来的照片要活得过重开：它走的是同一份存储，不是内存里的临时态
    page.evaluate("""() => {
      window.__mk('#2c3a4a', '第三张.jpg').then((f) => {
        const dt = new DataTransfer(); dt.items.add(f);
        const el = document.querySelector('#fileRephoto'); el.files = dt.files; el.dispatchEvent(new Event('change'));
      });
    }""")
    page.wait_for_timeout(900)
    kept = page.evaluate("() => state.wardrobe[1].img")
    page.reload()
    page.wait_for_timeout(800)
    check("补的照片活过了重开（同一段字节）", page.evaluate("(u) => state.wardrobe[1].img === u", kept), True)
    check("重开之后穿着记录也还在（换照片没带走它）",
          page.evaluate("() => [state.wardrobe[1].name, 'img' in state.wardrobe[1]]"), ["第二件", True])

    print("\n--- 12. PWA 图标与元信息 ---")
    icon_files = ["icon-192.png", "icon-512.png", "icon-maskable-512.png",
                  "apple-touch-icon.png", "favicon.png", "favicon.ico"]
    check("图标文件齐全", all((JIAN / "icons" / f).exists() for f in icon_files), True)
    mf = json.loads((JIAN / "manifest.json").read_text(encoding="utf-8"))
    check("manifest 列了 3 个图标", len(mf["icons"]), 3)
    check("manifest 含 maskable", any(i.get("purpose") == "maskable" for i in mf["icons"]), True)
    check("页面引了 favicon 与 apple-touch-icon",
          page.evaluate("""() => document.querySelectorAll('link[rel="icon"],link[rel="apple-touch-icon"]').length"""), 2)

    print("\n--- 13. 窄屏：按钮标签不折字、内容不越出纸边 ---")
    # 上面所有章节一直在 430 宽的视口里跑，而真机最窄的是 360。那 40px 的差正好够让
    # 「填一段示例聊天」折成「填一段示例聊 / 天」，把 pill 从 49px 撑到 75px 也没人发现。
    #
    # 溢出为什么不能只量 documentElement.scrollWidth：.screen 有 overflow-x: clip（第九轮，
    # 掐掉水印那 12px 出血），.btn 又有 nowrap（第十一轮，标签不许折行）。两条凑一起，
    # 标签放不下时不再折行也不是撑大文档，而是**被裁掉**——实测 360 宽把示例按钮换成 18 字，
    # documentElement.scrollWidth 一动不动还是 360，按钮右边缘却在 399。裁掉不产生可滚动区，
    # 于是文档级判定对这类缺陷全盲，而它的产品后果是文字静默消失。
    # 所以改按「屏内每个元素自己的矩形有没有越出这张纸」来判：按钮矩形 399 > 纸边 360 就炸。
    # 顺带这条也不误报：水印是 .screen::after 伪元素，天然出血 12px，但它不出现在元素矩形里。
    # 文档级 scrollWidth 仍然留着——它管的是另一件事：clip 被人摘掉、出血重新变成能晃的缝。
    NARROW = """(sel) => {
      const wrapped = [];
      for (const el of document.querySelectorAll(sel)) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        if (!el.getClientRects().length) continue;
        const txt = (el.textContent || '').replace(/\\s+/g, ' ').trim();
        if (!txt) continue;
        const rg = document.createRange();
        rg.selectNodeContents(el);
        const tops = [...rg.getClientRects()]
          .filter(r => r.width > 1 && r.height > 1).map(r => r.top).sort((a, b) => a - b);
        let rows = 0, last = -999;
        for (const y of tops) if (y - last > 6) { rows++; last = y; }
        if (rows > 1) wrapped.push((el.id || el.className) + ' · ' + txt + ' · ' + rows + '行');
      }
      const de = document.documentElement;
      return { wrapped, overflow: de.scrollWidth - de.clientWidth };
    }"""
    BLEED = """(sel) => {
      const scr = document.querySelector(sel);
      const box = scr.getBoundingClientRect();
      const bleed = [];
      for (const el of scr.querySelectorAll('*')) {
        const cs = getComputedStyle(el);
        // 浮层（toast/veil/底栏）按视口定位，本来就不归这张纸管
        if (cs.position === 'fixed') continue;
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        const over = Math.max(r.right - box.right, box.left - r.left);
        if (over > 1) {
          const cls = typeof el.className === 'string' ? el.className.trim().split(/\\s+/)[0] : '';
          const who = el.tagName.toLowerCase() + (el.id ? '#' + el.id : cls ? '.' + cls : '');
          const txt = (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 24);
          const side = r.right - box.right >= box.left - r.left ? '右' : '左';
          bleed.push(who + ' 越' + side + '边 ' + Math.round(over) + 'px' + (txt ? ' · ' + txt : ''));
        }
      }
      return bleed;
    }"""
    # 光量按钮自己的矩形还不够：哪天有人给 .btn 加 max-width:100%（想让长标签「别撑破屏幕」），
    # 框是不越界了，字却照旧跑到框外——实测「填一段示例聊天记录看看会不会撑破屏幕」在 360 下
    # 文字左右各出框 7px，墨字压在纸上；再配 overflow:hidden 更糟，min-width:auto 失效，
    # 按钮缩成半宽、头和尾各被砍掉一截，而 text-overflow 对 flex 容器的匿名子项根本不生效，
    # 连省略号都没有。两种修法都会把缺陷从「框越界」里藏起来，所以这条按**文字自己的矩形**量：
    # 标签必须整条待在「自己的框 ∩ 这张纸」里。越自己的框 = 被裁/漏到框外，越纸边 = 被 clip 裁掉。
    TRUNC = """(sel) => {
      const scr = document.querySelector(sel);
      const box = scr.getBoundingClientRect();
      const cut = [];
      for (const el of scr.querySelectorAll('.btn, .chip')) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        const rg = document.createRange();
        rg.selectNodeContents(el);
        const tr = [...rg.getClientRects()].filter(x => x.width > 1 && x.height > 1);
        if (!tr.length) continue;
        const right = Math.max(...tr.map(x => x.right));
        const left = Math.min(...tr.map(x => x.left));
        const over = Math.max(right - Math.min(r.right, box.right), Math.min(r.left, box.left) - left);
        if (over > 1) {
          const txt = (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 24);
          cut.push((el.id || el.className) + ' 出框 ' + Math.round(over) + 'px · ' + txt);
        }
      }
      return cut;
    }"""
    for w in (360, 390):
        # 守门必须量到「只有跑完才出现」的那些按钮。第 10、11 节各 reload 了一次，
        # 跑到这里结果区是空的——「复制整张笺」在 360 折成两行，这一节原先根本看不见。
        page.evaluate("""() => {
          const d = Date.now();
          state.yanCards = [{ k: '待办', line: '明天把材料发我', when: { text: '明天', at: d + DAY }, done: false }];
          state.clothSel = state.wardrobe.length ? state.wardrobe[0].id : null;
          // 排过的桌是「跑出来的界面」——第 27 节才造得出来，而这一节每次都在这之前量完。
          // 同一类盲点这文件里已经写过一次（复制整张笺那枚按钮）。所以这里直接造出
          // **最坏情况**：记满上限（WEI_HIST）的桌、12 个人、九道菜、忌口过三项。
          state.weiHist = [0, 1, 2, 3].map(i => ({
            menu: ["清蒸鲈鱼", "白灼菜心", "米饭", "紫菜蛋花汤", "宫保鸡丁", "白切鸡", "地三鲜", "蛋炒饭", "冬瓜排骨汤"]
              .slice(0, 9 - i).join(String.fromCharCode(10)),
            n: 12, t: d - i * DAY, chips: ['辣', '蒜', '海鲜', '花生']
          }));
          // 笺册那排过滤签同理：它要有存档才画得出来，而第 30 节在这之后才跑。
          // 同一类盲点这个文件里已经写过三次（复制整张笺 / 排过的桌 / 遮罩）。造最坏情况：
          // 在册上限 24 张、三种笺都有 → 签排同时出四枚。
          state.album = [];
          for (let i = 0; i < 24; i++) {
            const t = ['yi', 'wei', 'yan'][i % 3];
            state.album.push({ type: t, t: d - i * DAY, quote: '第' + i + '张', text: '整张笺' + t + '-' + i });
          }
          // 报告那一屏的三格对比框是 paintReport 填的：上面几节 reload / 造过假备份，
          // lastReport 可能已经没了。不补一份的话「章不许压住对比框」会量到 0 个框而假绿
          // （空案例不算通过——所以这一节先把自己要量的东西造出来）。
          if (!state.lastReport) {
            const it = { name: '奶咖针织', cat: '上衣', color: '#c9b39b' };
            state.lastReport = Engine.yi(it, state.wardrobe);
            state.lastReport.new = it;
          }
          paintReport();
          save(state);
        }""")
        page.set_viewport_size({"width": w, "height": 780})
        for scr in ("yi", "yi-report", "wei", "yan", "me"):
            page.evaluate("(id) => show(id)", scr)
            page.wait_for_timeout(200)
            # 0.5.x 的底栏是一枚枚纯文字按钮（「衣笺」两个字一行），所以它也被算进
            # 「标签不折字」这一格里。0.6.0 的底栏改成了**两行设计**：上面一枚小印
            # （`.nav-ico`，「衣」），下面一行标签（`.nav-lab`，「衣笺」）——
            # 那是 `.nav5 button { flex-direction: column }` intentionally 摆的，
            # 不是折字。拿「文字矩形有几行」去量它，量到的是 2，而 2 正是设计。
            # 所以量的对象收回到**真正的按钮标签**（.btn / .chip），底栏另立一条：
            # 每一枚的标签必须自己只占一行、而且与 aria-label 同一个字
            # （那就把「标签被挤断」这件事照样钉住了，没有放宽）。
            res = page.evaluate(NARROW, ".btn, .chip")
            where = f"{w}px/{scr}"
            check(f"{where} 不横向溢出", res["overflow"] <= 0, True)
            check(f"{where} 内容不越出纸边", page.evaluate(BLEED, f"#{scr}"), [])
            check(f"{where} 标签不被裁字", page.evaluate(TRUNC, f"#{scr}"), [])
            check(f"{where} 标签不折字", res["wrapped"], [])
            # 底栏五枚：小印 + 标签两行是设计，标签自己不许再折；名字与读屏器认的那句同源。
            nav = page.evaluate("""() => [...document.querySelectorAll('#nav button')].map((b) => {
              const lab = b.querySelector('.nav-lab');
              const rg = document.createRange(); rg.selectNodeContents(lab);
              const tops = [...rg.getClientRects()].filter(r => r.width > 1 && r.height > 1)
                .map(r => r.top).sort((x, y) => x - y);
              let rows = 0, last = -999;
              for (const y of tops) if (y - last > 6) { rows++; last = y; }
              return [b.id, lab.textContent, b.getAttribute('aria-label'), rows];
            })""")
            print(f"        {where} 底栏：{nav}")
            check(f"{where} 底栏每一枚的标签只占一行，且与 aria-label 同源",
                  [x[0] for x in nav if x[3] != 1 or x[1] != x[2]], [])
            if scr == "yan":
                # 行上有三个动作（挪 / 时间 / ×）。第 23 轮加「时间」之后实测 360 上正文列
                # 被挤到 **67px**——四个字一行，正文成了竖排；那条窄屏媒体查询把动作挪到
                # 正文下面一行之后回到 175px。这条预算钉住它：谁再把动作塞回同一行，
                # 或者往 .acts 里加第四枚，这里就红。
                # 量的对象是正文那一格：第 38 轮之后它不再是 .check 的直接孩子（label 缩小了，
                # 动作成了兄弟），所以按类名找。label 是 display:contents，格子宽度不变。
                col = page.evaluate("""() => {
                  const r = document.querySelector('#yanOut .check');
                  return r ? Math.round(r.querySelector('.ck-body').getBoundingClientRect().width) : -1;
                }""")
                check(f"{where} 言笺正文列够写字（≥120px，不是被动作挤成竖排）", col >= 120, True)
            if scr == "yi-report":
                # 结论章压在纸上是真的印章会做的事，但它盖掉了第三格对比框的照片：
                # 360/390/412 三档实测重叠 3314px²（章 72px 圆转 12° 之后视觉外框 85px，
                # 下沿落在离纸内边 103px，而那一排原来只留了 14px）。这条量的是**面积**。
                ov = page.evaluate("""() => {
                  const st = document.querySelector('#yi-report .stamp');
                  const boxes = [...document.querySelectorAll('#yi-report .compare .box')];
                  if (!st || !boxes.length) return { ok: true, stamp: !!st, n: boxes.length, ov: [] };
                  const s = st.getBoundingClientRect();
                  return { stamp: true, n: boxes.length,
                           ov: boxes.map((b) => {
                             const r = b.getBoundingClientRect();
                             return Math.round(Math.max(0, Math.min(s.right, r.right) - Math.max(s.left, r.left))
                                              * Math.max(0, Math.min(s.bottom, r.bottom) - Math.max(s.top, r.top)));
                           }) };
                }""")
                print(f"        {where} 章与对比框：{ov['n']} 格 · 重叠面积 {ov['ov']}")
                # 「屏上没有章 / 没有对比框」不能算过——那是空案例假绿，不是没缺陷。
                check(f"{where} 这一屏真的有报告（章 + 三格对比框都在）",
                      [ov["stamp"], ov["n"]], [True, 3])
                check(f"{where} 结论章不许盖住对比框的照片", max(ov["ov"] or [0]), 0)
            if scr == "wei":
                # 排满 8 桌时这一栏的**高度**也要有个数：不折字不代表不占地方。
                # 最早那版一签 277px（360 的一行只放得下一枚），8 桌实测 370px 高——
                # 那等于在菜单框和「排这桌」之间砌一堵墙。标签收短之后重定预算：
                # 8 桌 4 行 ≈ 200px，再长就是有人往签上堆字了。
                geo = page.evaluate("""() => {
                  const cs = [...document.querySelectorAll('#weiHist [data-hist]')];
                  return { h: Math.round(document.querySelector('#weiHist').getBoundingClientRect().height),
                           w: Math.round(Math.max(...cs.map(c => c.getBoundingClientRect().width))),
                           rows: new Set(cs.map(c => Math.round(c.getBoundingClientRect().top))).size };
                }""")
                print(f"        {where} 排过的桌：{geo['rows']} 行 · 一签 {geo['w']}px · 共 {geo['h']}px")
                check(f"{where} 记满桌数的签墙不超过 200px", geo["h"] <= 200, True)

            if scr == "me":
                # 笺册的过滤签也是「有存档才露面」的面。它一屏只摊 12 张，签排最多四枚；
                # 高度要有个数，不然谁再往这一排加第五枚、把「先过一张」那屏顶下去也没人知道。
                geo = page.evaluate("""() => {
                  const cs = [...document.querySelectorAll('#albumChips .chip')];
                  return { n: cs.length,
                           rows: new Set(cs.map(c => Math.round(c.getBoundingClientRect().top))).size,
                           h: Math.round(document.querySelector('#albumChips').getBoundingClientRect().height) };
                }""")
                print(f"        {where} 笺册签排：{geo['n']} 枚 · {geo['rows']} 行 · {geo['h']}px")
                check(f"{where} 笺册签排不超过 100px", geo["h"] <= 100, True)

        # 遮罩也是「只有跑起来才看得见」的面：BLEED/TRUNC 都按 .screen 里的元素量，
        # 而它是 fixed 浮层（本来就不该归那张纸管），那两条永远扫不到它。
        # 360 上它能坏在两件具体的事上：整张卡比屏幕还宽；或者那颗按钮的字出框。
        # endpoint 临时指一个假地址只为让「先不等了」露出来（不动 state.apiUrl，不落盘）。
        page.evaluate("() => { window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9';"
                      " JianAPI.beginTurn(); veil(true, '在认这一笺…'); }")
        page.wait_for_timeout(200)
        vg = page.evaluate("""() => {
          const card = document.querySelector('.veil-card');
          const btn = document.querySelector('#veilOff');
          const c = card.getBoundingClientRect(), b = btn.getBoundingClientRect();
          const rg = document.createRange(); rg.selectNodeContents(btn);
          const tr = [...rg.getClientRects()].filter((x) => x.width > 1 && x.height > 1);
          return { vw: innerWidth, left: Math.round(c.left), right: Math.round(innerWidth - c.right),
                   over: tr.length ? Math.round(Math.max(
                            Math.max(...tr.map((x) => x.right)) - b.right,
                            b.left - Math.min(...tr.map((x) => x.left)))) : -1,
                   h: Math.round(c.height), shown: !!btn.offsetParent };
        }""")
        page.evaluate("() => { veil(false); window.JIAN_CONFIG.endpoint = ''; }")
        print(f"        {w}px 遮罩卡：{vg['h']}px 高 · 左右余量 {vg['left']}/{vg['right']}px"
              f" · 按钮字出框 {vg['over']}px")
        check(f"{w}px 等远端时给得出「先不等了」", vg["shown"], True)
        check(f"{w}px 遮罩卡不越出屏幕两侧", vg["left"] >= 0 and vg["right"] >= 0, True)
        check(f"{w}px 遮罩那颗按钮的字不出框", vg["over"] <= 1, True)
        check(f"{w}px 遮罩卡不超过半屏高（它是提示，不是新页面）", vg["h"] <= 200, True)

    print("\n--- 14. 改与反悔：改名 / 改品类 / 单条删除 / 撤销 / 焦点找回 ---")
    page.set_viewport_size({"width": 430, "height": 940})
    page.evaluate("""() => {
      const d = Date.now();
      state.wardrobe = [
        { id: 'a1', name: '奶咖针织', cat: '上衣', color: '#d8c9b4', worn: 5, lastWorn: d - 2 * DAY, season: '春秋' },
        { id: 'a2', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: d - DAY },
        { id: 'a3', name: '驼大衣', cat: '外套', color: '#c4a574', worn: 3, lastWorn: d - 214 * DAY }
      ];
      state.editCloset = false; state.clothSel = null; state.closetSeason = 'all';
      state.yanCards = [
        { k: '待办', line: '明天把材料发我', when: { text: '明天', at: d + DAY } },
        { k: '要买', line: '买一盒药', when: null },
        { k: '已定', line: '周五见', when: { text: '周五', at: d + 3 * DAY } }
      ];
      state.yanAsk = ''; state.yanView = 'kind';
      state.people = [{ name: '我', chips: ['辣'] }, { name: '小周', chips: [] }];
      save(state); renderWeiPeople();
    }""")
    # 这一节的「改与反悔」全是柜子上的操作：#closet 的瓷砖、#clothActions 的名字框、
    # #editCloset 的整理模式。0.6.0 起这些都在 #yiPaneCloset 里（默认 hidden），
    # 只 show('yi') 的话第一下 page.click('#closet .item[data-id="a1"]') 就超时。
    yi_tab(page, "closet")
    page.wait_for_timeout(300)

    print("    · 改名（入柜时名字取自文件名，IMG_1234 那种没法忍）")
    page.click('#closet .item[data-id="a1"]')
    page.wait_for_timeout(250)
    check("点中后操作条里有名字输入框", page.is_visible("#clothName"), True)
    page.evaluate("() => { window.__tile = document.querySelector('#closet .item[data-id=\"a1\"]'); }")
    page.fill("#clothName", "燕麦开衫")
    page.evaluate("() => document.querySelector('#clothName').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(250)
    check("瓷砖上的名字跟着改", page.inner_text('#closet .item[data-id="a1"] .tag'), "燕麦开衫")
    check("读屏标签一起改，不是只改看得见的地方",
          page.get_attribute('#closet .item[data-id="a1"]', "aria-label"), "燕麦开衫，上衣，穿过 5 次")
    check("落库了", page.evaluate("() => state.wardrobe.find(w => w.id === 'a1').name"), "燕麦开衫")
    check("操作条标题也改了", page.inner_text("#clothActions .action-head b"), "燕麦开衫")
    check("改名是就地改，那块瓷砖没被重建（重建会让 Tab 提交掉进焦点陷阱）",
          page.evaluate("() => window.__tile === document.querySelector('#closet .item[data-id=\"a1\"]')"), True)
    page.evaluate("() => { document.querySelector('#clothName').value = '   '; }")
    page.evaluate("() => document.querySelector('#clothName').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(200)
    check("改成空白不生效，名字回滚", page.evaluate("() => state.wardrobe[0].name"), "燕麦开衫")
    # 回滚这件事界面自己会演（文字弹回去），但「是谁弹的」看不见——不说一句，
    # 那次弹动看着就像 bug。（第 58 轮：不许静默。）
    check("清空名字被弹回时要说一声", "名字不能空着" in toast_text(), True)

    print("    · 改主色（判定唯一吃的那个输入）")
    # `<input type=color>` 只认 #rrggbb：给它 #abc 它不报错，而是把 value 静默清成空串。
    # 老备份里三位色值是合法的（cssColor 收 3~8 位），所以这里必须先展开成六位。
    page.evaluate("() => { state.wardrobe.find(w => w.id === 'a1').color = '#abc'; save(state); renderCloset(); renderClothActions(); }")
    page.wait_for_timeout(250)
    # 浏览器自己会把控件里的值归成六位（实测 #abc→#aabbcc、#2c3a4aff→#2c3a4a、red→#ff0000），
    # 所以「展开」这件事在控件那一头根本量不出来——注入 hex6→cssColor 时 e2e 照旧绿，
    # 是守门自检把这条假门报出来的。hex6 真正管的是那行文本，和「这次到底改没改」的比较。
    check("控件和文本说的是同一个色", page.input_value("#clothColor"), page.inner_text("#clothHex"))
    page.evaluate("() => { const el = document.querySelector('#clothColor'); el.value = '#aabbcc'; el.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(250)
    check("一个字没动就不算一次改动（存储三位 vs 控件六位）", page.evaluate(
        "() => !!document.querySelector('.toast button')"), False)
    check("不算改动就不许顺手把存储改写成六位", page.evaluate(
        "() => state.wardrobe.find(w => w.id === 'a1').color"), "#abc")
    check("色值另用文本写一遍（取色器说不清自己是多少）", page.inner_text("#clothHex"), "#aabbcc")
    check("取色器有可读的名字", page.get_attribute("#clothColor", "aria-label"), "改这件的主色")
    page.evaluate("() => { window.__tile2 = document.querySelector('#closet .item[data-id=\"a1\"]'); }")
    page.evaluate("() => { const el = document.querySelector('#clothColor'); el.value = '#7b1f2b'; el.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(300)
    check("改完落库", page.evaluate("() => state.wardrobe.find(w => w.id === 'a1').color"), "#7b1f2b")
    check("操作条上那枚小色块跟着变", page.evaluate(
        "() => getComputedStyle(document.querySelector('#clothActions .swatch-sm')).backgroundColor"), "rgb(123, 31, 43)")
    check("柜里那块瓷砖的色块跟着变", page.evaluate(
        "() => getComputedStyle(document.querySelector('#closet .item[data-id=\"a1\"] .swatch')).backgroundColor"), "rgb(123, 31, 43)")
    check("改色没把读屏标签改坏（名字、品类、次数还在）",
          page.get_attribute('#closet .item[data-id="a1"]', "aria-label"), "燕麦开衫，上衣，穿过 5 次")
    check("改色也是就地改，瓷砖没被重建",
          page.evaluate("() => window.__tile2 === document.querySelector('#closet .item[data-id=\"a1\"]')"), True)
    # 判定真的吃这个新值：把它调成和候选一模一样，色差就该归零
    check("判定吃的是改过的那个色（调成同色，色差归零）", page.evaluate(
        "() => Engine.yi({ name: 'x', cat: '裙装', color: '#7b1f2b' }, state.wardrobe).basis.gap"), 0)
    page.reload()
    page.wait_for_timeout(900)
    check("整页重开之后新色还在", page.evaluate(
        "() => JSON.parse(localStorage.getItem('jian.v1')).wardrobe.find(w => w.id === 'a1').color"), "#7b1f2b")
    # 旧报告是拿旧色算的——屏幕上不能同时摆着「新色」和「按旧色下的章」还不说一句
    # reload 之后停在过笺页签，而下面要量的是柜子操作条上的 #clothColor。
    page.evaluate("() => { state.onboarded = true; }")
    yi_tab(page, "closet")
    page.wait_for_timeout(250)
    page.evaluate("""() => {
      state.editCloset = true; state.clothSel = 'a1';
      state.lastReport = Object.assign({}, state.lastReport || {}, { stamp: '宜入', quote: '旧的', new: { name: 'n', cat: '上衣', color: '#111111' } });
      renderCloset(); renderClothActions();
    }""")
    page.wait_for_timeout(250)
    page.evaluate("() => { const el = document.querySelector('#clothColor'); el.value = '#00ff00'; el.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(300)
    check("手上有报告时，改色要说这张笺是改之前算的", "改之前算的" in page.inner_text(".toast"), True)
    page.evaluate("() => document.querySelector('.toast button').click()")
    page.wait_for_timeout(300)
    check("撤销回到改之前那个色", page.evaluate("() => state.wardrobe.find(w => w.id === 'a1').color"), "#7b1f2b")
    check("撤销之后色块也回去了", page.evaluate(
        "() => getComputedStyle(document.querySelector('#clothActions .swatch-sm')).backgroundColor"), "rgb(123, 31, 43)")
    page.evaluate("() => { const el = document.querySelector('#clothColor'); el.value = '#7b1f2b'; el.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(250)
    check("值没变就不算一次改动（不弹撤销、不写盘）", page.evaluate("() => !!document.querySelector('.toast button')"), False)
    # 这一段为了量「改色之后重开还在」自己开过整理模式，得关回去：
    # 下面那节是 `page.click("#editCloset")`  expecting 从关到开，留着开会把它点到关。
    page.evaluate("() => { state.editCloset = false; save(state); renderCloset(); }")
    page.wait_for_timeout(200)

    print("    · 改品类")
    check("默认品类是上衣", page.evaluate("() => state.wardrobe[0].cat"), "上衣")
    page.click('#clothActions [data-item-cat="外套"]')
    page.wait_for_timeout(250)
    check("点一下归到外套", page.evaluate("() => state.wardrobe.find(w => w.id === 'a1').cat"), "外套")
    check("外套那枚成了选中态",
          page.evaluate("() => document.querySelector('#clothActions [data-item-cat=\"外套\"]').classList.contains('on')"), True)
    check("手改过的季节不被品类改动冲掉",
          page.evaluate("() => state.wardrobe.find(w => w.id === 'a1').season"), "春秋")

    print("    · 删一条与反悔（言笺）")
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(250)
    check("每行都有一枚 ×", page.eval_on_selector_all("#yanOut .check .drop", "els => els.length"), 3)
    done_before = page.evaluate("() => state.yanCards.map(c => !!c.done)")
    page.click('#yanOut [data-drop="1"]')
    page.wait_for_timeout(250)
    check("删掉一条", len(page.evaluate("() => state.yanCards")), 2)
    check("× 没有连带把别的行勾上",
          page.evaluate("() => state.yanCards.map(c => !!c.done)"), [done_before[0], done_before[2]])
    check("撤销提示就在眼前", page.is_visible(".toast.act"), True)
    check("提示文案", page.inner_text(".toast.act span"), "已删掉这一条")
    check("按钮写着撤销", page.inner_text(".toast.act button"), "撤销")
    page.click(".toast.act button")
    page.wait_for_timeout(250)
    check("撤销回到原位", page.evaluate("() => state.yanCards.map(c => c.line)"),
          ["明天把材料发我", "买一盒药", "周五见"])
    check("撤销后没多出勾选（× 在 label 里没触发勾选）",
          page.evaluate("() => state.yanCards.every(c => !c.done)"), True)
    page.click("#clearYan")
    page.wait_for_timeout(250)
    check("清空了", len(page.evaluate("() => state.yanCards")), 0)
    page.click(".toast.act button")
    page.wait_for_timeout(250)
    check("清空也能撤销", len(page.evaluate("() => state.yanCards")), 3)

    print("    · 删一件与反悔（衣笺）")
    # 上一段切去了言笺；这一段点的是 #editCloset 与柜子瓷砖，得先回柜子页签。
    yi_tab(page, "closet")
    page.wait_for_timeout(200)
    page.click("#editCloset")
    page.wait_for_timeout(250)
    check("整理模式下标题变成完成", page.inner_text("#editCloset"), "完成")
    page.click('#closet .item[data-id="a2"]')
    page.wait_for_timeout(250)
    check("去掉一件", page.evaluate("() => state.wardrobe.map(w => w.id)"), ["a1", "a3"])
    page.click(".toast.act button")
    page.wait_for_timeout(250)
    check("撤销按原顺序放回", page.evaluate("() => state.wardrobe.map(w => w.id)"), ["a1", "a2", "a3"])
    check("放回来的那件穿着记录没丢", page.evaluate("() => state.wardrobe[1].worn"), 12)
    page.click("#editCloset")
    page.wait_for_timeout(200)

    print("    · 键盘：整片重建之后焦点该留在原处")
    page.evaluate("() => document.querySelector('#closet .item[data-id=\"a2\"]').focus()")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    check("回车选中之后焦点还在那块瓷砖上", page.evaluate("() => document.activeElement.dataset.id"), "a2")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    check("再回车取消选中，焦点仍在",
          page.evaluate("() => [document.activeElement.dataset.id, state.clothSel]"), ["a2", None])
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(200)
    page.evaluate("() => document.querySelector('#yanOut [data-yi=\"0\"]').focus()")
    page.keyboard.press("Space")
    page.wait_for_timeout(300)
    check("空格勾完之后焦点还在那一行的复选框上",
          page.evaluate("() => document.activeElement.dataset.yi"), "0")
    check("确实勾上了", page.evaluate("() => state.yanCards[0].done"), True)
    page.evaluate("() => document.querySelector('#yanOut [data-yanview=\"time\"]').focus()")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    check("换看法之后焦点留在「按时间」上",
          page.evaluate("() => [document.activeElement.dataset.yanview, state.yanView]"), ["time", "time"])
    page.evaluate("() => { state.yanView = 'kind'; save(state); renderYan(); }")

    print("    · 味笺忌口：默认收成一行，点开才是全表")
    # 「忌口」那张卡片与 #people 都长在排桌页签里（#weiPanePlan）。
    # 只 show('wei') 的话 #people 是 hidden 子树，page.click 会等 30 秒再抛。
    wei_tab(page, "plan")
    page.wait_for_timeout(250)
    check("没忌口的人不摊开那一排小签",
          page.evaluate("() => document.querySelectorAll('#people .card:nth-child(2) [data-c]').length"), 0)
    check("已选的人行上是「忌口」，没选的人写着没人忌口",
          page.evaluate("""() => [
            [...document.querySelectorAll('#people .card:nth-child(1) .chips button')].map(e => e.textContent),
            [...document.querySelectorAll('#people .card:nth-child(2) .chips button')].map(e => e.textContent),
            document.querySelector('#people .card:nth-child(2) .who-none') !== null
          ]"""), [["辣", "忌口"], ["忌口"], True])
    check("折叠态告诉读屏器没展开",
          page.get_attribute('#people [data-open="1"]', "aria-expanded"), "false")
    page.click('#people [data-open="1"]')
    page.wait_for_timeout(250)
    # 数量从 state.js 的 CHIPS 现读：2026-10 补了蛋 / 小麦 / 大豆 / 坚果 四类，
    # 写死 11 的话这条会在「展开之后少了几枚」和「清单变长了」两种情况下都说不出区别。
    chips_n = page.evaluate(
        "() => document.querySelectorAll('#people .card:nth-child(2) [data-c]').length")
    want_chips = page.evaluate("() => CHIPS.length")
    check("点「忌口」摊开全表（枚数 == state.js 的 CHIPS.length）", chips_n, want_chips)
    check("展开态跟着变", page.get_attribute('#people [data-open="1"]', "aria-expanded"), "true")
    check("标题变成收起", page.inner_text('#people [data-open="1"]'), "收起")
    page.click('#people .card:nth-child(2) [data-c="香菜"]')
    page.wait_for_timeout(250)
    check("勾中一枚忌口落库", page.evaluate("() => state.people[1].chips"), ["香菜"])
    check("勾完保持摊开", page.inner_text('#people [data-open="1"]'), "收起")
    page.click('#people .card:nth-child(2) [data-c="香菜"]')
    page.wait_for_timeout(250)
    check("再点一下取消", page.evaluate("() => state.people[1].chips"), [])
    page.click('#people [data-del="1"]')
    page.wait_for_timeout(250)
    check("移除一个人", page.evaluate("() => state.people.map(p => p.name)"), ["我"])
    page.click(".toast.act button")
    page.wait_for_timeout(250)
    check("撤销把人放回原位", page.evaluate("() => state.people.map(p => p.name)"), ["我", "小周"])
    check("两个人的忌口都还在", page.evaluate("() => state.people.map(p => p.chips.length)"), [1, 0])
    check("三个人的忌口互不串（焦点找回也按人分）",
          page.evaluate("""() => {
            state.people[1].chips = ['辣']; save(state); renderWeiPeople();
            return [...document.querySelectorAll('#people [data-c="辣"]')].map(b => b.dataset.who);
          }"""), ["0", "1"])

    print("\n--- 15. 分批贴不再互相覆盖（以前第二贴会把第一贴连同勾掉的状态整片冲掉）---")
    page.evaluate("() => { state.points = 20; state.yanCards = []; state.yanAsk = ''; save(state); show('yan'); }")
    page.wait_for_timeout(200)
    page.evaluate("() => { document.querySelector('#yanText').value = '明天把材料发我。\\n药快没了帮我买一盒。'; runYan(); }")
    page.wait_for_function("() => (state.yanCards || []).length > 0", timeout=15000)
    first = len(page.evaluate("() => state.yanCards"))
    pts1 = page.evaluate("() => state.points")        # 已经扣过第一贴那 1 点
    check("第一贴捞出条数", first > 0, True)
    page.evaluate("() => { document.querySelector('#yanText').value = '明天把材料发我。\\n周五把合同寄出。'; runYan(); }")
    page.wait_for_timeout(1200)
    check("重复那句没多出来，新那句进来了", len(page.evaluate("() => state.yanCards")), first + 1)
    check("第二贴再扣一点", page.evaluate("() => state.points"), pts1 - 1)
    # 勾掉一条，再把同一批原样贴一次：一条都不该多，点也不该扣
    page.evaluate("() => { state.yanCards[0].done = true; save(state); renderYan(); }")
    page.evaluate("() => { document.querySelector('#yanText').value = '明天把材料发我。\\n周五把合同寄出。'; runYan(); }")
    page.wait_for_timeout(1200)
    check("原样再贴一条没多", len(page.evaluate("() => state.yanCards")), first + 1)
    check("一条没多就把这点退回去", page.evaluate("() => state.points"), pts1 - 1)
    check("已勾的那条还勾着（合并没把它冲成新的）", page.evaluate("() => state.yanCards[0].done"), True)
    # 这句提示是 runYan 的异步尾巴上才出现的：固定等 1.2 秒在忙机器上会读在「还没弹出来」
    # 的那一刻——那就不是一条红断言，而是一颗会把守门自检的归因带跑的随机炸弹。
    wait_ok("() => { const t = document.querySelector('.toast');"
            " return !!t && t.textContent.indexOf('已经捞过') >= 0; }", 8000, "「这批已经捞过了」那句提示")
    check("提示说了「已经捞过」",
          toast_text(), "这批已经捞过了，一条没多")
    check("合并之后复制整张笺含两批", page.evaluate("() => yanText().includes('周五把合同寄出')"), True)

    print("\n--- 16. 换屏要把焦点交给那一屏（读屏器才知道到了哪儿）---")
    page.evaluate("() => show('wei')")
    page.wait_for_timeout(250)
    check("普通屏交给标题",
          page.evaluate("() => document.activeElement.tagName + '|' + document.activeElement.closest('.screen').id"),
          "H1|wei")
    page.evaluate("() => show('yi-report')")
    page.wait_for_timeout(250)
    # 这一屏以前没有 h1：焦点交给 section 本身，读屏器只念出区域名「衣笺报告」，
    # 而这一屏唯一要看的那两个字（宜入 / 再想想 / 先别）一个字都没念。现在有一个只给读屏器的
    # 标题，文字跟着判定走（yi.js 的 paintReport），焦点落点因此就是答案本身。
    check("换屏把焦点交给报告页那个屏幕外的标题", page.evaluate("() => document.activeElement.id"), "reportTitle")
    rt = page.evaluate("""() => ({ t: document.querySelector('#reportTitle').textContent,
                                   stamp: (state.lastReport || {}).stamp || '' })""")
    check("标题里带着判定（有笺就带章上那个词，没笺就明说）",
          (rt["stamp"] in rt["t"]) if rt["stamp"] else ("还没有笺" in rt["t"]), True)
    check("它只给读屏器：自己不占版面", page.evaluate(
        "() => { const r = document.querySelector('#reportTitle').getBoundingClientRect();"
        " return r.width <= 1 && r.height <= 1; }"), True)

    check("报告页有 aria-label", page.get_attribute("#yi-report", "aria-label"), "衣笺报告")

    print("\n--- 17. 清空本地数据也能反悔（全 App 最狠的一下）---")
    dialogs.clear()      # 处理器在第 11.5 节就挂上了，一个页面只能挂一个
    page.evaluate("""() => {
      state.onboarded = true;
      state.wardrobe = [{ id: 'z1', name: '要没的衣服', cat: '上衣', color: '#888888', worn: 4, lastWorn: null }];
      state.points = 9; save(state); show('me');
    }""")
    page.wait_for_timeout(250)
    page.click("#reset")
    page.wait_for_timeout(1600)      # 清空之后整页 reload
    check("弹的是确认框", dialogs, ["confirm"])
    check("清空之后回到种子柜", page.evaluate("() => state.wardrobe.length"), 6)
    check("回来还有一次撤销", page.is_visible(".toast.act button"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(500)
    check("撤销把整份数据拿回来", page.evaluate("() => [state.wardrobe[0].name, state.wardrobe[0].worn, state.points]"),
          ["要没的衣服", 4, 9])
    # 清空之后整页 reload 过，页签回到默认的「过笺」；「界面也跟着回来了」问的是
    # 柜子瓷砖有没有重新长出来，而瓷砖只在 #yiPaneCloset 里——不切过去恒为 False。
    yi_tab(page, "closet")
    check("界面也跟着回来了", page.is_visible("#closet .item[data-id]"), True)
    # 注意 check() 在 want=None 时退化成 bool(got)，所以「期望是 null」必须在页面里比成布尔
    check("快照只活一次，用完作废",
          page.evaluate("() => sessionStorage.getItem('jian.v1.undo') === null"), True)

    print("\n--- 18. 安卓返回键的去处：先回上一张纸，栈底才交给系统 ---")
    # registerNativeBack 以前一律 minimizeApp()：在衣笺报告上按返回，整个 App 退到后台。
    # 栈本身在浏览器里也成立（原生回调只是 goBack() 的调用方），所以在这里量。
    page.evaluate("() => show('yi')")
    page.evaluate("() => show('yi-report')")
    check("子页把上一张记进栈", page.evaluate("() => backStack.slice()"), ["yi"])
    check("返回回到衣笺", page.evaluate("() => goBack() && document.querySelector('.screen.on').id"), "yi")
    check("栈底之后返回键交还给系统（该退后台了）", page.evaluate("() => goBack()"), False)
    check("底栏那种平级切换会清栈", page.evaluate(
        "() => { show('yi'); show('yi-report'); show('wei'); return backStack.slice(); }"), [])
    check("报告页里的「返回衣笺」也清栈", page.evaluate(
        "() => { show('yi'); show('yi-report'); show('yi'); return backStack.slice(); }"), [])

    print("\n--- 19. 判定出处要说真话：填了地址 ≠ 接通了 ---")
    # 以前 hintEngine / #apiState 只看 remoteOn()（有没有填过地址），三条路静默回落本地时
    # 界面照旧说「已指向网关」。这是 NEXT.md 里挂着的一条旧债，这一节把它钉住。
    check("没填地址时说的是本地", page.evaluate("() => JianAPI.status().via"), "local")
    # 这一节问的是过笺这一页的入口（#camBtn / #fileCam）与顶栏那行小字。
    # 0.6.0 起 #camBtn 在 #yiPanePass 里：停在别的页签上时它虽然还在 DOM 里，
    # `is_visible` 却是 False——那会把「拍照入口在」报成一条假红。
    yi_tab(page, "pass")
    page.wait_for_timeout(250)
    check("顶栏那行小字跟着说实话", page.inner_text("#engineHint"), "本地")
    check("拍照入口在，且直接指向后置相机", page.evaluate(
        "() => { const i = document.querySelector('#fileCam');"
        " return [!!document.querySelector('#camBtn'), i.getAttribute('capture'), i.accept]; }"),
        [True, "environment", "image/*"])
    check("点「过笺 · 拍照」开的是拍照那个输入框", page.evaluate("""() => {
      const i = document.querySelector('#fileCam'); let hit = 0;
      const orig = i.click.bind(i); i.click = () => { hit++; };
      document.querySelector('#camBtn').click(); i.click = orig; return hit;
    }"""), 1)

    # 填一个必然连不上的地址：判定必须照样出（回落本地），但出处要认账。
    # 端口 9 是 Chromium 的保留端口，fetch 根本不出网就失败 —— 比挑一个「应该没人占」的端口确定。
    mark = len(errors)
    page.evaluate("""() => {
      window.JIAN_CONFIG.endpoint = "http://127.0.0.1:9/";
      state.points = 20; save(state);
    }""")
    # 第 17 节清空数据时 reload 过整页，window.__mk 那种页面里注入的助手就没了 → 重新装一次
    page.evaluate(MK)
    page.evaluate("async () => { const f = await window.__mk('#c9b39b', 'cam.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport !== null", timeout=20000)
    page.wait_for_timeout(300)
    st = page.evaluate("() => JianAPI.status('yi')")
    check("网关没通时判定仍然出得来", bool(page.evaluate("() => state.lastReport && state.lastReport.stamp")), True)
    check("但出处记的是本地", st["via"], "local")
    check("并且留下了失败原因", bool(st["error"]), True)
    page.evaluate("() => { show('yi'); renderCloset(); hintEngine(); }")
    # 上面 renderCloset 是显式调的，但 #engineHint 是顶栏那一行（不属于任何页签），
    # 所以这一条不依赖页签；保留 show('yi') 只为让「回落本地」出现在衣笺上。
    page.wait_for_timeout(200)
    check("顶栏改口：回落本地", page.inner_text("#engineHint"), "回落本地")
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    check("「册」里明说那张笺是本地算的", page.evaluate("() => /本地规则算的/.test(document.querySelector('#apiState').textContent)"), True)
    # —— 上面那三条其实咬不住 yi 自己那一行记账：过笺是先 see() 再 yi()，see() 撞死地址时
    # 已经把 30 秒冷却点着了，yi() 整段根本没打网关，走的是「冷却中」那支。把 yi 的 catch
    # 整行删掉，界面上照旧是「local + 一句话 + 回落本地」——第一次全量 127 条注入认证
    # 就是这么抓到这条死门的（126 拦 / 1 漏）。所以要另造一个只经 yi 这一支的现场：
    # 先把冷却按掉，再**直接**调 JianAPI.yi()，让它自己成为第一个撞上死地址的人。
    yi_direct = page.evaluate("""async () => {
      JianAPI.warm();                       // 只清冷却，不清 last（就是要看它会不会被改写）
      const wasCold = JianAPI.status('yi').cold;
      const r = await JianAPI.yi({ name: '直接问的这件', cat: '上衣', color: '#c9b39b' }, state.wardrobe);
      const s = JianAPI.status('yi');
      return { stamp: r.stamp || '', wasCold, cold: s.cold, via: s.via, error: s.error || '' };
    }""")
    check("现场是真的：进这一枪之前冷却归零（不然比的是旧账）", yi_direct["wasCold"] < 1000, True)
    check("冷却按掉后 yi 自己撞死地址，判定照样出", bool(yi_direct["stamp"]), True)
    check("出处记的是本地", yi_direct["via"], "local")
    check("而且是 yi 这一支自己把冷却点上的（不是抄 see 的功）", yi_direct["cold"] > 20000, True)
    check("留的原因不是「冷却中」那句托词", "30 秒内先都走本地" in yi_direct["error"], False)
    check("留了可定位的失败原文", len(yi_direct["error"]) > 0, True)
    # 这一段是故意打一个死地址：只把这段时间里「那条请求本身」的控制台报错剔掉，
    # 别的任何新报错（pageerror、别的资源 404）一律照旧算账
    errors[mark:] = [e for e in errors[mark:] if "Failed to load resource" not in e]
    page.evaluate("() => { delete window.JIAN_CONFIG.endpoint; show('yi'); hintEngine(); }")
    page.wait_for_timeout(200)
    check("清掉地址后回到本地口径", page.inner_text("#engineHint"), "本地")

    print("\n--- 19b. 回话读不懂不许把屏幕锁住（模型在网关那一头，它回什么都有可能）---")
    pts_gw = page.evaluate("() => state.points")
    page.evaluate("() => { state.points = 20; state.yanCards = []; save(state); show('yan'); }")
    page.wait_for_timeout(200)
    # 前三条什么都捞不出来（退点、屏上不多东西），第四条里那句「买牛奶」是**好的**——
    # 一条坏数据不该把同批的好数据一起带走。两种都要钉住。
    empty_yan = [("待办是一段话", {"待办": "不是数组"}),
                 ("条目没有 line", {"待办": [{"when": {"text": "明天", "at": 1758123456000}}]}),
                 ("line 是数字", {"待办": [{"line": 123, "when": {"text": "明天", "at": 1758123456000}}]})]
    for label, payload in empty_yan:
        mark = len(errors)
        page.evaluate("(p) => { window.__savedYan = JianAPI.yan; JianAPI.yan = async () => p; }", payload)
        page.evaluate("() => { document.querySelector('#yanText').value = '记得买一箱牛奶。'; runYan(); }")
        page.wait_for_timeout(800)
        page.evaluate("() => { JianAPI.yan = window.__savedYan; }")
        check(f"{label}：遮罩收了（不是一条路走死）",
              page.evaluate("() => !document.querySelector('.veil.on')"), True)
        check(f"{label}：没抛到外面", [e for e in errors[mark:] if "pageerror" in e], [])
        errors[mark:] = [e for e in errors[mark:] if "Failed to load resource" not in e]
        check(f"{label}：一条都没进笺，这一点也退回来",
              [page.evaluate("() => state.yanCards.length"), page.evaluate("() => state.points")], [0, 20])
        # 「读不懂」那一句是**兜底 catch** 才说的。数据是空的但形状读得动，说的就该是
        # 「没捞到能落地的事」——把 normCards 的 Array 检查摘掉，这里就会露出崩溃托词。
        check(f"{label}：说的是没捞到，不是崩溃托词", "读不懂" in toast_text(), False)
    mark = len(errors)
    page.evaluate("""() => { window.__savedYan = JianAPI.yan; JianAPI.yan = async () =>
      ({ 待办: [null, '买牛奶', { line: 42 }, ''] }); }""")
    page.evaluate("() => { document.querySelector('#yanText').value = '记得买一箱牛奶。'; runYan(); }")
    page.wait_for_timeout(800)
    page.evaluate("() => { JianAPI.yan = window.__savedYan; }")
    check("坏回包之后下一批照常捞得出来", page.evaluate("() => state.yanCards.length"), 1)
    check("捞进来的正是那句好数据", page.evaluate("() => state.yanCards[0].line + '｜' + state.yanCards[0].k"), "买牛奶｜待办")
    junk = page.evaluate("""() => {
      const t = document.querySelector('#yanOut').innerText;
      const m = t.match(/.{0,26}(\\[object Object\\]|undefined|NaN).{0,26}/);
      return m ? m[0] : '';
    }""")
    check("同批那些读不懂的没留在屏上", junk, "")
    check("遮罩收了", page.evaluate("() => !document.querySelector('.veil.on')"), True)
    check("没抛到外面", [e for e in errors[mark:] if "pageerror" in e], [])
    errors[mark:] = [e for e in errors[mark:] if "Failed to load resource" not in e]
    # 回话本身能拿到、但**处理到一半**抛（模型给的字段是个会炸的东西）：
    # 这正是「收尾写在 try 外面」那一版会把遮罩永远挂着的那一格。
    page.evaluate("() => { state.points = 20; state.yanCards = []; save(state); }")
    mark = len(errors)
    page.evaluate("""() => { window.__savedYan = JianAPI.yan; JianAPI.yan = async () => ({
      待办: ['记得带伞'], get ask() { throw new Error('这个字段读不出来'); } }); }""")
    page.evaluate("() => { document.querySelector('#yanText').value = '记得带伞。'; runYan(); }")
    page.wait_for_timeout(800)
    page.evaluate("() => { JianAPI.yan = window.__savedYan; }")
    check("处理途中抛了也不许把遮罩留着", page.evaluate("() => !document.querySelector('.veil.on')"), True)
    check("抛出来说明这一封没成，那一点退回来", page.evaluate("() => state.points"), 20)
    check("而且当场说清楚是回话读不懂", "读不懂" in toast_text(), True)
    check("没抛到外面", [e for e in errors[mark:] if "pageerror" in e], [])
    errors[mark:] = [e for e in errors[mark:] if "Failed to load resource" not in e]
    page.evaluate("() => { state.yanCards = []; save(state); renderYan(); }")

    print("\n--- 19c. 味笺收到不像桌的回话：能清的清掉，清不动的退点 ---")
    # #menu 与 #weiResult 都在排桌页签里；下面 `is_visible("#weiResult .sheet")`
    # 是「这一桌画得出来」的判据，藏在 hidden 里就恒为 False。
    wei_tab(page, "plan")
    page.evaluate("() => { document.querySelector('#menu').value = '米饭\\n宫保鸡丁'; }")
    page.wait_for_timeout(200)
    mark = len(errors)
    page.evaluate("""() => { window.__savedWei = JianAPI.wei; JianAPI.wei = async () => ({
      safe: '不是数组', kinds: '一段话', plan: '也不是桌', boom: {}, order: null, talk: '这一桌' }); }""")
    page.evaluate("() => { state.points = 20; runWei(); }")
    page.wait_for_timeout(900)
    page.evaluate("() => { JianAPI.wei = window.__savedWei; }")
    check("形状错的字段被收掉，不留给 paintWei 去 map", page.evaluate(
        "() => ['safe', 'boom', 'order'].filter(k => k in state.lastWei.r).join()"), "")
    check("kinds / plan 补成空对象（画的时候是直接取子键的）", page.evaluate(
        "() => [typeof state.lastWei.r.kinds, typeof state.lastWei.r.plan.want, typeof state.lastWei.r.plan.gap]"),
        ["object", "object", "object"])
    check("这一桌照样画得出来（不是整屏空白）", page.is_visible("#weiResult .sheet"), True)
    check("遮罩收了", page.evaluate("() => !document.querySelector('.veil.on')"), True)
    check("没抛到外面", [e for e in errors[mark:] if "pageerror" in e], [])
    errors[mark:] = [e for e in errors[mark:] if "Failed to load resource" not in e]
    # 连对象都不是的回话：退这一点，并说清是网关那边回的东西不对
    mark = len(errors)
    page.evaluate("() => { JianAPI.wei = async () => '一段话'; }")
    page.evaluate("() => { state.points = 20; runWei(); }")
    page.wait_for_timeout(900)
    page.evaluate("() => { JianAPI.wei = window.__savedWei; }")
    check("回话不是一张桌时把这一点退回去", page.evaluate("() => state.points"), 20)
    check("说的是「网关回的不是一张桌」，不是含糊的没排成", toast_text(), "网关回的不是一张桌，笺点已退回")
    check("遮罩收了（退点这条路上也一样）", page.evaluate("() => !document.querySelector('.veil.on')"), True)
    check("没抛到外面", [e for e in errors[mark:] if "pageerror" in e], [])
    errors[mark:] = [e for e in errors[mark:] if "Failed to load resource" not in e]
    page.evaluate("(p) => { state.points = p; save(state); }", pts_gw)
    page.wait_for_timeout(200)

    print("\n--- 20. 柜子搜索：筛得动，搜不到要说搜不到 ---")
    tiles = lambda: page.eval_on_selector_all("#closet .item[data-id]", "els => els.length")
    # 这一整节量的是柜子搜索：#clothSearch 输入框、「常穿/久未穿」那排筛、#closet 的空态。
    # 0.6.0 起它们全在 #yiPaneCloset 里，而上一节停在味笺——不切页签，
    # 第一句 `page.fill("#clothSearch", …)` 就会报 "element is not visible"。
    yi_tab(page, "closet")
    # 自己铺一遍种子柜：前面第 11.5 节导入过备份，柜里已经不是那 6 件了。
    # 依赖上一条用例留下的数据，是这套门最容易被无声改坏的地方。
    page.evaluate("""() => {
      state.wardrobe = seedWardrobe();
      state.closetSeason = 'all'; state.closetSort = 'freq';
      state.clothSel = null; state.editCloset = false;
      save(state);
      document.querySelector('#clothSearch').value = ''; renderCloset();
    }""")
    page.wait_for_timeout(250)
    check("没搜之前是整柜", tiles(), 6)
    page.fill("#clothSearch", "上衣")
    page.wait_for_timeout(200)
    check("按品类搜得动", tiles(), 2)
    check("摘要跟着报命中数", "搜「上衣」2 件" in page.inner_text("#closetNote"), True)
    page.fill("#clothSearch", "白")
    check("按名字搜得动（跨品类）", tiles(), 2)
    page.fill("#clothSearch", "  燕麦  ")
    check("首尾空白不算进关键词", tiles(), 1)
    page.fill("#clothSearch", "不存在的某件")
    check("搜不到给的是专属空态", page.inner_text("#closet .empty").startswith("柜里搜不到"), True)
    check("空态里留了退路", page.is_visible("#clearSearch"), True)
    check("搜空了也不说「柜子是空的」", "柜子是空的" in page.inner_text("#closet"), False)
    page.click("#clearSearch")
    page.wait_for_timeout(200)
    check("点「清掉搜索」回到整柜", tiles(), 6)
    check("搜索框跟着清空", page.input_value("#clothSearch"), "")
    # 搜索与季节是叠加的：驼大衣搜得到，切到「夏」就该被季节筛掉——
    # 只验一条会放过「后写的筛子把前一条覆盖了」这种错。
    page.fill("#clothSearch", "驼大衣")
    page.wait_for_timeout(200)
    check("单搜那一件搜得到", tiles(), 1)
    page.click('[data-season="夏"]')
    page.wait_for_timeout(200)
    check("季节 + 搜索叠加之后为空", tiles(), 0)
    check("叠加筛空了说的还是搜索这一条", page.inner_text("#closet .empty").startswith("柜里搜不到"), True)
    page.click('[data-season="all"]')
    page.wait_for_timeout(200)
    check("换回「全部」时搜索词还在", tiles(), 1)
    # 大小写：柜子里可以有「UNIQLO 白 T」这种混写
    page.evaluate("""() => {
      state.wardrobe.push({ id: 'wtest', name: 'UNIQLO 白 T', cat: '上衣', color: '#ffffff', worn: 0, lastWorn: null });
      save(state); renderCloset();
    }""")
    page.fill("#clothSearch", "uniqlo")
    page.wait_for_timeout(200)
    check("搜小写命中大写名", tiles(), 1)
    check("搜出来的正是那件", page.inner_text("#closet .item[data-id] .tag"), "UNIQLO 白 T")
    page.evaluate("""() => {
      state.wardrobe = state.wardrobe.filter(w => w.id !== 'wtest');
      document.querySelector('#clothSearch').value = '';
      save(state); renderCloset();
    }""")
    page.wait_for_timeout(200)
    check("搜完把测试件撤掉，柜里回到 6 件", tiles(), 6)

    print("\n--- 21. 言笺「只看没办的」：过滤不许把行号挪位 ---")
    rows = lambda: page.eval_on_selector_all("#yanOut .check", "els => els.length")
    page.evaluate("""() => {
      state.yanHideDone = false; state.yanView = 'kind'; state.yanAsk = '';
      state.yanCards = [
        { k: '待办', line: '发材料', when: null, who: null, speaker: null, done: false },
        { k: '待办', line: '买药', when: null, who: null, speaker: null, done: false },
        { k: '要买', line: '买纸巾', when: null, who: null, speaker: null, done: false }];
      save(state); show('yan');
    }""")
    page.wait_for_timeout(250)
    check("三行全在", rows(), 3)
    page.click("#yanOut input[data-yi='0']")
    page.wait_for_timeout(250)
    check("默认仍然看得见已勾的", rows(), 3)
    check("计数说的是全量", "3 条 · 已勾 1" in page.inner_text("#yanOut .bar .tiny"), True)
    page.click("#yanUndone")
    page.wait_for_timeout(250)
    check("过滤后只剩没办的", rows(), 2)
    check("屏上没有勾掉的", page.evaluate("() => [...document.querySelectorAll('#yanOut .check')].every(e => !e.classList.contains('done'))"), True)
    check("行上的下标仍是全量下标", page.eval_on_selector_all("#yanOut input[data-yi]", "els => els.map(e => +e.dataset.yi)"), [1, 2])
    check("计数换成「没办 / 已勾」", "没办 2 · 已勾 1" in page.inner_text("#yanOut .bar .tiny"), True)
    page.click("#yanOut input[data-yi='1']")
    page.wait_for_timeout(250)
    check("勾的是第 2 条，不是被顶上来的那条", page.evaluate("() => state.yanCards.map(c => c.done)"), [True, True, False])
    check("过滤后计数跟着走", "没办 1 · 已勾 2" in page.inner_text("#yanOut .bar .tiny"), True)
    page.evaluate("() => { state.yanCards[2].done = true; save(state); renderYan(); }")
    page.wait_for_timeout(250)
    check("全清完了给的是空态而不是白屏", page.inner_text("#yanOut .empty").startswith("没办的清完了"), True)
    check("空态下笺还在（复制/清空仍然点得到）", page.is_visible("#copyYan"), True)
    page.click("#yanUndone")
    page.wait_for_timeout(250)
    check("取消过滤回看全部", rows(), 3)
    page.evaluate("() => { state.yanHideDone = false; state.yanCards = []; state.yanAsk = ''; save(state); renderYan(); }")

    print("\n--- 22. 深链：快捷方式与 #hash 要落到那一笺 ---")
    # 注意：screenOf 认不出时返回 null，而 check() 的第二个参数缺省即「按真假判」，
    # 所以这里一律把「是不是 null」在页面里算成布尔，别把 None 当期望值传进来。
    check("认得 jian://screen/yan", page.evaluate("() => screenOf('jian://screen/yan')"), "yan")
    check("认得 #wei", page.evaluate("() => screenOf('#wei')"), "wei")
    check("子页不算主屏", page.evaluate("() => screenOf('#yi-report') === null"), True)
    check("不相干的地址不认", page.evaluate("() => screenOf('https://example.com/a/b') === null"), True)
    check("空地址不认", page.evaluate("() => screenOf('') === null"), True)
    page.evaluate("() => { state.modules = { yi: true, wei: true, yan: true }; save(state); paintNav(); }")
    check("点快捷方式真的换屏", page.evaluate("() => openDeep('jian://screen/wei') && document.querySelector('.screen.on').id"), "wei")
    # 快捷方式是静态清单，它不知道用户把哪一笺关掉了
    page.evaluate("() => { state.modules.yan = false; save(state); paintNav(); }")
    check("关掉的那一笺不硬开", page.evaluate("() => openDeep('jian://screen/yan') && document.querySelector('.screen.on').id"), "me")
    check("并且说清楚为什么", page.inner_text(".toast"), "这一笺已经关掉了，在下面重新打开")
    page.evaluate("() => { state.modules.yan = true; save(state); paintNav(); show('yi'); }")
    check("地址里的 # 变了也跟着换屏", page.evaluate(
        "async () => { location.hash = '#yan';"
        " await new Promise(r => setTimeout(r, 200)); return document.querySelector('.screen.on').id; }"), "yan")

    # 原生冷启动：伪造一个只带 App 插件的 Capacitor，看 boot 认不认这个地址。
    # 只给 App 一个插件就够：hasNative() 为真之后，其余原生调用都各有权判，缺插件就是静默。
    page.evaluate("() => { state.onboarded = true; state.home = 'yan'; save(state); }")
    # add_init_script 挂在 page 上只影响这一张页；新页要的是挂在 context 上的那份。
    ctx.add_init_script("""window.Capacitor = { Plugins: { App: {
      getLaunchUrl: async () => ({ url: 'jian://screen/wei' }),
      addListener: () => ({}) } } };""")
    lp = ctx.new_page()
    lp.on("pageerror", lambda e: errors.append("pageerror(deeplink): " + str(e)))
    lp.goto(URL)
    lp.wait_for_function("() => document.querySelector('.screen.on') && !document.querySelector('#onboard').classList.contains('on')", timeout=15000)
    check("冷启动带地址时，落的不是 state.home", lp.evaluate("() => document.querySelector('.screen.on').id"), "wei")
    check("没地址时仍然按 state.home", page.evaluate("() => { show(state.home); return document.querySelector('.screen.on').id; }"), "yan")
    lp.close()

    print("\n--- 23. 纸的两种说法：白天是那张米色的纸，夜里是墨底的那张 ---")
    # 0.5.x 的这条断言叫「纸只有一种说法：系统夜里也不换皮肤」——那时全仓只有一张米色的纸，
    # 而它的用意是**不让系统自作主张**把浏览器画的那些控件（复选框 / 日期 / 滚动条）
    # 换成一身深色皮，压在米纸上就是一块块对不上的灰。
    #
    # 0.6.0 改了产品事实：theme.js + styles-v06.css 的 `:root[data-theme="dark"]` 那一整块
    # 是**故意做出来的夜间纸**（--paper #1b1917 / --ink #e8e2d6 / color-scheme: dark），
    # 用户在「册 → 外观」里能选亮 / 暗 / 跟随系统。所以「夜里也不换皮肤」这条已经不成立，
    # 但它原本要守的那件事**仍然要守**，只是判据换了：换了纸，就得整张一起换——
    # 纸底、墨色、UA 控件三处不许一处换了另一处没换（那才是「两个 App 拼的」那种错）。
    # 所以这一节改成钉这三条：
    #   ① 亮色时：纸是米色的那张，color-scheme 里是 light；
    #   ② 跟随系统 + 系统夜里：整张纸一起翻到墨底（纸底、正文色、UA 控件三样同一套）；
    #   ③ 用户在「册」里选死「亮色」时：系统再怎么夜里也不许翻（用户的选择压过系统）。
    check("亮色时根上声明的是 light", page.evaluate(
        "() => (getComputedStyle(document.documentElement).colorScheme || '').split(' ').includes('light')"), True)
    check("亮色时纸底是那张米色的纸", page.evaluate(
        "() => getComputedStyle(document.body).backgroundColor"), "rgb(244, 239, 230)")
    check("亮色时输入框是纸上的浅底深字", page.evaluate("""() => {
      const el = document.querySelector('#clothSearch');
      const cs = getComputedStyle(el);
      return [cs.backgroundColor, cs.color];
    }"""), ["rgb(250, 247, 241)", "rgb(42, 39, 35)"])
    # 跟随系统（默认就是 auto）→ 系统夜里，整张纸一起翻
    page.evaluate("() => { THEME.set('theme', 'auto'); }")
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(300)
    dark23 = page.evaluate("""() => {
      const root = document.documentElement, cs = getComputedStyle(root);
      const body = getComputedStyle(document.body);
      const inp = document.querySelector('#clothSearch');
      const ics = getComputedStyle(inp);
      return { theme: root.dataset.theme,
               scheme: (cs.colorScheme || '').split(' ').includes('dark'),
               paper: body.backgroundColor, ink: body.color,
               box: [ics.backgroundColor, ics.color],
               // 夜里不许还有一处是白天那组色：米纸 / 深墨字
               light: ['rgb(244, 239, 230)', 'rgb(42, 39, 35)'] };
    }""")
    print(f"        跟随系统翻夜：{dark23}")
    check("跟随系统 + 系统夜里：整张纸翻到墨底（不是只换了一半）",
          [dark23["theme"], dark23["scheme"], dark23["paper"] != dark23["light"][0]],
          ["dark", True, True])
    check("翻到墨底之后，正文是浅字（深浅陪着一起来，不许白纸黑字只换一半）",
          dark23["ink"] != dark23["light"][1], True)
    check("UA 控件（输入框）也跟着换了皮，不是一块白底压在墨纸上",
          dark23["box"][0] != "rgb(250, 247, 241)", True)
    # 用户自己选死「亮色」→ 系统再怎么夜里也不许翻（用户的选择压过系统）
    page.evaluate("() => { THEME.set('theme', 'light'); }")
    page.wait_for_timeout(250)
    check("「册」里选了亮色：系统夜里也不翻（用户的选择压过系统）",
          page.evaluate("() => [document.documentElement.dataset.theme,"
                        " getComputedStyle(document.body).backgroundColor]"),
          ["light", "rgb(244, 239, 230)"])
    page.evaluate("() => { THEME.set('theme', 'auto'); }")
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(250)
    check("系统回到白天：纸也跟着回到那张米色的（不是翻过去就不回来）",
          page.evaluate("() => [document.documentElement.dataset.theme,"
                        " getComputedStyle(document.body).backgroundColor]"),
          ["light", "rgb(244, 239, 230)"])

    print("\n--- 24. 笺册那一行点得动：复制的是当时那整张笺 ---")
    # 把 copy 换成记录用的桩：file:// 不是安全上下文，真剪贴板不一定给，
    # 而这里要看的是「交出去的那段字是什么」，不是「操作系统收没收到」。
    page.evaluate("""() => {
      state.points = 60; save(state);
      window.__copied = [];
      window.copy = (t, m) => { window.__copied.push([t, m]); };
    }""")
    # 味笺：笺册那行必须与结果页「复制这段话」逐字相同。
    # （话术是 join("") 出来的一整句，所以不能拿「有没有换行」当判据，只能两边对字。）
    # #copyWei 是 paintWei 画进 #weiResult 的，而 #weiResult 在 #weiPanePlan 里：
    # 停在别的页签上 `page.click("#copyWei")` 会因为不可见而超时。
    wei_tab(page, "plan")
    page.evaluate("() => { document.querySelector('#menu').value = '宫保鸡丁\\n蒜蓉西兰花\\n白切鸡\\n米饭'; }")
    page.evaluate("() => runWei()")
    page.wait_for_function("() => state.album.some(a => a.type === 'wei' && a.text)", timeout=20000)
    page.click("#copyWei")
    live, stored = page.evaluate(
        "() => [window.__copied.at(-1)[0], state.album.find(a => a.type === 'wei').text]")
    check("味笺那行存的就是结果页复制的那段话术", [live, live == stored and len(live) > 8], [stored, True])
    # 衣笺：笺册那行与报告页的「复制这段话」必须一字不差
    same = page.evaluate("""() => {
      const a = state.album.find(x => x.type === 'yi');
      return !!a && a.text === reportText(state.lastReport) && a.text.indexOf(state.lastReport.stamp) >= 0;
    }""")
    check("衣笺那行 == 报告页会复制的那段（含当时的结论章）", same, True)
    page.evaluate("() => show('me')")
    tags = page.eval_on_selector_all("#album .slip", "els => els.map(e => e.tagName)")
    check("笺册每一行都是真按钮（键盘 Tab 走得到）", set(tags), {"BUTTON"})
    # 不用 inner_text（那是个等待定位器：元素没了就抛超时，报告只能说「崩在无断言处」）。
    # 取不到要点名「不在了」，第 29 轮那条「× 塞回卡片里」的注入才有脸说出自己炸在哪。
    check("行上写着能再复制", page.evaluate(
        "() => { const e = document.querySelector('#album .slip .slip-copy');"
        " return e ? e.textContent.trim() : '（卡片里没有那一行了）'; }"), "再复制")
    # 点的是衣笺那一行：味笺那行的 text 与 quote 本来就相同，拿它测「复制的是整张笺」是白测
    yi_at = page.evaluate("() => state.album.findIndex(a => a.type === 'yi')")
    page.click("#album [data-slip='%d']" % yi_at)
    # 取最后一次：上面「复制这段话」也走同一个桩，__copied 里前面几条是它的
    got = page.evaluate("() => window.__copied.at(-1) || []")
    want = page.evaluate("() => state.album[%d].text" % yi_at)
    check("点衣笺那一行复制出去的是整张笺（不是标题那一句）",
          bool(got) and got[0] == want and "\n" in want, True)
    check("提示说的是这一张", got[1] if len(got) > 1 else "", "已复制这一张笺")
    # 升级之前的老数据只有标题：不许复制出一句空话
    page.evaluate("""() => {
      state.album = [{ type: 'yi', t: Date.now(), quote: '只有标题的一张旧笺' }];
      window.__copied = []; save(state); show('me');
    }""")
    page.click("#album [data-slip]")
    old = page.evaluate("() => window.__copied")
    check("旧条目没有 text 时退回标题，不复制出空白", bool(old) and old[0][0] == "只有标题的一张旧笺", True)
    page.evaluate("() => { delete window.__copied; delete window.copy; }")

    print("\n--- 25. 衣笺闭环：判完那一下，东西要能进柜子 ---")
    # 这一节从「过笺」开始（runYi 要 #fileNew 那一套），但中途要量的是柜子：
    # `document.querySelector('#closet .item[data-id]').dataset.id` 与 #dropIt。
    # 0.6.0 里 reportToCloset 会自己 setYiTab('closet')（见 wardrobe.js），
    # 但本节开头那一发 runYi 走的是过笺页签，所以两边都要显式摆对。
    yi_tab(page, "pass")
    page.evaluate("() => { delete window.JIAN_CONFIG.endpoint; }")
    before = page.evaluate("() => state.wardrobe.length")
    page.evaluate("async () => { const f = await window.__mk('#7f8fa6', 'coat.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport && state.lastReport.new", timeout=20000)
    page.wait_for_timeout(300)
    check("报告页有「记进柜子」，而且现在点得动", page.evaluate(
        "() => { const b = document.querySelector('#toCloset'); return [b.textContent, b.getAttribute('aria-disabled') === 'true']; }"),
        ["记进柜子", False])
    page.click("#toCloset")
    page.wait_for_timeout(400)
    # reportToCloset() 只 show('yi')，**不切页签**（0.6.0 里衣笺有四个页签）。
    # 入柜的结果全在柜子那一页上：#closet 的瓷砖、#clothActions 的名字框、#dropIt。
    # 不切过去，下面 `page.click("#dropIt")` 会因为「element is not visible」白等 30 秒。
    yi_tab(page, "closet")
    after = page.evaluate("""() => [state.wardrobe.length, state.wardrobe[0].id, state.clothSel,
      document.querySelector('.screen.on').id,
      document.querySelector('#closet .item[data-id]').dataset.id,
      document.querySelector('#clothName') ? document.querySelector('#clothName').value : null,
      state.wardrobe[0].name]""")
    check("柜里多了一件", after[0], before + 1)
    # 注意：网格是按「常穿」排的，新件 worn=0 不会排第一——别把插入序当成显示序。
    # 这里要的是「用户看得见刚入的那件」：它在网格里、带着 .sel 高亮。
    check("新件在网格里且带着选中高亮", page.evaluate(
        "() => { const el = document.querySelector('#closet .item.sel');"
        " return !!(el && el.dataset.id === state.wardrobe[0].id); }"), True)
    check("选中的就是刚入的这件（改名框就在下面）", after[2], after[1])
    check("落回衣笺那一屏", after[3], "yi")
    check("名字框里就是它的名字", after[5], after[6])
    check("按钮自己变成「已在柜里」并且点不动", page.evaluate("""() => {
      paintReport(); const b = document.querySelector('#toCloset');
      return [b.textContent, b.getAttribute('aria-disabled') === 'true'];
    }"""), ["已在柜里", True])
    # 先验撤销：任何一句新 toast 都会顶掉带「撤销」的那条，所以它必须趁活着的时候点
    page.evaluate("() => document.querySelector('.toast.act button').click()")
    page.wait_for_timeout(300)
    check("撤销之后柜里回到原样", page.evaluate("() => state.wardrobe.length"), before)
    check("撤销之后按钮又活了", page.evaluate(
        "() => { paintReport(); const b = document.querySelector('#toCloset'); return [b.textContent, b.getAttribute('aria-disabled') === 'true']; }"),
        ["记进柜子", False])
    # 重复点不许再加第二件（标 aria-disabled 之外，函数里还得再挡一次并说一句）
    page.evaluate("() => { reportToCloset(); reportToCloset(); reportToCloset(); }")
    check("连点三次也只加一件", page.evaluate("() => state.wardrobe.length"), before + 1)
    # 入柜 → 再从柜子里删掉：按钮必须活回来（存布尔就会一直谎称「已在柜里」）
    page.evaluate("() => reportToCloset()")
    page.wait_for_timeout(250)
    newid = page.evaluate("() => state.lastReport.closetId")
    page.evaluate("() => { state.clothSel = state.lastReport.closetId; renderCloset(); }")
    page.click("#dropIt")
    page.wait_for_timeout(300)
    check("柜里那件被删掉了", page.evaluate("() => state.wardrobe.some(w => w.id === '%s')" % newid), False)
    check("删掉之后报告页的按钮活回来", page.evaluate("""() => {
      show('yi-report'); paintReport(); const b = document.querySelector('#toCloset');
      return [b.textContent, b.getAttribute('aria-disabled') === 'true'];
    }"""), ["记进柜子", False])
    # 带着一条搜索入柜：新件多半不匹配那个词，会被筛到看不见，用户看到的就是「点了没反应」
    # 这一段两次切换都要显式摆页签：reportToCloset 自己只 show('yi')，
    # #clothSearch 在 #yiPaneCloset 里（hidden 时 page.input_value 仍读得到，
    # 但那正是「假绿」的形状——量的是看不见的框；所以先切过去再量）。
    yi_tab(page, "closet")
    page.evaluate("() => { document.querySelector('#clothSearch').value = '蓝'; renderCloset(); }")
    page.evaluate("() => { show('yi-report'); reportToCloset(); }")
    yi_tab(page, "closet")
    page.wait_for_timeout(300)
    check("入柜这一下顺手清掉了搜索", page.input_value("#clothSearch"), "")
    check("清掉之后新件就在网格里了", page.evaluate("() => !!document.querySelector('#closet .item.sel')"), True)
    # 没有照片的旧报告：这枚要标成「此刻不许用」，并且按下去说得出为什么（不是静默）
    page.evaluate("() => { state.lastReport = { stamp: '宜入', quote: 'x' }; save(state); show('yi-report'); paintReport(); }")
    check("没有可记的照片时那枚被挡（标 aria-disabled，仍可聚焦、按下去会说话）",
          page.evaluate("() => { const b = document.querySelector('#toCloset');"
                        " return [b.getAttribute('aria-disabled'), b.disabled]; }"), ["true", False])
    page.evaluate("() => { state.lastReport = null; save(state); renderCloset(); }")

    print("\n--- 26. 味笺那一桌要留得住：切走、重开都还在 ---")
    # #demoWei / #runWei / #weiResult / #menu 全在 #weiPanePlan 里，先摆到排桌页签。
    wei_tab(page, "plan")
    page.evaluate("() => { state.points = 40; save(state); }")
    page.click("#demoWei")
    page.click("#runWei")
    wait_ok("() => state.lastWei && state.lastWei.r", 20000, "上一桌的判定回到屏上（lastWei.r 有货）")
    page.wait_for_timeout(300)
    check("排完有结果那张笺", page.is_visible("#weiResult .sheet"), True)
    # 「切去衣笺再回来」这一段正是页签存在之后最容易被量错的一格：
    # 回来之后如果停在别的味笺页签上，#weiResult 是 hidden，`is_visible` 会假红。
    page.evaluate("() => show('yi')")
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    check("切去衣笺再回来，结果还在", page.is_visible("#weiResult .sheet"), True)
    page.reload()
    page.wait_for_timeout(900)
    wei_tab(page, "plan")
    page.wait_for_timeout(400)
    sheet = page.evaluate("() => document.querySelector('#weiResult .sheet').textContent")
    check("整页重开之后结果还在（不是只活在 DOM 里）", bool(sheet.strip()), True)
    check("上面写着这是什么时候的哪一桌", ("排的一桌" in sheet) and ("道" in sheet), True)
    shown_n = page.evaluate(
        "() => { const m = document.querySelector('#weiResult .sheet').textContent.match(/(\\d+) 人 ·/); return m ? +m[1] : null; }")
    check("人数用的是当时那一桌的数（屏上 vs 存的）", shown_n, page.evaluate("() => Number(state.lastWei.n)"))
    check("菜单文本也活过了重开（不然「改过了」那句是谎话）", page.input_value("#menu"),
          page.evaluate("() => state.lastWei.menu"))
    check("「复制这段话」也回来了", page.is_visible("#copyWei"), True)
    # 改了菜单：结果就是旧的了，要说出来
    page.evaluate("() => { const el = document.querySelector('#menu'); el.value += '\\n宫保鸡丁'; el.dispatchEvent(new Event('input')); }")
    page.wait_for_timeout(200)
    check("改过菜单之后亮出「这张还是上一版的」", page.evaluate(
        "() => document.querySelector('#weiStale').style.display"), "flex")
    check("提示里给了重排的入口", page.is_visible("#reWei"), True)
    pts = page.evaluate("() => state.points")
    page.click("#reWei")
    page.wait_for_function("() => state.lastWei.menu.indexOf('宫保鸡丁') >= 0", timeout=20000)
    page.wait_for_timeout(300)
    check("重排是一次新判定：照常扣一点", page.evaluate("() => state.points"), pts - 1)
    check("重排之后提示收起来了", page.evaluate(
        "() => document.querySelector('#weiStale').style.display"), "none")
    check("新菜进了结果", page.evaluate("() => /宫保鸡丁/.test(document.querySelector('#weiResult').textContent)"), True)
    # 外来的备份能往 lastWei 里塞任意 JSON：不能让它把这一屏弄崩
    page.evaluate("""() => {
      const bad = Object.assign({}, state, { lastWei: '不是桌' });
      cancelSoon();   // 测试也是「绕过 save() 直接写盘」的一方：不取消排在前面的防抖，它会把旧 state 盖回来
      localStorage.setItem('jian.v1', JSON.stringify(bad));
    }""")
    stored = page.evaluate("() => typeof JSON.parse(localStorage.getItem('jian.v1')).lastWei")
    page.reload()
    page.wait_for_timeout(900)
    # reload 回到过笺；这里问的是味笺的引导空态，#weiResult 在排桌页签里。
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    check("写进去的确实是脏值（否则这条是白测）", stored, "string")
    check("normalizeState 把脏的 lastWei 丢掉了", page.evaluate("() => state.lastWei === undefined"), True)
    check("味笺回到引导而不是崩", page.evaluate("() => !!document.querySelector('#weiResult .empty')"), True)

    # 外面那一层收干净了不算完：r 里每个字段都是画的时候逐个 .map 的。
    # "boom": {} 是 truthy，paintWei 会在一个对象上取 .map —— 整屏空白，而且不报错。
    page.evaluate("""() => {
      const r = Engine.wei('米饭\\n宫保鸡丁', [{ name: '我', chips: ['辣'] }]);
      const bad = Object.assign({}, state, { lastWei: {
        menu: '米饭', t: Date.now(), n: 1, talk: '这一桌',
        r: Object.assign({}, r, { boom: {}, notes: '一段话', safe: null, inferred: ['辣|有人不吃辣'] }) } });
      cancelSoon();   // 同上：不取消排在前面的防抖，它会把旧 state 盖回来
      localStorage.setItem('jian.v1', JSON.stringify(bad));
    }""")
    page.reload()
    page.wait_for_timeout(900)
    try:
        # 排桌页签：#weiResult .sheet 只长在 #weiPanePlan 里，停在别处时 is_visible 恒 False，
        # 那会把「脏值把这一屏弄崩了」误报成真的崩了。
        wei_tab(page, "plan")
        page.wait_for_timeout(300)
        check("r 里不是数组的字段被丢掉，不留给 paintWei 去 map", page.evaluate(
            "() => ['boom', 'notes', 'safe'].filter(k => k in state.lastWei.r).join()"), "")
        check("inferred 里来路不明的字符串也清掉（画的时候要取 .chip）", page.evaluate(
            "() => state.lastWei.r.inferred.length"), 0)
        check("洗完之后这一桌照旧画得出来", page.is_visible("#weiResult .sheet"), True)
    except Exception as e:
        # 整段都在 try 里：脏值没清干净时先炸的是 boot / show，只包 check 的话又只剩「崩了」
        print("        这一桌在启动时就炸了：" + str(e).splitlines()[0][:130])
        check("r 里的脏字段没让味笺崩掉", False, True)

    print("\n--- 26b. 外来的言笺条目与笺册也洗一遍：脏值的症状不是崩，是数不对 ---")
    # 三处注入都咬在这段上：k 认不出、line 不是话、when 不是对象。
    # 屏上不会报错，只会头上写 6 条、行上只有 4 行，复制出来那句带着（undefined）。
    page.evaluate("""() => {
      const bad = Object.assign({}, state, {
        yanCards: [
          { k: '外星', line: '买牛奶' },
          { k: '待办', line: 123 },
          { k: '要买', line: '   ' },
          { k: '待办', line: '交房租', when: '明天', done: 'no' },
          { k: '已定', line: '周五见', when: { text: '明天', at: 'abc' } },
          { k: '待办', line: '真待办', when: { text: '后天', at: 1758123456000 }, wset: true },
        ],
        album: [null, '一张笺', { type: 'yi', t: 'abc', quote: { a: 1 } },
          { type: 'yan', t: 1758000000000, quote: '好的', text: '一整张言笺' }],
      });
      cancelSoon();   // 同 26 节：不取消排在前面的防抖，旧 state 会把这份脏备份盖回去
      localStorage.setItem('jian.v1', JSON.stringify(bad));
    }""")
    page.reload()
    # 这句是 boot 里弹的（活 5.2 秒）：固定等 900ms 在忙机器上会读在「还没弹出来」那一刻
    wait_toast("言笺少 2 条", 12000, "开机那句「丢了几条」")
    # 0.5.x 的这句话是按集合逐个手写的，笺册那一段用的是「少 N **张**」
    # （`bootNotes.push([normLoss.cards ? \`言笺少 ${n} 条\` : "", normLoss.album ? \`笺册少 ${n} 张\` : ""])`）。
    # 0.6.0 把它收成了一张表（app.js 里 `names = { cards: "言笺", album: "笺册", … }`）
    # 和一个模板 `${names[k]}少 ${n} 条`——九个新集合统一成一个量词「条」，
    # 笺册因此从「3 张」变成「3 条」。断言要守的是**「说了少几条、说的是哪个集合」**，
    # 不是量词该用哪个字，所以期望值跟着改，并且把「两个集合都点名、数目都对」钉死。
    check("开机就把丢掉的条数说在脸上",
          ["言笺少 2 条" in toast_text(), "笺册少 3 条" in toast_text()], [True, True])
    check("认不出的类别进了「还没说清」而不是蒸发", page.evaluate("() => state.yanCards.map(c => c.k).join()"),
          "还没说清,待办,已定,待办")
    check("两条读不懂的条目被丢掉，四条留下", page.evaluate("() => state.yanCards.length"), 4)
    page.evaluate("() => { state.yanView = 'kind'; show('yan'); renderYan(); }")
    page.wait_for_timeout(300)
    ytxt = page.inner_text("#yanOut")
    check("屏上行数与头上的条数对上", page.evaluate("() => document.querySelectorAll('#yanOut .check').length"), 4)
    check("头上那行写的就是 4 条", page.evaluate("() => document.querySelector('#yanOut .bar p.tiny').textContent"), "4 条 · 已勾 0")
    check("屏上没有 [object Object]", "[object" in ytxt, False)
    check("「买牛奶」这一条看得见（以前它根本进不了任何一组）", "买牛奶" in ytxt, True)
    check("done 是字符串「no」的不算已勾", page.evaluate("() => document.querySelectorAll('#yanOut input:checked').length"), 0)
    check("复制整张笺里没有 undefined", "undefined" in page.evaluate("() => yanText()"), False)
    check("手动定过的时间活过重开", page.evaluate("() => [state.yanCards[3].wset, state.yanCards[3].when.text]"), [True, "后天"])
    check("那一条的行上标着「已定时」", page.evaluate("""() => [...document.querySelectorAll('#yanOut .check')]
      .find((e) => e.textContent.includes('真待办')).querySelector('.wtimer').textContent"""), "已定时")
    page.evaluate("() => { state.yanView = 'time'; renderYan(); }")
    page.wait_for_timeout(250)
    check("脏 when 不再写出 NaN 的分组标题", "NaN" in page.inner_text("#yanOut"), False)
    check("when 不是对象的那条进了「没写时间」", "没写时间" in page.inner_text("#yanOut"), True)
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    atxt = page.inner_text("#album")
    check("笺册只留下画得出的一行（null 没让整屏抛出去）", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 1)
    check("笺册里没有 [object Object]", "[object" in atxt, False)
    check("脏 t 没写出 NaN 的日期", "NaN" in atxt, False)
    check("洗完之后「我的」还是全的（笺点那一栏在）", page.is_visible("#points"), True)

    print("\n--- 27. 排过的桌：拿回来重排，不必翻聊天记录找菜单 ---")
    # #menu / #weiHist / #runWei / #weiStale 都在 #weiPanePlan 里：这一节要点
    # `#weiHist [data-hist='0']`，停在别的页签上会直接超时。
    # 顺序要紧：先把 state 摆好，再 wei_tab()——setWeiTab('plan') 里那一手 renderWei()
    # 才会拿新的空 weiHist 重画那一栏。先切页签再改 state，屏上留的是上一节的旧栏
    # （「一桌都没排过时这一栏根本不出来」就是这么红起来的）。
    page.evaluate("""() => {
      state.points = 90; state.weiHist = [];
      state.people = [{ name: '我', chips: ['辣'] }, { name: '小周', chips: ['蒜', '辣'] }];
      save(state); renderWeiPeople();
    }""")
    wei_tab(page, "plan")
    page.wait_for_timeout(250)
    check("一桌都没排过时这一栏根本不出来",
          page.evaluate("() => document.querySelector('#weiHist').style.display"), "none")

    def run_table(menu):
        page.evaluate("(m) => { const el = document.querySelector('#menu'); el.value = m; runWei(); }", menu)
        page.wait_for_function("(m) => state.lastWei && state.lastWei.menu === m", timeout=20000, arg=menu)
        page.wait_for_timeout(250)
        return page.eval_on_selector_all("#weiHist [data-hist]", "els => els.map(e => e.textContent.trim())")

    labels = run_table("宫保鸡丁\n白切鸡\n米饭")
    check("排完一桌就记了一笔", len(labels), 1)
    check("签上写着几个人、几道菜", ("2 人" in labels[0]) and ("3 道" in labels[0]), True)
    check("签上不写忌口（写了实测 277px 宽，360 的一行只放得下一枚）", "忌" in labels[0], False)
    page.evaluate("""() => {
      state.people.push({ name: '阿姨', chips: ['海鲜'] });
      save(state); renderWeiPeople();
    }""")
    labels = run_table("清蒸鲈鱼\n白灼菜心\n米饭\n紫菜蛋花汤")
    check("换一桌就是两枚，新的在最前", len(labels), 2)
    check("最前面那枚是刚刚那一桌：3 个人、4 道菜", ("3 人" in labels[0]) and ("4 道" in labels[0]), True)
    labels = run_table("宫保鸡丁\n白切鸡\n米饭")
    check("同一桌再排一次不留两行", len(labels), 2)
    check("但那一次挪到了最前", ("3 道" in labels[0]) and ("4 道" in labels[1]), True)
    check("记的是当时那一桌的人数（不是屏幕此刻的人数）",
          page.evaluate("() => state.weiHist.map(h => h.n)"), [3, 3])
    # 忌口没丢：点的那一下才说（那才是用得到它的时刻），超过两项收进「等 N 项忌口」
    page.evaluate("() => { state.people = [{ name: '我', chips: ['辣', '蒜', '海鲜', '花生', '猪肉'] }]; save(state); renderWeiPeople(); }")
    run_table("白米饭\n清炒时蔬")
    page.click("#weiHist [data-hist='0']")
    page.wait_for_timeout(250)
    check("点的那一下说清这一桌忌口什么", page.inner_text(".toast"),
          "菜单拿回来了（忌 辣 蒜 等 5 项忌口）。要重排点「排这桌」")
    page.evaluate("() => { state.people = [{ name: '我', chips: [] }]; save(state); renderWeiPeople(); }")
    run_table("白米饭")
    page.click("#weiHist [data-hist='0']")
    page.wait_for_timeout(250)
    check("没人忌口那一桌就说没人忌口", page.inner_text(".toast"),
          "菜单拿回来了（没人忌口）。要重排点「排这桌」")

    # 点一签只是把菜单拿回来：重排是一次新判定、要扣点，得用户自己按
    pts = page.evaluate("() => state.points")
    want_menu = page.evaluate("() => state.weiHist[1].menu")
    page.click("#weiHist [data-hist='1']")
    page.wait_for_timeout(300)
    check("点一下就把那桌的菜单填回框里", page.input_value("#menu"), want_menu)
    check("拿回菜单不偷偷重排（笺点没动）", page.evaluate("() => state.points"), pts)
    check("结果就此变成上一版的：提示亮出来",
          page.evaluate("() => document.querySelector('#weiStale').style.display"), "flex")
    check("state.weiMenu 跟着改了（不然重开之后「改过了」是谎话）",
          page.evaluate("() => state.weiMenu"), want_menu)

    for i in range(9):
        run_table(f"米饭\n拿手菜{i}")
    check("只留最近 4 桌（再多就把「排这桌」推出屏幕）",
          page.eval_on_selector_all("#weiHist [data-hist]", "els => els.length"), 4)
    page.reload()
    page.wait_for_timeout(900)
    # reload 之后停在过笺；#weiHist 那一栏在排桌页签里，先摆回去再量行数。
    wei_tab(page, "plan")
    page.wait_for_timeout(400)
    check("整页重开之后这 4 桌还在", page.eval_on_selector_all("#weiHist [data-hist]", "els => els.length"), 4)

    # 备份能往 weiHist 里塞任意 JSON：不能让它把这一屏弄崩，也不能把脏值原样画出来
    page.evaluate("""() => {
      const bad = Object.assign({}, state, { weiHist: '不是桌' });
      cancelSoon();   // 测试也是「绕过 save() 直接写盘」的一方：不取消排在前面的防抖，它会把旧 state 盖回来
      localStorage.setItem('jian.v1', JSON.stringify(bad));
    }""")
    try:
        page.reload()
        page.wait_for_timeout(900)
        wei_tab(page, "plan")
        page.wait_for_timeout(300)
        check("整个是字符串的 weiHist 被收干净",
              page.evaluate("() => Array.isArray(state.weiHist) && state.weiHist.length === 0"), True)
        check("收干净之后这一栏不再出来",
              page.evaluate("() => document.querySelector('#weiHist').style.display"), "none")
    except Exception as e:
        # 脏值没清干净时，boot / show('wei') 里就抛了。整段都在 try 里：
        # 只把 check 包起来没用——先炸的是那一行 show('wei')，守门自检于是又只看到「崩了」。
        print("        这一屏在启动时就炸了：" + str(e).splitlines()[0][:130])
        check("整个是字符串的 weiHist 被收干净（脏值把这一屏弄崩了）", False, True)
    page.evaluate("""() => {
      const bad = Object.assign({}, state, { weiHist: [
        { menu: '米饭', n: '三', t: '昨天', chips: ['辣', '毒词', 3] },
        null, '一行字', { n: 2 }, { menu: '   ' }
      ] });
      cancelSoon();   // 测试也是「绕过 save() 直接写盘」的一方：不取消排在前面的防抖，它会把旧 state 盖回来
      localStorage.setItem('jian.v1', JSON.stringify(bad));
    }""")
    try:
        page.reload()
        page.wait_for_timeout(900)
        wei_tab(page, "plan")
        page.wait_for_timeout(300)
        cleaned = page.evaluate("() => state.weiHist")
        check("混在里面的脏条目只留下真是一桌的那条", len(cleaned), 1)
        check("人数不是数字就回落成 1", cleaned[0]["n"], 1)
        check("忌口只认那一组芯片里的词（不认识的词被丢掉了）", cleaned[0]["chips"], ["辣"])
        check("时间是脏值就落到当下（正数、不超过现在）",
              page.evaluate("() => Number.isFinite(state.weiHist[0].t) && state.weiHist[0].t > 0 && state.weiHist[0].t <= Date.now()"), True)
        check("脏值洗完之后这一栏照旧画得出来",
              page.eval_on_selector_all("#weiHist [data-hist]", "els => els.length"), 1)
    except Exception as e:
        # 这一段的 reload / show 也得包在里面：脏 weiHist 没被清掉时，先炸的是 boot，
        # 不是任何一条 check——只包 check 的话守门自检又只能报「e2e 崩了」。
        print("        这一屏在启动时就炸了：" + str(e).splitlines()[0][:130])
        check("混在里面的脏条目只留下真是一桌的那条（脏值把这一屏弄崩了）", False, True)

    print("\n--- 28. 季节这一层要走到底：报告页不许数落一件夏天的短袖 ---")
    # 第 26、27 节各 reload 过整页，__mk 是页面里注入的助手 → 重新装一次
    page.evaluate(MK)
    page.evaluate("""() => {
      const d = Date.now();
      state.wardrobe = [
        { id: 'h1', name: '白短袖T恤', cat: '上衣', color: '#f4f0ea', worn: 5, lastWorn: d - 200 * DAY, season: '夏' },
        { id: 'h2', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: d - DAY }
      ];
      state.lastReport = null; state.clothSel = null;
      save(state); renderCloset();
    }""")
    # 这一节两发 runYi 都在过笺页签里（runYi 要的是 #fileNew 那一套），
    # 而它量的东西在报告页上——所以开始前先摆回过笺。
    yi_tab(page, "pass")
    page.wait_for_timeout(300)
    page.evaluate("async () => { const f = await window.__mk('#f2eee7', 'tee.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport !== null", timeout=15000)
    page.evaluate("() => show('yi-report')")
    page.wait_for_timeout(350)
    rep = page.evaluate("() => ({ seasonal: !!state.lastReport.seasonal, stale: !!state.lastReport.stale })")
    note = page.inner_text("#reportNote")
    check("判定认这是季节性衣物", rep["seasonal"], True)
    check("久未穿那一层不再成立", rep["stale"], False)
    check("报告页说的是换季，不是数落「几个月没穿」",
          ("换季" in note) and ("个月没穿" not in note), True)
    check("但撞色这条没被放水：照样「先别」", page.evaluate("() => state.lastReport.stamp"), "先别")
    # 手选「四季」的那件就是常年穿的，不给它换季的台阶
    page.evaluate("""() => {
      const d = Date.now();
      state.wardrobe = [
        { id: 'h3', name: '打底长袖', cat: '上衣', color: '#f4f0ea', worn: 2, lastWorn: d - 200 * DAY, season: '四季' }
      ];
      state.lastReport = null; save(state); renderCloset();
    }""")
    page.wait_for_timeout(300)
    page.evaluate("async () => { const f = await window.__mk('#f2eee7', 'tee2.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport !== null", timeout=15000)
    page.evaluate("() => show('yi-report')")
    page.wait_for_timeout(350)
    check("手选四季的那件照旧说「几个月没穿」",
          ("个月没穿" in page.inner_text("#reportNote")) and (page.evaluate("() => !!state.lastReport.stale")), True)

    print("\n--- 29. 接上网关：认衣服与抄截图要走到底 ---")
    # 这一节用一台假网关（不是真供应商）：守门全套不能依赖密钥与网络，
    # 但「客户端把图缩了没有、模型给的名字有没有真的用上、抄回来的字有没有落进框里」
    # 这三件事只有走真 fetch 才测得到，所以在这里起一个本地 HTTP 桩。
    mark29 = len(errors)   # 这一节要故意打不通的端点，回声单独算
    calls = []
    gets = []         # GET 单独数：/v1/status 一共问了几个，重试那条要看它
    flaky = [0]       # >0 时前 N 次 /v1/status 不回话直接掐连接，模拟「头一次没通」
    hang = [0]        # >0 时下一笔 /v1/recognize 先挂这么多秒才回，验「先不等了」用

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            gets.append(self.path)
            if self.path.endswith("/v1/status") and flaky[0] > 0:
                # 不回话、直接掐：客户端拿到的就是 Failed to fetch，和设备上冷启动
                # 头一次出网挤掉预算那一档一样。
                flaky[0] -= 1
                self.close_connection = True
                return
            self._send(200, {"ok": True, "model": {"on": True, "model": "stub-1"},
                             "tasks": {"recognize": True, "ocr": True}})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = json.loads(self.rfile.read(n) or b"{}")
            img = str(raw.get("image") or "")
            calls.append((self.path, len(img), img))
            if self.path.endswith("/v1/recognize") and hang[0] > 0:
                # 挂这么多秒才回。客户端早就 abort 走了，所以这一笔是「迟到的回话」——
                # 它到了也不许把已经摆在屏幕上的结果盖掉。
                secs = hang[0]
                hang[0] = 0
                time.sleep(secs)
            if self.path.endswith("/v1/recognize"):
                self._send(200, {"name": "针织开衫", "cat": "外套", "color": "#C9B89A",
                                 "season": "春秋", "source": "model", "model": "stub-1"})
            elif self.path.endswith("/v1/ocr"):
                self._send(200, {"text": "明天下午记得把材料发我" + chr(10) + "那就周五见吧。",
                                 "model": "stub-1"})
            else:
                self._send(404, {"error": "unknown"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    srv.request_queue_size = 128
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # 反过来也要成立：没填网关的时候没有任何东西可等，那颗按钮不该出现在屏幕上。
        # 断言看的是「看不看得见」（offsetParent），不是 .hidden 属性——
        # 只查属性的话，少一条 .veil-off[hidden]{display:none} 也能照样绿。
        check("没填网关时不给「先不等了」（没得可等就别给按钮）",
              page.evaluate("""() => {
                veil(true, '在算…');
                const vis = !!document.querySelector('#veilOff').offsetParent;
                veil(false); return vis;
              }"""), False)
        page.evaluate("(p) => { state.apiUrl = 'http://127.0.0.1:' + p;"
                      " window.JIAN_CONFIG.endpoint = state.apiUrl; gwReset();"
                      " state.points = 40; save(state); }", port)
        page.reload()
        page.wait_for_timeout(900)
        page.evaluate(MK)   # reload 会把页面里注入的 __mk 助手带走
        page.evaluate("() => show('me')")
        page.wait_for_timeout(1200)
        am = page.inner_text("#apiModel")
        print("        " + am)
        check("「册」里说得出这台网关能干什么、是哪只模型",
              ("stub-1" in am) and ("可用" in am), True)

        # 这一发 runYi 走「过笺」页签（#fileNew 与 #yiCats 那一排都在 #yiPanePass 里）。
        page.evaluate("() => { state.yiCat = '上衣'; state.lastReport = null; save(state); }")
        yi_tab(page, "pass")
        page.wait_for_timeout(250)
        page.evaluate("async () => { const f = await window.__mk('#b69f88', 'knit.png'); runYi(f); }")
        page.wait_for_function("() => state.lastReport && state.lastReport.new && state.lastReport.new.seen",
                               timeout=25000)
        it = page.evaluate("() => state.lastReport.new")
        check("认出来的名字真的用上了（不再是「想买的这件」）", it["name"], "针织开衫")
        check("品类跟着认的结果走（上衣 → 外套）", it["cat"], "外套")
        check("主色仍用本机量的那一个，没被模型的色串改",
              (it["color"].startswith("#") and len(it["color"]) == 7
               and it["color"].lower() != "#c9b89a"), True)
        check("报告附注说得出是谁认的", "认出来的是" in page.inner_text("#reportNote"))
        rec = [c for c in calls if c[0].endswith("/v1/recognize")]
        sent = rec[-1][1] if rec else 0
        print("        发给网关的图：data URL " + str(sent) + " 字符")
        check("发出去的图在合理大小（1.5KB ~ 120KB）", 1500 < sent < 120000, True)

        def img_edge(data_url):
            """把网关真收到的那张图交回浏览器量长边。
            量字节猜不出缩没缩（600x800 缩到 512 边也就 3KB，两者落在同一区间）；
            而钉 shrink(f,512) 与 shrink(f,4000) 谁大，比的是传进去的参数，
            调用方用的却是默认值——把默认值改掉这道门照旧绿（这一版就瞎在这儿）。
            契约写的是「缩到 512 边」，那就量发出去那张图的长边。"""
            return page.evaluate(
                "(u) => new Promise((res) => { const i = new Image();"
                " i.onload = () => res(Math.max(i.naturalWidth, i.naturalHeight));"
                " i.onerror = () => res(-1); i.src = u; })", data_url)

        edge = img_edge(rec[-1][2]) if rec else -1
        print("        认衣服发出去的图：长边 " + str(edge) + " px（测试原图 600x800）")
        check("认衣服前真的把图缩到 512 边以内", 0 < edge <= 512, True)
        # 这一条钉的是 shrink 认不认它收到的宽度参数——ocr 传 768 靠的就是这个。
        cmp = page.evaluate("""async () => {
          const f = await window.__mk('#b69f88', 'knit.png');
          const a = await JianAPI.shrink(f, 512);
          const b = await JianAPI.shrink(f, 4000);
          return { a: a.length, b: b.length };
        }""")
        print("        shrink 512 → " + str(cmp["a"]) + " 字符；shrink 4000 → " + str(cmp["b"]) + " 字符")
        check("上传前真的在缩图（不是把原图直接发出去）", cmp["a"] < cmp["b"], True)

        page.evaluate("() => { show('yan'); document.querySelector('#yanText').value = '';"
                      " state.yanCards = []; save(state); }")
        page.wait_for_timeout(250)
        page.set_input_files("#fileYanImg", str(JIAN / "test" / "test-photo.jpg"))
        wait_ok("() => document.querySelector('#yanText').value.length > 5", 25000,
                "抄回来的字落进聊天框（点了像没反应）")
        box = page.input_value("#yanText")
        print("        抄回：" + repr(box[:70]))
        check("抄回来的字落进了聊天框", ("材料发我" in box) and ("周五见" in box), True)
        oc = [c for c in calls if c[0].endswith("/v1/ocr")]
        oedge = img_edge(oc[-1][2]) if oc else -1
        print("        抄截图发出去的图：长边 " + str(oedge) + " px（测试原图 600x800）")
        check("抄截图前把图缩到 768 边以内（比 512 宽一档，字才认得出）", 0 < oedge <= 768, True)
        page.evaluate("() => runYan()")
        page.wait_for_function("() => (state.yanCards || []).length >= 2", timeout=25000)
        check("截图抄完能直接捞成笺", page.evaluate("() => state.yanCards.length"), 2)

        # 网关说它不行：判定照旧要出得来，出处要说明白
        page.evaluate("() => { window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9';"
                      " state.apiUrl = 'http://127.0.0.1:9'; gwReset(); save(state); }")
        page.reload()
        page.wait_for_timeout(900)
        page.evaluate(MK)
        # 这一发 runYi 走的是过笺页签（0.6.0 默认就是 pass，但上面几节把页签挪走过）。
        page.evaluate("() => { state.lastReport = null; state.points = 40; save(state); }")
        yi_tab(page, "pass")
        page.wait_for_timeout(250)
        page.evaluate("async () => { const f = await window.__mk('#b69f88', 'knit2.png'); runYi(f); }")
        page.wait_for_function("() => state.lastReport && state.lastReport.new", timeout=25000)
        page.wait_for_timeout(700)
        check("网关连不上时判定照旧出得来", bool(page.evaluate("() => state.lastReport.stamp")))
        check("连不上就不谎称认过", page.evaluate("() => !state.lastReport.new.seen"), True)
        page.evaluate("() => show('me')")
        page.wait_for_timeout(1200)
        am2 = page.inner_text("#apiModel")
        print("        " + am2)
        check("「册」里说得出网关连不上", "连不上" in am2, True)

        # --- 连不上一次之后，30 秒内不再撞第二次 ---
        # 这里刻意不用 127.0.0.1:9：那端口是「秒失败」，等不等冷都在 0.0 秒，
        # 时间断言根本分不出「躲开了」和「又撞了一次但立刻死」。所以换成一台
        # **收了连接但不回话**的桩（hang），并把客户端预算临时压到 2 秒：
        # 第一张必须真的等满那 2 秒，第二张必须几乎立刻、而且一笔都不发出去。
        page.evaluate("(b) => { window.JIAN_CONFIG.endpoint = b; state.apiUrl = b;"
                      " window.JIAN_CONFIG.seeMs = 2000; window.JIAN_CONFIG.timeoutMs = 2000;"
                      " gwReset(); save(state); }", f"http://127.0.0.1:{port}")
        page.wait_for_timeout(200)
        rec_before = len([c for c in calls if c[0].endswith("/v1/recognize")])
        hang[0] = 6
        page.evaluate("async () => { state.points = 40; state.lastReport = null; save(state);"
                      " const f = await window.__mk('#b69f88', 'cold1.png'); runYi(f); }")
        t0 = time.time()
        page.wait_for_function("() => !!(state.lastReport && state.lastReport.stamp)", timeout=20000)
        spent1 = round(time.time() - t0, 2)
        page.evaluate("async () => { state.points = 40; state.lastReport = null; save(state);"
                      " const f = await window.__mk('#b69f88', 'cold2.png'); runYi(f); }")
        t0 = time.time()
        page.wait_for_function("() => !!(state.lastReport && state.lastReport.stamp)", timeout=20000)
        spent2 = round(time.time() - t0, 2)
        print(f"        第一张等满超时 {spent1}s，第二张 {spent2}s")
        check("第一张确实为那台不回话的网关等过一次", 1.2 <= spent1 <= 4.5, True)
        check("第二张不再重等超时（30 秒内躲开它）", spent2 < 0.8, True)
        check("第二张连一笔都没发出去（不是又撞了个快的）",
              len([c for c in calls if c[0].endswith("/v1/recognize")]), rec_before + 1)
        check("出处记着这是在冷却期里，不是「没填地址」",
              (json.loads(page.evaluate("() => JSON.stringify(JianAPI.status())")) or {}).get("cold", 0) > 0, True)
        page.evaluate("() => show('me')")
        page.wait_for_timeout(300)
        stt = page.inner_text("#apiState")
        print("        " + stt)
        # 只查「连不上」+「本地规则算的」是一断言两意：冷却分支被摘掉之后，
        # 状态会落到「最近一笺（…）没通（<那句冷却话术>）——那笺是本地规则算的」，两个词它都还在。
        # 所以要钉一句只有倒计时那句话才有的话：还剩几秒、以及改地址立刻再试。
        check("「册」说得出还在冷却第几秒、以及改地址会立刻再试",
              "秒内的笺是本地规则算的" in stt and "改地址会立刻再试" in stt, True)
        check("改过地址就立刻愿意再试一次（不是一棍子打死）",
              page.evaluate("() => { const a = JianAPI.wantsRemote(); gwReset();"
                            " return [a, JianAPI.wantsRemote()]; }"), [False, True])
        # 预算恢复原样，后面那两节（重试、先不等了）要按生产的数值跑
        page.evaluate("() => { window.JIAN_CONFIG.seeMs = 45000; window.JIAN_CONFIG.timeoutMs = 20000; }")

        # 反过来：一次没问通，也不许把一台够得着的网关永远说成够不着。
        # 设备上实测过——冷启动的头一次出网能慢到把预算挤掉，界面于是永远挂着「连不上」，
        # 那是「已指向网关」那笔假账的反面。所以失败之后要再问一次；
        # 但也只许多问这一次，真死的网关不能被无限敲。
        flaky[0] = 1
        before = len(gets)
        page.evaluate("(p) => { state.apiUrl = 'http://127.0.0.1:' + p;"
                      " window.JIAN_CONFIG.endpoint = state.apiUrl; gwReset(); save(state); }", port)
        page.reload()
        page.wait_for_timeout(900)
        page.evaluate(MK)
        page.evaluate("() => show('me')")
        try:      # 第一笔被桩掐掉，中间那一瞬界面上确实会闪一下「连不上」，别拿那一瞬当结论
            page.wait_for_function(
                "() => document.querySelector('#apiModel').textContent.includes('在线')", timeout=30000)
        except Exception:
            pass
        am3 = page.inner_text("#apiModel")
        print("        " + am3)
        check("头一次没问通还会再问一次，界面最终落到「在线」", "在线" in am3, True)
        asked = len([g for g in gets[before:] if g.endswith("/v1/status")])
        print("        这一轮一共问了 " + str(asked) + " 次 /v1/status")
        check("只多问那一次（真死的网关不会被无限敲）", asked, 2)

        # --- 「先不等了」：等远端的时候不许把用户关在遮罩外面 ---
        # 模型认一件实测 2.6~14 秒，而本地引擎几十毫秒就能出判定。桩这里挂 4 秒不回话，
        # 按了放弃之后必须马上拿到本地结果，并且这一轮**不再试第二枪**（判定那一枪也不发）。
        hang[0] = 4
        see_before = len([c for c in calls if c[0].endswith("/v1/see")])
        page.evaluate("() => { state.lastReport = null; state.points = 40; save(state); }")
        yi_tab(page, "pass")
        page.wait_for_timeout(250)
        page.evaluate("async () => { const f = await window.__mk('#b69f88', 'slow.png'); runYi(f); }")
        page.wait_for_function("() => document.querySelector('#veil').classList.contains('on')",
                               timeout=8000)
        check("等远端时遮罩说得出在等什么", "在认这件" in page.inner_text("#veilWhat"), True)
        check("这时候「先不等了」是露出来的",
              page.evaluate("() => !document.querySelector('#veilOff').hidden"), True)
        t0 = time.time()
        page.evaluate("() => document.querySelector('#veilOff').click()")
        try:
            page.wait_for_function("() => !!(state.lastReport && state.lastReport.stamp)", timeout=6000)
        except Exception:
            pass
        spent = round(time.time() - t0, 2)
        print("        按了放弃之后 " + str(spent) + " 秒拿到判定")
        check("按了先不等了，判定立刻出来（不等那 4 秒）", 0 < spent < 2.0, True)
        check("放弃之后遮罩收掉", page.evaluate(
            "() => !document.querySelector('#veil').classList.contains('on')"), True)
        check("放弃之后不再谎称认过", page.evaluate("() => !(state.lastReport.new || {}).seen"), True)
        check("出处记得是用户自己放弃的，不是「网关坏了」",
              "先不等了" in page.evaluate("() => JSON.stringify(JianAPI.status('see'))"), True)
        check("放弃之后这一轮不再发第二枪",
              len([c for c in calls if c[0].endswith("/v1/see")]), see_before)
        stamp_now = page.evaluate("() => state.lastReport.stamp")
        page.wait_for_timeout(2200)   # 桩那 4 秒这会儿早到了
        check("迟到的回话盖不掉已经摆出来的判定",
              page.evaluate("() => state.lastReport.stamp") == stamp_now
              and not page.evaluate("() => (state.lastReport.new || {}).seen"), True)
    finally:
        srv.shutdown()
        srv.server_close()
        page.evaluate("() => { state.apiUrl = ''; window.JIAN_CONFIG.endpoint = ''; gwReset(); save(state); }")
    # 这一节打了两个「明知不通」的端点（桩里没接的 /v1/see、以及 127.0.0.1:9）。
    # Chrome 把它们记成 console.error——那是网络回声，不是 JS 异常；但也不白吞，条数印出来。
    seg = errors[mark29:]
    echo = [e for e in seg if "Failed to load resource" in e]
    real = [e for e in seg if "Failed to load resource" not in e]
    print("        故意的网络回声 " + str(len(echo)) + " 条（404 / ERR_UNSAFE_PORT），不计入运行错误")
    del errors[mark29:]
    errors.extend(real)

    print("\n--- 30. 笺册里那另外 12 张：总数、按笺过滤、摊开、上限要说话 ---")
    # 笺册在册 24 张，屏上以前永远只画 12 张，而且一个字都没说：另外那 12 张既够不着，
    # 也数不清到底存了几张。第 21 轮那条「上限动了手要说」同一种哑——超出 24 张是悄悄切的。
    page.evaluate("""() => {
      window.__copied = [];
      window.copy = (t, m) => { window.__copied.push([t, m]); };
      state.album = [];
      for (let i = 0; i < 24; i++) {
        const t = ['yi', 'wei', 'yan'][i % 3];
        state.album.push({ type: t, t: Date.now() - i * DAY, quote: '第' + i + '张',
                           text: '整张笺' + t + '-' + i + String.fromCharCode(10) + '第二行' });
      }
      albumView = 'all'; albumAll = false;
      save(state); show('me');
    }""")
    page.wait_for_timeout(250)
    check("头上说了在册几张、现在摊着几张", page.text_content("#albumNote"),
          "笺册 · 一共 24 张，先摊着最新的 12 张")
    check("屏上摊 12 张", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 12)
    check("另一枚签说清还欠几张", page.text_content("#albumChips [data-aall]").strip(), "看另外 12 张")
    page.click("#albumChips [data-aall]")
    page.wait_for_timeout(200)
    check("摊开之后 24 张全在", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 24)
    check("摊开之后说明里不再写「先摊着」", "先摊着" in page.text_content("#albumNote"), False)
    check("那枚签自己改口成收回", page.text_content("#albumChips [data-aall]").strip(), "只看最新 12 张")
    # 过滤之后的下标必须是 state.album 里的真下标。按「屏上第几张」取值时，点第一行复制到
    # 的是背后另一张笺——第 15 轮「勾错条」同款坑，那时候错在 indexOf，这里是 slice。
    page.evaluate("""() => { document.querySelector("#albumChips [data-aview='wei']").focus(); }""")
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    check("键盘点过滤，焦点还在同一枚签上（整片重建不许把人甩回页首）",
          page.evaluate("() => document.activeElement && document.activeElement.dataset.aview"), "wei")
    check("过滤后只剩味笺那 8 张", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 8)
    check("说明里带上这一类有几张", page.text_content("#albumNote"), "笺册 · 一共 24 张，味笺 8 张")
    got_idx = page.eval_on_selector_all("#album .slip", "els => els.map(e => +e.dataset.slip)")
    want_idx = page.evaluate("() => state.album.map((a, i) => a.type === 'wei' ? i : -1).filter(i => i >= 0)")
    check("这 8 行的下标是在册里的真下标", got_idx, want_idx)
    page.evaluate("() => { window.__copied = []; }")
    page.click("#album .slip >> nth=0")
    page.wait_for_timeout(150)
    check("点这一排第一行，复制到的是它自己那张（不是全册第一张）",
          page.evaluate("() => window.__copied.at(-1)[0]"), "整张笺wei-1\n第二行")
    page.click("#albumChips [data-aview='all']")
    page.wait_for_timeout(150)
    check("换回全部时刚才摊开的没被悄悄收回",
          page.evaluate("() => document.querySelectorAll('#album .slip').length"), 24)
    # × 只能在卡片**外面**：整张卡片是个 <button>，button 里不许有交互内容
    # （第 23 轮那个嵌套 <label> 是同一条规定），塞进去点 × 会连带触发一次复制。
    check("每一行一枚 ×", page.evaluate("() => document.querySelectorAll('#album [data-del]').length"), 24)
    check("× 不在卡片里面", page.evaluate(
        "() => [...document.querySelectorAll('#album [data-del]')]"
        ".every(d => !d.closest('.slip'))"), True)
    # 这条才是「× 塞进 button」真有牙的地方：HTML 解析器遇到 button 里的 button 会
    # **当场把外面那张闭合掉**，于是「再复制」那行落到卡片外面——整张卡片的形状就散了。
    check("「再复制」那一行还在卡片里面（卡片没被嵌套的 button 咬断）",
          page.evaluate("() => document.querySelectorAll('#album .slip .slip-copy').length"), 24)
    # × 在 DOM 上必须是卡片的兄弟，但视觉上要压在卡片自己的框里——第一版给它单独一列，
    # 截图上看就是一个浮在纸外的记号，像卡片缺了一角。
    check("× 压在卡片自己的框里", page.evaluate(
        """() => [...document.querySelectorAll('#album .slip-row')].every(r => {
             const c = r.querySelector('.slip').getBoundingClientRect();
             const x = r.querySelector('.drop').getBoundingClientRect();
             return x.left >= c.left - 1 && x.right <= c.right + 1
                 && x.top >= c.top - 1 && x.bottom <= c.bottom + 1; })"""), True)
    check("眉上那排日期不与 × 相叠", page.evaluate(
        """() => [...document.querySelectorAll('#album .slip-row')].every(r => {
             const d = r.querySelector('.slip-date').getBoundingClientRect();
             const x = r.querySelector('.drop').getBoundingClientRect();
             return d.right <= x.left; })"""), True)
    quotes = page.evaluate("() => state.album.map(a => a.quote)")
    page.evaluate("() => { window.__copied = []; }")
    page.click("#album [data-del='3']")
    page.wait_for_timeout(200)
    check("在册的少了一张", page.evaluate("() => state.album.length"), 23)
    check("屏上少了一行", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 23)
    check("头上那句话跟着改口", "一共 23 张" in page.text_content("#albumNote"), True)
    check("删掉的正是那一张，其余一字不动",
          page.evaluate("() => state.album.map(a => a.quote)"), quotes[:3] + quotes[4:])
    check("点 × 不顺手复制（复制是卡片的事）", page.evaluate("() => window.__copied.length"), 0)
    check("提示给了一次撤销", page.is_visible(".toast button"), True)
    page.click(".toast button")
    page.wait_for_timeout(200)
    check("撤销把那张放回**原位**（顺序与删前一字不差）",
          page.evaluate("() => state.album.map(a => a.quote)"), quotes)
    # 过滤态下 × 也必须带真下标，否则「删味笺第一张」删掉的是全册第一张
    page.click("#albumChips [data-aview='yan']")
    page.wait_for_timeout(200)
    yan_idx = page.evaluate("() => state.album.map((a, i) => a.type === 'yan' ? i : -1).filter(i => i >= 0)")
    check("过滤之后 × 带的还是在册真下标",
          page.eval_on_selector_all("#album [data-del]", "els => els.map(e => +e.dataset.del)"), yan_idx)
    first = yan_idx[0]
    q2 = page.evaluate("() => state.album.map(a => a.quote)")
    page.click("#album [data-del='%d']" % first)
    page.wait_for_timeout(200)
    check("过滤态下删掉的也是那一张",
          page.evaluate("() => state.album.map(a => a.quote)"), q2[:first] + q2[first + 1:])
    page.evaluate("() => { albumView = 'all'; show('me'); }")
    # 只有一类有存档时不该摆一堆点不动的签；0 张时那一排整个收着，不许留一行空高。
    page.evaluate("""() => {
      state.album = [{ type: 'yi', t: Date.now(), quote: '只有衣笺', text: '只有衣笺' }];
      albumView = 'all'; save(state); show('me');
    }""")
    page.wait_for_timeout(200)
    check("一类有存档时不出过滤签", page.evaluate("() => document.querySelectorAll('#albumChips .chip').length"), 0)
    check("一张笺时不摆「看另外」那枚空签",
          page.evaluate("() => !!document.querySelector('#albumChips [data-aall]')"), False)
    # 手里这份可能因为导入新备份而只剩别的笺：过滤态不许把人关在里面，也得说清空白是过滤造成的。
    page.evaluate("() => { albumView = 'wei'; show('me'); }")
    page.wait_for_timeout(200)
    check("这一笺一张都没有时空态说清了", "这一笺还没有存档" in page.inner_text("#album"), True)
    check("出不去不行：「全部」那枚签还在", page.text_content("#albumChips [data-aview='all']").strip(), "全部 1 张")
    page.evaluate("() => { albumView = 'all'; show('me'); }")
    page.evaluate("() => { state.album = []; save(state); show('me'); }")
    page.wait_for_timeout(200)
    check("空笺册把说明与签排一起收着（不留一行空高）",
          page.evaluate("() => [document.querySelector('#albumNote').hidden,"
                        " document.querySelector('#albumChips').hidden]"), [True, True])
    check("空态那句话还在", "还没有笺" in page.inner_text("#album"), True)
    # 上限动了手要说：这条路以前只报照片和柜子，笺册一次切掉 6 张不吭声。
    page.evaluate("""() => {
      state.album = [];
      for (let i = 0; i < 30; i++) state.album.push({ type: 'yi', t: Date.now(), quote: 'q' + i, text: 'x' });
      const t = document.querySelector('.toast'); if (t) t.remove();
      save(state);
    }""")
    page.wait_for_timeout(200)
    check("存完之后真留 24 张", page.evaluate("() => state.album.length"), 24)
    check("话里说了丢掉几张", "笺册只留最新 24 张，丢掉 6 张" in toast_text(), True)
    # 配额吃紧那条逐级丢的路更狠：一次把笺册切到 8 张。这条路平时走不到，所以拿桩逼出来——
    # 它说的张数必须是**这条路**的张数，把 24 抄在这儿就是一句假话。
    page.evaluate("""() => {
      const t = document.querySelector('.toast'); if (t) t.remove();
      const real = window.writeStore; let first = true;
      window.writeStore = (s) => { if (first) { first = false; throw new Error('配额'); } return real.call(window, s); };
      state.album = [];
      for (let i = 0; i < 24; i++) state.album.push({ type: 'yi', t: Date.now(), quote: 'q' + i, text: 'x' });
      save(state);
      window.writeStore = real;
    }""")
    page.wait_for_timeout(200)
    check("逐级丢那条路说的是留 8 张、丢 16 张", "笺册只留最新 8 张，丢掉 16 张" in toast_text(), True)
    check("丢完在册的还剩 8 张", page.evaluate("() => JSON.parse(localStorage.getItem('jian.v1')).album.length"), 8)

    print("\n--- 31. 今天穿了什么：记进去的账，屏上得有个地方答 ---")
    # 「今天穿了」这个按钮从第四轮就在，但全 App 没有任何一处答得出来「今天穿了什么」——
    # 想知道就得自己翻 36 块瓷砖找哪枚写着「上次 今天」。
    page.evaluate("""() => {
      const d = Date.now(), DAY = 86400000;
      const lastNight = new Date(d - DAY); lastNight.setHours(23, 0, 0, 0);   // 昨晚十一点
      state.wardrobe = [
        { id: 't1', name: '奶咖针织', cat: '上衣', color: '#c9b39b', worn: 27, lastWorn: d - 3600000 },
        { id: 't2', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: d },
        { id: 't3', name: '驼色大衣', cat: '外套', color: '#c4a574', worn: 3, lastWorn: lastNight.getTime() },
        { id: 't4', name: '白衬衫', cat: '上衣', color: '#f2efe9', worn: 18, lastWorn: d - 2 * DAY },
        { id: 't5', name: '灰蓝卫衣', cat: '上衣', color: '#7d8ea0', worn: 0, lastWorn: null },
        { id: 't6', name: '燕麦开衫', cat: '外套', color: '#d8c9b4', worn: 41, lastWorn: d },
        { id: 't7', name: '白鞋', cat: '鞋', color: '#f5f5f3', worn: 15, lastWorn: d }
      ];
      state.clothSel = 't5'; state.closetSeason = 'all';
      save(state); renderCloset();
    }""")
    # 这一节量两样东西，而 0.6.0 把它们分到了**两个页签**上：
    #   · 「今天穿了」那排签（#closetNote [data-worn]）在**过笺**页（index.html 里 #closetNote
    #     就在 #yiPanePass 里，紧跟着 #lastReportLink）——那一行是「柜子现在什么状态」，
    #     判定前先看一眼柜子，所以它跟过笺摆在一起；
    #   · 操作条（#wearIt / #clothName）与柜子网格在**柜子**页（#yiPaneCloset）。
    # 0.5.x 只有一页，两样都在屏上；现在点那排签必须站在过笺页，点「今天穿了」必须站在柜子页。
    # 不这么摆的话：`page.click("#closetNote [data-worn='t2']")` 报 "element is not visible"，
    # 而 `#wearIt` 那一头同理。（先过笺后柜子，与用户的真实动作顺序一致。）
    yi_tab(page, "pass")
    page.wait_for_timeout(300)
    chips = page.eval_on_selector_all("#closetNote [data-worn]", "els => els.map(e => e.textContent.trim())")
    check("今天那一排只数同一历日的，并且只摊三枚", chips, ["奶咖针织", "深蓝阔腿", "燕麦开衫"])
    # 昨晚十一点那件按「24 小时内」会被算进来——那是另一件事：今天没穿它
    check("昨晚十一点那件不算今天（不是 24 小时之内）", "驼色大衣" in chips, False)
    check("第四件不摊出来，但计进「等 N 件」",
          ["白鞋" in chips, page.text_content("#closetNote").count("等 4 件")], [False, 1])
    check("签上的读屏标签说的是这一行会干什么",
          page.evaluate("() => document.querySelector('#closetNote [data-worn]').getAttribute('aria-label')"),
          "选中今天穿的这件：奶咖针织")
    page.click("#closetNote [data-worn='t2']")
    page.wait_for_timeout(300)
    check("点名字就是选中那一件", page.evaluate("() => state.clothSel"), "t2")
    # 选中之后操作条在柜子页：切过去再量 #clothName（它不在过笺页上）
    yi_tab(page, "closet")
    page.wait_for_timeout(200)
    check("操作条跟着换成那一件", page.input_value("#clothName"), "深蓝阔腿")
    # 带着搜索点一个被筛掉的名字 = 点了没反应（第 22 轮「带着搜索入柜」同一条规矩）
    page.evaluate("""() => {
      const s = document.querySelector('#clothSearch');
      s.value = '卫衣'; s.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.wait_for_timeout(300)
    check("搜索生效时那件被筛掉了",
          page.evaluate("() => !!document.querySelector('#closet .item[data-id=\"t1\"]')"), False)
    # 那排名字在过笺页上，点它要站在过笺页（搜索框的值留在 DOM 里，切页签不会丢）
    yi_tab(page, "pass")
    page.click("#closetNote [data-worn='t1']")
    page.wait_for_timeout(300)
    check("点被筛掉的名字会把搜索清掉（不许点了没反应）",
          page.evaluate("() => document.querySelector('#clothSearch').value"), "")
    check("清掉之后那件真的在屏上",
          page.evaluate("() => !!document.querySelector('#closet .item[data-id=\"t1\"]')"), True)
    check("并且选中了它", page.evaluate("() => state.clothSel"), "t1")
    # 触摸高度是第 9 轮画的那条线：.chip 平时 34px，摘要里这一排收到 26px 就是下限
    check("今天那排签的触摸高度不低于 24px", page.evaluate(
        "() => Math.min(...[...document.querySelectorAll('#closetNote [data-worn]')]"
        ".map(e => e.getBoundingClientRect().height)) >= 24"), True)
    page.set_viewport_size({"width": 360, "height": 780})
    # 窄屏这两条量的是「今天那一排签」，而那一排只在过笺页上可见（另一页是 display:none，
    # BLEED/TRUNC 会把整层跳过去）。所以两个页签都要量一遍：
    # 不切的话，过笺这一页永远是空扫，两条都会「干净」地假绿。
    for tab_name in ("pass", "closet"):
        yi_tab(page, tab_name)
        page.wait_for_timeout(250)
        check(f"360px/衣笺{tab_name} 标签不折字", page.evaluate(TRUNC, "#yi"), [])
        check(f"360px/衣笺{tab_name} 内容不越纸边", page.evaluate(BLEED, "#yi"), [])
    page.set_viewport_size({"width": 390, "height": 844})
    # 一件都没记时不许是空白：那句话要教人去按操作条上那枚
    page.evaluate("""() => {
      state.wardrobe.forEach((w) => { w.lastWorn = Date.now() - 3 * 86400000; });
      save(state); renderCloset();
    }""")
    yi_tab(page, "pass")
    page.wait_for_timeout(250)
    check("没记过的时候那句话说的是没记过",
          "今天还没记穿了什么" in page.text_content("#closetNote"), True)
    check("并且指向那枚按钮", "今天穿了" in page.text_content("#closetNote"), True)
    # 记错了要能撤：次数与「上次」都得回去（久未穿那条判定吃的就是 lastWorn）
    yi_tab(page, "closet")
    page.evaluate("() => { state.clothSel = 't3'; save(state); renderCloset(); }")
    page.wait_for_timeout(250)
    before = page.evaluate("() => { const w = state.wardrobe.find(x => x.id === 't3');"
                           " return [w.worn, w.lastWorn]; }")
    page.click("#wearIt")
    page.wait_for_timeout(300)
    after = page.evaluate("() => { const w = state.wardrobe.find(x => x.id === 't3');"
                          " return [w.worn, w.lastWorn]; }")
    check("记下之后次数加一、上次变成今天", [after[0] - before[0], after[1] > before[1]], [1, True])
    # 记完之后那一排「今天穿了」要跟着长出这一件——它在过笺页上，切过去再读。
    yi_tab(page, "pass")
    page.wait_for_timeout(200)
    check("它现在出现在今天那一排里", "驼色大衣" in page.eval_on_selector_all(
        "#closetNote [data-worn]", "els => els.map(e => e.textContent.trim())"), True)
    page.click(".toast button")
    page.wait_for_timeout(300)
    check("撤销把 worn 与 lastWorn 一起退回（一字不差）",
          page.evaluate("() => { const w = state.wardrobe.find(x => x.id === 't3');"
                        " return [w.worn, w.lastWorn]; }"), before)
    check("退回之后它不在今天那一排里了", "驼色大衣" in page.eval_on_selector_all(
        "#closetNote [data-worn]", "els => els.map(e => e.textContent.trim())"), False)

    print("\n--- 32. 四句做不到的话：假入口、门槛话、指错路 ---")
    # ① 空柜子以前只说「先入几件常穿的，过笺才准」，而那一支里根本不画 ＋：
    #    删掉最后一件之后，屏上叫你做的事在这块屏上没有入口（唯一的出路是先去扣点的过笺）。
    # 这一节读的是空柜那句（#closet 的空态），它在柜子页签里——不切过去 inner_text 读到的是
    # 看不见的子树，而「才准 / 放几件常穿的进来」这两句恰好都在里面，会假绿。
    yi_tab(page, "closet")
    page.evaluate("() => { state.wardrobe = []; state.clothSel = null; save(state); renderCloset(); }")
    page.wait_for_timeout(300)
    check("空柜子也给一枚 ＋（叫人事就得给入口）",
          page.evaluate("() => !!document.querySelector('#closet #addCloth')"), True)
    check("空柜那句不再写「才准」这种门槛", "才准" in page.inner_text("#closet"), False)
    check("说的是「放几件常穿的进来」", "放几件常穿的进来" in page.inner_text("#closet"), True)
    # ② 门槛话在第 21 轮从引擎那句里删了，DOM 里这句是**同一句话的第二份拷贝**，漏了。
    #    所以这里扫四屏：以后谁再写一句「N 件…才准」，不管写在哪儿都会被抓。
    for scr in ("yi", "wei", "yan", "me"):
        page.evaluate("(id) => show(id)", scr)
        page.wait_for_timeout(200)
        check(f"{scr} 屏上不出现「才准」这种没实现的门槛", "才准" in page.inner_text("#" + scr), False)
    # ③ 「放录音」是一枚按了必然没用的按钮：它不发任何音频，网关永远回 needText，
    #    而界面那句「（网关那边没有能转写录音的模型）」是假的——根本没去问过那台模型。
    check("「放录音」那枚假入口没了", page.evaluate("() => !!document.querySelector('#yanAudBtn')"), False)
    check("配套的 audio 文件框也不留着", page.evaluate("() => !!document.querySelector('#fileYanAud')"), False)
    check("api 里不再挂着一个永远失败的 hear", page.evaluate("() => typeof JianAPI.hear"), "undefined")
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(200)
    check("要转文字那句话还在，只是不再假装能办", "听写" in page.inner_text("#yan"), True)
    # ④ 「笺点不足，去『我的』开一笺」指错了地方：那一屏上「开哪一笺」只管开关，一个点也不送，
    #    送点的在折叠着的「测试订阅」里。名字撞车，照着做的人只会更困惑。
    page.evaluate("""() => {
      state.points = 0; state.plan = null; save(state);
      const t = document.querySelector('.toast'); if (t) t.remove();
      spend(1, 'yi');
    }""")
    page.wait_for_timeout(200)
    check("笺点不足时指的是能送点的那一格", "测试订阅" in toast_text(), True)
    check("并且说的是「开哪一笺就不再扣点」这条一定拿得到的出路，不再报一个可能不发生的固定数额",
          ["不再扣点" in toast_text(), "16 点" in toast_text()], [True, False])
    check("这一笺确实没排成（点没扣）", page.evaluate("() => state.points"), 0)

    print("\n--- 33. 记下来没人读的、截断没人说的 ---")
    # ① 话术里「可以点」只带前五道，而屏上那一节列的是全部：不写「等 N 道」，
    #    粘到群里的人以为就这五道。
    page.evaluate("""() => {
      state.points = 90; state.plan = 'all';
      // 现场要自己造：前面几节把 people 设成过忌口的一桌，那样安全菜会被雷区吃掉，
      // 「等 N 道」这一格就没有输入能走到（第 20 轮 POS_RE 那条假门的同一个形状）。
      state.people = [{ name: '我', chips: [] }];
      const el = document.querySelector('#menu');
      el.value = ['清蒸鲈鱼','白灼菜心','米饭','紫菜蛋花汤','宫保鸡丁','白切鸡','地三鲜','蛋炒饭','冬瓜排骨汤','麻婆豆腐','蒜蓉西兰花','番茄炒蛋'].join(String.fromCharCode(10));
      el.dispatchEvent(new Event('input', { bubbles: true }));
      runWei();
    }""")
    page.wait_for_function("() => state.lastWei && state.lastWei.talk", timeout=20000)
    page.wait_for_timeout(300)
    talk_safe = page.evaluate("""() => {
      const r = state.lastWei.r, t = state.lastWei.talk;
      const m = t.match(/可以点：([^。]*)。/);
      return { safe: (r.safe || []).length, line: m ? m[1] : '', sheet: document.querySelector('#weiResult').textContent };
    }""")
    print("        安全菜 " + str(talk_safe["safe"]) + " 道 · 话术那行：" + talk_safe["line"])
    check("这一桌确实超过五道安全菜", talk_safe["safe"] > 5, True)
    check("话术里带出总数「等 N 道」", ("等 %d 道" % talk_safe["safe"]) in talk_safe["line"], True)
    listed = talk_safe["line"].split(" 等 ")[0].split("、")
    check("列出来的仍是前五道（长列表不整段塞进群话）", len(listed), 5)
    # ② 三处静默截断现在都归入「动了手要说」
    page.evaluate("""() => {
      const t = document.querySelector('.toast'); if (t) t.remove();
      state.yanCards = []; for (let i = 0; i < 240; i++) state.yanCards.push({ k: '待办', line: 'L' + i, done: false });
      save(state);
    }""")
    page.wait_for_timeout(200)
    check("言笺超上限也报条数", "言笺只留最新 200 条，丢掉 40 条" in toast_text(), True)
    page.evaluate("""() => {
      const t = document.querySelector('.toast'); if (t) t.remove();
      state.yanText = '字'.repeat(5000); save(state);
    }""")
    page.wait_for_timeout(200)
    check("贴进来的字被掐报字数", "掐掉后面 1000 字" in toast_text(), True)
    page.evaluate("""() => {
      const t = document.querySelector('.toast'); if (t) t.remove();
      const d = Date.now();
      state.weiHist = [0,1,2,3,4,5,6].map(i => ({ menu: '米饭', n: 2, t: d - i, chips: [] }));
      save(state);
    }""")
    page.wait_for_timeout(200)
    check("排过的桌超上限报桌数，并说清笺册没动",
          "排过的桌只留 4 桌，丢掉 3 桌（笺册里那些桌没动）" in toast_text(), True)
    # ③ 网关自述里 recognize/ocr 是两个分开的布尔：只有聊天模型的网关不该被承诺「认衣服可用」
    page.evaluate("""() => {
      // 桩换的是 JianAPI.gateway，它**出来时已经归一过**（model 是字符串、tasks 是对象），
      // 所以这里给的必须是归一之后的形状——给成网关原始的那份 {model:{model:…}}，
      // 测的就是「界面会不会印出 [object Object]」这件根本没发生的事。
      window.__gw = { on: true, ok: true, model: 'chat-only', tasks: { yi: true, wei: true, yan: true, recognize: false, ocr: false } };
      if (!window.__realGw) window.__realGw = JianAPI.gateway;
      JianAPI.gateway = async () => window.__gw;
      // 「我的」那一行先问 eng.on（填没填地址），没填就永远走「没填网关地址」那支。
      // 地址指到保留端口：这一节唯一会出网的是 gateway()，而它已经被桩换掉。
      window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9';
      jianGw = null; jianGwTried = false; gwTries = 0;
      show('me'); askGateway(true);
    }""")
    page.wait_for_timeout(400)
    check("只有聊天模型的网关：明说认衣服不行、抄截图不行",
          page.inner_text("#apiModel"), "网关在线，模型 chat-only：认衣服不行、抄截图不行。")
    page.evaluate("""() => {
      window.__gw = { on: true, ok: true, model: 'old-gw', tasks: {} };
      jianGw = null; jianGwTried = false; askGateway(true);
    }""")
    page.wait_for_timeout(400)
    # 这一格以前**一边叫自己的名字一边量反了的东西**：名字写「缺字段当不知道，不擅自说不行」，
    # 断言查的却是「认衣服可用、抄截图可用」——于是它把那句假话钉成了规矩（第 37 轮修）。
    check("老网关不回 tasks：缺字段就念「没自述」，既不说可用也不说不行",
          page.inner_text("#apiModel"), "网关在线，模型 old-gw：认衣服没自述、抄截图没自述。")
    # 桩要收回去：这一节之后还有「运行时错误」汇总，留一个假 gateway 在 JianAPI 上
    # 就是给下一套测试留坑（第 18 轮 device_gateway 那条残留死地址是同一类事故）。
    page.evaluate("""() => {
      if (window.__realGw) JianAPI.gateway = window.__realGw;
      delete window.__gw; delete window.__realGw;
      window.JIAN_CONFIG.endpoint = ''; gwReset();
    }""")

    print("\n--- 34. 冷暖调这一句：判定算出来的，三处都得说同一句 ---")
    # toneOf 从第五轮就在算，注释写着「用于文案」——文案二十几轮没来，算出来的 tone
    # 只躺进 lastNew 与备份里没人读。现在它成了判定自己的属性（r.toneLine），
    # 屏幕附注、复制的话术、长图的依据行共用一份，跟 thinNote 同一个办法。
    page.evaluate("""() => {
      const d = Date.now();
      const warm = ['#c9b39b', '#d8c9b4', '#c4a574', '#8a5a2b', '#b06a4a'];
      state.wardrobe = warm.map((c, i) => ({ id: 'k' + i, name: '暖' + i, cat: '上衣', color: c, worn: 3, lastWorn: d }));
      state.points = 90; state.plan = 'all'; state.clothSel = null;
      state.lastReport = null; state.lastNew = null;
      save(state);
    }""")
    # 这一节两发 runYi 都在过笺页签里（runYi 的入口是 #fileNew）。
    yi_tab(page, "pass")
    page.wait_for_timeout(250)
    page.evaluate("async () => { const f = await window.__mk('#2c3a4a', 'cool.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport && state.lastReport.stamp", timeout=30000)
    page.wait_for_timeout(400)
    tone = "柜里 5/5 件是暖调，这件是冷调。"
    note_txt = page.inner_text("#reportNote")
    print("        附注：" + note_txt)
    check("屏幕附注说了冷暖这一层", tone in note_txt, True)
    copied = page.evaluate("() => reportText(state.lastReport)")
    check("复制出去的话术也带着同一句", tone in copied, True)
    forms = page.evaluate("""() => {
      const r = state.lastReport;
      return [basisLine(r, false).includes(r.toneLine), basisLine(r, true).includes(r.toneLine)];
    }""")
    check("长图的依据行走的是同一句（放不下才退回短版，短版不带它）", forms, [True, False])
    check("这一句是判定的属性，不是界面自己拼的",
          page.evaluate("() => typeof state.lastReport.toneLine"), "string")
    # 柜子里冷暖本来就不分明的时候，别硬找话说
    page.evaluate("""() => {
      const d = Date.now();
      const mix = ['#c9b39b', '#d8c9b4', '#c4a574', '#2c3a4a', '#3b6e8f', '#4a6b52'];
      state.wardrobe = mix.map((c, i) => ({ id: 'm' + i, name: '混' + i, cat: '上衣', color: c, worn: 3, lastWorn: d }));
      save(state);
    }""")
    page.evaluate("() => { window.__rep0 = state.lastReport; }")
    page.evaluate("async () => { const f = await window.__mk('#2c3a4a', 'cool2.jpg'); runYi(f); }")
    page.wait_for_function("() => state.lastReport !== window.__rep0", timeout=30000)
    page.wait_for_timeout(400)
    check("冷暖各半的柜子不硬找话说", page.evaluate("() => state.lastReport.toneLine"), "")

    print("\n--- 35. 笺册里那整张笺，终于不用复制出来才看得见 ---")
    # 册子存的是当时那**整张**笺（多行），可界面永远只画一行 quote：想读只能复制出去。
    page.evaluate("""() => {
      const d = Date.now();
      state.album = [
        { type: 'yi', t: d, stamp: '先别', quote: '柜里的「奶咖针织」就是这个色。',
          text: '【衣笺】先别\\n柜里的「奶咖针织」就是这个色。\\n再买一件，是重复的句子。\\n—— 一张短笺，一次决定' },
        { type: 'wei', t: d - 86400000, quote: '这桌先排过了。避开：宫保鸡丁。',
          text: '这桌先排过了。避开：宫保鸡丁。' },
        { type: 'yan', t: d - 2 * 86400000, quote: '三条：明天交材料',
          text: '· 明天把材料发我\\n· 药快没了帮我买一盒\\n· 周五见' },
      ];
      albumView = 'all'; albumAll = false; albumOpen = [];
      save(state); show('me');
      window.__copied = [];
    }""")
    page.wait_for_timeout(300)
    toggles = page.eval_on_selector_all("#album [data-aopen]", "els => els.map(e => e.textContent.trim())")
    check("只有 text 与那一行不同的存档才摆「全文」", toggles, ["全文", "全文"])
    check("味笺那种两个值一样的不摆空签",
          page.evaluate("() => { const i = 1; return !!document.querySelector(`#album [data-aopen='${i}']`); }"), False)
    page.evaluate("() => { window.__copied = []; }")
    page.click("#album [data-aopen='0']")
    page.wait_for_timeout(250)
    body0 = page.evaluate("""() => document.querySelector("#album [data-slip='0'] .slip-body").textContent""")
    check("点开看到的是整张笺（第二行也在）", "再买一件，是重复的句子。" in body0, True)
    # 取不到要点名「没有摊开的那一行」：直接 getComputedStyle(null) 会抛，
    # 守门自检就只能说「崩了」，说不出是哪一格在守（第 31 轮那条同一个修法）。
    check("换行没被吃掉（pre-wrap 生效）",
          page.evaluate("""() => { const e = document.querySelector('#album .slip-body.full');
            return e ? getComputedStyle(e).whiteSpace : '（没有摊开的那一行）'; }"""),
          "pre-wrap")
    check("点「全文」不顺手复制（它是卡片的兄弟）", page.evaluate("() => window.__copied.length"), 0)
    check("读屏知道这一行摊开了",
          page.evaluate("() => document.querySelector(\"#album [data-aopen='0']\").getAttribute('aria-expanded')"), "true")
    check("那枚签自己改口成「收起」",
          page.evaluate("() => document.querySelector(\"#album [data-aopen='0']\").textContent.trim()"), "收起")
    page.click("#album [data-aopen='0']")
    page.wait_for_timeout(250)
    check("收起之后回到那一行", "再买一件" in page.evaluate(
        """() => document.querySelector("#album [data-slip='0'] .slip-body").textContent"""), False)
    # 摊开着一张再去删**另一张**：下标整体前移，摊着的那几张必须作废，
    # 否则「摊开的第 0 张」会指着别的笺（第 27 轮那条下标坑的第三个变种）。
    page.evaluate("() => { albumOpen = [0]; renderMe(); }")
    page.wait_for_timeout(200)
    check("先让第 0 张摊着", page.evaluate("() => document.querySelectorAll('#album .slip-body.full').length"), 1)
    page.click("#album [data-del='1']")
    page.wait_for_timeout(250)
    check("删掉另一张之后，摊着的那几张一起作废",
          page.evaluate("() => [albumOpen.length, document.querySelectorAll('#album .slip-body.full').length]"), [0, 0])
    check("剩下两张还在", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 2)
    page.evaluate("() => { albumOpen = [0]; renderMe(); }")
    page.wait_for_timeout(200)
    page.evaluate("() => document.querySelector(\"#album [data-aopen='0']\").focus()")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    check("键盘点「全文」，焦点还在同一枚签上",
          page.evaluate("() => document.activeElement && document.activeElement.dataset.aopen"), "0")
    # 窄屏：摊开的那张不许把纸撑破
    page.set_viewport_size({"width": 360, "height": 780})
    page.evaluate("() => show('me')")
    page.wait_for_timeout(250)
    check("360px 摊开的笺不越纸边", page.evaluate(BLEED, "#me"), [])
    check("360px 全文那枚签不折字", page.evaluate(TRUNC, "#me"), [])
    page.set_viewport_size({"width": 390, "height": 844})

    print("\n--- 36. 「几乎同色」这套词只许有一份 ---")
    # 屏幕附注以前自己抄了一遍 12/30 的阈值（card.js 的 nearWord 是另一份）。
    # 两份今天一样，明天有人调其中一档：同一张笺，屏幕上说「同色系」、长图上说「隔得开」。
    gaps = page.evaluate("""() => {
      if (!state.lastReport) return null;
      const out = [];
      for (const g of [11, 12, 29, 30, 55]) {
        const r = Object.assign({}, state.lastReport, { gap: g });
        r.basis = Object.assign({}, state.lastReport.basis, { gap: g });
        state.lastReport = r; paintReport();
        out.push({ g, note: document.querySelector('#reportNote').textContent,
                   card: basisLine(r, false), word: nearWord(g) });
      }
      return out;
    }""")
    check("这一屏有报告可量（没有的话这节是白测）", gaps is not None, True)
    for row in (gaps or []):
        check("色差 %d：屏幕说的词就是 nearWord 的那个词（%s）" % (row["g"], row["word"]),
              row["word"] in row["note"], True)
        check("色差 %d：长图的依据行用同一个词" % row["g"], row["word"] in row["card"], True)
        check("色差 %d：只出现一个档名，不会两个都在" % row["g"],
              sum(w in row["note"] for w in ("几乎同色", "同色系", "隔得开")), 1)

    print("\n--- 37. 清空要把「备份保险丝」那一份一起擦掉 ---")
    # localStorage 之外还有第二份：Capacitor Preferences。它的本职是「系统清了本机数据时捞回来」，
    # 而「清空本地数据」以前只擦第一份——reload 之后保险丝看见本机空了，就把刚删掉的整份搬回来，
    # 屏幕上还写着「本机数据已清空」。浏览器里 hasNative() 恒 false，十七轮以来这道门对这条路全瞎。
    # 这里挂一个假桥把它照出来：假 Preferences 存在另一个 localStorage 键上，
    # 于是它和真的一样活得过 reload，而 remove/get 各记一笔，能问「到底调用过没有」。
    nctx = browser.new_context(viewport={"width": 430, "height": 940})
    nctx.add_init_script("""(() => {
      const PK = '__fakeprefs__', LK = '__plog__';
      // 真插件是一次原生往返，不是微任务：每一步先让出 120ms。
      // 不这样做的话「忘了 await 擦除」在测试里也照样对——async 函数体在第一个 await
      // 之前是同步跑完的，remove 其实已经执行了，那条注入就成了假靶子。
      // 120ms 是量出来的：reload 一定抢在它之前，而 2 秒那道等待还绰绰有余。
      const nap = () => new Promise((r) => setTimeout(r, 120));
      const log = (m) => { try {
        const a = JSON.parse(localStorage.getItem(LK) || '[]'); a.push(m);
        localStorage.setItem(LK, JSON.stringify(a));
      } catch (_) {} };
      window.Capacitor = { Plugins: { Preferences: {
        get: async (o) => { await nap(); log('get'); return { value: localStorage.getItem(PK) }; },
        set: async (o) => { await nap(); log('set'); localStorage.setItem(PK, o.value); return {}; },
        // 挂着 __noerase__ 时假装这台机器的 remove 不生效：用来量「App 有没有发现自己没擦干净」
        remove: async (o) => { await nap(); log('remove');
          if (localStorage.getItem('__noerase__')) return {};
          localStorage.removeItem(PK); return {}; },
      } } };
    })()""")
    npage = nctx.new_page()
    nerrs = []
    npage.on("pageerror", lambda e: nerrs.append("pageerror: " + str(e)))
    npage.on("console", lambda m: nerrs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    ndlg = []
    npage.on("dialog", lambda d: (ndlg.append(d.type),
                                  d.accept() if d.type == "confirm" else d.dismiss()))

    def nw_ok(cond, ms, note):
        # 等条件这件事本身也可能赶在 reload 中间抛「context destroyed」：那不是「等不到」，
        # 是读早了。当成还没等到，继续等。
        deadline = time.time() + ms / 1000.0
        while True:
            try:
                npage.wait_for_function(cond, timeout=max(500, int((deadline - time.time()) * 1000)))
                return True
            except Exception as e:
                if "context was destroyed" in str(e) and time.time() < deadline:
                    time.sleep(0.15)
                    continue
                check("等不到：" + note, False, True)
                return False

    def nw_eval(expr):
        """清空与导入都会 reload：读得赶上了那一下，evaluate 就抛
        「Execution context was destroyed」。这一节以前是**绿着通过**的这种 flaky，
        一旦它抢先炸掉，认证报告里那条注入就成了「e2e 崩了 = 抓到了」——
        崩在哪一条根本没说，也就等于任何一条注入都能靠它蒙混过关（第 31/34 轮同一颗雷）。
        所以：等页面重新可用，再读。

        两种竞态都要认（只有第一种被处理过，是第 66 轮实测补上的）：
          · 「Execution context was destroyed」——读的瞬间文档正在被换掉；
          · 「state is not defined」——新文档已经起来了，但 app.js 的脚本还没跑完，
            于是 `state` 这个全局还不在。两者都不是「被测行为坏了」，是读早了。
        等法是**重新轮询**（不是 sleep 一下就当成功）：脚本跑完之后同一个 expr 自然读得通，
        读不通才是真红。"""
        deadline = time.time() + 20
        while True:
            try:
                return npage.evaluate(expr)
            except Exception as e:
                msg = str(e)
                transient = ("context was destroyed" in msg
                             or "Execution context was destroyed" in msg
                             or "state is not defined" in msg
                             or "document is not defined" in msg)
                if not transient or time.time() > deadline:
                    raise
                time.sleep(0.15)

    def nw_toast(sub, ms=9000):
        return nw_ok("() => { const t = document.querySelector('.toast');"
                     " return !!t && t.textContent.indexOf(" + json.dumps(sub, ensure_ascii=False) + ") >= 0; }",
                     ms, "假桥那一页的提示里出现「" + sub + "」")

    npage.goto(URL)
    nw_ok("() => typeof state !== 'undefined'", 20000, "假桥那一页起得来")
    # 先量「这一节测的是不是那条路」：hasNative() 为假的话，下面每一条都是白测（空集合假绿）
    check("这一页确实带着假 Capacitor 桥（否则整节白测）", nw_eval("() => hasNative()"), True)
    # 开机那一步没从假 Preferences 捞回任何东西：下面所有「擦干净了」的观察才不是自导自演
    check("开机时保险丝是空的（fuseRefilled=false）", nw_eval("() => fuseRefilled"), False)

    nw_eval("""() => {
      state.onboarded = true; state.home = 'me';
      state.wardrobe = [{ id: 'z1', name: '张三的外套', cat: '外套', color: '#888888', worn: 4, lastWorn: null }];
      save(state); show('me');
    }""")
    nw_ok("() => (localStorage.getItem('__fakeprefs__') || '').indexOf('张三的外套') >= 0", 6000,
          "save 之后保险丝那一份里有了这件衣服")
    check("擦之前那一份里确实留着（这一格红 = 上一步根本没写进去）",
          nw_eval("() => (localStorage.getItem('__fakeprefs__') || '').indexOf('张三的外套') >= 0"), True)

    npage.click("#reset")
    nw_ok("() => typeof state !== 'undefined' && !!document.querySelector('.toast')", 20000,
          "清空之后页面重开并给了一句提示")
    check("弹的是确认框", ndlg, ["confirm"])
    check("清空之后本机那份没了", nw_eval("() => localStorage.getItem('jian.v1') === null"), True)
    check("清空之后保险丝那份也没了", nw_eval("() => localStorage.getItem('__fakeprefs__') === null"), True)
    check("重开之后没有把刚删掉的那件搬回来",
          nw_eval("() => (state.wardrobe || []).some((w) => w && w.name === '张三的外套')"), False)
    check("说的是「已清空」而不是「没清干净」", nw_toast("本机数据已清空"), True)
    check("擦那一下真的发生过（remove 记了一笔）",
          nw_eval("() => JSON.parse(localStorage.getItem('__plog__') || '[]').indexOf('remove') >= 0"), True)

    # B：这台机器的 remove 不生效。App 必须发现自己没擦干净——那句「已清空」不能说，
    # 反悔那枚签也不该给（数据本来就没丢，没什么可还）。
    nw_eval("() => localStorage.setItem('__noerase__', '1')")
    nw_eval("""() => {
      state.onboarded = true; state.home = 'me';
      state.wardrobe = [{ id: 'z2', name: '擦不掉的那件', cat: '上衣', color: '#654321', worn: 2, lastWorn: null }];
      save(state); show('me');
    }""")
    nw_ok("() => (localStorage.getItem('__fakeprefs__') || '').indexOf('擦不掉的那件') >= 0", 6000,
          "B：擦之前保险丝里有这件")
    npage.click("#reset")
    nw_ok("() => typeof state !== 'undefined' && !!document.querySelector('.toast')", 20000, "B：清空之后页面重开")
    check("B：没擦干净时数据确实被搬回来了（这一格红 = 场景没构造成功，下面的话就都是白测）",
          nw_eval("() => (state.wardrobe || []).some((w) => w && w.name === '擦不掉的那件')"), True)
    check("B：说的是「没清干净」而不是「已清空」", nw_toast("没清干净"), True)
    check("B：不给反悔那枚签", npage.is_visible(".toast.act button"), False)
    nw_eval("() => localStorage.removeItem('__noerase__')")

    # 导入是同一个洞的另一半：写完立刻 reload，那 1 秒的定时器跟着文档一起没，
    # 于是本机是新的、保险丝还是上一代的——哪天系统清一次本机，捞回来的是导入前的旧数据。
    nw_eval("""() => {
      state.onboarded = true;
      state.wardrobe = [{ id: 'o1', name: '导入前的旧名字', cat: '上衣', color: '#777777', worn: 1, lastWorn: null }];
      save(state); show('me');
    }""")
    nw_ok("() => (localStorage.getItem('__fakeprefs__') || '').indexOf('导入前的旧名字') >= 0", 6000,
          "导入之前，保险丝里是这一份（旧名字）")
    fp = OUT / "换代的备份.json"
    fp.write_text(json.dumps({
        "onboarded": True, "home": "yi", "modules": {"yi": True, "wei": True, "yan": True},
        "points": 44, "plan": None, "schema": 2,
        "wardrobe": [{"id": "i1", "name": "导入的那件", "cat": "上衣", "color": "#123456",
                      "worn": 1, "lastWorn": None}],
        "people": [{"name": "我", "chips": []}], "album": [], "yanCards": [],
    }, ensure_ascii=False), encoding="utf-8")
    npage.set_input_files("#fileImport", str(fp))
    nw_ok("() => typeof state !== 'undefined' && state.points === 44", 20000, "导入之后页面重开")
    check("导入之后保险丝换成了新那一份",
          nw_eval("() => (localStorage.getItem('__fakeprefs__') || '').indexOf('导入的那件') >= 0"), True)
    check("导入前那一份没有留在保险丝里",
          nw_eval("() => (localStorage.getItem('__fakeprefs__') || '').indexOf('导入前的旧名字') >= 0"), False)
    check("假桥那一页全程无 JS 报错", [e for e in nerrs if "favicon" not in e.lower()], [])
    nctx.close()

    print("\n--- 38. 六个说不准的数与词 ---")
    # 三份审计（算了没人读 / 文案越界 / 够不着）里属于「数字与话对不上」的那一批，逐条先量后修。
    # ① 味笺那行「现有」以前只有四类，可乐果盘这类「其他」算出来没人读。
    #    paintWei 写进的是隐藏屏，innerText 对隐藏元素返回空串——所以量 textContent。
    struct = page.evaluate("""() => {
      show('wei');
      const mk = (menu) => {
        const r = Engine.wei(menu, [{ name: '我', chips: [] }]);
        paintWei(r, '话术', 4);
        return document.querySelector('#weiResult').textContent;
      };
      return { all: mk('可乐、果盘、冰淇淋、坚果'), mix: mk('红烧肉、拍黄瓜、可乐、果盘'),
               none: mk('红烧肉、清炒时蔬、紫菜蛋花汤、米饭') };
    }""")
    check("四道全是「其他」时那行不再报「一道没有」",
          "荤 0 / 素 0 / 汤 0 / 主食 0 / 其他 4" in struct["all"], True)
    check("混着的时候只补一次，件数跟着走", "其他 2" in struct["mix"], True)
    check("没有「其他」的时候不占字数", "其他" in struct["none"], False)

    # ② 言笺的上限以前是全仓唯一的**头切**，而 lossMsg 说的是「只留最新 200 条」。
    edge = page.evaluate("""() => {
      const d = Date.now();
      state.yanCards = [];
      for (let i = 0; i < 240; i++)
        state.yanCards.push({ k: '待办', line: 'L' + i, text: 'T' + i, when: '', done: false, at: d + i });
      save(state);
      return [state.yanCards.length, state.yanCards[0].line, state.yanCards[state.yanCards.length - 1].line];
    }""")
    check("超上限之后留下的确实是最新那 200 条", edge, [200, "L40", "L239"])
    page.evaluate("() => { state.yanCards = []; save(state); }")   # 别把 200 条垃圾留给下一节

    # ③「数据只在这台设备」与同屏那个网关字段
    #    光把 endpoint 设成死地址不够：renderMe 看见「填过」就会去问一次网关，
    #    那两次 fetch 的失败是以 console.error 记进来的，会把最后「无运行时错误」那格顶红。
    #    所以照第 33 节同一个办法把 gateway 换成桩，量完再收回去。
    page.evaluate("() => { window.JIAN_CONFIG.endpoint = ''; show('me'); }")
    page.wait_for_timeout(200)
    check("没填网关：说的是「数据只在这台设备」",
          "数据只在这台设备" in page.inner_text("#storageNote"), True)
    page.evaluate("""() => {
      if (!window.__realGw2) window.__realGw2 = JianAPI.gateway;
      JianAPI.gateway = async () => ({ on: true, ok: true, model: '桩', tasks: {} });
      window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9'; gwReset(); show('me');
    }""")
    page.wait_for_timeout(200)
    filled = page.inner_text("#storageNote")
    check("填了网关：改成「会发往你填的那个地址」",
          "文字与照片会发往你填的那个地址" in filled, True)
    check("填了网关：那句「只在这台设备」不再出现", "数据只在这台设备" in filled, False)
    page.evaluate("""() => {
      JianAPI.gateway = window.__realGw2; delete window.__realGw2;
      window.JIAN_CONFIG.endpoint = ''; gwReset(); show('me');
    }""")

    # ④ 百分比的分母：照片到 2.8MB 就开始丢，而以前那个百分数拿 5MB 当分母
    pct = page.evaluate("""() => {
      const keep = localStorage.getItem(KEY);
      localStorage.setItem(KEY, 'x'.repeat(SHED_AT));
      const at = storageInfo().pct;
      localStorage.setItem(KEY, 'x'.repeat(Math.round(SHED_AT / 2)));
      const half = storageInfo().pct;
      if (keep === null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, keep);
      return [at, half];
    }""")
    check("那条线走到头就是 100%，而不是 5MB 才算满", pct, [100, 50])
    check("那一行说了满之后会发生什么", "满了先丢照片" in page.inner_text("#storageNote"), True)

    # ⑤ 群话术里那句「两个人」是写死的
    talk = page.evaluate("""() => weiTalk(Engine.wei('米饭、红烧肉', [{ name: '我', chips: [] }]), 'couple', 4)""")
    check("四个人那一桌，话术里写的是四个人", "今晚按 4 个人的胃来。" in talk, True)
    check("写死的「两个人」没有了", "两个人" in talk, False)

    # ⑥ 第 31 轮删掉「放录音」之后，那屏还在教用户存录音
    yan_tiny = page.evaluate("() => [...document.querySelectorAll('#yan .tiny')].map((e) => e.textContent).join(' | ')")
    check("言笺那一屏不再教人存一个没处放的录音", "录音" in yan_tiny, False)
    check("「语音先转文字」这一屏只说一次", yan_tiny.count("语音"), 1)

    print("\n--- 39. 读屏器与键盘够不着的那几处 ---")
    # 审计来的：live region 必须是常驻的、选择卡要能 Tab 到、重建之后焦点要还在同一枚签上、
    # 复选框的名字不许把行上的按钮一起念进去。
    host = page.evaluate("""() => { const h = document.querySelector('#toasts');
      return { exists: !!h, live: h && h.getAttribute('aria-live'), role: h && h.getAttribute('role') }; }""")
    check("提示区是常驻的一个空容器（不是每次新造）", host, {"exists": True, "live": "polite", "role": "status"})
    page.evaluate("() => toast('自证一下：提示该落在常驻容器里')")
    page.wait_for_timeout(120)
    check("提示确实挂在那里面", page.evaluate("() => !!document.querySelector('#toasts .toast')"), True)
    check("节点自己不再挂一份 aria-live（两层 live region 会重复念）",
          page.evaluate("() => !!document.querySelector('#toasts .toast[aria-live]')"), False)
    # 连续两条只留最后一条：这是改掉「每次新造节点」之前就在的行为，别顺手弄丢
    page.evaluate("() => { toast('第一条'); toast('第二条'); }")
    page.wait_for_timeout(120)
    check("后发的覆盖先发的，容器里只有一条", page.evaluate(
        "() => document.querySelectorAll('#toasts .toast').length"), 1)
    page.evaluate("() => document.querySelector('#toasts').replaceChildren()")

    page.evaluate("() => show('wei')")
    page.wait_for_timeout(150)
    check("底栏说得出「我在哪一笺」", page.evaluate(
        "() => [...document.querySelectorAll('#nav button')].filter(b => b.getAttribute('aria-current') === 'page')"
        ".map(b => b.id)"), ["nav-wei"])
    page.evaluate("() => show('yi-report')")
    page.wait_for_timeout(150)
    check("子页（报告）把当前页记在父页那一枚上", page.evaluate(
        "() => (document.querySelector('#nav [aria-current]') || {}).id"), "nav-yi")

    # 引导页那三张：要是能 Tab 到的按钮、aria-pressed 跟着走、而且点一次只中一次
    page.evaluate("() => { state.onboarded = false; save(state); show('onboard'); }")
    page.wait_for_timeout(150)
    check("三张选择卡是真按钮（读屏器与键盘够得着）", page.evaluate(
        "() => [...document.querySelectorAll('#onboard .mode-card')].every(e => e.tagName === 'BUTTON')"), True)
    page.evaluate("() => document.querySelectorAll('#onboard .mode-card')[1].click()")
    page.wait_for_timeout(200)
    check("aria-pressed 只落在选中的那一张上", page.evaluate(
        "() => [...document.querySelectorAll('#onboard .mode-card')].map(e => e.getAttribute('aria-pressed'))"),
        ["false", "true", "false"])
    check("引导页上点一下不该冒出来自「我的」那句提示（两处绑定曾叠在同一批元素上）",
          "打开即是这一笺" in page.inner_text("#toasts"), False)
    check("而且 home 真的换了", page.evaluate("() => state.home"), "wei")
    page.evaluate("() => { state.onboarded = true; save(state); show('yi'); }")

    # 品类那一排签以前重建完就把焦点丢了（四个模块里唯一漏了找回的一处）
    page.wait_for_timeout(200)
    page.evaluate("""() => {
      show('yi');
      window.__cat0 = state.yiCat;          // 这一节改了过滤，收尾要还原（别让下一节以为柜子空了）
      const b = document.querySelector('#yiCats [data-cat="外套"]');
      b.focus(); b.click();
    }""")
    page.wait_for_timeout(150)
    check("按一次 Enter 之后焦点还在同一枚签上", page.evaluate(
        "() => { const a = document.activeElement;"
        " return a.tagName + '|' + (a.dataset.cat || '') + '|' + (a.closest('#yiCats') ? 1 : 0); }"),
        "BUTTON|外套|1")
    check("选中态也念得出来", page.evaluate(
        "() => document.querySelector('#yiCats [data-cat=\"外套\"]').getAttribute('aria-pressed')"), "true")
    page.evaluate("() => { state.yiCat = window.__cat0; save(state); renderCats(); }")

    # 言笺那一行：整行是 label 时，复选框的名字里混进了「挪 / 时间 / 删掉这一条」
    # 上一节收尾把 yanCards 清空了，所以这一节自己种两行——不然下面三格量的就是空集合（假绿）。
    page.evaluate("""() => {
      state.yanCards = [
        { k: '待办', line: '小王：记得把材料发我', when: '周四', who: null, speaker: '小王', done: false },
        { k: '要买', line: '小李说要去买电池', when: null, who: null, speaker: '小李', done: true },
      ];
      state.yanAsk = ''; save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(250)
    check("这一节有行可量（没有的话下面三格是白测）",
          page.evaluate("() => document.querySelectorAll('#yanOut .check').length"), 2)
    check("复选框的名字里不再混着行上的按钮", page.evaluate(
        "() => { const l = document.querySelector('#yanOut .check .ck-main');"
        " return l ? /挪|时间|删掉|×/.test(l.textContent) : '没找到那一行'; }"), False)
    check("动作是 label 的兄弟，不是它的孩子", page.evaluate(
        "() => !!document.querySelector('#yanOut .check .ck-main .acts')"), False)
    check("全 App 没有一个 <label> 里装着 <button>（笺册 / 日期 / 这一行同一条规定）",
          page.evaluate("() => document.querySelectorAll('label button').length"), 0)
    check("五个文字控件都有可读的名字", page.evaluate(
        "() => ['#personName', '#menu', '#yanText', '#apiUrl', '#clothSearch']"
        ".map(s => { const e = document.querySelector(s);"
        " return e && (e.getAttribute('aria-label') || '').length > 0 ? 1 : 0; }).join('')"), "11111")
    check("那个屏幕外的标题确实不占版面", page.evaluate(
        "() => { const r = document.querySelector('#reportTitle').getBoundingClientRect();"
        " return r.width <= 1 && r.height <= 1; }"), True)
    # 标题不能只在过笺那一刻对：换屏也要刷新（show() 里那一手）。这一格自己造一次判定，
    # 不靠上面哪一节先跑过——省掉那一步就只有这里红，别的节照旧绿。
    t8 = page.evaluate("""() => {
      state.lastReport = Object.assign({}, state.lastReport || {}, { stamp: '先别' });
      show('yi'); show('yi-report');
      return document.querySelector('#reportTitle').textContent;
    }""")
    check("判定换了，标题跟着换（换屏前刷新那一步没被省掉）", "先别" in t8, True)

    print("\n--- 41. 每一个可点的东西有多大：一次量全 App ---")
    # 32px 这条线怎么来的：WCAG 2.5.8 的下限是 24，Android 的期待是 48dp，这张纸上的控件密度
    # 放不下 48——取中间那一档。真正的要点是**一次量全部**：以前只有 #closetNote 那一排签
    # 有一条 24px 的下限断言，别处没人量过，于是撤销那枚签实测 18px、开笺的入口 30px、
    # 勾选框 22×13，一直没人知道（第 39 轮）。
    TARGETS = r"""() => {
      const SEL = 'button, input:not([type=hidden]), select, textarea, summary, [role="button"]';
      const out = [];
      const boxes = [];
      let n = 0;
      document.querySelectorAll(SEL).forEach((el) => {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        if (el.closest('.file')) return;                 // 藏起来的文件框不是触摸目标
        const who = (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
          + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '')
          + [...el.attributes].filter(a => a.name.indexOf('data-') === 0)
              .map(a => '[' + a.name + ']').join('')).slice(0, 60);
        // 看得见的那一格：勾框那一格另有 24px 的下限（整行点得到，不代表那一格够大）。
        // 只算**真的看得见**的那些：言笺那两枚勾框在别的屏上是 display:none，
        // 量出来是 0×0 —— 不收这一条就变成「别的屏上有一格 0px 的控件」这种假红。
        if (el.type === 'checkbox') {
          const er = el.getBoundingClientRect();
          if (er.width > 0 && er.height > 0)
            boxes.push({ who, w: Math.round(er.width), h: Math.round(er.height) });
        }
        // 命中区算的是「能点到的那一片」：表单控件在 label 里，点整行都算（勾选框就是这种）
        let box = el;
        if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) {
          const l = el.closest('label');
          if (l) box = l;
        }
        const r = box.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        n++;
        if (Math.min(r.width, r.height) < 32)
          out.push({ who, w: Math.round(r.width), h: Math.round(r.height) });
      });
      return { measured: n, small: out, boxes };
    }"""
    # 把每一屏都撑满并摊开：只有当前那一屏是 display 出来的，逐屏走一遍才量得到全貌
    page.evaluate("""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.points = 3;
      state.album = [{ type: 'yi', t: Date.now(), quote: '一张笺', text: '一张笺\\n第二行' },
                     { type: 'wei', t: Date.now(), quote: '一桌', text: '一桌' }];
      // 勾框只在言笺的行上：§39 会先把 yanCards 填好，可窄跑（e2e_only.py 41）不会先跑 §39——
      // 那时这一节的「确实量到了勾框」就是拿一个空集合量出来的，红得与被测行为无关。
      // 自己种两行：这一节本来就叫「一次量全 App」，它得能自己把要量的面撑起来。
      state.yanCards = [
        { k: '待办', line: '明天把材料发我', when: null, done: false, moved: false, wset: false },
        { k: '要买', line: '买一盒药', when: null, done: true, moved: false, wset: false },
      ];
      state.yanAsk = ''; state.yanView = 'kind'; state.yanHideDone = false;
      save(state);
    }""")
    total, small, boxes = 0, [], []
    measured = {}
    # 0.6.0 把衣笺与味笺各拆成四个页签，而一次只有一页是 display 出来的。
    # 只按屏扫一遍的话，「过笺 / 柜子 / 搭配 / 愿望」只量到第一页，
    # 「排桌 / 做菜 / 买菜 / 这周」也一样——那正是这一节自己反对的「sweep 瞎了」。
    # 所以逐屏 × 逐页签扫：同一个 TARGETS 原样跑，量到的东西只会更多、不会更少。
    SWEEP = [("onboard", None), ("yi", "pass"), ("yi", "closet"), ("yi", "outfit"), ("yi", "wish"),
             ("yi-report", None),
             ("wei", "plan"), ("wei", "cook"), ("wei", "market"), ("wei", "week"),
             ("yan", None), ("me", None)]
    for scr, tab in SWEEP:
        if tab:
            # 页签要在 show() 之后切：setYiTab 会顺手 renderCloset / renderCook 那一页，
            # 先把内容画出来，量到的才不是空壳。
            (yi_tab if scr == "yi" else wei_tab)(page, tab)
        else:
            page.evaluate("(s) => { show(s); }", scr)
        page.wait_for_timeout(200)
        if scr == "yan":       # 摊开之后才有那排日期签与「挑一天」的原生框
            page.evaluate("""() => {
              const m = document.querySelector('#yanOut [data-move]'); if (m) m.click();
              const w = document.querySelector('#yanOut [data-when]'); if (w) w.click();
            }""")
        if scr == "me":        # 开笺那一格展开之后才有它的签；笺册摊开才有「全文 / 收起」
            page.evaluate("""() => {
              const s = document.querySelector('#topup'); if (s) s.open = true;
              const b = document.querySelector('#album [data-aopen]'); if (b) b.click();
            }""")
        page.wait_for_timeout(220)
        r = page.evaluate(TARGETS)
        total += r["measured"]
        label = scr + (":" + tab if tab else "")
        measured[label] = r["measured"]
        small += [dict(x, scr=label) for x in r["small"]]
        boxes += [dict(x, scr=label) for x in r["boxes"]]
    # 撤销那枚签不属于任何一屏：让它正在挂着的时候补量一次
    page.evaluate("() => { toastUndo('自证：撤销那枚签也得够大', () => {}); }")
    page.wait_for_timeout(120)
    rt = page.evaluate(TARGETS)
    total += rt["measured"]
    small += [dict(x, scr="toast") for x in rt["small"]]
    check("这一次真的量到了够多的控件（不够就是 sweep 瞎了）", total >= 70, True)
    # 0.6.0 那八个页签也要真的被扫到：少扫一个页签，这一节的绿就少一格覆盖，
    # 而「扫过 0 个」和「扫过 400 个都没问题」在输出上一模一样。
    # 只数「扫过几个控件」不看它们落在哪个面上，正是这类整片扫最坏的骗法。
    print("        逐面量到：" + " / ".join(f"{k}={v}" for k, v in measured.items()))
    empty_faces = [k for k, v in measured.items() if v <= 0]
    check("八个页签每一面都真的扫到了控件（空的那些就是没扫到）", empty_faces, [])
    check("全 App 没有一个可点的东西小于 32px（按命中区算）",
          [(x["scr"], x["who"], x["w"], x["h"]) for x in small], [])
    check("确实量到了勾框（没有的话下面那格是空集合）", len(boxes) >= 1, True)
    check("看得见的那一格勾框也不许小于 24（整行点得到，不等于那一格够大）",
          [(x["scr"], x["who"], x["w"], x["h"]) for x in boxes
           if min(x["w"], x["h"]) < 24], [])
    check("撤销那枚签确实在被量的这批里（不在就是空集合假绿）", page.evaluate(
        "() => !!document.querySelector('#toasts .toast.act button')"), True)
    # 缩放：关掉它挡不住任何布局问题（放大只是放大，不重排），却把「字被省略号吃掉」
    # 时用户唯一的自救办法一起关掉了
    vp = page.evaluate("() => (document.querySelector('meta[name=viewport]') || {}).content || ''")
    check("viewport 里不再锁缩放", "user-scalable=no" in vp or "maximum-scale" in vp, False)
    check("viewport 仍然带着宽度与安全区", "width=device-width" in vp and "viewport-fit=cover" in vp, True)

    print("\n--- 42. 味笺那四张模式签：按下去要真的换一桌 ---")
    # 「家里这桌，硬菜和雷放后面」「同事这桌，先保全员能入口」这两句从第九轮就印在屏上，
    # 而 mode 从来没进过判定：四张签排出来逐字节相同。现在它进了排序键，
    # 这一节量的是**屏幕上那一桌**，不是引擎里的数组。
    # 四张模式签、#menu、#runWei、#weiStale、#reWei 全在排桌页签里（0.6.0），
    # 停在别的页签上 `page.click("#runWei")` 会超时。
    wei_tab(page, "plan")
    page.evaluate("""() => {
      state.points = 20; state.weiMode = 'friends';
      state.people = [{ name: '我', chips: ['辣'] }];
      save(state);
      const m = document.querySelector('#menu');
      m.value = '白灼菜心\\n红烧肉\\n水煮鱼\\n米饭';
      m.dispatchEvent(new Event('input'));
    }""")
    page.wait_for_timeout(200)
    page.click("#runWei")
    wait_ok("() => !!document.querySelector('#weiResult .serving .dish')", 15000, "第一桌排出来了")

    def served():
        return page.eval_on_selector_all("#weiResult .serving .dish", "els => els.map(e => e.textContent)")

    def rerun(mode):
        page.click(f'[data-weimode="{mode}"]')
        page.wait_for_timeout(150)
        bar = page.evaluate("() => { const b = document.querySelector('#weiStale');"
                            " return b && b.style.display !== 'none' ? b.querySelector('.tiny').textContent : ''; }")
        if bar:
            page.click("#reWei")
            wait_ok("() => document.querySelector('#weiStale').style.display === 'none'", 15000,
                    "重排之后那根「上一版」的条收了")
        # 没提示就不点重排——那一桌本来就是旧的。这里必须让**按名字的断言**去红：
        # 以前断言排在「点不动的那一枚按钮」后面，注入进来只剩一条 TimeoutError，
        # 什么都没说（认证时撞的就是这个，见 NEXT.md 第四十轮）。
        return bar, served()

    friends = served()
    check("朋友那桌：硬菜在水煮鱼之前、米饭收尾", friends, ["白灼菜心", "红烧肉", "水煮鱼", "米饭"])
    stale_work, work = rerun("work")
    check("换到同事那桌：先说「这桌的人换了」（不声不响换判定=骗人）", "这桌的人换了" in stale_work, True)
    check("同事那桌：只把有人忌的压后，硬菜照旧先上", work, ["白灼菜心", "红烧肉", "米饭", "水煮鱼"])
    stale_home, home = rerun("home")
    check("家里那桌：硬菜也一起压到最后", home, ["白灼菜心", "米饭", "红烧肉", "水煮鱼"])
    check("三种桌序两两不同（屏幕上真的换了一桌）", len({tuple(friends), tuple(work), tuple(home)}), 3)
    check("换回原来那桌时不再提示过期（lastWei.mode 读的是这一桌当时那个）",
          page.evaluate("() => document.querySelector('#weiStale').style.display"), "none")
    page.evaluate("() => { state.lastWei = null; state.points = 0; save(state); }")

    print("\n--- 43. 「已导出备份」「已保存长图」以前在原生里是假话 ---")
    # App 里没有「下载」这回事：a.click() 在 WebView 里什么都不做。
    # 而系统的分享面板即使用户划走也照样 resolve——所以原生这一路最多只能说「交出去了」。
    # 以前两条路都 toast「已导出 / 已保存」，文件从来没出现过。
    def bridge_page(share_fails):
        c = browser.new_context(viewport={"width": 430, "height": 940})
        c.add_init_script("""(() => {
          const nap = () => new Promise((r) => setTimeout(r, 60));
          window.__dl = null;
          const orig = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function () {
            if (this.download) { window.__dl = this.href; return; }
            return orig.call(this);
          };
          window.__sharefail = %s;
          window.Capacitor = { Plugins: {
            Preferences: { get: async () => ({ value: null }), set: async () => ({}), remove: async () => ({}) },
            Filesystem: { writeFile: async () => ({}), getUri: async (o) => ({ uri: 'file://x/' + o.path }) },
            Share: { share: async () => { await nap();
              if (window.__sharefail) throw new Error('User cancelled'); return { value: true }; } },
          } };
        })()""" % ("true" if share_fails else "false"))
        p = c.new_page()
        p.goto(URL)
        p.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
        return c, p

    def page_disabled(p, sel):
        return p.evaluate("(s) => { const e = document.querySelector(s);"
                          " return e ? e.getAttribute('aria-disabled') === 'true' : '没这个按钮'; }", sel)

    def clear_toast(p):
        # 必须在**按之前**清：这些路径里 toast 是同步或几百毫秒内就出现的，
        # 按完再去清，等于把刚要读的那一条擦掉（第一版就这么假红过一次）。
        p.evaluate("() => { const h = document.querySelector('#toasts'); if (h) h.replaceChildren(); }")

    def p_toast(p, sub, ms=9000, why=None):
        """等一句提示。等不到要报成**点名的一格**，不能让它以 TimeoutError 收场：
        崩了的话认证报告上写的是「崩在无断言处」，那条注入等于没被任何一句话抓住。"""
        try:
            p.wait_for_function("() => { const t = document.querySelector('.toast');"
                                " return !!t && t.textContent.indexOf("
                                + json.dumps(sub, ensure_ascii=False) + ") >= 0; }", timeout=ms)
            return True
        except Exception:
            check("等不到：" + (why or ("提示里出现「" + sub + "」")), False, True)
            return False

    c1, p1 = bridge_page(False)
    p1.evaluate("() => { state.onboarded = true; show('me'); }")
    p1.wait_for_timeout(200)
    clear_toast(p1)
    p1.click("#exportData")
    p_toast(p1, "分享", 9000, "备份：原生面板起来了")
    t1 = p1.inner_text(".toast")
    check("原生 + 面板起来了：说的是「交给系统的分享」", "交给系统的分享" in t1, True)
    check("不再冒充「已导出」", "已导出" in t1, False)
    c1.close()

    c2, p2 = bridge_page(True)
    p2.evaluate("() => { state.onboarded = true; show('me'); }")
    p2.wait_for_timeout(200)
    clear_toast(p2)
    p2.click("#exportData")
    check("原生 + 面板没起来：说实话", p_toast(p2, "没起来", 9000, "备份：分享失败要说没起来")
          and "系统的分享没起来" in p2.inner_text(".toast"), True)
    check("也没有偷偷走一次点不动的假下载", p2.evaluate("() => window.__dl === null"), True)
    # 长图那一处走的是同一条规矩：面板没起来就不能说「已保存」。
    # 现造一份判定：Engine.yi 给得出桌序/依据，但 `new`（那件要画的衣）是 yi.js 贴上去的，
    # 少了它 saveCard 会直接 return——第一版就因此什么都没等到。
    p2.evaluate("""() => {
      const it = { name: '要买的外套', cat: '外套', color: '#123456' };
      state.lastReport = Object.assign(Engine.yi(it, state.wardrobe), { new: it });
      save(state); show('yi-report'); paintReport(); window.__dl = null;
    }""")
    p2.wait_for_timeout(250)
    check("有判定时那枚章不挡（读的是 aria-disabled，不是真 disabled）", page_disabled(p2, "#saveCard"), False)
    clear_toast(p2)
    p2.click("#saveCard")
    check("长图那一处也一样说实话", p_toast(p2, "没起来", 15000, "长图：分享失败要说没起来")
          and "系统的分享没起来" in p2.inner_text(".toast"), True)
    check("长图也没有走那次假下载", p2.evaluate("() => window.__dl === null"), True)
    # 没有判定的时候这枚章该被挡。第 57 轮起「挡」= 标 aria-disabled + 按下去说得出为什么，
    # 不再是用真 disabled 把它按不动——那对读屏器和键盘是隐形的，连为什么都问不到。
    p2.evaluate("() => { state.lastReport = null; save(state); show('yi-report'); paintReport(); }")
    p2.wait_for_timeout(200)
    check("没有可画的判定时那枚章被标成「此刻不许用」", page_disabled(p2, "#saveCard"), True)
    check("但它没有被真 disabled —— 仍然聚焦得到、按得下去",
          p2.evaluate("() => document.querySelector('#saveCard').disabled"), False)
    clear_toast(p2)
    press(p2, "#saveCard")        # 它现在是「挡着但照样按得下去」，见 press() 的说明
    check("按下去说得出原因（不是又一枚沉默的章）",
          p_toast(p2, "先过一张笺", 6000, "存长图被挡时该说的那句")
          and "先过一张笺" in p2.inner_text(".toast"), True)
    c2.close()

    c3, p3 = browser.new_context(viewport={"width": 430, "height": 940}), None
    p3 = c3.new_page()
    p3.add_init_script("""(() => { window.__dl = null;
      const orig = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () {
        if (this.download) { window.__dl = this.href; return; } return orig.call(this); }; })()""")
    p3.goto(URL)
    p3.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    p3.evaluate("() => { state.onboarded = true; show('me'); }")
    p3.wait_for_timeout(200)
    clear_toast(p3)
    p3.click("#exportData")
    check("浏览器那一路：说的是下载里能看到",
          p_toast(p3, "下载", 9000, "浏览器：该指到下载里去看")
          and "浏览器的下载里能看到" in p3.inner_text(".toast"), True)
    check("而且真的发起了一次下载（blob）", str(p3.evaluate("() => window.__dl")).startswith("blob:"), True)
    c3.close()

    print("\n--- 44. 「最近一次判定是网关给的」要说得出是哪一笺，而且得是最近那一次 ---")
    # 以前 api.js 的 status() 不带参数时是 some(via === 'remote')：
    # 只要历史上有任何一笺走过网关，这句就一直为真——哪怕刚连着两笺都回落了本地。
    # 顶栏那一行第十九轮就修过了，这是同一颗雷留在「我的」屏上的另一半。
    class GwStub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        # file:// 这一侧的 origin 是 null，带 JSON Content-Type 的 POST 会先走 preflight；
        # 不给这三行的话每一次都是 CORS 挡下，note() 记到的就是「连不上」而不是我要测的那两种。
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def _send(self, code, obj):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            # 「我的」那一屏会去问 /v1/status（#apiModel 那行）。不接这一笔的话
            # 基类回 501、没有 CORS 头，最后两格「无运行时错误」被它顶红。
            self._send(200, {"ok": True, "model": {"on": True, "model": "stub-44"},
                             "tasks": {"recognize": True, "ocr": True}})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            if self.path.endswith("/v1/see"):
                self._send(200, {"stamp": "宜入", "quote": "网关给的那一笺", "gap": 99, "basis": None})
            else:
                # 形状不对：不是判定该有的东西。网关活着在说话，所以这一笔**不进**冷却，
                # 记的是「local + 一句原因」——正好是要被念出来的那一种最近。
                self._send(200, {"ok": True})

    gwsrv = ThreadingHTTPServer(("127.0.0.1", 0), GwStub)
    gwport = gwsrv.server_address[1]
    threading.Thread(target=gwsrv.serve_forever, daemon=True).start()
    try:
        page.evaluate("(p) => { window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:' + p;"
                      " state.apiUrl = window.JIAN_CONFIG.endpoint; gwReset(); }", gwport)
        # ① 衣笺走了网关，随后味笺被网关回了句不是判定的东西 → 最近的是味笺，落回本地
        page.evaluate("async () => { await JianAPI.yi({ name: '外套', cat: '上衣', color: '#123456' }, state.wardrobe); }")
        page.wait_for_timeout(30)      # 时间戳要分得出先后（同一毫秒里 reduce 会留下先那条）
        page.evaluate("async () => { await JianAPI.wei('米饭', [{ name: '我', chips: [] }]); }")
        page.evaluate("() => { show('me'); }")
        page.wait_for_timeout(250)
        line1 = page.inner_text("#apiState")
        check("说的是最近那一笺（味笺），不是历史上任何走过网关的一笺",
              "味笺" in line1 and "衣笺" not in line1, True)
        check("并且照旧说清那张是本地规则算的（第十六轮的口径）", "本地规则算的" in line1, True)
        # ② 反过来：味笺先来一次不对的形状，衣笺最后真的走通了网关 → 这次该说衣笺
        page.evaluate("async () => { await JianAPI.wei('米饭', [{ name: '我', chips: [] }]); }")
        page.wait_for_timeout(30)
        page.evaluate("async () => { await JianAPI.yi({ name: '外套', cat: '上衣', color: '#123456' }, state.wardrobe); }")
        page.evaluate("() => { show('me'); }")
        page.wait_for_timeout(250)
        line2 = page.inner_text("#apiState")
        check("顺序换了，那句话也跟着换（不是写死某一笺）",
              "衣笺" in line2 and "网关给的" in line2, True)
        check("没有笺名时不念 undefined", "undefined" in line1 + line2, False)
    finally:
        gwsrv.shutdown()
        page.evaluate("() => { window.JIAN_CONFIG.endpoint = ''; state.apiUrl = ''; gwReset(); }")

    print("\n--- 45. 删掉的死代码没有回来，删它也没有改判定 ---")
    # 审计扫出来的「算了没人读」那一批里，能安全删的只有这几处零调用者的东西；
    # 引擎导出面上的字段大多**留着**——它们是差分 fuzz 的比对面（第 24 轮的教训：
    # 白名单/挑字段比对会把漂移藏起来，删掉被比的字段等于把能看见问题的地方凿掉）。
    # 所以这里钉两件事：死函数别被「以后可能用」再塞回来；删的那句可达的话行为不变。
    check("零调用者的 Engine.avgColor 已经不在", page.evaluate("() => typeof Engine.avgColor"), "undefined")
    check("零调用者的 JianAPI.waiting 已经不在", page.evaluate("() => typeof JianAPI.waiting"), "undefined")
    # 取色要绕开种子柜子里那几个色——不然 stamp 不是「宜入」，走的是另一支文案，
    # 这一格就会因为柜子而不是因为被测的东西红。所以逐个试，取第一个判成宜入的。
    q = page.evaluate("""() => {
      const cands = ['#7a1f2b', '#112233', '#0f7a55', '#e8a13c', '#5b2d8e', '#c2b1a3'];
      const pick = (extra) => {
        for (const c of cands) {
          const it = Object.assign({ name: '一件', cat: '上衣', color: c }, extra);
          const r = Engine.yi(it, state.wardrobe);
          if (r.stamp === '宜入') return r.quote;
        }
        return null;
      };
      return { pat: pick({ pattern: 0.9 }), plain: pick({}) };
    }""")
    check("试得出宜入的那一笺（试不出来说明这一格在空转）",
          q["pat"] is not None and q["plain"] is not None, True)
    check("花纹那一笺还是原来那句话（删掉中间那条没把它顶掉）",
          q["pat"], "这个色柜里空着。买回去，旧的几件会重新好穿。")
    check("普通新色那一笺取的是表首（带件数那句）", "它能解开" in q["plain"], True)

    print("\n--- 46. 动作不许埋在它所作用的列表底下；勾一下不再重建整片 ---")
    # 探针量出来的两个数（360×720、数据顶到上限）：言笺 200 条时「复制整张笺」在首屏下
    # 40.5 屏，笺册 24 张时「导出备份」在 3.7 屏。攒了一年记录的人想看那枚按钮，
    # 得先划过自己一年的聊天记录——而这两枚一个管备份、一个管出口。
    # 守两条：DOM 顺序（动作在列表之前，与视口无关）+ 距离上限（挡「把按钮塞回表尾」）。
    page.evaluate("""() => {
      window.__before46 = JSON.stringify({ yan: state.yanCards, album: state.album,
        hide: state.yanHideDone, view: state.yanView });
      const DAY = 86400000, now = Date.now();
      state.yanCards = Array.from({length: 200}, (_, i) => ({
        k: ["待办","要买","已定","还没说清"][i % 4], line: "买酱油、卫生纸、两节五号电池" + i,
        when: i % 3 === 0 ? { text: "月底前", at: now + 3 * DAY } : null,
        done: false, moved: false, wset: false }));
      state.album = Array.from({length: 24}, (_, i) => ({ type: ["yi","wei","yan"][i % 3],
        t: now - i * DAY, quote: "这件外套的色号在你柜子里其实有第三件相近的" + i, text: "正文" + i }));
      state.yanHideDone = false; state.yanView = "kind";
      save(state);
    }""")
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(400)
    y46 = page.evaluate("""() => {
      const vh = window.innerHeight;
      const scr = (sel) => { const e = $(sel); return e ? Math.round((e.getBoundingClientRect().top + window.scrollY) / vh * 10) / 10 : null; };
      const cp = $('#copyYan'), cl = $('#clearYan'), first = $('#yanOut .check');
      const after = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      return { copy: scr('#copyYan'), clear: scr('#clearYan'), rows: $$('#yanOut .check').length,
               beforeList: !!(cp && first) && after(cp, first), bothThere: !!(cp && cl) };
    }""")
    check("200 条一条不少（先确认这一格不是数空气）", y46["rows"], 200)
    check("「复制整张笺」在这一屏之内（≤2 屏，以前 40.5 屏）",
          y46["copy"] is not None and y46["copy"] <= 2, True)
    check("「清空这张」还在，且也在这一屏之内",
          y46["bothThere"] and y46["clear"] is not None and y46["clear"] <= 2, True)
    check("整张笺的动作排在行之前（DOM 顺序，不随视口变）", y46["beforeList"], True)

    # 勾一下要就地改。以前每次勾选都 renderYan()：200 条 = 1696 个节点重摆一遍，
    # 桌面 Chromium 光布局 34ms（JS 只占 2ms），手机上是一次看得见的顿。
    patched = page.evaluate("""() => {
      const row = document.querySelector('#yanOut .check');
      row.__stamp = 'alive';
      const cb = row.querySelector('input[data-yi]');
      const t0 = performance.now();
      cb.click();
      return { ms: Math.round((performance.now() - t0) * 10) / 10, same: document.querySelector('#yanOut .check').__stamp === 'alive' };
    }""")
    check("勾第一条之后那一行还是原来那个节点（没整片重建）", patched["same"], True)
    p46 = page.evaluate("""() => ({
      head: $('#yanCount').textContent, prune: $('#yanPrune').textContent, hidden: $('#yanPrune').hidden,
      grp: document.querySelector('[data-yangroup="待办"]').textContent, done: state.yanCards[0].done,
      rows: $$('#yanOut .check').length })""")
    check("state 里真的勾上了", p46["done"], True)
    check("顶上那行计数当场跟着改", p46["head"], "200 条 · 已勾 1")
    check("所属类别的 0/50 跟着改成 1/50", p46["grp"], "1/50")
    check("「清掉勾掉的」从收起到露出且数目对", [p46["hidden"], p46["prune"]], [False, "清掉勾掉的 1"])
    check("那一行自己也要变成勾过的样子（就地改的不只是数字）",
          page.evaluate("() => document.querySelector('#yanOut .check').classList.contains('done')"), True)
    check("勾一下不会让条目变少", p46["rows"], 200)

    # 就地打补丁最怕的是「屏上的数」和「重建出来的数」分家——那正是本轮在修的那一类谎。
    same46 = page.evaluate("""() => {
      const snap = () => [ '#yanCount=' + $('#yanCount').textContent, '#yanPrune=' + $('#yanPrune').textContent,
        ...[...document.querySelectorAll('[data-yangroup]')].map((e) => e.dataset.yangroup + '=' + e.textContent) ];
      const a = snap().sort();
      renderYan();
      return JSON.stringify([a, snap().sort()]);
    }""")
    pair46 = json.loads(same46)
    check("这一格数得出三处计数（不是拿两个空数组比出来的绿）", len(pair46[0]) >= 6, True)
    check("就地打补丁的三处计数与整片重建完全一致（就地补丁不撒谎）", pair46[0], pair46[1])
    page.evaluate("() => { $$('#yanOut input[data-yi]').slice(0, 10).forEach((cb) => { if (!cb.checked) cb.click(); }); }")
    ten = page.evaluate("""() => ({ head: $('#yanCount').textContent, prune: $('#yanPrune').textContent,
      real: state.yanCards.filter((c) => c.done).length, grp: document.querySelector('[data-yangroup="待办"]').textContent })""")
    check("连勾十条之后屏上的数还是等于 state 里的数",
          [ten["head"], ten["prune"], ten["real"], ten["grp"]],
          ["200 条 · 已勾 10", "清掉勾掉的 10", 10, "10/50"])
    # 这枚现在一直挂在 DOM 里、靠 hidden 收放（就地改文字要它常在）。常在可以，
    # 一条没勾时还露着就是又一枚「按了没用的按钮」——第 27 轮定的那条规矩没作废。
    un46 = page.evaluate("""() => {
      $$('#yanOut input[data-yi]').slice(0, 10).forEach((cb) => { if (cb.checked) cb.click(); });
      return { hidden: $('#yanPrune').hidden, head: $('#yanCount').textContent,
               grp: document.querySelector('[data-yangroup="待办"]').textContent,
               done: document.querySelector('#yanOut .check').classList.contains('done'),
               real: state.yanCards.filter((c) => c.done).length };
    }""")
    check("全取消之后这枚自己收回去，计数回到 0",
          [un46["hidden"], un46["head"], un46["grp"], un46["real"], un46["done"]],
          [True, "200 条 · 已勾 0", "0/50", 0, False])
    # 「只看没办的」里刚勾上那一条要从屏上消失、分组要重算——就地做不到，必须退回重建。
    hide46 = page.evaluate("""() => {
      state.yanHideDone = true; save(state); renderYan();
      const before = $$('#yanOut .check').length;
      document.querySelector('#yanOut input[data-yi]').click();
      return { before, now: $$('#yanOut .check').length, head: $('#yanCount').textContent,
               same: state.yanCards.filter((c) => !c.done).length };
    }""")
    check("「只看没办的」里勾上：这一条当场从屏上消失（退回整片重建）",
          hide46["now"], hide46["before"] - 1)
    check("那句「没办 N · 已勾 M」说的是真数", hide46["head"],
          f"没办 {hide46['same']} · 已勾 {200 - hide46['same']}")
    page.evaluate("() => { state.yanHideDone = false; save(state); renderYan(); }")

    page.evaluate("() => show('me')")
    page.wait_for_timeout(400)
    m46 = page.evaluate("""() => {
      const vh = window.innerHeight;
      const scr = (sel) => { const e = $(sel); return e ? Math.round((e.getBoundingClientRect().top + window.scrollY) / vh * 10) / 10 : null; };
      const aa = $('#album'), ex = $('#exportData');
      const out = { drawn: $$('#album .card').length, ex: scr('#exportData'), im: scr('#importData'), rs: scr('#reset'),
                    beforeList: !!(ex && aa) && !!(ex.compareDocumentPosition(aa) & Node.DOCUMENT_POSITION_FOLLOWING),
                    stored: state.album.length };
      const t = $('#albumChips [data-aall]');
      if (t) { t.click(); out.afterExpand = { ex: scr('#exportData'), drawn: $$('#album .card').length }; }
      return out;
    }""")
    check("笺册存 24 张、画 ALBUM_PAGE 张（先确认有东西在撑页面）",
          [m46["stored"], m46["drawn"]], [24, 12])
    check("备份两枚与「清空本地数据」都在一屏半之内（以前 3.7 屏）",
          all(m46[k] is not None and m46[k] <= 2 for k in ("ex", "im", "rs")), True)
    check("备份排在笺册前面", m46["beforeList"], True)
    check("摊开成 24 张之后，备份还是那一屏（不跟着往下跑）",
          [m46["afterExpand"]["drawn"], m46["afterExpand"]["ex"] <= 2], [24, True])

    # 同一把尺量全 App：每一屏**最后一个 .btn** 不许超过两屏。
    # 上面那三处不是三个 bug，是一个习惯——「先画数据，再摆按钮」。
    #
    # 「我的」这一屏在 0.6.0 被重排成**七块**（个人卡 / 三个入口 / 钱包与订阅 / 数据与备份 /
    # 笺册 / 网关 / 数据体检，见 me.js:311 那一行 me.append）。而这条规矩要挡的是
    # 「一枚按钮被**它自己作用的那份数据**挤到天边」——按整屏量，在七块的结构上量到的
    # 是「这一块排在那一块后面」，跟这条规矩管的不是同一件事：
    # `#saveApi`（保存接口，实测 3.2 屏）上面压着的是笺册那 24 张——它**不作用于**笺册，
    # 它作用的 `#apiUrl` 就在它上面一行。所以「我的」改成**按块量**：
    # 每一块里最后一枚 .btn 到这一块顶的距离必须 ≤2 屏（块自己的清单长了、按钮跟着往下跑，
    # 那才是要挡的那件事；块与块之间谁排前面是版式，不是这条规矩）。判据一个数字都没放宽：
    # 还是 ≤2 屏，只是把它量在「按钮与它作用的数据」同一块之内。
    # 另外四屏（yi / wei / yan / settings）仍然按整屏量，一个字没动。
    page.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      const CATS = ["上衣","裤装","裙装","外套","鞋","包"];
      state.wardrobe = Array.from({length: 36}, (_, i) => ({ id: "c" + i,
        name: "衣服" + i, cat: CATS[i % 6], color: "#" + (0x223344 + i * 0x0b0b0b).toString(16).slice(0, 6),
        worn: 30 - i, lastWorn: now - i * 3 * DAY }));
      save(state);
    }""")
    last_btn = {}
    # 每一屏/每个页签按它自己的样子量。「衣笺」的 `.btn` 只在**过笺**与**愿望**两个页签里
    # （柜子那一页的最后一排是 36 件瓷砖底下的 `#clothActions`，而它本来就该在网格下面——
    # 0.5.x 那一版之所以量到「2 枚、0.4 屏」，是因为那时没有选中的件、操作条是空的；
    # 柜子那一页自己的规矩是「选中之后编辑器要滚进视野」，下面单独有一条守着它）。
    # 「设置」那一屏整屏没有 `.btn`（它那一排是 chip 与 rowbtn）。
    # 所以量的是「**这一面里**最后一枚 .btn 的屏距」，面按页签拆开。
    # 没有 `.btn` 的那一面（设置）**换成它真有的那类动作**量：`#setResetAll`
    # （`.chip`，整屏最后一枚能按的东西）。判据还是同一条「≤2 屏」。
    FACES = [("yi", "pass"), ("wei", "plan"), ("yan", None), ("me", None), ("settings", None)]
    # 没有 .btn 的面：改用这一枚（各自那一面最后一枚、且属于「动作」那一类）
    NO_BTN_SEL = {"settings": "#setResetAll"}
    last_btn = {}
    for scr, tab in FACES:
        page.evaluate("(id) => show(id)", scr)
        page.wait_for_timeout(300)
        if tab:
            (yi_tab if scr == "yi" else wei_tab)(page, tab)
            page.wait_for_timeout(300)
        face = scr + (":" + tab if tab else "")
        last_btn[face] = page.evaluate("""([byBlock, altSel]) => {
          const vh = window.innerHeight;
          const vis = (el) => !el.hidden && el.offsetParent !== null;
          const scr = document.querySelector('.screen.on');
          if (byBlock) {
            // 按块量：块 = .me-sec（预算里没有「块」的屏就退回整屏）
            const secs = [...scr.querySelectorAll('.me-sec')];
            const scope = secs.length ? secs : [scr];
            let n = 0, far = 0;
            for (const s of scope) {
              const btns = [...s.querySelectorAll('.btn')].filter(vis);
              if (!btns.length) continue;
              const top = s.getBoundingClientRect().top + window.scrollY;
              n += btns.length;
              far = Math.max(far, ...btns.map((el) =>
                ((el.getBoundingClientRect().top + window.scrollY) - top) / vh));
            }
            return { n, far: Math.round(far * 10) / 10, sel: '.btn（按块）' };
          }
          const btns = [...scr.querySelectorAll('.btn')].filter(vis);
          if (!btns.length) {
            // 这一面没有 .btn：换它的动作那一类来量（同一把「≤2 屏」的尺）
            const alt = altSel ? [...scr.querySelectorAll(altSel)].filter(vis) : [];
            if (!alt.length) return { n: 0, far: 0, sel: altSel };
            const f = Math.max(...alt.map((el) => (el.getBoundingClientRect().top + window.scrollY) / vh));
            return { n: alt.length, far: Math.round(f * 10) / 10, sel: altSel };
          }
          const far = Math.max(...btns.map((el) => (el.getBoundingClientRect().top + window.scrollY) / vh));
          return { n: btns.length, far: Math.round(far * 10) / 10, sel: '.btn' };
        }""", [scr == "me", NO_BTN_SEL.get(face)])
        whose = last_btn[face]["sel"]
        check(f"{face}：数据顶到上限时最后一个 {whose} 还在两屏之内"
              f"（{last_btn[face]['n']} 枚，最远 {last_btn[face]['far']} 屏）",
              last_btn[face]["n"] > 0 and last_btn[face]["far"] <= 2, True)
    # 上面那个按块量法要能看见东西（不是拿 0 枚量出来的绿）：这一格把「我的」每一块
    # 各自的按钮数与「到这一块顶」的最远距离数出来。块数是**动态**的：`.me-sec` 由
    # me.js:264 的 sec() 现造，只有钱包 / 数据与备份 / 网关 / 笺册四块给了标题与 id
    # （个人卡 #meProfile 与数据体检 #meHealth 是 div，三个入口 #meLinks 是 list）。
    # 所以这里数的不是「七块」，是「**有按钮的那几块**都量到了」——
    # 原来写死 7 会把版式当成被测行为（那是 `show('me')` 那一屏的块数，不是规矩）。
    me_blocks = page.evaluate("""() => {
      show('me');
      const vh = window.innerHeight;
      const vis = (el) => !el.hidden && el.offsetParent !== null;
      return [...document.querySelectorAll('#me .me-sec')].map((s) => {
        const btns = [...s.querySelectorAll('.btn')].filter(vis);
        const top = s.getBoundingClientRect().top + window.scrollY;
        return [s.id, btns.length, btns.length
          ? Math.round(Math.max(...btns.map((el) => ((el.getBoundingClientRect().top + window.scrollY) - top) / vh)) * 10) / 10
          : null];
      });
    }""")
    check("「我的」那几块里，带按钮的两块都量得出距离（不是拿空块量出的绿）",
          [len(me_blocks) >= 4, [[b[0], b[1]] for b in me_blocks if b[1] > 0]],
          [True, [["meSecData", 2], ["meSecNet", 1]]])

    # 第三处同病：柜子里点中第 1 件（共 36 件），App 说「已选中」，可那块改名/品类/
    # 季节/主色的编辑器落在整张网格底下六屏处——屏上什么都没变，这句话就等于没说。
    # 36 件瓷砖和它下面那枚操作条都在柜子页签里（0.6.0），停在过笺上这两条会空过。
    yi_tab(page, "closet")
    page.evaluate("() => { window.scrollTo(0, 0); }")
    page.wait_for_timeout(300)
    page.evaluate("() => document.querySelector('#closet .item[data-id]').click()")
    pick = page.evaluate("() => ({ sel: state.clothSel, tiles: $$('#closet .item[data-id]').length })")
    check("柜子里 36 件都在（先确认这一格有东西可撑；末尾那枚 ＋ 不入网格数据）", pick["tiles"], 36)
    check("点第 1 件真的选中了", pick["sel"], "c0")
    # 等到它真的进视野再读位置：滚动可能是平滑的，点完立刻读会量到半路的位置（假红）。
    wait_ok("() => { const b = document.querySelector('#clothActions .action-bar');"
            " if (!b) return false; const r = b.getBoundingClientRect();"
            " return r.top < window.innerHeight * 0.9 && r.bottom > 0; }",
            3000, "选中之后编辑器滚进视野（以前它在整张网格底下六屏处）")
    check("改名那一格就在首屏里", page.evaluate(
        "() => { const n = $('#clothName'); return !!n && n.getBoundingClientRect().top < window.innerHeight; }"), True)
    page.evaluate("() => { state.clothSel = null; save(state); renderCloset(); }")

    page.evaluate("""() => { const b = JSON.parse(window.__before46);
      state.yanCards = b.yan; state.album = b.album; state.yanHideDone = b.hide; state.yanView = b.view;
      delete window.__before46; save(state); renderYan(); renderMe(); }""")

    print("\n--- 47. 320px 窄屏 + 每一项都顶到校验上限：不撑破，也不许悄悄裁字 ---")
    # 320 是安卓上够得着的最窄一档（老机型、折叠屏外屏、系统字号拉到最大都会到这一档）。
    # 这一节是把第 44 轮那支一次性的探针搬进守门：量的不是「哪一处坏了」，是一条全局规矩——
    # 名字 40 字、言笺正文 500 字、菜单 4000 字、网关地址 200 字、柜子 36 件、笺册 24 张
    # **同时**拉满时，既不把版面撑破，也不许把字裁了又不给省略号（那等于信息静悄悄不见了）。
    nctx = browser.new_context(viewport={"width": 320, "height": 720}, device_scale_factor=1)
    nwp = nctx.new_page()
    nwp_errs = []
    nwp.on("pageerror", lambda e: nwp_errs.append(str(e)))
    nwp.clock.install(time="2026-09-17T10:00:00")
    nwp.goto(URL)
    nwp.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    nwp.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      const NAME40 = "雾霾蓝羊毛混纺oversize落肩宽松针织开衫外套加长版整整四十个字占满上限";
      const LINE500 = ("周五之前把预付定金的尾款补齐并且顺手约一下周末上门清洗油烟机的那位师傅").repeat(20);
      const CHIPS = ["辣","香菜","海鲜","花生","猪肉","牛羊肉","内脏","蒜","酒","乳","清淡"];
      const CATS = ["上衣","裤装","裙装","外套","鞋","包"];
      state.wardrobe = Array.from({length: 36}, (_, i) => ({ id: "n" + i,
        name: (i % 3 === 0 ? NAME40 : "普通衣服" + i), cat: CATS[i % 6],
        color: "#" + (0x223344 + i * 0x0b0b0b).toString(16).slice(0, 6),
        worn: 30 - i, lastWorn: now - i * 3 * DAY }));
      state.people = Array.from({length: 5}, (_, i) => ({ name: "隔壁部门新来的同事小赵和小李两位" + i, chips: CHIPS }));
      state.weiMenu = ("川味水煮牛肉配青红花椒与二荆条干辣椒、宫保鸡丁、白灼菜心、紫菜蛋花汤、米饭。").repeat(60)
        + "今天八个人吃，有人不吃辣，海鲜也少碰。"
        + "另外这次是部门聚餐预算有限所以太贵的两个方案先放一放等我把报销单批下来再说清楚。";
      state.yanCards = [0,1,2,3,4].map((i) => ({ k: ["待办","要买","已定","还没说清"][i % 4],
        line: LINE500.slice(0, 500) + i, when: { text: "月底前", at: now + 3 * DAY },
        done: false, moved: false, wset: false, who: "王小李师傅" }));
      state.album = Array.from({length: 24}, (_, i) => ({ type: ["yi","wei","yan"][i % 3], t: now - i * DAY,
        quote: "这件外套的色号在你柜子里其实有第三件相近的，先别买" + i, text: "正文" + i }));
      state.apiUrl = "https://gateway.example-company.internal.lan:8443" + "/api/jian/v1/slip";
      state.onboarded = true;
      save(state);
    }""")
    nwp.reload()
    nwp.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    NARROW = """() => {
      const vw = document.documentElement.clientWidth;
      const sc = document.scrollingElement || document.documentElement;
      const inScroller = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll') return true; } return false; };
      const tag = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
      const screen = document.querySelector('.screen.on');
      const over = [], cx = [];
      for (const el of (screen ? screen.querySelectorAll('*') : [])) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
        if (el.classList.contains('sr-only')) continue;      // 1×1 那格是给读屏器的，本来就该看不见
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        if (r.right > vw + 1 && !inScroller(el)) over.push(tag(el) + '→' + Math.round(r.right));
        const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
        if (/hidden|clip/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1 && own &&
            cs.textOverflow !== 'ellipsis' && !el.title && !inScroller(el)) {
          cx.push(tag(el) + '→' + el.scrollWidth + '/' + el.clientWidth);
        }
      }
      return { ovf: sc.scrollWidth - vw, over: over.slice(0, 4), cx: cx.slice(0, 4) };
    }"""
    def narrow(scr, tab=None):
        nwp.evaluate("(id) => show(id)", scr)
        nwp.wait_for_timeout(200)
        if tab:
            (yi_tab if scr == "yi" else wei_tab)(nwp, tab)
        nwp.wait_for_timeout(350)
        bad = nwp.evaluate(NARROW)
        face = scr + (":" + tab if tab else "")
        check(f"{face}@320：整页不横向溢出（{bad['ovf']}px）", bad["ovf"] <= 0, True)
        check(f"{face}@320：没有东西伸出屏幕边 {bad['over']}", bad["over"], [])
        check(f"{face}@320：没有被悄悄裁掉、又不给省略号的字 {bad['cx']}", bad["cx"], [])

    # 先量静态的（网关那 200 字的地址还在「我的」上，那行自述也得跟着量）。
    # 0.6.0 的四个页签要各自量一遍：一次只有一个 display 出来，只量主屏等于
    # 放过「柜子 / 搭配 / 愿望」「做菜 / 买菜 / 这周」在 320 上的全部版面。
    for scr, tab in [("yi", "pass"), ("yi", "closet"), ("yi", "outfit"), ("yi", "wish"),
                     ("wei", "cook"), ("wei", "market"), ("wei", "week"),
                     ("yan", None), ("me", None)]:
        narrow(scr, tab)
    # 味笺要真排出一桌才有内容：先把网关地址清掉——不然 runWei 在等一台不存在的机器，
    # 屏上迟迟不画，量到的就是一张白纸（第一版就是这么假绿的）。
    nwp.evaluate("() => { state.apiUrl = ''; gwReset(); }")
    # 味笺要从排桌页签排（#menu / #weiResult）；0.6.0 新开的页默认在 plan，
    # 但显式切一遍才不依赖「这一页刚好没被别人动过」。
    wei_tab(nwp, "plan")
    nwp.evaluate("() => { $('#menu').value = state.weiMenu; }")
    nwp.wait_for_timeout(150)
    nwp.evaluate("() => { runWei(); }")
    # 这一桌 301 行上菜顺序 + 241 行雷区、77KB 的 HTML：等它真出来，不用固定 sleep 赌。
    if not wait_ok("() => $$('#weiResult .serving .line').length > 0", 12000,
                   "窄屏上这一桌排得出来", on=nwp):
        check("窄屏上这一桌排得出来（不然是量一张白纸）", False, True)
    note47 = nwp.evaluate("""() => {
      const n = [...document.querySelectorAll('#weiResult .note-line')];
      const tall = n.map((e) => e.offsetHeight).sort((a, b) => b - a)[0] || 0;
      return { n: n.length, tall };
    }""")
    check("那一桌有「没当成菜的那几句」可量（不然是空转）", note47["n"] > 0, True)
    check("最长那句在 320 上排到了两行以上（裁字那条规矩保护的就是它）",
          note47["tall"] > 30, True)
    narrow("wei", "plan")
    check("窄屏顶格数据的四屏全程无 JS 报错", nwp_errs, [])
    nctx.close()

    print("\n--- 48. 系统字号拉到最大（200%）：字要真变大，而且不许有字被裁掉 ---")
    # 安卓的 font zoom 乘的是**算出来的字号**，跟 px / rem 的写法无关：字会大，写死的 px 高度
    # 不会跟着大。所以这一节测的不是「CSS 用了什么单位」，是「字变大之后还有没有字看不见」。
    # 原生那一路（MainActivity 把 fontScale 交给 textZoom）在浏览器里点不到，这里量的是版面：
    # 把每一屏每个元素的字号按 2.0× 覆写成 inline style，等价于用户在系统里把滑杆拉到最大。
    zctx = browser.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=1)
    zpg = zctx.new_page()
    zerrs = []
    zpg.on("pageerror", lambda e: zerrs.append(str(e)))
    zpg.clock.install(time="2026-09-17T10:00:00")
    zpg.goto(URL)
    zpg.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    zpg.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      const CATS = ["上衣","裤装","裙装","外套","鞋","包"];
      state.wardrobe = Array.from({length: 12}, (_, i) => ({ id: "z" + i, name: "燕麦针织开衫" + i,
        cat: CATS[i % 6], color: "#" + (0x223344 + i * 0x0b0b0b).toString(16).slice(0, 6),
        worn: 20 - i, lastWorn: now - i * 3 * DAY }));
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
      state.weiMenu = '宫保鸡丁、白灼菜心、紫菜蛋花汤、米饭、清炒时蔬、水煮鱼。今天八个人吃，有人不吃辣。';
      state.yanCards = Array.from({length: 14}, (_, i) => ({ k: ["待办","要买","已定","还没说清"][i % 4],
        line: "下午记得把材料发我，顺便问一下快递到了没有" + i,
        when: i % 3 === 0 ? { text: "月底前", at: now + 3 * DAY } : null,
        done: i % 5 === 0, moved: false, wset: false }));
      state.album = Array.from({length: 8}, (_, i) => ({ type: ["yi","wei","yan"][i % 3], t: now - i * DAY,
        quote: "柜里的奶咖针织就是这个色，再买一件是重复的" + i, text: "整张笺的正文" + i }));
      state.apiUrl = ''; state.onboarded = true;
      save(state);
    }""")
    zpg.reload()
    zpg.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    zpg.evaluate("() => { show('wei'); }")
    # 排桌的输入与结果都在 #weiPanePlan 里；不切页签的话 runWei 排得出来，
    # 但 `$$('#weiResult .serving .line')` 等在 hidden 子树里，等不到就假红。
    wei_tab(zpg, "plan")
    zpg.evaluate("() => { $('#menu').value = state.weiMenu; runWei(); }")
    if not wait_ok("() => $$('#weiResult .serving .line').length > 0", 15000, "味笺排得出这一桌", on=zpg):
        check("味笺排得出这一桌（不然是量一张白纸）", False, True)
    ZOOM = """() => {
      const vw = document.documentElement.clientWidth;
      const sc = document.scrollingElement;
      const inScroller = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
        if (/auto|scroll/.test(getComputedStyle(p).overflow)) return true; } return false; };
      const tag = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/)[0] : '');
      const screen = document.querySelector('.screen.on');
      const over = [], cx = [], cy = [];
      for (const el of screen.querySelectorAll('*')) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
        if (el.classList.contains('sr-only')) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
        if (r.right > vw + 1 && !inScroller(el)) over.push(tag(el) + '→' + Math.round(r.right));
        if (own && /hidden|clip/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1 &&
            cs.textOverflow !== 'ellipsis' && !el.title && !inScroller(el)) {
          cx.push(tag(el) + '→' + el.scrollWidth + '/' + el.clientWidth);
        }
        // 纵向这一格 §47 没有：固定 px 高度 + 变大的字，坏的就是这一种
        if (own && /hidden|clip/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 3 && !inScroller(el)) {
          cy.push(tag(el) + '→' + el.scrollHeight + '/' + el.clientHeight);
        }
      }
      const uniq = (a) => [...new Set(a)];
      return { ovf: sc.scrollWidth - vw, over: uniq(over).slice(0, 4), cx: uniq(cx).slice(0, 4), cy: uniq(cy).slice(0, 4) };
    }"""
    # 0.6.0：衣笺与味笺各有四个页签，一次只有一个 display 出来。
    # 原来只扫 `yi` 与 `wei` 各一遍，量到的其实是「过笺」与「排桌」那一页——
    # 「柜子 / 搭配 / 愿望」「做菜 / 买菜 / 这周」在 200% 字号下从来没被量过。
    # 逐页签扫一遍（同一个 ZOOM 逐字原样跑，判据一个字没动）。
    #
    # ⚠ 逐页签扫就多出一件必须自己收拾的事：**放大是写进 inline style 的**，而四个页签
    # 是同一个 `<section class="screen">` 里的四块——上一页签那一遍写上去的 2× 不会自己消失。
    # 原来只有「重置 __zo 这个 WeakMap」一行，它不是重置 DOM：实测同一屏连量四次，
    # 字号一路 24px → 48px → 96px → 192px（`.brand` 的 computed fontSize 就是这条曲线），
    # 于是第三、第四个页签量到的是 800%、1600% 的版面——`span#engineHint→369`、
    # `div→597 / h1→1171` 这些「伸出屏幕边」全是这么来的，产品在 200% 下并没有这些问题
    # （第一次量 yi:pass 时同一个 ZOOM 探针报的是空数组）。
    # 现在每一面量完就把 inline 字号**还原成量之前那一份**（量之前先记下原值），
    # 每一面都从 1.0× 起算——量到的才是「200% 下这一页的样子」，不是「又乘了一次」。
    for scr, tab in [("wei", "plan"), ("wei", "cook"), ("wei", "market"), ("wei", "week"),
                     ("yan", None), ("yi", "pass"), ("yi", "closet"), ("yi", "outfit"),
                     ("yi", "wish"), ("me", None)]:
        zpg.evaluate("(id) => { show(id); }", scr)
        zpg.wait_for_timeout(300)
        if tab:
            (yi_tab if scr == "yi" else wei_tab)(zpg, tab)
            zpg.wait_for_timeout(200)
        zpg.wait_for_timeout(200)
        face = scr + (":" + tab if tab else "")
        # 先记下 1.0× 的算好字号，再整屏乘——不记原值就会连乘
        grown = zpg.evaluate("""() => {
          const screen = document.querySelector('.screen.on');
          const els = [...screen.querySelectorAll('*')];
          window.__zo = new WeakMap(); window.__zorig = new Map();
          for (const el of els) {
            window.__zo.set(el, parseFloat(getComputedStyle(el).fontSize));
            window.__zorig.set(el, el.style.fontSize);      // 手上那一份 inline 原值（可能是空串）
          }
          const probe = els.find((e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()));
          const before = window.__zo.get(probe);
          for (const el of els) el.style.fontSize = (window.__zo.get(el) * 2) + 'px';
          return { before, after: parseFloat(getComputedStyle(probe).fontSize), els: els.length };
        }""")
        # 空壳（没画出东西的那一页）量不到任何字号变化，那才是这一节最坏的假绿。
        # 门槛从「>40 个元素」改成「>10」：0.6.0 的搭配 / 买菜 / 这周这几页本来就只有几十个节点，
        # 按 40 卡会把「这一页真的画出来了」误判成没画出来（那是假红，不是覆盖更严）。
        check(f"{face}@200%：字确实变大了（{grown['before']}px → {grown['after']}px，{grown['els']} 个元素）",
              [grown["after"] / grown["before"], grown["els"] > 10], [2.0, True])
        zpg.wait_for_timeout(250)
        z = zpg.evaluate(ZOOM)
        check(f"{face}@200%：整页不横向溢出（{z['ovf']}px）", z["ovf"] <= 0, True)
        check(f"{face}@200%：没有东西伸出屏幕边 {z['over']}", z["over"], [])
        check(f"{face}@200%：没有被裁掉又不给省略号的字 {z['cx']}", z["cx"], [])
        check(f"{face}@200%：没有字被固定高度纵向裁掉 {z['cy']}", z["cy"], [])
        # 量完把 inline 字号还给原样：下一页签（甚至下一屏）不该继承这一遍的 2×。
        zpg.evaluate("""() => {
          for (const [el, v] of window.__zorig) el.style.fontSize = v;
          window.__zo = null; window.__zorig = null; window.__ze = null;
        }""")
    # 放大之后「动作在列表之前」这条还得成立：chrome 变高不等于可以把动作再塞回表尾
    zpg.evaluate("() => { show('yan'); }")
    zpg.wait_for_timeout(300)
    check("200% 之下整张笺的动作仍然在行之前",
          zpg.evaluate("""() => { const cp = $('#copyYan'), first = $('#yanOut .check');
            return !!(cp && first) && !!(cp.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING); }"""), True)
    check("字号放大这一路无 JS 报错", zerrs, [])
    zctx.close()

    # ── 49 与 53 共用的三段 ─────────────────────────────────────────────
    # 同一台「顶到上限」的机器，同一只接住 a.download 的网。抽出来而不是复制两份：
    # 复制的那两份迟早各自漂移，漂移之后第二节测的已经不是第一节认证过的那条路了。
    # 拦截 a.click()，好让**真的** exportData() 跑完并把那份文件交回我们手上
    # （add_init_script 收的是语句，不是函数——写成 () => {} 会被求值完就丢掉）
    DL_TRAP = """(() => {
      window.__dl = null;
      const orig = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () {
        if (this.download) { window.__dl = this.href; return; }
        return orig.call(this);
      };
    })()"""
    # 把「本机放不下」变成一次**可控**的故障：写 jian.v1 时直接抛，跟真撞了配额一样
    # 落进 importData 里那个 catch。拿真配额去撞要造十几 MB 假照片，而 file:// 一组
    # 到底给多少字节是浏览器说了算——量不准的故障等于没有故障。
    UCTRAP = """(() => {
      const orig = Storage.prototype.setItem;
      window.__failWrite = false;
      Storage.prototype.setItem = function (k, v) {
        if (window.__failWrite && k === 'jian.v1') throw new DOMException('full', 'QuotaExceededError');
        return orig.apply(this, [k, v]);
      };
    })()"""
    SEED_BIG = """() => {
      const DAY = 86400000, now = Date.now();
      const CHIPS = ["辣","香菜","海鲜","花生","猪肉","牛羊肉","内脏","蒜","酒","乳","清淡"];
      const CATS = ["上衣","裤装","裙装","外套","鞋","包"];
      const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
      state.wardrobe = Array.from({length: 36}, (_, i) => ({ id: "w" + i, name: "燕麦针织开衫" + i,
        cat: CATS[i % 6], color: "#" + (0x223344 + i * 0x0b0b0b).toString(16).slice(0, 6),
        worn: Math.max(0, 30 - i), lastWorn: now - i * 3 * DAY,
        season: ["夏","春秋","冬","四季"][i % 4], img: i % 4 === 0 ? PNG : undefined }));
      state.people = Array.from({length: 12}, (_, i) => ({ name: "同" + i, chips: CHIPS.slice(0, (i % 11) + 1) }));
      state.weiMenu = "宫保鸡丁、白灼菜心、紫菜蛋花汤、米饭。".repeat(120);
      state.weiMode = "home";
      state.weiHist = [0,1,2,3].map((i) => ({ menu: "菜" + i + "、菜B", n: 8 - i, t: now - i * DAY, chips: CHIPS.slice(0, 4) }));
      state.yanCards = Array.from({length: 200}, (_, i) => ({ k: ["待办","要买","已定","还没说清"][i % 4],
        line: "下午记得把材料发我" + i, when: i % 3 === 0 ? { text: "月底前", at: now + 3 * DAY } : null,
        done: i % 5 === 0, moved: i % 7 === 0, wset: i % 3 === 0 }));
      state.yanText = "贴进来的那段聊天".repeat(300);
      state.yanAsk = "「下午记得把材料发我」谁来做、什么时候？";
      state.album = Array.from({length: 24}, (_, i) => ({ type: ["yi","wei","yan"][i % 3], t: now - i * DAY,
        quote: "柜里的奶咖针织就是这个色" + i, text: i === 0 ? "很长的正文".repeat(900) : "整张笺的正文\\n第二行" + i, stamp: "先别" }));
      state.closetSort = "idle"; state.closetSeason = "冬"; state.yanView = "time"; state.yanHideDone = true;
      state.reportStyle = "mag"; state.home = "yan"; state.plan = "all"; state.points = 9999;
      state.modules = { yi: true, wei: false, yan: true };
      state.apiUrl = "https://gateway.example.com:8443/jian";
      state.onboarded = true;
      state = normalizeState(state);          // 真实状态都是归一化之后的样子
      state.lastReport = { stamp: "宜入", gap: 7, quote: "这句话留着",
        basis: { name: "燕麦针织开衫1", gap: 7 }, closetId: "w1", t: now, newOnes: [], compared: [] };
      state.lastWei = { menu: state.weiMenu, mode: "home", n: 12, t: now,
        r: Engine.wei(state.weiMenu, state.people, "home"), talk: "这桌这样排。" };
      save(state);
    }"""
    # 49 那一趟：导 → 进，两头都走**真的**函数。exportData 造 blob 再点 a.download
    # （上面那张网把这一击换成 window.__dl），importData 读文件、验货、落盘、reload。
    SEED_FILE = """async () => {
      localStorage.setItem('__rt49before', JSON.stringify(state));   // 导出前的本机那一份
      const t0 = Date.now();
      await exportData();                                            // 走**真的**导出：blob → a.download
      const t1 = Date.now();
      const file = await (await fetch(window.__dl)).text();
      localStorage.setItem('__rt49file', file);
      window.__rt49seq = 1;
      importData(new File([file], 'jian-backup.json', { type: 'application/json' }));
      return { wardrobe: state.wardrobe.length, cards: state.yanCards.length, album: state.album.length,
               imgs: state.wardrobe.filter((w) => w.img).length, moved: state.yanCards.filter((c) => c.moved).length,
               kb: Math.round(file.length / 1024), points: state.points,
               savedAt: JSON.parse(file).savedAt, t0: t0, t1: t1,
               albumKB: Math.round(state.album[0].text.length / 1024) };
    }"""

    print("\n--- 49. 备份的往返：导出的那一份再导入回来，一件都不能少 ---")
    # 商店第五张图的标题就是「自己的数据自己拿」，而这句话的真伪只有一个地方能验：
    # 导出 → 导入 → 逐字段比。导出是 JSON.stringify(state)，所以会不会丢全看导入那一路
    # （migrate / normalizeState / cssImg / 那几条正则与上限）吃不吃得下自己写出去的东西。
    # 走的是**真入口** importData(File) —— 它带 reload，比在页里手调归一化多覆盖 migrate。
    rctx = browser.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=1)
    rctx.add_init_script(DL_TRAP)
    rpg = rctx.new_page()
    rerrs = []
    rpg.on("pageerror", lambda e: rerrs.append(str(e)))
    rpg.clock.install(time="2026-09-17T10:00:00")
    rpg.goto(URL)
    rpg.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    rpg.evaluate(SEED_BIG)
    rpg.wait_for_timeout(500)
    cov = rpg.evaluate(SEED_FILE)
    check("导出前每一样都顶到上限（不然是拿空状态比出一场绿）",
          [cov["wardrobe"], cov["cards"], cov["album"], cov["imgs"], cov["moved"], cov["points"], cov["albumKB"] > 3],
          [36, 200, 24, 9, 29, 9999, True])
    # 真入口带 reload：等 window 上的记号消失，才是「新页面带着这份备份起来了」
    if not wait_ok("() => typeof state !== 'undefined' && !window.__rt49seq", 25000,
                   "导入自己的备份之后页面重开", on=rpg):
        check("导入自己的备份之后页面重开", False, True)
    pair = json.loads(rpg.evaluate("""() => JSON.stringify([
      JSON.parse(localStorage.getItem('__rt49before')), JSON.parse(localStorage.getItem('jian.v1'))])"""))
    def deep_diff(a, b, path=""):
        """逐字段比两份 JSON，把「哪里不一样」列出来。
        以前它叫 walk，还被 50 节拿同一个名字去装「这一屏有几个可聚焦的」——
        于是 53 节复用这份比对时，调用的是一个 int，报出来的是崩而不是红。
        一份工具一个名字，别再让同一个词在同一趟里既像函数又像计数。"""
        out = []

        def one(a, b, path):
            if isinstance(a, list) or isinstance(b, list):
                if not (isinstance(a, list) and isinstance(b, list)):
                    out.append((path, "类型变了", type(a).__name__, type(b).__name__))
                    return
                if len(a) != len(b):
                    out.append((path + ".length", "条数", len(a), len(b)))
                for i in range(min(len(a), len(b))):
                    one(a[i], b[i], f"{path}[{i}]")
                return
            if isinstance(a, dict) and isinstance(b, dict):
                for k in sorted(set(a) | set(b)):
                    if k not in a:
                        out.append((f"{path}.{k}", "多出来的键", None, str(b[k])[:40]))
                    elif k not in b:
                        out.append((f"{path}.{k}", "丢掉的键", str(a[k])[:40], None))
                    else:
                        one(a[k], b[k], f"{path}.{k}")
                return
            if a != b:
                out.append((path, "值不同", str(a)[:46], str(b)[:46]))

        one(a, b, path)
        return out

    diffs = deep_diff(pair[0], pair[1])
    check(f"备份往返 {cov['kb']}KB 之后逐字段相同（扫了 {len(pair[0])} 个顶层键）",
          diffs[:8], [])
    # savedAt 是**文件**的时间戳，不是 state 的字段：两头都要钉住。
    # 只钉「落进来的那份没有它」不够——那样 exportData 干脆不写这个键也照样绿，
    # 而下一节反悔时那句「这份是 X 导出的」就没有时间可报了。
    meta = rpg.evaluate("""() => {
      const pre = JSON.parse(localStorage.getItem('__rt49before'));
      const raw = JSON.parse(localStorage.getItem('__rt49file'));
      const at = raw.savedAt; delete raw.savedAt;
      const land = JSON.parse(localStorage.getItem('jian.v1') || '{}');
      return { at: at, landed: 'savedAt' in land, seeded: 'savedAt' in pre,
               ordered: JSON.stringify(Object.keys(raw)) === JSON.stringify(Object.keys(pre)),
               verbatim: JSON.stringify(raw) === JSON.stringify(pre) }; }""")
    atnum = meta["at"] if isinstance(meta["at"], (int, float)) else -1
    check("导出的那份文件写着导出时间，而且就是按下导出的那一刻",
          [atnum >= cov["t0"], atnum <= cov["t1"]],
          [True, True])
    check("文件剥掉 savedAt 之后与导出前的 state 一字不差（连键的顺序都是原样）",
          [meta["ordered"], meta["verbatim"]], [True, True])
    check("savedAt 没跟着备份住进本机 state：它是文件的时间，不是柜子的字段",
          [meta["landed"], meta["seeded"]], [False, False])
    after = rpg.evaluate("""() => ({ imgs: state.wardrobe.filter((w) => w.img).length,
      moved: state.yanCards.filter((c) => c.moved).length, points: state.points,
      albumKB: Math.round(state.album[0].text.length / 1024), season: state.wardrobe[3].season,
      hist: state.weiHist.length, lastWei: !!(state.lastWei && state.lastWei.r && state.lastWei.r.order.length),
      report: !!(state.lastReport && state.lastReport.basis), apiUrl: state.apiUrl, home: state.home })""")
    check("照片、挪过的标记、长正文、季节、上菜顺序、报告、网关地址都还在",
          [after["imgs"], after["moved"], after["albumKB"] > 3, after["season"], after["hist"],
           after["lastWei"], after["report"], after["apiUrl"], after["home"]],
          [9, 29, True, "四季", 4, True, True, "https://gateway.example.com:8443/jian", "yan"])
    check("备份这一路无 JS 报错", rerrs, [])
    rctx.close()

    print("\n--- 50. 只用键盘走一遍：绑了点击的东西必须够得着，Tab 顺序不许来回跳 ---")
    # 第 38 轮修的是「读屏器够不着」，这一节修的是「只用键盘的人够不着」——两条不一样的路。
    # 量之前先解决「怎么知道一个元素能不能被点」：这个 App 一律用 el.onclick = fn 绑事件，
    # 所以把属性 setter 拦下来，就能拿到**全部**可点的元素清单，不用去猜类名。
    # 之前只会数「可聚焦的元素」，那正好漏掉最坏的一种：能点、但键盘永远走不到。
    kctx = browser.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=1)
    kctx.add_init_script("""(() => {
      window.__clicked = new Set();
      Object.defineProperty(HTMLElement.prototype, 'onclick', {
        configurable: true,
        get() { return this.__onclick47; },
        set(fn) { this.__onclick47 = fn; if (fn) window.__clicked.add(this); }
      });
      const add = EventTarget.prototype.addEventListener;
      EventTarget.prototype.addEventListener = function (type) {
        if (type === 'click' && this instanceof HTMLElement) window.__clicked.add(this);
        return add.apply(this, arguments);
      };
    })()""")
    kpg = kctx.new_page()
    kerrs = []
    kpg.on("pageerror", lambda e: kerrs.append(str(e)))
    kpg.clock.install(time="2026-09-17T10:00:00")
    kpg.goto(URL)
    kpg.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    kpg.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      const CATS = ["上衣","裤装","裙装","外套","鞋","包"];
      state.wardrobe = Array.from({length: 8}, (_, i) => ({ id: "k" + i, name: "衣服" + i,
        cat: CATS[i % 6], color: "#8899aa", worn: 8 - i, lastWorn: now - i * 3 * DAY }));
      state.yanCards = [0,1,2,3].map((i) => ({ k: ["待办","要买","已定","还没说清"][i % 4],
        line: "下午记得把材料发我" + i, when: null, done: false, moved: false, wset: false }));
      state.album = [0,1,2].map((i) => ({ type: "yi", t: now - i * DAY, quote: "备份的一行" + i, text: "正文" + i }));
      state.weiMenu = "宫保鸡丁、白灼菜心、米饭。";
      state.onboarded = true; state.apiUrl = '';
      save(state);
    }""")
    kpg.reload()
    kpg.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    kpg.evaluate("() => { runWei(); }")
    if not wait_ok("() => $$('#weiResult .serving .line').length > 0", 15000, "味笺排得出这一桌", on=kpg):
        check("味笺排得出这一桌", False, True)
    # 引导页也要走一遍：第 38 轮就是从那里捞出三张假按钮的
    for scr in ["onboard", "yi", "yi-report", "wei", "yan", "me"]:
        if scr == "onboard":
            kpg.evaluate("() => { state.onboarded = false; save(state); show('onboard'); }")
        else:
            kpg.evaluate("(id) => show(id)", scr)
        kpg.wait_for_timeout(400)
        reach = kpg.evaluate("""() => {
          const screen = document.querySelector('.screen.on');
          const live = [...(window.__clicked || [])].filter((el) => document.contains(el) && screen.contains(el));
          const focusable = (el) => el.matches('a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])');
          const bad = live.filter((el) => !focusable(el))
            .map((el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '.') +
              (typeof el.className === 'string' ? el.className.trim().split(/\\s+/)[0] : ''));
          return { clicked: live.length, bad: [...new Set(bad)].slice(0, 6) };
        }""")
        check(f"{scr}：绑了点击的 {reach['clicked']} 个东西全都键盘够得着（够不着的：{reach['bad']}）",
              reach["clicked"] > 0 and not reach["bad"], True)
        nfoc = kpg.evaluate("""() => {
          const screen = document.querySelector('.screen.on');
          const vis = (el) => { const cs = getComputedStyle(el);
            return cs.display !== 'none' && cs.visibility !== 'hidden' && el.getClientRects().length > 0 && !el.closest('[hidden]'); };
          return [...screen.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, summary, [tabindex]:not([tabindex="-1"])')].filter(vis).length;
        }""")
        kpg.evaluate("() => { window.scrollTo(0, 0); if (document.activeElement) document.activeElement.blur(); window.__f47 = null; window.__prev47 = null; }")
        # 「每一站都在视口里」这一格量的是「Tab 到它之后，浏览器有没有把它滚进来」。
        # 原来在按下 Tab 的**同一个 evaluate** 里就读 getBoundingClientRect()，
        # 读到的是滚动**还没发生**的那一帧：实测 Tab 到 `textarea#menu` 时
        # top=661 / bottom=799（视口 780）、scrollY 还是 0；400ms 之后同一格
        # top=193 / scrollY=468——它一直都会被滚进来，只是每秒读得太早。
        # 根因是 `html { scroll-behavior: smooth }`（styles.css:34）：聚焦引起的滚动
        # 是一次动画，不是当场跳。所以：① 这一段把平滑滚动关掉（量的仍是「滚没滚进来」
        # 这同一件事，只把「动画怎么走」换成立刻）；② 即使关掉，也等**下一帧**再读，
        # 不在按 Tab 的同一个 tick 里读。两条合起来，量到的才是「这一站最终在不在视口里」。
        kpg.add_style_tag(content="html, body { scroll-behavior: auto !important; }")
        kpg.wait_for_timeout(120)
        stops, ring_missing, out_of_view, back_jumps = [], [], [], []
        for _ in range(nfoc * 2 + 12):
            kpg.keyboard.press("Tab")
            # 先让浏览器把「聚焦引起的滚动」走完，再读位置：不在按 Tab 的同一个 tick 里读。
            # 读的是**同一站**，只是晚一帧（`requestAnimationFrame` 之后那次布局）。
            kpg.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
            row = kpg.evaluate("""() => {
              const el = document.activeElement;
              if (!el || el === document.body) return { none: true };
              const r = el.getBoundingClientRect();
              const cs = getComputedStyle(el);
              const wrapped = !!window.__f47 && window.__f47 === el;
              if (!window.__f47) window.__f47 = el;
              // 顺序对不对，问的是 DOM 顺序，不是屏幕上的 y：焦点走到 fixed 的底栏时
              // 浏览器会把页面滚回顶部，y 于是跨了两种滚动位置，量出来的是假跳。
              const prev = window.__prev47;
              window.__prev47 = el;
              const back = !!(prev && prev !== el && !wrapped && el.closest('.screen.on') && prev.closest('.screen.on')
                && (prev.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING));
              // 「在视口里」判的是**外接矩形与可视区相交**，不是「整条都装得下」：
              // 一个 138px 高的菜单框在 780 的视口里当然装得下，可一条 40 行的清单条目
              // 本来就比视口高——要求「整条装下」等于要求 App 不许有比视口长的东西，
              // 那是另一条规矩（§47 的 BLEED 量的是别的）。这里要守的是
              // 「Tab 到它之后它有没有出现在屏幕上」，所以判相交。
              const vh = window.innerHeight;
              return { none: false, wrapped, back,
                       tag: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '.'),
                       prevTag: prev ? (prev.tagName.toLowerCase() + (prev.id ? '#' + prev.id : '.')) : null,
                       inScreen: !!el.closest('.screen.on'),
                       ring: el.matches(':focus-visible') ? (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) : null,
                       inView: r.bottom > 0 && r.top < vh };
            }""")
            if row.get("none"):
                continue
            if row["wrapped"] and stops:
                break
            stops.append(row)
            if row["ring"] is False:
                ring_missing.append(row["tag"])
            if row["inView"] is False:
                out_of_view.append(row["tag"])
            if row["back"]:
                back_jumps.append(f"{row['prevTag']}→{row['tag']}")
        check(f"{scr}：Tab 一圈走到 {len(stops)} 站，清单上 {nfoc} 个可聚焦的（不含绕回起点那一跳）",
              len(stops) >= nfoc - 1, True)
        check(f"{scr}：每一站焦点描边都画得出来（缺的：{list(dict.fromkeys(ring_missing))[:4]}）", ring_missing, [])
        check(f"{scr}：每一站都在视口里（不在的：{list(dict.fromkeys(out_of_view))[:4]}）", out_of_view, [])
        check(f"{scr}：Tab 顺序不乱跳（往回跳的点：{back_jumps[:4]}）", back_jumps, [])
    # 键盘「按得动」：柜子里那一格不是 <button>，靠的是自己写的 Enter/Space
    # 这一格在柜子页签里（0.6.0 起），停在过笺上 `#closet .item` 是 null，
    # 下面读 tile.dataset 会直接抛，而报出来的是「键盘这一路崩了」。
    yi_tab(kpg, "closet")
    kpg.wait_for_timeout(300)
    kb = kpg.evaluate("""() => {
      const tile = document.querySelector('#closet .item[data-id]');
      const id = tile.dataset.id;
      state.clothSel = null; save(state); renderCloset();
      const t = document.querySelector(`#closet .item[data-id="${id}"]`);
      t.focus();
      t.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      return { sel: state.clothSel, want: id, focused: document.activeElement === t };
    }""")
    check("柜子里那一格（不是 <button>）按 Enter 真的选中了", [kb["sel"], kb["want"]], [kb["want"], kb["want"]])
    check("键盘这一路无 JS 报错", kerrs, [])
    kctx.close()

    print("\n--- 51. 言笺的搜索：筛的是显示，不是账本 ---")
    # 200 条的一笺之前只能一屏一屏划。搜索是第二把「只作用于显示」的筛（和「只看没办的」
    # 同一处地方、同一条规矩），所以这一节量的重点不是「能不能搜到」，是**筛过之后
    # 每一行还认不认得自己是哪一条**——第 15 / 22 / 28 轮三次踩过同一个坑。
    page.evaluate("""() => {
      window.__before51 = JSON.stringify({ yan: state.yanCards, ask: state.yanAsk, hide: state.yanHideDone, view: state.yanView });
      const now = Date.now();
      state.yanCards = [
        { k: '待办', line: '上次说好的那家店叫什么来着', when: null, done: false, moved: false, wset: false },
        { k: '要买', line: '买两节五号电池', when: null, done: false, moved: false, wset: false },
        { k: '已定', line: '就定那家火锅店', when: null, done: true, moved: false, wset: false, who: '小王' },
        { k: '还没说清', line: '再说吧，电池不急', when: null, done: false, moved: false, wset: false }
      ];
      state.yanAsk = ""; state.yanHideDone = false; state.yanView = "kind";
      save(state); show('yan');
    }""")
    page.wait_for_timeout(400)
    def type_yan(v):
        page.evaluate("""(v) => { const s = $('#yanSearch'); s.focus(); s.value = v;
          s.dispatchEvent(new Event('input', { bubbles: true })); }""", v)
        # 搜索现在是「计数立刻、整片列表晚 140 毫秒」(§54)。这一页的表是冻住的
        # （page.clock.install），所以这里不 sleep 而是真的把表拨过去：
        # 拿 280 毫秒的墙钟等一条只有假表才会走的延时，等于碰巧机器慢才绿。
        page.clock.run_for(200)
    check("四条都在，搜索框不藏（有条目可搜就该摆出来）",
          page.evaluate("() => [$('#yanSearchBar').hidden, $$('#yanOut .check').length]"), [False, 4])
    type_yan("电池")
    s51 = page.evaluate("""() => ({
      rows: $$('#yanOut .check').length,
      idx: $$('#yanOut input[data-yi]').map((e) => e.dataset.yi),
      head: $('#yanCount').textContent,
      caret: document.activeElement === $('#yanSearch')
    })""")
    check("搜「电池」剩两行", s51["rows"], 2)
    check("行上的下标还是全量下标 1 和 3（不是屏上第 0、第 1 行）", s51["idx"], ["1", "3"])
    check("顶上那行说的是「搜到几 / 共几」", s51["head"], "搜「电池」2 / 4 条")
    check("重画列表没把光标从搜索框里抢走", s51["caret"], True)
    check("复制整张笺不受搜索影响（筛的是显示，不是账本）",
          page.evaluate("() => yanText().split(String.fromCharCode(10)).filter((x) => x.trim()).length"),
          page.evaluate("() => { const v = $('#yanSearch').value; $('#yanSearch').value = ''; const n = yanText().split(String.fromCharCode(10)).filter((x) => x.trim()).length; $('#yanSearch').value = v; return n; }"))
    type_yan("zzz")
    s51b = page.evaluate("""() => ({
      empty: $('#yanOut .empty') ? $('#yanOut .empty').textContent.trim() : null,
      chip: !!$('#clearYanSearch') })""")
    check("搜不到那句话说是「搜不到」，不是「笺是空的」",
          "搜不到「zzz」" in (s51b["empty"] or ""), True)
    check("并且当场给一条出路（清掉搜索）", s51b["chip"], True)
    page.click("#clearYanSearch")
    page.wait_for_timeout(300)
    check("清掉之后四行回来、光标留在搜索框",
          page.evaluate("() => [$('#yanSearch').value, $$('#yanOut .check').length, document.activeElement.id]"),
          ["", 4, "yanSearch"])
    # 搜索和「只看没办的」叠在一起：两把筛同时生效时才看得出「筛的是显示」这条规矩有没有守住。
    # 「店」命中第 0 条（没办）和第 2 条（已勾）——只留没办的那一条，且下标仍是全量的 0。
    page.evaluate("() => { state.yanHideDone = true; save(state); renderYan(); }")
    type_yan("店")
    check("「只看没办的」+ 搜索同时生效：只剩没办的那一条，下标还是 0",
          page.evaluate("() => [$$('#yanOut .check').length, $$('#yanOut input[data-yi]').map((e) => e.dataset.yi)]"),
          [1, ["0"]])
    page.evaluate("() => { state.yanHideDone = false; save(state); renderYan(); }")
    type_yan("")
    # 这一格问的是「**这一次的过滤词**不许跟着备份跑」——柜子的 `#clothSearch` 与言笺的
    # `#yanSearch` 都是**读 DOM、不进 state**（yan.js:yanQuery / yi.js:closetQuery），
    # 所以量法本该是「刚才敲进去的那串字不在盘上」。
    # 原来量的是 `Object.keys(store).filter(k => /search|quer/i.test(k))` 必须为空——
    # 那在 0.5.x 成立，因为那时 state 里没有任何带 search 的键。0.6.0 加了**全局搜索**那一屏
    # （index.html #search / settings.js renderSearch），它把「真的点开过的那条搜索词」记成
    # `state.searchHist`（最多 8 条，settings.js:240）——那是用户**按出来**的历史记录，
    # 是内容不是临时过滤，本来就该跟着备份走。于是这条断言从「测过滤词」变成了
    # 「测产品里不许存在任何叫 search* 的持久字段」，而它现在必然会红，红得与被测行为无关
    # （它甚至不是本节敲的那三个字造成的：那三个字一个都没进 searchHist）。
    # 口径改成：**本节敲过的过滤词一个都不在盘上**，同时把「历史可以留、但只留用户点开过的」
    # 这条也钉住（`searchHist` 里不许出现「电池 / zzz / 店」——这三个都只是敲进框里没过）。
    check("过滤词不进备份（临时过滤，和柜子的搜索同一个规矩）", page.evaluate("""() => {
      const s = JSON.parse(localStorage.getItem('jian.v1'));
      const typed = ['电池', 'zzz', '店'];                 // 本节敲进 #yanSearch 的三个词
      const leaked = [];
      for (const k of Object.keys(s)) {
        if (!/search|quer/i.test(k)) continue;
        const v = JSON.stringify(s[k]);
        for (const w of typed) if (w && v.includes(w)) leaked.push(k + '=' + v);
      }
      return leaked;
    }"""), [])
    check("笺清空之后搜索框自己藏起来（不摆一个搜了也白搜的框）",
          page.evaluate("""() => { state.yanCards = []; save(state); renderYan();
            return [$('#yanSearchBar').hidden, !!$('#yanOut .empty')]; }"""), [True, True])
    page.evaluate("""() => { const b = JSON.parse(window.__before51);
      state.yanCards = b.yan; state.yanAsk = b.ask; state.yanHideDone = b.hide; state.yanView = b.view;
      delete window.__before51; save(state); renderYan(); }""")

    print("\n--- 52. 搜到之后要看得见「是哪一处」：命中高亮 ---")
    # 只有计数的搜索是半个功能：一条 500 字的话里搜「电池」，屏上说「1 / 200 条」，
    # 人还是得把那一段从头读一遍才知道命中在哪。
    page.evaluate("""() => {
      window.__before52 = JSON.stringify(state.yanCards);
      state.yanCards = [
        { k: '待办', line: '买两节五号电池，电池要耐用的', when: null, done: false, moved: false, wset: false },
        { k: '要买', line: '小王的 <b> 标签、3 & 5 的账单，还有 amp 这首歌', when: null, done: false, moved: false, wset: false },
        { k: '已定', line: 'Battery 电量还剩一格', when: null, done: false, moved: false, wset: false, who: '电池供应商' }
      ];
      state.yanAsk = ""; state.yanHideDone = false; state.yanView = "kind";
      save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(350)
    def mark_probe(q):
        page.evaluate("""(v) => { const s = $('#yanSearch'); s.focus(); s.value = v;
          s.dispatchEvent(new Event('input', { bubbles: true })); }""", q)
        page.clock.run_for(200)   # 同 type_yan：这条延时只有拨表才走得到，sleep 是假绿
        return page.evaluate("""() => ({
          marks: $$('#yanOut mark').length,
          texts: $$('#yanOut mark').map((m) => m.textContent),
          bodies: $$('#yanOut .ck-body').map((e) => e.textContent),
          realB: $$('#yanOut .ck-body b').length,
          rows: $$('#yanOut .check').length
        })""")
    m0 = mark_probe("")
    check("没搜的时候一个高亮都没有", m0["marks"], 0)
    m1 = mark_probe("电池")
    check("「电池」在一行里出现两次就标两处（外加人名那一处）", m1["marks"], 3)
    check("每个高亮里就是命中的那几个字", sorted(set(m1["texts"])), ["电池"])
    check("标完那一行的文字一个字没多、一个字没少",
          m1["bodies"][0], "买两节五号电池，电池要耐用的")
    m2 = mark_probe("<b>")
    check("搜「<b>」标得出来，而且屏上不会真长出一个 <b> 元素",
          [m2["marks"], m2["realB"], m2["texts"]], [1, 0, ["<b>"]])
    m3 = mark_probe("amp")
    # 原文里既有 `&`（转义成 &amp;，中间就藏着 amp）又真有一个 amp。
    # 先转义再替换的那一种会把 &amp; 里的三个字母也标上：标 2 处，而正确的答案是 1 处。
    check("搜「amp」只标原文里那一个：转义出来的 &amp; 里的三个字母不算命中",
          [m3["marks"], m3["rows"], m3["texts"]], [1, 1, ["amp"]])
    m4 = mark_probe("battery")
    check("大小写不敏感：搜 battery 标到 Battery 那一处", m4["marks"], 1)
    page.evaluate("() => { const s = $('#yanSearch'); s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true })); renderYan(); }")
    page.wait_for_timeout(250)
    check("清空搜索之后高亮一起消失（不留一排灰底）",
          page.evaluate("() => $$('#yanOut mark').length"), 0)
    page.evaluate("""() => { state.yanCards = JSON.parse(window.__before52);
      delete window.__before52; save(state); renderYan(); }""")

    print("\n--- 53. 把旧备份盖到新数据上之后那一次反悔：撤回去要一字不差是刚才那份 ---")
    # 导入是一次整体覆盖。选错文件的人要的不是事前对话框（这个 App 不做事前确认，
    # 「清空本地数据」也是先做再给一次反悔），是事后那一次能真的换回来。
    # 这一节的关键是**别让导进来的那一份就是本机这一份**。49 节为了验「往返不丢」
    # 故意让两边相等，而相等的时候「撤销回到了过去」是句空话——撤不撤都长一个样，
    # 连「撤销按钮什么都不做」这种最坏的写法都能测绿。所以这里：导出旧份 A →
    # 把本机改成新份 B → 拿 A 盖上来 → 撤销必须把 B 一个字不差地还回来。
    uctx = browser.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=1)
    uctx.add_init_script(DL_TRAP)
    uctx.add_init_script(UCTRAP)
    upg = uctx.new_page()
    uerrs = []
    upg.on("pageerror", lambda e: uerrs.append(str(e)))
    upg.clock.install(time="2026-09-17T10:00:00")   # 冻住表：那条 toast 5.2 秒就自己没了
    upg.goto(URL)
    upg.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    upg.evaluate(SEED_BIG)
    upg.wait_for_timeout(500)
    afile = upg.evaluate("""async () => {
      const t0 = Date.now();
      await exportData();
      const f = await (await fetch(window.__dl)).text();
      localStorage.setItem('__u53fileA', f);
      return { kb: Math.round(f.length / 1024), at: JSON.parse(f).savedAt, t0: t0 }; }""")
    check("先存下一份顶到上限的旧备份 A（一百多 KB，不是拿三件衣服演一遍）",
          [afile["at"] >= afile["t0"], afile["kb"] > 100], [True, True])
    upg.evaluate("""() => {
      state.wardrobe = state.wardrobe.slice(0, 3);
      state.yanCards = state.yanCards.slice(0, 7);
      state.album = []; state.points = 7; state.home = "yi";
      save(state);
      localStorage.setItem('__u53B', localStorage.getItem('jian.v1'));
    }""")
    b = upg.evaluate("""() => ({ w: state.wardrobe.length, c: state.yanCards.length,
      a: state.album.length, p: state.points, home: state.home,
      landed: localStorage.getItem('jian.v1') === localStorage.getItem('__u53B') })""")
    check("本机改成了新份 B：3 件 / 7 条 / 0 张 / 7 分 / 落在衣笺（A 是 36/200/24）",
          [b["w"], b["c"], b["a"], b["p"], b["home"]], [3, 7, 0, 7, "yi"])
    check("B 真的落了盘：反悔要还的是盘上那一份，不是页里那个变量", b["landed"], True)
    upg.evaluate("""async () => {
      const f = localStorage.getItem('__u53fileA');
      window.__u53seq = 1;
      importData(new File([f], 'jian-backup-old.json', { type: 'application/json' })); }""")
    # 等的是那枚「撤销」本身，不是等一秒：占槽在写盘成功之后、reload 之前，
    # 而 toast 要等整段 boot 跑完才挂出来。
    if not wait_ok("() => typeof state !== 'undefined' && !window.__u53seq"
                   " && !!document.querySelector('.toast.act button')",
                   25000, "导入旧备份之后开机给出了那一次反悔", on=upg):
        check("导入旧备份之后开机给出了那一次反悔", False, True)
    u = upg.evaluate("""() => {
      const t = document.querySelector('.toast.act');
      const btn = t && t.querySelector('button');
      return { said: t ? t.querySelector('span').textContent : null,
               label: btn ? btn.textContent : null, type: btn ? btn.type : null,
               onScreen: !!(btn && btn.offsetParent),
               slot: sessionStorage.getItem('jian.v1.importundo'),
               at: sessionStorage.getItem('jian.v1.importat'),
               w: state.wardrobe.length, c: state.yanCards.length, a: state.album.length } }""")
    check("那句话报的是**落进来之后**的真实件数和文件上那个导出时间",
          u["said"], "已导入：柜里 36 件 · 言笺 200 条 · 笺册 24 张（这份是 2026.09.17 导出的）")
    check("屏幕上的数确实是 A 的 36/200/24，不是 B 的 3/7/0（说错了数就等于骗人）",
          [u["w"], u["c"], u["a"]], [36, 200, 24])
    check("那枚反悔真的挂出来了，而且是个能按的按钮",
          [u["onScreen"], u["label"], u["type"]], [True, "撤销", "button"])
    check("快照只活一次：boot 读完就把两个槽都作废了",
          [u["slot"], u["at"]], [None, None])
    upg.click(".toast.act button")
    upg.wait_for_timeout(400)
    back = upg.evaluate("""() => ({ w: state.wardrobe.length, c: state.yanCards.length,
      a: state.album.length, p: state.points, home: state.home,
      on: state.onboarded && document.querySelector('#yi').classList.contains('on'),
      said: (document.querySelector('.toast') || {}).textContent || null,
      sameStore: localStorage.getItem('jian.v1') === localStorage.getItem('__u53B') })""")
    check("按下去报的是「换回导入前那份了」，而且说得出人话", back["said"], "换回导入前那份了")
    check("撤回来的是 B：3 件 / 7 条 / 0 张 / 7 分，屏也换回衣笺",
          [back["w"], back["c"], back["a"], back["p"], back["home"], back["on"]],
          [3, 7, 0, 7, "yi", True])
    check("撤回来的是**盘上那一份 B 的每一字节**，不是重新拼出来的近似品",
          back["sameStore"], True)
    # 反悔本身也得落得住：再开一次，还是 B，而且不会再冒出一句「已导入」。
    # 第二遍没有 toast 可等（这一路 boot 本来就不该有 toast），所以拿 readyState==='complete'
    # 当「boot 跑完了」的凭据：boot 挂在 DOMContentLoaded 上，浏览器这一路全程只有 microtask
    # （hasNative() 为假，两个 await 都当场落定），而 load 是之后的一格 task —— 它到了，boot 必到。
    # 这一句是**等不到就报 FAIL** 的：拿 sleep 验一次不存在的东西，正是第 34 轮拆掉的那四类假认证。
    upg.evaluate("() => { window.__u53seq = 1; location.reload(); }")
    if not wait_ok("() => typeof state !== 'undefined' && !window.__u53seq"
                   " && document.readyState === 'complete'", 25000,
                   "撤销之后重开还是那一份", on=upg):
        check("撤销之后重开还是那一份", False, True)
    again = upg.evaluate("""() => ({ w: state.wardrobe.length, c: state.yanCards.length,
      a: state.album.length, p: state.points, home: state.home,
      sameStore: localStorage.getItem('jian.v1') === localStorage.getItem('__u53B'),
      act: !!document.querySelector('.toast.act'),
      slot: sessionStorage.getItem('jian.v1.importundo') })""")
    check("重开之后还是 B（撤销真的写进盘里了，不只是页里改了一下）",
          [again["sameStore"], again["w"], again["c"], again["a"], again["p"], again["home"]],
          [True, 3, 7, 0, 7, "yi"])
    check("boot 跑完了一遍，那句「已导入」没有第二次冒出来（槽读过就作废，点没点都作废）",
          [again["slot"], again["act"]], [None, False])
    # 反悔的槽只能由**真的换了本机这一份**占上。写盘没成功（备份太大、存储满了）也照样占，
    # 下次开机就凭空多出一句「已导入」，而柜子里一条都没变——那是第二遍骗人。
    upg.evaluate("""() => {
      window.__q53alive = 1;
      window.__q53before = localStorage.getItem('jian.v1');
      window.__failWrite = true;
      importData(new File([localStorage.getItem('__u53fileA')], 'no-room.json',
                          { type: 'application/json' })); }""")
    if not wait_ok("() => Array.from(document.querySelectorAll('.toast'))"
                   ".some((n) => n.textContent.includes('原数据没动'))", 8000,
                   "写不进去的那次导入照实说了「原数据没动」", on=upg):
        check("写不进去的那次导入照实说了「原数据没动」", False, True)
    q = upg.evaluate("""() => { window.__failWrite = false;
      return { alive: window.__q53alive, same: localStorage.getItem('jian.v1') === window.__q53before,
               slot: sessionStorage.getItem('jian.v1.importundo'),
               at: sessionStorage.getItem('jian.v1.importat') }; }""")
    check("落盘失败：本机那一份一个字节都没动，页面也没 reload",
          [q["same"], q["alive"]], [True, 1])
    check("落盘失败就不占反悔槽（占了是在预告一次没发生过的导入）",
          [q["slot"], q["at"]], [None, None])
    # 那份文件压根没写时间（第 49 轮之前导出的就是这种）：要说「没写导出时间」，
    # 不能拿今天凑一个日期上去——那一句是把「不知道」说成了「知道」。
    # 这一格非走不可：不占这一趟，下面那条注入（永远按今天报）就没人能把它测红。
    upg.evaluate("""() => {
      const o = JSON.parse(localStorage.getItem('__u53fileA'));
      delete o.savedAt;
      window.__u53seq = 1;
      importData(new File([JSON.stringify(o)], 'no-stamp.json', { type: 'application/json' })); }""")
    if not wait_ok("() => typeof state !== 'undefined' && !window.__u53seq"
                   " && !!document.querySelector('.toast.act button')", 25000,
                   "没有导出时间的那一份也照样给了反悔", on=upg):
        check("没有导出时间的那一份也照样给了反悔", False, True)
    nod = upg.evaluate("""() => ({
      said: (document.querySelector('.toast.act span') || {}).textContent || null })""")
    check("文件没写时间就说没写时间，不拿今天凑一个日期出来",
          nod["said"], "已导入：柜里 36 件 · 言笺 200 条 · 笺册 24 张（这份备份没写导出时间）")
    upg.click(".toast.act button")
    upg.wait_for_timeout(300)
    nodback = upg.evaluate("""() => ({ same: localStorage.getItem('jian.v1') === localStorage.getItem('__u53B'),
      said: (document.querySelector('.toast') || {}).textContent || null })""")
    check("没写时间的那一份也撤得动：盘里又是导入前那一份 B", nodback["same"], True)
    check("撤销给的回话每次都算数（第二遍也说的是「换回导入前那份了」）",
          nodback["said"], "换回导入前那份了")
    # 开机要说的话不止一句，而提示区一次只放得下一条（第 38 轮定的）。第 50 轮加了
    # 「已导入」那一句之后，它会把第 19 轮那句「言笺少 N 条」顶掉——而后者报的是丢了数据，
    # 商店文案里明写着「不会悄悄少掉」。所以两句得合成一句说；这一格量的就是合成还在不在。
    upg.evaluate("""() => {
      const o = JSON.parse(localStorage.getItem('__u53fileA'));
      o.yanCards = o.yanCards.concat([null, { k: "要买" }]);          // 两条形状不对
      o.album = o.album.concat([{}]);                                 // 一张也是
      window.__u53seq = 1;
      importData(new File([JSON.stringify(o)], 'dirty.json', { type: 'application/json' })); }""")
    if not wait_ok("() => typeof state !== 'undefined' && !window.__u53seq"
                   " && !!document.querySelector('.toast.act button')", 25000,
                   "带着脏条目的那一份也给了反悔", on=upg):
        check("带着脏条目的那一份也给了反悔", False, True)
    both = upg.evaluate("""() => {
      const t = document.querySelector('.toast.act');
      return { said: t ? (t.querySelector('span') || {}).textContent || null : null,
               btn: !!(t && t.querySelector('button')),
               cards: state.yanCards.length, album: state.album.length } }""")
    check("「已导入」和「少了几条」合成一句说，谁也不把谁顶掉",
          both["said"],
          # 量词那一处跟着 0.6.0 改：那句话现在由 app.js 的 `names` 表统一生成，
          # 九个集合一律写「少 N 条」，笺册不再单独写「少 N 张」（0.5.x 是手写两段）。
          # 这条要守的是「两句合成一句、谁也不顶掉谁」，所以期望里两个集合都点名。
          "已导入：柜里 36 件 · 言笺 200 条 · 笺册 24 张（这份是 2026.09.17 导出的）。"
          "言笺少 2 条，笺册少 1 条（备份里这几条形状不对，没放进来）")
    check("脏条目确实没上屏（202 条洗成 200、25 张洗成 24），而那枚撤销还在",
          [both["cards"], both["album"], both["btn"]], [200, 24, True])
    check("导入反悔这一整条链无 JS 报错", uerrs, [])
    uctx.close()

    print("\n--- 54. 搜索那一行字不许拖住刚敲进去的那个字：计数立刻、整片晚 140 毫秒 ---")
    # 本轮量出来的原始数字：200 条的时候一次整片重建摆 1800 个节点，从按键到下一帧最坏 139ms
    # （桌面 Edge，手机上只会更糟）。那不只是「列表慢」——主线程被占死的时候，
    # 连刚敲进框里那个字都要等下一帧才出现，而这一下是用户判定「它有没有在听」的地方。
    # 现在按键只改头上那行数字，整片列表等手停下来再画。
    # 这一页的表是冻住的（上面 clock.install），所以「还没到 140 毫秒」是**真的看得见**的状态，
    # 不是靠 sleep 撞运气——延后这件事只有拨表才量得准。
    page.evaluate("""() => {
      window.__before54 = JSON.stringify(state.yanCards);
      state.yanCards = Array.from({length: 200}, (_, i) => ({ k: ['待办','要买','已定','还没说清'][i % 4],
        line: '下午记得把材料发我，另外药快没了帮我买一盒 ' + i,
        done: false, moved: false, wset: false }));
      state.yanHideDone = false; state.yanView = 'kind'; state.yanAsk = '';
      save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(300)
    def key_yan(v):
        page.evaluate("""(x) => { const s = $('#yanSearch'); s.focus(); s.value = x;
          s.dispatchEvent(new Event('input', { bubbles: true })); }""", v)
    # 种子行尾是「 0」…「 199」，所以「1」命中 119 条、 「11」命中 11 条：
    # 这两个数是数出来的，不是从实现里抄的——抄过来的期望值会把断言变成复读。
    n1 = len([i for i in range(200) if "1" in str(i)])
    n11 = sorted([i for i in range(200) if "11" in str(i)])
    key_yan("1")
    page.clock.run_for(200)
    first = page.evaluate("""() => ({ head: $('#yanCount').textContent,
      rows: $$('#yanOut .check').length, marks: $$('#yanOut mark').length })""")
    check(f"先让整片画一次：搜「1」{n1} / 200，行也真的只剩 {n1}",
          [first["head"], first["rows"]], [f"搜「1」{n1} / 200 条", n1])
    check("那一次重建把高亮也画上了（延后不是干脆不画）", first["marks"] >= n1, True)
    key_yan("11")
    mid = page.evaluate("""() => ({ head: $('#yanCount').textContent,
      rows: $$('#yanOut .check').length, mark0: ($('#yanOut mark') || {}).textContent || null })""")
    check("再敲一个字：头上那行数字**当场**就变了", mid["head"], f"搜「11」{len(n11)} / 200 条")
    check("而列表还是上一版那 119 行——延后是真的在延后，不是句注释",
          [mid["rows"], mid["mark0"]], [n1, "1"])
    page.clock.run_for(200)
    settled = page.evaluate("""() => ({ head: $('#yanCount').textContent,
      rows: $$('#yanOut .check').length,
      idx: $$('#yanOut input[data-yi]').map((e) => +e.dataset.yi) })""")
    check("140 毫秒之后整片跟上：11 行，而且行上的下标仍是全量下标（没被挪成屏上第几行）",
          [settled["head"], settled["rows"], sorted(settled["idx"])],
          [f"搜「11」{len(n11)} / 200 条", len(n11), n11])
    # 连着敲不该攒出一串重建：四个字各敲一下、每两下之间只过 60 毫秒（比那 140 短），
    # 一次都不该画；手停下来之后只补画那一次。
    #
    # ⚠ 量法上有两个必须显式排掉的干扰，原来那两格都栽在这儿（实测 1 与 2，期望 0 与 1）：
    #   ① `page.clock.run_for(60)` 拨的是**整张假表**，不是「只让这一个输入动作过去 60ms」。
    #      而 `run_for` / `fast_forward` 会把这段时间里**所有**到期的定时器都跑掉——
    #      包括本节前面那一趟排队的那一次重建。也就是说：四下里每一下都顺手补画了
    #      「上一次还剩的 140ms」，累计 240ms 足够让排队的那一次真的落地。
    #      产品并没有在连敲里重建（yanSearchTick 每敲一下都会 clearTimeout 再排一个新的），
    #      红的是「拿拨表当 sleep」这个量法。
    #   ② 计数窗口开得太早：`window.__paints54` 装上去的那一刻，上一趟还挂着一个没到期的
    #      排队重建，它一落地就记一笔。
    # 现在的量法：先让窗口里**干净**（把上一趟的排队跑完、再清零计数），再在窗口内
    # **每一步之后核对一次两件事**——头上那行数字变了（说明这一下真进去了）、
    # 而整片一次都没重建（paints 还是 0）。只要有一次 paints>0，就是产品在连敲里重建了。
    page.evaluate("""() => { window.__origPaint54 = window.paintYan; window.__paints54 = 0;
      window.paintYan = function () { window.__paints54++; return window.__origPaint54.apply(this, arguments); }; }""")
    # 清场：把此刻还挂着的那一次排队跑掉，再清零——窗口从「一次都不欠」开始。
    page.clock.run_for(200)
    page.evaluate("() => { window.__paints54 = 0; }")
    burst_steps = []
    for ch in ["", "材", "材料", "材料发"]:
        key_yan(ch)
        # 一下 60ms（比那 140 短）：这一下自己排的重建不该到期，
        # 而上一趟的排队在清场时已经跑完了，所以这段时间里一次都不该落地。
        page.clock.run_for(60)
        burst_steps.append(page.evaluate("""() => ({ paints: window.__paints54,
          head: $('#yanCount').textContent, rows: $$('#yanOut .check').length })"""))
    burst = burst_steps[-1]
    check("连敲四下、每下只隔 60 毫秒：一次整片重建都没发生",
          [s["paints"] for s in burst_steps], [0, 0, 0, 0])
    check("但头上那行已经跟着走到第四下了", burst["head"], "搜「材料发」200 / 200 条")
    page.clock.run_for(200)
    after = page.evaluate("""() => ({ paints: window.__paints54,
      rows: $$('#yanOut .check').length, marks: $$('#yanOut mark').length })""")
    check("手停下来之后**只**补画那一次（四下攒成一次，不是四次各画一遍）",
          [after["paints"], after["rows"], after["marks"] >= 200], [1, 200, True])
    # 「当场改的那行数字」和「140 毫秒后画出来的那批行」必须是**同一把筛**数出来的。
    # 这一格专门造一个两边会分家的例子：命中的字在 who（人名）里而不在正文里，
    # 而且其中一条已经勾掉、「只看没办的」正开着——抄一份只认 line、不看 hideDone 的
    # 计数会报 0，少看了 hideDone 的会报 2，正确的答案是 1。
    page.evaluate("""() => {
      state.yanCards[5].who = '小王'; state.yanCards[9].who = '小王';
      state.yanCards[9].done = true;
      state.yanHideDone = true; save(state); renderYan(); }""")
    page.clock.run_for(200)
    key_yan("小王")
    who54 = page.evaluate("""() => ({ head: $('#yanCount').textContent,
      rows: $$('#yanOut .check').length })""")
    check("那行数字走的是同一把筛：人名里搜得到，已勾的那条在「只看没办的」里不算",
          who54["head"], "搜「小王」1 / 200 条")
    page.clock.run_for(200)
    check("140 毫秒之后画出来的也正是那一条（数字和行不是两套口径）",
          page.evaluate("""() => [$$('#yanOut .check').length,
            $$('#yanOut input[data-yi]').map((e) => +e.dataset.yi)]"""), [1, [5]])
    # 直接画过一次之后，排队那一次不该再来一遍：「清掉搜索」走的就是这一条路
    # （它把框清空、当场重建，可 140 毫秒前那一下的定时器还挂着）。
    page.evaluate("""() => { state.yanHideDone = false; save(state); renderYan(); }""")
    page.clock.run_for(200)
    page.evaluate("() => { window.__paints54 = 0; }")
    key_yan("药")                       # 排上一次整片重建
    page.evaluate("() => renderYan()")  # 同「清掉搜索」那一下：当场画
    page.clock.run_for(300)
    check("当场画过一次之后，排队那一次就作废（不会被 140 毫秒前那一下再刷一遍）",
          page.evaluate("() => window.__paints54"), 1)
    page.evaluate("""() => {
      window.paintYan = window.__origPaint54;
      delete window.__origPaint54; delete window.__paints54;
      const s = $('#yanSearch'); s.value = '';
      state.yanCards = JSON.parse(window.__before54);
      delete window.__before54; save(state); renderYan(); }""")
    check("搜索延时这一路无 JS 报错",
          [e for e in errors if "favicon" not in e.lower()], [])

    print("\n--- 55. 把安全区拨到手势条那一档：贴在屏幕下沿的东西要自己让开 ---")
    # 桌面浏览器里 `env(safe-area-inset-bottom)` 恒为 0，所以「刘海/手势条之下压住底栏」
    # 这一整类错在浏览器里根本不存在——以前也没人为它写过一行断言。
    # 但样式里那些偏移都是 `calc(96px + var(--sab))` 写的，而 `--sab` 就在 :root 上：
    # 把它覆写成 48px，等于原地换了一台有手势条的手机，量的还是真布局。
    # 48 不是随手挑的：Pixel 系手势条 48dp，比常见的 24dp 更狠，过这一档就够。
    def inset_probe(sab):
        page.evaluate("(v) => { document.documentElement.style.setProperty('--sab', v + 'px'); }", sab)
        page.wait_for_timeout(200)
        return page.evaluate("""() => {
          const nav = document.querySelector('.nav');
          const t = document.querySelector('.toast');
          const btn = t && t.querySelector('button');
          const r = (el) => { const b = el.getBoundingClientRect();
            return { top: Math.round(b.top), bottom: Math.round(b.bottom), h: Math.round(b.height) }; };
          const inter = (a, b) => Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
          const N = r(nav);
          return { nav: N, toast: t ? r(t) : null, overlap: t ? inter(r(t), N) : -1,
                   btnOverlap: btn ? inter(r(btn), N) : -1,
                   offBottom: t ? Math.round(innerHeight - r(t).bottom) : null,
                   appPad: Math.round(parseFloat(getComputedStyle(document.querySelector('#app')).paddingBottom)) };
        }""")
    base55 = inset_probe(0)
    tall = page.evaluate("""() => {
      toastUndo("柜里 36 件都还在，这是刚删掉的那一件唯一一次能救回来的入口", () => {});
      return document.querySelectorAll('.toast').length; }""")
    check("先确认这一屏真的挂着一条能撤销的提示（不然是拿一条不存在的浮层量了个空）", tall, 1)
    big55 = page.evaluate("""() => { const b = document.querySelector('.toast').getBoundingClientRect();
      return Math.round(b.height); }""")
    check("这条提示是三行高那种（拿一条一行的去量重叠，等于没量）", big55 > 40, True)
    flat = inset_probe(0)
    check("没有安全区时：提示整条在底栏之上，一点不压",
          [flat["overlap"], flat["offBottom"] >= 0], [0, True])
    notch = inset_probe(48)
    # 先证明这个旋钮真的动了：底栏自己该长高 48px。这一条不过，后面全是空测。
    check("把 --sab 拨到 48px 真的改了布局（底栏自己长高了 48px）",
          notch["nav"]["h"] - base55["nav"]["h"], 48)
    check("手势条那一档下，提示条仍然整条在底栏之上（压住底栏就点不到「撤销」）",
          [notch["overlap"], notch["btnOverlap"]], [0, 0])
    check("而且没被屏幕下沿裁掉，也没被顶出可视区",
          [notch["offBottom"] >= 0, notch["toast"]["top"] >= 0], [True, True])
    check("正文那一屏给底栏留的白也跟着长高（最后一行不会藏在底栏底下）",
          notch["appPad"] - flat["appPad"], 48)
    # 上面那个旋钮能拨动一切的前提是：全文件只有一处安全区的来源。
    # `.nav` 以前直接写 `env(safe-area-inset-bottom)`，绕开了 `--sab`——行为上没错，
    # 但那一处从此**永远量不到**（桌面浏览器里 env() 恒为 0）。这条不变量就是为了让它
    # 下次不能再绕过去：`env(safe-area-inset-*)` 只许出现在 :root 那四行定义里。
    css = (JIAN / "styles.css").read_text(encoding="utf-8")
    env_uses = re.findall(r"env\(\s*safe-area-inset-", css)
    check("安全区只有一个来源（env(...) 只许出现在 :root 那四行，别处一律走 var(--sab)）",
          len(env_uses), 4)
    # 遮罩是 inset:0 铺满的：安全区之内它要还能把那颗章画在正中，而不是被手势条吃掉半截
    veil55 = page.evaluate("""() => {
      veil(true, '在认这一笺…');
      const c = document.querySelector('.veil-card'), m = document.querySelector('.veil-mark');
      const cr = c.getBoundingClientRect(), vr = m ? m.getBoundingClientRect() : null;
      const nav = document.querySelector('.nav').getBoundingClientRect();
      return { inView: vr ? (vr.top >= 0 && vr.bottom <= innerHeight) : null,
               clearsNav: vr ? (vr.bottom <= nav.top || vr.top >= nav.bottom) : null,
               cardCentered: Math.abs((cr.top + cr.bottom) / 2 - innerHeight / 2) < innerHeight * 0.12,
               shown: getComputedStyle(c).display !== 'none' }; }""")
    check("同一档安全区下，遮罩那颗章还在可视区内、也没被底栏压住",
          [veil55["shown"], veil55["inView"], veil55["clearsNav"]], [True, True, True])
    # 上面量的都是**下**半边。状态栏那一档（--sat）更要紧：targetSdk 36 在安卓 15/16 上
    # 是强制 edge-to-edge 的，到那时 WebView 从 y=0 开始画，任何没让开 --sat 的东西
    # 都会钻进状态栏底下——图标压字、点不到。本机模拟器给不出非零 inset（见自验指南 §6），
    # 所以这一半也只能靠同一个旋钮模拟：把 --sat 拨到 48px（刘海/状态栏那一档），
    # 逐屏扫「有字或能操作」的元素，要求没有一个的顶边落在状态栏带里。
    top55 = page.evaluate("""() => {
      // 状态栏那一档 48px，左右圆角各 24px（应用锁竖屏，横向 inset 只会是圆角那一档）
      const S = { top: 48, left: 24, right: 24 };
      document.documentElement.style.setProperty('--sat', S.top + 'px');
      document.documentElement.style.setProperty('--sal', S.left + 'px');
      document.documentElement.style.setProperty('--sar', S.right + 'px');
      const out = [];
      let seen = 0;
      const vis = (el) => { const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && el.getClientRects().length > 0
          && !el.closest('[hidden]') && !el.closest('.veil'); };
      for (const id of ['onboard', 'yi', 'wei', 'yan', 'me']) {
        show(id);
        const scr = document.querySelector('.screen.on') || document.querySelector('#' + id);
        const bad = [];
        for (const el of scr.querySelectorAll('*')) {
          if (!vis(el)) continue;
          // 只问「有内容的那一层」：容器套着文字时它的顶边也在 48 之上是正常的，
          // 真正会被压住的是自己带文字或自己能操作的那一层
          const own = (el.childNodes.length && [...el.childNodes].some((n) =>
                       n.nodeType === 3 && n.textContent.trim()))
            || /^(BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(el.tagName);
          if (!own) continue;
          seen++;
          const r = el.getBoundingClientRect();
          if (r.height <= 0) continue;
          const inTop = r.top < S.top;
          const inLeft = r.left < S.left;
          const inRight = r.right > innerWidth - S.right;
          if (inTop || inLeft || inRight) bad.push({ t: el.tagName,
            x: (el.textContent || '').trim().slice(0, 14),
            带: inTop ? '状态栏' : (inLeft ? '左圆角' : '右圆角'),
            top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right) });
        }
        if (bad.length) out.push({ id, bad: bad.slice(0, 4) });
      }
      return { hits: out, seen };
    }""")
    # 「扫过 0 个元素」和「扫过 400 个都没问题」输出是一样的——那正是这类整片扫最坏的骗法。
    # 先把扫到的数量本身钉住，再判它干不干净。
    check("这一遍真的扫到了东西（五屏加起来至少几十处带字或能操作的层）",
          top55["seen"] >= 60, True)
    check(f"拨出状态栏 48px + 左右圆角各 24px：扫过 {top55['seen']} 处，"
          f"没有一个字或控件落在安全区带里",
          top55["hits"], [])
    back55b = page.evaluate("""() => {
      ['--sat', '--sal', '--sar'].forEach((v) => document.documentElement.style.removeProperty(v));
      show(state.home);
      const scr = document.querySelector('.screen.on');
      return { pad: Math.round(parseFloat(getComputedStyle(scr).paddingTop)),
               first: (() => { const e = scr.querySelector('h2, .mark, .sheet, .empty');
                 return e ? Math.round(e.getBoundingClientRect().top) : null; })() };
    }""")
    check("旋钮归零之后上边距也跟着收回来（48px 那一档不是靠硬留白撑的）",
          back55b["pad"] < 48, True)
    page.evaluate("""() => { veil(false);
      ['--sat', '--sab', '--sal', '--sar'].forEach((v) => document.documentElement.style.removeProperty(v)); }""")
    back55 = inset_probe(0)
    check("旋钮归零之后一切回到原样（这一节不许给后面的节留下一个歪的安全区）",
          [back55["nav"]["h"], back55["overlap"]], [base55["nav"]["h"], 0])
    check("安全区这一路无 JS 报错",
          [e for e in errors if "favicon" not in e.lower()], [])

    print("\n--- 56. 穿用记录改得动：那句「N 个月没穿过」的原料 ---")
    # 第 59 轮。全 App 原先只有一个写入口「今天穿了」：只能记今天、只能 +1。
    # 于是三件事做不到——补不回去（换机、导入备份、忘了记）、退不回来（手滑点一下，
    # 次数与「上次穿」永久错）、纠正不成「还没穿过」。而这两个数不是记账那么轻：
    # 它们直接决定 engine.js 落进报告页的那句劝告里写几个月。所以这一节的胜负手是
    # **改完之后重跑一次过笺，那句话必须跟着变**，不是「输入框的值变了」。
    page.evaluate(MK)

    def r59():
        return page.evaluate("() => { const w = state.wardrobe.find((x) => x.id === 'r59');"
                             " return [w.worn, w.lastWorn]; }")

    def r59head():
        return page.inner_text("#clothActions .action-head").replace("\n", " ")

    def r59aria():
        return page.get_attribute('#closet .item[data-id="r59"]', "aria-label")

    def r59badge():
        return page.evaluate("() => { const w = document.querySelector('#closet .item[data-id=\"r59\"] .worn');"
                             " return w ? w.textContent : '（没有角标）'; }")

    def r59today():
        return page.eval_on_selector_all("#closetNote [data-worn]", "els => els.map(e => e.textContent.trim())")

    def r59quote():
        return page.inner_text("#reportQuote")

    def r59open():
        """进衣笺那一屏、切到柜子页签并选中那件：.screen 不是 .on 时是 display:none，
        而 0.6.0 起柜子又收进了 #yiPaneCloset（默认 hidden）——两道都要过，
        Playwright 的 click/fill 才会认它可见。少了页签这一道，
        `page.locator("#clothWornDay").fill(...)` 报的是 "element is not visible"。"""
        page.evaluate("() => { state.clothSel = 'r59'; save(state); }")
        yi_tab(page, "closet")
        page.evaluate("() => { renderCloset(); renderClothActions(); }")
        page.wait_for_timeout(250)

    def r59run():
        """跑一次过笺。runYi 要的是过笺页签（#fileNew 那一套入口都在 #yiPanePass 里）；
        跑完 runYi 自己 show('yi-report')，所以量报告页的那几句不用再切回来。"""
        page.evaluate("() => { state.lastReport = null; }")
        yi_tab(page, "pass")
        page.evaluate("async () => { const f = await window.__mk('#d8d2c6', 'r59.jpg'); runYi(f); }")
        page.wait_for_function("() => state.lastReport !== null", timeout=20000)
        page.wait_for_timeout(300)

    page.evaluate("""() => {
      const d = Date.now(), DAY = 86400000;
      state.modules.yi = true; state.points = 90;
      state.wardrobe = [
        { id: 'r59', name: '灰蓝长袖', cat: '上衣', color: '#d4c4b0', worn: 3, lastWorn: d - 210 * DAY, season: '四季' },
        { id: 'r59b', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: d - 5 * DAY }
      ].map(normCloth);
      state.clothSel = 'r59'; state.closetSeason = 'all'; state.closetSort = 'idle';
      state.lastReport = null;
      save(state); show('yi'); renderCloset();
    }""")
    page.wait_for_timeout(250)
    r59run()
    check("改之前：判定把这件算成久未穿（stale 那一层）",
          page.evaluate("() => [state.lastReport.stamp, !!state.lastReport.stale]"), ["先别", True])
    check("改之前：那句劝告渲染在报告页上，说的是 7 个月",
          "而且 7 个月没穿过了。再买一件，只会多一件不穿的。" in r59quote(), True)
    # 修正入口本身：三枚快捷签 + 一枚日期框 + 次数两枚，全在编辑器里，不开弹窗不加遮罩
    check("编辑器给了三枚「上次穿」快捷签",
          page.eval_on_selector_all("#clothActions [data-wear-day]", "els => els.map(e => e.textContent.trim())"),
          ["今天", "昨天", "前天"])
    check("还给了一个原生日期框，里面回填着账上真记着的那一天",
          [page.evaluate("() => !!document.querySelector('#clothWornDay')"),
           page.evaluate("() => document.querySelector('#clothWornDay').value")],
          [True, "2026-02-19"])
    check("次数两枚：−1 与 ＋1",
          page.eval_on_selector_all("#clothActions #wearDown, #clothActions #wearUp",
                                    "els => els.map(e => e.textContent.trim())"), ["−1", "＋1"])
    # 改日子：只挪日子，不动次数（口径③——次数另有 ±1，两格各修一件事）
    keep = r59()
    r59open()
    page.locator("#clothWornDay").fill("2026-03-11")     # 190 天前：还是久未穿，但月数要换
    page.wait_for_timeout(300)
    check("挑一天之后次数一格没动（改日子不等于多穿一次）", r59()[0], keep[0])
    check("日子真的挪到了挑的那一天", page.evaluate(
        "() => dayStr(state.wardrobe.find((w) => w.id === 'r59').lastWorn)"), "2026.03.11")
    check("编辑器头上那行跟着改口", "穿过 3 次 · 上次 6 个月前" in r59head(), True)
    check("改完给的是带撤销的那句，说得出改成了哪天",
          wait_toast("上次穿改成3月11日"), True)
    check("焦点留在日期框里（重画不许把它甩回页首）",
          page.evaluate("() => document.activeElement.id"), "clothWornDay")
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("撤销把 worn 与 lastWorn 一字不差还回来", r59(), keep)
    # 胜负手：改完记录，重跑一次过笺，那句劝告自己的措辞必须跟着变
    r59open()
    page.locator("#clothWornDay").fill("2026-03-11")
    page.wait_for_timeout(300)
    # 真落盘了吗：整页重开一次。`save(state)` 被摘掉时内存里的值照样对，
    # 只有重开才会露馅——而重开走的正是开机那份 normCloth 与渲染。
    page.reload()
    page.wait_for_timeout(700)
    page.evaluate(MK)
    check("重开之后账上还是改过的那一天（改动真的写进本机的，不是只挂在内存里）", page.evaluate(
        "() => { const w = state.wardrobe.find((x) => x.id === 'r59'); return [w.worn, dayStr(w.lastWorn)]; }"),
        [3, "2026.03.11"])
    check("重开之后瓷砖念的、编辑器回填的还是同一本账", page.evaluate("""() => {
      const tile = document.querySelector('#closet .item[data-id="r59"]');
      return [tile.getAttribute('aria-label'), tile.querySelector('.worn').textContent,
              document.querySelector('#clothWornDay').value]; }"""),
        ["灰蓝长袖，上衣，穿过 3 次", "3", "2026-03-11"])
    r59run()
    check("改完重算：同一件衣服，那句劝告改成 6 个月",
          "而且 6 个月没穿过了。再买一件，只会多一件不穿的。" in r59quote(), True)
    check("并且 7 个月那句不再出现在屏上", "7 个月" in r59quote(), False)
    # 再挪近一点，直接挪出久未穿那一层：整句话术换掉
    # 这里的 show('yi') 只切屏，不切页签——#clothActions 在 #yiPaneCloset 里，
    # 不切到柜子页的话 `page.click("#clothActions [data-wear-day='昨天']")` 报 "element is not visible"。
    page.evaluate("() => { state.clothSel = 'r59'; save(state); }")
    yi_tab(page, "closet")
    page.evaluate("() => { renderCloset(); renderClothActions(); }")
    page.wait_for_timeout(250)
    page.click("#clothActions [data-wear-day='昨天']")
    page.wait_for_timeout(300)
    check("快捷签「昨天」落在昨天那一天（与日期框同一把尺）", page.evaluate(
        "() => dayStr(state.wardrobe.find((w) => w.id === 'r59').lastWorn)"), "2026.09.16")
    r59run()
    check("挪到昨天之后久未穿那一层整个撤掉", page.evaluate("() => !!state.lastReport.stale"), False)
    check("那句「再买一件，只会多一件不穿的」不再对这件说出口",
          "只会多一件不穿的" in r59quote(), False)
    # 同一日历天只记一次（口径②）：摘要行一件只列一次，这里能加两次就是同一屏两个说法
    keep = r59()
    page.evaluate("() => { state.clothSel = 'r59'; save(state); }")
    yi_tab(page, "closet")
    page.evaluate("() => { renderCloset(); renderClothActions(); }")
    page.wait_for_timeout(250)
    page.click("#clothActions [data-wear-day='昨天']")
    page.wait_for_timeout(300)
    check("改到已经记过的那天：账上一个字都不动", r59(), keep)
    check("并且说得出为什么没动", wait_toast("同一天不记两遍"), True)
    check("什么都没改就不许冒出一条「撤销」",
          page.evaluate("() => !!document.querySelector('.toast.act button')"), False)
    # 正向那一格必须有：下面那格断的是「同一天再点一下什么都不变」，把 wearNow 整笔摘掉
    # 它照样绿（第 59 轮注入 I14 就是这个形状）。**只断「没变化」的断言，缺陷正好藏在
    # 「什么都不做」里** —— 与第 58 轮那条把沉默当被测行为钉死的老断言同一族。
    page.evaluate("""() => { const w = state.wardrobe.find((x) => x.id === 'r59');
      w.worn = 3; w.lastWorn = Date.now() - 5 * 86400000; save(state); renderCloset(); }""")
    page.wait_for_timeout(250)
    r59open()
    page.click("#wearIt")
    page.wait_for_timeout(300)
    check("「今天穿了」第一下真的记上了：次数从 3 变 4", r59()[0], 4)
    check("日子落到今天（不是把五天前那一天往前挪）",
          page.evaluate("() => { const w = state.wardrobe.find((x) => x.id === 'r59');"
                        " return dayStr(w.lastWorn) === dayStr(Date.now()); }"), True)
    check("摘要那一行真的把它列进「今天穿了」（改的是画面，不只是字段）",
          r59today(), ["灰蓝长袖"])
    page.evaluate("""() => { const w = state.wardrobe.find((x) => x.id === 'r59');
      w.worn = 4; w.lastWorn = Date.now(); save(state); renderCloset(); }""")
    page.wait_for_timeout(250)
    r59open()
    page.click("#wearIt")
    page.wait_for_timeout(300)
    check("「今天穿了」同一天点第二下不再 +1（以前会算成两次）", r59()[0], 4)
    check("那一枚也开得出口：说的是今天已经记过", wait_toast("今天已经记过"), True)
    # 次数：能加也能减，减到 0 就是「还没穿过」
    page.evaluate("""() => { const w = state.wardrobe.find((x) => x.id === 'r59');
      w.worn = 2; w.lastWorn = Date.now() - 3 * 86400000; save(state); renderCloset(); }""")
    page.wait_for_timeout(250)
    r59open()
    page.click("#wearDown")
    page.wait_for_timeout(300)
    check("−1 减一次，日子不动", [r59()[0], page.evaluate(
        "() => dayStr(state.wardrobe.find((w) => w.id === 'r59').lastWorn)")], [1, "2026.09.14"])
    check("角标与 aria-label 一起改成 1 次", [r59badge(), "穿过 1 次" in r59aria()], ["1", True])
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("次数也能反悔：撤销回到 2 次", r59()[0], 2)
    r59open()
    page.click("#wearDown")
    page.wait_for_timeout(300)
    r59open()
    page.click("#wearDown")
    page.wait_for_timeout(300)
    check("减到 0 = 「还没穿过」，那条日子一起清掉", r59(), [0, None])
    check("瓷砖角标整个不画了", r59badge(), "（没有角标）")
    check("瓷砖念的是「还没穿过」", r59aria(), "灰蓝长袖，上衣，还没穿过")
    check("头上那行念的是「还没穿过」", "还没穿过" in r59head(), True)
    check("摘要把它算进「1 件还没穿过」，而不是列进「今天穿了」",
          ["1 件还没穿过" in page.inner_text("#closetNote"), r59today()], [True, []])
    check("日期框跟着空掉（不许留着一张屏幕上已经不存在的日子）",
          page.evaluate("() => document.querySelector('#clothWornDay').value"), "")
    check("减到不能再减的那一枚是挡着的，不是藏起来（aria-disabled，还能聚焦）",
          [page.get_attribute("#wearDown", "aria-disabled"),
           page.evaluate("() => document.querySelector('#wearDown').disabled")], ["true", False])
    press(page, "#wearDown")
    page.wait_for_timeout(300)
    check("按下去说得出为什么挡着", wait_toast("不能再减"), True)
    check("挡着的那一下没有凭空造出撤销",
          page.evaluate("() => !!document.querySelector('.toast.act button')"), False)
    r59open()
    page.click("#wearUp")
    page.wait_for_timeout(300)
    check("0 次按 ＋1：这一笔只能记在今天，并且说出来", page.evaluate("""() => {
      const w = state.wardrobe.find((x) => x.id === 'r59');
      return [w.worn, dayStr(w.lastWorn) === dayStr(Date.now()),
              [...document.querySelectorAll('#closetNote [data-worn]')]
                .map((e) => e.textContent.trim()).indexOf('灰蓝长袖') >= 0]; }"""),
        [1, True, True])
    check("说的是「日子记在今天，不对就在上面改」", wait_toast("日子记在今天"), True)
    # 排序吃这两个数：柜子那两排「按久未穿 / 按常穿」必须当场换人
    page.evaluate("""() => { const w = state.wardrobe.find((x) => x.id === 'r59');
      w.worn = 1; w.lastWorn = Date.now() - 20 * 86400000; save(state); renderCloset(); }""")
    page.wait_for_timeout(250)
    check("「按久未穿排」第一块是刚被挪远的那件（20 天前，比另一件的 5 天更久）",
          page.eval_on_selector("#closet .item[data-id] .tag", "el => el.textContent"), "灰蓝长袖")
    page.click("#clothActions [data-wear-day='今天']")
    page.wait_for_timeout(300)
    check("改成今天之后第一块换成了另一件（排序吃的是手改的数）",
          page.eval_on_selector("#closet .item[data-id] .tag", "el => el.textContent"), "深蓝阔腿")
    # 两种坏输入：挡下来要说话，而且不许留下一格假账
    page.evaluate("""() => { const w = state.wardrobe.find((x) => x.id === 'r59');
      w.worn = 5; w.lastWorn = Date.now() - 3 * 86400000; save(state); renderCloset(); }""")
    page.wait_for_timeout(250)
    keep = r59()
    r59open()
    page.locator("#clothWornDay").fill("2027-12-31")
    page.wait_for_timeout(300)
    check("还没到的那一天挡下来，账上一个字不动", r59(), keep)
    check("挡下来要说话", wait_toast("还没到的那一天"), True)
    check("日期框弹回真记着的那一天（不许留着 2027 在那儿跟头上那行打脸）",
          page.evaluate("() => document.querySelector('#clothWornDay').value"), "2026-09-14")
    page.evaluate("() => { const el = document.querySelector('#clothWornDay');"
                  " el.value = ''; el.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(300)
    check("没填完不许把原来记着的那天抹掉", r59(), keep)
    check("没填完要说清为什么没改", wait_toast("日期没填全"), True)
    check("没填完也不许冒出撤销", page.evaluate("() => !!document.querySelector('.toast.act button')"), False)
    # 外来数据那一对冲突破口：0 次却带着日子，屏幕上就是两句相反的话
    check("normCloth 把 {worn:0, lastWorn:今天} 洗成「还没穿过」", page.evaluate("""() => {
      const w = normCloth({ id: 'r59c', name: '外来的一件', cat: '上衣', color: '#8899aa',
                            worn: 0, lastWorn: Date.now() });
      return [w.worn, w.lastWorn]; }"""), [0, None])
    check("洗完之后摘要行不再把它列进「今天穿了」", page.evaluate("""() => {
      const d = Date.now();
      state.wardrobe = [{ id: 'r59c', name: '外来的一件', cat: '上衣', color: '#8899aa',
                          worn: 0, lastWorn: d }].map(normCloth);
      state.clothSel = null; save(state); renderCloset();
      const tile = document.querySelector('#closet .item[data-id="r59c"]');
      return [tile.getAttribute('aria-label'),
              [...document.querySelectorAll('#closetNote [data-worn]')].map((e) => e.textContent.trim()),
              document.querySelector('#closetNote').textContent]; }"""),
          ["外来的一件，上衣，还没穿过", [], "柜里 1 件 · 1 件还没穿过（按久未穿排）今天还没记穿了什么。柜里那件的操作条上有「今天穿了」。"])
    # 360 宽：这一排不能撑成墙（第 16 轮那次的事故就是这个）
    page.set_viewport_size({"width": 360, "height": 780})
    # 上面那一格把柜子换成了「外来的一件」单件，编辑器随之清空——量的之前必须把
    # 这一节的柜子放回来，否则量到的是一个空 #clothActions（红得毫无理由）。
    page.evaluate("""() => {
      const d = Date.now(), DAY = 86400000;
      state.wardrobe = [
        { id: 'r59', name: '灰蓝长袖', cat: '上衣', color: '#d4c4b0', worn: 3, lastWorn: d - 210 * DAY, season: '四季' },
        { id: 'r59b', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: d - 5 * DAY }
      ].map(normCloth);
      state.clothSel = 'r59'; show('yi'); save(state); renderCloset();
    }""")
    # 这一格量的是编辑器里那几枚签与日期框：它们都在柜子页签的 #clothActions 里。
    # 只 show('yi') 的话 BLEED/TRUNC 扫的是过笺那一页，三条都会「干净」地空过（假绿）。
    yi_tab(page, "closet")
    page.evaluate("() => { renderCloset(); renderClothActions(); }")
    page.wait_for_timeout(250)
    check("360 宽：编辑器里的签一枚都不折字", page.evaluate(TRUNC, "#yi"), [])
    check("360 宽：穿用记录那两排一枚都不越纸边", page.evaluate(BLEED, "#yi"), [])
    check("360 宽：穿用记录那几枚签都还够按（不低于 24px）", page.evaluate("""() => {
      const els = [...document.querySelectorAll('#clothActions [data-wear-day], #clothActions #wearDown, #clothActions #wearUp')];
      return els.length >= 5 && Math.min(...els.map((e) => e.getBoundingClientRect().height)) >= 24; }"""), True)
    page.set_viewport_size({"width": 430, "height": 940})
    check("穿用记录这一路无 JS 报错", [e for e in errors if "favicon" not in e.lower()], [])

    print("\n--- 57. 网关地址：存之前就得校验，当场说成的那次重启必须还算 ---")
    # 这一节问的是一句话的两种口径能不能并存：当场的「已记下网关」与下次开机那一格凭空变空。
    # 断言一律落在**下一次开机还在不在**（page.reload），不是落在「输入框的值变了」。
    BASE = "https://127.0.0.1:8787/v1"  # 填得进账本的假网关：8787 是文档里那台局域网网关的端口
    LAN = "http://127.0.0.1:8787"       # 明文 http：安卓壳刻意允许（局域网那台网关），不是错误
    mark57 = len(errors)
    page.evaluate("() => { state.onboarded = true; save(state); show('me'); }")
    page.wait_for_timeout(250)

    def api_save(v):
        """往「算力网关」那一格填 v、按「保存接口」，一次读回四件事：
        说了什么话 / 内存里是谁 / 运行时 endpoint 是谁 / 框里剩谁 / 本机盘上落的是谁
        （disk 那一份就是下次开机 load() 读到的原始 JSON，比 reload 快，两者都要看）。"""
        page.evaluate("() => show('me')")
        page.locator("#apiUrl").fill(v)
        page.click("#saveApi")
        page.wait_for_timeout(260)
        return {
            "toast": toast_text(),
            "state": page.evaluate("() => state.apiUrl"),
            "endpoint": page.evaluate("() => window.JIAN_CONFIG.endpoint"),
            "box": page.input_value("#apiUrl"),
            "disk": page.evaluate("() => { try { const j = JSON.parse(localStorage.getItem(KEY));"
                                 " return j && j.apiUrl; } catch (e) { return 'PARSE-ERR'; } }"),
        }

    def boot_api():
        """真的重开一次，读回来的是「这一格开机后长什么样」——渲染也一并验了。"""
        page.reload()
        page.wait_for_timeout(700)
        page.evaluate("() => show('me')")
        page.wait_for_timeout(250)
        return {"state": page.evaluate("() => state.apiUrl"),
                "box": page.input_value("#apiUrl"),
                "on": page.evaluate("() => JianAPI.remoteOn()")}

    a = api_save(BASE)
    check("填对形状的那一条当场就说「已记下」", a["toast"].startswith("已记下网关"), True)
    check("https 的那一条不许顺带扯「不加密」", "不加密" in a["toast"], False)
    check("说成的那一次四本账当场就对上同一串",
          [a["state"], a["endpoint"], a["box"], a["disk"]], [BASE, BASE, BASE, BASE])

    # 真机上最常见的那一种写法：漏掉 scheme
    b = api_save("192.168.1.5:8787")
    check("漏 scheme 的那一条当场就说没存（不许说已记下）", wait_toast("没存"), True)
    check("没存那句不许同时冒出「已记下」", "已记下" in b["toast"], False)
    check("说得出它要长什么样（两种 scheme 都给出来，照着抄就行）",
          ["http://" in b["toast"], "https://" in b["toast"]], [True, True])
    check("举例举的就是这一族（192.168.1.5 这样的地址在话里）", "192.168.1.5" in b["toast"], True)
    check("挡下来那一次账本一个字都不动",
          [b["state"], b["endpoint"], b["disk"]], [BASE, BASE, BASE])
    check("挡下来那一次不许抹掉用户敲的那一串", b["box"], "192.168.1.5:8787")
    # 挡路的那一枚钮任何时候都还看得见、按得动（第 57 轮：不许用真 disabled 藏入口）
    check("「保存接口」那一枚不是真 disabled", page.evaluate(
        "() => { const el = document.querySelector('#saveApi');"
        " return [el.disabled, el.hasAttribute('disabled')]; }"), [False, False])
    check("屏幕上说的还是那一台作数的网关（没被没存成的那串带跑）",
          "网关" in page.inner_text("#apiState"), True)
    page.wait_for_timeout(2200)
    check("那句解释读得完（比默认 1.8 秒留得久）", toast_text().startswith("没存"), True)
    r = boot_api()
    check("重开之后账本里还是原来那一台（没存成的那串从头到尾没进过本机）", r["state"], BASE)
    check("重开之后那一格是作数的那一条，不是凭空变空", r["box"], BASE)

    # 另一头：局域网明文 http 是合法用法，不能当错误挡
    c = api_save(LAN)
    check("局域网 http 地址当场收下并说「已记下」", c["toast"].startswith("已记下网关"), True)
    check("顺带提一句它不加密（一句话，不发明新界面）", "不加密" in c["toast"], True)
    check("三本账立刻一致：state / endpoint / 本机盘",
          [c["state"], c["endpoint"], c["disk"]], [LAN, LAN, LAN])
    check("填了就算「指向网关」，顶栏当下离开本地口径",
          page.evaluate("() => JianAPI.remoteOn()"), True)
    r2 = boot_api()
    check("存进去的那一条下次开机还在（说成了就得算）", r2["state"], LAN)
    check("开机后那一格还写着它", r2["box"], LAN)
    check("开机后仍然算「指向网关」（不许悄悄回到本地口径）", r2["on"], True)

    # 剩下的坏形状：每一种都要说话、都不许动账本、都不许抹输入
    for v, tag in [("http://192.168.1.5: 8787", "中间有空格"),
                   ("https://" + "a" * 201, "超过 200 字"),
                   ("https://", "只有 scheme"),
                   ("ftp://192.168.1.5", "别的协议"),
                   ("javascript:alert(1)", "脚本地址")]:
        d = api_save(v)
        check(f"「{tag}」这一条挡住并且说出为什么",
              [d["toast"].startswith("没存"), len(d["toast"]) > 6], [True, True])
        check(f"「{tag}」不许改账本，也不许抹掉那一格",
              [d["state"], d["endpoint"], d["disk"], d["box"]], [LAN, LAN, LAN, v])
    long201 = "https://" + "a" * 201
    check("超长那句报得出字数（不是只说「不合法」）", "201" in api_save(long201)["toast"], True)

    # 正向的边界：上限不许悄悄收紧，否则上面那五发挡住一切也照样绿
    OK200 = "https://" + "a" * 200
    e = api_save(OK200)
    check("刚好 200 字的那一条要收（上限没被悄悄收紧）", [e["state"], e["disk"]], [OK200, OK200])
    r3 = boot_api()
    check("刚好 200 字的那一条重开还在", r3["state"], OK200)
    e1 = api_save("http://a")
    check("scheme 后面只剩一个字也要收（没被顺手判成无效）", e1["state"], "http://a")
    # 留空是合法值：它是「改回本地」那条路，不许被校验当成坏输入
    e2 = api_save("   ")
    check("留空说「已改回本地」，账本与运行时就都回到本地",
          [e2["toast"], e2["state"], e2["endpoint"], e2["disk"]], ["已改回本地", "", "", ""])
    check("留空之后那一格不留着一格假字", e2["box"], "")
    check("留空之后不再指向任何网关", page.evaluate("() => JianAPI.remoteOn()"), False)
    r4 = boot_api()
    check("「已改回本地」下次开机也算数（还是本地）", [r4["state"], r4["on"]], ["", False])
    check("规则只有一处定义：那条裸钳位正则不许回来，两处都走 normApi",
          [(JIAN / "state.js").read_text(encoding="utf-8").count("normApi("),
           (JIAN / "state.js").read_text(encoding="utf-8").count("s.apiUrl = normApi("),
           "S{1,200}" in (JIAN / "state.js").read_text(encoding="utf-8"),
           (JIAN / "app.js").read_text(encoding="utf-8").count("normApi(")],
          [2, 1, False, 1])
    # 这一节故意打不通几个端点，浏览器自己会往 console 里打 'Failed to load resource'；
    # 存的是 http://127.0.0.1:8787 这种跨源地址时，它还会再打一条 **CORS**：
    #   "Access to fetch at 'http://127.0.0.1:8787/v1/status' from origin 'null' has been
    #    blocked by CORS policy: No 'Access-Control-Allow-Origin' header ..."
    # 这两条都是**浏览器打的、预期之内的**噪音：这一节的被测行为恰恰是
    # 「填了一个地址之后去探活、探不到也不能抛」——探活失败本来就该在 console 里留一条。
    # 断言本来是「不许有未捕获异常」（pageerror），原来把 console.error 一起算了进来，
    # 于是它量的是「页面上不许出现任何跨源失败的痕迹」——那不是这个 App 能保证的事，
    # 也不是这一节在测的事。这里显式排除这两类浏览器噪音，**页面自己的 pageerror 一条都不放过**。
    seg = [e for e in errors[mark57:]
           if "Failed to load resource" not in e
           and "blocked by CORS policy" not in e
           and "Access to fetch at" not in e]
    errors[mark57:] = seg
    check("网关地址这一路没把异常抛到外面", seg, [])
    # 排掉的只是浏览器那两句噪音：pageerror 这一类**必须一条都没有**（这一格不许跟着放宽）
    check("网关地址这一路没有一条页面自己的异常（pageerror 一类为零）",
          [e for e in seg if e.startswith("pageerror")], [])

    print("\n--- 58. 味笺的人：名字就地改得动，删他要预告带走了哪几项忌口 ---")
    # 这一节问的是「用户造出来的数据改得动吗、删错了反悔得了吗、删它会不会连带毁掉别的承诺」。
    # 断言一律落在渲染出来的那一屏与下一次开机还在不在，不落在字段值上。
    mark58 = len(errors)
    P2 = '#people .card:nth-child(2) [data-rename="1"]'
    # 这一节量的是味笺排桌页签上那张「人」的卡片与它的名字输入框（0.6.0 起在 #weiPanePlan 里）。
    # 不切页签的话 `page.fill('#people .card…[data-rename]')` 会因为不可见而超时。
    #
    # 换数据与换屏必须落在**同一次 evaluate 里，并且放在 wei_tab 之前**。原来这里三件事的
    # 顺序是「先 wei_tab → 再写 state.people」。§57 结束时屏停在「我的」（它整节都在
    # #apiUrl 那一格上），于是 `wei_tab(page,'plan')` 里的 `setWeiTab('plan')` 调
    # renderWei() → renderWeiPeople()，画的是**§57 留下来的那两个默认人**（我 / 同行）；
    # 接着那句 evaluate 只改了 `state.people` 就 `save(state)` 过日子，**没重画 #people**。
    # 后面每一句 page.get_attribute('#people [data-del="1"]') 都是要等一个第 2 张卡才有的
    # 「移除」——DOM 里只有 2 张卡时 `[data-del="1"]` 正好不存在？不，它是存在的（第 2 张卡
    # 就是 i=1）……真正的坑是**人数**：`state.people` 那一刻已经有 3 个人、DOM 上只有 2 张，
    # 而 `#people` 的空态与卡片数是渲染期的事，屏上根本没刷新过。
    # 实测报的就是 `page.get_attribute: Timeout 30000ms`（等 `[data-del="1"]`）——
    # 那不是元素藏起来，是**这一节量的 DOM 还是上一节那一份**。
    # 现在：先落数据、再 show('wei') + setWeiTab('plan')（setWeiTab 自己会调 renderWei），
    # 一句话里既换数据又换屏，画出来的就是本节种下的那三个人。
    wei_tab(page, "plan")
    page.evaluate("""() => {
      state.onboarded = true;
      state.points = 30;
      state.people = [{ name: '我', chips: ['辣'] },
                      { name: '阿姨', chips: ['海鲜', '蒜', '清淡'] },
                      { name: '小周', chips: [] }];
      state.lastWei = null; state.weiHist = [];
      state.weiMenu = '清蒸鲈鱼\\n蒜蓉西兰花\\n白切鸡\\n米饭';
      document.querySelector('#menu').value = state.weiMenu;
      save(state);
      // 换完数据必须自己重画一遍：上面那次 wei_tab 画的是**换数据之前**的那一份。
      renderWeiPeople();
    }""")
    page.wait_for_timeout(300)

    # 这一格**必须排在任何改名之前**：它量的是模板自己给读屏器的那句预告。
    # 第 63 轮第一版只在改名之后量它，于是读到的其实是改名那条路顺手 `setAttribute`
    # 写上去的标签——我把模板里那句换成「移除这一行」，整节照样全绿（注入实测报的是
    # 「改了源码，e2e#58 全都过了」）。**一句只能守一条路的断言，守的不是它名字里那条。**
    check("还没人改过名时，「移除」那句预告就已经写着会带走几项忌口（模板给读屏器的那一句）",
          page.get_attribute('#people [data-del="1"]', "aria-label"),
          "移除 阿姨，会连带去掉 3 项忌口")

    def rename(i, v, real=False):
        """改第 i 个人的名字。real=True 走真人那一条（打字 → 焦点离开 = 提交）；
        否则直接落值再派一次 change —— 要绕过 maxlength 塞 25 字进去，只有这一条路。
        两种都不点「填示例」那一类会自己冒话的按钮：那一句会把改名那句顶掉（toast 只留一条）。"""
        sel = '#people .card:nth-child(%d) [data-rename="%d"]' % (i + 1, i)
        if real:
            page.fill(sel, v)
            page.evaluate("() => document.activeElement.blur()")
        else:
            page.evaluate("() => { const e = document.querySelector(%s);"
                          " e.value = %s; e.dispatchEvent(new Event('change')); }"
                          % (json.dumps(sel), json.dumps(v, ensure_ascii=False)))
        page.wait_for_timeout(250)
        return {"toast": toast_text(), "box": page.input_value(sel),
                "state": page.evaluate("() => state.people[%d].name" % i),
                "aria": page.evaluate("() => { const b = document.querySelector('#people [data-del=\"%d\"]');"
                                      " return b ? b.getAttribute('aria-label') : null; }" % i)}

    check("名字那一格是改得动的输入框，不是行上一枚死字",
          page.evaluate("""() => {
            const c = document.querySelector('#people .card:nth-child(2)');
            const inp = c.querySelector('input[data-rename]');
            return [!!inp, !c.querySelector('b'), inp ? inp.value : null,
                    inp ? inp.maxLength : null, inp ? inp.getAttribute('aria-label') : null]; }"""),
          [True, True, "阿姨", 20, "改「阿姨」的名字"])

    # 真人那一条路：打字、焦点走开，一次改完整屏写着这个名字的地方
    page.evaluate("() => { window.__inp = document.querySelector('%s'); }" % P2)
    r = rename(1, "姨", real=True)
    check("改完：框里、库里同一串，说的就是改成了什么",
          [r["box"], r["state"], r["toast"]], ["姨", "姨", "已改名：「阿姨」→「姨」"])
    check("改名是就地改这一格，没重建整片（原来那个输入框还挂在树上）",
          page.evaluate("() => [window.__inp.isConnected, window.__inp.value]"), [True, "姨"])
    check("行上「移除」那句预告跟着名字一起刷，屏上不许留一个旧名字",
          r["aria"], "移除 姨，会连带去掉 3 项忌口")
    check("味笺这一屏一个字都不再写着旧名字",
          page.evaluate("() => document.querySelector('#wei').textContent.indexOf('阿姨')"), -1)
    page.reload()
    page.wait_for_timeout(700)
    wei_tab(page, "plan")
    page.wait_for_timeout(250)
    check("改完的名字下一次开机还在这一格上（不是只活在内存里）",
          [page.input_value(P2), page.evaluate("() => state.people[1].name")], ["姨", "姨"])

    r = rename(1, "   ")
    check("空名字不许静默弹回：说清是这句把它填回去的", r["toast"].startswith("名字不能空着"), True)
    check("空名字那一趟库里一个字节都没动", [r["box"], r["state"]], ["姨", "姨"])

    r = rename(1, "名" * 25)
    check("超长那一串当场说留了几字", [r["toast"].startswith("名字太长"), "20" in r["toast"]], [True, True])
    check("超长：框里与库里都是那 20 字（屏上不许还挂着 25 字）",
          [len(r["box"]), len(r["state"])], [20, 20])
    page.reload()
    page.wait_for_timeout(700)
    wei_tab(page, "plan")
    page.wait_for_timeout(250)
    check("重开之后还是那 20 字（当场那一条与开机钳位同口径）",
          len(page.input_value(P2)), 20)
    rename(1, "姨")

    r = rename(2, "姨")
    check("重名不许弹回：真的改了，同时点出两行会看着一样",
          [r["box"], r["state"], "已经有一个「姨」" in r["toast"]], ["姨", "姨", True])
    check("两行同名也各有自己的那句预告（按的是哪一行说得清）",
          page.evaluate("() => [document.querySelector('#people [data-del=\"1\"]').getAttribute('aria-label'),"
                        " document.querySelector('#people [data-del=\"2\"]').getAttribute('aria-label')]"),
          ["移除 姨，会连带去掉 3 项忌口", "移除 姨，他没挂忌口"])

    # 删人：按下去之前就得知道会带走什么（可见的那一行下面正摊着那三枚签）
    check("「移除」的名字里先写着连带带走几项忌口（读屏器按之前听得见）",
          page.get_attribute('#people [data-del="1"]', "aria-label"), "移除 姨，会连带去掉 3 项忌口")
    page.click('#people [data-del="1"]')
    page.wait_for_timeout(250)
    t = toast_text()
    check("移除那一句点名带走了几项、是哪几项",
          [t.startswith("已移除「姨」"), "3 项忌口" in t, "海鲜" in t, "清淡" in t],
          [True, True, True, True])
    check("移除之后那一行真的从屏上没了（不是只换了个字）",
          page.evaluate("() => document.querySelectorAll('#people .card').length"), 2)
    check("反悔那一枚摆着，没藏", page.evaluate("() => !!document.querySelector('.toast.act button')"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(250)
    check("撤销那句说的是忌口一起回来，不只是人回来了", wait_toast("3 项忌口一起回来"), True)
    check("撤销按快照填回：名字、位置、三组忌口一项都不少",
          page.evaluate("() => state.people.map((p) => [p.name, p.chips])"),
          [["我", ["辣"]], ["姨", ["海鲜", "蒜", "清淡"]], ["姨", []]])
    check("屏上那一行又数得回那三枚签",
          page.evaluate("() => [...document.querySelectorAll('#people .card:nth-child(2) .chips button')]"
                        ".map((b) => b.textContent)"), ["海鲜", "蒜", "清淡", "忌口"])
    page.reload()
    page.wait_for_timeout(700)
    check("撤销填回的那一组忌口重开之后还在本机盘上",
          page.evaluate("() => state.people[1].chips"), ["海鲜", "蒜", "清淡"])

    # 改名牵不牵动已经在屏上的旧结果：查过才敢钉 —— 名字不进判定、也不印在旧笺上
    # #runWei / #weiResult / #weiStale 都在排桌页签里：不切过去，下面 page.click("#runWei")
    # 会在一个 hidden 的按钮上等 30 秒。
    wei_tab(page, "plan")
    page.wait_for_timeout(250)
    check("进屏时还没有排过桌（下面那一串要有东西可量）",
          page.evaluate("() => !!state.lastWei"), False)
    page.click("#runWei")
    page.wait_for_function("() => !!state.lastWei && !!document.querySelector('#weiResult .sheet')",
                           timeout=15000)
    page.wait_for_timeout(300)
    talk1 = page.evaluate("() => state.lastWei.talk")
    bans1 = page.evaluate("() => state.lastWei.r.boom.map((x) => x.dish + '/' + x.why)")
    check("这一桌真的排出来了（下面三格有东西可量）", [len(talk1) > 6, len(bans1) > 0], [True, True])
    check("屏上那一张旧笺本来就没印人名（改名无处要刷 —— 这条是本轮决定的地基）",
          page.evaluate("() => document.querySelector('#weiResult .sheet').textContent.indexOf('姨') < 0"),
          True)
    r = rename(0, "老王")
    # 量「旧笺还在不在」要回到排桌页签上：屏换了之后 #weiResult .sheet 是 hidden 的，
    # `is_visible` 会假红成「旧笺被弄没了」。
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    check("改了名字，屏上那一张旧笺与那句群话术原样留着（只改往后，不偷改已经说过的那一句）",
          [page.evaluate("() => JSON.stringify(state.lastWei.talk)") == json.dumps(talk1, ensure_ascii=False),
           page.evaluate("() => state.lastWei.r.boom.map((x) => x.dish + '/' + x.why)") == bans1,
           page.is_visible("#weiResult .sheet")], [True, True, True])
    check("改名也不许把「这张是上一版的」那条提示谎点亮起来",
          page.evaluate("() => document.querySelector('#weiStale').style.display"), "none")
    t1 = page.evaluate("() => state.lastWei.t")
    page.click("#runWei")
    page.wait_for_function("() => state.lastWei.t !== %d" % t1, timeout=15000)
    page.wait_for_timeout(400)
    check("重排一次照样成（改名没把判定这条路弄坏：它只吃忌口和人数）",
          page.is_visible("#weiResult .sheet"), True)

    # 量窄屏之前先把名字放到上限那 20 字：短名字下 input 的固有宽度不会顶人，
    # 少了 min-width:0 也照样不越界 —— 那样这一格就没牙了（第 63 轮注入实跑量出来的）。
    rename(1, "名" * 20)
    page.set_viewport_size({"width": 360, "height": 780})
    # 窄屏量的是人卡（#people）与那一行：都在排桌页签里，停在别处 BLEED 会空扫一场。
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    check("360 宽：二十字的名字摆在人卡上，一片都不越纸边", page.evaluate(BLEED, "#wei"), [])
    check("360 宽：人名那一格与「移除」都还够按（不低于 30px）", page.evaluate("""() => {
      const els = [...document.querySelectorAll('#people .card:nth-child(1) .topbar > *')];
      return [els.length, Math.min(...els.map((e) => e.getBoundingClientRect().height)) >= 30]; }"""),
      [2, True])
    page.set_viewport_size({"width": 430, "height": 940})
    check("人名这一路没把异常抛到外面",
          [e for e in errors[mark58:] if "favicon" not in e.lower()
           and "Failed to load resource" not in e], [])

    print("\n--- 59. 订阅关得掉，也不许写着指向已关掉的那一笺 ---")
    # 这一节问两件事：
    #   ① 「未订阅」这一屏到得了吗——以前全仓只有 me.js 的 buy() 写 state.plan，
    #      没有任何一处能把它设回 null，而 state.js 认 null、这一行也会印「未订阅」：
    #      界面上摆着一个永远回不去的状态，想回去只能自己手写 JSON 导进来。
    #   ② 订阅指向的那一笺从底栏关掉了（「开哪一笺」那一排不动 plan），屏上怎么说。
    # 断言一律落在渲染出来的那一屏与 page.reload() 之后还在不在，不落在 state.plan 上。
    mark59 = len(errors)

    def buy_open(k):
        """走真路开一笺：那一格折叠着，先摊开再按（details 的展开态不跟着 reload 走）。"""
        page.evaluate("() => { document.querySelector('.topup').open = true; }")
        page.wait_for_timeout(150)
        page.click('[data-buy="%s"]' % k)
        page.wait_for_timeout(300)

    def clear_toast():
        page.evaluate("() => { const t = document.querySelector('.toast'); if (t) t.remove(); }")

    page.evaluate("""() => {
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.plan = null; state.points = 20; state.album = [];
      save(state); show('me');
    }""")
    page.wait_for_timeout(300)
    check("「未订阅」这一屏到得了：钱包那一行就写着它", page.inner_text("#planName"), "未订阅")
    check("没有订阅时不摆那枚签（按下去只能说「现在就是未订阅」的东西不许摆）",
          page.is_visible("#planOff"), False)
    buy_open("yi")
    check("开完之后那一行写着衣笺", page.inner_text("#planName"), "衣笺")
    check("写着订阅的那一片，就摆着关掉它的那一枚", page.is_visible("#planOff"), True)
    check("新加的这一枚命中区不低于 32px（全 App 那条线，它也得过）",
          page.evaluate("""() => { const r = document.querySelector('#planOff').getBoundingClientRect();
            return [r.width >= 32, r.height >= 32]; }"""), [True, True])
    check("读屏器按之前就听得见这一下要干什么", page.get_attribute("#planOff", "aria-label"),
          "取消订阅（现在订阅的是衣笺）")
    clear_toast()
    page.click("#planOff")
    page.wait_for_timeout(300)
    t = toast_text()
    check("取消那一下说清了取消了什么、往后会怎样",
          [t.startswith("已取消衣笺订阅"), "这一笺重新开始扣点" in t], [True, True])
    check("屏上立刻回到「未订阅」（不是只改了字段）", page.inner_text("#planName"), "未订阅")
    check("关掉之后那枚签自己收起来，不留一枚按了没用的", page.is_visible("#planOff"), False)
    check("反悔那一枚摆着，没藏", page.evaluate("() => !!document.querySelector('.toast.act button')"), True)
    check("取消之后衣笺真的重新开始扣点（那个「不再扣点」的名额不再白占着）",
          page.evaluate("""() => { const b = state.points; spend(2, 'yi'); renderWallet();
            return [b, document.querySelector('#points').textContent]; }"""), [20, "18"])
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("撤销之后屏上又写着衣笺、那枚签又摆回来",
          [page.inner_text("#planName"), page.is_visible("#planOff")], ["衣笺", True])
    clear_toast()
    page.click("#planOff")
    page.wait_for_timeout(300)
    page.reload()
    page.wait_for_timeout(800)
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    check("关掉订阅下次开机还是「未订阅」（真的写进本机盘，不是只刷了一次屏）",
          page.inner_text("#planName"), "未订阅")
    check("下次开机也不再摆那枚签", page.is_visible("#planOff"), False)
    # 「全笺」是另一种订阅名：笺点那一格写着不限，取消之后必须改口
    page.evaluate("() => { state.modules = { yi: true, wei: true, yan: true };"
                  " state.plan = 'all'; state.points = 20; save(state); renderMe(); }")
    page.wait_for_timeout(250)
    check("全笺订阅时笺点那一格写着不限", page.inner_text("#points"), "不限")
    clear_toast()
    page.click("#planOff")
    page.wait_for_timeout(300)
    check("取消全笺订阅那句说的是「三笺都重新开始扣点」", wait_toast("三笺都重新开始扣点"), True)
    check("取消全笺订阅：那一格当场不再写着不限", page.inner_text("#points"), "20")
    # ②订阅指向的那一笺被关掉了：屏上这一行不许照旧只印一个名字
    page.evaluate("() => { state.plan = null; state.modules = { yi: true, wei: true, yan: true };"
                  " save(state); show('me'); }")
    page.wait_for_timeout(250)
    buy_open("yi")
    page.evaluate("() => document.querySelector('[data-mod=\"yi\"]').click()")
    page.wait_for_timeout(300)
    check("关掉订阅指向的那一笺：那一行当场说清它指着一笺已经不在底栏的订阅",
          page.inner_text("#planName"), "衣笺 · 这一笺已经关掉了")
    check("同一屏上那三处说的是同一件事：那一排的开关、底栏、钱包那一行",
          page.evaluate("""() => [
            document.querySelector('[data-mod="yi"]').getAttribute('aria-pressed'),
            [...document.querySelectorAll('#nav button')].map((b) => b.textContent).indexOf('衣笺') < 0,
            document.querySelector('#planName').textContent.indexOf('已经关掉了') >= 0]"""),
          ["false", True, True])
    check("这一行右边那枚签还在：这个状态关得掉，不用去手写 JSON 导进来",
          page.is_visible("#planOff"), True)
    clear_toast()
    page.click("#planOff")
    page.wait_for_timeout(300)
    check("取消这一份时不许再补一句「重新开始扣点」——同一屏刚说过那一笺关着",
          wait_toast("本来就关着，没在扣点"), True)
    check("取消之后那一行回到未订阅（那句「已经关掉了」跟着一起没了）",
          page.inner_text("#planName"), "未订阅")
    # 那一行是跟着模块开关活的：把那一笺重新开回来，就不许还写着「已经关掉了」
    page.evaluate("() => { state.plan = 'yi'; save(state); renderMe(); }")
    page.wait_for_timeout(250)
    check("订阅又指回那一笺、而它仍关着：那一行重新说清（不是刷一次就完）",
          page.inner_text("#planName"), "衣笺 · 这一笺已经关掉了")
    page.evaluate("() => document.querySelector('[data-mod=\"yi\"]').click()")
    page.wait_for_timeout(300)
    check("把那一笺开回来：那一行立刻不再写着「已经关掉了」", page.inner_text("#planName"), "衣笺")
    # 导入的备份能直接写成「订阅：衣笺 + 衣笺关着」，关模块那一路管不到它——
    # 同一句话必须在重开之后也说得出，不是只在用户按开关那一下才成立。
    page.evaluate("""() => { cancelSoon(); localStorage.setItem('jian.v1', JSON.stringify({
      schema: 2, onboarded: true, modules: { yi: false, wei: true, yan: true }, home: 'wei',
      points: 30, plan: 'yi', wardrobe: [], people: [{ name: '我', chips: [] }], album: [],
      yanCards: [], weiHist: [], closetSort: 'freq', reportStyle: 'card' })); }""")
    page.reload()
    page.wait_for_timeout(800)
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    check("导入来的「订阅指向已关掉的一笺」，重开之后那一行照样说得清",
          page.inner_text("#planName"), "衣笺 · 这一笺已经关掉了")
    check("这一份也关得掉（那枚签就摆在同一行）", page.is_visible("#planOff"), True)
    page.set_viewport_size({"width": 360, "height": 780})
    page.wait_for_timeout(300)
    check("360 宽：那一行加上「已经关掉了」与那枚签，一片都不越纸边", page.evaluate(BLEED, "#me"), [])
    page.set_viewport_size({"width": 430, "height": 940})
    check("订阅这一路没把异常抛到外面",
          [e for e in errors[mark59:] if "favicon" not in e.lower()
           and "Failed to load resource" not in e], [])

    print("\n--- 60. 排过的桌出得去：每一桌有「删」，删错一桌按原位填回 ---")
    # 这一节问的是第 65 轮那份只读审计：state.weiHist 全仓只有 wei.js 的 rememberWei 一个写入口
    # （unshift + slice(0, WEI_HIST)），没有任何删的入口——误把一整页聊天记录贴成一桌，那一格
    # 就永远占着四格之一（一格里存着整份菜单文本），只能靠再排四桌把它挤掉。这一轮补一枚「删」。
    # 断言一律落在渲染出来的那一屏与 page.reload() 之后还在不在，不落在 state.weiHist 上。
    mark60 = len(errors)

    def clear60():
        # 不能借用 §59 里那个 clear_toast：e2e_only 按节切字节，单独跑第 60 节时它不存在
        page.evaluate("() => { const t = document.querySelector('.toast'); if (t) t.remove(); }")

    HIST4 = r"""() => {
      const d = Date.now(), DAY = 86400000;
      state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
      state.points = 30; state.plan = null;
      state.people = [{ name: '我', chips: ['辣'] }, { name: '小周', chips: ['蒜'] }];
      state.lastWei = null; state.album = [];
      state.weiMenu = "清蒸鲈鱼\n白灼菜心\n米饭";
      state.weiHist = [
        { menu: '清蒸鲈鱼\n白灼菜心\n米饭', n: 3, t: d, chips: ['辣'] },
        { menu: '宫保鸡丁\n白切鸡\n米饭\n冬瓜排骨汤', n: 2, t: d - DAY, chips: ['海鲜'] },
        { menu: '蛋炒饭', n: 1, t: d - 2 * DAY, chips: [] },
        { menu: '酸菜鱼\n宫保鸡丁\n白切鸡\n米饭\n紫菜蛋花汤\n地三鲜\n蛋炒饭\n白灼菜心\n清蒸鲈鱼\n冬瓜排骨汤\n手撕包菜\n蒜蓉西兰花',
          n: 1, t: d - 3 * DAY, chips: ['辣', '蒜', '海鲜', '清淡'] }];
      document.querySelector('#menu').value = state.weiMenu;
      save(state); return state.weiHist.length }"""
    FULL = ["今天 · 3 人 · 3 道", "昨天 · 2 人 · 4 道", "2 天前 · 1 人 · 1 道", "3 天前 · 1 人 · 12 道"]

    def hist_labels():
        return page.eval_on_selector_all("#weiHist [data-hist]", "els => els.map(e => e.textContent.trim())")

    def reboot_to_wei():
        # 「重开之后还在不在」这一层要过的门：整页重载 + 重新进屏，不是读一次内存。
        # 0.6.0 起「重新进屏」还得切到排桌页签：#weiHist 那一栏在 #weiPanePlan 里，
        # 停在过笺上时 `page.click("#weiHist [data-hdel='3']")` 会报 "element is not visible"。
        page.reload()
        page.wait_for_timeout(800)
        wei_tab(page, "plan")
        page.wait_for_timeout(300)

    page.evaluate(HIST4)
    # 上一节停在「我的」；HIST4 里那句 show('wei') 只切屏，0.6.0 还得切到排桌页签，
    # 否则 #weiHist 是 hidden 的，下面 `page.click("#weiHist [data-hdel='3']")` 超时。
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    check("四桌照旧摆着，签上还是「时间 · 几人 · 几道」（加「删」没动原来那一行字）",
          hist_labels(), FULL)
    check("每一桌右边都摆着「删」那一枚，一桌一枚",
          page.eval_on_selector_all("#weiHist [data-hdel]", "els => els.map(e => e.textContent.trim())"),
          ["删"] * 4)
    check("按下去之前那一句就写着删的是哪一桌、带走几道菜（读屏器按之前听得见）",
          page.get_attribute("#weiHist [data-hdel='3']", "aria-label"),
          "删掉「3 天前」那一桌，会带走 12 道菜的菜单")
    check("预告里的道数与签上写的是同一个数（两处不许一个改了一个没改）",
          page.evaluate("""() => [...document.querySelectorAll('#weiHist .hpair')].map((g) => {
            const h = g.querySelector('[data-hist]').textContent;
            const a = g.querySelector('[data-hdel]').getAttribute('aria-label');
            return (h.match(/· (\\d+) 道/) || [])[1] === (a.match(/带走 (\\d+) 道菜/) || [])[1]; })"""),
          [True, True, True, True])
    check("「删」那一枚命中区不低于 32px（§41 那条线，可它要有排过的桌才画得出来）",
          page.evaluate("""() => [...document.querySelectorAll('#weiHist [data-hdel]')].map((b) => {
            const r = b.getBoundingClientRect(); return [r.width >= 32, r.height >= 32]; })"""),
          [[True, True]] * 4)
    check("两枚签包在同一格：不许出现「删」换行后挨着别一桌的签那种摆法",
          page.evaluate("() => [...document.querySelectorAll('#weiHist .hpair')]"
                        ".map((g) => [!!g.querySelector('[data-hist]'), !!g.querySelector('[data-hdel]')])"),
          [[True, True]] * 4)

    # 删掉最旧那一格（审计里那句「误贴成一桌」就是它）
    clear60()
    page.click("#weiHist [data-hdel='3']")
    page.wait_for_timeout(300)
    t = toast_text()
    check("删的那一句点名是哪一桌、带走了几道菜",
          [t.startswith("已删掉「3 天前」那一桌"), "12 道菜" in t], [True, True])
    check("同一句说清笺册里那张笺没跟着没（删掉的只是这一桌的菜单记录）",
          "笺册里那张笺没动" in t, True)
    check("屏上那一桌真的少了：只剩三枚签，「12 道」那一行整个不见了",
          [hist_labels(), "12 道" in " ".join(hist_labels())], [FULL[:3], False])
    check("反悔那一枚摆着，没藏", page.evaluate("() => !!document.querySelector('.toast.act button')"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("反悔那句报的是回到第几格、几道菜（不是只说「回来了」）", wait_toast("那一桌回到第 4 格"), True)
    check("反悔之后那一桌回到**原来那一格**：四桌顺序一字不差", hist_labels(), FULL)
    reboot_to_wei()
    check("反悔填回的那一桌重开之后还在第四格（真写进本机盘，不是只刷了一次屏）", hist_labels(), FULL)

    # 删中间那一格：位置这件事只有删的不是头也不是尾才量得出来
    clear60()
    page.click("#weiHist [data-hdel='1']")
    page.wait_for_timeout(300)
    check("删掉中间那一格，剩下的不许窜位", hist_labels(), [FULL[0], FULL[2], FULL[3]])
    reboot_to_wei()
    check("删了重开还在少：还是那三桌、还是那个顺序", hist_labels(), [FULL[0], FULL[2], FULL[3]])
    check("重开之后「删」还是三枚（入口跟着桌数走，不是画过一次就不管）",
          page.evaluate("() => document.querySelectorAll('#weiHist [data-hdel]').length"), 3)
    clear60()
    page.click("#weiHist [data-hdel='1']")
    page.wait_for_timeout(300)
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    # 期望是**三**桌不是四桌：第 2 格（「昨天」那一桌）在这一节更早的那一次删除里
    # 已经删掉了，而且那一次是**真的删**（量的是「删中间不许窜位」，删完就 reboot 了，
    # 没有反悔过）。所以此刻历史是 [今天, 2 天前, 3 天前]，刚才这一下删的是
    # 第 2 格（2 天前那桌）再反悔——它必须回到第 2 格，不是被塞到末尾变成「最旧那一桌」。
    # 这条断言要钉的就是**位置**：三桌里填回第 2 格与四桌里填回第 2 格验的是同一件事，
    # 所以期望按此刻真实的三桌逐项写死（不放宽成长度 ≥3、也不写成「包含」——
    # 那两种写法都会把「填回末尾」这个真缺陷一起放过去）。
    # 原来这里写的是 FULL（四桌），那是从「四桌完整」的上下文里抄过来的期望，
    # 而这一节的上下文早就不是四桌了：红的不是反悔（它填对了），是期望值。
    check("重开之后再删一次、再反悔，仍然填回同一格（第 2 格，不是塞回末尾）",
          hist_labels(), [FULL[0], FULL[2], FULL[3]])

    # 一桌一桌删到空：那一栏整个收起来，但每一步都要说话，而且撤得回来
    #
    # 删的顺序必须是「从最后一格往前」——每次删都会重画、后面的下标整体前移，
    # 所以只有降序才保证每一次点的都是当前真实存在的最后一格。
    # 原来这里把起始格写死成 3（那是以「四桌」为前提）；此刻历史只剩三桌（见上一条注释），
    # `[data-hdel='3']` 不存在，于是 page.click 白等 30 秒抛出去——
    # 那不是产品坏了，是**测试把桌数写死了**。现在按屏上真实存在的格数算起点，
    # 但删的仍然是「每一格的最后一格」，一直删到一桌不剩；下面那两条断言
    # （整栏收起、最后删掉的是第 1 格那桌）比原来更严，一格都没放松。
    before_n = page.evaluate("() => document.querySelectorAll('#weiHist [data-hdel]').length")
    check("删空之前先确认屏上真的摆着三桌（不然下面那一圈是空转）", before_n, 3)
    for i in range(before_n - 1, -1, -1):
        page.click("#weiHist [data-hdel='%d']" % i)
        page.wait_for_timeout(220)
    check("删到一桌不剩：那一栏整个收起来（不是摆着一个空框）",
          page.evaluate("() => [document.querySelector('#weiHist').style.display,"
                        " document.querySelector('#weiHist').innerHTML]"), ["none", ""])
    check("删掉最后一桌那一句照样点名带走了几道菜", "道菜的菜单" in toast_text(), True)
    check("反悔那一枚还摆着", page.evaluate("() => !!document.querySelector('.toast.act button')"), True)
    page.click(".toast.act button")
    page.wait_for_timeout(300)
    check("那一次反悔填回的是最后删掉的那一桌、在原位第 1 格（提示只留一条，不是把四桌一起变回来）",
          hist_labels(), [FULL[0]])

    # 屏上的 DOM 落后于 state（外来备份刚盖进来、别的路改过）：不许静默，也不许抛。
    # 这一趟故意**只改内存不落盘**——守的是「按下去那一格已经不在了」这条兜底路，
    # 它只重画屏、不写盘，所以下面重开之后该照旧摆着盘上那一桌。
    page.evaluate("() => { state.weiHist = []; }")
    clear60()
    page.click("#weiHist [data-hdel='0']")
    page.wait_for_timeout(300)
    check("那一桌已经不在了时按「删」说得出为什么（不是按了没反应）", wait_toast("已经不在了"), True)
    check("同一趟把屏刷回真相：那一栏收起来了",
          page.evaluate("() => document.querySelector('#weiHist').style.display"), "none")
    reboot_to_wei()
    check("那一条兜底路没有顺手写盘：重开之后盘上那一桌还在",
          hist_labels(), [FULL[0]])

    # 出口存在的意义：误贴那一桌不必靠「再排四桌」挤掉
    page.evaluate(HIST4)
    # HIST4 里那句 show('wei') 不切页签：这一节要按 #weiHist 的「删」，
    # 页签不在 plan 上时就又回到「element is not visible」那 30 秒。
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    page.click("#runWei")
    page.wait_for_function("() => !!state.lastWei && !!document.querySelector('#weiResult .sheet')",
                           timeout=20000)
    page.wait_for_timeout(400)
    check("重排同一份菜单是把那一桌挪到最前，不是留两行几乎一样的签",
          hist_labels(), ["今天 · 2 人 · 3 道"] + FULL[1:])
    clear60()
    page.click("#weiHist [data-hdel='3']")
    page.wait_for_timeout(300)
    check("删掉误贴那一桌，不许把屏上那一张笺一起弄没（它存的是另一份东西）",
          page.is_visible("#weiResult .sheet"), True)
    page.evaluate("() => { const el = document.querySelector('#menu');"
                  " el.value = '手撕包菜\\n紫菜蛋花汤\\n白切鸡\\n米饭\\n地三鲜'; }")
    page.click("#runWei")
    page.wait_for_function("() => state.lastWei && state.lastWei.menu.indexOf('手撕包菜') === 0", timeout=20000)
    page.wait_for_timeout(400)
    lab = hist_labels()
    check("腾出格子之后不必把最旧的挤掉：还是四桌，而误贴那一桌没有回来占格",
          [len(lab), "12 道" in " ".join(lab), lab[0].startswith("今天")], [4, False, True])
    reboot_to_wei()
    check("重开之后本机盘上真的只剩这四桌（删掉的那一桌没有诈尸）",
          [page.evaluate("() => state.weiHist.length"), "12 道" in " ".join(hist_labels())], [4, False])

    # 版面预算：加了「删」之后 360 的纸上一桌正好占一行，四桌 = 四行；§13 那道 200px 的门
    # 只看默认态，量不到「道数写在预告里」这一格，所以这一轮自己再钉一次。
    page.set_viewport_size({"width": 360, "height": 780})
    page.evaluate(HIST4)
    # BLEED / 高度预算量的都是 #weiHist 那一栏（在排桌页签里）。
    wei_tab(page, "plan")
    page.wait_for_timeout(300)
    check("360 宽：一桌一格带上「删」，一片都不越纸边", page.evaluate(BLEED, "#wei"), [])
    h60 = page.evaluate("() => Math.round(document.querySelector('#weiHist').getBoundingClientRect().height)")
    check("360 宽：记满四桌 + 每桌一枚「删」，这堵墙不超过 200px（实测 %dpx）" % h60, h60 <= 200, True)
    page.set_viewport_size({"width": 430, "height": 940})
    check("排过的桌这一路没把异常抛到外面",
          [e for e in errors[mark60:] if "favicon" not in e.lower()
           and "Failed to load resource" not in e], [])

    ctx.close()
    browser.close()

print("\n--- 9. 运行时错误 ---")
real = [e for e in errors if "favicon" not in e.lower()]
if real:
    for e in real:
        print("   " + e)
else:
    print("   无")
check("无 JS 运行时错误", len(real), 0)

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks)-len(bad)} 通过 / {len(bad)} 失败")
sys.exit(1 if bad else 0)
