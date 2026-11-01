/** 笺 · 离线加密备份（WebCrypto；不发送密码、不储存密码、不借第三方服务）。
 *  格式版本独立于业务 SCHEMA：文件外壳明文只暴露格式和导出时间，
 *  业务正文全部在 AES-256-GCM 密文中；口令用 PBKDF2-SHA-256 派生，每份随机盐。
 *  勿在 UI 层自行解读密文，也勿在失败时更改 localStorage。 */
const JianVault = (() => {
  const KIND = "jian-encrypted-backup";
  const FORMAT = 1;
  const ITERATIONS = 600000;
  const MIN_ITER = 100000, MAX_ITER = 1000000;
  // state 的上限按 JS 字符数计，汉字 UTF-8 可占 3 字节：给接近满额的旧备份留余量。
  const MAX_PLAIN = 10 * 1024 * 1024;
  const MAX_DATA = MAX_PLAIN + 16;
  const enc = new TextEncoder(), dec = new TextDecoder("utf-8", { fatal: true });
  const subtle = () => {
    if (!globalThis.crypto || !globalThis.crypto.subtle) throw new Error("此环境不支持安全加密，请使用 HTTPS 或新版 App");
    return globalThis.crypto.subtle;
  };
  const base64 = (u) => {
    let out = "";
    for (let i = 0; i < u.length; i += 32768) out += String.fromCharCode(...u.subarray(i, i + 32768));
    return btoa(out);
  };
  const unbase64 = (v, limit) => {
    if (typeof v !== "string" || !v || v.length > Math.ceil(limit / 3) * 4 + 4 ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(v))
      throw new Error("加密备份的数据格式不正确");
    const raw = atob(v);
    if (raw.length > limit) throw new Error("加密备份超过大小上限");
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  };
  const aad = (o) => enc.encode([o.kind, o.format, o.savedAt, o.iterations].join("|"));
  async function keyFor(password, salt, iterations) {
    const s = subtle();
    const material = await s.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
    return s.deriveKey({ name: "PBKDF2", salt, iterations, hash: "SHA-256" },
      material, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }
  function isEnvelope(obj) {
    return !!obj && typeof obj === "object" && !Array.isArray(obj) && obj.kind === KIND;
  }
  function validate(obj) {
    if (!isEnvelope(obj) || obj.format !== FORMAT || obj.cipher !== "AES-256-GCM" ||
        obj.kdf !== "PBKDF2-SHA-256" || !Number.isInteger(obj.iterations) ||
        obj.iterations < MIN_ITER || obj.iterations > MAX_ITER ||
        !Number.isSafeInteger(obj.savedAt) || obj.savedAt <= 0)
      throw new Error("加密备份格式不受支持或已损坏");
    const salt = unbase64(obj.salt, 16), iv = unbase64(obj.iv, 12);
    if (salt.length !== 16 || iv.length !== 12) throw new Error("加密备份随机参数不正确");
    const data = unbase64(obj.data, MAX_DATA);
    if (data.length < 17) throw new Error("加密备份内容不完整");
    return { salt, iv, data };
  }
  async function encrypt(plain, password, savedAt = Date.now()) {
    if (typeof password !== "string" || password.length < 10 || password.length > 256)
      throw new Error("密码请设为 10–256 个字符");
    if (typeof plain !== "string") throw new Error("备份正文不是文本");
    const data = enc.encode(plain);
    if (data.length > MAX_PLAIN) throw new Error("数据太多，暂时无法生成加密备份");
    const s = subtle(), salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const header = { kind: KIND, format: FORMAT, savedAt, cipher: "AES-256-GCM",
      kdf: "PBKDF2-SHA-256", iterations: ITERATIONS };
    const key = await keyFor(password, salt, ITERATIONS);
    const sealed = await s.encrypt({ name: "AES-GCM", iv, additionalData: aad(header) }, key, data);
    return { ...header, salt: base64(salt), iv: base64(iv), data: base64(new Uint8Array(sealed)) };
  }
  async function decrypt(obj, password) {
    const { salt, iv, data } = validate(obj); // 先验大小/格式，再花 PBKDF2 时间
    if (typeof password !== "string" || !password) throw new Error("请输入备份密码");
    try {
      const key = await keyFor(password, salt, obj.iterations);
      const plain = await subtle().decrypt({ name: "AES-GCM", iv, additionalData: aad(obj) }, key, data);
      if (plain.byteLength > MAX_PLAIN) throw new Error("解密后的数据过大");
      return dec.decode(plain);
    } catch (e) {
      if (e instanceof Error && /数据过大/.test(e.message)) throw e;
      throw new Error("密码不对，或备份文件已被改动；原数据没有变化");
    }
  }
  return Object.freeze({ isEnvelope, encrypt, decrypt, validate });
})();
