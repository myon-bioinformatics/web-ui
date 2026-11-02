"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
// The browser modules are Python data: unless WEB_UI_JS_DIR names a folder, ask web_ui.py to write them to a temp folder.
const jsDir = process.env.WEB_UI_JS_DIR || (() => {
  const {mkdtempSync} = require("fs"), {join} = require("path"), {tmpdir} = require("os");
  const out = mkdtempSync(join(tmpdir(), "web-ui-js-"));
  const done = require("child_process").spawnSync(process.env.PYTHON || "python3", ["-S", join(__dirname, "..", "web_ui.py"), "--site", out], {encoding: "utf8"});
  if (done.status !== 0) throw new Error("web_ui.py --site failed: " + done.stderr);
  return join(out, "js");
})();
const renderer = require(path.join(jsDir, "repository-diagnostics.js"));

const fixturePath = path.join(__dirname, "fixtures", "repository_metadata_v1.json");
const record = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

assert.strictEqual(
  renderer.commitLine(record),
  "Commit 1376c703 · main · 2026-09-27T19:09:22+09:00 · chore: refresh metadata"
);

const html = renderer.render(record);
assert(html.includes("myon-bioinformatics/Ironmate"));
assert(html.includes("not measured"));
assert(html.includes("1.12 MiB"));

const hostile = JSON.parse(JSON.stringify(record));
hostile.repository.full_name = "<img src=x onerror=alert(1)>";
hostile.head.subject = "<script>alert(1)</script>";
const escaped = renderer.render(hostile);
assert(!escaped.includes("<script>"));
assert(!escaped.includes("<img src=x"));
assert(escaped.includes("&lt;script&gt;"));
assert(escaped.includes("&lt;img src=x onerror=alert(1)&gt;"));

const invalid = JSON.parse(JSON.stringify(record));
invalid.measurements.working_tree_bytes = -5;
assert.throws(() => renderer.render(invalid), /invalid byte measurement/);

// Optional actual producer output exercises the same read-only renderer.
if (process.argv[2]) {
  const canonical = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const head = canonical.head;
  assert.strictEqual(renderer.commitLine(canonical),
    `Commit ${head.short_sha} · ${head.branch} · ${head.timestamp} · ${head.subject}`);
  const rendered = renderer.render(canonical);
  assert(rendered.includes(canonical.repository.full_name));
  assert.strictEqual((rendered.match(/not measured/g) || []).length, 3);
  assert(!rendered.includes("<script>"));
  assert(rendered.includes("&lt;script&gt;fixture&lt;/script&gt;"));
}
