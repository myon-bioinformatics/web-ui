"""The seed dial: theme.js gives the tokens of web_ui.random_theme, seed for seed (Node), and the dial's HTML.

Browser behaviour (dial, 🎲, ✖️, tap on a wall cell, named themes taking over) is in tests/integration/controls_browser.py.
"""
import json, random, subprocess, tempfile
from pathlib import Path

import pytest
import web_ui as ui
from support import node26

EDGES = [0, 1, 2, 11, 99, 2**31 - 1, 2**32 - 1, 2**32, 2**32 + 1, 2**40 + 5, 12345678901, 2**53 - 1, -1, -5, -2**32, -(2**40)]


def node_tokens(seeds):
    """randomTheme(seed) for every seed, run by Node on the module exactly as the page embeds it."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "theme.mjs").write_text(ui.js_source("theme.js"), encoding="utf-8")
        (root / "run.mjs").write_text("import{randomTheme}from'./theme.mjs';const seeds=JSON.parse(process.argv[2]);"
                                      "process.stdout.write(JSON.stringify(seeds.map(s=>randomTheme(s))))", encoding="utf-8")
        done = subprocess.run([node26(), str(root / "run.mjs"), json.dumps(seeds)], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(not node26(), reason="Node 26+ not available")
def test_the_page_gives_the_tokens_python_gives_for_every_seed():
    rng = random.Random(20261106)
    seeds = [*range(1500), *EDGES, *(rng.randrange(2**31) for _ in range(1500)), *(rng.randrange(2**53) for _ in range(300)),
             *(-rng.randrange(2**40) for _ in range(100))]
    got = node_tokens(seeds)
    assert len(got) == len(seeds)
    for seed, tokens in zip(seeds, got):
        expected = ui.random_theme(seed)
        assert tokens == expected, seed
        assert list(tokens) == list(expected), seed               # the same order too: the page writes them out as Python does


@pytest.mark.skipif(not node26(), reason="Node 26+ not available")
def test_a_seed_that_is_not_a_safe_integer_is_refused():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "theme.mjs").write_text(ui.js_source("theme.js"), encoding="utf-8")
        (root / "run.mjs").write_text("import{randomTheme}from'./theme.mjs';const bad=[];for(const s of [1.5,NaN,Infinity,2**53,'3',null])"
                                      "{try{randomTheme(s);bad.push(String(s))}catch(e){if(!(e instanceof RangeError))bad.push(String(s))}}"
                                      "process.stdout.write(JSON.stringify(bad))", encoding="utf-8")
        done = subprocess.run([node26(), str(root / "run.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []


def test_theme_js_is_a_module_and_the_page_is_not_given_anything_to_run_by_it():
    assert "theme.js" in ui.js_modules()
    source = ui.js_source("theme.js")
    for name in ("randomTheme", "applySeed", "clearSeed", "bindSeed"):
        assert f"export function {name}" in source
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "eval(", "innerHTML", "sessionStorage", "document.cookie"):
        assert banned not in source
    assert "</script" not in source.lower()


def test_the_dial_html_is_one_fieldset_with_the_hooks_bindSeed_looks_for():
    html = ui.seed_dial_html()
    for hook in ("data-ui-seed ", "data-ui-seed-out", "data-ui-seed-roll", "data-ui-seed-off", 'type="range"', 'max="99"'):
        assert hook in html
    assert html.startswith("<fieldset") and html.endswith("</fieldset>") and html.count("<fieldset") == 1
    assert 'max="12"' in ui.seed_dial_html(maximum=12)
    for bad in (0, -1, 2**31, 1.5, "9", True, None):
        with pytest.raises(ValueError):
            ui.seed_dial_html(maximum=bad)


def test_front_html_is_one_main_view_a_menu_and_one_room_per_entry():
    rooms = [{"id": "alpha", "emoji": "🅰️", "title": "Alpha <b>", "text": "First & best", "link": "Go", "html": '<p id="alpha">a</p>'},
             {"id": "beta", "emoji": "🅱️", "title": "Beta", "html": '<section><h2 id="beta">b</h2></section>'}]
    page = ui.front_html("<p>MAIN</p>", rooms, title="Hub & <Co>", lead="Lead <i>", tags=("v1",), icon="./i.png", tools=ui.seed_roll_html())
    assert page.count('<main class="ui-front">') == 1 and page.index("<p>MAIN</p>") < page.index('class="ui-room"')
    assert page.count('class="ui-room"') == 3                                                                         # the menu and two rooms
    assert '<section class="ui-room" id="rooms">' in page
    assert 'href="#alpha">Go →</a>' in page and 'href="#beta">Open →</a>' in page                                    # the link defaults to Open
    assert "Hub &amp; &lt;Co&gt;" in page and "Alpha &lt;b&gt;" in page and "First &amp; best" in page and "Lead &lt;i&gt;" in page
    assert "<b>" not in page and "<i>" not in page
    assert page.count('href="#rooms"') == 3 and page.count('href="#"') == 3                                          # 🚪 on the bar and in each room, ✖️ in each room and the menu
    assert '<img src="./i.png" width="32" height="32" alt="Hub &amp; &lt;Co&gt; icon">' in page and "data-ui-seed-roll" in page
    assert ":is(:target,:has(:target))" in ui.front_css() and "visibility:hidden" in ui.front_css()                   # rooms open by CSS alone
    assert ui.front_html("", rooms, title="x") == ui.front_html("", rooms, title="x") and "<img" not in ui.front_html("", rooms, title="x")


def test_front_html_refuses_rooms_it_cannot_open():
    ok = {"id": "a", "emoji": "A", "title": "A", "html": '<p id="a"></p>'}
    for bad in ([], [ok, ok], [{**ok, "id": "rooms"}], [{**ok, "id": "A B"}], [{**ok, "html": "<p></p>"}], [{**ok, "extra": 1}], [{"id": "a", "emoji": "A", "title": "A"}],
                [dict(ok, title="")], "nope", None, [ok] * 25):
        with pytest.raises(ValueError):
            ui.front_html("", bad, title="t")
    for kwargs in ({"icon": "javascript:alert(1)"}, {"icon": "//evil.example/x.png"}, {"tags": ["x"] * 7}, {"tags": "v1"}):
        with pytest.raises(ValueError):
            ui.front_html("", [ok], title="t", **kwargs)


def test_front_document_is_one_file_with_the_bundle_the_rules_and_the_icons():
    room = {"id": "a", "emoji": "A", "title": "A", "html": '<p id="a"></p>'}
    page = ui.front_document("<p>M</p>", [room], title="T", css=".x{}", scripts=ui.module_script("1;"), document_title="Tab", favicon="./f.png", icon="./i.png")
    assert "<title>Tab</title>" in page and '<link rel="icon" type="image/png" href="./f.png">' in page and '<link rel="apple-touch-icon" href="./i.png">' in page
    assert ui.front_css() in page and ".x{}" in page and 'rel="stylesheet"' not in page and "<script type=\"module\">1;</script>" in page


def test_render_document_icons_are_optional_png_links_that_stay_local_or_https():
    assert "rel=\"icon\"" not in ui.render_document("x") and "apple-touch-icon" not in ui.render_document("x")
    page = ui.render_document("x", favicon="https://example.test/f.png", touch_icon="./i.png")
    assert '<link rel="icon" type="image/png" href="https://example.test/f.png">' in page and '<link rel="apple-touch-icon" href="./i.png">' in page
    for bad in ("javascript:alert(1)", "data:image/png;base64,AAAA", "//evil.example/x.png", "./i.png?x=1", "", "https://u:p@example.test/x.png"):
        with pytest.raises(ValueError):
            ui.render_document("x", favicon=bad)


def test_the_curl_panel_and_theme_switch_are_builders_with_the_hooks_their_modules_bind():
    panel = ui.curl_panel_html()
    assert panel.count("data-ui-curl") == 1 and "data-curl-input" in panel and "data-curl-run" in panel and "data-curl-output" in panel
    assert "<h3>" in ui.curl_panel_html(heading_level=3) and "&lt;x&gt;" in ui.curl_panel_html("curl http://x/?a=<x>")
    for bad in ("x" * 2001, None, 5):
        with pytest.raises(ValueError):
            ui.curl_panel_html(bad)
    switch = ui.theme_switch_html()
    assert switch.count('name="ui-theme"') == 2 + len(ui.CANDIDATE_THEMES) and switch.count(" checked>") == 1 and 'value="modern" checked' in switch
