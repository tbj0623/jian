# 真机验收：在安卓 WebView 里跑一遍第十轮的新行为。
#
# 为什么单独一套：Playwright 那三道跑的是桌面 Edge。触摸事件、WebView 的 localStorage、
# Capacitor 的 asset 协议、真实视口宽度——这些只有在装好的 App 里才验得到。
# 上一轮就是靠这条路发现过「桌面看不出来」的问题。
#
# 前置（都是手动一次性的，所以这套不进门禁）：
#   1. 模拟器或真机在线：adb devices 看得到
#   2. 装的是 **debug** 包：release 包默认没开 webContentsDebuggingEnabled，CDP 连不上
#      cd android && cmd //c gradlew.bat assembleDebug && "$ADB" install -r app/build/outputs/apk/debug/app-debug.apk
#   3. App 已经打开在前台（脚本会自己 monkey 拉起来）
#
# 运行：python test/device_verify.py
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CDP = str(pathlib.Path.home() / ".qoder" / "mcp-out" / "cap-cdp.mjs")
OUT = ROOT / ".impeccable" / "review"
PKG = "com.jian.app"
ADB = str(pathlib.Path.home() / "AppData" / "Local" / "Android" / "Sdk"
          / "platform-tools" / "adb.exe")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from device_avd import require_avd  # noqa: E402

checks = []


def packaged_version():
    """装进 APK 的那一份 config.js 里的版本号（`android/.../assets/public/` 是 cap sync 的落点）。
    找不到就退回仓库根那份，并把「退回去了」这件事写在断言名字里，不假装量到了包。"""
    for rel in ("android/app/src/main/assets/public/config.js", "config.js"):
        p = ROOT / rel
        if not p.exists():
            continue
        m = re.search(r'version:\s*"([^"]+)"', p.read_text(encoding="utf-8"))
        if m:
            return m.group(1), "装进包里的那份" if "assets" in rel else "仓库根那份（还没 cap:sync）"
    return None, "两处都没找到"


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def cdp_run(*cmds):
    """跑一串 cap-cdp，返回 (退出码, stdout 行, stderr)。不抛错，给「等冷启动」那种轮询用。"""
    argv = ["node", CDP, "--pkg", PKG]
    for c in cmds:
        argv += c
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=180)
    return p.returncode, (p.stdout or "").splitlines(), (p.stderr or "")


def cdp(*cmds):
    """一次 attach 跑一串命令，返回每步的输出列表。"""
    code, lines, err = cdp_run(*cmds)
    if code != 0:
        print("   cap-cdp 失败：" + (err or "\n".join(lines)).strip()[:400])
        raise SystemExit(2)
    return lines


def wait_ready(timeout=120):
    """App 冷启动之后，WebView 的 devtools socket 还要几秒才起来（实测 8 秒），
    而且第一个 page target 可能仍是没加载完的空白文档（`state` 都还没有）。
    以前这里是一句 sleep(3.0)：重装后第一次跑必然连不上，或者连上了却在空页上求值。
    所以改成轮询到「能连、而且文档真是我们这套前端」为止。"""
    t0 = time.time()
    probe = "(() => (typeof state !== 'undefined' && typeof show === 'function') ? location.href : '')()"
    while time.time() - t0 < timeout:
        code, lines, _ = cdp_run(["eval", probe])
        line = (lines[-1] if lines else "").strip().strip('"')
        if code == 0 and ("localhost" in line or "capacitor" in line):
            return line, time.time() - t0
        time.sleep(2)
    return None, time.time() - t0


