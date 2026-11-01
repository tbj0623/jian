# 笺 · 交接（给下一个改代码的人）

> 面向「要在这个仓里加东西 / 修东西」的人。README 讲这个 App 是什么、怎么跑；
> 这份讲**为什么它必须是现在这个样子**，以及踩过的坑复现出来是什么症状。
>
> 全部数字都是现数的（0.6.0 / versionCode 28）。`index.html` 553 行、24 个 `<script>`、
> 10 个 `<link>`（其中 7 个样式表）、17 个 `<section class="screen">`。

---

## 1. 加载顺序 = 依赖顺序

`index.html` 末尾那 24 行 `<script>`（第 522–551 行）就是整份依赖图。抄一遍：

| 段 | 文件 | 为什么必须在这一段 |
|---|---|---|
| 底座 | `config.js` `engine.js` `api.js` | 无依赖。`config.js` 里的 `JIAN_CONFIG` 被后面所有文件读 |
| 状态 | `state.js` | **parse 期就执行** `normalizeState(state)`（第 865 行） |
| 主题 | `theme.js` | 要读 `state.settings`，所以只能在 state 之后；它**不在** parse 期 init |
| 共用件 | `ui.js` `card.js` `card-year.js` `card-long.js` | 导航 / toast；长图按「报告卡 / 年度 / 三张新图」分三份（见下面那条「为什么要拆长图」） |
| 老四屏 | `yi.js` `wei.js` `yan.js` `me.js` | 各自独占一屏 |
| v0.6 模块 | `wardrobe.js` `cookbook.js` `market.js` `remind.js` `stats.js` `achievements.js` `settings.js` | 会调老四屏的函数；反过来一条都没有 |
| 接线层 | `wire.js` `share.js` | 只做切屏、传参、复位 |
| 今日 | `today.js` | 要调上面所有模块的入口，所以排在最后一段 |
| 启动 | `app.js` | 永远最后，末尾 `boot()` |

### 为什么这是硬约束（不是风格问题）

`state.js` 不是「定义一个对象就完事」——它在**解析期**就跑完了一整套：

```js
normalizeState(state);                               // state.js:872
if (state.apiUrl) window.JIAN_CONFIG.endpoint = ...; // state.js:873
```

`normalizeState()` 里会调一批函数（`dayStr`、`cssColor`、各个 `normXxx`）。
这些函数**必须在 state.js 里定义，或者在 state.js 之前加载**；否则那一刻它还是
`undefined`，抛 `ReferenceError`，**整页白屏**——不是某一屏坏了，是打开就是一张白纸，
连「哪里错了」都不会显示出来。

这个仓被同一条打伤过两次：

- `cssColor` 被从 `state.js` 挪进 `ui.js` → `normalizeState()` 在 parse 期调它 →
  `ReferenceError` → 整页白。
- `THEME.init()` 一度写在 `theme.js` 的 parse 期末尾 → 那时 `state` 还没从原生备份
  （Preferences）里恢复回来 → 第一帧永远是「上次关掉之前那个主题」。
  现在由 `app.js` 的 `boot()` 在数据救回来**之后**调（`app.js:54`）。

同类还有一处注释钉着：`state.js:9-12` 的 `dayStr()` 必须在 state.js 里，
「放进 ui.js 会变成 `dayStr is not defined`」。

**所以**：看到某个函数「只在某个文件里用」就想挪走之前，先确认它有没有出现在
`normalizeState()` / `migrate()` / `trimStore()` 的调用链上。挪动前先搜一遍。

### 为什么长图拆成了三份

`card.js` 一度长到 74KB，撞了 `scripts/test.mjs` 的载荷门（`MAX_FILE_KB = 64`，
`test:pkg` 直接红在「www 载荷 / 安卓 assets 有超过 64KB 的文件」）。拆法不是按行数切的：

| 文件 | 装什么 | 大约 |
|---|---|---|
| `card.js` | 报告卡两版式 + 它们共用的纸 / 折行 / 印章（`token` / `CARD` / `wrapZh` / `drawStamp` …） | 17KB |
| `card-year.js` | 年度总结；**`tokenLight()` 与 `CARD_LIGHT_FALLBACK` 也在这里** | 19KB |
| `card-long.js` | 单品 / 搭配 / 摘录三张，共用 `longPaper()` | 41KB |

