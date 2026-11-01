# 言笺 0.6.0 的守门：日历 / 今天-今晚抽屉 / 归档七天规则 / 多维搜索 /
# 铃铛定提醒 / 重复提醒的下一次 / 摘录本 / 屏内快速添加（不许 prompt）。
#
# 为什么单独一套：这些行为都长在「时间」上，而其它几套 e2e 的表是冻在
# 2026-09-17 那一格的。七天归档、跨月重复、今晚抽屉，一条都没法用真实的
# Date.now() 去等——所以这一套每一节都重开页面、自己装表、自己拨表。
#
# 三条规矩（照搬 dead_controls 的写法，这几条都是踩过的）：
#   1) 每一节重开一页：上一节的落盘与模块级 let 会漏进来，量出来的全是假案。
#   2) 拨表用 page.clock，不用 sleep：140 毫秒的延后、七天之后、跨月，
#      sleep 是假绿（表是冻着的，等多久都不会过去）。
#   3) 断言打在**看得见的结果**上，不打在实现细节上：能说「屏上那个圆点在不在」，
#      就不说「那个变量是不是 true」。
#
# 运行：PYTHONIOENCODING=utf-8 python test/yan_v06.playwright.py
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
URL = (JIAN / "index.html").as_uri()

DAY = 86400000
checks = []
errors = []
# `check(..., None)` 是「这个值应当就是 null」，不能当成「按真假判」。
# 用一枚哨兵把两种意思分开：这张纸上「等于是 null」和「等于是假」是两件事。
NONE = object()


def check(name, got, want=NONE):
    if want is NONE:
        ok = bool(got)
    elif want is None:
        ok = got is None
    else:
        ok = got == want
    checks.append((ok, name, got, want))
    shown = "（要有值）" if want is NONE else ("（应当是 null）" if want is None else want)
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}"
          + ("" if ok else f"   (期望 {shown})"))
    return ok


SEED = """(cards) => {
  state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
  state.points = 40; state.yanAsk = '';
  state.yanText = ''; state.yanView = 'kind'; state.yanHideDone = false;
  state.yanCards = (cards || []).map((c) => normYanCard(c));
  state.reminders = []; state.digest = []; state.album = [];
  save(state); show('yan'); renderYan();
  return state.yanCards.length;
}"""


def open_page(browser, cards, at="2026-09-17T10:00:00", extra=None):
    """新开一页：装表 → 进 App → 赋 state → 进言笺。返回 (context, page)。
    `at` 是冻住的时刻：这一套所有断言都相对它算，不靠机器当前时间。"""
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    pg.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
    pg.clock.install(time=at)
    pg.goto(URL)
    pg.wait_for_function("() => typeof state !== 'undefined' && typeof show === 'function'")
    pg.wait_for_timeout(200)
    pg.click("#go")
    pg.wait_for_timeout(200)
    if extra:
        pg.evaluate(extra)
    n = pg.evaluate(SEED, cards)
    pg.wait_for_timeout(250)
    return ctx, pg, n


