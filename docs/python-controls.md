# Python UI one-liners

`web_ui.py` remains one stdlib-only Python 3.10+ file. Copy it into the import
path or use the repository root. All labels, values and default bodies are
escaped. These helpers emit HTML, not a Python application server.

`run_node()` also works when only `web_ui.py` is copied. It requires an installed
Node 24+ executable; HTML generation does not require Node. A checkout uses
`vendor/node_launch.py`; a standalone copy uses an embedded snapshot of that
same stdlib launcher. Updating the vendor requires refreshing the snapshot;
the regression suite checks their equality. Both paths preserve text output,
nonzero exit results, and `subprocess.TimeoutExpired` with raw byte output.

| Helper | Native behavior / use |
| --- | --- |
| `button("実行")` | `type=button` by default; use `type="submit"` inside a form |
| `select((("a", "項目A"),), id="choice", label="選択")` | Native keyboard-accessible dropdown |
| `input_field(id="query", label="検索", type="search")` | Labeled input |
| `textarea(id="source", label="原文")` | Multiline text |
| `checkbox("有効", id="enabled")` | Native checked state |
| `badge("新着")` | Tag / badge element (`.ui-tag`) |
| `card("本文", title="見出し", heading_level=2)` | Card container element (`.ui-card`); `heading_level` 1-6 sets the title tag; `text` and `trusted_html` are mutually exclusive |
| `details("詳細", "本文")` | Expand/collapse without JS |
| `section_browser((("概要", "本文"),), full_text="全文")` | Heading selector and text output; pair with local `controls.js` |

```sh
python -S -c 'from web_ui import *; print(render_document(trusted_html=select((("a","項目A"),("b","項目B")),id="choice",label="選択")+button("実行")))' > controls.html
python -S -c 'from web_ui import *; print(render_document(trusted_html=section_browser((("概要","概要の本文"),("詳細","詳細の本文")),full_text="全文"),scripts=shared_scripts(".",names=("controls.js",))))' > sections.html
```

Serve `sections.html` alongside `js/controls.js` over local HTTP (for example
`python -m http.server`). Native controls/disclosures require no script;
section switching requires explicit local `controls.js`. With JS disabled,
full text stays visible and the section selector stays disabled. Supply
`stylesheets=shared_stylesheets(".")` to opt into the shared CSS.

`controls.js` also exposes `webUiControls.bindSelect(selectNode, outputNode)`.
Its `update(items, fullText, fullLabel)` accepts `{value, label, body}` objects;
`clear()` resets stale content and `destroy()` unbinds the listener. Values must
be unique and nonempty. Duplicate labels are allowed. It writes `textContent`
and makes no network calls. The caller owns parsing, caching, and custom button
actions; no inline event-handler strings are accepted by the Python helpers.

## Markdown / Pixiv boundary

Provider syntax belongs in the consumer adapter. `markdown.py` renders canonical
Markdown. `web-ui` receives HTML via explicit `trusted_html`, or text via the
safe default. It neither imports a second Markdown parser nor assumes that a
heading title uniquely identifies a section.

```python
from web_ui import details, render_document
from markdown import markdown_to_html  # myon-bioinformatics/markdown.py
print(render_document(trusted_html=details("関連タグ", trusted_html=markdown_to_html(body))))
```

Unlike wrapping an entire table in Markdown's current `:::details` parser,
rendering the body first preserves its normal table/list/heading rendering.
Only pass output from a trusted renderer to `trusted_html`; arbitrary pasted
HTML is not sanitized by web-ui. The section selector deliberately displays
Markdown as text, matching the portfolio Wiki extraction view.

## Browser regression

The required `Local Gradio DOM` CI job runs
`python tests/integration/controls_browser.py -v` after installing its pinned
Playwright/Chromium dependencies. This opens Python-generated HTML over loopback
HTTP and checks auto-mount, duplicate labels, change/full-text restoration, inert
hostile text, clear/destroy, zero external requests and the no-JS fallback.
Missing browser dependencies fail this explicitly invoked test instead of skipping.
