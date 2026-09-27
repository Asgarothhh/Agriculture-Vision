import { isSecurityError } from "../ui.js";

// Share of the whole segmentation run shown by the progress bar at each client stage.
export const SEG_STAGES = {
  health: { percent: 5, text: "Проверка ML-сервера…" },
  capture: { percent: 15, text: "Захват карты…" },
  upload: { percent: 30, text: "Отправка снимка на сервер…" },
  publish: { percent: 93, text: "Публикация результатов на карту…" },
  done: { percent: 100, text: "Готово" },
};

// Server-side task progress (0–100) is mapped into this part of the bar.
const TASK_FROM = 35;
const TASK_TO = 90;

export function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
}

export function taskStage(task) {
  const progress = clampPercent(task?.progress);
  if (task?.status === "PENDING") {
    return { percent: TASK_FROM, text: "В очереди на обработку…" };
  }
  if (task?.status === "PROCESSING") {
    return {
      percent: TASK_FROM + Math.round((progress * (TASK_TO - TASK_FROM)) / 100),
      text: `Сегментация на сервере… ${progress}%`,
    };
  }
  return { percent: TASK_TO, text: "Обработка на сервере завершена" };
}

/**
 * Header pill for the ML server (spec 4): «ML <models>» when ready, «ML недоступен»
 * when the server does not answer, «ML оффлайн» when the user has no internet.
 */
export function mlPillState(health, { online = true, failed = false } = {}) {
  if (!online) return { text: "ML оффлайн", cls: "status-offline" };
  if (failed || !health) return { text: "ML недоступен", cls: "status-idle" };
  if (health.status === "loading") return { text: "ML · загрузка моделей", cls: "status-idle" };
  if (health.status !== "ready") return { text: "ML недоступен", cls: "status-idle" };
  const loaded = (health.models || []).filter((m) => m.loaded).map((m) => m.code);
  return { text: `ML · ${loaded.join(", ") || "готов"}`, cls: "status-online" };
}

export function mlPillTitle(health) {
  const models = health?.models || [];
  const lines = models.map((m) => `${m.code}: ${m.loaded ? "загружена" : m.error || "не загружена"}`);
  return lines.join("\n") || "Нет данных от ML-сервера";
}

export function humanizeSegError(err) {
  if (isSecurityError(err)) {
    return "Браузер запретил чтение изображения карты (SecurityError). Обновите страницу с очисткой кэша (Ctrl+F5); если ошибка повторится — смените подложку.";
  }
  if (err?.status === 401) return "Сессия истекла — войдите снова";
  if (err instanceof TypeError && /fetch/i.test(String(err.message || ""))) {
    return "Нет связи с сервером";
  }
  return err?.message || "Сегментация не удалась";
}
