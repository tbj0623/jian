#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""亮暗两套主题的「纸是不是整张都翻了」审计。

为什么单独一支：深色模式漏到底这件事，单元测试与 DOM 断言都抓不住——它只有肉眼看得见。
0.6.0 里踩过一次：`body` 的两个渐变把白天的纸写死（rgba(244,239,230,.92)），
于是 data-theme="dark" 只换掉了卡片和字，屏幕上就是**黑卡片浮在米色纸**上；
底栏 .nav 与 .veil 又各写死一次，夜里底栏成了整屏唯一一条亮带。
这三处现在都走 --paper-wash / --paper-veil 变量。这支脚本守的就是「不许再写死一次」。

判法不靠像素比对（那对字体渲染太敏感），而是问浏览器要**算出来的实际颜色**：
  1. 每一屏在白天与夜里各取一次 body 的 computed background-image / -color
  2. 断言：两套主题下这两个值**不同**（翻了）且夜里那套确实更暗（真的暗纸，不是换个色相）
  3. 断言：没有任何 CSS 文件里还留着 `background: rgba(244, 239, 230` 这种写死白纸的写法
     （styles-v06.css 的变量定义处除外——那是唯一该出现白天纸色的地方）
  4. 逐屏截图到 test/screens/light-<theme>-<screen>.png，供人眼复核

