/** 笺 · 衣笺
   柜子渲染、首屏输入槽、过笺与报告页。长图的绘制在 card.js，这里只管发起。 */

/* ---------- 衣笺 ---------- */

function swatchEl(color, img) {
  const src = cssImg(img);
  // cssImg() 返回的已经是「可以原样放进 src="…"」的值（它自己会把引号与尖括号转掉）。
  // 在这里再 esc 一次就变成双重转义：地址里带 & 的会被写成 &amp;amp;，图片直接加载不出来。
  if (src) return `<img src="${src}" alt="">`;
  return `<div class="swatch" style="background:${cssColor(color)}"></div>`;
}

function renderCats() {
  const box = $("#yiCats");
  if (!box) return;
  // 这一排签是整片重建的，而且它跑在 renderCloset 那次 restoreFocus **之后**（paintCloset
  // 的末尾），所以外层那一次找回救不了它：键盘用户按一次 Enter 选中「外套」，焦点就掉回 body，
  // Tab 得从页首再走一遍。四个模块里只有它漏了这一手。
  const fk = focusKey();
  box.innerHTML = CATS.map((c) =>
    `<button class="chip ${state.yiCat === c ? "on" : ""}" data-cat="${c}" aria-pressed="${state.yiCat === c}">${c}</button>`
  ).join("");
  $$("#yiCats [data-cat]").forEach((b) => {
    b.onclick = () => { state.yiCat = b.dataset.cat; save(state); renderCats(); };
  });
  restoreFocus(fk);
}

/**
 * 柜子的搜索词。故意不写进 state：开机看见一条自己没点过的过滤，比不记更烦，
 * 而它本来就是「这一眼没找到」的临时工具，不是偏好。
 */
function closetQuery() {
  const el = $("#clothSearch");
  return el ? el.value.trim().toLowerCase() : "";
}

/**
 * 柜子的三种筛法叠在一起：季节 → 搜索 → 排序。
 * 叠加季节筛选：选中某季 S，显示 seasonOf(w)===S 或「四季」的衣物；「全部」不过滤。
 * 搜索匹配名字或品类，去空白后大小写不敏感（柜子里有「UNIQLO 白 T」这种混写）。
 * 老数据没有 season 字段，Engine.seasonOf 现场推断，不必回写。
 */
function closetList() {
  const season = state.closetSeason || "all";
  let base = season === "all"
    ? [...state.wardrobe]
    : state.wardrobe.filter((w) => {
        const s = Engine.seasonOf(w);
        return s === season || s === "四季";
      });
  const q = closetQuery();
  if (q) base = base.filter((w) => (w.name + " " + w.cat + " " + (w.brand || "") + " "
    + (w.tags || []).join(" ") + " " + (w.occasions || []).join(" ")).toLowerCase().includes(q));
  const list = [...base];
  if (state.closetSort === "idle") {
    list.sort((a, b) => (a.lastWorn || 0) - (b.lastWorn || 0));
  } else if (state.closetSort === "new") {
    // 「最近买」：按购入日倒序；没记购入日的排在后面（不拿入柜时间冒充购入时间）
    list.sort((a, b) => (b.boughtAt || 0) - (a.boughtAt || 0) || (b.lastWorn || 0) - (a.lastWorn || 0));
  } else if (state.closetSort === "cpw") {
    // 「单次成本」：贵的在前。算不出来的（没价格 / 还没穿过）排在最后，因为它们没有数可比，
    // 把它们混进排序里等于拿「算不出来」当成「最便宜」。
    const rank = (w) => {
      const c = typeof cpw === "function" ? cpw(w) : null;
      return Number.isFinite(c) ? c : -1;
    };
    list.sort((a, b) => rank(b) - rank(a));
  } else {
    list.sort((a, b) => (b.worn || 0) - (a.worn || 0) || (b.lastWorn || 0) - (a.lastWorn || 0));
  }
  return list;
}

/**
 * 首屏那块大纸是「要过笺的那件」的槽位，不是装饰。
 * 以前它固定显示柜子里第一件，于是屏幕上最大的元素讲的是另一件衣服，
 * 而你刚选的那张图从头到尾没在那儿出现过。没选之前，它就是「点这里放照片」。
 */
function paintHero() {
  const box = $("#heroCloth");
  if (!box) return;
  const it = state.lastNew;
  if (it && (it.img || it.color)) {
    box.classList.remove("asking");
    $("#heroInner").innerHTML = swatchEl(it.color, it.img);
    // 标一句「换一张」，否则这张照片会一直赖在首屏，看不出还能改
    const nm = it.name || "想买的这件";
    $("#heroName").innerHTML = `${esc(nm)}<span class="swap">换一张</span>`;
    box.setAttribute("aria-label", `换一张照片，当前是${nm}`);
  } else {
    box.classList.add("asking");
    box.setAttribute("aria-label", "选一张想买的衣服照片");
    $("#heroInner").innerHTML = "";
    $("#heroName").textContent = "";
  }
}

/** 今天穿过的：按**同一个日历天**算，不是「24 小时之内」。
 *  昨晚 23 点记的那件，今天下午不该还算在今天；日界口径只有 dayStr 一处。
 *  这里只看 lastWorn 不看 worn，靠的是 normCloth 那条「0 次就没有最后一次」的钳位
 *  （state.js）——两件字段要是能各说各话，这一行就会把一件瓷砖上写着「还没穿过」的
 *  衣服列进「今天穿了」。 */
function wornToday() {
  const t = dayStr(Date.now());
  return state.wardrobe.filter((w) => w.lastWorn && dayStr(w.lastWorn) === t);
}

