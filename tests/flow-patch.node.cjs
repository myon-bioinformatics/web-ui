"use strict";
const assert = require("node:assert/strict");
const {test} = require("node:test");
const fs = require("node:fs");
const {patchFlow} = require("../js/flow-patch.cjs");
const sample = JSON.parse(fs.readFileSync("examples/pr-flow.json", "utf8"));
test("patches update one field and leave input intact", () => {
  const old = JSON.stringify(sample);
  const next = patchFlow(sample, [{path:"/steps/0/note",value:"merged"}]);
  assert.equal(JSON.stringify(sample), old);
  assert.equal(next.steps[0].note, "merged");
  assert.deepEqual(patchFlow(next, []), next);
});
test("invalid late patch does not mutate input", () => {
  const old = JSON.stringify(sample);
  assert.throws(() => patchFlow(sample, [
    {path:"/title",value:"new"}, {path:"/steps/99/note",value:"bad"}]));
  assert.equal(JSON.stringify(sample), old);
});
