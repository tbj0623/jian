# API 35（Android 15）与指南 §6.5 的差异清单

> **只标不改。** `docs/安卓自验指南.md` 不在我的可改范围（本轮硬约束：只许改 `test/`），
> 所以把跑之前核对出来的、与「13/14 口径」不符的地方集中记在这里，供统一重写时取用。
> 每条都标了「哪一句」「13/14 是什么」「API 35 实测是什么」「判据该怎么改」。

## 台面上的事实

本机唯一能用的 AVD 是 `jian_test`，系统镜像是 **`system-images/android-35/default/x86_64`**
（`~/.android/avd/jian_test.avd/config.ini` 的 `image.sysdir.1`），
即 **AOSP API 35 / Android 15 / 无 Google Play**。本机 `$ANDROID_HOME/platforms` 只有
`android-35` 与 `android-36` 两个平台，**没有 13/14 的镜像可选**——所以指南里凡是写
「安卓 13/14」的行为预期，在这台机器上都得按 15 重新对一遍。

APK 本身：`versionCode 28 / versionName 0.6.0`，`minSdk 24`、`**targetSdk 36**`、`compileSdk 36`。
targetSdk 36 这件事下面第 3 条会用到。

---

## 1. §6.5.3「系统确实切到了夜间」的判据不成立

- **指南写的是**（`device_deeplink.py` 原来也照着写）：
  `settings get secure ui_night_mode` 应回 `"2"`。
- **13/14 上**：这个值确实是 `2`（`UI_NIGHT_MODE_YES`）——只要有人在设置里动过一次。
- **API 35 实测**：**没人动过时它是 `null`**（本机实测 `settings get secure ui_night_mode` → `null`），
  而此时 `cmd uimode night` 明明回 `Night mode: no`/`yes`。
  也就是说这个 secure 值回答的是「用户有没有手动覆盖过」，
  不是「此刻是不是夜间」。
- **改法**：问 UiModeManager 本人——`adb shell cmd uimode night`，
  输出里 `Night mode: yes|no|auto`。已改在 `test/device_deeplink.py` §5。

## 2. §6.5.4 快捷方式：`dumpsys shortcut` 的输出形状变了

- **指南写的是**：`dumpsys shortcut | grep -A2 'com.jian.app'`。
- **13/14 上**：一个包的快捷方式常常是连续的一段，`-A2` 能抓到 `ShortcutInfo` 头两行。
- **API 35 实测**：
  - 整份 dump 把所有包**混排**，且新增了 `PackageInfo:` / `IsShadow: false (installed)` /
    `Launcher: com.google.android.as` 这些区段；本机整份 dump 一万多行、要 8~12 秒。
  - 用 `grep -A2` 基本只能抓到 `ShortcutInfo {id=…, flags=0x1a4 [ImManIc-rStr]` 和
    `packageName=com.jian.app` 两行，**抓不到 `shortLabel` / `intents`**，
    而这两样才是「五枚挂上了没有」「地址对不对」的判据。
  - 标签形状是 `shortLabel=过一件衣, resId=2131…[shortcut_yi_short]`：
    中文在，但后面**一定**跟着 `resId=`。原来那条
    「短标签不是 `res/` 开头」的断言在新格式里恒为真（因为值里根本没有 `res/` 前缀），
    等于量空气。
- **改法**：
  - 取值改用 `cmd shortcut get-shortcuts com.jian.app`（只出这一个包，格式与 dumpsys 内那段逐字相同，
    实测快一个量级）；`dumpsys shortcut` 留作兜底。
  - 「标签取到了中文」改成判断**值里有汉字**（`[\u4e00-\u9fff]`），不再判断前缀。
  - 已改在 `test/device_deeplink.py` §4。

## 3. Android 15 的强制 edge-to-edge：`statusBarColor` 在 15+ 上已经不生效

- **指南 §6.5.3 说**：「夜里状态栏/手势条要求浅色图标（`windowLightStatusBar=false`）」，
  并依赖 `res/values-night/styles.xml` 里的 `statusBarColor` / `navigationBarColor`。
- **13/14 上**：这两条 `android:statusBarColor` / `android:navigationBarColor` 决定系统条底色。
- **API 35 实测 + 文档事实**：只要 `targetSdk ≥ 35`，应用被强制 edge-to-edge，
  **`Window.setStatusBarColor()` / `setNavigationBarColor()` 不再有任何视觉效果**，
  系统条底色由应用自己画在下面那层决定。
  本项目的 `ui.js` 注释里已经记了这一条（「安卓 15 起强制 edge-to-edge，插件自己标注
  setBackgroundColor / overlaysWebView 在 15+ 已失效」），所以**代码是对的**，
  但**指南 §6.5.3 的说法在 15 上会误导人**：它让人以为「夜里系统条会变成夜纸色」是靠 res 那两条，
  其实靠的是网页 body 铺到条下面。
- **顺带一条与 §6 那段「安全区恒为 0」有关的观察**：正因为 15 强制 edge-to-edge，
  在这一台上 `env(safe-area-inset-bottom)` **不应该**是 0。指南第 6 节那条
  「WebView 没铺到屏幕边、安全区恒为 0」的实测记录，很可能是 0.6.0 之前（targetSdk 更低时）
  留下的；如果这一轮在 API 35 上量到的安全区不是 0，那段结论与它连带的
  「`--sab` 覆写成 48px 的模拟验证」都需要重写。**本轮以截图与量到的值为准。**
