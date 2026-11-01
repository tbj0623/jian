# 守门测试：engine.js 与 backend/gateway.py 对同一批输入必须给同一结论。
# 两端的判定口径一旦漂了，这里会先炸——比起走网关才发现结论不对要省事得多。
#
# 运行：python test/consistency.py
#
# 三条纪律，都是上一轮漂移换来的：
#   1. 比对走 norm_*（只在本文件写一份），字段要取全。norm 里漏一个字段 = 那个字段没人守。
#   2. 词表/正则/阈值整张表对账（tables 小节）。判定用例只能命中词表队首，尾部漂移靠表。
#   3. 时钟钉死。判定里有「半年没穿」「下周三」，两端各取当前时间会无规律地闪、at 永远对不上。
import json
import os
import pathlib
import shutil
import subprocess
import sys
import types
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "test" / "_cases.json"

DAY = 86400000
# 2026-03-05 14:30 本地时间，一个周四（e2e 也钉在周四）
PIN_DT = datetime(2026, 3, 5, 14, 30, 0)
PIN_MS = int(PIN_DT.timestamp() * 1000)
NOW = PIN_MS

CASES = {
    "yi": [
        {
            "name": "白上衣撞白衬衫",
            "item": {"name": "想买的这件", "cat": "上衣", "color": "#f5f0eb"},
            "wardrobe": [
                {"name": "白衬衫", "cat": "上衣", "color": "#f4f0ea", "worn": 4, "lastWorn": NOW - 10 * DAY},
                {"name": "深蓝阔腿", "cat": "裤装", "color": "#2c3a4a", "worn": 12, "lastWorn": NOW - DAY},
                {"name": "白鞋", "cat": "鞋", "color": "#f5f5f3", "worn": 15, "lastWorn": NOW},
            ],
        },
        {
            "name": "同色但半年没穿",
            "item": {"name": "x", "cat": "上衣", "color": "#f2eee7"},
            "wardrobe": [
                {"name": "旧白衬衫", "cat": "上衣", "color": "#f4f0ea", "worn": 3, "lastWorn": NOW - 200 * DAY},
                {"name": "白鞋", "cat": "鞋", "color": "#f5f5f3", "worn": 9, "lastWorn": NOW - 2 * DAY},
            ],
        },
        {
            "name": "亮红上衣全柜无",
            "item": {"name": "x", "cat": "上衣", "color": "#b83227"},
            "wardrobe": [
                {"name": "燕麦针织", "cat": "上衣", "color": "#d4c4b0", "worn": 9, "lastWorn": NOW - 2 * DAY},
                {"name": "深蓝阔腿", "cat": "裤装", "color": "#2c3a4a", "worn": 12, "lastWorn": NOW - DAY},
                {"name": "白鞋", "cat": "鞋", "color": "#f5f5f3", "worn": 15, "lastWorn": NOW},
                {"name": "驼大衣", "cat": "外套", "color": "#c4a574", "worn": 3, "lastWorn": NOW - 200 * DAY},
            ],
        },
        {
            "name": "外套久未穿（换季）",
            "item": {"name": "x", "cat": "外套", "color": "#c9ab7c"},
            "wardrobe": [
                {"name": "驼大衣", "cat": "外套", "color": "#c4a574", "worn": 3, "lastWorn": NOW - 214 * DAY},
            ],
        },
        # 季节这一层两端都得读同一个字段：season_of 供柜子筛选，is_seasonal 供久未穿判定。
        # 以前后者只看品类与名字线索，手选过「夏」的一件在三月会被数落「6 个月没穿」。
        # want 把产品口径钉住——两端一起改错也要炸。
        {
            "name": "手选夏天的衣物久未穿（换季，不是买错）",
            "item": {"name": "x", "cat": "上衣", "color": "#f2eee7"},
            "wardrobe": [
                {"name": "白短袖T恤", "cat": "上衣", "color": "#f4f0ea",
                 "worn": 5, "lastWorn": NOW - 200 * DAY, "season": "夏"},
            ],
            "want": {"stamp": "先别", "seasonal": True, "stale": False},
        },
        {
            "name": "手选四季的衣物久未穿（不给他找换季的台阶）",
            "item": {"name": "x", "cat": "上衣", "color": "#f2eee7"},
            "wardrobe": [
                {"name": "打底长袖", "cat": "上衣", "color": "#f4f0ea",
                 "worn": 2, "lastWorn": NOW - 200 * DAY, "season": "四季"},
            ],
            "want": {"stamp": "先别", "seasonal": False, "stale": True},
        },
        {
            "name": "没人手选季节、名字推断出夏天（推断也算）",
            "item": {"name": "x", "cat": "鞋", "color": "#efe6d6"},
            "wardrobe": [
                {"name": "细带凉鞋", "cat": "鞋", "color": "#f0e8dc", "worn": 2, "lastWorn": NOW - 200 * DAY},
            ],
            "want": {"seasonal": True, "stale": False},
        },
        # 冷暖调这一句（第 33 轮）：toneOf 从第五轮就在算，可全仓没人读它。
        # want 钉的是这句话的产品口径——什么时候说、说什么、数怎么带。
        {
            "name": "暖柜里的一件冷色：少数调要说出来，并带上几件/共几件",
            "item": {"name": "x", "cat": "鞋", "color": "#2c3a4a"},
            "wardrobe": [
                {"name": "a", "cat": "上衣", "color": "#c9b39b", "worn": 3, "lastWorn": NOW},
                {"name": "b", "cat": "上衣", "color": "#d8c9b4", "worn": 3, "lastWorn": NOW},
                {"name": "c", "cat": "上衣", "color": "#c4a574", "worn": 3, "lastWorn": NOW},
                {"name": "d", "cat": "上衣", "color": "#8a5a2b", "worn": 3, "lastWorn": NOW},
                {"name": "e", "cat": "上衣", "color": "#b06a4a", "worn": 3, "lastWorn": NOW},
            ],
            "want": {"toneLine": "柜里 5/5 件是暖调，这件是冷调。"},
        },
        {
            "name": "冷暖各半的柜子：不到六成就不硬找话说",
            "item": {"name": "x", "cat": "鞋", "color": "#2c3a4a"},
            "wardrobe": [
                {"name": "a", "cat": "上衣", "color": "#c9b39b", "worn": 3, "lastWorn": NOW},
                {"name": "b", "cat": "上衣", "color": "#d8c9b4", "worn": 3, "lastWorn": NOW},
                {"name": "c", "cat": "上衣", "color": "#c4a574", "worn": 3, "lastWorn": NOW},
                {"name": "d", "cat": "上衣", "color": "#2c3a4a", "worn": 3, "lastWorn": NOW},
                {"name": "e", "cat": "上衣", "color": "#3b6e8f", "worn": 3, "lastWorn": NOW},
                {"name": "f", "cat": "上衣", "color": "#4a6b52", "worn": 3, "lastWorn": NOW},
            ],
            "want": {"toneLine": ""},
        },
        {
            "name": "空柜",
            "item": {"name": "x", "cat": "上衣", "color": "#ffffff"},
            "wardrobe": [],
        },
        # 非法色值：两端必须回落同一个灰，否则色差差 1~2，宜入/再想想会整个翻。
        # 曾经 gateway 只查长度不查字符，"#gggggg" 直接把 int(x,16) 掀翻。
        {
            "name": "非法色值（6 位非 16 进制）",
            "item": {"name": "x", "cat": "裤装", "color": "#gggggg"},
            "wardrobe": [
                {"name": "羊羔毛外套", "cat": "外套", "color": "#8a8a8a", "worn": 9, "lastWorn": NOW - 40 * DAY},
                {"name": "四季长裤", "cat": "裤装", "color": "#f4f0ea", "worn": 0, "lastWorn": None},
            ],
        },
        {
            "name": "非法色值（空串 / 短串 / 中文）",
            "item": {"name": "x", "cat": "上衣", "color": ""},
            "wardrobe": [
                {"name": "短袖T恤", "cat": "上衣", "color": "红色", "worn": 0, "lastWorn": None},
                {"name": "白衬衫", "cat": "外套", "color": "#0a", "worn": 3, "lastWorn": NOW - 150 * DAY},
                {"name": "卫衣", "cat": "包", "color": "#d4c4b0", "worn": 10, "lastWorn": NOW - 3 * DAY},
            ],
        },
        {
            "name": "三位色值缩写",
            "item": {"name": "x", "cat": "上衣", "color": "#abc"},
            "wardrobe": [
                {"name": "灰针织", "cat": "上衣", "color": "#aabbcc", "worn": 1, "lastWorn": NOW - DAY},
                {"name": "深蓝阔腿", "cat": "裤装", "color": "#2c3a4a", "worn": 12, "lastWorn": NOW - DAY},
            ],
        },
        {
            "name": "等距两件（并列取先入柜的）",
            "item": {"name": "x", "cat": "上衣", "color": "#8a8a8a"},
            "wardrobe": [
                {"name": "甲灰外套", "cat": "外套", "color": "#808080", "worn": 2, "lastWorn": NOW - 5 * DAY},
                {"name": "乙灰裤子", "cat": "裤装", "color": "#808080", "worn": 2, "lastWorn": NOW - 5 * DAY},
            ],
        },
        {
            "name": "宜入且能配少于两件（数能解开几件）",
            "item": {"name": "x", "cat": "裙装", "color": "#1f4f9c", "pattern": 0.2},
            "wardrobe": [
                {"name": "蓝裙子A", "cat": "裙装", "color": "#1f4f9c", "worn": 1, "lastWorn": NOW - DAY},
                {"name": "黑裙子B", "cat": "裙装", "color": "#101010", "worn": 8, "lastWorn": NOW - 20 * DAY},
                {"name": "白裙子C", "cat": "裙装", "color": "#f7f7f7", "worn": 2, "lastWorn": NOW - 40 * DAY},
            ],
        },
        {
            "name": "花色压过配搭文案",
            "item": {"name": "x", "cat": "上衣", "color": "#1f4f9c", "pattern": 0.9},
            "wardrobe": [
                {"name": "蓝短袖", "cat": "上衣", "color": "#1f4f9c", "worn": 1, "lastWorn": NOW - DAY},
            ],
        },
    ],
    "wei": [
        {
            "name": "四人各有忌口",
            "menu": "宫保鸡丁\n水煮鱼\n蒜蓉西兰花\n白切鸡\n酸菜鱼\n花生豆腐\n米饭\n西红柿蛋汤",
            "people": [
                {"name": "我", "chips": ["花生"]},
                {"name": "小周", "chips": ["辣"]},
                {"name": "阿姨", "chips": ["海鲜"]},
                {"name": "同行", "chips": ["香菜"]},
            ],
        },
        {
            "name": "缺菜的桌",
            "menu": "宫保鸡丁\n白切鸡",
            "people": [
                {"name": "我", "chips": ["花生", "辣"]},
                {"name": "小周", "chips": []},
                {"name": "阿姨", "chips": ["海鲜"]},
                {"name": "同行", "chips": []},
            ],
        },
        {
            "name": "重复主料",
            "menu": "水煮鱼\n清蒸鲈鱼\n红烧带鱼",
            "people": [{"name": "我", "chips": []}],
        },
        {
            "name": "要清淡",
            "menu": "麻婆豆腐\n水煮鱼",
            "people": [{"name": "我", "chips": ["清淡"]}],
        },
        # 第四十轮：mode 是判定的输入，不是文案的装饰。「家里这桌，硬菜和雷放后面」
        # 「同事这桌，先保全员能入口」这两句从第九轮就印在屏上，而两端都没吃过 mode 这个参数，
        # 四张模式签排出来逐字节相同。want 钉的是**实测**出来的三种不同桌序——
        # 两端一起漂回「不看 mode」也会炸在这里（比两端只是互相一致强）。
        {
            "name": "模式：朋友那桌走家常顺序",
            "menu": "白灼菜心\n红烧肉\n水煮鱼\n米饭",
            "people": [{"name": "我", "chips": ["辣"]}],
            "mode": "friends",
            "want": {"order": ["白灼菜心:先上", "红烧肉:硬菜", "水煮鱼:硬菜", "米饭:主食"]},
        },
        {
            "name": "模式：家里那桌把硬菜和雷压到最后",
            "menu": "白灼菜心\n红烧肉\n水煮鱼\n米饭",
            "people": [{"name": "我", "chips": ["辣"]}],
            "mode": "home",
            "want": {"order": ["白灼菜心:先上", "米饭:主食", "红烧肉:硬菜", "水煮鱼:硬菜"]},
        },
        {
            "name": "模式：同事那桌只压雷，不压硬菜",
            "menu": "白灼菜心\n红烧肉\n水煮鱼\n米饭",
            "people": [{"name": "我", "chips": ["辣"]}],
            "mode": "work",
            "want": {"order": ["白灼菜心:先上", "红烧肉:硬菜", "米饭:主食", "水煮鱼:硬菜"]},
        },
        {
            "name": "新菜上桌与忌口",
            "menu": "油焖大虾\n红烧狮子头\n韭菜盒子\n海带豆腐汤\n醋溜土豆丝\n蒜泥茄子",
            "people": [{"name": "我", "chips": ["海鲜", "蒜"]}],
        },
        {
            "name": "新菜重复主料与补缺",
            "menu": "糖醋里脊\n京酱里脊丝\n木须肉\n牛肉面\n鲫鱼豆腐汤\n海带豆腐汤",
            "people": [{"name": "我", "chips": ["牛羊肉"]}],
        },
        # 散文菜单：整句当菜名是笑话，「有人不吃辣」被丢掉是把人吃坏的错。
        # want 钉的是产品预期——两端一起漂回去（比如把 NOTE_RE 拆了）也要炸。
        {
            "name": "散文菜单：菜和话分开，话里的忌口要算",
            "menu": "周五晚上三个人来吃饭，准备番茄牛腩、清炒时蔬、蒜蓉虾，还有一个凉拌黄瓜。有人不吃辣，另外一个对海鲜有点忌讳。",
            "people": [{"name": "我", "chips": []}, {"name": "同行", "chips": []}],
            "want": {
                "notes": ["周五晚上三个人来吃饭", "有人不吃辣", "对海鲜有点忌讳"],
                "chipBans": [],
                "bans": ["辣", "海鲜"],
                "inferred": ["辣|有人不吃辣", "海鲜|对海鲜有点忌讳"],
            },
        },
        {
            "name": "散文菜单：爱吃辣不是忌辣",
            "menu": "米饭\n宫保鸡丁\n他最爱吃辣",
            "people": [{"name": "我", "chips": []}],
            "want": {"notes": ["他最爱吃辣"], "bans": [], "inferred": []},
        },
        # 转折：整句一起判会连「不吃香菜」那半句一起放过，那正是这一桌的雷
        {
            "name": "散文菜单：不吃香菜但爱吃辣",
            "menu": "清炒时蔬\n不吃香菜但爱吃辣",
            "people": [{"name": "我", "chips": []}],
            "want": {"bans": ["香菜"], "inferred": ["香菜|不吃香菜"]},
        },
        # 空格与括号：整行被当成一句话时，三道菜一道没算，而句里的「牛腩」「蒜蓉」
        # 反倒被当成忌牛忌蒜——两头都错。
        {
            "name": "散文菜单：空格分开的三道 + 括号里的过敏",
            "menu": "番茄牛腩 蒜蓉虾 清炒时蔬（有人对虾过敏）",
            "people": [{"name": "我", "chips": []}],
            "want": {"notes": ["有人对虾过敏"], "bans": ["海鲜"],
                     "inferred": ["海鲜|有人对虾过敏"]},
        },
        # 排桌人数：n*0.5 落在 x.5 上时（n=5/9/13），Python 的 round() 会往偶数收，
        # JS 的 Math.round() 四舍五入向上——5 人桌曾一个要 8 道一个要 10 道。
        # 产品口径是家常的「宁可多一道」，所以取向上；want 把它钉死，两端一起改错也炸。
        {"name": "5 人桌（半整数陷阱）", "menu": "米饭",
         "people": [{"name": f"p{i}", "chips": []} for i in range(5)],
         "want": {"want": {"荤": 4, "素": 3, "汤": 1, "主食": 2}, "total": 10}},
        {"name": "9 人桌（半整数陷阱）", "menu": "米饭\n小炒肉",
         "people": [{"name": f"p{i}", "chips": []} for i in range(9)],
         "want": {"want": {"荤": 6, "素": 5, "汤": 1, "主食": 2}, "total": 14}},
        {"name": "13 人桌（半整数陷阱）", "menu": "",
         "people": [{"name": f"p{i}", "chips": []} for i in range(13)],
         "want": {"want": {"荤": 8, "素": 7, "汤": 1, "主食": 2}, "total": 18}},
        {"name": "1 人桌", "menu": "白灼菜心", "people": [{"name": "我", "chips": []}],
         "want": {"want": {"荤": 1, "素": 1, "汤": 0, "主食": 1}, "total": 3}},
        {"name": "2 人桌", "menu": "白灼菜心", "people": [{"name": "我", "chips": []}, {"name": "对象", "chips": ["清淡"]}]},
        {"name": "4 人桌", "menu": "白灼菜心\n米饭", "people": [{"name": f"p{i}", "chips": []} for i in range(4)],
         "want": {"want": {"荤": 3, "素": 2, "汤": 1, "主食": 1}, "total": 7}},
        {"name": "0 人（回落 1 人）", "menu": "米饭", "people": [],
         "want": {"want": {"荤": 1, "素": 1, "汤": 0, "主食": 1}, "total": 3}},
        # 雷区理由的成分先后：JS 用 Set 插入序，Python 的 set 按哈希排，
        # 同一道菜会写成「海鲜 / 辣」和「辣 / 海鲜」两种。
        # 这一对是专门构造的：香辣虾 的成分来自 HIDDEN（辣 先声明），麻酱虾 的辣只由
        # CHIP_MAP 补上（海鲜 先入）。正确实现下两句必然一正一反；谁退回用 set 迭代，
        # 两道菜就塌成同一个顺序，总有一句对不上——不依赖哈希碰运气。
        {
            "name": "雷区理由先后（一对反序，哈希序必炸）",
            "menu": "香辣虾\n麻酱虾",
            "people": [{"name": "我", "chips": ["海鲜", "辣"]}],
            "want": {"boom": ["香辣虾|辣 / 海鲜|荤", "麻酱虾|海鲜 / 辣|荤"]},
        },
        {
            "name": "雷区两个成分的先后（辣在前）",
            "menu": "香辣虾\n毛血旺",
            "people": [{"name": "我", "chips": ["海鲜", "辣"]}],
        },
        {
            "name": "雷区两个成分的先后（chips 反序）",
            "menu": "香辣虾\n毛血旺",
            "people": [{"name": "我", "chips": ["辣", "海鲜"]}],
        },
        {
            "name": "谨慎层理由（没人忌口的隐藏成分）",
            "menu": "啤酒鸭\n腰果西芹\n双皮奶",
            "people": [{"name": "我", "chips": []}],
        },
        # 扣肉：菜名没写「梅菜」也还是猪肉。HIDDEN 与 CHIP_MAP 两处都得认。
        {"name": "扣肉算猪肉（无忌口 → 谨慎）", "menu": "扣肉\n米饭", "people": [{"name": "我", "chips": []}]},
        {"name": "扣肉算猪肉（忌猪肉 → 雷区）", "menu": "扣肉\n米饭", "people": [{"name": "我", "chips": ["猪肉"]}]},
        {"name": "梅菜扣肉与芽菜扣肉", "menu": "梅菜扣肉\n芽菜扣肉", "people": [{"name": "我", "chips": ["猪肉"]}]},
        # 菜库的 tags 也是成分来源：小笼包 / 干煸四季豆 的名字里不含原料字，
        # HIDDEN 与 CHIP_MAP 都认不出，只有 DISHES 这张表知道。以前只读前两处，
        # 于是忌猪肉的人看到「小笼包 · 全员安全」。want 钉死结论，两端一起改错也炸。
        {"name": "菜库 tags 认回成分（忌猪肉 → 雷区）", "menu": "小笼包\n米饭",
         "people": [{"name": "我", "chips": ["猪肉"]}],
         "want": {"boom": ["小笼包|猪肉|主食"], "risk": [], "safe": ["米饭"]}},
        {"name": "菜库 tags 认回成分（两个成分的先后）", "menu": "干煸四季豆\n小笼包",
         "people": [{"name": "我", "chips": ["辣", "猪肉"]}],
         "want": {"boom": ["干煸四季豆|辣 / 猪肉|素", "小笼包|猪肉|主食"], "risk": [], "safe": []}},
        {"name": "菜库 tags 无忌口时走谨慎层", "menu": "小笼包\n米饭",
         "people": [{"name": "我", "chips": []}],
         "want": {"boom": [], "risk": ["小笼包|猪肉|主食"], "safe": ["米饭"]}},
        # 忌「清淡」这一层：只看菜名的话，「香辣土豆丝」进雷区而「手撕包菜」只算谨慎——
        # 同一样成分（辣）因为名字的写法落进不同一层。菜库说它辣，就算它辣。
        {"name": "忌清淡读菜库的辣（不看菜名写法）", "menu": "手撕包菜\n干煸四季豆\n白米饭",
         "people": [{"name": "我", "chips": ["清淡"]}],
         "want": {"boom": ["手撕包菜|清淡|素", "干煸四季豆|清淡|素"], "risk": []}},
        # 菜库的数据本身：三杯鸡的「三杯」是米酒 / 酱油 / 麻油各一杯；海带与紫菜同为藻类，
        # 从前只标了紫菜那一道。忌酒（吃头孢）的人漏一道就是真会出事的那种错。
        {"name": "三杯鸡含酒", "menu": "三杯鸡\n白米饭",
         "people": [{"name": "我", "chips": ["酒"]}],
         "want": {"boom": ["三杯鸡|酒|荤"], "safe": ["白米饭"]}},
        {"name": "两道藻类同一判法（海带从前漏了）", "menu": "海带豆腐汤\n紫菜蛋花汤",
         "people": [{"name": "我", "chips": ["海鲜"]}],
         "want": {"boom": ["海带豆腐汤|海鲜|汤", "紫菜蛋花汤|海鲜|汤"]}},
        {"name": "涮羊肉与烤羊腰", "menu": "涮羊肉\n烤羊腰", "people": [{"name": "我", "chips": ["牛羊肉"]}]},
        {"name": "凉拌花生与凉拌香菜", "menu": "凉拌花生\n凉拌香菜", "people": [{"name": "我", "chips": ["花生", "香菜"]}]},
        {"name": "未知忌口词（不在 CHIP_MAP 里）", "menu": "香菜面\n芡实糕", "people": [{"name": "我", "chips": ["芡实"]}]},
        # 「爆」是旺火速成，跟红烧/干锅一样压得住桌尾——葱爆羊肉从前被排成「主菜」
        {
            "name": "爆炒归硬菜",
            "menu": "葱爆羊肉\n酱爆鸡丁\n清炒时蔬\n米饭",
            "people": [{"name": "我", "chips": []}],
            "want": {"order": ["清炒时蔬:清口", "葱爆羊肉:硬菜", "酱爆鸡丁:硬菜", "米饭:主食"]},
        },
    ],
    "yan": [
        {
            "name": "五句混合",
            "text": "明天下午记得把材料发我。\n药快没了帮我买一盒。\n那就周五见吧。\n时间再说。\n快递到了你拿一下。",
        },
        {
            "name": "带日期与人名",
            "text": "小王让我周四前把报价发过去。\n9月28日要交房租。\n别忘了买牛奶。",
        },
        {
            "name": "有日期的「把 X 做掉」：以前整句被丢掉，两端一起认回来",
            "text": "周五把合同寄出。\n月底把报销单交了。\n明天把伞带上。",
        },
        {
            "name": "全是闲聊",
            "text": "今天天气不错。\n哈哈这个好玩。",
        },
        {
            "name": "说话人：正例与防误伤",
            "text": "小红：明天开会。\n明天：交房租。\n要买：洗衣液和纸巾。\n小王说：记得把发票发我。",
        },
        {
            "name": "说话人：冒号前缀边界",
            "text": "下周三：例会。\n月底：交房租记得别拖。\n欧阳老师：明天交材料。\n小李:下午取快递。\n礼拜五：取件。\n十月一日：记得值班。",
        },
        # 卡片上盖了「小王」那枚签，追问再念一遍「小王：」就成了两个人在说话。
        # line 仍是原话（复制整张笺要它），只有引用去掉了前缀——want 把这条钉死，
        # 光比两端是比不出「两端一起把前缀留在引用里」的。
        {
            "name": "追问引用不带说话人前缀",
            "text": "小王：下周项目要评审了，材料我周三之前给你。\n老李：预算还没定，再看看。",
            "want": {"ask": "「预算还没定，再看看」这件事，时间定在哪天？"},
        },
        # 追问是念给用户听的一句短话：整句抄回来会把那一屏撑满，读的人找不到重点
        {
            "name": "长待办的追问截断",
            "text": "明天下午三点之前把这份三百页的附件里的第三章和第五章的表格全部核对一遍并且发给王总另外抄送财务。",
            "want": {"ask": "「明天下午三点之前把这份三百页的附件里的第三…」谁来做、什么时候？"},
        },
        {
            "name": "who 停用词：时间再说不出人名",
            "text": "时间再说周五交稿。\n回头说一声。\n小王再说一遍。",
        },
        {
            "name": "who 贪心捕获剥离连接副词",
            "text": "小王再说一遍。\n时间再说。\n他又让我去拿。\n欧阳才说周五要交稿。\n小王说记得周五交稿。",
        },
        # 「今天晚上」该念成「今晚」。gateway 早先只判断 今天/今日/今晚，会写成「今天」。
        {"name": "今天晚上＝今晚", "text": "今天晚上记得吃面。"},
        {"name": "今晚 / 今天 分开", "text": "今晚加班。\n今天记得带伞。\n今日值班。"},
        # 不存在的日期：钳到当月最后一天，文案与时间戳必须自洽。
        # 早先 JS 的 new Date(y,m,31) 静默滚到下个月却还写原来的月日；Python 直接 ValueError。
        {"name": "2月31日钳到月末", "text": "记得2月31日前把年报交了。"},
        {"name": "6月31日与12月32号", "text": "记得6月31日搬家。\n12月32号再说。"},
        {"name": "闰日 2月29日", "text": "记得2月29日体检。"},
        {"name": "裸日号溢出当月", "text": "31日记得交材料。"},
        {"name": "裸日号就是今天", "text": "5日记得交房租。"},
        {"name": "月份越界不算时间", "text": "记得99月5日开会。"},
        {"name": "月底 / 月末", "text": "月底记得交房租。\n月末我要请假。"},
        {"name": "下周与本周", "text": "下周三开会。\n这周五交稿。\n本周日值班。\n礼拜六聚餐。"},
        {"name": "明天与后天与大后天", "text": "明天交A。\n后天交B。\n大后天交C。\n明日交D。"},
    ],
    "season": [
        {"name": "手选优先于推断", "w": {"cat": "上衣", "name": "白短袖T恤", "season": "冬"}, "want": "冬"},
        {"name": "手选四季原样返回", "w": {"cat": "裤装", "name": "深蓝阔腿", "season": "四季"}, "want": "四季"},
        {"name": "短袖推断夏", "w": {"cat": "上衣", "name": "白短袖T恤"}, "want": "夏"},
        {"name": "凉鞋推断夏", "w": {"cat": "鞋", "name": "细带凉鞋"}, "want": "夏"},
        {"name": "羽绒服推断冬", "w": {"cat": "外套", "name": "长款羽绒服"}, "want": "冬"},
        {"name": "针织推断冬", "w": {"cat": "上衣", "name": "燕麦针织"}, "want": "冬"},
        {"name": "非法 season 回落推断", "w": {"cat": "上衣", "name": "吊带", "season": "夏天"}, "want": "夏"},
        {"name": "无线索回落春秋", "w": {"cat": "裤装", "name": "深蓝阔腿"}, "want": "春秋"},
        {"name": "四季不由词表猜出", "w": {"cat": "上衣", "name": "四季可穿衬衫"}, "want": "春秋"},
    ],
}

