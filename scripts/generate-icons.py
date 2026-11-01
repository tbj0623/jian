# generate-icons.py — 用 Pillow 手动生成 Android 的图标与启动图资源（@capacitor/assets 的回退方案）。
# 输入：icons/icon-512.png（纸底 logo）、icons/icon-maskable-512.png（图案缩在安全区里的 maskable）
# 输出：android/app/src/main/res/mipmap-*/ic_launcher*{,_monochrome}.png
#       + drawable-*/splash_icon.png（启动画面中央那枚印）+ 背景色更新
# 用法：python scripts/generate-icons.py
# 别用 npm run assets 生成启动图：它按整屏铺一张 2732×2732，11 个密度目录各存一份 = 2.9MB，
# 解码出来是 29MB 位图。启动图现在由 drawable/splash.xml（纸底 + 居中这枚印）负责。
from PIL import Image, ImageDraw
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'res')
BG = (244, 239, 230, 255)  # #f4efe6
SEAL = (181, 74, 60)       # #b54a3c styles.css 里的 --seal

DENSITIES = {  # dir -> launcher size(=dp*密度), foreground size(=108dp*密度)
    'mipmap-mdpi': (48, 108),
    'mipmap-hdpi': (72, 162),
    'mipmap-xhdpi': (96, 216),
    'mipmap-xxhdpi': (144, 324),
    'mipmap-xxxhdpi': (192, 432),
}


def composite_square(src, size):
    """logo 合成到 #f4efe6 底上，方形。"""
    canvas = Image.new('RGBA', (size, size), BG)
    icon = src.resize((size, size), Image.LANCZOS)
    canvas.alpha_composite(icon)
    return canvas


def round_masked(img):
    """圆形蒙版（4x 超采样抗锯齿），圆外透明。"""
    size = img.size[0]
    big = size * 4
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def seal_layer(src, size, color):
    """从整张 logo 里把「那一枚印」抠出来：离纸色越远越实，纸本身全透明。

    两个地方要它：安卓 13 的主题图标（monochrome 层要的是剪影，系统自己上色）、
    以及启动画面中央那枚红印（Theme.SplashScreen 的 animatedIcon）。
    拿 maskable 那张做源，因为它的图案本来就缩在安全区里，被圆形蒙版切也不会掉边。"""
    img = src.convert('RGBA').resize((size, size), Image.LANCZOS)
    ref = ((SEAL[0] - BG[0]) ** 2 + (SEAL[1] - BG[1]) ** 2 + (SEAL[2] - BG[2]) ** 2) ** 0.5
    px = img.load()
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    o = out.load()
    for y in range(size):
        for x in range(size):
            r, g, b, _a = px[x, y]
            d = ((r - BG[0]) ** 2 + (g - BG[1]) ** 2 + (b - BG[2]) ** 2) ** 0.5
            if d <= 1.0:
                continue                      # 纯纸：留透明
            t = min(1.0, d / ref * 1.25)      # 抗锯齿的过渡色按比例带上
            o[x, y] = (color[0], color[1], color[2], round(255 * t))
    return out


def main():
    logo = Image.open(os.path.join(ROOT, 'icons', 'icon-512.png')).convert('RGBA')
    maskable = Image.open(os.path.join(ROOT, 'icons', 'icon-maskable-512.png')).convert('RGBA')

    for d, (launcher, fg) in DENSITIES.items():
        out_dir = os.path.join(RES, d)
        os.makedirs(out_dir, exist_ok=True)

        square = composite_square(logo, launcher)
        square.save(os.path.join(out_dir, 'ic_launcher.png'))

        round_masked(square).save(os.path.join(out_dir, 'ic_launcher_round.png'))

        # adaptive 前景：maskable 全出血缩放（其自身已含安全区边距），底透明
        canvas = Image.new('RGBA', (fg, fg), (0, 0, 0, 0))
        canvas.alpha_composite(maskable.resize((fg, fg), Image.LANCZOS))
        canvas.save(os.path.join(out_dir, 'ic_launcher_foreground.png'))

        # 主题图标层（安卓 13+）：同一枚印的剪影，黑色靠 alpha，系统按主题上色
        seal_layer(maskable, fg, (0, 0, 0)).save(os.path.join(out_dir, 'ic_launcher_monochrome.png'))

        print(f'{d}: ic_launcher {launcher}px, foreground/monochrome {fg}px')

    # 启动画面中央那枚红印：按密度各放一张（108dp × 密度），
    # 替代以前那 11 张 2732×2732 的整屏位图——一张 29MB 的位图解码量，够把低端机卡出黑屏
    for d, (_launcher, fg) in DENSITIES.items():
        dd = d.replace('mipmap', 'drawable')
        out_dir = os.path.join(RES, dd)
        os.makedirs(out_dir, exist_ok=True)
        seal_layer(maskable, fg, SEAL).save(os.path.join(out_dir, 'splash_icon.png'))
        print(f'{dd}: splash_icon {fg}px')

    # adaptive 背景色对齐应用底色
    color_xml = os.path.join(RES, 'values', 'ic_launcher_background.xml')
    with open(color_xml, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
                '    <color name="ic_launcher_background">#f4efe6</color>\n</resources>\n')
    print('values/ic_launcher_background.xml -> #f4efe6')
    print('done.')


if __name__ == '__main__':
    main()