function closetNote() {
  const el = $("#closetNote");
  if (!el) return;
  const all = state.wardrobe;
  if (!all.length) { el.textContent = ""; return; }
  const list = closetList();
  const cutoff = Date.now() - 90 * DAY;
  const never = all.filter((w) => !w.lastWorn).length;
  const stale = all.filter((w) => w.lastWorn && w.lastWorn < cutoff).length;
  const parts = [`柜里 ${all.length} 件`];
  if (never) parts.push(`${never} 件还没穿过`);
  if (stale) parts.push(`${stale} 件超过 3 个月没动`);
  if (parts.length === 1) parts.push("都在穿");
  // 搜索生效时把命中数报出来：筛完只剩两件、摘要还写「柜里 20 件」，等于没说
  const q = closetQuery();
  if (q) parts.push(`搜「${q}」${list.length} 件`);
  // 统计一句、提示一句：全挤成一行会被屏幕右边缘切掉半句
  const line1 = parts.join(" · ") + (state.closetSort === "idle" ? "（按久未穿排）" : "（按常穿排）");
  const line2 = all.every((w) => /^w[1-6]$/.test(w.id)) ? "示例柜子，点 ＋ 换成自己的" : "";
  // 第三行回答一句这柜子本来就答得出的话：今天穿了什么。以前 `今天穿了` 记进去了，
  // 但全 App 没有任何一处答得出来——想知道就得自己翻 36 块瓷砖找哪枚写着「上次 今天」。
  const today = wornToday();
  // 名字最多点三个，其余收进「等 N 件」：20 字的名字排五个会在 360 上把签撑成横幅
  // （和第 16 轮那堵签墙同一件事，那条也是量出来的不是看着顺眼）。
  const shown = today.slice(0, 3);
  const line3 = today.length
    ? `今天穿了：${shown.map((w) => `<button type="button" class="chip" data-worn="${esc(w.id)}"` +
        ` aria-label="选中今天穿的这件：${esc(w.name)}">${esc(w.name)}</button>`).join("")}` +
      (today.length > shown.length ? `等 ${today.length} 件` : "")
    : "今天还没记穿了什么。柜里那件的操作条上有「今天穿了」。";
  el.innerHTML = `<span>${esc(line1)}</span>` + (line2 ? `<span>${esc(line2)}</span>` : "")
    + `<span>${line3}</span>`;
  $$("#closetNote [data-worn]").forEach((b) => {
    b.onclick = () => {
      const id = b.dataset.worn;
      const w = state.wardrobe.find((x) => x.id === id);
      if (!w) return;
      // 带着搜索或季节筛时点一个被筛掉的名字 = 点了没反应。第 22 轮「带着搜索入柜」
      // 同一条规矩：把筛清掉，别让用户对着一行字找自己。
      if (!closetList().some((x) => x.id === id)) {
        state.closetSeason = "all";
        const s = $("#clothSearch"); if (s) s.value = "";
      }
      state.clothSel = id; save(state); renderCloset();
      scrollToClothActions();
      toast(`已选中「${w.name}」`);
    };
  });
}

function wornBadge(w) {
  if (!w.worn) return "";
  const idle = w.lastWorn && Date.now() - w.lastWorn > 90 * DAY;
  const n = esc(w.worn);
  return `<span class="worn ${idle ? "idle" : ""}" title="穿过 ${n} 次">${n}</span>`;
}

/** 瓷砖给读屏器念的那一句。改名之后要重算，所以抽出来一处。 */
const tileLabel = (w) => `${w.name}，${w.cat}${w.worn ? "，穿过 " + w.worn + " 次" : "，还没穿过"}`;

/** 柜子的外壳：先把焦点身份记下来，再让 paintCloset 整片重建，最后按身份找回。
 *  （四个模块都是 innerHTML 重建，键盘用户不该每点一下就掉回页首。） */
function renderCloset() {
  const fk = focusKey();
  paintCloset();
  restoreFocus(fk);
}

function paintCloset() {
  const box = $("#closet");
  if (!box) return;
  // 季节 chips 选中态同步，仿 [data-closet] 的写法
  $$("[data-season]").forEach((b) => {
    const on = (b.dataset.season || "all") === (state.closetSeason || "all");
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
  });
  // 排法那两枚必须和季节签一样**在早退之前**刷。以前它写在函数末尾，而两支空态
  // （筛空了 / 柜里真没东西）都在它前面 return：于是柜里空着时点「久未穿」，
  // state 改了、上面那行 closetNote 也跟着改口，唯独签上还亮着「常穿」——
  // 同一屏上两个面互相打脸。这一处是 dead_controls 的「空态」那一趟抓出来的。
  $$("[data-closet]").forEach((b) => {
    const on = b.dataset.closet === state.closetSort;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
  });
  const list = closetList();
  const q = closetQuery();
  if (!list.length && state.wardrobe.length) {
    // 柜里不是空的，只是这一筛筛空了——三种空态要说清各自的原因，别都写成「柜子是空的」
    const why = q
      ? `柜里搜不到「${esc(q)}」。<br>换个词，或 <button type="button" class="chip" id="clearSearch">清掉搜索</button>`
      : "这一季没有衣物。<br>换一个季节，或点上面的「全部」。";
    box.innerHTML = `<div class="empty">${why}</div>`;
    $("#clothActions").innerHTML = "";
    closetNote();
    renderCats();
    const cs = $("#clearSearch");
    if (cs) cs.onclick = () => { $("#clothSearch").value = ""; renderCloset(); $("#clothSearch").focus(); };
    return;
  }
  if (!list.length) {
    // 这句以前写到「过笺才准」，而那一支里根本不画 ＋：删掉最后一件之后，屏上叫你做的事
    // 在这块屏上没有入口（唯一的出路是先去「过笺」——那还要扣点）。门槛第 21 轮在引擎
    // 那句里改掉了，这一句是同一句话的**第二份拷贝**，漏了。两份现在合成一份。
    box.innerHTML = `<div class="empty">柜里还空着。<br>放几件常穿的进来，过笺才有得比。<br>`
      + `<button type="button" class="chip" id="addCloth" aria-label="入柜">＋ 放第一件</button></div>`;
    $("#clothActions").innerHTML = "";
    closetNote();
    renderCats();
    $("#addCloth").onclick = () => $("#fileCloth").click();
    return;
  }
  box.innerHTML = list.map((w) => `
    <div class="item ${state.editCloset ? "edit" : ""} ${state.clothSel === w.id ? "sel" : ""}"
         data-id="${esc(w.id)}" role="button" tabindex="0"
         aria-label="${esc(tileLabel(w))}">
      ${swatchEl(w.color, w.img)}
      ${wornBadge(w)}
      <div class="tag">${esc(w.name)}</div>
    </div>`).join("") + `<button class="item add" id="addCloth" aria-label="入柜">＋</button>`;

  $("#addCloth").onclick = () => $("#fileCloth").click();
  $$("#closet .item[data-id]").forEach((el) => {
    const act = () => {
      const id = el.dataset.id;
      if (state.editCloset) {
        const at = state.wardrobe.findIndex((w) => w.id === id);
        const [gone] = state.wardrobe.splice(at, 1);
        if (state.clothSel === id) state.clothSel = null;
        save(state); renderCloset();
        toastUndo(`已去掉「${gone.name}」`, () => {
          state.wardrobe.splice(Math.min(at, state.wardrobe.length), 0, gone);
          save(state); renderCloset();
        });
        return;
      }
      state.clothSel = state.clothSel === id ? null : id;
      save(state); renderCloset();
      // 取消选中不用带人去任何地方；选中了就得看见那块编辑器
      if (state.clothSel) scrollToClothActions();
    };
    el.onclick = act;
    el.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); }
    };
  });

  const ed = $("#editCloset");
  if (ed) {
    ed.textContent = state.editCloset ? "完成" : "整理";
    ed.classList.toggle("on", state.editCloset);
  }
  paintHero();
  closetNote();
  renderClothActions();
  renderCats();
}

