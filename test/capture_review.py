# 审阅截图：三档宽度、五屏、真衣服照片，一次拍齐。
#
# 为什么要固定下来：前两轮审阅的截图各人说各的——「全页」有人拍成视口裁剪，
# 430 宽当成 390，用的还是那张带 95px 白圈的手涂方块（跟未蘸墨的印章撞脸）。
# 截图口径写进脚本，下次直接跑，不再靠记忆。
#
# 口径：
#   390×844（iPhone 逻辑尺寸）全页 + 首屏；360×780（安卓最窄）全页；1440×900 桌面
#   每屏都等到 toast 掉下去才拍，免得把「已复制」糊在版面上
#   过笺用一张画出来的毛衣照片（针织纹 + 侧光 + 颗粒），不是纯色块
#
# 运行：PYTHONIOENCODING=utf-8 python test/capture_review.py
import base64
import pathlib

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
OUT = JIAN / ".impeccable" / "review"
OUT.mkdir(parents=True, exist_ok=True)
URL = (JIAN / "index.html").as_uri()

# 在页面里画一张「燕麦色针织衫」：底色 + 竖向罗纹 + 侧光 + 噪点，导出成 JPEG 文件
SUIT = """() => {
  const w = 900, h = 1200;
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const x = c.getContext('2d');
  // 影棚灰白背景，衣服占中间一大块，边界是肩线和下摆
  const bg = x.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, '#efeae2'); bg.addColorStop(1, '#ded7cc');
  x.fillStyle = bg; x.fillRect(0, 0, w, h);
  const body = () => {
    x.beginPath();
    x.moveTo(150, 250);                       // 左肩
    x.quadraticCurveTo(450, 150, 750, 250);   // 肩线（领口在最中间凹下去）
    x.quadraticCurveTo(830, 330, 800, 470);   // 右袖
    x.lineTo(770, 1050);                      // 右下摆
    x.quadraticCurveTo(450, 1120, 130, 1050); // 下摆
    x.lineTo(100, 470);
    x.quadraticCurveTo(70, 330, 150, 250);
    x.closePath();
  };
  const fill = x.createLinearGradient(100, 0, 800, 0);
  fill.addColorStop(0, '#b9a892'); fill.addColorStop(.35, '#d8c9b4');
  fill.addColorStop(.62, '#e2d5c2'); fill.addColorStop(1, '#ab9982');
  body(); x.save(); x.clip();
  x.fillStyle = fill; x.fillRect(0, 0, w, h);
  // 罗纹：竖向细条纹，间距带一点抖动，别像栅栏
  for (let i = 60; i < 860; i += 9) {
    x.strokeStyle = `rgba(120, 100, 78, ${0.05 + 0.035 * Math.sin(i * 0.7)})`;
    x.lineWidth = 2.4;
    x.beginPath(); x.moveTo(i, 150); x.lineTo(i + 6, 1120); x.stroke();
  }
  // 针织的横向颗粒
  for (let j = 160; j < 1120; j += 6) {
    x.strokeStyle = 'rgba(90, 74, 56, 0.035)';
    x.lineWidth = 1;
    x.beginPath(); x.moveTo(90, j + Math.sin(j * 0.11) * 2); x.lineTo(810, j); x.stroke();
  }
  // 袖子接缝 + 领口罗纹边
  x.strokeStyle = 'rgba(70, 56, 40, .22)'; x.lineWidth = 6;
  x.beginPath(); x.moveTo(215, 265); x.lineTo(190, 1040); x.stroke();
  x.beginPath(); x.moveTo(690, 265); x.lineTo(715, 1040); x.stroke();
  x.strokeStyle = 'rgba(255,255,255,.5)'; x.lineWidth = 3;
  x.beginPath(); x.moveTo(218, 268); x.lineTo(193, 1040); x.stroke();
  x.beginPath(); x.moveTo(687, 268); x.lineTo(712, 1040); x.stroke();
  x.strokeStyle = 'rgba(80, 64, 46, .30)'; x.lineWidth = 26;
  x.beginPath(); x.moveTo(330, 214); x.quadraticCurveTo(450, 292, 570, 214); x.stroke();
  // 一道侧光、一圈暗角
  const light = x.createLinearGradient(0, 200, 900, 1100);
  light.addColorStop(0, 'rgba(255,250,240,.22)'); light.addColorStop(.5, 'rgba(255,255,255,0)');
  light.addColorStop(1, 'rgba(40,30,20,.20)');
  x.fillStyle = light; x.fillRect(0, 0, w, h);
  x.restore();
  // 噪点：让 JPEG 有压缩痕迹，别像矢量色块
  const img = x.getImageData(0, 0, w, h), d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * 14;
    d[i] += n; d[i + 1] += n; d[i + 2] += n;
  }
  x.putImageData(img, 0, 0);
  return c.toDataURL('image/jpeg', 0.86);
}"""

