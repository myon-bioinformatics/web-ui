"""Required Chromium contract: python tests/integration/route_table_browser.py -v.

The same generated route table navigates offline (file://) and over HTTP. Invoked
explicitly by the browser CI job; missing Playwright/browser is an error.
"""
import functools
import http.server
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from web_ui import render_document, route_links

HOME, MAP, SHADES = '\U0001F3E0', '\U0001F5FA\ufe0f', '\U0001F576'
TABLE = [{'route': '/', 'key': HOME, 'label': 'Home'}, {'route': '/map', 'key': MAP, 'label': 'Map'},
         {'route': '/shades', 'key': SHADES}]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def page_files(directory):
    # A classic script, not type=module: browsers block module scripts from file:// (origin null).
    body = (route_links(TABLE) + f'<button type="button" data-ui-go="{SHADES}">go shades</button>'
            + '<script src="./js/navigation.js"></script>')
    document = render_document(trusted_html=body)
    root = Path(directory)
    (root / 'index.html').write_text(document, encoding='utf-8')
    (root / 'js').mkdir()
    shutil.copyfile(ROOT / 'js/navigation.js', root / 'js/navigation.js')
    return root / 'index.html'


class RouteTableBrowserTests(unittest.TestCase):
    def walk(self, page, url):
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        nav = page.get_by_role('navigation', name='Pages')
        expect(nav.get_by_role('link', name=HOME + ' Home')).to_have_attribute('aria-current', 'page')
        nav.get_by_role('link', name=MAP + ' Map').click()
        expect(page).to_have_url(url.split('#')[0] + '#/map')
        expect(nav.get_by_role('link', name=MAP + ' Map')).to_have_attribute('aria-current', 'page')
        page.get_by_role('button', name='go shades').click()
        expect(page).to_have_url(url.split('#')[0] + '#/shades')
        # Both spellings of the map emoji resolve to one route.
        self.assertEqual(page.evaluate("k => webUiNavigation.bindRouteTable(window, {}).go(k)", '\U0001F5FA'), '/map')
        expect(page).to_have_url(url.split('#')[0] + '#/map')
        page.go_back()
        expect(page).to_have_url(url.split('#')[0] + '#/shades')
        expect(nav.get_by_role('link', name=MAP + ' Map')).not_to_have_attribute('aria-current', 'page')
        self.assertEqual(errors, [])

    def test_offline_file_and_http_navigate_the_same_table(self):
        with tempfile.TemporaryDirectory() as directory:
            index = page_files(directory)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                                                     functools.partial(QuietHandler, directory=directory))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        for url in (index.as_uri(), f'http://127.0.0.1:{server.server_port}/index.html'):
                            with self.subTest(url=url.split(':')[0]):
                                context = browser.new_context()
                                requests = []
                                context.on('request', lambda request: requests.append(request.url))
                                self.walk(context.new_page(), url)
                                self.assertTrue(all(r.startswith(url.rsplit('/', 1)[0]) for r in requests), requests)
                                context.close()
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
