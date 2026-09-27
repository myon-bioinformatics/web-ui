(function (global) {
  "use strict";

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
    });
  }

  function bytes(value) {
    if (value === null || value === undefined) return "not measured";
    if (!Number.isInteger(value) || value < 0) throw new Error("invalid byte measurement");
    var units = ["B", "KiB", "MiB", "GiB"], n = value, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return (i === 0 ? String(n) : n.toFixed(2)) + " " + units[i];
  }

  function validate(record) {
    if (!record || record.schema_version !== "1.0") throw new Error("unsupported metadata schema");
    if (!record.head || !record.repository || !record.measurements) throw new Error("incomplete metadata");
    if (record.head.short_sha !== record.head.sha.slice(0, 8)) throw new Error("invalid short sha");
    return record;
  }

  function commitLine(record) {
    validate(record);
    var h = record.head;
    return "Commit " + h.short_sha + " · " + h.branch + " · " + h.timestamp + " · " + h.subject;
  }

  function render(record) {
    validate(record);
    var m = record.measurements;
    return '<section class="repo-diagnostics" data-schema-version="' + esc(record.schema_version) + '">' +
      '<h2>Repository diagnostics</h2>' +
      '<p class="repo-diagnostics__commit">' + esc(commitLine(record)) + '</p>' +
      '<dl class="repo-diagnostics__measurements">' +
      '<dt>GitHub reported</dt><dd>' + esc(bytes(m.github_reported_size_bytes)) + '</dd>' +
      '<dt>Working tree</dt><dd>' + esc(bytes(m.working_tree_bytes)) + '</dd>' +
      '<dt>Release artifact</dt><dd>' + esc(bytes(m.release_artifact_bytes)) + '</dd>' +
      '</dl></section>';
  }

  var api = {validate: validate, formatBytes: bytes, commitLine: commitLine, render: render};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.RepositoryDiagnostics = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
