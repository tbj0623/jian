# 商店页上每一句可核实的话，都得有人对着代码查一遍。
#
# 为什么单独一道门：商店文案是给审查员和用户看的**承诺**，而代码改了不会通知它。
# Play 的政策是「应用描述与实际行为不符」可以直接下架，所以这一类错不是难看，是致命。
# 第 50 轮差点就带着一句假话出包：文档写着「导入时少了几条它会说」，而那一句
# 恰好被本轮新加的「已导入」顶掉了——全靠一条**别的节**的旧断言报的案。
# 那道门（backup_claim.py）只管「自动备份」一句；这一道管其余全部可核实的句子。
#
# 规矩：每条都要 (a) 从文档里**读出那句话本身**（文档没写 = 红，不许对着空文件自证），
#       (b) 拿它去对代码/清单/测试里的实物。两边任意一边单独改都会红。
#
# 运行：PYTHONIOENCODING=utf-8 python test/store_claims.py
import ast
import html as htmllib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "上架" / "商店材料.md"
MAN = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
MERGED = (ROOT / "android" / "app" / "build" / "intermediates" / "merged_manifests" /
          "release" / "processReleaseManifest" / "AndroidManifest.xml")
GRADLE = ROOT / "android" / "app" / "build.gradle"
API = ROOT / "api.js"
ENGINE = ROOT / "engine.js"
INDEX = ROOT / "index.html"
STYLES = ROOT / "styles.css"
E2E = ROOT / "test" / "e2e.playwright.py"
OFFLINE = ROOT / "test" / "offline.playwright.py"
SHORTCUTS = ROOT / "android" / "app" / "src" / "main" / "res" / "xml" / "shortcuts.xml"

checks = []
SOURCE_ONLY = "--source-only" in sys.argv
PACKAGE_CHECK_PREFIXES = ("合并后的清单在", "文档列出的权限与合并后的清单", "release APK", "APK 里 targetSdk")


def check(name, ok, got=""):
    # 新克隆的公开源码尚无 Android 构建产物：只跳过依赖 APK / merged manifest 的三项。
    # 原生构建完成后，默认完整检查仍然严格执行，绝不以源码版本号替代真实产物。
    if SOURCE_ONLY and name.startswith(PACKAGE_CHECK_PREFIXES):
        print(" SKIP " + name + "（需先构建 Android release 才能验产物）")
        return
    checks.append((ok, name, got))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f"  ->  {got}"))


doc = DOC.read_text(encoding="utf-8")

# ---------- 0. 这道门自己看得见文档吗 ----------
# 文本扫描类的门最容易「什么都没匹配上却全绿」。先量它读到了多少可核实的句子。
QUOTED = re.findall(r"^> (.*)$", doc, re.M)
check("文档读得到（引用块里有正文可查，不是对着空文件自证）", len(QUOTED) > 30, f"{len(QUOTED)} 行")


def row(label):
    """表格行 `| 项 | 值 |` 里的值。"""
    m = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|(.+?)\|", doc, re.M)
    return m.group(1).strip() if m else None


# ---------- 1. 身份那一格：版本、包名、名字长度 ----------
pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
cfg_js = (ROOT / "config.js").read_text(encoding="utf-8")
sw_js = (ROOT / "sw.js").read_text(encoding="utf-8")
gradle = GRADLE.read_text(encoding="utf-8")
# 锚在**那一行**上，不是「文档里随便哪一处 `x.y.z` / `versionCode N`」：
# 第 19 行的操作说明里也写着 `versionCode`，用宽正则的话「把当前版本那一行改坏」这种缺陷
# 会被别处的正确写法救活（今天实测到：注入改坏了行首，检查照过）。
ver_doc = re.search(r"\|\s*当前版本\s*\|\s*`(\d+\.\d+\.\d+)`\s*/\s*`versionCode (\d+)`\s*\|", doc)
vn_g = re.search(r'versionName "([^"]+)"', gradle)
vc_g = re.search(r"versionCode (\d+)", gradle)
v_cfg = re.search(r'version: "([^"]+)"', cfg_js)
v_sw = re.search(r'const VERSION = "([^"]+)"', sw_js)
check("文档写的版本号就是四个源文件里那个版本号（第五处没人读，正是它最容易过期）",
      bool(ver_doc) and ver_doc.group(1) == pkg["version"] == v_cfg.group(1) == v_sw.group(1) == vn_g.group(1),
      f"文档 {ver_doc and ver_doc.group(1)} / package {pkg['version']} / config {v_cfg.group(1)}"
      f" / sw {v_sw.group(1)} / gradle {vn_g.group(1)}")
