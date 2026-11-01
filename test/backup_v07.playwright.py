# 数据保险箱端到端：真实下载、密码错误/篡改保护、加密恢复与普通备份兼容。
import json
import pathlib
import sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "index.html").as_uri()
checks, errors, external = [], [], []
def ck(name, got, want=True):
    ok = got == want
    checks.append(ok)
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f": {got!r} != {want!r}"))
    return ok

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width":390,"height":844}, accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: external.append(r.url) if r.url.startswith(("https://","http://")) else None)
    page.goto(URL)
    page.wait_for_function("() => typeof JianVault === 'object' && typeof exportEncryptedData === 'function'")
    page.click("#go")
    page.evaluate("""() => {
      state.onboarded = true;
      state.modules = {yi:true, wei:true, yan:true};
      state.wardrobe = [{ id:"vault-w", name:"私人蓝衬衫", cat:"上衣",color:"#334455",worn:2 }];
      state.yanCards = [normYanCard({k:"待办",line:"不能公开的句子",done:false})];
      save(state); show("me");
    }""")
    ck("旧明文导出/导入按钮保留", page.locator("#exportData, #importData").count(), 2)
    ck("数据与备份有可展开的保险箱", page.locator("#meSecData #vaultBox summary").count(), 1)
    ck("默认不展示解密恢复按钮", page.locator("#vaultRestore").is_hidden())
    page.locator("#vaultBox summary").click()
    ck("密码控件有明确标签", page.locator("label[for='vaultPass']").count(), 1)
    ck("密码框未自动填充", page.input_value("#vaultPass"), "")
    page.fill("#vaultPass", "太短")
    page.fill("#vaultConfirm", "太短")
    page.click("#vaultExport")
    ck("短密码被拒绝", "至少 10" in page.locator("#vaultStatus").inner_text())
    ck("短密码不污染导出时间", page.evaluate("localStorage.getItem('jian.backupAt')"), None)

    pwd = "这是独立加密备份的长密码 2026"
    page.fill("#vaultPass", pwd)
    page.fill("#vaultConfirm", pwd + "不一样")
    page.click("#vaultExport")
    ck("两次密码不一致不会导出", "不一致" in page.locator("#vaultStatus").inner_text())
    page.fill("#vaultConfirm", pwd)
    with page.expect_download() as event:
        page.click("#vaultExport")
    download = event.value
    data = json.loads(pathlib.Path(download.path()).read_text(encoding="utf-8"))
    ck("下载的文件是加密 JSON", data["kind"], "jian-encrypted-backup")
    ck("下载文件包含 AES-256-GCM 标识", data["cipher"], "AES-256-GCM")
    ck("原始衣服名不能在文件中直接看见", "私人蓝衬衫" not in json.dumps(data,ensure_ascii=False))
    ck("原始私话不能在文件中直接看见", "不能公开的句子" not in json.dumps(data,ensure_ascii=False))
    ck("导出后两处密码均已清空", [page.input_value("#vaultPass"),page.input_value("#vaultConfirm")], ["",""])
    ck("密码未落到本地数据/会话", pwd not in page.evaluate("() => JSON.stringify(localStorage)+JSON.stringify(sessionStorage)"))
    ck("成功导出才登记备份日期", page.evaluate("Number(localStorage.getItem('jian.backupAt'))>0"))

    # 导出以后修改本机记录，验证导入真的替换、且可撤销。
    page.evaluate("""() => { state.wardrobe[0].name='导入前修改的衣服'; save(state); }""")
    before = page.evaluate("localStorage.getItem('jian.v1')")
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    page.locator("#fileImport").set_input_files({"name":"encrypted.json","mimeType":"application/json","buffer":payload})
    page.wait_for_function("() => pendingEncryptedBackup !== null")
    ck("加密文件不自动覆盖数据", page.evaluate("localStorage.getItem('jian.v1')"), before)
    ck("加密文件令恢复按钮可见", page.locator("#vaultRestore").is_visible())
    ck("选择文件将焦点交给密码框", page.evaluate("document.activeElement.id"), "vaultPass")
    page.fill("#vaultPass", "输入错误的备份密码")
    page.click("#vaultRestore")
    page.wait_for_function("() => !vaultBusy")
    ck("错误密码显示明确提示", "密码不对" in page.locator("#vaultStatus").inner_text())
    ck("密码错误本机不变", page.evaluate("localStorage.getItem('jian.v1')"), before)
    ck("错误密码之后清空输入框", page.input_value("#vaultPass"), "")

    # 密文被篡改：UI 只能拒绝，还不能触发导入。
    mutated = dict(data)
    mutated["savedAt"] += 1
    page.locator("#fileImport").set_input_files({"name":"tampered.json","mimeType":"application/json",
       "buffer":json.dumps(mutated,ensure_ascii=False).encode("utf-8")})
    page.wait_for_function("() => pendingEncryptedBackup !== null")
    page.fill("#vaultPass", pwd)
    page.click("#vaultRestore")
    page.wait_for_function("() => !vaultBusy")
    ck("篡改头部同样被拒绝", "密码不对" in page.locator("#vaultStatus").inner_text())
    ck("篡改数据仍不改变本机", page.evaluate("localStorage.getItem('jian.v1')"), before)

    page.locator("#fileImport").set_input_files({"name":"original.json","mimeType":"application/json","buffer":payload})
    page.wait_for_function("() => pendingEncryptedBackup !== null")
    page.fill("#vaultPass", pwd)
    page.click("#vaultRestore")
    page.wait_for_function("() => state.wardrobe[0].name==='私人蓝衬衫'", timeout=15000)
    ck("正确密码还原原来的衣服与记录", page.evaluate("() => [state.wardrobe[0].name,state.yanCards[0].line]"),
       ["私人蓝衬衫","不能公开的句子"])
    ck("导入之后可以一键撤销", page.locator("#toasts .toast.act button").count() > 0)
    page.locator("#toasts .toast.act button").first.click()
    ck("撤销恢复导入前的本机记录", page.evaluate("state.wardrobe[0].name"), "导入前修改的衣服")

    # 原有的明文 JSON 兼容路线。只走读取/写入，不丢备注、设置，且可撤销。
    plain = {"savedAt":1793562000000, "schema":3, "wardrobe":[{"id":"plain","name":"老备份衬衫","cat":"上衣","color":"#123456"}],
      "modules":{"yi":True,"wei":True,"yan":True}}
    page.evaluate("show('me')")
    page.locator("#fileImport").set_input_files({"name":"old.json","mimeType":"application/json",
       "buffer":json.dumps(plain,ensure_ascii=False).encode("utf-8")})
    page.wait_for_function("() => state.wardrobe[0].name==='老备份衬衫'", timeout=15000)
    ck("原有明文 JSON 导入继续兼容", page.evaluate("state.wardrobe[0].name"), "老备份衬衫")
    page.evaluate("show('me')")
    ck("切换文件后解密按钮不会恢复旧加密文件", page.locator("#vaultRestore").count() == 1 and page.locator("#vaultRestore").is_hidden())

    page.set_viewport_size({"width":320,"height":720})
    page.locator("#vaultBox summary").click()
    ck("320 宽加密备份表单不横向溢出", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    ck("加密操作目标大于等于 44px", page.evaluate("""() => {
      const r=document.querySelector('#vaultExport').getBoundingClientRect();
      return r.width>=44 && r.height>=44;
    }"""))
    ck("无页面脚本异常", errors, [])
    ck("全程不向第三方发请求", external, [])
    ctx.close(); browser.close()
ok = sum(checks)
print(f"\n加密备份浏览器：{ok} 通过 / {len(checks)-ok} 失败")
sys.exit(0 if all(checks) else 1)
