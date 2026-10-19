"""capture_matrix: representative Flutter pages by emoji, and a viewer for multi-browser captures."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import capture_matrix as cm  # noqa: E402
import web_ui  # noqa: E402

PAGES = json.loads((ROOT / "examples/flutter-pages.json").read_text(encoding="utf-8"))
# browser-test-kit adapters/flutter-*.json (contract shared by fixture, not by import).
BTK_ADAPTERS = {"flutter-home": "/", "flutter-hub": "/hub", "flutter-clipboard-shelf": "/core/clipboard-shelf",
                "flutter-now-timeline": "/tools/time/now-timeline", "flutter-photo-studio": "/tools/media/photo-studio",
                "flutter-http-request-draft": "/tools/http/request-draft", "flutter-ui-showcase": "/examples/ui-showcase",
                "flutter-counter": "/examples/counter-playground", "flutter-screen1": "/screen1"}


def report(**extra):
    base = {"schema": "ironmate-browser-matrix/1", "reference": "Linux-chromium-desktop",
            "pages": ["flutter-home", "flutter-hub"], "envs": ["Linux-chromium-desktop", "macOS-webkit-iphone"],
            "cells": [{"page": "flutter-home", "env": "Linux-chromium-desktop", "difference": {"rgb_mae": 0}},
                      {"page": "flutter-home", "env": "macOS-webkit-iphone", "difference": {"rgb_mae": 12.34}},
                      {"page": "flutter-hub", "env": "Linux-chromium-desktop", "difference": {"rgb_mae": 0}}]}
    return {**base, **extra}


def test_page_table_is_the_btk_page_set_and_a_valid_route_table():
    assert PAGES["schema"] == "web-ui-flutter-pages/1"
    rows = web_ui.route_table(PAGES["pages"])
    assert {p["adapter"]: p["route"] for p in PAGES["pages"]} == BTK_ADAPTERS
    assert [r["identity"] for r in rows][:3] == ["\U0001F3E0", "\U0001F5FA", "\U0001F4CB"]
    for page in PAGES["pages"]:
        assert page["url"] == PAGES["base_url"] + "#" + page["route"]


def test_viewer_sections_open_by_emoji_without_javascript():
    dataset = {"schema": "btk-platform-matrix/1", "records": [
        {"env": {"id": "macOS-webkit-iphone"}, "verdict": "fail",
         "target": {"adapter": "flutter-home", "provenance": {"value": "a" * 40}}},
        {"env": {"id": "Linux-chromium-desktop"}, "verdict": "pass", "target": {"adapter": "flutter-hub"}},
        {"env": {"id": "Linux-chromium-desktop"}, "verdict": "pass"}]}  # fixture record without a target
    page = cm.viewer(PAGES, report(), dataset)
    assert '<section id="/hub" class="ui-panel">' in page and '<section id="/" class="ui-panel">' in page
    assert 'href="#/hub" data-ui-go="\U0001F5FA\ufe0f"' in page and 'id="ui-route-table"' in page
    assert '<script src' not in page  # route links work from file:// without the navigation module
    assert 'src="./tiles/flutter-home/macOS-webkit-iphone.png"' in page and "MAE 12.3" in page
    assert '<li class="is-fail">' in page and "fail \u00b7 build " + "a" * 12 in page
    # 7 pages without cells (both environments) plus the hub on iPhone; the reference column keeps its marker.
    assert page.count('class="is-missing"') == 8 and page.count('class="is-missing is-reference"') == 7
    assert 'class="is-reference"' in page and 'href="./css/matrix.css"' in page
    assert "https://myon-bioinformatics.github.io/flutter_navigation_basic/#/screen1" in page


def test_viewer_escapes_and_embeds_css():
    pages = {"pages": [{"route": "/x", "key": "<b>", "label": "<i>", "adapter": "a<b", "url": "https://e.test/#/x"}]}
    page = cm.viewer(pages, report(pages=["a<b"], cells=[]), embed_css=True, theme="modern")
    assert "<b>" not in page.split("<style>")[1].split("</style>")[1] and "&lt;i&gt;" in page
    assert ".ui-matrix:has(" in page and '<body data-ui-theme="modern">' in page


def test_matrix_css_spacing_is_on_the_8px_grid():
    import re
    css = (ROOT / "css/matrix.css").read_text(encoding="utf-8")
    sizes = [int(v) for v in re.findall(r"(?<![\d.])(\d+)px", css) if v not in ("1", "2")]  # borders/outlines
    assert sizes and all(v % 8 == 0 for v in sizes) and "rem" not in css.replace(".8rem", "")


@pytest.mark.parametrize("change", [
    {"report": {"schema": "other"}}, {"theme": "dark"}, {"tiles_base": "https://cdn"}, {"asset_base": "a\"b"},
    {"pages": {"pages": [{"route": "/x", "key": "k", "adapter": "a", "url": "http://insecure/"}]}},
    {"pages": {"pages": [{"route": "/x", "key": "k", "url": "https://e/"}]}},
    {"pages": {"pages": [{"route": "/x", "key": "k", "adapter": "a", "url": "https://e/"},
                         {"route": "/y", "key": "j", "adapter": "a", "url": "https://e/"}]}},
    {"pages": {"pages": [{"route": "/x", "key": "k", "adapter": "a", "url": "https://e/"},
                         {"route": "/x", "key": "j", "adapter": "b", "url": "https://e/"}]}},
    {"pages": {"rows": []}},
])
def test_viewer_rejects_bad_inputs(change):
    args = {"pages": PAGES, "report": report(), **change}
    with pytest.raises(ValueError):
        cm.viewer(args.pop("pages"), args.pop("report"), **args)


def test_cli_writes_a_page_or_exits_2(tmp_path):
    (tmp_path / "report.json").write_text(json.dumps(report()), encoding="utf-8")
    run = subprocess.run([sys.executable, "-S", str(ROOT / "tool/capture_matrix.py"), "--pages",
                          str(ROOT / "examples/flutter-pages.json"), "--report", str(tmp_path / "report.json"),
                          "--embed-css"], capture_output=True, text=True, encoding="utf-8", cwd=tmp_path)
    assert run.returncode == 0 and run.stdout.startswith("<!doctype html>") and "<style>" in run.stdout
    (tmp_path / "bad.json").write_text('{"schema": "x"}', encoding="utf-8")
    bad = subprocess.run([sys.executable, "-S", str(ROOT / "tool/capture_matrix.py"), "--pages",
                          str(tmp_path / "bad.json"), "--report", str(tmp_path / "report.json")],
                         capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode == 2 and "expected schema web-ui-flutter-pages/1" in bad.stderr
