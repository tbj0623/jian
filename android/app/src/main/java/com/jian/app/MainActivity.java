package com.jian.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.res.Configuration;
import android.os.Build;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.WebViewListener;
import org.json.JSONObject;

/**
 * 安卓壳自己那份代码：字体缩放、通知渠道、系统分享接收、系统条配色。
 *
 * 三件事各有一个「不写会怎样」，都写在对应方法头上。这里只记一条总原则：
 * 这个类里**不许**出现业务判定。所有「这段文字怎么处理」「夜里该不该黑」都由网页决定，
 * 原生只负责「把它递进去」与「把系统的状态告诉它」——两边各有一套判定就等于有两套真相。
 */
public class MainActivity extends BridgeActivity {

    /** remind.js 里 scheduleNative() 写死的渠道名。改一边不改另一边，通知会静默不弹
     *  （安卓 8+ 往一个不存在的渠道发通知，系统直接丢掉，连异常都不报）。 */
    public static final String CHANNEL_REMIND = "jian-remind";

    /** 分享进来的文字上限，与 share.js 的 slice(0, 4000) 是同一个数。
     *  在原生这侧先截断的理由：一条几十万字的分享（比如整篇网页）走
     *  evaluateJavascript 会拼出几 MB 的脚本，WebView 直接卡住甚至 ANR——
     *  而那发生在「用户想分享一段话」这么小的一件事上。 */
    private static final int SHARE_MAX = 4000;

    /** 冷启动时分享比网页先到：先存在这里，等 onPageLoaded 再递。 */
    private String pendingShare = null;

