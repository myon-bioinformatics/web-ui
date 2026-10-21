# Build-free collection filtering: Python and Node

This extends the browser `js/collection.js` module with **two independent
runtime entrypoints** for the same JSON input/output contract. Neither CLI
requires npm, pip, compilation, a network connection, or the other runtime.

```sh
printf '%s\n' '{"items":[{"name":"Aoi","topics":["python"]},{"name":"Ironmate","topics":["js"]}],"query":"PYTHON","text_fields":["name","topics"]}' | python -S collection_filter.py
printf '%s\n' '{"items":[{"name":"Aoi","topics":["python"]},{"name":"Ironmate","topics":["js"]}],"query":"PYTHON","text_fields":["name","topics"]}' | node js/collection-cli.cjs
```

Both print `[{"name":"Aoi","topics":["python"]}]` and a newline. Contract:

- Input: one JSON object on stdin; `items` is a required array of objects.
- Optional `query` string (case-insensitive trimmed substring);
  `text_fields` is a nonempty array of top-level field names (default `["name"]`).
  Array-valued text fields are searched elementwise.
- Optional `facets` maps top-level field names to exact scalar JSON values.
  Array-valued item fields match by membership; multiple facets use AND.
  Missing fields behave like null for a null facet. Do not use a magic "all".
- Output: selected original objects, in input order, as one JSON array on
  stdout, followed by newline. JSON structure, not byte-identical key order
  or whitespace, is the parity contract.
- Exit 0: valid request (including zero matches). Exit 2: invalid JSON,
  invalid contract, or processing error; stdout remains empty and stderr
  carries a diagnostic. No partial result is presented as success.
- Neither implementation mutates the input or downloads dependencies.
  Node uses `js/collection.js`; Python uses the stdlib only.
- The browser-specific callback API stays in `js/collection.js`; arbitrary
  JavaScript functions are **not** serialized into the JSON contract.

`tests/fixtures/collection_filter_cases.json` is shared across both languages.
Run `python -S collection_filter.py` with JSON stdin, `python -m pytest
tests/test_collection_filter.py`, and `node --test tests/collection-cli.node.cjs`.
A consumer should pin the source revision and verify its bytes before vendoring.
