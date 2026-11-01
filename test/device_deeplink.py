# 深链、快捷方式、夜间模式：三件只有在设备上才算数的事。
#
# 为什么要在设备上做：桌面长按图标弹出来的那条快捷方式，落到系统里就是
#   am start -a android.intent.action.VIEW -d jian://screen/<哪一笺>
# ——和测试里伪造 window.Capacitor 相比，这条走的是清单里的 intent-filter、
# Bridge 的 intentUri、singleTask 的 onNewIntent 整条真链路。
# 夜间模式更没法在浏览器里量：会不会被算法反色（纸变黑、朱印变青）取决于
# WebView 拿到 forceDarkAllowed 之后怎么渲染，只能截图看像素。
#
# 跑：ANDROID_SERIAL=emulator-5554 PYTHONIOENCODING=utf-8 python test/device_deeplink.py
#   前提：调试包已装（release 包没有 CDP，量不了 JS 侧）
import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from device_avd import require_avd                          # noqa: E402
from device_verify import ADB, PKG, ROOT, cdp, check, checks, wait_ready  # noqa: E402

SERIAL = require_avd()
SHOTS = ROOT / "test" / "screens"
SHOTS.mkdir(parents=True, exist_ok=True)
EVAL_SCREEN = "(() => { const s = document.querySelector('.screen.on'); return s ? s.id : ''; })()"


def sh(*args, binary=False):
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True,
                          timeout=180, **({} if binary else dict(text=True, encoding="utf-8")))


def shell(cmd):
    return (sh("shell", cmd).stdout or "").strip()


def js(expr):
    """只求值一个表达式（cap-cdp 的 eval 走的是 String(...) 那条壳，塞语句会语法错）。"""
    out = cdp(["eval", "(() => { try { return String(%s); } catch (e) { return 'ERR:' + e; } })()" % expr])
    v = (out[-1] if out else "").strip()
    return v.strip('"') if v.startswith('"') else v


def run(stmts):
    """跑一段语句（赋值 + 调用混着写），只看有没有抛。"""
    out = cdp(["eval", "(() => { try { %s return 'ok'; } catch (e) { return 'ERR:' + e; } })()" % stmts])
    v = (out[-1] if out else "").strip().strip('"')
    if v.startswith("ERR"):
        print("   页面里报错了：" + v[:200])
    return v


def screen():
    return js("document.querySelector('.screen.on') ? document.querySelector('.screen.on').id : ''")


# 一次往返同时拿「哪一屏 + toast 上那句」：toast 只活 5.2 秒，分两次 cdp 调就没了
STATE = ("JSON.stringify([document.querySelector('.screen.on') ? document.querySelector('.screen.on').id : '',"
         "document.querySelector('.toast') ? document.querySelector('.toast').textContent : ''])")


