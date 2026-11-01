# 算力网关约定

业务只调 `JianAPI.yi / wei / yan / hear`。
`config.js` 的 `endpoint` 为空 → 本地 `engine.js`。
填了地址 → POST JSON，失败自动回落本地。

`backend/gateway.py` 是同一套约定的本地实现。

> **两端的判定口径必须一致。** 改 `engine.js` 的规则时同步改 `gateway.py`，
> 然后跑 `python test/consistency.py`——它会拿同一批输入比对两端结论，漂了会先炸。

## POST {endpoint}/v1/see

```json
{ "task": "yi", "item": { "name": "想买的这件", "cat": "上衣", "color": "#d8d2c6" },
  "wardrobe": [{ "name": "燕麦针织", "cat": "上衣", "color": "#d4c4b0", "season": "冬" }] }
```

返回：

```json
{
  "stamp": "宜入 | 再想想 | 先别",
  "quote": "柜里没有这个色，能和 3 件旧的搭上。",
  "close": [{ "name": "燕麦针织", "cat": "上衣", "color": "#d4c4b0" }],
  "match": [{ "name": "深蓝阔腿", "cat": "裤装", "color": "#2c3a4a", "gap": 41 }],
  "gap": 8,
  "stale": false,
  "basis": {
    "name": "燕麦针织", "cat": "上衣", "gap": 8,
    "wear": "那件 2 天前刚穿过。", "wearShort": "2 天前穿过",
    "worn": 9, "lastWorn": 1789000000000
  }
}
```

- `gap` 与 `basis` 是感知色差（CIE Lab ΔE）和最近邻，用于报告页附注与长图。
- `match` 是**能配**的件：不同品类、颜色协调的，最多 3 件。
- `basis.wear` 来自柜子的穿着记录；`lastWorn` 是毫秒时间戳，`worn` 是次数。
  当 `stale` 为真（半年没穿）时，前端会换一套更直接的金句。
- 判定口径：同品类 ΔE<22 → 先别；<45 → 再想想；跨品类 ΔE<14 → 再想想；否则宜入。
- 衣柜件可带 `"season": "夏 | 春秋 | 冬 | 四季"`（用户手选优先）。缺省时网关按 `seasonOf` / `season_of`
  同口径从「品类名+名称」推断（夏：短袖/背心/吊带/凉鞋/拖鞋/短裤/雪纺；冬：羽绒/大衣/棉服/毛衣/针织/靴/卫衣/加绒…；其余春秋）。
  「四季」只来自手选，不由词表猜；非法值回落推断。本次季节不进 `yi` 判定，仅供后续使用。
- 前端只强制要求 `stamp` 与 `quote` 存在，缺 `gap` / `basis` / `match` 也能跑。

## POST {endpoint}/v1/complete

味：`{ "task": "wei", "menu": "...", "people": [{ "name": "我", "chips": ["花生"] }], "mode": "friends" }`

返回：

```json
{
  "safe": ["白切鸡"],
  "risk": [{ "dish": "蒜蓉西兰花", "why": "蒜", "kind": "素" }],
  "boom": [{ "dish": "宫保鸡丁", "why": "花生", "kind": "荤" }],
  "suggest": ["白切鸡"],
  "kinds": { "荤": 4, "素": 2, "汤": 1, "主食": 1, "其他": 0 },
  "plan": { "want": { "荤": 3, "素": 2, "汤": 1, "主食": 1 }, "gap": {}, "total": 7 },
  "add": [{ "kind": "素", "name": "清炒时蔬" }],
  "dupes": [{ "main": "鸡", "dishes": ["宫保鸡丁", "白切鸡"] }],
  "order": [{ "dish": "宫保鸡丁", "stage": 3, "label": "主菜" }],
  "hasMenu": true
}
```

- `kinds` / `plan` 用于"排桌"区块。`plan.want` 是家常口径的建议道数（人数 × 0.5 四舍五入向上，
  4 人以上荤再加一道，**宁可多一道**）；`gap` 只列还差的那几类。
