# Observed anti-patterns

This catalogue records failures and rollout lessons already observed in web-ui.
It is intentionally small. Reuse a cross-repository stable ID when the failure
mode is equivalent; do not mint a local synonym only to make this list larger.

## Stable IDs reused from sibling repositories

| ID | Observed web-ui incident | Guard / preferred pattern |
| --- | --- | --- |
| `VISUAL_DIFF_TOO_EARLY` | PR #7 introduced exact PNG comparison in candidate mode because reviewed deterministic baselines were not yet complete. Making missing baselines blocking at that point would have made rollout noise look like regression signal. | Keep deterministic capture and candidate validation first. Promote a baseline to blocking only after it is reviewed and stable. The vocabulary owner is [browser-test-kit](https://github.com/myon-bioinformatics/browser-test-kit/blob/d1907443583c8edd00377f1656f46f619d2addbd/docs/antipatterns.md). |

## Observed contract-boundary lesson

PR #12 established the repository diagnostics renderer as a consumer of
Ironmate repository metadata v1. Review found that partially re-implementing
producer validation in JavaScript can drift from the producer contract, for
example around missing measurement keys and head-field validation.

The preferred boundary is:

- the canonical producer owns collection, normalization, and authoritative
  validation;
- web-ui reads generated JSON and owns presentation safety such as escaping,
  formatting, and clear rejection of data it cannot render;
- tests use a producer-generated/shared fixture so schema drift is visible.

This lesson intentionally has no new stable ID yet. Promote it only if the same
failure recurs or an existing cross-repository ID is adopted as its vocabulary
owner.

## Maintenance rule

Every stable entry must point to an observed incident and a guard or regression
test. Keep speculative design advice out of this catalogue.
