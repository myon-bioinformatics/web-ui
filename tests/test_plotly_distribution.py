"""Plotly CDN contract: bounded fetch helper; no network in unit tests."""
import io
import http.client
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

import web_ui as ui


class Response(io.BytesIO):
    status = 200


PLOTLY_JSDELIVR = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min/plotly.min.js"


class PlotlyDistributionTests(unittest.TestCase):
    def test_contract_and_external_tag_agree(self):
        self.assertEqual(ui.PLOTLY_JS_URL, PLOTLY_JSDELIVR)
        self.assertNotRegex(ui.PLOTLY_JS_URL, r"@[0-9]")
        self.assertNotIn("plotly-latest", ui.PLOTLY_JS_URL)
        with patch('urllib.request.urlopen', side_effect=AssertionError('render must not fetch')):
            tag = ui.remote_script_tag(ui.remote_scripts('plotly.js')[0])
        self.assertIn(f'src="{PLOTLY_JSDELIVR}"', tag)
        self.assertNotIn('integrity=', tag)
        self.assertNotIn('crossorigin=', tag)
        with self.assertRaises(ValueError):
            ui.remote_script_tag('https://cdn.plot.ly/plotly-latest.min.js')

    def test_fetch_returns_raw_bytes_and_bounds_read(self):
        raw = b'/* unit fixture */ window.Plotly={version:"test"};'
        with patch('urllib.request.urlopen', return_value=Response(raw)) as opener:
            self.assertEqual(ui.fetch_plotly_js(), raw)
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, ui.PLOTLY_JS_URL)
            self.assertEqual(opener.call_args.kwargs['timeout'], 60.0)

        class LargeResponse(Response):
            def read(self, size=-1):
                self_test.assertEqual(size, ui.PLOTLY_JS_MAX_BYTES + 1)
                return b'x' * size
        self_test = self
        with patch('urllib.request.urlopen', return_value=LargeResponse()):
            with self.assertRaisesRegex(RuntimeError, 'byte limit'):
                ui.fetch_plotly_js()

    def test_empty_bytes_are_rejected(self):
        with patch('urllib.request.urlopen', return_value=Response(b'')):
            with self.assertRaisesRegex(RuntimeError, 'empty body'):
                ui.fetch_plotly_js()
        with self.assertRaisesRegex(RuntimeError, 'empty body'):
            ui.verify_plotly_js(b'')

    def test_acquisition_failures_are_errors(self):
        for error in (urllib.error.HTTPError(ui.PLOTLY_JS_URL, 503, 'Unavailable', None, None),
                      urllib.error.URLError('offline'), TimeoutError('timed out'), OSError('broken read'),
                      http.client.IncompleteRead(b'partial')):
            with self.subTest(error=error), patch('urllib.request.urlopen', side_effect=error):
                with self.assertRaisesRegex(RuntimeError, 'request failed'):
                    ui.fetch_plotly_js()
        response = Response(b'window.Plotly={};')
        response.status = 206
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 206'):
                ui.fetch_plotly_js()

    @unittest.skipUnless(os.environ.get('WEB_UI_PLOTLY_JS_TEST_FILE'), 'real CDN bytes supplied by browser CI')
    def test_actual_jsdelivr_bundle_is_bounded(self):
        raw = Path(os.environ['WEB_UI_PLOTLY_JS_TEST_FILE']).read_bytes()
        self.assertEqual(ui.verify_plotly_js(raw), raw)
        self.assertIn(b'Plotly', raw[:4096])
        with patch('urllib.request.urlopen', return_value=Response(raw)):
            self.assertEqual(ui.fetch_plotly_js(), raw)


if __name__ == '__main__':
    unittest.main()
