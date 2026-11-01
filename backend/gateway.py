#!/usr/bin/env python3
# 笺 · 本地算力网关
# 与 engine.js 保持同一份规则：词表、排桌结构、时间抽取三处对齐。
# 需要时自己运行：python3 backend/gateway.py（默认 127.0.0.1:8787）
# 不要在聊天沙箱里后台常驻挂起。
from __future__ import annotations

import calendar
import json
import math
import os
import re
import socket
import sys
import time
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402  模型客户端：只有网关调模型，密钥不进应用包

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("JIAN_PORT", "8787"))
# 默认只听回环。这台机器上跑的是用户的衣柜照片和聊天记录，不该因为「起了个网关」
# 就对全网敞开；要让手机在同一张局域网里连上来，得自己说一声 JIAN_HOST=0.0.0.0。
HOST = os.environ.get("JIAN_HOST", "127.0.0.1")


def lan_ips():
    """绑 0.0.0.0 时说得出手机上该填什么。

    不提醒这一步，用户照着文档填 http://127.0.0.1:8787——而手机上的 127.0.0.1
    是手机自己，永远只会「回落本地」，界面上还得不到任何解释。
    这里不发包，只是问内核「出网走哪张网卡」，所以拿到的就是局域网那个地址。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return [s.getsockname()[0]]
        finally:
            s.close()
    except OSError:
        return []


def _round(v: float) -> int:
    """JS Math.round 的半进位口径。Python 内建 round() 是银行家舍入（round(2.5)==2），
    两端算同一个数会差 1——排桌道数、色差 gap 都栽在这儿。"""
    return math.floor(v + 0.5)


def clamp_date(year: int, month: int, day: int) -> datetime:
    """本地零点的 年/月/日；不存在的日子钳到当月最后一天。
    与 engine.js 的 clampDate 同口径（那边 month 是 0 基，这里是 1 基）。"""
    return datetime(year, month, min(day, calendar.monthrange(year, month)[1]))


# 菜名关键词 → 隐藏成分
# 键的顺序 = 命中后「雷区/谨慎」理由里成分的先后，所以必须与 engine.js 的 HIDDEN 逐行同序，
# 增删键要两端一起动（test/consistency.py 对全表 + 顺序）。
HIDDEN = {
    "宫保": ["花生"], "怪味": ["花生"], "花生": ["花生"], "腰果": ["花生"],
    "坚果": ["花生"], "核桃": ["花生"], "果仁": ["花生"],
    "水煮": ["辣"], "麻婆": ["辣"], "麻辣": ["辣"], "香锅": ["辣"], "火锅": ["辣"],
    "毛血旺": ["辣"], "口水": ["辣"], "担担": ["辣"], "辣子": ["辣"], "剁椒": ["辣"],
    "泡椒": ["辣"], "藤椒": ["辣"], "椒麻": ["辣"], "红油": ["辣"], "干锅": ["辣"],
    "香辣": ["辣"], "酸辣": ["辣"], "辣炒": ["辣"], "火爆": ["辣"], "冒菜": ["辣"],
    "串串": ["辣"], "麻辣烫": ["辣"], "口味虾": ["辣"], "夫妻肺片": ["辣"],
    "香菜": ["香菜"], "芫荽": ["香菜"], "折耳根": ["香菜"],
    "蒜蓉": ["蒜"], "蒜泥": ["蒜"], "蒜香": ["蒜"], "蒜苗": ["蒜"],
    "啤酒": ["酒"], "黄酒": ["酒"], "醉": ["酒"], "花雕": ["酒"], "酒酿": ["酒"],
    "虾": ["海鲜"], "蟹": ["海鲜"], "生蚝": ["海鲜"], "花甲": ["海鲜"], "蛤": ["海鲜"],
    "鱿鱼": ["海鲜"], "章鱼": ["海鲜"], "鲍": ["海鲜"], "扇贝": ["海鲜"], "海参": ["海鲜"],
    "龙虾": ["海鲜"], "皮皮虾": ["海鲜"], "生鱼": ["海鲜"], "三文鱼": ["海鲜"],
    "带子": ["海鲜"], "蛏": ["海鲜"], "海蜇": ["海鲜"],
    # 「海鲜」这两个字本身也要认：菜单写「海鲜汤」「捞汁海鲜」时一个虾蟹鱼字都没有，
    # 以前它落在 HIDDEN 与 CHIP_MAP 之外——忌海鲜的人看到的是「全员安全」。与 engine.js 同序。
    "海鲜": ["海鲜"],
    "酸菜鱼": ["鱼"], "水煮鱼": ["辣", "鱼"], "烤鱼": ["鱼"], "清蒸鱼": ["鱼"],
    "红烧鱼": ["鱼"], "鲫鱼": ["鱼"], "草鱼": ["鱼"], "鲤鱼": ["鱼"], "黄鱼": ["鱼"],
    "鲈鱼": ["鱼"], "黑鱼": ["鱼"], "鱼头": ["鱼"],
    "红烧肉": ["猪肉"], "回锅": ["猪肉"], "东坡": ["猪肉"], "扣肉": ["猪肉"],
    "排骨": ["猪肉"], "猪蹄": ["猪肉"], "叉烧": ["猪肉"], "腊肉": ["猪肉"], "香肠": ["猪肉"],
    "小炒肉": ["猪肉"], "木须": ["猪肉"], "锅包肉": ["猪肉"], "狮子头": ["猪肉"],
    "鱼香肉丝": ["猪肉"], "青椒肉丝": ["猪肉"], "梅干菜": ["猪肉"], "五花": ["猪肉"],
    "里脊": ["猪肉"], "培根": ["猪肉"], "火腿": ["猪肉"], "猪肝": ["内脏"], "肥肠": ["内脏"],
    "腰花": ["内脏"], "肚丝": ["内脏"], "鸡杂": ["内脏"], "鸭血": ["内脏"], "猪心": ["内脏"],
    "牛肉": ["牛羊肉"], "肥牛": ["牛羊肉"], "牛腩": ["牛羊肉"], "牛排": ["牛羊肉"],
    "黑椒牛": ["牛羊肉"], "羊肉": ["牛羊肉"], "羊排": ["牛羊肉"], "涮羊": ["牛羊肉"],
    "手抓羊": ["牛羊肉"], "烤羊": ["牛羊肉"],
    "奶茶": ["乳"], "布丁": ["乳"], "蛋糕": ["乳"], "奶油": ["乳"], "芝士": ["乳"],
    "奶酪": ["乳"], "奶盖": ["乳"], "黄油": ["乳"], "双皮奶": ["乳"], "拿铁": ["乳"],
}

# 忌口芯片 → 触发它的菜名关键词
CHIP_MAP = {
    "辣": ["辣", "麻", "水煮", "火锅", "香锅", "口水", "担担", "剁椒", "毛血", "泡椒", "藤椒", "干锅", "红油"],
    "香菜": ["香菜", "芫荽", "折耳根"],
    "海鲜": ["海鲜", "虾", "蟹", "蚝", "贝", "鱼", "鱿", "花甲", "蛤", "鲍", "蛏", "海参", "海蜇", "章鱼", "龙虾"],
    "花生": ["花生", "宫保", "坚果", "腰果", "核桃", "果仁"],
    "牛羊肉": ["牛", "羊"],
    "内脏": ["肝", "腰", "肚", "肠", "胗", "心", "肺", "血"],
    "蒜": ["蒜"],
    "酒": ["酒", "啤", "醉", "花雕"],
    "乳": ["奶", "芝士", "奶酪", "黄油", "乳"],
    "清淡": [],
    "猪肉": ["猪", "回锅", "东坡", "叉烧", "排骨", "扣肉", "腊肉", "五花", "里脊"],
    # 2026-10 补的四类。与 engine.js **逐字同序**：这张表的键序被 chipsInNotes 与
    # Python 的 dict 序同时依赖，插在中间会让两端漂。加一项就要两边同时加。
    # 这四类以前一个字都没有，判定退化成按菜名字面匹配，而菜名里不会写「小麦」——
    # 实测 63 道菜，小麦应判 9 道判出 0 道，大豆应判 3 道判出 0 道。
    "蛋": ["蛋"],
    "小麦": ["面", "饼", "饺", "包子", "小笼", "馒头", "馍", "烙", "馄饨", "云吞", "油条", "春卷", "面筋"],
    "大豆": ["豆腐", "豆干", "豆皮", "豆泡", "千张", "腐竹", "毛豆", "豆浆", "豆芽", "豆豉", "豆瓣"],
    "坚果": ["腰果", "核桃", "杏仁", "松仁", "榛", "开心果", "果仁", "巴旦木", "宫保"],
}

# 与 engine.js 同表同序：不含原料名的家常菜（地三鲜 / 小笼包 / 凤爪）要显式列进来，
# 否则 dish_kind 判成「其他」而菜库归在某一类，排桌的荤素计数会和推荐自相矛盾。
MEAT_RE = re.compile("肉|鸡|鸭|鹅|牛|羊|猪|鱼|虾|蟹|排骨|肘|蹄|肚|肠|肝|腰|贝|蚝|鱿|鳝|蛙|兔|鸽|培根|火腿|香肠|腊|丸|排|里脊|狮子头|凤爪")
VEG_RE = re.compile("菜|豆|茄|瓜|笋|菇|菌|藕|萝卜|土豆|菠菜|白菜|西兰花|四季豆|玉米|青椒|番茄|西红柿|木耳|海带|山药|莴笋|空心菜|油麦|生菜|韭菜|芹菜|洋葱|彩椒|蔬|地三鲜")
SOUP_RE = re.compile("汤|羹|煲|粥|砂锅")
STAPLE_RE = re.compile("饭|面|粉|饺|包子|馒头|饼|馍|米线|河粉|年糕|馄饨|云吞|团|盒|小笼|烙")


_HEX_BAD = re.compile("[^0-9a-f]", re.I)


def hex_rgb(h):
    """与 engine.js 的 hexToRgb 同口径：非法字符合、长度不对一律回落 (200,200,200)。
    早先这里只查长度不查字符，"#gggggg" 会把 int(x,16) 直接掀翻；空串又被 (h or "#cccccc")
    变成 204，两端算出的色差差 1~2，判定跟着翻。"""
    s = str(h or "").strip().replace("#", "", 1)
    if len(s) == 3:
        s = s[0] * 2 + s[1] * 2 + s[2] * 2
    if len(s) != 6 or _HEX_BAD.search(s):
        return (200, 200, 200)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    """与 engine.js 同一套：CIE Lab（D65）。判定必须两端同尺度。
    立方根用 math.cbrt 而不是 t ** (1/3)：后者走 exp/log，和 JS 的 Math.cbrt
    不是同一个近似。实测两者最大偏差 2.3e-13、翻不了任何判定阈值，但没理由留着。"""
    r, g, b = (srgb_to_linear(v) for v in rgb)
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) / 1.0
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883

    def f(t):
        return math.cbrt(t) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def rgb_to_hsl(rgb):
    r, g, b = (v / 255.0 for v in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    d = mx - mn
    h = s = 0.0
    if d > 1e-6:
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:
            h = ((g - b) / d + (6 if g < b else 0)) * 60
        elif mx == g:
            h = ((b - r) / d + 2) * 60
        else:
            h = ((r - g) / d + 4) * 60
    return h, s, l


def _q4(v: float) -> float:
    # 与 JS 的 Math.round(x*1e4)/1e4 同一条舍入：Python 的 round() 是银行家舍入，
    # 正好压在 .00005 上时两端会给出不同的调，而这句话是要印在笺上给人看的。
    return math.floor(v * 1e4 + 0.5) / 1e4


def tone_of(h: float, s: float, l: float) -> str:
    """冷 / 暖 / 中性。与 engine.js 的 toneOf 同一条口径（含四位小数量化）。"""
    h, s, l = _q4(h), _q4(s), _q4(l)
    if s < 0.12 or l > 0.93 or l < 0.08:
        return "中性"
    if 20 <= h < 55:
        return "暖"
    if 55 <= h < 95:
        return "暖"
    if h >= 300 or h < 20:
        return "暖"
    return "冷"


def tone_line(new_color: str, wardrobe: list) -> str:
    """冷暖调这一句：只在柜子里冷暖分明（≥5 件、多数过六成）的时候说一句事实，不改判定。
    与 engine.js 的 toneLine 一字不差——两端各说一句，笺上就会出现两种说法。"""
    if len(wardrobe) < 5:
        return ""
    cnt = {"冷": 0, "暖": 0, "中性": 0}
    for w in wardrobe:
        h, s, l = rgb_to_hsl(hex_rgb(w.get("color")))
        cnt[tone_of(h, s, l)] += 1
    major = "暖" if cnt["暖"] >= cnt["冷"] else "冷"
    n, m_n = len(wardrobe), cnt[major]
    if m_n / n < 0.6:
        return ""
    h, s, l = rgb_to_hsl(hex_rgb(new_color))
    nt = tone_of(h, s, l)
    if nt == "中性":
        return f"柜里 {m_n}/{n} 件是{major}调，这件是中性色，两边都接得住。"
    if nt == major:
        return f"这件和柜里多数衣服同调（{major}调 {m_n}/{n}）。"
    return f"柜里 {m_n}/{n} 件是{major}调，这件是{nt}调。"


def hue_gap(h1, h2) -> float:
    d = abs(h1 - h2) % 360
    return 360 - d if d > 180 else d


def _days_since(ts) -> int:
    # math.floor 而不是 int()：engine.js 用 Math.floor，lastWorn 是未来时间时两者要为负且相等
    return math.floor((time.time() * 1000 - (ts or 0)) / 86400000)


# 季节性衣物半年没穿是正常的，不能据此断定"你不需要"。
SEASONAL_RE = re.compile("大衣|羽绒|棉袄|棉服|毛衣|针织|围巾|披肩|靴|风衣|夹克|外套|雪地")


def is_seasonal(w) -> bool:
    """夏、冬两季的衣服一年只出两场，半年没穿不是「买错了」的证据。
    season_of 早就算得出这一层（柜子按季节筛靠它），判定以前只看品类与名字线索。
    「四季」是用户明说常年穿的，不替他找换季的台阶；「春秋」跨两季，仍按久未穿算。"""
    if not w:
        return False
    s = season_of(w)
    if s in ("夏", "冬"):
        return True
    return w.get("cat") == "外套" or bool(SEASONAL_RE.search(str(w.get("name") or "")))


# 衣物季节：手选 season 优先（值域内原样返回），否则按「品类名+名称」推断。
# 推断只出 夏 / 冬 / 春秋——「四季」只来自手选，不由词表猜。与 engine.js 的 seasonOf 逐字同口径。
SEASON_VALUES = ("夏", "春秋", "冬", "四季")
SEASON_SUMMER_RE = re.compile("短袖|背心|吊带|凉鞋|拖鞋|短裤|雪纺")
SEASON_WINTER_RE = re.compile("羽绒|大衣|棉服|棉袄|围巾|围脖|毛衣|针织|靴|卫衣|加绒|羊羔毛|皮草|雪地")


def season_of(w) -> str:
    s = (w or {}).get("season")
    if s in SEASON_VALUES:
        return s
    text = f"{(w or {}).get('cat') or ''}{(w or {}).get('name') or ''}"
    if SEASON_SUMMER_RE.search(text):
        return "夏"
    if SEASON_WINTER_RE.search(text):
        return "冬"
    return "春秋"


def wear_line(w) -> str:
    if not w:
        return ""
    if not w.get("worn"):
        return "那件还没穿过。"
    d = _days_since(w.get("lastWorn"))
    if d >= 180:
        if is_seasonal(w):
            return "那件是季节性衣物，多半是换季收起来了。"
        return f"那件已经 {d // 30} 个月没穿了。"
    if d >= 60:
        return f"那件上次穿是 {d // 30} 个月前。"
    if d >= 14:
        return f"那件上次穿是 {d // 7} 周前。"
    if d >= 2:
        return f"那件 {d} 天前刚穿过。"
    return "那件最近常穿。"


def wear_short(w) -> str:
    if not w:
        return ""
    if not w.get("worn"):
        return "还没穿过"
    d = _days_since(w.get("lastWorn"))
    if d >= 180:
        return "换季收起了" if is_seasonal(w) else f"{d // 30} 个月没穿"
    if d >= 60:
        return f"{d // 30} 个月前穿过"
    if d >= 14:
        return f"{d // 7} 周前穿过"
    if d >= 2:
        return f"{d} 天前穿过"
    return "最近常穿"


def pick_companions(item: dict, wardrobe: list) -> list:
    """这件能和柜里哪些搭。只算不同品类。"""
    rgb_n = hex_rgb(item.get("color"))
    lab_n = rgb_to_lab(rgb_n)
    h1, s1, l1 = rgb_to_hsl(rgb_n)

    def neutral(s, l):
        return s < 0.16 or l > 0.90 or l < 0.12

    base_neutral = neutral(s1, l1)
    out = []
    for w in wardrobe:
        if w.get("cat") == item.get("cat"):
            continue
        rgb_w = hex_rgb(w.get("color"))
        de = delta_e(lab_n, rgb_to_lab(rgb_w))
        if de < 6:
            continue
        h2, s2, l2 = rgb_to_hsl(rgb_w)
        ok = base_neutral or neutral(s2, l2)
        if not ok:
            g = hue_gap(h1, h2)
            ok = g < 60 or g > 150
        if ok:
            out.append((de, w))
    out.sort(key=lambda x: x[0])
    res = []
    for de, w in out[:3]:
        it = dict(w)
        it["gap"] = _round(de)
        res.append(it)
    return res


SAME_CAT_STOP = 22
SAME_CAT_HOLD = 45
CROSS_CAT_HOLD = 14
STALE_MS = 180 * 86400000

# 与 engine.js 的 YI_LINES 一一对应，改一处必须改两处，test/consistency.py 会守着。
YI_LINES = {
    "先别": [
        "和「{}」几乎是同一句话，只是换了个人说。",
        "柜里的「{}」就是这个色。再买一件，是重复的句子。",
        "「{}」已经把这句话说完了。",
    ],
    "再想想": [
        "接近「{}」，差在深浅，或者差在场合。",
        "能进柜，但会和「{}」抢同一季。",
        "跟「{}」是一家的。除非它能解开更多旧的搭配。",
    ],
    "宜入": [
        "柜里没有这个色。它能解开 {} 件旧衣。",
        "这个色柜里空着。买回去，旧的几件会重新好穿。",
    ],
}


def yi(body: dict) -> dict:
    item = body.get("item") or {}
    wardrobe = body.get("wardrobe") or []
    rgb = hex_rgb(item.get("color"))
    lab_n = rgb_to_lab(rgb)

    scored = []
    for w in wardrobe:
        scored.append({
            "item": w,
            "de": delta_e(lab_n, rgb_to_lab(hex_rgb(w.get("color")))),
            "same": w.get("cat") == item.get("cat"),
        })
    scored.sort(key=lambda x: x["de"])

    if not scored:
        return {"stamp": "再想想", "quote": "柜里还空着。先放几件常穿的，过笺才有得比。",
                "close": [], "match": [], "gap": 0, "basis": None, "thin": True, "closetN": 0}

    same = [s for s in scored if s["same"]]
    basis = (same or scored)[0]
    far_best = scored[0]

    stamp = "宜入"
    if basis["same"]:
        if basis["de"] < SAME_CAT_STOP:
            stamp = "先别"
        elif basis["de"] < SAME_CAT_HOLD:
            stamp = "再想想"
    elif far_best["de"] < CROSS_CAT_HOLD:
        stamp = "再想想"

    base_w = basis["item"]
    last_worn = base_w.get("lastWorn")
    seasonal = is_seasonal(base_w)
    stale = (not seasonal) and bool(last_worn) and (time.time() * 1000 - last_worn) > STALE_MS
    match = pick_companions(item, wardrobe)
    name = base_w.get("name", "那件")

    if stamp == "宜入":
        is_pattern = (item.get("pattern") or 0) > 0.55
        # 「能解开 N 件旧衣」数的是全柜里色差够大的那些（只在柜中已有同品类时才报），
        # 不是同品类内的件数——解锁的是搭配，不是再多一件白衬衫。
        wearables = len([s for s in scored if s["de"] >= SAME_CAT_HOLD]) if same else 0
        if is_pattern:
            # 和 engine.js 一样取「最后一句」，不写死下标：那句可达的话在表尾，
            # 表里删一行时这里不会悄悄指到空位上（这里就因此 IndexError 过一次）。
            quote = YI_LINES["宜入"][-1]
        elif len(match) >= 2:
            quote = f"柜里没有这个色，能和 {len(match)} 件旧的搭上。"
        else:
            quote = YI_LINES["宜入"][0].format(max(1, min(4, wearables or 2)))
    elif stale and stamp == "先别":
        quote = f"柜里的「{name}」就是这个色，而且 {_days_since(last_worn) // 30} 个月没穿过了。再买一件，只会多一件不穿的。"
    elif stale and stamp == "再想想":
        quote = f"接近「{name}」。但那一件你自己都不太穿——先想清楚要的是这个色，还是新鲜感。"
    else:
        pool = YI_LINES[stamp]
        quote = pool[min(len(pool) - 1, 1 if len(scored) > 1 else 0)].format(name)

    return {
        "stamp": stamp,
        "quote": quote,
        "close": [x["item"] for x in scored[:2]],
        "match": match,
        "gap": _round(basis["de"]),
        "sameCat": basis["same"],
        "stale": stale,
        "seasonal": seasonal,
        "basis": {
            "name": name,
            "cat": base_w.get("cat", ""),
            "gap": _round(basis["de"]),
            "wear": wear_line(base_w),
            "wearShort": wear_short(base_w),
            "seasonal": seasonal,
            "worn": base_w.get("worn", 0),
            "lastWorn": last_worn,
        },
        # 柜子的厚度：判定函数自己的属性，屏幕、长图、复制话术都从这一处说
        "thin": len(scored) < 5, "closetN": len(scored),
        "toneLine": tone_line(item.get("color"), wardrobe),
    }


def dish_kind(dish: str) -> str:
    if SOUP_RE.search(dish):
        return "汤"
    if STAPLE_RE.search(dish):
        return "主食"
    if MEAT_RE.search(dish):
        return "荤"
    if VEG_RE.search(dish):
        return "素"
    return "其他"


# 上菜阶段：先开胃清口，硬菜居中偏后，汤和主食收尾。
STAGE_NAMES = {1: "先上", 2: "清口", 3: "主菜", 4: "硬菜", 5: "汤", 6: "主食"}
COLD_RE = re.compile("凉拌|拍黄瓜|白灼|醉|卤|酱牛肉|刺身|沙拉|皮蛋|拌")
HEAVY_RE = re.compile("红烧|干锅|水煮|烤|麻辣|香锅|炖|焖|扣|爆|肘子|大盘|小龙虾|整只|整条")


def serving_stage(dish: str) -> int:
    if SOUP_RE.search(dish):
        return 5
    if STAPLE_RE.search(dish):
        return 6
    if COLD_RE.search(dish):
        return 1
    if HEAVY_RE.search(dish):
        return 4
    if dish_kind(dish) == "素":
        return 2
    return 3


def serving_order(lines: list, mode: str = "", later=None) -> list:
    """上菜顺序。mode 是判定输入：work（同事）把有人吃不了的压到最后，
    home（家里）把这些连同硬菜一起压到最后——这两句话在界面上印了很久，
    以前这一函数只认 stage。压后 = stage + 7（stage 只有 1~6），全序且确定。
    later 由调用方算好传入（boom 的菜名），这里不再判一遍忌口。"""
    late = later or set()

    def key(d: str) -> int:
        st = serving_stage(d)
        pushed = (mode == "work" and d in late) or \
                 (mode == "home" and (d in late or HEAVY_RE.search(d)))
        return st + (7 if pushed else 0)

    pairs = sorted(enumerate(lines), key=lambda p: (key(p[1]), p[0]))
    return [
        {"dish": d, "stage": st, "label": STAGE_NAMES[st]}
        for _, d in pairs
        for st in [serving_stage(d)]
    ]


def table_plan(n: int, kinds: dict) -> dict:
    n = max(1, n)
    want = {
        "荤": max(1, _round(n * 0.5) + (1 if n >= 4 else 0)),
        "素": max(1, _round(n * 0.5)),
        "汤": 1 if n >= 3 else 0,
        "主食": 2 if n >= 5 else 1,
    }
    gap = {k: want[k] - kinds.get(k, 0) for k in ("荤", "素", "汤", "主食") if want[k] - kinds.get(k, 0) > 0}
    return {"want": want, "gap": gap, "total": sum(want.values())}


# 家常菜库。tags 是它会触发哪些忌口，推荐时避开。
DISHES = {
    "荤": [
        ("红烧排骨", ["猪肉"]), ("糖醋里脊", ["猪肉"]), ("可乐鸡翅", []), ("白切鸡", []),
        ("三杯鸡", ["酒"]), ("黑椒牛柳", ["牛羊肉"]), ("孜然羊肉", ["牛羊肉"]),
        ("清蒸鲈鱼", ["海鲜"]), ("红烧带鱼", ["海鲜"]),
        ("京酱肉丝", ["猪肉"]), ("梅菜扣肉", ["猪肉"]), ("滑蛋虾仁", ["海鲜"]),
        ("豉汁蒸凤爪", ["蒜"]), ("香菇滑鸡", []), ("土豆炖牛肉", ["牛羊肉"]),
        ("酱爆鸡丁", ["花生"]),
        ("红烧狮子头", ["猪肉"]), ("油焖大虾", ["海鲜"]), ("木须肉", ["猪肉"]),
        ("葱爆羊肉", ["牛羊肉"]),
    ],
    "素": [
        ("清炒时蔬", []), ("白灼菜心", []), ("香菇青菜", []),
        ("清炒芦笋", []), ("地三鲜", []), ("醋溜白菜", []), ("蒜蓉西兰花", ["蒜"]),
        ("凉拌黄瓜", ["蒜"]), ("手撕包菜", ["辣"]), ("酸辣土豆丝", ["辣"]),
        ("干煸四季豆", ["辣", "猪肉"]), ("麻婆豆腐", ["辣", "猪肉"]), ("凉拌木耳", ["蒜"]),
        ("醋溜土豆丝", []), ("蒜泥茄子", ["蒜"]), ("香菇油菜", []),
        # 蛋菜按素计（与 engine.js 同：MEAT_RE 没有「蛋」）；放队尾不动既有推荐顺序
        ("番茄炒蛋", []), ("韭菜炒蛋", []),
    ],
    "汤": [
        ("西红柿蛋汤", []), ("丝瓜蛋汤", []), ("菌菇汤", []), ("冬瓜排骨汤", ["猪肉"]),
        ("玉米排骨汤", ["猪肉"]), ("老鸭汤", []), ("紫菜蛋花汤", ["海鲜"]),
        ("番茄牛腩汤", ["牛羊肉"]), ("酸辣汤", ["辣"]), ("萝卜牛腩煲", ["牛羊肉"]),
        ("海带豆腐汤", ["海鲜"]), ("鲫鱼豆腐汤", ["海鲜"]),
        ("上汤娃娃菜", []),   # 「上汤」是带汤的做法，SOUP_RE 先判，算汤不算素
    ],
    "主食": [
        ("米饭", []), ("蛋炒饭", []), ("葱油拌面", []), ("阳春面", []), ("手抓饼", []),
        ("玉米烙", []), ("南瓜饼", []), ("猪肉白菜饺子", ["猪肉"]), ("小笼包", ["猪肉"]),
        ("刀削面", []),
        ("韭菜盒子", []), ("牛肉面", ["牛羊肉"]),
    ],
}

SPICY_RE = re.compile("辣|麻|干锅|水煮|泡椒|剁椒|椒麻|红油")
# 同一主料出现两次以上就提醒换一道（里脊/狮子头补家常肉菜主料）
MAINS = ["鱼", "虾", "蟹", "鸡", "鸭", "牛", "羊", "猪", "排骨", "豆腐", "蛋", "茄子", "土豆", "面", "里脊", "狮子头"]


def recommend(gap: dict, bans: set, lines: list) -> list:
    """缺口在哪一类，就从菜库里挑几道能点的。"""
    out = []
    for kind in ("荤", "素", "汤", "主食"):
        if not gap.get(kind):
            continue
        pool = []
        for name, tags in DISHES.get(kind, []):
            if any(name in d or d in name for d in lines):
                continue
            if any(t in bans for t in tags):
                continue
            if "清淡" in bans and ("辣" in tags or SPICY_RE.search(name)):
                continue
            pool.append(name)
        for name in pool[: min(3, gap[kind] + 1)]:
            out.append({"kind": kind, "name": name})
    return out


def find_dupes(lines: list) -> list:
    """同一主料出现两次以上。"""
    buckets: dict = {}
    for dish in lines:
        for m in MAINS:
            if m in dish:
                buckets.setdefault(m, []).append(dish)
    return [{"main": m, "dishes": ds} for m, ds in buckets.items() if len(ds) > 1]


QINGDAN_RE = re.compile("辣|麻|水煮|香锅|火锅|酸菜|口水|毛血|剁椒|泡椒|藤椒|红油")


# 菜库摊平成一列（荤→素→汤→主食，与 engine.js 的 Object.keys 序一致）：
# 每次判定都扫它一遍，40 行的菜单也就 2500 次子串比较，不值得再缓存。
DISH_TAGS = [(d[0], d[1]) for kind in DISHES.values() for d in kind]


# 菜单框里混的不只是菜（详见 engine.js 的 menuItems）：整句被当成一道菜是笑话，
# 「有人不吃辣」被静默丢掉是把人吃坏的那一种错。与 engine.js 逐字一致。
SPLIT_MENU_RE = re.compile(r"[\n,，、；;。！!？?()\s（）【】]")
FILLER_HEAD_RE = re.compile(r"^(还有|再有|再来|再加|以及|另外|另|然后|最后|准备|打算|想做|做个|做点|来点|来份|来一份|来一盘|点个|点份|加|[一二三四五六七八九十两\d]+ ?[道份盘碗个])+")
NOTE_RE = re.compile(r"不吃|不敢吃|不能吃|吃不了|不喝|忌口|忌讳|忌|过敏|别上|别放|不放|不要|喜欢|爱吃|爱喝|偏好|口味|来吃饭|来吃|吃饭|几个人|[一两二三四五六七八九十\d]+ ?个人|个人|这桌|那桌|预算|多少钱|随便|就行|够了|注意|提醒|菜单|点菜|订餐|外卖")
NEG_RE = re.compile(r"不吃|不敢吃|不能吃|吃不了|不喝|忌口|忌讳|忌|过敏|别上|别放|不放|不要|少放")
POS_RE = re.compile(r"喜欢|爱吃|爱喝|偏好|无辣不欢|就好|就好吃")
# 一句话里可以两个方向都有：「不吃香菜但爱吃辣」。整句一起判会连香菜一起放过，
# 所以先按转折词劈开，逐小句判否定/肯定——「但」前面那句才是这一桌的雷。
TURN_RE = re.compile(r"但|可是|不过|然而|虽然")
# 波浪号、间隔号这类装饰性收尾：「沙拉～」当菜名端出来就是一张废纸。
MENU_TRIM_RE = re.compile(r"^[\s、，,。.!！?？~～〜·・]+|[\s、，,。.!！?？~～〜·・]+$")
# 一个片段里连一个字/字母/数字都没有（只剩 🍕 🥗 这类表情）就不是菜，也不值得回显。
MENU_REAL_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]")


def menu_items(menu: str):
    """把菜单文本分成「菜」和「关于这桌人的话」，顺序即出现顺序。"""
    dishes, notes = [], []
    for seg in SPLIT_MENU_RE.split(menu or ""):
        raw = MENU_TRIM_RE.sub("", seg.strip())
        if not raw or not MENU_REAL_RE.search(raw):
            continue
        s = MENU_TRIM_RE.sub("", FILLER_HEAD_RE.sub("", raw).strip())
        if not s or NOTE_RE.search(s):
            notes.append(s or raw)
            continue
        dishes.append(s)
    return dishes, notes


def chips_in_notes(notes, known):
    """从「话」里捞出忌口：命中否定词、且句子里有这味忌口的关键词才算。
    遍历 CHIP_MAP 的声明序（与 engine.js 同），按文本位置排两端就会漂。
    转折词先把句子劈开：「不吃香菜但爱吃辣」里香菜照忌、辣不忌。"""
    out = []
    for seg in notes:
        for clause in TURN_RE.split(seg):
            clause = clause.strip()
            if not clause or not NEG_RE.search(clause) or POS_RE.search(clause):
                continue
            for c, keys in CHIP_MAP.items():
                if c in known or any(x[0] == c for x in out) or not keys:
                    continue                       # 清淡没有关键词，不靠猜
                if any(k and k in clause for k in keys):
                    out.append((c, clause))
    return out


def wei(body: dict) -> dict:
    menu = body.get("menu") or ""
    people = body.get("people") or []
    # mode 是应用发过来的（api.js 的 wei(...)），以前这里收了包却从不看它
    mode = body.get("mode") or ""
    lines, notes = menu_items(menu)
    # bans 用「去重且保序」的列表：engine.js 那边是 Set（插入序 = people 先后、
    # 每人 chips 先后），换成 Python 的 set 会按哈希排，理由文案就漂了。
    chip_bans = list(dict.fromkeys(c for p in people for c in (p.get("chips") or [])))
    inferred = chips_in_notes(notes, chip_bans)
    bans = chip_bans + [c for c, _ in inferred]
    ban_set = set(bans)

    safe, risk, boom = [], [], []
    kinds = {"荤": 0, "素": 0, "汤": 0, "主食": 0, "其他": 0}
    for dish in lines:
        # dict 当有序集合用：命中顺序 = HIDDEN 声明序 → chips 序，与 JS 的 Set 一致
        hits: dict = {}
        for k, arr in HIDDEN.items():
            if k in dish:
                for x in arr:
                    hits.setdefault(x, None)
        for b in bans:
            for k in CHIP_MAP.get(b, [b]):
                if k and k in dish:
                    hits.setdefault(b, None)
        # 菜库的 tags 也算成分（小笼包 / 干煸四季豆 这种名字里不含原料字的菜）。
        # 顺序与 engine.js 一致：荤→素→汤→主食，再按表内序。
        for dn, dtags in DISH_TAGS:
            if dn in dish:
                for x in dtags:
                    hits.setdefault(x, None)
        blocked = [h for h in hits if h in ban_set]
        # 菜库说它辣也算：只看菜名的话「香辣土豆丝」进雷区而「手撕包菜」只算谨慎，
        # 同一样成分因为名字写法不同落进不同一层。
        if "清淡" in ban_set and (QINGDAN_RE.search(dish) or "辣" in hits) and "辣" not in blocked:
            blocked.append("清淡")
        kind = dish_kind(dish)
        kinds[kind] = kinds.get(kind, 0) + 1
        if blocked:
            boom.append({"dish": dish, "why": " / ".join(blocked), "kind": kind})
        elif hits:
            risk.append({"dish": dish, "why": " / ".join(hits), "kind": kind})
        else:
            safe.append(dish)

    plan = table_plan(len(people), kinds)
    suggest = (safe or [x["dish"] for x in risk])[:8]
    return {
        "safe": safe, "risk": risk, "boom": boom, "suggest": suggest,
        "kinds": kinds, "plan": plan,
        "add": recommend(plan["gap"], ban_set, lines),
        "dupes": find_dupes(lines),
        "order": serving_order(lines, mode, {x["dish"] for x in boom}),
        "hasMenu": len(lines) > 0,
        "bans": bans, "chipBans": chip_bans, "notes": notes,
        "inferred": [{"chip": c, "from": s} for c, s in inferred],
    }


KINDS = [
    ("要买", re.compile("买|下单|带一|带瓶|带个|药|票|快递|取件|代购|补货")),
    ("已定", re.compile("就定|就这样|定了|决定|那就|同意|成交|说定|约好|确认|可以了|行吧")),
    ("还没说清", re.compile("再说|不确定|看看|可能|或者|到时|改天|待定|再议|回头说")),
    ("待办", re.compile("记得|务必|需要|下周|明天|后天|截止|之前|安排|处理|提交|预约|发我|拿一下|别忘了|跟进|催|让我|叫我")),
]
WD = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}

# 说话人前缀：行首「某某：」（1-4 个汉字）。前缀命中时间词或功能标签时不标，
# 防止「明天：交房租」被当成自我介绍。与 engine.js 的 SPEAKER_* 逐字一致。
SPEAKER_RE = re.compile(r"^([\u4e00-\u9fa5]{1,4})[：:]")
SPEAKER_TIME_STOP = re.compile(r"今天|明天|后天|大后天|下周|本周|这周|周末|周中|[周星期拜][一二三四五六日天]|月底|月中|月初|年底|中午|晚上|下午|早上|[\u4e00-\u9fa5]{1,2}月[\u4e00-\u9fa5]{0,2}[日号]")
SPEAKER_TAG_STOP = re.compile(r"要买|待办|提醒|注意|备注")

# who 否决词：命中即不出人名（时间/转场/指代/动作词）。与 engine.js 的 WHO_STOP_RE 逐字一致。
WHO_STOP_RE = re.compile("快|没|不|了|要|买|发|拿|再说|时间|时候|现在|回头|等下|大家|我们|你们|他们")
# 连接副词：{2,3} 贪心捕获会把它吃进人名（「小王再说」→「小王再」），末尾剥一个收口。
WHO_TAIL_ADVERB_RE = re.compile(r"[再又还也就才都先]$")


def parse_time(line: str, now: datetime):
    """与 engine.js 的 parseTime 同口径：绝对日期落到本地零点、不存在的日子钳到月末、
    文案与时间戳自洽。月份/日期越界（99月5日）当作没有时间，不硬凑。"""
    # 相对日期一律按「绝对毫秒 + N 天」算，和 JS 的 d.getTime() + 86400000 一模一样。
    # 用 timedelta(days=) 是加墙钟时间，部署到有夏令时的时区会比前端多/少一小时。
    now_ms = int(now.timestamp() * 1000)
    DAY_MS = 86400000

    if m := re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", line):
        mo, day = int(m.group(1)), int(m.group(2))
        if mo < 1 or mo > 12 or day < 1 or day > 31:
            return None
        t = clamp_date(now.year, mo, day)
        if t < now - timedelta(days=180):
            t = clamp_date(t.year + 1, mo, day)
        return {"text": f"{t.month}月{t.day}日", "at": int(t.timestamp() * 1000)}
    if "大后天" in line:
        return {"text": "大后天", "at": now_ms + 3 * DAY_MS}
    if "后天" in line:
        return {"text": "后天", "at": now_ms + 2 * DAY_MS}
    if "明天" in line or "明日" in line:
        return {"text": "明天", "at": now_ms + DAY_MS}
    if any(k in line for k in ("今天", "今日", "今晚", "今天晚上")):
        label = "今晚" if ("今晚" in line or "今天晚上" in line) else "今天"
        return {"text": label, "at": now_ms}
    if m := re.search(r"(下+|本|这)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天])", line):
        target = WD[m.group(2)]
        cur = 7 if now.isoweekday() == 7 else now.isoweekday()
        is_next = (m.group(1) or "").startswith("下")
        add = target - cur
        if is_next:
            add += 7
        elif add < 0:  # add == 0 就是今天，比如今天周四说「周四前」
            add += 7
        return {"text": ("下" if is_next else "这") + "周" + m.group(2),
                "at": now_ms + add * DAY_MS}
    if m := re.search(r"(\d{1,2})\s*[日号](?![前内])", line):
        day = int(m.group(1))
        if 1 <= day <= 31:
            t = clamp_date(now.year, now.month, day)
            if t < now - timedelta(days=1):
                t = clamp_date(now.year + 1, 1, day) if now.month == 12 else clamp_date(now.year, now.month + 1, day)
            return {"text": f"{t.month}月{t.day}日", "at": int(t.timestamp() * 1000)}
    if "月底" in line or "月末" in line:
        nxt = now.replace(day=28) + timedelta(days=7)
        last = (nxt - timedelta(days=nxt.day)).replace(hour=0, minute=0, second=0, microsecond=0)
        return {"text": "月底", "at": int(last.timestamp() * 1000)}
    return None


def yan(body: dict) -> dict:
    text = body.get("text") or ""
    parts = [x.strip() for x in re.split(r"[。！？!?\n；;]", text) if len(x.strip()) > 1]
    out = {"待办": [], "要买": [], "已定": [], "还没说清": []}
    now = datetime.now()
    for line in parts:
        hit = None
        for key, rx in KINDS:
            if rx.search(line):
                hit = key
                break
        t = parse_time(line, now)
        if not hit:
            if re.search("明天|下周|记得|帮|要", line):
                hit = "待办"
            # 「周五把合同寄出」这种——有能解析出的日期、又是「把 X 怎么着」的句式，
            # 以前两边都不认，整句被静默丢掉。只兜「本来会被扔掉的行」，不改已分类的结果。
            elif t and re.search("把.+", line):
                hit = "待办"
            else:
                continue
        item = {"line": line[:60], "when": t, "who": None, "speaker": None}
        if m := re.match(r"^([\u4e00-\u9fa5]{2,3})(?=说|让我|叫我|答应|要求|问)", line):
            # 只认明确指认，避免「药快没了帮我买」被当成人名；
            # 否决词含时间/转场停用词，防止「时间再说周五交稿」误判出 who=时间再。
            # 贪心捕获末尾剥单个连接副词收口成纯人名；剥后不足 2 字（「他又让我」→「他」）则不给。
            # 与 engine.js 逐字一致。
            raw = m.group(1)
            name = WHO_TAIL_ADVERB_RE.sub("", raw)
            if len(name) >= 2 and not WHO_STOP_RE.search(raw) and not WHO_STOP_RE.search(name):
                item["who"] = name
        if sp := SPEAKER_RE.match(line):
            # 说话人：冒号前缀原样保留（不去前缀、不改写），line 保持原文与截断逻辑不变
            pfx = sp.group(1)
            if not SPEAKER_TIME_STOP.search(pfx) and not SPEAKER_TAG_STOP.search(pfx):
                item["speaker"] = pfx
        out[hit].append(item)
    ask = "要不要把截止日期说死？"
    # 追问引用的是念给用户听的那一句：卡片上已经盖了说话人的签，再引一遍「小王：」
    # 就成了两个人在说话。只动这一处引用——line 留着原话，复制整张笺要它。与 engine.js 一致。
    def quoted(x):
        rest = x["line"][len(x["speaker"]):] if x.get("speaker") and x["line"].startswith(x["speaker"]) else ""
        return rest[1:] if rest[:1] in ("：", ":") else x["line"]
    # 也不许整句抄回来：一条 46 字的待办能把追问撑成满屏的字。截到 22 字加省略号。
    def brief(s):
        return s if len(s) <= 22 else s[:21] + "…"
    if out["还没说清"]:
        ask = f"「{brief(quoted(out['还没说清'][0]))}」这件事，时间定在哪天？"
    elif out["待办"]:
        ask = f"「{brief(quoted(out['待办'][0]))}」谁来做、什么时候？"
    out["ask"] = ask
    out["total"] = sum(len(v) for v in out.values() if isinstance(v, list))
    return out


# 仅供 test/consistency.py 做全表对账：与 engine.js 的 TABLES 同结构，逐字逐序比。
# 判定函数的用例覆盖不到词表尾部，一端偷偷加一条菜只有整张表才能炸出来。
# 正则以 .pattern 文本比，engine.js 侧对应 .source。
# DISHES 在这里就规范成 engine 的 {n, tags} 形状，让对账两端同构。
TABLES = {
    "HIDDEN": HIDDEN,
    "CHIP_MAP": CHIP_MAP,
    "DISHES": {k: [{"n": d[0], "tags": list(d[1])} for d in v] for k, v in DISHES.items()},
    "MAINS": MAINS,
    "RE": {
        "MEAT": MEAT_RE.pattern, "VEG": VEG_RE.pattern, "SPICY": SPICY_RE.pattern,
        "SOUP": SOUP_RE.pattern, "STAPLE": STAPLE_RE.pattern, "COLD": COLD_RE.pattern,
        "HEAVY": HEAVY_RE.pattern, "QINGDAN": QINGDAN_RE.pattern,
        "SEASONAL": SEASONAL_RE.pattern,
        "SEASON_SUMMER": SEASON_SUMMER_RE.pattern, "SEASON_WINTER": SEASON_WINTER_RE.pattern,
        "WHO_STOP": WHO_STOP_RE.pattern, "WHO_TAIL_ADVERB": WHO_TAIL_ADVERB_RE.pattern,
        "SPEAKER": SPEAKER_RE.pattern, "SPEAKER_TIME_STOP": SPEAKER_TIME_STOP.pattern,
        "SPEAKER_TAG_STOP": SPEAKER_TAG_STOP.pattern,
        "MENU_SPLIT": SPLIT_MENU_RE.pattern, "MENU_FILLER": FILLER_HEAD_RE.pattern,
        "MENU_NOTE": NOTE_RE.pattern, "MENU_NEG": NEG_RE.pattern, "MENU_POS": POS_RE.pattern,
        "MENU_TURN": TURN_RE.pattern,
        "MENU_TRIM": MENU_TRIM_RE.pattern, "MENU_REAL": MENU_REAL_RE.pattern,
        "KINDS": [{"key": k, "source": rx.pattern} for k, rx in KINDS],
    },
    "NUM": {
        "SAME_CAT_STOP": SAME_CAT_STOP, "SAME_CAT_HOLD": SAME_CAT_HOLD,
        "CROSS_CAT_HOLD": CROSS_CAT_HOLD, "STALE": STALE_MS,
    },
}


# 静态目录就是仓库根，里面躺着 .git/ 和正式签名 keystore。这两个不该被 GET 走。
# 没有改成只发 www/：www/ 是构建产物，新克隆的仓库里不存在，会把「浏览器开网关直接看 H5」
# 这条路断掉；而且网关真正的卖点是 /v1/*，静态目录只是顺带。
# 仓库根目录就是静态目录，所以落在仓库树里的任何密钥文件都能被 http://网关/路径 下载走。
# 模型清单默认放在 ~/.jian/（仓库外）是第一层；这里是第二层——万一有人把它放进了仓库树，
# 或者哪天改了名放进来，也别让它发得出去。\.pem$ 顺带盖住私钥。
_DENY_RE = re.compile(r"(^|/)\.[^/]+|\.keystore$|(^|/)(llm_providers|providers|secrets)\.json$|\.pem$", re.I)

# 图片走 base64 塞在 JSON 里：手机原图能到 8~12MB，转完更大。前端会先缩到 512 再传，
# 这里再兜一道上限，免得一个误传的大文件把网关的内存和带宽都吃掉。
MAX_BODY = int(os.environ.get("JIAN_MAX_BODY", str(8 * 1024 * 1024)))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def translate_path(self, path):
        full = super().translate_path(path)
        rel = "/" + os.path.relpath(full, ROOT).replace(os.sep, "/")
        if _DENY_RE.search(rel):
            return str(ROOT / "__denied__")   # 必然不存在，交给基类回 404
        return full

    def log_message(self, fmt, *args):
        print("[jian]", fmt % args)

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # /v1/status 是网关的自述：配没配模型、是哪一家。界面上要说得出
        # 「网关在线，但没配模型，识图走不了」，不能只说「已连接」。
        if urlparse(self.path).path.endswith("/v1/status"):
            return self._json(200, {"ok": True, "model": llm.status(),
                                    "tasks": {"yi": True, "wei": True, "yan": True,
                                              "recognize": llm.configured(), "ocr": llm.configured()}})
        return super().do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        # 判定层抛异常必须回 500，不能让连接被掀掉：api.js 把连接中断和 !res.ok 都当成
        # 「网关不可用」静默回落本地引擎，界面上看不出任何异常，接了网关的假象永远发现不了。
        try:
            code, obj = self._handle()
        except Exception as e:
            code, obj = 500, {"error": f"{type(e).__name__}: {e}"}
        self._json(code, obj)

    def _handle(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "invalid json"}
        if not isinstance(body, dict):
            return 400, {"error": "body must be an object"}
        # 按路径分流（GATEWAY.md 的约定），task 只在 /v1/complete 里区分味/言。
        # 之前写成 `path.endswith("/v1/see") or task == "yi"`，任何路径带着 task=yi
        # 都会回 200——端点打错了也悄悄能用，正好把配置错误藏起来。
        if path.endswith("/v1/see"):
            return 200, yi(body)
        if path.endswith("/v1/complete"):
            task = body.get("task")
            # 认不出的 task 不能悄悄当味笺算了：以前 task 打错字照样回 200，
            # 界面上看不出接线错了。缺省（老客户端）仍按味笺走。
            if task not in (None, "", "wei", "yan"):
                return 400, {"error": "badtask", "message": "/v1/complete 只认 wei 与 yan，收到 %r" % (task,)}
            return 200, yan(body) if task == "yan" else wei(body)
        if path.endswith("/v1/hear"):
            return 200, {"needText": True, "message": HEAR_NOTE}
        if path.endswith("/v1/recognize"):
            return _see_model(body)
        if path.endswith("/v1/ocr"):
            return _ocr_model(body)
        return 404, {"error": "unknown"}

# 语音这条路目前没有可转写的模型：与其回一句含糊的「不支持」，不如说清楚下一步怎么办。
HEAR_NOTE = "这里还不能把录音转成文字。请在手机上用输入法把那段话转写出来，再贴进言笺的框里。"


def _model_reply(fn, body):
    """两条模型路的共同外壳：图片要带、要不太大、模型不行就说得出为什么不行。"""
    img = str(body.get("image") or "")
    if not img.startswith("data:image/"):
        return 400, {"error": "noimage", "message": "没收到图片（要 data:image/… 的 base64）"}
    if len(img) < 2048:
        # 一张真缩略图也不止 2KB。这么短的十有八九是前端把空 canvas 或测试塞进来的假数据，
        # 发给模型只会白等一次超时，所以在这里就拒，并且说清楚是「太小」不是「没有」。
        return 400, {"error": "tinyimage", "message": "图片太小（%d 字节），不像一张能看的照片" % len(img)}
    if len(img) > MAX_BODY:
        return 413, {"error": "toobig",
                     "message": "图片太大（%dMB），先把它缩小一点再传" % (len(img) // 1024 // 1024)}
    try:
        return 200, fn(img)
    except llm.LlmError as e:
        # 502：上游模型的问题，不是这条请求写错了。前端据此回落本地并说明原因。
        return 502, {"error": e.code, "message": str(e)}


def _see_model(body):
    code, obj = _model_reply(llm.see, body)
    if code == 200:
        obj["source"] = "model"
        obj["model"] = llm.MODEL
    return code, obj


def _ocr_model(body):
    code, obj = _model_reply(lambda s: {"text": llm.ocr(s)}, body)
    if code == 200:
        obj["model"] = llm.MODEL
    return code, obj


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"jian gateway http://{HOST}:{PORT}  (ctrl+c stop)")
    if HOST in ("0.0.0.0", "::"):
        for ip in lan_ips():
            print(f"  同一张局域网里的手机填：http://{ip}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
