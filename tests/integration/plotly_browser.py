"""Required Chromium SRI boundary, with real fixed CDN bytes and isolated routes."""
import os
from pathlib import Path
import sys
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import web_ui as ui


class PlotlyBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = os.environ.get('WEB_UI_PLOTLY_JS_TEST_FILE')
        cls.raw = ui.verify_plotly_js(Path(source).read_bytes()) if source else ui.fetch_plotly_js()
        cls.playwright = sync_playwright().start()
        executable = os.environ.get('CHROME')
        cls.browser = cls.playwright.chromium.launch(
            **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def page_for(self, raw, *, fail=False):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        spec = {'data': [{'type': 'scatter', 'x': [1, 2], 'y': [3, 4], 'mode': 'markers'}],
                'layout': {'title': {'text': 'Pinned Plotly'}, 'width': 400, 'height': 300}}
        document = ui.render_document(trusted_html=ui.plotly_figure(spec, height=None),
                                      remote_scripts=ui.remote_scripts('plotly.js'))
        def serve(route):
            if route.request.url == 'https://plotly-test.invalid/':
                route.fulfill(status=200, content_type='text/html', body=document)
            elif route.request.url == ui.PLOTLY_JS_URL:
                if fail:
                    route.abort('failed')
                else:
                    route.fulfill(status=200, content_type='application/javascript', body=raw,
                                  headers={'Access-Control-Allow-Origin': '*'})
            else:
                route.abort('blockedbyclient')
        page.route('**/*', serve)
        page.goto('https://plotly-test.invalid/', wait_until='load')
        return page

    def test_fixed_bundle_renders_json(self):
        page = self.page_for(self.raw)
        page.wait_for_selector('#plot .point')
        self.assertEqual(page.evaluate('Plotly.version'), ui.PLOTLY_JS_VERSION)
        self.assertEqual(page.locator('#plot .point').count(), 2)
        self.assertIn('Pinned Plotly', page.locator('#plot .gtitle').text_content())

    def test_modified_fixed_bundle_is_not_executed(self):
        page = self.page_for(self.raw + b';window.__tampered=true;')
        self.assertEqual(page.evaluate('typeof Plotly'), 'undefined')
        self.assertIsNone(page.evaluate('window.__tampered'))
        self.assertEqual(page.locator('#plot svg').count(), 0)

    def test_different_cdn_content_is_not_executed(self):
        page = self.page_for(b'window.__tampered=true;window.Plotly={version:"1.58.5"};')
        self.assertEqual(page.evaluate('typeof Plotly'), 'undefined')
        self.assertIsNone(page.evaluate('window.__tampered'))

    def test_cdn_failure_cannot_run_plotly(self):
        page = self.page_for(self.raw, fail=True)
        self.assertEqual(page.evaluate('typeof Plotly'), 'undefined')
        self.assertEqual(page.locator('#plot svg').count(), 0)


if __name__ == '__main__':
    unittest.main()
