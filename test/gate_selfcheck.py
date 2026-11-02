# 守门测试的守门测试：只改一处，对应那道守门必须 FAIL。
# 上一轮 consistency.py 28 项全绿、两端却漂了 1400 例里 306 例——因为 norm 漏字段、
# 用例覆盖不到、词表没有全表对账。所以「加一条守门项」不算完，得证明它真会炸。
#
# 这个脚本会临时改产品源码再改回来，跑完即用；不进 CI、不常驻。
# 每次改前备份、跑完 cmp 校验还原，任何一处没还原就红。
#
# **同一时间只能有一个在跑**：它改的是真源码。两条并发的自检会互相读到对方改过的文件，
# 基线直接判红（踩过：和 `npm run check` 同时跑，两边都在同一批 styles.css / yi.js 上打架）。
#
# 一条注入只跑它对应的那几道守门：CSS 注入不该顺手重跑一遍 100 秒的 e2e。
# 但每条注入都要把「归它管」的门全跑一遍——以前拆掉 500 兜底没人抓到，就是因为
# 只跑了 consistency.py，而那道门根本走不到 HTTP 外壳。
#
# 运行：PYTHONIOENCODING=utf-8 python test/gate_selfcheck.py
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENG = ROOT / "engine.js"
GATE = ROOT / "backend" / "gateway.py"
CSS = ROOT / "styles.css"
CARD = ROOT / "card.js"
APP = ROOT / "app.js"
UI = ROOT / "ui.js"
HTML = ROOT / "index.html"
API = ROOT / "api.js"
YI = ROOT / "yi.js"
YAN = ROOT / "yan.js"
ME = ROOT / "me.js"
WEI = ROOT / "wei.js"
STATE = ROOT / "state.js"
STATS = ROOT / "stats.js"
SWJS = ROOT / "sw.js"
CAPCFG = ROOT / "capacitor.config.json"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
NSC = ROOT / "android" / "app" / "src" / "main" / "res" / "xml" / "network_security_config.xml"
LLM = ROOT / "backend" / "llm.py"
RES = ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "colors.xml"
STOREDOC = ROOT / "docs" / "上架" / "商店材料.md"
PRIVPAGE = ROOT / "docs" / "上架" / "privacy" / "index.html"
PUBSCRIPT = ROOT / "scripts" / "publish-privacy.py"
CFGJS = ROOT / "config.js"
GRADLE = ROOT / "android" / "app" / "build.gradle"
SCLAIMS = ROOT / "test" / "store_claims.py"
DAVD = ROOT / "test" / "device_avd.py"
DDEEP = ROOT / "test" / "device_deeplink.py"
DSMOKE = ROOT / "test" / "release_smoke.py"
DGUARD = ROOT / "test" / "device_guards.py"
DDEAD = ROOT / "test" / "dead_controls.playwright.py"

CONSISTENCY = ("consistency", [sys.executable, "test/consistency.py"])
GATEWAY_HTTP = ("gateway_http", [sys.executable, "test/gateway_http.py"])
ENGINE_TEST = ("engine.test", ["node", "test/engine.test.mjs"])
CONTRAST = ("contrast", [sys.executable, "test/contrast.playwright.py"])
# 0.6.0 那九道浏览器门（smoke / light_audit / 六条 lane / a11y）从加进来起**一发注入都没有**，
# 于是它们全都不受自检保护——这正是 README 那句「一条没有自检的守门，等于没有守门」。
# 这一档先只接最值得守的一条（a11y 的热力图键盘替代操作），成本是每次约 160 秒；
# 其余几道等有具体靶子时再逐个接，不要为了「有自检」而凑数。
A11Y = ("a11y_v06", [sys.executable, "test/a11y_v06.playwright.py"])
PU = ("pu_v06", [sys.executable, "test/stats_v06.playwright.py"])
SMOKE = ("smoke", [sys.executable, "test/smoke.py"])
E2E = ("e2e", [sys.executable, "test/e2e.playwright.py"])
# 只跑 e2e 的某一节（test/e2e_only.py 按标记从同一份文件里现切，断言只有一份）。
# 加这一档的理由与 DEADCTLQ 一样：第 59 轮一次加 14 发注入，全走完整 e2e 是 14 × 七分钟；
# 而「窄跑绿」与「那一节绿」必须是同一件事，所以切的是同一批字节，不另抄断言。
E2E56 = ("e2e#56", [sys.executable, "test/e2e_only.py", "56"])
E2E57 = ("e2e#57", [sys.executable, "test/e2e_only.py", "57"])
E2E58 = ("e2e#58", [sys.executable, "test/e2e_only.py", "58"])
E2E59 = ("e2e#59", [sys.executable, "test/e2e_only.py", "59"])
E2E_GW = ("e2e_gateway", [sys.executable, "test/e2e_gateway.playwright.py"])
OFFLINE = ("offline", [sys.executable, "test/offline.playwright.py"])
PERF = ("perf", [sys.executable, "test/perf.playwright.py"])
BACKUP = ("backup_claim", [sys.executable, "test/backup_claim.py"])
STORE = ("store_claims", [sys.executable, "test/store_claims.py"])
DEVGUARD = ("device_guards", [sys.executable, "test/device_guards.py"])
DEADCTL = ("dead_controls", [sys.executable, "test/dead_controls.playwright.py"])
# 只跑与「全量扫」无关的那几节（§1/§2/§2b/§4/§5）：靶子在这些节里的注入不必再花十一分钟，
# 而被跳过的每一条覆盖底线会显式印 skip —— 窄跑的绿不会被当成全量的绿。
DEADCTLQ = ("dead_controls#quick", [sys.executable, "test/dead_controls.playwright.py", "--quick"])
# 再窄一档：只跑「空柜」那一趟（§1/§2/§5 照跑，§3 只扫空态那几屏）。规格第三项 = 给这道门
# 多带的环境变量：认证一条只与空柜有关的注入，不该被迫等全量扫的十一分钟。
DEADCTLN = ("dead_controls#空态", [sys.executable, "test/dead_controls.playwright.py"],
            {"JIAN_DEAD_ONLY": "空态"})
PKG = ("test_pkg", ["node", "scripts/test.mjs", "pkg"])

# 两端一致性这道门同时管着 JS 和 PY，两条都要跑
TWO_END = [CONSISTENCY, GATEWAY_HTTP, ENGINE_TEST]

