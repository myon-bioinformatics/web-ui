/* Portable, DOM-free collection filtering. Domain semantics stay with consumers. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WebUICollections = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function normalizeText(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
  }

  function matchesFacet(actual, expected) {
    if (Array.isArray(actual)) return actual.includes(expected);
    return actual === expected;
  }

  /**
   * Filter without modifying items or relying on DOM/network globals.
   *
   * text(item) may return a scalar or an array of searchable fields.
   * facets is an object of exact selected values. If an item's facet value
   * is an array, membership is tested. Omit inactive facets (no 'all' magic).
   * facetValues optionally maps facet names to item accessors.
   * predicates is an optional array of additional AND conditions.
   */
  function filterItems(items, options = {}) {
    if (!Array.isArray(items)) throw new TypeError('items must be an array');
    if (!options || typeof options !== 'object') throw new TypeError('options must be an object');
    const { query = '', text = item => item, facets = {}, facetValues = {}, predicates = [] } = options;
    if (typeof text !== 'function') throw new TypeError('text must be a function');
    if (!facets || typeof facets !== 'object' || Array.isArray(facets)) throw new TypeError('facets must be an object');
    if (!facetValues || typeof facetValues !== 'object' || Array.isArray(facetValues)) throw new TypeError('facetValues must be an object');
    if (!Array.isArray(predicates) || predicates.some(fn => typeof fn !== 'function')) throw new TypeError('predicates must be functions');
    const needle = normalizeText(query);
    const selected = Object.entries(facets).filter(([, value]) => value !== undefined);
    for (const [key] of selected) {
      if (Object.prototype.hasOwnProperty.call(facetValues, key) && typeof facetValues[key] !== 'function') {
        throw new TypeError('facetValues entries must be functions');
      }
    }
    return items.filter(item => {
      if (needle) {
        const raw = text(item);
        const fields = Array.isArray(raw) ? raw : [raw];
        if (!fields.some(field => normalizeText(field).includes(needle))) return false;
      }
      for (const [key, expected] of selected) {
        const actual = Object.prototype.hasOwnProperty.call(facetValues, key) ? facetValues[key](item) : item?.[key];
        if (!matchesFacet(actual, expected)) return false;
      }
      return predicates.every(predicate => predicate(item));
    });
  }

  return { filterItems, normalizeText };
});
