const assert = require('node:assert/strict');
const { filterItems, normalizeText } = require('../js/collection.js');
const items = [
  { name: 'Aoi', desc: 'Baseball analysis', topics: ['python', 'sports'], archived: false },
  { name: 'Ironmate', desc: 'Slides', topics: ['javascript', 'slides'], archived: false },
  { name: 'Legacy', desc: null, topics: ['python'], archived: true },
];
const snapshot = JSON.stringify(items);
const text = item => [item.name, item.desc, ...(item.topics || [])];
assert.deepEqual(filterItems(items, { query: '  PYTHON  ', text }).map(x => x.name), ['Aoi', 'Legacy']);
assert.deepEqual(filterItems(items, { query: 'python', text, facets: { archived: false } }).map(x => x.name), ['Aoi']);
assert.deepEqual(filterItems(items, { facets: { topic: 'slides', archived: false }, facetValues: { topic: item => item.topics } }).map(x => x.name), ['Ironmate']);
assert.deepEqual(filterItems(items, { query: 'nothing', text }), []);
assert.deepEqual(filterItems(items), items);
assert.deepEqual(filterItems(items, { facets: { archived: undefined } }), items);
assert.deepEqual(filterItems(items, { predicates: [item => !item.archived, item => item.name.length > 3] }).map(x => x.name), ['Ironmate']);
assert.equal(normalizeText(null), '');
assert.deepEqual(filterItems([{name:'日本語'}, {name:'English'}], { query:'日本', text:x=>x.name }), [{name:'日本語'}]);
assert.deepEqual(filterItems([{name: 'x', tag: 0}, {name: 'y', tag: false}], {facets: {tag: false}}).map(x=>x.name), ['y']);
assert.deepEqual(filterItems([null, { name:'ok' }], {facets: {name: 'ok'}}), [{name:'ok'}]);
for (const invalid of [null, {}, 'x']) assert.throws(() => filterItems(invalid), TypeError);
assert.throws(() => filterItems(items, {text: 'name'}), TypeError);
assert.throws(() => filterItems(items, {predicates: [true]}), TypeError);
assert.throws(() => filterItems(items, {facets: {name: 'x'}, facetValues: {name: 'x'}}), TypeError);
assert.equal(JSON.stringify(items), snapshot, 'input items remain unchanged');
console.log('collection filtering contract passed');