/**
 * 选中一件之后把那块编辑器带到眼前。编辑器挂在整张网格底下：柜子里 36 件时它离首屏
 * 隔着六屏（360×720 实测），点下去既没有滚动也没有别的反馈，等于「点了没反应」——
 * 这是第 44 轮同一把尺量出来的第三处「动作埋在它所作用的列表底下」。
 * 不滚到刚点的那一格：那格就是用户手指头指着的位置，本来就在视野里；
 * 而编辑器头上就写着这件的名字和色块，认得出是哪一件。
 */
function scrollToClothActions() {
  const bar = $("#clothActions .action-bar");
  if (bar) bar.scrollIntoView({ block: "start" });
}

/** 点中一件衣服后，在柜子下方出现这条，不弹窗、不遮屏。名字、品类、季节都在这里改。 */
function renderClothActions() {
  const box = $("#clothActions");
  if (!box) return;
  const w = state.wardrobe.find((x) => x.id === state.clothSel);
  if (!w) { box.innerHTML = ""; return; }
  const last = relativeDays(w.lastWorn);
  const line = w.worn ? `穿过 ${w.worn} 次 · 上次 ${last}` : "还没穿过";
  const cur = Engine.seasonOf(w);   // 老数据没有 season 就现场推断，点一下即落库
  box.innerHTML = `
    <div class="action-bar">
      <div class="action-head">
        <div class="swatch-sm" style="background:${cssColor(w.color)}"></div>
        <div>
          <b>${esc(w.name)}</b>
          <div class="tiny">${esc(w.cat)} · ${line}</div>
        </div>
        <button type="button" class="chip yi-archive" id="openItemBtn"
                aria-label="打开「${esc(w.name)}」的完整档案：价格、购入日、穿着日历">档案</button>
      </div>
      <div class="tiny" style="margin-top:12px">上次穿 <span class="who-none">判「久未穿」就按这一天；记错了在这儿改，不用删了重录</span></div>
      <div class="chips" style="margin-top:6px">
        ${WEAR_DAY_CHIPS.map((d) =>
          `<button type="button" class="chip" data-wear-day="${d}" aria-label="上次穿改成${d}">${d}</button>`
        ).join("")}
        <span class="datepick">挑一天<input type="date" id="clothWornDay" aria-label="上次穿改到某一天"
               value="${w.lastWorn ? isoDay(w.lastWorn) : ""}"></span>
      </div>
      <div class="tiny" style="margin-top:12px">穿过几次 <span class="who-none">一次 = 一天；减到 0 就是「还没穿过」，那天跟着一起清掉</span></div>
      <div class="chips" style="margin-top:6px">
        <button type="button" class="chip" id="wearDown" aria-label="次数减一" aria-disabled="${!w.worn}">−1</button>
        <button type="button" class="chip" id="wearUp" aria-label="次数加一">＋1</button>
      </div>
      <div class="tiny" style="margin-top:12px">名字</div>
      <input type="text" id="clothName" value="${esc(w.name)}" maxlength="20"
             placeholder="给这件起个名" aria-label="改名" style="margin-top:6px" />
      <div class="tiny" style="margin-top:12px">品类</div>
      <div class="chips" style="margin-top:6px">
        ${CATS.map((c) =>
          `<button class="chip ${w.cat === c ? "on" : ""}" data-item-cat="${c}" aria-pressed="${w.cat === c}">${c}</button>`
        ).join("")}
      </div>
      <div class="tiny" style="margin-top:12px">穿的季节</div>
      <div class="chips" style="margin-top:6px">
        ${SEASON_OPTS.map((s) =>
          `<button class="chip ${cur === s ? "on" : ""}" data-item-season="${s}" aria-pressed="${cur === s}">${s}</button>`
        ).join("")}
      </div>
      <div class="tiny" style="margin-top:12px">主色 <span class="who-none">判定就按这个色和柜子比；照片里取错了，在这儿改</span></div>
      <div class="colorrow">
        <input type="color" id="clothColor" value="${hex6(w.color)}" aria-label="改这件的主色" />
        <span class="hex" id="clothHex">${esc(hex6(w.color))}</span>
      </div>
      <div class="tiny" style="margin-top:12px">照片 <span class="who-none">${w.img
        ? "换一张；只换照片，名字、品类、季节、主色、穿着记录都不动"
        : "本机放不下时照片会被清掉，这里能补回来"}</span></div>
      <div class="row" style="margin-top:6px">
        <button class="btn ghost" id="rephotoBtn">相册补图</button>
        <button class="btn ghost" id="recamBtn">现拍一张</button>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn ghost" id="wearIt">今天穿了</button>
        <button class="btn ghost" id="dropIt">从柜里去掉</button>
      </div>
    </div>`;
  // 第 21 轮那句「重新拍照能补上」当时没有入口：唯一的出路是删掉重入柜，
  // 而删掉正好毁掉同一句话承诺「还在」的穿着记录。这两枚按钮把那句话兑现。
  $("#rephotoBtn").onclick = () => { haptic("LIGHT"); $("#fileRephoto").click(); };
  $("#recamBtn").onclick = () => { haptic("LIGHT"); $("#fileRecam").click(); };
  // 「档案」：柜子里只有一条路能看见这件衣服的全部（价格、购入日、穿着日历）。
  // 长按/双击在 WebView 里不可发现，所以入口做成操作条上一枚明写的签。
  const oi = $("#openItemBtn");
  if (oi) oi.onclick = () => { if (typeof openItem === "function") openItem(w.id); };
  $("#wearIt").onclick = () => { const before = w.worn || 0; wearNow(w.id); if (typeof afterWearAction === "function") afterWearAction(w, before); };
  $$("#clothActions [data-wear-day]").forEach((b) => {
    b.onclick = () => { const before = w.worn || 0; wearSetDay(w, wearDayFromLabel(b.dataset.wearDay).at, b.dataset.wearDay); if (typeof afterWearAction === "function") afterWearAction(w, before); };
  });
  const wd = $("#clothWornDay");
  wd.onchange = () => {
    const d = whenFromDate(wd.value);
    // 没挑完（年/月/日只填了一半）不改，别把原来记着的那天抹掉——与言笺「改时间」同一条判据。
    // 挡下来必须说：不然用户以为「这日期框点了没反应」（第 58 轮那条规矩）。
    if (!d) { toast("日期没填全，上次穿先不动；要记成还没穿过就把次数减到 0"); return; }
    if (d.at > Date.now()) {
      // 未来的那一天还没发生，不能当「最后一次」——它会让久未穿那一层反向少算，
      // 而 normCloth 要在下次开机才把它钳回来，这一屏就摆着一条假账。当场挡，
      // 并把框里弹回真记着的那一天：留着 2027 年在那儿，就是屏幕上两个面打脸。
      wd.value = w.lastWorn ? isoDay(w.lastWorn) : "";
      toast("还没到的那一天不算穿过，上次穿先不动");
      return;
    }
    wearSetDay(w, d.at, d.text);
  };
  $("#wearDown").onclick = () => { const before = w.worn || 0; wearBump(w, -1); if (typeof afterWearAction === "function") afterWearAction(w, before); };
  $("#wearUp").onclick = () => { const before = w.worn || 0; wearBump(w, 1); if (typeof afterWearAction === "function") afterWearAction(w, before); };
  $("#dropIt").onclick = () => {
    const at = state.wardrobe.findIndex((x) => x.id === w.id);
    state.wardrobe.splice(at, 1);
    state.clothSel = null;
    save(state); renderCloset();
    if (typeof paintTabCounts === "function") paintTabCounts();
    if (typeof renderWardrobeStats === "function") renderWardrobeStats();
    toastUndo(`已从柜里去掉「${w.name}」`, () => {
      state.wardrobe.splice(Math.min(at, state.wardrobe.length), 0, w);
      save(state); renderCloset();
      if (typeof paintTabCounts === "function") paintTabCounts();
      if (typeof renderWardrobeStats === "function") renderWardrobeStats();
    });
  };
  const nm = $("#clothName");
  nm.onchange = () => {
    const v = nm.value.trim().slice(0, 20);
    // 清空名字会把文字弹回原名 —— 界面动了一下、动的方向像 bug，比一动不动更糟。
    // 所以这一路也要说清是谁把它改回去的。（同名那条保持静默：改了个一模一样的
    // 名字本来就不该有第二种结果，见 #16 里那段判定。）
    if (!v) { nm.value = w.name; toast("名字不能空着，已填回原来那个"); return; }
    if (v === w.name) return;
    w.name = v; save(state);
    // 就地改这三处，不重建整片。重建会把焦点从正在改名的输入框里抢走，
    // 用 Tab 提交时还会「重建 → 焦点按身份找回同一个输入框」转成死循环。
    const tile = $(`#closet .item[data-id="${CSS.escape(w.id)}"]`);
    if (tile) {
      tile.querySelector(".tag").textContent = v;
      tile.setAttribute("aria-label", tileLabel(w));
    }
    const head = $("#clothActions .action-head b");
    if (head) head.textContent = v;
    toast("已改名");
  };
  $$("#clothActions [data-item-cat]").forEach((b) => {
    b.onclick = () => {
      const c = b.dataset.itemCat;
      if (w.cat === c) return;
      w.cat = c;                       // 手改过的 season 保留；没改过的会按新品类重新推断
      save(state); renderCloset();
      toast(`已归到「${c}」`);
    };
  });
  $$("#clothActions [data-item-season]").forEach((b) => {
    b.onclick = () => {
      w.season = b.dataset.itemSeason;
      save(state); renderCloset();
    };
  });
  const cc = $("#clothColor");
  cc.onchange = () => {
    const v = hex6(cc.value);
    if (v === hex6(w.color)) return;
    const before = w.color;
    w.color = v; save(state);
    // 就地改这几处，不重建整片：重建会把焦点从取色器里抢走（改名那条是同一个坑）。
    // 有照片的格子显示的是照片、不是这个色，所以照片那格不动——但判定吃的就是它。
    const head = $("#clothActions .action-head .swatch-sm");
    if (head) head.style.background = cssColor(v);
    const hx = $("#clothHex");
    if (hx) hx.textContent = v;
    const sw = $(`#closet .item[data-id="${CSS.escape(w.id)}"] .swatch`);
    if (sw && !sw.querySelector("img")) sw.style.background = cssColor(v);
    const tile = $(`#closet .item[data-id="${CSS.escape(w.id)}"]`);
    if (tile) tile.setAttribute("aria-label", tileLabel(w));
    // 报告是拿旧色算出来的，不说这一句，屏幕上就同时摆着「新色」和「按旧色下的章」
    toastUndo(`主色改成 ${v}${state.lastReport ? " · 这张笺还是改之前算的" : ""}`, () => {
      w.color = before; save(state); renderCloset();
    });
  };
}

