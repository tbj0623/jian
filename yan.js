/** 笺 · 言笺
   把贴进来的话捞成笺。

   0.6.0 这一版在「捞」之后补了三件让话真的回来找人的事：
   · **日历**：有时间的条目落在月历上，点一天看那天的事；
   · **今天 / 今晚**：卡片分白天与夜里两档（slot），同一句话不会在凌晨三点找上门；
   · **归档**：办完满七天的自己收进归档，收的时候说一声、给一次反悔。

   规矩还是老的：筛选只有 `yanShown()` 一个口径，行上的下标永远是**全量下标**
   （用「屏上第几行」当下标，点第一行会办到另一条上去——这一族踩过三次）。 */

/* ---------- 言笺 ---------- */

const ORDER = YAN_KINDS;

/**
 * 把时间戳说成「今天 / 明天 / 3 天后」。
 * 按日历天比，不按毫秒差——否则「今天」的条目会因为差几毫秒被判成「已经过了」。
 */
function dayLabel(at) {
  const a = new Date(at), b = new Date();
  const dayA = new Date(a.getFullYear(), a.getMonth(), a.getDate()).getTime();
  const dayB = new Date(b.getFullYear(), b.getMonth(), b.getDate()).getTime();
  const d = Math.round((dayA - dayB) / DAY);
  if (d < 0) return "已经过了";
  if (d === 0) return "今天";
  if (d === 1) return "明天";
  if (d <= 6) return d + " 天后";
  if (d <= 13) return "下周";
  return shortDay(at);
}

/** 哪几条正展开「挪到…」的选择器。只是界面态，不进备份（同味笺忌口的展开）。 */
let moveOpen = [];
/** 同上，展开着「改时间」的那几条。两排选择器不同时摊着：见各自的点击处理。 */
let whenOpen = [];

/** 手动定时常用的几枚签。引擎把「周五」听成这周五、把「月底」听漏了的时候，
 *  这几枚能盖掉它——时间猜错比类别猜错更疼，待办过期是看不见的。 */
const WHEN_CHIPS = ["今天", "明天", "后天", "大后天", "下周一"];

/** 与 engine.js 的 parseTime 同口径：只挪日历天，保留此刻的时分秒。
 *  「下周一」按 ISO 走（周一下 7 天，周日下 1 天），和「下周三之前交方案」一致。 */
function whenFromLabel(label, now = Date.now()) {
  const off = { 今天: 0, 明天: 1, 后天: 2, 大后天: 3 }[label];
  if (off !== undefined) return { text: label, at: now + off * DAY };
  const d = new Date(now);
  const cur = d.getDay() === 0 ? 7 : d.getDay();
  return { text: label, at: now + (8 - cur) * DAY };
}

/** 用户从日期控件挑的那一天：月/日钳到当月末（2 月 30 日 → 2 月最后一天），同 clampDate。 */
function whenFromDate(v, now = Date.now()) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  if (!m) return null;
  const mo = +m[2], day = +m[3];
  if (mo < 1 || mo > 12 || day < 1 || day > 31) return null;
  const d = new Date(now);
  const t = new Date(+m[1], mo - 1, Math.min(day, new Date(+m[1], mo, 0).getDate()));
  const hms = d.getHours() * 3600000 + d.getMinutes() * 60000 + d.getSeconds() * 1000 + d.getMilliseconds();
  return { text: `${t.getMonth() + 1}月${t.getDate()}日`, at: t.setHours(0, 0, 0, 0) + hms };
}

/** 改一条的时间：只动 when，原话/类别/勾没勾都留在原地。给一次反悔。 */
function setWhen(i, w) {
  const c = state.yanCards[i];
  if (!c) return;
  const from = c.when, wasSet = c.wset === true;
  c.when = w || null;
  c.wset = !!w;
  whenOpen = [];
  save(state); renderYan();
  // 排收掉了，日期控件跟着没了，焦点别掉回页首：还给这一行那枚「时间」。
  const back = $(`#yanOut [data-when="${i}"]`);
  if (back) back.focus({ preventScroll: true });
  toastUndo(w ? `已改到「${w.text}」` : "已清掉这一条的时间", () => {
    c.when = from; c.wset = wasSet;
    save(state); renderYan();
  });
}

function normCards(r) {
  const out = [];
  if (!r || typeof r !== "object") return out;
  ORDER.forEach((k) => {
    // 类别以分组的键为准（网关回一个 o.k 也不认），条目本身走 state.js 那份 normYanCard：
    // 少一句 line、line 是数字、when 不是对象——都在渲染的地方抛，而抛出 runYan 的 try
    // 之外就是「遮罩永久挂着」（第一次全量注入认证之后量出来的，见 NEXT.md 第二十四轮）。
    (Array.isArray(r[k]) ? r[k] : []).forEach((x) => {
      const o = typeof x === "string" ? { line: x } : (x || {});
      const c = normYanCard({ ...o, k, done: false, moved: false, wset: false });
      if (c) out.push(c);
    });
  });
  return out;
}

/** 说话人小签：speaker 去掉结尾的「说」当显示名；空了退回 who；两者都无就不给签。 */
function speakerTag(c) {
  let name = c.speaker ? String(c.speaker).replace(/说$/, "") : "";
  if (!name) name = c.who || "";
  // 小签是「这句是谁说的」的标记，不是新信息：line 按约定保留原文不去前缀，
  // 所以名字出现两次是设计（README 里「会标出小红」就是它）。别在这儿去重。
  return name ? `<span class="speaker">${esc(name)}</span>` : "";
}

/** 一张卡的指纹：类别 + 原话。同一句在两个类别里算两张（「周五见」既可能是已定也可能被当成待办）。 */
const cardKey = (c) => c.k + "｜" + c.line;

/** 分批贴是常态，第二贴不该把第一贴冲掉。
 *  合并按指纹去重，已有的卡保持原样（勾掉的还是勾掉的），只 append 新出现的。
 *  手动挪过类别的那几条按「原话」认领：不然再贴同一段聊天时，引擎按它原来的类别
 *  又算一张，用户看到的是「我明明挪走了，怎么变成两条」。 */
function mergeCards(next) {
  const seen = new Set(state.yanCards.map(cardKey));
  const claimed = new Set(state.yanCards.filter((c) => c.moved).map((c) => c.line));
  const fresh = next.filter((c) => !seen.has(cardKey(c)) && !claimed.has(c.line));
  if (fresh.length) state.yanCards = state.yanCards.concat(fresh);
  return fresh.length;
}

