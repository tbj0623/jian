# 笺 · 并行开发工程约定（v0.6.0 重构期，所有人必读）

> 这份文件是**并行改造期间的契约**。任何与它冲突的个人偏好都要让步。
> 读完之后再去读 `docs/HANDOVER.md`（架构事实与踩过的坑 —— 它接的正是这份文件写的规矩，
> 逐条给出事故现场与「为什么必须是现在这样」）与 `README.md`（这个 App 是什么、怎么跑）。
> 重构已经落地，这份文件现在的角色是**交接文档**：它写的是「0.6.0 之后这个仓长什么样、
> 哪些规矩是被真事故打出来的」。新来的人按它读代码，比按目录顺序读快十倍。

## 0. 一句话背景

「笺」是一个纸感（宣纸 + 印章红 + 宋体）的生活决策工具，现在是纯静态 H5 +
Capacitor 8 安卓壳，本地规则引擎，数据只落在 localStorage。
0.6.0 把它做成了**体量大、可玩性高、成熟的安卓应用**：三笺（衣/味/言）各自加深成一个
完整的模块，新增「笺谱」（热力图/统计/成就/年度总结）与重构后的「册」（个人主页 + 设置中心），
补齐了本地通知、系统分享接收、夜间模式、五枚桌面快捷方式等原生能力。

## 1. 技术形态：不许改的三件事

1. **不要引入构建步骤**。没有打包器、没有 TypeScript、没有 npm 依赖进运行时。
   `index.html` 里就是一堆传统 `<script src>`，`file://` 双击必须能跑。
2. **不要引入 ES module**（`import/export`）。`<script type="module">` 在 `file://` 下会被
   CORS 挡住。所有文件都是全局脚本，靠**加载顺序**表达依赖。
3. **不要引入框架**（React/Vue/Preact 一律不行）。所有 UI 都是模板字符串 + 事件委托。

## 2. 加载顺序 = 依赖顺序（硬约束）

```
config → engine → api → state → theme → ui → card
  → 各屏渲染文件（yi/wei/yan/me）→ v0.6 模块文件（wardrobe/cookbook/market/remind/stats/achievements/settings）
  → 接线层（wire/share）→ 今日（today）→ app（末尾 boot()）
```

实际顺序以 `index.html` 末尾那 24 行 `<script>` 为准，抄在这里是为了让人知道**意图**：

| 段 | 文件 | 为什么在这一段 |
|---|---|---|
| 底座 | `config.js` `engine.js` `api.js` | 无依赖 |
| 状态 | `state.js` | **parse 期**就执行 `normalizeState(state)` |
| 主题 | `theme.js` | 要读 `state.settings`，所以在 state 之后；它**不**在 parse 期 init（见 §4） |
| 共用件 | `ui.js` `card.js` `card-year.js` `card-long.js` | 导航/toast/长图（长图按 报告卡 / 年度 / 三张新图 分了三个文件，理由见 HANDOVER 第 1 节） |
| 老四屏 | `yi.js` `wei.js` `yan.js` `me.js` | 各自独占 |
| v0.6 模块 | `wardrobe.js` `cookbook.js` `market.js` `remind.js` `stats.js` `achievements.js` `settings.js` | 可调老四屏的函数，反过来不行 |
| 接线层 | `wire.js` `share.js` | **只做切屏/传参/复位**，不实现业务（§7） |
| 今日 | `today.js` | 要调上面所有模块的入口，排在最后一段 |
| 启动 | `app.js` | 永远最后，末尾 `boot()` |

**已经被这条打伤过两次**，都是白屏：

- `cssColor` 被从 `state.js` 挪到 `ui.js` → `normalizeState()` 在 parse 期调它 → `ReferenceError` → 整页白。
- `THEME.init()` 一度写在 `theme.js` 的 parse 期末尾 → 那时 `state` 还没从原生备份里恢复回来 →
  第一帧永远是「上次关掉之前那个主题」。现在由 `app.js` 的 `boot()` 在数据救回来**之后**调。

新增文件要同时改**三处**，漏一处就是线上少一屏（离线时尤其明显）：

1. `index.html` 的 `<script>` / `<link>`
2. `scripts/build-www.mjs` 的 `files` 白名单
3. `sw.js` 的 `SHELL` 预缓存清单

