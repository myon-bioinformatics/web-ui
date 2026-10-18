"use strict";
const assert = require("node:assert/strict");
const {test} = require("node:test");
const fs = require("node:fs");
const {spawnSync} = require("node:child_process");
const path = require("node:path");
const {flowHtml, flowMermaid, validate} = require("../js/flow.cjs");
const root = path.resolve(__dirname, "..");
const fixture = JSON.parse(fs.readFileSync(path.join(root, "examples/pr-flow.json"), "utf8"));
test("HTML contract is static and escaped", () => {
  const output = flowHtml(fixture);
  assert.equal((output.match(/<li /g) || []).length, 5);
  assert(!output.includes("<script"));
  const hostile = {title:'"><script>alert(1)</script>', sources:[{title:"A"}], steps:[{title:"B"}]};
  assert(!flowHtml(hostile).includes("<script>"));
});
test("Mermaid has complete fan-in and step edges", () => {
  const md = flowMermaid(fixture);
  assert(md.startsWith("```mermaid\n"));
  for (let i = 0; i < 3; i++) assert(md.includes("S" + i + " --> T0"));
  assert(md.includes("T0 --> T1"));
});
test("invalid labels and unexpected properties fail closed", () => {
  assert.throws(() => validate({title:"A",sources:[{title:"B",html:"<script>"}],steps:[{title:"C"}]}));
  assert.throws(() => validate({title:"A",sources:[{title:"B\nC"}],steps:[{title:"D"}]}));
});
test("Node and Python produce matching Mermaid fixture", () => {
  const input = JSON.stringify(fixture);
  const node = spawnSync(process.execPath, ["js/flow.cjs", "--format", "mermaid"], {cwd:root,input,encoding:"utf8"});
  const py = spawnSync(process.env.PYTHON || "python3", ["-S", "-m", "tool.flow_diagram", "--format", "mermaid"], {cwd:root,input,encoding:"utf8"});
  assert.equal(node.status, 0, node.stderr);
  assert.equal(py.status, 0, py.stderr);
  assert.equal(node.stdout, py.stdout);
});
