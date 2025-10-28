// ======================================
// login.js – Connect Bootstrap form to FastAPI JWT backend
// Works with endpoints:
//   POST /api/auth/login        -> { access_token, access_expires_at, refresh_token, refresh_expires_at }
//   POST /api/auth/refresh      -> { access_token, ..., refresh_token, ... }
//   GET  /api/me                -> user profile (requires Bearer access token)
//   POST /api/auth/logout       -> revokes current access token (requires Bearer access token)
// ======================================

(async () => {
    "use strict";

    // -----------------------------
    // Configuration
    // -----------------------------
    // const API_BASE = "http://localhost:8001";
    const API_BASE = `${location.protocol}//${location.hostname}:8001`;


    const ROUTES = {
        login: `${API_BASE}/api/auth/login`,
        refresh: `${API_BASE}/api/auth/refresh`,
        me: `${API_BASE}/api/me`,
        logout: `${API_BASE}/api/auth/logout`,
    };

    // Storage keys
    const LS_KEYS = {
        accessToken: "auth.access_token",
        accessExp: "auth.access_expires_at", // epoch seconds
        refreshToken: "auth.refresh_token",
        refreshExp: "auth.refresh_expires_at", // epoch seconds
    };

    // Leeway for expiration checks (seconds)
    const EXP_LEEWAY = 30;

    // -----------------------------
    // DOM helpers
    // -----------------------------
    const $ = (sel) => document.querySelector(sel);

    // Footer year
    const yearEl = $("#year");
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    // Password toggler
    const togglePwd = $("#togglePwd");
    const pwd = $("#password");
    if (togglePwd && pwd) {
        const setPwdVisible = (visible) => {
            pwd.type = visible ? "text" : "password";
            togglePwd.innerHTML = `<i class="bi ${visible ? "bi-eye-slash" : "bi-eye"}"></i>`;
            togglePwd.setAttribute("aria-label", visible ? "Hide password" : "Show password");
            togglePwd.setAttribute("aria-pressed", String(visible));
        };
        togglePwd.addEventListener("click", () => setPwdVisible(pwd.type === "password"));
        setPwdVisible(false);
    }

    // Create or reuse a small alert area above the form button
    function ensureAlertHost() {
        let host = $("#login-alert-host");
        if (!host) {
            host = document.createElement("div");
            host.id = "login-alert-host";
            const form = $("#loginForm");
            const btnRow = form?.querySelector(".text-center");
            if (btnRow && btnRow.parentNode) {
                btnRow.parentNode.insertBefore(host, btnRow); // insert before submit button row
            } else if (form) {
                form.appendChild(host);
            }
        }
        return host;
    }

    function showAlert(message, type = "danger") {
        const host = ensureAlertHost();
        host.innerHTML = `
      <div class="alert alert-${type} d-flex align-items-start" role="alert">
        <i class="bi ${type === "success" ? "bi-check-circle" : "bi-exclamation-triangle"} me-2"></i>
        <div>${escapeHtml(message)}</div>
      </div>`;
    }

    function clearAlert() {
        const host = $("#login-alert-host");
        if (host) host.innerHTML = "";
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[ch]));
    }

    // -----------------------------
    // Token storage utilities
    // -----------------------------
    function setTokens(tp) {
        // tp: TokenPairResponse
        localStorage.setItem(LS_KEYS.accessToken, tp.access_token);
        localStorage.setItem(LS_KEYS.accessExp, String(tp.access_expires_at));
        localStorage.setItem(LS_KEYS.refreshToken, tp.refresh_token);
        localStorage.setItem(LS_KEYS.refreshExp, String(tp.refresh_expires_at));
    }

    function getAccessToken() {
        return localStorage.getItem(LS_KEYS.accessToken) || "";
    }

    function getRefreshToken() {
        return localStorage.getItem(LS_KEYS.refreshToken) || "";
    }

    function getEpochNow() {
        return Math.floor(Date.now() / 1000);
    }

    function isAccessExpired() {
        const exp = Number(localStorage.getItem(LS_KEYS.accessExp) || "0");
        if (!exp) return true;
        return getEpochNow() >= (exp - EXP_LEEWAY);
    }

    function isRefreshExpired() {
        const exp = Number(localStorage.getItem(LS_KEYS.refreshExp) || "0");
        if (!exp) return true;
        return getEpochNow() >= (exp - EXP_LEEWAY);
    }

    function clearTokens() {
        localStorage.removeItem(LS_KEYS.accessToken);
        localStorage.removeItem(LS_KEYS.accessExp);
        localStorage.removeItem(LS_KEYS.refreshToken);
        localStorage.removeItem(LS_KEYS.refreshExp);
    }

    // -----------------------------
    // Fetch wrapper with auto-refresh
    // -----------------------------
    let refreshing = null; // Promise guard to avoid parallel refresh storms


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
            if (isAccessExpired()) await ensureAccessToken();
            const at = getAccessToken();
            if (at) headers.set("Authorization", `Bearer ${at}`);
        }

        let res = await fetch(url, opts);

        if (res.status === 401 && auth === "access" && retryOn401) {

            const refreshed = await tryRefreshOnce();
            if (refreshed) {
                const retryHeaders = new Headers({ Accept: "application/json" });
                if (options.headers) {

                    for (const [k, v] of Object.entries(options.headers)) {
                        if (String(k).toLowerCase() !== "authorization") retryHeaders.set(k, v);
                    }
                }
                const at2 = getAccessToken();
                if (at2) retryHeaders.set("Authorization", `Bearer ${at2}`);

                res = await fetch(url, {
                    method: opts.method || "GET",
                    body: opts.body || undefined,
                    headers: retryHeaders,
                    cache: "no-store",
                });
            }
        }

        const ct = res.headers.get("content-type") || "";
        const data = ct.includes("application/json") ? await res.json().catch(() => null) : null;
        if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
        return data;
    }
    function dbgToken(tag) {
        try {
            const t = getAccessToken();
            const p = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
            console.debug(`[${tag}] sub=${p.sub} jti=${p.jti} exp=${p.exp} now=${Math.floor(Date.now() / 1000)}`);
        } catch { console.debug(`[${tag}] no token`); }
    }



    async function ensureAccessToken() {

        if (!isAccessExpired()) return;

        if (isRefreshExpired()) {
            throw new Error("Session expired. Please log in again.");
        }

        await refreshAccessToken();
    }

    async function tryRefreshOnce() {
        try {
            if (isRefreshExpired()) return false;
            await refreshAccessToken();
            return true;
        } catch {
            return false;
        }
    }

    async function refreshAccessToken() {
        // Debounce concurrent refresh calls
        if (refreshing) return refreshing;

        const token = getRefreshToken();
        if (!token) throw new Error("Missing refresh token");

        refreshing = (async () => {
            const res = await fetch(ROUTES.refresh, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({ refresh_token: token }),
            });

            const data = await (async () => {
                try { return await res.json(); } catch { return null; }
            })();

            refreshing = null; // clear guard

            if (!res.ok) {
                const detail = data?.detail || `HTTP ${res.status}`;
                throw new Error(detail);
            }

            // Save new pair (rotation)
            setTokens(data);
            return true;
        })();

        return refreshing;
    }

    // -----------------------------
    // UI: form wiring
    // -----------------------------
    const form = $("#loginForm");
    const btn = $("#loginBtn");
    const usernameEl = $("#username");
    const passwordEl = $("#password");

    function setLoading(loading) {
        if (!btn || !form) return;
        const btnText = btn.querySelector(".btn-text");
        const spinner = btn.querySelector(".spinner-border");
        btn.disabled = loading;
        btn.setAttribute("aria-disabled", String(loading));
        form.setAttribute("aria-busy", String(loading));
        if (spinner) spinner.classList.toggle("d-none", !loading);
        if (btnText) btnText.classList.toggle("d-none", loading);
    }

    function setFieldInvalid(input, invalid, message) {
        if (!input) return;
        input.classList.toggle("is-invalid", invalid);
        const fb = input.parentElement?.querySelector(".invalid-feedback") || input.nextElementSibling;
        if (fb && fb.classList && fb.classList.contains("invalid-feedback") && message) {
            fb.textContent = message;
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        clearAlert();

        // Trigger constraint validation
        if (!form.checkValidity()) {
            e.stopPropagation();
            form.classList.add("was-validated");
            return;
        }

        // Basic client checks
        const identifier = (usernameEl?.value || "").trim();
        const password = passwordEl?.value || "";

        // Clean invalid states
        setFieldInvalid(usernameEl, false);
        setFieldInvalid(passwordEl, false);

        setLoading(true);
        try {
            // Call login
            const tp = await apiFetch(
                ROUTES.login,
                {
                    method: "POST",
                    body: JSON.stringify({ identifier, password }),
                },
                { auth: "none" }
            );

            setTokens(tp);

            const me = await apiFetch(ROUTES.me, { method: "GET" }, { auth: "access" });
            localStorage.setItem("auth.me", JSON.stringify(me || {}));

            window.location.href = "./home.html";


            form.reset();
            form.classList.remove("was-validated");
            // Reset password visibility & icon
            if (pwd && togglePwd) {
                pwd.type = "password";
                togglePwd.innerHTML = `<i class="bi bi-eye"></i>`;
                togglePwd.setAttribute("aria-label", "Show password");
                togglePwd.setAttribute("aria-pressed", "false");
            }
        } catch (err) {
            // Map common errors to fields/alerts
            const msg = String(err?.message || err || "Login failed");
            if (/Invalid credentials/i.test(msg)) {
                setFieldInvalid(usernameEl, true, "Invalid username or email.");
                setFieldInvalid(passwordEl, true, "Invalid password.");
                showAlert("Invalid username/email or password.");
            } else if (/inactive/i.test(msg)) {
                showAlert("Your account is inactive. Please contact support.");
            } else {
                showAlert(msg);
            }
        } finally {
            setLoading(false);
        }
    }

    if (form && btn) {
        form.addEventListener("submit", handleSubmit);
    }

    // Optional: "Forgot password" click wiring (placeholder)
    const forgotLink = $("#forgotLink");
    if (forgotLink) {
        forgotLink.addEventListener("click", (e) => {
            e.preventDefault();
            showAlert("Please contact admin to reset your password.", "info");
        });
    }

    // -----------------------------
    // Expose small helpers globally (optional)
    // -----------------------------
    window.AuthClient = {
        // Call when user clicks a logout button (if you add one later)
        async logout() {
            try {
                const at = getAccessToken();
                if (!at) {
                    clearTokens();
                    return;
                }
                await apiFetch(
                    ROUTES.logout,
                    { method: "POST", headers: { "Authorization": `Bearer ${at}` } },
                    { auth: "none" }
                );
            } catch {
                // ignore network errors on logout
            } finally {
                clearTokens();
            }
        },

        // Example of an authenticated GET using the wrapper
        async getMe() {
            return apiFetch(ROUTES.me, { method: "GET" }, { auth: "access" });
        }
    };

    try {
        const hasRT = !!getRefreshToken();
        const notExpired = !isRefreshExpired();
        if (hasRT && notExpired) {
            dbgToken('before-me');
            await apiFetch(ROUTES.me, { method: 'GET' }, { auth: 'access' });
        }
    } catch { /* swallow */ }
})();
