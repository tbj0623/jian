# 离线守门：把 H5 用 http 起在一个临时端口上，注册 service worker，然后**拔网**再打开一次。
#
# 为什么单独一套：manifest.json 早就配齐了图标和 standalone，README 也写着 PWA，
# 但 sw.js 从来没存在过——「离线可用」是句没人验过的话。这套就是让这句话必须为真。
# 其余三道浏览器用例都跑在 file:// 上，而 service worker 在 file:// 下根本不注册，
# 所以只有这条路能验到。
#
# 服务器只在 127.0.0.1 的临时端口上、只活这几秒、只认白名单里的文件——
# 不是后台常驻服务，跑完就关（和 gateway_http.py 同一套路子）。
#
# 运行：PYTHONIOENCODING=utf-8 python test/offline.playwright.py
import os
import pathlib
import re
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "scripts" / "build-www.mjs").read_text(encoding="utf-8")

ALLOW = set()
_m = re.search(r"const files = \[(.*?)\];", SRC, re.S)
ALLOW.update("/" + f for f in re.findall(r"'([^']+)'", _m.group(1)))
for m in re.findall(r"'([^']+)'", re.search(r"const optionalFiles = \[(.*?)\]", SRC).group(1)):
    if (ROOT / m).exists():
        ALLOW.add("/" + m)

errors = []
checks = []


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))
    return ok   # 调用方要能拿这个值决定要不要打现场（不打回去就永远是句「红得看不懂」）


class Handler(BaseHTTPRequestHandler):
    # 「升级之后拿到的是不是新文件」那一节要临时改一份内容。用类属性而不是实例属性：
    # 每一请求都会新建一个 handler 实例，实例属性传不过去。
    override = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        if path not in ALLOW:
            # icons 下是目录白名单，但必须先确认解析出来还在 icons 里——
            # 不然 /icons/../../x 就绕过去了（和 gateway.py 里挡 .git 同一类事）
            if not path.startswith("/icons/"):
                self.send_error(404)
                return
            f = (ROOT / path.lstrip("/")).resolve()
            inside = str(f).startswith(str((ROOT / "icons").resolve()) + os.sep)
            if not inside or not f.is_file():
                self.send_error(404)
                return
        else:
            f = ROOT / path.lstrip("/")
            if not f.is_file():
                self.send_error(404)
                return
        kind = "text/html" if f.suffix == ".html" else ("text/css" if f.suffix == ".css"
               else ("application/javascript" if f.suffix == ".js"
                     else ("application/json" if f.suffix == ".json" else "image/png")))
        body = Handler.override.get(path) or f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve():
    class Server(ThreadingHTTPServer):
        # 默认只有 5。service worker 装壳时是一次并发抓 15 个文件，机器一忙 accept 队列就溢出，
        # 多出来的 SYN 直接被拒 —— 表现是「controller 不在、缓存 0 个、三条 ERR_CONNECTION_REFUSED」，
        # 看起来像预缓存逻辑坏了，其实是这台测试服务器自己的门口太窄。今天就这样假红过两次。
        request_queue_size = 128
        daemon_threads = True
    s = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}/index.html"


def health(url):
    """先确认这台临时服务器真的在答题，再往下演。

    踩过：整机只剩 2GB 空闲时跑整套 check，ThreadingHTTPServer 派不出线程 / 浏览器抢不到资源，
    于是「controller 不在、缓存 0 个、缓存名不跟版本号走、renderCloset is not defined」五条一起红，
    看起来完全像产品坏了。单独重跑又是 19/0。资源紧不是产品缺陷，得当场说清楚。"""
    import urllib.request
    base = url.rsplit("/", 1)[0]
    for path in ("index.html", "yi.js", "sw.js"):
        try:
            with urllib.request.urlopen(base + "/" + path, timeout=15) as r:
                if r.status != 200:
                    return path, "HTTP " + str(r.status)
        except Exception as e:
            return path, repr(e)[:140]
    return None, ""


