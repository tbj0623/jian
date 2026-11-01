# 「丝滑流畅」不能是一句形容词：把每次点击到画面重画完的耗时量出来，并且盯住主线程长任务。
#
# 量的是桌面 Edge（headless）里的真 DOM，安卓 WebView 会慢一截——所以预算不是「越快越好」，
# 而是按本机实测放约 2~3 倍余量：它抓的是「量级错了」那类回归（多套一层循环、每帧强制重排、
# 把整页重建写成 N 次重建），不是机器今天忙不忙。
#
# 跑：PYTHONIOENCODING=utf-8 python test/perf.playwright.py
#   只想要数字、不想判红：加 --report
import json
import pathlib
import statistics
import sys

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()
REPORT_ONLY = "--report" in sys.argv

# 每项：名字 → (中位数预算 ms, 最慢一次预算 ms)。括号里是 2026-09-20 本机稳定态实测。
# 预算不是「越快越好」，是「别差一个量级」：中位数留 5~25 倍、最慢一次留 2~50 倍。
# 这台机器常年只剩 2GB 空闲（ComfyUI 一个 python 就吃 4.5GB），留太紧就会报假红——
# 而守门报假红比不报更糟。要收紧先 --report 跑几遍看分布。
#
# `换屏 show()` 的「最慢一次」以前写 120ms，本轮实测它是个**假红的制造机**：
# 安静时连跑五遍，中位 5.2~6.4、p95 48.9~52.9、最慢 49.3~55.5（p95 的散布只有 1.1 倍，
# 看着很稳）；可就在刚跑完 gradle、别的会话还在忙的一遍里，中位 16.2、p95 147.5、最慢 169.9。
# 也就是说**整条分布会随机器负载平移 3 倍**——换成 p95 去判照样红，只是换了个统计量而已。
# 所以这一项的分工写清楚：
#   · 中位数（30ms，安静实测 5~16）才是回归探测器——量级错了它先红；
#   · 「最慢一次」放宽到 400ms，只当灾难兜底：一次换屏卡半秒不是负载能解释的；
#   · 「有没有把主线程占死」本来就由下面 LONGTASK 那一条按浏览器自己的 50ms 定义在数，
#     那才是管离群值的仪器。
BUDGET = {
    "首次换屏（冷）":         (120, 120),      # 实测 25
    "换屏 show()":            (30, 400),       # 实测 中位 5~16 / 最慢 49~170（随负载平移）
    "柜子整片重绘 36 件":      (16, 60),        # 实测 0.3 / 0.6
    "搜索一个按键（含重绘）":   (16, 60),        # 实测 0.3 / 0.7
    "言笺重绘 200 条":         (24, 120),       # 实测 3.5~17（同样随负载平移，兜底放宽）
    "言笺搜索一个按键（只改计数）": (6, 30),       # 实测 0.1~0.2（第五十一轮：按键不再整片重建）
    "味笺 12 人重绘":          (16, 60),        # 实测 0.1 / 0.2
    "排这桌（40 道）":         (40, 120),       # 实测 1.6 / 2.2
    "存成长图（画完整张）":     (200, 600),      # 实测 8.3 / 12（无照片；带照片还要加解码）
}
# 一次交互里最不该出现的是「主线程被占死」。50ms 是浏览器判 longtask 的线，
# 这里给 100ms：换屏那几下本来就带布局和绘制，卡过 100ms 才是手指能感觉到的。
LONGTASK_MS = 100

PROBE = """() => {
  window.__perf = { samples: {}, long: 0, longest: 0, tally: false, nol: false };
  try {
    new PerformanceObserver((l) => {
      if (!window.__perf.tally) return;
      for (const e of l.getEntries()) {
        window.__perf.long++;
        window.__perf.longest = Math.max(window.__perf.longest, e.duration);
      }
    }).observe({ type: 'longtask', buffered: true });
  } catch (_) { window.__perf.nol = true; }
  // 长任务只在「稳定态」这一段计数：开机第一帧的绘制本来就是一次性的开销，
  // 它由下面「首次换屏」单独量，混进来的话这道预算就成了糊账。
  window.__startTally = () => { window.__perf.long = 0; window.__perf.longest = 0; window.__perf.tally = true; };
  // warm 次先空跑再计时：第一次付的是排版冷启动、canvas 首次分配这种一次性钱，
  // 量出来的中位数才代表用户连点十下时手感到的那个数。
  window.__bench = (name, n, fn, warm) => {
    for (let i = 0; i < (warm || 0); i++) fn(-1 - i);
    const t = [];
    for (let i = 0; i < n; i++) { const a = performance.now(); fn(i); t.push(performance.now() - a); }
    window.__perf.samples[name] = t; return t.length;
  };
  window.__benchA = async (name, n, fn, warm) => {
    for (let i = 0; i < (warm || 0); i++) await fn(-1 - i);
    const t = [];
    for (let i = 0; i < n; i++) { const a = performance.now(); await fn(i); t.push(performance.now() - a); }
    window.__perf.samples[name] = t; return t.length;
  };
  // saveCard 末尾会点一个 <a download>：拦住它，别在 headless 里滚出一堆文件
  const orig = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () { if (this.download) return undefined; return orig.call(this); };
  return true;
}"""