# (名字, 文件, 原文, 替换文, 该管的守门[, 额外的 (文件, 原文, 替换文)…])
# 最后那个可选字段是「一起改才成为缺陷」的注入：单独动哪一处都不是 bug，凑在一起才是。
# 这一轮栽的就是这种亏——clip 和 nowrap 各自都对，合起来把守门弄瞎了。
MUTATIONS = [
    ("只改 engine 的色差阈值", ENG, "const SAME_CAT_STOP = 22;", "const SAME_CAT_STOP = 21;", TWO_END),
    ("只改 engine 的排桌口径", ENG, "荤: Math.max(1, Math.round(n * 0.5) + (n >= 4 ? 1 : 0)),",
     "荤: Math.max(1, Math.floor(n * 0.5) + (n >= 4 ? 1 : 0)),", TWO_END),
    ("只往 engine 菜库加一道", ENG, '{ n: "清炒时蔬", tags: [] },',
     '{ n: "清炒时蔬", tags: [] }, { n: "engine 私加的菜", tags: [] },', TWO_END),
    ("只往 engine 的 HIDDEN 加一条", ENG, "    香菜: [\"香菜\"], 芫荽: [\"香菜\"], 折耳根: [\"香菜\"],",
     "    香菜: [\"香菜\"], 芫荽: [\"香菜\"], 折耳根: [\"香菜\"], engine私货: [\"辣\"],", TWO_END),
    ("只把 engine 的月末钳位去掉", ENG, "    return new Date(year, month, Math.min(day, last));",
     "    return new Date(year, month, day);", TWO_END),
    # 「换回哈希序」这条以前写成 set(hits)：Python 的 set 顺序随哈希种子变，
    # 单跑三次都炸、在整套里却两次「全都过了」——一条看运气的守门等于没有守门。
    # 改成确定地把顺序倒过来：只要有一条菜同时踩中两样忌口，理由文案必然反序。
    ("只把 gateway 的理由排序倒过来（等价于退回不保序的迭代）", GATE,
     "        blocked = [h for h in hits if h in ban_set]",
     "        blocked = [h for h in list(reversed(list(hits))) if h in ban_set]", TWO_END),
    ("只把 gateway 的排桌换回银行家舍入", GATE, '        "素": max(1, _round(n * 0.5)),',
     '        "素": max(1, round(n * 0.5)),', TWO_END),
    ("只往 gateway 的 HIDDEN 加一条", GATE, '"折耳根": ["香菜"],', '"折耳根": ["香菜"], "gateway私货": ["辣"],', TWO_END),
    ("只把 gateway 的色值兜底改回 204", GATE, "        return (200, 200, 200)", "        return (204, 204, 204)", TWO_END),
    ("只把 gateway 的日期文案改回未钳位的原值", GATE, '        return {"text": f"{t.month}月{t.day}日", "at": int(t.timestamp() * 1000)}\n    if "大后天"',
     '        return {"text": f"{t.month}月{day}日", "at": int(t.timestamp() * 1000)}\n    if "大后天"', TWO_END),
    ("只把 gateway 的 500 兜底拆掉", GATE, "        except Exception as e:\n            code, obj = 500, {\"error\": f\"{type(e).__name__}: {e}\"}",
     "        except Exception:\n            raise", [GATEWAY_HTTP]),
    # 对比度：这一类缺陷连着抓到三条（金字 2.26、占位符 2.44、已完成行 2.66），
    # 所以 contrast.playwright.py 每次都把纸上的字真算一遍。下面四条是它必须抓得住的样子。
    ("把 --seal-2 换回 2.26:1 的老金", CSS, "--seal-2: #7a611f;", "--seal-2: #c9a227;", [CONTRAST]),
    ("把柜况提示行改回 opacity:.72", CSS, "#closetNote span:first-child { color: var(--ink); }",
     "#closetNote span + span { opacity: .72; }", [CONTRAST]),
    ("把已完成待办行改回 opacity:.45", CSS,
     ".check.done div { color: var(--ink-soft); text-decoration: line-through; }",
     ".check.done div { opacity: .45; text-decoration: line-through; }", [CONTRAST]),
    ("把长图的印色改回硬编码", CARD, '  再想想: token("--seal-2", "#7a611f"),', '  再想想: "#c9a227",', [CONTRAST]),
    # 「正在写这张…」那枚按钮：本轮之前是 opacity:.55，把 ink 13:1 乘成 2.29:1。
    # 它是**唯一**告诉用户「还在动、别走」的句子，所以这条靶子打的是那五行里的前三行之一。
    ("把「正在写这张…」那枚按钮改回 opacity:.55（最该读清的那句被淡掉）", CSS,
     ".btn.busy { background: var(--paper-2); color: var(--ink-soft); cursor: default; pointer-events: none; }",
     ".btn.busy { opacity: .55; pointer-events: none; }", [CONTRAST]),
    # 窄屏：整套用例一直在 430 宽跑，那 40px 的差正好够让一个按钮折成两行还没人发现。
    # .btn 加了 nowrap 之后，「标签折行」这条路只对 chip / 底栏有效；按钮的失败模式变成了
    # 「整枚按钮比屏幕还宽 → 被 .screen 的 clip 裁掉」。下面三条靶子各打一种形状：
    # 框越出纸边、框夹住了但字漏到框外、标签在框里折行。
    ("把示例按钮文案改回会撑破屏幕的长句", HTML, "id=\"demoYan\">填示例聊天</button>",
     "id=\"demoYan\">填一段示例聊天记录看看会不会撑破屏幕</button>", [E2E]),
    # 把按钮的框夹住（max-width:100%）看着像修好了「撑破屏幕」，其实字照旧跑到框外面：
    # 实测 360 下 18 字的标签左右各漏出按钮 7px，墨字压在纸上，而「框越界」那条判定从此看不见它。
    # 单独加 max-width 不是缺陷（真实标签最长 5 字，谁也截不到），单独把标签写长已经被上面那条守着，
    # 所以这条必须是**两处一起改**，它才是「标签不被裁字」那条断言独立的靶子。
    ("夹住按钮的框 + 标签写成长句（字漏到框外，框却规矩）", CSS,
     "  white-space: nowrap;\n  transition:",
     "  white-space: nowrap;\n  max-width: 100%;\n  transition:", [E2E],
     [(HTML, "id=\"demoYan\">填示例聊天</button>", "id=\"demoYan\">填一段示例聊天记录看看会不会撑破屏幕</button>")]),
    ("把底栏标签改成会折行的长句", UI, '{ id: "yi", mark: "衣", label: "衣笺" },',
     '{ id: "yi", mark: "衣", label: "衣笺历史报告" },', [E2E]),
    ("把屏角水印的出血放开、不裁横向", CSS, ".screen { position: relative; overflow-x: clip; }",
     ".screen { position: relative; }", [E2E]),
    # 改与反悔：焦点找回和「就地改不重建」都是行为约定，不是风格偏好
    ("把柜子的重渲染焦点找回拆掉", YI,
     "function renderCloset() {\n  const fk = focusKey();\n  paintCloset();\n  restoreFocus(fk);\n}",
     "function renderCloset() {\n  paintCloset();\n}", [E2E]),
    ("把改名改回整片重建", YI, "    w.name = v; save(state);",
     "    w.name = v; save(state); renderCloset();", [E2E]),
    # 第十一轮：分批贴要合并、新兜底规则两端得一起长
    ("把言笺的合并改回整片覆盖", YAN,
     "  if (fresh.length) state.yanCards = state.yanCards.concat(fresh);",
     "  state.yanCards = next;", [E2E]),
    ("只让 engine 认「有日期的把 X 做掉」", ENG,
     "        else if (t && /把.+/.test(line)) hit = \"待办\";",
     "        // 删掉这条兜底", TWO_END),
    # 360 宽时「复制整张笺」真的折过两行，而守门当时是绿的——因为它量的是空结果页。
    # 现在第 13 节先把结果态造出来，这条注入就是那道门的回归靶子。
    ("把按钮的 nowrap 摘掉", CSS, "  white-space: nowrap;\n  transition:", "  transition:", [E2E]),
    # 离线：注册拆掉，offline 那道门必须立刻演不出「断网还能打开」
    ("把 service worker 的注册拆掉", APP,
     '    navigator.serviceWorker.register("sw.js").catch(() => { });',
     "    // 拆掉注册", [OFFLINE]),
    # 判定出处：填了地址不等于接通。这条把回落时的记账拆掉，界面上就再也说不出
    # 「这张笺其实是本地算的」——e2e 第 19 节必须抓到。
    ("把 api.js 回落时的出处记账拆掉", API,
     '      } catch (e) { console.warn("yi remote", e); wentCold(e); note("yi", "local", e && e.message || String(e)); }',
     '      } catch (e) { console.warn("yi remote", e); }', [E2E]),
    # ---------- 第 14 轮加的三个功能：搜索 / 只看没办的 / 深链，每样都得有靶子 ----------
    ("把柜子搜索的过滤拆掉（框还在，输入什么都是整柜）", YI,
     '  if (q) base = base.filter((w) => (w.name + " " + w.cat',
     '  const q = closetQuery();', [E2E]),
    ("言笺「只看没办的」变成假开关（点了不筛）", YAN,
     '  let cards = state.yanHideDone ? all.filter((c) => !c.done) : all;',
     '  let cards = all;', [E2E]),
    # 这条最阴：过滤之后行号被重排，勾的是看得见的第一条，实际改掉的是另一条。
    # 界面上一切正常，数据在背后错位——所以第 21 节盯的是 data-yi 的下标，不是行数。
    ("过滤之后把行号按筛完的列表重排", YAN,
     '  const i = all.indexOf(c);',
     '  const i = cards.indexOf(c);', [E2E]),
    ("把深链的子页边界写错（#yi-report 被当成主屏 yi）", UI,
     r'  const m = String(url || "").match(/(?:^|[#/?&])(yi|wei|yan|me|pu|today)(?![\w-])/);',
     r'  const m = String(url || "").match(/(?:^|[#/?&])(yi|wei|yan|me|pu|today)(?=$|[#/?&-])/);', [E2E]),
    # 性能这道门要能抓到「量级错了」：把一次重绘变成一百次，perf 必须红。
    ("把柜子的一次重绘改成一百次（肉眼看不出，帧时间看得出来）", YI,
     'function renderCloset() {\n  const fk = focusKey();\n  paintCloset();',
     'function renderCloset() {\n  const fk = focusKey();\n  for (let i = 0; i < 100; i++) paintCloset();', [PERF]),
    # 「纸只有一种说法」：摘掉 color-scheme 这句，系统夜里 UA 控件会自己换深色皮。
    ("摘掉「只走亮色」这句声明（夜间 UA 控件会换皮）", CSS,
     "  color-scheme: light;\n", "", [E2E]),
    # 笺册那行的两条命门：存的时候存没存整张笺、点的时候复制的是不是它。
    # 第二条尤其阴：text 与 quote 一模一样的味笺行会让「只复制标题」的错混过去，
    # 所以 e2e 第 24 节点的是衣笺那一行。
    ("笺册点行时复制的是标题不是整张笺", ME,
     '      const body = (a && (a.text || a.quote)) || "";',
     '      const body = (a && a.quote) || "";', [E2E]),
    ("衣笺进笺册时不存整张笺的文本", YI,
     'state.album.unshift({ type: "yi", t: Date.now(), stamp: r.stamp, quote: r.quote, text: reportText(r) });',
     'state.album.unshift({ type: "yi", t: Date.now(), stamp: r.stamp, quote: r.quote });', [E2E]),
    # ---------- 衣笺闭环「记进柜子」的四条命门 ----------
    ("记进柜子不挡重复（连点三次就加三件）", YI,
     '  if (closetHasReportItem()) { toast("这件已经在柜里了"); return; }',
     '  // 不挡重复', [E2E]),
    ("记进柜子时不清搜索（新件被筛到看不见，像点了没反应）", YI,
     '  const sq = $("#clothSearch");\n  if (sq) sq.value = "";',
     '  const sq = $("#clothSearch");', [E2E]),
    ("记进柜子的撤销是假的（按了什么都没回去）", YI,
     '    state.wardrobe = state.wardrobe.filter((w) => w.id !== it.id);',
     '    state.wardrobe = state.wardrobe.slice();', [E2E]),
    # 这条是「布尔谎称」那一类：入柜时写一个布尔、按钮只看那个布尔，
    # 于是从柜子里把那件删掉之后，报告页还一直显示「已在柜里」。
    ("入柜状态改存布尔（从柜里删掉之后按钮再也不活）", YI,
     '  const id = state.lastReport && state.lastReport.closetId;\n  return !!(id && state.wardrobe.some((w) => w.id === id));',
     '  return !!(state.lastReport && state.lastReport.closetAdded);', [E2E],
     [(YI, '  r.closetId = it.id;', '  r.closetAdded = true;')]),
    # ---------- 味笺「上一桌」留得住：四条命门 + 一条外来数据的门 ----------
    ("排完不存这一桌（重开就什么都没有）", WEI,
     '  state.lastWei = { menu, mode: state.weiMode, n: state.people.length, t: Date.now(), r, talk };',
     '  // 不存', [E2E]),
    ("味笺那一屏永远给引导（存了也不读）", WEI,
     '  if (w && w.r) {',
     '  if (false) {', [E2E]),
    ("菜单文本不跟着重开（结果在、框空了，「改过了」就成了谎话）", APP,
     '  $("#menu").value = state.weiMenu || "";',
     '  // 不回填菜单', [E2E]),
    ("「按现在的重排」偷偷不扣点", WEI,
     '  if (rw) rw.onclick = () => runWei();',
     '  if (rw) rw.onclick = () => runWei({ free: true });', [E2E]),
    ("外来备份里的 lastWei 不做校验", STATE,
     '  if (!lwr || JSON.stringify(lwr).length > 80000) delete s.lastWei;',
     '  if (false) delete s.lastWei;', [E2E]),
    # ---------- 味笺读菜库 tags 认成分（小笼包 忌猪肉）：两端各拆一次 ----------
    # 这条缺陷的可怕之处在于「两端一起对」：拆掉任何一端，另一端的结论还带着猪肉，
    # 所以 consistency 必红；同时 engine.test 的三条断言与自洽不变式也要红——
    # 推荐不推小笼包、判定却说它安全，这种自相矛盾只有一端拆掉时才现形。
    ("只把 engine 的判定和菜库 tags 断开", ENG,
     "      if (dish.includes(d.n)) (d.tags || []).forEach((x) => hits.add(x));",
     "      if (false) (d.tags || []).forEach((x) => hits.add(x));", TWO_END),
    ("只把 gateway 的判定和菜库 tags 断开", GATE,
     "        for dn, dtags in DISH_TAGS:",
     "        for dn, dtags in []:", TWO_END),
    # ---------- 排过的桌（第 27 节）：七条命门 ----------
    ("排完不记这一桌（那一栏永远是空的）", WEI,
     "    rememberWei(menu);",
     "    // 不记", [E2E]),
    ("同一桌再排一次留两行几乎一样的签", WEI,
     "  const hist = (state.weiHist || []).filter((h) => h && h.menu !== menu);",
     "  const hist = state.weiHist || [];", [E2E]),
    ("点一签不回填菜单（看着没反应）", WEI,
     '  el.value = h.menu;\n  el.dispatchEvent(new Event("input"));',
     '  el.dispatchEvent(new Event("input"));', [E2E]),
    # 这条最贵：拿回菜单只是把文本填回去，重排是一次新判定。
    # 替用户按下「排这桌」就是替他花笺点。
    ("点一签偷偷替用户重排（扣了他的笺点）", WEI,
     '  el.value = h.menu;\n  el.dispatchEvent(new Event("input"));',
     '  el.value = h.menu;\n  el.dispatchEvent(new Event("input"));\n  runWei();', [E2E]),
    ("忌口不再收起来（一桌五人各忌一样，提示里说不完）", WEI,
     "`忌 ${chips.slice(0, 2).join", "`忌 ${chips.slice(0, 9).join", [E2E]),
    # 密度这条是「看着定的」就得有靶子：把忌口写回签上，签变成 277px 一枚、
    # 8 桌砌出 370px 的一堵墙——第 13 节那两条预算（一签 ≤150px、整栏 ≤200px）必须红。
    ("把忌口写回签上（一墙 370px，把「排这桌」推出手感区）", WEI,
     ' 道</button>', ' 道 · ${esc(weiHistBan(h))}</button>', [E2E]),
    # ---------- 接上模型之后新增的三条命门（e2e 第 29 节） ----------
    # 模型白认一场（回了 200 却不用）是这一类功能最体面的失败：界面看着正常，
    # 只是永远显示「想买的这件 / 上衣」。所以断言钉的是「界面上到底改了没有」。
    ("认出来的名字不用（模型白认一场）", YI,
     "        if (seen.name && !fromLink) item.name = seen.name;",
     "        if (seen.name && !fromLink) item.name = item.name;", [E2E]),
    # 0.6.0 补的一条同族命门：用户自己给的名字（深链/言笺「寄去衣笺」带过来的）不许被模型改掉。
    # 这一条与上一条是一对：只拆上一条 → 模型的名字进不来（模型白认一场）；
    # 只拆这一条 → 用户写的那几个字被模型猜的名字盖掉（用户说的话不算数）。
    ("用户自己带过来的名字被模型盖掉", YI,
     "      const fromLink = !!(typeof pendingNewName === \"string\" && pendingNewName);",
     "      const fromLink = false;", [E2E]),
    ("抄回来的字不落进聊天框（点了像没反应）", APP,
     '    if (!r || !(r.text || "").trim()) {',
     "    if (true) {", [E2E]),
    # 这条一开始是道假门：e2e 钉的是 shrink(f,512) 与 shrink(f,4000) 谁小，比的是**传进去的
    # 参数**，而调用方用的是默认值——把默认值 512 改成 4000，两个显式调用一个字节都没变，
    # 门照旧绿。现在钉的是「网关真收到的那张图长边 ≤512」，默认值怎么改都躲不过。
    ("上传给网关的图不缩（手机原图一张就是几 MB）", API,
     "(w || 512) / Math.max(img.width || 1, img.height || 1)",
     "(w || 4000) / Math.max(img.width || 1, img.height || 1)", [E2E]),
    ("外来备份里的 weiHist 不做清洗", STATE,
     '    .filter((h) => h && typeof h === "object" && !Array.isArray(h) && typeof h.menu === "string" && h.menu.trim())',
     "    .filter((h) => h)", [E2E]),
    # 上限是一个常量（写入、收口、清洗三处都读它），所以拆这一处就等于全放开。
    ("排过的桌不再限 4 桌（上限抬到 40）", STATE,
     "const WEI_HIST = 4;", "const WEI_HIST = 40;", [E2E]),
    # ---------- 久未穿读 season / 清淡读辣 tags / 菜库两条数据：各拆一端 ----------
    # 这三条都是「两端一起对」的缺陷：任何一端单独退回旧口径，另一端的结论就不一样，
    # consistency 必红；engine.test 与 consistency 的 want 又各自钉住产品口径。
    ("只让 engine 的久未穿判定不再读 season", ENG,
     'if (s === "夏" || s === "冬") return true;',
     'if (s === "夏夏" || s === "冬冬") return true;', TWO_END),
    ("只让 gateway 的久未穿判定不再读 season", GATE,
     '    if s in ("夏", "冬"):',
     '    if s in ("夏夏", "冬冬"):', TWO_END),
    ("只把 engine 的清淡判定退回只看菜名", ENG,
     '(QINGDAN_RE.test(dish) || hits.has("辣"))', '(QINGDAN_RE.test(dish))', TWO_END),
    ("只把 gateway 的清淡判定退回只看菜名", GATE,
     '(QINGDAN_RE.search(dish) or "辣" in hits)', '(QINGDAN_RE.search(dish))', TWO_END),
    ("只把 engine 的三杯鸡 tag 摘掉", ENG,
     '{ n: "三杯鸡", tags: ["酒"] },', '{ n: "三杯鸡", tags: [] },', TWO_END),
    ("只把 gateway 的海带豆腐汤 tag 摘掉", GATE,
     '("海带豆腐汤", ["海鲜"])', '("海带豆腐汤", [])', TWO_END),
    # 导入备份／清空／原生备份回写以前各自手写一句 cancelSoon()，漏一处就是「提示说成功了，
    # 重启发现什么都没变」。而这一类在浏览器里原本根本没有靶子：写完立刻 reload，
    # 那个 600ms 定时器跟着文档一起消失（实测 Location.prototype.reload 不可拦截）。
    # 收成一个落盘入口之后，门才有可观察的东西可钉——见 e2e 第 11.5 节末尾那两条。
    ("落盘时不取消排着的防抖（刚导入的备份会被旧 state 盖回去）", STATE,
     "  cancelSoon();\n  localStorage.setItem(KEY, json);",
     "  localStorage.setItem(KEY, json);", [E2E]),
    ("清空时不取消排着的防抖（清完又被那次防抖写回来）", STATE,
     "  cancelSoon();\n  localStorage.removeItem(KEY);",
     "  localStorage.removeItem(KEY);", [E2E]),
    # ---------- 安卓壳发得出这条 http ----------
    # 第 17 轮的识图/抄截图在 APK 里走的是「壳去 fetch 用户那台 http 网关」。
    # 同一台模拟器上把两道闸逐个关掉量过（每一格都重新 cap:sync）：
    #   混合内容开 + NSC 关 → 连不上；混合内容关 + NSC 开 → 连不上；两道都开 → 在线。
    # 所以两道都承重；usesCleartextTraffic 那一行才是被 NSC 盖掉的废话，多它只会招上架追问。
    # 界面上永远只有一句「网关连不上：Failed to fetch」，看不出是配置被谁改回去了。
    ("把混合内容开关关掉（实测一关，识图在 APK 里就发不出去）", CAPCFG,
     '"allowMixedContent": true', '"allowMixedContent": false', [GATEWAY_HTTP]),
    ("把 NSC 的明文放行关掉（安卓 28+ 默认禁明文，识图在 APK 里发不出去）", NSC,
     'cleartextTrafficPermitted="true"', 'cleartextTrafficPermitted="false"', [GATEWAY_HTTP]),
    ("摘掉 manifest 上的网络安全配置引用（那份 NSC 就成了没挂上的文件）", MANIFEST,
     '\n        android:networkSecurityConfig="@xml/network_security_config"', "", [GATEWAY_HTTP]),
    ("把 usesCleartextTraffic 加回清单（有 NSC 时它被忽略，留着只招上架审查追问）", MANIFEST,
     'android:resizeableActivity="false"',
     'android:resizeableActivity="false"\n        android:usesCleartextTraffic="true"', [GATEWAY_HTTP]),
    # 一次没问通就再也不问，和「填了地址就说已指向网关」是同一笔假账的两个方向：
    # 设备上实测过冷启动第一次出网能慢到挤掉预算，那台网关明明够得着。
    ("网关头一次没问通就永远挂着「连不上」（不再试第二次）", ME,
     "      if (gwTries < 2) askGateway(true);", "      // 不再试第二次", [E2E]),
    # 反方向的命门：局域网要连得上，但不该替用户把端口开给整条街。
    ("让网关默认就监听所有网卡", GATE,
     'os.environ.get("JIAN_HOST", "127.0.0.1")', 'os.environ.get("JIAN_HOST", "0.0.0.0")', [GATEWAY_HTTP]),
    # ---------- 接进来的真密钥不能被发出去、也不能一家不行就全停 ----------
    # 仓库根目录就是网关的静态目录：deny 名单少一条，模型清单就是一个下载链接。
    # 金丝雀那一条（test/gateway_http.py）会真造一个同名文件进去，所以摘掉必红。
    ("把仓库树里的模型清单从 deny 名单摘掉（密钥能被下载走）", GATE,
     r'|(^|/)(llm_providers|providers|secrets)\.json$', "", [GATEWAY_HTTP]),
    ("一家不行不再换下一家（免费额度打满就全停）", LLM,
     'r"^(timeout|unreachable|empty|http408|http429|http5\\d\\d)$"', 'r"^$"', [GATEWAY_HTTP]),
    # 密钥进包是这一套架构最贵的一次走偏：APK 是发给陌生人的。
    ("往要发的 JS 里落一枚密钥（网关侧的密钥漏进应用包）", API,
     "window.JianAPI = (() => {",
     'window.JianAPI = (() => { const K = "sk-abcdefghij1234567890abcdef";', [GATEWAY_HTTP]),
    # 实测 glm-4v-flash 对一张纯色块回 {"name":"无"}，而品类认得挺准——照抄进柜子里，
    # 那件衣服从此叫「无」，比留着用户自己起的名字还差。
    ("模型回「无」也照样当名字用", LLM,
     "    if len(s) < 2 or NO_NAME_RE.match(s):", "    if False:", [GATEWAY_HTTP]),
    # ---------- 「先不等了」这一轮：四个方向各有一牙 ----------
    # 等远端的时候本地其实立刻能答，所以「放弃」必须真掐得掉；
    # 而没在等的时候不许给按钮，给了又不许永远不显示。
    ("按了「先不等了」其实不掐请求（判定还是要等那几秒）", API,
     "    for (const c of live) { try { c.abort(); } catch (_) { } }",
     "    // 不掐，让它自己跑完", [E2E]),
    ("放弃之后这一轮还去发第二枪（用户等于又等了一遍）", API,
     "    if (givenUp) throw new Error(GAVE_UP);   // 这一轮用户已经放弃了，别再让他等第二遍",
     "    // 不看这个记号", [E2E]),
    ("那颗「先不等了」永远不显示（遮罩又变回只能干等）", UI,
     "  if (off) off.hidden = !(on && window.JianAPI && JianAPI.remoteOn());",
     "  if (off) off.hidden = true;", [E2E]),
    # 少这一条 CSS，[hidden] 会被 .btn 的 inline-flex 盖掉：没在等的时候按钮也露着。
    # 断言看的是 offsetParent（看不看得见），查 .hidden 属性的话这条就抓不到。
    ("摘掉 .veil-off[hidden] 那条（.btn 的 inline-flex 会盖过 hidden）", CSS,
     ".veil-off[hidden] { display: none; }", "", [E2E]),
    # 遮罩是「只在操作中出现」的面：整片扫描和窄屏那两条都扫不到它，所以它自己那几条
    # 断言也得各有靶子。摘掉加粗就是从 WCAG 大字档掉回正文档——淡到的 --seal-2 只有 4.20:1。
    ("摘掉遮罩那颗章的加粗（动画淡下去那一档对比度不够）", CSS,
     "  font-size: calc(22px * var(--fs-scale, 1)); font-weight: 700; color: var(--seal);",
     "  font-size: calc(22px * var(--fs-scale, 1)); color: var(--seal);", [CONTRAST]),
    ("遮罩卡的最小宽度顶破 360 的屏", CSS,
     "  min-width: 180px; max-width: 78vw; padding: 22px 24px;",
     "  min-width: 372px; max-width: 78vw; padding: 22px 24px;", [E2E]),
    # ---------- 连不上那 30 秒的熔断 ----------
    # 「记」和「躲」是两件事，各拆一次：只拆记的那半，冷却永远不启动；
    # 只拆躲的那半，记了冷却却照旧每张去撞。两条都炸同一条时间断言，但它们是两个缺陷。
    ("连不上之后不记这笔（每张都要重等满超时）", API,
     '    if (DEAD_RE.test(String((e && e.message) || e || ""))) coldUntil = Date.now() + COLD_MS;',
     "    // 什么都不记", [E2E]),
    ("记了冷却但入口不看（躲开那步没生效）", API,
     "  const wantsRemote = () => remoteOn() && !cold();",
     "  const wantsRemote = () => remoteOn();", [E2E]),
    ("「册」不再说这几张是冷却期里本地算的", ME,
     "    : eng.cold\n", "    : false\n", [E2E]),
    # 顶栏那行小字要答「你正在看的这张笺是谁算的」。改回不带参数的 status()
    # 就变回三条路的平均近况：衣笺 通过过一次，言笺 明明回落本地，顶栏照旧写「网关」。
    ("顶栏又去看三条路的平均近况（当前这张笺说谎）", UI,
     "  const s = JianAPI.status(id || undefined);", "  const s = JianAPI.status();", [E2E_GW]),
    # ---------- 第二十轮：散文菜单、压在照片上的字、程序性焦点 ----------
    # 这一批的靶子都是「两端一起改错」那一类：只动一端的话对账门自己就红，
    # 测不出产品断言有没有牙。所以每条都配一份另一端的同款改动。
    ("整句话当菜端上桌（散文分词退回只切逗号顿号）", ENG,
     "      if (!s || NOTE_RE.test(s)) { notes.push(s || raw); return; }",
     "      if (!s) { notes.push(s || raw); return; }", [CONSISTENCY, E2E],
     [(GATE, "        if not s or NOTE_RE.search(s):", "        if not s:")]),
    ("话里的忌口只记不躲（算出来了但没进这一桌的 bans）", ENG,
     "    const bans = chipBans.concat(inferred.map((x) => x.chip));",
     "    const bans = chipBans.slice();", [CONSISTENCY, E2E],
     [(GATE, "    bans = chip_bans + [c for c, _ in inferred]", "    bans = list(chip_bans)")]),
    ("转折句不劈开（「不吃香菜但爱吃辣」连香菜一起放过）", ENG,
     "      String(seg).split(TURN_RE).forEach((clause) => {",
     "      [seg].forEach((clause) => {", [CONSISTENCY, E2E],
     [(GATE, "        for clause in TURN_RE.split(seg):", "        for clause in [seg]:")]),
    # 「海鲜」这两个字：HIDDEN 与 CHIP_MAP 两处一起摘，才是「忌海鲜的人看到海鲜汤
    # 写着全员安全」那个缺陷——只摘一处另一条路还认得，门照旧绿。
    ("「海鲜」这个字面词从两张表里一起拿掉", ENG,
     '    海鲜: ["海鲜"],\n', "", [ENGINE_TEST, CONSISTENCY],
     [(ENG, '    海鲜: ["海鲜", "虾", "蟹",', '    海鲜: ["虾", "蟹",')]),
    # 2026-10 补的四类过敏原（蛋 / 小麦 / 大豆 / 坚果）。这两条各管一种坏法：
    #   · 芯片名从词表里掉了 → 判定退化成按菜名字面匹配，而菜名里不会写「小麦」，
    #     于是排桌页会对一个小麦过敏的人说「小笼包 · 全员安全」。
    #   · 词表里混进单字「豆」→ 土豆、四季豆、豇豆全被误判成含大豆。误伤比漏判更坏：
    #     用户一旦发现一次误报，就会开始不信所有结论。
    # 种子柜子被当成用户的账来算。那六件带着 9/4/12/2/3/15 次穿着，是给第一次打开的人
    # 看的说明书；把它当真账算，全新安装进笺谱就是「6 件里 6 件穿过 · 100% 在穿率」，
    # 年度长图还会把这句画成 1080×1920 发出去。
    # 这一发让判据永远说「不是种子」——也就是回到修之前的样子：
    # 出厂六件被当成用户的账，「6 件里 6 件穿过 · 100% 在穿率」重新出现在笺谱上。
    # 它炸的是 stats_v06 专为这件事新加的那三条（示例柜不出现百分比 / 说清那句话 /
    # 换掉名字之后恢复算账），而不是「薄柜」那两条合成柜子的断言。
    ("出厂那六件示例衣服被当成用户的账来算（全新安装显示 100% 在穿率）", STATS,
     "  return wd.every((w) => SEED_NAMES[w.id] === w.name);",
     "  return false;", [PU]),
    # 图片地址只判前缀：`"` 原样放行就能断掉 src 属性再注入一个。
    # 这一发把结尾那句转义换回原串，smoke 里那三条 cssImg 断言会红。
    # 锚点只取结尾那半句：整行里同时有单引号和双引号，写进 Python 字符串要转义一圈，
    # 转错一次就是「注入自己语法不通」那种假炸（本文件已经踩过一次，见下面那条注记）。
    ("图片地址不转义引号（断得开 src 属性，能注入新属性）", STATE,
     '  return s.replace(/[&<>"]/g,',
     "  return s.replace(/[&<>]/g,", [SMOKE]),
    # 打字打了一半就切走/关掉，最后那一下被 600ms 防抖吞掉。
    # 修法是 app.js 里挂 visibilitychange/pagehide → state.js 的 flushSoon()。
    # 这一发把那个监听摘掉，smoke 那条「切走时排队中的改动会落盘」就会红。
    # 锚点写法：源码里那一整句是一条单行（箭头函数体在同一行），所以不用跨行转义。
    # 锚点只换**函数体那一行**，不碰括号——第一版把整行监听换掉，注入之后代码
    # 直接语法不通，于是它「炸」是因为打不开，不是因为行为变了。那种注入证明不了
    # 「这条门守住了行为」，只能证明它守住了我们能写对括号。
    ("页面切走时不落盘（600ms 防抖里的最后一下丢掉）", APP,
     '    if (document.visibilityState === "hidden") flushSoon();',
     "    if (document.visibilityState === \"hidden\") { /* 不落盘 */ }", [SMOKE]),
    # rescheduleAll() 曾经是死代码：全仓只有定义、零个调用点。于是「开机把没办完的
    # 提醒重新排一遍」这句注释描述的事从来没发生过——重装或系统清过队列之后，
    # 没到点的提醒一条都不会响。这一发把 boot() 里那句调用摘掉。
    ("开机不再重排提醒（重装之后那些没到点的提醒一条都不会响）", APP,
     '  try { if (typeof rescheduleAll === "function") rescheduleAll(); } catch (e) { console.warn("reschedule", e); }',
     "  // 不重排", [SMOKE]),
    # 离线缓存永远装不进新文件。以前 fill() 把已经交给页面的 Response 直接 cache.put，
    # 浏览器抛 "Response body is already used" 又被 .catch 吞掉——缓存停在第一次装的那版，
    # 老用户刷新多少次都还是旧前端，且**没有任何一处会报错**。
    ("离线缓存把已经交给页面的响应直接塞进缓存（升级后永远还是旧前端）", SWJS,
     "  let copy;\n  try { copy = res.clone(); } catch (e) { console.warn(\"sw clone\", e); return; }",
     "  let copy;\n  try { copy = res; } catch (e) { console.warn(\"sw clone\", e); return; }",
     [OFFLINE]),
    # 字号三档形同虚设。以前 `--fs-scale` 只乘在 `body` 一条上，而全仓 203 处
    # font-size 都写死 px：实测「册」屏 105 个文字元素里只有 4 个会随档位变。
    # 这一发把其中一处改回裸 px——那一个元素就不再跟着档位走。
    ("字号三档只乘在 body 上，各处的 px 纹丝不动（选「大」几乎没变化）", CSS,
     ".tiny { font-size: calc(12px * var(--fs-scale, 1)); color: var(--ink-soft); }",
     ".tiny { font-size: 12px; color: var(--ink-soft); }", [A11Y]),
    # 热力图的键盘替代操作（WCAG 2.5.8）。年视图 371 个格子只有 11×11，
    # 放大到 24 会把一张年历毁掉——所以那一道门的判据不是「格子够大」，是
    # 「格子小，但键盘走得到、开得了」。这一发把「第一次按键只选中今天、不移动」
    # 那一步拆掉，还原成修之前的行为：按方向键屏幕上一动不动。
    ("热力图方向键按下去屏幕上没有反应（键盘用户走不进年历）", STATS,
     "  if (!heatSel) {\n    heatSel = dayStr(g.today);\n    paintHeatSel(grid);",
     "  if (!heatSel) {\n    heatSel = dayStr(g.today);", [A11Y]),
    ("小麦这一项从 CHIP_MAP 里掉了（小笼包变回「全员安全」）", ENG,
     '    小麦: ["面", "饼", "饺", "包子", "小笼", "馒头", "馍", "烙", "馄饨", "云吞", "油条", "春卷", "面筋"],\n',
     "", [ENGINE_TEST, CONSISTENCY],
     [(GATE, '    "小麦": ["面", "饼", "饺", "包子", "小笼", "馒头", "馍", "烙", "馄饨", "云吞", "油条", "春卷", "面筋"],\n', "")]),
    ("大豆的词表里混进了单字「豆」（土豆和四季豆被误判成含大豆）", ENG,
     '    大豆: ["豆腐", "豆干", "豆皮", "豆泡", "千张", "腐竹", "毛豆", "豆浆", "豆芽", "豆豉", "豆瓣"],',
     '    大豆: ["豆"],', [ENGINE_TEST, CONSISTENCY],
     [(GATE, '    "大豆": ["豆腐", "豆干", "豆皮", "豆泡", "千张", "腐竹", "毛豆", "豆浆", "豆芽", "豆豉", "豆瓣"],',
       '    "大豆": ["豆"],')]),
    ("追问引用又把说话人念了一遍", ENG,
     "      return /^[：:]/.test(rest) ? rest.slice(1) : x.line;",
     "      return x.line;", [CONSISTENCY, E2E],
     [(GATE, '        return rest[1:] if rest[:1] in ("：", ":") else x["line"]',
           '        return x["line"]')]),
    ("卡片正文再留说话人前缀（徽章之外名字出现两遍）", YAN,
     r'  for (const p of [c.speaker, name + "：", name + ":", name]) {' "\n"
     r'    if (p && text.length > p.length && text.startsWith(p)) { text = text.slice(p.length); break; }' "\n"
     "  }",
     "  // 不去前缀", [E2E]),
    ("道数自己抄一份切法（引擎改了它不知道）", WEI,
     "  return Engine.menuItems(menu).dishes.length;",
     '  return String(menu || "").split(/[\\n,，、；;]/).map((s) => s.trim()).filter(Boolean).length;', [E2E]),
    ("回看上一桌时不再清洗 r 里的字段（一个 \"boom\" 对象就能让整屏空白）", STATE,
     "    .forEach((k) => { if (!Array.isArray(r[k])) delete r[k]; });",
     "    .forEach(() => {});", [E2E]),
    ("柜格标签的实底摘掉（回到靠照片上的渐变）", CSS,
     "  background: var(--ink); color: var(--cream);\n  left: 6px; right: auto;",
     "  color: var(--cream);\n  left: 6px; right: auto;", [CONTRAST]),
    ("首屏角标的实底摘掉（同上，那一行离底边 29px，渐变只剩 .56）", CSS,
     "  background: var(--ink); padding: 3px 10px 4px; border-radius: 8px;",
     "  padding: 3px 10px 4px; border-radius: 8px;", [CONTRAST]),
    # 实底是给「照片上压字」用的，没选图时那一格是空的：空的实底就是首屏左下角一颗墨点。
    # 这条是商店截图里看到的，不是测试先发现的。
    ("空角标的占位收回去（没选图时露出一颗墨点）", CSS,
     ".hero-cloth .cap:empty { display: none; }", "", [E2E]),
    ("程序性焦点的描边放回来（整屏绕一圈，底边露一条全宽红线）", CSS,
     '.screen [tabindex="-1"]:focus-visible, .screen:focus-visible { outline: none; }',
     "", [E2E]),
    # 薄柜子的判定不自己说，界面、长图、复制话术就会三处各说各的（或者都不说）
    ("判定不再说自己薄（三件柜子也装作有把握）", YI,
     "    if (r.thin) {", "    if (false) {", [E2E]),
    # 薄不薄只写在一处（card.js 的 thinNote），长图和复制共用。摘掉它，三处一起不说
    ("薄柜子的说法整个消失（屏幕上、长图里、复制出去的都装作有把握）", CARD,
     "  if (!r || !r.thin) return \"\";", "  if (!r) return \"\";", [E2E]),
    # ---------- 第二十一轮：柜子里的主色可以改了 ----------
    # 控件那一头不用帮：实测浏览器自己把 #abc 展成 #aabbcc、#2c3a4aff 截成 #2c3a4a、
    # 连 red 都翻成 #ff0000。第一版把注入钉在 value= 上，e2e 照旧绿——那是假门，
    # 是守门自检把它报出来的（「改了源码，e2e 全都过了」）。hex6 真正管的是那行文本。
    ("色值那行文本不展开（界面印 #abc，控件里却是 #aabbcc）", YI,
     '<span class="hex" id="clothHex">${esc(hex6(w.color))}</span>',
     '<span class="hex" id="clothHex">${esc(w.color)}</span>', [E2E]),
    ("改完主色不写盘（重开就回到旧色）", YI,
     "    w.color = v; save(state);", "    w.color = v;", [E2E]),
    ("值没变也算一次改动（每点一下都弹一次撤销）", YI,
     "    if (v === hex6(w.color)) return;", "    if (false) return;", [E2E]),
    # 比较那一头才是 hex6 有牙的地方：控件回来的是六位、存储里可能是三位
    # （cssColor 收 3~8 位，老备份里合法），不展开就把「打开取色器、一个字没动、点确定」
    # 记成一次改动，还顺手把 #abc 改写成 #aabbcc。
    ("比较时不展开：一个字没动也被当成改过", YI,
     "    if (v === hex6(w.color)) return;", "    if (v === w.color) return;", [E2E]),
    ("改色不提「这张笺是改之前算的」（新色配旧章同时摆在屏上）", YI,
     '${state.lastReport ? " · 这张笺还是改之前算的" : ""}', '""', [E2E]),
    # ---------- 第二十一轮（下）：上限动了手要说，空柜别许诺没实现的门槛 ----------
    ("主动裁剪丢了照片，屏幕上还写着「已用 56%」", STATE,
     "    if (lost) toast(lost);", "    // 不说", [E2E]),
    ("说了丢，但数错了（把七件说成一件）", STATE,
     "  trimLoss.imgs = Math.max(0, before.imgs - (s.wardrobe || []).filter((w) => w && w.img).length);",
     "  trimLoss.imgs = 1;", [E2E]),
    ("整件被 36 件上限切掉却不报件数", STATE,
     "  trimLoss.clothes = Math.max(0, before.clothes - (s.wardrobe || []).length);",
     "  trimLoss.clothes = 0;", [E2E]),
    # 空柜那句承诺过「先收 8 件…才准」，可代码里从来没有这个门槛：一件就照常出判定，
    # <5 件还会另说「判定还薄」。两端一起改回去，才是产品断言要抓的（对账抓不到）。
    ("空柜文案又回去承诺一个没实现的件数", ENG,
     'quote: "柜里还空着。先放几件常穿的，过笺才有得比。"',
     'quote: "柜里还太少。先收 8 件常穿的，过笺才准。"', [ENGINE_TEST, CONSISTENCY],
     [(GATE, '"quote": "柜里还空着。先放几件常穿的，过笺才有得比。"',
           '"quote": "柜里还太少。先收 8 件常穿的，过笺才准。"')]),
    ("薄的门槛挪到 0 件（三件柜子不再说自己薄）", ENG,
     "    const thin = list.length < 5;", "    const thin = list.length < 1;",
     [CONSISTENCY, E2E],
     [(GATE, '"thin": len(scored) < 5, "closetN": len(scored),',
           '"thin": len(scored) < 1, "closetN": len(scored),')]),
    # ---------- 第二十二轮：言笺的类别猜错了，能挪 ----------
    # 前两条症状一样（再贴同一段会冒出两张），根因不同：一个是没打上标记，
    # 一个是打了标记但合并的时候不看。
    ("挪过的条目没打标记（再贴同一段就按原类别多出一张）", YAN,
     "      c.k = k; c.moved = true;", "      c.k = k;", [E2E]),
    ("合并时不按原话认领挪过的条目（同上，多出一张）", YAN,
     "  const fresh = next.filter((c) => !seen.has(cardKey(c)) && !claimed.has(c.line));",
     "  const fresh = next.filter((c) => !seen.has(cardKey(c)));", [E2E]),
    ("撤销只把类别挪回去，「已挪」的标记留着（行上永远写着已挪）", YAN,
     "        c.k = from; c.moved = false;", "        c.k = from;", [E2E]),
    ("删一条不清展开态（下标前移，选择器指到别的条上）", YAN,
     "      moveOpen = [];                    // 下标整体前移，展开着的选择器会指到别的条上\n"
     "      whenOpen = [];                    // 两排选择器都是按下标记的，一起作废",
     "      // 两排都不清", [E2E]),
    # ---------- 第二十三轮：外来的言笺条目先洗干净，时间也改得动 ----------
    # 这一批的症状没有一条是「崩」：全是数不对——头上写 6 条、屏上 4 行。
    ("认不出的类别原样留着（那条既不进按类型也不进按时间，凭空蒸发）", STATE,
     '    k: YAN_KINDS.includes(c.k) ? c.k : "还没说清",', "    k: c.k,", [E2E]),
    ("line 不做类型检查（一个数字写进屏是 [object Object]）", STATE,
     '  const line = typeof c.line === "string" ? c.line.trim() : "";',
     '  const line = String(c.line ?? "").trim();', [E2E]),
    ("读不懂的条目不丢掉（空行占一格，开机那句「少几条」也跟着少报）", STATE,
     "  if (!line) return null;", "  // 不丢", [E2E]),
    ("done 不做布尔收口（备份里一个字符串 no 就冒充已勾）", STATE,
     "    done: c.done === true,", "    done: !!c.done,", [E2E]),
    ("when.at 不验有限（NaN 的分组标题写出「NaN月NaN日」，排序整屏带偏）", STATE,
     "  if (!Number.isFinite(at) || Math.abs(at) > AT_MAX) return null;",
     "  if (Math.abs(at) > AT_MAX) return null;", [E2E]),
    ("笺册的 quote 不做类型检查（一个对象就是 [object Object]，还会在 .slice 上抛）", STATE,
     '  const quote = typeof a.quote === "string" ? a.quote.slice(0, 120) : "";',
     '  const quote = String(a.quote ?? "").slice(0, 120);', [E2E]),
    ("清洗丢条不数（少了几条却一句不说）", STATE,
     "  normLoss.cards = yc.length - ycn.length;", "  normLoss.cards = 0;", [E2E]),
    ("「下周一」的偏移写错一天（周四点的，落到了周二）", YAN,
     "  return { text: label, at: now + (8 - cur) * DAY };",
     "  return { text: label, at: now + (9 - cur) * DAY };", [E2E]),
    ("清掉时间之后 wset 还留着（那一行永远写着「已定时」）", YAN,
     "  c.wset = !!w;", "  c.wset = true;", [E2E]),
    ("撤销改时间时把「已定时」的标记留下（行上永远标着手动定的）", YAN,
     "  const from = c.when, wasSet = c.wset === true;",
     "  const from = c.when, wasSet = true;", [E2E]),
    ("改完时间不把焦点还给那一行（键盘用户被甩回页首）", YAN,
     "  if (back) back.focus({ preventScroll: true });", "  // 不还", [E2E]),
    ("日期框没挑完也照样落（半填一次就把原时间抹了）", YAN,
     '      if (!w) { toast("日期没填全，时间先不动；要去掉它按旁边的「清掉」"); return; }\n'
     "      setWhen(+el.dataset.wday, w);",
     "      setWhen(+el.dataset.wday, w);", [E2E]),
    ("改完时间不签收起的这一排（选一枚签，那排还摊着）", YAN,
     "  whenOpen = [];\n  save(state); renderYan();", "  save(state); renderYan();", [E2E]),
    ("开「时间」时不清「挪」那排（一屏两排同时摊着）", YAN,
     "      moveOpen = [];                    // 与上面相反：一屏只摊一排签", "      // 不清", [E2E]),
    ("开「挪」时不清「时间」那排（同上）", YAN,
     "      whenOpen = [];                    // 一屏只摊一排签：两排同时摊着，谁都不知道 × 归谁",
     "      // 不清", [E2E]),
    # ---------- 第二十四轮：回话读不懂，不许把屏幕锁在后面 ----------
    # 模型在网关那一头，它回什么都有可能。这一批的靶子是「收尾只在成功路径上」：
    # 遮罩是 position:fixed 的浮层，它挂着的时候除了一颗「先不等了」什么都做不了。
    ("言笺的收尾不放在 finally（处理途中一抛，遮罩就永久挂着）", YAN,
     "  } finally {\n"
     "    // 遮罩与忙闩**无条件**落下。以前收尾写在 try 外面，而 normCards 一抛就跳过它们：\n"
     "    // 一个坏回包能把全屏遮罩永远挂着，除了一颗「先不等了」没法逃（衣笺早就是这副骨架）。\n"
     "    busy = false;\n"
     "    veil(false);\n"
     "  }",
     "  } finally {\n  }", [E2E]),
    ("分组不是数组就照原样 forEach（一个字符串回话把整批带走）", YAN,
     "    (Array.isArray(r[k]) ? r[k] : []).forEach((x) => {",
     "    (r[k] || []).forEach((x) => {", [E2E]),
    ("味笺的收尾不放在 finally（同上，遮罩留着）", WEI,
     "  } finally {\n    // 与衣笺/言笺同一副骨架：收尾写在 try 外面的话，处理途中一抛就是「遮罩永久挂着」\n"
     "    busy = false;\n    veil(false);\n  }",
     "  } finally {\n  }", [E2E]),
    ("plan.want 形状不对时不补空对象（画「荤 2 / 素 3」那一行直接取子键）", STATE,
     "    if (!r.plan[k] || typeof r.plan[k] !== \"object\" || Array.isArray(r.plan[k])) r.plan[k] = {};",
     "    if (Array.isArray(r.plan[k])) r.plan[k] = {};", [E2E]),

    # ---------- 第二十五轮：补照片，与那句「卸载即删除」\n    # 第 21 轮写着「重新拍照能补上」，可当时柜子里的一件根本没有换照片的入口——
    # 唯一的出路是删掉重入柜，而删掉正好毁掉同一句话承诺「还在」的穿着记录。
    ("补的照片不压缩（本机配额立刻再爆一次）", YI,
     "    w.img = compress(img, 320, 0.72);",
     "    w.img = compress(img, 4000, 0.95);", [E2E]),
    ("撤销换照片时把原来那张弄丢（只删不还原）", YI,
     "      if (before) w.img = before; else delete w.img;",
     "      delete w.img;", [E2E]),
    ("撤销只把键留着写个 undefined（屏幕上是真「没有」，存储里是个空键）", YI,
     "      if (before) w.img = before; else delete w.img;   // 原本没照片的要真退回「没有」",
     "      w.img = before;", [E2E]),
    ("补照片补到第一件头上（目标不是选中的那件）", YI,
     "  const w = state.wardrobe.find((x) => x.id === state.clothSel);\n  if (!w) { toast(\"先点中柜里那一件\"); return; }",
     "  const w = state.wardrobe[0];\n  if (!w) { toast(\"先点中柜里那一件\"); return; }", [E2E]),
    ("没选中的时候照样往下走（在一个 undefined 上写 img）", YI,
     '  if (!w) { toast("先点中柜里那一件"); return; }',
     "  // 不拦", [E2E]),
    ("换照片顺手重取主色（把第 21 轮那格手改的色盖掉）", YI,
     "    w.img = compress(img, 320, 0.72);",
     "    w.img = compress(img, 320, 0.72); w.color = Engine.analyze(img).color;", [E2E]),
    ("相册补图走回「再入柜一件」那条路", APP,
     '"#fileRephoto").onchange = (e) => { const f = e.target.files[0]; if (f) rephotoCloth(f);',
     '"#fileRephoto").onchange = (e) => { const f = e.target.files[0]; if (f) addClothFile(f);', [E2E]),
    # 这条不是 App 行为，是**跨产物的陈述**：清单那个布尔与商店材料里的隐私政策必须同真同假。
    ("把 allowBackup 改回 true（政策那句「卸载即随之删除」就成假话）", MANIFEST,
     '        android:allowBackup="false"', '        android:allowBackup="true"', [BACKUP]),

    # ---------- 第二十六轮：窄屏那一列正文，与两支跨产物的颜色 ----------
    # 加一枚「时间」按钮就把 360 上的正文挤到 67px（四个字一行）；
    # 而纸色 / 印章红同时写在 CSS 与安卓 res 里，改一边就跳色。
    ("窄屏让动作与正文抢同一行（正文被挤成竖排）", CSS,
     "  .check { grid-template-columns: var(--ck-col) auto 1fr; }",
     "  .check { grid-template-columns: var(--ck-col) auto 1fr auto; }", [E2E],
     [(CSS, "  .check .acts { grid-column: 1 / -1; justify-self: end; margin-top: 4px; }",
       "  .check .acts { justify-self: end; }")]),
    ("res 里的印章红改了，CSS 里那份没跟（原生弹层与纸上的红分家）", RES,
     '<color name="seal_red">#b54a3c</color>', '<color name="seal_red">#b54ac3</color>', [PKG]),
    ("启动图底色与纸色分家（实测就是「灰屏 → 纸屏」跳一下）", RES,
     '<color name="splash_background">#f4efe6</color>', '<color name="splash_background">#eeeeee</color>', [PKG]),

    # ---------- 第二十七轮：名字只说一遍，勾掉的可以只清勾掉的 ----------
    # 「小王小王让我周四前…」是盯着 360 的截图看出来的：第 20 轮只认带冒号那一种，
    # 而光杆名字与「某某说」这两种更常见，徽章是从 who 来的。
    ("正文只认带冒号的写法（光杆「小王让我…」照旧说两遍）", YAN,
     '  for (const p of [c.speaker, name + "：", name + ":", name]) {',
     '  for (const p of [c.speaker, name + "：", name + ":"]) {', [E2E]),
    ("「小王说要去…」剥完留下一个「说」字", YAN,
     r'  text = text.replace(/^[：:]\s*/, "").replace(/^说\s*/, "");',
     r'  text = text.replace(/^[：:]\s*/, "");', [E2E]),
    ("清掉勾掉的之后不许再摆一枚按了没用的按钮", YAN,
     '        <button class="chip" id="yanPrune" ${doneCount ? "" : "hidden"}>清掉勾掉的 ${doneCount}</button>',
     '        <button class="chip" id="yanPrune">清掉勾掉的 ${doneCount}</button>', [E2E]),
    # ---- 第四十四轮：动作埋在列表底下 + 勾一下不再重建整片 ----
    ("把整张笺的动作塞回所有行的底下（言笺那两枚又跑到 40 屏外）", YAN,
     "      ${head + body}", "      ${body + head}", [E2E]),
    ("「只看没办的」里勾上那条不退回整片重建（它还留在屏上）", YAN,
     "  if (state.yanHideDone && c.done) return false;",
     "  if (state.yanHideDone && c.done) return true;", [E2E]),
    ("就地补丁改了别处、顶上那行「已勾」不动（屏上的数永远慢一次）", YAN,
     "  cnt.textContent = `${all.length} 条 · 已勾 ${doneCount}`;",
     "  void doneCount;   // 故意不写回去：整片重建时它才追上", [E2E]),
    ("就地补丁忘了收回去的那枚「清掉勾掉的」（一条没勾还露着）", YAN,
     "  pr.hidden = !doneCount;", "  pr.hidden = false;", [E2E]),
    ("就地补丁不改那一行自己的样子（勾上了却看不出来）", YAN,
     '  row.classList.toggle("done", c.done);',
     '  row.classList.toggle("done", false);', [E2E]),
    ("就地补丁漏掉类别那一格的 0/50", YAN,
     "    g.textContent = `${same.filter((x) => x.done).length}/${same.length}`;",
     "    g.textContent = `0/${same.length}`;", [E2E]),
    ("点中一件只滚到那一格、不滚编辑器（报了「已选中」而屏上没变）", YI,
     '  const bar = $("#clothActions .action-bar");\n'
     '  if (bar) bar.scrollIntoView({ block: "start" });',
     '  const tile = $("#closet .item[data-id]");\n'
     '  if (tile) tile.scrollIntoView({ block: "nearest" });', [E2E]),
    # ---- 第四十四轮 §47：320px 窄屏 + 顶格数据 ----
    ("窄屏上把「没当成菜的那几句」裁成一行、不给省略号（那句话从此看不见）", CSS,
     ".note-line { font-size: calc(13px * var(--fs-scale, 1)); line-height: 1.65; color: var(--ink); margin-top: 3px; }",
     ".note-line { font-size: 13px; line-height: 1.65; color: var(--ink); margin-top: 3px;\n  overflow: hidden; white-space: nowrap; }",
     [E2E]),
    ("字号放大之后才露馅的那种：给一行小字钉死一个高度", CSS,
     ".tiny { font-size: calc(12px * var(--fs-scale, 1)); color: var(--ink-soft); }",
     ".tiny { font-size: 12px; color: var(--ink-soft); height: 26px; overflow: hidden; }", [E2E]),
    ("言笺正文不许换行：500 字那一条把整页撑出屏幕外", CSS,
     ".check .ck-body { font-size: calc(15px * var(--fs-scale, 1)); line-height: 1.7; }",
     ".check .ck-body { font-size: 15px; line-height: 1.7; white-space: nowrap; }", [E2E]),
    # ---- 第四十六轮：备份的往返（导出那一份再导入回来，一件都不能少）----
    ("导入时只认 jpeg 的照片：备份里那几张 PNG 进门就被丢掉", STATE,
     '  if (!/^(data:image\\/|https?:\\/\\/)/i.test(s)) return "";',
     '  if (!/^(data:image\\/jpeg|https?:\\/\\/)/i.test(s)) return "";', [E2E]),
    ("导入把「手动挪过类别」的标记洗掉（下次再贴同一段聊天就多出一条重复的）", STATE,
     "    moved: c.moved === true,", "    moved: false,", [E2E]),
    ("导入把笺点的上限改成 999：备份里明明存着 9999", STATE,
     "  s.points = Number.isFinite(pts) ? Math.max(0, Math.min(9999, Math.floor(pts))) : 24;",
     "  s.points = Number.isFinite(pts) ? Math.max(0, Math.min(999, Math.floor(pts))) : 24;", [E2E]),
    # ---- 第四十七轮：只用键盘走一遍 ----
    ("柜子里那一格退回「能点但键盘走不到」的 div", YI,
     '         data-id="${esc(w.id)}" role="button" tabindex="0"',
     '         data-id="${esc(w.id)}"', [E2E]),
    ("格子够得着了，但 Enter / 空格按不动它", YI,
     '    el.onkeydown = (e) => {\n      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); }\n    };',
     '    el.onkeydown = null;', [E2E]),
    ("全局焦点描边按掉：键盘用户看不出自己走到哪了", CSS,
     "\n:focus-visible { outline: 2px solid var(--seal); outline-offset: 2px; }\n",
     "\n:focus-visible { outline: none; }\n", [E2E]),
    # ---- 第四十八轮：言笺的搜索 ----
    ("搜过之后行上的下标按「屏上第几行」算（点第一行会办到别的一条上去）", YAN,
     "  const i = all.indexOf(c);", "  const i = cards.indexOf(c);", [E2E]),
    ("让复制整张笺跟着搜索走（那句话字面上就不成立了）", YAN,
     "  const cards = state.yanCards || [];",
     "  let cards = (state.yanCards || []).filter((c) => !yanQuery() || `${c.line} ${c.k}`.toLowerCase().includes(yanQuery()));",
     [E2E]),
    ("搜不到的时候只说「搜不到」，不给出路", YAN,
     '      + `<button type="button" class="chip" id="clearYanSearch">清掉搜索</button></div>`;',
     "      + `</div>`;", [E2E]),
    ("笺清空了搜索框还杵在那儿（一个搜了也白搜的框）", YAN,
     "  if (bar) bar.hidden = !all.length;", "  if (bar) bar.hidden = false;", [E2E]),
    ("把临时过滤词写进备份：重启之后人被关在自己上次搜的那半屏里", APP,
     '  $("#yanSearch").oninput = () => yanSearchTick();',
     '  $("#yanSearch").oninput = () => { state.yanQuery = $("#yanSearch").value; save(state); yanSearchTick(); };',
     [E2E]),
    # ---- 第四十九轮：命中高亮 ----
    ("先转义再替换：查询里的 amp 会撞上 &amp; 里的三个字母，标到没命中的地方去", YAN,
     "  const low = s.toLowerCase(), needle = q.toLowerCase();",
     '  const es = esc(s);\n'
     '  if (q && es.toLowerCase().includes(q.toLowerCase()))\n'
     '    return es.replace(new RegExp(q.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&"), "gi"), (m) => "<mark>" + m + "</mark>");\n'
     "  const low = s.toLowerCase(), needle = q.toLowerCase();", [E2E]),
    ("高亮整个不做：搜完只给一个计数，一行 500 字里中在哪还得自己读", YAN,
     "  if (!q) return esc(s);", "  return esc(s);", [E2E]),
    ("把命中的那几个字从文字里吃掉（只剩一对空标记）", YAN,
     '    out += esc(s.slice(from, at)) + "<mark>" + esc(s.slice(at, at + needle.length)) + "</mark>";',
     '    out += esc(s.slice(from, at)) + "<mark></mark>";', [E2E]),
    # 这一发以前锚的是**整屏那 12 行**（从 space 一路到 album），结果第 62 轮在中间插了
    # 一个隐私政策入口就把锚点整段弄断了（锚点自检报出来的）。改成两处小改动：
    # 摘掉备份那一行、再把它贴到笺册底下——**只表达「顺序变了」这一件事**，
    # 中间再插什么都不影响它，这才对得起这条注入想守的东西。
    ("备份又压回笺册底下（想导出的人得先划过 24 张存档）", HTML,
     '      <p class="tiny" id="storageNote">数据只在这台设备</p>\n'
     '      <div class="row" style="margin-top:8px">\n'
     '        <button class="btn ghost" id="exportData">导出备份</button>\n'
     '        <button class="btn ghost" id="importData">导入备份</button>\n'
     '      </div>\n',
     "", [E2E],
     [(HTML, '      <div class="stack" id="album"></div>',
       '      <div class="stack" id="album"></div>\n'
       '      <p class="tiny" id="storageNote">数据只在这台设备</p>\n'
       '      <div class="row" style="margin-top:8px">\n'
       '        <button class="btn ghost" id="exportData">导出备份</button>\n'
       '        <button class="btn ghost" id="importData">导入备份</button>\n'
       '      </div>')]),
    ("撤销把清掉的两条 append 到末尾（顺序和勾掉前不一样了）", YAN,
     "      at.forEach((idx, k) => state.yanCards.splice(Math.min(idx, state.yanCards.length), 0, gone[k]));",
     "      gone.forEach((c) => state.yanCards.push(c));", [E2E]),
    ("清掉之后不收回展开态（下标全变了，选择器指到别的条上）", YAN,
     "    moveOpen = [];                      // 下标全变了，两排展开态一起作废\n"
     "    whenOpen = [];",
     "    // 都不清", [E2E]),
    # ---- 第五十轮：把旧备份盖到新数据上之后那一次反悔 ----
    ("导入时不剥掉文件自带的 savedAt：它住进 state，下一次备份就把它往返进柜子里了", ME,
     "    const at = Number.isFinite(Number(obj.savedAt)) && Number(obj.savedAt) > 0 ? Number(obj.savedAt) : null;\n"
     "    delete obj.savedAt;",
     "    const at = Number.isFinite(Number(obj.savedAt)) && Number(obj.savedAt) > 0 ? Number(obj.savedAt) : null;",
     [E2E]),
    ("导出的那份文件不写导出时间：反悔时那句「这份是 X 导出的」就没有时间可报", ME,
     "  const json = JSON.stringify(Object.assign({ savedAt: Date.now() }, state), null, 2);",
     "  const json = JSON.stringify(state, null, 2);",
     [E2E]),
    ("导入完不占反悔槽：整台都被换掉了，事后无处可退", ME,
     "    try {\n"
     "      sessionStorage.setItem(KEY + \".importundo\", prev);\n"
     "      sessionStorage.setItem(KEY + \".importat\", at ? String(at) : \"\");\n"
     "    } catch (_) { }",
     "    // 不占这个槽", [E2E]),
    ("写盘还没成功就先占槽：下次开机凭空一句「已导入」，柜子里却一条都没变", ME,
     "    try {\n"
     "      writeStore(text);   // 走唯一落盘入口：它先取消排在那次防抖里的旧 state\n"
     "    } catch (e) {\n"
     "      return reject();\n"
     "    }",
     "    const prev = (() => { try { return localStorage.getItem(KEY) || \"\"; } catch (_) { return \"\"; } })();\n"
     "    try { sessionStorage.setItem(KEY + \".importundo\", prev);"
     " sessionStorage.setItem(KEY + \".importat\", at ? String(at) : \"\"); } catch (_) { }\n"
     "    try {\n"
     "      writeStore(text);\n"
     "    } catch (e) {\n"
     "      return reject();\n"
     "    }", [E2E]),
    ("那句「已导入」报的是快照里的件数，不是真的落进来之后的那些", APP,
     "  const n = (state.wardrobe || []).length, m = (state.yanCards || []).length,"
     " a = (state.album || []).length;",
     "  const o = JSON.parse(snap) || {}; const n = (o.wardrobe || []).length,"
     " m = (o.yanCards || []).length, a = (o.album || []).length;",
     [E2E]),
    ("文件没写时间也凑一个今天：把「不知道」说成「知道」", APP,
     "  const when = /^\\d+$/.test(at) ? `这份是 ${dayStr(+at)} 导出的` : \"这份备份没写导出时间\";",
     "  const when = `这份是 ${dayStr(Number(at) || Date.now())} 导出的`;",
     [E2E]),
    ("撤销只改页里那个变量、不写盘：一重开又变回刚导入的那一份", APP,
     "      save(state); paintNav(); show(state.onboarded ? state.home : \"onboard\");\n"
     "      toast(\"换回导入前那份了\");",
     "      paintNav(); show(state.onboarded ? state.home : \"onboard\");\n"
     "      toast(\"换回导入前那份了\");", [E2E]),
    ("反悔的槽读完不擦：每次开机都重来一句「已导入」", APP,
     "    if (snap !== null) {\n"
     "      sessionStorage.removeItem(KEY + \".importundo\");\n"
     "      sessionStorage.removeItem(KEY + \".importat\");\n"
     "    }",
     "    // 不擦：留着它，下次开机再说一遍", [E2E]),
    ("后开口的那句把攒下的报告吃掉：丢了数据这件事又没人说了", APP,
     "  const s = bootNotes.filter(Boolean).join(\"；\");\n"
     "  bootNotes = [];\n"
     "  return s ? (text ? `${text}。${s}` : s) : text;",
     "  bootNotes = [];\n"
     "  return text;", [E2E]),
    ("没人开口时，攒下的那句报告也就跟着不说了", APP,
     "  const note = joinBootNotes(\"\");\n"
     "  if (note) toast(note, 5200);",
     "  joinBootNotes(\"\");", [E2E]),
    # ---- 第五十一轮：搜索那一行字不许拖住刚敲进去的那个字 ----
    ("搜索框改回按键直接整片重建：连打四个字就是四帧掉帧", APP,
     '  $("#yanSearch").oninput = () => yanSearchTick();',
     '  $("#yanSearch").oninput = () => renderYan();', [E2E]),
    ("延后写在注释里，代码却还是当场重建", YAN,
     "  renderYanSoon();", "  renderYan();", [E2E]),
    ("延后了，但那一枪从来没放出去：数对了，列表永远停在上一版", YAN,
     "  yanRenderTimer = setTimeout(() => { yanRenderTimer = null; renderYan(); }, 140);",
     "  yanRenderTimer = setTimeout(() => { yanRenderTimer = null; }, 140);", [E2E]),
    ("排新的一次之前不取消旧的：四下按键攒出四次重建", YAN,
     "  if (yanRenderTimer) clearTimeout(yanRenderTimer);\n"
     "  yanRenderTimer = setTimeout(",
     "  yanRenderTimer = setTimeout(", [E2E]),
    ("按键那一下连头上那个数都不改：延后成了不回话", YAN,
     "  if (cnt && q) cnt.textContent = `搜「${esc(q)}」${yanShown().length} / ${all.length} 条`;",
     "  if (cnt && q) { /* 等整片重建再说 */ }", [E2E]),
    ("计数自己另抄一把筛：只认 line、连「只看没办的」都不看，两边各说各话", YAN,
     "  if (cnt && q) cnt.textContent = `搜「${esc(q)}」${yanShown().length} / ${all.length} 条`;",
     "  if (cnt && q) cnt.textContent = `搜「${esc(q)}」"
     "${all.filter((c) => String(c.line).toLowerCase().includes(q)).length} / ${all.length} 条`;",
     [E2E]),
    ("直接画过一次之后，排队那一次还来补画（点「清掉搜索」被 140 毫秒前那一下再刷一遍）", YAN,
     "  if (yanRenderTimer) { clearTimeout(yanRenderTimer); yanRenderTimer = null; }\n"
     "  const fk = focusKey();",
     "  const fk = focusKey();", [E2E]),
    # ---- 第五十二轮：商店页上每一句可核实的话，都有人回头对代码 ----
    # 这一批注入改的**大多是文档**：那道门管的就是「文档说了一份、代码是另一份」。
    ("商店页那个版本号是第五处写版本的地方，代码升了它没跟（对账只对了四处）", STOREDOC,
     "| 当前版本 | ",
     "| 当前版本（这一行的版本号漏了） ", [STORE]),
    ("第 6 节说「这批商店截图是某个版本拍的」，那个版本号过期了（描述的是另一个版本的界面）", STOREDOC,
     "截图内容固定为（",
     "截图内容固定为 [", [STORE]),
    # 0.6.0：文案改了一句「长按桌面图标」的列举（三枚 → 五枚），完整说明从 1131 变成 1143。
    # 锚点跟着改，但**注入要验的那件事没变**：把那个数字改回一个旧值，store_claims 必须红。
    # 所以替换文写的是 1131（上一版的真值），而不是随便一个假数——这样将来谁改文案
    # 忘了回填这个数，红的理由和今天这条一模一样。
    ("文案里那句「实测 1143」没人回来对数（第三十六轮就是这么飘的）", STOREDOC,
     "**完整说明（4000 字符内，实测 1143）**",
     "**完整说明（4000 字符内，实测 1131）**", [STORE]),
    ("商店页多报了一条危险权限：清单里根本没有相机，描述却写着申请了", STOREDOC,
     "`android.permission.VIBRATE`（触感反馈，不读不写任何数据；由 @capacitor/haptics 带入）。",
     "`android.permission.VIBRATE` 与 `android.permission.CAMERA`（触感反馈，不读不写任何数据；"
     "由 @capacitor/haptics 带入）。", [STORE]),
    ("上传给网关的图不再缩小（文档那句「先在手机里缩小、最长边 ≤512」成假话）", API,
     "          const k = Math.min(1, (w || 512) / Math.max(img.width || 1, img.height || 1));",
     "          const k = Math.min(1, (w || 2048) / Math.max(img.width || 1, img.height || 1));",
     [STORE]),
    ("菜库里那条小笼包不再挂着猪肉（商店文案举的那个「名字里没写出来的成分」的例子空了）", ENG,
     '      { n: "小笼包", tags: ["猪肉"] },',
     '      { n: "小笼包", tags: [] },', [STORE]),
    # ---- 第五十三轮：把手势条那一档的安全区拨出来量一遍 ----
    ("提示条不让安全区：手势条 48dp 的机器上它正好压在底栏上", CSS,
     "  position: fixed; left: 50%; bottom: calc(96px + var(--sab)); transform: translateX(-50%);",
     "  position: fixed; left: 50%; bottom: 96px; transform: translateX(-50%);", [E2E]),
    ("底栏绕过 --sab 直接写 env()：行为没错，但这一处从此永远量不到", CSS,
     "  padding: 8px 8px calc(8px + var(--sab));",
     "  padding: 8px 8px calc(8px + env(safe-area-inset-bottom));", [E2E]),
    ("正文给底栏留的那块白不让安全区（最后一行藏在底栏底下）", CSS,
     "  padding-bottom: calc(96px + var(--sab));",
     "  padding-bottom: 96px;", [E2E]),
    ("状态栏那一档不让了：安卓 15/16 强制 edge-to-edge 之后每一屏的标题都钻进状态栏", CSS,
     "  padding: calc(30px + var(--sat)) calc(22px + var(--sar)) 28px calc(22px + var(--sal));",
     "  padding: 30px calc(22px + var(--sar)) 28px calc(22px + var(--sal));", [E2E]),
    ("左右圆角那一档不让了：圆角屏上正文第一行被切掉半个字", CSS,
     "  padding: calc(30px + var(--sat)) calc(22px + var(--sar)) 28px calc(22px + var(--sal));",
     "  padding: calc(30px + var(--sat)) 22px 28px 22px;", [E2E]),
    # —— 第二十八轮：笺册那另外 12 张
    ("笺册「看另外 N 张」按了不摊（摊开那一下是空的）", ME,
     "    if (aa) aa.onclick = () => { albumAll = !albumAll; renderMe(); };",
     "    if (aa) aa.onclick = () => { renderMe(); };", [E2E]),
    ("笺册过滤之后行上写下标为「屏上第几张」（点第一行复制到全册第一张）", ME,
     '      return `<div class="slip-row">\n'
     '        <button type="button" class="card slip" data-slip="${i}"',
     '      return `<div class="slip-row">\n'
     '        <button type="button" class="card slip" data-slip="${items.indexOf(i)}"', [E2E]),
    ("笺册头上的张数说的是摊着的，不是在册的", ME,
     "      : `笺册 · 一共 ${state.album.length} 张`",
     "      : `笺册 · 一共 ${shown.length} 张`", [E2E]),
    ("笺册超上限切掉了但不说（丢了也不吭声）", STATE,
     "  trimLoss.slips = Math.max(0, before.slips - s.album.length);",
     "  trimLoss.slips = 0;", [E2E]),
    ("逐级丢那条把留几张抄成 24（这条路只留 8 张）", STATE,
     '        slips: hadSlips - light.album.length, keepSlips: 8 }) || "本机空间紧张，已清掉几件旧图");',
     '        slips: hadSlips - light.album.length, keepSlips: 24 }) || "本机空间紧张，已清掉几件旧图");', [E2E]),
    ("只有一笺有存档也照摆按笺的签（点了什么也不会变）", ME,
     "    if (kinds.length > 1) {",
     "    if (kinds.length > 0) {", [E2E]),
    ("笺册的签排重建之后不还焦点（键盘按一次签被甩回页首）", ME,
     "  restoreFocus(fk);",
     "  // 不还焦点", [E2E]),
    ("空笺册留一行空高（说明与签排都收着那句摘掉）", ME,
     "    note.hidden = chipRow.hidden = !state.album.length;",
     "    note.hidden = false; chipRow.hidden = false;", [E2E]),
    # —— 第二十九轮：笺册的单张删除
    ("笺册的 × 摘掉（那一行只剩「只能整台机器清空」）", ME,
     "        <button type=\"button\" class=\"drop\" data-del=\"${i}\"",
     "        <button type=\"button\" class=\"drop\" data-nope=\"${i}\"", [E2E]),
    ("× 塞回卡片里面（button 里有交互内容，解析器会把这张卡片咬断）", ME,
     '        <span class="tiny slip-copy">再复制</span>\n'
     "        </button>\n"
     '        <span class="slip-acts">',
     '        <button type="button" class="drop" data-del="${i}">×</button>\n'
     '        <span class="tiny slip-copy">再复制</span>\n'
     "        </button>\n"
     '        <span class="slip-acts">', [E2E]),
    ("笺册的 × 带屏上序号（过滤之后删的是背后那一张）", ME,
     "        <button type=\"button\" class=\"drop\" data-del=\"${i}\"",
     "        <button type=\"button\" class=\"drop\" data-del=\"${items.indexOf(i)}\"", [E2E]),
    ("笺册删一张之后不重画（屏上还摆着那 24 行）", ME,
     "      albumOpen = [];          // 下标整体前移了，摊着全文的那几张会指到别的笺上\n"
     "      save(state); renderMe(); haptic(\"LIGHT\");",
     "      albumOpen = [];          // 下标整体前移了，摊着全文的那几张会指到别的笺上\n"
     "      save(state); haptic(\"LIGHT\");", [E2E]),
    ("撤销把删掉的那张 append 到末尾（顺序和删前不一样了）", ME,
     "        state.album.splice(Math.min(i, state.album.length), 0, gone);",
     "        state.album.push(gone);", [E2E]),
    ("笺册的 × 掉到纸外（回到第一版那个浮在框外的列）", CSS,
     ".slip-row .slip-acts { position: absolute; top: 5px; right: 6px; display: inline-flex; gap: 2px; }",
     ".slip-row .slip-acts { position: absolute; top: 5px; right: -46px; display: inline-flex; gap: 2px; }", [E2E]),
    ("眉上的日期不给 × 让位（2026.09.22 压在 × 底下）", CSS,
     ".slip-row .slip-top { padding-right: 86px; }",
     ".slip-row .slip-top { padding-right: 0; }", [E2E]),
    ("报告页的结论章又压回第三格对比框（那里面是照片）", CSS,
     ".report .compare { margin-top: 64px; }",
     ".report .compare { margin-top: 14px; }", [E2E]),
    # —— 第三十一轮：四句做不到的话
    # compound：只删按钮不删绑定会当场抛（那是一条崩，不是一格红）。历史上的缺陷形状是
    # 「这一支里既不画 ＋、也没有绑定」，所以两处一起改——它才是那个没人守的 bug。
    ("空柜子只留一句话，不给 ＋（叫人事却没入口）", YI,
     '      + `<button type="button" class="chip" id="addCloth" aria-label="入柜">＋ 放第一件</button></div>`;',
     "      + `</div>`;", [E2E],
     [(YI, '    $("#addCloth").onclick = () => $("#fileCloth").click();\n    return;', "    return;")]),
    ("空柜那句又把门槛写回来（同一句话的第二份拷贝，第 21 轮漏的那份）", YI,
     "    box.innerHTML = `<div class=\"empty\">柜里还空着。<br>放几件常穿的进来，过笺才有得比。<br>`",
     "    box.innerHTML = `<div class=\"empty\">柜子是空的。<br>先入几件常穿的，过笺才准。<br>`", [E2E]),
    ("「放录音」那枚假入口回来（点了永远只会回一句请先转文字）", HTML,
     '        <button class="chip" id="yanImgBtn">放图片</button>',
     '        <button class="chip" id="yanImgBtn">放图片</button>\n'
     '        <button class="chip" id="yanAudBtn">放录音</button>', [E2E]),
    ("「已开全笺」又只改订阅名，不动 modules（底栏照旧短）", ME,
     '  if (plan === "all") ["yi", "wei", "yan"].forEach((k) => { state.modules[k] = true; });',
     '  if (plan === "all") { /* 只改订阅名 */ }', [E2E]),
    ("笺点不足又把人说去「开一笺」（那一格一个点也不送）", STATE,
     '  if (state.points < n) {\n'
     '    toast("笺点不足。去「我的」展开「测试订阅」：开哪一笺，那一笺就不再扣点");\n'
     '    return false;\n'
     '  }',
     '  if (state.points < n) { toast("笺点不足，去「我的」开一笺"); return false; }', [E2E]),
    # ---- 第五十五轮：送点按「这次真的开了几笺」算，不再是一台印钞机 ----
    ("送点回到写死的 16：那四枚签买完还在原处，连点两下就是 32", ME,
     "  const gift = 8 * opened.length;",
     "  const gift = 16;", [E2E]),
    ("数「开了几笺」时不看它原来是关的还是开的（本来就全开着也照送 24）", ME,
     '  const opened = ["yi", "wei", "yan"].filter((k) => !was[k] && state.modules[k]);',
     '  const opened = ["yi", "wei", "yan"].filter((k) => state.modules[k]);', [E2E]),
    ("全笺开着时点单笺，把订阅悄悄降回单笺（另外两笺重新开始扣点）", ME,
     '  if (plan !== "all" && state.plan === "all") {\n'
     "    save(state); paintNav(); renderMe();\n"
     "    toast(gift ? `已补开${MOD_NAME[plan]}，送 ${gift} 点（全笺还开着）`\n"
     "               : `${MOD_NAME[plan]}本来就开着，全笺不变`);\n"
     "    return;\n"
     "  }",
     '  if (plan === "impossible" && state.plan === "all") {\n'
     "    save(state); paintNav(); renderMe();\n"
     "    return;\n"
     "  }", [E2E]),
    ("签上又写死一个「送 16 点」——送多少从来不由标签决定", HTML,
     '          <button class="chip" data-buy="yi">开衣笺</button>',
     '          <button class="chip" data-buy="yi">开衣笺（送 16 点）</button>', [E2E]),
    # —— 第三十二轮：记下来没人读的、截断没人说的
    ("群话术里前五道不带总数（屏上明明列着六道）", WEI,
     '  const line2 = ok.length ? `可以点：${ok.join("、")}${safe.length > ok.length ? ` 等 ${safe.length} 道` : ""}。`\n'
     "    : `建议先问一圈忌口。`;",
     '  const line2 = ok.length ? `可以点：${ok.join("、")}。`\n'
     "    : `建议先问一圈忌口。`;", [E2E]),
    ("言笺超 200 条切掉了但不说", STATE,
     "  trimLoss.cards = Math.max(0, before.cards - s.yanCards.length);",
     "  trimLoss.cards = 0;", [E2E]),
    ("贴进来的字被掐了但不说", STATE,
     "  trimLoss.chars = Math.max(0, before.chars - textLen(s.weiMenu) - textLen(s.yanText));",
     "  trimLoss.chars = 0;", [E2E]),
    ("排过的桌超上限切掉了但不说", STATE,
     "  trimLoss.hist = Math.max(0, before.hist - s.weiHist.length);",
     "  trimLoss.hist = 0;", [E2E]),
    ("网关自述里的 tasks 又没人读了（有聊天模型就一律说可用）", ME,
     '      const can = (k) => t[k] === true ? "可用" : t[k] === false ? "不行" : "没自述";',
     '      const can = (k) => "可用";', [E2E]),
    # —— 第三十三轮：冷暖调这一句（判定算出来的，三处都得说同一句）
    # 两条「只改一端」的配对：一端不说了，两端就对不上（consistency 比的是导出原样）；
    # JS 这一端不说了，界面上那句也跟着没。
    ("冷暖这一句 JS 端不产了（另一端还在说）", ENG,
     "      thin, closetN: list.length,\n      toneLine: toneLine(newItem.color, list)",
     "      thin, closetN: list.length", [CONSISTENCY, E2E, ENGINE_TEST]),
    ("冷暖这一句网关端不产了（另一端还在说）", GATE,
     '        "thin": len(scored) < 5, "closetN": len(scored),\n        "toneLine": tone_line(item.get("color"), wardrobe),',
     '        "thin": len(scored) < 5, "closetN": len(scored),', [CONSISTENCY]),
    ("冷暖这一句在屏幕附注里被摘掉（长图和复制还带着）", YI,
     '    if (r.toneLine) {\n      note.textContent = (note.textContent ? note.textContent + " " : "") + r.toneLine;\n    }',
     "    // 屏幕上不说", [E2E]),
    ("冷暖这一句从复制的话术里掉了（屏幕上明明有）", CARD,
     "  if (r.toneLine) parts.push(r.toneLine);          // 冷暖调这一句：屏幕上有的，复制出去也得有",
     "  // 话术里不带", [E2E]),
    ("长图的依据行不带冷暖这一句（短版兜底也没了意义）", CARD,
     '  return `柜里最像的一件：「${r.basis.name}」· 色差 ${r.gap} · ${nearWord(r.gap)}${wear}${thin}`\n'
     '    + (r.toneLine ? ` ${r.toneLine}` : "");',
     '  return `柜里最像的一件：「${r.basis.name}」· 色差 ${r.gap} · ${nearWord(r.gap)}${wear}${thin}`;',
     [E2E]),
    ("柜子里冷暖不分明也硬找话说（六成那道闸拆了）", ENG,
     '    if (mN / n < 0.6) return "";',
     '    if (false) return "";', [ENGINE_TEST, CONSISTENCY]),
    # —— 第三十四轮：笺册里那整张笺
    ("text 与那一行一样的存档也摆「全文」（点了什么也不会变）", ME,
     "      const canOpen = !!a.text && a.text !== a.quote;",
     "      const canOpen = !!a.text;", [E2E]),
    ("「全文」点开还是那一行（签成了摆设）", ME,
     "      const body = open ? a.text : (a.quote || \"\");",
     "      const body = a.quote || \"\";", [E2E]),
    ("删掉一张之后不收回摊着全文的那几张（下标前移会指到别的笺）", ME,
     "      albumOpen = [];          // 下标整体前移了，摊着全文的那几张会指到别的笺上\n"
     "      save(state); renderMe(); haptic(\"LIGHT\");",
     "      save(state); renderMe(); haptic(\"LIGHT\");", [E2E]),
    ("「全文」只能收不能开", ME,
     "      if (at >= 0) albumOpen.splice(at, 1); else albumOpen.push(i);",
     "      if (at >= 0) albumOpen.splice(at, 1);", [E2E]),
    ("摊开的全文把换行吃掉（pre-wrap 被摘）", CSS,
     ".slip-body.full { white-space: pre-wrap; }",
     ".slip-body.full { white-space: normal; }", [E2E]),
    # —— 第三十轮：今天穿了什么
    ("「今天」按 24 小时内算（昨晚十一点那件被算进今天）", YI,
     "  return state.wardrobe.filter((w) => w.lastWorn && dayStr(w.lastWorn) === t);",
     "  return state.wardrobe.filter((w) => w.lastWorn && Date.now() - w.lastWorn < 86400000);", [E2E]),
    ("今天穿过的名字不收，全摊出来（360 上撑成横幅）", YI,
     "  const shown = today.slice(0, 3);",
     "  const shown = today;", [E2E]),
    ("一件都没记时那一行什么都不说（空白不是答案）", YI,
     '    : "今天还没记穿了什么。柜里那件的操作条上有「今天穿了」。";',
     '    : "";', [E2E]),
    ("点今天那排的名字不选中（只是好-looking 的文字）", YI,
     "      state.clothSel = id; save(state); renderCloset();",
     "      save(state); renderCloset();", [E2E]),
    ("带着搜索点被筛掉的名字不清搜索（点了没反应）", YI,
     "      if (!closetList().some((x) => x.id === id)) {\n"
     "        state.closetSeason = \"all\";\n"
     "        const s = $(\"#clothSearch\"); if (s) s.value = \"\";\n"
     "      }",
     "      // 不清筛：那件在屏上不存在，用户只会以为这行字坏了", [E2E]),
    ("撤销「今天穿了」只退回次数，不退回上次穿的时间", YI,
     "    w.worn = before.worn; w.lastWorn = before.lastWorn;",
     "    w.worn = before.worn;", [E2E]),
    ("撤销「今天穿了」不退回次数（账还是多一笔）", YI,
     "    w.worn = before.worn; w.lastWorn = before.lastWorn;",
     "    w.lastWorn = before.lastWorn;", [E2E]),
    # 这条第一版是**假注入**：只把 padding 从 4px 收到 1px——签的高度是行高撑起来的
    # （#closetNote span 的 line-height:1.8 × 13px ≈ 23px），改 padding 改不到 24px 以下，
    # 于是「改了源码，e2e 全都过了」。真正的缺陷形状是「把这排签压成文字大小」，
    # 那要连行高一起收，所以注入是 compound。
    ("摘要里那排签被压成文字大小（触摸高度掉到 24px 以下）", CSS,
     "#closetNote .chip { padding: 4px 11px; margin: 0 0 0 6px; vertical-align: middle; }",
     "#closetNote .chip { padding: 0 6px; line-height: 1; margin: 0 0 0 6px; vertical-align: middle; }",
     [E2E]),
    # 三十五轮：屏幕附注和长图的依据行说的是同一句判定话，以前各抄一份阈值。
    # 这两条盯的是两种不同的坏法：①两份都在、但分了家（屏幕一档、长图一档）；
    # ②屏幕这份整个不说档名了（长图还说）。只测①的话，②这种「少半句」会溜过去。
    ("把屏幕上那句的色差阈值另抄一份（和长图分了家）", YI,
     "      const near = nearWord(r.gap);",
     '      const near = r.gap < 15 ? "几乎同色" : r.gap < 30 ? "同色系" : "隔得开";',
     [E2E]),
    ("屏幕上不再说色差档名（长图说，屏幕不说）", YI,
     "      const near = nearWord(r.gap);",
     '      const near = "";',
     [E2E]),
    # 三十六轮：localStorage 之外还有 Capacitor Preferences 那一份「保险丝」。
    # 四条各管一种坏法——前三条是「没擦 / 没等擦完 / 擦之前先写错了」，第四条是
    # 「擦失败了却不承认」。分开写是因为每一种在屏幕上都是不同的谎话，合在一条
    # 就说不清是哪道断言救的场。
    ("清空只删本机，不擦保险丝那一份", APP,
     "    await Promise.race([eraseNativeBackup(), new Promise((r) => setTimeout(r, 2000))]);",
     "    // 忘了擦保险丝", [E2E]),
    ("擦保险丝不等它做完就 reload", APP,
     "    await Promise.race([eraseNativeBackup(), new Promise((r) => setTimeout(r, 2000))]);",
     "    Promise.race([eraseNativeBackup(), new Promise((r) => setTimeout(r, 2000))]);",
     [E2E]),
    ("保险丝写的还是内存那份（导入完就 reload 时它是上一代）", UI,
     "  const prefs = prefsPlugin();\n  const json = storeJson();",
     "  const prefs = prefsPlugin();\n  const json = JSON.stringify(state);",
     [E2E]),
    ("没擦干净也不承认（照样说「已清空」）", APP,
     "      fuseRefilled = true;",
     "      // 不记这一笔", [E2E]),
    # 三十七轮：六个「数字与话对不上」。每条都对应 §38 里一格（第三条对应第 33 节那格，
    # 那一格以前把自己的名字写在检查名里、断言却量反了）。
    ("「其他」那一类算了不画（四道饮料报成一道没有）", WEI,
     '    + (kinds["其他"] ? ` / 其他 ${kinds["其他"]}` : "");',
     '    + "";', [E2E]),
    ("言笺上限改回头切（说的是留最新，留的是最旧）", STATE,
     "  s.yanCards = (s.yanCards || []).slice(-YAN_CAP);",
     "  s.yanCards = (s.yanCards || []).slice(0, YAN_CAP);", [E2E]),
    ("网关没自述也念成「可用」", ME,
     '      const can = (k) => t[k] === true ? "可用" : t[k] === false ? "不行" : "没自述";',
     '      const can = (k) => t[k] === false ? "不行" : "可用";', [E2E]),
    ("填了网关还说「数据只在这台设备」", UI,
     '    ? "文字与照片会发往你填的那个地址" : "数据只在这台设备";',
     '    ? "数据只在这台设备" : "数据只在这台设备";', [E2E]),
    ("百分比又拿 5MB 当分母（照片正在丢却报尚有余量）", STATE,
     "pct: Math.round((len / SHED_AT) * 100)",
     "pct: Math.round((len / (5 * 1024 * 1024)) * 100)", [E2E]),
    ("群话术里的人数写死成「两个人」", WEI,
     "    couple: `今晚按 ${n} 个人的胃来。`,",
     "    couple: `今晚按两个人的胃来。`,", [E2E]),
    ("言笺那一屏重新教用户存一个没处放的录音", HTML,
     '      <p class="tiny">贴文字即可。</p>',
     '      <p class="tiny">贴文字即可。语音请先转文字。通话请自己存录音。</p>', [E2E]),
    # 三十八轮：读屏器与键盘。这一批里有两条是**复合**的（一条改开头一条改结尾），
    # 因为「退回旧结构」必须成对改，只改一半会让解析器自己补出一个洞来——
    # 那种红是「文件坏了」的红，不是缺陷的红。
    ("提示回到「每次新造一个带 aria-live 的节点」", UI,
     "  h.appendChild(n);",
     '  n.setAttribute("aria-live", "polite");\n  document.body.appendChild(n);', [E2E]),
    ("常驻的提示区丢了 aria-live", HTML,
     '  <div id="toasts" role="status" aria-live="polite"></div>',
     '  <div id="toasts"></div>', [E2E]),
    ("底栏不再说「我在哪一笺」", UI,
     '    nb.setAttribute("aria-current", "page");',
     "    // 不给当前页留记号", [E2E]),
    ("引导页那三张卡又被「我的」那一排绑了一遍", APP,
     '  $$("#me [data-home]").forEach((el) => {',
     '  $$("[data-home]").forEach((el) => {', [E2E]),
    ("品类那一排签重建完不找回焦点", YI,
     "    b.onclick = () => { state.yiCat = b.dataset.cat; save(state); renderCats(); };\n  });\n  restoreFocus(fk);",
     "    b.onclick = () => { state.yiCat = b.dataset.cat; save(state); renderCats(); };\n  });",
     [E2E]),
    ("引导页的选择卡退回一个带 onclick 的 div", HTML,
     '        <button type="button" class="card mode-card on" data-home="yi" aria-pressed="true">'
     '<b class="serif"><span class="seal-mark" aria-hidden="true">衣</span>衣笺</b>'
     '<span class="tiny">买之前，先问柜子</span></button>',
     '        <div class="card mode-card on" data-home="yi" aria-pressed="true">'
     '<b class="serif"><span class="seal-mark" aria-hidden="true">衣</span>衣笺</b>'
     '<span class="tiny">买之前，先问柜子</span></div>', [E2E]),
    ("言笺那一行整个退回一个 label（按钮又住进 label 里）", YAN,
     '    <div class="check ${c.done ? "done" : ""}${second ? "" : " no-when"}">\n'
     "      <label class=\"ck-main\">",
     '    <label class="check ${c.done ? "done" : ""}${second ? "" : " no-when"}">\n'
     "      <span class=\"ck-main\">",
     [E2E],
     # 这两段的收尾锚点原来只写 `    </div>`;`——它在 yan.js 里出现 4 处，而 sub_once 换的是
     # **第一处**（第 424 行，yanCal 那一块）。也就是说这条注入一直改错了地方：
     # 它把日历的收尾改成 `</label>`，语法直接坏掉，于是「炸」只是因为编译不过，
     # 而不是因为「按钮住进 label」这件真事。这正是 preflight 该抓的形状——现在它抓到了。
     # 修法是把锚点写长到只剩一处：带上前面那行只在这一张卡里出现的 jump 行。
     [(YAN, '      ${jump.length ? `<div class="yan-jump">${jump.join("")}</div>` : ""}\n    </div>`;',
           '      ${jump.length ? `<div class="yan-jump">${jump.join("")}</div>` : ""}\n    </label>`;'),
      (YAN, '      </label>\n      <span class="acts">', '      </span>\n      <span class="acts">')]),
    ("换屏不再刷新那个屏幕外的标题（念的是上一次的判定）", UI,
     'function enterReport() { paintReportTitle(); paintReportActions(); }',
     'function enterReport() { paintReportActions(); }', [E2E]),
    # 三十九轮：触摸目标与缩放。这一批全在 styles.css 的几行 padding 上——第 34 轮那条教训
    # （只改 padding 改不动被 line-height 撑起来的高度，于是注入没有牙）在这里逐条验过：
    # 每一条都连着 min-height 一起收，收完确实掉到 32 以下，红的是 §41 那两格点名的清单。
    ("双指缩放又锁回去", HTML,
     'content="width=device-width, initial-scale=1, viewport-fit=cover"',
     'content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover"',
     [E2E]),
    ("撤销那枚签又被压回文字大小", CSS,
     "  cursor: pointer; flex: none; padding: 9px 12px 9px 16px; min-height: 34px;\n"
     "  margin: -6px -8px -6px -10px; border-radius: 999px;",
     "  cursor: pointer; flex: none; padding: 2px 0 2px 4px;", [E2E]),
    ("勾选框退回浏览器默认那一格（13px 高）", CSS,
     ".check input { margin-top: 4px; accent-color: var(--ink); min-width: var(--ck-col); min-height: 24px; }",
     ".check input { margin-top: 4px; accent-color: var(--ink); }", [E2E]),
    ("「挑一天」那个日期框缩回 5px", CSS,
     "  border: 1px solid var(--line); border-radius: 10px; padding: 7px 8px; min-height: 44px; min-width: 132px;",
     "  border: 1px solid var(--line); border-radius: 10px; padding: 5px 8px;", [E2E]),
    ("开笺的入口缩回 6px 那一行", CSS,
     ".topup summary { cursor: pointer; list-style: none; padding: 10px 0; }",
     ".topup summary { cursor: pointer; list-style: none; padding: 6px 0; }", [E2E]),
    ("「挪 / 时间」两枚签缩回 31px 高", CSS,
     "  margin: -9px 0; padding: 12px 8px; border-radius: 10px; min-height: 44px; min-width: 44px;",
     "  margin: -6px 0 -6px 0; padding: 10px 8px; border-radius: 10px;", [E2E]),
    # 四十轮：mode 终于进了判定。前两条是「只改一端」的配对——这一族的 bug 形状就是
    # 「两端各自内部一致，但排出来的桌不一样」，所以 consistency 与差分 fuzz 都要有牙；
    # 后三条量的是屏幕这一侧：本地那一支丢掉 mode、换了人不提示、点了不刷新。
    ("只有 JS 端不看 mode（两端桌序分家）", ENG,
     '    const pushed = (dish) =>\n      (mode === "work" && late.has(dish)) ||\n'
     '      (mode === "home" && (late.has(dish) || HEAVY_RE.test(dish)));',
     "    const pushed = (dish) => false;", TWO_END),
    ("只有 PY 端不看 mode（两端桌序分家的另一半）", GATE,
     '        pushed = (mode == "work" and d in late) or \\\n'
     '                 (mode == "home" and (d in late or HEAVY_RE.search(d)))',
     "        pushed = False", TWO_END),
    ("本地引擎这一支把 mode 丢了（离线手机按四张签排出一桌）", API,
     "    return Engine.wei(menu, people, mode);",
     "    return Engine.wei(menu, people);", [E2E]),
    ("换了这桌的人却不提示上一版（只盯菜单）", WEI,
     '  bar.style.display = menuChanged || modeChanged ? "flex" : "none";',
     '  bar.style.display = menuChanged ? "flex" : "none";', [E2E]),
    ("点了模式签不重算那根过期条", APP,
     "      markStaleWei();   // 换人要当场说出来：屏幕上那一桌已经过期了（见 wei.js）",
     "      // 不刷新过期条", [E2E]),
    # 四十一轮：导出与存长图。三条各管一种坏法——两条是「原生没走通就回落到一次
    # WebView 里根本不会发生的下载」（这一条要连着看 toast：回落之后说的是成功），
    # 第三条是「把交出去说成存好了」。
    ("备份分享失败后回落到一次假下载，还说成功", ME,
     "      toast(SHARE_FAILED, 5200);\n      return;",
     "      // 回落到浏览器那一路", [E2E]),
    # 2026-10：长图的落盘链路从三份收成了一份（card.js 的 saveCanvasPng），
    # 原生壳失败那一支现在只有一处。锚点跟着搬家——它盯的东西没变：
    # 失败必须**就在这里停住并说出 SHARE_FAILED**，不许掉进下面那次下载。
    ("长图分享失败后同样回落到假下载", CARD,
     "      reset();\n      toast(SHARE_FAILED, 5200);\n      return false;",
     "      reset();", [E2E]),
    ("原生里也说「已导出：浏览器的下载里能看到」", UI,
     "  return hasNative() ? SHARE_HANDOFF : `已${what}：浏览器的下载里能看到`;",
     "  return `已${what}：浏览器的下载里能看到`;", [E2E]),
    ("没有判定时「存成长图」没被标成「此刻不许用」（换轨之后只标 aria-disabled）", YI,
     '  blockBtn($("#saveCard"), !ready);',
     '  blockBtn($("#saveCard"), false);', [E2E, DEADCTL]),
    # 四十二轮：出处那句「最近一次」。三条各是一种坏法：聚合回 some(remote)、
    # 时间戳不记了、界面上干脆写死。后两条管的是「都在」这种替系统担保的话。
    ("出处又回到「历史上任何一笺走过网关就算」", API,
     "    const newest = seen.reduce((a, b) => ((b.at || 0) > (a.at || 0) ? b : a));",
     '    const newest = seen.find((v) => v.via === "remote") || seen[0];', [E2E]),
    ("不记时间戳：「最近一笺」排不出来", API,
     "  function note(task, via, error) { last[task] = { via, error: error || null, at: Date.now() }; }",
     "  function note(task, via, error) { last[task] = { via, error: error || null }; }",
     [E2E]),
    ("界面上把那句写死成「最近一次判定是网关给的」", ME,
     '      : eng.via === "remote" ? `已指向网关，最近一笺（${GWTask[eng.task] || "那张"}）是网关给的。`',
     '      : eng.via === "remote" ? "已指向网关，最近一次判定是网关给的。"', [E2E]),
    ("排过的桌没了，改口替笺册担保「都还在」", STATE,
     "  if (l.hist) bits.push(`排过的桌只留 ${WEI_HIST} 桌，丢掉 ${l.hist} 桌（笺册里那些桌没动）`);",
     "  if (l.hist) bits.push(`排过的桌只留 ${WEI_HIST} 桌，丢掉 ${l.hist} 桌（笺册里那些桌都还在）`);",
     [E2E]),
    ("清掉勾掉的之后替笺册担保「那张整笺还在」", YAN,
     "    toastUndo(`已清掉 ${gone.length} 条了结的（笺册里那张没动）`, () => {",
     "    toastUndo(`已清掉 ${gone.length} 条了结的（笺册里那张整笺还在）`, () => {", [E2E]),
    # 四十三轮：死代码删了要钉住「别以后可能用为名再塞回来」。这三条注入都是
    # 「把刚删的东西原样放回导出面」——正是最可能发生的那种回归。
    ("零调用者的 avgColor 又被挂回导出面", ENG,
     "    analyze, yi, wei, yan, parseTime, tablePlan, dishKind,",
     "    analyze, avgColor: (img) => analyze(img).color, yi, wei, yan, parseTime, tablePlan, dishKind,",
     [E2E]),
    ("零调用者的 waiting 又被挂回导出面", API,
     "           beginTurn, giveUp, warm };",
     "           beginTurn, giveUp, waiting, warm };", [E2E],
     # 复合：函数体也要一起放回来，只挂导出名会抛 ReferenceError——那种红是「文件坏了」，
     # 不是「死代码回来了」。锚点用还在那儿的一行常量。
     [(API, '  const GAVE_UP = "先不等了";',
       '  function waiting() { return live.size > 0; }\n  const GAVE_UP = "先不等了";')]),
    # —— 第 57 轮：APK 自己声明的版本这一族（两条都打在 gradle 上，故意不动产物）
    ("gradle 写了个新 versionName 却没重跑打包（Play 看到的还是旧的那份）", GRADLE,
     '        versionName "', '        versionName "9.', [STORE]),   # 锚在前缀上：以后升版本不用再重挂
    # —— 第 58 轮：两处「挡住就要开口」的牙（摘掉 toast 必须红在 e2e 那两格）
    ("日期没填全又闷着不改（用户以为日期框坏了）", YAN,
     '      if (!w) { toast("日期没填全，时间先不动；要去掉它按旁边的「清掉」"); return; }',
     '      if (!w) return;', [E2E]),
    ("清空名字被弹回却不说（那一下弹动看着就像 bug）", YI,
     '    if (!v) { nm.value = w.name; toast("名字不能空着，已填回原来那个"); return; }',
     '    if (!v) { nm.value = w.name; return; }', [E2E]),
    # —— 第 57 轮下午段：这两处都是新门当场抓出来的（空柜排法签、引导页开局同步）
    # —— 第 57 轮 §5 那三条静态不变量的牙（每条都是"退回本轮之前的样子"，不是编出来的坏写法）
    ("模块开关的态又只写在 class 里（读屏器听不到哪笺开着）", ME,
     """  $$("[data-mod]").forEach((el) => {
    const on = !!state.modules[el.dataset.mod];
    el.classList.toggle("on", on);
    el.setAttribute("aria-pressed", String(on));
  });""",
     """  $$("[data-mod]").forEach((el) => {
    el.classList.toggle("on", !!state.modules[el.dataset.mod]);
  });""", [DEADCTLQ]),
    ("禁用态又用 opacity 表达（字被压到 2.30:1，读不出为什么按不动）", CSS,
     '.btn[aria-disabled="true"] { background: var(--paper-2); color: var(--ink-soft); border-color: var(--line); cursor: default; }',
     '.btn[aria-disabled="true"] { background: var(--paper-2); color: var(--ink-soft); border-color: var(--line); cursor: default; opacity: .4; }',
     [DEADCTLQ]),
    ("挡住又退回成真 disabled（对读屏器与键盘隐形，键盘门当场塌）", YI,
     'function blockBtn(el, blocked) {\n  if (!el) return;\n  el.setAttribute("aria-disabled", blocked ? "true" : "false");\n}',
     'function blockBtn(el, blocked) {\n  if (!el) return;\n  el.disabled = !!blocked;\n}',
     [DEADCTLQ]),
    ("把排法签的同步放回函数末尾（柜里空着时说明行改了、描边没改）", YI,
     """  // 排法那两枚必须和季节签一样**在早退之前**刷。以前它写在函数末尾，而两支空态
  // （筛空了 / 柜里真没东西）都在它前面 return：于是柜里空着时点「久未穿」，
  // state 改了、上面那行 closetNote 也跟着改口，唯独签上还亮着「常穿」——
  // 同一屏上两个面互相打脸。这一处是 dead_controls 的「空态」那一趟抓出来的。
  $$("[data-closet]").forEach((b) => {
    const on = b.dataset.closet === state.closetSort;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
  });
""", "", [DEADCTLN],
     [(YI, """  paintHero();
  closetNote();""",
       """  $$("[data-closet]").forEach((b) => {
    const on = b.dataset.closet === state.closetSort;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
  });
  paintHero();
  closetNote();""")]),
    ("引导页不再照 state 刷那三张卡（导进来的偏好会被出厂描边盖过去）", UI,
     """  if (id === "onboard") paintModeCards();   // 引导页不许带着旧描边开屏（见 app.js）
""", "", [DEADCTLQ]),
    ("花纹那一笺不再取表尾（删掉的那句话被顶回来了）", ENG,
     "      if (isPattern) quote = picks[picks.length - 1]();",
     "      if (isPattern) quote = picks[0](2);", [E2E]),
    # —— 第五十六轮：设备门。这台机器上好几个会话共用一个 adb server，串口还会漂，
    #    所以「忘带环境变量就退回到 5554」不是难看，是把包写到别人的机器上。
    #    这一组注入全打在判定与接线本身（test/device_guards.py 不碰真设备，只桩化 adb 问话）。
    ("设备门改判「名字里含 jian_test 就行」（jian_test2 会被当成自己那台）", DAVD,
     "    if name != WANT:", "    if WANT not in name:", [DEVGUARD]),
    ("设备门只把名字念一遍、不拦（问出来不是自己那台也照样往下跑）", DAVD,
     '        sys.exit(f"[设备门] {serial} 上是 AVD「{name or \'问不到名字\'}」，不是「{WANT}」。\\n"',
     '        print(f"[设备门] {serial} 上是 AVD「{name or \'问不到名字\'}」，不是「{WANT}」。\\n"',
     [DEVGUARD]),
    ("两台在线时让设备门自己挑一台（挑到的往往是别人的那台）", DAVD,
     "        if len(got) > 1:", "        if len(got) > 9:", [DEVGUARD]),
    ("放行之后不把串口写进 ANDROID_SERIAL（cap-cdp 那句裸 pidof 又会打到别人那台）", DAVD,
     '    os.environ["ANDROID_SERIAL"] = serial   # cap-cdp 里那句不带 -s 的 `adb shell pidof` 也跟着认这台\n',
     "", [DEVGUARD]),
    ("认领之后不打印是哪台（跑的人无从核对动的是谁的机器）", DAVD,
     "    if not quiet:", "    if False:", [DEVGUARD]),
    ("deeplink 又把「环境变量没给就退回 5554」写回来（正是撞见 suipai_r4 的那条路）", DDEEP,
     "SERIAL = require_avd()",
     'SERIAL = os.environ.get("ANDROID_SERIAL") or "emulator-5554"', [DEVGUARD]),
    ("设备侧脚本里冒出一句不带 -s 的 adb 调用", DSMOKE,
     '    cmd = [ADB, "-s", SERIAL] + list(args)', "    cmd = [ADB] + list(args)", [DEVGUARD]),
    ("接线扫描的清单被清空，而「整片扫」没有覆盖底线时会一路全绿", DGUARD,
     'SCRIPTS = ["device_verify.py", "device_deeplink.py", "device_gateway.py",\n'
     '           "device_perf.py", "release_smoke.py"]',
     "SCRIPTS = []", [DEVGUARD]),
    ("这道门自己丢了牙：check() 又肯收「两个值摆在一起」的假判定", DGUARD,
     "    if not isinstance(ok, bool):", "    if False:", [DEVGUARD]),
    # ---- 第五十七轮：报告页那三枚按钮的灰，是进屏当场算的 ----
    # dead_controls 管的是「按下去会静默 return 的控件不许亮着」（第 27 轮的规矩，这一轮
    # 才从逐例变成整片扫）。四条各打一种坏法：①三枚里少刷一枚的条件；②这一条路根本不刷；
    # ③把两条不同的条件并成一条（旧版那张没有 .new 的报告明明能复制，却被一起灰掉）；
    # ④整片扫退回只扫一屏——覆盖底线没人钉时，「什么都没扫到却全绿」就是这类门的默认失败模式。
    ("摘掉「有没有笺可复制」这一条（没笺时「复制这段话」连「此刻不许用」都没标）", YI,
     '  blockBtn($("#copyReport"), !reportCopyable());\n', "", [DEADCTLQ]),
    ("进报告页不再刷三枚按钮的灰（它们停在 index.html 里各自的说法上）", UI,
     'function enterReport() { paintReportTitle(); paintReportActions(); }',
     'function enterReport() { paintReportTitle(); }', [DEADCTLQ]),
    ("把「可复制」并到「能存图」那条条件上（旧版那张报告明明能复制却被标成不许用）", YI,
     '  blockBtn($("#copyReport"), !reportCopyable());',
     '  blockBtn($("#copyReport"), !ready);', [DEADCTLQ]),
    ("整片扫退回只扫「我的」一屏（少一半屏，没人说）", DDEAD,
     'SCREENS = ["onboard", "yi", "yi-report", "wei", "yan", "me"]',
     'SCREENS = ["me"]', [DEADCTL]),
    # 比上一条更狠的一格：三趟种子收成一趟。SCREENS 那条只弄红「屏数」与「认得三枚」，
    # 而这三种子各自守的是不同的坏法（空态养出静默的章、只剩一笺才量得到守卫型 toggle）——
    # 收成一趟是这类整片门最省事的作弊方式：跑得快、还全绿。
    ("三趟种子收成一趟（空态与「只剩一笺」那两趟不再扫）", DDEAD,
     'MODES = [("有内容", SEEDS, SCREENS),\n'
     '                 ("空态", {s: EMPTY for s in SCREENS}, SCREENS),\n'
     '                 ("只剩一笺", {s: ONE for s in ["me", "yi"]}, ["me", "yi"])]',
     'MODES = [("有内容", SEEDS, SCREENS)]', [DEADCTL]),
    # ---- 第五十七轮（补）：store_claims 那三格新牙 ----
    # 这道门是文本扫描 + AST 读脚本，最容易的坏法不是「查错了」，是**什么都没读到却全绿**。
    # 所以三条靶子里有两条钉的是「读空气」那格地板：一条让它当第一条红（地板有牙），
    # 一条把地板一起拆掉看红退到哪（证明地板是那条会点名的断言）。
    # 注意 `BAN = []`（清空禁词清单）这条**没写**：清空之后没有任何一句假话会被读到，
    # 而图上此刻本来就没有禁词——所有检查照旧全绿，是一条测不到的注入（#3 的规矩：换掉）。
    # 禁词那条要单独有牙，得让门去查一份「源文本里出现禁词但画到别处」的形状，那是改门的活。
    ("读图上的字取错了参数位（读出一条空表，只有地板认得出这是量空气）", SCLAIMS,
     'texts = [n.args[1].value for n in ast.walk(ast.parse(art_src))\n'
     '         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)\n'
     '         and n.func.attr == "text" and len(n.args) >= 2\n'
     '         and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)]',
     'texts = [n.args[0].value for n in ast.walk(ast.parse(art_src))\n'
     '         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)\n'
     '         and n.func.attr == "text" and len(n.args) >= 2\n'
     '         and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)]',
     [STORE]),
    # 上面那条改的是「读」，这一条连「读出来是空的」那句声明一起改：地板拆了之后
    # 红不会消失（内容那两格还盯着），但**再没人说「这一节在量空气」**——
    # 而 251-252 行记的就是上一次 exactly 这一步没人说、门自证了三天假绿。
    ("同上，且把「读不出来 = 量空气」那格地板一起拆掉（红退到内容检查，地板不点名了）", SCLAIMS,
     'texts = [n.args[1].value for n in ast.walk(ast.parse(art_src))\n'
     '         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)\n'
     '         and n.func.attr == "text" and len(n.args) >= 2\n'
     '         and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)]',
     'texts = [n.args[0].value for n in ast.walk(ast.parse(art_src))\n'
     '         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)\n'
     '         and n.func.attr == "text" and len(n.args) >= 2\n'
     '         and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)]',
     [STORE],
     [(SCLAIMS, "len(texts) >= 4", "len(texts) >= 0")]),
    ("文档 6.素材表 引的那行字换了说法、脚本照旧（两头对退成单向就看不见这一步）", STOREDOC,
     "一行「零账号 · 零广告 · 不联网也能用」", "一行「零账号 · 零广告 · 离线可用」", [STORE]),
    # 这条改完会**真跑一遍生成脚本且不指定输出目录**，于是图落回 store/。
    # 实测（两次跑进临时目录）当前脚本的产物与 store/ 里那两张逐字节相同，所以它是一次
    # 无变化的重写；但 store/ 没进版本库、git 救不回来——跑之前先拷一份 store/ 再说。
    ("跑生成脚本时不再传 JIAN_STORE_OUT：图落回 store/，临时目录成了空的", SCLAIMS,
     '    env = dict(os.environ, JIAN_STORE_OUT=td, PYTHONIOENCODING="utf-8")',
     '    env = dict(os.environ, PYTHONIOENCODING="utf-8")', [STORE]),

    # ── 第 60 轮：隐私政策。同一句话有**三个副本**——文档第 4 节那块正文、
    # docs/上架/privacy/index.html（真的挂在网上的那一页的源）、以及 GitHub 上已发布的那一份。
    # 前两个由 store_claims 逐句两头对（下面这七条钉的就是它）；第三个要联网，
    # 由 `python scripts/publish-privacy.py --check` 量（比 git blob，不进快速门禁）。
    ("政策那一页的某条条款少了半句，文档照旧——上线的那一份和商店材料不再是同一句话", PRIVPAGE,
     "<li>应用内置的判定是本地规则，不联网即可完成。离线可用是实测过的。</li>",
     "<li>应用内置的判定是本地规则，不联网即可完成。</li>", [STORE]),
    ("第 1 节的联系邮箱改了、政策正文与那一页没跟（三处各写一个邮箱，审查员看见哪一个？）", STOREDOC,
     "| 联系方式 | `1193046937@qq.com`", "| 联系方式 | `jian.example@163.com`", [STORE]),
    ("政策正文的落款又退回成一句占位符——那一格其实还没有答案，就不该带着它出包", STOREDOC,
     "联系方式：1193046937@qq.com", "联系方式：【待你确认的邮箱】", [STORE]),
    # 0.6.0：政策正文因为多了通知那一组权限而改写，落款日期跟着推到 2026-10-18。
    # 锚点随日期走，注入想验的那件事不变：把日期换回「发布当日」那种占位提醒，store_claims 必须红。
    ("政策落款那个更新日期又写成「发布当日」这种提醒而不是一天（它在那里躺了三轮）", STOREDOC,
     "更新日期：2026 年 10 月 18 日", "更新日期：【发布当日】", [STORE]),
    ("政策 URL 那一格少了一截、页面自己的 canonical 还是旧的：填错了地址没人发现", STOREDOC,
     "| 隐私政策 URL | `https://tbj0623.github.io/jian-privacy/`",
     "| 隐私政策 URL | `https://tbj0623.github.io/jian/`", [STORE]),
    ("政策页多出来那句被文档改了个说法、页面照旧（两头对退成单向就看不见这一步）", STOREDOC,
     "那一段与笺无关——笺没有服务器，也读不到这些。", "那一段与笺无关。", [STORE]),
    # 这一条改的是「读」：把那一页的解析退化成只认条款。没有那格 13 条地板的话，
    # 红会退成「少比了四条也算过」——同一个形状在特性图那节已经记过一次（251-252 行）。
    ("政策页的解析退化成只认 <li>（标题/首句/落款不读了）：靠 13 条地板点名，不许悄悄少比", SCLAIMS,
     r'    for mu in re.finditer(r"<(h1|p|li|dt|dd)\b[^>]*>([\s\S]*?)</\1>", t):',
     r'    for mu in re.finditer(r"<(li)\b[^>]*>([\s\S]*?)</\1>", t):', [STORE]),
    ("政策页偷偷挂了一个外部字体：页面自己那句「不加载任何第三方」立刻成假话，而名单是唯一证人", PRIVPAGE,
     '<link rel="canonical" href="https://tbj0623.github.io/jian-privacy/" />',
     '<link rel="canonical" href="https://tbj0623.github.io/jian-privacy/" />\n'
     '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Noto+Sans+SC" />',
     [STORE]),
    # 这一发改的是**那条规矩本身**：把「按引用形状抓」退化成「按几个域名关键字抓」。
    # 退回去之后 store_claims 里那格样张自测（喂它两枚站外引用）立刻红——
    # 这一格地板量的是「import 进来的规矩还会不会抓」，比数名单长度强。
    ("政策页那条「不许引站外东西」的规矩退化成域名黑名单（换一个没抄进来的域名就漏）", PUBSCRIPT,
     '        if _origin(v) != mine:\n            hits.append(v)',
     '        if "googleapis" in v or "analytics" in v:\n            hits.append(v)', [STORE]),
    # 页面上「看得见的邮箱」与 `mailto:` 里那个真地址是两份东西：改文档、改可见文字、
    # 忘改 href，审查员看见的还是一个能收信的地址——用户点下去寄到别处。
    ("那一页可见的邮箱没改、`mailto:` 忘了跟（点「联系方式」寄到一个没人收的旧地址）", PRIVPAGE,
     'href="mailto:1193046937@qq.com">1193046937@qq.com</a>',
     'href="mailto:jian-old@163.com">1193046937@qq.com</a>', [STORE]),
    ("那一页的 <title> 与页面上那行 h1 分家（浏览器标签页与页面自己各说一句话）", PRIVPAGE,
     "<title>笺 隐私政策</title>", "<title>隐私政策 · 笺</title>", [STORE]),
    # 文档侧那格地板：它和已证过的页面侧地板是一对，只证一边等于另一半没门。
    # 把章节锚从 4 挪到 5，读出来的条目完全变一批，两侧都比不上。
    ("政策正文的锚飘到别的章节去了（文档侧那格地板必须也认得出「读的不是那一段」）", SCLAIMS,
     'blk = re.search(r"^## 4\\.', 'blk = re.search(r"^## 5\\.', [STORE]),
    ("政策页的源路径在文档里改了名、门还在读老地方（门不许保护一个没人引用的文件）", STOREDOC,
     "源就是仓库里的 `docs/上架/privacy/index.html`", "源就是仓库里的 `docs/privacy/index.html`",
     [STORE]),

    # ── 第 59 轮：穿用记录改得动（14 发，靶子是 e2e 第 56 节，走窄跑手 e2e#56）──
    # 这一族的来源是 #17 那条线交来的 `test/_round59_injections.pending.md`：
    # 它在盒子（快照目录）里先逐条验过红，这里换成改真源码 + 跑归它管的那道门。
    # 每一发的「预期红」写在名字里，跑完对着日志逐条点名字看：红的那条必须就是它。
    ("穿用记录：改「上次穿」的写回整个摘掉（快捷签与日期框按下去什么都不改）", YI,
     "function wearSetDay(w, at, label) {\n  if (wornOnThatDay(w, at)) {",
     "function wearSetDay(w, at, label) {\n  if (true) return;\n  if (wornOnThatDay(w, at)) {",
     [E2E56]),
    ("穿用记录：次数 −1/＋1 的写回整个摘掉", YI,
     "function wearBump(w, d) {\n  const worn",
     "function wearBump(w, d) {\n  if (true) return;\n  const worn", [E2E56]),
    ("穿用记录：改完只 save、不 renderCloset（字段对了，画面没动——断言落在渲染面上的那一族）", YI,
     "  w.lastWorn = next.lastWorn;\n  save(state); renderCloset();\n  toastUndo(msg,",
     "  w.lastWorn = next.lastWorn;\n  save(state);\n  toastUndo(msg,", [E2E56]),
    ("穿用记录：改完不落盘（只内存里改 + 重画；只有整页重开那两格抓得到）", YI,
     "  w.lastWorn = next.lastWorn;\n  save(state); renderCloset();\n  toastUndo(msg,",
     "  w.lastWorn = next.lastWorn;\n  renderCloset();\n  toastUndo(msg,", [E2E56]),
    ("穿用记录：「同一个日历天只算一次」那道守卫摘掉（口径②的对手）", YI,
     'const wornOnThatDay = (w, at) => !!(w.lastWorn && dayStr(w.lastWorn) === dayStr(at));',
     "const wornOnThatDay = () => false;", [E2E56]),
    ("穿用记录：次数减到 0 不再清掉那条日子（瓷砖说没穿过、摘要说今天穿了）", YI,
     "applyWear(w, { worn, lastWorn: worn ? day : null },",
     "applyWear(w, { worn, lastWorn: day },", [E2E56]),
    ("穿用记录：0 次按 ＋1 不再把日子落在今天（造出「穿过 N 次却没有哪一天」）", YI,
     "  const day = worn && !w.lastWorn ? Date.now() : (w.lastWorn || null);",
     "  const day = w.lastWorn || null;", [E2E56]),
    ("穿用记录：还没到的那一天不挡，直接写进账（久未穿那层会反向少算）", YI,
     "    if (d.at > Date.now()) {", "    if (false) {", [E2E56]),
    ("穿用记录：日期没填全时**静默**挡下（第 57 轮禁的那种闷着不动）", YI,
     'if (!d) { toast("日期没填全，上次穿先不动；要记成还没穿过就把次数减到 0"); return; }',
     "if (!d) return;", [E2E56]),
    ("穿用记录：反悔按下去不真还回去（撤销键在那儿，账不回）", YI,
     "  toastUndo(msg, () => {\n    w.worn = before.worn;",
     "  toastUndo(msg, () => {\n    if (true) return;\n    w.worn = before.worn;", [E2E56]),
    # 这一发**不归 e2e#56 管**：拿真 disabled 挡一枚入口，§56 那两格抓不到（实测跑过，
    # 一红都没有，只是把跑手撞死了——撞死不算抓到）。它的家是第 57 轮那条静态禁令，
    # 而那条禁令原先只堵 `el.disabled =` 这一种写法，模板里的 `disabled="${…}"` 是漏的。
    ("穿用记录：挡改用真 disabled 属性（第 57 轮禁止的那种藏；归静态那条门管）", YI,
     'aria-disabled="${!w.worn}"', 'disabled="${!w.worn}"', [DEADCTLQ]),
    ("穿用记录：快捷签那一排多一枚（360 宽下把日期框顶到下一行，第 16 轮那堵签墙）", YI,
     'const WEAR_DAY_CHIPS = ["今天", "昨天", "前天"];',
     'const WEAR_DAY_CHIPS = ["今天", "昨天", "前天", "大前天"];', [E2E56]),
    ("穿用记录：normCloth 里「0 次就没有最后一次」那条钳位摘掉（外来备份带进来越界数据）", STATE,
     "  if (!o.worn) o.lastWorn = null;", "  if (false && !o.worn) o.lastWorn = null;", [E2E56]),
    ("穿用记录：「今天穿了」这笔账整个摘掉（只断「没变化」的断言，缺陷正好藏在什么都不做里）", YI,
     "  applyWear(w, { worn: (w.worn || 0) + 1,",
     "  if (true) return;\n  applyWear(w, { worn: (w.worn || 0) + 1,", [E2E56]),

    # ── 第 61 轮：网关地址存前不校验（#24 那句假确认）──
    # 这一族由 netguard 先在窄跑手里逐条验过红（`test/_round61_injections.pending.md` 是当时那份记录），
    # 这里换成改真源码。靶子全在 e2e §57（窄跑 e2e#57 约 20 秒一发）。
    ("网关地址：保存时不校验（第 61 轮那个原缺陷整个长回来），顺带丢掉 http 那句提醒", APP,
     "    const r = normApi(raw);",
     "    const r = { url: raw, why: \"\" };", [E2E57],
     [(APP, r"      ? (/^http:\/\//i.test(state.apiUrl)",
       r"      ? (/^NEVER_MATCH$/i.test(state.apiUrl)")]),
    # 「一个规则两份定义」这一发同时红两格：放宽 normApi 认任意 scheme，
    # 而开机那一侧退回另一条裸正则 —— 于是「当场说成了、重启后不算」又活了。
    ("网关地址：normApi 放宽成认任意 scheme，开机那侧另起一条裸正则（一个规则两份定义）", STATE,
     r"  const m = /^https?:\/\//i.exec(s);",
     r"  const m = /^[a-z][a-z0-9+.\-]*:\/\//i.exec(s);", [E2E57],
     [(STATE, "  s.apiUrl = normApi(s.apiUrl).url;",
       "  s.apiUrl = /^https?:\\/\\/\\S{1,200}$/i.test(String(s.apiUrl ?? \"\").trim())"
       " ? String(s.apiUrl ?? \"\").trim() : \"\";")]),
    # 反向那一发：规则收到过紧，任何非空地址一律判无效。只有「该收的必须收」那一族抓得到它
    # ——与第 59 轮 I14 同一课：只断「挡住了」的断言，看不见「把对的也挡了」。
    ("网关地址：规则过紧，任何非空地址一律判无效（正向那一族的对手）", STATE,
     '  return { url: s, why: "" };', '  return { url: "", why: "形状不对" };', [E2E57]),
    ("网关地址：拒收时把用户敲的那一串抹掉（他多半只是想补个 http:// 前缀）", APP,
     '      toast("没存：" + r.why, 5200);',
     '      renderMe(); toast("没存：" + r.why, 5200);', [E2E57]),
    ("网关地址：拒收时什么都不说（第 57 轮禁的那种静默早退）", APP,
     '      toast("没存：" + r.why, 5200);', "      void 0;", [E2E57]),
    ("网关地址：拒收之后用真 disabled 把入口藏起来（第 57 轮裁决禁止的那种藏）", APP,
     '      toast("没存：" + r.why, 5200);',
     '      $("#saveApi").disabled = true; toast("没存：" + r.why, 5200);', [E2E57]),
    ("网关地址：局域网 http 那句「不加密」被顺手摘掉（政策里明写着的那一条，界面上却不提了）", APP,
     '"已记下网关。这一台走的是 http，不加密——局域网里用可以"', '"已记下网关"', [E2E57]),
    ("网关地址：那句解释只留默认 1.8 秒（长句子读不完等于没说）", APP,
     '      toast("没存：" + r.why, 5200);', '      toast("没存：" + r.why);', [E2E57]),
    ("网关地址：把「留空＝只用本地」也当成坏输入挡掉（那条路是默认且最常用的一条）", APP,
     "    if (raw && !r.url) {", "    if (!r.url) {", [E2E57]),
    ("网关地址：上限悄悄收紧（200 → 100），一条正常地址被判太长", STATE,
     "const API_MAX = 200;", "const API_MAX = 100;", [E2E57]),
    ("网关地址：当场说「已记下」、重启后不算（开机把那一条清成空）", STATE,
     "  s.apiUrl = normApi(s.apiUrl).url;", '  s.apiUrl = "";', [E2E57]),
    ("网关地址：「不加密」那句不分 https 一起说（说错的加密状态比不说更坏）", APP,
     r"      ? (/^http:\/\//i.test(state.apiUrl)",
     r"      ? (/^https?:\/\//i.test(state.apiUrl)", [E2E57]),
    ("网关地址：解释退成一句「形状不对」，不给能照抄的样子（用户不知道改哪儿）", STATE,
     '  if (!m) return { url: "", why: "地址要以 http:// 或 https:// 开头，比如 http://192.168.1.5:8787" };',
     '  if (!m) return { url: "", why: "形状不对" };', [E2E57]),

    # ── 第 62 轮：应用内那条隐私政策入口 ──
    # 这条地址从这一轮起有**四份副本**（商店材料 / 政策页 canonical / 已发布那一份 / 应用里的 config.js），
    # 所以第一发红在 store_claims 那四处对账；其余六发红在 dead_controls 新加的那一节
    # （窄跑 --quick 就够，一发约一分半）。
    ("政策入口：应用里那条地址被改成另一个站点（用户在应用里点开的不是商店页承诺的那一页）", CFGJS,
     'privacyUrl: "https://tbj0623.github.io/jian-privacy/",',
     'privacyUrl: "https://example.com/privacy/",', [STORE]),
    ("政策入口：链子上加了 preventDefault（把系统那一跳掐掉，只剩一枚看着能点的字）", ME,
     '  $("#privacyLink").onclick = () => {\n    toast("在系统浏览器里打开这一页',
     '  $("#privacyLink").onclick = (e) => {\n    e.preventDefault();\n    toast("在系统浏览器里打开这一页',
     [DEADCTLQ]),
    ("政策入口：按下去什么都不说（安卓那侧打不开时是真的静默，第 57 轮禁的那种）", ME,
     '  $("#privacyLink").onclick = () => {\n    toast("在系统浏览器里打开这一页；没看到新页面的话，按「复制这段网址」再粘到地址栏", 5200);',
     '  $("#privacyLink").onclick = () => {\n    void 0;', [DEADCTLQ]),
    ("政策入口：me.js 不读 config 而是自己抄了一份字面（两份副本，改一处漏一处）", ME,
     "  const url = window.JIAN_CONFIG.privacyUrl;",
     '  const url = "https://tbj0623.github.io/jian-privacy/";', [DEADCTLQ]),
    ("政策入口：链子丢了 rel=\"noopener\"（target=_blank 开出去的新页能反控这一页）", ME,
     '<a class="policy-url" id="privacyLink" href="${esc(url)}" target="_blank" rel="noopener"',
     '<a class="policy-url" id="privacyLink" href="${esc(url)}" target="_blank"', [DEADCTLQ]),
    ("政策入口：链上只写「隐私政策」四个字不给网址（用户确认不了自己去的是哪儿）", ME,
     ">${esc(url)}</a>", ">隐私政策</a>", [DEADCTLQ]),
    ("政策入口：网址被写死进 index.html 那个容器（绕开了「运行时只有一份定义」）", HTML,
     '<div id="privacyBox" class="privacy"></div>',
     '<div id="privacyBox" class="privacy">https://tbj0623.github.io/jian-privacy/</div>',
     [DEADCTLQ]),

    # ── 第 63 轮：味笺的人名改得动、删人要预告（靶子是 e2e §58，窄跑 e2e#58）──
    # 这一族的注入是我（lead）替那条线补的——它 60 轮预算用尽时没来得及跑验红，
    # 所以每条都在窄跑手里实跑过「先看见红」才留下，红的格子名写在 spec 上方的 §58 清单里。
    ("味笺人名：改完不写盘（只活在内存里，重开就回到旧名字）", WEI,
     "      p.name = v; save(state);", "      p.name = v;", [E2E58]),
    ("味笺人名：改完顺手重建整片（焦点被抢走，就地改这一格的意义全没）", WEI,
     "      p.name = v; save(state);", "      p.name = v; save(state); renderWeiPeople();", [E2E58]),
    ("味笺人名：只改名字不刷行上那两句（「移除」的预告还写着旧名字，屏上两处各说一个）", WEI,
     '      const del = inp.closest(".topbar").querySelector("[data-del]");',
     "      const del = null;", [E2E58]),
    ("味笺人名：空名字静默弹回（界面动了一下、动的方向像 bug，第 58 轮禁的那种）", WEI,
     '      if (!raw) { inp.value = p.name; toast("名字不能空着，已填回原来那个"); return; }',
     "      if (!raw) { inp.value = p.name; return; }", [E2E58]),
    ("味笺人名：重名那一支不吭声（两行会看着一样，而用户不知道按的是哪一行）", WEI,
     "        : dup ? `改成「${v}」了 · 这桌已经有一个「${v}」，两行会看着一样`\n          : ",
     "        : ", [E2E58]),
    ("味笺人名：「移除」那句预告退化成一句「移除这一行」（按之前听不出会带走几项忌口）", WEI,
     'aria-label="${esc(delAria(p.name, p.chips.length))}"',
     'aria-label="移除这一行"', [E2E58]),
    ("味笺人名：移除那一句不再点名带走了哪几项忌口（数据没了还不说）", WEI,
     '        + (n ? `，连带去掉 ${n} 项忌口（${snapshot.chips.join("、")}）` : "，他没挂忌口"), () => {',
     "        , () => {", [E2E58]),
    ("味笺人名：反悔只把人塞回去、忌口清空（下一次排桌吃的就是它）", WEI,
     "          { ...snapshot, chips: snapshot.chips.slice() });",
     "          { ...snapshot, chips: [] });", [E2E58]),
    ("味笺人名：反悔那句只说「回来了」（忌口没回来，话却说得像全回来了）", WEI,
     '        toast(`「${snapshot.name}」回到这桌`\n          + (n ? `，${n} 项忌口一起回来了` : ""));',
     '        toast(`「${snapshot.name}」回来了`);', [E2E58]),

    # ── 第 64 轮：订阅关得掉，也不许写着指向已关掉那一笺（靶子 e2e §59，窄跑 e2e#59）──
    # 来源是那条线交来的 `test/_round64_injections.pending.md`（19 发，每发的「红的格子」都是实跑输出）。
    # 其中「不给反悔」「不摆出口」「没造出来」「撤销不填回」这四发会先点名红、再把后面那一次
    # page.click 卡到超时——红在超时之前，所以报的是「断言炸了」，不是撞死。
    ("订阅那一枚：取消只改内存不落盘（当场看着成了，重开又不是）", ME,
     "  save(state); renderWallet(); haptic(\"LIGHT\");",
     "  renderWallet(); haptic(\"LIGHT\");", [E2E59]),
    ("订阅那一枚：按下去话说了、plan 一个字没改（第 57 轮禁的那一类）", ME,
     "  state.plan = null;", "  state.plan = was;", [E2E59]),
    ("订阅那一枚：取消完不给反悔（toastUndo 退回 toast）", ME,
     "  toastUndo(`已取消${name}订阅：${tail}`, () => {\n"
     "    state.plan = was;\n"
     "    save(state); renderWallet();\n"
     "  });",
     "  toast(`已取消${name}订阅：${tail}`);", [E2E59]),
    ("订阅那一枚：该收的时候不收（造出来之后一直摆着）", ME,
     "    if (b) b.hidden = true;", "    if (b) b.hidden = false;", [E2E59]),
    ("订阅那一枚：没订阅时也把它造出来（一枚只能吐一句「现在就是未订阅」的签）", ME,
     "  if (!state.plan) {\n    if (b) b.hidden = true;\n    return;\n  }",
     "  if (!state.plan) {\n    if (!b) {\n"
     "      b = document.createElement(\"button\");\n"
     "      b.type = \"button\"; b.id = \"planOffX\"; b.className = \"chip\";\n"
     "      b.onclick = cancelPlan; b.textContent = \"取消订阅\";\n"
     "      $(\"#planName\").closest(\"p\").appendChild(b);\n"
     "    }\n    return;\n  }", [E2E59]),
    ("订阅那一枚：指向已关掉那一笺时照旧只印一个名字（本轮第②件事整条没做）", ME,
     "  $(\"#planName\").textContent = (PLAN_NAME[state.plan] || \"未订阅\")\n"
     "    + (state.plan && dead ? (state.plan === \"all\" ? \" · 这三笺都已经关掉了\""
     " : \" · 这一笺已经关掉了\") : \"\");",
     "  $(\"#planName\").textContent = (PLAN_NAME[state.plan] || \"未订阅\");", [E2E59]),
    ("订阅那一枚：那句「已经关掉了」不看模块，写死成只要有订阅就说", ME,
     "  const dead = !planCovers().some((k) => state.modules[k]);",
     "  const dead = !!state.plan;", [E2E59]),
    ("订阅那一枚：订阅指向已关掉那一笺时反而不摆出口（那个状态又回不去了）", ME,
     "  if (!state.plan) {",
     "  if (!state.plan || !planCovers().some((k) => state.modules[k])) {", [E2E59]),
    ("订阅那一枚：取消全笺那句还写着「这一笺」（三被说成一笺）", ME,
     "  const tail = (was === \"all\" ? \"三笺都\" : \"这一笺\")",
     "  const tail = (\"这一笺\")", [E2E59]),
    ("订阅那一枚：对着一笺已经关着的订阅也说「重新开始扣点」（同屏两句相反的话）", ME,
     "    + (live ? \"重新开始扣点\" : \"本来就关着，没在扣点\");",
     "    + \"重新开始扣点\";", [E2E59]),
    ("订阅那一枚：不写 aria-label（读屏器按之前不知道这一下要干什么）", ME,
     "  b.setAttribute(\"aria-label\", \"取消订阅（现在订阅的是\""
     " + (PLAN_NAME[state.plan] || state.plan) + \"）\");",
     "  void 0;", [E2E59]),
    ("订阅那一枚：不给 .chip（裸按钮 20px 高，全 App 那条命中区下限漏了它）", ME,
     "    b.type = \"button\"; b.id = \"planOff\"; b.className = \"chip\";",
     "    b.type = \"button\"; b.id = \"planOff\";", [E2E59]),
    ("订阅那一枚：标签长到不管行（360 的纸上越纸边）", ME,
     "  b.textContent = \"取消订阅\";",
     "  b.style.whiteSpace = \"nowrap\";\n  b.textContent = \"取消订阅\" + \"很\".repeat(30);",
     [E2E59]),
    ("订阅那一枚：取消之后不刷新那一行（落了盘，屏上还是旧名字）", ME,
     "  save(state); renderWallet(); haptic(\"LIGHT\");",
     "  save(state); haptic(\"LIGHT\");", [E2E59]),
    ("订阅那一枚：根本没造出来（订阅照旧只能开不能关）", ME,
     "    $(\"#planName\").closest(\"p\").appendChild(b);", "    void 0;", [E2E59]),
    ("订阅那一枚：取消那句不点名取消了什么", ME,
     "  toastUndo(`已取消${name}订阅：${tail}`, () => {",
     "  toastUndo(\"已取消订阅\", () => {", [E2E59]),
    ("订阅那一枚：撤销只说一句，不把订阅填回去", ME,
     "  toastUndo(`已取消${name}订阅：${tail}`, () => {\n"
     "    state.plan = was;\n"
     "    save(state); renderWallet();\n"
     "  });",
     "  toastUndo(`已取消${name}订阅：${tail}`, () => { });", [E2E59]),
    ("订阅那一枚：笺点那一格不再跟着订阅名走（「不限」那一格是死的）", ME,
     "  $(\"#points\").textContent = state.plan === \"all\" ? \"不限\" : state.points;",
     "  $(\"#points\").textContent = state.points;", [E2E59]),
    ("订阅那一枚：取消那一下把异常抛到外面", ME,
     "  if (wasOn) {",
     "  throw new Error(\"注入：取消订阅这一路抛异常\");\n  if (wasOn) {", [E2E59]),
]


