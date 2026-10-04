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

`tooling_meta.py` delegates Python runtime, Git/GitHub CLI/Node/npx versions,
and the explicitly allowlisted `pytest`/`stagehand` distributions to Ironmate's
`collect_portable_tooling()`. The consumer only timestamps and projects those
observations into the existing `runtime`, `commands`, and `packages` JSON groups.
It does not collect repository identity or add app/render/build measurements.

Available values are canonical normalized short version strings (for example,
Git `2.45.1`, rather than `git version 2.45.1`). Missing, failed, malformed or
unmeasured observations are **omitted**, never replaced with `null` or `unknown`.
Empty groups remain `{}`; consumers must handle absent keys. Duplicate canonical
owners are errors even when a tool is unavailable. No consumer values are merged
over canonical keys. Command probes use the producer's 5 second timeout;
`WEB_UI_TOOL_TIMEOUT` is no longer used.

Repository identity is generated exclusively by Ironmate's stdlib producer,
pinned with its contract at `73157cb7fed236a4a941722a6dcddd69a33ab95a`.
`tool/vendor/provenance.json` records source paths, Git blob IDs and SHA-256
hashes; both Python files are unchanged upstream bytes, with the upstream MIT
license included. To refresh, retrieve both files from one reviewed upstream
commit and update all provenance fields together; verify byte hashes before use.

CI's existing `tooling-meta` artifact contains three separate files:
`tooling-meta.json` (advisory observations), `repository-metadata.json`, and
`repository-metadata.jsonl` (the same canonical record). Measurements remain
`null` unless measured. `js/repository-diagnostics.js` only reads/renders the
canonical record; it never recollects Git identity. This is the first consumer
slice of Ironmate #49; Flutter and other consumers remain separate follow-ups.
The repository-metadata v1 schema and JSON/JSONL identity path are unchanged.

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
