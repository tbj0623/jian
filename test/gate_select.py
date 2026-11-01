"""认证之前先问一句：这次 --only 的关键词到底挑中了几条？
   `gate_selfcheck.py --only 关键词` 是**子串匹配**，少一个字（甚至少一个空格）就安静地少跑一条，
   跑完的「N/总数」如果没人看，就等于「其中一条从来没被证过」——第 37 轮就是这么差点漏掉的。
   用法：python test/gate_select.py 关键词 [关键词…]   （不带关键词 = 全跑）
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gate", str(ROOT / "test" / "gate_selfcheck.py"))
mod = importlib.util.module_from_spec(spec)
kws = sys.argv[1:]
sys.argv = ["gate_selfcheck.py"] + kws      # selected_mutations() 读的就是 sys.argv
spec.loader.exec_module(mod)
picked = mod.selected_mutations()
print("PICKED %d / %d" % (len(picked), len(mod.MUTATIONS)))
for e in picked:
    print("  -", mod.parts(e)[0])
missing = [k for k in kws if not any(k in mod.parts(e)[0] for e in mod.MUTATIONS)]
for k in missing:
    print("!! 没有任何一条注入的名字里含「%s」——这个词是白给的" % k)
sys.exit(1 if missing else 0)
