/** 笺 · 我的（册）
 *
 *  这一屏是「我是谁、我攒了什么、我的数据怎么样」，不是一张设置清单。
 *
 *  版式顺序（v0.6.0）：
 *    个人主页卡 → 三个入口（设置 / 找东西 / 章）→ 钱包与订阅 →
 *    数据与备份（含隐私与清空）→ 算力网关 → 笺册 → 数据体检
 *
 *  为什么顺序写在 me.js 而不是 index.html：index.html 是 Lead 的文件，而这一屏的
 *  静态骨架是连着七轮长出来的（每一块都有自己的 e2e 断言）。所以版式靠 layoutMe()
 *  在第一次进来时**搬一次家**，之后幂等——静态节点一个都不重建，只换父节点，
 *  于是原有的事件绑定、id、断言全都原样有效。
 *
 *  原有功能一件都不能坏：钱包、模块开关、默认首页、测试订阅、网关、备份导入导出、
 *  隐私政策、清空、笺册分页/过滤/复制/删除/全文，全部保持原样（它们各有 e2e 与
 *  gate_selfcheck 的注入在盯着，连注释里的锚点都是手写的）。
 */

/** 网关的自述缓存：问一次就够，改了地址再问（见 gwReset）。
 *  「接得上」和「那台网关配了模型」是两件事，界面上必须分开说。 */
let jianGw = null, jianGwTried = false, gwTries = 0;
function gwReset() { jianGw = null; jianGwTried = false; gwTries = 0; JianAPI.warm(); }
function askGateway(again) {
  if (jianGwTried && !again) return;   // again：重试那条要能越过这个闩，否则永远重试不了
  jianGwTried = true;
  gwTries++;
  JianAPI.gateway().then((r) => { jianGw = r; renderMe(); });
}

/** api.js 记的那几个任务名 → 屏幕上说人话。只有这一屏用得到，所以放在这里。
 *  认衣服 / 抄截图不是「一笺」，是两件事，所以句子写的是「最近一笺（认衣服）」。 */
const GWTask = { yi: "衣笺", wei: "味笺", yan: "言笺", see: "认衣服", ocr: "抄截图" };

/* ==================== 个人档案 ====================
   档案存在 state.profile（nick/line/since/avatar），钳位在 state.js 的 normalizeState 里。
   「开始用的日子」第一次开机就写好了，年度总结按它算年表——这里只负责印出来，
   绝不自己编一个。 */

/** 档案编辑态。和 albumOpen 同一个道理：这是「我正在改」，不进备份、重开回到只读。 */
let meEditing = false;
/** 编辑中的草稿。留着它是因为 renderMe() 会被别处（askGateway 的回调）调用，
 *  整片重建会把正在敲的字冲掉——草稿在模块变量里，重建之后还回输入框。 */
let meDraft = null;

/** 昵称/一句话的显示值：没填时**不许**印占位符冒充数据，要明说还没填。 */
function meNickText() { return String((state.profile || {}).nick || "").trim(); }
function meLineText() { return String((state.profile || {}).line || "").trim(); }

/** 个人主页卡。四个数字全部现算 state，不存派生数（存了就会在删数据之后变成假话）。 */
function renderMeProfile() {
  const box = $("#meProfile");
  if (!box) return;
  const pf = state.profile || {};
  const nick = meNickText(), line = meLineText();
  const days = (() => { try { return activeDays().length; } catch (_) { return 0; } })();
  const st = state.streak || {};
  const wd = (state.wardrobe || []).length;
  const yc = (state.yanCards || []).length;
  const ab = (state.album || []).length;
  const bd = (state.badges || []).length;

  if (meEditing) {
    const d = meDraft || { nick, line };
    box.innerHTML = `
      <div class="mp-head">
        <span class="seal-mark lg" aria-hidden="true">己</span>
        <div class="mp-main"><b class="serif">改一改自己的档案</b>
          <span>称呼和一句话，都只存在这台设备上。</span></div>
      </div>
      <div class="mp-edit">
        <label class="field"><span>称呼（最多 16 字）</span>
          <input type="text" id="meNickIn" maxlength="16" autocomplete="off"
                 value="${esc(d.nick)}" placeholder="怎么称呼你" aria-label="你的称呼"></label>
        <label class="field"><span>一句话（最多 60 字）</span>
          <input type="text" id="meLineIn" maxlength="60" autocomplete="off"
                 value="${esc(d.line)}" placeholder="比如：东西少一点，日子慢一点"
                 aria-label="一句话介绍自己"></label>
        <div class="row">
          <button type="button" class="btn" id="meSave">存下</button>
          <button type="button" class="btn ghost" id="meCancel">不改了</button>
        </div>
      </div>`;
    const ni = $("#meNickIn"), li = $("#meLineIn");
    const keep = () => { meDraft = { nick: String(ni.value || ""), line: String(li.value || "") }; };
    ni.oninput = keep; li.oninput = keep;
    $("#meSave").onclick = () => { meDraft = { nick: ni.value, line: li.value }; saveMeProfile(); };
    $("#meCancel").onclick = () => {
      if (meDraft && (String(meDraft.nick).trim() !== nick || String(meDraft.line).trim() !== line)) {
        meDraft = null; meEditing = false; renderMe();
        toast("没改，还是原来那样");
        return;
      }
      meDraft = null; meEditing = false; renderMe();
    };
    return;
  }

  box.innerHTML = `
    <div class="mp-head">
      <span class="seal-mark lg" aria-hidden="true">己</span>
      <div class="mp-main">
        <b class="serif${nick ? "" : " mp-empty"}" id="meNick">${esc(nick || "还没起名字")}</b>
        <span id="meLine">${esc(line || "还没有一句话。写一句，年度总结第一页用得着。")}</span>
      </div>
      <button type="button" class="chip" id="meEdit" aria-label="改我的称呼与一句话">改</button>
    </div>
    <p class="mp-since" id="meSince">${pf.since ? `自 ${dayStr(pf.since)} 起 · 有记录 ${days} 天` : `有记录 ${days} 天`}
      ${st.days ? `· 连续 ${st.days} 天` : ""}</p>
    <div class="mp-stats">
      <div class="mp-cell"><b>${wd}</b><span>柜里</span></div>
      <div class="mp-cell"><b>${yc}</b><span>言笺</span></div>
      <div class="mp-cell"><b>${ab}</b><span>笺册</span></div>
      <div class="mp-cell"><b>${bd}</b><span>章</span></div>
    </div>`;
  $("#meEdit").onclick = () => {
    meDraft = { nick, line };
    meEditing = true;
    renderMe();
    const el = $("#meNickIn");
    if (el) el.focus({ preventScroll: true });
  };
}

