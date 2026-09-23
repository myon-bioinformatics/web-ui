# Visual regression baselines

This directory is the reviewed PNG baseline lane for deterministic Chromium
captures.

Current policy:

- pull requests always generate candidate screenshots;
- if a reviewed baseline exists, exact PNG equality is checked;
- if no baseline exists, CI reports `missing-baseline` but does not fail;
- a future enforcement switch may pass `--require-baseline` once reviewed
  baselines are committed for all stable fixtures;
- baseline changes must be intentional and reviewed together with the UI change.

The first stable target is `contract/v1/example.html`. Gallery/example pages
may also receive baselines, but the frozen contract fixture has priority.


## Candidate selection

The default checker pattern is `web-ui-*.png`, meaning every deterministic
screenshot produced by the current CI lane is visible in the candidate report.

Enforcement may be rolled out more narrowly with `--pattern`, for example:

```sh
python scripts/check_visual_regression.py \
  --candidate-dir . \
  --pattern "web-ui-contract-*.png" \
  --require-baseline
```

This lets the frozen contract fixture become blocking before gallery/demo
screenshots do.

The directory is intentionally tracked by this README; no `.gitkeep` is
required.
