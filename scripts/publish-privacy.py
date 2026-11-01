# 把 docs/上架/privacy/index.html 发成公开网页（GitHub Pages），并且能**验**已发布的那一份就是这一份。
#
# 为什么走 Contents API 而不是 git push：这台机器上 GitHub 被本地加速器接管
# （hosts 把 github.com 指到 127.0.0.1，证书是它自己签的），`gh` 认，`curl` 不认。
# 少一条要修的传输链路就少一处会假失败的地方。
#
# 跑法：
#   py scripts/publish-privacy.py           # 发布 / 更新
#   py scripts/publish-privacy.py --check   # 只读：仓库里那份 == 本地这份，并且公开 URL 抓回来逐字节同
#   py scripts/publish-privacy.py --live    # 只量「网上那一份 == 本地这份」，不查仓库（仓库刚改过就用 --check）
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "上架" / "privacy"
PAGE = SRC / "index.html"
REPO = os.environ.get("JIAN_PRIVACY_REPO", "jian-privacy")


def strip_comments(text):
    """注释里写着「没有 <script>」，不先剥掉就会自己抓自己（第一跑真的这么红了）。"""
    return re.sub(r"<!--[\s\S]*?-->", "", text)


def canonical_url(html):
    """公开地址**只从页面自己那一行 canonical 读**。
    以前它由「gh 登录名 + 仓库名」拼出来——那条可以指向另一个仓库，
    而商店材料引用的是页面上这一条；两边一飘，`--check` 验的就是别人那一页，门还绿。"""
    mu = re.search(r'rel="canonical" href="([^"]+)"', html)
    return mu.group(1).rstrip("/") + "/" if mu else None


def _origin(u):
    m = re.match(r"^(?:https?:)?//([^/?#]+)", u, re.I)
    if m:
        return "//" + m.group(1).lower()
    m = re.match(r"^([a-z][a-z0-9+.-]*://[^/?#]+)", u, re.I)
    return m.group(1).lower() if m else None


# 「这一页不许自己去打第三方请求」这条规则的**唯一**定义：test/store_claims.py 第 8 节 import 它。
# 按**引用形状**抓，不按域名黑名单抓：黑名单只认得写下来的那几个域名，
# `<link rel="stylesheet" href="https://没抄进名单的那个">` 一个都不会红；
# 反过来，政策正文里本来就写着 `https://` 那两个字（讲用户自填网关那一段），
# 按子串抓会把一句真话当成外链。所以只看属性、CSS、脚本这三类真的会发出去的引用。
REF_ATTR = re.compile(r'\b(?:src|href|poster|action|data-src|srcset)\s*=\s*"([^"]*)"', re.I)
REF_CSS = re.compile(r"url\(\s*['\"]?([^)'\"]+)", re.I)
REF_JS = (r"<script", r"\bfetch\s*\(", r"\bXMLHttpRequest", r"sendBeacon", r"new\s+Image",
          r"@import", r"<iframe", r"<embed", r"<object")


def external_refs(html):
    """返回这一页里每一个指向站外的引用。allow 只有页面自己那条 canonical 的同源。"""
    t = strip_comments(html)
    t = re.sub(r"<!DOCTYPE[^>]*>", "", t, flags=re.I)
    canon = canonical_url(t)
    mine = _origin(canon) if canon else None
    hits = []
    for mu in REF_ATTR.finditer(t):
        v = mu.group(1).strip()
        if not v or v.startswith(("mailto:", "tel:", "#", "data:", "javascript:void")):
            continue
        if not v.startswith(("/", "http:", "https:", "//")):
            continue                       # 相对路径：同源（这一页目前一个都没有）
        if _origin(v) != mine:
            hits.append(v)
    for mu in REF_CSS.finditer(t):
        hits.append("css:" + mu.group(1).strip())
    for pat in REF_JS:
        if re.search(pat, t, re.I):
            hits.append("js:" + pat)
    return hits


NOJEKYLL = "# 没有 Jekyll：这一页就是它自己，不需要构建，也不许被构建改写字面下划线。\n"
README = """# 笺 · 隐私政策（公开页）

这一页是安卓应用「笺」(`com.jian.app`) 的隐私政策，Google Play 商店页与应用内引用的就是它。

- 公开地址：{url}
- 源文件在另一个仓库：`docs/上架/privacy/index.html`（「笺」项目里），
  由 `scripts/publish-privacy.py` 逐字节推到这里。仓库里这份是**产物**，不要在这儿手改——
  在这儿改，下一次发布就会被覆盖，而且那条「已发布的 == 源」的门会红。
- 这一页不加载任何第三方脚本、字体、图片，也不放 Cookie。
"""