# 数据铺到各自的实际上限：柜子 36 件是 trimStore 的顶，言笺 200 条也是。
# 量「平均 6 件」没有意义，要量的是用户攒到上限那天。
SETUP = """() => {
  state.onboarded = true;
  state.points = 999;
  state.wardrobe = seedWardrobe();
  const c = ['上衣', '裤装', '裙装', '外套', '鞋', '包'];
  const s = ['夏', '春秋', '冬', '四季'];
  while (state.wardrobe.length < 36) {
    const i = state.wardrobe.length;
    state.wardrobe.push({ id: 'p' + i, name: '压测件' + i + '号（名字故意写长）', cat: c[i % 6],
      color: '#8899aa', worn: i % 9, lastWorn: Date.now() - i * 86400000, season: s[i % 4] });
  }
  state.yanCards = [];
  for (let i = 0; i < 200; i++) {
    state.yanCards.push({ k: ['待办', '要买', '已定', '还没说清'][i % 4],
      line: '第 ' + i + ' 条：明天把材料发给小李并确认时间',
      when: null, who: i % 3 ? null : '小王', speaker: i % 4 ? null : '小红说', done: i % 7 === 0 });
  }
  state.yanAsk = '要不要顺便把发票也带上？';
  state.people = [{ name: '我', chips: [] }];
  for (let i = 0; i < 11; i++) state.people.push({ name: '同行' + i, chips: i % 2 ? ['香菜', '辣'] : [] });
  save(state);
  return [state.wardrobe.length, state.yanCards.length, state.people.length];
}"""

