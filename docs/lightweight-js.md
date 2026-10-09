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
rejected even if they look versioned; there is no remote-script/SRI API.
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
The wrapper itself never generates inline script bodies or downloads packages.

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