pass_n = fail_n = 0


def check(name, a, b):
    global pass_n, fail_n
    if a == b:
        pass_n += 1
        print(f"  ok   {name}")
        return True
    fail_n += 1
    print(f" FAIL  {name}")
    if isinstance(a, dict) and isinstance(b, dict):
        # 遍历两边 key 的并集，任何一边多出字段也能发现
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                print(f"          {k}:  engine={a.get(k)!r}")
                print(f"          {k}: gateway={b.get(k)!r}")
    else:
        print(f"          engine={a!r}")
        print(f"          gateway={b!r}")
    return False


# ---------- 归一化：两端各跑各的，比之前都过一遍这里 ----------
# 每个字段都要取。上一轮漏了 boom 的 why、整个 risk、plan 的 want/total，
# 于是「理由先后」「几道菜」两类漂移在 28 项全绿的情况下活了下来。

def norm_yi(r):
    b = r.get("basis")
    match = [{"name": m.get("name"), "cat": m.get("cat"), "gap": m.get("gap")}
             for m in (r.get("match") or [])]
    return {
        "stamp": r["stamp"],
        "quote": r["quote"],
        "gap": r["gap"],
        "sameCat": bool(r.get("sameCat")),
        "stale": bool(r.get("stale")),
        "seasonal": bool(r.get("seasonal")),
        "basis": None if not b else {
            "name": b.get("name"), "cat": b.get("cat"), "gap": b.get("gap"),
            "wear": b.get("wear"), "wearShort": b.get("wearShort"),
            "seasonal": bool(b.get("seasonal")), "worn": b.get("worn"),
            "lastWorn": b.get("lastWorn"),
        },
        "match": match,
        "close": [c.get("name") for c in (r.get("close") or [])],
        # 柜子的厚度：界面上那句「判定还薄」就是它说的，两端不一致就会一个说一个不说
        "thin": bool(r.get("thin")), "closetN": r.get("closetN"),
        # 冷暖调这一句会印在笺上（屏幕、长图、复制话术共用），两端各说一句就露馅了
        "toneLine": r.get("toneLine") or "",
    }


