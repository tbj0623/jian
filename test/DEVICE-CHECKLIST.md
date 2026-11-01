# 逐屏检查单（真机/模拟器截图用）

这份不是「跑完的门」，是**眼睛要看的那一栏**。截图存在 `test/shots-device/`，
每条观感回到报告里时请写成「文件名 + 一句话 + 有没有缺陷」，别只写「正常」。

## 0. 先看这四条（任何一张截图都适用）

| 看什么 | 什么样的不对 | 为什么它值得单列 |
| --- | --- | --- |
| 文字被截断 | 中文被切掉半个字 / 省略号吃掉关键名词 / 行高把字压进下一行 | 安卓 WebView 的字体缩放会把固定 px 高度顶破，而 `textZoom` 是原生侧报的倍数（MainActivity.applyFontScale），桌面浏览器永远复现不出来 |
| 颜色不对 | 印章红不是 #b54a3c（夜里 #c97164）/ 纸不是 #f4efe6（夜里 #1b1917）/ 出现青绿或纯黑 | 原生 res 与 CSS 是两份颜色定义，只有设备能证明两边没分家 |
| 留白奇怪 | 首屏末尾一大片空 / 关键内容被推到一屏之外 / 两段之间忽然多出半屏 | 这一版的屏是 0.6.0 新拼的，空容器（`#todayStats`、`#album` 这类）没数据时最容易留下一块 |
| 底栏遮挡 | 最后一行被底栏压住、按钮只露一半、`env(safe-area-inset-bottom)` 没吃到 | 指南第 6 节记过：这台机器上 WebView 没铺到屏幕边，安全区恒为 0，所以「遮挡」只能靠截图看 |

## 1. 十一屏各自最该盯的地方

| 屏 | 文件名 | 这一屏的核心 | 具体盯什么 |
| --- | --- | --- | --- |
| 今日 | `今日.png` | 永远只三件事 | 三件事是否真的只有三件；`#todayStats` 那组数字有没有空壳；「我的这一年」按钮在不在首屏内 |
| 衣笺 | `衣笺.png` | 一个动作（过笺） | 那张「点这张纸，放照片」的大纸有没有塌；下面四枚页签（过笺/柜子/搭配/愿望）有没有被底栏压住；引擎提示那行（`#engineHint`）在右上角是否折行 |
| 味笺 | `味笺.png` | 这桌能入口 | 页签「做菜」「买菜」上的计数角标（`.cnt`）在空数据时是不是一个孤零零的 0；「排这桌」按钮与上面的 textarea 间距 |
| 言笺 | `言笺.png` | 贴一段话 | 输入框高度是否被压；框下面三枚小签（放图片/到点提醒/摘一句）有没有挤成两行；`#yanOut` 空态那一段 |
| 笺谱 | `笺谱.png` | 用过的日子 | 热力图（`#puHeat`）在没有记录时是不是一片空白框；返回那枚 chip 与标题是否同一行 |
| 册 | `册.png` | 我的档 | 笺点卡片右上角那枚装饰印（`.stampcard .corner`）有没有被裁掉一角（`overflow:hidden`，指南记过 3.0× 字号会裁）；「导出备份 / 导入备份」两枚按钮是否等宽 |
| 章 | `章.png` | 一枚一枚攒 | 徽章网格（`.badge-grid`）在只解锁少数几枚时，未解锁的是灰还是空白；`#badgeNote` 那行说明有没有压到网格上 |
| 这一年 | `这一年.png` | 年度总结 | 大数字与单位是否错位；最底部一行有没有被底栏盖住 |
| 设置 | `设置.png` | 把笺调顺 | 每一组之间是否有一致的分隔；开关（外观三档、字号三档）在选中态是否看得出来（不只是颜色，还有 `aria-pressed`） |
| 找东西 | `找东西.png` | 一次搜遍 | 搜索框是否在首屏顶部（不是滚下去才有）；历史 chips（`#searchHist`）空的时候有没有留一条空行 |
| 提醒 | `提醒.png` | 到点提醒 | 顶部那三行权限说明（`#remindPermState`）说的是不是真话（装了 App 就该说「通知权限…」，不该说「浏览器里没有系统通知」）；四条分段（已过期/今天/往后/办完）在空数据时是否各自都摆了一个空标题 |

## 2. 深色三屏（`dark-今日.png` / `dark-衣笺.png` / `dark-册.png`）

深色最容易出的不是「不够黑」，是**亮块**——某一块还留着白天的底色，在夜纸上像手电筒。

