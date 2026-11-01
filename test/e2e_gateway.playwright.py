# 网关模式验证：确认浏览器真的能通过 HTTP 走通 backend/gateway.py。
#
# 这是「接模型时只改 endpoint」这条承诺的验收——之前只测过两端结论一致，
# 从没验证过浏览器里那条远程路径能不能真的跑起来。
#
# 运行：python test/e2e_gateway.playwright.py
import os
import pathlib
import socket
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
URL = (ROOT / "index.html").as_uri()
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"

MK = """() => {
  window.__mk = (color, name) => {
    const c = document.createElement('canvas');
    c.width = 600; c.height = 800;
    const x = c.getContext('2d');
    x.fillStyle = color; x.fillRect(0, 0, 600, 800);
    x.fillStyle = 'rgba(255,255,255,0.20)'; x.fillRect(0, 470, 600, 330);
    return new Promise((r) => c.toBlob((bl) => r(new File([bl], name, { type: 'image/jpeg' })), 'image/jpeg'));
  };
  return true;
}"""

checks = []


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append(ok)
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def port_open(port, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


gw = subprocess.Popen(
    [sys.executable, str(ROOT / "backend" / "gateway.py")],
    # 网关往 stdout 打中文（启动横幅、每条请求的日志），而母进程按 utf-8 读这根管道。
    # Windows 上的 Python 子进程在输出接进管道时按本地代码页写（这台机器 cp936），
    # 于是第一个中文行就能把读线程炸掉——从没设 PYTHONIOENCODING 的终端起就是这样。
    # 不钉住它，这套门会「跑完了」但那半截输出谁也没读到。
    env={**os.environ, "JIAN_PORT": str(PORT), "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    errors="replace",
)

try:
    if not port_open(PORT):
        # 网关是本脚本自己拉起来的，起不来就是真出错（端口被占、语法炸了、依赖没了）。
        # 以前这里印一句「跳过」然后退 0——整套守门因此可以绿着一项没跑。
        alive = gw.poll() is None
        try:
            gw.terminate()
            gw.wait(timeout=5)
        except Exception:
            pass
        try:
            out = gw.stdout.read() or ""
        except Exception:
            out = ""
        print(f" FAIL  网关没起来（进程{'还活着' if alive else '已自行退出'}），这一套一项都没跑")
        print((out or "（网关没有输出）")[-1200:])
        raise SystemExit(1)
    print(f"网关已启动：{BASE}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 430, "height": 940}, device_scale_factor=2)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        posts = []
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)

        page.goto(URL)
        page.wait_for_timeout(600)

        print("--- 1. 指向网关 ---")
        page.evaluate(f"() => {{ state.apiUrl = '{BASE}'; window.JIAN_CONFIG.endpoint = '{BASE}'; save(state); }}")
        page.evaluate("() => { show('yi'); hintEngine(); }")
        page.wait_for_timeout(200)
        # 刚填上地址、一次请求都还没发：这时候说「网关」就是假话（第十四轮改的就是它）。
        # 只有真的通过一次，顶栏才许改口成「网关」。
        check("只填了地址还没试过", page.inner_text("#engineHint"), "网关未试")
        check("JianAPI.remoteOn() 为真", page.evaluate("() => JianAPI.remoteOn()"), True)

        print("\n--- 2. 衣笺走网关 ---")
        page.evaluate(MK)
        posts.clear()
        page.evaluate("async () => { const f = await window.__mk('#d8d2c6', 'tee.jpg'); runYi(f); }")
        page.wait_for_function("() => state.lastReport !== null", timeout=20000)
        check("确实发出了 POST", len(posts) > 0)
        check("打到了 /v1/see", any("/v1/see" in u for u in posts))
        print("        请求：" + " , ".join(posts))
        r = page.evaluate("() => state.lastReport")
        check("网关返回了印章", r["stamp"] in ("宜入", "再想想", "先别"))
        check("网关返回带 basis", bool(r.get("basis")))
        # 真的通过一次了，顶栏这才许改口
        page.evaluate("() => { show('yi'); hintEngine(); }")
        page.wait_for_timeout(200)
        check("通过一次之后才说「网关」", page.inner_text("#engineHint"), "网关")
        print(f"        印章={r['stamp']} 依据={r['basis']['name'] if r.get('basis') else '无'} gap={r.get('gap')}")

        print("\n--- 3. 味笺走网关 ---")
        page.evaluate("() => { show('wei'); }")
        page.wait_for_timeout(200)
        page.evaluate("""() => {
          state.people = [{ name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }];
          save(state); renderWeiPeople();
          document.querySelector('#menu').value = '宫保鸡丁\\n水煮鱼\\n米饭';
          runWei();
        }""")
        page.wait_for_function("() => document.querySelector('#weiResult .todo, #weiResult .quote')", timeout=20000)
        page.wait_for_timeout(400)
        check("味笺打到 /v1/complete", any("/v1/complete" in u for u in posts))
        check("禁花生 → 宫保鸡丁进雷区", page.evaluate("() => state.album[0].quote.includes('宫保鸡丁')"))
        order_len = page.evaluate("() => document.querySelectorAll('#weiResult .serving .line').length")
        check("网关也给出了上菜顺序", order_len, 3)

        print("\n--- 4. 言笺走网关 ---")
        page.evaluate("() => { show('yan'); }")
        page.wait_for_timeout(200)
        page.evaluate("""() => {
          document.querySelector('#yanText').value = '明天记得把材料发我。\\n那就周五见吧。';
          runYan();
        }""")
        page.wait_for_function("() => (state.yanCards || []).length > 0", timeout=20000)
        page.wait_for_timeout(300)
        cards = page.evaluate("() => state.yanCards")
        check("言笺捞出 2 条", len(cards), 2)
        check("时间由网关抽出", cards[0]["when"]["text"] if cards[0].get("when") else None, "明天")

        print("\n--- 4.5 顶栏那行说的是「当前这张笺」，不是三条路的平均近况 ---")
        # 衣笺 刚刚是真的走网关出的判定；这之后把地址换成一台不通的，言笺 只能回落本地。
        # 这时候人站在 言笺 页上，顶栏必须说「回落本地」——
        # 以前它问的是不带参数的 status()（哪条路通过过就算「网关」），会照旧写「网关」。
        page.evaluate("() => { window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9';"
                      " state.apiUrl = 'http://127.0.0.1:9'; save(state); }")
        page.evaluate("() => { show('yan'); document.querySelector('#yanText').value ="
                      " '明天记得把材料发我。\\n那就周五见吧。'; runYan(); }")
        page.wait_for_function("() => (state.yanCards || []).length > 0", timeout=30000)
        page.wait_for_timeout(300)
        hYan = page.inner_text("#engineHint")
        print("        言笺页顶栏：" + hYan)
        check("言笺回落本地时，顶栏就说回落本地", hYan, "回落本地")
        page.evaluate("(b) => { window.JIAN_CONFIG.endpoint = b; state.apiUrl = b; save(state); }", BASE)
        page.evaluate("() => { show('wei'); }")
        page.wait_for_timeout(200)
        # 同一份「最近近况」，两屏两个答案：味笺 第 3 节是真走网关排的，所以这里该说「网关」；
        # 前一步站在 言笺 页上该说「回落本地」。聚合口径下两处都会写「网关」。
        check("切到味笺，说的是味笺自己那条路", page.inner_text("#engineHint"), "网关")
        page.evaluate("() => show('yi')")
        page.wait_for_timeout(200)
        check("切回衣笺，顶栏又说出它自己的网关判定", page.inner_text("#engineHint"), "网关")

        print("\n--- 5. 网关不可达时自动回落 ---")
        page.evaluate("() => { window.JIAN_CONFIG.endpoint = 'http://127.0.0.1:9'; }")
        check("remoteOn 仍为真（地址非空）", page.evaluate("() => JianAPI.remoteOn()"), True)
        page.evaluate("() => { show('yi'); }")
        page.wait_for_timeout(200)
        posts.clear()
        page.evaluate("async () => { const f = await window.__mk('#b83227', 'red.jpg'); runYi(f); }")
        page.wait_for_function("() => state.lastReport !== null && state.lastReport.stamp", timeout=30000)
        r2 = page.evaluate("() => state.lastReport")
        check("连不上时仍出结果（回落本地）", r2["stamp"] in ("宜入", "再想想", "先别"))
        print(f"        回落结果：{r2['stamp']}  {r2['quote']}")
        check("回落没有抛未捕获错误", len(errors), 0)

        print("\n--- 6. 关掉网关也能用 ---")
        gw.terminate()
        gw.wait(timeout=10)
        # 第 5 节刚失败过一次，熔断期（30 秒）里本来就不该再往外发——那正是第 19 轮要的行为。
        # 所以这里按「用户动了地址」那条路走：gwReset() 会 warm，尝试恢复。
        # 少了 gwReset 这一句，posts 会是空的，看着像「App 不再试了」，其实是熔断在起作用。
        page.evaluate(f"() => {{ window.JIAN_CONFIG.endpoint = '{BASE}'; gwReset(); }}")
        posts.clear()
        page.evaluate("async () => { const f = await window.__mk('#2c3a4a', 'blue.jpg'); runYi(f); }")
        page.wait_for_function("() => state.lastReport && state.lastReport.stamp", timeout=30000)
        r3 = page.evaluate("() => state.lastReport")
        check("网关关掉后依然出结果", r3["stamp"] in ("宜入", "再想想", "先别"))
        check("确实尝试过连接", len(posts) > 0)

        if errors:
            print("\n运行时错误：")
            for e in errors:
                print("   " + e)
        check("全程无 JS 运行时错误", len(errors), 0)

        ctx.close()
        browser.close()
finally:
    if gw.poll() is None:
        gw.terminate()
        try:
            gw.wait(timeout=5)
        except subprocess.TimeoutExpired:
            gw.kill()

bad = checks.count(False)
print(f"\n结果：{len(checks) - bad} 通过 / {bad} 失败")
sys.exit(1 if bad else 0)