- `order` 是**上菜顺序**（`stage` 1 先上 / 2 清口 / 3 主菜 / 4 硬菜 / 5 汤 / 6 主食），前端会渲染。
- `boom` / `risk` 的 `why` 是**多个成分按固定顺序**用 ` / ` 拼的（如 `"辣 / 海鲜"`）。
  顺序由词表声明序决定，两端必须一样，不要按集合哈希排。
- `add` 是按缺口推荐的具体菜（已避开全桌忌口与桌上已有的菜），前端点一下会加进菜单。
  家常菜库（DISHES/MAINS/上菜阶段正则）两端同表：本次已扩充至 63 道（荤/素/汤/主食全覆盖），tags 只用既有忌口词，不要另造新词。
- `dupes` 是主料重复提醒。
- 前端对这几项都是可选的，缺了就自动降级只显示 `safe` / `boom`。

言：`{ "task": "yan", "text": "..." }`

返回：

```json
{
  "待办":     [{ "line": "明天下午记得把材料发我", "when": { "text": "明天", "at": 1789120066080 }, "who": null, "speaker": null }],
  "要买":     [{ "line": "药快没了帮我买一盒", "when": null, "who": null, "speaker": null }],
  "已定":     [],
  "还没说清": [],
  "ask": "「…」这件事，时间定在哪天？",
  "total": 2
}
```

- 四类的值统一为**对象数组**。前端 `normCards()` 兼容旧的纯字符串数组写法，所以老网关不会崩。
- `when.at` 是毫秒时间戳；`who` 只在明确指认（某某说 / 让我 / 叫我）时才给，
  且前缀含时间/转场停用词（时间|时候|现在|回头|等下|再说|大家|我们|你们|他们）时为 `null`，防止「时间再说…」误判出人名。
  贪心捕获会把「小王再说」吃成「小王再」：末尾的连接副词（再/又/还/也/就/才/都/先）会被剥掉——「小王再说一遍」给 `"小王"`；剥后不足两字（「他又让我…」）不给。
- 每张卡片带 `speaker`（这句话是谁说的）：行首「某某：」的冒号前缀（1-4 个汉字，全角/半角冒号均可）。
  防误伤：前缀是时间词（明天：、月底：、周三：、礼拜五：、十月一日：…）或功能标签（要买|待办|提醒|注意|备注）时为 `null`。
  前缀原样返回、不改写（「小王说：」会给 `"小王说"`）；要纯人名用 `who`。`line` 保持原文不去前缀。
- `when.text` 与 `when.at` **必须自洽**：不存在的日期（2月31日、6月31日）钳到当月最后一天，
  文案跟着写钳位后的月日（`2月28日`）；月份或日期越界（99月5日、12月32号）当作**没抽到时间**，`when` 给 `null`。
  绝对日期（月日 / 裸日号 / 月底）落在本地零点，相对日期（明天 / 下周三）保住当前时刻。

## 错误与兜底

| 情况 | 返回 |
|---|---|
| body 不是合法 JSON / 不是对象 | `400 {"error": "…"}` |
| 判定过程抛异常 | `500 {"error": "类型: 消息"}` |
| 模型没配 / 连不上 / 回的东西不能用 | `502 {"error": 代码, "message": 人话}` |
| 没带图、图小得不像照片 | `400 {"error": "noimage" \| "tinyimage"}` |
| `/v1/complete` 收到不认识的 `task` | `400 {"error": "badtask"}`（不填 `task` 仍按味笺走） |
| 路径不在 `/v1/see`、`/v1/complete`、`/v1/hear`、`/v1/recognize`、`/v1/ocr`、`/v1/status` 里 | `404 {"error": "unknown"}` |

