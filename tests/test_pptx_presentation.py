"""PptxGenJS JSON slide specs and the line-plus-triangle arrow helper (stdlib only)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from web_ui import (
    pptx_arrow_geometry,
    pptx_connector,
    pptx_presentation,
    remote_scripts,
    render_document,
)

ROOT = Path(__file__).resolve().parents[1]
PLOTLY_JSDELIVR = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min/plotly.min.js"
PPTX_URL = "https://cdn.jsdelivr.net/npm/pptxgenjs@4.0.1/dist/pptxgen.bundle.js"
PPTX_SRI = "sha384-qb0Xhi7LLYpvW1HCK6oMrmDLSY9sy7vwm6ZlV6KjtrlL9yg30+YN4neTwnmX+Kp8"


def _resolved(fragment: str, button_id: str = "download-pptx") -> dict:
    marker = f'<script type="application/json" id="{button_id}-spec">'
    start = fragment.index(marker) + len(marker)
    end = fragment.index("</script>", start)
    return json.loads(fragment[start:end])


class PptxPresentationTests(unittest.TestCase):
    def test_remote_script_pin_includes_sri(self):
        self.assertEqual(remote_scripts("pptxgenjs"), (PPTX_URL,))
        html = render_document(remote_scripts=remote_scripts("pptxgenjs"))
        head, body = html.split("</head>", 1)
        self.assertIn(f'src="{PPTX_URL}"', head)
        self.assertIn(f'integrity="{PPTX_SRI}"', head)
        self.assertIn('crossorigin="anonymous"', head)
        self.assertNotIn("pptxgen", body)
        plotly = render_document(remote_scripts=remote_scripts("plotly.js"))
        self.assertIn(f'src="{PLOTLY_JSDELIVR}"', plotly)
        self.assertNotIn("integrity=", plotly.split("</head>", 1)[0])
        combined = render_document(remote_scripts=remote_scripts("plotly.js", "pptxgenjs"))
        head = combined.split("</head>", 1)[0]
        self.assertLess(head.index("plotly.js-dist-min"), head.index("pptxgen.bundle"))
        self.assertIn("integrity=", head)
        with self.assertRaises(ValueError):
            remote_scripts("pptxgenjs", "missing.js")

    def test_side_by_side_edges_and_midpoint_head(self):
        source = {"x": 0.5, "y": 1.0, "w": 2.0, "h": 1.0}
        target = {"x": 4.0, "y": 1.0, "w": 2.0, "h": 1.0}
        geometry = pptx_arrow_geometry(source, target)
        self.assertEqual(geometry["mode"], "edge")
        self.assertEqual((geometry["x1"], geometry["y1"]), (2.5, 1.5))
        self.assertEqual((geometry["x2"], geometry["y2"]), (4.0, 1.5))
        self.assertEqual(geometry["midpoint"], {"x": 3.25, "y": 1.5})
        self.assertAlmostEqual(geometry["distance"], 1.5)
        self.assertEqual(geometry["rotate"], 90)
        reversed_geometry = pptx_arrow_geometry(target, source)
        self.assertEqual((reversed_geometry["x1"], reversed_geometry["x2"]), (4.0, 2.5))
        self.assertEqual(reversed_geometry["rotate"], 270)
        self.assertEqual(geometry["line"]["op"], "line")
        self.assertEqual(geometry["line"]["options"]["line"]["color"], "000000")
        self.assertEqual(geometry["head"]["options"]["fill"], {"type": "none"})
        self.assertEqual(geometry["head"]["options"]["line"]["color"], "000000")
        self.assertFalse(geometry["line"]["options"]["flipH"])
        head = geometry["head"]
        self.assertEqual(head["shape"], "triangle")
        self.assertAlmostEqual(head["options"]["x"] + head["options"]["w"] / 2, 3.25)
        self.assertAlmostEqual(head["options"]["y"] + head["options"]["h"] / 2, 1.5)
        encoded = json.dumps(geometry)
        for banned in ("endArrowType", "beginArrowType", "lineHead", "lineTail"):
            self.assertNotIn(banned, encoded)

    def test_vertical_and_diagonal_edges(self):
        above = {"x": 1.0, "y": 0.5, "w": 2.0, "h": 1.0}
        below = {"x": 1.0, "y": 3.5, "w": 2.0, "h": 1.0}
        vertical = pptx_arrow_geometry(above, below)
        self.assertEqual((vertical["x1"], vertical["y1"]), (2.0, 1.5))
        self.assertEqual((vertical["x2"], vertical["y2"]), (2.0, 3.5))
        self.assertEqual(vertical["rotate"], 180)
        self.assertEqual(vertical["midpoint"]["y"], 2.5)

        offset = pptx_arrow_geometry({"x": 0, "y": 0, "w": 2, "h": 1}, {"x": 3, "y": 3, "w": 2, "h": 1})
        self.assertEqual(offset["y1"], 1)
        self.assertEqual(offset["y2"], 3)
        self.assertEqual(offset["rotate"], 135)
        self.assertAlmostEqual(offset["midpoint"]["x"], (offset["x1"] + offset["x2"]) / 2)
        self.assertAlmostEqual(offset["midpoint"]["y"], (offset["y1"] + offset["y2"]) / 2)

        sideways = pptx_arrow_geometry({"x": 0, "y": 0, "w": 2, "h": 1}, {"x": 5, "y": 0.5, "w": 2, "h": 1})
        self.assertEqual(sideways["x1"], 2)
        self.assertEqual(sideways["x2"], 5)

    def test_edge_mode_rejects_overlap_touch_and_shared_center(self):
        left = {"x": 0, "y": 0, "w": 3, "h": 2}
        overlap = {"x": 2, "y": 0, "w": 3, "h": 2}
        with self.assertRaises(ValueError):
            pptx_arrow_geometry(left, overlap)
        touching = {"x": 3, "y": 0, "w": 2, "h": 2}
        with self.assertRaises(ValueError):
            pptx_arrow_geometry(left, touching)
        outer = {"x": 0, "y": 0, "w": 10, "h": 10}
        inner = {"x": 6, "y": 4, "w": 2, "h": 2}
        with self.assertRaises(ValueError):
            pptx_arrow_geometry(outer, inner, mode="edge")
        contained = pptx_arrow_geometry(outer, inner, mode="center")
        self.assertEqual(contained["mode"], "center")
        self.assertGreater(contained["distance"], 0)
        with self.assertRaises(ValueError):
            pptx_arrow_geometry({"x": 0, "y": 0, "w": 4, "h": 4}, {"x": 1, "y": 1, "w": 2, "h": 2}, mode="center")

    def test_center_mode_line_is_behind_objects(self):
        spec = {
            "fileName": "flow.pptx",
            "slides": [{
                "items": [
                    {"id": "a", "kind": "shape", "shape": "rect", "x": 0.5, "y": 1, "w": 2, "h": 1},
                    {"id": "b", "kind": "shape", "shape": "ellipse", "x": 4, "y": 1, "w": 2, "h": 1},
                    pptx_connector("a", "b", mode="center"),
                ],
            }],
        }
        fragment = pptx_presentation(spec)
        runtime = fragment.rsplit("<script>", 1)[1].split("</script>", 1)[0]
        self.assertIn("(slideSpec.items||[])", runtime)
        self.assertNotIn("slideSpec.back||", runtime)
        self.assertNotIn("slideSpec.front", runtime)
        slide = _resolved(fragment)["slides"][0]
        self.assertEqual(set(slide), {"items"})
        kinds = [item.get("shape") if item["op"] == "shape" else item["op"] for item in slide["items"]]
        self.assertEqual(kinds, ["line", "triangle", "rect", "ellipse"])
        self.assertEqual(slide["items"][0]["options"]["x"], 1.5)
        self.assertEqual(slide["items"][0]["options"]["w"], 3.5)
        self.assertEqual(slide["items"][1]["shape"], "triangle")
        self.assertEqual(slide["items"][1]["options"]["rotate"], 90)

    def test_center_connectors_lead_the_list_and_edge_connectors_stay_put(self):
        spec = {
            "slides": [{
                "items": [
                    {"id": "a", "kind": "shape", "shape": "rect", "x": 0.5, "y": 1, "w": 2, "h": 1},
                    pptx_connector("a", "b", mode="center", color="111111"),
                    {"id": "b", "kind": "shape", "shape": "ellipse", "x": 4, "y": 1, "w": 2, "h": 1},
                    pptx_connector("b", "c"),
                    {"id": "c", "kind": "shape", "shape": "rect", "x": 2, "y": 3.2, "w": 2, "h": 1},
                    pptx_connector("a", "c", mode="center", color="222222"),
                ],
            }],
        }
        slide = _resolved(pptx_presentation(spec))["slides"][0]
        kinds = [item.get("shape") if item["op"] == "shape" else item["op"] for item in slide["items"]]
        self.assertEqual(kinds, [
            "line", "triangle", "line", "triangle",
            "rect", "ellipse", "line", "triangle", "rect",
        ])
        self.assertEqual(slide["items"][0]["options"]["line"]["color"], "111111")
        self.assertEqual(slide["items"][1]["options"]["line"]["color"], "111111")
        self.assertEqual(slide["items"][2]["options"]["line"]["color"], "222222")
        self.assertEqual(slide["items"][3]["options"]["line"]["color"], "222222")
        self.assertEqual(slide["items"][4]["shape"], "rect")
        self.assertEqual(slide["items"][5]["shape"], "ellipse")
        self.assertEqual(slide["items"][6]["op"], "line")
        self.assertEqual(slide["items"][8]["shape"], "rect")
        with self.assertRaises(ValueError):
            pptx_presentation({"slides": [{"back": [], "items": [], "front": []}]})

    def test_edge_connector_expands_inside_the_spec(self):
        spec = {
            "slides": [{
                "background": {"color": "#eef2ff"},
                "items": [
                    {"id": "a", "kind": "text", "text": "A", "x": 0.5, "y": 1, "w": 2, "h": 1,
                     "options": {"align": "center", "shape": "roundRect"}},
                    {"id": "b", "kind": "text", "text": "B", "x": 4, "y": 1, "w": 2, "h": 1},
                    pptx_connector("a", "b"),
                    {"kind": "table", "rows": [["Step", "Note"], ["1", "Generic"]],
                     "x": 0.5, "y": 3, "w": 4, "h": 1.2,
                     "options": {"colW": [2, 2], "border": {"color": "CCCCCC", "pt": 0.5}}},
                    {"kind": "image", "data": "image/png;base64,aaaa", "x": 5, "y": 3, "w": 1, "h": 1},
                    {"kind": "line", "x": 0.5, "y": 4.5, "w": 3, "h": -1,
                     "options": {"line": {"color": "112233", "width": 1, "dashType": "dash"}}},
                ],
            }],
        }
        fragment = pptx_presentation(spec, label="Save deck")
        self.assertIn(">Save deck<", fragment)
        self.assertIn("writeFile", fragment)
        self.assertIn("PptxGenJS", fragment)
        self.assertNotIn("endArrowType", fragment)
        deck = _resolved(fragment)
        slide = deck["slides"][0]
        self.assertEqual(slide["background"]["color"], "EEF2FF")
        self.assertNotIn("back", slide)
        self.assertNotIn("front", slide)
        kinds = [item.get("shape") if item["op"] == "shape" else item["op"] for item in slide["items"]]
        self.assertEqual(kinds, ["text", "text", "line", "triangle", "table", "image", "line"])
        self.assertEqual(slide["items"][2]["options"]["x"], 2.5)
        self.assertEqual(slide["items"][4]["rows"][0][0]["text"], "Step")
        self.assertEqual(slide["items"][5]["options"]["data"], "image/png;base64,aaaa")
        diagonal = slide["items"][6]["options"]
        self.assertTrue(diagonal["flipH"])
        self.assertEqual(diagonal["line"]["dashType"], "dash")
        self.assertNotIn("auto", deck)
        self.assertTrue(_resolved(pptx_presentation({"slides": [{"items": []}]}, auto=True))["auto"])
        self.assertIn('nonce="nonce-1"', pptx_presentation({"slides": [{"items": []}]}, nonce="nonce-1"))

    def test_rejects_invalid_specs_and_builtin_arrows(self):
        with self.assertRaises(ValueError):
            pptx_presentation([])
        with self.assertRaises(ValueError):
            pptx_presentation({"slides": []})
        with self.assertRaises(ValueError):
            pptx_presentation({"slides": [{"items": [{"kind": "text", "text": "A", "x": 0, "y": 0, "w": 1, "h": 1},
                                                     {"kind": "connector", "from": "missing", "to": "also"}]}]})
        with self.assertRaises(ValueError):
            pptx_connector("box", "box")
        with self.assertRaises(ValueError):
            pptx_presentation({"slides": [{"items": [
                {"id": "a", "kind": "shape", "shape": "rect", "x": 0, "y": 0, "w": 1, "h": 1},
                {"id": "a", "kind": "text", "text": "A", "x": 2, "y": 0, "w": 1, "h": 1},
            ]}]})
        with self.assertRaises(ValueError):
            pptx_presentation({"slides": [{"items": [
                {"kind": "line", "x": 0, "y": 0, "w": 1, "h": 0, "options": {"line": {"endArrowType": "triangle"}}},
            ]}]})
        with self.assertRaises(ValueError):
            pptx_presentation({"slides": [{"items": [
                {"kind": "image", "path": "http://example.test/a.png", "x": 0, "y": 0, "w": 1, "h": 1},
            ]}]})

    def test_slide_text_cannot_break_out_of_the_script(self):
        hostile = '</ScRiPt><script>alert(1)</script>&\u2028\u2029'
        fragment = pptx_presentation(
            {"author": hostile, "slides": [{"items": [
                {"kind": "text", "text": hostile, "x": 0.2, "y": 0.2, "w": 2, "h": 0.5},
            ]}]},
            label='<script>alert(1)</script>',
        )
        payload, after_json = fragment.split('id="download-pptx-spec">', 1)[1].split("</script>", 1)
        runtime = after_json.split("</script>", 1)[0]
        self.assertNotIn("<", payload)
        self.assertNotIn("\u2028", payload)
        self.assertNotIn("\u2029", payload)
        self.assertNotIn("alert(1)", runtime)
        self.assertIn("writeFile", runtime)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", fragment)
        resolved = _resolved(fragment)
        self.assertEqual(resolved["slides"][0]["items"][0]["text"], hostile)
        self.assertEqual(resolved["author"], hostile)

    def test_generated_objects_default_to_black_meiryo_and_no_fill(self):
        spec = {"slides": [{"items": [
            {"id": "a", "kind": "text", "text": "A", "x": 0.4, "y": 0.4, "w": 2, "h": 0.8},
            {"id": "b", "kind": "shape", "shape": "rect", "x": 3, "y": 0.4, "w": 2, "h": 0.8,
             "options": {"fill": {"color": "EEEEEE"}, "line": {"width": 2}}},
            {"kind": "text", "text": "Override", "x": 0.4, "y": 1.6, "w": 2, "h": 0.6,
             "options": {"color": "FF0000", "fontFace": "メイリオ", "fill": {"color": "AABBCC"}}},
            {"kind": "line", "x": 0.4, "y": 2.6, "w": 2, "h": 0},
            pptx_connector("a", "b", color="112233"),
            {"kind": "table", "rows": [["Name", {"text": "Value", "options": {"bold": True, "color": "0000FF"}}]],
             "x": 0.4, "y": 3.2, "w": 4, "h": 1},
        ]}]}
        slide = _resolved(pptx_presentation(spec))["slides"][0]
        text = slide["items"][0]["options"]
        self.assertEqual(text["color"], "000000")
        self.assertEqual(text["fontFace"], "Meiryo")
        self.assertEqual(text["fill"], {"type": "none"})
        self.assertEqual(text["line"]["color"], "000000")
        shape = slide["items"][1]["options"]
        self.assertEqual(shape["fill"], {"color": "EEEEEE"})
        self.assertEqual(shape["line"]["color"], "000000")
        self.assertEqual(shape["line"]["width"], 2)
        override = slide["items"][2]["options"]
        self.assertEqual(override["color"], "FF0000")
        self.assertEqual(override["fontFace"], "メイリオ")
        self.assertEqual(override["fill"], {"color": "AABBCC"})
        self.assertEqual(override["line"]["color"], "000000")
        self.assertEqual(slide["items"][3]["options"]["line"]["color"], "000000")
        connector_line = slide["items"][4]["options"]["line"]
        connector_head = slide["items"][5]["options"]
        self.assertEqual(connector_line["color"], "112233")
        self.assertEqual(connector_head["fill"], {"type": "none"})
        self.assertEqual(connector_head["line"]["color"], "112233")
        self.assertLess(
            next(index for index, item in enumerate(slide["items"]) if item["op"] == "line" and item["options"]["line"]["color"] == "112233"),
            next(index for index, item in enumerate(slide["items"]) if item["op"] == "table"),
        )
        table = slide["items"][6]
        self.assertEqual(table["options"]["fontFace"], "Meiryo")
        self.assertEqual(table["options"]["color"], "000000")
        self.assertEqual(table["options"]["fill"], {"type": "none"})
        self.assertEqual(table["options"]["border"], {"color": "000000", "pt": 1.25})
        self.assertEqual(table["rows"][0][0]["options"]["fontFace"], "Meiryo")
        self.assertEqual(table["rows"][0][0]["options"]["color"], "000000")
        self.assertEqual(table["rows"][0][1]["options"]["color"], "0000FF")
        self.assertTrue(table["rows"][0][1]["options"]["bold"])
        self.assertEqual(table["rows"][0][1]["options"]["fontFace"], "Meiryo")

    def test_python_source_does_not_assemble_office_xml(self):
        source = (ROOT / "web_ui.py").read_text(encoding="utf-8")
        for marker in ("p:spTree", "a:xfrm", "[Content_Types]", "ppt/slides"):
            self.assertNotIn(marker, source)

    def test_cli_and_one_liner_without_extra_packages(self):
        fragment = pptx_presentation({"slides": [{"items": [
            {"kind": "text", "text": "Hello", "x": 0.5, "y": 0.5, "w": 3, "h": 0.5},
        ]}]})
        run = subprocess.run(
            [sys.executable, "-S", str(ROOT / "web_ui.py"), "--trusted-html", "--with-remote-scripts", "pptxgenjs"],
            input=fragment,
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(PPTX_SRI, run.stdout)
        self.assertIn("writeFile", run.stdout)
        code = (
            "from web_ui import pptx_connector, pptx_presentation, render_document, remote_scripts; "
            "spec={'slides':[{'items':["
            "{'id':'a','kind':'shape','shape':'rect','x':0.5,'y':1,'w':2,'h':1},"
            "{'id':'b','kind':'shape','shape':'rect','x':4,'y':1,'w':2,'h':1},"
            "pptx_connector('a','b')"
            "]}]}; "
            "print(render_document(trusted_html=pptx_presentation(spec), "
            "remote_scripts=remote_scripts('pptxgenjs')), end='')"
        )
        run = subprocess.run([sys.executable, "-S", "-c", code], text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(run.returncode, 0, run.stderr)
        head, rest = run.stdout.split("</head>", 1)
        self.assertIn("pptxgen.bundle.js", head)
        self.assertIn("triangle", rest)


if __name__ == "__main__":
    unittest.main()