check("文档写的 versionCode 与 build.gradle 一致",
      bool(ver_doc) and ver_doc.group(2) == vc_g.group(1),
      f"文档 {ver_doc and ver_doc.group(2)} / gradle {vc_g.group(1)}")

app_id = re.search(r'applicationId "([^"]+)"', gradle)
doc_pkg = re.search(r"^\|\s*包名\s*\|\s*`([^`]+)`", doc, re.M)
check("文档写的包名就是 gradle 里那个 applicationId",
      bool(doc_pkg) and bool(app_id) and doc_pkg.group(1) == app_id.group(1),
      f"文档 {doc_pkg and doc_pkg.group(1)} / gradle {app_id and app_id.group(1)}")

name_doc = re.search(r"^\|\s*应用名[^|]*\|\s*`([^`]+)`", doc, re.M)
title_doc = re.search(r"^\|\s*完整标题[^|]*\|\s*`([^`]+)`", doc, re.M)
check("应用名与完整标题都在 Play 的 30 字符上限内（超限是提交时才被拒，那时已经晚了）",
      bool(name_doc) and bool(title_doc) and len(name_doc.group(1)) <= 30 and len(title_doc.group(1)) <= 30,
      f"{name_doc and len(name_doc.group(1))} / {title_doc and len(title_doc.group(1))}")


# ---------- 2. 那两条「实测 N」：文案长度 ----------
def blockquote_after(header_pat):
    """紧跟在某个加粗标题后面的那段引用块，按粘进 Play 输入框的样子拼回来。"""
    h = re.search(r"^\*\*" + header_pat + r"\*\*", doc, re.M)
    if not h:
        return None, None
    stated = re.search(r"实测\s*(\d+)", doc[h.start():h.end()])
    lines, started = [], False
    for line in doc[h.end():].split("\n"):
        # 空的那一行引用在 markdown 里是光一根 `>`（后面没有空格），它粘进 Play 输入框
        # 就是一个换行。以前只认 `> ` 开头，于是整段在第一个空行处被截断——
        # 门当场把 1068 字的完整说明数成了 30 字。
        if line.startswith("> "):
            lines.append(line[2:])
            started = True
        elif line.strip() == ">":
            if started:
                lines.append("")
        elif started and not line.strip():
            break
        elif started:
            break
    return (int(stated.group(1)) if stated else None), "\n".join(lines)


for label, pat, cap in (("简短说明", r"简短说明（(\d+) 字符内", 80),
                        ("完整说明", r"完整说明（(\d+) 字符内", 4000)):
    m = re.search(r"\*\*" + re.escape(label) + r"（(\d+) 字符内，实测 (\d+)", doc)
    stated, text = blockquote_after(re.escape(label) + r"（\d+ 字符内，实测 \d+）")
    limit = int(m.group(1)) if m else None
    check(f"{label}那一段真的存在（门不许对着找不到的段落报绿）", bool(text), "找不到引用块")
    check(f"{label}在 Play 的 {limit} 字符上限内", bool(text) and len(text) <= limit,
          f"实测 {len(text or '')}")
    # 「实测 40」这种数字是文档在代替人数字。人数过一次就冻结了，而文案会改——
    # 第 36 轮就撞上过：写着 979，真实是 1068，中间改了好几轮没人回来对。
    check(f"{label}里那句「实测 {stated}」就是现在的真实字符数（改文案要顺手改这个数）",
          stated == len(text or ""), f"文档写 {stated}，真实 {len(text or '')}")


# ---------- 3. 权限：文档说什么，清单就得是什么 ----------
def perms_of(text):
    """数**全部** <uses-permission>，不比 `android.permission.*` 那种前缀。
    以前两侧都只认那个前缀，于是合并清单里第三条（AndroidX 自己加的
    `com.jian.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`）结构性隐形：
    下一个 SDK 再带一条 scoping 权限进来，这条门照样全绿。
    比较用末段名字（文档里就是这么写的）。
    只数 `<uses-permission android:name=…>`：合并清单里还有别的 `android.permission.X`，
    比如 AndroidX 内部广播接收器上的 `android:permission="…DUMP"`，那是「谁能来调我」
    不是「我要什么权限」——按子串抓会报出一条根本不存在的申请。"""
    return sorted({m.rsplit(".", 1)[-1]
                   for m in re.findall(r'<uses-permission[^>]*?\bandroid:name="([\w.]+)"', text)})