/** 存档案：空着是合法状态（等于没填），但要**说清楚**存成了什么，别让人以为没生效。 */
function saveMeProfile() {
  const nick = String((meDraft || {}).nick || "").trim().slice(0, 16);
  const line = String((meDraft || {}).line || "").trim().slice(0, 60);
  const before = { nick: meNickText(), line: meLineText() };
  state.profile.nick = nick;
  state.profile.line = line;
  save(state);
  meEditing = false;
  meDraft = null;
  renderMe();
  try { haptic("LIGHT"); } catch (_) { }
  if (!nick && !line) { toast("存下了：两样都空着，屏上会写着还没填"); return; }
  toastUndo(!nick ? "存下了。称呼还空着" : `存下了：${nick}`, () => {
    state.profile.nick = before.nick;
    state.profile.line = before.line;
    save(state);
    renderMe();
    toast("改回原来那句了");
  });
}

/* ==================== 数据体检 ====================
   「我的数据有多少、上限在哪、有什么可以清」——这一块以前一句话都没有，
   于是「笺册只留 24 张」「言笺只留 200 条」这些上限只有在真丢东西那一刻才被知道。
   全部现算，不落盘（落盘的数字删一条之后就成了假话）。 */

/** 备份是**文件**的事，不是 state 的事：只记一个「上一次导出是什么时候」。
 *  不进备份（它跟着备份往返就成了循环定义），也不进 state（§49 那条逐字段比对的断言）。 */
