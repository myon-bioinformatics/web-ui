# Local Gradio DOM regression

The optional lab wraps an audited HTML fragment using `web_ui.render_document`
and displays it in a sandboxed srcdoc iframe inside Gradio. The iframe isolates
fixture CSS. No scripts are enabled inside it. This is deterministic local
reproduction, not proof that an inaccessible upstream site rendered identically.
Do not pass unreviewed HTML containing external assets; sandboxing is not an HTML
sanitizer or a network firewall.

```sh
python -m pip install -r tests/requirements-gradio.txt
python -m playwright install chromium
python tool/serve_dom_lab.py fixture.html --css fixture.css
```

The test actually launches Gradio on loopback, opens Chromium, and compares
`innerText`, saved DOM and browser-test-kit `page_text`. It checks saved Alpine
(hidden copy target), Deno, FFmpeg and Pillow (terminal LF) fragments plus
Japanese/code whitespace. Tone.js and Remotion use saved real pre DOM but select
only its code element, excluding filename/copy controls. The static comparison
explicitly wraps the selected code in a modeled pre to retain the observed
parent context; evidence marks this wrapper rather than claiming it was captured.
The media fixtures are read from the pinned browser-test-kit checkout, not copied.
Test browser requests outside the local Gradio origin are aborted. Evidence JSON
is retained even on comparison failure and the browser/server are closed.

```sh
WEB_UI_GRADIO_TEST=1 BTK_ROOT=/path/to/pinned/browser-test-kit python -m pytest tests/integration/test_gradio_dom.py
```

The CI lane supplies browser-test-kit commit
`b94f801a9c57b1914ff6b732519521a7a42fadfe`. The parser is not copied
into web-ui. Gradio and Playwright are optional test dependencies, not requirements
of `web_ui.py`. GHI's Markdown fixture exporter can supply the input HTML; there
is no new Markdown converter or CORS workaround here. The earlier Markdown
round-trip code-block extra-LF finding remains distinct from text extraction.

The separate six-case GHI HTML/Markdown probe now passes against markdown PR #95
commit `6f69bd59693c81d8796613cc4966b17f6c070d7c`, including this web-ui wrapper
and GHI #24's updated structural extractor. This does not update any consumer
vendor lock or claim arbitrary HTML is reversible. Code with no terminal LF and
code inside details retain documented representation limitations in that PR.
