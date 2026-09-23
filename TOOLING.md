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
```

`tooling_meta.py` reports the current repository SHA/short SHA, UTC generation
time, Python/package versions, and availability/version strings for Git, GitHub
CLI, Node and npx. This is **advisory evidence**, not a strict freshness gate.

CI stores the same JSON as an artifact so a successful run can be traced back to
the exact commit and tool environment. Command probes default to a 10 second
timeout; unusually slow environments may override it with
`WEB_UI_TOOL_TIMEOUT`.

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
