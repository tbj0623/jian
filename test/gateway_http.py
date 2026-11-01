# 网关的 HTTP 外壳：判定层抛异常时必须回 500，而不是把连接掀掉。
# api.js 对「连接中断」和「!res.ok」都是静默回落本地引擎，用户在界面上看不出任何异常；
# 只有回一个像样的 500，控制台里才留得下线索，「已经接了网关」的假象才可能被发现的。
#
# 运行：python test/gateway_http.py
import json
import pathlib
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import gateway as g  # noqa: E402

pass_n = fail_n = 0


def ok(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"  ok   {name}")
    else:
        fail_n += 1
        # detail 要能拼进字符串：传 dict / list 时这里会直接抛 TypeError，
        # 于是那两条断言红的时候不报名字、只留一个 traceback——正是这套守门最忌的「看不出炸在哪」。
        print(f" FAIL  {name}{('  → ' + str(detail)) if detail else ''}")


def post(path, raw: bytes):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=raw,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))
    except (ConnectionError, OSError) as e:
        # 连接被掀掉：这正是 do_POST 没兜住异常时的症状，报成一次可读的失败而不是 traceback
        return 0, {"error": f"connection-reset: {e}"}


def get(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (ConnectionError, OSError):
        return 0, b""


def main():
    global PORT
    s = ThreadingHTTPServer(("127.0.0.1", 0), g.Handler)
    PORT = s.server_address[1]
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        run()
    finally:
        s.shutdown()
        s.server_close()
    print(f"\n网关 HTTP：{pass_n} 通过 / {fail_n} 失败")
    return 1 if fail_n else 0


def run():
    # --- 曾经能把连接掀掉的两处输入 ---
    code, obj = post("/v1/complete", json.dumps(
        {"task": "yan", "text": "记得2月31日前把年报交了"}, ensure_ascii=False).encode())
    ok("2月31日不再打挂网关，钳到月末",
       code == 200 and obj["待办"][0]["when"]["text"] == "2月28日", f"{code} {obj}")

    code, obj = post("/v1/complete", json.dumps(
        {"task": "yan", "text": "12月32号再说一遍"}, ensure_ascii=False).encode())
    ok("12月32号不再打挂网关，当作没时间",
       code == 200 and obj["还没说清"][0]["when"] is None, f"{code} {obj}")

    code, obj = post("/v1/see", json.dumps(
        {"task": "yi", "item": {"name": "x", "cat": "上衣", "color": "#gggggg"},
         "wardrobe": [{"name": "a", "cat": "上衣", "color": "#ffffff"}]}, ensure_ascii=False).encode())
    ok("非 16 进制色值不再打挂网关", code == 200 and obj["stamp"] in ("先别", "再想想", "宜入"), f"{code} {obj}")

    # --- 异常兜底：判定层真炸时，要 500 + JSON，不能连接被掐 ---
    real = g.yi
    g.yi = lambda body: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        code, obj = post("/v1/see", json.dumps({"task": "yi", "item": {}, "wardrobe": []}).encode())
        ok("判定层异常回 500 且带 JSON", code == 500 and "RuntimeError" in obj.get("error", ""), f"{code} {obj}")
    finally:
        g.yi = real
    code, obj = post("/v1/see", json.dumps({"task": "yi", "item": {"name": "x", "cat": "上衣", "color": "#ffffff"},
                                           "wardrobe": []}, ensure_ascii=False).encode())
    # 这条要验的是「炸过一次之后服务还能用」，不是某一句文案——
    # 以前它顺手钉了 quote.startswith("柜里还太少")，第二十轮改空柜文案就把它带红了。
    # 文案有 consistency 两端逐字比对守着，这里不该再钉一遍。
    ok("炸过一次之后服务还能用",
       code == 200 and obj["stamp"] in ("先别", "再想想", "宜入") and bool(obj["quote"]), f"{code} {obj}")

    # --- 请求体边界 ---
    code, obj = post("/v1/complete", b"{not json")
    ok("坏 JSON 回 400", code == 400 and obj.get("error") == "invalid json", f"{code} {obj}")
    code, obj = post("/v1/complete", b"[1,2]")
    ok("数组体回 400 而不是 500", code == 400 and obj.get("error") == "body must be an object", f"{code} {obj}")
    code, obj = post("/v1/complete", b"null")
    ok("null 体回 400", code == 400, f"{code} {obj}")
    code, obj = post("/v1/nope", b'{"task":"yi"}')
    ok("未知路径回 404", code == 404 and obj.get("error") == "unknown", f"{code} {obj}")
    code, obj = post("/v1/complete", b'{"task":"whatever"}')
    # 这一条以前钉的是「未知 task 悄悄当味笺算了」（回 200）。那是个会藏错的行为：
    # 客户端把 task 写成 "yab" 也能拿到一个 200 的味笺结果，界面上永远看不出接线错了。
    # 现在缺省（老客户端不填 task）仍按味笺走，填了却不认识的回 400。
    ok("complete 上未知 task 回 400（不再悄悄当味笺）",
       code == 400 and obj.get("error") == "badtask", f"{code} {obj}")
    code, obj = post("/v1/complete", b'{}')
    ok("不填 task 仍按味笺走（老客户端不断）", code == 200 and "safe" in obj, f"{code} {obj}")

    # --- 正常路径 ---
    code, obj = post("/v1/complete", json.dumps(
        {"task": "wei", "menu": "米饭\n小炒肉", "people": [{"name": "我", "chips": ["猪肉"]}]},
        ensure_ascii=False).encode())
    ok("wei 正常返回", code == 200 and obj["boom"][0]["dish"] == "小炒肉", f"{code} {obj}")
    code, obj = post("/v1/hear", b'{"task":"hear"}')
    ok("hear 仍提示转文字", code == 200 and obj.get("needText") is True, f"{code} {obj}")

    # --- 模型那两条路：拿假回复验「夹得住」，不连真供应商 ---
    # 真跑放在 test/gateway_live.py（要密钥、要网络，不能进 npm run check）；
    # 这里守的是「模型不守格式」那一类：围栏 JSON、把枚举原文抄回来、色值乱给、编号引号。
    import llm
    IMG = "data:image/jpeg;base64," + "A" * 4000
    real = (llm.chat, llm.BASE, llm.KEY, llm.MODEL)
    def stub(text):
        llm.chat = lambda *a, **k: text
    llm.BASE, llm.KEY, llm.MODEL = "http://127.0.0.1:1/v1", "stub-key", "stub-model"
    try:
        stub("```json" + chr(10) + '{"name":"针织开衫","cat":"外套","color":"#C9B89A","season":"春秋|冬|四季"}' + chr(10) + "```")
        code, obj = post("/v1/recognize", json.dumps({"image": IMG}).encode())
        ok("认衣服：``` 围栏里的 JSON 也接得住",
           code == 200 and obj.get("name") == "针织开衫", f"{code} {obj}")
        ok("模型把枚举原文整段抄回来，季节夹进值域",
           obj.get("season") in ("夏", "春秋", "冬", "四季", ""), obj.get("season"))
        ok("色值统一成小写六位", obj.get("color") == "#c9b89a", obj.get("color"))
        ok("回的是 source=model 与模型名（出处要说得清）",
           obj.get("source") == "model" and obj.get("model") == "stub-model", obj)
        stub("我看这是一件衣服，颜色大概是米色吧")
        code, obj = post("/v1/recognize", json.dumps({"image": IMG}).encode())
        ok("回的不是 JSON → 502 并说得出原因（不是 200 空壳）",
           code == 502 and obj.get("error") == "notjson", f"{code} {obj}")
        stub('{"name":"包","cat":"帽子","color":"notacolor","season":"夏"}')
        code, obj = post("/v1/recognize", json.dumps({"image": IMG}).encode())
        ok("色值不可用时不硬给（让前端回落本机量的色）",
           code == 502 and obj.get("error") == "nocolor", f"{code} {obj}")
        # 模型认不出时不会说「认不出」，它回「无」——照抄进柜子里那件衣服从此就叫「无」。
        # 实测 glm-4v-flash 对一张纯色块照片回的就是 {"name":"无"}，而品类认得挺准。
        stub('{"name":"无","cat":"外套","color":"#c9b89a","season":"春秋"}')
        code, obj = post("/v1/recognize", json.dumps({"image": IMG}).encode())
        ok("模型说「无」不当名字用（宁可留着用户自己起的那个）",
           code == 200 and obj.get("name") == "" and obj.get("cat") == "外套", f"{code} {obj}")
        stub('{"name":"未知","cat":"鞋","color":"#c9b89a","season":"四季"}')
        code, obj = post("/v1/recognize", json.dumps({"image": IMG}).encode())
        ok("「未知」这类占位话一样拦掉，其余字段照收",
           obj.get("name") == "" and obj.get("cat") == "鞋" and obj.get("season") == "四季", obj)
        Q = chr(34)   # 一行里不想再放转义引号：上一版就是这么把字符串写断的
        stub("1. " + Q + "明天开会" + Q + chr(10) + "2. " + Q + "记得买药" + Q + chr(10) + "- 周五见")
        code, obj = post("/v1/ocr", json.dumps({"image": IMG}).encode())
        ok("抄图：编号与引号被清掉，行序不变",
           code == 200 and obj.get("text", "").startswith("明天开会")
           and obj["text"].splitlines()[1] == "记得买药", f"{code} {obj}")
        code, obj = post("/v1/recognize", json.dumps({}).encode())
        ok("没图回 400 noimage", code == 400 and obj.get("error") == "noimage", obj)
        code, obj = post("/v1/recognize", json.dumps({"image": "data:image/jpeg;base64,QQ=="}).encode())
        ok("小得不像照片的图拒掉，并且说「太小」",
           code == 400 and obj.get("error") == "tinyimage", obj)
    finally:
        llm.chat, llm.BASE, llm.KEY, llm.MODEL = real

    # --- 「没配模型」这一档必须由测试自己搭出来 ---
    # 这台机器上现在常驻着 ~/.jian/llm_providers.json。以前下面两句是白捡的环境状态：
    # 配上之后它们不是变红，而是拿真密钥去打供应商（实测真的打出去了，
    # 上游回 400「图片输入格式/解析错误」）。这套守门的约定是不依赖网络与密钥
    # 也能跑完，所以前置条件得自己造，不能指望「这台机器恰好没配」。
    keep = (llm.PROVIDERS, llm.BASE, llm.KEY, llm.MODEL, llm.NAME, llm._active, llm.FAILOVER)
    llm.PROVIDERS, llm.BASE, llm.KEY, llm.MODEL = [], "", "", ""
    llm.NAME, llm._active, llm.FAILOVER = "", -1, ""
    try:
        code, raw = get("/v1/status")
        obj = json.loads(raw.decode("utf-8")) if raw else {}
        ok("没配模型时 /v1/status 说 recognize=false",
           code == 200 and obj["model"]["on"] is False and obj["tasks"]["recognize"] is False,
           f"{code} {obj}")
        code, obj = post("/v1/recognize", json.dumps({"image": IMG}).encode())
        ok("没配模型时识图回 502 而不是 200 空壳",
           code == 502 and obj.get("error") == "unconfigured", f"{code} {obj}")
    finally:
        llm.PROVIDERS, llm.BASE, llm.KEY, llm.MODEL, llm.NAME, llm._active, llm.FAILOVER = keep

    # --- 一家不行要换下一家 ---
    # 免费额度会打满、某一家会抽风。这一条不灵，「今天这家不行」就变成了全 App 回落本地。
    # 两家都指向没人听的端口：连不上要换，绕完一圈把最后一个错交出去，不许无限换。
    keep = (llm.PROVIDERS, llm.BASE, llm.KEY, llm.MODEL, llm.NAME, llm._active, llm.FAILOVER)
    llm.PROVIDERS = [{"name": "第一家", "base": "http://127.0.0.1:1/v1", "key": "k", "model": "m1"},
                     {"name": "第二家", "base": "http://127.0.0.1:2/v1", "key": "k", "model": "m2"}]
    llm._apply(0)
    llm.FAILOVER = ""
    try:
        try:
            llm.chat([{"role": "user", "content": "x"}])
            ok("两家都不通时仍然把错抛出来", False, "居然没抛错")
        except llm.LlmError as e:
            ok("第一家连不上会自动换到第二家",
               llm.NAME == "第二家" and e.code == "unreachable", f"停在 {llm.NAME}，{e.code}")
            ok("换过家的原因留得下来（/v1/status 说得出今天为什么换了）",
               "第一家" in llm.FAILOVER, llm.FAILOVER)
    finally:
        llm.PROVIDERS, llm.BASE, llm.KEY, llm.MODEL, llm.NAME, llm._active, llm.FAILOVER = keep

    # --- 静态目录：.git 与 keystore 不该被读走 ---
    st, _ = get("/.git/config")
    ok("GET /.git/config 被拒", st == 404, f"{st}")
    st, _ = get("/.gitignore")
    ok("GET /.gitignore 被拒", st == 404, f"{st}")
    st, _ = get("/android/app/jian-release.keystore")
    ok("GET keystore 被拒", st == 404, f"{st}")
    # 模型清单默认在 ~/.jian/（仓库外）。但仓库根目录就是静态目录，所以「有人把它放进了
    # 仓库树」这一层也要拦得住。只查 404 不够——文件本来不存在时谁都答 404，
    # deny 名单里那一条被摘掉也没人发现；所以要真造一张金丝雀进去，看它出不出得来。
    canary = ROOT / "backend" / "llm_providers.json"
    made = not canary.exists()
    if made:
        canary.write_text('{"providers": [{"key": "CANARY-DO-NOT-SERVE"}]}', encoding="utf-8")
    try:
        disk = canary.read_bytes()
        st, body = get("/backend/llm_providers.json")
        ok("落在仓库树里的模型清单发不出去（404，正文里也没有它的内容）",
           st == 404 and disk not in body, f"{st} 正文含内容={disk in body}")
    finally:
        if made:
            canary.unlink(missing_ok=True)
    st, body = get("/index.html")
    ok("H5 仍然能打开", st == 200 and b"<html" in body.lower()[:200], f"{st}")
    st, _ = get("/styles.css")
    ok("样式仍能打开", st == 200, f"{st}")

    # --- 安卓壳到底把不把这条路发出去 ---
    # 第 17 轮把识图/抄截图接进了 H5，而用户填的是 http://局域网IP:8787。
    # 同一台模拟器上把两道闸逐个关掉量（每一格都重新 cap:sync，别让 APK 里那份旧配置
    # 替你说谎——第一版就是这么差点得出反结论）：
    #     混合内容开 + NSC 关 → 连不上；混合内容关 + NSC 开 → 连不上；两道都开 → 在线。
    # 所以两道都是承重的。usesCleartextTraffic 那一行反而多余：有 networkSecurityConfig
    # 在它就被忽略，留着只会让上架审查多问一句。
    # 这几样都是配置文件里的一个布尔，改回去悄无声息，所以钉成守门而不是写进文档。
    cfg = json.loads((ROOT / "capacitor.config.json").read_text(encoding="utf-8"))
    ok("壳允许混合内容（实测一关，https 的壳就发不出 http 的网关请求）",
       cfg.get("android", {}).get("allowMixedContent") is True, cfg.get("android"))
    man = (ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    nsc = (ROOT / "android" / "app" / "src" / "main" / "res" / "xml" /
           "network_security_config.xml")
    ok("manifest 挂上了网络安全配置", "networkSecurityConfig=" in man, "")
    ok("manifest 里没有那个被 NSC 盖掉的 usesCleartextTraffic", "usesCleartextTraffic" not in man, "")
    ok("网络安全配置放行明文（targetSdk 28+ 默认禁，网关是 http）",
       nsc.exists() and 'cleartextTrafficPermitted="true"' in nsc.read_text(encoding="utf-8"), "")
    # 反方向的命门：局域网要能连，但默认不该替用户把端口开给整条街。
    ok("网关默认只听回环（开给局域网得用户自己说）", g.HOST == "127.0.0.1", g.HOST)

    # --- 密钥不能被发出去：整套架构的前提是「密钥只在网关，APK 发给陌生人」 ---
    # 光靠「大家都记得别粘」不算守门。按形状扫一遍要发的东西（源码 + 两份构建产物），
    # 再把清单里那几枚真密钥逐个对一遍。
    def shipped():
        out = []
        for pat in ("*.js", "index.html", "www/**/*.*", "android/app/src/main/assets/public/**/*.*"):
            for p in ROOT.glob(pat):
                if p.is_file() and p.suffix.lower() in (".js", ".html", ".json", ".css"):
                    out.append(p)
        return sorted(set(out))

    KEYISH = re.compile(r"sk-[A-Za-z0-9_\-]{12,}|[A-Za-z0-9]{12,32}\.[A-Za-z0-9]{12,32}")
    files = shipped()
    shape = [f"{f.relative_to(ROOT)} 里 {m.group()[:8]}…" for f in files
             for m in KEYISH.finditer(f.read_text(encoding="utf-8", errors="replace"))]
    ok("要发的 %d 个文件里没有密钥形状的内容" % len(files), shape == [], shape)
    try:
        keys = [str(p.get("key") or "") for p in
                json.loads(llm.PROVIDERS_PATH.read_text(encoding="utf-8")).get("providers", [])]
        keys = [k for k in keys if k]
    except Exception:
        keys = []
        print("   注：%s 不在，这一条退化成只按形状扫（换台没配密钥的机器上跑是正常的）"
              % llm.PROVIDERS_PATH)
    hit = sorted({str(f.relative_to(ROOT)) for f in files
                  for k in keys if k in f.read_text(encoding="utf-8", errors="replace")})
    ok("清单里 %d 枚真密钥一枚都不在要发的东西里" % len(keys), hit == [], hit)


if __name__ == "__main__":
    raise SystemExit(main())
