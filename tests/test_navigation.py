import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
from html.parser import HTMLParser
import pytest
ROOT=Path(__file__).resolve().parents[1]


def _node_at_least_24() -> bool:
    if shutil.which("node") is None:
        return False
    try:
        done = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    match = re.search(r"v?(\d+)", (done.stdout or "") + (done.stderr or ""))
    return bool(match and int(match.group(1)) >= 24)
spec=importlib.util.spec_from_file_location('web_ui_navigation',ROOT/'web_ui.py');ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
@pytest.mark.skipif(not _node_at_least_24(), reason="run_node requires Node 24+")
def test_node_navigation_contract():
    result=ui.run_node(ROOT/'tests/navigation.node.js')
    assert result.returncode==0,result.stderr
def test_source_link_is_escaped_and_explicit():
    html=ui.source_link('source-url',label='<script>bad</script>')
    assert 'data-ui-source-for="source-url"' in html
    assert 'target="_blank"' in html and 'noopener noreferrer' in html and 'no-referrer' in html
    assert ' hidden>' in html and ' href=' not in html
    assert '&lt;script&gt;bad&lt;/script&gt;' in html
    with pytest.raises(ValueError):ui.source_link('bad" onclick="bad')
def test_view_tabs_escape_labels_and_reject_ambiguous_views():
    html=ui.view_tabs((('home','Home'),('wiki','<Wiki>')))
    assert 'data-ui-nav="wiki"' in html and '&lt;Wiki&gt;' in html
    with pytest.raises(ValueError):ui.view_tabs((('home','A'),('home','B')))
    with pytest.raises(ValueError):ui.view_tabs((('wiki','A'),))
def test_navigation_module_remains_opt_in():
    assert 'navigation.js' not in ui.render_document('A')
    assert ui.shared_scripts('.',names=('navigation.js',))==('./js/navigation.js',)
def test_adopt_static_export_preserves_data_and_script_bodies():
    source='<html><head><link rel="stylesheet" href="legacy.css?v=1"><style>pre, code { font-family: monospace; }</style></head><body><main class="old-page"><button id="go">Go</button><pre>{"snapshot":"old"}</pre><script>const s="<button>unchanged</button>pre, code { font-family: original; }";</script></main></body></html>'
    adapted=ui.adopt_document(source,asset_base='./vendor',class_aliases={'old-page':'ui-page'},remove_stylesheets=('legacy.css',))
    assert 'legacy.css' not in adapted and 'class="ui-page"' in adapted
    assert '<button id="go" class="ui-button">Go</button>' in adapted
    assert '{"snapshot":"old"}' in adapted
    assert '<script>const s="<button>unchanged</button>pre, code { font-family: original; }";</script>' in adapted
    assert 'font-family: inherit;' in adapted
    assert adapted==ui.adopt_document(adapted,asset_base='./vendor')


ROUTE_CASES = __import__('json').loads((ROOT / 'tests/fixtures/route_table_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', ROUTE_CASES['valid'], ids=lambda c: c['name'])
def test_route_table_valid_cases_match_navigation_js(case):
    rows = ui.route_table(case['registry'])
    lookup = {row['identity']: row['route'] for row in rows}
    routes = {row['route'] for row in rows}
    for key, expected in case['lookups'].items():
        found = lookup.get(key.replace('\ufe0f', ''), key if key in routes else None)
        assert found == expected, key


@pytest.mark.parametrize('case', ROUTE_CASES['invalid'], ids=lambda c: c['name'])
def test_route_table_invalid_cases_match_navigation_js(case):
    with pytest.raises(ValueError):
        ui.route_table(case['registry'])


def test_route_links_escape_and_carry_the_table():
    html = ui.route_links([{'route': '/', 'key': 'home', 'label': '</script><b>x'}, {'route': '/map', 'key': 'map'}])
    assert '</script><b>' not in html.split('<script', 1)[1].split('</script>', 1)[0]
    assert '\\u003c/script>' in html and 'href="#/"' in html and 'data-ui-go="map"' in html
    assert 'data-ui-routing="hash"' in html and '&lt;/script&gt;&lt;b&gt;x' in html
    assert 'href="/map"' in ui.route_links({'/map': 'map'}, routing='path')
    with pytest.raises(ValueError):
        ui.route_links({'/map': 'map'}, routing='query')
