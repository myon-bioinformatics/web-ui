"""The generic source panel: a name (one GET) or pasted JSON read through a consumer's declarative spec into Markdown tables.

Python (``web_ui.source_*``) is the reference; ``source.js`` must agree: ``tests/fixtures/source/cases.json`` is run by both.
"""
import copy, html, importlib.util, json, re
from pathlib import Path

import pytest
from support import node26

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "source"
_spec = importlib.util.spec_from_file_location("web_ui_source_panel", ROOT / "web_ui.py")
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

CASES = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))
POKEMON = json.loads((FIX / "pokeapi.spec.json").read_text(encoding="utf-8"))
DITTO = (FIX / "ditto.json").read_text(encoding="utf-8")
DITTO_MD = (FIX / "ditto.md").read_text(encoding="utf-8")


def _minimal(**over):
    spec = {"id": "t", "label": "Name", "name": "[a-z]+", "url": "https://example.test/{name}", "title": "T",
            "tables": [{"headers": ["a"], "rows": [[{"key": "a"}]]}]}
    spec.update(over)
    return spec


@pytest.mark.parametrize("case", CASES["extract"], ids=lambda c: c["name"])
def test_extract_cases_match_source_js(case):
    if "markdown" in case:
        assert ui.source_markdown(ui.source_extract(case["spec"], case["source"])) == case["markdown"]
    else:
        with pytest.raises(ValueError) as caught:
            ui.source_extract(case["spec"], case["source"])
        assert str(caught.value) == case["error"]


def test_name_and_url_cases_match_source_js():
    names = CASES["names"]
    for text, want in names["valid"]:
        assert ui.source_name(names["spec"], text) == want
    for text in names["invalid"]:
        assert ui.source_name(names["spec"], text) == ""
    for text, want in names["urls"]:
        assert ui.source_url(names["spec"], text) == want


def test_pokemon_spec_reproduces_the_lab_markdown_byte_for_byte():
    # tests/fixtures/source/ditto.md is what mcp-toolcall-lab's adapters/pokeapi.py writes for the same JSON.
    extract = ui.source_extract(POKEMON, DITTO)
    assert ui.source_markdown(extract) == DITTO_MD
    assert ui.source_markdown(ui.source_extract(POKEMON, json.loads(DITTO))) == DITTO_MD
    assert extract["title"] == "ditto (#132)" and [t["headers"] for t in extract["tables"]][0] == ["type", "height m", "weight kg"]
    assert ui.source_url(POKEMON, " Ditto ") == "https://pokeapi.co/api/v2/pokemon/ditto"
    assert ui.source_url(POKEMON, "../x") == "" and ui.source_url(POKEMON, "") == ""


def test_extract_limits_and_messages():
    with pytest.raises(ValueError, match="exceeds"):
        ui.source_extract(POKEMON, " " * (ui.SOURCE_LIMIT + 1))
    small = dict(POKEMON, limit=10)
    with pytest.raises(ValueError, match="exceeds 10 bytes"):
        ui.source_extract(small, DITTO)
    with pytest.raises(ValueError, match="source is not JSON"):
        ui.source_extract(POKEMON, "{")
    with pytest.raises(ValueError, match="not a PokéAPI pokemon response"):
        ui.source_extract(POKEMON, '{"name":"x","id":1}')
    # With no custom error text the generic one is used; deep nesting never escapes as another exception type.
    with pytest.raises(ValueError, match="not the expected response"):
        ui.source_extract(_minimal(), "{}")
    with pytest.raises(ValueError):  # a pathologically deep document is refused, never a RecursionError
        ui.source_extract(_minimal(), "[" * 100000 + "]" * 100000)