async function runYan() {
  const text = $("#yanText").value;
  state.yanText = text; save(state);
  if (!text.trim()) { toast("先把说过的话贴进来"); return; }
  if (busy) return;
  if (!spend(1, "yan")) return;      // 笺点不足由 spend 自己提示
  busy = true;
  JianAPI.beginTurn();
  veil(true, "在捞这一段…");
  toast("捞笺中…");
  let r = null;
  try {
    r = await JianAPI.yan(text);
    const added = mergeCards(normCards(r));
    // 一句没多：这一批全捞过了，不该扣点，也不该在笺册里再塞一封一模一样的
    if (!added) refund(1, "yan");
    // 追问取最新一句非空的（它对应刚捞的这批）；新的为空就留着旧的，别清空
    state.yanAsk = r.ask || state.yanAsk;
    if (added) state.album.unshift({ type: "yan", t: Date.now(), quote: r.ask || "一封言笺",
      text: yanText() });
    save(state);
    renderYan();
    hintEngine("yan");   // 判定刚出，顶栏得跟着换：这一封是网关给的还是本地捞的
    if (added) haptic("MEDIUM");     // 真捞出了东西才给一记，空批不给
    // 不清输入框：合并之后框里那段还是「已经捞过的那批」，留着让人能改几个字再捞一次
    if (!added) toast(normCards(r).length ? "这批已经捞过了，一条没多" : "没捞到能落地的事，试试更像待办的句子");
  } catch (e) {
    refund(1, "yan");
    // 分开说：回话没来 vs 回话读不懂。后者是网关那边把形状弄坏了，
    // 一句「没捞成」会让人以为是自己贴的话不对。
    toast(r === null ? "这一封没捞成，笺点已退回" : "这一封的回话读不懂，笺点已退回");
  } finally {
    // 遮罩与忙闩**无条件**落下。以前收尾写在 try 外面，而 normCards 一抛就跳过它们：
    // 一个坏回包能把全屏遮罩永远挂着，除了一颗「先不等了」没法逃（衣笺早就是这副骨架）。
    busy = false;
    veil(false);
  }
}

function yanText() {
  const cards = state.yanCards || [];
  if (!cards.length) return "";
  const lines = ["【言笺】"];
  ORDER.forEach((k) => {
    const group = cards.filter((c) => c.k === k);
    if (!group.length) return;
    lines.push("", k);
    group.forEach((c) => {
      const tail = c.when ? `（${c.when.text}）` : "";
      lines.push(`· ${c.line}${tail}`);
    });
  });
  if (state.yanAsk) lines.push("", "追问：" + state.yanAsk);
  lines.push("", "一张短笺，一次决定");
  return lines.join("\n");
}

/** 言笺的搜索词。和柜子的 `closetQuery()` 同一套规矩：**读 DOM，不进 state**——
 *  一个没敲过的过滤词不该跟着备份跑到下一台机器上，也不该在重启之后还把人
 *  关在「搜不到」的那半屏里。 */
function yanQuery() {
  const el = $("#yanSearch");
  return el ? String(el.value || "").trim().toLowerCase() : "";
}

/* ==================== 视图与筛选（界面态，不进 state） ====================
   和搜索框同一条规矩：「我现在正按谁筛」是一次性的看法，不是这份笺的属性。
   进 state 会跟着备份跑去下一台机器，也会让人重启之后还困在「只显示 3 条」里。 */
let yanFilters = { who: "", status: "", range: "" };
/** 正看着归档没有。归档是这一张笺里的另一个抽屉，不是第四个视图。 */
let yanArchiveMode = false;
/** 「今天 / 今晚」两个抽屉收起来没有。 */
let slotClosed = { day: false, evening: false };
/** 月历正看着哪一个月、选中了哪一天。 */
let calMonth = null;
let calSel = "";
/** 自动归档的界线：勾掉满七天。 */
const ARCHIVE_AFTER = 7 * DAY;

function yanFilterOn() {
  return !!(yanFilters.who || yanFilters.status || yanFilters.range);
}

/** 这张笺里出现过的说话人（去重、去空）。「按人」那把筛的选项就从这儿来。 */
function yanPeople() {
  const set = new Set();
  (state.yanCards || []).forEach((c) => {
    if (c.archivedAt) return;
    if (c.who) set.add(String(c.who).replace(/说$/, ""));
    if (c.speaker) set.add(String(c.speaker).replace(/说$/, ""));
  });
  return [...set].filter(Boolean).sort((a, b) => a.localeCompare(b, "zh"));
}

/** 时间范围：今天 / 本周 / 已过。没有 when 的条目在任何范围里都不算命中——
 *  一把按时间筛的东西，不该把没写时间的也拉进来充数。 */
function yanInRange(c, range) {
  if (!range) return true;
  if (!c.when) return false;
  const at = c.when.at;
  if (range === "today") return dayStr(at) === dayStr(Date.now());
  if (range === "week") {
    const start = addDays(startOfDay(Date.now()), -weekIdx(Date.now()));
    return at >= start && at < addDays(start, 7);
  }
  if (range === "past") return at < Date.now();
  return true;
}

/** 这一屏「看得见的那几条」。**整张笺只有这一把筛**：整片重建、按键当下那行计数、
 *  日历上落不落格、归档里那几条——全读它。抄两份就是第 35 轮 nearWord 那个家族的旧账：
 *  两边各数一半，数字和列表迟早开始各说各话。 */
function yanShown() {
  const all = state.yanCards || [];
  const q = yanQuery();
  if (yanArchiveMode) {
    let arch = all.filter((c) => c.archivedAt);
    if (q) arch = arch.filter((c) =>
      `${c.line} ${c.who || ""} ${c.speaker || ""} ${c.k}`.toLowerCase().includes(q));
    return arch;
  }
  let cards = state.yanHideDone ? all.filter((c) => !c.done) : all;
  // 归档的那几条不进主列表：它们还在 state 里、还能看还能恢复，只是不该占着这一屏。
  cards = cards.filter((c) => !c.archivedAt);
  if (yanFilters.who) cards = cards.filter((c) =>
    `${c.who || ""} ${c.speaker || ""}`.replace(/说/g, "").includes(yanFilters.who));
  if (yanFilters.status === "todo") cards = cards.filter((c) => !c.done);
  else if (yanFilters.status === "done") cards = cards.filter((c) => c.done);
  if (yanFilters.range) cards = cards.filter((c) => yanInRange(c, yanFilters.range));
  if (q) cards = cards.filter((c) =>
    `${c.line} ${c.who || ""} ${c.speaker || ""} ${c.k}`.toLowerCase().includes(q));
  return cards;
}

/** 排着队还没画的那一次整片重建。 */
let yanRenderTimer = null;
function renderYanSoon() {
  if (yanRenderTimer) clearTimeout(yanRenderTimer);
  yanRenderTimer = setTimeout(() => { yanRenderTimer = null; renderYan(); }, 140);
}

/**
 * 搜索框里每敲一下走这里，而不是直接 renderYan()。
 * 200 条的时候一次整片重建要摆 1800 个节点：实测从按键到下一帧最坏 **139ms**
 * （桌面 Edge，手机上只会更糟），连打四个字就是四帧掉帧——连刚敲进去那个字都跟着顿。
 * 所以按键当下只做一件便宜事：把头上那行「搜「X」N / M 条」的数改对（一处 textContent，
 * 亚毫秒级），整片列表等手停下来 140 毫秒再重画。
 * 为什么只改计数不改行的显隐：行是按类型/按时间分了组的，藏掉几行就得连带着挪组标题和
 * 组内计数——那等于把分组逻辑再抄一份，两份迟早分家。宁可让列表晚 140 毫秒。
 */