**这三份之间没有解析期依赖**——`CARD` / `token` 虽然是 `const`，但读它们的地方全在
函数体里，函数要到 `boot()` 之后才跑。所以加载顺序只表达「谁读谁」：
`card-long.js` 调 `card-year.js` 的 `tokenLight`，排在它后面。

第 1 节那条「加载顺序 = 依赖顺序」的硬约束**仍然只对 `state.js` 那一族成立**，
别把这条拆分的自由度推广到别处去。

### 新增一个文件要同时改三处

漏一处就是线上少一屏（离线时尤其明显），而三处各自都不会报错：

1. `index.html` 的 `<script src>` / `<link rel="stylesheet">`（末尾那一块）
2. `scripts/build-www.mjs` 的 `files` 白名单（第 17 行起；`icons/` 在 `dirs`，`sw.js` 在 `optionalFiles`）
3. `sw.js` 的 `SHELL` 预缓存清单（第 18 行起）

`npm run check` 会对着查：`checkWww()` 读白名单比对 `www/`，`checkSw()` 确认
`SHELL` 盖住整份白名单。少一个的报错长这样：`FAIL sw 清单 预缓存漏了：xxx → 断网时这些拿不到`。

---

## 2. state 的规矩

### 加一个字段，三步，一步都不能省

1. **默认值**：`let state = load() || { … }` 里加（`state.js:841`，对象字面量一直到第 864 行）。
2. **钳位**：`normalizeState()`（`state.js:511`）里加。导入一份备份就能把这个字段写成任意
   JSON——不钳位就是「别人给你的备份能把某一屏炸掉」。
   v0.6.0 那批新集合的钳位被拆进了 `normXxx()`（`state.js:593` 起），因为
   `normalizeState` 本身已经 60 行了。
3. **迁移**：结构变了才需要——`SCHEMA`（`state.js:17`，现在是 `3`）`+1`，
   并在 `migrate()`（`state.js:90`）末尾补一段 `if (from < N) { … }`。
   注意 `migrate` 末尾会 `s.schema = SCHEMA`，所以旧数据进来一次就再也不会进第二遍。

**不加钳位的集合 = 一颗定时炸弹**：一个 `null` 以前能把整个「册」屏弄空白。

### 归一化必须幂等——`Number(null)` 是 0，不是 NaN

0.6.0 真的踩过这一发，现场在 `state.js:371-381` 的 `normCloth()`。

原来写的是：

```js
const price = Number(o.price);
o.price = Number.isFinite(price) && price >= 0 ? Math.min(price, 1e7) : null;
```

看起来无懈可击——有限、非负、封顶。但 **`Number(null)` 就是 `0`**，
于是「从没填过价」过一遍归一化就变成「0 元赠品」。后果是三重的：

1. 档案页对一件从没填过价的衣服开始声称「记了 ¥0」，`itemMissing()` 里那条
   「还缺价格」消失（`wardrobe.js:82`）；
2. `closetCpw()` 的分母（参与平均的件数）虚高，平均值当场变成一个不是事实的数；
3. **归一化不幂等**：导出的备份再导入一次，值还会再变一次。于是
   「撤销导入之后逐字节比对」那条门红在一个根本看不出跟价格有关的地方——
   排查成本全花在「我明明没动价格」上。

修法是判**原值**，不是判**转成数字之后的结果**：

```js
const rawPrice = o.price;
const blankPrice = rawPrice === null || rawPrice === undefined || rawPrice === "";
const price = Number(rawPrice);
o.price = !blankPrice && Number.isFinite(price) && price >= 0 ? Math.min(price, 1e7) : null;
```

**通用判据**：凡是 `Number(x)` 之后再用 `Number.isFinite(x)` 判空的写法，都要回头看一眼
`x` 有没有可能是 `null`。同族还有两个：

