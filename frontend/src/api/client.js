const ACCESS_KEY = "av_access_token";
const REFRESH_KEY = "av_refresh_token";
const REMEMBER_KEY = "av_remember";

export function storageForRemember(remember) {
  return remember ? localStorage : sessionStorage;
}

export function getAccessToken() {
  return sessionStorage.getItem(ACCESS_KEY) || localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken() {
  return sessionStorage.getItem(REFRESH_KEY) || localStorage.getItem(REFRESH_KEY);
}

export function setTokens({ access_token, refresh_token }, remember = false) {
  clearTokens();
  const store = storageForRemember(remember);
  store.setItem(ACCESS_KEY, access_token);
  if (refresh_token) store.setItem(REFRESH_KEY, refresh_token);
  if (remember) localStorage.setItem(REMEMBER_KEY, "1");
  else sessionStorage.setItem(REMEMBER_KEY, "1");
}

export function clearTokens() {
  for (const store of [localStorage, sessionStorage]) {
    store.removeItem(ACCESS_KEY);
    store.removeItem(REFRESH_KEY);
    store.removeItem(REMEMBER_KEY);
  }
}

export function rememberEnabled() {
  return localStorage.getItem(REMEMBER_KEY) === "1";
}

export function formatDetail(payload) {
  if (!payload) return "Ошибка запроса";
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || item?.detail || JSON.stringify(item))
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return payload.message || "Ошибка запроса";
}

export class ApiError extends Error {
  constructor(status, detail, payload) {
    super(detail);
    this.status = status;
    this.payload = payload;
  }
}

let refreshPromise = null;

function isAuthTokenError(payload) {
  const detail = typeof payload?.detail === "string" ? payload.detail : "";
  if (/неверн.*парол/i.test(detail)) return false;
  if (/учётные данные dzz/i.test(detail)) return false;
  if (/нет сессии dzz/i.test(detail)) return false;
  if (/user inactive/i.test(detail)) return false;
  return true;
}

async function parseBody(res) {
  if (res.status === 204 || res.status === 205) return null;
  const ct = (res.headers.get("content-type") || "").toLowerCase();
  if (ct.includes("application/json") || ct.includes("application/geo+json")) {
    const text = await res.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return { detail: text };
    }
  }
  if (!res.ok) {
    const text = await res.text();
    return text ? { detail: text } : null;
  }
  return res.blob();
}

async function rawFetch(path, options = {}, { skipAuth = false, skipRefresh = false } = {}) {
  const headers = new Headers(options.headers || {});
  if (!skipAuth) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...options, headers });
  const payload = await parseBody(res);
  if (res.status === 401 && !skipRefresh && !skipAuth && isAuthTokenError(payload)) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return rawFetch(path, options, { skipAuth, skipRefresh: true });
  }
  if (!res.ok) {
    const detail = formatDetail(payload) || `HTTP ${res.status}`;
    throw new ApiError(res.status, detail, payload);
  }
  return payload;
}

export async function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;
  const refresh = getRefreshToken();
  if (!refresh) {
    clearTokens();
    return false;
  }
  refreshPromise = (async () => {
    try {
      const payload = await rawFetch(
        "/api/v1/auth/refresh",
        { method: "POST", body: JSON.stringify({ refresh_token: refresh }) },
        { skipAuth: true, skipRefresh: true },
      );
      setTokens(payload, rememberEnabled());
      return true;
    } catch {
      clearTokens();
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export function api(path, options) {
  return rawFetch(path, options);
}

export function apiNoAuth(path, options) {
  return rawFetch(path, options, { skipAuth: true, skipRefresh: true });
}

export function apiForm(path, form, method = "POST") {
  return rawFetch(path, { method, body: form });
}