src_perms = perms_of(MAN.read_text(encoding="utf-8"))
if MERGED.exists():
    merged_perms = perms_of(MERGED.read_text(encoding="utf-8"))
    # 合并进来的那些（AndroidX 的私有权限）文档也逐条点了名，所以两边集合必须严格相等
    # 文档里那条 AndroidX 自加的权限写作末段（没有 `android.permission.` 前缀），
    # 所以两侧都取末段来比：只按前缀抓，第三条就永远不进比较（第 60 轮复核点的）。
    doc_perms = sorted(set(re.findall(r"`android\.permission\.([A-Z_]+)`", doc))
                       | set(re.findall(r"`([A-Z][A-Z_]*_PERMISSION)`", doc)))
    check("文档列出的权限与合并后的清单**逐条相等**（多一条没写、少一条写了都是红）",
          doc_perms == merged_perms, f"文档 {doc_perms} / 清单 {merged_perms}")
else:
    check("合并后的清单在（先跑一次 gradle 再跑这道门，不然这一项是瞎的）", False, str(MERGED))

DANGEROUS = ["CAMERA", "RECORD_AUDIO", "READ_CONTACTS", "ACCESS_FINE_LOCATION",
             "ACCESS_COARSE_LOCATION", "READ_EXTERNAL_STORAGE", "READ_MEDIA_IMAGES",
             "READ_MEDIA_VIDEO", "READ_MEDIA_AUDIO", "POST_NOTIFICATIONS"]
check("清单里没有任何危险权限（文档承诺「不申请任何需要用户授权的权限」）",
      not [p for p in src_perms if p in DANGEROUS],
      [p for p in src_perms if p in DANGEROUS])
CN_NAMES = ["相机", "麦克风", "通讯录", "位置", "存储"]
check("文档那句「不申请相机、麦克风、通讯录、位置、存储等任何需要用户授权的权限」"
      "确实写在政策正文里（门不许对着一句它没读到的承诺报绿）",
      all(n in doc for n in CN_NAMES) and "不申请" in doc,
      [n for n in CN_NAMES if n not in doc])
man_text = MAN.read_text(encoding="utf-8")
check("文档说「锁竖屏 + resizeableActivity=false」，清单就得真是这样",
      'android:screenOrientation="portrait"' in man_text
      and 'android:resizeableActivity="false"' in man_text
      and "锁竖屏" in doc and 'resizeableActivity="false"' in doc)


# ---------- 4. 照片缩小那两个像素数 ----------
w_see = re.search(r"function shrink\(file, w\)[\s\S]{0,600}?\(w \|\| (\d+)\)", API.read_text(encoding="utf-8"))
w_ocr = re.search(r"shrink\(file, (\d+)\)", API.read_text(encoding="utf-8"))
doc_px = sorted(set(int(x) for x in re.findall(r"(\d+) 像素", doc)))
check("文档说「认衣服 ≤512、抄截图 ≤768」，api.js 里就是这两个数",
      bool(w_see) and bool(w_ocr) and int(w_see.group(1)) == 512 and int(w_ocr.group(1)) == 768,
      f"代码 {w_see and w_see.group(1)} / {w_ocr and w_ocr.group(1)}")
check("文档里出现过的像素数只有那两个（多出一个说明代码或文档又动过一边）",
      doc_px == [512, 768], doc_px)


# ---------- 5. 举了具体例子的功能句 ----------
eng = ENGINE.read_text(encoding="utf-8")
dish = re.search(r'\{\s*n: "小笼包",\s*tags: \[([^\]]*)\]', eng)
check("文档举例「小笼包是猪肉馅」——菜库里那条真的挂着猪肉",
      bool(dish) and "猪肉" in dish.group(1), dish and dish.group(0))
# 这句是**举了具体菜名的承诺**，光在 engine.js 里扫字面扫不出来（辣子鸡不在菜库里，
# 它靠的是名字里那个「辣」字被忌口词撞上）。所以这道门改去查「有没有人真的把这句话跑过」：
# 用例在 test/engine.test.mjs 里，两边谁删谁红。
etest = (ROOT / "test" / "engine.test.mjs").read_text(encoding="utf-8")
check("文档举例「有人不吃辣不会变成一道菜，而会让那盘辣子鸡进有人不能吃」："
      "这句话在引擎用例里真的跑过",
      "辣子鸡" in etest and re.search(r"chili\.boom", etest) is not None,
      "engine.test.mjs 里找不到那个用例")