@pytest.mark.parametrize("change, why", [
    (lambda s: s.update(extra=1), "unknown key"),
    (lambda s: s.pop("tables"), "tables required"),
    (lambda s: s.update(id="Bad Id"), "id token"),
    (lambda s: s.update(url="http://example.test/{name}"), "https only"),
    (lambda s: s.update(url="https://u:p@example.test/{name}"), "no credentials"),
    (lambda s: s.update(url="https://example.test/{name}/{name}"), "one {name}"),
    (lambda s: s.update(url="https://example.test/ {name}"), "no blanks"),
    (lambda s: s.update(name="(?i)abc"), "no inline flags"),
    (lambda s: s.update(name="é+"), "ASCII pattern"),
    (lambda s: s.update(name="("), "valid regex"),
    (lambda s: s.update(limit=0), "limit range"),
    (lambda s: s.update(limit=ui.SOURCE_LIMIT + 1), "limit range"),
    (lambda s: s.update(limit=True), "limit int"),
    (lambda s: s.update(tables=[]), "at least one table"),
    (lambda s: s.update(tables=[{"headers": ["a"], "rows": [[{"key": "a"}]], "each": "x", "cells": []}]), "rows xor each"),
    (lambda s: s.update(tables=[{"headers": ["a", "b"], "rows": [[{"key": "a"}]]}]), "one cell per header"),
    (lambda s: s.update(tables=[{"headers": ["a"], "rows": [[{"key": "a", "bogus": 1}]]}]), "cell keys"),
    (lambda s: s.update(tables=[{"headers": ["a"], "rows": [[{"key": "a", "div": 0}]]}]), "div nonzero"),
    (lambda s: s.update(tables=[{"headers": ["a"], "rows": [[{"key": ""}]]}]), "key required"),
    (lambda s: s.update(label="x" * 401), "text length"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_spec_validation_rejects(change, why):
    spec = _minimal()
    change(spec)
    with pytest.raises(ValueError):
        ui.source_spec(spec)
    with pytest.raises(ValueError):
        ui.source_panel_html(spec)


def test_spec_validation_accepts_the_shipped_specs_and_non_objects_fail():
    assert ui.source_spec(POKEMON) is POKEMON and ui.source_spec(_minimal())
    for bad in (None, [], "x", 3):
        with pytest.raises(ValueError):
            ui.source_spec(bad)


def test_panel_html_carries_the_spec_and_escapes_text():
    spec = _minimal(label='<b>"Name"</b>', heading="<script>x</script>", note="a & b", placeholder='"><img src=x>')
    page = ui.source_panel_html(spec, heading_level=3)
    assert page.startswith('<section class="ui-panel ui-source" id="source-t" data-ui-source data-source-spec="')
    assert "<h3>&lt;script&gt;x&lt;/script&gt;</h3>" in page and "<script>" not in page and "<img" not in page
    assert "&lt;b&gt;&quot;Name&quot;&lt;/b&gt;" in page or "&lt;b&gt;" in page
    attribute = re.search(r'data-source-spec="([^"]*)"', page).group(1)
    assert json.loads(html.unescape(attribute)) == spec
    for hook in ("data-source-name", "data-source-fetch", "data-source-open", "data-source-text", "data-source-extract",
                 "data-source-status", "data-source-error", "data-source-output"):
        assert hook in page
    assert re.search(r'<p class="ui-source-error" role="alert" data-source-error hidden>', page)
    assert re.search(r'<pre class="ui-output" data-source-output hidden>', page)
    assert 'role="status"' in page
    # heading_level falls back to 2 for anything outside 1..6; the panel never embeds a network address outside its spec attribute.
    assert "<h2>" in ui.source_panel_html(spec, heading_level=9)
    assert "<h2>" in ui.source_panel_html(spec, heading_level="3")
    assert "example.test" not in re.sub(r'data-source-spec="[^"]*"', "", page)


def test_panel_html_for_pokemon_has_stable_ids():
    page = ui.source_panel_html(POKEMON)
    assert 'id="source-pokemon"' in page and 'for="pokemon-name"' in page and 'id="pokemon-text"' in page
    assert ">Pokémon<" in page and "Pokémon name or number" in page


def test_css_and_js_are_python_data_and_ship_with_the_bundle():
    css = ui.bundled_css()
    assert ".ui-source-row" in css and ".ui-source-error" in css and "var(--ui-danger)" in css
    assert ui._CSS["source.css"].startswith("@layer components{")
    assert "source.js" in ui.js_modules() and "webUiSource" in ui.js_modules()["source.js"]
    # No module ships a network address of its own: the spec names it.
    assert "https://" not in ui.js_modules()["source.js"]


def test_source_module_is_opt_in_and_written_by_site_export(tmp_path):
    assert "source.js" not in ui.render_document("A") and "data-ui-source" not in ui.render_document("A")
    assert ui.js_source("source.js") is ui.js_modules()["source.js"]
    assert "js/source.js" in "".join(ui.write_js(tmp_path)).replace("\\", "/")
    assert (tmp_path / "js" / "source.js").read_text(encoding="utf-8") == ui.js_modules()["source.js"]


def test_markdown_never_breaks_the_table_shape():
    out = ui.source_markdown({"title": "a\nb", "tables": [{"headers": ["x|y"], "rows": [["1|2\n3"], ["\r"]]}]})
    assert out == "# a b\n\n| x\\|y |\n| --- |\n| 1\\|2 3 |\n|   |\n"
    for line in out.splitlines()[2:]:
        assert line.startswith("| ") and line.endswith(" |")


def test_spec_is_not_mutated():
    before = copy.deepcopy(POKEMON)
    ui.source_extract(POKEMON, DITTO)
    ui.source_panel_html(POKEMON)
    ui.source_url(POKEMON, "ditto")
    assert POKEMON == before


@pytest.mark.skipif(not node26(), reason="run_node requires Node 26+")
def test_node_source_contract():
    result = ui.run_node(ROOT / "tests/source.node.js")
    assert result.returncode == 0, result.stderr