## 3. 每个文件的归属（并发写权限）

| 文件 | 谁可以写 | 说明 |
|---|---|---|
| `index.html` | **只有 Lead** | 骨架、屏幕容器、脚本引入 |
| `styles.css` | **只有 Lead** | 基础设计令牌与老组件 |
| `styles-v06.css` | **只有 Lead** | 夜纸覆盖、v0.6 通用新件、五枚底栏 |
| `state.js` | **只有 Lead** | 数据结构与钳位 |
| `ui.js` | **只有 Lead** | 导航、toast、主题、原生 chrome |
| `app.js` | **只有 Lead** | boot 与全局事件绑定 |
| `theme.js` | **只有 Lead** | 主题/字号/动效/印章款式 |
| `settings.js` | **只有 Lead** | 设置页与全局搜索 |
| `wire.js`、`share.js` | **只有 Lead** | 跨模块接线 |
| `scripts/build-www.mjs`、`sw.js`、`package.json`、`config.js`、`android/app/build.gradle` | **只有 Lead** | 版本号五副本（见 §10） |
| `engine.js` | 味笺 lane（独占） | 判定词表 + 菜库，改它必须同步 `backend/gateway.py` 与 `test/consistency.py` |
| `yi.js` | 衣笺 lane（独占） | |
| `wardrobe.js` | 衣笺 lane（独占） | |
| `wei.js` `cookbook.js` `market.js` | 味笺 lane（独占） | |
| `yan.js` `remind.js` | 言笺 lane（独占） | |
| `stats.js` `achievements.js` | 笺谱 lane（独占） | |
| `me.js` `today.js` | 今日/册 lane（独占） | |
| `card.js` | 笺谱 lane **只许追加** | 已有函数一个字节都不许改（9 处测试对着它）。2026-10 起长图拆成 `card.js` / `card-year.js` / `card-long.js` 三份（载荷门 64KB，见 HANDOVER 第 1 节） |
| `styles-<模块>.css` | 创建它的 lane | 见 §7 |

**Lead 在阶段开始时把 `state.js` 的新字段一次性加好**，各 lane 只读不写。
需要新字段 → 在共享任务里写清「需要 state.xxx」，Lead 统一加，不要自己动手。
`writeScopes` 是**建议性**的，不是锁：两个 lane 同时写一个文件不会报错，只会互相覆盖。
所以拆分时宁可多建一个文件，也不要两个人往同一个文件里加。

## 4. 数据层：state 的规矩

- **唯一真相**：`state` 全局对象。所有持久化字段必须在 `normalizeState()` 里有钳位，
  否则导入一份备份就能把它写成任意 JSON，并在某次渲染里炸掉整屏。
- **加字段三步**：① `state = load() || {…}` 的默认值里加 ② `normalizeState()` 里加钳位
  ③ 需要迁移时 `SCHEMA += 1` 并在 `migrate()` 里补一段（0.6.0 从 2 升到 3，补的是行为流水）。
- **落盘**：整体写盘用 `save(state)`；高频输入用 `saveSoon()`（600ms 合并）。
  **不要**直接 `localStorage.setItem`——绕过 `save()` 会跳过裁剪与原生保险丝。
  三个例外入口都收在 `state.js` 里：`writeStore()` / `clearStore()` / `cancelSoon()`，
  它们各自会取消排队的防抖（不然 600ms 后旧数据把刚写的盖掉）。
- **上限**：`trimStore()` 里现在有 **19 处**裁剪（衣柜 36 / 愿望 24 / 菜谱 40 / 搭配 30 /
  下厨 60 / 买菜 120 / 周菜单 14 / 摘录 60 / 提醒 200 / 行为流水 400 / 章 64 / 搜索史 8 /
  草稿 6 / 人档 12 / …）。新增集合时**必须**在 `trimStore()` 里给出上限并记进 `trimLoss`，
  让 `lossMsg()` 说得出「丢了几件」。**不加钳位的集合 = 一颗定时炸弹**。