check("文档说「久未穿的会提醒你——换季收起来的夏装不在此列」：那条提醒真的先看季节",
      re.search(r"const stale = !seasonal", eng) is not None and "换季" in doc)


# ---------- 6. 「没有任何第三方请求 / SDK」 ----------
deps = list(pkg.get("dependencies", {})) + list(pkg.get("devDependencies", {}))
# 用**白名单**而不是关键字黑名单：黑名单只认得写进来的那几个词，
# 装一个没抄进去的（posthog / umeng / tongji / appsflyer…）这条门就静默全绿。
# 这个应用一共十个依赖，全是 @capacitor/* 官方包，所以白名单闭得起来。
ALLOWED = re.compile(r"^@capacitor/[a-z-]+$")
stray = [d for d in deps if not ALLOWED.match(d)]
check("package.json 的依赖**全在** Capacitor 白名单里（文档写着「不集成任何统计或崩溃上报 SDK」）",
      not stray and len(deps) >= 8, f"名单外 {stray}，共 {len(deps)} 个依赖")
ext = re.findall(r'(?:src|href)="(https?://[^"]+)"', INDEX.read_text(encoding="utf-8"))
check("index.html 不引用任何外部地址（连字体都不外链，文档那句「不上传任何东西」才立得住）",
      not ext, ext)
front_fetch = re.findall(r"fetch\(\s*([^,\n)]+)", "".join(
    (ROOT / f).read_text(encoding="utf-8") for f in ("api.js", "app.js", "yi.js", "wei.js", "yan.js", "me.js", "ui.js", "card.js")))
hardcoded = [x for x in front_fetch if re.search(r"https?://", x)]
check("前端所有 fetch 的目标都由用户填的地址拼出来，没有一处硬编码主机",
      not hardcoded, hardcoded)
check("文档说「宽窗（≥900px）另有一套桌面版式，实测过」：那套版式真的在",
      "@media (min-width: 900px)" in STYLES.read_text(encoding="utf-8"))
off = OFFLINE.read_text(encoding="utf-8") if OFFLINE.exists() else ""
n_off = len(re.findall(r"^\s*check\(", off, re.M))
check("文档说「离线可用是测过的」：那道离线门真的在跑断言，不是一句空话",
      OFFLINE.exists() and n_off >= 8, f"{n_off} 条")
sc = SHORTCUTS.read_text(encoding="utf-8") if SHORTCUTS.exists() else ""
# 0.6.0：快捷方式从三枚扩到五枚（三张笺之外加了「今日」与「记一笔」）。
# 为什么这条要从「数 == 3」改成「逐枚点名」：数量相等挡不住「三枚都指向同一屏」
# 或者「新加的那枚指向一个不存在的屏」——那两种坏法数量都还是五。
# 所以这里改成对着 id → 目标地址一条条比，外加五个标签真的都在 strings.xml 里。
# 这一条与 scripts/test.mjs 的 checkShortcuts（三头对账：shortcuts.xml / 清单 / screenOf）
# 分工不同：那边查「指得对不对」，这边查「商店文案承诺的那五件事是不是真的都在」。
SC = {"yi": "jian://screen/yi", "wei": "jian://screen/wei", "yan": "jian://screen/yan",
      "today": "jian://screen/today", "note": "jian://screen/yan?new=1"}
sc_ids = dict(re.findall(
    r'<shortcut\b[^>]*?android:shortcutId="([\w-]+)"[\s\S]*?android:data="([^"]+)"', sc))
check("文档说长按图标能直接进那五处（三张笺 + 今日 + 记一笔）：五枚就指着那五个地址，逐枚对",
      sc_ids == SC, f"{sc_ids}")
