/** 笺 · 今日
 *
 *  这一屏回答的是「我为什么今天要打开这个 App」，而不是「我有哪些功能」。
 *
 *  三条设计硬约束（写成代码是因为软约束都会被后来的改动磨平）：
 *  1. **永远只显示三件事。**再多就变仪表盘，而仪表盘是「多」的产品，笺是「少」的。
 *  2. **当天只变一次。**三件事按当天的数据挑，挑定之后在本机记一笔（jian.today）：
 *     白天再打开还是同三件——每次打开都换一批等于没有建议，只是噪音。
 *     「再抽一笺」是用户**主动**要换，那是另一回事（见 todayNext()）。
 *  3. **不许空着。**新用户柜子是种子柜、言笺是空的、味笺没排过桌：
 *     这时候三件事要变成「怎么开始」的三步，而不是三行「暂无数据」。
 *
 *  三件事的来源各有各的挑选逻辑（衣服：当季 + 久未穿/没穿过；味道：没做过 + 这桌人能吃 +
 *  当季；言笺：今天到期 > 已过期 > 还没说清），但**都在这里收口**，因为「今天给你看哪三件」
 *  是一个产品决定，拆到三个文件里就再也没人能一眼看出它到底怎么选的。
 *
 *  另一条更硬的规矩：**每一件都能当场做完**。只给三个「跳过去看看」的入口，
 *  这一屏就退化成目录，而目录不需要每天打开。做完之后那一行变成「✓ 今天做过了」，
 *  不消失——用户需要看见自己的成果。
 */

/** 当天日期做种子的小随机：同一个日子永远得到同一个结果。
 *  不用 Math.random——那会让「明天再看」这件事失去意义（今天和明天一样随机）。 */