/* ---------- 穿用记录：能被记下来就得能被改回去（第 59 轮） ----------
 * 这件衣服只有两个数可记，而它们不是各管各的：判定引擎直接吃它们
 * （engine.js 的 stale 与那句「柜里的『X』就是这个色，而且 N 个月没穿过了」），
 * 记错了又改不回来，等于一句劝告没有修正入口。口径三句话：
 * ① `worn` = 穿过几次，一次 = 一个**日历天**；`lastWorn` = 最后一次穿在哪一天。
 *    穿过至少一次才谈得上「最后一次」，所以 0 次 ⟺ 没有日子（钳位写在 state.js
 *    的 normCloth 里，摘要行「今天穿了」只看 lastWorn 就靠这条才不打脸）。
 * ② 凡按日子记的入口，同一个日历天只记一次：「今天穿了」点第二下不再 +1，
 *    「上次穿」改到已经记过的那天也不算数第二次。摘要行一件只列一次，
 *    这里若能加两次，同一屏上就是两个说法。
 * ③ 两格各修一件事，互不夹带：改「上次穿」只挪日子（修「哪一天记错了」——
 *    手滑记到今天往回挪、上周三忘了记往前补），次数另有 −1/＋1（修「几笔账」）。
 *    两处各有一个不得不带的例外，都是为了让 ① 成立：给 0 次这件补一个日子 =
 *    承认它穿过 → 次数记作 1；次数减到 0 = 还没穿过 → 那条日子一起清掉。
 */

