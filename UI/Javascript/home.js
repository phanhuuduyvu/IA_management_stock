
// ======================
// Auth + Me loader (top)
// ======================
(function () {
  "use strict";

  // ----- API config (same as login.js) -----
  const API_BASE = `${location.protocol}//${location.hostname}:8001`;
  const ROUTES = {
    login: `${API_BASE}/api/auth/login`,
    refresh: `${API_BASE}/api/auth/refresh`,
    me: `${API_BASE}/api/me`,
    logout: `${API_BASE}/api/auth/logout`,
  };

  // ----- Storage keys -----
  const LS = {
    access: "auth.access_token",
    accessExp: "auth.access_expires_at",
    refresh: "auth.refresh_token",
    refreshExp: "auth.refresh_expires_at",
    me: "auth.me",
  };
  const EXP_LEEWAY = 30; // expiration leeway (seconds)

  const $ = (s) => document.querySelector(s);

  // ----- Token utils -----
  const getEpochNow = () => Math.floor(Date.now() / 1000);
  const getAT = () => localStorage.getItem(LS.access) || "";
  const getRT = () => localStorage.getItem(LS.refresh) || "";
  const isAccessExpired = () => {
    const exp = Number(localStorage.getItem(LS.accessExp) || 0);
    return !exp || getEpochNow() >= (exp - EXP_LEEWAY);
  };
  const isRefreshExpired = () => {
    const exp = Number(localStorage.getItem(LS.refreshExp) || 0);
    return !exp || getEpochNow() >= (exp - EXP_LEEWAY);
  };
  const clearTokens = () => {
    localStorage.removeItem(LS.access);
    localStorage.removeItem(LS.accessExp);
    localStorage.removeItem(LS.refresh);
    localStorage.removeItem(LS.refreshExp);
    // Optionally remove LS.me too:
    // localStorage.removeItem(LS.me);
  };

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
      const data = await (async () => { try { return await res.json(); } catch { return null; } })();
      refreshing = null;
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);

      // update tokens
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
    if (isRefreshExpired()) throw new Error("Session expired.");
    await refreshAccessToken();
  }

  async function apiFetch(url, options = {}, { auth = "access", retryOn401 = true } = {}) {
    const base = new Headers({ Accept: "application/json" });
    const user = new Headers(options.headers || {});
    const headers = new Headers([...base, ...user]);

    const opts = {
      method: "GET",
      ...options,
      headers,
      cache: "no-store",
    };

    if (opts.body && !(opts.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    if (auth === "access") {
      await ensureAccessToken();
      const at = getAT();
      if (at) headers.set("Authorization", `Bearer ${at}`);
    }

    let res = await fetch(url, opts);

    if (res.status === 401 && auth === "access" && retryOn401) {
      try {
        if (!isRefreshExpired()) {
          await refreshAccessToken();
          // retry with fresh header
          const retryHeaders = new Headers({ Accept: "application/json" });
          const at2 = getAT();
          if (at2) retryHeaders.set("Authorization", `Bearer ${at2}`);
          res = await fetch(url, { method: opts.method, body: opts.body, headers: retryHeaders, cache: "no-store" });
        }
      } catch { /* fallthrough */ }
    }

    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await res.json().catch(() => null) : null;
    if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
    return data;
  }

  // ----- Load user on page -----
  async function loadMeOrRedirect() {
    try {
      // if no refresh token => go to login
      if (!getRT() || isRefreshExpired()) {
        location.href = "./login.html";
        return;
      }
      // show cached user immediately if available
      const cached = (() => { try { return JSON.parse(localStorage.getItem(LS.me) || "{}"); } catch { return {}; } })();
      if (cached?.username || cached?.email) {
        paintUser(cached);
      }
      // fetch user from API (accurate)
      const me = await apiFetch(ROUTES.me, { method: "GET" }, { auth: "access" });
      localStorage.setItem(LS.me, JSON.stringify(me || {}));
      paintUser(me);
    } catch (e) {
      // token error => go to login
      clearTokens();
      location.href = "./login.html";
    }
  }

  function paintUser(me) {
    const greet = $("#greetName");
    if (greet) {
      const name = me?.full_name || me?.username || me?.email || "User";
      greet.textContent = `${name}`;
    }
  }

  // ----- Logout wiring -----
  async function doLogout(e) {
    e?.preventDefault?.();
    try {
      const at = getAT();
      if (at) {
        await fetch(ROUTES.logout, { method: "POST", headers: { "Authorization": `Bearer ${at}` } });
      }
    } catch { /* ignore network errors */ }
    clearTokens();
    location.href = "./login.html";
  }

  document.addEventListener("DOMContentLoaded", () => {
    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) logoutBtn.addEventListener("click", doLogout);
    loadMeOrRedirect();
  });
})();

