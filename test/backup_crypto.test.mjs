// 加密备份协议的独立守门：真实 Node WebCrypto，错误密码、篡改和格式炸弹均不可落盘。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const src = readFileSync(new URL("../backup-crypto.js", import.meta.url), "utf8");
const ctx = vm.createContext({ crypto: webcrypto, TextEncoder, TextDecoder, Uint8Array, btoa, atob, Date });
vm.runInContext(src + "\nglobalThis.Vault = JianVault;", ctx);
const V = ctx.Vault;
const checks = [];
const check = async (label, f) => { await f(); checks.push(label); console.log("  ok  " + label); };
const fail = async (action, match) => assert.rejects(action, match);
const pwd = "这是一句很长的加密备份密码! ☂️ 2026";
const raw = JSON.stringify({ savedAt: 1793562000000, wardrobe: [{ name: "白衬衫", img: "data:image/png;base64,abc" }],
  modules: { yi: true, wei: false, yan: true }, yanCards: [{ line: "私人：保密" }] });
const sealed = await V.encrypt(raw, pwd, 1793562000000);

await check("真正 AES-GCM 加密后可完整往返中文和照片文本", async () => {
  assert.equal(await V.decrypt(sealed, pwd), raw);
  assert.equal(sealed.kind, "jian-encrypted-backup");
  assert.equal(sealed.cipher, "AES-256-GCM");
  assert.equal(sealed.kdf, "PBKDF2-SHA-256");
  assert.equal(sealed.iterations, 600000);
});
await check("备份外壳只含元数据，密文不泄露私人字句", () => {
  assert.equal(JSON.stringify(sealed).includes("私人：保密"), false);
  assert.equal(JSON.stringify(sealed).includes("白衬衫"), false);
  assert.equal(Object.hasOwn(sealed, "wardrobe"), false);
});
await check("每次导出换盐与 IV，同样的内容产生不同密文", async () => {
  const b = await V.encrypt(raw, pwd, sealed.savedAt);
  assert.notEqual(sealed.salt, b.salt);
  assert.notEqual(sealed.iv, b.iv);
  assert.notEqual(sealed.data, b.data);
});
await check("错误密码不会得到任何明文", async () =>
  fail(() => V.decrypt(sealed, "其它密码绝对不行"), /密码不对/));
await check("密文字节被动过就验证失败", async () => {
  const byte = sealed.data[10] === "A" ? "B" : "A";
  await fail(() => V.decrypt({ ...sealed, data: sealed.data.slice(0, 10) + byte + sealed.data.slice(11) }, pwd), /密码不对/);
});
await check("外层导出时间被改动也验证失败（AAD）", async () =>
  fail(() => V.decrypt({ ...sealed, savedAt: sealed.savedAt + 1 }, pwd), /密码不对/));
await check("文件格式版本、算法和 KDF 不识别时拒绝", async () => {
  for (const field of ["format", "cipher", "kdf"]) {
    assert.throws(() => V.validate({ ...sealed, [field]: "malformed" }), /不受支持/);
  }
});
await check("恶意 PBKDF2 次数在派生前被拦截", () => {
  for (const iterations of [1, 99999, 1000001, 2 ** 30, 0.5, "250000"]) {
    assert.throws(() => V.validate({ ...sealed, iterations }), /不受支持/);
  }
});
await check("随机盐与 IV 长度必须严格正确", () => {
  assert.throws(() => V.validate({ ...sealed, salt: "YQ==" }), /随机参数/);
  assert.throws(() => V.validate({ ...sealed, iv: "YQ==" }), /随机参数/);
});
await check("截断、非法 Base64、过大密文被拒绝", () => {
  for (const data of ["!", "", "YQ==", "A".repeat(16_000_000)]) {
    assert.throws(() => V.validate({ ...sealed, data }), /格式不正确|不完整|上限/);
  }
});
await check("导出密码至少十字符，类型不对也拒绝", async () => {
  await fail(() => V.encrypt(raw, "short"), /10/);
  await fail(() => V.encrypt(raw, null), /10/);
});
await check("过大明文在加密前被拒绝", async () =>
  fail(() => V.encrypt("长".repeat(3_600_000), pwd), /数据太多/));
await check("普通 JSON 不会被误认为加密文件", () => {
  assert.equal(V.isEnvelope(JSON.parse(raw)), false);
  assert.equal(V.isEnvelope(null), false);
  assert.equal(V.isEnvelope([]), false);
});
await check("没有外部通信或第三方密码依赖", () => {
  assert.doesNotMatch(src, /fetch\s*\(|XMLHttpRequest|https?:\/\/|sendBeacon/);
});
console.log("\n加密备份协议：" + checks.length + " 通过 / 0 失败");