- **运行时计数器**（`trimLoss` / `normLoss`）不进 state、不进备份。
- **给别人的观测口子**：`logEvent()`（写流水 + bumpStreak + checkBadges）、
  `activeOn/activeDays/eventsOn/eventsBetween/yearSpan/countByKind` 都是模块级函数，
  谁都能调，但**不要各自再算一遍**（第二份定义必然与第一份漂移）。

## 5. 渲染约定

- 每一屏是 `<section class="screen" id="…">`，切屏靠 `show(id)`（`ui.js`）。
- 每屏的渲染入口收在 `show()` 里的 **`RENDER` 表**（`id → 函数名字符串`）。
  值是字符串不是引用：那些函数在后面的文件里，直接引用会在 parse 期命中 TDZ。
  **新增子屏 = 在这张表里加一行 + 在 `SUB_OF` 里加一行**，不要在别处另写一套。
- **模板字符串 + `esc()`**：所有用户数据进 HTML 必须过 `esc()`（`ui.js`）。
  `<button>` 里不许放交互元素（解析器会把按钮咬断）。
- **事件绑定**：一律 `el.onclick = …`（整体重渲染后旧节点被丢弃，不会泄漏）。
  **接管别人屏上的常驻按钮时必须是赋值、必须是赋值、必须是赋值**——`addEventListener`
  会和原来的 handler 同时挂上，一次点击既开屏内面板又弹原生框。
  且**绑在渲染入口**（如 `renderWei()`）而不是「那个页签的渲染函数」里：否则从别的页签
  进来时还是旧 handler。这条是 0.6.0 的实战结论（`#newRecipe` 那条路，测试钉住
  「点一次只开一个面板、prompt 计数为 0」）。
- **不要摆按了没反应的控件**（`test/dead_controls.playwright.py` 会把每一枚都点一次）。
  用不了就 `aria-disabled="true"` **并让按下去吐一句原因**，不要用真 `disabled`
  （真 disabled 对读屏器与键盘隐形，而且与「键盘可达」那道门直接打架）。
- **重建整片之后**：焦点用 `focusKey()` / `restoreFocus()` 保住。
- **文案必须说真话**：演示数据要说「示例/测试」，做不到的入口宁可不摆，数据薄就说薄
  （「再记 3 次这里才说得上话」比摆一个 0 强）。

## 6. 视觉约定

> 这一节是视觉规矩的唯一来源。它原本指向一份 `DESIGN.md`，但那份文件在仓库历史里
> 从来没有存在过（`git log --all` 里查不到任何一次增加或删除）——照着指过去的人会扑空。
> 下面这些条款是**现役的**，每条都在 `docs/HANDOVER.md` 第 4 节有对应的事故记录。

- 只有一个强调色：印章红 `--seal`。金色 `--seal-2` 只用于「再想想」。
- 阴影只有一种：`--lift`。圆角 `--radius`。
- 字体：正文无衬线，标题/金句宋体（`.serif`）。
- 所有颜色必须从 CSS 变量取，**不许在 JS/HTML 里写死色值**。
- 新颜色必须过 WCAG AA（`test/contrast.playwright.py` 会量）。
- 触摸目标 ≥ 44×44（`.chip` 现在 34px 是历史遗留，新控件不许低于 44）。
- **淡出用颜色，不用 `opacity`**。0.6.0 的两个实测：`.nav-ico` 用 `opacity:.62` 把
  `--ink-soft` 的 5.09:1 乘成 2.47:1（对比度门红 8 条）；`[aria-disabled]` 用 `opacity:.4`
  把字压到 2.30:1（读不出为什么按不动）。要「退后」就换一个更浅的颜色变量。

### 6.1 纸只有两种说法（0.6.0 新增，最容易做漏的一处）

`<html data-theme="light|dark">` 由 `theme.js` 的 `apply()` 写，CSS 只认这个属性，不认 JS 分支。
**所有「纸色」必须走变量**，包括渐变里的那种：

