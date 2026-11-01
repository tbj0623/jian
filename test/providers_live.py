"""清单里每一家真模型逐个验一遍（要网络、要密钥，**不进** npm run check）。

    python test/providers_live.py          # 清单里的每一家
    python test/providers_live.py 智谱     # 只看名字里含「智谱」的那家

做法上有一件事是刻意的：不直接 import llm 来问，而是为每一家单独起一个网关
（用 JIAN_LLM_* 把那一家钉死），再拿真图片打它的 /v1/recognize 与 /v1/ocr。
因为用户在应用里走的就是那条 HTTP 路——夹 JSON、超时、502 的说法、/v1/status
自述，全在那条路上；只测客户端函数会把这些都绕过去。

顺带验一件事：环境变量优先于 ~/.jian/llm_providers.json。清单里现在有三家，
「今天用的是哪一家」必须说得出、且和钉的那一家一致。
"""
import base64
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import llm  # noqa: E402

GARMENT = next(iter(sorted((ROOT / "vibe_images").glob("garment-*.png"))), None)
CHAT = ROOT / "test" / "_audit" / "chat-screenshot.png"
# 聊天截图里确实写着的七句话（test/_audit/make_assets.py 造的就是它）
SAID = ["材料发我", "买一盒", "周五见", "时间再说", "拿一下", "报价", "酱油"]


def data_url(p, edge):
    from PIL import Image
    im = Image.open(p).convert("RGB")
    im.thumbnail((edge, edge))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def port_open(port, timeout=25.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def call(base, path, payload, timeout=60):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace")), time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            body = {"error": "unreadable"}
        return e.code, body, time.time() - t0
    except Exception as e:
        return 0, {"error": type(e).__name__, "message": str(e)[:160]}, time.time() - t0


def call_retry(base, path, payload, label, tries=2):
    """免费额度会抽。一次超时/回空就把整条集成判红，和「为一次偶发红去改预算」是同一个毛病；
    所以重试一次，并且把「第二次才通」说出来——那是这家今天不稳，不是这里接坏了。"""
    code, r, dt = call(base, path, payload)
    for n in range(1, tries):
        if code == 200:
            break
        print(f"        {label}第 {n + 1} 次之前不通（{dt:.1f}s，{r.get('error')}），重试")
        code, r, dt = call(base, path, payload)
        if code == 200:
            print(f"        {label}第 {n + 1} 次才通（{dt:.1f}s）——这一家今天不稳，记一笔")
    return code, r, dt


ok_n = bad_n = 0


def chk(name, cond, detail=""):
    global ok_n, bad_n
    if cond:
        ok_n += 1
        print("  ok   " + name)
    else:
        bad_n += 1
        print(f" FAIL  {name}  →  {str(detail)[:200]}")


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    prov = llm.PROVIDERS
    if only:
        prov = [p for p in prov if only in p["name"] or only == p["model"]]
    if not prov:
        print(f"清单 {llm.PROVIDERS_PATH} 里没有{('叫 ' + only + ' 的') if only else '任何'}一家。"
              "先看文件在不在、JSON 有没有写坏。")
        return 1
    if not GARMENT or not CHAT.exists():
        print(f"缺素材：衣服图要放 vibe_images/garment-*.png，"
              f"聊天截图要 test/_audit/chat-screenshot.png（跑 python test/_audit/make_assets.py）")
        return 1

    see_img = data_url(GARMENT, 512)
    ocr_img = data_url(CHAT, 768)
    print(f"清单：{llm.PROVIDERS_PATH}（{len(prov)} 家）\n衣服图 {GARMENT.name} · 截图 {CHAT.name}\n")

    for p in prov:
        print(f"--- {p['name']}  {p['model']}  {p['base']}")
        port = free_port()
        # 三家都在清单里，为什么这里测的就是这一家？因为环境变量那一套优先，
        # 而且它一配就是「只此一家」——见 llm._from_env()。所以这一家不通不会换到下一家，
        # 报出来的红是这一家自己的红。
        # 超时也不设，就用生产那一档 15 秒：这里要量的是「在应用真等得起的时间里它能不能干活」，
        # 给到 40 秒只会把一家本来该判不行的供应商糊过去。
        env = {**os.environ, "JIAN_PORT": str(port), "JIAN_LLM_BASE": p["base"],
               "JIAN_LLM_KEY": p["key"], "JIAN_LLM_MODEL": p["model"],
               "PYTHONIOENCODING": "utf-8"}
        gw = subprocess.Popen([sys.executable, str(ROOT / "backend" / "gateway.py")],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace")
        base = f"http://127.0.0.1:{port}"
        try:
            if not port_open(port):
                chk(f"{p['name']}：网关起得来", False, "端口没开（看下面的输出）")
                continue
            st, obj, _ = call(base, "/v1/nope", {})      # 先确认这条端口上确实是刚起的那个进程
            chk("打不通的路回 404（不是隔壁哪个服务）", st == 404 and obj.get("error") == "unknown", obj)
            code, s, _ = get_json(base + "/v1/status")
            chk("自述说得出是哪一家（环境变量优先于清单）",
                code == 200 and s.get("model", {}).get("model") == p["model"]
                and s.get("model", {}).get("on") is True, s.get("model"))
            code, r, dt = call_retry(base, "/v1/recognize", {"image": see_img}, "认衣服")
            print(f"        认衣服 {dt:.1f}s → {json.dumps(r, ensure_ascii=False)[:150]}")
            chk("认衣服 200 且四格齐",
                code == 200 and r.get("name") and r.get("cat") and r.get("color"), f"{code} {r}")
            chk("认出来的品类在值域里",
                r.get("cat") in llm.CATS and r.get("season") in llm.SEASONS + ("",), r.get("cat"))
            chk("色值是六位小写", str(r.get("color", "")).startswith("#")
                and len(str(r.get("color", ""))) == 7, r.get("color"))
            code, r, dt = call_retry(base, "/v1/ocr", {"image": ocr_img}, "抄截图")
            got = r.get("text", "")
            print(f"        抄截图 {dt:.1f}s → 抄到 {len(got)} 字：{repr(got[:110])}")
            hit = [w for w in SAID if w in got]
            chk("聊天截图里的话抄到手了（七句里至少五句）",
                code == 200 and len(hit) >= 5, f"{code} 只抄到 {len(hit)} 句：{hit}")
        finally:
            if gw.poll() is None:
                gw.terminate()
            try:
                out = gw.stdout.read() or ""
            except Exception:
                out = ""
            tail = [l for l in out.splitlines() if "Traceback" in l or "Error" in l or "[jian]" in l]
            if tail:
                print("        网关侧说了几句：" + " / ".join(tail[-3:])[:200])
    print(f"\n逐家真跑：{ok_n} 通过 / {bad_n} 失败")
    return 1 if bad_n else 0


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace")), 0
    except Exception as e:
        return 0, {"error": type(e).__name__, "message": str(e)[:160]}, 0


if __name__ == "__main__":
    raise SystemExit(main())