def fail_reason(out):
    """这道门为什么红：(是不是某条断言变红, 那一句话)。
    sync API 里 page.wait_for_function 超时会直接抛 Python traceback，输出里没有以
    FAIL 开头的行，以前这里退化成「取最后三条拼起来再截 78 字符」，印出来的是一串
    `File "C:\\...\\python_embeded\\...`——那是 traceback 的文件行，异常名字正好被切掉。
    所以：断言行优先，没有就挑最后一条不像 traceback 上下文的话。
    断言行**最多带三条**：一条注入常常同时弄红几格，只印第一条会把「其实是哪一格在守」
    说错——第 30 轮那条「今天按 24 小时算」报的就是 §15 的一句 toast，而不是新写的那格。"""
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    hits = [l for l in lines if l.startswith("FAIL")][:3]
    if hits:
        return True, " ｜ ".join(hits)
    said = [l for l in lines if not l.startswith(("File ", "Traceback", "  ", "\t"))]
    return False, (said[-1] if said else "（没有输出）")


def run_gate(spec):
    # 规格可以是 (标签, 命令) 或 (标签, 命令, 额外环境变量)：多出来的那份 env 是给
    # 「同一道门跑一个窄场景」用的（见 DEADCTLN）——认证一条注入不该被迫等全量扫的十一分钟。
    label, cmd = spec[0], spec[1]
    extra = spec[2] if len(spec) > 2 else {}
    # 强制子进程用 UTF-8 打印，并且解码不许因为一个怪字节而整条门崩掉：
    # 母进程按 utf-8 读管道，可 Windows 上的 Python 子进程在输出被接进管道时按本地
    # 代码页（这台机器是 cp936）写。从没有 PYTHONIOENCODING 的终端起这套门，
    # 读线程会抛 UnicodeDecodeError——而它长得像「门跑过了」，实际那道门的输出
    # 一句都没读到，红成什么样没人知道。errors="replace" 是第二道保险：
    # 判定看的行首标记是 ASCII，替换字符不会把它藏起来。
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **extra)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(ROOT), env=env)
    return label, p.returncode, (p.stdout or "") + (p.stderr or "")


