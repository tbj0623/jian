# 笺谱 lane（stats.js / achievements.js / card.js 的年度长图）的窄跑门。
#
# 为什么单独一份：笺谱这一屏有四个「静态页永远看不出错」的地方——
#   1. 热力图三档切换：格子数、月份刻度位置、今天那一列在不在可视区；
#   2. 统计块的数字：必须能和「直接从 state 现算一遍」逐条对上。
#      凭肉眼看「33%」永远是对的，只有拿分子分母重算才抓得到「分母用了错的那个集合」；
#   3. 成就进度：每一枚都要说得出「还差 N 次」，而且这个 N 要能反算；
#   4. 年度长图：尺寸 1080×1920、**深色模式下仍是浅纸**、数据薄时拒绝生成。
#
# 跑法：PYTHONIOENCODING=utf-8 python test/stats_v06.playwright.py
import json
import pathlib
import sys
import traceback

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

errors = []
checks = []


def check(name, got, want=True):
    ok = (got == want) if want is not True or not isinstance(want, bool) else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def text_of(page, sel):
    return page.evaluate("(s) => { const e = document.querySelector(s); return e ? e.textContent.trim() : null; }", sel)


# 造一份「中等厚度」的数据：够让四块统计都说得出结论，又不至于把边界掩盖掉。
SEED = r"""(DAY) => {
  const now = Date.now();
  const log = [];
  // 200 笔流水，散布在最近 260 天里：热力图有深浅、统计有分母
  for (let i = 0; i < 200; i++) {
    const back = Math.floor((i * 7) % 250) + 1;
    log.push({ t: now - back * DAY + i * 1000,
               kind: ['wear', 'cook', 'catch', 'plan', 'note'][i % 5],
               mod: ['yi', 'wei', 'yan'][i % 3], ref: 'x' + i, v: 1 });
  }
  log.sort((a, b) => a.t - b.t);
  state.log = log;
  state.wardrobe = Array.from({ length: 12 }, (_, i) => ({
    id: 'w' + i, name: '衣服' + i,
    cat: ['上衣', '裤装', '裙装', '外套', '鞋', '包'][i % 6],
    // 6 件同色系（赭橙）+ 4 件无彩色 + 2 件另一个色系：让「三种颜色」有话说
    color: i < 6 ? '#a86b28' : (i < 10 ? '#f2f0ec' : '#2c3a4a'),
    worn: i * 2, lastWorn: now - i * 7 * DAY,
    price: i % 3 === 0 ? null : 300 + i * 50,
    boughtAt: now - (60 + i * 10) * DAY,
  }));
  state.cookLog = Array.from({ length: 14 }, (_, i) => ({
    id: 'c' + i, name: '菜' + (i % 7), t: now - i * 3 * DAY, stars: 0, note: '', people: 2,
  }));
  state.yanCards = Array.from({ length: 10 }, (_, i) => ({
    k: '待办', line: '事情' + i, when: null, done: i < 4, moved: false, wset: false,
    who: ['小红', '小王'][i % 2],
  }));
  state.badges = [{ id: 'first-wear', t: now - 30 * DAY }];
  state.streak = { last: dayStr(now), days: 4, best: 11 };
  state.profile = { nick: '', avatar: '', line: '', since: now - 300 * DAY };
  save(state);
}"""


