# Lightweight JavaScript and verification lanes

## Acceptance bar for lightweight JS

Pages UIs may use CSS, GIF, and lightweight JavaScript. Heavy frameworks and npm
runtime dependencies are out of scope for shared web-ui assets.

Acceptable lightweight JS meets all of:

1. Very few dependencies, so version upgrades stay easy
2. Referable like a CDN or Deno import (URL or single vendored file), without a
   consumer build step
3. Little prerequisite tooling and a small persistent cache/build environment;
   source KB/MB and network transfer size alone do not define lightweight

web-ui’s first-party ES modules (`js/ui.js`, `js/stub.js`,
`js/repository-diagnostics.js`) already sit inside this bar. Execution JS must
be owned and version-pinned by the project. Do not execute arbitrary JavaScript
found inside API responses.

## Python layout wrapper

`web_ui.py` is the stdlib one-liner surface for layout-including static output:

```sh
python -S -c 'from web_ui import render_document; print(render_document("Hello"))'
printf 'Hello' | python -S web_ui.py --title Demo > demo.html
printf 'Hello' | python -S web_ui.py --asset-base . --with-scripts ui.js > demo.html
```

Scripts are omitted by default. `--with-scripts` / `shared_scripts()` only emit
`<script type="module" src="...">` links for local managed assets only.
`shared_scripts()` accepts only the known first-party names. Direct
`render_document(scripts=(...))` accepts caller-selected local module paths with
the same validation: relative or root-relative paths, no scheme/authority,
query, fragment, whitespace, control characters or backslashes. HTTPS URLs are
rejected on the local module path even if they look versioned.

### Opt-in remote classic scripts

`remote_scripts()` is the separate, explicit allowlist for HTTPS classic scripts
that are not ES modules. It does not weaken `shared_scripts()` or local
`scripts=` validation. Each name maps to one documented URL; callers opt in by
name and pass the returned tuple to `render_document(remote_scripts=...)`.
Remote tags are emitted in `<head>` so trusted body inline initializers can
depend on them. There is no generic remote URL API and no caller-supplied SRI
argument. Pinned allowlist entries whose bytes are immutable are emitted with
`integrity` and `crossorigin="anonymous"`. Rolling entries omit SRI because a
moving URL has no stable hash. Consumers own CSP and network access.

Current allowlist entries:

- `plotly.js` → `https://cdn.plot.ly/plotly-latest.min.js` (unpinned latest lane; no SRI)
- `pptxgenjs` → `https://cdn.jsdelivr.net/npm/pptxgenjs@4.0.1/dist/pptxgen.bundle.js`
  (pinned 4.0.1 browser bundle, JSZip included;
  `sha384-qb0Xhi7LLYpvW1HCK6oMrmDLSY9sy7vwm6ZlV6KjtrlL9yg30+YN4neTwnmX+Kp8`)

The separate `pptxgen.min.js` build expects a global `JSZip` and is not the
allowlist entry. Recompute the sha384 from the pinned bundle bytes before
changing the version. Further allowlist names can be added without changing
the local module policy.

Stylesheet links retain their existing local/HTTPS behavior.

The wrapper guarantees link syntax and opt-in emission, not immutable bytes or
provenance. Before opting in, callers must vendor audited modules at an exact
commit, retain/verify their lock and hashes, and serve that snapshot alongside
the document. Callers also own module imports and must avoid remote redirects
or a remote document base. A local filename alone is not evidence of a pin.
`shared_scripts()` does not inspect the filesystem or fetch assets, and direct
`scripts=` does not restrict filenames to the first-party name list.

`trusted_html` / `--trusted-html` remains an explicit trust escape hatch: it is
emitted verbatim and can contain script tags, event handlers or a `<base>` that
changes relative URL resolution. Its caller must audit all of that HTML; link
validation is not an HTML sanitizer or a document-wide execution sandbox.
The wrapper generates inline classic scripts only through explicit helpers such
as `classic_script()`, `plotly_figure()`, and `pptx_presentation()`; it does
not download packages or assemble Office XML.

