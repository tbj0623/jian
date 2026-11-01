# 设备侧的帧耗时基线：perf.playwright.py 量的是桌面 Edge，那是「代理数字」。
# 这台 AVD 的 WebView（Chrome/124）跑在 x86_64 + 软件 GPU 上，比真机快还是慢并不显然，
# 所以「丝滑」要拿目标平台自己的数字说话。
#
# 两样一起量：
#   1. 同一批操作在 WebView 里的 JS 耗时（与桌面那套同名同数据，能直接对比）
#   2. 安卓自己数出来的帧：dumpsys gfxinfo 的「渲染多少帧 / 卡帧百分比」——
#      这才是用户眼睛看到的。JS 花 8ms 但那一帧什么都没画，不算卡；反过来布局重排
#      在合成线程上烧 40ms，JS 侧一点都测不到。
#
# 跑：ANDROID_SERIAL=emulator-5554 PYTHONIOENCODING=utf-8 python test/device_perf.py
#   只要数字不想判红：加 --report
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from device_avd import require_avd                                # noqa: E402
from device_verify import ADB, PKG, cdp, check, checks, wait_ready  # noqa: E402

SERIAL = require_avd()
REPORT_ONLY = "--report" in sys.argv

# 首次跑先看数字，再定预算；这里给的是「比桌面实测慢一个量级才算坏」的量级线。
BUDGET = {
    # 2026-09-20 本机 AVD（API 35 / WebView 124 / x86_64）实测：中位 / 最慢
    "换屏 show()":            (60, 300),      # 14 / 143
    "柜子整片重绘 36 件":       (30, 120),      # 2.4 / 19
    "搜索一个按键（含重绘）":    (20, 80),       # 1.3 / 3.5
    "言笺重绘 200 条":          (60, 200),      # 10.4 / 19
    "味笺 12 人重绘":           (20, 80),       # 0.5 / 2
    "排这桌（40 道）":          (60, 200),      # 10.8 / 17
    "画完这张长图（卡片版）":    (30, 120),      # 0.5 / 0.9（canvas 指令是异步提交的）
    "画完这张长图（杂志版）":    (30, 120),      # 1.6 / 8.5
}
# 卡帧率只打印、不设预算：同一台 AVD、同一套节奏下，系统自带的
# com.android.launcher3 桌面量出来是 59 帧 / 88.14% janky（实测，不是推测）。
# 一台连桌面都画不出不卡帧的机器，拿这个数当门只会得到一条永远红的检查。
# 这台 AVD 上真正可信的是上面那八项 JS 侧耗时。

PROBE = """() => {
  window.__perf = { samples: {} };
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
  const orig = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () { if (this.download) return undefined; return orig.call(this); };
  return true;
}"""

SETUP = """() => {
  state.onboarded = true; state.points = 999;
  state.wardrobe = seedWardrobe();
  const c = ['上衣', '裤装', '裙装', '外套', '鞋', '包'], s = ['夏', '春秋', '冬', '四季'];
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
  state.people = [{ name: '我', chips: [] }];
  for (let i = 0; i < 11; i++) state.people.push({ name: '同行' + i, chips: i % 2 ? ['香菜', '辣'] : [] });
  save(state);
  return [state.wardrobe.length, state.yanCards.length, state.people.length];
}"""


def adb(*args, binary=False):
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, timeout=180,
                          **({} if binary else dict(text=True, encoding="utf-8")))


def shell(cmd):
    return (adb("shell", cmd).stdout or "").strip()


def ev(expr):
    """一次求值，返回值（cap-cdp 的 eval 只吃表达式）。"""
    out = cdp(["eval", "(() => { try { return String(%s); } catch (e) { return 'ERR:' + e; } })()" % expr])
    v = (out[-1] if out else "").strip()
    return v.strip('"') if v.startswith('"') else v


def run_js(stmts):
    out = cdp(["eval", "(() => { try { %s return 'ok'; } catch (e) { return 'ERR:' + e; } })()" % stmts])
    v = (out[-1] if out else "").strip().strip('"')
    if v.startswith("ERR"):
        raise RuntimeError(v[:200])
    return v


def samples(name):
    raw = ev("JSON.stringify(window.__perf.samples[%s] || [])" % json.dumps(name, ensure_ascii=False))
    try:
        return json.loads(raw.strip('"').replace('\\"', '"'))
    except Exception:
        return []


def judge(name, wait_s=6):
    t0 = time.time()
    while time.time() - t0 < wait_s:
        s = samples(name)
        if s:
            break
        time.sleep(0.5)
    s = samples(name)
    if not s:
        check("%s 拿到了样本" % name, False, True)
        return
    med, mx = statistics.median(s), max(s)
    print("        %-22s n=%-3d 中位 %6.1fms  最慢 %6.1fms" % (name, len(s), med, mx))
    mb, xb = BUDGET[name]
    check("%s：中位数在 %dms 内" % (name, mb), round(med, 1) <= mb, True)
    check("%s：最慢一次在 %dms 内" % (name, xb), round(mx, 1) <= xb, True)