const BACKUP_AT_KEY = "jian.backupAt";
function backupAtGet() {
  try {
    const n = Number(localStorage.getItem(BACKUP_AT_KEY));
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch (_) { return null; }
}
function backupAtSet(ts) {
  try { localStorage.setItem(BACKUP_AT_KEY, String(ts)); } catch (_) { }
}

/** 各集合的条数与上限。上限只有**一处**定义（state.js 的 *_CAP），这里只读它。 */
function meCaps() {
  return [
    { key: "wardrobe", name: "柜子", n: (state.wardrobe || []).length, cap: 36, unit: "件" },
    { key: "yanCards", name: "言笺", n: (state.yanCards || []).length, cap: YAN_CAP, unit: "条" },
    { key: "album", name: "笺册", n: (state.album || []).length, cap: 24, unit: "张" },
    { key: "cookLog", name: "做过的菜", n: (state.cookLog || []).length, cap: COOK_CAP, unit: "道" },
    { key: "market", name: "买菜清单", n: (state.market || []).length, cap: MARKET_CAP, unit: "条" },
    { key: "recipes", name: "自己录的菜谱", n: (state.recipes || []).length, cap: RECIPE_CAP, unit: "张" },
    { key: "wish", name: "愿望单", n: (state.wish || []).length, cap: WISH_CAP, unit: "件" },
    { key: "outfits", name: "搭配册", n: (state.outfits || []).length, cap: OUTFIT_CAP, unit: "套" },
    { key: "weeks", name: "一周菜单", n: (state.weeks || []).length, cap: WEEK_CAP, unit: "张" },
    { key: "digest", name: "摘录", n: (state.digest || []).length, cap: DIGEST_CAP, unit: "句" },
    { key: "reminders", name: "提醒", n: (state.reminders || []).length, cap: NOTE_CAP, unit: "条" },
    { key: "log", name: "行为记录", n: (state.log || []).length, cap: LOG_CAP, unit: "条" },
    { key: "drafts", name: "草稿", n: (state.drafts || []).length, cap: DRAFT_CAP, unit: "条" },
  ];
}

function renderMeHealth() {
  const box = $("#meHealth");
  if (!box) return;
  const st = storageInfo();
  const caps = meCaps();
  const full = caps.filter((c) => c.n >= c.cap);
  const doneYan = (state.yanCards || []).filter((c) => c.done).length;
  const at = backupAtGet();
  const capLine = caps.map((c) => {
    const near = c.n >= c.cap * 0.85;
    return `<div class="mh-row" data-health="${c.key}"><span>${esc(c.name)}</span>
      <b class="mh-n${near ? " mh-near" : ""}">${c.n}<i>/${c.cap}</i> ${esc(c.unit)}</b></div>`;
  }).join("");
  const notes = [];
  if (full.length) notes.push(`已经顶到上限：${full.map((c) => c.name).join("、")}——再存会从最旧的开始丢。`);
  if (st.pct >= 80) notes.push(`本机已经用到 ${st.pct}%。到了 100% 会先清掉旧照片（衣服、颜色、记录都还在）。`);
  box.innerHTML = `
    <p class="tiny me-sec-t">数据体检</p>
    <div class="card mh-card">
      <div class="mh-top">
        <div><b class="serif" id="mhKb">${st.kb} KB</b><span>已用 · 上限约 ${Math.round(SHED_AT / 1024)} KB</span></div>
        <div><b class="serif" id="mhBackup">${at ? dayStr(at) : "还没"}</b><span>${at ? "上次导出的那天" : "没导出过备份"}</span></div>
      </div>
      <div class="mh-meter" role="img" aria-label="本机占用 ${Math.min(100, st.pct)}%">
        <i style="width:${Math.min(100, Math.max(0, st.pct))}%"></i>
      </div>
      <p class="tiny mh-honest">${at ? "" : "数据只在这台设备上。丢一次就没有第二次——导出一份，换手机也有得拿。"}</p>
      <div class="mh-list" id="mhCaps">${capLine}</div>
      ${notes.length ? `<p class="tiny mh-note">${esc(notes.join(" "))}</p>` : `<p class="tiny mh-note">还没有顶到上限的集合，宽裕。</p>`}
      <div class="mh-clean">
        ${doneYan ? `<button type="button" class="chip" id="mhCleanYan">清掉已办完的 ${doneYan} 条言笺</button>` : ""}
        <button type="button" class="chip" id="mhExport">导出备份</button>
      </div>
      <p class="tiny">普通 JSON 备份没有加密，含价格和私人记录。想保护文件，请到「数据与备份」选加密备份。</p>
    </div>`;
  const cy = $("#mhCleanYan");
  if (cy) cy.onclick = () => {
    const gone = [], at2 = [];
    state.yanCards.forEach((c, i) => { if (c.done) { gone.push(c); at2.push(i); } });
    if (!gone.length) { toast("没有已经办完的言笺"); renderMe(); return; }
    state.yanCards = state.yanCards.filter((c) => !c.done);
    save(state); renderMe(); haptic("LIGHT");
    toastUndo(`清掉了 ${gone.length} 条已办完的言笺`, () => {
      // 按原下标升序插回去（倒着插会全落到末尾，顺序就和清前不一样了）
      at2.forEach((idx, k) => state.yanCards.splice(Math.min(idx, state.yanCards.length), 0, gone[k]));
      save(state); renderMe();
    });
  };
  const ex = $("#mhExport");
  if (ex) ex.onclick = () => exportData();
}

/* ==================== 版式：进来搬一次家 ====================
   幂等。只换父节点，不重建静态节点——id、绑定、文本全都不动，
   于是 e2e 里那一大批断言（#points / #planName / #storageNote / #album …）原样有效。 */
function layoutMe() {
  const me = $("#me");
  if (!me || me.dataset.meLaid === "1") return;
  const wallet = $(".stampcard", me);
  const modChips = $("#me [data-mod]") ? $("#me [data-mod]").parentElement : null;
  const modLabel = modChips ? modChips.previousElementSibling : null;
  const homeChips = $("#me [data-home]") ? $("#me [data-home]").parentElement : null;
  const homeLabel = homeChips ? homeChips.previousElementSibling : null;
  const links = $("#meLinks");
  const topup = $(".topup", me);
  const apiInput = $("#apiUrl");
  const apiLabel = apiInput ? apiInput.previousElementSibling : null;
  const saveApi = $("#saveApi");
  const apiState = $("#apiState");
  const apiModel = $("#apiModel");
  const storageNote = $("#storageNote");
  const exportRow = $("#exportData") ? $("#exportData").parentElement : null;
  const privacy = $("#privacyBox");
  const reset = $("#reset");
  const albumNote = $("#albumNote");
  const albumChips = $("#albumChips");
  const album = $("#album");
  if (!wallet || !links || !apiInput || !exportRow || !privacy || !reset || !album) return;

  const gap = () => { const d = document.createElement("div"); d.className = "space"; return d; };
  /** 一块 = 一个新容器 + 原样搬进来的静态节点。标题只在需要分段时给。 */
  const sec = (id, title, nodes) => {
    const wrap = document.createElement("section");
    wrap.id = id;
    wrap.className = "me-sec";
    if (title) {
      const h = document.createElement("p");
      h.className = "tiny me-sec-t";
      h.textContent = title;
      wrap.appendChild(h);
    }
    nodes.filter(Boolean).forEach((n) => wrap.appendChild(n));
    return wrap;
  };

  const profile = document.createElement("div");
  profile.id = "meProfile";
  profile.className = "card me-profile";

  const walletSec = sec("meSecWallet", "钱包与订阅",
    [wallet, gap(), modLabel, modChips, gap(), homeLabel, homeChips, gap(), topup]);

  // 「备份里含什么」写在这一行下面：不是按下去才知道，而是**按之前**就该知道。
  const backupNote = document.createElement("p");
  backupNote.className = "tiny";
  backupNote.id = "backupNote";
  backupNote.textContent = `普通 JSON 备份不加密，${BACKUP_WHAT}（柜子、言笺、笺册、设置都在里面）。要私密保存，请用下面的加密备份。`;
  const vaultBox = document.createElement("details");
  vaultBox.id = "vaultBox";
  vaultBox.className = "vault-box";
  vaultBox.innerHTML = `<summary>加密备份 · 给私人记录上锁</summary>
    <p class="tiny">离线 AES-256-GCM 加密，密码只在这次操作中使用，不发送、不保存。密码忘了无法恢复，请自行保管。</p>
    <label class="tiny" for="vaultPass">备份密码（至少 10 个字符）</label>
    <input id="vaultPass" type="password" autocomplete="off" minlength="10" maxlength="256" placeholder="输入备份密码" />
    <label class="tiny" for="vaultConfirm">再次输入密码（仅导出时需要）</label>
    <input id="vaultConfirm" type="password" autocomplete="off" minlength="10" maxlength="256" placeholder="再次确认密码" />
    <div class="vault-actions">
      <button type="button" class="btn ghost" id="vaultExport">导出加密备份</button>
      <button type="button" class="btn" id="vaultRestore" hidden>解密并恢复</button>
    </div>
    <p class="tiny" id="vaultStatus" role="status" aria-live="polite">导入加密 JSON 后，会在这里提示输入原密码；普通备份仍可直接导入。</p>`;
  const recoveryBox = document.createElement("details");
  recoveryBox.id = "recoveryBox";
  recoveryBox.className = "vault-box recovery-box";
  recoveryBox.innerHTML = `<summary>本机恢复点 · 给整份笺留底</summary>
    <p class="tiny">独立存到这台设备的 IndexedDB，包含衣服照片、言笺、笺册和设置。最多保留最近 5 份，每份校验完整性。导入备份前会自动留一份。</p>
    <p class="tiny">恢复点不加密、不会上传；浏览器清理网站数据时仍可能丢失。换设备或长期保管请用上方加密备份文件。</p>
    <div class="vault-actions"><button type="button" class="btn ghost" id="recoverySave">现在留一份</button></div>
    <p class="tiny" id="recoveryStatus" role="status" aria-live="polite">展开后检查本机存过的恢复点。</p>
    <div id="recoveryList" class="recovery-list"></div>`;
  const dataSec = sec("meSecData", "数据与备份",
    [storageNote, exportRow, backupNote, vaultBox, recoveryBox, privacy, gap(), reset]);
  vaultBox.querySelector("#vaultExport").onclick = exportEncryptedData;
  vaultBox.querySelector("#vaultRestore").onclick = decryptPendingBackup;
  RecoveryPoints.attach(recoveryBox);

  const netSec = sec("meSecNet", "", [apiLabel, apiInput, gap(), saveApi, apiState, apiModel]);

  // 笺册那一块不给标题：它自己头上那句「笺册 · 一共 N 张」已经是标题了，
  // 再压一行就成了同一句话说两遍。
  const albumSec = sec("meSecAlbum", "", [albumNote, albumChips, album]);

  const health = document.createElement("div");
  health.id = "meHealth";

  // 先全部摘下来再按新顺序装回去：留着原地的那几个 .space 会在版首空出一截。
  [wallet, modLabel, modChips, homeLabel, homeChips, links, topup, apiLabel, apiInput, saveApi,
    apiState, apiModel, storageNote, exportRow, privacy, reset, albumNote, albumChips, album]
    .forEach((n) => { if (n && n.parentElement === me) n.remove(); });
  [...me.children].forEach((n) => { if (n.classList && n.classList.contains("space")) n.remove(); });

  // 版式顺序：个人卡 → 三个入口 → 钱包与订阅 → 数据与备份 → 笺册 → 其余（网关 / 数据体检）。
  // 备份排在它保护的数据（笺册）**前面**：e2e §46 量的就是这个顺序，
  // 而想导出的人往往是觉得数据要出事的那个。
  me.append(profile, links, walletSec, dataSec, albumSec, netSec, health);
  me.dataset.meLaid = "1";
}

/* ==================== 钱包 / 订阅 ==================== */

/** 笺册的视图态：先看哪一笺、要不要把剩下的摊开、哪几张摊着全文。刻意不进备份——
 *  开机看见一条自己没点过的过滤，比不记更烦（和第 15 轮柜子搜索同一裁决）。 */
let albumView = "all", albumAll = false, albumOpen = [];
const ALBUM_PAGE = 12;

/** 订阅覆盖到的那几笺。「全笺」摊开成三笺，单笺就是它自己——
 *  「这份订阅还指着屏上真的开着的笺吗」和「取消之后会不会真的重新开始扣点」
 *  问的是同一件事，所以只在这里算一次（同一件事两份定义是本仓反复栽过的那一族）。 */
function planCovers() {
  return state.plan === "all" ? ["yi", "wei", "yan"] : [state.plan];
}

function renderWallet() {
  $("#points").textContent = state.plan === "all" ? "不限" : state.points;
  // 订阅指向的那一笺已经从底栏关掉了：这一行不能照旧只印一个名字。「开哪一笺」那一排
  // 关掉模块时不动 plan（app.js），导入的备份更能直接写成这样——于是钱包卡长期写着
  // 「订阅：衣笺」，而那一笺用户在底栏已经找不到，那个「不再扣点」的名额占在一个不存在的地方。
  // 这里只说事实，不假装它还在管事；要清掉它，就按这一行后面的那枚签。
  const dead = !planCovers().some((k) => state.modules[k]);
  $("#planName").textContent = (PLAN_NAME[state.plan] || "未订阅")
    + (state.plan && dead ? (state.plan === "all" ? " · 这三笺都已经关掉了" : " · 这一笺已经关掉了") : "");
  paintPlanOff();
}

/** 「取消订阅」补在钱包那一行「订阅：X」的后面（第 64 轮）。以前全仓只有 buy() 写过
 *  state.plan，没有任何一处能把它设回 null，而 state.js 认 null、这一行也会印「未订阅」——
 *  界面上摆着一个永远回不去的状态，想回去只能自己手写 JSON 导进来。
 *  这一枚由 JS 造（index.html 那一行是静态的），跟着现有版式走：不开弹窗、不加遮罩，
 *  就摆在写着订阅的那一片上——写着它的地方就是关得掉它的地方。
 *  没有订阅时不摆：那一枚按下去只能说「现在就是未订阅」，是笺册那一排
 *  「只剩一笺时不出过滤签」定下来不许做的东西。 */
function paintPlanOff() {
  let b = $("#planOff");
  if (!state.plan) {
    if (b) b.hidden = true;
    return;
  }
  if (!b) {
    b = document.createElement("button");
    b.type = "button"; b.id = "planOff"; b.className = "chip";
    b.onclick = cancelPlan;
    $("#planName").closest("p").appendChild(b);
  }
  b.hidden = false;
  b.textContent = "取消订阅";
  // 这一行前面就是「订阅：衣笺」，视觉上读得到上下文；读屏器按之前也要知道这一下会干什么
  b.setAttribute("aria-label", "取消订阅（现在订阅的是" + (PLAN_NAME[state.plan] || state.plan) + "）");
}

const PLAN_NAME = { all: "全笺", yi: "衣笺", wei: "味笺", yan: "言笺" };

/** 关掉订阅：改 state → 落盘 → 屏上那句「未订阅」真的到得了 → 给一次反悔。
 *  扣点不扣点这一句必须跟着「那一笺现在开不开着」说：对着一屏写着「这一笺已经关掉了」的
 *  行再说「这一笺重新开始扣点」，就是第 58 轮那族「同一屏两句相反的话」。 */
function cancelPlan() {
  const was = state.plan;
  // 这一枚只在有订阅时摆着；真按到（比如另一屏刚把它关掉）也不许一声不吭地返回
  if (!was) { toast("现在就是未订阅，不用取消"); return; }
  const live = planCovers().some((k) => state.modules[k]);
  const name = PLAN_NAME[was] || was;
  const tail = (was === "all" ? "三笺都" : "这一笺")
    + (live ? "重新开始扣点" : "本来就关着，没在扣点");
  // 键盘那一路：这一枚按完就要收起来，焦点不许甩回页首（同 me.js 整片重建那套找回）
  const wasOn = document.activeElement === $("#planOff");
  state.plan = null;
  save(state); renderWallet(); haptic("LIGHT");
  toastUndo(`已取消${name}订阅：${tail}`, () => {
    state.plan = was;
    save(state); renderWallet();
  });
  if (wasOn) {
    const u = $("#toasts .toast.act button");
    if (u) u.focus({ preventScroll: true });
  }
}

/** 隐私政策这一处入口（第 62 轮）。三件事一起做：
 *   1) **网址本身看得见**——一枚只写着「隐私政策」的按钮等于让用户按下去之前不知道自己
 *      要去哪儿，所以链上的字**就是**那条 URL；
 *   2) **复制**它，走 ui.js 现成的 copy()（和「复制这段话」同一条路）；
 *   3) **试着打开**：<a target="_blank" rel="noopener">。Capacitor 8 安卓侧没有重写
 *      onCreateWindow，也没开 setSupportMultipleWindows（Bridge.java 只设了
 *      setJavaScriptCanOpenWindowsAutomatically），所以这一跳走的是同窗导航 →
 *      BridgeWebViewClient 的 shouldOverrideUrlLoading → Bridge.launchIntent → ACTION_VIEW
 *      交给系统浏览器，App 自己那张 WebView 不会离开。
 *  但 launchIntent 里那个 ActivityNotFoundException 是被吞掉的（源码里一句 TODO）：
 *  设备上没装任何处理 https 的 App 时，点下去真的什么都不发生。所以这一枚不许
 *  preventDefault（那是把唯一那条真路堵死），也不许静默——按下去先说一句，
 *  那句话同时给出路（第 57 轮那条：不许摆一枚按了没反应的签）。
 *  这条 URL 在仓库里只有 config.js 一份定义，这里读它，不写字面串。 */
function renderPrivacy() {
  const url = window.JIAN_CONFIG.privacyUrl;
  $("#privacyBox").innerHTML = `<p class="tiny">隐私政策 · 你的数据到底怎么处理，全在这一页上</p>
    <a class="policy-url" id="privacyLink" href="${esc(url)}" target="_blank" rel="noopener"
       aria-label="在浏览器里打开隐私政策这一页：${esc(url)}">${esc(url)}</a>
    <div class="chips" style="margin-top:8px">
      <button type="button" class="chip" id="copyPrivacyUrl">复制这段网址</button>
    </div>`;
  $("#privacyLink").onclick = () => {
    toast("在系统浏览器里打开这一页；没看到新页面的话，按「复制这段网址」再粘到地址栏", 5200);
  };
  $("#copyPrivacyUrl").onclick = () => {
    haptic("LIGHT");
    copy(url, "已复制这段网址");
  };
}

/* ==================== 那一屏 ==================== */

function renderMe() {
  layoutMe();                // 第一次进来把版式搬一次家（之后幂等，什么都不做）
  renderWallet();
  renderPrivacy();
  // 整片重建之前先记住焦点在哪一枚签上，重建之后还回去（见 ui.js）：
  // 键盘按一次「只看衣笺」就被甩回页首，是第 10 轮在别处踩过的那类事。
  const fk = focusKey();
  const MODS = { yi: ["衣笺", "衣"], wei: ["味笺", "味"], yan: ["言笺", "言"] };
  const count = { yi: 0, wei: 0, yan: 0 };
  state.album.forEach((a) => { if (count[a.type] !== undefined) count[a.type]++; });
  // 行上的 data-slip 必须是 state.album 里的**真下标**。过滤之后按「屏上第几张」取值，
  // 点第一张复制到的会是背后另一张——第 15 轮「勾错条」同款坑，那时候是 indexOf，这里是 slice。
  const hit = [];
  state.album.forEach((a, i) => { if (albumView === "all" || a.type === albumView) hit.push(i); });
  const shown = albumAll ? hit : hit.slice(0, ALBUM_PAGE);
  // 笺册存到 24 张，屏上以前永远只画 12 张，而且一句都没说：另外那 12 张既看不见、
  // 也数不清到底存了几张。这里一次补三件事——总数、按笺过滤、把剩下的摊开。
  const note = $("#albumNote"), chipRow = $("#albumChips");
  if (note && chipRow) {
    // 空笺册不给它留一行空的高度：那一屏本来就只有一句「先过一张」。
    note.hidden = chipRow.hidden = !state.album.length;
    note.textContent = !state.album.length ? ""
      : `笺册 · 一共 ${state.album.length} 张`
        + (albumView === "all" ? "" : `，${MODS[albumView][0]} ${count[albumView]} 张`)
        + (hit.length > shown.length ? `，先摊着最新的 ${shown.length} 张` : "");
    const chips = [];
    const kinds = Object.keys(count).filter((k) => count[k]);
    // 只有一笺有存档时不出按笺的签：滤过去还是这一些，那是一枚按了没用的按钮
    // （和第 27 轮「一条都没勾时不许摆『清掉勾掉的』」同一条规矩）。「全部」那枚例外——
    // 手里这一份可能只剩别的笺（导入了一份新备份），没有它就出不去了。
    if (albumView !== "all") chips.push(`<button type="button" class="chip" data-aview="all"
        aria-pressed="false">全部 ${state.album.length} 张</button>`);
    if (kinds.length > 1) {
      kinds.forEach((k) => {
        chips.push(`<button type="button" class="chip${albumView === k ? " on" : ""}" data-aview="${k}"
            aria-pressed="${albumView === k}">${MODS[k][1]} ${count[k]}</button>`);
      });
    }
    if (hit.length > ALBUM_PAGE) {
      chips.push(`<button type="button" class="chip" data-aall="1"
          aria-pressed="${albumAll}">${albumAll ? `只看最新 ${ALBUM_PAGE} 张` : `看另外 ${hit.length - ALBUM_PAGE} 张`}</button>`);
    }
    chipRow.innerHTML = chips.join("");
    $$("#albumChips [data-aview]").forEach((b) => {
      b.onclick = () => { albumView = b.dataset.aview; renderMe(); };
    });
    const aa = $("#albumChips [data-aall]");
    if (aa) aa.onclick = () => { albumAll = !albumAll; renderMe(); };
  }
  const items = shown;
  // 笺册以前是四个一模一样的灰盒子，全 App 最平的一段。
  // 这里的东西其实和报告页同一种——一枚结论章 + 一句金句，那就用同一副骨架：
  // 模块小印开眉，日期收到右边，正文走宋体，结论章用印章红而不是套引号。
  $("#album").innerHTML = items.length
    ? items.map((i) => {
      const a = state.album[i];
      const [full, seal] = MODS[a.type] || MODS.yi;
      // 一行就是一张笺的存档：点卡片把**当时那张笺**再复制一次（旧数据只存了标题，
      // 没有 text 就退回标题，至少不会复制出一句空话——见下面点击回调里的兜底）。
      // × 与「全文」都在卡片**外面**：整张卡片是个 `<button>`，而 button 里不许放交互内容
      // （和第 23 轮那个嵌套 `<label>` 同一条规定）——塞进去解析器会把这张卡片咬断。
      // 只有 text 与 quote 真的不同时才摆「全文」：味笺那行两个值一样，
      // 摆一枚点开什么也不变的签就是第 27 轮定下来不许做的事。
      const canOpen = !!a.text && a.text !== a.quote;
      const open = albumOpen.indexOf(i) >= 0;
      const body = open ? a.text : (a.quote || "");
      return `<div class="slip-row">
        <button type="button" class="card slip" data-slip="${i}"
          aria-label="再复制这张${full}：${esc((a.quote || "").slice(0, 30))}">
        <div class="slip-top"><span class="seal-mark" aria-hidden="true">${seal}</span>
          <span class="meta">${full}</span>
          <span class="slip-date">${dayStr(a.t)}</span></div>
        <p class="slip-body serif${open ? " full" : ""}">${a.stamp ? `<span class="slip-stamp">${esc(a.stamp)}</span>` : ""}${esc(body)}</p>
        <span class="tiny slip-copy">再复制</span>
        </button>
        <span class="slip-acts">
          ${canOpen ? `<button type="button" class="toggle" data-aopen="${i}"
              aria-expanded="${open}" aria-label="${open ? "收起" : "看这一张的全文"}">${open ? "收起" : "全文"}</button>` : ""}
          <button type="button" class="drop" data-del="${i}"
            aria-label="从笺册去掉这张${full}：${esc((a.quote || "").slice(0, 20))}">×</button>
        </span>
      </div>`;
    }).join("")
    : `<p class="tiny">${state.album.length ? "这一笺还没有存档。" : "还没有笺。先过一张。"}</p>`;
  $$("#album [data-slip]").forEach((b) => {
    b.onclick = () => {
      const a = state.album[+b.dataset.slip];
      const body = (a && (a.text || a.quote)) || "";
      if (!body.trim()) { toast("这一张没存下能复制的话"); return; }
      haptic("LIGHT");
      copy(body, "已复制这一张笺");
    };
  });
  // 单张去得掉：册子攒的是存档，以前只能整台机器清空才能把它清干净。
  // 撤销按**原下标**放回（第 27 轮那条：push 回队尾会把顺序弄乱）。
  $$("#album [data-del]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.del;
      const gone = state.album[i];
      if (!gone) return;
      state.album.splice(i, 1);
      albumOpen = [];          // 下标整体前移了，摊着全文的那几张会指到别的笺上
      save(state); renderMe(); haptic("LIGHT");
      toastUndo("已从笺册去掉这一张（纸上那张笺没动）", () => {
        state.album.splice(Math.min(i, state.album.length), 0, gone);
        albumOpen = [];
        save(state); renderMe();
      });
    };
  });
  // 摊开看全文：册子存的是**当时那整张笺**（多行），可界面永远只画一行 quote，
  // 想读只能复制出去——存档在，看不见。这枚签只在外头，卡片本身还是「点一下就复制」。
  $$("#album [data-aopen]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.aopen;
      const at = albumOpen.indexOf(i);
      if (at >= 0) albumOpen.splice(at, 1); else albumOpen.push(i);
      renderMe();
    };
  });
  // 开关态不能只写在 class 里：读屏器看不见 .on，只念得出 aria-pressed。
  // 这一排是三枚**独立开关**（不是单选组），所以它拿不到 dead_controls 那条
  // 「同组让出选中位 = 真单选」的豁免——它关掉最后一笺会被挡回去，那是守卫型开关。
  $$("[data-mod]").forEach((el) => {
    const on = !!state.modules[el.dataset.mod];
    el.classList.toggle("on", on);
    el.setAttribute("aria-pressed", String(on));
  });
  // 只算「我的」这一屏的那一排（引导页那三张卡也叫 data-home，见 app.js 的绑定）
  $$("#me [data-home]").forEach((el) => {
    const on = state.home === el.dataset.home;
    el.classList.toggle("on", on);
    el.setAttribute("aria-pressed", String(on));
  });
  $("#apiUrl").value = state.apiUrl || "";
  // 说真话：填了地址不等于接通。上一次没通，就要明说那张笺是本地规则算的
  const eng = JianAPI.status();
  // 连不上过一次之后的那 30 秒里根本不问网关（见 api.js 的冷却）。这句话要把三件事都说清：
  // 为什么没问、这几张是谁算的、怎么才能立刻再试一次。
  // 少了中间那半句，用户看到「正在用本地引擎」会以为地址没填对——那句「本地规则算的」
  // 是第十六轮钉下来的口径，别被新文案悄悄换掉（e2e 里有一条就盯着它）。
  $("#apiState").textContent = !eng.on ? "正在用本地引擎。"
    : eng.cold
      ? `这台网关刚才连不上（${eng.error || "没回话"}），${Math.ceil(eng.cold / 1000)} 秒内的笺是本地规则算的；改地址会立刻再试。`
      // 说的是**最近那一张**，并且报得出是哪一笺：一次很久以前的远端衣笺，
      // 不该让刚回落本地的味笺也被说成「网关给的」。
      : eng.via === "remote" ? `已指向网关，最近一笺（${GWTask[eng.task] || "那张"}）是网关给的。`
    : eng.via === "fell-back"
      ? `已指向网关，但最近一笺（${GWTask[eng.task] || "那张"}）没通（${eng.error || "未知原因"}）——那笺是本地规则算的。`
      : "已指向网关，还没发过请求；失败时会回落到本地。";
  const am = $("#apiModel");
  if (am) {
    if (!eng.on) am.textContent = "认衣服、抄聊天截图：没填网关地址，这两条走不了。";
    else if (!jianGw) { am.textContent = "正在问网关能干什么…"; askGateway(); }
    else if (!jianGw.ok) {
      am.textContent = "网关连不上：" + (jianGw.error || "未知原因") + "——判定与识图都会回落到本机。";
      // 一次没问通就永远说「连不上」，是「已指向网关」那笔假账的反面：设备上实测过，
      // 冷启动的头一次出网能慢到把预算挤掉，那台网关其实好得很。
      // 所以失败之后再问一次（改了地址才重新计数），但也只多这一次，不会没完没了地敲。
      // 那个 `true` 不能省：askGateway 自己有个「问过就不再问」的闩，不带它这一行等于
      // 什么都没做——第一版就是这么写的，被 e2e §29 那条重试断言当场抓出来。
      if (gwTries < 2) askGateway(true);
    }
    else if (jianGw.model) {
      // 网关自述里 recognize / ocr 是两个分开的布尔（只挂了聊天模型的网关也算「配了模型」，
      // 但它认不了衣服也抄不了图）。以前这里只看 model 有没有值，于是对那种网关
      // 承诺了「认衣服、抄截图可用」——记下来的 tasks 全仓没人读。缺字段当「不知道」，不算否。
      const t = jianGw.tasks || {};
      // 三态：缺字段是「不知道」，不是「可用」——上面那行注释一直这么写，代码却把 undefined
      // 顺嘴念成「可用」。一台只挂了聊天模型、不报 tasks 的老实网关，因此被承诺了两条能力。
      const can = (k) => t[k] === true ? "可用" : t[k] === false ? "不行" : "没自述";
      am.textContent = `网关在线，模型 ${jianGw.model}：认衣服${can("recognize")}、抄截图${can("ocr")}。`;
    }
    else am.textContent = "网关在线，但那台网关没配模型：认衣服、抄截图走不了，判定照旧能用。";
  }
  const st = storageInfo();
  const sn = $("#storageNote");
  // 「数据只在这台设备」是这一屏最响的一句承诺，而同一屏下面就放着网关地址那一格：
  // 填了它，认衣服发照片、抄图发截图、排桌发菜单和每个人的称呼忌口、捞笺发整段聊天——
  // 那句话当场就不成立了。第 16 轮修的是「填了地址≠接通」，这是同一颗雷的另一半。
  const where = dataWhere();
  // 百分比的分母是「开始丢照片那条线」（见 state.js 的 SHED_AT）：说「已用 56%，离 5MB 还远」
  // 而照片已经在被清掉，是一句会让人做坏决定的话。
  if (sn) sn.textContent = `笺 ${window.JIAN_CONFIG.version} · ${where} · 已用 ${st.kb} KB（${st.pct}%，满了先丢照片）`;
  // 档案卡与数据体检：两块都是现算 state，所以每次重建都要跟着刷。
  try { renderMeProfile(); } catch (e) { console.warn("me profile", e); }
  try { renderMeHealth(); } catch (e) { console.warn("me health", e); }
  // 「章」那枚入口的副标题：数字长在屏上，才有人点进去看差什么
  const bs = $("#badgeSub");
  if (bs) bs.textContent = (state.badges || []).length ? `已攒 ${state.badges.length} 枚 · 一枚一枚攒` : "一枚一枚攒";
  restoreFocus(fk);
}

