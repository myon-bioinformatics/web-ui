/* Lightweight tabbed panel module. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.webUiTabbedPanel = api;
    if (typeof document !== "undefined") {
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => api.mount(document));
      else api.mount(document);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function bindTabbed(container) {
    const nav = container.querySelector("[data-ui-tab-nav]");
    if (!nav) return;
    const tabs = Array.from(nav.querySelectorAll("button[data-ui-tab]"));
    const panels = Array.from(container.querySelectorAll("[data-ui-tab-panel]"));

    function selectTab(targetTab) {
      const targetId = targetTab.getAttribute("data-ui-tab");
      tabs.forEach(tab => {
        const isSelected = tab === targetTab;
        if (isSelected) {
          tab.setAttribute("aria-selected", "true");
        } else {
          tab.removeAttribute("aria-selected");
        }
      });
      panels.forEach(panel => {
        if (panel.getAttribute("data-ui-tab-panel") === targetId) {
          panel.hidden = false;
        } else {
          panel.hidden = true;
        }
      });
    }

    function handleClick(event) {
      const btn = event.target.closest("button[data-ui-tab]");
      if (!btn) return;
      selectTab(btn);
    }

    nav.addEventListener("click", handleClick);
    return {
      select(index) {
        if (tabs[index]) selectTab(tabs[index]);
      },
      destroy() {
        nav.removeEventListener("click", handleClick);
      }
    };
  }

  const mounted = new WeakSet();
  function mount(root) {
    root.querySelectorAll("[data-ui-tabbed]").forEach(container => {
      if (mounted.has(container)) return;
      bindTabbed(container);
      mounted.add(container);
    });
  }

  return { bindTabbed, mount };
});
