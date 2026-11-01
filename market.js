/** 笺 · 买菜清单
 *
 *  这一份只做一件事，但要做对：**把「要买什么」变成一张按货架分区的单子**。
 *
 *  三条从 Paprika 学来的、值得学的规矩：
 *  1. **清单是菜谱的派生物，不是独立功能。** 从菜谱详情页点「去记要买」、从一周菜单
 *     点「变成清单」，都会走到 addMarketItems()——手动一条一条敲是保底路径，不是主路径。
 *  2. **同名同单位要合并。**「鸡蛋 2 个 + 鸡蛋 3 个 = 5 个」。合并要保守：
 *     单位不同就并排摆着，不硬凑成一行（`1 个` + `200 克` 相加是一句假话）。
 *  3. **按货架分区。** 蔬菜/肉蛋/水产/主食/调料/水果/其他——这是人在超市里走的顺序。
 *
 *  v0.6.0 补的两件事：
 *  - **排序可以换。** 默认按货架（超市动线），另一档按加入时间（想起一样加一样的时候更顺手）。
 *    两种排法都稳定：同档里按加入时间，不抖。
 *  - **勾掉就是一笔记录。** 勾掉时 logEvent("market")——成就「买到二十样」只有这一处在记。
 */

const MARKET_KINDS = ["蔬菜", "肉蛋", "水产", "主食", "调料", "水果", "其他"];
/** 货架分区规则：**按「这东西在超市哪个区能买到」判**，判不出来就「其他」——**不猜**。
 *
 *  上一版全是单字词、谁先命中谁赢，实测 232 个常见食材里 30 多条落错区：
 *   · 「椒」先被调料抢走 → 青椒 / 尖椒 / 彩椒 / 小米椒 显示在调料区；
 *   · 「粉」先被主食抢走 → 胡椒粉 / 花椒粉 / 淀粉 / 泡打粉 显示在米面区；
 *   · 「螺」抢走螺丝椒、「米」抢走小米辣、「鱼」抢走鱼腥草、「鸡」抢走鸡腿菇；
 *   · 里脊 / 花甲 / 生蚝 / 海参 / 西兰花 干脆落进「其他」。
 *  这些错不是「难看」，是**让人在超市里走回头路**——按货架排的全部意义就是避免这个。
 *
 *  现在的顺序按「谁更具体」排，不按字母：
 *  1. 前几条是**例外清单**：名字里带着别区的字，但东西不在那一区；
 *  2. 再按区判：冷藏柜 → 调料 → 坚果 → 水产 → 水果 → 蔬菜 → 主食 → 肉蛋；
 *  3. 判不出来仍是「其他」。
 *
 *  几条写死在这里的常识（test/wei_v06.playwright.py 逐条钉住）：
 *  · 鲜椒是菜（青椒 / 尖椒 / 小米辣 / 螺丝椒）；花椒 / 胡椒 / 辣椒粉 是调料；
 *  · 核桃 / 腰果 / 花生 在干货架，既不是水果也不是米；
 *  · 牛奶 / 酸奶 / 黄油 是冷藏柜——七区里没有乳品，报「其他」比硬塞进肉蛋诚实；
 *  · 淀粉 / 生粉 / 泡打粉 跟盐糖一起摆，不进米面区；
 *  · 油麦菜 / 油菜 是菜不是油，紫菜 / 海带 是水产干货不是菜。 */