const MOD_NAME = { yi: "衣笺", wei: "味笺", yan: "言笺" };

function buy(plan) {
  // 送点按「当场真的从关到开了几笺」算。以前是固定发 16：那四枚签买完之后还留在原处，
  // 再点一次又送 16，连点两下就是 32——一个谁都能撞见的印钞机；而「另两笺各送 8 点」
  // 那一句在另两笺本来就开着的时候也是假的（开了个寂寞，钱照发）。
  const was = Object.assign({}, state.modules);
  // 「开全笺」必须连 modules 一起改：以前它只改订阅名，底栏还是短的，
  // 桌面快捷方式点进来照旧被 openDeep 挡回「这一笺已经关掉了」——那句话承诺的事没做到。
  if (plan === "all") ["yi", "wei", "yan"].forEach((k) => { state.modules[k] = true; });
  else state.modules[plan] = true;
  const opened = ["yi", "wei", "yan"].filter((k) => !was[k] && state.modules[k]);
  const gift = 8 * opened.length;
  // 已经是这一笺、这次又一笺都没新开：什么都不改，也别装作给了钱。
  if (!opened.length && state.plan === plan) {
    toast("这一笺已经开着了，没再送点");
    return;
  }
  // 全笺开着时点单笺不许把订阅**降**成单笺：那会悄悄让另外两笺重新开始扣点，
  // 而屏幕上写的明明是「开」，是反方向的。这里只把那一笺补开（上面已经补了）。
  if (plan !== "all" && state.plan === "all") {
    save(state); paintNav(); renderMe();
    toast(gift ? `已补开${MOD_NAME[plan]}，送 ${gift} 点（全笺还开着）`
               : `${MOD_NAME[plan]}本来就开着，全笺不变`);
    return;
  }
  if (gift) state.points = Math.min(9999, state.points + gift);
  state.plan = plan;
  save(state); paintNav(); renderMe();
  toast(plan === "all"
    ? (gift ? `三笺都开好了，送 ${gift} 点` : "三笺本来就都开着")
    : (gift ? `已开${MOD_NAME[plan]}：这一笺不再扣点，另补开 ${gift / 8 - 1} 笺共送 ${gift} 点`
            : `已换成${MOD_NAME[plan]}：这一笺不再扣点，没再送点`));
}

