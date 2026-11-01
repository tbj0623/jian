/** 笺 · 成就
 *
 *  徽章不是积分。每一枚都必须对应**一件真的发生过的事**，而且解锁那一刻不弹窗、
 *  不打断——只在「今日」那一屏的章数上 +1，用户自己去发现。
 *  （弹窗式成就系统会让「静」这个品牌当场破功。）
 *
 *  定义分两种：
 *  - **计数型**：某个集合到了多少（做过 10 道菜）
 *  - **事件型**：某件特定的事发生过（第一次在报告页记进柜子）
 *  两者都从 state 现算，不存「当前进度」——进度一旦落盘，删掉数据之后它就成假话。
 *
 *  mark 是那枚章上的字，只能一个字（章面就这么大）。
 *
 *  ==================== 进度（v0.6.0 补） ====================
 *  每一枚都必须能算出「还差几次」。原来只有 {ok}，于是没解锁的章点开只有一句
 *  「还没解锁」——那是把一个可玩机制做成了一堵墙。现在：
 *
 *    progress: { now, need }  now = 现在到哪儿了，need = 到哪儿就解锁
 *    hint: '还差 3 次' / '还差 2 件' / '已经攒够了，马上就会亮'
 *
 *  三条硬规矩（和热力图、统计同一套口径）：
 *  1. **now 一律现算**，不落盘。删掉一条记录之后「还差 1 次」必须当场变回「还差 2 次」。
 *  2. **now 不许超过 need**：到了就解锁了，屏上不该出现「已经 12 / 10」这种自相矛盾。
 *  3. **量词要对**：次数说「次」，件数说「件」，天数说「天」。中文里量词错了，
 *     整句话就不像人写的。
 *
 *  还有一种「事件型」章（第一次过笺、导出过备份）算不出进度条——它的 hint 说明
 *  「怎么才算做到」，need 给 1、now 给 0，不假装有百分比。
 */
