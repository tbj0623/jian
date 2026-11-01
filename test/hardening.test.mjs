import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const source = (name) => readFileSync(path.join(ROOT, name), "utf8");
const ctx = {
  console, Date, Math, JSON, Promise, setTimeout, clearTimeout,
  document: { querySelector: () => null, querySelectorAll: () => [] },
  localStorage: { getItem: () => null, setItem: () => {} },
  window: { JIAN_CONFIG: { endpoint: "" } },
};
vm.createContext(ctx);
for (const name of ["state.js", "ui.js", "remind.js"]) vm.runInContext(source(name), ctx, { filename: name });
const { normalizeState, scheduleNative, rescheduleAll, haptic, dataWhere, veil } =
  vm.runInContext("({ normalizeState, scheduleNative, rescheduleAll, haptic, dataWhere, veil })", ctx);
let checks = 0;
const ok = (label, fn) => { fn(); checks++; console.log("  ok  " + label); };
const clean = (input) => {
  ctx.fixture = input;
  return vm.runInContext("normalizeState(fixture)", ctx);
};
const newPiece = { name: "白衬衫", cat: "上衣", color: "#f4f0ea" };
const previous = { stamp: "再想想", quote: "再看看", new: newPiece, close: [newPiece], match: [] };

ok("正常的旧报告和新报告不被修改", () => {
  const s = clean({ wardrobe: [], lastReport: structuredClone(previous), lastNew: { ...newPiece } });
  assert.equal(JSON.stringify(s.lastReport), JSON.stringify(previous));
  assert.equal(JSON.stringify(s.lastNew), JSON.stringify(newPiece));
});
ok("损坏的报告形状不会带进绘图", () => {
  const s = clean({ wardrobe: [], lastReport: { stamp: {}, close: {} }, lastNew: "boom" });
  assert.equal(s.lastReport, null);
  assert.equal(s.lastNew, null);
});
ok("视图字段和追问只能接受合理值", () => {
  const s = clean({ wardrobe: [], weiMode: { bad: true }, yiCat: 42, yanAsk: { bad: true } });
  assert.equal(s.weiMode, "friends");
  assert.equal(s.yiCat, "上衣");
  assert.equal(s.yanAsk, "");
});
ok("上一桌文本受限，不挤掉照片空间", () => {
  const r = { safe: [], risk: [], boom: [], kinds: {}, plan: { want: {}, gap: {} } };
  const s = clean({ wardrobe: [], lastWei: { menu: "菜".repeat(100000), talk: "话".repeat(100000), r } });
  assert.equal(s.lastWei.menu.length, 4000);
  assert.equal(s.lastWei.talk.length, 6000);
  const giant = clean({ wardrobe: [], lastWei: { menu: "正常", talk: "正常", r: { safe: ["x".repeat(81000)] } } });
  assert.equal(giant.lastWei, undefined);
});
ok("重复归一化稳定，不改正常报告", () => {
  const input = { wardrobe: [], lastReport: structuredClone(previous), lastNew: { ...newPiece } };
  const once = clean(input);
  const first = JSON.stringify(once);
  assert.equal(JSON.stringify(clean(once)), first);
});
const calls = { schedule: [], cancelAll: 0, impact: [] };
ctx.window.Capacitor = { Plugins: {
  LocalNotifications: {
    schedule: (arg) => { calls.schedule.push(arg); return Promise.resolve(); },
    cancelAll: () => { calls.cancelAll++; return Promise.resolve(); },
  },
  Haptics: { impact: (arg) => { calls.impact.push(arg); return Promise.resolve(); } },
}};
vm.runInContext("state.reminders = [{id:'r1', text:'明天取件', at:Date.now()+86400000, done:false, repeat:''}, {id:'r2', text:'已办', at:Date.now()+86400000, done:true, repeat:''}]; state.settings.notify=false; state.settings.haptic=false", ctx);
ok("关闭通知后新增提醒不再排程", () => {
  scheduleNative({ id: "r3", text: "别响", at: Date.now() + 86400000 });
  assert.equal(calls.schedule.length, 0);
});
ok("重启恢复也清理关闭状态的系统队列", () => {
  rescheduleAll();
  assert.equal(calls.schedule.length, 0);
  assert.equal(calls.cancelAll, 1);
});
ok("重新开启后只补排将来的未完成提醒", () => {
  vm.runInContext("state.settings.notify=true", ctx);
  rescheduleAll();
  assert.equal(calls.schedule.length, 1);
  assert.equal(calls.schedule[0].notifications[0].id > 0, true);
  assert.equal(calls.schedule[0].notifications[0].isExactNotification, false);
});
ok("触感关闭不调用原生，开启后会调用", () => {
  haptic("LIGHT");
  assert.equal(calls.impact.length, 0);
  vm.runInContext("state.settings.haptic=true", ctx);
  haptic("MEDIUM");
  assert.equal(calls.impact.length, 1);
  assert.equal(calls.impact[0].style, "MEDIUM");
});
ok("隐私说明随网关状态变化", () => {
  ctx.window.JianAPI = { remoteOn: () => false };
  ctx.JianAPI = ctx.window.JianAPI;
  assert.equal(dataWhere(), "数据只在这台设备");
  ctx.window.JianAPI = { remoteOn: () => true };
  ctx.JianAPI = ctx.window.JianAPI;
  assert.match(dataWhere(), /发往你填的那个地址/);
});
ok("遮罩打开时背景不可交互，关闭后恢复焦点", () => {
  const css = new Set();
  const focus = [];
  const overlay = {
    classList: { contains: (x) => css.has(x), toggle: (x, on) => on ? css.add(x) : css.delete(x) },
    focus: () => focus.push("overlay"),
  };
  const app = { inert: false, setAttribute: (key, value) => { app[key] = value; } };
  const nav = { inert: false };
  const off = { hidden: true, focus: () => focus.push("cancel") };
  const what = { textContent: "" };
  const origin = {
    isConnected: true,
    closest: () => ({ classList: { contains: (x) => x === "on" } }),
    focus: () => focus.push("origin"),
  };
  ctx.document.activeElement = origin;
  const els = { "#veil": overlay, "#app": app, "#nav": nav, "#veilOff": off, "#veilWhat": what };
  ctx.document.querySelector = (sel) => els[sel] || null;
  veil(true, "正在处理");
  assert.equal(app.inert, true);
  assert.equal(nav.inert, true);
  assert.equal(app["aria-busy"], "true");
  assert.equal(what.textContent, "正在处理");
  assert.equal(focus.at(-1), "cancel");
  veil(false);
  assert.equal(app.inert, false);
  assert.equal(nav.inert, false);
  assert.equal(app["aria-busy"], "false");
  assert.equal(focus.at(-1), "origin");
});
ok("两套月历的按钮 ID 不冲突，且绑定到各自页面", () => {
  const yan = source("yan.js");
  const wardrobe = source("wardrobe.js");
  for (const side of ["Prev", "Next"]) {
    assert.match(yan, new RegExp('id="yanCal' + side + '"'));
    assert.equal(yan.includes('$("#yanCal' + side + '")'), true);
    assert.match(wardrobe, new RegExp('id="cal' + side + '"'));
    assert.doesNotMatch(yan, new RegExp('id="cal' + side + '"'));
  }
});
console.log("结果：" + checks + " 通过 / 0 失败");