strings = (ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
labels = {"yi": "过一件衣", "wei": "排一桌菜", "yan": "捞一段话", "today": "看今天", "note": "记一笔"}
check("五枚快捷方式的短标签都取得到中文，而且就是商店文案里引的那五个说法",
      all(f'<string name="shortcut_{k}_short">{v}</string>' in strings for k, v in labels.items())
      and all(v in doc for v in labels.values()),
      [v for v in labels.values() if v not in doc])
check("文档那句「长按桌面图标」把那五件事都写出来了（少写一件 = 描述与实际不符）",
      bool(re.search(r"长按桌面图标可以直接进「([^」]+)」", doc))
      and all(v in re.search(r"长按桌面图标可以直接进「([^」]+)」", doc).group(1) for v in labels.values()),
      re.search(r"长按桌面图标可以直接进「([^」]+)」", doc))
e2e = E2E.read_text(encoding="utf-8")
sec29 = re.search(r'--- 29\..*?(?=\n\s*print\("\\n--- 30\.)', e2e, re.S)
check("文档指着「e2e 第 29 节量网关真收到的那张图」：那一节在，而且真的在量收到的图",
      bool(sec29) and "image" in sec29.group(0) and re.search(r"512|768", sec29.group(0)) is not None,
      "找不到那一节")
check("文档说「数据可否删除 = 是（清空本地数据一键）」：那一键真的在界面上",
      'id="reset"' in INDEX.read_text(encoding="utf-8") and "清空本地数据" in doc)
st = (ROOT / "state.js").read_text(encoding="utf-8")
check("文档说「三张笺共用一个笺点钱包」：账本里只有一个 points 字段，不是一笺一份",
      "points" in st
      and not re.search(r"\b(yi|wei|yan)Points|pointsPer", st) and "笺点" in doc,
      "找得到按笺分开的点数字段")


# ---------- 7. 文档自己有没有过期 ----------
# 第 6 节写着「截图内容固定为（0.5.6 这一批…）」——那是给审查员说「这五张图长这样」的，
# 版本号一过期就等于在描述另一个版本的界面。商店图每轮重拍，这一句就得每轮跟着改。
shot_ver = re.search(r"截图内容固定为（(\d+\.\d+\.\d+) 这一批", doc)
check("第 6 节说的那批商店截图就是当前版本（图每轮重拍，这句也得跟着改）",
      bool(shot_ver) and shot_ver.group(1) == pkg["version"],
      f"文档写 {shot_ver and shot_ver.group(1)}，当前 {pkg['version']}")
# 【待你确认】是给人看的 TODO。第 60 轮把最后两处（公开邮箱、隐私政策 URL）清掉了，
# 所以这一条从「还留着几处」改成「一处都不许再留」——它以前是 >=2，写成区间就等于
# 允许谁把它填了一半就报绿。留痕：占位符一旦回来（比如新加了一格没定的），这条会红，
# 那时该做的是**把它定下来**，而不是把这条改松。
todo = [w for w in ("【待你确认】", "【待你确认的邮箱】", "【发布当日】") if w in doc]
check("文档里一处【待你确认】都不许剩（第 60 轮之后这两样都有答案了）",
      not todo, todo)

# ── 7. 商店素材：烤进图里的字也是承诺 ─────────────────────────────
# 图片上的话以前没有任何一道门看过。store/feature-graphic 那一行写的是
# 「零账号 · 零联网 · 零广告 · 离线可用」，而「零联网」这个词第十七轮之后就禁写了
# （应用能连用户自己填的那台网关，照片确实会发出去），文档第 2 节还专门写了换成哪句。
# 文档改了、生成脚本没改——像素里那句假话不会自己过期（第 57 轮由上架审计抓出来）。
ART = ROOT / "scripts" / "make-store-assets.py"
art_src = ART.read_text(encoding="utf-8")
# d.text 的签名是 (xy, text, font=…, fill=…)：字在第 2 个位置上。
# 第一版按 args[2] 取，读出 0 条——「图上没有假话」那一条就变成对着空表自证，
# 是下面那条「读不出字来就是量空气」的地板把它报出来的。
texts = [n.args[1].value for n in ast.walk(ast.parse(art_src))
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "text" and len(n.args) >= 2
         and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)]
check("从生成脚本里真的读出「画到图上的字」（读不出来 = 这一节在量空气）", len(texts) >= 4, f"{len(texts)} 条")
BAN = ["零联网", "永不联网", "绝不上网"]
banned = [(w, t) for t in texts for w in BAN if w in t]
check("图上没有一句用到被推翻的说法（" + "、".join(BAN) + "）", not banned, banned)
check("特性图那行仍然只说三件真话：零账号 / 零广告 / 不联网也能用",
      any("零账号" in t and "零广告" in t and "不联网也能用" in t for t in texts), texts)
# 两头对：文档第 6 节把那行字**引**出来了，就得和脚本画的严格同一句。
# 只有单向检查的话，改图不改文档（就是这次「零联网」活这么久的原因）照样绿。
drawn_claim = [t for t in texts if "零账号" in t]
doc_claim = re.findall(r"一行「([^」]+)」", doc)
check("文档 6.素材表 引的那行图上的字 == 脚本真画的那句（改图不改文档、或反过来，都会红）",
      len(drawn_claim) == 1 and doc_claim == drawn_claim, [doc_claim, drawn_claim])
