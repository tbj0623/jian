/** 笺 · 主题与外观
 *  亮 / 暗 / 跟随系统、字号三档、动效开关、印章款式、触感开关。
 *
 *  为什么单独一个文件：这些开关影响的是**根节点**（<html data-theme>）与各处 CSS 变量，
 *  而不是某一屏的渲染。它们必须在 state.js 之后、任何渲染之前就能被读到，
 *  所以放在 ui.js 之前加载（index.html 里紧跟 config.js）。
 *
 *  三条硬规矩：
 *  1. **纸只有两种说法：白天的纸、夜里的纸。** 不做 Material You 动态取色——纸色与印章红
 *     是品牌资产，让系统从壁纸取色会把纸变成蓝的。
 *  2. **长图永远是白天的纸。** card.js 画出来的 1080×1920 是发给别人看的，
 *     夜里存一张黑底长图贴到群里，看起来像另一个 App。所以 card.js 的取色**不走主题**。
 *  3. **原生状态栏跟着主题走**（ui.js 的 paintNativeChrome 读 THEME.dark()），
 *     而 styles.css 里已有「颜色即语义」的那套令牌，这里只加一层覆盖，不改旧值。
 */
const THEME = (() => {
  const MEDIA = "(prefers-color-scheme: dark)";
  /** 当前实际生效的暗色（不是用户选的那个值：auto 要问系统）。 */
  let systemDark = false;
  let mq = null;

  function pref() { return (state.settings || {}).theme || "auto"; }
  function dark() {
    const p = pref();
    if (p === "dark") return true;
    if (p === "light") return false;
    return systemDark;
  }

  /** 把状态写到 <html>：CSS 只认 data-theme 与 data-font，不认 JS 分支。
   *  这样所有屏（包括还没写好的）自动跟着走，不需要谁去记着刷新。 */
  function apply() {
    const root = document.documentElement;
    const p = pref();
    const isDark = dark();
    root.dataset.theme = isDark ? "dark" : "light";
    root.dataset.themePref = p;
    root.dataset.font = (state.settings || {}).font || "m";
    root.dataset.seal = (state.settings || {}).sealStyle || "classic";
    root.classList.toggle("no-motion", (state.settings || {}).motion === false
      || (state.settings || {}).reduceMotion === true);
    // 让浏览器的 UA 控件（日期选择器 / 复选框 / 滚动条）跟着换皮肤。
    // 这一条以前刻意钉死成 light，因为只有纸色一种；现在有两种了，颜色说真话比钉死重要。
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", isDark ? "#1b1917" : "#f4efe6");
    if (typeof paintNativeChrome === "function") paintNativeChrome();
  }

  /** 用户在「册 → 外观」里改了什么，都从这里过：落盘 → 刷根节点 → 刷原生条。 */
  function set(key, value) {
    if (!state.settings) state.settings = {};
    state.settings[key] = value;
    save(state);
    apply();
    if (key === "theme" || key === "font") {
      // 换主题要让当前那屏重新量一次高度（长图 / 热力图这类按 DOM 算的会变）
      if (typeof layoutRefresh === "function") layoutRefresh();
    }
    return true;
  }
  /** 三档字号：映射到 :root 的 --fs-scale，与系统 fontScale 相乘（原生侧 textZoom 已经在报）。 */
  function fontScale() {
    const f = (state.settings || {}).font || "m";
    return f === "l" ? 1.12 : f === "s" ? 0.94 : 1;
  }
  /** 系统主题变化时跟着切（只在 auto 下才有视觉变化，但始终重算一次）。 */
  function watch() {
    if (mq || typeof window.matchMedia !== "function") return;
    mq = window.matchMedia(MEDIA);
    systemDark = !!mq.matches;
    const onChange = (e) => { systemDark = !!e.matches; if (pref() === "auto") apply(); };
    try { mq.addEventListener("change", onChange); }
    catch (_) { try { mq.addListener(onChange); } catch (__) { /* 更老的 WebView：只认开机那一次 */ } }
  }
  /** 系统主题**此刻**是不是暗的：给「跟随系统」那一格显示当前事实用。 */
  function systemIsDark() { return systemDark; }

  function init() { watch(); apply(); }
  return { init, apply, set, dark, pref, fontScale, systemIsDark, systemDark: () => systemDark };
})();
/* 不在这里 init：theme.js 在 state.js 之后加载，但 boot() 才是「数据已经救回来」的那一刻
   （原生保险丝可能刚把备份填进 state）。提前 init 会拿一份还没恢复的设置去刷根节点，
   屏幕上就是「开机的第一帧还是上次关掉之前的那个主题」。所以由 app.js 的 boot() 调 THEME.init()。 */
