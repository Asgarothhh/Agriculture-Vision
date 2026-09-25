import * as authApi from "../api/auth.js";
import * as activityApi from "../api/activity.js";
import { $, confirmModal, openAppModal, closeAppModal, showToast } from "../ui.js";
import { applyUser, logoutNow } from "../auth/session.js";
import { loadMapData } from "../layers/store.js";

const UI_TO_API = {
  account: "account",
  tool: "map_tools",
  export: "export",
  process: "upload_processing",
};

const CATEGORY_LABEL = {
  account: "Аккаунт",
  map_tools: "Инструменты и карта",
  export: "Экспорт",
  upload_processing: "Загрузка и обработка",
};

function iconFor(category) {
  const paths = {
    account: `<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>`,
    map_tools: `<polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>`,
    export: `<path d="M4 12v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6"></path><polyline points="16 6 12 2 8 6"></polyline>`,
    upload_processing: `<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline>`,
  };
  const d = paths[category] || paths.account;
  const type = category === "map_tools" ? "tool" : category === "upload_processing" ? "process" : category;
  return `<span class="history-icon type-${type}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${d}</svg></span>`;
}

export async function saveProfile() {
  const payload = {
    first_name: $("prof-name").value.trim(),
    last_name: $("prof-lastname").value.trim(),
    organization: $("prof-org").value.trim(),
  };
  const password = $("prof-new-password").value;
  const currentPassword = $("prof-current-password")?.value || "";
  if (password) {
    if (!currentPassword) {
      showToast("Укажите текущий пароль", true);
      return;
    }
    payload.current_password = currentPassword;
    payload.password = password;
    payload.password_repeat = $("prof-new-password2").value;
  }
  try {
    const me = await authApi.patchMe(payload);
    applyUser(me);
    if ($("prof-current-password")) $("prof-current-password").value = "";
    $("prof-new-password").value = "";
    $("prof-new-password2").value = "";
    showToast("Профиль сохранён");
  } catch (err) {
    showToast(err.message, true);
  }
}

let accountDeleteBusy = false;

export async function deleteAccount() {
  if (accountDeleteBusy) return;
  const warn = await confirmModal({
    title: "Удалить аккаунт",
    bodyHtml: "<p>Аккаунт и все данные будут удалены безвозвратно, действие нельзя отменить.</p>",
    confirmLabel: "Продолжить",
    cancelLabel: "Отмена",
    danger: true,
  });
  if (!warn) return;
  openAppModal({
    title: "Подтвердите паролем",
    bodyHtml: `<div class="input-group"><label>ПАРОЛЬ</label><input id="delete-acc-password" type="password" class="search-input" autocomplete="current-password"></div>`,
    actions: [
      { label: "Отмена", onClick: closeAppModal },
      {
        label: "Удалить",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          if (accountDeleteBusy) return;
          accountDeleteBusy = true;
          try {
            await authApi.deleteMe($("delete-acc-password")?.value || "");
            closeAppModal();
            await logoutNow({ skipServer: true });
          } catch (err) {
            accountDeleteBusy = false;
            showToast(err.message || "Неверный пароль", true);
          }
        },
      },
    ],
  });
}

export async function renderHistoryFeed() {
  const q = $("history-search")?.value || "";
  const order = $("history-sort")?.value || "newest";
  const checked = [...document.querySelectorAll(".history-filter-cat:checked")].map((el) => el.value);
  const all = $("history-filter-all")?.checked;
  const category = !all && checked.length === 1 ? UI_TO_API[checked[0]] : undefined;
  try {
    const data = await activityApi.listActivity({ q, order, category, limit: 50 });
    const feed = $("history-feed");
    const items = data.items || [];
    if (!items.length) {
      feed.innerHTML = `<p class="history-empty">${data.total ? "Ничего не найдено" : "Пока нет действий на аккаунте"}</p>`;
      return;
    }
    feed.innerHTML = items
      .map((item) => {
        const taskId = item.payload?.task_id;
        return `<div class="history-row">
          ${iconFor(item.category)}
          <div>
            <div class="history-text">${item.action}</div>
            <div class="history-date">${CATEGORY_LABEL[item.category] || item.category} · ${new Date(item.created_at).toLocaleString("ru")}</div>
            ${taskId ? `<button type="button" class="mini-btn" data-open-task="${taskId}">Открыть результат</button>
              <button type="button" class="mini-btn" data-dl-task="${taskId}">Скачать результат</button>` : ""}
          </div>
        </div>`;
      })
      .join("");
    feed.querySelectorAll("[data-open-task]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          await activityApi.openActivityResult(btn.dataset.openTask);
          await loadMapData();
          showToast("Результат открыт на карте");
        } catch (err) {
          showToast(err.message, true);
        }
      };
    });
    feed.querySelectorAll("[data-dl-task]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const payload = await activityApi.downloadActivityResult(btn.dataset.dlTask);
          const blob = payload instanceof Blob ? payload : new Blob([JSON.stringify(payload)]);
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `task-${btn.dataset.dlTask}.geojson`;
          a.click();
          URL.revokeObjectURL(url);
        } catch (err) {
          showToast(err.message, true);
        }
      };
    });
  } catch (err) {
    showToast(err.message, true);
  }
}