RUN_YI = """(dataUrl) => {
  const b = atob(dataUrl.split(',')[1]);
  const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
  runYi(new File([u], 'sweater.jpg', { type: 'image/jpeg' }));
}"""

SETUP = """() => {
  state.people = [
    { name: '我', chips: ['花生'] },
    { name: '小周', chips: ['辣'] },
    { name: '阿姨', chips: ['海鲜'] }
  ];
  document.querySelector('#menu').value =
    '宫保鸡丁\\n水煮鱼\\n蒜蓉西兰花\\n白切鸡\\n酸菜鱼\\n花生豆腐\\n米饭\\n西红柿蛋汤';
  document.querySelector('#yanText').value =
    '明天下午记得把材料发我。\\n药快没了帮我买一盒。\\n那就周五见吧。\\n时间再说。\\n快递到了你拿一下。\\n小王让我周四前把报价发过去。';
  save(state);
  renderWeiPeople();   // 不重渲染的话，拍出来的人卡还是种子柜那两张
}"""


# 全页截图会把 position:fixed 的底栏画在初始视口那一屏的底部——图中间凭空多一条导航，
# 上一轮审阅就是被这个假象带跑的。拍之前把它挪到整篇纸的最下面，拍完原样放回去。
PIN_NAV = """() => {
  const n = document.querySelector('#nav');
  if (!n || getComputedStyle(n).display === 'none') return false;
  n.dataset.prev = n.style.cssText;
  n.style.position = 'absolute';
  n.style.bottom = 'auto';
  n.style.top = (document.documentElement.scrollHeight - n.offsetHeight) + 'px';
  return true;
}"""
UNPIN_NAV = """(on) => {
  if (!on) return;
  const n = document.querySelector('#nav');
  n.style.cssText = n.dataset.prev || '';
  delete n.dataset.prev;
}"""


def settle(page):
    """等入场动画跑完、toast 自己掉下去，再拍。"""
    page.wait_for_function("() => !document.querySelector('.toast')", timeout=8000)
    page.wait_for_timeout(700)


def shot(page, name, full=True, fold=False):
    settle(page)
    if full:
        on = page.evaluate(PIN_NAV)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        page.evaluate(UNPIN_NAV, on)
    if fold:
        page.screenshot(path=str(OUT / f"{name}-fold.png"))
    print(f"  · {name}.png" + ("（含首屏）" if fold else ""))


def boot(page):
    page.goto(URL)
    page.wait_for_timeout(500)
    shot(page, "onboard", full=False)
    page.click("#go")
    page.wait_for_timeout(400)
    page.evaluate(SETUP)


