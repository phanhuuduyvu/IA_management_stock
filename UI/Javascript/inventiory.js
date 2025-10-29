// inventory.js — Connect UI to inventory.py (CRUD + filters + modal)
// Backend defaults to http://<host>:8001; override via <body data-api-base="http://localhost:8001">

(function () {
  "use strict";

  // ================== CONFIG ==================
  const bodyEl = document.body;
  const API_BASE = bodyEl?.getAttribute("data-api-base")?.trim()
    || `${location.protocol}//${location.hostname}:8001`;

  const ROUTES = {
    inventory: `${API_BASE}/api/inventory`,
    raw: `${API_BASE}/api/raw-materials`,
    finished: `${API_BASE}/api/finished-goods`,
    health: `${API_BASE}/api/health`,
  };

  // ================== STATE + ELTS ==================
  let INVENTORY = []; // always from API
  const state = { currentPage: 1, pageSize: 12, search: "", type: "", status: "", inStockOnly: false };

  const tbody = document.querySelector("#inventoryTable tbody");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const pageIndicator = document.getElementById("pageIndicator");
  const searchInput = document.getElementById("searchInput");
  const searchBtn = document.getElementById("searchBtn");
  const typeFilter = document.getElementById("typeFilter");   // "" | "Raw" | "Finished"
  const statusFilter = document.getElementById("statusFilter"); // "" | "OK" | "Low" | "Out"
  const inStockOnly = document.getElementById("inStockOnly");
  const pageSizeSel = document.getElementById("pageSize");

  // Modal
  const modalEl = document.getElementById('materialModal');
  const modalObj = new bootstrap.Modal(modalEl, { backdrop: 'static' });
  const modalTitle = document.getElementById('materialModalTitle');
  const addBtn = document.getElementById('addBtn');
  const matName = document.getElementById('matName');
  const matType = document.getElementById('matType'); // "Raw" | "Finished"
  const matUnit = document.getElementById('matUnit'); // only for Raw
  const matQty = document.getElementById('matQty');
  const matLow = document.getElementById('matLow');
  const matNameHint = document.getElementById('matNameHint');
  const matSaveBtn = document.getElementById('matSaveBtn');

  let editMode = 'add'; // 'add' | 'edit'
  let editingKey = null;  // { id, type }

  // ================== HELPERS ==================
  async function request(url, options = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options
    });
    if (!res.ok) {
      let detail = "";
      try { const d = await res.json(); detail = d?.detail || JSON.stringify(d); } catch (_) { }
      throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
    }
    // 204 has no content
    if (res.status === 204) return null;
    return res.json();
  }

  function toast(msg, type = "info") {
    // simple bootstrap alert replacement
    console[type === "error" ? "error" : "log"]("[INFO]", msg);
  }

  // ================== API BINDINGS ==================
  async function fetchInventory() {
    const params = new URLSearchParams();
    if (state.type) params.set("type", state.type);                 // Raw | Finished
    if (state.status) params.set("status", state.status);             // OK | Low | Out
    if (state.inStockOnly) params.set("inStockOnly", "true");
    if (state.search) params.set("search", state.search.trim());

    const url = `${ROUTES.inventory}${params.toString() ? `?${params.toString()}` : ""}`;
    const data = await request(url); // response_model: List<InventoryItem>
    // convert updatedAt string -> Date for display
    INVENTORY = (Array.isArray(data) ? data : []).map(it => ({
      ...it,
      updatedAt: it.updatedAt ? new Date(it.updatedAt) : null
    }));
  }

  async function createItem(payload) {
    // payload from modal: {type, name, qty, low, unit?}
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
        // send only changed fields is okay; we send all non-null for simplicity
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
    // 1) create in NEW table
    const created = await createItem(newPayload); // { id: ... }
    const newId = created?.id;

    try {
      // 2) delete OLD
      await deleteItem(oldId, oldType);
      return { migrated: true, newId };
    } catch (err) {
      // Rollback: delete the newly-created one if old deletion failed
      try {
        await deleteItem(newId, newPayload.type);
      } catch (_) { /* swallow rollback errors */ }
      throw err;
    }
  }

  // ================== RENDERING ==================
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

  function paginate(data) { const start = (state.currentPage - 1) * state.pageSize; return data.slice(start, start + state.pageSize); }

  function badge(status) { const map = { OK: "success", Low: "warning", Out: "secondary" }; return `<span class="badge bg-${map[status] || "light"}">${status}</span>`; }

  function renderPagination(totalItems) {
    const totalPages = Math.max(1, Math.ceil(totalItems / state.pageSize));
    state.currentPage = Math.min(state.currentPage, totalPages);
    pageIndicator.textContent = `Page ${state.currentPage} of ${totalPages}`;
    prevBtn.disabled = state.currentPage <= 1;
    nextBtn.disabled = state.currentPage >= totalPages;
  }

  function renderTable() {
    const filtered = applyFilters(INVENTORY);
    const paged = paginate(filtered);
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
    renderPagination(filtered.length);
  }

  function goToPage(p) { state.currentPage = Math.max(1, p); renderTable(); }

  // ================== UI EVENTS ==================
  prevBtn.addEventListener("click", () => goToPage(state.currentPage - 1));
  nextBtn.addEventListener("click", () => goToPage(state.currentPage + 1));

  function refreshAndRender() {
    fetchInventory()
      .then(() => renderTable())
      .catch(err => { toast(err.message, "error"); });
  }

  searchBtn.addEventListener("click", (e) => { e.preventDefault(); state.search = searchInput.value; state.currentPage = 1; refreshAndRender(); });
  searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { state.search = searchInput.value; state.currentPage = 1; refreshAndRender(); } });
  typeFilter.addEventListener("change", () => { state.type = typeFilter.value; state.currentPage = 1; refreshAndRender(); });
  statusFilter.addEventListener("change", () => { state.status = statusFilter.value; state.currentPage = 1; refreshAndRender(); });
  inStockOnly.addEventListener("change", () => { state.inStockOnly = inStockOnly.checked; state.currentPage = 1; refreshAndRender(); });
  pageSizeSel.addEventListener("change", () => { state.pageSize = parseInt(pageSizeSel.value, 10) || 12; state.currentPage = 1; renderTable(); });

  // Delegated events: edit/delete
  tbody.addEventListener('click', (e) => {
    const del = e.target.closest('.btn-delete');
    if (del) {
      const id = Number(del.dataset.id);
      const type = del.dataset.type; // Raw | Finished
      if (confirm("Delete this item?")) {
        deleteItem(id, type)
          .then(() => { toast("Deleted"); refreshAndRender(); })
          .catch(err => toast(err.message, "error"));
      }
      return;
    }
    const edit = e.target.closest('.btn-edit');
    if (edit) {
      const id = Number(edit.dataset.id);
      const type = edit.dataset.type;
      const item = INVENTORY.find(x => x.id === id && x.type === type);
      if (!item) return;
      editMode = 'edit';
      editingKey = { id, type };
      modalTitle.textContent = 'Edit item';

      matName.value = item.name || '';
      matType.value = item.type; // Raw | Finished
      matQty.value = String(item.quantity ?? 0);
      matLow.value = String(item.lowStock ?? 0);
      matUnit.value = (item.type === 'Raw') ? (item.unit || '') : '';
      toggleControlsByType();
      hideHints();
      modalObj.show();
    }
  });

  // Add button
  addBtn.addEventListener('click', (e) => {
    e.preventDefault();
    editMode = 'add';
    editingKey = null;
    modalTitle.textContent = 'Add item';
    resetForm();
    modalObj.show();
  });

  // Modal helpers
  function resetForm() {
    matName.value = '';
    matType.value = 'Raw'; // default
    matUnit.value = '';
    matQty.value = '0';
    matLow.value = '0';
    hideHints();
    toggleControlsByType();
  }
  function hideHints() { matNameHint.style.display = 'none'; }
  function validate() {
    let ok = true;
    if (!matName.value.trim()) { matNameHint.style.display = 'block'; ok = false; }
    return ok;
  }
  function toggleControlsByType() {
    const isFinished = matType.value === 'Finished';
    matUnit.disabled = isFinished;
    if (isFinished) matUnit.value = '';
  }
  matType.addEventListener('change', toggleControlsByType);
  matName.addEventListener('input', hideHints);
  modalEl.addEventListener('hidden.bs.modal', resetForm);

  // Save (Create/Update)
  // Save (Create/Update) — supports changing type (Raw <-> Finished)
  matSaveBtn.addEventListener('click', () => {
    if (!validate()) return;

    const payload = {
      name: matName.value.trim(),
      type: matType.value, // Raw | Finished
      unit: matType.value === 'Raw' ? (matUnit.value.trim() || '-') : '-',
      qty: Math.max(0, parseInt(matQty.value || '0', 10)),
      low: Math.max(0, parseInt(matLow.value || '0', 10)),
    };

    // ADD mode
    if (editMode !== 'edit' || !editingKey) {
      createItem(payload)
        .then(() => {
          modalObj.hide();
          toast("Created");
          refreshAndRender();
        })
        .catch(err => toast(err.message, "error"));
      return;
    }

    // EDIT mode
    const oldId = editingKey.id;
    const oldType = editingKey.type;
    const newType = payload.type;

    // Case 1: same type -> simple UPDATE
    if (oldType === newType) {
      updateItem(oldId, oldType, payload)
        .then(() => {
          modalObj.hide();
          toast("Updated");
          refreshAndRender();
        })
        .catch(err => toast(err.message, "error"));
      return;
    }

    // Case 2: type changed -> CREATE in new table, then DELETE old (with rollback)
    const msg = `You changed Type from "${oldType}" to "${newType}". `
      + `This will create a new item in ${newType} and delete the old ${oldType} entry. Continue?`;
    if (!confirm(msg)) return;

    migrateItem(oldId, oldType, payload)
      .then(() => {
        modalObj.hide();
        toast(`Moved to ${newType}`);
        refreshAndRender();
      })
      .catch(err => toast(err.message, "error"));
  });


  // ================== INIT ==================
  // Optional: quick health check
  request(ROUTES.health).catch(() => {/* ignore */ });
  refreshAndRender();
})();