def wait_state(timeout=25):
    """boot() 是 async：restoreNativeBackup 没回来之前一屏都没有亮。
    连上 CDP ≠ 画完了，所以要等到有屏为止。返回 (屏, toast)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        raw = js(STATE).strip()
        if raw.startswith('"') or raw.startswith("["):
            try:
                scr, toast = json.loads(raw.strip('"').replace('\\"', '"'))
            except Exception:
                scr, toast = "", ""
            if scr:
                return scr, toast
        time.sleep(0.6)
    return "", ""


def wait_screen(timeout=25):
    return wait_state(timeout)[0]


def cold_land(link=None):
    """冷启动（可带快捷方式地址）之后最终落在哪一屏。
    落在引导页就替用户点一次「进入」再看——因为「刚写的 onboarded 有没有落盘」
    本来就不保证，稳定的契约是「最多点一次进入，必须到位」。"""
    relaunch(link)
    scr, _ = wait_state()
    if scr == "onboard":
        run("document.querySelector('#go').click();")
        scr, _ = wait_state()
    return scr


def settle():
    """刚写完的 localStorage 要先落盘再杀进程：WebView 是异步提交的，
    立刻 force-stop 会把这一两秒里的写入丢掉（实测：引导标记没落盘，
    下一次冷启动又回到引导页，于是这条用例看起来像「深链没生效」）。"""
    shell("input keyevent KEYCODE_HOME")
    time.sleep(2.0)


def relaunch(via_link=None):
    """force-stop 之后重开：要么走快捷方式那条 VIEW intent，要么走普通启动。"""
    settle()
    shell("am force-stop %s" % PKG)
    time.sleep(1.0)
    if via_link:
        shell("am start -a android.intent.action.VIEW -d '%s' -n %s/.MainActivity" % (via_link, PKG))
    else:
        shell("monkey -p %s -c android.intent.category.LAUNCHER 1" % PKG)
    url, took = wait_ready(timeout=120)
    if not url:
        print("   WebView 没起来（CDP 连不上），后面没法判")
        raise SystemExit(2)
    return url


print("--- 1. 冷启动带快捷方式地址（桌面上长按那一下的等价物）---")
# 引导优先：快捷方式答的是「去哪一笺」，不该替用户回答「打开即是哪一笺」，
# 所以没走完引导时先给引导，进去之后必须落在它指的那一笺。
# 到底给不给引导，取决于上一秒写的 onboarded 有没有赶在 force-stop 前落盘——
# 那个不保证（见 settle 的注释），所以这里断的是「最多点一次进入就要到位」这条契约。
relaunch()      # 先把进程拉起来：上一节可能刚重装过，这时候进程是死的
wait_screen()
home = js("state.home")     # 期望值从设备上那份状态里读，不写死
check("冷启动带 jian://screen/yan → 言笺", cold_land("jian://screen/yan"), "yan")
check("冷启动带 jian://screen/wei → 味笺", cold_land("jian://screen/wei"), "wei")
check("认不出的地址不乱跳，落在首页 %s" % home, cold_land("jian://screen/nope"), home)
check("不带地址的普通启动也落在首页", cold_land(), home)

print("\n--- 2. 热启动：singleTask 要把地址递给正在跑的那张纸，不许重载 ---")
relaunch()
wait_screen()
run("window.__warm = 1; show('yi');")
check("先落回衣笺", screen(), "yi")
shell("am start -a android.intent.action.VIEW -d 'jian://screen/wei' %s" % PKG)
time.sleep(2.5)
check("热启动换到了味笺", wait_screen(), "wei")
# 页面一旦重载，window.__warm 就没了。这条是「有没有重新走一遍开机」的判据。
check("是换屏，不是重载（JS 上下文还在）", js("typeof window.__warm"), "number")

print("\n--- 3. 快捷方式指着被关掉的模块：不能硬开 ---")
run("state.modules.yan = false; save(state); paintNav();")
# toast 只活 5.2 秒，而从主机起一次 node + 连 CDP 就要一两秒——按时间去「撞」它，
# 在这台机器上时灵时不灵。改成把 toast 收集起来：读的时候不看时机，只看有没有说过。
run("window.__toasts = []; const _t = window.toast;"
    " window.toast = (x) => { window.__toasts.push(x); return _t(x); };")
shell("am start -a android.intent.action.VIEW -d 'jian://screen/yan' %s" % PKG)
time.sleep(2.0)
check("送去的是「我的」", wait_screen(), "me")
check("话说清楚了", js("window.__toasts.join('|')"), "这一笺已经关掉了，在下面重新打开")
run("window.toast = undefined; delete window.__toasts;")
run("state.modules.yan = true; save(state); paintNav();")

print("\n--- 4. 桌面快捷方式条目（系统注册表里查得到才算挂上）---")
# 取法在 API 35 上换过一次（实测）：
#   · `dumpsys shortcut` 把所有包的条目**混排**，而且多了 `PackageInfo:` / `IsShadow:`
#     这些 13/14 上没有的区段。按 `ShortcutInfo {id=` 切仍然能用，但整份 dump 有一万多行，
#     在这台 AVD 上要 8~12 秒，还容易被别的包的同名字段串味。
#   · `cmd shortcut get-shortcuts <pkg>` 只出这一个包的，格式与 dumpsys 里那一段逐字相同
#     （实测同一条 `ShortcutInfo {id=…` 行），快且不会串味。
# 两条都试：老的走 dumpsys，新的走 cmd；只要有一条读得到就用它。
def shortcut_dump():
    d = sh("shell", "cmd", "shortcut", "get-shortcuts", PKG).stdout or ""
    if "ShortcutInfo {id=" not in d:
        # 兜底：老路子。API 33/34 上 get-shortcuts 是后来才有的子命令，
        # 有些 ROM（以及极老的 build-tools 镜像）会回一段 usage。
        d = sh("shell", "dumpsys", "shortcut").stdout or ""
    return d


dump = shortcut_dump()
got = {}
# 整份 dump 里几十个包的条目混在一起，按区段切行会串味（实测把别的 App 的
# manifest-shortcut-* 也算了进来），所以按每条自己的 packageName 认领。
for part in dump.split("ShortcutInfo {id=")[1:]:
    # dumpsys 把 Intent 的 URI 打成 dat=jian://screen/...（路径被系统省略），
    # 所以这里只能对到协议头；「哪个地址开哪一屏」由上面 1~3 节在真链路里验。
    if "packageName=" + PKG not in part:
        continue
    got[part.split(",", 1)[0].strip()] = part.split("iconRes=")[0]
# `cmd shortcut get-shortcuts` 已经把范围收窄到一个包，个别 ROM 仍然不打印
# packageName= 那一行；那种情况下整份都是我们的，不该因此判成「一条都没有」。
if not got and "ShortcutInfo {id=" in dump:
    for part in dump.split("ShortcutInfo {id=")[1:]:
        got[part.split(",", 1)[0].strip()] = part.split("iconRes=")[0]
print("   系统里这个包的快捷方式：" + "、".join(sorted(got)) + ("（一条都没有）" if not got else ""))
for sid in ("yi", "wei", "yan", "today", "note"):
    body = got.get(sid, "")
    check("「%s」这枚已注册且指向 MainActivity + jian://screen/" % sid,
          "com.jian.app/.MainActivity" in body and "jian://screen/" in body, True)
    lab = re.search(r"shortLabel=([^,\n]+)", body)
    # API 35 的标签形状是 `shortLabel=过一件衣, resId=2131…[shortcut_yi_short]`：
    # 中文在，但**一定**跟着 resId，13/14 上有些 ROM 只给 resId 不给字面量。
    # 所以要判的是「拿到了中文」而不是「没有 res/ 前缀」——后者在新格式里永远为假。
    check("「%s」的短标签取到了中文（不是 res/0x…）" % sid,
          bool(lab) and bool(re.search(r"[\u4e00-\u9fff]", lab.group(1))), True)
# 0.6.0：三枚 → 五枚。多出来的 today（看今天）与 note（记一笔，地址带 ?new=1）也是
# 真实用到的入口，不再是「设计里的三枚」。这条断言盯的是**没有模板残留**
# （Android Studio 模板会带 Share/AppInfo 那几枚），不是盯数量本身——
# 数量由上面那两行的逐枚检查兜住：少一枚上面就少一对 ok。
check("只有设计里的五枚（没有模板残留）", sorted(got), ["note", "today", "wei", "yan", "yi"])

print("\n--- 5. 夜间模式：纸有两张，白天那张与夜里那张都要对得上 CSS ---")
cap = SHOTS / "night-paper.png"


def css_papers():
    """从 CSS 里**读**出两张纸色，而不是在测试里再写死一遍。

    0.6.0 之前这里断言的是「夜里主色仍是纸色、且与亮色一致」——那是 0.5.x 的口径，
    当时只有一个主题、靠 forceDarkAllowed 挡住反色。0.6.0 起有了真的夜纸
    （styles-v06.css 的 dark 主题覆盖 --paper），夜里就该是深色纸；
    再按旧口径断言「必须和白天一样」，守的是一条已经作废的事实。
    改成守「两处色值一致」：CSS 说夜纸是什么，截图里就该是什么。
    这样它既能抓「夜间被算法反色成纯黑」，也能抓「CSS 改了纸色、原生 res 没跟」。"""
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    v06 = (ROOT / "styles-v06.css").read_text(encoding="utf-8")
    light = re.search(r"--paper:\s*(#[0-9a-fA-F]{6})", css)
    darkblk = re.search(r':root\[data-theme="dark"\]\s*\{([\s\S]*?)\}', v06)
    dark = re.search(r"--paper:\s*(#[0-9a-fA-F]{6})", darkblk.group(1) if darkblk else "")
    return ((light.group(1) if light else None), (dark.group(1) if dark else None))


CSS_LIGHT, CSS_DARK = css_papers()
hx = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))            # noqa: E731


def sample_when_night(on):
    """把系统切到指定夜间状态、重开 App、截一帧，然后看像素。
    取「整屏最多的那个颜色」当纸色，而不是按坐标猜某块背景——按坐标会被
    正好压在上面的那枚墨色按钮骗到。反色一旦发生，这个主色直接变成近黑。"""
    shell("cmd uimode night %s" % ("yes" if on else "no"))
    time.sleep(1.5)
    relaunch()
    # 截之前把画面钉在衣笺上：墨占比是「屏上有没有字」的代理指标，
    # 落在引导页还是落在柜子上，数字差一个量级，预算就没法定。
    run("state.onboarded = true; show('yi');")
    time.sleep(1.5)
    blob = sh("exec-out", "screencap", "-p", binary=True).stdout
    with open(cap, "wb") as fh:
        fh.write(blob)
    from PIL import Image
    im = Image.open(cap).convert("RGB")
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]          # noqa: E731
    # getcolors 一次拿到「颜色 → 出现次数」，比 list(getdata()) 省一整个像素数组，
    # 也躲开 Pillow 那个 getdata 的 DeprecationWarning
    cols = small.getcolors(small.width * small.height + 1) or []
    total = sum(n for n, _ in cols) or 1
    _, paper = max(cols, key=lambda nc: nc[0])
    dark_share = sum(n for n, c in cols if lum(c) < 120) / total
    light_share = sum(n for n, c in cols if lum(c) > 180) / total
    return {"纸": paper, "墨占比": round(dark_share, 4), "亮占比": round(light_share, 4),
            "尺寸": im.size}


# 两格地板：读不出 CSS 里的纸色就等于这一节在比空气（和 store_claims 那两道地板同一手法）
check("从 styles.css 读得到白天的纸色（读不出来 = 这一段在量空气）", bool(CSS_LIGHT), CSS_LIGHT)
check("从 styles-v06.css 读得到夜里的纸色", bool(CSS_DARK), CSS_DARK)

light = sample_when_night(False)
dark = sample_when_night(True)
print("   亮色：%s（CSS %s）" % (light, CSS_LIGHT))
print("   夜间：%s（CSS %s）" % (dark, CSS_DARK))
# 判「系统切到夜间了」不能看 `settings get secure ui_night_mode`：
#   13/14 上它是 "2"（UI_NIGHT_MODE_YES），**没有任何人设过时是 "null"**；
#   API 35 的 AVD 实测就是 null，而那时 `cmd uimode night` 照样回 `Night mode: yes`。
# 用 secure 那个值当判据会在「刚起机、从没切过夜间」时红一条与产品无关的检查。
# 真正的判据分两层：上面 sample_when_night(True) 已经让系统切过去了，
# 这里再向 UiModeManager 本人确认一次。
night_now = shell("cmd uimode night")
check("系统确实切到了夜间（不然这一段是白测）", "yes" in night_now.lower(), night_now)
check("白天的主色就是 CSS 那张纸（三个通道都不差过 12）",
      bool(CSS_LIGHT) and max(abs(a - b) for a, b in zip(light["纸"], hx(CSS_LIGHT))) <= 12,
      True)
check("夜里的主色就是 CSS 规定的那张夜纸（差过 12 就是原生 res 与 CSS 分家了）",
      bool(CSS_DARK) and max(abs(a - b) for a, b in zip(dark["纸"], hx(CSS_DARK))) <= 12,
      True)
check("夜纸确实是深色（不是把白纸又画了一遍）",
      (0.299 * dark["纸"][0] + 0.587 * dark["纸"][1] + 0.114 * dark["纸"][2]) < 80, True)
check("两张纸不是同一个颜色（不然这套主题开关是空的）",
      bool(CSS_LIGHT) and bool(CSS_DARK) and hx(CSS_LIGHT) != hx(CSS_DARK), True)
# 夜里字在纸上的对比度：主色是夜纸、字是浅墨，所以「深色像素占比」不再是指标，
# 换成「亮色像素占比」——反色一旦发生（夜纸被翻成近白、浅墨被翻成近黑），这一项会反过来。
# 0.004 这个地板与白天那条是同一个数：它只要求「屏上确实有一片与纸不同色的字」，
# 不是行数预算，所以两档共用同一个量级。
check("白天有字（深色像素占比够）", light["墨占比"] > 0.004, True)
check("夜里也有字（浅墨压在夜纸上，亮色像素占比够）", dark["亮占比"] > 0.004, True)
shell("cmd uimode night no")
time.sleep(1.5)
relaunch()
check("切回亮色后界面照常（截图 %s）" % cap.name, cold_land() in ("yi", "wei", "yan"), True)

print("\n--- 6. 系统分享接收：冷启动与热启动两条都要真的到 ---")
# 为什么这条要在设备上：整条链路（清单里的 intent-filter → singleTask 的 onCreate/onNewIntent
# → WebView 的 evaluateJavascript → share.js 的 __jianShare）没有任何一段在浏览器里存在。
# 两条路必须分开验：「冷启动那条能用、热启动那条丢内容」是这套壳最经典的坏法，
# 因为热启动走的是 onNewIntent，只写 onCreate 的人根本不会发现。
SHARE_JS = "(() => { const el = document.querySelector('#yanText'); return el ? el.value : 'NO_EL'; })()"


def share(text):
    sh("shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "text/plain",
       "--es", "android.intent.extra.TEXT", text, "-n", "com.jian.app/.MainActivity")


def wait_page(timeout=60):
    """force-stop 之后 CDP 要等 WebView 起来才能连（与本文件第 2 节的 relaunch 同一个理由）。
    连不上就返回 None，让调用方把那条断言判红，而不是把整套测试崩掉。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if js("typeof window.__jianShare") == "function":
                return True
        except SystemExit:
            pass                      # cdp() 连不上时会 SystemExit(2)，这里吞掉继续等
        time.sleep(2)
    return False