def scroll_still(timeout=8.0):
    """等页面滚动停稳。
    show() 里那句 window.scrollTo({top:0}) 撞上 `html { scroll-behavior: smooth }`，
    换屏其实是一段几百毫秒的**滚动动画**（从衣笺的柜子滚回顶部）。而 cap-cdp 的 tap 是
    「先量元素中心、再按坐标落点」：量完那一瞬页面还在往下滑，落点就压在目标**上面**那个元素上。
    实测点第 2 个人的「忌口」，展开的却是第 1 个人，脚本只看到「摊开 0 枚」，像产品坏了。
    真人换屏后不可能在 30ms 内点到那一枚，所以这是脚本要等，不是产品要改。"""
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        cur = (cdp(["eval", "(() => Math.round(scrollY))()"]) or [""])[-1].strip()
        if last is not None and cur == last:
            return True
        last = cur
        time.sleep(0.25)
    return False


HIT = """(sel) => {
  const e = document.querySelector(sel);
  if (!e) return 'no element ' + sel;
  const r = e.getBoundingClientRect();
  const x = r.x + r.width / 2, y = r.y + r.height / 2;
  const hit = document.elementFromPoint(x, y);
  const same = hit && (hit === e || e.contains(hit) || hit.contains(e));
  return same ? 'hit @' + Math.round(x) + ',' + Math.round(y)
              : 'MISS @' + Math.round(x) + ',' + Math.round(y) + ' -> ' +
                (hit ? hit.tagName.toLowerCase() + '.' + hit.className : '什么都没有');
}"""


CENTER = """(sel) => {
  const e = document.querySelector(sel);
  if (!e) return 'no element ' + sel;
  // 滚到**视口中线**，不是「滚进视野」：笺册那一行在 412×915 的真机上正好压在
  // 折叠线以下，`scrollIntoView()` 的默认值只保证露出一个角，元素中心仍然
  // 在屏幕外——`elementFromPoint` 直接返回 null，报出来像「这一行点不动」。
  // 第 50 轮把备份那一格搬到笺册上面之后，这一行比当年更低了。
  e.scrollIntoView({ block: 'center' });
  return 'scrolled';
}"""


def tap_at(sel, name):
    """落点之前先确认「按坐标打到的那个元素，就是选择器指的那一个」。
    不确认的话，打偏只会表现成「这个功能没反应」，永远查不到是点错了地方。"""
    cdp(["eval", f"(({CENTER})({json.dumps(sel)}))"])
    scroll_still()
    line = (cdp(["eval", f"(({HIT})({json.dumps(sel)}))"]) or [""])[-1].strip().strip('"')
    print(f"        {name}：{line}")
    if not line.startswith("hit"):
        check(f"落点命中 {name}", False, True)
        return False
    cdp(["tap", sel])
    return True


