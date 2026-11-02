# v0.9.0 恢复点端到端：完整快照、回滚、篡改拒绝、容量上限、隐私清空。
import pathlib
import sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
results, errors, external = [], [], []

def ck(name, got, want=True):
    ok = got == want
    results.append(ok)
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f": {got!r} != {want!r}"))
    return ok

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: external.append(r.url) if r.url.startswith(("https://", "http://")) else None)
    page.on("dialog", lambda d: d.accept())
    page.goto(URL)
    page.wait_for_function("() => typeof RecoveryPoints === 'object' && typeof applyBackupObject === 'function'")
    page.click("#go")
    ck("可用 WebCrypto 与 IndexedDB", page.evaluate("RecoveryPoints.available()"))
    page.evaluate("""() => {
      state.onboarded = true;
      state.modules = {yi:true,wei:true,yan:true};
      state.wardrobe = [{id:'r1', name:'恢复前的蓝衣', cat:'上衣', img:'data:image/png;base64,aGVsbG8='}];
      state.yanCards = [normYanCard({k:'待办',line:'私密原始言笺'})];
      state.album = [{type:'yi',quote:'旧相册',text:'历史存档',t:Date.now()}];
      save(state); show('me');
    }""")
    ck("出现恢复点入口", page.locator("#recoveryBox summary").count(), 1)
    page.locator("#recoveryBox summary").click()
    ck("手动保存按钮", page.locator("#recoverySave").count(), 1)
    page.click("#recoverySave")
    page.wait_for_function("() => document.querySelector('#recoveryStatus')?.textContent.includes('本机共 1 份')")
    rows = page.evaluate("RecoveryPoints.list().then(x=>x.map(p=>({id:p.id,raw:p.raw,sha:p.sha256,reason:p.reason})))")
    ck("第一份只留一个", len(rows), 1)
    ck("完整保留照片字节", "data:image/png;base64,aGVsbG8=" in rows[0]["raw"])
    ck("完整保留言笺", "私密原始言笺" in rows[0]["raw"])
    ck("完整保留笺册", "历史存档" in rows[0]["raw"])
    ck("摘要为 SHA-256", len(rows[0]["sha"]), 64)
    ck("快照校验通过", page.evaluate("(id)=>RecoveryPoints.verified(id).then(x=>x.obj.wardrobe[0].name)", rows[0]["id"]), "恢复前的蓝衣")
    page.evaluate("""() => { state.wardrobe[0].name='新改的黄衣'; save(state); }""")
    ck("日常修改不影响老快照", page.evaluate("(id)=>RecoveryPoints.verified(id).then(x=>x.obj.wardrobe[0].name)", rows[0]["id"]), "恢复前的蓝衣")

    # 篡改已保存记录的原文，不改 SHA-256，验证恢复被拒且不碰当前数据。
    tampered = page.evaluate("""async (id) => {
      const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('jian-recovery-v1');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)});
      await new Promise((resolve,reject)=>{const t=db.transaction('points','readwrite');const q=t.objectStore('points').get(id);
        q.onsuccess=()=>{const v=q.result;v.raw=v.raw.replace('恢复前的蓝衣','恶意替换');t.objectStore('points').put(v)};
        t.oncomplete=resolve;t.onerror=()=>reject(t.error)});
      db.close();
      try{await RecoveryPoints.verified(id);return false}catch(e){return e.message.includes('校验失败')}
    }""", rows[0]["id"])
    ck("篡改一字被摘要拒绝", tampered)
    ck("坏快照没有覆盖当前数据", page.evaluate("state.wardrobe[0].name"), "新改的黄衣")
    page.evaluate("(id)=>RecoveryPoints.remove(id)", rows[0]["id"])
    ck("坏快照删除", page.evaluate("RecoveryPoints.list().then(x=>x.length)"), 0)

    # 循环留档，只保留最新五份且每份内容独立。
    names = []
    for i in range(6):
        page.evaluate("(n)=>{state.wardrobe[0].name=n;save(state)}", "版本" + str(i))
        page.evaluate("RecoveryPoints.capture('手动')")
        names.append("版本" + str(i))
    saved = page.evaluate("RecoveryPoints.list().then(x=>x.map(p=>JSON.parse(p.raw).wardrobe[0].name))")
    ck("第六次自动淘汰最旧快照", len(saved), 5)
    ck("最新快照完整", "版本5" in saved)
    ck("最旧快照已淘汰", "版本0" not in saved)
    ck("五份各自独立", len(set(saved)), 5)
    point_id = page.evaluate("RecoveryPoints.list().then(x=>x[0].id)")
    ck("恢复点列出五份", page.evaluate("RecoveryPoints.list().then(x=>x.length)"), 5)

    # 直接走正式导入入口；成功时会刷新页面，必须有“导入前”自动恢复点。
    page.evaluate("""() => {const obj=JSON.parse(JSON.stringify(state));obj.wardrobe[0].name='外部导入';window.__importJob=applyBackupObject(obj)}""")
    page.wait_for_load_state("load")
    page.wait_for_function("() => typeof RecoveryPoints === 'object' && !!document.querySelector('#go')")
    ck("覆盖导入后衣名被替换", page.evaluate("state.wardrobe[0]?.name"), "外部导入")
    auto = page.evaluate("RecoveryPoints.list().then(x=>x.filter(p=>p.reason==='导入前'))")
    ck("覆盖前自动留一份恢复点", len(auto) >= 1)
    ck("自动留档包含未导入状态", any("版本5" in x["raw"] for x in auto))
    ck("导入后的撤销按钮可用", page.evaluate("!!document.querySelector('.toast.act button') && document.querySelector('.toast.act').textContent.includes('已导入')"))
    ck("自动留档也在五份限制内", page.evaluate("RecoveryPoints.list().then(x=>x.length)"), 5)
    ck("刷新后快照仍可验证", page.evaluate("(id)=>RecoveryPoints.verified(id).then(x=>!!x.obj.wardrobe)", point_id))

    # 恢复：用恢复点经统一导入，触发刷新；并证实自动留了恢复前的版本。
    page.evaluate("""async (id)=>{const entry=await RecoveryPoints.verified(id);await applyBackupObject(entry.obj)}""", point_id)
    page.wait_for_load_state("load")
    page.wait_for_function("() => typeof RecoveryPoints === 'object'")
    ck("恢复后找回原衣物", page.evaluate("state.wardrobe[0]?.name"), "版本5")
    ck("恢复点继续保留照片", page.evaluate("state.wardrobe[0]?.img"), "data:image/png;base64,aGVsbG8=")
    ck("恢复操作前也留了自动档", page.evaluate("RecoveryPoints.list().then(x=>x.some(p=>p.reason==='导入前'&&p.raw.includes('外部导入')))"))

    page.evaluate("show('me')")
    page.locator("#recoveryBox summary").click()
    ck("UI 可显示最多五个恢复按钮", page.locator("[data-rprestore]").count() <= 5)
    page.set_viewport_size({"width": 320, "height": 720})
    ck("窄屏恢复点不横向溢出", page.evaluate("document.documentElement.scrollWidth<=innerWidth"))

    # 清空应同步抹掉恢复点；否则残留隐蔽个人信息。原有 sessionStorage 撤销不受影响。
    page.click("#reset")
    page.wait_for_load_state("load")
    page.wait_for_function("() => typeof RecoveryPoints === 'object'")
    ck("清空后不存在历史恢复点", page.evaluate("RecoveryPoints.list().then(x=>x.length)"), 0)
    ck("清空后数据真的重置", page.evaluate("!state.wardrobe.some(x=>x.name==='版本5')"))
    ck("原有清空撤销按钮仍可用", page.evaluate("!!document.querySelector('.toast.act button') && document.querySelector('.toast.act').textContent.includes('本机数据已清空')"))
    ck("没有脚本异常", errors, [])
    ck("没有意外外网请求", external, [])
    context.close()
    browser.close()

print(f"v0.9 恢复点：{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
