/** 笺 · 本机恢复点 v0.9
 * IndexedDB 与原来的 localStorage 完全分离：不接管日常保存，不改备份 JSON 形状。
 * 恢复点由 WebCrypto SHA-256 验证，创建完成后才宣布成功，最多保留最近五份。
 * 同源存储仍可能被浏览器清理；它不是跨设备或加密备份的替代品。 */
const RecoveryPoints = (() => {
  const DB = "jian-recovery-v1";
  const STORE = "points";
  const KEEP = 5;
  const MAX_BYTES = 16 * 1024 * 1024;

  const available = () => typeof indexedDB !== "undefined"
    && typeof crypto !== "undefined" && !!crypto.subtle;

  function open() {
    return new Promise((resolve, reject) => {
      if (!available()) return reject(new Error("当前环境不支持本机恢复点，请导出文件备份"));
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
      };
      req.onerror = () => reject(req.error || new Error("本机恢复点无法打开"));
      req.onblocked = () => reject(new Error("其他标签页占着恢复库，请关闭后重试"));
      req.onsuccess = () => resolve(req.result);
    });
  }

  async function operate(mode, work) {
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        let answer;
        const tx = db.transaction(STORE, mode);
        tx.oncomplete = () => resolve(answer);
        tx.onerror = () => reject(tx.error || new Error("本机恢复点操作失败"));
        tx.onabort = () => reject(tx.error || new Error("本机恢复点事务中断"));
        try {
          const request = work(tx.objectStore(STORE));
          if (request) request.onsuccess = () => { answer = request.result; };
        } catch (e) { try { tx.abort(); } catch (_) {} reject(e); }
      });
    } finally { db.close(); }
  }
  async function hash(raw) {
    const data = new TextEncoder().encode(raw);
    const digest = await crypto.subtle.digest("SHA-256", data);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  async function list() {
    const rows = await operate("readonly", (store) => store.getAll());
    return rows.sort((a, b) => b.savedAt - a.savedAt || String(b.id).localeCompare(String(a.id)));
  }
  async function putAndPrune(point) {
    const existing = await list();
    const remove = [...existing, point].sort((a, b) => b.savedAt - a.savedAt
      || String(b.id).localeCompare(String(a.id))).slice(KEEP).map((p) => p.id);
    const db = await open();
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("恢复点保存失败"));
        tx.onabort = () => reject(tx.error || new Error("恢复点保存被中断"));
        const store = tx.objectStore(STORE);
        store.put(point);
        remove.forEach((key) => { if (key !== point.id) store.delete(key); });
      });
    } finally { db.close(); }
  }
  async function capture(reason) {
    if (!available()) throw new Error("当前环境无法使用恢复点，请改用文件备份");
    const at = Date.now();
    // 序列化一份只读快照：绝不调用 trimStore，更不能修改正在使用的 state。
    const raw = JSON.stringify(Object.assign({ savedAt: at }, state));
    const bytes = new TextEncoder().encode(raw).byteLength;
    if (bytes > MAX_BYTES) throw new Error("本机数据超过 16 MB，恢复点未保存；请导出文件备份");
    const point = {
      id: "rp-" + at.toString(36) + "-" + Math.random().toString(36).slice(2, 10),
      savedAt: at, reason: reason === "导入前" ? "导入前" : "手动",
      sha256: await hash(raw), bytes,
      clothes: (state.wardrobe || []).length, cards: (state.yanCards || []).length,
      slips: (state.album || []).length, raw
    };
    await putAndPrune(point);
    // 再读一次确认整个事务提交；成功之前不提示已留档。
    const saved = await operate("readonly", (store) => store.get(point.id));
    if (!saved || saved.sha256 !== point.sha256)
      throw new Error("恢复点未能通过落盘校验，请导出文件备份");
    return point;
  }

  async function verified(id) {
    const point = await operate("readonly", (store) => store.get(id));
    if (!point || typeof point.raw !== "string" || point.raw.length > MAX_BYTES
        || !/^[a-f0-9]{64}$/.test(String(point.sha256 || "")))
      throw new Error("恢复点缺失或结构异常，原数据未改变");
    if ((await hash(point.raw)) !== point.sha256)
      throw new Error("恢复点校验失败，原数据未改变");
    let obj;
    try { obj = JSON.parse(point.raw); } catch (_) { throw new Error("恢复点内容损坏，原数据未改变"); }
    if (!obj || !Array.isArray(obj.wardrobe) || !obj.modules || Array.isArray(obj.modules))
      throw new Error("恢复点结构不完整，原数据未改变");
    return { point, obj };
  }

  const remove = (id) => operate("readwrite", (store) => store.delete(id));
  // 隐私清空不能依赖 WebCrypto：即使摘要接口暂时不可用，也必须尝试擦除旧快照。
  const clear = () => typeof indexedDB !== "undefined"
    ? operate("readwrite", (store) => store.clear()) : Promise.resolve();

  function tell(box, msg) {
    const el = box.querySelector("#recoveryStatus");
    if (el) el.textContent = msg;
  }
  async function refresh(box) {
    if (!box || !box.isConnected) return;
    const host = box.querySelector("#recoveryList");
    try {
      if (!available()) { tell(box, "当前环境不支持 IndexedDB；请使用普通或加密文件备份。"); return; }
      const points = await list();
      if (!host || !box.isConnected) return;
      host.innerHTML = points.length ? points.map((p) => {
        const d = new Date(p.savedAt);
        const when = Number.isFinite(d.getTime()) ? d.toLocaleString("zh-CN", { hour12: false }) : "日期不详";
        return '<div class="recovery-row"><div class="grow"><b>'
          + esc(p.reason === "导入前" ? "自动 · 导入前" : "手动恢复点")
          + '</b><span class="tiny">' + esc(when)
          + ' · 柜里 ' + Number(p.clothes || 0) + ' 件 · 言笺 '
          + Number(p.cards || 0) + ' 条 · 笺册 ' + Number(p.slips || 0)
          + ' 张 · ' + Math.round(Number(p.bytes || 0) / 1024) + ' KB</span></div>'
          + '<div class="recovery-actions"><button class="chip" data-rprestore="' + esc(p.id)
          + '">恢复</button><button class="chip" data-rpdel="' + esc(p.id)
          + '">删除</button></div></div>';
      }).join("") : '<p class="tiny">还没有恢复点。点「现在留一份」就会存下此刻全部数据。</p>';
      tell(box, "本机共 " + points.length + " 份，最多保留最近 " + KEEP + " 份。");
      host.querySelectorAll("[data-rprestore]").forEach((b) => {
        b.onclick = async () => {
          if (box.dataset.busy) return;
          box.dataset.busy = "1";
          try {
            const { point, obj } = await verified(b.dataset.rprestore);
            if (!confirm("要将整份本机数据恢复到 " + new Date(point.savedAt).toLocaleString("zh-CN")
                + " 吗？导入前会自动保留当前数据的恢复点，还可以撤销。")) return;
            tell(box, "正在校验并恢复…");
            if (!(await applyBackupObject(obj))) tell(box, "恢复失败，原数据未改变。");
          } catch (e) { tell(box, String(e.message || e)); }
          finally { delete box.dataset.busy; }
        };
      });
      host.querySelectorAll("[data-rpdel]").forEach((b) => {
        b.onclick = async () => {
          if (box.dataset.busy || !confirm("确定永久删除这一份本机恢复点？")) return;
          box.dataset.busy = "1";
          try { await remove(b.dataset.rpdel); await refresh(box); }
          catch (e) { tell(box, String(e.message || e)); }
          finally { delete box.dataset.busy; }
        };
      });
    } catch (e) { tell(box, String(e.message || e)); }
  }
  function attach(box) {
    if (!box) return;
    box.querySelector("#recoverySave").onclick = async () => {
      if (box.dataset.busy) return;
      box.dataset.busy = "1";
      tell(box, "正在为此刻的数据留一份完整快照…");
      try { await capture("手动"); await refresh(box); }
      catch (e) { tell(box, String(e.message || e)); }
      finally { delete box.dataset.busy; }
    };
    box.addEventListener("toggle", () => { if (box.open) refresh(box); });
  }
  return Object.freeze({ available, capture, verified, list, remove, clear, attach, refresh });
})();
