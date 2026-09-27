import * as layersApi from "../api/layers.js";
import { $, downloadBlob, showToast } from "../ui.js";
import { getMe } from "../api/auth.js";
import { applyUser } from "../auth/session.js";

export async function exportLayers() {
  const format = $("export-format").value;
  $("export-status").textContent = "Экспорт…";
  try {
    const { payload, headers } = await layersApi.exportLayers(format);
    const blob =
      payload instanceof Blob
        ? payload
        : new Blob([JSON.stringify(payload)], { type: "application/geo+json" });
    const ext = { geojson: "geojson", kml: "kml", shp: "zip", shapefile: "zip", svg: "svg" }[format] || "bin";
    downloadBlob(blob, `layers.${ext}`);
    // Spec 5.4: the number of exported objects is shown under the button.
    const count = Number(headers.get("X-Exported-Count"));
    $("export-status").textContent = Number.isFinite(count) && count > 0 ? `Экспортировано объектов: ${count}` : "Готово";
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
