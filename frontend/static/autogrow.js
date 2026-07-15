// Auto-grow textareas so they always show their full content.
// Loaded from base.html, so it applies site-wide.
(function () {
  // .yaml panes are deliberately fixed-height scrollers, not grow-to-fit.
  const SKIP = "textarea.yaml";

  // Re-fit when a field gains layout (a hidden pane is revealed) or changes
  // width (narrower box => text rewraps => more lines). Observing the element
  // is more reliable than trying to hook every reveal path in the app.
  const lastWidth = new WeakMap();
  const sizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const ta = entry.target;
      if (!ta.getClientRects().length) continue; // still hidden; wait
      const w = ta.clientWidth;
      if (lastWidth.get(ta) === w) continue; // our own height change; ignore
      lastWidth.set(ta, w);
      fit(ta);
    }
  });

  function fit(ta) {
    if (!ta || ta.matches(SKIP)) return;
    // A hidden field has no layout: scrollHeight reads 0 and would lock in a
    // wrong height. Leave it alone; sizeObserver re-fits it once it's shown.
    sizeObserver.observe(ta);
    if (!ta.getClientRects().length) return;
    const cs = getComputedStyle(ta);
    // Border-box sizing means scrollHeight excludes the borders; add them back
    // or the field loses a couple of pixels and scrolls by one line.
    const border = parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
    ta.style.height = "auto";
    let h = ta.scrollHeight + border;

    // A template's rows="10" is the author asking for a 10-line box; keep that
    // as the floor so an empty field doesn't collapse to a single line.
    const rows = parseInt(ta.getAttribute("rows"), 10);
    if (rows > 1) {
      const line = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
      const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
      h = Math.max(h, rows * line + pad + border);
    }
    ta.style.height = h + "px";
    lastWidth.set(ta, ta.clientWidth);
  }

  function fitAll(root) {
    (root || document).querySelectorAll("textarea").forEach(fit);
  }

  document.addEventListener("input", (e) => {
    if (e.target.tagName === "TEXTAREA") fit(e.target);
  });

  // Assigning .value from JS fires no event, so hook the setter itself. This
  // covers every `ta.value = …` in the app without each caller opting in.
  const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  Object.defineProperty(HTMLTextAreaElement.prototype, "value", {
    configurable: true,
    enumerable: desc.enumerable,
    get: desc.get,
    set: function (v) {
      desc.set.call(this, v);
      // Detached nodes have no layout yet; they get sized when inserted.
      if (this.isConnected) fit(this);
    },
  });

  // Textareas added later (templates, innerHTML renders, htmx swaps) need a
  // first pass; they have no value assignment and no input event.
  new MutationObserver((records) => {
    for (const r of records) {
      for (const node of r.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.tagName === "TEXTAREA") fit(node);
        else fitAll(node);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  // Server-rendered content sized once fonts are settled, so metrics are final.
  document.addEventListener("DOMContentLoaded", () => fitAll());
  if (document.fonts) document.fonts.ready.then(() => fitAll());

  window.CVAutoGrow = { fit, fitAll };
})();
