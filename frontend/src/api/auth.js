import { api, setTokens, clearTokens, getRefreshToken } from "./client.js";

export function login(email, password, rememberMe) {
  return api("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, remember_me: !!rememberMe }),
  }).then((tokens) => {
    setTokens(tokens, !!rememberMe);
    return tokens;
  });
}

export function register(payload) {
  return api("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then((tokens) => {
    setTokens(tokens, false);
    return tokens;
  });
}

export async function logout() {
  const refresh = getRefreshToken();
  try {
    if (refresh) {
      await api("/api/v1/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: refresh }),
      });
    }
  } finally {
    clearTokens();
  }
}

export function requestPasswordReset(email) {
  return api("/api/v1/auth/password-reset/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function confirmPasswordReset(payload) {
  return api("/api/v1/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getMe() {
  return api("/api/v1/users/me");
}

export function patchMe(payload) {
  return api("/api/v1/users/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteMe() {
  return api("/api/v1/users/me", { method: "DELETE" });
}