LOCK = ROOT / "test" / ".gate.lock"
LOCK_TTL = 45 * 60      # 全套跑完约 6~12 分钟；45 分钟还没放锁就是崩在半路了


def acquire_lock():
    """它改的是真源码，两个并发必然互相踩：踩过一次，一条本该炸的注入被另一边的
    还原写回抹平，报了「没人守」的假警报。所以宁可拒绝启动。"""
    if LOCK.exists():
        try:
            info = json.loads(LOCK.read_text(encoding="utf-8"))
        except Exception:
            info = {}
        age = time.time() - (info.get("at") or 0)
        if 0 <= age < LOCK_TTL:
            print(f"已经有一个守门自检在跑（pid {info.get('pid')}，{int(age)} 秒前开始）。"
                  f"并发跑只会互相踩出假结果——等它跑完；确认没有在跑就删掉 test/{LOCK.name}。")
            return False
    LOCK.write_text(json.dumps({"pid": os.getpid(), "at": time.time()}), encoding="utf-8")
    return True


def preflight():
    """只干两件事：每条注入的每一段锚点 (1) 还在源码里找得到、(2) **只找得到一处**。

    为什么要单独成一个命令、还要进快速门禁：锚点是手写的字符串，源码一改它就飘；
    而飘了的后果不是「报错」，是**那条守门从此根本没被跑到**（跑到了也只是印一行 SKIP）。
    这套要 60 多分钟才走完，等到那时才发现「今天新加的那条锚点没对上」太晚了——
    这一步实测只花一秒，所以它可以每次都跑。

    为什么要查「唯一」：`sub_once` 换的是**第一处**（`text.replace(a, b, 1)`）。
    锚点在源码里出现两处以上时，它换的可能是另一处，注入于是炸在别的地方或者干脆不炸，
    而 preflight 只看「找得到」会一路报绿。实测已经踩到两处：
    `styles.css` 同一句焦点描边写了 2 次、`yan.js` 的 `'    </div>';` 出现 4 次。
    这类锚点的修法是把它写长一点（带上前后的上下文），让它在全仓只剩一处——
    不是在 preflight 里加豁免。"""
    bad = []
    dup = []
    for entry in MUTATIONS:
        name, edits, _ = parts(entry)
        for f, old, _ in edits:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                bad.append((name, f.name, "文件不在"))
                continue
            if not sub_once(text, old, "")[1]:
                bad.append((name, f.name, old[:46]))
                continue
            # 数它出现几次（CRLF 也数一遍，与 sub_once 的口径对齐）
            n = text.count(old)
            if n <= 1 and "\n" in old:
                n = max(n, text.count(old.replace("\n", "\r\n")))
            if n > 1:
                dup.append((name, f.name, n, old[:46]))
    for name, fn, frag in bad:
        print(f" FAIL  锚点失效      {name} —— {fn} 里找不到 {frag!r}")
    for name, fn, n, frag in dup:
        print(f" FAIL  锚点不唯一    {name} —— {fn} 里 {frag!r} 出现 {n} 处"
              f"（sub_once 换第一处，注入可能炸错地方；把锚点写长到只剩一处）")
    if bad or dup:
        print(f"锚点自检：{len(MUTATIONS)} 条注入里 {len(bad)} 段失效、{len(dup)} 段不唯一"
              f" → 改源码时把锚点一起带上")
        return 1
    print(f"  ok   锚点自检      {len(MUTATIONS)} 条注入的每一段都在源码里、且只出现一处")
    return 0


