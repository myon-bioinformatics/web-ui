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

## Local preview

```sh
python -m http.server 8000
```

Open `http://localhost:8000/examples/index.html`.

## UI verification

`python -m unittest discover -s tests -v` checks the static contract. GitHub Actions additionally opens the example with Playwright and captures desktop and mobile screenshots as the `web-ui-screenshots` artifact.

The first phase intentionally treats screenshots as observable test evidence rather than a pixel-perfect blocking regression test.

## Roadmap

- expand the component gallery
- migrate Ironmate MCP Stub onto the shared contract
- add API/MCP Stub patterns without moving domain logic into web-ui
- add more themes alongside Modern
- stabilize an HTML contract that `markdown.py` and `ascii_artist` can target

See #1 for the bootstrap plan.