function daySeed(extra) {
  const s = dayStr(Date.now()) + String(extra || "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
/** 从数组里按当天种子挑 i 个（i 大于长度时循环补，但不重复同一项直到用完一轮）。 */
function seededPick(list, i, extra) {
  const arr = (list || []).slice();
  if (!arr.length) return [];
  const out = [];
  let seed = daySeed(extra);
  for (let k = 0; k < i && k < arr.length; k++) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    out.push(arr.splice(seed % arr.length, 1)[0]);
  }
  return out;
}
/** 整池的确定顺序（洗一次、同一天永远一样）。seededPick 的「取 i 个」在 i=长度 时就是洗牌。 */
function seededOrder(list, extra) { return seededPick(list, (list || []).length, extra); }

/* ==================== 今天的三件：挑定之后记在本机 ====================
   为什么不是 state：这三件是**今天这一屏的便签**，不是用户的数据。
   进了 state 就会跟着备份往返、被统计数一遍，而它明天就该作废。
   为什么不是内存变量：安卓上退到后台再回来、或者浏览器里按一下刷新，
   内存变量就没了，于是「同一天内稳定」当场破功。所以单独一个键、当天有效。
   它读坏了/不见了都不影响任何真实数据——最坏的情况就是重挑一遍。 */
const TODAY_KEY = "jian.today";

function todayMemoLoad() {
  try {
    const o = JSON.parse(localStorage.getItem(TODAY_KEY) || "null");
    if (!o || o.day !== dayStr(Date.now()) || !o.pick || typeof o.pick !== "object") return null;
    return { day: o.day, pick: { yi: String(o.pick.yi || ""), wei: String(o.pick.wei || ""), yan: String(o.pick.yan || "") } };
  } catch (_) { return null; }
}
function todayMemoSave(pick) {
  try { localStorage.setItem(TODAY_KEY, JSON.stringify({ day: dayStr(Date.now()), pick })); } catch (_) { /* 存不进去就退化成每次重挑 */ }
}

/** 今天算哪一季。只用来**挡掉不合季的推荐**（夏天不该让人穿驼大衣），不做别的判断。
 *  6-8 夏 / 12-2 冬 / 其余 春秋 —— 近似的、按月的口径，够用；真按节气算反而要一份节气表。 */
function todaySeason() {
  const m = new Date().getMonth() + 1;
  if (m >= 6 && m <= 8) return "夏";
  if (m === 12 || m <= 2) return "冬";
  return "春秋";
}

/** 这一顿合不合季：天热先挑清爽的，天冷先挑热的。是个**排序偏好**，不是硬筛——
 *  硬筛会把「今晚就想喝汤」的人挡在外面，而菜库本来就只有六十来道。 */
function dishSeasonRank(d) {
  const name = String((d && d.name) || "");
  const s = todaySeason();
  if (s === "夏") return /拌|凉|蒸|白灼|清炒|清蒸|时蔬|黄瓜|丝瓜|冬瓜|番茄|西红柿|蛋/.test(name) ? 0 : 1;
  if (s === "冬") return /汤|炖|煲|焖|红烧|砂锅|羊|萝卜|排骨|鸡/.test(name) ? 0 : 1;
  return /炒|蒸|拌|白切|时蔬|蛋/.test(name) ? 0 : 1;
}

/* ---------- 三个池子：顺序就是「今天应该先想到谁」 ---------- */

/** 衣：当季 + 久未穿/没穿过优先。池子是**排好序**的候选，第一个就是今天的推荐。 */
function todayYiPool() {
  const season = todaySeason();
  let wd = (state.wardrobe || []).slice();
  if (!wd.length) return [];
  let fit = wd;
  try {
    fit = wd.filter((w) => {
      const s = Engine.seasonOf(w);
      return s === "四季" || s === season;
    });
  } catch (_) { fit = wd; }
  // 一件合季的都没有（比如夏天柜里只剩冬装）：退回全柜，但推荐语里会说清是「换季收着的」
  if (!fit.length) fit = wd;
  const now = Date.now();
  const idle = fit.filter((w) => w.worn && w.lastWorn && (now - w.lastWorn) / DAY > 90)
    .sort((a, b) => a.lastWorn - b.lastWorn);
  const never = fit.filter((w) => !w.worn);
  const rest = fit.filter((w) => !idle.includes(w) && !never.includes(w));
  // 常穿的那批也要有一个稳定顺序：同一天里不能因为排序不稳定而换人
  const tail = seededOrder(rest, "yi-rest");
  return [...never, ...idle, ...tail];
}

/** 味：这桌人能吃的（忌口是硬条件）+ 没做过优先 + 当季优先。 */
function todayWeiPool() {
  let all = [];
  try { all = typeof allDishes === "function" ? allDishes() : []; } catch (_) { all = []; }
  if (!all.length) return [];
  const done = new Set((state.cookLog || []).map((c) => c.name));
  const safe = all.filter((d) => {
    try { return typeof dishSafeFor === "function" ? dishSafeFor(d, state.people) : true; } catch (_) { return true; }
  });
  // 一桌人把整本菜库都吃不了：那是「忌口比菜还多」的极端，不许因此让今日空着——
  // 退回整本库，推荐语里会写明这一桌有人不能吃（别让人以为它安全）
  const pool = safe.length ? safe : all;
  const bySeason = (list) => seededOrder(list, "wei-season").sort((a, b) => dishSeasonRank(a) - dishSeasonRank(b));
  const fresh = pool.filter((d) => !done.has(d.name));
  const tried = pool.filter((d) => done.has(d.name));
  return [...bySeason(fresh), ...bySeason(tried)];
}

/** 言：今天到期 > 已经过期 > 还没说清 > 其余没办的。 */
function todayYanPool() {
  const cards = (state.yanCards || []).filter((c) => !c.done);
  if (!cards.length) return [];
  const now = Date.now();
  const endOfToday = new Date(); endOfToday.setHours(23, 59, 59, 999);
  const dueToday = cards.filter((c) => c.when && c.when.at <= endOfToday.getTime() && c.when.at >= now)
    .sort((a, b) => a.when.at - b.when.at);
  const overdue = cards.filter((c) => c.when && c.when.at < now).sort((a, b) => a.when.at - b.when.at);
  const vague = cards.filter((c) => !c.when && c.k === "还没说清");
  const others = cards.filter((c) => !dueToday.includes(c) && !overdue.includes(c) && !vague.includes(c));
  return [...dueToday, ...overdue, ...seededOrder(vague, "yan-vague"), ...seededOrder(others, "yan-rest")];
}

/** 一条候选的身份：只存够认回它的那几个字段，不存整条（存整条就成了第二份数据）。 */
function yanKey(c) { return String((c && c.k) || "") + "\u0001" + String((c && c.line) || ""); }
function yanByKey(key) {
  const [k, line] = String(key || "").split("\u0001");
  return (state.yanCards || []).find((c) => c.k === k && c.line === line) || null;
}

/** 今天的三个选择。**先认回本机记的那一份，认不回来才重挑**——这是「同一天内稳定」的兑现处。 */
function todayPick() {
  const memo = todayMemoLoad();
  const yiPool = todayYiPool(), weiPool = todayWeiPool(), yanPool = todayYanPool();
  const pick = memo ? Object.assign({}, memo.pick) : { yi: "", wei: "", yan: "" };
  let dirty = !memo;
  const yiHit = pick.yi && yiPool.find((w) => w.id === pick.yi);
  if (!yiHit && yiPool.length) { pick.yi = yiPool[0].id; dirty = true; }
  if (!yiPool.length) pick.yi = "";
  const weiHit = pick.wei && weiPool.find((d) => d.name === pick.wei);
  if (!weiHit && weiPool.length) { pick.wei = weiPool[0].name; dirty = true; }
  if (!weiPool.length) pick.wei = "";
  const yanHit = pick.yan && yanByKey(pick.yan);
  if (!yanHit && yanPool.length) { pick.yan = yanKey(yanPool[0]); dirty = true; }
  if (!yanPool.length) pick.yan = "";
  if (dirty) todayMemoSave(pick);
  return { pick, yiPool, weiPool, yanPool };
}

/** 「再抽一笺」：换到池子里的下一件。用户主动要换，才换——刷新不算。 */
function todayNext() {
  const { pick, yiPool, weiPool, yanPool } = todayPick();
  const step = (pool, cur, idOf) => {
    if (!pool.length) return "";
    const at = pool.findIndex((x) => idOf(x) === cur);
    return idOf(pool[(at + 1 + pool.length) % pool.length]);
  };
  pick.yi = step(yiPool, pick.yi, (w) => w.id);
  pick.wei = step(weiPool, pick.wei, (d) => d.name);
  pick.yan = step(yanPool, pick.yan, (c) => yanKey(c));
  todayMemoSave(pick);
}

/* ---------- 今天做过没有：全部从真实数据读，不存「已完成」这个布尔 ---------- */

/** 今天记过穿的那几件（按时间倒序）。data 里本来就有 lastWorn，不必另存一份。 */
function todayWornList() {
  const t = dayStr(Date.now());
  return (state.wardrobe || []).filter((w) => w.lastWorn && dayStr(w.lastWorn) === t)
    .sort((a, b) => b.lastWorn - a.lastWorn);
}
/** 今天记过做的菜（最近一条在前）。 */
function todayCookedList() {
  const t = dayStr(Date.now());
  return (state.cookLog || []).filter((c) => dayStr(c.t) === t).sort((a, b) => b.t - a.t);
}
/** 今天办完的言笺（最近一条在前）。
 *  为什么要翻流水：一条言笺只有 done 这个布尔，没有「哪天勾掉的」——光看它推不出
 *  「今天办完的」，而这一屏要显示的是用户**今天**的成果。所以办完那一下记一笔流水
 *  （那是发生过的实事），这里按流水读回来。要同时满足「账上还勾着」，
 *  因为撤销会把 done 放回去，那时这一行就不该还写着「办完了」。 */
function todayDoneYanList() {
  const t = dayStr(Date.now());
  return (state.log || [])
    // kind 必须是 `done`，不是 `note`：`note` 归摘录（那也是一句「话」，也进 log），
    // 用它当判据的话，同一天你记一句摘录，今日屏就会把那一句当成「办完的言笺」摆出来
    // （实测：addDigest('同一句话') 之后 doneYanList 里多了一条 ref=同一句话）。
    .filter((e) => e.kind === "done" && e.mod === "yan" && e.ref && dayStr(e.t) === t)
    .sort((a, b) => b.t - a.t)
    .map((e) => ({ ref: String(e.ref), at: e.t }))
    // logEvent 把 ref 掐到 40 字，所以这里也按前 40 字比（整行可能更长）
    .filter((x) => (state.yanCards || []).some((c) => c.done && c.line.slice(0, 40) === x.ref));
}

/** 今天的「三件事」。返回 [{ mark, mod, title, sub, done, doneTitle, doneSub, actLabel,
 *  act, go }]，act 是当场做完，go 是跳过去看。永远是三件（不够就用「怎么开始」补）。 */
function todayThree() {
  const { pick, yiPool, weiPool, yanPool } = todayPick();
  const out = [];
  const season = todaySeason();

  /* ---- 衣 ---- */
  try {
    const worn = todayWornList();
    if (worn.length) {
      const w = worn[0];
      out.push({
        mark: "衣", mod: "yi", done: true,
        // title 在「做完了」那几行上也必须给：它是这一行的**一句话本身**
        // （smoke / e2e 读的就是 todayThree() 的 title；空着就是 undefined 进屏）。
        title: `今天穿了「${w.name}」`,
        doneTitle: `今天穿了「${w.name}」`,
        doneSub: w.worn > 1 ? `这是第 ${w.worn} 次，单次成本又降了一点` : "第一笔记上了",
        go: () => { show("yi"); if (typeof selectCloth === "function") selectCloth(w.id); },
      });
    } else if (yiPool.length) {
      const w = yiPool.find((x) => x.id === pick.yi) || yiPool[0];
      const days = w.lastWorn ? Math.floor((Date.now() - w.lastWorn) / DAY) : 0;
      let seasonTag = "";
      try { const s = Engine.seasonOf(w); if (s === season) seasonTag = `当季（${s}）`; } catch (_) { }
      out.push({
        mark: "衣", mod: "yi",
        title: w.worn ? `${w.name} 已经 ${days} 天没穿了` : `${w.name} 还一次没穿过`,
        sub: [seasonTag, w.worn ? "今天穿它，账上就多一次" : "先把它穿一次，再决定留不留"].filter(Boolean).join(" · "),
        actLabel: "今天穿了",
        // 以前只调 wearNow()：它改的是 worn/lastWorn 两个字段，而「记一笔流水 + bumpStreak」
        // 是 afterWearAction() 干的（衣笺屏那五枚签各自在外面包了一层）。今日屏没包，
        // 于是同一件衣服在衣笺屏点会点亮热力图、连续天数 +1，在今日屏点**什么都不记**
        // （实测：衣笺屏 {logWear:1, streakDays:1} / 今日屏 {logWear:0, streakDays:0}）。
        // 同一件事在两张屏上留下两种结果，是那种「用户永远发现不了、但统计全是错的」的错。
        act: () => {
          const before = w.worn || 0;
          try {
            if (typeof wearNow === "function") wearNow(w.id);
            else return false;
            if (typeof afterWearAction === "function") afterWearAction(w, before);
          } catch (e) { console.warn("today wear", e); return false; }
          renderToday(); return true;
        },
        go: () => { show("yi"); if (typeof selectCloth === "function") selectCloth(w.id); },
      });
    }
  } catch (e) { console.warn("today yi", e); }

  /* ---- 味 ---- */
  try {
    const cooked = todayCookedList();
    if (cooked.length) {
      const c = cooked[0];
      const times = (state.cookLog || []).filter((x) => x.name === c.name).length;
      out.push({
        mark: "味", mod: "wei", done: true,
        title: `今天做了「${c.name}」`,
        doneTitle: `今天做了「${c.name}」`,
        doneSub: times > 1 ? `这一道做过 ${times} 次了` : "开火了。这一道记进账上了",
        go: () => { if (typeof openDish === "function") openDish(c.name); else show("wei"); },
      });
    } else if (weiPool.length) {
      const d = weiPool.find((x) => x.name === pick.wei) || weiPool[0];
      const doneSet = new Set((state.cookLog || []).map((c) => c.name));
      const mins = (() => { try { return typeof dishMinutes === "function" ? dishMinutes(d) : 0; } catch (_) { return 0; } })();
      const bans = (() => { try { return typeof dishBansFor === "function" ? dishBansFor(d, state.people) : []; } catch (_) { return []; } })();
      const seasonWord = todaySeason() === "夏" ? "天热，挑的是清爽的"
        : todaySeason() === "冬" ? "天冷，挑的是带热汤的" : "当季";
      out.push({
        mark: "味", mod: "wei",
        title: `今晚可以试试 ${d.name}`,
        sub: [mins ? `约 ${mins} 分钟` : "", doneSet.has(d.name) ? "做过" : "没做过",
          bans.length ? `这桌有人吃不了（${bans.join("、")}）` : seasonWord].filter(Boolean).join(" · "),
        actLabel: "就做这道",
        act: () => { try { todayCookIt(d.name); } catch (e) { console.warn("today cook", e); } },
        go: () => { if (typeof openDish === "function") openDish(d.name); else show("wei"); },
      });
    }
  } catch (e) { console.warn("today wei", e); }

  /* ---- 言 ---- */
  try {
    // 今天在这一屏上办完的那一条：显示成果，不消失（用户需要看见自己的成果）。
    const doneToday = todayDoneYanList();
    // 今天办完的是哪一条：按日志里那前 40 字认回整行（logEvent 的 ref 就是这么掐的）
    const doneCard = doneToday.length
      ? (state.yanCards || []).find((c) => c.done && c.line.slice(0, 40) === doneToday[0].ref)
      : null;
    const card = pick.yan ? yanByKey(pick.yan) : null;
    const live = card && !card.done ? card : (yanPool.length ? yanPool[0] : null);
    if (doneCard) {
      const more = doneToday.length - 1;
      out.push({
        mark: "言", mod: "yan", done: true,
        title: `办完了：「${doneCard.line}」`,
        doneTitle: `办完了：「${doneCard.line}」`,
        doneSub: more > 0 ? `今天一共办完 ${doneToday.length} 件了` : "勾掉了。今天少一件压在心上的事",
        go: () => { show("yan"); if (typeof focusYanCard === "function") focusYanCard(doneCard); },
      });
    } else if (live) {
      const late = live.when && live.when.at < Date.now();
      const dueToday = live.when && !late && dayStr(live.when.at) === dayStr(Date.now());
      out.push({
        mark: "言", mod: "yan",
        title: `「${live.line}」${late ? "已经到期了" : dueToday ? "今天到期" : live.k === "还没说清" ? "还没说清怎么办" : "还没办"}`,
        sub: late ? "过期的事最占脑子，办掉或明确不做"
          : dueToday ? "今天这一件，顺手就了了"
            : live.k === "还没说清" ? "一句话的事：定个时间，或者干脆放下"
              : "勾掉它，今天就少一件压在心上的",
        actLabel: "办完了",
        act: () => { try { todayDoneYan(live); } catch (e) { console.warn("today yan", e); } },
        go: () => { show("yan"); if (typeof focusYanCard === "function") focusYanCard(live); },
      });
    }
  } catch (e) { console.warn("today yan", e); }

  /* ---- 都不够三件时：用「开始」三件事补上，绝不摆「暂无数据」 ---- */
  const empty = [
    { mark: "衣", mod: "yi", title: "过第一张笺", sub: "拍一件想买的衣服，问柜子该不该买", start: true,
      go: () => { show("yi"); if (typeof openPhoto === "function") openPhoto(); } },
    { mark: "味", mod: "wei", title: "排第一桌", sub: "把今晚的菜单贴进来，看谁吃不了哪道", start: true,
      go: () => { show("wei"); if (typeof setWeiTab === "function") setWeiTab("plan"); } },
    { mark: "言", mod: "yan", title: "捞第一张笺", sub: "把一段聊天贴进来，落成待办和要买", start: true,
      go: () => { show("yan"); } },
  ];
  for (const e of empty) { if (out.length >= 3) break; if (!out.some((x) => x.mod === e.mod)) out.push(e); }
  return out.slice(0, 3);
}

/** 当场做完：记一笔「今天做了这道」。与菜谱页那枚「今天做了这道」同一个账法
 *  （cookbook.js renderWeiDish 里那一段），所以两处记出来的数据长得一样。 */
function todayCookIt(name) {
  const n = String(name || "").trim();
  if (!n) return;
  const already = todayCookedList().some((c) => c.name === n);
  if (already) { toast(`今天已经记过「${n}」了，同一天不记两遍`); return; }
  state.cookLog.push({ id: "c" + newId().slice(1), name: n, t: Date.now(), stars: 0,
    note: "", people: (state.people || []).length });
  save(state);
  try { logEvent("cook", "wei", n); } catch (e) { console.warn("today cook log", e); }
  try { haptic("MEDIUM"); } catch (_) { }
  renderToday();
  toast(`记下了：今天做了「${n}」`);
}

/** 当场做完：勾掉今天这一条言笺。撤销按原状态放回（这条没有下标问题，是同一个对象）。 */
function todayDoneYan(card) {
  if (!card || card.done) { toast("这一条已经办完了"); return; }
  card.done = true;
  save(state);
  // 记一笔流水：这一屏要显示「今天办完了什么」，而言笺条目本身只有一个 done 布尔，
  // 看不出是哪天勾的。流水记的是发生过的实事（不是派生数），所以它进 log 是对的。
  // kind 用 `done` 不用 `note`：`note` 是摘录（remind.js 的 addDigest 也在写它）。
  try { logEvent("done", "yan", card.line.slice(0, 40), 1); } catch (e) { console.warn("today done", e); }
  try { haptic("MEDIUM"); } catch (_) { }
  renderToday();
  toastUndo(`办完了：「${String(card.line).slice(0, 16)}」`, () => {
    card.done = false;
    // 撤销要把那一笔流水也一起收回：留着它，今日那一屏会继续写着「办完了」
    // 只删 `done` 这一种：以前这里按 `note` 删，同一天记过一句摘录的话，
    // 那一句的流水会被这条撤销顺手抹掉（and 出来的结果是「摘录没了、摘录本里还在」）。
    state.log = (state.log || []).filter((e) =>
      !(e.kind === "done" && e.mod === "yan" && e.ref === card.line.slice(0, 40) && dayStr(e.t) === dayStr(Date.now())));
    save(state);
    renderToday();
    toast("又放回没办里了");
  });
}

/* ==================== 连续天数 ====================
   不惩罚、不归零喊话。断签只有一句「从今天重新算」，外加**一次**「补记昨天」——
   那一次只在「正好漏了昨天」时给：漏一天补得上，漏三天补了也是假的。 */
function todayBackfillAvailable() {
  const st = state.streak || {};
  const today = dayStr(Date.now());
  const y = dayStr(Date.now() - DAY);
  const before = dayStr(Date.now() - 2 * DAY);
  return !!st.last && st.last !== today && st.last === before && (st.days || 0) > 0;
}

/** 补记昨天：把昨天记成一笔「打开过」的流水，连续天数接着算。
 *  这是一次**用户自己确认**的补记（不是悄悄改数字）：撤销就在提示里。 */
function todayBackfill() {
  const st = state.streak;
  if (!todayBackfillAvailable()) { toast("今天这一笔已经记上了，不用补"); return; }
  const before = { last: st.last, days: st.days, best: st.best, logLen: (state.log || []).length };
  const y = new Date(Date.now() - DAY);
  y.setHours(20, 0, 0, 0);
  state.log.push({ t: y.getTime(), kind: "visit", mod: "me", ref: "补记", v: 1 });
  state.log.sort((a, b) => a.t - b.t);
  if (state.log.length > LOG_CAP) state.log = state.log.slice(-LOG_CAP);
  st.last = dayStr(Date.now() - DAY);
  st.days = (st.days || 0) + 1;
  if (st.days > (st.best || 0)) st.best = st.days;
  save(state);
  renderToday();
  toastUndo(`把昨天补上了 · 现在是连续第 ${st.days} 天`, () => {
    st.last = before.last; st.days = before.days; st.best = before.best;
    state.log = state.log.filter((e) => !(e.kind === "visit" && e.ref === "补记" && dayStr(e.t) === dayStr(y.getTime())));
    save(state);
    renderToday();
  });
}

/* ==================== 往年今日 ==================== */
/** 去年（或更早）的今天，你在这里做过什么。用本地日期按「月.日」跨年匹配。
 *  返回 { year, events, digest } 或 null。没有就整块不摆——摆一个空标题比不摆更糟。 */
function todayPastOfYear() {
  const now = new Date();
  const md = dayStr(Date.now()).slice(5);           // "10.18"
  const year = String(now.getFullYear());
  const byYear = {};
  (state.log || []).forEach((e) => {
    const k = dayStr(e.t);
    if (k.slice(5) !== md) return;
    const y = k.slice(0, 4);
    if (y === year) return;
    (byYear[y] = byYear[y] || []).push(e);
  });
  const digs = (state.digest || []).filter((d) => {
    const k = dayStr(d.t);
    return k.slice(5) === md && k.slice(0, 4) !== year;
  });
  const years = Object.keys(byYear).concat(digs.map((d) => dayStr(d.t).slice(0, 4)))
    .filter((v, i, a) => a.indexOf(v) === i).sort();
  if (!years.length) return null;
  const y = years[years.length - 1];
  return { year: y, events: byYear[y] || [], digest: digs.filter((d) => dayStr(d.t).slice(0, 4) === y) };
}

/* ==================== 那一屏 ==================== */

/** 个人档案那一小块（点它进「册」）。今天这一屏不该是匿名的：一张纸上先得有个人。 */
function renderTodayMe() {
  const host = $("#todayStreak");
  if (!host) return;
  let el = $("#todayMe");
  if (!el) {
    el = document.createElement("button");
    el.type = "button";
    el.id = "todayMe";
    el.className = "today-me";
    host.parentNode.insertBefore(el, host);
  }
  const pf = state.profile || {};
  const nick = String(pf.nick || "").trim();
  const line = String(pf.line || "").trim();
  const since = pf.since ? dayStr(pf.since) : "";
  const days = (() => { try { return activeDays().length; } catch (_) { return 0; } })();
  el.innerHTML = `
    <span class="tm-seal seal-mark" aria-hidden="true">己</span>
    <span class="tm-main">
      <b class="serif">${esc(nick || "给自己起个称呼")}</b>
      <span>${esc(line || "一句话说说你")}</span>
    </span>
    <span class="tm-meta">${since ? `自 ${since}` : ""}<b>${days} 天</b></span>`;
  el.setAttribute("aria-label", `我的档案：${nick || "还没起名字"}，${days} 天有记录，点开去「册」`);
  el.onclick = () => show("me");
}

/** 连续天数那一枚章 + 断签时那一次「补记昨天」。0 天不摆死板的「0」，
 *  新装第一天就写一句「今天做一件小事，就算开始」。 */
function renderTodayStreak() {
  const sk = $("#todayStreak");
  if (!sk) return;
  const st = state.streak || {};
  const days = st.days || 0;
  const today = dayStr(Date.now());
  if (days <= 0) {
    sk.innerHTML = `<span class="tiny">今天做一件小事，就算开始。</span>`;
    return;
  }
  const alive = st.last === today || st.last === dayStr(Date.now() - DAY);
  const tail = st.last === today
    ? `今天已经记上了。最长 ${st.best || days} 天。`
    : st.last === dayStr(Date.now() - DAY)
      ? `昨天也在。今天做一件小事就续上第 ${days + 1} 天。`
      : todayBackfillAvailable()
        ? "昨天断了。补上那一次，这笔账就还是连着的。"
        : `断了就从今天重新算，不计前账。最长 ${st.best || days} 天。`;
  sk.innerHTML = `<span class="sk-mark" aria-label="连续 ${days} 天"><b>${days}</b><i>天</i></span>
    <span class="tiny">${tail}</span>` +
    (todayBackfillAvailable() ? `<button type="button" class="chip sk-backfill" id="streakBack">补记昨天</button>` : "");
  const b = $("#streakBack");
  if (b) b.onclick = () => todayBackfill();
  sk.setAttribute("data-alive", alive ? "1" : "0");
}

/** 今天的三件事。每一行 = 一个可以做／做过的动作，不是三枚跳转链接。 */
function renderTodaySheet() {
  const sheet = $("#todaySheet");
  if (!sheet) return;
  const three = todayThree();
  sheet.innerHTML = three.map((t, i) => {
    const no = ["一", "二", "三"][i];
    if (t.done) {
      return `<div class="tj-item tj-done" data-today="${i}">
        <span class="tj-no" aria-hidden="true">${no}</span>
        <div class="tj-main"><b>✓ ${esc(t.doneTitle)}</b><span>${esc(t.doneSub || "")}</span></div>
        <div class="tj-acts"><button type="button" class="chip tj-go" data-today-go="${i}">去看看</button></div>
      </div>`;
    }
    return `<div class="tj-item" data-today="${i}">
      <span class="tj-no" aria-hidden="true">${no}</span>
      <div class="tj-main"><b>${esc(t.title)}</b><span>${esc(t.sub || "")}</span></div>
      <div class="tj-acts">
        ${t.act ? `<button type="button" class="btn seal tj-do" data-today-do="${i}">${esc(t.actLabel)}</button>` : ""}
        <button type="button" class="chip tj-go" data-today-go="${i}">${t.start ? "去开始" : "去" + t.mark + "笺"}</button>
      </div>
    </div>`;
  }).join("");
  $$("#todaySheet [data-today-do]").forEach((b) => {
    b.onclick = () => {
      const t = three[Number(b.dataset.todayDo)];
      if (t && typeof t.act === "function") t.act();
    };
  });
  $$("#todaySheet [data-today-go]").forEach((b) => {
    b.onclick = () => {
      const t = three[Number(b.dataset.todayGo)];
      if (t && typeof t.go === "function") t.go();
    };
  });
}

/** 往年今日。今年这一次不许混进来（那是「今天」，不是「往年」）。 */
function renderTodayPast() {
  const past = $("#todayPast");
  if (!past) return;
  const label = past.previousElementSibling;        // 静态 HTML 里那一行「往年今日」
  const hit = todayPastOfYear();
  if (!hit) {
    past.hidden = true;
    if (label && label.classList.contains("tiny")) label.hidden = true;
    return;
  }
  const kinds = countByKind(hit.events);
  const bits = Object.keys(kinds).map((k) => `${KIND_NAME[k] || k} ${kinds[k]}`);
  const quotes = hit.digest.slice(-1).map((d) => String(d.text || "").trim()).filter(Boolean);
  past.hidden = false;
  if (label && label.classList.contains("tiny")) label.hidden = false;
  past.innerHTML = `<p class="past-year">${hit.year} 年的这一天，你在这里` +
    (bits.length ? `留了 <b>${hit.events.length}</b> 笔：${esc(bits.join("、"))}。` : "打开过一次。") +
    `</p>` +
    (quotes.length ? `<p class="past-year past-quote serif">那天记下的一句：「${esc(quotes[0].slice(0, 40))}」</p>` : "");
}

/** 今日那一屏。刷新时不重建整片 DOM 之外的东西（连续天数、往年今日、统计格各自算）。 */
function renderToday() {
  const d = new Date();
  const wd = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  const dateEl = $("#todayDate");
  if (dateEl) dateEl.textContent = `${d.getMonth() + 1} 月 ${d.getDate()} 日 · 周${wd}`;
  const titleEl = $("#todayTitle");
  if (titleEl) {
    const h = d.getHours();
    titleEl.textContent = h < 5 ? "还醒着" : h < 11 ? "早上好" : h < 14 ? "中午好" : h < 18 ? "下午好" : h < 23 ? "晚上好" : "夜深了";
  }

  try { renderTodayMe(); } catch (e) { console.warn("today me", e); }
  try { renderTodayStreak(); } catch (e) { console.warn("today streak", e); }
  try { renderTodaySheet(); } catch (e) { console.warn("today sheet", e); }
  try { renderTodayPast(); } catch (e) { console.warn("today past", e); }

  /* 四个统计格：永远有数（新用户也会显示 0，但下面那行说的是「还没有」而不是「0」） */
  const stats = $("#todayStats");
  if (stats) {
    const wd2 = (state.wardrobe || []).length;
    const yc = (state.yanCards || []).filter((c) => !c.done).length;
    const cook = new Set((state.cookLog || []).map((c) => c.name)).size;
    const days = (() => { try { return activeDays().length; } catch (_) { return 0; } })();
    stats.innerHTML = [
      { n: wd2, u: "件", l: "柜里" },
      { n: cook, u: "道", l: "做过的菜" },
      { n: yc, u: "条", l: "还没办的" },
      { n: days, u: "天", l: "有记录" },
    ].map((s) => `<div class="stat"><b>${s.n}<small>${s.u}</small></b><span>${s.l}</span></div>`).join("");
  }

  /* 底部三个入口：不占底栏，但每天都能看见 */
  const links = $("#todayLinks");
  if (links) {
    const badgeN = (state.badges || []).length;
    links.innerHTML = `
      <button class="rowbtn" data-tolink="pu"><span class="grow"><b>笺谱</b><span class="sub">热力图 · 统计 · 这一年的账</span></span></button>
      <button class="rowbtn" data-tolink="badges"><span class="grow"><b>章</b><span class="sub">已攒 ${badgeN} 枚</span></span></button>
      <button class="rowbtn" data-tolink="search"><span class="grow"><b>找东西</b><span class="sub">一次搜遍全部</span></span></button>`;
    $$("#todayLinks [data-tolink]").forEach((b) => { b.onclick = () => show(b.dataset.tolink); });
  }

  bindTodayOnce();
  paintNavBadges();
}

/** 「再抽一笺」这一枚的归属。
 *  为什么要在捕获阶段接：app.js 的 boot() 里也给它绑过一次（那句老的
 *  `renderToday(); toast("换了一笺")`）——而三件事是按天定的，所以那一下**其实什么都没换**，
 *  是一枚按了没反应的签。那一份绑定在 boot 里、晚于本文件第一次渲染，抢不过来；
 *  而 show() 每次都会重跑 renderToday()，谁也说不准哪一份是最后一份。
 *  所以这里用捕获阶段（祖先先于目标收到事件）把这一下**接住并掐断**，
 *  不让那枚签再同时跑两遍。只挂一次，之后每次渲染都不重绑（重绑会叠出多份）。 */
let todayBound = false;
function bindTodayOnce() {
  if (todayBound) return;
  const scr = $("#today");
  if (!scr) return;
  todayBound = true;
  scr.addEventListener("click", (e) => {
    const t = e.target;
    if (!t || !t.closest || !t.closest("#todayJian")) return;
    e.preventDefault();
    e.stopPropagation();
    todayNext();
    renderToday();
    toast("换了一笺");
    try { haptic("LIGHT"); } catch (_) { }
  }, true);
}

/** kind 的中文名。统计页、往年今日、年度总结都印它，所以只能有一份。
 *  必须与 state.js 的 LOG_KINDS 一一对应（多一个少一个都是「某一类事在统计里没有名字」）。 */
const KIND_NAME = {
  wear: "穿", cook: "做菜", catch: "捞笺", slip: "存笺", badge: "得章",
  visit: "打开", buy: "买", plan: "排桌", note: "摘录", wish: "愿望",
  market: "买菜", recipe: "录菜谱", outfit: "搭配", reminder: "提醒",
  // 「办完一条言笺」与「记一句摘录」以前共用 note，热力图那天写着「摘录 · 把报销单交了」，
  // 年度总结也把两件事算成一件。0.6.0 起分开。
  done: "办完",
};
