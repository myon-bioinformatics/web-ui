# Deno: optional tooling and documentation evidence

Decision clarified 2026-10-09: Python remains the default for acquisition,
saved-data processing and CLI orchestration. Deno is an optional candidate when
running/reusing a JS/TS module or preparing managed web-ui assets has a concrete
benefit. A Python subprocess wrapper is acceptable if that need arises; do not
duplicate an existing Python reader simply to introduce Deno.

## Meaning of lightweight

Prioritize a very small dependency graph, little prerequisite tooling, and low
persistent cache/build-environment burden. A few KB versus MB of source or network
transfer is not the acceptance criterion. A build-free consumer path is useful;
measure setup and recurring maintenance before declaring a candidate lightweight.
Deno still has a runtime and dependency cache; URL imports do not remove them.

Normal saved-HTML processing should not launch a browser. Browser-test-kit owns
local browser tests and bounded live capture when a selected site's rendered DOM
is actually needed. Deno is not a browser and does not supply layout/innerText on
its own. The Deno runtime was not installed or executed for this investigation.

## Where to look

| Question | Official entry point |
| --- | --- |
| URL imports, lock, cache, vendoring, dependency graph | [Dependency management](https://docs.deno.com/runtime/packages/) |
| Run a JS/TS CLI | [Run code](https://docs.deno.com/runtime/run/) |
| fetch and other Web-compatible APIs | [Web platform APIs](https://docs.deno.com/runtime/reference/web_platform_apis/) |
| Module semantics and DOM limitations | [Modules](https://docs.deno.com/runtime/fundamentals/modules/) |

The first page received both raw HTTP and live-DOM inspection in this change.
The other links are reference candidates previously located in the official docs,
not additional DOM captures. For dependency investigation start with deno info
and deno why; for updates consult the update/lock sections and retain the project's
existing canonical vendor ownership. This does not introduce a competing updater.

## Actual acquisition and local replay

On 2026-10-09, curl fetched the dependency-management HTML once (142497 bytes).
The whole response hash, two exact source fragments and corresponding live DOM
are recorded in [deno-doc-dom.json](evidence/deno-doc-dom.json). Only the bounded
fragments are committed, not the whole third-party document.

Browser observations: UTF-8; one main#content article region; 22 pre elements.
The selected first pre and h2#https-imports were byte-for-byte identical as
strings between the HTTP source fragments and the browser's outerHTML.
This establishes equality for those two fragments, not the complete page or all
Deno documentation.

The selected code block contains highlighted spans and a final LF. textContent
and innerText both retain that LF. The existing browser-test-kit page_text reader
(sampled main 54d30b102284020a4e6b9ae94a97a69ab473ffef) returns the command without
the final LF. Thus fragment-source equality passes while exact code-text equality
fails. Record this boundary behavior; do not claim round-trip content preservation.

The heading contains an sr-only accessibility label and an aria-hidden anchor.
The recorded innerText includes both. Neither textContent nor innerText alone is
a pixel-visible-text oracle. Preserve each representation independently; selecting
one must follow the caller's extraction contract.

This evidence complements the Alpine hidden copy-target case in
[lightweight-js-candidates.md](lightweight-js-candidates.md). Future reader
regressions should consume saved fragments through browser-test-kit, with no
site-specific parser copied into web-ui or GHI.

## Adoption boundary

Deno stays a candidate. Existing web-ui pages retain the opt-in local ES module
contract. If Deno later prepares those assets, the result must still be a managed,
pinned browser-compatible module graph; Deno-specific APIs cannot be assumed to
run in a browser. Declare the concrete reuse benefit, dependencies and cache/build
requirements in that implementation change. No runtime dependency or lock changes
are made here.
