import { clearTokens, getAccessToken } from "../api/client.js";
import * as authApi from "../api/auth.js";
import { $, closeAppModal, confirmModal, initials, openAppModal, setFormError, showForm, showScreen, showToast, dbg } from "../ui.js";
import { resetDisplaySettings } from "../layers/store.js";

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
    // #region agent log
    dbg("H4", "session-ready", { email: me?.email, role: me?.role });
    // #endregion
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
    resetDisplaySettings();
    await authApi.login(email, password, remember);
    const me = await authApi.getMe();
    applyUser(me);
    showScreen("app");
    await onReady(me);
  } catch (err) {
    setFormError("login-error", err.message || "Неверный email или пароль. Если почта уже зарегистрирована — проверьте пароль");
  }
  return false;
}

function validatePassword(value) {
  return /^(?=.*[a-zа-я])(?=.*[A-ZА-Я])(?=.*[^A-Za-zА-Яа-я0-9]).{8,}$/.test(value);
}

export async function handleRegister(event) {
  event.preventDefault();
  setFormError("register-error", "");
  const password = $("reg-password").value;
  const passwordRepeat = $("reg-password2").value;
  if (!validatePassword(password)) {
    setFormError("register-error", "Пароль: минимум 8 символов, строчная и заглавная буквы, спецсимвол");
    return false;
  }
  try {
    resetDisplaySettings();
    await authApi.register({
      first_name: $("reg-firstname").value.trim(),
      last_name: $("reg-lastname").value.trim(),
      email: $("reg-email").value.trim(),
      organization: $("reg-org").value.trim(),
      role: $("reg-role").value || "Агроном",
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

export async function logoutNow({ skipServer = false } = {}) {
  if (skipServer) clearTokens();
  else await authApi.logout();
  currentUser = null;
  resetDisplaySettings();
  showScreen("auth");
  showForm("login");
  onLogout();
}

export async function handleLogout() {
  const ok = await confirmModal({
    title: "Выход",
    bodyHtml: "<p>Выйти из аккаунта?</p>",
    confirmLabel: "Выйти",
    cancelLabel: "Отмена",
    danger: true,
  });
  if (!ok) return;
  await logoutNow();
}

export function toggleMode(mode) {
  showForm(mode);
}

export function openForgotPasswordModal() {
  renderResetStep({ email: "", step: 1 });
}

function setResetModalError(text) {
  const el = $("reset-modal-error");
  if (el) el.textContent = text || "";
}

function escapeAttr(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function applyResetCodeHint(res, email) {
  const mailSent = !!res?.mail_sent;
  const devCode = res?.dev_code ? String(res.dev_code) : "";
  if (mailSent) showToast(res?.detail || "Код отправлен на почту");
  else if (devCode) showToast("SMTP не настроен — письмо не уходило, код показан в окне");
  else showToast(res?.detail || "Если аккаунт существует, код отправлен на почту");
  renderResetStep({ email, step: 2, mailSent, devCode });
}

function renderResetStep({ email, step, code, mailSent, devCode }) {
  if (step === 1) {
    openAppModal({
      title: "Восстановление пароля",
      bodyHtml: `<div class="input-group"><label>EMAIL</label><input id="reset-email" type="email" class="search-input" value="${escapeAttr(email)}"></div>
        <p class="modal-hint">Код из 4 цифр. Письмо уходит только если на сервере задан SMTP. Иначе код покажем в следующем окне.</p>
        <p class="modal-error" id="reset-modal-error"></p>`,
      actions: [
        { label: "Отмена", onClick: closeAppModal },
        {
          label: "Отправить код",
          className: "mini-btn mini-btn-red",
          onClick: async (event) => {
            const btn = event?.currentTarget;
            const value = $("reset-email")?.value.trim();
            if (!value) {
              setResetModalError("Укажите email");
              return;
            }
            setResetModalError("");
            if (btn) btn.disabled = true;
            try {
              const res = await authApi.requestPasswordReset(value);
              applyResetCodeHint(res, value);
            } catch (err) {
              const message = err.message || "Не удалось отправить код";
              setResetModalError(message);
              showToast(message, true);
              if (btn) btn.disabled = false;
            }
          },
        },
      ],
    });
    setTimeout(() => $("reset-email")?.focus(), 40);
    return;
  }
  if (step === 2) {
    const codeBlock = devCode
      ? `<p class="reset-dev-code" id="reset-code-display">${escapeAttr(devCode)}</p>
         <p class="modal-hint" id="reset-dev-hint">Письмо не отправлено: SMTP на сервере пустой. Введите эти 4 цифры.</p>`
      : `<p class="modal-hint" id="reset-dev-hint">${
          mailSent
            ? "Проверьте почту, в том числе «Спам». Код из 4 цифр действует 15 минут."
            : "Если аккаунт с этим email есть, код отправлен. Без SMTP письмо не уйдёт."
        }</p>`;
    openAppModal({
      title: "Код из письма",
      bodyHtml: `<div class="input-group"><label>КОД</label><input id="reset-code" class="search-input" maxlength="4" inputmode="numeric" value="${escapeAttr(devCode)}"></div>
        <button type="button" class="mini-btn" id="reset-resend">Отправить код ещё раз</button>
        ${codeBlock}
        <p class="modal-error" id="reset-modal-error"></p>`,
      actions: [
        { label: "Назад", onClick: () => renderResetStep({ email, step: 1 }) },
        {
          label: "Далее",
          className: "mini-btn mini-btn-red",
          onClick: () => {
            const nextCode = $("reset-code").value.trim();
            if (!/^\d{4}$/.test(nextCode)) {
              setResetModalError("Введите 4 цифры");
              showToast("Введите 4 цифры", true);
              return;
            }
            renderResetStep({ email, step: 3, code: nextCode });
          },
        },
      ],
    });
    $("reset-resend")?.addEventListener("click", async () => {
      try {
        const res = await authApi.requestPasswordReset(email);
        applyResetCodeHint(res, email);
      } catch (err) {
        setResetModalError(err.message);
        showToast(err.message, true);
      }
    });
    setTimeout(() => $("reset-code")?.focus(), 40);
    return;
  }
  openAppModal({
    title: "Новый пароль",
    bodyHtml: `<div class="input-group"><label>НОВЫЙ ПАРОЛЬ</label><input id="reset-password" type="password" class="search-input"></div>
      <div class="input-group"><label>ПОВТОР</label><input id="reset-password2" type="password" class="search-input"></div>
      <p class="modal-error" id="reset-modal-error"></p>`,
    actions: [
      { label: "Отмена", onClick: closeAppModal },
      {
        label: "Сменить пароль",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          try {
            await authApi.confirmPasswordReset({
              email,
              code,
              new_password: $("reset-password").value,
              new_password_repeat: $("reset-password2").value,
            });
            closeAppModal();
            showToast("Пароль обновлён");
          } catch (err) {
            setResetModalError(err.message);
            showToast(err.message, true);
          }
        },
      },
    ],
  });
}