/** 「上次穿」那几枚快捷签。只往前：往后的日子还没发生，摆一枚按下去永远只得到
 *  一句「先不动」的签是噪音（挡未来那天写在日期框那条路上）。三枚是量出来的：
 *  360 宽下这一排还要放「挑一天」+日期框，四枚就把日期框顶到下一行去凑墙。 */
const WEAR_DAY_CHIPS = ["今天", "昨天", "前天"];

/** 时间戳 → 日期控件认的 YYYY-MM-DD。只格式化：解析与月末钳位只有 whenFromDate 那一份。 */
function isoDay(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 快捷签 → 那一天的时刻。折成 YYYY-MM-DD 再交给 yan.js 的 whenFromDate，
 *  于是「签」与「挑一天」算出来的是同一个时刻，不会有第二份日界口径。 */
function wearDayFromLabel(label) {
  const back = { 今天: 0, 昨天: 1, 前天: 2 }[label] || 0;
  return whenFromDate(isoDay(Date.now() - back * DAY));
}

/** 口径②：这一件的账上有没有那一天。日界只有 dayStr 一处（与 wornToday 同一把尺）。 */
const wornOnThatDay = (w, at) => !!(w.lastWorn && dayStr(w.lastWorn) === dayStr(at));

/** 一次改动 = 一次写回 + 一次 save + 一次 renderCloset + 一次反悔。
 *  重画是必须的：角标、摘要行、瓷砖 aria-label、头上那行「穿过 N 次 · 上次 X」、
 *  柜子排序全都吃这两个数，就地改 class 只会让其中几处先动起来（第 58 轮那两处
 *  就是这么栽的）。撤销照快照填回去，一字不差。 */
function applyWear(w, next, msg) {
  const before = { worn: w.worn || 0, lastWorn: w.lastWorn || null };
  w.worn = next.worn;
  w.lastWorn = next.lastWorn;
  save(state); renderCloset();
  toastUndo(msg, () => {
    w.worn = before.worn; w.lastWorn = before.lastWorn;
    save(state); renderCloset();
  });
}

/** 改「上次穿」到某一天：只挪日子，不动次数（口径③）。 */
function wearSetDay(w, at, label) {
  if (wornOnThatDay(w, at)) {
    // 什么都没改，就不许冒出一条「撤销」——那是在暗示刚才动了什么。
    toast(`「${w.name}」上次穿就是${label}，同一天不记两遍`);
    return;
  }
  const first = !w.worn;   // 口径③的例外：补了日子 = 它被穿过过，0 次这件至少算一次
  applyWear(w, { worn: first ? 1 : w.worn, lastWorn: at },
    `「${w.name}」上次穿改成${label}` + (first ? " · 记作穿过 1 次" : ""));
}

/** 次数 ±1：只改几笔账，不动日子（口径③的另一半）。 */
function wearBump(w, d) {
  const worn = Math.max(0, (w.worn || 0) + d);
  if (worn === (w.worn || 0)) {
    toast(`「${w.name}」本来就没穿过，不能再减了`);
    return;
  }
  // 从 0 变成 1 时账上还没有任何日子，这一笔只能落在今天（0 次 ⟺ 没有日子，口径①），
  // 所以这里同时把日子记上，并说出来——用户要的不是今天就把上面那格改一下。
  const day = worn && !w.lastWorn ? Date.now() : (w.lastWorn || null);
  applyWear(w, { worn, lastWorn: worn ? day : null },
    `「${w.name}」` + (worn ? `记作穿过 ${worn} 次` : "记作还没穿过 · 那天一起清掉")
    + (worn && !w.lastWorn ? " · 日子记在今天，不对就在上面改" : ""));
}

function wearNow(id) {
  const w = state.wardrobe.find((x) => x.id === id);
  if (!w) return;
  if (wornOnThatDay(w, Date.now())) {
    // 同一天点两下从前是 +2，而摘要行「今天穿了」里它只出现一次——同一屏两个说法。
    toast(`今天已经记过「${w.name}」了，同一天不记两遍`);
    return;
  }
  // 记错了以前撤不回：次数永远多一次，而「久未穿」那条判定吃的就是 lastWorn——
  // 手滑点错一件，等于替它把 214 天没穿的账抹掉。
  applyWear(w, { worn: (w.worn || 0) + 1, lastWorn: Date.now() },
    `已记下：今天穿了「${w.name}」`);
}

function compress(img, max, q) {
  const canvas = document.createElement("canvas");
  const scale = Math.min(1, max / Math.max(img.width, img.height));
  canvas.width = Math.max(1, Math.round(img.width * scale));
  canvas.height = Math.max(1, Math.round(img.height * scale));
  canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", q);
}

function addClothFile(file) {
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const feat = Engine.analyze(img);
    const data = compress(img, 320, 0.72);
    const raw = file.name.replace(/\.[^.]+$/, "").slice(0, 10);
    const name = /^(IMG|DCIM|image|微信|mmexport|Screenshot|wx_camera)/i.test(raw) ? (state.yiCat || "新衣") : (raw || "新衣");
    const it = {
      id: newId(), name, cat: state.yiCat || "上衣",
      color: feat.color, img: data, worn: 0, lastWorn: null,
      season: Engine.seasonOf({ cat: state.yiCat || "上衣", name })
    };
    state.wardrobe.unshift(it);
    save(state); renderCloset(); toast("已入柜"); haptic("HEAVY");
    // 入柜是一件「真的发生了的事」：页签上的件数与那一柜的统计都得当场跟上，
    // 否则用户在柜子里看见 7 件、页签上还写着 6（同一屏两个数）。
    if (typeof paintTabCounts === "function") paintTabCounts();
    if (typeof renderWardrobeStats === "function") renderWardrobeStats();
    URL.revokeObjectURL(url);
    // 认一认：填了网关就把「IMG_1234 / 新衣」换成看得懂的名字与品类。
    // 先落柜再认——认不认得都不挡着用户继续做事；主色仍用本机量的（像素比猜的准）。
    // beginTurn() 不能省：它是另一次操作了。少了这一句，用户上一次按「先不等了」
    // 会一路管下来，把这里也变成「根本不问网关」，而界面上一个字都不会说。
    JianAPI.beginTurn();
    JianAPI.see(file).then((seen) => {
      if (!seen) return;
      const at = state.wardrobe.findIndex((w) => w.id === it.id);
      if (at < 0) return;                       // 这几秒里被删掉了，别把它加回来
      const w = state.wardrobe[at];
      if (seen.name && w.name === name) w.name = seen.name;
      if (seen.cat) w.cat = seen.cat;
      if (seen.season) w.season = seen.season;
      save(state); renderCloset();
      toast(`认出来了：「${w.name}」` + (w.cat ? ` · ${w.cat}` : ""));
    });
  };
  img.onerror = () => { toast("图片读不出来"); URL.revokeObjectURL(url); };
  img.src = url;
}

