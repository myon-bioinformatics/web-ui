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

## Roadmap

- expand the component gallery
- migrate Ironmate MCP Stub onto the shared contract
- add API/MCP Stub patterns without moving domain logic into web-ui
- expand themes beyond Modern and GitHub-like
- keep HTML contract v1 stable while `markdown.py` and `ascii_artist` integrations adopt it

See #1 for the bootstrap plan.


## Development tooling

Browser/UI verification keeps two separate lanes: deterministic Playwright/Chromium smoke tests and optional Stagehand v4 agent-oriented experiments. Git/gh and Python tool versions plus the exact repository SHA can be captured as advisory CI metadata. See [TOOLING.md](./TOOLING.md).
