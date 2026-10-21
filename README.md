# web-ui

Shared CSS themes, semantic UI components, and small JavaScript utilities for static interfaces across myon-bioinformatics projects.

**Static-first · build-free runtime · dependency-light · cross-repository**

## v1 foundation

```text
css/
  tokens.css
  base.css
  components.css
  stub.css
  themes/
    modern.css
js/
  ui.js
  stub.js
examples/
  index.html
  mcp-stub.html
  api-stub.html
tests/
```

Modern is the default theme, not the only theme. `github-like` is the first alternate theme using the same semantic `ui-*` / `stub-*` contract.

Generic JavaScript handles browser behavior and rendering helpers. MCP/API protocol semantics remain in consuming repositories.

## Themes

Current themes:

- `modern` — terminal/monospace-oriented default
- `github-like` — generic light presentation intentionally using familiar GitHub visual cues

Theme files are presentation-only. Consumers keep the same semantic HTML and
switch `data-ui-theme` plus the loaded theme stylesheet.

The alternate-theme example is available at
`examples/github-like.html`, and CI captures desktop/mobile screenshots for it.

Theme screenshot filenames follow
`web-ui-<theme>-<viewport-name>.png`, for example
`web-ui-github-like-mobile-390x844.png`. The 390x844 capture is the responsive
contract evidence: `.ui-grid` collapses through the existing mobile component rule.

## HTML contract v1

The v1 compatibility surface is now frozen under
[`contract/v1/`](./contract/v1/):

- `contract.json` — machine-readable source of truth
- `README.md` — normative compatibility rules
- `example.html` — canonical structural fixture used by CI
- [`contract/COMPAT.md`](./contract/COMPAT.md) — version-lane coexistence policy

Within v1, stable classes may be extended but are not removed or semantically
repurposed. Breaking semantic changes require v2.

Consumers should treat the semantic HTML surface as the reusable contract:

- shared presentation classes use the `ui-*` namespace
- Stub-specific presentation classes use the `stub-*` namespace
- themes are selected with `data-ui-theme` on `body`
- consumers own content, protocol semantics, validation, and domain behavior
- user-controlled text should be rendered as text, not interpreted as HTML

Modern theme usage:

```html
<link rel="stylesheet" href="css/tokens.css">
<link rel="stylesheet" href="css/base.css">
<link rel="stylesheet" href="css/components.css">
<link rel="stylesheet" href="css/themes/modern.css">

<body data-ui-theme="modern">
  <main class="ui-page">
    <section class="ui-panel">...</section>
  </main>
</body>
```

A future theme should be able to replace `modern.css` and the `data-ui-theme` value without changing the semantic component structure.

### Stub workspace pattern

`examples/mcp-stub.html` and `examples/api-stub.html` share the same
responsive `stub-*` workspace. On wider viewports, the primary result pane
sits beside a secondary evidence/history sidebar. At `max-width: 720px`, the
workspace reflows to one column and the supporting region follows the result.

`.stub-meta` is for compact status or capability badges associated with the
tool page. `.stub-endpoint` is deliberately presentation-only: consumers
replace the placeholder with their own endpoint or connection label, while
request construction, protocol behavior, validation, history, evidence, and
export behavior remain consumer-owned.

For example:

```html
<div class="stub-meta">
  <span class="ui-tag">mcp</span>
  <span class="ui-tag">ready</span>
</div>
<p class="stub-status">
  Endpoint: <span class="stub-endpoint">/consumer-owned-endpoint</span>
</p>
```

The shared examples are structural fixtures, not reference implementations of
MCP or API semantics.

## Local preview

```sh
python -m http.server 8000
```

Open `http://localhost:8000/examples/index.html`.

## UI verification

Run the static contract checks locally:

```sh
python -m unittest discover -s tests -v
```

The `-v` output identifies the failing contract by test name. If a browser screenshot fails in CI, inspect the `UI smoke` job first; successful screenshot runs publish the `web-ui-screenshots` artifact.

GitHub Actions captures Chromium screenshots at two explicit v1 viewports:

- `desktop-1440x900`
- `mobile-390x844`

Screenshot filenames follow `web-ui-<viewport-name>.png`. New viewport or locale variants should extend the descriptive suffix rather than replace the existing names, for example `web-ui-tablet-768x1024.png` or `web-ui-mobile-390x844-ja.png`.

The first phase intentionally treats screenshots as observable test evidence rather than a pixel-perfect blocking regression test.

## Visual regression

The deterministic Chromium screenshot lane now also runs
`scripts/check_visual_regression.py`.

The rollout is intentionally two-stage:

1. candidate mode: screenshots are validated as PNGs and compared when a reviewed
   baseline exists;
2. enforcement mode: `--require-baseline` can be enabled once all stable
   contract fixtures have reviewed baselines.

Baseline updates are reviewed UI changes, not automatic CI output.

