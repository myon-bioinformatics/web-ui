/* Provider-independent, text-only dropdown binding. No fetches or HTML input. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.webUiControls = api;
    if (typeof document !== "undefined") {
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => api.mount(document));
      else api.mount(document);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function bindSelect(select, output) {
    let entries = new Map(), fullText = "";
    function change() {
      output.textContent = entries.has(select.value) ? entries.get(select.value) : fullText;
    }
    select.addEventListener("change", change);
    return {
      update(items, text, fullLabel = "(full extract)") {
        const next = new Map();
        const options = [{value: "", label: fullLabel}];
        for (const item of items) {
          const value = String(item.value);
          if (!value || next.has(value)) throw new Error("section values must be nonempty and unique");
          next.set(value, String(item.body));
          options.push({value, label: String(item.label)});
        }
        const nodes = options.map(item => {
          const option = select.ownerDocument.createElement("option");
          option.value = item.value;
          option.textContent = item.label;
          return option;
        });
        entries = next;
        fullText = String(text);
        select.replaceChildren(...nodes);
        select.value = "";
        select.disabled = items.length === 0;
        change();
      },
      clear() { this.update([], ""); },
      destroy() { select.removeEventListener("change", change); }
    };
  }
  const mounted = new WeakSet();
  function mount(root) {
    root.querySelectorAll("[data-ui-section-browser]").forEach(panel => {
      if (mounted.has(panel)) return;
      const data = JSON.parse(panel.querySelector("[data-ui-section-data]").textContent);
      const control = bindSelect(panel.querySelector("select"), panel.querySelector("[data-ui-section-output]"));
      control.update(data.items, data.fullText, data.fullLabel);
      mounted.add(panel);
    });
  }
  return {bindSelect, mount};
});
