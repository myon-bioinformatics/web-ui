"""Typography is shared: --ui-font (Meiryo first) for text, --ui-font-mono for code, the same stack for Plotly."""
import json
import re
import unittest
from pathlib import Path

import web_ui
from web_ui import plotly_figure

CSS = Path(__file__).resolve().parents[1] / "css"


def read(*parts):
    return CSS.joinpath(*parts).read_text(encoding="utf-8")


def token(name):
    return re.search(rf"--{name}:([^;}}]+)", read("tokens.css")).group(1)


def figure_layout(fragment):
    return json.loads(re.search(r"var s=(\{.*?\});var el=", fragment, re.S).group(1))["layout"]


class FontTests(unittest.TestCase):
    def test_token_matches_the_python_constant_and_puts_meiryo_first(self):
        self.assertEqual(token("ui-font").replace(" ", ""), web_ui.UI_FONT.replace(" ", ""))
        self.assertTrue(web_ui.UI_FONT.startswith("Meiryo"))
        self.assertEqual(web_ui._PPTX_DEFAULT_FONT, web_ui.UI_FONT.split(",")[0])

    def test_base_follows_the_tokens_and_no_stylesheet_hardcodes_a_face(self):
        base = read("base.css")
        self.assertIn("font:16px/1.6 var(--ui-font)", base)
        # !important: it must also win over an adapted page's own `pre, code { font-family: inherit }`
        self.assertIn("pre,code,kbd,samp{font-family:var(--ui-font-mono)!important}", base)
        for path in CSS.rglob("*.css"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("system-ui", text, path.name)
            if path.parent.name == "themes":
                self.assertNotIn("font-family", text, f"{path.name}: themes follow the tokens")

    def test_plotly_figure_defaults_the_family_and_keeps_the_figures_own_font(self):
        spec = {"data": [], "layout": {"title": {"text": "t"}}}
        self.assertEqual(figure_layout(plotly_figure(spec))["font"], {"family": web_ui.UI_FONT})
        self.assertNotIn("font", spec["layout"])  # the caller's spec is not changed

        own = {"data": [], "layout": {"font": {"size": 11, "color": "#123"}}}
        self.assertEqual(figure_layout(plotly_figure(own))["font"], {"family": web_ui.UI_FONT, "size": 11, "color": "#123"})

        own_family = {"data": [], "layout": {"font": {"family": "Arial"}}}
        self.assertEqual(figure_layout(plotly_figure(own_family))["font"], {"family": "Arial"})

        with self.assertRaisesRegex(ValueError, "font must be a mapping"):
            plotly_figure({"data": [], "layout": {"font": "Arial"}})


if __name__ == "__main__":
    unittest.main()
