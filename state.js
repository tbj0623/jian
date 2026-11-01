/** 笺 · 状态与存储
   localStorage 是唯一的数据源；导入备份和 Preferences 恢复回来的数据都从这里收口。
   必须在其它所有前端脚本之前加载：state / busy 是全局的，钱包也在这份里。
   传统 <script>，不用 ES module——file:// 双击 index.html 要能跑。 */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const KEY = "jian.v1";
/** 日历日的唯一口径（YYYY.MM.DD）。**必须在 state.js 里**：<script> 顺序是 state 先于 ui，
    而下面的连续天数 / 热力图 / 穿着日历都在 parse 期之后立刻要用它；放进 ui.js 会变成
    dayStr is not defined（这个仓踩过一次同类：cssColor 被挪进 ui.js，白屏）。
    ui.js 里那份是同一个函数的另一份拷贝——两处必须逐字一致，consistency 会盯。 */
function dayStr(ts) {
  const d = new Date(ts);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}
const SCHEMA = 3;          // 结构版本，改数据结构时 +1 并在 migrate 里补一段
/** 真正动手的那道线：到这字节数就先丢照片，不等 localStorage 那堵 5MB 的墙
 *  （撞墙时写盘直接抛，那时候连「丢掉了几件」都来不及说）。以前 2800000 是个裸数字，
 *  而「我的」上那个百分比分母另外写着一个 5MB——同一件事两个口径，于是 53% 就开始丢照片，
 *  屏上却还写着「已用 56%，宽裕」。现在裁剪读它，百分比也读它。 */
const SHED_AT = 2800000;
/** 言笺的上限。lossMsg 那句「只留最新 N 条」和 trimStore 的切片必须读同一个数。 */
const YAN_CAP = 200;

const CATS = ["上衣", "裤装", "裙装", "外套", "鞋", "包"];
/* 忌口芯片。前十一项是 0.6.0 的老清单，后四项（蛋 / 小麦 / 大豆 / 坚果）是 2026-10 补的。
 *
 *  为什么补：这四类在引擎的词表里根本没有条目，于是**判定退化成按字面匹配**，
 *  而菜名里不会写「小麦」两个字。实测（`Engine.dishBans`，63 道菜）：
 *    小麦  应判 9 道（葱油拌面 / 阳春面 / 手抓饼 / 玉米烙 / 南瓜饼 / 猪肉白菜饺子 /
 *                  小笼包 / 刀削面 / 牛肉面）→ 实际判出 **0 道**
 *    大豆  应判 3 道（麻婆豆腐 / 海带豆腐汤 / 鲫鱼豆腐汤）→ 实际判出 **0 道**
 *  后果不是「少提醒一句」，是**排桌页会告诉一个对小麦过敏的人「小笼包 · 全员安全」**。
 *  这是这个 App 唯一一处可能把人吃坏的地方，按 README 的规矩，它比任何锦上添花都优先。
 *
 *  两条不能动的约束：
 *  1. **只能往末尾追加。** CHIP_MAP 的键序被 chipsInNotes（引擎）与 Python 的 dict 序
 *     同时依赖（engine.js:761 的注释写死了这条），插在中间会让两端漂。
 *  2. **加一项就要在 engine.js 与 backend/gateway.py 的 CHIP_MAP 里同时加一行**，
 *     并跑 `npm test` 的 consistency——两端判定口径漂了，那道门会先炸。
 *
 *  「坚果」不再挂在花生底下：对花生过敏和对坚果过敏是两件事，而花生严格说不是坚果。
 *  老数据里挂「花生」的人不会自动多出「坚果」，那是他们的选择，不由我们替他们改。 */
const CHIPS = ["辣", "香菜", "海鲜", "花生", "猪肉", "牛羊肉", "内脏", "蒜", "酒", "乳", "清淡",
  "蛋", "小麦", "大豆", "坚果"];
const SEASON_OPTS = ["夏", "春秋", "冬", "四季"];   // 与 Engine.seasonOf 的值域一致
/** 单品的场合。第一个「日常」是默认口径；空数组表示「没标场合」，不默认成日常。 */
const OCCASIONS = ["日常", "通勤", "约会", "运动", "正式", "居家", "旅行"];
/** 言笺的四类。与 engine.js 的 out、gateway.py 的 out 同名同序；
 *  这份必须在 state.js 里——normalizeState 在解析期就跑，那时 yan.js 还没加载。 */
const YAN_KINDS = ["待办", "要买", "已定", "还没说清"];
const ALBUM_TYPES = ["yi", "wei", "yan"];
/** 网关地址：scheme 之后允许多少字。开机钳位与「保存接口」那一枚都读 normApi，
 *  这条线只能有一个地方说得出（以前是 state.js 里一条裸正则，保存那头一个字不问）。 */
const API_MAX = 200;
/** 排过的桌最多记几桌。一签实测 155px，360 的纸上一行只放得下一枚：4 桌是四行 188px，
 *  再多就成了把「排这桌」推出屏幕的签墙。真要往前翻，笺册里每一桌都存着整张笺。 */
const WEI_HIST = 4;

/* ==================== v0.6.0 新增的上限 ====================
   每一个集合都必须有上限，且必须记进 trimStore 的 trimLoss——「丢了几件」说不出来，
   屏幕上就会凭空少东西，而用户没删过。 */
const WISH_CAP = 24;          // 愿望单（想买还没买的）
const RECIPE_CAP = 40;        // 自己录的菜谱卡（内置菜库在 cookbook.js，不进 state）
const OUTFIT_CAP = 30;        // 搭配册
const COOK_CAP = 60;          // 做过的菜（菜谱卡）
const MARKET_CAP = 120;       // 买菜清单条目
const WEEK_CAP = 14;          // 一周菜单（存过的周数）
const DIGEST_CAP = 60;        // 每日摘录
const NOTE_CAP = 200;         // 言笺的提醒/便签合并上限（沿用言笺的 200）
const LOG_CAP = 400;          // 行为流水（热力图/统计的原料）
const MEMO_CAP = 80;          // 衣橱搭配备忘 / 场合备注
const TAGS_CAP = 12;          // 单品自定义标签
const BADGE_CAP = 64;         // 已解锁成就
const SEARCH_HIST = 8;        // 搜索历史
const DRAFT_CAP = 6;          // 草稿（草稿箱）
const PEOPLE_SETS_CAP = 12;   // 「常一起吃饭的人」档案组数
const PLAN_WEEK_DAYS = 7;

/** 一次行为流水：热力图、连续天数、年度总结、成就都读它。
 *  kind ∈ wear/cook/catch/slip/badge/visit/…，mod ∈ yi/wei/yan/谱/册 */
/** 行为流水的类型。**新增一个调用点就要先在这里加一个值**——logEvent 对不认识的值是静默丢弃的，
 *  所以「记了但没记上」这种错只有在这里漏加时才会发生。today.js 的 KIND_NAME 与它必须一一对应。
 *
 *  0.6.0 修的一处串味：以前「办完一条言笺」与「记一句摘录」都写 `note`，
 *  于是热力图那一天的抽屉里写着「摘录 · 把报销单交了」，年度总结也把两件事算成一件；
 *  更要紧的是今日屏撤销「办完了」时按 `kind==="note"` 去删流水，
 *  同一天你真记过一句摘录，那句话会被一起删掉（实测：流水 2 条 → 1 条）。
 *  现在 `note` 只归摘录，办完言笺单独一个 `done`。 */
const LOG_KINDS = ["wear", "cook", "catch", "slip", "badge", "visit", "buy", "plan", "note", "wish",
  "market", "recipe", "outfit", "reminder", "digest", "done"];

/* 种子柜子。带一点穿着记录，第一次打开就能看出「常穿」和「久未穿」的区别。 */
const DAY = 86400000;
const seedWardrobe = () => {
  const now = Date.now();
  return [
    { id: "w1", name: "燕麦针织", cat: "上衣", color: "#d4c4b0", worn: 9, lastWorn: now - 2 * DAY },
    { id: "w2", name: "白衬衫", cat: "上衣", color: "#f4f0ea", worn: 4, lastWorn: now - 23 * DAY },
    { id: "w3", name: "深蓝阔腿", cat: "裤装", color: "#2c3a4a", worn: 12, lastWorn: now - 1 * DAY },
    { id: "w4", name: "奶油半裙", cat: "裙装", color: "#efe6d6", worn: 2, lastWorn: now - 96 * DAY },
    { id: "w5", name: "驼大衣", cat: "外套", color: "#c4a574", worn: 3, lastWorn: now - 214 * DAY },
    { id: "w6", name: "白鞋", cat: "鞋", color: "#f5f5f3", worn: 15, lastWorn: now }
  ];
};

