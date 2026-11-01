# 味笺 lane（v0.6.0）的验收：菜谱库 / 菜谱详情 / 转盘 / 一周菜单 / 买菜清单 / 口味档案 / 菜单长图
#
# 为什么单独一份而不并进 smoke.py：smoke 是「改完一眼看它炸没炸」，两分钟以内跑完，
# 断言数要克制；这一份是味笺这一层的**行为合同**，逐条写着「用户做完这件事之后，
# state 里应该是什么」。两者混在一起，smoke 会慢到没人愿意在每一轮都跑。
#
# 跑法：$env:PYTHONIOENCODING='utf-8'; python test/wei_v06.playwright.py
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()

checks = []


def check(name, got, want=True):
    # want 是 bool 时按真值比（False 也是一种期望，不能拿默认值把它顶掉）；
    # 其余情况按 == 比（列表、数字、字符串）。
    ok = (bool(got) == want) if isinstance(want, bool) else (got == want)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


# 忌口清单**从源码里现读**，不在这里抄一份。
# 抄一份的后果是具体的：2026-10 给 state.js 补了 蛋 / 小麦 / 大豆 / 坚果 四类，
# 而这份写死的清单还是十一项——那道「63 道 × N 种忌口逐一对账」的门照旧绿，
# 新加的四类一个字都没被验过。这正是本仓反复栽的「第二份定义」。
import re as _re
_STATE = (ROOT / "state.js").read_text(encoding="utf-8")
CHIPS = _re.search(r"const CHIPS = \[([^\]]*)\]", _STATE).group(1)
CHIPS = [c for c in _re.findall(r'"([^"]+)"', CHIPS)]
assert len(CHIPS) >= 11, f"state.js 里读出来的忌口清单不对：{CHIPS}"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
    page.clock.install(time="2026-09-17T10:00:00")
    page.goto(URL)
    page.wait_for_timeout(700)
    page.click("#go")
    page.wait_for_timeout(250)

    print("\n--- 1. 菜库是一座能逛的库：63 道，按四类分组 ---")
    check("菜库拍平正好 63 道", page.evaluate("() => allDishes().length"), 63)
    kinds = page.evaluate("() => allDishes().reduce((m, d) => (m[d.kind] = (m[d.kind] || 0) + 1, m), {})")
    check("四类都有货：" + str(kinds), sorted(kinds.keys()), ["主食", "汤", "素", "荤"])
    st = page.evaluate(
        "() => { show('wei'); setWeiTab('cook'); return document.querySelectorAll('#cookList .dish-group').length; }")
    page.wait_for_timeout(250)
    check("屏上按组分块（荤/素/汤/主食，主食默认收起但那一块在）", st, 4)
    # 这一条以前是「每一组的 .dish-grid 都是 grid」，而主食那一组**默认是收起的**
    # （`hidden` 属性）——`hidden` 的子树 `getComputedStyle().display` 是 `none`，
    # 所以那条断言必然红。那不是产品坏了，是断言把「收起」和「没画成网格」混成了一件事。
    # 现在分开量：摊开的那三组必须是 grid，收起的那一组必须是 none（它确实在 DOM 里，
    # 只是没摊开——这正是「那一块在」的意思）。
    grids = page.evaluate("""() => [...document.querySelectorAll('#cookList .dish-grid')]
      .map(g => ({ hidden: g.hidden, display: getComputedStyle(g).display }))""")
    open_ones = [g for g in grids if not g["hidden"]]
    shut_ones = [g for g in grids if g["hidden"]]
    # 注意 check() 的签名是 (name, got, want=True)：第三个位置是**期望值**，不是「附加说明」。
    # 把列表塞进第三个位置会退化成 `True == [...]`，于是两条正确的事实被判成红
    # （第一版就是这么红的）。细节写进断言名里。
    check("摊开的那几组真的是卡片网格（display:grid）：" + str(open_ones),
          len(open_ones) >= 3 and all(g["display"] == "grid" for g in open_ones))
    check("收起的那一组确实在 DOM 里、只是没摊开（hidden + display:none）：" + str(shut_ones),
          len(shut_ones) == 1 and shut_ones[0]["display"] == "none")
    check("一屏能扫到 ≥6 张卡（390 宽下第一屏）", page.evaluate("""() => {
      const vh = window.innerHeight;
      return [...document.querySelectorAll('#cookList .dish-card')]
        .filter(c => { const r = c.getBoundingClientRect(); return r.top < vh && r.bottom > 0; }).length;
    }""") >= 6, True)
    check("分组头可折叠：点一下那一组就收起来", page.evaluate("""() => {
      const head = document.querySelector('#cookList [data-dgtoggle]');
      head.click();
      const g = document.querySelector('#cookList .dish-grid');
      return g.hidden;
    }"""), True)
    page.evaluate("() => document.querySelector('#cookList [data-dgtoggle]').click()")
    page.wait_for_timeout(150)
    check("再点一下摊开（折叠不是单向门）",
          page.evaluate("() => document.querySelector('#cookList .dish-grid').hidden"), False)

    print("\n--- 2. 搜索：名字 / 忌口标签 / 用户的食材与步骤 ---")
    # 先写一张自己的菜谱，用来验「搜食材与步骤」
    page.evaluate("""() => {
      state.recipes = [{ id: 'k1', name: '外婆的红烧肉', minutes: 90, level: 2, serves: 4,
        items: ['五花肉 500 克', '冰糖 20 克'], steps: ['焯水', '炒糖色', '小火炖一小时'], t: Date.now() }];
      save(state); renderCook();
    }""")
    page.wait_for_timeout(200)
    search = lambda q: page.evaluate("""(q) => {
      const s = document.querySelector('#dishSearch'); s.value = q; s.dispatchEvent(new Event('input'));
      return [...document.querySelectorAll('#cookList .dish-card .dc-name')].map(e => e.textContent);
    }""", q)
    names = search("冰糖")
    check("搜食材「冰糖」→ 自己录的那道出现", names, ["外婆的红烧肉"])
    names = search("炒糖色")
    check("搜步骤也能命中", names, ["外婆的红烧肉"])
    names = search("花生")
    check("搜忌口标签「花生」→ 只命中菜库挂着花生的那道（酱爆鸡丁）", "酱爆鸡丁" in names, True)
    names = search("西兰花")
    check("搜菜名命中", names, ["蒜蓉西兰花"])
    search("")
    page.wait_for_timeout(120)
    check("自己录的那道单独成「自己录的」一组", page.evaluate(
        "() => !!document.querySelector('#cookList .dish-group[data-group=\"自己录的\"]')"), True)

    print("\n--- 3. 「自己写一道」是屏内面板，不用原生弹框 ---")
    # 这一条守的是「不该弹原生框」，不是「弹不出来」。
    # prompt/confirm 在这个壳里**是能用的**：Capacitor 的 BridgeWebChromeClient 真实现了
    # onJsPrompt / onJsConfirm（Material AlertDialog + EditText + 英文 OK/Cancel）。
    # 不用它的理由是三个：跟这张纸不是同一套东西、阻塞 WebView、只能问一行字。
    page.evaluate("() => { cookPanel = ''; renderCook(); document.querySelector('#newRecipe').click(); }")
    page.wait_for_timeout(250)
    check("点「自己写一道」出一个屏内面板", page.evaluate(
        "() => !!document.querySelector('#cookList #newRecipePanel')"), True)
    check("面板里那格是普通输入框，不是原生弹窗", page.evaluate(
        "() => document.querySelector('#cookList #nrName').tagName"), "INPUT")
    page.evaluate("() => { document.querySelector('#cookList #nrName').value = '番茄牛腩';"
                  " document.querySelector('#cookList #nrGo').click(); }")
    page.wait_for_timeout(300)
    check("按「接着写」就进编辑器，且已经在菜谱那一屏", page.evaluate(
        "() => [document.querySelector('.screen.on').id, !!document.querySelector('#rcItems')]"), ["wei-dish", True])
    page.evaluate("""() => {
      document.querySelector('#rcMinutes').value = '45';
      document.querySelector('#rcItems').value = '牛腩 500 克\\n番茄 3 个';
      document.querySelector('#rcSteps').value = '牛腩焯水\\n番茄炒软\\n小火炖四十分钟';
      document.querySelector('#rcSave').click();
    }""")
    page.wait_for_timeout(300)
    rec = page.evaluate("() => (state.recipes || []).find(r => r.name === '番茄牛腩')")
    check("菜谱存进 state：用时 45、食材 2、步骤 3",
          [rec["minutes"], len(rec["items"]), len(rec["steps"])], [45, 2, 3])
    check("菜谱正文只由用户写：内置菜库的那 63 道里没有一道带 steps",
          page.evaluate("() => allDishes().every(d => !d.steps && !d.items)"), True)
    # #newRecipe 这枚按钮是 index.html 里的常驻节点、app.js 在 boot 里绑过一个 prompt。
    # 两条断言守的是「覆盖」这件事：不留两条 handler（点一次只开一个面板、prompt 计数为 0），
    # 以及在别的页签下点到它时先把页签切到位（面板不会画进一个看不见的容器）。
    page.evaluate("""
      window.__promptCalls = 0;
      window.prompt = () => { window.__promptCalls++; return 'x'; };
      show('wei'); setWeiTab('plan');
    """)
    page.wait_for_timeout(200)
    src = page.evaluate("() => String(document.querySelector('#newRecipe').onclick)")
    check("进味笺之后 #newRecipe 的 handler 已经被换掉（不再是 app.js 那个 prompt）",
          "prompt" in src, False)
    page.evaluate("() => document.querySelector('#newRecipe').click()")
    page.wait_for_timeout(350)
    check("在排桌页签下点它：先切到「做菜」页签，再开面板",
          page.evaluate("""() => [
            [...document.querySelectorAll('#weiTabs [data-weitab]')]
              .find(b => b.getAttribute('aria-selected') === 'true').dataset.weitab,
            !!document.querySelector('#weiPaneCook #newRecipePanel'),
            window.__promptCalls]"""), ["cook", True, 0])
    check("点一次只开一个面板（没有两条 handler 同时跑）", page.evaluate(
        "() => document.querySelectorAll('#weiPaneCook #newRecipePanel').length"), 1)
    page.evaluate("() => document.querySelector('#newRecipe').click()")
    page.wait_for_timeout(250)
    check("再点一次收起，prompt 始终没被调用过", page.evaluate(
        "() => [!!document.querySelector('#weiPaneCook #newRecipePanel'), window.__promptCalls]"), [False, 0])

    print("\n--- 4. 菜谱详情：和这桌人的关系 / 做过几次 / 加进这周 ---")
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
      save(state); openDish('宫保鸡丁');
    }""")
    page.wait_for_timeout(300)
    rel = page.evaluate("() => (document.querySelector('#dishBody .dish-rel-bad') || {}).textContent || ''")
    check("详情说清是「谁」不能吃（不是只说有雷）", ["我" in rel, "花生" in rel], [True, True])
    # 宫保鸡丁只踩「花生」：小周忌辣不会被它踩到。要看「逐个人」得挑一道两个都踩的，
    # 或者让两个人的忌口都踩到同一道——这里换成「水煮鱼」（辣），只踩小周。
    page.evaluate("() => openDish('水煮鱼')")
    page.wait_for_timeout(250)
    rel2 = page.evaluate("() => (document.querySelector('#dishBody .dish-rel-bad') || {}).textContent || ''")
    check("换一道只踩一个人：那一行点名的就是那个人（不是笼统说「有人」）",
          ["小周" in rel2, "我" not in rel2], [True, True])
    page.evaluate("""() => {
      // 麻婆豆腐同时踩两样（菜库里挂着 辣 + 猪肉）：两个人各踩一样，这一行就该有两个名字
      state.people = [{ name: '我', chips: ['辣'] }, { name: '小周', chips: ['猪肉'] }];
      save(state); openDish('麻婆豆腐');
    }""")
    page.wait_for_timeout(250)
    rel3 = page.evaluate("() => (document.querySelector('#dishBody .dish-rel-bad') || {}).textContent || ''")
    check("两个人都踩到时两个名字都在那一行：" + rel3, ["我" in rel3, "小周" in rel3], [True, True])
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
      save(state); openDish('白切鸡');
    }""")
    page.wait_for_timeout(250)
    check("没人吃不了的那道说「都能吃」", page.evaluate(
        "() => !!document.querySelector('#dishBody .dish-rel-ok')"), True)
    # 加进这周的某一餐：7 天 × 2 餐
    check("加进某一餐的入口有 14 个（7 天 × 午晚饭）", page.evaluate(
        "() => document.querySelectorAll('#dishBody [data-dishweek]').length"), 14)
    page.evaluate("() => document.querySelector('#dishBody [data-dishweek=\"3:night\"]').click()")
    page.wait_for_timeout(300)
    check("点了之后真的落进周四晚饭", page.evaluate(
        "() => { const w = currentWeek(false); return (w.days[3].night || []); }"), ["白切鸡"])
    check("落格之后那一格写着已有几道", page.evaluate(
        "() => document.querySelector('#dishBody [data-dishweek=\"3:night\"]').textContent"), "晚饭 · 1")
    # 做过几次
    page.evaluate("() => { document.querySelector('#cookIt').click(); }")
    page.wait_for_timeout(250)
    check("「今天做了这道」记进 cookLog", page.evaluate("() => (state.cookLog || []).length"), 1)
    check("详情页当场改口说「做过 1 次」", page.evaluate(
        "() => document.querySelector('#dishBody .dh-main .tiny').textContent.includes('做过 1 次')"), True)
    page.evaluate("() => { document.querySelector('#cookIt').click(); }")
    page.wait_for_timeout(250)
    check("再做一次是「做过 2 次」，不是又开一行", page.evaluate(
        "() => [(state.cookLog || []).length,"
        " document.querySelector('#dishBody .dh-main .tiny').textContent.includes('做过 2 次')]"), [2, True])

    print("\n--- 5. 忌口判定与排桌同源（不是第二份口径）---")
    # 这一条是这一版最要紧的一处：菜谱页以前问 Engine.dishBans，比排桌少两层判定
    # （HIDDEN 与 CHIP_MAP），实测 63 道 × 11 种忌口里有 6 组两个答案。
    diff = page.evaluate("""(chips) => {
      const bad = [];
      allDishes().forEach((d) => {
        chips.forEach((c) => {
          const mine = dishBansFor(d, [{ name: 'x', chips: [c] }]).length > 0;
          const r = Engine.wei(d.name, [{ name: 'x', chips: [c] }], 'friends');
          if (mine !== (r.boom.length > 0)) bad.push([d.name, c]);
        });
      });
      return bad;
    }""", CHIPS)
    # 数字从 CHIPS 现算：写死 11 就会在清单变长之后继续说「11 种」，而它其实已经跑了 15 种。
    check(f"63 道 × {len(CHIPS)} 种忌口，菜谱页与排桌逐一对账（{63 * len(CHIPS)} 组）",
          diff, [])
    spot = page.evaluate("() => dishBansFor({ name: '白灼菜心' }, [{ name: 'x', chips: ['内脏'] }])")
    check("抽查：「白灼菜心」对忌内脏的人算雷（菜名里有「心」，排桌一直是这么判的）", spot, ["内脏"])

    print("\n--- 6. 今晚吃什么：抽出来的菜一定在「这桌人能吃的」里 ---")
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
      save(state); show('wei'); setWeiTab('cook'); renderCook(); renderWeiPeople();
    }""")
    page.wait_for_timeout(250)
    picks = []
    for _ in range(8):
        page.evaluate("() => document.querySelector('#wheelBtn').click()")
        page.wait_for_timeout(120)
        picks.append(page.evaluate("() => wheelResult && wheelResult.name"))
    check("抽了 8 次，8 次都有结果", len([x for x in picks if x]), 8)
    unsafe = page.evaluate("""(names) => names.filter((n) => {
      const d = allDishes().find(x => x.name === n) || { name: n };
      return dishBansFor(d, state.people).length > 0;
    })""", picks)
    check("这 8 道全都能被这桌吃（忌花生 + 忌辣）", unsafe, [])
    check("抽到的菜名真的画在屏上", page.evaluate(
        "() => document.querySelector('#wheelPick').textContent"), picks[-1])
    check("面板上有「再抽一次」和「就它了」两枚", page.evaluate(
        "() => [!!document.querySelector('#cookList [data-wheel=\"again\"]'),"
        " !!document.querySelector('#cookList [data-wheel=\"keep\"]')]"), [True, True])
    # no-motion 下动画必须立即完成：轨道直接停在抽中那一格
    page.evaluate("() => { THEME.set('motion', false); spinWheel(); }")
    page.wait_for_timeout(120)
    geo = page.evaluate("""() => {
      const stage = document.querySelector('.wheel-stage').getBoundingClientRect();
      const band = document.querySelector('.wheel-pick').getBoundingClientRect();
      const track = document.querySelector('.wheel-track');
      const spans = [...track.children];
      const hit = spans.findIndex((s) => {
        const r = s.getBoundingClientRect();
        return Math.abs((r.top + r.bottom) / 2 - (band.top + band.bottom) / 2) < 3;
      });
      return { hit, pick: track.querySelector('span.pick').textContent,
               anim: getComputedStyle(track).animationDuration, same: hit >= 0 };
    }""")
    check("no-motion 下抽中的那一格真的停在高亮框里：" + str(geo["pick"]), geo["same"], True)
    check("no-motion 下动画时长被压到 .001s（不是靠 setTimeout 兜）",
          geo["anim"] in ("0.001s", "0s"), True)
    page.evaluate("() => THEME.set('motion', true)")
    # 就它了 → 记进这周
    page.evaluate("() => { weekPick = null; state.weeks = []; save(state); }")
    page.evaluate("() => document.querySelector('#cookList [data-wheel=\"keep\"]').click()")
    page.wait_for_timeout(300)
    check("「就它了」把这周某一餐排上了", page.evaluate(
        "() => currentWeek(false) ? weekDishCount(currentWeek(false)) : 0"), 1)

    print("\n--- 7. 一周菜单：点格弹面板落菜 / 每格可删 / 删了能撤销 ---")
    page.evaluate("() => { state.weeks = []; save(state); weekPick = null; setWeiTab('week'); }")
    page.wait_for_timeout(250)
    check("这周页签有 7 天 × 2 餐 = 14 格", page.evaluate(
        "() => document.querySelectorAll('#weekGrid [data-wkpick]').length"), 14)
    page.evaluate("() => document.querySelector('#weekGrid [data-wkpick=\"1:noon\"]').click()")
    page.wait_for_timeout(250)
    check("点一格弹出屏内挑菜面板（不是 prompt）", page.evaluate(
        "() => !!document.querySelector('#weekGrid .wk-pick')"), True)
    check("面板里能搜（有一格搜索框）", page.evaluate(
        "() => !!document.querySelector('#weekGrid .wk-search')"), True)
    page.evaluate("""() => { const s = document.querySelector('#weekGrid .wk-search');
      s.value = '鱼'; s.dispatchEvent(new Event('input')); }""")
    page.wait_for_timeout(250)
    opts = page.evaluate("() => [...document.querySelectorAll('#weekGrid [data-wkadd]')].map(b => b.dataset.wkadd)")
    check("搜「鱼」筛出几道（" + str(len(opts)) + "）", len(opts) > 0, True)
    page.evaluate("() => document.querySelector('#weekGrid [data-wkadd]').click()")
    page.wait_for_timeout(300)
    check("点选项就落进周二午饭那一格", page.evaluate(
        "() => JSON.stringify(((state.weeks[0] || { days: [] }).days[1] || {}).noon || [])"),
        '["' + opts[0] + '"]')
    page.evaluate("() => document.querySelector('#weekGrid [data-wkrm]').click()")
    page.wait_for_timeout(300)
    check("面板里那枚「✕」把这道删掉了", page.evaluate(
        "() => JSON.stringify(((state.weeks[0] || { days: [] }).days[1] || {}).noon || [])"), "[]")
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(300)
    check("删掉之后那一枚「撤销」把它放回原处", page.evaluate(
        "() => JSON.stringify(((state.weeks[0] || { days: [] }).days[1] || {}).noon || [])"),
        '["' + opts[0] + '"]')
    # 一天最多四道 + 同一个不重复
    cap = page.evaluate("""() => {
      state.weeks = []; save(state);
      for (let i = 0; i < 6; i++) addToWeek(2, 'noon', '菜' + i);
      return ((currentWeek(false).days[2] || {}).noon || []).length;
    }""")
    check("一天最多四道（塞六次只进四道）", cap, 4)
    dup = page.evaluate("() => [addToWeek(3, 'night', '米饭'), addToWeek(3, 'night', '米饭'),"
                        " ((currentWeek(false).days[3] || {}).night || []).length]")
    check("同一格同一个菜不会排两遍", dup, [True, False, 1])

    print("\n--- 8. 一周菜单 → 买菜清单：只算写过食材的，重复只算一次，缺的说出来 ---")
    page.evaluate("""() => {
      state.weeks = []; state.market = []; state.recipes = [];
      state.recipes.push({ id: 'k1', name: '番茄牛腩', minutes: 60, level: 2, serves: 3,
        items: ['牛腩 500 克', '番茄 3 个'], steps: ['炖'], t: Date.now() });
      state.recipes.push({ id: 'k2', name: '蒜蓉西兰花', minutes: 20, level: 1, serves: 2,
        items: ['西兰花 1 个', '蒜 4 瓣'], steps: ['炒'], t: Date.now() });
      save(state);
      addToWeek(0, 'noon', '番茄牛腩');
      addToWeek(0, 'night', '番茄牛腩');     // 同一道排两次
      addToWeek(1, 'noon', '蒜蓉西兰花');
      addToWeek(2, 'noon', '白切鸡');        // 没写食材
    }""")
    page.wait_for_timeout(200)
    shop = page.evaluate("() => { const s = weekShopping(); return {n: s.dishes.length, uniq: s.uniq.length,"
                         " miss: s.missing, rep: s.repeat, items: s.items.length}; }")
    check("这周排了 4 道（含重复），4 条记录", [shop["n"], shop["uniq"]], [4, 3])
    check("重复排的那道被点出来：" + str(shop["rep"]), shop["rep"], ["番茄牛腩"])
    check("没写食材的那道被点出来：" + str(shop["miss"]), shop["miss"], ["白切鸡"])
    check("食材一共 4 样（重复的那道只算一次）", shop["items"], 4)
    page.evaluate("() => document.querySelector('#weekGrid [data-weekmarket]').click()")
    page.wait_for_timeout(400)
    check("清单真的生成了 4 条", page.evaluate("() => (state.market || []).length"), 4)
    check("落到「买菜」页签上（不是留在周菜单干看着）", page.evaluate(
        "() => document.querySelector('.screen.on').id + '|' + !document.querySelector('#weiPaneMarket').hidden"),
        "wei|true")

    print("\n--- 9. 买菜清单：合并边界 / 货架分区 / 勾掉记一笔 / 排序切换 ---")
    merged = page.evaluate("""() => {
      state.market = []; save(state);
      addMarketItems(['鸡蛋 2 个'], 'a');
      addMarketItems(['鸡蛋 3 个'], 'a');
      const same = state.market.find(m => m.name === '鸡蛋').qty;
      addMarketItems(['鸡蛋 200 克'], 'a');
      const mixed = state.market.find(m => m.name === '鸡蛋').qty;
      state.market = []; save(state);
      addMarketItems(['鸡蛋 2 个', '鸡蛋 2 个'], 'a');
      return [same, mixed, state.market.length];
    }""")
    check("同名同单位相加：2 个 + 3 个 = 5 个", merged[0], "5个")
    check("同名不同单位并排、硬加就是假话：5 个 + 200 克", merged[1], "5个 + 200克")
    check("第二次加同一样不新增行", merged[2], 1)
    page.evaluate("""() => {
      state.market = []; save(state);
      addMarketItems(['鸡蛋 2 个', '番茄 3 个', '排骨 500 克', '生抽 1 瓶'], 'test');
      setWeiTab('market');
    }""")
    page.wait_for_timeout(250)
    kindsOnScreen = page.evaluate("""() => [...document.querySelectorAll('#marketList .mrow')]
      .map(r => r.querySelector('.grow b').textContent)""")
    check("四样都在屏上：" + str(kindsOnScreen), len(kindsOnScreen), 4)
    check("按货架分区的小标题也在（肉蛋 / 蔬菜 / 调料…）", page.evaluate(
        "() => [...document.querySelectorAll('#marketList p.tiny')].map(p => p.textContent.split(' · ')[0])"
        ".filter(x => ['肉蛋','蔬菜','调料','水产','主食','水果','其他'].includes(x)).length >= 3"), True)
    check("默认按货架排", page.evaluate("() => marketSort"), "shelf")
    page.evaluate("() => document.querySelector('#marketList [data-msort=\"time\"]').click()")
    page.wait_for_timeout(220)
    check("切成按加入时间：选中态跟着换", page.evaluate(
        "() => [marketSort, document.querySelector('#marketList [data-msort=\"time\"]').getAttribute('aria-pressed')]"),
        ["time", "true"])
    check("切了之后清单还在（不是空屏）", page.evaluate(
        "() => document.querySelectorAll('#marketList .mrow').length"), 4)
    page.evaluate("() => document.querySelector('#marketList [data-msort=\"shelf\"]').click()")
    page.wait_for_timeout(200)
    check("再切回货架也行", page.evaluate("() => marketSort"), "shelf")
    # 勾掉 → logEvent("market")
    # 每点一次都重新取节点：勾一下整片会重画一次，拿同一批节点连点是在点已经不存在的元素。
    # 真实手指也是「点一下 → 看见新的一屏 → 再点下一格」，这里照它写。
    marks = page.evaluate("""() => {
      state.market = []; state.log = []; save(state);
      addMarketItems(['鸡蛋 2 个', '番茄 3 个', '排骨 500 克'], 'test');
      setWeiTab('market');
      for (let k = 0; k < 3; k++) {
        const cb = document.querySelector('#marketList .mrow:not(.done) [data-mcheck]');
        if (cb) cb.click();
      }
      return [(state.log || []).filter((e) => e.kind === 'market').length,
              (state.market || []).filter((m) => m.done).length];
    }""")
    check("勾掉三样 → 行为流水里有 3 条 kind=market（成就「买到二十样」靠它）", marks, [3, 3])
    unmark = page.evaluate("""() => {
      const before = (state.log || []).filter((e) => e.kind === 'market').length;
      const cb = document.querySelector('#marketList .mrow.done [data-mcheck]');
      if (cb) cb.click();
      return (state.log || []).filter((e) => e.kind === 'market').length - before;
    }""")
    check("取消勾掉不是一件事，不记流水", unmark, 0)
    page.wait_for_timeout(200)
    check("三条里取消了一条，剩下两条在「已经拿到」那一段", page.evaluate(
        "() => document.querySelectorAll('#marketList .mrow.done').length"), 2)
    # 清掉 / 删除 / 撤销这一组从四样干净的清单重新起步（前面那几条已经把状态搅过一轮）
    page.evaluate("""() => {
      state.market = []; save(state);
      addMarketItems(['鸡蛋 2 个', '番茄 3 个', '排骨 500 克', '生抽 1 瓶'], 'test');
      const first = state.market[0]; first.done = true;
      save(state); renderMarket();
    }""")
    page.wait_for_timeout(200)
    check("四样里勾掉一样（准备验「清掉已拿到的」）", page.evaluate(
        "() => [(state.market || []).length, (state.market || []).filter(m => m.done).length]"), [4, 1])
    page.evaluate("() => document.querySelector('#marketClear').click()")
    page.wait_for_timeout(250)
    check("「清掉已拿到的」把那一行清掉，剩三样", page.evaluate("() => (state.market || []).length"), 3)
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(250)
    check("撤销把它放回来（连同 done 状态）", page.evaluate(
        "() => [(state.market || []).length, (state.market || []).filter(m => m.done).length]"), [4, 1])
    # 删一条 + 撤销。删「还没买的」那一条：已拿到的那一条在另一段里，选中会受排序影响
    page.evaluate("""() => {
      const row = document.querySelector('#marketList .mrow:not(.done) [data-mdel]');
      row.click();
    }""")
    page.wait_for_timeout(250)
    check("删一条真的少一条", page.evaluate("() => (state.market || []).length"), 3)
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(250)
    check("删掉的撤销得回来（还是四样）", page.evaluate("() => (state.market || []).length"), 4)

    print("\n--- 10. 常一起吃饭的人：存档 / 拉回来 / 重名说清 ---")
    page.evaluate("""() => {
      state.peopleSets = [];
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
      save(state); show('wei'); setWeiTab('plan'); renderWeiPeople();
    }""")
    page.wait_for_timeout(250)
    check("排桌页有一个「常一起吃饭的人」抽屉", page.evaluate(
        "() => !!document.querySelector('#peopleSets details.people-drawer')"), True)
    page.evaluate("() => document.querySelector('#peopleSets [data-psave]').click()")
    page.wait_for_timeout(250)
    check("存下一组（名字 + 每个人的忌口快照）", page.evaluate(
        "() => JSON.stringify((state.peopleSets || []).map(g => [g.names.length,"
        " g.names.map(x => x.name + ':' + x.chips.join('+'))]))"), "[[2,[\"我:花生\",\"小周:辣\"]]]")
    again = page.evaluate("() => [savePeopleSet(), (state.peopleSets || []).length]")
    check("一模一样的一组不重复存（那一栏会变成一堆同名项）", again[1], 1)
    # 换一桌人再拉回来
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: [] }]; save(state); renderWeiPeople();
      document.querySelector('#peopleSets [data-pload]').click();
    }""")
    page.wait_for_timeout(300)
    check("拉回来：小周回来了，忌口一起回来", page.evaluate(
        "() => JSON.stringify(state.people.map(p => p.name + ':' + p.chips.join('+')))"),
        '["我:","小周:辣"]')
    dupMsg = page.evaluate("""() => {
      const before = state.people.length;
      document.querySelector('#peopleSets [data-pload]').click();
      return [(state.people.length - before),
        (document.querySelector('.toast') || {}).textContent || ''];
    }""")
    page.wait_for_timeout(250)
    toastTxt = page.evaluate("() => (document.querySelector('.toast') || {}).textContent || ''")
    check("再拉一次不添第二个「小周」，并且当场说清", ["小周" not in [p for p in []], "已经在这桌" in toastTxt], [True, True])
    check("这桌人数没变", page.evaluate("() => state.people.length"), 2)
    page.evaluate("() => document.querySelector('#peopleSets [data-pdel]').click()")
    page.wait_for_timeout(250)
    check("删掉一组", page.evaluate("() => (state.peopleSets || []).length"), 0)
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(250)
    check("删掉的撤销得回来", page.evaluate("() => (state.peopleSets || []).length"), 1)

    print("\n--- 11. 菜单长图：1080×1920、画得出非空像素、取色走变量 ---")
    page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
      save(state); renderWeiPeople(); show('wei'); setWeiTab('plan');
      document.querySelector('#menu').value = '宫保鸡丁\\n水煮鱼\\n蒜蓉西兰花\\n白切鸡\\n米饭';
      runWei({ free: true });
    }""")
    page.wait_for_function("() => state.lastWei && state.lastWei.r", timeout=15000)
    page.wait_for_timeout(400)
    check("结果页上有「存成菜单长图」这一枚", page.evaluate(
        "() => !!document.querySelector('#saveMenuCard')"), True)
    canvas = page.evaluate("""() => {
      const w = state.lastWei;
      const c = drawMenuCard(menuCardData(w.r, w.talk, w.n, ''), menuCardTokens());
      const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let ink = 0, seal = 0;
      for (let i = 0; i < px.length; i += 4) {
        // 只数「画上去的东西」：纸底 RGB 都在 240 上下
        if (px[i] < 200 || px[i + 1] < 200 || px[i + 2] < 200) ink++;
        if (px[i] > 120 && px[i] < 220 && px[i + 1] < 140 && px[i + 2] < 130) seal++;
      }
      return { w: c.width, h: c.height, ink, seal, kb: Math.round(c.toDataURL('image/png').length / 1024) };
    }""")
    check("长图尺寸正好 1080×1920", [canvas["w"], canvas["h"]], [1080, 1920])
    check("画布上真的有字（深色像素 > 2000 个）", canvas["ink"] > 2000, True)
    check("有印章红（不是一张纯灰图）", canvas["seal"] > 200, True)
    check("PNG 体积像一张真图（>30KB）", canvas["kb"] > 30, True)
    check("夜里的纸也画白天的长图（长图是发给别人看的）", page.evaluate("""() => {
      THEME.set('theme', 'dark');
      const w = state.lastWei;
      const c = drawMenuCard(menuCardData(w.r, w.talk, w.n, ''), menuCardTokens());
      const ctx2 = c.getContext('2d');
      // 纸底取三种位置（左上 / 右中 / 底中）：只量一个点会撞上纸边那一条 --paper
      const spots = [[4, 4], [c.width - 8, c.height / 2], [c.width / 2, c.height - 4]].map(
        ([x, y]) => [...ctx2.getImageData(x, y, 1, 1).data].slice(0, 3));
      THEME.set('theme', 'light');
      return spots.map((px) => px.every((v) => v > 230) || (px[1] > 230 && px[2] > 220));
    }"""), [True, True, True])
    page.evaluate("() => document.querySelector('#saveMenuCard').click()")
    page.wait_for_timeout(1200)
    check("按下去真的出了图（没报错、按钮标签回来了）", page.evaluate("""() => {
      const b = document.querySelector('#saveMenuCard');
      return [b.textContent, b.classList.contains('busy')];
    }"""), ["存成菜单长图", False])

    print("\n--- 12. 结果页里的菜名可点进菜谱卡 ---")
    links = page.evaluate("() => [...document.querySelectorAll('#weiResult .dish-link')].map(b => b.dataset.dishlink)")
    check("结果页的菜名做成了按钮（不是死文字）", len(links) > 0, True)
    inLib = page.evaluate("() => [...document.querySelectorAll('#weiResult .dish-link')]"
                          ".every(b => !!allDishes().find(d => d.name === b.dataset.dishlink))")
    check("只有菜库里真有的那几道才做成按钮", inLib, True)
    page.evaluate("() => document.querySelector('#weiResult .dish-link').click()")
    page.wait_for_timeout(300)
    check("点菜名进菜谱详情，且是同一道", page.evaluate(
        "() => [document.querySelector('.screen.on').id, document.querySelector('#dishBody h2').textContent]"),
        ["wei-dish", links[0]])

    print("\n--- 13. 这一路走下来没有 JS 异常 ---")
    check("全程无未捕获异常", [e for e in errors if "pageerror" in e], [])
    if errors:
        for e in errors[:6]:
            print("        " + e)

    ctx.close()
    browser.close()

passed = len([c for c in checks if c[0]])
failed = len(checks) - passed
print(f"\n味笺 v0.6：{passed} 通过 / {failed} 失败")
sys.exit(1 if failed else 0)