const MARKET_RULES = [
  /* ① 例外清单：字面上撞了后面某一条，但东西在另一个区。
        「马蹄」不是猪蹄，「牛蒡」不是牛肉，「鱼腥草」不是鱼，「蟹味菇」不是蟹，
        「猪耳朵」不是木耳，「樱桃萝卜」不是樱桃，「芝麻菜」不是芝麻。 */
  ["蔬菜", /鱼腥草|折耳根|螺丝椒|马蹄|荸荠|牛蒡|蟹味菇|杏鲍菇|千张|腐竹|橄榄菜|雪里蕻|西葫芦|柿子椒|樱桃萝卜|芝麻菜|豆芽|芸豆角|苦菊|二荆条|鸡毛菜|鸡腿菇|牛肝菌|木耳菜/],
  /* 半成品 / 成品：名字里带着别区的字（葱 / 酱 / 韭 / 蛋），但整件东西在米面冷冻区。
        这一条必须最靠前：它们字面上会被③的「酱」和⑦的「葱 / 韭」抢走。 */
  ["主食", /葱油饼|葱油面|葱油拌面|炸酱面|韭菜盒子|鸡蛋灌饼|蛋炒饭/],
  /* 熟食柜的东西名字里带着「酱」或「蛋」，但买的是肉 / 蛋，不是酱。 */
  ["肉蛋", /酱牛肉|酱肉|酱肘子|酱鸭|酱鸡|酱排骨|酱猪蹄|卤肉|卤味|卤蛋|猪耳|牛耳|鸽子|荷包蛋|茶叶蛋|煎蛋|蒸蛋/],
  /* 干豆 / 杂粮 / 面点：字面上带「豆 / 米 / 粉」，但货架上是粮油干货，不是生鲜豆角那一堆。 */
  ["主食", /红薯粉|土豆粉|藕粉|肠粉|贝果|玉米面|小米面|玉米片|汉堡胚|春卷|油条|麻花|馓子|锅巴|粽子|黄豆|绿豆|红豆|黑豆|芸豆|鹰嘴豆|薏米|薏仁|藜麦|西米|荞麦|高粱|糙米|黑米|紫米|豆沙|法棍|欧包|餐包/],
  ["水果", /砂糖橘|砂糖桔|沙糖桔|牛油果|富士|青柠|青提|红提|黑提|奇异果/],
  /* ② 冷藏柜 / 饮品：牛奶 / 酸奶 / 黄油 / 豆浆。七区里没有乳品区，单独成条比乱塞好。 */
  ["其他", /牛奶|酸奶|芝士|奶酪|黄油|奶油|炼乳|豆浆|奶粉|豆奶|椰奶|米浆|燕麦奶|乳酸菌|奶昔|淡奶油|布丁/],
  /* ③ 调料：写在肉蛋与主食之前——「猪油」「鸡精」是调料，「米醋」「米酒」「淀粉」也不是米面。
        不写单字「油」：那样「油麦菜」「油菜」会被抢走；不写单字「椒」：那样青椒会被抢走。 */
  ["调料", /酱油|生抽|老抽|蚝油|食用油|橄榄油|菜籽油|花生油|玉米油|葵花籽油|大豆油|色拉油|调和油|香油|芝麻油|猪油|牛油|鸡油|鸭油|椰子油|藤椒油|辣椒油|花椒油|虾油|鱼露|豉油|味极鲜|料酒|黄酒|米酒|白酒|啤酒|花雕|高汤|底料|香锅|盐|糖|醋|酱|花椒|胡椒|麻椒|藤椒|辣椒粉|辣椒面|辣椒酱|椒盐|剁椒|泡椒|干辣椒|五香|孜然|咖喱|肉桂|桂皮|八角|香叶|丁香|十三香|芥末|腐乳|豆豉|豆瓣|淀粉|生粉|泡打粉|苏打|酵母|芝麻|味精|鸡精|蜂蜜|柠檬汁|姜粉|姜黄|蒜粉|卤水|卤汁|食用碱|吉利丁|香草精|榨菜|酸菜|泡菜|酸豆角|腌菜/],
  /* ④ 坚果 / 干货：在零食干货架，不跟水果（桃 / 杏 / 果）也不跟米面走。
        必须排在③之后：「花生酱」「花生油」是调料，裸「花生」才是干货。
        干果 / 银耳 / 竹荪同理：买的时候是干货，跟香菇木耳那种带水气的不在一处。 */
  ["其他", /核桃|腰果|杏仁|开心果|花生|瓜子|松子|榛子|巴旦木|碧根果|夏威夷果|果仁|葵花籽|南瓜子|西瓜子|葡萄干|蔓越莓干|芒果干|猕猴桃干|草莓干|香蕉干|桂圆干|红枣干|枸杞|阿胶枣|话梅|陈皮|银耳|竹荪|黄花菜|梅干菜|笋干|香菇干|干香菇|木耳干/],
  /* ⑤ 水产：在海鲜 / 水产干货区。紫菜与海带在这一区，所以排在蔬菜之前。
        花甲 / 蛏子 / 青口 / 花螺都是贝类，字面上谁也不带「贝」字，得点名。 */
  ["水产", /鱼|虾|蟹|贝|蛤|螺|鱿|海带|紫菜|海参|蚝|蛏|蚬|蚌|鲍|蜇|鳝|鳗|鲈|鳕|鲤|鲫|鲳|鲅|鳜|鲢|鳙|裙带菜|海白菜|海苔|墨斗|章鱼|花甲|青口|带子|北极贝|田螺|海米|虾米/],
  /* ⑥ 水果：只写果名，不写单字「瓜」——不然南瓜 / 冬瓜 / 黄瓜全成水果。
        排在蔬菜之前：「牛油果」「鸭梨」的名字里带着肉蛋区的字。 */
  ["水果", /苹果|香蕉|橙|橘|梨|桃|莓|葡萄|提子|西瓜|哈密瓜|香瓜|甜瓜|木瓜|柠檬|芒果|菠萝|凤梨|枣|柚|杏|李|樱桃|车厘子|石榴|枇杷|山楂|桑葚|杨梅|荔枝|龙眼|桂圆|椰子|甘蔗|榴莲|山竹|火龙果|百香果|无花果|猕猴桃|莲雾|释迦|杨桃|蔓越莓|青梅|西梅|梅子|乌梅|柿子|柿/],
  /* ⑦ 蔬菜：在生鲜区。排在主食与肉蛋之前——「包菜」是菜不是包，「豇豆」不是豆制品的豆，
        「姜」不是「生姜粉」那种调料（粉那一条在③，先判掉了）。 */
  ["蔬菜", /菜|瓜|豆|葱|姜|蒜|椒|辣|茄|萝卜|土豆|藕|菇|菌|蘑|笋|芹|薯|芋|葵|茭|苗|苔|薹|芽|耳|荪|西兰|西蓝|芥|莼|荠|蒿|苋|韭|甘蓝|番茄|西红柿|玉米|山药|松茸|椿|莴|芦|葫芦|圣女果|荆条/],
  /* ⑧ 主食：在米面粮油区。排在肉蛋之前——「肠粉」不是肠，「鱼香」不在这一层判。 */
  ["主食", /米|面|粉|饭|馒头|面包|饼|年糕|糕|饺|馄饨|云吞|馍|团|燕麦|麦|烙|包|粉丝|粉条|粉皮|凉皮|汤圆|元宵|吐司/],
  /* ⑨ 肉蛋：在生鲜肉柜 / 蛋品区。 */
  ["肉蛋", /肉|鸡|鸭|鹅|猪|牛|羊|排骨|排|蹄|翅|腿|蛋|培根|火腿|香肠|里脊|肘|肋|肝|腰|肚|肠|丸|腊|骨|胗|掌|爪|舌|腩|腱|鸽/],
];
function marketKindOf(name) {
  const n = String(name || "");
  for (const [kind, re] of MARKET_RULES) { if (re.test(n)) return kind; }
  return "其他";
}