/** 备份里到底装了什么。这句话要摆在**按下去之前**（数据与备份那一块的说明里），
 *  也要在那句提示里说一遍——要导出的人往往就是想把数据交出去的人，
 *  而这份 JSON 里有价格、有私人记录。两处读同一句，别各写一份。 */
const BACKUP_WHAT = "备份里含价格与私人记录";

async function exportData() {
  // savedAt 是**文件**的元数据，不是 state 的一部分：导入那一路会把它剥掉，
  // 所以它不会混进柜子、也不会跟着往返进备份（e2e §49 两头都钉着）。
  const json = JSON.stringify(Object.assign({ savedAt: Date.now() }, state), null, 2);
  if (hasNative()) {
    // 原生壳里：写进文稿目录再分享，文件名带日期
    try {
      const d = new Date();
      const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
      await nativeShareFile(`jian-backup-${ymd}.json`, json, { directory: "Documents", encoding: "UTF8" });
      backupAtSet(Date.now());
      toast(doneMsg("导出备份") + "。" + BACKUP_WHAT, 5200);
      return;
    } catch (e) {
      console.warn(e);
      // App 里没有「下载」这回事：a.click() 在 WebView 里什么都不做。
      // 以前这里回落到那一下、然后照样 toast「已导出备份」——文件从来没出现过。
      toast(SHARE_FAILED, 5200);
      return;
    }
  }
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.download = `笺-备份-${dayStr(Date.now())}.json`;
  a.href = URL.createObjectURL(blob);
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  backupAtSet(Date.now());
  toast(doneMsg("导出备份") + "。" + BACKUP_WHAT, 5200);
}