- **改法建议**：§6.5.3 那句改成「系统条图标深浅由 `windowLightStatusBar` 管（这一条在 15 上仍然生效）；
  系统条**底色**在 15+ 不再由 res 决定，跟着网页那张纸走，所以截图里条上不应该出现第二种底色」。

## 4. §6.5.1 `POST_NOTIFICATIONS` 的弹框**时机**：不是 check，是 schedule

- **指南写的是**：「安卓 13/14 上第一次排提醒弹不弹运行时权限框」，没写清是哪一步弹。
- **插件实测**（`@capacitor/local-notifications` 8.3.1，
  `LocalNotificationsPlugin.kt:101`）：
  ```kotlin
  private fun shouldRequestNotificationPermission(): Boolean =
      Build.VERSION.SDK_INT >= TIRAMISU && getPermissionState(LOCAL_NOTIFICATIONS) != PermissionState.GRANTED
  ```
  只在 `schedule()` / `update()` 里查，`checkPermissions()` 不查也不弹。
  也就是说：**用户第一次按「定下来」的那一刻**会先被系统权限框挡一下，
  点允许之后那条通知才真的排上（`scheduleAfterPermission` 回调）。
- **13/14 与 15 在这一条上没有区别**，区别在于 15 的权限框文案与「拒绝两次之后不再弹」的更严格实现。
  对脚本的影响是：自动化里必须在排之前 `pm grant`，否则会卡在一个系统框上，
  看起来像「通知没弹」——这是**测试环境**问题，不是产品缺陷。
  已在 `test/device_accept.py` 里显式 `pm grant com.jian.app android.permission.POST_NOTIFICATIONS`
  并注明原因。
- **改法建议**：§6.5.1 补一句「权限框在这一步弹：第一次 schedule 时，而不是进言笺时」。

## 5. `dumpsys notification --noredact` 的正文

- **指南写的是**：`dumpsys notification --noredact | grep -A3 'jian-remind'`，
  期望看到 `mId='jian-remind'  mName=到点提醒  mImportance=3  mLockscreenVisibility=2`。
- **API 35 实测**：渠道是**一整行内联**的
  `NotificationChannel{mId='jian-remind', mName=到点提醒, mDescription=…, mImportance=3,
  mBypassDnd=false, …, mLockscreenVisibility=2, …}`，
  后面还跟着 `mSound / mVibrationEffect / mUserLockedFields / mBlockableSystem / mParent / mDemoted…`。
  所以 `-A3` 抓到的三行里**不一定**有 `mImportance`——它在同一行里，可能在第 300 个字符之后。
  按 `NotificationChannel{` 切开、再在那一块里找 `mId=` / `mImportance=` / `mLockscreenVisibility=` 才稳。
- **改法**：见 `test/device_accept.py` 的 `channel_block()`。
- 另一条：`--noredact` 要在 userdebug/eng 上才有正文（本机 AVD 是 `userdebug/dev-keys`，能拿到）；
  **真机上 `adb shell dumpsys notification` 不给 `android.text`**。
  报告里贴这段证据时要写明「这是模拟器特权输出」，别让人以为零售机能这样读到用户通知内容。

## 6. `cmd uimode night` 的写法与回显

- 指南 §6.5.3 用的是 `cmd uimode night yes` / `no`——**这一条 15 上照样成立**，
  回显是 `Night mode: yes` / `Night mode: no`（不是 13 上的空输出）。
- 但要注意：`cmd uimode night`（不带参数）是**读**，输出同样是 `Night mode: …`。
  脚本里判「切过去了没有」就读这一句，不要读 secure 设置（见第 1 条）。

## 7. `dumpsys gfxinfo` 的字段

- 指南没写，`test/device_perf.py` 用 `Total frames rendered:` 与 `Janky frames`。
- **API 35 实测**：两者都在，但多了一行 `Janky frames (legacy):`。
  现有脚本用 `if "Janky frames" in l` 取**第一行**，取到的是新那个口径（对的）。
  如果哪天有人改成取最后一行，会拿到 legacy 那个数——两者的差别在本机桌面上实测是
  81.31% vs 77.57%，差 4 个百分点，足够让一条预算误判。
- **不改代码**，只在这里记一笔：`device_perf.py` 现在的取法（取第一行）是对的。

## 8. `WebView` 版本

- 指南 §6.5 与 `device_perf.py` 的注释都写「WebView 124」。**API 35 上仍是 124.0.6367.219**
  （本机实测 `dumpsys package com.google.android.webview`），所以这一条**不需要改**。
  记在这里是因为一旦哪天镜像升级到 WebView 13x，`device_perf.py` 里那八条预算的基线
  （注释里那些「14 / 143」「2.4 / 19」）就失去了可比性，得重测一遍。

---

## 汇总成一句

指南 §6.5 里**与 API 35 不符**的一共四处：
**§6.5.3 的夜间判据**（secure 值是 null）、**§6.5.4 的 dumpsys shortcut 形状**（抓不到 label/intents）、
**§6.5.3 的 statusBarColor 说法**（15+ 强制 edge-to-edge 已失效）、
**§6.5.1 的权限框时机**（在 schedule 不是 check）。
另外 §6 那段「安全区恒为 0」在 targetSdk 36 + Android 15 上大概率已经不成立，需要在真机上重测。
这五处我都已经在 `test/` 里按实测行为改成了正确判据，代码侧的改动逐处带注释（注释里写清了 13/14 与 15 的差别）。
