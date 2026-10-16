"""Plotly figure spec helpers and opt-in remote script allowlist (stdlib only)."""
import subprocess
import sys
import unittest
from pathlib import Path

from web_ui import (
    classic_script,
    plotly_figure,
    remote_scripts,
    render_document,
)

ROOT = Path(__file__).resolve().parents[1]


class PlotlyFigureTests(unittest.TestCase):
    def test_remote_scripts_allowlist_is_explicit(self):
        self.assertEqual(
            remote_scripts("plotly.js"),
            ("https://cdn.plot.ly/plotly-4.1.1.min.js",),
        )
        with self.assertRaises(ValueError):
            remote_scripts()
        with self.assertRaises(ValueError):
            remote_scripts("missing.js")
        with self.assertRaises(ValueError):
            render_document(remote_scripts=("https://evil.test/plotly.js",))

    def test_plotly_figure_emits_div_and_initializer(self):
        spec = {
            "data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}],
            "layout": {"title": {"text": "Demo"}},
            "config": {"responsive": True},
        }
        fragment = plotly_figure(spec, div_id="chart", height=320, width=640)
        self.assertIn('<div id="chart" class="ui-panel"></div>', fragment)
        self.assertIn("Plotly.newPlot", fragment)
        compact = fragment.replace(" ", "")
        self.assertIn('"responsive":true', compact)
        self.assertIn('"height":320', compact)
        self.assertIn('"width":640', compact)

    def test_plotly_figure_rejects_invalid_spec(self):
        with self.assertRaises(ValueError):
            plotly_figure([])
        with self.assertRaises(ValueError):
            plotly_figure({"data": "nope"})
        with self.assertRaises(ValueError):
            plotly_figure({"data": []}, height=0)

    def test_render_document_places_remote_script_in_head(self):
        spec = {"data": [{"type": "bar", "y": [1]}]}
        html = render_document(
            trusted_html=plotly_figure(spec),
            remote_scripts=remote_scripts("plotly.js"),
        )
        head, body = html.split("</head>", 1)
        self.assertIn('src="https://cdn.plot.ly/plotly-4.1.1.min.js"', head)
        self.assertNotIn("plotly-latest", body.split("<body", 1)[1].split("</body>", 1)[0])
        self.assertIn('id="plot"', body)

    def test_classic_script_rejects_script_end_tag(self):
        with self.assertRaises(ValueError):
            classic_script("</script>")

    def test_cli_with_remote_scripts(self):
        run = subprocess.run(
            [
                sys.executable,
                "-S",
                str(ROOT / "web_ui.py"),
                "--trusted-html",
                "--with-remote-scripts",
                "plotly.js",
            ],
            input=plotly_figure({"data": []}),
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("plotly-4.1.1.min.js", run.stdout)

    def test_one_liner_without_python_plotly_package(self):
        code = (
            "import json; from web_ui import plotly_figure, render_document, remote_scripts; "
            "spec={'data':[{'type':'scatter','x':[1],'y':[2]}]}; "
            "print(render_document(trusted_html=plotly_figure(spec), "
            "remote_scripts=remote_scripts('plotly.js')), end='')"
        )
        run = subprocess.run([sys.executable, "-S", "-c", code], text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(run.returncode, 0, run.stderr)
        head, rest = run.stdout.split("</head>", 1)
        self.assertIn("plotly-4.1.1.min.js", head)
        self.assertIn("Plotly.newPlot", rest)


if __name__ == "__main__":
    unittest.main()