// 加密文件只停留在此页的内存里；换页、重载不留口令和待解密正文。
let pendingEncryptedBackup = null;
let vaultBusy = false;
function vaultSay(message) {
  const target = $("#vaultStatus");
  if (target) target.textContent = message;
  toast(message, 4800);
}
async function exportEncryptedData() {
  if (vaultBusy) return;
  const passEl = $("#vaultPass"), confirmEl = $("#vaultConfirm"), button = $("#vaultExport");
  if (!passEl || !confirmEl) return;
  const pass = passEl.value;
  if (pass.length < 10 || pass.length > 256) return vaultSay("密码至少 10 个字符，最多 256 个");
  if (pass !== confirmEl.value) return vaultSay("两次输入的密码不一致，没有导出");
  vaultBusy = true;
  if (button) button.disabled = true;
  try {
    const savedAt = Date.now();
    const body = JSON.stringify(Object.assign({ savedAt }, state));
    const sealed = JSON.stringify(await JianVault.encrypt(body, pass, savedAt), null, 2);
    if (hasNative()) {
      const d = new Date(savedAt);
      const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
      await nativeShareFile(`jian-private-${ymd}.json`, sealed, { directory: "Documents", encoding: "UTF8" });
    } else {
      const blob = new Blob([sealed], { type: "application/json" });
      const link = document.createElement("a");
      link.download = `笺-加密备份-${dayStr(savedAt)}.json`;
      link.href = URL.createObjectURL(blob);
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 4000);
    }
    backupAtSet(savedAt);
    vaultSay(doneMsg("导出加密备份") + "。文件已加密，密码忘记无法恢复");
  } catch (e) {
    console.warn("encrypted backup", e);
    vaultSay(hasNative() && !/密码|加密|数据/.test(String(e.message)) ? SHARE_FAILED : String(e.message || "加密导出失败"));
  } finally {
    // 绝不写入 localStorage / sessionStorage，操作结束抹掉输入框。
    passEl.value = "";
    confirmEl.value = "";
    vaultBusy = false;
    if (button) button.disabled = false;
  }
}
async function decryptPendingBackup() {
  if (vaultBusy || !pendingEncryptedBackup) return vaultSay("先按「导入备份」选择加密 JSON");
  const passEl = $("#vaultPass"), button = $("#vaultRestore");
  const pass = passEl ? passEl.value : "";
  if (!pass) return vaultSay("请输入导出时设下的原密码");
  vaultBusy = true;
  if (button) button.disabled = true;
  try {
    const plain = await JianVault.decrypt(pendingEncryptedBackup, pass);
    const obj = JSON.parse(plain);
    const ok = await applyBackupObject(obj);
    if (!ok) vaultSay("解密成功，但备份结构不完整；原数据没有变化");
  } catch (e) {
    vaultSay(e instanceof SyntaxError ? "解密后的备份不是有效 JSON；原数据没有变化"
      : String(e.message || "解密失败；原数据没有变化"));
  } finally {
    if (passEl) passEl.value = "";
    vaultBusy = false;
    if (button) button.disabled = false;
  }
}
function importData(file) {
  if (vaultBusy) return vaultSay("正在加密或解密，请稍后再选择文件");
  // 新文件一选，旧的待解密文件立即作废；不能让按钮误恢复上一次选的那份。
  pendingEncryptedBackup = null;
  const oldRestore = $("#vaultRestore");
  if (oldRestore) oldRestore.hidden = true;
  if (!file || file.size > 16 * 1024 * 1024) return vaultSay("备份文件过大（上限 16 MB），原数据没有变化");
  const fr = new FileReader();
  fr.onload = async () => {
    let obj;
    try { obj = JSON.parse(fr.result); }
    catch (_) { return vaultSay("这不是有效 JSON 备份，原数据没有变化"); }
    if (JianVault.isEnvelope(obj)) {
      try { JianVault.validate(obj); }
      catch (e) { return vaultSay(String(e.message)); }
      pendingEncryptedBackup = obj;
      const box = $("#vaultBox"), action = $("#vaultRestore"), pass = $("#vaultPass");
      if (box) box.open = true;
      if (action) action.hidden = false;
      vaultSay("这是加密备份。请输入原密码，按「解密并恢复」；现有数据尚未改变");
      if (pass) pass.focus();
      return;
    }
    await applyBackupObject(obj);
  };
  fr.onerror = () => toast("文件没读出来");
  fr.readAsText(file);
}

