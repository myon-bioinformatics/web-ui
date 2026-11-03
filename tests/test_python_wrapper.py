import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import json
import math

import web_ui
from web_ui import _node_launch_module, bundled_css, render_document, run_node, shared_scripts

ROOT = Path(__file__).resolve().parents[1]


def _node_at_least_26() -> bool:
    if shutil.which("node") is None:
        return False
    try:
        done = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    match = re.search(r"v?(\d+)", (done.stdout or "") + (done.stderr or ""))
    return bool(match and int(match.group(1)) >= 26)


class PythonWrapperTests(unittest.TestCase):
    def test_user_values_remain_text_and_no_scripts_by_default(self):
        html = render_document('<script>alert(1)</script>&', title='"<Title>')
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;&amp;', html)
        self.assertIn('&lt;Title&gt;', html)
        self.assertNotIn('<script', html)
        self.assertIn('data-ui-theme="modern"', html)

    def test_generic_document_does_not_inherit_pages_branding(self):
        html = render_document("Consumer output", title="Consumer page")
        self.assertNotIn('rel="icon"', html)
        self.assertNotIn("docs/brand", html)
        self.assertNotIn("favicon.png", html)

    def test_authored_html_and_css_can_be_supplied(self):
        html = render_document(
            trusted_html='<main class="ui-page">Hi</main>',
            css='body { color: #000; background: #fff; }',
            theme='github-like',
        )
        self.assertIn('<main class="ui-page">Hi</main>', html)
        self.assertIn('<style>body { color: #000; background: #fff; }</style>', html)
        self.assertIn('data-ui-theme="github-like"', html)

    def test_external_stylesheets_are_still_escaped_links(self):
        self.assertIn('href="a&amp;b.css"', render_document(stylesheets=('a&b.css',)))
        self.assertFalse(hasattr(web_ui, "shared_stylesheets"), "stylesheets are embedded, not linked from css/ files")

    def test_opt_in_shared_scripts_are_module_links(self):
        scripts = shared_scripts('.', names=('ui.js', 'stub.js'))
        self.assertEqual(scripts, ('./js/ui.js', './js/stub.js'))
        for src in scripts:
            self.assertIn(src.rsplit("/", 1)[1], web_ui.js_modules())  # modules are written by write_js()/--site
        html = render_document(scripts=scripts)
        self.assertIn('<script type="module" src="./js/ui.js"></script>', html)
        self.assertIn('<script type="module" src="./js/stub.js"></script>', html)
        self.assertNotIn('<script>', html)

    def test_remote_and_ambiguous_scripts_rejected_on_both_paths(self):
        invalid = (
            'https://example.test/latest', 'https://example.test/main',
            'https://example.test/' + 'a' * 40, '//example.test',
            '///example.test', 'http://example.test', 'javascript:alert(1)',
            'data:text/javascript,alert(1)', 'file:///tmp/ui.js',
            'https://user:password@example.test/latest',
            r'\\example.test', r'/\example.test',
            ' /assets', '/assets\n', '/assets\t', '/assets\x00', '/assets\x7f',
            '', '/assets?ref=latest', '/assets#latest', '/assets?', '/assets#',
        )
        for value in invalid:
            with self.subTest(value=value, api='shared'), self.assertRaises(ValueError):
                shared_scripts(value)
            with self.subTest(value=value, api='direct'), self.assertRaises(ValueError):
                render_document(scripts=(value,))

    def test_local_module_paths_remain_supported(self):
        for base in ('.', './vendor/web-ui', '../vendor/web-ui', '/assets/web-ui', '/'):
            with self.subTest(base=base):
                scripts = shared_scripts(base)
                self.assertEqual(scripts, (base.rstrip('/') + '/js/ui.js',))
                self.assertIn('src="' + scripts[0] + '"', render_document(scripts=scripts))
        self.assertIn('src="./owned/custom.js"',
                      render_document(scripts=('./owned/custom.js',)))
        self.assertIn('src="./owned/a&amp;b.js"',
                      render_document(scripts=('./owned/a&b.js',)))

    def test_html_css_output_compatibility_without_scripts(self):
        self.assertEqual(
            render_document('A&B', title='Title', css='body{color:red}',
                            stylesheets=('https://example.test/main.css?v=1',)),
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Title</title><link rel="stylesheet" href="https://example.test/main.css?v=1">'
            '<style>body{color:red}</style></head><body data-ui-theme="modern">'
            '<main class="ui-page"><section class="ui-panel"><h1 class="ui-title">Title</h1>'
            '<pre class="ui-output">A&amp;B</pre></section></main></body></html>\n',
        )

    def test_cli_remote_assets_are_css_only(self):
        command = [sys.executable, '-S', str(ROOT / 'web_ui.py'),
                   '--asset-base', 'https://example.test/latest']
        plain = subprocess.run(command, input='ok', text=True, capture_output=True)
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertNotIn('<script', plain.stdout)
        for names in ([], ['ui.js']):
            with self.subTest(names=names):
                linked = subprocess.run(command + ['--with-scripts'] + names,
                                        input='ok', text=True, capture_output=True)
                self.assertEqual(linked.returncode, 2)
                self.assertEqual(linked.stdout, '')
                self.assertIn('must be a local path', linked.stderr)

    def test_invalid_inputs_and_raw_text_escape_are_rejected(self):
        for css in ('</STYLE><script>x</script>', '</style >', '</style/>'):
            with self.subTest(css=css), self.assertRaises(ValueError):
                render_document(css=css)
        for href in (
            'javascript:alert(1)',
            '//example.test/a.css',
            'http://example.test/a.css',
            'https://user:password@example.test/a.css',
        ):
            with self.subTest(href=href), self.assertRaises(ValueError):
                render_document(stylesheets=(href,))
            with self.subTest(script=href), self.assertRaises(ValueError):
                render_document(scripts=(href,))
        with self.assertRaises(ValueError):
            render_document(theme='unknown')
        with self.assertRaises(ValueError):
            shared_scripts('https://example.test/main?ref=latest', names=('ui.js',))
        with self.assertRaises(ValueError):
            shared_scripts('.', names=('missing.js',))

    def test_cli_stdlib_only_read_only_inputs_and_opt_in_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            css = Path(directory) / 'palette.css'
            original = b'body { color: #000; }'
            css.write_bytes(original)
            run = subprocess.run(
                [sys.executable, '-S', str(ROOT / 'web_ui.py'), '--css', str(css)],
                input='<b>user</b>',
                text=True,
                capture_output=True,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('&lt;b&gt;user&lt;/b&gt;', run.stdout)
            self.assertIn(original.decode(), run.stdout)
            self.assertNotIn('<script', run.stdout)
            self.assertEqual(css.read_bytes(), original)
        run = subprocess.run(
            [sys.executable, '-S', str(ROOT / 'web_ui.py'), '--stub'],  # removed flag: usage error
            input='',
            text=True,
            capture_output=True,
        )
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stdout, '')
        linked = subprocess.run(
            [
                sys.executable,
                '-S',
                str(ROOT / 'web_ui.py'),
                '--asset-base',
                '.',
                '--with-scripts',
                'ui.js',
            ],
            input='ok',
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(linked.returncode, 0, linked.stderr)
        self.assertIn('<script type="module" src="./js/ui.js"></script>', linked.stdout)

    def test_run_node_wraps_diagnostics_script(self):
        if not _node_at_least_26():
            self.skipTest('node 26+ not available')
        with tempfile.TemporaryDirectory() as out:
            web_ui.write_js(out)
            result = run_node(ROOT / 'tests' / 'repository_diagnostics.node.js', env={'WEB_UI_JS_DIR': str(Path(out) / 'js')})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_run_node_reports_missing_executable(self):
        node_launch = _node_launch_module()
        node_launch.clear_probe_cache()
        with mock.patch.object(node_launch.shutil, 'which', return_value=None):
            with self.assertRaises(RuntimeError):
                run_node('missing.js')

    def test_python_c_layout_one_liner(self):
        run = subprocess.run(
            [
                sys.executable,
                '-S',
                '-c',
                'from web_ui import render_document; print(render_document("one-liner", title="Demo"), end="")',
            ],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('data-ui-theme="modern"', run.stdout)
        self.assertIn('one-liner', run.stdout)
        self.assertNotIn('<script', run.stdout)


class BundledCssTests(unittest.TestCase):
    def test_bundle_is_built_in_memory_from_every_source_in_a_fixed_order(self):
        css = bundled_css()
        marks = re.findall(r"^/\* css/(\S+) \*/$", css, re.MULTILINE)
        self.assertEqual(marks[:3], ["tokens.css", "base.css", "components.css"])
        self.assertEqual(sorted(marks), sorted(web_ui._CSS))
        themes = [m for m in marks if m.startswith("themes/")]
        self.assertEqual(marks[-len(themes):], themes)
        self.assertEqual(themes, sorted(themes))
        self.assertTrue(css.startswith("@layer base,components,theme;\n"))
        self.assertLess(css.index("@layer base,components,theme;"), css.index("@layer base{"))
        for name in web_ui._CSS:
            self.assertIn(web_ui.css_source(name).strip("\n"), css)
        self.assertEqual(css, bundled_css())
        self.assertFalse((ROOT / "css").exists(), "there are no css/ files: Python is the only source")
        with self.assertRaises(ValueError):
            web_ui.css_source("nope.css")

    def test_single_file_page_works_for_every_theme_without_links(self):
        css = bundled_css()
        for theme in ("modern", "github-like", "green"):
            html = render_document("hello", theme=theme, css=css)
            self.assertIn(f'data-ui-theme="{theme}"', html)
            self.assertNotIn('rel="stylesheet"', html)
            self.assertIn(f'body[data-ui-theme="{theme}"]', css)

    def test_candidate_themes_live_in_tokens_and_any_hue_makes_a_theme(self):
        tokens = web_ui.css_source("tokens.css")
        for name in web_ui.CANDIDATE_THEMES:
            self.assertIn(f'body[data-ui-theme="{name}"]', tokens)
            self.assertNotIn(f"themes/{name}.css", web_ui._CSS)
        self.assertEqual(web_ui.CANDIDATE_THEMES, ("green", "red", "blue"))
        for hue in (0.0, 0.08, 0.33, 0.6, 0.83):
            for dark in (False, True):
                theme = web_ui.theme_palette(hue, dark=dark)
                for text, minimum in (("fg", 7), ("muted", 4.5), ("accent", 4.5), ("danger", 4.5)):
                    for ground in ("bg", "panel"):
                        self.assertGreaterEqual(web_ui.contrast_ratio(theme[f"--ui-{text}"], theme[f"--ui-{ground}"]), minimum, (hue, dark, text))
        self.assertEqual(web_ui.theme_palette(0.3), web_ui.theme_palette(0.3))

    @unittest.skipUnless(_node_at_least_26(), "Node 26+ not available")
    def test_node_reaches_the_bundle_through_the_shared_launcher(self):
        # No Node twin and no web_ui.cjs: Node runs web_ui.py via vendor/py_launch.cjs, so the bytes cannot differ.
        args = ["--css-bundle", "--theme", "green"]
        env = {**os.environ, "PYTHON": sys.executable}
        run = lambda argv: subprocess.run(argv, cwd=ROOT, env=env, input="hello\n", capture_output=True,
                                          text=True, encoding="utf-8", timeout=60)
        via_node = run(["node", "vendor/py_launch.cjs", "--", "web_ui.py", *args])
        via_python = run([sys.executable, "-S", "web_ui.py", *args])
        self.assertEqual(via_python.returncode, 0, via_python.stderr)
        self.assertEqual((via_node.returncode, via_node.stdout), (0, via_python.stdout))
        self.assertIn('body[data-ui-theme="green"]', via_node.stdout)


WORLD = web_ui.example_data("world")


def _has_tzdata() -> bool:
    try:
        import zoneinfo
        zoneinfo.ZoneInfo("Europe/London")
        return True
    except Exception:
        return False


class WorldTests(unittest.TestCase):
    """One page, a camera: Python validates, does the arithmetic and writes HTML, CSS and a thin JS module."""

    def test_demo_world_is_valid_and_validation_is_idempotent(self):
        world = web_ui.world_validate(WORLD)
        self.assertEqual(web_ui.world_validate(world), world)
        self.assertEqual([f["id"] for f in world["floors"]], ["1f", "2f"])

    def test_invalid_worlds_are_rejected(self):
        spot = {"id": "a", "x": 8, "y": 8, "label": "A"}
        floor = {"id": "f", "label": "F", "width": 64, "height": 64, "spots": [spot]}
        bad = [
            {"schema": "other"}, {**WORLD, "extra": 1}, {"schema": web_ui.WORLD_SCHEMA},
            {**WORLD, "id": "1bad"}, {**WORLD, "zoom_max": 9},
            {**WORLD, "shots": [{"id": "A", "label": "x", "title": "t"}]},
            {**WORLD, "shots": [{"id": "a", "label": "x", "title": "t", "bg": "red"}]},
            {**WORLD, "shots": [{"id": "a", "label": "x", "title": ""}]},
            {**WORLD, "floors": [{**floor, "spots": [{**spot, "x": 65}]}]},
            {**WORLD, "floors": [{**floor, "spots": [{**spot, "x": 1.5}]}]},
            {**WORLD, "floors": [{**floor, "spots": [spot, spot]}]},
            {**WORLD, "floors": [{**floor, "spots": []}]},
            {**WORLD, "floors": [{**floor, "width": 63}]},
            {**WORLD, "floors": [{**floor, "spots": [{**spot, "category": "Bad Cat"}]}]},
        ]
        for spec in bad:
            with self.subTest(spec=str(spec)[:80]), self.assertRaises(ValueError):
                web_ui.world_validate(spec)

    def test_camera_math(self):
        self.assertAlmostEqual(web_ui.fit_zoom(960, 640, 400, 300), 0.41666, places=4)
        self.assertEqual(web_ui.clamp_focus(10, 10, 2, 960, 640, 400, 300), (100, 75))          # held inside the map
        self.assertEqual(web_ui.clamp_focus(950, 630, 2, 960, 640, 400, 300), (860, 565))
        self.assertEqual(web_ui.clamp_focus(0, 0, 0.25, 960, 640, 400, 300), (480, 320))        # smaller than the view: centered
        self.assertEqual(web_ui.clamp_focus(480, 320, 1, 960, 640, 400, 300), (480, 320))

    def test_html_is_semantic_escaped_and_works_without_js(self):
        hostile = {**WORLD, "title": '<img src=x onerror=1>', "floors": [{**WORLD["floors"][0], "spots": [
            {"id": "a", "x": 8, "y": 8, "label": "<b>x</b>", "category": "info", "body": "<script>1</script>"}]}]}
        html = web_ui.world_html(hostile)
        for raw in ("<b>x</b>", "<script>", "<img src=x"):
            self.assertNotIn(raw, html)
        self.assertEqual(html.count('class="ui-spot"'), 1)
        self.assertIn('href="#demo-spot-a"', html)
        self.assertIn('id="demo-spot-a"', html)
        full = web_ui.world_html(WORLD)
        self.assertEqual(full.count('type="radio" name="demo-floor"'), 2)
        self.assertEqual(full.count('class="ui-spot"'), 6)
        self.assertEqual(full.count('class="ui-shot-mark"'), 4)
        self.assertEqual(full.count('class="ui-actor"'), 5)
        self.assertEqual(full.count('class="ui-sheet-item"'), 11)  # a sheet for every spot and every villager

    def test_css_has_one_rule_per_floor_category_and_shot(self):
        css = web_ui.world_css(WORLD)
        self.assertTrue(css.startswith("@layer components{") and css.endswith("}"))
        for fragment in ('#demo-floor-2f:checked) .ui-floor[data-floor="2f"]{display:block}',
                         '#demo-cat-value-food:checked) .ui-spot:not([data-category="food"]){display:none}',
                         '.ui-shot-mark[data-i="3"][data-lit])'):
            self.assertIn(fragment, css)
        for shot in WORLD["shots"]:
            self.assertGreaterEqual(web_ui.contrast_ratio(web_ui.ink_for(shot["bg"]), shot["bg"]), 4.5)
            self.assertIn(shot["bg"], css)

    def test_single_file_world_page(self):
        html = web_ui.world_document(WORLD, theme="github-like")
        self.assertNotIn('rel="stylesheet"', html)
        self.assertEqual(html.count('<script type="module">'), 1)
        self.assertIn("globalThis.webUiWorld", html)
        self.assertEqual(web_ui.module_asset("world.js")[0].decode(), web_ui.WORLD_JS)

    def test_random_themes_always_read_and_are_reproducible(self):
        seen = set()
        for seed in range(200):
            theme = web_ui.random_theme(seed)
            self.assertEqual(theme, web_ui.random_theme(seed))
            for text, minimum in (("fg", 7), ("muted", 4.5), ("accent", 4.5), ("danger", 4.5)):
                for ground in ("bg", "panel"):
                    ratio = web_ui.contrast_ratio(theme[f"--ui-{text}"], theme[f"--ui-{ground}"])
                    self.assertGreaterEqual(ratio, minimum, f"seed {seed}: {text} on {ground} {ratio:.2f}")
            seen.add(theme["--ui-bg"])
        self.assertGreater(len(seen), 150)

    def test_front_page_is_what_the_generator_writes(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(page, web_ui.example_pages()["index.html"])
        for fragment in (web_ui.world_html(WORLD), web_ui.theme_wall(range(12)), web_ui.world_css(WORLD), web_ui.WORLD_JS):
            self.assertIn(fragment, page)

    def test_villagers_walk_straight_at_constant_speed_pause_at_random_and_loop_seamlessly(self):
        for seed in range(60):
            for width, height, speed in ((960, 640, 48), (640, 640, 32), (320, 480, 64)):
                path = web_ui.villager_path(seed, width, height, speed=speed)
                keys = path["keys"]
                self.assertEqual((keys[0][0], keys[-1][0]), (0.0, 100.0))
                self.assertEqual(keys[0][1:], keys[-1][1:])                       # the loop closes
                self.assertEqual(path, web_ui.villager_path(seed, width, height, speed=speed))
                pauses = moves = 0
                for (p0, x0, y0), (p1, x1, y1) in zip(keys, keys[1:]):
                    self.assertGreaterEqual(p1, p0)
                    self.assertTrue(32 <= x1 <= width - 32 and 32 <= y1 <= height - 32, (seed, x1, y1))
                    seconds, dist = (p1 - p0) / 100 * path["duration"], math.hypot(x1 - x0, y1 - y0)
                    if dist == 0:
                        pauses += 1
                        self.assertTrue(0.9 <= seconds <= 4.1, (seed, seconds))   # a random stop of 1..4 s
                    else:
                        moves += 1
                        self.assertAlmostEqual(dist / seconds, speed, delta=speed * 0.02)   # constant speed
                self.assertEqual((moves, pauses), (5, 4))
        self.assertNotEqual(web_ui.villager_path(1, 960, 640), web_ui.villager_path(2, 960, 640))

    def test_travel_clock_and_board_math(self):
        self.assertEqual(web_ui.travel_seconds(0, 0, 3, 4, 5), 1.0)
        self.assertEqual(web_ui.travel_seconds(10, 10, 10, 10, 96), 0.0)
        self.assertEqual([web_ui.minutes_until(*case) for case in ((600, 630), (600, 600), (1430, 10), (0, 1439))], [30, 0, 20, 1439])
        self.assertEqual([web_ui.board_seconds(n) for n in (1, 64, 160, 400)], [8.0, 8.0, 20.0, 50.0])

    def test_gauge_clock_and_zone_rules(self):
        # 09:00..18:00 in ten cells at 10:00: one hour of nine has passed.
        self.assertEqual(web_ui.gauge_state(600, 540, 1080, 10), (1, 11, "active"))
        self.assertEqual(web_ui.gauge_state(540, 540, 1080, 10), (0, 0, "active"))              # the first minute is empty, not "before"
        self.assertEqual(web_ui.gauge_state(1080, 540, 1080, 10), (10, 100, "after"))           # the end is full
        self.assertEqual(web_ui.gauge_state(180, 540, 1080, 10), (0, 0, "before"))              # 03:00: the start is nearer than the end
        self.assertEqual(web_ui.gauge_state(1260, 540, 1080, 10), (10, 100, "after"))           # 21:00: the end is nearer
        self.assertEqual(web_ui.gauge_state(180, 540, 1260, 10)[2], "before")                   # equidistant: a tie counts as before
        self.assertEqual(web_ui.gauge_state(60, 1320, 120, 8), (6, 75, "active"))               # 22:00..02:00 runs past midnight: 01:00 is 3 h of 4
        for start, end, cells in ((540, 1080, 10), (1320, 120, 8), (0, 1439, 20), (1439, 0, 3)):
            seen = [web_ui.gauge_state(now, start, end, cells) for now in range(1440)]
            for filled, percent, phase in seen:
                self.assertTrue(0 <= filled <= cells and 0 <= percent <= 100 and phase in ("before", "active", "after"))
            active = [s for s in seen if s[2] == "active"]
            self.assertEqual(len(active), (end - start) % 1440)                                  # exactly the window is active
        self.assertEqual(web_ui.gauge_cells(3, 5, ("A", "b")), "AAAbb")
        self.assertEqual(web_ui.gauge_cells(0, 3, web_ui.GAUGE_GLYPHS["hourglass"]), "⏳⏳⏳")
        self.assertEqual([web_ui.clock_label(m) for m in (0, 9, 600, 1439)], ["00:00", "00:09", "10:00", "23:59"])
        self.assertEqual([web_ui.utc_offset_label(m) for m in (0, 540, 330, -300, -210, 765, -720)],
                         ["UTC", "UTC+9", "UTC+5:30", "UTC-5", "UTC-3:30", "UTC+12:45", "UTC-12"])

    def test_gauge_is_validated_normalized_and_escaped(self):
        def board(*items, **flags):
            return {**WORLD, "board": {"title": "T", "items": list(items), **flags}}
        window = {"from": "09:00", "to": "18:00"}
        for bad in (
            {"text": "x", "gauge": {**window, "from": "9:00"}}, {"text": "x", "gauge": {**window, "to": "24:00"}},
            {"text": "x", "gauge": {"from": "09:00", "to": "09:00"}},                              # no window
            {"text": "x", "gauge": {**window, "cells": 2}}, {"text": "x", "gauge": {**window, "cells": 21}},
            {"text": "x", "gauge": {**window, "cells": True}}, {"text": "x", "gauge": {**window, "cells": "10"}},
            {"text": "x", "gauge": {**window, "glyphs": "sand"}},                                  # unknown preset
            {"text": "x", "gauge": {**window, "glyphs": ["A"]}}, {"text": "x", "gauge": {**window, "glyphs": ["A", "B", "C"]}},
            {"text": "x", "gauge": {**window, "glyphs": ["A", " "]}}, {"text": "x", "gauge": {**window, "glyphs": ["A", ""]}},
            {"text": "x", "gauge": {**window, "glyphs": ["A", "\x07"]}}, {"text": "x", "gauge": {**window, "glyphs": ["A", "B" * 9]}},
            {"text": "x", "gauge": {**window, "glyphs": ["A", 5]}}, {"text": "x", "gauge": {**window, "extra": 1}},
            {"text": "x", "gauge": "09:00-18:00"}, {"text": "x", "at": "10:00", "gauge": window},  # at and gauge are exclusive
        ):
            with self.subTest(bad=str(bad)[-70:]), self.assertRaises(ValueError):
                web_ui.world_validate(board(bad))
        with self.assertRaises(ValueError):
            web_ui.world_validate(board({"text": "x"}, offset_label="yes"))
        # Every preset works, defaults are filled in, and a custom pair keeps its own glyphs.
        for name, pair in web_ui.GAUGE_GLYPHS.items():
            got = web_ui.world_validate(board({"text": "x", "gauge": {**window, "glyphs": name}}))["board"]["items"][0]["gauge"]
            self.assertEqual(got["glyphs"], list(pair), name)
        plain = web_ui.world_validate(board({"text": "x", "gauge": window}))
        self.assertEqual(plain["board"]["items"][0]["gauge"], {**window, "cells": 10, "glyphs": ["⌛", "⏳"]})
        self.assertEqual((plain["board"]["offset_label"], plain["board"]["zones"]), (False, []))
        self.assertEqual(web_ui.world_validate(plain), plain)                                      # normalizing twice changes nothing
        custom = web_ui.world_validate(board({"text": "x", "gauge": {**window, "glyphs": ["🔥", "🪵"], "cells": 5}}))
        self.assertEqual(custom["board"]["items"][0]["gauge"]["glyphs"], ["🔥", "🪵"])
        # Markup: the window and glyphs are data attributes (escaped), the cells start empty so the page works before its script runs.
        html = web_ui.world_html(board({"text": "<b>Open</b>", "gauge": {**window, "glyphs": ['"<', "&>"], "cells": 3}}, offset_label=True))
        for raw in ("<b>Open</b>", 'data-done=""<"', 'data-todo="&>"'):
            self.assertNotIn(raw, html)
        self.assertIn('data-done="&quot;&lt;" data-todo="&amp;&gt;"', html)
        self.assertIn('data-from="09:00" data-to="18:00" data-cells="3"', html)
        self.assertIn('<span class="ui-board-cells" aria-hidden="true">&amp;&gt;&amp;&gt;&amp;&gt;</span> <span class="ui-board-pct">0%</span>', html)
        self.assertIn(" data-offset-label>", html)
        self.assertNotIn("data-offset-label", web_ui.world_html(board({"text": "x"})))

    @unittest.skipUnless(_has_tzdata(), "needs the system tz database")
    def test_zone_table_follows_the_tz_database_and_known_transitions(self):
        import datetime as dt
        import zoneinfo
        utc = lambda *a: int(dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp())
        # Golden instants written down by hand (the first second of the new offset), not read back from zoneinfo.
        golden = {"Europe/London": [(utc(2026, 3, 29, 1), 0, 60), (utc(2026, 10, 25, 1), 60, 0)],
                  "America/New_York": [(utc(2026, 3, 8, 7), -300, -240), (utc(2026, 11, 1, 6), -240, -300)],
                  "Australia/Sydney": [(utc(2026, 4, 4, 16), 660, 600), (utc(2026, 10, 3, 16), 600, 660)]}
        for tz, cases in golden.items():
            rows = web_ui.zone_rows(tz)
            for at, before, after in cases:
                with self.subTest(tz=tz, at=at):
                    self.assertEqual((web_ui.zone_offset(rows, at - 1), web_ui.zone_offset(rows, at)), (before, after))
        self.assertEqual(web_ui.zone_rows("Asia/Tokyo"), (utc(2020, 1, 1), 540))               # no changes: the start row only
        self.assertEqual(web_ui.zone_offset(web_ui.zone_rows("Asia/Kathmandu"), utc(2026, 6, 1)), 345)
        # Every row is exact against the database, and so are thousands of random instants (reproducible seed).
        rng = random.Random(20261103)
        lo, hi = utc(2020, 1, 1), utc(2040, 1, 1)
        for tz in ("Europe/London", "America/New_York", "Australia/Sydney", "Asia/Kolkata", "America/Sao_Paulo", "Pacific/Auckland", "Africa/Cairo"):
            rows, zone = web_ui.zone_rows(tz), zoneinfo.ZoneInfo(tz)
            oracle = lambda t: int(dt.datetime.fromtimestamp(t, dt.timezone.utc).astimezone(zone).utcoffset().total_seconds() // 60)
            for t, offset in zip(rows[2::2], rows[3::2]):
                self.assertEqual((oracle(t - 1) == offset, oracle(t) == offset), (False, True), (tz, t))
            for _ in range(1500):
                t = rng.randrange(lo, hi)
                self.assertEqual(web_ui.zone_offset(rows, t), oracle(t), (tz, t))
        london = web_ui.zone_rows("Europe/London")
        self.assertEqual((web_ui.zone_offset(london, 0), web_ui.zone_offset(london, 4_000_000_000)), (0, 0))   # outside the window: nearest end
        for bad in ("Mars/Base", "../etc/passwd", "Asia//Tokyo", "", "Asia/Tokyo ", 5, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                web_ui.zone_rows(bad)

    @unittest.skipUnless(_has_tzdata(), "needs the system tz database")
    def test_board_zones_are_validated_and_rendered_with_their_tables(self):
        zones = [{"id": "tokyo", "label": "Tokyo", "tz": "Asia/Tokyo"}, {"id": "london", "label": "<b>London</b>", "tz": "Europe/London"}]
        def board(*items, zones=zones):
            return {**WORLD, "board": {"title": "T", "items": list(items), "zones": zones}}
        for bad in (board({"text": "x"}, zones=[{**zones[0], "tz": "Mars/Base"}]), board({"text": "x"}, zones=[zones[0], zones[0]]),
                    board({"text": "x"}, zones=[{**zones[0], "id": "Tokyo"}]), board({"text": "x"}, zones=[{**zones[0], "extra": 1}]),
                    board({"text": "x"}, zones=[{**zones[0], "id": f"z{i}"} for i in range(7)]), board({"text": "x"}, zones="Asia/Tokyo"),
                    board({"text": "x", "at": "10:00", "zone": "paris"}),                        # a zone the board does not have
                    board({"text": "x", "zone": "tokyo"}),                                       # a zone needs at or gauge
                    board({"text": "x", "at": "10:00", "zone": 5})):
            with self.subTest(bad=str(bad["board"])[-70:]), self.assertRaises(ValueError):
                web_ui.world_validate(bad)
        spec = board({"text": "Opens", "at": "09:00", "zone": "tokyo"}, {"text": "Open", "gauge": {"from": "09:00", "to": "18:00"}, "zone": "london"},
                     {"text": "Local", "at": "09:00"})
        world = web_ui.world_validate(spec)
        self.assertEqual(web_ui.world_validate(world), world)
        self.assertEqual([i["zone"] for i in world["board"]["items"]], ["tokyo", "london", None])
        html = web_ui.world_html(spec)
        self.assertNotIn("<b>London</b>", html)
        for z in world["board"]["zones"]:
            match = re.search(rf'data-zone-id="{z["id"]}" data-rows="([^"]*)"', html)
            self.assertEqual(json.loads(match.group(1)), list(web_ui.zone_rows(z["tz"])))
        self.assertEqual(html.count('data-at="09:00" data-zone="tokyo"'), 2)                    # the visible line and its twin
        self.assertEqual(html.count('data-cells="10" data-zone="london"'), 2)
        self.assertEqual(html.count('data-at="09:00"></span>'), 2)                              # no zone: the viewer's own clock
        self.assertEqual(html.count('class="ui-board-zones"'), 1)                                # the clocks share one row
        self.assertNotIn("ui-board-zone", web_ui.world_html({**WORLD, "board": {"title": "T", "items": [{"text": "x"}]}}))

    def test_world_script_stores_nothing_and_requests_only_for_the_opt_in_shared_section(self):
        # What a visitor writes stays in the page: no storage, cookies, beacons or sockets, no place names. The one network call is the
        # shared section's refresh button (opt in with shared_issue): an anonymous GET without credentials, cache or referrer.
        for word in ("localStorage", "sessionStorage", "indexedDB", "cookie", "XMLHttpRequest", "sendBeacon", "WebSocket",
                     "caches", "Intl", "timeZone", "navigator", "geolocation", "pushState", "postMessage", "Worker"):
            self.assertTrue(word not in web_ui.WORLD_JS, word)                                # (replaceState only edits the #spot fragment)
        self.assertEqual(web_ui.WORLD_JS.count("fetch("), 1)
        for needle in ('method:"GET"', 'credentials:"omit"', 'cache:"no-store"', 'referrerPolicy:"no-referrer"'):
            self.assertIn(needle, web_ui.WORLD_SHARED_JS)
        self.assertIn("fetch(", web_ui.WORLD_SHARED_JS)
        plain = {**WORLD, "board": {**WORLD["board"], "shared_issue": None}}
        for needle in ("api.github.com", "data-shared-refresh", "ui-board-shared"):
            self.assertNotIn(needle, web_ui.world_html(plain))
            self.assertIn(needle, web_ui.world_html(WORLD))

    def test_actors_player_and_board_are_validated_and_escaped(self):
        floor = WORLD["floors"][0]
        actor = {"id": "x", "emoji": "🐈", "label": "L"}
        bad = [
            {**WORLD, "floors": [{**floor, "actors": [{**actor, "emoji": "A"}]}]},                     # plain text is not a character
            {**WORLD, "floors": [{**floor, "actors": [{**actor, "emoji": "<b>"}]}]},
            {**WORLD, "floors": [{**floor, "actors": [{**actor, "speed": 1}]}]},
            {**WORLD, "floors": [{**floor, "actors": [{**actor, "id": "gate"}]}]},                     # ids are shared with spots
            {**WORLD, "floors": [{**floor, "actors": [{**actor, "id": f"a{i}"} for i in range(17)]}]},
            {**WORLD, "floors": [{**floor, "player": {"emoji": "🧙", "x": 9999, "y": 0}}]},
            {**WORLD, "floors": [{**floor, "player": {"emoji": "x", "x": 0, "y": 0}}]},
            {**WORLD, "board": {"title": "T", "items": []}},
            {**WORLD, "board": {"title": "T", "items": [{"text": "x", "at": "25:00"}]}},
            {**WORLD, "board": {"title": "T", "items": [{"text": "x", "at": "9:00"}]}},
        ]
        for spec in bad:
            with self.subTest(spec=str(spec)[-80:]), self.assertRaises(ValueError):
                web_ui.world_validate(spec)
        hostile = {**WORLD, "board": {"title": "<i>", "items": [{"text": "<script>1</script>", "at": "10:30"}]},
                   "floors": [{**floor, "actors": [{**actor, "label": "<b>x</b>", "body": "<img src=x>"}]}]}
        html = web_ui.world_html(hostile)
        for raw in ("<script>", "<b>x</b>", "<img src=x>", "<i>"):
            self.assertNotIn(raw, html)
        css = web_ui.world_css(hostile)
        self.assertIn("@keyframes ui-walk-demo-x{0.0%{transform:translate(", css)
        self.assertIn("#demo-actor-x{animation:ui-walk-demo-x ", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_visitor_lines_are_cleaned_to_plain_text_and_the_form_is_opt_in(self):
        cases = {"  hello   world  ": "hello world", "a\tb\nc": "a b c", "\x00\x07x": "x", "": None, "   ": None, 5: None,
                 "x" * 100: "x" * 60, "\U0001f600 ok": "\U0001f600 ok", "\U0001f9d1\u200d\U0001f33e hi": "\U0001f9d1\u200d\U0001f33e hi",
                 "a\u3000b\u00a0c": "a b c", "z\u200bz": "zz", "p\x85q": "pq", "<b>x</b>": "<b>x</b>"}
        for raw, expected in cases.items():
            self.assertEqual(web_ui.clean_message(raw), expected, repr(raw))
        self.assertEqual(web_ui.clean_message("abcdef", limit=3), "abc")
        self.assertIn('class="ui-board-post"', web_ui.world_html(WORLD))
        quiet = {**WORLD, "board": {**WORLD["board"], "post": False}}
        self.assertNotIn("ui-board-post", web_ui.world_html(quiet))
        with self.assertRaises(ValueError):
            web_ui.world_validate({**WORLD, "board": {**WORLD["board"], "post": "yes"}})

    def test_theme_wall_and_cli(self):
        wall = web_ui.theme_wall(range(12))
        self.assertEqual(wall.count('class="ui-wall-cell"'), 12)
        self.assertIn("--ui-radius:", wall)
        run = lambda *args: subprocess.run([sys.executable, "-S", "web_ui.py", *args], cwd=ROOT, capture_output=True,
                                           text=True, encoding="utf-8", timeout=60)
        with tempfile.TemporaryDirectory() as out:
            spec = Path(out) / "world.json"
            spec.write_text(run("--example", "world").stdout, encoding="utf-8")
            self.assertEqual(json.loads(spec.read_text(encoding="utf-8")), WORLD)
            shown = run("--world", str(spec), "--theme", "green")
        self.assertEqual((shown.returncode, shown.stdout), (0, web_ui.world_document(WORLD, theme="green")))
        self.assertEqual(run("--example", "nope").returncode, 2)
        self.assertEqual(run("--theme-wall", "3").stdout, web_ui.theme_wall_document(3))
        self.assertEqual(run("--world", "no-such.json").returncode, 2)

    def test_site_writes_pages_browser_modules_and_example_data_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as out:
            done = subprocess.run([sys.executable, "-S", "web_ui.py", "--site", out], cwd=ROOT, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            pages = web_ui.example_pages()
            modules = {f"js/{name}": source for name, source in web_ui.js_modules().items()}
            data = {f"examples/{name}.json": json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
                    for name, spec in web_ui.EXAMPLES.items()}
            self.assertEqual(sorted(done.stdout.split()), sorted([*pages, *modules, *data, "docs/brand/icon.png", "docs/brand/favicon.png"]))
            for name, text in {**pages, **modules, **data}.items():
                self.assertEqual((Path(out) / name).read_text(encoding="utf-8"), text)


class StubTests(unittest.TestCase):
    """MCP/API stubs and mocks are one function call; the mock is declarative and evaluated the same in Python and the page."""

    def test_stub_spec_is_validated(self):
        mcp = web_ui.EXAMPLE_STUBS["mcp"]
        self.assertEqual(web_ui.stub_validate(web_ui.stub_validate(mcp)), web_ui.stub_validate(mcp))
        for bad in ({**mcp, "schema": "x"}, {**mcp, "extra": 1}, {**mcp, "id": "1a"}, {**mcp, "tags": ["t"] * 7},
                    {**mcp, "field": {"placeholder": "no label"}}, {**mcp, "field": {"label": "x", "extra": 1}},
                    {**mcp, "heading": ""}, {**mcp, "mock": {"k": "x" * 4001}}):
            with self.assertRaises(ValueError):
                web_ui.stub_validate(bad)

    def test_mock_template_substitutes_the_query_everywhere(self):
        template = {"path": "/api/$input", "list": ["$input", 1, None, True], "nested": {"q": "$input$input"}}
        self.assertEqual(web_ui.stub_response(template, "a$&b"),
                         {"path": "/api/a$&b", "list": ["a$&b", 1, None, True], "nested": {"q": "a$&ba$&b"}})
        self.assertEqual(template["path"], "/api/$input")

    def test_html_is_escaped_ids_are_prefixed_and_the_mock_cannot_close_the_script(self):
        spec = {**web_ui.EXAMPLE_STUBS["api"], "id": "x", "heading": "<b>h</b>", "evidence": "<i>e</i>",
                "mock": {"note": "</script><script>1</script>"}}
        html = web_ui.stub_html(spec, heading_level=2)
        for raw in ("<b>h</b>", "<i>e</i>", "</script><script>"):
            self.assertNotIn(raw, html)
        for ident in ("x-query", "x-run", "x-output", "x-form", "x-mock"):
            self.assertIn(f'id="{ident}"', html)
        self.assertIn('<h2 class="ui-title">', html)
        self.assertIn('value="/api/example"', html)

    def test_stub_document_is_a_single_file_page(self):
        page = web_ui.stub_document(web_ui.EXAMPLE_STUBS["mcp"], theme="github-like")
        self.assertNotIn('rel="stylesheet"', page)
        self.assertEqual(page.count('<script type="module">'), 1)
        self.assertIn('bindStub({input:"#mcp-query"', page)


def screens_like(count: int = 198) -> list[dict]:
    """A catalogue shaped like flutter_navigation_basic's screens.json (5 categories of 40, 40, 40, 39, 39), after mapping its fields."""
    groups = ["navigation", "api", "ui", "data", "advanced"]
    per = [40, 40, 40, 39, 39]
    out, n = [], 0
    for group, size in zip(groups, per):
        for _ in range(size):
            n += 1
            out.append({"id": f"Screen{n}", "label": f"Pattern{n} <b>x</b>", "emoji": "🌍" if n % 2 else "🧭", "group": group,
                        "category": ["integration", "display", "state"][n % 3], "body": f"Screen {n}: <i>about</i> {group}"})
    return out[:count]


class CatalogueTests(unittest.TestCase):
    """A flat catalogue becomes a map: a floor per group, spots on a grid of multiples of 8, all validated and escaped."""

    def test_a_198_screen_catalogue_fits_five_floors(self):
        world = web_ui.catalogue_world(screens_like(), title="Screens")
        self.assertEqual(web_ui.world_validate(world), world)
        self.assertEqual([len(f["spots"]) for f in world["floors"]], [40, 40, 40, 39, 39])
        self.assertEqual([f["label"] for f in world["floors"]], ["navigation", "api", "ui", "data", "advanced"])
        ids = [spot["id"] for f in world["floors"] for spot in f["spots"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "screen1")
        for floor in world["floors"]:
            points = [(s["x"], s["y"]) for s in floor["spots"]]
            self.assertEqual(len(points), len(set(points)))                                     # no two spots on the same cell
            self.assertTrue(all(0 <= x <= floor["width"] and 0 <= y <= floor["height"] for x, y in points))
            self.assertEqual((floor["width"] % 8, floor["height"] % 8), (0, 0))                 # the 8 px grid, by default
            # Neighbours in a row are a cell apart, wide enough for a pill, and rows are a cell apart.
            xs = sorted({x for x, _ in points})
            self.assertTrue(all(b - a >= 160 for a, b in zip(xs, xs[1:])))
        self.assertEqual(world["floors"][0]["spots"][0]["label"], "🌍 Pattern1 <b>x</b>")        # stored as text; escaped when written
        html = web_ui.world_html(world)
        self.assertNotIn("<b>x</b>", html)
        self.assertNotIn("<i>about</i>", html)
        self.assertEqual(html.count('class="ui-spot"'), 198)

    def test_groups_of_more_than_64_continue_and_limits_are_kept(self):
        many = [{"id": f"a{i}", "label": f"A{i}", "group": "all"} for i in range(130)]
        world = web_ui.catalogue_world(many)
        self.assertEqual([(f["label"], len(f["spots"])) for f in world["floors"]], [("all", 64), ("all 2", 64), ("all 3", 2)])
        for bad in ([], "x", [{"id": "a", "label": "A"}], [{"id": "a", "label": "", "group": "g"}], [{"id": "a", "label": "A", "group": "g", "x": 1}],
                    [{"id": f"a{i}", "label": "A", "group": f"g{i}"} for i in range(9)], [5], [{"id": "a", "label": "A", "group": ""}]):
            with self.subTest(bad=str(bad)[:50]), self.assertRaises(ValueError):
                web_ui.catalogue_world(bad)
        with self.assertRaises(ValueError):
            web_ui.catalogue_world(many, columns=0)
        same = web_ui.catalogue_world([{"id": "Screen 1", "label": "A", "group": "g"}, {"id": "screen-1", "label": "B", "group": "g"},
                                       {"id": "!!", "label": "C", "group": "g"}])
        self.assertEqual([s["id"] for s in same["floors"][0]["spots"]], ["screen-1", "screen-1-2", "x"])   # ids stay unique
        long = web_ui.catalogue_world([{"id": "a", "label": "L" * 80, "emoji": "🌍", "group": "g"}])
        self.assertEqual(len(long["floors"][0]["spots"][0]["label"]), 40)


SHOWCASE = web_ui.example_data("showcase")


class ShowcaseTests(unittest.TestCase):
    """The app shell: data in, page out; sections switch with radios, so the rules are CSS the generator writes."""

    def test_example_is_valid_and_validation_is_idempotent(self):
        show = web_ui.showcase_validate(SHOWCASE)
        self.assertEqual(web_ui.showcase_validate(show), show)
        self.assertEqual([s["id"] for s in show["sections"]], ["overview", "components", "data", "media"])

    def test_bad_specs_are_refused(self):
        section = SHOWCASE["sections"][0]
        two = SHOWCASE["sections"][:2]
        for bad in ({**SHOWCASE, "schema": "x"}, {**SHOWCASE, "extra": 1}, {**SHOWCASE, "id": "Bad Id"}, {**SHOWCASE, "sections": two[:1]},
                    {**SHOWCASE, "sections": [{**section, "id": f"s{i}"} for i in range(7)]}, {**SHOWCASE, "sections": [section, section]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "icon": "nope"}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "label": ""}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "extra": 1}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "cards": [{"icon": "nope", "title": "t", "body": "b"}]}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "table": {"columns": ["a"], "rows": [["1", "2"]]}}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "table": {"columns": [], "rows": []}}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "tags": ["x"] * 9}]},
                    {**SHOWCASE, "sections": [section, {**section, "id": "b", "controls": "yes"}]},
                    {**SHOWCASE, "favorite": "yes"}, {**SHOWCASE, "themes": 1}, "not a dict", None):
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(ValueError):
                web_ui.showcase_validate(bad)

    def test_everything_is_escaped_and_every_icon_and_radio_resolves(self):
        hostile = {**SHOWCASE, "title": "<i>t</i>", "emoji": "<b>", "sections": [
            {"id": "a", "label": "<b>A</b>", "icon": "star", "heading": "<script>1</script>", "lead": "<img src=x>", "tags": ["<u>"],
             "cards": [{"icon": "info", "title": "<s>", "body": "<em>b</em>"}], "table": {"columns": ["<x-col>"], "rows": [["<x-cell>"]]}},
            {"id": "b", "label": "B", "icon": "data", "heading": "H"}]}
        html = web_ui.showcase_html(hostile)
        for raw in ("<script>", "<i>t</i>", "<b>A</b>", "<img src=x>", "<u>", "<s>", "<em>", "<x-cell>", "<x-col>", "<b>"):
            self.assertNotIn(raw, html)
        for use in re.findall(r'<use href="#([^"]+)"', html):
            self.assertIn(f'<symbol id="{use}"', html)
        for target in re.findall(r'<label class="[^"]+" for="([^"]+)"', html):
            self.assertIn(f'id="{target}"', html)
        self.assertEqual(html.count('type="radio"'), 2)
        self.assertEqual(html.count("checked"), 1)                                             # one section is open to begin with
        self.assertEqual(html.count('class="ui-rail-item"'), html.count('class="ui-bottom-item"'))   # the rail and the bottom bar list the same sections

    def test_rules_name_every_section_and_the_page_is_one_file(self):
        css = web_ui.showcase_css(SHOWCASE)
        for sec in SHOWCASE["sections"]:
            self.assertIn(f'#showcase:has(#showcase-sec-{sec["id"]}:checked) .ui-shell-section:not([data-section="{sec["id"]}"]){{display:none}}', css)
            self.assertIn(f'label[for="showcase-sec-{sec["id"]}"]', css)
        page = web_ui.showcase_document(SHOWCASE)
        self.assertEqual(page.count("<script"), 1)                                             # one inline module: ui.js and the two calls
        self.assertIn("bindTheme();bindToggles();", page)
        self.assertNotIn("<link", page)
        for flags, expect in (({"favorite": False, "themes": False}, False), ({}, True)):
            html = web_ui.showcase_html({**SHOWCASE, **flags})
            self.assertEqual(("data-ui-toggle" in html, "data-ui-theme-switch" in html), (expect, expect))