| 写法 | 你以为 | 实际 |
|---|---|---|
| `Number(null)` | `NaN` | **`0`** |
| `Number("")` | `NaN` | **`0`** |
| `Number(false)` | `NaN` | **`0`** |

反过来，`Number(undefined)` 是 `NaN`、`Number("")` 是 `0`——所以「空串」和「undefined」
在这套判法里**行为不一样**，这本身就是必须显式判三个值的原因。

`state.js` 里同一段还有一处同源但要分开判的：`o.price` 与 `o.boughtAt`。
「没填」与「填了 0」在这两格上是两件不同的事实，界面上说的话也不同
（「还没记价格」vs「0 元记的（礼物或赠品），谈不上单次成本」，见 `wardrobe.js:60-66`）。

写新钳位时的自检：**同一份数据 `normalize(normalize(x))` 必须等于 `normalize(x)`**。
不幂等的归一化会以「跟它无关的门红了」的形式出现，最难认。

### `trimStore()` 的每一处上限，都要记进 `trimLoss`

`trimStore()`（`state.js:144-206`，63 行）里现在有 **17 条裁剪语句**：

| 集合 | 上限 | 常量 |
|---|---|---|
| `album`（笺册） | 24 | 字面量 |
| `wardrobe`（柜子） | 36 | 字面量 |
| `yanCards` | 200 | `YAN_CAP` |
| `weiMenu` / `yanText` | 4000 字 | 字面量 |
| `weiHist`（排过的桌） | 4 | `WEI_HIST` |
| `wish` | 24 | `WISH_CAP` |
| `recipes` | 40 | `RECIPE_CAP` |
| `outfits` | 30 | `OUTFIT_CAP` |
| `cookLog` | 60 | `COOK_CAP` |
| `market` | 120 | `MARKET_CAP` |
| `weeks` | 14 | `WEEK_CAP` |
| `digest` | 60 | `DIGEST_CAP` |
| `reminders` | 200 | `NOTE_CAP` |
| `log` | 400 | `LOG_CAP` |
| `drafts` | 6 | `DRAFT_CAP` |
| `peopleSets` | 12 | `PEOPLE_SETS_CAP` |
| 照片（超 `SHED_AT` 时） | 只留前 13 件的图 | 字面量 |

`trimLoss` 有 **17 个键**，与上面这张表一一对应；`lossMsg()`（`state.js:209`）把它们
说成人话（「柜子只留最新 36 件，丢掉 3 件（连穿着记录一起）」）。

两条写在这里的硬规矩：

- **一律用「裁剪前后的件数差」来数**，不要在每一处删除点各记一笔。理由是
  `state.js:185-187` 记的那次：各记一笔会被最后那道重算盖掉，于是
  「把七件说成一件」这种注入照旧绿——守门自检报出来的。**只留一个真相来源。**
- `trimLoss` / `normLoss` 是**运行时计数器，不进 state、不进备份**。进了备份，
  每次开机都会弹一次「丢过照片」。

「丢了几件」说不出来的后果是具体的：屏幕上写着「已用 56%，宽裕」，照片正在被清掉。
所以 `storageInfo()` 的百分比分母是 `SHED_AT`（2 800 000 字节，那道**真的会动手**的线），
不是 localStorage 的 5MB。

### 落盘只有三个例外入口

| 入口 | 在哪 | 它替你做了什么 |
|---|---|---|
| `writeStore(json)` | `state.js:271` | 先 `cancelSoon()` 再 `setItem` |
| `clearStore()` | `state.js:276` | 先 `cancelSoon()` 再 `removeItem` |
| `cancelSoon()` | `state.js:294` | 只取消排队的那次防抖；给「先造脏数据再自己 setItem」的测试用 |

为什么必须走它们：`saveSoon()` 落的是**定时器响那一刻的 state**。凡是绕过 `save()`
直接写盘的地方（导入备份、清空、原生 Preferences 回写），不先取消那次防抖，
600ms 后旧的那份就把刚写进去的盖掉——提示说「已导入」，回头一看什么都没变。

日常写盘用 `save(state)`；打字这种高频小改动用 `saveSoon()`（600ms 合并）。
`test:gate` 里有一组注入专门盯这几条路。

