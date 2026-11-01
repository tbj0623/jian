# 设备门：五套设备脚本只准动自己那台模拟器。
#
# 为什么单独一道门：本机同时开着好几个 Qoder 会话，它们共用同一个 adb server，
# 而模拟器串口会**漂**——自己那台退了，别人的 AVD 可能立刻顶到同一个 `emulator-5554`。
# 以前五套脚本都写着 `os.environ.get("ANDROID_SERIAL") or "emulator-5554"`：忘了带环境变量，
# 就会把笺的包装到**另一个项目的模拟器**上，跑完还报一句「全绿」。那不是量错了，是动了别人的东西。
# 2026-09-23 就是这么撞上的：当时 `emulator-5554` 是随拍会话的 `suipai_r4`。
#
# 这道门不碰真设备（跑门禁的机器上可能一台都没有）：
#   第 1 节把 device_avd 里那一个 `_run()` 打桩掉，把「什么样的现场该放行」逐个判一遍；
#   第 2、3 节静态扫那五套脚本，确认它们真的都从这道门走、没有留下裸 adb 与硬写死的串口。
#
# 运行：PYTHONIOENCODING=utf-8 python test/device_guards.py
import ast
import contextlib
import io
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
# 不写字节缓存：这道门要在「源码被注入改过」的状态下 import device_avd，
# 而 .pyc 的校验只精确到秒——同秒内等长的改动会命中旧缓存，注入就隐形了。
sys.dont_write_bytecode = True
import device_avd  # noqa: E402

SCRIPTS = ["device_verify.py", "device_deeplink.py", "device_gateway.py",
           "device_perf.py", "release_smoke.py"]
ALL6 = SCRIPTS + ["device_avd.py"]

checks = []


def check(name, ok, got=""):
    # 这道口只收真判定。写成 check(name, 拿到的值, 期望的值) 时那个值几乎总是非空 = 真，
    # 于是一条断言什么都不比却天天报 ok——这一类假绿本项目踩过好几回，这里直接不让过。
    if not isinstance(ok, bool):
        raise TypeError(f"{name}：check() 要的是 True/False，比大小请用 eq()（这里收到 {type(ok).__name__}）")
    checks.append((ok, name, got))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f"  ->  {got}"))


def eq(name, got, want):
    check(name, got == want, f"{got!r}（期望 {want!r}）")


# ───────────────────────── 1. 判定本身：打桩 adb，不碰真设备 ─────────────────────────
class Out:
    def __init__(self, stdout):
        self.stdout = stdout


def fake_run(state):
    """替 device_avd._run：只答 `adb devices` 和 `-s X emu avd name` 两句，别的一律报错。

    报错是有意的：判定逻辑要是多问了一句没预料到的（比如不带 -s 的 pidof），
    这道门必须当场炸，不能默默答一句「空」让它过去。
    """
    def run(args):
        state["argv"].append(list(args))
        if args[1:] == ["devices"]:
            return Out("List of devices attached\n" +
                       "".join(f"{s}\t{st}\n" for s, st in state["devices"]) + "\n")
        if args[-3:] == ["emu", "avd", "name"]:
            if "-s" not in args:
                raise AssertionError("问 AVD 名却不带 -s：那在多台在线时会炸，见 device_avd")
            serial = args[args.index("-s") + 1]
            n = state["names"].get(serial)
            return Out("" if n is None else f"{n}\n\nOK\n")   # 真 adb 回的就是「名字 + 空行 + OK」
        raise AssertionError("打桩没预料到的 adb 调用：" + " ".join(args))
    return run


def probe(devices, names, env=None):
    """跑一次 require_avd()。返回 (结局, 消息或串口, 这次问过的 argv, 那一刻的 ANDROID_SERIAL)。

    环境变量要在还原之前抓：不然「放行时写了 / 拒绝时没写」这两条查的都是自己收的尾。
    """
    state = {"argv": [], "devices": devices, "names": names}
    saved_run, saved_env = device_avd._run, os.environ.get("ANDROID_SERIAL")
    device_avd._run = fake_run(state)
    if env is None:
        os.environ.pop("ANDROID_SERIAL", None)
    else:
        os.environ["ANDROID_SERIAL"] = env
    try:
        try:
            got = device_avd.require_avd(quiet=True)
            return "放行", got, state["argv"], os.environ.get("ANDROID_SERIAL")
        except SystemExit as e:
            return "退出", str(e), state["argv"], os.environ.get("ANDROID_SERIAL")
    finally:
        device_avd._run = saved_run
        if saved_env is None:
            os.environ.pop("ANDROID_SERIAL", None)
        else:
            os.environ["ANDROID_SERIAL"] = saved_env


ONE_OK = ([("emulator-5556", "device")], {"emulator-5556": "jian_test"})