/** 「按货架排 / 按加入时间排」。界面偏好，不进 state：
 *  它描述的是「我现在在超市还是在厨房」，换台设备不该把它带过去。 */
let marketSort = "shelf";

/** 把一行「鸡蛋 2 个」拆成 {name, qty}。拆不出来就整行当名字、数量空着。 */
function parseMarketItem(line) {
  const s = String(line || "").trim();
  if (!s) return null;
  // 「名字 + 空格 + 数量」，数量可以是 2 / 2个 / 200克 / 半斤
  const m = s.match(/^(.+?)[\s:：]+([\d.]+)\s*([^\d\s]{0,4})$/);
  if (m) return { name: m[1].trim().slice(0, 30), qty: (m[2] + m[3]).trim() };
  return { name: s.slice(0, 30), qty: "" };
}

/** 数量的「单位」：`2 个` → 个，`200 克` → 克，`2` → ""（没有单位）。
 *  合并判定与界面上的说明都用它——两处各写一份的话，迟早一个说「合并了」一个说没合并。 */
function qtyUnit(q) {
  const m = String(q || "").match(/[^\d.\s]+$/);
  return m ? m[0] : "";
}
function qtyNum(q) {
  const n = parseFloat(String(q || ""));
  return Number.isFinite(n) ? n : NaN;
}