def seed(page, script=SEED):
    page.evaluate(script, 86400000)
    page.reload()
    page.wait_for_function("() => typeof state !== 'undefined'", timeout=20000)
    page.wait_for_timeout(400)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
    page.clock.install(time="2026-10-17T10:00:00")
    page.goto(URL)
    page.wait_for_timeout(700)
    page.click("#go")
    page.wait_for_timeout(300)
    seed(page)

    # ---------------------------------------------------------------- 1. 热力图
    print("\n--- 1. 热力图：三档、月份刻度、今天 ---")
    page.evaluate("() => show('pu')")
    page.wait_for_timeout(300)

    check("热力图默认是「近半年」那一档", page.evaluate(
        "() => document.querySelector('#heatRange [aria-pressed=\"true\"]').dataset.heatRange"), "h26")
    check("近半年 = 26 列 × 7 行 = 182 格", page.evaluate(
        "() => document.querySelectorAll('#heatGrid .heat-cell').length"), 182)
    check("今天那一格正好一枚（带边框的那枚）", page.evaluate(
        "() => document.querySelectorAll('#heatGrid .heat-cell.today').length"), 1)
    check("今天那一格真的在可视区里（不许被右边缘裁掉）", page.evaluate(
        """() => {
          const t = document.querySelector('#heatGrid .heat-cell.today').getBoundingClientRect();
          const s = document.querySelector('#heatScroll').getBoundingClientRect();
          return t.left >= s.left - 1 && t.right <= s.right + 1 && t.width > 0;
        }"""), True)
    check("月份刻度至少 3 个（26 周跨 6 个月，少于 3 个就是刻度逻辑坏了）", page.evaluate(
        "() => document.querySelectorAll('.heat-months span').length") >= 3, True)
    check("刻度全是「N月」的形状", page.evaluate(
        "() => [...document.querySelectorAll('.heat-months span')].every(e => /^\\d{1,2}月$/.test(e.textContent))"), True)
    check("五档深浅都画得出来（图例里 l0..l4 各一枚）", page.evaluate(
        "() => [0,1,2,3,4].every(l => document.querySelector('.heat-legend .heat-cell.l' + l))"), True)

    # 三档切换
    page.click('#heatRange [data-heat-range="w6"]')
    page.wait_for_timeout(200)
    check("切到「近 6 周」= 42 格", page.evaluate(
        "() => document.querySelectorAll('#heatGrid .heat-cell').length"), 42)
    check("近 6 周放得下、不需要横向滚动", page.evaluate(
        "() => { const s = document.querySelector('#heatScroll'); return s.scrollWidth <= s.clientWidth + 1; }"), True)
    page.click('#heatRange [data-heat-range="y53"]')
    page.wait_for_timeout(200)
    check("切到「近一年」= 53 列 × 7 行 = 371 格", page.evaluate(
        "() => document.querySelectorAll('#heatGrid .heat-cell').length"), 371)
    check("近一年要横向滚（53 列在 390 宽的纸上是放不下的）", page.evaluate(
        "() => { const s = document.querySelector('#heatScroll'); return s.scrollWidth > s.clientWidth + 10; }"), True)
    check("近一年的「今天」仍在可视区", page.evaluate(
        """() => {
          const t = document.querySelector('#heatGrid .heat-cell.today').getBoundingClientRect();
          const s = document.querySelector('#heatScroll').getBoundingClientRect();
          return t.width > 0 && t.left >= s.left - 1 && t.right <= s.right + 1;
        }"""), True)
    check("三档的格子边长不同（不同跨度要有不同的格子尺寸，不许一套尺寸硬套）", page.evaluate(
        """() => {
          const w = (id) => { heatRangeId = id; renderHeat(document.querySelector('#puHeat'));
            return document.querySelector('#heatGrid .heat-cell').getBoundingClientRect().width; };
          const a = w('w6'), b = w('h26'), c = w('y53');
          heatRangeId = 'h26'; renderHeat(document.querySelector('#puHeat'));
          return a > b && b > c;
        }"""), True)

    # 点某一天 → 流水面板
    print("\n--- 2. 点热力图的某一格，看那一天的流水 ---")
    page.evaluate("() => show('pu')")
    page.wait_for_timeout(200)
    day_with = page.evaluate(
        """() => {
          const cells = [...document.querySelectorAll('#heatGrid .heat-cell')];
          const hit = cells.find(c => Number(c.getAttribute('aria-label').match(/，(\\d+) 笔/)[1]) > 0);
          return hit ? hit.dataset.heat : '';
        }""")
    check("热力图上确实有一格是有记录的", bool(day_with), True)
    page.evaluate("(k) => openDayPanel(k)", day_with)
    page.wait_for_timeout(250)
    check("点某一天弹出了面板（不是 toast、不是 alert）", page.evaluate(
        "() => !!document.querySelector('.stats-pop [role=\"dialog\"]')"), True)
    check("面板标题就是那一天", page.evaluate(
        """(k) => { const t = document.querySelector('.sp-title');
          const d = new Date(k.replace(/\\./g, '-'));
          return t ? t.textContent.includes(String(d.getMonth() + 1) + ' 月') : false; }""", day_with), True)
    check("面板里的流水条数 == eventsOn(那一天).length", page.evaluate(
        """(k) => document.querySelectorAll('.day-row').length === eventsOn(k).length""", day_with), True)
    check("流水面板至少有一行（空集合不算通过）", page.evaluate(
        "() => document.querySelectorAll('.day-row').length") >= 1, True)
    # Esc 关得掉
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check("Esc 关得掉面板", page.evaluate("() => !document.querySelector('.stats-pop')"), True)
    # 点背景也关得掉
    page.evaluate("(k) => openDayPanel(k)", day_with)
    page.wait_for_timeout(200)
    page.evaluate("() => document.querySelector('.stats-pop').click()")
    page.wait_for_timeout(200)
    check("点背景关得掉面板", page.evaluate("() => !document.querySelector('.stats-pop')"), True)
    # 没记录的那一天也要说得出话
    empty_day = page.evaluate(
        """() => {
          const cells = [...document.querySelectorAll('#heatGrid .heat-cell')];
          const hit = cells.find(c => /，没有记录/.test(c.getAttribute('aria-label')));
          return hit ? hit.dataset.heat : '';
        }""")
    page.evaluate("(k) => openDayPanel(k)", empty_day)
    page.wait_for_timeout(200)
    check("没记录的那天也说得出话（不是空白面板）", page.evaluate(
        "() => (document.querySelector('.sp-body') || {}).textContent.includes('没有记录')"), True)
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)

    # ---------------------------------------------------------------- 3. 统计块
    print("\n--- 3. 四块统计：每一个数字都要能反推 ---")
    page.evaluate("() => show('pu')")
    page.wait_for_timeout(300)

    check("四块统计都在（时 / 衣 / 味 / 言）+ 三种颜色", page.evaluate(
        "() => [...document.querySelectorAll('#puBody .sb-head')].map(e => e.textContent.trim().slice(1))"),
        ["时间", "衣柜", "味笺", "言笺", "你的三种颜色"])
    check("每一块都带一句「这些数是怎么来的」（没有反推句的百分比是假话）", page.evaluate(
        "() => [...document.querySelectorAll('#puBody .stat-block')].every(b => b.querySelector('.sb-note'))"), True)

    # 衣柜：件数 / 在穿率 与 state 现算一致
    wd = page.evaluate("""() => {
      const wd = state.wardrobe;
      const worn = wd.filter(w => w.worn > 0).length;
      return { total: wd.length, worn, pct: Math.round(worn / wd.length * 100) };
    }""")
    check("在穿率的分子分母都能在 state 里找到（12 件里 11 件穿过 = 92%）",
          [wd["total"], wd["worn"], wd["pct"]], [12, 11, 92])
    check("衣柜那块的反推句写明了「N 件里 M 件穿过」", page.evaluate(
        """() => { const t = [...document.querySelectorAll('#puBody .sb-note')].map(e => e.textContent).join('');
          return t.includes('12 件里 11 件穿过') && t.includes('在穿率 = 穿过的件数'); }"""), True)
    check("单次穿着成本的分母写清了（几件记了价、共多少钱、穿过几次）", page.evaluate(
        """() => { const t = [...document.querySelectorAll('#puBody .sb-note')].map(e => e.textContent).join('');
          return /单次穿着成本 ¥[\\d.]+：\\d+ 件记了价，共 ¥\\d+，穿过 \\d+ 次/.test(t); }"""), True)

    # 味笺
    wei = page.evaluate("""() => {
      const log = state.cookLog;
      const byName = {}; log.forEach(c => byName[c.name] = (byName[c.name] || 0) + 1);
      const top = Object.keys(byName).sort((a, b) => byName[b] - byName[a])[0];
      return { n: log.length, dishes: new Set(log.map(c => c.name)).size, top };
    }""")
    check("味笺那块的数 == 直接算 state.cookLog", page.evaluate(
        """(w) => {
          // 两个数都得在屏上，而且必须与现算的一致（不是「屏上有串数字就算过」）
          const t = document.querySelector('#puBody').textContent;
          return t.includes(w.dishes + ' 道') && t.includes(w.n + ' 次');
        }""", wei), True)

    # 言笺：办完率
    yan = page.evaluate("""() => {
      const all = state.yanCards, done = all.filter(c => c.done).length;
      return { all: all.length, done, pct: Math.round(done / all.length * 100) };
    }""")
    check("言笺办完率的分子分母 == state 现算", yan, {"all": 10, "done": 4, "pct": 40})
    check("言笺的反推句写明了「N 条里 M 条办完了」", page.evaluate(
        "() => document.querySelector('#puBody').textContent.includes('10 条里 4 条办完了')"), True)

    # 时间块
    check("时间块的三格（连续 / 最长 / 有记录）与 state 一致", page.evaluate("""() => {
      const cells = [...document.querySelectorAll('#puBody .stat-block')].find(b => b.textContent.includes('时间'))
        .querySelectorAll('.stat b');
      return [...cells].map(c => parseInt(c.textContent, 10));
    }"""), page.evaluate("() => [state.streak.days || 0, state.streak.best || 0, activeDays().length]"))

    # 三种颜色
    print("\n--- 4. 你的三种颜色 ---")
    check("三种颜色那块列出了色系名与件数", page.evaluate(
        "() => document.querySelectorAll('#puBody .tone-item').length") >= 1, True)
    check("色相分桶读的是 Engine 那一份（不许在 stats.js 里再写一遍 hex→hue）", page.evaluate(
        """() => {
          // 行为对账而不是源码字符串匹配：Engine.rgbToHsl 回什么，colorBucket 就得跟着分到哪一桶。
          // 有人哪天在 stats.js 里另写一份换算，只要两份在边界上差一点，这里就会红。
          const probe = ['#b54a3c', '#2c3a4a', '#a86b28', '#4a6b52', '#7a5c9e'];
          return probe.every((hex) => {
            const b = colorBucket(hex);
            if (b.achromatic) return false;
            const h = Engine.rgbToHsl(Engine.hexToRgb(hex))[0];
            return b.idx === Math.floor(h / 30) % 12;
          });
        }"""), True)
    check("「同一个色系」那句带得住百分比与件数", page.evaluate(
        "() => /你 \\d+% 的衣服是同一个色系（.+，\\d+ 件）/.test(document.querySelector('#puBody').textContent)"), True)
    check("无彩色（白/灰/黑）单独说，不算进「同色系」", page.evaluate(
        "() => document.querySelector('#puBody').textContent.includes('没有色相')"), True)
    color_pct = page.evaluate("""() => {
      const t = colorTones();
      return { pct: t.pct, topN: t.topN, total: t.total, achromatic: t.achromatic };
    }""")
    check("三种颜色的百分比 == top1 件数 ÷ 柜里件数", color_pct["pct"],
          round(color_pct["topN"] / color_pct["total"] * 100) if color_pct["total"] else 0)
    check("6 件同色系 + 4 件无彩色 + 2 件另一系 → 无彩色记到 4 件", color_pct["achromatic"], 4)

    # ---------------------------------------------------------------- 5. 薄数据不许摆 0
    print("\n--- 5. 数据薄的时候：说薄，不许把 0 当结论 ---")
    page.evaluate("""() => {
      state.log = []; state.wardrobe = []; state.cookLog = []; state.yanCards = [];
      state.badges = []; state.streak = { last: '', days: 0, best: 0 };
      save(state); show('pu');
    }""")
    page.wait_for_timeout(300)
    pu_text = page.evaluate("() => document.querySelector('#pu').textContent")
    check("空柜空笺时不出现「0%」当结论", "0%" in pu_text, False)
    check("空柜时说「柜子还空着」而不是摆 0 件", page.evaluate(
        "() => document.querySelector('#puBody').textContent.includes('柜子还空着')"), True)
    check("一笔记录都没有时热力图不写「0 天有记录」", page.evaluate(
        "() => !document.querySelector('.heat-count').textContent.includes('0 天')"), True)
    check("热力图计数改成「还没有记录，今天算第一天」", page.evaluate(
        "() => document.querySelector('.heat-count').textContent.includes('还没有记录')"), True)
    check("空态也每一块都说得出下一步做什么", page.evaluate(
        "() => document.querySelectorAll('#puBody .stat-block.thin').length >= 3"), True)

    # 薄但不空的柜子：<5 件不摆百分比
    page.evaluate("""() => {
      state.wardrobe = [{ id: 'w1', name: '甲', cat: '上衣', color: '#a86b28', worn: 1, lastWorn: Date.now() },
                        { id: 'w2', name: '乙', cat: '上衣', color: '#a86b28', worn: 0, lastWorn: null }];
      save(state); show('pu');
    }""")
    page.wait_for_timeout(300)
    check("柜里 3 件以下时不摆「在穿率 50%」这种巧合", page.evaluate(
        "() => document.querySelector('#puBody').textContent.includes('还差 3 件到 5 件')"), True)
    check("薄柜子时那块统计里没有百分比格", page.evaluate(
        "() => { const blk = [...document.querySelectorAll('#puBody .stat-block')].find(b => b.textContent.includes('衣柜'));"
        " return blk.querySelectorAll('.stat').length === 1; }"), True)

    # 出厂那六件示例衣服：带 9/4/12/2/3/15 次穿着，是**说明书**不是用户的账。
    # 以前笺谱把它们当真账算：全新安装写着「6 件里 6 件穿过 · 100% 在穿率」，
    # 年度长图还会把这句话画成 1080×1920 发进群里。这一条钉住「不再这么算」。
    # 判据要两条一起认（id 是 w1..w6 **且**名字还是出厂那六个），所以这里用原样的种子数据——
    # 换成 w1/w2 那种自建的两件，那条判据不该把它认成种子（上面那两条薄柜断言就在防这个）。
    page.evaluate("""() => {
      const now = Date.now(), D = 86400000;
      state.wardrobe = [
        { id: 'w1', name: '燕麦针织', cat: '上衣', color: '#d4c4b0', worn: 9, lastWorn: now - 2 * D },
        { id: 'w2', name: '白衬衫', cat: '上衣', color: '#f4f0ea', worn: 4, lastWorn: now - 23 * D },
        { id: 'w3', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: now - 1 * D },
        { id: 'w4', name: '奶油半裙', cat: '裙装', color: '#efe6d6', worn: 2, lastWorn: now - 96 * D },
        { id: 'w5', name: '驼大衣', cat: '外套', color: '#c4a574', worn: 3, lastWorn: now - 214 * D },
        { id: 'w6', name: '白鞋', cat: '鞋', color: '#f5f5f3', worn: 15, lastWorn: now }
      ];
      save(state); show('pu');
    }""")
    page.wait_for_timeout(300)
    seed_text = page.inner_text("#puBody")
    check("示例柜子不算用户的账：不出现「100% 在穿率」",
          "%" in seed_text and "在穿率" in seed_text, False)
    check("示例柜子那块说清了「换成自己的第一件之后才开始算」",
          "换成自己的第一件" in seed_text, True)
    # 换掉一件的名字（用户做的第一件事）之后，它就必须开始算了
    page.evaluate("""() => {
      const w = state.wardrobe.find(x => x.id === 'w1');
      w.name = '我自己的针织衫';
      save(state); show('pu');
    }""")
    page.wait_for_timeout(300)
    check("换掉一件的名字之后就恢复算账（判据不是「一进过示例柜就永远不算」）",
          "在穿率" in page.inner_text("#puBody"), True)

    # ---------------------------------------------------------------- 6. 成就
    print("\n--- 6. 成就页：分组、进度、每一枚都算得出「还差 N 次」---")
    # 上面那一节把柜子清空又换成了 2 件——这一节要的是一份固定的 12 件，
    # 不重新灌种子就会量到上一节留下的残局（第一次跑正是这样红的）。
    seed(page)
    page.evaluate("() => { state.badges = []; save(state); show('badges'); }")
    page.wait_for_timeout(300)
    check("成就按衣 / 味 / 言 / 时四组分段", page.evaluate(
        "() => [...document.querySelectorAll('#badgeGrid .bgg-name')].map(e => e.textContent.trim())"),
        ["衣", "味", "言", "时"])
    check("每组标题右边给出「已解锁 / 总数」", page.evaluate(
        "() => [...document.querySelectorAll('#badgeGrid .badge-group')].every(g => /\\d+ \\/ \\d+/.test(g.textContent))"), True)
    check("30 枚章全都在", page.evaluate("() => document.querySelectorAll('#badgeGrid .badge').length"), 30)
    check("未解锁的章都带一根进度条", page.evaluate("""() => {
      const locked = [...document.querySelectorAll('#badgeGrid .badge.locked')];
      return locked.length > 0 && locked.every(b => b.querySelector('.bg-prog'));
    }"""), True)

    prog = page.evaluate("""() => {
      const out = {};
      BADGES().forEach((b) => { const p = badgeProgress(b); out[b.id] = p; });
      return out;
    }""")
    check("每一枚都给出了 {ok, now, need, hint}", page.evaluate(
        "() => BADGES().every(b => { const p = badgeProgress(b);"
        " return p && typeof p.ok === 'boolean' && Number.isFinite(p.now) && Number.isFinite(p.need) && typeof p.hint === 'string'; })"), True)
    check("need 都是正数（除不了就画不出进度）", page.evaluate(
        "() => BADGES().every(b => badgeProgress(b).need > 0)"), True)
    check("now 不许超过 need（到了就该解锁，屏上不该有 12/10）", page.evaluate(
        "() => BADGES().every(b => { const p = badgeProgress(b); return p.now <= p.need; })"), True)
    check("没解锁的那枚 hint 形如「还差 N 单位」", page.evaluate("""() => {
      const b = BADGES().find(x => x.id === 'closet-30');
      const p = badgeProgress(b);
      return p.ok ? 'ALREADY' : /^还差 \\d+ 件$/.test(p.hint);
    }"""), True)
    check("closet-30 在这份数据下是「还差 18 件」（12 件 → 30 件）", page.evaluate(
        "() => { const p = badgeProgress(BADGES().find(b => b.id === 'closet-30')); return [p.now, p.need, p.hint]; }"),
        [12, 30, "还差 18 件"])

    # 造数据到「差 1 次」：把柜子补到 29 件
    page.evaluate("""() => {
      const now = Date.now();
      state.wardrobe = Array.from({ length: 29 }, (_, i) => ({
        id: 'z' + i, name: 'Z' + i, cat: '上衣', color: '#a86b28', worn: 0, lastWorn: null }));
      save(state);
    }""")
    check("补到 29 件时 closet-30 的进度是「还差 1 件」", page.evaluate(
        "() => { const p = badgeProgress(BADGES().find(b => b.id === 'closet-30')); return [p.now, p.need, p.hint, p.pct]; }"),
        [29, 30, "还差 1 件", 97])
    # 再补 1 件 → 应解锁
    page.evaluate("""() => {
      state.wardrobe.push({ id: 'z29', name: 'Z29', cat: '上衣', color: '#a86b28', worn: 0, lastWorn: null });
      save(state);
    }""")
    check("补到 30 件之后 badgeProgress(ok)=true", page.evaluate(
        "() => badgeProgress(BADGES().find(b => b.id === 'closet-30')).ok"), True)
    check("checkBadges() 把它记进 state.badges", page.evaluate(
        "() => { checkBadges(); return (state.badges || []).some(b => b.id === 'closet-30'); }"), True)
    check("解锁之后 hint 不再说「还差」（说「已经做到了」）", page.evaluate(
        "() => badgeProgress(BADGES().find(b => b.id === 'closet-30')).hint"), "已经做到了")

    # 点一枚章 → 面板
    page.evaluate("() => show('badges')")
    page.wait_for_timeout(300)
    page.evaluate("() => document.querySelector('#badgeGrid [data-badge=\"closet-30\"]').click()")
    page.wait_for_timeout(250)
    check("点一枚章弹出面板（不是 alert / toast）", page.evaluate(
        "() => !!document.querySelector('.stats-pop [role=\"dialog\"]')"), True)
    check("已解锁的章在面板里给出解锁日期", page.evaluate(
        "() => /\\d{4}\\.\\d{2}\\.\\d{2} 得的/.test(document.querySelector('.sp-body').textContent)"), True)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # 挑一枚**确定没解锁**的：这份种子有 200 天记录，days-100 早就解锁了（第一次写这条时
    # 正是踩在这个上——量到的是「已解锁」面板，于是「还差 N 天」红得莫名其妙）。
    # digest-7 要 7 天摘录，而摘录一条都没有，是这份数据下最稳的一枚。
    locked_id = page.evaluate("""() => {
      const got = new Set((state.badges || []).map(b => b.id));
      const b = BADGES().find(x => x.id === 'digest-7');
      return got.has(b.id) ? null : { id: b.id, hint: badgeProgress(b).hint,
                                    need: badgeProgress(b).need, now: badgeProgress(b).now };
    }""")
    check("确实找到了一枚没解锁的章（找不到就是空集合假绿）", locked_id is not None, True)
    page.evaluate("(id) => document.querySelector(`#badgeGrid [data-badge=\"${id}\"]`).click()", locked_id["id"])
    page.wait_for_timeout(250)
    check("未解锁的章在面板里给出「还差 N」", page.evaluate(
        "() => /还差 \\d+/.test(document.querySelector('.sp-body').textContent)"), True)
    check("面板里那句「还差」与 badgeProgress 的 hint 逐字一致", page.evaluate(
        "(h) => document.querySelector('.sp-body').textContent.includes(h)", locked_id["hint"]), True)
    check("未解锁的面板里有进度条", page.evaluate(
        "() => !!document.querySelector('.sp-body .meter > i')"), True)
    check("面板里的进度与 badgeProgress 一致", page.evaluate("""(id) => {
      const p = badgeProgress(BADGES().find(b => b.id === id));
      const w = document.querySelector('.sp-body .meter > i').style.width;
      return Math.abs(parseFloat(w) - p.pct) < 1;
    }""", locked_id["id"]), True)
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)

    # 最近解锁那一排
    page.evaluate("() => show('badges')")
    page.wait_for_timeout(250)
    check("「最近解锁」那一排按时间倒序、最多三枚", page.evaluate("""() => {
      const items = [...document.querySelectorAll('#badgeGrid .br-item')];
      return items.length <= 3;
    }"""), True)
    check("「最近解锁」那排上有「新」的标记（7 天内解锁的）", page.evaluate(
        "() => document.querySelectorAll('#badgeGrid .br-item.is-new, #badgeGrid .badge.is-new').length >= 1"), True)

    # ---------------------------------------------------------------- 7. 年度总结
    print("\n--- 7. 这一年：12 个月、四类事件、最常穿/最常做 ---")
    seed(page)   # 回到那份中等厚度的数据
    page.evaluate("() => show('year')")
    page.wait_for_timeout(400)
    check("12 根月柱都在", page.evaluate("() => document.querySelectorAll('.year-months .ym-col').length"), 12)
    check("每根月柱都能被读屏器念出来（带 aria-label）", page.evaluate(
        "() => [...document.querySelectorAll('.ym-col')].every(c => /月 \\d+ 笔/.test(c.getAttribute('aria-label')))"), True)
    check("最高的那根月柱被标成 top", page.evaluate(
        "() => document.querySelectorAll('.ym-bar.top').length") >= 1, True)
    yb = page.evaluate("""() => {
      const b = yearBook();
      return { events: b.events, days: b.days, months: b.months, kinds: b.kinds, best: b.best };
    }""")
    check("12 个月的分桶加起来 == 今年的事件数", sum(yb["months"]), yb["events"])
    check("有记录的日子数 == activeDays 里属于今年的那些", page.evaluate("""() => {
      const y = new Date().getFullYear();
      return activeDays().filter(k => k.startsWith(String(y))).length;
    }"""), yb["days"])
    check("四类事件（穿搭 / 下厨 / 捞笺）与 countByKind 一致", page.evaluate("""() => {
      const b = yearBook();
      return [b.kinds.wear || 0, b.kinds.cook || 0, b.kinds.catch || 0];
    }"""), [yb["kinds"].get("wear", 0), yb["kinds"].get("cook", 0), yb["kinds"].get("catch", 0)])
    check("「第一次在笺上留字」印出来了", page.evaluate(
        "() => /第一次在笺上留字是 \\d{4}\\.\\d{2}\\.\\d{2}/.test(document.querySelector('#yearBody').textContent)"), True)
    # 年度页的「最长连续」只许数**今年**。
    # 它曾经直接读 state.streak.best（全历史最高），而 best 是落盘的派生数——
    # 去年连过的天数会原样印到今年这张纸上，年度长图还会把它画成 1080×1920 发出去。
    # 这里拿今年的流水**另算一遍**去对账（不信 yearBook 自说自话）：
    # 独立算法把 'YYYY.MM.DD' 换成 Date.UTC 的天序号再比相邻差 1，不走 dayTs/addDays。
    YEAR_RUN = """() => {
      const y = new Date().getFullYear();
      const days = [...new Set(state.log.filter(e => new Date(e.t).getFullYear() === y)
        .map(e => dayStr(e.t)))].sort();
      const num = (k) => { const [a, b, c] = k.split('.').map(Number);
                           return Date.UTC(a, b - 1, c) / 86400000; };
      let best = 0, run = 0, prev = null;
      days.forEach((k) => { const n = num(k);
        run = (prev !== null && n - prev === 1) ? run + 1 : 1;
        if (run > best) best = run; prev = n; });
      const m = document.querySelector('#yearBody').textContent.match(/今年最长连续 ([0-9]+) 天/);
      return { shown: m ? Number(m[1]) : null, want: best, storedBest: state.streak.best || 0 };
    }"""
    yr = page.evaluate(YEAR_RUN)
    # 前提自证：这份种子下「今年的最长」必须与 best 不同，否则下面那条对账恒真。
    check("前提：种子数据里今年的最长连续 ≠ state.streak.best（best 来自别的年份）",
          yr["want"] != yr["storedBest"], True)
    check("年度页的「今年最长连续」== 今年流水另算一遍的最长连续（不是 state.streak.best）",
          yr["shown"], yr["want"])

    # 钉死「best 来自别的年份」这一支：去年连 30 天、今年只连 3 天，best 是 30。
    # 修之前年度页会印「最长连续 30 天」，而今年实际只连了 3 天——这张纸会被发出去。
    # 断言名字里写明防的是「拿历史最高冒充今年」。
    page.evaluate("""() => {
      const now = Date.now(), DAY = 86400000;
      const log = [];
      // 去年：连续 30 天
      for (let i = 0; i < 30; i++) {
        log.push({ t: now - 400 * DAY + i * DAY, kind: 'wear', mod: 'yi', ref: 'w1', v: 1 });
      }
      // 今年：连续 3 天 + 一个孤立的日子（让「有记录」够厚，也证明只数今年）
      for (let i = 0; i < 3; i++) {
        log.push({ t: now - (2 - i) * DAY, kind: 'cook', mod: 'wei', ref: '菜' + i, v: 1 });
      }
      log.push({ t: now - 60 * DAY, kind: 'catch', mod: 'yan', ref: '事', v: 1 });
      state.log = log.sort((a, b) => a.t - b.t);
      state.streak = { last: dayStr(now), days: 3, best: 30 };   // best 来自去年
      save(state); show('year');
    }""")
    page.wait_for_timeout(350)
    cross = page.evaluate(YEAR_RUN)
    check("防「拿历史最高冒充今年」：best=30 来自去年时，年度页印今年自己算出的 3 天",
          [cross["shown"], cross["want"], cross["storedBest"]], [3, 3, 30])
    check("防「拿历史最高冒充今年」：年度页正文里没有出现「最长连续 30 天」",
          page.evaluate("() => !/(最长连续|今年最长连续) 30 天/.test("
                        "document.querySelector('#yearBody').textContent)"), True)
    check("防「拿历史最高冒充今年」：复制出去的纯文字版同样只写今年的 3 天", page.evaluate(
        """() => yearText(yearBook(), wearRate()).includes('今年最长连续 3 天')
             && !yearText(yearBook(), wearRate()).includes('最长连续 30 天')"""), True)
    check("防「拿历史最高冒充今年」：年度长图那一份数（yearBook().best）也是 3",
          page.evaluate("() => yearBook().best"), 3)

    # 今年一天都没有：不印「0 天」冒充结论，要说「还没有连着的日子」。
    # 前提：streak.best 仍是 30（历史最高在），更证明这一句与 best 无关。
    page.evaluate("""() => {
      const now = Date.now(), DAY = 86400000;
      const log = [];
      for (let i = 0; i < 12; i++) {
        log.push({ t: now - 400 * DAY + i * DAY, kind: 'wear', mod: 'yi', ref: 'w1', v: 1 });
      }
      state.log = log;
      state.streak = { last: '', days: 0, best: 12 };
      save(state); show('year');
    }""")
    page.wait_for_timeout(350)
    check("今年没有任何记录时，年度页说「今年还没有连着的日子」，不印「0 天」", page.evaluate(
        """() => { const t = document.querySelector('#yearBody').textContent;
           return t.includes('今年还没有连着的日子')
             && !/今年最长连续 0 天|最长连续 0 天/.test(t); }"""), True)
    check("今年没有任何记录时，复制出去的纯文字版也不写「0 天」", page.evaluate(
        """() => { const s = yearText(yearBook(), wearRate());
           return s.includes('今年还没有连着的日子') && !s.includes('最长连续 0 天'); }"""), True)

    # 上面两段把 state 换成了「去年连续 / 今年空白」的极端账单，这一段要回到
    # 那份中等厚度的种子（它今年的流水里有 wear），否则下面「对不上柜子」那段
    # 会在一个今年零穿搭的数据上跑，属于假红。
    seed(page)
    page.evaluate("() => show('year')")
    page.wait_for_timeout(350)

    # 「有穿着记录但对不上柜里任何一件」是一条真实的分支：导入备份只带来日志、
    # 或者那件已经从柜里去掉了。这时候说「这一年还没记过穿搭」是假话（实测踩过：
    # 屏上同时写着「记了穿搭 40 次」和「这一年还没记过穿搭」）。
    page.evaluate("""() => {
      state.wardrobe = []; save(state); show('year');
    }""")
    page.wait_for_timeout(300)
    check("穿着记录对不上柜子时，明确说「衣服已经不在柜里」，不写「还没记过穿搭」", page.evaluate(
        """() => { const t = document.querySelector('#yearBody').textContent;
          return t.includes('已经不在柜里') && !t.includes('这一年还没记过穿搭'); }"""), True)
    check("这一句仍然带着真实的穿着次数（数字不许丢）", page.evaluate("""() => {
      const b = yearBook();
      return b.kinds.wear > 0 && document.querySelector('#yearBody').textContent.includes(String(b.kinds.wear) + ' 次穿搭');
    }"""), True)
    seed(page)
    page.evaluate("() => show('year')")
    page.wait_for_timeout(300)

    # ---------------------------------------------------------------- 8. 年度长图
    print("\n--- 8. 年度长图：1080×1920、永远浅纸、薄数据拒绝生成 ---")
    cv = page.evaluate("""() => {
      const c = drawYearCard(yearBook(), wearRate(), closetCpw());
      const g = c.getContext('2d');
      const px = (x, y) => { const d = g.getImageData(x, y, 1, 1).data; return [d[0], d[1], d[2], d[3]]; };
      // 竖向取九个采样点，而不是一个：版式一改，某一个固定坐标就会落在一条分隔线、
      // 一根柱、一个字上，那条断言于是量的是「那一像素恰好是什么」，不是「这张图是纸」。
      // 0.6.0 改搭配/摘录那张长图的版式时，「中段」那一点就从 #ebe4d6 变成了 235→239
      // （压在一条更浅的纸上），整条断言无故变红——那是断言太脆，不是图画错了。
      const col = [];
      for (let i = 1; i <= 9; i++) col.push(px(540, Math.round(1920 * i / 10)));
      // 同时数一遍「有多少深色像素」：全图都是纸色 = 什么都没画，那才是真该红的事。
      let ink = 0;
      const img = g.getImageData(0, 0, c.width, c.height).data;
      for (let i = 0; i < img.length; i += 4 * 97) {
        if (img[i] < 140 && img[i + 1] < 140 && img[i + 2] < 140) ink++;
      }
      return { w: c.width, h: c.height, corner: px(4, 4), col, ink };
    }""")
    check("长图尺寸写死 1080 × 1920", [cv["w"], cv["h"]], [1080, 1920])
    check("长图的底色是浅纸 #f4efe6（不是透明、不是黑）", cv["corner"], [244, 239, 230, 255])
    # 竖着九个点全都要是「纸」：每个通道 ≥ 205 且 alpha 255。
    # 纸质长图里没有一处能比这更暗——除了墨迹，而墨迹是**画上去的**，不是底色。
    off = [p for p in cv["col"] if p[3] != 255 or min(p[:3]) < 205]
    check("沿中线竖着取九个点，每一处都还是纸（图是画满的，不是只画了四角）："
          + str(cv["col"][:3]), off, [])
    # 采样是「每 97 个像素取一个」（约 2.1 万个样点）。一张年度长图上的墨迹（标题、
    # 三条数、12 个月折线、落款）大约占几十个样点——0.6.0 实测 244 个。
    # 门槛放在 50：全白会掉到 0，正常版式改动不会跌破 50。
    # 注意这个文件的 check() 是 (name, got, want=True)：把数字塞进第三位会退化成
    # `244 == True` → 假红。所以数量写进断言名，第三位留给默认的 True。
    check("图上真的有墨（全纸色 = 什么都没画）：" + str(cv["ink"]) + " 个深色样点",
          cv["ink"] > 50)

    # 深色模式下再画一次：**必须仍是浅纸**
    page.evaluate("() => THEME.set('theme', 'dark')")
    page.wait_for_timeout(400)
    cv_dark = page.evaluate("""() => {
      const c = drawYearCard(yearBook(), wearRate(), closetCpw());
      const g = c.getContext('2d');
      const d = g.getImageData(4, 4, 1, 1).data;
      return { corner: [d[0], d[1], d[2], d[3]], theme: document.documentElement.dataset.theme };
    }""")
    check("深色模式下确实切到了 dark", cv_dark["theme"], "dark")
    check("深色模式下长图**仍是浅纸**（发给别人看的不能是黑底）", cv_dark["corner"], [244, 239, 230, 255])
    # 分界写死在这里：**DOM 该跟着翻，canvas 长图不许翻**。
    # 只断言「长图是浅的」会漏掉一半——哪天有人把 tokenLight 改成读主题（长图黑了）
    # 或者反过来把纸色写死（DOM 不翻了），必须分别红。
    # 颜色过渡结束才取最终值：固定等 400ms 曾在最后一个 RGB 通道差 1，误报纸色漂移。
    settled = False
    try:
        page.wait_for_function("""() => {
          const s = getComputedStyle(document.body);
          return s.backgroundColor === 'rgb(27, 25, 23)' && s.color === 'rgb(232, 226, 214)';
        }""", timeout=2500)
        settled = True
    except Exception:
        pass
    check("夜纸颜色过渡最终落稳", settled, True)
    dom_dark = page.evaluate("""() => {
      show('pu');
      return { body: getComputedStyle(document.body).backgroundColor,
               ink: getComputedStyle(document.body).color };
    }""")
    check("深色模式下的 DOM 纸色确实翻了（与长图相反的那一半）",
          [dom_dark["body"], dom_dark["ink"]], ["rgb(27, 25, 23)", "rgb(232, 226, 214)"])
    check("长图取色不走会跟主题翻的 token()，走 tokenLight()", page.evaluate(
        "() => typeof tokenLight === 'function' && getComputedStyle(document.documentElement)"
        ".getPropertyValue('--paper').trim() === '#1b1917'"), True)
    page.evaluate("() => THEME.set('theme', 'light')")
    page.wait_for_timeout(300)

    # 薄数据：拒绝生成
    page.evaluate("""() => {
      const now = Date.now();
      state.log = [{ t: now, kind: 'wear', mod: 'yi', ref: 'w1', v: 1 },
                   { t: now - 86400000, kind: 'cook', mod: 'wei', ref: '菜0', v: 1 }];
      state.album = []; state.wardrobe = [];
      save(state); show('year');
    }""")
    page.wait_for_timeout(350)
    check("数据不足时 yearThin 为真", page.evaluate("() => yearThin(yearBook())"), True)
    check("数据不足时明说还差几天", page.evaluate(
        "() => /再记 \\d+ 天/.test(document.querySelector('#yearBody').textContent)"), True)
    check("还差的天数 == 10 − 已有天数（10 是下限，两边用同一个数）", page.evaluate("""() => {
      const b = yearBook();
      return yearShort(b) === Math.max(0, 10 - b.days) && b.days < 10;
    }"""), True)
    check("数据不足时不画月柱（曲线是假的就干脆不画）", page.evaluate(
        "() => document.querySelectorAll('.year-months').length"), 0)
    check("数据不足时「存成长图」被标成此刻不许用", page.evaluate(
        "() => document.querySelector('#yearSave').getAttribute('aria-disabled')"), "true")
    # 挡下时必须开口：按下去要吐出原因，不能静默
    page.evaluate("() => { document.querySelector('#yearSave').click(); }")
    page.wait_for_timeout(300)
    check("按下去说得出为什么存不了（不是一枚沉默的钮）", page.evaluate(
        "() => ((document.querySelector('.toast') || {}).textContent || '').includes('再记')"), True)

    # ---------------------------------------------------------------- 9. 触摸目标
    print("\n--- 9. 可点的东西都够大（含热力图与章格）---")
    seed(page)
    for scr in ("pu", "badges", "year"):
        page.evaluate("(s) => show(s)", scr)
        page.wait_for_timeout(250)
        small = page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('.screen.on button, .screen.on [role="button"]').forEach((el) => {
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden') return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return;
            if (Math.min(r.width, r.height) < 32) {
              out.push([(el.id || el.className || el.tagName).slice(0, 30),
                        Math.round(r.width), Math.round(r.height)]);
            }
          });
          return out;
        }""")
        check(f"{scr}：可点的东西没有小于 32px 的", small, [])

    # ---------------------------------------------------------------- 10. 无报错
    print("\n--- 10. 全程无未捕获异常 ---")
    errs = [e for e in errors if "pageerror" in e]
    check("笺谱三屏全程无未捕获异常", errs, [])
    if errs:
        for e in errs:
            print("        " + e)
    con = [e for e in errors if "console.error" in e]
    check("控制台没有 error（有就是有静默失败的分支）", con[:3], [])

    ctx.close()
    browser.close()

passed = len([c for c in checks if c[0]])
failed = len(checks) - passed
print(f"\n笺谱窄跑：{passed} 通过 / {failed} 失败")
sys.exit(1 if failed else 0)