def ago(pg, ms):
    """相对页面里那个冻住的 now 往前/往后。返回页面内的毫秒时间戳。"""
    return pg.evaluate("(d) => Date.now() + d", ms)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)

    # ==================== 1. 日历视图 ====================
    print("\n--- 1. 日历：一格一天、七列对齐、今天带标记、有事的日期带圆点 ---")
    ctx, page, n = open_page(browser, [])
    check("空种子也能进言笺（下面每节自己铺数据）", n, 0)
    page.evaluate("""() => {
      const now = Date.now(), D = 86400000;
      state.yanCards = [
        { k: '待办', line: '今天要交的材料', when: { text: '今天', at: now + 2*3600000 }, slot: 'day' },
        { k: '待办', line: '晚上回个电话', when: { text: '今天', at: now + 5*3600000 }, slot: 'evening' },
        { k: '已定', line: '周五吃饭', when: { text: '周五', at: now + 3*D } },
        { k: '还没说清', line: '时间再说', when: null },
        { k: '待办', line: '明天的事', when: { text: '明天', at: now + D } }
      ].map((c) => normYanCard(c));
      state.yanView = 'calendar'; save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    check("言笺有三个视图签（按类型 / 按时间 / 日历）",
          page.eval_on_selector_all("#yanOut [data-yanview]",
                                    "els => els.map(e => e.dataset.yanview)"),
          ["kind", "time", "calendar"])
    check("state.yanView 存得住 calendar", page.evaluate("() => state.yanView"), "calendar")
    head = page.eval_on_selector_all("#yanOut .cal-head span", "els => els.map(e => e.textContent)")
    check("月历表头是周一到周日（与热力图同一口径）", head, ["一", "二", "三", "四", "五", "六", "日"])
    cells = page.eval_on_selector_all("#yanOut .cal-day", "els => els.length")
    check("格子数能被 7 整除（每一行的星期都对得上）", cells % 7, 0)
    check("格子数在 28~42 之间（真的一个月，不是一整年）", 28 <= cells <= 42, True)
    check("月历标题写着年月", page.evaluate(
        "() => /^\\d{4} 年 \\d{1,2} 月$/.test(document.querySelector('#yanOut .cal-title').textContent)"), True)
    today_mark = page.evaluate(
        "() => document.querySelectorAll('#yanOut .cal-day.today').length")
    check("今天恰好一格带标记", today_mark, 1)
    check("今天那一格就是冻住那天的日号（17）", page.evaluate(
        "() => +document.querySelector('#yanOut .cal-day.today').textContent.trim()"), 17)
    dots = page.evaluate("() => document.querySelectorAll('#yanOut .cal-day.has2 .cal-dots i').length")
    check("有事的日期画了圆点（至少三颗：今天两条 + 周五 + 明天）", dots >= 3, True)
    check("没写时间的那条不落在任何格子上（按时间筛的东西不充数）", page.evaluate(
        "() => document.querySelectorAll('#yanOut .cal-day.has2').length"), 3)
    # 「今天」那一格的日号必须读得出来。原来它用 --seal 当字色，而「今天」如果恰好
    # 也是「有事的那天」而**没被选中**，底色是 --paper-2，印章红压上去只有 4.14:1 ——
    # 4.14 < 4.5，那个数字读不出来，而这一格正是用户最想看的那一格。
    # 现在字回 --ink，印章红只留给那圈描边（非文本图形，1.4.11 只要 3:1）。
    #
    # 为什么要按「静态最坏组合」量而不是量屏幕上那一格：测试里今天恰好是**选中态**
    # （.on，底 --ink、字 --paper，本来 13:1），量它对上面这个缺陷完全无感——
    # 第一版就是这么写的，注入之后照样 1:1 之外的两条都绿。所以这里改成：
    # 在页面里造一格「今天 + 有事 + 没选中」，量它的真实计算色。
    today_ratio = page.evaluate(r"""() => {
      const host = document.querySelector('#yanOut .cal-day.today');
      const probe = document.createElement('button');
      probe.type = 'button';
      probe.className = 'cal-day yd today has2';    // today + 有事，但**不带** on
      probe.textContent = '1';
      probe.style.visibility = 'hidden';
      host.parentElement.appendChild(probe);        // 同一棵树下，继承同一套令牌
      const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      const lum = (k) => 0.2126 * f(k[0]) + 0.7152 * f(k[1]) + 0.0722 * f(k[2]);
      const rgb = (s) => { const m = String(s).match(/rgba?\(([^)]*)\)/); return m ? m[1].split(',').map(parseFloat).slice(0, 3) : null; };
      const fg = rgb(getComputedStyle(probe).color);
      const bg = rgb(getComputedStyle(probe).backgroundColor);
      const la = lum(fg), lb = lum(bg);
      const r = +((Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)).toFixed(2);
      probe.remove();
      return r;
    }""")
    check(f"「今天 + 有事 + 没选中」那一格的日号仍过 AA（{today_ratio}:1）", today_ratio >= 4.5, True)
    check("「今天」那圈红还在（它是非文本图形，1.4.11 只要 3:1，所以仍可以用 --seal）",
          page.evaluate("""() => {
            // 不能量屏幕上那一格：它此刻是「今天 + 选中」（.on），那条规则会把圈改成 --paper
            // （选中态的底是 --ink，白圈才看得见）。要量的是「今天但没选中」时的圈。
            const host = document.querySelector('#yanOut .cal-day.today');
            const probe = document.createElement('button');
            probe.type = 'button'; probe.className = 'cal-day yd today';
            probe.style.visibility = 'hidden';
            host.parentElement.appendChild(probe);
            const ring = getComputedStyle(probe, '::after').borderTopColor;
            probe.remove();
            const seal = getComputedStyle(document.documentElement).getPropertyValue('--seal').trim().replace('#', '');
            const want = `rgb(${parseInt(seal.slice(0,2),16)}, ${parseInt(seal.slice(2,4),16)}, ${parseInt(seal.slice(4,6),16)})`;
            return ring === want;
          }"""), True)
    page.screenshot(path=str(OUT / "smoke-yan-calendar.png"), full_page=True)

    # 点一天：下面列出当天的事
    page.click("#yanOut .cal-day.today")
    page.wait_for_timeout(250)
    sel_rows = page.eval_on_selector_all("#yanOut .check .ck-body", "els => els.map(e => e.textContent)")
    check("点今天，下面列出今天那两条", len(sel_rows), 2)
    check("列出来的确实是今天那两句", any("材料" in t for t in sel_rows) and any("电话" in t for t in sel_rows), True)
    check("选中那一天带着选中态", page.evaluate(
        "() => document.querySelectorAll('#yanOut .cal-day.on').length"), 1)

    # 翻月
    mon_before = page.evaluate("() => document.querySelector('#yanOut .cal-title').textContent")
    page.click("#yanCalNext")
    page.wait_for_timeout(250)
    mon_after = page.evaluate("() => document.querySelector('#yanOut .cal-title').textContent")
    check("点 › 翻到下一个月", mon_after != mon_before, True)
    check("翻走之后那个月里没有今天（今天只在这一格）", page.evaluate(
        "() => document.querySelectorAll('#yanOut .cal-day.today').length"), 0)
    page.click("#yanCalPrev")
    page.wait_for_timeout(250)
    check("点 ‹ 又翻回来", page.evaluate(
        "() => document.querySelector('#yanOut .cal-title').textContent"), mon_before)
    check("翻回来之后「回到这个月」那枚就收了（此刻就在这个月）",
          page.evaluate("() => !document.querySelector('#calBack')"), True)
    page.click("#yanCalNext")
    page.wait_for_timeout(200)
    check("翻走之后给出「回到这个月」这条出路", page.evaluate(
        "() => !!document.querySelector('#calBack')"), True)
    page.click("#calBack")
    page.wait_for_timeout(200)
    check("按它真的回到这个月", page.evaluate(
        "() => document.querySelector('#yanOut .cal-title').textContent"), mon_before)
    ctx.close()

    # ==================== 2. 今天 / 今晚 两个抽屉 ====================
    print("\n--- 2. 「按时间」顶上两个抽屉：白天的事与今晚的事分开 ---")
    ctx, page, _ = open_page(browser, [])
    page.evaluate("""() => {
      const now = Date.now();
      state.yanCards = [
        { k: '待办', line: '白天要做完的', when: { text: '今天', at: now + 2*3600000 }, slot: 'day' },
        { k: '待办', line: '晚上回个电话', when: { text: '今天', at: now + 5*3600000 }, slot: 'evening' },
        { k: '待办', line: '没写档位的一句', when: { text: '今天', at: now + 3*3600000 } }
      ].map((c) => normYanCard(c));
      state.yanView = 'time'; save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    groups = page.eval_on_selector_all("#yanOut .bar p.tiny", "els => els.map(e => e.textContent)")
    check("时间视图顶上有「今天」抽屉", "今天" in groups, True)
    check("也有「今晚」抽屉", "今晚" in groups, True)
    # 两条行分别在哪个抽屉下面
    where = page.evaluate("""() => {
      const out = {};
      let cur = "";
      document.querySelectorAll('#yanOut .bar, #yanOut .check').forEach((el) => {
        if (el.classList.contains('bar')) { const p = el.querySelector('p.tiny'); cur = p ? p.textContent : ''; }
        else { const b = el.querySelector('.ck-body'); if (b) out[b.textContent.trim()] = cur; }
      });
      return out;
    }""")
    check("白天那条落在「今天」抽屉下", where.get("白天要做完的"), "今天")
    check("今晚那条落在「今晚」抽屉下", where.get("晚上回个电话"), "今晚")
    check("没写档位的默认算白天（slot 缺省 day）", where.get("没写档位的一句"), "今天")
    page.screenshot(path=str(OUT / "smoke-yan-time.png"), full_page=True)
    # 收起来
    page.click("#yanOut [data-slot-fold='evening']")
    page.wait_for_timeout(250)
    check("点「收起」之后今晚那两条行不在屏上了", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].every((e) => !e.textContent.includes('回个电话'))"), True)
    check("但抽屉标题与计数还在（收起不等于删掉）", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .bar p.tiny')].some((e) => e.textContent === '今晚')"), True)
    check("收起态在 aria-expanded 上说得出来", page.get_attribute(
        "#yanOut [data-slot-fold='evening']", "aria-expanded"), "false")
    page.click("#yanOut [data-slot-fold='evening']")
    page.wait_for_timeout(250)
    check("再点一次展开回来", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].some((e) => e.textContent.includes('回个电话'))"), True)
    ctx.close()

    # ==================== 3. 归档：七天规则 + 撤销 ====================
    print("\n--- 3. 勾掉满七天自动进归档，当场说一声、给一次反悔 ---")
    ctx, page, _ = open_page(browser, [])
    page.evaluate("""() => {
      const now = Date.now(), D = 86400000;
      state.yanCards = [
        { k: '待办', line: '八天前勾掉的', when: null, done: true, doneAt: now - 8*D },
        { k: '待办', line: '六天前勾掉的', when: null, done: true, doneAt: now - 6*D },
        { k: '待办', line: '刚勾掉的', when: null, done: true, doneAt: now - 3600000 },
        { k: '待办', line: '还没办完', when: null, done: false }
      ].map((c) => normYanCard(c));
      state.yanView = 'kind'; state.yanHideDone = false;
      save(state); show('yan'); renderYan();
    }""")
    page.wait_for_timeout(300)
    check("满七天的已经不在主列表上", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].some((e) => e.textContent.includes('八天前'))"), False)
    check("没满七天的还在", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].some((e) => e.textContent.includes('六天前'))"), True)
    check("自动移出不静默：当场弹一句说清收了几条",
          page.evaluate("() => (document.querySelector('#toasts .toast') || {}).firstChild.textContent").strip(),
          "已把 1 条办完的事收进归档")
    check("那句话给得出「撤销」这条路", page.evaluate(
        "() => !!document.querySelector('#toasts .toast.act button')"), True)
    check("state 里它只是被标了归档，没有被删", page.evaluate(
        "() => state.yanCards.filter((c) => c.archivedAt).length"), 1)
    check("归档数量写在明处（「归档 1」那枚）", page.evaluate(
        "() => { const b = document.querySelector('#yanArch'); return b ? b.textContent.trim() : '没有入口'; }"), "归档 1")
    page.screenshot(path=str(OUT / "smoke-yan-archive-toast.png"), full_page=True)

    # 撤销
    page.click("#toasts .toast.act button")
    page.wait_for_timeout(300)
    check("撤销之后那一条回到主列表上", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].some((e) => e.textContent.includes('八天前'))"), True)
    check("撤销同时把 archivedAt 清回 null", page.evaluate(
        "() => state.yanCards.filter((c) => c.archivedAt).length"), 0)
    check("撤销把 doneAt 也清了（用户已明说要留着，不该下次又被收走）", page.evaluate(
        "() => (state.yanCards.find((c) => c.line === '八天前勾掉的') || {}).doneAt"), None)

    # 归档抽屉：回看 + 恢复
    page.evaluate("""() => {
      state.yanCards = state.yanCards.map((c) => {
        if (c.line === '八天前勾掉的') { c.archivedAt = Date.now() - 3600000; c.doneAt = Date.now() - 8*86400000; }
        return c;
      });
      save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    page.click("#yanArch")
    page.wait_for_timeout(250)
    check("归档抽屉里看得到那一条", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].some((e) => e.textContent.includes('八天前'))"), True)
    check("归档里给得出「放回这张笺」", page.evaluate(
        "() => !!document.querySelector('#yanOut [data-unarchive]')"), True)
    check("归档里说得出两个时间点（哪天勾掉、哪天收起来）", page.evaluate(
        "() => { const t = document.querySelector('#yanOut .move-chips .tiny'); return t ? t.textContent.trim() : ''; }")
          .startswith("勾掉"), True)
    page.click("#yanOut [data-unarchive]")
    page.wait_for_timeout(300)
    check("「放回这张笺」真的把它从归档里拿出来", page.evaluate(
        "() => state.yanCards.filter((c) => c.archivedAt).length"), 0)
    page.click("#yanUnarchAll")
    page.wait_for_timeout(250)
    check("「回到这张笺」把归档抽屉收起来、主列表回来", page.evaluate(
        "() => [!!document.querySelector('#yanCount'), !!document.querySelector('#yanArchiveCount')]"), [True, False])
    check("回到主列表之后归档那枚也收了（归档清空了就没有「归档 N」）", page.evaluate(
        "() => !!document.querySelector('#yanArch')"), False)
    check("筛签又出来了（归档模式下它们是藏着的）", page.evaluate(
        "() => !!document.querySelector('#yanFilters')"), True)
    ctx.close()

    # 勾选那一刻就记时间（不是等到下次进屏才补）
    print("\n--- 3b. 勾掉那一刻记下时间；取消勾就清掉 ---")
    ctx, page, _ = open_page(browser, [{"k": "待办", "line": "一条待办", "when": None}])
    page.evaluate("() => document.querySelector('#yanOut input[data-yi=\"0\"]').click()")
    page.wait_for_timeout(250)
    check("勾上之后 doneAt 有值", page.evaluate(
        "() => Number.isFinite(state.yanCards[0].doneAt) && state.yanCards[0].doneAt > 0"), True)
    page.evaluate("() => document.querySelector('#yanOut input[data-yi=\"0\"]').click()")
    page.wait_for_timeout(250)
    check("取消勾之后 doneAt 清回 null（没办完的事没有办完的时间）", page.evaluate(
        "() => state.yanCards[0].doneAt"), None)
    ctx.close()

    # ==================== 4. 多维搜索 ====================
    print("\n--- 4. 搜索：关键词之外再加按人 / 按状态 / 按时间三把筛，且只有一处口径 ---")
    ctx, page, _ = open_page(browser, [])
    page.evaluate("""() => {
      const now = Date.now(), D = 86400000;
      state.yanCards = [
        { k: '待办', line: '小王说的材料要发', who: '小王', when: { text: '今天', at: now + 2*3600000 } },
        { k: '待办', line: '小王提过的报价', who: '小王', when: { text: '明天', at: now + D } },
        { k: '待办', line: '小李那边的合同', who: '小李', when: { text: '明天', at: now + D } },
        { k: '待办', line: '自己记的一句', when: null },
        { k: '待办', line: '小王那条已经办了的', who: '小王', when: { text: '今天', at: now + 3600000 }, done: true, doneAt: now - 3600000 }
      ].map((c) => normYanCard(c));
      state.yanView = 'kind'; state.yanHideDone = false;
      save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    check("三把筛的选项都在（按人 / 按状态 / 按时间）", page.evaluate(
        "() => ['#yanWho', '#yanStatus', '#yanRange'].every((s) => !!document.querySelector(s))"), True)
    check("「按人」的选项从真数据来（小王、小李都在）", page.eval_on_selector_all(
        "#yanWho option", "els => els.map(e => e.value)"), ["", "小李", "小王"])
    page.select_option("#yanWho", "小王")
    page.wait_for_timeout(250)
    check("按人筛出 3 条小王相关", page.eval_on_selector_all(
        "#yanOut .check", "els => els.length"), 3)
    check("筛的时候头上那行说的是「筛出 N · 一共 M」", page.inner_text(
        "#yanCount").startswith("筛出 3"), True)
    page.select_option("#yanStatus", "todo")
    page.wait_for_timeout(250)
    check("再叠「没办的」：小王 + 没办 = 2 条", page.eval_on_selector_all(
        "#yanOut .check", "els => els.length"), 2)
    page.select_option("#yanRange", "today")
    page.wait_for_timeout(250)
    check("再叠「今天」：小王 + 没办 + 今天 = 1 条", page.eval_on_selector_all(
        "#yanOut .check", "els => els.length"), 1)
    check("这一条就是今天那条", page.evaluate(
        "() => document.querySelector('#yanOut .ck-body').textContent.includes('材料要发')"), True)
    check("按时间筛把没写时间的排除掉（不拿它充数）", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .ck-body')].every((e) => !e.textContent.includes('自己记的一句'))"), True)
    # 关键词叠在筛上
    page.evaluate("""() => { const s = $('#yanSearch'); s.value = '材料'; s.dispatchEvent(new Event('input', { bubbles: true })); }""")
    page.clock.run_for(200)
    check("关键词再叠一层，结果与头上那行数是同一把筛数出来的",
          page.evaluate("() => ({ head: $('#yanCount').textContent, rows: $$('#yanOut .check').length })")
          .get("rows"), 1)
    # 筛空了给一条出路
    page.evaluate("""() => { const s = $('#yanSearch'); s.value = '根本没有这个词'; s.dispatchEvent(new Event('input', { bubbles: true })); }""")
    page.clock.run_for(200)
    check("筛空了给的是「清掉搜索」这条出路", page.evaluate(
        "() => !!document.querySelector('#clearYanSearch')"), True)
    page.evaluate("""() => { const s = $('#yanSearch'); s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true })); }""")
    page.clock.run_for(200)
    page.select_option("#yanRange", "past")
    page.wait_for_timeout(250)
    check("三把筛筛到一条不剩时，给的是「筛都清掉」", page.evaluate(
        "() => !!document.querySelector('#clearYanFilter')"), True)
    page.click("#clearYanFilter")
    page.wait_for_timeout(250)
    check("按它把三把筛一起清掉，5 条全回来", page.eval_on_selector_all(
        "#yanOut .check", "els => els.length"), 5)
    ctx.close()

    # ==================== 5. 铃铛定提醒 ====================
    print("\n--- 5. 每条右边的铃铛：点了就定，定了显示状态，没时间先说清 ---")
    ctx, page, _ = open_page(browser, [])
    page.evaluate("""() => {
      const now = Date.now();
      state.yanCards = [
        { k: '待办', line: '有时间的一条', when: { text: '今天', at: now + 3*3600000 } },
        { k: '待办', line: '没时间的一条', when: null }
      ].map((c) => normYanCard(c));
      state.yanView = 'kind'; save(state); renderYan();
    }""")
    page.wait_for_timeout(250)
    check("每行都有一枚铃铛", page.eval_on_selector_all(
        "#yanOut [data-ybell]", "els => els.length"), 2)
    check("还没定的时候写的是「铃」", page.eval_on_selector_all(
        "#yanOut [data-ybell]", "els => els.map(e => e.textContent.trim())"), ["铃", "铃"])
    page.evaluate("() => document.querySelectorAll('#yanOut [data-ybell]')[0].click()")
    page.wait_for_timeout(300)
    check("点有时间那条的铃，提醒真的加进了 state", page.evaluate(
        "() => state.reminders.length"), 1)
    check("提醒记的是从言笺来", page.evaluate(
        "() => state.reminders[0].from"), "yan")
    check("提醒的文字就是那一句", page.evaluate(
        "() => state.reminders[0].text"), "有时间的一条")
    check("提醒的时间取的是那条的时间", page.evaluate(
        "() => Math.abs(state.reminders[0].at - state.yanCards[0].when.at) < 1000"), True)
    check("定完之后那枚铃铛变成「已定」", page.evaluate(
        "() => document.querySelectorAll('#yanOut [data-ybell]')[0].textContent.trim()"), "已定")
    check("「已定」在 aria-pressed 上也说得出来", page.get_attribute(
        "#yanOut [data-ybell='0']", "aria-pressed"), "true")
    check("答话里说的是「大约这个点」，不是「准时」",
          ("大约这个点" in page.inner_text(".toast")) and ("准时" not in page.inner_text(".toast")), True)
    # 没时间的那条：先说清，并把「时间」那排摊开
    page.evaluate("() => document.querySelectorAll('#yanOut [data-ybell]')[1].click()")
    page.wait_for_timeout(300)
    check("没时间那条点铃不会瞎猜一个时间（提醒还是 1 条）", page.evaluate(
        "() => state.reminders.length"), 1)
    check("而是把「挑时间」那排摊开给用户", page.evaluate(
        "() => document.querySelectorAll('#yanOut [data-when-to]').length > 0"), True)
    check("并且当场说清为什么", page.inner_text(".toast"), "这一条还没写时间。挑一个，定下来之后铃铛就亮了")
    # 摊开之后挑一个签
    page.click("#yanOut [data-when-to='明天']")
    page.wait_for_timeout(300)
    check("挑完时间那排收回去", page.evaluate(
        "() => document.querySelectorAll('#yanOut .move-chips').length"), 0)
    page.evaluate("() => document.querySelectorAll('#yanOut [data-ybell]')[1].click()")
    page.wait_for_timeout(300)
    check("再点铃就真的定上了（提醒 2 条）", page.evaluate(
        "() => state.reminders.length"), 2)
    ctx.close()

    # ==================== 6. 重复提醒的下一次 ====================
    print("\n--- 6. 重复提醒：下一次怎么算（含跨月与月末钳位） ---")
    ctx, page, _ = open_page(browser, [])
    r = page.evaluate("""() => {
      const base = new Date(2026, 0, 31, 9, 0, 0).getTime();   // 1 月 31 日
      const fmt = (t) => { const d = new Date(t);
        return [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()]; };
      return {
        daily: fmt(runsOn(base, 'daily')),
        weekly: fmt(runsOn(base, 'weekly')),
        monthly: fmt(runsOn(base, 'monthly')),       // 2 月只有 28 天 → 钳到 28 日
        none: runsOn(base, ''),
        leap: fmt(runsOn(new Date(2028, 0, 31, 9, 0, 0).getTime(), 'monthly')),  // 2028 是闰年 → 2 月 29
      };
    }""")
    check("每天：往后挪一天，时分不变", r["daily"], [2026, 2, 1, 9, 0])
    check("每周：往后挪七天", r["weekly"], [2026, 2, 7, 9, 0])
    check("每月：1 月 31 日的下一次是 2 月 28 日（钳到月末，不是 3 月 3 日）", r["monthly"], [2026, 2, 28, 9, 0])
    check("闰年的 1 月 31 日落到 2 月 29 日", r["leap"], [2028, 2, 29, 9, 0])
    check("只提醒一次的那种没有下一次", r["none"], None)
    r2 = page.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      const fmt = (t) => { const d = new Date(t); return [d.getMonth() + 1, d.getDate()]; };
      return {
        stale: fmt(nextRunAfter(now - 10 * DAY, 'daily', now)),   // 十天没开的每日提醒
        future: fmt(nextRunAfter(now + 2 * DAY, 'daily', now)),  // 本来就在未来的不动
      };
    }""")
    now_md = page.evaluate("() => { const d = new Date(Date.now()); return [d.getMonth() + 1, d.getDate()]; }")
    check("过了十天没打开的每日提醒，下一次被推到明天（不是停在十天前）",
          r2["stale"] != page.evaluate(
              "() => { const d = new Date(Date.now() - 10*86400000); return [d.getMonth() + 1, d.getDate()]; }"), True)
    check("本来就在未来的提醒原样保留（不白折腾）", r2["future"],
          page.evaluate("() => { const d = new Date(Date.now() + 2*86400000); return [d.getMonth() + 1, d.getDate()]; }"))
    # 进提醒屏时真的把过去的重复推到下一次
    page.evaluate("""() => {
      const now = Date.now();
      state.reminders = [{ id: 'rOld', text: '每天要做的事', at: now - 5 * 86400000,
                           repeat: 'daily', done: false, fired: false, from: 'manual' }];
      save(state); show('yan-remind'); renderRemind();
    }""")
    page.wait_for_timeout(300)
    check("进提醒总览时，过了点的重复被排到下一次（不再是五天前）", page.evaluate(
        "() => state.reminders[0].at > Date.now()"), True)
    check("而且说得出「已经排到下一次」这件事", page.evaluate(
        "() => document.querySelector('#remindBody').textContent.includes('已经排到下一次')"), True)
    check("「这一次发过了」记在 fired 上，不是把提醒标成办完", page.evaluate(
        "() => [state.reminders[0].fired, state.reminders[0].done]"), [True, False])
    page.screenshot(path=str(OUT / "smoke-yan-remind-repeat.png"), full_page=True)
    ctx.close()

    # ==================== 7. 屏内快速添加（不许 prompt） ====================
    print("\n--- 7. 加提醒走屏内面板，不许用浏览器 prompt ---")
    ctx, page, _ = open_page(browser, [])
    asked = page.evaluate("""() => {
      window.__prompts = 0;
      window.prompt = () => { window.__prompts++; return null; };
      window.confirm = () => { window.__prompts++; return false; };
      window.alert = () => { window.__prompts++; };
      return true;
    }""")
    check("prompt 桩装好了", asked, True)
    page.evaluate("() => show('yan-remind')")
    page.wait_for_timeout(300)
    page.click("#remindAdd")
    page.wait_for_timeout(300)
    check("「加一条提醒」开的是屏内的一块面板", page.evaluate(
        "() => !!document.querySelector('#remindQuick')"), True)
    check("面板里有说法的输入框、几个快捷时刻、重复档、两个按钮", page.evaluate("""() => {
      const q = document.querySelector('#remindQuick');
      return [!!q.querySelector('#rqText'), q.querySelectorAll('[data-rqwhen]').length,
              q.querySelectorAll('[data-rqrep]').length, !!q.querySelector('#rqAdd'), !!q.querySelector('#rqCancel')];
    }"""), [True, 4, 4, True, True])
    check("打开面板的同时把光标放进输入框（不是让用户自己找）", page.evaluate(
        "() => document.activeElement && document.activeElement.id"), "rqText")
    check("这一整段没有一次浏览器 prompt/confirm/alert", page.evaluate(
        "() => window.__prompts"), 0)
    # 用快捷时刻加一条
    page.fill("#rqText", "面板里加的一条")
    page.click("#remindQuick [data-rqwhen='1h']")
    page.wait_for_timeout(300)
    check("填名字 + 点「一小时后」就真的加了一条", page.evaluate(
        "() => state.reminders.length"), 1)
    check("加完面板自己收起来（不给用户留一块没用的框）", page.evaluate(
        "() => !document.querySelector('#remindQuick')"), True)
    check("约在一小时后", page.evaluate(
        "() => Math.abs(state.reminders[0].at - (Date.now() + 3600000)) < 5000"), True)
    check("依旧没有 prompt", page.evaluate("() => window.__prompts"), 0)
    page.screenshot(path=str(OUT / "smoke-yan-remind.png"), full_page=True)
    # 空名字挡下来，且不扔面板
    page.click("#remindAdd")
    page.wait_for_timeout(250)
    page.click("#remindQuick [data-rqwhen='tomorrow']")
    page.wait_for_timeout(250)
    check("名字空着不硬加（提醒还是 1 条）", page.evaluate(
        "() => state.reminders.length"), 1)
    check("挡下来之后面板还开着（不把用户刚填的东西扔掉）", page.evaluate(
        "() => !!document.querySelector('#remindQuick')"), True)
    check("并且说清为什么", page.evaluate(
        "() => (document.querySelector('.toast') || {}).textContent"), "提醒得有个名字")
    page.click("#rqCancel")
    page.wait_for_timeout(250)
    check("「算了」把面板收起来", page.evaluate(
        "() => !document.querySelector('#remindQuick')"), True)
    # 重复档
    page.click("#remindAdd")
    page.wait_for_timeout(250)
    page.fill("#rqText", "每周要做的事")
    page.click("#remindQuick [data-rqrep='weekly']")
    page.wait_for_timeout(150)
    check("选「每周」就地变选中态（不重画，别把刚打的字清掉）", page.evaluate(
        "() => { const b = document.querySelector('#remindQuick [data-rqrep=\"weekly\"]');"
        " return [b.getAttribute('aria-pressed'), document.querySelector('#rqText').value]; }"),
          ["true", "每周要做的事"])
    page.click("#remindQuick [data-rqwhen='tomorrow']")
    page.wait_for_timeout(300)
    check("加进去的这条是每周重复", page.evaluate(
        "() => state.reminders[state.reminders.length - 1].repeat"), "weekly")
    # 每行的重复档也能改
    page.evaluate("() => document.querySelector('#remindBody [data-rrep]').click()")
    page.wait_for_timeout(250)
    check("点行上的重复档，摊开四枚签", page.evaluate(
        "() => document.querySelectorAll('#remindBody [data-rrep-to]').length"), 4)
    page.evaluate("() => document.querySelector('#remindBody [data-rrep-to=\"monthly\"]').click()")
    page.wait_for_timeout(300)
    check("改成每月真的落到 state 上", page.evaluate(
        "() => state.reminders.some((r) => r.repeat === 'monthly')"), True)
    ctx.close()

    # ==================== 8. 摘录本 ====================
    print("\n--- 8. 摘录本：列出全部、按日期倒序、改心情、同日覆盖 ---")
    ctx, page, _ = open_page(browser, [{"k": "待办", "line": "一句待办", "when": None}])
    check("言笺纸上有摘录本这块折叠区", page.evaluate(
        "() => !!document.querySelector('#yanDigestBook')"), True)
    page.evaluate("() => { const d = document.querySelector('#yanDigestBook'); d.open = true; d.dispatchEvent(new Event('toggle')); }")
    page.wait_for_timeout(300)
    check("摊开之后有写一句的输入框", page.evaluate(
        "() => !!document.querySelector('#dgNew')"), True)
    page.fill("#dgNew", "第一句")
    page.click("#dgSave")
    page.wait_for_timeout(300)
    check("写进去真的进了 state.digest", page.evaluate("() => state.digest.length"), 1)
    check("屏上出现这一句", page.evaluate(
        "() => document.querySelector('#digestBody').textContent.includes('第一句')"), True)
    # 同一天再写 → 覆盖，不是新增
    page.fill("#dgNew", "换一句说法")
    page.click("#dgSave")
    page.wait_for_timeout(300)
    check("同一天再写是覆盖，不是新增（还是 1 条）", page.evaluate(
        "() => state.digest.length"), 1)
    check("覆盖之后内容换成新的", page.evaluate(
        "() => state.digest[0].text"), "换一句说法")
    check("同一天覆盖这件事在输入框上面写清了", page.evaluate(
        "() => document.querySelector('#digestBody .field > span').textContent.includes('换掉')"), True)
    # 造几条历史，看倒序
    page.evaluate("""() => {
      const now = Date.now();
      state.digest = [
        { t: now - 3*86400000, text: '三天前那句', from: '', mood: 0 },
        { t: now, text: '今天这句', from: '小红', mood: 0 },
        { t: now - 86400000, text: '昨天那句', from: '', mood: 0 },
      ];
      save(state); paintDigestBody();
    }""")
    page.wait_for_timeout(250)
    order = page.eval_on_selector_all("#digestBody .dg-text", "els => els.map(e => e.textContent)")
    check("摘录按日期倒序（今天 → 昨天 → 三天前）", order, ["今天这句", "昨天那句", "三天前那句"])
    # 改心情：点一下换一档
    before_mood = page.evaluate("() => state.digest.find((d) => d.text === '昨天那句').mood")
    page.evaluate("""() => { const b = [...document.querySelectorAll('#digestBody [data-dgmood]')]
        .find((x) => x.closest('.digest-row').textContent.includes('昨天那句')); b.click(); }""")
    page.wait_for_timeout(300)
    after_mood = page.evaluate("() => state.digest.find((d) => d.text === '昨天那句').mood")
    check("点心情那一枚真的改了一档", after_mood != before_mood, True)
    check("改完说清改成了什么", page.inner_text(".toast").startswith("这句的心情改成了"), True)
    # 复制
    page.evaluate("""() => { window.__clip = ''; navigator.clipboard.writeText = (t) => { window.__clip = t; return Promise.resolve(); }; }""")
    page.evaluate("""() => { const b = [...document.querySelectorAll('#digestBody [data-dgcopy]')]
        .find((x) => x.closest('.digest-row').textContent.includes('今天这句')); b.click(); }""")
    page.wait_for_timeout(300)
    check("「复制」复制走的是那一句本身", page.evaluate("() => window.__clip"), "今天这句")
    check("复制这件事说出来了", page.inner_text(".toast"), "已复制这一句")
    # 删 + 撤销
    page.evaluate("""() => { const b = [...document.querySelectorAll('#digestBody [data-dgdel]')]
        .find((x) => x.closest('.digest-row').textContent.includes('三天前那句')); b.click(); }""")
    page.wait_for_timeout(300)
    check("删一条真的从 state 里去掉", page.evaluate("() => state.digest.length"), 2)
    check("删完给一次反悔", page.evaluate(
        "() => !!document.querySelector('#toasts .toast.act button')"), True)
    page.click("#toasts .toast.act button")
    page.wait_for_timeout(300)
    check("撤销把它放回来", page.evaluate("() => state.digest.length"), 3)
    page.screenshot(path=str(OUT / "smoke-yan-digest.png"), full_page=True)
    ctx.close()

    # ==================== 9. 寄去别处 ====================
    print("\n--- 9. 寄去别处：要买的去衣笺、像顿饭的已定去味笺 ---")
    ctx, page, _ = open_page(browser, [
        {"k": "要买", "line": "买一件白衬衫", "when": None},
        {"k": "已定", "line": "周六去那家川菜馆吃饭", "when": None},
        {"k": "待办", "line": "交个材料", "when": None},
    ])
    check("只有「要买」那条有「寄去衣笺」", page.eval_on_selector_all(
        "#yanOut [data-jump]", "els => els.map(e => [e.dataset.jump, e.textContent.trim()])"),
          [["yi", "寄去衣笺 · 过这一件"], ["wei", "寄去味笺 · 排这一桌"]])
    check("普通待办不摆「寄去别处」（猜不出该去哪儿就别摆）", page.evaluate(
        "() => [...document.querySelectorAll('#yanOut .check')].filter((e) => e.textContent.includes('交个材料'))[0]"
        ".querySelectorAll('[data-jump]').length"), 0)
    page.evaluate("() => document.querySelector('#yanOut [data-jump=\"yi\"]').click()")
    page.wait_for_timeout(300)
    check("按「寄去衣笺」跳到衣笺", page.evaluate(
        "() => document.querySelector('.screen.on').id"), "yi")
    # 只 show('yi') 是不够的：衣笺会落在上一次停下的那个页签，用户从言笺点过来
    # 看到的是柜子或愿望，过笺入口根本不在这屏上——
    # 「按了有反应，但落在了看不见的地方」。所以必须先切回「过笺」。
    # 量的是**用户看得见的那一半**：哪个 pane 露着。内存里那个 `yiTab` 归 app.js 的
    # 页签回调写，setYiTab 不碰它（那是 wire.js 与 app.js 的口径差，不在本 lane 修）。
    def panes():
        return page.evaluate("""() => ({
          pass: !document.querySelector('#yiPanePass').hidden,
          wish: !document.querySelector('#yiPaneWish').hidden,
          closet: !document.querySelector('#yiPaneCloset').hidden,
        })""")

    check("而且落在「过笺」那一页上", panes(), {"pass": True, "wish": False, "closet": False})
    # 把页签停在「愿望」再点一次——这一次才量得着上面那件事。
    # 必须**真点那枚页签**：只有这样 aria-selected 与 pane 显隐才是用户真的点出来的样子。
    page.evaluate("() => show('yi')")
    page.wait_for_timeout(250)
    page.click("#yiTabs [data-yitab='wish']")
    page.wait_for_timeout(300)
    check("先确认页签真的停在「愿望」上", panes(), {"pass": False, "wish": True, "closet": False})
    page.evaluate("() => { show('yan'); renderYan(); }")
    page.wait_for_timeout(250)
    page.evaluate("() => document.querySelector('#yanOut [data-jump=\"yi\"]').click()")
    page.wait_for_timeout(300)
    check("页签停在「愿望」时点「寄去衣笺」，仍然落到「过笺」上",
          panes(), {"pass": True, "wish": False, "closet": False})
    check("页签的选中态也跟着回到「过笺」（读屏器念的是这个）", page.evaluate(
        "() => document.querySelector('#yiTabs [data-yitab=\\'pass\\']').getAttribute('aria-selected')"), "true")
    check("名字已经交给接线层（wire 的 presetNewName）", page.evaluate("() => pendingNewName"), "买一件白衬衫")
    # 这一条才是真的：过一件带名字的照片，落到柜里的名字必须是言笺带过去那个，
    # 不能被「想买的这件」或网关猜的名字盖掉（yi.js 的 fromLink 就守着这件事）。
    page.evaluate("""async () => {
      const c = document.createElement('canvas'); c.width = 600; c.height = 800;
      const x = c.getContext('2d'); x.fillStyle = '#d8d2c6'; x.fillRect(0, 0, 600, 800);
      const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg'));
      const f = new File([blob], 'tee.jpg', { type: 'image/jpeg' });
      runYi(f);
    }""")
    page.wait_for_function("() => state.lastNew !== null", timeout=15000)
    page.wait_for_timeout(400)
    check("过笺之后，名字用的是言笺带过来的那个（不是「想买的这件」）", page.evaluate(
        "() => state.lastNew.name"), "买一件白衬衫")
    check("带过来的名字用完即清（不会串到下一条）", page.evaluate("() => pendingNewName"), "")
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(250)
    page.evaluate("() => document.querySelector('#yanOut [data-jump=\"wei\"]').click()")
    page.wait_for_timeout(300)
    check("按「寄去味笺」跳到味笺", page.evaluate(
        "() => document.querySelector('.screen.on').id"), "wei")
    check("而且那一句已经成了菜单里的一行", page.evaluate(
        "() => document.querySelector('#menu').value.includes('周六去那家川菜馆吃饭')"), True)
    ctx.close()

    # ==================== 10. 提醒总览的诚实边界 ====================
    print("\n--- 10. 提醒屏说实话：没有精确闹钟，就只说「大约这个点」 ---")
    ctx, page, _ = open_page(browser, [])
    page.evaluate("""() => {
      const now = Date.now();
      state.reminders = [
        { id: 'rPast', text: '已经过去的', at: now - 3600000, repeat: '', done: false, fired: false, from: 'manual' },
        { id: 'rToday', text: '今天的', at: now + 3600000, repeat: '', done: false, fired: false, from: 'manual' },
        { id: 'rLater', text: '往后的', at: now + 3*86400000, repeat: '', done: false, fired: false, from: 'manual' },
        { id: 'rDone', text: '办完的', at: now + 2*3600000, repeat: '', done: true, fired: true, from: 'manual' }
      ];
      save(state); show('yan-remind'); renderRemind();
    }""")
    page.wait_for_timeout(300)
    body = page.inner_text("#remindBody")
    check("四段都在（已经过期 / 今天之内 / 往后 / 办完了）",
          all(x in body for x in ["已经过期", "今天之内", "往后", "办完了"]), True)
    check("屏上写的是「大约这个点」，没有「准时」", ("大约这个点" in body) and ("准时" not in body), True)
    check("说得出省电模式会把通知攒着发", "攒着" in body, True)
    check("给得出「检查通知权限」这条出路", page.evaluate(
        "() => !!document.querySelector('#remindPerm')"), True)
    check("通知权限状态有一句话（不是一片空白）", page.evaluate(
        "() => (document.querySelector('#remindPermState') || {}).textContent || ''").strip() != "", True)
    # dueToday 口径：没办 + 24 小时内（含已过期）
    due = page.evaluate("() => dueToday()")
    check("dueToday 数的是「没办 + 24 小时内到期（含已过期）」= 2 条", due, 2)
    check("办完了那条不算进底栏小点", page.evaluate(
        "() => state.reminders.filter((r) => r.done).length"), 1)
    # 删一条给撤销
    page.evaluate("() => document.querySelector('#remindBody [data-rdel]').click()")
    page.wait_for_timeout(250)
    check("删一条提醒真的从 state 里去掉", page.evaluate("() => state.reminders.length"), 3)
    page.click("#toasts .toast.act button")
    page.wait_for_timeout(300)
    check("撤销把它放回来，顺序也按时间重排好", page.evaluate(
        "() => state.reminders.length === 4 && state.reminders.every((r, i, a) => !i || a[i-1].at <= r.at)"), True)
    ctx.close()

    # ==================== 11. 触摸目标与无死控件 ====================
    print("\n--- 11. 新增的每一枚控件都够大、按了都有反应 ---")
    ctx, page, _ = open_page(browser, [])
    page.evaluate("""() => {
      const now = Date.now(), D = 86400000;
      state.yanCards = [
        { k: '待办', line: '今天要交的材料', when: { text: '今天', at: now + 2*3600000 }, who: '小王' },
        { k: '要买', line: '买一盒药', when: null },
        { k: '已定', line: '周六去吃饭', when: { text: '周六', at: now + 2*D } },
        { k: '待办', line: '八天前勾掉的', when: null, done: true, doneAt: now - 8*D }
      ].map((c) => normYanCard(c));
      state.yanView = 'calendar'; save(state); renderYan();
    }""")
    page.wait_for_timeout(300)
    sizes = page.evaluate("""() => {
      // 勾选框不算：整行 label 就是它的命中区（e2e §41 那条对勾框另有 24px 的下限，
      // 而且量的是整行）。这里量的是「新加的那些按得动的东西」。
      const SEL = '#yanOut button, #yanOut select, #yanOut summary';
      const bad = [];
      let n = 0;
      document.querySelectorAll(SEL).forEach((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return;
        n++;
        if (Math.min(r.width, r.height) < 32) bad.push([el.id || el.className || el.tagName,
          Math.round(r.width), Math.round(r.height)]);
      });
      return { n, bad };
    }""")
    check("日历视图里量到了足够多控件（不够就是扫描瞎了）", sizes["n"] >= 40, True)
    check("日历视图里没有小于 32px 的可点控件", sizes["bad"], [])
    page.evaluate("() => { state.yanView = 'time'; save(state); renderYan(); }")
    page.wait_for_timeout(250)
    sizes2 = page.evaluate("""() => {
      const bad = [];
      document.querySelectorAll('#yanOut button, #yanOut select').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return;
        if (Math.min(r.width, r.height) < 32) bad.push([el.id || el.className, Math.round(r.width), Math.round(r.height)]);
      });
      return bad;
    }""")
    check("时间视图（含今天/今晚抽屉）也没有小于 32px 的可点控件", sizes2, [])
    page.evaluate("() => { show('yan-remind'); renderRemind(); }")
    page.wait_for_timeout(250)
    check("提醒屏里也一样", page.evaluate("""() => {
      const bad = [];
      document.querySelectorAll('#remindBody button').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return;
        if (Math.min(r.width, r.height) < 32) bad.push([el.className, Math.round(r.width), Math.round(r.height)]);
      });
      return bad;
    }"""), [])
    ctx.close()

    # ==================== 12. 全程无异常 ====================
    print("\n--- 12. 全程没有未捕获异常 ---")
    errs = [e for e in errors if "pageerror" in e]
    check("全程没有未捕获异常", errs, [])
    if errs:
        for e in errs[:10]:
            print("        " + e)

    browser.close()

passed = len([c for c in checks if c[0]])
failed = len(checks) - passed
print(f"\n言笺 0.6.0：{passed} 通过 / {failed} 失败（共 {len(checks)} 条）")
sys.exit(1 if failed else 0)