/** 给柜里已有的一件补一张照片。两处刻意：
 *  ① **主色不重取**——那一个值用户可能刚在上面那格手改过（第 21 轮的取色器），
 *     换照片不等于把手改盖掉；要改色另有一格。
 *  ② 压缩参数与入柜同一档（320 / 0.72）：本机配额就是按这个尺寸算的，
 *     补一张原图等于让第 21 轮那句「本机放不下」立刻再发生一次。 */
function rephotoCloth(file) {
  const w = state.wardrobe.find((x) => x.id === state.clothSel);
  if (!w) { toast("先点中柜里那一件"); return; }
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const before = w.img;
    w.img = compress(img, 320, 0.72);
    save(state); renderCloset();
    haptic("HEAVY");
    toastUndo(before ? `已换掉「${w.name}」的照片` : `已给「${w.name}」补上照片`, () => {
      if (before) w.img = before; else delete w.img;   // 原本没照片的要真退回「没有」
      save(state); renderCloset();
    });
    URL.revokeObjectURL(url);
  };
  img.onerror = () => { toast("图片读不出来"); URL.revokeObjectURL(url); };
  img.src = url;
}

async function runYi(file) {
  if (busy) return;
  busy = true;
  JianAPI.beginTurn();
  veil(true, "在认这件…");
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = async () => {
    try {
      const feat = Engine.analyze(img);
      const data = compress(img, 460, 0.78);
      const item = {
        // 名字的来路有三条，优先级就是这个顺序：
        //  1. 深链/言笺「寄去衣笺」带来的名字（wire.js 的 pendingNewName）——那是用户自己说的，
        //     比模型猜的准，所以**它优先于下面 seen.name 的覆盖**（用 fromLink 记住这件事）。
        //  2. 网关认出来的名字（seen.name，下一个 await 才到）。
        //  3. 「想买的这件」。
        name: (typeof pendingNewName === "string" && pendingNewName) || "想买的这件",
        cat: state.yiCat || "上衣",
        color: feat.color, img: data, tone: feat.tone, pattern: feat.pattern
      };
      // 用完即清：再存一次笺不该还顶着上一次那个名字（那是另一份数据的名字）
      const fromLink = !!(typeof pendingNewName === "string" && pendingNewName);
      if (fromLink) pendingNewName = "";
      if (!spend(2, "yi")) return;
      // 图一选就先落到首屏那个槽位上，别等结果页才看见自己挑的东西
      state.lastNew = item;
      paintHero();
      toast("过笺中…");
      // 认这件：填了网关就把照片交给模型看名字 / 品类 / 季节。
      // 主色仍然用本机量的——像素就在手上，模型猜的色实测能偏出一档（米色报成 #d4c5a9）。
      // 先画一版再认，认出来才改：填了网关的人不该对着空白多等这几秒。
      const seen = await JianAPI.see(file);
      if (seen) {
        if (seen.cat) item.cat = seen.cat;
        // 用户自己给的名字（深链/言笺带来的）不许被模型改掉：那是他自己写的那几个字。
        if (seen.name && !fromLink) item.name = seen.name;
        if (seen.season) item.season = seen.season;
        item.seen = { name: seen.name || "", cat: seen.cat || "", model: seen.model || "网关" };
        state.lastNew = item;
        paintHero();
      }
      const r = await JianAPI.yi(item, state.wardrobe);
      // 报告自带「想买的那件」。以前报告和照片分两个字段存，引擎一抛错就成了
      // 新照片配老报告；收成一个对象以后，两者不可能再各走各的。
      r.new = item;
      state.lastReport = r;
      state.album.unshift({ type: "yi", t: Date.now(), stamp: r.stamp, quote: r.quote, text: reportText(r) });
      save(state);
      paintReport();
      show("yi-report");
    } catch (e) {
      console.warn(e);
      refund(2, "yi");
      toast("这张笺没写成，笺点已退回");
    } finally {
      busy = false;
      veil(false);
      URL.revokeObjectURL(url);
    }
  };
  img.onerror = () => { busy = false; veil(false); toast("图片读不出来"); URL.revokeObjectURL(url); };
  img.src = url;
}

