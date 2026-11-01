# store_shots.py — 拍 Google Play 的手机截图：1080×2340，五张，拍的是真界面。
#
# 口径（写死在这里，别每次凭记忆）：
#   视口 360×780、deviceScaleFactor 3 → 出来正好 1080×2340（Play 收 9:16~2:3 之间）
#   拍**视口**而不是全页：Play 的截图就是手机屏的样子，底栏本来就该压在底部；
#   全页拼接反而会把 position:fixed 的底栏画在图中间（capture_review.py 里那个坑）。
#   内容用 App 自己的「填示例」按钮造，不是手搓的假数据——审图的人看到的就是新用户会看到的。
#
# 运行：PYTHONIOENCODING=utf-8 python test/store_shots.py
import base64
import pathlib

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
OUT = JIAN / "store" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# 取景不合格的那几格攒起来，最后一起报——拍完再说「有一张是废的」不如不拍完。
BAD = []
URL = (JIAN / "index.html").as_uri()
PHOTO = JIAN / ".impeccable" / "review" / "garment-photo.jpg"

# 衣笺要一张真照片才好看；柜里其余几件用色块（App 没照片时就是这么画的）
SEED = """() => {
  const d = Date.now(), DAY = 86400000;
  state.onboarded = true; state.modules = { yi: true, wei: true, yan: true };
  state.points = 24; state.plan = null; state.schema = 2;
  state.wardrobe = [
    { id: 'w1', name: '燕麦开衫', cat: '外套', color: '#d8c9b4', worn: 41, lastWorn: d - 2 * DAY, season: '春秋' },
    // 两件记在今天：摘要那一行要拍出「今天穿了：…」这一格（第 30 轮新加的），
    // 全记在过去就只能拍到那句「还没记过」——两句都是真话，但卖点只在前一句。
    { id: 'w2', name: '深蓝阔腿', cat: '裤装', color: '#2c3a4a', worn: 12, lastWorn: d - 3600000 },
    { id: 'w3', name: '白衬衫', cat: '上衣', color: '#f2efe9', worn: 18, lastWorn: d - 9 * DAY },
    { id: 'w4', name: '驼色大衣', cat: '外套', color: '#c4a574', worn: 3, lastWorn: d - 214 * DAY, season: '冬' },
    { id: 'w5', name: '奶咖针织', cat: '上衣', color: '#c9b39b', worn: 27, lastWorn: d - 7200000 },
    { id: 'w6', name: '灰蓝卫衣', cat: '上衣', color: '#7d8ea0', worn: 0, lastWorn: null }
  ];
  state.people = [
    { name: '我', chips: ['花生'] }, { name: '小周', chips: ['辣'] }, { name: '阿姨', chips: ['香菜', '海鲜'] }
  ];
  state.album = []; state.yanCards = []; state.lastReport = null; state.lastNew = null;
  save(state);
}"""

RUN_YI = """(dataUrl) => {
  const b = atob(dataUrl.split(',')[1]);
  const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
  runYi(new File([u], 'kaishan.jpg', { type: 'image/jpeg' }));
}"""