---

## 3. 渲染规矩

### `show()` 里的 `RENDER` 表

`ui.js:303` 的 `show(id)` 是唯一的切屏入口。每屏的渲染入口收在 `RENDER`（`ui.js:327`）里：

```js
const RENDER = {
  me: "renderMe", yi: "renderYi", yan: "renderYan", wei: "renderWei",
  pu: "renderPu", today: "renderToday",
  "yi-report": "enterReport", "yi-item": "renderYiItem", "yi-outfit": "renderYiOutfit",
  "wei-dish": "renderWeiDish", "wei-week": "renderWeiWeek", "yan-remind": "renderRemind",
  settings: "renderSettings", badges: "renderBadges", year: "renderYear", search: "renderSearch",
};
const fn = RENDER[id];
if (fn && typeof window[fn] === "function") { try { window[fn](); } catch (e) { … } }
```

**值是函数名字符串，不是函数引用。** 因为 `renderMe` / `renderYi` 这些函数定义在
`ui.js` **之后**加载的文件里；在 `ui.js` 的 parse 期直接写 `{ me: renderMe }` 会当场
命中 TDZ / `ReferenceError`——就是第 1 节那个白屏。

漏掉一行的症状很安静：切过去是**上一版的画面**，不报错，只有用户看得出来。

### 新增一个子屏 = `SUB_OF` 加一行

`SUB_OF`（`ui.js:260`）现在是 **11 条**，它只表达一件事：**这张纸是从哪张纸翻过来的**。

```
yi-report→yi  yi-item→yi  yi-outfit→yi  wei-dish→wei  wei-week→wei
yan-remind→yan  settings→me  pu→today  badges→pu  year→pu  search→me
```

`show()` 靠它决定要不要把当前屏压进 `backStack`（`ui.js:307`）；
`goBack()`（`ui.js:276`）靠它退回去；`registerNativeBack`（`app.js`）在 `goBack()`
返回 `false` 时才 `minimizeApp()`。**不要在各自的渲染函数里另写一套返回逻辑**
（那是第二份定义，安卓返回键和屏上那枚「返回」迟早走岔）。

新增子屏还要同时看两处：`NAV_OF`（`ui.js:294`，子页归到哪一枚底栏签）和
`app.js:121` 那串 `#backXxx` 绑定。

### 接管别人屏上的常驻按钮：`el.onclick = …`（赋值），并绑在渲染入口

样板在 `cookbook.js:253-282` 的 `bindWeiChrome()`：

```js
function bindWeiChrome() {
  const wb = $("#wheelBtn");
  if (wb) wb.onclick = () => spinWheel();
  const nr = $("#newRecipe");
  if (nr) nr.onclick = () => { … };   // 屏内面板，不是 prompt
}
```

三条都要满足：

1. **必须是赋值**。`addEventListener` 会和原来那个 handler 同时挂着，
   一次点击既开屏内面板又弹原生框。赋值把属性位置上那个函数整个换掉。
2. **必须绑在渲染入口**，也就是 `renderWei()`（`wei.js:123`，第 141 行调 `bindWeiChrome()`），
   不是 `renderCook()`。这两枚按钮是 `index.html` 里的**常驻 DOM**，不随页签销毁；
   只绑在页签渲染函数里的话，从「排桌」页签直接点过去，用的还是 `boot()` 时那个旧 handler。
3. **每一趟进屏都要重绑**，所以它挂在 `renderWei()` 而不是某个一次性初始化里。

这一条由 `test/wei_v06.playwright.py` 钉住：「点一次只多一个面板、prompt 计数为 0」。

### 其它几条同族的

- 用户数据进 HTML 必须过 `esc()`（`ui.js`）。`<button>` 里不许放交互元素。
- 整片重建之前用 `focusKey()` 记、之后 `restoreFocus(fk)` 还回去。
- 换屏时 `show()` 会把焦点交给这一屏（`ui.js:354-359`），读屏器才念得出区域名。

---

## 4. 纸的两种说法