print("--- 一台自己的模拟器在线：放行，而且把串口写给后面那些不带 -s 的 adb 调用 ---")
kind, msg, argv, env = probe(*ONE_OK)
eq("唯一一台是 jian_test → 放行，返回它的串口", (kind, msg), ("放行", "emulator-5556"))
eq("放行之后 ANDROID_SERIAL 已写成认领的那台（cap-cdp 里那句裸 `adb shell pidof` 靠它）",
   env, "emulator-5556")
check("列举串口那一句不带 -s（它要看的正是「在线的都有谁」）",
      argv[0][1:] == ["devices"])
check("问 AVD 名那一句带着 -s 精确问（不许问一台未知的）",
      argv[1][1:3] == ["-s", "emulator-5556"])

print("\n--- 2026-09-23 的真实现场：5554 上坐着别人的 suipai_r4 ---")
kind, msg, _, env = probe([("emulator-5554", "device")], {"emulator-5554": "suipai_r4"})
eq("不是 jian_test → 退出", kind, "退出")
check("退出消息点名了那台是谁、串口是什么（跑的人一眼看得懂撞了谁）",
      ("suipai_r4" in msg) and ("emulator-5554" in msg), msg[:120])
check("退出消息给了起自己那台的命令", "jian_test" in msg and "emulator" in msg, msg[:120])
check("拒绝的时候绝不把别人的串口写进 ANDROID_SERIAL", env is None, env)

kind, msg, argv, _ = probe([("emulator-5554", "device")], {"emulator-5554": "suipai_r4"},
                           env="emulator-5554")
eq("环境变量明确给了 5554 也不放行：它是一张待核实的地址，不是通行证", kind, "退出")
check("给了环境变量就不再列举设备（省一次问话，判定仍然只认名字）",
      [a[1:] for a in argv] == [["-s", "emulator-5554", "emu", "avd", "name"]], argv)

print("\n--- 「不许猜」那一档 ---")
kind, msg, _, _ = probe([("emulator-5554", "device"), ("emulator-5556", "device")],
                        {"emulator-5554": "suipai_r4", "emulator-5556": "jian_test"})
eq("两台在线又没给环境变量 → 退出，不挑「看起来像我那台」的", kind, "退出")
check("退出消息把两台串口都列出来（该由人决定用哪一台）",
      all(s in msg for s in ("emulator-5554", "emulator-5556")), msg[:120])
kind, msg, _, _ = probe([], {})
eq("一台都没在线 → 退出，而不是拿默认串口去撞", kind, "退出")

kind, msg, _, _ = probe([("emulator-5556", "offline")], {"emulator-5556": "jian_test"})
eq("状态不是 device 的那台不算在线（offline 上问不出名字）", kind, "退出")

print("\n--- 名字是全等比对：相近、包含、大小写不同都算别人的机器 ---")
for nm in ["jian_test2", "jian_test_r4", "Jian_Test", "my_jian_test", "an_test", ""]:
    kind, _, _, _ = probe([("emulator-5556", "device")], {"emulator-5556": nm})
    eq(f"AVD 叫「{nm or '（问不出来）'}」→ 不放行", kind, "退出")

print("\n--- 认领凭证是给「人」看的那一句，不能被删成静默 ---")
state = {"argv": [], "devices": ONE_OK[0], "names": ONE_OK[1]}
orig_run, saved_env = device_avd._run, os.environ.get("ANDROID_SERIAL")
device_avd._run = fake_run(state)
os.environ.pop("ANDROID_SERIAL", None)
try:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        device_avd.require_avd()          # quiet 默认 False
    line = buf.getvalue()
finally:
    device_avd._run = orig_run
    if saved_env is None:
        os.environ.pop("ANDROID_SERIAL", None)
    else:
        os.environ["ANDROID_SERIAL"] = saved_env
check("放行时打印「哪台串口 = 哪个 AVD，可以动」（跑的人要能确认动的是自己那台）",
      "emulator-5556" in line and "jian_test" in line, line.strip()[:120])


# ─────────────────────── 2. 那五套脚本确实从这道门走 ───────────────────────
print("\n--- 五套设备脚本的接线（静态）---")


def code_lines(text):
    """去掉注释行与空行：文档里写「以前默认是 5554」不是违规，能跑的那几行才是。"""
    return [(i, ln) for i, ln in enumerate(text.splitlines(), 1)
            if ln.strip() and not ln.strip().startswith("#")]


