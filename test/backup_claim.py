# 「数据只留在你设备上」这句话，和清单里的开关，必须同真同假。
#
# 为什么单独一道门：这是**跨产物**的陈述——一边是 `AndroidManifest.xml` 里一个布尔，
# 另一边是 `docs/上架/商店材料.md` 里给审查员和用户看的隐私政策正文。两边谁都不会去读谁，
# 而 Play 的数据安全表要按其中一边的答案勾。以前 `allowBackup="true"`（且没有
# `dataExtractionRules`）时整份应用数据会进用户的 Google 云备份、卸载重装还会回来，
# 政策里却写着「卸载应用即随之删除」——所有测试全绿，因为没有任何一道门把两句话对起来。
#
# 运行：python test/backup_claim.py
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAN = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
DOC = ROOT / "docs" / "上架" / "商店材料.md"

checks = []


def check(name, ok, got=""):
    checks.append((ok, name, got))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else f"  ->  {got}"))


man = MAN.read_text(encoding="utf-8")
doc = DOC.read_text(encoding="utf-8")

# 这道门是按正则读清单的，所以它自己看不见「清单根本不是合法 XML」。
# 那一类错要等 90 秒的 gradle 才炸（真事：把注释写进 <application> 的属性中间，
# 属性之间的注释是非法的，manifestmerger 只报一句 Error parsing）。0.2 秒先挡一下。
try:
    ET.fromstring(man)
    check("清单是合法 XML（注释不能写在标签的属性中间）", True)
except ET.ParseError as e:
    check("清单是合法 XML（注释不能写在标签的属性中间）", False, f"{e.lineno}:{e.offset}: {e.msg}")

m = re.search(r'android:allowBackup="(true|false)"', man)
check("清单里 allowBackup 是显式写的（不是靠默认）", bool(m), m and m.group(0) or "找不到这一行")
backup_on = bool(m) and m.group(1) == "true"
# 默认行为算不算「上云」也要看有没有自定义规则；两边都缺省 = 整份数据进云备份
has_rules = "dataExtractionRules" in man or "fullBackupContent" in man
check("allowBackup=true 时必须自定义备份规则（否则等于整份数据上云）",
      (not backup_on) or has_rules, "true 且没有任何 dataExtractionRules / fullBackupContent")

# 政策里那三句「只在你的设备上」的陈述：它们各自对应一个可核实的开关
claims = ["只保存在你自己设备的私有存储里", "卸载应用即随之删除", "不上传任何东西"]
said = [c for c in claims if c in doc]
check("政策确实在做这些陈述（门不能对着空文档自证）", len(said) >= 2, f"只找到 {len(said)} 句")
check("政策说「卸载即删除」时，清单不许开自动备份",
      (not backup_on) or "卸载应用即随之删除" not in doc,
      "allowBackup=true，而政策写着卸载即删除")
check("政策说「不上传任何东西」时，也不许把数据交给云备份",
      (not backup_on) or "不上传任何东西" not in doc,
      "allowBackup=true，而政策写着不上传")
# 反过来：真开了云备份，就得在数据安全那一节明说，不能只靠政策那句含糊话
if backup_on:
    check("开了自动备份就要在合规那一节明说会进云备份",
          "备份到云端" in doc or "云备份" in doc, "清单开着，文档里找不到这句")
else:
    check("关掉自动备份后，文档里不许还留着「数据会被备份到云端」这种指导勾选的话",
          "要在数据安全表里如实勾选" not in doc, "文档还在教人勾「会备份到云端」")

bad = sum(1 for ok, _, _ in checks if not ok)
print(f"\n结果：{len(checks) - bad} 通过 / {bad} 失败")
sys.exit(1 if bad else 0)
