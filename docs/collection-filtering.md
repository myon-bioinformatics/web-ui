# Collection filtering (portable JavaScript)

`js/collection.js` is a dependency-free UMD module for browsers and Node.
It does not fetch data, access DOM/storage, or define domain-specific fields.

Browser: `<script src="collection.js"></script>` exposes `WebUICollections`.
Node: `const { filterItems } = require('./js/collection.js');`

```js
const visible = WebUICollections.filterItems(projects, {
  query: searchInput.value,
  text: p => [p.name, p.desc, ...(p.topics || [])],
  facets: { archived: false, topic: 'python' },
  facetValues: { topic: p => p.topics || [] },
});
```

Search is trimmed, case-insensitive substring matching across scalar/array text
fields. Facets and optional predicate callbacks are combined with AND.
Facet values use strict equality; if an item field is an array, selected-value
membership is used. Omit an inactive facet entirely (there is no magic
`all` value). `undefined` selections are ignored, but `false`, `0`,
`null`, and empty strings are explicit values. Input items are not mutated.

Consumer responsibilities: load/canonicalize data, decide fallback and
error behavior, validate external URLs, preserve UI selection state, and
render results. The portfolio keeps repository membership in `api/repos.json`,
not this generic module. Browser-test-kit keeps browser/platform semantics.

Run: `node tests/collection.node.cjs`.