def gh(*args, stdin=None):
    r = subprocess.run(["gh", "api", *args], input=stdin, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r


def die(msg, *extra):
    print("FAIL " + msg)
    for e in extra:
        if e:
            print("     " + str(e).strip()[-400:])
    sys.exit(1)


def owner():
    r = gh("user", "--jq", ".login")
    if r.returncode != 0:
        die("gh 没登录或取不到用户名（先跑 `gh auth status`）", r.stderr)
    return r.stdout.strip()


def blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def ensure_repo(o):
    r = gh("-X", "POST", "/user/repos", "--input", "-",
           stdin=json.dumps({"name": REPO, "private": False, "auto_init": True,
                             "has_issues": False, "has_wiki": False,
                             "description": "隐私政策公开页 · 应用「笺」com.jian.app"}))
    if r.returncode == 0:
        print("  建了仓库 " + o + "/" + REPO)
        return
    if "already exists" in (r.stderr or "").lower() or "422" in (r.stderr or ""):
        return
    die("建不了仓库", r.stderr)


def default_branch(o):
    r = gh("repos/" + o + "/" + REPO, "--jq", ".default_branch")
    if r.returncode != 0:
        die("读不到仓库（是不是没建起来？）", r.stderr)
    b = r.stdout.strip()
    return b or "main"


def remote_sha(o, path):
    """(仓库里那份的 git blob sha, 出错解释)。
    以前「API 报错」与「文件不存在」都折成 None，于是登录态过期会被报成
    「已发布的那一份与本地不一样」——一句会把人推去重新发布的假话。"""
    r = gh("repos/" + o + "/" + REPO + "/contents/" + path, "--jq", ".sha")
    out = (r.stdout or "").strip()
    if r.returncode == 0 and out and out != "null":
        return out, ""
    err = (r.stderr or "").strip()
    if "Not Found" in err or "404" in err or "does not exist" in err:
        return None, ""                       # 真的还没有这个文件
    return None, err[:220]


def put(o, path, data: bytes, msg):
    want = blob_sha(data)
    cur, err = remote_sha(o, path)
    if err:
        die("读不到 " + path + " 在仓库里的现状，不敢瞎写", err)
    body = {"message": msg, "content": base64.b64encode(data).decode(), "branch": BRANCH}
    if cur:
        # 不带 sha 的 PUT 会**盖掉别人在这期间的改动**而不出声；带上就是乐观并发。
        body["sha"] = cur
    r = gh("-X", "PUT", "repos/" + o + "/" + REPO + "/contents/" + path, "--input", "-",
           stdin=json.dumps(body))
    if r.returncode != 0:
        die("写 " + path + " 失败", r.stderr)
    try:
        j = json.loads(r.stdout)
    except Exception:
        die("写 " + path + " 的返回不是 JSON（多半是登录态过期）", r.stdout)
    got = (j.get("content") or {}).get("sha")
    # 「存进去的就是这几个字节」是这条链上最便宜的一次对账，以前只把 sha 打印出来给人看。
    if got != want:
        die("仓库里算出来的 blob 与本地不是同一份（编码或换行被谁动过）\n"
            "     本地 " + want + "\n     仓库 " + str(got))
    return got


def enable_pages(o):
    """已经开着就别再 POST。第一版拿 `.status` 判「开没开」，而**刚开好的那几分钟这个字段是空的**
    → 判成没开 → 再 POST → HTTP 409「already enabled」→ 一次成功的发布以红收场（第二次发布实测就是这样）。
    `html_url` 只要站点在就一定有，用它判；409 也按「已开」处理。"""
    r = gh("repos/" + o + "/" + REPO + "/pages", "--jq", ".html_url")
    if r.returncode == 0 and (r.stdout or "").strip().startswith("http"):
        print("  Pages 已开：" + r.stdout.strip())
        return
    err = ""
    for b in ({"build_type": "standard", "source": {"branch": BRANCH, "path": "/"}},
              {"source": {"branch": BRANCH, "path": "/"}}):
        r = gh("-X", "POST", "repos/" + o + "/" + REPO + "/pages", "--input", "-",
               stdin=json.dumps(b))
        if r.returncode == 0:
            print("  Pages 刚开：build_type=" + str(b.get("build_type")))
            return
        err = (r.stderr or "").strip()
        if "already enabled" in err or "409" in err:
            print("  Pages 已开（POST 回 409，按已开处理）")
            return
    die("开不了 Pages", err)


def wait_pages(url, want, want_live=False):
    """量「网上那一份 == 本地这一份」，**按字节**。
    以前只判 `"笺 隐私政策" in html`——那是 <title>/h1，跨版本都不变：
    Pages 构建失败、源分支被换、CDN 还发着上一版，仓库 blob 那条绿、这一条也绿。
    而 `put` 完立刻进循环时第 1 次抓到的**就是上一个构建**，于是「live ok 第 1 次抓到」
    可以指着一份旧政策（第 60 轮复核抓出来的 P0）。"""
    if not want_live:
        print("  公开地址：" + url)
        return
    import time
    last = ""
    for i in range(60):
        try:
            with urllib.request.urlopen(url, timeout=20) as f:
                raw, code = f.read(), f.status
            if code != 200:
                last = "HTTP " + str(code)
            elif blob_sha(raw) == want:
                print("  live ok：" + url + "（" + str(len(raw)) + " 字节，逐字节 == 本地那一份，"
                      "第 " + str(i + 1) + " 次抓到）")
                return
            else:
                last = ("200 但不是这一份（Pages 还在发旧构建）抓到 blob " + blob_sha(raw)[:10]
                        + " ≠ 本地 " + want[:10])
        except Exception as e:
            last = type(e).__name__ + " " + str(e)[:80]
        print("  " + str(i + 1) + " 次还没好：" + last)
        time.sleep(5)
    die("公开 URL 60 次都不是一份对得上的字节：" + url + "\n     最后一次：" + last)


def check_local_floor():
    """发布前自己先量一遍：不许发出去一份空页/半页，也不许这一页自己去打第三方请求。"""
    html = PAGE.read_bytes()
    if len(html) < 2000:
        die("index.html 只有 " + str(len(html)) + " 字节，不像一份完整的政策页")
    text = html.decode("utf-8")
    body = strip_comments(text)
    for need in ("笺 隐私政策", "<li>", "更新日期", "mailto:"):
        if need not in body:
            die("发布前自检：政策页里没有「" + need + "」")
    # 那封邮箱**不写死**在这里：它是政策正文那一行的一部分，由 test/store_claims.py 与文档两头对。
    # 这里再钉一份，日后换邮箱就是一次没有道理的假红（第 60 轮复核点出来的）。
    if not canonical_url(text):
        die("发布前自检：这一页没有 canonical —— 那条公开地址就没有唯一的说法")
    refs = external_refs(text)
    if refs:
        die("发布前自检：这一页会往站外发请求 " + "、".join(refs[:6]))
    return html


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    html = check_local_floor()
    o = owner()
    global BRANCH
    want = blob_sha(html)
    # 要验的那条地址**从页面上读**，不由「登录名 + 仓库名」拼：拼出来的那条可以指向
    # 另一个仓库，而商店材料引用的是页面上这一条（两边一飘，--check 验的是别人那一页，门还绿）。
    url = canonical_url(html.decode("utf-8"))
    if "/" + REPO not in url:
        die("这一页的 canonical（" + str(url) + "）里没有仓库名 " + REPO +
            "：要么改了 JIAN_PRIVACY_REPO，要么 canonical 指到别处去了")
    # 只有发布这一档才允许创建东西：`--check` 是「只读」的，
    # 一台没建过仓库的机器上跑它，不该顺手把公开仓库给建出来（第一版就是这么写的）。
    if mode in ("--check", "--live"):
        r = gh("repos/" + o + "/" + REPO, "--jq", ".default_branch")
        if r.returncode != 0:
            die("仓库 " + o + "/" + REPO + " 不在：这一页还没发布过，"
                "没有「已发布 == 本地」可比。要发布就跑 `python scripts/publish-privacy.py`",
                r.stderr)
        BRANCH = r.stdout.strip() or "main"
    else:
        ensure_repo(o)
        BRANCH = default_branch(o)
    if mode == "--check":
        have, err = remote_sha(o, "index.html")
        if err:
            die("读不到仓库里那份的现状（不是「没有」，是读不出来）", err)
        if have != want:
            die("仓库里那一份与本地不一样（改了源忘了发布）\n"
                "     本地 blob " + want + "\n     仓库 blob " + str(have))
        print("  仓库里 == 本地源（blob " + want[:10] + "）")
        wait_pages(url, want, want_live=True)
        return
    if mode == "--live":
        wait_pages(url, want, want_live=True)
        return
    put(o, "index.html", html, "docs/上架/privacy/index.html " + want[:10])
    put(o, ".nojekyll", NOJEKYLL.encode("utf-8"), "关掉 Jekyll：这一页不需要构建")
    # 发布仓库那份 README 里的地址也从 canonical 生成：硬抄一份就是第四处副本，
    # 它会比页面先过期（第 60 轮复核点的就是这种「同一句话好几个副本、门只读其中三个」）。
    put(o, "README.md", README.replace("{url}", url).encode("utf-8"),
        "说明：这一页的源在「笺」仓库里，别在这儿改")
    print("  写了 index.html（git blob 已对上）")
    enable_pages(o)
    wait_pages(url, want, want_live=True)
    print("OK " + url)


BRANCH = "main"

if __name__ == "__main__":
    main()