`<html data-theme="light|dark">` 由 `theme.js` 的 `apply()`（`theme.js:36`）写。
**CSS 只认这个属性，不认 JS 分支**——这样还没写好的屏也自动跟着走。

| 变量 | 白天（`styles.css`） | 夜里（`styles-v06.css`） | 用在哪 |
|---|---|---|---|
| `--paper` | `#f4efe6` | `#1b1917` | 底色 |
| `--paper-2` | `#ebe4d6` | `#232019` | 桌面 / 宽窗外的底 / 空档 |
| `--paper-wash` | `rgba(244, 239, 230, .92)` | `rgba(27, 25, 23, .96)` | body 的两个渐变、宽窗 `#app`、`.nav` 底栏 |
| `--paper-veil` | `rgba(244, 239, 230, .72)` | `rgba(27, 25, 23, .82)` | `.veil` 生成/预览长图时那层薄纱 |
| `--grain` | `rgba(42, 39, 35, .015)` | `rgba(232, 226, 214, .02)` | 纸纹（repeating-linear-gradient） |
| `--ink` | `#2a2723` | `#e8e2d6` | 正文墨色 |
| `--ink-soft` | `#6b645b` | `#a09889` | 次级文字（纸白上 5.09:1） |
| `--line` | `#d9d0c2` | `#35302a` | 发丝线、分隔线（**从不承载文字**） |
| `--seal` | `#b54a3c` | `#c97164` | 印章红，全 App 唯一的强调色 |
| `--cream` | `#faf7f1` | `#221f1b` | 卡片底 / 压色块上的字 |

白天那四个「wash / grain / veil」写在 `styles.css` 的 `var()` **fallback** 位置上
（`styles.css:43-45`（body 的两个渐变）、`338-339`（.nav）、`864`（.veil）、`962-965`（宽窗 #app）），
`styles-v06.css:43-48` 的 `:root[data-theme="light"]` 再把它们显式写一遍；夜里由
`:root[data-theme="dark"]`（`styles-v06.css:21-42`）覆盖。**纸色仍然只有 `styles.css` 那一处定义**，
这份表的白天值就是从那抄的。

### 为什么这件事值得单列一节

0.6.0 的深色模式一开始只换了卡片和字色，而下面这四处写死了白天的纸：

- `body` 的**两个渐变**（`styles.css:43-45`）
- 宽窗（≥900px）里 `#app` 的同一对渐变（`styles.css:962-965`）
- `.nav` 底栏的 `background`（`styles.css:338`）
- `.veil` 那层薄纱（`styles.css:864`）

后果不是「稍微有点不协调」，是**黑卡片浮在米色纸上**：整屏只有底栏一条亮带，
像屏幕底部漏光；看起来像两个 App 拼起来的。

现在 `test/light_audit.playwright.py` 守着：10 屏 × 两套主题，断言纸真的翻了、
夜里确实更暗、白天仍是原纸色、深色下没有「亮卡片」，并且**CSS 里不许再写死白天的纸**
（除变量定义处与 `var()` 的 fallback 位）。

### 另外两条同族的

- `:root { color-scheme: light }`（`styles.css:9`）是刻意的：不写它，安卓的日期框 /
  复选框会在系统夜间模式里自己变成深色皮肤，压在纸上就是一块块对不上的灰。
  `theme.js:22` 里夜里会改成 `color-scheme: dark`（见 `styles-v06.css:22`）。
- 阴影只有 `--lift` 一种，圆角只有 `--radius`。新颜色必须过 WCAG AA。

---

## 5. 长图永远是白天的纸

六张 1080×1920 的长图（报告卡两版式 / 年度总结 / 单品 / 搭配 / 摘录 / 菜单）全部**不跟主题**。

### `tokenLight()` 干什么

`card-year.js:59`（拆分前是 `card.js:468`；它跟年度总结住在一起，因为两份新长图都读它）：

```js
function tokenLight(name, fallback) {
  const root = document.documentElement;
  const was = root.dataset.theme;
  try {
    root.dataset.theme = "light";                                  // 临时钉到白天
    const v = getComputedStyle(root).getPropertyValue(name).trim(); // 量一次真值
    if (v) return v;
  } catch (_) { /* 掉到兜底 */ }
  finally { if (was === undefined) delete root.dataset.theme; else root.dataset.theme = was; }
  return CARD_LIGHT_FALLBACK[name] || fallback || "#000";
}
```