function yanSearchTick() {
  const cnt = $("#yanCount"), all = state.yanCards || [], q = yanQuery();
  if (cnt && q) cnt.textContent = `搜「${esc(q)}」${yanShown().length} / ${all.length} 条`;
  else if (cnt) cnt.textContent = yanCountLine(all, yanShown());
  renderYanSoon();
}

/** 没有搜索词时那行怎么说。paintYan 的头和 yanSearchTick 清框那一下共用同一句。
 *  `cards` 由调用方给：它就是 `yanShown()` 的结果，这里再算一次是白扫 200 条。 */
function yanCountLine(all, cards) {
  const live = all.filter((c) => !c.archivedAt);
  const doneCount = live.filter((c) => c.done).length;
  if (yanFilterOn()) return `筛出 ${cards.length} · 一共 ${live.length}`;
  return state.yanHideDone ? `没办 ${cards.length} · 已勾 ${doneCount}`
    : `${live.length} 条 · 已勾 ${doneCount}`;
}

/**
 * 把命中的那一小截标出来。**先按位置切原文、逐段 esc()，再拼 `<mark>`**——
 * 反过来（整段先 esc 再替换）有两种坏法：查询里的 `&` 会撞上转义出来的 `&amp;`
 * 里的三个字母（标错地方），而查询里带 `<` 时替换进去的标记和转义后的实体混在一起，
 * 拼出来的就不是我以为的那段 HTML。逐段转义让这两件事都没法发生。
 */
function hitMark(text, q) {
  const s = String(text ?? "");
  if (!q) return esc(s);
  const low = s.toLowerCase(), needle = q.toLowerCase();
  let from = 0, out = "";
  for (;;) {
    const at = low.indexOf(needle, from);
    if (at < 0) break;
    out += esc(s.slice(from, at)) + "<mark>" + esc(s.slice(at, at + needle.length)) + "</mark>";
    from = at + needle.length;
  }
  return out + esc(s.slice(from));
}

/* ---------- 归档 ---------- */

/** 勾掉满七天、还没进归档的那几条，收进去。返回刚收走的那一批（给调用方说一声）。
 *
 *  **只在言笺这一屏真的在眼前时才收**：归档是一次「你没看着的时候东西挪了位置」，
 *  必须当场说一声、给一次反悔（草稿箱与笺册都守这条）。在别的屏上悄悄收走，
 *  用户切回言笺只会看到少了几条。 */
function yanArchiveDue() {
  const scr = document.querySelector(".screen.on");
  if (!scr || scr.id !== "yan") return [];
  const now = Date.now();
  const due = (state.yanCards || []).filter((c) =>
    c.done && !c.archivedAt && Number.isFinite(c.doneAt) && c.doneAt > 0 && now - c.doneAt > ARCHIVE_AFTER);
  if (!due.length) return [];
  due.forEach((c) => { c.archivedAt = now; });
  save(state);
  return due;
}

/** 归档里那几条：全部、按勾掉的时间倒序（最近收进来的在最上面）。 */
function yanArchived() {
  return (state.yanCards || []).filter((c) => c.archivedAt);
}

/** 「寄去别处」：这一条像不像一顿饭。猜的是**去向**，不是判定——
 *  猜错了按钮不出现，用户还看得见这句话本身；不会把话改了。 */
const MEAL_RE = /吃|饭|菜|汤|锅|面|粥|烧烤|火锅|外卖|订餐|馆子|餐厅|食堂|做饭|下厨|喝一杯/;
function looksLikeMeal(line) {
  const s = String(line || "");
  if (!s) return false;
  if (MEAL_RE.test(s)) return true;
  try { return typeof findDish === "function" && !!findDish(s); } catch (_) { return false; }
}

/** 已经给这一条定过提醒了吗（从言笺派生的、还没办完的那一条）。
 *  认的是**原话**：提醒不带言笺条目的下标（下标会随删除/重排变），
 *  而原话是这两份数据之间唯一稳定的那根线。同一句话说两遍会两条都亮，
 *  那是对的——确实两行共用一个提醒。 */
function reminderFor(c) {
  return (state.reminders || []).find((r) =>
    r.from === "yan" && !r.done && r.text === c.line) || null;
}

/* ---------- 月历 ---------- */

/** 一行笺的一部分要说的话拆开：徽章之外不留名字。
 *  **只在显示这一处去前缀**：c.line 本身不动，复制整张笺和笺册里存的还是原话。 */
function yanBodyText(c) {
  const name = c.speaker ? String(c.speaker).replace(/说$/, "") : (c.who || "");
  let text = c.line;
  for (const p of [c.speaker, name + "：", name + ":", name]) {
    if (p && text.length > p.length && text.startsWith(p)) { text = text.slice(p.length); break; }
  }
  text = text.replace(/^[：:]\s*/, "").replace(/^说\s*/, "");
  const body0 = c.when && text.startsWith(c.when.text) ? text.slice(c.when.text.length) : text;
  // 剥完什么都不剩就退回原话：宁可名字出现两次，也不能给出一行空白
  return body0.trim() ? body0 : c.line;
}

/** 一行笺。日历经、今天/今晚抽屉、按类型/按时间三处共用这一份——
 *  各写一份的下场是「同一句话在三个视图里有三种样子」，而修一处漏两处是必然的。 */