# 内容对账，不用 mtime（mtime 一过 git clone 就没意义，而且「新」不等于「对」）：
# 把脚本跑进临时目录，再和仓库里那两张逐字节比。
with tempfile.TemporaryDirectory() as td:
    env = dict(os.environ, JIAN_STORE_OUT=td, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ART)], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, timeout=240)
    made = sorted(pathlib.Path(td).glob("*.png"))
    drift = [p.name for p in made
             if not (ROOT / "store" / p.name).exists()
             or (ROOT / "store" / p.name).read_bytes() != p.read_bytes()]
check("store/ 那两张就是当前脚本的产物（改了脚本忘了重跑图 = 这次那条假话的成因）",
      r.returncode == 0 and len(made) == 2 and not drift,
      f"rc={r.returncode} 产出 {len(made)} 张，对不上 {drift} {(r.stderr or '')[-140:]}")

# 「模块可以随时开关」这句在第九轮之后有了限度（至少留一笺，全关掉底栏只剩「我的」）。
# 应用会挡、也会说；文档要是还写「随时开关」不带限度，就是描述与实际行为不符——
# 所以两边都查：文档里有那句限度，应用里也真的有那道守卫（同「特性图那句两头对」一把手法）。
app_src = (ROOT / "app.js").read_text(encoding="utf-8")
check("文档写着「随时开关（至少留一笺）」，而 app.js 里确实有那道守卫与那句话",
      "至少留一笺" in doc and "至少留一笺" in app_src,
      f"文档 {'至少留一笺' in doc}，app.js {'至少留一笺' in app_src}")

