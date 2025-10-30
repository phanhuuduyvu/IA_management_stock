// inventory.js — Connect UI to inventory.py (CRUD + filters + modal) [LOGIN REQUIRED]
// Backend defaults to http://<host>:8001; override via <body data-api-base="http://localhost:8001">

document.addEventListener("DOMContentLoaded", () => {
  "use strict";

  // =============== CONFIG =================
  const bodyEl = document.body;
  const API_BASE = bodyEl?.getAttribute("data-api-base")?.trim()
    || `${location.protocol}//${location.hostname}:8001`;

  const ROUTES = {
    inventory: `${API_BASE}/api/inventory`,
    raw:       `${API_BASE}/api/raw-materials`,
    finished:  `${API_BASE}/api/finished-goods`,
    health:    `${API_BASE}/api/health`,
    me:        `${API_BASE}/api/me`,
    login:     `${API_BASE}/api/auth/login`,
    refresh:   `${API_BASE}/api/auth/refresh`,
    logout:    `${API_BASE}/api/auth/logout`,
  };

  // =============== AUTH STORAGE KEYS =================
  const LS = {
    access: "auth.access_token",
    accessExp: "auth.access_expires_at",
    refresh: "auth.refresh_token",
    refreshExp: "auth.refresh_expires_at",
    me: "auth.me",
  };
  const EXP_LEEWAY = 30; // seconds

  // =============== TOKEN UTILS =================
  const getEpochNow = () => Math.floor(Date.now() / 1000);
  const getAT = () => localStorage.getItem(LS.access) || "";
  const getRT = () => localStorage.getItem(LS.refresh) || "";
  const isExpired = (k) => {
    const exp = Number(localStorage.getItem(k) || 0);
    return !exp || getEpochNow() >= (exp - EXP_LEEWAY);
  };
  const isAccessExpired = () => isExpired(LS.accessExp);
  const isRefreshExpired = () => isExpired(LS.refreshExp);
  const clearTokens = () => {
    localStorage.removeItem(LS.access);
    localStorage.removeItem(LS.accessExp);
    localStorage.removeItem(LS.refresh);
    localStorage.removeItem(LS.refreshExp);
    // localStorage.removeItem(LS.me); // optional
  };

  // =============== LOGOUT (same behavior as home.js) ===============
  async function doLogout(e) {
    e?.preventDefault?.();
    try {
      const at = getAT();
      if (at) {
        await fetch(ROUTES.logout, {
          method: "POST",
          headers: { "Authorization": `Bearer ${at}` },
          cache: "no-store",
        });
      }
    } catch { /* ignore network errors */ }
    clearTokens();
    location.href = "./login.html";
  }

  // Bind logout button early
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) logoutBtn.addEventListener("click", doLogout);

  // =============== REFRESH / AUTHED FETCH =================
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

  // Standard fetch with Bearer and auto-refresh on 401
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

  // BẮT BUỘC LOGIN: nếu không có refresh token/hết hạn => về login.html
  async function requireLogin() {
    if (!getRT() || isRefreshExpired()) {
      location.href = "./login.html";
      throw new Error("Redirecting to login");
    }
    // thử gọi /api/me để xác nhận
    await apiFetch(ROUTES.me, { method: "GET" }, { auth: "access" });
  }

  // =============== UI + STATE ELTS =================
  let INVENTORY = []; // always from API
  const state = { currentPage: 1, pageSize: 12, search: "", type: "", status: "", inStockOnly: false };

  const tbody         = document.querySelector("#inventoryTable tbody");
  const prevBtn       = document.getElementById("prevBtn");
  const nextBtn       = document.getElementById("nextBtn");
  const pageIndicator = document.getElementById("pageIndicator");
  const searchInput   = document.getElementById("searchInput");
  const searchBtn     = document.getElementById("searchBtn");
  const typeFilter    = document.getElementById("typeFilter");   // "" | "Raw" | "Finished"
  const statusFilter  = document.getElementById("statusFilter"); // "" | "OK" | "Low" | "Out"
  const inStockOnly   = document.getElementById("inStockOnly");
  const pageSizeSel   = document.getElementById("pageSize");

  // Modal bits
  const modalEl    = document.getElementById("materialModal");
  const modalObj   = modalEl ? new bootstrap.Modal(modalEl, { backdrop: "static" }) : null;
  const modalTitle = document.getElementById("materialModalTitle");
  const addBtn     = document.getElementById("addBtn");
  const matName    = document.getElementById("matName");
  const matType    = document.getElementById("matType");   // "Raw" | "Finished"
  const matUnit    = document.getElementById("matUnit");   // only for Raw
  const matQty     = document.getElementById("matQty");
  const matLow     = document.getElementById("matLow");
  const matNameHint= document.getElementById("matNameHint");
  const matSaveBtn = document.getElementById("matSaveBtn");

  let editMode = "add"; // 'add' | 'edit'
  let editingKey = null;  // { id, type }

  // ======= Guards: tránh null gây crash =======
  function req(el, id){
    if (!el) { console.error(`Missing element #${id}`); }
    return !!el;
  }
  if (!req(tbody, "inventoryTable tbody")) return;

  // Đảm bảo #matType có option "Raw"/"Finished"
  if (matType) {
    const hasRaw = !!matType.querySelector('option[value="Raw"]');
    const hasFin = !!matType.querySelector('option[value="Finished"]');
    if (!hasRaw || !hasFin) {
      matType.innerHTML = `
        <option value="Raw">Raw</option>
        <option value="Finished">Finished</option>
      `;
    }
  }

  // =============== HELPERS (fetch JSON with auth) ===============
  async function request(url, options = {}) {
    return apiFetch(url, options, { auth: "access" });
  }

  function toast(msg, type = "info") {
    console[type === "error" ? "error" : "log"]("[INFO]", msg);
  }

  // =============== API BINDINGS =================
  async function fetchInventory() {
    const params = new URLSearchParams();
    if (state.type) params.set("type", state.type);             // Raw | Finished
    if (state.status) params.set("status", state.status);       // OK | Low | Out
    if (state.inStockOnly) params.set("inStockOnly", "true");
    if (state.search) params.set("search", state.search.trim());

    const url = `${ROUTES.inventory}${params.toString() ? `?${params.toString()}` : ""}`;
    const data = await request(url); // List<InventoryItem>
    INVENTORY = (Array.isArray(data) ? data : []).map(it => ({
      ...it,
      updatedAt: it.updatedAt ? new Date(it.updatedAt) : null
    }));
  }

  async function createItem(payload) {
    if (payload.type === "Raw") {
      const body = {
        MaterialName: payload.name,
        MaterialQuantity: payload.qty,
        Lowstock: payload.low,
        Unit: payload.unit || "-"
      };
      return request(ROUTES.raw, { method: "POST", body: JSON.stringify(body) });
    } else {
      const body = {
        FinishedGoodsName: payload.name,
        FinishedGoodsQuantity: payload.qty,
        Lowstock: payload.low
      };
      return request(ROUTES.finished, { method: "POST", body: JSON.stringify(body) });
    }
  }

  async function updateItem(id, type, payload) {
    if (type === "Raw") {
      const body = {
        MaterialName: payload.name,
        MaterialQuantity: payload.qty,
        Lowstock: payload.low,
        Unit: payload.unit || "-"
      };
      return request(`${ROUTES.raw}/${id}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      const body = {
        FinishedGoodsName: payload.name,
        FinishedGoodsQuantity: payload.qty,
        Lowstock: payload.low
      };
      return request(`${ROUTES.finished}/${id}`, { method: "PUT", body: JSON.stringify(body) });
    }
  }

  async function deleteItem(id, type) {
    const url = (type === "Raw") ? `${ROUTES.raw}/${id}` : `${ROUTES.finished}/${id}`;
    return request(url, { method: "DELETE" });
  }

  async function migrateItem(oldId, oldType, newPayload) {
    const created = await createItem(newPayload); // { id: ... }
    const newId = created?.id;
    try {
      await deleteItem(oldId, oldType);
      return { migrated: true, newId };
    } catch (err) {
      try { await deleteItem(newId, newPayload.type); } catch (_) {}
      throw err;
    }
  }

  // =============== RENDERING ===============
  function applyFilters(data) {
    const s = state.search.trim().toLowerCase();
    return data.filter(item => {
      if (s && !(`${item.name} ${item.code}`.toLowerCase().includes(s))) return false;
      if (state.type && item.type !== state.type) return false;
      if (state.status && item.status !== state.status) return false;
      if (state.inStockOnly && item.quantity <= 0) return false;
      return true;
    });
  }

  function paginate(data) {
    const start = (state.currentPage - 1) * state.pageSize;
    return data.slice(start, start + state.pageSize);
  }

  function badge(status) {
    const map = { OK: "success", Low: "warning", Out: "secondary" };
    return `<span class="badge bg-${map[status] || "light"}">${status}</span>`;
  }

  function renderPagination(totalItems) {
    const totalPages = Math.max(1, Math.ceil(totalItems / state.pageSize));
    state.currentPage = Math.min(state.currentPage, totalPages);
    if (pageIndicator) pageIndicator.textContent = `Page ${state.currentPage} of ${totalPages}`;
    if (prevBtn) prevBtn.disabled = state.currentPage <= 1;
    if (nextBtn) nextBtn.disabled = state.currentPage >= totalPages;
  }

  function renderTable() {
    const filtered = applyFilters(INVENTORY);
    const paged = paginate(filtered);
    if (tbody) {
      tbody.innerHTML = paged.map(item => `
        <tr>
          <td>${item.code}</td>
          <td>${item.name}<br><small class="text-muted">Type: ${item.type} • ${badge(item.status)}</small></td>
          <td class="text-end">${Number(item.quantity || 0).toLocaleString()}</td>
          <td>${item.unit || "-"}</td>
          <td>${item.lowStock ?? 0}</td>
          <td>${item.updatedAt ? new Date(item.updatedAt).toLocaleString() : "-"}</td>
          <td class="text-center">
            <button class="btn btn-sm btn-outline-primary btn-edit" data-id="${item.id}" data-type="${item.type}">
              <i class="bi bi-pencil-square"></i>
            </button>
          </td>
          <td class="text-center">
            <button class="btn btn-sm btn-outline-danger btn-delete" data-id="${item.id}" data-type="${item.type}">
              <i class="bi bi-trash"></i>
            </button>
          </td>
        </tr>
      `).join("");
    }
    renderPagination(filtered.length);
  }

  function goToPage(p) { state.currentPage = Math.max(1, p); renderTable(); }

  // =============== UI EVENTS ===============
  if (prevBtn) prevBtn.addEventListener("click", () => goToPage(state.currentPage - 1));
  if (nextBtn) nextBtn.addEventListener("click", () => goToPage(state.currentPage + 1));

  function refreshAndRender() {
    fetchInventory()
      .then(renderTable)
      .catch(err => {
        toast(err.message, "error");
        if (/401|expired/i.test(err.message)) {
          clearTokens();
          location.href = "./login.html";
        }
      });
  }

  if (searchBtn) searchBtn.addEventListener("click", (e) => {
    e.preventDefault(); state.search = (searchInput?.value || ""); state.currentPage = 1; refreshAndRender();
  });
  if (searchInput) searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { state.search = (searchInput.value || ""); state.currentPage = 1; refreshAndRender(); }
  });
  if (typeFilter) typeFilter.addEventListener("change", () => { state.type = typeFilter.value; state.currentPage = 1; refreshAndRender(); });
  if (statusFilter) statusFilter.addEventListener("change", () => { state.status = statusFilter.value; state.currentPage = 1; refreshAndRender(); });
  if (inStockOnly) inStockOnly.addEventListener("change", () => { state.inStockOnly = inStockOnly.checked; state.currentPage = 1; refreshAndRender(); });
  if (pageSizeSel) pageSizeSel.addEventListener("change", () => { state.pageSize = parseInt(pageSizeSel.value, 10) || 12; state.currentPage = 1; renderTable(); });

  // Delegated events: edit/delete
  if (tbody) tbody.addEventListener("click", (e) => {
    const del = e.target.closest?.(".btn-delete");
    if (del) {
      const id = Number(del.dataset.id);
      const type = del.dataset.type; // Raw | Finished
      if (confirm("Delete this item?")) {
        deleteItem(id, type)
          .then(() => { toast("Deleted"); refreshAndRender(); })
          .catch(err => {
            toast(err.message, "error");
            if (/401|expired/i.test(err.message)) { clearTokens(); location.href="./login.html"; }
          });
      }
      return;
    }
    const edit = e.target.closest?.(".btn-edit");
    if (edit) {
      const id = Number(edit.dataset.id);
      const type = edit.dataset.type;
      const item = INVENTORY.find(x => x.id === id && x.type === type);
      if (!item) return;
      editMode = "edit";
      editingKey = { id, type };
      if (modalTitle) modalTitle.textContent = "Edit item";

      if (matName) matName.value = item.name || "";
      if (matType) matType.value = item.type; // Raw | Finished
      if (matQty)  matQty.value  = String(item.quantity ?? 0);
      if (matLow)  matLow.value  = String(item.lowStock ?? 0);
      if (matUnit) matUnit.value = (item.type === "Raw") ? (item.unit || "") : "";

      toggleControlsByType();
      hideHints();
      modalObj?.show();
    }
  });

  // Add button
  if (addBtn) addBtn.addEventListener("click", (e) => {
    e.preventDefault();
    editMode = "add";
    editingKey = null;
    if (modalTitle) modalTitle.textContent = "Add item";
    resetForm();
    modalObj?.show();
  });

  // Modal helpers
  function resetForm() {
    if (matName) matName.value = "";
    if (matType) matType.value = "Raw";
    if (matUnit) matUnit.value = "";
    if (matQty)  matQty.value  = "0";
    if (matLow)  matLow.value  = "0";
    hideHints();
    toggleControlsByType();
  }
  function hideHints() { if (matNameHint) matNameHint.style.display = "none"; }
  function validate() {
    let ok = true;
    if (!matName?.value.trim()) { if (matNameHint) matNameHint.style.display = "block"; ok = false; }
    return ok;
  }
  function toggleControlsByType() {
    const isFinished = matType?.value === "Finished";
    if (matUnit) {
      matUnit.disabled = !!isFinished;
      if (isFinished) matUnit.value = "";
    }
  }
  if (matType) matType.addEventListener("change", toggleControlsByType);
  if (matName) matName.addEventListener("input", hideHints);
  if (modalEl) modalEl.addEventListener("hidden.bs.modal", resetForm);

  // Save (Create/Update) — supports changing type (Raw <-> Finished)
  if (matSaveBtn) matSaveBtn.addEventListener("click", () => {
    if (!validate()) return;

    const payload = {
      name: matName?.value.trim(),
      type: matType?.value, // Raw | Finished
      unit: (matType?.value === "Raw") ? ((matUnit?.value.trim() || "-")) : "-",
      qty: Math.max(0, parseInt(matQty?.value || "0", 10)),
      low: Math.max(0, parseInt(matLow?.value || "0", 10)),
    };

    const after = () => { modalObj?.hide(); refreshAndRender(); };

    if (editMode !== "edit" || !editingKey) {
      createItem(payload)
        .then(() => { toast("Created"); after(); })
        .catch(err => {
          toast(err.message, "error");
          if (/401|expired/i.test(err.message)) { clearTokens(); location.href="./login.html"; }
        });
      return;
    }

    const oldId = editingKey.id;
    const oldType = editingKey.type;
    const newType = payload.type;

    if (oldType === newType) {
      updateItem(oldId, oldType, payload)
        .then(() => { toast("Updated"); after(); })
        .catch(err => {
          toast(err.message, "error");
          if (/401|expired/i.test(err.message)) { clearTokens(); location.href="./login.html"; }
        });
      return;
    }

    const msg = `You changed Type from "${oldType}" to "${newType}". `
      + `This will create a new item in ${newType} and delete the old ${oldType} entry. Continue?`;
    if (!confirm(msg)) return;

    migrateItem(oldId, oldType, payload)
      .then(() => { toast(`Moved to ${newType}`); after(); })
      .catch(err => {
        toast(err.message, "error");
        if (/401|expired/i.test(err.message)) { clearTokens(); location.href="./login.html"; }
      });
  });

  // =============== INIT (LOGIN CHECK FIRST) ===============
  (async () => {
    try {
      await requireLogin();               // ⟵ bắt buộc đăng nhập
      await apiFetch(ROUTES.health).catch(()=>{});
      // (Optional) paint user name if you have a #greetName on this page
      try {
        const me = await apiFetch(ROUTES.me, { method: "GET" }, { auth: "access" });
        localStorage.setItem(LS.me, JSON.stringify(me || {}));
        const greet = document.querySelector("#greetName");
        if (greet) {
          const name = me?.full_name || me?.username || me?.email || "User";
          greet.textContent = `${name}`;
        }
      } catch { /* ignore */ }

      refreshAndRender();
    } catch (e) {
      // requireLogin đã redirect; ở đây chỉ dự phòng
    }
  })();
});
