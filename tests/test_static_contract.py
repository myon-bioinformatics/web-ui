from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class StaticContractTest(unittest.TestCase):
    def test_examples_reference_shared_assets(self):
        for name in ("index.html","mcp-stub.html","api-stub.html"):
            text=(ROOT/"examples"/name).read_text(encoding="utf-8")
            self.assertIn("../css/tokens.css",text)
            self.assertIn("../css/themes/modern.css",text)
    def test_examples_do_not_embed_css(self):
        for path in (ROOT/"examples").glob("*.html"):
            self.assertNotIn("<style",path.read_text(encoding="utf-8").lower())
    def test_domain_protocols_not_in_generic_js(self):
        text=(ROOT/"js"/"stub.js").read_text(encoding="utf-8").lower()
        for term in ("tools/list","tools/call","json-rpc","authorization:"):
            self.assertNotIn(term,text)
if __name__=="__main__": unittest.main()