/** 老版本的数据结构在这里补齐，避免用户升级后打不开。 */
function migrate(s) {
  if (!s || typeof s !== "object" || Array.isArray(s)) return null;
  const from = s.schema || 1;
  if (from < 2) {
    // v1 → v2：柜子加穿着记忆；新增柜子排序与报告版式
    s.wardrobe = (s.wardrobe || []).map((w) => ({ worn: 0, lastWorn: null, ...w }));
    s.closetSort = s.closetSort || "freq";
    s.reportStyle = s.reportStyle || "card";
  }
  if (from < 3) {
    // v2 → v3：「笺谱」与「册」两套体系上线。
    // 老用户的衣柜补上档案字段（价格/购入日/品牌/场合留空，不编造）；
    // 行为流水从已有的穿着记录反推出来——不然刚升级的人热力图是一片空白，
    // 而他的柜子里明明记着「穿过 9 次、最后 2 天前」。
    s.wish = Array.isArray(s.wish) ? s.wish : [];
    s.outfits = Array.isArray(s.outfits) ? s.outfits : [];
    s.cookLog = Array.isArray(s.cookLog) ? s.cookLog : [];
    s.market = Array.isArray(s.market) ? s.market : [];
    s.weeks = Array.isArray(s.weeks) ? s.weeks : [];
    s.digest = Array.isArray(s.digest) ? s.digest : [];
    s.reminders = Array.isArray(s.reminders) ? s.reminders : [];
    s.log = Array.isArray(s.log) ? s.log : [];
    s.badges = Array.isArray(s.badges) ? s.badges : [];
    s.searchHist = Array.isArray(s.searchHist) ? s.searchHist : [];
    s.drafts = Array.isArray(s.drafts) ? s.drafts : [];
    s.profile = (s.profile && typeof s.profile === "object" && !Array.isArray(s.profile)) ? s.profile : {};
    s.settings = (s.settings && typeof s.settings === "object" && !Array.isArray(s.settings)) ? s.settings : {};
    s.streak = (s.streak && typeof s.streak === "object" && !Array.isArray(s.streak)) ? s.streak : {};
    // 穿着记录反推：每件衣服记最后一笔「穿过」，够热力图和连续天数先有一点底子
    if (!s.log.length) {
      (s.wardrobe || []).forEach((w) => {
        if (w && w.lastWorn) s.log.push({ t: w.lastWorn, kind: "wear", mod: "yi", ref: w.id, v: 1 });
      });
      s.log = s.log.sort((a, b) => a.t - b.t).slice(-LOG_CAP);
    }
  }
  s.schema = SCHEMA;
  return s;
}

function load() {
  try { return migrate(JSON.parse(localStorage.getItem(KEY))); } catch { return null; }
}
/**
 * 上一次 trimStore 真丢掉了什么。上限本身是产品决定（localStorage 5MB，照片一张几十 KB），
 * 但「丢了」这件事不能只有字节知道：丢之前屏幕上写着「已用 56%」，用户只会以为 App 坏了。
 * 这是个运行时计数器，不进 state——进了备份就会每次开机都弹一次「丢过照片」。
 */
let trimLoss = { imgs: 0, clothes: 0, slips: 0, cards: 0, hist: 0, chars: 0,
  wish: 0, recipes: 0, outfits: 0, cook: 0, market: 0, weeks: 0, digest: 0, reminders: 0, log: 0, drafts: 0, peopleSets: 0 };
/** 清洗丢掉的条数，同一个口径的另一件事：备份里读不懂的条目不会进柜子，
 *  但屏幕上凭空少三条是用户没删过的少——也要说。同样是运行时计数，不进备份。 */
let normLoss = { cards: 0, album: 0,
  wish: 0, recipes: 0, outfits: 0, cook: 0, market: 0, weeks: 0, digest: 0, reminders: 0, log: 0, drafts: 0, peopleSets: 0 };
function trimStore(s) {
  const textLen = (x) => String(x ?? '').length;
  const before = { clothes: (s.wardrobe || []).length, imgs: (s.wardrobe || []).filter((w) => w && w.img).length,
                   slips: (s.album || []).length, cards: (s.yanCards || []).length,
                   hist: (s.weiHist || []).length, chars: textLen(s.weiMenu) + textLen(s.yanText),
                   wish: (s.wish || []).length, recipes: (s.recipes || []).length, outfits: (s.outfits || []).length,
                   cook: (s.cookLog || []).length, market: (s.market || []).length,
                   weeks: (s.weeks || []).length, digest: (s.digest || []).length,
                   reminders: (s.reminders || []).length, log: (s.log || []).length,
                   drafts: (s.drafts || []).length, peopleSets: (s.peopleSets || []).length };
  s.album = (s.album || []).slice(0, 24);
  if ((s.wardrobe || []).length > 36) s.wardrobe = s.wardrobe.slice(0, 36);
  // 言笺现在是合并进来的，只会越长。一条百来字节、不带图，200 条远够日常，
  // 这道上限是防「一次贴进整年的聊天记录」把渲染和配额一起撑爆。
  // **留最新的那 200 条**：新条目是 concat 到队尾的（yan.js 的 mergeCards），头切会把刚捞出来的
  // 那些掐掉、把一年前的旧账留着，而屏幕上说的是「只留最新 200 条」——全仓只有这一处是头切。
  s.yanCards = (s.yanCards || []).slice(-YAN_CAP);
  // 贴进来的菜单也是用户数据：整页重开不该让它蒸发（不然「上一桌」回来了，菜单却是空的，
  // 那个「菜单改过了」的提示就成了谎话）。4000 字够一桌点菜的量，再多是误贴。
  s.weiMenu = String(s.weiMenu ?? '').slice(0, 4000);
  s.weiHist = (s.weiHist || []).slice(0, WEI_HIST);
  s.yanText = String(s.yanText ?? '').slice(0, 4000);
  // v0.6.0 的新集合：一律保留**最近**的那一批（新数据在队尾，除非是显式的头插）。
  s.wish = (s.wish || []).slice(-WISH_CAP);
  s.recipes = (s.recipes || []).slice(-RECIPE_CAP);
  s.outfits = (s.outfits || []).slice(-OUTFIT_CAP);
  s.cookLog = (s.cookLog || []).slice(-COOK_CAP);
  s.market = (s.market || []).slice(-MARKET_CAP);
  s.weeks = (s.weeks || []).slice(-WEEK_CAP);
  s.digest = (s.digest || []).slice(-DIGEST_CAP);
  s.reminders = (s.reminders || []).slice(-NOTE_CAP);
  s.log = (s.log || []).slice(-LOG_CAP);
  s.drafts = (s.drafts || []).slice(-DRAFT_CAP);
  s.peopleSets = (s.peopleSets || []).slice(-PEOPLE_SETS_CAP);
  trimLoss = { imgs: 0, clothes: 0, slips: 0, cards: 0, hist: 0, chars: 0,
    wish: 0, recipes: 0, outfits: 0, cook: 0, market: 0, weeks: 0, digest: 0, reminders: 0, log: 0, drafts: 0, peopleSets: 0 };
  try {
    if (JSON.stringify(s).length > SHED_AT) {
      s.wardrobe = s.wardrobe.map((w, i) => (i <= 12 || !w.img ? w : { ...w, img: undefined }));
    }
  } catch (_) {}
  // 每处上限都算进「丢了什么」，而且一律用「裁剪前后的件数差」来数：
  // 在每一处删除点各记一笔，看着更直白，其实会被最后这道重算盖掉——
  // 注入「把七件说成一件」因此照旧绿（守门自检报出来的）。只留一个真相来源。
  trimLoss.clothes = Math.max(0, before.clothes - (s.wardrobe || []).length);
  trimLoss.imgs = Math.max(0, before.imgs - (s.wardrobe || []).filter((w) => w && w.img).length);
  trimLoss.slips = Math.max(0, before.slips - s.album.length);
  trimLoss.cards = Math.max(0, before.cards - s.yanCards.length);
  trimLoss.hist = Math.max(0, before.hist - s.weiHist.length);
  trimLoss.chars = Math.max(0, before.chars - textLen(s.weiMenu) - textLen(s.yanText));
  trimLoss.wish = Math.max(0, before.wish - s.wish.length);
  trimLoss.recipes = Math.max(0, before.recipes - s.recipes.length);
  trimLoss.outfits = Math.max(0, before.outfits - s.outfits.length);
  trimLoss.cook = Math.max(0, before.cook - s.cookLog.length);
  trimLoss.market = Math.max(0, before.market - s.market.length);
  trimLoss.weeks = Math.max(0, before.weeks - s.weeks.length);
  trimLoss.digest = Math.max(0, before.digest - s.digest.length);
  trimLoss.reminders = Math.max(0, before.reminders - s.reminders.length);
  trimLoss.log = Math.max(0, before.log - s.log.length);
  trimLoss.drafts = Math.max(0, before.drafts - s.drafts.length);
  trimLoss.peopleSets = Math.max(0, before.peopleSets - s.peopleSets.length);
  return s;
}
/** 丢了东西要说出来：屏幕上还写着「已用 56%」而照片已经没了，是这一类里最难自己发现的事。
 *  吃一个计数对象而不是四个位置参数：上限从三处涨到六处，位置参数已经在传错东西了。 */
