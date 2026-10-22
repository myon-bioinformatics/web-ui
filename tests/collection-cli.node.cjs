'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { filterRequest } = require('../js/collection-cli.cjs');
const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/collection_filter_cases.json'), 'utf8'));
test('shared collection filter fixtures and Node stdin CLI', () => {
  for (const c of fixture.cases) {
    assert.deepEqual(filterRequest(c.request), c.expected, c.name);
    const result = spawnSync(process.execPath, [path.join(root, 'js/collection-cli.cjs')], {input: JSON.stringify(c.request), encoding:'utf8'});
    assert.equal(result.status, 0, c.name + ': ' + result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), c.expected, c.name);
  }
});
test('invalid requests and malformed JSON fail closed', () => {
  for (const request of fixture.invalid) {
    assert.throws(() => filterRequest(request));
    const result = spawnSync(process.execPath, [path.join(root, 'js/collection-cli.cjs')], {input: JSON.stringify(request), encoding:'utf8'});
    assert.equal(result.status, 2);
    assert.equal(result.stdout, '');
  }
  for (const input of ['{', '{"items":[],"query":NaN}', '{"items":[]} trailing']) {
    const result = spawnSync(process.execPath, [path.join(root, 'js/collection-cli.cjs')], {input, encoding:'utf8'});
    assert.equal(result.status, 2);
    assert.equal(result.stdout, '');
  }
});
