/** 笺 · 外部入口
 *
 *  三条「从外面进来」的路，全在这里收口：
 *  1. **系统分享**（安卓 ACTION_SEND）：别的 App 里选中一段话 → 分享 → 笺。
 *     MainActivity 把文字通过 `window.__jianShare(text)` 递进来。
 *  2. **深链参数**：jian://screen/yi?new=白衬衫、jian://screen/yan?text=…（见 ui.js 的 openDeep）。
 *  3. **桌面快捷方式**：jian://screen/today 等。
 *
 *  为什么单开一个文件：这三条路都是**别人调用我们**，它们的失败方式很特别——
 *  进来的时候 App 可能还没 boot 完（分享是冷启动进来的第一件事），也可能是热启动
 *  （App 已经在后台，WebView 活着）。两条路必须汇到同一个函数，否则「冷启动能用、
 *  热启动丢内容」这种 bug 会一直存在。
 */

/** 冷启动时原生可能比 boot() 更早把文字递进来：先存在这里，boot 完再消费。 */
let pendingShare = null;
/** boot() 结束时把它设 true：在此之前进来的分享先进 pendingShare。 */
let shareReady = false;

/** 原生侧调用入口。必须是同步、永不抛的——它在 Java 的 evaluateJavascript 里跑。 */
window.__jianShare = function (text) {
  const t = String(text == null ? "" : text).slice(0, 4000);
  if (!t.trim()) return false;
  if (!shareReady) { pendingShare = t; return true; }
  consumeShare(t);
  return true;
};

/** 消费一段分享进来的文字：贴进言笺并**不自动捞**（捞是一次判定，要扣点，得用户自己按）。
 *  但要说清楚「已经贴好了，按一下捞成笺」——静默填入是最坏的一种。 */
function consumeShare(text) {
  const t = String(text || "").trim();
  if (!t) return;
  try {
    // 已经有内容时不覆盖：追加到后面（用户可能先手打了几句）
    const cur = String(state.yanText || "").trim();
    const joined = (cur ? cur + "\n" : "") + t;
    state.yanText = joined.slice(0, 4000);
    save(state);
    const el = $("#yanText");
    if (el) el.value = state.yanText;
    show("yan");
    // 有「要买 / 周五 / 记得」这类字样时说一句更有用的话——它预告了捞出来会得到什么
    const hint = /买|下单|快递|药/.test(t) ? "看起来是件要买的东西"
      : /(明天|后天|下周|周[一二三四五六日]|\d+月\d+日|之前|记得|别忘)/.test(t) ? "里面有时间，捞出来会带上"
        : "按「捞成笺」就会分成待办、要买、已定、还没说清";
    toast("已贴进言笺。" + hint, 3200);
    haptic("LIGHT");
    logEvent("catch", "yan", "share");
  } catch (e) { console.warn("share", e); }
}

/** boot() 末尾调：把早到的分享补消费掉。 */
function flushShare() {
  shareReady = true;
  if (pendingShare) {
    const t = pendingShare;
    pendingShare = null;
    consumeShare(t);
    return true;
  }
  return false;
}

/** 系统「返回 App」时，如果用户是从别的 App 分享过来又退回去，再分享一次：
 *  热启动走的是同一个 __jianShare（MainActivity 的 onNewIntent），这里不用额外挂。 */
