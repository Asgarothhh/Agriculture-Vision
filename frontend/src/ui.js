export function $(id) {
  return document.getElementById(id);
}

export function showToast(message, isError = false) {
  const el = $("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", !!isError);
  el.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.remove("show"), 3200);
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
    btn.onclick = action.onClick;
    box.appendChild(btn);
  });
  $("app-modal").style.display = "flex";
}

export function closeAppModal() {
  $("app-modal").style.display = "none";
}

export function bindPasswordToggles(root = document) {
  root.querySelectorAll(".password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = btn.parentElement?.querySelector("input");
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
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
