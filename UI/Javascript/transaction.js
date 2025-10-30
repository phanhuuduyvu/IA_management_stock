(() => {
  "use strict";

  // ---------- API base ----------
  const API_BASE = document.body?.getAttribute("data-api-base")?.trim()
    || `${location.protocol}//${location.hostname}:8001`;

  const ROUTES = {
    transactions: `${API_BASE}/api/transactions`,
    materials:    `${API_BASE}/api/raw-materials`,
    products:     `${API_BASE}/api/finished-goods`,
    // Auth + profile
    me:        `${API_BASE}/api/me`,
    login:     `${API_BASE}/api/auth/login`,
    refresh:   `${API_BASE}/api/auth/refresh`,
    logout:    `${API_BASE}/api/auth/logout`,
  };

  // ---------- Elements ----------
  const fromDate     = document.getElementById("fromDate");
  const toDate       = document.getElementById("toDate");
  const itemType     = document.getElementById("itemType");
  const searchInput  = document.getElementById("searchInput");
  const filterBtn    = document.getElementById("filterBtn");
  const resetBtn     = document.getElementById("resetBtn");
  const pageSizeSel  = document.getElementById("pageSize");
  const tableBody    = document.querySelector("#txTable tbody");
  const pager        = document.getElementById("pager");
  const logoutBtn    = document.getElementById("logoutBtn");   // <-- Nút Logout (nếu có)
  const greetEl      = document.getElementById("greetName");   // <-- Tuỳ chọn: hiển thị tên user

  // Create modal
  const createForm       = document.getElementById("createForm");
  const createItemType   = document.getElementById("createItemType");
  const createMaterial   = document.getElementById("createMaterial");
  const createProduct    = document.getElementById("createProduct");
  const createTxTypeSel  = createForm?.querySelector('select[name="TransactionType"]');
  const createQtyInput   = createForm?.querySelector('input[name="Qty"]');

  // ---------- AUTH (JWT) ----------
  const LS = {
    access: "auth.access_token",
    accessExp: "auth.access_expires_at",
    refresh: "auth.refresh_token",
    refreshExp: "auth.refresh_expires_at",
    me: "auth.me",
  };
  const EXP_LEEWAY = 30; // giây

  const nowEpoch = () => Math.floor(Date.now() / 1000);
  const getAT    = () => localStorage.getItem(LS.access) || "";
  const getRT    = () => localStorage.getItem(LS.refresh) || "";
  const getMe    = () => { try { return JSON.parse(localStorage.getItem(LS.me) || "null"); } catch { return null; } };

  const isExpired = (key) => {
    const exp = Number(localStorage.getItem(key) || 0);
    return !exp || nowEpoch() >= (exp - EXP_LEEWAY);
  };
  const isAccessExpired  = () => isExpired(LS.accessExp);
  const isRefreshExpired = () => isExpired(LS.refreshExp);

  const clearTokens = () => {
    localStorage.removeItem(LS.access);
    localStorage.removeItem(LS.accessExp);
    localStorage.removeItem(LS.refresh);
    localStorage.removeItem(LS.refreshExp);
    // localStorage.removeItem(LS.me); // nếu muốn xoá luôn cache me
  };

  async function doLogout(e) {
    e?.preventDefault?.();
    try {
      const at = getAT();
      if (at) {
        await fetch(ROUTES.logout, { method: "POST", headers: { "Authorization": `Bearer ${at}` }, cache: "no-store" });
      }
    } catch { /* ignore */ }
    clearTokens();
    location.href = "./login.html";
  }
  if (logoutBtn) logoutBtn.addEventListener("click", doLogout);

  let refreshing = null;
  async function refreshAccessToken() {
    if (refreshing) return refreshing;
    const rt = getRT();
    if (!rt) throw new Error("No refresh token");

    refreshing = (async () => {
      const res = await fetch(ROUTES.refresh, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
        cache: "no-store",
      });
      const data = await (async ()=>{try{return await res.json();}catch{return null;}})();
      refreshing = null;
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);

      localStorage.setItem(LS.access, data.access_token);
      localStorage.setItem(LS.accessExp, String(data.access_expires_at));
      localStorage.setItem(LS.refresh, data.refresh_token);
      localStorage.setItem(LS.refreshExp, String(data.refresh_expires_at));
      return true;
    })();

    return refreshing;
  }

  async function ensureAccessToken() {
    if (!isAccessExpired()) return;
    if (isRefreshExpired()) throw new Error("Session expired");
    await refreshAccessToken();
  }

  // fetch kèm Bearer, tự refresh 401
  async function apiFetch(url, options = {}, { auth = "access", retryOn401 = true } = {}) {
    const headers = new Headers({ Accept: "application/json", ...(options.headers || {}) });
    const opts = { method: "GET", ...options, headers, cache: "no-store" };

    if (opts.body && !(opts.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    if (auth === "access") {
      await ensureAccessToken();
      const at = getAT();
      if (at) headers.set("Authorization", `Bearer ${at}`);
    }

    let res = await fetch(url, opts);

    if (res.status === 401 && auth === "access" && retryOn401 && !isRefreshExpired()) {
      try {
        await refreshAccessToken();
        const headers2 = new Headers({ Accept: "application/json" });
        if (opts.body && !(opts.body instanceof FormData)) headers2.set("Content-Type", "application/json");
        const at2 = getAT();
        if (at2) headers2.set("Authorization", `Bearer ${at2}`);
        res = await fetch(url, { method: opts.method, body: opts.body, headers: headers2, cache: "no-store" });
      } catch { /* fallthrough */ }
    }

    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await res.json().catch(()=>null) : null;
    if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
    return data;
  }

  async function requireLogin() {
    if (!getRT() || isRefreshExpired()) {
      location.href = "./login.html";
      throw new Error("Redirecting to login");
    }
    const me = await apiFetch(ROUTES.me, { method: "GET" }, { auth: "access" });
    localStorage.setItem(LS.me, JSON.stringify(me || {}));
    if (greetEl) {
      const name = me?.full_name || me?.username || me?.email || "User";
      greetEl.textContent = name;
    }
  }

  // ---------- State ----------
  const state = {
    page: 1,
    pageSize: parseInt(pageSizeSel?.value || "20", 10) || 20,
    sort: "TimeUpdate",
    order: "desc",
    all: [],
    view: [],
    total: 0,

    // Preview numbers for create
    preview: { beforeQty: null, afterQty: null }
  };

  // ---------- Helpers ----------
  const qs = (params) =>
    Object.entries(params)
      .filter(([,v]) => v !== undefined && v !== null && `${v}`.trim() !== "")
      .map(([k,v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");

  const fmtNum = (v) => (v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString());
  const fmtDT  = (s) => s ? new Date(s).toLocaleString() : "";

  const getChangedBy = () => {
    const me = getMe();
    return me?.UserID ?? me?.id ?? me?.user_id ?? null;
  };

  // ---------- Load materials/products for Create modal (AUTHED) ----------
  async function loadMaterials() {
    try {
      const data = await apiFetch(ROUTES.materials, { method: "GET" }, { auth: "access" });
      const list = Array.isArray(data?.data) ? data.data : Array.isArray(data) ? data : [];
      createMaterial.innerHTML = `<option value="">—</option>` +
        list.map(m => {
          const id = m.MaterialID ?? m.MaterialsId ?? m.id ?? m.ID;
          const name = m.MaterialName ?? m.MaterialsName ?? m.Name ?? "";
          return `<option value="${id}">${id ?? ""} — ${name ?? ""}</option>`;
        }).join("");
    } catch (e) {
      console.error("Load materials failed:", e);
      createMaterial.innerHTML = `<option value="">—</option>`;
      if (/401|expired/i.test(String(e))) { clearTokens(); location.href = "./login.html"; }
    }
  }

  async function loadProducts() {
    try {
      const data = await apiFetch(ROUTES.products, { method: "GET" }, { auth: "access" });
      const list = Array.isArray(data?.data) ? data.data : Array.isArray(data) ? data : [];
      createProduct.innerHTML = `<option value="">—</option>` +
        list.map(p => {
          const id = p.GoodsID ?? p.ProductId ?? p.id ?? p.ID;
          const name = p.FinishedGoodsName ?? p.ProductName ?? p.Name ?? "";
          return `<option value="${id}">${id ?? ""} — ${name ?? ""}</option>`;
        }).join("");
    } catch (e) {
      console.error("Load products failed:", e);
      createProduct.innerHTML = `<option value="">—</option>`;
      if (/401|expired/i.test(String(e))) { clearTokens(); location.href = "./login.html"; }
    }
  }

  // === Lấy quantity hiện tại của item để preview Before/After (AUTHED) ===
  async function fetchCurrentQty() {
    const t = createItemType?.value;
    const mId = createMaterial?.value;
    const pId = createProduct?.value;

    try {
      if (t === "RawMaterials" && mId) {
        const data = await apiFetch(`${ROUTES.materials}/${encodeURIComponent(mId)}`, { method: "GET" }, { auth: "access" });
        const qty = Number(data?.data?.MaterialQuantity ?? data?.MaterialQuantity ?? 0);
        return qty;
      }
      if (t === "FinishedGoods" && pId) {
        const data = await apiFetch(`${ROUTES.products}/${encodeURIComponent(pId)}`, { method: "GET" }, { auth: "access" });
        const qty = Number(data?.data?.FinishedGoodsQuantity ?? data?.FinishedGoodsQuantity ?? 0);
        return qty;
      }
    } catch (e) {
      console.warn("fetchCurrentQty failed:", e);
      if (/401|expired/i.test(String(e))) { clearTokens(); location.href = "./login.html"; }
      return null;
    }
    return null;
  }

  function computeAfterQty(before, delta, txType) {
    const d = Number(delta || 0);
    const b = Number(before || 0);
    return (txType === "Export") ? (b - d) : (b + d);
  }

  async function refreshPreview() {
    const txType = createTxTypeSel?.value || "Import";
    const qty    = Number(createQtyInput?.value || 0);
    const before = await fetchCurrentQty();
    if (before == null) {
      state.preview.beforeQty = null;
      state.preview.afterQty  = null;
      return;
    }
    state.preview.beforeQty = before;
    state.preview.afterQty  = computeAfterQty(before, qty, txType);
    console.info(`[Preview] Before=${before}, Qty=${qty}, Type=${txType} => After=${state.preview.afterQty}`);
  }

  // ---------- Fetch transactions (AUTHED) ----------
  async function fetchTransactions() {
    try {
      const params = {
        item_type: itemType?.value || undefined,
        from_date: fromDate?.value || undefined,
        to_date:   toDate?.value || undefined,
      };
      const url = `${ROUTES.transactions}${Object.values(params).some(v => v)?.toString() ? "?" + qs(params) : (qs(params) ? "?" + qs(params) : "")}`;
      const data = await apiFetch(url, { method: "GET" }, { auth: "access" });
      state.all = Array.isArray(data) ? data : Array.isArray(data?.data) ? data.data : [];
      applyClientFilters();
    } catch (e) {
      alert(`Load transactions failed:\n${e?.message || e}`);
      if (/401|expired/i.test(String(e))) { clearTokens(); location.href = "./login.html"; }
    }
  }

  // ---------- Client filters ----------
  function applyClientFilters() {
    const s = (searchInput?.value || "").trim().toLowerCase();
    let rows = state.all.filter(r => {
      if (!s) return true;
      const id         = (r.TransactionID ?? r.id ?? "") + "";
      const prodId     = (r.ProductId ?? "") + "";
      const matId      = (r.MaterialsId ?? "") + "";
      const changedBy  = (r.ChangedBy ?? "") + "";
      const note       = (r.Note ?? "") + "";
      return [id, prodId, matId, changedBy, note].some(x => (x + "").toLowerCase().includes(s));
    });

    const field = state.sort;
    const order = state.order === "asc" ? 1 : -1;
    rows.sort((a,b) => {
      const keyA = a?.[field] ?? a?.[field.charAt(0).toLowerCase()+field.slice(1)];
      const keyB = b?.[field] ?? b?.[field.charAt(0).toLowerCase()+field.slice(1)];
      if (keyA == null && keyB == null) return 0;
      if (keyA == null) return -order;
      if (keyB == null) return order;
      if (field === "TimeUpdate") {
        return (new Date(keyA).getTime() - new Date(keyB).getTime()) * order;
      }
      if (!isNaN(Number(keyA)) && !isNaN(Number(keyB))) return (Number(keyA) - Number(keyB)) * order;
      return ((""+keyA).localeCompare(""+keyB)) * order;
    });

    state.view = rows;
    state.total = rows.length;
    renderPager();
    renderTable(pagedRows());
  }

  function pagedRows() {
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    state.page = Math.min(state.page, totalPages);
    const start = (state.page - 1) * state.pageSize;
    return state.view.slice(start, start + state.pageSize);
  }

  // ---------- Renderers ----------
  function renderTable(rows) {
    if (!tableBody) return;
    tableBody.innerHTML = (rows || []).map(r => {
      const id          = r.TransactionID ?? r.transaction_id ?? r.id;
      const type        = r.TransactionType ?? r.type;
      const itemT       = r.ItemType ?? r.item_type;
      const matId       = r.MaterialsId ?? r.MaterialID ?? r.material_id ?? "";
      const prodId      = r.ProductId ?? r.product_id ?? "";
      const qty         = r.Qty ?? r.qty;
      const before      = r.BeforeQty ?? r.before_qty;
      const after       = r.AfterQty ?? r.after_qty;
      const note        = r.Note ?? "";
      const changedBy   = r.ChangedBy ?? r.changed_by ?? "";
      const timeUpdate  = r.TimeUpdate ?? r.time_update ?? r.updated_at;

      return `<tr>
        <td class="text-nowrap">${id ?? ""}</td>
        <td>${type ?? ""}</td>
        <td>${itemT ?? ""}</td>
        <td>${matId ?? ""}</td>
        <td>${prodId ?? ""}</td>
        <td class="text-end">${fmtNum(qty)}</td>
        <td class="text-end">${fmtNum(before)}</td>
        <td class="text-end">${fmtNum(after)}</td>
        <td class="text-truncate" style="max-width:280px">${note ?? ""}</td>
        <td>${changedBy ?? ""}</td>
        <td class="text-nowrap">${fmtDT(timeUpdate)}</td>
      </tr>`;
    }).join("");
  }

  function renderPager() {
    if (!pager) return;
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    state.page = Math.min(state.page, totalPages);

    const mk = (p, label = p, disabled = false, active = false) =>
      `<li class="page-item ${disabled ? "disabled" : ""} ${active ? "active" : ""}">
         <a class="page-link" href="#" data-page="${p}">${label}</a>
       </li>`;

    let html = "";
    html += mk(state.page - 1, "&laquo;", state.page <= 1);
    const start = Math.max(1, state.page - 2);
    const end = Math.min(totalPages, start + 4);
    for (let p = start; p <= end; p++) html += mk(p, String(p), false, p === state.page);
    html += mk(state.page + 1, "&raquo;", state.page >= totalPages);
    pager.innerHTML = html;

    pager.querySelectorAll("a[data-page]").forEach(a => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const p = parseInt(a.getAttribute("data-page"), 10);
        if (!isNaN(p) && p !== state.page) {
          state.page = p;
          renderTable(pagedRows());
          renderPager();
        }
      });
    });
  }

  // ---------- Events ----------
  document.querySelectorAll("#txTable thead th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const field = th.getAttribute("data-sort");
      if (!field) return;
      if (state.sort === field) {
        state.order = state.order === "asc" ? "desc" : "asc";
      } else {
        state.sort = field; state.order = "asc";
      }
      state.page = 1;
      applyClientFilters();
    });
  });

  filterBtn?.addEventListener("click", () => { state.page = 1; fetchTransactions(); });

  resetBtn?.addEventListener("click", () => {
    if (fromDate) fromDate.value = "";
    if (toDate)   toDate.value   = "";
    if (itemType) itemType.value = "";
    if (searchInput) searchInput.value = "";
    state.page = 1; state.sort = "TimeUpdate"; state.order = "desc";
    fetchTransactions();
  });

  pageSizeSel?.addEventListener("change", () => {
    state.pageSize = parseInt(pageSizeSel.value, 10) || 20;
    state.page = 1;
    renderTable(pagedRows());
    renderPager();
  });

  searchInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      state.page = 1;
      applyClientFilters();
    }
  });

  // ---- Create modal: enable/disable select boxes
  function toggleCreateTargets() {
    const t = createItemType?.value;
    if (!createMaterial || !createProduct) return;
    if (t === "RawMaterials") {
      createMaterial.disabled = false;
      createProduct.disabled  = true;  createProduct.value = "";
    } else if (t === "FinishedGoods") {
      createProduct.disabled  = false;
      createMaterial.disabled = true;  createMaterial.value = "";
    } else {
      createMaterial.disabled = false; createProduct.disabled = false;
    }
  }
  createItemType?.addEventListener("change", async () => { toggleCreateTargets(); await refreshPreview(); });

  // ---- Preview Before/After
  createTxTypeSel?.addEventListener("change", refreshPreview);
  createQtyInput?.addEventListener("input",  refreshPreview);
  createMaterial?.addEventListener("change", refreshPreview);
  createProduct?.addEventListener("change",  refreshPreview);

  // ---- Submit create (AUTHED)
  createForm?.addEventListener("submit", async (e) => {
    e.preventDefault();

    await refreshPreview();

    const fd = new FormData(createForm);
    const payload = Object.fromEntries(fd.entries());

    payload.Qty = payload.Qty ? Number(payload.Qty) : undefined;
    payload.MaterialsId = payload.MaterialsId ? Number(payload.MaterialsId) : null;
    payload.ProductId   = payload.ProductId   ? Number(payload.ProductId)   : null;

    const changedBy = getChangedBy();
    if (!changedBy) { alert("You must log in before creating a transaction (missing ChangedBy)."); return; }
    payload.ChangedBy = Number(changedBy);

    const txType = payload.TransactionType || "Import";
    const before = state.preview.beforeQty;
    const after  = state.preview.afterQty;

    if (before == null) { alert("Cannot determine current quantity of the selected item. Please try again."); return; }
    if (txType === "Export" && after < 0) {
      alert(`Export would make stock negative.\nBefore: ${before}\nQty: ${payload.Qty}\nAfter: ${after}\nPlease reduce quantity.`);
      return;
    }

    const ok = confirm(
      `Create ${txType}?\n\nItemType: ${payload.ItemType}\n` +
      `BeforeQty: ${before}\nQty: ${payload.Qty}\nAfterQty: ${after}`
    );
    if (!ok) return;

    try {
      await apiFetch(ROUTES.transactions, {
        method: "POST",
        body: JSON.stringify(payload)
      }, { auth: "access" });

      bootstrap.Modal.getInstance(document.getElementById("createModal"))?.hide();
      createForm.reset();
      toggleCreateTargets();
      state.preview.beforeQty = null;
      state.preview.afterQty  = null;
      await fetchTransactions();
    } catch (e2) {
      alert(`Create failed:\n${e2?.message || e2}`);
      if (/401|expired/i.test(String(e2))) { clearTokens(); location.href = "./login.html"; }
    }
  });

  // ---------- Init ----------
  (async function init() {
    try {
      await requireLogin(); // bắt buộc đăng nhập
      await Promise.all([loadMaterials(), loadProducts()]);
      toggleCreateTargets();
      await fetchTransactions();
    } catch (e) {
      // requireLogin đã redirect nếu fail
    }
  })();

})();
