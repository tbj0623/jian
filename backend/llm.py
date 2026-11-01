"""笺 · 网关的模型客户端（只在服务端跑，密钥不进应用包）

三件事是这里的全部难点，都是实测出来的：
1. **模型不守格式**。它会回 ```json 包裹的块、会在字段里吐回提示中的枚举原文
   （实测把 season 写成 "春秋|冬|四季"）、会给非六位色值。所以每一格都要夹。
2. **reasoning 模型会「想完就断」**。实测 glm-4.5v 与 agnes-2.5-flash 在 max_tokens=260 时
   content 是空串、finish_reason=length（思考占满了预算）。所以预算给足，并且
   content 空但 reasoning 里有 JSON 时，从 reasoning 里捞一次。
3. **超时不等于失败**。应用侧 20 秒就回落本地引擎，所以这里默认 15 秒，并且把
   「网关没配模型」「模型超时」「回的东西不能用」分成三种说法，界面上才说得出为什么回落。

密钥有两种来路，按优先级：
1. 环境变量 `JIAN_LLM_BASE` / `JIAN_LLM_KEY` / `JIAN_LLM_MODEL`（配了就以它为准，只此一家）。
2. `~/.jian/llm_providers.json`（或 `JIAN_PROVIDERS` 指过去），按数组顺序试，
   某一家超时/连不上/回空就自动换下一家。**不放仓库**：backend/gateway.py 把仓库
   根目录当静态目录发，写进仓库树的密钥能被 `http://网关/路径` 直接下载走。
   `JIAN_LLM_TIMEOUT` 秒，默认 15。

形状（密钥别贴进 issue）：
    {"providers": [{"name": "智谱", "model": "glm-4v-flash",
                    "base": "https://open.bigmodel.cn/api/paas/v4", "key": "…"}, …]}
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = float(os.environ.get("JIAN_LLM_TIMEOUT", "15"))
PROVIDERS_PATH = pathlib.Path(os.environ.get("JIAN_PROVIDERS")
                              or (pathlib.Path.home() / ".jian" / "llm_providers.json"))
# 环境变量那一套只在进模块时读一次：下面 _apply() 会反复改写 BASE/KEY/MODEL，
# 用实时的全局值判断「是不是只配了环境这一家」会在换到第二家之后自己骗自己。
_ENV = {"base": os.environ.get("JIAN_LLM_BASE", "").rstrip("/"),
        "key": os.environ.get("JIAN_LLM_KEY", ""),
        "model": os.environ.get("JIAN_LLM_MODEL", "")}


def _from_env():
    return [{**_ENV, "name": _ENV["model"]}] if all(_ENV.values()) else []


def _read_file():
    """读不出来要说得出为什么，不能静默当成「没配模型」——
    那正好是第 16 轮清掉的那类假账：界面上写「网关没配模型」，其实是文件里少个逗号。"""
    try:
        doc = json.loads(PROVIDERS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:
        print("[jian] 模型清单读不出来（%s）：%s" % (PROVIDERS_PATH, e), file=sys.stderr)
        return []
    out = []
    for p in (doc.get("providers") or []):
        if not isinstance(p, dict):
            continue
        base = str(p.get("base") or "").rstrip("/")
        key, model = str(p.get("key") or ""), str(p.get("model") or "")
        if base and key and model:
            out.append({"name": str(p.get("name") or model), "base": base,
                        "key": key, "model": model})
    return out


PROVIDERS = _from_env() or _read_file()
NAME = ""
BASE = KEY = MODEL = ""
_active = -1


def _apply(i):
    """把第 i 家设为当前。_post() 读的就是这三个全局量，测试也直接改它们。"""
    global BASE, KEY, MODEL, NAME, _active
    p = PROVIDERS[i]
    BASE, KEY, MODEL, NAME, _active = p["base"], p["key"], p["model"], p["name"], i


if PROVIDERS:
    _apply(0)

CATS = ("上衣", "裤装", "裙装", "外套", "鞋", "包")
SEASONS = ("夏", "春秋", "冬", "四季")

# 换一家还有意义的错误：这一家不行不代表下一家不行。
# 反过来，badbase / unconfigured / notjson / nocolor 是要人改东西的，
# 拿它们去换家只会把三个家一起撞一遍、还把手上的错误盖掉。
FAILOVER_RE = re.compile(r"^(timeout|unreachable|empty|http408|http429|http5\d\d)$")
FAILOVER = ""        # 最近一次自动换家的原因，/v1/status 带回去，界面上说得出「为什么今天换了一家」


class LlmError(Exception):
    """带一个 code，界面上要说得出是哪一种不行。"""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def configured() -> bool:
    return bool(BASE and KEY and MODEL)


def _check_base():
    """地址里混进非 ASCII 是真实会发生的事：用户把「（不确定）」这种备注和 URL 一起粘进来，
    urllib 会抛一个看不懂的 UnicodeEncodeError。这里提前拦住，说人话。"""
    if not BASE:
        raise LlmError("unconfigured", "网关没配模型地址")
    try:
        BASE.encode("ascii")
    except UnicodeEncodeError:
        bad = "".join(c for c in BASE if ord(c) > 127)
        raise LlmError("badbase", "模型地址里有中文（%s）——多半是把备注一起粘进来了" % bad)
    if not re.match(r"^https?://", BASE):
        raise LlmError("badbase", "模型地址要以 http:// 或 https:// 开头")


def status() -> dict:
    """给 /v1/status 用：说得出配没配、现在用的是哪一家、后面还排着几家（不回密钥）。"""
    return {"on": configured(), "name": NAME, "base": BASE, "model": MODEL,
            "timeoutMs": int(TIMEOUT * 1000), "count": len(PROVIDERS),
            "rest": [p["name"] for i, p in enumerate(PROVIDERS) if i != _active],
            "failedOver": FAILOVER}


def _extract_json(text: str):
    """从一段可能带 ```json 围栏、前后有废话的回复里抠出第一个 JSON 对象。"""
    if not text:
        return None
    t = text.strip()
    f = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if f:
        t = f.group(1).strip()
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except Exception:
            return None
    return None


def _post(payload) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE.rstrip("/") + "/chat/completions", data=body, method="POST")
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # 带一小段上游正文出来：只说「模型 400」等于没说。
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:220]
        except Exception:
            pass
        err = LlmError("http%d" % e.code, "模型 %d：%s" % (e.code, detail or "无正文"))
        err.detail = detail
        raise err
    except urllib.error.URLError as e:
        raise LlmError("unreachable", "模型地址连不上：" + str(getattr(e, "reason", e))[:80])
    except TimeoutError:
        raise LlmError("timeout", "模型超时（%d 秒）" % int(TIMEOUT * 1000))


def chat(messages, max_tokens: int = 900, temperature: float = 0.0) -> str:
    """一次对话，按清单顺序试到有人答得上来。返回 content 文本，出错抛 LlmError(code)。

    免费额度会打满、某一家会抽风（实测同一段 OCR 快 2.6 秒、慢 14 秒），
    所以「这一家今天不行」不该让整个 App 悄悄回落到本地规则。
    换过去之后就停在这一家，不每次回头重试第一家（那等于每单都先撞一次墙）；
    重启网关复位。"""
    global FAILOVER
    if not configured():
        raise LlmError("unconfigured", "网关没配模型")
    _check_base()
    err, first = None, _active
    for _ in range(len(PROVIDERS) or 1):
        try:
            return _chat_once(messages, max_tokens, temperature)
        except LlmError as e:
            err = e
            nxt = (_active + 1) % len(PROVIDERS) if len(PROVIDERS) > 1 else _active
            # nxt == first：这一圈全都试过了，把最后一个错交出去，别绕回去无限换
            if not FAILOVER_RE.match(e.code) or nxt == _active or nxt == first:
                raise
            print("[jian] %s 不行（%s），换 %s" % (NAME or MODEL, e.code, PROVIDERS[nxt]["name"]),
                  file=sys.stderr)
            FAILOVER = "%s：%s" % (NAME or MODEL, e)
            _apply(nxt)
    raise err or LlmError("unconfigured", "网关没配模型")


def _chat_once(messages, max_tokens: int = 900, temperature: float = 0.0) -> str:
    """只问当前这一家，返回 content；出错抛 LlmError(code)。

    上游嫌预算大（实测 glm-4v-flash 对 max_tokens>1024 直接回 400）就换小一号再试一次：
    这种能自愈的事不该丢给用户。"""
    if not configured():
        raise LlmError("unconfigured", "网关没配模型")
    _check_base()
    t0, ask = time.time(), max_tokens
    while True:
        try:
            # 不要再发 "thinking": {"type": "disabled"}。它当初是给 glm-4.5v 加的，
            # 实测（同一张衣服图，每家两次）：Agnes 两家收到它反而更慢——0.9s → 5.8~7.7s——
            # 而且并没有真的关掉思考（reasoning_content 照样满），六次里还出了一次空回复、
            # 一次「color 前面少一个引号」的坏 JSON。不发才是 6/6 干净、0.9~5.3 秒。
            # 思考型模型真把预算花在 thinking 上时，下面的 _content_of 会从 reasoning 里捞。
            obj = _post({"model": MODEL, "messages": messages, "max_tokens": ask,
                         "temperature": temperature})
            break
        except LlmError as e:
            smaller = min(ask, 1024) if ask > 1024 else 512
            if (e.code == "http400" and smaller < ask
                    and re.search(r"token|length|长度", getattr(e, "detail", "") or "", re.I)):
                ask = smaller
                continue
            raise
    content = _content_of(obj)
    if not content:
        raise LlmError("empty", "模型回空了（用了 %d 秒、预算 %d token）" % (round(time.time() - t0), ask))
    return content


def _content_of(obj) -> str:
    """模型的回话。content 是空的就再去 reasoning 里捞一次——实测 glm-4.5v 与
    agnes-2.5-flash 会把整段预算花在思考上，答案其实写在 reasoning_content 里。"""
    ch = (obj.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = (msg.get("content") or "").strip()
    if content:
        return content
    for alt in (msg.get("reasoning_content"), msg.get("reasoning"), ch.get("text")):
        got = _first_jsonish(str(alt or ""))
        if got:
            return got
    return ""


def _first_jsonish(text: str) -> str:
    m = re.search(r"\{.*\}", text or "", re.S)
    return m.group(0) if m else ""


# ---------- 衣笺：照片 → 这件是什么 ----------

SEE_PROMPT = (
    "这是一张衣服的照片。只看衣服本身，忽略背景、衣架、人。\n"
    "只输出一个 JSON，不要解释、不要代码围栏，字段与取值范围严格如下：\n"
    '{"name":"八个字以内的中文叫法（认不出来就留空字符串，不要填「无」「未知」这类占位话），'
    '"cat":"' + "|".join(CATS) + '"（六选一，只能填其中一个词，不要把竖线也填进去）,'
    '"color":"#rrggbb 这件衣服本身的主色，不要背景色",'
    '"season":"' + "|".join(SEASONS) + '"（四选一，同样不要把竖线填进去）}'
)


def _hex(v) -> str:
    s = str(v or "").strip().lower()
    m = re.search(r"#?([0-9a-f]{6})\b", s)
    if m:
        return "#" + m.group(1)
    m = re.search(r"#?([0-9a-f]{3})\b", s)
    return "#" + m.group(1) * 2 if m else ""


def _one_of(v, options):
    """模型常把提示里的枚举原文整段抄回来（实测 season 收到过 "春秋|冬|四季"）。
    所以先整词比，再退一步在串里找第一个出现的合法值。"""
    s = str(v or "").strip()
    if s in options:
        return s
    hits = [(s.index(o), o) for o in options if o and o in s]
    return min(hits)[1] if hits else ""


# 模型认不出的时候不会说「认不出」，它会回「无」「未知」「一件衣服」。
# 这种话照抄进柜子里，那件衣服就叫「无」——比留着用户自己的文件名还差。
# 实测 glm-4v-flash 对一张纯色块的照片回的就是 {"name":"无",…}，而且品类照样认对。
NO_NAME_RE = re.compile(r"^(无|未知|暂无|没有|无相关|不清楚|不确定|无法识别|不可识别|"
                        r"识别不了|n/?a|none|null|unknown)$", re.I)


def _name(v) -> str:
    s = str(v or "").strip()[:12]
    if len(s) < 2 or NO_NAME_RE.match(s):
        return ""
    return s


def see(image_data_url: str) -> dict:
    """照片 → {name, cat, color, season}。字段夹到值域，夹不出就报错让上层回落本地。"""
    if not image_data_url:
        raise LlmError("noimage", "没收到图片")
    txt = chat([{"role": "user", "content": [
        {"type": "text", "text": SEE_PROMPT},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]}], max_tokens=700)
    obj = _extract_json(txt)
    if not isinstance(obj, dict):
        raise LlmError("notjson", "回的不是 JSON")
    out = {"name": _name(obj.get("name")),
           "cat": _one_of(obj.get("cat"), CATS),
           "color": _hex(obj.get("color")),
           "season": _one_of(obj.get("season"), SEASONS)}
    out["ok"] = bool(out["color"])
    if not out["ok"]:
        raise LlmError("nocolor", "没给出可用的主色")
    return out


# ---------- 言笺：聊天截图 → 文字 ----------

OCR_PROMPT = ("这是聊天记录截图。按**从上到下的实际顺序**逐条抄出每一条消息的文字，"
              "一条一行，不要编号、不要引号、不要翻译或补全，也不要解释。"
              "读不到的字用「〇」代替。")


def ocr(image_data_url: str) -> str:
    if not image_data_url:
        raise LlmError("noimage", "没收到图片")
    txt = chat([{"role": "user", "content": [
        {"type": "text", "text": OCR_PROMPT},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]}], max_tokens=1500)
    lines = [l.strip() for l in re.split(r"[\r\n]+", txt) if l.strip()]
    # 模型爱写「1. 」前缀和成对的引号，抄进聊天框会污染后面的抽取
    clean = []
    for l in lines:
        l = re.sub(r"^\s*[\-*·•]\s*", "", l)
        l = re.sub(r"^\s*\d+[.、)]\s*", "", l)
        l = l.strip().strip('"“”\'')
        if l:
            clean.append(l[:200])
    return "\n".join(clean[:80])