| 变量 | 白天 | 夜里 | 用在哪 |
|---|---|---|---|
| `--paper` | `#f4efe6` | `#1b1917` | 底色 |
| `--paper-2` | `#ebe4d6` | `#232019` | 桌面 / 空档 |
| `--paper-wash` | `rgba(244,239,230,.92)` | `rgba(27,25,23,.96)` | body 渐变、宽窗 `#app`、**底栏** |
| `--paper-veil` | `rgba(244,239,230,.72)` | `rgba(27,25,23,.82)` | 长图/打印的薄纱 |
| `--grain` | `rgba(42,39,35,.015)` | `rgba(232,226,214,.02)` | 纸纹 |
| `--ink` / `--ink-soft` / `--line` / `--seal` / `--cream` | 见 `styles.css` | 见 `styles-v06.css` | 全部 |

**为什么单独列一张表**：0.6.0 的深色模式一开始只换了卡片和字色，`body` 的两个渐变、
宽窗 `#app`、`.nav` 底栏都写死了白天的纸 → 实测截图就是**黑卡片浮在米色纸上**，
底栏是整屏唯一一条亮带，看起来像两个 App 拼的。
现在有 `test/light_audit.playwright.py` 守着：10 屏 × 两套主题，断言纸真的翻了、
夜里确实更暗、白天仍是原纸色、深色下没有「亮卡片」、且 **CSS 里不许再写死白天的纸**
（除变量定义处与 `var()` 的 fallback 位）。

### 6.2 长图永远是白天的纸

长图（`card.js` / `card-year.js` / `card-long.js` 三份）画出来的 1080×1920 是**发给别人看的**。夜里存一张黑底长图贴到群里，
看起来像另一个 App。所以 canvas 取色**不走主题**，走 `tokenLight()`：
它探一个 `:root[data-theme="light"]` 作用域把令牌量出来，量完把 `data-theme` 还原，
另有 `CARD_LIGHT_FALLBACK` 常量兜底（拿不到 CSS 变量时用）。
新增长图（年度长图、菜单长图）都调它，不要自己 `getComputedStyle(document.documentElement)`。

## 7. 模块怎么切分 / 接线层为什么单独存在

| 文件 | 内容 |
|---|---|
| `wardrobe.js` | 单品档案、搭配册、愿望冷静期、衣柜统计 |
| `cookbook.js` | 菜谱库、菜谱详情、转盘、一周菜单、菜单长图 |
| `market.js` | 买菜清单、合并规则、货架排序 |
| `remind.js` | 提醒、重复规则、摘录本、原生通知排程 |
| `stats.js` | 热力图三档、四块统计、三种颜色、年度页、成就页 |
| `achievements.js` | 30 枚章的定义与进度 |
| `today.js` | 每日三件事（同一天稳定）、往年今日、连续天数 |
| `wire.js` | **只做**切屏、传一个对象、把状态复位 |
| `share.js` | 系统分享接收（`window.__jianShare`） |

`wire.js` 为什么单独一个文件：`selectCloth / openPhoto / presetNewName / presetYanText /
focusYanCard / yanSearchFor / setYiTab / setWeiTab / resetAll` 每一个都是「A 屏跳到 B 屏」
这种跨模块小事。放进任何一个模块文件都会让那个文件开始理解别人的概念
（衣笺不该知道味笺有什么菜）。放在这里，依赖方向永远是**接线层 → 模块**，反过来一条都没有。

规矩：这一层**不实现业务**。任何一处出现「算出来」的逻辑，都应该搬回它该在的模块文件里。

## 8. 测试与验收

先记三档，别乱跑：

```bash
npm test              # fast：锚点 / 引擎 / 两端一致性 / 网关 HTTP / 备份陈述 / 商店陈述 / 设备守卫（~40s）
npm run test:v06      # 0.6.0 的七道浏览器门（smoke / light_audit / yi / wei / yan / pu / me，~7min）
npm run test:e2e      # 老六道浏览器全流程（e2e / e2e_gateway / contrast / offline / perf / dead_controls，~25min）
```

出包与上架：

```bash
npm run test:pkg      # 产物对账：www / android 资产 / cap 配置 / 墨色 / sw 清单 / 载荷 / APK+AAB 里是哪版前端 / 快捷方式
npm run check         # 以上全部 + gate + e2e + v06 + fuzz 深扫 + 产物对账（发版前跑这个）
npm run test:ship     # 已发布的隐私政策页 == 本地源（要联网、要 gh 登录）
```

其它常用：