def main():
    if "--preflight" in sys.argv[1:]:
        return preflight()
    if not acquire_lock():
        return 1
    try:
        return run_all_mutations()
    finally:
        LOCK.unlink(missing_ok=True)


def parts(entry):
    """把一条注入拆成 (名字, [(文件, 原文, 替换文)…], 该管的守门)。
    第 6 个字段（可选）是同一轮里要**一起**改的其他地方：有些缺陷单独改哪一处都不成立。"""
    name, target, old, new, gates = entry[:5]
    extra = list(entry[5]) if len(entry) > 5 else []
    # 第 5 个字段是守门（二元组 (名字, 命令)），第 6 个是复合改动（三元组 (文件, 原文, 替换文)）。
    # 写反了不会有任何提示，只会在这套东西跑到一半时抛一句「not enough values to unpack」——
    # 第 38 轮就这么撞过一次，所以这里当场说清是哪条、哪一段。
    # 第 5 个字段是守门：(名字, 命令) 或 (名字, 命令, 额外环境变量)——第三项只给
    # 「同一道门跑一个窄场景」用（见 DEADCTLN），必须是个 dict，否则照样当场说清。
    for g in gates:
        if not (isinstance(g, tuple) and 2 <= len(g) <= 3 and isinstance(g[0], str)
                and isinstance(g[1], list) and (len(g) == 2 or isinstance(g[2], dict))):
            raise SystemExit(f"注入「{name}」的第 5 个字段不是一组 (名字, 命令[, 环境变量])：{g!r}")
    for e in extra:
        if not (isinstance(e, tuple) and len(e) == 3):
            raise SystemExit(f"注入「{name}」的第 6 个字段不是一组 (文件, 原文, 替换文)：{e!r}"
                             "（第 5 个字段是守门，别把两者写反）")
    return name, [(target, old, new)] + extra, gates


