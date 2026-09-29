// Menu «Ещё» (tools card), as in the reference: position:fixed next to the tool buttons by
// their real screen coordinates, so it never slides off the right or bottom edge; the inner
// list scrolls down to «Готово». Re-positioned whenever it opens, its content grows
// (brush / eraser / merge panels), the window is resized or «Сегментация» folds.

let bound = false;

export function positionMoreMenu() {
  const menu = document.getElementById("more-menu");
  const toolbar = document.getElementById("map-toolbar");
  if (!menu || !toolbar || !menu.classList.contains("active")) return;
  const tRect = toolbar.getBoundingClientRect();
  // Always level with the tool buttons, to their left; never over «Сегментация» above.
  const top = Math.max(8, Math.min(tRect.top, window.innerHeight - 60));
  const right = Math.max(8, window.innerWidth - tRect.left + 8);
  menu.style.top = `${top}px`;
  menu.style.right = `${right}px`;
  const totalMax = Math.max(120, window.innerHeight - top - 12);
  menu.style.maxHeight = `${totalMax}px`;
  const header = menu.querySelector(".map-card-header");
  const headerH = header ? header.getBoundingClientRect().height : 44;
  const clip = menu.querySelector(".map-card-body-clip");
  if (clip) clip.style.maxHeight = `${Math.max(100, totalMax - headerH)}px`;
}

export function repositionMoreMenuIfOpen() {
  if (document.getElementById("more-menu")?.classList.contains("active")) positionMoreMenu();
}

export function initMoreMenu() {
  if (bound) return;
  const menu = document.getElementById("more-menu");
  if (!menu) return;
  bound = true;
  // Opened from several places (toolbar button, drawing modes): watch the class itself.
  new MutationObserver(() => {
    repositionMoreMenuIfOpen();
    const open = menu.classList.contains("active");
    const btn = document.getElementById("tool-more-btn");
    if (btn) {
      btn.classList.toggle("active", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
  }).observe(menu, { attributes: true, attributeFilter: ["class"] });
  if (typeof ResizeObserver !== "undefined") {
    const body = menu.querySelector(".more-menu-clip") || menu;
    new ResizeObserver(() => repositionMoreMenuIfOpen()).observe(body);
    const toolbar = document.getElementById("map-toolbar");
    if (toolbar) new ResizeObserver(() => repositionMoreMenuIfOpen()).observe(toolbar);
  }
  window.addEventListener("resize", repositionMoreMenuIfOpen);
  // «Сегментация» above moves the tool buttons: re-measure after its fold animation.
  document.getElementById("seg-panel-toggle")?.addEventListener("click", () => setTimeout(repositionMoreMenuIfOpen, 220));
}
