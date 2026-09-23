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

Modern is the first theme, not the only theme. Components use semantic `ui-*` / `stub-*` classes so future themes can reuse the same HTML contract.

Generic JavaScript handles browser behavior and rendering helpers. MCP/API protocol semantics remain in consuming repositories.

The generic Stub layer now covers request submission, text-safe result rendering,
copy, clear-history, status text, and optional local request history. Consumers
still supply the handler that defines protocol/API behavior.

## HTML contract v1

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

## Generic Stub UI

`js/stub.js` is deliberately protocol-neutral. `bindStub()` accepts a
consumer handler and can wire:

- form submission / run-button state
- text-safe string or JSON output
- status text
- copy-result action
- local request history and rerun
- history clearing

The API and MCP example pages use the same shared controls and differ only in
their consumer-provided handler. Generic JS must not embed MCP methods, HTTP
authorization semantics, or product-specific validation.

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

The screenshot artifact also includes desktop/mobile captures of both
`examples/api-stub.html` and `examples/mcp-stub.html`, so the generic Stub
contract has visual evidence independent of any consuming repository.

## Roadmap

- expand the component gallery
- migrate Ironmate MCP Stub onto the shared contract
- keep API/MCP Stub behavior generic while consumers own domain logic
- add more themes alongside Modern
- stabilize an HTML contract that `markdown.py` and `ascii_artist` can target

See #1 for the bootstrap plan.


## Development tooling

Browser/UI verification keeps two separate lanes: deterministic Playwright/Chromium smoke tests and optional Stagehand v4 agent-oriented experiments. Git/gh and Python tool versions plus the exact repository SHA can be captured as advisory CI metadata. See [TOOLING.md](./TOOLING.md).