def sub_once(text, old, new):
    """换一处，返回 (新文本, 有没有换到)。
    锚点是手写的 `\\n`，可文件未必是 LF：`backend/gateway.py` 整份是 CRLF，
    于是那两条带换行的锚点（500 外壳、日期钳位）一直匹配不上 → 年年 SKIP、
    年年被算成「异常」，而异常长什么样没人细看，这两条守门其实停摆了一整轮。
    所以这里两种换行都试一次，让锚点跟文件走。"""
    for a, b in ((old, new), (old.replace("\n", "\r\n"), new.replace("\n", "\r\n"))):
        if a in text:
            return text.replace(a, b, 1), True
    return text, False


def selected_mutations():
    """`python test/gate_selfcheck.py --only 关键词` 只跑名字里带它的几条：
    新加一条靶子时不必先等整套半小时。默认全跑，`npm run check` 走的就是默认全跑，
    子集只是省等待，不会把没跑的那几条算成通过。"""
    kws = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not kws:
        return MUTATIONS
    picked = [e for e in MUTATIONS if any(k in parts(e)[0] for k in kws)]
    if not picked:
        print(f"没有一条注入的名字里含 {'/'.join(kws)}（现有 {len(MUTATIONS)} 条）")
        raise SystemExit(2)
    print(f"只跑 {len(picked)}/{len(MUTATIONS)} 条：" + "、".join(parts(e)[0] for e in picked) + "\n")
    return picked


