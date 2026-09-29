// Profile picture, as in the reference: kept in the browser per email (the spec does not
// send it to the server). The image is scaled down first so it fits into localStorage.
import { $, closeAppModal, openAppModal, showToast } from "../ui.js";
import { logAction } from "../api/activity.js";

const PREFIX = "ttz_avatar_";
const MAX_SIDE = 256;

let current = { email: "", initials: "" };

function key(email) {
  return `${PREFIX}${email}`;
}

export function getAvatar(email) {
  try {
    return email ? localStorage.getItem(key(email)) : null;
  } catch {
    return null;
  }
}

/** Shows the picture (or the initials) in the profile card and the sidebar. */
export function applyAvatarUI(email, initials) {
  current = { email: email || "", initials: initials || "" };
  const dataUrl = getAvatar(email);
  [$("card-avatar"), $("sidebar-avatar")].forEach((el) => {
    if (!el) return;
    if (dataUrl) {
      el.style.backgroundImage = `url(${dataUrl})`;
      el.style.backgroundSize = "cover";
      el.style.backgroundPosition = "center";
      el.style.color = "transparent";
    } else {
      el.style.backgroundImage = "";
      el.style.color = "";
    }
    el.textContent = current.initials;
  });
}

function scaleDown(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Файл не похож на изображение"));
      img.onload = () => {
        const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.width * scale));
        canvas.height = Math.max(1, Math.round(img.height * scale));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.85));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export async function handleAvatarFile(file) {
  if (!file || !current.email) return;
  if (!String(file.type || "").startsWith("image/")) {
    showToast("Выберите изображение", true);
    return;
  }
  try {
    const dataUrl = await scaleDown(file);
    localStorage.setItem(key(current.email), dataUrl);
    applyAvatarUI(current.email, current.initials);
    logAction("account", "Обновлена аватарка");
    showToast("Аватарка обновлена");
  } catch (err) {
    showToast(err.message || "Не удалось сохранить аватарку", true);
  }
}

function removeAvatar() {
  if (!getAvatar(current.email)) return;
  try {
    localStorage.removeItem(key(current.email));
  } catch {
    /* storage unavailable */
  }
  applyAvatarUI(current.email, current.initials);
  logAction("account", "Удалена аватарка");
  showToast("Аватарка удалена");
}

/** Click on the profile picture: «Загрузить» / «Удалить». */
export function onAvatarClick() {
  if (!current.email) return;
  const has = Boolean(getAvatar(current.email));
  openAppModal({
    title: "Аватарка",
    bodyHtml: has
      ? '<p class="modal-text">Загрузите новое изображение или удалите текущую аватарку.</p>'
      : '<p class="modal-text">Загрузите изображение для аватарки профиля.</p>',
    actions: [
      ...(has
        ? [
            {
              label: "Удалить",
              className: "mini-btn mini-btn-blue",
              onClick: () => {
                closeAppModal();
                removeAvatar();
              },
            },
          ]
        : []),
      {
        label: "Загрузить",
        className: "mini-btn mini-btn-red",
        onClick: () => {
          closeAppModal();
          $("avatar-file-input")?.click();
        },
      },
      { label: "Отмена", className: "mini-btn", onClick: closeAppModal },
    ],
  });
}
