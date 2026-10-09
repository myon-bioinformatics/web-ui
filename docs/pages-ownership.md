# Static discovery and execution evidence

## Current scope

Ironmate metadata-only discovery transfers to the portfolio in
[portfolio PR #31](https://github.com/myon-bioinformatics/myon-bioinformatics.github.io/pull/31).
[Ironmate PR #81](https://github.com/myon-bioinformatics/Ironmate/pull/81)
retires its legacy stub and Pages deployment source. These are proposed changes,
not claims of a completed deployment. Consolidation is limited to Ironmate;
Flutter navigation and working MCP toolcall lab search interfaces retain their
own responsibilities. The parent repository also has its own Pages publication.

The portfolio owns project metadata and navigation (for example `#ironmate`).
web-ui owns presentation primitives and the portable Python wrapper. Consumers
own protocol operations, transformations, authorization, and evidence semantics.
Vendored helpers are usable at build/test time; publishing Python under a Pages
URL does not cause the browser or Pages to execute it.

Python/pytest may wrap layout generation and existing `node` checks as
one-liners. Optional lightweight JS links follow the acceptance bar in
[lightweight-js.md](./lightweight-js.md). Live DOM snapshots of published pages
belong to an agent `/js` verification lane, not to Pages execution.

## Future visitor-triggered experiment

A useful future experiment could select a bounded test case with a recorded seed
and retain its JUnit result, including an intentionally failing offline fixture.
GitHub Pages serves static files: it does not run Python/Docker for each visit or
persist newly produced seeds/results. A page can show a previously published
result or offer a link to an authenticated Actions workflow. Python can generate
that page during a build; Actions can run the test or a container separately.

Before implementing visitor-triggered execution, choose an authenticated
workflow dispatch or an explicitly operated backend. Never publish a write token
in browser code. Record the chosen seed, exact source SHA, case identifier, run
identifier, and JUnit artifact together so the experiment is reproducible. Treat
expected fixture failure separately from infrastructure failure. Execution must
be explicit, bounded, and observable; a visit alone must not silently start an
unbounded job. Artifact retention and any published summary need a stated policy.
No visitor-triggered workflow, storage service, Docker runtime, or new deployment
is introduced by this change.

References: [GitHub Pages static hosting](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
and [manually running Actions workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
