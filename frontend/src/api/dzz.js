import { apiNoAuth } from "./client.js";
import { dzzSession, getActiveBasemapTileUrl, toSameOriginDzzUrl } from "../dzz/urls.js";

export function connectDzz({ login, password, url, service_url }) {
  return apiNoAuth("/api/v1/dzz/connect", {
    method: "POST",
    body: JSON.stringify({ login, password, url: url || service_url }),
  });
}

export function dzzStatus() {
  return apiNoAuth("/api/v1/dzz/status");
}

export function dzzCheck() {
  return apiNoAuth("/api/v1/dzz/health");
}

export function disconnectDzz() {
  return apiNoAuth("/api/v1/dzz/disconnect", { method: "POST" });
}

export function dzzRegions() {
  return apiNoAuth("/api/v1/dzz/regions");
}

export function dzzSites() {
  return apiNoAuth("/api/v1/dzz/sites");
}

export function dzzCapabilities(body = {}) {
  return apiNoAuth("/api/v1/wmts/capabilities", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function dzzTileUrl(z, x, y) {
  return toSameOriginDzzUrl(getActiveBasemapTileUrl(z, x, y));
}

export { dzzSession, toSameOriginDzzUrl };