/** 合并的同一条规矩：名字与数量**同时**相同才合并数量；
 *  名字相同、数量不同（或一方没写）时并排成「2 个 + 3 个」，不替用户做加法。
 *  返回实际新增的条数（全部已经在清单里时返回 0）。 */
function addMarketItems(items, from) {
  const list = state.market || (state.market = []);
  let added = 0;
  (items || []).forEach((raw) => {
    const it = typeof raw === "string"
      ? parseMarketItem(raw)
      : { name: String((raw && raw.name) || "").trim(), qty: String((raw && raw.qty) || "").trim() };
    if (!it || !it.name) return;
    const same = list.find((x) => !x.done && x.name === it.name);
    if (same) {
      const u1 = qtyUnit(same.qty), u2 = qtyUnit(it.qty);
      const n1 = qtyNum(same.qty), n2 = qtyNum(it.qty);
      if (u1 === u2 && Number.isFinite(n1) && Number.isFinite(n2)) {
        // 同单位相加：`2 个` + `3 个` = `5 个`
        same.qty = String(n1 + n2) + u1;
      } else if (it.qty && same.qty !== it.qty) {
        // 不同单位并排：`200 克` + `2 个` 写成「200 克 + 2 个」——硬加就是一句假话
        same.qty = same.qty ? `${same.qty} + ${it.qty}` : it.qty;
      }
      return;
    }
    list.push({
      id: "m" + newId().slice(1), name: it.name, kind: marketKindOf(it.name),
      qty: it.qty || "", done: false, t: Date.now(), from: String(from || "").slice(0, 20),
    });
    added++;
  });
  if (added) {
    save(state);
    renderMarket();
    if (typeof paintTabCounts === "function") paintTabCounts();
  }
  return added;
}

/* ==================== 买菜那一页 ==================== */

/** 一行。勾选框在 label 里（整行可点），删在右边——两个动作各自有足够的命中区。 */
function marketRowHTML(x) {
  return `<label class="mrow${x.done ? " done" : ""}">
      <input type="checkbox" data-mcheck="${esc(x.id)}" ${x.done ? "checked" : ""}
             aria-label="${esc(x.done ? "已经拿到" : "还没买")}：${esc(x.name)}">
      <span class="grow"><b>${esc(x.name)}</b>${x.qty ? ` <span class="tiny">${esc(x.qty)}</span>` : ""}
        ${x.from ? `<span class="tiny"> · ${esc(x.from)}</span>` : ""}</span>
      <button class="chip hdel" data-mdel="${esc(x.id)}" type="button"
              aria-label="从清单删掉 ${esc(x.name)}">删</button>
    </label>`;
}

/** 按货架分组：只在同一档里保持「先进先出」，档与档之间按超市动线。
 *  稳定性来自两条：MARKET_KINDS 的声明序、以及每档之内按 t 再按 id（同一毫秒加入的两条也不抖）。 */
function marketGroups(arr) {
  const g = {};
  arr.forEach((x) => { (g[x.kind] = g[x.kind] || []).push(x); });
  MARKET_KINDS.forEach((k) => {
    if (g[k]) g[k].sort((a, b) => (a.t - b.t) || String(a.id).localeCompare(String(b.id)));
  });
  return MARKET_KINDS.filter((k) => g[k]).map((k) => ({ kind: k, items: g[k] }));
}