- 单节 e2e 窄跑：`python test/e2e_only.py <节号>`（例如 `python test/e2e_only.py 8`）
- 引擎用例：`node test/engine.test.mjs`（192 条）
- 两端一致性：`python test/consistency.py`（改了 `engine.js` 必须跑，且必须同步 `gateway.py`）
- 锚点自检：`python test/gate_selfcheck.py --preflight`（395 段注入，1 秒跑完，**改完源码就跑它**）
- 只跑某一步：`node scripts/test.mjs <fast|v06|e2e|gate|audit|pkg|ship|all>`
- 窄跑诊断：`JIAN_DEAD_ONLY=标签 python test/dead_controls.playwright.py`

**改了源码就跑 `--preflight`**：锚点飘了意味着那条守门根本没在跑，而 `npm run test:gate`
要跑十几分钟才告诉你这件事。0.6.0 期间这件事发生了 6 次（都是某行缩进或条件改了），
每次都是 preflight 一秒抓到。

新增屏幕/新交互必须补测试，两条路选一条：

- 结构不变量（「每枚控件按了有反应」「对比度过 AA」）→ 加进共享门禁（`dead_controls` / `contrast`）；
- 这一屏的业务行为 → 新建/扩展 `test/<lane>_v06.playwright.py`。

格式照既有：`check("断言名", page.evaluate("() => …"), "期望值")`，并**说清这一条在防什么**——
`check` 的名字是给一年后的人看的，不是给 CI 看的。

## 9. 禁令（历史踩过的坑，别再踩）

- 不要在聊天沙箱里后台常驻 `http.server`（会拖垮环境）。
- 不要跑 `adb kill-server`（本机有其它会话共用 adb server）；设备操作一律 `-s <serial>`。
- 不要起第二台模拟器；用完 `adb -s <serial> emu kill`（本机 14.3 GB 内存，一台无头 AVD 吃 4.5–5.5 GB）。
- 不要改 `android/app/jian-release.keystore`；签名密码在 `~/.gradle/gradle.properties`。
- 不要在仓库树里写 API key（网关把仓库根当静态目录发）。
- 不要删 `test/` 下任何既有断言来「让门变绿」，只许补齐或标注原因。
- **不要用真 `disabled`**，也不要在禁用态的选择器里写 `opacity`（会同时破两道门）。
- **不要在注释里下结论说某个平台「不支持」某能力，而不去看它到底怎么实现的**。
  0.6.0 有一次全员传阅的错误前提：「安卓 WebView 禁用 `prompt()`」。
  实际 `Bridge.java:280` 装的是 `BridgeWebChromeClient`，它的 `onJsPrompt/onJsConfirm/onJsAlert`
  全都实现了（`AlertDialog` + `EditText`，`result.confirm(...)` 回调）。
  `prompt()` 在原生壳里**能用**，问题只是它难看（Material + 英文 OK/Cancel）、阻塞 WebView、
  且一次只能问一行字。结论（该换成屏内面板）不变，但**理由写错的代价**是：后来人会去改
  一条正在正常工作的路径，或者反过来指着一个能被证伪的「平台限制」做一堆无用功。
  查证入口：`node_modules/@capacitor/android/capacitor/src/main/java/com/getcapacitor/`。

## 10. 版本号五副本（改一处必须同步四处）

`0.6.0` / `versionCode 28` 现在同时写在：

1. `package.json` 的 `version`
2. `config.js` 的 `VERSION`（页面顶部与「关于」里显示的就是它）
3. `android/app/build.gradle` 的 `versionName` / `versionCode`
4. `sw.js` 的 `VERSION`（**改它才会让老用户的缓存失效**，不改就是永远跑旧前端）
5. `docs/上架/商店材料.md` 的版本那一行

`test/store_claims.py` 会把 APK 里 aapt2 读出来的版本号与这几处对着查——
版本对不上在 Play 那边是可以直接下架的。出包时**先改 1–4，再出包，最后改 5**。

## 11. 一句话给下一个接手的人

这个仓里**大部分看起来啰嗦的注释都是事故报告**。某一行代码旁边写着「以前是 X，
为什么不行」，那句话的价值通常高于代码本身——它记的是某一次真机上真的错了、
以及错成了什么样。改代码的时候顺手看一眼它，别把事故重新犯一遍。