    /** 网页加载完了没有。没加载完就 evaluateJavascript，脚本会跑在 about:blank 上然后被冲掉。 */
    private boolean pageLoaded = false;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        applyFontScale();
        ensureRemindChannel();
        // 冷启动的分享藏在启动那条 Intent 里（launcher 那条没有 EXTRA_TEXT，取出来是 null）。
        // 注意这里的 null 判断不是多余的：super.onCreate() 内部会走一遍 onNewIntent(getIntent())
        // （BridgeActivity.load() 的最后一行），热启动那条重载**已经在上面跑过一次**，
        // 而且它会把 EXTRA_TEXT 抹掉（防止配置变化时重复贴一遍）——所以这里再读一次
        // 得到的必然是 null。不判断就写回 null，冷启动的分享会被自己抹掉。
        if (pendingShare == null) pendingShare = readShareText(getIntent());
        // 网页那边要等 onPageFinished 才敢递；Bridge 提供的监听点就是这一条。
        Bridge bridge = getBridge();
        if (bridge != null) {
            bridge.addWebViewListener(new WebViewListener() {
                @Override
                public void onPageLoaded(WebView webView) {
                    pageLoaded = true;
                    flushShare();
                    followWebTheme();
                }
            });
        }
        syncSystemBarIcons(isNightMode());
    }

    /**
     * 热启动：singleTask 下「分享 → 笺」走到这里，而不是再走一遍 onCreate。
     *
     * 不覆盖这一条会怎样（实测过的典型坏法）：App 停在后台，用户在浏览器里选中一段话
     * 分享给笺，App 被叫到前台，界面一切正常，**那段话没了**——因为 onCreate 早就跑完了，
     * 没有任何人读新来的那条 Intent。这类 bug 特别难报：它只发生在「已经开着 App」的时候。
     */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String text = readShareText(intent);
        if (text == null) return;
        // 读完就抹掉：这条 Intent 会被当成 getIntent() 留着，不抹的话下一次
        // 因配置变化（如字体、深浅色）重建 Activity 会把同一段话再贴一遍。
        intent.removeExtra(Intent.EXTRA_TEXT);
        if (pageLoaded) deliverShare(text);
        else pendingShare = text;
    }

    /** 系统深浅色跟着换的时候（configChanges 里有 uiMode，所以 Activity 不重建）。 */
    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        syncSystemBarIcons((newConfig.uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES);
        // 网页的 prefers-color-scheme 会自己变，主题随之重算；这条兜底负责把
        // 「重算之后该是什么样」再钉一次（见 followWebTheme 的注释）。
        followWebTheme();
    }

    /**
     * 把系统的「设置 → 显示 → 字体大小」交进 WebView。
     *
     * 不写这一条会怎样：WebView 的 textZoom 默认就是 100，Capacitor 也不代它去读 fontScale，
     * 所以用户把字号拉到最大，这个 App 一个字都不会变大——不是「版式撑不住」，是根本没响应。
     * 安卓的 font zoom 乘的是算出来的字号（与 px / rem 写法无关），所以真正需要确认的是
     * 「字变大了，写死的 px 高度会不会把字裁掉」。这一版是按 1.5×、2.0× 逐屏量过的
     * （见 test/e2e.playwright.py §48）：不溢出、不裁字，行高全是无单位比值所以自己会长。
     * 滑杆最大那档（2.0×）是量过没坏的；再往上到 3.0× 只有一件事会坏——笺点那张卡右上角
     * 的装饰章会被卡片自己的 overflow:hidden 裁掉一角，它是 aria-hidden 的装饰，正文一字不损。
     *
     * fontScale 不在 AndroidManifest 的 configChanges 里，所以改字号会重建 Activity，
     * 这里只需要在 onCreate 重新报一次倍数，不用另挂配置变化回调。
     */
    private void applyFontScale() {
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) return;
        float scale = getResources().getConfiguration().fontScale;
        WebSettings settings = bridge.getWebView().getSettings();
        // fontScale 理论上能到 3.x，textZoom 的范围是 0..1000，四舍五入后不会越界
        settings.setTextZoom(Math.round(scale * 100f));
    }

    // ───────────────────────── 通知渠道 ─────────────────────────
    /**
     * 建「到点提醒」这条渠道。
     *
     * 为什么要在原生侧建，而不是让网页调 LocalNotifications.createChannel()：
     * 网页那条路是一次异步插件调用，而 remind.js 在**开机恢复**时（rescheduleAll）
     * 可能比它先跑到——通知已经排上、渠道还没建，安卓 8+ 会安静地把它丢掉。
     * 渠道是幂等的：同名再建一次只会更新描述，不会重置用户改过的开关。
     *
     * importance 用 DEFAULT（有声音、会亮、不弹 heads-up）：
     * 笺的提醒是「到点提醒你一下」，不是闹钟；用户不该在写东西时被一条提醒打断。
     * 文案写「大约这个点」也是同一个口径——没有精确闹钟权限，Doze 下本来就会晚几分钟。
     */
    private void ensureRemindChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        NotificationChannel ch = new NotificationChannel(
                CHANNEL_REMIND, getString(R.string.channel_remind_name),
                NotificationManager.IMPORTANCE_DEFAULT);
        ch.setDescription("言笺里定了时间的那些话，到点提醒一次");
        // 锁屏上不显示正文：提醒的内容是用户贴进来的聊天记录片段，
        // 默认摊在锁屏上等于替用户公开他的私事。想看正文要点进应用。
        ch.setLockscreenVisibility(android.app.Notification.VISIBILITY_PRIVATE);
        nm.createNotificationChannel(ch);
    }

    // ───────────────────────── 系统分享接收 ─────────────────────────
    /** 从 ACTION_SEND + text/plain 里取那一段字；不是分享动作就返回 null。 */
    private static String readShareText(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return null;
        if (intent.getType() == null || !intent.getType().startsWith("text/")) return null;
        CharSequence cs = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
        if (cs == null) {
            // 少数 App 只给 String extra 不给 CharSequence，这一句是兼容而不是冗余
            String s = intent.getStringExtra(Intent.EXTRA_TEXT);
            cs = s;
        }
        if (cs == null) return null;
        String text = cs.toString().trim();
        if (text.isEmpty()) return null;
        return text.length() > SHARE_MAX ? text.substring(0, SHARE_MAX) : text;
    }

    private void flushShare() {
        if (pendingShare == null) return;
        String text = pendingShare;
        pendingShare = null;
        deliverShare(text);
    }

    /**
     * 把文字递进网页：`window.__jianShare(text)`。
     *
     * 协议名为什么叫这个：网页那边 share.js 的接收端就是这个签名（Lead 已接好），
     * 它负责「冷启动先存着、boot 完再消费」的全部时序。原生这侧只做三件事——
     * 限长、转义、投递到 WebView 的 UI 线程。
     *
     * 转义用 org.json.JSONObject.quote()：手写 replace 的话漏掉一个反斜杠或
     * U+2028 就能让整段脚本语法错误——而 evaluateJavascript 的语法错误
     * **不会抛异常**，它只会安静地什么都不做，最后表现成「分享进来没反应」。
     */
    private void deliverShare(String text) {
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) {
            pendingShare = text;
            return;
        }
        String js = "window.__jianShare && window.__jianShare(" + JSONObject.quote(text) + ");";
        bridge.getWebView().post(() -> {
            WebView wv = getBridge() == null ? null : getBridge().getWebView();
            if (wv != null) wv.evaluateJavascript(js, null);
        });
    }

    // ───────────────────────── 系统条与深浅色 ─────────────────────────
    private boolean isNightMode() {
        return (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
    }

    /**
     * 状态栏那一排图标：白天要深色（压在纸上），夜里要浅色（压在夜纸上）。
     *
     * 为什么原生也要管一次：Capacitor 的 StatusBar 插件只在初始化时按 uiMode 选一次
     * （DEFAULT 分支），之后**没有人**在配置变化时重算——而 configChanges 里带着 uiMode，
     * Activity 不重建，插件也就不会再初始化。结果就是：开着 App 把系统切到深色，
     * 时间与电量立刻变成深色图标压在一片 #1b1917 上，等于消失。
     */
    private void syncSystemBarIcons(boolean night) {
        try {
            WindowInsetsControllerCompat c = WindowCompat.getInsetsController(
                    getWindow(), getWindow().getDecorView());
            c.setAppearanceLightStatusBars(!night);
            c.setAppearanceLightNavigationBars(!night);
        } catch (Exception ignored) {
            // 系统条这种装饰性的事不值得让 App 崩；插件那条路还在
        }
    }

    /**
     * 让系统条跟上**网页实际用的主题**。
     *
     * 为什么不是在原生侧按 uiMode 直接定死：用户可以在「册 → 外观」里选亮/暗，
     * 那时的纸色与系统深浅色是两回事，而 status bar 压在网页那张纸上——
     * 只能问网页现在是什么主题。这里挂一个 MutationObserver 盯 <html data-theme>，
     * 每次变化就把「该深还是该浅」重新报给 StatusBar 插件。
     *
     * 与 ui.js 的 paintNativeChrome 的关系：那一条是网页主动报，这里是原生兜底。
     * 两条同时存在是幂等的（同样的 setStyle 调两次没有副作用），
     * 而少任何一条都会在「热启动换主题」这种时序里露出一帧错的图标。
     */
    private void followWebTheme() {
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) return;
        String js = "(function(){try{"
                + "var r=document.documentElement;"
                + "var go=function(){try{"
                + "var d=r.getAttribute('data-theme')==='dark';"
                + "var P=window.Capacitor&&window.Capacitor.Plugins&&window.Capacitor.Plugins.StatusBar;"
                + "if(P&&P.setStyle)P.setStyle({style:d?'DARK':'LIGHT'});"
                + "}catch(e){}};"
                + "go();"
                + "if(window.__jianChromeObs)window.__jianChromeObs.disconnect();"
                + "var o=new MutationObserver(go);"
                + "o.observe(r,{attributes:true,attributeFilter:['data-theme']});"
                + "window.__jianChromeObs=o;"
                // 再补几个一次性重放：boot() 是异步的（要先从 Preferences 捞备份再 THEME.init），
                // 主题可能落得比 onPageFinished 还晚；而 ui.js 的 paintNativeChrome 目前
                // 无条件报 LIGHT，夜里那张纸会被它盖回深色图标。这里是**兜底**不是修法：
                // 正解是 paintNativeChrome 按 THEME.dark() 分叉，已报给 Lead。
                // 只放三次一次性定时器（0 / 400ms / 1500ms），不起常驻轮询。
                + "setTimeout(go,0);setTimeout(go,400);setTimeout(go,1500);"
                + "}catch(e){}})();";
        bridge.getWebView().post(() -> {
            WebView wv = getBridge() == null ? null : getBridge().getWebView();
            if (wv != null) wv.evaluateJavascript(js, null);
        });
    }
}