## Node wrapping for pytest

Browser protocol behavior stays outside web-ui. Existing Node checks (for
example `tests/repository_diagnostics.node.js`) are wrapped for pytest as:

```python
from web_ui import run_node
assert run_node("tests/repository_diagnostics.node.js").returncode == 0
```

`run_node` is a thin stdlib subprocess helper. It does not start Playwright, CUA,
or an in-app browser.

## Live DOM checks stay on the agent `/js` lane

Manual or agent confirmation of a published public page may use the Node REPL
`/js` path, for example:

```js
const browser = await cua.getBrowser({url: 'https://github.com/myon-bioinformatics/mcp-toolcall-lab'});
```

```js
const tab = await browser.tabs.new();
await tab.goto('https://github.com/myon-bioinformatics/mcp-toolcall-lab');
nodeRepl.write(await tab.playwright.domSnapshot());
```

That lane verifies a live published surface. It is not a Pages runtime
dependency, not a substitute for offline pytest, and not vendored into web-ui.
CI continues to use Python layout generation plus explicit Node wrappers and the
existing screenshot evidence jobs.

## Candidate catalogue

See [lightweight JS candidates and documentation tips](lightweight-js-candidates.md)
for declared evaluation scope, official URLs and observed documentation DOM gaps.

## Optional Deno tooling

Python remains the default. Deno is a candidate for concrete JS/TS reuse or asset
preparation needs, not a required browser launcher or a duplicate HTML reader.
See [Deno scope and real HTML/DOM evidence](deno-tooling-candidate.md).

## Shared source links and view switching

`navigation.js` is a dependency-free first-party UMD module (also usable as a
side-effect ES module). It never fetches URLs or writes storage. Python emits
escaped controls in one call; the consumer pins/copies the module and opts in:

```sh
python -S -c 'from web_ui import source_link; print(source_link("source-url"))'
python -S -c 'from web_ui import view_tabs; print(view_tabs((("home","Home"),("wiki","Wiki"))))'
```

Pair `source_link()` with a caller-authored input whose id matches `input_id`.
`shared_scripts("./vendor/web-ui", names=("navigation.js",))` emits the local
module link; `render_document` remains JS-free by default. Loading the module
binds declared `data-ui-source-for` links and `data-ui-view`/`data-ui-nav` panels.
Only an explicit link click navigates. Empty, credentialed, non-HTTP(S), whitespace
and backslash-containing URLs are rejected. New tabs use noopener/noreferrer.
Normal remote navigation is distinct from browser fetch, proxying, raw source
capture, and same-input extraction reuse.

For existing markup, `webUiNavigation.bindSourceLink(input, anchor)` and
`webUiNavigation.bindViews(window, {viewAttribute: "data-pages-view",
navAttribute: "data-pages-nav", queryAliases: {wiki: "wiki"}})` are single-call
JS bindings. Duplicate binding returns the existing handle; `destroy()` removes
its event listeners. View names come from declared panels; unknown hashes fall
back to home. Optional explicit legacy `?view=wiki` aliases retain query priority
and canonicalize to `#wiki`, preserving other query fields. No alias is enabled
by default. `openExternalURL(url, window)` supplies the same HTTP(S) validation
and new-tab policy to legacy consumers' existing buttons.

## Plotly figure specs without the Python plotly package

Consumers such as Aoi/DRAgoWing can render charts from a Plotly figure JSON
spec using stdlib-only helpers. No `pip install plotly` is required; the browser
loads plotly.js from the opt-in CDN allowlist.

```sh
python -S -c 'from web_ui import plotly_figure, render_document, remote_scripts; spec={"data":[{"type":"scatter","x":[1,2],"y":[3,4]}]}; print(render_document(trusted_html=plotly_figure(spec), remote_scripts=remote_scripts("plotly.js")))' > chart.html
```