def norm_wei(r):
    return {
        "safe": r["safe"],
        "boom": [f"{x['dish']}|{x['why']}|{x['kind']}" for x in r["boom"]],
        "risk": [f"{x['dish']}|{x['why']}|{x['kind']}" for x in r["risk"]],
        "suggest": r["suggest"],
        "kinds": r["kinds"],
        "want": r["plan"]["want"],
        "gap": r["plan"]["gap"],
        "total": r["plan"]["total"],
        "add": [f"{x['kind']}:{x['name']}" for x in r.get("add", [])],
        "dupes": [f"{x['main']}={'+'.join(x['dishes'])}" for x in r.get("dupes", [])],
        "order": [f"{x['dish']}:{x['label']}" for x in r.get("order", [])],
        "hasMenu": r["hasMenu"],
        # 散文分词新增的四项：菜/话分离的结果和从话里捞出的忌口。不比对它们，
        # 一端把「有人不吃辣」当菜、另一端不当，两边各自内部还是绿的。
        "bans": r.get("bans"), "chipBans": r.get("chipBans"),
        "notes": r.get("notes"),
        "inferred": [f"{x['chip']}|{x['from']}" for x in r.get("inferred") or []],
    }


YAN_KEYS = ["待办", "要买", "已定", "还没说清"]


