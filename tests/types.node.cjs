"use strict";
// Every js/*.cjs ships a .d.cts whose exported names match the runtime exports exactly.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const dir = path.join(__dirname, "..", "js");
for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".cjs")).sort()) {
  test(`${file} has matching .d.cts`, () => {
    const types = path.join(dir, file.replace(/\.cjs$/, ".d.cts"));
    assert.ok(fs.existsSync(types), `missing ${path.basename(types)}`);
    const declared = [...fs.readFileSync(types, "utf8").matchAll(/^export (?:function|const) ([A-Za-z_$][\w$]*)/gm)]
      .map((m) => m[1]);
    assert.deepEqual([...new Set(declared)].sort(), Object.keys(require(path.join(dir, file))).sort());
  });
}