function lossMsg(l) {
  const bits = [];
  if (l.clothes) bits.push(`柜子只留最新 36 件，丢掉 ${l.clothes} 件（连穿着记录一起）`);
  if (l.imgs) bits.push(`清掉 ${l.imgs} 件旧照片（衣服、颜色、记录都还在，重新拍照能补上）`);
  // 笺册丢的是最旧的那些，而它不像照片那样在屏上看得见——不说的话，用户只会以为
  // 「上周那张笺不见了」是自己记错了。留几张要看这次走的是哪条路：常规 24 张，
  // 配额吃紧的逐级丢只留 8 张，说成 24 就是一句假话。
  if (l.slips) bits.push(`笺册只留最新 ${l.keepSlips || 24} 张，丢掉 ${l.slips} 张`);
  if (l.cards) bits.push(`言笺只留最新 ${YAN_CAP} 条，丢掉 ${l.cards} 条`);
  // 「都还在」是替系统担保了一件它没担保的事：笺册总共只留 24 张，每张还能单独删。
  // 说「没动」就够准了——这一次丢的确实只是排过的桌那一份。
  if (l.hist) bits.push(`排过的桌只留 ${WEI_HIST} 桌，丢掉 ${l.hist} 桌（笺册里那些桌没动）`);
  if (l.chars) bits.push(`贴进来的字太长，掐掉后面 ${l.chars} 字`);
  if (l.wish) bits.push(`愿望单只留最新 ${WISH_CAP} 件，丢掉 ${l.wish} 件`);
  if (l.outfits) bits.push(`搭配册只留最新 ${OUTFIT_CAP} 套，丢掉 ${l.outfits} 套`);
  if (l.cook) bits.push(`做过的菜只留最新 ${COOK_CAP} 道，丢掉 ${l.cook} 道`);
  if (l.market) bits.push(`买菜清单只留最新 ${MARKET_CAP} 条，丢掉 ${l.market} 条`);
  if (l.weeks) bits.push(`一周菜单只留最新 ${WEEK_CAP} 张，丢掉 ${l.weeks} 张`);
  if (l.digest) bits.push(`每日摘录只留最新 ${DIGEST_CAP} 条，丢掉 ${l.digest} 条`);
  if (l.reminders) bits.push(`提醒只留最新 ${NOTE_CAP} 条，丢掉 ${l.reminders} 条`);
  if (l.log) bits.push(`行为记录只留最新 ${LOG_CAP} 条，丢掉 ${l.log} 条（统计会少一截）`);
  if (l.recipes) bits.push(`自己录的菜谱只留最新 ${RECIPE_CAP} 道，丢掉 ${l.recipes} 道`);
  if (l.peopleSets) bits.push(`常一起吃饭的人只留最新 ${PEOPLE_SETS_CAP} 组，丢掉 ${l.peopleSets} 组`);
  if (l.drafts) bits.push(`草稿只留最新 ${DRAFT_CAP} 条，丢掉 ${l.drafts} 条`);
  return bits.length ? `本机放不下：${bits.join("；")}。去「我的」可以导出备份` : "";
}
function save(s) {
  const data = JSON.stringify(trimStore(s));
  const lost = lossMsg(trimLoss);
  try {
    writeStore(data);
    scheduleNativeBackup();
    if (lost) toast(lost);
    return true;
  } catch (_) {
    try {
      const light = JSON.parse(data);
      const had = (light.wardrobe || []).filter((w) => w && w.img).length;
      const hadSlips = (light.album || []).length;
      light.wardrobe = (light.wardrobe || []).map((w, i) => (i > 5 ? { ...w, img: undefined } : w));
      light.album = (light.album || []).slice(0, 8);
      writeStore(JSON.stringify(light));
      scheduleNativeBackup();
      // 逐级丢是保命的办法，但「丢了」和「丢了几件」是两件事：只说「已清掉几件旧图」
      // 等于让用户自己去柜子里数哪件没了照片。笺册同理——这条路一次就丢 16 张。
      toast(lossMsg({ imgs: had - (light.wardrobe || []).filter((w) => w && w.img).length,
        slips: hadSlips - light.album.length, keepSlips: 8 }) || "本机空间紧张，已清掉几件旧图");
      return true;
    } catch (e2) {
      toast("本机存不下了。去「我的」导出备份后清空重来。");
      return false;
    }
  }
}

/** 往本机落盘的唯一入口。
 *
 *  先取消排在后面的那次防抖，是因为 saveSoon() 落的是「定时器响那一刻的 state」。
 *  凡是绕过 save() 直接写盘的地方——导入备份、清空、原生备份回写、测试里造脏数据——
 *  不取消就会在 600ms 后被旧的那份盖掉：提示说成功了，回头一看什么都没变。
 *  收成一个函数而不是在每处手写一句 cancelSoon()，因为「忘掉一句」是必然会发生的事
 *  （这一版就有两处：清空和原生回写）。 */
function writeStore(json) {
  cancelSoon();
  localStorage.setItem(KEY, json);
}
/** 清空也走这条路：留着那次防抖，清空就等于没清。 */
function clearStore() {
  cancelSoon();
  localStorage.removeItem(KEY);
}

/** 打字这种高频小改动用它：600ms 之内合并成一次写盘。
 *  save() 每次都要 JSON.stringify 整份状态（柜子里有照片时是 MB 级），
 *  跟着按键走就会在每一笔上卡一下——数据不能丢，但也不必一个字存一次。 */
let saveTimer = null;
function saveSoon() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { saveTimer = null; save(state); }, 600);
}
/** 把排着队的那一次立刻落盘（没有排队就什么都不做）。
 *
 *  为什么需要它：`saveSoon()` 合并的是 600ms 内的连续改动，而**用户不会等到定时器响**。
 *  实测：在言笺输入框里打一句、100ms 后关掉页面，重开是空的——那 600ms 里
 *  `state` 已经改了，但一个字节都没落盘。
 *  同类路径还有：安卓切到后台被系统回收、从「册」跳到别的 App、锁屏。
 *
 *  两条硬规矩：
 *  1. **只在这里落盘，不新建一个入口。** 走的是 `save(state)`，和定时器响那次完全一样
 *     （同样的裁剪、同样的 lossMsg、同样的原生保险丝）。另写一份 setItem 就绕过了前三样。
 *  2. **不能抛。** 它挂在页面生命周期事件上，那次调用里抛异常会让浏览器静默吞掉、
 *     也可能打断后面的清理。`save()` 自己已经有 try/catch，这里再兜一层。 */
function flushSoon() {
  if (!saveTimer) return false;
  clearTimeout(saveTimer);
  saveTimer = null;
  try { save(state); return true; } catch (e) { console.warn("flushSoon", e); return false; }
}
/** 取消还没落盘的那一次防抖。
 *
 *  落盘请走 writeStore()／clearStore()，它们已经调过这句了；这里留着是给
 *  「先造脏数据再自己 setItem」的测试用的——那 600ms 里等着落盘的还是**旧的那份 state**，
 *  一落盘就把刚写进去的东西盖掉。 */
function cancelSoon() { if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; } }
/** 有没有还排在后面的写盘（守门用它确认自己没和防抖打架） */
function savePending() { return !!saveTimer; }

function storageInfo() {
  try {
    const len = (localStorage.getItem(KEY) || "").length;
    // 分母是 SHED_AT（那道真的会动手的线），不是 localStorage 的 5MB：跟用户说「还没到 5MB，
    // 尚有余量」而照片正在开始丢，是一句让人做出坏决定的话。超过 100 不钳掉——那就是正在丢的状态。
    return { kb: Math.round(len / 1024), pct: Math.round((len / SHED_AT) * 100) };
  } catch (_) {
    return { kb: 0, pct: 0 };
  }
}

