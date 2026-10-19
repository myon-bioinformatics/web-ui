"""Required Chromium contract: python tests/integration/layout_presets_browser.py -v.

Choosing a layout preset re-lays the viewer at once (no reload, no JavaScript), and the
sweep clicks every preset at every width: several presets may pass, a broken one is caught.
Invoked explicitly by the browser CI job; missing Playwright/browser is an error.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tool"))
import capture_matrix  # noqa: E402
import layout_presets  # noqa: E402

PAGES = json.loads((ROOT / "examples/flutter-pages.json").read_text(encoding="utf-8"))
SPEC = json.loads((ROOT / "examples/layout-presets.json").read_text(encoding="utf-8"))
# A preset meant to break on phones: tiles wider than the screen.
BROKEN = {**SPEC, "presets": SPEC["presets"] + [{"id": "poster", "label": "Poster",
          "vars": {"--ui-matrix-col": "480px", "--ui-matrix-gap": "8px", "--ui-matrix-pad": "8px"}}]}
REPORT = {"schema": "ironmate-browser-matrix/1", "reference": "Linux-chromium-desktop",
          "pages": [p["adapter"] for p in PAGES["pages"]],
          "envs": ["Linux-chromium-desktop", "Windows-firefox-desktop", "macOS-webkit-iphone", "Linux-webkit-desktop"],
          "cells": []}


class LayoutPresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.page = Path(self.tmp.name) / "viewer.html"
        self.page.write_text(capture_matrix.viewer(PAGES, REPORT, embed_css=True, layouts=BROKEN), encoding="utf-8")

    def test_switching_relays_live_without_reload(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(self.page.as_uri() + "#/hub")
            page.evaluate("window.__marker = 'same document'")
            column = "() => getComputedStyle(document.querySelector('#\\\\/hub .ui-matrix-tiles')).gridTemplateColumns.split(' ').length"
            before = page.evaluate(column)
            page.get_by_label("Wide").check()
            wide = page.evaluate(column)
            page.get_by_label("Compact").check()
            compact = page.evaluate(column)
            self.assertEqual(page.evaluate("window.__marker"), "same document")  # no reload happened
            self.assertTrue(compact > before > wide, (compact, before, wide))
            browser.close()

    def test_sweep_keeps_every_passing_preset_and_catches_the_broken_one(self):
        result = layout_presets.sweep(self.page.as_uri(), BROKEN, [320, 384, 1280], items=".ui-matrix-tiles li")
        self.assertEqual(result["schema"], "web-ui-layout-candidates/1")
        self.assertTrue(result["every_width_has_a_candidate"])
        self.assertGreaterEqual(len(result["by_width"]["1280"]), 2)  # several presets may pass
        self.assertIn("poster", result["by_width"]["1280"])
        self.assertEqual(result["presets"]["poster"]["failed"], [320, 384])
        self.assertTrue(all(o["items"] > 0 for o in result["observations"]))
        labelled = capture_matrix.viewer(PAGES, REPORT, embed_css=True, layouts=BROKEN, candidates=result)
        self.assertIn("ok at 1280px; check at 320px, 384px", labelled)

    def assert_no_candidates(self, result):
        self.assertFalse(result["every_width_has_a_candidate"])
        self.assertEqual(result["by_width"], {"320": [], "1280": []})
        self.assertEqual(len(result["observations"]), 2 * len(SPEC["presets"]))
        for row in result["observations"]:
            self.assertFalse(row["ok"])
            self.assertEqual(row["items"], 0)
            self.assertIn("no_items", row["failed"])
        for row in result["presets"].values():
            self.assertEqual(row, {"passed": [], "failed": [320, 1280]})

    def test_sweep_rejects_selector_without_matches(self):
        result = layout_presets.sweep(self.page.as_uri(), SPEC, [320, 1280], items=".typo-no-tiles")
        self.assert_no_candidates(result)

    def test_sweep_rejects_unrendered_items(self):
        # Matching DOM nodes are insufficient when none have rendered boxes.
        self.page.write_text(self.page.read_text(encoding="utf-8").replace(
            "</head>", "<style>.ui-matrix-tiles{display:none}</style></head>"), encoding="utf-8")
        result = layout_presets.sweep(self.page.as_uri(), SPEC, [320, 1280], items=".ui-matrix-tiles li")
        self.assert_no_candidates(result)

    def test_cli_returns_failure_and_writes_evidence_when_items_are_missing(self):
        out = Path(self.tmp.name) / "candidates.json"
        status = layout_presets.main(["sweep", str(self.page), "--presets",
                                      str(ROOT / "examples/layout-presets.json"), "--widths", "320", "1280",
                                      "--items", ".typo-no-tiles", "--out", str(out)])
        self.assertEqual(status, 1)
        self.assert_no_candidates(json.loads(out.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
