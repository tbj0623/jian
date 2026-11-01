# make-store-assets.py — 生成 Google Play 需要的两张静态素材：应用图标(512) 与特性图(1024×500)。
#
# 为什么用脚本而不是手画：特性图上有纸纹、印章、宋体标题，手画每次都不一样；
# 换 slogan 或换纸色时要能一起重出，所以和 scripts/generate-icons.py 同一个道理。
#
# 输入：icons/icon-512.png（纸底 + 印章 logo）、styles.css 里的 --paper / --ink / --seal
# 输出：store/icon-512.png、store/feature-graphic-1024x500.png
# 用法：python scripts/make-store-assets.py
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('JIAN_STORE_OUT') or os.path.join(ROOT, 'store')
# 上面那个环境变量是留给门禁的缝：test/store_claims.py 把同一份脚本跑进临时目录，
# 再和仓库里这两张 PNG 逐字节对——「改了脚本忘了重跑图」就是这次「零联网」活在特性图上的原因。
PAPER = (244, 239, 230)     # --paper
INK = (42, 39, 35)          # --ink
SEAL = (181, 74, 60)        # --seal
SOFT = (122, 112, 98)       # --ink-soft 那一档

W, H = 1024, 500            # Play 的特性图规格，要求 ≤1MB


def font(size, serif=True):
    """中文用宋体（styles.css 的品牌字栈里就有 SimSun），说明文字用雅黑。"""
    names = (['simsun.ttc', 'SimsunExtG.ttf', 'simhei.ttf'] if serif
             else ['msyh.ttc', 'simhei.ttf', 'simsun.ttc'])
    for n in names:
        p = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def paper(size):
    """复刻 body 那张纸：底色 + 每 7px 一根 1px 的竖纹（styles.css 的 repeating-linear-gradient）。"""
    img = Image.new('RGB', size, PAPER)
    d = ImageDraw.Draw(img)
    for x in range(0, size[0], 7):
        d.line([(x, 0), (x, size[1])], fill=(240, 235, 226), width=1)
    return img


def seal_layer(src, size):
    """从整张 logo 里把印章抠出来（离纸色越远越实），要的是它压在特性图上时不带那块方底。"""
    img = src.convert('RGBA').resize((size, size), Image.LANCZOS)
    ref = sum((a - b) ** 2 for a, b in zip(SEAL, PAPER)) ** 0.5
    px, out = img.load(), Image.new('RGBA', (size, size), (0, 0, 0, 0))
    o = out.load()
    for y in range(size):
        for x in range(size):
            r, g, b, _ = px[x, y]
            d = ((r - PAPER[0]) ** 2 + (g - PAPER[1]) ** 2 + (b - PAPER[2]) ** 2) ** 0.5
            if d <= 1.0:
                continue
            o[x, y] = (SEAL[0], SEAL[1], SEAL[2], min(255, round(255 * d / ref * 1.25)))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    logo = Image.open(os.path.join(ROOT, 'icons', 'icon-512.png'))

    # 1) 应用图标：Play 要 512×512 的 32 位 PNG，直接就是仓库里那张
    icon = logo.convert('RGBA').resize((512, 512), Image.LANCZOS)
    icon.save(os.path.join(OUT, 'icon-512.png'))
    print('store/icon-512.png 512x512')

    # 2) 特性图 1024×500
    img = paper((W, H)).convert('RGBA')
    d = ImageDraw.Draw(img)
    # 用 maskable 那张抠印：icon-512 的四角有括号形装饰，抠出来会变成一圈假边框
    seal = seal_layer(Image.open(os.path.join(ROOT, 'icons', 'icon-maskable-512.png')), 300)
    img.alpha_composite(seal, (58, 100))

    d.text((400, 96), '笺', font=font(200), fill=INK)
    d.text((404, 300), '一张短笺，一次决定。', font=font(46), fill=INK)
    d.text((406, 372), '衣笺 · 味笺 · 言笺', font=font(30, serif=False), fill=SOFT)
    # 「零联网」这个词在第十七轮之后就禁写了（用户能自己填一台网关，照片确实会发出去），
    # 商店材料第 2 节明写着换成「不联网也能用」。可这张图是从第十七轮之前那行字一直刷出来的
    # ——像素里烤着的假话不会自己过期，第 57 轮由 storeready 审出来。
    d.text((406, 418), '零账号 · 零广告 · 不联网也能用', font=font(26, serif=False), fill=SOFT)
    # 一条印章红的细边压住底部：Play 的列表页会把特性图裁成 16:9，边缘别放字
    d.line([(0, H - 6), (W, H - 6)], fill=SEAL, width=6)

    out = os.path.join(OUT, 'feature-graphic-1024x500.png')
    img.convert('RGB').save(out, optimize=True)
    kb = os.path.getsize(out) // 1024
    print(f'store/feature-graphic-1024x500.png 1024x500 {kb}KB')
    if kb > 1024:
        raise SystemExit('特性图超过 1MB，Play 不收')


if __name__ == '__main__':
    main()
