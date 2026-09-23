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