def norm_yan(r):
    items = []
    for k in YAN_KEYS:
        for x in r.get(k) or []:
            w = x.get("when")
            items.append("|".join([
                k, x["line"],
                w["text"] if w else "-",
                str(w["at"]) if w else "-",       # 时间戳也要对：光对文案看不出溢出的月份
                x.get("who") or "-", x.get("speaker") or "-",
            ]))
    return {"items": items, "ask": r["ask"], "total": r["total"]}


# ---------- 时钟钉死 ----------

def pin_gateway(g):
    """让 gateway 里的 time.time() / datetime.now() 都返回 PIN。
    gateway 只用 g.time.time() 和 g.datetime，绑到模块命名空间上就能整体替换。"""
    g.time = types.SimpleNamespace(time=lambda: PIN_MS / 1000.0)

    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return PIN_DT

    g.datetime = PinnedDatetime


# ---------- 全表对账 ----------

def diff_tables(a, b, path=""):
    """返回 [(路径, engine 值, gateway 值)]，只报前几处，够定位就行。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in a:
                out.append((f"{path}.{k}", "<缺键>", b[k]))
            elif k not in b:
                out.append((f"{path}.{k}", a[k], "<缺键>"))
            else:
                out += diff_tables(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((f"{path}[长度]", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_tables(x, y, f"{path}[{i}]")
    elif a != b:
        out.append((path, a, b))
    return out


def check_tables(js_tables, g):
    """词表 / 正则 / 阈值整张表对账，键序也算（HIDDEN 的声明顺序决定理由的先后）。"""
    ok = check("tables.HIDDEN 全表同字同序",
               list(js_tables["HIDDEN"].items()), list(g.TABLES["HIDDEN"].items()))
    if not ok:
        for p, x, y in diff_tables(js_tables["HIDDEN"], g.TABLES["HIDDEN"])[:8]:
            print(f"          {p}: engine={x!r} gateway={y!r}")
        # 单独把「只在一边有的键」列出来，比逐字节 diff 好读
        only_js = [k for k in js_tables["HIDDEN"] if k not in g.TABLES["HIDDEN"]]
        only_py = [k for k in g.TABLES["HIDDEN"] if k not in js_tables["HIDDEN"]]
        if only_js:
            print(f"          只有 engine 有: {only_js}")
        if only_py:
            print(f"          只有 gateway 有: {only_py}")

    check("tables.CHIP_MAP 全表同字同序",
          list(js_tables["CHIP_MAP"].items()), list(g.TABLES["CHIP_MAP"].items()))
    check("tables.DISHES 菜库全表同字同序",
          js_tables["DISHES"], g.TABLES["DISHES"])
    check("tables.MAINS 主料表同字同序", js_tables["MAINS"], g.TABLES["MAINS"])

    jre, pre = js_tables["RE"], g.TABLES["RE"]
    for name in sorted((set(jre) | set(pre)) - {"KINDS"}):
        check(f"tables.RE.{name} 正则逐字一致", jre.get(name), pre.get(name))
    check("tables.RE.KINDS 言笺四类关键词同字同序", jre.get("KINDS"), pre.get("KINDS"))

    jnum, pnum = js_tables["NUM"], g.TABLES["NUM"]
    for name in sorted(set(jnum) | set(pnum)):
        check(f"tables.NUM.{name} 阈值一致", jnum.get(name), pnum.get(name))


def main():
    global pass_n, fail_n
    node = shutil.which("node")
    if not node:
        print("找不到 node，跳过一致性检查")
        return 0
    CASES_FILE.write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [node, str(ROOT / "test" / "_engine_dump.mjs"), str(CASES_FILE)],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "JIAN_PIN_MS": str(PIN_MS)},
    )
    if proc.returncode != 0:
        print("engine.js 执行失败：\n" + (proc.stderr or ""))
        return 1
    js = json.loads(proc.stdout)
    if js.get("pin") != PIN_MS:
        print(f" FAIL  engine.js 没吃住钉住的时钟（engine={js.get('pin')} 期望={PIN_MS}），"
              "两端时间不一致，后面的比对不算数")
        return 1

    sys.path.insert(0, str(ROOT / "backend"))
    import gateway as g
    pin_gateway(g)

    print(f"时钟钉在 {PIN_DT:%Y-%m-%d %H:%M}（本地）\n")

    for i, c in enumerate(CASES["yi"]):
        b = norm_yi(g.yi({"item": c["item"], "wardrobe": c["wardrobe"]}))
        b["seasons"] = [g.season_of(c["item"])] + [g.season_of(w) for w in c["wardrobe"]]
        a = norm_yi(js["yi"][i])
        a["seasons"] = js["yi_seasons"][i]
        check(f"[yi] {c['name']}", a, b)

    for i, c in enumerate(CASES["wei"]):
        a, b = norm_wei(js["wei"][i]), norm_wei(g.wei({
                "menu": c["menu"], "people": c["people"], "mode": c.get("mode") or ""}))
        if not check(f"[wei] {c['name']}", a, b):
            continue
        # 两端一起漂到同一个错答案时，比两端是比不出来的：带 want 的用例还要等于预期
        for field, expected in (c.get("want") or {}).items():
            if b.get(field) != expected:
                fail_n += 1
                print(f" FAIL  [wei] {c['name']} 两端一致但不符合预期：{field}={b.get(field)!r} != {expected!r}")
            else:
                pass_n += 1

    for i, c in enumerate(CASES["yan"]):
        a, b = norm_yan(js["yan"][i]), norm_yan(g.yan({"text": c["text"]}))
        if not check(f"[yan] {c['name']}", a, b):
            continue
        # 追问那一句话两端一起改错也是错：带 want 的用例还要等于产品预期
        for field, expected in (c.get("want") or {}).items():
            if b.get(field) != expected:
                fail_n += 1
                print(f" FAIL  [yan] {c['name']} 两端一致但不符合预期：{field}={b.get(field)!r} != {expected!r}")
            else:
                pass_n += 1

    # seasonOf 对账小节：两端一致只是下限，还得等于产品预期（两端一起漂也要炸）。
    js_season = js.get("season") or []
    for i, c in enumerate(CASES["season"]):
        a = js_season[i] if i < len(js_season) else None
        b = g.season_of(c["w"])
        if not check(f"[season] {c['name']}", a, b):
            print(f"          want={c.get('want')!r}")
        elif a != c.get("want"):
            # 两端一起漂到同一个错答案，光比两端是比不出来的
            fail_n += 1
            print(f" FAIL  [season] {c['name']} 两端一致但不符合预期：{a!r} != {c.get('want')!r}")
        else:
            pass_n += 1

    if js.get("tables"):
        check_tables(js["tables"], g)
    else:
        check("[tables] engine.js 导出了 TABLES", False, True)

    print(f"\n两端一致性：{pass_n} 通过 / {fail_n} 失败")
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