**网关出错一定要回一个像样的 HTTP 状态码，不能让连接被掐掉。** `api.js` 对「连接中断」和
「`!res.ok`」都是 `catch` 之后静默回落本地引擎——界面上一切正常，你以为在走模型，其实一直在跑本地规则。
路由按**路径**分流，`task` 只在 `/v1/complete` 里区分味 / 言；`test/gateway_http.py` 守着上面这张表。

## POST {endpoint}/v1/hear

语音转写。没有能转写的模型时回一句说明（`needText: true`）。

**这一条应用侧已经不调了**：第 34 轮把「放录音」那枚按钮删掉之后，前端没有任何入口收音频
（`api.js` 里那个 `hear()` 一起删的），所以屏幕上不会再有这句话被念给用户的机会。
网关这一侧仍然应答，是为了不砸自建脚本和旧客户端；**别把它当成一条界面上走得通的路**。
要让用户说一段话进来，目前的正路是：手机自己的听写转成文字 → 贴进言笺那个框。

### GET {endpoint}/v1/status 的 `tasks`（自建网关请看这一小段）

除了 `model`，`/v1/status` 还回一张 `tasks` 布尔表：

```json
{"ok": true, "model": {"on": true, "model": "agnes-2.5-flash"},
 "tasks": {"yi": true, "wei": true, "yan": true, "recognize": true, "ocr": true}}
```

`recognize` / `ocr` 决定「我的」那一屏怎么说这两件事：**`true` 说可用，`false` 说不行，字段缺了说
「没自述」**——第三种不是含糊，是因为你换了一台第三方网关、它没打算报这个，程序不该替它充好。
只挂了聊天模型的网关如果报 `recognize: true`，用户就会去按一件必然回落本机的按钮。
`yi` / `wei` / `yan` 三条是判定本身，本地引擎永远兜得住，所以内置网关一律 `true`。
（第 32 轮之前这两个布尔被记下来却没人读；第 37 轮之前「缺字段」被界面念成「可用」。）

## POST {endpoint}/v1/recognize 与 /v1/ocr（要模型）

这两条是唯一真的调外部模型的路。**密钥只在网关那一侧**（环境变量），应用包里永远没有。

```json
{ "image": "data:image/jpeg;base64,…" }
```

`/v1/recognize` → `{"name":"针织开衫","cat":"外套","color":"#c9b89a","season":"春秋","source":"model","model":"agnes-2.5-flash"}`
`/v1/ocr` → `{"text":"明天下午记得把材料发我\n那就周五见吧。","model":"…"}`

- 前端上传前先把图缩到 512 边（`JianAPI.shrink`），网关那边还有一道 `JIAN_MAX_BODY`（默认 8MB）的闸。
- **主色不用模型给的**：像素就在本机，`Engine.analyze` 量的比模型猜的准（实测同一张米色针织衫，
  本机量到 `#b69f88`，模型报 `#c9b89a` / `#d3b484` 两档都有）。模型负责「这是什么、算哪类、什么季」，
  判定仍然走本地那套规则——两端一致性的所有保证因此继续成立。
