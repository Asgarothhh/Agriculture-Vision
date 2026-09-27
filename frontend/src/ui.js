export function $(id) {
  return document.getElementById(id);
}

const ICON_EYE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
const ICON_EYE_OFF = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-7 0-11-7-11-7a21.8 21.8 0 0 1 5.06-5.94"></path><path d="M9.9 4.24A10.94 10.94 0 0 1 12 5c7 0 11 7 11 7a21.8 21.8 0 0 1-2.16 3.19"></path><path d="M14.12 14.12a3 3 0 0 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

export function showToast(message, isError = false) {
  const text = String(message || "");
  const targets = [$("toast"), $("global-toast")].filter(Boolean);
  targets.forEach((el) => {
    el.hidden = false;
    el.textContent = text;
    el.title = text;
    el.classList.toggle("error", !!isError);
    el.classList.toggle("toast-error", !!isError);
    el.classList.add("show");
  });
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    targets.forEach((el) => {
      el.classList.remove("show");
      if (el.id === "global-toast") el.hidden = true;
    });
  }, 3200);
}

export function showScreen(name) {
  const auth = $("screen-auth");
  const app = $("screen-app");
  if (name === "app") {
    auth.style.display = "none";
    app.style.display = "flex";
    app.classList.add("active");
  } else {
    app.style.display = "none";
    app.classList.remove("active");
    auth.style.display = "flex";
  }
}

export function showForm(mode) {
  $("form-login")?.classList.toggle("active", mode === "login");
  $("form-register")?.classList.toggle("active", mode === "register");
  $("text-login")?.classList.toggle("active", mode === "login");
  $("text-register")?.classList.toggle("active", mode === "register");
}

export function setFormError(id, message) {
  const el = $(id);
  if (!el) return;
  el.textContent = message || "";
  el.style.display = message ? "block" : "none";
}

export function openAppModal({ title, bodyHtml, actions }) {
  $("app-modal-title").textContent = title;
  $("app-modal-body").innerHTML = bodyHtml;
  const box = $("app-modal-actions");
  box.innerHTML = "";
  (actions || []).forEach((action) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = action.className || "mini-btn";
    btn.textContent = action.label;
    btn.onclick = (event) => action.onClick?.(event);
    box.appendChild(btn);
  });
  $("app-modal").style.display = "flex";
}

export function closeAppModal() {
  $("app-modal").style.display = "none";
}

export function confirmModal({
  title,
  bodyHtml = "",
  confirmLabel = "Продолжить",
  cancelLabel = "Отмена",
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    openAppModal({
      title,
      bodyHtml,
      actions: [
        {
          label: cancelLabel,
          onClick: () => {
            closeAppModal();
            resolve(false);
          },
        },
        {
          label: confirmLabel,
          className: danger ? "mini-btn mini-btn-red" : "mini-btn mini-btn-blue",
          onClick: () => {
            closeAppModal();
            resolve(true);
          },
        },
      ],
    });
  });
}

export function bindPasswordToggles(root = document) {
  root.querySelectorAll(".password-toggle").forEach((btn) => {
    if (!btn.innerHTML.trim()) btn.innerHTML = ICON_EYE;
    btn.addEventListener("click", () => {
      const field = btn.parentElement;
      const input = field?.querySelector("input");
      if (!input) return;
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      btn.innerHTML = visible ? ICON_EYE_OFF : ICON_EYE;
      field?.classList.toggle("is-visible", visible);
    });
  });
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function initials(first, last) {
  return `${(first || "A")[0]}${(last || "V")[0]}`.toUpperCase();
}

/** Tainted-canvas / blocked-storage errors: Firefox says "The operation is insecure." */
export function isSecurityError(err) {
  return !!err && (err.name === "SecurityError" || /insecure|tainted/i.test(String(err.message || "")));
}

export function withTimeout(promise, ms, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), ms);
    }),
  ]).finally(() => clearTimeout(timer));
}
