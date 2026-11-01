# release 包冒烟验收：装**真正要上架的那个包**，看它到底画没画出来。
#
# 为什么单独一套：release 包没有 CDP（CapConfig 的 webContentsDebuggingEnabled 跟随 isDebug），
# device_verify.py 那套桥驱动对它完全无效。而 release 恰好是唯一会过 R8 的构建类型
# （minify + shrinkResources）——它最坏的死法是「编得过、装得上、某个东西静默没了」：
# 插件被裁掉不会报错，按名字查的资源被裁掉也不会。所以这个包必须被真的装起来看一眼。
#
# 看什么：
#   1. 签名是不是正式那把钥匙（CN=Jian），不是 Android Debug——装错钥匙上不了架；
#   2. 冷启动之后屏幕上真的有「墨」（正文颜色），不是纯纸、不是黑屏、不是白屏；
#   3. logcat 里我们这个进程没有 FATAL / AndroidRuntime；
#   4. 启动图那张按名字查的 drawable/splash 还在（R8 裁掉它的话第一屏就没有印）。
#
# 跑完会把 debug 包装回去（device_verify 要 CDP 就得用 debug 包）。
#
# 运行：PYTHONIOENCODING=utf-8 python test/release_smoke.py
import glob
import os
import pathlib
import subprocess
import sys
import time

import io

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = "com.jian.app"
ACT = f"{PKG}/.MainActivity"
# 默认验 release APK；也可以传一个别的包进来（比如 bundletool 从 AAB 里拆出来的 universal APK），
# 那条路才代表 Play 真正会发给用户的东西。
APK = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1
       else ROOT / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk")
