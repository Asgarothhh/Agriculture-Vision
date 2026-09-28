import { $, closeAppModal } from "../ui.js";
import { getMap } from "./map.js";
import {
  cancelActiveTool,
  currentMapTool,
  deleteCurrentMapSelection,
  finishPolygonDraw,
  jumpToSelectionHistory,
  mergeHotkey,
  toggleLabelsAndCoords,
} from "./tools.js";
import { redoLast, undoLast } from "./undo.js";

let bound = false;

function isShown(el) {
  return !!el && el.style.display !== "none" && el.style.display !== "";
}

/** Global map hotkeys, as in the reference (onGlobalKeyDown). */
export function bindHotkeys() {
  if (bound) return;
  bound = true;
  document.addEventListener(
    "keydown",
    (e) => {
      const typing = !!e.target?.matches?.("input, textarea, select, [contenteditable='true']");
      if (e.key === "Escape") {
        const modal = $("app-modal");
        if (isShown(modal)) {
          e.preventDefault();
          closeAppModal();
          return;
        }
        const picker = $("folder-picker");
        if (isShown(picker)) {
          e.preventDefault();
          picker.style.display = "none";
          return;
        }
        if (typing) return;
        e.preventDefault();
        cancelActiveTool();
        return;
      }
      if (typing) return;
      // Keys below act on the map only: not while a dialog is open or the map screen is hidden.
      if (isShown($("app-modal")) || !getMap() || $("view-map")?.style.display === "none") return;
      const key = (e.key || "").toLowerCase();
      const code = e.code || "";
      const mod = e.ctrlKey || e.metaKey;
      if (e.key === "Enter" && currentMapTool() === "polygon") {
        e.preventDefault();
        finishPolygonDraw();
        return;
      }
      if (mod && (key === "z" || key === "я" || code === "KeyZ")) {
        e.preventDefault();
        if (e.shiftKey) redoLast();
        else undoLast();
        return;
      }
      if (mod && (key === "g" || key === "п" || code === "KeyG")) {
        e.preventDefault();
        toggleLabelsAndCoords();
        return;
      }
      if (mod && (key === "m" || key === "ь" || code === "KeyM")) {
        e.preventDefault();
        mergeHotkey();
        return;
      }
      // Without Ctrl: Chrome/Edge reserve Ctrl+J for Downloads.
      if ((key === "j" || key === "о" || code === "KeyJ") && !mod && !e.altKey) {
        e.preventDefault();
        jumpToSelectionHistory();
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        deleteCurrentMapSelection();
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