它把 `data-theme` 临时切到 `light`、量出令牌、**再切回来**。代价是两次强制重排
（毫秒级，一次只存一张图）；收益是纸色仍然只有 `styles.css` 一处定义，
代码里没有第二条纸色定义。

### 为什么 canvas 不能走主题

`token()`（`card.js:12`）读的是 `documentElement` 上的**计算值**，
`:root[data-theme="dark"]` 会把 `--paper` / `--cream` / `--ink` 全换掉。
于是夜里存出来的长图就是黑底浅字——实测整张纸 `#1b1917`，**贴进群里像另一个 App**。

判断口径很简单：**这张图会被别人看见**。别人看见的应该是一张笺，
不是「我这台手机开了夜间模式」。所以：

- `yearPalette()`（`card-year.js:76`）与 `longPaper()`（`card-long.js:46`）全部走 `tokenLight`；
- `CARD` 常量（`card.js:17`）是**开机时按当时主题取的**，也不能直接用，
  长图那一族连它都要绕开（新拆出来的两份确实都没碰它）；
- 新增长图时不要自己写 `getComputedStyle(document.documentElement)`。
- **新增长图放在哪**：跟已有的一族同住，不要往 `card.js` 里追加——那一份是报告卡的家，
  再往上堆就又撞 64KB。年度那一族进 `card-year.js`，单品/搭配/摘录那一族进 `card-long.js`。

`test/card_v06.playwright.py` 是真的画一遍、量一次像素来验「夜里存出来还是白天的纸」——
这一条只有真画才验得到。

---

## 6. 测试三档 + 产物对账 + 上架前

`scripts/test.mjs` 一把跑完。分组是**按「跑多久 / 要不要浏览器 / 要不要设备」分的**，
不是按重要性分的。

| 命令 | 跑多久（本机实测） | 跑什么 | 什么时候跑 |
|---|---|---|---|
| `npm test`（= `fast`） | **约 12 秒** | 7 道：锚点 preflight / 引擎 192 条 / 两端一致性 170 条 / 网关 HTTP 41 条 / `allowBackup` 陈述 / 商店陈述 55 条 / 设备门守卫 52 条 | 每改一次源码 |
| `npm run test:v06` | **约 10 分钟** | 9 道浏览器门（Edge，headless）：smoke（54s）/ light_audit（40s）/ yi（49s）/ wei（57s）/ yan（113s）/ pu=stats（55s）/ card（33s）/ me（37s）/ a11y（184s）。全部 9 道单跑加起来 **约 10 分钟** | 改完任何一个模块，**先跑这个** |
| `npm run test:e2e` | **20 多分钟** | 老六道：e2e / e2e_gateway / contrast / offline / perf / dead_controls | 改动横跨多屏、或动过 `app.js` / `ui.js` / `styles.css` |
| `npm run test:gate` | **十几分钟** | `gate_selfcheck.py`：395 段「只改一处」的注入，每次都必须炸；跑完校验源码字节一致 | 加/改守门锚点时；赶时间用 `--only 关键词` |
| `npm run test:pkg` | **几秒** | 只验产物：www 漂移 / 安卓资产 / cap 配置副本 / 墨色对账 / sw 清单 / 载荷重量 / APK+AAB 里是哪版前端 / 桌面快捷方式 | 出完包 |
| `npm run test:ship` | **几十秒（要联网 + gh 登录）** | 已发布的隐私政策页 == 本地源（逐字节），再把公开那一页渲染出来量 | 提交商店前 |
| `npm run audit` | **几分钟** | 固定种子差分 fuzz，1400 例，要求漂移 0 | 发版前深扫一次 |
| `npm run check`（= `all`） | **40 分钟以上** | 以上全部 + 产物对账 | 发版前跑这个 |

