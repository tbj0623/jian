"""设备脚本开工前先认领串口：这套要跑在 **jian_test** 上，别的 AVD 一律不动。

为什么单独一个模块：本机同时开着好几个 Qoder 会话，它们共用同一个 adb server，
而模拟器串口会**漂**——自己那台退了，别人的 AVD 可能马上顶到同一个 `emulator-5554`。
以前五套设备脚本都写着 `os.environ.get("ANDROID_SERIAL") or "emulator-5554"`：
忘了带环境变量，就会把笺的包装到**另一个项目的模拟器**上，跑完还报一句「全绿」。
那不是量错了，是动了别人的东西。

（2026-09-23 就是这么撞上的：`emulator-5554` 当时是随拍会话的 `suipai_r4`。）

规矩：`require_avd()` 只在**串口唯一**或 `ANDROID_SERIAL` 明确给了的时候放行，
并且必须 `adb emu avd name` 回 `jian_test` 才继续；否则直接退出，把该怎么做写清楚。
"""
import os
import pathlib
import subprocess
import sys

ADB = str(pathlib.Path.home() / "AppData" / "Local" / "Android" / "Sdk"
          / "platform-tools" / "adb.exe")
WANT = "jian_test"


def _run(args):
    """所有 adb 问话都走这里：离线门（test/device_guards.py）打桩就打在这一个函数上。

    收成一道口是因为这道门的全部价值都在「问出来的是什么名字 → 放不放行」这条判定上，
    而过程边界（真起一个 adb 进程）没有可测的东西。散成三处 subprocess.run 的话，
    打桩就得改源码，那条门也就量不到真的那份逻辑了。
    """
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)


def attached():
    """`adb devices` 上状态是 device 的那些串口。"""
    p = _run([ADB, "devices"])
    return [ln.split()[0] for ln in (p.stdout or "").splitlines()[1:]
            if ln.strip() and ln.split()[1] == "device"]


def avd_name(serial):
    p = _run([ADB, "-s", serial, "emu", "avd", "name"])
    lines = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def require_avd(quiet=False):
    """确认要用的那台就是 jian_test，返回串口；不是就退出进程。"""
    serial = os.environ.get("ANDROID_SERIAL", "").strip()
    if not serial:
        got = attached()
        if not got:
            sys.exit(f"[设备门] 没有在线的设备。要么起一台 jian_test，"
                     f"要么明确给 ANDROID_SERIAL。（现在 adb devices 是空的）")
        if len(got) > 1:
            sys.exit(f"[设备门] 在线的不止一台：{got}。这套脚本不猜——"
                     f"请带 ANDROID_SERIAL=<你那台 jian_test 的串口> 再跑。")
        serial = got[0]
    name = avd_name(serial)
    if name != WANT:
        sys.exit(f"[设备门] {serial} 上是 AVD「{name or '问不到名字'}」，不是「{WANT}」。\n"
                 f"          这台属于别的会话或别的项目，这套脚本不会往上装包、也不碰它。\n"
                 f"          起自己的那台：emulator -avd {WANT} -no-window -no-audio "
                 f"-no-boot-anim -no-snapshot-save -gpu auto，"
                 f"然后用 ANDROID_SERIAL=<它的串口> 重跑。")
    os.environ["ANDROID_SERIAL"] = serial   # cap-cdp 里那句不带 -s 的 `adb shell pidof` 也跟着认这台
    if not quiet:
        print(f"[设备门] {serial} = AVD「{name}」，可以动。")
    return serial


if __name__ == "__main__":
    print("require_avd() ->", require_avd())