function yanRow(c, second) {
  const q = yanQuery();
  const all = state.yanCards || [];
  const body = yanBodyText(c);
  const who = c.who && !c.line.startsWith(c.who) ? `<span class="tiny"> · ${hitMark(c.who, q)}</span>` : "";
  const badge = speakerTag(c);
  const i = all.indexOf(c);
  const open = moveOpen.includes(i);
  const wopen = whenOpen.includes(i);
  const others = ORDER.filter((k) => k !== c.k);
  const rem = reminderFor(c);
  // 「寄去别处」：要买的送去衣笺过一件，像顿饭的已定送去味笺排桌。
  // 两枚都只在真的说得出「送过去之后会发生什么」时才出现。
  const jump = [];
  if (c.k === "要买") {
    jump.push(`<button type="button" class="ybtn sm" data-jump="yi" data-jump-i="${i}">寄去衣笺 · 过这一件</button>`);
  } else if (c.k === "已定" && looksLikeMeal(c.line)) {
    jump.push(`<button type="button" class="ybtn sm" data-jump="wei" data-jump-i="${i}">寄去味笺 · 排这一桌</button>`);
  }
  return `
    <!-- 整行以前就是一个 <label>：读屏器念复选框的名字时要把「挪 / 时间 / ×」和摊开的
         那排签一起念进去（可访问名字是整棵子树的文字），而按钮摆在 label 里本来就是
         非法的（笺册那行是同一个规定，见 styles.css 的 .slip-row）。
         现在 label 只包「复选框 + 眉料 + 正文」，动作是它的兄弟；display:contents
         让那三个孩子照样直接站进行里的网格，一格像素都不动。 -->
    <div class="check ${c.done ? "done" : ""}${second ? "" : " no-when"}">
      <label class="ck-main">
        <input type="checkbox" data-yi="${i}" ${c.done ? "checked" : ""}>
        ${second ? `<b>${esc(second)}</b>` : ""}
        <div class="ck-body">${badge}${hitMark(body, q)}${who}</div>
      </label>
      <span class="acts">
        <button type="button" class="bell${rem ? " on" : ""}" data-ybell="${i}"
                aria-pressed="${!!rem}" aria-label="${rem ? `已经定了提醒：${esc(whenText(rem.at))}，大约这个点` : "给这一条定提醒"}">${rem ? "已定" : "铃"}</button>
        <button type="button" class="mover" data-move="${i}" aria-expanded="${open}"
                aria-label="把这一条挪到别的类别">${c.moved ? "已挪" : "挪"}</button>
        <button type="button" class="wtimer" data-when="${i}" aria-expanded="${wopen}"
                aria-label="改这一条的时间">${c.wset ? "已定时" : "时间"}</button>
        <button type="button" class="drop" data-drop="${i}" aria-label="删掉这一条">×</button>
      </span>
      ${open ? `<div class="move-chips">${others.map((k) =>
        `<button type="button" class="chip" data-move-to="${k}" data-move-i="${i}">挪到「${k}」</button>`
      ).join("")}</div>` : ""}
      ${wopen ? `<div class="move-chips">
        ${WHEN_CHIPS.map((w) => `<button type="button" class="chip" data-when-to="${w}" data-when-i="${i}">${w}</button>`).join("")}
        <span class="datepick">挑一天<input type="date" data-wday="${i}" aria-label="改到某一天"></span>
        <button type="button" class="chip" data-when-to="" data-when-i="${i}">清掉</button>
        ${c.when ? `<button type="button" class="chip" data-slot-i="${i}" data-slot-to="${c.slot === "evening" ? "day" : "evening"}">${c.slot === "evening" ? "放回白天" : "放到今晚"}</button>` : ""}
      </div>` : ""}
      ${yanArchiveMode ? `<div class="move-chips">
        <button type="button" class="ybtn sm" data-unarchive="${i}">放回这张笺</button>
        <span class="tiny">勾掉 ${esc(shortDay(c.doneAt || c.archivedAt || Date.now()))}，收起来 ${esc(shortDay(c.archivedAt || Date.now()))}</span>
      </div>` : ""}
      ${jump.length ? `<div class="yan-jump">${jump.join("")}</div>` : ""}
    </div>`;
}

