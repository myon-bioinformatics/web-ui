#!/usr/bin/env node
/* JSON stdin/stdout adapter around the existing build-free web-ui collection.js. */
'use strict';
const fs = require('node:fs');
const { filterItems } = require('./collection.js');

function filterRequest(request) {
  if (!request || typeof request !== 'object' || Array.isArray(request)) throw new TypeError('request must be an object');
  if (!Array.isArray(request.items) || request.items.some(item => !item || typeof item !== 'object' || Array.isArray(item))) {
    throw new TypeError('items must be an array of objects');
  }
  const query = request.query === undefined ? '' : request.query;
  if (typeof query !== 'string') throw new TypeError('query must be a string');
  const fields = request.text_fields === undefined ? ['name'] : request.text_fields;
  if (!Array.isArray(fields) || fields.length === 0 || fields.some(f => typeof f !== 'string' || !f)) {
    throw new TypeError('text_fields must be a nonempty array of field names');
  }
  const facets = request.facets === undefined ? {} : request.facets;
  if (!facets || typeof facets !== 'object' || Array.isArray(facets) ||
      Object.values(facets).some(value => value !== null && typeof value === 'object')) {
    throw new TypeError('facets must map field names to scalar JSON values');
  }
  return filterItems(request.items, {
    query,
    text: item => fields.flatMap(field => Array.isArray(item[field]) ? item[field] : [item[field]]),
    facets,
  });
}

if (require.main === module) {
  try {
    const input = fs.readFileSync(0, 'utf8');
    process.stdout.write(JSON.stringify(filterRequest(JSON.parse(input))) + '\n');
  } catch (error) {
    process.stderr.write('error: ' + error.message + '\n');
    process.exitCode = 2;
  }
}
module.exports = { filterRequest };
