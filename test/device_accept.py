"""0.6.0 安卓验收流水线：一条命令，从起模拟器到收尾关模拟器。

为什么要这一个文件：验收本身有顺序（起机 → 装包 → 五道门 → 逐屏截图 → 深色 → 通知 → 关），
中间任何一步失败，**收尾都必须照做**——这台机器只剩几百 MB 可用内存，一台没人管的
无头模拟器会一直占着 3~4 GB，把别人的会话挤到页面文件里。散着敲命令时最容易漏的
就是最后那一步（本项目 AGENTS.md 把它写成硬约束，就是因为漏过）。

## 两个包，各干各的活

    release APK（app-release.apk，1,703,626 字节 / 0.6.0 / code 28）
        用户真正装到手机上的那个。**没有 CDP**：Capacitor 的 webContentsDebuggingEnabled
        跟随 APK 的 debuggable 标记（node_modules/@capacitor/android/.../CapConfig.java:286），
        release 不可调试，所以那四道靠 CDP 驱动页面的门在它上面**跑不了**——
        不是「跑过了是绿的」，是根本连不上。
        它能验：签名 / 版本 / 权限清单 / 首屏真的画出来了 / 深链。本脚本用它做「产物真身」那一节。

    debug APK（app-debug.apk）
        五道门的前提（指南 §6.5 原话「调试包已装」）。它与 release 的前端是**同一份字节**
        （www/ 由 cap:sync 拷进 android/app/src/main/assets/public/，`npm run test:pkg`
        会逐个文件比；本脚本另行再比一次，见 compare_frontends()）。
        所以它截出来的图与 release 是同一张界面——而它能开 CDP，能种数据、能点进没有深链的子页。

本脚本因此不假装：五道门跑在 debug 包上，截图与通知跑在**同一份前端**上，
release 包单独做一次「它真的能画出来」的实拍。

## 用法

    python test/device_accept.py                     # 全套（要 --debug-apk 才跑那四道门）
    python test/device_accept.py --debug-apk <path>  # 五道门 + 截图 + 通知
    python test/device_accept.py --gates none        # 只截图
    python test/device_accept.py --keep              # 收尾不关（排障用，别习惯性加）

## 收尾判据（与 AGENTS.md 一致）

`adb devices` 不再列出该串口，且 `qemu-system-x86_64-headless.exe` 进程数为 0。
本脚本把两条都打印出来，并且**只** kill 自己起的那一台。
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

ADB = str(pathlib.Path.home() / "AppData" / "Local" / "Android" / "Sdk"
          / "platform-tools" / "adb.exe")
EMULATOR = str(pathlib.Path.home() / "AppData" / "Local" / "Android" / "Sdk"
               / "emulator" / "emulator.exe")
AAPT = next((str(p / "aapt2.exe") for p in sorted(
    (pathlib.Path.home() / "AppData/Local/Android/Sdk/build-tools").glob("*"), reverse=True)
    if (p / "aapt2.exe").exists()), "")
CDP = str(pathlib.Path.home() / ".qoder" / "mcp-out" / "cap-cdp.mjs")

AVD = "jian_test"                      # 与 device_avd.WANT 同一个名字
PKG = "com.jian.app"
ACT = f"{PKG}/.MainActivity"
SHOTS = HERE / "shots-device"
LOGS = SHOTS / "logs"

# 11 屏：用户口径的屏名 → 到达方式。
#   有深链的六屏直接用 jian://screen/<id>（这也是快捷方式走的那条真链路）；
#   另外五屏（章/这一年/设置/找东西/提醒）没有深链，只能从父屏点进去，
#   而 release 包没有 CDP，所以这五屏在 debug 包上用 show() 到达——
#   与真人点进去得到的是同一个 DOM 状态（show() 就是那个入口最后调的函数）。
SCREENS = [
    ("今日", "today"), ("衣笺", "yi"), ("味笺", "wei"), ("言笺", "yan"),
    ("笺谱", "pu"), ("册", "me"),
    ("章", "badges"), ("这一年", "year"), ("设置", "settings"),
    ("找东西", "search"), ("提醒", "yan-remind"),
]
DARK = [("今日", "today"), ("衣笺", "yi"), ("册", "me")]

GATES = [
    ("device_verify.py", 1200),
    ("device_deeplink.py", 1800),
    ("device_gateway.py", 1500),
    ("device_perf.py", 1500),
    ("device_guards.py", 300),        # 纯静态：不碰设备
]

results = []          # [(名字, ok/fail/skip, 说明)]


# ───────────────────────────── 小工具 ─────────────────────────────
def say(msg=""):
    print(msg, flush=True)


def record(name, state, note=""):
    results.append((name, state, note))
    mark = {"ok": " ok ", "fail": "FAIL ", "skip": " skip"}.get(state, "  ?  ")
    say(f"{mark} {name}" + (f"  —  {note}" if note else ""))


def run(argv, timeout=300, binary=False, env=None):
    kw = dict(capture_output=True, timeout=timeout)
    kw["text"] = not binary
    if not binary:
        kw.update(encoding="utf-8", errors="replace")
    if env:
        kw["env"] = env
    try:
        return subprocess.run(argv, **kw)
    except subprocess.TimeoutExpired:
        return None


def adb(serial, *args, binary=False, timeout=300):
    return run([ADB, "-s", serial, *args], timeout=timeout, binary=binary)


def shell(serial, cmd, timeout=120):
    p = adb(serial, "shell", cmd, timeout=timeout)
    return (p.stdout or "").strip() if p else ""


def device_states():
    """串口 → 状态。收尾要看的是「不再列出」，而不是「不在 device 里」（offline 也算列出）。"""
    p = run([ADB, "devices"], timeout=60)
    got = {}
    for ln in ((p.stdout or "") if p else "").splitlines()[1:]:
        bits = ln.split()
        if len(bits) >= 2:
            got[bits[0]] = bits[1]
    return got


def avd_of(serial):
    p = adb(serial, "emu", "avd", "name", timeout=60)
    lines = [ln.strip() for ln in ((p.stdout or "") if p else "").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def qemu_procs():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='qemu-system-x86_64-headless.exe'\" "
          "| Select-Object -Expand ProcessId")
    p = run(["powershell", "-NoProfile", "-Command", ps], timeout=60)
    return [x for x in ((p.stdout or "") if p else "").split() if x.strip()]


# ─────────────────────────── 起 / 关模拟器 ───────────────────────────
def start_avd(timeout=300):
    """起一台 jian_test。已经在线的 jian_test 直接借用（并标记「不是我起的」）。"""
    for s in device_states():
        if avd_of(s) == AVD:
            say(f"   已经有一台 {AVD} 在线：{s}（借用，收尾不杀它）")
            return s, False
    before = set(device_states())
    say(f"   起 {AVD}（无头、不存快照）…")
    log = open(LOGS / "emulator.log", "w", encoding="utf-8", errors="replace")
    subprocess.Popen([EMULATOR, "-avd", AVD, "-no-window", "-no-audio", "-no-boot-anim",
                      "-no-snapshot", "-gpu", "auto", "-netdelay", "none", "-netspeed", "full"],
                     stdout=log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    t0 = time.time()
    serial = None
    while time.time() - t0 < timeout:
        serial = next((s for s in device_states() if s not in before), None)
        if serial:
            break
        time.sleep(2)
    if not serial:
        raise SystemExit(f"[验收] {timeout}s 内没等到新串口（看 {LOGS / 'emulator.log'}）")
    say(f"   串口 {serial}，等开机完成…")
    while time.time() - t0 < timeout:
        if shell(serial, "getprop sys.boot_completed") == "1":
            say(f"   开机完成，用了 {time.time() - t0:.0f}s")
            break
        time.sleep(3)
    else:
        raise SystemExit(f"[验收] {serial} 没在 {timeout}s 内 boot_completed=1")
    return serial, True


def kill_avd(serial, owned):
    say("\n=== 收尾 ===")
    if serial and owned:
        adb(serial, "emu", "kill", timeout=60)
    elif serial:
        say(f"   {serial} 不是我起的（别人会话的 {AVD}），不发 emu kill")
    t0 = time.time()
    while time.time() - t0 < 90 and serial in device_states():
        time.sleep(2)
    left, leftq = device_states(), qemu_procs()
    say("   adb devices：" + (", ".join(f"{k}={v}" for k, v in left.items()) or "（空）"))
    say("   qemu-system-x86_64-headless：" + ("、".join(leftq) if leftq else "（没有进程）"))
    record("收尾：adb devices 不再列出该串口", "ok" if serial not in left else "fail", str(serial))
    if owned:
        record("收尾：headless qemu 进程已消失", "ok" if not leftq else "fail",
               "、".join(leftq) if leftq else "")


# ───────────────────────────── 装包 ─────────────────────────────
def install(serial, apk, label):
    shell(serial, f"am force-stop {PKG}")
    # release 用正式钥匙、debug 用 Android Debug 钥匙：签名不同不能覆盖安装
    # （INSTALL_FAILED_UPDATE_INCOMPATIBLE），所以一律先卸再装。
    adb(serial, "uninstall", PKG, timeout=150)
    p = adb(serial, "install", "-r", "-t", str(apk), timeout=420)
    out = ((p.stdout or "") + (p.stderr or "")) if p else ""
    ok = "Success" in out
    record(f"装上 {label}", "ok" if ok else "fail",
           pathlib.Path(apk).name + ("" if ok else out.strip()[-300:]))
    return ok


def compare_frontends(rel_apk, dbg_apk):
    """两个包里打进去的前端是不是同一份字节。

    这一条比「版本号一样」重要得多：版本号在 build.gradle 里，而前端在 assets/public/。
    改了 CSS 没 cap:sync、或者 debug 包是上周的，版本号照样对得上，截出来的却是两张界面。
    """
    import zipfile
    names = ["config.js", "styles.css", "styles-v06.css", "app.js", "ui.js", "index.html"]
    try:
        zr, zd = zipfile.ZipFile(rel_apk), zipfile.ZipFile(dbg_apk)
    except Exception as e:
        record("两个包里的前端是同一份字节", "fail", str(e)[:120])
        return False
    diff = []
    for n in names:
        key = f"assets/public/{n}"
        try:
            a, b = zr.read(key), zd.read(key)
        except KeyError:
            diff.append(f"{n}(缺)")
            continue
        if a != b:
            diff.append(n)
    record("debug 包与 release 包是同一份前端（逐字节）", "ok" if not diff else "fail",
           "、" .join(diff) if diff else "、".join(names))


def apk_facts(apk):
    if not AAPT:
        return ""
    p = run([AAPT, "dump", "badging", str(apk)], timeout=180)
    out = (p.stdout or "") if p else ""
    ver = next((l for l in out.splitlines() if l.startswith("package:")), "")
    perms = [l.split("name='")[1].rstrip("'") for l in out.splitlines()
             if l.startswith("uses-permission:") and "name='" in l]
    return ver, perms


# ───────────────────────────── 截图 ─────────────────────────────
def screencap(serial, path):
    p = adb(serial, "exec-out", "screencap", "-p", binary=True, timeout=150)
    blob = (p.stdout if p else b"") or b""
    if not blob.startswith(b"\x89PNG"):
        return None
    path.write_bytes(blob)
    return path


def deep(serial, screen):
    shell(serial, "am start -a android.intent.action.VIEW -d "
                  f"'jian://screen/{screen}' -n {ACT}")
    time.sleep(1.5)


# ───────────────────────── CDP（调试包才用得上）─────────────────────────
def cdp(serial, args, timeout=200):
    if not pathlib.Path(CDP).exists():
        return 3, [], "没有 cap-cdp.mjs"
    p = run(["node", CDP, "--pkg", PKG, *args], timeout=timeout,
            env={**os.environ, "ANDROID_SERIAL": serial})
    if p is None:
        return 4, [], "cap-cdp 超时"
    return p.returncode, (p.stdout or "").splitlines(), (p.stderr or "")


def cdp_ready(serial, timeout=150):
    probe = "(() => (typeof state !== 'undefined' && typeof show === 'function') ? 'yes' : '')()"
    t0 = time.time()
    while time.time() - t0 < timeout:
        code, lines, _ = cdp(serial, ["eval", probe], timeout=60)
        if code == 0 and any("yes" in ln for ln in lines):
            return True
        time.sleep(2)
    return False


def js(serial, expr):
    out = cdp(serial, ["eval", "(() => { try { return String(%s); } catch (e) { return 'ERR:' + e; } })()" % expr])
    v = (out[1][-1] if out[1] else "").strip()
    return v.strip('"') if v.startswith('"') else v


def jsrun(serial, stmts):
    out = cdp(serial, ["eval", "(() => { try { %s return 'ok'; } catch (e) { return 'ERR:' + e; } })()" % stmts])
    v = (out[1][-1] if out[1] else "").strip().strip('"')
    if v.startswith("ERR"):
        say("   页面里报错了：" + v[:200])
    return v


SEED = r"""(() => {
  const DAY = 86400000, now = Date.now();
  state.onboarded = true;
  state.points = 128;
  state.wardrobe = [
    { id: 'a1', name: '奶咖针织开衫', cat: '上衣', color: '#d8c9b4', worn: 5, lastWorn: now - 2 * DAY, season: '春秋', price: 399 },
    { id: 'a2', name: '深蓝阔腿裤', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: now - DAY, season: '四季', price: 459 },
    { id: 'a3', name: '驼色长大衣', cat: '外套', color: '#c4a574', worn: 3, lastWorn: now - 214 * DAY, season: '冬', price: 1680 },
    { id: 'a4', name: '白衬衫', cat: '上衣', color: '#f4f0ea', worn: 21, lastWorn: now - 5 * DAY, season: '四季', price: 260 },
    { id: 'a5', name: '黑色乐福鞋', cat: '鞋', color: '#2a2723', worn: 9, lastWorn: now - 9 * DAY, season: '春秋', price: 780 }
  ];
  state.yanCards = [
    { k: '待办', line: '明天把材料发给小李，顺便确认一下时间', when: { text: '明天', at: now + DAY }, done: false },
    { k: '要买', line: '药快没了，帮我买一盒', when: null, done: false },
    { k: '已定', line: '周五晚上七点，老地方见', when: { text: '周五', at: now + 3 * DAY }, done: false },
    { k: '待办', line: '把上个月的水电费交了', when: null, done: true }
  ];
  state.people = [{ name: '我', chips: ['辣'] }, { name: '小周', chips: ['香菜'] }, { name: '阿岚', chips: [] }];
  state.reminders = [
    { id: 'r1', text: '把材料发给小李', at: now + 3 * 3600000, repeat: '', done: false, fired: false, from: 'manual' },
    { id: 'r2', text: '给妈妈打电话', at: now + 2 * DAY, repeat: 'weekly', done: false, fired: false, from: 'manual' }
  ];
  state.cookLog = [
    { id: 'c1', name: '番茄炒蛋', t: now - DAY, stars: 4, note: '糖少一点', people: 2 },
    { id: 'c2', name: '清蒸鲈鱼', t: now - 4 * DAY, stars: 5, note: '', people: 3 }
  ];
  state.album = [
    { type: 'yi', t: now - DAY, quote: '柜里那件驼色的，够搭了', text: '【衣笺】先别\n柜里那件驼色的，够搭了' },
    { type: 'wei', t: now - 3 * DAY, quote: '这桌有两个人不吃香菜', text: '【味笺】这桌能入口\n这桌有两个人不吃香菜' }
  ];
  state.log = [];
  for (let i = 0; i < 40; i++) {
    const back = Math.floor(i * 6.2) + 1;
    state.log.push({ t: now - back * DAY, kind: ['wear', 'cook', 'catch', 'plan', 'note'][i % 5],
                     mod: ['yi', 'wei', 'yan'][i % 3], ref: 'x' + i, v: 1 });
  }
  state.log.sort((a, b) => a.t - b.t);
  state.streak = { last: dayStr(now), days: 6, best: 21 };
  state.badges = [
    { id: 'first-wear', t: now - 30 * DAY }, { id: 'closet-10', t: now - 2 * DAY },
    { id: 'first-cook', t: now - 20 * DAY }
  ];
  state.profile = { nick: '', avatar: '', line: '', since: now - 300 * DAY };
  save(state);
  return [state.wardrobe.length, state.yanCards.length, state.reminders.length];
})()"""


def shoot(serial, prefix="", use_cdp=True):
    """逐屏截图。有 CDP 时用 show() 直接到达（与点进去是同一个 DOM 状态）；
    没有 CDP 就只截得到有深链的那六屏。"""
    made = []
    linkable = {"today", "yi", "wei", "yan", "pu", "me"}
    for name, sid in SCREENS:
        if use_cdp:
            jsrun(serial, f"show('{sid}');")
        elif sid in linkable:
            deep(serial, sid)
        else:
            record(f"截图 {prefix}{name}.png", "skip", "没有 CDP 也点不进这一屏（没有深链）")
            continue
        time.sleep(1.2)
        fn = f"{prefix}{name}.png"
        p = screencap(serial, SHOTS / fn)
        if p:
            made.append(fn)
            record(f"截图 {fn}", "ok", f"{p.stat().st_size // 1024} KB")
        else:
            record(f"截图 {fn}", "fail", "screencap 没回 PNG")
    return made


# ─────────────────────────── 通知 ───────────────────────────
def channel_block(serial):
    """渠道那一段。API 35 的渠道是 `NotificationChannel{mId='…', mName=…, mImportance=3, …}`
    一整行内联（不是 13/14 那种分行块），所以按 `NotificationChannel{` 切，不按 `-A4` 抓。"""
    d = shell(serial, "dumpsys notification --noredact", timeout=240)
    blocks = [b for b in d.split("NotificationChannel{") if "jian-remind" in b]
    return (blocks[0].split("mDemoted")[0].strip() if blocks else ""), d


def notif_fire(serial, text="验收提醒：一分钟以后见"):
    at = int(time.time() * 1000) + 60 * 1000
    expr = ("(() => { const r = addReminder(%s, %d, {from:'manual'}); if (!r) return 'ADD_FAIL';"
            " scheduleNative(r); return 'scheduled'; })()"
            % (json.dumps(text, ensure_ascii=False), at))
    return js(serial, expr)


def wait_notification(serial, timeout=140):
    """等它真的进系统：判据是 NotificationRecord 里出现 pkg=com.jian.app 且 channel=jian-remind。
    渠道存在 ≠ 弹过；只有通知记录里那一条才算弹了。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = shell(serial, "dumpsys notification --noredact", timeout=240)
        for rec in d.split("NotificationRecord(")[1:]:
            head = rec.split("\n", 1)[0]
            if "pkg=com.jian.app" in head and "jian-remind" in head:
                return d, rec.split("publicNotification=")[0], round(time.time() - t0)
        time.sleep(5)
    return shell(serial, "dumpsys notification --noredact", timeout=240), "", None