nadb = 0
exempt = []
for fn in ALL6:
    text = (HERE / fn).read_text(encoding="utf-8")
    lines = code_lines(text)
    if fn in SCRIPTS:
        check(f"{fn} 问了设备门", "require_avd(" in text, "没调用")
        check(f"{fn} 把认领到的串口用作 SERIAL",
              bool([ln for _, ln in lines if "require_avd()" in ln and ("SERIAL" in ln or "serial" in ln)]),
              "调用过但没接住返回值？")
        check(f"{fn} 没有「环境变量没给就退回到某台」的兜底",
              'or "emulator-' not in text and 'setdefault("ANDROID_SERIAL"' not in text)
    lit = [c.value for c in ast.walk(ast.parse(text))
           if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    # 写死的串口 = 绕开这道门。注意查的是「整个字面量就是一个串口」，
    # 不是「串里含 emulator-」：文档句子里提一次 5554 不该红。
    check(f"{fn} 的字面量里没写死串口（emulator-NNNN 只能来自认领）",
          not [v for v in lit if re.fullmatch(r"emulator-\d+", v)],
          str([v for v in lit if re.fullmatch(r"emulator-\d+", v)][:3]))
    for i, ln in lines:
        if "[ADB" not in ln:
            continue
        nadb += 1
        if '"-s"' not in ln and "devices" not in ln:
            exempt.append(f"{fn}:{i}")

check("扫到了足够多的 adb 调用点（整片扫最容易的骗法是什么都没扫到）", nadb >= 8, f"{nadb} 处")
check("唯一允许不带 -s 的那一句是 `adb devices`（它要列的就是全部）",
      exempt == [], f"裸 adb：{exempt}")

print("\n--- 这道门自己的牙：check() 不收「两个值摆在一起」 ---")
try:
    check("这一句根本不该存在", "退出", "放行")        # 故意写错：第二个位置放的是值，不是判定
    拦住了 = False
except TypeError:
    拦住了 = True
check("拿非布尔当判定传给 check() 会当场炸，而不是被「非空 = 真」蒙过去", 拦住了)

# ───────────────── 4. 流水线脚本（device_accept.py）：自己起机，自己收机 ─────────────────
# 它和上面五套不是一路：那五套**借用**一台已经在跑的 jian_test（require_avd 只认名字），
# 而这一套负责把机器起出来、验完再关掉。所以它不调 require_avd，也就不能套上面那三条
# 断言——但它有自己那三条更硬的规矩，漏了任何一条都会留下 3~4 GB 的孤儿进程。
print("\n--- 流水线脚本 device_accept.py 的收尾纪律（静态） ---")
pipe_path = HERE / "device_accept.py"
if not pipe_path.exists():
    check("device_accept.py 在（不在就跳过这一节）", True)
else:
    pipe = pipe_path.read_text(encoding="utf-8")
    plines = code_lines(pipe)
    check("收尾走 try/finally", "finally:" in pipe, "没有 finally，中途失败就漏掉关机")
    check("收尾真的发 emu kill（不是只关窗口）", "emu" in pipe and "kill" in pipe and '"emu", "kill"' in pipe.replace("'", '"'),
          "没找到 emu kill")
    # 与 AGENTS.md 同一条：串口要精确，kill-server 会打断别人的会话。
    check("绝不 adb kill-server", "kill-server" not in pipe, "脚本里有 kill-server")
    # 裸 adb：唯一允许的是 `adb devices`（它要列的就是全部）。
    # 判据是「真正的 adb 调用点」= 行里出现 `[ADB`（拼 argv 的那一处），
    # 不是「行里出现 ADB」——后者会把 ADB = str(...) 这个多行常量的续行也算进来，
    # 那不是一次调用，是路径换行。
    calls = [(i, ln) for i, ln in plines if "[ADB" in ln]
    check("扫到了 adb 调用点（一处都没扫到说明这条断言在量空气）", len(calls) >= 1, f"{len(calls)} 处")
    naked = [str(i) for i, ln in calls if '"-s"' not in ln and "devices" not in ln]
    check("除了列举设备，每一处 adb 都带 -s", naked == [], f"裸 adb：{naked}")
    lit = [c.value for c in ast.walk(ast.parse(pipe))
           if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    check("字面量里没写死串口（emulator-NNNN 只能来自「新增了谁」）",
          not [v for v in lit if re.fullmatch(r"emulator-\d+", v)],
          str([v for v in lit if re.fullmatch(r"emulator-\d+", v)][:3]))
    # 五道门必须逐个跑、不许并行：一台无头模拟器扛不住两条 CDP 同时点同一张纸。
    # 判据是「顺序 for 循环」而不是 ThreadPool / asyncio.gather / &。
    check("五道门是顺序跑的（没有线程池/并发 gather 去抢同一台设备）",
          not re.search(r"ThreadPool|ProcessPool|asyncio\.gather|&\s*$", pipe, re.M),
          "出现了并发原语")

bad = [c for c in checks if not c[0]]
print(f"\n结果：{len(checks) - len(bad)} 通过 / {len(bad)} 失败")
sys.exit(1 if bad else 0)
