# Consumer-owned catalogs

`catalog_document(spec, theme="modern")` is a small, standard-library-only
assembly entry, not another site framework. It reuses `card`, `badge`, `details`
and `render_document`, returns an HTML string and never reads consumer files,
fetches data, executes Node, or writes a site. Consumers own collection,
provenance, transformations, output paths, tests and publication.

## Input and output

The `web-ui-catalog/1` object has these fields; unknown fields are rejected:

- Required `schema`, `title` (nonempty text, at most 200 characters), `items`.
- Optional `description` (text, at most 4,000 characters).
- `items`: at most 512 objects. Required unique ASCII `id` (letter first,
  then letters, digits, hyphens or underscores; at most 128 characters) and `title` (200 characters).
- Optional item `summary` (4,000), `category` (100), `details` (16,000),
  and `links` (at most 32 objects).
- Each link has exactly `label` (nonempty, at most 200 characters) and `href`
  (nonempty, at most 2,048 characters).

Text is escaped, not trusted HTML. Control characters other than newline/tab,
unpaired Unicode surrogates, duplicate IDs and invalid field types fail closed.
Titles supply the native disclosure labels and index link names. Categories are
badges, not a filtering database. Input order is preserved; the input is not
modified. The HTML uses stable, prefixed anchors, a single h1, native links
and native details, so navigation and disclosure work without JavaScript.

Links allow relative paths (including `../`, query strings and fragments) or
credential-free HTTPS URLs. Root-relative paths, protocol-relative URLs,
backslashes, whitespace and other schemes are rejected. Percent-encode spaces.
The renderer does not check whether a destination exists or is trustworthy and
makes no requests. Consumers must validate their evidence files and choose
external destinations appropriately. Links open in the same tab.

There is no base URL rewriting: `./evidence/result.json` stays beside the generated
page under `/repo-a/` or `/repo-b/nested/`. Consumers must emit the referenced
files at the corresponding paths. A copied `web_ui.py` is sufficient; the output
embeds only core CSS and its selected theme, and requires no web-ui gallery,
brand image, CDN, JavaScript, Python server or storage at runtime.

## Two examples, one entry

Synthetic analysis-report and project-directory input lives in the existing
Python `EXAMPLES` registry; it is not duplicated repository metadata or measured
research. Both use the same API:

```python
from pathlib import Path
from web_ui import catalog_document, example_data

for name in ("catalog-report", "catalog-projects"):
    page = catalog_document(example_data(name))
    Path(name + ".html").write_text(page, encoding="utf-8")
```

Or use the thin CLI:

```sh
python -S web_ui.py --example catalog-report > report.json
python -S web_ui.py --catalog report.json > report.html
```

`--site` retains its existing role and page set: it writes web-ui's own gallery.
Render these consumer examples explicitly through `catalog_document` or `--catalog`.
`--site` is **not** a consumer site-config reader. The `site.config.json` proposal in
`pages-ownership.md` remains a draft and is not silently implemented here.
Example evidence links are illustrative; the example generator does not invent
research outputs or documentation at their targets.

## Adoption boundary

A future markdown consumer can adapt its existing report rows and retain
statistics, image availability, revision metadata and evidence paths. A future
portfolio consumer must first adapt its older `shared_stylesheets()` integration
to Python-generated assets; simply changing its currently consistent old pin
would break that API contract. Neither consumer nor its Pages deployment is
changed by this work. World, motion, flow and local-note behavior is unchanged;
flow generation remains owned by ascii_artist.

## Verification

`python -m unittest discover -s tests -p test_catalog.py -v` tests schemas,
Unicode/escaping, link validation, deterministic output, source immutability,
portable paths and an isolated `python -I -S` single-file CLI.

The existing Chromium `tests/integration/controls_browser.py` lane also tests
both catalogs at mobile/desktop widths over HTTP project subpaths and `file://`,
with JavaScript disabled. It checks native keyboard/repeated disclosure,
Back/Forward, evidence navigation and lack of external requests. Its HTTP
screenshots are preserved under the existing `build/gradio-dom` artifact path.
Existing tests and CI settings remain unchanged apart from adding test coverage.
Capacity and installation/runtime speed improvements are not claimed.