const BADGE_DEFS = [
  /* ---- 开始用 ---- */
  { id: "first-wear", mark: "初", name: "第一件", how: "记第一次「今天穿了」", group: "衣", unit: "次",
    test: () => (state.log || []).some((e) => e.kind === "wear"),
    count: () => (state.log || []).filter((e) => e.kind === "wear").length, need: 1 },
  { id: "first-slip", mark: "笺", name: "第一张笺", how: "完成第一次过笺", group: "衣", unit: "张",
    test: () => (state.album || []).length > 0,
    count: () => (state.album || []).length, need: 1 },
  { id: "first-table", mark: "桌", name: "第一桌", how: "排第一次桌", group: "味", unit: "桌",
    test: () => (state.weiHist || []).length > 0,
    count: () => (state.weiHist || []).length, need: 1 },
  { id: "first-catch", mark: "捞", name: "第一捞", how: "第一次从聊天里捞成笺", group: "言", unit: "条",
    test: () => (state.yanCards || []).length > 0,
    count: () => (state.yanCards || []).length, need: 1 },
  { id: "first-cook", mark: "灶", name: "开火", how: "记第一次「今天做了这道」", group: "味", unit: "次",
    test: () => (state.cookLog || []).length > 0,
    count: () => (state.cookLog || []).length, need: 1 },

  /* ---- 衣 ---- */
  { id: "closet-10", mark: "十", name: "十件", how: "柜里攒到 10 件", group: "衣", unit: "件",
    test: () => (state.wardrobe || []).length >= 10,
    count: () => (state.wardrobe || []).length, need: 10 },
  { id: "closet-30", mark: "卅", name: "卅件", how: "柜里攒到 30 件", group: "衣", unit: "件",
    test: () => (state.wardrobe || []).length >= 30,
    count: () => (state.wardrobe || []).length, need: 30 },
  { id: "wear-50", mark: "穿", name: "穿过五十次", how: "累计记 50 次「今天穿了」", group: "衣", unit: "次",
    test: () => (state.log || []).filter((e) => e.kind === "wear").length >= 50,
    count: () => (state.log || []).filter((e) => e.kind === "wear").length, need: 50 },
  { id: "wear-200", mark: "百", name: "穿过两百次", how: "累计记 200 次穿着", group: "衣", unit: "次",
    test: () => (state.log || []).filter((e) => e.kind === "wear").length >= 200,
    count: () => (state.log || []).filter((e) => e.kind === "wear").length, need: 200 },
  { id: "cpw-low", mark: "值", name: "穿回本了", how: "有一件衣服的单次成本降到 ¥5 以下", group: "衣", unit: "件",
    test: () => (state.wardrobe || []).some((w) => w.price !== null && w.price !== undefined && w.worn > 0 && w.price / w.worn < 5),
    count: () => (state.wardrobe || []).filter((w) => w.price !== null && w.price !== undefined && w.worn > 0 && w.price / w.worn < 5).length, need: 1 },
  { id: "outfit-5", mark: "搭", name: "五套搭配", how: "搭配册存到 5 套", group: "衣", unit: "套",
    test: () => (state.outfits || []).length >= 5,
    count: () => (state.outfits || []).length, need: 5 },
  { id: "wish-drop", mark: "省", name: "忍住", how: "在愿望单里决定「不买了」3 次", group: "衣", unit: "次",
    test: () => (state.wish || []).filter((w) => w.done && !w.bought).length >= 3,
    count: () => (state.wish || []).filter((w) => w.done && !w.bought).length, need: 3 },

  /* ---- 味 ---- */
  { id: "cook-10", mark: "十", name: "十道菜", how: "做过 10 道不同的菜", group: "味", unit: "道",
    test: () => new Set((state.cookLog || []).map((c) => c.name)).size >= 10,
    count: () => new Set((state.cookLog || []).map((c) => c.name)).size, need: 10 },
  { id: "cook-30", mark: "卅", name: "卅道菜", how: "做过 30 道不同的菜", group: "味", unit: "道",
    test: () => new Set((state.cookLog || []).map((c) => c.name)).size >= 30,
    count: () => new Set((state.cookLog || []).map((c) => c.name)).size, need: 30 },
  { id: "table-10", mark: "宴", name: "十桌", how: "排过 10 桌", group: "味", unit: "桌",
    test: () => (state.log || []).filter((e) => e.kind === "plan").length >= 10,
    count: () => (state.log || []).filter((e) => e.kind === "plan").length, need: 10 },
  { id: "recipe-5", mark: "谱", name: "五张菜谱", how: "自己写了 5 张菜谱", group: "味", unit: "张",
    test: () => (state.recipes || []).length >= 5,
    count: () => (state.recipes || []).length, need: 5 },
  { id: "market-20", mark: "篮", name: "二十样", how: "买菜清单累计勾掉 20 样", group: "味", unit: "样",
    test: () => (state.log || []).filter((e) => e.kind === "market").length >= 20,
    count: () => (state.log || []).filter((e) => e.kind === "market").length, need: 20 },

  /* ---- 言 ---- */
  { id: "yan-50", mark: "言", name: "五十条", how: "言笺累计捞到 50 条", group: "言", unit: "条",
    test: () => (state.yanCards || []).length >= 50,
    count: () => (state.yanCards || []).length, need: 50 },
  { id: "done-50", mark: "办", name: "办完五十", how: "累计办完 50 条", group: "言", unit: "条",
    // 两条路都算「办完」：流水里带 ref 的 note（勾一条记一笔），或言笺里勾着的那些。
    // 这两条在同一个 collection 里其实是同一件事的两种记账法，取较大的那个，
    // 免得同一件事被数两遍（原来的 OR 已经这么写了，这里只是把它挪进 count 里对齐）。
    test: () => (state.log || []).filter((e) => e.kind === "note" && e.ref && e.ref.length > 0).length >= 50
      || (state.yanCards || []).filter((c) => c.done).length >= 50,
    count: () => Math.max(
      (state.log || []).filter((e) => e.kind === "note" && e.ref && e.ref.length > 0).length,
      (state.yanCards || []).filter((c) => c.done).length), need: 50 },
  { id: "remind-10", mark: "铃", name: "十个提醒", how: "定过 10 条提醒", group: "言", unit: "条",
    test: () => (state.log || []).filter((e) => e.kind === "reminder").length >= 10,
    count: () => (state.log || []).filter((e) => e.kind === "reminder").length, need: 10 },
  { id: "digest-7", mark: "句", name: "七句摘录", how: "攒了 7 天摘录", group: "言", unit: "句",
    test: () => (state.digest || []).length >= 7,
    count: () => (state.digest || []).length, need: 7 },
  { id: "digest-30", mark: "章", name: "卅句", how: "攒了 30 天摘录", group: "言", unit: "句",
    test: () => (state.digest || []).length >= 30,
    count: () => (state.digest || []).length, need: 30 },

  /* ---- 回来 ---- */
  { id: "streak-3", mark: "三", name: "三天不断", how: "连续三天有记录", group: "时", unit: "天",
    test: () => (state.streak.best || 0) >= 3,
    count: () => state.streak.best || 0, need: 3 },
  { id: "streak-7", mark: "七", name: "一周不断", how: "连续七天有记录", group: "时", unit: "天",
    test: () => (state.streak.best || 0) >= 7,
    count: () => state.streak.best || 0, need: 7 },
  { id: "streak-30", mark: "月", name: "一个月不断", how: "连续三十天有记录", group: "时", unit: "天",
    test: () => (state.streak.best || 0) >= 30,
    count: () => state.streak.best || 0, need: 30 },
  { id: "days-30", mark: "积", name: "攒了三十天", how: "累计 30 天有记录", group: "时", unit: "天",
    test: () => activeDays().length >= 30,
    count: () => activeDays().length, need: 30 },
  { id: "days-100", mark: "久", name: "攒了一百天", how: "累计 100 天有记录", group: "时", unit: "天",
    test: () => activeDays().length >= 100,
    count: () => activeDays().length, need: 100 },
  { id: "all-three", mark: "全", name: "三笺都用过", how: "衣、味、言各做过至少一件事", group: "时", unit: "笺",
    test: () => ["yi", "wei", "yan"].every((m) => (state.log || []).some((e) => e.mod === m)),
    count: () => ["yi", "wei", "yan"].filter((m) => (state.log || []).some((e) => e.mod === m)).length, need: 3 },
  { id: "year-1", mark: "年", name: "满一年", how: "从开始用笺满一年", group: "时", unit: "天",
    test: () => Date.now() - (state.profile.since || Date.now()) > 365 * 86400000,
    // 满一年是 365 天。用「已经过了多少天」算，进度条才有意义（不是 0/1 的假比例）。
    count: () => Math.min(365, Math.floor((Date.now() - (state.profile.since || Date.now())) / 86400000)),
    need: 365, unit: "天" },
  { id: "backup", mark: "存", name: "留了备份", how: "导出过一次备份", group: "时", unit: "次",
    test: () => (state.log || []).some((e) => e.kind === "slip" && e.ref === "backup"),
    count: () => (state.log || []).some((e) => e.kind === "slip" && e.ref === "backup") ? 1 : 0, need: 1 },
];

