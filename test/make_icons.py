# 生成「笺」的应用图标：纸色底 + 一枚印章。
# 运行：python test/make_icons.py
# 用浏览器 canvas 画，字体走系统衬线，比 PIL 稳。
import base64
import pathlib

from playwright.sync_api import sync_playwright

JIAN = pathlib.Path(__file__).resolve().parent.parent
OUT = JIAN / "icons"
OUT.mkdir(exist_ok=True)

HTML = """<!DOCTYPE html><html><body><canvas id="c"></canvas><script>
window.draw = function (size, opts) {
  opts = opts || {};
  var round = opts.round === undefined ? size * 0.22 : opts.round;
  var inkScale = opts.inkScale || 0.60;
  var c = document.getElementById('c');
  c.width = size; c.height = size;
  var x = c.getContext('2d');
  x.clearRect(0, 0, size, size);

  x.fillStyle = '#f4efe6';
  if (round > 0) {
    x.beginPath();
    x.moveTo(round, 0);
    x.arcTo(size, 0, size, size, round);
    x.arcTo(size, size, 0, size, round);
    x.arcTo(0, size, 0, 0, round);
    x.arcTo(0, 0, size, 0, round);
    x.closePath();
    x.fill();
  } else {
    x.fillRect(0, 0, size, size);
  }

  var cx = size / 2, cy = size / 2;
  var rr = size * inkScale / 2;

  x.strokeStyle = '#b54a3c';
  x.lineWidth = Math.max(2, size * 0.042);
  x.beginPath();
  x.arc(cx, cy, rr, 0, Math.PI * 2);
  x.stroke();

  x.fillStyle = '#b54a3c';
  x.font = Math.round(size * inkScale * 0.56) + 'px "Songti SC","STSong","Noto Serif SC","SimSun",serif';
  x.textAlign = 'center';
  x.textBaseline = 'middle';
  x.fillText('笺', cx, cy + size * 0.012);
  return c.toDataURL('image/png');
};
</script></body></html>"""

TARGETS = [
    ("icon-192.png", 192, {"round": 42}),
    ("icon-512.png", 512, {"round": 112}),
    ("icon-maskable-512.png", 512, {"round": 0, "inkScale": 0.46}),
    ("apple-touch-icon.png", 180, {"round": 0, "inkScale": 0.58}),
    ("favicon.png", 64, {"round": 14}),
    # iOS/Android 通用启动图。方图会被按「覆盖」缩放裁切，印章按最窄可见宽度
    # (约 2732 的 46%) 缩进安全区，画法与 icon-512 一致，只是取整张方形不倒角。
    ("splash-2732.png", 2732, {"round": 0, "inkScale": 0.44}),
]

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    page.set_content(HTML)
    for name, size, opts in TARGETS:
        data = page.evaluate("([size, opts]) => window.draw(size, opts)", [size, opts])
        raw = base64.b64decode(data.split(",", 1)[1])
        (OUT / name).write_bytes(raw)
        print(f"  {name}  {size}x{size}  {len(raw)//1024} KB")
    browser.close()

# favicon.ico：把 64px 的 png 直接当 ico 用（浏览器认）
src = OUT / "favicon.png"
(OUT / "favicon.ico").write_bytes(src.read_bytes())
print("  favicon.ico  (复用 64px png)")
print("图标已生成到", OUT)
