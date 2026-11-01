# 那一页隐私政策要看过图才算发出去。
#
# 为什么单独一支脚本：`store_claims.py` 第 8 节量的是**字**（三个副本逐句两头对），
# 但字全对、页面照样可能是烂的——手机上横向出血、落款被切、编号压住正文，
# 那些都只有渲染出来才看得见。第 57 轮特性图那句假话烤在像素里活了二十几轮，
# 商店截图第 2 张把主按钮折掉一条边也是人眼事后看出来的，这一页同理。
#
# 它还顺手量了页面上那句「本页面不加载任何第三方脚本、字体、图片」：
# 那句话以前只是我写上去的一句话，现在由**真实网络面板**钉着——一个请求发往别的源就红。
#
# 运行：PYTHONIOENCODING=utf-8 python test/privacy_page.playwright.py
#   想量本地那一份而不是网上那份：JIAN_PRIVACY_URL=file:///…/docs/上架/privacy/index.html
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = os.environ.get("JIAN_PRIVACY_URL") or "https://tbj0623.github.io/jian-privacy/"
W, H, DPR = 360, 780, 3
OUT = ROOT / "test"
SHOTS = [OUT / "_privacy_page.png", OUT / "_privacy_fold.png"]

checks = []


def check(name, ok, got=""):
    checks.append((ok, name, got))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f"  ->  {got}"))


with sync_playwright() as p:
    br = p.chromium.launch(channel="msedge", headless=True,
                           args=["--disable-gpu", "--no-sandbox", "--hide-scrollbars"])
    ctx = br.new_context(viewport={"width": W, "height": H}, device_scale_factor=DPR)
    pg = ctx.new_page()
    hits = []          # 发往本站之外的每一个请求，一个都不许有
    errors = []
    # 允许的前缀：https 量的是「除了这个站还有谁」，file:// 允许同目录的兄弟文件。
    # 第一版把这行写成了一个带 and/or 的 lambda 三元式，看着像过滤器、其实一条都不记——
    # 这种红不会出现，只会安静地报绿。
    ALLOW = "file://" if URL.startswith("file://") else URL.split("//")[0] + "//" + URL.split("//")[1].split("/")[0]

    def on_req(r):
        u = r.url
        if u.startswith(("data:", "blob:")):
            return
        if not u.startswith(ALLOW):
            hits.append(u)

    def on_console(m):
        if m.type == "error":
            errors.append(m.text)

    # 控制台那句「Failed to load resource … 404」不带 URL，第一跑就只能干看着红不知道是谁 404。
    # 所以同时记每一个 4xx/5xx 的**响应**：红的现场要能自己说清是哪一条请求。
    def on_response(r):
        if r.status >= 400:
            errors.append("HTTP " + str(r.status) + " " + r.url)

    pg.on("request", on_req)
    pg.on("response", on_response)
    pg.on("console", on_console)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(600)

    check("那一页打得开，标题就是「笺 隐私政策」",
          pg.title() == "笺 隐私政策", pg.title())
    check("这一页不往站外发任何一个请求（页面上那句「不加载任何第三方」从此由网络面板钉着）",
          not hits, hits[:4])
    check("打开这一页没有任何控制台报错", not errors, errors[:3])

    n_li = pg.locator("#policy > li").count()
    check("九条条款都渲染出来了（读不到 = 选择器或页面结构变了，而不是「没有需要量的」）",
          n_li == 9, f"{n_li} 条")

    # 横向出血：手机上要左右滚才能读完一段，等于把政策藏在屏幕外
    over = pg.evaluate("""() => {
      const de = document.documentElement;
      const bad = [];
      document.querySelectorAll('h1,p,li,dt,dd,.mark').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.right > window.innerWidth + 1 || r.left < -1)
          bad.push(el.tagName + ':' + Math.round(r.left) + '~' + Math.round(r.right));
      });
      return { scroll: de.scrollWidth - de.clientWidth, bad: bad.slice(0, 4) };
    }""")
    check("360 宽之下整页不横向出血（scrollWidth == clientWidth）",
          over["scroll"] <= 0, f"多出 {over['scroll']}px")
    check("没有哪一个标题/条款/落款的方框伸出屏幕外", not over["bad"], over["bad"])

    # 落款那一格：审查员和用户要找的就是「谁负责、哪天写的」，
    # 它被底栏压住一半或压根滚不到，等于没有
    sig = pg.locator(".sig")
    sig.scroll_into_view_if_needed()
    pg.wait_for_timeout(250)
    box = sig.bounding_box()
    email = pg.locator(".sig a").first.inner_text()
    check("滚到底能看见完整落款（含邮箱，且不被屏幕下沿切掉）",
          box is not None and box["y"] >= 0 and box["y"] + box["height"] <= H + 0.5
          and "@" in email, f"box={box} email={email}")

    # 印章不许变形：它是这一族界面唯一的强调图形，被压扁就是坏掉
    m = pg.locator(".mark").bounding_box()
    check("那枚印章还是方的（宽和高差在一像素内）",
          m is not None and abs(m["width"] - m["height"]) <= 1, m)

    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(200)
    pg.screenshot(path=str(SHOTS[1]))            # 首屏
    pg.screenshot(path=str(SHOTS[0]), full_page=True)   # 整页
    ctx.close()
    br.close()

size = [str(s.name) + " " + str(s.stat().st_size) + "B" for s in SHOTS if s.exists()]
check("两张图真的落盘了（拍了没人看图等于没拍）", all(s.exists() for s in SHOTS), size)

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败（{URL}）")
print("要人眼过的两张：" + "、".join(size))
sys.exit(1 if bad else 0)