function yanCalInit() {
  const now = new Date();
  if (!calMonth) calMonth = { y: now.getFullYear(), m: now.getMonth() };
  if (!calSel) calSel = dayStr(Date.now());
}
function calShift(n) {
  yanCalInit();
  const d = new Date(calMonth.y, calMonth.m + n, 1);
  calMonth = { y: d.getFullYear(), m: d.getMonth() };
  // 换月之后刚才选中的那天已经不在这一屏上了：清掉，让用户点新的那天。
  calSel = "";
  renderYan();
}
function calBackThisMonth() {
  const now = new Date();
  calMonth = { y: now.getFullYear(), m: now.getMonth() };
  calSel = dayStr(Date.now());
  renderYan();
}
/** 「9月17日」这种说法（读屏器与当天列表的标题共用）。 */
function calDayLabel(ts) {
  const d = new Date(ts);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 月历那一块。**七列对齐**、今天带标记、有事的日期带圆点——不是七个格子里堆字。
 *  周一开头（与 weekIdx / 热力图同一口径），前后补齐相邻月份的日子（灰的），
 *  这样每一行的星期都对得上，看起来才是一页真正的月历。 */
function yanCalendarHTML(cards) {
  yanCalInit();
  const { y, m } = calMonth;
  const byDay = {};
  cards.forEach((c) => {
    if (!c.when) return;
    const k = dayStr(c.when.at);
    (byDay[k] = byDay[k] || []).push(c);
  });
  const first = new Date(y, m, 1);
  const lead = weekIdx(first.getTime());           // 周一起：0=周一 … 6=周日
  const daysIn = new Date(y, m + 1, 0).getDate();
  const prevMonthDays = new Date(y, m, 0).getDate();
  const todayK = dayStr(Date.now());
  const cell = (ts, out) => {
    const k = dayStr(ts);
    const n = (byDay[k] || []).length;
    const cls = ["cal-day", "yd"];
    if (out) cls.push("out");
    if (n) cls.push("has2");       // 不用 .has：styles-v06 给它挂了一颗固定 ::after 圆点，这里自己画
    if (k === todayK) cls.push("today");
    if (k === calSel) cls.push("on");
    return `<button type="button" class="${cls.join(" ")}" data-cald="${k}"
      aria-label="${esc(calDayLabel(ts))}${n ? `，${n} 件` : "，没事"}"
      aria-pressed="${k === calSel}">${new Date(ts).getDate()}<span class="cal-dots" aria-hidden="true">${
      n ? "<i></i>".repeat(Math.min(3, n)) + (n > 3 ? `<b>${n}</b>` : "") : ""}</span></button>`;
  };
  const cells = [];
  for (let i = lead; i > 0; i--) cells.push(cell(new Date(y, m - 1, prevMonthDays - i + 1).getTime(), true));
  for (let d = 1; d <= daysIn; d++) cells.push(cell(new Date(y, m, d).getTime(), false));
  // 补到最后一行满：真的月历不会在最后一周留半截
  for (let d = 1; cells.length % 7; d++) cells.push(cell(new Date(y, m + 1, d).getTime(), true));

  const hello = thisMonthCount(byDay, y, m);
  const selCards = calSel ? (byDay[calSel] || []).slice() : [];
  const selTs = calSel ? new Date(String(calSel).replace(/\./g, "-")).getTime() : 0;

  return `<div class="yan-cal">
    <div class="bar cal-nav">
      <button type="button" class="ybtn sm" id="yanCalPrev" aria-label="上一个月">‹</button>
      <p class="cal-title serif">${y} 年 ${m + 1} 月</p>
      <button type="button" class="ybtn sm" id="yanCalNext" aria-label="下一个月">›</button>
    </div>
    <p class="tiny cal-sub">这个月 ${hello} 天有事${calSel ? ` · 选中 ${esc(calDayLabel(selTs))}` : ""}
      ${calMonthIsNow() ? "" : ` · <button type="button" class="ybtn sm" id="calBack">回到这个月</button>`}</p>
    <div class="cal-head">${["一", "二", "三", "四", "五", "六", "日"].map((w) => `<span>${w}</span>`).join("")}</div>
    <div class="cal-grid">${cells.join("")}</div>
    <div class="space"></div>
    <p class="tiny rem-sec">${calSel ? esc(calDayLabel(selTs)) + ` · ${selCards.length} 件` : "点一天看那天的事"}</p>
    ${selCards.length ? selCards.sort((a, b) => a.when.at - b.when.at).map((c) => yanRow(c, c.k)).join("")
      : `<p class="tiny yan-empty-line">${calSel ? "这一天没有事。" : "上面点一天，看那天有什么。"}</p>`}
  </div>`;
}
function thisMonthCount(byDay, y, m) {
  let n = 0;
  Object.keys(byDay).forEach((k) => {
    const d = new Date(String(k).replace(/\./g, "-"));
    if (!Number.isFinite(d.getTime())) return;
    if (d.getFullYear() === y && d.getMonth() === m) n++;
  });
  return n;
}
function calMonthIsNow() {
  yanCalInit();
  const n = new Date();
  return calMonth.y === n.getFullYear() && calMonth.m === n.getMonth();
}

/** 「今天 / 今晚」两个抽屉。抽屉标题用 <p class="tiny"> 而不是 <summary>：
 *  一行筛签 + 计数是这一屏的既有说法，读屏器念得清，也不占额外一格高度。
 *  `which` 是 slot 的档位；收起来的状态记在 slotClosed（界面态，不进 state）。
 *  行上的眉料用**时分**而不是「今天」：抽屉题目已经写着今天，
 *  每一行再写一遍「今天」是两个一样的字并排站，什么信息都没多。 */
function slotDrawer(title, arr, which) {
  const closed = !!slotClosed[which];
  const hm = (c) => {
    const d = new Date(c.when.at);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };
  return `<div class="bar">
      <p class="tiny">${title}</p>
      <span class="slot-head">
        <span class="tiny">${arr.length}</span>
        <button type="button" class="ybtn sm" data-slot-fold="${which}" aria-expanded="${!closed}">${closed ? "展开" : "收起"}</button>
      </span>
    </div>
    ${closed ? "" : (arr.length ? arr.map((c) => yanRow(c, hm(c))).join("")
      : `<p class="tiny yan-empty-line">${which === "evening" ? "今晚还空着。给一条点「时间」，再选「放到今晚」。" : "今天没有白天的事。"}</p>`)}`;
}

/** 「寄去别处」：把这一条送进别的笺，并且**说清会发生什么**。
 *  衣笺那一步只带名字（照片得自己拍——不替用户造一张不存在的图）；
 *  味笺那一步把它添进菜单的一行，排桌仍然由用户按。 */
function sendToYi(text) {
  const nm = String(text || "").replace(/\s+/g, " ").trim().slice(0, 40);
  if (!nm) { toast("这一条没有名字可以带过去"); return; }
  if (typeof presetNewName === "function") presetNewName(nm);
  show("yi");
  // **必须把页签切回「过笺」**：衣笺落在上一次停下的那一个页签（内存里的 yiTab，
  // 可能是柜子或愿望）。不切的话，用户从言笺点过来看到的是柜子，
  // 过笺入口根本不在这屏上——那就成了「按了有反应，但落在了看不见的地方」。
  if (typeof setYiTab === "function") setYiTab("pass");
  // 说清「到了衣笺要做什么」：照片得自己拍，没有照片就没有判定。
  toast(`已到衣笺。「${nm}」的名字记下了，拍一张照片就能过这一件`);
}
function sendToWei(text) {
  const line = String(text || "").replace(/\s+/g, " ").trim().slice(0, 40);
  if (!line) { toast("这一条没有内容可以带过去"); return; }
  const menu = $("#menu");
  if (!menu) { toast("味笺的菜单框没找到"); return; }
  const cur = String(menu.value || "").trim();
  menu.value = cur ? cur + "\n" + line : line;
  // 走 input 这一个入口：state.weiMenu、落盘、「这张是上一版的」提示三件事同时更新
  menu.dispatchEvent(new Event("input"));
  if (typeof setWeiTab === "function") setWeiTab("plan");
  show("wei");
  toast(`已经放进菜单：${line}。按「排这桌」就算这一桌`);
}

function renderYan() {
  // 有人已经把整片画过了，排队那一次就不必再来一遍（不然刚点完「清掉搜索」
  // 还会被 140 毫秒前那一下再刷一次）。
  if (yanRenderTimer) { clearTimeout(yanRenderTimer); yanRenderTimer = null; }
  const fk = focusKey();
  // 勾掉满七天的先收进归档，再画——画的时候它们就不在主列表上了。
  const pushed = yanArchiveDue();
  paintYan();
  restoreFocus(fk);
  // 自动移出主列表**必须说一声**：悄悄少东西，用户会以为丢了。
  // 撤销把 doneAt 一起清掉：这一条不再参与自动归档（用户已经明确说过要留着）。
  if (pushed.length) {
    toastUndo(`已把 ${pushed.length} 条办完的事收进归档`, () => {
      pushed.forEach((c) => { c.archivedAt = null; c.doneAt = null; });
      save(state); renderYan();
      toast("那几条回到这张笺上了");
    });
  }
}

/**
 * 勾一下不必重建整片。200 条的时候一次 paintYan 要摆 1696 个节点，光布局就 34ms
 * （桌面 Chromium 实测，JS 只占 2ms）——手机上是一次看得见的顿，而勾选是这一屏
 * 重复次数最高的动作。就地改的只有这一行的样子和三处计数；改不了的（「只看没办的」
 * 里刚勾上那条要从屏上消失、分组要重算）返回 false 让调用方整片重建：
 * 宁可慢那一次，不能少算一个数。
 */
function patchYanDone(el, c) {
  const row = el.closest(".check");
  if (!row || el.checked !== c.done) return false;
  if (state.yanHideDone && c.done) return false;
  // 搜索生效时顶上那行写的是「搜「X」N / M 条」，不是「N 条 · 已勾 M」。
  // 就地补丁里再抄一份那个格式，就是两份口径开始分家的地方——直接退回整片重建。
  if (yanQuery()) return false;
  // 按人/按状态/按时间那三把筛同理：头上那行换成了「筛出 N · 一共 M」，
  // 补丁里再抄一份就是第三处口径。退回整片重建。
  if (yanFilterOn() || yanArchiveMode) return false;
  const cnt = $("#yanCount"), pr = $("#yanPrune");
  if (!cnt || !pr) return false;
  row.classList.toggle("done", c.done);
  const all = (state.yanCards || []).filter((x) => !x.archivedAt);
  const doneCount = all.filter((x) => x.done).length;
  // 这里只有「N 条 · 已勾 M」一种说法，没有「没办 N · 已勾 M」那一支：上面那道
  // `yanHideDone && c.done` 已经把「只看没办的」整条挡回整片重建了，走到这一行的时候
  // hideDone 一定是关着的——那一支是够不着的死话（第 44 轮的注入认证撞出来的）。
  // 哪天放开成「勾上了也留在屏上」，那支措辞要连这道挡一起加回来。
  cnt.textContent = `${all.length} 条 · 已勾 ${doneCount}`;
  pr.textContent = `清掉勾掉的 ${doneCount}`;
  pr.hidden = !doneCount;
  const g = $(`#yanOut [data-yangroup="${c.k}"]`);
  if (g) {
    const same = all.filter((x) => x.k === c.k);
    g.textContent = `${same.filter((x) => x.done).length}/${same.length}`;
  }
  return true;
}

function paintYan() {
  const box = $("#yanOut");
  if (!box) return;
  const all = state.yanCards || [];
  // 一张空笺不该摆着一个搜了也白搜的框（第 27 轮那条「不摆按了没用的按钮」的输入框版本）。
  // 这一句还要摆在下面那个「一条都没有」的早退**之前**：藏框对空笺恰恰最要紧，
  // 放在早退后面就永远轮不到它执行（自己写的断言当场抓出来的）。
  const bar = $("#yanSearchBar");
  if (bar) bar.hidden = !all.length;
  if (!all.length) {
    box.innerHTML = state.yanAsk
      ? `<div class="empty">这段里没捞出能落地的事。<br>试试更像待办的句子，比如「明天记得把材料发我」。</div>`
      : `<div class="empty">贴一段聊天，点「捞成笺」。<br>它会挑出要办的、要买的、已经定下的。</div>`;
    return;
  }

  // 「只看没办的」：勾完十条之后满屏还是那十条，划半天找不到还剩什么没做。
  // 过滤只作用于显示——行上的 data-yi 仍是全量下标，勾掉/删掉的都是同一条。
  // 搜索是第二把同样的筛，同一条规矩：它筛掉的条目的下标不许往前挪（第 15 / 22 / 28 轮
  // 三次踩过同一处：用「屏上第几行」当下标，点第一行会办到另一条上去）。
  const cards = yanShown();
  const live = all.filter((c) => !c.archivedAt);
  const doneCount = live.filter((c) => c.done).length;
  const archCount = yanArchived().length;
  const q = yanQuery();
  // 三把筛一直都在：设过之后还得能改、能撤。藏起来（只在没筛时摆）会有两种坏法——
  // 筛完之后控件消失，用户以为这一屏只有这么点东西；而且唯一的出路是「筛都清掉」
  // 那枚，它只在筛到一条不剩时才出现，筛剩下三条的人就被关在这三把筛里了。
  const filterRow = yanArchiveMode ? "" : `
    <div class="chips yan-filter-row" id="yanFilters">
      <select id="yanWho" class="yan-sel" aria-label="按人筛">
        <option value="">按人 · 都看</option>
        ${yanPeople().map((n) => `<option value="${esc(n)}"${yanFilters.who === n ? " selected" : ""}>${esc(n)}</option>`).join("")}
      </select>
      <select id="yanStatus" class="yan-sel" aria-label="按状态筛">
        <option value=""${yanFilters.status === "" ? " selected" : ""}>办没办 · 都看</option>
        <option value="todo"${yanFilters.status === "todo" ? " selected" : ""}>没办的</option>
        <option value="done"${yanFilters.status === "done" ? " selected" : ""}>已勾的</option>
      </select>
      <select id="yanRange" class="yan-sel" aria-label="按时间范围筛">
        <option value=""${yanFilters.range === "" ? " selected" : ""}>什么时候 · 都看</option>
        <option value="today"${yanFilters.range === "today" ? " selected" : ""}>今天</option>
        <option value="week"${yanFilters.range === "week" ? " selected" : ""}>本周</option>
        <option value="past"${yanFilters.range === "past" ? " selected" : ""}>已经过了</option>
      </select>
      ${yanFilterOn() ? `<button class="chip" id="yanClearFilter">筛都清掉</button>` : ""}
    </div>`;

  const head = yanArchiveMode ? `
    <div class="bar">
      <p class="tiny" id="yanArchiveCount">归档 · ${archCount} 条</p>
      <div class="chips">
        <button class="chip" id="yanUnarchAll">回到这张笺</button>
      </div>
    </div>
    <p class="tiny">办完满七天的事会自动收到这里。它们还在，随时可以放回去。</p>` : `
    <div class="bar">
      <p class="tiny" id="yanCount">${
        q ? `搜「${esc(q)}」${cards.length} / ${all.length} 条` : yanCountLine(all, cards)}</p>
      <div class="chips">
        <button class="chip ${state.yanView === "kind" ? "on" : ""}" data-yanview="kind" aria-pressed="${state.yanView === "kind"}">按类型</button>
        <button class="chip ${state.yanView === "time" ? "on" : ""}" data-yanview="time" aria-pressed="${state.yanView === "time"}">按时间</button>
        <button class="chip ${state.yanView === "calendar" ? "on" : ""}" data-yanview="calendar" aria-pressed="${state.yanView === "calendar"}">日历</button>
        <button class="chip ${state.yanHideDone ? "on" : ""}" id="yanUndone" aria-pressed="${!!state.yanHideDone}">只看没办的</button>
        <!-- 数量变了要就地改文字，所以这枚一直在 DOM 里、用 hidden 收放；
              以前它整个不存在，勾上第一条之后不重建就没有它。 -->
        <button class="chip" id="yanPrune" ${doneCount ? "" : "hidden"}>清掉勾掉的 ${doneCount}</button>
      </div>
    </div>
    ${filterRow}
    <!-- 这两枚是对**整张笺**的动作，以前排在所有行的下面：笺越攒越长，200 条的时候
         它们离首屏 40 屏（实测），想复制一次得先划过自己一年的聊天记录。
         动作不许埋在它所作用的列表底下——量出来的那条不变量见 e2e §46。
         搬上来之后重拍商店截图又看见另一件事：那两枚是 46px 高的实心黑按钮（.btn），
         于是「清空这张」成了整屏最抢眼的东西，压在一屏只有五条待办的人脸上。
         这一屏的主动作是「捞成笺」和逐条打勾，不是清空——所以它们用签的份量，
         和上面的筛选签分两行摆，谁是谁一眼分得清。 -->
    <div class="chips" style="margin-top:8px">
      <button class="chip" id="copyYan">复制整张笺</button>
      <button class="chip" id="clearYan">清空这张</button>
      ${archCount ? `<button class="chip" id="yanArch">归档 ${archCount}</button>` : ""}
    </div>`;

  let body = "";
  if (yanArchiveMode) {
    const arch = cards.slice().sort((a, b) => (b.archivedAt || 0) - (a.archivedAt || 0));
    body = arch.length
      ? `<div class="space"></div>${arch.map((c) => yanRow(c, c.k)).join("")}`
      : `<div class="empty">归档是空的。<br>办完满七天的事会自动收到这里。</div>`;
  } else if (!cards.length && q) {
    // 三种空态各有各的原因，别都写成「没有条目」：搜空了的时候告诉人是他这个词没有，
    // 并且当场给一条出路（柜子的 #clearSearch 同一个写法）。
    body = `<div class="empty">这张笺里搜不到「${esc(q)}」。<br>换个词，或 `
      + `<button type="button" class="chip" id="clearYanSearch">清掉搜索</button></div>`;
  } else if (!cards.length && yanFilterOn()) {
    body = `<div class="empty">这几把筛一起用，一条都没剩下。<br>`
      + `<button type="button" class="chip" id="clearYanFilter">筛都清掉</button></div>`;
  } else if (!cards.length) {
    body = `<div class="empty">没办的清完了。<br>取消「只看没办的」回看勾掉的。</div>`;
  } else if (state.yanView === "calendar") {
    body = yanCalendarHTML(cards);
  } else if (state.yanView === "time") {
    const timed = cards.filter((c) => c.when).sort((a, b) => a.when.at - b.when.at);
    const untimed = cards.filter((c) => !c.when);
    const todayStart = startOfDay(Date.now());
    const todayCards = timed.filter((c) => startOfDay(c.when.at) === todayStart);
    const dayCards = todayCards.filter((c) => c.slot !== "evening");
    const eveCards = todayCards.filter((c) => c.slot === "evening");
    const rest = timed.filter((c) => startOfDay(c.when.at) !== todayStart);
    const groups = [];
    rest.forEach((c) => {
      const label = dayLabel(c.when.at);
      const last = groups[groups.length - 1];
      if (last && last.label === label) last.items.push(c);
      else groups.push({ label, items: [c] });
    });
    // 「今天 / 今晚」两抽屉摆在这一屏最上面：一天里只有这两段是「现在就要动手」的。
    body = slotDrawer("今天", dayCards, "day") + slotDrawer("今晚", eveCards, "evening")
      + groups.map((g) => `
      <div class="bar"><p class="tiny">${esc(g.label)}</p><span class="tiny">${g.items.length}</span></div>
      ${g.items.map((c) => yanRow(c, c.k)).join("")}
      <div class="space"></div>`).join("")
      + (untimed.length ? `
      <div class="bar"><p class="tiny">没写时间</p><span class="tiny">${untimed.length}</span></div>
      <p class="tiny yan-empty-line">没写时间的排不进今天或今晚——给一条点「时间」定一个。</p>
      ${untimed.map((c) => yanRow(c, c.k)).join("")}
      <div class="space"></div>` : "");
  } else {
    body = ORDER.filter((k) => cards.some((c) => c.k === k)).map((k) => {
      const group = cards.filter((c) => c.k === k);
      return `
        <div class="bar"><p class="tiny">${k}</p><span class="tiny" data-yangroup="${k}">${group.filter((c) => c.done).length}/${group.length}</span></div>
        ${group.map((c) => yanRow(c, c.when ? c.when.text : "")).join("")}
        <div class="space"></div>`;
    }).join("");
  }

  box.innerHTML = `
    <div class="sheet">
      <p class="meta">JIAN · YAN</p>
      <span class="seal-mark lg serif" aria-hidden="true">言</span>
      ${head + body}
      ${state.yanAsk ? `<div class="rule"></div><p class="tiny sheet-cap">追问</p><p class="quote serif">${esc(state.yanAsk)}</p>` : ""}
      ${digestSheetHTML()}
    </div>`;

  const cs = $("#clearYanSearch");
  if (cs) cs.onclick = () => {
    const s = $("#yanSearch");
    if (s) s.value = "";
    renderYan();
    if (s) s.focus();          // 清完把光标还给搜索框：下一步多半是换个词再搜
  };
  const cf = $("#clearYanFilter");
  if (cf) cf.onclick = () => {
    yanFilters = { who: "", status: "", range: "" };
    renderYan();
    toast("筛都清掉了");
  };
  const ycf = $("#yanClearFilter");
  if (ycf) ycf.onclick = () => {
    yanFilters = { who: "", status: "", range: "" };
    renderYan();
    toast("筛都清掉了");
  };
  $$("#yanOut [data-yi]").forEach((el) => {
    el.onchange = () => {
      const i = +el.dataset.yi, c = state.yanCards[i];
      if (!c) { renderYan(); return; }     // 行和数据对不上（外来备份刚换过）：宁可整片重来
      c.done = el.checked;
      // 勾掉那一刻记下来：归档的七天从这儿算。取消勾就把时间清掉——
      // 一条没办完的事没有「办完的时间」。
      c.doneAt = el.checked ? Date.now() : null;
      save(state);
      if (!patchYanDone(el, c)) renderYan();
      // 勾一下是这份 state 里唯一**没有反悔**的行内动作。取消勾对本来就地再点一次就行，
      // 可开着「只看没办的」时勾上等于把那一行从屏上抹掉（上面那一次 renderYan）——
      // 想反悔得先关掉过滤、再在剩下的几百条里把它找回来。那一趟没有第二条路，所以在这里给一次反悔。
      // 没开着过滤时不给：那一行还在眼前，勾着的框就是它自己的撤销。
      if (el.checked && state.yanHideDone) {
        toastUndo(`已勾掉「${c.line.slice(0, 20)}」，这一行从「只看没办的」里收起来了`, () => {
          // 5.2 秒里这一条可能被同一屏那枚「清掉勾掉的」整批扔了（勾着的都会被扔）。
          // 对着已经不在账上的东西说「回来了」是假话：重画一次让用户看见真相，并说清撤不了。
          if (state.yanCards.indexOf(c) < 0) { renderYan(); toast("那一条已经被清掉了，撤不回来"); return; }
          c.done = false; c.doneAt = null; save(state); renderYan();
          toast("取消勾对了，那一行回到这一屏");
        });
      }
    };
  });
  $$("#yanOut [data-yanview]").forEach((b) => {
    b.onclick = () => {
      state.yanView = b.dataset.yanview;
      // 换视图不该把归档那个抽屉也一起带过去：归档是回看，不是第四种排法
      yanArchiveMode = false;
      save(state); renderYan();
    };
  });
  const fu = $("#yanUndone");
  if (fu) fu.onclick = () => { state.yanHideDone = !state.yanHideDone; save(state); renderYan(); };
  // 勾满十条之后想清场，以前只有「清空这张」——把没办的也一起扔了。
  // 这一枚只扔勾掉的；笺册里那张没动——说的是这一次动作，不是替笺册作保（它只留 24 张）。
  const pr = $("#yanPrune");
  if (pr) pr.onclick = () => {
    const gone = [], at = [];
    state.yanCards.forEach((c, i) => { if (c.done && !c.archivedAt) { gone.push(c); at.push(i); } });
    if (!gone.length) return;
    state.yanCards = state.yanCards.filter((c) => c.archivedAt || !c.done);
    moveOpen = [];                      // 下标全变了，两排展开态一起作废
    whenOpen = [];
    save(state); renderYan();
    toastUndo(`已清掉 ${gone.length} 条了结的（笺册里那张没动）`, () => {
      // 按原下标升序插回去：倒着插会全落到末尾，撤销之后顺序和勾掉前不一样
      at.forEach((idx, k) => state.yanCards.splice(Math.min(idx, state.yanCards.length), 0, gone[k]));
      save(state); renderYan();
    });
  };
  // 删一条：以前整张笺只有「清空这张」，想扔掉一条只能全清重来。
  // 有了一次反悔，× 才敢直接摆在行上。
  $$("#yanOut [data-drop]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.drop;
      const [gone] = state.yanCards.splice(i, 1);
      moveOpen = [];                    // 下标整体前移，展开着的选择器会指到别的条上
      whenOpen = [];                    // 两排选择器都是按下标记的，一起作废
      save(state); renderYan();
      toastUndo("已删掉这一条", () => {
        state.yanCards.splice(Math.min(i, state.yanCards.length), 0, gone);
        save(state); renderYan();
      });
    };
  });
  // 类别是关键词猜的，猜错了不该只能整条删掉。挪一下，原话、时间、说话人都跟着走。
  $$("#yanOut [data-move]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.move;
      whenOpen = [];                    // 一屏只摊一排签：两排同时摊着，谁都不知道 × 归谁
      moveOpen = moveOpen.includes(i) ? moveOpen.filter((x) => x !== i) : [i];
      renderYan();
    };
  });
  $$("#yanOut [data-move-to]").forEach((b) => {
    b.onclick = () => {
      const c = state.yanCards[+b.dataset.moveI], k = b.dataset.moveTo;
      if (!c || c.k === k) return;
      const from = c.k;
      c.k = k; c.moved = true;
      moveOpen = [];
      save(state); renderYan();
      toastUndo(`已挪到「${k}」`, () => {
        c.k = from; c.moved = false;
        save(state); renderYan();
      });
    };
  });
  // 时间也是猜的，而猜错的时间比猜错的类别更疼：类别错了看得见，日期过了看不见。
  $$("#yanOut [data-when]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.when;
      moveOpen = [];                    // 与上面相反：一屏只摊一排签
      whenOpen = whenOpen.includes(i) ? whenOpen.filter((x) => x !== i) : [i];
      renderYan();
    };
  });
  $$("#yanOut [data-when-to]").forEach((b) => {
    b.onclick = () => {
      const w = b.dataset.whenTo;
      setWhen(+b.dataset.whenI, w ? whenFromLabel(w) : null);
    };
  });
  $$("#yanOut [data-wday]").forEach((el) => {
    el.onchange = () => {
      const w = whenFromDate(el.value);
      // 没挑完（年/月/日只填了一半）不改，别把原时间清成空 —— 这是对的取舍，
      // 但挡下来必须说：不然用户以为「这日期框点了没反应」。旁边那枚「清掉」
      // （见上面模板里 data-when-to=""）才是去掉时间的出路，话要指得准。
      if (!w) { toast("日期没填全，时间先不动；要去掉它按旁边的「清掉」"); return; }
      setWhen(+el.dataset.wday, w);
    };
  });
  // 白天 / 今晚：一句「晚上八点再说」的话，大白天摊在「今天」里就是在催。
  $$("#yanOut [data-slot-i]").forEach((b) => {
    b.onclick = () => {
      const c = state.yanCards[+b.dataset.slotI];
      if (!c) return;
      c.slot = b.dataset.slotTo === "evening" ? "evening" : "day";
      save(state); renderYan();
      toast(c.slot === "evening" ? "这一条挪到今晚了（在「按时间」里看得见）" : "这一条放回白天了");
    };
  });
  // 铃铛：给这一条定提醒。已经有时间就用它的时间；没有就把「时间」那排摊开——
  // 定在哪一天是用户的事，替她猜一个时间再通知她，比不提醒更糟。
  $$("#yanOut [data-ybell]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.ybell, c = state.yanCards[i];
      if (!c) return;
      const rem = reminderFor(c);
      if (rem) { toast(`这一条已经定在 ${whenText(rem.at)}（大约这个点）`); return; }
      if (!c.when) {
        moveOpen = [];
        whenOpen = [i];
        renderYan();
        toast("这一条还没写时间。挑一个，定下来之后铃铛就亮了");
        return;
      }
      remindYanCard(c);
      renderYan();
    };
  });
  // 寄去别处
  $$("#yanOut [data-jump]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.jumpI, c = state.yanCards[i];
      if (!c) return;
      // 带过去的是**显示出来那一句**（名字已经在徽章里，别再带一遍）
      const nm = yanBodyText(c);
      if (b.dataset.jump === "yi") sendToYi(nm);
      else sendToWei(nm);
    };
  });
  // 归档：进 / 出 / 恢复
  const arch = $("#yanArch");
  if (arch) arch.onclick = () => {
    yanArchiveMode = true;
    yanFilters = { who: "", status: "", range: "" };
    renderYan();
  };
  const unarchAll = $("#yanUnarchAll");
  if (unarchAll) unarchAll.onclick = () => { yanArchiveMode = false; renderYan(); };
  $$("#yanOut [data-unarchive]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.unarchive;
      const c = state.yanCards[i];
      if (!c) return;
      const at = c.archivedAt, done = c.doneAt;
      // 放回去的时候把 doneAt 一起清掉：用户已经明确说过「这一条要留着」，
      // 下次进屏不该再被同一个七天规则收走（清勾再勾会重新计时）。
      c.archivedAt = null; c.doneAt = null;
      save(state); renderYan();
      toastUndo("已放回这张笺", () => {
        c.archivedAt = at; c.doneAt = done;
        save(state); renderYan();
      });
    };
  });
  // 月历
  const cp = $("#yanCalPrev");
  if (cp) cp.onclick = () => calShift(-1);
  const cn = $("#yanCalNext");
  if (cn) cn.onclick = () => calShift(1);
  const cb2 = $("#calBack");
  if (cb2) cb2.onclick = () => calBackThisMonth();
  $$("#yanOut [data-cald]").forEach((b) => {
    b.onclick = () => {
      calSel = b.dataset.cald;
      renderYan();
    };
  });
  // 今天 / 今晚：抽屉收放
  $$("#yanOut [data-slot-fold]").forEach((b) => {
    b.onclick = () => {
      const w = b.dataset.slotFold;
      slotClosed[w] = !slotClosed[w];
      renderYan();
    };
  });
  // 那三把筛：换了就整片重建（筛选只走 yanShown 一处口径）
  [["#yanWho", "who"], ["#yanStatus", "status"], ["#yanRange", "range"]].forEach(([sel, key]) => {
    const el = $(sel);
    if (el) el.onchange = () => {
      yanFilters[key] = el.value;
      renderYan();
    };
  });
  // 摘录本
  bindDigestSheet();
  const cb = $("#copyYan");
  if (cb) cb.onclick = () => copy(yanText(), "已复制整张笺");  const cl = $("#clearYan");
  if (cl) cl.onclick = () => {
    if (!state.yanCards.length && !state.yanAsk) return;
    const gone = state.yanCards, goneAsk = state.yanAsk;
    state.yanCards = []; state.yanAsk = "";
    save(state); renderYan();
    toastUndo("已清空这张笺", () => {
      state.yanCards = gone; state.yanAsk = goneAsk;
      save(state); renderYan();
    });
  };
}
