"""Required Chromium contract: python tests/integration/source_browser.py -v.

The generic source panel (web_ui.source_panel_html + source.js) with the Pokémon spec, offline (file://) and over HTTP: pasted JSON is read with no
request, Fetch asks the spec's one address once (answered here by the browser's own network layer, never the live site), and every failure is a visible
message. Invoked explicitly by the browser CI job; missing Playwright/browser is an error.
"""
import functools
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from web_ui import bundled_css, render_document, source_panel_html, write_js

FIX = ROOT / 'tests' / 'fixtures' / 'source'
SPEC = json.loads((FIX / 'pokeapi.spec.json').read_text(encoding='utf-8'))
DITTO = (FIX / 'ditto.json').read_text(encoding='utf-8')
DITTO_MD = (FIX / 'ditto.md').read_text(encoding='utf-8')
API = 'https://pokeapi.co/api/v2/pokemon/'


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def page_files(directory):
    # A classic script, not type=module: browsers block module scripts from file:// (origin null).
    body = '<main class="ui-page">' + source_panel_html(SPEC) + '</main><script src="./js/source.js"></script>'
    root = Path(directory)
    (root / 'index.html').write_text(render_document(trusted_html=body, css=bundled_css()), encoding='utf-8')
    write_js(root)
    return root / 'index.html'


def launch(playwright):
    chrome = os.environ.get('WEBUI_CHROME')  # a local Chrome when Playwright's own build is not installed
    return playwright.chromium.launch(**({'executable_path': chrome} if chrome else {}))


class SourcePanelBrowserTests(unittest.TestCase):
    def walk(self, page, url):
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def answer(route):
            requests.append((route.request.url, route.request.headers.get('accept')))
            name = route.request.url.rsplit('/', 1)[-1]
            if name == 'ditto':
                route.fulfill(status=200, content_type='application/json', headers={'access-control-allow-origin': '*'}, body=DITTO)
            elif name == 'nope':
                route.fulfill(status=404, headers={'access-control-allow-origin': '*'}, body='Not Found')
            elif name == 'html':
                route.fulfill(status=200, content_type='text/html', headers={'access-control-allow-origin': '*'}, body='<html>')
            else:
                route.abort('failed')

        page.context.route(API + '**', answer)  # the context, so the new tab Open JSON makes is answered too
        page.goto(url)
        panel = page.locator('[data-ui-source]')
        name, text = panel.locator('[data-source-name]'), panel.locator('[data-source-text]')
        output, error, status = panel.locator('[data-source-output]'), panel.locator('[data-source-error]'), panel.locator('[data-source-status]')
        expect(output).to_be_hidden()
        expect(error).to_be_hidden()

        # Paste: no request at all.
        panel.locator('[data-source-extract]').click()
        expect(error).to_have_text('Paste the JSON first.')
        text.fill(DITTO)
        panel.locator('[data-source-extract]').click()
        expect(output).to_have_text(DITTO_MD.rstrip('\n'))
        expect(error).to_be_hidden()
        expect(status).to_contain_text('ditto (#132) — from pasted JSON')
        text.fill('{nope')
        panel.locator('[data-source-extract]').click()
        expect(error).to_have_text('source is not JSON')
        expect(output).to_be_hidden()
        self.assertEqual(requests, [])

        # Fetch: one request, JSON accepted, the same Markdown.
        name.fill('  Ditto ')
        panel.locator('[data-source-fetch]').click()
        expect(output).to_have_text(DITTO_MD.rstrip('\n'))
        expect(status).to_contain_text('fetched')
        self.assertEqual(requests, [(API + 'ditto', 'application/json')])

        # Every failure is a message, and a bad name sends nothing.
        for typed, message in (('nope', 'not found: nope'), ('html', 'source is not JSON'), ('boom', 'could not fetch')):
            name.fill(typed)
            panel.locator('[data-source-fetch]').click()
            expect(error).to_contain_text(message)
            expect(output).to_be_hidden()
        sent = len(requests)
        name.fill('no way!')
        panel.locator('[data-source-fetch]').click()
        expect(error).to_have_text(SPEC['missing'])
        self.assertEqual(len(requests), sent)

        # Open JSON: the spec's address in a new tab, without opener or referrer.
        name.fill('ditto')
        with page.expect_popup() as popup:
            panel.locator('[data-source-open]').click()
        popup.value.wait_for_load_state()
        self.assertEqual(popup.value.url, API + 'ditto')
        self.assertIsNone(popup.value.evaluate('window.opener'))
        popup.value.close()
        self.assertEqual(errors, [])

    def test_offline_and_http(self):
        with tempfile.TemporaryDirectory() as directory:
            index = page_files(directory)
            handler = functools.partial(QuietHandler, directory=directory)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = launch(playwright)
                    try:
                        for url in (index.as_uri(), f'http://127.0.0.1:{server.server_port}/index.html'):
                            context = browser.new_context()
                            try:
                                self.walk(context.new_page(), url)
                            finally:
                                context.close()
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