CURL_CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "curl_request_cases.json").read_text(encoding="utf-8"))["cases"]


def curl_fuzz_inputs(count: int = 1500, seed: int = 20261103) -> list[str]:
    """Seeded curl-ish inputs: real options, quoting, continuations, odd whitespace, full-width forms, bad escapes and shell characters,
    so that Python and the page can be compared on exactly the same text."""
    rng = random.Random(seed)
    words = ["curl", "curl", "CURL", "-X", "POST", "get", "put", "BOGUS", "-H", "--header", "'Content-Type: application/json'", '"X-Api-Key: abc"',
             "'Accept: */*'", "'Bad Header'", '"X-Note: a\\"b"', "-d", "--data-raw", "--data-binary", "--data-urlencode", "'{\"a\":1}'", "'[1,2]'",
             "a=1&b=2", "a=%E3%81%82&b=%2B", "a+b=c+d", "%ZZ", "a=%FF", "a=%C0%80", "@file.json", "name@file", "x=y=z", "&&", "-u", "me:pw",
             "--user=a:b", "--url=http://u.test/", "https://example.com/a?b=c", "http://x", "-G", "--get", "-I", "-L", "-s", "-k", "--insecure",
             "-A", "agent/1", "-e", "https://ref/", "--proxy=x", "-Xpost", "--request=PUT", "-", "--", "\\\n", "|", "$HOME", "`x`", "'unbalanced",
             '"unbalanced', "\uff35\uff32\uff2c", "\u3000", "\u2212X", "\u0085", "\x1f", "\ufeff", "\x0b", "\U0001f600", "\\", "''", '""',
             "'a'\"b\"c", "\\x", "\"\\$\"", "Authorization: Bearer ***", "-H", "'X-Token: ***'", "-H", "'Cookie: s=1'", "-H", "'My-Key: v'"]
    separators = [" ", " ", " ", "\t", "\n", "  ", " \\\n ", " \\\r\n "] * 6 + ["\u00a0", "\u2028"]   # now and then a space the lexer does not split on
    headers = ["'Content-Type: application/json'", "'Content-Type: application/x-www-form-urlencoded'", '"X-Api-Key: abc"', "'Accept: */*'", "'Cookie: s=1'"]
    bodies = ["'{\"a\":1}'", "'[1,2]'", "a=1&b=2", "a=%E3%81%82&b=%2B", "a+b=c+d", "'plain text'", "'x=y=z'"]
    pieces = lambda: rng.choice([["-X", rng.choice(["POST", "put", "DELETE", "bogus"])], ["-H", rng.choice(headers)], ["-d", rng.choice(bodies)],
                                 ["--data-urlencode", rng.choice(["'q=a b'", "n=é", "x"])], ["-u", "me:pw"], ["-A", "agent/1"], ["-s"], ["-L"], ["-G"], ["-I"]])
    out = []
    for _ in range(count):
        if rng.random() < 0.6:                                  # mostly valid commands, some then spoiled by one odd word
            groups = [pieces() for _ in range(rng.randint(0, 4))]
            groups.insert(rng.randint(0, len(groups)), [rng.choice(["https://example.com/a?b=c", "http://x"])])
            if rng.random() < 0.25:
                groups.insert(rng.randint(0, len(groups)), [rng.choice(words)])
            parts = ["curl"] + [word for group in groups for word in group]
        else:
            parts = ["curl"] if rng.random() < 0.8 else []
            parts += [rng.choice(words) for _ in range(rng.randint(0, 11))]
        text = "".join(part + rng.choice(separators) for part in parts)
        if rng.random() < 0.15:
            text = text[: rng.randint(0, len(text))]
        out.append(text if rng.random() < 0.9 else rng.choice([" ", "\t"]) + text)
    return out