run("state.onboarded = true; state.yanText = ''; save(state); show('yi');")
sh("shell", "am", "force-stop", PKG)          # 冷启动：进程都没了
time.sleep(0.8)
share("明天记得把材料发我")
check("冷启动分享：App 真的被那条 SEND 叫起来了（页面上有 __jianShare）", wait_page(), True)
# boot() 是异步的（先捞 Preferences 备份再落首屏），分享比它早到会先存在 pendingShare 里，
# 由 boot() 末尾的 flushShare() 补消费——所以这里要多等一会儿再看输入框。
time.sleep(3.0)
cold_txt = js(SHARE_JS)
check("冷启动分享：文字到了言笺输入框里", "明天记得把材料发我" in (cold_txt or ""), cold_txt)
check("冷启动分享：落在言笺那一屏（不是停在首页）", wait_screen(), "yan")

# 热启动：App 已经在后台。刚才那条 getIntent() 里的 EXTRA_TEXT 已经被原生抹掉了
# （防配置变化重复贴），所以这里贴进来的必须是**新的一句**，否则分不清是新的还是旧的。
sh("shell", "input", "keyevent", "KEYCODE_HOME")
time.sleep(1.2)
share("药快没了帮我买一盒")
time.sleep(2.5)
warm_txt = js(SHARE_JS)
check("热启动分享：文字也到了（这条最容易漏，走的是 onNewIntent）",
      "药快没了帮我买一盒" in (warm_txt or ""), warm_txt)
