import * as authApi from "../api/auth.js";
import * as activityApi from "../api/activity.js";
import { $, showToast } from "../ui.js";
import { applyUser, handleLogout } from "../auth/session.js";
import { loadMapData } from "../layers/store.js";

const UI_TO_API = {
  account: "account",
  tool: "map_tools",
  export: "export",
  process: "upload_processing",
};

export async function saveProfile() {
  const payload = {
    first_name: $("prof-name").value.trim(),
    last_name: $("prof-lastname").value.trim(),
    organization: $("prof-org").value.trim(),
  };
  const password = $("prof-new-password").value;
  if (password) {
    payload.password = password;
    payload.password_repeat = $("prof-new-password2").value;
  }
  try {
    const me = await authApi.patchMe(payload);
    applyUser(me);
    $("prof-new-password").value = "";
    $("prof-new-password2").value = "";
    showToast("Профиль сохранён");
  } catch (err) {
    showToast(err.message, true);
  }
}

export async function deleteAccount() {
  if (!window.confirm("Удалить аккаунт безвозвратно?")) return;
  try {
    await authApi.deleteMe();
    await handleLogout();
  } catch (err) {
    showToast(err.message, true);
  }
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
    feed.innerHTML = (data.items || [])
      .map((item) => {
        const taskId = item.payload?.task_id;
        return `<div class="history-item">
          <div class="history-item-title">${item.action}</div>
          <div class="history-item-meta">${item.category} · ${new Date(item.created_at).toLocaleString("ru")}</div>
          ${taskId ? `<button type="button" class="mini-btn" data-open-task="${taskId}">Открыть результат</button>` : ""}
        </div>`;
      })
      .join("") || "<p>Нет событий</p>";
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
  } catch (err) {
    showToast(err.message, true);
  }
}
