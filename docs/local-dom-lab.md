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
(hidden copy target) and Deno (terminal LF) fragments plus Japanese/code whitespace.
Test browser requests outside the local Gradio origin are aborted. Evidence JSON
is retained even on comparison failure and the browser/server are closed.

```sh
WEB_UI_GRADIO_TEST=1 BTK_ROOT=/path/to/pinned/browser-test-kit python -m pytest tests/integration/test_gradio_dom.py
```

The CI lane supplies browser-test-kit commit
`2d4da483c30907bd7a392b009b73366421ee0c8d`. The parser is not copied
into web-ui. Gradio and Playwright are optional test dependencies, not requirements
of `web_ui.py`. GHI's Markdown fixture exporter can supply the input HTML; there
is no new Markdown converter or CORS workaround here. The earlier Markdown
round-trip code-block extra-LF finding remains distinct from text extraction.
