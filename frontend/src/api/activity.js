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
