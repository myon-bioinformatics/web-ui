import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import json

import web_ui
from web_ui import (_node_launch_module, bundled_css, render_document, run_node, shared_scripts,
                    shared_stylesheets)

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

    def test_existing_assets_and_theme_order(self):
        links = shared_stylesheets('../vendor/web-ui', theme='github-like', stub=True)
        self.assertEqual(
            links[-2:],
            ('../vendor/web-ui/css/stub.css', '../vendor/web-ui/css/themes/github-like.css'),
        )
        for href in shared_stylesheets('.'):
            self.assertTrue((ROOT / href).is_file())
        self.assertIn('href="a&amp;b.css"', render_document(stylesheets=('a&b.css',)))

    def test_opt_in_shared_scripts_are_module_links(self):
        scripts = shared_scripts('.', names=('ui.js', 'stub.js'))
        self.assertEqual(scripts, ('./js/ui.js', './js/stub.js'))
        for src in scripts:
            self.assertTrue((ROOT / src).is_file())
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
        self.assertEqual(shared_stylesheets('https://example.test/pinned')[0],
                         'https://example.test/pinned/css/tokens.css')

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
            shared_stylesheets('https://example.test/main?ref=latest')
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
            [sys.executable, '-S', str(ROOT / 'web_ui.py'), '--stub'],
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
        result = run_node(ROOT / 'tests' / 'repository_diagnostics.node.js')
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
        self.assertEqual(sorted(marks), sorted(str(p.relative_to(ROOT / "css")) for p in (ROOT / "css").rglob("*.css")))
        themes = [m for m in marks if m.startswith("themes/")]
        self.assertEqual(marks[-len(themes):], themes)
        self.assertEqual(themes, sorted(themes))
        self.assertTrue(css.startswith("@layer base,components,theme;\n"))
        self.assertLess(css.index("@layer base,components,theme;"), css.index("@layer base{"))
        for path in (ROOT / "css").rglob("*.css"):
            self.assertIn(path.read_text(encoding="utf-8").strip("\n"), css)
        self.assertEqual(css, bundled_css(ROOT))
        self.assertFalse((ROOT / "css" / "web-ui.css").exists(), "the bundle is never written to the repository")

    def test_single_file_page_works_for_every_theme_without_links(self):
        css = bundled_css()
        for theme in ("modern", "github-like", "green"):
            html = render_document("hello", theme=theme, css=css)
            self.assertIn(f'data-ui-theme="{theme}"', html)
            self.assertNotIn('rel="stylesheet"', html)
            self.assertIn(f'body[data-ui-theme="{theme}"]', css)

    def test_candidate_theme_has_no_theme_file_to_link(self):
        links = shared_stylesheets("../vendor/web-ui", theme="green")
        self.assertEqual(links[-1], "../vendor/web-ui/css/components.css")
        self.assertFalse((ROOT / "css/themes/green.css").exists())

    def test_missing_checkout_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(OSError):
            bundled_css(empty)

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


WORLD = json.loads((ROOT / "examples/world.json").read_text(encoding="utf-8"))


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
        self.assertEqual(full.count('class="ui-sheet-item"'), 6)

    def test_css_has_one_rule_per_floor_category_and_shot(self):
        css = web_ui.world_css(WORLD)
        self.assertTrue(css.startswith("@layer components{") and css.endswith("}"))
        for fragment in ('#demo-floor-2f:checked) .ui-floor[data-floor="2f"]{display:block}',
                         '#demo-cat-food:checked) .ui-spot:not([data-category="food"]){display:none}',
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

    def test_front_page_regions_are_what_the_generators_write(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        region = lambda start, end: page.split(start)[1].split(end)[0]
        self.assertEqual(region("<!--world-->", "<!--/world-->"), web_ui.world_html(WORLD))
        self.assertEqual(region("<!--wall-->", "<!--/wall-->"), web_ui.theme_wall(range(12)))
        self.assertEqual(region("/*world-css*/", "/*/world-css*/"), web_ui.world_css(WORLD) + web_ui._WALL_CSS)
        self.assertEqual(region("/*world-js*/", "/*/world-js*/"), web_ui.WORLD_JS)

    def test_theme_wall_and_cli(self):
        wall = web_ui.theme_wall(range(12))
        self.assertEqual(wall.count('class="ui-wall-cell"'), 12)
        self.assertIn("--ui-radius:", wall)
        run = lambda *args: subprocess.run([sys.executable, "-S", "web_ui.py", *args], cwd=ROOT, capture_output=True,
                                           text=True, encoding="utf-8", timeout=60)
        shown = run("--world", "examples/world.json", "--theme", "green")
        self.assertEqual((shown.returncode, shown.stdout), (0, web_ui.world_document(WORLD, theme="green")))
        self.assertEqual(run("--theme-wall", "3").stdout, web_ui.theme_wall_document(3))
        self.assertEqual(run("--world", "no-such.json").returncode, 2)


if __name__ == '__main__':
    unittest.main()