| 看什么 | 典型位置 |
| --- | --- |
| 亮块 | 卡片（`.card` / `.sheet`）的底、输入框、chip 选中态、`details` 展开区、toast |
| 系统条图标 | 状态栏时间/电量在 #1b1917 上必须是**浅色**；nav 手势条同理（`values-night/styles.xml` 的 windowLight*Bar=false） |
| 纸色 | 主色应当是 #1b1917，不是纯黑 #000（纯黑 = 算法反色没挡住） |
| 印章红 | 夜里是 #c97164（降了饱和），不是白天那支 #b54a3c |
| 分隔线 | `--line: #35302a` 在夜纸上要看得见但不刺眼；太亮就成了第二条底栏 |
| 长图 | 这一条不在这三张里：**长图永远是白天的纸**（card.js 不走主题），验它要另存一张长图 |

## 3. 原生能力 ↔ 证据对照表

每一项都要能指到「哪一行输出/哪一张图」才算验过，不接受「应该没问题」。

| 能力 | 看哪一行证据 | 期望 |
| --- | --- | --- |
| 通知渠道 | `dumpsys notification --noredact` 里 `mId='jian-remind'` 那一段 | `mName=到点提醒`、`mImportance=3`、`mLockscreenVisibility=2` |
| 通知权限 | `settings get secure notification_badging` + `dumpsys package com.jian.app \| grep POST_NOTIFICATIONS` | 权限是 `granted`（API 33+ 是运行时权限；模拟器上首次 schedule 会弹框，见 §4） |
| 真弹一条 | `dumpsys notification` 里 `NotificationRecord(... pkg=com.jian.app ...)` 那一段 | `channel=jian-remind`、`tickerText`/`android.title=笺 · 提醒`、`android.text` 是你写的那句话 |
| 排上了但没到点 | `dumpsys alarm \| grep com.jian.app` | 有 RTC 类型的一条，且**不是** `setExact*`（没有 SCHEDULE_EXACT_ALARM 是设计） |
| 分享冷启动 | 言笺输入框里有那句话 + 落在言笺 | 走 `am start -a android.intent.action.SEND` |
| 分享热启动 | 第二句**追加**在第一句后面 | 走 `onNewIntent`；覆盖 = 失败 |
| 五枚快捷方式 | `cmd shortcut get-shortcuts com.jian.app` | `yi/wei/yan/today/note` 五枚，`shortLabel` 是中文，`intents=` 里有 `jian://screen/…` |
| 深链 | `am start -a VIEW -d jian://screen/<id>` 之后落的屏 | today/yi/wei/yan/pu/me 六个 id 都要认 |
| 九个返回键 | 每按一次 `KEYCODE_BACK` 之后落的屏 | 子页 → 父屏；栈底才退后台（`yi-report/yi-item/yi-outfit/wei-dish/wei-week/yan-remind/settings/badges/year/search`） |
| 深色纸色 | 截图像素统计的主色 | 亮 #f4efe6 / 暗 #1b1917，逐通道差 ≤ 12 |
| 系统条图标 | 深色截图顶部 100px 内最亮的像素 | 夜里是浅色（时间/电量可见），白天是深色 |

## 4. 只在 API 35 上成立的几条（与指南 §6.5 的差异）

> 本机 AVD 是 **AOSP API 35（Android 15）**，指南 §6.5 是按 13/14 写的。以下是实机差异，
> 已汇总进 `test/DEVICE-API35-NOTES.md`，这里只列会影响「怎么判」的部分。

1. **`settings get secure ui_night_mode` 在无人改过时返回 `null`**，不是 `1`/`2`。
   判「切到夜间了」要用 `cmd uimode night` 回显的 `Night mode: yes`，不要断言那个 secure 值等于 2。
2. **`dumpsys notification` 里渠道是 `NotificationChannel{mId='…'}`**（一行内联），
   不在单独一段里；`grep -A4 'jian-remind'` 常常只能抓到一行，需要按 `NotificationChannel{` 切。
3. **`dumpsys shortcut` 在 API 35 里先把所有包的快捷方式混排**，且每条带缩进；
   `PackageInfo:` 区段里的 `IsShadow: false (installed)` 才是「这个包真的扫到了」。
   用 `cmd shortcut get-shortcuts <pkg>` 更稳（只出这一个包的）。
4. **`POST_NOTIFICATIONS` 的弹框时机**：插件 `LocalNotificationsPlugin.kt` 的
   `shouldRequestNotificationPermission()` 是「SDK ≥ 33 且尚未 granted」→ 在 **schedule() 那一刻**
   就弹运行时权限框（不是 checkPermissions）。所以「排一条提醒」这一步在模拟器上会先出现一个系统框，
   点掉之后 schedule 才继续；自动化脚本必须预料到这一帧，不能当成「App 卡住了」。
5. **`--noredact` 在 API 35 上仍然要特权**：模拟器是 userdebug 所以能拿到正文；
   真机上`adb shell dumpsys notification` 不给 `android.text`。验收报告里要写清「这是模拟器特权输出」。
