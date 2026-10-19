"use strict";
const assert = require("node:assert/strict");
const {test} = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const {spawnSync} = require("node:child_process");
const {css, controlsHtml, validate} = require("../js/layout-presets.cjs");
const root = path.resolve(__dirname, "..");
const file = path.join(root, "examples/layout-presets.json");
const spec = JSON.parse(fs.readFileSync(file, "utf8"));
const python = (args) => spawnSync(process.env.PYTHON || "python3", ["-S", path.join(root, "tool/layout_presets.py"), ...args], {encoding: "utf8"});
test("Node and Python produce identical CSS and controls", () => {
  const pyCss = python(["css", file]);
  if (pyCss.error) return; // no Python on this runner: the Python suite covers it
  assert.equal(pyCss.status, 0, pyCss.stderr);
  assert.equal(css(spec), pyCss.stdout);
  assert.equal(controlsHtml(spec) + "\n", python(["html", file]).stdout);
});
test("labels come from candidates and nothing is disabled", () => {
  const html = controlsHtml(spec, {schema: "web-ui-layout-candidates/1", presets: {wide: {passed: [1280], failed: [320]}}});
  assert(html.includes("ok at 1280px; check at 320px") && html.includes("not checked") && !html.includes("disabled"));
});
test("invalid presets are rejected like Python", () => {
  assert.throws(() => validate({...spec, schema: "x"}));
  assert.throws(() => validate({...spec, presets: [{id: "a", label: "x", vars: {"--ui-a": "1px;}body{x:1px"}}]}));
  assert.throws(() => validate({...spec, presets: [{id: "a", label: "x", vars: {"--ui-a": "1px"}}, {id: "b", label: "y", vars: {"--ui-b": "1px"}}]}));
  assert.throws(() => validate({...spec, default: "nope"}));
});
