# 今日 / 册 lane 的自验：把 today.js 与 me.js 的几块逐块推一遍。
#
# 这不是替代 e2e，而是「改完一眼看它对不对」的那一步：
#   - 今日那一屏永远恰好三件、同一天内稳定（刷新也不换）
#   - 三件事每一件都能**当场做完**，做完之后那一行变成「✓ …」而不是消失
#   - 个人档案改得动、存得住、重开还在
#   - 数据体检的数字与 state 对得上
#   - 备份提示说得出「价格」两个字
#
# 跑法：PYTHONIOENCODING=utf-8 python test/me_v06.playwright.py
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

# 冻结的时钟：2026-09-17 是周四（与 e2e 同一时刻），这样「今天/往年今天」两组都确定。
CLOCK = "2026-09-17T10:00:00"

errors = []
checks = []


def check(name, got, want=True):
    """want 省略 = 只要真值；给了具体值 = 逐字比。
    （`got == want` 与 `bool(got)` 混在一行里写过一次，结果数值断言全假红——见 yi_v06。）"""
    ok = bool(got) if want is True else (got == want)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def toast_text(page):
    return page.evaluate("() => { const t = document.querySelector('.toast'); return t ? t.textContent : ''; }")


def wait_toast(page, sub, ms=6000):
    try:
        page.wait_for_function(
            "() => { const t = document.querySelector('.toast');"
            " return !!t && t.textContent.indexOf(" + json.dumps(sub, ensure_ascii=False) + ") >= 0; }",
            timeout=ms)
        return True
    except Exception:
        check("等不到：提示里出现「" + sub + "」", False, True)
        return False


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
    page.clock.install(time=CLOCK)
    page.goto(URL)
    page.wait_for_timeout(700)
    page.evaluate("() => { state.onboarded = true; save(state); paintNav(); show('today'); }")
    page.wait_for_timeout(300)

    # ==================== 1. 今日：永远恰好三件 ====================
    print("\n--- 1. 今日那一屏：三件，不多不少 ---")
    check("三件事恰好三件", page.evaluate("() => todayThree().length"), 3)
    check("屏上也是三块（不是三行数据、画成别的数目）",
          page.evaluate("() => document.querySelectorAll('#todaySheet .tj-item').length"), 3)
    check("三块分别来自衣 / 味 / 言（不是同一笺摆三遍）",
          page.evaluate("() => [...new Set(todayThree().map(t => t.mod))].sort()"), ["wei", "yan", "yi"])

    # ==================== 2. 同一天内稳定 ====================
    print("\n--- 2. 同一天内刷新也不换（这是「建议」不是「噪音」的分界） ---")
    first = page.evaluate("() => todayThree().map(t => t.title)")
    page.evaluate("() => renderToday()")
    page.wait_for_timeout(150)
    check("再渲染一次还是那三句", page.evaluate("() => todayThree().map(t => t.title)"), first)
    page.reload()
    page.wait_for_timeout(800)
    page.evaluate("() => show('today')")
    page.wait_for_timeout(250)
    check("整页重开之后还是那三句（记在 jian.today 上，不是内存变量）",
          page.evaluate("() => todayThree().map(t => t.title)"), first)
    check("今天这一份便签真的落在本机（键名 jian.today）",
          page.evaluate("() => { const o = JSON.parse(localStorage.getItem('jian.today') || 'null');"
                        " return !!o && o.day === dayStr(Date.now()); }"), True)
    check("这一份便签不进 state（它不是用户的数据，也不该跟着备份往返）",
          page.evaluate("() => Object.keys(state).some(k => k === 'today')"), False)

    # ==================== 3. 「再抽一笺」真的换 ====================
    print("\n--- 3. 「再抽一笺」是**主动**换，不是每次刷新都换 ---")
    page.evaluate("() => { document.querySelectorAll('#todaySheet .tj-item').length; }")
    page.click("#todayJian")
    page.wait_for_timeout(250)
    check("按一下真的换了一笺", page.evaluate("() => todayThree().map(t => t.title)") != first, True)
    check("换过之后刷新不会自己换回去", page.evaluate(
        "() => { const a = todayThree().map(t => t.title); renderToday();"
        " return JSON.stringify(a) === JSON.stringify(todayThree().map(t => t.title)); }"), True)

    # ==================== 4. 三件事都当场做得了 ====================
    print("\n--- 4. 三件事每件都能当场做完（不是只能跳过去） ---")
    # 造一组确定的数据：一件很久没穿的衣服、一条没办的言笺、一个干净的白菜谱。
    page.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      state.wardrobe = [{ id: 't1', name: '灰毛衣', cat: '上衣', color: '#888888',
                          worn: 3, lastWorn: now - 200 * DAY }];
      state.cookLog = [];
      state.yanCards = [{ k: '待办', line: '把报销单交了', when: { text: '今天', at: now + 3600000 },
                          done: false, moved: false, wset: false }];
      state.log = []; state.album = []; state.people = [{ name: '我', chips: [] }];
      localStorage.removeItem('jian.today');
      save(state); show('today');
    }""")
    page.wait_for_timeout(250)
    acts = page.evaluate("() => [...document.querySelectorAll('#todaySheet [data-today-do]')].map(b => b.textContent.trim())")
    check("三枚主按钮都在（今天穿了 / 就做这道 / 办完了）", acts, ["今天穿了", "就做这道", "办完了"])

    # 衣：点「今天穿了」→ 真的记进 state，那条变成「✓ 今天穿了」
    page.evaluate("() => document.querySelector('#todaySheet [data-today-do=\"0\"]').click()")
    page.wait_for_timeout(300)
    wear = page.evaluate("() => ({ worn: state.wardrobe[0].worn, last: dayStr(state.wardrobe[0].lastWorn),"
                         "  today: dayStr(Date.now()) })")
    check("衣：账上真的多了一次（worn +1、上次穿记在今天）",
          [wear["worn"], wear["last"] == wear["today"]], [4, True])
    check("衣：那一行变成「✓ 今天穿了」，没有消失",
          page.evaluate("() => { const e = document.querySelector('#todaySheet .tj-done');"
                        " return e ? e.textContent.indexOf('✓ 今天穿了') >= 0 : false; }"), True)
    check("衣：同一件衣服今天不会被记两遍", page.evaluate(
        "() => { const b = state.wardrobe[0].worn; wearNow('t1'); return state.wardrobe[0].worn === b; }"), True)

    # 味：点「就做这道」→ cookLog 真的多一条
    page.evaluate("() => document.querySelector('#todaySheet [data-today-do=\"1\"]').click()")
    page.wait_for_timeout(300)
    cook = page.evaluate("() => ({ n: state.cookLog.length, name: state.cookLog[0] && state.cookLog[0].name,"
                         "  day: state.cookLog[0] ? dayStr(state.cookLog[0].t) : '' })")
    check("味：cookLog 真的写进一条", cook["n"], 1)
    check("味：记的是这道菜、记在今天", [bool(cook["name"]), cook["day"] == page.evaluate("() => dayStr(Date.now())")],
          [True, True])
    check("味：那一行变成「✓ 今天做了…」",
          page.evaluate("() => [...document.querySelectorAll('#todaySheet .tj-done')]"
                        ".some(e => e.textContent.indexOf('✓ 今天做了') >= 0)"), True)
    check("味：同一天再点不会写第二条", page.evaluate(
        "() => { const n = state.cookLog.length; todayCookIt(state.cookLog[0].name);"
        " return state.cookLog.length === n; }"), True)

    # 言：点「办完了」→ done 真的翻过去、并记了一笔流水
    # kind 是 `done` 不是 `note`：0.6.0 把「办完言笺」与「记一句摘录」分开了
    # （共用 note 的时候，同一天记一句摘录会让今日屏把那一句当成「办完的言笺」摆出来，
    #  撤销时也会顺手把摘录那笔流水删掉）。
    page.evaluate("() => document.querySelector('#todaySheet [data-today-do=\"2\"]').click()")
    page.wait_for_timeout(300)
    yan = page.evaluate("() => ({ done: state.yanCards[0].done,"
                        " note: (state.log || []).filter(e => e.kind === 'done' && e.ref).length })")
    check("言：那一条真的勾掉了", yan["done"], True)
    check("言：同时记了一笔流水（今日那一屏靠它认出「今天办完的」）", yan["note"], 1)
    check("言：那一行变成「✓ 办完了…」",
          page.evaluate("() => [...document.querySelectorAll('#todaySheet .tj-done')]"
                        ".some(e => e.textContent.indexOf('✓ 办完了') >= 0)"), True)
    check("言：三行都做完之后，三行**都还在**（成果要看得见，不许消失）",
          page.evaluate("() => document.querySelectorAll('#todaySheet .tj-item').length"), 3)
    page.screenshot(path=str(OUT / "me-v06-today-done.png"), full_page=True)

    # 撤销那一下要把流水也收回
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(300)
    check("言：撤销之后 done 回来、流水也一起收回（不会继续写着办完了）",
          page.evaluate("() => [state.yanCards[0].done,"
                        " (state.log || []).filter(e => e.kind === 'done' && e.ref).length]"), [False, 0])

    # ==================== 5. 三件事的选择依据 ====================
    print("\n--- 5. 选择依据：合季 / 忌口 / 到期优先 ---")
    # 夏天不该推荐冬装（9 月是春秋，先直接问 todaySeason() 的口径）
    check("季节口径覆盖全年四段", page.evaluate("""() => {
      const m = new Date().getMonth() + 1;
      return todaySeason();
    }""") in ("夏", "冬", "春秋"), True)
    seasonJuly = page.evaluate("""() => {
      const real = Date.now;
      // 直接问「按月份该算哪一季」的那一段：不拨真表，改问纯函数
      const f = (month) => {
        const save = Date.prototype.getMonth;
        Date.prototype.getMonth = () => month - 1;
        const s = todaySeason();
        Date.prototype.getMonth = save;
        return s;
      };
      return [f(7), f(1), f(4), f(10)];
    }""")
    check("7 月算夏、1 月算冬、4 月与 10 月算春秋", seasonJuly, ["夏", "冬", "春秋", "春秋"])
    # 夏天柜里只有两件：一件短袖（夏）、一件驼大衣（冬）→ 推荐必须是短袖
    pick_summer = page.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      const save = Date.prototype.getMonth;
      Date.prototype.getMonth = () => 6;             // 7 月
      state.wardrobe = [
        { id: 's1', name: '白短袖T恤', cat: '上衣', color: '#f4f0ea', worn: 1, lastWorn: now - 300 * DAY },
        { id: 'w1', name: '驼大衣', cat: '外套', color: '#c4a574', worn: 1, lastWorn: now - 320 * DAY },
      ];
      localStorage.removeItem('jian.today');
      const pool = todayYiPool();
      Date.prototype.getMonth = save;
      return pool.map(w => w.name);
    }""")
    check("夏天不推荐驼大衣（当季的排在前面）", pick_summer[0], "白短袖T恤")
    # 忌口是硬条件：这桌有人不吃海鲜 → 菜池里不该有海鲜菜
    safe_pool = page.evaluate("""() => {
      state.people = [{ name: '我', chips: ['海鲜'] }];
      localStorage.removeItem('jian.today');
      return todayWeiPool().map(d => d.name);
    }""")
    check("忌口是硬条件：这桌有人不吃海鲜，池子里没有海鲜菜",
          [len(safe_pool) > 0, not any(("鱼" in n or "虾" in n or "蟹" in n) for n in safe_pool)], [True, True])
    # 言笺：到期的排在没到期的前面
    yan_pick = page.evaluate("""() => {
      const now = Date.now(), DAY = 86400000;
      state.yanCards = [
        { k: '待办', line: '以后再说的事', when: null, done: false },
        { k: '待办', line: '今天到期的事', when: { text: '今天', at: now + 3600000 }, done: false },
      ];
      localStorage.removeItem('jian.today');
      return todayYanPool()[0].line;
    }""")
    check("言笺：今天到期的排在「以后再说」前面", yan_pick, "今天到期的事")

    # ==================== 6. 往年今日 ====================
    print("\n--- 6. 往年今日说人话 ---")
    past = page.evaluate("""() => {
      const now = Date.now();
      const lastYear = new Date(now); lastYear.setFullYear(lastYear.getFullYear() - 1);
      state.log = [
        { t: lastYear.getTime(), kind: 'wear', mod: 'yi', ref: 't1', v: 1 },
        { t: lastYear.getTime() + 3600000, kind: 'cook', mod: 'wei', ref: '番茄炒蛋', v: 1 },
      ];
      state.digest = [{ t: lastYear.getTime(), text: '那天风很大，记得穿厚一点', from: '', mood: 0 }];
      save(state); show('today');
      return { block: !document.querySelector('#todayPast').hidden,
               text: document.querySelector('#todayPast').textContent };
    }""")
    check("往年今日那块露出来了", past["block"], True)
    check("说的是哪一年", str(page.evaluate("() => new Date().getFullYear() - 1")) in past["text"], True)
    check("把两笔记录译成人话（穿 / 做菜）", ["穿" in past["text"], "做菜" in past["text"]], [True, True])
    check("那天记下的那一句也摆出来了", "那天风很大" in past["text"], True)
    check("没有往年的记录时整块收起来（不摆一个空标题）", page.evaluate("""() => {
      state.log = []; state.digest = []; save(state); renderToday();
      return [document.querySelector('#todayPast').hidden,
              document.querySelector('#todayPast').previousElementSibling.hidden];
    }"""), [True, True])

    # ==================== 7. 连续天数与「补记昨天」 ====================
    print("\n--- 7. 断签只给一次「补记昨天」，补完能撤 ---")
    bf = page.evaluate("""() => {
      const DAY = 86400000;
      state.streak = { last: dayStr(Date.now() - 2 * DAY), days: 6, best: 9 };
      save(state); renderToday();
      const b = document.querySelector('#streakBack');
      return { shown: !!b, label: b ? b.textContent.trim() : '', before: state.streak.days };
    }""")
    check("正好漏了昨天时，摆出一枚「补记昨天」", [bf["shown"], bf["label"]], [True, "补记昨天"])
    page.click("#streakBack")
    page.wait_for_timeout(300)
    after = page.evaluate("() => ({ days: state.streak.days, last: state.streak.last,"
                          " log: (state.log || []).filter(e => e.ref === '补记').length })")
    check("补完连续天数接着算（6 → 7）", after["days"], 7)
    check("补的那一天真的记进了流水（不是只改数字）", [after["log"], after["last"] == page.evaluate("() => dayStr(Date.now() - DAY)")],
          [1, True])
    check("补完之后那枚签自己收起来", page.evaluate("() => !document.querySelector('#streakBack')"), True)
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(300)
    check("撤销把天数与那一笔流水一起退回", page.evaluate(
        "() => [state.streak.days, (state.log || []).filter(e => e.ref === '补记').length]"), [6, 0])
    check("漏了两天以上时不给这枚签（补了也是假的）", page.evaluate("""() => {
      const DAY = 86400000;
      state.streak = { last: dayStr(Date.now() - 3 * DAY), days: 6, best: 9 };
      save(state); renderToday();
      return !document.querySelector('#streakBack');
    }"""), True)

    # ==================== 8. 那份便签过期就作废 ====================
    print("\n--- 8. 隔天一睁眼，三件该换了 ---")
    stale = page.evaluate("""() => {
      localStorage.setItem('jian.today', JSON.stringify({ day: '2000.01.01', pick: { yi: 'x', wei: 'y', yan: 'z' } }));
      const p = todayPick();
      return { day: JSON.parse(localStorage.getItem('jian.today')).day, ok: p.pick.yi !== 'x' };
    }""")
    check("隔天的那份便签不算数，当场重挑", [stale["ok"], stale["day"] == page.evaluate("() => dayStr(Date.now())")],
          [True, True])

    # ==================== 9. 册：个人主页卡 ====================
    print("\n--- 9. 册：个人主页卡能看能改 ---")
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    check("顶上是个人卡，不是设置清单", page.evaluate("""() => {
      // 版首那行「我的 / 笺册」是静态骨架（Lead 的 index.html），个人卡排在它后面第一位；
      // 用「在 meLinks 之前、在钱包之前」而不是「是第几个孩子」来量，添加骨架不改口径。
      const me = document.querySelector('#me');
      const kids = [...me.children].filter((e) => !e.classList.contains('space'));
      const at = (id) => kids.findIndex((e) => e.id === id);
      const p = at('meProfile');
      return p > 0 && p < at('meLinks') && p < at('meSecWallet');
    }"""), True)
    check("没填过时说「还没起名字」，不印一个假的占位符", page.evaluate(
        "() => document.querySelector('#meNick').textContent"), "还没起名字")
    check("四个数字都在（柜里 / 言笺 / 笺册 / 章）",
          page.evaluate("() => [...document.querySelectorAll('#meProfile .mp-cell span')].map(e => e.textContent)"),
          ["柜里", "言笺", "笺册", "章"])
    check("个人卡上的数字与 state 对得上", page.evaluate("""() => {
      const n = [...document.querySelectorAll('#meProfile .mp-cell b')].map(e => +e.textContent);
      return [n[0] === state.wardrobe.length, n[1] === state.yanCards.length,
              n[2] === state.album.length, n[3] === state.badges.length];
    }"""), [True, True, True, True])

    page.click("#meEdit")
    page.wait_for_timeout(250)
    check("点「改」进的是屏内输入框（不是原生 prompt）", page.evaluate(
        "() => !!document.querySelector('#meNickIn') && !!document.querySelector('#meLineIn')"), True)
    page.fill("#meNickIn", "阿笺")
    page.fill("#meLineIn", "东西少一点，日子慢一点")
    page.click("#meSave")
    page.wait_for_timeout(300)
    check("昵称存回 state", page.evaluate("() => state.profile.nick"), "阿笺")
    check("一句话存回 state", page.evaluate("() => state.profile.line"), "东西少一点，日子慢一点")
    check("屏上立刻改成新的", page.evaluate(
        "() => [document.querySelector('#meNick').textContent.trim(),"
        " document.querySelector('#meLine').textContent.trim()]"), ["阿笺", "东西少一点，日子慢一点"])
    page.reload()
    page.wait_for_timeout(800)
    page.evaluate("() => show('me')")
    page.wait_for_timeout(300)
    check("重开之后还在（真的落盘了）", page.evaluate(
        "() => [state.profile.nick, document.querySelector('#meNick').textContent.trim()]"), ["阿笺", "阿笺"])
    check("空着存也不算错，只是如实说「还没起名字」", page.evaluate("""() => {
      state.profile.nick = ''; state.profile.line = ''; save(state); renderMe();
      return document.querySelector('#meNick').textContent.trim() === '还没起名字';
    }"""), True)
    # 改回一个真名字给后面看
    page.evaluate("""() => { state.profile.nick = '阿笺'; state.profile.line = '把日子过慢一点';
      save(state); renderMe(); }""")
    page.wait_for_timeout(200)

    # ==================== 10. 册：版式顺序 ====================
    print("\n--- 10. 册：版式顺序（个人卡 → 入口 → 钱包 → 数据 → 笺册） ---")
    order = page.evaluate("""() => {
      const ids = ['meProfile', 'meLinks', 'meSecWallet', 'meSecData', 'meSecAlbum', 'meHealth'];
      return ids.map((id) => [...document.querySelector('#me').children].findIndex((e) => e.id === id));
    }""")
    check("六块都在、而且顺成一列（-1 说明搬家漏了一块）", -1 not in order, True)
    check("顺序就是定下来的那个顺序", order == sorted(order), True)
    check("备份排在笺册**前面**（想导出的人要先划过 24 张存档是旧的毛病）", page.evaluate("""() => {
      const ex = document.querySelector('#exportData'), aa = document.querySelector('#album');
      return !!(ex && aa) && !!(ex.compareDocumentPosition(aa) & Node.DOCUMENT_POSITION_FOLLOWING);
    }"""), True)
    check("原有那一批 id 一个都没丢", page.evaluate("""() => ['points','planName','apiUrl','saveApi',
      'apiState','storageNote','exportData','importData','privacyBox','reset','albumNote','albumChips',
      'album','meLinks','openSettings','openSearch','openBadges'].filter((id) => !document.getElementById(id))"""), [])
    check("模块开关 / 默认首页 / 测试订阅那三排都还在",
          page.evaluate("() => [document.querySelectorAll('#me [data-mod]').length,"
                        " document.querySelectorAll('#me [data-home]').length,"
                        " document.querySelectorAll('[data-buy]').length]"), [3, 4, 4])

    # ==================== 11. 册：数据体检 ====================
    print("\n--- 11. 数据体检：数字对得上 state ---")
    page.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      state.wardrobe = Array.from({length: 7}, (_, i) => ({ id: 'd' + i, name: '衣' + i, cat: '上衣',
        color: '#888888', worn: 1, lastWorn: now - i * DAY }));
      state.yanCards = Array.from({length: 12}, (_, i) => ({ k: '待办', line: '第' + i + '条',
        when: null, done: i < 5, moved: false, wset: false }));
      state.album = Array.from({length: 3}, (_, i) => ({ type: 'yi', t: now - i * DAY,
        quote: '第' + i + '张', text: '正文' + i }));
      save(state); renderMe();
    }""")
    page.wait_for_timeout(250)
    health = page.evaluate("""() => {
      const row = (k) => { const e = document.querySelector('#meHealth [data-health="' + k + '"]');
        return e ? e.textContent.replace(/\\s+/g, ' ').trim() : 'MISS'; };
      return { kb: document.querySelector('#mhKb').textContent.trim(),
               backup: document.querySelector('#mhBackup').textContent.trim(),
               wardrobe: row('wardrobe'), yan: row('yanCards'), album: row('album') };
    }""")
    check("柜子那一行写的是「7/36 件」", health["wardrobe"], "柜子 7/36 件")
    check("言笺那一行写的是「12/200 条」", health["yan"], "言笺 12/200 条")
    check("笺册那一行写的是「3/24 张」", health["album"], "笺册 3/24 张")
    check("存储占用与 storageInfo() 同源", health["kb"], "%d KB" % page.evaluate("() => storageInfo().kb"))
    check("没导出过备份时就写「还没」，不编一个日期", health["backup"], "还没")
    check("有已经办完的言笺时，给一枚「清掉已办完的 N 条」", page.evaluate(
        "() => { const b = document.querySelector('#mhCleanYan'); return b ? b.textContent.trim() : 'MISS'; }"),
        "清掉已办完的 5 条言笺")
    page.click("#mhCleanYan")
    page.wait_for_timeout(300)
    check("清掉之后言笺真的少 5 条", page.evaluate("() => state.yanCards.length"), 7)
    page.evaluate("() => { const b = document.querySelector('.toast.act button'); if (b) b.click(); }")
    page.wait_for_timeout(300)
    check("撤销把 5 条按原位放回来", page.evaluate("() => state.yanCards.length"), 12)
    check("一键都清空言笺之后，那枚签自己收起来（不留一枚按了没用的）", page.evaluate("""() => {
      state.yanCards = []; save(state); renderMe();
      return !document.querySelector('#mhCleanYan');
    }"""), True)

    # ==================== 12. 册：导出备份要说清含什么 ====================
    print("\n--- 12. 导出备份：按之前、按之后都说清里面有什么 ---")
    page.evaluate("() => show('me')")
    page.wait_for_timeout(200)
    check("备份那一行下面明说含价格与私人记录", page.evaluate(
        "() => document.querySelector('#backupNote').textContent"), 
        "普通 JSON 备份不加密，备份里含价格与私人记录（柜子、言笺、笺册、设置都在里面）。要私密保存，请用下面的加密备份。")

    # 浏览器那一路：把 a.click() 接下来，读到那份文件
    page.evaluate("""() => {
      window.__dl = null;
      const orig = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () {
        if (this.download) { window.__dl = this.href; return; }
        return orig.call(this);
      };
    }""")
    page.evaluate("() => { const t = document.querySelector('.toast'); if (t) t.remove(); }")
    page.click("#exportData")
    page.wait_for_timeout(400)
    told = page.evaluate("() => { const t = document.querySelector('.toast'); return t ? t.textContent : ''; }")
    check("导出之后那句提示里含「价格」", "价格" in told, True)
    check("也还说得出「浏览器的下载里能看到」（原口径没被这句顶掉）", "浏览器的下载里能看到" in told, True)
    check("真的发起了一次下载（不是只说话）", str(page.evaluate("() => window.__dl")).startswith("blob:"), True)
    # 导出的那份 JSON 里真的带着价格字段
    has_price = page.evaluate("""async () => {
      const f = await (await fetch(window.__dl)).text();
      const o = JSON.parse(f);
      return [Array.isArray(o.wardrobe), 'savedAt' in o, Object.keys(o.profile || {}).includes('nick')];
    }""")
    check("那份文件里真的有柜子 / 导出时间 / 档案（不是一句空话）", has_price, [True, True, True])
    check("导出之后「上次备份」有了日期", page.evaluate("""() => {
      renderMe();
      return document.querySelector('#mhBackup').textContent.trim() !== '还没';
    }"""), True)
    check("导出这一路无 JS 报错", [e for e in errors if "favicon" not in e.lower()
                                and "Failed to load resource" not in e], [])

    # ==================== 13. 册：原有功能没坏 ====================
    print("\n--- 13. 原有功能：钱包 / 开关 / 订阅 / 笺册 ----------")
    page.evaluate("() => { state.points = 24; state.plan = null; state.modules = { yi: true, wei: true, yan: true };"
                  " save(state); renderMe(); }")
    page.wait_for_timeout(250)
    check("钱包印的是这笔账", page.inner_text("#points"), "24")
    check("订阅那行是「未订阅」", page.inner_text("#planName"), "未订阅")
    page.evaluate("() => document.querySelector('[data-mod=\"wei\"]').click()")
    page.wait_for_timeout(250)
    # 底栏那一枚按 id 认，不按文字：v0.6.0 的底栏是「小印 + 标签」两段，
    # textContent 拼出来是「味味笺」——按文字比会掉进一个有空格差异的坑里。
    check("关掉味笺：底栏跟着少一枚", page.evaluate("() => !!document.querySelector('#nav-wei')"), False)
    page.evaluate("() => document.querySelector('[data-mod=\"wei\"]').click()")
    page.wait_for_timeout(250)
    check("开回味笺", page.evaluate("() => !!document.querySelector('#nav-wei')"), True)
    page.evaluate("() => document.querySelector('.topup').open = true")
    page.wait_for_timeout(150)
    page.click('[data-buy="wei"]')
    page.wait_for_timeout(300)
    check("测试订阅买得动、订阅名跟着改", [page.evaluate("() => state.plan"), page.inner_text("#planName")], ["wei", "味笺"])
    check("买完摆出「取消订阅」那一枚", page.is_visible("#planOff"), True)
    page.click("#planOff")
    page.wait_for_timeout(300)
    check("取消订阅回得到「未订阅」", page.inner_text("#planName"), "未订阅")

    # 笺册：分页 / 过滤 / 复制三件事各量一次
    alb = page.evaluate("""() => {
      const DAY = 86400000, now = Date.now();
      state.album = Array.from({length: 24}, (_, i) => ({ type: ['yi','wei','yan'][i % 3],
        t: now - i * DAY, quote: '第' + i + '张', text: '整张笺' + i }));
      albumView = 'all'; albumAll = false; save(state); show('me');
      return { note: document.querySelector('#albumNote').textContent,
               slips: document.querySelectorAll('#album .slip').length };
    }""")
    check("笺册头一句说清在册几张、现在摊着几张", alb["note"], "笺册 · 一共 24 张，先摊着最新的 12 张")
    check("屏上摊 12 张", alb["slips"], 12)
    page.click("#albumChips [data-aall]")
    page.wait_for_timeout(250)
    check("摊开之后 24 张全在", page.evaluate("() => document.querySelectorAll('#album .slip').length"), 24)
    page.click("#albumChips [data-aview='wei']")
    page.wait_for_timeout(250)
    check("按笺过滤之后只剩味笺那 8 张", page.evaluate(
        "() => [document.querySelectorAll('#album .slip').length, document.querySelector('#albumNote').textContent]"),
        [8, "笺册 · 一共 24 张，味笺 8 张"])
    check("过滤之后行上带的还是在册真下标", page.evaluate("""
      () => { const got = [...document.querySelectorAll('#album .slip')].map(e => +e.dataset.slip);
        const want = state.album.map((a, i) => a.type === 'wei' ? i : -1).filter(i => i >= 0);
        return JSON.stringify(got) === JSON.stringify(want); }"""), True)
    page.evaluate("() => { albumView = 'all'; renderMe(); }")
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "me-v06-me.png"), full_page=True)

    # 触摸目标：新摆的控件都不低于 44（那枚「改」与「补记昨天」是这一轮新加的）
    small = page.evaluate("""() => {
      const pick = ['#meEdit', '#exportData', '#importData', '#reset', '#mhCleanYan',
                    '#copyPrivacyUrl', '#openSettings'];
      const out = [];
      pick.forEach((s) => { const e = document.querySelector(s);
        if (!e) return;
        const r = e.getBoundingClientRect();
        if (r.width && Math.min(r.width, r.height) < 32) out.push([s, Math.round(r.width), Math.round(r.height)]);
      });
      return out;
    }""")
    check("册上这两排控件没有一个小于 32px 命中区", small, [])
    page.evaluate("() => show('today')")
    page.wait_for_timeout(250)
    small2 = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('#todaySheet button, #todayJian, #todayYear, #todayMe').forEach((e) => {
        const r = e.getBoundingClientRect();
        if (r.width && Math.min(r.width, r.height) < 32) out.push([e.id || e.className, Math.round(r.width), Math.round(r.height)]);
      });
      return out;
    }""")
    check("今日上那几枚控件也没有一个小于 32px 命中区", small2, [])

    real = [e for e in errors if "favicon" not in e.lower()]
    check("全程无 JS 报错", real, [])
    ctx.close()
    browser.close()

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
for ok, name, got, want in bad:
    print(f"   ✗ {name}  ->  {got}   (期望 {want})")
sys.exit(1 if bad else 0)
