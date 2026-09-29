import * as authApi from "../api/auth.js";
import * as activityApi from "../api/activity.js";
import { rememberEnabled } from "../api/client.js";
import {
  $,
  PASSWORD_RULE_TEXT,
  closeAppModal,
  confirmModal,
  downloadBlob,
  escapeHtml,
  openAppModal,
  showToast,
  validatePassword,
} from "../ui.js";
import { applyUser, logoutNow } from "../auth/session.js";
import { showResultOverlay } from "../map/map.js";

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

/** Password-change fields of the profile form: returns an error text or null. */
export function passwordChangeError({ current, password, repeat }) {
  if (!current && !password && !repeat) return null;
  if (!current) return "Укажите текущий пароль";
  if (!password) return "Введите новый пароль";
  if (!validatePassword(password)) return PASSWORD_RULE_TEXT;
  if (password !== repeat) return "Пароли не совпадают";
  if (password === current) return "Новый пароль совпадает с текущим";
  return null;
}

export async function saveProfile() {
  const first = $("prof-name").value.trim();
  const last = $("prof-lastname").value.trim();
  if (!first || !last) {
    showToast("Имя и фамилия не могут быть пустыми", true);
    return;
  }
  const payload = { first_name: first, last_name: last, organization: $("prof-org").value.trim() };
  const current = $("prof-current-password")?.value || "";
  const password = $("prof-new-password").value;
  const repeat = $("prof-new-password2").value;
  const error = passwordChangeError({ current, password, repeat });
  if (error) {
    showToast(error, true);
    return;
  }
  const changingPassword = !!password;
  if (changingPassword) {
    payload.current_password = current;
    payload.password = password;
    payload.password_repeat = repeat;
  }
  try {
    const me = await authApi.patchMe(payload);
    if (changingPassword) {
      // The server revokes every refresh token on a password change; get a fresh pair.
      await authApi.login(me.email, password, rememberEnabled());
    }
    applyUser(me);
    $("prof-current-password").value = "";
    $("prof-new-password").value = "";
    $("prof-new-password2").value = "";
    showToast(changingPassword ? "Пароль изменён" : "Профиль сохранён");
  } catch (err) {
    showToast(err.message, true);
  }
}

/** Reload the «Экспортов» / «Обработано» counters from the server. */
export async function refreshAccountStats() {
  try {
    applyUser(await authApi.getMe());
  } catch {
    /* counters stay as they were */
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
    bodyHtml: `<div class="input-group"><label>ПАРОЛЬ</label><input id="delete-acc-password" type="password" class="search-input" autocomplete="current-password"></div>
      <div id="delete-acc-error" class="form-error"></div>`,
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
            accountDeleteBusy = false;
          } catch (err) {
            accountDeleteBusy = false;
            const box = $("delete-acc-error");
            if (box) {
              box.textContent = err.message || "Неверный пароль";
              box.style.display = "block";
            } else showToast(err.message || "Неверный пароль", true);
          }
        },
      },
    ],
  });
}

/** Categories to request, or null when nothing is checked (the feed is then empty). */
export function historyCategories(checked, all) {
  if (all) return [];
  if (!checked.length) return null;
  return checked.map((value) => UI_TO_API[value]).filter(Boolean);
}

/** Only finished processing has a result to open or download. */
export function hasTaskResult(item) {
  const payload = item?.payload || {};
  if (!payload.task_id) return false;
  return payload.status === "COMPLETED" || item.action === "Обработка снимка завершена";
}

let historyRequest = 0;

/** Filter button text, as in the reference: «Все» / «Не выбрано» / category / «Выбрано: N». */
export function historyFilterLabel(checkedLabels, total) {
  if (checkedLabels.length === total) return "Все";
  if (!checkedLabels.length) return "Не выбрано";
  if (checkedLabels.length === 1) return checkedLabels[0];
  return `Выбрано: ${checkedLabels.length}`;
}

function syncHistoryFilterLabel() {
  const boxes = [...document.querySelectorAll(".history-filter-cat")];
  const on = boxes.filter((el) => el.checked);
  const label = $("history-filter-label");
  if (label) {
    label.textContent = historyFilterLabel(
      on.map((el) => el.closest("label")?.textContent.trim() || el.value),
      boxes.length,
    );
  }
  const all = $("history-filter-all");
  if (all) all.indeterminate = on.length > 0 && on.length < boxes.length;
}

export async function renderHistoryFeed() {
  const q = $("history-search")?.value || "";
  const order = $("history-sort")?.value || "newest";
  syncHistoryFilterLabel();
  const checked = [...document.querySelectorAll(".history-filter-cat:checked")].map((el) => el.value);
  const categories = historyCategories(checked, $("history-filter-all")?.checked);
  const feed = $("history-feed");
  if (categories === null) {
    feed.innerHTML = `<p class="history-empty">Ничего не найдено</p>`;
    return;
  }
  const request = ++historyRequest;
  try {
    const data = await activityApi.listActivity({ q, order, categories, limit: 200 });
    if (request !== historyRequest) return; // a newer search is already on its way
    const items = data.items || [];
    if (!items.length) {
      const empty = (data.total_all ?? data.total) ? "Ничего не найдено" : "Пока нет действий на аккаунте";
      feed.innerHTML = `<p class="history-empty">${empty}</p>`;
      return;
    }
    feed.innerHTML = items
      .map((item) => {
        const taskId = hasTaskResult(item) ? escapeHtml(item.payload.task_id) : "";
        return `<div class="history-row">
          ${iconFor(item.category)}
          <div>
            <div class="history-text">${escapeHtml(item.action)}</div>
            <div class="history-date">${escapeHtml(CATEGORY_LABEL[item.category] || item.category)} · ${new Date(item.created_at).toLocaleString("ru")}</div>
            ${taskId ? `<button type="button" class="mini-btn" data-open-task="${taskId}">Открыть</button>
              <button type="button" class="mini-btn" data-dl-task="${taskId}">Скачать результат</button>` : ""}
          </div>
        </div>`;
      })
      .join("");
    feed.querySelectorAll("[data-open-task]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const geojson = await activityApi.openActivityResult(btn.dataset.openTask);
          const count = showResultOverlay(geojson);
          showToast(count ? `Результат открыт на карте: объектов ${count}` : "В этом результате нет объектов", !count);
        } catch (err) {
          showToast(err.message, true);
        }
      };
    });
    feed.querySelectorAll("[data-dl-task]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const payload = await activityApi.downloadActivityResult(btn.dataset.dlTask);
          const blob =
            payload instanceof Blob ? payload : new Blob([JSON.stringify(payload)], { type: "application/geo+json" });
          downloadBlob(blob, `task-${btn.dataset.dlTask}.geojson`);
        } catch (err) {
          showToast(err.message, true);
        }
      };
    });
  } catch (err) {
    showToast(err.message, true);
  }
}
