import { api } from "./client.js";

export function listActivity({ categories = [], q, order = "newest", limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams();
  categories.forEach((category) => params.append("category", category));
  if (q) params.set("q", q);
  if (order) params.set("order", order);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return api(`/api/v1/activity/?${params}`);
}

export function openActivityResult(taskId) {
  return api(`/api/v1/activity/${taskId}/open`);
}

export function downloadActivityResult(taskId) {
  return api(`/api/v1/activity/${taskId}/result`);
}

// Reference history types → server categories.
const EVENT_CATEGORY = {
  tool: "map_tools",
  map: "map_tools",
  account: "account",
  login: "account",
  export: "export",
  process: "upload_processing",
  upload: "upload_processing",
};

/**
 * Records a UI event the server cannot see by itself (tool switch, undo, basemap…),
 * like logAction() of the reference. Fire-and-forget: history must never break the UI.
 */
export function logAction(type, action, payload) {
  const category = EVENT_CATEGORY[type] || "map_tools";
  return api("/api/v1/activity/", {
    method: "POST",
    body: JSON.stringify({ category, action: String(action).slice(0, 300), payload: payload || null }),
  }).catch(() => {});
}