checks = []
errors = []


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def report(page, name):
    """按 BUDGET 判一项；返回样本供调用方核对。"""
    samples = page.evaluate("() => window.__perf.samples[%s] || []" % json.dumps(name, ensure_ascii=False))
    med, mx = statistics.median(samples), max(samples)
    p95 = sorted(samples)[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    print(f"        {name}: n={len(samples)} 中位 {med:.1f}ms  p95 {p95:.1f}ms  最慢 {mx:.1f}ms")
    mb, xb = BUDGET[name]
    check(f"{name}：中位数在 {mb}ms 内", round(med, 1) <= mb, True)
    check(f"{name}：最慢一次在 {xb}ms 内", round(mx, 1) <= xb, True)
    return med, mx


def bench(page, name, js):
    page.evaluate(js)
    return report(page, name)


def abench(page, name, js):
    """异步项：先起测，再等样本落地（不写死等待时间，快机器不多花一秒）。"""
    page.evaluate(js)
    page.wait_for_function(
        "() => window.__perf.samples[%s]" % json.dumps(name, ensure_ascii=False), timeout=90000)
    report(page, name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 430, "height": 940}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.goto(URL)
    page.wait_for_timeout(500)
    page.evaluate(PROBE)
    check("压测数据铺到了上限（36 件 / 200 条 / 12 人）", page.evaluate(SETUP), [36, 200, 12])
    page.wait_for_timeout(300)

    print("\n--- 0. 冷启动那一下（只此一次，不许连本带利）---")
    # 开机到文档就绪，用户在等；这一项量的是「等了多久」，不是稳态手感。
    boot = page.evaluate("""() => {
      const n = performance.getEntriesByType('navigation')[0];
      return n ? Math.round(n.domContentLoadedEventEnd - n.startTime) : 0;
    }""")
    print(f"        导航 → DOMContentLoaded：{boot}ms")
    check("开机文档在 3 秒内就绪", boot <= 3000, True)
    bench(page, "首次换屏（冷）", """() => {
      show('yi');
      window.__bench('首次换屏（冷）', 1, () => show('wei'));
    }""")
    page.evaluate("() => window.__startTally()")

    print("\n--- 1. 点下去那一瞬（稳定态重绘）---")
    bench(page, "换屏 show()", """() => {
      const ids = ['yi', 'wei', 'yan', 'me'];
      window.__bench('换屏 show()', 20, (i) => show(ids[i % 4]), 4);
    }""")
    bench(page, "柜子整片重绘 36 件", """() => {
      show('yi');
      window.__bench('柜子整片重绘 36 件', 20, () => renderCloset(), 4);
    }""")
    bench(page, "搜索一个按键（含重绘）", """() => {
      const el = document.querySelector('#clothSearch');
      const q = ['压', '压测', '压测件', '压测件1', '上衣', '', '鞋', '名字'];
      window.__bench('搜索一个按键（含重绘）', 20, (i) => {
        el.value = q[Math.abs(i) % q.length];
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }, 4);
      el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    yan_paint = bench(page, "言笺重绘 200 条", """() => {
      show('yan');
      window.__bench('言笺重绘 200 条', 12, () => renderYan(), 3);
    }""")
    # 搜索框里每敲一下该有多贵？本轮之前它是「一次整片重建」：200 条的时候按键到下一帧
    # 最坏 139ms，连打四个字就是四帧掉帧——被拖住的还包括刚敲进去那个字本身。
    # 现在按键只改头上那行数字，整片列表延后 140 毫秒。这一项量的就是那一下。
    # 判的是**同一台机器上两者之比**，不是绝对毫秒：绝对数会被机器忙不忙牵着走，
    # 而「按键比整片重建便宜一个量级」这件事在哪个机器上都一样成立。
    ks = bench(page, "言笺搜索一个按键（只改计数）", """() => {
      const el = document.querySelector('#yanSearch');
      const q = ['1', '11', '1', '11'];
      window.__bench('言笺搜索一个按键（只改计数）', 20, (i) => {
        el.value = q[i % q.length];
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }, 4);
    }""")
    # 同一台机器上、相隔几毫秒量的两个数——比值比任何绝对毫秒都稳。
    # 谁要把这一行改回「按键直接 renderYan()」，这一条先红，绝对预算那条只是兜底。
    check(f"敲一下搜索比整片重建便宜一个量级（{ks[0]:.1f}ms 对 {yan_paint[0]:.1f}ms）",
          ks[0] * 3 <= yan_paint[0], True)
    # 把延后的那一次放出去，别把这一屏留在「计数是新的、列表是旧的」那 140 毫秒里
    page.evaluate("() => { const el = document.querySelector('#yanSearch'); el.value = ''; "
                  "el.dispatchEvent(new Event('input', { bubbles: true })); }")
    page.wait_for_timeout(400)
    bench(page, "味笺 12 人重绘", """() => {
      show('wei');
      window.__bench('味笺 12 人重绘', 12, () => renderWeiPeople(), 3);
    }""")

    print("\n--- 2. 从点按钮到出结果（含异步）---")
    abench(page, "排这桌（40 道）", """() => {
      show('wei');
      document.querySelector('#menu').value =
        Array.from({ length: 40 }, (_, i) => ['宫保鸡丁', '水煮鱼', '蒜蓉西兰花', '白切鸡', '酸菜鱼', '花生豆腐', '米饭'][i % 7] + (i + 1)).join('\\n');
      window.__perf.samples['排这桌（40 道）'] = null;
      window.__benchA('排这桌（40 道）', 8, async () => { await runWei(); }, 2);
    }""")
    page.evaluate("""() => {
      const item = { name: '想买的那件', cat: '上衣', color: '#c9b39b', img: '', tone: '暖', pattern: '纯色' };
      return JianAPI.yi(item, state.wardrobe).then((r) => {
        r.new = item; state.lastReport = r; save(state); paintReport(); show('yi-report');
      });
    }""")
    page.wait_for_function("() => state.lastReport && state.lastReport.stamp", timeout=30000)
    abench(page, "存成长图（画完整张）", """() => {
      window.__perf.samples['存成长图（画完整张）'] = null;
      window.__benchA('存成长图（画完整张）', 5, async () => { await saveCard(); }, 2);
    }""")

    print("\n--- 3. 主线程长任务 ---")
    stat = page.evaluate("() => window.__perf")
    print(f"        longtask：{stat['long']} 条，最长 {stat['longest']:.0f}ms")
    if stat["nol"]:
        print("        （这个浏览器不给 longtask 上观察器，本项跳过）")
    else:
        check(f"最长一次主线程占用 <= {LONGTASK_MS}ms（实测 {stat['longest']:.0f}ms）",
              round(stat["longest"], 1) <= LONGTASK_MS, True)
    if errors:
        for e in errors:
            print("   " + e)
    check("压测全程无 JS 运行时错误", errors, [])

    ctx.close()
    browser.close()

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks)-len(bad)} 通过 / {len(bad)} 失败")
sys.exit(1 if bad and not REPORT_ONLY else 0)