def shot(page, name, focus=None, pad=24, must_show=None):
    """拍一张能进商店页的图：等 toast 掉干净、把要展示的那块滚到顶上（instant，
    html{scroll-behavior:smooth} 会让普通 scrollTo 变成一段动画，等不到就拍糊）、再拍。
    `pad` 是留白：默认 24px，但那一格会把上一块的最后一行切一半留在画面顶上——
    商店图里那半截被切掉的胶囊看着就像截图事故，所以指到「这块要顶天」的图给 0。
    `must_show` 是这一格的**主行动**选择器：它必须整块落在视口里、且不被固定底栏压住。
    取景以前只靠人眼事后看图（第 57 轮就是看真图才发现「存成长图」被折掉一条边），
    而本轮已经证明过一次「画面没人看」的代价——特性图里那句假话活了二十几轮。"""
    page.wait_for_function("() => !document.querySelector('.toast')", timeout=20000)
    page.evaluate("""([sel, pad]) => {
      const el = sel ? document.querySelector(sel) : null;
      const y = el ? el.getBoundingClientRect().top + window.scrollY - pad : 0;
      window.scrollTo({ top: Math.max(0, y), behavior: 'instant' });
    }""", [focus, pad])
    page.wait_for_timeout(500)
    if must_show:
        def fit(sel):
            # 量的是**字**，不是盒子。第一版要求整枚元素可见，于是那张 452px 高的空相纸卡
            # 把上面的标题挤了出去，报出三条「构图装不下」——那是规则太粗：
            # 一张卡上半截是空白，切掉无所谓；一行字被切成半截才是事故。
            return page.evaluate("""(sel) => {
              const root = document.querySelector(sel);
              if (!root) return { ok: false, why: "这一屏找不到这个主行动" };
              const nav = document.querySelector("#nav");
              const limit = nav ? nav.getBoundingClientRect().top : window.innerHeight;
              let top = Infinity, bottom = -Infinity;
              for (const el of [root, ...root.querySelectorAll("*")]) {
                let t = ""; for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
                if (!t.trim()) continue;
                const r = el.getBoundingClientRect();
                if (!r.height || !el.getClientRects().length) continue;
                top = Math.min(top, r.top); bottom = Math.max(bottom, r.bottom);
              }
              if (top === Infinity) { const r = root.getBoundingClientRect(); top = r.top; bottom = r.bottom; }
              return { ok: top >= 0 && bottom <= limit - 18, top: Math.round(top),
                       bottom: Math.round(bottom), limit: Math.round(limit),
                       h: Math.round(bottom - top) };
            }""", sel)
        got = fit(must_show)
        if not got.get("ok"):
            # 取景自己先修一次：主行动在框外哪一边，就往那边挪到刚好装下（留 24px 呼吸）。
            # 第一版只报不修，一跑就报出四张不合格 —— 第 1 张把「选一张照片」甩到视口上方
            # 679px，等于拍的根本不是这一屏要卖的那件事；光靠人眼事后看，永远只看得见第 2 张。
            page.evaluate("""(sel) => {
              const el = document.querySelector(sel);
              if (!el) return;
              const r = el.getBoundingClientRect();
              const nav = document.querySelector("#nav");
              const limit = nav ? nav.getBoundingClientRect().top : window.innerHeight;
              let dy = 0;
              if (r.top < 0) dy = r.top - 24;
              else if (r.bottom > limit - 18) dy = r.bottom - (limit - 18) + 24;
              window.scrollTo({ top: Math.max(0, window.scrollY + dy), behavior: 'instant' });
            }""", must_show)
            page.wait_for_timeout(300)
            got = fit(must_show)
            if not got.get("ok"):
                BAD.append(f"{name}：主行动 {must_show} 修过一次仍放不下 {got}")
        # 第二条取景规矩：**不许有一行字被画面的任一条边切成半截**。
        # 第一版只管了底栏那一边，结果把底下那行推出去之后，**顶上**的标题「先问柜子。」
        # 又被切掉一半 —— 同一族缺陷换了个方向，只量一条边等于没量。
        # 第二条取景规矩：**不许有一行字被画面的任一条边切成半截**。
        # 贪心地"往那边挪一点"在密屏上会来回撞（第 4 张就是），所以改成**搜**：
        # 被切的滚动位置是一小段一小段的禁区，禁区之间必然存在干净的落点 ——
        # 在 ±320px 里每 6px 试一次，取离当前最近、且主行动仍然装得下的那个。
        plan = page.evaluate("""(sel) => {
          const nav = document.querySelector("#nav");
          const limit = nav ? nav.getBoundingClientRect().top : window.innerHeight;
          const rows = [];
          for (const el of document.querySelectorAll("body *")) {
            let t = ""; for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
            if (!t.trim()) continue;
            const r = el.getBoundingClientRect();
            if (!r.height || !el.getClientRects().length) continue;
            rows.push([r.top, r.bottom]);
          }
          let mTop = Infinity, mBot = -Infinity;
          if (sel) {
            const root = document.querySelector(sel);
            if (root) for (const el of [root, ...root.querySelectorAll("*")]) {
              let t = ""; for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
              if (!t.trim()) continue;
              const r = el.getBoundingClientRect();
              if (!r.height || !el.getClientRects().length) continue;
              mTop = Math.min(mTop, r.top); mBot = Math.max(mBot, r.bottom);
            }
          }
          const TOL = 10;   // 离底栏上沿不到 10px 的擦边不算切字（见下面终检用同一个数）
          const bad = (d) => rows.filter(([a, b]) => (a + d < 0 && b + d > TOL) ||
                                (a + d < limit - TOL && b + d > limit)).length;
          // 只搜**滚得到**的位置：d 是内容要往下移多少，落到滚动上是 scrollY - d，
          // 而 scrollY 最小是 0 —— 第一版没管这条边界，于是第 1 张拿到达不到的 -6 当解，
          // 实际纹丝不动，报出来还是那一行被切。
          const y = window.scrollY, max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
          let best = null;
          for (let d = -320; d <= 320; d += 6) {
            if (y - d < 0 || y - d > max) continue;
            if (bad(d)) continue;
            if (sel && !(mTop + d >= 0 && mBot + d <= limit - 18)) continue;
            if (!best || Math.abs(d) < Math.abs(best)) best = d;
          }
          return { best, now: bad(0), limit: Math.round(limit), rows: rows.length };
        }""", must_show)
        if plan.get("best"):
            # best 是「画面内容要往下移多少像素」（数学里 top + d），落到滚动上就是反号。
            page.evaluate("(d) => window.scrollTo({ top: Math.max(0, window.scrollY - d), behavior: 'instant' })", plan["best"])
            page.wait_for_timeout(250)
        left = page.evaluate("""() => {
          const nav = document.querySelector("#nav");
          const limit = nav ? nav.getBoundingClientRect().top : window.innerHeight;
          const who = [];
          for (const el of document.querySelectorAll("body *")) {
            let t = ""; for (const c of el.childNodes) if (c.nodeType === 3) t += c.nodeValue;
            if (!t.trim()) continue;
            const r = el.getBoundingClientRect();
            if (!r.height || !el.getClientRects().length) continue;
            if ((r.top < 0 && r.bottom > 10) || (r.top < limit - 10 && r.bottom > limit))
              who.push(t.trim().slice(0, 14) + "@" + Math.round(r.top) + ".." + Math.round(r.bottom));
          }
          return who;
        }""")
        if left:
            BAD.append(f"{name}：还有 {len(left)} 行字被画面边切成半截（主行动与它挤不下同一框，要改构图）：{left}")
    page.screenshot(path=str(OUT / name))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_context(viewport={"width": 360, "height": 780},
                                   device_scale_factor=3).new_page()
        page.goto(URL)
        page.wait_for_timeout(900)
        page.evaluate(SEED)
        page.reload()
        page.wait_for_timeout(900)

        # 1) 衣笺：柜子里有东西、选中一件。商店材料里这张的说明是「衣笺（含柜子）」，
        # 所以要把柜子那块滚进画面——停在首屏就是一张空纸，看不出这是个有柜子的 App。
        # 框在摘要那一格：它上面是「柜里几件 / 今天穿了什么」，往下正好带出搜索框与瓷砖。
        page.evaluate("() => { state.clothSel = 'w5'; save(state); show('yi'); renderCloset(); }")
        page.wait_for_timeout(600)
        # 这一屏卖的是「买之前先问柜子」，主角就是那枚「选一张想买的衣服照片」；
        # 以前对着 #closetNote 取景，把主角甩到视口上方 679px（第 58 轮的取景自证抓出来的）。
        shot(page, "1-衣笺-先问柜子.png", "#heroCloth", 0, must_show="#heroCloth")

        # 2) 衣笺报告：真过一遍笺（跑的是引擎，不是摆拍）
        if PHOTO.exists():
            data = "data:image/jpeg;base64," + base64.b64encode(PHOTO.read_bytes()).decode()
            page.evaluate(RUN_YI, data)
            page.wait_for_function("() => state.lastReport !== null", timeout=30000)
        page.evaluate("() => { paintReport(); show('yi-report'); }")
        page.wait_for_timeout(900)
        shot(page, "2-衣笺-一张短笺.png", "#reportCard", 16, must_show="#reportQuote")

        # 3) 味笺：点 App 自己的「填示例菜单」再「排这桌」，然后把镜头对准结果那张笺
        page.evaluate("() => show('wei')")
        page.wait_for_timeout(400)
        page.click("#demoWei")
        page.wait_for_timeout(400)
        page.click("#runWei")
        # 味笺的结果只在 DOM 里（没有 state.lastWei 这种字段），所以等的是节点不是状态
        page.wait_for_function("() => document.querySelector('#weiResult .sheet, #weiResult .card') !== null",
                               timeout=30000)
        shot(page, "3-味笺-这桌能入口.png", "#weiResult", 0, must_show="#runWei")

        # 4) 言笺：「填示例聊天」→「捞成笺」，再把「猜错了能改」这一格摊开——
        #    这一屏真正的卖点不是捞得出来，而是行上那排 挪 / 时间：
        #    一张写着「已定时」，另一张正摊着快捷签和原生挑一天。
        page.evaluate("() => { state.yanView = 'kind'; show('yan'); }")
        page.wait_for_timeout(400)
        page.click("#demoYan")
        page.wait_for_timeout(400)
        page.click("#runYan")
        page.wait_for_function("() => state.yanCards.length > 0", timeout=30000)
        page.evaluate("""() => {
          if (state.yanCards.length > 1) { state.yanCards[1].k = '待办'; state.yanCards[1].moved = true; }
          // 手动定时要定成**句子里那个**明天：眉上写「后天」而正文以「明天」开头，
          // 剥前缀那条规则就不剥（它只剥和 when.text 相同的那段），屏上看着像自相矛盾。
          const c = state.yanCards[0];
          c.when = { text: '明天', at: Date.now() + 86400000 }; c.wset = true;
          // 第三张勾掉：这一屏要顺带说清「办完的可以只清掉勾掉的」（第 27 轮）。
          if (state.yanCards.length > 2) { state.yanCards[2].done = true; }
          save(state); renderYan();
        }""")
        page.wait_for_timeout(300)
        page.evaluate("() => document.querySelectorAll('#yanOut .wtimer')[0].click()")
        page.wait_for_timeout(400)
        # 取景从搜索框起：第 48 轮给这一笺加了搜索，再对着 #yanOut 取景就把新能力和
        # 笺的抬头一起裁在画面外了（原来那张就是这么拍的）。
        shot(page, "4-言笺-落成笺.png", "#yanSearchBar", 0, must_show="#runYan")

        # 5) 册：这张的说明是「自己的数据自己拿」，那画面就该落在笺册与导出/导入上，
        #    而不是页首那张笺点卡（第 28 轮之后笺册自己会报「一共几张、能按笺看」）。
        page.evaluate("() => show('me')")
        page.wait_for_timeout(700)
        # 这张图说的是「自己的数据自己拿」，卖点就是导出/导入那两枚。第 44 轮把它们挪到
        # 笺册列表之上之后，再对着 #albumNote 取景就只拍得到存档、拍不到卖点。
        shot(page, "5-册-自己的数据自己拿.png", "#storageNote", 0, must_show="#exportData")

        browser.close()
    for f in sorted(OUT.glob("*.png")):
        print(f"  · {f.relative_to(JIAN)}  {f.stat().st_size // 1024}KB")
    for b in BAD:
        print(" FAIL 取景 " + b)
    if BAD:
        print(f"     （{len(BAD)} 处取景不合格：主行动装不进框，或有文字行被画面边切半截 —— 改构图，别将就上架）")
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
