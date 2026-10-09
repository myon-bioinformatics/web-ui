"""Opt-in real Gradio/Chromium test, using the shared BTK text extractor."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(os.environ.get('WEB_UI_GRADIO_TEST') != '1', reason='optional Gradio integration lane')
def test_gradio_dom(tmp_path, monkeypatch):
    monkeypatch.setenv('GRADIO_ANALYTICS_ENABLED', 'False')
    from playwright.sync_api import sync_playwright, expect
    btk = Path(os.environ['BTK_ROOT']).resolve()
    extractor = load('shared_page_text', btk / 'scripts/page_text.py')
    lab = load('gradio_lab', ROOT / 'tool/serve_dom_lab.py')
    alpine = json.loads((ROOT / 'docs/evidence/alpine-code-dom.json').read_text())
    deno = json.loads((ROOT / 'docs/evidence/deno-doc-dom.json').read_text())['samples'][0]
    samples = [(alpine['html'], alpine['visible_text']), (deno['dom_html'], deno['inner_text']),
               ('<pre><code>日本語 &amp; text\n\n  x  \n</code></pre>', '日本語 & text\n\n  x  \n')]
    fragment = ''.join(f'<section id="sample-{i}">{html}</section>' for i, (html, _) in enumerate(samples))
    demo = lab.build_demo(fragment, css='pre { white-space: pre; }')
    evidence = []
    try:
        _, url, _ = demo.launch(server_name='127.0.0.1', share=False, inbrowser=False, prevent_thread_lock=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                # A fixture cannot fetch CDN assets or escape to a remote site.
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(url) else route.abort())
                page.goto(url, wait_until='domcontentloaded')
                frame = page.frame_locator('#dom-lab')
                for i, (html, expected) in enumerate(samples):
                    pre = frame.locator(f'#sample-{i} pre')
                    expect(pre).to_be_visible()
                    visible = pre.inner_text()
                    dom = pre.evaluate('(el) => el.outerHTML')
                    extracted = extractor.page_text(dom)['text']
                    evidence.append(dict(html=dom, visible=visible, extracted=extracted))
                    assert visible == expected
                    assert extracted == expected
            finally:
                browser.close()
    finally:
        output = Path(os.environ.get('DOM_EVIDENCE_DIR', str(tmp_path)))
        output.mkdir(parents=True, exist_ok=True)
        (output / 'gradio-dom.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        demo.close()