async function applyBackupObject(obj) {
    const reject = () => { toast("这不是笺的备份文件，原数据没动"); return false; };
    // 先验货再落盘。以前是「是个 object 就 setItem」，数组也照样过；形状不对时 reload 后
    // load()→migrate() 返回 null，用户看到的是回到出厂示例柜，真实柜子已经被覆盖掉了。
    // 查的必须是原始 obj 而不是 migrate() 的结果：migrate/normalizeState 会把缺字段补成
    // 空数组，一份「没有 wardrobe」的 JSON 会被它补齐成空柜子——照样把数据清了。
    const bad = !obj || typeof obj !== "object" || Array.isArray(obj) ||
      !Array.isArray(obj.wardrobe) ||
      !obj.modules || typeof obj.modules !== "object" || Array.isArray(obj.modules);
    if (bad) return reject();
    // savedAt 是**文件**的元数据，不是 state 的一部分：不剥掉它就会跟着这份备份住进本机，
    // 而「往返不丢」那条守门量的正是 state 本身。
    const at = Number.isFinite(Number(obj.savedAt)) && Number(obj.savedAt) > 0 ? Number(obj.savedAt) : null;
    delete obj.savedAt;
    let text = null;
    try { text = JSON.stringify(migrate(obj)); } catch (e) { return reject(); }
    const prev = (() => { try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; } })();
    // 覆盖式导入前先留独立恢复点。IndexedDB 不可用时保留旧的 sessionStorage 撤销路径；
    // 可用却写失败（如配额已满）则停在原地，让用户先导出文件，不能冒险覆盖。
    if (prev && RecoveryPoints.available()) {
      try { await RecoveryPoints.capture("导入前"); }
      catch (e) {
        toast("导入前恢复点没存成，数据未改变。请先导出备份：" + String(e.message || e), 6500);
        return false;
      }
    }
    try {
      writeStore(text);   // 走唯一落盘入口：它先取消排在那次防抖里的旧 state
    } catch (e) {
      return reject();
    }
    // 换掉了才存：导入是一次整体覆盖，选错文件的人需要的不是事前对话框，是事后一次反悔
    // （和「清空本地数据」同一套路子）。写盘没成功就不占这个槽，否则下次开机凭空冒出一句「已导入」。
    try {
      sessionStorage.setItem(KEY + ".importundo", prev);
      sessionStorage.setItem(KEY + ".importat", at ? String(at) : "");
    } catch (_) { }
    // 这一份文件是某天导出的：把那次时间记在「数据体检」里（文件的事，不进 state）
    if (at) backupAtSet(at);
    // 导入完立刻 reload，那 1 秒的保险丝定时器就跟着文档一起没了：本机是新的、
    // 系统里那份还是旧的，哪天被系统清一次就整台退回导入前。所以先上一膛再走。
    await flushNativeBackup();
    location.reload();
    return true;
}
