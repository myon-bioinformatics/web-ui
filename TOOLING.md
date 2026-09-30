# Tooling reference

This repository keeps runtime UI assets build-free. Python packages below are
**development / verification tools only** and are not web-ui runtime dependencies.

## Browser automation

Stagehand v4 is available as a Python SDK (`pip install stagehand`) as well as
TypeScript and Go SDKs. web-ui treats it as an optional browser-agent lane next
to deterministic Playwright smoke tests, not as a replacement for Playwright.

Reference baseline when this integration was introduced:

- Stagehand major: **v4**
- observed PyPI release: **4.1.0**
- checked: **2026-09-23**
- Python: **3.11+ for the current PyPI v4 package**
- local browser execution requires Chrome/Chromium; remote Browserbase use
  requires credentials

The required Stagehand v4 surface contract is deliberately small:

- the Python package imports successfully
- it exposes `Stagehand` or `AsyncStagehand`

Browser launch, navigation, extraction, `act`/`observe`, and live agent behavior
are **not** required CI contracts yet. Those operations cross into browser/model
integration and should remain opt-in tests.

Live Stagehand tests must be opt-in. Local browser tests may use local
Chrome/Chromium. Remote Browserbase tests must receive credentials through
GitHub Actions secrets/environment at execution time; credentials must never be
committed, emitted by `tooling_meta.py`, or uploaded as artifacts.

## Tool diagnostics

Install development dependencies:

```sh
python -m pip install -r tests/requirements.txt
```

Run:

```sh
python -m pytest -v
python tool/tooling_meta.py
python -S tool/vendor/repository_metadata_generator.py --repository myon-bioinformatics/web-ui --root . --output-dir /tmp/web-ui-metadata
```

`tooling_meta.py` reports UTC observation time, Python/package versions, and
availability/version strings for Git, GitHub CLI, Node and npx. It does not
collect repository identity. Command probes default to a 10 second timeout;
slow environments may override it with `WEB_UI_TOOL_TIMEOUT`.

Repository identity is generated exclusively by Ironmate's stdlib producer,
pinned with its contract at `0aee64da2f8d0119a3ef9b955e5c3818f28aaf92`.
`tool/vendor/provenance.json` records source paths, Git blob IDs and SHA-256
hashes; both Python files are unchanged upstream bytes, with the upstream MIT
license included. To refresh, retrieve both files from one reviewed upstream
commit and update all provenance fields together; verify byte hashes before use.

CI's existing `tooling-meta` artifact contains three separate files:
`tooling-meta.json` (advisory observations), `repository-metadata.json`, and
`repository-metadata.jsonl` (the same canonical record). Measurements remain
`null` unless measured. `js/repository-diagnostics.js` only reads/renders the
canonical record; it never recollects Git identity. Portable tooling consolidation
is deferred to Ironmate #49; existing observation semantics remain unchanged.

### What can fail CI

- required API/surface contract break: **fail**
- required Git/GitHub tooling missing: **fail**
- invalid/missing repository SHA metadata: **fail**
- newer tool/package version exists: **pass**
- optional live Stagehand integration is not configured: **pass**

## Policy

- deterministic browser smoke: Playwright/Chromium
- agent-oriented browser experiments: Stagehand v4
- GitHub automation/diagnostics: `git` + `gh`
- tests may use pytest
- application/runtime UI remains build-free and dependency-light
- version/SHA metadata should aid diagnosis, not cause needless failures merely
  because a newer tool release exists


## Reuse in other repositories

This repository defines the web-ui verification pattern only. Other repositories may copy or adapt the deterministic smoke, advisory metadata, pytest, or Stagehand pieces independently. References to `flutter_navigation_basic`, Ironmate, `mcp-toolcall-lab`, or future projects are examples, not requirements or cross-repository contracts.