def flow(page, tag, data_url):
    shot(page, f"{tag}-yi-empty", fold=tag == "m390")
    # 点中一件，把「改名 / 改品类 / 改季节 / 去掉」这条操作条也拍进来
    page.evaluate("() => { const t = document.querySelector('#closet .item[data-id]'); if (t) t.click(); }")
    page.wait_for_timeout(250)
    shot(page, f"{tag}-yi-actions")
    page.evaluate("() => { state.clothSel = null; save(state); show('yi'); }")
    page.wait_for_timeout(200)
    page.evaluate(RUN_YI, data_url)
    page.wait_for_function("() => state.lastReport !== null", timeout=20000)
    page.wait_for_timeout(400)
    page.evaluate("() => show('yi')")
    shot(page, f"{tag}-yi", fold=tag == "m390")   # 首屏：照片已经压在槽位里
    page.evaluate("() => { paintReport(); show('yi-report'); }")
    shot(page, f"{tag}-yi-report", fold=tag == "m390")
    page.evaluate("() => show('yi')")
    page.wait_for_timeout(200)
    page.evaluate("() => { state.editCloset = true; save(state); show('yi'); }")
    page.wait_for_timeout(300)
    shot(page, f"{tag}-yi-closet-edit")
    page.evaluate("() => { state.editCloset = false; save(state); show('wei'); }")
    page.wait_for_timeout(200)
    page.evaluate("() => runWei()")
    page.wait_for_function("() => document.querySelector('#weiResult').innerHTML.trim().length > 0", timeout=20000)
    page.evaluate("() => show('wei')")
    shot(page, f"{tag}-wei", fold=tag == "m390")
    page.evaluate("() => { whoOpen = [1]; renderWeiPeople(); }")   # 展开一枚忌口选择器
    page.wait_for_timeout(250)
    shot(page, f"{tag}-wei-jikou")
    page.evaluate("() => { whoOpen = []; renderWeiPeople(); }")
    page.evaluate("() => show('yan')")
    page.wait_for_timeout(200)
    page.evaluate("() => runYan()")
    page.wait_for_function("() => (state.yanCards || []).length > 0", timeout=20000)
    page.evaluate("""() => {
      const c = state.yanCards.find((x) => x.k === '待办') || state.yanCards[0];
      c.done = true; save(state); renderYan(); show('yan');
    }""")
    shot(page, f"{tag}-yan", fold=tag == "m390")
    page.evaluate("() => { state.yanView = 'time'; save(state); renderYan(); }")
    page.wait_for_timeout(300)
    shot(page, f"{tag}-yan-time")
    page.evaluate("() => { state.yanView = 'kind'; save(state); renderYan(); show('me'); }")
    shot(page, f"{tag}-me", fold=tag == "m390")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3)
    page = ctx.new_page()
    page.clock.install(time="2026-09-17T10:00:00")
    boot(page)
    data_url = page.evaluate(SUIT)
    (OUT / "garment-photo.jpg").write_bytes(base64.decodebytes(data_url.split(",")[1].encode()))
    print("\n=== 390×844 ===")
    flow(page, "m390", data_url)
    page.evaluate("""() => {
      state.lastReport = null; state.lastNew = null; state.album = []; state.yanCards = [];
      save(state); paintHero();
    }""")

    print("\n=== 360×780 ===")
    page.set_viewport_size({"width": 360, "height": 780})
    page.evaluate("() => show('yi')")
    flow(page, "m360", data_url)

    print("\n=== 1440×900 ===")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("() => { state.lastReport = null; state.lastNew = null; save(state); paintHero(); }")
    shot(page, "d1440-yi-empty")
    page.evaluate(RUN_YI, data_url)
    page.wait_for_function("() => state.lastReport !== null", timeout=20000)
    page.wait_for_timeout(400)
    page.evaluate("() => show('yi')")
    shot(page, "d1440-yi")
    page.evaluate("() => { paintReport(); show('yi-report'); }")
    shot(page, "d1440-yi-report")
    page.evaluate("() => show('wei')")
    shot(page, "d1440-wei")
    page.evaluate("() => show('yan')")
    shot(page, "d1440-yan")
    page.evaluate("() => show('me')")
    shot(page, "d1440-me")

    ctx.close()
    browser.close()

print(f"\n写到 {OUT}")
