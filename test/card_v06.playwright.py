# 长图 lane 的浏览器门（v0.6.0 · card_v06）。
#
# 盯的是「存成长图」这一条路的四张纸：单品档案 / 搭配 / 摘录（v0.6.0 新增的三张）
# 与年度总结（原有那一张，作为样板一起量，防止新纸把老纸带歪）。
#
# 五组断言：
#   1. 四张图各自 1080×1920，且 toDataURL 有下限（真画了东西，不是白纸）
#   2. **夜里存出来还是白天的纸** —— 全篇最关键的一条，双角度验：
#      tokenLight('--paper') 的读数，以及 canvas 左上角像素 ctx.getImageData(0,0,1,1)
#      （注意：x=0 那一列正好压着第 0 根纸纹，(0,0) 是 paper/paper2 的 50% 混合，
#       所以「纸色」这个断言取 (1,1) 那一格；(0,0) 单独断言它只是略深一点的纸，
#       仍然是亮的——把这两件事分开写，夜里变黑才会真的红。）
#   3. tokenLight 量完必须把 data-theme 还原（不许把用户的主题改掉）
#   4. 三枚「存成长图」钮存在、可见、命中区 ≥44px；数据不足时 aria-disabled="true"
#      且**不是真 disabled**，按下去要开口说话
#   5. saveLongCard 走完一遍，state 深比较前后一致、按钮文案复原、真的产生一次下载
#
# 跑法：PYTHONIOENCODING=utf-8 python test/card_v06.playwright.py
import base64
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
URL = (JIAN / "index.html").as_uri()
OUT = JIAN / "test" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

# 冻结时钟：与 e2e / me_v06 同一个锚（2026-09-17），长图右上角的日子因此确定。
CLOCK = "2026-09-17T10:00:00"
# 长图永远是白天的纸。这个值必须与 styles.css 的 :root[data-theme="light"] --paper 同值。
LIGHT_PAPER = "#f4efe6"
LIGHT_PAPER_RGB = [244, 239, 230]
# 夜里的纸（:root[data-theme="dark"] --paper）——只用来证明「长图没有跟着它走」。
DARK_PAPER = "#1b1917"

# 体积下限：四张测下来最小的那张（摘录，一句话）也有 120KB+。
# 定 60KB 是「真画了东西」的下限，不是「画得好」的标准（画得好由人眼看 png）。
MIN_PNG_BYTES = 60 * 1024

errors = []
checks = []


def check(name, got, want=True):
    """want 省略 = 只要真值；给了具体值 = 逐字比。"""
    ok = bool(got) if want is True else (got == want)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def toast_text(page):
    return page.evaluate("() => { const t = document.querySelector('.toast'); return t ? t.textContent : ''; }")


def rect_of(page, sel):
    return page.evaluate(
        "(sel) => { const b = document.querySelector(sel); if (!b) return null;"
        " const r = b.getBoundingClientRect();"
        " return { w: Math.round(r.width), h: Math.round(r.height),"
        " vis: getComputedStyle(b).visibility, disp: getComputedStyle(b).display,"
        " aria: b.getAttribute('aria-disabled'), dis: b.disabled === true,"
        " tab: b.tabIndex, text: b.textContent.trim() }; }", sel)


SEED = r"""() => {
  const DAY = 86400000, now = Date.now();
  state.onboarded = true;
  state.modules = { yi: true, wei: true, yan: true };
  state.settings = { theme: "light", font: "m" };
  state.wardrobe = [
    { id: "v1", name: "燕麦色针织开衫", cat: "上衣", color: "#d8c9b0", price: 268,
      boughtAt: now - DAY * 96, brand: "无印良品", size: "M", occasions: ["通勤", "正式"],
      tags: ["常穿"], worn: 18, lastWorn: now - DAY * 2, wearDays: [] },
    { id: "v2", name: "黑牛津鞋", cat: "鞋", color: "#2a2723", price: 890,
      boughtAt: now - DAY * 400, brand: "", size: "42", occasions: ["通勤"],
      tags: [], worn: 40, lastWorn: now - DAY * 1, wearDays: [] },
    { id: "v3", name: "驼色长大衣", cat: "外套", color: "#c8a97e", price: 1500,
      boughtAt: now - DAY * 500, brand: "某牌", size: "L", occasions: ["通勤", "正式"],
      tags: [], worn: 12, lastWorn: now - DAY * 5, wearDays: [] }
  ];
  state.clothSel = "v1";
  state.outfits = [
    { id: "o1", name: "上班那一套", ids: ["v1", "v2", "v3"], occasion: "通勤",
      note: "天冷就把大衣加上", t: now - DAY * 5, worn: 2, lastWorn: now - DAY * 3 },
    { id: "oEmpty", name: "全掉了的一套", ids: ["gone1", "gone2"], occasion: "",
      note: "", worn: 0, lastWorn: null }
  ];
  state.digest = [{ t: now - DAY, text: "好日子是自己过出来的，不是等出来的。",
                    from: "自己", mood: 2 }];
  state.yanCards = [{ k: "待办", line: "把报销单交了", when: null, done: false,
                      moved: false, wset: false }];
  state.log = [];
  state.streak = { days: 3, best: 9, last: dayStr(now) };
  save(state);
}"""

