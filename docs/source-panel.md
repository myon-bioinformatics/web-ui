# Source panel

A reusable panel that reads **one JSON response** (asked for by name, or pasted) into **Markdown tables**. The consumer supplies only a small JSON `spec`; the panel, its
script and its stylesheet are `web_ui.py` data, so a consumer writes no JavaScript or CSS for it.

```python
import web_ui
spec = json.loads(Path("pokeapi.spec.json").read_text(encoding="utf-8"))
page_html = web_ui.source_panel_html(spec)          # the panel (the spec rides in a data attribute)
web_ui.bundled_css()                                  # includes source.css (or css_source / --css-bundle)
web_ui.js_source("source.js")                         # classic <script>; binds every [data-ui-source]
extract = web_ui.source_extract(spec, response_text)  # {"title", "tables": [{"headers", "rows"}]}
markdown = web_ui.source_markdown(extract)
```

`python -S web_ui.py --site DIR` writes `DIR/js/source.js`. The panel never ships a network address of its own: the spec names it.

## The spec

| key | meaning |
| --- | --- |
| `id` | lower-case token; ids in the panel are `source-<id>`, `<id>-name`, `<id>-text` |
| `label`, `heading`, `note`, `placeholder` | texts (at most 400 characters; `heading` defaults to `label`) |
| `name` | pattern the trimmed, lower-cased name must match **entirely** (plain ASCII, no `(?`; Python `re.ASCII` and JavaScript read it the same) |
| `url` | `https://…` with exactly one `{name}` (percent-encoded as `encodeURIComponent`), no credentials |
| `title` | text; `{key}` takes a top-level scalar (a dot path works too) |
| `tables` | one to eight tables, below |
| `limit` | most bytes of text read (default and maximum 2 MiB) |
| `error`, `missing` | message for an unexpected response / an invalid name |

A table is `{"headers": [...], "rows": [[cell, ...]]}` (one row per list) or `{"headers": [...], "each": "path", "sort"?: "path", "cells": [cell, ...]}` (one row per item
of the list at `path`, sorted by a number when `sort` is given). A cell is `{"key": "dot.path"}` plus at most one of:

- on a list: `sort` (a number path), `pick` (a path inside each item), `sep` (default `", "`)
- `div` (a nonzero number the value is divided by; shown with one decimal when whole, else as the shortest number)
- `yes` (a boolean shown as this text when true, empty when false)

Whole floats print as integers (`1.0` → `1`), booleans as `true`/`false`, `null` as empty; an object where text is expected, a missing key or a wrong type is the spec's `error`.
In Markdown cells `|` becomes `\|` and line breaks become spaces. The shared behaviour covers numbers a double holds exactly (integers up to 2^53, ordinary decimals); beyond that Python keeps exact integers where JavaScript rounds.

## Behaviour

- **Fetch** sends one `GET` (`Accept: application/json`, no credentials, no referrer, redirects refused) per press, never retries, and ignores a second press while one is in flight.
- **Open JSON** opens the spec's address in a new tab (`noopener,noreferrer`) so the response can be copied and pasted when the browser blocks the request (CORS).
- **Extract** reads pasted JSON with no network at all. Nothing is stored.
- Failures (`not found: x`, `HTTP 500`, `source is not JSON`, the spec's `error`, a blocked request) are shown in a `role="alert"` line; results in a `<pre class="ui-output">`.

## Example: PokéAPI

`tests/fixtures/source/pokeapi.spec.json` is the whole PokéAPI consumer. For `ditto` it gives the Markdown that mcp-toolcall-lab's `adapters/pokeapi.py` writes, byte for byte
(`tests/fixtures/source/ditto.md`), so a consumer can drop its own panel, script and stylesheet and keep only this spec.

## Tests

`tests/test_source_panel.py` (spec validation, panel HTML, bundle) and `tests/source.node.js` (Node 26+) run the same `tests/fixtures/source/cases.json`; `tests/integration/source_browser.py`
runs the panel in Chromium (`file://` and HTTP, the network answered by the browser's own request layer).