/**
 * 色值进 style 属性前过一遍。今天 color 只由 Engine.analyze 产出所以安全，
 * 但「导入备份」能往 localStorage 塞任意 JSON——一个带 " 的字符串就能断掉属性。
 * 与 engine.js 的 hexToRgb 回落同一档灰（200,200,200）。
 */
function cssColor(c) {
  return /^#[0-9a-f]{3,8}$/i.test(String(c ?? "")) ? c : "#c8c8c8";
}
/**
 * 收进六位十六进制的形状。`<input type=color>` 这一头其实不用我帮：
 * 实测浏览器自己会把 #abc 展成 #aabbcc、把 #2c3a4aff 截成 #2c3a4a、连 red 都翻成 #ff0000，
 * 只有真认不得的才回落 #000000。它要帮的是另外两处：
 *   ① 界面上那行**文本**没有浏览器帮忙，不展开就照原样印一个 #abc；
 *   ② 「这次到底改没改」的比较——控件回来的是六位、存储里可能是三位（cssColor 收 3~8 位，
 *      老备份里合法），不展开就会把「打开取色器、一个字没动、点确定」当成一次改动。
 */
function hex6(c) {
  const s = String(c ?? "").trim().toLowerCase();
  const m = s.match(/^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/);
  if (!m) return "#c8c8c8";
  const h = m[1];
  const rgb = h.length <= 4 ? h.slice(0, 3).split("").map((x) => x + x) : [h.slice(0, 2), h.slice(2, 4), h.slice(4, 6)];
  return "#" + rgb.join("");
}
/** 图片地址只收数据 URL 或 http(s)，别的连属性都不给进。
 *
 *  **返回的是可以原样放进 `src="…"` 的值**——调用点不必、也不该再去转义一遍
 *  （`yi.js:8` 那种在调用点写 `esc(cssImg(...))` 的写法是同一件事的第二份定义，
 *  迟早有一处忘记）。
 *
 *  以前这里只判前缀：`https://a.example/x" onerror="alert(1)` 原样放行，
 *  拼进 `<img src="${cssImg(w.img)}">` 就当场断掉属性、注入一个新属性。
 *  数据有两个外来入口（导入备份、Preferences 恢复），`w.img` 是用户能控制的。
 *  现在两件事一起做：**继续只认那两种前缀**（这是产品口径，不改），
 *  然后把结果里的 `"`、`<`、`>`、`&` 转掉（这是安全口径）。
 *  合法的 data URL 与 http(s) 地址里不会有这四个字符里除 `&` 之外的任何一个，
 *  所以对正常图片零影响；`&` 转成 `&amp;` 在 HTML 属性里仍然是同一个 URL。 */
