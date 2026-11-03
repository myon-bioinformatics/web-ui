import base64
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
        self.assertEqual(sorted(w.BTK_ADAPTERS), ["web-ui-clipboard-shelf", "web-ui-composition-studio", "web-ui-coordinates", "web-ui-door", "web-ui-photo-studio", "web-ui-showcase"])
        for adapter_id in w.BTK_ADAPTERS:
            config = w.btk_adapter(adapter_id)
            with self.subTest(adapter_id):
                self.assertEqual(self.contract_errors(config), [])
                self.assertEqual(config["id"], adapter_id)
                self.assertIn("examples/" + w.BTK_ADAPTERS[adapter_id]["page"], pages)
                self.assertEqual(config["url"], "http://127.0.0.1:8000/examples/" + w.BTK_ADAPTERS[adapter_id]["page"])
        self.assertEqual(w.btk_adapter("web-ui-door", "http://localhost:9/x.html")["url"], "http://localhost:9/x.html")
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


if __name__ == '__main__':
    unittest.main()
