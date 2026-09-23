import { api, dzzTileUrl } from "./client.js";

export function connectDzz({ login, password, service_url }) {
  return api("/api/v1/dzz/connect", {
    method: "POST",
    body: JSON.stringify({ login, password, service_url }),
  });
}

export function dzzStatus() {
  return api("/api/v1/dzz/status");
}

export function dzzCheck() {
  return api("/api/v1/dzz/check", { method: "POST" });
}

export function disconnectDzz() {
  return api("/api/v1/dzz/disconnect", { method: "POST" });
}

export function dzzRegions() {
  return api("/api/v1/dzz/regions");
}

export function dzzCapabilities() {
  return api("/api/v1/dzz/wmts/capabilities");
}

export { dzzTileUrl };