# 四张一起画。返回 png 的 dataURL 与尺寸；体积与解码字节数由 Python 这边量。
DRAW_FOUR = r"""async () => {
  const w = state.wardrobe[0], o = state.outfits[0], d = state.digest[0];
  // wr 是 wearRate()（{total, worn, pct}），不是 closetFacts()——传错那个，
  // 年图上会印出「3 件，undefined 件穿过」（本次验收时真踩到过）。
  const yb = yearBook(), wr = wearRate(), cc = closetCpw();
  const jobs = [['item', () => drawItemCard(w)], ['outfit', () => drawOutfitCard(o)],
                ['quote', () => drawQuoteCard(d)], ['year', () => drawYearCard(yb, wr, cc)]];
  const out = {};
  for (const [k, fn] of jobs) {
    const c = await fn();
    out[k] = { w: c.width, h: c.height, url: c.toDataURL('image/png') };
  }
  return out;
}"""


def png_bytes(url):
    return len(base64.b64decode(url.split(",", 1)[1]))


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                              accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
    page.clock.install(time=CLOCK)
    page.goto(URL)
    page.wait_for_timeout(700)
    page.click("#go")
    page.wait_for_timeout(250)
    page.evaluate(SEED)
    page.wait_for_timeout(350)

    # ==================== 1. 四张图：尺寸 + 体积 ====================
    print("\n--- 1. 四张长图：尺寸 1080×1920、toDataURL 有下限 ---")
    shots = page.evaluate(DRAW_FOUR)
    sizes = {}
    for k in ["item", "outfit", "quote", "year"]:
        s = shots[k]
        sizes[k] = png_bytes(s["url"])
        check(f"{k} 图宽 1080", s["w"], 1080)
        check(f"{k} 图高 1920", s["h"], 1920)
        check(f"{k} toDataURL 长度 > 60000（真画了东西）", len(s["url"]) > 60000, True)
        check(f"{k} 解码后的 png 字节 > 60KB", sizes[k] > MIN_PNG_BYTES, True)
        print(f"        {k}: dataURL={len(s['url']):,}  png={sizes[k]:,}")

    check("四张图的体积互不相同（不是同一张纸画了四遍）",
          len(set(sizes.values())), 4)

    # ==================== 2. 夜里仍然是白天的纸 ====================
    print("\n--- 2. 夜间模式下取到的纸色仍是 #f4efe6（双角度） ---")
    dark = page.evaluate(r"""async () => {
      const out = {};
      // 白天那一份先记下来做对照
      THEME.set('theme', 'light');
      out.lightTL = tokenLight('--paper');
      out.lightCss = getComputedStyle(document.documentElement).getPropertyValue('--paper').trim();
      // 切到夜里
      THEME.set('theme', 'dark');
      out.themeNow = document.documentElement.dataset.theme;
      out.darkCss = getComputedStyle(document.documentElement).getPropertyValue('--paper').trim();
      // 角度一：tokenLight 的读数
      out.darkTL = tokenLight('--paper');
      out.themeAfterToken = document.documentElement.dataset.theme;
      // 角度二：真的画一张，量像素
      const w = state.wardrobe[0], o = state.outfits[0], d = state.digest[0];
      const cvs = [await drawItemCard(w), await drawOutfitCard(o), drawQuoteCard(d),
                   drawYearCard(yearBook(), wearRate(), closetCpw())];
      const px = (cv, x, y) => {
        const dd = cv.getContext('2d').getImageData(x, y, 1, 1).data;
        return [dd[0], dd[1], dd[2], dd[3]];
      };
      // x=0 那一列是纸纹本身（paper 与 paper2 的 50% 混合），所以「纸色」取 (1,1)。
      out.darkPx = cvs.map((cv) => ({ corner: px(cv, 0, 0), paper: px(cv, 3, 3),
                                      bottom: px(cv, 540, 1900) }));
      out.darkLen = cvs.map((cv) => cv.toDataURL('image/png').length);
      out.themeAfterDraw = document.documentElement.dataset.theme;
      // 白天再画一遍，逐像素对齐
      THEME.set('theme', 'light');
      const cvs2 = [await drawItemCard(w), await drawOutfitCard(o), drawQuoteCard(d),
                    drawYearCard(yearBook(), wearRate(), closetCpw())];
      out.lightPx = cvs2.map((cv) => ({ corner: px(cv, 0, 0), paper: px(cv, 3, 3),
                                        bottom: px(cv, 540, 1900) }));
      return out;
    }""")

    check("切到夜里之后 data-theme 真的是 dark（这条断言先自证前提）", dark["themeNow"], "dark")
    check("夜里的 --paper 令牌确实是 #1b1917（对照，证明它真的会翻）", dark["darkCss"], DARK_PAPER)
    # 角度一：tokenLight
    check("夜里的 tokenLight('--paper') 仍是 #f4efe6", dark["darkTL"], LIGHT_PAPER)
    check("白天与夜里的 tokenLight('--paper') 返回值相同",
          [dark["lightTL"], dark["darkTL"]], [LIGHT_PAPER, LIGHT_PAPER])
    # 角度二：像素
    for i, k in enumerate(["item", "outfit", "quote", "year"]):
        check(f"夜里 {k} 的纸色像素 (3,3) 是 {LIGHT_PAPER_RGB}",
              dark["darkPx"][i]["paper"][:3], LIGHT_PAPER_RGB)
        check(f"夜里 {k} 的底部像素 (540,1900) 也是纸色",
              dark["darkPx"][i]["bottom"][:3], LIGHT_PAPER_RGB)
        check(f"夜里 {k} 的 (0,0) 只是纸纹那一格（仍比夜纸亮得多）",
              dark["darkPx"][i]["corner"][0] > 200, True)
        check(f"夜里 {k} 与白天 {k} 的同一像素逐值相同",
              dark["darkPx"][i]["paper"], dark["lightPx"][i]["paper"])
        check(f"夜里 {k} 与白天 {k} 的 (0,0) 也逐值相同（纸纹不随主题变）",
              dark["darkPx"][i]["corner"], dark["lightPx"][i]["corner"])
    check("整张纸没有一格是夜里的 #1b1917",
          [px[:3] for px in [d["paper"] for d in dark["darkPx"]]].count([27, 25, 23]), 0)

    # ==================== 3. tokenLight 不把主题改坏 ====================
    print("\n--- 3. tokenLight 量完把 data-theme 还原了 ---")
    theme_state = page.evaluate(r"""() => {
      const root = document.documentElement;
      const out = {};
      // 第 2 节收尾时主题停在 dark 上；这里显式再钉一次，免得两节之间的顺序
      // 变成一条隐式依赖（第一版就写成「现状（夜里）」直接读，读到的是 light，假红两条）。
      THEME.set('theme', 'dark');
      out.before = root.dataset.theme;
      tokenLight('--paper');
      out.after = root.dataset.theme;
      // 没有 data-theme 时也要还原成「仍然没有」
      const saved = root.dataset.theme;
      delete root.dataset.theme;
      out.noThemeValue = tokenLight('--paper');
      out.restoredAbsent = !Object.prototype.hasOwnProperty.call(root.dataset, 'theme');
      root.dataset.theme = saved;
      // 白天再走一遍
      THEME.set('theme', 'light');
      out.lightBefore = root.dataset.theme;
      tokenLight('--paper');
      out.lightAfter = root.dataset.theme;
      return out;
    }""")
    check("夜里调完 tokenLight，data-theme 还是 dark", theme_state["after"], "dark")
    check("没有 data-theme 时调 tokenLight 也不会凭空写一个出来",
          theme_state["restoredAbsent"], True)
    check("那种情况下取到的纸色仍是 #f4efe6", theme_state["noThemeValue"], LIGHT_PAPER)
    check("白天调完 tokenLight，data-theme 还是 light", theme_state["lightAfter"], "light")
    check("两次调用之间的 data-theme 一个字没动",
          [theme_state["before"], theme_state["lightBefore"]], ["dark", "light"])
    check("画完四张长图之后主题仍是用户选的那个（dark）",
          page.evaluate("() => { THEME.set('theme', 'dark'); return document.documentElement.dataset.theme; }"),
          "dark")
    page.evaluate("() => THEME.set('theme', 'light')")
    page.wait_for_timeout(200)

    # ==================== 4. 三枚「存成长图」按钮 ====================
    print("\n--- 4. 三枚钮：存在、可见、命中区 ≥44px ---")
    page.evaluate("() => openItem('v1')")
    page.wait_for_timeout(250)
    item_btn = rect_of(page, "#itemSaveCard")
    check("单品档案的「存成长图」在", item_btn is not None, True)
    if item_btn:
        check("单品钮可见", [item_btn["vis"], item_btn["disp"]], ["visible", "flex"])
        check("单品钮命中区高 ≥44", item_btn["h"] >= 44, True)
        check("单品钮宽 ≥44", item_btn["w"] >= 44, True)
        check("单品钮文案说得出「长图」", "长图" in item_btn["text"], True)
        check("数据齐的单品不挂 aria-disabled", item_btn["aria"], None)
        check("单品钮可聚焦（tabIndex ≥ 0）", item_btn["tab"] >= 0, True)

    page.evaluate("() => openOutfit('o1')")
    page.wait_for_timeout(250)
    outfit_btn = rect_of(page, "#outfitSaveCard")
    check("搭配详情的「存成长图」在", outfit_btn is not None, True)
    if outfit_btn:
        check("搭配钮可见", outfit_btn["disp"] in ("flex", "inline-flex"), True)
        check("搭配钮命中区高 ≥44", outfit_btn["h"] >= 44, True)
        check("搭配钮宽 ≥44", outfit_btn["w"] >= 44, True)
        check("数据齐的搭配不挂 aria-disabled", outfit_btn["aria"], None)

    # 摘录本里有两处入口：行上那枚 + 底下 wide 那枚
    dig = page.evaluate(r"""() => {
      show('yan');
      const det = document.querySelector('#yanDigestBook');
      if (det) det.open = true;
      digestOpen = true; paintDigestBody();
      const wide = document.querySelector('#dgSaveCard');
      const row = document.querySelector('#digestBody [data-dgsave]');
      const mk = (b) => {
        if (!b) return null;
        const r = b.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height),
                 vis: getComputedStyle(b).visibility, disp: getComputedStyle(b).display,
                 aria: b.getAttribute('aria-disabled'), dis: b.disabled === true,
                 tab: b.tabIndex, text: b.textContent.trim() };
      };
      return { wide: mk(wide), row: mk(row),
               rows: document.querySelectorAll('#digestBody [data-dgsave]').length };
    }""")
    check("摘录本的 wide 钮在", dig["wide"] is not None, True)
    if dig["wide"]:
        check("摘录 wide 钮可见", dig["wide"]["vis"], "visible")
        check("摘录 wide 钮命中区高 ≥44", dig["wide"]["h"] >= 44, True)
        check("摘录 wide 钮宽 ≥44", dig["wide"]["w"] >= 44, True)
        check("有摘录时不挂 aria-disabled", dig["wide"]["aria"], "false")
    check("每一行摘录都带一枚「存图」", dig["rows"], 1)
    if dig["row"]:
        check("行上那枚「存图」命中区 ≥44×44",
              [dig["row"]["w"] >= 44, dig["row"]["h"] >= 44], [True, True])
        check("行上那枚「存图」不是真 disabled", dig["row"]["dis"], False)

    # ==================== 5. 数据不足时：aria-disabled 且按下去要说话 ====================
    print("\n--- 5. 数据不足：aria-disabled=true、不是真 disabled、按下去开口 ---")

    # (a) 搭配一件都不剩
    page.evaluate("() => openOutfit('oEmpty')")
    page.wait_for_timeout(250)
    empty_outfit = rect_of(page, "#outfitSaveCard")
    check("空搭配那枚钮仍然在 DOM 里（不是被藏起来）", empty_outfit is not None, True)
    if empty_outfit:
        check("空搭配 aria-disabled=true", empty_outfit["aria"], "true")
        check("空搭配不是真 disabled（读屏器要问得到）", empty_outfit["dis"], False)
        check("空搭配仍可聚焦", empty_outfit["tab"] >= 0, True)
        check("空搭配钮的命中区仍 ≥44", empty_outfit["h"] >= 44, True)
    page.evaluate("() => document.querySelector('#outfitSaveCard').click()")
    page.wait_for_timeout(400)
    t_empty_outfit = toast_text(page)
    check("按空搭配那枚钮会开口（不是静默）", len(t_empty_outfit) > 0, True)
    check("那句话里说了「画不成」或「不在柜里」",
          ("画不成" in t_empty_outfit) or ("不在柜里" in t_empty_outfit), True)

    # (b) 摘录本空着
    page.evaluate(r"""() => {
      state.digest = []; save(state);
      show('yan');
      const det = document.querySelector('#yanDigestBook');
      if (det) det.open = true;
      digestOpen = true; paintDigestBody();
    }""")
    page.wait_for_timeout(300)
    empty_dg = rect_of(page, "#dgSaveCard")
    check("空摘录本那枚 wide 钮在", empty_dg is not None, True)
    if empty_dg:
        check("空摘录本 aria-disabled=true", empty_dg["aria"], "true")
        check("空摘录本不是真 disabled", empty_dg["dis"], False)
        check("空摘录本仍可聚焦", empty_dg["tab"] >= 0, True)
        check("空摘录本命中区高 ≥44", empty_dg["h"] >= 44, True)
    check("空摘录本时行上的「存图」一枚也不留",
          page.evaluate("() => document.querySelectorAll('#digestBody [data-dgsave]').length"), 0)
    page.evaluate("() => document.querySelector('#dgSaveCard').click()")
    page.wait_for_timeout(400)
    t_empty_dg = toast_text(page)
    check("按空摘录那枚钮会开口", len(t_empty_dg) > 0, True)
    check("那句话里说了「先写一句」", "先写一句" in t_empty_dg, True)

    # 恢复数据
    page.evaluate(r"""() => {
      state.digest = [{ t: Date.now() - 86400000, text: "好日子是自己过出来的，不是等出来的。",
                        from: "自己", mood: 2 }];
      save(state);
    }""")
    page.wait_for_timeout(200)

    # (c) 单品：没有价格 / 没穿过 —— 画得出来，而且图上不编数字
    print("\n--- 5c. 单品数据薄：不编数字（—），也不崩 ---")
    thin = page.evaluate(r"""async () => {
      const bare = { id: "t1", name: "没记价格的旧外套", cat: "外套", color: "#bbbbbb",
                     price: null, boughtAt: null, brand: "", size: "", occasions: [],
                     tags: [], worn: 0, lastWorn: null, wearDays: [] };
      const c = await drawItemCard(bare);
      return { w: c.width, h: c.height, len: c.toDataURL('image/png').length };
    }""")
    check("没价格 / 没穿过的单品也画得出来 1080×1920",
          [thin["w"], thin["h"]], [1080, 1920])
    check("那张图也有体积（不是白纸）", thin["len"] > 60000, True)
    check("cpw(null 价格) 返回 null，不被 0 顶替",
          page.evaluate("() => cpw({ price: null, worn: 5 })"), None)
    check("cpw(0 次) 返回 Infinity，不是 0",
          page.evaluate("() => cpw({ price: 100, worn: 0 })") == float("inf"), True)

    # ==================== 6. 页面里没有多余的报错 ====================
    print("\n--- 6. 存图链路：真下载 + state 没被改坏 ---")
    page.evaluate("() => { THEME.set('theme', 'light'); openItem('v1'); }")
    page.wait_for_timeout(300)
    before_state = page.evaluate("() => JSON.stringify(state)")
    # 不许把上一步的旧 toast 算作这次下载的反馈。
    page.evaluate("() => document.querySelector('#toasts').replaceChildren()")
    with page.expect_download(timeout=20000) as dl:
        page.click("#itemSaveCard")
    got = dl.value
    fname = got.suggested_filename
    # 提示只有 5.2 秒：下载落盘/文件大小读取可能较慢，必须在读磁盘之前取证。
    save_toast = ""
    try:
        page.wait_for_function("() => !!document.querySelector('#toasts .toast')", timeout=2500)
        save_toast = toast_text(page)
    except Exception:
        pass
    fsize = pathlib.Path(got.path()).stat().st_size if got.path() else 0
    page.wait_for_timeout(600)
    after_state = page.evaluate("() => JSON.stringify(state)")

    check("点「存成长图」真的产生了一次下载", len(fname) > 0, True)
    check("文件名是「衣笺-单品-…-日期.png」那一套",
          [fname.startswith("衣笺-单品-"), fname.endswith(".png")], [True, True])
    check("文件名里带着这件衣服的名字（群里按文件名找图）",
          "燕麦色针织开衫" in fname, True)
    check("下载下来的 png > 60KB", fsize > MIN_PNG_BYTES, True)
    check("state 前后深比较一致", before_state == after_state, True)
    btn_after = page.evaluate(
        "() => ({ text: document.querySelector('#itemSaveCard').textContent.trim(),"
        " busy: document.querySelector('#itemSaveCard').classList.contains('busy') })")
    check("按钮文案复原成「存成长图」", btn_after["text"], "存成长图")
    check("按钮的 busy 类被摘掉", btn_after["busy"], False)
    check("存完说了一句话", len(save_toast) > 0, True)

    # 文件名口径：三处各自的前缀
    names = page.evaluate(r"""() => [
      longFileName('衣笺-单品', '燕麦色针织开衫'),
      longFileName('衣笺-搭配', '上班那一套'),
      longFileName('言笺-摘录', '好日子是自己过出来的')
    ]""")
    check("三个文件名前缀各自对得上",
          [n.split("-")[0] + "-" + n.split("-")[1] for n in names],
          ["衣笺-单品", "衣笺-搭配", "言笺-摘录"])
    check("文件名里没有斜杠/冒号这类非法字符",
          [("/" in n or ":" in n or "\\" in n) for n in names], [False, False, False])
    check("名字两端没有空白（空格会被换成去掉）",
          page.evaluate("() => longFileName('衣笺-单品', '  带 空 格  ')").count(" "), 0)

    # 空名字要有兜底
    check("空名字也生得出文件名", page.evaluate("() => longFileName('衣笺-单品', '')"), None) \
        if False else check("空名字也生得出文件名（不抛、不空）",
                            page.evaluate("() => { const s = longFileName('衣笺-单品', '');"
                                          " return s.length > 8 && s.endsWith('.png'); }"), True)

    # ==================== 7. 宋体真的用上了 ====================
    print("\n--- 7. 宋体标题真的进了 canvas 的 font ---")
    fonts = page.evaluate(r"""async () => {
      const proto = CanvasRenderingContext2D.prototype;
      const d = Object.getOwnPropertyDescriptor(proto, 'font');
      const seen = [];
      Object.defineProperty(proto, 'font', {
        configurable: true,
        get() { return d.get.call(this); },
        set(v) { seen.push(String(v)); d.set.call(this, v); }
      });
      try {
        await drawItemCard(state.wardrobe[0]);
        await drawOutfitCard(state.outfits[0]);
        let q = null;
        try { q = drawQuoteCard({ t: Date.now(), text: "一句话", from: "", mood: 0 }); } catch (_) {}
        drawYearCard(yearBook(), wearRate(), closetCpw());
      } finally {
        Object.defineProperty(proto, 'font', d);
      }
      return seen;
    }""")
    check("画的时候确实设置过 font", len(fonts) > 0, True)
    check("用到了宋体那一串（Songti SC）",
          any('"Songti SC"' in f for f in fonts), True)
    check("宋体那一串与 CARD.SERIF 逐字一致",
          page.evaluate("() => CARD.SERIF"), '"Songti SC","STSong","Noto Serif SC","SimSun",serif')
    check("标题用的是 ≥80px 的宋体（不是正文尺寸混过去）",
          any(('"Songti SC"' in f) and int(f.split("px")[0].split()[-1]) >= 80 for f in fonts), True)

    # ==================== 8. 全程无未捕获异常 ====================
    print("\n--- 8. 收尾 ---")
    errs = [e for e in errors if "pageerror" in e]
    check("全程无未捕获异常", errs, [])
    if errs:
        for e in errs[:6]:
            print("        " + e)
    check("全程没有 console.error", [e for e in errors if "console.error" in e], [])

    ctx.close()
    browser.close()

passed = len([c for c in checks if c[0]])
failed = len(checks) - passed
print(f"\n长图 lane：{passed} 通过 / {failed} 失败（共 {len(checks)} 条）")
sys.exit(1 if failed else 0)