用法：python test/light_audit.playwright.py
"""
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
SHOTS = ROOT / "test" / "screens"

PASS = 0
FAIL = 0
BAD = []


def check(name, ok, got=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}" + (f"  ->  {got}" if got != "" else ""))
    else:
        FAIL += 1
        BAD.append(f"{name}  ->  {got}")
        print(f"  FAIL {name}" + (f"  ->  {got}" if got != "" else ""))


SEED = """
() => {
  const now = Date.now();
  const day = 86400000;
  state.profile = { nick: '小笺', line: '把话说清楚，把日子过明白', since: now - day * 40 };
  state.closet = [
    { id: 'c1', name: '白衬衫', color: '#f2ede2', style: '通勤', note: '',
      price: 260, boughtAt: now - day * 90, brand: '无印', size: 'M',
      occasions: ['通勤', '正式'], tags: ['常穿'], worn: 18, lastWorn: now - day * 2, wearDays: [] },
    { id: 'c2', name: '黑牛津鞋', color: '#2a2723', style: '通勤', note: '',
      price: 890, boughtAt: now - day * 400, brand: '', size: '42',
      occasions: ['通勤'], tags: [], worn: 40, lastWorn: now - day * 1, wearDays: [] },
    { id: 'c3', name: '驼色大衣', color: '#c8a97e', style: '重外套', note: '',
      price: 1600, boughtAt: now - day * 300, brand: '', size: 'M',
      occasions: ['日常', '旅行'], tags: [], worn: 3, lastWorn: now - day * 200, wearDays: [] }
  ];
  state.wish = [{ id: 'w1', name: '羊绒围巾', price: 480, color: '#8f6d15', why: '', t: now - day * 20 }];
  state.outfits = [{ id: 'o1', name: '上班那套', ids: ['c1', 'c2'], occasion: '通勤', t: now - day * 5, worn: 2, lastWorn: now - day * 3 }];
  state.yanCards = [
    { id: 'y1', k: '待办', line: '周三之前把报销单交了', done: false, doneAt: null,
      when: { text: '周三之前', at: now + day * 2 }, slot: 'day', t: now - day },
    { id: 'y2', k: '要买', line: '买两盒猫罐头', done: false, doneAt: null,
      when: { text: '明天', at: now + day }, slot: 'evening', t: now - day }
  ];
  state.recipes = [{ id: 'r1', name: '番茄炒蛋', minutes: 15, level: '简单', serves: 2,
    items: ['番茄 2 个', '鸡蛋 3 个'], steps: ['打蛋', '炒'], t: now - day * 10 }];
  state.cookLog = [{ id: 'l1', name: '番茄炒蛋', t: now - day * 3, stars: 4, note: '', people: 2 }];
  state.market = [{ id: 'm1', name: '番茄', kind: '蔬菜', qty: '2 个', done: false, t: now }];
  state.weeks = [{ id: 'k1', start: now, days: [{ noon: ['番茄炒蛋'], night: [] }], note: '' }];
  state.reminders = [{ id: 'rm1', text: '交电费', at: now + day, repeat: '', done: false, fired: false, from: '' }];
  state.digest = [{ t: now - day, text: '好日子是自己过出来的。', from: '自己', mood: '平' }];
  state.people = [{ id: 'p1', name: '小周', chips: ['辣'] }];
  state.badges = [];
  state.log = [
    { t: now - day, kind: 'wear', mod: 'yi', ref: 'c1', v: 1 },
    { t: now - day * 2, kind: 'cook', mod: 'wei', ref: '番茄炒蛋', v: 1 },
    { t: now - day * 3, kind: 'yan', mod: 'yan', ref: 'y1', v: 1 }
  ];
  state.settings = Object.assign({}, state.settings, { theme: 'light' });
  save(state);
  return true;
}
"""

SCREENS = ["today", "yi", "wei", "yan", "pu", "me", "badges", "year", "settings", "search"]

# 每一屏里「应该翻纸」的容器：取它们的 computed background-color 来确认没漏
VEIL_SELECTORS = ["body", ".nav", "#app"]


def rgb_of(css):
    """把 'rgb(27, 25, 23)' / 'rgba(27, 25, 23, .96)' 取成 (r,g,b) 与 alpha。"""
    m = re.search(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\s*\)", css or "")
    if not m:
        return None
    a = 1.0 if m.group(4) is None else float(m.group(4))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), a


def luma(rgb):
    r, g, b = [c / 255 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def snapshot(pg, theme, screen):
    pg.evaluate("(t) => { THEME.set('theme', t); }", theme)
    pg.wait_for_timeout(140)
    pg.evaluate("(s) => show(s)", screen)
    pg.wait_for_timeout(200)
    out = {}
    for sel in VEIL_SELECTORS:
        out[sel] = pg.evaluate(
            """(sel) => {
                 const el = sel === 'body' ? document.body : document.querySelector(sel);
                 if (!el) return null;
                 const cs = getComputedStyle(el);
                 return { bg: cs.backgroundColor, img: cs.backgroundImage };
               }""",
            sel,
        )
    return out


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(URL, wait_until="domcontentloaded")
        pg.wait_for_function("() => typeof state !== 'undefined' && typeof show === 'function'")
        pg.evaluate(SEED)
        pg.wait_for_timeout(150)

        print("--- 两套主题的纸 ---")
        pairs = {}
        for theme in ("light", "dark"):
            pairs[theme] = snapshot(pg, theme, "today")
        # #app 只在 ≥900px 的宽窗里才有背景（手机窄窗是透明的），所以宽窗单独量一次
        pg.set_viewport_size({"width": 1100, "height": 900})
        pg.wait_for_timeout(200)
        wide = {}
        for theme in ("light", "dark"):
            pg.evaluate("(t) => { THEME.set('theme', t); }", theme)
            pg.wait_for_timeout(160)
            wide[theme] = pg.evaluate(
                "(sel) => { const cs = getComputedStyle(document.querySelector(sel)); "
                "return { bg: cs.backgroundColor, img: cs.backgroundImage }; }",
                "#app",
            )
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.wait_for_timeout(150)
        for sel in ("body", ".nav"):
            lo, da = pairs["light"].get(sel), pairs["dark"].get(sel)
            check(f"{sel} 白天有背景", lo is not None and (lo["bg"] or lo["img"]), lo)
            if not lo or not da:
                continue
            lc = rgb_of(lo["bg"]) or rgb_of(lo["img"])
            dc = rgb_of(da["bg"]) or rgb_of(da["img"])
            check(f"{sel} 两套主题颜色不同（真的翻了纸）",
                  bool(lc and dc and lc[0] != dc[0]), f"{lc[0] if lc else None} vs {dc[0] if dc else None}")
            if lc and dc:
                check(f"{sel} 夜纸比白纸暗", luma(dc[0]) < luma(lc[0]) - 0.25,
                      f"{luma(lc[0]):.2f} -> {luma(dc[0]):.2f}")
                check(f"{sel} 白纸就是 #f4efe6 那一档（回归护住白天）",
                      abs(lc[0][0] - 244) <= 3 and abs(lc[0][1] - 239) <= 3 and abs(lc[0][2] - 230) <= 3,
                      lc[0])
        # 宽窗那张「桌上的一张纸」
        lw, dw = wide["light"], wide["dark"]
        lc = rgb_of(lw["bg"]) or rgb_of(lw["img"])
        dc = rgb_of(dw["bg"]) or rgb_of(dw["img"])
        check("宽窗 #app 两套主题颜色不同", bool(lc and dc and lc[0] != dc[0]),
              f"{lc[0] if lc else None} vs {dc[0] if dc else None}")
        if lc and dc:
            check("宽窗 #app 白纸是 #f4efe6 那一档",
                  abs(lc[0][0] - 244) <= 3 and abs(lc[0][1] - 239) <= 3 and abs(lc[0][2] - 230) <= 3, lc[0])
            check("宽窗 #app 夜纸比白纸暗", luma(dc[0]) < luma(lc[0]) - 0.25,
                  f"{luma(lc[0]):.2f} -> {luma(dc[0]):.2f}")

        print("\n--- CSS 里不许再写死白天的纸 ---")
        # 判法：先剥掉注释（注释里提到历史写法不算），再看这一行是不是
        #   要么 styles-v06.css 里 --paper-* 的定义处（白天纸色的唯一出处），
        #   要么包在 var(--paper-*, <fallback>) 的 fallback 位里。
        # 除了这两种，写死 rgba(244,239,230,…) 就是「又有人把白天的纸钉进了一个不跟主题走的地方」。
        for css in sorted(ROOT.glob("styles*.css")):
            raw = css.read_text(encoding="utf-8")
            # 逐行剥注释但保留行号：/* … */ 可能跨行，用一个状态机
            in_comment = False
            for ln, line in enumerate(raw.splitlines(), 1):
                live = ""
                i = 0
                while i < len(line):
                    if not in_comment and line.startswith("/*", i):
                        in_comment = True
                        i += 2
                        continue
                    if in_comment and line.startswith("*/", i):
                        in_comment = False
                        i += 2
                        continue
                    if not in_comment:
                        live += line[i]
                    i += 1
                if not re.search(r"244\s*,\s*239\s*,\s*230", live):
                    continue
                is_var_def = css.name == "styles-v06.css" and "--paper-wash" in live or \
                    css.name == "styles-v06.css" and "--paper-veil" in live
                is_fallback = bool(re.search(r"var\(--paper-[a-z-]+\s*,\s*rgba?\(\s*244", live))
                check(f"{css.name}:{ln} 写死白纸色之处合法（变量定义 / var() fallback）",
                      is_var_def or is_fallback, live.strip()[:70])

        print("\n--- 逐屏：两套主题都渲染，且纸确实不同 ---")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        for screen in SCREENS:
            got = {}
            for theme in ("light", "dark"):
                pg.evaluate("(t) => { THEME.set('theme', t); }", theme)
                pg.wait_for_timeout(120)
                pg.evaluate("(s) => show(s)", screen)
                pg.wait_for_timeout(220)
                info = pg.evaluate(
                    """() => {
                         const on = document.querySelector('.screen.on');
                         const cs = getComputedStyle(document.body);
                         return {
                           id: on && on.id,
                           bg: cs.backgroundColor,
                           color: cs.color,
                           text: (on ? on.innerText : '').length
                         };
                       }"""
                )
                got[theme] = info
                pg.screenshot(path=str(SHOTS / f"light-{theme}-{screen}.png"), full_page=False)
                check(f"{screen} / {theme} 真的切过去了", info["id"] is not None, info["id"])
                check(f"{screen} / {theme} 有字", info["text"] > 20, info["text"])
            lc, dc = rgb_of(got["light"]["bg"]), rgb_of(got["dark"]["bg"])
            check(f"{screen} 正文色跟着翻", got["light"]["color"] != got["dark"]["color"],
                  f"{got['light']['color']} -> {got['dark']['color']}")
            if lc and dc:
                check(f"{screen} 夜里不刺眼", luma(dc[0]) < 0.30, f"{luma(dc[0]):.2f}")

        print("\n--- 深色卡片不超过纸色太多（不许出现黑卡片浮米色纸）---")
        pg.evaluate("() => THEME.set('theme', 'dark')")
        pg.evaluate("() => show('today')")
        pg.wait_for_timeout(250)
        cards = pg.evaluate(
            """() => {
                 const out = [];
                 document.querySelectorAll('.card, .sheet, .stat, .rowbtn').forEach((el) => {
                   const cs = getComputedStyle(el);
                   const r = el.getBoundingClientRect();
                   if (r.width < 40 || r.height < 20) return;
                   out.push({ cls: el.className, bg: cs.backgroundColor, color: cs.color });
                 });
                 return out.slice(0, 24);
               }"""
        )
        check("深色下确实有卡片可量", len(cards) >= 3, len(cards))
        bad = []
        for c in cards:
            cr = rgb_of(c["bg"])
            if not cr or cr[1] < 0.5:
                continue            # 透明/半透的交给底色，不算
            if luma(cr[0]) > 0.55:
                bad.append(f"{c['cls'][:24]} {c['bg']}")
        check("深色下没有「亮卡片」", bad == [], bad[:3])

        print("\n--- 运行时错误 ---")
        check("无 JS 报错", errs == [], errs[:3])

        ctx.close()
        browser.close()

    print(f"\n亮暗审计：{PASS} 通过 / {FAIL} 失败")
    if BAD:
        print("失败项：")
        for b in BAD:
            print("  -", b)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
