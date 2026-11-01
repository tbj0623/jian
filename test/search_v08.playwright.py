# v0.8.0 全局搜索直达：对真实屏幕做点击 / 键盘 / 归档 / 折叠 / 排序回归。
import pathlib
import sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
checks, errors = [], []

def ck(name, got, want=True):
    ok = got == want
    checks.append(ok)
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f" -> {got!r} != {want!r}"))
    return ok

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    page.wait_for_function("() => typeof searchAll === 'function' && typeof normYanCard === 'function'")
    page.click("#go")
    page.evaluate("""() => {
      state.onboarded=true;
      state.modules={yi:true,wei:true,yan:true};
      state.yanView='calendar'; state.yanHideDone=true;
      state.yanCards=Array.from({length:47},(_,i)=>
        normYanCard({k:'待办',line:'精确言笺 '+i,done:i===2}));
      state.yanCards[2].archivedAt=Date.now()-86400000;
      state.yanCards[2].doneAt=Date.now()-9*86400000;
      state.yanCards[35].line='同名任务';
      state.yanCards[36].line='同名任务';
      state.album=Array.from({length:20},(_,i)=>({
        type:'yi',quote:'精确笺册 '+i,text:'精确笺册 '+i+' 的展开全文',t:Date.now()-i*86400000
      }));
      state.digest=[
        {text:'精确摘录 A',from:'会话',t:Date.now()-3*86400000,mood:0},
        {text:'精确摘录 B',from:'会话',t:Date.now(),mood:0},
        {text:'精确摘录 C',from:'会话',t:Date.now()-86400000,mood:0}
      ];
      state.reminders=[
        {id:'r-future',text:'精确提醒 未来',at:Date.now()+86400000,done:false,repeat:''},
        {id:'r-done',text:'精确提醒 已办',at:Date.now()-86400000,done:true,repeat:''}
      ];
      state.searchHist=[];
      save(state); show('search');
    }""")
    ck("搜索六类源码可调用", page.evaluate("typeof openYanSearchHit==='function' && typeof openReminderSearchHit==='function'"))
    page.fill("#globalSearch", "精确言笺")
    ck("总命中数显示 45", "找到 45 条" in page.locator("#searchBody").inner_text())
    ck("言笺结果限前 40 且展示明确", "40 / 共 45" in page.locator("#searchBody").inner_text())
    ck("只展示 40 条有说明", "先展示前 40 条" in page.locator("#searchBody").inner_text())
    ck("返回真正数量", page.locator("#searchBody [data-g='言笺']").count(), 40)
    ck("中文输入法候选键不会抢焦点", page.evaluate("""() => {
      const el=document.querySelector('#globalSearch');
      const e=new KeyboardEvent('keydown',{key:'ArrowDown',isComposing:true,cancelable:true,bubbles:true});
      el.dispatchEvent(e);
      return !e.defaultPrevented && document.activeElement===el;
    }"""))
    page.locator("#globalSearch").press("ArrowDown")
    ck("↓ 进入第一条结果", page.evaluate("document.activeElement.getAttribute('data-i')"), "0")
    page.keyboard.press("ArrowDown")
    ck("↓ 移动到第二条", page.evaluate("document.activeElement.getAttribute('data-i')"), "1")
    page.keyboard.press("ArrowUp")
    ck("↑ 返回上一条", page.evaluate("document.activeElement.getAttribute('data-i')"), "0")
    page.keyboard.press("Escape")
    ck("Esc 返回输入框", page.evaluate("document.activeElement.id"), "globalSearch")
    page.locator("#searchBody [data-g='言笺'][data-i='2']").click()
    ck("归档结果自动打开归档", page.evaluate("yanArchiveMode"))
    ck("归档目标仍是全量下标 2", page.locator("#yanOut .search-landmark [data-edit='2']").count(), 1)
    ck("命中行获得焦点", page.evaluate("document.activeElement.classList.contains('search-landmark')"))
    ck("搜索不会删除归档字段", page.evaluate("!!state.yanCards[2].archivedAt"))
    page.evaluate("show('search')")
    page.fill("#globalSearch", "同名任务")
    ck("同名任务各是一条结果", page.locator("#searchBody [data-g='言笺']").count(), 2)
    page.locator("#searchBody [data-g='言笺'][data-i='1']").click()
    ck("同名第二条对上索引 36", page.locator("#yanOut .search-landmark [data-edit='36']").count(), 1)
    ck("跳转后关掉只看没办过滤", page.evaluate("state.yanHideDone"), False)
    ck("跳转后切回可见的分组视图", page.evaluate("state.yanView"), "kind")
    page.evaluate("() => {albumView='yi';albumAll=false;albumOpen=[];show('search');}")
    page.fill("#globalSearch", "精确笺册 19")
    page.locator("#searchBody [data-g='笺册']").first.click()
    ck("第 20 张历史存档可以直接看见", page.locator("#album .search-landmark [data-slip='19']").count(), 1)
    ck("笺册摊开全文", "展开全文" in (page.locator("#album [data-slip='19']").first.inner_text(timeout=1000) if page.locator("#album [data-slip='19']").count() else ""))
    ck("旧存档焦点已定位", page.evaluate("document.activeElement.classList.contains('search-landmark')"))
    page.evaluate("() => { digestOpen=false; show('search'); }")
    page.fill("#globalSearch", "精确摘录 A")
    page.locator("#searchBody [data-g='摘录']").first.click()
    ck("折叠摘录本自动打开", page.locator("#yanDigestBook").get_attribute("open") is not None)
    ck("排序后精准命中摘录 A", page.locator("#digestBody .search-landmark").count() > 0 and "精确摘录 A" in page.locator("#digestBody .search-landmark").inner_text())
    ck("摘录定位获得焦点", page.evaluate("document.activeElement.classList.contains('search-landmark')"))
    page.evaluate("show('search')")
    page.fill("#globalSearch", "精确提醒 已办")
    page.locator("#searchBody [data-g='提醒']").first.click()
    ck("已办提醒仍能定位", page.locator("#remindBody .search-landmark[data-rem='r-done']").count(), 1)
    ck("提醒所在行获得焦点", page.evaluate("document.activeElement.classList.contains('search-landmark')"))
    page.evaluate("show('search')")
    page.fill("#globalSearch", "精确提醒 未来")
    page.locator("#globalSearch").press("Enter")
    ck("搜索框回车直达第一条", page.locator("#remindBody .search-landmark[data-rem='r-future']").count(), 1)
    page.evaluate("show('search')")
    page.fill("#globalSearch", "不存在的关键词")
    ck("无结果给换词出口", "试试更短的一段字" in page.locator("#searchBody").inner_text())
    page.locator("#globalSearch").press("Escape")
    ck("输入框 Esc 清空搜索", page.input_value("#globalSearch"), "")
    ck("未修改用户记录条数", page.evaluate("() => [state.yanCards.length,state.album.length,state.digest.length,state.reminders.length]"), [47,20,3,2])
    ck("搜索历史只记已打开的词", page.evaluate("() => !state.searchHist.includes('不存在的关键词')"))
    ck("无页面脚本异常", len(errors), 0)
    browser.close()

print(f"搜索直达 v0.8: {sum(checks)}/{len(checks)}")
if not all(checks): sys.exit(1)