# 整段场景在页面里跑完，只回一个报告对象：省掉一次次 attach，也避免中途 App 被切走。
# 结尾那个 () 不能省——cap-cdp 的 eval 只求值表达式，不会替你调用函数。
SCENE = r"""(async () => {
  const r = { ok: true, notes: [] };
  const DAY = 86400000, d = Date.now();
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
  save(state);

  // 1) 改名：就地改，不重建瓷砖
  show('yi'); renderCloset();
  document.querySelector('#closet .item[data-id="a1"]').click();
  const tile = document.querySelector('#closet .item[data-id="a1"]');
  const nm = document.querySelector('#clothName');
  r.hasNameInput = !!nm;
  nm.value = '燕麦开衫';
  nm.dispatchEvent(new Event('change'));
  r.renamed = document.querySelector('#closet .item[data-id="a1"] .tag').textContent;
  r.renamedAria = document.querySelector('#closet .item[data-id="a1"]').getAttribute('aria-label');
  r.tileKept = tile === document.querySelector('#closet .item[data-id="a1"]');
  r.renamedStored = state.wardrobe[0].name;

  // 2) 改品类，手改过的季节不动
  document.querySelector('#clothActions [data-item-cat="外套"]').click();
  r.recatted = state.wardrobe[0].cat;
  r.seasonKept = state.wardrobe[0].season;

  // 3) 删一条 + 撤销
  show('yan'); renderYan();
  r.rows = document.querySelectorAll('#yanOut .check').length;
  r.hasDrop = document.querySelectorAll('#yanOut .check .drop').length;
  document.querySelector('#yanOut [data-drop="1"]').click();
  r.afterDelete = state.yanCards.length;
  r.undoToast = !!document.querySelector('.toast.act button');
  document.querySelector('.toast.act button').click();
  r.afterUndo = state.yanCards.map(c => c.line).join('｜');
  r.noAccidentalCheck = state.yanCards.every(c => !c.done);

  // 4) 键盘：整片重建之后焦点留在原处
  show('yi'); renderCloset();
  const t2 = document.querySelector('#closet .item[data-id="a2"]');
  t2.focus();
  t2.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  r.focusAfterEnter = document.activeElement.dataset ? document.activeElement.dataset.id : null;
  r.selected = state.clothSel;

  // 5) 视口与横向溢出（真机宽度下）
  const de = document.documentElement;
  r.vw = window.innerWidth;
  r.overflow = de.scrollWidth - de.clientWidth;
  r.dpr = window.devicePixelRatio;
  r.wide = matchMedia('(min-width: 900px)').matches;
  // API 35 这台 AVD 是 1080×2400 / DPR 2.625 → CSS 视口 411×914（13/14 的镜像略矮一点）。
  // 这里不钉死那两个数字——钉死它，下一次换 AVD 就红一条与产品无关的检查——
  // 只把「现在是不是窄屏那一档」记下来，给上面 r.wide 那条断言做解释。
  r.narrow = r.vw < 600;

  // 6) 存储真的落在 App 私有目录里
  r.stored = JSON.parse(localStorage.getItem('jian.v1')).wardrobe.map(w => w.name).join('｜');
  r.version = window.JIAN_CONFIG.version;
  r.engine = typeof Engine === 'object' && !!Engine.yi;
  r.card = typeof saveCard === 'function' && typeof drawMagStyle === 'function';
  // 前端没有打包器，插件全靠 window.Capacitor.Plugins 这一个入口摸出来。
  // 名字写错一个字母（Statusbar / FileSytem）不会报错，只会让那条原生能力静默没有——
  // 状态栏图标、分享、写文件、震动、返回键全都在界面上看不出差别。所以在设备上逐个点名。
  const P = (window.Capacitor && window.Capacitor.Plugins) || {};
  const fn = (o, k) => typeof ((o || {})[k]) === 'function';
  r.bridge = {
    statusBar: fn(P.StatusBar, 'setStyle'),
    splash: fn(P.SplashScreen, 'hide'),
    app: fn(P.App, 'minimizeApp'),
    haptics: fn(P.Haptics, 'impact'),
    filesystem: fn(P.Filesystem, 'writeFile'),
    share: fn(P.Share, 'share'),
    prefs: fn(P.Preferences, 'set'),
    // 0.6.0 加的第八个插件：言笺的「到点提醒」全靠它（remind.js 的 notifyPlugin()）。
    // 漏了它，界面上一切正常，只是提醒一条都不会到——正是这段注释开头说的那种静默失败。
    localNotifications: fn(P.LocalNotifications, 'schedule')
  };
  r.ua = navigator.userAgent.slice(-46);
  return r;
})()"""


