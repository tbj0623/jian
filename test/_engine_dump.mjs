// 把 engine.js 的判定结果原样导成 JSON，给 consistency.py 和 backend/gateway.py 对答案。
// 刻意不做任何字段裁剪：归一化只写在 consistency.py 一处。
// 早先这里和 consistency.py 各写一遍 norm_*，两边都只挑了几个字段比，
// 「雷区理由的先后」「排桌要几道」这类漂移就从缝里漏出去了。
//
// 时钟钉死：判定里有「半年没穿」「下周三」这类相对时间，不钉的话 node 和 python
// 各自取当前时间，跨毫秒就可能翻判——测试会无规律地闪，而且永远对不上 at。
// 运行：node test/_engine_dump.mjs <cases.json>   （JIAN_PIN_MS 由 consistency.py 传）
import fs from "fs";
import path from "path";
import vm from "vm";
import { fileURLToPath } from "url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const PIN_MS = Number(process.env.JIAN_PIN_MS || Date.now());

class PinnedDate extends Date {
  static now() { return PIN_MS; }
}

const ctx = { Math, console, Date: PinnedDate, JSON };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(ROOT, "engine.js"), "utf8") + "\n;globalThis.__E = Engine;", ctx);
const E = ctx.__E;

const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = { pin: PIN_MS, yi: [], yi_seasons: [], wei: [], yan: [], season: [] };

(cases.yi || []).forEach((c) => {
  out.yi.push(E.yi(c.item, c.wardrobe));
  // 本件 + 柜里每件的季节归属（seasonOf 口径对账用）
  out.yi_seasons.push([E.seasonOf(c.item)].concat((c.wardrobe || []).map((w) => E.seasonOf(w))));
});
(cases.wei || []).forEach((c) => { out.wei.push(E.wei(c.menu, c.people, c.mode)); });
(cases.yan || []).forEach((c) => { out.yan.push(E.yan(c.text)); });
out.season = (cases.season || []).map((c) => E.seasonOf(c.w));
out.tables = E.TABLES;

console.log(JSON.stringify(out));
