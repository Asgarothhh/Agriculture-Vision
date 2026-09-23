import { getAccessToken } from "../api/client.js";
import * as authApi from "../api/auth.js";
import { $, closeAppModal, initials, openAppModal, setFormError, showForm, showScreen, showToast } from "../ui.js";

let currentUser = null;
let onReady = () => {};
let onLogout = () => {};

export function getCurrentUser() {
  return currentUser;
}

export function setAuthCallbacks({ ready, logout }) {
  onReady = ready || onReady;
  onLogout = logout || onLogout;
}

export function applyUser(user) {
  currentUser = user;
  const name = `${user.first_name || ""} ${user.last_name || ""}`.trim();
  const av = initials(user.first_name, user.last_name);
  const side = $("sidebar-avatar");
  const card = $("card-avatar");
  if (side) side.textContent = av;
  if (card) card.textContent = av;
  if ($("user-display-name")) $("user-display-name").textContent = name || user.email;
  if ($("user-display-role-org")) {
    $("user-display-role-org").textContent = [user.role, user.organization].filter(Boolean).join(" · ");
  }
  if ($("prof-name")) $("prof-name").value = user.first_name || "";
  if ($("prof-lastname")) $("prof-lastname").value = user.last_name || "";
  if ($("prof-email")) $("prof-email").value = user.email || "";
  if ($("prof-org")) $("prof-org").value = user.organization || "";
  if ($("prof-role")) $("prof-role").value = user.role || "";
  if ($("stat-exports")) $("stat-exports").textContent = user.exports_count ?? 0;
  if ($("stat-processed")) $("stat-processed").textContent = user.processed_count ?? 0;
}

export async function restoreSession() {
  if (!getAccessToken()) {
    showScreen("auth");
    return false;
  }
  try {
    const me = await authApi.getMe();
    applyUser(me);
    showScreen("app");
    await onReady(me);
    return true;
  } catch {
    showScreen("auth");
    return false;
  }
}

export async function handleLogin(event) {
  event.preventDefault();
  setFormError("login-error", "");
  const email = $("login-email").value.trim();
  const password = $("login-password").value;
  const remember = $("login-remember")?.checked;
  try {
    await authApi.login(email, password, remember);
    const me = await authApi.getMe();
    applyUser(me);
    showScreen("app");
    await onReady(me);
  } catch (err) {
    setFormError("login-error", err.message || "Неверный email или пароль.");
  }
  return false;
}

export async function handleRegister(event) {
  event.preventDefault();
  setFormError("register-error", "");
  const password = $("reg-password").value;
  const passwordRepeat = $("reg-password2").value;
  try {
    await authApi.register({
      first_name: $("reg-firstname").value.trim(),
      last_name: $("reg-lastname").value.trim(),
      email: $("reg-email").value.trim(),
      organization: $("reg-org").value.trim(),
      role: $("reg-role").value.trim() || "Агроном",
      password,
      password_repeat: passwordRepeat,
    });
    const me = await authApi.getMe();
    applyUser(me);
    showScreen("app");
    await onReady(me);
  } catch (err) {
    setFormError("register-error", err.message || "Не удалось создать аккаунт.");
  }
  return false;
}

export async function handleLogout() {
  await authApi.logout();
  currentUser = null;
  showScreen("auth");
  showForm("login");
  onLogout();
}

export function toggleMode(mode) {
  showForm(mode);
}

export function openForgotPasswordModal() {
  openAppModal({
    title: "Восстановление пароля",
    bodyHtml: `
      <div class="input-group"><label>EMAIL</label><input id="reset-email" type="email" class="search-input"></div>
      <div class="input-group"><label>КОД</label><input id="reset-code" class="search-input" maxlength="6"></div>
      <div class="input-group"><label>НОВЫЙ ПАРОЛЬ</label><input id="reset-password" type="password" class="search-input"></div>
      <div class="input-group"><label>ПОВТОР</label><input id="reset-password2" type="password" class="search-input"></div>
    `,
    actions: [
      { label: "Отмена", onClick: closeAppModal },
      {
        label: "Отправить код",
        className: "mini-btn",
        onClick: async () => {
          try {
            await authApi.requestPasswordReset($("reset-email").value.trim());
            showToast("Если аккаунт существует, код отправлен на почту");
          } catch (err) {
            showToast(err.message, true);
          }
        },
      },
      {
        label: "Сменить пароль",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          try {
            await authApi.confirmPasswordReset({
              email: $("reset-email").value.trim(),
              code: $("reset-code").value.trim(),
              new_password: $("reset-password").value,
              new_password_repeat: $("reset-password2").value,
            });
            closeAppModal();
            showToast("Пароль обновлён");
          } catch (err) {
            showToast(err.message, true);
          }
        },
      },
    ],
  });
}