def main():
    serial = require_avd()
    subprocess.run([ADB, "-s", serial, "shell", "monkey", "-p", PKG, "-c",
                    "android.intent.category.LAUNCHER", "1"],
                   capture_output=True, text=True, timeout=60)

    print("\n--- 连上 WebView ---")
    href, waited = wait_ready()
    print(f"   等了 {waited:.1f} 秒才连上可调试且已加载完的页面")
    if href is None:
        print("   等不到：确认模拟器在线、装的是 debug 包、App 在前台")
        return 1
    line = href
    check("跑的是 App 内的资源（capacitor/localhost，不是桌面 file://）",
          ("localhost" in line) or ("capacitor" in line), True)

    print("\n--- 第十轮的新行为 ---")
    out = cdp(["eval", SCENE])
    raw = "\n".join(out)
    i = raw.find("{")
    if i < 0:
        print("   页面没回报告：" + raw[:400])
        return 1
    r = json.loads(raw[i:])
    check("改名：操作条里有输入框", r["hasNameInput"], True)
    check("改名：瓷砖文字跟着变", r["renamed"], "燕麦开衫")
    check("改名：读屏标签跟着变", r["renamedAria"], "燕麦开衫，上衣，穿过 5 次")
    check("改名：就地改，瓷砖没被重建", r["tileKept"], True)
    check("改名：落库", r["renamedStored"], "燕麦开衫")
    check("改品类", r["recatted"], "外套")
    check("手改过的季节不被冲掉", r["seasonKept"], "春秋")
    check("言笺三行、每行一枚 ×", [r["rows"], r["hasDrop"]], [3, 3])
    check("删一条", r["afterDelete"], 2)
    check("撤销提示出现", r["undoToast"], True)
    check("撤销回到原位", r["afterUndo"], "明天把材料发我｜买一盒药｜周五见")
    check("× 没连带打勾", r["noAccidentalCheck"], True)
    check("回车之后焦点还在瓷砖上", r["focusAfterEnter"], "a2")
    check("回车确实选中了", r["selected"], "a2")
    check("真机宽度下没有横向溢出", r["overflow"], 0)
    check("localStorage 落在 App 里（改名活下来了）",
          r["stored"], "燕麦开衫｜深蓝阔腿｜驼大衣")
    # 以前这里写死 "0.5.2"：下一次升版本它必红，而红的原因不是 App 有问题。
    # 更要紧的是比的对象——拿仓库根目录那份比，正好漏掉「前端改了但没 cap:sync / 没重装」
    # 这一类，而那恰恰是这套真机验收存在的理由。所以比的是**装进包里的那一份**。
    want_ver, where = packaged_version()
    check(f"跑的是装进包里的那份前端（{where}）", r["version"], want_ver)
    check("引擎与长图都在", [r["engine"], r["card"]], [True, True])
    # 0.6.0：七个 → 八个。第八个是 LocalNotifications（言笺提醒的地基）——
    # 它没桥到的表现是「提醒设了、界面显示已设、到点什么都不弹」，界面上看不出来。
    check("八个原生插件在 JS 侧都桥到了", r["bridge"],
          {"statusBar": True, "splash": True, "app": True, "haptics": True,
           "filesystem": True, "share": True, "prefs": True, "localNotifications": True})
    print(f"        视口 {r['vw']}px · DPR {r['dpr']} · 宽窗 {r['wide']} · 窄屏 {r['narrow']}")
    print(f"        UA …{r['ua']}")

    print("\n--- 真机触摸（CDP 派发的是真 touch 事件，不是 click()）---")
    # cap-cdp 的 eval 只求值表达式，所以每条都得是 IIFE（外面那层括号不能省）
    # whoOpen 是 wei.js 的模块状态，活得过一次整套用例：上一遍跑完它停在 [0,1]，
    # 这一遍「之前不摊开」就成了 11 → 假红。所以前置条件自己摆平，别指望 App 是刚开的。
    out = cdp(["eval", "(() => { show('wei'); whoOpen = []; renderWeiPeople(); "
                       "return document.querySelectorAll('#people .card:nth-child(2) [data-c]').length; })()"])
    before = (out[-1] if out else "").strip()
    check("点「忌口」之前不摊开", before, "0")
    tap_at('#people [data-open="1"]', "第 2 个人的「忌口」")
    out = cdp(["eval", "(() => document.querySelectorAll('#people .card:nth-child(2) [data-c]').length)()"])
    check("真触摸之后摊开 11 枚", (out[-1] if out else "").strip(), "11")
    tap_at('#people .card:nth-child(2) [data-c="香菜"]', "「香菜」那枚小签")
    out = cdp(["eval", "(() => JSON.stringify(state.people[1].chips))()"])
    check("真触摸勾中忌口", (out[-1] if out else "").replace('\\"', '"'), '["香菜"]')

    print("\n--- 笺册那一行：真触摸点得动，复制的是当时那整张笺 ---")
    # 复制函数换成记录用的桩（安卓上真剪贴板读不回来），要验的两件事仍然是真的：
    # 一是**真 touch 事件**能不能触发这一行，二是交出去的那段字是不是整张笺。
    # 用言笺来做这一条：它的 quote（追问一句）与 text（整张笺）天然不同，
    # 味笺那两样是同一串话术，拿它测「整张 vs 标题」是白测。
    cdp(["eval", "(() => { state.points = 60; save(state); window.__copied = [];"
                  " window.__realCopy = window.copy;"
                  " window.copy = (t, m) => { window.__copied.push([t, m]); };"
                  " show('yan'); document.querySelector('#demoYan').click(); runYan(); return 1; })()"])
    t0 = time.time()
    while time.time() - t0 < 25:
        n = (cdp(["eval", "(() => state.album.filter(a => a.type === 'yan' && a.text).length)()"])[-1] or "0").strip()
        if n != "0":
            break
        time.sleep(1.0)
    cdp(["eval", "(() => { show('me'); return 1; })()"])
    time.sleep(0.6)
    tags = (cdp(["eval", "(() => JSON.stringify([...document.querySelectorAll('#album .slip')].map(e => e.tagName)))()"])[-1] or "").strip()
    check("笺册每一行都是真按钮", "BUTTON" in tags and "DIV" not in tags, True)
    tap_at("#album [data-slip='0']", "笺册第一行")
    ok = (cdp(["eval", "(() => { const c = window.__copied.at(-1) || ['', ''];"
                       " return String(c[0] === state.album[0].text &&"
                       " state.album[0].text.indexOf('【言笺】') === 0 &&"
                       " state.album[0].text !== state.album[0].quote); })()"])[-1] or "").strip()
    check("真触摸之后复制走的是整张笺（不是标题那一句）", ok, "true")
    tip = (cdp(["eval", "(() => (window.__copied.at(-1) || [0, '（一次都没复制）'])[1])()"])[-1] or "").strip()
    check("提示说的是这一张", tip.strip('"'), "已复制这一张笺")
    cdp(["eval", "(() => { window.copy = window.__realCopy; delete window.__copied;"
                  " delete window.__realCopy; return 1; })()"])

    print("\n--- 上一桌要活过冷启动（WebView 的存储不是内存） ---")
    # 桌面浏览器里 reload 就算测完了；安卓上要杀掉进程再起来，才算「重开还在」。
    # 这一步同时验的是：localStorage 真落到了磁盘，而 Preferences 那份备份没把它带歪。

    def dev_shell(cmd):
        return subprocess.run([ADB, "-s", serial, "shell", cmd], capture_output=True,
                              text=True, encoding="utf-8", timeout=90)

    cdp(["eval", "(() => { state.points = 60; save(state); show('wei');"
                  " document.querySelector('#demoWei').click(); runWei(); return 1; })()"])
    t0 = time.time()
    while time.time() - t0 < 25:
        if (cdp(["eval", "(() => String(!!(state.lastWei && state.lastWei.r)))()"])[-1] or "").strip() == "true":
            break
        time.sleep(1.0)
    n0 = (cdp(["eval", "(() => String(state.lastWei.n))()"])[-1] or "").strip()
    # 上一桌的 runWei 是 async：lastWei 落到 state 时 busy 还没放下，立刻再点会被
    # 「正在忙」挡掉，看起来就像这一桌没被记下来。先等它闲下来。
    t0 = time.time()
    while time.time() - t0 < 8:
        if (cdp(["eval", "(() => String(!busy))()"])[-1] or "").strip() == "true":
            break
        time.sleep(0.5)
    # 再排一桌不同的：下面「点一签把菜单拿回来」要有可分辨的两桌才测得出名堂，
    # 只有一桌时点下去「对了」也说明不了什么
    cdp(["eval", "(() => { const el = document.querySelector('#menu');"
                  " el.value = ['清蒸鲈鱼', '白灼菜心', '米饭', '冬瓜排骨汤'].join(String.fromCharCode(10));"
                  " el.dispatchEvent(new Event('input')); runWei(); return 1; })()"])
    t0 = time.time()
    while time.time() - t0 < 25:
        got = (cdp(["eval", "(() => String((state.weiHist || []).length >= 2))()"])[-1] or "").strip()
        if got == "true":
            break
        time.sleep(1.0)
    check("排过的桌记下了两桌（杀进程之前）", got, "true")
    # 先让 WebView 把 localStorage 提交到磁盘再杀：它是异步提交的，force-stop 太快会把
    # 刚写的东西丢掉（device_deeplink 里同一坑，表现为「深链没生效」的假红）
    dev_shell("input keyevent KEYCODE_HOME")
    time.sleep(2.0)
    dev_shell("am force-stop %s" % PKG)
    time.sleep(1.0)
    dev_shell("monkey -p %s -c android.intent.category.LAUNCHER 1" % PKG)
    wait_ready(timeout=120)
    out = cdp(["eval", "(() => { show('wei'); const s = document.querySelector('#weiResult .sheet');"
                       ' return String(!!s && s.textContent.includes("%s 人 ·")); })()' % n0])
    check("杀掉进程重开，上一桌还在、人数还是当时那一桌的", (out[-1] if out else "").strip(), "true")
    out = cdp(["eval", "(() => String(document.querySelector('#menu').value === state.lastWei.menu"
                       " && document.querySelector('#menu').value.length > 0))()"])
    check("菜单文本也回来了（否则「菜单改过了」那句是谎话）", (out[-1] if out else "").strip(), "true")

    # 排过的桌：杀掉进程重开之后那一签还在，而且**真手指**点一下就把那一桌的菜单拿回来。
    # 桌面浏览器里点的是合成事件；原生壳里点不到的按钮，是一上架就露馅的那种错。
    out = cdp(["eval", "(() => String(document.querySelectorAll('#weiHist [data-hist]').length))()"])
    cnt = (out[-1] if out else "").strip()
    check("重开之后排过的桌还留着（两桌都在，且不超过上限）", cnt in ("2", "3", "4"), True)
    cdp(["eval", "(() => { const e = document.querySelector(\"#weiHist [data-hist='1']\");"
                  " if (e) e.scrollIntoView({ block: 'center' }); return 1; })()"])
    time.sleep(0.8)
    if tap_at("#weiHist [data-hist='1']", "排过的桌第二签（更早那一桌）"):
        time.sleep(1.0)
        out = cdp(["eval", "(() => { const m = document.querySelector('#menu').value;"
                           ' return String(m === state.weiHist[1].menu && m !== state.lastWei.menu); })()'])
        check("真触摸点一签：填回来的是那一桌的菜单，且和当前结果不是同一桌",
              (out[-1] if out else "").strip(), "true")
        out = cdp(["eval", "(() => String(document.querySelector('#weiStale').style.display === 'flex'"
                           " && document.querySelector('#menu').value === state.weiMenu))()"])
        check("拿回来之后当场就说得出「这张是上一版的」，菜单文本也一起记下了",
              (out[-1] if out else "").strip(), "true")

    OUT.mkdir(parents=True, exist_ok=True)
    for screen, name in (("yi", "device-yi"), ("wei", "device-wei"), ("yan", "device-yan")):
        cdp(["eval", f"(() => {{ show('{screen}'); return document.querySelector('.screen.on').id; }})()"])
        cdp(["shot", str(OUT / f"{name}.png")])
    print(f"        截图写到 {OUT}")

    bad = [c for c in checks if not c[0]]
    print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
    for ok, name, got, want in bad:
        print(f"   ✗ {name}  ->  {got}   (期望 {want})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