function cssImg(src) {
  const s = String(src ?? "");
  if (!/^(data:image\/|https?:\/\/)/i.test(s)) return "";
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/**
 * 单件衣物的形状收口。数据有两个外来入口（导入备份、Preferences 恢复），
 * 而渲染时 id 要进 data-id 属性、worn 要进 title 属性——不在这儿洗干净，
 * 一个带 " 的 id 就能断掉属性。导入校验只保证 wardrobe 是个数组，管不到每一项。
 */
function newId() {
  // 原来用 "w" + Date.now()：同一毫秒连加两件会撞 id，删除时 filter 会把两件一起干掉
  return "w" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}
function normCloth(w) {
  const o = (w && typeof w === "object" && !Array.isArray(w)) ? { ...w } : {};
  o.id = /^[A-Za-z0-9_.-]{1,40}$/.test(String(o.id ?? "")) ? String(o.id) : newId();
  o.name = String(o.name ?? "").slice(0, 40) || "未命名";
  o.cat = CATS.includes(o.cat) ? o.cat : CATS[0];
  o.color = cssColor(o.color);
  const img = cssImg(o.img);
  if (img) o.img = img; else delete o.img;
  const worn = Number(o.worn);
  o.worn = Number.isFinite(worn) ? Math.max(0, Math.min(9999, Math.floor(worn))) : 0;
  const last = Number(o.lastWorn);
  o.lastWorn = Number.isFinite(last) && last > 0 ? Math.min(last, Date.now()) : null;
  // 0 次就是「还没穿过」，那它的「最后一次」不成立 —— 这两个字段不是各管各的（口径写在
  // yi.js 的穿用记录那一段）。不清，外来备份里 `{worn:0, lastWorn:今天}` 过得了上面两道
  // 钳位，屏上就是两句相反的话同时摆着：瓷砖角标与 tileLabel 按 worn 说「还没穿过」，
  // 摘要行「今天穿了」（wornToday 只看 lastWorn）却把它列进去；判定那一行更绝，
  // 前言不搭后语地说「那件还没穿过」又数落它「N 个月没穿过了」。
  if (!o.worn) o.lastWorn = null;
  if (!SEASON_OPTS.includes(o.season)) delete o.season;   // 非法值删掉，让 seasonOf 按品类推断
  /* ---------- v0.6.0 单品档案 ----------
     以前柜子里一件衣服只有名字/品类/颜色/穿了几次。要算「单次穿着成本」、要知道
     「这件买了多久」、想筛「通勤的」「这件值不值」，就都得有下面这些。全部可空——
     空着不算错（导入的老数据、急着入柜的人都没填），界面在缺字段时不许印占位符。 */
  /* 价格：null（没填过）与 0（赠品/礼物）是两件事，必须分开。
     0.6.0 的重构期这里踩过一个不幂等的坑：`Number(null)` 是 **0**，所以
     `price: null` 过一遍归一化就被写成 `price: 0` —— 一件从没填过价的衣服
     在档案页开始声称「记了 ¥0」，`itemMissing()` 里那条「还缺价格」消失，
     `closetCpw()` 的分母也跟着虚高。而导出的备份再导入一次，值还会变（不幂等），
     于是「撤销导入后逐字节比对」那条门红在一个根本看不出跟价格有关的地方。
     判据必须是「原值是 null / undefined / 空串吗」，不是「转成数字之后有限吗」。 */
  const rawPrice = o.price;
  const blankPrice = rawPrice === null || rawPrice === undefined || rawPrice === "";
  const price = Number(rawPrice);
  o.price = !blankPrice && Number.isFinite(price) && price >= 0 ? Math.min(price, 1e7) : null;
  const bought = Number(o.boughtAt);
  o.boughtAt = Number.isFinite(bought) && bought > 0 && bought <= Date.now() ? Math.floor(bought) : null;
  o.brand = String(o.brand ?? "").trim().slice(0, 20);
  o.size = String(o.size ?? "").trim().slice(0, 10);
  // 场合：多选，值域固定（和 CATS 同一套收口办法）
  o.occasions = Array.isArray(o.occasions)
    ? [...new Set(o.occasions.filter((x) => OCCASIONS.includes(x)))].slice(0, OCCASIONS.length) : [];
  // 自定义标签：用户自己写的词，只收短串
  o.tags = Array.isArray(o.tags)
    ? [...new Set(o.tags.map((x) => String(x ?? "").trim().slice(0, 8)).filter(Boolean))].slice(0, TAGS_CAP) : [];
  o.note = String(o.note ?? "").trim().slice(0, 120);
  const wearDays = Array.isArray(o.wearDays)
    ? [...new Set(o.wearDays.map(Number).filter((t) => Number.isFinite(t) && t > 0 && t <= Date.now()))].slice(-400) : [];
  o.wearDays = wearDays.sort((a, b) => a - b);
  return o;
}
function normPerson(p) {
  const o = (p && typeof p === "object" && !Array.isArray(p)) ? { ...p } : {};
  o.name = String(o.name ?? "").slice(0, 20) || "同行";
  o.chips = Array.isArray(o.chips) ? o.chips.filter((c) => CHIPS.includes(c)) : [];
  return o;
}
/** Date 能接受的极限：超出就是 Invalid Date，dayLabel 会走出「NaN月NaN日」。 */
const AT_MAX = 8.64e15;
function normYanWhen(w) {
  if (!w || typeof w !== "object" || Array.isArray(w)) return null;
  /* `Number(null) === 0`、`Number("") === 0`、`Number(false) === 0`——这个坑本仓已经
     踩过两次（`normCloth` 的价格、`normCloth` 的购入日，见前面那段长注释），这里是第三次。
     一条「没定时间」的言笺（`at: null` 或 `at: ""`）以前会被归一成 0，
     也就是 **1970 年**：它不但活了下来，还会被今日屏当成「最早就过期的那一条」排在第一位。
     判原值，不判转成数字之后的结果。 */
  const raw = w.at;
  if (raw === null || raw === undefined || raw === "") return null;
  const at = Number(raw);
  if (!Number.isFinite(at) || Math.abs(at) > AT_MAX) return null;
  // 时间是眉料（那一行上面短短的一截），不是正文：网关回一个 200 字的 text 也不该撑破行
  const text = String(w.text ?? "").slice(0, 20);
  const d = new Date(at);
  return { text: text || `${d.getMonth() + 1}月${d.getDate()}日`, at };
}
/**
 * 言笺的一条。脏值在这里不洗，出去是两种更坏的形态：
 * k 不在四类里 → 「按类型」「按时间」两边都按 k 过滤，那条**从屏上蒸发**，
 * 而头上的「N 条」用的是全量，复制整张笺也带着它——用户看到的是数不对（实测过）；
 * line 不是字符串 → 行上写出「[object Object]」，when 不是对象 → 复制出「（undefined）」。
 * 认不出来的条目（line 不是句话）丢掉：它渲染不出任何有意义的一行。
 */
function normYanCard(c) {
  if (!c || typeof c !== "object" || Array.isArray(c)) return null;
  const line = typeof c.line === "string" ? c.line.trim() : "";
  if (!line) return null;
  const o = {
    k: YAN_KINDS.includes(c.k) ? c.k : "还没说清",
    line: line.slice(0, 500),
    when: normYanWhen(c.when),
    done: c.done === true,
    moved: c.moved === true,
    wset: c.wset === true,
    /* 「今天 / 今晚」的抽屉归属。值域外一律落回 day：猜错的时段比没有时段更糟——
       一件事被错放进「今晚」，白天就永远看不到它。 */
    slot: c.slot === "evening" ? "evening" : "day",
    /* 勾掉那一刻。归档的 7 天从这个时间起算；老数据没有这个字段就是 null，
       界面上视为「还没开始计时」，**不补一个假时间**（补出来的日期会让它立刻被归档）。 */
    doneAt: timeOr(c.doneAt, null),
    /* 进归档那一刻。归档不新建集合：主列表过滤掉 archivedAt 非空的，恢复就是清回 null。
       于是 yanCards 仍是 200 条上限，trimStore / normLoss 那套一个字都不用动。 */
    archivedAt: timeOr(c.archivedAt, null),
  };
  // who / speaker 会进徽章和 aria-label：不是字符串就整个不给（宁可少一枚签）
  if (typeof c.who === "string" && c.who.trim()) o.who = c.who.trim().slice(0, 20);
  if (typeof c.speaker === "string" && c.speaker.trim()) o.speaker = c.speaker.trim().slice(0, 20);
  return o;
}
/** 笺册的一行。这一处不洗是会**抛**的：null 让 renderMe 在 a.type 上取属性，
 *  「我的」整屏空白；quote 是对象则在 .slice 上抛（都实测过）。 */
function normAlbumItem(a) {
  if (!a || typeof a !== "object" || Array.isArray(a)) return null;
  const quote = typeof a.quote === "string" ? a.quote.slice(0, 120) : "";
  const text = typeof a.text === "string" ? a.text.slice(0, 6000) : "";
  if (!quote && !text) return null;        // 两头都空的一行，点开只会是「没存下能复制的话」
  const t = Number(a.t);
  return {
    type: typeof a.type === "string" ? a.type.slice(0, 10) : "yi",
    t: Number.isFinite(t) && t > 0 ? Math.min(t, Date.now()) : Date.now(),
    quote, text,
    ...(typeof a.stamp === "string" && a.stamp.trim() ? { stamp: a.stamp.trim().slice(0, 12) } : {}),
  };
}

/**
 * 味笺那张结果对象的形状收口。它有两个外来入口：导入备份 / Preferences 恢复，
 * 以及**用户自己填的那台网关**（`/v1/complete` 背后是一个模型，它回什么都有可能）。
 * 画的时候每个字段都是逐个 .map / Object.entries 的，缺字段 paintWei 有 `|| []` 兜着，
 * 形状错了没有：一个 `"boom": {}` 就能让整屏空白，而且不报错。
 * 恢复路径与刚排完的那一桌共用这一份——两边各清一半，就是漂移藏身的地方。
 */
function cleanWeiResult(r) {
  if (!r || typeof r !== "object" || Array.isArray(r)) return null;
  ["safe", "risk", "boom", "suggest", "add", "dupes", "order", "notes", "bans", "chipBans", "inferred"]
    .forEach((k) => { if (!Array.isArray(r[k])) delete r[k]; });
  // inferred 的元素要能取 .chip：一个字符串会让那一行写成「这句里写着忌口：、」
  if (r.inferred) r.inferred = r.inferred
    .filter((x) => x && typeof x === "object" && typeof x.chip === "string" && typeof x.from === "string");
  if (r.notes) r.notes = r.notes.filter((x) => typeof x === "string" && x.trim()).slice(0, 40);
  if (!r.kinds || typeof r.kinds !== "object" || Array.isArray(r.kinds)) r.kinds = {};
  if (!r.plan || typeof r.plan !== "object" || Array.isArray(r.plan)) r.plan = {};
  // plan.want 是「荤 2 / 素 3」那一行直接取子键的地方：缺了要补空对象，删掉反而把它弄崩
  ["want", "gap"].forEach((k) => {
    if (!r.plan[k] || typeof r.plan[k] !== "object" || Array.isArray(r.plan[k])) r.plan[k] = {};
  });
  return r;
}

/** 旧报告可以没有 new（仍可复制文字），但不能带形状错误的对象进绘图。 */
function validYiPiece(x) {
  if (!x || typeof x !== "object" || Array.isArray(x)) return false;
  return ["name", "cat", "color", "img"].every((k) => x[k] == null || typeof x[k] === "string");
}
function validYiReport(r) {
  if (!r || typeof r !== "object" || Array.isArray(r)) return false;
  if (r.stamp != null && typeof r.stamp !== "string") return false;
  if (r.quote != null && typeof r.quote !== "string") return false;
  if (r.new != null && !validYiPiece(r.new)) return false;
  if (r.basis != null && !validYiPiece(r.basis)) return false;
  for (const k of ["close", "match"]) {
    if (r[k] == null) continue;
    if (!Array.isArray(r[k]) || r[k].length > 36 || !r[k].every(validYiPiece)) return false;
  }
  return true;
}

/**
 * 网关地址的唯一口径：收不收、为什么不收，只在这里算一次。
 * 开机钳位（normalizeState）与「保存接口」那一枚（app.js #saveApi）都读它——
 * 一个规则两份定义是本仓反复栽过的那一族（nearWord / countMenu / paintReportActions）。
 * 留空是合法值，意思是「全程不联网」。
 * 局域网的明文 http 是**合法**用法，安卓壳刻意允许了明文流量（docs/上架/商店材料.md 第 3 节），
 * 所以它不能当错误挡掉；保存那一句会顺带提一句它不加密。
 * @returns {{url:string, why:string}} url 为 "" 表示这一条不进账本，why 是当场要说的话。
 */
function normApi(v) {
  const s = String(v ?? "").trim();
  if (!s) return { url: "", why: "" };
  const m = /^https?:\/\//i.exec(s);
  if (!m) return { url: "", why: "地址要以 http:// 或 https:// 开头，比如 http://192.168.1.5:8787" };
  const rest = s.slice(m[0].length);
  if (!rest) return { url: "", why: `${m[0]} 后面还没有地址` };
  if (/\s/.test(rest)) return { url: "", why: "地址中间不能有空格" };
  if (rest.length > API_MAX)
    return { url: "", why: `地址太长了：${m[0]} 后面最多 ${API_MAX} 字，这一条有 ${rest.length} 字` };
  return { url: s, why: "" };
}

/** 老数据/外来的备份补齐缺省字段；boot 里从 Preferences 恢复备份后也会再走一遍。 */
function normalizeState(s) {
  s.modules = (s.modules && typeof s.modules === "object" && !Array.isArray(s.modules))
    ? { yi: !!s.modules.yi, wei: !!s.modules.wei, yan: !!s.modules.yan }
    : { yi: true, wei: true, yan: true };
  s.wardrobe = Array.isArray(s.wardrobe) ? s.wardrobe.map(normCloth) : seedWardrobe();
  s.people = (Array.isArray(s.people) && s.people.length) ? s.people.map(normPerson) : [{ name: "我", chips: [] }];
  normLoss = { cards: 0, album: 0,
    wish: 0, recipes: 0, outfits: 0, cook: 0, market: 0, weeks: 0, digest: 0, reminders: 0, log: 0, drafts: 0, peopleSets: 0 };
  const yc = Array.isArray(s.yanCards) ? s.yanCards : [];
  const ycn = yc.map(normYanCard).filter(Boolean);
  normLoss.cards = yc.length - ycn.length;
  s.yanCards = ycn;
  const ab = Array.isArray(s.album) ? s.album : [];
  const abn = ab.map(normAlbumItem).filter(Boolean);
  normLoss.album = ab.length - abn.length;
  s.album = abn;
  // 空柜是合法状态（用户真的把柜子清空了），不要拿种子柜去覆盖它
  if (!["freq", "idle", "new", "cpw"].includes(s.closetSort)) s.closetSort = "freq";
  if (!["all", ...SEASON_OPTS].includes(s.closetSeason)) s.closetSeason = "all";
  // 三个视图：按类型 / 按时间 / 月历。月历是 v0.6.0 加的——同一批事换个看法，
  // 是「体量」最便宜的一种（滴答清单的四视图被验证过）。
  if (!["kind", "time", "calendar"].includes(s.yanView)) s.yanView = "kind";
  // 「只看没办的」是视图偏好，跟着走；柜子的搜索词是临时过滤，故意不入库
  s.yanHideDone = !!s.yanHideDone;
  // 上一桌的味笺：备份能往这里塞任意 JSON，画之前先确认真是个结果对象，
  // 否则 renderWei 会在一个来路不明的 r 上取 .kinds / .boom
  const lw = s.lastWei;
  const lwr = lw && typeof lw === "object" && !Array.isArray(lw) ? cleanWeiResult(lw.r) : null;
  // 上一桌不受集合上限管：坏备份可塞进巨量文本，下一次 save() 就可能挤掉用户照片。
  // 超过合理的结果体积直接丢弃这份缓存（当前菜单与历史记录不受影响）。
  if (!lwr || JSON.stringify(lwr).length > 80000) delete s.lastWei;
  else {
    s.lastWei.menu = String(lw.menu ?? "").slice(0, 4000);
    s.lastWei.talk = String(lw.talk ?? "").slice(0, 6000);
    s.lastWei.r = lwr;
  }
  // 报告与几个视图偏好同样可能来自外部备份：不能把对象/数组直接送进 DOM。
  if (s.lastReport != null && !validYiReport(s.lastReport)) s.lastReport = null;
  if (s.lastNew != null && !validYiPiece(s.lastNew)) s.lastNew = null;
  if (!["friends", "couple", "home", "work"].includes(s.weiMode)) s.weiMode = "friends";
  if (!CATS.includes(s.yiCat)) s.yiCat = CATS[0];
  s.yanAsk = typeof s.yanAsk === "string" ? s.yanAsk.slice(0, 500) : "";
  // 排过的桌：一桌一行文本，脏值会让 renderWeiHist 在 h.chips 上取长度取崩，
  // 也会把任意字符串写进按钮的文本里。菜单收进 4000 字，人数收进 1..99。
  s.weiHist = Array.isArray(s.weiHist) ? s.weiHist
    .filter((h) => h && typeof h === "object" && !Array.isArray(h) && typeof h.menu === "string" && h.menu.trim())
    .slice(0, WEI_HIST).map((h) => {
      const n = Number(h.n), t = Number(h.t);
      return {
        menu: h.menu.slice(0, 4000),
        n: Number.isFinite(n) ? Math.min(99, Math.max(1, Math.floor(n))) : 1,
        t: Number.isFinite(t) && t > 0 ? Math.min(t, Date.now()) : Date.now(),
        chips: Array.isArray(h.chips) ? h.chips.filter((c) => CHIPS.includes(c)) : []
      };
    }) : [];
  s.weiMenu = String(s.weiMenu ?? "").slice(0, 4000);
  s.yanText = String(s.yanText ?? "").slice(0, 4000);
  if (s.clothSel !== null && !s.wardrobe.some((w) => w.id === s.clothSel)) s.clothSel = null;
  if (!["card", "mag"].includes(s.reportStyle)) s.reportStyle = "card";
  // 钱包与偏好：类型不对会直接把 NaN 印到界面上
  const pts = Number(s.points);
  s.points = Number.isFinite(pts) ? Math.max(0, Math.min(9999, Math.floor(pts))) : 24;
  if (!["all", "yi", "wei", "yan"].includes(s.plan)) s.plan = null;
  s.onboarded = !!s.onboarded;
  if (!["yi", "wei", "yan"].includes(s.home)) s.home = "yi";
  s.apiUrl = normApi(s.apiUrl).url;
  normalizeV06(s);
  s.schema = SCHEMA;
  return s;
}

/* ==================== v0.6.0：新集合的钳位 ====================
   一个函数收口，因为 normalizeState 已经 60 行了，再往里塞两百行钳位没人读得下去。
   规矩和上面一致：外来的备份能往任何一个集合塞任意 JSON，而渲染时这些字段会进
   innerHTML、进 data-* 属性、进 canvas 文本。形状不对的一律**丢掉条目**并计入 normLoss，
   不要「补个默认值继续画」——补出来的假数据比少一行更难发现。 */
function num(v, lo, hi, dflt) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt;
}
function shortText(v, max) { return String(v ?? "").trim().slice(0, max); }
function timeOr(v, dflt) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 && n <= Date.now() + 86400000 * 365 ? Math.floor(n) : dflt;
}
function strList(v, max, each) {
  return Array.isArray(v)
    ? [...new Set(v.map((x) => shortText(x, each || 24)).filter(Boolean))].slice(0, max)
    : [];
}