check("热启动分享：是追加不是覆盖（前面那句还在）",
      "明天记得把材料发我" in (warm_txt or ""), warm_txt)
check("热启动分享：没有重新走一遍开机（JS 上下文还在）", js("typeof window.__jianShare"), "function")

# 超长文本：原生侧先截断到 4000（几十万字拼进 evaluateJavascript 会把 WebView 卡死）。
# 这里造 6000 字，验证「进来了、而且没有把 App 弄挂」。
run("state.yanText = ''; save(state);")
share("字" * 6000)
time.sleep(3.5)
long_txt = js(SHARE_JS)
check("超长分享被截到 4000 字（不是整段塞进 WebView）",
      isinstance(long_txt, str) and len(long_txt) == 4000, len(long_txt or ""))
check("截断之后 App 还活着（没有 ANR / 白屏）", wait_screen() in ("yan", "yi"), True)

print("\n--- 7. 返回键：子页先回上一屏，栈底才退后台 ---")
# 判据只有一条：按一次返回，从子页回到它属于的那一屏。九个新子页各走一遍，
# 覆盖 SUB_OF 的每一类父屏（衣/味/言/册/笺谱）。返回栈为空时 goBack() 返回 false，
# app.js 的 registerNativeBack 才调 minimizeApp()——所以「回到上一屏而不是退出」这件事
# 只有走真返回键才量得到。
BACK_CASES = [("yi-item", "yi"), ("yi-outfit", "yi"), ("wei-dish", "wei"),
              ("wei-week", "wei"), ("yan-remind", "yan"), ("settings", "me"),
              ("badges", "pu"), ("year", "pu"), ("search", "me")]
for sub, parent in BACK_CASES:
    # 先回到父屏再进子页：show() 只有从父屏进子页时才压返回栈
    run("show('%s'); show('%s');" % (parent, sub))
    time.sleep(0.5)
    if wait_screen() != sub:
        check("%s 能进得去（进不去就说明这一条没验到）" % sub, False, wait_screen())
        continue
    sh("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(1.0)
    check("在 %s 按返回 → 回到 %s（不是退出 App）" % (sub, parent), wait_screen(), parent)

run("show('yi');")

bad = [c for c in checks if not c[0]]
print("\n结果：%d 通过 / %d 失败" % (len(checks) - len(bad), len(bad)))
sys.exit(1 if bad else 0)