print("--- 起 App、铺数据 ---")
shell("am force-stop %s" % PKG)
time.sleep(1)
shell("monkey -p %s -c android.intent.category.LAUNCHER 1" % PKG)
url, took = wait_ready(timeout=150)
if not url:
    print("   连不上 CDP（装的是 debug 包吗？）")
    raise SystemExit(2)
print("   WebView 就绪，用了 %.1f 秒；%s" % (took, url))
ev("(%s)()" % PROBE)      # PROBE / SETUP 都是箭头函数表达式，调用一次才装上助手
seed = ev("(%s)()" % SETUP)
check("设备上数据铺到了上限（36 / 200 / 12）", seed, "36,200,12")   # String(数组) 是逗号串，不是 JSON
time.sleep(1.0)

print("\n--- 1. WebView 里的操作耗时 ---")
run_js("const ids = ['yi', 'wei', 'yan', 'me'];"
       "window.__bench('换屏 show()', 20, (i) => show(ids[Math.abs(i) % 4]), 4);")
judge("换屏 show()")
run_js("show('yi'); window.__bench('柜子整片重绘 36 件', 20, () => renderCloset(), 4);")
judge("柜子整片重绘 36 件")
run_js("""const el = document.querySelector('#clothSearch');
const q = ['压', '压测', '压测件', '上衣', '', '鞋', '名字', '号'];
window.__bench('搜索一个按键（含重绘）', 20, (i) => {
  el.value = q[Math.abs(i) % q.length];
  el.dispatchEvent(new Event('input', { bubbles: true }));
}, 4);
el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true }));""")
judge("搜索一个按键（含重绘）")
run_js("show('yan'); window.__bench('言笺重绘 200 条', 12, () => renderYan(), 3);")
judge("言笺重绘 200 条")
run_js("show('wei'); window.__bench('味笺 12 人重绘', 12, () => renderWeiPeople(), 3);")
judge("味笺 12 人重绘")
run_js("""show('wei');
document.querySelector('#menu').value =
  Array.from({ length: 40 }, (_, i) => ['宫保鸡丁', '水煮鱼', '蒜蓉西兰花', '白切鸡', '酸菜鱼', '花生豆腐', '米饭'][i % 7] + (i + 1)).join('\\n');
window.__benchA('排这桌（40 道）', 8, async () => { await runWei(); }, 2);""")
judge("排这桌（40 道）", wait_s=20)
run_js("""const item = { name: '想买的那件', cat: '上衣', color: '#c9b39b', img: '', tone: '暖', pattern: '纯色' };
window.__yiReady = JianAPI.yi(item, state.wardrobe).then((r) => {
  r.new = item; state.lastReport = r; save(state); paintReport(); show('yi-report');
}); 'started';""")
t0 = time.time()
while time.time() - t0 < 30 and ev("!!(state.lastReport && state.lastReport.stamp)") != "true":
    time.sleep(0.5)
# 量的是 drawCardStyle / drawMagStyle 本身，不是 saveCard()：
# saveCard 在原生壳里会把图交给系统分享面板，那个面板一开，
# 一是不 resolve（await 卡住），二是把后面 gfxinfo 数的帧全搅脏（实测 3 帧 100% 卡）。
run_js("window.__benchA('画完这张长图（卡片版）', 4, async () => { await drawCardStyle(state.lastReport, state.lastReport.new); }, 2);")
judge("画完这张长图（卡片版）", wait_s=60)
run_js("window.__benchA('画完这张长图（杂志版）', 3, async () => { await drawMagStyle(state.lastReport, state.lastReport.new); }, 1);")
judge("画完这张长图（杂志版）", wait_s=60)

print("\n--- 2. 安卓自己数的帧（14 次换屏，每次隔 0.4 秒）---")
shell("dumpsys gfxinfo %s reset" % PKG)
# 一个 JS 循环里连切 24 次屏，合成器只会画一两帧——那样数出来的「卡帧率」是假的。
# 按人手的速度铺开：每次切换之间留 0.4 秒，让换屏动画真的跑完，帧才真的被画出来。
for i in range(14):
    run_js("show(%s);" % json.dumps(["yi", "wei", "yan", "me"][i % 4], ensure_ascii=False))
    time.sleep(0.4)
time.sleep(1.0)
info = adb("shell", "dumpsys", "gfxinfo", PKG).stdout or ""
import re as _re
m = _re.search(r"Total frames rendered:\s+(\d+)", info)
frames = int(m.group(1)) if m else 0
janky_line = [l.strip() for l in info.splitlines() if "Janky frames" in l][:1]
print("   " + (janky_line[0] if janky_line else "没读到 Janky frames 这一行"))
pct = 100.0
if janky_line:
    try:
        pct = float(janky_line[0].split("(")[0].split(":")[1].strip().rstrip("%"))
    except Exception:
        pass
check("这一轮真的画了帧（不是空转）", frames > 20, True)
print("   （卡帧率只记数不作门：本机桌面控件同样节奏下是 88% janky）")
slow = [l.strip() for l in info.splitlines() if "50th percentile" in l or "99th percentile" in l]
for l in slow:
    print("   " + l)

bad = [c for c in checks if not c[0]]
print("\n结果：%d 通过 / %d 失败" % (len(checks) - len(bad), len(bad)))
sys.exit(1 if bad and not REPORT_ONLY else 0)