function normalizeV06(s) {
  normLoss.wish = 0; normLoss.outfits = 0; normLoss.cook = 0; normLoss.market = 0;
  normLoss.weeks = 0; normLoss.digest = 0; normLoss.reminders = 0; normLoss.log = 0; normLoss.drafts = 0;

  /* 愿望单：想买但还没买的那件。冷静期是核心机制——加了日期，到期才提醒「还想买吗」。 */
  const wishIn = Array.isArray(s.wish) ? s.wish : [];
  s.wish = wishIn.map((w) => {
    if (!w || typeof w !== "object" || Array.isArray(w)) return null;
    const name = shortText(w.name, 40);
    if (!name) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(w.id ?? "")) ? String(w.id) : "s" + newId().slice(1),
      name,
      cat: CATS.includes(w.cat) ? w.cat : CATS[0],
      color: cssColor(w.color),
      price: w.price === null || w.price === undefined ? null : num(w.price, 0, 1e7, null),
      t: timeOr(w.t, Date.now()),
      // 冷静期天数：0 表示不设冷静期（当场决定要不要买）
      cool: num(w.cool, 0, 90, 3),
      note: shortText(w.note, 80),
      done: !!w.done,          // 已决定（买了或放弃）；不做硬删除，留着给统计看
      bought: !!w.bought,
    };
  }).filter(Boolean).slice(-WISH_CAP);
  normLoss.wish = wishIn.length - s.wish.length;

  /* 搭配册：一套 = 若干件衣柜里的单品 + 一句备注。单品 id 找不到时**保留 id**，
     渲染时跳过——删了一件衣服不该把整套搭配一起删掉（那套搭配是用户的心思）。 */  const outfitIn = Array.isArray(s.outfits) ? s.outfits : [];
  s.outfits = outfitIn.map((o) => {
    if (!o || typeof o !== "object" || Array.isArray(o)) return null;
    const ids = Array.isArray(o.ids) ? [...new Set(o.ids.map((x) => String(x ?? "")).filter(Boolean))] : [];
    if (!ids.length) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(o.id ?? "")) ? String(o.id) : "o" + newId().slice(1),
      name: shortText(o.name, 20) || "一套",
      ids: ids.slice(0, 12),
      occasion: OCCASIONS.includes(o.occasion) ? o.occasion : "",
      note: shortText(o.note, 80),
      t: timeOr(o.t, Date.now()),
      worn: num(o.worn, 0, 9999, 0),
      lastWorn: timeOr(o.lastWorn, null),
    };
  }).filter(Boolean).slice(-OUTFIT_CAP);
  normLoss.outfits = outfitIn.length - s.outfits.length;

  /* 自己录的菜谱：内置菜库（cookbook.js 的 RECIPES）不在 state 里，随包走、不占配额。
     用户自己录的才存这里——**菜谱正文只允许用户自己写**，不从网上抓（版权 + 联网）。 */
  const rcIn = Array.isArray(s.recipes) ? s.recipes : [];
  s.recipes = rcIn.map((r) => {
    if (!r || typeof r !== "object" || Array.isArray(r)) return null;
    const name = shortText(r.name, 30);
    if (!name) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(r.id ?? "")) ? String(r.id) : "k" + newId().slice(1),
      name,
      minutes: num(r.minutes, 0, 600, 0),
      level: num(r.level, 0, 3, 0),
      serves: num(r.serves, 1, 20, 2),
      items: Array.isArray(r.items)
        ? r.items.map((x) => shortText(typeof x === "string" ? x : (x && x.n), 30)).filter(Boolean).slice(0, 30)
        : [],
      steps: Array.isArray(r.steps)
        ? r.steps.map((x) => shortText(x, 200)).filter(Boolean).slice(0, 30)
        : [],
      t: timeOr(r.t, Date.now()),
    };
  }).filter(Boolean).slice(-RECIPE_CAP);
  normLoss.recipes = rcIn.length - s.recipes.length;

  /* 做过的菜：cookLog 一条 = 某天做了某道菜。菜名要能在菜库里对上才好算「重复做过几次」，
     但用户自己写的菜也要能记（菜库之外的家常菜），所以只收名字不校验存在性。 */
  const cookIn = Array.isArray(s.cookLog) ? s.cookLog : [];
  s.cookLog = cookIn.map((c) => {
    if (!c || typeof c !== "object" || Array.isArray(c)) return null;
    const name = shortText(c.name, 30);
    if (!name) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(c.id ?? "")) ? String(c.id) : "c" + newId().slice(1),
      name,
      t: timeOr(c.t, Date.now()),
      // 1-5 星；0 表示没评分（不默认满分）
      stars: num(c.stars, 0, 5, 0),
      note: shortText(c.note, 60),
      people: num(c.people, 1, 99, 1),
    };
  }).filter(Boolean).slice(-COOK_CAP);
  normLoss.cook = cookIn.length - s.cookLog.length;

  /* 买菜清单：按类别分组（蔬菜/肉蛋/水产/主食/调料/其他）。 */
  const MARKET_KINDS = ["蔬菜", "肉蛋", "水产", "主食", "调料", "水果", "其他"];
  const mkIn = Array.isArray(s.market) ? s.market : [];
  s.market = mkIn.map((m) => {
    if (!m || typeof m !== "object" || Array.isArray(m)) return null;
    const name = shortText(m.name, 30);
    if (!name) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(m.id ?? "")) ? String(m.id) : "m" + newId().slice(1),
      name,
      kind: MARKET_KINDS.includes(m.kind) ? m.kind : "其他",
      qty: shortText(m.qty, 10),
      done: !!m.done,
      t: timeOr(m.t, Date.now()),
    };
  }).filter(Boolean).slice(-MARKET_CAP);
  normLoss.market = mkIn.length - s.market.length;

  /* 一周菜单：7 天 × 最多 3 餐的餐名数组。 */
  const wkIn = Array.isArray(s.weeks) ? s.weeks : [];
  s.weeks = wkIn.map((w) => {
    if (!w || typeof w !== "object" || Array.isArray(w)) return null;
    const start = timeOr(w.start, null);
    if (!start) return null;
    const days = Array.isArray(w.days) ? w.days.slice(0, PLAN_WEEK_DAYS).map((d) => ({
      noon: strList(d && d.noon, 4, 20),
      night: strList(d && d.night, 4, 20),
    })) : [];
    return { start, days, note: shortText(w.note, 40) };
  }).filter(Boolean).slice(-WEEK_CAP);
  normLoss.weeks = wkIn.length - s.weeks.length;

  /* 每日摘录：一句金句 + 来源。 */
  const dgIn = Array.isArray(s.digest) ? s.digest : [];
  s.digest = dgIn.map((d) => {
    if (!d || typeof d !== "object" || Array.isArray(d)) return null;
    const text = shortText(d.text, 200);
    if (!text) return null;
    return { t: timeOr(d.t, Date.now()), text, from: shortText(d.from, 40), mood: num(d.mood, 0, 4, 0) };
  }).filter(Boolean).slice(-DIGEST_CAP);
  normLoss.digest = dgIn.length - s.digest.length;

  /* 提醒：从言笺条目里派生，但**单独存一份**（言笺条目可以删，提醒要独立活着）。 */
  const rmIn = Array.isArray(s.reminders) ? s.reminders : [];
  s.reminders = rmIn.map((r) => {
    if (!r || typeof r !== "object" || Array.isArray(r)) return null;
    const text = shortText(r.text, 120);
    const at = timeOr(r.at, null);
    if (!text || !at) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(r.id ?? "")) ? String(r.id)
        : "r" + newId().slice(1),
      text, at,
      // repeat: ""（一次）/ daily / weekly / monthly
      repeat: ["", "daily", "weekly", "monthly"].includes(r.repeat) ? r.repeat : "",
      done: !!r.done,
      fired: !!r.fired,
      from: ["yan", "manual", "wei"].includes(r.from) ? r.from : "manual",
    };
  }).filter(Boolean).sort((a, b) => a.at - b.at).slice(-NOTE_CAP);
  normLoss.reminders = rmIn.length - s.reminders.length;

  /* 行为流水：热力图、连续天数、年度总结的原料。只收认识 kind 的条目。 */
  const logIn = Array.isArray(s.log) ? s.log : [];
  s.log = logIn.map((e) => {
    if (!e || typeof e !== "object" || Array.isArray(e)) return null;
    const t = timeOr(e.t, null);
    if (!t || !LOG_KINDS.includes(e.kind)) return null;
    return {
      t, kind: e.kind,
      mod: ["yi", "wei", "yan", "me", "pu"].includes(e.mod) ? e.mod : "me",
      ref: shortText(e.ref, 40),
      v: num(e.v, 0, 1e6, 1),
    };
  }).filter(Boolean).sort((a, b) => a.t - b.t).slice(-LOG_CAP);
  normLoss.log = logIn.length - s.log.length;

  /* 草稿：言笺贴了一大段没捞、切走再回来还在。 */
  const dfIn = Array.isArray(s.drafts) ? s.drafts : [];
  s.drafts = dfIn.map((d) => {
    if (!d || typeof d !== "object" || Array.isArray(d)) return null;
    const text = shortText(d.text, 4000);
    if (!text) return null;
    return { t: timeOr(d.t, Date.now()), text, from: shortText(d.from, 20) };
  }).filter(Boolean).slice(-DRAFT_CAP);
  normLoss.drafts = dfIn.length - s.drafts.length;
  /* 「常一起吃饭的人」：一组 = 一批人 + 一个名字。存下来的是**人名与忌口的快照**，
     不是引用——删掉某人之后，旧的一组里他还应该在（那是当时那桌人）。 */
  const psIn = Array.isArray(s.peopleSets) ? s.peopleSets : [];
  s.peopleSets = psIn.map((g) => {
    if (!g || typeof g !== 'object' || Array.isArray(g)) return null;
    const names = Array.isArray(g.names) ? g.names.map((p) => {
      if (!p || typeof p !== 'object') return null;
      const nm = shortText(p.name, 20);
      if (!nm) return null;
      return { name: nm, chips: Array.isArray(p.chips) ? [...new Set(p.chips.filter((c) => CHIPS.includes(c)))] : [] };
    }).filter(Boolean) : [];
    if (!names.length) return null;
    return {
      id: /^[A-Za-z0-9_.-]{1,40}$/.test(String(g.id ?? '')) ? String(g.id) : 'p' + newId().slice(1),
      name: shortText(g.name, 20) || names.map((x) => x.name).join('、').slice(0, 20),
      names: names.slice(0, 12),
      t: timeOr(g.t, Date.now()),
    };
  }).filter(Boolean).slice(-PEOPLE_SETS_CAP);
  normLoss.peopleSets = psIn.length - s.peopleSets.length;

  /* 成就：只存 id 与解锁时间，定义在 achievements.js 里（解锁时间要能画成时间轴）。 */
  const bdIn = Array.isArray(s.badges) ? s.badges : [];
  s.badges = bdIn.map((b) => {
    if (!b || typeof b !== "object" || Array.isArray(b)) return null;
    const id = shortText(b.id, 40);
    if (!id) return null;
    return { id, t: timeOr(b.t, Date.now()) };
  }).filter(Boolean).slice(-BADGE_CAP);
  // 同一个成就重复解锁只留最早那次（解锁时间点是不会回来的那一刻，重解锁不该改写它）
  {
    const seen = new Set();
    s.badges = s.badges.filter((b) => (seen.has(b.id) ? false : (seen.add(b.id), true)));
  }

  /* 个人档案：全是可选，空字符串表示没填。 */
  const pf = s.profile || {};
  s.profile = {
    nick: shortText(pf.nick, 16),
    avatar: /^(data:image\/)/i.test(String(pf.avatar ?? "")) ? String(pf.avatar) : "",
    // 「我是谁」的一句话，出现在年度总结第一页
    line: shortText(pf.line, 60),
    since: timeOr(pf.since, null),        // 开始用笺的日子，年度总结要按它算
  };
  // 第一次跑就记下开始的日子：年度总结没有「从哪一天起」就画不出年表
  if (!s.profile.since) s.profile.since = Date.now();

  /* 设置：主题/字号/动效/通知/每日一问/触感。每一个都有值域。 */
  const st = s.settings || {};
  s.settings = {
    theme: ["auto", "light", "dark"].includes(st.theme) ? st.theme : "auto",
    font: ["s", "m", "l"].includes(st.font) ? st.font : "m",
    motion: st.motion === false ? false : true,
    haptic: st.haptic === false ? false : true,
    notify: st.notify === false ? false : true,
    notifyAt: /^\d{1,2}:\d{2}$/.test(String(st.notifyAt ?? "")) ? String(st.notifyAt) : "20:30",
    daily: st.daily === false ? false : true,
    // 首页那枚「每日一问」每天换一条，答案存进 digest
    reduceMotion: st.reduceMotion === true,
    sealStyle: ["classic", "thin", "solid"].includes(st.sealStyle) ? st.sealStyle : "classic",
  };

  /* 连续天数：{ last: 最后活跃日（YYYY.MM.DD）, days: 当前连了几天的桶 }。
     用「日」字符串而不是时间戳——跨时区、夏令时、手动改时间都不该把连续天数弄错。 */
  const sk = s.streak || {};
  s.streak = {
    last: /^\d{4}\.\d{2}\.\d{2}$/.test(String(sk.last ?? "")) ? String(sk.last) : "",
    days: num(sk.days, 0, 100000, 0),
    best: num(sk.best, 0, 100000, 0),
  };
  /* 搜索历史：全是短串，重复的只留最近一次。 */
  s.searchHist = strList(s.searchHist, SEARCH_HIST, 24);
  return s;
}
let state = load() || {
  onboarded: false,
  modules: { yi: true, wei: true, yan: true },
  home: "yi",
  points: 24,
  plan: null,
  wardrobe: seedWardrobe(),
  lastNew: null,
  lastReport: null,
  people: [{ name: "我", chips: [] }, { name: "同行", chips: ["香菜"] }],
  weiMode: "friends",
  album: [],
  yiCat: "上衣",
  editCloset: false,
  closetSort: "freq",
  closetSeason: "all",
  clothSel: null,
  reportStyle: "card",
  yanCards: [],
  yanAsk: "",
  weiMenu: "",
  weiHist: [],
  yanText: "",
  yanView: "kind",
  yanHideDone: false,
  apiUrl: "",
  // v0.6.0：笺谱与册两套体系
  wish: [], recipes: [], outfits: [], cookLog: [], market: [], weeks: [], digest: [], peopleSets: [],
  reminders: [], log: [], badges: [], searchHist: [], drafts: [],
  profile: {}, settings: {}, streak: {},
};
normalizeState(state);
if (state.apiUrl) window.JIAN_CONFIG.endpoint = state.apiUrl;
let busy = false;