/** 认出来的那一行：说得出是谁认的，用户才知道可以改。没走模型时是空串。 */
function seenLine(it) {
  const s = it && it.seen;
  if (!s || !s.name) return "";
  return `认出来的是「${s.name}」（${s.cat || "未分类"}）· ${s.model}，品类不对就在柜子里改。`;
}

/** 报告页那件「想买的」是不是已经在柜子里了。
 *  靠报告上记的 closetId 现算，不另存一个布尔：从柜子里把那件删掉之后，
 *  按钮会自己活回来——布尔会一直谎称「已在柜里」。 */
function closetHasReportItem() {
  const id = state.lastReport && state.lastReport.closetId;
  return !!(id && state.wardrobe.some((w) => w.id === id));
}

/** 判完就入柜：过笺的那张照片、那个品类、那身颜色，本来就是柜子的新线索。 */
function reportToCloset() {
  const r = state.lastReport, n = r && r.new;
  if (!n) { toast("先过一张笺"); return; }
  if (closetHasReportItem()) { toast("这件已经在柜里了"); return; }
  const it = normCloth({
    id: newId(),
    name: n.name || "新入的一件",
    cat: CATS.includes(n.cat) ? n.cat : (state.yiCat || "上衣"),
    color: n.color, img: n.img, worn: 0, lastWorn: null,
    season: Engine.seasonOf({ cat: n.cat, name: n.name })
  });
  state.wardrobe.unshift(it);
  r.closetId = it.id;
  // 选中的就是刚入的这件：改名框、品类、季节立刻就在柜子下面摆着
  state.clothSel = it.id;
  // 柜子上方如果还挂着一条搜索，新这件多半不匹配那个词，会被筛到看不见——
  // 用户看到的就成了「点了没反应」。入柜这一下顺手把搜索清掉。
  const sq = $("#clothSearch");
  if (sq) sq.value = "";
  save(state);
  paintReport();
  show("yi");
  renderCloset();
  // 页签件数与那一柜的统计要跟着长：入柜是「积累感」那一条的原料
  if (typeof paintTabCounts === "function") paintTabCounts();
  if (typeof renderWardrobeStats === "function") renderWardrobeStats();
  haptic("HEAVY");
  toastUndo(`已记进柜子：「${it.name}」`, () => {
    state.wardrobe = state.wardrobe.filter((w) => w.id !== it.id);
    if (state.clothSel === it.id) state.clothSel = null;
    delete r.closetId;
    save(state);
    renderCloset(); paintReport();
    if (typeof paintTabCounts === "function") paintTabCounts();
    if (typeof renderWardrobeStats === "function") renderWardrobeStats();
  });
}

/** 报告页那个只给读屏器的标题。单独抽出来是因为换屏也要刷新它（ui.js 的 show() 一屏配一个
 *  render），而 paintReport 不能整片重跑——那会把落章的动画和那一记触感再演一遍。 */
function paintReportTitle() {
  const r = state.lastReport;
  const rt = $("#reportTitle");
  if (rt) rt.textContent = r && r.stamp ? `衣笺报告：${r.stamp}` : "衣笺报告（还没有笺）";
}

function reportReady() { return !!(state.lastReport && state.lastReport.new); }
// 「这一屏有笺可复制吗」与「有图可存吗」是两回事：旧版备份里的那张报告没有 .new，
// 存图画不出来（该灰），文字照样能复制（不该灰）。两条分开写，是因为按钮的条件必须
// 和函数自己的早退一模一样——差一个字就是一枚按了没反应的章。
function reportCopyable() { return !!state.lastReport; }