`plotly_figure(spec, *, div_id="plot", height=400, width=None)` returns trusted
HTML: a `ui-panel` graph container and an inline classic script that calls
`Plotly.newPlot` with the JSON fields `data`, `layout`, and `config`. Pass
`remote_scripts("plotly.js")` to `render_document` (or `--with-remote-scripts
plotly.js` on the CLI) so plotly.js loads before the initializer runs.

## PowerPoint files from a JSON slide spec

`pptx_presentation()` is the generic browser download helper for PptxGenJS.
Python validates a JSON slide spec and emits a button plus an inline classic
script. The browser constructs the `.pptx` with `writeFile`. web-ui does not
unzip the package, post-process OOXML, or patch PowerPoint-app compatibility
markup; that stays in the consumer repository (Ironmate, for example). Diagram
layouts and visual styles also stay in the consumer spec. This repository only
provides the allowlist entry, the spec helper, and the arrow geometry below.

```sh
python -S -c 'from web_ui import pptx_connector, pptx_presentation, render_document, remote_scripts; spec={"fileName":"flow.pptx","layout":"LAYOUT_WIDE","slides":[{"items":[{"id":"a","kind":"text","text":"A","x":0.5,"y":1.5,"w":2.2,"h":0.8,"options":{"shape":"roundRect","align":"center","valign":"middle"}},{"id":"b","kind":"text","text":"B","x":4.0,"y":1.5,"w":2.2,"h":0.8,"options":{"shape":"roundRect","align":"center","valign":"middle"}},{"id":"c","kind":"text","text":"C","x":2.2,"y":3.4,"w":2.2,"h":0.8},pptx_connector("a","b"),pptx_connector("b","c"),{"kind":"table","rows":[["Step","Note"],["1","Generic"]],"x":7.0,"y":1.5,"w":5.0,"h":1.2}]}]}; print(render_document(trusted_html=pptx_presentation(spec), remote_scripts=remote_scripts("pptxgenjs")))' > deck.html
```

Item `kind` is `text`, `shape`, `line`, `table`, `image`, or `connector`.
Positions are inches. Pass `remote_scripts("pptxgenjs")` or
`--with-remote-scripts pptxgenjs` so the pinned bundle loads before the click
handler runs. Images use an HTTPS `path` or an `image/...;base64,...` `data`
value.

### Arrows are a line plus a triangle

`pptx_connector("a", "b")` does not use PptxGenJS line arrows
(`endArrowType` / `beginArrowType`) or the built-in connector shape. The helper
expands the connector into a straight `line` shape and a separate `triangle`
centered on the midpoint (half the segment length). The triangle starts
pointing up; `rotate` turns it clockwise to the line angle (approximate degrees
are enough).

- `mode="edge"` (default) follows the center-to-center ray and stops on each
  box boundary. Side-by-side boxes join the facing sides (right edge to left
  edge when the target is to the right). A box below or above another joins the
  bottom and top edges when that is the edge the ray crosses.
- `mode="center"` joins the centers. Those lines are drawn first (`back`) so
  later objects cover the part inside each box, and the arrowhead stays in
  front. The visible remainder between the objects is the arrow.

`pptx_arrow_geometry(source_box, target_box)` returns the same coordinates
without HTML, for a consumer that wants to place the line and triangle itself.

For an existing **trusted static export**, Python can reuse presentation in one
call instead of cloning the theme: `adopt_document(page, asset_base="./vendor",
class_aliases={"old-page":"ui-page"}, remove_stylesheets=("legacy.css",))`.
It requires audited double-quoted export markup, preserves IDs/scripts/report
contents and adds shared control classes. It is not an HTML sanitizer or an
input parser. The consumer must preserve original source hashes and record the
published presentation transform/hash; theme adoption is not a fresh report run.