function renderMarket() {
  const host = $("#marketList");
  const note = $("#marketNote");
  if (!host) return;
  lockMarketBindings();
  const list = state.market || [];
  if (!list.length) {
    if (note) note.textContent = "";
    host.innerHTML = `<div class="empty"><div class="empty-印" aria-hidden="true">买</div>
      清单还是空的。<br>从菜谱详情页点「去记要买」，或者自己在上面加一条。</div>`;
    return;
  }
  const open = list.filter((x) => !x.done);
  const done = list.filter((x) => x.done);
  if (note) {
    note.textContent = open.length
      ? `还差 ${open.length} 样${done.length ? `，已经拿到 ${done.length} 样` : ""}。`
      : `都买齐了。${done.length} 样全在篮子里。`;
  }

  const sortBar = `<div class="bar mkt-sort" style="margin:0 0 10px">
    <div class="seg" role="group" aria-label="清单怎么排">
      <button type="button" data-msort="shelf" aria-pressed="${marketSort === "shelf"}">按货架排</button>
      <button type="button" data-msort="time" aria-pressed="${marketSort === "time"}">按加入时间</button>
    </div>
  </div>`;

  const body = marketSort === "time"
    ? `<p class="tiny" style="margin:10px 0 6px">按加入时间 · ${open.length} 样还没买</p>
       <div class="list">${open.slice().sort((a, b) => b.t - a.t).map(marketRowHTML).join("")}</div>`
    : marketGroups(open).map((g) => `<p class="tiny" style="margin:14px 0 6px">${g.kind} · ${g.items.length}</p>
       <div class="list">${g.items.map(marketRowHTML).join("")}</div>`).join("");

  const doneHTML = done.length
    ? `<p class="tiny" style="margin:16px 0 6px">已经拿到 · ${done.length}</p>
       <div class="list">${done.slice().sort((a, b) => b.t - a.t).map(marketRowHTML).join("")}</div>
       <div class="space"></div>
       <button class="btn ghost wide" id="marketClear" type="button">清掉已拿到的 ${done.length} 样</button>`
    : "";

  host.innerHTML = sortBar + body + doneHTML;

  $$("#marketList [data-msort]").forEach((b) => {
    b.onclick = () => { marketSort = b.dataset.msort === "time" ? "time" : "shelf"; renderMarket(); };
  });
  $$("#marketList [data-mcheck]").forEach((cb) => {
    cb.onchange = () => {
      const x = state.market.find((y) => y.id === cb.dataset.mcheck);
      if (!x) { renderMarket(); return; }
      const was = x.done;
      x.done = cb.checked;
      // 勾掉是「拿到了一样东西」，记一笔；取消勾掉不是一件事，不记
      if (x.done && !was) logEvent("market", "wei", x.name);
      save(state);
      renderMarket();
      paintTabCounts();
      haptic("LIGHT");
      if (x.done) toast(`拿到「${x.name}」`);
    };
  });
  $$("#marketList [data-mdel]").forEach((b) => {
    b.onclick = (ev) => {
      ev.preventDefault();           // 这一枚在 <label> 里：不拦的话点「删」会顺手把勾选框点一下
      const i = state.market.findIndex((y) => y.id === b.dataset.mdel);
      if (i < 0) { renderMarket(); return; }
      const snap = state.market[i];
      state.market.splice(i, 1);
      save(state);
      renderMarket();
      paintTabCounts();
      toastUndo(`已删掉「${snap.name}」`, () => {
        state.market.splice(Math.min(i, state.market.length), 0, snap);
        save(state);
        renderMarket();
        paintTabCounts();
      });
    };
  });
  const clr = $("#marketClear");
  if (clr) clr.onclick = () => {
    const gone = state.market.filter((x) => x.done);
    if (!gone.length) { toast("还没有拿到的可以清"); return; }
    state.market = state.market.filter((x) => !x.done);
    save(state);
    renderMarket();
    paintTabCounts();
    toastUndo(`已清掉 ${gone.length} 样拿到的`, () => {
      state.market = state.market.concat(gone);
      save(state);
      renderMarket();
      paintTabCounts();
    });
  };
}

/** 页签上那两枚常驻控件（输入框 + 加上）。app.js 在 boot 里绑过一次，
 *  这里每次重画再绑一次——整片重建之后旧节点被丢弃，不重绑就是「点一次之后失效」。 */
function lockMarketBindings() {
  const add = $("#addMarket");
  if (add) add.onclick = () => {
    const el = $("#marketName");
    const v = String((el && el.value) || "").trim();
    if (!v) { toast("先写要买什么"); if (el) el.focus(); return; }
    const it = parseMarketItem(v);
    const n = addMarketItems([v], "");
    if (el) el.value = "";
    if (n) { toast(`加进清单了：${it.name}${it.qty ? " " + it.qty : ""}`); haptic("LIGHT"); }
    else toast(`「${it.name}」已经在清单里，数量并到一起了`);
    paintTabCounts();
  };
  const inp = $("#marketName");
  if (inp) inp.onkeydown = (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const b = $("#addMarket");
    if (b) b.click();
  };
}
