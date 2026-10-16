"""Pinned CDN bytes: fail closed before embedding; no network in unit tests."""
import base64
import hashlib
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


class PlotlyDistributionTests(unittest.TestCase):
    def test_contract_and_external_tag_agree(self):
        self.assertEqual(ui.PLOTLY_JS_VERSION, '4.1.1')
        self.assertEqual(ui.PLOTLY_JS_URL, 'https://cdn.plot.ly/plotly-4.1.1.min.js')
        self.assertEqual(ui.PLOTLY_JS_SHA256,
                         '3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f')
        self.assertEqual(ui.PLOTLY_JS_SRI, 'sha256-' + base64.b64encode(
            bytes.fromhex(ui.PLOTLY_JS_SHA256)).decode('ascii'))
        with patch('urllib.request.urlopen', side_effect=AssertionError('render must not fetch')):
            tag = ui.remote_script_tag(ui.remote_scripts('plotly.js')[0])
        self.assertIn(f'integrity="{ui.PLOTLY_JS_SRI}"', tag)
        self.assertIn('crossorigin="anonymous"', tag)
        with self.assertRaises(ValueError):
            ui.remote_script_tag('https://cdn.plot.ly/plotly-latest.min.js')

    def test_fetch_hashes_raw_bytes_and_bounds_read(self):
        raw = b'/* unit fixture */ window.Plotly={version:"4.1.1"};'
        with patch.object(ui, 'PLOTLY_JS_SHA256', hashlib.sha256(raw).hexdigest()), \
                patch('urllib.request.urlopen', return_value=Response(raw)) as opener:
            self.assertEqual(ui.fetch_plotly_js(), raw)
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, ui.PLOTLY_JS_URL)
            self.assertEqual(opener.call_args.kwargs['timeout'], 60.0)
        # A payload bigger than the limit is rejected using a bounded read.
        class LargeResponse(Response):
            def read(self, size=-1):
                self_test.assertEqual(size, ui.PLOTLY_JS_MAX_BYTES + 1)
                return b'x' * size
        self_test = self
        with patch('urllib.request.urlopen', return_value=LargeResponse()):
            with self.assertRaisesRegex(RuntimeError, 'byte limit'):
                ui.fetch_plotly_js()

    def test_changed_wrong_version_and_empty_bytes_are_rejected(self):
        for raw in (b'/* plotly.js v4.1.1 */ window.pwned=true;',
                    b'/* plotly.js v1.58.5 */', b' ', b'\xff'):
            with self.subTest(raw=raw), patch('urllib.request.urlopen', return_value=Response(raw)):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
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
        response = Response(b'wrong')
        response.status = 206
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 206'):
                ui.fetch_plotly_js()

    @unittest.skipUnless(os.environ.get('WEB_UI_PLOTLY_JS_TEST_FILE'), 'real CDN bytes supplied by browser CI')
    def test_actual_fixed_bundle_matches_contract(self):
        raw = Path(os.environ['WEB_UI_PLOTLY_JS_TEST_FILE']).read_bytes()
        self.assertEqual(ui.verify_plotly_js(raw), raw)
        self.assertIn(b'plotly.js v4.1.1', raw[:160])
        with patch('urllib.request.urlopen', return_value=Response(raw)):
            self.assertEqual(ui.fetch_plotly_js(), raw)
        with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
            ui.verify_plotly_js(raw + b'window.pwned=true;')


if __name__ == '__main__':
    unittest.main()
