/** 统一网关。业务只调 JianAPI.yi / wei / yan / hear，不直连模型。 */
window.JianAPI = (() => {
  function cfg() { return window.JIAN_CONFIG || {}; }
  function remoteOn() { return !!(cfg().endpoint && cfg().endpoint.trim()); }

  /* 判定到底是谁给的。
     以前界面只问 remoteOn()——那是「有没有填过地址」，不是「通没通过」。
     填了个死地址、或者网关挂了，三条路全部静默回落本地引擎，
     界面上照旧写着「已指向网关」，用户完全看不出这张笺其实是本地规则算的。
     这里给每条任务记下最近一次的真实出处和失败原因，界面照着说。 */
  const last = Object.create(null);

  function note(task, via, error) { last[task] = { via, error: error || null, at: Date.now() }; }

  /* 「先不等了」：网关在另一台机器上，它慢或不回话的时候，本地引擎其实立刻就能给答案。
     所以等待必须是可以放弃的——放弃之后这一轮不再试远端，直接落回本地出判定。
     live 里是在飞的那些 AbortController；givenUp 是「这一轮用户已经放弃了」的记号，
     beginTurn() 每次操作开头清掉。 */
  const live = new Set();
  let givenUp = false;

  function beginTurn() { givenUp = false; }
  function giveUp() {
    givenUp = true;
    for (const c of live) { try { c.abort(); } catch (_) { } }
    live.clear();
  }
  const GAVE_UP = "先不等了";

  /* 连不上这件事要记 30 秒。
     换 wifi、笔记本睡一觉，填着的局域网地址就指向一个没人在听的端口——那种失败的特征是
     「每一枪都要等到超时才死心」：识图 45 秒、判定 20 秒，用户每拍一张都要重等一遍，
     而本地引擎几十毫秒就能给出判定。冷却期内直接走本地，界面上明说为什么没问网关。
     4xx/5xx 不算：那是网关活着、而且在说话，问题在配置或模型，躲开它没有意义。
     用户改地址（gwReset → warm）或 30 秒之后，会再试一次——不会一棍子打死。 */
  const COLD_MS = 30000;
  let coldUntil = 0;
  const DEAD_RE = /failed to fetch|networkerror|aborted|abortederror|load failed|ERR_|秒内没回话|连不上|unreachable/i;
  const cold = () => Date.now() < coldUntil;
  const wantsRemote = () => remoteOn() && !cold();
  function wentCold(e) {
    if (DEAD_RE.test(String((e && e.message) || e || ""))) coldUntil = Date.now() + COLD_MS;
  }
  function warm() { coldUntil = 0; }
  const COLD_MSG = "这台网关刚才连不上，30 秒内先都走本地";

  /** task 省略时看三条路里最近一次的整体情况。 */
  function status(task) {
    const coldMs = Math.max(0, coldUntil - Date.now());
    if (!remoteOn()) return { on: false, via: "local", error: null, cold: 0 };
    if (task) return Object.assign({ on: true, cold: coldMs }, last[task] || { via: "untried", error: null });
    // 「最近一次」必须真的是最近那一次。以前这里是 some(via === 'remote')：
    // 一小时前衣笺走过一次网关、之后味笺言笺全回落本地，这句话照样成立——
    // 和第十九轮顶栏那一行修的是同一颗雷，只是这一半在「我的」屏上。
    // 现在取时间戳最大的那一条，并把「是哪一笺」一起交出去，界面上才说得出名字。
    const seen = Object.keys(last).map((k) => Object.assign({ task: k }, last[k]));
    if (!seen.length) return { on: true, via: "untried", error: null, cold: coldMs };
    const newest = seen.reduce((a, b) => ((b.at || 0) > (a.at || 0) ? b : a));
    return {
      on: true, cold: coldMs, task: newest.task, at: newest.at,
      via: newest.via === "local" && newest.error ? "fell-back" : newest.via,
      error: newest.error || null
    };
  }

  async function post(path, body, ms) {
    const c = cfg();
    if (givenUp) throw new Error(GAVE_UP);   // 这一轮用户已经放弃了，别再让他等第二遍
    const ctrl = new AbortController();
    live.add(ctrl);
    const t = setTimeout(() => ctrl.abort(), ms || c.timeoutMs || 20000);
    try {
      const res = await fetch(c.endpoint.replace(/\/$/, "") + path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(c.key ? { Authorization: "Bearer " + c.key } : {})
        },
        body: JSON.stringify(body),
        signal: ctrl.signal
      });
      if (!res.ok) {
        // 网关回 4xx/5xx 时带着一句人话（为什么不行）。把它读出来当回落原因，
        // 不然界面上只能说「网关 502」，用户不知道该改地址还是该换模型。
        let why = "网关 " + res.status;
        try { const j = await res.json(); if (j && j.message) why += "：" + j.message; } catch (_) { }
        throw new Error(why);
      }
      return await res.json();
    } catch (e) {
      // 按「先不等了」中止时 fetch 抛的是 AbortError（一句 signal is aborted…），
      // 那不该出现在界面上：换成用户刚点的那个按钮的名字。
      if (givenUp) throw new Error(GAVE_UP);
      throw e;
    } finally { clearTimeout(t); live.delete(ctrl); }
  }

  async function get(path, ms) {
    const c = cfg();
    const budget = ms || 6000;
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), budget);
    try {
      const res = await fetch(c.endpoint.replace(/\/$/, "") + path, { signal: ctrl.signal });
      if (!res.ok) throw new Error("网关 " + res.status);
      return await res.json();
    } catch (e) {
      // AbortController 抛出来那句是「signal is aborted without reason」——那是内部话，
      // 以前一字不差被印到「我的」上：用户看到「网关连不上：signal is aborted ...」，
      // 既不知道是等太久、也不知道该干什么。改成一句人话，并说清等了多久。
      if (ctrl.signal.aborted) throw new Error(budget / 1000 + " 秒内没回话");
      throw e;
    } finally { clearTimeout(t); }
  }

  /** 选中的图先缩到 512 边再传：手机原图 8~12MB，base64 之后更大，
   *  直接传会被网关的 body 闸挡回来（那闸是给误传用的，不是给人等的）。 */
  function shrink(file, w) {
    return new Promise((res, rej) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        try {
          const k = Math.min(1, (w || 512) / Math.max(img.width || 1, img.height || 1));
          const c = document.createElement("canvas");
          c.width = Math.max(1, Math.round((img.width || 1) * k));
          c.height = Math.max(1, Math.round((img.height || 1) * k));
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          res(c.toDataURL("image/jpeg", 0.82));
        } catch (e) { rej(e); }
      };
      img.onerror = () => { URL.revokeObjectURL(url); rej(new Error("图片读不出来")); };
      img.src = url;
    });
  }

  /** 照片 → 这件叫什么、什么品类、什么季节。
   *  主色不用它：像素就在本机，量出来的比模型猜的准（实测模型会把米色报成 #d4c5a9，
   *  而图上的衣服主体在 #c2ab96 一带）。回 null 表示这条路不通，调用方自己走本地。 */
  async function see(file) {
    if (!remoteOn()) { note("see", "local", "没填网关地址"); return null; }
    if (cold()) { note("see", "local", COLD_MSG); return null; }
    let img;
    try { img = await shrink(file); } catch (e) { note("see", "local", (e && e.message) || "图片读不出来"); return null; }
    try {
      const r = await post(cfg().paths.recognize, { image: img }, cfg().seeMs);
      if (usable(r, (x) => /^#[0-9a-f]{6}$/i.test(String(x.color || "")))) { note("see", "remote"); return r; }
      note("see", "local", "网关回的不是识别结果");
    } catch (e) { console.warn("see remote", e); wentCold(e); note("see", "local", (e && e.message) || String(e)); }
    return null;
  }

  /** 聊天截图 → 文字。 */
  async function ocr(file) {
    if (!remoteOn()) { note("ocr", "local", "没填网关地址"); return null; }
    if (cold()) { note("ocr", "local", COLD_MSG); return null; }
    let img;
    try { img = await shrink(file, 768); } catch (e) { note("ocr", "local", (e && e.message) || "图片读不出来"); return null; }
    try {
      const r = await post(cfg().paths.ocr, { image: img }, cfg().seeMs);
      if (usable(r, (x) => String(x.text || "").trim().length > 0)) { note("ocr", "remote"); return r; }
      note("ocr", "local", "网关没抄出字来");
    } catch (e) { console.warn("ocr remote", e); wentCold(e); note("ocr", "local", (e && e.message) || String(e)); }
    return null;
  }

  /** 网关的自述：接得上 ≠ 能看图。配了地址但没配模型的网关，识图这条路是断的。 */
  async function gateway() {
    if (!remoteOn()) return { on: false };
    try {
      // 12 秒不是拍脑袋：设备上实测过 6 秒这一档会被冷启动的第一次出网挤掉
      // （WebView 刚起来、网络栈还没热），一次没回话界面就永远停在「连不上」。
      // 状态这一问是异步的、不挡任何操作，多给几秒只赚不亏。
      const r = await get(cfg().paths.status, 12000);
      return { on: true, ok: !!r.ok, model: (r.model && r.model.model) || "", tasks: r.tasks || {} };
    } catch (e) { return { on: true, ok: false, error: (e && e.message) || String(e) }; }
  }

  // 远端给了东西但结构不对，和「根本没通」是两回事，分开记：界面上要说得出为什么回落
  function usable(r, ok) { try { return !!(r && ok(r)); } catch (_) { return false; } }

  async function yi(item, wardrobe) {
    if (wantsRemote()) {
      try {
        const r = await post(cfg().paths.see, { task: "yi", item, wardrobe: wardrobe.map((w) => ({ name: w.name, cat: w.cat, color: w.color, season: w.season })) });
        if (usable(r, (x) => x.stamp)) { note("yi", "remote"); return r; }
        note("yi", "local", "网关回的不是判定");
      } catch (e) { console.warn("yi remote", e); wentCold(e); note("yi", "local", e && e.message || String(e)); }
    } else note("yi", "local", cold() ? COLD_MSG : null);
    return Engine.yi(item, wardrobe);
  }

  async function wei(menu, people, mode) {
    if (wantsRemote()) {
      try {
        const r = await post(cfg().paths.complete, { task: "wei", menu, people, mode });
        if (usable(r, (x) => x.safe || x.suggest)) { note("wei", "remote"); return r; }
        note("wei", "local", "网关回的不是判定");
      } catch (e) { console.warn("wei remote", e); wentCold(e); note("wei", "local", e && e.message || String(e)); }
    } else note("wei", "local", cold() ? COLD_MSG : null);
    // mode 以前只发给网关、本地这一支丢掉——于是四张模式签在离线的手机上排出来一模一样，
    // 而屏幕上写着「家里这桌，硬菜和雷放后面」。两端现在吃同一个 mode。
    return Engine.wei(menu, people, mode);
  }

  async function yan(text) {
    if (wantsRemote()) {
      try {
        const r = await post(cfg().paths.complete, { task: "yan", text });
        if (usable(r, (x) => x["待办"] || x.ask)) { note("yan", "remote"); return r; }
        note("yan", "local", "网关回的不是判定");
      } catch (e) { console.warn("yan remote", e); wentCold(e); note("yan", "local", e && e.message || String(e)); }
    } else note("yan", "local", cold() ? COLD_MSG : null);
    return Engine.yan(text);
  }

  // 没有 hear：应用不录也不转写录音。以前这里有一条 `hear()`，它**不发任何音频**，
  // 网关永远回 needText，而界面那句「（网关那边没有能转写录音的模型）」是假的——
  // 我们根本没发东西去问那台模型。要转文字请用系统自己的听写，再把字贴进言笺的框。
  return { remoteOn, wantsRemote, status, yi, wei, yan, see, ocr, gateway, shrink,
           beginTurn, giveUp, warm };
})();
