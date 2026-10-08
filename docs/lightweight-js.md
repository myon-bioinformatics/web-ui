# Lightweight JavaScript and verification lanes

## Acceptance bar for lightweight JS

Pages UIs may use CSS, GIF, and lightweight JavaScript. Heavy frameworks and npm
runtime dependencies are out of scope for shared web-ui assets.

Acceptable lightweight JS meets all of:

1. Few dependencies, so version upgrades stay easy
2. Referable like a CDN or Deno import (URL or single vendored file), without a
   consumer build step
3. Capable enough that a single file can drive multi-feature UI, similar in
   spirit to Vue’s single-file / CDN usage model

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
`<script type="module" src="...">` links for local or HTTPS sources. The wrapper
never injects inline script bodies and never downloads packages.

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
