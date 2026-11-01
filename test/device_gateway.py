# 安卓壳到底能不能把请求发给用户自己起的网关。
#
# 为什么单独一套：第 17 轮把识图／抄截图接进了 H5，而桌面那套（e2e 第 29 节）是在
# file:// 上跑的，走不到安卓这两道闸——NSC 的明文放行（targetSdk 28+ 默认禁）和
# WebView 的混合内容（壳自己的源是 https://localhost，往 http:// 发属混合内容）。
# 两道逐个关掉在同一台模拟器上量过：开+关 连不上、关+开 连不上、开+开 在线，
# 缺一层设备上就只有「网关连不上：Failed to fetch」这一句，看不出是壳把路拦了。
# 详见 GATEWAY.md 的「手机要连」一节（含一个坑：改完配置不 cap:sync，APK 里还是旧那份）。
#
# 好消息是模拟器有一条专门的路：10.0.2.2 就是宿主机的回环。所以网关照默认只绑
# 127.0.0.1 也能连上，不必为了测试把端口开给整条局域网。
#
# 跑：ANDROID_SERIAL=emulator-5554 PYTHONIOENCODING=utf-8 python test/device_gateway.py
#   前提：调试包已装（release 包没有 CDP，读不到 #apiModel）；~/.jian/llm_providers.json 在
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# cap-cdp 里那句 `adb shell pidof` 不带 -s，两台模拟器在线时就炸「more than one
# device/emulator」，而且是从 node 里炸出来的，看着像 App 坏了。require_avd() 认领过
# 串口之后会把它写进 ANDROID_SERIAL，adb 认这个环境变量，所以那条裸调用也走对的那台。
from device_avd import WANT, require_avd                       # noqa: E402
from device_verify import ADB, PKG, ROOT, cdp, check, checks, wait_ready  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SERIAL = require_avd()


def sh(*args):
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True,
                          timeout=180, text=True, encoding="utf-8", errors="replace")


def shell(cmd):
    return (sh("shell", cmd).stdout or "").strip()


def js(expr):
    out = cdp(["eval", "(() => { try { return String(%s); } catch (e) { return 'ERR:' + e; } })()" % expr])
    v = (out[-1] if out else "").strip()
    return v.strip('"') if v.startswith('"') else v


def run(stmts):
    out = cdp(["eval", "(() => { try { %s return 'ok'; } catch (e) { return 'ERR:' + e; } })()" % stmts])
    v = (out[-1] if out else "").strip().strip('"')
    if v.startswith("ERR"):
        print("   页面里报错了：" + v[:220])
    return v


