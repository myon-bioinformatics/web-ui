"use strict";
// Every js/*.cjs has a js/*.d.cts that declares exactly its exports (names; tsc checks the types in CI).
const assert = require("node:assert/strict");
const {test} = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const dir = path.resolve(__dirname, "../js");
const declared = (file) => [...fs.readFileSync(file, "utf8").matchAll(/^export (?:function|const) (\w+)/gm)].map((m) => m[1]);
for (const name of fs.readdirSync(dir).filter((f) => f.endsWith(".cjs")).sort()) {
  test(`js/${name} exports match js/${name.replace(/\.cjs$/, ".d.cts")}`, () => {
    const types = path.join(dir, name.replace(/\.cjs$/, ".d.cts"));
    assert(fs.existsSync(types), `missing ${path.basename(types)}`);
    assert.deepEqual([...new Set(declared(types))].sort(), Object.keys(require(path.join(dir, name))).sort());
  });
}