def run_all_mutations():
    picked = selected_mutations()
    # 开跑前把要动的文件全部拍一份：最后如果哪道门还红，得先回答「文件到底还原了没有」，
    # 才能把「没还原干净」和「浏览器套件被机器压得偶发一次红」分开说
    snapshot = {p: p.read_bytes() for p in {f for e in picked for f, _, _ in parts(e)[1]}}
    # 规格从注入条目本身取，不再抄一份写死的名单：加了一道新门、忘了往下面那个
    # 元组里补一个名字，`--only` 就会 KeyError——那正是「清单与来源分家」这一类，
    # 而这一轮整轮都在修这类东西。
    specs = dict(needed_specs(picked))
    needed = sorted(specs)
    base = {label: run_gate(specs[label]) for label in needed}
    dead = [label for label, (_, code, _) in base.items() if code != 0]
    if dead:
        print(f"基线就没过：{dead}，先修好再来自检。")
        for label in dead:
            print("----", label, "----")
            print("\n".join(base[label][2].splitlines()[-25:]))
        return 1
    print(f"基线：{len(needed)} 道守门全绿（{('、'.join(needed))}）\n")

    bad = 0
    for entry in picked:
        name, edits, gates = parts(entry)
        files = [f for f, _, _ in edits]
        backups = {f: f.read_bytes() for f in files}
        missing = [f for f, old, _ in edits
                   if not sub_once(backups[f].decode("utf-8"), old, "")[1]]
        if missing:
            print(f" SKIP  {name}（锚点没找到：{'、'.join(f.name for f in missing)}，脚本该跟着更新了）")
            bad += 1
            continue
        try:
            # 同一个文件可能被改两处：在那份文本上一次一次叠，别各自从原文覆盖。
            # newline="" 是必须的：Windows 上 write_text 默认会把 \n 翻成 \r\n，
            # 那会把 CRLF 文件写成 \r\r\n——测试照跑，但改的已经不是那份文件了。
            for f in backups:
                text = backups[f].decode("utf-8")
                for ff, old, new in edits:
                    if ff == f:
                        text, _ = sub_once(text, old, new)
                with open(f, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            results = [run_gate(g) for g in gates]
            caught = [(label,) + fail_reason(out) for label, code, out in results if code != 0]
            if caught:
                label, asserted, first = caught[0]
                # 崩在半路也算抓到（基线是绿的，红只能是注入引起的），但要说清它是哪一种红：
                # 某条断言变红，还是套件整个死了。后者读起来像好消息，其实看不出炸在哪。
                tag = "断言炸了" if asserted else "崩在无断言处"
                print(f"  ok   {name} → {label} {tag}：{first[:320]}")
            else:
                # 现场留证。踩过一次「某条注入在整套里报没人守，单跑三次都必炸」，
                # 而日志里说不出当时文件到底改了没有——那就没法查下去。
                now = {f.name: ("变了" if f.read_bytes() != backups[f] else "没变！") for f in files}
                print(f" FAIL  {name} → 改了源码，{'、'.join(l for l, _, _ in results)} 全都过了！"
                      f"这一类漂移仍然没人守（落盘：{'，'.join(f'{k} {v}' for k, v in now.items())}）")
                bad += 1
        finally:
            for f, blob in backups.items():
                f.write_bytes(blob)
                if f.read_bytes() != blob:
                    print(f"  !!  {f.name} 没能还原，立刻检查！")
                    bad += 1

    # 还原后必须回到全绿。
    # 踩过：整套跑到最后 offline 报「还原后仍红」，看起来像写回把源码弄坏了，
    # 而 offline / e2e 单独重跑都是全绿——机器满载时浏览器套件会偶发一次红。
    # 所以先用字节比对确定还原到底干净不干净，再把红的门重跑一次分诊。
    dirty = sorted(p.name for p, blob in snapshot.items() if p.read_bytes() != blob)
    if dirty:
        print(f"\n !!  文件没还原干净：{'、'.join(dirty)} —— 先查这个，其它结论都不可信")
        bad += 1
    still = []
    for label, spec in needed_specs(picked):
        if run_gate(spec)[1] != 0:
            print(f"   （{label} 复跑第一次红，再跑一次分诊：还原问题还是机器太忙）")
            if run_gate(spec)[1] != 0:
                still.append(label)
    if still:
        print(f"\n还原后仍红：{still}"
              + ("（文件逐字节一致 → 更像机器太忙，重跑这一套看看）" if not dirty else "（且文件没还原干净）"))
        bad += 1
    else:
        print("\n还原后复跑：全绿")
    print(f"自检：{len(picked) - bad}/{len(MUTATIONS)} 项按预期拦截 / {bad} 项异常")
    return 1 if bad else 0


def needed_specs(mutations):
    seen = {}
    for entry in mutations:
        for g in parts(entry)[2]:
            seen[g[0]] = g
    return seen.items()


if __name__ == "__main__":
    raise SystemExit(main())
