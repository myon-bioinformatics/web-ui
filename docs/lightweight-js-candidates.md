# Lightweight JS candidates and documentation tips

Decision recorded 2026-10-09 for the Python wrapper work in PR #43.

## What we are adding

Add this maintained reference catalogue and reusable documentation DOM evidence
to web-ui. Keep first-party ES modules as the default. Third-party entries below
are declared evaluation candidates, not adopted runtime dependencies. No CDN
script, package, import map or vendor lock is added by this documentation change.

| Status | Choice | When to consult it | Official documentation |
| --- | --- | --- | --- |
| Existing default | Native DOM plus js/ui.js | Text updates, JSON display and clipboard; prefer existing setText, prettyJson and copyText | [MDN DOM](https://developer.mozilla.org/en-US/docs/Web/API/Document_Object_Model), local js/ui.js |
| First evaluation candidate | Alpine.js | Declarative state and small interactions on existing HTML | [Installation](https://www.alpinejs.dev/essentials/installation), [CSP](https://www.alpinejs.dev/advanced/csp) |
| Conditional candidate | petite-vue | Vue-like reactive enhancement of a bounded existing region | [Official README](https://github.com/vuejs/petite-vue) |
| Conditional alternative | Preact + HTM | Reusable interactive components when native helpers or attribute bindings no longer suffice | [No-build guide](https://preactjs.com/guide/v10/no-build-workflows/), [HTM](https://github.com/developit/htm) |

These are alternatives for an explicit need, not a stack to load together.
No size claim is used as an acceptance result: measure the selected distribution,
its complete import graph and transfer bytes when preparing an actual adoption.

## Compatibility with web-ui

The existing wrapper emits opt-in local module links, not remote script URLs or
inline initialization. Alpine's documented classic defer CDN snippet is therefore
not a drop-in shared_scripts entry. Any experiment needs a pinned local compatible
distribution and project-owned initialization module, with initialization once.

petite-vue exposes an ESM path and explicit mount target. Its README also describes
restricted maintenance scope and expression evaluation via new Function; assess
that against the consumer's CSP before selecting it. Do not automatically mount
over fetched or user-supplied HTML.

HTM is template syntax, not a standalone DOM renderer; the Preact pairing includes
a renderer dependency. The no-build guide discusses import maps and avoiding
duplicate Preact instances. A local managed module graph must satisfy that
requirement without silently introducing remote transitive imports. The observed
v10 guide labels itself older than the current major; keep that version identity
when using its examples.

For an actual adoption: record the use case and chosen release, distribution,
license, complete import graph, commit/hash lock, then test the local module via
the existing browser-test-kit lane. This entry is advance declaration of candidate
scope, not a claim that those gates have passed. See [lightweight-js.md](lightweight-js.md).

## Actual documentation DOM observations

Observed through a live browser on 2026-10-09, not inferred from search text.
These facts describe these pages at capture time; they are not universal selectors.

| Page | Observed structure | Reader implication |
| --- | --- | --- |
| Alpine installation | main; h1; pre > code.torchlight; individual div.line and highlighted spans; hidden copy-target div | textContent includes a duplicate source copy; visible code and structural text differ |
| Preact v10 no-build | main; h2#htm with fragment-link, SVG and span; four pre blocks with code.language-html and token spans | Exclude decorative SVG; preserve literal newlines and version notice; do not include side navigation as content |
| petite-vue README | article.markdown-body.entry-content.container-lg; 15 pre blocks; markdown-heading wrapper containing h2 and separate permalink anchor | Scope to README article; heading and anchor are siblings; copy controls are separate UI |

The Alpine evidence is stored in
[alpine-code-dom.json](evidence/alpine-code-dom.json): one actual outerHTML fragment
and its browser innerText. It includes only one short installation command. Treat
it as inert text; the version shown in the page is not an adopted dependency pin.

A local replay through browser-test-kit page_text, sampled at its existing main
54d30b102284020a4e6b9ae94a97a69ab473ffef, produced the command twice and did not
match the browser-visible text. This is a recorded extraction gap, not a passing
browser-equivalence test. The hidden copy carries hidden, aria-hidden=true and
display:none; the rendered lines can also depend on block layout rather than
literal newlines. Removing style strings alone does not reconstruct visible code.

Keep raw HTML, textContent, innerText and any normalized result distinct. Do not
deduplicate repeated strings globally: real code can intentionally repeat lines.
Resolve the general hidden-node/line-boundary contract in the shared page-text
reader with saved evidence. This catalogue introduces no duplicate parser.

Capture ownership stays with
[browser-test-kit PR #54](https://github.com/myon-bioinformatics/browser-test-kit/pull/54).
Consumers can reuse the pinned evidence offline. GHI need not acquire a browser
or take ownership of generic documentation probes.

## Media candidates (2026-10-09)

- **Tone.js: optional audio-specific candidate.** Use only for an actual audio UI;
  this does not add it to the default bundle or `shared_scripts()` allowlist.
  Vendor an exact version locally and record its license and transitive dependencies.
  Start audio from a deliberate user gesture via `Tone.start()`; do not autoplay
  in generic DOM tests. Documentation: https://tonejs.github.io/docs/14.9.17/functions/start.html
  (observed version, not a latest-version claim).
- **Remotion: separate rendering tool candidate.** CLI rendering is supported
  (`npx remotion render <entry> <composition> <output>`), but React, Node tooling,
  bundling and browser rendering are additional prerequisites. Under our definition
  of lightweight (few dependencies and little setup/cache/build), it belongs in
  an optional media project/job, not the shared page runtime. No runtime dependency
  is adopted by this PR. Documentation: https://www.remotion.dev/docs/cli/render
  and https://www.remotion.dev/docs.

Saved documentation DOM observations are maintained in browser-test-kit
`docs/media-doc-dom-survey.md`; acquisition/extraction implementations stay there.