The checker requires an existing candidate directory and emits an explicit
setup error if no PNGs match the configured pattern. By default it considers
`web-ui-*.png`; `--pattern` can narrow enforcement to stable contract
fixtures before examples/gallery captures become blocking.

CI currently runs the checker with Python 3.12. The script uses Python 3.9+
built-in generic type syntax such as `tuple[int, int]`.

## Roadmap

- expand the component gallery
- consolidate Ironmate metadata-only discovery in the portfolio; retain working consumer demos
- add API/MCP Stub patterns without moving domain logic into web-ui
- expand themes beyond Modern and GitHub-like
- keep HTML contract v1 stable while `markdown.py` and `ascii_artist` integrations adopt it

See #1 for the bootstrap plan.


## Development tooling

Browser/UI verification keeps two separate lanes: deterministic Playwright/Chromium smoke tests and optional Stagehand v4 agent-oriented experiments. Git/gh and Python tool versions are captured as advisory CI metadata. Repository identity comes only from the pinned canonical Python producer, in separate JSON/JSONL artifacts. See [TOOLING.md](./TOOLING.md).

## Shared screenshot checks

CI checks all six named Chromium desktop/mobile PNGs with browser-test-kit at
`6a2e32a4bbe49be5268e6b30040d665a89eecf66`, checked out separately in the screenshot job.
See the [shared screenshot guide](https://github.com/myon-bioinformatics/browser-test-kit/blob/6a2e32a4bbe49be5268e6b30040d665a89eecf66/docs/screenshot-evidence.md).
The shared structural PNG checks supplement the existing local candidate/baseline
comparison. Missing/invalid required captures fail CI; available PNGs are uploaded
even after failure (14 days). This lane does not measure Firefox/WebKit; image validity does not establish semantic correctness.

The screenshot lane now seals a current-run multi-image receipt via pinned
browser-test-kit, requires all six PNGs and their recorded SHA-256/size, and
checks the explicit tested head SHA plus run ID/attempt. Output is cleared before
capture. Failed receipts are preserved but cannot cover required success. CI also
mutates isolated copies of the real bundle to prove rejection of missing images,
wrong hashes, stale run IDs and failed receipts. These are integrity/run checks;
they add no screen-content or pixel-regression assertions.

Public source placement and automatic Python CI updates: [vendor automation](docs/vendor-automation.md).

## Multi-browser captures of Flutter pages

`examples/flutter-pages.json` lists the representative flutter_navigation_basic pages by emoji
(route table + published URL), and `tool/capture_matrix.py` turns browser-test-kit captures and
Ironmate's comparison sheet into a static viewer opened by emoji. See [capture matrix](docs/capture-matrix.md).

## Python static wrapper

`web_ui.py` is a portable, stdlib-only HTML emitter for Python 3.10+. It accepts
text or explicitly authored HTML and CSS. It neither downloads assets nor needs
npm, Deno, a browser, or an installed Python package. Layout output is meant for
Python/`pytest` one-liners. JavaScript is omitted by default; shared modules may
be linked explicitly. `run_node()` wraps existing Node checks for the same
pytest lane.

```sh
python -S -c 'from web_ui import render_document; print(render_document("Hello"))'
printf 'Hello <world>' | python -S web_ui.py --title Demo > demo.html
printf '<main class="ui-page">Demo</main>' | python -S web_ui.py --trusted-html --css palette.css > demo.html
printf 'Result' | python -S web_ui.py --asset-base ./vendor/web-ui --theme github-like > demo.html
printf 'Result' | python -S web_ui.py --asset-base . --with-scripts ui.js > demo.html
```

The first examples escape input as text. `--trusted-html` and `--css` accept
caller-authored source, not untrusted content; this wrapper is not a sanitizer.
Embedded CSS produces a self-contained document when the supplied HTML/CSS have
no external references. Shared stylesheet links need the existing `css/` directory
copied alongside the output or an explicit HTTPS asset base pinned by the
consumer to a full commit SHA. A mutable URL is not a recommended baseline.
`--stub` additionally links `css/stub.css` and requires `--asset-base`.
`--with-scripts` requires a **local** `--asset-base` and emits module `src`
links only. `shared_scripts()` and direct `render_document(scripts=...)` both
reject remote URLs (including HTTPS), query/fragment and ambiguous path syntax.
Consumers must vendor and verify exact-version modules and manage their serving
and imports; the wrapper checks path syntax, not file identity. Authored
`trusted_html` is outside this link policy. See [the JS contract](docs/lightweight-js.md).

```python
from web_ui import render_document, run_node, shared_scripts, shared_stylesheets
print(render_document("Hello", title="Demo", stylesheets=shared_stylesheets("./vendor/web-ui")))
print(render_document("Hello", scripts=shared_scripts("./vendor/web-ui")))
assert run_node("tests/repository_diagnostics.node.js").returncode == 0
# Caller-supplied CSS can also be passed directly: render_document("Hello", css="body {color:#000}")
```

Existing `ui.js` text/clipboard helpers, `stub.js` form binding, and
`repository-diagnostics.js` rendering remain in use by examples or consumers.
They remain optional browser utilities under the lightweight JS bar in
[docs/lightweight-js.md](docs/lightweight-js.md). Python cannot replace
browser-side interaction merely by generating HTML. Live DOM checks of published
pages stay on an agent `/js` lane documented there. The wrapper preserves the v1
classes and theme attributes without changing those existing assets.

See [Pages ownership and execution](docs/pages-ownership.md) for the separation
between static discovery and execution evidence.

### Single-file embedded ES modules (experimental)

The Python wrapper can carry a snapshot of `js/ui.js` inside `web_ui.py`.
No npm, pip dependencies or runtime download is needed. JavaScript remains opt-in.

```sh
printf 'Hello' | python -S web_ui.py --embed-ui > demo.html
python -S -c 'from web_ui import render_document; print(render_document("Hello", embedded_modules=("ui.js",)))' > demo.html
```

The output HTML contains the ES module body. The module exports `setText`,
`prettyJson` and `copyText`; embedding it alone does not invoke them.
The same Python file exposes `module_asset("ui.js")`, returning bytes and
`text/javascript; charset=utf-8` for caller-owned HTTP routing. The Python
wrapper does **not** run a web server. To avoid inline code, use
`module_mode="data"` for a base64 data URL, with a CSP that explicitly permits
`data:` scripts. Data URLs do not support relative module imports.

Inline modules need an appropriate CSP nonce or hash (or a relaxed policy).
`module_nonce="..."` supplies a caller-generated nonce;
`module_csp_hash(EMBEDDED_UI_JS)` gives the CSP hash expression.
Do not generate a static, predictable nonce as a security measure.
These modes are not a JS sanitizer: source must be trusted and audited.
Module bodies containing HTML `</script>` terminators are rejected.

**Deployment comparison:** existing local module `src` references require a
separate served JS file; embedded inline/data mode creates one HTML artifact;
`module_asset` allows a single Python source to serve a separate JS response.
CDN dependencies stay a deliberate consumer choice. Local module `scripts=` and
`shared_scripts()` still reject remote URLs. Opt in to documented HTTPS classic
scripts with `remote_scripts()` and `render_document(remote_scripts=...)`. See
[docs/lightweight-js.md](docs/lightweight-js.md).

Plotly charts from a figure JSON spec (no Python `plotly` package):

```sh
python -S -c 'from web_ui import plotly_figure, render_document, remote_scripts; spec={"data":[{"type":"bar","y":[1,2,3]}]}; print(render_document(trusted_html=plotly_figure(spec), remote_scripts=remote_scripts("plotly.js")))' > chart.html
```

`plotly_figure()` emits the graph div and a trusted inline `Plotly.newPlot`
initializer; `remote_scripts("plotly.js")` links the unpinned plotly.js CDN URL
from the explicit allowlist.

Browser `.pptx` download from a JSON slide spec (no `python-pptx`, no Office
XML in Python). `pptxgenjs` is the pinned PptxGenJS 4.0.1 bundle with SRI.
Each slide is one `items` list; array order is z-order. Center-mode connectors
move to the start of that list so they paint behind later objects. Connectors
are a straight line plus an unfilled triangle arrowhead, not the built-in
arrow connector. Generated text, shapes, lines, arrowheads, and tables default
to black `000000` text and borders, no fill, and `fontFace` `Meiryo` (メイリオ).
Spec values for those properties override the defaults. Layouts beyond that
stay in the caller spec.

```sh
python -S -c 'from web_ui import pptx_presentation, render_document, remote_scripts; spec={"slides":[{"items":[{"kind":"text","text":"Hello","x":0.5,"y":0.5,"w":4,"h":0.6}]}]}; print(render_document(trusted_html=pptx_presentation(spec), remote_scripts=remote_scripts("pptxgenjs")))' > deck.html
```

See [docs/lightweight-js.md](docs/lightweight-js.md) for the slide spec,
`pptx_connector()`, and the edge/center arrow convention.

Run `python -m unittest tests.test_embedded_modules -v` or pytest. Browser
verification should check the resulting module in Chromium under the chosen CSP;
unit tests alone do not establish browser execution.

### Common controls in one line

`button`, `select`, `input_field`, `textarea`, `checkbox`, `badge`, `card`, `key_value_list`, `alert`, `sortable_table`, `details`, and
`section_browser` now emit labeled native controls and components from Python. A local,
explicitly loaded `controls.js` binds section selection to text output; native
controls and disclosure work without JS. See [one-liners and the Markdown
boundary](docs/python-controls.md).