/** 这一屏三枚按钮灰不灰，一句话算完：**按下去会静默 return 的那一枚，就不许亮着**
 *  （第 27 轮定的「不许摆一枚按了没用的签」）。
 *  以前这份计算只写在 paintReport 里——那是「刚出判定」那条路才跑的，从别的口进这一屏
 *  （看上一张报告、以后可能的深链）三枚钮就停在各自的旧说法上：复制只问有没有
 *  lastReport、存图问的是有没有 .new，两枚按下去一个字都不说。
 *  三条各自的条件仍然各自成立（复制要有一张笺、存图与记柜要有一张能画/能记的新笺），
 *  收在一起的只是「由谁在什么时候把它们刷对」。 */
/** 挡住一枚按钮，不许用「按不动」来表达。
 *  真的 `disabled` 对读屏器和键盘是**隐形**的：他连「这枚现在不能用、为什么」都问不到，
 *  比按了没反应更糟（第 50 节那道键盘门就是把灰掉的钮算成「够不着」，两条牙当场打起来）。
 *  所以只标 aria-disabled——钮照样能聚焦、能按下——把理由留在 handler 里当场说。
 *  这一轮定下的一句话：**不许静默，也不许把入口藏起来。** */
function blockBtn(el, blocked) {
  if (!el) return;
  el.setAttribute("aria-disabled", blocked ? "true" : "false");
}

function paintReportActions() {
  const ready = reportReady();
  blockBtn($("#copyReport"), !reportCopyable());
  blockBtn($("#saveCard"), !ready);
  const tc = $("#toCloset");
  if (tc) {
    const has = closetHasReportItem();
    tc.textContent = has ? "已在柜里" : "记进柜子";
    blockBtn(tc, has || !ready);      // 按下去会各说一句为什么（先过一张笺 / 已经在柜里了）
  }
}

function paintReport() {
  const r = state.lastReport;
  hintEngine();     // 判定刚出，顶栏那行「本地 / 网关 / 回落本地」得跟着换（放在 return 之前：
                    // 没有照片的旧报告也要刷新出处，不然会停在上一张的说法上）
  const n = r && r.new;
  // 换屏时焦点落在这个屏幕外的标题上（ui.js 的 show() 找 h1）。以前报告页没有 h1，
  // 焦点交给 section 本身，读屏器只念区域名「衣笺报告」——这一屏唯一要看的那两个字
  // （宜入 / 再想想 / 先别）一个字都没念出来。写在早退之前：没有笺的时候也要说实话。
  paintReportTitle();
  paintReportActions();
  if (!n) return;
  const stampClass = r.stamp === "先别" ? "no" : r.stamp === "再想想" ? "mid" : "yes";
  $("#reportStamp").className = "stamp " + stampClass;
  $("#reportStamp").textContent = r.stamp;
  // 落章：每次出结论都重新盖一次（重排强制重启动画）
  const stampEl = $("#reportStamp");
  stampEl.classList.remove("press");
  void stampEl.offsetWidth;
  stampEl.classList.add("press");
  // 盖章要有手感：每次落章给一记中等触感（浏览器里静默）
  haptic("MEDIUM");
  $("#reportQuote").textContent = r.quote;
  const hint = {
    宜入: "可以买。",
    再想想: "不是错，只是柜里已有近亲。",
    先别: "先别下单。"
  }[r.stamp];
  const sub = $("#reportSub");
  if (sub) sub.textContent = hint || "";
  const note = $("#reportNote");
  if (note) {
    if (r.basis) {
      // 「几乎同色 / 同色系 / 隔得开」这套词只许有一份（card.js 的 nearWord）。
      // 这里以前自己抄了一遍同样的 12/30 阈值：谁调了 card.js 那一档，屏幕说「同色系」
      // 而长图说「隔得开」，同一张笺两种说法——和第 16 轮「推荐与判定各读一张表」同族。
      const near = nearWord(r.gap);
      let s = `柜里最像的一件是「${r.basis.name}」（${r.basis.cat}），色差 ${r.gap}，${near}。`;
      if (r.basis.wear) s += r.basis.wear;
      note.textContent = s + seenLine(r.new);
      note.dataset.seen = (r.new && r.new.seen && r.new.seen.name) ? "1" : "";
    } else {
      note.textContent = "";
    }
    // 薄柜子的判定几乎不会错，但也几乎没用：说出来，别让用户拿它去下单。
    // 「有多薄」是判定自己的属性（r.thin / r.closetN），长图和复制走同一份口径。
    if (r.thin) {
      note.textContent = (note.textContent ? note.textContent + " " : "") +
        `柜里只有 ${r.closetN || 0} 件，这个判定还薄——多收几件会准很多。`;
    }
    // 冷暖调这一句同样来自判定自己（r.toneLine）：屏幕上说的那句，长图与复制出去的那句不能少半截。
    if (r.toneLine) {
      note.textContent = (note.textContent ? note.textContent + " " : "") + r.toneLine;
    }
  }
  const matchEl = $("#reportMatch");
  if (matchEl) {
    const m = r.match || [];
    matchEl.textContent = m.length
      ? `也能配柜里的：${m.map((x) => x.name).join("、")}`
      : "";
  }
  const boxes = [n, ...(r.close || [])].slice(0, 3);
  $("#reportCompare").innerHTML = boxes.map((it, i) =>
    `<div class="box">${swatchEl(it.color, it.img)}<div class="tag">${i === 0 ? "想买" : esc(it.name || "柜里")}</div></div>`
  ).join("");
  updateStyleBtn();
}

function updateStyleBtn() {
  const b = $("#switchStyle");
  if (b) b.textContent = "版式 · " + (state.reportStyle === "mag" ? "杂志" : "卡片");
}
