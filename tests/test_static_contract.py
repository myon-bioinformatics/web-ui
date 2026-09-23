from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class ContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.classes = []
        self.ids = set()
        self.labels_for = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if values.get("class"):
            self.classes.extend(values["class"].split())
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "label" and values.get("for"):
            self.labels_for.add(values["for"])


class StaticContractTest(unittest.TestCase):
    def parsed(self, path):
        parser = ContractParser()
        parser.feed(path.read_text(encoding="utf-8"))
        return parser

    def test_examples_reference_shared_assets(self):
        for path in EXAMPLES.glob("*.html"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("../css/tokens.css", text)
            self.assertIn("../css/base.css", text)
            self.assertIn("../css/components.css", text)
            self.assertIn("../css/themes/", text)

    def test_theme_examples_keep_semantic_markup(self):
        text = (EXAMPLES / "github-like.html").read_text(encoding="utf-8")
        self.assertIn('data-ui-theme="github-like"', text)
        self.assertIn("../css/themes/github-like.css", text)
        for class_name in ("ui-page", "ui-panel", "ui-card", "ui-button", "ui-input", "ui-tag", "ui-output"):
            self.assertIn(class_name, text)

    def test_examples_do_not_embed_css(self):
        for path in EXAMPLES.glob("*.html"):
            self.assertNotIn("<style", path.read_text(encoding="utf-8").lower())

    def test_local_links_exist(self):
        for path in EXAMPLES.glob("*.html"):
            for href in self.parsed(path).hrefs:
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc or href.startswith("#"):
                    continue
                target = (path.parent / parsed.path).resolve()
                self.assertTrue(target.exists(), f"{path.name}: broken href {href}")

    def test_ui_classes_follow_namespaces(self):
        for path in EXAMPLES.glob("*.html"):
            for name in self.parsed(path).classes:
                self.assertTrue(name.startswith(("ui-", "stub-")), f"{path.name}: unnamespaced class {name}")

    def test_labels_target_existing_controls(self):
        for path in EXAMPLES.glob("*stub.html"):
            parsed = self.parsed(path)
            self.assertTrue(parsed.labels_for)
            self.assertTrue(parsed.labels_for <= parsed.ids)

    def test_domain_protocols_not_in_generic_js(self):
        text = (ROOT / "js" / "stub.js").read_text(encoding="utf-8").lower()
        for term in ("tools/list", "tools/call", "json-rpc", "authorization:"):
            self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
