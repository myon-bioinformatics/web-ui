# Feature-specific dependency environments

PR #105 separates optional browser assistance from the default development environment. Runtime dependencies remain empty. Node consumers require Node >=26.

| Environment | Command | Purpose |
| --- | --- | --- |
| Default | `uv sync --locked` | pytest and PyYAML; Stagehand absent |
| Gradio | `uv sync --locked --group gradio` | Gradio and Playwright DOM/browser integration; Stagehand absent |
| Stagehand | `uv sync --locked --group stagehand` | Browser assistance SDK and its Python surface test |

Use separate `UV_PROJECT_ENVIRONMENT` directories when comparing lanes. Count installed distributions with `uv pip list`; measure apparent venv bytes with the same method and Python version for both revisions. Browser binaries and uv caches are separate from venv size.

## Recorded measurements

The PR author measured Linux x86_64, Python 3.14, fresh uv caches, one sync per condition. These are recorded observations, not a repeated performance benchmark.

| Lane | Packages before → after (including web-ui) | Apparent venv bytes before → after | Sync seconds before → after |
| --- | --- | --- | --- |
| Default | 24 → 7 | 23,020,089 → 9,468,459 (58.9% reduction) | 4.47 → 1.40 |
| Gradio | 65 → 60 | 390,345,641 → 386,265,151 (1.0% reduction) | 11.97 → 11.52 |
| Stagehand opt-in | 24 after | 23,020,019 after | 1.34 after |

## Final CI inspection

For head `5df20ab8b185860693ea4bf1006bcad17f85bfd8`, Tooling smoke run [41287053731](https://github.com/myon-bioinformatics/PySaiyanWeBoo/actions/runs/41287053731) tested the merge with main (`24b771ea619a7c7e4cd94d545a83e65b352f1bde`). Node was **26.13.0**. Both the locked baseline and tooling Node 26 jobs reported **239 passed, 3 skipped, 114 subtests passed**. `test_stagehand_v4_python_surface` explicitly **PASSED**. The Node test command reported **17 passed, 0 failed, 0 skipped**.

The three skips were the separately enabled Gradio DOM test and optional remote Plotly/PptxGenJS bundle probes; Stagehand was not skipped. The Gradio test ran in its dedicated lane with `WEB_UI_GRADIO_TEST=1` and passed in [Local Gradio DOM run 41287053801](https://github.com/myon-bioinformatics/PySaiyanWeBoo/actions/runs/41287053801). That job installed the official Playwright Chromium shell and passed Plotly rendering, controls, offline/HTTP route navigation and live layout preset checks.

[UI smoke run 41287053839](https://github.com/myon-bioinformatics/PySaiyanWeBoo/actions/runs/41287053839) used Node 26, captured six desktop/mobile Chromium screenshots, verified current-run identity and hashes, and passed visual regression checks. Stagehand coverage here is the SDK import/surface contract, not an authenticated external browser-agent service test.

## Accepting future Flutter functionality

Keep the default environment small when receiving functionality from Flutter. Put new framework/browser/service dependencies in a named opt-in dependency group for the feature. Reuse `gradio` for Gradio/Playwright integration and `stagehand` for browser assistance; enable both explicitly only when a feature needs both. Do not add these packages to `dev` merely to avoid local skips.

Every optional feature must have an enabled CI lane that installs its group and actually executes its required tests. A local `importorskip` is acceptable only when a corresponding enabled lane proves the test passes. Compare default and enabled environments, inspect skip reasons, preserve browser evidence, and record package/size measurements with conditions before expanding dependencies.