- 模型不守格式是常态，`backend/llm.py` 全部要夹：` ```json ` 围栏、把提示里的枚举原文整段抄回来
  （实测 `season` 收到过 `"春秋|冬|四季"`）、非六位色值、`1. ` 前缀与成对引号。
- 出错回 **502 + `{"error": 代码, "message": 人话}`**，前端据此回落并在「册」里说原因。
  绝不回 200 空壳——那会被当成「模型说这件衣服没有颜色」。

### 模型侧的环境变量（都在网关进程，不进仓库）

```
JIAN_LLM_BASE=https://api.agnes-ai.cn/v1     # OpenAI 兼容的 /chat/completions
JIAN_LLM_KEY=…
JIAN_LLM_MODEL=agnes-2.5-flash               # 或智谱 glm-4v-flash
JIAN_LLM_TIMEOUT=15
JIAN_MAX_BODY=8388608
```

没配这三样时 `/v1/status` 报 `model.on = false`，`/v1/recognize` 直接 502 `unconfigured`，
判定三条路照旧可用——「接了网关」和「能看图」是两件事，界面上分开说。

### 实测过的模型行为（2026-09-21，两张真图）

| 模型 | 认衣服 | 抄聊天截图 |
|---|---|---|
| `agnes-2.5-flash`（.cn） | 1.1~5 秒，品类/名字对，色偏亮一档 | 2.4~2.6 秒，七句全中、**原序** |
| `glm-4v-flash`（智谱） | 1.2~2.7 秒，同上 | 顺序会打乱；`max_tokens>1024` 直接 400 |
| `agnes-3.0-flash` | 60 秒超时（两家都一样） | — |
| `glm-4.5v` / `agnes-2.5-flash`（.com） | content 空、`finish_reason=length`：思考占满预算 | — |

所以 `llm.py` 里那两条不像样子的代码是有原因的：发 `"thinking": {"type":"disabled"}`，
以及 content 为空时从 `reasoning_content` 里捞一次 JSON。

## 鉴权

`Authorization: Bearer {key}`（可选）。
密钥只应出现在网关那一侧的环境变量里，不要写进应用包发给用户。

> 前端 `Engine.analyze()` 的图像特征（主色、花色、冷暖）只在本地算，不上传。
> 走 `/v1/recognize` 时上传的是**缩过的**照片本身——这是唯一会离开设备的图像数据，
> 而且只在用户填了网关地址、并且主动拍照/选图的时候发生。

本地实现：`python backend/gateway.py`，默认只听 `127.0.0.1:8787`。

- **桌面 H5**：在「我的」填 `http://127.0.0.1:8787` 就够了。
- **手机要连**：得 `set JIAN_HOST=0.0.0.0` 再起，网关会把它自己的局域网地址打出来，手机上填那个。
  默认不开，是因为这台机器上跑的是用户的衣柜照片和聊天记录——「起了个网关」不等于「对整条街敞开」。
- **APK 里填 `http://127.0.0.1:8787` 一定没用**：那是手机自己的回环。模拟器同理要用 `http://10.0.2.2:8787`。
  安卓壳这一侧要两道闸同时开着，缺一层设备上就只剩一句「网关连不上：Failed to fetch」：
  · `android/app/src/main/res/xml/network_security_config.xml` 放行明文流量
    （targetSdk 28+ 默认禁明文；实测合并后的 manifest 里原本连这份引用都没有）；
  · `capacitor.config.json` 的 `android.allowMixedContent: true`
    （壳自己的源是 `https://localhost`，往 `http://` 发请求属混合内容，Chromium 直接拦）。
  同一台模拟器逐层关掉量过：开+关 → 连不上，关+开 → 连不上，开+开 → 在线。
  `android:usesCleartextTraffic` 则确认是废话（有 NSC 时它被忽略），清单里不写，免得白招上架审查追问。
  **改完这两处一定要 `npm run cap:sync` 再构建**：APK 读的是 `android/app/src/main/assets/` 里那份
  拷贝，不 sync 就等于没改（这一条本轮真的踩过，差点据此得出反结论）。
  设备侧那条真请求在 `test/device_gateway.py`（18 项，含网关自己记到的 `/v1/status` 与
  `/v1/recognize` 两笔）；这三处配置各有守门钉着，见 `test/gateway_http.py` 末尾一节。

不要在聊天沙箱里后台挂起。

真模型跑一遍（要密钥，不进 `npm run check`）：

```
set JIAN_LLM_BASE=…  JIAN_LLM_KEY=…  JIAN_LLM_MODEL=…
python backend/gateway.py
set JIAN_GATEWAY=http://127.0.0.1:8787
python test/gateway_live.py
```

没设 `JIAN_GATEWAY` 时它以退出码 3 报「跳过」——守门全套必须能在没有网络与密钥的机器上跑完。
不依赖真供应商的那一半（假网关 + 假模型回复）在 `test/e2e.playwright.py` 第 29 节和
`test/gateway_http.py` 的模型小节里，每次都跑。
