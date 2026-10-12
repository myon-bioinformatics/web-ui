"""Embedded ES module regression checks (stdlib unittest / pytest compatible)."""
import base64
import hashlib
import re
import unittest
from pathlib import Path

from web_ui import EMBEDDED_UI_JS, module_asset, module_script, module_csp_hash, render_document


class EmbeddedModulesTests(unittest.TestCase):
    def test_snapshot_matches_original(self):
        self.assertEqual(EMBEDDED_UI_JS, (Path(__file__).resolve().parents[1] / "js/ui.js").read_text(encoding="utf-8"))

    def test_opt_in_and_one_file(self):
        self.assertNotIn('<script', render_document("hello"))
        html = render_document("hello", embedded_modules=("ui.js",))
        self.assertIn('<script type="module">', html)
        self.assertIn("export function setText", html)
        self.assertEqual(html.count('<script type="module">'), 1)

    def test_asset_response(self):
        body, mime = module_asset()
        self.assertEqual(body, EMBEDDED_UI_JS.encode("utf-8"))
        self.assertEqual(mime, "text/javascript; charset=utf-8")

    def test_data_mode(self):
        html = render_document(embedded_modules=("ui.js",), module_mode="data")
        encoded = re.search(r'data:text/javascript;base64,([^"]+)', html).group(1)
        self.assertEqual(base64.b64decode(encoded).decode(), EMBEDDED_UI_JS)

    def test_reject_end_tag_and_duplicates(self):
        for source in ("</script>", "</ScRiPt >", "</script/"):
            with self.assertRaises(ValueError):
                module_script(source)
        with self.assertRaises(ValueError):
            render_document(embedded_modules=("ui.js", "ui.js"))
        with self.assertRaises(ValueError):
            render_document(embedded_modules=("unknown",))

    def test_csp(self):
        html = render_document(embedded_modules=("ui.js",), module_nonce="abc123")
        self.assertIn('nonce="abc123"', html)
        self.assertEqual(module_csp_hash(EMBEDDED_UI_JS), "'sha256-" + base64.b64encode(hashlib.sha256(EMBEDDED_UI_JS.encode()).digest()).decode() + "'")
        with self.assertRaises(ValueError):
            module_script("ok", nonce='" onclick="bad')
        with self.assertRaises(ValueError):
            render_document(embedded_modules=("ui.js",), module_mode="data", module_nonce="abc")


if __name__ == "__main__":
    unittest.main()