def wait_js(pred, timeout=60, note=""):
    """等页面里某个条件成立（真模型一次识别 2~12 秒，别用固定 sleep 赌）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if js(pred) in ("true", "1"):
            return round(time.time() - t0, 1)
        time.sleep(0.6)
    print(f"   等不到 {note or pred}（{timeout}s）")
    return None


def launch():
    subprocess.run([ADB, "-s", SERIAL, "shell", "monkey", "-p", PKG, "-c",
                    "android.intent.category.LAUNCHER", "1"], capture_output=True, timeout=60)


def restart():
    """改了 endpoint 要重启才算：state.apiUrl 是在 boot 里灌进 JIAN_CONFIG 的（见 state.js），
    热切换只改了内存里那一份，验的不是用户下次打开 App 看到的样子。

    前面那 3 秒不能省：force-stop 是 SIGKILL，而 Chromium 落 localStorage 是异步的。
    实测省掉之后，页面里 localStorage.getItem 明明读得到刚写的值（那是内存里的那份），
    重启回来却变成空的——「我的」于是说「没填网关地址」，看着像网络不通，其实是没落盘。
    真人写完地址到重开 App 之间总不止 3 秒，所以这是脚本要等，不是产品要改。"""
    time.sleep(3)
    shell(f"am force-stop {PKG}")
    launch()


def set_endpoint(base):
    run("state.onboarded = true; state.points = 40;"
        f" state.apiUrl = '{base}'; window.JIAN_CONFIG.endpoint = '{base}';"
        " gwReset(); save(state);")
    restart()
    wait_ready()
    got = js("state.apiUrl")
    # 先把「重启之后地址还在不在」单独钉一条：不钉的话，它一旦丢了后面全是网络类的假红，
    # 看上去像壳发不出请求，其实是地址没落盘。
    check("网关地址活过一次真重启（不是只活在内存里）", got, base)
    return got == base


def jsobj(expr):
    """取一个 JSON 字符串。cap-cdp 的 eval 走 String(...)，有时带一层引号有时不带，
    两种都试一次，别让它静默变成一个空 dict（那会让所有断言一起变红，查半天）。"""
    raw = js(expr)
    for cand in (raw, raw.strip('"').replace('\\"', '"')):
        try:
            return json.loads(cand)
        except Exception:
            pass
    print(f"   页面回的不是 JSON：{raw[:180]}")
    return None


def read_api_model(timeout=45):
    """「我的」那一行是异步填的：先「正在问网关能干什么…」，回话到了才改口。"""
    am = ""
    t0 = time.time()
    while time.time() - t0 < timeout:
        am = js("document.querySelector('#apiModel').textContent")
        if any(k in am for k in ("在线", "连不上", "没配模型", "没填网关")):
            return am
        time.sleep(0.8)
    return am


def make_photo():
    """在页面里现造一张 600x800 的「衣服」。验的是那条 fetch，不是相机。
    每次重启之后都得重造：window.__f 活在页面里，页面一换就没了。"""
    run("window.__f = null;"
        "const c = document.createElement('canvas'); c.width = 600; c.height = 800;"
        "const x = c.getContext('2d'); x.fillStyle = '#d8c9b4'; x.fillRect(0,0,600,800);"
        "x.fillStyle = '#b8a58c'; x.fillRect(120,150,360,520);"
        "c.toBlob((b) => { window.__f = new File([b], 'knit.jpg', {type:'image/jpeg'}); });")
    return wait_js("!!window.__f", 15, "canvas.toBlob") is not None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    # 以前这里自己 query 一次 `emu avd name` 打印出来，然后什么都不做——
    # 把名字念一遍不拦一道，等于给下一个忘带环境变量的人留了个心理安慰。
    # 现在认领串口这件事在 device_avd.require_avd() 里做掉了，走到这句时名字必然是 WANT。
    print(f"设备：{SERIAL}（AVD「{WANT}」）")
    if PKG not in shell("pm list packages"):
        print(f"   设备上没装 {PKG}，先 assembleDebug + adb install -r")
        return 1

    port = free_port()
    env = {**os.environ, "JIAN_PORT": str(port)}
    env.pop("JIAN_LLM_BASE", None)          # 用清单里的第一家（实测最稳的那家）
    env.pop("JIAN_LLM_KEY", None)
    env.pop("JIAN_LLM_MODEL", None)
    # 网关的输出去文件，不去管道：管道要边跑边读，收尾才 read() 拿到的是 0 行
    # （实测：App 明明已经报出模型名了，日志里却一行都没有，那种「没证据」是假的）。
    # `-u` 也不是随手加的：子进程的 stdout 对着文件时是整块缓冲的，而 terminate() 在
    # Windows 上是硬杀，缓冲区里那几千字节连同证据一起没了。加了才逐行落盘。
    gwlog = pathlib.Path(tempfile.gettempdir()) / "jian_device_gateway.log"
    gwf = gwlog.open("w", encoding="utf-8", errors="replace")
    gw = subprocess.Popen([sys.executable, "-u", str(ROOT / "backend" / "gateway.py")], env=env,
                          stdout=gwf, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    base = f"http://10.0.2.2:{port}"       # 模拟器眼里的「宿主机回环」
    try:
        t0 = time.time()
        while time.time() - t0 < 25:
            with socket.socket() as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        else:
            print("   网关没起来，后面都测不了")
            return 1
        print(f"   网关：http://127.0.0.1:{port}（设备上填 {base}）\n")

        print("--- 1. 连上 WebView ---")
        launch()
        href, waited = wait_ready()
        if href is None:
            print("   等不到可调试且已加载完的页面")
            return 1
        print(f"   等了 {waited:.1f}s，{href}")
        check("跑的是 App 内的资源（不是桌面 file://）", ("localhost" in href) or ("capacitor" in href), True)

        print("\n--- 2. 让 App 指向宿主机上那台 http 网关 ---")
        if not set_endpoint(base):
            print("   地址没留住，后面的网络结论都不可信")
            return 1
        run("show('me');")
        am = read_api_model()
        print(f"   「我的」那一行：{am}")
        check("壳把 http 请求发得出去（网关的自述回来了）",
              ("在线" in am) and ("连不上" not in am), True)
        check("说得出用的是哪只模型（这台网关真配了模型）",
              ("glm-4v-flash" in am) or ("agnes-2.5-flash" in am), True)

        print("\n--- 3. 手机上拍一件 → 认出来的是模型给的 ---")
        run("state.yiCat = '上衣'; state.lastReport = null; state.points = 40; save(state); show('yi');")
        time.sleep(0.6)
        check("图造出来了", make_photo(), True)
        run("runYi(window.__f);")
        secs = wait_js("!!(state.lastReport && state.lastReport.new && state.lastReport.new.seen)",
                       60, "模型认这件")
        print(f"   认了 {secs}s")
        it = jsobj("JSON.stringify(state.lastReport && state.lastReport.new || {})") or {}
        seen = it.get("seen") or {}
        print(f"   认出来的是：{json.dumps(seen, ensure_ascii=False)}  本机量到的主色 {it.get('color')}")
        check("模型的回话真的落进了这张笺", bool(seen), True)
        # 页面上留的是 seen.model（yi.js 把回话收成一个三元组），source 是网关响应里的字段，
        # 不在 App 存的那一份里——钉错地方只会得到一个假红。
        check("这一张笺记得是哪只模型认的",
              seen.get("model") in ("glm-4v-flash", "agnes-2.5-flash"), True)
        # 这一张是页面里现造的色块，模型很可能回「无」——被拦下来之后 App 该保持默认名。
        # 所以这里不能钉「名字一定来自模型」，钉的是「名字不会是占位话，也不会是空」。
        # （造这张图是为了验那条真 fetch，不是验模型认得准不准——认得准不准由
        #   test/providers_live.py 拿真衣服图量。）
        check("名字不是模型吐出来的占位话（「无」被拦下了）",
              it.get("name") not in ("", "无", "未知"), True)
        check("主色仍用本机量的那一个（没被模型的色串改）",
              bool(it.get("color")) and it["color"] != seen.get("color"), True)
        check("印章照样出得来（判定还是本地那套）",
              js("state.lastReport.stamp") in ("宜入", "再想想", "先别"), True)
        note = js("document.querySelector('#reportNote').textContent")
        if seen.get("name"):
            check("认出来了就在附注里说是哪只模型认的", "认出来的是" in note, True)
        else:
            # 这张色块模型没给名字（「无」被拦下了）——那附注就不许说「认出来的是…」。
            check("模型没给出名字时，附注不谎称认出了名字", "认出来的是" not in note, True)
            print(f"   （模型对这张色块没报出名字，附注现在写：{note[:90]}）")

        print("\n--- 4. 反面对照：填一台不通的，界面上必须改口 ---")
        # 没有这一条，上面「在线」也可能只是永远显示在线：那一类假账第十四轮清过一次。
        dead = f"http://10.0.2.2:{free_port()}"
        set_endpoint(dead)
        run("show('me');")
        am2 = read_api_model()
        print(f"   填死地址之后：{am2}")
        check("连不上就明说连不上", "连不上" in am2, True)
        check("图重造一张（重启把页面换掉了，旧的 __f 不在）", make_photo(), True)
        run("state.lastReport = null; state.points = 40; save(state); show('yi'); runYi(window.__f);")
        # 预算给到 90 秒：识图那条先撞 seeMs(45s) 再撞判定那条 timeoutMs(20s)，
        # 而宿主机端口不通时模拟器这边是「丢包」不是「拒接」，只能等超时。
        # 桌面 e2e 用 127.0.0.1:9（Chromium 保留端口，秒失败）测不到这一档。
        secs = wait_js("!!(state.lastReport && state.lastReport.stamp)", 95, "回落本地还能出判定")
        check("连不上照样出判定（回落本地引擎）", secs is not None, True)
        check("回落时不再谎称认过", js("!state.lastReport.new.seen"), "true")
    finally:
        # 收尾把地址擦掉。这一套把 endpoint 写进了 localStorage，而它活得过 force-stop：
        # 下一套（device_verify 的「上一桌要活过冷启动」）接着用同一个 App 时，
        # 每次判定都要先撞满 20 秒的远程超时才回落本地，于是那几条时序断言全红——
        # 看起来像 writeStore 重构弄坏了持久化，其实是上一套没扫地。
        try:
            run("state.apiUrl = ''; window.JIAN_CONFIG.endpoint = ''; gwReset(); save(state);")
            time.sleep(3)     # 等 localStorage 落盘，别又被下一次 force-stop 吃掉
        except Exception as e:
            print("   收尾没擦干净网关地址（会影响后面那几套的时序）：" + str(e)[:120])
        if gw.poll() is None:
            gw.terminate()
            try:
                gw.wait(timeout=5)
            except Exception:
                pass
        gwf.close()
        try:
            out = gwlog.read_text(encoding="utf-8", errors="replace")
        except Exception:
            out = ""
        hits = [l for l in out.splitlines() if "/v1/" in l]
        print(f"\n   网关自己记到的（来自这台设备的请求 {len(hits)} 条）：")
        for l in hits[:10]:
            print("     " + l)
        # 服务端有一笔，才算「设备真把请求发出去了」：只读物体的那一侧，
        # 理论上可以被一个说谎的界面糊过去。
        check("网关收到了来自设备的 /v1/status", any("/v1/status" in l for l in hits), True)
        check("网关收到了来自设备的 /v1/recognize", any("/v1/recognize" in l for l in hits), True)

    bad = [c for c in checks if not c[0]]
    print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
    for ok, name, got, want in bad:
        print(f"   ✗ {name}  ->  {got}   (期望 {want})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
