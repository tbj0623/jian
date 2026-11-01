# 言笺改字回归：原话可修、提醒不孤儿、再贴旧聊天不复活旧稿。
# 独立于需要联网/Android 的测试；命中真实 DOM 和本地持久化。
import pathlib
import sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
checks = []
errors = []

def check(name, actual, expected=True):
    ok = actual == expected
    checks.append(ok)
    print(("  ok   " if ok else " FAIL ") + name + ("" if ok else f" -> {actual!r} ≠ {expected!r}"))
    return ok

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.clock.install(time="2026-09-17T10:00:00")
    page.goto(URL)
    page.wait_for_function("() => typeof state !== 'undefined' && typeof editYanLine === 'function'")
    page.click("#go")
    page.evaluate("""() => {
      state.onboarded = true;
      state.modules = {yi:true, wei:true, yan:true};
      state.yanView = 'kind'; state.yanHideDone = false;
      state.yanCards = [
        {k:'待办', line:'旧句', when:{text:'明天', at:Date.now()+86400000}, done:false},
        {k:'待办', line:'已在这里', when:null, done:false},
        {k:'要买', line:'共用句', when:null, done:false},
        {k:'待办', line:'共用句', when:null, done:false}
      ].map(normYanCard);
      state.reminders = [
        {id:'r1', text:'旧句', at:Date.now()+86400000, repeat:'', done:false, fired:false, from:'yan'},
        {id:'r2', text:'共用句', at:Date.now()+86400000, repeat:'', done:false, fired:false, from:'yan'}
      ];
      save(state); show('yan'); renderYan();
    }""")
    check("每一条都有改字按钮", page.locator("#yanOut [data-edit]").count(), 4)
    check("改字是可读的独立按钮", page.locator("#yanOut [data-edit='0']").get_attribute("aria-label"), "修改这一条的文字")
    page.click("#yanOut [data-edit='0']")
    check("展开之后光标进入原话框", page.evaluate("document.activeElement.id"), "yanEditText-0")
    check("编辑器保留完整原话", page.input_value("#yanEditText-0"), "旧句")
    page.fill("#yanEditText-0", " ")
    page.click("#yanOut [data-edit-save='0']")
    check("空文字被挡住且原话没动", page.evaluate("state.yanCards[0].line"), "旧句")
    check("空文字不丢掉编辑框", page.locator("#yanEditText-0").count(), 1)
    page.fill("#yanEditText-0", "已在这里")
    page.click("#yanOut [data-edit-save='0']")
    check("同类重名不覆盖已有条目", page.evaluate("state.yanCards.map(x => x.line)"), ["旧句","已在这里","共用句","共用句"])
    page.fill("#yanEditText-0", "改过的句子")
    page.click("#yanOut [data-edit-save='0']")
    check("保存文字并保留类别和时间", page.evaluate("""() => {
      const c=state.yanCards[0]; return [c.line,c.k,c.when.text,c.done,c.sourceLine];
    }"""), ["改过的句子","待办","明天",False,"旧句"])
    check("原有独占提醒一起改文字", page.evaluate("state.reminders[0].text"), "改过的句子")
    check("修改之后铃铛仍然认得提醒", page.locator("#yanOut [data-ybell='0']").get_attribute("aria-pressed"), "true")
    page.click("#toasts .toast.act button")
    check("撤销还原原话与提醒", page.evaluate("() => [state.yanCards[0].line,state.reminders[0].text]"), ["旧句","旧句"])
    check("撤销后不留假的来源别名", page.evaluate("state.yanCards[0].sourceLine || null"), None)

    page.click("#yanOut [data-edit='0']")
    page.fill("#yanEditText-0", "最终稿")
    page.click("#yanOut [data-edit-save='0']")
    check("再次贴原话不复活旧稿", page.evaluate("""() => mergeCards([
      normYanCard({k:'待办',line:'旧句',when:null})
    ])"""), 0)
    check("原来的提醒仍跟随最终稿", page.evaluate("state.reminders[0].text"), "最终稿")
    page.reload()
    page.wait_for_function("() => typeof state !== 'undefined' && typeof show === 'function'")
    page.evaluate("() => {show('yan'); renderYan();}")
    check("重开后编辑与原文别名都还在", page.evaluate("() => [state.yanCards[0].line,state.yanCards[0].sourceLine]"), ["最终稿","旧句"])
    check("重开后再贴旧聊天仍不重复", page.evaluate("""() => mergeCards([
      normYanCard({k:'待办',line:'旧句',when:null})
    ])"""), 0)

    page.click("#yanOut [data-edit='2']")
    page.fill("#yanEditText-2", "独立改写")
    page.click("#yanOut [data-edit-save='2']")
    check("共用原话改一条不会篡改另一条的提醒", page.evaluate("state.reminders[1].text"), "共用句")
    check("另一条仍显示已有提醒", page.locator("#yanOut [data-ybell='3']").get_attribute("aria-pressed"), "true")
    check("改过的那条不误认共用提醒", page.locator("#yanOut [data-ybell='2']").get_attribute("aria-pressed"), "false")

    page.click("#yanOut [data-edit='1']")
    page.fill("#yanEditText-1", "按 Escape 不保存")
    page.press("#yanEditText-1", "Escape")
    check("Escape 取消不改原话", page.evaluate("state.yanCards[1].line"), "已在这里")
    check("Escape 把编辑框收起", page.locator("#yanEditText-1").count(), 0)
    check("Escape 后焦点回到该行按钮", page.evaluate("document.activeElement.getAttribute('data-edit')"), "1")
    page.click("#yanOut [data-edit='1']")
    page.fill("#yanEditText-1", "快捷键保存")
    page.press("#yanEditText-1", "Control+Enter")
    check("Ctrl+Enter 能保存", page.evaluate("state.yanCards[1].line"), "快捷键保存")
    payload = '<img src=x onerror="window.__yanInjected=1">测试'
    page.click("#yanOut [data-edit='1']")
    page.fill("#yanEditText-1", payload)
    page.click("#yanOut [data-edit-save='1']")
    check("特殊符号原样保存而不执行 HTML", page.evaluate("state.yanCards[1].line"), payload)
    check("渲染内容没有注入 img 或执行事件", page.evaluate("() => [document.querySelectorAll('#yanOut img').length,window.__yanInjected || 0]"), [0,0])
    check("新改字控件有 44px 热区", page.evaluate("""() => {
      const r=document.querySelector('#yanOut [data-edit="1"]').getBoundingClientRect();
      return Math.min(r.width,r.height)>=44;
    }"""), True)
    page.set_viewport_size({"width":480,"height":844})
    page.evaluate("renderYan()")
    check("480px 宽时动作栏不挤压正文", page.evaluate("""() => {
      const r=document.querySelector('#yanOut .ck-body').getBoundingClientRect();
      return r.width>140 && document.documentElement.scrollWidth<=window.innerWidth;
    }"""), True)
    check("没有页面脚本异常", errors, [])
    context.close()
    browser.close()

passed=sum(checks)
print(f"\n言笺改字：{passed} 通过 / {len(checks)-passed} 失败")
sys.exit(0 if all(checks) else 1)
