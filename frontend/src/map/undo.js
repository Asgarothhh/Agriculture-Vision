// Undo/redo of map actions (as in the reference: 80 steps, toasts, history log).
// Entries are {undo, redo} async functions; server-backed entries call the API,
// overlays (ruler/compass/text) are local only.
import { showToast } from "../ui.js";
import { logAction } from "../api/activity.js";

const MAX = 80;
const stack = [];
let cursor = -1;
let busy = false;
let afterChange = null;

/** Tools register a hook (clear selection etc.) run after every undo/redo, as in the reference. */
export function setUndoHook(fn) {
  afterChange = fn;
}

export function pushUndo(entry) {
  stack.splice(cursor + 1);
  stack.push(entry);
  if (stack.length > MAX) stack.shift();
  cursor = stack.length - 1;
  syncButtons();
}

async function run(direction) {
  if (busy) return false;
  const isUndo = direction === "undo";
  if (isUndo ? cursor < 0 : cursor >= stack.length - 1) {
    showToast(isUndo ? "Нечего отменять" : "Нечего повторить", true);
    return false;
  }
  busy = true;
  const index = isUndo ? cursor : cursor + 1;
  try {
    await stack[index][direction]?.();
    cursor = isUndo ? cursor - 1 : cursor + 1;
    afterChange?.(direction);
    showToast(isUndo ? "Действие отменено" : "Действие повторено");
    logAction("tool", isUndo ? "Отменено последнее действие на карте" : "Повторено действие на карте");
    return true;
  } catch (err) {
    showToast(`${isUndo ? "Не удалось отменить" : "Не удалось повторить"}: ${err?.message || err}`, true);
    return false;
  } finally {
    busy = false;
    syncButtons();
  }
}

export function undoLast() {
  return run("undo");
}

export function redoLast() {
  return run("redo");
}

export function clearUndo() {
  stack.length = 0;
  cursor = -1;
  syncButtons();
}

export function canUndo() {
  return cursor >= 0;
}

function syncButtons() {
  const undo = document.getElementById("undo-btn");
  const redo = document.getElementById("redo-btn");
  if (undo) undo.disabled = cursor < 0;
  if (redo) redo.disabled = cursor >= stack.length - 1;
}