`fast` 里最前面那一道是 `gate_selfcheck.py --preflight`（**1 秒**）：它只检查
「守门脚本里那些锚点字符串还在不在源码里」。锚点飘了 = 那条守门根本没在跑，
而 `test:gate` 要十几分钟才告诉你这件事。0.6.0 期间这件事发生了 6 次
（都是某行缩进或条件改了），每次都是 preflight 一秒抓到。**改完源码就跑它。**

### 产物对账（`test:pkg`）

三处漂移，任何一处不一致都意味着「测试全绿、包却是旧的」：

1. 根目录 → `www/`（`checkWww`，逐字节比白名单里的每个文件）
2. `www/` → `android/app/src/main/assets/public/`（`checkAndroid`，`cap sync` 拷过去的）
3. 仓库根的 `capacitor.config.json` → `android/.../assets/capacitor.config.json`
   （`checkCapConfig`，APK 真正读的是后者）

外加：`sw.js` 的 `SHELL` 必须盖住白名单（`checkSw`）；单文件不许超过 64KB
（`checkPayload`，`MAX_FILE_KB`）；`res/` 里不许再出现整屏 `splash.png`；
release APK 与 AAB 要真的解开、逐个文件和 `www/` 比字节（`checkArtifacts`）。

**最容易犯的错**：在 `android/` 里直接敲 `gradlew`。那样不会先跑 `cap sync`，
打出来的包跑的是上一版前端——测试全绿也白绿。`npm run android` / `npm run release`
都会先 sync。

### 上架前

1. 先改版本号 1–4（见第 8 节），再出包，最后改第 5 处。
2. `npm run release` → `python test/release_smoke.py`（装 release 看像素：有没有墨色文字、
   纸色占不占大头、有没有崩溃；跑完会把 debug 包装回去）。
3. `npm run check`（全套）→ `npm run test:ship`。

---

## 7. 八类坑

每一条都能在代码里找到对应的注释。**先读那条注释，再改那一段。**

### 7.1 `state.js` 在 parse 期就跑

`state.js:872` 的 `normalizeState(state)` 不是函数定义，是**立即执行**。
它调到的每一个函数都必须已经在全局词法环境里。

- 事故：`cssColor` 挪进 `ui.js` → 白屏（`docs/ENG-CONVENTIONS.md:48`）。
- 同类：`dayStr` 必须在 `state.js:13` 这一份里（`state.js:9-12` 的注释把理由写死了：
  「放进 ui.js 会变成 `dayStr is not defined`」）。
- 推论：`ui.js` 里有一份 `dayStr` 的拷贝，**两处必须逐字一致**，`consistency` 会盯。

### 7.2 新增文件要同时改三处

`index.html` / `scripts/build-www.mjs` 的 `files` 白名单 / `sw.js` 的 `SHELL`。
三处各自都不报错，漏了的后果是「联机能用、断网少一屏」或者「本地能用、装到手机上是旧版」。
`npm run check` 的 `checkWww` / `checkSw` 会对着查。

### 7.3 纸色必须走变量

`styles.css:38-42` 那段注释就是事故现场：`body` 里写死 `rgba(244,239,230,.92)`
之后，`data-theme="dark"` 只换掉了卡片和字色，**整张纸还是亮的**。
同族的还有 `.nav`（`styles.css:335-338`）、宽窗 `#app`（`styles.css:962-965`）、
`.veil`（`styles.css:864`）。判据：**搜 `rgba(` 和 `#f`，看它是不是在定义变量或 fallback 位。**

### 7.4 长图不跟主题

见第 5 节。事故现场的注释在 `card-year.js:44-52`（拆分前是 `card.js:453-462`）——
`tokenLight()` 之所以存在，就是因为那一段记录的「整张纸 `#1b1917`」实测。

### 7.5 淡出用颜色，不用 `opacity`

`opacity` 会把**已经算好的对比度再乘一次**：

- `.nav-ico` 原来是 `opacity: .62`，把 `--ink-soft` 的 **5.09:1 乘成 2.47:1**
  （`styles-v06.css:101-104`；对比度门当时红了 8 条）。
