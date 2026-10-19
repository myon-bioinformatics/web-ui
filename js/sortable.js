/* Lightweight client-side table sorting module. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.webUiSortable = api;
    if (typeof document !== "undefined") {
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => api.mount(document));
      else api.mount(document);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function parseValue(text) {
    const trimmed = text.trim();
    if (!trimmed) return { type: "string", val: "" };
    // Numeric check
    const num = Number(trimmed);
    if (!isNaN(num) && trimmed !== "") return { type: "number", val: num };
    return { type: "string", val: trimmed.toLowerCase() };
  }

  function sortTable(table, colIndex, dir) {
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll("tr"));
    if (rows.length === 0) return;

    const rowData = rows.map((row, index) => {
      const cell = row.children[colIndex];
      const text = cell ? cell.textContent : "";
      return { row, parsed: parseValue(text), index };
    });

    rowData.sort((a, b) => {
      const va = a.parsed.val;
      const vb = b.parsed.val;
      let cmp = 0;
      if (typeof va === "number" && typeof vb === "number") {
        cmp = va - vb;
      } else {
        cmp = String(va).localeCompare(String(vb));
      }
      if (cmp !== 0) return dir === "asc" ? cmp : -cmp;
      return a.index - b.index; // stable sort fallback
    });

    const fragment = table.ownerDocument.createDocumentFragment();
    rowData.forEach(item => fragment.appendChild(item.row));
    tbody.appendChild(fragment);

    // Update aria-sort attributes on th elements
    const ths = table.querySelectorAll("thead th");
    ths.forEach((th, idx) => {
      const btn = th.querySelector("button[data-ui-sort]");
      if (idx === colIndex) {
        th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
        if (btn) btn.setAttribute("data-ui-sort-dir", dir);
      } else {
        th.removeAttribute("aria-sort");
        if (btn) btn.removeAttribute("data-ui-sort-dir");
      }
    });
  }

  function bindTable(table) {
    const thead = table.querySelector("thead");
    if (!thead) return;

    function handleClick(event) {
      const btn = event.target.closest("button[data-ui-sort]");
      if (!btn) return;
      const th = btn.closest("th");
      if (!th) return;
      const ths = Array.from(thead.querySelectorAll("th"));
      const colIndex = ths.indexOf(th);
      if (colIndex === -1) return;

      const currentDir = btn.getAttribute("data-ui-sort-dir");
      const nextDir = currentDir === "asc" ? "desc" : "asc";
      sortTable(table, colIndex, nextDir);
    }

    thead.addEventListener("click", handleClick);
    return {
      sort(colIndex, dir = "asc") { sortTable(table, colIndex, dir); },
      destroy() { thead.removeEventListener("click", handleClick); }
    };
  }

  const mounted = new WeakSet();
  function mount(root) {
    root.querySelectorAll("table[data-ui-sortable]").forEach(table => {
      if (mounted.has(table)) return;
      bindTable(table);
      mounted.add(table);
    });
  }

  return { parseValue, sortTable, bindTable, mount };
});
