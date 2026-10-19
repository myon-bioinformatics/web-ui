"""layout_presets: switchable presets as data, CSS and radio controls; sweep results become candidates."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import layout_presets as lp  # noqa: E402

SPEC = json.loads((ROOT / "examples/layout-presets.json").read_text(encoding="utf-8"))


def test_presets_are_valid_and_css_switches_on_the_checked_radio():
    data = lp.validate(SPEC)
    assert data["default"] == "grid8" and [p["id"] for p in data["presets"]] == ["grid8", "compact", "device", "wide"]
    css = lp.css(SPEC)
    assert css.startswith(":root{--ui-matrix-col:160px;--ui-matrix-gap:8px;--ui-matrix-pad:8px}\n")
    assert 'body:has(input[name="ui-layout"][value="device"]:checked){--ui-matrix-col:195px' in css
    html = lp.controls_html(SPEC)
    assert html.count('type="radio" name="ui-layout"') == 4 and html.count(" checked") == 1
    assert "195px = half an iPhone (390px)" in html


@pytest.mark.parametrize("change", [
    {"schema": "other"}, {"presets": []}, {"default": "nope"},
    {"presets": [{"id": "A", "label": "x", "vars": {"--ui-a": "1px"}}]},
    {"presets": [{"id": "a", "label": "", "vars": {"--ui-a": "1px"}}]},
    {"presets": [{"id": "a", "label": "x", "vars": {"--ui-a": "red"}}]},
    {"presets": [{"id": "a", "label": "x", "vars": {"color": "1px"}}]},
    {"presets": [{"id": "a", "label": "x", "vars": {"--ui-a": "1px;}body{x:1px"}}]},
    {"presets": [{"id": "a", "label": "x", "vars": {"--ui-a": "1px"}}, {"id": "a", "label": "y", "vars": {"--ui-a": "2px"}}]},
    {"presets": [{"id": "a", "label": "x", "vars": {"--ui-a": "1px"}}, {"id": "b", "label": "y", "vars": {"--ui-b": "2px"}}]},
    {"presets": [{"id": "a", "label": "x", "vars": {"--ui-a": "1px"}, "extra": 1}]},
])
def test_invalid_presets_are_rejected(change):
    with pytest.raises(ValueError):
        lp.validate({**SPEC, **change})


def test_candidates_allow_several_passing_presets_and_label_without_disabling():
    data = lp.validate(SPEC)
    rows = [{"preset": "grid8", "width": 320, "ok": True, "failed": []},
            {"preset": "compact", "width": 320, "ok": True, "failed": []},
            {"preset": "wide", "width": 320, "ok": False, "failed": ["horizontal_overflow"]},
            {"preset": "wide", "width": 1280, "ok": True, "failed": []}]
    result = lp.candidates(data, rows)
    assert result["by_width"] == {"320": ["grid8", "compact"], "1280": ["wide"]}
    assert result["every_width_has_a_candidate"] and result["presets"]["device"] == {"passed": [], "failed": []}
    html = lp.controls_html(SPEC, result)
    assert "ok at 1280px; check at 320px" in html and 'value="wide"> Wide' in html and "disabled" not in html
    assert lp.candidates(data, rows[2:3])["every_width_has_a_candidate"] is False
    with pytest.raises(ValueError, match="candidates"):
        lp.controls_html(SPEC, {"schema": "x"})


def test_cli_css_and_html(capsys):
    assert lp.main(["css", str(ROOT / "examples/layout-presets.json")]) == 0
    assert capsys.readouterr().out == lp.css(SPEC)
    assert lp.main(["html", str(ROOT / "examples/layout-presets.json")]) == 0
    assert capsys.readouterr().out == lp.controls_html(SPEC) + "\n"
    with pytest.raises(ValueError, match="widths"):
        lp.sweep("file:///x", SPEC, [100], items="li")
