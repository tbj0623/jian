# 笺 · 功能研究与排期

> 目标：把「一张短笺，一次决定」从原型推到**体量大、可玩性高、成熟**的安卓应用。
> 约束不变：纸、静、少、印章；不做社交 Feed、不做商城、不做虚拟试穿、不偷听。
> 本文只研究、只给清单，不动源码。所有竞品结论都附来源链接；凡是我从功能描述反推的实现方式（不是原厂原话），都在句子里写明"推断"或"从…可见"。

代码基线：`0.5.24` / `versionCode 21` / Capacitor 8 / targetSdk 36 / 纯静态 H5 + localStorage（`KEY="jian.v1"`、`SCHEMA=2`、单份 `state`）。下文「契合点」全部指向真实函数与字段，例如 `normCloth()`、`state.js:365`、`Engine.yi()`、`card.js` 的 1080×1920。

---

## 0. 结论先行

1. **「体量大」不等于「功能多」。** 现在三笺各自只完成了一次闭环（判完 → 出一张笺），缺的是**第二次回来的理由**。成熟产品的体量感来自三样东西：可积累的对象（柜子/桌/条目）、可回看的记录（日历/热力图/历史）、可展示的产出（长图/年度总结）。这三样笺都有雏形，但都没有形成"越用越厚"的曲线。
2. **最大的结构性缺口是「时间」。** 全仓只有三种时间：`cloth.worn/lastWorn`（一件衣服两个数）、`weiHist[].t`（一桌一个点）、`album[].t`（一张笺一个点）——**没有任何按天的事件流**。穿着日历、连续天数、每日摘录、年度总结、提醒，五件事全都卡在同一个前提上：**一张 `dayLog`**。这是本批唯一值得先做的"地基"，直接撑起清单里的 10 项（Y03 S01 S02 S03 S04 S05 G01 G04 N04 N06）。
3. **第二缺口是「单品没有价格」。** CPW（单次穿着成本）、衣柜总值、最贵那件、值不值，四个玩法全都要一个 `price` 字段。而 `normCloth()` 现在只有 8 个字段。加 4 个字段（价格/购入日/场合/尺码）能一次点亮四个功能，是投入产出比最高的一刀。
4. **可玩性的来源不是游戏化积分，是"数字本身有叙事"。**「柜里有一件 214 天没穿了」「这件穿了 12 次，单次 8 块 3」「你连续 9 天有动作」——这类句子比任何徽章都更能让人截图。Whering 的 My Stats 页面标题就直说 "Think Spotify wrapped but for your wardrobe"（[来源](https://whering.co.uk/faq/my-stats-and-tags)），这说明**统计页本身就是传播物**。
5. **安卓侧现在有三个"免费但没捡"的东西**：`enableOnBackInvokedCallback="true"` 已经写了（预测性返回只差手势条适配）、`shortcuts.xml` 三枚快捷方式已经在、`MainActivity` 已经在报 `fontScale`。缺的是 `@capacitor/local-notifications`（未安装）、`ACTION_SEND` 接收（清单里没有 receiver）、深色模式（`styles.css` 无 `prefers-color-scheme`）。这三样是"成熟度"最直观的分水岭。

---

## 1. 竞品拆解

### 1.1 衣橱 / 穿搭

| 产品 | 关键机制 | 对笺的意义 |
|---|---|---|
| **Stylebook** | 90+ 功能；Outfit Shuffle（把衣柜当牌洗，撞出新搭配）；`cost-per-wear` 由价格 ÷ 日历里记录次数算出；日历可一天记多套；统计含「衣柜总值 / 颜色分布 / Top10 最常穿与最少穿 / 没进过任何搭配的单品 / 最近没上日历的单品」；尺码可按品类存、并按品牌存例外 | 最完整的"成熟"参照。**统计项几乎全是"少买"的论据**，和笺的立场同向 |
| **Whering** | 1000 万用户；My Stats 自述 "Think Spotify wrapped but for your wardrobe"；CPW、衣柜总值、在穿率、最常穿颜色、搭配在穿率；Planner 可排未来、可只记单品不建搭配；wishlist + moodboard | 「在穿率」和「搭配在穿率」两个百分比非常适合做笺的季度长图 |
| **Cladwell** | 色彩档案 + Style Direction + 「你离一整周只差三件」（按"能多出几套"排序的缺口建议）+ 「你有结构但不穿它——西装每件只穿 1 次」；免费可建档，订阅 $9.99/月 | 「缺口 + 多出几套」的排序逻辑，可以直接搬到衣笺的"该补什么" |
| **Acloset** | 800 万用户；拍照 AI 归类；日程 & 旅行打包；风格统计；AI 造型师；虚拟试穿 | 规模化的代价是重 AI、重云。**笺只学它的日历与统计，不学试穿** |
| **爱搭衣橱**（国内小体量） | 三条腿：管理（分类/快速上传/穿着记录）、记录（每日穿搭照片，形成风格档案）、搭配（AI 推荐） | 国内用户对"每日穿搭照片"接受度验证过 |
| **Indyx** | 官网为 SPA，抓取拿不到正文（[入口](https://www.indyx.com/features)），从 App Store 描述可见其定位为 outfit planner + stylist + CPW | 说明这条赛道"记账式衣橱"是共识而非某家独创 |

**共性结论（4 条）**：① 单品字段至少是「价格、购入日、品牌、尺码、场合/季节、颜色、材质」七件套；② CPW 是唯一被所有产品实现的"财务化"指标；③ 日历是统计的唯一数据源，没有日历就没有统计；④ wishlist 与"冷静期"是"少买"品牌的标准配置——但 Stylebook 的 wishlist 通向商城，**笺必须把它做成纯本地、不带购买链接**。

### 1.2 菜谱 / 做饭

| 产品 | 关键机制 | 对笺的意义 |
|---|---|---|
| **Paprika** | 内置浏览器抓菜谱；买菜清单**按货架分区**并**自动合并同类项**（`1 egg + 2 eggs = 3 eggs`）；步骤可勾选、屏幕常亮；**时长自动识别**点一下起计时；份量自动缩放；月/周菜单计划；pantry | 「按货架分区 + 合并同类项」是买菜清单的灵魂，纯本地规则做得出来 |
| **AnyList** | 清单自动按类别分组、输入时建议常见项；食谱网页导入；菜单日历；清单项可配图；主题 | 「输入时建议」需要一份本地词表——笺的菜库已经有了 |
| **Mealime** | 三步：Plan → Shop → Cook；每周选菜自动生成清单 | 三步叙事极清晰，适合做笺"排这桌"的引导。**注意它 2026-10-21 关停**（[公告](https://www.mealime.com/)）——纯订阅制小工具的死法值得记一笔 |
| **下厨房** | 3,597,790 菜谱 / 80,414,769 作品；「菜单」（recipe_list）是**用户自组的菜谱集合**，可收藏；时令食材榜单 | 「菜单」这个对象在国内是成立的——它不是"一周计划"，是"我的一桌" |
| **豆果美食** | 菜单/菜谱/食材/「智能找菜」（随机出一道） | 「智能找菜」就是"今晚吃什么"转盘的国内版本 |
| **Whisk / Samsung Food** | 已被三星收购，做购物与食谱的电商打通 | 反面教材：一旦接购物，工具就变成渠道 |

**共性结论**：① 菜谱卡必须有「食材 / 步骤 / 用时 / 难度 / 份量」五段；② 买菜清单必须是菜谱的**派生物**而不是独立功能；③ "今晚吃什么"的随机化是被验证过的留存钩子；④ 忌口/口味档案是家庭场景的刚需，而这正是味笺现有的 `CHIPS` 与 `people[].chips`。

### 1.3 待办 / 笔记

| 产品 | 关键机制 | 对笺的意义 |
|---|---|---|
| **滴答清单 TickTick** | 自然语言解析时间；**看板 / 时间轴 / 日历 / 清单**四视图；重复提醒、持续提醒、每日提醒；习惯打卡与统计；四象限；番茄钟；桌面小组件；全局快捷键 | 视图切换是"体量感"最便宜的来源——同一份数据四种看法 |
| **Things** | Today / This Evening 分离；Upcoming 汇总未来（含重复项与截止日）；Headings 分组；Checklist 子项；Magic Plus 拖放插入；Quick Find 全库秒搜；Jump Start 自然语言日期；进度饼；**「像一张干净的白纸」** | 和笺的品牌最像的一家。**"This Evening"这个切分**可以借给言笺（今天 / 今晚） |
| **Todoist** | Quick Add 自然语言；重复规则极强；80+ 集成 | 笺不做集成，只学"一句话进得去" |
| **flomo** | 每日回顾（默认全部内容 / 全部时间 / **8 条每天**，可 4–24 条）；桌面小组件；推送提醒；**热力图五档深浅 + 有边框表示今天**；月/年统计；**年统计可生成年度分享图**；随机漫步 | 「每日回顾」是"每天回来的理由"的标准答案；热力图的视觉规范（五档 + 今天有边框）可直接照抄 |
| **Bear** | Markdown、标签、OCR 搜索、多格式导出 | 导出即尊严 |
| **Cubox** | 微信转发即收藏；高亮漫游回顾；桌面小组件；URL Scheme；全文与语义搜索 | 「转发即入」——对应笺的 `ACTION_SEND` |

**共性结论**：① 从聊天文字提取待办已是成熟能力，但**大多数产品要联网**；笺的本地规则是差异化而不是短板；② 视图切换（按类型/按时间/日历/看板）比新增字段更能撑"体量"；③ 搜索必须带高亮（笺已有 `hitMark()` 与 `<mark>` 的印泥淡版）；④ 连续天数与年度分享图是留存与传播的双引擎。

### 1.4 轻量习惯 / 日记 / 年度总结

- **flomo 年统计 → 年度分享图**（[热力图与统计](https://help.flomoapp.com/advance/notes-graph.html)）：把"一年写了多少、记录了多少天、每月变化"渲染成一张可发的图。这是"Wrapped 式"最轻的本地实现，**不需要任何服务端**。
- **Day One**（[入口](https://dayoneapp.com/features/)）：日记类以"On This Day / 往年今日"作为回访钩子——一条本地查询即可实现，成本极低。
- **小打卡**（国内习惯类）：连续天数 + 补卡 + 排行榜。**排行榜必须砍掉**（那是社交 Feed 的变体），只留连续天数与补卡。

### 1.5 安卓平台体验

| 能力 | 关键事实 | 来源 |
|---|---|---|
| 本地通知 | `@capacitor/local-notifications`；Android 13+ 需 `POST_NOTIFICATIONS` 运行时权限；Android 12+ 精确定时需 `SCHEDULE_EXACT_ALARM`（否则只排非精确）；Android 14 起 `USE_EXACT_ALARM` 可免申请但**只应给"精确定时是核心功能"的应用**；Doze 下 `allowWhileIdle: true` 的通知**每 App 每 9 分钟只能发一次** | [Capacitor LocalNotifications](https://capacitorjs.com/docs/apis/local-notifications) |
| 系统分享接收 | `ACTION_SEND` + `text/plain` 的 intent-filter；Capacitor 无内置"接收分享"插件，**需要在 `MainActivity` 里读 `Intent.EXTRA_TEXT` 再交给 WebView** | [接收其他应用的数据](https://developer.android.google.cn/develop/ui/compose/sharing/receive) |
| 深链 / 启动 URL | `App.getLaunchUrl()`（冷启动）与 `appUrlOpen` 事件（热启动）；`singleTask` 保证热启动递回正在跑的实例 | [Capacitor App](https://capacitorjs.com/docs/apis/app) |
| 返回键 / 预测性返回 | 清单里 `enableOnBackInvokedCallback="true"` 已开；Capacitor 的 `backButton` 事件与 `toggleBackButtonHandler()` 可运行时开关 | [Capacitor App](https://capacitorjs.com/docs/apis/app)、[预测性返回手势](https://developer.android.google.cn/guide/navigation/custom-back/predictive-back-gesture) |
| edge-to-edge | targetSdk 35+ 强制；`SystemBars` 的 `insetsHandling` 三档（`native` / `css` / `disable`），旧 WebView（<140）安全区 `env()` 有 bug，需靠插件注入 `--safe-area-inset-*` | [Capacitor SystemBars](https://capacitorjs.com/docs/apis/system-bars)、[edge-to-edge](https://developer.android.google.cn/develop/ui/views/layout/edge-to-edge) |
| 通知权限 | Android 13 起为运行时权限，拒绝后不可再弹系统框，只能引导去设置 | [通知运行时权限](https://developer.android.google.cn/develop/ui/views/notifications/notification-permission) |
| 分享出去 | `Share.share({ text, url, files })`；分享文件受 `file_paths.xml` 白名单限制 | [Capacitor Share](https://capacitorjs.com/docs/apis/share) |
| Material You 动态取色 | M3 的色彩角色体系 | [M3 Color roles](https://m3.material.io/styles/color/roles) |

**对笺的判断**：动态取色（Material You）**不该做**。笺的 `--paper: #f4efe6` / `--seal: #b54a3c` 是品牌资产，`styles.css` 与安卓 `res/values/colors.xml` 之间还有一条"墨色对账"的门（ROADMAP 第 63 轮）。让系统从壁纸取色会把纸变成蓝的或紫的——这不是个性化，是品牌自杀。**深色模式要做，但要做成"夜里的纸"（暖灰纸 + 降低印章饱和），不是把纸变黑。**

---

## 2. 在不做大广场的前提下提高可玩性：10 条机制

每条都能落到具体字段与界面，不依赖服务端、不依赖社交。

1. **印章收藏册**：把三笺的判定结果映射成 12–36 枚可收集的印章（`宜入 / 再想想 / 先别 / 雷区 / 全清 / 缺口` × 场景），首次出现时盖一枚并落 `state.stamps[]`，**未解锁的显示为浅灰空章**——空位比成就更能驱动收集。
2. **连续天数只算"有动作的日子"，断签给一次"补记昨天"**：`streak` 由 `dayLog` 推导（判定 / 入柜 / 记穿 / 捞笺 / 排桌任一即算），断签当天不归零而是给一张"补记"笺，**把惩罚换成一次操作**。
3. **每日一笺**：每天首次打开，从柜子、言笺、菜单里各抽一条生成"今天可以做的三件小事"，三件都能一键完成或一键跳过——**开屏就从"空白"变成"有话说"**。
4. **数字叙事**：所有统计句都写成"有主语的句子"而不是图表——「有一件 214 天没穿了」「这件穿了 12 次，一次 8 块 3」「你的柜子里有 7 件是同一种蓝」。整数百分比没人截图，**具体的天数、金额、件数才会**。
5. **年度/季度长图（Wrapped 式）**：复用 `card.js` 的 1080×1920 画布与 `drawStamp()`，多页拼接成 3–5 张一组，全部本地生成，**不需要任何服务端**；flomo 已验证这条路（[来源](https://help.flomoapp.com/advance/notes-graph.html)）。
6. **决定器（转盘 / 洗牌 / 抽签）**：味笺"今晚吃什么"转盘、衣笺"今天穿什么"洗牌（对应 Stylebook 的 Outfit Shuffle）、言笺"先办哪件"抽签——**随机化是把"选择疲劳"变成"游戏"的最短路径**，且完全离线。
7. **可分享产出物做成四种规格**：9:16 故事图（1080×1920，已有）、1:1 方图、纯文字（已有 `reportText()`）、以及**"一句话"**（一行字 + 一枚印章，最容易被复制进群里）。产出物规格化 = 传播面 ×4。
8. **里程碑自动盖章**：第 1 / 10 / 50 / 100 张笺、第一次清空柜子、第一次连续 7 天——自动盖一枚带日期的"第 N 张"章，**只增不改**，成为时间轴。
9. **往年今日**：打开时 30% 概率插入一条"去年的今天你判了这件 / 那时这桌人还是这几个"，一条本地日期查询即可，成本近乎为零。
10. **柜子完整度**：按品类、颜色、场合三条轴算"你的柜子完成了几成"，缺的那一格给出"补一件什么"（Cladwell 的"你离一整周只差三件"是同一逻辑的付费版）。**完成度是进度条，进度条是最便宜的留存。**

---

## 3. 功能清单

**读法**：`编号 名称` · 优先级 `P0/P1/P2` · 复杂度 `S/M/L`；每条一行，依次是 用户故事｜机制/数据形状｜界面落点｜可玩性来源｜与现有代码的契合点｜风险与「这不该做」。

### 3.1 衣笺（Y）

**Y01 单品档案（价格 / 购入日 / 场合 / 尺码）** `P0` `M`
买之前想得起"去年也买过一件差不多的、多少钱"｜`cloth.price:number`、`boughtAt:ts`、`occasions:string[]`、`size:string`，全部进 `normCloth()` 的白名单并钳位（价格 0–99999，购入日 ≤ now）｜柜子点开一件 → `#clothActions` 里新增可折叠"档案"段｜CPW 有了分子；「最贵那件」「买回来没穿过」两条排行｜`normCloth()` 加 4 行；`state.js:236` 就是唯一收口处；`card.js` 的 `basisLine()` 直接读｜**风险**：价格是敏感数据，导出备份时会明文落在 JSON 里——必须在「我的 → 导出」旁写明"备份含价格"。**不做**：不做分期/花呗联想，不做"你本月服装支出"（那是记账 App）。

**Y02 单次穿着成本 CPW** `P0` `S`
我想知道这件到底值不值｜`cpw = price / max(1, worn)`，`worn=0` 时显示"还没穿过"而不是除零；按 `cpw` 排序即"最不值"｜柜子排序条新增第三枚「按单次成本」；单品档案里一行大字｜「8 块 3 一次」比任何徽章都想截图｜`worn` 已存在（`state.js:245`），`closetSort` 只认 `freq|idle`，加一个 `cpw` 值即可｜**风险**：`worn` 是用户手记的，可能虚高 → 必须显示"按 N 次算"，不能装作精确。

**Y03 穿着日历 / 热力图** `P0` `M`
我想看见自己这一年到底穿了什么｜`dayLog: { "2026-10-18": { wear:[clothId], outfit?:id, note?:string } }`，**只存有事件的天**，一年最多 366 键｜衣笺顶部新增「日历」入口 → 一整屏 7×N 网格（flomo 五档深浅 + 今天带边框）｜点一格看当天穿了什么；连续空格本身就是压力｜`ui.js` 已有 `dayStr()`（全仓唯一日界）与 `relativeDays()`；`worn/lastWorn` 可以由此派生而不是继续各存一份｜**风险**：**这是全仓第一个按天的事件流，必须一次做对**——`dayStr` 只在 `ui.js` 有一份，`dayLog` 的键必须用它生成，否则跨时区/夏令时会裂。**不做**：不做"穿搭照片墙"（那是社交）。

**Y04 衣柜统计总览** `P0` `M`
我想一眼看清这个柜子｜派生量：`closetN`、`总值`、`在穿率 = worn>0 的件数 / 总件数`、`颜色分布`（按 `Engine.rgbToHsl` 分桶）、`Top5 最常穿 / 最久未穿`、`没进过任何搭配的件`｜衣笺第二屏「柜子·统计」，全部由现有字段现算，**不新增存储**｜"你的柜子有 63% 在穿"是能被发出去的一句话｜`Engine` 已有 `rgbToHsl/hexToRgb/deltaE`；`closetNote()` 已经在算 `never/stale`｜**风险**：柜子 <5 件时统计全是噪声 → 沿用 `thin` 标志，薄柜只显示"件数"和"再入几件才有统计"。

**Y05 搭配册（outfit）** `P1` `L`
我想把"这套能穿"存下来，下次直接用｜`outfits:[{ id, name, items:[clothId], occasions[], t, worn:number, lastWorn }]`，上限 40 套；一件可属于多套｜衣笺第三屏「搭配」，格子墙 + 新建（勾选柜里 2–4 件）｜洗牌出搭配（对应 Stylebook Outfit Shuffle）；"这套穿过 5 次"｜`Engine.pickCompanions()` 已经在算"能配柜里哪几件"，把它的输出从"报告里的一行"升级成"可保存的对象"｜**风险**：搭配的图要靠单品照片拼，而照片会被 `SHED_AT=2.8MB` 逐级清掉 → **搭配不能依赖照片**，必须有纯色卡降级。**不做**：不做自由拖拽画布（Stylebook 的 free-form canvas 是 L+，且与"少"冲突）。

**Y06 愿望单 + 冷静期** `P1` `M`
我想买但先放三天｜`wish:[{ id, name, price?, color?, t, decideAt, verdict? }]`，`decideAt = t + 72h`｜衣笺第四屏「想买」，卡片上一条倒计时｜"还有 2 天可以想清楚"；到期那天推送一次｜`state.lastNew` 已经是"这一件"的暂存，愿望单是它的持久化版本；`Engine.yi()` 可直接对愿望单里的项复用判定｜**风险**：**绝不能带购买链接、不能带商品图抓取**——那一步就变成商城。只允许用户自己拍/选一张图。

**Y07 单品「该退休了」清单** `P1` `S`
哪些该捐、该卖、该扔｜`retire = worn<=2 && age>365天`（用 `boughtAt`），或 `lastWorn > 365天`｜柜子统计页末尾一节「可以想想的 N 件」｜"一年没穿"是很硬的自我说服｜`closetNote()` 已有的 `stale`（90 天）扩到 365 天即可｜**风险**：措辞不许judge（"扔掉"→"可以想想"）；**不做**二手转卖入口。

**Y08 报告页历史（最近 12 张）** `P1` `S`
我想翻回上个月那张笺｜`reports:[{ id, t, stamp, quote, gap, clothName, img? }]`，上限 12 张，图不存（按需重画）｜报告页底部横向卡片条｜"三个月前你判的是'再想想'，最后买了吗"｜`state.lastReport` 已是单张，扩成数组；`album[]` 里已经存了 `type:"yi"` 的条目，可以合并｜**风险**：和 `album`（笺册）功能重叠 → 二者必须分工：**album 是"我复制过的文本"，reports 是"我判过的结论"**。

**Y09 颜色库 / 我的常用色** `P1` `S`
我老是买同一个颜色，我想看见它｜`Engine.analyze()` 产出的主色按 `hue` 分 12 桶，取 `pct` 最高的 3 个作为"你的颜色"｜柜子统计页一节「你的三种颜色」｜"你 41% 的衣服是同一个色系"｜`Engine.palette()` 已有分桶与合并逻辑（`rgbDist < 42`）｜**风险**：无。这是最便宜的一条。

**Y10 入柜向导（三问）** `P2` `S`
入柜时懒得填那么多｜三个问题：多少钱 / 什么时候买的 / 什么场合穿，可全跳过｜入柜后弹出的 `toast` 换成一张三问小卡｜把"填档案"从表单变成对话｜`yi.js` 的入柜路径已经有一次 `toast`，替换即可｜**风险**：跳过率会很高 → 必须允许"以后再说"，且档案段永远可补。

**Y11 季节柜子（收纳 / 换季）** `P2` `M`
换季时我想把夏装收起来｜`cloth.stored:boolean`，`closetSeason` 已有；"收起"= 从主列表隐藏但仍在统计里｜柜子筛选条加「在柜 / 收起」｜换季那一下有仪式感｜`state.closetSeason` 已存在，只需多一个布尔｜**风险**：与现有季节筛选语义重叠 → 必须先厘清"季节"是属性、"收纳"是状态。

### 3.2 味笺（W）

**W01 菜谱卡（食材 / 步骤 / 用时 / 难度 / 份量）** `P0` `M`
我想把"这家店那道菜"变成"我能做的那道菜"｜`recipes:[{ id, name, tags[], minutes, level:1-3, serves, items:[{n,q,unit}], steps:[string] }]`，上限 60 道｜味笺新增「菜谱」页，卡片式列表 + 详情｜"这道 25 分钟、两口人、不难"是决策信息｜`Engine.DISHES` 已有 63 道带 `tags` 的菜库，正好是菜谱卡的种子数据｜**风险**：菜谱正文不许从网上抓（版权 + 联网）→ **只允许用户自己录**，内置菜库只存"名字 + 标签 + 缺口"，不存步骤。

**W02 菜谱 → 买菜清单** `P0` `M`
定了菜单我不想再手抄一遍要买什么｜`shopping:[{ id, n, q, unit, aisle, done, from:recipeId }]`，由菜谱/菜单派生｜味笺「买菜」页，按 `aisle` 分组｜勾选打勾的爽感 + "还差 3 样"｜`mealPlan` 的 `menu` 解析（`countMenu()`）已经能拿菜名，菜谱卡带上 `items` 就能自动展开｜**风险**：合并同类项（`1 蛋 + 2 蛋 = 3 蛋`）是 Paprika 的核心，**做不精确就不要假装做**——先按"同名 + 同单位"合并，不同单位的并排显示。

**W03 一周菜单 / 这周吃什么** `P0` `M`
周日想把这一周定下来｜`weekPlan: { "2026-W42": { mon:[dishName], ... } }`，一周 7 天 × 最多 4 道｜味笺新增「这周」页，7 列网格｜点格填菜，自动汇总成清单｜`weiHist` 已有 4 桌历史，周计划是"未来的桌"｜**风险**：和"排这桌"（一次性）概念重叠 → 周计划只存"菜名"，**不存判定结果**，排桌时才跑 `Engine`。

**W04 家庭忌口档案（多人持久化）** `P1` `S`
每次都要重新说一遍谁不吃什么｜现有的 `state.people[]` 已经是对的，缺的是"这桌人"和"我认识的人"两层｜味笺顶部「常一起吃饭的人」抽屉，一键把 3 个人拉进这一桌｜"阿姨不吃香菜、小李不吃海鲜"一次记住，永远有效｜`people[]` + `normPerson()` 已有，只需加 `saved:boolean` 区分"存档的人"与"这桌的人"｜**风险**：人数上限（现在没有）→ 必须设 12 人上限并说清楚。

**W05 「今晚吃什么」转盘** `P1` `S`
选择疲劳时想有人替我决定｜从菜库/我的菜谱里抽 3 道，转盘动画停在一道｜味笺首页一枚「替我想」按钮｜**随机化 = 游戏化**，豆果的「智能找菜」就是这个｜`Engine.DISHES` 现成，`servingStage()` 可保证抽出来的组合不全是硬菜｜**风险**：抽出来的一定要能"再抽一次"，否则用户会以为坏了。

**W06 口味档案（我的四气质）** `P1` `M`
我想知道我这桌人到底是什么口味｜从历史 `weiHist[].chips` 与 `mode` 统计出"你常排的是朋友局、最常踩的雷是辣"｜味笺「口味」页｜"你排过 12 桌，7 桌避开了辣"｜`weiHist` 已有 `chips/n/t`，够算｜**风险**：样本 <5 桌时全是噪声 → 与 `thin` 同款处理。

**W07 菜单分享长图** `P1` `M`
排好的一桌我想直接发群里｜复用 `card.js` 的 1080×1920，版式：桌名 + 人数 + 上菜顺序 + 雷区 + 缺口｜味笺结果页新增「存成菜单图」｜**这桌的图本身就是群里的社交货币**｜`card.js` 的画布/印章/竖排全是现成的，只需新写一个 `drawWeiCard()`｜**风险**：`card.js` 现在是 1000+ 行单文件，再加一个版式会失控 → 先拆出 `drawBaseCanvas()`。

**W08 上菜顺序可视化（时间轴）** `P1` `S`
我想知道先上什么、什么时候起锅｜`servingOrder()` 已返回 6 段（先上/清口/主菜/硬菜/汤/主食），把它画成一条竖向时间轴｜味笺结果区，替换现在的纯文字列表｜时间轴比列表更有"这桌在发生"的感觉｜`Engine.servingOrder()` 与 `STAGE_NAMES` 已存在｜**风险**：无。

**W09 重复主料检测升格** `P1` `S`
一桌三道都是土豆，我想被提醒｜现有 `dupes` 已在算，缺的是"给替代建议"｜味笺结果里 `dupes` 那一行加"换一道"｜"三道土豆"是个好笑的瞬间，值得截图｜`Engine` 的 `dupes` 已有｜**风险**：建议必须来自本地菜库，不许联网。

**W10 剩菜 / 打包记一笔** `P2` `S`
这桌点多了，下次少点两道｜`leftover: { menuHash, extra:number, t }`，只记"多了几道"｜排桌结果页底部一枚小签｜"上次这桌剩了 3 道"｜`weiHist` 加一个字段即可｜**风险**：会变成记账 → 只记"道数"，不记钱。

### 3.3 言笺（N）

**N01 提醒与重复** `P0` `M`
说好周五交的东西，我到点能收到一条｜`card.remindAt:ts`、`card.repeat:"none|daily|weekly|monthly"`，与 `when` 分开（`when` 是"说的时间"，`remindAt` 是"叫我的时间"）｜言笺每条右侧一枚铃铛；「我的 → 提醒」总览｜到点推送（安卓本地通知）+ 完成时那一行划掉｜`normYanCard()` 已有 `when`；`dayLabel()/whenFromDate()` 已有日期解析；接 `@capacitor/local-notifications`｜**风险**：**重复任务的通知必须每次重排**，Doze 下 `allowWhileIdle` 每 9 分钟才一次（[来源](https://capacitorjs.com/docs/apis/local-notifications)）→ 只能承诺"大约这个点"，文案不许写"准时"。

**N02 三视图：按类型 / 按时间 / 日历** `P0` `M`
同一批事我想换个看法｜`yanView: "kind"|"time"|"calendar"`；日历视图把有 `when` 的条目落到月网格｜言笺顶部三枚签（现在只有两枚）｜视图切换是"体量"最便宜的来源（滴答清单四视图）｜`state.yanView` 已存在且只认两个值，加第三个值 + 一条 `paintYan()` 分支｜**风险**：`paintYan()` 已经很大，日历视图必须独立成函数，别塞进去。

**N03 今天 / 今晚 两个抽屉** `P1` `S`
今天要办的和今晚要办的不是一回事｜`card.slot:"day"|"evening"`，默认 `day`｜言笺「按时间」视图顶部两个抽屉｜Things 的 This Evening 被验证过｜`yan.js` 的 `dayLabel()` 已在算"今天/明天"｜**风险**：多一个字段就多一次误判 → 默认 `day`，只在用户手动改时写 `evening`。

**N04 每日摘录 / 金句** `P0` `M`
我想留一句今天最值得记的话｜`quotes:[{ t, text, from?:speaker }]`，上限 200；`dayLog` 每天最多 1 条｜言笺顶部一枚「摘一句」；「我的」里一节「摘录」｜flomo 的每日回顾已验证：**人愿意回看自己写过的句子**｜`album[]` 已经是"文本 + 时间 + 类型"的结构，摘录可以是它的第四种 `type`｜**风险**：与 `album` 重叠 → 摘录是"主动存的句子"，album 是"自动存的整张笺"，UI 上必须分开。

**N05 搜索增强（按人 / 按时间范围 / 按状态）** `P1` `M`
我想找"小王说过的、还没办的"｜`yanQuery()` 现在只有关键词；加 `who` / `from..to` / `done` 三个筛选维度｜言笺搜索条展开成筛选面板｜组合筛选是"我的数据真的多到需要工具"的体感｜`yanShown()` 是唯一筛选口径，扩展它即可（**不要**再写第二份）｜**风险**：`yan.js` 已有一次"筛选两处定义"的教训（`yanShown()` 是唯一真相）→ 新维度必须进同一个函数。

**N06 一键把勾掉的归档** `P1` `S`
办完的事我不想一直看着｜`done` 且有 `doneAt` 的条目在 7 天后自动移出主列表，进「归档」｜言笺底部「归档」入口｜"你今年办完了 84 件事"｜现在有 `yanPrune`（只清勾掉的），归档是它的自动版｜**风险**：自动移出会让用户以为丢了 → 必须先给一次可撤销的提示。

**N07 言笺 → 衣笺 / 味笺的转投** `P1` `S`
"要买"那条其实该去衣笺过一遍｜`card.k==="要买"` 的行上给一枚「去过笺」｜言笺行 → 跳衣笺并预填名称｜跨模块联动让三笺像一个应用而不是三个｜`openDeep()` 已能跨屏跳转（`jian://screen/yi`），加一个"带参数"的形式即可｜**风险**：预填只能带名字，**不能带图**（跨模块传图会撑爆 localStorage）。

**N08 贴进来的文字自动去噪** `P2` `S`
聊天记录里全是时间和表情，我想干净点｜在 `normCards()` 前加一道：剥时间戳、剥 `[表情]`、剥重复的系统消息｜无独立界面，就是"捞成笺"这一步变准｜准确率提升本身就是可玩性｜`yan.js` 已有 `speakerTag()` 与 `TURN_RE`，同一层加规则｜**风险**：剥多了会把内容剥没 → 必须"剥完为空就退回原话"（现有代码已经这么做过一次）。

**N09 每条一张小票（时间 / 谁说的 / 来源）** `P2` `S`
我想知道这句话是从哪段聊天里捞的｜`card.src:{ t, excerpt }`，只存前后 20 字｜点条目展开「原话」｜可追溯 = 可信｜`normYanCard()` 加一个字段，`yan.js` 折叠区展示｜**风险**：会显著增大存储（200 条 × 40 字）→ 只给"手动钉住"的条目存。

### 3.4 全局（G）

**G01 今日一笺（首页）** `P0` `M`
我打开 App 想知道"今天该做点什么"｜`home = "today"` 新屏：三件小事（一条柜子里的事 / 一条言笺的事 / 一条味笺的事）+ 连续天数 + 今日摘录入口｜底栏加一枚「今日」，或把现有 `home` 扩一个值｜**这是"每天回来的理由"的唯一载体**｜`paintModeCards()` / `state.home` 已支持四个值，加 `today` 即可；数据全从 `dayLog` 派生｜**风险**：会变成"仪表盘"从而违反"少"→ 硬性限制：**这一屏永远只显示 3 件事**。

**G02 深色模式** `P0` `M`
晚上看白纸太刺眼｜`@media (prefers-color-scheme: dark)` 覆盖 `--paper/--paper-2/--ink/--line/`，印章饱和降 15%，纸做"夜纸"（#1c1a17 一类暖灰）｜全局，`styles.css` 一处｜夜里也能写笺 = 使用时长翻倍｜`styles.css` 现在**一条** `prefers-color-scheme` 都没有，全是 `:root` 变量 → 加一组覆盖是最小改动｜**风险**：`card.js` 的长图色是硬编码的（`STAMP_COLOR` 等），深色模式下长图必须**仍然是浅纸**（长图是发给别人看的）。这条要写进门里。

**G03 统一搜索（三笺 + 笺册）** `P1` `M`
我想一次搜遍所有｜一个入口，结果分四组，命中带 `<mark>`｜「我的」顶部或全局搜索键｜"我到底有没有存过这句话"｜柜子有 `closetQuery()`、言笺有 `yanQuery()`、album 无搜索 → 抽一个 `searchAll(q)` 复用它俩｜**风险**：三份筛选逻辑会漂 → `searchAll()` 只能调用现有函数，不许自己再判一次。

**G04 数据看板（存储 / 件数 / 天数）** `P1` `S`
我想知道自己用了多少｜`storageInfo()` 已有，补"柜 12 件 / 言 34 条 / 笺 8 张 / 用了 12 天"｜「我的」顶部一块｜体量感来自"我的东西在这里"｜`storageInfo()`（`state.js:186`）与 `trimLoss` 都已有｜**风险**：`pct` 的分母是 `SHED_AT`，文案不许写"已用 X%"让人以为 5MB——现有代码已经踩过这个坑。

**G05 引导页重做（三张卡 → 一个动作）** `P1` `M`
第一次打开不知道该干嘛｜现在的引导页是三张选择卡（选默认首页），对一个新用户来说是"先做设置"。改成：一句话 + 一个"试试看"（直接给一个示例，走完一次完整闭环）｜`#onboard` 屏｜首次成功体验（TTV）决定留存｜`app.js` 的 `boot()` 与 `#go` 已有；示例数据 `seedWardrobe()` / `demoWei` / `demoYan` 全都在｜**风险**：`onboarded` 是布尔，老用户不会重看 → 只对新装生效。

**G06 键盘/读屏/字号的持续守门（已有，扩到新屏）** `P1` `S`
放大字号之后不许有字被裁｜`--sat/--sab` 已有；新增的每一屏都要进 `test/e2e.playwright.py` 的 §48 与 §54｜CI 门｜——｜现有门已经很完整（1162 条断言、219 条注入），新屏必须接进去｜**风险**：不加门的新屏会在两轮之后悄悄坏掉。**这条是"成熟"的必要条件，不是加分项。**

### 3.5 统计与成就（S）

**S01 总览统计页** `P0` `M`
我想看见"我用这个 App 的这半年"｜一屏四块：柜子（件数/总值/在穿率）、穿着（总次数/最常穿/最久没穿）、言笺（总条数/办完率/最常出现的词）、味笺（桌数/最常踩的雷）｜底栏「我的」里一节，或新屏｜数字叙事（见 §2 第 4 条）｜全部派生，`storageInfo()` + `closetNote()` + `album` 已有｜**风险**：数据少时整页是空的 → 每块独立判空，各自给"再记 N 次就有"。

**S02 连续天数 streak** `P0` `S`
我想保持这个记录｜`streak` 由 `dayLog` 派生（有事件的连续天），断签给一次补记｜「今日」屏顶部一枚小章 "9 天"｜**连续感是最便宜的回访驱动**｜`dayLog` 派生，零新存储｜**风险**：时区/跨天必须只用 `dayStr()`；**不做**排行榜、不做"断签惩罚"。

**S03 印章收藏册** `P0` `M`
我想收集这些章｜`stamps:[{ id, at, count }]`，12–36 枚，未解锁显示浅灰空章｜「我的」新增「章」页，网格｜**空位驱动收集**，且每一枚都对应一次真实判定｜`card.js` 的 `drawStamp()` 已在画章，CSS 已有 `.seal-mark`｜**风险**：章太多会稀释 → **第一批只做 12 枚**，且必须"每一枚都能说清是怎么来的"。

**S04 里程碑（第 N 张笺）** `P1` `S`
我想记住第 100 张｜`milestones:[{ n, at }]` at 1/10/50/100/500｜判定完成时 `toast` 换成盖章动画｜只增不改的时间轴｜`state.album` 的长度就是天然计数｜**风险**：动画不许超过 400ms（现有 perf 门对"最慢一次"有 400ms 兜底）。

**S05 季度 / 年度长图** `P1` `L`
年底我想发一张"我的这一年"｜复用 `card.js` 1080×1920，3–5 页：件数、在穿率、最常穿、最贵一次、连续天数｜「统计」页底部「做成一张」｜Wrapped 式，flomo 已验证｜`card.js` 的画布/印章/竖排全在；数据全在 `dayLog` + `state`｜**风险**：**必须能在数据不足时拒绝生成**并说明"再记 20 天就有"。

**S06 「今年少买了 N 件」对比** `P2` `M`
我想知道自己是不是真的少买了｜需要"往年"数据 → 第一年做不出来｜统计页一节｜——｜**风险**：第一年没有基线，做了就是假话 → **推迟到第二年**，现在只存 `boughtAt` 供以后用。

**S07 我的三种颜色 / 三个词** `P2` `S`
我想知道自己的偏好｜颜色从 `Engine.palette()` 统计；词从言笺分词统计｜统计页两块小卡｜"你最常说'再说吧'"这类发现很好笑、很想发｜`Engine` 已有颜色分桶；词频用一个 `Map` 即可｜**风险**：分词没有词表会出垃圾 → 只统计"已在 `CHIPS`/菜库/人名里出现过的词"。

### 3.6 设置（P）

**P01 设置页收口** `P1` `M`
「我的」现在什么都往里塞｜拆成「我的（数据与笺册）」+「设置（外观/通知/隐私/关于）」｜底栏不变，`#me` 顶部加一枚齿轮 → 新屏 `#settings`｜设置页是"成熟"的心理学证据｜`me.js` 的 `renderMe()` 已经很挤，拆屏比继续加节更安全｜**风险**：拆屏会动 `show()` 的 `map` 与 `backStack`，必须同步更新 `screenOf()` 与 `shortcuts.xml` 的深链。

**P02 通知开关（分类 + 时段）** `P1` `S`
我不想半夜被叫｜`notify:{ on, yan:bool, wei:bool, quiet:[22,8] }`｜设置页｜——｜接 `LocalNotifications.checkPermissions()`｜**风险**：Android 13 拒绝后不可再弹系统框（[来源](https://developer.android.google.cn/develop/ui/views/notifications/notification-permission)）→ 拒绝后只能给"去设置"的说明。

**P03 字号与密度** `P1` `S`
我想字大一点 / 一屏多看几行｜三档（标准/大/更大）映射到 `:root` 的 `--fs`，与系统 `fontScale` **相乘**｜设置页｜——｜安卓侧 `MainActivity` 已经在报 `textZoom`（`applyFontScale()`），Web 侧再给一档｜**风险**：两套缩放会叠乘到 3× → 必须钳位并进 §48。

**P04 关于 / 版本 / 隐私政策入口迁移** `P2` `S`
——｜复用 `config.js` 的 `privacyUrl`｜设置页｜——｜`renderPrivacy()` 已有，挪位置即可｜**风险**：`store_claims.py` 会按位置断言那句"数据只在这台设备"→ 挪了要同步改门。

### 3.7 安卓原生（A）

**A01 本地通知** `P0` `M`
到点提醒我｜`@capacitor/local-notifications`；Android 13+ 请求 `POST_NOTIFICATIONS`；不用 `USE_EXACT_ALARM`（笺的提醒不精确到分钟）；通知 id 用 `card.id` 的哈希｜设置页开关；言笺每条铃铛｜——｜现在**没装这个依赖**（`package.json` 只有 app/filesystem/haptics/preferences/share/splash/status-bar）｜**风险**：Doze 下 `allowWhileIdle` 每 9 分钟一次（[来源](https://capacitorjs.com/docs/apis/local-notifications)）→ 文案写"大约"，不写"准时"；`cancelAll()` 必须在清空数据时调用。

**A02 系统分享接收（ACTION_SEND）** `P0` `M`
我在微信里选中一段话，直接"分享到笺"｜`AndroidManifest` 加 `ACTION_SEND` + `text/plain` 的 intent-filter；`MainActivity.onCreate/onNewIntent` 读 `Intent.EXTRA_TEXT`，经 `Bridge` 交给 WebView，落到 `#yanText` 并自动跑一次 `runYan()`｜外部入口，无独立屏｜**这是言笺最重要的入口**——比"打开 App 再粘贴"少三步｜`app.js` 的 `openDeep()` 与 `screenOf()` 已有"从外部 URL 进屏"的路子，`ACTION_SEND` 走同一条收口｜**风险**：Capacitor 无内置接收插件 → 要写 20 行 Java；`launchMode="singleTask"` 已经在，`onNewIntent` 必须覆盖，否则热启动会丢内容。

**A03 edge-to-edge 与安全区** `P0` `S`
状态栏和手势条不许压在字上｜`SystemBars` 的 `insetsHandling: "css"`；`--sat/--sab/--sal/--sar` 已有，且已有"`env(safe-area-inset-*)` 只许出现四次"的不变量｜全局｜——｜`styles.css` 的四个变量已就位；ROADMAP 第 53/54 轮已把上半圈量过（251 处零违规）｜**风险**：targetSdk 36 强制 edge-to-edge（ROADMAP 原话）→ 这条不是"优化"，是**必须**。

**A04 预测性返回** `P1` `S`
返回手势要能预览"回到哪张纸"｜`enableOnBackInvokedCallback="true"` 已开；补 `android:enableOnBackInvokedCallback` 的逐 Activity 行为 + 让 WebView 在 `backButton` 事件里同步 `backStack`｜全局｜——｜清单里那一条**已经写了**，缺的是"返回时真的回上一张纸"（`ui.js` 的 `goBack()` 已有 `backStack`）｜**风险**：WebView 里的预测性返回动画支持有限 → 先保证"返回不退出 App"，动画是加分项。

**A05 桌面快捷方式扩展** `P1` `S`
我想长按图标直接"记一笔"｜现有三枚（`jian://screen/yi|wei|yan`）再加两枚：`jian://screen/today`、`jian://action/quick-note`｜`shortcuts.xml`｜——｜`shortcuts.xml` 已有完整模板，复制两条即可｜**风险**：`shortcutId` 与 `strings.xml` 的 label 必须同步（`store_claims.py` 会数三枚）。**注意：`shortcut` 最多 5 个**。

**A06 深链参数化** `P1` `S`
从别处点链接能直接带着内容进来｜`jian://screen/yi?name=白衬衫`、`jian://screen/yan?text=...`｜无独立屏｜——｜`screenOf()` 只认 `yi|wei|yan|me`，加 query 解析｜**风险**：`text` 要限长（4000 字，与 `yanText` 一致），且**必须走 `esc()`**（`screenOf` 的输出以前进过 `innerHTML`？要查）。

**A07 深色主题的原生侧对齐** `P1` `S`
系统切深色，状态栏图标也得跟着｜`SystemBars.setStyle({style: Dark|Light})` + `res/values-night/colors.xml` + `themes.xml` 的 `windowBackground`｜——｜——｜`paintNativeChrome()`（`ui.js`）已有 StatusBar 调用，扩成 SystemBars｜**风险**：`styles.css` 与 `res/values/colors.xml` 之间有"墨色对账"门 → 新增的夜纸值必须两处同时写。

**A08 小组件（Widget）** `P2` `L`
桌面上就能看见今天那三件事｜`AppWidgetProvider` + 一个只读的 JSON 快照（`files/` 下，由 WebView 写）｜——｜——｜**没有现成 Capacitor 插件**，要写原生 + 一套快照协议｜**风险**：L 且维护成本高；**建议先不做**，等"今日一笺"稳定三个月再说。ROADMAP 里 Widget 标的是"可选"。

**A09 无障碍与字号（已有，扩到新屏）** `P1` `S`
——｜新屏必须进 `dead_controls` / `contrast` / §48 字缩放 / §54 触摸目标尺寸｜CI｜——｜现有四道门已经很严（`dead_controls` 72 项、`contrast` 33 项）｜**风险**：不加门的新控件会在两轮后变成"按了没反应"。

---

## 4. 排期建议（4 个版本）

| 版本 | 主题 | 内容 | 为什么是这个顺序 |
|---|---|---|---|
| **v0.6** | 地基 | Y01 Y02 Y03 Y04 · S02 · A03 · G06/A09 | `dayLog` 与 `price` 是所有玩法的前置；edge-to-edge 是 targetSdk 36 的硬要求 |
| **v0.7** | 回来 | G01 G02 · N01 N02 N04 · S01 S03 · A01 A02 | 通知 + 分享接收 + 今日一笺 = "每天回来的理由"三件套 |
| **v0.8** | 变厚 | W01 W02 W03 · Y05 · N05 N06 · P01 · W04 N03 | 味笺从"排一次"变成"能做饭"；衣笺从"判一次"变成"能搭配"；设置页收口 |
| **v0.9** | 可发 | S03 S04 S05 · W07 · Y06 Y09 · A05 A06 A07 | 收藏册 + 年度长图 + 菜单图 = 传播面；愿望单是"少买"的收口 |

**P0 共 18 项**（逐字核对过清单里的标记）：

- 衣笺 4：Y01 Y02 Y03 Y04
- 味笺 3：W01 W02 W03
- 言笺 3：N01 N02 N04
- 全局 2：G01 G02
- 统计 3：S01 S02 S03
- 安卓 3：A01 A02 A03

合计 4+3+3+2+3+3 = **18**，正好由 v0.6 与 v0.7 两个版本装完。清单共 **56 项**（Y11 / W10 / N9 / G6 / S7 / P4 / A9）。

**刻意降到 P1 的**：Y05 搭配册（L 级，且要解决"照片会被 `SHED_AT` 清掉"的降级方案，不适合塞进第一批）、W04 家庭忌口档案（`state.people` 与 `normPerson()` 已经写好了，只差一个 `saved` 布尔，可顺手）、N03 今天/今晚（多一个 `slot` 字段）、P01 设置页收口（要动 `show()` / `backStack` / `screenOf()` 三处，单独搬一次不划算，适合和 v0.8 一起）。

---

## 5. 明确不做（负面清单）

| 不做 | 为什么 |
|---|---|
| 社交 Feed / 广场 / 评论 / 关注 | 品牌自杀（交接说明原话：空广场会毁品牌）；且微信个人主体做不了社交类目 |
| 商城 / 购买链接 / 商品抓取 | Whering、Stylebook 都在这条路上通向电商；笺的愿望单必须纯本地、无链接 |
| 虚拟试穿 / AI 生成穿搭图 | Acloset、Cladwell 都在做；与"静"冲突，且是云依赖 |
| Material You 动态取色 | 纸色 `#f4efe6` 与印章红 `#b54a3c` 是品牌资产；系统取色会把纸变成蓝的 |
| 排版自由画布（Stylebook 式） | L 级复杂度，与"少"冲突；搭配用"选 2–4 件"的轻形式即可 |
| 云同步 / 账号 / 登录 | 与"数据只在 localStorage、卸载即删除"的隐私承诺直接冲突 |
| 偷听 / 后台录音 / 常驻服务 | 硬约束；`ACTION_SEND` 是"用户主动分享"，不是"偷" |
| 排行榜 / 好友互看 | 社交变体 |
| 小组件（v0.6–v0.9） | L 且无现成插件；推迟到今日一笺稳定后 |
| 二手转卖 / 捐赠对接 | 会引出"交易"，滑向商城 |

---

## 6. 来源

**衣橱**
- [Stylebook 功能页（90+ features / Outfit Shuffle / cost-per-wear / calendar / stats / sizes）](https://www.stylebookapp.com/features.html)
- [Whering My Stats & Tags](https://whering.co.uk/faq/my-stats-and-tags)
- [Whering 单次穿着成本](https://whering.co.uk/faq/cost-per-wear)
- [Whering Planner](https://whering.co.uk/faq/what-is-the-planner)
- [Whering How it works](https://whering.co.uk/how-it-works)
- [Cladwell 官网（色彩/风格/缺口建议）](https://cladwell.com/)
- [Acloset 中文官网](https://www.acloset.app/zh-cn/)
- [爱搭衣橱](https://www.aidacloset.com/)
- [Indyx（SPA，正文抓不到）](https://www.indyx.com/features)

**菜谱 / 做饭**
- [Paprika 官网（买菜清单按货架分区 + 合并同类项 / 时长识别 / 份量缩放 / 月计划）](https://www.paprikaapp.com/)
- [AnyList 官网](https://www.anylist.com/)
- [Mealime（含 2026-10-21 关停公告）](https://www.mealime.com/)
- [下厨房首页](https://www.xiachufang.com/)
- [下厨房「流行菜单」（recipe_list）](https://www.xiachufang.com/explore/menu/collect/)
- [豆果美食（含「智能找菜」）](https://www.douguo.com/)
- [Whisk（三星子公司，Samsung Food）](https://whisk.com/)

**待办 / 笔记**
- [滴答清单功能页（四视图 / NLP / 提醒 / 习惯 / 小组件）](https://ticktick.com/features)
- [Things 功能页（Today / This Evening / Upcoming / Quick Find / Jump Start）](https://culturedcode.com/things/features/)
- [Todoist 功能页](https://www.todoist.com/features)
- [flomo 官网](https://flomoapp.com/)
- [flomo 每日回顾](https://help.flomoapp.com/advance/lucky.html)
- [flomo 热力图与统计（含年统计生成年度分享图）](https://help.flomoapp.com/advance/notes-graph.html)
- [Bear](https://bear.app/)
- [Cubox](https://cubox.pro/)
- [Day One](https://dayoneapp.com/features/)

**安卓**
- [Capacitor Local Notifications（Android 13 权限 / 精确定时 / Doze 9 分钟）](https://capacitorjs.com/docs/apis/local-notifications)
- [Capacitor App（getLaunchUrl / appUrlOpen / backButton / toggleBackButtonHandler）](https://capacitorjs.com/docs/apis/app)
- [Capacitor SystemBars（insetsHandling / WebView<140 安全区 bug）](https://capacitorjs.com/docs/apis/system-bars)
- [Capacitor Share（files / file_paths.xml）](https://capacitorjs.com/docs/apis/share)
- [Android 接收其他应用的数据](https://developer.android.google.cn/develop/ui/compose/sharing/receive)
- [Android 预测性返回手势](https://developer.android.google.cn/guide/navigation/custom-back/predictive-back-gesture)
- [Android edge-to-edge](https://developer.android.google.cn/develop/ui/views/layout/edge-to-edge)
- [Android 通知运行时权限](https://developer.android.google.cn/develop/ui/views/notifications/notification-permission)
- [Material 3 色彩角色](https://m3.material.io/styles/color/roles)