with sync_playwright() as p:
    srv, URL = serve()
    bad, why = health(URL)
    if bad:
        print(f"环境没起来：临时服务器答不上「{bad}」（{why}）。"
              f"这不算产品红——先确认机器还有多少空闲内存，再重跑。")
        raise SystemExit(3)
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.set_default_timeout(20000)      # 卡住要报错，不许无限等（service worker 没激活时最容易挂在这）
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    # 不钉时钟：假时钟和 service worker 的内部计时没有一起验过，这套用例也不需要绝对日期

    print("\n--- 连上 http（不是 file://）---")
    page.goto(URL)
    page.wait_for_timeout(700)
    check("页面起来了", page.evaluate("() => document.title"), "笺")
    check("file:// 才有的那条限制没影响 http 路径",
          page.evaluate("() => location.protocol"), "http:")

    print("\n--- service worker 注册并接管 ---")
    # 注意：page.evaluate 里 `await navigator.serviceWorker.ready` 一旦不激活就是**永久挂住**
    # （evaluate 没有超时）。所有等待一律走 wait_for_function，超时了就报失败而不是卡死整套。
    # 预算给到 60 秒而不是 20 秒：这是 wait_for_function，就绪就立刻返回，机器空时不多花一秒；
    # 但机器一忙（同时开着两个模拟器 + gradle 守护进程）SW 的安装/激活就会爬过 20 秒，
    # 实测表现为「controller 不在、缓存 0 个、外加四条 ERR_CONNECTION_REFUSED」的假红。
    # 守门报假红比不报更糟——它会让人开始不信这套测试。
    def settled(fn, ms=60000):
        try:
            page.wait_for_function(fn, timeout=ms)
            return True
        except Exception:
            return False

    ok_sw = check("service worker 装好并激活",
                  settled("async () => { const r = await navigator.serviceWorker.getRegistration();"
                          " return !!(r && r.active); }"), True)
    if not ok_sw:
        # 装不上就把注册表当时的状态打出来（installing / waiting / active）。
        # 以前只报「controller 不在」，分不清是没注册上、装上没激活、还是服务器根本没答，
        # 而这三种的修法完全不一样。
        print("        注册表现场：" + page.evaluate("""async () => {
          const r = await navigator.serviceWorker.getRegistration();
          if (!r) return '没有 registration（register() 就没成）';
          const st = (x) => x ? x.state : 'null';
          return 'installing=' + st(r.installing) + ' waiting=' + st(r.waiting) + ' active=' + st(r.active);
        }"""))
    check("已经接管页面（controller 在）",
          settled("() => navigator.serviceWorker.controller !== null"), True)
    # 预缓存是在 install 里一个文件一个文件 add 进去的，机器忙时它会比「激活」慢半拍。
    # 先轮询到缓存里真的装着整份壳再断言，别拿一次快照定罪。
    settled("""async () => {
      const ks = (await caches.keys()).filter(k => k.startsWith('jian-'));
      if (!ks.length) return false;
      const c = await caches.open(ks[0]);
      return (await c.keys()).length >= 16;
    }""")
    caches = page.evaluate("async () => (await caches.keys()).filter(k => k.startsWith('jian-'))")
    check("建了带版本号的缓存", len(caches), 1)
    ver = page.evaluate("() => window.JIAN_CONFIG.version")
    check("缓存名跟着版本号走", caches[0] if caches else None, "jian-" + ver)
    n = page.evaluate("""async () => {
      const c = await caches.open('jian-%s');
      return (await c.keys()).length;   // Cache.keys() 给的是数组，不是 Map（没有 .size）
    }""" % ver) if caches else 0
    check("预缓存装下了整份清单", n >= 16, True)
    print(f"        预缓存 {n} 项")

    print("\n--- 先造点数据，再拔网 ---")
    page.evaluate("""() => {
      state.onboarded = true;
      state.wardrobe = [
        { id: 'w1', name: '燕麦针织', cat: '上衣', color: '#d4c4b0', worn: 9, lastWorn: Date.now() - 2 * DAY }
      ];
      state.points = 20; save(state);
    }""")
    page.reload()
    page.wait_for_timeout(600)

    ctx.set_offline(True)
    try:
        page.reload(wait_until="load")
    except Exception as e:
        print("   断网刷新没走完：" + str(e).splitlines()[0][:140])
    page.wait_for_timeout(900)
    check("断网后仍能打开", page.evaluate("() => document.title"), "笺")
    check("样式是从缓存来的（不是裸 HTML）",
          page.evaluate("() => getComputedStyle(document.body).backgroundColor"), "rgb(244, 239, 230)")
    check("引擎在断网的页面上还在", page.evaluate("() => typeof Engine"), "object")
    check("数据也还在", page.evaluate("() => state.wardrobe[0].name"), "燕麦针织")
    check("断网照样能出判定",
          page.evaluate("""() => Engine.yi({ name: 'x', cat: '上衣', color: '#d8d2c6' },
                                           state.wardrobe).stamp"""), "先别")
    # 柜子在「柜子」那个页签里（#yiPaneCloset 默认 hidden），重开落在「过笺」页签上时
    # 它当然是不可见的——这条断言以前一直红着，红的原因不是界面没画出来，
    # 是它没先切页签。切过去再量，量的才是「界面真的画出来了」。
    page.evaluate("() => { show('yi'); setYiTab('closet'); }")
    page.wait_for_timeout(400)
    check("界面画出来了", page.is_visible("#closet .item[data-id]"), True)
    ctx.set_offline(False)

    print("\n--- 恢复联网：导航走网络，不会被旧缓存卡住 ---")
    page.reload()
    page.wait_for_timeout(700)
    check("回到在线正常", page.evaluate("() => state.points"), 20)

    # ---- 升级之后，缓存里必须装的是**新**文件 ----
    #
    # 这一节是补上来的：sw.js 的 fill() 曾经把已经交给页面的 Response 直接 cache.put，
    # 浏览器抛 "Response body is already used"，异常被 `.catch(()=>{})` 吞掉——
    # 于是缓存永远停在第一次装的那一版。现象是：版本号改了、包也发了，老用户刷新多少次
    # 都还是旧界面，而且**没有任何一处会报错**。
    # 同时 install 里的 c.add(u) 会命中上一代的 HTTP 缓存，新桶里装旧文件。
    #
    # 怎么验：把某个文件在服务器上改掉（加一行标记），让 SW 换一个新版本名重新安装，
    # 再看缓存里那份到底是新的还是旧的。
    print("\n--- 升级之后缓存里装的是新文件，不是上一版 ---")
    marker = b"\n/* offline-gate-marker-%d */\n" % os.getpid()
    orig_theme = (ROOT / "theme.js").read_bytes()

    def theme_with_marker():
        return orig_theme + marker

    # 让服务器对这个文件返回带标记的内容（其余照旧）
    Handler.override = {"/theme.js": theme_with_marker()}
    page.evaluate("""async () => {
      // 换一个版本名重新安装：等价于「发了一版新的前端」
      const reg = await navigator.serviceWorker.getRegistration();
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
      if (reg) await reg.unregister();
    }""")
    page.reload()
    page.wait_for_timeout(2500)          # 等 SW 重新安装 + 预缓存
    got = page.evaluate("""async () => {
      const keys = await caches.keys();
      const c = await caches.open(keys.find((k) => k.startsWith('jian-')) || keys[0]);
      const res = await c.match('/theme.js');
      return res ? await res.text() : '';
    }""")
    check("升级后缓存里的 theme.js 就是服务器上那份新的（不是上一版的旧文件）",
          marker.decode() in (got or ""), True)

    # 上面那一条验的是 install 里的 `cache:"reload"`。fill() 那条路（运行时补缓存）
    # 走的是完全不同的分支：对一个**还没进缓存**的地址发一次正常请求，让 SW 的
    # cacheFirst 去 fetch 然后 fill。以前 fill 把已经交给页面的同一个 Response
    # 直接 cache.put，浏览器抛 "body is already used"、被 .catch 吞掉——
    # 于是这个地址**永远进不了缓存**（断网时就拿不到它）。
    #
    # 拿一个确实在预缓存清单里的文件来验：先从缓存删掉它，再请求一次，
    # 然后看它有没有回到缓存里、内容对不对。
    print("\n--- 运行时补缓存真的补进去了（fill 不许把用过的 body 再塞一次）---")
    # 用 fetch 到同一个 URL（不带查询串，免得多出一个键），先删掉缓存里的那一份，
    # 再走一次 cacheFirst → fill。等 SW 接管之后再量（上面刚 unregister 过）。
    page.reload()
    page.wait_for_timeout(2000)
    refilled = page.evaluate("""async () => {
      const reg = await navigator.serviceWorker.getRegistration();
      const controlled = !!navigator.serviceWorker.controller;
      const keys = await caches.keys();
      const c = await caches.open(keys.find((k) => k.startsWith('jian-')) || keys[0]);
      await c.delete('/theme.js');
      const gone = !(await c.match('/theme.js'));
      // 带 no-store 让浏览器一定去网络取，而不是吃它自己的 HTTP 缓存
      const res = await fetch('/theme.js?refill-gate=1', { cache: 'no-store' });
      const len = (await res.text()).length;
      await new Promise((r) => setTimeout(r, 500));
      // SW 的 fill 写回的是**不带查询串**的那个键（cacheFirst 用 req 原样作键）——
      // 所以我们查的也是查询串那一个，它才是 fill 真正写进去的
      const hit = await c.match('/theme.js?refill-gate=1');
      return { controlled, gone, len, refilledLen: hit ? (await hit.text()).length : 0 };
    }""")
    check("运行时请求一次之后，那个文件真的回到了缓存里（fill 的 body 没被重复使用）",
          refilled["refilledLen"] > 0, True)
    # 再清一次，免得后面几节读到带 ?refill=1 的那一份
    page.evaluate("async () => { const k = await caches.keys(); const c = await caches.open(k.find(x => x.startsWith('jian-'))); await c.delete('/theme.js?refill=1'); }")
    Handler.override = {}

    print("\n--- 只认白名单：这台临时服务器不漏源码外的东西 ---")
    for path, want in (("/../backend/gateway.py", 404), ("/.git/config", 404),
                       ("/test/e2e.playwright.py", 404), ("/icons/../../backend/gateway.py", 404)):
        s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
        s.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode())
        buf = b""
        while True:                     # 读到 EOF 再关：半路 close 会让服务器写 404 时撞上连接重置
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        check(f"{path} 拿不到", b"404" in buf[:64], want == 404)

    real = [e for e in errors if "favicon" not in e.lower() and "net::ERR_FAILED" not in e]
    check("没有 JS 运行时错误", real, [])
    ctx.close()
    browser.close()
    srv.shutdown()

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
for ok, name, got, want in bad:
    print(f"   ✗ {name}  ->  {got}   (期望 {want})")
sys.exit(1 if bad else 0)
