/** 笺 · 离线
   manifest.json 早就配好了，`build-www.mjs` 也一直给这个文件留着位置（optionalFiles 里就是它），
   但 service worker 从来没写过——「PWA / 离线可用」是句空话。这里补上：
   装到主屏、或者断网的手机，还能打开上次的界面。

   两条策略：
   - 导航（打开 / 刷新 index.html）**网络优先**，失败才回缓存：发版后不会永远卡在旧壳上
   - 静态资源**缓存优先**，未命中再上网并把结果补进缓存

   缓存名带版本号，而版本号必须和 `config.js`、`package.json` 一致（`build-www` 出包前对账，
   不一致直接不给打包）。版本一变，activate 就清掉旧缓存。
   `file://` 下根本不注册（见 app.js），双击打开这条老用法不受任何影响。
 */
const VERSION = "0.7.0";
const CACHE = "jian-" + VERSION;

/* 这份清单要和 build-www.mjs 的白名单对齐，npm run check 会盯。 */
const SHELL = [
  "./", "./index.html", "./styles.css", "./config.js", "./engine.js", "./api.js",
  "./state.js", "./ui.js", "./card.js", "./card-year.js", "./card-long.js",
  "./yi.js", "./wei.js", "./yan.js", "./backup-crypto.js", "./me.js",
  "./app.js", "./theme.js", "./wardrobe.js", "./cookbook.js", "./market.js", "./remind.js",
  "./stats.js", "./achievements.js", "./settings.js", "./wire.js", "./share.js", "./today.js", "./styles-v06.css", "./styles-yi.css", "./styles-wei.css", "./styles-yan.css",
  "./styles-stats.css", "./styles-me.css", "./manifest.json",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/icon-maskable-512.png",
  "./icons/apple-touch-icon.png", "./icons/favicon.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    // 少一个文件（比如没生成 favicon）不该让整次安装失败，逐个吞掉。
    // 但「一个都没存下来」必须让安装失败：机器忙的时候 20 个 add 可以全挂，
    // 全吞掉之后安装照样算成功、SW 照样激活——于是断网重开是一片 ERR_CONNECTION_REFUSED，
    // 守门只报得出「controller 不在、缓存 0 个」，看不出真正的原因在哪一层。
    // `cache: "reload"` 是必须的：不带它，`c.add(u)` 会命中**上一代 SW 留下的 HTTP 缓存**，
    // 于是新版本号的缓存里装的还是旧文件（实测过：版本号升到 0.6.1，新缓存里 app.js 仍是旧的）。
    // 缓存名跟着版本走只保证「换一个桶」，不保证「桶里装的是新东西」。
    let stored = 0;
    await Promise.all(SHELL.map((u) =>
      c.add(new Request(u, { cache: "reload" })).then(() => { stored++; }, () => {})));
    if (!stored) throw new Error("预缓存一个文件都没存下");
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((k) => k.startsWith("jian-") && k !== CACHE)
      .map((k) => caches.delete(k)));
    self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // 网关地址是用户自己的后端，跨源就绝不插手（也不该把判定结果缓存下来）
  if (url.origin !== self.location.origin) return;
  if (/\/sw\.js$/.test(url.pathname)) return;               // 别缓存自己，否则永远更新不了
  if (req.mode === "navigate") { e.respondWith(networkFirst(req)); return; }
  e.respondWith(cacheFirst(req));
});

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res.ok) fill(req, res);
    return res;
  } catch (_) { /* 断网：掉到缓存 */ }
  const hit = await caches.match(req);
  if (hit) return hit;
  const shell = await caches.match("./index.html");
  return shell || Response.error();
}

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) fill(req, res);
  return res;
}

/** 把一次成功响应补进缓存。
 *
 *  这里以前是 `c.put(req, res)` —— 而 res 已经 `return` 给页面了，它的 body 已经被读走。
 *  浏览器的反应是抛 `Response body is already used`，那个异常又被本行的 `.catch(()=>{})`
 *  吞掉，于是**什么都没发生，日志里也没有一行**。后果是：缓存里永远是最早那一版的资源，
 *  升版本之后老用户刷新多少次都还是旧前端（实测过一次：版本号改成 0.6.1，新缓存里
 *  装的仍是旧的 app.js，刷新 5 次、关掉浏览器重开都不恢复）。
 *
 *  两个改法缺一不可：
 *  1. `res.clone()` —— 给缓存一份独立的 body 流，页面继续读原来那份；
 *  2. 吞异常之前先 `warn` —— 这一行如果又失败，控制台得有一行字，
 *     不然下次还是「静默地什么都没发生」。 */
function fill(req, res) {
  let copy;
  try { copy = res.clone(); } catch (e) { console.warn("sw clone", e); return; }
  caches.open(CACHE).then((c) => c.put(req, copy)).catch((e) => console.warn("sw put", e));
}
