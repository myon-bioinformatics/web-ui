"""Generic pinned-asset verification (SHA-256 hex or SRI) shared by Plotly.js and allowlisted scripts."""
import base64
import hashlib
import io
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import web_ui as ui

RAW = b'console.log("pinned");\n'


class Response(io.BytesIO):
    status = 200


class PinnedAssetTests(unittest.TestCase):
    def test_sri_and_hex_pins_accept_exact_bytes(self):
        for algorithm in ('sha256', 'sha384', 'sha512'):
            pin = ui.sri(RAW, algorithm)
            self.assertTrue(pin.startswith(algorithm + '-'))
            self.assertIs(ui.verify_pinned_asset(RAW, pin), RAW)
        self.assertEqual(ui.sri(RAW), 'sha384-' + base64.b64encode(hashlib.sha384(RAW).digest()).decode())
        self.assertIs(ui.verify_pinned_asset(RAW, hashlib.sha256(RAW).hexdigest()), RAW)

    def test_mismatch_empty_size_and_type_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, r'^lib SHA-384 mismatch: '):
            ui.verify_pinned_asset(RAW + b' ', ui.sri(RAW), label='lib')
        with self.assertRaisesRegex(RuntimeError, r'SHA-256 mismatch: [0-9a-f]{64}$'):
            ui.verify_pinned_asset(RAW + b' ', hashlib.sha256(RAW).hexdigest())
        with self.assertRaisesRegex(RuntimeError, 'empty body'):
            ui.verify_pinned_asset(b'', ui.sri(RAW))
        with self.assertRaisesRegex(RuntimeError, '4 byte limit'):
            ui.verify_pinned_asset(RAW, ui.sri(RAW), max_bytes=4)
        with self.assertRaises(TypeError):
            ui.verify_pinned_asset(RAW.decode(), ui.sri(RAW))
        for pin in ('md5-abc', 'sha384-', 'sha256-' + base64.b64encode(b'short').decode(), 'A' * 64, None):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                ui.verify_pinned_asset(RAW, pin)
        for limit in (0, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                ui.verify_pinned_asset(RAW, ui.sri(RAW), max_bytes=limit)
        with self.assertRaises(TypeError):
            ui.sri('text')
        with self.assertRaises(ValueError):
            ui.sri(RAW, 'md5')

    def test_fetch_pinned_asset(self):
        pin = ui.sri(RAW)
        with patch('urllib.request.urlopen', return_value=Response(RAW)) as opener:
            self.assertEqual(ui.fetch_pinned_asset('https://cdn.example/lib.js', pin, timeout=5), RAW)
        self.assertEqual(opener.call_args.args[0].full_url, 'https://cdn.example/lib.js')
        self.assertEqual(opener.call_args.kwargs['timeout'], 5)
        with patch('urllib.request.urlopen', return_value=Response(b'other')):
            with self.assertRaisesRegex(RuntimeError, r'^https://cdn.example/lib.js SHA-384 mismatch'):
                ui.fetch_pinned_asset('https://cdn.example/lib.js', pin)
        for url, kwargs in (('http://cdn.example/lib.js', {}), ('https://cdn.example/lib.js', {'timeout': 0})):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ui.fetch_pinned_asset(url, pin, **kwargs)
        with self.assertRaises(ValueError):
            ui.fetch_pinned_asset('https://cdn.example/lib.js', 'nope')

    def test_remote_script_pins(self):
        url = ui.REMOTE_SCRIPT_NAMES['pptxgenjs']
        with patch.dict(ui.REMOTE_SCRIPT_INTEGRITY, {url: ui.sri(RAW)}):
            self.assertIs(ui.verify_remote_script('pptxgenjs', RAW), RAW)
            with self.assertRaisesRegex(RuntimeError, '^pptxgenjs SHA-384 mismatch'):
                ui.verify_remote_script('pptxgenjs', RAW + b'x')
        with self.assertRaises(ValueError):
            ui.verify_remote_script('left-pad', RAW)
        # Every allowlisted remote script has a parseable pin.
        for name, address in ui.REMOTE_SCRIPT_NAMES.items():
            with self.subTest(name=name):
                ui._parse_integrity(ui.REMOTE_SCRIPT_INTEGRITY[address])

    @unittest.skipUnless(os.environ.get('WEB_UI_PPTXGENJS_TEST_FILE'),
                         'npm pack pptxgenjs@4.0.1 bytes (package/dist/pptxgen.bundle.js) supplied explicitly')
    def test_actual_pptxgenjs_bundle_matches_pin(self):
        raw = Path(os.environ['WEB_UI_PPTXGENJS_TEST_FILE']).read_bytes()
        self.assertIs(ui.verify_remote_script('pptxgenjs', raw), raw)

    def test_cli_prints_sri_and_hex(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'lib.js'
        path.write_bytes(RAW)
        out = io.StringIO()
        with patch('sys.stdout', out):
            self.assertEqual(ui.main(['--sri', str(path)]), 0)
        self.assertEqual(out.getvalue(), f'{ui.sri(RAW)}\nsha256 {hashlib.sha256(RAW).hexdigest()}\n')
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
            ui.main(['--sri', str(path) + '.missing'])


if __name__ == '__main__':
    unittest.main()
