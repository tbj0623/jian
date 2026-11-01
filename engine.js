/* 笺 · 本地判定引擎
   测试版走规则，接网关后按同一签名替换实现。
   对外：Engine.analyze / yi / wei / yan
   说明：这里刻意不写 ES module，保证 file:// 直接打开 index.html 能用。 */
const Engine = (() => {
  /* ==================== 色彩 ==================== */

  function hexToRgb(hex) {
    let h = String(hex || "").trim().replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (h.length !== 6 || /[^0-9a-f]/i.test(h)) return [200, 200, 200];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }

  function rgbToHex(rgb) {
    return "#" + rgb.map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0")).join("");
  }

  function srgbToLinear(c) {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  /** RGB → CIE Lab（D65）。用于感知色差，比 RGB 欧氏距离贴近人眼。 */
  function rgbToLab(rgb) {
    const R = srgbToLinear(rgb[0]), G = srgbToLinear(rgb[1]), B = srgbToLinear(rgb[2]);
    const x = (R * 0.4124564 + G * 0.3575761 + B * 0.1804375) / 0.95047;
    const y = (R * 0.2126729 + G * 0.7151522 + B * 0.0721750) / 1.0;
    const z = (R * 0.0193339 + G * 0.1191920 + B * 0.9503041) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    const fx = f(x), fy = f(y), fz = f(z);
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  }

  /** CIE76 色差。0-2 肉眼几乎不可分，2-12 很近，12-30 同色系，>30 明显不同。 */
  function deltaE(a, b) {
    return Math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2);
  }

  /** RGB → HSL，h 为 0-360，s/l 为 0-1。 */
  function rgbToHsl(rgb) {
    const r = rgb[0] / 255, g = rgb[1] / 255, b = rgb[2] / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const l = (max + min) / 2;
    let h = 0, s = 0;
    const d = max - min;
    if (d > 1e-6) {
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
      else if (max === g) h = ((b - r) / d + 2) * 60;
      else h = ((r - g) / d + 4) * 60;
    }
    return [h, s, l];
  }

  /** 两个色相的夹角，0-180。 */
  function hueGap(h1, h2) {
    const d = Math.abs(h1 - h2) % 360;
    return d > 180 ? 360 - d : d;
  }

  /** 归一化 RGB 距离，仅用于合并邻近色簇。 */
  function rgbDist(a, b) {
    return Math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2);
  }

  /** 冷 / 暖 / 中性。用于文案，不参与硬判定。
   *  先把 h/s/l 收到四位小数再比阈值：两端各自算 HSL，浮点最后一位可能差一点，
   *  而阈值边界上那一点点就够把「暖」翻成「冷」——这句话是要印在笺上给人看的。 */
  function toneOf(h, s, l) {
    const q = (x) => Math.round(x * 1e4) / 1e4;
    h = q(h); s = q(s); l = q(l);
    if (s < 0.12 || l > 0.93 || l < 0.08) return "中性";
    if (h >= 20 && h < 55) return "暖";     // 红橙黄棕
    if (h >= 55 && h < 95) return "暖";     // 黄绿偏暖
    if (h >= 300 || h < 20) return "暖";    // 紫红、红
    return "冷";                             // 青蓝绿、紫
  }

  /** 冷暖调这一句。toneOf 从第五轮就在算，注释写着「用于文案」——可文案二十几轮没来，
   *  算出来的值只躺进 lastNew 与备份里，全仓没有一处读它（第 24 轮删掉的就是同一类回显）。
   *  现在它只在**柜子里冷暖分明**的时候说一句事实：薄柜子（<5 件）谈不上多数，
   *  多数不到六成也不硬找话说。它不改判定，只给依据那一行多一句。 */
  function toneLine(newColor, list) {
    if (list.length < 5) return "";
    const cnt = { "冷": 0, "暖": 0, "中性": 0 };
    list.forEach((w) => { cnt[toneOf(...rgbToHsl(hexToRgb(w.color)))]++; });
    const major = cnt["暖"] >= cnt["冷"] ? "暖" : "冷";
    const n = list.length, mN = cnt[major];
    if (mN / n < 0.6) return "";
    const nt = toneOf(...rgbToHsl(hexToRgb(newColor)));
    if (nt === "中性") return `柜里 ${mN}/${n} 件是${major}调，这件是中性色，两边都接得住。`;
    if (nt === major) return `这件和柜里多数衣服同调（${major}调 ${mN}/${n}）。`;
    return `柜里 ${mN}/${n} 件是${major}调，这件是${nt}调。`;
  }

  /* ==================== 图像分析 ==================== */

  /** 把图缩到 size×size 取像素，避免整图开销。 */
  function samplePixels(img, size) {
    const c = document.createElement("canvas");
    c.width = size; c.height = size;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, size, size);
    return ctx.getImageData(0, 0, size, size).data;
  }

  /**
   * 主色提取。整图平均色会把条纹变灰、把深色背景混进来，
   * 所以改成：量化到颜色桶 → 按占比排序 → 合并邻近簇 → 跳过纯背景取主色。
   */
  function palette(img) {
    const size = 32;
    const data = samplePixels(img, size);
    const buckets = new Map();
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 96) continue;               // 透明像素不计
      const r = data[i], g = data[i + 1], b = data[i + 2];
      const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
      let e = buckets.get(key);
      if (!e) { e = { n: 0, r: 0, g: 0, b: 0 }; buckets.set(key, e); }
      e.n++; e.r += r; e.g += g; e.b += b;
    }
    let list = [...buckets.values()].map((e) => ({
      n: e.n,
      rgb: [Math.round(e.r / e.n), Math.round(e.g / e.n), Math.round(e.b / e.n)]
    })).sort((a, b) => b.n - a.n);

    const merged = [];
    for (const c of list) {
      const hit = merged.find((m) => rgbDist(m.rgb, c.rgb) < 42);
      if (hit) {
        // 以像素数加权平均
        const w = hit.n + c.n;
        hit.rgb = hit.rgb.map((v, i) => Math.round((v * hit.n + c.rgb[i] * c.n) / w));
        hit.n = w;
      } else {
        merged.push({ n: c.n, rgb: c.rgb });
      }
    }
    merged.sort((a, b) => b.n - a.n);

    const total = merged.reduce((s, x) => s + x.n, 0) || 1;
    return merged.map((m) => {
      const [h, s, l] = rgbToHsl(m.rgb);
      return {
        pct: m.n / total,
        rgb: m.rgb,
        hex: rgbToHex(m.rgb),
        lab: rgbToLab(m.rgb),
        hsl: [h, s, l],
        isGround: l > 0.94 || l < 0.06 || s < 0.05   // 白底 / 黑底 / 灰底
      };
    });
  }

  /**
   * 一件衣服的图像特征。
   * color  主色（跳过白底黑底后的最大色簇）
   * color2 次色，用于判断是不是多色/花色
   * pattern 0-1，越高越花
   */
  function analyze(img) {
    const pal = palette(img);
    const top = pal[0] || { hex: "#d4c4b0", hsl: [0, 0, 0.7], lab: [75, 0, 0], pct: 1, isGround: false };
    const real = pal.find((c) => !c.isGround && c.pct >= 0.1);
    const main = real || top;
    const second = pal.find((c) => c !== main && !c.isGround) || null;

    // 花不花：主色占比越低越花；主色次色色差越大越花
    let pattern = 1 - main.pct;
    if (second) {
      const gap = Math.min(1, deltaE(main.lab, second.lab) / 60);
      pattern = Math.max(pattern, (1 - main.pct) * 0.6 + gap * 0.4);
    }
    pattern = Math.max(0, Math.min(1, pattern));

    const [h, s, l] = main.hsl;
    return {
      color: main.hex,
      color2: second ? second.hex : null,
      hex: main.hex,
      rgb: main.rgb,
      lab: main.lab,
      hue: h,
      sat: s,
      light: l,
      tone: toneOf(h, s, l),
      pattern: Math.round(pattern * 100) / 100,
      ratio: img.width / Math.max(1, img.height)
    };
  }

  /* ==================== 排版规则 ==================== */

  /**
   * 竖排避头尾（禁则）。放这里而不是写在长图绘制里，因为它就是一张规则表 + 一个纯函数，
   * 能直接单测；app.js 里那份内联实现只能靠肉眼看渲染结果。
   * 行首禁：不能出现在一列开头的字符——句读、后括号、后引号、长音符、破折号、空白。
   * 行尾禁：不能收在一列末尾的字符——前括号、前引号、书名号。
   */
  const VHEAD_BAN =
    "。．、・･,，;；:：!！?？‥…〜～ー–—―‐_゛゜々〻" +
    "）)］]｝}〉》」』】〞〝”’'\"" +
    " 　";   // 半角/全角空格同样不能开列——金句里的「 3 件」正好撞上
  const VTAIL_BAN = "（(［[｛{〈《「『【〔〖〘〚“‘";

  /** 一个竖排字占多少步距：句读半格，让挤进列尾的标点放得下。 */
  function vCost(ch) {
    return VHEAD_BAN.includes(ch) ? 0.6 : 1;
  }

  /**
   * 竖排占位单元。连续两个半角数字合成一个「纵中横」单元：横着挤进一格，而不是像
   * 逐字竖排那样把「16」拆成 1 和 6 两行——那是杂志绝不会犯的错。
   * 三位以上整段退回逐字（一格塞不下，也别只把后两位合并、剩个孤零零的首字）。
   */
  function vClusters(str) {
    const chars = [...String(str || "")];
    const isNum = (c) => c >= "0" && c <= "9";
    const out = [];
    for (let i = 0; i < chars.length; i++) {
      if (!isNum(chars[i])) { out.push({ t: chars[i], adv: vCost(chars[i]) }); continue; }
      let j = i;
      while (j < chars.length && isNum(chars[j])) j++;
      const run = chars.slice(i, j).join("");
      if (run.length === 2) out.push({ t: run, adv: 1 });
      else for (const d of run) out.push({ t: d, adv: 1 });
      i = j - 1;
    }
    return out;
  }

  /** 一列（list 的 [from, to) 段）占多少步距。 */
  function vAdvance(list, from, to) {
    let adv = 0;
    for (let k = from; k < to; k++) adv += list[k].adv;
    return adv;
  }

  /**
   * 按禁则把竖排单元切成列。perCol 是「一个字的顶位还能走到几步」= (可用高度 - 字高) / 步距，
   * 由调用方按版面真实边界算给它。别拿「高度/步距」直接当预算：那样 14 个整字之后还能再挤
   * 一个标点，列尾就掉到照片外面去了。
   */
  function vBreak(list, perCol) {
    const cols = [];
    let i = 0;
    while (i < list.length) {
      let end = i, adv = 0;
      while (end < list.length) {
        const must = end > i && VHEAD_BAN.includes(list[end].t);
        if (adv > perCol + (must ? 0.6 : 0)) break;     // 顶位已在带外
        adv += list[end].adv; end += 1;
      }
      if (end <= i) end = i + 1;                        // 至少吃一个单元，避免卡死
      // 紧跟在列尾的是行首禁的字（。、「色，而且…」这种）：光靠 0.6 的借位常常不够，
      // 宁可少排一个字、让它和前面的字一起挪到下一列，也不能让一列以标点开头。
      while (end > i + 1 && end < list.length && VHEAD_BAN.includes(list[end].t) &&
             vAdvance(list, i, end) + list[end].adv > perCol + 0.6) end -= 1;
      while (end - 1 > i && VTAIL_BAN.includes(list[end - 1].t)) end -= 1;   // 开引号挪去下一列
      cols.push(list.slice(i, end).map((c) => c.t).join(""));
      i = end;
    }
    return cols;
  }

  /**
   * 把一句金句切成不超过 maxCols 列的竖排文本。
   * 早先 app.js 里的写法是「先按 14×4 截断，再分列，最后只画前 4 列」——禁则把字往后挤时，
   * 第 5 列连同里面的字会被静默丢掉。这里改成挤爆了就收回尾巴重排：宁可末尾换成省略号，
   * 也不让句子从中间消失。
   */
  function verticalCols(str, perCol, maxCols) {
    const all = [...String(str || "")];
    if (!all.length || !(perCol >= 1) || !(maxCols >= 1)) return [];
    // 一列装得下的格数 = floor(顶位预算) + 1（第一个单元顶位在 0）
    const cells = Math.floor(perCol) + 1;
    let n = Math.min(all.length, cells * maxCols);
    let cols = [];
    for (let guard = 0; guard <= maxCols + 1; guard++) {
      const chars = all.slice(0, n);
      if (chars.length < all.length && chars.length) chars[chars.length - 1] = "…";
      cols = vBreak(vClusters(chars.join("")), perCol);
      if (cols.length <= maxCols) return cols;
      n = Math.max(1, n - cells);                       // 少排一列的字再来一遍
    }
    return cols.slice(0, maxCols);
  }

  /* ==================== 衣笺 ==================== */

  // 同品类色差阈值（CIE76 ΔE）
  const SAME_CAT_STOP = 22;    // 以内：几乎是同一句
  const SAME_CAT_HOLD = 45;    // 以内：同色系，抢同一季
  const CROSS_CAT_HOLD = 14;   // 跨品类但颜色极近

  const YI_LINES = {
    先别: [
      (n) => `和「${n}」几乎是同一句话，只是换了个人说。`,
      (n) => `柜里的「${n}」就是这个色。再买一件，是重复的句子。`,
      (n) => `「${n}」已经把这句话说完了。`
    ],
    再想想: [
      (n) => `接近「${n}」，差在深浅，或者差在场合。`,
      (n) => `能进柜，但会和「${n}」抢同一季。`,
      (n) => `跟「${n}」是一家的。除非它能解开更多旧的搭配。`
    ],
    宜入: [
      (w) => `柜里没有这个色。它能解开 ${w} 件旧衣。`,
      () => "这个色柜里空着。买回去，旧的几件会重新好穿。"
    ]
  };

  /**
   * 季节性衣物：半年没穿是正常的（换季收起来了），不能据此断定"你不需要"。
   * 这是上一版会犯的错——9 月看到驼大衣 7 个月没穿，其实是去年冬天穿的。
   */
  const SEASONAL_RE = /大衣|羽绒|棉袄|棉服|毛衣|针织|围巾|披肩|靴|风衣|夹克|外套|雪地/;
  function isSeasonal(w) {
    if (!w) return false;
    // 夏、冬两季的衣服本来就一年只出两场，半年没穿不是「买错了」的证据。
    // seasonOf() 早就算得出这一层（柜子按季节筛就是靠它），判定以前只看品类和名字里的
    // 线索，于是柜上标着「夏」的一件，九月会被数落「6 个月没穿过了」。
    // 「四季」是用户明说常年穿的，不替他找换季的台阶；「春秋」跨两季，仍按久未穿算。
    const s = seasonOf(w);
    if (s === "夏" || s === "冬") return true;
    return w.cat === "外套" || SEASONAL_RE.test(String(w.name || ""));
  }

  /**
   * 一件衣物的季节归属：夏 / 春秋 / 冬 / 四季。
   * 用户手选 season 优先（值域内原样返回）；否则按「品类名+名称」推断。
   * 推断只出 夏 / 冬 / 春秋——「四季」只能来自手选，不由词表猜。
   * 与 gateway.py 的 season_of 逐字同口径，test/consistency.py 守着。
   */
  const SEASON_VALUES = ["夏", "春秋", "冬", "四季"];
  const SEASON_SUMMER_RE = /短袖|背心|吊带|凉鞋|拖鞋|短裤|雪纺/;
  const SEASON_WINTER_RE = /羽绒|大衣|棉服|棉袄|围巾|围脖|毛衣|针织|靴|卫衣|加绒|羊羔毛|皮草|雪地/;
  function seasonOf(w) {
    if (w && SEASON_VALUES.includes(w.season)) return w.season;
    const text = `${(w && w.cat) || ""}${(w && w.name) || ""}`;
    if (SEASON_SUMMER_RE.test(text)) return "夏";
    if (SEASON_WINTER_RE.test(text)) return "冬";
    return "春秋";
  }

  /** 把柜里那件的穿着状态说成一句人话——往往比色差更有说服力。 */
  function wearLine(w) {
    if (!w) return "";
    if (!w.worn) return "那件还没穿过。";
    const d = Math.floor((Date.now() - (w.lastWorn || 0)) / 86400000);
    if (d >= 180) {
      return isSeasonal(w)
        ? "那件是季节性衣物，多半是换季收起来了。"
        : `那件已经 ${Math.floor(d / 30)} 个月没穿了。`;
    }
    if (d >= 60) return `那件上次穿是 ${Math.floor(d / 30)} 个月前。`;
    if (d >= 14) return `那件上次穿是 ${Math.floor(d / 7)} 周前。`;
    if (d >= 2) return `那件 ${d} 天前刚穿过。`;
    return "那件最近常穿。";
  }

  /** 长图上用的一行短版本。 */
  function wearShort(w) {
    if (!w) return "";
    if (!w.worn) return "还没穿过";
    const d = Math.floor((Date.now() - (w.lastWorn || 0)) / 86400000);
    if (d >= 180) return isSeasonal(w) ? "换季收起了" : `${Math.floor(d / 30)} 个月没穿`;
    if (d >= 60) return `${Math.floor(d / 30)} 个月前穿过`;
    if (d >= 14) return `${Math.floor(d / 7)} 周前穿过`;
    if (d >= 2) return `${d} 天前穿过`;
    return "最近常穿";
  }

  const STALE = 180 * 86400000;   // 半年没穿过

  /**
   * 这件能和柜里哪些搭上。
   * 只算不同品类——同品类的相似是「重复」，不是「搭配」。
   */
  function pickCompanions(newItem, list) {
    const rgbN = hexToRgb(newItem.color);
    const labN = rgbToLab(rgbN);
    const [h1, s1, l1] = rgbToHsl(rgbN);
    const neutral = (s, l) => s < 0.16 || l > 0.90 || l < 0.12;
    const baseNeutral = neutral(s1, l1);
    const out = [];
    list.forEach((w) => {
      if (w.cat === newItem.cat) return;
      const rgbW = hexToRgb(w.color);
      const de = deltaE(labN, rgbToLab(rgbW));
      if (de < 6) return;                        // 几乎一样，谈不上"搭"
      const [h2, s2, l2] = rgbToHsl(rgbW);
      let ok = baseNeutral || neutral(s2, l2);
      if (!ok) {
        const g = hueGap(h1, h2);
        ok = g < 60 || g > 150;                  // 邻近色，或撞得出彩的对比色
      }
      if (ok) out.push({ item: w, de });
    });
    return out.sort((a, b) => a.de - b.de).slice(0, 3).map((x) => ({ ...x.item, gap: Math.round(x.de) }));
  }

  function yi(newItem, wardrobe) {
    const list = Array.isArray(wardrobe) ? wardrobe : [];
    // 柜子里只有一两件时，「柜里没有这个色」几乎不可能是错的——但那不是洞察。
    // 把厚度做成判定自己的属性：屏幕、长图、复制的话术都从这一处说，不各自猜。
    const thin = list.length < 5;
    if (!list.length) {
      return { stamp: "再想想", quote: "柜里还空着。先放几件常穿的，过笺才有得比。", close: [], match: [], gap: 0, basis: null, thin: true, closetN: 0 };
    }
    const labNew = rgbToLab(hexToRgb(newItem.color));
    // 只算判定真要用的色差。早先这里每件都顺带算一次 HSL、再乘出 hueGap / lightGap，
    // 而两个字段全仓没人读（新买那件的 HSL 还在循环里重复算了 N 遍）——去掉。
    const scored = list.map((w) => ({
      item: w,
      de: deltaE(labNew, rgbToLab(hexToRgb(w.color))),
      sameCat: w.cat === newItem.cat
    })).sort((a, b) => a.de - b.de);

    // 优先在"同品类"里找最近的那件：买第二件白衬衫才算重复
    const sameCat = scored.filter((s) => s.sameCat);
    const basis = (sameCat.length ? sameCat : scored)[0];
    const farBest = scored[0];

    let stamp = "宜入";
    if (basis.sameCat) {
      if (basis.de < SAME_CAT_STOP) stamp = "先别";
      else if (basis.de < SAME_CAT_HOLD) stamp = "再想想";
    } else if (farBest.de < CROSS_CAT_HOLD) {
      stamp = "再想想";
    }

    // 柜里那件几乎一样、却很久没穿——这比"重复"更值得说。
    // 但季节性衣物（外套、毛衣）半年没穿是正常的，不能算数。
    const seasonal = isSeasonal(basis.item);
    const stale = !seasonal && basis.item.lastWorn && Date.now() - basis.item.lastWorn > STALE;
    const match = pickCompanions(newItem, list);

    const isPattern = (newItem.pattern || 0) > 0.55;
    const picks = YI_LINES[stamp];
    let quote;
    if (stamp === "宜入") {
      const wearables = sameCat.length ? scored.filter((s) => s.de >= SAME_CAT_HOLD).length : 0;
      if (isPattern) quote = picks[picks.length - 1]();
      else if (match.length >= 2) quote = `柜里没有这个色，能和 ${match.length} 件旧的搭上。`;
      else quote = picks[0](Math.max(1, Math.min(4, wearables || 2)));
    } else if (stale && stamp === "先别") {
      quote = `柜里的「${basis.item.name}」就是这个色，而且 ${Math.floor((Date.now() - basis.item.lastWorn) / (30 * 86400000))} 个月没穿过了。再买一件，只会多一件不穿的。`;
    } else if (stale && stamp === "再想想") {
      quote = `接近「${basis.item.name}」。但那一件你自己都不太穿——先想清楚要的是这个色，还是新鲜感。`;
    } else {
      const pool = picks.filter((p) => p.length === 1);
      quote = pool[Math.min(pool.length - 1, scored.length > 1 ? 1 : 0)](basis.item.name);
    }

    return {
      stamp,
      quote,
      close: scored.slice(0, 2).map((s) => s.item),
      match,
      gap: Math.round(basis.de),
      sameCat: basis.sameCat,
      stale: !!stale,
      seasonal,
      basis: {
        name: basis.item.name, cat: basis.item.cat, gap: Math.round(basis.de),
        wear: wearLine(basis.item), wearShort: wearShort(basis.item),
        seasonal,
        worn: basis.item.worn || 0, lastWorn: basis.item.lastWorn || null
      },
      thin, closetN: list.length,
      toneLine: toneLine(newItem.color, list)
    };
  }

  /* ==================== 味笺 ==================== */

  // 菜名关键词 → 隐藏成分。命中即认为含该成分。
  const HIDDEN = {
    宫保: ["花生"], 怪味: ["花生"], 花生: ["花生"], 腰果: ["花生"],
    坚果: ["花生"], 核桃: ["花生"], 果仁: ["花生"],
    水煮: ["辣"], 麻婆: ["辣"], 麻辣: ["辣"], 香锅: ["辣"], 火锅: ["辣"],
    毛血旺: ["辣"], 口水: ["辣"], 担担: ["辣"], 辣子: ["辣"], 剁椒: ["辣"],
    泡椒: ["辣"], 藤椒: ["辣"], 椒麻: ["辣"], 红油: ["辣"], 干锅: ["辣"],
    香辣: ["辣"], 酸辣: ["辣"], 辣炒: ["辣"], 火爆: ["辣"], 冒菜: ["辣"],
    串串: ["辣"], 麻辣烫: ["辣"], 口味虾: ["辣"], 夫妻肺片: ["辣"],
    香菜: ["香菜"], 芫荽: ["香菜"], 折耳根: ["香菜"],
    蒜蓉: ["蒜"], 蒜泥: ["蒜"], 蒜香: ["蒜"], 蒜苗: ["蒜"],
    啤酒: ["酒"], 黄酒: ["酒"], 醉: ["酒"], 花雕: ["酒"], 酒酿: ["酒"],
    虾: ["海鲜"], 蟹: ["海鲜"], 生蚝: ["海鲜"], 花甲: ["海鲜"], 蛤: ["海鲜"],
    鱿鱼: ["海鲜"], 章鱼: ["海鲜"], 鲍: ["海鲜"], 扇贝: ["海鲜"], 海参: ["海鲜"],
    龙虾: ["海鲜"], 皮皮虾: ["海鲜"], 生鱼: ["海鲜"], 三文鱼: ["海鲜"],
    带子: ["海鲜"], 蛏: ["海鲜"], 海蜇: ["海鲜"],
    // 「海鲜」这两个字本身也要认：菜单上写的是「海鲜汤」「捞汁海鲜」，
    // 里面一个虾蟹鱼字都没有，以前它落在 HIDDEN 与 CHIP_MAP 之外——
    // 忌海鲜的人看到的是一行「全员安全」。
    海鲜: ["海鲜"],
    酸菜鱼: ["鱼"], 水煮鱼: ["辣", "鱼"], 烤鱼: ["鱼"], 清蒸鱼: ["鱼"],
    红烧鱼: ["鱼"], 鲫鱼: ["鱼"], 草鱼: ["鱼"], 鲤鱼: ["鱼"], 黄鱼: ["鱼"],
    鲈鱼: ["鱼"], 黑鱼: ["鱼"], 鱼头: ["鱼"],
    红烧肉: ["猪肉"], 回锅: ["猪肉"], 东坡: ["猪肉"], 扣肉: ["猪肉"],
    排骨: ["猪肉"], 猪蹄: ["猪肉"], 叉烧: ["猪肉"], 腊肉: ["猪肉"], 香肠: ["猪肉"],
    小炒肉: ["猪肉"], 木须: ["猪肉"], 锅包肉: ["猪肉"], 狮子头: ["猪肉"],
    鱼香肉丝: ["猪肉"], 青椒肉丝: ["猪肉"], 梅干菜: ["猪肉"], 五花: ["猪肉"],
    里脊: ["猪肉"], 培根: ["猪肉"], 火腿: ["猪肉"], 猪肝: ["内脏"], 肥肠: ["内脏"],
    腰花: ["内脏"], 肚丝: ["内脏"], 鸡杂: ["内脏"], 鸭血: ["内脏"], 猪心: ["内脏"],
    牛肉: ["牛羊肉"], 肥牛: ["牛羊肉"], 牛腩: ["牛羊肉"], 牛排: ["牛羊肉"],
    黑椒牛: ["牛羊肉"], 羊肉: ["牛羊肉"], 羊排: ["牛羊肉"], 涮羊: ["牛羊肉"],
    手抓羊: ["牛羊肉"], 烤羊: ["牛羊肉"],
    奶茶: ["乳"], 布丁: ["乳"], 蛋糕: ["乳"], 奶油: ["乳"], 芝士: ["乳"],
    奶酪: ["乳"], 奶盖: ["乳"], 黄油: ["乳"], 双皮奶: ["乳"], 拿铁: ["乳"]
  };

  // 忌口芯片 → 菜名里触发它的关键词
  const CHIP_MAP = {
    辣: ["辣", "麻", "水煮", "火锅", "香锅", "口水", "担担", "剁椒", "毛血", "泡椒", "藤椒", "干锅", "红油"],
    香菜: ["香菜", "芫荽", "折耳根"],
    海鲜: ["海鲜", "虾", "蟹", "蚝", "贝", "鱼", "鱿", "花甲", "蛤", "鲍", "蛏", "海参", "海蜇", "章鱼", "龙虾"],
    花生: ["花生", "宫保", "坚果", "腰果", "核桃", "果仁"],
    牛羊肉: ["牛", "羊"],
    内脏: ["肝", "腰", "肚", "肠", "胗", "心", "肺", "血"],
    蒜: ["蒜"],
    酒: ["酒", "啤", "醉", "花雕"],
    乳: ["奶", "芝士", "奶酪", "黄油", "乳"],
    清淡: [],
    猪肉: ["猪", "回锅", "东坡", "叉烧", "排骨", "扣肉", "腊肉", "五花", "里脊"],
    /* 2026-10 补的四类。**只能往末尾追加**：这张表的键序被 chipsInNotes 与 Python 的
       dict 序同时依赖（见下面 chipsInNotes 的注释），插在中间会让两端漂。

       这四类以前一个字都没有，判定于是退化成「按菜名字面匹配」——而菜名里不会写
       「小麦」。实测 63 道菜：小麦应判 9 道、判出 0 道；大豆应判 3 道、判出 0 道。
       屏幕上那句「小笼包 · 全员安全」，对一个对小麦过敏的人是会造成伤害的谎话。

       词表里的每个词都必须是「菜名里会出现、且出现就一定含这样东西」的：
         · 小麦：面 / 饼 / 饺 / 包子 / 小笼 / 馒头 / 馍 / 烙 / 馄饨 / 云吞 / 油条 / 春卷 / 面筋
           （不写「粉」—— 河粉米线是米做的，写进去会把米粉汤判成含小麦）
         · 大豆：豆腐 / 豆干 / 豆皮 / 豆泡 / 千张 / 腐竹 / 毛豆 / 豆浆 / 豆芽 / 豆豉 / 豆瓣
           （不写单字「豆」—— 土豆、四季豆、豇豆都不是大豆，写进去这三道会被误判）
         · 坚果：腰果 / 核桃 / 杏仁 / 松仁 / 榛 / 开心果 / 果仁 / 巴旦木，**外加「宫保」**：
           宫保类菜放的是花生，而花生过敏与坚果过敏在现实里经常同时存在，两边都该避开它。
           「花生」这个芯片自己的映射早就把 坚果/腰果/核桃/果仁 包了进去，方向是对称的——
           这一条只补上另一边，不改花生那一条（改了会让老数据里挂花生的人凭空多出忌口）。 */
    蛋: ["蛋"],
    小麦: ["面", "饼", "饺", "包子", "小笼", "馒头", "馍", "烙", "馄饨", "云吞", "油条", "春卷", "面筋"],
    大豆: ["豆腐", "豆干", "豆皮", "豆泡", "千张", "腐竹", "毛豆", "豆浆", "豆芽", "豆豉", "豆瓣"],
    坚果: ["腰果", "核桃", "杏仁", "松仁", "榛", "开心果", "果仁", "巴旦木", "宫保"]
  };

  // 正则只认菜名里出现的字面 token，所以「地三鲜 / 小笼包 / 凤爪」这类不含原料名的
  // 家常菜要显式列进来——否则 dishKind 判成「其他」，而菜库把它归在某一类，
  // 排桌时「素 0 道」和「推荐你加道素菜」就会自相矛盾。test/engine.test.mjs 守着这条不变式。
  const MEAT_RE = /肉|鸡|鸭|鹅|牛|羊|猪|鱼|虾|蟹|排骨|肘|蹄|肚|肠|肝|腰|贝|蚝|鱿|鳝|蛙|兔|鸽|培根|火腿|香肠|腊|丸|排|里脊|狮子头|凤爪/;
  const VEG_RE = /菜|豆|茄|瓜|笋|菇|菌|藕|萝卜|土豆|菠菜|白菜|西兰花|四季豆|玉米|青椒|番茄|西红柿|木耳|海带|山药|莴笋|空心菜|油麦|生菜|韭菜|芹菜|洋葱|彩椒|蔬|地三鲜/;
  const SOUP_RE = /汤|羹|煲|粥|砂锅/;
  const STAPLE_RE = /饭|面|粉|饺|包子|馒头|饼|馍|米线|河粉|年糕|馄饨|云吞|团|盒|小笼|烙/;
  const COLD_RE = /凉拌|拍黄瓜|白灼|醉|卤|酱牛肉|刺身|沙拉|皮蛋|拌/;
  const HEAVY_RE = /红烧|干锅|水煮|烤|麻辣|香锅|炖|焖|扣|爆|肘子|大盘|小龙虾|整只|整条/;
  // 有人只吃清淡时，这些做法/口味词算踩雷
  const QINGDAN_RE = /辣|麻|水煮|香锅|火锅|酸菜|口水|毛血|剁椒|泡椒|藤椒|红油/;

  /** 一道菜属于哪一类，用于排桌结构。粥归汤（前一条先判），不进主食正则。 */
  function dishKind(dish) {
    if (SOUP_RE.test(dish)) return "汤";
    if (STAPLE_RE.test(dish)) return "主食";
    if (MEAT_RE.test(dish)) return "荤";
    if (VEG_RE.test(dish)) return "素";
    return "其他";
  }

  /**
   * 上菜阶段。先开胃清口，主菜跟上，硬菜居中偏后，汤和主食收尾。
   * 参考的是家常待客的顺序——硬的压轴，汤饭垫底。
   */
  const STAGE_NAMES = { 1: "先上", 2: "清口", 3: "主菜", 4: "硬菜", 5: "汤", 6: "主食" };

  function servingStage(dish) {
    if (SOUP_RE.test(dish)) return 5;
    if (STAPLE_RE.test(dish)) return 6;
    if (COLD_RE.test(dish)) return 1;
    if (HEAVY_RE.test(dish)) return 4;
    if (dishKind(dish) === "素") return 2;
    return 3;
  }

  /** 把菜单排成上菜顺序。
   *  mode 是这条判定的输入之一，不是文案的装饰：「家里这桌，硬菜和雷放后面」
   *  「同事这桌，先保全员能入口」这两句从第九轮就印在屏上，而以前这里只认 stage，
   *  四张模式签排出来的桌逐字节相同——按了没反应的那一种（第 40 轮）。
   *  压后用 stage + 7 表达：stage 只有 1~6，加一档就稳定落在所有正常道之后，
   *  被压后的几道之间仍按自己的 stage 走。全序且确定，两端不会漂。
   *  later 是「有人吃不了」的那几道（boom 的菜名），由调用方算好传进来，
   *  免得这里再判一遍忌口——那是第二份口径。 */
  function servingOrder(lines, mode, later) {
    const late = later || new Set();
    const pushed = (dish) =>
      (mode === "work" && late.has(dish)) ||
      (mode === "home" && (late.has(dish) || HEAVY_RE.test(dish)));
    return lines
      .map((dish, i) => ({ dish, i, stage: servingStage(dish), sortKey: servingStage(dish) + (pushed(dish) ? 7 : 0) }))
      .sort((a, b) => a.sortKey - b.sortKey || a.i - b.i)
      .map((x) => ({ dish: x.dish, stage: x.stage, label: STAGE_NAMES[x.stage] }));
  }

  /** 按人数给一份排桌结构建议。家常口径：人数 + 2 道。 */
  function tablePlan(peopleCount, kinds) {
    const n = Math.max(1, peopleCount);
    const want = {
      荤: Math.max(1, Math.round(n * 0.5) + (n >= 4 ? 1 : 0)),
      素: Math.max(1, Math.round(n * 0.5)),
      汤: n >= 3 ? 1 : 0,
      主食: n >= 5 ? 2 : 1
    };
    const gap = {};
    ["荤", "素", "汤", "主食"].forEach((k) => {
      const d = (want[k] || 0) - (kinds[k] || 0);
      if (d > 0) gap[k] = d;
    });
    return { want, gap, total: Object.values(want).reduce((a, b) => a + b, 0) };
  }

  /* 家常菜库。tags 写的是它会让哪些忌口的人吃不了，推荐时会据此避开。 */
  const DISHES = {
    荤: [
      { n: "红烧排骨", tags: ["猪肉"] },
      { n: "糖醋里脊", tags: ["猪肉"] },
      { n: "可乐鸡翅", tags: [] },
      { n: "白切鸡", tags: [] },
      { n: "三杯鸡", tags: ["酒"] },
      { n: "黑椒牛柳", tags: ["牛羊肉"] },
      { n: "孜然羊肉", tags: ["牛羊肉"] },
      { n: "清蒸鲈鱼", tags: ["海鲜"] },
      { n: "红烧带鱼", tags: ["海鲜"] },
      { n: "京酱肉丝", tags: ["猪肉"] },
      { n: "梅菜扣肉", tags: ["猪肉"] },
      { n: "滑蛋虾仁", tags: ["海鲜"] },
      { n: "豉汁蒸凤爪", tags: ["蒜"] },
      { n: "香菇滑鸡", tags: [] },
      { n: "土豆炖牛肉", tags: ["牛羊肉"] },
      { n: "酱爆鸡丁", tags: ["花生"] },
      { n: "红烧狮子头", tags: ["猪肉"] },
      { n: "油焖大虾", tags: ["海鲜"] },
      { n: "木须肉", tags: ["猪肉"] },
      { n: "葱爆羊肉", tags: ["牛羊肉"] }
    ],
    素: [
      { n: "清炒时蔬", tags: [] },
      { n: "白灼菜心", tags: [] },
      { n: "香菇青菜", tags: [] },
      { n: "清炒芦笋", tags: [] },
      { n: "地三鲜", tags: [] },
      { n: "醋溜白菜", tags: [] },
      { n: "蒜蓉西兰花", tags: ["蒜"] },
      { n: "凉拌黄瓜", tags: ["蒜"] },
      { n: "手撕包菜", tags: ["辣"] },
      { n: "酸辣土豆丝", tags: ["辣"] },
      { n: "干煸四季豆", tags: ["辣", "猪肉"] },
      { n: "麻婆豆腐", tags: ["辣", "猪肉"] },
      { n: "凉拌木耳", tags: ["蒜"] },
      { n: "醋溜土豆丝", tags: [] },
      { n: "蒜泥茄子", tags: ["蒜"] },
      { n: "香菇油菜", tags: [] },
      // 蛋菜按素计：MEAT_RE 里没有「蛋」，VEG_RE 认得出番茄 / 韭菜。
      // 放在队尾，不动既有推荐顺序（这两道从前在荤队尾，本来也取不到）。
      { n: "番茄炒蛋", tags: [] },
      { n: "韭菜炒蛋", tags: [] }
    ],
    汤: [
      { n: "西红柿蛋汤", tags: [] },
      { n: "丝瓜蛋汤", tags: [] },
      { n: "菌菇汤", tags: [] },
      { n: "冬瓜排骨汤", tags: ["猪肉"] },
      { n: "玉米排骨汤", tags: ["猪肉"] },
      { n: "老鸭汤", tags: [] },
      { n: "紫菜蛋花汤", tags: ["海鲜"] },
      { n: "番茄牛腩汤", tags: ["牛羊肉"] },
      { n: "酸辣汤", tags: ["辣"] },
      { n: "萝卜牛腩煲", tags: ["牛羊肉"] },
      { n: "海带豆腐汤", tags: ["海鲜"] },
      { n: "鲫鱼豆腐汤", tags: ["海鲜"] },
      // 「上汤」是带汤的做法，SOUP_RE 先判，算汤不算素
      { n: "上汤娃娃菜", tags: [] }
    ],
    主食: [
      { n: "米饭", tags: [] },
      { n: "蛋炒饭", tags: [] },
      { n: "葱油拌面", tags: [] },
      { n: "阳春面", tags: [] },
      { n: "手抓饼", tags: [] },
      { n: "玉米烙", tags: [] },
      { n: "南瓜饼", tags: [] },
      { n: "猪肉白菜饺子", tags: ["猪肉"] },
      { n: "小笼包", tags: ["猪肉"] },
      { n: "刀削面", tags: [] },
      { n: "韭菜盒子", tags: [] },
      { n: "牛肉面", tags: ["牛羊肉"] }
    ]
  };

  const SPICY_RE = /辣|麻|干锅|水煮|泡椒|剁椒|椒麻|红油/;

  /** 缺口在哪一类，就从菜库里挑几道能点的，避开全桌忌口与已有菜。 */
  function recommend(gap, bans, lines) {
    const out = [];
    const has = (name) => lines.some((d) => d.includes(name) || name.includes(d));
    ["荤", "素", "汤", "主食"].forEach((kind) => {
      if (!gap[kind]) return;
      const pool = (DISHES[kind] || []).filter((d) => {
        if (has(d.n)) return false;
        if (d.tags.some((t) => bans.has(t))) return false;
        if (bans.has("清淡") && (d.tags.includes("辣") || SPICY_RE.test(d.n))) return false;
        return true;
      });
      const take = Math.min(3, gap[kind] + 1);
      pool.slice(0, take).forEach((d) => out.push({ kind, name: d.n }));
    });
    return out;
  }

  // 同一主料出现两次以上就提醒换一道（里脊/狮子头补家常肉菜主料）
  const MAINS = ["鱼", "虾", "蟹", "鸡", "鸭", "牛", "羊", "猪", "排骨", "豆腐", "蛋", "茄子", "土豆", "面", "里脊", "狮子头"];

  function findDupes(lines) {
    const map = {};
    lines.forEach((d) => {
      MAINS.forEach((m) => {
        if (d.includes(m)) (map[m] = map[m] || []).push(d);
      });
    });
    return Object.entries(map)
      .filter(([, arr]) => arr.length > 1)
      .map(([main, dishes]) => ({ main, dishes }));
  }

  /** 菜库摊平成一列，按「荤→素→汤→主食」的声明序；两端必须同序，
   *  否则同一道菜的雷区理由会写成「猪肉 / 辣」和「辣 / 猪肉」两种。 */
  const DISH_TAGS = [];
  Object.keys(DISHES).forEach((k) => DISHES[k].forEach((d) => DISH_TAGS.push(d)));

  /**
   * 菜单框里混的不只是菜。实测贴一句「周五晚上三个人来吃饭，准备番茄牛腩、清炒时蔬、
   * 蒜蓉虾，还有一个凉拌黄瓜。有人不吃辣，另外一个对海鲜有点忌讳。」，旧的分词只切
   * 逗号顿号，于是「还有一个凉拌黄瓜。有人不吃辣」整句被当成一道先上的菜，
   * 而「不吃辣」「对海鲜忌讳」这两条真忌口被静默丢掉——蒜蓉虾照样进「全员安全」。
   * 前者是笑话，后者是把人吃坏的那一种错。
   * 所以先把片段分成「菜」和「关于这桌人的话」：话不占菜数，但它说到的忌口真的算进雷区。
   * 与 gateway.py 的 SPLIT_MENU_RE / FILLER_HEAD_RE / NOTE_RE / NEG_RE / POS_RE 逐字一致。
   */
  const SPLIT_MENU_RE = /[\n,，、；;。！!？?()\s（）【】]/;
  // 菜名前头的口语填充：连接词、数量词、动词。剥完什么都不剩的（「还有一个」）也算话。
  const FILLER_HEAD_RE = /^(还有|再有|再来|再加|以及|另外|另|然后|最后|准备|打算|想做|做个|做点|来点|来份|来一份|来一盘|点个|点份|加|[一二三四五六七八九十两\d]+ ?[道份盘碗个])+/;
  // 「关于这桌人」的句子：忌口、人数、场合、预算。这些不是菜名。
  const NOTE_RE = /不吃|不敢吃|不能吃|吃不了|不喝|忌口|忌讳|忌|过敏|别上|别放|不放|不要|喜欢|爱吃|爱喝|偏好|口味|来吃饭|来吃|吃饭|几个人|[一两二三四五六七八九十\d]+ ?个人|个人|这桌|那桌|预算|多少钱|随便|就行|够了|注意|提醒|菜单|点菜|订餐|外卖/;
  // 忌口要落在否定上：「有人不吃辣」算忌辣，「他最爱吃辣」不算。
  const NEG_RE = /不吃|不敢吃|不能吃|吃不了|不喝|忌口|忌讳|忌|过敏|别上|别放|不放|不要|少放/;
  const POS_RE = /喜欢|爱吃|爱喝|偏好|无辣不欢|就好|就好吃/;
  // 一句话里可以两个方向都有：「不吃香菜但爱吃辣」。整句一起判会连香菜一起放过，
  // 所以先按转折词劈开，逐小句判否定/肯定——「但」前面那句才是这一桌的雷。
  const TURN_RE = /但|可是|不过|然而|虽然/;
  // 波浪号、间隔号这类装饰性收尾：「沙拉～」当菜名端出来就是一张废纸。
  const MENU_TRIM_RE = /^[\s、，,。.!！?？~～〜·・]+|[\s、，,。.!！?？~～〜·・]+$/g;
  // 一个片段里连一个字/字母/数字都没有（只剩 🍕 🥗 这类表情）就不是菜，也不值得回显。
  const MENU_REAL_RE = /[\u4e00-\u9fa5A-Za-z0-9]/;

  /** 把菜单文本分成「菜」和「话」。顺序即出现顺序，两端一致。 */
  function menuItems(menuText) {
    const dishes = [], notes = [];
    String(menuText || "").split(SPLIT_MENU_RE).forEach((seg) => {
      const raw = seg.trim().replace(MENU_TRIM_RE, "");
      if (!raw || !MENU_REAL_RE.test(raw)) return;
      const s = raw.replace(FILLER_HEAD_RE, "").trim().replace(MENU_TRIM_RE, "");
      if (!s || NOTE_RE.test(s)) { notes.push(s || raw); return; }
      dishes.push(s);
    });
    return { dishes, notes };
  }

  /** 从「话」里捞出忌口：命中否定词、且句子里有这味忌口的关键词才算。
   *  已经有人挂了签的不重复记（那是本人说的，比猜出来的可信）。
   *  遍历 CHIP_MAP 的声明序——Python 的 dict 也是这个序，换成按文本位置排就漂了。 */
  function chipsInNotes(notes, known) {
    const out = [];
    notes.forEach((seg) => {
      String(seg).split(TURN_RE).forEach((clause) => {
        if (!clause.trim() || !NEG_RE.test(clause) || POS_RE.test(clause)) return;
        Object.keys(CHIP_MAP).forEach((c) => {
          if (known.indexOf(c) >= 0) return;
          if (out.some((x) => x.chip === c)) return;
          const keys = CHIP_MAP[c] || [];
          if (!keys.length) return;                       // 清淡没有关键词，不靠猜
          if (keys.some((k) => k && clause.includes(k))) out.push({ chip: c, from: clause.trim() });
        });
      });
    });
    return out;
  }

  /** 一道菜踩了哪些忌口，返回 { hits, blocked }。
   *  这一套判定有四种来源，缺一层就会说错话：
   *  1. HIDDEN——菜名关键词直接说明的隐藏成分（宫保 → 花生）
   *  2. CHIP_MAP——忌口词在菜名里的各种写法（内脏 ← 肝/腰/肚/肠/心/血）
   *  3. DISH_TAGS——菜库自己声明的 tags（小笼包含猪肉，名字里看不出来）
   *  4. 清淡这一档——只看做法词与「是否辣」，没有关键词可查
   *  v0.6.0 之前 wei() 与 dishBans() 各写了一遍，后写的漏了 1、3、4 三层，
   *  实测 63 道 × 11 种忌口里 6 组两边不一致：菜谱页对一个忌内脏的人说「能吃」，
   *  排桌页说「不能吃」。所以收成一个函数，两个入口都走它——**唯一口径**。 */
  function dishBlocked(dish, banSet) {
    const hits = new Set();
    Object.entries(HIDDEN).forEach(([k, arr]) => {
      if (dish.includes(k)) arr.forEach((x) => hits.add(x));
    });
    banSet.forEach((b) => {
      (CHIP_MAP[b] || [b]).forEach((k) => { if (k && dish.includes(k)) hits.add(b); });
    });
    // 菜库的 tags 也是成分信息：名字里不含原料字的菜（小笼包、干煸四季豆），
    // 只有这张表知道它含猪肉 / 辣。以前只读 HIDDEN 与 CHIP_MAP，于是忌猪肉的人
    // 看到的是「小笼包 · 全员安全」——这是会把人吃坏的那一种错。
    DISH_TAGS.forEach((d) => {
      if (dish.includes(d.n)) (d.tags || []).forEach((x) => hits.add(x));
    });
    const blocked = [...hits].filter((h) => banSet.has(h));
    // 菜库说它辣也算（手撕包菜、干煸四季豆 的名字里没有辣字）：只看菜名的话，
    // 同一样成分会因为名字的写法不同落进不同一层。
    if (banSet.has("清淡") && (QINGDAN_RE.test(dish) || hits.has("辣")) && !blocked.includes("辣")) {
      blocked.push("清淡");
    }
    return { hits, blocked };
  }

  function wei(menuText, people, mode) {
    const { dishes: lines, notes } = menuItems(menuText);
    const chipBans = [];
    (people || []).forEach((p) => (p.chips || []).forEach((c) => {
      if (chipBans.indexOf(c) < 0) chipBans.push(c);
    }));
    const inferred = chipsInNotes(notes, chipBans);
    const bans = chipBans.concat(inferred.map((x) => x.chip));
    const banSet = new Set(bans);

    const safe = [], risk = [], boom = [];
    const kinds = { 荤: 0, 素: 0, 汤: 0, 主食: 0, 其他: 0 };

    lines.forEach((dish) => {
      const { hits, blocked } = dishBlocked(dish, banSet);
      const kind = dishKind(dish);
      kinds[kind] = (kinds[kind] || 0) + 1;
      if (blocked.length) boom.push({ dish, why: blocked.join(" / "), kind });
      else if (hits.size) risk.push({ dish, why: [...hits].join(" / "), kind });
      else safe.push(dish);
    });

    const plan = tablePlan((people || []).length, kinds);
    const suggest = (safe.length ? safe : risk.map((r) => r.dish)).slice(0, 8);
    return {
      safe, risk, boom, suggest,
      kinds,
      plan,
      add: recommend(plan.gap, banSet, lines),
      dupes: findDupes(lines),
      order: servingOrder(lines, mode, new Set(boom.map((x) => x.dish))),
      hasMenu: lines.length > 0,
      bans, chipBans, notes, inferred
    };
  }

  /* ==================== 言笺 ==================== */

  const KINDS = [
    { key: "要买", re: /买|下单|带一|带瓶|带个|药|票|快递|取件|代购|补货/ },
    { key: "已定", re: /就定|就这样|定了|决定|那就|同意|成交|说定|约好|确认|可以了|行吧/ },
    { key: "还没说清", re: /再说|不确定|看看|可能|或者|到时|改天|待定|再议|回头说/ },
    { key: "待办", re: /记得|务必|需要|下周|明天|后天|截止|之前|安排|处理|提交|预约|发我|拿一下|别忘了|跟进|催|让我|叫我/ }
  ];

  const WD = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 日: 7, 天: 7 };

  /**
   * 本地零点的 年/月/日；不存在的日子（2月31日、6月31日）钳到当月最后一天。
   * 不钳的话 JS 会静默滚到下个月，而文案还写原来的月日——时间戳和文字对不上。
   * month 是 0 基。与 gateway.py 的 clamp_date 同口径。
   */
  function clampDate(year, month, day) {
    const last = new Date(year, month + 1, 0).getDate();
    return new Date(year, month, Math.min(day, last));
  }

  /** 从一句话里抽时间点，返回 { text, at } 或 null。 */
  function parseTime(line, now) {
    const d = new Date(now);
    const stamp = (date, text) => ({ text, at: date.getTime() });

    let m = line.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]/);
    if (m) {
      const mo = +m[1], day = +m[2];
      if (mo < 1 || mo > 12 || day < 1 || day > 31) return null;   // 99月5日 这种不当时间处理
      let t = clampDate(d.getFullYear(), mo - 1, day);
      if (t.getTime() < d.getTime() - 86400000 * 180) t = clampDate(t.getFullYear() + 1, mo - 1, day);
      return stamp(t, `${t.getMonth() + 1}月${t.getDate()}日`);
    }
    if (/大后天/.test(line)) return stamp(new Date(d.getTime() + 3 * 86400000), "大后天");
    if (/后天/.test(line)) return stamp(new Date(d.getTime() + 2 * 86400000), "后天");
    if (/明天|明日/.test(line)) return stamp(new Date(d.getTime() + 86400000), "明天");
    if (/今天|今日|今晚|今天晚上/.test(line)) return stamp(d, /今晚|今天晚上/.test(line) ? "今晚" : "今天");

    m = line.match(/(下+|本|这)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天])/);
    if (m) {
      const target = WD[m[2]];
      const cur = d.getDay() === 0 ? 7 : d.getDay();
      let add = target - cur;
      const isNext = (m[1] || "").startsWith("下");
      if (isNext) add += 7;
      else if (add < 0) add += 7;   // add === 0 就是今天，比如今天周四说「周四前」
      const t = new Date(d.getTime() + add * 86400000);
      return stamp(t, (isNext ? "下" : "这") + "周" + m[2]);
    }
    if (/(\d{1,2})\s*[日号](?![前内])/.test(line)) {
      m = line.match(/(\d{1,2})\s*[日号](?![前内])/);
      const day = +m[1];
      if (day >= 1 && day <= 31) {
        let t = clampDate(d.getFullYear(), d.getMonth(), day);
        if (t.getTime() < d.getTime() - 86400000) t = clampDate(d.getFullYear(), d.getMonth() + 1, day);
        return stamp(t, `${t.getMonth() + 1}月${t.getDate()}日`);
      }
    }
    if (/月底|月末/.test(line)) {
      return stamp(new Date(d.getFullYear(), d.getMonth() + 1, 0), "月底");
    }
    return null;
  }

  // 说话人：行首「某某：」冒号前缀（1-4 个汉字）。前缀命中时间词或功能标签时不标，
  // 防止「明天：交房租」被当成自我介绍。与 gateway.py 的 SPEAKER_* 逐字一致。
  const SPEAKER_RE = /^([\u4e00-\u9fa5]{1,4})[：:]/;
  const SPEAKER_TIME_STOP = /今天|明天|后天|大后天|下周|本周|这周|周末|周中|[周星期拜][一二三四五六日天]|月底|月中|月初|年底|中午|晚上|下午|早上|[\u4e00-\u9fa5]{1,2}月[\u4e00-\u9fa5]{0,2}[日号]/;
  const SPEAKER_TAG_STOP = /要买|待办|提醒|注意|备注/;

  // who 否决词：命中即不出人名（时间/转场/指代/动作词）。
  const WHO_STOP_RE = /快|没|不|了|要|买|发|拿|再说|时间|时候|现在|回头|等下|大家|我们|你们|他们/;
  // 连接副词：{2,3} 贪心捕获会把它吃进人名（「小王再说」→「小王再」），末尾剥一个收口。
  const WHO_TAIL_ADVERB_RE = /[再又还也就才都先]$/;

  function yan(text) {
    const lines = String(text || "")
      .split(/[\n。！？!?；;]/).map((s) => s.trim()).filter((s) => s.length > 1);
    const out = { 待办: [], 要买: [], 已定: [], 还没说清: [] };
    const now = Date.now();

    lines.forEach((line) => {
      let hit = null;
      for (const k of KINDS) if (k.re.test(line)) { hit = k.key; break; }
      const t = parseTime(line, now);
      if (!hit) {
        if (/(明天|下周|记得|帮|要)/.test(line)) hit = "待办";
        // 「周五把合同寄出」这种——有能解析出的日期、又是「把 X 怎么着」的句式，
        // 以前两边都不认，整句被静默丢掉。只兜「本来会被扔掉的行」，不改已分类的结果。
        else if (t && /把.+/.test(line)) hit = "待办";
        else return;
      }
      const item = { line: line.slice(0, 60), when: null, who: null, speaker: null };
      if (t) item.when = t;
      // 只认「某某说 / 让我 / 叫我」这类明确指认，避免把「药快没了帮我买」当成人名；
      // 否决词含时间/转场停用词，防止「时间再说周五交稿」误判出 who=时间再。
      // {2,3} 贪心会把「小王再说」吃成「小王再」：末尾剥单个连接副词收口成纯人名，
      // 剥后不足 2 字（「他又让我」→「他」）则不给。与 gateway.py 逐字一致。
      const w = line.match(/^([\u4e00-\u9fa5]{2,3})(?=说|让我|叫我|答应|要求|问)/);
      if (w) {
        const raw = w[1];
        const name = raw.replace(WHO_TAIL_ADVERB_RE, "");
        if (name.length >= 2 && !WHO_STOP_RE.test(raw) && !WHO_STOP_RE.test(name)) item.who = name;
      }
      // 说话人：冒号前缀原样保留（不去前缀、不改写），line 保持原文与截断逻辑不变
      const sp = line.match(SPEAKER_RE);
      if (sp && !SPEAKER_TIME_STOP.test(sp[1]) && !SPEAKER_TAG_STOP.test(sp[1])) item.speaker = sp[1];
      out[hit].push(item);
    });

    let ask = "要不要把截止日期说死？";
    // 追问是念给用户听的一句话，卡片上已经盖了说话人的签：这里再引一遍「小王：」
    // 就成了两个人在说话。只动这一处引用——line 本身留着原话，复制整张笺要它。
    const quoted = (x) => {
      const rest = x.speaker && x.line.startsWith(x.speaker) ? x.line.slice(x.speaker.length) : "";
      return /^[：:]/.test(rest) ? rest.slice(1) : x.line;
    };
    // 也不许整句抄回来：实测一条 46 字的待办把追问撑成满屏的字，读的人找不到重点。
    // 截到 22 字（390 宽上两行以内）加省略号。line 仍是全文。
    const brief = (s) => (s.length <= 22 ? s : s.slice(0, 21) + "…");
    if (out["还没说清"][0]) {
      ask = `「${brief(quoted(out["还没说清"][0]))}」这件事，时间定在哪天？`;
    } else if (out["待办"][0]) {
      ask = `「${brief(quoted(out["待办"][0]))}」谁来做、什么时候？`;
    }
    const total = Object.values(out).reduce((a, b) => a + b.length, 0);
    return { ...out, ask, total };
  }

  /**
   * 仅供 test/consistency.py 做全表对账：判定函数的用例覆盖不到词表尾部，
   * 一端偷偷加一条菜/改一个字，只有整张表逐字逐序比才能炸出来。
   * 正则以 .source 文本比，gateway.py 侧对应 .pattern。
   */
  const TABLES = {
    HIDDEN, CHIP_MAP, DISHES, MAINS,
    RE: {
      MEAT: MEAT_RE.source, VEG: VEG_RE.source, SPICY: SPICY_RE.source,
      SOUP: SOUP_RE.source, STAPLE: STAPLE_RE.source, COLD: COLD_RE.source, HEAVY: HEAVY_RE.source,
      QINGDAN: QINGDAN_RE.source,
      SEASONAL: SEASONAL_RE.source,
      SEASON_SUMMER: SEASON_SUMMER_RE.source, SEASON_WINTER: SEASON_WINTER_RE.source,
      WHO_STOP: WHO_STOP_RE.source, WHO_TAIL_ADVERB: WHO_TAIL_ADVERB_RE.source,
      SPEAKER: SPEAKER_RE.source, SPEAKER_TIME_STOP: SPEAKER_TIME_STOP.source,
      SPEAKER_TAG_STOP: SPEAKER_TAG_STOP.source,
      MENU_SPLIT: SPLIT_MENU_RE.source, MENU_FILLER: FILLER_HEAD_RE.source,
      MENU_NOTE: NOTE_RE.source, MENU_NEG: NEG_RE.source, MENU_POS: POS_RE.source,
      MENU_TURN: TURN_RE.source, MENU_TRIM: MENU_TRIM_RE.source, MENU_REAL: MENU_REAL_RE.source,
      KINDS: KINDS.map((k) => ({ key: k.key, source: k.re.source }))
    },
    // 排桌口径：两端都得是「四舍五入向上」，阈值也要一样
    NUM: { SAME_CAT_STOP, SAME_CAT_HOLD, CROSS_CAT_HOLD, STALE }
  };

  return {
    analyze, yi, wei, yan, parseTime, tablePlan, dishKind,
    recommend, findDupes, servingOrder, servingStage, isSeasonal, seasonOf, DISHES, TABLES,
    menuItems,
    verticalCols, vCost, vClusters,
    /* v0.6.0：颜色换算是「你的三种颜色 / 色相分桶」那一类功能的唯一口径。
       以前 hexToRgb / rgbToHsl 只在引擎内部用，外层要用就各自抄一份——
       而「怎么把色值变成一个色相」这种规则抄一份漂一份。这里只读导出，不改任何判定。 */
    hexToRgb, rgbToHsl, rgbToHex, toneOf, deltaE, rgbToLab,
    /* v0.6.0：菜谱页与「今晚吃什么」要把菜库拍平成一张表。
       以前只有 DISHES 这个二维结构，调用方各自 Object.keys 拍平一遍——那是第二份定义。
       这个函数是**只读**的：返回的是新对象数组，改它不会动到 DISHES。 */
    dishesOf() {
      const out = [];
      Object.keys(DISHES).forEach((kind) => {
        (DISHES[kind] || []).forEach((d) => {
          out.push({ name: d.n, kind, tags: Array.isArray(d.tags) ? d.tags.slice() : [] });
        });
      });
      return out;
    },
    /* 这道菜会让哪些忌口的人吃不了：与 wei() 同一个判定（dishBlocked），
       所以这里返回的就是排桌页会亮红灯的那几个词。返回忌口词数组（可能为空）。
       v0.6.0 之前这里是「只看 tags + 菜名字面」的第二份实现，漏了 HIDDEN / CHIP_MAP /
       清淡三层，于是菜谱页和一个忌内脏的人说「白灼菜心能吃」，排桌页说不能。
       现在两边同源：谁再想把判定抄一遍，先看这个名字。 */
    dishBans(dish, chips) {
      const has = Array.isArray(chips) ? chips : [];
      if (!dish || !has.length) return [];
      return dishBlocked(String(dish.name || ""), new Set(has)).blocked;
    },
  };
})();
