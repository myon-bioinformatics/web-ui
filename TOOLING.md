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

The pytest check intentionally validates the v4 Python surface without starting
an agent session or requiring API keys. Live Stagehand tests should be opt-in.

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
the exact commit and tool environment.

## Policy

- deterministic browser smoke: Playwright/Chromium
- agent-oriented browser experiments: Stagehand v4
- GitHub automation/diagnostics: `git` + `gh`
- tests may use pytest
- application/runtime UI remains build-free and dependency-light
- version/SHA metadata should aid diagnosis, not cause needless failures merely
  because a newer tool release exists
