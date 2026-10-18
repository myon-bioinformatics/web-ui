"""Flow diagram validation, HTML safety, CLI and output contracts."""
import json
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import unittest
from tool.flow_diagram import flow_document, flow_html, flow_mermaid, validate

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "examples/pr-flow.json").read_text(encoding="utf-8"))

class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

class FlowDiagramTests(unittest.TestCase):
    def test_html_structure_and_no_js(self):
        source = flow_document(SAMPLE)
        tags = Elements(source).tags
        self.assertEqual(sum(tag == "li" for tag, _ in tags), 5)
        self.assertEqual(sum(tag == "script" for tag, _ in tags), 0)
        self.assertIn('css/flow.css', source)
        self.assertIn('data-ui-theme="github-like"', source)

    def test_untrusted_text_is_escaped(self):
        hostile = '"><script>alert(1)</script>&'
        spec = {"title": hostile, "sources": [{"title": hostile}],
                "steps": [{"title": hostile, "note": hostile}]}
        source = flow_html(spec)
        self.assertNotIn("<script>", source)
        self.assertEqual(sum(tag == "li" for tag, _ in Elements(source).tags), 2)
        markdown = flow_mermaid(spec)
        self.assertEqual(markdown.count("S0 --> T0"), 1)
        self.assertIn("#quot;", markdown)
        self.assertIn("#lt;", markdown)

    def test_invalid_specs_fail(self):
        invalid = [None, {}, {"title": "x", "sources": [], "steps": [{"title": "ok"}]},
                   {"title": "x", "sources": [{"title": "z", "raw_html": "x"}], "steps": [{"title": "ok"}]},
                   {"title": "x", "sources": [{"title": "one" + chr(10) + "two"}], "steps": [{"title": "ok"}]},
                   {"title": "x", "sources": [{"title": "ok"}], "steps": [{"title": ""}]},
                   {"title": "x", "sources": [{"title": "ok"}] * 9, "steps": [{"title": "ok"}]}]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate(item)

    def test_cli_mermaid(self):
        run = subprocess.run([sys.executable, "-S", "-m", "tool.flow_diagram", "--format", "mermaid"],
                             input=json.dumps(SAMPLE), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(run.stdout.startswith("```mermaid\nflowchart TB\n"))
        self.assertIn("T0 --> T1", run.stdout)

    def test_embed_css(self):
        source = flow_document(SAMPLE, embed_css=True)
        self.assertIn("<style>", source)
        self.assertIn("ui-flow-sources", source)
        self.assertNotIn("<script", source)
        self.assertNotIn('<link rel="stylesheet"', source)

if __name__ == "__main__":
    unittest.main()
