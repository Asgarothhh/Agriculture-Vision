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
