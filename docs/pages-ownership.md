# GitHub Pages static hosting and ownership architecture

This document defines the static hosting boundary, repository ownership responsibilities, evidence publishing policy, and execution boundaries for GitHub Pages deployments across `web-ui` and consuming repositories.

## Static hosting vs. execution boundary

GitHub Pages serves static web assets (HTML, CSS, images, and client-side JavaScript). It does not provide a server-side execution runtime or database backend.
- **No server-side code execution:** Publishing Python scripts, Dockerfiles, or Node backend scripts under a Pages URL serves them as static text/files; browser visits to Pages will never execute server-side Python or Docker containers.
- **Static generation at build time:** Dynamic content or layout generation (e.g. using `web_ui.py` or pytest layout helpers) must occur at CI/build time before static deployment.
- **No implicit persistence:** Pages cannot persist newly generated state or seeds upon visitor interaction. Any persistent state or test results must be published as build artifacts or recorded prior to deployment.

## Repository ownership boundaries

To prevent duplicate discovery interfaces and maintain clear boundaries, responsibilities are partitioned as follows:

| Repository / Layer | Primary Responsibility |
| --- | --- |
| **Portfolio (`myon-bioinformatics.github.io`)** | Top-level project metadata, portfolio-wide navigation (e.g., `#ironmate`), and centralized discovery. |
| **`web-ui`** | Reusable presentation primitives (`ui-*` / `stub-*`), CSS themes, lightweight browser utilities, and stdlib Python static wrapper (`web_ui.py`). |
| **Domain Consumers** (Ironmate, MCP toolcall lab, Flutter navigation, etc.) | Domain protocol operations, transformations, authorization, protocol semantics, and backend test execution. |

*Note on consolidation:* Ironmate metadata-only discovery transfers to the portfolio ([portfolio PR #31](https://github.com/myon-bioinformatics/myon-bioinformatics.github.io/pull/31)), and Ironmate retires its legacy stub and Pages deployment source ([Ironmate PR #81](https://github.com/myon-bioinformatics/Ironmate/pull/81)). Flutter navigation and MCP toolcall lab search interfaces retain their specific responsibilities.

## Evidence and diagnostics publishing policy

Execution evidence (JUnit XML reports, raw diagnostic JSONL, visual regression screenshots, and trace logs) must remain cleanly separated from public Pages deployments:
- **CI Artifact retention:** Raw diagnostics, test outputs, and JUnit XML are captured and stored as GitHub Actions workflow artifacts (typically retained for 14 days). See [junit-evidence.md](./junit-evidence.md).
- **Public Pages summaries:** Pages publications should present high-level static summaries or links to specific Actions workflow runs, rather than hosting raw, unparsed test diagnostics or internal logs.

## Client-side JavaScript and verification lanes

- **Lightweight JS rules:** Any JavaScript loaded by pages hosted on GitHub Pages must follow the lightweight JS policy (see [lightweight-js.md](./lightweight-js.md)). Secret write tokens must never be embedded in client-side code.
- **Verification vs. Pages runtime:** Automated or manual verification of published Pages surfaces (e.g. DOM snapshots via Playwright or CUA `/js` lane) is a CI/verification task, not a runtime dependency of GitHub Pages.

## Visitor-triggered execution and workflow dispatch

If a published page offers interactive or visitor-initiated execution (e.g. running an offline fixture or triggering a test case with a recorded seed):
1. **Explicit dispatch:** Use an authenticated GitHub Actions `workflow_dispatch` trigger or a dedicated backend service.
2. **Token security:** Never embed write tokens or workflow permissions in browser code.
3. **Traceability:** Record the chosen seed, exact commit SHA, case identifier, run ID, and JUnit artifact together for full reproducibility.
4. **Bounded execution:** Execution must be explicit, bounded, and observable; a page visit alone must never silently launch an unbounded background job.

## References

- [GitHub Pages static hosting documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [Manually running GitHub Actions workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
- [Lightweight JavaScript and verification lanes](./lightweight-js.md)
- [Python JUnit evidence](./junit-evidence.md)