class CurlTests(unittest.TestCase):
    """The curl import is read by Python and by the page the same way; the golden file is flutter_navigation_basic's own (47 cases)."""

    def test_golden_cases_from_the_flutter_editor(self):
        self.assertEqual(len(CURL_CASES), 47)
        for case in CURL_CASES:
            with self.subTest(case["id"]):
                self.assertEqual(web_ui.parse_curl(case["input"]), case["expected"])

    def test_limits_and_errors_never_echo_the_input(self):
        secret = "SECRETXYZ-0123456789"
        fail = lambda text: web_ui.parse_curl(text)["errors"]
        edge = "curl http://x/" + "a" * (web_ui.CURL_MAX_BYTES - len("curl http://x/"))
        self.assertTrue(web_ui.parse_curl(edge)["ok"])                                       # exactly 64 KiB is fine,
        self.assertEqual(fail(edge + "a"), ["httpDraft.curl.error.inputTooLarge"])             # one byte more is not
        self.assertEqual(fail("curl http://x/" + "\u3042" * web_ui.CURL_MAX_BYTES), ["httpDraft.curl.error.inputTooLarge"])   # bytes, not characters
        many = lambda n: "curl " + " ".join(f"-s" for _ in range(n - 1))
        self.assertTrue(web_ui.parse_curl(many(web_ui.CURL_MAX_TOKENS) + " http://x")["errors"] == ["httpDraft.curl.error.tooManyTokens"])
        self.assertEqual(fail("curl http://x/\x00"), ["httpDraft.curl.error.nul"])
        self.assertEqual(fail("curl http://x/\ud800"), ["httpDraft.curl.error.encoding"])
        self.assertEqual(fail(5), ["httpDraft.curl.error.inputType"])
        for text in (f"curl http://x/ | sh {secret}", f"curl -H 'Authorization: Bearer {secret}' $(x)", f"curl -d '{secret}", f"wget {secret}",
                     f"curl -X {secret} http://x", f"curl --{secret} http://x", f"curl http://x/ extra-{secret}", f"curl -d @{secret} http://x"):
            with self.subTest(text[:30]):
                self.assertNotIn(secret, json.dumps(web_ui.parse_curl(text)))

    def test_masking_hides_marked_credentials_and_nothing_else(self):
        result = web_ui.parse_curl("curl -u me:pw -H 'X-Api-Key: k1' -H 'Cookie: s=2' -H 'Accept: json' -H 'Note: ***' -d 'token=t&a=1' http://x/")
        shown = web_ui.mask_curl(result)
        self.assertEqual({h["name"]: h["value"] for h in shown["draft"]["headers"]},
                         {"Authorization": "***", "X-Api-Key": "***", "Cookie": "***", "Accept": "json", "Note": "***"})
        self.assertEqual({f["name"]: (f["value"], f["sensitive"]) for f in shown["draft"]["formFields"]}, {"token": ("t", False), "a": ("1", False)})
        self.assertEqual(result["draft"]["headers"][0]["value"][:6], "Basic ")                      # the original is untouched
        self.assertNotIn("bWU6cHc=", json.dumps(shown))
        self.assertEqual(web_ui.mask_curl(web_ui.parse_curl("nope"))["draft"], None)
        for name, sensitive in {"Authorization": True, "x-API-KEY": True, "client_secret": True, "My-Key": True, "X_Token": True,
                                "Accept": False, "Keyboard": False, "Content-Type": False, "\uff21uthorization": True}.items():
            self.assertEqual(web_ui._curl_sensitive(name), sensitive, name)

    def test_the_fuzz_corpus_is_varied_and_reproducible(self):
        inputs = curl_fuzz_inputs()
        self.assertEqual(inputs, curl_fuzz_inputs())
        results = [web_ui.parse_curl(text) for text in inputs]
        self.assertGreater(sum(r["ok"] for r in results), 400)                                   # plenty of successful parses ...
        self.assertGreater(len({e for r in results for e in r["errors"]}), 8)                    # ... and many different failures
        self.assertGreater(len({r["draft"]["bodyMode"] for r in results if r["ok"]}), 3)


