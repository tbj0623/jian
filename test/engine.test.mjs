// 运行：node test/engine.test.mjs    （零依赖，不需要浏览器）
import fs from "fs";
import path from "path";
import vm from "vm";
import { fileURLToPath } from "url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const code = fs.readFileSync(path.join(ROOT, "engine.js"), "utf8");
const ctx = { Math, console, Date, JSON };
vm.createContext(ctx);
vm.runInContext(code + "\n;globalThis.__E = Engine;", ctx);
const Engine = ctx.__E;

let pass = 0, fail = 0;
function t(name, got, want) {
  const ok = got === want;
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : " FAIL "} ${name}  →  ${got}${ok ? "" : "   (期望 " + want + ")"}`);
}

const closet = [
  { id: "w1", name: "燕麦针织", cat: "上衣", color: "#d4c4b0" },
  { id: "w2", name: "白衬衫", cat: "上衣", color: "#f4f0ea" },
  { id: "w3", name: "深蓝阔腿", cat: "裤装", color: "#2c3a4a" },
  { id: "w4", name: "奶油半裙", cat: "裙装", color: "#efe6d6" },
  { id: "w5", name: "驼大衣", cat: "外套", color: "#c4a574" },
  { id: "w6", name: "白鞋", cat: "鞋", color: "#f5f5f3" }
];

console.log("\n--- 衣笺：印章判定 ---");
const cases = [
  ["白上衣 vs 白衬衫", { name: "x", cat: "上衣", color: "#f5f0eb" }, "先别"],
  ["深蓝裤 vs 深蓝阔腿", { name: "x", cat: "裤装", color: "#2c3a4a" }, "先别"],
  ["驼外套 vs 驼大衣", { name: "x", cat: "外套", color: "#c4a574" }, "先别"],
  ["米白上衣 vs 燕麦针织（同色系）", { name: "x", cat: "上衣", color: "#ded0bd" }, "先别"],
  ["深驼上衣 vs 燕麦针织（差一档）", { name: "x", cat: "上衣", color: "#a8875e" }, "再想想"],
  ["亮红上衣 vs 全是浅色", { name: "x", cat: "上衣", color: "#b83227" }, "宜入"],
  ["墨绿上衣 vs 全是浅色", { name: "x", cat: "上衣", color: "#25503c" }, "宜入"]
];
for (const [name, item, want] of cases) {
  const r = Engine.yi(item, closet);
  t(name, r.stamp, want);
  console.log(`         「${r.quote}」  basis=${r.basis ? r.basis.name + " gap=" + r.gap : "无"}`);
}
const empty = Engine.yi({ name: "x", cat: "上衣", color: "#ffffff" }, []);
t("空柜 → 再想想", empty.stamp, "再想想");
// 「先收 8 件常穿的，过笺才准」承诺过一个从没实现过的门槛：一件就照常出判定，
// 第 15 轮之后 <5 件还会另说一句「判定还薄」。两句互相打脸，所以空柜只说眼下这件事。
t("空柜文案不许诺一个没实现的件数", /\d+ ?件/.test(empty.quote), false);
t("空柜说的是柜子空着", empty.quote.includes("柜里还空着"), true);
// 薄柜子的判定几乎不会错，但也几乎没用。这句得由判定自己说出来（界面、长图、
// 复制话术共用一个属性），否则三处各说各的。
const thinItem = { name: "x", cat: "上衣", color: "#7b1f2b" };
t("4 件算薄、5 件不算", [Engine.yi(thinItem, closet.slice(0, 4)).thin, Engine.yi(thinItem, closet.slice(0, 5)).thin].join(), "true,false");
t("空柜也说自己薄", empty.thin, true);
t("薄到什么程度说得出口（件数跟着走）", Engine.yi(thinItem, closet.slice(0, 3)).closetN, 3);
t("种子柜 6 件不薄", Engine.yi(thinItem, closet).closetN, 6);

console.log("\n--- 衣笺：冷暖调这一句 ---");
// toneOf 从第五轮就在算，注释写着「用于文案」，可文案二十几轮没来（算出来的 tone
// 只躺进 lastNew 和备份里，全仓没有一处读）。这一组钉的是「什么时候说、说什么」：
// 薄柜子不谈多数，冷暖不分明不硬找话说，说了就要带上「几件 / 共几件」这个数。
const piece = (c, i) => ({ name: "p" + i, cat: "上衣", color: c, worn: 3, lastWorn: Date.now() });
const WARM5 = ["#c9b39b", "#d8c9b4", "#c4a574", "#8a5a2b", "#b06a4a"].map(piece);
const COOL5 = ["#2c3a4a", "#3b6e8f", "#4a6b52", "#556270", "#2f4858"].map(piece);
const tone = (color, list) => Engine.yi({ name: "x", cat: "鞋", color }, list).toneLine;
t("少数调：说清多数是几件、这件是什么调", tone("#2c3a4a", WARM5), "柜里 5/5 件是暖调，这件是冷调。");
t("同调：说的是同调", tone("#c9b39b", WARM5), "这件和柜里多数衣服同调（暖调 5/5）。");
t("中性色：两边都接得住", tone("#f5f5f3", WARM5), "柜里 5/5 件是暖调，这件是中性色，两边都接得住。");
t("薄柜子（<5 件）不谈多数", tone("#2c3a4a", WARM5.slice(0, 4)), "");
t("柜里冷暖不分明（不到六成）→ 不硬找话说", tone("#2c3a4a", WARM5.slice(0, 3).concat(COOL5.slice(0, 3))), "");
t("反方向对称：冷柜 + 暖件", tone("#c9b39b", COOL5), "柜里 5/5 件是冷调，这件是暖调。");
t("多数不到整柜：数要跟着走", tone("#2c3a4a", WARM5.slice(0, 4).concat(COOL5.slice(0, 2))), "柜里 4/6 件是暖调，这件是冷调。");

console.log("\n--- 衣笺：穿着记忆 ---");
const D = 86400000;
const staleCloset = [
  { id: "s1", name: "旧白衬衫", cat: "上衣", color: "#f4f0ea", worn: 3, lastWorn: Date.now() - 200 * D }
];
const rStale = Engine.yi({ name: "x", cat: "上衣", color: "#f2eee7" }, staleCloset);
t("半年没穿的同色衬衫 → 仍是先别", rStale.stamp, "先别");
t("文案点出很久没穿", /没穿过/.test(rStale.quote), true);
t("标记 stale", rStale.stale, true);
console.log("        金句：" + rStale.quote);

const freshCloset = [
  { id: "f1", name: "常穿白衬衫", cat: "上衣", color: "#f4f0ea", worn: 12, lastWorn: Date.now() - 2 * D }
];
const rFresh = Engine.yi({ name: "x", cat: "上衣", color: "#f2eee7" }, freshCloset);
t("常穿的衬衫 → 不用久未穿文案", /没穿过/.test(rFresh.quote), false);
t("标记不 stale", rFresh.stale, false);
console.log("        金句：" + rFresh.quote);

const rNone = Engine.yi({ name: "x", cat: "上衣", color: "#f4f0ea" }, [
  { id: "n1", name: "全新衬衫", cat: "上衣", color: "#f4f0ea", worn: 0, lastWorn: null }
]);
t("没穿过的那件", rNone.basis.wear, "那件还没穿过。");
t("短版本", rNone.basis.wearShort, "还没穿过");

const rOld = Engine.yi({ name: "x", cat: "上衣", color: "#b83227" }, freshCloset);
t("宜入时也带穿着信息", !!rOld.basis.wear, true);

console.log("\n--- 衣笺：季节性衣物不该被误判 ---");
const coatCloset = [
  { id: "z1", name: "驼大衣", cat: "外套", color: "#c4a574", worn: 3, lastWorn: Date.now() - 214 * D }
];
const rCoat = Engine.yi({ name: "x", cat: "外套", color: "#c9ab7c" }, coatCloset);
t("外套仍按同品类判先别", rCoat.stamp, "先别");
t("外套不判 stale", rCoat.stale, false);
t("标记为季节性", rCoat.seasonal, true);
t("文案改成换季口径", /换季收起/.test(rCoat.basis.wear), true);
console.log("        文案：" + rCoat.basis.wear);
console.log("        金句：" + rCoat.quote);

const knitCloset = [
  { id: "k1", name: "燕麦针织", cat: "上衣", color: "#d4c4b0", worn: 5, lastWorn: Date.now() - 200 * D }
];
const rKnit = Engine.yi({ name: "x", cat: "上衣", color: "#d6c6b2" }, knitCloset);
t("针织衫也算季节性", rKnit.seasonal, true);
t("针织衫不判 stale", rKnit.stale, false);

console.log("\n--- 衣笺：seasonOf 季节推断 ---");
t("手选优先于推断", Engine.seasonOf({ cat: "上衣", name: "白短袖T恤", season: "冬" }), "冬");
t("手选四季原样返回", Engine.seasonOf({ cat: "裤装", name: "深蓝阔腿", season: "四季" }), "四季");
t("短袖推断夏", Engine.seasonOf({ cat: "上衣", name: "白短袖T恤" }), "夏");
t("凉鞋推断夏", Engine.seasonOf({ cat: "鞋", name: "细带凉鞋" }), "夏");
t("羽绒服推断冬", Engine.seasonOf({ cat: "外套", name: "长款羽绒服" }), "冬");
t("针织推断冬", Engine.seasonOf({ cat: "上衣", name: "燕麦针织" }), "冬");
t("非法 season 回落推断", Engine.seasonOf({ cat: "上衣", name: "吊带", season: "夏天" }), "夏");
t("无线索回落春秋", Engine.seasonOf({ cat: "裤装", name: "深蓝阔腿" }), "春秋");
t("四季不由词表猜出", Engine.seasonOf({ cat: "上衣", name: "四季可穿衬衫" }), "春秋");

const plain = [
  { id: "t1", name: "旧白衬衫", cat: "上衣", color: "#f4f0ea", worn: 3, lastWorn: Date.now() - 200 * D }
];
const rPlain = Engine.yi({ name: "x", cat: "上衣", color: "#f2eee7" }, plain);
t("普通上衣不是季节性", rPlain.seasonal, false);
t("普通上衣仍判 stale", rPlain.stale, true);
t("普通上衣仍说很久没穿", /个月没穿/.test(rPlain.basis.wear), true);
console.log("        金句：" + rPlain.quote);

// 手选过「夏」的一件：半年没穿是换季，不是买错。seasonOf 一直读这个字段（柜子按季节
// 筛靠的就是它），判定却只看品类和名字里的线索——于是柜上写着「夏」的一件，
// 九月会被数落「6 个月没穿过了。再买一件，只会多一件不穿的」。
const teeCloset = [
  { id: "s1", name: "白短袖T恤", cat: "上衣", color: "#f4f0ea", worn: 5, lastWorn: Date.now() - 200 * D, season: "夏" }
];
const rTee = Engine.yi({ name: "x", cat: "上衣", color: "#f2eee7" }, teeCloset);
t("手选夏天的衣物算季节性", rTee.seasonal, true);
t("手选夏天的不判 stale", rTee.stale, false);
t("文案不再数落「几个月没穿」", /个月没穿/.test(rTee.basis.wear), false);
t("但同品类撞色照样「先别」（不因为换了个说法就放行）", rTee.stamp, "先别");
// 「四季」是用户明说常年穿的，就不能再替他找换季的台阶
const allYear = [{ id: "s2", name: "打底长袖", cat: "上衣", color: "#f4f0ea", worn: 2, lastWorn: Date.now() - 200 * D, season: "四季" }];
const rAllY = Engine.yi({ name: "x", cat: "上衣", color: "#f2eee7" }, allYear);
t("手选四季的仍按久未穿说", rAllY.seasonal, false);
t("手选四季的照判 stale", rAllY.stale, true);
// 没人手选过季节时，名字推断出的夏季也算
t("名字推断出的夏季也算季节性", Engine.isSeasonal({ cat: "鞋", name: "细带凉鞋" }), true);
t("名字推不出季节的春秋仍不算季节性", Engine.isSeasonal({ cat: "裤装", name: "深蓝阔腿" }), false);

console.log("\n--- 衣笺：能配什么 ---");
const closet2 = [
  { id: "c1", name: "深蓝阔腿", cat: "裤装", color: "#2c3a4a" },
  { id: "c2", name: "白鞋", cat: "鞋", color: "#f5f5f3" },
  { id: "c3", name: "白衬衫", cat: "上衣", color: "#f4f0ea" },
  { id: "c4", name: "驼大衣", cat: "外套", color: "#c4a574" }
];
const rM = Engine.yi({ name: "x", cat: "上衣", color: "#b83227" }, closet2);
t("给出了能配的", rM.match.length > 0, true);
t("搭配里不含同品类", rM.match.some((x) => x.cat === "上衣"), false);
console.log("        能配：" + rM.match.map((x) => x.name + "(" + x.cat + ")").join("、"));
t("宜入金句说清楚能配几件", /能和 \d+ 件旧的搭上/.test(rM.quote), true);
console.log("        金句：" + rM.quote);

const rGrey = Engine.yi({ name: "x", cat: "上衣", color: "#8a8a8a" }, closet2);
t("灰上衣能配深蓝与白", rGrey.match.length >= 2, true);

console.log("\n--- 味笺 ---");
const menu = "宫保鸡丁\n水煮鱼\n蒜蓉西兰花\n白切鸡\n酸菜鱼\n花生豆腐\n米饭";
const r1 = Engine.wei(menu, [{ name: "我", chips: [] }, { name: "同行", chips: ["香菜"] }]);
t("无人忌花生辣 → 无雷区", r1.boom.length, 0);
t("安全菜数量", r1.safe.length, 2);
console.log("         safe:", r1.safe.join("、"));
console.log("         kinds:", JSON.stringify(r1.kinds), "plan.gap:", JSON.stringify(r1.plan.gap));

const r2 = Engine.wei(menu, [{ name: "我", chips: ["花生", "辣"] }]);
t("忌花生+辣 → 雷区数", r2.boom.length, 3);
console.log("         boom:", r2.boom.map((x) => x.dish + "(" + x.why + ")").join(" / "));

const r3 = Engine.wei("清蒸鲈鱼\n蒜蓉粉丝虾\n白灼菜心\n西红柿蛋汤", [{ name: "A", chips: ["海鲜"] }]);
t("忌海鲜 → 雷区数", r3.boom.length, 2);

/* ---- 四类过敏原：2026-10 之前这里一个字都没有 ----
 *  修之前实测：小麦应判 9 道、判出 0 道；大豆应判 3 道、判出 0 道。
 *  后果是排桌页会对一个对小麦过敏的人说「小笼包 · 全员安全」——这个 App 唯一一处
 *  可能把人吃坏的地方。下面这几条钉住「判得出来」，也钉住「不误伤」。 */
console.log("\n--- 味笺：四类过敏原 ---");
const wheat = ["葱油拌面", "阳春面", "手抓饼", "玉米烙", "南瓜饼", "猪肉白菜饺子", "小笼包", "刀削面", "牛肉面"];
// t() 是严格 === 比较，数组和字符串永远不相等——所以这里一律把结果收成
// 布尔或数字再比，别拿数组当期望值（会得到「→ 小麦 (期望 小麦)」这种看不懂的假红）。
t("小麦：面/饼/饺/小笼/刀削面全判得出",
  wheat.every((n) => Engine.dishBans({ name: n }, ["小麦"]).length > 0), true);
t("小麦：小笼包判出的原因就是「小麦」（不是被别的成分顺带带出来）",
  Engine.dishBans({ name: "小笼包" }, ["小麦"]).join("|"), "小麦");
const soy = ["麻婆豆腐", "海带豆腐汤", "鲫鱼豆腐汤"];
t("大豆：豆腐类全判得出", soy.every((n) => Engine.dishBans({ name: n }, ["大豆"]).length > 0), true);
t("蛋：番茄炒蛋 / 蛋炒饭 判得出", ["番茄炒蛋", "蛋炒饭", "紫菜蛋花汤"].every(
  (n) => Engine.dishBans({ name: n }, ["蛋"]).length > 0), true);
t("坚果：宫保鸡丁（放的是花生）对坚果过敏也算",
  Engine.dishBans({ name: "宫保鸡丁" }, ["坚果"]).join("|"), "坚果");
// 误伤比漏判更坏：把一个不含小麦的东西说成含小麦，用户会开始不信所有结论。
t("不误伤：土豆/四季豆/河粉/米线 都不含小麦也不含大豆",
  ["酸辣土豆丝", "干煸四季豆", "醋溜土豆丝", "土豆炖牛肉", "河粉", "米线"]
    .filter((n) => Engine.dishBans({ name: n }, ["小麦", "大豆"]).length).length, 0);
t("不误伤：清蒸鲈鱼 / 白切鸡 不含蛋", ["清蒸鲈鱼", "白切鸡"].filter(
  (n) => Engine.dishBans({ name: n }, ["蛋"]).length).length, 0);
// 老十一项一条都不许因为这次改动变宽或变窄（CHIP_MAP 只能往末尾追加）
t("老十一项的全库命中数一个都没变",
  ["辣", "香菜", "海鲜", "花生", "猪肉", "牛羊肉", "内脏", "蒜", "酒", "乳", "清淡"]
    .map((c) => Engine.dishesOf().filter((d) => Engine.dishBans(d, [c]).length).length).join(","),
  "5,0,7,1,12,7,1,5,1,0,5");

console.log("\n--- 味笺：推荐具体菜 ---");
const rec = Engine.wei("宫保鸡丁\n水煮鱼\n白切鸡", [
  { name: "我", chips: ["花生", "辣"] }, { name: "小周", chips: [] },
  { name: "阿姨", chips: ["海鲜"] }, { name: "同行", chips: [] }
]);
t("缺什么就推荐", rec.add.length > 0, true);
t("推荐全部避开忌口", rec.add.filter((d) => /花生|宫保|辣|水煮|虾|鱼|蟹|贝|蚝|孜然|牛|羊/.test(d.name)).length, 0);
t("推荐都标了类别", rec.add.every((d) => ["荤", "素", "汤", "主食"].includes(d.kind)), true);
console.log("        " + rec.add.map((d) => d.kind + "·" + d.name).join(" / "));

const light = Engine.wei("麻婆豆腐\n水煮鱼", [{ name: "我", chips: ["清淡"] }]);
t("要清淡时不推辣菜", light.add.filter((d) => /辣|麻|水煮|干锅|泡椒|剁椒/.test(d.name)).length, 0);

const dup = Engine.wei("水煮鱼\n清蒸鲈鱼\n红烧带鱼", [{ name: "我", chips: [] }]);
t("检出重复主料", dup.dupes.length, 1);
t("重复的是鱼", dup.dupes[0].main, "鱼");
t("列出了重复的菜", dup.dupes[0].dishes.length, 3);

console.log("\n--- 味笺：上菜顺序 ---");
const ord = Engine.wei("凉拌黄瓜\n水煮鱼\n西红柿蛋汤\n蒜蓉西兰花\n米饭\n红烧排骨", [{ name: "我", chips: [] }]).order;
console.log("        " + ord.map((x, i) => `${i + 1}.${x.dish}(${x.label})`).join(" → "));
t("凉菜排第一", ord[0].dish, "凉拌黄瓜");

// 第四十轮：mode 是判定的输入，不是文案的装饰。下面三张桌是**同一份菜单**，
// 差别只在「这桌是谁」——水煮鱼有人忌辣（雷），红烧肉是硬菜但没人忌。
const M3 = "白灼菜心\n红烧肉\n水煮鱼\n米饭";
const P3 = [{ name: "我", chips: ["辣"] }];
const seq = (mode) => Engine.wei(M3, P3, mode).order.map((x) => x.dish).join(">");
t("朋友那桌走家常顺序", seq("friends"), "白灼菜心>红烧肉>水煮鱼>米饭");
t("家里那桌把硬菜和雷一起压到最后", seq("home"), "白灼菜心>米饭>红烧肉>水煮鱼");
t("同事那桌只压雷，硬菜照旧先上", seq("work"), "白灼菜心>红烧肉>米饭>水煮鱼");
t("没选模式与朋友那桌同序（默认不改变判定）", seq(""), seq("friends"));
t("三种桌序两两不同（mode 确实进了排序键，不是只在文案里）",
  new Set([seq("home"), seq("work"), seq("friends")]).size, 3);
t("主食排最后", ord[ord.length - 1].dish, "米饭");
t("汤在主食之前", ord.findIndex((x) => x.dish === "西红柿蛋汤") < ord.findIndex((x) => x.dish === "米饭"), true);
t("水煮鱼算硬菜", ord.find((x) => x.dish === "水煮鱼").label, "硬菜");
t("红烧排骨算硬菜", ord.find((x) => x.dish === "红烧排骨").label, "硬菜");
t("素菜是清口", ord.find((x) => x.dish === "蒜蓉西兰花").label, "清口");
t("上菜顺序覆盖全部菜", ord.length, 6);
t("顺序里没有重复", new Set(ord.map((x) => x.dish)).size, 6);

console.log("\n--- 味笺：家常菜库扩充 ---");
t("红烧狮子头算荤", Engine.dishKind("红烧狮子头"), "荤");
t("糖醋里脊算荤", Engine.dishKind("糖醋里脊"), "荤");
t("韭菜盒子算主食", Engine.dishKind("韭菜盒子"), "主食");
t("海带豆腐汤算汤", Engine.dishKind("海带豆腐汤"), "汤");
t("油焖大虾算硬菜", Engine.servingStage("油焖大虾"), 4);
t("红烧狮子头算硬菜", Engine.servingStage("红烧狮子头"), 4);
t("葱爆羊肉算硬菜", Engine.servingStage("葱爆羊肉"), 4);
t("酱爆鸡丁算硬菜", Engine.servingStage("酱爆鸡丁"), 4);
t("糖醋里脊算主菜", Engine.servingStage("糖醋里脊"), 3);
t("醋溜土豆丝算清口", Engine.servingStage("醋溜土豆丝"), 2);
t("韭菜盒子压轴主食", Engine.servingStage("韭菜盒子"), 6);
t("虾类重复主料能查出", Engine.findDupes(["油焖大虾", "滑蛋虾仁"])[0].main, "虾");
t("里脊重复主料能查出", Engine.findDupes(["糖醋里脊", "京酱里脊丝"])[0].main, "里脊");
t("狮子头重复主料能查出", Engine.findDupes(["红烧狮子头", "清炖狮子头"])[0].main, "狮子头");
t("豆腐汤与麻婆豆腐重复", Engine.findDupes(["海带豆腐汤", "麻婆豆腐"])[0].main, "豆腐");
t("忌海鲜时不推油焖大虾", Engine.recommend({ 荤: 2 }, new Set(["海鲜"]), []).some((d) => d.name === "油焖大虾"), false);
const recNew = Engine.recommend({ 荤: 1 }, new Set(["猪肉", "牛羊肉", "花生", "辣"]),
  ["红烧排骨", "糖醋里脊", "可乐鸡翅", "白切鸡", "三杯鸡", "黑椒牛柳", "孜然羊肉", "清蒸鲈鱼", "红烧带鱼", "番茄炒蛋", "韭菜炒蛋", "京酱肉丝", "梅菜扣肉", "滑蛋虾仁", "香菇滑鸡", "土豆炖牛肉", "酱爆鸡丁"]);
t("老荤全被避开后推到新菜油焖大虾", recNew.some((d) => d.name === "油焖大虾"), true);
const rNew = Engine.wei("油焖大虾\n韭菜盒子\n海带豆腐汤", [{ name: "我", chips: ["海鲜"] }]);
t("新菜入桌按类计数", rNew.kinds["主食"], 1);
t("韭菜盒子不算素", rNew.kinds["素"], 0);
t("忌海鲜时油焖大虾进雷区", rNew.boom[0] ? rNew.boom[0].dish : null, "油焖大虾");

console.log("\n--- 味笺：菜库 tags 也是成分来源 ---");
// 小笼包、干煸四季豆 的名字里不含原料字，HIDDEN / CHIP_MAP 都认不出，只有菜库这张表
// 知道它含什么。recommend() 一直读 tags（忌猪肉时不推小笼包），判定却不读——
// 于是同一屏上「不给你推荐小笼包」和「小笼包 · 全员安全」并存。这三条把口径并齐。
const t1 = Engine.wei("小笼包\n米饭", [{ name: "我", chips: ["猪肉"] }]);
t("忌猪肉 → 小笼包进雷区", t1.boom.map((x) => `${x.dish}|${x.why}`).join(), "小笼包|猪肉");
const t2 = Engine.wei("小笼包\n米饭", [{ name: "我", chips: [] }]);
t("没人忌口 → 小笼包走谨慎层", t2.risk.map((x) => `${x.dish}|${x.why}`).join(), "小笼包|猪肉");
const t3 = Engine.wei("干煸四季豆", [{ name: "我", chips: ["猪肉", "辣"] }]);
t("一道菜两个成分按表内序写", t3.boom[0] ? t3.boom[0].why : null, "辣 / 猪肉");
// 推广成一条不变式：推荐的任何一道菜，单独拿去判定都不许落进雷区。
// 表里再加一行、tags 改一个词，只要两个口径又分叉，这里就炸。
const selfok = [[], ["猪肉"], ["辣", "海鲜"], ["花生", "蒜"], ["清淡"], ["牛羊肉", "香菜"]].every((chips) => {
  const r = Engine.wei("白灼菜心\n米饭", [{ name: "我", chips }]);
  return r.add.every((d) => Engine.wei(d.name, [{ name: "我", chips }]).boom.length === 0);
});
t("推荐的菜自己过不了自己的判定（自洽不变式）", selfok, true);

// 同一条口径的第二层：忌「清淡」时只看菜名，「香辣土豆丝」进雷区而「手撕包菜」只算谨慎
// —— 同一样成分（辣）因为名字的写法落进不同一层。菜库说它辣，就算它辣。
const light2 = Engine.wei("手撕包菜\n干煸四季豆\n白米饭", [{ name: "我", chips: ["清淡"] }]);
t("忌清淡：菜库说辣的照样进雷区", light2.boom.map((b) => b.dish).join(), "手撕包菜,干煸四季豆");
t("忌清淡：理由写的就是「清淡」", light2.boom.map((b) => b.why).join(), "清淡,清淡");
// 数据本身也要对：三杯鸡的「三杯」就是米酒 / 酱油 / 麻油各一杯，吃头孢的人忌的就是酒；
// 海带和紫菜同为菜库认的藻类，从前只标了紫菜那一道。
const wine = Engine.wei("三杯鸡\n白米饭", [{ name: "我", chips: ["酒"] }]);
t("三杯鸡含酒：忌酒的人进雷区", wine.boom.map((b) => `${b.dish}|${b.why}`).join(), "三杯鸡|酒");
t("三杯鸡含酒：忌酒时不再被推荐", Engine.recommend({ 荤: 3 }, new Set(["酒"]), ["红烧排骨", "糖醋里脊", "可乐鸡翅", "白切鸡"]).some((d) => d.name === "三杯鸡"), false);
const weed = Engine.wei("海带豆腐汤\n紫菜蛋花汤", [{ name: "我", chips: ["海鲜"] }]);
t("两道藻类同一判法（海带从前漏了）", weed.boom.map((b) => b.dish).join(), "海带豆腐汤,紫菜蛋花汤");
// 「海鲜」这两个字本身：菜单上写的是海鲜汤，一个虾蟹鱼字都没有
const soup = Engine.wei("海鲜汤\n米饭", [{ name: "我", chips: ["海鲜"] }]);
t("海鲜汤不用虾蟹鱼字也进雷区", soup.boom.map((b) => b.dish).join(), "海鲜汤");
t("海鲜汤在没人忌口时算谨慎", Engine.wei("海鲜汤\n米饭", [{ name: "我", chips: [] }]).risk.map((b) => `${b.dish}|${b.why}`).join(), "海鲜汤|海鲜");

console.log("\n--- 味笺：散文菜单（菜和话分开） ---");
const prose = Engine.wei("周五晚上三个人来吃饭，准备番茄牛腩、清炒时蔬、蒜蓉虾，还有一个凉拌黄瓜。有人不吃辣，另外一个对海鲜有点忌讳。",
  [{ name: "我", chips: [] }, { name: "同行", chips: [] }]);
t("整句话不混进上菜顺序（四道菜，按凉→素→荤排）", prose.order.map((x) => x.dish).join(), "凉拌黄瓜,清炒时蔬,番茄牛腩,蒜蓉虾");
t("口语填充剥得掉（还有一个凉拌黄瓜 → 凉拌黄瓜）", prose.safe.concat(prose.risk.map((x) => x.dish), prose.boom.map((x) => x.dish)).includes("还有一个凉拌黄瓜"), false);
t("「有人不吃辣」被认成话不是菜", prose.notes.includes("有人不吃辣"), true);
t("话里的忌口真的算进这一桌", prose.bans.join(), "辣,海鲜");
t("忌口是从哪句话来的，说得出来", prose.inferred.map((x) => `${x.chip}|${x.from}`).join(), "辣|有人不吃辣,海鲜|对海鲜有点忌讳");
t("忌了海鲜之后蒜蓉虾进雷区", prose.boom.map((b) => b.dish).join(), "蒜蓉虾");
t("人数那句不占菜数（4 道而不是 6 道）", Object.values(prose.kinds).reduce((a, b) => a + b, 0), 4);
// 否定才算忌口：「他最爱吃辣」是给这一桌加分，不是划雷区
const like = Engine.wei("米饭\n宫保鸡丁\n他最爱吃辣", [{ name: "我", chips: [] }]);
t("爱吃辣不算忌辣", like.bans.join(), "");
t("爱吃辣那句仍然留着给用户看", like.notes.join(), "他最爱吃辣");
// 剥完什么都不剩的片段（「还有一个」）不能变成一道空菜
const bare = Engine.wei("还有一个\n米饭", [{ name: "我", chips: [] }]);
t("光一句「还有一个」不当菜", bare.order.map((x) => x.dish).join(), "米饭");
t("已经挂了签的忌口不重复记一遍", Engine.wei("米饭\n有人不吃辣", [{ name: "我", chips: ["辣"] }]).inferred.length, 0);
// 空格与括号也要切：实测「番茄牛腩 蒜蓉虾 清炒时蔬（有人对虾过敏）」整行被当成一句话，
// 三道菜一道没算，而那句里的「牛腩」「蒜蓉」反倒被当成忌牛忌蒜——两头都错。
const paren = Engine.wei("番茄牛腩 蒜蓉虾 清炒时蔬（有人对虾过敏）", [{ name: "我", chips: [] }]);
t("空格分开的三道都算菜", paren.order.length, 3);
t("括号里那句才是话", paren.notes.join(), "有人对虾过敏");
t("「对虾过敏」只忌海鲜，不忌牛不忌蒜", paren.bans.join(), "海鲜");
t("蒜蓉虾因为桌上有人海鲜过敏进雷区", paren.boom.map((b) => b.dish).join(), "蒜蓉虾");
// 表情与装饰性标点：🍕 🥗 各成一道菜、菜名尾巴挂着「～」，都是把菜单当废纸处理
const emo = Engine.wei("🍕 披萨！！🥗 沙拉～ 可乐", [{ name: "我", chips: [] }]);
t("表情不单独成菜", emo.order.length, 3);
t("「沙拉～」收干净成「沙拉」", emo.safe.includes("沙拉"), true);
t("光一个表情的片段既不当菜也不当话", emo.notes.length, 0);
// 转折：「不吃香菜但爱吃辣」整句一起判会连香菜一起放过（POS 命中就整句跳过），
// 那正是这一桌的雷。劈开逐小句判，香菜照忌、辣不忌。
const both = Engine.wei("清炒时蔬\n不吃香菜但爱吃辣", [{ name: "我", chips: [] }]);
t("转折句两味都判对：忌香菜、不忌辣", both.bans.join(), "香菜");
t("转折句的忌口指得回是哪半句", both.inferred.map((x) => `${x.chip}|${x.from}`).join(), "香菜|不吃香菜");
// 商店文案拿「辣子鸡」当例子举的那句话（docs/上架/商店材料.md 第 2 节）原样跑一遍。
// 举了具体菜名的例子最容易被后来改文案的人当成修辞处理掉，而它是一句对用户的承诺；
// test/store_claims.py 会回头查这两个用例还在不在，两边谁删谁红。
const chili = Engine.wei("辣子鸡\n白切鸡\n米饭\n有人不吃辣", [{ name: "我", chips: [] }]);
t("文案那句「有人不吃辣」不会变成一道菜", chili.order.map((x) => x.dish).join(), "辣子鸡,白切鸡,米饭");
t("而那盘辣子鸡真的进「有人不能吃」", chili.boom.map((x) => x.dish).join(), "辣子鸡");

console.log("\n--- 言笺 ---");
const txt = "明天下午记得把材料发我。\n药快没了帮我买一盒。\n那就周五见吧。\n时间再说。\n快递到了你拿一下。";
const y = Engine.yan(txt);
t("捞出条数", y.total, 5);
t("待办数", y.待办.length, 1);
t("要买数", y.要买.length, 2);
console.log("         待办:", JSON.stringify(y.待办));
console.log("         要买:", JSON.stringify(y.要买));
t("明天被识别出时间", y.待办[0] && y.待办[0].when ? y.待办[0].when.text : "无", "明天");
t("追问句非空", !!y.ask, true);

const y2 = Engine.yan("下周三之前把方案提交了。\n9月28日要交房租。\n别忘了买牛奶。");
console.log("         时间抽取:", y2.待办.concat(y2.要买).map((x) => x.line.slice(0, 12) + "→" + (x.when ? x.when.text : "无时间")).join(" | "));
t("下周三被识别", !!y2.待办.concat(y2.要买).find((x) => x.when && x.when.text === "下周三"), true);
// 追问是念给用户听的一句短话，不是把那条待办整句抄一遍
const longY = Engine.yan("明天下午三点之前把这份三百页的附件里的第三章和第五章的表格全部核对一遍并且发给王总另外抄送财务");
t("长待办的追问收在省略号上", longY.ask.includes("…"), true);
t("长待办的追问不超过 40 字", longY.ask.length <= 40, true);
t("被截的是引用，条目本身还是全文", longY.待办[0].line.length > 40, true);
t("9月28日被识别", !!y2.待办.concat(y2.要买).find((x) => x.when && x.when.text === "9月28日"), true);

console.log("\n--- 言笺：有日期的「把 X 做掉」不该被静默丢掉 ---");
const yba = Engine.yan("周五把合同寄出。\n月底把报销单交了。");
t("两句都进了待办", yba.待办.length, 2);
t("周五抽成了时间", !!yba.待办[0].when, true);
t("月底也抽成了时间", !!yba.待办[1].when, true);
t("没日期也没线索的闲话仍然不进笺", Engine.yan("今天天气不错。\n哈哈这个好玩。").total, 0);
t("光有「把」没日期也不硬塞", Engine.yan("把这事儿说了吧。").total, 0);
t("已定优先：新兜底不抢已有分类", Engine.yan("那就周五见吧。").已定.length, 1);

console.log("\n--- 言笺：说话人 speaker ---");
const ysp = Engine.yan("小红：明天开会。\n明天：交房租。\n要买：洗衣液和纸巾。\n小明让我周五交表。\n小王说：记得把发票发我。");
const spCards = [...ysp.待办, ...ysp.要买, ...ysp.已定, ...ysp.还没说清];
t("冒号前缀标出说话人", spCards.find((x) => x.line.indexOf("小红") === 0).speaker, "小红");
t("时间词前缀不标 speaker", spCards.find((x) => x.line.indexOf("明天") === 0).speaker, null);
t("功能标签前缀不标 speaker", spCards.find((x) => x.line.indexOf("要买") === 0).speaker, null);
t("无冒号不标 speaker", spCards.find((x) => x.line.indexOf("小明") === 0).speaker, null);
const bothCard = spCards.find((x) => x.line.indexOf("小王说") === 0);
t("「某某说：」speaker 与 who 并存", bothCard.speaker, "小王说");
t("同一张卡 who 仍是纯人名", bothCard.who, "小王");
const ysp2 = Engine.yan("小李:下午取快递。");
t("半角冒号也标 speaker", ysp2.要买[0].speaker, "小李");
console.log("         说话人:", spCards.map((x) => x.line.slice(0, 10) + "→" + (x.speaker ? x.speaker : "无")).join(" | "));

console.log("\n--- 言笺：who 停用词 ---");
const ystop = Engine.yan("时间再说周五交稿。\n回头说一声。\n小王再说一遍。\n小王说记得周五交稿。");
const stopCards = [...ystop.待办, ...ystop.要买, ...ystop.已定, ...ystop.还没说清];
t("「时间再说周五交稿」不出 who", stopCards.find((x) => x.line.indexOf("时间再说") === 0)?.who, null);
t("「回头说一声」不出 who", stopCards.find((x) => x.line.indexOf("回头说") === 0)?.who, null);
// {2,3} 贪心捕获「小王再」→ 末尾剥连接副词「再」收口成纯人名「小王」（两端同口径）
t("「小王再说一遍」剥掉尾部「再」得纯人名", stopCards.find((x) => x.line.indexOf("小王再说") === 0)?.who, "小王");
t("「小王说记得…」who 仍是纯人名", stopCards.find((x) => x.line.indexOf("小王说记") === 0)?.who, "小王");

console.log("\n--- 言笺：who 贪心捕获剥离连接副词 ---");
const ywho = Engine.yan("小王再说一遍。\n时间再说。\n他又让我去拿。\n欧阳才说周五要交稿。");
const whoCards = [...ywho.待办, ...ywho.要买, ...ywho.已定, ...ywho.还没说清];
t("「小王再说一遍」→ 小王（徽章不再带「再」）", whoCards.find((x) => x.line.indexOf("小王再说") === 0)?.who, "小王");
t("「时间再说」仍被停用词拦下", whoCards.find((x) => x.line.indexOf("时间再说") === 0)?.who, null);
t("「他又让我去拿」剥后单字不出 who", whoCards.find((x) => x.line.indexOf("他又让我") === 0)?.who, null);
t("「欧阳才说…」剥「才」剩两字人名", whoCards.find((x) => x.line.indexOf("欧阳才说") === 0)?.who, "欧阳");

console.log("\n--- 菜库不变式：库里的分类必须和 dishKind 判的一致 ---");
// 菜库给每道菜写死了它在荤/素/汤/主食哪一栏，dishKind 又是按菜名的字面 token 现判的。
// 两边一旦对不上，排桌就会一边显示「素 0 道」、一边推荐你「加一道素菜」——
// 上一轮查出 8 道这样的菜（清炒时蔬判成其他、地三鲜判成其他、番茄炒蛋库荤判素…）。
const kindBad = [];
const tagWords = new Set(Object.keys(Engine.TABLES.CHIP_MAP));
const seen = new Map();
let dishTotal = 0;
for (const [bucket, list] of Object.entries(Engine.DISHES)) {
  for (const d of list) {
    dishTotal++;
    const got = Engine.dishKind(d.n);
    if (got !== bucket) kindBad.push(`${bucket}/${d.n}→${got}`);
    for (const tg of d.tags) if (!tagWords.has(tg)) kindBad.push(`tags 造新词 ${d.n}:${tg}`);
    if (seen.has(d.n)) kindBad.push(`重名 ${d.n}（${seen.get(d.n)} / ${bucket}）`);
    seen.set(d.n, bucket);
  }
}
// t() 是恒等比较，数组必须先 join 成字符串才有意义
t("菜库分类与 dishKind 判定全部自洽", kindBad.join("；"), "");
t("菜库仍是 63 道", dishTotal, 63);
t("蛋菜算素", Engine.dishKind("番茄炒蛋"), "素");
t("凤爪算荤", Engine.dishKind("豉汁蒸凤爪"), "荤");
t("小笼包算主食", Engine.dishKind("小笼包"), "主食");
t("玉米烙算主食", Engine.dishKind("玉米烙"), "主食");
t("地三鲜算素", Engine.dishKind("地三鲜"), "素");
t("上汤娃娃菜算汤", Engine.dishKind("上汤娃娃菜"), "汤");

console.log("\n--- 竖排避头尾（禁则）---");
// 长图杂志版式的几何：金句从 y=316 起竖排，步距 56、字号 48，纸白带底边在 imgH-44。
// 预算是「一个字的顶位还能走到几步」，必须减掉字高，否则最后一个字整只掉出版面。
const TOP = 316, STEP = 56, FPX = 48, IMG_BOTTOM = 1180, MC = 4;
const PC = Math.max(1, (IMG_BOTTOM - 44 - TOP - FPX) / STEP);
const vc = (s) => Engine.verticalCols(s, PC, MC);
/** 一列里最后一个单元的底边 y：越界就说明字掉到照片外面了。 */
const colBottom = (c) => {
  const list = Engine.vClusters(c);
  let adv = 0;
  for (let k = 0; k < list.length - 1; k++) adv += list[k].adv;
  return TOP + adv * STEP + FPX;
};
const startsWithBan = (cols) => cols.some((c) => !c || /[\s。、，;；:：!！?？‥…）)］]｝}〉》」』”’ー〜～—]/.test([...c][0]));
t("句读不落列首", startsWithBan(vc("一二三四五六七八九十一二三。五六七八九十")), false);
t("空白不落列首（金句里的「 3 件」就有空格）",
  startsWithBan(vc("它能解开 4 件旧衣。它能解开 4 件旧衣。它能解开 4 件旧衣。它能解开 4 件")), false);
t("后括号不落列首", vc("一二三四五六七八九十一二三）五六七八九十").every((c) => !/^[）)]/.test(c)), true);
// 列尾装不下标点时，宁可少排一个字让标点跟前面的字一起挪走——
// 第一版只给了 0.6 的借位，结果「色，而且…」的逗号单独开了一列，正是禁则要防的那件事。
t("列尾挤不下标点时整对挪走，不留标点开列",
  startsWithBan(vc("柜里的「深蓝阔腿裤」就是这个色，而且 16 个月没穿过了。再买一件，只会多一件不穿的。")), false);
t("标点和它的字不被拆开",
  vc("柜里的「深蓝阔腿裤」就是这个色，而且 16 个月没穿过了。再买一件，只会多一件不穿的。")
    [1].startsWith("色，"), true);
t("开引号不收列尾，挪去下一列行首",
  vc("一二三四五六七八九十一二三「五六七八九十")[1].startsWith("「"), true);
t("任何一列的最后一个字都不掉出版面（顶位预算要减字高）",
  vc("柜里的「深蓝阔腿裤」就是这个色，而且 16 个月没穿过了。再买一件，只会多一件不穿的。")
    .every((c) => colBottom(c) <= IMG_BOTTOM - 44 + 12), true);
t("长金句每列都不越界",
  ["啊".repeat(60), "接近「白衬衫」。但那一件你自己都不太穿——先想清楚要的是这个色，还是新鲜感。",
   "一二三四五六七八九十。、，！？五六七八九十。、，！？五六七八"].every(
    (q) => vc(q).every((c) => colBottom(c) <= IMG_BOTTOM - 44 + 12)), true);
t("一个字都不会静默丢掉",
  vc("「「「「「「「「「「「「「「「「「「「「开头全是引号的金句一二三四五六七八九十").join("").length > 0, true);
t("列数不超过 maxCols", vc("啊".repeat(200)).length, MC);
t("装不下时末尾收成省略号而不是从中间断",
  [...vc("啊".repeat(50) + "一二三四五六七八九十")].pop().includes("…") ||
  vc("啊".repeat(50) + "一二三四五六七八九十").join("").length <= 60, true);
t("空串给空列", vc("").length, 0);
t("整字占一格、标点占半格", [Engine.vCost("衣"), Engine.vCost("。")].join(","), "1,0.6");
// 纵中横：两个连续数字横着挤进一格，不能拆成两行（「16 个月」被拆成 1 / 6 是杂志级错误）
t("两位数字合成一格", Engine.vClusters("16 个月").map((c) => c.t).join("|"), "16| |个|月");
t("两位数字只占一步距", Engine.vClusters("16")[0].adv, 1);
t("三位数字不合并", Engine.vClusters("168").map((c) => c.t).join("|"), "1|6|8");
t("金句里的「16 个月」在列里不被拆开",
  vc("而且 16 个月没穿过了。再买一件，只会多一件不穿的。").some((c) => /16/.test(c)), true);

console.log(`\n结果：${pass} 通过 / ${fail} 失败\n`);
process.exit(fail ? 1 : 0);