DEBUG_APK = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
ADB = str(pathlib.Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from device_avd import require_avd   # noqa: E402

INK = (42, 39, 35)          # styles.css 的 --ink
PAPER = (244, 239, 230)     # --paper
SERIAL = require_avd()

checks = []


def check(name, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    checks.append((ok, name, got, want))
    print(("  ok  " if ok else " FAIL ") + f"{name}  ->  {got}" + ("" if ok else f"   (期望 {want})"))


def adb(*args, binary=False):
    cmd = [ADB, "-s", SERIAL] + list(args)
    kw = {"capture_output": True, "timeout": 300}
    if binary:
        kw["text"] = False            # 注意：encoding/errors 一旦给出就会把 Popen 拉回文本模式，
    else:                             # 那样 screencap 的 PNG 会变成 str，Image.open 直接炸
        kw.update(text=True, encoding="utf-8", errors="replace")
    p = subprocess.run(cmd, **kw)
    out = p.stdout if binary else (p.stdout or "") + (p.stderr or "")
    return (p.returncode, out)


def find_apksigner():
    bt = sorted(glob.glob(str(pathlib.Path.home() / "AppData" / "Local" / "Android" / "Sdk"
                            / "build-tools" / "*")))
    for d in reversed(bt):
        exe = pathlib.Path(d) / "apksigner.bat"
        if exe.exists():
            return str(exe)
    return None


def main():
    if not APK.exists():
        print(f"没有 release 包：{APK}\n先跑 npm run release（或 gradlew assembleRelease）")
        return 1

    print("\n--- 1. 签名 ---")
    text = ""
    signer = find_apksigner()
    if signer:
        r = subprocess.run([signer, "verify", "--print-certs", str(APK)],
                           capture_output=True, text=True, errors="replace")
        text = (r.stdout or "") + (r.stderr or "")
    if "CN=" not in text:                      # 没有 build-tools 就用 keytool 兜底
        kt = str(pathlib.Path(os.environ.get("JAVA_HOME", "")) / "bin" / "keytool.exe")
        r = subprocess.run([kt, "-printcert", "-jarfile", str(APK)],
                           capture_output=True, text=True, errors="replace")
        text = r.stdout or ""
    dn = [l for l in text.splitlines() if "CN=" in l]
    line = dn[0].strip() if dn else "读不到证书"
    print(f"        {line}")
    check("release 包是正式签名（CN=Jian，不是 Android Debug）",
          ("CN=Jian" in line) and ("Android Debug" not in line), True)

    print("\n--- 2. 装上去、冷启动 ---")
    _, out = adb("uninstall", PKG)
    if "Success" not in out:
        print(f"        （卸载返回：{out.strip()[:60]}）")
    code, out = adb("install", "-r", "-t", str(APK))
    check("release 包能装上", "Success" in out, True)
    if "Success" not in out:
        print(out.strip()[:300])
        return 1

    adb("shell", "logcat", "-c")
    adb("shell", "am", "force-stop", PKG)
    time.sleep(1)
    adb("shell", "am", "start", "-n", ACT)

    # 启动图：等它出现（纸底），再等界面画出来。release 在这台机器上冷启动要十几秒，
    # 所以一律「轮询到为止」，不写死秒数。
    from PIL import Image
    shot = None
    t0 = time.time()
    seen = {"ink": 0, "paper": 0, "seal": 0}
    while time.time() - t0 < 90:
        code, png = adb("exec-out", "screencap", "-p", binary=True)
        if code != 0 or not png:
            time.sleep(1)
            continue
        im = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = im.size
        ink = paper = seal = 0
        for y in range(0, h, 7):
            for x in range(0, w, 7):
                c = im.getpixel((x, y))
                if max(abs(c[i] - INK[i]) for i in range(3)) < 26:
                    ink += 1
                if max(abs(c[i] - PAPER[i]) for i in range(3)) < 6:
                    paper += 1
                if abs(c[0] - 181) < 22 and abs(c[1] - 74) < 22 and abs(c[2] - 60) < 22:
                    seal += 1
        seen["ink"], seen["paper"], seen["seal"] = ink, paper, seal
        shot = im
        if ink > 40:       # 有墨 = 界面真的画出来了
            break
        time.sleep(1.5)
    if shot is None:
        check("截到屏了", "一次都没截到", "有图")
        return 1
    total = (shot.size[0] // 7 + 1) * (shot.size[1] // 7 + 1)
    print(f"        等了 {time.time() - t0:.1f} 秒；采样 {total} 点：墨 {seen['ink']}、纸 {seen['paper']}、印色 {seen['seal']}")
    check("release 包真的把界面画出来了（屏幕上有墨色文字）", seen["ink"] > 40, True)
    check("界面是那张纸（纸色占大头，不是黑屏白屏）", seen["paper"] / total > 0.3, True)
    check("印章红在（图标/印色资源没被 R8 裁光）", seen["seal"] > 0, True)

    print("\n--- 3. logcat 里不许有崩溃 ---")
    _, log = adb("logcat", "-d", "-v", "brief")
    mine = [l for l in log.splitlines() if PKG in l or "Capacitor" in l]
    fatal = [l for l in mine if "FATAL" in l or "AndroidRuntime" in l or "Unable to start activity" in l]
    missing = [l for l in mine if "Unable to find class" in l or "NoClassDefFoundError" in l
               or "did not find expected method" in l.lower()]
    check("没有崩溃日志", fatal[:2], [])
    check("没有类/方法被裁掉找不到", missing[:2], [])

    print("\n--- 4. 把 debug 包装回去（device_verify 要 CDP） ---")
    if DEBUG_APK.exists():
        # 必须先卸载：release 用正式钥匙、debug 用 Android Debug 钥匙，签名不同不能覆盖安装
        # （INSTALL_FAILED_UPDATE_INCOMPATIBLE），而这条只有在这套脚本里才会撞上一次。
        adb("uninstall", PKG)
        _, out = adb("install", "-r", "-t", str(DEBUG_APK))
        check("debug 包已装回", "Success" in out, True)
    else:
        print("  --  没有 debug 包，跳过装回")

    bad = [c for c in checks if not c[0]]
    print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
    for ok, name, got, want in bad:
        print(f"   ✗ {name}  ->  {got}   (期望 {want})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
