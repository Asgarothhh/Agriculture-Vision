import * as layersApi from "../api/layers.js";
import { $, downloadBlob, showToast } from "../ui.js";
import { getMe } from "../api/auth.js";
import { applyUser } from "../auth/session.js";

export async function exportLayers() {
  const format = $("export-format").value;
  $("export-status").textContent = "Экспорт…";
  try {
    const payload = await layersApi.exportLayers(format);
    const blob =
      payload instanceof Blob
        ? payload
        : new Blob([JSON.stringify(payload)], { type: "application/geo+json" });
    const ext = { geojson: "geojson", kml: "kml", shp: "zip", shapefile: "zip", svg: "svg" }[format] || "bin";
    downloadBlob(blob, `layers.${ext}`);
    $("export-status").textContent = "Готово";
    try {
      applyUser(await getMe());
    } catch {
      /* ignore */
    }
  } catch (err) {
    $("export-status").textContent = err.message;
    showToast(err.message, true);
  }
}
