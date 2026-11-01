"""真模型跑一遍全流程（可选，不进 npm run check）。
需要外部先把网关和模型配好：
    set JIAN_GATEWAY=http://127.0.0.1:8787
    set JIAN_LLM_BASE=https://…/v1   JIAN_LLM_KEY=…   JIAN_LLM_MODEL=agnes-2.5-flash
    python backend/gateway.py
    python test/gateway_live.py
没配就退出码 3 并说「跳过」——守门全套里没有它，因为那套必须不依赖网络和密钥。

素材：test/_audit/ 下两张图（一张衣服、一张聊天截图）。没有就先跑
    python test/_audit/make_assets.py
"""
import sys, os, json, time, pathlib, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = pathlib.Path(__file__).resolve().parent.parent
GW = os.environ.get("JIAN_GATEWAY", "").rstrip("/")
GAR = next(iter(sorted((ROOT / "vibe_images").glob("garment-*.png"))), None) if (ROOT / "vibe_images").exists() else None
CHAT = ROOT / "test" / "_audit" / "chat-screenshot.png"

if not GW:
    print("跳过：没设 JIAN_GATEWAY（也不该在 npm run check 里跑——它要网络和真密钥）")
    raise SystemExit(3)
missing = [str(p) for p in (GAR, CHAT) if not p or not pathlib.Path(p).exists()]
if missing:
    print("跳过：缺素材 " + "、".join(missing) + "；衣服图放 vibe_images/，截图跑 make_assets.py")
    raise SystemExit(3)

from playwright.sync_api import sync_playwright  # noqa: E402

ok = 0
bad = 0


def chk(n, c, d=''):
    global ok, bad
    print(('  ok   ' if c else '  FAIL ') + n + ('   ' + str(d)[:170] if d != '' else ''))
    if c:
        ok += 1
    else:
        bad += 1


BOOT = ("(base) => { state.onboarded = true; state.points = 40; state.apiUrl = base;"
        " window.JIAN_CONFIG.endpoint = base; save(state); }")

with sync_playwright() as p:
    b = p.chromium.launch(channel='msedge', headless=True)
    pg = b.new_page(viewport={'width': 430, 'height': 940})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(str(ROOT / 'index.html').replace('\\', '/'))
    pg.wait_for_timeout(900)
    pg.evaluate(BOOT, GW)
    pg.reload()
    pg.wait_for_timeout(900)

    print('\n--- 1. 网关自述 ---')
    pg.evaluate("() => show('me')")
    pg.wait_for_timeout(2500)
    txt = pg.inner_text('#apiModel')
    print('   ', txt)
    chk('说得出模型名与「可用」', '可用' in txt and '没配模型' not in txt, txt)

    print('\n--- 2. 照片过笺：认出来的是模型给的 ---')
    pg.evaluate("() => { state.yiCat = '上衣'; show('yi'); }")
    pg.wait_for_timeout(200)
    t0 = time.time()
    pg.set_input_files('#fileNew', str(GAR))
    pg.wait_for_function("() => state.lastReport && state.lastReport.new", timeout=60000)
    pg.wait_for_function("() => state.lastReport.new.seen", timeout=60000)
    it = pg.evaluate("() => state.lastReport.new")
    print(f'   用了 {time.time()-t0:.1f}s 识别:', json.dumps(it.get('seen'), ensure_ascii=False),
          ' 本机主色:', it['color'])
    chk('名字来自模型', it['name'] != '想买的这件' and 0 < len(it['name']) <= 12, it['name'])
    chk('品类是模型认的那个', it['cat'] == it['seen']['cat'], it['cat'])
    chk('主色仍是本机量的', bool(re.match(r'^#[0-9a-f]{6}$', it['color'])), it['color'])
    chk('附注说得出是谁认的', '认出来的是' in pg.inner_text('#reportNote'))
    chk('印章照旧出得来', pg.evaluate("() => state.lastReport.stamp") in ('宜入', '再想想', '先别'))

    print('\n--- 3. 入柜：先落柜，认出来再就地改名 ---')
    pg.evaluate("() => show('yi')")
    pg.wait_for_timeout(200)
    n0 = pg.evaluate("() => state.wardrobe.length")
    pg.set_input_files('#fileCloth', str(GAR))
    pg.wait_for_function("() => state.wardrobe.length === N + 1".replace('N', str(n0)), timeout=20000)
    first_then = pg.evaluate("() => state.wardrobe[0].name")
    pg.wait_for_function("() => state.wardrobe[0].name !== OLD".replace('OLD', json.dumps(first_then, ensure_ascii=False)),
                         timeout=60000)
    now = pg.evaluate("() => ({name: state.wardrobe[0].name, cat: state.wardrobe[0].cat, season: state.wardrobe[0].season})")
    print('   落柜时叫', first_then, '→ 现在是', json.dumps(now, ensure_ascii=False))
    chk('那件被改名了', now['name'] != first_then, now)
    chk('季节也一起认了', bool(now.get('season')), now.get('season'))

    print('\n--- 4. 聊天截图 → 文字 → 成笺 ---')
    pg.evaluate("() => { show('yan'); document.querySelector('#yanText').value = ''; state.yanCards = []; save(state); }")
    pg.wait_for_timeout(200)
    t0 = time.time()
    pg.set_input_files('#fileYanImg', str(CHAT))
    pg.wait_for_function("() => document.querySelector('#yanText').value.length > 20", timeout=60000)
    box = pg.input_value('#yanText')
    print(f'   抄了 {time.time()-t0:.1f}s:', repr(box[:130]))
    chk('七句都在', all(s in box for s in ['材料发我', '买一盒', '周五见', '时间再说', '拿一下', '报价', '酱油']))
    pg.evaluate("() => runYan()")
    pg.wait_for_function("() => (state.yanCards||[]).length >= 3", timeout=30000)
    cards = pg.evaluate("() => state.yanCards.map(c => c.k)")
    chk('截图里的话真的捞成了笺', len(cards) >= 4, cards)
    chk('四类里至少出现三类', len(set(cards)) >= 3, sorted(set(cards)))

    print('\n--- 5. 断网关：一切照旧 ---')
    pg.evaluate("() => { state.apiUrl = ''; window.JIAN_CONFIG.endpoint = ''; save(state); }")
    pg.reload()
    pg.wait_for_timeout(800)
    pg.evaluate("() => { state.points = 30; save(state); show('yi'); }")
    pg.wait_for_timeout(200)
    pg.set_input_files('#fileNew', str(GAR))
    pg.wait_for_function("() => state.lastReport && state.lastReport.new", timeout=30000)
    chk('没网关照样过笺', bool(pg.evaluate("() => state.lastReport.stamp")))
    chk('没有识别那一行', pg.evaluate("() => !state.lastReport.new.seen"))
    chk('无 JS 运行时错误', errs == [], errs[:2])
    b.close()

print(f'\n真模型跑：{ok} 通过 / {bad} 失败')
sys.exit(1 if bad else 0)