// ======================
// Your existing UI code
// (unchanged, runs after DOM ready)
// ======================
document.addEventListener("DOMContentLoaded", function () {
  const signup_btn = document.querySelector(".custom-signup");
  if (signup_btn) {
    signup_btn.addEventListener("click", function (e) {
      e.preventDefault();
      alert("Redirecting to sign-up");
    });
  }

  // ==== PIE CHART ====
  const pieEl = document.getElementById("pieChart");
  if (pieEl) {
    const pieChart = new Chart(pieEl.getContext("2d"), {
      type: "pie",
      data: {
        labels: ["2 weeks before", "Last week", "This week"],
        datasets: [
          {
            label: "Current visits",
            data: [24.7, 18.3, 31.5],
            backgroundColor: ["rgb(201, 38, 38)", "rgb(46, 230, 43)", "rgb(27, 51, 208)"],
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "bottom" } },
      },
    });
  }

  // ==== SHARED CHART OPTIONS ====
  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        position: "top",
        align: "center",
        labels: { usePointStyle: true, font: { size: 12 } },
      },
      tooltip: { enabled: true },
    },
    layout: { padding: 0 },
  };

  // ==== LINE CHART ====
  const lineCanvas = document.getElementById("lineChart");
  if (lineCanvas) {
    new Chart(lineCanvas.getContext("2d"), {
      type: "line",
      data: {
        labels: getLastSevenMonths(),
        datasets: [
          { label: "Team A", data: getRandomValue(), borderColor: "rgb(156, 93, 93)", backgroundColor: "#5b88bd", fill: true, tension: 0.35, pointRadius: 3 },
          { label: "Team B", data: getRandomValue(), borderColor: "rgba(11, 11, 8, 0.47)", backgroundColor: "rgb(88, 231, 122)", fill: true, tension: 0.35, pointRadius: 3 },
        ],
      },
      options: { ...baseOptions, scales: { x: { grid: { display: false } }, y: { beginAtZero: true } } },
    });
  }

  // ==== RADAR CHART ====
  const radarCanvas = document.getElementById("radarChart");
  if (radarCanvas) {
    const radarCtx = radarCanvas.getContext("2d");
    new Chart(radarCtx, {
      type: "radar",
      data: {
        labels: ["English", "History", "Physics", "Geography", "Chinese", "Math"],
        datasets: [
          { label: "Series 1", data: [80, 40, 30, 50, 90, 50], backgroundColor: "rgba(33, 117, 255, 0.3)", borderColor: "blue", pointBackgroundColor: "blue" },
          { label: "Series 2", data: [20, 60, 90, 10, 30, 70], backgroundColor: "rgba(255, 180, 26, 0.3)", borderColor: "orange", pointBackgroundColor: "orange" },
          { label: "Series 3", data: [50, 70, 60, 80, 30, 40], backgroundColor: "rgba(44, 188, 224, 0.3)", borderColor: "cyan", pointBackgroundColor: "cyan" },
        ],
      },
      options: { ...baseOptions, scales: { r: { beginAtZero: true, min: 0, max: 100 } } },
    });
  }

  // ==== Filter table ====
  const searchInput = document.getElementById("search");
  const statusFilter = document.getElementById("statusFilter");
  const tableRows = document.querySelectorAll("#dataTable tbody tr");
  if (searchInput && statusFilter) {
    function filterTable() {
      const searchValue = searchInput.value.toLowerCase();
      const statusValue = statusFilter.value;
      tableRows.forEach((row) => {
        const cells = row.getElementsByTagName("td");
        const matchesSearch = cells[1].textContent.toLowerCase().includes(searchValue);
        const matchesStatus = statusValue === "" || cells[2].textContent === statusValue;
        row.style.display = matchesSearch && matchesStatus ? "" : "none";
      });
    }
    searchInput.addEventListener("input", filterTable);
    statusFilter.addEventListener("change", filterTable);
  }

  // ==== Search items ====
  const searchAddedItems = document.getElementById("searchAddedItems");
  if (searchAddedItems) {
    searchAddedItems.addEventListener("input", function (e) {
      const searchValue = e.target.value.toLowerCase();
      document.querySelectorAll("#addedItemsTable tbody tr").forEach((row) => {
        const nameCell = row.querySelector("td");
        row.style.display = nameCell && nameCell.textContent.toLowerCase().includes(searchValue) ? "" : "none";
      });
    });
  }

  // ==== Add item ====
  const addItemForm = document.getElementById("addItemForm");
  if (addItemForm) {
    addItemForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const name = document.getElementById("newItemName").value.trim();
      const quantity = document.getElementById("newItemQuantity").value.trim();
      if (name && quantity) {
        const tbody = document.querySelector("#addedItemsTable tbody");
        const newRow = document.createElement("tr");
        newRow.innerHTML = `<td>${name}</td><td>${quantity}</td><td>0</td><td>0</td>`;
        tbody.appendChild(newRow);
        addItemForm.reset();
      }
    });
  }
});

// ==== Utils ====
function getLastSevenMonths() {
  const labels = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    labels.push(d.toLocaleString("en-US", { month: "short" }));
  }
  return labels;
}

function getRandomValue() {
  const random = [];
  for (let i = 0; i <= 6; i++) {
    random.push(Math.floor(Math.random() * 201));
  }
  return random;
}