function spend(n, mod) {
  if (state.plan === "all" || state.plan === mod) return true;
  // 「去『我的』开一笺」以前指不到地方：「我的」那一屏上「开哪一笺」那三枚只管模块开关，
  // 一个点也不送；送点的在折叠着的「测试订阅」里。名字撞车，照着做的人只会更困惑。
  // 「送 16 点」那句也过期了：现在按「当场真的从关到开了几笺」一笺 8 点发，
  // 已经开着的一笺不重复给——写死一个 16 是在教人去做一件不会发生的事。
  if (state.points < n) {
    toast("笺点不足。去「我的」展开「测试订阅」：开哪一笺，那一笺就不再扣点");
    return false;
  }
  state.points -= n; save(state); renderWallet(); return true;
}
/** 这一步没做成，把点退回去——不能因为出错白扣。 */
function refund(n, mod) {
  if (state.plan === "all" || state.plan === mod) return;
  state.points += n; save(state); renderWallet();
}

/* ==================== 行为流水与连续天数 ====================
   全仓原先只有三个孤立的时间点（worn/lastWorn、weiHist[].t、album[].t），
   所以「穿着日历 / 热力图 / 连续天数 / 年度总结 / 成就」五件事一件都做不出来。
   log 是它们的共同原料：一条 = 某时刻发生了某类事。

   两条硬规矩：
   1. **日的界只有 dayStr() 一处**（ui.js:105）。跨时区、夏令时、手动改系统时间都不该
      让「今天」裂成两个，所以连续天数只比 dayStr 的字符串，绝不自己算 86400000 的倍数。
   2. **只记事实，不记评价**。log 里不存「这次是第 N 次」这类派生数——派生数一旦落盘，
      删掉一条旧记录之后它就成了假话。统计一律现算。
*/
/** 记一笔。调用点遍布三笺与册，所以它必须永不抛：日志失败不该毁掉用户真正在做的事。 */
function logEvent(kind, mod, ref, v) {
  try {
    if (!LOG_KINDS.includes(kind)) return;
    state.log.push({ t: Date.now(), kind, mod: mod || "me", ref: String(ref || "").slice(0, 40),
      v: Number.isFinite(Number(v)) ? Number(v) : 1 });
    if (state.log.length > LOG_CAP) state.log = state.log.slice(-LOG_CAP);
    bumpStreak();
    /* 成就检查挂在**这一处**：它是全 App 唯一「记完一笔」的收口，所以只有这里能保证
       「做的事一到数，章就当场落下」。别处（进笺谱 / 进章屏）的兜底调用是补漏，不是主路
       ——导入备份、换机恢复这两条路没有 logEvent，章数只能在进屏时补算。
       achievements.js 在 state.js 之后加载，logEvent 是运行时调用，不会踩 TDZ。 */
    try { if (typeof checkBadges === "function") checkBadges(); } catch (_) { }
    saveSoon();
  } catch (e) { console.warn("log", e); }
}

