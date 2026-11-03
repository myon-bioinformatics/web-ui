import base64
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
import unittest
from pathlib import Path
from unittest import mock

import json
import math

import hashlib
import xml.etree.ElementTree as ET
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

    def test_gauge_unicode_visibility_and_scroll_budget(self):
        for glyph in ("\u200d", "\ufe0f", "\u0301", "\u200d\ufe0f", "\u3164", "\uffa0"):
            with self.subTest(glyph=repr(glyph)), self.assertRaises(ValueError):
                web_ui._gauge_glyph(glyph)
        for glyph in ("👩\u200d💻", "🇯🇵", "1️⃣", "ABCDEFGH"):
            self.assertEqual(web_ui._gauge_glyph(glyph), glyph)
        with self.assertRaisesRegex(ValueError, "requires from and to; cells and glyphs are optional"):
            web_ui._world_gauge({"extra": 1})
        gauge = web_ui._world_gauge({"from": "09:00", "to": "18:00", "cells": 3,
                                     "glyphs": ["ABCDEFGH", "👩\u200d💻"]})
        html = web_ui._board_html({"title": "test", "items": [{"text": "x", "at": None, "zone": None, "gauge": gauge}],
                                   "post": False, "offset_label": False, "offset_minutes": None, "zones": []})
        self.assertIn('data-chars="31"', html)  # text + space + longest cells + " 100%"

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


AREA_CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "coordinate_area_cases.json").read_text(encoding="utf-8"))["cases"]
TOKYO = (35.681236, 139.767125)


def coordinate_fuzz_urls(count: int = 800, seed: int = 20261103) -> list[str]:
    """Seeded Maps-ish text: the real URL shapes with random points, percent-encoding (once, twice, bad), full-width digits, odd whitespace and noise."""
    rng = random.Random(seed)
    point = lambda: (f"{rng.uniform(-95, 95):.{rng.randint(0, 7)}f}", f"{rng.uniform(-185, 185):.{rng.randint(0, 7)}f}")
    shapes = ["https://www.google.com/maps/search/?api=1&query={a},{b}", "https://www.google.com/maps/@{a},{b},16z", "https://www.google.com/maps/@{a},{b}",
              "https://www.google.com/maps/place/X/@{c},{d},17z/data=!3d{a}!4d{b}", "https://maps.apple.com/?ll={a},{b}&q=Coordinates", "https://maps.apple.com/?q={a}, {b}",
              "https://example.com/?q={a}%2C{b}", "https://x/#ll={a} , {b}", "no coordinates here", "https://maps.apple.com/?q=Tokyo", "@{a},{b}z", "?LL={a},{b}", "?QUERY={a},{b}"]
    out = []
    for _ in range(count):
        a, b = point()
        c, d = point()
        text = rng.choice(shapes).format(a=a, b=b, c=c, d=d)
        roll = rng.random()
        if roll < 0.2:
            text = text.replace(",", "%2C")
        elif roll < 0.3:
            text = text.replace("%", "%25").replace(",", "%252C")
        elif roll < 0.35:
            text = text.replace(",", "%ZZ", 1)
        elif roll < 0.4:
            text = text.replace(",", "%E3%81%82%FF", 1)
        elif roll < 0.5:
            text = text.translate({ord(ch): ord(ch) + 0xFEE0 for ch in "0123456789,.-"})
        elif roll < 0.55:
            text = "  \n" + text + "\u3000 "
        elif roll < 0.6:
            text = text.replace("+", "%2B").replace("/", "%2F")
        elif roll < 0.65:
            text = text.replace(" ", "+")
        out.append(text)
    return out


class CoordinatesTests(unittest.TestCase):
    """The coordinate tool's rules, with flutter_navigation_basic's Dart tests and golden vectors as the oracle."""

    def test_the_dart_tests_for_points_dms_and_urls(self):
        w = web_ui
        lat, lon = w.parse_coordinate("35.681236", "139.767125")
        self.assertEqual((w.coordinate_text(lat, lon), w.dms_text(lat, lon)), ("35.681236, 139.767125", "35° 40′ 52.45″ N, 139° 46′ 01.65″ E"))
        self.assertIn("S", w.dms_text(*w.parse_coordinate("-33.8688", "-70.6693")))
        self.assertIn("W", w.dms_text(*w.parse_coordinate("-33.8688", "-70.6693")))
        w.parse_coordinate("90", "180"); w.parse_coordinate("-90", "-180")
        self.assertEqual(w.to_dms(179.999999999996, is_latitude=False), "180° 00′ 00.00″ E")                  # the rounding carry
        for bad in (("90.1", "0"), ("0", "180.1"), ("north", "east"), ("NaN", "0"), ("0", "Infinity"), ("", "0"), ("1e999", "0"), ("0x10", "0"), ("1_0", "0"), ("٣", "0")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.parse_coordinate(*bad)
        self.assertEqual(w.parse_coordinate("３５．５", "－１３９"), (35.5, -139.0))                           # full-width digits, point and minus
        self.assertEqual(w.parse_coordinate(" +1e1 ", ".5"), (10.0, 0.5))
        urls = {"https://www.google.com/maps/search/?api=1&query=35.681236,139.767125": TOKYO,
                "https://www.google.com/maps/@35.681236,139.767125,16z": TOKYO,
                "https://maps.apple.com/?ll=35.681236,139.767125&q=Coordinates": TOKYO,
                "https://www.google.com/maps/place/Tokyo+Station/@35.680000,139.760000,17z/data=!3d35.681236!4d139.767125": TOKYO,   # the pin, not the viewport
                "https://www.google.com/maps/place/Example/@-33.870000,-70.670000,15z/data=!3d-33.868800!4d-70.669300": (-33.8688, -70.6693),
                "https://www.google.com/maps/search/?api=1&query=35.681236%2C139.767125": TOKYO,
                "https://www.google.com/maps/search/?api=1&query=35.681236%ZZ139.767125": None,                                # a bad escape never throws
                "https://maps.apple.com/?q=Tokyo": None, "not a maps url": None, "": None, "   ": None,
                "https://x/?q=91,0": None, "https://x/?q=91,0&ll=1,2": (1.0, 2.0)}                                           # an out-of-range pair falls through to the next rule
        for text, expected in urls.items():
            with self.subTest(text=text[:60]):
                self.assertEqual(w.try_parse_maps_url(text), expected)
        built = w.maps_urls(*TOKYO)                                                                                          # what the tool builds, it can read back
        area = w.tolerance_area(*TOKYO, 100)
        texts = w.area_texts(area)
        for url in (built["google"], built["apple"], texts["google_area_url"], texts["apple_area_url"]):
            self.assertEqual(w.try_parse_maps_url(url), TOKYO, url)
        self.assertIn("query=35.681236%2C139.767125", built["google"])
        self.assertIn("ll=35.681236%2C139.767125", built["apple"])
        self.assertIn("center=35.681236%2C139.767125&zoom=16", built["osm_preview"])

    def test_tolerance_areas_zoom_and_tiles_as_the_dart_tests_say(self):
        w = web_ui
        area = w.tolerance_area(*TOKYO, 100)
        self.assertTrue(area["south"] < TOKYO[0] < area["north"] and area["west"] < TOKYO[1] < area["east"] and not area["wraps"])
        self.assertAlmostEqual(area["north"] - TOKYO[0], 0.000899, delta=0.00001)
        self.assertGreater(area["east"] - TOKYO[1], area["north"] - TOKYO[0])
        t = w.area_texts(area)
        self.assertIn("radius_m: 100", t["center_radius"])
        self.assertIn('"wraps_antimeridian": false', t["json"])
        self.assertEqual(t["google_area_url"], "https://www.google.com/maps/@35.681236,139.767125,16z")
        self.assertTrue(t["apple_area_url"].startswith("https://maps.apple.com/?ll=35.681236%2C139.767125&q=Tolerance+area&spn="))
        self.assertEqual(w.area_texts(w.tolerance_area(*TOKYO, 350))["google_circle"], "new google.maps.Circle({\n  center: {\n    lat: 35.681236,\n    lng: 139.767125\n  },\n  radius: 350\n});")
        self.assertEqual(w.area_texts(w.tolerance_area(*TOKYO, 350))["mapkit_circle"], "MKCircle(\n  center: CLLocationCoordinate2D(\n    latitude: 35.681236,\n    longitude: 139.767125\n  ),\n  radius: 350\n)")
        self.assertIn("south: " + w.fixed(area["south"], 6), t["google_rectangle"])
        self.assertIn("latitudeDelta: " + w.fixed(abs(area["north"] - area["south"]), 6), t["mapkit_region"])
        self.assertEqual(w.area_texts(w.tolerance_area(*TOKYO, 12.5))["center_radius"].splitlines()[1], "radius_m: 12.50")
        near_date_line = w.tolerance_area(0, 179.999, 1000)
        self.assertTrue(near_date_line["wraps"] and not near_date_line["apple_span"] and near_date_line["west"] < 180 and near_date_line["east"] < 0)
        self.assertNotIn("spn=", w.area_texts(near_date_line)["apple_area_url"])
        pole = w.tolerance_area(89.9999, 20, 1000)
        self.assertEqual((pole["north"], pole["west"], pole["east"], pole["wraps"], pole["full_longitude"], pole["apple_span"], pole["lon_span"]), (90, -180, 180, False, True, False, 360))
        self.assertEqual((w.zoom_for_radius(1000, 89.9999), w.zoom_for_radius(100, 85), w.zoom_for_radius(100, 80)), (3, 13, 14))
        self.assertGreater(w.zoom_for_radius(100, 0), w.zoom_for_radius(100, 80))
        self.assertTrue(w.area_texts(w.tolerance_area(80, 0, 100))["google_area_url"].endswith(",14z"))
        for case in AREA_CASES:                                                                                               # the shared golden vectors
            with self.subTest(case["coordinateAreaCaseId"]):
                a = w.tolerance_area(case["latitude"], case["longitude"], case["radius_m"])
                self.assertEqual((w.zoom_for_radius(case["radius_m"], case["latitude"]), a["wraps"], a["full_longitude"], a["apple_span"]),
                                 (case["expected_zoom"], case["expect_antimeridian"], case["expect_full_longitude"], case["expect_apple_spn"]))
                self.assertEqual("spn=" in w.area_texts(a)["apple_area_url"], case["expect_apple_spn"])
        for bad in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                w.tolerance_area(*TOKYO, bad)
        self.assertEqual(w.zoom_for_radius(0), 16)
        tile = w.xyz_tile(*TOKYO, 16)
        self.assertEqual((tile["zoom"], tile["x"], tile["y"], tile["path"]), (16, 58211, 25806, "16/58211/25806"))
        north = w.xyz_tile(90, 0, 2)
        self.assertTrue(0 <= north["x"] <= 3 and north["y"] == 0)
        for zoom in (-1, 23, 1.5, True):
            with self.subTest(zoom=zoom), self.assertRaises(ValueError):
                w.xyz_tile(*TOKYO, zoom)
        self.assertEqual((w.xyz_tile(0, 0, 0)["path"], w.xyz_tile(-90, 180, 3)["path"]), ("0/0/0", "3/7/7"))                # both edges stay inside the grid

    def test_fixed_rounds_like_javascript_and_dart(self):
        w = web_ui
        self.assertEqual([w.fixed(v, n) for v, n in ((0.0078125, 6), (2.5, 0), (0.125, 2), (-0.125, 2), (1.005, 2), (-1e-9, 6), (-0.0, 2), (35.681236, 6), (0.5, 0), (179.999999999996, 2))],
                         ["0.007813", "3", "0.13", "-0.13", "1.00", "-0.000000", "0.00", "35.681236", "1", "180.00"])      # ties go away from zero; 1.005 is really 1.00499999...

    def test_the_fuzz_corpus_is_varied_and_reproducible(self):
        texts = coordinate_fuzz_urls()
        self.assertEqual(texts, coordinate_fuzz_urls())
        found = [web_ui.try_parse_maps_url(t) for t in texts]
        self.assertGreater(sum(f is not None for f in found), 300)
        self.assertGreater(sum(f is None for f in found), 100)


class CompositionTests(unittest.TestCase):
    """The studio's rules. Expected values are the ones in flutter_navigation_basic's Dart tests (chord_theory, metronome_timing, note_sequence)."""

    def test_chord_theory_as_the_dart_tests_say(self):
        w = web_ui
        self.assertEqual(w.convert_progression("C", "I V vi IV", minor=False), ["C", "G", "Am", "F"])
        key = w.transpose_key("C", 2)
        self.assertEqual((key, w.convert_progression(key, "I V vi IV", minor=False)), ("D", ["D", "A", "Bm", "G"]))
        self.assertEqual(w.transpose_key("C", -1), "B")
        self.assertEqual([w.fifth_neighbor("C", clockwise=False), w.fifth_neighbor("C", clockwise=True), w.fifth_neighbor("D♭", clockwise=False),
                          w.fifth_neighbor("D♭", clockwise=True)], ["F", "G", "G♭", "A♭"])
        self.assertEqual(w.scale("F♯", minor=False), ["F♯", "G♯", "A♯", "B", "C♯", "D♯", "E♯"])           # one letter per degree: E♯, not F
        self.assertEqual(w.convert_progression("C", "I6 IV6 Imaj7 V7 ii7 viiø7 IVsus2 IVadd9 Vaug", minor=False),
                         ["C6", "F6", "Cmaj7", "G7", "Dm7", "Bm7♭5", "Fsus2", "Fadd9", "Gaug"])
        self.assertEqual(w.convert_progression("C", "ii6 vi6", minor=False), ["Dm6", "Am6"])
        self.assertEqual([w.apply_modifier(r, m) for r, m in (("C", "6"), ("C", "m6"), ("B", "m7♭5"), ("C", "sus2"), ("C", "sus4"), ("F", "add9"),
                                                              ("F", "add11"), ("D", "dim"), ("E", "aug"), ("G", "7"))],
                         ["C6", "Cm6", "Bm7♭5", "Csus2", "Csus4", "Fadd9", "Fadd11", "Ddim", "Eaug", "G7"])
        self.assertEqual([w.chord_with_inversion("C", "maj7", i) for i in range(4)], ["Cmaj7", "Cmaj7/E", "Cmaj7/G", "Cmaj7/B"])
        self.assertEqual(w.chord_with_inversion("C", "6", 3), "C6/A")
        self.assertEqual((w.normalized_inversion("triad", 3), w.chord_with_inversion("C", "triad", 3), w.chord_with_inversion("C", "sus4", 3)), (1, "C/E", "Csus4/F"))
        self.assertEqual([w.diatonic_chord("C", d, minor=False) for d in range(1, 8)], ["C", "Dm", "Em", "F", "G", "Am", "Bdim"])

    def test_every_key_and_chord_is_spelled_consistently_and_bad_input_is_refused(self):
        w = web_ui
        for key in w.SELECTABLE_KEYS:
            for minor in (False, True):
                notes = w.scale(key, minor=minor)
                self.assertEqual((notes[0], [n[0] for n in notes]), (key, [("CDEFGAB" * 2)[("CDEFGAB".index(key[0]) + i)] for i in range(7)]), (key, minor))
                steps = (0, 2, 3, 5, 7, 8, 10) if minor else (0, 2, 4, 5, 7, 9, 11)
                self.assertEqual([w.pitch_class(n) for n in notes], [(w.pitch_class(key) + st) % 12 for st in steps])
                for neighbor in (w.fifth_neighbor(key, clockwise=True), w.fifth_neighbor(key, clockwise=False)):
                    self.assertIn(neighbor, w.SELECTABLE_KEYS)                                         # the circle never leaves the key list
                for modifier in w.CHORD_MODIFIERS:
                    for root in notes:
                        for inversion in range(4):
                            chord = w.chord_with_inversion(root, modifier, inversion)
                            self.assertTrue(chord.startswith(w.apply_modifier(root, modifier)))
        for bad in ("H", "c", "C#", "", "C♯♭x", None, 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.pitch_class(bad)
        for call in (lambda: w.diatonic_chord("C", 0, minor=False), lambda: w.diatonic_chord("C", 8, minor=False), lambda: w.apply_modifier("C", "9"),
                     lambda: w.chord_tones("C", "nope"), lambda: w.normalized_inversion("triad", 4), lambda: w.normalized_inversion("triad", -1), lambda: w.scale("H", minor=False)):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(w.convert_progression("C", "I – V | vi, IV", minor=False), ["C", "G", "Am", "F"])
        self.assertEqual(w.convert_progression("C", "x I y", minor=False), ["x", "C", "y"])                  # not a numeral: kept as written
        self.assertEqual(w.convert_progression("A", "i iv v i", minor=True), ["Am", "Dm", "Em", "Am"])
        self.assertEqual(w.convert_progression("C", "", minor=False), [])

    def test_metronome_and_tap_tempo_as_the_dart_tests_say(self):
        w = web_ui
        self.assertEqual((w.beat_micros(120), w.bar_micros(120, 4), w.subdivision_micros(120, 2)), (500_000, 2_000_000, 250_000))
        self.assertEqual(w.metronome_position(750_000, 120, 4, 2), (1, 1, 0.0))                              # position comes from elapsed time
        self.assertEqual(w.metronome_position(2_250_000, 120, 4, 2)[:2], (0, 1))                             # and wraps at the end of the bar
        self.assertEqual(w.metronome_position(-5, 120, 4, 2), (0, 0, 0.0))
        self.assertEqual((w.beat_micros(1), w.beat_micros(30), w.beat_micros(9999), w.beat_micros(300)), (2_000_000, 2_000_000, 200_000, 200_000))
        for bad in ((lambda: w.subdivision_micros(120, 0)), (lambda: w.bar_micros(120, 0)), (lambda: w.metronome_position(0, 120, 0, 2))):
            with self.assertRaises(ValueError):
                bad()
        taps, bpms = [], []
        for ms in (0, 500, 1000, 1500):
            taps, bpm = w.tap_tempo(taps, ms * 1000)
            bpms.append(bpm)
        self.assertEqual(bpms, [None, 120, 120, 120])
        taps, _ = w.tap_tempo([], 0)
        taps, bpm = w.tap_tempo(taps, 500_000)
        taps, bpm2 = w.tap_tempo(taps, 3_000_000)                                                            # more than two seconds: start again
        self.assertEqual((bpm, bpm2, len(taps)), (120, None, 1))
        self.assertEqual(w.tap_tempo([0], 100_000)[1], 300)                                                  # clamped to the supported range
        self.assertEqual(w.tap_tempo([0], 1_900_000)[1], 32)
        self.assertEqual(w.tap_tempo([5], 5)[1], None)                                                       # no time passed
        taps = []
        for ms in range(0, 3000, 400):                                                                       # only the last five intervals count
            taps, bpm = w.tap_tempo(taps, ms * 1000)
        self.assertEqual((len(taps), bpm), (6, 150))
        self.assertEqual([w.duration_label(m) for m in (500_000, 2_000_000, 1_125_000, 999_999, 1_000_000, 0)],
                         ["500 ms", "2.00 s", "1.13 s", "1000 ms", "1.00 s", "0 ms"])

    def test_note_sequences_as_the_dart_tests_say(self):
        w = web_ui
        self.assertEqual(w.parse_notes("C3 d3 F#3 Gb3"), ["C3", "D3", "F♯3", "G♭3"])
        self.assertEqual(w.note_bars(w.parse_notes("C3 D3 C3 D3 G3 A3 G3 C4"), 4, 4, 8), [["C3", "D3", "C3", "D3", "G3", "A3", "G3", "C4"]])
        self.assertEqual(w.note_bars(w.parse_notes("C3 D3 E3 F3 G3 A3 B3 C4"), 4, 4, 4), [["C3", "D3", "E3", "F3"], ["G3", "A3", "B3", "C4"]])
        self.assertEqual((w.notes_per_bar(6, 8, 8), w.notes_per_bar(6, 8, 4), w.notes_per_bar(3, 4, 8)), (6, 3, 6))
        self.assertEqual(w.parse_notes("C3,D3,\tE-1\n"), ["C3", "D3", "E-1"])
        self.assertEqual((w.parse_notes(""), w.note_bars([], 4, 4, 8)), ([], []))
        for bad in ("C3 nope D3", "C", "C33", "H3", "C3#", "c♯♭3", "٣"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                w.parse_notes(bad)
        for args in ((4, 4, 16), (5, 8, 4), (4, 4, 2), (0, 4, 4)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                w.notes_per_bar(*args)

    def test_the_seeded_song_seed(self):
        w = web_ui
        seeds = [w.song_seed(n) for n in range(2000)]
        self.assertEqual(w.song_seed(5), w.song_seed(5))
        self.assertTrue(all(80 <= x["bpm"] <= 160 and x["tonic"] in w.SEED_KEYS and x["time"] in w.SEED_TIMES and x["progression"] in w.SEED_PROGRESSIONS[x["mode"]] for x in seeds))
        for field, options in (("tonic", w.SEED_KEYS), ("mode", w.SEED_MODES), ("time", w.SEED_TIMES)):
            self.assertEqual({x[field] for x in seeds}, set(options))
        self.assertEqual({x["bpm"] for x in seeds}, set(range(80, 161)))
        self.assertTrue(all(w.song_seed(n, avoid=w.song_seed(n)) != w.song_seed(n) for n in range(300)))          # asked to differ, it does
        self.assertEqual(w.song_seed_text({"tonic": "E♭", "mode": "Minor", "bpm": 100, "time": "6/8", "progression": "i – iv – v – i"}),
                         "Key: E♭ Minor · BPM: 100 · Time: 6/8 · Progression: i – iv – v – i")
        self.assertEqual(w.song_seed(1), {"tonic": "B♭", "mode": "Minor", "bpm": 122, "time": "6/8", "progression": "i – iv – v – i"})   # frozen: the page must agree


DOOR = web_ui.example_data("door")
# The identities the Flutter doc's examples use (docs/testing/page-identities.md), as a door registry.
FLUTTER_PAGES = [{"emoji": e, "label": l, "href": h} for e, l, h in (("🏠", "Home", "#/"), ("🗺️", "Hub", "#/hub"), ("🥐", "Irony", "#/examples/irony-generator"),
                                                                 ("🌍", "Screen1", "#/screen1"), ("🕶️", "Screen2", "#/screen2"))]


class DoorTests(unittest.TestCase):
    """Page emoji, the go/return notation, the seeded draw and the pull-down."""

    def test_the_example_is_valid_and_validation_is_idempotent(self):
        door = web_ui.door_validate(DOOR)
        self.assertEqual(web_ui.door_validate(door), door)
        self.assertEqual(len({web_ui.emoji_key(p["emoji"]) for p in door["pages"]}), len(door["pages"]))

    def test_bad_registries_are_refused(self):
        page = lambda e, h, **kw: {"emoji": e, "label": "L", "href": h, **kw}
        for bad in ({**DOOR, "schema": "x"}, {**DOOR, "extra": 1}, {**DOOR, "pages": []}, {**DOOR, "pages": "x"},
                    {**DOOR, "pages": [page("🏠", "/a"), page("🏠", "/b")], "k": 0},                    # the same emoji twice
                    {**DOOR, "pages": [page("🗺️", "/a"), page("🗺", "/b")], "k": 0},                    # ... even if only a variation selector differs
                    {**DOOR, "pages": [page("🏠", "/a"), page("🏠\ufe0e", "/b")], "k": 0},
                    {**DOOR, "pages": [page("🏠", "/a"), page("🧭", "/a")], "k": 0},                    # the same href twice
                    {**DOOR, "pages": [page("🏠", "/a"), page("A", "/b")], "k": 0},                     # plain text is not an emoji
                    {**DOOR, "pages": [page("🏠", "/a", group="other")], "k": 0},
                    {**DOOR, "pages": [page("🏠", "/a", group="discover")], "k": 0},                    # nothing stable: no Home
                    {**DOOR, "pages": [page("🏠", "/a"), page("🧭", "/b", group="discover")], "k": 2},   # more drawn than can be
                    {**DOOR, "k": 9}, {**DOOR, "seed": -1}, {**DOOR, "seed": 2**32}, {**DOOR, "current": "./nowhere.html"}):
            with self.subTest(bad=str(bad)[:70]), self.assertRaises(ValueError):
                web_ui.door_validate(bad)
        for href in ("javascript:alert(1)", "//evil.example/x", "ftp://x/y", "http:///x", "a b", "a\\b", "data:text/html,x", "", "x" * 513, "mailto:a@b", "\x00"):
            with self.subTest(href=href), self.assertRaises(ValueError):
                web_ui.door_validate({"schema": web_ui.DOOR_SCHEMA, "pages": [page("🏠", href)], "k": 0})
        for href in ("./a.html", "../a.html#x", "/abs/path", "#/hub", "a/b?c=d", "https://example.com/a", "http://x"):
            web_ui.door_validate({"schema": web_ui.DOOR_SCHEMA, "pages": [page("🏠", href)], "k": 0})

    def test_emoji_transitions_as_the_flutter_doc_writes_them(self):
        path = lambda text: web_ui.emoji_path(text, FLUTTER_PAGES)
        self.assertEqual(path("🏠 ↔︎ 🗺️"), ["#/", "#/hub", "#/"])                              # go and come back (with a variation selector, ignored)
        self.assertEqual(path("🏠 → 🥐"), ["#/", "#/examples/irony-generator"])
        self.assertEqual(path("🏠 → 🗺️ → 🌍 ↔ 🕶️"), ["#/", "#/hub", "#/screen1", "#/screen2", "#/screen1"])   # chains expand left to right
        self.assertEqual(path("🗺 → 🏠"), ["#/hub", "#/"])                                      # 🗺 and 🗺️ are the same page
        self.assertEqual(path(" 🏠\u3000→\n🥐 "), ["#/", "#/examples/irony-generator"])
        self.assertEqual(path("🏠"), ["#/"])
        for bad in ("🏠 → 🦄", "", "→", "🏠 →", "→ 🏠", "🏠 → → 🥐", "🏠 ↔ 🥐 🌍", "🏠 - 🥐"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                path(bad)                                                                           # an unknown emoji returns nothing at all

    def test_the_seeded_draw(self):
        self.assertEqual(web_ui.door_draw(1, 10, 3), [6, 1, 0])                                     # frozen: the page must give the same
        self.assertEqual(web_ui.door_draw(20261103, 6, 3), [1, 3, 5])
        for seed in (0, 1, 2**32 - 1, 12345):
            for count, k in ((1, 1), (5, 0), (5, 5), (64, 3), (193, 3)):
                draw = web_ui.door_draw(seed, count, k)
                self.assertEqual((len(draw), len(set(draw)), all(0 <= i < count for i in draw)), (k, k, True))
                self.assertEqual(draw, web_ui.door_draw(seed, count, k))
        self.assertEqual(sorted(web_ui.door_draw(7, 9, 9)), list(range(9)))                         # k = count is a shuffle
        for bad in ((1, 3, 4), (1, 3, -1)):
            with self.assertRaises(ValueError):
                web_ui.door_draw(*bad)
        counts = [0] * 12
        for seed in range(3000):
            for i in web_ui.door_draw(seed, 12, 3):
                counts[i] += 1
        self.assertTrue(all(abs(c - 750) < 120 for c in counts), counts)                            # no index is favored (3000 draws x 3 of 12)
        first = [next(g) for g in [web_ui.mulberry32(s) for s in range(1000)]]
        self.assertTrue(all(0 <= x < 1 for x in first) and len(set(first)) == 1000)

    def test_the_pulldown_order_marking_and_markup(self):
        options = web_ui.door_options(DOOR)
        self.assertEqual(options[0]["href"], "../index.html")                                       # Home first
        self.assertEqual([o["drawn"] for o in options[1:4]], [True] * 3)
        self.assertEqual(sum(o["drawn"] for o in options), 3)
        self.assertEqual([o["href"] for o in options[4:]], [p["href"] for p in web_ui.door_validate(DOOR)["pages"] if p["group"] == "stable"][1:])
        self.assertEqual([o["current"] for o in options].count(True), 1)
        self.assertNotEqual([o["href"] for o in web_ui.door_options(DOOR, 1)[1:4]], [o["href"] for o in options[1:4]])
        html = web_ui.door_html({**DOOR, "pages": [{**p, "label": "<b>" + p["label"]} for p in DOOR["pages"]]})
        self.assertNotIn("<b>", html)
        self.assertEqual(html.count("selected disabled"), 1)
        self.assertIn("(current)", html)
        self.assertEqual(web_ui.door_document(DOOR).count("<script"), 1)
        self.assertNotIn("<link", web_ui.door_document(DOOR))


BASE64_CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "base64_bridge_cases.json").read_text(encoding="utf-8"))
PNG_B64 = BASE64_CASES["cases"][0]["text"]                                                       # a real 2x1 PNG, raw Base64


def shelf_fuzz_texts(count: int = 1200, seed: int = 20261103) -> list[str]:
    """Seeded pasted texts: Markdown-ish lines, URLs, image text with wrapping, odd whitespace, bad padding, wrong labels, case tricks."""
    rng = random.Random(seed)
    spaces = [" ", " ", "\t", "\n", "\r\n", "\r", "\u00a0", "\u3000", "\x85", "\ufeff", "\x1f", "\u2028"]
    words = ["# Title", "## sub", "- item", "* item", "+ item", "> quote", "1. one", "2) two", "```py", "```", "plain words", "**bold**", "~~gone~~", "`code`",
             "[link](http://x.test/a)", "[bad](", "see https://example.com/a?b=c", "https://example.com/a?b=c", "HTTPS://X.TEST/", "http://", "https://a b",
             "\u017fttps://x", "ftp://x/y", "data:image/png;base64," + PNG_B64, "DATA:IMAGE/PNG;BASE64," + PNG_B64, PNG_B64, PNG_B64[:40], "data:text/plain,hi", "####### seven",
             "\u212a", "    indented", "  # two spaces", "#nospace", "-x", "日本語のメモ", "😀", "<b>x</b>", '"quoted"', "a" * 90, "A" * 88]
    out = []
    for _ in range(count):
        parts = [rng.choice(words) for _ in range(rng.randint(1, 6))]
        text = "".join(part + rng.choice(spaces) for part in parts)
        roll = rng.random()
        if roll < 0.12:
            text = " " * rng.randint(1, 3) + text
        elif roll < 0.2:
            text = text.replace("=", "", 1)
        elif roll < 0.25:
            text = text.replace("+", "-").replace("/", "_")
        elif roll < 0.3:
            text = PNG_B64[: rng.randint(1, len(PNG_B64))]
        elif roll < 0.35:
            text = "data:image/" + rng.choice(["png", "jpeg", "jpg", "webp", "gif", "x", ""]) + rng.choice([";base64,", ",", ";charset=utf-8;base64,", ";a=\"b\";base64,"]) + PNG_B64
        out.append(text)
    return out


class ShelfTests(unittest.TestCase):
    """The clipboard shelf's rules: Ironmate's Base64 cases are the golden file for the image reading."""

    def test_ironmate_base64_cases(self):
        self.assertEqual(len(BASE64_CASES["cases"]), 19)
        limit = BASE64_CASES["limits"]["maxInputBytes"]
        self.assertEqual((limit, web_ui.shelf_max_chars(limit)), (web_ui.SHELF_MAX_IMAGE_BYTES, BASE64_CASES["limits"]["maxBase64Chars"]))
        for case in BASE64_CASES["cases"]:
            with self.subTest(case["id"]):
                got = web_ui.decode_image_text(case["text"], limit)
                self.assertEqual(got["ok"], case["expect"] == "ok")
                self.assertEqual(got["format"] if got["ok"] else got["category"], case["result"])

    def test_image_limits_and_text_that_only_looks_like_an_image(self):
        png = web_ui.decode_image_text(PNG_B64)
        self.assertEqual((png["format"], png["mime"]), ("png", "image/png"))
        self.assertEqual(png["bytes"], len(base64.b64decode(PNG_B64)))
        self.assertEqual(web_ui.decode_image_text(PNG_B64, png["bytes"] - 1), {"ok": False, "category": "too_large"})   # the byte limit is exact
        self.assertTrue(web_ui.decode_image_text(PNG_B64, png["bytes"])["ok"])
        self.assertEqual(web_ui.decode_image_text("A" * 100, 10), {"ok": False, "category": "too_large"})
        jpeg = base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(20)).decode()
        webp = base64.b64encode(b"RIFF\x00\x00\x00\x00WEBPVP8 " + bytes(8)).decode()
        self.assertEqual([web_ui.decode_image_text(x)["format"] for x in (jpeg, webp, "data:image/jpg;base64," + jpeg)], ["jpeg", "webp", "jpeg"])
        self.assertEqual(web_ui.decode_image_text("data:image/png;base64," + jpeg), {"ok": False, "category": "mismatch"})
        self.assertEqual(web_ui.decode_image_text("data:;base64," + png["data"])["ok"], True)           # no declared type: the bytes decide
        self.assertTrue(web_ui.looks_like_image(PNG_B64) and web_ui.looks_like_image("data:image/x"))
        self.assertFalse(web_ui.looks_like_image("hello world, this is just a sentence that is long enough to look suspicious at first glance!"))
        self.assertFalse(web_ui.looks_like_image("A" * 79))
        self.assertEqual(web_ui.decode_image_text("\u017fttps"), {"ok": False, "category": "bad_base64"})

    def test_classify_markdown_prompt_and_bundle(self):
        classify = web_ui.shelf_classify
        self.assertEqual([classify(t) for t in ("https://example.com/a?b=c", "  HTTP://X.TEST/  ", "https://a b", "http://", "ftp://x/y", "plain", "")],
                         ["url", "url", "text", "text", "text", "text", "text"])
        self.assertEqual([classify(t) for t in ("# T", "  ## T", "    # four spaces", "- a", "> q", "```py", "x\n* y", "[a](b)", "#nospace", "-x", "a [b](c) d")],
                         ["markdown", "markdown", "text", "markdown", "markdown", "markdown", "markdown", "markdown", "text", "text", "markdown"])
        self.assertEqual(web_ui.markdown_plain("# T\n> q\n- i\n1. n\n```py\nc `x` **b** ~~s~~ [l](u)\n```"), "T\nq\ni\nn\n\nc x b s l (u)")
        self.assertEqual(web_ui.build_prompt({}), "# System Prompt Draft")
        self.assertEqual(web_ui.build_prompt({"goal": " G ", "raw": "r", "must": "  "}, {"mime": "image/png", "bytes": 5}),
                         "# System Prompt Draft\n\n## Goal\nG\n\n## Raw source\nr\n\n## Visual reference\nAn image reference is attached in the workbench "
                         "(image/png, 5 bytes).\nUse its layout/content as visual context when the receiving system supports image input.")
        self.assertEqual(web_ui.shelf_bundle([{"kind": "text", "text": "a"}, {"kind": "image", "mime": "image/png", "data": "QQ=="}, {"kind": "url", "text": "https://x/"}]),
                         "# Context Bundle\n\n## 1. Text\na\n\n## 2. Image\ndata:image/png;base64,QQ==\n\n## 3. URL\nhttps://x/")

    def test_the_fuzz_corpus_is_varied_and_reproducible(self):
        texts = shelf_fuzz_texts()
        self.assertEqual(texts, shelf_fuzz_texts())
        kinds = {web_ui.shelf_classify(t) for t in texts}
        outcomes = {r["format"] if r["ok"] else r["category"] for r in map(web_ui.decode_image_text, texts)}
        self.assertEqual(kinds, {"text", "url", "markdown"})
        self.assertGreaterEqual(len(outcomes), 6, outcomes)
        self.assertGreater(sum(map(web_ui.looks_like_image, texts)), 100)

    def test_the_page_is_one_file_with_the_filters_in_css(self):
        css = web_ui.css_source("shelf.css")
        for kind in web_ui.SHELF_KINDS:
            self.assertIn(f'#shelf-kind-{kind}:checked) .ui-shelf-item:not([data-kind="{kind}"]){{display:none}}', css)
        page = web_ui.shelf_document()
        self.assertEqual(page.count("<script"), 1)
        for needle in ("data-shelf-add", "shelf-sort-manual", "data-shelf-prompt"):
            self.assertIn(needle, page)
        self.assertNotIn("<link", page)


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


PHOTO_FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "photo_import_cases.json").read_text(encoding="utf-8"))
PHOTO_CASES = {case["id"]: case for case in PHOTO_FIXTURE["cases"]}


def photo_file(case_id):
    data = PHOTO_CASES[case_id]["data"]
    return base64.b64decode(data) if data else b""


def photo_pillow_engine(data):
    """An engine to decode with: Pillow, fully (so a truncated file fails), as ``(width, height)`` or ``None``."""
    import io
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.size
    except Exception:
        return None


class PhotoSniffTests(unittest.TestCase):
    """Format hints, with flutter_navigation_basic's Dart sniff tests and Pillow as the oracle."""

    def test_the_fixtures_are_the_bytes_that_were_copied(self):
        import hashlib
        for case in PHOTO_FIXTURE["cases"]:
            if case["data"]:
                with self.subTest(case["id"]):
                    self.assertEqual(hashlib.sha256(photo_file(case["id"])).hexdigest(), case["sha256"])
                    self.assertEqual(len(photo_file(case["id"])), case["bytes"])
        self.assertEqual(PHOTO_FIXTURE["limits"], {"maxInputBytes": web_ui.PHOTO_MAX_BYTES, "maxPixels": web_ui.PHOTO_MAX_PIXELS, "maxDocumentLongEdge": web_ui.PHOTO_MAX_EDGE})
        self.assertEqual(tuple(PHOTO_FIXTURE["outcomeVocabulary"]), web_ui.PHOTO_OUTCOMES)

    def test_the_dart_sniff_tests(self):
        w = web_ui
        kinds = {"png_opaque_2x2": None, "png_opaque_64x32": "png", "png_alpha_64x32": "png", "png_markers_64x32": "png", "jpeg_baseline_markers_64x32": "jpeg",
                 "webp_lossy_64x32": "webp", "webp_lossless_64x32": "webp", "webp_alpha_8x4": "webp", "gif_still_1x1": "gif", "avif_ftyp_only": "avif",
                 "heic_synthetic_markers_64x32": "heic", "empty": "empty", "png_truncated": "png", "png_claim_10000x10000": "png"}
        for case_id, kind in kinds.items():
            if kind:
                with self.subTest(case_id):
                    self.assertEqual(w.photo_sniff(photo_file(case_id))["kind"], kind)
        for brand in ("heic", "heif", "mif1", "msf1", "heix"):
            info = w.photo_sniff(photo_file(f"heic_ftyp_{brand}"))
            self.assertEqual((info["kind"], info["brand"], info["label"]), ("heic", brand, "HEIC"))
        self.assertEqual(w.photo_sniff(photo_file("avif_ftyp_only"))["brand"], "avif")
        self.assertEqual(w.photo_sniff(b"")["label"], "empty")
        self.assertEqual(w.photo_sniff(bytes([1, 2, 3, 4]))["kind"], "unknown")
        self.assertEqual([w.photo_sniff(photo_file(i))["label"] for i in ("png_markers_64x32", "jpeg_baseline_markers_64x32", "webp_lossy_64x32", "gif_still_1x1")],
                         ["PNG", "JPEG", "WebP", "GIF"])
        self.assertTrue(w.photo_sniff(photo_file("jpeg_progressive_markers_64x32"))["progressive"])
        self.assertFalse(w.photo_sniff(photo_file("jpeg_baseline_markers_64x32"))["progressive"])
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                info = w.photo_sniff(photo_file(f"jpeg_exif_orientation_{orientation}_markers_64x32"))
                self.assertEqual((info["kind"], info["orientation"]), ("jpeg", orientation))
        self.assertIsNone(w.photo_sniff(photo_file("jpeg_baseline_markers_64x32"))["orientation"])
        for tail in (b"\x00" * 3, b"\x89PNG", b"RIFF\0\0\0\0WEB", b"GIF8", b"GIF87a", b"\xff\xd8"):
            self.assertIn(w.photo_sniff(tail)["kind"], ("gif", "unknown", "png", "jpeg", "webp"))

    def test_marker_scanning_like_the_dart_tests(self):
        base = photo_file("jpeg_exif_orientation_6_markers_64x32")
        xmp = "http://ns.adobe.com/xap/1.0/\u0000<x/>".encode("latin-1")
        length = len(xmp) + 2
        with_xmp = base[:2] + bytes([0xFF, 0xE1, length >> 8, length & 0xFF]) + xmp + base[2:]
        self.assertEqual(web_ui.photo_sniff(with_xmp)["orientation"], 6)                    # an XMP APP1 before the EXIF one
        self.assertEqual(web_ui.photo_sniff(base[:2] + b"\xff\xff" + base[2:])["orientation"], 6)   # fill bytes before a marker
        self.assertEqual(web_ui.photo_sniff(base[:2] + b"\xff\xff" + base[2:])["kind"], "jpeg")

    @staticmethod
    def jpeg_with(marker, width=640, height=480):
        sof = bytes([0xFF, marker, 0, 17, 8, height >> 8, height & 255, width >> 8, width & 255, 3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1])
        return b"\xff\xd8" + b"\xff\xe0\x00\x04\x00\x00" + sof + b"\xff\xd9"

    def test_every_start_of_frame_marker(self):
        for marker in range(0xC0, 0xD0):
            data = self.jpeg_with(marker)
            with self.subTest(marker=hex(marker)):
                self.assertEqual(web_ui.photo_sniff(data)["progressive"], marker in (0xC2, 0xC6, 0xCA, 0xCE))        # Huffman or arithmetic progressive; the rest scan on
                self.assertEqual(web_ui.photo_header_size(data), (640, 480) if marker not in (0xC4, 0xC8, 0xCC) else None)   # DHT, JPG and DAC are not frames
        self.assertEqual(web_ui.photo_header_size(self.jpeg_with(0xC0, 65535, 65535)), (65535, 65535))

    def test_progressive_and_orientation_agree_with_pillow(self):
        import io
        from PIL import Image
        for case in PHOTO_FIXTURE["cases"]:
            if case["format"] != "jpeg":
                continue
            with self.subTest(case["id"]):
                data = photo_file(case["id"])
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(web_ui.photo_sniff(data)["progressive"], bool(image.info.get("progressive")))
                    self.assertEqual(web_ui.photo_sniff(data)["orientation"], image.getexif().get(0x0112))

    def test_orientation_is_neutralised_in_two_bytes_only(self):
        for orientation in range(1, 9):
            data = photo_file(f"jpeg_exif_orientation_{orientation}_markers_64x32")
            neutral = web_ui.photo_neutralize_orientation(data)
            with self.subTest(orientation=orientation):
                self.assertEqual(len(neutral), len(data))
                self.assertEqual(web_ui.photo_sniff(neutral)["orientation"], 1)
                self.assertLessEqual(sum(a != b for a, b in zip(data, neutral)), 1 if orientation > 1 else 0)
                self.assertEqual(web_ui.photo_neutralize_orientation(neutral), neutral)
        for case_id in ("png_markers_64x32", "jpeg_baseline_markers_64x32", "empty", "heic_ftyp_heic"):
            self.assertEqual(web_ui.photo_neutralize_orientation(photo_file(case_id)), photo_file(case_id))
        big = bytearray(photo_file("jpeg_exif_orientation_6_markers_64x32"))                  # big-endian TIFF: the value is 00 06
        self.assertEqual(web_ui.photo_sniff(bytes(big))["orientation_big_endian"] in (True, False), True)

    def test_damaged_files_never_raise(self):
        rng = random.Random(5)
        for case in PHOTO_FIXTURE["cases"]:
            data = photo_file(case["id"]) if case["data"] else b""
            variants = [data[:n] for n in range(0, len(data) + 1, max(1, len(data) // 60))]
            for _ in range(40):
                mutated = bytearray(data)
                for _ in range(rng.randint(1, 4)):
                    if mutated:
                        mutated[rng.randrange(len(mutated))] = rng.randrange(256)
                variants.append(bytes(mutated))
            for variant in variants:
                info = web_ui.photo_sniff(variant)
                self.assertIn(info["kind"], web_ui.PHOTO_LABELS)
                self.assertIn(info["orientation"], (None, 1, 2, 3, 4, 5, 6, 7, 8))
                size = web_ui.photo_header_size(variant)
                self.assertTrue(size is None or (len(size) == 2 and all(isinstance(v, int) and v >= 0 for v in size)), (case["id"], size))
                self.assertEqual(len(web_ui.photo_neutralize_orientation(variant)), len(variant))
                web_ui.photo_decide(variant, photo_pillow_engine)


class PhotoImportTests(unittest.TestCase):
    """Header sizes, the pixel budget, the order of checks and the stored size."""

    def test_header_sizes_equal_pillows_for_every_fixture(self):
        import io
        from PIL import Image
        for case in PHOTO_FIXTURE["cases"]:
            if not case["data"] or case["format"] in ("heic", "avif", "empty") or case["id"] in ("png_claim_10000x10000", "png_truncated"):
                continue
            with self.subTest(case["id"]):
                with Image.open(io.BytesIO(photo_file(case["id"]))) as image:
                    self.assertEqual(web_ui.photo_header_size(photo_file(case["id"])), image.size)
        self.assertEqual(web_ui.photo_header_size(photo_file("png_claim_10000x10000")), (10000, 10000))
        self.assertEqual(web_ui.photo_header_size(photo_file("png_truncated")), (64, 32))      # cut after the sizes: the header alone cannot tell it is damaged
        for case_id in ("heic_ftyp_heic", "heic_synthetic_markers_64x32", "avif_ftyp_only", "empty"):
            self.assertIsNone(web_ui.photo_header_size(photo_file(case_id)))

    def test_pictures_made_by_pillow_in_every_format_agree(self):
        import io
        from PIL import Image
        rng = random.Random(11)
        sizes = [(1, 1), (1, 2), (2, 1), (16383, 1), (1, 16383), (255, 256), (257, 255), (640, 480)] + [(rng.randint(1, 300), rng.randint(1, 300)) for _ in range(30)]
        for width, height in sizes:
            rgb = Image.frombytes("RGB", (width, height), bytes(rng.randrange(256) for _ in range(3 * width * height)) if width * height <= 4096 else bytes(3 * width * height))
            rgba = rgb.convert("RGBA")
            rgba.putalpha(Image.frombytes("L", (width, height), bytes(rng.randrange(256) for _ in range(width * height)) if width * height <= 4096 else bytes(width * height)))
            made = {"png": (rgb, "PNG", {}), "png-rgba": (rgba, "PNG", {}), "gif": (rgb.convert("P"), "GIF", {}), "jpeg": (rgb, "JPEG", {"quality": 70}),
                    "jpeg-progressive": (rgb, "JPEG", {"progressive": True}), "webp-lossy": (rgb, "WEBP", {"quality": 60}),
                    "webp-lossless": (rgb, "WEBP", {"lossless": True}), "webp-alpha-lossy": (rgba, "WEBP", {"quality": 60}),
                    "webp-alpha-lossless": (rgba, "WEBP", {"lossless": True}), "webp-exif": (rgb, "WEBP", {"exif": b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00"})}
            for name, (image, fmt, options) in made.items():
                if fmt == "WEBP" and max(width, height) > 16383:
                    continue
                buffer = io.BytesIO()
                image.save(buffer, fmt, **options)
                with self.subTest(size=(width, height), format=name):
                    self.assertEqual(web_ui.photo_header_size(buffer.getvalue()), (width, height))
                    self.assertEqual(web_ui.photo_sniff(buffer.getvalue())["kind"], {"png": "png", "png-rgba": "png", "gif": "gif", "jpeg": "jpeg", "jpeg-progressive": "jpeg"}.get(name, "webp"))
        built = web_ui.photo_png(3, 2, bytes(range(24)))
        with Image.open(io.BytesIO(built)) as image:
            image.load()
            self.assertEqual((image.size, image.mode, list(image.tobytes())), ((3, 2), "RGBA", list(range(24))))
        self.assertEqual(web_ui.photo_header_size(web_ui.photo_png(40001, 1)), (40001, 1))
        with self.assertRaises(ValueError):
            web_ui.photo_png(2, 2, b"short")

    def test_a_png_must_reach_iend(self):
        import io
        from PIL import Image
        for case in PHOTO_FIXTURE["cases"]:
            if case["format"] == "png" and case["data"]:
                with self.subTest(case["id"]):
                    self.assertEqual(web_ui.photo_png_complete(photo_file(case["id"])), case["id"] != "png_truncated")
        whole = io.BytesIO()
        Image.new("RGB", (9, 7), (1, 2, 3)).save(whole, "PNG")
        data = whole.getvalue()
        self.assertTrue(web_ui.photo_png_complete(data))
        self.assertTrue(web_ui.photo_png_complete(data + b"trailing bytes"))                  # what follows IEND is not the picture's business
        for n in range(len(data)):
            self.assertFalse(web_ui.photo_png_complete(data[:n]), n)                          # every cut-off copy is refused
        self.assertFalse(web_ui.photo_png_complete(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND" + b"\x00" * 4))   # IEND before IHDR
        self.assertFalse(web_ui.photo_png_complete(data[:8] + b"\xff\xff\xff\xff" + data[12:]))          # a length larger than the file
        cut = web_ui.photo_decide(data[:-5], lambda d: (9, 7))                                  # whatever the engine would say
        self.assertEqual((cut["outcome"], cut["message"]), ("rejected:undecodable", "That image format could not be decoded."))
        self.assertTrue(web_ui.photo_decide(data, lambda d: (9, 7))["ok"])

    def test_the_png_probe_is_a_2x2_picture_and_probes_are_what_they_claim(self):
        import io
        from PIL import Image
        probes = {p["id"]: p for p in web_ui.photo_probes()}
        self.assertEqual(list(probes), ["png", "jpeg", "jpeg_exif_orientation_6", "webp_lossy", "webp_lossless", "webp_alpha", "gif", "avif", "heic"])
        png = base64.b64decode(probes["png"]["data"])
        with Image.open(io.BytesIO(png)) as image:
            image.load()
            self.assertEqual((image.size, list(image.convert("RGBA").tobytes())), ((2, 2), [255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 0, 128]))
        self.assertEqual(web_ui.photo_header_size(png), (2, 2))
        for probe in probes.values():
            data = base64.b64decode(probe["data"])
            self.assertEqual("image/" + web_ui.photo_sniff(data)["kind"], probe["mime"])
            if probe["id"] != "heic":
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
        self.assertEqual(web_ui.photo_sniff(base64.b64decode(probes["jpeg_exif_orientation_6"]["data"]))["orientation"], 6)
        self.assertEqual(web_ui.photo_sniff(base64.b64decode(probes["heic"]["data"]))["brand"] in web_ui.PHOTO_HEIC_BRANDS, True)

    def test_the_decision_order_reproduces_what_flutter_measured(self):
        for case in PHOTO_FIXTURE["cases"]:
            expected = case["flutter_test_ci"]
            if expected in (None, "not_verified"):
                continue
            with self.subTest(case["id"]):
                result = web_ui.photo_decide(photo_file(case["id"]), photo_pillow_engine)
                self.assertEqual(result["outcome"], expected)
                self.assertIn(result["outcome"], web_ui.PHOTO_OUTCOMES)
                self.assertEqual(result["ok"], expected == "supported")
        ok = web_ui.photo_decide(photo_file("png_markers_64x32"), photo_pillow_engine)
        self.assertEqual((ok["format"], ok["width"], ok["height"], ok["document"], ok["message"], ok["meta"]), ("PNG", 64, 32, (43, 21), "Image loaded", "PNG · 64 × 32"))

    def test_bytes_declared_type_and_pixel_edges(self):
        w = web_ui
        self.assertEqual([w.photo_reject_bytes(n) for n in (0, 1, w.PHOTO_MAX_BYTES, w.PHOTO_MAX_BYTES + 1)], ["empty", None, None, "tooLargeBytes"])
        self.assertEqual(w.photo_decide(bytes(w.PHOTO_MAX_BYTES + 1))["outcome"], "rejected:tooLargeBytes")                      # the runtime case in cases.json
        self.assertEqual([w.photo_reject_size(*s) for s in ((8000, 5000), (8000, 5001), (10000, 10000), (1, 0), (0, 5), (-1, 5), (40_000_000, 1), (1, 40_000_001))],
                         [None, "tooManyPixels", "tooManyPixels", "undecodable", "undecodable", "undecodable", None, "tooManyPixels"])
        png = photo_file("png_markers_64x32")
        self.assertTrue(w.photo_decide(png, photo_pillow_engine, "image/png")["ok"])
        self.assertTrue(w.photo_decide(png, photo_pillow_engine, "")["ok"])
        self.assertTrue(w.photo_decide(png, photo_pillow_engine, "image/x-unknown")["ok"])
        for declared in ("application/octet-stream", "text/plain", "video/mp4"):
            refused = w.photo_decide(png, photo_pillow_engine, declared)
            self.assertEqual((refused["outcome"], refused["reason"], refused["message"]), ("rejected:undecodable", "unsupportedFormat", "That image format could not be decoded."))
        self.assertEqual(w.photo_decide(b"", None, "application/pdf")["reason"], "unsupportedFormat")                           # the declared type is looked at first, as in Flutter
        self.assertEqual(w.photo_decide(w.photo_png(10000, 10000), lambda d: (_ for _ in ()).throw(AssertionError("decoded before the pixel budget")))["outcome"], "rejected:tooManyPixels")
        self.assertEqual(w.photo_decide(png, lambda d: (9000, 9000))["outcome"], "rejected:tooManyPixels")                      # an engine size over budget, as for HEIC
        self.assertEqual(w.photo_decide(png, lambda d: (0, 0))["outcome"], "rejected:undecodable")
        self.assertEqual(w.photo_decide(bytes([7, 7, 7]), lambda d: (4, 4), "image/avif")["format"], "AVIF")                     # no magic bytes: the declared type names it
        self.assertEqual(w.photo_decide(bytes([7, 7, 7]), lambda d: (4, 4))["format"], "IMAGE")
        self.assertEqual(w.photo_decide(photo_file("heic_ftyp_heic"))["message"], w.PHOTO_MESSAGES["heicUnsupported"])
        self.assertEqual(sorted(w.PHOTO_MESSAGES), sorted(set(w.PHOTO_MESSAGES)))
        for rejection in ("empty", "tooLargeBytes", "tooManyPixels", "undecodable", "heicConversionFailed"):
            failure = w.photo_failure(rejection)
            self.assertIn(failure["reason"], w.PHOTO_MESSAGES)
            self.assertIn(failure["outcome"], w.PHOTO_OUTCOMES)

    def test_document_size_golden_values_and_exact_arithmetic(self):
        from fractions import Fraction
        w = web_ui
        self.assertEqual([w.photo_document_size(*s) for s in ((64, 32), (1, 1), (2, 2), (3, 3), (1080, 1920), (1920, 1080), (8000, 6000), (6000, 8000), (24576, 3), (4096, 4096), (40000000, 1))],
                         [(43, 21), (1, 1), (1, 1), (2, 2), (720, 1280), (1280, 720), (4096, 3072), (3072, 4096), (4096, 1), (2731, 2731), (4096, 1)])

        def exact(width, height):                                                         # the same rules in exact rational arithmetic
            half_up = lambda x: math.floor(x + Fraction(1, 2))
            tw, th = (min(max(half_up(Fraction(2, 3) * v), 1), v) for v in (width, height))
            long_edge = max(tw, th)
            if long_edge > 4096:
                fit = Fraction(4096, long_edge)
                tw, th = (min(max(half_up(v * fit), 1), s) for v, s in ((tw, width), (th, height)))
            return tw, th
        rng = random.Random(3)
        sizes = [(a, b) for a in (1, 2, 3, 4, 5, 63, 64, 1000, 4095, 4096, 4097, 6143, 6144, 6145, 7000) for b in (1, 2, 3, 7, 64, 1000, 4096, 6144, 9000)]
        sizes += [(rng.randint(1, 12000), rng.randint(1, 12000)) for _ in range(3000)]
        for size in sizes:
            self.assertEqual(w.photo_document_size(*size), exact(*size), size)
            tw, th = w.photo_document_size(*size)
            self.assertTrue(1 <= tw <= size[0] and 1 <= th <= size[1] and max(tw, th) <= 4096, size)


class PhotoOrientationTests(unittest.TestCase):
    """EXIF Orientation 1-8: the table, the turn the page applies, and Pillow's own transposes as the oracle."""

    def test_the_operation_table_from_the_dart_tests(self):
        w = web_ui
        self.assertEqual([w.photo_orientation_op(o) for o in (0, 1, 9, -1, True, None, 2.0)], [None] * 7)
        self.assertEqual([tuple(w.photo_orientation_op(o).values()) for o in range(2, 9)],
                         [("flipX", 0, True, False), ("rotate", 180, False, False), ("flipY", 0, False, True), ("transpose", 90, True, False),
                          ("rotate", 90, False, False), ("transverse", -90, True, False), ("rotate", -90, False, False)])
        self.assertEqual([w.photo_oriented_size(64, 32, o) for o in range(1, 9)], [(64, 32)] * 4 + [(32, 64)] * 4)

    def test_the_matrix_turns_a_picture_like_pillows_transposes(self):
        from PIL import Image
        methods = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                   6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
        for width, height in ((5, 3), (1, 1), (2, 7), (64, 32)):
            image = Image.new("RGB", (width, height))
            image.putdata([(x * 3 % 256, y * 5 % 256, (x + y * width) % 256) for y in range(height) for x in range(width)])
            for orientation in range(1, 9):
                expected = image if orientation == 1 else image.transpose(methods[orientation])
                a, b, c, d, e, f = web_ui.photo_orientation_matrix(orientation, width, height)
                self.assertEqual(expected.size, web_ui.photo_oriented_size(width, height, orientation))
                for y in range(height):
                    for x in range(width):
                        tx, ty = math.floor(a * (x + .5) + c * (y + .5) + e), math.floor(b * (x + .5) + d * (y + .5) + f)
                        self.assertEqual(expected.getpixel((tx, ty)), image.getpixel((x, y)), (width, height, orientation, x, y))
        self.assertEqual(web_ui.photo_orientation_matrix(0, 4, 4), (1, 0, 0, 1, 0, 0))
        self.assertEqual(web_ui.photo_orientation_matrix(99, 4, 4), (1, 0, 0, 1, 0, 0))

    def test_neutralised_files_turned_by_the_matrix_equal_pillows_exif_transpose(self):
        import io
        from PIL import Image, ImageOps
        for orientation in range(1, 9):
            data = photo_file(f"jpeg_exif_orientation_{orientation}_markers_64x32")
            with Image.open(io.BytesIO(data)) as original:
                expected = ImageOps.exif_transpose(original).convert("RGB")
            with Image.open(io.BytesIO(web_ui.photo_neutralize_orientation(data))) as stored:
                stored = stored.convert("RGB")
            width, height = stored.size
            a, b, c, d, e, f = web_ui.photo_orientation_matrix(orientation, width, height)
            upright = Image.new("RGB", web_ui.photo_oriented_size(width, height, orientation))
            for y in range(height):
                for x in range(width):
                    upright.putpixel((math.floor(a * (x + .5) + c * (y + .5) + e), math.floor(b * (x + .5) + d * (y + .5) + f)), stored.getpixel((x, y)))
            with self.subTest(orientation=orientation):
                self.assertEqual(upright.size, expected.size)
                self.assertEqual(upright.tobytes(), expected.tobytes())


class PhotoGeometryTests(unittest.TestCase):
    """Rectangles, shapes and hit targets: the Dart tests' numbers, and the identities that hold for every box."""

    def test_the_dart_rectangle_tests(self):
        w, R = web_ui, web_ui.photo_rect
        self.assertEqual(w.photo_rect_sanitized(w.PHOTO_INITIAL_RECT), R(0.2, 0.2, 0.8, 0.8))
        tiny = w.photo_rect_sanitized(R(0.1, 0.1, 0.12, 0.11))
        self.assertGreaterEqual(tiny["right"] - tiny["left"], 0.04 - 1e-12)
        self.assertGreaterEqual(tiny["bottom"] - tiny["top"], 0.04 - 1e-12)
        moved = w.photo_rect_translated(w.PHOTO_INITIAL_RECT, 0.9, -0.5)
        self.assertTrue(moved["left"] >= 0 and moved["top"] >= 0 and moved["right"] <= 1 and moved["bottom"] <= 1)
        resized = w.photo_rect_resized(w.PHOTO_INITIAL_RECT, "bottomRight", -0.1, -0.1)
        for key, value in (("right", 0.7), ("bottom", 0.7), ("left", 0.2), ("top", 0.2)):
            self.assertAlmostEqual(resized[key], value, places=9)
        self.assertEqual(w.photo_rect_from_diagonal(.5, .5, .8, .9), R(.5, .5, .8, .9))
        self.assertEqual(w.photo_rect_from_diagonal(.5, .5, .2, .1), R(.2, .1, .5, .5))
        self.assertEqual(w.photo_rect_from_diagonal(.5, .5, .7, .2), R(.5, .2, .7, .5))
        self.assertEqual(w.photo_rect_from_diagonal(.5, .5, .1, .75), R(.1, .5, .5, .75))
        self.assertEqual(w.photo_rect_from_diagonal(-1, 2, 3, -4), R(0, 0, 1, 1))
        self.assertEqual(w.photo_rect_text(R(0.2, 0.2, 0.8, 0.8)), "left: 0.2000\ntop: 0.2000\nright: 0.8000\nbottom: 0.8000")
        self.assertEqual(w.photo_rect_csv(R(1 / 3, 0.00005, 0.99995, 1)), "0.3333, 0.0001, 1.0000, 1.0000")
        with self.assertRaises(ValueError):
            w.photo_rect_resized(w.PHOTO_INITIAL_RECT, "middle", 0, 0)

    def test_the_dart_geometry_table(self):
        w, R = web_ui, web_ui.photo_rect
        cases = [(R(0.2, 0.2, 0.8, 0.8), [(0.5, 0.2), (0.8, 0.5), (0.5, 0.8), (0.2, 0.5)], (0.5, 0.5, 0.3), [(0.5, 0.2), (0.8, 0.8), (0.2, 0.8)], [(0.65, 0.5), (0.5, 0.8), (0.35, 0.5)], (0.5, 0.5)),
                 (R(0.1, 0.25, 0.9, 0.55), [(0.5, 0.25), (0.9, 0.4), (0.5, 0.55), (0.1, 0.4)], (0.5, 0.4, 0.15), [(0.5, 0.25), (0.9, 0.55), (0.1, 0.55)], [(0.7, 0.4), (0.5, 0.55), (0.3, 0.4)], None)]
        pairs = lambda points: [(p["x"], p["y"]) for p in points]
        for box, rect_mids, circle, vertices, tri_mids, crossing in cases:
            for got, want in zip(pairs(w.photo_rect_edge_midpoints(box)) + pairs(w.photo_triangle(box)) + pairs(w.photo_triangle_midpoints(box)), rect_mids + vertices + tri_mids):
                self.assertAlmostEqual(got[0], want[0], places=9)
                self.assertAlmostEqual(got[1], want[1], places=9)
            c = w.photo_circle(box)
            for got, want in zip((c["cx"], c["cy"], c["radius"]), circle):
                self.assertAlmostEqual(got, want, places=9)
            hit = w.photo_segment_intersection(box["left"], box["top"], box["right"], box["bottom"], box["left"], box["bottom"], box["right"], box["top"])
            if crossing:
                self.assertAlmostEqual(hit["x"], crossing[0], places=9)
                self.assertAlmostEqual(hit["y"], crossing[1], places=9)
        hit = w.photo_segment_intersection(0, 0, 1, 1, 0, 1, 1, 0)
        self.assertEqual((hit["x"], hit["y"]), (0.5, 0.5))
        self.assertIsNone(w.photo_segment_intersection(0, 0, 1, 0, 0, 1, 1, 1))              # parallel
        self.assertIsNone(w.photo_segment_intersection(0, 0, 1, 1, 2, 0, 3, 0))              # misses
        box = R(0.2, 0.2, 0.8, 0.8)
        self.assertIn("radius:", w.photo_describe(box, "circle"))
        self.assertIn("apex:", w.photo_describe(box, "triangle"))
        self.assertEqual(w.photo_describe(box, "rectangle").splitlines()[0:2], ["shape: rectangle", "left: 0.2000"])
        self.assertEqual(w.photo_describe(box, "circle"), "shape: circle\ncx: 0.5000\ncy: 0.5000\nradius: 0.3000")
        with self.assertRaises(ValueError):
            w.photo_describe(box, "star")
        self.assertFalse(w.photo_shape_contains(box, "circle", 0.21, 0.21))
        self.assertTrue(w.photo_shape_contains(box, "circle", 0.5, 0.5))
        self.assertFalse(w.photo_shape_contains(box, "triangle", 0.21, 0.21))
        self.assertTrue(w.photo_shape_contains(box, "triangle", 0.5, 0.5))
        self.assertTrue(w.photo_shape_contains(box, "triangle", 0.33, 0.5, slop=0.05))      # the stroke grab: 0.018 outside the left edge
        self.assertFalse(w.photo_shape_contains(box, "triangle", 0.2, 0.5, slop=0.05))      # 0.134 outside it
        self.assertTrue(w.photo_shape_contains(box, "rectangle", 0.19, 0.5, slop=0.02))

    def test_hit_targets_and_the_export_numbers(self):
        w, R = web_ui, web_ui.photo_rect
        box = R(0.25, 0.25, 0.75, 0.75)                                                    # 400 x 400 canvas: the frame spans 100..300
        grabbed = {(100, 100): "topLeft", (301, 99): "topRight", (95, 305): "bottomLeft", (310, 300): "bottomRight", (100, 200): "left", (300, 200): "right", (200, 100): "top",
                   (200, 300): "bottom", (200, 200): "move", (110, 110): "topLeft", (104, 200): "left", (150, 150): "move", (50, 50): None, (200, 340): None}
        for point, handle in grabbed.items():
            self.assertEqual(w.photo_hit_handle(box, 400, 400, *point), handle, point)
        tiny = R(0.5, 0.5, 0.54, 0.54)                                                     # 16 x 16: every point is within 18 of some corner; corners are tried in order
        self.assertEqual(w.photo_hit_handle(tiny, 400, 400, 208, 208), "topLeft")
        self.assertEqual(w.photo_hit_handle(tiny, 400, 400, 215, 215), "topRight")
        self.assertEqual(w.photo_hit_handle(R(0.5, 0.5, 0.58, 0.58), 400, 400, 230, 230), "bottomRight")
        frames = [{"id": "bottom", "rect": R(0.2, 0.2, 0.8, 0.8), "shape": "rectangle"}, {"id": "top", "rect": R(0.15, 0.15, 0.45, 0.45), "shape": "rectangle"}]
        self.assertEqual(w.photo_hit_frame(frames, 400, 300, 88, 66)["id"], "top")
        self.assertEqual(w.photo_hit_frame(frames, 400, 300, 300, 200)["id"], "bottom")
        self.assertIsNone(w.photo_hit_frame(frames, 400, 300, 10, 10))
        self.assertIsNone(w.photo_hit_frame(frames, 0, 300, 10, 10))
        stamps = [{"id": "a", "x": 0.5, "y": 0.5, "scale": 1}, {"id": "b", "x": 0.5, "y": 0.5, "scale": 3}]
        self.assertEqual(w.photo_hit_stamp(stamps, 400, 300, 210, 150)["id"], "b")           # both are hit: topmost wins
        self.assertEqual(w.photo_hit_stamp(stamps[:1], 400, 300, 200 + 18, 150)["id"], "a")  # at least 18 pixels
        self.assertIsNone(w.photo_hit_stamp(stamps[:1], 400, 300, 200 + 18.5, 150))
        self.assertEqual(w.photo_hit_stamp(stamps[1:], 400, 300, 200 + 44, 150)["id"], "b")  # 300 * 0.05 * 3 = 45
        self.assertEqual([w.photo_export_size(*s) for s in ((760, 280), (400.25, 300.2), (0.1, 0.1), (3000, 100), (1, 1))], [(1520, 560), (801, 600), (1, 1), (4096, 200), (2, 2)])
        self.assertEqual(w.photo_contain_rect(100, 50, 400, 400), (0, 100, 400, 200))
        self.assertEqual(w.photo_contain_rect(50, 100, 400, 400), (100, 0, 200, 400))
        self.assertEqual(w.photo_contain_rect(200, 100, 400, 200), (0, 0, 400, 200))
        self.assertEqual([w.photo_stamp_px(400, 300, s) for s in (1, 0.1, 0.4, 3, 9)], [30.0, 12.0, 12.0, 90.0, 90.0])


class PhotoStudioTests(unittest.TestCase):
    """Undo history and the editing state machine, with the Dart history and canvas tests as the oracle."""

    @staticmethod
    def state(**changes):
        return {"image": None, "frames": [], "selected_frame": None, "draft_color": "#7e57c2", "draft_shape": None, "stamps": [], "selected_stamp": None, "stamp_scale": 1, **changes}

    def test_the_dart_history_tests(self):
        h = web_ui.PhotoHistory()
        before = self.state(frames=[{"id": "frame-a", "rect": web_ui.PHOTO_INITIAL_RECT, "shape": "rectangle", "color": "#7e57c2"}])
        after = {**before, "frames": [{**before["frames"][0], "rect": web_ui.photo_rect(.1, .1, .9, .9)}], "selected_frame": "frame-a"}
        h.begin_gesture(before)
        self.assertTrue(h.end_gesture(after))
        self.assertEqual((h.depth, h.can_undo), (1, True))
        self.assertEqual(h.undo(after), before)
        self.assertEqual((h.depth, h.can_redo), (0, True))
        state = self.state(draft_color="#e53935")
        h = web_ui.PhotoHistory()
        h.begin_gesture(state)
        self.assertFalse(h.end_gesture(state))
        self.assertFalse(h.record_change(state, state))
        self.assertEqual((h.depth, h.can_undo), (0, False))
        base, h, current = self.state(), web_ui.PhotoHistory(), None
        for i in range(25):
            self.assertTrue(h.record_change({**base, "stamp_scale": 1.0 + i * 0.01}, {**base, "stamp_scale": 1.0 + (i + 1) * 0.01}))
            current = {**base, "stamp_scale": 1.0 + (i + 1) * 0.01}
        self.assertEqual(h.depth, 20)                                                      # capped at 20 entries
        first = h.undo(current)
        self.assertAlmostEqual(first["stamp_scale"], 1.24, places=9)
        oldest, cursor = None, first
        while h.can_undo:
            oldest = cursor = h.undo(cursor)
        self.assertAlmostEqual(oldest["stamp_scale"], 1.05, places=9)
        self.assertEqual(h.depth, 0)
        h = web_ui.PhotoHistory()
        for i in range(20):
            h.record_change({**base, "stamp_scale": 1.0 + i * 0.01}, {**base, "stamp_scale": 1.0 + (i + 1) * 0.01})
        same = {**base, "stamp_scale": 9}
        self.assertFalse(h.record_change(same, same))
        h.begin_gesture(same)
        self.assertFalse(h.end_gesture(same))
        self.assertEqual(h.depth, 20)
        a, b, c = (self.state(draft_shape=s) for s in (None, "circle", "triangle"))        # multi undo, redo, and a new edit clears redo
        h = web_ui.PhotoHistory()
        self.assertTrue(h.record_change(a, b) and h.record_change(b, c))
        self.assertEqual((h.undo(c)["draft_shape"], h.undo(b)["draft_shape"], h.undo(a)), ("circle", None, None))
        h = web_ui.PhotoHistory()
        h.record_change(a, b), h.record_change(b, c)
        self.assertEqual(h.undo(c), b)
        self.assertTrue(h.can_redo)
        self.assertEqual(h.redo(b), c)
        self.assertFalse(h.can_redo)
        self.assertEqual(h.undo(c), b)
        d = self.state(draft_shape="rectangle")
        self.assertTrue(h.record_change(b, d))
        self.assertEqual((h.can_redo, h.redo(d)), (False, None))
        stale = self.state(frames=[{"id": "x"}])
        h = web_ui.PhotoHistory()
        h.begin_gesture(stale)
        h.undo(stale)                                                                      # undo and redo drop an open gesture
        self.assertFalse(h.end_gesture(self.state()))
        h.clear()
        self.assertEqual((h.depth, h.can_undo, h.can_redo), (0, False, False))

    def test_dragging_makes_a_frame_from_the_origin_in_every_direction(self):
        w = web_ui
        s = w.PhotoStudio(400, 300)
        s.set_shape("rectangle")
        s.pointer_down(1, 20, 15)
        s.pointer_move(1, 180, 165)
        s.pointer_up(1)
        (frame,) = s.state["frames"]
        self.assertEqual((frame["id"], frame["shape"], frame["color"], s.state["selected_frame"]), ("frame-1", "rectangle", "#7e57c2", "frame-1"))
        self.assertAlmostEqual(frame["rect"]["left"], 0.05, places=9)
        self.assertAlmostEqual(frame["rect"]["top"], 0.05, places=9)
        self.assertAlmostEqual(frame["rect"]["right"], 0.45, places=9)
        self.assertAlmostEqual(frame["rect"]["bottom"], 0.55, places=9)
        s = w.PhotoStudio(400, 300)                                                         # up and left from the centre, with another frame away in a corner
        s.state = self.state(draft_shape="rectangle", frames=[{"id": "away", "rect": w.photo_rect(.8, .8, .95, .95), "shape": "rectangle", "color": "#7e57c2"}])
        s.pointer_down(1, 200, 150)
        s.pointer_move(1, 80, 60)
        s.pointer_up(1)
        created = s.state["frames"][-1]["rect"]
        self.assertEqual(len(s.state["frames"]), 2)
        self.assertAlmostEqual(created["right"], 0.5, places=9)
        self.assertAlmostEqual(created["bottom"], 0.5, places=9)
        self.assertLess(created["left"], 0.35)
        self.assertLess(created["top"], 0.35)
        s = w.PhotoStudio(400, 300)                                                         # no tool: an empty drag creates nothing
        s.pointer_down(1, 40, 30)
        s.pointer_move(1, 160, 120)
        s.pointer_up(1)
        self.assertEqual((s.state["frames"], s.history.depth), ([], 0))
        s = w.PhotoStudio(400, 300)
        s.set_shape("circle")
        for start, end in (((20, 15), (120, 90)), ((220, 165), (360, 270))):
            s.pointer_down(1, *start)
            s.pointer_move(1, *end)
            s.pointer_up(1)
        self.assertEqual([f["shape"] for f in s.state["frames"]], ["circle", "circle"])
        self.assertEqual(s.state["selected_frame"], s.state["frames"][-1]["id"])
        s.pointer_down(1, 100, 75)                                                         # a click does not move: a small drag below 4 pixels is a tap
        s.pointer_move(1, 102, 76)
        s.pointer_up(1)
        self.assertEqual(s.state["selected_frame"], s.state["frames"][0]["id"])

    def test_moving_resizing_and_overlaps(self):
        w, R = web_ui, web_ui.photo_rect
        s = w.PhotoStudio(400, 300)
        s.state = self.state(frames=[{"id": "f1", "rect": R(.2, .2, .8, .8), "shape": "rectangle", "color": "#7e57c2"}], selected_frame="f1")
        s.pointer_down(1, 200, 150)
        s.pointer_move(1, 248, 174)
        s.pointer_up(1)
        moved = s.state["frames"][0]["rect"]
        self.assertAlmostEqual(moved["left"], 0.2 + 0.12, places=9)
        self.assertAlmostEqual(moved["top"], 0.2 + 0.08, places=9)
        self.assertEqual(s.history.depth, 1)
        self.assertTrue(s.undo())
        self.assertEqual(s.state["frames"][0]["rect"], R(.2, .2, .8, .8))
        s.pointer_down(1, 320, 240)                                                        # the bottom-right corner of the frame
        s.pointer_move(1, 280, 210)
        s.pointer_up(1)
        grown = s.state["frames"][0]["rect"]
        self.assertAlmostEqual(grown["right"], 0.8 - 40 / 400, places=9)
        self.assertAlmostEqual(grown["bottom"], 0.8 - 30 / 300, places=9)
        s = w.PhotoStudio(400, 300)                                                         # a buried selected frame's handle does not steal the gesture
        s.state = self.state(frames=[{"id": "bottom", "rect": R(.2, .2, .8, .8), "shape": "rectangle", "color": "#7e57c2"},
                                     {"id": "top", "rect": R(.15, .15, .45, .45), "shape": "rectangle", "color": "#7e57c2"}], selected_frame="bottom")
        s.pointer_down(1, 88, 66)
        s.pointer_move(1, 112, 84)
        s.pointer_move(1, 136, 102)
        s.pointer_up(1)
        by_id = {f["id"]: f for f in s.state["frames"]}
        self.assertEqual((s.state["selected_frame"], by_id["bottom"]["rect"]), ("top", R(.2, .2, .8, .8)))
        self.assertGreater(by_id["top"]["rect"]["left"], 0.15)
        self.assertGreater(by_id["top"]["rect"]["top"], 0.15)
        s = w.PhotoStudio(400, 300)                                                         # a circle's empty corner defers to the rectangle under it
        s.state = self.state(frames=[{"id": "bottom", "rect": R(.1, .1, .9, .9), "shape": "rectangle", "color": "#7e57c2"},
                                     {"id": "topCircle", "rect": R(.2, .2, .8, .8), "shape": "circle", "color": "#7e57c2"}], selected_frame="topCircle")
        s.pointer_down(1, 88, 66)
        s.pointer_move(1, 128, 96)
        s.pointer_up(1)
        by_id = {f["id"]: f for f in s.state["frames"]}
        self.assertEqual(s.state["selected_frame"], "bottom")
        self.assertGreater(by_id["bottom"]["rect"]["left"], 0.1)
        self.assertEqual(by_id["topCircle"]["rect"], R(.2, .2, .8, .8))

    def test_stamps_taps_spray_and_one_undo_step_per_gesture(self):
        from unittest import mock
        w = web_ui
        s = w.PhotoStudio(400, 400)
        s.arm_stamp("⭐")
        for point in ((80, 120), (320, 280)):
            s.pointer_down(1, *point)
            s.pointer_up(1)
        self.assertEqual([x["emoji"] for x in s.state["stamps"]], ["⭐", "⭐"])
        self.assertEqual((s.state["stamps"][0]["x"], s.state["stamps"][0]["y"], s.pending_emoji), (0.2, 0.3, "⭐"))
        self.assertEqual((s.state["selected_stamp"], s.history.depth), ("stamp-2", 2))
        s = w.PhotoStudio(400, 400)                                                         # the spray places a stamp again only 28 pixels on
        s.arm_stamp("🔥")
        s.pointer_down(1, 100, 100)
        s.pointer_move(1, 120, 100)
        s.pointer_move(1, 127.9, 100)
        self.assertEqual(len(s.state["stamps"]), 1)
        s.pointer_move(1, 128, 100)
        self.assertEqual(len(s.state["stamps"]), 2)
        s.pointer_up(1)
        s = w.PhotoStudio(400, 400)                                                         # a press that moves less than 4 pixels is still a tap
        s.arm_stamp("🔥")
        s.pointer_down(1, 100, 100)
        s.pointer_move(1, 103.9, 100)
        s.pointer_up(1)
        self.assertEqual((len(s.state["stamps"]), s.state["stamps"][0]["x"]), (1, 0.25))
        s = w.PhotoStudio(400, 400)
        s.arm_stamp("🔥")
        s.pointer_down(1, 100, 100)
        s.pointer_move(1, 104, 100)
        s.pointer_up(1)
        self.assertEqual(len(s.state["stamps"]), 1)                                         # a drag of 4 or more starts at the press point and sprays from there
        self.assertEqual(s.state["stamps"][0]["x"], 0.25)
        s = w.PhotoStudio(400, 400)
        s.arm_stamp("🔥")
        with mock.patch.object(s.history, "begin_gesture", wraps=s.history.begin_gesture) as begun, mock.patch.object(s.history, "end_gesture", wraps=s.history.end_gesture) as ended:
            s.pointer_down(1, 40, 200)
            for x in (140, 260, 360):
                s.pointer_move(1, x, 200)
            s.pointer_up(1)
        self.assertGreaterEqual(len(s.state["stamps"]), 4)
        self.assertEqual({x["emoji"] for x in s.state["stamps"]}, {"🔥"})
        self.assertEqual((begun.call_count, ended.call_count, s.history.depth), (1, 1, 1))     # one transaction, one undo step
        gaps = [s.state["stamps"][i + 1]["x"] * 400 - s.state["stamps"][i]["x"] * 400 for i in range(len(s.state["stamps"]) - 1)]
        self.assertTrue(all(g >= 28 - 1e-9 for g in gaps), gaps)
        self.assertTrue(s.undo())
        self.assertEqual(s.state["stamps"], [])
        self.assertTrue(s.redo())
        self.assertEqual(len(s.state["stamps"]), len(gaps) + 1)
        s = w.PhotoStudio(400, 400)                                                         # cancelling commits what was placed, like lifting the pointer
        s.arm_stamp("⭐")
        s.pointer_down(7, 40, 40)
        s.pointer_move(7, 140, 40)
        s.pointer_cancel(7)
        self.assertEqual((len(s.state["stamps"]) >= 2, s.history.depth, s.history.can_undo), (True, 1, True))
        s.pointer_down(7, 300, 300)                                                         # the next tap is its own step
        s.pointer_up(7)
        self.assertEqual(s.history.depth, 2)

    def test_dragging_a_stamp_scale_selection_and_editing_actions(self):
        w, R = web_ui, web_ui.photo_rect
        s = w.PhotoStudio(400, 400)
        s.arm_stamp("⭐")
        s.pointer_down(1, 200, 200)
        s.pointer_up(1)
        s.arm_stamp("⭐")                                                                   # arming the armed one disarms it
        self.assertIsNone(s.pending_emoji)
        depth = s.history.depth
        s.set_stamp_scale(2)
        self.assertEqual((s.state["stamps"][0]["scale"], s.state["stamp_scale"], s.history.depth), (2, 2, depth))      # the slider is not an undo step
        s.set_stamp_scale(99)
        self.assertEqual(s.state["stamps"][0]["scale"], 3)
        s.pointer_down(2, 200, 200)                                                         # drag the stamp
        s.pointer_move(2, 300, 100)
        s.pointer_up(2)
        self.assertEqual((s.state["stamps"][0]["x"], s.state["stamps"][0]["y"]), (0.75, 0.25))
        s.pointer_down(2, 300, 100)                                                         # outside the canvas is clamped
        s.pointer_move(2, 900, -50)
        s.pointer_up(2)
        self.assertEqual((s.state["stamps"][0]["x"], s.state["stamps"][0]["y"]), (1.0, 0.0))
        s.set_shape("triangle")
        s.arm_stamp("🍀")
        self.assertIsNone(s.state["draft_shape"])                                           # arming drops the frame tool
        s.set_shape("triangle")
        self.assertIsNone(s.pending_emoji)                                                  # choosing a tool drops the stamp
        with self.assertRaises(ValueError):
            s.set_shape("star")
        s.pointer_down(1, 20, 20)
        s.pointer_move(1, 120, 120)
        s.pointer_up(1)
        frame_id = s.state["selected_frame"]
        s.set_color("#e53935")
        self.assertEqual(([f["color"] for f in s.state["frames"] if f["id"] == frame_id], s.state["draft_color"]), (["#e53935"], "#e53935"))
        depth = s.history.depth
        s.set_color("#e53935")
        self.assertEqual(s.history.depth, depth)                                            # nothing changed: no step
        s.nudge(0.01, 0.02)
        s.reset_selected_frame()
        self.assertEqual(s.state["frames"][0]["rect"], R(.2, .2, .8, .8))
        s.delete_selected_frame()
        self.assertEqual((s.state["frames"], s.state["selected_frame"]), ([], None))
        s.delete_selected_frame()
        s.set_image(7)
        self.assertEqual(s.state["image"], 7)
        while s.undo():
            pass
        self.assertEqual((s.state["frames"], s.state["image"], s.history.can_redo), ([], None, True))
        s.set_shape("circle")
        s.undo()
        s.arm_stamp("⭐")
        s.set_shape("circle")
        s.undo()
        self.assertIsNone(s.pending_emoji if s.state["draft_shape"] else None)

    def test_any_pointer_sequence_keeps_the_state_sound(self):
        w = web_ui
        rng = random.Random(21)
        for run in range(60):
            s = w.PhotoStudio(rng.choice([400, 320, 760]), rng.choice([300, 280, 500]))
            ids = set()
            for _ in range(80):
                action = rng.choice(["down", "move", "move", "up", "cancel", "shape", "arm", "color", "undo", "redo", "nudge", "delete", "reset", "scale"])
                p = rng.choice([1, 2])
                x, y = rng.uniform(-30, s.width + 30), rng.uniform(-30, s.height + 30)
                if action == "down": s.pointer_down(p, x, y)
                elif action == "move": s.pointer_move(p, x, y)
                elif action == "up": s.pointer_up(p)
                elif action == "cancel": s.pointer_cancel(p)
                elif action == "shape": s.set_shape(rng.choice([None, "rectangle", "circle", "triangle"]))
                elif action == "arm": s.arm_stamp(rng.choice(["⭐", "🔥", " ", ""]))
                elif action == "color": s.set_color(rng.choice([c for _, c in w.PHOTO_COLORS]))
                elif action == "undo": s.undo()
                elif action == "redo": s.redo()
                elif action == "nudge": s.nudge(rng.uniform(-.2, .2), rng.uniform(-.2, .2))
                elif action == "delete": s.delete_selected_frame()
                elif action == "reset": s.reset_selected_frame()
                else: s.set_stamp_scale(rng.uniform(0, 5))
                state = s.state
                for frame in state["frames"]:
                    r = frame["rect"]
                    self.assertTrue(0 <= r["left"] <= r["right"] <= 1 and 0 <= r["top"] <= r["bottom"] <= 1, (run, r))
                    ids.add(frame["id"])
                self.assertEqual(len({f["id"] for f in state["frames"]}), len(state["frames"]))
                self.assertEqual(len({x["id"] for x in state["stamps"]}), len(state["stamps"]))
                self.assertTrue(state["selected_frame"] is None or any(f["id"] == state["selected_frame"] for f in state["frames"]))
                for stamp in state["stamps"]:
                    self.assertTrue(0 <= stamp["x"] <= 1 and 0 <= stamp["y"] <= 1 and 0.4 <= stamp["scale"] <= 3 or stamp["scale"] == 1)
                self.assertLessEqual(s.history.depth, 20)


class BtkAdapterTests(unittest.TestCase):
    """browser-test-kit's platform adapters, written from Python: valid by its contract, one per page that has state to observe."""

    @staticmethod
    def contract_errors(config):
        """browser-test-kit's tools/platform_adapter.load_adapter rules, restated (the contract is shared by fixture, not by import)."""
        from urllib.parse import urlsplit
        errors = []
        if config.get("schema") != "btk-platform-adapter/1":
            errors.append("schema")
        if not isinstance(config.get("id"), str) or not config["id"].replace("-", "").isalnum():
            errors.append("id")
        if not config.get("elements") or not all(isinstance(s, str) and s for s in config["elements"]):
            errors.append("elements")
        click = config.get("click", {})
        if not isinstance(click, dict) or not all(isinstance(click.get(k), str) and click[k] for k in ("target", "observe", "attribute")):
            errors.append("click")
            return errors
        if any(k not in click or (click[k] is not None and not isinstance(click[k], str)) for k in ("before", "after")):
            errors.append("before/after")
        if click["before"] == click["after"]:
            errors.append("distinct states")
        if click["target"] not in config["elements"]:
            errors.append("click target is an element")
        parts = urlsplit(config.get("url", ""))
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            errors.append("url")
        if len(set(config["elements"])) != len(config["elements"]):
            errors.append("duplicate elements")
        return errors

    def test_adapters_meet_the_contract_and_name_real_pages(self):
        w = web_ui
        pages = w.example_pages()
        self.assertEqual(sorted(w.BTK_ADAPTERS), ["web-ui-clipboard-shelf", "web-ui-composition-studio", "web-ui-coordinates", "web-ui-door", "web-ui-image-stamp", "web-ui-image-studio", "web-ui-irony", "web-ui-mcp-lab", "web-ui-mcp-send", "web-ui-pattern-run", "web-ui-patterns", "web-ui-photo-studio", "web-ui-playground", "web-ui-showcase", "web-ui-test-report"])
        for adapter_id in w.BTK_ADAPTERS:
            config = w.btk_adapter(adapter_id)
            with self.subTest(adapter_id):
                self.assertEqual(self.contract_errors(config), [])
                self.assertEqual(config["id"], adapter_id)
                self.assertIn("examples/" + w.BTK_ADAPTERS[adapter_id]["page"], pages)
                self.assertEqual(config["url"], w.btk_adapter_url(w.BTK_ADAPTERS[adapter_id]))
                self.assertTrue(config["url"].startswith("http://127.0.0.1:8000/examples/" + w.BTK_ADAPTERS[adapter_id]["page"]))
        self.assertEqual(w.btk_adapter("web-ui-door", "http://localhost:9/x.html")["url"], "http://localhost:9/x.html")
        self.assertEqual(w.btk_adapter("web-ui-irony")["url"], "http://127.0.0.1:8000/examples/playground.html#irony-title")
        self.assertEqual(w.btk_adapter("web-ui-door")["url"], "http://127.0.0.1:8000/examples/door.html")
        self.assertIsNot(w.btk_adapter("web-ui-door")["elements"], w.BTK_ADAPTERS["web-ui-door"]["elements"])      # a copy: callers cannot change the table
        with self.assertRaises(ValueError):
            w.btk_adapter("flutter-home")
        self.assertEqual(self.contract_errors({**w.btk_adapter("web-ui-door"), "url": "file:///x.html"}), ["url"])
        self.assertEqual(self.contract_errors({**w.btk_adapter("web-ui-door"), "click": {**w.BTK_ADAPTERS["web-ui-door"]["click"], "after": "0"}}), ["distinct states"])
        if shutil.which("python3") and (ROOT.parent / "browser-test-kit" / "tools" / "platform_adapter.py").exists():           # the real validator, when a clone is next to this one
            import importlib.util
            spec = importlib.util.spec_from_file_location("btk_platform_adapter", ROOT.parent / "browser-test-kit" / "tools" / "platform_adapter.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as directory:
                for adapter_id in w.BTK_ADAPTERS:
                    target = Path(directory) / (adapter_id + ".json")
                    target.write_text(json.dumps(w.btk_adapter(adapter_id)), encoding="utf-8")
                    self.assertEqual(module.load_adapter(target)["id"], adapter_id)

    def test_the_command_line_prints_them(self):
        def run(*args):
            return subprocess.run([sys.executable, "-S", "web_ui.py", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
        listed = run("--btk-adapter", "list")
        self.assertEqual((listed.returncode, listed.stdout.split()), (0, sorted(web_ui.BTK_ADAPTERS)))
        one = run("--btk-adapter", "web-ui-photo-studio", "--url", "http://127.0.0.1:9/p.html")
        self.assertEqual((one.returncode, json.loads(one.stdout)), (0, web_ui.btk_adapter("web-ui-photo-studio", "http://127.0.0.1:9/p.html")))
        bad = run("--btk-adapter", "nope")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("unknown adapter", bad.stderr)


def clip_png(width, height, rgba):
    pixels = bytes(rgba[i % len(rgba)] for i in range(width * 4)) * height
    return web_ui.photo_png(width, height, pixels)


CLIP_PIXELS = [255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 0, 0]
CLIP_IMAGE = base64.b64encode(clip_png(3, 1, CLIP_PIXELS)).decode()
CLIP_GREEN = base64.b64encode(clip_png(1, 1, [0, 255, 0, 255])).decode()
CLIP_URI = "data:image/png;base64," + CLIP_IMAGE


def clip_resolve(value):
    """Replace the ``@pad:N`` markers scenarios carry (a 32 MiB payload is not shipped around as text) with the real Base64."""
    if isinstance(value, str):
        return re.sub(r"@pad:(\d+)", lambda m: clip_padded(int(m.group(1))), value)
    if isinstance(value, list):
        return [clip_resolve(v) for v in value]
    if isinstance(value, dict):
        return {k: clip_resolve(v) for k, v in value.items()}
    return value


def clip_padded(size):
    """Base64 of the 3 x 1 PNG followed by zeros up to ``size`` bytes (a file at, and just over, the 32 MiB ceiling)."""
    data = bytearray(size)
    png = base64.b64decode(CLIP_IMAGE)
    data[:len(png)] = png
    return base64.b64encode(bytes(data)).decode()


class ClipBlob:
    def __init__(self, data, size=None):
        self.data, self.size = data, len(data) if size is None else size
        self.read_calls = 0

    def read(self):
        self.read_calls += 1
        return self.data


class ClipItem:
    def __init__(self, formats, calls):
        self.formats, self.types, self.calls, self.blobs = formats, [f["type"] for f in formats], calls, []

    def get_type(self, kind):
        self.calls["getType"] += 1
        fmt = next(f for f in self.formats if f["type"] == kind)
        if fmt.get("error"):
            raise web_ui.ClipboardFailure(fmt["error"])
        blob = ClipBlob(base64.b64decode(fmt.get("base64", "")), 32 * 1024 * 1024 + 1 if fmt.get("oversized") else None)
        self.blobs.append(blob)
        return blob


class ClipDouble:
    """The browser's clipboard as Ironmate's tests double it: optional readText and read, with injected failures and call counts."""

    def __init__(self, config):
        self.calls = {"read": 0, "readText": 0, "getType": 0}
        self.config = config
        if not config.get("noText"):
            self.read_text = self._read_text
        if not config.get("noRead"):
            self.read = self._read
        self.items = []

    def _read_text(self):
        self.calls["readText"] += 1
        if self.config.get("textError"):
            raise web_ui.ClipboardFailure(self.config["textError"])
        return self.config.get("text", "")

    def _read(self):
        self.calls["read"] += 1
        if self.config.get("readError"):
            raise web_ui.ClipboardFailure(self.config["readError"])
        self.items = [ClipItem(item["formats"], self.calls) for item in self.config.get("items", [])]
        return self.items


def clip_binary(base64_text=CLIP_IMAGE, kind="image/png", **more):
    return {"formats": [{"type": kind, "base64": base64_text, **more}]}


def clip_importer(data, mime):
    """Ironmate's importImageBytes in miniature: the bytes must be the declared type, decode, and stay within 4 megapixels."""
    from io import BytesIO
    from PIL import Image
    if web_ui._sniff_image_mime(data) != mime:
        raise ValueError("MIME mismatch")
    with Image.open(BytesIO(data)) as image:
        image.load()
        if image.width * image.height > 4 * 1024 * 1024:
            raise ValueError("over 4 MP")
    return True


def clip_scenarios():
    """Ironmate's tests/studio_clipboard.cjs scenarios: (name, config, expected error code or None)."""
    big, over = "@pad:33554432", "@pad:33554433"
    return [
        ("ordinary-text-and-PNG", {"text": "これは普通のメモです", "items": [clip_binary()]}, None),
        ("base64-of-nonimage-and-PNG", {"text": base64.b64encode(b"ordinary text").decode(), "items": [clip_binary()]}, None),
        ("image-Base64-wins-over-binary", {"text": CLIP_URI, "items": [clip_binary(CLIP_GREEN)]}, None),
        ("raw-image-Base64", {"text": CLIP_IMAGE, "noRead": True}, None),
        ("BOM-case-parameters-and-wrapping", {"text": "\ufeff DATA:IMAGE/PNG;charset=utf-8;BASE64,\n" + CLIP_IMAGE + "\n"}, None),
        ("invalid-image-data-URI-does-not-import-stale-PNG", {"text": "data:image/png;base64,!!!", "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("invalid-image-URI-header", {"text": "data:image/png,abc", "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("MIME-mismatch-text", {"text": CLIP_URI.replace("image/png", "image/jpeg"), "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("unsupported-image-URI", {"text": "data:image/gif;base64,R0lGODlh", "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("recognized-raw-image-with-invalid-padding", {"text": CLIP_IMAGE + "=", "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("undecodable-image-text", {"text": "data:image/png;base64," + base64.b64encode(bytes.fromhex("89504e470d0a1a0a000000000000")).decode(), "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("text-denied-image-readable", {"textError": "NotAllowedError", "items": [clip_binary()]}, None),
        ("text-failed-image-readable", {"textError": "UnknownError", "items": [clip_binary()]}, None),
        ("text-unsupported-image-readable", {"textError": "NotSupportedError", "items": [clip_binary()]}, None),
        ("binary-only-API", {"noText": True, "items": [clip_binary()]}, None),
        ("both-APIs-denied", {"textError": "NotAllowedError", "readError": "NotAllowedError"}, "clipboard-denied"),
        ("normal-text-image-denied", {"text": "memo", "readError": "NotAllowedError"}, "clipboard-denied"),
        ("security-error", {"noText": True, "readError": "SecurityError"}, "clipboard-denied"),
        ("API-absent", {"absent": True}, "clipboard-unsupported"),
        ("read-methods-absent", {"noText": True, "noRead": True}, "clipboard-unsupported"),
        ("API-NotSupportedError", {"noText": True, "readError": "NotSupportedError"}, "clipboard-unsupported"),
        ("API-other-failure", {"noText": True, "readError": "UnknownError"}, "clipboard-read-failed"),
        ("item-read-other-failure-means-a-bad-image", {"noText": True, "items": [{"formats": [{"type": "image/png", "error": "UnknownError"}]}]}, "clipboard-invalid-image"),
        ("item-read-not-supported", {"noText": True, "items": [{"formats": [{"type": "image/png", "error": "NotSupportedError"}]}]}, "clipboard-unsupported"),
        ("item-read-denied-wins-over-invalid", {"noText": True, "items": [{"formats": [{"type": "image/png", "error": "NotAllowedError"}, {"type": "image/jpeg", "base64": CLIP_IMAGE}]}]}, "clipboard-denied"),
        ("gif-item-is-no-image", {"items": [{"formats": [{"type": "image/gif", "base64": CLIP_IMAGE}]}]}, "clipboard-no-image"),
        ("text-only-no-image", {"text": "memo", "noRead": True}, "clipboard-no-image"),
        ("empty-clipboard", {}, "clipboard-no-image"),
        ("nonimage-items", {"items": [{"formats": [{"type": "text/html"}]}]}, "clipboard-no-image"),
        ("later-item-after-getType-denial", {"items": [{"formats": [{"type": "image/png", "error": "NotAllowedError"}]}, clip_binary()]}, None),
        ("later-format-after-corrupt-image", {"items": [{"formats": [{"type": "image/jpeg", "base64": CLIP_IMAGE}, {"type": "image/png", "base64": CLIP_IMAGE}]}]}, None),
        ("binary-MIME-mismatch", {"items": [clip_binary(CLIP_IMAGE, "image/jpeg")]}, "clipboard-invalid-image"),
        ("binary-over-32MiB-before-read", {"items": [{"formats": [{"type": "image/png", "base64": CLIP_IMAGE, "oversized": True}]}]}, "clipboard-invalid-image"),
        ("binary-exactly-32MiB", {"items": [clip_binary(big)]}, None),
        ("raw-Base64-exactly-32MiB", {"text": big}, None),
        ("raw-Base64-over-32MiB", {"text": over, "items": [clip_binary()]}, "clipboard-invalid-image"),
        ("URI-Base64-over-32MiB", {"text": "data:image/png;base64," + over}, "clipboard-invalid-image"),
        ("4MP-boundary-accepted", {"items": [clip_binary(base64.b64encode(clip_png(2048, 2048, [1, 2, 3, 255])).decode())]}, None),
        ("over-4MP-rejected", {"items": [clip_binary(base64.b64encode(clip_png(2049, 2048, [1, 2, 3, 255])).decode())]}, "clipboard-invalid-image"),
    ]


class ClipboardTests(unittest.TestCase):
    """The temporary clipboard, the clipboard read order and error codes, the shelf budget, and handing a PNG back as Base64."""

    def test_the_temporary_clipboard_like_the_dart_tests(self):
        w = web_ui
        entries, outcome = w.session_clip_save([], "one")
        entries, _ = w.session_clip_save(entries, "two")
        entries, _ = w.session_clip_save(entries, "one")
        self.assertEqual(entries, ["one", "two"])                                          # a repeat moves to the front, not listed twice
        self.assertEqual((w.session_clip_save(entries, "")[1], w.session_clip_save(entries, None)[1]), ("noText", "noText"))
        self.assertEqual(w.session_clip_save(entries, "x" * (w.SESSION_CLIP_MAX_CHARS + 1)), (["one", "two"], "tooLarge"))
        self.assertEqual(w.session_clip_save(entries, "x" * w.SESSION_CLIP_MAX_CHARS)[1], "saved")
        self.assertEqual(w.session_clip_save([], "saved user text"), (["saved user text"], "saved"))
        self.assertEqual((w.utf16_length("x"), w.utf16_length("é"), w.utf16_length("😀"), w.utf16_length("\ud800")), (1, 1, 2, 1))
        self.assertEqual(w.session_clip_save([], "😀" * 50000)[1], "saved")                  # 100,000 code units
        self.assertEqual(w.session_clip_save([], "😀" * 50001)[1], "tooLarge")               # 100,002 units, though only 50,001 characters
        many = []
        for number in range(40):
            many, _ = w.session_clip_save(many, f"entry {number}")
        self.assertEqual((len(many), many[0], many[-1]), (30, "entry 39", "entry 10"))      # the newest 30
        many, _ = w.session_clip_save(many, "entry 15")
        self.assertEqual((len(many), many[0], many[1]), (30, "entry 15", "entry 39"))
        self.assertEqual(many.count("entry 15"), 1)
        for key in ("save", "noText", "saved", "tooLarge", "readFailed", "copied", "copyFailed", "empty", "copy", "title", "subtitle"):
            self.assertTrue(w.SESSION_CLIP_MESSAGES[key])

    def test_ironmates_clipboard_scenarios(self):
        for name, config, code in clip_scenarios():
            config = clip_resolve(config)
            with self.subTest(name):
                clip = None if config.get("absent") else ClipDouble(config)
                result = web_ui.clipboard_pick(clip, clip_importer)
                if code:
                    self.assertEqual((result["ok"], result["code"]), (False, code), result)
                    self.assertIn(code, web_ui.CLIPBOARD_MESSAGES)
                else:
                    self.assertTrue(result["ok"], result)
                    self.assertIn(result["source"], ("text", "item"))
        for name, reads, read_texts, source in (("ordinary-text-and-PNG", 1, 1, "item"), ("image-Base64-wins-over-binary", 0, 1, "text"), ("invalid-image-data-URI-does-not-import-stale-PNG", 0, 1, None),
                                               ("empty-clipboard", 1, 1, None)):
            config = next(c for n, c, _ in clip_scenarios() if n == name)
            clip = ClipDouble(clip_resolve(config))
            result = web_ui.clipboard_pick(clip, clip_importer)
            self.assertEqual((clip.calls["read"], clip.calls["readText"], result.get("source")), (reads, read_texts, source), name)
        clip = ClipDouble(clip_resolve(next(c for n, c, _ in clip_scenarios() if n == "binary-over-32MiB-before-read")))
        web_ui.clipboard_pick(clip, clip_importer)
        self.assertEqual([blob.read_calls for item in clip.items for blob in item.blobs], [0])        # an oversized item is asked for but never read
        green = web_ui.clipboard_pick(ClipDouble({"text": CLIP_URI, "items": [clip_binary(CLIP_GREEN)]}), lambda d, m: len(d))
        self.assertEqual((green["source"], green["mime"], green["size"]), ("text", "image/png", len(base64.b64decode(CLIP_IMAGE))))

    def test_a_smaller_limit_refuses_unread(self):
        w = web_ui
        small = len(base64.b64decode(CLIP_IMAGE))
        self.assertTrue(w.clipboard_pick(ClipDouble({"text": CLIP_URI}), lambda d, m: 1, max_bytes=small)["ok"])
        self.assertEqual(w.clipboard_pick(ClipDouble({"text": CLIP_URI}), lambda d, m: 1, max_bytes=small - 1)["category"], "too_large")
        clip = ClipDouble({"items": [clip_binary()]})
        self.assertEqual(w.clipboard_pick(clip, lambda d, m: 1, max_bytes=small - 1), {"ok": False, "code": "clipboard-invalid-image", "category": "too_large"})
        self.assertEqual([blob.read_calls for blob in clip.items[0].blobs], [0])                        # the blob was looked at (its size) but never read
        self.assertTrue(w.clipboard_pick(ClipDouble({"items": [clip_binary()]}), lambda d, m: 1, max_bytes=small)["ok"])
        self.assertEqual(w.clipboard_pick(ClipDouble({"text": "memo"}), lambda d, m: 1, "shelf", 0)["source"], "plain")

    def test_the_shelf_keeps_text_and_reports_why_when_image_text_is_refused(self):
        w = web_ui
        pick = lambda config: w.clipboard_pick(ClipDouble(config), clip_importer, mode="shelf")
        self.assertEqual(pick({"text": "  a memo \n"}), {"ok": True, "source": "plain", "text": "a memo", "refused": None})
        self.assertEqual(pick({"text": "data:image/png;base64,!!!", "items": [clip_binary()]}), {"ok": True, "source": "plain", "text": "data:image/png;base64,!!!", "refused": "bad_base64"})
        self.assertEqual(pick({"text": CLIP_URI})["source"], "text")
        self.assertEqual(pick({"text": "memo", "items": [clip_binary()]})["source"], "item")                  # an image beats the text beside it
        self.assertEqual(pick({"textError": "NotAllowedError", "items": [clip_binary()]})["source"], "item")
        self.assertEqual(pick({"text": "memo", "readError": "NotAllowedError"})["source"], "plain")            # text still lands when the image read is refused
        self.assertEqual(pick({"text": "memo", "items": [clip_binary(CLIP_IMAGE, "image/jpeg")]})["code"], "clipboard-invalid-image")   # but a broken image is an error, not a note
        self.assertEqual(pick({"textError": "NotAllowedError", "readError": "NotAllowedError"})["code"], "clipboard-denied")
        self.assertEqual(pick({})["code"], "clipboard-no-image")
        self.assertEqual(pick({"noText": True, "noRead": True})["code"], "clipboard-unsupported")

    def test_the_shelf_budget_like_ironmates(self):
        w = web_ui
        self.assertEqual((w.SHELF_MAX_ITEMS, w.SHELF_MAX_TOTAL_BYTES), (20, 32 * 1024 * 1024))
        self.assertEqual([w.shelf_room(19, 0, 1), w.shelf_room(20, 0, 1), w.shelf_room(0, w.SHELF_MAX_TOTAL_BYTES - 5, 5), w.shelf_room(0, w.SHELF_MAX_TOTAL_BYTES - 5, 6),
                          w.shelf_room(0, 0, w.SHELF_MAX_TOTAL_BYTES), w.shelf_room(0, 0, w.SHELF_MAX_TOTAL_BYTES + 1)], [None, "full", None, "budget", None, "budget"])
        self.assertEqual([w.shelf_text_size(t) for t in ("", "a", "é", "あ", "😀", "\ud800", "aé あ😀")], [0, 1, 2, 3, 4, 3, 1 + 2 + 1 + 3 + 4])

    def test_a_png_goes_back_out_as_base64_and_in_again(self):
        import io
        from PIL import Image
        w = web_ui
        rng = random.Random(2)
        for width, height in ((1, 1), (3, 2), (17, 5), (64, 64)):
            buffer = io.BytesIO()
            Image.frombytes("RGB", (width, height), bytes(rng.randrange(256) for _ in range(3 * width * height))).save(buffer, "PNG")
            png = buffer.getvalue()
            for as_uri in (True, False):
                text = w.png_base64_text(png, as_uri)
                with self.subTest(size=(width, height), uri=as_uri):
                    self.assertEqual(text.startswith("data:image/png;base64,"), as_uri)
                    back = w.decode_image_text(text)
                    self.assertTrue(back["ok"])
                    self.assertEqual((base64.b64decode(back["data"]), back["mime"]), (png, "image/png"))
                    self.assertEqual(text.split(",")[-1], base64.b64encode(png).decode())                 # standard Base64, no URL-safe form, no padding change
                    self.assertTrue(w.clipboard_text_image(text)["ok"])
        with self.assertRaises(ValueError):
            w.png_base64_text(b"GIF89a")
        with self.assertRaises(ValueError):
            w.png_base64_text(b"\x89PNG\r\n\x1a\n" + bytes(w.SHELF_MAX_IMAGE_BYTES))
        self.assertTrue(w.png_base64_text(b"\x89PNG\r\n\x1a\n" + bytes(w.SHELF_MAX_IMAGE_BYTES - 8)))


class PlaygroundTests(unittest.TestCase):
    """The Counter Playground, the hold-to-repeat button and the Irony generator. The Dart tests of flutter_navigation_basic (counter_playground_controller_test,
    counter_battle_effect_test, counter_battle_effect_ui_test, hold_repeating_button_test, irony_generator_interaction_test) are the golden values."""

    def run_actions(self, *steps):
        state = web_ui.counter_state()
        for step in steps:
            state = web_ui.counter_apply(state, *step)
        return state

    def test_the_controller_dart_tests(self):
        state = web_ui.counter_state()
        self.assertEqual((state["counter"], state["step"], state["history"]), (0, 1, [0]))
        self.assertTrue(web_ui.counter_effect(0)["idle"])
        up = self.run_actions(("increment",))
        self.assertEqual((up["counter"], up["burst"]), (1, 1))
        self.assertEqual((web_ui.counter_effect(1)["heal"], web_ui.counter_effect(1)["amount"]), (False, 1))
        down = self.run_actions(("decrement",))
        self.assertEqual((down["counter"], web_ui.counter_effect(-1)["heal"], web_ui.counter_effect(-1)["amount"]), (-1, True, 1))
        ten = self.run_actions(*[("increment",)] * 10)
        self.assertEqual((ten["counter"], web_ui.counter_effect(10)["amount"]), (10, 10))
        cleared = self.run_actions(("change", 5), ("reset",))
        self.assertEqual(cleared["counter"], 0)
        self.assertTrue(web_ui.counter_effect(cleared["counter"])["idle"])

    def test_the_ends_clamp_and_do_not_bump_the_burst(self):
        top = self.run_actions(("change", web_ui.COUNTER_MAX))
        self.assertEqual(top["counter"], 100)
        self.assertEqual(web_ui.counter_apply(top, "increment"), top)
        self.assertEqual(web_ui.counter_apply(top, "change", 7), top)
        bottom = self.run_actions(("change", web_ui.COUNTER_MIN))
        self.assertEqual(bottom["counter"], -100)
        self.assertEqual(web_ui.counter_apply(bottom, "decrement"), bottom)
        step10 = self.run_actions(("step", 10), *[("increment",)] * 9)
        self.assertEqual((step10["counter"], step10["burst"]), (90, 9))
        over = web_ui.counter_apply(step10, "change", 50)
        self.assertEqual((over["counter"], over["burst"], over["history"][:2]), (100, 10, [100, 90]))

    def test_step_history_undo_and_restore_follow_the_controller(self):
        state = self.run_actions(("step", 5), ("increment",))
        self.assertEqual((state["counter"], state["history"]), (5, [5, 0]))
        state = web_ui.counter_apply(state, "decrement")
        self.assertEqual((state["counter"], state["history"]), (0, [0, 5, 0]))
        state = web_ui.counter_apply(state, "undo")
        self.assertEqual((state["counter"], state["history"]), (5, [5, 0]))
        state = web_ui.counter_apply(state, "restore", 2)
        self.assertEqual((state["counter"], state["history"]), (2, [2, 5, 0]))
        state = web_ui.counter_apply(state, "reset")
        self.assertEqual((state["counter"], state["history"]), (0, [0, 2, 5, 0]))

    def test_undo_records_nothing_and_bumps_the_burst_but_only_when_there_is_something_to_undo(self):
        first = web_ui.counter_state()
        self.assertEqual(web_ui.counter_apply(first, "undo"), first)
        moved = web_ui.counter_apply(first, "change", 3)
        back = web_ui.counter_apply(moved, "undo")
        self.assertEqual(back, {"counter": 0, "step": 1, "burst": 2, "history": [0]})
        self.assertEqual(web_ui.counter_apply(first, "reset"), first)
        self.assertEqual(web_ui.counter_apply(moved, "restore", 3), moved)
        self.assertEqual(web_ui.counter_apply(moved, "restore", 300)["counter"], 100)

    def test_the_history_keeps_the_eight_newest_values(self):
        state = web_ui.counter_state()
        for n in range(1, 13):
            state = web_ui.counter_apply(state, "change", 1)
            self.assertEqual(len(state["history"]), min(n + 1, web_ui.COUNTER_HISTORY))
        self.assertEqual(state["history"], [12, 11, 10, 9, 8, 7, 6, 5])
        for _ in range(7):
            state = web_ui.counter_apply(state, "undo")
        self.assertEqual((state["counter"], state["history"]), (5, [5]))
        self.assertEqual(web_ui.counter_apply(state, "undo"), state)

    def test_only_steps_one_five_and_ten_are_accepted(self):
        state = web_ui.counter_state()
        for value in (2, 0, -5, 11, True, 5.0, "5", None):
            self.assertEqual(web_ui.counter_apply(state, "step", value), state, value)
        self.assertEqual(web_ui.counter_apply(state, "step", 1), state)
        self.assertEqual([web_ui.counter_apply(state, "step", s)["step"] for s in web_ui.COUNTER_STEPS], [1, 5, 10])
        self.assertEqual(web_ui.counter_apply(web_ui.counter_apply(state, "step", 10), "step", 10)["burst"], 0)

    def test_bad_input_is_an_error_not_a_guess(self):
        state = web_ui.counter_state()
        for bad in (("nope",), ("change", "3"), ("change", 1.5), ("change", True), ("restore",), ("restore", None)):
            with self.assertRaises(ValueError, msg=bad):
                web_ui.counter_apply(state, *bad)
        for broken in ({**state, "history": []}, {**state, "history": [1]}, {**state, "history": [0, "x"]}, {**state, "counter": True}, {**state, "step": 1.0}):
            with self.assertRaises(ValueError, msg=broken):
                web_ui.counter_apply(broken, "increment")
        self.assertEqual(state, web_ui.counter_state(), "the input is never changed")

    def test_the_battle_effect_dart_tests(self):
        self.assertEqual(web_ui.counter_effect(0), {"counter": 0, "amount": 0, "heal": False, "idle": True, "orbs": []})
        damage = web_ui.counter_effect(3)
        self.assertEqual((damage["heal"], damage["amount"], damage["orbs"]), (False, 3, ["🔥", "💧", "🌳"]))
        heal = web_ui.counter_effect(-2)
        self.assertEqual((heal["heal"], heal["amount"], heal["orbs"]), (True, 2, ["❤️", "💚"]))
        big = web_ui.counter_effect(20)
        self.assertEqual((big["amount"], len(big["orbs"])), (20, web_ui.COUNTER_MAX_ORBS))
        self.assertEqual(web_ui.counter_effect(7)["orbs"], ["🔥", "💧", "🌳", "💡", "🔮", "🔥"])
        self.assertEqual(web_ui.counter_effect(-7)["orbs"], ["❤️", "💚", "✨", "❤️", "💚", "✨"])
        self.assertEqual([web_ui.counter_label(n) for n in (1, -1, 0, 20, -100)], ["💥 Damage 1", "💚 Heal 1", "Orbs ready…", "💥 Damage 20", "💚 Heal 100"])

    def test_the_status_ladder_is_first_match_wins(self):
        ladder = {100: "max", 99: "high", 50: "high", 49: "too_much", 10: "too_much", 9: "neutral", 1: "neutral", 0: "neutral", -1: "neutral", -9: "neutral",
                  -10: "reverse", -49: "reverse", -50: "low", -99: "low", -100: "min"}
        self.assertEqual({n: web_ui.counter_status_key(n) for n in ladder}, ladder)
        self.assertEqual(set(ladder.values()), set(web_ui.COUNTER_STATUS))
        self.assertEqual(web_ui.COUNTER_STATUS["too_much"], "Too much 😈")

    def test_holding_fires_after_350_ms_and_then_every_70_ms(self):
        self.assertEqual([web_ui.hold_repeat_count(ms) for ms in (0, 100, 349, 349.9, 350, 419, 419.9, 420, 489, 490, 700, 1050)], [0, 0, 0, 0, 1, 1, 1, 2, 2, 3, 6, 11])
        self.assertGreaterEqual(web_ui.hold_repeat_count(350), 1)
        self.assertGreaterEqual(web_ui.hold_repeat_count(350 + 70 + 70), 3)
        self.assertEqual([web_ui.hold_repeat_count(5000, buttons=b) for b in (1, 2, 4, 0)], [web_ui.hold_repeat_count(5000), 0, 0, 0])
        self.assertEqual([web_ui.hold_swallows_click(ms) for ms in (0, 349, 350, 5000)], [False, False, True, True])
        self.assertFalse(web_ui.hold_swallows_click(5000, buttons=2))

    def test_the_ironies_are_the_darts_twenty(self):
        self.assertEqual(len(web_ui.IRONIES), 20)
        self.assertEqual(len({text for text, _ in web_ui.IRONIES}), 20)
        self.assertEqual(list(dict.fromkeys(tone for _, tone in web_ui.IRONIES)), ["Tech", "Work", "Daily", "Human"])
        self.assertEqual([sum(tone == name for _, tone in web_ui.IRONIES) for name in ("Tech", "Work", "Daily", "Human")], [5, 5, 5, 5])
        self.assertEqual(web_ui.IRONIES[4][0], "The cloud is just someone else’s computer with better branding.")
        source = Path("/home/claude/myon-bioinformatics/flutter_navigation_basic/lib/data/ironies.dart")
        if source.is_file():
            dart = re.findall(r"IronyEntry\(text: '((?:[^'\\]|\\.)*)', tone: '(\w+)'\)", source.read_text(encoding="utf-8"))
            self.assertEqual(tuple(dart), web_ui.IRONIES)

    def test_the_next_irony_is_never_the_one_on_screen_and_every_other_one_can_come(self):
        for count in (2, 3, 20):
            for current in range(count):
                seen = {web_ui.irony_next(count, current, (k + 0.5) / (count - 1)) for k in range(count - 1)}
                self.assertEqual(seen, set(range(count)) - {current}, (count, current))
        self.assertIsNone(web_ui.irony_next(1, 0, 0.5))
        self.assertIsNone(web_ui.irony_next(0, None, 0.5))
        self.assertIn(web_ui.irony_next(5, None, 0.999999), range(5))
        self.assertEqual([web_ui.irony_first(20, u) for u in (0, 0.049999, 0.05, 0.999999)], [0, 0, 1, 19])
        for bad in (-0.1, 1.0, 2):
            with self.assertRaises(ValueError):
                web_ui.irony_next(5, 0, bad)
            with self.assertRaises(ValueError):
                web_ui.irony_first(5, bad)
        with self.assertRaises(ValueError):
            web_ui.irony_first(0, 0.5)
        for seed in (7, 11, 13, 17, 0, 4294967295):
            run = web_ui.irony_sequence(seed, 2000)
            self.assertTrue(all(a != b for a, b in zip(run, run[1:])), seed)
            self.assertEqual(run, web_ui.irony_sequence(seed, 2000))
            self.assertGreaterEqual(len(set(run)), 19, "a long run reaches (almost) all of them")

    # The Dart widget tests pump an 800x600 surface; the body under the app bar is 800x544, the card (max width 520) is centred and the handle sits at the top of it.
    ARENA = (800, 544)
    CARD = (140.0, 172.0, 660.0, 372.0)
    HANDLE = (376.0, 180.0, 424.0, 212.0)

    @staticmethod
    def shifted(rect, dx, dy):
        return (rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy)

    def drop(self, dx, dy):
        return web_ui.irony_drop(self.ARENA, self.shifted(self.CARD, dx, dy), self.shifted(self.HANDLE, dx, dy))

    def test_a_small_drag_keeps_the_message(self):
        self.assertEqual(self.drop(48, 32), {"action": "none", "dx": 0.0, "dy": 0.0})

    def test_moving_the_card_fully_outside_spawns_the_next_message(self):
        self.assertEqual(self.drop(1600, 0)["action"], "spawn")
        self.assertEqual(self.drop(0, 600)["action"], "spawn")
        self.assertEqual(self.drop(-900, 0)["action"], "spawn")
        # touching along an edge is not overlapping; one pixel of overlap is
        self.assertEqual(self.drop(800 - 140.0, 0)["action"], "spawn")
        self.assertEqual(self.drop(800 - 140.0 - 1, 0)["action"], "snap")

    def test_partial_exit_snaps_the_handle_back_inside_eight_pixels(self):
        for dy in (0 - self.HANDLE[3] - 12, 0 - self.HANDLE[3] + 4, -300.0, -175.0):
            handle = self.shifted(self.HANDLE, 0, dy)
            card = self.shifted(self.CARD, 0, dy)
            self.assertGreater(card[3], 0, "precondition: the card body stays partly visible")
            result = web_ui.irony_drop(self.ARENA, card, handle)
            self.assertEqual(result["action"], "snap", dy)
            moved = self.shifted(handle, result["dx"], result["dy"])
            self.assertTrue(web_ui.rect_inside(moved, web_ui.rect_deflate((0, 0, *self.ARENA), 8)), (dy, moved))
            self.assertAlmostEqual(moved[1], 8.0)

    def test_a_handle_exactly_on_the_safe_inset_stays_where_it_is(self):
        self.assertEqual(web_ui.irony_drop(self.ARENA, (0, 0, 100, 100), (8, 8, 56, 40))["action"], "none")
        self.assertEqual(web_ui.irony_drop(self.ARENA, (0, 0, 100, 100), (7.5, 8, 55.5, 40))["action"], "snap")
        self.assertEqual(web_ui.irony_drop(self.ARENA, (0, 0, 100, 100), (8, 8, 56, 40))["action"], "none")

    def test_missing_measurements_end_the_drag_quietly(self):
        none = {"action": "none", "dx": 0.0, "dy": 0.0}
        self.assertEqual(web_ui.irony_drop(self.ARENA, None, self.HANDLE), none)
        self.assertEqual(web_ui.irony_drop(self.ARENA, None, None), none)
        self.assertEqual(web_ui.irony_drop(self.ARENA, self.CARD, None), none)

    def test_a_handle_as_large_as_the_arena_is_centred(self):
        result = web_ui.irony_drop((100, 100), (0, 0, 120, 120), (-10, -10, 110, 110))
        self.assertEqual(result["action"], "snap")
        self.assertEqual((result["dx"], result["dy"]), (0.0, 0.0))
        shifted = web_ui.irony_drop((100, 100), (-20, -20, 100, 100), (-30, -30, 90, 90))
        self.assertEqual((shifted["dx"], shifted["dy"]), (20.0, 20.0))

    def test_rect_rules(self):
        self.assertTrue(web_ui.rect_overlaps((0, 0, 10, 10), (9, 9, 20, 20)))
        self.assertFalse(web_ui.rect_overlaps((0, 0, 10, 10), (10, 0, 20, 10)))
        self.assertFalse(web_ui.rect_overlaps((0, 0, 10, 10), (0, 10, 10, 20)))
        self.assertTrue(web_ui.rect_inside((1, 1, 9, 9), (0, 0, 10, 10)))
        self.assertTrue(web_ui.rect_inside((0, 0, 10, 10), (0, 0, 10, 10)))
        self.assertFalse(web_ui.rect_inside((0, 0, 10.5, 10), (0, 0, 10, 10)))
        self.assertEqual(web_ui.rect_deflate((0, 0, 100, 50), 8), (8.0, 8.0, 92.0, 42.0))
        self.assertEqual(web_ui.rect_clamp_inside((-20, 5, 30, 25), (0, 0, 100, 100), 8), (8.0, 8.0, 58.0, 28.0))
        for bad in ((1, 2, 3), (1, 2, 3, float("nan")), (1, 2, 3, True), "abcd", None):
            with self.assertRaises(ValueError, msg=bad):
                web_ui.rect_overlaps(bad, (0, 0, 1, 1))
        with self.assertRaises(ValueError):
            web_ui.irony_drop((float("inf"), 10), self.CARD, self.HANDLE)

    def test_a_seeded_fuzz_always_ends_with_the_handle_reachable_or_the_card_gone(self):
        rng = random.Random(20261103)
        for _ in range(5000):
            width, height = rng.randint(120, 1000), rng.randint(120, 1000)
            card = (rng.uniform(-600, 1200), rng.uniform(-600, 1200))
            cw, ch, hw, hh = rng.uniform(40, 520), rng.uniform(40, 300), rng.uniform(16, 64), rng.uniform(16, 48)
            card_rect = (card[0], card[1], card[0] + cw, card[1] + ch)
            handle = (card[0] + rng.uniform(0, max(cw - hw, 0)), card[1] + rng.uniform(0, max(ch - hh, 0)))
            handle_rect = (handle[0], handle[1], handle[0] + hw, handle[1] + hh)
            result = web_ui.irony_drop((width, height), card_rect, handle_rect)
            if not web_ui.rect_overlaps(card_rect, (0, 0, width, height)):
                self.assertEqual(result["action"], "spawn")
                continue
            moved = self.shifted(handle_rect, result["dx"], result["dy"])
            self.assertIn(result["action"], ("none", "snap"))
            # the card moves by (clamped centre - centre), as in the Dart page, so it can land a rounding error (1e-13) off the exact inset: allow that
            if hw <= width - 16 and hh <= height - 16:
                self.assertTrue(web_ui.rect_inside(moved, web_ui.rect_deflate((0, 0, width, height), 8 - 1e-9)), (result, moved, width, height))

    def test_the_page_is_semantic_and_self_contained(self):
        html = web_ui.playground_document()
        for needle in ('data-ui-play', 'data-counter-increment', 'data-counter-decrement', 'data-counter-reset', 'data-counter-undo', 'data-counter-history', 'data-irony-arena',
                       'data-irony-handle', 'aria-label="Drag to move message"', 'data-irony-next', 'aria-live="polite"', 'name="counter-step"'):
            self.assertIn(needle, html)
        self.assertEqual(html.count('<script'), 1)
        self.assertNotIn('http://', html.split('<style', 1)[0])
        self.assertIn("examples/playground.html", web_ui.example_pages())
        self.assertIn("./playground.html", web_ui.example_pages()["examples/index.html"])
        self.assertEqual(json.loads(re.search(r'data-play="([^"]*)"', html).group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#x27;", "'"))["status"], web_ui.COUNTER_STATUS)


def flutter_case(tid, sid, name, result="success", **done):
    return [{"type": "testStart", "test": {"id": tid, "suiteID": sid, "name": name}}, {"type": "testDone", "testID": tid, "result": result, **done}]


def ndjson(events):
    return "\n".join(json.dumps(e) for e in events)


class ReportTests(unittest.TestCase):
    """Test reports: the Python tests of flutter_navigation_basic's outcomes, flutter_machine_junit, validate_runner_junit, junit_history, multi_test_runner,
    node_test_runner and expected_child_failure are the golden values (ported case by case)."""

    SHA = "a" * 40

    def parse(self, xml):
        return ET.fromstring(xml)

    # --- outcomes (python/tests/test_outcomes.py)
    def test_a_known_skip_is_xfailed_and_a_plain_skip_is_skipped(self):
        events = [
            {"type": "testStart", "test": {"id": 1, "name": "loading suite", "metadata": {"skip": False, "skipReason": None}}},
            {"type": "testDone", "testID": 1, "result": "success", "skipped": False, "hidden": True},
            {"type": "testStart", "test": {"id": 2, "name": "works", "metadata": {"skip": False, "skipReason": None}}},
            {"type": "testDone", "testID": 2, "result": "success", "skipped": False, "hidden": False},
            {"type": "testStart", "test": {"id": 3, "name": "known gap", "metadata": {"skip": True, "skipReason": "known: pattern catalogue not on latest-stable"}}},
            {"type": "testDone", "testID": 3, "result": "success", "skipped": True, "hidden": False},
            {"type": "testStart", "test": {"id": 4, "name": "plain skip", "metadata": {"skip": True, "skipReason": "not in this env"}}},
            {"type": "testDone", "testID": 4, "result": "success", "skipped": True, "hidden": False},
            {"type": "testStart", "test": {"id": 5, "name": "x", "metadata": {"skip": True, "skipReason": "XFAIL: upper case counts too"}}},
            {"type": "testDone", "testID": 5, "result": "success", "skipped": True},
        ]
        counts = web_ui.flutter_outcomes(ndjson(events))
        self.assertEqual((counts["passed"], counts["xfailed"], counts["skipped"], counts["failed"]), (1, 2, 1, 0))
        self.assertIn("xfailed=2", web_ui.counts_line(counts))

    def test_bad_lines_count_as_errors_and_garbage_alone_is_not_ok(self):
        lines = [json.dumps({"type": "testStart", "test": {"id": 1, "name": "works"}}), json.dumps({"type": "testDone", "testID": 1, "result": "success"}), "{not-json", "42", ""]
        counts = web_ui.flutter_outcomes("\n".join(lines))
        self.assertEqual((counts["passed"], counts["error"]), (1, 2))
        self.assertFalse(web_ui.counts_summary(counts, source="flutter-json")["ok"])
        garbage = web_ui.flutter_outcomes("truncated...\n{broken")
        self.assertEqual(garbage, {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "error": 2})
        self.assertFalse(web_ui.counts_summary(garbage, source="flutter-json")["ok"])
        self.assertEqual(web_ui.flutter_outcomes('{"a": NaN}\n{"type": "testStart", "test": [1]}')["error"], 2, "JSON constants and a non-object test are errors")

    def test_the_receipt_round_trips(self):
        payload = web_ui.counts_summary({"passed": 1, "failed": 0, "skipped": 2, "xfailed": 1, "xpassed": 0, "error": 0}, source="pytest")
        loaded = json.loads(json.dumps(payload))
        self.assertEqual((loaded["ok"], loaded["counts"]["xfailed"], loaded["total"]), (True, 1, 4))

    def test_nothing_passed_is_not_green_and_a_failed_load_is_an_error(self):
        self.assertFalse(web_ui.counts_summary({}, source="x")["ok"])
        self.assertFalse(web_ui.counts_summary({"skipped": 5}, source="x")["ok"])
        self.assertTrue(web_ui.counts_summary({"passed": 1, "skipped": 5}, source="x")["ok"])
        broken = ndjson([*flutter_case(1, 0, "loading test/broken_test.dart", result="error", hidden=False), {"type": "done", "success": False}])
        self.assertEqual(web_ui.flutter_outcomes(broken)["error"], 1)
        shown = ndjson([*flutter_case(1, 0, "loading test/ok_test.dart"), *flutter_case(2, 0, "real"), {"type": "done", "success": True}])
        self.assertEqual(web_ui.flutter_outcomes(shown)["passed"], 1, "a successful, visible loading pseudo-test is not a test")
        ids = ndjson([{"type": "testStart", "test": {"id": True, "name": "a", "metadata": {"skipReason": "known: x"}}}, {"type": "testDone", "testID": True, "result": "success", "skipped": True}])
        self.assertEqual(web_ui.flutter_outcomes(ids)["skipped"], 1, "a boolean is never a test ID, so the start's skip reason is not linked to the completion")

    # --- Flutter machine events to JUnit (python/tests/test_flutter_machine_junit.py)
    def convert(self, events):
        return web_ui.flutter_machine_junit(ndjson(events))

    def test_per_case_failure_is_preserved(self):
        events = [{"type": "testStart", "test": {"id": 1, "name": "passes"}}, {"type": "testDone", "testID": 1, "result": "success"},
                  {"type": "testStart", "test": {"id": 2, "name": "fails"}}, {"type": "error", "testID": 2, "error": "expected true"},
                  {"type": "testDone", "testID": 2, "result": "failure"}, {"type": "done", "success": False}]
        done = self.convert(events)
        self.assertEqual(done["tests"], 2)
        cases = self.parse(done["xml"]).findall("testcase")
        self.assertEqual([c.get("name") for c in cases], ["passes", "fails"])
        self.assertIsNotNone(cases[1].find("failure"))
        self.assertEqual(cases[1].find("failure").text, "expected true")

    def test_skip_hidden_and_suite_identity_follow_the_protocol(self):
        suite = lambda sid, path: {"type": "suite", "suite": {"id": sid, "path": path}}
        events = [suite(0, "test/a_test.dart"), suite(1, "test/b_test.dart"), *flutter_case(1, 0, "loading test/a_test.dart", hidden=True), *flutter_case(2, 0, "same name"),
                  *flutter_case(3, 1, "same name"), {"type": "testStart", "test": {"id": 4, "suiteID": 1, "name": "skip me", "metadata": {"skipReason": "known: gap"}}},
                  {"type": "testDone", "testID": 4, "result": "success", "skipped": True}, {"type": "done", "success": True}]
        cases = self.parse(self.convert(events)["xml"]).findall("testcase")
        self.assertEqual([(c.get("classname"), c.get("name")) for c in cases], [("test/a_test.dart", "same name"), ("test/b_test.dart", "same name"), ("test/b_test.dart", "skip me")])
        self.assertEqual(cases[2].find("skipped").get("message"), "known: gap")
        self.assertTrue(all(c.find("skipped") is None for c in cases[:2]))

    def test_a_failed_load_stays_visible(self):
        events = [{"type": "suite", "suite": {"id": 0, "path": "test/broken_test.dart"}}, {"type": "testStart", "test": {"id": 1, "suiteID": 0, "name": "loading test/broken_test.dart"}},
                  {"type": "error", "testID": 1, "error": "Compilation failed"}, {"type": "testDone", "testID": 1, "result": "error", "hidden": False}, {"type": "done", "success": False}]
        cases = self.parse(self.convert(events)["xml"]).findall("testcase")
        self.assertEqual(len(cases), 1)
        self.assertIn("Compilation failed", cases[0].find("error").text)

    def test_incomplete_or_inconsistent_events_are_rejected(self):
        done = {"type": "done", "success": True}
        bad = {
            "only hidden": [*flutter_case(1, 0, "loading x", hidden=True), done],
            "no done": [{"type": "testStart", "test": {"id": 1, "name": "x"}}, {"type": "testDone", "testID": 1, "result": "success"}],
            "never completed": [{"type": "testStart", "test": {"id": 1, "name": "x"}}, done],
            "bad result": [*flutter_case(1, 0, "x", result="weird"), done],
            "duplicate id": [*flutter_case(1, 0, "x"), {"type": "testStart", "test": {"id": 1, "name": "y"}}, done],
            "missing id": [{"type": "testStart", "test": {"name": "x"}}, done],
            "boolean id": [{"type": "testStart", "test": {"id": True, "name": "x"}}, done],
            "nameless": [*flutter_case(1, 0, ""), done],
            "orphan error": [{"type": "error", "testID": 9, "error": "e"}, *flutter_case(1, 0, "x"), done],
            "orphan completion": [{"type": "testDone", "testID": 9, "result": "success"}, *flutter_case(1, 0, "x"), done],
            "repeated completion": [*flutter_case(1, 0, "x"), {"type": "testDone", "testID": 1, "result": "success"}, done],
        }
        for name, events in bad.items():
            with self.assertRaises(ValueError, msg=name):
                self.convert(events)
        for text in ("{broken", "42", "[]", '{"a": NaN}'):
            with self.assertRaises(ValueError, msg=text):
                web_ui.flutter_machine_junit(text)

    def test_the_converted_xml_is_exact_and_always_parses(self):
        events = [{"type": "suite", "suite": {"id": 0, "path": 'test/<a>&"b".dart'}}, *flutter_case(1, 0, 'x < y & "z"\ttab'), {"type": "testStart", "test": {"id": 2, "suiteID": 0, "name": "bad"}},
                  {"type": "error", "testID": 2, "error": "boom \x1b[31mred\x1b[0m < & >", "stackTrace": "line1\nline2"}, {"type": "testDone", "testID": 2, "result": "failure"},
                  {"type": "testStart", "test": {"id": 3, "suiteID": 0, "name": "gap", "metadata": {"skipReason": 'xfail: "q"'}}},
                  {"type": "testDone", "testID": 3, "result": "success", "skipped": True}, {"type": "testStart", "test": {"id": 4, "suiteID": 0, "name": "empty failure"}},
                  {"type": "testDone", "testID": 4, "result": "error"}, {"type": "done", "success": False}]
        xml = self.convert(events)["xml"]
        self.assertEqual(xml, '<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="flutter" tests="4">\n'
                              '  <testcase name="x &lt; y &amp; &quot;z&quot;&#09;tab" classname="test/&lt;a&gt;&amp;&quot;b&quot;.dart" />\n'
                              '  <testcase name="bad" classname="test/&lt;a&gt;&amp;&quot;b&quot;.dart">\n    <failure message="Flutter test failure">boom �[31mred�[0m &lt; &amp; &gt;\nline1\nline2</failure>\n  </testcase>\n'
                              '  <testcase name="gap" classname="test/&lt;a&gt;&amp;&quot;b&quot;.dart">\n    <skipped message="xfail: &quot;q&quot;" />\n  </testcase>\n'
                              '  <testcase name="empty failure" classname="test/&lt;a&gt;&amp;&quot;b&quot;.dart">\n    <error message="Flutter test error" />\n  </testcase>\n</testsuite>\n')
        root = self.parse(xml)
        self.assertEqual(root.findall("testcase")[0].get("name"), 'x < y & "z"\ttab')
        report = web_ui.junit_report(xml)
        self.assertEqual((report["counts"]["passed"], report["counts"]["failed"], report["counts"]["xfailed"], report["counts"]["error"]), (1, 1, 1, 1))

    def test_a_realistic_stream_gives_the_same_counts_as_junit(self):
        events = [{"type": "suite", "suite": {"id": 0, "path": "test/a_test.dart"}}, *flutter_case(1, 0, "loading test/a_test.dart", hidden=True), *flutter_case(2, 0, "ok"),
                  *flutter_case(3, 0, "bad", result="failure"), *flutter_case(4, 0, "boom", result="error"),
                  {"type": "testStart", "test": {"id": 5, "suiteID": 0, "name": "gap", "metadata": {"skipReason": "known: x"}}}, {"type": "testDone", "testID": 5, "result": "success", "skipped": True},
                  {"type": "testStart", "test": {"id": 6, "suiteID": 0, "name": "skip", "metadata": {"skipReason": "later"}}}, {"type": "testDone", "testID": 6, "result": "success", "skipped": True},
                  {"type": "done", "success": False}]
        text = ndjson(events)
        self.assertEqual(web_ui.flutter_outcomes(text), web_ui.junit_report(web_ui.flutter_machine_junit(text)["xml"])["counts"])
        self.assertEqual(web_ui.flutter_outcomes(text), {"passed": 1, "failed": 1, "skipped": 1, "xfailed": 1, "xpassed": 0, "error": 1})

    # --- JUnit validation and report (python/tests/test_validate_runner_junit.py, test_multi_test_runner.py, test_node_test_runner.py)
    def test_native_junit_cases_are_counted(self):
        xml = '<testsuite tests="3"><testcase name="pass"/><testcase name="fail"><failure message="oops"/></testcase><testcase name="skip"><skipped/></testcase></testsuite>'
        self.assertEqual(web_ui.junit_inspect(xml), {"tests": 3, "failures": 1, "errors": 0, "skipped": 1})

    def test_nested_suites_are_searched_at_any_depth(self):
        xml = '<testsuite name="root"><testsuite name="group"><testcase name="inner"/></testsuite><testcase name="top"/></testsuite>'
        self.assertEqual(web_ui.junit_inspect(xml)["tests"], 2)
        self.assertEqual(web_ui.junit_inspect('<testsuites><testsuite><testsuite><testcase name="deep"/></testsuite></testsuite></testsuites>')["tests"], 1)

    def test_invalid_reports_fail_closed(self):
        for xml in ("<testsuite/>", "<testsuite><testcase/></testsuite>", "<testsuite><testcase name='x'></testsuite>", "<not-junit><testcase name='x'/></not-junit>", "", "   ", "<broken",
                    '<testsuite xmlns="urn:x"><testcase name="a"/></testsuite>', '<!DOCTYPE testsuite [<!ENTITY a "b">]><testsuite><testcase name="&a;"/></testsuite>',
                    '<!doctype x><testsuite><testcase name="a"/></testsuite>', '<testsuite><testcase name=""/></testsuite>', "<testsuites/>"):
            with self.assertRaises(ValueError, msg=xml):
                web_ui.junit_cases(xml)
        with self.assertRaises(ValueError):
            web_ui.junit_cases("<testsuite>" + '<testcase name="a"/>' * 60000 + "</testsuite>")
        with self.assertRaises(ValueError):
            web_ui.junit_cases(None)
        self.assertEqual(len(web_ui.junit_cases("﻿" + '<testsuite><testcase name="a"/></testsuite>')), 1)
        self.assertEqual(len(web_ui.junit_cases('<?xml version="1.0" encoding="UTF-8"?>\n<testsuite><testcase name="a"/></testsuite>')), 1)

    def test_a_report_counts_outcomes_and_keeps_messages_out(self):
        xml = ('<testsuites><testsuite><testcase classname="c" name="ok"/><testcase classname="c" name="bad"><failure message="SECRET_TOKEN">trace</failure></testcase>'
               '<testcase classname="c" name="boom"><error>text only</error></testcase><testcase name="gap"><skipped message="Known: later"/></testcase>'
               '<testcase name="xf"><skipped type="pytest.xfail" message="reason"/></testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuites>')
        report = web_ui.junit_report(xml)
        self.assertEqual(report["counts"], {"passed": 1, "failed": 1, "skipped": 1, "xfailed": 2, "xpassed": 0, "error": 1})
        self.assertEqual((report["total"], report["ok"], report["schema"]), (6, False, "junit-report/1"))
        self.assertEqual([(f["name"], f["kind"]) for f in report["failures"]], [("bad", "failure"), ("boom", "error")])
        self.assertEqual(report["failures"][0]["message_sha256"], hashlib.sha256(b"SECRET_TOKEN").hexdigest())
        self.assertEqual(report["failures"][1]["message_sha256"], hashlib.sha256(b"text only").hexdigest())
        self.assertNotIn("SECRET_TOKEN", json.dumps(report))
        shown = web_ui.junit_report(xml, messages=True)
        self.assertEqual([f["message"] for f in shown["failures"]], ["SECRET_TOKEN", "text only"])

    def test_the_node_report_golden(self):
        xml = '<testsuites><testcase name="ok"/><testcase name="bad"><failure message="boom">stack</failure></testcase><testcase name="skip"><skipped/></testcase></testsuites>'
        report = web_ui.junit_report(xml, messages=True)
        self.assertEqual((report["counts"]["passed"], report["counts"]["failed"], report["counts"]["skipped"], report["total"]), (1, 1, 1, 3))
        self.assertEqual([(f["name"], f["message"]) for f in report["failures"]], [("bad", "boom")])
        self.assertEqual([c["name"] for c in web_ui.junit_cases(xml)], ["ok", "bad", "skip"])

    def test_a_message_longer_than_the_limit_is_cut_by_characters_not_bytes(self):
        xml = f'<testsuite><testcase classname="{"é" * 300}" name="{"😀" * 300}"><failure message="{"x" * 3000}"/></testcase></testsuite>'
        failure = web_ui.junit_report(xml, messages=True)["failures"][0]
        self.assertEqual((len(failure["class"]), len(failure["name"]), len(failure["message"])), (200, 200, 2000))
        self.assertEqual(failure["name"], "😀" * 200)

    def test_text_after_a_comment_or_cdata_is_the_message(self):
        xml = '<testsuite><testcase name="a"><failure>one<!-- c -->two<![CDATA[ <three> ]]><b/>ignored</failure></testcase></testsuite>'
        self.assertEqual(web_ui.junit_cases(xml)[0]["message"], "onetwo <three>")

    # --- failure history (python/tests/test_junit_history.py)
    def sample(self, test="test_one", kind="failure", report="run-specific"):
        return {"category": "test_failure", "context": {"repository": "myon-bioinformatics/flutter_navigation_basic", "report_id": report, "commit_sha": None},
                "value": {"class": "test_oracle", "test": test, "kind": kind}}

    def test_the_fingerprint_ignores_run_specific_context(self):
        a = web_ui.junit_history_load(json.dumps(self.sample(report="first")) + "\n")
        b = web_ui.junit_history_load(json.dumps(self.sample(report="second")) + "\n")
        self.assertEqual(a[0]["fingerprint"], b[0]["fingerprint"])
        self.assertTrue(a[0]["fingerprint"].startswith("junit-basic-v1:"))
        token = json.dumps({"class": "test_oracle", "kind": "failure", "repository": "myon-bioinformatics/flutter_navigation_basic", "test": "test_one"}, separators=(",", ":"))
        self.assertEqual(a[0]["fingerprint"], "junit-basic-v1:" + hashlib.sha256(token.encode()).hexdigest())

    def test_new_recurring_and_resolved_with_counts(self):
        rows = lambda name, count: web_ui.junit_history_load([self.sample(name)] * count)
        report = web_ui.junit_history(rows("same", 2) + rows("new", 1), rows("old", 1) + rows("same", 1), commit_sha=self.SHA, run_id="42", previous_commit_sha="b" * 40, previous_run_id="41")
        self.assertEqual(report["summary"], {"new": 1, "recurring": 1, "resolved": 1})
        recurring = next(x for x in report["findings"] if x["status"] == "recurring")
        self.assertEqual((recurring["previous_count"], recurring["current_count"]), (1, 2))
        self.assertEqual([f["fingerprint"] for f in report["findings"]], sorted(f["fingerprint"] for f in report["findings"]))
        self.assertEqual((report["schema"], report["fingerprint_scope"]), ("junit-history/1", "repository+class+test+kind (not root cause)"))

    def test_an_error_and_a_failure_have_distinct_fingerprints(self):
        found = web_ui.junit_history_load([self.sample(kind=k) for k in ("failure", "error")])
        self.assertEqual(len({x["fingerprint"] for x in found}), 2)

    def test_bad_history_input_is_an_error(self):
        for kwargs in ({"commit_sha": "invalid", "run_id": "42"}, {"commit_sha": self.SHA, "run_id": "4x"}, {"commit_sha": self.SHA, "run_id": "42", "previous_commit_sha": "zz"},
                       {"commit_sha": self.SHA, "run_id": "42", "previous_run_id": "-1"}, {"commit_sha": self.SHA + "\n", "run_id": "42"}):
            with self.assertRaises(ValueError, msg=kwargs):
                web_ui.junit_history([], [], **kwargs)
        for records in ([{"category": "test_failure", "context": {}, "value": {}}], [{"category": "test_failure", "context": [], "value": {}}],
                        [{"category": "test_failure", "context": {"repository": "a/b"}, "value": {"class": "", "test": "t", "kind": "failure"}}], '{"category": "test_failure"}\n{broken'):
            with self.assertRaises(ValueError, msg=records):
                web_ui.junit_history_load(records)
        self.assertEqual(web_ui.junit_history_load([{"category": "other"}, 5, None]), [])

    def test_identities_come_straight_from_a_report_without_parameters_or_messages(self):
        xml = ('<testsuite><testcase classname="tests.test_a[py3]" name="test_x[1-2]"><failure message="m1"/></testcase><testcase classname="tests.test_a" name="test_x[3-4]"><error message="m2"/></testcase>'
               '<testcase name="solo"><failure/></testcase><testcase name="fine"/></testsuite>')
        got = web_ui.junit_failure_records(xml, "o/n")
        self.assertEqual([r["value"] for r in got["records"]], [{"class": "tests.test_a", "test": "test_x", "kind": "failure"}, {"class": "tests.test_a", "test": "test_x", "kind": "error"},
                                                                   {"class": "(none)", "test": "solo", "kind": "failure"}])
        self.assertFalse(got["truncated"])
        self.assertNotIn("m1", json.dumps(got))
        many = '<testsuite>' + "".join(f'<testcase name="t{i}"><failure/></testcase>' for i in range(7)) + "</testsuite>"
        self.assertEqual((len(web_ui.junit_failure_records(many, "o/n", max_cases=5)["records"]), web_ui.junit_failure_records(many, "o/n", max_cases=5)["truncated"]), (5, True))
        self.assertFalse(web_ui.junit_failure_records(many, "o/n", max_cases=7)["truncated"])
        for repo in ("", "no-slash", "a/b/c", "a/ b", None):
            with self.assertRaises(ValueError, msg=repo):
                web_ui.junit_failure_records(xml, repo)

    def test_two_reports_diff_into_new_recurring_and_resolved(self):
        suite = lambda *names: "<testsuite>" + "".join(f'<testcase classname="c" name="{n}"><failure/></testcase>' for n in names) + '<testcase name="fine"/></testsuite>'
        diff = web_ui.junit_diff(suite("same", "new", "same[2]"), suite("same", "gone"))
        self.assertEqual(diff["summary"], {"new": 1, "recurring": 1, "resolved": 1})
        recurring = next(f for f in diff["findings"] if f["status"] == "recurring")
        self.assertEqual((recurring["current_count"], recurring["previous_count"]), (2, 1), "a parameterized failure shares its identity")
        self.assertEqual(diff["schema"], "junit-diff/1")

    # --- ledger and attempt records (multi_test_runner)
    def test_the_failure_ledger_accumulates_without_raw_text_and_rejects_corruption(self):
        failure = {"kind": "failure", "message_sha256": "a" * 64}
        attempts = [{"failures": [failure]}]
        once = web_ui.failure_ledger_update(None, "node", attempts)
        twice = web_ui.failure_ledger_update(once, "node", attempts)
        self.assertEqual((once["schema"], next(iter(once["patterns"].values()))["occurrences"], next(iter(twice["patterns"].values()))["occurrences"]), ("failure-patterns/1", 1, 2))
        self.assertEqual(next(iter(once["patterns"].values()))["occurrences"], 1, "the input ledger is not changed")
        for broken in ({"schema": "x", "patterns": {}}, {"schema": "failure-patterns/1", "patterns": []}, [], "text"):
            with self.assertRaises(ValueError, msg=broken):
                web_ui.failure_ledger_update(broken, "node", attempts)
        many = [{"failures": [{"kind": "failure", "message_sha256": f"{i:064x}"} for i in range(501)]}]
        with self.assertRaises(ValueError):
            web_ui.failure_ledger_update(None, "node", many)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "patterns.json"
            web_ui.failure_ledger_file(path, "node", attempts)
            web_ui.failure_ledger_file(path, "node", attempts)
            self.assertEqual(next(iter(json.loads(path.read_text())["patterns"].values()))["occurrences"], 2)
            path.write_text("{broken")
            with self.assertRaises(ValueError):
                web_ui.failure_ledger_file(path, "node", attempts)
            self.assertEqual(path.read_text(), "{broken")

    def test_attempt_records_say_when_a_retry_recovered(self):
        first, second = {"exit_code": 1}, {"exit_code": 0}
        self.assertEqual({k: web_ui.attempt_history("deno", ["a.ts"], [first, second])[k] for k in ("initial_failed", "flaky_recovered")}, {"initial_failed": True, "flaky_recovered": True})
        self.assertFalse(web_ui.attempt_history("deno", ["a.ts"], [first, first])["flaky_recovered"])
        self.assertFalse(web_ui.attempt_history("deno", ["a.ts"], [second])["initial_failed"])
        self.assertFalse(web_ui.attempt_history("deno", ["a.ts"], [first])["flaky_recovered"])

    # --- allowlisted runners (python/tests/test_multi_test_runner.py, test_node_test_runner.py)
    def test_runner_commands_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "e2e").mkdir()
            for file in ("e2e/test.spec.ts", "test.ts", "test_pw.py"):
                (root / file).write_text("test")
            report = root / "report.xml"
            deno, cwd, env = web_ui.runner_command("deno", root=root, files=["test.ts"], report=report)
            self.assertEqual((deno[:3], cwd, env), (["deno", "test", "--junit-path"], root.resolve(), {}))
            node, cwd, env = web_ui.runner_command("playwright-node", root=root, files=["e2e/test.spec.ts"], report=report)
            self.assertEqual((node[:4], cwd, env["PLAYWRIGHT_JUNIT_OUTPUT_FILE"]), (["npx", "--no-install", "playwright", "test"], root.resolve() / "e2e", str(report.resolve())))
            self.assertEqual(node[-1], "test.spec.ts")
            py, _, _ = web_ui.runner_command("playwright-python", root=root, files=["test_pw.py"], report=report)
            self.assertEqual(py[:3], [sys.executable, "-m", "pytest"])
            for files in ([], ["../escape.py"], ["not-found.ts"]):
                with self.assertRaises(ValueError, msg=files):
                    web_ui.runner_command("deno", root=root, files=files, report=report)
            (root.parent / "outside.spec.ts").write_text("test")
            for runner, files in (("playwright-node", ["test.ts"]), ("make", ["test.ts"]), ("deno", ["../outside.spec.ts"])):
                with self.assertRaises(ValueError, msg=runner):
                    web_ui.runner_command(runner, root=root, files=files, report=report)
            (root.parent / "outside.spec.ts").unlink()

    def suite(self, tmp, invoke, **kwargs):
        (tmp / "test_pw.py").write_text("test")
        return web_ui.run_test_suite("playwright-python", root=tmp, files=["test_pw.py"], report=kwargs.pop("report", tmp / "r.xml"), history=kwargs.pop("history", tmp / "history.json"),
                                     invoke=invoke, **kwargs)

    def test_a_retry_keeps_the_first_failure_and_hashes_the_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            calls = []
            def invoke(cmd, **kwargs):
                calls.append(cmd)
                output = Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--junitxml=")))
                if len(calls) == 1:
                    output.write_text('<testsuites><testsuite><testcase name="bad"><failure message="SECRET_TOKEN"/></testcase></testsuite></testsuites>')
                    return mock.Mock(returncode=1)
                output.write_text('<testsuites><testsuite><testcase name="ok"/></testsuite></testsuites>')
                return mock.Mock(returncode=0)
            self.assertEqual(self.suite(tmp, invoke, retry_failed=True), 1)
            data = json.loads((tmp / "history.json").read_text())
            self.assertEqual((len(calls), len(data["attempts"]), data["initial_failed"], data["flaky_recovered"]), (2, 2, True, True))
            self.assertNotIn("SECRET_TOKEN", (tmp / "history.json").read_text())
            self.assertEqual(data["attempts"][0]["failures"][0]["message_sha256"], hashlib.sha256(b"SECRET_TOKEN").hexdigest())

    def test_missing_or_all_skipped_junit_fails_closed(self):
        for xml in (None, '<testsuites><testsuite><testcase name="skip"><skipped/></testcase></testsuite></testsuites>'):
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                def invoke(cmd, **kwargs):
                    if xml:
                        (tmp / "r.xml").write_text(xml)
                    return mock.Mock(returncode=0)
                self.assertEqual(self.suite(tmp, invoke), 1, xml)

    def test_the_first_success_removes_a_previous_retry_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            retry = tmp / "r.retry.xml"
            retry.write_text('<testsuites><testcase name="old-retry"/></testsuites>')
            def invoke(cmd, **kwargs):
                (tmp / "r.xml").write_text('<testsuites><testcase name="ok"/></testsuites>')
                return mock.Mock(returncode=0)
            self.assertEqual(self.suite(tmp, invoke, retry_failed=True), 0)
            self.assertFalse(retry.exists())
            self.assertEqual(len(json.loads((tmp / "history.json").read_text())["attempts"]), 1)

    def test_a_stale_report_never_stands_in_and_a_missing_runner_is_127(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "r.xml").write_text('<testsuites><testcase name="stale"/></testsuites>')
            def missing(cmd, **kwargs):
                raise FileNotFoundError()
            self.assertEqual(self.suite(tmp, missing), 127)
            self.assertFalse((tmp / "r.xml").exists())
            def slow(cmd, **kwargs):
                raise subprocess.TimeoutExpired(cmd, 1)
            self.assertEqual(self.suite(tmp, slow), 124)
            with self.assertRaises(ValueError):
                self.suite(tmp, missing, timeout=0)

    def test_a_corrupt_ledger_does_not_mask_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ledger = tmp / "ledger.json"
            ledger.write_text("{broken")
            def invoke(cmd, **kwargs):
                (tmp / "r.xml").write_text('<testsuites><testcase name="bad"><failure message="expected"/></testcase></testsuites>')
                return mock.Mock(returncode=1)
            with mock.patch("sys.stderr") as err:
                self.assertEqual(self.suite(tmp, invoke, ledger=ledger), 1)
            self.assertEqual(ledger.read_text(), "{broken")
            self.assertIn("warning: failure ledger update skipped", "".join(c.args[0] for c in err.write.call_args_list))

    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_real_node_success_failure_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            js = tmp / "checks.test.mjs"
            js.write_text("import test from 'node:test';\ntest('passes', () => {});\ntest('fails', () => {throw new Error('sentinel failure')});\n")
            report, receipt = tmp / "node.xml", tmp / "summary.json"
            with mock.patch("sys.stdout"):
                self.assertEqual(web_ui.node_test_run(root=tmp, files=[js.name], report=report, receipt=receipt), 1)
                data = json.loads(receipt.read_text())
                self.assertEqual((data["failed"], data["passed"]), (1, 1))
                self.assertIn("sentinel failure", data["failures"][0]["message"])
                self.assertEqual(web_ui.node_test_run(root=tmp, files=[js.name], report=report, receipt=receipt, name_pattern="^passes$"), 0)
                self.assertEqual(json.loads(receipt.read_text())["failed"], 0)
                receipt.write_text('{"ok":true}')
                self.assertNotEqual(web_ui.node_test_run(root=tmp, files=[js.name], report=report, receipt=receipt, name_pattern="^never-matches$"), 0)
                self.assertFalse(receipt.exists())
                for style in (js.name, "./" + js.name, str(js)):
                    self.assertNotEqual(web_ui.node_test_run(root=tmp, files=[style], report=report, name_pattern="^never-matches$"), 0, style)

    def test_node_runner_fails_closed_without_node_or_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report, receipt = tmp / "node.xml", tmp / "summary.json"
            report.write_text('<testsuites><testcase name="stale"/></testsuites>')
            receipt.write_text('{"ok":true}')
            with mock.patch("sys.stderr"):
                self.assertEqual(web_ui.node_test_run(root=tmp, files=["x.test.mjs"], report=report, receipt=receipt, node="__node_does_not_exist__"), 127)
                self.assertEqual((report.exists(), receipt.exists()), (False, False))
                self.assertEqual(web_ui.node_test_run(root=tmp, files=[], report=report), 2)

    # --- a child that is meant to fail (python/tests/test_expected_child_failure.py)
    def child(self, expect, code, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evidence"
            status, receipt = web_ui.expected_child_failure([sys.executable, "-c", code], expect_exit=expect, output_dir=out, **kwargs)
            return status, receipt, {n: (out / n).read_bytes() for n in ("stdout.bin", "stderr.bin")}, json.loads((out / "receipt.json").read_text())

    def test_an_expected_failure_is_recorded_without_failing_the_outer_test(self):
        status, receipt, streams, saved = self.child([7], "import sys; print('intentional stdout'); print('intentional stderr', file=sys.stderr); raise SystemExit(7)")
        self.assertEqual((status, receipt["schema"], receipt["exit_code"], receipt["expected_exit_codes"], receipt["matched_expectation"], receipt["argument_count"]),
                         (0, "expected-child-failure/1", 7, [7], True, 2))
        self.assertEqual((streams["stdout.bin"], streams["stderr.bin"]), (b"intentional stdout\n", b"intentional stderr\n"))
        self.assertEqual(saved, receipt)

    def test_an_unexpected_result_fails_the_outer_contract(self):
        status, receipt, _, _ = self.child([7], "raise SystemExit(3)")
        self.assertEqual((status, receipt["exit_code"], receipt["matched_expectation"]), (1, 3, False))

    def test_zero_cannot_be_an_expected_failure(self):
        for expect in ([0], [], [7, 0]):
            with self.assertRaises(ValueError, msg=expect):
                web_ui.expected_child_failure([sys.executable, "-c", "pass"], expect_exit=expect, output_dir=Path(tempfile.gettempdir()) / "unused-evidence")
        with self.assertRaises(ValueError):
            web_ui.expected_child_failure([sys.executable], expect_exit=[7], output_dir=Path(tempfile.gettempdir()) / "unused-evidence", timeout=0)
        with self.assertRaises(ValueError):
            web_ui.expected_child_failure([], expect_exit=[7], output_dir=Path(tempfile.gettempdir()) / "unused-evidence")

    def test_a_timeout_is_bounded_and_recorded(self):
        status, receipt, _, _ = self.child([7], "import time; time.sleep(5)", timeout=0.2)
        self.assertEqual((status, receipt["timed_out"], receipt["exit_code"], receipt["matched_expectation"]), (1, True, None, False))
        self.assertGreater(receipt["stream_limit_bytes"], 0)

    def test_large_output_is_truncated_and_marked(self):
        status, receipt, streams, _ = self.child([7], "import sys; sys.stdout.write('x' * (2 * 1024 * 1024)); raise SystemExit(7)")
        self.assertEqual((status, receipt["stdout_truncated"], receipt["stderr_truncated"], len(streams["stdout.bin"])), (0, True, False, receipt["stream_limit_bytes"]))

    # --- what the page shows
    def test_the_page_reads_either_kind_and_explains_what_it_could_not_do(self):
        junit = '<testsuite><testcase name="a"/><testcase classname="c" name="b"><failure message="m"/></testcase></testsuite>'
        read = web_ui.report_read(junit)
        self.assertEqual((read["kind"], read["line"], read["ok"], len(read["failures"])), ("junit", "passed=1 failed=1 skipped=0 xfailed=0 xpassed=0 error=0 total=2 ok=false", False, 1))
        stream = ndjson([{"type": "suite", "suite": {"id": 0, "path": "t.dart"}}, *flutter_case(1, 0, "ok"), *flutter_case(2, 0, "bad", result="failure"), {"type": "done", "success": False}])
        flutter = web_ui.report_read(stream)
        self.assertEqual((flutter["kind"], flutter["counts"]["failed"], flutter["failures"][0]["name"], flutter["junit"] is not None, flutter["convert_error"]), ("flutter", 1, "bad", True, None))
        partial = web_ui.report_read(ndjson(flutter_case(1, 0, "ok")))
        self.assertEqual((partial["junit"], partial["convert_error"], partial["failures"]), (None, "incomplete Flutter machine report", []))
        self.assertIn("diff", web_ui.report_read(junit, junit))
        self.assertNotIn("diff", web_ui.report_read(junit, "   "))
        with self.assertRaises(ValueError):
            web_ui.report_read(stream, junit)
        for text in ("", "plain words", "[1]"):
            with self.assertRaises(ValueError, msg=text):
                web_ui.report_read(text)
        self.assertEqual([web_ui.report_kind(t) for t in ("<a/>", "  \n<a/>", "﻿<a/>", "{}", " {", "x", "")], ["junit", "junit", "junit", "flutter", "flutter", None, None])

    def test_the_command_line_reads_reports_and_converts_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            good, bad, older = tmp / "good.xml", tmp / "bad.xml", tmp / "older.xml"
            good.write_text('<testsuite><testcase name="a"/></testsuite>')
            bad.write_text('<testsuite><testcase name="a"/><testcase name="b"><failure message="m"/></testcase></testsuite>')
            older.write_text('<testsuite><testcase name="a"/><testcase name="gone"><failure/></testcase></testsuite>')
            run = lambda *args, **kw: subprocess.run([sys.executable, "-S", str(ROOT / "web_ui.py"), *args], capture_output=True, text=True, timeout=60, **kw)
            ok = run("--junit", str(good))
            self.assertEqual((ok.returncode, json.loads(ok.stdout)["ok"]), (0, True))
            failing = run("--junit", str(bad), "--previous", str(older))
            self.assertEqual(failing.returncode, 1)
            self.assertEqual(json.loads(failing.stdout)["diff"]["summary"], {"new": 1, "recurring": 0, "resolved": 1})
            both = run("--junit", str(good), str(bad))
            self.assertEqual((both.returncode, len(both.stdout.strip().splitlines())), (1, 2))
            invalid = run("--junit", str(tmp / "missing.xml"))
            self.assertEqual(invalid.returncode, 2)
            self.assertNotIn(str(tmp), invalid.stderr.replace("missing.xml", ""))
            events = tmp / "events.jsonl"
            events.write_text(ndjson([*flutter_case(1, 0, "ok"), {"type": "done", "success": True}]))
            counts = run("--flutter-events", str(events), "--to", str(tmp / "out.xml"))
            self.assertEqual(counts.returncode, 0, counts.stderr)
            self.assertIn("passed=1", counts.stdout)
            self.assertEqual(web_ui.junit_inspect((tmp / "out.xml").read_text())["tests"], 1)
            events.write_text("{broken")
            self.assertEqual(run("--flutter-events", str(events)).returncode, 1)
            self.assertEqual(run("--flutter-events", str(events), "--to", str(tmp / "never.xml")).returncode, 2)
            self.assertFalse((tmp / "never.xml").exists())
            expected = run("--expect-exit", "7", "--output-dir", str(tmp / "evidence"), "--", sys.executable, "-c", "raise SystemExit(7)")
            self.assertEqual(expected.returncode, 0, expected.stderr)
            self.assertEqual(json.loads((tmp / "evidence" / "receipt.json").read_text())["matched_expectation"], True)
            self.assertEqual(run("--expect-exit", "0", "--output-dir", str(tmp / "e2"), "--", sys.executable, "-c", "pass").returncode, 2)


class McpTests(unittest.TestCase):
    """The MCP foundation: test/shared/mcp/mcp_foundation_test.dart and mcp_integration_test.dart of flutter_navigation_basic are the golden values (ported case by case);
    RFC 7636 Appendix B is the PKCE oracle."""

    LEGACY, CURRENT = "2025-03-26", "2026-07-28"
    META = "io.modelcontextprotocol/protocolVersion"

    def routes(self, session="sess-1", **kwargs):
        return web_ui.McpRoutes(web_ui.McpFoundation(lambda: session), **kwargs)

    def post(self, routes, body, headers=None, method="POST", path="/mcp"):
        return routes.handle(method, path, headers or {}, json.dumps(body) if not isinstance(body, str) and body is not None else body)

    def init_body(self, rid=1, version=None):
        return {"jsonrpc": "2.0", "id": rid, "method": "initialize", "params": {"protocolVersion": version or self.LEGACY, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}

    def modern_meta(self, version=None):
        return {self.META: version or self.CURRENT, "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"}, "io.modelcontextprotocol/clientCapabilities": {}}

    def modern_headers(self, method, name=None, version=None):
        out = {"mcp-protocol-version": version or self.CURRENT, "mcp-method": method}
        if name is not None:
            out["mcp-name"] = name
        return out

    # --- JSON-RPC
    def test_a_request_is_parsed_or_refused(self):
        ok = web_ui.rpc_request_parse({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual((ok["method"], web_ui.rpc_is_notification(ok)), ("ping", False))
        self.assertTrue(web_ui.rpc_is_notification(web_ui.rpc_request_parse('{"jsonrpc":"2.0","method":"x"}')))
        self.assertTrue(web_ui.rpc_is_notification(web_ui.rpc_request_parse('{"jsonrpc":"2.0","id":null,"method":"x"}')))
        for bad in ({"jsonrpc": "1.0", "method": "ping"}, {"jsonrpc": "2.0"}, {"jsonrpc": "2.0", "method": ""}, {"jsonrpc": "2.0", "method": 5}, "[1]", "{broken", "NaN", '{"jsonrpc":"2.0","method":"a","x":NaN}', None, 42, []):
            self.assertIsNone(web_ui.rpc_request_parse(bad), bad)
        self.assertEqual(web_ui.rpc_request("ping"), {"jsonrpc": "2.0", "method": "ping"})
        self.assertEqual(list(web_ui.rpc_request("a", id=1, params={})), ["jsonrpc", "id", "method", "params"])

    def test_a_response_must_have_exactly_one_of_result_and_error(self):
        parse = web_ui.rpc_response_parse
        for bad in ({"jsonrpc": "1.0", "id": 1, "result": {"ok": True}}, {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -1, "message": "x"}}, {"jsonrpc": "2.0", "id": 1},
                    {"jsonrpc": "2.0", "id": 1, "error": {"code": "-32603", "message": "x"}}, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": 42}},
                    {"jsonrpc": "2.0", "id": 1, "error": {"message": "x"}}, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603}}, {"jsonrpc": "2.0", "id": 1, "error": "text"},
                    {"jsonrpc": "2.0", "id": 1, "error": {"code": True, "message": "x"}}, [], None):
            with self.assertRaises(ValueError, msg=bad):
                parse(bad)
        with self.assertRaises(ValueError):
            parse({"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}, 1)
        self.assertEqual(parse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, 1)["result"], {"ok": True})
        self.assertEqual(parse({"jsonrpc": "2.0", "id": 2, "result": 1})["id"], 2, "no expected id: nothing to compare")
        valid = parse({"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "boom", "data": {"k": 1}}})
        self.assertEqual((valid["error"]["code"], valid["error"]["message"], valid["error"]["data"]), (-32603, "boom", {"k": 1}))

    # --- PKCE and OAuth metadata
    def test_pkce_matches_rfc_7636_appendix_b(self):
        self.assertEqual(web_ui.pkce_challenge_s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        pair = web_ui.pkce_pair(web_ui.mulberry32(42).__next__, 64)
        self.assertEqual((len(pair["codeVerifier"]), pair["codeChallengeMethod"], pair["codeChallenge"]), (64, "S256", web_ui.pkce_challenge_s256(pair["codeVerifier"])))
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9._~-]{64}", pair["codeVerifier"]))
        self.assertEqual(len(web_ui.pkce_pair(None, 43)["codeVerifier"]), 43)
        self.assertEqual(len(web_ui.pkce_pair(None, 128)["codeVerifier"]), 128)
        for length in (42, 129, 0):
            with self.assertRaises(ValueError):
                web_ui.pkce_pair(None, length)

    AS_DOC = {"issuer": "https://auth.example.test/", "authorization_endpoint": "https://auth.example.test/authorize", "token_endpoint": "https://auth.example.test/token", "response_types_supported": ["code"]}

    def test_oauth_metadata_never_invents_what_a_server_left_out(self):
        full = web_ui.oauth_server_metadata({**self.AS_DOC, "code_challenge_methods_supported": ["S256"], "scopes_supported": ["mcp"]})
        self.assertTrue(full["supportsPkceS256"])
        omitted = web_ui.oauth_server_metadata(self.AS_DOC)
        self.assertEqual((omitted["code_challenge_methods_supported"], omitted["supportsPkceS256"], omitted["token_endpoint_auth_methods_supported"], omitted["grant_types_supported"]),
                         ([], False, ["client_secret_basic"], ["authorization_code", "implicit"]))
        empty = web_ui.oauth_server_metadata({**self.AS_DOC, "code_challenge_methods_supported": [], "token_endpoint_auth_methods_supported": ["none"]})
        self.assertEqual((empty["supportsPkceS256"], empty["token_endpoint_auth_methods_supported"]), (False, ["none"]))
        self.assertTrue(web_ui.oauth_server_metadata({**self.AS_DOC, "code_challenge_methods_supported": ["s256"]})["supportsPkceS256"])
        prm = web_ui.oauth_resource_metadata({"resource": "https://mcp.example.test/", "authorization_servers": ["https://auth.example.test/"], "scopes_supported": ["mcp"]})
        self.assertEqual((len(prm["authorization_servers"]), prm["bearer_methods_supported"]), (1, ["header"]))

    def test_oauth_metadata_rejects_the_wrong_types(self):
        without = {k: v for k, v in self.AS_DOC.items() if k != "response_types_supported"}
        for bad in (without, {**self.AS_DOC, "response_types_supported": []}, {**self.AS_DOC, "response_types_supported": "code"}, {**self.AS_DOC, "response_types_supported": ["code", 1]},
                    {**self.AS_DOC, "registration_endpoint": 123}, {**self.AS_DOC, "registration_endpoint": ""}, {**self.AS_DOC, "issuer": ""}, {**self.AS_DOC, "token_endpoint": None},
                    {**self.AS_DOC, "scopes_supported": None}, {**self.AS_DOC, "code_challenge_methods_supported": "S256"}, [], "x"):
            with self.assertRaises(ValueError, msg=bad):
                web_ui.oauth_server_metadata(bad)
        resource = {"resource": "https://mcp.example.test/", "authorization_servers": ["https://auth.example.test/"]}
        for bad in ({**resource, "authorization_servers": ["https://auth.example.test/", 1]}, {**resource, "authorization_servers": [""]}, {**resource, "authorization_servers": []},
                    {**resource, "resource_name": 9}, {**resource, "resource": ""}, {**resource, "bearer_methods_supported": "header"}, {"authorization_servers": ["a"]}, []):
            with self.assertRaises(ValueError, msg=bad):
                web_ui.oauth_resource_metadata(bad)
        self.assertEqual(web_ui.oauth_resource_metadata({**resource, "scopes_supported": None, "bearer_methods_supported": None})["bearer_methods_supported"], ["header"])
        self.assertEqual(str(self.fail_message(web_ui.oauth_server_metadata, {**without, "issuer": ""})), "missing OAuth metadata field: response_types_supported", "Dart checks the arrays before the issuer")

    @staticmethod
    def fail_message(fn, *args):
        try:
            fn(*args)
        except ValueError as error:
            return error
        raise AssertionError("no error")

    # --- Bearer audience
    def jwt(self, aud, exp):
        return web_ui.demo_bearer_token(aud, exp).rsplit(".", 1)[0] + ".sig"

    def test_bearer_audience_missing_expired_wrong_and_ok(self):
        now = 1789387200       # 2026-09-14 12:00 UTC, the Dart tests' clock
        inspect = lambda header, aud="https://mcp.example.test": web_ui.bearer_inspect(header, aud, now)["status"]
        self.assertEqual(inspect(None), "missing")
        self.assertEqual(inspect(""), "missing")
        self.assertEqual(inspect("Bearer " + self.jwt("https://mcp.example.test", 1)), "expired")
        self.assertEqual(inspect("Bearer " + self.jwt("https://other.test", 9999999999)), "wrong_audience")
        self.assertEqual(inspect("Bearer " + self.jwt("https://mcp.example.test", 9999999999)), "ok")
        self.assertEqual(inspect("Bearer " + self.jwt(["https://a.test", "https://mcp.example.test"], 9999999999)), "ok")
        self.assertEqual(inspect("Bearer " + self.jwt(["https://a.test", "https://b.test"], 9999999999)), "wrong_audience")
        self.assertEqual(inspect("Bearer " + self.jwt(["https://a.test", 42], 9999999999)), "malformed")
        self.assertEqual(inspect("Bearer " + self.jwt([], 9999999999)), "malformed")
        self.assertEqual(inspect("Bearer " + self.jwt([""], 9999999999)), "malformed")
        self.assertEqual(inspect("Bearer " + self.jwt(7, 9999999999)), "malformed")
        self.assertEqual(inspect("Bearer " + self.jwt("https://other.test", 1)), "expired", "expiry is reported before the audience")
        self.assertEqual(inspect("Bearer " + self.jwt("https://mcp.example.test", now)), "expired", "an expiry that is not after now is expired")
        self.assertEqual(inspect("Bearer " + self.jwt("https://mcp.example.test", now + 1)), "ok")
        self.assertEqual(web_ui.bearer_inspect("Bearer " + self.jwt("a", 9999999999), "a", now), {"status": "ok", "audience": "a", "expires_at": 9999999999})
        for bad in ("not-a-jwt", "Bearer not-a-jwt", "Bearer", "Basic abc.def.ghi", "Bearer a b", " Bearer x.y.z", "Bearer x.%%%.z", "Bearer x.W10.z", "Bearer x.bm90LWpzb24.z"):
            self.assertEqual(inspect(bad), "malformed", bad)
        self.assertEqual(inspect("Bearer x.e30=.z"), "wrong_audience", "a payload with no aud has no audience to match")
        self.assertEqual(inspect("bearer " + self.jwt("https://mcp.example.test", 9999999999)), "ok", "the scheme is case-insensitive")
        self.assertEqual(inspect("Bearer\t" + self.jwt("https://mcp.example.test", 9999999999)), "ok")
        no_exp = web_ui.demo_bearer_token("a", 1).split(".")
        no_exp[1] = web_ui._b64url_nopad(b'{"aud":"a"}')
        self.assertEqual(web_ui.bearer_inspect("Bearer " + ".".join(no_exp), "a", now)["status"], "ok", "no exp: no expiry")

    # --- Foundation handler
    def initialize(self, handler, params=None, rid=1):
        request = web_ui.rpc_request("initialize", id=rid, params=params if params is not None else {"protocolVersion": self.LEGACY, "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
        return handler.handle_rpc(request)

    def test_the_session_flow_initialize_list_call(self):
        handler = web_ui.McpFoundation(lambda: "sess-1")
        response, session = self.initialize(handler)
        self.assertEqual((session, response["result"]["protocolVersion"]), ("sess-1", self.LEGACY))
        listed, _ = handler.handle_rpc(web_ui.rpc_request("tools/list", id=2), "sess-1")
        self.assertTrue(listed["result"]["tools"])
        called, _ = handler.handle_rpc(web_ui.rpc_request("tools/call", id=3, params={"name": "echo", "arguments": {"text": "hi"}}), "sess-1")
        self.assertEqual(called["result"]["content"][0]["text"], "hi")
        self.assertEqual(called["result"]["isError"], False)

    def test_an_unsupported_client_version_negotiates_down_to_the_pin(self):
        response, session = self.initialize(web_ui.McpFoundation(lambda: "sess-1"), {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": {"name": "x", "version": "0"}})
        self.assertEqual((response["result"]["protocolVersion"], session), (self.LEGACY, "sess-1"))

    def test_initialize_rejects_missing_and_malformed_fields_without_a_session(self):
        info = {"name": "x", "version": "0"}
        v = self.LEGACY
        cases = [{"capabilities": {}, "clientInfo": info}, {"protocolVersion": 20250326, "capabilities": {}, "clientInfo": info}, {"protocolVersion": "", "capabilities": {}, "clientInfo": info},
                 {"protocolVersion": v, "clientInfo": info}, {"protocolVersion": v, "capabilities": "nope", "clientInfo": info}, {"protocolVersion": v, "capabilities": {}},
                 {"protocolVersion": v, "capabilities": {}, "clientInfo": "nope"}, {"protocolVersion": v, "capabilities": {}, "clientInfo": {}},
                 {"protocolVersion": v, "capabilities": {}, "clientInfo": {"version": "0"}}, {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "x"}},
                 {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "", "version": "0"}}, {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "x", "version": ""}},
                 {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": 1, "version": "0"}}, {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "x", "version": 2}}, "nope", None]
        for params in cases:
            handler = web_ui.McpFoundation(lambda: "sess-1")
            response, session = handler.handle_rpc(web_ui.rpc_request("initialize", id=1, params=params))
            self.assertEqual((response["error"]["code"], session, handler.session("sess-1")), (web_ui.RPC_INVALID_PARAMS, None, None), params)

    def test_requests_that_need_a_session_say_so(self):
        handler = web_ui.McpFoundation(lambda: "sess-1")
        no_session, _ = handler.handle_rpc(web_ui.rpc_request("tools/list", id=1))
        self.assertEqual(no_session["error"]["code"], web_ui.RPC_SESSION_REQUIRED)
        initialized, _ = handler.handle_rpc(web_ui.rpc_request("notifications/initialized"))
        self.assertEqual(initialized["error"]["code"], web_ui.RPC_SESSION_REQUIRED)
        unknown, returned = handler.handle_rpc(web_ui.rpc_request("ping", id=2), "nope")
        self.assertEqual((unknown["error"]["code"], returned), (web_ui.RPC_SESSION_INVALID, "nope"))
        self.initialize(handler)
        for request in (web_ui.rpc_request("resources/list", id=2), web_ui.rpc_request("prompts/get", id=3, params={"name": "greet"}), web_ui.rpc_request("ping", id=4),
                        web_ui.rpc_request("notifications/initialized"), web_ui.rpc_request("resources/read", id=5, params={"uri": "demo://readme"})):
            self.assertNotIn("error", handler.handle_rpc(request, "sess-1")[0], request)
        self.assertEqual(handler.handle_rpc(web_ui.rpc_request("ping", id=4), "sess-1")[0]["result"], {})
        for bad in (web_ui.rpc_request("tools/call", id=6, params={"name": "nope"}), web_ui.rpc_request("tools/call", id=6, params={"name": "echo", "arguments": {"text": 5}}),
                    web_ui.rpc_request("tools/call", id=6, params={"name": "echo"}), web_ui.rpc_request("resources/read", id=6, params={"uri": "x"}), web_ui.rpc_request("prompts/get", id=6, params={"name": "x"})):
            self.assertEqual(handler.handle_rpc(bad, "sess-1")[0]["error"]["code"], web_ui.RPC_INVALID_PARAMS, bad)

    def test_default_session_ids_are_high_entropy_and_do_not_repeat(self):
        ids = [web_ui.mcp_session_id() for _ in range(20)]
        self.assertEqual(len(set(ids)), 20)
        for item in ids:
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{24}", item), item)
        seeded = web_ui.mulberry32(5)
        self.assertEqual(web_ui.mcp_session_id(seeded.__next__), web_ui.mcp_session_id(web_ui.mulberry32(5).__next__))
        self.assertEqual(len(web_ui.mcp_session_id(seeded.__next__, 5)), 7)
        handler = web_ui.McpFoundation()
        a = self.initialize(handler)[1]
        b = self.initialize(handler)[1]
        self.assertNotEqual(a, b)
        self.assertEqual(sorted(handler.sessions), sorted([a, b]))

    # --- HTTP routes: sessions, Origin, auth, discovery
    def test_session_required_and_session_not_found(self):
        routes = self.routes("sess-http")
        missing = self.post(routes, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((missing["status"], missing["body"]["error"]), (400, "session_required"))
        unknown = self.post(routes, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"mcp-session-id": "nope"})
        self.assertEqual((unknown["status"], unknown["body"]["error"]), (404, "session_not_found"))
        legacy = self.post(routes, {"jsonrpc": "2.0", "id": 6, "method": "tools/list"})
        self.assertEqual((legacy["status"], legacy["body"]["error"]), (400, "session_required"))

    def test_origin_allowed_rejected_and_absent(self):
        routes = self.routes("sess-http")
        init = self.post(routes, self.init_body())
        self.assertEqual(init["status"], 200)
        session = init["headers"]["mcp-session-id"]
        listed = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        self.assertEqual(self.post(routes, listed, {"mcp-session-id": session, "origin": "http://127.0.0.1:8787"})["status"], 200)
        self.assertEqual(self.post(routes, listed, {"mcp-session-id": session, "origin": "http://localhost:8787"})["status"], 200)
        rejected = self.post(routes, {**listed, "id": 3}, {"mcp-session-id": session, "origin": "https://evil.example"})
        self.assertEqual((rejected["status"], rejected["body"]), (403, {"error": "origin_forbidden", "origin": "https://evil.example"}))
        self.assertEqual(self.post(routes, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"mcp-session-id": session})["status"], 202)
        self.assertEqual(self.post(routes, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"mcp-session-id": session, "ORIGIN": "https://evil.example"})["status"], 403, "header names ignore case")

    def test_bearer_invalid_expired_or_for_another_audience_is_401_or_403(self):
        routes = self.routes("sess-auth", expected_audience="http://127.0.0.1:8787/mcp", clock=lambda: 1789387200)
        session = self.post(routes, self.init_body())["headers"]["mcp-session-id"]
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        token = lambda aud, exp: "Bearer " + web_ui.demo_bearer_token(aud, exp)
        expired = self.post(routes, note, {"mcp-session-id": session, "authorization": token("http://127.0.0.1:8787/mcp", 1577836800)})
        self.assertEqual((expired["status"], expired["body"]["error"], expired["body"]["reason"]), (401, "unauthorized", {"reason": "expired"}))
        wrong = self.post(routes, note, {"mcp-session-id": session, "authorization": token("http://evil.example/mcp", 4070908800)})
        self.assertEqual((wrong["status"], wrong["body"]["error"], wrong["body"]["reason"]), (403, "forbidden", {"reason": "wrong_audience"}))
        self.assertEqual(self.post(routes, note, {"mcp-session-id": session, "authorization": "Bearer not-a-jwt"})["status"], 401)
        ok = self.post(routes, note, {"mcp-session-id": session, "authorization": token("http://127.0.0.1:8787/mcp", 4070908800)})
        self.assertEqual(ok["status"], 202)
        self.assertEqual(self.post(routes, note, {"mcp-session-id": session})["status"], 202, "no Authorization header: no gate")

    def test_discovery_follows_the_listen_port(self):
        routes = web_ui.McpRoutes.for_port(9999)
        self.assertEqual((routes.issuer, routes.resource, routes.expected_audience), ("http://127.0.0.1:9999", "http://127.0.0.1:9999/mcp", "http://127.0.0.1:9999/mcp"))
        self.assertTrue(web_ui.mcp_origin_allows(routes.allowed_origins, "http://127.0.0.1:9999"))
        self.assertFalse(web_ui.mcp_origin_allows(routes.allowed_origins, "http://127.0.0.1:8787"))
        self.assertTrue(web_ui.mcp_origin_allows(routes.allowed_origins, None) and web_ui.mcp_origin_allows(routes.allowed_origins, ""))
        server = routes.handle("GET", "/.well-known/oauth-authorization-server", {}, None)
        self.assertEqual((server["status"], server["body"]["issuer"], server["body"]["authorization_endpoint"], server["body"]["token_endpoint"]),
                         (200, "http://127.0.0.1:9999", "http://127.0.0.1:9999/oauth/authorize", "http://127.0.0.1:9999/oauth/token"))
        self.assertEqual(server["body"]["code_challenge_methods_supported"], ["S256"])
        self.assertNotIn("supportsPkceS256", server["body"])
        for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource/"):
            resource = routes.handle("GET", path, {}, None)
            self.assertEqual((resource["body"]["resource"], resource["body"]["authorization_servers"]), ("http://127.0.0.1:9999/mcp", ["http://127.0.0.1:9999"]), path)
        matrix = routes.handle("GET", "/mcp/support-matrix", {}, None)["body"]
        self.assertEqual((matrix["specificationVersion"], matrix["currentOfficialVersion"], matrix["flutterWebInAppOAuthGuaranteed"], matrix["legacySseDefault"], matrix["legacyMcpEra"],
                          matrix["currentOfficialEra"], matrix["implementsCurrentOfficial"]), (self.LEGACY, self.CURRENT, False, False, True, True, True))
        self.assertIsNone(routes.handle("GET", "/nope", {}, None))
        not_post = routes.handle("GET", "/mcp", {}, None)
        self.assertEqual((not_post["status"], not_post["body"], not_post["headers"]), (405, {"error": "method_not_allowed"}, {"allow": "POST"}))
        self.assertEqual(routes.handle("get", "/mcp/", {}, None)["status"], 405)

    def test_a_body_that_is_not_json_rpc_is_a_parse_error(self):
        routes = self.routes()
        for body in ("{broken", "[]", '{"jsonrpc":"1.0","method":"x"}', None, ""):
            out = routes.handle("POST", "/mcp", {}, body)
            self.assertEqual((out["status"], out["body"]["error"]["code"], out["body"]["id"]), (400, web_ui.RPC_PARSE_ERROR, None), body)

    # --- the current-official era
    def test_server_discover_and_modern_calls_need_no_session(self):
        routes = self.routes("sess-modern")
        discover = self.post(routes, {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": self.modern_meta()}}, self.modern_headers("server/discover"))
        self.assertEqual((discover["status"], discover["body"]["result"]["resultType"], discover["headers"]["mcp-protocol-version"]), (200, "complete", self.CURRENT))
        self.assertEqual(discover["body"]["result"]["protocolVersions"], [self.LEGACY, self.CURRENT])
        self.assertNotIn("mcp-session-id", discover["headers"])
        listed = self.post(routes, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": self.modern_meta()}}, self.modern_headers("tools/list"))
        result = listed["body"]["result"]
        self.assertEqual((listed["status"], result["resultType"], result["ttlMs"], result["cacheScope"]), (200, "complete", 60000, "private"))
        called = self.post(routes, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "via-http"}, "_meta": self.modern_meta()}},
                           self.modern_headers("tools/call", "echo"))
        self.assertEqual((called["status"], called["body"]["result"]["resultType"], called["body"]["result"]["content"][0]["text"]), (200, "complete", "via-http"))
        self.assertNotIn("ttlMs", called["body"]["result"])

    def test_modern_resources_and_prompts_have_the_modern_shape(self):
        routes = self.routes()
        def modern(method, rid, params=None, name=None):
            return self.post(routes, {"jsonrpc": "2.0", "id": rid, "method": method, "params": {**(params or {}), "_meta": self.modern_meta()}}, self.modern_headers(method, name))["body"]["result"]
        for method in ("resources/list", "prompts/list"):
            result = modern(method, 71)
            self.assertEqual((result["resultType"], result["ttlMs"], result["cacheScope"]), ("complete", 60000, "private"), method)
        self.assertEqual(modern("resources/list", 71)["resources"][0]["uri"], "demo://readme")
        self.assertEqual(modern("resources/read", 72, {"uri": "demo://readme"}, "demo://readme")["resultType"], "complete")
        self.assertEqual(modern("prompts/get", 74, {"name": "greet"}, "greet")["resultType"], "complete")
        ping = self.post(routes, {"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {"_meta": self.modern_meta()}}, self.modern_headers("ping"))
        self.assertEqual((ping["status"], ping["body"]["error"]["code"]), (200, web_ui.RPC_SESSION_REQUIRED), "ping has no modern form here: the routes answer 200 with the JSON-RPC error")
        shaped = web_ui.McpFoundation()._modern_or_session({"id": 1, "method": "x", "params": {"_meta": {self.META: self.CURRENT}}}, None, lambda _s: web_ui.rpc_result(1, 5))
        self.assertEqual(shaped[0]["result"], {"resultType": "complete", "value": 5})

    def test_a_modern_unknown_method_is_404_and_a_legacy_one_is_200(self):
        routes = self.routes("sess-modern")
        modern = self.post(routes, {"jsonrpc": "2.0", "id": 75, "method": "totally/unknown", "params": {"_meta": self.modern_meta()}}, self.modern_headers("totally/unknown"))
        self.assertEqual((modern["status"], modern["body"]["error"]["code"]), (404, web_ui.RPC_METHOD_NOT_FOUND))
        session = self.post(routes, self.init_body())["headers"]["mcp-session-id"]
        legacy = self.post(routes, {"jsonrpc": "2.0", "id": 84, "method": "totally/unknown"}, {"mcp-session-id": session})
        self.assertEqual((legacy["status"], legacy["body"]["error"]["code"], legacy["headers"]["mcp-protocol-version"]), (200, web_ui.RPC_METHOD_NOT_FOUND, self.LEGACY))

    def modern_failure(self, headers, body, expect_status=400):
        out = self.post(self.routes(), body, headers)
        self.assertEqual(out["status"], expect_status, body)
        self.assertEqual(out["headers"], {"mcp-protocol-version": self.CURRENT})
        return out["body"]["error"]

    def test_modern_envelope_failures_are_400_with_the_right_code_and_message(self):
        discover = lambda meta, rid=70: {"jsonrpc": "2.0", "id": rid, "method": "server/discover", "params": {"_meta": meta}}
        headers = self.modern_headers("server/discover")
        meta = self.modern_meta()
        self.assertIn("clientInfo", self.modern_failure(headers, discover({self.META: self.CURRENT}))["message"])
        self.assertIn("clientInfo", self.modern_failure(headers, discover({**meta, "io.modelcontextprotocol/clientInfo": "nope"}))["message"])
        self.assertIn("clientInfo.name", self.modern_failure(headers, discover({**meta, "io.modelcontextprotocol/clientInfo": {"name": "", "version": "0"}}))["message"])
        self.assertIn("clientInfo.version", self.modern_failure(headers, discover({**meta, "io.modelcontextprotocol/clientInfo": {"name": "x"}}))["message"])
        self.assertIn("clientCapabilities", self.modern_failure(headers, discover({**meta, "io.modelcontextprotocol/clientCapabilities": "nope"}))["message"])
        self.assertIn("clientCapabilities", self.modern_failure(headers, discover({self.META: self.CURRENT, "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"}}))["message"])
        missing_method = self.modern_failure({"mcp-protocol-version": self.CURRENT}, discover(meta, 4))
        self.assertEqual((missing_method["code"], missing_method["message"]), (web_ui.RPC_HEADER_MISMATCH, "Mcp-Method header is required"))
        unsupported = self.modern_failure(self.modern_headers("server/discover", version="2099-01-01"), discover(self.modern_meta("2099-01-01"), 5))
        self.assertEqual((unsupported["code"], unsupported["data"]), (web_ui.RPC_UNSUPPORTED_VERSION, {"supported": [self.LEGACY, self.CURRENT], "requested": "2099-01-01"}))
        mismatch = self.modern_failure(headers, discover(self.modern_meta(self.LEGACY), 81))
        self.assertEqual((mismatch["code"], mismatch["message"], mismatch["data"]), (web_ui.RPC_HEADER_MISMATCH, "MCP-Protocol-Version does not match body _meta", {"header": self.CURRENT, "meta": self.LEGACY}))
        method_mismatch = self.modern_failure(self.modern_headers("tools/list"), discover(meta, 80))
        self.assertEqual((method_mismatch["code"], method_mismatch["data"]), (web_ui.RPC_HEADER_MISMATCH, {"header": "tools/list", "method": "server/discover"}))
        self.assertIn("Mcp-Method", method_mismatch["message"])
        call = lambda: {"jsonrpc": "2.0", "id": 82, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "x"}, "_meta": meta}}
        self.assertIn("Mcp-Name", self.modern_failure(self.modern_headers("tools/call"), call())["message"])
        wrong_name = self.modern_failure(self.modern_headers("tools/call", "other"), call())
        self.assertEqual((wrong_name["message"], wrong_name["data"]), ("Mcp-Name does not match body params", {"header": "other", "decoded": "other", "expected": "echo"}))
        malformed = self.modern_failure(self.modern_headers("tools/call", "=?base64?!!!?="), call())
        self.assertIn("malformed", malformed["message"])

    def test_header_only_and_meta_only_modern_markers(self):
        header_only = self.modern_failure({"mcp-protocol-version": self.CURRENT, "mcp-method": "totally/unknown"}, {"jsonrpc": "2.0", "id": 10, "method": "totally/unknown"})
        self.assertEqual(header_only["code"], web_ui.RPC_HEADER_MISMATCH)
        meta_only = self.modern_failure({"mcp-method": "totally/unknown"}, {"jsonrpc": "2.0", "id": 15, "method": "totally/unknown", "params": {"_meta": self.modern_meta()}})
        self.assertIn("MCP-Protocol-Version", meta_only["message"])
        legacy_versions = self.modern_failure({"mcp-protocol-version": self.LEGACY, "mcp-method": "x"}, {"jsonrpc": "2.0", "id": 16, "method": "x", "params": {"_meta": self.modern_meta(self.LEGACY)}})
        self.assertEqual(legacy_versions["code"], web_ui.RPC_UNSUPPORTED_VERSION)
        no_meta = self.modern_failure({"mcp-protocol-version": self.CURRENT}, {"jsonrpc": "2.0", "id": 17, "method": "x", "params": []})
        self.assertEqual(no_meta["message"], "params._meta is required")
        no_version = self.modern_failure({"mcp-protocol-version": self.CURRENT}, {"jsonrpc": "2.0", "id": 18, "method": "x", "params": {"_meta": {}}})
        self.assertEqual(no_version["message"], "params._meta protocolVersion is required")

    def test_header_names_travel_as_a_base64_sentinel_when_they_must(self):
        unicode_name, spaced, sentinel = "エコー", " leading ", "=?base64?YQ==?="
        for value in (unicode_name, spaced, sentinel, "trailing ", "tab\t", "x" + chr(127), "=?foo?="):
            self.assertTrue(web_ui.mcp_header_needs_encoding(value), repr(value))
        for value in ("echo", "demo://readme", "a b", "", "=?", "?=", "=?x"):
            self.assertFalse(web_ui.mcp_header_needs_encoding(value), repr(value))
        encoded = web_ui.mcp_header_encode(unicode_name)
        self.assertTrue(encoded.startswith("=?base64?"))
        self.assertEqual(web_ui.mcp_header_decode(encoded), unicode_name)
        self.assertEqual(web_ui.mcp_header_decode(spaced), spaced)
        self.assertEqual(web_ui.mcp_header_decode(web_ui.mcp_header_encode(spaced)), spaced)
        self.assertEqual(web_ui.mcp_header_decode(web_ui.mcp_header_encode(sentinel)), sentinel)
        self.assertIsNone(web_ui.mcp_header_decode("=?base64?!!!?="))
        self.assertIsNone(web_ui.mcp_header_decode("=?notbase64?YQ==?="))
        self.assertIsNone(web_ui.mcp_header_decode("=?base64?YQ?="), "padding is required")
        self.assertIsNone(web_ui.mcp_header_decode("=?base64?Y=Q=?="))
        self.assertIsNone(web_ui.mcp_header_decode("=?base64?/w==?="), "bytes that are not UTF-8")
        self.assertEqual(web_ui.mcp_header_decode("=?base64?YQ==?="), "a")
        self.assertEqual((web_ui.mcp_header_encode("echo"), web_ui.mcp_header_decode("echo")), ("echo", "echo"))
        self.assertEqual(web_ui.mcp_header_decode("=?base64?" + base64.b64encode("﻿x".encode()).decode() + "?="), "﻿x", "a BOM is kept")
        routes = self.routes()
        called = self.post(routes, {"jsonrpc": "2.0", "id": 76, "method": "tools/call", "params": {"name": unicode_name, "arguments": {"text": "hi"}, "_meta": self.modern_meta()}},
                           {**self.modern_headers("tools/call"), "mcp-name": encoded})
        self.assertNotEqual(called["status"], 400)
        self.assertNotEqual(called["body"].get("error", {}).get("code"), web_ui.RPC_HEADER_MISMATCH)
        headers = web_ui.mcp_streamable_headers(protocol_version=self.CURRENT, method="tools/call", name=unicode_name)
        self.assertEqual(headers["mcp-name"], encoded)
        self.assertEqual(list(headers), ["content-type", "accept", "mcp-protocol-version", "mcp-method", "mcp-name"])
        legacy = web_ui.mcp_streamable_headers(session_id="s", accept_event_stream=False)
        self.assertEqual(legacy, {"content-type": "application/json", "accept": "application/json", "mcp-protocol-version": self.LEGACY, "mcp-session-id": "s"})
        self.assertNotIn("mcp-session-id", web_ui.mcp_streamable_headers(session_id=""))

    # --- the client (mcp_integration_test.dart)
    def test_both_echo_demos_over_the_handler_and_over_the_routes(self):
        for make in (lambda: web_ui.mcp_foundation_transport(web_ui.McpFoundation()), lambda: web_ui.mcp_in_process(self.routes("sess-demo"))):
            legacy = web_ui.McpClient(make()).run_echo_demo("ping")
            self.assertEqual((legacy["ok"], bool(legacy["session_id"]), len(legacy["log"])), (True, True, 4))
            self.assertEqual(legacy["last_response"]["result"]["content"][0]["text"], "ping")
            modern = web_ui.McpClient(make()).run_modern_echo_demo("modern-ping")
            self.assertEqual((modern["ok"], modern["session_id"]), (True, None))
            self.assertEqual(modern["last_response"]["result"]["content"][0]["text"], "modern-ping")
            self.assertEqual(modern["last_response"]["result"]["resultType"], "complete")
        self.assertEqual(web_ui.McpClient(web_ui.mcp_in_process(self.routes("sess-demo"))).run_echo_demo("x")["session_id"], "sess-demo")
        client = web_ui.McpClient(web_ui.mcp_in_process(self.routes("sess-1")))
        client.run_echo_demo()
        self.assertEqual((client.ping()["result"], client.list_resources()["result"]["resources"][0]["name"], client.list_prompts()["result"]["prompts"][0]["name"]), ({}, "README", "greet"))

    def transport(self, responder):
        return lambda headers, body: responder(headers, web_ui.rpc_request_parse(body))

    def test_a_rejected_initialized_notification_stops_the_demo(self):
        def respond(headers, request):
            if request["method"] == "initialize":
                return {"status_code": 200, "headers": {"mcp-session-id": "sess-reject-init"}, "body": web_ui.rpc_result(request["id"], {"protocolVersion": self.LEGACY, "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}})}
            if request["method"] == "notifications/initialized":
                return {"status_code": 404, "headers": {}, "body": {"error": "session_invalid"}}
            return {"status_code": 500, "headers": {}, "body": {"error": "unexpected"}}
        result = web_ui.McpClient(self.transport(respond)).run_echo_demo("nope")
        self.assertFalse(result["ok"])
        self.assertTrue(any("rejected" in line for line in result["log"]))
        self.assertEqual(len(result["log"]), 2)

    def test_a_failed_initialize_does_not_keep_a_session_id(self):
        failing = self.transport(lambda headers, request: {"status_code": 401, "headers": {"mcp-session-id": "should-not-keep"}, "body": web_ui.rpc_result(request["id"], {"protocolVersion": self.LEGACY})})
        client = web_ui.McpClient(failing)
        init = client.initialize()
        self.assertEqual((init["error"]["code"], client.session_id), (web_ui.RPC_UNAUTHORIZED, None))
        lying = self.transport(lambda headers, request: {"status_code": 500, "headers": {"mcp-session-id": "sess-should-not-adopt"}, "body": web_ui.rpc_result(request["id"], {"protocolVersion": self.LEGACY})})
        client = web_ui.McpClient(lying)
        init = client.initialize()
        self.assertEqual((init["error"]["code"], init["error"]["message"], client.session_id), (web_ui.RPC_INTERNAL_ERROR, "HTTP 500 with result-shaped body", None))
        forbidden = web_ui.McpClient(self.transport(lambda headers, request: {"status_code": 403, "headers": {}, "body": {"error": "forbidden"}}))
        self.assertEqual(forbidden.initialize()["error"]["code"], web_ui.RPC_FORBIDDEN)
        plain = web_ui.McpClient(self.transport(lambda headers, request: {"status_code": 502, "headers": {}, "body": {"error": {"nested": 1}}}))
        self.assertEqual(plain.initialize()["error"]["message"], '{"nested":1}')
        self.assertEqual(web_ui.McpClient(self.transport(lambda headers, request: {"status_code": 200, "headers": {}, "body": "text"})).initialize()["error"]["message"], "unexpected transport body")

    def test_a_malformed_json_rpc_error_becomes_a_failure_not_a_crash(self):
        for body in ({"jsonrpc": "2.0", "id": 1, "error": {"code": "-32603", "message": "x"}}, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": 42}},
                     {"jsonrpc": "2.0", "id": 1, "error": {"message": "x"}}, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603}}, {"jsonrpc": "2.0", "id": 99, "result": {}},
                     {"jsonrpc": "2.0", "id": 1}, {"jsonrpc": "1.0", "id": 1, "result": {}}):
            client = web_ui.McpClient(self.transport(lambda headers, request, body=body: {"status_code": 200, "headers": {"mcp-session-id": "sess-should-not-adopt"}, "body": body}))
            init = client.initialize()
            self.assertIn("invalid JSON-RPC response", init["error"]["message"], body)
            self.assertIsNone(client.session_id)

    def test_notification_status_parity(self):
        modern = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {"_meta": self.modern_meta()}}
        headers = web_ui.mcp_streamable_headers(protocol_version=self.CURRENT, method="notifications/initialized")
        post = lambda transport: transport(headers, json.dumps(modern))
        unauthorized = post(web_ui.mcp_foundation_transport(web_ui.McpFoundation(), {"status": "unauthorized", "reason": "expired"}))
        self.assertEqual((unauthorized["status_code"], unauthorized["body"]["error"], unauthorized["body"]["message"], unauthorized["body"]["reason"]), (401, "unauthorized", "unauthorized", {"reason": "expired"}))
        forbidden = post(web_ui.mcp_foundation_transport(web_ui.McpFoundation(), {"status": "forbidden", "reason": "wrong_audience"}))
        self.assertEqual((forbidden["status_code"], forbidden["body"]["error"]), (403, "forbidden"))
        rejected = post(web_ui.mcp_foundation_transport(web_ui.McpFoundation()))
        self.assertEqual((rejected["status_code"], rejected["body"]["error"], rejected["body"]["code"]), (400, "notification_rejected", web_ui.RPC_SESSION_REQUIRED))
        transport = web_ui.mcp_foundation_transport(web_ui.McpFoundation(lambda: "sess-notif-ok"))
        init = transport({}, json.dumps(self.init_body()))
        session = init["headers"]["mcp-session-id"]
        accepted = transport({"mcp-session-id": session}, json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual((init["status_code"], accepted["status_code"], accepted["body"]), (200, 202, None))

    def test_the_foundation_transport_maps_session_errors_to_http_statuses(self):
        transport = web_ui.mcp_foundation_transport(web_ui.McpFoundation())
        missing = transport({}, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "totally/unknown"}))
        self.assertEqual((missing["status_code"], missing["body"]["error"]), (400, "session_required"))
        unknown = transport({"mcp-session-id": "no-such-session"}, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "totally/unknown"}))
        self.assertEqual((unknown["status_code"], unknown["body"]["error"]), (404, "session_not_found"))
        ping = transport(web_ui.mcp_streamable_headers(protocol_version=self.CURRENT, method="ping"), json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {"_meta": self.modern_meta()}}))
        self.assertEqual((ping["status_code"], ping["body"]["error"]["code"]), (400, web_ui.RPC_SESSION_REQUIRED), "the in-process transport maps a session error to 400; the routes answer 200")
        origin = transport({"origin": "https://evil.example"}, json.dumps(self.init_body()))
        self.assertEqual(origin["status_code"], 200, "the in-process transport ignores Origin")
        parse = transport({}, "{broken")
        self.assertEqual((parse["status_code"], parse["body"]["error"]["code"]), (400, web_ui.RPC_PARSE_ERROR))

    def test_the_lab_exchange_wraps_the_routes(self):
        routes = self.routes("sess-lab")
        sent = web_ui.mcp_exchange(routes, {"body": self.init_body()})
        self.assertEqual((sent["status"], sent["headers"]["mcp-session-id"]), (200, "sess-lab"))
        self.assertEqual(web_ui.mcp_exchange(routes, {"method": "GET", "path": "/nope"})["status"], 404)
        self.assertEqual(web_ui.mcp_exchange(routes, {"method": "GET", "path": "/mcp"})["status"], 405)
        for bad in ({"headers": []}, {"headers": {"a": 1}}):
            with self.assertRaises(ValueError):
                web_ui.mcp_exchange(routes, bad)

    def test_the_page_is_self_contained_and_in_the_index(self):
        html = web_ui.mcp_document()
        for needle in ("data-ui-mcp", "data-mcp-send", "data-mcp-template=\"toolsCall\"", "data-mcp-demo-legacy", "data-mcp-codec-in", "data-mcp-verifier", "data-mcp-auth", "data-mcp-meta", "aria-live=\"polite\""):
            self.assertIn(needle, html)
        self.assertEqual(html.count("<script"), 1)
        self.assertIn("examples/mcp-lab.html", web_ui.example_pages())
        self.assertIn("./mcp-lab.html", web_ui.example_pages()["examples/index.html"])
        self.assertIn("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", html)


PATTERN_ASSETS = json.loads((Path(__file__).resolve().parent / "fixtures" / "pattern_assets.json").read_text(encoding="utf-8"))
PATTERN_GOLDEN = json.loads((Path(__file__).resolve().parent / "fixtures" / "pattern_golden.json").read_text(encoding="utf-8"))


def typed(value):
    """JSON text that keeps 1, 1.0 and true apart (== does not) and ignores object key order."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


class PatternTests(unittest.TestCase):
    """The 792-pattern references. The golden values are the original flutter_navigation_basic oracles' own outputs (recorded, never produced by this code)."""

    go = staticmethod(web_ui.pattern_run)

    def refused(self, family, request, message=None):
        with self.assertRaises(ValueError) as caught:
            self.go(family, request)
        if message is not None:
            self.assertEqual(str(caught.exception), message)

    def test_every_asset_the_dart_app_shows_is_reproduced_exactly(self):
        assets = PATTERN_ASSETS["assets"]
        self.assertEqual(len(assets), 34)
        self.assertEqual({a["family"] for a in assets}, {"collection", "order", "select", "structure", "text", "window"})
        for asset in assets:
            with self.subTest(asset["asset"]):
                self.assertEqual(typed(self.go(asset["family"], asset["request"])), typed(asset["expected"]))

    def test_the_recorded_original_outputs_are_reproduced_exactly(self):
        cases = PATTERN_GOLDEN["cases"]
        self.assertGreaterEqual(len(cases), 800)
        seen: dict[str, set[str]] = {}
        for index, case in enumerate(cases):
            kind = "ok" if "ok" in case else "error"
            seen.setdefault(case["family"], set()).add(kind)
            with self.subTest(index=index, family=case["family"]):
                if kind == "ok":
                    self.assertEqual(typed(self.go(case["family"], case["request"])), typed(case["ok"]))
                else:
                    self.refused(case["family"], case["request"], case["error"])
        self.assertEqual(set(seen), set(web_ui.PATTERN_RUNNERS))
        for family in set(web_ui.PATTERN_RUNNERS) - {"text", "structure"}:      # the two example-only families have nothing to refuse except an unknown mode
            self.assertEqual(seen[family], {"ok", "error"}, family)

    # --- query -----------------------------------------------------------------------------------------------------------------------------------
    def test_sorting_is_stable_in_both_directions(self):
        items = [{"k": 1, "i": 0}, {"k": 0, "i": 1}, {"k": 1, "i": 2}]
        order = lambda extra: [row["i"] for row in self.go("query", {"operation": "stable_sort", "items": items, "key": "k", **extra})]
        self.assertEqual(order({}), [1, 0, 2])
        self.assertEqual(order({"descending": True}), [0, 2, 1])
        self.assertEqual([r["i"] for r in self.go("query", {"operation": "custom_sort", "items": items, "key": "k", "comparator": "descending"})], [0, 2, 1])
        self.refused("query", {"operation": "stable_sort", "items": [{"k": 1}, {"k": "a"}], "key": "k"}, "mixed sort key types")
        self.refused("query", {"operation": "stable_sort", "items": [{"k": True}], "key": "k"}, "unsupported sort key")
        self.refused("query", {"operation": "custom_sort", "items": items, "key": "k", "comparator": "lambda"}, "unsupported comparator")
        self.refused("query", {"operation": "stable_sort", "items": items, "key": "k", "descending": 1}, "descending must be boolean")

    def test_grouping_keeps_one_true_and_one_point_zero_apart(self):
        groups = self.go("query", {"operation": "group_by", "key": "g", "items": [{"g": 1}, {"g": 1.0}, {"g": True}, {"g": 1}, {"g": None}]})
        self.assertEqual([typed(g["value"]) for g in groups], ["1", "1.0", "true", "null"])
        self.assertEqual([len(g["items"]) for g in groups], [2, 1, 1, 1])
        self.refused("query", {"operation": "group_by", "key": "g", "items": [{"g": [1]}]}, "group key must be scalar")

    def test_filters_and_the_geographic_radius(self):
        rows = [{"c": "a", "t": ["x"], "v": 1}, {"c": "b", "t": ["y", "z"], "v": 5}, {"c": "a", "t": [], "v": 9}]
        self.assertEqual([r["v"] for r in self.go("query", {"operation": "facet", "items": rows, "key": "c", "selected": ["a"]})], [1, 9])
        self.assertEqual([r["v"] for r in self.go("query", {"operation": "tag", "items": rows, "key": "t", "selected": ["z", "x"]})], [1, 5])
        self.assertEqual([r["v"] for r in self.go("query", {"operation": "range", "items": rows, "key": "v", "minimum": 5, "maximum": 9})], [5, 9])
        places = [{"name": "Yokohama", "latitude": 35.4437, "longitude": 139.6380}, {"name": "Osaka", "latitude": 34.6937, "longitude": 135.5023}]
        near = lambda radius: [p["name"] for p in self.go("query", {"operation": "geo", "items": places, "latitude": 35.6762, "longitude": 139.6503, "radius_km": radius})]
        self.assertEqual(near(30), ["Yokohama"])
        self.assertEqual(near(20), [])
        self.assertEqual(near(500), ["Yokohama", "Osaka"])
        self.refused("query", {"operation": "geo", "items": [], "latitude": 91, "longitude": 0, "radius_km": 1}, "invalid geographic search")
        self.refused("query", {"operation": "drop", "items": []}, "unsupported operation")

    # --- search ----------------------------------------------------------------------------------------------------------------------------------
    def test_search_helpers(self):
        search = lambda **request: self.go("search", request)
        self.assertEqual(search(operation="tokenize", text="Ｃａｆé, naïve!"), ["café", "naïve"])
        self.assertEqual(search(operation="stem", text="Running walked cats files go"), ["runn", "walk", "cat", "fil", "go"])
        self.assertEqual(search(operation="history", events=["a", "b", "A", "c"]), ["c", "A", "b"])
        self.assertEqual(search(operation="history", events=["a", "b", "c"], limit=2), ["c", "b"])
        self.assertEqual(search(operation="fuzzy", query="cat", values=["cats", "car", "dog", "cat"], max_distance=1), ["cat", "cats", "car"])
        self.assertEqual(search(operation="autocomplete", query="ＡＰ", values=["Apple", "apricot", "banana"], limit=1), ["Apple"])
        self.assertEqual(search(operation="autocomplete", query="", values=["Apple"]), [])
        self.assertEqual(search(operation="highlight", query="NAIVE", text="a naive test"), {"matched": True, "text": "a naive test"})
        self.refused("search", {"operation": "history", "events": [], "limit": 0}, "invalid history limit")
        self.refused("search", {"operation": "regex"}, "unsupported search operation")

    # --- page ------------------------------------------------------------------------------------------------------------------------------------
    def test_pages_by_offset_and_by_cursor_recover_the_dataset(self):
        items = list(range(7))
        self.assertEqual(self.go("page", {"operation": "offset", "items": items, "limit": 3, "offset": 6}), {"items": [6], "has_more": False, "next_offset": None})
        self.assertEqual(self.go("page", {"operation": "offset", "items": items, "limit": 3}), {"items": [0, 1, 2], "has_more": True, "next_offset": 3})
        for mode in ("cursor", "infinite"):
            got, cursor = [], None
            for _ in range(10):
                request = {"operation": mode, "items": items, "limit": 3}
                if cursor is not None:
                    request["cursor"] = cursor
                page = self.go("page", request)
                got.extend(page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            self.assertEqual(got, items, mode)

    def test_a_cursor_is_bound_to_the_exact_dataset(self):
        first = self.go("page", {"operation": "cursor", "items": [1, 2, 3], "limit": 1})
        cursor = first["next_cursor"]
        self.refused("page", {"operation": "cursor", "items": [1, 2, 4], "limit": 1, "cursor": cursor}, "cursor does not match dataset")
        self.refused("page", {"operation": "cursor", "items": [1, 2, 3], "limit": 1, "cursor": cursor[:-2]}, "invalid cursor")
        self.refused("page", {"operation": "cursor", "items": [1, 2, 3], "limit": 1, "cursor": ""}, "invalid cursor")
        self.refused("page", {"operation": "cursor", "items": [1], "limit": 1, "offset": 0}, "cursor mode does not accept offset")
        self.refused("page", {"operation": "offset", "items": [1], "limit": 1, "cursor": cursor}, "offset mode does not accept cursor")
        self.refused("page", {"operation": "offset", "items": [1], "limit": 1, "offset": 2}, "page position beyond dataset")
        self.refused("page", {"operation": "offset", "items": [1], "limit": 1001}, "limit too large")
        self.refused("page", {"operation": "offset", "items": [1], "limit": True}, "limit must be an integer >= 1")

    # --- score -----------------------------------------------------------------------------------------------------------------------------------
    def test_tfidf_and_minheap(self):
        first, second = self.go("score", {"operation": "tfidf", "documents": ["a b", "a c"]})
        self.assertAlmostEqual(first["a"], 0.5)
        self.assertAlmostEqual(first["b"], 0.5 * (math.log(3 / 2) + 1))
        self.assertEqual(sorted(second), ["a", "c"])
        self.assertEqual(self.go("score", {"operation": "tfidf", "documents": [""]}), [{}])
        self.assertEqual(self.go("score", {"operation": "minheap", "values": [5, 1, 3, 1], "pops": 2}), {"popped": [1, 1], "remaining_sorted": [3, 5]})
        values = [3, 1, 2]
        self.go("score", {"operation": "minheap", "values": values, "pops": 3})
        self.assertEqual(values, [3, 1, 2], "the request is never changed")
        self.refused("score", {"operation": "minheap", "values": [1], "pops": 2}, "invalid pop count")
        self.refused("score", {"operation": "minheap", "values": [True]}, "heap values must be finite numbers")

    # --- reduce ----------------------------------------------------------------------------------------------------------------------------------
    def test_reducing_actions_into_a_history(self):
        actions = [{"type": "increment", "value": 5}, {"type": "decrement", "value": 3}, {"type": "set", "value": 100}, {"type": "reset"}]
        self.assertEqual(self.go("reduce", {"mode": "redux", "initial": 10, "actions": actions}), {"schema": "state-reducer/1", "mode": "redux", "state": 10, "history": [10, 15, 12, 100, 10]})
        for bad, message in (({"type": "multiply", "value": 2}, "action requires known type"), ({"type": "set", "value": True}, "action value must be integer"),
                             ({"type": "reset", "value": 1}, "action fields do not match type"), ({"type": "increment", "value": 10 ** 9 + 1}, "action value out of bounds")):
            self.refused("reduce", {"mode": "event_state", "initial": 0, "actions": [bad]}, message)
        self.refused("reduce", {"mode": "event_state", "initial": 10 ** 9, "actions": [{"type": "increment", "value": 1}]}, "result out of bounds")
        self.refused("reduce", {"mode": "getx", "initial": 0, "actions": []}, "unsupported mode")

    # --- convert ---------------------------------------------------------------------------------------------------------------------------------
    def test_conversions(self):
        convert = lambda **request: self.go("convert", request)["value"]
        self.assertEqual(convert(operation="normalize", value="  Ａｂｃ ", case="lower"), "abc")
        self.assertEqual(convert(operation="normalize", value="e" + chr(0x301), form="NFC"), "é")
        self.assertEqual((convert(operation="coerce", target="int", value="+12"), convert(operation="coerce", target="float", value="1e3")), (12, 1000.0))
        self.assertEqual([convert(operation="coerce", target="bool", value=v) for v in ("true", "0", True, 1, 0)], [True, False, True, True, False])
        self.refused("convert", {"operation": "coerce", "target": "bool", "value": 1.0}, "invalid boolean")
        self.refused("convert", {"operation": "coerce", "target": "int", "value": "1_0"}, "invalid integer")
        self.refused("convert", {"operation": "coerce", "target": "int", "value": "9" * 5000}, "invalid integer")
        self.refused("convert", {"operation": "coerce", "target": "float", "value": "1e999"}, "non-finite float")
        self.refused("convert", {"operation": "coerce", "target": "float", "value": "nan"}, "invalid float")
        self.assertEqual((convert(operation="date", value="20240229", source="compact", target="iso"), convert(operation="date", value="2024-02-29", target="compact")), ("2024-02-29", "20240229"))
        self.refused("convert", {"operation": "date", "value": "2023-02-29"}, "invalid iso date")
        self.refused("convert", {"operation": "date", "value": "2024-W01-1"}, "invalid iso date")
        self.assertEqual((convert(operation="unit", value=1, **{"from": "km", "to": "m"}), convert(operation="unit", value=500, **{"from": "g", "to": "kg"})), (1000.0, 0.5))
        self.refused("convert", {"operation": "unit", "value": 1, "from": "kg", "to": "m"}, "incompatible units")
        self.refused("convert", {"operation": "unit", "value": 1e-320, "from": "cm", "to": "km"}, "unit conversion underflow")
        self.refused("convert", {"operation": "unit", "value": 10 ** 400, "from": "m", "to": "m"}, "unit value must be finite number")
        self.assertEqual(convert(operation="encoding", mode="utf8_to_base64", value="héllo"), "aMOpbGxv")
        self.assertEqual(convert(operation="encoding", mode="base64_to_utf8", value="aMOpbGxv"), "héllo")
        self.refused("convert", {"operation": "encoding", "mode": "base64_to_utf8", "value": "aMOpbGx"}, "invalid base64 utf8")
        self.refused("convert", {"operation": "encoding", "mode": "utf8_to_base64", "value": chr(0xD800)}, "invalid utf8 input")
        self.assertEqual((convert(operation="mask", value="1234567890"), convert(operation="mask", value="abc"), convert(operation="mask", value="日本語テスト", keep_last=2)), ("******7890", "***", "****スト"))
        self.refused("convert", {"operation": "mask", "value": "x", "keep_last": 33}, "invalid keep_last")

    # --- validate --------------------------------------------------------------------------------------------------------------------------------
    def test_validation_rules(self):
        valid = lambda operation, value, **options: self.go("validate", {"operation": operation, "value": value, **({"options": options} if options else {})})["valid"]
        self.assertEqual([valid("required", v) for v in (None, "", "  ", "x", 0, False)], [False, False, False, True, True, True])
        self.assertEqual([valid("email", v) for v in ("a@b.co", "a@b", "a b@c.de", 5)], [True, False, False, False])
        self.assertEqual([valid("password", v) for v in ("abcdefgh1234", "abcdefghijkl", "short1a")], [True, False, False])
        self.assertEqual([valid("phone", v) for v in ("+8190123456", "0901234567", "123")], [True, True, False])
        self.assertEqual([valid("url", v) for v in ("https://a.b/c", "ftp://a.b", "https://u:p@a.b", "https://a.b:0", "https://a b")], [True, False, False, False, False])
        self.assertEqual([valid("date", v) for v in ("2024-02-29", "2023-02-29", "2024-2-9")], [True, False, False])
        self.assertEqual([valid("range", v, minimum=1, maximum=5) for v in (1, 5, 6, True, "3")], [True, True, False, False, False])
        self.assertEqual([valid("regex", v, pattern="hex_color") for v in ("#ABCDEF", "#abcdeg", "ABCDEF")], [True, False, False])
        self.refused("validate", {"operation": "regex", "value": "x", "options": {"pattern": "(a+)+$"}}, "unknown named regex")
        self.refused("validate", {"operation": "range", "value": 1, "options": {"minimum": 3, "maximum": 1}}, "invalid numeric range")
        form = self.go("validate", {"operation": "form", "fields": [{"name": "mail", "rule": "email", "value": "a@b.co"}, {"name": "tel", "rule": "phone", "value": "12"}]})
        self.assertEqual(form, {"valid": False, "fields": [{"name": "mail", "valid": True}, {"name": "tel", "valid": False}]})
        self.refused("validate", {"operation": "form", "fields": []}, "form requires fields")

    # --- workflow --------------------------------------------------------------------------------------------------------------------------------
    def test_workflow_operations(self):
        flow = lambda **request: self.go("workflow", request)["result"]
        self.assertEqual(flow(operation="swap", values=[1, 2, 3], a=0, b=2), [3, 2, 1])
        self.assertEqual((flow(operation="move_top", values=[1, 2, 3], index=2), flow(operation="move_bottom", values=[1, 2, 3], index=0)), ([3, 1, 2], [2, 3, 1]))
        self.assertEqual(flow(operation="insert_sorted", values=[1, 3, 5], value=4), [1, 3, 4, 5])
        self.refused("workflow", {"operation": "insert_sorted", "values": [3, 1], "value": 2}, "input not sorted")
        undo = flow(operation="undo_redo", values=[1], commands=[{"type": "append", "value": 2}, {"type": "append", "value": 3}, {"type": "undo"}, {"type": "undo"}, {"type": "redo"}])
        self.assertEqual((undo["values"], undo["cursor"], undo["history"]), ([1, 2], 1, [[1], [1, 2], [1, 2, 3]]))
        branch = flow(operation="command", values=[], commands=[{"type": "append", "value": 1}, {"type": "undo"}, {"type": "append", "value": 9}])
        self.assertEqual((branch["history"], branch["cursor"]), ([[], [9]], 1), "a new command discards the redo branch")
        self.refused("workflow", {"operation": "memento", "values": [], "commands": [{"type": "undo"}]}, "cannot undo")
        self.refused("workflow", {"operation": "memento", "values": [], "commands": [{"type": "redo"}]}, "cannot redo")
        self.assertEqual(flow(operation="batch", values=[1, 2, 3, 4, 5], batch_size=2), [[1, 2], [3, 4], [5]])
        self.assertEqual(flow(operation="scheduler", values=[1], schedule=[0, 500]), [{"at_ms": 0, "values": [1]}, {"at_ms": 500, "values": [1]}])
        commands = [{"type": "append", "value": 2}, {"type": "append", "value": 3}]
        self.assertEqual(flow(operation="transaction", values=[1], commands=commands), {"committed": True, "values": [1, 2, 3], "applied": [0, 1], "rolled_back": False})
        self.assertEqual(flow(operation="saga", values=[1], commands=commands, fail_at=1), {"committed": False, "values": [1], "applied": [0], "rolled_back": True})
        events = [{"type": "append", "value": "x"}]
        self.assertEqual(flow(operation="pubsub", values=[], events=events, subscribers=2), {"subscribers": [events, events], "state": ["x"]})
        self.assertEqual(flow(operation="cqrs", values=[1], events=events), {"write_state": [1, "x"], "read_projection": [1, "x"]})
        self.assertEqual(flow(operation="checkpoint", values=[1, 2, 3], checkpoint=1), {"processed": [1], "remaining": [2, 3], "checkpoint": 1})
        self.refused("workflow", {"operation": "swap", "values": [1], "a": 0, "b": 1}, "index out of range")
        self.refused("workflow", {"operation": "drop", "values": []}, "unknown operation")

    # --- transform and select --------------------------------------------------------------------------------------------------------------------
    def test_transformations_keep_json_types_apart(self):
        make = lambda **request: self.go("transform", request)["values"]
        self.assertEqual(make(operation="constraint", values=[1, 1.0, True, "1"], condition={"operator": "equals", "value": 1}), [True, False, False, False])
        self.assertEqual(make(operation="partition", values=[1, 5, 3], condition={"operator": "greater_than", "value": 2}), {"matched": [5, 3], "unmatched": [1]})
        schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "string"}}}, "additional_properties": False}
        self.assertEqual(make(operation="schema_validation", schema=schema, values=[{"id": 1}, {"id": 1.0}, {"id": 2, "tags": ["a", 1]}, {"id": 3, "x": 1}, {}]), [True, False, False, False, False])
        self.assertEqual(make(operation="pipeline", values=[" A ", "b"], steps=[{"operation": "strip"}, {"operation": "lower"}]), ["a", "b"])
        self.assertEqual(make(operation="pipeline", values=[1, 2], steps=[{"operation": "add", "value": 1}, {"operation": "multiply", "value": 2}]), [4, 6])
        self.assertEqual(make(operation="map_reduce", key="k", reducer="sum", values=[{"k": "a", "value": 1}, {"k": "b", "value": 2}, {"k": "a", "value": 3}]), [{"key": "a", "value": 4}, {"key": "b", "value": 2}])
        self.assertEqual(make(operation="flatten", values=[1, [2, [3, []]]]), [1, 2, 3])
        self.assertEqual(make(operation="zip", values=[1, 2, 3], other=["a", "b"]), [[1, "a"], [2, "b"]])
        self.refused("transform", {"operation": "zip", "values": [1], "other": [], "strict": True}, "strict zip lengths differ")
        self.refused("transform", {"operation": "flatten", "values": self._nested(101)}, "nested arrays exceed 100 levels")
        self.assertEqual(make(operation="flatten", values=self._nested(99)), [])
        self.refused("transform", {"operation": "constraint", "values": [], "condition": {"operator": "greater_than", "value": "a"}}, "ordered comparisons require numbers")

    @staticmethod
    def _nested(depth):
        value = []
        for _ in range(depth):
            value = [value]
        return [value]

    def test_selection_filters_distinct_values_and_reports_duplicates(self):
        pick = lambda **request: self.go("select", request)["values"]
        self.assertEqual(pick(values=[1, 2, 1], equals=1), [1, 1])
        rows = [{"name": "A", "profile": {"tags": ["blue"]}}, {"name": "B", "profile": {"tags": ["red"]}}, {"name": "C", "profile": {"tags": ["blue", "red"]}}]
        condition = lambda path, equals: {"path": path, "equals": equals}
        self.assertEqual([r["name"] for r in pick(values=rows, conditions=[condition(["profile", "tags", 0], "blue")])], ["A", "C"])
        self.assertEqual([r["name"] for r in pick(values=rows, match="any", conditions=[condition(["name"], "B"), condition(["profile", "tags", 1], "red")])], ["B", "C"])
        self.assertEqual([r["name"] for r in pick(values=rows, match="all", conditions=[condition(["name"], "C"), condition(["profile", "tags", 1], "red")])], ["C"])
        self.assertEqual(typed(pick(operation="distinct", values=[{"a": 1, "b": 2}, {"b": 2, "a": 1}, 1, 1.0, True, [1], [1], None, None])), typed([{"a": 1, "b": 2}, 1, 1.0, True, [1], None]))
        self.assertEqual(pick(operation="deduplicate_report", values=["a", "b", "a", "a"]), [{"input_count": 4, "unique_count": 2, "duplicate_count": 2, "has_duplicates": True}])
        self.refused("select", {"values": [], "conditions": []}, "conditions must be a non-empty list")
        self.refused("select", {"values": [], "conditions": [{"path": ["a", -1], "equals": 1}]}, "path must contain literal keys or non-negative integer indices")
        self.refused("select", {"values": [], "equals": 1, "conditions": [{"equals": 1}]}, "use equals or conditions, not both")
        self.refused("select", {"values": [], "operation": "sort"}, "operation must be filter, distinct or deduplicate_report")

    # --- order, text, window, collection, structure ----------------------------------------------------------------------------------------------
    def test_ordering_examples_and_custom_values(self):
        order = lambda mode, values=None: self.go("order", {"mode": mode, **({} if values is None else {"values": values})})["values"]
        self.assertEqual(order("basic"), [1, 2, 3, 5, 9])
        self.assertEqual(order("reverse", [1, 3, 2]), [3, 2, 1])
        self.assertEqual(order("sorted-set"), [1, 2, 3, 5])
        self.assertEqual(order("top-n", [7, 1, 9, 3, 8, 2]), [9, 8, 7])
        self.assertEqual([r["name"] for r in order("priority")], ["critical", "urgent", "normal", "later"])
        self.assertEqual([r["name"] for r in order("multi")], ["A3", "A1", "B2", "B1"])
        self.refused("order", {"mode": "basic", "values": [1, True]}, "basic ordering requires numbers")
        self.refused("order", {"mode": "shuffle"}, "unsupported ordering mode")

    def test_text_search_is_an_and_over_an_inverted_index(self):
        docs = web_ui.PATTERN_TEXT_DOCUMENTS
        self.assertEqual(web_ui.pattern_text_search(docs, "portable search"), ["doc-2"])
        self.assertEqual(web_ui.pattern_text_search(docs, "the PORTABLE"), ["doc-1", "doc-2"])
        self.assertEqual(web_ui.pattern_text_search(docs, "and the"), [])
        self.assertEqual(web_ui.pattern_inverted_index(docs)["search"], ["doc-2", "doc-3"])
        self.assertEqual(web_ui.pattern_tokens("Ａ b_c 12"), ["b", "c", "12"], "ASCII alphanumerics only")
        with self.assertRaises(TypeError):
            web_ui.pattern_tokens(5)
        with self.assertRaises(ValueError):
            web_ui.pattern_inverted_index([{"id": "", "text": "x"}])
        self.refused("text", {"mode": "fuzzy"}, "unsupported text-processing mode")

    def test_windows_clamp_and_keyset_follows_the_last_item(self):
        window = lambda mode, *commands: self.go("window", {"mode": mode, "commands": list(commands)})
        self.assertEqual((window("load-more")["values"], window("load-more", "next")["state"]["offset"]), (["item-01", "item-02", "item-03", "item-04"], 4))
        self.assertEqual(window("load-more", "next", "next", "next", "next")["state"]["offset"], 8, "the last window ends at the end")
        self.assertEqual(window("keyset", "next")["state"]["cursor"], "item-04")
        self.assertEqual(window("keyset", "next", "reset")["state"]["cursor"], "item-04", "reset moves back to the start but leaves the cursor as it was")
        self.assertEqual(window("page-size", "page-size-3")["state"]["limit"], 3)
        self.assertEqual(window("offset-limit", "offset-6")["values"], ["item-07", "item-08", "item-09", "item-10"])
        self.assertEqual(window("load-more", "refresh", "refresh")["state"]["revision"], 2)
        self.assertEqual((window("window", "next")["page"], window("window")["pages"]), (2, 3))
        self.refused("window", {"mode": "scroll"}, "unsupported mode")
        self.refused("window", {"mode": "window", "commands": ["jump"]}, "unsupported command")
        self.refused("window", {"mode": "window", "commands": "next"}, "commands must be strings")
        state = web_ui.pattern_window_initial("window")
        self.assertEqual(web_ui.pattern_window_step(state, "next")["offset"], 4)
        self.assertEqual(state["offset"], 0, "a step never changes the state it is given")
        self.refused("window", {"mode": "window", "commands": ["x"] * 1001}, "commands must be strings")

    def test_collection_commands(self):
        run = lambda mode, *commands: self.go("collection", {"mode": mode, "commands": [list(c) for c in commands]})
        self.assertEqual([v["selected"] for v in run("selectable", ("select", "b"), ("select", "c"), ("select", "b"))["values"]], [False, False, True, False])
        self.assertEqual(run("swipe-delete", ("select", "a"), ("delete", "a"))["state"], {"mode": "swipe-delete", "items": ["b", "c", "d"], "selected": []})
        self.assertEqual(run("reorderable", ("move-first", "d"))["state"]["items"], ["d", "a", "b", "c"])
        self.refused("collection", {"mode": "checklist", "commands": [["toggle", "z"]]}, "unknown item")
        self.refused("collection", {"mode": "checklist", "commands": [["sort"]]}, "unsupported collection command")
        self.refused("collection", {"mode": "dragging"}, "unsupported collection mode")

    def test_structure_examples(self):
        self.assertEqual([(s["header"], [i["id"] for i in s["items"]]) for s in self.go("structure", {"mode": "grouped"})["values"]], [("A", ["a1", "a2"]), ("B", ["b1", "b2"])])
        self.assertEqual([(n["id"], n["depth"]) for n in self.go("structure", {"mode": "tree"})["values"]], [("root", 0), ("left", 1), ("right", 1), ("leaf", 2)])
        self.refused("structure", {"mode": "ring"}, "unsupported mode")

    # --- the runner, the parser and the command line ---------------------------------------------------------------------------------------------
    def test_the_runner_names_unknown_families_and_wraps_crashes(self):
        with self.assertRaises(ValueError) as unknown:
            self.go("regex", {})
        self.assertIn("one of collection, concurrency, convert, event_loop, future, interaction, order", str(unknown.exception))
        with self.assertRaises(ValueError) as caught:
            self.go("transform", {"operation": ["unhashable"], "values": []})
        self.assertTrue(str(caught.exception).startswith("invalid transform request:"))
        self.refused("order", [])
        self.refused("window", None)

    def test_the_remaining_refusals(self):
        self.assertEqual(self.go("convert", {"operation": "normalize", "value": "straße", "case": "upper"}), {"value": "STRASSE"})
        self.refused("convert", {"operation": "normalize", "value": "x", "case": "title"}, "unsupported case mode")
        self.refused("convert", {"operation": "coerce", "target": "float", "value": 10 ** 400}, "invalid float")
        self.refused("convert", {"operation": "date", "value": "20231301", "source": "compact"}, "invalid compact date")
        self.refused("convert", {"operation": "unit", "value": 1e308, "from": "km", "to": "m"}, "unit conversion overflow")
        self.assertFalse(self.go("validate", {"operation": "url", "value": "https://[::1"})["valid"], "urlsplit itself refuses an unclosed IPv6 host")
        with self.assertRaises(TypeError):
            web_ui.pattern_without_stop_words(["a", 1])
        with self.assertRaises(TypeError):
            web_ui.pattern_window_step([], "next")
        self.assertEqual(web_ui.pattern_owner(199), "undecided")
        with mock.patch.dict(web_ui.PATTERN_TITLES, {"api": "OnlyOne"}), self.assertRaises(ValueError):
            web_ui.pattern_catalogue()

    def test_edges_of_every_limit_and_type_check(self):
        # inclusive bounds
        self.assertEqual(self.go("query", {"operation": "range", "items": [{"v": 3}, {"v": 4}], "key": "v", "minimum": 3, "maximum": 3}), [{"v": 3}])
        near = lambda lat, lon, row: self.go("query", {"operation": "geo", "items": [row], "latitude": lat, "longitude": lon, "radius_km": 0})
        self.assertEqual(near(90, 180, {"latitude": 90, "longitude": 180}), [{"latitude": 90, "longitude": 180}])
        self.assertEqual(near(-90, -180, {"latitude": -90, "longitude": -180}), [{"latitude": -90, "longitude": -180}])
        for lat, lon in ((90.5, 0), (-90.5, 0), (0, 180.5), (0, -180.5)):
            self.refused("query", {"operation": "geo", "items": [], "latitude": lat, "longitude": lon, "radius_km": 1}, "invalid geographic search")
            self.refused("query", {"operation": "geo", "items": [{"latitude": lat, "longitude": lon}], "latitude": 0, "longitude": 0, "radius_km": 1}, "invalid point coordinates")
        for key in ("", 5, None):
            self.refused("query", {"operation": "group_by", "items": [], "key": key}, "group key required")
        self.assertEqual(self.go("search", {"operation": "history", "events": ["a", "b"], "limit": 1}), ["b"])
        self.assertEqual(self.go("search", {"operation": "fuzzy", "query": "cat", "values": ["cat", "cap"], "max_distance": 0}), ["cat"])
        self.refused("search", {"operation": "fuzzy", "query": "cat", "values": [], "max_distance": True}, "invalid edit distance")
        self.refused("search", {"operation": "fuzzy", "query": "cat", "values": [], "max_distance": 11}, "invalid edit distance")
        self.assertEqual((web_ui._pat_distance("", "abc"), web_ui._pat_distance("kitten", "sitting"), web_ui._pat_distance("abc", "")), (3, 3, 3))
        # case folding, not lower-casing; a stem only touches plain ASCII words
        self.assertEqual(self.go("search", {"operation": "tokenize", "text": "STRASSE Straße"}), ["strasse", "strasse"])
        self.assertEqual(self.go("search", {"operation": "stem", "text": "cafés 123s"}), ["cafés", "123s"])
        self.assertEqual(self.go("convert", {"operation": "normalize", "value": "Straße", "case": "lower"}), {"value": "strasse"})
        first, = self.go("score", {"operation": "tfidf", "documents": ["Straße STRASSE"]})
        self.assertEqual(first, {"strasse": 2 / 2 * (math.log(2 / 2) + 1)})
        # a cursor is read strictly and does not depend on the order of an object's keys
        cursor = self.go("page", {"operation": "cursor", "items": [{"a": 1, "b": 2}, {"x": 0}], "limit": 1})["next_cursor"]
        self.assertEqual(self.go("page", {"operation": "cursor", "items": [{"b": 2, "a": 1}, {"x": 0}], "limit": 1, "cursor": cursor})["items"], [{"x": 0}])
        for junk in (cursor[:3] + "!" + cursor[3:], cursor[:3] + "\n" + cursor[3:], cursor + "===="):
            self.refused("page", {"operation": "cursor", "items": [{"a": 1, "b": 2}, {"x": 0}], "limit": 1, "cursor": junk}, "invalid cursor")
        # convert
        self.refused("convert", {"operation": "coerce", "target": "bool", "value": 0.0}, "invalid boolean")
        self.refused("convert", {"operation": "coerce", "target": "bool", "value": 2}, "invalid boolean")
        self.assertEqual(self.go("convert", {"operation": "unit", "value": 0, "from": "km", "to": "m"}), {"value": 0.0})
        self.refused("convert", {"operation": "encoding", "mode": "base64_to_utf8", "value": "aMOp!bGxv"}, "invalid base64 utf8")
        self.assertEqual([self.go("convert", {"operation": "mask", "value": "abcd", "keep_last": k})["value"] for k in (0, 1, 32)], ["****", "***d", "****"])
        self.refused("convert", {"operation": "mask", "value": "abcd", "keep_last": -1}, "invalid keep_last")
        # validate
        url = lambda n: "https://a.bc/" + "x" * (n - len("https://a.bc/"))
        self.assertEqual([self.go("validate", {"operation": "url", "value": url(n)})["valid"] for n in (2048, 2049)], [True, False])
        self.assertEqual([self.go("validate", {"operation": "regex", "value": "1" * n, "options": {"pattern": "digits"}})["valid"] for n in (4096, 4097)], [True, False])
        # workflow
        self.refused("workflow", {"operation": "swap", "values": [1, 2], "a": True, "b": 0}, "index out of range")
        self.refused("workflow", {"operation": "swap", "values": [1, 2], "a": 0.5, "b": 0}, "index out of range")
        append = {"type": "append", "value": 1}
        self.assertEqual(len(self.go("workflow", {"operation": "undo_redo", "values": [], "commands": [append] * 1000})["result"]["values"]), 1000)
        self.refused("workflow", {"operation": "undo_redo", "values": [], "commands": [append] * 1001}, "commands must be array <=1000")
        self.refused("workflow", {"operation": "transaction", "values": [], "commands": [append] * 1001}, "commands must be array <=1000")
        self.assertEqual(len(self.go("workflow", {"operation": "batch", "values": list(range(1000)), "batch_size": 1000})["result"]), 1)
        self.refused("workflow", {"operation": "batch", "values": [1], "batch_size": 1001}, "invalid batch size")
        self.refused("workflow", {"operation": "batch", "values": [1], "batch_size": True}, "invalid batch size")
        self.refused("workflow", {"operation": "batch", "values": [1], "batch_size": 0}, "invalid batch size")
        self.refused("workflow", {"operation": "scheduler", "values": [], "schedule": [True]}, "invalid schedule")
        self.refused("workflow", {"operation": "scheduler", "values": [], "schedule": [60001]}, "invalid schedule")
        self.assertEqual(len(self.go("workflow", {"operation": "scheduler", "values": [], "schedule": [60000] * 1000})["result"]), 1000)
        self.refused("workflow", {"operation": "scheduler", "values": [], "schedule": [0] * 1001}, "invalid schedule")
        self.refused("workflow", {"operation": "saga", "values": [], "commands": [{"type": "append", "value": 1}], "fail_at": 1}, "invalid fail_at")
        event = {"type": "append", "value": 1}
        self.assertEqual(len(self.go("workflow", {"operation": "queue", "values": [], "events": [event] * 1000})["result"]["state"]), 1000)
        self.refused("workflow", {"operation": "queue", "values": [], "events": [event] * 1001}, "events must be array <=1000")
        self.refused("workflow", {"operation": "queue", "values": [0], "events": [event] * 1000}, "result too large")
        self.refused("workflow", {"operation": "swap", "values": list(range(1001)), "a": 0, "b": 1}, "values must be array <=1000")
        self.assertEqual(self.go("workflow", {"operation": "checkpoint", "values": [1, 2], "checkpoint": 0})["result"], {"processed": [], "remaining": [1, 2], "checkpoint": 0})
        # transform
        none = {"type": "null"}
        self.assertEqual(self.go("transform", {"operation": "schema_validation", "schema": none, "values": [None, 0, False, ""]})["values"], [True, False, False, False])
        self.assertEqual(self.go("transform", {"operation": "constraint", "condition": {"operator": "type", "type": "null"}, "values": [None, 0]})["values"], [True, False])
        loose = {"type": "object", "properties": {"a": {"type": "integer"}}}
        self.assertEqual(self.go("transform", {"operation": "schema_validation", "schema": loose, "values": [{"a": 1, "b": 2}, {"a": "x"}]})["values"], [True, False])
        less = lambda operator, values: self.go("transform", {"operation": "constraint", "condition": {"operator": operator, "value": 2}, "values": values})["values"]
        self.assertEqual((less("less_than", [1, 2, 3]), less("greater_than", [1, 2, 3])), ([True, False, False], [False, False, True]))
        self.assertEqual(self.go("transform", {"operation": "constraint", "condition": {"operator": "equals", "value": {"a": 1, "b": 2}}, "values": [{"b": 2, "a": 1}]})["values"], [True])
        with self.assertRaises(ValueError):
            self.go("transform", {"operation": "constraint", "condition": {"operator": "equals", "value": 1}, "values": [float("nan")]})
        with self.assertRaises(ValueError):
            self.go("select", {"operation": "distinct", "values": [float("nan")]})
        # windows and collections
        window = lambda **state: web_ui.pattern_window_step({"mode": "window", "offset": 0, "limit": 4, "total": 12, **state}, "next")
        self.assertEqual(window(limit=1)["offset"], 1)
        for bad in ({"limit": 0}, {"offset": -1}, {"total": -1}, {"offset": True}, {"limit": 0.5}, {"total": "12"}):
            with self.assertRaises(ValueError, msg=bad):
                window(**bad)
        step = lambda command, **state: web_ui.pattern_window_step({"mode": "window", "offset": 0, "limit": 4, "total": 12, **state}, command)["offset"]
        self.assertEqual((step("page-size-3", total=3), step("page-size-3", total=2), step("offset-6", total=4), step("offset-6", total=3)), (0, 0, 0, 0))
        self.assertEqual(web_ui.pattern_window_render({"mode": "window", "offset": 0, "limit": 4, "total": 0}), {"schema": "collection-window/1", "mode": "window", "state": {"mode": "window", "offset": 0, "limit": 4, "total": 0}, "page": 0, "pages": 0, "values": []})
        self.assertEqual(web_ui.pattern_window_render({"mode": "window", "offset": 8, "limit": 4, "total": 10})["pages"], 3)
        for state in ([], None, {"mode": "dragging", "items": [], "selected": []}, {"mode": "checklist", "items": "ab", "selected": []}, {"mode": "checklist", "items": ["a"], "selected": "a"},
                      {"mode": "checklist", "items": ["a", "a"], "selected": []}, {"mode": "checklist", "items": ["a", 1], "selected": []}, {"mode": "checklist", "items": ["a"], "selected": ["z"]}):
            with self.assertRaises(ValueError, msg=state):
                web_ui.pattern_collection_step(state, "toggle", "a")
        self.assertEqual(len(self.go("window", {"mode": "window", "commands": ["next"] * 1000})["values"]), 4)
        self.refused("window", {"mode": "window", "commands": ["next"] * 1001}, "commands must be strings")
        self.refused("window", {"mode": "window", "commands": ["next", 5]}, "commands must be strings")
        self.assertEqual(self.go("collection", {"mode": "checklist", "commands": [["toggle"]] * 1000})["state"]["selected"], [])
        self.refused("collection", {"mode": "checklist", "commands": [["toggle"]] * 1001}, "commands must be [command] or [command, item]")
        for commands in ("toggle", [["toggle", "a", "b"]], [[]], [["toggle", 5]], [5]):
            self.refused("collection", {"mode": "checklist", "commands": commands}, "commands must be [command] or [command, item]")
        # more edges: result limits, the e-mail length, and the shape of a window's page counts
        self.assertEqual(len(self.go("search", {"operation": "autocomplete", "query": "a", "values": ["a"] * 1001, "limit": 1000})), 1000)
        self.refused("search", {"operation": "autocomplete", "query": "a", "values": [], "limit": 1001}, "invalid result limit")
        mail = lambda n: "a" * (n - len("@b.co")) + "@b.co"
        self.assertEqual([self.go("validate", {"operation": "email", "value": mail(n)})["valid"] for n in (254, 255)], [True, False])
        self.assertEqual(step("next", total=4), 0)
        self.assertEqual(step("next", total=0), 0)
        render = lambda **state: web_ui.pattern_window_render({"mode": "window", "offset": 0, "limit": 4, "total": 12, **state})
        self.assertEqual([(render(offset=o, total=t)["page"], render(offset=o, total=t)["pages"]) for o, t in ((0, 8), (4, 8), (8, 12), (4, 12), (0, 1), (0, 4), (0, 5))],
                         [(1, 2), (2, 2), (3, 3), (2, 3), (1, 1), (1, 1), (1, 2)])
        with self.assertRaises(ValueError):
            self.go("transform", {"operation": "constraint", "condition": {"operator": "equals", "value": float("nan")}, "values": [1]})
        with self.assertRaises(ValueError):
            self.go("page", {"operation": "cursor", "items": [float("nan")], "limit": 1})
        self.assertEqual(web_ui.PATTERN_ORDER_EXAMPLES["top-n"], [7, 1, 9, 3, 8, 2])
        self.assertEqual(web_ui.PATTERN_ORDER_EXAMPLES["basic"], [9, 2, 5, 1, 3])
        self.assertEqual(web_ui.PATTERN_ORDER_EXAMPLES["sorted-set"], [5, 2, 5, 1, 3, 2])
        self.assertEqual((web_ui._pat_distance("ab", "a"), web_ui._pat_distance("a", "ab"), web_ui._pat_distance("flaw", "lawn"), web_ui._pat_distance("", "")), (1, 1, 2, 0))
        self.assertEqual(len(self.go("reduce", {"mode": "redux", "initial": 0, "actions": [{"type": "reset"}] * 1000})["history"]), 1001)
        self.refused("reduce", {"mode": "redux", "initial": 0, "actions": [{"type": "reset"}] * 1001}, "actions must be array of at most 1000")
        self.assertEqual([self.go("convert", {"operation": "mask", "value": "abcd", "keep_last": k})["value"] for k in (3, 4, 5)], ["*bcd", "****", "****"])
        self.assertEqual(self.go("convert", {"operation": "mask", "value": "abcd"}), {"value": "****"})
        with self.assertRaises(ValueError) as caught:
            self.go("transform", {"operation": "schema_validation", "schema": {"type": ["string"]}, "values": []})
        self.assertEqual(str(caught.exception), "invalid JSON type")
        self.refused("transform", {"operation": "schema_validation", "schema": {"type": "string", "items": {"type": "string"}}, "values": ["ab"]}, "items requires array type")
        self.assertEqual(self.go("transform", {"operation": "constraint", "condition": {"operator": "equals", "value": {"b": 2, "a": 1}}, "values": [{"a": 1, "b": 2}]})["values"], [True])
        # select
        self.refused("select", {"values": [], "conditions": [{"path": [True], "equals": 1}]}, "path must contain literal keys or non-negative integer indices")
        self.assertEqual(self.go("select", {"values": [[7]], "conditions": [{"path": [0], "equals": 7}]})["values"], [[7]])
        self.assertEqual(self.go("select", {"values": [[7], [8]], "conditions": [{"path": [1], "equals": 8}]})["values"], [])

    def test_the_javascript_references_answer_as_their_node_tests_expect(self):
        # javascript/tests/future_patterns.test.mjs
        future = lambda mode, **extra: self.go("future", {"mode": mode, **extra})["value"]
        self.assertEqual(future("basic", task={"value": "ok"}), "ok")
        self.assertEqual(future("chain", task={"value": 2}, steps=[{"op": "multiply", "by": 3}, {"op": "add", "by": 1}]), 7)
        self.assertEqual(future("chain", task={"value": "ab"}, steps=[{"op": "uppercase"}]), "AB")
        self.assertEqual(future("error", task={"value": None, "reject": "broken"}, fallback="safe"), {"caught": "broken", "fallback": "safe"})
        self.assertEqual(future("error", task={"value": 1, "reject": "x"}, fallback=None)["fallback"], None)
        self.assertEqual(future("error", task={"value": 5}, fallback="unused"), 5)
        self.assertEqual(future("wait", tasks=[{"value": "slow", "delay_ms": 25}, {"value": "fast"}]), ["slow", "fast"])
        self.assertEqual(future("any", tasks=[{"value": "slow", "delay_ms": 30}, {"value": "fast"}]), "fast")
        self.refused("future", {"mode": "any", "tasks": [{"value": "late", "delay_ms": 30}, {"value": None, "reject": "first"}]}, "first")
        self.refused("future", {"mode": "wait", "tasks": [{"value": 1, "reject": "b", "delay_ms": 9}, {"value": 2, "reject": "a", "delay_ms": 3}, {"value": 3}]}, "a")
        self.assertEqual(future("any", tasks=[{"value": "one", "delay_ms": 1}, {"value": "zero"}]), "one", "a timer of 0 ms waits 1 ms, so the earlier created wins a tie")
        self.refused("future", {"mode": "timeout", "task": {"value": 1, "delay_ms": 30}, "timeout_ms": 5}, "timeout")
        self.assertEqual(future("timeout", task={"value": 1}, timeout_ms=100), 1)
        self.assertEqual(future("timeout", task={"value": 1, "delay_ms": 5}, timeout_ms=5), 1, "a tie goes to the task")
        self.refused("future", {"mode": "timeout", "task": {"value": 1, "reject": "late"}, "timeout_ms": 5}, "late")
        for request, message in (({"mode": "basic", "task": {"value": 1}, "other": 2}, "unknown field other"), ({"mode": "chain", "task": {"value": 1}, "steps": [{"op": "uppercase"}]}, "string input required"),
                                 ({"mode": "chain", "task": {"value": 1}, "steps": [{"op": "add"}]}, "numeric by required"), ({"mode": "wait", "tasks": []}, "tasks must contain 1..32 tasks"),
                                 ({"mode": "any", "tasks": [{"value": 1, "delay_ms": -1}]}, "delay_ms must be an integer 0..1000"), ({"mode": "timeout", "task": {"value": 1}, "timeout_ms": 0}, "timeout_ms must be 1..1000"),
                                 ({"mode": "error", "task": {"value": 1}}, "fallback required"), ({"mode": "basic", "task": {"delay_ms": 1}}, "missing field value"),
                                 ({"mode": "basic", "task": {"value": 1, "reject": ""}}, "reject must be a nonempty string"), ({"mode": "basic", "task": {"value": 1}, "9": 1, "a": 1}, "unknown field 9"),
                                 ({"mode": "nope"}, "unsupported mode"), ([], "request must be an object")):
            self.refused("future", request, message)
        self.assertEqual(future("basic", task={"value": 1, "delay_ms": 4.0}), 1, "JavaScript reads 4.0 as the integer 4")
        # javascript/tests/stream_patterns.test.mjs
        e = lambda *pairs: [{"at_ms": at, "value": value} for at, value in pairs]
        stream = lambda mode, **extra: self.go("stream", {"mode": mode, **extra})
        self.assertEqual(stream("basic", events=e((0, 1), (1, 2)))["events"], e((0, 1), (1, 2)))
        self.assertEqual(stream("controller", commands=[{"op": "add", "value": 1}, {"op": "close"}])["events"], e((0, 1)))
        self.assertEqual(stream("broadcast", events=e((0, 1)), subscribers=2)["subscribers"], [e((0, 1)), e((0, 1))])
        self.assertEqual(stream("transform", events=e((0, [1, 2])), steps=[{"op": "expand"}, {"op": "map_add", "value": 1}, {"op": "where_equals", "value": 3}])["events"], e((0, 3)))
        self.assertEqual(stream("merge", streams=[e((0, "a"), (2, "b")), e((1, "x"), (2, "y"))])["events"],
                         [{"at_ms": 0, "value": "a", "source": 0}, {"at_ms": 1, "value": "x", "source": 1}, {"at_ms": 2, "value": "b", "source": 0}, {"at_ms": 2, "value": "y", "source": 1}])
        self.assertEqual(stream("debounce", events=e((0, "a"), (5, "b"), (11, "c"), (20, "d")), duration_ms=6)["events"], e((11, "c"), (20, "d")))
        self.assertEqual(stream("throttle", events=e((0, 1), (4, 2), (5, 3)), duration_ms=5)["events"], e((0, 1), (5, 3)))
        self.assertEqual(stream("buffer", events=e((0, 1), (1, 2), (2, 3)), size=2)["events"], e((1, [1, 2]), (2, [3])))
        self.assertEqual(stream("window", events=e((0, 1), (1, 2), (2, 3)), size=2)["events"], e((1, [1, 2]), (2, [2, 3])))
        self.assertEqual(stream("window", events=e((0, 1), (1, 2), (2, 3), (3, 4)), size=3, step=1)["events"], e((2, [1, 2, 3]), (3, [2, 3, 4])))
        self.assertEqual(stream("transform", events=e((0, {"a": 1, "b": 2})), steps=[{"op": "where_equals", "value": {"b": 2, "a": 1}}])["events"], [], "the JSON text is compared, so key order matters")
        self.assertEqual(stream("transform", events=e((0, 1)), steps=[{"op": "where_equals"}])["events"], [])
        for request, message in (({"mode": "basic", "events": e((2, 1), (1, 2))}, "sorted event time"), ({"mode": "controller", "commands": [{"op": "close"}, {"op": "add", "value": 1}]}, "invalid add"),
                                 ({"mode": "controller", "commands": [{"op": "add", "value": 1}]}, "close required"), ({"mode": "controller", "commands": [{"op": "close"}, {"op": "close"}]}, "closed twice"),
                                 ({"mode": "buffer", "events": [], "size": 0}, "size"), ({"mode": "debounce", "events": [], "duration_ms": 0}, "duration"),
                                 ({"mode": "basic", "events": [{"at_ms": 1}]}, "event shape"), ({"mode": "merge", "streams": []}, "streams"), ({"mode": "transform", "events": [], "steps": []}, "steps"),
                                 ({"mode": "transform", "events": e((0, 1)), "steps": [{"op": "expand"}]}, "expand array"), ({"mode": "transform", "events": e((0, 1)), "steps": [{"op": "map_add", "value": "x"}]}, "map_add numbers"),
                                 ({"mode": "broadcast", "events": [], "subscribers": 17}, "subscribers"), ({"mode": "x"}, "mode")):
            self.refused("stream", request, message)
        self.assertEqual(stream("basic", events=e((-1, 1)))["events"], e((-1, 1)), "the first event may be at -1: the original starts its order check there")
        # javascript/tests/concurrency_patterns.test.mjs
        task = lambda value, delay_ms=0: {"value": value, "delay_ms": delay_ms}
        conc = lambda mode, **extra: self.go("concurrency", {"mode": mode, **extra})["result"]
        self.assertEqual(conc("work_queue", tasks=[task("a", 9), task("b"), task("c")]), {"values": ["a", "b", "c"], "max_active": 1})
        self.assertEqual(conc("semaphore", concurrency=2, tasks=[task(1, 12), task(2, 12), task(3)]), {"values": [1, 2, 3], "max_active": 2})
        self.assertEqual(conc("semaphore", concurrency=5, tasks=[task(1)]), {"values": [1], "max_active": 1})
        self.assertEqual(conc("semaphore", concurrency=5, tasks=[]), {"values": [], "max_active": 0})
        self.assertEqual(conc("mutex", increments=[3, -1, 4]), {"value": 6, "history": [3, 2, 6]})
        self.assertEqual(conc("cancelable", task=task("a"), cancel=True), {"status": "cancelled"})
        self.assertEqual(conc("cancelable", task=task("a"), cancel=False), {"status": "completed", "value": "a"})
        self.assertEqual(conc("parallel_map", concurrency=2, tasks=[task("slow", 12), task("fast"), task("last")]), {"values": ["slow", "fast", "last"], "max_active": 2})
        self.assertEqual(conc("progress", tasks=[task(1), task(2)])["progress"], [{"completed": 1, "total": 2}, {"completed": 2, "total": 2}])
        for request, message in (({"mode": "semaphore", "tasks": [task(1)], "concurrency": 0}, "concurrency 1..32"), ({"mode": "work_queue", "tasks": [task(1, -1)]}, "delay_ms must be 0..50"),
                                 ({"mode": "cancelable", "task": task(1), "cancel": "true"}, "cancel flag required"), ({"mode": "mutex", "increments": [1.5]}, "increments"),
                                 ({"mode": "parallel_map", "tasks": [], "concurrency": 33}, "concurrency 1..32"), ({"mode": "mutex", "increments": [2 ** 53 - 1, 1]}, "overflow"),
                                 ({"mode": "mutex", "increments": [], "tasks": []}, "unknown request keys"), ({"mode": "work_queue", "tasks": [{"delay_ms": 1}]}, "task keys"),
                                 ({"mode": "work_queue", "tasks": [5]}, "task object required"), ({"mode": "work_queue", "tasks": [task(1)] * 33}, "tasks must be an array (max 32)"),
                                 ({"mode": "nope"}, "unsupported mode"), ([], "request object")):
            self.refused("concurrency", request, message)
        # javascript/tests/event_loop_patterns.test.mjs
        loop = lambda mode, **extra: self.go("event_loop", {"mode": mode, **extra})["result"]
        self.assertEqual(loop("reactive", values=[1, 2, 3], steps=[{"op": "map_add", "value": 1}, {"op": "where_equals", "value": 3}]), [3])
        self.assertEqual([step["phase"] for step in loop("event_loop", values=["x"])], ["sync", "microtask", "timer"])
        self.assertEqual(loop("microtask", values=[]), ["sync", "microtask", "promise", "timer"])
        self.assertEqual(loop("suspend_resume", values=[1, 2, 3], pause_after=1), {"values": [1, 2, 3], "trace": ["paused", "resumed"]})
        self.assertEqual(loop("suspend_resume", values=[1, 2, 3], pause_after=3)["trace"], ["paused", "resumed"])
        self.assertEqual(loop("async_generator", values=[1, "b", None]), [1, "b", None])
        for request, message in (({"mode": "reactive", "values": [1], "steps": []}, "steps"), ({"mode": "reactive", "values": [1], "steps": [{"op": "map_add", "value": "bad"}]}, "numbers required"),
                                 ({"mode": "suspend_resume", "values": [1], "pause_after": 2}, "pause_after"), ({"mode": "microtask", "values": [], "extra": 1}, "unknown field"),
                                 ({"mode": "reactive", "values": [1]}, "missing field"), ({"mode": "x", "values": 5}, "values must be array <=1000"), ({"mode": "x", "values": []}, "unsupported mode"),
                                 ({"mode": "reactive", "values": [1], "steps": [{"op": "x", "value": 1}]}, "unsupported reactive step"), ([], "object required")):
            self.refused("event_loop", request, message)
        # javascript/tests/interaction_patterns.test.mjs: virtualWindow
        window = lambda **params: self.go("interaction", {"operation": "virtual_window", **params})["result"]
        self.assertEqual(window(count=100, itemHeight=20, scrollTop=200, viewportHeight=100, overscan=1), {"start": 9, "end": 16, "topPadding": 180, "bottomPadding": 1680})
        self.assertEqual(window(count=0, itemHeight=20, scrollTop=0, viewportHeight=100), {"start": 0, "end": 0, "topPadding": 0, "bottomPadding": 0})
        self.assertEqual(window(count=10, itemHeight=20, scrollTop=0, viewportHeight=40), {"start": 0, "end": 4, "topPadding": 0, "bottomPadding": 120})
        self.refused("interaction", {"operation": "virtual_window", "count": 10, "itemHeight": 0, "scrollTop": 0, "viewportHeight": 100}, "invalid viewport configuration")
        self.refused("interaction", {"operation": "virtual_window", "count": 10.5, "itemHeight": 1, "scrollTop": 0, "viewportHeight": 100}, "invalid viewport configuration")
        self.refused("interaction", {"operation": "virtual_window", "count": -1, "itemHeight": 1, "scrollTop": 0, "viewportHeight": 100}, "invalid viewport number")
        self.refused("interaction", {"operation": "virtual_window", "count": 1, "itemHeight": 1, "scrollTop": 0}, "invalid viewport number")
        self.refused("interaction", {"operation": "virtual_window", "count": 1, "itemHeight": 1, "scrollTop": 0, "viewportHeight": 1, "overscan": None}, "invalid viewport number")
        self.refused("interaction", {"operation": "nope"}, "unsupported operation")

    def test_the_debounce_follows_the_node_test_with_fake_timers(self):
        callbacks, seen, ids = {}, [], [0]

        def set_timeout(fn, ms):
            ids[0] += 1
            callbacks[ids[0]] = fn
            return ids[0]
        trigger = web_ui.PatternDebouncer(seen.append, 20, set_timeout, lambda key: callbacks.pop(key, None))
        trigger("first")
        trigger("last")
        self.assertEqual(len(callbacks), 1)
        key, callback = next(iter(callbacks.items()))
        del callbacks[key]
        callback()
        self.assertEqual(seen, ["last"])
        trigger("cancelled")
        trigger.cancel()
        self.assertEqual(len(callbacks), 0)
        for args in ((None, 1), (seen.append, -1), (seen.append, float("nan")), (seen.append, "5"), (seen.append, None)):
            with self.assertRaises(TypeError, msg=args):
                web_ui.PatternDebouncer(args[0], args[1], set_timeout, lambda key: None)
        run = lambda calls, delay=20: self.go("interaction", {"operation": "debounce", "delay_ms": delay, "calls": calls})["result"]
        self.assertEqual(run([{"at_ms": 0, "value": "a"}, {"at_ms": 5, "value": "b"}, {"at_ms": 60, "value": "c"}]), [{"at_ms": 25, "value": "b"}, {"at_ms": 80, "value": "c"}])
        self.assertEqual(run([{"at_ms": 0, "value": "a"}, {"at_ms": 20, "value": "b"}]), [{"at_ms": 40, "value": "b"}], "a call at the moment the timer is due still replaces it")
        self.assertEqual(run([{"at_ms": 0, "value": "a"}, {"at_ms": 21, "value": "b"}]), [{"at_ms": 20, "value": "a"}, {"at_ms": 41, "value": "b"}])
        self.assertEqual(run([{"at_ms": 0, "value": "a"}, {"at_ms": 5, "cancel": True}]), [])
        self.assertEqual(run([{"at_ms": 0, "value": "a"}], delay=0), [{"at_ms": 0, "value": "a"}])
        for calls, message in (([{"at_ms": 5, "value": 1}, {"at_ms": 1, "value": 2}], "sorted call time"), ([{"at_ms": 1}], "call shape"), ([{"at_ms": 1, "cancel": False}], "call shape"),
                               ([{"at_ms": 1, "value": 1, "cancel": True}], "call shape"), (5, "calls must be array <=1000")):
            self.refused("interaction", {"operation": "debounce", "delay_ms": 5, "calls": calls}, message)
        self.refused("interaction", {"operation": "debounce", "delay_ms": 60001, "calls": []}, "delay_ms must be 0..60000")

    def test_strict_parsing(self):
        parse = web_ui.pattern_parse
        self.assertEqual(typed(parse('{"a":[1,1.0,true,null]}')), '{"a": [1, 1.0, true, null]}')
        for text in ("NaN", "[Infinity]", '{"a":-Infinity}', "1e999", "[1e400]", "[" * 100000):
            with self.subTest(text=text[:12]), self.assertRaises(ValueError):
                parse(text)

    def test_the_command_line(self):
        run = lambda *args, **kw: subprocess.run([sys.executable, "-S", str(ROOT / "web_ui.py"), *args], capture_output=True, timeout=60, **kw)
        done = run("--pattern", "reduce", input=json.dumps({"mode": "redux", "initial": 1, "actions": [{"type": "increment", "value": 2}]}).encode())
        self.assertEqual((done.returncode, json.loads(done.stdout)), (0, {"history": [1, 3], "mode": "redux", "schema": "state-reducer/1", "state": 3}))
        for stdin in (b'{"mode":"redux","initial":NaN,"actions":[]}', b"[1", b'{"mode":"x"}', "{\"a\":\"".encode() + b"\xff\"}", b" " * (web_ui.PATTERN_MAX_INPUT + 1)):
            done = run("--pattern", "reduce", input=stdin)
            self.assertEqual((done.returncode, done.stdout), (2, b""), stdin[:20])
            self.assertTrue(done.stderr.startswith(b"invalid pattern request: "))
        self.assertEqual(run("--pattern", "list").stdout.decode().split(), sorted(web_ui.PATTERN_RUNNERS))
        done = run("--pattern", "nonsense", input=b"{}")
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"unknown pattern family", done.stderr)
        rows = json.loads(run("--pattern", "catalogue").stdout)
        self.assertEqual((len(rows), rows[0]["id"], rows[-1]["id"]), (792, "A001", "D198"))

    # --- the catalogue ---------------------------------------------------------------------------------------------------------------------------
    def test_the_catalogue_lists_all_792_patterns(self):
        rows = web_ui.pattern_catalogue()
        self.assertEqual(len(rows), 792)
        self.assertEqual(len({r["id"] for r in rows}), 792)
        for key, letter, _ in web_ui.PATTERN_CATEGORIES:
            own = [r for r in rows if r["category"] == key]
            self.assertEqual([r["number"] for r in own], list(range(1, 199)))
            self.assertTrue(all(r["id"] == f"{letter}{r['number']:03d}" for r in own))
        by_id = {r["id"]: r for r in rows}
        self.assertEqual((by_id["A001"]["title"], by_id["A001"]["theme"]), ("BasicPush", "基本ナビゲーション (Push/Pop/Replace)"))
        self.assertEqual(by_id["D003"]["title"], "FilterNested")
        self.assertEqual(by_id["D198"]["title"], "FullPipeline")
        self.assertTrue(all(r["title"].isascii() and r["title"].isalnum() and r["theme"] for r in rows))
        self.assertEqual({r["id"] for r in rows if "family" in r}, {r["id"] for r in rows if r["category"] == "data"})

    def test_themes_follow_the_ranges_of_patterns_md(self):
        for key, ranges in web_ui.PATTERN_THEMES.items():
            self.assertEqual(ranges[0][0], 1, key)
            self.assertEqual(ranges[-1][1], 198, key)
            self.assertTrue(all(a[1] + 1 == b[0] for a, b in zip(ranges, ranges[1:])), key)
        theme = web_ui.pattern_theme
        self.assertEqual((theme("data", 30), theme("data", 31), theme("data", 185), theme("data", 186)), ("フィルタリング・ソート・検索", "ページング・無限スクロール・仮想化", "並び替え・追加・入れ替え機能", "バッチ処理・トランザクション・イベント駆動"))
        self.assertEqual(theme("ui", 175), "プラットフォーム固有 (iOS/Android/Web/macOS)")
        with self.assertRaises(ValueError):
            theme("data", 199)

    def test_every_reference_function_belongs_to_the_patterns_that_the_original_assigned(self):
        families: dict[str, list[int]] = {}
        for number in range(1, 199):
            family = web_ui.pattern_family(number)
            if family:
                families.setdefault(family, []).append(number)
        self.assertEqual(set(families), set(web_ui.PATTERN_RUNNERS))
        self.assertEqual(families["select"], [1, 2, 3, 30, 86, 113])
        self.assertEqual(families["query"], [11, 12, 14, 15, 16, 17, 18])
        self.assertEqual(families["window"], [34, 36, 37, 38, 39, 40, 41, 42, 43, 44])
        self.assertEqual(families["workflow"], list(range(176, 183)) + list(range(185, 199)))
        self.assertEqual(families["validate"], list(range(91, 100)))
        self.assertEqual(families["reduce"], [164, 165])
        self.assertEqual((families["future"], families["concurrency"], families["event_loop"], families["interaction"]), (list(range(121, 127)), list(range(138, 144)), list(range(146, 151)), [4, 35]))
        self.assertEqual(families["stream"], list(range(127, 136)) + [144, 145])
        owner = web_ui.pattern_owner
        self.assertEqual([owner(n) for n in (4, 35, 121, 135, 138, 150)], ["javascript"] * 6)
        self.assertEqual([owner(n) for n in (136, 137, 151, 163, 166, 170, 171, 184)], ["flutter_native"] * 8)
        self.assertEqual([owner(n) for n in (50, 60, 61, 90, 91, 112)], ["python_assets / flutter_layout", "python_assets / flutter_layout", "python_cache / runtime_specific", "python_cache / runtime_specific", "python", "python_validation / flutter_form"])
        self.assertEqual((owner(8), owner(113), owner(35)), ("python", "python", "javascript"), "the first row that contains a number decides (35 is JavaScript, not a window)")
        self.assertEqual(web_ui.pattern_family(35), "interaction")

    def test_finding_patterns(self):
        rows = web_ui.pattern_catalogue()
        ids = lambda **kw: [r["id"] for r in web_ui.pattern_find(rows, **kw)]
        self.assertEqual(ids(query="filternested"), ["D003"])
        self.assertEqual(ids(query="ＦＩＬＴＥＲ ｎｅｓｔｅｄ"), ["D003"], "NFKC and case folded")
        self.assertEqual(ids(query="d003"), ["D003"])
        self.assertEqual(ids(query="", category="api")[:2], ["B001", "B002"])
        self.assertEqual(len(ids(category="data", family="select")), 6)
        self.assertEqual(len(ids()), 792)
        self.assertEqual(ids(query="no such pattern"), [])
        self.assertIn("D030", ids(query="フィルタリング"))
        self.assertEqual(len(ids(query="フィルタリング")), 30)

    # --- the patterns page -----------------------------------------------------------------------------------------------------------------------
    def test_every_family_has_an_example_and_the_page_runs_seventeen_of_them(self):
        examples = web_ui.pattern_examples()
        self.assertEqual(sorted(examples), sorted(web_ui.PATTERN_RUNNERS))
        self.assertEqual(set(web_ui.PATTERN_RUNNERS) - set(web_ui.PATTERN_TWINS), {"search", "convert", "validate"})
        for family, example in examples.items():
            with self.subTest(family):
                self.assertEqual(typed(example["result"]), typed(self.go(family, web_ui.PATTERN_EXAMPLES[family])))
                json.dumps(example, allow_nan=False)
        for family in web_ui.PATTERN_TWINS:
            self.assertNotIn("1.0", json.dumps(web_ui.PATTERN_EXAMPLES[family]), "a page reads 1.0 as 1")

    def test_the_page_is_one_self_contained_document(self):
        page = web_ui.patterns_document()
        self.assertEqual(page.count('<script type="module">'), 1)
        self.assertEqual(page.count('id="patterns"'), 1)
        self.assertNotRegex(page, r"https?://")
        for hook in ("data-patterns-query", "data-patterns-category", "data-patterns-family", "data-patterns-count", "data-patterns-more", "data-patterns-list", "data-patterns-run-family",
                     "data-patterns-request", "data-patterns-run", "data-patterns-example", "data-patterns-status", "data-patterns-result", 'id="patterns-run-title"'):
            self.assertEqual(page.count(hook) if hook.startswith("id=") else len(re.findall(r"(?<= )%s(?=[ >])" % re.escape(hook), page)), 1, hook)
        self.assertEqual(len(re.findall(r'<option value="(?:%s)"' % "|".join(web_ui.PATTERN_RUNNERS), page)), 2 * len(web_ui.PATTERN_RUNNERS))
        self.assertIn('<option value="query" selected>', page)
        self.assertEqual(len(re.findall(r'<option value="(?:navigation|api|ui|data)">', page)), 4)
        self.assertIn("globalThis.webUiPatterns=api", page)
        self.assertIn(".ui-patterns", web_ui.bundled_css())
        self.assertTrue(all(int(px) % 8 == 0 for px in re.findall(r"(\d+)px", web_ui._CSS["patterns.css"])), "pixel sizes are multiples of 8")
        self.assertIn("examples/patterns.html", web_ui.example_pages())
        self.assertIn('href="./patterns.html"', web_ui.example_pages()["examples/index.html"])

    def test_the_js_constants_are_the_python_values(self):
        source = web_ui._JS["patterns.js"]
        want = {"PATTERN_CATEGORIES": web_ui.PATTERN_CATEGORIES, "PATTERN_THEMES": web_ui.PATTERN_THEMES, "PATTERN_TITLES": web_ui.PATTERN_TITLES,
                "PATTERN_PRODUCERS": [[list(n), r, f] for n, r, f in web_ui.PATTERN_PRODUCERS], "PATTERN_NATIVE": sorted(web_ui.PATTERN_NATIVE),
                "PATTERN_GESTURES": sorted(web_ui.PATTERN_GESTURES), "PATTERN_FAMILIES": sorted(web_ui.PATTERN_RUNNERS), "PATTERN_TWINS": list(web_ui.PATTERN_TWINS),
                "PATTERN_EXAMPLES": web_ui.pattern_examples()}
        for name, value in want.items():
            found = re.search(r"^export const %s=(.*);$" % name, source, re.M)
            self.assertIsNotNone(found, name)
            self.assertEqual(typed(json.loads(found.group(1))), typed(json.loads(json.dumps(value))), name)
        self.assertNotIn("</script", source.lower())
        self.assertNotIn('"""', source)

    def test_the_platform_adapters_check_the_page(self):
        for name, fragment in (("web-ui-patterns", None), ("web-ui-pattern-run", "patterns-run-title")):
            adapter = web_ui.btk_adapter(name)
            self.assertEqual(adapter["url"], "http://127.0.0.1:8000/examples/patterns.html" + ("" if fragment is None else "#" + fragment))
            self.assertNotEqual(adapter["click"]["before"], adapter["click"]["after"])
            self.assertTrue(all(selector.startswith("#patterns") for selector in adapter["elements"]))
        self.assertEqual((web_ui.BTK_ADAPTERS["web-ui-patterns"]["click"]["before"], web_ui.BTK_ADAPTERS["web-ui-patterns"]["click"]["after"]), ("48", "96"))

    # --- invariants on random input --------------------------------------------------------------------------------------------------------------
    def test_random_invariants(self):
        rng = random.Random(792)
        for _ in range(300):
            items = [{"k": rng.randint(0, 4), "i": i} for i in range(rng.randint(0, 12))]
            descending = rng.random() < 0.5
            result = self.go("query", {"operation": "stable_sort", "items": items, "key": "k", "descending": descending})
            self.assertEqual(sorted(r["i"] for r in result), list(range(len(items))), "a permutation")
            for a, b in zip(result, result[1:]):
                self.assertTrue(a["k"] > b["k"] or (a["k"] == b["k"] and a["i"] < b["i"]) if descending else a["k"] < b["k"] or (a["k"] == b["k"] and a["i"] < b["i"]))
            data = list(range(rng.randint(0, 20)))
            limit = rng.randint(1, 6)
            got, offset = [], 0
            while True:
                page = self.go("page", {"operation": "offset", "items": data, "limit": limit, "offset": offset})
                got += page["items"]
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            self.assertEqual(got, data)
            values = [rng.choice([1, 2, 3, "a", None, [1], 1.5]) for _ in range(rng.randint(0, 8))]
            unique = self.go("select", {"operation": "distinct", "values": values})["values"]
            report = self.go("select", {"operation": "deduplicate_report", "values": values})["values"][0]
            self.assertEqual((report["input_count"], report["unique_count"]), (len(values), len(unique)))
            self.assertEqual(typed(self.go("select", {"operation": "distinct", "values": unique})["values"]), typed(unique), "distinct is idempotent")


STUDIO_GOLDEN = json.loads((Path(__file__).resolve().parent / "fixtures" / "studio_golden.json").read_text(encoding="utf-8"))


def studio_norm(value):
    """JavaScript cannot tell 1 from 1.0, so integral floats compare as integers."""
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else value
    if isinstance(value, (list, tuple)):
        return [studio_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: studio_norm(v) for k, v in value.items()}
    return value


def studio_canon(value):
    return json.dumps(studio_norm(value), sort_keys=True, ensure_ascii=False)


def studio_call(fn, arg):
    """The Python reference for each function recorded from Ironmate's studio/core.js."""
    if fn == "jsnum":
        return web_ui.js_number(arg)
    if fn == "jsjson":
        return web_ui.js_json(arg)
    if fn == "heatColor":
        return web_ui.studio_heat_color(*arg)
    if fn == "matrix":
        return web_ui.studio_matrix(arg)
    if fn == "validate":
        return web_ui.studio_validate(arg)
    if fn == "mosaic":
        return list(web_ui.studio_mosaic_rgba(bytes(arg[0]), *arg[1:]))
    if fn == "arrow":
        return web_ui.studio_arrow_geometry(*arg)
    if fn == "outputSize":
        return web_ui.studio_output_size(*arg)
    if fn == "pngPayload":
        return web_ui.studio_png_payload(bytes(arg))
    if fn == "textLayout":
        return web_ui.studio_text_layout(arg)
    if fn == "layerSVG":
        return web_ui.studio_layer_svg(arg)
    if fn == "svg":
        return web_ui.studio_svg(arg[0], None, arg[1])
    if fn == "words":
        return web_ui.studio_words(arg)
    if fn == "graphemes":
        return web_ui.studio_graphemes(arg)
    if fn == "sincos":
        return [web_ui.studio_sin(arg), web_ui.studio_cos(arg)]
    if fn in ("demo", "stampDemo"):
        scene = web_ui.studio_demo_scene() if fn == "demo" else web_ui.studio_stamp_demo_scene()
        for i, layer in enumerate(scene["layers"]):
            layer["id"] = f"L{i}"
        return scene
    if fn == "history":
        history = None
        states = []
        for op, scene in arg:
            if op == "new":
                history = web_ui.StudioHistory(scene)
            elif op == "commit":
                history.commit(scene)
            elif op == "undo":
                history.undo()
            else:
                history.redo()
            states.append([history.index, len(history.items)])
        return {"states": states, "items": history.items, "workspace": web_ui.studio_workspace_text(history)}
    raise AssertionError(fn)


class ImageStudioTests(unittest.TestCase):
    """The Ironmate image studio. The golden values are Ironmate's studio/core.js own outputs (recorded by Node, never produced by this code)."""

    def blank(self, **patch):
        return {"schema": web_ui.STUDIO_SCHEMA, "width": 64, "height": 64, "background": "none", "layers": [], **patch}

    def history(self):
        history = web_ui.StudioHistory(self.blank())
        following = history.current
        following["background"] = "#123456"
        history.commit(following)
        history.undo()
        return history

    def run_cli(self, *argv, stdin=None):
        done = subprocess.run([sys.executable, str(Path(web_ui.__file__)), *map(str, argv)], input=stdin, capture_output=True, timeout=60)
        return done.returncode, done.stdout, done.stderr.decode("utf-8")

    # --- the originals' own outputs -------------------------------------------------------------------------------------------------------------
    def test_every_recorded_core_js_output_is_reproduced_exactly(self):
        counts = {}
        for case in STUDIO_GOLDEN["cases"]:
            fn, arg = case["fn"], case["arg"]
            counts[fn] = counts.get(fn, 0) + 1
            with self.subTest(fn=fn, n=counts[fn]):
                if "error" in case:
                    with self.assertRaises(web_ui.StudioError) as caught:
                        studio_call(fn, arg)
                    self.assertEqual(str(caught.exception), case["error"])
                else:
                    got, expect = studio_call(fn, arg), case["ok"]
                    self.assertEqual(got if isinstance(expect, str) else studio_canon(got), expect if isinstance(expect, str) else studio_canon(expect))
        self.assertGreaterEqual(len(counts), 15, "every function core.js has is covered")
        self.assertGreaterEqual(len(STUDIO_GOLDEN["cases"]), 500)

    # --- Ironmate's tests/test_image_studio.py -------------------------------------------------------------------------------------------------
    def test_heatmap_keeps_values_gaps_labels_and_source(self):
        source = {"data": [{"type": "heatmap", "z": [[-2.123456789012345, None, 4], [0, 1, 2]], "x": [2024, 2025, 2026], "y": ["中日", "巨人"], "zmin": -4, "zmax": 8}], "layout": {"title": {"text": "source"}}}
        scene = web_ui.studio_heatmap_scene(source)
        layer = scene["layers"][0]
        self.assertEqual((layer["z"], layer["xlabels"], layer["ylabels"], layer["low"], layer["high"]), ([[-2.123456789012345, None, 4], [0, 1, 2]], [2024, 2025, 2026], ["中日", "巨人"], -4, 8))
        self.assertIs(scene["source"], source)
        self.assertIsNone(layer["z"][0][1])
        self.assertEqual(web_ui.studio_validate(scene), scene, "a scene made from a matrix is already valid")

    def test_unsafe_or_empty_matrices_are_refused(self):
        for source in ([[True]], [[float("inf")]], [[2 ** 53]], [[1e100]], [[2 ** 1024]], [[1], [1, 2]], [], {"data": []}):
            with self.subTest(source=repr(source)[:30]), self.assertRaises(web_ui.StudioError):
                web_ui.studio_heatmap_scene(source)

    def test_transparent_rgb_does_not_pollute_a_block_average(self):
        # one opaque red pixel and one fully transparent blue pixel average to half-transparent red, not purple
        got = web_ui.studio_mosaic_rgba(bytes([255, 0, 0, 255, 0, 0, 255, 0]), 2, 1, 2, 256)
        self.assertEqual(list(got), [255, 0, 0, 128] * 2)

    def test_svg_escapes_text_and_keeps_gaps_visible(self):
        scene = web_ui.studio_heatmap_scene([[1, None, 2]])
        scene["layers"].append({"id": "text", "kind": "text", "name": "custom", "x": 10, "y": 20, "w": 500, "h": 100, "opacity": 0.5, "rotation": 30, "fontSize": 40, "fill": "#112233", "text": "<script>alert(1)</script> & 🌱\n次へ"})
        svg = web_ui.studio_svg(scene)
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)
        self.assertIn("欠測", svg)
        self.assertIn("🌱", svg)

    def test_history_saves_a_copy_undoes_and_branches(self):
        scene = web_ui.studio_heatmap_scene([[1, None, 2]])
        history = web_ui.StudioHistory(scene)
        edit = history.current
        edit["layers"][0]["levels"] = 4
        history.commit(edit)
        edit["layers"][0]["z"][0][0] = 999
        self.assertEqual(history.current["layers"][0]["z"][0][0], 1, "an edit after the commit does not reach the history")
        self.assertEqual(history.undo(), scene)
        history.redo()
        history.undo()
        branch = history.current
        branch["layers"].pop()
        history.commit(branch)
        self.assertEqual(len(history.redo()["layers"]), 0, "a new edit after undo drops the redo branch")
        self.assertEqual(len(history.items), 2)
        history.commit(history.current)
        self.assertEqual(len(history.items), 2, "an edit that changes nothing is not recorded")

    def test_forty_states_at_most(self):
        history = web_ui.StudioHistory(self.blank())
        for i in range(60):
            scene = history.current
            scene["width"] = 64 + i + 1
            history.commit(scene)
        self.assertEqual((len(history.items), history.index, history.items[0]["width"], history.items[-1]["width"]), (40, 39, 64 + 21 + 0, 64 + 60))

    def test_untrusted_scenes_with_outside_images_or_bad_geometry_are_refused(self):
        scene = web_ui.studio_heatmap_scene([[1]])
        nan = web_ui.studio_clone(scene)
        nan["layers"][0]["rotation"] = float("nan")
        outside = web_ui.studio_clone(scene)
        outside["layers"][0] = {**outside["layers"][0], "kind": "image", "src": "https://example.com/a.png", "cell": 1, "levels": 256}
        twin = web_ui.studio_clone(scene)
        twin["layers"].append(web_ui.studio_clone(twin["layers"][0]))
        for bad in (nan, outside, twin):
            with self.assertRaises(web_ui.StudioError):
                web_ui.studio_svg(bad)

    # --- Ironmate's tests/studio_workspace.test.cjs ---------------------------------------------------------------------------------------------
    def test_workspace_restores_index_redo_branch_unicode_and_is_detached(self):
        history = self.history()
        history.items[1]["source"] = {"note": "🌱日本語"}
        text = web_ui.studio_workspace_text(history)
        restored = web_ui.studio_workspace_history(text)
        self.assertEqual(restored.index, 0)
        self.assertEqual(restored.current, history.current)
        self.assertEqual(restored.redo(), history.items[1])
        restored.items[1]["source"]["note"] = "changed"
        self.assertEqual(history.items[1]["source"]["note"], "🌱日本語")
        self.assertIn("🌱日本語", text, "Unicode is written as it is")

    def test_workspace_validates_index_schema_count_and_every_scene(self):
        record = json.loads(web_ui.studio_workspace_text(self.history()))
        for patch in ({"schema": "wrong"}, {"index": -1}, {"index": 2}, {"index": 0.5}, {"items": []}, {"items": [self.blank()] * 41}, {"items": [self.blank(), self.blank(width=-1)]}, {"items": "x"}, {"index": True}):
            with self.subTest(patch=str(patch)[:40]), self.assertRaises(web_ui.StudioError):
                web_ui.studio_workspace_history(json.dumps({**record, **patch}))
        history = web_ui.StudioHistory(self.blank())
        history.index = 1
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_workspace_text(history)
        for bad in (None, 5, b"{}", "", "[]", "{", "null"):
            with self.subTest(bad=repr(bad)), self.assertRaises((web_ui.StudioError, ValueError)):
                web_ui.studio_workspace_history(bad)

    def test_workspace_limit_is_32_mib_of_utf8_inclusive(self):
        text = web_ui.studio_workspace_text(self.history())
        limit = web_ui.STUDIO_WORKSPACE_MAX_BYTES
        exact = text + " " * (limit - len(text.encode("utf-8")))
        self.assertEqual(len(exact.encode("utf-8")), limit)
        self.assertEqual(web_ui.studio_workspace_history(exact).current, self.blank())
        with self.assertRaisesRegex(web_ui.StudioError, "32MiB"):
            web_ui.studio_workspace_history(exact + " ")
        # below 32M characters yet above 32 MiB as UTF-8
        large = json.loads(text)
        large["items"][0]["source"] = "🌱" * 8_388_608
        multibyte = json.dumps(large, ensure_ascii=False)
        self.assertLess(len(multibyte), limit)
        self.assertGreater(len(multibyte.encode("utf-8")), limit)
        with self.assertRaisesRegex(web_ui.StudioError, "32MiB"):
            web_ui.studio_workspace_history(multibyte)

    def test_writer_refuses_repeated_images_over_budget_and_accepts_a_trimmed_history(self):
        scene = self.blank()
        scene["layers"].append({"id": "img", "kind": "image", "x": 0, "y": 0, "w": 64, "h": 64, "rotation": 0, "opacity": 1, "src": "data:image/png;base64," + "A" * 8_000_000, "cell": 1, "levels": 256})
        history = web_ui.StudioHistory(scene)
        history.items = [scene] * 5
        history.index = 2
        with self.assertRaisesRegex(web_ui.StudioError, "32MiB"):
            web_ui.studio_workspace_text(history)
        self.assertEqual(len(history.items), 5, "a refused save does not touch the history")
        trimmed = web_ui.StudioHistory(history.current)
        self.assertEqual(web_ui.studio_workspace_history(web_ui.studio_workspace_text(trimmed)).current, history.current)

    # --- the scene and its parts ---------------------------------------------------------------------------------------------------------------
    def test_refusal_messages_are_the_originals_japanese_text(self):
        cases = [(self.blank(schema="x"), "シーンの形式・サイズが不正です（最大100レイヤー、4MP）"), (self.blank(width=0), "シーンの形式・サイズが不正です（最大100レイヤー、4MP）")]
        for scene, message in cases:
            with self.assertRaises(web_ui.StudioError) as caught:
                web_ui.studio_validate(scene)
            self.assertEqual(str(caught.exception), message)
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_validate(self.blank(layers=[web_ui.studio_base_layer("rect", "a")] * 101))
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_validate(self.blank(width=4096, height=4096))
        self.assertEqual(web_ui.studio_validate(self.blank(width=2048, height=2048))["width"], 2048)

    def test_a_click_places_every_tool_where_it_was_pressed(self):
        for tool in ("rect", "ellipse", "triangle", "text", "stamp", "arrow", "clock"):
            layer = web_ui.studio_place(tool, "a", 123.5, 45, text="x")
            self.assertEqual((layer["x"], layer["y"]), (123.5, 45), tool)
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_place("star", "a", 0, 0)

    def test_the_two_demo_scenes_are_valid_and_drawn(self):
        for scene in (web_ui.studio_demo_scene(), web_ui.studio_stamp_demo_scene(), web_ui.studio_blank()):
            self.assertEqual(web_ui.studio_validate(scene), scene)
            svg = web_ui.studio_svg(scene)
            self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"'))
            ET.fromstring(svg)
        kinds = {layer["kind"] for layer in web_ui.studio_demo_scene()["layers"]} | {layer["kind"] for layer in web_ui.studio_stamp_demo_scene()["layers"]}
        self.assertGreaterEqual(len(kinds), 4)

    def test_every_layer_kind_is_drawn_as_well_formed_svg(self):
        scene = self.blank(width=400, height=300, background="#FFFFFF")
        scene["layers"] = [web_ui.studio_place(tool, tool, 40 + 8 * i, 40 + 8 * i) for i, tool in enumerate(("rect", "ellipse", "triangle", "arrow", "clock"))]
        scene["layers"].append(web_ui.studio_text_layer("Hello, 世界 🌱", "t", 20, 200))
        scene["layers"].append(web_ui.studio_matrix_layer([[1, 2], [3, None]], "h", 400, 300))
        document = ET.fromstring(web_ui.studio_svg(scene))
        self.assertEqual(document.get("width"), "400")
        ids = [g.get("data-layer") for g in document.iter("{http://www.w3.org/2000/svg}g") if g.get("data-layer")]
        self.assertEqual(ids, ["rect", "ellipse", "triangle", "arrow", "clock", "t", "h"])

    def test_scale_and_output_size(self):
        self.assertEqual(web_ui.studio_output_size(self.blank(width=333, height=720), 2), {"width": 666, "height": 1440})
        for scale in (0.2, 9, "x", 0):
            with self.assertRaises(web_ui.StudioError):
                web_ui.studio_output_size(self.blank(), scale)
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_output_size(self.blank(width=4096, height=4096), 8)
        svg = web_ui.studio_svg(self.blank(width=100, height=64), None, 4)
        self.assertIn('width="400" height="256" viewBox="0 0 100 64"', svg)

    def test_text_wraps_by_words_and_by_characters_for_long_words(self):
        layer = {**web_ui.studio_text_layer("a very long line of ordinary words that should wrap into several lines", "t", 0, 0, wrap=True), "w": 120, "fontSize": 16}
        paragraphs = web_ui.studio_text_layout(layer)
        self.assertEqual(len(paragraphs), 1)
        lines = paragraphs[0]
        self.assertGreater(len(lines), 2)
        self.assertEqual("".join(lines).replace(" ", ""), layer["text"].replace(" ", ""))
        self.assertTrue(all(web_ui.studio_measure(line, layer) <= layer["w"] for line in lines))
        glued = web_ui.studio_text_layout({**layer, "text": "x" * 40, "w": 100})[0]
        self.assertTrue(all(web_ui.studio_measure(line, layer) <= 100 for line in glued) and "".join(glued) == "x" * 40)
        self.assertEqual(web_ui.studio_words("Hello, world! can't stop 3.14"), ["Hello", ",", " ", "world", "!", " ", "can't", " ", "stop", " ", "3.14"])
        self.assertEqual(web_ui.studio_graphemes("é🇯🇵👨‍👩‍👧x"), ["é", "🇯🇵", "👨‍👩‍👧", "x"])

    def test_a_line_may_be_exactly_as_wide_as_the_box(self):
        measure = lambda text: len(text) * 10
        layer = {**web_ui.studio_text_layer("abcd efgh ij", "t", 0, 0, wrap=True), "fontSize": 10}
        for width, want in ((40, ["abcd", "efgh", "ij"]), (39, ["abc", "d", "efg", "h", "ij"]), (50, ["abcd", "efgh", "ij"]), (90, ["abcd efgh", "ij"]), (89, ["abcd", "efgh ij"]), (110, ["abcd efgh", "ij"]),
                           (120, ["abcd efgh ij"]), (119, ["abcd efgh", "ij"])):
            self.assertEqual(web_ui.studio_text_layout({**layer, "w": width}, measure), [want], width)
        # a word longer than the box is cut between characters, and a character exactly filling the box stays
        self.assertEqual(web_ui.studio_text_layout({**layer, "text": "abcdefghij", "w": 30}, measure), [["abc", "def", "ghi", "j"]])
        self.assertEqual(web_ui.studio_text_layout({**layer, "text": "abcdefghij", "w": 25}, measure), [["ab", "cd", "ef", "gh", "ij"]])
        self.assertEqual(web_ui.studio_text_layout({**layer, "text": "ab", "w": 5}, measure), [["a", "b"]], "a glyph wider than the box is never squeezed")

    def test_the_workspace_writer_stops_at_exactly_32_mib(self):
        limit = web_ui.STUDIO_WORKSPACE_MAX_BYTES
        scene = self.blank(source="")
        empty = len(web_ui.studio_workspace_text(web_ui.StudioHistory(scene)).encode("utf-8"))
        fits = web_ui.StudioHistory(self.blank(source="x" * (limit - empty)))
        self.assertEqual(len(web_ui.studio_workspace_text(fits).encode("utf-8")), limit)
        over = web_ui.StudioHistory(self.blank(source="x" * (limit - empty + 1)))
        with self.assertRaisesRegex(web_ui.StudioError, "32MiB"):
            web_ui.studio_workspace_text(over)

    def test_clock_hands_use_the_fdlibm_sin_and_cos_of_node(self):
        # Node 22's Math.sin and Math.cos; glibc gives -0.5984721441039565 for sin(-2.5), one bit away, and other engines and versions differ in the last bit too
        for x, sin, cos in ((0.5, 0.479425538604203, 0.8775825618903728), (1, 0.8414709848078965, 0.5403023058681398), (-2.5, -0.5984721441039564, -0.8011436155469337),
                            (7.9, 0.998941341839772, -0.04600212563953695), (0.5235987755982988, 0.49999999999999994, 0.8660254037844387),
                            (1.0471975511965976, 0.8660254037844386, 0.5000000000000001), (5.497787143782139, -0.707106781186547, 0.707106781186548),
                            (0.1, 0.09983341664682815, 0.9950041652780257), (2.356194490192345, 0.7071067811865476, -0.7071067811865475)):
            self.assertEqual((web_ui.studio_sin(x), web_ui.studio_cos(x)), (sin, cos), x)
        for x in (0, math.pi / 2, math.pi, -math.pi, 2 * math.pi, 6.9):
            self.assertAlmostEqual(web_ui.studio_sin(x), math.sin(x), places=12)
            self.assertAlmostEqual(web_ui.studio_cos(x), math.cos(x), places=12)
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_sin(12345.6789)

    def test_studio_json_is_read_the_way_json_parse_reads_it(self):
        self.assertEqual(web_ui.studio_parse("[9007199254740993, 9007199254740995, 1e2, -0, 1.5]"), [9007199254740992, 9007199254740996.0, 100.0, 0, 1.5])
        self.assertEqual(web_ui.js_number(web_ui.studio_parse("9007199254740995")), "9007199254740996")
        for text in ("1" + "0" * 400, "1e999", "NaN", "Infinity", "-Infinity", "[" * 100000):
            with self.subTest(text=text[:12]), self.assertRaises(ValueError):
                web_ui.studio_parse(text)
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_heatmap_scene([[2 ** 1024]])
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.json"
            big.write_text('[[1' + '0' * 400 + ']]', encoding="utf-8")
            self.assertEqual(self.run_cli("--studio-heatmap", big)[0], 2)
            self.assertEqual(self.run_cli("--studio-render", big)[0], 2)

    def test_javascript_number_and_json_text(self):
        self.assertEqual([web_ui.js_number(x) for x in (1.0, 0.1 + 0.2, 1e21, 1e-7, 123456789.123456789, -0.0, 100, 2 ** 53)], ["1", "0.30000000000000004", "1e+21", "1e-7", "123456789.12345679", "0", "100", "9007199254740992"])
        self.assertEqual(web_ui.js_json({"b": 1, "2": 2, "1": 3, "a": [1.0, None, True, "é\n\""]}), '{"1":3,"2":2,"b":1,"a":[1,null,true,"é\\n\\""]}')
        self.assertEqual(web_ui.js_json({"a": [1, {"b": 2}], "c": []}, 2), '{\n  "a": [\n    1,\n    {\n      "b": 2\n    }\n  ],\n  "c": []\n}')

    # --- images --------------------------------------------------------------------------------------------------------------------------------
    def test_png_codec_round_trips_and_refuses_what_it_cannot_read(self):
        rng = random.Random(7)
        rgba = bytes(rng.randrange(256) for _ in range(5 * 3 * 4))
        data = web_ui.studio_png_encode(5, 3, rgba)
        self.assertEqual(web_ui.studio_png_decode(data), (5, 3, rgba))
        self.assertEqual(web_ui.studio_png_payload(data)["mimeType"], "image/png")
        broken = bytearray(data)
        broken[-20] ^= 1
        for bad in (b"GIF89a", bytes(broken), data[:30], b"\x89PNG\r\n\x1a\n"):
            with self.subTest(bad=bad[:12]), self.assertRaises(web_ui.StudioError):
                web_ui.studio_png_decode(bad)
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_png_encode(2, 2, b"\0" * 5)

    def test_png_filters_and_colour_types_that_browsers_write_are_read(self):
        def png(width, height, color, rows, palette=b"", trns=b""):
            chunk = lambda kind, body: struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
            out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
            out += (chunk(b"PLTE", palette) if palette else b"") + (chunk(b"tRNS", trns) if trns else b"")
            return out + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
        # RGB, grey, grey+alpha and palette, each with the filter a browser might choose
        self.assertEqual(web_ui.studio_png_decode(png(2, 1, 2, [b"\x00" + bytes([1, 2, 3, 4, 5, 6])]))[2], bytes([1, 2, 3, 255, 4, 5, 6, 255]))
        self.assertEqual(web_ui.studio_png_decode(png(2, 1, 0, [b"\x00" + bytes([9, 200])]))[2], bytes([9, 9, 9, 255, 200, 200, 200, 255]))
        self.assertEqual(web_ui.studio_png_decode(png(1, 1, 4, [b"\x00" + bytes([7, 128])]))[2], bytes([7, 7, 7, 128]))
        self.assertEqual(web_ui.studio_png_decode(png(2, 1, 3, [b"\x00" + bytes([1, 0])], palette=bytes([10, 20, 30, 40, 50, 60]), trns=bytes([255, 100])))[2], bytes([40, 50, 60, 100, 10, 20, 30, 255]))
        sub = web_ui.studio_png_decode(png(3, 1, 0, [b"\x01" + bytes([10, 5, 5])]))[2]
        self.assertEqual(sub, bytes([10, 10, 10, 255, 15, 15, 15, 255, 20, 20, 20, 255]))
        up = web_ui.studio_png_decode(png(2, 2, 0, [b"\x00" + bytes([10, 20]), b"\x02" + bytes([1, 2])]))[2]
        self.assertEqual(up[8:], bytes([11, 11, 11, 255, 22, 22, 22, 255]))
        average = web_ui.studio_png_decode(png(2, 2, 0, [b"\x00" + bytes([10, 20]), b"\x03" + bytes([4, 4])]))[2]
        self.assertEqual(average[8:], bytes([9, 9, 9, 255, 18, 18, 18, 255]))
        paeth = web_ui.studio_png_decode(png(2, 2, 0, [b"\x00" + bytes([10, 20]), b"\x04" + bytes([1, 1])]))[2]
        self.assertEqual(paeth[8:], bytes([11, 11, 11, 255, 21, 21, 21, 255]))
        with self.assertRaises(web_ui.StudioError):
            web_ui.studio_png_decode(png(1, 1, 0, [b"\x09" + bytes([0])]))

    def png_file(self, width, height, color, rows, depth=8, interlace=0, palette=b"", trns=b"", crc_ok=True, iend=True, idat=True):
        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) if crc_ok else 0)
        out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace))
        out += (chunk(b"PLTE", palette) if palette else b"") + (chunk(b"tRNS", trns) if trns else b"")
        out += chunk(b"IDAT", zlib.compress(b"".join(rows))) if idat else b""
        return out + (chunk(b"IEND", b"") if iend else b"")

    def filtered(self, kind, raw, previous, bpp):
        """One scanline written with PNG filter ``kind`` (the encoder side, written here on its own)."""
        out = bytearray()
        for i, value in enumerate(raw):
            a = raw[i - bpp] if i >= bpp else 0
            b = previous[i]
            c = previous[i - bpp] if i >= bpp else 0
            if kind == 0:
                predictor = 0
            elif kind == 1:
                predictor = a
            elif kind == 2:
                predictor = b
            elif kind == 3:
                predictor = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else b if pb <= pc else c
            out.append((value - predictor) & 255)
        return bytes([kind]) + bytes(out)

    def test_every_colour_type_and_filter_is_read_as_an_independent_encoder_and_pillow_read_it(self):
        import io
        from PIL import Image
        rng = random.Random(404)
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
        palette = bytes(rng.randrange(256) for _ in range(3 * 6))
        trns = bytes([255, 0, 128])
        for color, bpp in channels.items():
            for kind in range(5):
                for width, height in ((1, 1), (2, 3), (5, 4), (9, 2), (3, 7)):
                    samples = [bytes(rng.randrange(6) if color == 3 else rng.randrange(256) for _ in range(width * bpp)) for _ in range(height)]
                    rows, previous = [], bytes(width * bpp)
                    for row in samples:
                        rows.append(self.filtered(kind, row, previous, bpp))
                        previous = row
                    data = self.png_file(width, height, color, rows, palette=palette if color == 3 else b"", trns=trns if color == 3 else b"")
                    got_width, got_height, rgba = web_ui.studio_png_decode(data)
                    self.assertEqual((got_width, got_height), (width, height))
                    with Image.open(io.BytesIO(data)) as image:
                        image.load()
                        self.assertEqual(rgba, image.convert("RGBA").tobytes(), (color, kind, width, height))
        # all five filters on the rows of one image, each row its own
        rows, previous = [], bytes(12)
        for kind in range(5):
            row = bytes(rng.randrange(256) for _ in range(12))
            rows.append(self.filtered(kind, row, previous, 4))
            previous = row
        data = self.png_file(3, 5, 6, rows)
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            self.assertEqual(web_ui.studio_png_decode(data)[2], image.convert("RGBA").tobytes())

    def test_a_png_the_studio_cannot_use_is_refused_with_its_reason(self):
        zeros = lambda w, h, c=4: [b"\x00" + bytes(w * c)] * h
        ok = self.png_file(2, 2, 6, zeros(2, 2))
        self.assertEqual(web_ui.studio_png_decode(ok)[:2], (2, 2))
        unsupported = "8ビット・非インターレースの4MP以下のPNGに対応しています"
        broken = "PNGが壊れています"
        cases = [(self.png_file(2, 2, 6, zeros(2, 2), depth=16), unsupported), (self.png_file(2, 2, 6, zeros(2, 2), interlace=1), unsupported), (self.png_file(2, 2, 1, zeros(2, 2)), unsupported),
                 (self.png_file(2, 2, 5, zeros(2, 2)), unsupported), (self.png_file(2048, 2049, 6, zeros(1, 1)), unsupported), (self.png_file(0, 2, 6, []), unsupported),
                 (self.png_file(2, 2, 6, zeros(2, 2), crc_ok=False), broken), (self.png_file(2, 2, 6, zeros(2, 2), idat=False), broken), (self.png_file(2, 2, 6, zeros(2, 3)), broken),
                 (self.png_file(2, 2, 6, zeros(2, 1)), broken), (self.png_file(2, 2, 6, [b"\x09" + bytes(8)] * 2), broken), (ok[:-3], broken), (ok[:20], broken), (b"\x89PNG\r\n\x1a\n", broken),
                 (b"GIF89a" + bytes(40), "PNGではありません")]
        for data, message in cases:
            with self.assertRaises(web_ui.StudioError) as caught:
                web_ui.studio_png_decode(data)
            self.assertEqual(str(caught.exception), message)
        self.assertEqual(web_ui.studio_png_decode(self.png_file(2048, 2048, 0, [b"\x00" + bytes(2048)] * 2048))[:2], (2048, 2048), "4 MP exactly is fine")
        self.assertEqual(web_ui.studio_png_decode(self.png_file(2, 2, 6, zeros(2, 2), iend=False))[:2], (2, 2), "a file that stops after its image data is still read")
        trailing = ok + b"junk"
        self.assertEqual(web_ui.studio_png_decode(trailing)[:2], (2, 2))

    def test_every_limit_is_exact(self):
        def refused(call, message=None):
            with self.assertRaises(web_ui.StudioError) as caught:
                call()
            if message:
                self.assertEqual(str(caught.exception), message)
        # the PNG hand-off: 32 MiB exactly, one byte over, the signature, eight bytes at least
        signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
        limit = 32 * 1024 * 1024
        self.assertEqual(web_ui.studio_png_payload(signature + bytes(limit - 8))["bytes"], limit)
        refused(lambda: web_ui.studio_png_payload(signature + bytes(limit - 7)), "32MiB以下のPNGが必要です")
        self.assertEqual(web_ui.studio_png_payload(signature)["bytes"], 8)
        refused(lambda: web_ui.studio_png_payload(signature[:7]))
        refused(lambda: web_ui.studio_png_payload(b"x" * 20))
        # numbers in a matrix: 2**53 - 1 is the largest safe whole number
        self.assertEqual(web_ui.studio_matrix([[2 ** 53 - 1, -(2 ** 53 - 1)]])["high"], 2 ** 53 - 1)
        for bad in (2 ** 53, -(2 ** 53), float(2 ** 53), 2.0 ** 60, 2 ** 54):
            refused(lambda: web_ui.studio_matrix([[bad]]))
        refused(lambda: web_ui.studio_matrix({"z": [[1]], "zmin": 2 ** 53}), "色の範囲には有限の安全な数値を指定してください")
        self.assertEqual(web_ui.studio_matrix([[None, None]])["low"], 0)
        self.assertEqual(web_ui.studio_matrix([[None, None]])["high"], 1)
        # sizes of a scene: 64 to 4096 a side, 4 MP, 100 layers, ids of 100 UTF-16 units
        for width, height, ok in ((64, 64, True), (63, 64, False), (64, 63, False), (4096, 1024, True), (4096, 1025, False), (4097, 64, False), (2048, 2048, True), (2049, 2048, False)):
            scene = self.blank(width=width, height=height)
            if ok:
                self.assertEqual(web_ui.studio_validate(scene)["width"], width)
            else:
                refused(lambda: web_ui.studio_validate(scene), "シーンの形式・サイズが不正です（最大100レイヤー、4MP）")
        layer = lambda i: web_ui.studio_base_layer("rect", f"r{i}") | {"fill": "none", "stroke": "none", "strokeWidth": 0}
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[layer(i) for i in range(100)]))["layers"]), 100)
        refused(lambda: web_ui.studio_validate(self.blank(layers=[layer(i) for i in range(101)])))
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[layer(0) | {"id": "x" * 100}]))["layers"]), 1)
        refused(lambda: web_ui.studio_validate(self.blank(layers=[layer(0) | {"id": "x" * 101}])), "レイヤーのIDまたは種類が不正です")
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[layer(0) | {"id": "😀" * 50}]))["layers"]), 1, "100 UTF-16 units")
        refused(lambda: web_ui.studio_validate(self.blank(layers=[layer(0) | {"id": "😀" * 51}])))
        for field, low, high in (("x", -8192, 8192), ("y", -8192, 8192), ("w", 1, 8192), ("h", 1, 8192), ("rotation", -360, 360), ("opacity", 0, 1), ("strokeWidth", 0, 64)):
            for value, ok in ((low, True), (high, True), (low - 1, False), (high + 1, False)):
                call = lambda: web_ui.studio_validate(self.blank(layers=[layer(0) | {field: value}]))
                self.assertEqual(call()["layers"][0][field], value) if ok else refused(call)
        # text: 2000 UTF-16 units, 4 to 512 px
        text = web_ui.studio_text_layer("a", "t", 0, 0)
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[text | {"text": "a" * 2000}]))["layers"]), 1)
        refused(lambda: web_ui.studio_validate(self.blank(layers=[text | {"text": "a" * 2001}])), "テキストが不正です")
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[text | {"text": "😀" * 1000}]))["layers"]), 1)
        refused(lambda: web_ui.studio_validate(self.blank(layers=[text | {"text": "😀" * 1001}])))
        for size, ok in ((4, True), (512, True), (3.9, False), (512.1, False)):
            call = lambda: web_ui.studio_validate(self.blank(layers=[text | {"fontSize": size}]))
            self.assertEqual(call()["layers"][0]["fontSize"], size) if ok else refused(call, "テキストが不正です")
        # images: a PNG data URI of at most 12,000,000 characters, 20,000,000 in all; a mosaic cell 1..512 and 2..256 levels
        image = lambda n, i=0: web_ui.studio_image_layer("data:image/png;base64," + "A" * (n - 22), 1, 1, f"i{i}") | {"w": 1, "h": 1}
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[image(12000000)]))["layers"]), 1)
        refused(lambda: web_ui.studio_validate(self.blank(layers=[image(12000001)])), "画像は埋め込みPNGが必要です")
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[image(10000000, 0), image(10000000, 1)]))["layers"]), 2)
        refused(lambda: web_ui.studio_validate(self.blank(layers=[image(10000000, 0), image(10000001, 1)])), "シーンの画像合計は20MB以下にしてください")
        self.assertEqual(len(web_ui.studio_validate(self.blank(layers=[image(100, 0), image(100, 1)]))["layers"]), 2, "the total starts from zero")
        for field, low, high in (("cell", 1, 512), ("levels", 2, 256)):
            for value, ok in ((low, True), (high, True), (low - 1, False), (high + 1, False), (low + 0.5, False)):
                call = lambda: web_ui.studio_validate(self.blank(layers=[image(100) | {field: value}]))
                self.assertEqual(call()["layers"][0][field], value) if ok else refused(call, "モザイク設定が不正です")
        refused(lambda: web_ui.studio_validate(self.blank(layers=[image(100) | {"cell": 0, "levels": 256}])))
        refused(lambda: web_ui.studio_validate(self.blank(layers=[image(100) | {"cell": 1, "levels": 1}])))
        # a workspace holds 1 to 40 states
        for count, ok in ((1, True), (40, True), (41, False), (0, False)):
            record = json.dumps({"schema": web_ui.STUDIO_WORKSPACE_SCHEMA, "items": [self.blank()] * count, "index": 0})
            self.assertEqual(len(web_ui.studio_workspace_history(record).items), count) if ok else refused(lambda: web_ui.studio_workspace_history(record), "作業履歴の形式が不正です")
        history = web_ui.StudioHistory(self.blank())
        history.items = [self.blank()] * 40
        self.assertEqual(len(json.loads(web_ui.studio_workspace_text(history))["items"]), 40)
        history.items = [self.blank()] * 41
        refused(lambda: web_ui.studio_workspace_text(history), "作業履歴の形式が不正です")
        # the mosaic's own checks
        for args in ((b"\0" * 4, 1, 1, 0), (b"\0" * 4, 1, 1, 513), (b"\0" * 4, 1, 1, 1, 1), (b"\0" * 4, 1, 1, 1, 257), (b"\0" * 4, 0, 1, 1), (b"\0" * 4, 1, 0, 1), (b"\0" * 3, 1, 1, 1), (b"\0" * 4, 1.5, 1, 1)):
            refused(lambda: web_ui.studio_mosaic_rgba(*args), "モザイク入力が不正です")
        self.assertEqual(len(web_ui.studio_mosaic_rgba(b"\0" * 4, 1, 1, 512, 2)), 4)
        self.assertEqual(len(web_ui.studio_mosaic_rgba(b"\0" * 4 * 4, 2, 2, 1, 256)), 16)

    def test_defaults_text_boxes_and_json_text(self):
        arrow = web_ui.studio_place("arrow", "a", 1, 2)
        self.assertEqual((arrow["headStyle"], arrow["headPlacement"], arrow["fill"], arrow["stroke"], arrow["headSize"], arrow["strokeWidth"]), ("beginner", "tip", web_ui.STUDIO_FILL, web_ui.STUDIO_STROKE, 28, 4))
        clock = web_ui.studio_place("clock", "c", 1, 2)
        self.assertEqual((clock["hour"], clock["minute"], clock["name"], clock["w"], clock["h"]), (10, 10, "時計 10:10", 160, 160))
        text = web_ui.studio_place("text", "t", 1, 2)
        self.assertEqual((text["mono"], text["wrap"], text["font"], text["text"]), (True, False, "sans", ""))
        rect = web_ui.studio_place("rect", "r", 1, 2)
        self.assertEqual((rect["fill"], rect["w"], rect["h"], rect["outline"] if "outline" in rect else None), (web_ui.STUDIO_FILL, 180, 120, None))
        # a text stamp is as wide as its longest line (48 px a character, 120 to 700) and as high as its lines (62.4 px each, 70 at least)
        for value, w, h in (("", 120, 70), ("ab", 120, 70), ("abc", 144, 70), ("a" * 14, 672, 70), ("a" * 15, 700, 70), ("a\nbcde", 192, 2 * 48 * 1.3), ("ab\nc\nd", 120, 3 * 48 * 1.3), ("😀😀😀", 144, 70)):
            layer = web_ui.studio_text_layer(value, "t", 0, 0)
            self.assertEqual((layer["w"], layer["h"]), (w, h), value)
        self.assertEqual(web_ui.studio_text_layer("123456789012345", "t", 0, 0)["name"], "文字 / 123456789012")
        self.assertEqual(web_ui.studio_text_layer("😀" * 14, "t", 0, 0)["name"], "文字 / " + "😀" * 12, "a name takes twelve characters, not twelve UTF-16 units")
        self.assertEqual(web_ui.js_json({"é": "日本", "k": "\u2028"}), '{"é":"日本","k":"\u2028"}'.replace("\\u2028", "\u2028"))
        self.assertEqual(web_ui.js_json({"b": 1, "a": {"2": 1, "1": 2, "x": 3}}), '{"b":1,"a":{"1":2,"2":1,"x":3}}')
        self.assertEqual(web_ui.js_json([float("nan"), float("inf")]), "[null,null]")

    def test_an_image_layer_is_mosaicked_from_its_embedded_original(self):
        rgba = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
        src = "data:image/png;base64," + base64.b64encode(web_ui.studio_png_encode(2, 2, rgba)).decode("ascii")
        scene = self.blank(width=64, height=64, layers=[web_ui.studio_image_layer(src, 2, 2, "img", 64)])
        plain = web_ui.studio_render(scene)
        self.assertIn(src, plain, "a layer that keeps every pixel passes its image through")
        scene["layers"][0]["cell"] = 2
        mosaic = web_ui.studio_render(scene)
        self.assertNotIn(src, mosaic)
        one = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", mosaic).group(1)
        width, height, pixels = web_ui.studio_png_decode(base64.b64decode(one))
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(pixels, bytes(web_ui.studio_mosaic_rgba(rgba, 2, 2, 2, 256)))
        self.assertEqual(len(set(pixels[i:i + 4] for i in range(0, 16, 4))), 1)

    # --- the command line ----------------------------------------------------------------------------------------------------------------------
    def test_cli_renders_svg_json_heatmap_and_base64(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            scene = tmp / "scene.json"
            scene.write_text(web_ui.js_json(web_ui.studio_demo_scene(), 2), encoding="utf-8")
            code, out, err = self.run_cli("--studio-render", scene)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(out.decode("utf-8"), web_ui.studio_render(web_ui.studio_demo_scene()) + "\n")
            code, out, _ = self.run_cli("--studio-render", scene, "--scale", "2")
            self.assertIn('width="2560" height="1440"', out.decode("utf-8"))
            code, out, _ = self.run_cli("--studio-render", scene, "--format", "json")
            self.assertEqual(json.loads(out), web_ui.studio_validate(web_ui.studio_demo_scene()))
            matrix = tmp / "matrix.json"
            matrix.write_text("[[1,null,3]]", encoding="utf-8")
            result = tmp / "scene-out.json"
            code, out, err = self.run_cli("--studio-heatmap", matrix, "-o", result)
            self.assertEqual((code, out), (0, b""))
            self.assertEqual(json.loads(result.read_text(encoding="utf-8"))["layers"][0]["z"], [[1, None, 3]])
            old = result.read_bytes()
            code, _, err = self.run_cli("--studio-heatmap", matrix, "-o", result)
            self.assertEqual(code, 2)
            self.assertIn("--force", err)
            self.assertEqual(result.read_bytes(), old, "an existing file is never replaced without --force")
            matrix.write_text("[[2,3]]", encoding="utf-8")
            self.assertEqual(self.run_cli("--studio-heatmap", matrix, "-o", result, "--force")[0], 0)
            self.assertEqual(json.loads(result.read_text(encoding="utf-8"))["layers"][0]["z"], [[2, 3]])
            png = tmp / "a.png"
            png.write_bytes(web_ui.studio_png_encode(1, 1, bytes([1, 2, 3, 4])))
            code, out, _ = self.run_cli("--studio-base64", png)
            self.assertEqual(base64.b64decode(out.strip()), png.read_bytes())
            code, out, _ = self.run_cli("--studio-base64", png, "--data-uri")
            self.assertTrue(out.startswith(b"data:image/png;base64,"))

    def test_cli_bad_input_is_exit_2_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad = tmp / "bad.json"
            for text in ("{", "[1]", '{"schema":"ironmate-image-studio/1"}', "﻿", "nan"):
                bad.write_text(text, encoding="utf-8")
                for option in ("--studio-render", "--studio-heatmap"):
                    with self.subTest(text=text, option=option):
                        code, out, err = self.run_cli(option, bad)
                        self.assertEqual((code, out), (2, b""))
                        self.assertTrue(err.startswith("invalid studio input: "))
            self.assertEqual(self.run_cli("--studio-render", tmp / "missing.json")[0], 2)
            text = tmp / "t.png"
            text.write_bytes(b"not a png")
            code, _, err = self.run_cli("--studio-base64", text)
            self.assertEqual(code, 2)
            big = tmp / "big.json"
            big.write_bytes(b" " * 20_000_001)
            self.assertEqual(self.run_cli("--studio-render", big)[0], 2)

    # --- the page ------------------------------------------------------------------------------------------------------------------------------
    def test_the_page_is_one_self_contained_document_with_every_control_the_script_uses(self):
        page = web_ui.imagestudio_document()
        self.assertEqual(page.count('<script type="module">'), 1)
        self.assertEqual(page.count('id="imagestudio"'), 1)
        self.assertNotRegex(page, r"https?://(?!www\.w3\.org/2000/svg)")
        html = web_ui.imagestudio_html()
        names = re.findall(r'data-is="([a-z0-9]+)"', html)
        self.assertEqual(len(names), len(set(names)), "every control has its own name")
        source = web_ui._JS["imagestudio.js"]
        used = set(re.findall(r"\bel\.([a-z0-9]+)\b", source)) | set(re.findall(r'"([a-z]+)"', " ".join(re.findall(r"for\((?:const|let) \w+ of ?\[([^\]]*)\]\)el\[", source))))
        self.assertEqual(used - set(names), set(), "the script uses only controls the page has")
        self.assertEqual(set(names) - used, set(), "every control is used by the script")
        self.assertEqual(len(re.findall(r'name="is-tool"', html)), len(web_ui.STUDIO_TOOLS))
        self.assertEqual(len(re.findall(r"data-stamp=", html)), len(web_ui.STUDIO_EMOJI) + len(web_ui.STUDIO_KAOMOJI))
        self.assertIn("globalThis.webUiImageStudio=api", page)
        self.assertIn(".ui-imagestudio", web_ui.bundled_css())
        self.assertTrue(all(int(px) % 8 == 0 for px in re.findall(r"(\d+)px", web_ui._CSS["imagestudio.css"])), "pixel sizes are multiples of 8")
        self.assertIn("examples/image-studio.html", web_ui.example_pages())
        self.assertIn('href="./image-studio.html"', web_ui.example_pages()["examples/index.html"])
        self.assertNotIn("</script", source.lower())
        self.assertNotIn('"""', source)

    def test_the_js_constants_are_the_python_values(self):
        source = web_ui._JS["imagestudio.js"]
        want = {"SCHEMA": web_ui.STUDIO_SCHEMA, "WORKSPACE_SCHEMA": web_ui.STUDIO_WORKSPACE_SCHEMA, "WORKSPACE_MAX_BYTES": web_ui.STUDIO_WORKSPACE_MAX_BYTES, "PALETTE": list(web_ui.STUDIO_PALETTE),
                "FILL": web_ui.STUDIO_FILL, "STROKE": web_ui.STUDIO_STROKE, "BACKGROUND": web_ui.STUDIO_BACKGROUND, "WSPACE": web_ui._STU_WSPACE, "MIDLETTER": web_ui._STU_MIDLETTER,
                "MIDNUM": web_ui._STU_MIDNUM, "MIDNUMLET": web_ui._STU_MIDNUMLET, "NEWLINE": web_ui._STU_NEWLINE, "KATAKANA": [list(r) for r in web_ui._STU_KATAKANA],
                "HAN_HIRAGANA": [list(r) for r in web_ui._STU_HAN_HIRAGANA], "PICTOGRAPHIC": [list(r) for r in web_ui._STU_PICTOGRAPHIC], "WORD_OVERRIDES": [[k, [list(r) for r in rs]] for k, rs in web_ui._STU_WORD_OVERRIDES],
                "GRAPHEME_OVERRIDES": [[k, [list(r) for r in rs]] for k, rs in web_ui._STU_GRAPHEME_OVERRIDES]}
        text = web_ui._studio_js_constants()
        self.assertIn(text, source, "the module starts from these lines")
        found, decoder = {}, json.JSONDecoder()
        for line in text.splitlines():
            position = len(line) - len(line.removeprefix("export ").removeprefix("const "))
            while True:
                name = re.compile(r"([A-Z_]+)=").match(line, position)
                value, position = decoder.raw_decode(line, name.end())
                found[name.group(1)] = value
                if line[position] == ";":
                    break
                position += 1
        self.assertEqual(found, want)

    def test_the_platform_adapters_check_the_page(self):
        for name, fragment in (("web-ui-image-studio", None), ("web-ui-image-stamp", "is-tools-title")):
            adapter = web_ui.btk_adapter(name)
            self.assertEqual(adapter["url"], "http://127.0.0.1:8000/examples/image-studio.html" + ("" if fragment is None else "#" + fragment))
            self.assertNotEqual(adapter["click"]["before"], adapter["click"]["after"])
            self.assertTrue(all("imagestudio" in selector or selector.startswith("#is-") for selector in adapter["elements"]))
            self.assertFalse(any(selector.startswith("select") or "[data-is=\"scale\"]" in selector for selector in adapter["elements"]), "a select is covered through its label")
        self.assertEqual(len(web_ui.studio_demo_scene()["layers"]), int(web_ui.BTK_ADAPTERS["web-ui-image-studio"]["click"]["before"]))

    def test_random_scenes_survive_validation_and_a_workspace_round_trip(self):
        rng = random.Random(2026)
        kinds = ("rect", "ellipse", "triangle", "arrow", "clock")
        for _ in range(60):
            scene = self.blank(width=rng.randint(64, 900), height=rng.randint(64, 700), background=rng.choice(["none", "#FFFFFF", "#18A7A1"]))
            for i in range(rng.randint(0, 6)):
                scene["layers"].append(web_ui.studio_place(rng.choice(kinds), f"L{i}", rng.randint(-50, 900), rng.randint(-50, 700), outline=rng.random() < 0.5))
            history = web_ui.StudioHistory(scene)
            checked = history.current
            edit = web_ui.studio_clone(checked)
            edit["layers"].append(web_ui.studio_text_layer(rng.choice(["a", "日本語", "x y z", "🌱"]), "text", rng.randint(0, 100), rng.randint(0, 100)))
            history.commit(edit)
            restored = web_ui.studio_workspace_history(web_ui.studio_workspace_text(history))
            self.assertEqual((restored.index, restored.items), (history.index, history.items))
            ET.fromstring(web_ui.studio_svg(restored.current))


if __name__ == '__main__':
    unittest.main()
