/** 外接算力：填了 endpoint 则走网关，留空则全部本地引擎。 */
window.JIAN_CONFIG = {
  // 运行时里唯一一处版本号。「我的」页脚读它；npm run build-www 会拿它和
  // package.json、android/app/build.gradle 的 versionName 对账，不一致就不给出包。
  version: "0.9.0",
  endpoint: "",
  key: "",
  // 隐私政策那一页的网址。**仓库里这条 URL 只有这一处定义**：「册」里那条入口（me.js 的
  // renderPrivacy）从这儿读，index.html 与 me.js 都不写字面串；商店材料第 1 节填的那格、
  // 政策页自己的 canonical 由 test/store_claims.py 拿这一条对账。
  privacyUrl: "https://tbj0623.github.io/jian-privacy/",
  timeoutMs: 20000,
  // 看图这条路实测 1.1~14 秒都有过（同一段 OCR，快的时候 2.6 秒，慢的时候顶到 14 秒）。
  // 判定是本地算的、几十毫秒，用不上这么久；给图片单开一个预算，不然一慢就被掐掉回落。
  seeMs: 45000,
  paths: {
    complete: "/v1/complete",
    see: "/v1/see",
    recognize: "/v1/recognize",
    ocr: "/v1/ocr",
    status: "/v1/status"
  }
};
