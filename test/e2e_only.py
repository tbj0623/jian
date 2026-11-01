# 只跑 e2e 的**某一节**——给守门自检（gate_selfcheck）用的窄跑手，不是另一套断言。
#
# 为什么要它：第 59 轮一次加了 14 发注入，全走完整 e2e 是 14 × 七分钟多。
# 而断言只有一份：这一节**按标记从 test/e2e.playwright.py 里现切**，
# 切的就是门里那批字节，所以「窄跑绿」和「那一节绿」不会是两件事（第 58 轮
# 搜索判据与终检判据分家那次，栽的就是这个形状）。
# 与 dead_controls 的 `--quick` 同一条路子：窄跑的每一条被跳过的覆盖底线都会显式印出来，
# 窄跑的绿不会被当成全量的绿。
#
# 跑法：PYTHONIOENCODING=utf-8 python test/e2e_only.py 56
import pathlib
import re
import sys

JIAN = pathlib.Path(__file__).resolve().parent.parent
SRC = (JIAN / "test" / "e2e.playwright.py").read_text(encoding="utf-8").splitlines(True)
SEC = sys.argv[1] if len(sys.argv) > 1 and re.fullmatch(r"\d+[a-z]?", sys.argv[1]) else "56"


def find(need, what, from_i=0, exact=False):
    """找不到标记就必须死在这里：静默切出半截、或者切出一段不含任何断言的空壳，
    比没有这道门更糟——它会一路报绿。"""
    try:
        return next(i for i in range(from_i, len(SRC))
                    if (SRC[i].strip() == need if exact else need in SRC[i]))
    except StopIteration:
        print(f" FAIL 在 e2e.playwright.py 里找不到「{what}」的标记 {need!r}：那一节改名或删掉了？")
        sys.exit(1)


def find_span(need, what):
    """按**节标题**切出 [start, end)：从印这一节标题的那一行，到下一节标题之前。

    为什么不再按 `ctx.close()` 找收尾（旧版那一刀）：0.6.0 的这几节（§4b/§4d/§56/§57/§59…）
    里嵌着 `page.evaluate("() => { … }")` 与 `for` 循环，**单独一行的 ctx.close()** 落在
    §60 末尾（第 5864 行）——于是「只跑第 4b 节」切出来的其实是 4b 到 59 的整段，
    红的永远是后面某一节（实测：跑 4d 崩在 §56 的 #clothWornDay 上）。节边界只有标题
    一处是真的。最后一节没有下一个标题时切到文件尾（§60 的 ctx.close() 在收尾里）。"""
    # 标题的两种前缀都要认：`1.`…`9.` 是 `--- 4b.`，两位数就是 `--- 13.`——
    # 前缀写死「%s. 」时，`13` 会先命中 §1…§9 里任何一行含子串 "13" 的标题？不会，
    # 因为带点号；但 `4b` 这种带字母的节号不走 isdigit，`end` 只能靠下一条标题。
    start = find('print("\\n--- %s. ' % SEC, "第 " + SEC + " 节")
    nxt = None
    for i in range(start + 1, len(SRC)):
        # 只认**缩进四个空格**的节标题行：正文里引用的 `--- 8. 模块开关 ---` 不缩进，
        # 免得把一节从中间劈开。
        if SRC[i].startswith('    print("\\n--- ') and 'ctx.close()' not in SRC[i]:
            nxt = i
            break
    end = nxt if nxt is not None else find("ctx.close()", "文件尾的收尾", from_i=start, exact=True) + 1
    if end <= start:
        print(" FAIL 第 " + SEC + " 节切出来是空的")
        sys.exit(1)
    return start, end


start, end = find_span(SEC, "第 " + SEC + " 节")
head = find('print("\\n--- 2. ', "第 2 节（第 1 节是引导，必须跟着）")
# `b1..b2` 那一段（BLEED / TRUNC / NARROW 三个探针）是**所有节共用**的，所以任何一节
# 都得带上它——窄跑第 56 节要靠它量「签折字」「越纸边」。
b1 = find('BLEED = """(sel)', "BLEED 探针")
b2 = find("for w in (360, 390)", "窄屏探针的收尾")
# §49 与 §53 共用另三段（DL_TRAP / UCTRAP / SEED_BIG），它们是 `BLEED = """(sel)` 之后
# 才定义的。窄跑 §53 时只切 1-head / b1-b2 / start-end 的话，这三段落在切口外面，
# 于是 `NameError: name 'DL_TRAP' is not defined`——那不是 §53 坏了，是窄跑切少了字节
# （实跑第 53 节时撞到的就是这个）。按标记把「共用的三段」整块带上：从 DL_TRAP 那一行
# 切到 §49 的标题之前，块里全是字符串赋值、没有 check、也没有依赖本节任何东西。
c1 = find('DL_TRAP = """(() => {', "§49/§53 共用的三段（DL_TRAP…SEED_BIG）")
c2 = find('print("\\n--- 49. ', "第 49 节（共用三段的收尾边界）")

# 切出来的这一节要自带收尾：不关 context / browser，Playwright 会在进程退出时把
# 「没关干净」当成错误抛出来，或者干脆挂住。主页面名叫 page，其余各节自己开 ctx 的
# 名字（nctx/zctx/rctx/kctx/uctx/c3…）各有各的收尾，这里只兜主那一对。
TAIL = ["\n    ctx.close()\n", "    browser.close()\n"]

SOURCE = "".join(SRC[0:head] + SRC[b1:b2] + SRC[c1:c2] + SRC[start:end] + TAIL)
# 上面那条「来自 …」的切法说明里，`SRC[end:]` 只是为了让收尾之后的**无关尾部**
# 不参与编译（真正的收尾在 TAIL 里）——它不在 SOURCE 里，所以行数会远小于整份文件。
# 别把那行打印当成「切出全量」的证据：`n` 才是。
n = SOURCE.count("check(")
if n < 2:
    print(" FAIL 切出来只含 " + str(n) + " 处 check( —— 这一节没被切进来，报绿是假的")
    sys.exit(1)
print("[只跑第 %s 节] 切出 %d 行 / %d 处 check(，来自 e2e.playwright.py 的 1-%d / %d-%d / %d-%d / %d-%d / 收尾"
      % (SEC, len(SOURCE.splitlines()), n, head, b1 + 1, b2, c1 + 1, c2, start + 1, end))
if SEC != "1":
    print(" 注意：窄跑只跑第 %s 节，它不覆盖 2-%d 与 %d 之后的各节；这个绿不等于全量绿。"
          % (SEC, start, end))
sys.argv[0] = str(JIAN / "test" / "e2e.playwright.py")
exec(compile(SOURCE, "e2e 第 %s 节 only" % SEC, "exec"),
     {"__name__": "__main__", "__file__": str(JIAN / "test" / "e2e.playwright.py")})