- `[aria-disabled]` 原来是 `opacity: .4`，把 ghost 按钮的字压到 **2.30:1**、
  印章红上那排白字压到 **2.11:1**（`styles.css:202-210`）。

要「退后」就换一个更浅的颜色变量（`--ink-soft` 压纸 5.09:1、压 `--paper-2` 4.61:1，都过 AA），
不要动透明度。同族的还有 `.check.done`（`styles.css:777`，原来整行 `opacity:.45` 把正文压到 2.66:1）
和 `#closetNote` 第二行（`styles.css:588`，原来 `opacity:.72` 把 12px 的字压到 2.95:1）。

### 7.6 接管常驻按钮用赋值

见第 3 节。事故现场在 `cookbook.js:253-267` 与 `wei.js:131-141`。

### 7.7 不许用真 `disabled`

真的 `disabled` 对读屏器与键盘是**隐形**的：他连「这枚现在不能用、为什么」都问不到，
比按了没反应更糟。而且 `test/dead_controls` 会把灰掉的钮算成「够不着」，两道门当场打架。

本仓的口径是 `aria-disabled`（**能聚焦、能按下**）+ 按下去当场说一句原因：

```js
function blockBtn(el, blocked) {            // yi.js:760
  if (!el) return;
  el.setAttribute("aria-disabled", blocked ? "true" : "false");
}
```

`styles.css:202-213` 里那条 `.btn[disabled] { opacity: .4 }` 已经**删掉了**，理由写在注释里：
留着就是一份纯诱惑，谁哪天写 `el.disabled = true` 就同时拿到「读不出为什么」和「对读屏器隐形」。

用 `aria-disabled` 就必须让 handler 开口。反例与正例都在 `card.js:425-431`：
`copyReportText()` 先 `if (!reportCopyable()) { toast("还没有一张笺可复制"); return; }`
——早退条件与「这枚按钮挡不挡」必须是**同一句话**，两边各写一份迟早差出一个静默分支。

### 7.8 「某平台不支持某能力」必须去看实现

0.6.0 有一次全员传阅的**错误前提**：「安卓 WebView 禁用 `prompt()`」。
实际去读 `node_modules/@capacitor/android/capacitor/src/main/java/com/getcapacitor/Bridge.java`
第 280 行装的是 `BridgeWebChromeClient`，它的 `onJsPrompt` / `onJsConfirm` / `onJsAlert`
全都实现了（`AlertDialog` + `EditText` + `result.confirm(...)` 回调）。

`prompt()` 在原生壳里**能用**。它的问题是别的：Material 弹框配英文 OK/Cancel、
阻塞 WebView、一次只能问一行字。所以结论（改成屏内面板）不变，但**理由写错**的代价是：
后来人会去改一条正在正常工作的路径，或者指着一个能被证伪的「平台限制」做一堆无用功。

同一段注释在三个地方（`cookbook.js:16-21`、`remind.js` 文件头、`wei.js:135-138`），
查证入口就是上面那个目录。

### 7.9 版本号五副本

改一处要同步四处：

1. `package.json` 的 `version`（第 3 行）
2. `config.js` 的 `version`（第 5 行）——**界面页脚显示的就是它**
3. `android/app/build.gradle` 的 `versionName`（第 11 行）/ `versionCode`（第 10 行）
4. `sw.js` 的 `VERSION`（第 14 行）——**改它才会让老用户的缓存失效**，不改就是永远跑旧前端
5. `docs/上架/商店材料.md` 的版本那一行（第 14 行）

`test/store_claims.py` 会把 APK 里 aapt2 读出来的版本号与这几处对着查；
`scripts/build-www.mjs` 的 `checkVersions()` 在出包前就拦住不一致（1/2/3/4 四处）。
**版本号对不上在 Play 那边是可以直接下架的。**

出包顺序：**先改 1–4，再出包，最后改 5**。

---

## 8. 一句话

这个仓里大部分看起来啰嗦的注释都是**事故报告**。某一行代码旁边写着「以前是 X、为什么不行」，
那句话的价值通常高于代码本身——它记的是某一次真机上真的错了、以及错成了什么样。
改代码的时候顺手看一眼，别把事故重新犯一遍。