/** 分组顺序：衣 → 味 → 言 → 时。成就页按这个顺序分段，不在别处再写一份。 */
const BADGE_GROUPS = ["衣", "味", "言", "时"];

/** 全部徽章（定义）。定义表本身是只读的，别在这里就地改（每次读都要拿到同一份）。 */
function BADGES() { return BADGE_DEFS; }

/** 一枚章的进度。
 *
 *  返回 { ok, now, need, hint, unit, pct }：
 *  - ok   ：现在解锁了没有（**唯一判据**，与 checkBadges 用的是同一个 test）
 *  - now  ：现在到哪儿了。**一律现算**，且钳到不超过 need（到了就该解锁了，
 *           屏上不该出现「12 / 10」）。算不出来的那种事件型，给 0。
 *  - need ：到哪儿就解锁
 *  - hint ：给屏上一句话。形如「还差 3 次」「已经攒够了，马上就会亮」
 *  - pct  ：进度条宽度（0-100 的整数）。need 为 0 时给 0，不出 NaN。
 *
 *  test 可能会抛（state 被导入的脏备份改坏时）。抛了就当「没解锁」，绝不让
 *  一枚章把整个成就页拖垮——这是成就页，不是判定页。 */
function badgeProgress(b) {
  const need = Math.max(0, Number(b && b.need) || 0);
  const unit = (b && b.unit) || "次";
  let ok = false;
  try { ok = !!(b && typeof b.test === "function" && b.test()); } catch (_) { ok = false; }
  let raw = 0;
  if (b && typeof b.count === "function") {
    try { raw = Number(b.count()); } catch (_) { raw = 0; }
    if (!Number.isFinite(raw) || raw < 0) raw = 0;
  }
  // 钳到 need：到了就是解锁了，不该在屏上留下「12 / 10」这种自相矛盾
  const now = need ? Math.floor(Math.min(raw, need)) : 0;
  let hint;
  if (ok) hint = "已经做到了";
  else if (!need) hint = b && b.how ? b.how : "还没开始";
  else if (now >= need) hint = "已经攒够了，马上就会亮";     // test 还没过的极少数边界
  else hint = `还差 ${need - now} ${unit}`;
  const pct = need > 0 ? Math.max(0, Math.min(100, Math.round((now / need) * 100))) : 0;
  return { ok, now, need, hint, unit, pct };
}

/** 检查一遍新解锁的章。**不弹窗**，只在「今日」那一屏的章数上体现出来。
 *  每个动作之后调一次（logEvent 里已经挂了一处）——它自己判断有没有新的，
 *  没新的什么都不做。返回值是新解锁的那几枚（测试与「今日」那一屏用）。 */
function checkBadges() {
  const got = new Set((state.badges || []).map((b) => b.id));
  const fresh = [];
  BADGE_DEFS.forEach((b) => {
    if (got.has(b.id)) return;
    let ok = false;
    try { ok = !!b.test(); } catch (_) { ok = false; }
    if (!ok) return;
    state.badges.push({ id: b.id, t: Date.now() });
    fresh.push(b);
  });
  if (fresh.length) {
    if (state.badges.length > BADGE_CAP) state.badges = state.badges.slice(-BADGE_CAP);
    saveSoon();
    // 触感代替弹窗：一枚章落下的手感，看得见的是屏上那个数字 +1
    haptic("LIGHT");
  }
  return fresh;
}
