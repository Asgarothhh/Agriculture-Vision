const MAX = 80;
const stack = [];
let cursor = -1;

export function pushUndo(entry) {
  stack.splice(cursor + 1);
  stack.push(entry);
  if (stack.length > MAX) stack.shift();
  cursor = stack.length - 1;
  syncButtons();
}

export async function undoLast() {
  if (cursor < 0) return false;
  const entry = stack[cursor];
  cursor -= 1;
  await entry.undo?.();
  syncButtons();
  return true;
}

export async function redoLast() {
  if (cursor >= stack.length - 1) return false;
  cursor += 1;
  await stack[cursor].redo?.();
  syncButtons();
  return true;
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