/** 连续天数：一天里第一次有动作时 +1；昨天有动作则 +1，否则从 1 重新开始。
 *  不惩罚、不归零惩罚——归零只是「从 1 开始」，屏幕上不会出现「你断了」这种句子。 */
function bumpStreak() {
  const today = dayStr(Date.now());
  const st = state.streak;
  if (st.last === today) return;                    // 今天已经记过
  const yStr = dayStr(Date.now() - 86400000);
  st.days = st.last === yStr ? st.days + 1 : 1;
  st.last = today;
  if (st.days > st.best) st.best = st.days;
}

/** 某个日历日有没有动作（热力图与「往年今日」都问这一句）。 */
function activeOn(dayKey) {
  return (state.log || []).some((e) => dayStr(e.t) === dayKey);
}
/** 全部有动作的日子，去重并升序。热力图、连续天数校验、年度总结都读它。 */
function activeDays() {
  const set = new Set((state.log || []).map((e) => dayStr(e.t)));
  return [...set].sort();
}
/** 某一天的全部事件（「往年今日」按「月.日」跨年匹配，所以调用方自己拼 dayKey）。 */
function eventsOn(dayKey) {
  return (state.log || []).filter((e) => dayStr(e.t) === dayKey);
}
/** 今年的起止：年度总结与「今年做了 N 件事」按自然年算。 */
function yearSpan(year) {
  const y = Number.isFinite(Number(year)) ? Number(year) : new Date().getFullYear();
  return { from: new Date(y, 0, 1).getTime(), to: new Date(y + 1, 0, 1).getTime(), year: y };
}
/** 区间内的流水（左闭右开）。 */
function eventsBetween(from, to) {
  return (state.log || []).filter((e) => e.t >= from && e.t < to);
}
/** 按 kind 计数。返回普通对象，方便直接印到屏上或算百分比。 */
function countByKind(list) {
  const out = {};
  (list || []).forEach((e) => { out[e.kind] = (out[e.kind] || 0) + 1; });
  return out;
}