class RepairRegressionTests(unittest.TestCase):
    def test_all_category_has_unique_ids(self):
        import copy
        from html.parser import HTMLParser
        spec = copy.deepcopy(WORLD)
        spec['floors'][0]['spots'][0]['category'] = 'all'
        class Ids(HTMLParser):
            def __init__(self):
                super().__init__(); self.ids = []
            def handle_starttag(self, tag, attrs):
                self.ids.extend(v for k, v in attrs if k == 'id')
        parser = Ids(); parser.feed(web_ui.world_html(spec))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertIn('demo-cat-value-all', parser.ids)
        self.assertIn('#demo-cat-value-all:checked', web_ui.world_css(spec))

    def test_bundle_asset_base_keeps_scripts_not_styles(self):
        result = subprocess.run([sys.executable, '-S', 'web_ui.py', '--css-bundle', '--asset-base', '.', '--with-scripts'],
                                cwd=ROOT, input='', text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('rel="stylesheet"', result.stdout)
        self.assertIn('src="./js/ui.js"', result.stdout)

    def test_theme_wall_zero_does_not_read_stdin(self):
        from unittest.mock import patch
        import io
        with patch('sys.stdin.read', side_effect=AssertionError('unexpected stdin read')), patch('sys.stdout', new=io.StringIO()) as out:
            self.assertEqual(web_ui.main(['--theme-wall', '0']), 0)
            self.assertIn('ui-wall', out.getvalue())
        with self.assertRaises(ValueError):
            web_ui.theme_wall_document(-1)
        with patch("sys.stdin.read", side_effect=AssertionError("unexpected stdin read")), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                web_ui.main(["--theme-wall", "-1"])
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