# 包自己声明的版本才是 Play 看到的那一份：gradle 写了 21、产物里却是 20（忘了重跑 gradle）
# 这种事，前面那几条「文件对账」一条都看不见 —— 它们比的是 www 与 assets，不是清单。
# aapt2 找不到就直接红：一道会悄悄消失的门比没有门更危险。
sdk = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home() / "AppData" / "Local"))) / "Android" / "Sdk" / "build-tools"
tools = sorted(sdk.glob("*"), key=lambda d: d.name) if sdk.exists() else []
apk = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
badging = ""
for t in reversed(tools):
    aapt = t / "aapt2.exe"
    if not aapt.exists():
        continue
    r = subprocess.run([str(aapt), "dump", "badging", str(apk)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=180)
    badging = r.stdout or ""
    if "package:" in badging:
        break
m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
tgt = re.search(r"targetSdkVersion:'(\d+)'", badging)
app_id = re.search(r'applicationId\s+"([^"]+)"', gradle)
check("release APK 自己声明的包名/版本 == gradle 与 package.json 的那几处（Play 读的就是这份）",
      bool(m) and bool(vn_g) and bool(vc_g) and app_id
      and m.group(1) == app_id.group(1) and m.group(2) == vc_g.group(1) and m.group(3) == vn_g.group(1)
      and m.group(3) == pkg["version"],
      (m.groups() if m else "aapt2 没读到包名/版本（apk 在不在？build-tools 装没装？）",
       (vc_g.group(1) if vc_g else "?"), (vn_g.group(1) if vn_g else "?"), pkg["version"]))
check("APK 里 targetSdk 就是 36（商店那条按产物这份算，不按 gradle 那份算）",
      bool(tgt) and tgt.group(1) == "36", tgt.group(1) if tgt else "没读到")

# ---------- 8. 隐私政策：同一句话，三个副本 ----------
# 政策正文不是一个字符串，是三个：第 4 节那块正文（人拿去核对的地方）、
# docs/上架/privacy/index.html（真的挂在上网的那一页的源）、以及 GitHub 上**已发布**的那一份。
# 第 50 轮那种「文档改了、产物没改」在这里更容易犯，也更贵：商店页一旦引用了那个 URL，
# 网上留着的就是旧的那句假话，而它看起来比文档还新。
# 手法照特性图那一行：两头对。只单向查（「页面上有这句话」）的话，
# 改文档不改页面照样绿，而那正是会出事的方向。
# 第三个副本（已发布的那一份）不在这里查——它要联网，见 scripts/publish-privacy.py --check。
PRIV = ROOT / "docs" / "上架" / "privacy" / "index.html"
priv_raw = PRIV.read_text(encoding="utf-8") if PRIV.exists() else ""


def priv_blocks(text):
    """按文档顺序取那一页的块级文字。注释与 <style> 先剥掉：注释里写着「没有 <script>」，
    不剥就会自己抓自己——发布脚本的第一跑真的这么红过一次。"""
    t = re.sub(r"<!--[\s\S]*?-->", "", text)
    t = re.sub(r"<style[\s\S]*?</style>", "", t)
    out = []
    for mu in re.finditer(r"<(h1|p|li|dt|dd)\b[^>]*>([\s\S]*?)</\1>", t):
        s = re.sub(r"<[^>]+>", "", mu.group(2))
        s = re.sub(r"\s+", " ", htmllib.unescape(s)).strip()
        if s:
            out.append((mu.group(1), s))
    return out


def doc_policy_lines():
    """第 4 节 ``` 那块正文 → 一条一句。折行是排版，不是另一句话：
    中文续行**不补空格**接回上一条（补了就与页面上的字对不上）。"""
    blk = re.search(r"^## 4\.[\s\S]*?^```[\s\S]*?\n([\s\S]*?)\n```$", doc, re.M)
    if not blk:
        return None
    items = []
    for line in blk.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith("· ") or re.match(r"^(笺 隐私政策|笺不收集|联系方式：|更新日期：)", line):
            items.append(line)
        elif items:
            items[-1] += line.strip()
    return [re.sub(r"\s+", " ", (x[2:] if x.startswith("· ") else x)
                   .replace("`", "")).strip() for x in items]


doc_pol = doc_policy_lines()
pb = priv_blocks(priv_raw)
page_pol, page_extra = [], []
# 读不出来的每一种形状都要落到**一条断言**上，不许落到异常上：
# 崩了也算「非零退出」，而那道门一旦把崩溃当战功，它就永远不知道自己其实没在量东西。
_first = lambda seq, tag: next((s for t, s in seq if t == tag), "（那一页里没有 <" + tag + ">）")
if pb:
    page_pol = [pb[0][1], _first(pb, "p")]                              # 标题 + 首句
    page_pol += [s for t, s in pb if t == "li"]                          # 九条条款
    page_pol += [a + "：" + b for a, b in zip([s for t, s in pb if t == "dt"],
                                              [s for t, s in pb if t == "dd"])]
    page_extra = [s for t, s in pb if t == "p"][1:]                      # 关于本页面那两句
else:
    page_pol = ["（那一页读不出任何块级文字）"]

check("文档指着的那个源路径，就是这个门在读的文件（门不许保护一个没人引用的文件）",
      "docs/上架/privacy/index.html" in doc and bool(priv_raw), str(PRIV))
# 两条地板：这一节比的是「列表相等」，两边任意一边解析成空表都会以「相等」报绿。
# 13 = 标题 1 + 首句 1 + 条款 9 + 落款 2。只写一次，两侧地板共用它（加条款改这一个数）。
POLICY_N = 13
check("那一页真的读得出 " + str(POLICY_N) + " 条正文（标题 + 首句 + 九条 + 落款两条）",
      len(page_pol) == POLICY_N, f"{len(page_pol)} 条：{page_pol[:1]}")
check("第 4 节那块正文真的读得出 " + str(POLICY_N) + " 条（读不出来 = 这一节在量空气）",
      bool(doc_pol) and len(doc_pol) == POLICY_N,
      len(doc_pol) if doc_pol else "第 4 节的 ``` 块没找到")
_fd = next(((i, a, b) for i, (a, b) in enumerate(zip(doc_pol or [], page_pol)) if a != b), None)
check("那一页的每一句 == 第 4 节的每一句，按顺序逐条比（只改一边就红）",
      bool(doc_pol) and doc_pol == page_pol,
      _fd and f"第 {_fd[0] + 1} 条 文档「{_fd[1]}」 vs 页面「{_fd[2]}」")

mail_row = re.search(r"`([^`@]+@[^`]+)`", row("联系方式") or "")
mail_pol = next((x for x in (doc_pol or []) if x.startswith("联系方式：")), "")
mail_page = next((x for x in page_pol if x.startswith("联系方式：")), "")
check("第 1 节的邮箱 == 政策正文里的 == 那一页上的落款（三处同一个，而且像个邮箱）",
      bool(mail_row) and mail_pol == mail_page == "联系方式：" + mail_row.group(1)
      and re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", mail_row.group(1)) is not None,
      f"第1节 {mail_row and mail_row.group(1)} / 正文 {mail_pol} / 页面 {mail_page}")
url_row = re.search(r"`(https://[^`]+)`", row("隐私政策 URL") or "")
canon = re.search(r'rel="canonical" href="([^"]+)"', priv_raw)
check("第 1 节填的那条 URL 是 https，而且就是那一页自己声明的 canonical（不是别处的第二份）",
      bool(url_row) and bool(canon) and url_row.group(1) == canon.group(1),
      f"文档 {url_row and url_row.group(1)} / canonical {canon and canon.group(1)}")
# 第 62 轮起这条地址有了**第四份副本**：应用自己要显示它（config.js 的 privacyUrl，
# 运行时唯一一份，me.js 读它）。商店页填的、页面上写的、应用里显示的，三处必须同一句话——
# 用户在应用里点开的不能是另一个站点。
app_pu = re.search(r'privacyUrl:\s*"([^"]+)"', cfg_js)
check("应用里那条隐私政策地址（config.js，运行时读的那一份）== 第 1 节填的 == 那一页的 canonical",
      bool(app_pu) and bool(url_row) and bool(canon)
      and app_pu.group(1) == url_row.group(1) == canon.group(1),
      f"应用 {app_pu and app_pu.group(1)} / 文档 {url_row and url_row.group(1)}"
      f" / canonical {canon and canon.group(1)}")
check("更新日期是一个真日期（不是一句「发布当日」的提醒）",
      any(re.match(r"更新日期：\d{4} 年 \d{1,2} 月 \d{1,2} 日$", x) for x in (doc_pol or [])),
      [x for x in (doc_pol or []) if x.startswith("更新日期")])
check("政策正文与那一页里没有任何【占位符】残留",
      bool(doc_pol) and not re.search(r"【[^】]*】", "".join(doc_pol) + "".join(page_pol)),
      re.findall(r"【[^】]*】", "".join(doc_pol or []) + "".join(page_pol)))
extra_doc = re.findall(r"^- 页面上还写着：「(.+)」$", doc, re.M)
check("文档引的那两句「页面上还写着」== 那一页真的多出来的那两句（双向）",
      len(page_extra) == 2 and extra_doc == page_extra, [extra_doc, page_extra])
# 这一条与发布脚本**共用同一份规矩**：从 scripts/publish-privacy.py import 进来，不另抄名单。
# 抄一份会怎样：第 60 轮复核就是照着两份名单找到的差别（`cdn.` 只在一边）。
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("jian_publish_privacy", ROOT / "scripts" / "publish-privacy.py")
PUB = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(PUB)
refs = PUB.external_refs(priv_raw) if priv_raw else ["（读不到那一页，等于这一条没在量东西）"]
check("那一页不引任何站外的东西（属性 / CSS url() / 脚本三类引用全看，不只认 <script>）",
      not refs, refs[:5])
# 地板：import 进来的这条规矩不许是个空壳。拿一页**故意**引了外部字体与外部图的样张喂它，
# 两枚都必须被点出来 —— 这比数名单长度强：名单再长，函数被写坏了照样一条都不抓。
CANON = PUB.canonical_url(priv_raw) or "https://tbj0623.github.io/jian-privacy/"
probe = ('<link rel="canonical" href="%s" />'
         '<link rel="stylesheet" href="https://fonts.example.com/a.css" />'
         '<img src="//cdn.example.com/b.png" />' % CANON)
caught = PUB.external_refs(probe)
check("那条规矩真的会抓（样张里两枚站外引用一枚都不许漏，同源那枚不许误报）",
      len(caught) == 2, caught)
# 邮箱在页面上有**两份**：给人看的那行字，和 `mailto:` 里那个真地址。
# 文档改了、可见文字改了、href 忘了改 —— 门前三样都对，用户点下去寄到旧地址。
mail_href = re.search(r'href="mailto:([^"]+)"', priv_raw)
check("那一页「看得见的邮箱」==「点下去寄去的地址」== 第 1 节那格 == 政策正文那句（四处一个样）",
      bool(mail_href) and bool(mail_row)
      and mail_href.group(1) == mail_row.group(1) == mail_page.split("：", 1)[-1],
      f"href {mail_href and mail_href.group(1)} / 页面文字 {mail_page} / 第1节 {mail_row and mail_row.group(1)}")
page_title = re.search(r"<title>([^<]*)</title>", priv_raw)
check("那一页的 <title> 就是页面上那行 h1（两个标题各写一份，早晚一份新一份旧）",
      bool(page_title) and page_title.group(1).strip() == (page_pol[0] if page_pol else None),
      f"<title> {page_title and page_title.group(1)} / h1 {page_pol[:1]}")

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
sys.exit(1 if bad else 0)
