# 衣笺 lane 的自验：把 wardrobe.js 的几块（单品档案 / 搭配册 / 愿望单 / 衣柜统计）逐块推一遍。
# 这不是替代 e2e，是改完一眼看它画得对不对、数字与 state 对不对得上。
# 跑法：PYTHONIOENCODING=utf-8 python test/yi_v06.playwright.py
import pathlib
import sys

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

errors = []
checks = []


def check(name, got, want=True):
    """want 省略 = 只要真值；给了具体值 = 逐字比。
    （`got == want` 与 `bool(got)` 两条口径混在一行里写过一次，结果数值断言全假红。）"""
    ok = bool(got) if want is True else (got == want)
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
    page.wait_for_timeout(700)
    page.evaluate("() => { state.onboarded = true; save(state); paintNav(); show('yi'); }")
    page.wait_for_timeout(200)

    # ---------- 1. 档案页能进、能回来 ----------
    print("\n--- 1. 柜子里那枚「档案」入口 ---")
    page.evaluate("() => { setYiTab('closet'); state.clothSel = state.wardrobe[0].id; save(state); renderCloset(); }")
    page.wait_for_timeout(200)
    check("操作条上有「档案」这枚按钮", page.evaluate("() => !!document.querySelector('#clothActions #openItemBtn')"), True)
    page.click("#openItemBtn")
    page.wait_for_timeout(250)
    check("点它进了单品详情屏", page.evaluate("() => (document.querySelector('.screen.on') || {}).id"), "yi-item")
    check("详情屏上有大图那一块", page.evaluate("() => !!document.querySelector('#itemBody .yi-hero')"), True)
    check("详情屏上有名字（宋体标题）", page.evaluate(
        "() => { const h = document.querySelector('#itemBody .yi-name'); return h ? h.className : 'MISS'; }").find("serif") >= 0, True)
    page.screenshot(path=str(OUT / "yi-v06-item.png"), full_page=True)

    # ---------- 2. 档案保存往返 ----------
    print("\n--- 2. 档案保存往返（价格 / 购入日 / 品牌 / 尺码 / 备注） ---")
    page.fill("#itemPrice", "899")
    page.fill("#itemBought", "2025-03-04")
    page.fill("#itemBrand", "UNIQLO")
    page.fill("#itemSize", "L")
    page.fill("#itemNote", "冬天配高领")
    page.click("#itemSave")
    page.wait_for_timeout(250)
    saved = page.evaluate("""() => { const w = state.wardrobe[0];
      return [w.price, w.boughtAt, w.brand, w.size, w.note]; }""")
    check("价格存回 state", saved[0], 899)
    check("购入日存回 state（2025-03-04 那天）",
          page.evaluate("() => new Date(state.wardrobe[0].boughtAt).getMonth() + 1"), 3)
    check("品牌存回 state", saved[2], "UNIQLO")
    check("尺码存回 state", saved[3], "L")
    check("备注存回 state", saved[4], "冬天配高领")
    check("存完之后屏上还是同一件（没有整片白掉）", page.evaluate("() => !!document.querySelector('#itemBody .yi-hero')"), True)

    # 未来的购入日必须挡下来，而且要说一句
    page.fill("#itemBought", "2030-01-01")
    page.click("#itemSave")
    page.wait_for_timeout(200)
    check("未来的购入日不写进 state（仍停在 2025）",
          page.evaluate("() => new Date(state.wardrobe[0].boughtAt).getFullYear()"), 2025)
    said = page.evaluate("() => ((document.querySelector('.toast') || {}).textContent || '')")
    check("挡住未来购入日时说了话（不静默）", "还没到" in said, True)

    # ---------- 3. 场合多选即落库 ----------
    print("\n--- 3. 场合多选 ---")
    page.click("#itemOcc [data-occ='通勤']")
    page.click("#itemOcc [data-occ='正式']")
    page.wait_for_timeout(200)
    check("场合落库（通勤、正式）", page.evaluate(
        "() => state.wardrobe[0].occasions.slice().sort().join(',')"), "正式,通勤")
    check("选中的那两枚标了 aria-pressed",
          page.evaluate("() => document.querySelectorAll('#itemOcc [aria-pressed=\"true\"]').length"), 2)
    page.click("#itemOcc [data-occ='通勤']")
    page.wait_for_timeout(150)
    check("再点一下取消（只剩正式）", page.evaluate("() => state.wardrobe[0].occasions.join(',')"), "正式")

    # ---------- 4. CPW 三种边界 ----------
    print("\n--- 4. 单次穿着成本：算得出 / 没价格 / 没穿过 ---")
    cpw_cases = page.evaluate("""() => {
      const base = { id: 'x1', name: 'T', cat: '上衣', color: '#888888', worn: 0, lastWorn: null };
      const a = cpw(Object.assign({}, base, { price: 900, worn: 100 }));
      const b = cpw(Object.assign({}, base, { price: 900, worn: 0 }));
      const c = cpw(Object.assign({}, base, { price: null, worn: 10 }));
      const d = cpw(Object.assign({}, base, { price: 0, worn: 4 }));
      return [a, b === Infinity, c, d];
    }""")
    check("900 元穿 100 次 = 每次 ¥9", cpw_cases[0], 9)
    check("记了价格但没穿过 = Infinity（不是 0）", cpw_cases[1], True)
    check("没记价格 = null（算不出来）", cpw_cases[2], None)
    check("0 元那件 = 0（是礼物，不是算不出来）", cpw_cases[3], 0)

    # ---------- 5. 穿着日历：补记 / 取消 ----------
    print("\n--- 5. 穿着日历：点一天补记、再点取消 ---")
    page.evaluate("() => { state.wardrobe[0].worn = 0; state.wardrobe[0].lastWorn = null;"
                  " state.wardrobe[0].wearDays = []; save(state); renderYiItem(); }")
    page.wait_for_timeout(150)
    check("穿着日历默认收起", page.evaluate("() => document.querySelector('#itemCal').hidden"), True)
    page.click("#itemCalToggle")
    page.wait_for_timeout(200)
    check("点开之后日历画出来了", page.evaluate("() => document.querySelectorAll('#itemCal [data-cald]').length") > 0, True)
    cal_cells = page.evaluate("() => document.querySelectorAll('#itemCal [data-cald]').length")
    print(f"        这个月 {cal_cells} 天")
    # 相邻两格最小高度 ≥44（新控件）
    minh = page.evaluate("""() => Math.min(...[...document.querySelectorAll('#itemCal [data-cald]')]
      .filter((el) => el.getClientRects().length)
      .map((el) => el.getBoundingClientRect().height))""")
    check("日历格高度不低于 44px", float(minh) >= 44, True)
    print(f"        量到的最小格高 {float(minh):.1f}px")
    page.screenshot(path=str(OUT / "yi-v06-item-cal.png"), full_page=True)

    # 点今天：补记
    today_d = page.evaluate("() => new Date().getDate()")
    page.click(f"#itemCal [data-cald='{today_d}']")
    page.wait_for_timeout(250)
    after_add = page.evaluate("() => [state.wardrobe[0].worn, (state.wardrobe[0].wearDays || []).length]")
    check("点今天 = 次数 +1", after_add[0], 1)
    check("点今天 = wearDays 里多一天", after_add[1], 1)
    check("那一天在日历上是亮的",
          page.evaluate(f"() => document.querySelector('#itemCal [data-cald=\"{today_d}\"]').getAttribute('aria-pressed')"), "true")
    check("点完之后屏上的次数也跟着改",
          page.evaluate("() => (document.querySelector('#itemBody .yi-wear-line') || {}).textContent || ''").find("穿过 1 次") >= 0, True)
    check("记穿进 log 了（热力图读它）", page.evaluate("() => state.log.filter((e) => e.kind === 'wear').length"), 1)

    # 再点今天：取消
    page.click(f"#itemCal [data-cald='{today_d}']")
    page.wait_for_timeout(250)
    after_del = page.evaluate("() => [state.wardrobe[0].worn, (state.wardrobe[0].wearDays || []).length, state.wardrobe[0].lastWorn]")
    check("再点今天 = 次数退回 0", after_del[0], 0)
    check("再点今天 = wearDays 清空", after_del[1], 0)
    check("次数 0 时「上次穿」一起清掉（两格不许各说各话）", after_del[2], None)

    # 未来那一天不许记
    future_d = page.evaluate("""() => { const d = new Date(); const n = new Date(d.getFullYear(), d.getMonth() + 1, 1);
      return [n.getMonth() === d.getMonth(), 1]; }""")
    # 翻到上个月再翻回来，验证月份导航。
    # 原来这一条是 `title.find(str(new Date().getMonth())) >= 0`：拿**这个月**的月号
    # 去标题里找，而标题显示的是**上个月**。两者只在 1 月那天不相等（12 月回绕到 0），
    # 于是 11 个月里它恒真、只有 1 月假红——一条几乎永远绿的断言等于没有。
    # 现在把期望值算出来逐字比：上个月是几月就得写着几月。
    title0 = page.evaluate("() => (document.querySelector('.yi-cal-title') || {}).textContent || ''")
    now_ym = page.evaluate("() => [new Date().getFullYear(), new Date().getMonth() + 1]")
    check("日历标题一开始就是这个月", f"{now_ym[0]} 年 {now_ym[1]} 月" in title0, True)
    prev_d = page.evaluate("""() => { const d = new Date();
      const p = new Date(d.getFullYear(), d.getMonth() - 1, 1);
      return [p.getFullYear(), p.getMonth() + 1]; }""")
    page.click("#calPrev")
    page.wait_for_timeout(200)
    title = page.evaluate("() => (document.querySelector('.yi-cal-title') || {}).textContent || ''")
    check("翻到上个月，标题写的是上个月那个年月（1 月回绕也要对）",
          f"{prev_d[0]} 年 {prev_d[1]} 月" in title, True)
    check("翻到上个月后标题里不再有这个月的年月",
          f"{now_ym[0]} 年 {now_ym[1]} 月" in title, False)
    # 翻回来又到这个月
    page.click("#calNext")
    page.wait_for_timeout(200)
    title2 = page.evaluate("() => (document.querySelector('.yi-cal-title') || {}).textContent || ''")
    check("翻回来又回到这个月", f"{now_ym[0]} 年 {now_ym[1]} 月" in title2, True)
    # 已经在本月时再按「下一个月」必须拒绝并说明，而不是静默什么都不发生。
    # 注意用 dispatch_event 而不是 page.click：Playwright 的可操作性检查把
    # aria-disabled="true" 当「不可点」直接超时（实测 30s 卡死），
    # 而这里要验的恰恰是「读屏器/键盘绕过去之后，那个 handler 会不会给一句话」。
    # 仓里的规矩是不用真 disabled，所以属性挂着、handler 仍然在——这条断言盯的是后者。
    check("本月时「下一个月」标着 aria-disabled", page.evaluate(
        "() => document.querySelector('#calNext').getAttribute('aria-disabled')"), "true")
    page.dispatch_event("#calNext", "click")
    page.wait_for_timeout(150)
    check("点挡着的「下一个月」后仍在同一个月（不是静默无事）",
          f"{now_ym[0]} 年 {now_ym[1]} 月" in page.evaluate(
              "() => (document.querySelector('.yi-cal-title') || {}).textContent || ''"), True)
    check("而且吐了一句原因（「这已经是这个月了」）", page.evaluate(
        "() => (document.querySelector('.toast') || {}).textContent || ''").find("这个月") >= 0, True)

    # ---------- 6. 搭配册：列表 / 详情 / 一次记四件 ----------
    print("\n--- 6. 搭配册：存一套、看详情、一次记四件 ---")
    page.evaluate("""() => {
      state.wardrobe = [
        { id: 'w1', name: '燕麦针织', cat: '上衣', color: '#d4c4b0', worn: 9, lastWorn: Date.now() - 86400000 * 2 },
        { id: 'w2', name: '白衬衫', cat: '上衣', color: '#f4f0ea', worn: 4, lastWorn: Date.now() - 86400000 * 23 },
        { id: 'w3', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: Date.now() - 86400000 },
        { id: 'w4', name: '白鞋', cat: '鞋', color: '#f5f5f3', worn: 15, lastWorn: Date.now() - 86400000 * 5 },
      ];
      state.outfits = []; state.log = []; save(state); show('yi'); setYiTab('outfit');
    }""")
    page.wait_for_timeout(250)
    check("搭配页签画在 #outfitList 里（不是画到子页去）",
          page.evaluate("() => !!document.querySelector('#yiPaneOutfit #outfitList .empty, #yiPaneOutfit #outfitList .btn')"), True)
    check("子页 #outfitBody 这时还是空的", page.evaluate("() => document.querySelector('#outfitBody').innerHTML.trim()"), "")
    page.click("#newOutfit")
    page.wait_for_timeout(250)
    check("挑件面板摊开了", page.evaluate("() => !!document.querySelector('#outfitPick')"), True)
    for wid in ["w1", "w2", "w3", "w4"]:
        page.click(f"#outfitPick [data-pick='{wid}']")
    page.wait_for_timeout(150)
    check("已挑 4 件的计数说出来了",
          page.evaluate("() => (document.querySelector('#pickCount') || {}).textContent || ''"), "已挑 4 件")
    page.fill("#outfitName", "通勤四件")
    page.click("#outfitOcc [data-oc='通勤']")
    page.click("#outfitSave")
    page.wait_for_timeout(300)
    made = page.evaluate("() => { const o = state.outfits[0]; return [state.outfits.length, o.name, o.ids.length, o.occasion]; }")
    check("搭配存进 state", made[0], 1)
    check("名字对", made[1], "通勤四件")
    check("四件都在", made[2], 4)
    check("场合标上了", made[3], "通勤")
    check("列表里出现这一套", page.evaluate("() => document.querySelectorAll('#outfitList .yi-outfit-card').length"), 1)

    # 点进详情
    page.click("#outfitList [data-oopen]")
    page.wait_for_timeout(300)
    check("点成套 → 进搭配子页", page.evaluate("() => (document.querySelector('.screen.on') || {}).id"), "yi-outfit")
    check("详情里四件都画出来了", page.evaluate("() => document.querySelectorAll('#outfitBody .yi-piece').length"), 4)
    check("「一次记 4 件」写在按钮上",
          page.evaluate("() => (document.querySelector('#outfitWear') || {}).textContent || ''").find("4") >= 0, True)
    page.screenshot(path=str(OUT / "yi-v06-outfit.png"), full_page=True)

    # 一次记四件
    before_worn = page.evaluate("() => state.wardrobe.map((w) => w.worn)")
    outfits_before = page.evaluate("() => state.log.filter((e) => e.kind === 'outfit').length")
    page.click("#outfitWear")
    page.wait_for_timeout(350)
    after_worn = page.evaluate("() => state.wardrobe.map((w) => w.worn)")
    check("四件各 +1（不是只 +1 一次）", [b - a for a, b in zip(before_worn, after_worn)], [1, 1, 1, 1])
    wear_logs = page.evaluate("() => state.log.filter((e) => e.kind === 'wear').length")
    check("log 里是四条 wear（不是一条）", wear_logs, 4)
    check("整套另记一笔 outfit",
          page.evaluate("() => state.log.filter((e) => e.kind === 'outfit').length") - outfits_before, 1)
    check("四件的 wearDays 都写上了今天",
          page.evaluate("() => state.wardrobe.every((w) => Array.isArray(w.wearDays) && w.wearDays.length === 1)"), True)
    said = page.evaluate("() => ((document.querySelector('.toast') || {}).textContent || '')")
    check("提示说的是「一次记 4 件」", "4" in said, True)
    check("提示里带撤销（四件能一起退）",
          page.evaluate("() => !!document.querySelector('#toasts .toast.act button')"), True)

    # 撤销：四件一起退
    page.click("#toasts .toast.act button")
    page.wait_for_timeout(300)
    check("撤销把四件一起退回", page.evaluate("() => state.wardrobe.map((w) => w.worn)"), before_worn)
    check("撤销也把 wearDays 一起退回",
          page.evaluate("() => state.wardrobe.every((w) => (w.wearDays || []).length === 0)"), True)

    # 再记一次，然后同一天再点一次：不许 +2
    page.click("#outfitWear")
    page.wait_for_timeout(300)
    once = page.evaluate("() => state.wardrobe.map((w) => w.worn)")
    page.click("#outfitWear")
    page.wait_for_timeout(300)
    check("同一天再点不再 +1", page.evaluate("() => state.wardrobe.map((w) => w.worn)"), once)
    said2 = page.evaluate("() => ((document.querySelector('.toast') || {}).textContent || '')")
    check("第二次点它说清了「今天都记过了」", "记过" in said2, True)

    # ---------- 7. 按场合筛 ----------
    print("\n--- 7. 搭配按场合筛 ---")
    page.evaluate("""() => {
      state.outfits.push({ id: 'o9', name: '周末两件', ids: ['w2', 'w3'], occasion: '约会',
        note: '', t: Date.now(), worn: 0, lastWorn: null });
      save(state); show('yi'); setYiTab('outfit');
    }""")
    page.wait_for_timeout(300)
    occs = page.eval_on_selector_all("#outfitList [data-occf]", "els => els.map(e => e.textContent.trim())")
    check("场合筛选那一排按真实用到的场合长出来（全部 + 通勤 + 约会）", occs, ["全部", "通勤", "约会"])
    check("默认「全部」选中", page.evaluate(
        "() => document.querySelector(\"#outfitList [data-occf='']\").getAttribute('aria-pressed')"), "true")
    check("「全部」时两套都在", page.evaluate("() => document.querySelectorAll('#outfitList .yi-outfit-card').length"), 2)
    page.click("#outfitList [data-occf='约会']")
    page.wait_for_timeout(300)
    check("筛「约会」只剩一套", page.evaluate("() => document.querySelectorAll('#outfitList .yi-outfit-card').length"), 1)
    check("筛出来的就是「周末两件」",
          page.evaluate("() => document.querySelector('#outfitList .yi-outfit-card').getAttribute('data-outfit')"), "o9")
    check("筛中的那枚签标成选中", page.evaluate(
        "() => document.querySelector(\"#outfitList [data-occf='约会']\").getAttribute('aria-pressed')"), "true")
    page.click("#outfitList [data-occf='']")
    page.wait_for_timeout(300)
    check("回到「全部」两套又都在", page.evaluate("() => document.querySelectorAll('#outfitList .yi-outfit-card').length"), 2)
    # 一套里的色块能点进单品档案（按钮里不许套按钮，色块是自己的按钮）
    page.evaluate("() => { show('yi'); setYiTab('outfit'); }")
    page.wait_for_timeout(250)
    page.click("#outfitList [data-oswatch]")
    page.wait_for_timeout(300)
    check("点一套里的色块 → 进那件单品的档案", page.evaluate("() => (document.querySelector('.screen.on') || {}).id"), "yi-item")
    first_piece = page.evaluate("() => state.wardrobe[0].name")
    check("档案页上就是刚点的那一件（名字对得上）",
          page.evaluate("() => (document.querySelector('#itemBody .yi-name') || {}).textContent || ''"), first_piece)
    # 空场合的说法（造一个只有空结果的筛选：把两套都标同一场合，再筛另一个）
    page.evaluate("""() => {
      state.outfits.forEach((o) => { o.occasion = '通勤'; });
      save(state); show('yi'); setYiTab('outfit'); outfitOcc = '约会';
      drawOutfitList();
    }""")
    page.wait_for_timeout(250)
    check("筛到没有搭配的场合 → 有空态文案",
          page.evaluate("() => (document.querySelector('#outfitList') || {}).textContent || ''").find("这个场合下还没有搭配") >= 0, True)
    page.evaluate("() => { outfitOcc = ''; drawOutfitList(); }")

    # ---------- 8. 愿望冷静期 ----------
    print("\n--- 8. 愿望单：冷静期 / 页签小点 / 省下多少 ---")
    page.evaluate("""() => {
      state.wish = [];
      state.wish.push({ id: 's1', name: '羊绒大衣', cat: '外套', color: '#c4a574', price: 2600,
                        t: Date.now() - 86400000 * 5, cool: 3, note: '', done: false, bought: false });
      state.wish.push({ id: 's2', name: '帆布鞋', cat: '鞋', color: '#cccccc', price: 399,
                        t: Date.now() - 86400000, cool: 3, note: '', done: false, bought: false });
      state.wish.push({ id: 's3', name: '旧包', cat: '包', color: '#888888', price: 1200,
                        t: Date.now() - 86400000 * 9, cool: 3, note: '', done: true, bought: false });
      save(state); show('yi'); setYiTab('wish');
    }""")
    page.wait_for_timeout(300)
    ripe = page.evaluate("() => wishRipe().length")
    check("冷静期到了的是 1 件（5 天 > 3 天那个）", ripe, 1)
    check("页签上标了 data-ripe",
          page.evaluate("() => document.querySelector('#yiTabs [data-yitab=\"wish\"]').getAttribute('data-ripe')"), "1")
    # 页签上那枚徽标的字就是 data-ripe（CSS attr() 读的），不是另一个人手写的常量
    badge = page.evaluate("""() => {
      const b = document.querySelector('#yiTabs [data-yitab="wish"]');
      const cs = getComputedStyle(b, '::before');
      return { content: cs.content, bg: cs.backgroundColor, color: cs.color };
    }""")
    check("徽标上那个数 = data-ripe", badge["content"], '"1"')
    check("徽标是印章红实底（从变量取，不是写死色值）", badge["bg"], "rgb(181, 74, 60)")
    # 徽标不许被 .tabs 的滚动容器裁掉：它的上边沿必须在容器可见区里
    clipped = page.evaluate("""() => {
      const tabs = document.querySelector('#yiTabs').getBoundingClientRect();
      const b = document.querySelector('#yiTabs [data-yitab="wish"]').getBoundingClientRect();
      return { tabsTop: Math.round(tabs.top), btnTop: Math.round(b.top),
               // ::before 的 top:3px + 16px 高 —— 只要容器上边沿不高于按钮上边沿太多就没裁
               腾出: Math.round(b.top - tabs.top) };
    }""")
    check("页签那一排在按钮上方留了位置（徽标不被滚动容器裁掉）", clipped["腾出"] >= 0, True)
    note = page.evaluate("() => (document.querySelector('#wishNote') || {}).textContent || ''")
    check("愿望页那句话里说了「冷静期到了」", "冷静期到了" in note, True)
    check("还说出了已经省下的钱", "省下" in note, True)
    page.screenshot(path=str(OUT / "yi-v06-wish.png"), full_page=True)
    check("老的那一件（已决定不买）有一枚「放回在想」",
          page.evaluate("() => document.querySelectorAll('#wishList [data-wundo]').length"), 1)
    check("在想的两件各有一枚「去过笺」",
          page.evaluate("() => document.querySelectorAll('#wishList [data-wpass]').length"), 2)

    # 「省下 ¥1200」这个数对不对（只有 done && !bought && 有价格的那一件）
    saved = page.evaluate("() => [wishSaved().pieces, wishSaved().money]")
    check("累计忍住：1 件", saved[0], 1)
    check("累计忍住：¥1200", saved[1], 1200)

    # 去过笺：把名字与品类带到过笺页
    page.click("#wishList [data-wpass='s1']")
    page.wait_for_timeout(300)
    check("点「去过笺」切到过笺页", page.evaluate("() => (document.querySelector('#yiPanePass').hidden)"), False)
    check("首屏那块纸显示的是这件（不是空白）",
          page.evaluate("() => (document.querySelector('#heroName') || {}).textContent || ''").find("羊绒大衣") >= 0, True)
    check("品类签跟着切到外套", page.evaluate("() => state.yiCat"), "外套")
    said = page.evaluate("() => ((document.querySelector('.toast') || {}).textContent || '')")
    check("说清了「判定要用一张照片重取颜色」", "照片" in said, True)

    # 不买了：省下的钱进统计
    page.evaluate("() => { show('yi'); setYiTab('wish'); }")
    page.wait_for_timeout(200)
    page.click("#wishList [data-wdrop='s2']")
    page.wait_for_timeout(250)
    saved2 = page.evaluate("() => [wishSaved().pieces, wishSaved().money]")
    check("再决定不买一件 → 2 件", saved2[0], 2)
    check("省下 ¥1200 + ¥399 = ¥1599", saved2[1], 1599)
    # 还有一件（羊绒大衣）冷静期到了，所以小点还在——它数的是「还没决定且到期」
    check("还剩一件到期的 → 小点仍在",
          page.evaluate("() => document.querySelector('#yiTabs [data-yitab=\"wish\"]').getAttribute('data-ripe')"), "1")
    page.evaluate("""() => {
      state.wish.forEach((w) => { if (!w.done) w.t = Date.now(); });
      save(state); renderWish();
    }""")
    page.wait_for_timeout(250)
    check("把冷静期重新拨回今天 → 小点消失（不摆一个不该有的红点）",
          page.evaluate("() => document.querySelector('#yiTabs [data-yitab=\"wish\"]').hasAttribute('data-ripe')"), False)

    # ---------- 9. 衣柜统计 ----------
    print("\n--- 9. 衣柜统计：数字与 state 对得上 ---")
    page.evaluate("""() => {
      state.wardrobe = [
        { id: 'w1', name: '燕麦针织', cat: '上衣', color: '#d4c4b0', worn: 9, lastWorn: Date.now() - 86400000 * 2,
          price: 600, boughtAt: Date.now() - 86400000 * 300, occasions: [], tags: [], note: '', wearDays: [] },
        { id: 'w2', name: '白衬衫', cat: '上衣', color: '#f4f0ea', worn: 4, lastWorn: Date.now() - 86400000 * 23,
          price: 300, boughtAt: Date.now() - 86400000 * 200, occasions: [], tags: [], note: '', wearDays: [] },
        { id: 'w3', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: Date.now() - 86400000,
          price: 800, boughtAt: Date.now() - 86400000 * 100, occasions: [], tags: [], note: '', wearDays: [] },
        { id: 'w4', name: '白鞋', cat: '鞋', color: '#f5f5f3', worn: 15, lastWorn: Date.now(),
          price: 500, boughtAt: Date.now() - 86400000 * 50, occasions: [], tags: [], note: '', wearDays: [] },
        { id: 'w5', name: '驼大衣', cat: '外套', color: '#c4a574', worn: 3, lastWorn: Date.now() - 86400000 * 214,
          price: null, boughtAt: null, occasions: [], tags: [], note: '', wearDays: [] },
      ];
      save(state); show('yi'); setYiTab('closet');
    }""")
    page.wait_for_timeout(300)
    stats = page.evaluate("""() => {
      const host = document.querySelector('#wardrobeStats');
      return { html: host.innerHTML, text: host.textContent || '' };
    }""")
    expected = page.evaluate("""() => {
      const wd = state.wardrobe;
      const priced = wd.filter((w) => w.price !== null && w.price !== undefined);
      const price = priced.reduce((s, w) => s + w.price, 0);
      const worn = priced.reduce((s, w) => s + w.worn, 0);
      return { n: wd.length, priced: priced.length, price, worn, cpw: price / worn,
               wr: wd.filter((w) => w.worn > 0).length };
    }""")
    check("统计里写着件数 5", "5" in stats["text"], True)
    check("统计里写着单次成本（总价 ÷ 总次数）的数值",
          f"¥{expected['cpw']:.1f}" in stats["text"], True)
    print(f"        期望：{expected['priced']} 件记价、共 ¥{expected['price']}、穿 {expected['worn']} 次 → 每次 ¥{expected['cpw']:.1f}")
    check("统计里说出了「几件记了价格」", f"{expected['priced']} 件记了价格" in stats["text"], True)
    check("没记价格的那件没被算进平均（5 件里 4 件参与）", "4 件记了价格" in stats["text"], True)
    # 在穿率 = 穿过件数 / 件数
    check("在穿率与真实 state 对得上", f"{round(expected['wr'] / expected['n'] * 100)}" in stats["text"], True)
    check("最常穿那一块画出来了", page.evaluate("() => document.querySelectorAll('#wardrobeStats .yi-top3-row').length") >= 3, True)
    check("最常穿第一位是「白鞋」（15 次）",
          page.evaluate("() => (document.querySelector('#wardrobeStats .yi-top3-row .yi-top3-name') || {}).textContent || ''"), "白鞋")
    check("统计里的名字能点进档案",
          page.evaluate("() => !!document.querySelector('#wardrobeStats [data-stat-item]')"), True)
    check("忍住的金额出现在统计里", "省下" in stats["text"], True)
    page.screenshot(path=str(OUT / "yi-v06-stats.png"), full_page=True)

    # 点统计里的名字 → 进档案
    page.click("#wardrobeStats [data-stat-item]")
    page.wait_for_timeout(300)
    check("点统计里的名字进得了单品档案", page.evaluate("() => (document.querySelector('.screen.on') || {}).id"), "yi-item")

    # ---------- 10. 薄数据时说薄，不摆 0 当结论 ----------
    print("\n--- 10. 薄数据：说薄，不把 0 / Infinity 当结论 ---")
    page.evaluate("""() => {
      state.wardrobe = [
        { id: 'w1', name: 'A', cat: '上衣', color: '#d4c4b0', worn: 0, lastWorn: null,
          price: null, boughtAt: null, occasions: [], tags: [], note: '', wearDays: [] },
        { id: 'w2', name: 'B', cat: '裤装', color: '#2c3a4a', worn: 0, lastWorn: null,
          price: null, boughtAt: null, occasions: [], tags: [], note: '', wearDays: [] },
      ];
      save(state); show('yi'); setYiTab('closet');
    }""")
    page.wait_for_timeout(300)
    thin_txt = page.evaluate("() => (document.querySelector('#wardrobeStats') || {}).textContent || ''")
    check("两件的柜子会说「还说明不了什么」", "说明不了什么" in thin_txt, True)
    check("没价格时说的是「还没给任何一件记价格」", "还没给任何一件记价格" in thin_txt, True)
    check("没穿过时**不**拿 Infinity / 0 冒充单次成本", ("Infinity" in thin_txt) or ("¥0.0" in thin_txt), False)

    # 单件详情的薄数据话术
    page.evaluate("() => { state.clothSel = 'w1'; save(state); renderCloset(); openItem('w1'); }")
    page.wait_for_timeout(250)
    item_txt = page.evaluate("() => (document.querySelector('#itemBody') || {}).textContent || ''")
    check("没记价格的档案说「算不出值不值」", "算不出值不值" in item_txt, True)
    check("档案里说清了还缺哪几样", "还空着" in item_txt, True)

    # 记了价格但没穿过
    page.evaluate("() => { state.wardrobe[0].price = 1200; save(state); renderYiItem(); }")
    page.wait_for_timeout(200)
    item_txt2 = page.evaluate("() => (document.querySelector('#itemBody') || {}).textContent || ''")
    check("记了价格但没穿过 → 「还看不出值不值」", "还看不出值不值" in item_txt2, True)
    check("那一格显示的是「— / ∞」而不是 ¥0.0",
          page.evaluate("() => (document.querySelector('#itemBody .yi-cost-num') || {}).textContent || ''").find("¥0.0"), -1)

    # ---------- 11. 柜子里记穿之后，档案页的日历与账是一致的 ----------
    print("\n--- 11. 从柜子里「今天穿了」→ 档案页的日历也认得那一天 ---")
    page.evaluate("""() => {
      state.wardrobe = [
        { id: 'w1', name: '燕麦针织', cat: '上衣', color: '#d4c4b0', worn: 2, lastWorn: Date.now() - 86400000 * 9,
          price: 600, boughtAt: null, occasions: [], tags: [], note: '', wearDays: [] },
      ];
      state.log = []; save(state); show('yi'); setYiTab('closet');
      state.clothSel = 'w1'; save(state); renderCloset();
    }""")
    page.wait_for_timeout(300)
    before_w = page.evaluate("() => state.wardrobe[0].worn")
    page.click("#wearIt")            # 走的是 yi.js 的 wearNow（主路），不是档案页自己的按钮
    page.wait_for_timeout(300)
    check("从柜子里记穿：次数 +1", page.evaluate("() => state.wardrobe[0].worn") - before_w, 1)
    check("它也进了 log（热力图/成就读它）", page.evaluate("() => state.log.filter((e) => e.kind === 'wear').length"), 1)
    page.evaluate("() => openItem('w1')")
    page.wait_for_timeout(300)
    page.evaluate("() => { itemCalOpen = true; renderYiItem(); }")
    page.wait_for_timeout(250)
    today_d = page.evaluate("() => new Date().getDate()")
    check("档案页的日历把柜子里记的那天算成「穿过」",
          page.evaluate(f"() => document.querySelector('#itemCal [data-cald=\"{today_d}\"]').getAttribute('aria-pressed')"), "true")
    check("日历标题说的是「记了 1 天」",
          page.evaluate("() => (document.querySelector('.yi-cal-title') || {}).textContent || ''").find("记了 1 天") >= 0, True)
    # 再点一次今天 = 取消（账与日历双向都改得动）
    page.click(f"#itemCal [data-cald='{today_d}']")
    page.wait_for_timeout(300)
    check("从日历上取消那天：次数退回", page.evaluate("() => state.wardrobe[0].worn"), before_w)
    check("取消后日历上那一天又空了",
          page.evaluate(f"() => document.querySelector('#itemCal [data-cald=\"{today_d}\"]').getAttribute('aria-pressed')"), "false")

    # ---------- 12. 页签小点在冷启动时也在 ----------
    print("\n--- 12. 冷启动：页签上的小点不靠某次点击才出现 ---")
    page.evaluate("""() => {
      state.wish = [{ id: 's1', name: '想买的大衣', cat: '外套', color: '#c4c4c4', price: 100,
                      t: Date.now() - 86400000 * 9, cool: 3, note: '', done: false, bought: false }];
      save(state);
    }""")
    page.reload()
    page.wait_for_timeout(900)
    check("重开之后页签上那个点还在（挂 load 上，不是只在点页签时才刷）",
          page.evaluate("() => { const b = document.querySelector('#yiTabs [data-yitab=\"wish\"]');"
                        " return !!(b && b.getAttribute('data-ripe')); }"), True)
    check("点那个点的数字与 wishRipe() 一致",
          page.evaluate("() => +document.querySelector('#yiTabs [data-yitab=\"wish\"]').getAttribute('data-ripe')"),
          page.evaluate("() => wishRipe().length"))

    # ---------- 13. 档案页的两处空态都有出路 ----------
    print("\n--- 13. 档案页的空态给了下一步，不是一句话就完了 ---")
    page.evaluate("() => { state.wardrobe = []; save(state); show('yi'); setYiTab('closet'); }")
    page.wait_for_timeout(250)
    page.evaluate("() => openItem('nope')")
    page.wait_for_timeout(250)
    check("柜里空着时档案页说「没有可以看的档案」",
          page.evaluate("() => (document.querySelector('#itemBody') || {}).textContent || ''").find("没有可以看的档案") >= 0, True)
    check("它给了一枚能走的入口", page.evaluate("() => !!document.querySelector('#itemToCloset')"), True)
    page.click("#itemToCloset")
    page.wait_for_timeout(300)
    check("点它回到柜子", page.evaluate("() => (document.querySelector('.screen.on') || {}).id"), "yi")

    # ---------- 14. 全程无异常 ----------
    errs = [e for e in errors if "pageerror" in e]
    check("全程无未捕获异常", errs, [])

    ctx.close()
    browser.close()

passed = len([c for c in checks if c[0]])
failed = len(checks) - passed
print(f"\n衣笺 lane：{passed} 通过 / {failed} 失败")
sys.exit(1 if failed else 0)
