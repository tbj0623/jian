# 冒烟：开一次 index.html，报告加载期错误、每屏能不能画出来、每屏有没有 JS 异常。
# 这不是替代 e2e，是重构期间「改完一眼看它炸没炸」的那一步。
# 跑法：PYTHONIOENCODING=utf-8 python test/smoke.py
import pathlib
import sys
import traceback

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

SCREENS = ["today", "yi", "yi-report", "yi-item", "yi-outfit", "wei", "wei-dish", "wei-week",
           "yan", "yan-remind", "pu", "badges", "year", "me", "settings", "search"]

errors = []
checks = []


def check(name, got, want=True):
    ok = (got == want) if want is not True or not isinstance(want, bool) else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
    page.clock.install(time="2026-09-17T10:00:00")
    page.goto(URL)
    page.wait_for_timeout(800)

    check("加载期无 JS 报错", [e for e in errors if "pageerror" in e], [])
    # 注意：`const`/`let` 声明的顶层名不进 window，只在全局词法环境里。
    # 所以这里按标识符直接引用（照 e2e 第 1 节那一段的写法），不要用 window[n] 查。
    globals_ok = page.evaluate(
        "() => [state, boot, show, toast, THEME, logEvent, checkBadges, addWish, addReminder,"
        " addDigest, addMarketItems, searchAll, yearBook, renderHeat, cpw, todayThree, renderToday,"
        " renderPu, renderSettings, renderBadges, renderYear, renderSearch, rescheduleAll]"
        ".every(x => x !== undefined && x !== null)")
    check("新增全局都在", globals_ok, True)

    # 开机要真的去重排提醒。
    #
    # 这一条防的是「定义了但没人调」：rescheduleAll() 曾经全仓零调用点，
    # 于是「开机把没办完的提醒重新排一遍」这句注释描述的事从来没发生过——
    # 重装之后、系统清过队列之后，那些没到点的提醒一条都不会响，
    # 而「我明明设了提醒它没响」是这个功能最伤人的失败方式。
    # 浏览器里 notifyPlugin() 是 null、函数本身是空操作，但**调用这一下**必须发生：
    # 打一个桩数它有没有被调，比去看代码里有没有那句调用可靠得多。
    # 打桩的位置要选对：`rescheduleAll` 是函数声明，挂在全局词法环境里，
    # 重赋值改不动 boot() 里那句调用（它按标识符取到的还是原来那个）。
    # 所以去数它**内部**那一句 `catchUpRepeats()` 跑了几次——两者一一对应，
    # 而 catchUpRepeats 只在 rescheduleAll 与「进提醒总览」两处被调，
    # 这一趟 boot() 里不该有第二处。顺带把 notifyPlugin 也换掉，
    # 因为浏览器里它返回 null、真正的 rescheduleAll 会在第一行就 return。
    # 注意 boot() 是 async：它在 `await restoreNativeBackup()` 那一行让出，
    # 所以**必须 await**，不能同步读计数（第一版就是这么假红的）。
    called = page.evaluate("""async () => {
      let n = 0;
      const realCatch = catchUpRepeats;
      const realNotify = notifyPlugin;
      catchUpRepeats = () => { n++; return 0; };
      notifyPlugin = () => ({});
      try { await boot(); } catch (e) { /* boot 会重画界面，报错不影响这条计数 */ }
      catchUpRepeats = realCatch;
      notifyPlugin = realNotify;
      return n;
    }""")
    check("boot() 真的会调 rescheduleAll（不是「定义了但没人调」）", called >= 1, True)

    # 打字打了一半就把页面切走/关掉，那一下不许丢。
    # saveSoon() 合并的是 600ms 内的连续改动，而用户不会等定时器响：
    # 实测「打一句、100ms 后关掉」重开是空的（一个字节都没落盘）。
    # 这里模拟同一件事：改 state → saveSoon → 100ms 后触发 visibilitychange(hidden)。
    flushed = page.evaluate("""async () => {
      state.yanText = '打在防抖窗口里的这一句';
      saveSoon();
      await new Promise((r) => setTimeout(r, 100));
      const before = (localStorage.getItem('jian.v1') || '').includes('打在防抖窗口里的这一句');
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      const after = (localStorage.getItem('jian.v1') || '').includes('打在防抖窗口里的这一句');
      return { before, after };
    }""")
    check("页面切走时排队中的那次改动会落盘（600ms 防抖不再吞掉最后一下）",
          flushed["after"], True)
    # 还原，别把这一句留进后面的屏
    page.evaluate("() => { state.yanText = ''; save(state); }")

    # 图片地址是一处外来数据（导入备份 / Preferences 恢复），它会原样拼进 src="…"。
    # cssImg() 以前只判前缀，`https://a.example/x" onerror="alert(1)` 原样放行、
    # 当场断掉属性再注入一个新属性。现在它返回的就是「可以原样放进 src」的值。
    img_safe = page.evaluate("""() => {
      const bad = cssImg('https://a.example/x" onerror="alert(1)');
      return {
        quoted: bad.includes('&quot;'),
        noRawQuote: !bad.includes('"'),
        normal: cssImg('https://a.example/p.jpg'),
        amp: cssImg('https://a.example/p.jpg?a=1&b=2'),
        js: cssImg('javascript:alert(1)'),
      };
    }""")
    check("cssImg 把属性里的引号转掉了（断不开 src=\"…\"）",
          img_safe["quoted"] and img_safe["noRawQuote"], True)
    check("cssImg 对正常地址零影响", img_safe["normal"], "https://a.example/p.jpg")
    check("cssImg 不放过 javascript:", img_safe["js"], "")

    # 进 App
    page.click("#go")
    page.wait_for_timeout(300)

    for sid in SCREENS:
        before = len([e for e in errors if "pageerror" in e])
        try:
            page.evaluate("(id) => show(id)", sid)
            page.wait_for_timeout(140)
            on = page.evaluate("() => { const s = document.querySelector('.screen.on'); return s ? s.id : ''; }")
            check(f"屏 {sid} 能切过去", on, sid)
            after = len([e for e in errors if "pageerror" in e])
            check(f"屏 {sid} 渲染无异常", after - before, 0)
            page.screenshot(path=str(OUT / f"smoke-{sid}.png"), full_page=True)
        except Exception as ex:
            check(f"屏 {sid} 能切过去", f"异常 {ex}", sid)

    # 页签
    for tab in ["pass", "closet", "outfit", "wish"]:
        before = len([e for e in errors if "pageerror" in e])
        page.evaluate("(t) => { show('yi'); setYiTab(t); }", tab)
        page.wait_for_timeout(120)
        check(f"衣笺页签 {tab}", len([e for e in errors if "pageerror" in e]) - before, 0)
        page.screenshot(path=str(OUT / f"smoke-yi-{tab}.png"), full_page=True)
    for tab in ["plan", "cook", "market", "week"]:
        before = len([e for e in errors if "pageerror" in e])
        page.evaluate("(t) => { show('wei'); setWeiTab(t); }", tab)
        page.wait_for_timeout(120)
        check(f"味笺页签 {tab}", len([e for e in errors if "pageerror" in e]) - before, 0)
        page.screenshot(path=str(OUT / f"smoke-wei-{tab}.png"), full_page=True)

    # 交互：加一件愿望 / 一条提醒 / 一句摘录 / 一样买菜
    page.evaluate("() => { show('yi'); setYiTab('wish'); addWish('测试大衣', '899'); }")
    page.wait_for_timeout(120)
    check("愿望单加得进去", page.evaluate("() => state.wish.length"), 1)
    page.evaluate("() => addReminder('测试提醒', Date.now() + 3600000, {from:'manual'})")
    page.wait_for_timeout(120)
    check("提醒加得进去", page.evaluate("() => state.reminders.length"), 1)
    page.evaluate("() => addDigest('今天这句话值得记')")
    page.wait_for_timeout(120)
    check("摘录加得进去", page.evaluate("() => state.digest.length"), 1)
    page.evaluate("() => addMarketItems(['鸡蛋 2 个', '番茄 3 个'], '测试')")
    page.wait_for_timeout(120)
    check("买菜清单加得进去", page.evaluate("() => state.market.length"), 2)
    check("买菜合并同类", page.evaluate("() => { addMarketItems(['鸡蛋 3 个'], '测试'); const m = state.market.find(x => x.name === '鸡蛋'); return m ? m.qty : 'MISS'; }"), "5个")

    # 主题
    page.evaluate("() => THEME.set('theme', 'dark')")
    page.wait_for_timeout(240)
    check("夜里的纸生效", page.evaluate("() => document.documentElement.dataset.theme"), "dark")
    page.screenshot(path=str(OUT / "smoke-dark-yi.png"), full_page=True)
    page.evaluate("() => { show('today'); }")
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "smoke-dark-today.png"), full_page=True)
    page.evaluate("() => THEME.set('theme', 'light')")
    page.wait_for_timeout(200)

    # 今日三件事
    three = page.evaluate("() => todayThree().map(t => t.title)")
    check("今日恰好三件", len(three), 3)
    print("        今日三件：" + " / ".join(three))
    # 三件必须来自三个不同的模块（衣 / 味 / 言 各挑一件）。
    # 原来这里只数了个长度：三条都来自衣笺也照样绿，而「三件事」这件事本身就没了。
    check("今日三件分别来自衣 / 味 / 言三个模块（不是三条同一类）",
          sorted(page.evaluate("() => todayThree().map(t => t.mod)")), ["wei", "yan", "yi"])
    check("今日每一件都说得出「做完之后这行变成什么」（不然点完就消失了）",
          page.evaluate("() => todayThree().every((t) => typeof t.title === 'string' && t.title.length > 0)"), True)

    # 全局搜索。原来写的是 `searchAll('大衣').length >= 0`——长度永远 ≥0，恒真，
    # 它当时想说的「这个函数存在且不抛」应该直接这么断言。
    # 现在验四件真事：返回的是分组形状、搜得到、搜不存在的词真的返回空、
    # 每组都说得清它来自哪一块（不然「搜到」可能只是把什么都倒出来）。
    hit = page.evaluate("() => searchAll('大衣')")
    check("全局搜索返回的是分组形状（title / kind / items 三件都齐）", page.evaluate(
        "() => searchAll('大衣').every((g) => typeof g.title === 'string' && typeof g.kind === 'string' && Array.isArray(g.items))"), True)
    check("全局搜索搜得到「大衣」（至少一组、组里至少一条）",
          len(hit) >= 1 and sum(len(g["items"]) for g in hit) >= 1, True)
    check("搜一个绝不存在的词真的返回空表（不然上一条可能只是永远返回全部）",
          page.evaluate("() => searchAll('zzqqxxttt不存在').length"), 0)
    check("空查询返回空表（不把整库倒出来）", page.evaluate("() => searchAll('').length"), 0)
    check("笺谱能画", page.evaluate("() => { show('pu'); return !!document.querySelector('#puHeat .heat'); }"), True)

    errs = [e for e in errors if "pageerror" in e]
    check("全程无未捕获异常", errs, [])
    if errs:
        for e in errs:
            print("        " + e)

    ctx.close()
    browser.close()

passed = len([c for c in checks if c[0]])
failed = len(checks) - passed
print(f"\n冒烟：{passed} 通过 / {failed} 失败")
sys.exit(1 if failed else 0)