# ───────────────────────────── 五道门 ─────────────────────────────
def run_gate(serial, name, timeout):
    log = LOGS / name.replace(".py", ".log")
    say(f"\n--- {name} ---")
    t0 = time.time()
    p = run([sys.executable, str(HERE / name)], timeout=timeout,
            env={**os.environ, "ANDROID_SERIAL": serial,
                 "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    took = time.time() - t0
    if p is None:
        log.write_text(f"超时（{timeout}s）", encoding="utf-8")
        record(f"门 {name}", "fail", f"超时 {timeout}s")
        return
    out = (p.stdout or "") + (p.stderr or "")
    log.write_text(out, encoding="utf-8", errors="replace")
    tail = [ln for ln in out.splitlines() if ln.strip()]
    say("   " + (tail[-1] if tail else "（没有输出）"))
    m = re.search(r"结果：\s*(\d+)\s*通过\s*/\s*(\d+)\s*失败", out)
    if not m:
        record(f"门 {name}", "fail", f"没有结果行（rc={p.returncode}，日志 {log.name}）")
        return
    ok_n, bad_n = int(m.group(1)), int(m.group(2))
    record(f"门 {name}", "ok" if bad_n == 0 else "fail",
           f"{ok_n} 通过 / {bad_n} 失败 · {took:.0f}s · {log.name}")


# ───────────────────────────── 主流程 ─────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", default=str(ROOT / "android/app/build/outputs/apk/release/app-release.apk"))
    ap.add_argument("--debug-apk", default="")
    ap.add_argument("--gates", choices=["auto", "none"], default="auto")
    ap.add_argument("--no-dark", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--keep", action="store_true", help="收尾不关模拟器（排障用）")
    args = ap.parse_args()

    SHOTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    rel = pathlib.Path(args.apk)
    dbg = pathlib.Path(args.debug_apk) if args.debug_apk else None
    serial, owned = None, False
    try:
        say("=== 1. 起模拟器 ===")
        serial, owned = start_avd()
        say(f"   目标：{serial} = {avd_of(serial)}（Android {shell(serial, 'getprop ro.build.version.release')}"
            f" / API {shell(serial, 'getprop ro.build.version.sdk')}）")

        say("\n=== 2. release 包：静态事实 ===")
        if not rel.exists():
            raise SystemExit(f"[验收] 没有 release 包：{rel}")
        ver = apk_facts(rel)
        if ver:
            say("   " + ver[0])
            say("   权限：" + "、".join(p.split(".")[-1] for p in ver[1]))
            need = {"INTERNET", "VIBRATE", "RECEIVE_BOOT_COMPLETED", "WAKE_LOCK", "POST_NOTIFICATIONS"}
            have = {p.split(".")[-1] for p in ver[1]}
            record("权限六条齐全，且没有 SCHEDULE_EXACT_ALARM",
                   "ok" if (need <= have and "SCHEDULE_EXACT_ALARM" not in have) else "fail",
                   "缺 " + "、".join(sorted(need - have)) if not (need <= have) else "六条齐、无精确闹钟")

        say("\n=== 3. release 包真身：装上去、看它画不画得出来 ===")
        if install(serial, rel, "release 包"):
            say("   " + shell(serial, f"dumpsys package {PKG} | grep -E 'versionName|versionCode' | head -2").replace("\n", " / "))
            shell(serial, f"am start -n {ACT}")
            time.sleep(6)
            deep(serial, "today")
            time.sleep(1.5)
            p = screencap(serial, SHOTS / "release-今日.png")
            if p:
                from PIL import Image
                im = Image.open(p).convert("RGB")
                small = im.resize((im.width // 8 or 1, im.height // 8 or 1))
                cols = small.getcolors(small.width * small.height + 1) or []
                total = sum(n for n, _ in cols) or 1
                paper = (244, 239, 230)
                inkish = sum(n for n, c in cols
                             if sum(abs(a - b) for a, b in zip(c, paper)) > 60) / total
                say(f"   release 首屏：{im.size}，非纸色像素 {inkish:.2%}")
                record("release 包真的把界面画出来了（不是白屏/黑屏）", "ok" if inkish > 0.02 else "fail",
                       f"{inkish:.2%}")

        if dbg and dbg.exists():
            say("\n=== 4. 前端对账：两个包里的 www 是不是同一份 ===")
            compare_frontends(rel, dbg)

            say("\n=== 5. 五道设备门（debug 包，CDP 前提）===")
            if install(serial, dbg, "debug 包") and args.gates != "none":
                for name, tmo in GATES:
                    run_gate(serial, name, tmo)
        elif args.gates != "none":
            record("五道设备门", "skip",
                   "没给 --debug-apk：release 包不可调试，CDP 连不上，那四道门跑不了")

        say("\n=== 6. 逐屏截图 ===")
        have_cdp = cdp_ready(serial, timeout=60)
        if have_cdp:
            seed = js(serial, SEED)
            say(f"   种了一份中等厚度的数据：{seed}")
            jsrun(serial, "state.reminders.forEach(cancelNative); show('today');")
            time.sleep(1.0)
        else:
            say("   （没有 CDP：只截得到有深链的那六屏，其余五屏会标 skip）")
            deep(serial, "today")
        made = shoot(serial, use_cdp=have_cdp)

        if not args.no_dark:
            say("\n=== 7. 深色三屏 ===")
            # 先把系统切到夜间，再让 WebView 真的收到 uiMode 变化：
            # configChanges 里有 uiMode，Activity 不重建，网页靠 prefers-color-scheme 自己翻。
            shell(serial, "cmd uimode night yes")
            time.sleep(2.5)
            jsrun(serial, "THEME.apply();")
            time.sleep(1.5)
            dark = []
            for label, sid in DARK:
                if have_cdp:
                    jsrun(serial, f"show('{sid}');")
                else:
                    deep(serial, sid)
                time.sleep(1.4)
                fn = f"dark-{label}.png"
                if screencap(serial, SHOTS / fn):
                    dark.append(fn)
                    record(f"截图 {fn}", "ok")
            night = shell(serial, "cmd uimode night")
            record("系统确实切到了夜间（不然深色那三张是白测）",
                   "ok" if "yes" in night.lower() else "fail", night.replace("\n", " "))
            shell(serial, "cmd uimode night no")
            time.sleep(2.0)
            jsrun(serial, "THEME.apply();")
            after = shell(serial, "cmd uimode night")
            record("深色验完已切回亮色", "ok" if "no" in after.lower() else "fail",
                   after.replace("\n", " "))

        if not args.no_notify:
            say("\n=== 8. 通知：渠道 + 真弹一条 ===")
            blk, _ = channel_block(serial)
            if blk:
                for piece in blk.split(", "):
                    if re.match(r"m(Id|Name|Importance|LockscreenVisibility|Description)=", piece):
                        say("     " + piece)
            record("jian-remind 渠道存在，importance=3、锁屏不显示正文",
                   "ok" if ("jian-remind" in blk and "mImportance=3" in blk
                            and "mLockscreenVisibility=2" in blk) else "fail",
                   "mImportance/lockscreen 对不上" if blk else "压根没有这条渠道")
            if have_cdp:
                # API 33+ 的 POST_NOTIFICATIONS 是运行时权限，插件在 **schedule() 那一刻**
                # 就弹框（LocalNotificationsPlugin.kt 的 shouldRequestNotificationPermission）。
                # 自动化里先把权限给掉，否则排一条就卡在一个系统框上，看起来像「没弹」。
                shell(serial, f"pm grant {PKG} android.permission.POST_NOTIFICATIONS", timeout=90)
                say("   权限：" + shell(serial, f"dumpsys package {PKG} | grep POST_NOTIFICATIONS | head -1"))
                say("   排一条 60 秒后的提醒：" + notif_fire(serial))
                (LOGS / "dumpsys-before.txt").write_text(
                    shell(serial, "dumpsys notification --noredact", timeout=240),
                    encoding="utf-8", errors="replace")
                dump, rec, waited = wait_notification(serial)
                (LOGS / "dumpsys-notification.txt").write_text(dump, encoding="utf-8", errors="replace")
                (LOGS / "notification-record.txt").write_text(rec, encoding="utf-8", errors="replace")
                if rec:
                    for ln in rec.splitlines():
                        if re.search(r"tickerText|android\.title|android\.text|channel=|pkg=com", ln):
                            say("     " + ln.strip())
                record("通知真的弹了（系统通知记录里有这一条）", "ok" if rec else "fail",
                       f"{waited}s 后看到" if waited is not None else "140s 内没有")
                if rec:
                    say("   排上的 alarm：" )
                    for ln in shell(serial, "dumpsys alarm | grep -A2 'com.jian.app' | head -8").splitlines():
                        say("     " + ln.strip())
            else:
                record("真弹一条通知", "skip", "没有 CDP，排不了 1 分钟后的提醒；见 DEVICE-CHECKLIST.md 的手工步骤")

        say("\n=== 9. 汇总 ===")
        bad = [r for r in results if r[1] == "fail"]
        skip = [r for r in results if r[1] == "skip"]
        for name, state, note in results:
            mark = {"ok": " ok ", "fail": "FAIL ", "skip": " skip"}[state]
            say(f"{mark} {name}" + (f"  —  {note}" if note else ""))
        say(f"\n合计：{len(results) - len(bad) - len(skip)} 通过 / {len(bad)} 失败 / {len(skip)} 跳过")
        (SHOTS / "REPORT.md").write_text(
            "# 设备验收实跑记录\n\n"
            + "\n".join(f"- { {'ok': '✅', 'fail': '❌', 'skip': '⏭'}[s] } {n}"
                        + (f" — {note}" if note else "") for n, s, note in results)
            + f"\n\n合计：{len(results) - len(bad) - len(skip)} 通过 / {len(bad)} 失败 / {len(skip)} 跳过\n",
            encoding="utf-8")
        say(f"   报告：{SHOTS / 'REPORT.md'}")
        return 1 if bad else 0
    finally:
        if args.keep:
            say("\n（--keep：按你的要求没有关模拟器。它现在占着 3~4 GB，别忘了手动关。）")
        else:
            kill_avd(serial, owned)


if __name__ == "__main__":
    raise SystemExit(main())
