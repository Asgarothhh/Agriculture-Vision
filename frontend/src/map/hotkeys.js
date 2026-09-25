import { $, showToast } from "../ui.js";
import { cycleVisitedBounds, getMap, visitedCount } from "./map.js";
import {
  activateMapTool,
  cancelMergeMode,
  currentMapTool,
  deleteAtPriority,
  finishEditAreaMode,
  finishPolygonDraw,
  mergeSelectedPair,
  getSelected,
  toggleLabelsAndCoords,
} from "./tools.js";
import { redoLast, undoLast } from "./undo.js";

let bound = false;

export function bindHotkeys() {
  if (bound) return;
  bound = true;
  document.addEventListener(
    "keydown",
    async (e) => {
    const tag = (e.target?.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    const key = (e.code || "").toLowerCase();
    if (e.key === "Escape") {
      if (document.getElementById("app-modal")?.style.display === "flex") {
        document.getElementById("app-modal").style.display = "none";
        e.preventDefault();
        return;
      }
      if (document.getElementById("folder-picker")?.style.display === "block") {
        document.getElementById("folder-picker").style.display = "none";
        e.preventDefault();
        return;
      }
      if (!typing) {
        finishEditAreaMode();
        cancelMergeMode();
        activateMapTool("select");
        e.preventDefault();
      }
      return;
    }
    if (!typing && (e.key === "Enter" || e.code === "Enter") && currentMapTool() === "polygon") {
      e.preventDefault();
      await finishPolygonDraw();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && key === "keyz") {
      e.preventDefault();
      if (e.shiftKey) {
        const ok = await redoLast();
        if (!ok) showToast("Нечего повторить");
      } else {
        const ok = await undoLast();
        if (!ok) showToast("Нечего отменять");
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && key === "keyg") {
      e.preventDefault();
      toggleLabelsAndCoords();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && key === "keym") {
      e.preventDefault();
      if (getSelected().length !== 2) {
        showToast("За раз можно объединить только 2 области", true);
        return;
      }
      await mergeSelectedPair();
      return;
    }
    if (!typing && (e.key === "j" || e.key === "J") && !e.ctrlKey) {
      const idx = cycleVisitedBounds();
      const total = visitedCount();
      if (total) showToast(`Область ${idx + 1} из ${total} (от недавней к первой)`);
      return;
    }
    if (!typing && (e.key === "Delete" || e.key === "Backspace")) {
      e.preventDefault();
      await deleteAtPriority();
    }
    },
    true,
  );
}

export function bindSidebarResize() {
  const wrap = $("sidebar-panel-wrap");
  const panel = $("sidebar-panel");
  const handle = $("sidebar-resizer");
  if (!wrap || !panel || !handle) return;
  const stored = Number(localStorage.getItem("ttz_sidebar_width") || 320);
  panel.style.width = `${Math.min(520, Math.max(300, stored))}px`;
  let dragging = false;
  handle.addEventListener("mousedown", (e) => {
    dragging = true;
    e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const left = wrap.getBoundingClientRect().left;
    const width = Math.min(520, Math.max(300, e.clientX - left));
    panel.style.width = `${width}px`;
    localStorage.setItem("ttz_sidebar_width", String(width));
    getMap()?.invalidateSize();
  });
  document.addEventListener("mouseup", () => {
    dragging = false;
  });
}
