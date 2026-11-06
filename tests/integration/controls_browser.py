"""Required Chromium contract: python tests/integration/controls_browser.py -v.

Invoked explicitly by the browser CI job; missing Playwright/browser is an error.
The ordinary dependency-light unit suite does not discover this module.
"""
import base64
import functools
import http.server
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from support import flutter_case  # noqa: E402
from web_ui import (EXAMPLE_STUBS, showcase_document, bundled_css, write_js, board_clock, clean_message, clock_label, gauge_cells, gauge_state, minutes_until, travel_seconds, board_seconds,
                    clamp_focus, contrast_ratio, fit_zoom, render_document, section_browser, shared_scripts, stub_response, theme_wall_document, utc_offset_label,
                    world_document, zone_offset, zone_rows)


def photo_engine(playwright):
    """The browser the photo studio tests run in: ``WEBUI_BROWSER`` = chromium (default), firefox or webkit. CI runs each engine; a laptop usually has only Chromium."""
    return getattr(playwright, os.environ.get('WEBUI_BROWSER', 'chromium'))


def photo_device(playwright):
    """Context options of a Playwright device named by ``WEBUI_DEVICE`` (for example Pixel 7 or iPhone 13), else a desktop window. Emulation, not a device."""
    name = os.environ.get('WEBUI_DEVICE')
    if not name:
        return {'viewport': {'width': 800, 'height': 900}}
    options = dict(playwright.devices[name])
    options.pop('default_browser_type', None)
    return options


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class PageCase(unittest.TestCase):
    """A browser test whose ``setUp`` leaves ``self.browser``, ``self.playwright_manager``, ``self.server``, ``self.errors`` (page errors) and ``self.external`` (requests
    beyond the page's own origin) behind; the tearDown that closes them in that order and requires both lists to be empty is shared."""

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        self.server.shutdown()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])


class ControlsBrowserTests(unittest.TestCase):
    def test_generated_page_mount_and_binding_lifecycle(self):
        hostile = '</script><script>globalThis.pwned=true</script><img src="https://example.invalid/pixel">'
        sections = (('同名', 'first section'), ('同名', hostile))
        full = 'Full extract: ' + hostile
        automatic = section_browser(sections, id='automatic', full_text=full)
        manual = section_browser(sections, id='manual', full_text=full).replace(' data-ui-section-browser', '')
        document = render_document(trusted_html=automatic + manual,
                                   scripts=shared_scripts('.', names=('controls.js',)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text(document, encoding='utf-8')
            write_js(root)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                functools.partial(QuietHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        page = browser.new_page()
                        external, errors = [], []
                        page.on('request', lambda request: external.append(request.url)
                                if not request.url.startswith(origin + '/') else None)
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(origin + '/index.html')
                        select = page.locator('#automatic')
                        output = select.locator('..').locator('[data-ui-section-output]')
                        expect(select).to_be_enabled()
                        expect(output).to_have_text(full)
                        expect(select.locator('option')).to_have_count(3)
                        self.assertEqual(select.locator('option').all_text_contents(), ['(full extract)', '同名', '同名'])
                        select.select_option('0')
                        expect(output).to_have_text('first section')
                        select.select_option('1')
                        expect(output).to_have_text(hostile)
                        expect(output.locator('script, img')).to_have_count(0)
                        self.assertIsNone(page.evaluate('globalThis.pwned'))
                        select.select_option('')
                        expect(output).to_have_text(full)
                        page.evaluate('webUiControls.mount(document)')
                        expect(select.locator('option')).to_have_count(3)
                        # A separate generated panel tests the public controller
                        # without leaving an auto-mounted listener behind.
                        page.evaluate('''() => {
                            const select = document.querySelector('#manual');
                            const panel = select.closest('section');
                            const data = JSON.parse(panel.querySelector('[data-ui-section-data]').textContent);
                            globalThis.binding = webUiControls.bindSelect(select, panel.querySelector('[data-ui-section-output]'));
                            globalThis.testData = data;
                            binding.update(data.items, data.fullText, data.fullLabel);
                        }''')
                        manual_select = page.locator('#manual')
                        manual_output = manual_select.locator('..').locator('[data-ui-section-output]')
                        manual_select.select_option('1')
                        expect(manual_output).to_have_text(hostile)
                        page.evaluate('binding.clear()')
                        expect(manual_select).to_be_disabled()
                        expect(manual_select.locator('option')).to_have_count(1)
                        expect(manual_output).to_have_text('')
                        page.evaluate('binding.update(testData.items, testData.fullText); binding.destroy()')
                        manual_select.select_option('0')
                        expect(manual_output).to_have_text(full)
                        self.assertEqual(manual_select.input_value(), '0')
                        self.assertEqual(errors, [])
                        self.assertEqual(external, [])
                        # Progressive enhancement: no JS still exposes full text.
                        no_js = browser.new_context(java_script_enabled=False)
                        try:
                            fallback = no_js.new_page()
                            fallback.goto(origin + '/index.html')
                            expect(fallback.locator('#automatic')).to_be_disabled()
                            expect(fallback.locator('#automatic').locator('..').locator('[data-ui-section-output]')).to_have_text(full)
                        finally:
                            no_js.close()
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


class UiHelpersBrowserTests(unittest.TestCase):
    """js/ui.js helpers in real Chromium: theme switch, lit state, lightbox and the copy fallback."""

    PAGE = (
        '<select data-ui-theme-switch id="pick"><option>modern</option><option>github-like</option>'
        '<option>green</option></select>'
        '<ul data-ui-lightbox><li><a href="a.png"><img src="a.png" alt="Alpha" width="64"></a></li>'
        '<li><a href="b.png"><img src="b.png" alt="Beta" width="64"></a></li></ul>'
        '<div class="ui-card" id="far" style="margin-top:3000px">far</div>'
        '<script type="module">import{bindTheme,observeLit,bindLightbox,copyText}from"./js/ui.js";'
        'globalThis.ui={bindTheme,observeLit,bindLightbox,copyText};bindTheme();bindLightbox();observeLit(".ui-card")'
        '</script>'
    )

    def test_theme_lit_lightbox_and_copy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text(render_document(trusted_html=self.PAGE, css=bundled_css()), encoding='utf-8')
            write_js(root)
            shutil.copyfile(ROOT / 'docs/brand/icon.png', root / 'a.png')
            shutil.copyfile(ROOT / 'docs/brand/favicon.png', root / 'b.png')
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        page = browser.new_page(viewport={'width': 800, 'height': 600})
                        errors, external = [], []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda r: external.append(r.url) if not r.url.startswith(origin + '/') else None)
                        page.goto(origin + '/index.html')
                        body = page.locator('body')
                        background = lambda: page.evaluate('getComputedStyle(document.body).backgroundColor')
                        # Theme: one stylesheet holds every theme, so the switch needs no reload; the choice is remembered.
                        expect(body).to_have_attribute('data-ui-theme', 'modern')
                        self.assertEqual(background(), 'rgb(13, 17, 23)')
                        page.select_option('#pick', 'green')
                        expect(body).to_have_attribute('data-ui-theme', 'green')
                        self.assertEqual(background(), 'rgb(237, 240, 236)')
                        page.reload()
                        expect(body).to_have_attribute('data-ui-theme', 'green')
                        self.assertEqual(page.input_value('#pick'), 'green')
                        # Lit: only what is on screen is marked, and the mark follows scrolling.
                        far = page.locator('#far')
                        expect(far).not_to_have_attribute('data-lit', '')
                        far.scroll_into_view_if_needed()
                        expect(far).to_have_attribute('data-lit', '')
                        page.evaluate('window.scrollTo(0, 0)')
                        expect(far).not_to_have_attribute('data-lit', '')
                        # Lightbox: opens, steps by key and by swipe, shuts on Escape, and locks page scroll while open.
                        dialog = page.locator('dialog.ui-lightbox')
                        expect(dialog).to_be_hidden()
                        page.click('[data-ui-lightbox] a >> nth=0')
                        expect(dialog).to_be_visible()
                        shown = lambda: page.evaluate('document.querySelector("dialog.ui-lightbox img").src.split("/").pop()')
                        self.assertEqual(shown(), 'a.png')
                        self.assertEqual(page.evaluate('getComputedStyle(document.body).overflow'), 'hidden')
                        page.keyboard.press('ArrowRight')
                        self.assertEqual(shown(), 'b.png')
                        box = dialog.bounding_box()
                        y = box['y'] + box['height'] / 2
                        page.mouse.move(box['x'] + 200, y)
                        page.mouse.down()
                        page.mouse.move(box['x'] + 100, y)
                        page.mouse.up()
                        self.assertEqual(shown(), 'a.png')
                        page.keyboard.press('Escape')
                        expect(dialog).to_be_hidden()
                        # Copy: without the async clipboard the hidden-textarea path runs and cleans up.
                        copied = page.evaluate('''async () => {
                            Object.defineProperty(navigator, "clipboard", {value: undefined});
                            document.execCommand = () => { globalThis.sent = document.activeElement.value; return true };
                            await ui.copyText("x<y&z");
                            return [globalThis.sent, document.querySelectorAll("textarea").length];
                        }''')
                        failures = page.evaluate("""async () => {
                            const results = [];
                            for (const exec of [undefined, () => false, () => {throw Error('disabled')}]) {
                                document.execCommand = exec;
                                let rejected = false;
                                try { await ui.copyText('failure') } catch { rejected = true }
                                results.push([rejected, document.querySelectorAll('textarea').length]);
                            }
                            return results;
                        }""")
                        self.assertEqual(failures, [[True, 0]] * 3)
                        self.assertEqual(copied, ['x<y&z', 0])
                        self.assertEqual(errors, [])
                        self.assertEqual(external, [])
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


class WorldBrowserTests(unittest.TestCase):
    """The world engine in real Chromium: scroll shots, map camera, sheet, no-JS fallback, and the random theme wall."""

    @staticmethod
    def serve(pages):
        directory = tempfile.mkdtemp()
        for name, html in pages.items():
            (Path(directory) / name).write_text(html, encoding='utf-8')
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=directory))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f'http://127.0.0.1:{server.server_port}'

    def test_shots_map_sheet_and_fallback(self):
        import json
        from web_ui import example_data
        spec = example_data('world')
        server, origin = self.serve({'index.html': world_document(spec, theme='github-like')})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 900})
                    errors, external = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda r: external.append(r.url) if not r.url.startswith(origin + '/') else None)
                    page.goto(origin + '/index.html')
                    # Shots: scrolling the box lights one mark, and CSS shows that shot on that shot's color.
                    scroller = page.locator('.ui-shots-scroll')
                    height = scroller.evaluate('el => el.clientHeight')
                    expect(page.locator('.ui-shot-mark[data-i="0"]')).to_have_attribute('data-lit', '')
                    scroller.evaluate(f'el => el.scrollTop = {height * 2}')
                    expect(page.locator('.ui-shot-mark[data-i="2"]')).to_have_attribute('data-lit', '')
                    expect(page.locator('.ui-shot[data-i="2"]')).to_have_css('opacity', '1')
                    expect(page.locator('.ui-shot[data-i="0"]')).to_have_css('opacity', '0')
                    expect(page.locator('.ui-shots-stage')).to_have_css('background-color', 'rgb(90, 42, 26)')
                    # Map: Python's camera arithmetic and the JS agree on every case.
                    cases = [(10, 10, 2, 960, 640, 400, 300), (950, 630, 2, 960, 640, 400, 300),
                             (0, 0, 0.25, 960, 640, 400, 300), (480, 320, 1, 960, 640, 390, 844), (5, 900, 3, 960, 640, 390, 844)]
                    got = page.evaluate('cases => cases.map(c => webUiWorld.clampFocus(...c))', cases)
                    for case, result in zip(cases, got):
                        self.assertEqual(result, list(clamp_focus(*case)), case)
                    self.assertAlmostEqual(page.evaluate('webUiWorld.fitZoom(960, 640, 390, 844)'), fit_zoom(960, 640, 390, 844))
                    world = page.locator('#demo-map')
                    view = world.locator('.ui-world-view')
                    expect(world).to_have_attribute('data-js', '')
                    expect(world.locator('.ui-floor[data-floor="1f"]')).to_be_visible()
                    expect(world.locator('.ui-floor[data-floor="2f"]')).to_be_hidden()
                    cam = world.locator('.ui-world-cam')
                    z0 = float(cam.evaluate('el => el.style.getPropertyValue("--z")'))
                    world.locator('.ui-world-view').hover()
                    page.mouse.wheel(0, -300)
                    page.wait_for_function('z => parseFloat(document.querySelector("#demo-map .ui-world-cam").style.getPropertyValue("--z")) > z', arg=z0)
                    box = view.bounding_box()
                    fx0 = float(cam.evaluate('el => el.style.getPropertyValue("--fx")'))
                    page.mouse.move(box['x'] + 300, box['y'] + 150)
                    page.mouse.down()
                    page.mouse.move(box['x'] + 200, box['y'] + 150, steps=5)
                    page.mouse.up()
                    self.assertGreater(float(cam.evaluate('el => el.style.getPropertyValue("--fx")')), fx0)   # dragged left, camera moved right
                    # Categories and floors switch by CSS alone (radios).
                    world.locator('label[data-cat="food"]').click()
                    expect(world.locator('.ui-spot[data-category="info"]').first).to_be_hidden()
                    expect(world.locator('.ui-spot[data-category="food"]').first).to_be_visible()
                    world.locator('label[data-cat=""]').click()
                    world.locator('label[for="demo-floor-2f"]').click()
                    expect(world.locator('.ui-floor[data-floor="2f"]')).to_be_visible()
                    expect(world.locator('.ui-floor[data-floor="1f"]')).to_be_hidden()
                    # Spot -> sheet -> Escape; the camera moves to the spot, the URL gains a hash, the page does not change.
                    world.locator('label[for="demo-floor-1f"]').click()
                    world.locator('.ui-spot', has_text='Hall').click()
                    sheet = world.locator('#demo-spot-hall')
                    expect(sheet).to_be_visible()
                    self.assertTrue(page.url.endswith('#demo-spot-hall'))
                    self.assertGreaterEqual(float(cam.evaluate('el => el.style.getPropertyValue("--z")')), 2)
                    page.keyboard.press('Escape')
                    expect(sheet).to_be_hidden()
                    # Deep link: a fresh load with a hash opens that spot (here a spot on the other floor).
                    page.goto(origin + '/index.html#demo-spot-lab')
                    expect(page.locator('#demo-spot-lab')).to_be_visible()
                    expect(page.locator('.ui-floor[data-floor="2f"]')).to_be_visible()
                    self.assertEqual(errors, [])
                    self.assertEqual(external, [])
                    # Without JavaScript the sheet still opens through :target and scrolling still works.
                    no_js = browser.new_context(java_script_enabled=False)
                    try:
                        plain = no_js.new_page()
                        plain.goto(origin + '/index.html#demo-spot-gate')
                        expect(plain.locator('#demo-spot-gate')).to_be_visible()
                        expect(plain.locator('.ui-shot[data-i="3"]')).to_be_visible()
                    finally:
                        no_js.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_world_interrupted_repeated_and_history_flows(self):
        import json
        from web_ui import example_data
        spec = example_data('world')
        spec['floors'][0]['spots'][0]['category'] = 'all'
        server, origin = self.serve({'index.html': world_document(spec)})
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 900})
                    page.goto(origin + '/index.html#demo-spot-lab')
                    world = page.locator('#demo-map')
                    sheet = page.locator('#demo-spot-lab')
                    expect(sheet).to_be_visible()
                    world.locator('.ui-world-view').focus()
                    page.keyboard.press('Escape')
                    expect(sheet).to_be_hidden()
                    self.assertEqual(page.evaluate('location.hash'), '')
                    page.goto(origin + '/index.html#demo-spot-lab')
                    sheet.locator('.ui-sheet-close').click()
                    expect(sheet).to_be_hidden()
                    self.assertEqual(page.evaluate('location.hash'), '')
                    # A category named all is distinct from the unfiltered choice.
                    world.locator('label[for="demo-floor-1f"]').click()
                    world.locator('label[data-cat="all"]').click()
                    expect(world.locator('.ui-spot', has_text='Gate')).to_be_visible()
                    expect(world.locator('.ui-spot', has_text='Hall')).to_be_hidden()
                    world.locator('label[data-cat=""]').click()
                    expect(world.locator('.ui-spot', has_text='Hall')).to_be_visible()
                    # Rebinding must not double the wheel handler.
                    page.evaluate('webUiWorld.bindWorlds(); webUiWorld.bindWorlds()')
                    view = world.locator('.ui-world-view')
                    z = view.evaluate('e => parseFloat(e.firstElementChild.style.getPropertyValue("--z"))')
                    view.dispatch_event('wheel', {'deltaY': -100})
                    z1 = view.evaluate('e => parseFloat(e.firstElementChild.style.getPropertyValue("--z"))')
                    self.assertAlmostEqual(z1, z * 1.1)
                    # Interrupted pointers clear drag state; keyboard activation still works.
                    for event in ('pointercancel', 'lostpointercapture'):
                        view.dispatch_event('pointerdown', {'pointerId': 11, 'button': 0, 'clientX': 100, 'clientY': 100})
                        view.dispatch_event(event, {'pointerId': 11})
                        expect(world).not_to_have_attribute('data-drag', '')
                    # A real completed drag must not poison subsequent keyboard activation.
                    box = view.bounding_box()
                    page.mouse.move(box['x'] + 200, box['y'] + 150)
                    page.mouse.down()
                    page.mouse.move(box['x'] + 150, box['y'] + 150, steps=4)
                    page.mouse.up()
                    expect(world).not_to_have_attribute('data-drag', '')
                    hall = world.locator('.ui-spot', has_text='Hall')
                    hall.dispatch_event('click', {'detail': 1})
                    expect(page.locator('#demo-spot-hall')).to_be_hidden()
                    self.assertEqual(page.evaluate('location.hash'), '')
                    hall.focus(); page.keyboard.press('Enter')
                    expect(page.locator('#demo-spot-hall')).to_be_visible()
                    # Hash navigation resets a conflicting filter and restores both directions.
                    world.locator('label[data-cat="food"]').click()
                    page.evaluate('location.hash = "demo-spot-lab"')
                    expect(sheet).to_be_visible()
                    expect(world.locator('.ui-spot', has_text='Lab')).to_be_visible()
                    page.go_back()
                    expect(page.locator('#demo-spot-hall')).to_be_visible()
                    expect(sheet).to_be_hidden()
                    page.go_forward()
                    expect(sheet).to_be_visible()
                    expect(page.locator('#demo-spot-hall')).to_be_hidden()
                finally:
                    browser.close()
        finally:
            server.shutdown(); server.server_close()

    def test_board_follows_the_viewers_time_zone_and_shows_only_the_offset(self):
        import datetime
        from web_ui import example_data
        spec = example_data('world')
        spec['board']['zones'] = []                                         # authored zone labels are the page's own words; here only the viewer's clock is shown
        spec['board']['items'] = [i for i in spec['board']['items'] if not i.get('zone')]
        server, origin = self.serve({'index.html': world_document(spec)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    # 2026-11-03 10:00 UTC seen from five places: the clock, the gauges and the stamp all use the viewer's local minutes.
                    for zone, offset in (('UTC', 0), ('Asia/Tokyo', 540), ('Asia/Kolkata', 330), ('America/New_York', -300), ('Pacific/Chatham', 825)):
                        with self.subTest(zone=zone):
                            context = browser.new_context(viewport={'width': 800, 'height': 900}, timezone_id=zone)
                            page = context.new_page()
                            page.clock.set_fixed_time(datetime.datetime(2026, 11, 3, 10, 0, tzinfo=datetime.timezone.utc))
                            page.goto(origin + '/index.html')
                            local = (600 + offset) % 1440
                            expect(page.locator('[data-clock]')).to_have_text(f'{clock_label(local)} {utc_offset_label(offset)}')
                            filled, percent, _ = gauge_state(local, 540, 1080, 10)
                            first = page.locator('.ui-board-run .ui-board-gauge').first
                            self.assertEqual(first.locator('.ui-board-cells').text_content(), gauge_cells(filled, 10, ('⌛', '⏳')))
                            self.assertEqual(first.locator('.ui-board-pct').text_content(), f'{percent}%')
                            page.locator('.ui-board-post input').fill('hi')
                            page.locator('.ui-board-post input').press('Enter')
                            self.assertEqual(page.locator('.ui-board-note .ui-board-stamp').first.text_content(), clock_label(local))
                            board_text = page.locator('.ui-board').inner_text()                  # an offset, never a place name
                            for place in zone.split('/')[1:]:
                                self.assertNotIn(place.replace('_', ' '), board_text)
                            self.assertNotIn('/', board_text)
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_board_zone_clocks_and_items_follow_the_tz_database_not_the_viewer(self):
        import datetime
        import random
        from web_ui import example_data
        spec = example_data('world')
        spec['board']['items'].append({'text': 'Tokyo hours', 'gauge': {'from': '09:00', 'to': '18:00', 'cells': 10}, 'zone': 'tokyo'})
        server, origin = self.serve({'index.html': world_document(spec)})
        utc = lambda *a: datetime.datetime(*a, tzinfo=datetime.timezone.utc)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    # The page's lookup agrees with Python's: every change to the second, and thousands of seeded instants.
                    rng = random.Random(20261103)
                    for tz in ('Europe/London', 'America/New_York', 'Australia/Sydney', 'Asia/Kolkata', 'Pacific/Auckland'):
                        rows = list(zone_rows(tz))
                        instants = [t + d for t in rows[2::2] for d in (-1, 0, 1)] + [rng.randrange(1_500_000_000, 2_300_000_000) for _ in range(2000)] + [0, 4_000_000_000]
                        page = browser.new_page()
                        page.goto(origin + '/index.html')
                        got = page.evaluate('([rows, ts]) => ts.map(t => webUiWorld.zoneOffset(rows, t))', [rows, instants])
                        self.assertEqual(got, [zone_offset(rows, t) for t in instants], tz)
                        page.close()
                    # Either side of a change, seen by a viewer in New York: London's clock jumps, New York repeats an hour.
                    cases = [(utc(2026, 3, 29, 0, 59), {'tokyo': '09:59', 'london': '00:59', 'ny': '20:59'}),
                             (utc(2026, 3, 29, 1, 0), {'tokyo': '10:00', 'london': '02:00', 'ny': '21:00'}),
                             (utc(2026, 11, 1, 5, 59), {'tokyo': '14:59', 'london': '05:59', 'ny': '01:59'}),
                             (utc(2026, 11, 1, 6, 0), {'tokyo': '15:00', 'london': '06:00', 'ny': '01:00'})]
                    for moment, expected in cases:
                        with self.subTest(moment=moment.isoformat()):
                            context = browser.new_context(viewport={'width': 800, 'height': 900}, timezone_id='America/New_York')
                            page = context.new_page()
                            page.clock.set_fixed_time(moment)
                            page.goto(origin + '/index.html')
                            shown = {z: page.locator(f'[data-zone-id="{z}"] [data-zone-clock]').text_content() for z in expected}
                            self.assertEqual(shown, expected)
                            for z, tz in (('tokyo', 'Asia/Tokyo'), ('london', 'Europe/London'), ('ny', 'America/New_York')):    # and Python says the same
                                self.assertEqual(shown[z], board_clock(moment.timestamp(), zone_offset(zone_rows(tz), moment.timestamp()))['clock'])
                            context.close()
                    # Items with a zone count in that zone's local time (London lunch 12:00, Tokyo hours 09:00..18:00); the others use the viewer's.
                    context = browser.new_context(viewport={'width': 800, 'height': 900}, timezone_id='America/New_York')
                    page = context.new_page()
                    page.clock.set_fixed_time(utc(2026, 11, 3, 1, 0))                       # Tokyo 10:00, London 01:00, viewer 20:00 the day before
                    page.goto(origin + '/index.html')
                    texts = page.locator('.ui-board-run [data-at]').all_text_contents()
                    viewer, london = 20 * 60, 60
                    expected = [f'あと{minutes_until(viewer, h * 60 + m)}分' for h, m in ((10, 30), (14, 0), (17, 30))] + [f'あと{minutes_until(london, 12 * 60)}分']
                    self.assertEqual(texts, expected * 2)
                    last = page.locator('.ui-board-run .ui-board-gauge').last
                    filled, percent, _ = gauge_state(10 * 60, 540, 1080, 10)
                    self.assertEqual((last.locator('.ui-board-cells').text_content(), last.locator('.ui-board-pct').text_content()), (gauge_cells(filled, 10, ('⌛', '⏳')), f'{percent}%'))
                    self.assertEqual(percent, 11)
                    context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_board_line_stays_readable_on_a_phone(self):
        from web_ui import example_data
        spec = example_data('world')
        spec['board']['items'].append({'text': 'emoji', 'gauge': {'from': '09:00', 'to': '18:00',
                                      'cells': 20, 'glyphs': ['👩\u200d💻', 'ABCDEFGH']}})
        server, origin = self.serve({'index.html': world_document(spec)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for width in (320, 390, 800):
                        with self.subTest(width=width):
                            page = browser.new_page(viewport={'width': width, 'height': 700})
                            page.goto(origin + '/index.html')
                            self.assertEqual(page.locator('.ui-board-gauge[data-todo=\"ABCDEFGH\"]').count(), 2)
                            track, board = page.locator('.ui-board-track').bounding_box(), page.locator('.ui-board').bounding_box()
                            self.assertGreater(track['width'], 200)                                 # the scrolling line is not squeezed away
                            self.assertLessEqual(track['x'] + track['width'], board['x'] + board['width'] + 1)
                            form = page.locator('.ui-board-post').bounding_box()
                            self.assertLessEqual(form['x'] + form['width'], board['x'] + board['width'] + 1)
                            page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_board_keeps_nothing_and_sends_nothing(self):
        from web_ui import example_data
        spec = example_data('world')
        server, origin = self.serve({'index.html': world_document(spec)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 900})
                    requests = []
                    page.goto(origin + '/index.html')
                    page.on('request', lambda request: requests.append(request.url))
                    before = page.evaluate('performance.getEntriesByType("resource").length')
                    form = page.locator('.ui-board-post input')
                    for text in ('meet at the gate 14:00', 'second line', '\U0001f9d1\u200d\U0001f33e hi'):
                        form.fill(text)
                        form.press('Enter')
                    self.assertEqual(page.locator('.ui-board-note').count(), 6)
                    page.wait_for_timeout(400)
                    # No storage of any kind, no cookie, no cache, no database, and not one request after the page loaded.
                    state = page.evaluate("""async () => ({
                        local: localStorage.length, session: sessionStorage.length, cookie: document.cookie,
                        databases: (await indexedDB.databases()).length, caches: (await caches.keys()).length,
                        resources: performance.getEntriesByType('resource').length})""")
                    self.assertEqual(state, {'local': 0, 'session': 0, 'cookie': '', 'databases': 0, 'caches': 0, 'resources': before})
                    self.assertEqual(requests, [])
                    # Reload: everything a visitor wrote is gone, the board is back to what the page was built with.
                    page.reload()
                    self.assertEqual(page.locator('.ui-board-note').count(), 0)
                    self.assertEqual(page.evaluate('localStorage.length + sessionStorage.length'), 0)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_villagers_player_board_clock_and_visitor_lines(self):
        import datetime
        from web_ui import example_data
        spec = example_data('world')
        server, origin = self.serve({'index.html': world_document(spec)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    context = browser.new_context(viewport={'width': 800, 'height': 900}, timezone_id='UTC')
                    page = context.new_page()
                    page.clock.set_fixed_time(datetime.datetime(2026, 11, 3, 10, 0, tzinfo=datetime.timezone.utc))
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/index.html')
                    # Villagers: a CSS animation per actor, and they really move (straight, constant speed is checked in Python).
                    cat = page.locator('#demo-actor-cat')
                    self.assertNotEqual(cat.evaluate('el => getComputedStyle(el).animationName'), 'none')
                    first = cat.bounding_box()
                    page.wait_for_timeout(900)
                    second = cat.bounding_box()
                    self.assertTrue(abs(first['x'] - second['x']) + abs(first['y'] - second['y']) > 1, (first, second))
                    # Touching a villager shows what it says; the map keeps its camera.
                    cat.dispatch_event('click')
                    expect(page.locator('#demo-spot-cat')).to_be_visible()
                    page.keyboard.press('Escape')
                    # The player walks to a tapped spot at constant speed: Python's travel time is what the page uses.
                    page.locator('.ui-spot', has_text='Hall').click()
                    player = page.locator('.ui-player')
                    expect(player).to_have_attribute('data-speed', '96')
                    walk = float(player.evaluate('el => el.style.getPropertyValue("--walk")').rstrip('s'))
                    self.assertAlmostEqual(walk, travel_seconds(120, 320, 480, 320, 96), places=6)
                    self.assertEqual(player.get_attribute('data-target-x'), '480')
                    # Board: the clock and "in N min" come from the page's clock, by the same rule as Python.
                    expect(page.locator('[data-clock]')).to_have_text('10:00 UTC')
                    texts = page.locator('.ui-board-run [data-at]').all_text_contents()
                    expected = [f'あと{minutes_until(600, h * 60 + m)}分' for h, m in ((10, 30), (14, 0), (17, 30), (12, 0))] * 2   # the last one follows London (GMT in November)
                    self.assertEqual(texts, expected)
                    cases = [(600, 630), (600, 600), (1430, 10), (0, 1439)]
                    self.assertEqual(page.evaluate('cases => cases.map(c => webUiWorld.minutesUntil(...c))', cases), [minutes_until(*c) for c in cases])
                    self.assertEqual(page.evaluate('[1, 64, 160, 400].map(n => webUiWorld.boardSeconds(n))'), [board_seconds(n) for n in (1, 64, 160, 400)])
                    # Gauges: the same integer rule as Python, for the demo's two glyph sets (visible line and its aria-hidden twin).
                    gauges = page.locator('.ui-board-run .ui-board-gauge')
                    self.assertEqual(gauges.count(), 4)
                    for index, ((start, end, cells, glyphs)) in enumerate([(540, 1080, 10, ('⌛', '⏳')), (360, 1320, 8, ('🌕', '🌑'))] * 2):
                        filled, percent, phase = gauge_state(600, start, end, cells)
                        self.assertEqual(phase, 'active')
                        self.assertEqual(gauges.nth(index).locator('.ui-board-cells').text_content(), gauge_cells(filled, cells, glyphs))
                        self.assertEqual(gauges.nth(index).locator('.ui-board-pct').text_content(), f'{percent}%')
                    windows = [(540, 1080, 10), (1320, 120, 8), (0, 1439, 20), (1439, 0, 3), (360, 1320, 8)]
                    cases = [[now, start, end, cells] for start, end, cells in windows for now in range(1440)]
                    self.assertEqual(page.evaluate('cases => cases.map(c => webUiWorld.gaugeState(...c))', cases),
                                     [list(gauge_state(*c)) for c in cases])
                    self.assertEqual(page.evaluate('() => [0, 1, 9, 600, 1439].map(m => webUiWorld.clockLabel(m))'), [clock_label(m) for m in (0, 1, 9, 600, 1439)])
                    offsets = [0, 540, 330, -300, -210, 765, -720, 60, -60]
                    self.assertEqual(page.evaluate('offsets => offsets.map(o => webUiWorld.utcOffsetLabel(o))', offsets), [utc_offset_label(o) for o in offsets])
                    self.assertEqual(page.evaluate('() => webUiWorld.gaugeCells(3, 5, "🔥", "🪵")'), gauge_cells(3, 5, ('🔥', '🪵')))
                    # Visitor lines: same cleaning as Python, shown as text, kept only on this page view.
                    lines = ['  hello   world  ', '<img src=x onerror=1>', 'x' * 100, '   ', '\U0001f9d1\u200d\U0001f33e hi']
                    self.assertEqual(page.evaluate('lines => lines.map(t => webUiWorld.cleanMessage(t))', lines), [clean_message(t) for t in lines])
                    form = page.locator('.ui-board-post')
                    for text in lines[:3]:
                        form.locator('input').fill(text)
                        form.locator('input').press('Enter')
                    form.locator('input').fill('   ')
                    form.locator('input').press('Enter')                                   # nothing to show: ignored
                    notes = page.locator('.ui-board-note').all_text_contents()
                    self.assertEqual(notes, [f'10:00 {clean_message(t)}' for t in reversed(lines[:3])] * 2)          # the stamp is the page's clock at posting
                    self.assertEqual(page.locator('.ui-board-note .ui-board-stamp').all_text_contents(), ['10:00'] * 6)
                    self.assertEqual(page.locator('.ui-board-run img').count(), 0)
                    self.assertEqual(page.evaluate('globalThis.pwned'), None)
                    page.reload()
                    self.assertEqual(page.locator('.ui-board-note').count(), 0)            # nothing is stored
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_board_posts_keep_two_bounded_identical_halves(self):
        from web_ui import example_data, board_seconds
        server, origin = self.serve({'index.html': world_document(example_data('world'))})
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(origin + '/index.html')
                    board = page.locator('.ui-board')
                    base = int(board.get_attribute('data-chars'))
                    for i in range(8):
                        board.locator('input[name="message"]').fill(f'{i}😀')
                        board.locator('button[type="submit"]').click()
                    halves = board.evaluate("""b => {const rows=[...b.querySelectorAll('.ui-board-item')].map(n=>{const c=n.cloneNode(true);c.querySelectorAll('.ui-board-stamp').forEach(s=>s.remove());return c.textContent.trim()});return [rows.slice(0,rows.length/2),rows.slice(rows.length/2)]}""")
                    self.assertEqual(halves[0], halves[1])
                    self.assertEqual(halves[0][:5], ['7😀', '6😀', '5😀', '4😀', '3😀'])
                    self.assertEqual(board.locator('.ui-board-note').count(), 10)
                    self.assertEqual(int(board.get_attribute('data-chars')), base + 40)
                    self.assertEqual(len(set(board.locator('.ui-board-note .ui-board-stamp').all_text_contents())), 1)   # each line carries its HH:MM stamp
                    expect(board.locator('.ui-board-run')).to_have_css('animation-duration', f'{board_seconds(base + 40):g}s')
                    page.reload()
                    self.assertEqual(page.locator('.ui-board-note').count(), 0)
                finally:
                    browser.close()
        finally:
            server.shutdown(); server.server_close()

    def test_random_theme_wall_reads_in_every_cell_without_overflow(self):
        server, origin = self.serve({'wall.html': theme_wall_document(24)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 390, 'height': 844})
                    page.goto(origin + '/wall.html')
                    rows = page.evaluate('''() => [...document.querySelectorAll(".ui-wall-cell")].map(cell => {
                        const css = getComputedStyle(cell), muted = getComputedStyle(cell.querySelector(".ui-muted"));
                        const hex = c => "#" + c.match(/\\d+/g).slice(0, 3).map(n => (+n).toString(16).padStart(2, "0")).join("");
                        return {bg: hex(css.backgroundColor), fg: hex(css.color), muted: hex(muted.color), seed: cell.dataset.seed};
                    })''')
                    self.assertEqual(len(rows), 24)
                    for row in rows:
                        self.assertGreaterEqual(contrast_ratio(row['fg'], row['bg']), 7, row)
                        self.assertGreaterEqual(contrast_ratio(row['muted'], row['bg']), 4.5, row)
                    self.assertEqual(len({row['bg'] for row in rows}) > 18, True)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class StubBrowserTests(unittest.TestCase):
    """Generated stub pages in Chromium: the mock answers exactly what Python's stub_response says."""

    def test_mock_stubs_answer_like_python_on_their_own_page_and_on_the_front_page(self):
        import json
        from web_ui import stub_document
        pages = {'mcp.html': stub_document(EXAMPLE_STUBS['mcp']), 'api.html': stub_document(EXAMPLE_STUBS['api']),
                 'index.html': (ROOT / 'index.html').read_text(encoding='utf-8')}
        server, origin = WorldBrowserTests.serve(pages)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for name, ids in (('mcp.html', ['mcp']), ('api.html', ['api']), ('index.html', ['mcp', 'api'])):
                        page = browser.new_page(viewport={'width': 800, 'height': 900})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'{origin}/{name}')
                        for sid in ids:
                            for query in ('tools/list', 'a$&b <x> "q"'):
                                page.fill(f'#{sid}-query', query)
                                page.click(f'#{sid}-run')
                                expected = json.dumps(stub_response(EXAMPLE_STUBS[sid]['mock'], query), indent=2, ensure_ascii=False)
                                expect(page.locator(f'#{sid}-output')).to_have_text(expected)
                            self.assertEqual(page.locator(f'#{sid}-output').evaluate('el => el.children.length'), 0)  # text, never HTML
                        self.assertEqual(errors, [], name)
                        page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


    def test_curl_in_the_page_reads_exactly_like_python_and_masks_credentials(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import CURL_CASES, curl_fuzz_inputs
        from web_ui import mask_curl, parse_curl
        server, origin = WorldBrowserTests.serve({'index.html': (ROOT / 'index.html').read_text(encoding='utf-8')})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    requests = []
                    page.goto(origin + '/index.html')
                    page.on('request', lambda request: requests.append(request.url))
                    # The flutter editor's 47 golden cases, then 1500 seeded inputs (odd whitespace, bad escapes, shell characters ...):
                    # the page's answer equals Python's, errors included.
                    golden = [case['input'] for case in CURL_CASES]
                    got = page.evaluate('inputs => inputs.map(t => webUiCurl.parseCurl(t))', golden)
                    self.assertEqual(got, [case['expected'] for case in CURL_CASES])
                    fuzz = curl_fuzz_inputs()
                    got = page.evaluate('inputs => inputs.map(t => webUiCurl.parseCurl(t))', fuzz)
                    for text, result in zip(fuzz, got):
                        self.assertEqual(result, parse_curl(text), repr(text))
                    masked = page.evaluate('inputs => inputs.map(t => webUiCurl.maskCurl(webUiCurl.parseCurl(t)))', fuzz[:300])
                    self.assertEqual(masked, [mask_curl(parse_curl(t)) for t in fuzz[:300]])
                    # Limits and unusual text agree as well.
                    edge = ['curl http://x/' + 'a' * 65522, 'curl http://x/' + 'a' * 65523, 'curl http://x/' + '\u3042' * 65536, 'curl http://x/\u0000',
                            'curl http://x/\ud800', 'curl ' + ' '.join(['-s'] * 4095) + ' http://x', 'curl ' + ' '.join(['-s'] * 4096) + ' http://x',
                            '\u0085curl\u0085http://x\u0085', '\ufeffcurl http://x', 'curl http://x -d a=%F0%9F%98%80&b=%ED%A0%80', 'curl -G -d "a=%E3%81" http://x',
                            'curl http://x -H "X-Api-Key:"', 'curl -H "constructor: 1" -H "__proto__: 2" http://x']
                    got = page.evaluate('inputs => inputs.map(t => webUiCurl.parseCurl(t))', edge)
                    self.assertEqual(got, [parse_curl(t) for t in edge])
                    # The card on the front page: typing parses live, credentials are shown as ***, and nothing is sent.
                    box = page.locator('[data-ui-curl]')
                    out = box.locator('[data-curl-output]')
                    self.assertIn('"method": "POST"', out.text_content())
                    self.assertIn('"bodyMode": "json"', out.text_content())
                    self.assertNotIn('Bearer abc', out.text_content())
                    self.assertIn('"value": "***"', out.text_content())
                    box.locator('[data-curl-input]').fill("curl -u me:pw 'http://x/?a=1' | sh")
                    self.assertIn('httpDraft.curl.error.shellMeta', out.text_content())
                    self.assertNotIn('me:pw', out.text_content())
                    box.locator('[data-curl-input]').fill('curl -H "X-Token: s3cr3t" -d "a=1" http://x/')
                    box.locator('[data-curl-run]').click()
                    self.assertNotIn('s3cr3t', out.text_content())
                    self.assertEqual(requests, [])
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class GeneratedSiteBrowserTests(unittest.TestCase):
    def test_generated_front_page_works_offline_without_external_modules(self):
        from web_ui import write_site
        with tempfile.TemporaryDirectory() as directory:
            write_site(directory)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto((Path(directory) / 'index.html').as_uri())
                    page.check('input[name="ui-theme"][value="green"]')
                    expect(page.locator('body')).to_have_attribute('data-ui-theme', 'green')
                    page.fill('#api-query', '/local/offline')
                    page.click('#api-run')
                    expect(page.locator('#api-output')).to_contain_text('/local/offline')
                    self.assertTrue(page.locator('img').first.evaluate('e => e.complete && e.naturalWidth > 0'))
                    self.assertEqual(errors, [])
                finally:
                    browser.close()


class CatalogBrowserTests(unittest.TestCase):
    """The same data adapter works at project subpaths and with JavaScript off."""

    def test_catalog_native_navigation_and_disclosure(self):
        from web_ui import catalog_document, example_data
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('catalog-report', 'catalog-projects'):
                output = root / 'project' / name
                output.mkdir(parents=True)
                spec = example_data(name)
                spec['items'][0]['links'] = [{'label': 'Local evidence', 'href': './evidence.txt'}]
                (output / 'index.html').write_text(catalog_document(spec), encoding='utf-8')
                (output / 'evidence.txt').write_text('fixture evidence', encoding='utf-8')
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                functools.partial(QuietHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        for name in ('catalog-report', 'catalog-projects'):
                            for width in (390, 1440):
                                for transport in ('file', 'http'):
                                    with self.subTest(name=name, width=width, transport=transport):
                                        context = browser.new_context(java_script_enabled=False,
                                                                      viewport={'width': width, 'height': 844})
                                        try:
                                            page = context.new_page()
                                            errors, external = [], []
                                            page.on('pageerror', lambda error: errors.append(str(error)))
                                            page.on('request', lambda request: external.append(request.url)
                                                    if not request.url.startswith((origin + '/', 'file://')) else None)
                                            path = f'/project/{name}/index.html'
                                            url = (root / path.lstrip('/')).as_uri() if transport == 'file' else origin + path
                                            page.goto(url)
                                            expect(page.locator('article')).to_have_count(2)
                                            expect(page.locator('script')).to_have_count(0)
                                            nav = page.locator('nav a')
                                            nav.nth(0).click()
                                            first = page.url
                                            nav.nth(1).click()
                                            second = page.url
                                            self.assertNotEqual(first, second)
                                            page.go_back()
                                            self.assertEqual(page.url, first)
                                            page.go_forward()
                                            self.assertEqual(page.url, second)
                                            nav.nth(0).click()
                                            summary = page.locator('summary').first
                                            disclosure = page.locator('details').first
                                            summary.focus()
                                            page.keyboard.press('Enter')
                                            expect(disclosure).to_have_attribute('open', '')
                                            page.keyboard.press('Enter')
                                            expect(disclosure).not_to_have_attribute('open', '')
                                            summary.click()
                                            expect(disclosure).to_have_attribute('open', '')
                                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                                            evidence = Path('build/gradio-dom')
                                            evidence.mkdir(parents=True, exist_ok=True)
                                            if transport == 'http':
                                                page.screenshot(path=str(evidence / f'{name}-{width}.png'), full_page=True)
                                            page.get_by_role('link', name='Local evidence', exact=True).click()
                                            self.assertTrue(page.url.endswith('/project/' + name + '/evidence.txt'))
                                            self.assertIn('fixture evidence', page.locator('body').inner_text())
                                            self.assertEqual(errors, [])
                                            self.assertEqual(external, [])
                                        finally:
                                            context.close()
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


class ShowcaseBrowserTests(unittest.TestCase):
    """The app shell in Chromium: sections switch with no reload, the rail gives way to the bottom bar, nothing overflows, every theme reads."""

    def pages(self):
        from web_ui import example_data
        return WorldBrowserTests.serve({'showcase.html': showcase_document(example_data('showcase'))})

    def test_sections_switch_by_rail_bottom_bar_and_keyboard_without_a_reload(self):
        server, origin = self.pages()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 800})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/showcase.html')
                    page.evaluate('window.stay = 1')                                       # survives only if the page is never reloaded
                    visible = lambda: [s.get_attribute('data-section') for s in page.locator('.ui-shell-section').all() if s.is_visible()]
                    self.assertEqual(visible(), ['overview'])
                    expect(page.locator('.ui-rail')).to_be_visible()
                    expect(page.locator('.ui-bottom-nav')).to_be_hidden()
                    self.assertEqual(page.locator('.ui-rail').bounding_box()['width'], 256)    # wide: the full rail, labels shown
                    page.locator('.ui-rail label', has_text='Data').click()
                    self.assertEqual(visible(), ['data'])
                    expect(page.locator('.ui-shell-table')).to_be_visible()
                    # Keyboard: the radios are one group, so the arrow keys move between sections.
                    page.locator('#showcase-sec-data').focus()
                    page.keyboard.press('ArrowRight')
                    self.assertEqual(visible(), ['media'])
                    page.keyboard.press('ArrowLeft'); page.keyboard.press('ArrowLeft')
                    self.assertEqual(visible(), ['components'])
                    # The selected control is drawn selected (and only that one), in the rail and in the bottom bar.
                    selected = page.evaluate("""() => [...document.querySelectorAll('.ui-rail label')].map(l => getComputedStyle(l).backgroundColor !== 'rgba(0, 0, 0, 0)')""")
                    self.assertEqual(selected, [False, True, False, False])
                    # 80 px rail between 900 and 1199: labels stay for screen readers but are not drawn.
                    page.set_viewport_size({'width': 1000, 'height': 800})
                    self.assertEqual(page.locator('.ui-rail').bounding_box()['width'], 80)
                    label = page.locator('.ui-rail .ui-rail-label').first
                    self.assertLessEqual(label.bounding_box()['width'], 1)
                    self.assertEqual(label.text_content(), 'Overview')
                    # Narrow: the bottom bar replaces the rail and chooses the same sections.
                    page.set_viewport_size({'width': 390, 'height': 800})
                    expect(page.locator('.ui-rail')).to_be_hidden()
                    expect(page.locator('.ui-bottom-nav')).to_be_visible()
                    page.locator('.ui-bottom-nav label', has_text='Media').click()
                    self.assertEqual(visible(), ['media'])
                    page.locator('.ui-bottom-nav label', has_text='Overview').click()
                    self.assertEqual(visible(), ['overview'])
                    self.assertEqual(page.evaluate('window.stay'), 1)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_favorite_is_memory_only_and_the_theme_list_works(self):
        server, origin = self.pages()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 800})
                    page.goto(origin + '/showcase.html')
                    star = page.locator('[data-ui-toggle]')
                    self.assertEqual((star.get_attribute('aria-pressed'), star.get_attribute('aria-label')), ('false', 'Favorite this page'))
                    star.click()
                    self.assertEqual((star.get_attribute('aria-pressed'), star.get_attribute('aria-label'), star.get_attribute('title')),
                                     ('true', 'Remove from favorites', 'Remove from favorites'))
                    star.focus(); page.keyboard.press('Space')
                    self.assertEqual(star.get_attribute('aria-pressed'), 'false')
                    star.click()
                    self.assertEqual(page.evaluate('localStorage.length'), 0)              # nothing is saved for the favorite
                    page.reload()
                    self.assertEqual(page.locator('[data-ui-toggle]').get_attribute('aria-pressed'), 'false')
                    page.locator('[data-ui-theme-switch]').select_option('green')
                    self.assertEqual(page.evaluate('document.body.dataset.uiTheme'), 'green')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_no_overflow_at_any_width_or_height_and_the_selection_reads_in_every_theme(self):
        server, origin = self.pages()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(origin + '/showcase.html')
                    for width in (320, 384, 768, 899, 900, 1199, 1200, 1440):
                        for height in (900, 432):
                            for section in ('overview', 'components', 'data', 'media'):
                                with self.subTest(width=width, height=height, section=section):
                                    page.set_viewport_size({'width': width, 'height': height})
                                    page.locator(f'label[for="showcase-sec-{section}"]:visible').first.click()
                                    metrics = page.evaluate("""() => {
                                        const box = s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; };
                                        const nav = [...document.querySelectorAll('.ui-rail, .ui-bottom-nav')].find(n => getComputedStyle(n).display !== 'none');
                                        return {docW: document.documentElement.scrollWidth, innerW: innerWidth, header: box('.ui-shell-header'),
                                                main: box('.ui-shell-main'), nav: nav.getBoundingClientRect().toJSON(), headerH: document.querySelector('.ui-shell-header').offsetHeight};
                                    }""")
                                    self.assertLessEqual(metrics['docW'], metrics['innerW'])           # no sideways scrolling
                                    self.assertGreaterEqual(metrics['header'][0], 0); self.assertLessEqual(metrics['header'][1], width)
                                    self.assertGreaterEqual(metrics['main'][0], 0); self.assertLessEqual(metrics['main'][1], width)
                                    self.assertGreaterEqual(metrics['nav']['left'], 0); self.assertLessEqual(metrics['nav']['right'], width)
                                    self.assertEqual(metrics['headerH'] % 8, 0)                       # the header is on the 8 px grid
                    # The selected rail/bottom-bar item reads in every theme (accent on the page color, both ways round).
                    page.set_viewport_size({'width': 1280, 'height': 800})
                    page.locator('.ui-rail label', has_text='Overview').click()
                    for theme in ('modern', 'github-like', 'green', 'red', 'blue'):
                        with self.subTest(theme=theme):
                            page.evaluate('theme => { document.body.dataset.uiTheme = theme }', theme)
                            colors = page.evaluate("""() => {
                                const l = document.querySelector('.ui-rail label[for="showcase-sec-overview"]'), s = getComputedStyle(l);
                                const hex = c => '#' + c.match(/\\d+/g).slice(0, 3).map(n => (+n).toString(16).padStart(2, '0')).join('');
                                return {bg: hex(s.backgroundColor), fg: hex(s.color)};
                            }""")
                            self.assertGreaterEqual(contrast_ratio(colors['fg'], colors['bg']), 4.5, colors)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class CatalogueBrowserTests(unittest.TestCase):
    """A 198-screen catalogue as a map, in Chromium: floors and categories filter it, a tap opens the sheet, and it fits a phone."""

    def test_floors_categories_and_sheets_work_on_a_large_catalogue(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import screens_like
        from web_ui import catalogue_world
        server, origin = WorldBrowserTests.serve({'index.html': world_document(catalogue_world(screens_like(), title='Screens'))})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for width in (390, 1280):
                        with self.subTest(width=width):
                            page = browser.new_page(viewport={'width': width, 'height': 800})
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(origin + '/index.html')
                            world = page.locator('#catalogue-map')
                            self.assertEqual(world.locator('.ui-world-bar label[for^="catalogue-floor-"]').count(), 5)
                            shown = lambda: world.locator('.ui-floor:visible .ui-spot:visible').count()
                            world.locator('label[for="catalogue-floor-f3"]').click()
                            self.assertEqual(world.locator('.ui-floor:visible').get_attribute('data-floor'), 'f3')
                            expect(world.locator('.ui-floor:visible .ui-spot').first).to_be_visible()
                            everything = world.locator('.ui-floor:visible .ui-spot').count()
                            self.assertEqual(everything, 40)
                            world.locator('label[data-cat="display"]').click()                 # a category chip narrows the floor
                            narrowed = world.locator('.ui-floor:visible .ui-spot:visible').count()
                            self.assertTrue(0 < narrowed < everything, narrowed)
                            world.locator('label[data-cat=""]').click()
                            self.assertEqual(world.locator('.ui-floor:visible .ui-spot:visible').count(), everything)
                            spot = world.locator('.ui-floor:visible .ui-spot').first
                            spot.dispatch_event('click', {'detail': 0})
                            self.assertTrue(page.locator('.ui-sheet-item[data-open]').is_visible())
                            self.assertIn('about', page.locator('.ui-sheet-item[data-open]').inner_text())
                            self.assertEqual(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), True)
                            self.assertEqual(errors, [])
                            page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class ShelfBrowserTests(unittest.TestCase):
    """The clipboard shelf in Chromium: its rules equal Python's, and the shelf works and keeps nothing."""

    def serve_page(self):
        from web_ui import shelf_document
        return WorldBrowserTests.serve({'shelf.html': shelf_document()})

    def test_the_pages_rules_equal_pythons_on_ironmates_cases_and_a_seeded_fuzz(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import BASE64_CASES, PNG_B64, shelf_fuzz_texts
        import random
        import web_ui
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/shelf.html')
                    limit = BASE64_CASES['limits']['maxInputBytes']
                    texts = [c['text'] for c in BASE64_CASES['cases']]
                    got = page.evaluate('([texts, limit]) => texts.map(t => webUiShelf.decodeImageText(t, limit))', [texts, limit])
                    self.assertEqual(got, [web_ui.decode_image_text(t, limit) for t in texts])
                    fuzz = shelf_fuzz_texts()
                    for name, py in (('shelfClassify', web_ui.shelf_classify), ('markdownPlain', web_ui.markdown_plain), ('looksLikeImage', web_ui.looks_like_image),
                                     ('decodeImageText', web_ui.decode_image_text)):
                        got = page.evaluate(f'texts => texts.map(t => webUiShelf.{name}(t))', fuzz)
                        for text, result in zip(fuzz, got):
                            self.assertEqual(result, py(text), (name, text))
                    # Byte limits: the same answer at every limit around the PNG's size, and for text that only looks like an image.
                    size = len(__import__('base64').b64decode(PNG_B64))
                    limits = [1, size - 1, size, size + 1, 3, 4, 5]
                    got = page.evaluate('([t, limits]) => limits.map(n => webUiShelf.decodeImageText(t, n))', [PNG_B64, limits])
                    self.assertEqual(got, [web_ui.decode_image_text(PNG_B64, n) for n in limits])
                    # Prompts and bundles from random fields and items.
                    rng = random.Random(7)
                    pool = ['', ' ', 'Goal \u3000', '\ufeffx', 'line1\nline2', '  pad  ', '\t\n', 'あ', '## h']
                    fields = [{k: rng.choice(pool) for k in ('goal', 'context', 'must', 'avoid', 'format', 'raw') if rng.random() < 0.7} for _ in range(300)]
                    images = [None if rng.random() < 0.5 else {'mime': rng.choice(['image/png', '', 'image/webp']), 'bytes': rng.randint(1, 10 ** 6)} for _ in fields]
                    got = page.evaluate('pairs => pairs.map(([f, i]) => webUiShelf.buildPrompt(f, i))', [[f, i] for f, i in zip(fields, images)])
                    self.assertEqual(got, [web_ui.build_prompt(f, i) for f, i in zip(fields, images)])
                    bundles = [[rng.choice([{'kind': 'text', 'text': 'a\nb'}, {'kind': 'url', 'text': 'https://x/'}, {'kind': 'markdown', 'text': '# h'},
                                            {'kind': 'image', 'mime': 'image/png', 'data': 'QQ=='}]) for _ in range(rng.randint(0, 4))] for _ in range(100)]
                    got = page.evaluate('lists => lists.map(l => webUiShelf.shelfBundle(l))', bundles)
                    self.assertEqual(got, [web_ui.shelf_bundle(b) for b in bundles])
                    self.assertEqual(page.evaluate('webUiShelf.shelfMaxChars(33554432)'), web_ui.shelf_max_chars(33554432))
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_adding_filtering_ordering_copying_and_forgetting(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import PNG_B64
        import base64
        import web_ui
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    context = browser.new_context(viewport={'width': 900, 'height': 1000})
                    context.add_init_script("""window.__copied = []; window.__paste = '';
                        Object.defineProperty(navigator, 'clipboard', {value: {writeText: async t => { window.__copied.push(t) }, readText: async () => window.__paste}});""")
                    page = context.new_page()
                    errors, requests = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/shelf.html')
                    page.on('request', lambda request: requests.append(request.url))
                    box, status = page.locator('[data-shelf-input]'), page.locator('[data-shelf-status]')
                    add = lambda text: (box.fill(text), page.locator('[data-shelf-add]').click())
                    add('   ')
                    self.assertIn('Nothing to add', status.text_content())
                    for text in ('first note', 'https://example.com/a', '# Heading\n- point [l](http://u)', PNG_B64):
                        add(text)
                    self.assertEqual(box.input_value(), '')
                    kinds = lambda: [li.get_attribute('data-kind') for li in page.locator('.ui-shelf-item').all()]
                    visible = lambda: [li.get_attribute('data-kind') for li in page.locator('.ui-shelf-item').all() if li.is_visible()]
                    self.assertEqual(sorted(kinds()), ['image', 'markdown', 'text', 'url'])
                    img = page.locator('.ui-shelf-item[data-kind="image"] img')
                    img.wait_for()
                    self.assertEqual(page.evaluate("document.querySelector('.ui-shelf-item img').naturalWidth"), 2)
                    # A GIF is refused as an image and kept as text, saying why.
                    gif = base64.b64encode(b'GIF89a\x01\x00\x01\x00' + bytes(80)).decode()      # long enough to look like an image, but a GIF
                    add(gif)
                    self.assertIn('unsupported_format', status.text_content())
                    self.assertEqual(visible().count('text'), 2)
                    # Filters are radios drawn by CSS only.
                    page.locator('label[for="shelf-kind-url"]').click()
                    self.assertEqual(visible(), ['url'])
                    page.locator('label[for="shelf-kind-markdown"]').click()
                    self.assertEqual(visible(), ['markdown'])
                    page.locator('label[for="shelf-kind-all"]').click()
                    self.assertEqual(len(visible()), 5)
                    # Order: newest first by default; oldest first reverses it; the layout follows the order.
                    top = lambda: [li.get_attribute('data-id') for li in sorted(page.locator('.ui-shelf-item').all(), key=lambda li: li.bounding_box()['y'])]
                    self.assertEqual(top(), ['5', '4', '3', '2', '1'])
                    page.locator('label[for="shelf-sort-oldest"]').click()
                    self.assertEqual(top(), ['1', '2', '3', '4', '5'])
                    # Manual: Up/Down swap neighbours among the visible items and switch to manual order.
                    page.locator('.ui-shelf-item[data-id="1"] [data-act="down"]').click()
                    self.assertEqual(top(), ['2', '1', '3', '4', '5'])
                    self.assertTrue(page.locator('#shelf-sort-manual').is_checked())
                    page.locator('.ui-shelf-item[data-id="3"] [data-act="up"]').click()
                    self.assertEqual(top(), ['2', '3', '1', '4', '5'])
                    page.locator('.ui-shelf-item[data-id="2"] [data-act="up"]').click()      # already first: nothing moves
                    self.assertEqual(top(), ['2', '3', '1', '4', '5'])
                    # Copying: one item, the plain form of Markdown, and a bundle of the picked items in the shown order.
                    copied = lambda: page.evaluate('window.__copied')
                    page.locator('.ui-shelf-item[data-id="3"] [data-act="copy"]').click()
                    page.locator('.ui-shelf-item[data-id="3"] [data-act="plain"]').click()
                    page.wait_for_function('window.__copied.length === 2')
                    self.assertEqual(copied(), ['# Heading\n- point [l](http://u)', web_ui.markdown_plain('# Heading\n- point [l](http://u)')])
                    page.locator('.ui-shelf-item[data-id="1"] input[type=checkbox]').check()
                    page.locator('.ui-shelf-item[data-id="3"] input[type=checkbox]').check()
                    page.locator('[data-shelf-bundle]').click()
                    page.wait_for_function('window.__copied.length === 3')
                    self.assertEqual(copied()[2], web_ui.shelf_bundle([{'kind': 'markdown', 'text': '# Heading\n- point [l](http://u)'}, {'kind': 'text', 'text': 'first note'}]))
                    # Pasting from the clipboard goes through the same rules.
                    page.evaluate("window.__paste = 'https://example.org/pasted'")
                    page.locator('[data-shelf-paste]').click()
                    page.wait_for_function("document.querySelectorAll('.ui-shelf-item').length === 6")
                    # The prompt workbench previews and copies what Python builds, with the image attached on request.
                    page.locator('summary', has_text='Prompt workbench').click()
                    page.locator('[name=goal]').fill('  Summarize  ')
                    page.locator('[name=raw]').fill('raw text')
                    self.assertEqual(page.locator('[data-shelf-prompt]').text_content(), web_ui.build_prompt({'goal': 'Summarize', 'raw': 'raw text'}))
                    page.locator('[data-shelf-attach]').click()
                    size = len(base64.b64decode(PNG_B64))
                    self.assertEqual(page.locator('[data-shelf-prompt]').text_content(),
                                     web_ui.build_prompt({'goal': 'Summarize', 'raw': 'raw text'}, {'mime': 'image/png', 'bytes': size}))
                    page.locator('[data-shelf-copy-prompt]').click()
                    page.wait_for_function('window.__copied.length === 4')
                    self.assertTrue(copied()[3].startswith('# System Prompt Draft'))
                    # Removing and clearing; and nothing is stored or sent anywhere.
                    page.locator('.ui-shelf-item[data-id="2"] [data-act="remove"]').click()
                    self.assertEqual(page.locator('.ui-shelf-item').count(), 5)
                    state = page.evaluate("""async () => ({local: localStorage.length, session: sessionStorage.length, cookie: document.cookie,
                        databases: (await indexedDB.databases()).length, caches: (await caches.keys()).length})""")
                    self.assertEqual(state, {'local': 0, 'session': 0, 'cookie': '', 'databases': 0, 'caches': 0})
                    self.assertEqual([r for r in requests if not r.startswith('data:')], [])
                    page.locator('[data-shelf-clear]').click()
                    self.assertEqual(page.locator('.ui-shelf-item').count(), 0)
                    page.locator('[data-shelf-add]').click()
                    box.fill('kept?'); page.locator('[data-shelf-add]').click()
                    page.reload()
                    self.assertEqual(page.locator('.ui-shelf-item').count(), 0)               # a reload empties the shelf
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_the_shelf_reads_in_every_theme_and_fits_a_phone(self):
        from test_python_wrapper import PNG_B64
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for width in (320, 390, 900):
                        with self.subTest(width=width):
                            page = browser.new_page(viewport={'width': width, 'height': 800})
                            page.goto(origin + '/shelf.html')
                            for text in ('x' * 300, 'https://example.com/' + 'a' * 200, '# H\n- ' + 'word ' * 40, PNG_B64):
                                page.locator('[data-shelf-input]').fill(text)
                                page.locator('[data-shelf-add]').click()
                            self.assertEqual(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), True)
                            page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class DoorBrowserTests(unittest.TestCase):
    """Door-to-Door in Chromium: the page's seeded draw, notation and pull-down equal Python's, and the pull-down really goes there."""

    def test_the_seeded_draw_the_options_and_the_notation_equal_pythons(self):
        import random
        import web_ui
        from web_ui import door_document, door_draw, door_options, door_validate, emoji_path, example_data, mulberry32
        door = door_validate(example_data('door'))
        server, origin = WorldBrowserTests.serve({'door.html': door_document(door)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/door.html')
                    seeds = [0, 1, 2, 7, 2 ** 31, 2 ** 32 - 1, 20261103, 4294967295 - 12345] + [random.Random(11).randrange(2 ** 32) for _ in range(200)]
                    got = page.evaluate('seeds => seeds.map(s => { const g = webUiDoor.mulberry32(s); return Array.from({length: 12}, () => g()) })', seeds)
                    for seed, row in zip(seeds, got):
                        gen = mulberry32(seed)
                        self.assertEqual(row, [next(gen) for _ in range(12)], seed)                    # the same floats, bit for bit
                    shapes = [(1, 1), (5, 0), (5, 5), (6, 3), (14, 3), (64, 8), (193, 3)]
                    cases = [[seed, count, k] for seed in seeds for count, k in shapes]
                    got = page.evaluate('cases => cases.map(c => webUiDoor.doorDraw(...c))', cases)
                    self.assertEqual(got, [door_draw(*c) for c in cases])
                    got = page.evaluate('([door, seeds]) => seeds.map(s => webUiDoor.doorOptions(door, s).map(o => [o.href, o.current, o.drawn]))', [door, seeds[:60]])
                    self.assertEqual(got, [[[o['href'], o['current'], o['drawn']] for o in door_options(door, s)] for s in seeds[:60]])
                    # Notation: random mixes of known and unknown emoji, arrows, spaces and variation selectors.
                    rng = random.Random(5)
                    known = [p['emoji'] for p in door['pages']] + ['🗺', '🏠\ufe0e', '🕸', '🎛']
                    bits = known + ['🦄', '→', '↔', '→', '↔', ' ', '\u3000', '\n', '\ufe0f', '', '-', 'a']
                    notations = [''.join(rng.choice(bits) + rng.choice(['', ' ']) for _ in range(rng.randint(0, 7))) for _ in range(600)]
                    notations += ['🏠 ↔︎ 🧭', '🏠 → 🧭 → 🎨 ↔ 📋', '→', '🏠 →', '🌐 ↔ 🌐']
                    got = page.evaluate("""([notes, pages]) => notes.map(n => { try { return {ok: webUiDoor.emojiPath(n, pages)} } catch (e) { return {error: true} } })""", [notations, door['pages']])
                    for note, result in zip(notations, got):
                        try:
                            expected = {'ok': emoji_path(note, door['pages'])}
                        except ValueError:
                            expected = {'error': True}
                        self.assertEqual(result, expected, repr(note))
                    self.assertGreater(sum('ok' in r for r in got), 50)
                    self.assertGreater(sum('error' in r for r in got), 50)
                    self.assertEqual(page.evaluate('webUiDoor.emojiKey("🗺\ufe0f\u3000 \ufe0e")'), web_ui.emoji_key('🗺\ufe0f\u3000 \ufe0e'))
                    # The page's first render equals the Python-rendered options.
                    html = door_document(door)
                    import re
                    server_side = re.findall(r'<option value="([^"]*)"', html)
                    page_side = page.evaluate("[...document.querySelectorAll('[data-door-select] option')].map(o => o.getAttribute('value'))")
                    self.assertEqual([v.replace('&amp;', '&') for v in server_side], page_side)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_the_pulldown_goes_there_can_be_stopped_and_draws_again(self):
        import json
        from web_ui import door_document, door_options, door_validate
        spec = {'schema': 'web-ui-door/1', 'current': './door.html', 'k': 2, 'seed': 3, 'pages': [
            {'emoji': '🏠', 'label': 'Home', 'href': './home.html'}, {'emoji': '🚪', 'label': 'Door', 'href': './door.html'},
            {'emoji': '🅰️', 'label': 'A', 'href': './a.html', 'group': 'discover'}, {'emoji': '🅱️', 'label': 'B', 'href': './b.html', 'group': 'discover'},
            {'emoji': '🆎', 'label': 'C', 'href': './c.html', 'group': 'discover'}, {'emoji': '🆑', 'label': 'D', 'href': './d.html#frag', 'group': 'discover'}]}
        door = door_validate(spec)
        pages = {'door.html': door_document(spec), 'home.html': '<title>home</title><p id=here>HOME</p>', 'a.html': '<p id=here>A</p>',
                 'b.html': '<p id=here>B</p>', 'c.html': '<p id=here>C</p>', 'd.html': '<p id=here>D</p>'}
        server, origin = WorldBrowserTests.serve(pages)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    page.add_init_script('window.__rnd = [0.25, 0.5]; Math.random = () => window.__rnd.shift() ?? 0.75')
                    page.goto(origin + '/door.html')
                    select = page.locator('[data-door-select]')
                    labels = lambda: [o.text_content() for o in page.locator('[data-door-select] option').all()]
                    self.assertEqual(labels()[0], '🏠 Home')
                    self.assertIn('🚪 Door (current)', labels())
                    self.assertTrue(page.locator('[data-door-select] option:disabled').text_content().endswith('(current)'))
                    # Draw again: the page picks a seed with Math.random and shows exactly what Python draws for that seed.
                    page.locator('[data-door-draw]').click()
                    seed = int(0.25 * 4294967296)
                    expected = [f"{o['emoji']} {o['label']}" + (' (current)' if o['current'] else '') for o in door_options(door, seed)]
                    self.assertEqual(labels(), expected)
                    self.assertIn(f'seed {seed}', page.locator('[data-door-status]').text_content())
                    # A guard can stop the trip: nothing opens and the pull-down goes back.
                    page.evaluate("document.querySelector('[data-ui-door]').addEventListener('ui-door-leave', e => e.preventDefault(), {once: true})")
                    select.select_option(label='🏠 Home')
                    self.assertEqual(page.url, origin + '/door.html')
                    self.assertIn('Staying here', page.locator('[data-door-status]').text_content())
                    # Otherwise it goes there, a fragment included.
                    select.select_option(label='🏠 Home')
                    page.wait_for_url('**/home.html')
                    self.assertEqual(page.locator('#here').text_content(), 'HOME')
                    page.goto(origin + '/door.html')
                    target = next(o for o in door_options(door) if o['drawn'])
                    select.select_option(index=[i for i, o in enumerate(door_options(door)) if o['href'] == target['href']][0])
                    page.wait_for_url('**' + target['href'].lstrip('.'))
                    # The notation panel shows the pages in order, with the way back; an unknown emoji shows the problem and no list.
                    page.goto(origin + '/door.html')
                    page.locator('[data-door-notation]').fill('🏠 ↔ 🅰️')
                    self.assertEqual(page.locator('[data-door-path] a').all_text_contents(), ['./home.html', './a.html', './home.html'])
                    self.assertEqual(page.locator('[data-door-path] a').first.get_attribute('href'), './home.html')
                    page.locator('[data-door-notation]').fill('🏠 → 🦄')
                    self.assertEqual(page.locator('[data-door-path] li').count(), 0)
                    self.assertIn('unknown page emoji', page.locator('[data-door-note]').text_content())
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class StudioBrowserTests(unittest.TestCase):
    """The composition studio in Chromium: every rule equals Python's, and the controls drive them."""

    def serve_page(self):
        from web_ui import studio_document
        return WorldBrowserTests.serve({'studio.html': studio_document()})

    def test_every_rule_in_the_page_equals_pythons(self):
        import random
        import web_ui as w
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/studio.html')
                    # Run a Python function and the page's on the same arguments; an error must be an error on both sides.
                    def agree(name, py, calls):
                        got = page.evaluate(f"""calls => calls.map(a => {{ try {{ return {{ok: webUiStudio.{name}(...a)}} }} catch (e) {{ return {{error: true}} }} }})""", calls)
                        for call, result in zip(calls, got):
                            try:
                                expected = {'ok': py(*call)}
                            except ValueError:
                                expected = {'error': True}
                            if 'ok' in expected and isinstance(expected['ok'], tuple):
                                expected = {'ok': list(expected['ok'])}
                            self.assertEqual(result, expected, (name, call))
                        return got
                    keys = list(w.SELECTABLE_KEYS)
                    agree('transposeKey', w.transpose_key, [[k, n] for k in keys for n in range(-14, 15)])
                    agree('fifthNeighbor', lambda k, c: w.fifth_neighbor(k, clockwise=c), [[k, c] for k in keys for c in (True, False)])
                    agree('scale', lambda k, m: w.scale(k, minor=m), [[k, m] for k in keys + ['H', 'C#', ''] for m in (False, True)])
                    agree('diatonicChord', lambda k, d, m: w.diatonic_chord(k, d, minor=m), [[k, d, m] for k in keys for d in range(0, 9) for m in (False, True)])
                    roots = [r for k in keys[:6] for r in w.scale(k, minor=False)]
                    agree('chordWithInversion', w.chord_with_inversion, [[r, m, i] for r in roots for m in w.CHORD_MODIFIERS + ('9',) for i in range(-1, 5)])
                    agree('chordTones', w.chord_tones, [[r, m] for r in roots for m in w.CHORD_MODIFIERS])
                    agree('pitchClass', w.pitch_class, [[x] for x in ['C', 'F♯', 'B♭♭', 'E♯♯', 'H', 'c', '', 'C#', 'C♯♭']])
                    # Progressions: random Roman numerals, suffixes, separators, odd characters.
                    rng = random.Random(3)
                    tokens = ['I', 'ii', 'iii', 'IV', 'V', 'vi', 'vii', 'VII', 'i', 'iv', 'v', 'VI', 'III', 'I6', 'ii6', 'Imaj7', 'IM7', 'I△7', 'V7', 'ii7', 'viiø7', 'viim7♭5', 'IVsus2', 'IVsus4',
                              'IVadd9', 'IVadd11', 'Vaug', 'V+', 'vii°', 'viidim', 'im6', 'Vx', 'IIII', 'x', 'C', '7', 'vi\u3000', '\ufeffI', 'I\u2028V', 'iv\u00a0']
                    seps = [' ', ' ', ',', ' – ', ' — ', '-', '|', ' | ', '\t', '\n', ', ', '  ']
                    progressions = [''.join(rng.choice(tokens) + rng.choice(seps) for _ in range(rng.randint(0, 6))) for _ in range(500)]
                    agree('convertProgression', lambda k, p, m: w.convert_progression(k, p, minor=m), [[rng.choice(keys), p, rng.random() < 0.5] for p in progressions])
                    # Metronome: all tempos around the clamps, odd meters, huge and negative elapsed times; labels for every tempo.
                    cases = [[rng.choice([-10 ** 6, 0, 1, 249_999, 250_000, 750_000, 2_250_000, rng.randint(0, 10 ** 9), rng.randint(0, 10 ** 12)]),
                              rng.choice([1, 29, 30, 31, 120, 299, 300, 301, 1000]), rng.choice([1, 2, 3, 4, 6, 7, 12]), rng.choice([1, 2, 3, 4])] for _ in range(1500)]
                    agree('metronomePosition', w.metronome_position, cases)
                    agree('beatMicros', w.beat_micros, [[b] for b in range(0, 400)])
                    agree('barMicros', w.bar_micros, [[b, n] for b in range(25, 310, 7) for n in range(0, 13)])
                    agree('subdivisionMicros', w.subdivision_micros, [[b, n] for b in range(25, 310, 7) for n in range(0, 9)])
                    agree('durationLabel', w.duration_label, [[m] for m in [0, 1, 499, 500, 501, 999_499, 999_500, 999_999, 1_000_000, 1_004_999, 1_005_000, 1_125_000, 2_000_000, 12_345_678]
                                                              + [w.bar_micros(b, n) for b in range(30, 301, 5) for n in (1, 3, 4, 6)]])
                    # Tap tempo: random tap trains, with long gaps, repeats and zero intervals.
                    for _ in range(300):
                        train = sorted(rng.choice([0, 100_000, 250_000, 500_000, 900_000, 2_000_001, 5_000_000]) + 7_000_000 * j for j in range(rng.randint(1, 9)))
                        got = page.evaluate("""train => { let taps = []; return train.map(t => { const [k, b] = webUiStudio.tapTempo(taps, t); taps = k; return [k, b] }) }""", train)
                        taps, expected = [], []
                        for t in train:
                            taps, bpm = w.tap_tempo(taps, t)
                            expected.append([taps, bpm])
                        self.assertEqual(got, expected, train)
                    # Notes and bars.
                    notes = ['C3 d3 F#3 Gb3', 'C3,D3,\tE-1\n', '', 'C3 nope', 'C33', 'c♯♭3', 'A4 B4 C5 D5 E5', ' G3  ', 'H1']
                    agree('parseNotes', w.parse_notes, [[n] for n in notes])
                    agree('notesPerBar', w.notes_per_bar, [[b, u, n] for b in range(0, 9) for u in (1, 2, 4, 8) for n in (2, 4, 8, 16)])
                    agree('noteBars', w.note_bars, [[w.parse_notes(n), b, u, nu] for n in notes[:1] + notes[1:2] + notes[6:7] for b, u, nu in ((4, 4, 8), (4, 4, 4), (6, 8, 8), (6, 8, 4), (3, 4, 8), (5, 8, 4))])
                    # Song seeds, with and without something to avoid.
                    seeds = [0, 1, 5, 2 ** 32 - 1, 20261103] + [rng.randrange(2 ** 32) for _ in range(500)]
                    agree('songSeed', w.song_seed, [[x] for x in seeds])
                    agree('songSeed', w.song_seed, [[x, w.song_seed(x)] for x in seeds[:100]])
                    agree('songSeedText', w.song_seed_text, [[w.song_seed(x)] for x in seeds[:100]])
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_the_controls_drive_the_rules(self):
        import web_ui as w
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 1200})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.add_init_script('window.__rnd = [0.5]; Math.random = () => window.__rnd.shift() ?? 0.123')
                    page.goto(origin + '/studio.html')
                    text = lambda sel: page.locator(sel).text_content()
                    # Theory: the Dart tests' own cases, through the controls.
                    self.assertEqual(text('[data-prog-out]').split(), ['C', 'G', 'Am', 'F'])
                    page.locator('[data-key]').select_option('D')
                    self.assertEqual(text('[data-prog-out]').split(), ['D', 'A', 'Bm', 'G'])
                    page.locator('[data-semi-down]').click()
                    self.assertEqual(page.locator('[data-key]').input_value(), 'C♯')                    # D prefers sharps, so a semitone down is C♯
                    page.locator('[data-key]').select_option('D♭')
                    self.assertEqual(text('[data-fifth-left]'), 'G♭')
                    self.assertEqual(text('[data-fifth-right]'), 'A♭')
                    page.locator('[data-fifth-right]').click()
                    self.assertEqual(page.locator('[data-key]').input_value(), 'A♭')
                    page.locator('[data-key]').select_option('C')
                    self.assertEqual(page.locator('[data-degrees] .ui-tag').all_text_contents(), ['1 C', '2 Dm', '3 Em', '4 F', '5 G', '6 Am', '7 Bdim'])
                    page.locator('[data-prog]').fill('I6 IV6 Imaj7 V7 ii7 viiø7 IVsus2 IVadd9 Vaug')
                    self.assertEqual(text('[data-prog-out]').split(), ['C6', 'F6', 'Cmaj7', 'G7', 'Dm7', 'Bm7♭5', 'Fsus2', 'Fadd9', 'Gaug'])
                    page.locator('label', has_text='Minor').click()
                    self.assertEqual(page.locator('[data-degrees] .ui-tag').first.text_content(), '1 Cm')
                    page.locator('label', has_text='Major').first.click()
                    page.locator('[data-degree]').select_option('1')
                    page.locator('[data-mod]').select_option('maj7')
                    page.locator('label', has_text='1st').click()
                    self.assertEqual(text('[data-chord]'), 'Cmaj7/E  (C E G B)')
                    page.locator('[data-mod]').select_option('triad')
                    page.locator('label', has_text='3rd').click()
                    self.assertEqual(text('[data-chord]').split()[0], 'C/E')
                    # Notes and bars, and a refused note.
                    self.assertEqual(page.locator('[data-bars] li').all_text_contents(), ['C3 D3 C3 D3 G3 A3 G3 C4'])
                    page.locator('[data-note-unit]').select_option('4')
                    self.assertEqual(page.locator('[data-bars] li').all_text_contents(), ['C3 D3 C3 D3', 'G3 A3 G3 C4'])
                    page.locator('[data-notes]').fill('C3 nope')
                    self.assertEqual(page.locator('[data-bars] li[data-error]').text_content(), 'invalid note: nope')
                    # Metronome: the labels use Python's numbers; time signature changes the dots.
                    self.assertEqual(page.locator('.ui-beat').count(), 4)
                    self.assertIn(f'bar {w.duration_label(w.bar_micros(120, 4))}', text('[data-beat-info]'))
                    page.locator('label', has_text='6/8').click()
                    self.assertEqual(page.locator('.ui-beat').count(), 6)
                    page.locator('label', has_text='3/4').click()
                    self.assertEqual(page.locator('.ui-beat').count(), 3)
                    page.locator('[data-bpm]').fill('60')
                    self.assertEqual(text('[data-bpm-out]'), '60 BPM')
                    self.assertIn(w.duration_label(w.beat_micros(60)), text('[data-beat-info]'))
                    # A new song seed: Math.random picks the seed, the text and the controls show what Python computes for it.
                    page.locator('[data-new-seed]').click()
                    seed = int(0.5 * 4294967296)
                    result = w.song_seed(seed)
                    self.assertEqual(text('[data-seed-out]'), f'{w.song_seed_text(result)} (seed {seed})')
                    self.assertEqual((page.locator('[data-key]').input_value(), page.locator('[data-bpm]').input_value(), page.locator('[data-prog]').input_value()),
                                     (result['tonic'], str(result['bpm']), result['progression']))
                    self.assertTrue(page.locator(f'input[name="studio-mode"][value="{result["mode"]}"]').is_checked())
                    self.assertTrue(page.locator(f'input[name="studio-sig"][value="{result["time"]}"]').is_checked())
                    self.assertEqual(text('[data-prog-out]').split(), w.convert_progression(result['tonic'], result['progression'], minor=result['mode'] == 'Minor'))
                    self.assertEqual(page.evaluate('localStorage.length + sessionStorage.length'), 0)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_the_metronome_follows_elapsed_time_and_tap_tempo_sets_the_tempo(self):
        import web_ui as w
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 1200})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.clock.install(time=0)
                    page.goto(origin + '/studio.html')
                    page.clock.pause_at(10_000)                                                       # from here time moves only when the test says so
                    dots = lambda: [d.get_attribute('data-on') is not None for d in page.locator('.ui-beat').all()]
                    self.assertEqual(dots(), [False] * 4)
                    page.locator('[data-run]').click()
                    self.assertEqual(page.locator('[data-run]').get_attribute('aria-pressed'), 'true')
                    start = page.evaluate('performance.now()')                                         # 120 BPM in 4/4, two subdivisions per beat
                    for elapsed in (100, 770, 1620, 2270, 4120):                                      # just past a boundary: a frame lands 16 ms apart
                        now = page.evaluate('performance.now()')
                        page.clock.run_for(start + elapsed - now)
                        page.wait_for_timeout(0)
                        beat, sub, _ = w.metronome_position(elapsed * 1000, 120, 4, 2)
                        self.assertEqual(dots().index(True), beat, elapsed)
                        self.assertEqual(page.locator('[data-ui-studio]').get_attribute('data-sub'), str(sub), elapsed)
                    # A new tempo restarts the bar; stopping clears the dots.
                    page.locator('[data-bpm]').fill('60')
                    now = page.evaluate('performance.now()')
                    page.clock.run_for(1500)
                    self.assertEqual(dots().index(True), w.metronome_position(1_500_000, 60, 4, 2)[0])
                    page.locator('[data-run]').click()
                    self.assertEqual(dots(), [False] * 4)
                    self.assertEqual(page.locator('[data-run]').text_content(), 'Start')
                    # Tap tempo: taps 500 ms apart make 120 BPM; a long pause starts again.
                    for _ in range(4):
                        page.locator('[data-tap]').click()
                        page.clock.run_for(500)
                    self.assertEqual(page.locator('[data-bpm]').input_value(), '120')
                    self.assertIn('120', page.locator('[data-tap]').text_content())
                    page.clock.run_for(5000)
                    page.locator('[data-tap]').click()
                    page.clock.run_for(250)
                    page.locator('[data-tap]').click()
                    self.assertEqual(page.locator('[data-bpm]').input_value(), '240')
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class CoordinatesBrowserTests(unittest.TestCase):
    """The coordinate tool in Chromium: every rule equals Python's (and so the Dart tests'), and the page works."""

    def serve_page(self):
        from web_ui import coordinates_document
        return WorldBrowserTests.serve({'coord.html': coordinates_document()})

    def test_every_rule_in_the_page_equals_pythons(self):
        import random
        import web_ui as w
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import AREA_CASES, coordinate_fuzz_urls
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/coord.html')
                    def agree(name, py, calls, close=False):
                        got = page.evaluate(f"""calls => calls.map(a => {{ try {{ return {{ok: webUiCoordinates.{name}(...a)}} }} catch (e) {{ return {{error: true}} }} }})""", calls)
                        for call, result in zip(calls, got):
                            try:
                                expected = {'ok': py(*call)}
                            except ValueError:
                                expected = {'error': True}
                            if isinstance(expected.get('ok'), tuple):
                                expected = {'ok': list(expected['ok'])}
                            if isinstance(expected.get('ok'), dict) and close:                                  # floats: the same up to the last digit or two
                                self.assertEqual(result.keys(), expected.keys())
                                for key, value in expected['ok'].items():
                                    other = result['ok'][key]
                                    if isinstance(value, float):
                                        self.assertAlmostEqual(other, value, delta=1e-9 * max(1, abs(value)), msg=(name, call, key))
                                    else:
                                        self.assertEqual(other, value, (name, call, key))
                            else:
                                self.assertEqual(result, expected, (name, call))
                        return got
                    rng = random.Random(9)
                    numbers = ['35.681236', '-0', '0', '90', '-90', '90.0000001', '180', '-180.5', '.5', '5.', '+1e1', '1e999', '-1e-5', '٣', '0x10', '1_0', ' 12 ', '３５．５', '－１３９', 'NaN', 'Infinity', '-Infinity',
                               '', 'north', '1e', 'e1', '--1', '1.2.3', '12\u00a0', '\ufeff7', '1,5']
                    agree('parseCoordinate', w.parse_coordinate, [[a, b] for a in numbers for b in numbers])
                    texts = coordinate_fuzz_urls() + ['https://www.google.com/maps/place/Tokyo+Station/@35.680000,139.760000,17z/data=!3d35.681236!4d139.767125', 'https://x/?q=91,0&ll=1,2', '', '  ',
                                                      'https://maps.apple.com/?q=Tokyo', 'https://x/?ll=1,2%', 'https://x/?ll=%25252C1', 'https://x/?q=1%2C2%2C3', '@1,2', '@1,2z', '@1,2\n']
                    agree('tryParseMapsUrl', w.try_parse_maps_url, [[t] for t in texts])
                    values = [0, -0.0, 1e-12, 0.5, 35.681236, -33.8688, 89.99999999, 90, -90, 179.999999999996, -179.5, 180, 59.99999, 0.99999999, 12.345678] + [rng.uniform(-180, 180) for _ in range(400)]
                    agree('toDms', lambda v, lat: w.to_dms(v, is_latitude=lat), [[v, lat] for v in values for lat in (True, False)])
                    seconds_edge = [d + m / 60 + sec / 3600 for d in (0, 35, 179) for m in (0, 59) for sec in (0, 59.99, 59.994999, 59.995, 59.9951, 59.999999)]
                    agree('toDms', lambda v, lat: w.to_dms(v, is_latitude=lat), [[v, True] for v in seconds_edge])
                    agree('fixed', w.fixed, [[v, n] for v in [0.0078125, 2.5, 0.125, -0.125, 1.005, -1e-9, 0.5, 35.681236] + [rng.uniform(-200, 200) for _ in range(200)] + [k / 128 for k in range(-40, 40)] for n in (0, 2, 6)])
                    points = [(rng.uniform(-90, 90), rng.uniform(-180, 180), rng.choice([1, 25, 100, 350, 1000, 3000, 12.5, 100000, 5e6, rng.uniform(1, 2e6)])) for _ in range(500)]
                    points += [(la, lo, r) for la in (0, 89.9999, -89.9999, 90, -90, 80, 85, 35.681236) for lo in (0, 179.999, -179.999, 180, -180, 20) for r in (1, 100, 1000, 1e6)]
                    points += [(case['latitude'], case['longitude'], case['radius_m']) for case in AREA_CASES]
                    agree('toleranceArea', w.tolerance_area, [list(p) for p in points], close=True)
                    texts_got = page.evaluate('points => points.map(p => webUiCoordinates.areaTexts(webUiCoordinates.toleranceArea(...p)))', [list(p) for p in points])
                    for point, got in zip(points, texts_got):
                        self.assertEqual(got, w.area_texts(w.tolerance_area(*point)), point)                 # every copyable text, byte for byte
                    zooms = [(r, lat) for r in (1, 3, 10, 25, 100, 350, 1000, 3000, 1e5, 1e7, 0, -5, float('nan')) for lat in (0, 35.681236, 60, 80, 85, 89.9999, 90, -45)] + [(rng.uniform(1, 3e5), rng.uniform(-90, 90)) for _ in range(500)]
                    agree('zoomForRadius', w.zoom_for_radius, [list(z) for z in zooms])
                    steps = [(40075016.686 / (4 * 2 ** k), 0) for k in range(0, 22)]                          # radii at exact powers of two
                    agree('zoomForRadius', w.zoom_for_radius, [list(z) for z in steps])
                    tiles = [(rng.uniform(-90, 90), rng.uniform(-180, 180), rng.randint(0, 22)) for _ in range(800)] + [(la, lo, z) for la in (-90, -85.05112878, 0, 85.06, 90) for lo in (-180, 0, 180) for z in (0, 1, 22, 23, -1)]
                    agree('xyzTile', w.xyz_tile, [list(t) for t in tiles])
                    agree('mapsUrls', w.maps_urls, [[la, lo] for la, lo in [(p[0], p[1]) for p in points[:200]]])
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_the_page_checks_formats_and_reads_urls(self):
        import web_ui as w
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 800, 'height': 1200})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/coord.html')
                    out = lambda: {dt.text_content(): dd.text_content() for dt, dd in zip(page.locator('[data-out] dt').all(), page.locator('[data-out] dd').all())}
                    self.assertEqual(page.locator('[data-status]').text_content(), 'Valid.')
                    first = out()
                    self.assertEqual(first['Decimal degrees'], '35.681236, 139.767125')
                    self.assertEqual(first['Degrees, minutes, seconds'], '35° 40′ 52.45″ N, 139° 46′ 01.65″ E')
                    self.assertEqual(first['XYZ tile'], '16/58211/25806')
                    self.assertEqual(first['Google Maps area link'], 'https://www.google.com/maps/@35.681236,139.767125,16z')
                    self.assertEqual(first['Tolerance: JSON'], w.area_texts(w.tolerance_area(*w.parse_coordinate('35.681236', '139.767125'), 100))['json'])
                    # A bad value says so and shows no results; fixing it brings them back.
                    page.locator('[data-lat]').fill('95')
                    self.assertEqual(page.locator('[data-status]').text_content(), 'Latitude must be between -90 and 90.')
                    self.assertEqual(out(), {})
                    page.locator('[data-lat]').fill('３５．５')                                                  # full-width digits are read
                    page.locator('[data-lon]').fill('170')
                    self.assertEqual(page.locator('[data-status]').text_content(), 'Valid.')
                    # Presets and a custom radius change the area; a date-line box says so and offers no Apple span.
                    page.locator('input[name="coord-preset"][value="1000"]').check()
                    self.assertIn('radius_m: 1000', out()['Tolerance: centre and radius'])
                    self.assertIn('wraps_antimeridian: false', out()['Tolerance: bounds'])
                    page.locator('[data-lat]').fill('0')
                    page.locator('[data-lon]').fill('179.999')
                    self.assertIn('wraps_antimeridian: true', out()['Tolerance: bounds'])
                    self.assertNotIn('spn=', out()['Apple Maps area link'])
                    page.locator('input[name="coord-preset"][value="custom"]').check()
                    page.locator('[data-radius]').fill('12.5')
                    self.assertIn('radius_m: 12.50', out()['Tolerance: centre and radius'])
                    page.locator('[data-radius]').fill('0')
                    self.assertEqual(out()['Tolerance'], 'Tolerance radius must be greater than zero.')
                    page.locator('[data-zoom]').fill('23')
                    self.assertEqual(out()['XYZ tile'], 'XYZ tile zoom must be between 0 and 22.')
                    # Reading a Maps URL fills both fields and refreshes every result.
                    page.locator('[data-url]').fill('https://www.google.com/maps/place/Tokyo+Station/@35.680000,139.760000,17z/data=!3d35.681236!4d139.767125')
                    page.locator('[data-use-url]').click()
                    self.assertEqual((page.locator('[data-lat]').input_value(), page.locator('[data-lon]').input_value()), ('35.681236', '139.767125'))
                    page.locator('[data-url]').fill('https://maps.apple.com/?q=Tokyo')
                    page.locator('[data-use-url]').click()
                    self.assertEqual(page.locator('[data-status]').text_content(), 'Could not find latitude/longitude in that Maps URL.')
                    self.assertEqual((page.evaluate('localStorage.length + sessionStorage.length'), errors), (0, []))
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class PhotoBrowserTests(unittest.TestCase):
    """The photo studio in Chromium: every rule in the page equals Python's (and so the Dart tests' and Pillow's), and the page works and keeps nothing."""

    @staticmethod
    def corpus():
        import io
        import random
        sys.path.insert(0, str(ROOT / 'tests'))
        from PIL import Image
        from test_python_wrapper import PHOTO_FIXTURE, photo_file
        rng = random.Random(8)
        blobs = []
        for case in PHOTO_FIXTURE['cases']:
            data = photo_file(case['id']) if case['data'] else b''
            blobs.append(data)
            blobs += [data[:n] for n in range(0, len(data), max(1, len(data) // 25))]
            for _ in range(25):
                mutated = bytearray(data)
                for _ in range(rng.randint(1, 4)):
                    if mutated:
                        mutated[rng.randrange(len(mutated))] = rng.randrange(256)
                blobs.append(bytes(mutated))
        for marker in range(0xC0, 0xD0):                                                    # every start-of-frame marker, in a JPEG header only
            sof = bytes([0xFF, marker, 0, 17, 8, 1, 224, 2, 128, 3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1])
            blobs.append(b'\xff\xd8\xff\xe0\x00\x04\x00\x00' + sof + b'\xff\xd9')
        for width, height in [(1, 1), (3, 2), (255, 256), (257, 255), (16383, 1), (1, 16383)] + [(rng.randint(1, 200), rng.randint(1, 200)) for _ in range(12)]:
            rgb = Image.new('RGB', (width, height), (9, 99, 199))
            rgba = rgb.convert('RGBA')
            for image, fmt, options in ((rgb, 'PNG', {}), (rgba, 'PNG', {}), (rgb.convert('P'), 'GIF', {}), (rgb, 'JPEG', {'quality': 60}), (rgb, 'JPEG', {'progressive': True}),
                                        (rgb, 'WEBP', {'quality': 50}), (rgb, 'WEBP', {'lossless': True}), (rgba, 'WEBP', {'quality': 50}), (rgba, 'WEBP', {'lossless': True})):
                if fmt == 'WEBP' and max(width, height) > 16383:
                    continue
                buffer = io.BytesIO()
                image.save(buffer, fmt, **options)
                blobs.append(buffer.getvalue())
        return blobs

    def serve_page(self):
        from web_ui import photo_document
        return WorldBrowserTests.serve({'photo.html': photo_document()})

    def test_every_rule_in_the_page_equals_pythons(self):
        import json
        import random
        import web_ui as w
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import PHOTO_FIXTURE, photo_file
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = photo_engine(playwright).launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/photo.html')
                    blobs = self.corpus()
                    lists = [list(b) for b in blobs]
                    self.assertGreater(len(lists), 1500)
                    got = page.evaluate('lists => lists.map(a => { const b = Uint8Array.from(a); return [webUiPhoto.sniff(b), webUiPhoto.headerSize(b), Array.from(webUiPhoto.neutralizeOrientation(b)), webUiPhoto.pngComplete(b)] })', lists)
                    for blob, (sniffed, header, neutral, complete) in zip(blobs, got):
                        self.assertEqual(sniffed, w.photo_sniff(blob))
                        self.assertEqual(complete, w.photo_png_complete(blob))
                        self.assertEqual(header, (list(w.photo_header_size(blob)) if w.photo_header_size(blob) else None))
                        self.assertEqual(bytes(neutral), w.photo_neutralize_orientation(blob))
                    # The decision: the same bytes, the same engine answer (none, a size, an oversize), the same declared type.
                    declared = [None, '', 'image/png', 'image/jpeg', 'image/avif', 'application/octet-stream', 'text/plain', 'image/x-icon']
                    answers = [None, [64, 32], [1, 1], [9000, 9000], [0, 5], [40000000, 1], [40000001, 1]]
                    rng = random.Random(4)
                    jobs = [[rng.randrange(len(lists)), rng.choice(declared), rng.choice(answers)] for _ in range(1500)]
                    got = page.evaluate("""([lists, jobs]) => Promise.all(jobs.map(([i, mime, answer]) =>
                        webUiPhoto.decide(Uint8Array.from(lists[i]), answer === null ? null : async () => answer, mime === null ? undefined : mime)))""", [lists, jobs])
                    for (index, mime, answer), result in zip(jobs, got):
                        expected = w.photo_decide(blobs[index], (lambda data, a=answer: tuple(a)) if answer else None, mime)
                        expected = {**expected, **({"document": list(expected["document"])} if "document" in expected else {})}
                        self.assertEqual(result, expected, (index, mime, answer))
                    self.assertEqual(page.evaluate('n => webUiPhoto.decide(new Uint8Array(0), null, undefined)', 0), w.photo_decide(b''))
                    # Limits, orientation and sizes.
                    lengths = [-1, 0, 1, 33554431, 33554432, 33554433, 10 ** 9]
                    self.assertEqual(page.evaluate('v => v.map(n => webUiPhoto.rejectBytes(n))', lengths), [w.photo_reject_bytes(n) for n in lengths])
                    sizes = [[a, b] for a in (-3, 0, 1, 64, 8000, 10000, 40000000, 40000001) for b in (-1, 0, 1, 5, 5000, 5001, 10000)]
                    self.assertEqual(page.evaluate('v => v.map(s => webUiPhoto.rejectSize(...s))', sizes), [w.photo_reject_size(*s) for s in sizes])
                    rng = random.Random(6)
                    docs = [[a, b] for a in (1, 2, 3, 4, 63, 64, 4095, 4096, 4097, 6144, 24576, 36864) for b in (1, 2, 3, 5, 64, 6144)] + [[rng.randint(1, 12000), rng.randint(1, 12000)] for _ in range(1500)]
                    self.assertEqual(page.evaluate('v => v.map(s => webUiPhoto.documentSize(...s))', docs), [list(w.photo_document_size(*s)) for s in docs])
                    cases = [[o, a, b] for o in range(0, 10) for a, b in ((64, 32), (5, 3), (1, 1), (7, 2))]
                    self.assertEqual(page.evaluate('v => v.map(([o, a, b]) => [webUiPhoto.orientationMatrix(o, a, b), webUiPhoto.orientedSize(a, b, o)])', cases),
                                     [[list(w.photo_orientation_matrix(o, a, b)), list(w.photo_oriented_size(a, b, o))] for o, a, b in cases])
                    self.assertEqual(page.evaluate('v => v.map(o => webUiPhoto.orientationOp(o))', list(range(-1, 11))), [w.photo_orientation_op(o) for o in range(-1, 11)])
                    for rejection in ('empty', 'tooLargeBytes', 'tooManyPixels', 'undecodable', 'heicConversionFailed'):
                        self.assertEqual(page.evaluate('r => webUiPhoto.failure(r)', rejection), w.photo_failure(rejection))
                    # Rectangles and shapes: the same arithmetic in the same order, so exactly the same numbers.
                    rng = random.Random(12)
                    unit = lambda: rng.choice([0, 1, 0.04, 0.5, 0.2, 0.8, rng.random(), rng.uniform(-0.5, 1.5), rng.uniform(0, 1)])
                    rects = [{'left': unit(), 'top': unit(), 'right': unit(), 'bottom': unit()} for _ in range(600)]
                    moves = [[unit() - 0.5, unit() - 0.5] for _ in rects]
                    handles = [rng.choice(w.PHOTO_HANDLES) for _ in rects]
                    shapes = [rng.choice(w.PHOTO_SHAPES) for _ in rects]
                    slops = [rng.choice([0, 0, 0.01, 0.0133, 0.05]) for _ in rects]
                    points = [[unit(), unit()] for _ in rects]
                    got = page.evaluate("""([rects, moves, handles, shapes, slops, points]) => rects.map((r, i) => ({
                        sanitized: webUiPhoto.rectSanitized(r), moved: webUiPhoto.rectTranslated(r, ...moves[i]), resized: webUiPhoto.rectResized(r, handles[i], ...moves[i]),
                        diagonal: webUiPhoto.rectFromDiagonal(r.left, r.top, r.right, r.bottom), text: webUiPhoto.rectText(r), csv: webUiPhoto.rectCsv(r),
                        edges: webUiPhoto.rectEdgeMidpoints(r), circle: webUiPhoto.circle(r), triangle: webUiPhoto.triangle(r), trimids: webUiPhoto.triangleMidpoints(r),
                        contains: webUiPhoto.shapeContains(r, shapes[i], ...points[i], slops[i]), describe: webUiPhoto.describe(r, shapes[i]),
                        cross: webUiPhoto.segmentIntersection(r.left, r.top, r.right, r.bottom, r.left, r.bottom, r.right, r.top)}))""", [rects, moves, handles, shapes, slops, points])
                    for i, r in enumerate(rects):
                        expected = {'sanitized': w.photo_rect_sanitized(r), 'moved': w.photo_rect_translated(r, *moves[i]), 'resized': w.photo_rect_resized(r, handles[i], *moves[i]),
                                    'diagonal': w.photo_rect_from_diagonal(r['left'], r['top'], r['right'], r['bottom']), 'text': w.photo_rect_text(r), 'csv': w.photo_rect_csv(r),
                                    'edges': w.photo_rect_edge_midpoints(r), 'circle': w.photo_circle(r), 'triangle': w.photo_triangle(r), 'trimids': w.photo_triangle_midpoints(r),
                                    'contains': w.photo_shape_contains(r, shapes[i], *points[i], slops[i]), 'describe': w.photo_describe(r, shapes[i]),
                                    'cross': w.photo_segment_intersection(r['left'], r['top'], r['right'], r['bottom'], r['left'], r['bottom'], r['right'], r['top'])}
                        self.assertEqual(got[i], expected, (i, r, handles[i], shapes[i]))
                    # Hit targets, with the canvas sizes the page really has, and the export arithmetic.
                    jobs = []
                    for _ in range(800):
                        width, height = rng.choice([(400, 300), (760, 280), (320, 240), (1000.5, 333.25), (0, 10)])
                        frames = [{'id': f'f{k}', 'rect': {'left': unit(), 'top': unit(), 'right': unit(), 'bottom': unit()}, 'shape': rng.choice(w.PHOTO_SHAPES)} for k in range(rng.randint(0, 3))]
                        stamps = [{'id': f's{k}', 'x': unit(), 'y': unit(), 'scale': rng.choice([0.4, 1, 3, rng.uniform(0.4, 3)])} for k in range(rng.randint(0, 3))]
                        jobs.append([width, height, frames, stamps, rng.uniform(-20, width + 20), rng.uniform(-20, height + 20)])
                    got = page.evaluate("""jobs => jobs.map(([w, h, frames, stamps, x, y]) => [webUiPhoto.hitFrame(frames, w, h, x, y), webUiPhoto.hitStamp(stamps, w, h, x, y),
                        frames.map(f => webUiPhoto.hitHandle(f.rect, w, h, x, y))])""", jobs)
                    for (width, height, frames, stamps, x, y), result in zip(jobs, got):
                        self.assertEqual(result, [w.photo_hit_frame(frames, width, height, x, y), w.photo_hit_stamp(stamps, width, height, x, y),
                                                  [w.photo_hit_handle(f['rect'], width, height, x, y) for f in frames]], (width, height, x, y))
                    sizes = [[rng.uniform(0.1, 5000), rng.uniform(0.1, 5000)] for _ in range(300)] + [[760, 280], [400.25, 300.2], [0.1, 0.1], [3000, 100], [1, 1]]
                    self.assertEqual(page.evaluate('v => v.map(([a, b]) => [webUiPhoto.exportSize(a, b), webUiPhoto.exportSize(a, b, 1.5), webUiPhoto.stampPx(a, b, 2.5), webUiPhoto.containRect(a, b, 300, 200), webUiPhoto.containRect(b, a, 300, 200)])', sizes),
                                     [[list(w.photo_export_size(a, b)), list(w.photo_export_size(a, b, 1.5)), w.photo_stamp_px(a, b, 2.5), list(w.photo_contain_rect(a, b, 300, 200)), list(w.photo_contain_rect(b, a, 300, 200))] for a, b in sizes])
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()

    def test_the_editing_state_machine_equals_pythons_step_by_step(self):
        import random
        import web_ui as w
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = photo_engine(playwright).launch()
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/photo.html')
                    rng = random.Random(33)
                    names = {'pointerDown': 'pointer_down', 'pointerMove': 'pointer_move', 'pointerUp': 'pointer_up', 'pointerCancel': 'pointer_cancel', 'setShape': 'set_shape', 'armStamp': 'arm_stamp',
                             'setColor': 'set_color', 'undo': 'undo', 'redo': 'redo', 'nudge': 'nudge', 'deleteSelectedFrame': 'delete_selected_frame', 'resetSelectedFrame': 'reset_selected_frame',
                             'setStampScale': 'set_stamp_scale', 'setImage': 'set_image'}
                    scripts = []
                    edge = [[400, 400, [['armStamp', ['🔥']], ['pointerDown', [1, 100, 100]], ['pointerMove', [1, 120, 100]], ['pointerMove', [1, 127.9, 100]], ['pointerMove', [1, 128, 100]],
                                        ['pointerMove', [1, 155.9, 100]], ['pointerMove', [1, 156, 100]], ['pointerUp', [1]]]],
                            [400, 400, [['armStamp', ['⭐']], ['pointerDown', [1, 100, 100]], ['pointerMove', [1, 103.9, 100]], ['pointerUp', [1]], ['pointerDown', [1, 200, 200]], ['pointerMove', [1, 204, 200]],
                                        ['pointerCancel', [1]], ['undo', []], ['undo', []], ['redo', []]]],
                            [400, 300, [['setShape', ['rectangle']], ['pointerDown', [1, 40, 30]], ['pointerMove', [1, 160, 120]], ['pointerUp', [1]], ['setShape', [None]],
                                        ['pointerDown', [1, 40, 30]], ['pointerMove', [1, 41, 30]], ['pointerMove', [1, 60, 50]], ['pointerUp', [1]], ['pointerDown', [2, 58, 46]], ['pointerMove', [2, 100, 100]],
                                        ['pointerUp', [2]], ['nudge', [0.5, 0.5]], ['resetSelectedFrame', []], ['undo', []], ['undo', []], ['undo', []], ['redo', []]]]]
                    scripts.extend(edge)
                    for _ in range(120):
                        width, height = rng.choice([(400, 300), (760, 280), (320, 240), (500.5, 333.25)])
                        ops = []
                        for _ in range(90):
                            kind = rng.choice(['pointerDown', 'pointerMove', 'pointerMove', 'pointerMove', 'pointerUp', 'pointerCancel', 'setShape', 'armStamp', 'setColor', 'undo', 'redo', 'nudge',
                                               'deleteSelectedFrame', 'resetSelectedFrame', 'setStampScale', 'setImage'])
                            pointer = rng.choice([1, 2])
                            x, y = rng.uniform(-20, width + 20), rng.uniform(-20, height + 20)
                            args = {'pointerDown': [pointer, x, y], 'pointerMove': [pointer, x, y], 'pointerUp': [pointer], 'pointerCancel': [pointer],
                                    'setShape': [rng.choice([None, None, 'rectangle', 'circle', 'triangle', 'star'])], 'armStamp': [rng.choice(['⭐', '🔥', ' ', '', '⭐'])],
                                    'setColor': [rng.choice([c for _, c in w.PHOTO_COLORS])], 'undo': [], 'redo': [], 'nudge': [rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2)],
                                    'deleteSelectedFrame': [], 'resetSelectedFrame': [], 'setStampScale': [rng.uniform(-1, 5)], 'setImage': [rng.choice([None, 1, 2, 3])]}[kind]
                            if kind == 'pointerMove' and ops and ops[-1][0] in ('pointerDown', 'pointerMove') and rng.random() < 0.6:
                                args = [ops[-1][1][0], ops[-1][1][1] + rng.uniform(-60, 60), ops[-1][1][2] + rng.uniform(-60, 60)] if len(ops[-1][1]) == 3 else args
                            ops.append([kind, args])
                        scripts.append([width, height, ops])
                    got = page.evaluate("""scripts => scripts.map(([w, h, ops]) => { const s = new webUiPhoto.PhotoStudio(w, h), trace = [];
                        for (const [op, args] of ops) { try { s[op](...args) } catch (e) { trace.push('error'); continue }
                          trace.push([s.state, s.history.depth, s.history.canUndo, s.history.canRedo, s.pendingEmoji]) } return trace })""", scripts)
                    steps = 0
                    for script_number, ((width, height, ops), trace) in enumerate(zip(scripts, got)):
                        s = w.PhotoStudio(width, height)
                        for step, ((op, args), seen) in enumerate(zip(ops, trace)):
                            try:
                                getattr(s, names[op])(*args)
                            except ValueError:
                                self.assertEqual(seen, 'error', (script_number, step, op, args))
                                continue
                            self.assertEqual(seen, [s.state, s.history.depth, s.history.can_undo, s.history.can_redo, s.pending_emoji], (script_number, step, op, args))
                            steps += 1
                    self.assertGreater(steps, 9000)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()

    def test_evidence_and_the_probe_pictures_equal_pythons(self):
        import io
        import web_ui as w
        from PIL import Image
        probes = w.photo_probes()
        self.assertEqual([p['id'] for p in probes], ['png', 'jpeg', 'jpeg_exif_orientation_6', 'webp_lossy', 'webp_lossless', 'webp_alpha', 'gif', 'avif', 'heic'])
        for probe in probes:                                                                # every probe is a real file, and says what it is
            data = base64.b64decode(probe['data'])
            kind = w.photo_sniff(data)['kind']
            self.assertEqual('image/' + kind, probe['mime'])
            if kind != 'heic':
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
        outcomes = {'png': 'supported', 'heic': 'unsupported_by_runtime'}
        features = {'pointerEvents': True, 'devicePixelRatio': 2}
        server, origin = self.serve_page()
        try:
            with sync_playwright() as playwright:
                browser = photo_engine(playwright).launch()
                try:
                    page = browser.new_page()
                    page.goto(origin + '/photo.html')
                    for applied in (None, True, False):
                        got = page.evaluate('([o, f, a]) => webUiPhoto.evidence({userAgent: "UA", outcomes: o, features: f, verifiedAt: "2026-11-03", exifAppliedByEngine: a})', [outcomes, features, applied])
                        self.assertEqual(got, w.photo_evidence('UA', outcomes, features, '2026-11-03', applied))
                    self.assertEqual(page.evaluate('() => webUiPhoto.evidence({})'), w.photo_evidence())
                finally:
                    browser.close()
        finally:
            server.shutdown()
        with self.assertRaises(ValueError):
            w.photo_evidence(outcomes={'png': 'works'})


class PhotoPageBrowserTests(PageCase):
    """The photo studio page in Chromium: import outcomes, upright pixels, drawing, history, export, and keeping nothing."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_python_wrapper import PHOTO_CASES, photo_file
        self.cases, self.file = PHOTO_CASES, photo_file
        from web_ui import photo_document
        self.server, self.origin = WorldBrowserTests.serve({'photo.html': photo_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.engine = self.browser.browser_type.name
        self.context = self.browser.new_context(accept_downloads=True, **photo_device(self.playwright))
        self.page = self.context.new_page()
        self.errors, self.external = [], []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('console', lambda message: self.errors.append('console: ' + message.text) if message.type == 'error' else None)
        self.page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        self.page.goto(self.origin + '/photo.html')

    def mime(self, case_id):
        return {'png': 'image/png', 'jpeg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif', 'avif': 'image/avif', 'heic': 'image/heic'}.get(self.cases[case_id]['format'], 'image/png')

    def pick(self, case_id):
        self.page.set_input_files('#photo-file', files=[{'name': case_id, 'mimeType': self.mime(case_id), 'buffer': self.file(case_id)}])
        self.page.wait_for_function("() => document.querySelector('[data-ui-photo]').dataset.photoPhase !== 'loading'")
        return self.page.eval_on_selector('[data-ui-photo]', 'b => [b.dataset.photoPhase, b.dataset.photoOutcome]')

    def stage(self):
        self.page.locator('[data-stage]').scroll_into_view_if_needed()                        # a pointer outside the viewport reaches nothing
        return self.page.locator('[data-stage]').bounding_box()

    def drag(self, a, b, steps=6):
        box = self.stage()
        self.page.mouse.move(box['x'] + a[0] * box['width'], box['y'] + a[1] * box['height'])
        self.page.mouse.down()
        self.page.mouse.move(box['x'] + b[0] * box['width'], box['y'] + b[1] * box['height'], steps=steps)
        self.page.mouse.up()

    def tap(self, at):
        box = self.stage()
        self.page.mouse.click(box['x'] + at[0] * box['width'], box['y'] + at[1] * box['height'])

    def data(self, name):
        return self.page.eval_on_selector('[data-ui-photo]', f'b => b.dataset.{name}')

    def test_import_outcomes_equal_what_flutter_measured(self):
        import web_ui as w
        for case_id, case in self.cases.items():
            expected = case['flutter_test_ci']
            if not case['data'] or expected in (None, 'not_verified'):
                continue
            with self.subTest(case_id):
                phase, outcome = self.pick(case_id)
                if case_id == 'heic_synthetic_markers_64x32':                               # a real HEIC: Chromium and Firefox have no decoder for it, Safari's engine may
                    self.assertIn(outcome, ('rejected:heicConversionFailed',) if self.engine != 'webkit' else ('rejected:heicConversionFailed', 'supported'))
                    continue
                self.assertEqual(outcome, expected)
                self.assertEqual(phase, 'success' if expected == 'supported' else 'failure')
                self.assertEqual(self.page.inner_text('[data-status]'), w.PHOTO_MESSAGES['success'] if expected == 'supported' else w.photo_failure(expected.split(':')[1])['message'])
        self.pick('png_markers_64x32')
        self.assertEqual((self.page.inner_text('[data-meta]'), self.data('photoSize'), self.data('documentSize')), ('PNG · 64 × 32', '64x32', '43x21'))
        self.pick('png_claim_10000x10000')                                                  # a refused import leaves the photo that was there
        self.assertEqual((self.page.inner_text('[data-status]'), self.data('documentSize')), (w.PHOTO_MESSAGES['tooManyPixels'], '43x21'))
        self.assertTrue(self.page.locator('[data-retry]').is_visible())
        self.page.set_input_files('#photo-file', files=[{'name': 'a.txt', 'mimeType': 'text/plain', 'buffer': self.file('png_markers_64x32')}])    # a declared type that is not an image
        self.page.wait_for_function("() => document.querySelector('[data-ui-photo]').dataset.photoPhase !== 'loading'")
        self.assertEqual(self.page.inner_text('[data-status]'), w.PHOTO_MESSAGES['unsupportedFormat'])

    def test_every_exif_orientation_is_turned_upright_like_pillow(self):
        import io
        import web_ui
        from PIL import Image, ImageOps
        quadrants = ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))
        for orientation in range(1, 9):
            case_id = f'jpeg_exif_orientation_{orientation}_markers_64x32'
            with self.subTest(orientation=orientation):
                self.assertEqual(self.pick(case_id), ['success', 'supported'])
                self.assertEqual(self.data('orientation'), str(orientation))
                with Image.open(io.BytesIO(self.file(case_id))) as original:
                    expected = ImageOps.exif_transpose(original).convert('RGB')
                ow, oh = expected.size
                self.assertEqual(self.data('documentSize'), '%dx%d' % web_ui.photo_document_size(ow, oh))
                got = self.page.evaluate("""quadrants => { const b = document.querySelector('[data-ui-photo]').photo, c = b.docs.get(b.studio.state.image).canvas, g = c.getContext('2d');
                    return quadrants.map(([fx, fy]) => Array.from(g.getImageData(Math.floor(fx * c.width), Math.floor(fy * c.height), 1, 1).data)) }""", [list(q) for q in quadrants])
                for (fx, fy), pixel in zip(quadrants, got):
                    want = expected.getpixel((int(fx * ow), int(fy * oh)))
                    for channel in range(3):
                        self.assertLessEqual(abs(pixel[channel] - want[channel]), 24, (orientation, fx, fy, pixel, want))
                    self.assertEqual(pixel[3], 255)

    def test_what_this_engine_does_to_orientation_is_measured_not_assumed(self):
        import json
        self.page.click('.ui-photo-check summary')
        self.page.click('[data-check]')
        self.page.wait_for_function("() => document.querySelector('[data-ui-photo]').dataset.check")
        report = json.loads(self.data('check'))
        self.assertIn(report['exifOrientationAppliedByEngine'], (True, False))                # measured, whatever it is: the page neutralises it, so its pixels do not depend on it
        measured = {key: value['loader_browser_canvas_adapter'] for key, value in report['outcomes'].items()}
        for probe in ('png', 'jpeg', 'jpeg_exif_orientation_6', 'webp_lossy', 'webp_lossless', 'webp_alpha', 'gif'):                  # the formats every engine reads
            self.assertEqual(measured[probe], 'supported', (self.engine, probe))
        for probe in ('avif', 'heic'):
            self.assertIn(measured[probe], ('supported', 'unsupported_by_runtime'))
        if self.engine == 'chromium':                                                       # Chromium here: exact
            self.assertEqual(report['exifOrientationAppliedByEngine'], True)
            self.assertEqual((measured['avif'], measured['heic']), ('supported', 'unsupported_by_runtime'))
        for feature in ('pointerEvents', 'touchActionNone', 'createImageBitmap', 'canvasToBlob', 'anchorDownload', 'canvas4096'):
            self.assertTrue(report['features'][feature], (self.engine, feature))
        if os.environ.get('WEBUI_EVIDENCE_DIR'):                                            # CI keeps what each engine said, as a file
            os.makedirs(os.environ['WEBUI_EVIDENCE_DIR'], exist_ok=True)
            name = self.engine + ('-' + os.environ['WEBUI_DEVICE'].replace(' ', '') if os.environ.get('WEBUI_DEVICE') else '-desktop')
            print('photo-evidence', name, json.dumps({'decoded': measured, 'exifAppliedByEngine': report['exifOrientationAppliedByEngine'],
                                                       'features': {k: v for k, v in report['features'].items() if k != 'devicePixelRatio'}}, ensure_ascii=False, sort_keys=True))   # also in the log
            with open(os.path.join(os.environ['WEBUI_EVIDENCE_DIR'], name + '.json'), 'w', encoding='utf-8') as out:
                json.dump({**report, 'environmentId': name, 'emulation': bool(os.environ.get('WEBUI_DEVICE'))}, out, indent=2, ensure_ascii=False)
        shown = json.loads(self.page.inner_text('[data-check-out]'))
        self.assertEqual((shown['schemaVersion'], shown['environmentId'], shown['entryPoint']), (2, 'web_ui_photo_studio', 'loader_browser_canvas_adapter'))
        self.assertEqual(shown, report)
        import web_ui as w
        self.assertEqual(set(shown), set(w.photo_evidence()))
        self.assertIn(shown['verifiedAt'][:2], ('20',))

    def test_drawing_moving_history_keyboard_and_stamps(self):
        page = self.page
        page.click('label[for="photo-shape-rectangle"]')
        self.drag((0.1, 0.2), (0.5, 0.7))
        self.assertEqual((self.data('frames'), self.data('depth')), ('1', '2'))              # choosing the tool is a step, so is the drag
        left, top, right, bottom = (float(v) for v in self.data('rect').split(', '))
        for got, want in zip((left, top, right, bottom), (0.1, 0.2, 0.5, 0.7)):
            self.assertAlmostEqual(got, want, delta=0.02)
        self.assertIn('shape: rectangle', page.inner_text('[data-geometry]'))
        self.assertIn('mid.top:', page.inner_text('[data-geometry]'))
        page.click('label[for="photo-shape-none"]')
        self.drag((0.3, 0.45), (0.4, 0.55))                                                  # inside the frame: it moves
        moved = [float(v) for v in self.data('rect').split(', ')]
        self.assertGreater(moved[0], left + 0.05)
        page.click('[data-undo]')
        self.assertEqual([float(v) for v in self.data('rect').split(', ')], [left, top, right, bottom])
        page.click('[data-redo]')
        self.assertEqual([float(v) for v in self.data('rect').split(', ')], moved)
        page.focus('[data-stage]')
        page.keyboard.press('ArrowRight')
        nudged = [float(v) for v in self.data('rect').split(', ')]
        self.assertAlmostEqual(nudged[0], moved[0] + 0.01, places=3)
        page.keyboard.press('Control+z')
        self.assertEqual([float(v) for v in self.data('rect').split(', ')], moved)
        page.keyboard.press('Control+Shift+z')
        self.assertAlmostEqual([float(v) for v in self.data('rect').split(', ')][0], moved[0] + 0.01, places=3)
        page.click('label[for="photo-color-#e53935"]')
        self.assertEqual(page.evaluate("() => document.querySelector('[data-ui-photo]').photo.studio.state.frames[0].color"), '#e53935')
        page.click('[data-reset]')
        self.assertEqual(self.data('rect'), '0.2000, 0.2000, 0.8000, 0.8000')
        page.click('[data-delete]')
        self.assertEqual(self.data('frames'), '0')
        self.assertEqual(page.inner_text('[data-geometry]'), 'No frame selected.')
        page.click('[data-stamp="⭐"]')                                                      # arm, then tap twice, then spray
        self.assertEqual((page.get_attribute('[data-stamp="⭐"]', 'aria-pressed'), self.data('armed')), ('true', '⭐'))
        self.tap((0.2, 0.3))
        self.tap((0.8, 0.7))
        self.assertEqual(self.data('stamps'), '2')
        before = int(self.data('depth'))
        self.drag((0.1, 0.5), (0.9, 0.5), steps=20)
        self.assertGreaterEqual(int(self.data('stamps')), 5)
        self.assertEqual(int(self.data('depth')), before + 1)                                # one spray is one undo step
        page.click('[data-undo]')
        self.assertEqual(self.data('stamps'), '2')
        page.fill('#photo-custom', 'OK')
        page.click('[data-arm]')
        self.assertEqual(self.data('armed'), 'OK')
        page.click('[data-stamp="⭐"]')
        self.assertEqual(self.data('armed'), '⭐')
        page.fill('#photo-scale', '2.5')
        self.assertEqual(page.inner_text('[data-scale-out]'), '2.5')
        label = page.get_attribute('[data-stage]', 'aria-label')
        self.assertIn('2 stamps', label)
        self.assertIn('armed', label)

    def test_export_is_a_png_of_the_photo_frames_and_stamps(self):
        import io
        import web_ui as w
        from PIL import Image
        self.assertEqual(self.pick('png_markers_64x32'), ['success', 'supported'])
        self.page.click('label[for="photo-shape-rectangle"]')
        self.drag((0.1, 0.1), (0.9, 0.9))
        self.page.click('[data-stamp="🔥"]')
        self.tap((0.5, 0.5))
        box = self.stage()
        with self.page.expect_download() as download:
            self.page.click('[data-export]')
        self.assertEqual(download.value.suggested_filename, w.PHOTO_EXPORT_NAME)
        data = open(download.value.path(), 'rb').read()
        self.assertEqual(w.photo_sniff(data)['kind'], 'png')
        ew, eh = w.photo_export_size(box['width'], box['height'])
        self.assertEqual(self.data('exportSize'), f'{ew}x{eh}')
        self.assertEqual(w.photo_header_size(data), (ew, eh))
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            rgb = image.convert('RGB')
        near = lambda a, b: all(abs(x - y) <= 6 for x, y in zip(a, b))
        left_edge = round(0.1 * ew)
        self.assertTrue(near(rgb.getpixel((int(0.25 * ew), int(0.3 * eh))), (255, 0, 0)), rgb.getpixel((int(0.25 * ew), int(0.3 * eh))))      # the photo, upright, fitted whole
        self.assertTrue(near(rgb.getpixel((int(0.75 * ew), int(0.3 * eh))), (0, 255, 0)))
        self.assertTrue(near(rgb.getpixel((int(0.25 * ew), int(0.7 * eh))), (0, 0, 255)))
        self.assertTrue(near(rgb.getpixel((int(0.75 * ew), int(0.7 * eh))), (255, 255, 0)))
        self.assertTrue(near(rgb.getpixel((left_edge, int(0.5 * eh))), (0x7e, 0x57, 0xc2)), rgb.getpixel((left_edge, int(0.5 * eh))))        # the frame's stroke, in its colour
        self.assertIn('Saved as PNG.', self.page.inner_text('[data-live]'))

    def test_a_newer_import_replaces_an_older_one_and_clearing_cancels_a_load(self):
        import base64 as b64
        a, b = b64.b64encode(self.file('png_markers_64x32')).decode(), b64.b64encode(self.file('webp_lossy_64x32')).decode()
        self.page.evaluate("""async ([a, b]) => { const bytes = s => Uint8Array.from(atob(s), c => c.charCodeAt(0)), box = document.querySelector('[data-ui-photo]').photo;
            const first = box.importBytes(bytes(a), 'image/png', 'pick'), second = box.importBytes(bytes(b), 'image/webp', 'pick'); await Promise.all([first, second]) }""", [a, b])
        self.assertEqual((self.page.inner_text('[data-meta]'), self.data('photoPhase'), self.data('depth')), ('WebP · 64 × 32', 'success', '1'))
        self.assertEqual(self.page.evaluate("() => document.querySelector('[data-ui-photo]').photo.docs.size"), 1)
        self.page.evaluate("""async a => { const bytes = s => Uint8Array.from(atob(s), c => c.charCodeAt(0)), box = document.querySelector('[data-ui-photo]').photo;
            window.__pending = box.importBytes(bytes(a), 'image/png', 'pick'); document.querySelector('[data-clear]').click(); await window.__pending }""", a)
        self.assertEqual((self.data('photoPhase'), self.page.inner_text('[data-status]')), ('superseded', 'A newer import replaced this load.'))
        self.assertEqual(self.page.evaluate("() => document.querySelector('[data-ui-photo]').photo.studio.state.image"), None)
        self.page.click('[data-undo]')                                                      # undo brings the photo back, from history
        self.assertEqual(self.page.evaluate("() => document.querySelector('[data-ui-photo]').photo.studio.state.image !== null"), True)

    def test_the_stage_follows_the_window_width_without_observer_loops(self):
        """Fitting the canvas changes the page's height; the resize observer must not be notified again in the same frame (WebKit reports that loop as a page error, which tearDown rejects)."""
        self.assertEqual(self.pick('png_markers_64x32'), ['success', 'supported'])
        for width in (800, 520, 1000, 360, 800):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.wait_for_function("w => { const s = document.querySelector('[data-stage]'); return Math.abs(s.getBoundingClientRect().width - s.parentElement.clientWidth) < 1 }", arg=width)
            self.page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            box = self.stage()
            self.assertAlmostEqual(box['height'] / box['width'], 21 / 43, delta=0.01)             # the picture's shape (the stored 43 x 21)
        self.assertEqual(self.page.evaluate("() => { const s = document.querySelector('[data-stage]'); return Math.round(s.width / parseFloat(s.style.width)) }"), self.page.evaluate('() => Math.round(devicePixelRatio)'))

    def test_touch_drags_draw_a_frame_and_do_not_scroll_the_page(self):
        """On a phone the finger must edit the canvas, not scroll the page: pointer events plus ``touch-action: none`` (Chromium's Pixel emulation drags with CDP; WebKit's iPhone
        emulation taps; a device is a separate claim)."""
        if self.engine == 'firefox':
            self.skipTest('Playwright has no touch emulation for Firefox')
        if self.engine == 'webkit':
            return self.touch_taps_in_iphone_emulation()
        context = self.browser.new_context(**self.playwright.devices['Pixel 7'])
        try:
            page = context.new_page()
            page.on('pageerror', lambda error: self.errors.append(str(error)))
            page.goto(self.origin + '/photo.html')
            page.tap('label[for="photo-shape-rectangle"]')
            page.locator('[data-stage]').scroll_into_view_if_needed()
            box = page.locator('[data-stage]').bounding_box()
            self.assertLessEqual(box['width'], 412)                                         # laid out for the phone, not a desktop
            scroll = page.evaluate('() => window.scrollY')
            cdp = context.new_cdp_session(page)
            touch = lambda kind, fx=None, fy=None: cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [] if fx is None else [{'x': box['x'] + fx * box['width'], 'y': box['y'] + fy * box['height']}]})
            touch('touchStart', 0.2, 0.2)
            for step in range(1, 9):
                touch('touchMove', 0.2 + step * 0.06, 0.2 + step * 0.05)
            touch('touchEnd')
            self.assertEqual(page.eval_on_selector('[data-ui-photo]', 'b => b.dataset.frames'), '1')
            left, top, right, bottom = (float(v) for v in page.eval_on_selector('[data-ui-photo]', 'b => b.dataset.rect').split(', '))
            for got, want in zip((left, top, right, bottom), (0.2, 0.2, 0.68, 0.6)):
                self.assertAlmostEqual(got, want, delta=0.03)
            self.assertEqual(page.evaluate('() => window.scrollY'), scroll)                  # the drag did not move the page
            page.click('[data-stamp="⭐"]')                                                    # (a tap right after raw CDP touches gets no click from Chromium's recognizer: a harness matter)
            page.locator('[data-stage]').scroll_into_view_if_needed()
            box = page.locator('[data-stage]').bounding_box()
            page.touchscreen.tap(box['x'] + 0.8 * box['width'], box['y'] + 0.8 * box['height'])
            self.assertEqual(page.eval_on_selector('[data-ui-photo]', 'b => b.dataset.stamps'), '1')
        finally:
            context.close()

    def touch_taps_in_iphone_emulation(self):
        context = self.browser.new_context(**{k: v for k, v in self.playwright.devices['iPhone 13'].items() if k != 'default_browser_type'})
        try:
            page = context.new_page()
            page.on('pageerror', lambda error: self.errors.append(str(error)))
            page.goto(self.origin + '/photo.html')
            page.tap('[data-stamp="⭐"]')
            self.assertEqual(page.eval_on_selector('[data-ui-photo]', 'b => b.dataset.armed'), '⭐')
            page.locator('[data-stage]').scroll_into_view_if_needed()
            box = page.locator('[data-stage]').bounding_box()
            self.assertLessEqual(box['width'], 390)
            scroll = page.evaluate('() => window.scrollY')
            for fx, fy in ((0.3, 0.4), (0.7, 0.6)):
                page.touchscreen.tap(box['x'] + fx * box['width'], box['y'] + fy * box['height'])
            self.assertEqual(page.eval_on_selector('[data-ui-photo]', 'b => b.dataset.stamps'), '2')
            self.assertEqual(page.evaluate('() => window.scrollY'), scroll)
        finally:
            context.close()

    def synthetic_events_work(self):
        """Whether this engine lets a page build paste and drop events that carry files (some ignore ``clipboardData`` / ``dataTransfer`` in the constructor)."""
        return self.page.evaluate("""() => { try { const dt = new DataTransfer(); dt.items.add(new File(['x'], 'x.png', {type: 'image/png'}));
            return new ClipboardEvent('paste', {clipboardData: dt}).clipboardData === dt && new DragEvent('drop', {dataTransfer: dt}).dataTransfer === dt } catch (e) { return false } }""")

    def test_paste_and_drop_take_images_and_the_page_keeps_nothing(self):
        import base64 as b64
        import web_ui as w
        if not self.synthetic_events_work():
            self.skipTest('this engine ignores clipboardData / dataTransfer on events a page builds; real paste and drop are Layer 3 (a device)')
        png = b64.b64encode(self.file('png_markers_64x32')).decode()
        script = """([png, how]) => { const bytes = Uint8Array.from(atob(png), c => c.charCodeAt(0)), dt = new DataTransfer(); dt.items.add(new File([bytes], 'x.png', {type: 'image/png'}));
            const target = document.querySelector('[data-ui-photo]');
            if (how === 'paste') document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
            else target.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true})) }"""
        self.page.evaluate(script, [png, 'paste'])
        self.page.wait_for_function("() => document.querySelector('[data-ui-photo]').dataset.photoPhase === 'success'")
        self.assertEqual((self.data('source'), self.page.inner_text('[data-meta]')), ('paste', 'PNG · 64 × 32'))
        self.page.click('[data-clear]')
        self.page.evaluate(script, [png, 'drop'])
        self.page.wait_for_function("() => document.querySelector('[data-ui-photo]').dataset.photoPhase === 'success'")
        self.assertEqual(self.data('source'), 'insert')
        self.page.evaluate("() => document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: new DataTransfer(), bubbles: true, cancelable: true}))")
        self.assertEqual(self.page.inner_text('[data-status]'), w.PHOTO_MESSAGES['noClipboardImage'])
        self.page.fill('#photo-custom', 'x')                                                # pasting into a text box is the text box's business
        before = self.page.inner_text('[data-status]')
        self.page.evaluate("() => { const e = new ClipboardEvent('paste', {clipboardData: new DataTransfer(), bubbles: true, cancelable: true}); document.querySelector('#photo-custom').dispatchEvent(e) }")
        self.assertEqual(self.page.inner_text('[data-status]'), before)
        self.assertEqual(self.page.evaluate("() => [localStorage.length, sessionStorage.length, document.cookie]"), [0, 0, ''])
        self.assertEqual(self.page.evaluate("() => [...document.querySelectorAll('a[href]')].length"), 0)



class BtkAdapterBrowserTests(unittest.TestCase):
    """Each adapter against its page, with browser-test-kit's own checks: one element per selector, all visible inside the screen without clipping or overlap, and the click
    changes exactly what the adapter says. (The probe itself runs in the platform-matrix workflow, on every engine and profile.)"""

    LAYOUT = """cfg => { const failed = [], boxes = [], de = document.documentElement;
        if (de.scrollWidth > de.clientWidth + .5) failed.push('horizontal_overflow');
        for (const selector of cfg.elements) { const found = document.querySelectorAll(selector);
          if (found.length !== 1) { failed.push('missing_or_ambiguous:' + selector + ':' + found.length); continue }
          const e = found[0], r = e.getBoundingClientRect(), s = getComputedStyle(e);
          if (r.width <= 0 || r.height <= 0 || s.visibility === 'hidden' || s.display === 'none') failed.push('invisible:' + selector);
          if (r.left < -.5 || r.right > innerWidth + .5 || r.top < -.5 || r.bottom > innerHeight + .5) failed.push('outside:' + selector);
          if (e.scrollWidth > e.clientWidth + .5) failed.push('clipped:' + selector); boxes.push({selector, x: r.x, y: r.y, width: r.width, height: r.height}) }
        for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) { const a = boxes[i], b = boxes[j];
          if (Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > .5 && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > .5) failed.push('overlap:' + a.selector + ':' + b.selector) }
        const t = document.querySelector(cfg.click.target), r = t.getBoundingClientRect(), top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        if (!top || !(t === top || t.contains(top))) failed.push('occluded:' + cfg.click.target);
        return failed }"""

    def test_every_adapter_fits_its_page_and_its_click_does_what_it_says(self):
        import web_ui
        pages = web_ui.example_pages()
        server, origin = WorldBrowserTests.serve({web_ui.BTK_ADAPTERS[i]['page']: pages['examples/' + web_ui.BTK_ADAPTERS[i]['page']] for i in web_ui.BTK_ADAPTERS})
        try:
            with sync_playwright() as playwright:
                browser = photo_engine(playwright).launch()
                try:
                    for adapter_id in sorted(web_ui.BTK_ADAPTERS):
                        for width, height in ((1280, 800), (412, 839), (390, 664), (320, 664)):
                            with self.subTest(adapter=adapter_id, viewport=(width, height)):
                                config = web_ui.btk_adapter(adapter_id, web_ui.btk_adapter_url(web_ui.BTK_ADAPTERS[adapter_id], origin + '/'))
                                page = browser.new_page(viewport={'width': width, 'height': height})
                                errors = []
                                page.on('pageerror', lambda error: errors.append(str(error)))
                                try:
                                    page.goto(config['url'])
                                    page.wait_for_timeout(100)
                                    self.assertEqual(page.evaluate(self.LAYOUT, config), [])
                                    click = config['click']
                                    read = lambda: page.locator(click['observe']).inner_text() if click['attribute'] == 'textContent' else page.locator(click['observe']).get_attribute(click['attribute'])
                                    self.assertEqual(read(), click['before'])
                                    box = page.locator(click['target']).bounding_box()
                                    page.mouse.click(int(box['x'] + box['width'] / 2), int(box['y'] + box['height'] / 2))
                                    page.wait_for_timeout(150)
                                    self.assertEqual(read(), click['after'])
                                    self.assertEqual(errors, [])
                                finally:
                                    page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()


class ClipboardBrowserTests(PageCase):
    """The clipboard loops in Chromium: the read order, error codes and text rules equal Python's (and so Ironmate's and Dart's), and the shelf, the temporary clipboard and the
    photo studio use them."""

    DOUBLE = """
        const PNG = %s;
        const padded = n => { const png = atob(PNG), bytes = new Uint8Array(n); for (let i = 0; i < png.length; i++) bytes[i] = png.charCodeAt(i);
          let out = ''; for (let i = 0; i < n; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)); return btoa(out) };
        const resolve = v => typeof v === 'string' ? v.replace(/@pad:(\\d+)/g, (m, n) => padded(+n)) : Array.isArray(v) ? v.map(resolve) : v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, resolve(x)])) : v;
        const makeClip = config => { const calls = {read: 0, readText: 0, getType: 0, arrayBuffer: 0}; if (config.absent) return {clip: undefined, calls}; const fail = name => { throw new DOMException('injected', name) }, clip = {};
          if (!config.noText) clip.readText = async () => { calls.readText++; if (config.textError) fail(config.textError); return config.text || '' };
          if (!config.noRead) clip.read = async () => { calls.read++; if (config.readError) fail(config.readError);
            return (config.items || []).map(item => ({types: item.formats.map(f => f.type), getType: async type => { calls.getType++; const f = item.formats.find(f => f.type === type); if (f.error) fail(f.error);
              const blob = new Blob([Uint8Array.from(atob(f.base64 || ''), c => c.charCodeAt(0))], {type}); if (f.oversized) Object.defineProperty(blob, 'size', {value: 32 * 1024 * 1024 + 1});
              const read = blob.arrayBuffer.bind(blob); blob.arrayBuffer = () => { calls.arrayBuffer++; return read() }; return blob }})) };
          return {clip, calls} };
        const importer = async (bytes, mime) => { if (webUiShelf.sniffImageMime(bytes) !== mime) throw new Error('mime'); const url = URL.createObjectURL(new Blob([bytes], {type: mime}));
          try { const img = new Image(); img.src = url; await img.decode(); if (img.naturalWidth * img.naturalHeight > 4 * 1024 * 1024) throw new Error('4mp'); return true } finally { URL.revokeObjectURL(url) } };
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        import test_python_wrapper as t
        self.t = t
        from web_ui import shelf_document, photo_document
        self.server, self.origin = WorldBrowserTests.serve({'shelf.html': shelf_document(), 'photo.html': photo_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 800, 'height': 900}, accept_downloads=True)
        self.errors, self.external = [], []

    def page(self, name):
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        page.goto(self.origin + '/' + name)
        return page

    def test_the_read_order_and_error_codes_equal_pythons_on_ironmates_scenarios(self):
        t = self.t
        page = self.page('shelf.html')
        scenarios = t.clip_scenarios()
        script = "async ([scenarios, png]) => { " + (self.DOUBLE % json.dumps(t.CLIP_IMAGE)) + """
            const out = []; for (const [name, raw] of scenarios) { const config = resolve(raw), {clip, calls} = makeClip(config), result = await webUiShelf.clipboardPick(clip, importer); out.push([name, result, calls]) } return out }"""
        got = page.evaluate(script, [[[name, config] for name, config, _ in scenarios], t.CLIP_IMAGE])
        for (name, config, code), (seen_name, result, calls) in zip(scenarios, got):
            python_clip = None if config.get('absent') else t.ClipDouble(t.clip_resolve(config))
            expected = web_ui_module().clipboard_pick(python_clip, t.clip_importer)
            expected = {k: v for k, v in expected.items()}
            self.assertEqual(seen_name, name)
            self.assertEqual({k: result[k] for k in expected}, expected, name)
            if python_clip is not None:
                reads = sum(blob.read_calls for item in python_clip.items for blob in item.blobs)
                self.assertEqual((calls['read'], calls['readText'], calls['getType'], calls['arrayBuffer']), (python_clip.calls['read'], python_clip.calls['readText'], python_clip.calls['getType'], reads), name)
            if code:
                self.assertEqual(result['code'], code, name)

    def test_shelf_mode_and_limits_equal_pythons(self):
        t = self.t
        w = web_ui_module()
        page = self.page('shelf.html')
        configs = [{"text": "  a memo \n"}, {"text": "data:image/png;base64,!!!", "items": [t.clip_binary()]}, {"text": t.CLIP_URI}, {"text": "memo", "items": [t.clip_binary()]}, {"textError": "NotAllowedError", "items": [t.clip_binary()]},
                   {"text": "memo", "readError": "NotAllowedError"}, {"text": "memo", "items": [t.clip_binary(t.CLIP_IMAGE, "image/jpeg")]}, {"textError": "NotAllowedError", "readError": "NotAllowedError"}, {}, {"noText": True, "noRead": True},
                   {"text": "memo", "noRead": True}, {"noText": True, "items": [t.clip_binary()]}]
        script = "async ([configs, png, limits]) => { " + (self.DOUBLE % json.dumps(t.CLIP_IMAGE)) + """
            const out = []; for (const config of configs) for (const limit of limits) { const {clip} = makeClip(config); out.push(await webUiShelf.clipboardPick(clip, importer, 'shelf', limit)) } return out }"""
        limits = [32 * 1024 * 1024, 0, 60, len(base64.b64decode(t.CLIP_IMAGE))]
        got = page.evaluate(script, [configs, t.CLIP_IMAGE, limits])
        index = 0
        for config in configs:
            for limit in limits:
                clip = t.ClipDouble(config)
                expected = w.clipboard_pick(clip, t.clip_importer, 'shelf', limit)
                self.assertEqual({k: got[index][k] for k in expected}, expected, (config, limit))
                index += 1

    def test_text_rules_equal_pythons(self):
        import random
        import re
        w = web_ui_module()
        t = self.t
        page = self.page('shelf.html')
        rng = random.Random(14)
        texts = ['', ' ', 'memo', t.CLIP_IMAGE, t.CLIP_URI, t.CLIP_IMAGE + '=', ' \ufeff' + t.CLIP_URI + '\n', 'DATA:IMAGE/PNG;charset=utf-8;BASE64,' + t.CLIP_IMAGE, 'data:image/png;base64,!!!', 'data:image/gif;base64,R0lGODlh', 'data:text/plain;base64,aGk=',
                 'data:image/png,abc', 'data:image', 'data:imagex', base64.b64encode(b'ordinary text, not an image at all, just long enough').decode(), 'iVBORw0KGgo' * 3, '/9j/' * 8, 'UklGRg' * 4,
                 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==', 'x' * 100] + t.shelf_fuzz_texts()[:200]
        got = page.evaluate("texts => texts.map(t => { try { return {ok: webUiShelf.clipboardTextImage(t)} } catch (e) { return {error: e.code, category: e.category} } })", texts)
        for text, result in zip(texts, got):
            try:
                expected = {'ok': w.clipboard_text_image(text)}
            except w.ClipboardError as error:
                expected = {'error': error.code, 'category': error.category}
            self.assertEqual(result, expected, text[:60])
        # the temporary clipboard: seeded sequences of texts, one emoji or surrogate among them
        words = ['one', 'two', 'three', '', '😀', '@rep:x:100000', '@rep:x:100001', '@rep:😀:50000', '@rep:😀:50001', 'é', 'one']          # long texts are named, then built on both sides
        runs = [[rng.choice(words + [f'entry {rng.randrange(60)}']) for _ in range(90)] for _ in range(20)]
        runs.append([f'entry {i}' for i in range(45)] + ['entry 20', 'entry 44', 'entry 3', 'entry 30'])        # past the 30-entry limit, then repeats from inside and outside it
        expand = lambda s: re.sub(r"@rep:(.):(\d+)", lambda m: m.group(1) * int(m.group(2)), s)
        got = page.evaluate("""runs => runs.map(run => { let entries = [], trace = []; for (const raw of run) { const text = raw.replace(/@rep:(.|..):(\\d+)/gu, (m, u, n) => u.repeat(+n));
            const [next, outcome] = webUiShelf.sessionClipSave(entries, text); entries = next; trace.push([outcome, entries.length, entries[0] === undefined ? null : entries[0].length]) } return trace })""", runs)
        for run, trace in zip(runs, got):
            entries, expected = [], []
            for text in map(expand, run):
                entries, outcome = w.session_clip_save(entries, text)
                expected.append([outcome, len(entries), None if not entries else w.utf16_length(entries[0])])
            self.assertEqual(trace, expected)
        units = lambda s: list(__import__('struct').unpack('<%dH' % (len(s.encode('utf-16-le', 'surrogatepass')) // 2), s.encode('utf-16-le', 'surrogatepass')))
        samples = ['', 'a', 'é', 'あ', '😀', '\ud800', 'x\udc00y', 'aé あ😀', '\ud83d', '😀\ud83d']
        got = page.evaluate("samples => samples.map(u => webUiShelf.shelfTextSize(String.fromCharCode(...u)))", [units(s) for s in samples])
        self.assertEqual(got, [w.shelf_text_size(s) for s in samples])
        rooms = [[c, u, s] for c in (0, 19, 20, 25) for u in (0, 100, w.SHELF_MAX_TOTAL_BYTES - 5, w.SHELF_MAX_TOTAL_BYTES) for s in (0, 5, 6, w.SHELF_MAX_TOTAL_BYTES)]
        self.assertEqual(page.evaluate("v => v.map(a => webUiShelf.shelfRoom(...a))", rooms), [w.shelf_room(*a) for a in rooms])
        blobs = [w.photo_png(3, 2, bytes(range(24))), w.photo_png(1, 1), b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 8, b'GIF89a', b'', b'\x89PNG\r\n\x1a\n']
        for data in blobs:
            for as_uri in (True, False):
                try:
                    expected = w.png_base64_text(data, as_uri)
                except ValueError:
                    expected = 'error'
                self.assertEqual(page.evaluate("([d, u]) => { try { return webUiShelf.pngBase64Text(Uint8Array.from(d), u) } catch (e) { return 'error' } }", [list(data), as_uri]), expected)

    @staticmethod
    def press(page, selector, root='[data-ui-shelf]'):
        """Click and wait until the page has finished the read that click started."""
        page.click(selector)
        page.wait_for_function("root => !document.querySelector(root).hasAttribute('data-busy')", arg=root, timeout=120000)

    def stub_clipboard(self, page, text='', reads=None):
        """Replace the page's clipboard with one that records what is written and answers reads from ``text`` and ``reads``."""
        page.evaluate("""([text, items]) => { window.__written = []; Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
            writeText: async t => { window.__written.push(t) }, readText: async () => { if (text === null) throw new DOMException('denied', 'NotAllowedError'); return text },
            read: async () => items === null ? (() => { throw new DOMException('denied', 'NotAllowedError') })() : items.map(it => ({types: [it.type], getType: async () => new Blob([Uint8Array.from(atob(it.base64), c => c.charCodeAt(0))], {type: it.type})})) }}) }""",
                      [text, reads if reads is None else reads])

    def test_the_temporary_clipboard_page(self):
        page = self.page('shelf.html')
        entries = lambda: page.evaluate("() => document.querySelector('[data-ui-tempclip]').tempclip.entries")
        status = lambda: page.inner_text('[data-tc-status]')
        self.assertEqual((status(), page.is_visible('[data-tc-empty]'), page.is_disabled('[data-tc-clear]')), ('', True, True))
        for text in ('one', 'two', 'one'):
            page.fill('#tempclip-input', text)
            page.click('[data-tc-save-text]')
        self.assertEqual((entries(), status(), page.input_value('#tempclip-input')), (['one', 'two'], 'Saved to temporary clipboard', ''))
        page.click('[data-tc-save-text]')                                                      # nothing typed: nothing to save
        self.assertEqual((status(), entries()), ('No copied text to save', ['one', 'two']))
        self.stub_clipboard(page, 'Copied before opening menu')
        page.click('[data-tc-save]')
        self.assertEqual(entries(), ['Copied before opening menu', 'one', 'two'])
        page.click('[data-tc-list] li:nth-child(2) button')
        self.assertEqual((page.evaluate('() => window.__written'), status()), (['one'], 'Copied to system clipboard'))
        self.stub_clipboard(page, 'x' * 100001)
        page.click('[data-tc-save]')
        self.assertEqual((status(), len(entries())), ('Text is too large to save', 3))
        self.stub_clipboard(page, None)                                                        # reading is refused
        page.click('[data-tc-save]')
        self.assertEqual(status(), 'Cannot read system clipboard')
        page.evaluate("() => { Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async () => { throw new DOMException('no', 'NotAllowedError') }}}) }")
        page.click('[data-tc-list] li:first-child button')
        self.assertEqual(status(), 'Cannot copy to system clipboard')
        for number in range(35):
            page.fill('#tempclip-input', f'entry {number}')
            page.click('[data-tc-save-text]')
        self.assertEqual((len(entries()), entries()[0], entries()[-1], page.get_attribute('[data-ui-tempclip]', 'data-entries')), (30, 'entry 34', 'entry 5', '30'))
        self.assertEqual(page.get_attribute('[data-tc-list] li:first-child button', 'aria-label'), 'Copy saved text: entry 34')
        page.click('[data-tc-clear]')
        self.assertEqual((entries(), status(), page.is_visible('[data-tc-empty]')), ([], 'Temporary clipboard cleared', True))
        self.assertEqual(page.evaluate('() => [localStorage.length, sessionStorage.length, document.cookie]'), [0, 0, ''])         # nothing is kept anywhere

    def test_the_shelf_reads_the_clipboard_and_keeps_its_item_limit(self):
        t = self.t
        w = web_ui_module()
        page = self.page('shelf.html')
        status = lambda: page.inner_text('[data-shelf-status]')
        count = lambda: int(page.get_attribute('[data-ui-shelf]', 'data-items'))
        self.stub_clipboard(page, 'a note to keep')
        self.press(page, '[data-shelf-paste]')
        self.assertEqual((count(), status()), (1, 'Added.'))
        self.stub_clipboard(page, '', [{'type': 'image/png', 'base64': t.CLIP_IMAGE}])
        self.press(page, '[data-shelf-paste]')
        self.assertEqual((count(), status(), page.locator('[data-kind="image"]').count()), (2, 'Image added (png, %d bytes).' % len(base64.b64decode(t.CLIP_IMAGE)), 1))
        self.stub_clipboard(page, 'data:image/png;base64,!!!')
        self.press(page, '[data-shelf-paste]')
        self.assertEqual((count(), status()), (3, 'Added as text: it looked like an image but was refused (bad_base64).'))
        self.stub_clipboard(page, None, None)
        self.press(page, '[data-shelf-paste]')
        self.assertEqual((count(), status()), (3, w.CLIPBOARD_MESSAGES['clipboard-denied']))
        self.stub_clipboard(page, '', [{'type': 'image/png', 'base64': base64.b64encode(b'not a png').decode()}])
        self.press(page, '[data-shelf-paste]')
        self.assertEqual((count(), status()), (3, w.CLIPBOARD_MESSAGES['clipboard-invalid-image']))
        self.stub_clipboard(page, '', [])
        self.press(page, '[data-shelf-paste]')
        self.assertEqual(status(), w.CLIPBOARD_MESSAGES['clipboard-no-image'])
        # the item limit
        for number in range(20 - 3):
            page.fill('#shelf-input', f'item {number}')
            page.click('[data-shelf-add]')
        self.assertEqual(count(), 20)
        page.fill('#shelf-input', 'one too many')
        page.click('[data-shelf-add]')
        self.assertEqual((count(), status(), page.input_value('#shelf-input')), (20, 'The shelf holds at most 20 items.', 'one too many'))
        page.click('[data-shelf-clear]')
        self.assertEqual(count(), 0)
        # clearing while the clipboard is being read drops that read
        page.evaluate("""() => { window.__release = null; Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {readText: () => new Promise(r => { window.__release = () => r('late text') })}}) }""")
        page.click('[data-shelf-paste]')
        page.click('[data-shelf-clear]')
        page.evaluate('() => window.__release()')
        page.wait_for_function("() => document.querySelector('[data-shelf-status]').textContent.includes('cleared while')")
        self.assertEqual(count(), 0)

    def synthetic_events_work(self, page):
        """Whether this engine lets a page build paste and drop events that carry files (some ignore ``clipboardData`` / ``dataTransfer`` in the constructor)."""
        return page.evaluate("""() => { try { const dt = new DataTransfer(); dt.items.add(new File(['x'], 'x.png', {type: 'image/png'}));
            return new ClipboardEvent('paste', {clipboardData: dt}).clipboardData === dt && new DragEvent('drop', {dataTransfer: dt}).dataTransfer === dt } catch (e) { return false } }""")

    def test_the_shelf_takes_image_files_by_paste_and_drop_and_keeps_its_budget(self):
        t = self.t
        page = self.page('shelf.html')
        if not self.synthetic_events_work(page):
            self.skipTest('this engine ignores clipboardData / dataTransfer on events a page builds; real paste and drop are Layer 3 (a device)')
        status = lambda: page.inner_text('[data-shelf-status]')
        count = lambda: int(page.get_attribute('[data-ui-shelf]', 'data-items'))
        # images arrive by paste and by drop, are checked against their bytes, and share a 32 MiB budget
        script = """async ([png, how, size, type]) => { const bytes = new Uint8Array(size), head = Uint8Array.from(atob(png), c => c.charCodeAt(0)); bytes.set(head);
            const dt = new DataTransfer(); dt.items.add(new File([bytes], 'x.bin', {type})); const box = document.querySelector('[data-ui-shelf]');
            if (how === 'paste') document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); else box.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true})) }"""
        page.evaluate(script, [t.CLIP_IMAGE, 'paste', 4096, 'image/png'])
        page.wait_for_function("() => document.querySelector('[data-ui-shelf]').dataset.items === '1'")
        page.evaluate(script, [t.CLIP_IMAGE, 'drop', 4096, 'image/png'])
        page.wait_for_function("() => document.querySelector('[data-ui-shelf]').dataset.items === '2'")
        page.evaluate(script, [t.CLIP_IMAGE, 'paste', 4096, 'image/jpeg'])
        page.wait_for_function("() => document.querySelector('[data-shelf-status]').textContent.includes('does not match')")
        page.evaluate(script, [base64.b64encode(b'GIF89a').decode(), 'drop', 64, 'image/png'])
        page.wait_for_function("() => document.querySelector('[data-shelf-status]').textContent.includes('not a PNG, JPEG or WebP')")
        self.assertEqual(count(), 2)
        page.click('[data-shelf-clear]')
        half = 16 * 1024 * 1024
        for expected in (1, 2):
            page.evaluate(script, [t.CLIP_IMAGE, 'paste', half, 'image/png'])
            page.wait_for_function("n => document.querySelector('[data-ui-shelf]').dataset.items === String(n)", arg=expected, timeout=60000)
        self.assertEqual(page.get_attribute('[data-ui-shelf]', 'data-bytes'), str(2 * half))
        page.fill('#shelf-input', 'a')
        page.click('[data-shelf-add]')
        self.assertEqual((count(), status()), (2, 'The shelf as a whole must stay within 32 MiB.'))
        page.evaluate(script, [t.CLIP_IMAGE, 'paste', 4096, 'image/png'])
        page.wait_for_function("() => document.querySelector('[data-shelf-status]').textContent.includes('32 MiB')")
        self.assertEqual(count(), 2)
        page.click('[data-shelf-clear]')

    def test_the_photo_page_reads_the_clipboard_and_hands_a_png_back_as_base64(self):
        import io
        t = self.t
        w = web_ui_module()
        from PIL import Image
        photo = self.page('photo.html')
        status = lambda p: p.inner_text('[data-status]')
        phase = lambda p: p.get_attribute('[data-ui-photo]', 'data-photo-phase')
        self.stub_clipboard(photo, t.CLIP_URI)
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        photo.wait_for_function("() => document.querySelector('[data-ui-photo]').dataset.photoPhase === 'success'")
        self.assertEqual((photo.get_attribute('[data-ui-photo]', 'data-source'), photo.inner_text('[data-meta]')), ('paste', 'PNG · 3 × 1'))
        self.stub_clipboard(photo, '', [{'type': 'image/png', 'base64': base64.b64encode(t.clip_png(5, 4, [9, 8, 7, 255])).decode()}])
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        photo.wait_for_function("() => document.querySelector('[data-meta]').textContent === 'PNG · 5 × 4'")
        self.stub_clipboard(photo, None, None)
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        self.assertEqual((status(photo), photo.is_visible('[data-retry]')), (w.CLIPBOARD_MESSAGES['clipboard-denied'], True))
        self.stub_clipboard(photo, 'data:image/png;base64,!!!')
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        self.assertEqual(status(photo), w.CLIPBOARD_MESSAGES['clipboard-invalid-image'])
        truncated = t.photo_file('png_truncated')
        self.stub_clipboard(photo, '', [{'type': 'image/png', 'base64': base64.b64encode(truncated).decode()}])
        self.press(photo, '[data-paste]', '[data-ui-photo]')                                                         # the page's own reason is kept: this PNG stops short
        photo.wait_for_function("() => document.querySelector('[data-status]').textContent === 'That image format could not be decoded.'")
        self.assertEqual(phase(photo), 'failure')
        self.stub_clipboard(photo, '', [])
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        self.assertEqual(status(photo), w.CLIPBOARD_MESSAGES['clipboard-no-image'])
        # the whole loop: draw, export as Base64, put it on the shelf, copy it back from there, paste it into the photo page
        self.stub_clipboard(photo, t.CLIP_URI)
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        photo.wait_for_function("() => document.querySelector('[data-meta]').textContent === 'PNG · 3 × 1'")
        photo.click('label[for="photo-shape-rectangle"]')
        box = photo.locator('[data-stage]').bounding_box()
        photo.mouse.move(box['x'] + 0.2 * box['width'], box['y'] + 0.2 * box['height'])
        photo.mouse.down()
        photo.mouse.move(box['x'] + 0.8 * box['width'], box['y'] + 0.8 * box['height'], steps=5)
        photo.mouse.up()
        photo.evaluate("() => { window.__written = [] }")
        photo.click('[data-copy-b64-uri]')
        photo.wait_for_function('() => window.__written.length === 1')
        as_uri = photo.evaluate('() => window.__written[0]')
        photo.click('[data-copy-b64]')
        photo.wait_for_function('() => window.__written.length === 2')
        plain = photo.evaluate('() => window.__written[1]')
        self.assertEqual((as_uri.startswith('data:image/png;base64,'), as_uri.split(',', 1)[1] == plain), (True, True))
        self.assertIn('characters', photo.inner_text('[data-live]'))
        back = w.decode_image_text(as_uri)
        self.assertTrue(back['ok'])
        with Image.open(io.BytesIO(base64.b64decode(back['data']))) as image:
            image.load()
            ew, eh = w.photo_export_size(box['width'], box['height'])
            self.assertEqual(image.size, (ew, eh))
        shelf = self.page('shelf.html')
        shelf.fill('#shelf-input', as_uri)
        shelf.click('[data-shelf-add]')
        self.assertEqual((shelf.get_attribute('[data-ui-shelf]', 'data-items'), shelf.locator('[data-kind="image"]').count()), ('1', 1))
        self.stub_clipboard(shelf, '', [])
        shelf.click('[data-kind="image"] button[data-act="copy"]')
        shelf.wait_for_function('() => window.__written.length === 1')
        shelf_text = shelf.evaluate('() => window.__written[0]')
        self.assertEqual(shelf_text, as_uri)                                                  # the shelf gives back exactly what it was given
        self.stub_clipboard(photo, shelf_text)
        self.press(photo, '[data-paste]', '[data-ui-photo]')
        photo.wait_for_function("(size) => document.querySelector('[data-meta]').textContent === 'PNG · ' + size", arg=f'{ew} × {eh}')
        self.assertEqual(phase(photo), 'success')


def web_ui_module():
    import web_ui
    return web_ui



class PlaygroundBrowserTests(PageCase):
    """The playground in a real browser: the counter, the hold-to-repeat button and the irony card equal Python's rules, and the page behaves like the Dart widgets did."""

    SEED = 7

    def setUp(self):
        from web_ui import playground_document
        html = playground_document().replace('data-ui-play ', f'data-ui-play data-play-seed="{self.SEED}" ', 1)
        self.server, self.origin = WorldBrowserTests.serve({'play.html': html})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 800, 'height': 1700})
        self.errors, self.external = [], []

    def page(self, clock=False):
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        if clock:
            page.clock.install()
            # Freeze real time before navigation; run_for alone still lets wall time advance.
            page.clock.pause_at(page.evaluate("Date.now() + 1000"))
        page.goto(self.origin + '/play.html')
        return page

    def test_the_pages_rules_equal_pythons(self):
        w = web_ui_module()
        rng = random.Random(20261103)
        page = self.page()
        actions = []
        for _ in range(60):
            run = []
            for _ in range(rng.randint(1, 80)):
                kind = rng.choice(['increment', 'decrement', 'change', 'restore', 'undo', 'reset', 'step', 'step'])
                run.append([kind, rng.choice([1, 5, 10, 2, 0, -3]) if kind == 'step' else rng.randint(-150, 150) if kind in ('change', 'restore') else None])
            actions.append(run)
        got = page.evaluate("""runs => runs.map(run => { let s = webUiPlayground.counterState(); const seen = [s];
            for (const [kind, value] of run) { s = webUiPlayground.counterApply(s, kind, value === null ? undefined : value); seen.push(s) } return seen })""", actions)
        for run, seen in zip(actions, got):
            state, expected = w.counter_state(), [w.counter_state()]
            for kind, value in run:
                state = w.counter_apply(state, kind, value)
                expected.append(state)
            self.assertEqual(seen, expected)
        counters = list(range(-105, 106))
        self.assertEqual(page.evaluate("c => c.map(n => [webUiPlayground.counterEffect(n), webUiPlayground.counterLabel(n), webUiPlayground.counterStatusKey(n)])", counters),
                         [[w.counter_effect(n), w.counter_label(n), w.counter_status_key(n)] for n in counters])
        held = [0, 1, 349, 349.5, 350, 419, 419.5, 420, 489, 490, 1000, 1049.5, 5000, 123456]
        self.assertEqual(page.evaluate("h => h.flatMap(ms => [1, 2, 4, 0].map(b => [webUiPlayground.holdRepeatCount(ms, b), webUiPlayground.holdSwallowsClick(ms, b)]))", held),
                         [[w.hold_repeat_count(ms, buttons=b), w.hold_swallows_click(ms, buttons=b)] for ms in held for b in (1, 2, 4, 0)])
        seeds = [0, 1, 7, 11, 13, 17, 4294967295, 123456789] + [rng.randrange(2 ** 32) for _ in range(30)]
        self.assertEqual(page.evaluate("(seeds) => seeds.map(s => webUiPlayground.ironySequence(s, 300, 20))", seeds), [w.irony_sequence(s, 300) for s in seeds])
        self.assertEqual(page.evaluate("() => [[2, 0.7, 1], [20, 0.123, 19], [20, 0.9999, 0]].map(([n, u, c]) => [webUiPlayground.ironyNext(n, c, u), webUiPlayground.ironyNext(1, 0, u), webUiPlayground.ironyNext(n, null, u)])"),
                         [[w.irony_next(n, c, u), w.irony_next(1, 0, u), w.irony_next(n, None, u)] for n, u, c in ((2, 0.7, 1), (20, 0.123, 19), (20, 0.9999, 0))])
        drops = []
        for _ in range(3000):
            width, height = rng.uniform(100, 1200), rng.uniform(100, 1200)
            left, top = rng.uniform(-700, 1400), rng.uniform(-700, 1400)
            cw, ch, hw, hh = rng.uniform(30, 600), rng.uniform(30, 400), rng.uniform(10, 80), rng.uniform(10, 60)
            hx, hy = left + rng.uniform(0, max(cw - hw, 0)), top + rng.uniform(0, max(ch - hh, 0))
            drops.append([[width, height], [left, top, left + cw, top + ch], [hx, hy, hx + hw, hy + hh] if rng.random() > 0.05 else None])
        drops += [[[800, 544], [140, 172, 660, 372], [376, 180, 424, 212]], [[800, 544], None, None], [[100, 100], [-20, -20, 100, 100], [-30, -30, 90, 90]], [[100, 100], [100, 0, 200, 50], [100, 0, 148, 32]]]
        got = page.evaluate("d => d.map(([a, c, h]) => webUiPlayground.ironyDrop(a, c, h))", drops)
        self.assertEqual(got, [w.irony_drop(a, c, h) for a, c, h in drops])
        self.assertGreater(sum(g['action'] == 'snap' for g in got), 200)
        self.assertGreater(sum(g['action'] == 'spawn' for g in got), 200)

    def test_the_counter_page_follows_the_controller(self):
        w = web_ui_module()
        page = self.page()
        value, label, status = page.locator('[data-counter-value]'), page.locator('[data-counter-label]'), page.locator('[data-counter-status]')
        increase, decrease, reset, undo = (page.locator(f'[data-counter-{n}]') for n in ('increment', 'decrement', 'reset', 'undo'))
        self.assertEqual((value.inner_text(), label.inner_text(), status.inner_text()), ('0', 'Orbs ready…', 'Keep experimenting 👾'))
        self.assertTrue(undo.is_disabled() and reset.is_disabled())
        increase.click()
        self.assertEqual((value.inner_text(), label.inner_text(), page.locator('[data-counter-orbs]').inner_text()), ('1', '💥 Damage 1', '🔥'))
        decrease.click(); decrease.click()
        self.assertEqual((value.inner_text(), label.inner_text(), page.locator('[data-counter-orbs]').inner_text()), ('-1', '💚 Heal 1', '❤️'))
        self.assertEqual(page.locator('[data-counter-orbs]').get_attribute('data-kind'), 'heal')
        page.locator('input[name="counter-step"][value="10"]').check()
        for _ in range(10):
            decrease.click()
        self.assertEqual((value.inner_text(), status.inner_text(), decrease.is_disabled(), increase.is_disabled()), ('-100', 'Minimum reached 🧊', True, False))
        chips = page.locator('[data-counter-history] button')
        self.assertEqual(chips.count(), 8)
        self.assertEqual(chips.nth(0).get_attribute('aria-label'), 'Current value -100')
        self.assertTrue(chips.nth(0).is_disabled())
        self.assertEqual(chips.nth(1).get_attribute('aria-label'), 'Restore -91')
        chips.nth(1).click()
        self.assertEqual(value.inner_text(), '-91')
        self.assertEqual(status.inner_text(), w.COUNTER_STATUS['low'])
        undo.click()
        self.assertEqual(value.inner_text(), '-100')
        reset.click()
        self.assertEqual((value.inner_text(), reset.is_disabled(), page.locator('section[data-ui-play]').get_attribute('data-value')), ('0', True, '0'))
        for _ in range(10):
            increase.click()
        self.assertEqual((value.inner_text(), status.inner_text(), increase.is_disabled()), ('100', 'Maximum reached 🚀', True))
        # the same actions replayed in Python give the same value, burst token and history chips
        state = w.counter_state()
        for action in [('increment',), ('decrement',), ('decrement',), ('step', 10)] + [('decrement',)] * 10 + [('restore', -91), ('undo',), ('reset',)] + [('increment',)] * 10:
            state = w.counter_apply(state, *action)
        box = page.locator('section[data-ui-play]')
        self.assertEqual((box.get_attribute('data-value'), box.get_attribute('data-burst')), (str(state['counter']), str(state['burst'])))
        self.assertEqual([int(v) for v in page.locator('[data-counter-history] button').all_inner_texts()], state['history'])

    def test_holding_repeats_and_the_release_does_not_double_fire(self):
        page = self.page(clock=True)
        increase, value = page.locator('[data-counter-increment]'), page.locator('[data-counter-value]')
        read = lambda: int(value.inner_text())
        increase.click()
        page.clock.run_for(2000)
        self.assertEqual(read(), 1, 'a tap fires once and starts no repeat')
        increase.hover()
        page.mouse.down()
        page.clock.run_for(349)
        self.assertEqual(read(), 1)
        page.clock.run_for(1)
        self.assertEqual(read(), 2, 'the first repeat comes at 350 ms')
        page.clock.run_for(140)
        self.assertEqual(read(), 4, 'then one every 70 ms')
        page.mouse.up()
        page.clock.run_for(1)
        self.assertEqual(read(), 4, 'the click after a hold is swallowed')
        page.clock.run_for(500)
        self.assertEqual(read(), 4, 'the repeat stopped on release')
        increase.focus()
        page.keyboard.press('Enter')
        self.assertEqual(read(), 5, 'the next keyboard activation is not suppressed')
        page.mouse.move(0, 0)
        increase.hover()
        page.mouse.down()
        page.clock.run_for(350 + 70)
        self.assertEqual(read(), 7)
        page.mouse.move(5, 5)
        page.mouse.up()
        page.clock.run_for(5)
        self.assertEqual(read(), 7, 'dragging off and releasing stops the repeat')
        increase.focus()
        page.keyboard.press('Space')
        self.assertEqual(read(), 8, 'drag-off after a hold does not suppress the next activation')
        increase.hover()
        page.mouse.down(button='right')
        page.clock.run_for(2000)
        page.mouse.up(button='right')
        page.clock.run_for(5)
        self.assertEqual(read(), 8, 'a secondary button does not start a repeat')

    def test_holding_stops_at_the_end_and_keeps_the_disabled_state(self):
        page = self.page(clock=True)
        increase, value = page.locator('[data-counter-increment]'), page.locator('[data-counter-value]')
        page.locator('input[name="counter-step"][value="10"]').check()
        increase.hover()
        page.mouse.down()
        page.clock.run_for(350 + 70 * 20)
        self.assertEqual(value.inner_text(), '100')
        self.assertTrue(increase.is_disabled())
        page.mouse.up()
        page.clock.run_for(10)
        self.assertEqual(value.inner_text(), '100')

    def card_state(self, page):
        return page.evaluate("""() => { const q = s => document.querySelector(s), r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom] };
            const a = r(q('[data-irony-arena]')), c = r(q('[data-irony-card]')), h = r(q('[data-irony-handle]'));
            return {text: q('[data-irony-text]').textContent, index: Number(q('[data-irony-arena]').dataset.ironyIndex), arena: a, card: c, handle: h,
                    cardCenter: [(c[0] + c[2]) / 2, (c[1] + c[3]) / 2], arenaCenter: [(a[0] + a[2]) / 2, (a[1] + a[3]) / 2]} }""")

    def drag_handle(self, page, dx, dy):
        state = self.card_state(page)
        x, y = (state['handle'][0] + state['handle'][2]) / 2, (state['handle'][1] + state['handle'][3]) / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + dx / 2, y + dy / 2, steps=3)
        page.mouse.move(x + dx, y + dy, steps=3)
        page.mouse.up()

    def settled(self, page, check):
        """Wait out the 140 ms ease: run ``check(state)`` until it holds."""
        for _ in range(60):
            state = self.card_state(page)
            if check(state):
                return state
            page.wait_for_timeout(50)
        self.fail(f'never settled: {self.card_state(page)}')

    def test_the_irony_card_keeps_its_message_and_its_dragged_position(self):
        w = web_ui_module()
        sequence = w.irony_sequence(self.SEED, 3)
        page = self.page()
        first = self.card_state(page)
        self.assertEqual((first['text'], first['index']), (w.IRONIES[sequence[0]][0], sequence[0]))
        self.assertEqual(page.locator('[data-irony-tone]').inner_text(), w.IRONIES[sequence[0]][1])
        self.assertIn(page.evaluate("() => getComputedStyle(document.querySelector('[data-irony-text]')).userSelect || getComputedStyle(document.querySelector('[data-irony-text]')).webkitUserSelect"), ('text', 'auto'))
        self.drag_handle(page, 48, 32)
        moved = self.settled(page, lambda s: abs(s['cardCenter'][0] - first['cardCenter'][0] - 48) < 1 and abs(s['cardCenter'][1] - first['cardCenter'][1] - 32) < 1)
        self.assertEqual((moved['text'], moved['index']), (first['text'], first['index']))

    def test_moving_the_card_fully_outside_spawns_a_different_message(self):
        w = web_ui_module()
        sequence = w.irony_sequence(self.SEED, 3)
        page = self.page()
        first = self.card_state(page)
        events = page.evaluate("() => { window.__drops = []; document.addEventListener('ui-irony-drop', e => window.__drops.push(e.detail)); return true }")
        self.drag_handle(page, 0, first['arena'][3] - first['handle'][1] + 40)
        after = self.settled(page, lambda s: abs(s['cardCenter'][0] - s['arenaCenter'][0]) < 2 and abs(s['cardCenter'][1] - s['arenaCenter'][1]) < 2)
        self.assertEqual((after['index'], after['text']), (sequence[1], w.IRONIES[sequence[1]][0]))
        self.assertNotEqual(after['text'], first['text'])
        self.assertEqual([d['action'] for d in page.evaluate('() => window.__drops')], ['spawn'])

    def test_a_partial_exit_snaps_the_handle_back_inside_the_padded_arena(self):
        for extra in (-12, 4):
            page = self.page()
            first = self.card_state(page)
            dy = first['arena'][1] - first['handle'][3] - extra
            self.assertGreater(first['card'][3] + dy, first['arena'][1], 'precondition: the card body stays partly visible')
            self.drag_handle(page, 0, dy)
            inside = lambda s: s['handle'][1] >= s['arena'][1] + 8 - 0.5 and s['handle'][3] <= s['arena'][3] - 8 + 0.5 and s['handle'][0] >= s['arena'][0] + 8 - 0.5 and s['handle'][2] <= s['arena'][2] - 8 + 0.5
            after = self.settled(page, inside)
            self.assertEqual((after['text'], after['index']), (first['text'], first['index']), 'the message does not change on a snap')
            page.close()

    def test_the_new_irony_button_walks_the_same_sequence(self):
        w = web_ui_module()
        sequence = w.irony_sequence(self.SEED, 6)
        page = self.page()
        seen = [self.card_state(page)['index']]
        for _ in range(6):
            page.locator('[data-irony-next]').click()
            seen.append(self.card_state(page)['index'])
        self.assertEqual(seen, sequence)
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])))


class ReportBrowserTests(PageCase):
    """The test report in a real browser: SHA-256, the Flutter tally and conversion, JUnit reading and the failure history equal Python's on seeded fuzz, and the page works."""

    def setUp(self):
        from web_ui import report_document
        self.server, self.origin = WorldBrowserTests.serve({'report.html': report_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        self.errors, self.external = [], []

    def page(self):
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        page.goto(self.origin + '/report.html')
        return page

    @staticmethod
    def attempt(fn, *args, **kwargs):
        try:
            return {'ok': fn(*args, **kwargs)}
        except ValueError as error:
            return {'error': str(error)}

    JS_TRY = "const tryit = fn => { try { return {ok: fn()} } catch (e) { return {error: e.message} } };"

    def test_sha256_equals_hashlib(self):
        import hashlib
        rng = random.Random(256)
        page = self.page()
        strings = ['', 'abc', 'a' * 55, 'a' * 56, 'a' * 57, 'a' * 63, 'a' * 64, 'a' * 65, 'a' * 119, 'a' * 120, 'é' * 100, '😀' * 70, 'The quick brown fox jumps over the lazy dog', 'x' * 70000]
        strings += [''.join(rng.choice('abcXYZ 0123é😀\n<>&"') for _ in range(rng.randint(0, 400))) for _ in range(300)]
        got = page.evaluate("s => s.map(x => webUiReport.sha256Hex(x))", strings)
        self.assertEqual(got, [hashlib.sha256(s.encode()).hexdigest() for s in strings])
        raw = [bytes(rng.randrange(256) for _ in range(n)) for n in (0, 1, 55, 56, 64, 200, 1000)]
        self.assertEqual(page.evaluate("b => b.map(x => webUiReport.sha256Hex(Uint8Array.from(x)))", [list(b) for b in raw]), [hashlib.sha256(b).hexdigest() for b in raw])

    def flutter_streams(self, rng):
        names = ['ok', 'works', 'loading test/a_test.dart', 'x < y & "z"', 'ünï 😀', 'known gap', 'multi\nline', 'cr\rname', 'tab\tname', '']
        reasons = [None, 'known: gap', 'XFAIL: later', 'not in this env', '', 5, 'Known:x']
        streams = []
        for index in range(900):
            noisy = index % 3 == 0
            events, next_id = [], 1
            for _ in range(rng.randint(0, 9)):
                kind = rng.random()
                tid = next_id
                next_id += 1
                if kind < 0.1:
                    events.append({'type': 'suite', 'suite': {'id': rng.randint(0, 2), 'path': rng.choice(['test/a_test.dart', 'test/b_test.dart', '', None, 3])}})
                    continue
                start = {'type': 'testStart', 'test': {'id': tid if not noisy or rng.random() > 0.05 else rng.choice([True, 'x', 1.5, None]), 'name': rng.choice(names if noisy else names[:-1]), 'suiteID': rng.randint(0, 2)}}
                if rng.random() < 0.5:
                    start['test']['metadata'] = {'skipReason': rng.choice(reasons)}
                events.append(start)
                if rng.random() < 0.25:
                    events.append({'type': 'error', 'testID': tid, 'error': rng.choice(['expected true', 'bad \x1b[31m red', 'a < b & c', 5, None, '']), 'stackTrace': rng.choice(['at x\nat y', '', None, 7])})
                if not noisy or rng.random() < 0.93:
                    done = {'type': 'testDone', 'testID': tid, 'result': rng.choice(['success', 'success', 'success', 'failure', 'error'] + (['skipped', 'weird', None] if noisy else []))}
                    for flag in ('skipped', 'hidden'):
                        if rng.random() < 0.3:
                            done[flag] = rng.choice([True, False] + ([1, 'yes', None] if noisy else []))
                    events.append(done)
            if not noisy or rng.random() < 0.85:
                events.append({'type': 'done', 'success': rng.random() < 0.5})
            if noisy and rng.random() < 0.3:
                events.insert(rng.randrange(len(events) + 1), rng.choice([{'type': 'testDone', 'testID': 99, 'result': 'success'}, {'type': 'error', 'testID': 99, 'error': 'e'}, 42, 'text', [1], None]))
            if rng.random() < 0.3:     # ids need not arrive in order: shuffle them consistently
                ids = list(range(1, next_id))
                shuffled = ids[:]
                rng.shuffle(shuffled)
                mapping = dict(zip(ids, shuffled))
                for e in events:
                    if isinstance(e, dict):
                        if type(e.get('testID')) is int:
                            e['testID'] = mapping.get(e['testID'], e['testID'])
                        if isinstance(e.get('test'), dict) and type(e['test'].get('id')) is int:
                            e['test']['id'] = mapping.get(e['test']['id'], e['test']['id'])
            lines = [json.dumps(e) for e in events]
            if noisy and rng.random() < 0.4:
                lines.insert(rng.randrange(len(lines) + 1), rng.choice(['{broken', '', '   ', 'NaN', '{"type": NaN}', '[]', 'null', '"s"', '{"type":"testDone","testID":1,"result":"success"} trailing']))
            sep = rng.choice(['\n', '\n', '\r\n', '\r'])
            streams.append(sep.join(lines))
        streams += ['', '\n\n', '{"type":"done"}', '﻿{"type":"done"}', json.dumps({'type': 'testStart', 'test': {'id': 1, 'name': 'a b'}}) + '\n' + json.dumps({'type': 'testDone', 'testID': 1, 'result': 'success'}) + '\n{"type":"done"}']
        return streams

    def test_the_flutter_tally_and_the_conversion_equal_python(self):
        w = web_ui_module()
        rng = random.Random(20261103)
        streams = self.flutter_streams(rng)
        page = self.page()
        got = page.evaluate(self.JS_TRY + "streams => streams.map(s => [webUiReport.flutterOutcomes(s), tryit(() => webUiReport.flutterMachineJunit(s)), tryit(() => webUiReport.reportRead(s))])", streams)
        converted = 0
        for text, (counts, junit, read) in zip(streams, got):
            self.assertEqual(counts, w.flutter_outcomes(text), text)
            self.assertEqual(junit, self.attempt(w.flutter_machine_junit, text), text)
            self.assertEqual(read, self.attempt(w.report_read, text), text)
            converted += 'ok' in junit
        self.assertGreater(converted, 300, 'the fuzz must reach the conversion often enough')
        self.assertGreater(len(streams) - converted, 150, 'and the error branches too')

    def junit_documents(self, rng):
        from html import escape
        texts = ['', 'boom', 'a < b & c', 'tab\there', 'line\nbreak\r\nCRLF', 'ünï', '😀 emoji', '  spaced  ', 'known: x', 'XFAIL: y', 'Known: z', 'pytest', '[1-2]', 'x' * 230, 'q"uote\'s', ' nbsp　']
        def attr(name, value):
            return f' {name}="{escape(value, quote=True)}"'
        def body(value):
            if rng.random() < 0.2 and ']]>' not in value:
                return f'<![CDATA[{value}]]>'
            return escape(value, quote=False)
        def case():
            parts = ['<testcase']
            if rng.random() > 0.04:
                parts.append(attr('name', rng.choice(['test_a', 'test_b[1-2]', 'b', '😀' * 3, 'x < y', 'name\twith tab', 'n' * 250])))
            if rng.random() > 0.2:
                parts.append(attr('classname', rng.choice(['tests.A', 'tests.A[py3]', 'c', '', 'é' * 3, 'z' * 210])))
            if rng.random() < 0.1:
                parts.append(' time="0.1"')
            kids = []
            for _ in range(rng.choice([0, 0, 1, 1, 1, 2, 3])):
                tag = rng.choice(['failure', 'error', 'skipped', 'system-out', 'properties', 'failure', 'skipped'])
                a = ''
                if rng.random() < 0.6:
                    a += attr('message', rng.choice(texts))
                if tag == 'skipped' and rng.random() < 0.3:
                    a += attr('type', rng.choice(['pytest.xfail', 'pytest.skip', '']))
                if tag == 'failure' and rng.random() < 0.3:
                    a += attr('type', 'AssertionError')
                inner = ''
                if rng.random() < 0.5:
                    inner = body(rng.choice(texts))
                    if rng.random() < 0.2:
                        inner = '<!-- note -->' + inner + '<b>child</b>tail'
                kids.append(f'<{tag}{a}>{inner}</{tag}>' if inner or rng.random() < 0.5 else f'<{tag}{a}/>')
            return ''.join(parts) + ('>' + ''.join(kids) + '</testcase>' if kids else '/>')
        def suite(depth):
            inner = ''.join(case() if rng.random() < 0.7 or depth > 2 else suite(depth + 1) for _ in range(rng.randint(0, 5)))
            return f'<testsuite name="s{depth}" tests="3">{inner}</testsuite>'
        docs = []
        for _ in range(500):
            root = rng.choice(['suite', 'suites', 'suites', 'suite'])
            doc = suite(0) if root == 'suite' else '<testsuites>' + ''.join(suite(1) for _ in range(rng.randint(0, 3))) + '</testsuites>'
            if rng.random() < 0.2:
                doc = '<?xml version="1.0" encoding="UTF-8"?>\n' + doc
            if rng.random() < 0.05:
                doc = '﻿' + doc
            docs.append(doc)
        broken = []
        for doc in docs[:250]:
            kind = rng.random()
            if kind < 0.4:
                broken.append(doc[:rng.randrange(1, len(doc))])
            elif kind < 0.7:
                i = rng.randrange(len(doc))
                broken.append(doc[:i] + rng.choice(['<', '&', '>', '"', '\x01', '&#1;', '&bogus;', ']]>']) + doc[i + 1:])
            else:
                broken.append(doc.replace('testsuite', rng.choice(['TestSuite', 'x:testsuite', 'testsuite xmlns="urn:a"']), 1))
        fixed = [
            '<testsuite><testcase name="a"/></testsuite>', '<testsuite><testcase name="a"><failure/></testcase></testsuite>', '<testsuites/>', '<testsuite/>', '', ' ', '<a/>',
            '<testsuite xmlns="urn:x"><testcase name="a"/></testsuite>', '<testsuite xmlns:x="urn:x"><x:testcase name="a"/><testcase name="b"/></testsuite>',
            '<x:testsuite xmlns:x="urn:x"><testcase name="a"/></x:testsuite>', '<x:testsuite><testcase name="a"/></x:testsuite>',
            '<!DOCTYPE testsuite [<!ENTITY a "b">]><testsuite><testcase name="&a;"/></testsuite>', '<!doctype x><testsuite><testcase name="a"/></testsuite>', '<!DOCTYPEx><testsuite><testcase name="a"/></testsuite>',
            '<testsuite><testcase name="a" name="b"/></testsuite>', '<testsuite><testcase name="&#65;&#x42;&lt;&amp;"/></testsuite>', '<testsuite><testcase name="a&nbsp;"/></testsuite>',
            '<testsuite><testcase name="a"><failure message="m1">t1</failure><error message="m2">t2</error></testcase></testsuite>',
            '<testsuite><testcase name="a"><error message="m2">t2</error><failure message="m1">t1</failure></testcase></testsuite>',
            '<testsuite><testcase name="a"><failure>one<!-- c -->two<![CDATA[ <three> ]]><b/>ignored</failure></testcase></testsuite>',
            '<testsuite><testcase name="a"><failure><b/>after child</failure></testcase></testsuite>',
            '<testsuite>\n  <testcase name="a">\n    <failure>   </failure>\n  </testcase>\n</testsuite>',
            '<testsuite><testcase name="a"/></testsuite><!-- trailing -->', '<testsuite><testcase name="a"/></testsuite>junk', '<testsuite><testcase name="a"/></testsuite><testsuite/>',
            '\n<?xml version="1.0"?><testsuite><testcase name="a"/></testsuite>', '<?xml version="1.0" encoding="ISO-8859-1"?><testsuite><testcase name="é"/></testsuite>',
            '<testsuite><testcase name="a"><skipped message=" known: padded"/></testcase></testsuite>', '<testsuite><testcase name="a"><skipped message="KNOWN: up"/></testcase></testsuite>',
            '<testsuite><testcase name="KKnown"><skipped message="Known: kelvin"/></testcase></testsuite>',
            '<testsuite><testcase classname="a" name="x"><failure message="' + 'é' * 2500 + '"/></testcase></testsuite>',
            '<testsuite><testcase name="a"><failure message="&#xD;&#xA;&#x9;"/></testcase></testsuite>',
            '<testsuite><testcase classname="' + '😀' * 250 + '" name="' + '😀' * 250 + '"><failure message="' + '😀' * 2100 + '"/></testcase></testsuite>',
            '<testsuite><testcase name="a" pad="' + 'é' * 600_000 + '"/></testsuite>',                                  # 600,000 characters but over 1,000,000 bytes
            '<testsuite><testcase name="a" pad="' + 'x' * (1_000_000 - len('<testsuite><testcase name="a" pad=""/></testsuite>')) + '"/></testsuite>',        # exactly 1,000,000 bytes
            '<testsuite><testcase name="a" pad="' + 'x' * (1_000_001 - len('<testsuite><testcase name="a" pad=""/></testsuite>')) + '"/></testsuite>',        # one byte more
        ]
        return docs + broken + fixed

    def test_junit_reading_equals_python(self):
        w = web_ui_module()
        rng = random.Random(20261103)
        docs = self.junit_documents(rng)
        page = self.page()
        got = page.evaluate(self.JS_TRY + """docs => docs.map(d => [tryit(() => webUiReport.junitCases(d)), tryit(() => webUiReport.junitReport(d, true)), tryit(() => webUiReport.junitReport(d, false)),
            tryit(() => webUiReport.junitInspect(d)), tryit(() => webUiReport.junitFailureRecords(d, 'o/n', 4)), tryit(() => webUiReport.reportRead(d, null, true))])""", docs)
        parsed = 0
        for doc, (cases, report_m, report, inspect, records, read) in zip(docs, got):
            self.assertEqual(cases, self.attempt(w.junit_cases, doc), doc[:300])
            self.assertEqual(report_m, self.attempt(w.junit_report, doc, messages=True), doc[:300])
            self.assertEqual(report, self.attempt(w.junit_report, doc), doc[:300])
            self.assertEqual(inspect, self.attempt(w.junit_inspect, doc), doc[:300])
            self.assertEqual(records, self.attempt(w.junit_failure_records, doc, 'o/n', max_cases=4), doc[:300])
            self.assertEqual(read, self.attempt(w.report_read, doc, messages=True), doc[:300])
            parsed += 'ok' in cases
        self.assertGreater(parsed, 250)
        self.assertGreater(len(docs) - parsed, 100, 'the malformed and rejected documents are covered too')

    def test_history_ledger_and_attempts_equal_python(self):
        w = web_ui_module()
        rng = random.Random(7)
        page = self.page()
        def rec(i):
            return {'category': rng.choice(['test_failure'] * 5 + ['other']), 'context': {'repository': rng.choice(['o/n', 'a/b', 'o/n']), 'report_id': str(i)},
                    'value': {'class': rng.choice(['c1', 'c2', 'é']), 'test': rng.choice(['t1', 't2', 'q"\\\n\t\x1f 😀']), 'kind': rng.choice(['failure', 'error'])}}
        sets = [[rec(i) for i in range(rng.randint(0, 8))] for _ in range(200)]
        bad = [[{'category': 'test_failure', 'context': {}, 'value': {}}], [{'category': 'test_failure', 'context': [], 'value': {}}], [5, None, {'category': 'other'}],
               [{'category': 'test_failure', 'context': {'repository': 'a/b'}, 'value': {'class': '', 'test': 't', 'kind': 'failure'}}], [{'category': 'test_failure', 'context': {'repository': 'a/b'}, 'value': {'class': 'c', 'test': 't', 'kind': 3}}]]
        jsonl = ['\n'.join(json.dumps(r) for r in s) for s in sets[:40]] + ['{broken', json.dumps(sets[1][0] if sets[1] else {}) + '\n\n   \n{x', '']
        options = [dict(commit_sha='a' * 40, run_id='42'), dict(commit_sha='A' * 40, run_id='7', previous_commit_sha='b' * 40, previous_run_id='6'), dict(commit_sha='zz', run_id='1'), dict(commit_sha='a' * 40, run_id='x'),
                   dict(commit_sha='a' * 40, run_id='1', previous_commit_sha='short'), dict(commit_sha='a' * 40, run_id='1', previous_run_id='-')]
        got = page.evaluate(self.JS_TRY + """([sets, bad, jsonl, options]) => ({load: [...sets, ...bad].map(s => tryit(() => webUiReport.junitHistoryLoad(s))), jsonl: jsonl.map(s => tryit(() => webUiReport.junitHistoryLoad(s))),
            compare: sets.slice(0, 120).map((s, i) => tryit(() => webUiReport.junitHistory(webUiReport.junitHistoryLoad(s), webUiReport.junitHistoryLoad(sets[(i * 7 + 1) % sets.length]), options[i % options.length])))})""",
                           [sets, bad, jsonl, options])
        for s, g in zip(sets + bad, got['load']):
            self.assertEqual(g, self.attempt(w.junit_history_load, s))
        for s, g in zip(jsonl, got['jsonl']):
            self.assertEqual(g, self.attempt(w.junit_history_load, s))
        for i, g in enumerate(got['compare']):
            def compare():
                return w.junit_history(w.junit_history_load(sets[i]), w.junit_history_load(sets[(i * 7 + 1) % len(sets)]), **options[i % len(options)])
            self.assertEqual(g, self.attempt(compare))
        self.assertGreaterEqual(sum('ok' in g for g in got['compare']), 40)
        self.assertGreater(sum('error' in g for g in got['compare']), 20)
        attempts = [[{'exit_code': a, 'failures': [{'kind': rng.choice(['failure', 'error']), 'message_sha256': rng.choice(['a' * 64, 'b' * 64, 'c' * 64])} for _ in range(rng.randint(0, 3))]} for a in rng.choice([[1], [0], [1, 0], [1, 1], [0, 0]])]
                    for _ in range(80)]
        ledgers = [None, {'schema': 'failure-patterns/1', 'patterns': {}}, {'schema': 'x', 'patterns': {}}, {'schema': 'failure-patterns/1', 'patterns': []}, [], {'schema': 'failure-patterns/1', 'patterns': {'node:failure:' + 'a' * 64: {'runner': 'node', 'kind': 'failure', 'message_sha256': 'a' * 64, 'occurrences': 3}}}]
        got = page.evaluate(self.JS_TRY + """([attempts, ledgers]) => ({ledger: attempts.map((a, i) => tryit(() => webUiReport.failureLedgerUpdate(ledgers[i % ledgers.length], 'node', a))),
            history: attempts.map(a => webUiReport.attemptHistory('deno', ['a.ts'], a))})""", [attempts, ledgers])
        for i, (a, g) in enumerate(zip(attempts, got['ledger'])):
            self.assertEqual(g, self.attempt(w.failure_ledger_update, ledgers[i % len(ledgers)], 'node', a))
        for a, g in zip(attempts, got['history']):
            self.assertEqual(g, w.attempt_history('deno', ['a.ts'], a))
        many = [{'failures': [{'kind': 'failure', 'message_sha256': f'{i:064x}'} for i in range(501)]}]
        self.assertEqual(page.evaluate(self.JS_TRY + "m => tryit(() => webUiReport.failureLedgerUpdate(null, 'node', m))", many), self.attempt(w.failure_ledger_update, None, 'node', many))

    JUNIT = '<testsuite><testcase classname="tests.A" name="test_ok"/><testcase classname="tests.A" name="test_bad[1]"><failure message="SECRET_TOKEN">trace</failure></testcase><testcase name="gap"><skipped message="known: x"/></testcase></testsuite>'

    def test_the_page_reads_a_junit_report_and_keeps_messages_hidden_until_asked(self):
        import hashlib
        page = self.page()
        self.assertEqual(page.locator('[data-report-status]').inner_text(), 'Nothing read yet.')
        page.locator('[data-report-run]').click()
        self.assertEqual(page.locator('[data-report-status]').inner_text(), 'Nothing to read: paste a report first.')
        page.locator('[data-report-input]').fill(self.JUNIT)
        page.locator('[data-report-run]').click()
        self.assertEqual(page.locator('[data-report-line]').inner_text(), 'passed=1 failed=1 skipped=0 xfailed=1 xpassed=0 error=0 total=3 ok=false')
        self.assertEqual(page.locator('[data-report-out] tbody tr').count(), 1)
        row = page.locator('[data-report-out] tbody tr').first.inner_text().split('\t')
        self.assertEqual(row[:3], ['tests.A', 'test_bad[1]', 'failure'])
        self.assertEqual(row[3], hashlib.sha256(b'SECRET_TOKEN').hexdigest()[:16])
        self.assertNotIn('SECRET_TOKEN', page.locator('[data-ui-report]').inner_text())
        self.assertEqual(page.locator('[data-ui-report]').get_attribute('data-report-state'), 'failing')
        page.locator('[data-report-messages]').check()
        self.assertIn('SECRET_TOKEN', page.locator('[data-report-out]').inner_text())
        self.assertEqual(page.locator('[data-report-convert]').is_hidden(), True)

    def test_the_page_compares_with_a_previous_run_and_reads_flutter_events(self):
        page = self.page()
        page.locator('.ui-report-more summary').click()
        page.locator('[data-report-input]').fill(self.JUNIT)
        page.locator('[data-report-previous]').fill('<testsuite><testcase classname="tests.A" name="test_bad"><failure/></testcase><testcase classname="tests.B" name="gone"><error/></testcase></testsuite>')
        page.locator('[data-report-run]').click()
        out = page.locator('[data-report-out]').inner_text()
        self.assertIn('new=0 recurring=1 resolved=1', out)
        self.assertIn('recurring: tests.A · test_bad (failure) ×1 now, ×1 before', out)
        self.assertIn('resolved: tests.B · gone (error) ×0 now, ×1 before', out)
        events = '\n'.join(json.dumps(e) for e in [{'type': 'suite', 'suite': {'id': 0, 'path': 't.dart'}}, *flutter_case(1, 0, 'ok'), *flutter_case(2, 0, 'bad', result='failure'), {'type': 'done', 'success': False}])
        page.locator('[data-report-previous]').fill('')
        page.locator('[data-report-input]').fill(events)
        page.locator('[data-report-run]').click()
        self.assertEqual(page.locator('[data-report-line]').inner_text(), 'passed=1 failed=1 skipped=0 xfailed=0 xpassed=0 error=0 total=2 ok=false')
        self.assertTrue(page.locator('[data-report-convert]').is_visible())
        self.assertIn('bad', page.locator('[data-report-out]').inner_text())
        page.locator('[data-report-input]').fill('\n'.join(events.splitlines()[:3]))
        page.locator('[data-report-run]').click()
        self.assertIn('Not converted to JUnit: incomplete Flutter machine report', page.locator('[data-report-out]').inner_text())
        self.assertTrue(page.locator('[data-report-convert]').is_hidden())

    def test_the_page_refuses_what_it_cannot_read_and_says_why(self):
        page = self.page()
        for text, message in (('plain words', 'Paste JUnit XML'), ('<testsuite/>', 'JUnit report contains no testcases'), ('<!DOCTYPE a [<!ENTITY b "c">]><testsuite/>', 'DTD and entity declarations are unsupported'),
                              ('<testsuite><testcase/></testsuite>', 'testcase without name'), ('<broken', 'malformed JUnit XML')):
            page.locator('[data-report-input]').fill(text)
            page.locator('[data-report-run]').click()
            self.assertIn(message, page.locator('[data-report-status]').inner_text())
            self.assertEqual(page.locator('[data-ui-report]').get_attribute('data-report-state'), 'error')
            self.assertEqual(page.locator('[data-report-line]').inner_text(), '')
        page.locator('.ui-report-more summary').click()
        page.locator('[data-report-input]').fill('{"type":"done"}')
        page.locator('[data-report-previous]').fill('<testsuite><testcase name="a"/></testsuite>')
        page.locator('[data-report-run]').click()
        self.assertIn('needs JUnit XML for both', page.locator('[data-report-status]').inner_text())

    def test_a_file_can_be_chosen_and_an_oversized_one_is_refused(self):
        page = self.page()
        page.locator('[data-report-file]').set_input_files(files=[{'name': 'junit.xml', 'mimeType': 'application/xml', 'buffer': self.JUNIT.encode()}])
        page.wait_for_function("() => document.querySelector('[data-report-line]').textContent.includes('total=3')")
        self.assertEqual(page.locator('[data-report-input]').input_value(), self.JUNIT)
        page.locator('[data-report-file]').set_input_files(files=[{'name': 'big.xml', 'mimeType': 'application/xml', 'buffer': b'<testsuite>' + b' ' * 1_100_000 + b'</testsuite>'}])
        page.wait_for_function("() => document.querySelector('[data-report-status]').textContent === 'That file is over 1 MB.'")
        self.assertEqual(page.locator('[data-report-input]').input_value(), self.JUNIT, 'a refused file leaves the text alone')


class McpBrowserTests(PageCase):
    """The MCP lab in a real browser: every request of seeded scripts gets the same answer from the page's server as from Python's, the client demos and the helpers agree, and the
    page works."""

    LEGACY, CURRENT = '2025-03-26', '2026-07-28'
    META = 'io.modelcontextprotocol/protocolVersion'
    NOW = 1789387200

    def setUp(self):
        from web_ui import mcp_document
        self.server, self.origin = WorldBrowserTests.serve({'mcp.html': mcp_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        self.errors, self.external = [], []

    def page(self):
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        page.goto(self.origin + '/mcp.html')
        return page

    JS_TRY = "const tryit = fn => { try { return {ok: fn()} } catch (e) { return {error: e.message} } };"

    @staticmethod
    def attempt(fn, *args, **kwargs):
        try:
            return {'ok': fn(*args, **kwargs)}
        except ValueError as error:
            return {'error': str(error)}

    # --- seeded request scripts
    def meta(self, rng, version=None):
        return {self.META: version or self.CURRENT, 'io.modelcontextprotocol/clientInfo': {'name': 'test', 'version': '0'}, 'io.modelcontextprotocol/clientCapabilities': {}}

    def modern(self, rng, rid):
        w = web_ui_module()
        method = rng.choice(['server/discover', 'tools/list', 'tools/call', 'tools/call', 'resources/list', 'resources/read', 'prompts/list', 'prompts/get', 'ping', 'totally/unknown', 'notifications/initialized'])
        name = {'tools/call': rng.choice(['echo', 'echo', 'other', 'エコー', ' echo ', '=?base64?YQ==?=']), 'prompts/get': rng.choice(['greet', 'nope']), 'resources/read': rng.choice(['demo://readme', 'demo://x'])}.get(method)
        params = {'_meta': self.meta(rng)}
        if method == 'tools/call':
            params.update(name=name, arguments=rng.choice([{'text': 'hi'}, {'text': 5}, {}, 'x']))
        elif method == 'prompts/get':
            params['name'] = name
        elif method == 'resources/read':
            params['uri'] = name
        headers = {'mcp-protocol-version': self.CURRENT, 'mcp-method': method}
        if name is not None:
            headers['mcp-name'] = rng.choice([w.mcp_header_encode(name), name, w.mcp_header_encode(name), 'other', '=?base64?!!!?='])
        body = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if method != 'notifications/initialized' or rng.random() < 0.2:
            body['id'] = rid
        for _ in range(rng.choice([0, 0, 1, 1, 2])):
            action = rng.randrange(15)
            params = body.get('params')
            meta = params['_meta'] if isinstance(params, dict) and isinstance(params.get('_meta'), dict) else None
            if action == 0:
                headers.pop(rng.choice(['mcp-protocol-version', 'mcp-method', 'mcp-name']), None)
            elif action == 1:
                headers['mcp-protocol-version'] = rng.choice(['2099-01-01', self.LEGACY, '', self.CURRENT])
            elif action == 2 and meta is not None:
                meta.pop(rng.choice([self.META, 'io.modelcontextprotocol/clientInfo', 'io.modelcontextprotocol/clientCapabilities']), None)
            elif action == 3 and meta is not None:
                meta[self.META] = rng.choice([self.LEGACY, '2099-01-01', '', 5, None, self.CURRENT])
            elif action == 4 and meta is not None:
                meta['io.modelcontextprotocol/clientInfo'] = rng.choice(['nope', {}, {'name': ''}, {'name': 'x'}, {'name': 'x', 'version': ''}, {'name': 1, 'version': '0'}, {'version': '0'}, None])
            elif action == 5 and meta is not None:
                meta['io.modelcontextprotocol/clientCapabilities'] = rng.choice(['nope', [], None, 5])
            elif action == 6:
                body['params'] = rng.choice([[], None, 'x', {}])
            elif action == 7:
                headers['mcp-method'] = rng.choice(['tools/list', '', 'server/discover'])
            elif action == 8:
                body['method'] = 'totally/unknown'
            elif action == 9:
                body.pop('id', None)
            elif action == 10:
                body['id'] = rng.choice([None, 'str-id', 0, 7])
            elif action == 11:
                headers['mcp-name'] = rng.choice(['エコー', w.mcp_header_encode('エコー'), '=?', '=?base64?'])
            elif action == 12:
                headers.pop('mcp-protocol-version', None)
                headers['Mcp-Method'] = headers.pop('mcp-method', 'x')
            elif action == 13 and meta is not None:
                meta[self.META] = headers['mcp-protocol-version'] = rng.choice(['2099-01-01', self.LEGACY])      # header and body agree on a version that is not the current one
            else:
                body['jsonrpc'] = rng.choice(['1.0', 2, None])
        return headers, body

    def legacy(self, rng, rid, sessions):
        method = rng.choice(['initialize', 'initialize', 'notifications/initialized', 'notifications/initialized', 'notifications/initialized', 'ping', 'tools/list', 'tools/call', 'resources/list', 'resources/read',
                             'prompts/list', 'prompts/get', 'totally/unknown'])
        info = rng.choice([{'name': 't', 'version': '0'}] * 4 + ['nope', {}, {'name': ''}, {'name': 'x'}, {'name': 1, 'version': '0'}])
        params = None
        if method == 'initialize':
            params = rng.choice([{'protocolVersion': rng.choice([self.LEGACY, '1999-01-01', '', 5]), 'capabilities': rng.choice([{}, {}, 'nope', None]), 'clientInfo': info}] * 3 + [None, 'x', {}])
        elif method == 'tools/call':
            params = {'name': rng.choice(['echo', 'echo', 'other']), 'arguments': rng.choice([{'text': 'hi'}, {'text': 5}, {}, None])}
        elif method == 'resources/read':
            params = {'uri': rng.choice(['demo://readme', 'x'])}
        elif method == 'prompts/get':
            params = {'name': rng.choice(['greet', 'x'])}
        body = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            body['params'] = params
        if method != 'notifications/initialized' or rng.random() < 0.2:
            body['id'] = rid
        headers = {}
        if method != 'initialize' or rng.random() < 0.1:
            session = (rng.choice(sessions) if rng.random() < 0.75 else rng.choice(['nope', '', 'sess-0'])) if sessions else rng.choice(['nope', ''])
            if session or rng.random() < 0.5:
                headers[rng.choice(['mcp-session-id', 'Mcp-Session-Id', 'MCP-SESSION-ID'])] = session
        if rng.random() < 0.2:
            headers['mcp-protocol-version'] = rng.choice([self.LEGACY, '1999-01-01', self.CURRENT, ''])
        return headers, body

    def script(self, rng, size, sessions):
        w = web_ui_module()
        requests = []
        for rid in range(1, size + 1):
            kind = rng.random()
            headers, body = self.modern(rng, rid) if kind < 0.4 else self.legacy(rng, rid, sessions)
            if rid in (1, 2) or (rid % 17 == 0):      # sessions need an initialize that is well formed
                headers, body = {}, {'jsonrpc': '2.0', 'id': rid, 'method': 'initialize', 'params': {'protocolVersion': self.LEGACY, 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}}
                requests.append({'method': 'POST', 'path': '/mcp', 'headers': headers, 'body': json.dumps(body)})
                continue
            if rng.random() < 0.1:
                headers[rng.choice(['origin', 'Origin', 'ORIGIN'])] = rng.choice(['http://127.0.0.1:8787', 'http://localhost:8787', 'https://evil.example', '', 'http://127.0.0.1:9999'])
            if rng.random() < 0.12:
                aud = rng.choice(['http://127.0.0.1:8787/mcp', 'http://127.0.0.1:8787/mcp', 'http://evil.example/mcp', ['x', 'http://127.0.0.1:8787/mcp'], [], 5, None])
                exp = rng.choice([1, self.NOW - 1, self.NOW, self.NOW + 1, 4070908800, 1.5, True, None])
                token = w.demo_bearer_token(aud, exp) if exp is not None else w.demo_bearer_token(aud, 0).replace('"exp":0', '"zz":0')
                headers[rng.choice(['authorization', 'Authorization'])] = rng.choice(['Bearer ' + token] * 3 + ['Bearer', 'Bearer not-a-jwt', 'Basic abc', '', 'bearer ' + token, 'Bearer  ' + token, token])
            raw = rng.choice([json.dumps(body, ensure_ascii=False)] * 12 + ['{broken', '[]', 'null', '', '{"jsonrpc":"2.0","method":""}'])
            method = rng.choice(['POST'] * 15 + ['GET', 'post', 'PUT'])
            path = rng.choice(['/mcp'] * 20 + ['/mcp/', '/mcp/support-matrix', '/.well-known/oauth-authorization-server', '/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp', '/nope', '/'])
            requests.append({'method': method, 'path': path, 'headers': headers, 'body': raw if rng.random() > 0.05 else None})
        return requests

    def test_every_request_gets_the_same_answer_as_pythons_server(self):
        w = web_ui_module()
        rng = random.Random(20261103)
        page = self.page()
        scripts = [self.script(rng, 70, [f'sess-{i}' for i in range(1, 6)]) for _ in range(120)]
        got = page.evaluate("""scripts => scripts.map(script => { let n = 0; const routes = new webUiMcp.McpRoutes(new webUiMcp.McpFoundation(() => 'sess-' + (++n)), {clock: () => 1789387200});
            return script.map(r => routes.handle(r.method, r.path, r.headers, r.body)) })""", scripts)
        statuses, nonempty = {}, 0
        for script, answers in zip(scripts, got):
            counter = iter(range(1, 10 ** 6))
            routes = w.McpRoutes(w.McpFoundation(lambda: f'sess-{next(counter)}'), clock=lambda: self.NOW)
            for request, seen in zip(script, answers):
                expected = routes.handle(request['method'], request['path'], request['headers'], request['body'])
                self.assertEqual(seen, expected, request)
                key = None if expected is None else expected['status']
                statuses[key] = statuses.get(key, 0) + 1
                nonempty += bool(routes.handler.sessions)
        for status in (200, 202, 400, 401, 403, 404, 405):
            self.assertGreater(statuses.get(status, 0), 20, (status, statuses))
        self.assertGreater(nonempty, 2000, 'sessions get opened often enough for the legacy paths to be reached')

    def test_the_in_process_transport_and_the_client_demos_agree(self):
        w = web_ui_module()
        page = self.page()
        got = page.evaluate("""() => { const out = {}; for (const which of ['legacy', 'modern']) for (const kind of ['routes', 'foundation']) { let n = 0;
            const handler = new webUiMcp.McpFoundation(() => 'sess-' + (++n)), transport = kind === 'routes' ? webUiMcp.mcpInProcess(new webUiMcp.McpRoutes(handler)) : webUiMcp.mcpFoundationTransport(handler),
            client = new webUiMcp.McpClient(transport, 'cn', 'cv'); out[which + ':' + kind] = which === 'legacy' ? client.runEchoDemo('ünï 😀') : client.runModernEchoDemo('ünï 😀') } return out }""")
        for which in ('legacy', 'modern'):
            for kind in ('routes', 'foundation'):
                counter = iter(range(1, 100))
                handler = w.McpFoundation(lambda: f'sess-{next(counter)}')
                transport = w.mcp_in_process(w.McpRoutes(handler)) if kind == 'routes' else w.mcp_foundation_transport(handler)
                client = w.McpClient(transport, 'cn', 'cv')
                expected = client.run_echo_demo('ünï 😀') if which == 'legacy' else client.run_modern_echo_demo('ünï 😀')
                self.assertEqual(got[f'{which}:{kind}'], expected)
                self.assertTrue(expected['ok'])

    CANNED = [
        (200, {'mcp-session-id': 'sess-x'}, {'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': '2025-03-26'}}), (500, {'mcp-session-id': 'sess-x'}, {'jsonrpc': '2.0', 'id': 1, 'result': {}}),
        (401, {'Mcp-Session-Id': 'keep?'}, {'jsonrpc': '2.0', 'id': 1, 'result': {}}), (403, {}, {'error': 'forbidden'}), (401, {}, {'error': {'nested': [1, {'a': None}]}}), (502, {}, {'error': None}),
        (404, {}, {'error': 'session_invalid'}), (200, {}, 'text'), (200, {}, None), (200, {}, [1]), (200, {}, {}), (200, {'mcp-session-id': 'sess-y'}, {'jsonrpc': '2.0', 'id': 99, 'result': {}}),
        (200, {}, {'jsonrpc': '2.0', 'id': 1, 'error': {'code': '-32603', 'message': 'x'}}), (200, {}, {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32603, 'message': 42}}),
        (200, {}, {'jsonrpc': '2.0', 'id': 1, 'error': {'message': 'x'}}), (200, {}, {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32603}}), (200, {}, {'jsonrpc': '1.0', 'id': 1, 'result': {}}),
        (200, {}, {'jsonrpc': '2.0', 'id': 1}), (200, {}, {'jsonrpc': '2.0', 'id': 1, 'result': {}, 'error': {'code': 1, 'message': 'x'}}), (200, {}, {'jsonrpc': '2.0', 'id': 1, 'error': 'text'}),
        (200, {}, {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -1, 'message': 'm', 'data': {'k': 1}}}), (200, {'mcp-session-id': ''}, {'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': 5}}),
        (202, {'mcp-session-id': 'sess-n'}, None), (204, {}, None), (400, {}, {'error': 'notification_rejected'}), (200, {}, {'jsonrpc': '2.0', 'id': 1, 'result': None}),
    ]

    def test_the_client_checks_what_a_server_sends_the_same_way(self):
        w = web_ui_module()
        page = self.page()
        got = page.evaluate("""canned => canned.map(([status, headers, body]) => { const client = new webUiMcp.McpClient(() => ({status_code: status, headers, body}));
            const init = client.initialize(), s1 = client.sessionId, pv = client.protocolVersion, second = client.listTools(), note = client.notifyInitialized(); return [init, s1, pv, second, note, client.sessionId] })""", self.CANNED)
        for (status, headers, body), seen in zip(self.CANNED, got):
            client = w.McpClient(lambda h, b, status=status, headers=headers, body=body: {'status_code': status, 'headers': headers, 'body': body})
            init = client.initialize()
            expected = [init, client.session_id, client.protocol_version, client.list_tools(), client.notify_initialized(), client.session_id]
            self.assertEqual(seen, expected, (status, headers, body))

    def test_header_names_pkce_session_ids_and_oauth_documents_equal_python(self):
        w = web_ui_module()
        rng = random.Random(77)
        page = self.page()
        pieces = ['a', 'echo', 'demo://readme', ' ', '  x ', '=?', '?=', '=?base64?', 'YQ==', '!!!', '/w==', 'エコー', '😀', '\t', '\x7f', 'é', '=?base64?YQ==?=', '=?notbase64?YQ==?=', '=?base64?YQ?=', '=?base64?Y=Q=?=', '4pyT', '﻿']
        names = [''.join(rng.choice(pieces) for _ in range(rng.randint(0, 5))) for _ in range(800)] + pieces
        got = page.evaluate(self.JS_TRY + "names => names.map(n => { const e = webUiMcp.mcpHeaderEncode(n); return [webUiMcp.mcpHeaderNeedsEncoding(n), e, webUiMcp.mcpHeaderDecode(e), webUiMcp.mcpHeaderDecode(n), tryit(() => webUiMcp.mcpStreamableHeaders({name: n, method: 'm'}))] })", names)
        for name, seen in zip(names, got):
            encoded = w.mcp_header_encode(name)
            self.assertEqual(seen, [w.mcp_header_needs_encoding(name), encoded, w.mcp_header_decode(encoded), w.mcp_header_decode(name),
                                    {'ok': w.mcp_streamable_headers(name=name, method='m')}], name)
        verifiers = ['dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk', '', 'a', 'ü' * 40] + [''.join(rng.choice('abcXYZ019-._~') for _ in range(rng.randint(43, 128))) for _ in range(60)]
        self.assertEqual(page.evaluate("v => v.map(x => webUiMcp.pkceChallengeS256(x))", verifiers), [w.pkce_challenge_s256(x) for x in verifiers])
        seeds = [0, 1, 42, 4294967295] + [rng.randrange(2 ** 32) for _ in range(20)]
        self.assertEqual(page.evaluate(self.JS_TRY + "s => s.map(seed => [webUiMcp.mcpSessionId(webUiMcp.mulberry32(seed)), webUiMcp.mcpSessionId(webUiMcp.mulberry32(seed), 5), tryit(() => webUiMcp.pkcePair(webUiMcp.mulberry32(seed), 43 + seed % 86)), tryit(() => webUiMcp.pkcePair(webUiMcp.mulberry32(seed), 42))])", seeds),
                         [[w.mcp_session_id(w.mulberry32(s).__next__), w.mcp_session_id(w.mulberry32(s).__next__, 5), {'ok': w.pkce_pair(w.mulberry32(s).__next__, 43 + s % 86)}, {'error': 'verifier_length must be 43..128'}] for s in seeds])

        def tokens():
            out = []
            for _ in range(500):
                aud = rng.choice(['x', 'http://a', ['x', 'y'], ['y'], [], [''], 5, None, ['x', 3], 'ü'])
                exp = rng.choice([1, self.NOW, self.NOW + 1, 4070908800, 1.5, 2.9, -3, True, False, None, 'soon'])
                payload = {'alg': 'none'}
                body = {k: v for k, v in (('aud', aud), ('exp', exp)) if v is not None or k == 'aud'}
                b64 = lambda obj: w._b64url_nopad(json.dumps(obj, ensure_ascii=False).encode())
                token = b64(payload) + '.' + b64(body) + '.sig'
                header = rng.choice(['Bearer ' + token] * 6 + ['bearer ' + token, 'BEARER ' + token, 'Bearer  ' + token, ' Bearer ' + token, 'Bearer ' + token + ' ', 'Basic ' + token, token, 'Bearer', 'Bearer a.b', 'Bearer a.%%.c',
                                                              'Bearer x.' + b64([1]) + '.z', 'Bearer x.' + w._b64url_nopad(b'\xff\xfe') + '.z', 'Bearer x.' + w._b64url_nopad(b'{"aud":NaN}') + '.z', 'Bearer x.' + w._b64url_nopad(b'{"aud":"x","exp":1e999}') + '.z',
                                                              'Bearer x.' + b64(body)[:-1] + '.z', 'Bearer x.' + b64(body) + '=.z', '', None])
                out.append([header, rng.choice(['x', 'y', 'http://a', 'ü'])])
            return out
        cases = tokens()
        self.assertEqual(page.evaluate("c => c.map(([h, a]) => webUiMcp.bearerInspect(h, a, 1789387200))", cases), [w.bearer_inspect(h, a, self.NOW) for h, a in cases])
        statuses = {w.bearer_inspect(h, a, self.NOW)['status'] for h, a in cases}
        self.assertEqual(statuses, {'missing', 'malformed', 'expired', 'wrong_audience', 'ok'})

        def documents(kind):
            out = []
            base = {'issuer': 'https://a/', 'authorization_endpoint': 'https://a/auth', 'token_endpoint': 'https://a/token', 'response_types_supported': ['code']} if kind == 'server' else \
                {'resource': 'https://r/', 'authorization_servers': ['https://a/']}
            extras = ['registration_endpoint', 'scopes_supported', 'code_challenge_methods_supported', 'token_endpoint_auth_methods_supported', 'grant_types_supported', 'bearer_methods_supported', 'resource_name', 'unknown']
            for _ in range(500):
                doc = dict(base)
                for _ in range(rng.randint(0, 3)):
                    doc[rng.choice(extras)] = rng.choice([[], ['S256'], ['s256', 'plain'], [1], 'str', '', 5, None, ['a', ''], {}, ['none']])
                for _ in range(rng.choice([0, 0, 1])):
                    key = rng.choice(list(base))
                    doc[key] = rng.choice([None, '', 5, [], [''], ['a', 1], ['a'], 'ok', {}])
                if rng.random() < 0.05:
                    doc = rng.choice([[], 'x', None, 5])
                out.append(doc)
            return out
        servers, resources = documents('server'), documents('resource')
        got = page.evaluate(self.JS_TRY + "([s, r]) => [s.map(d => tryit(() => webUiMcp.oauthServerMetadata(d))), r.map(d => tryit(() => webUiMcp.oauthResourceMetadata(d)))]", [servers, resources])
        self.assertEqual(got[0], [self.attempt(w.oauth_server_metadata, d) for d in servers])
        self.assertEqual(got[1], [self.attempt(w.oauth_resource_metadata, d) for d in resources])
        self.assertGreater(sum('ok' in g for g in got[0]), 80)
        self.assertGreater(sum('error' in g for g in got[0]), 80)
        self.assertGreater(sum('ok' in g for g in got[1]), 80)
        self.assertGreater(sum('error' in g for g in got[1]), 80)

    def test_json_rpc_parsing_equals_python(self):
        w = web_ui_module()
        rng = random.Random(5)
        page = self.page()
        values = [None, 1, 'a', True, [], {}, {'code': -1, 'message': 'm'}, {'code': '1', 'message': 'm'}, {'code': 1}, {'message': 'm'}, {'code': 1, 'message': 'm', 'data': {'k': [1]}}, {'x': 1}]
        responses = []
        for index in range(600):
            r = {}
            if index % 4 == 0:      # a quarter are well formed, so the accepting branches are covered too
                r = {'jsonrpc': '2.0', 'id': rng.choice([1, 2, 'a']), rng.choice(['result', 'error']): None}
                key = next(k for k in ('result', 'error') if k in r)
                r[key] = rng.choice([v for v in values if key == 'result' or (isinstance(v, dict) and isinstance(v.get('code'), int) and isinstance(v.get('message'), str))])
                responses.append([r, r['id'] if rng.random() < 0.8 else rng.choice([None, 1, 2, 'a'])])
                continue
            for key, options in (('jsonrpc', ['2.0', '2.0', '2.0', '1.0', 2, None]), ('id', [1, 2, 'a', None]), ('result', values), ('error', values)):
                if rng.random() < 0.55 or key == 'jsonrpc':
                    r[key] = rng.choice(options)
            responses.append([r if rng.random() > 0.05 else rng.choice([[], 'x', None, 5]), rng.choice([None, 1, 2, 'a'])])
        got = page.evaluate(self.JS_TRY + "c => c.map(([r, id]) => tryit(() => webUiMcp.rpcResponseParse(r, id)))", responses)
        self.assertEqual(got, [self.attempt(w.rpc_response_parse, r, i) for r, i in responses])
        self.assertGreater(sum('ok' in g for g in got), 60)
        requests = []
        for _ in range(300):
            r = {}
            for key, options in (('jsonrpc', ['2.0', '2.0', '2.0', '1.0', 2]), ('id', [1, 'a', None, 0]), ('method', ['ping', 'tools/list', '', 5, None, 'x']), ('params', [{}, [], None, 'p', {'a': 1}])):
                if rng.random() < 0.8 or key == 'jsonrpc':
                    r[key] = rng.choice(options)
            requests.append(json.dumps(r))
        raws = requests + ['{"jsonrpc":"2.0","method":"a"}', '{"jsonrpc":"2.0","id":3,"method":"a","params":[1]}', '{broken', '', '[]', 'null', '"s"', '{"jsonrpc":"2.0","method":"a","x":NaN}',
                                                           '{"jsonrpc":"2.0","method":"","id":1}', '{"jsonrpc":"2.0","id":null,"method":"a"}'] + [r for r, _ in responses[200:300] if isinstance(r, dict)]
        got = page.evaluate("c => c.map(r => webUiMcp.rpcRequestParse(r))", raws)
        self.assertEqual(got, [w.rpc_request_parse(r) for r in raws])
        self.assertGreater(sum(g is not None for g in got), 40)

    def test_the_page_sends_requests_to_its_own_server(self):
        page = self.page()
        self.assertEqual(page.locator('[data-mcp-sessions]').inner_text(), '0 session(s) open on the in-page server.')
        send = lambda: page.locator('[data-mcp-send]').click()
        page.locator('[data-mcp-template="initialize"]').click()
        send()
        self.assertEqual(page.locator('[data-mcp-http-status]').inner_text(), 'HTTP 200')
        self.assertIn('mcp-session-id: ', page.locator('[data-mcp-out-headers]').inner_text())
        self.assertIn('"protocolVersion": "2025-03-26"', page.locator('[data-mcp-out-body]').inner_text())
        self.assertEqual(page.locator('[data-ui-mcp]').get_attribute('data-sessions'), '1')
        session = page.locator('[data-mcp-out-headers]').inner_text().split('mcp-session-id: ')[1].splitlines()[0]
        self.assertIn('Last: ' + session, page.locator('[data-mcp-sessions]').inner_text())
        page.locator('[data-mcp-template="initialized"]').click()
        self.assertIn('mcp-session-id: ' + session, page.locator('[data-mcp-headers]').input_value())
        send()
        self.assertEqual(page.locator('[data-mcp-http-status]').inner_text(), 'HTTP 202')
        self.assertEqual(page.locator('[data-mcp-out-body]').inner_text(), '(empty)')
        page.locator('[data-mcp-template="toolsCall"]').click()
        send()
        self.assertIn('"text": "hello"', page.locator('[data-mcp-out-body]').inner_text())
        page.locator('[data-mcp-headers]').fill('')
        page.locator('[data-mcp-template="toolsList"]').click()
        page.locator('[data-mcp-headers]').fill('')
        send()
        self.assertEqual(page.locator('[data-mcp-http-status]').inner_text(), 'HTTP 400')
        self.assertIn('session_required', page.locator('[data-mcp-out-body]').inner_text())
        page.locator('[data-mcp-template="discover"]').click()
        send()
        self.assertEqual(page.locator('[data-mcp-http-status]').inner_text(), 'HTTP 200')
        self.assertIn('"resultType": "complete"', page.locator('[data-mcp-out-body]').inner_text())
        page.locator('[data-mcp-template="modernCall"]').click()
        send()
        self.assertIn('"resultType": "complete"', page.locator('[data-mcp-out-body]').inner_text())
        page.locator('[data-mcp-headers]').fill('mcp-protocol-version: 2026-07-28\nmcp-method: tools/call\nmcp-name: other')
        send()
        self.assertEqual(page.locator('[data-mcp-http-status]').inner_text(), 'HTTP 400')
        self.assertIn('Mcp-Name does not match body params', page.locator('[data-mcp-out-body]').inner_text())
        page.locator('[data-mcp-headers]').fill('not a header line')
        send()
        self.assertIn('Each header line is name: value', page.locator('[data-mcp-http-status]').inner_text())
        self.assertEqual(page.locator('[data-ui-mcp]').get_attribute('data-http-status'), 'error')
        page.locator('[data-mcp-method]').select_option('GET')
        page.locator('[data-mcp-headers]').fill('')
        send()
        self.assertEqual(page.locator('[data-mcp-http-status]').inner_text(), 'HTTP 405')
        page.locator('[data-mcp-reset]').click()
        self.assertEqual(page.locator('[data-mcp-sessions]').inner_text(), '0 session(s) open on the in-page server.')

    def test_the_page_runs_both_demos(self):
        page = self.page()
        page.locator('[data-mcp-demo-text]').fill('ünï')
        page.locator('[data-mcp-demo-legacy]').click()
        self.assertEqual(page.locator('[data-mcp-demo-log] li').count(), 4)
        self.assertIn('Demo finished: ok. Session ', page.locator('[data-mcp-demo-status]').inner_text())
        self.assertIn('ünï', page.locator('[data-mcp-demo-log] li').nth(3).inner_text())
        self.assertEqual(page.locator('[data-ui-mcp]').get_attribute('data-demo'), 'legacy:ok')
        page.locator('[data-mcp-demo-modern]').click()
        self.assertEqual(page.locator('[data-mcp-demo-log] li').count(), 3)
        self.assertTrue(page.locator('[data-mcp-demo-status]').inner_text().endswith('No session.'))
        self.assertEqual(page.locator('[data-ui-mcp]').get_attribute('data-demo'), 'modern:ok')

    def test_the_helpers_on_the_page(self):
        w = web_ui_module()
        page = self.page()
        out = page.locator('[data-mcp-codec-out]')
        self.assertIn('Encoded: ' + w.mcp_header_encode('エコー'), out.inner_text())
        self.assertIn('Decoded back: "エコー"', out.inner_text())
        page.locator('[data-mcp-codec-in]').fill('echo')
        self.assertIn('Needs encoding: no', out.inner_text())
        page.locator('[data-mcp-codec-in]').fill('=?base64?!!!?=')
        self.assertIn('As typed, decoded: (malformed)', out.inner_text())
        self.assertEqual(page.locator('[data-mcp-challenge]').inner_text(), 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
        page.locator('[data-mcp-pkce-new]').click()
        verifier = page.locator('[data-mcp-verifier]').input_value()
        self.assertRegex(verifier, r'^[A-Za-z0-9._~-]{64}$')
        self.assertEqual(page.locator('[data-mcp-challenge]').inner_text(), w.pkce_challenge_s256(verifier))
        page.locator('[data-mcp-verifier]').fill('')
        self.assertEqual(page.locator('[data-mcp-challenge]').inner_text(), '')
        self.assertEqual(page.locator('[data-mcp-auth-out]').inner_text(), 'missing')
        page.locator('[data-mcp-auth-demo]').click()
        self.assertTrue(page.locator('[data-mcp-auth-out]').inner_text().startswith('ok · audience http://127.0.0.1:8787/mcp · expires '))
        page.locator('[data-mcp-aud]').fill('http://other/mcp')
        self.assertTrue(page.locator('[data-mcp-auth-out]').inner_text().startswith('wrong_audience'))
        page.locator('[data-mcp-auth]').fill('Bearer nope')
        self.assertEqual(page.locator('[data-mcp-auth-out]').inner_text(), 'malformed')
        self.assertIn('"supportsPkceS256": true', page.locator('[data-mcp-meta-out]').inner_text())
        page.locator('[data-mcp-meta]').fill('{broken')
        self.assertEqual(page.locator('[data-mcp-meta-out]').inner_text(), 'Not JSON.')
        page.locator('[data-mcp-meta]').fill('{"issuer": "x"}')
        self.assertEqual(page.locator('[data-mcp-meta-out]').inner_text(), 'missing OAuth metadata field: response_types_supported')
        page.locator('input[name="mcp-meta-kind"][value="resource"]').check()
        self.assertEqual(page.locator('[data-mcp-meta-out]').inner_text(), 'missing protected resource')
        page.locator('[data-mcp-meta]').fill('{"resource": "https://r/", "authorization_servers": ["https://a/"]}')
        self.assertIn('"bearer_methods_supported": [\n    "header"\n  ]', page.locator('[data-mcp-meta-out]').inner_text())


PATTERN_GOLDEN = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'pattern_golden.json').read_text(encoding='utf-8'))
SCREENS_FIXTURE = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'screens_asset.json').read_text(encoding='utf-8'))['screens']
PATTERN_ASSETS = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'pattern_assets.json').read_text(encoding='utf-8'))


def pat_norm(value):
    """Python's value with integral floats as ints: JSON in a page cannot tell 1.0 from 1."""
    if isinstance(value, float):
        return int(value) if value.is_integer() and abs(value) < 2 ** 53 else value
    if isinstance(value, list):
        return [pat_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: pat_norm(v) for k, v in value.items()}
    return value


def pat_integral_float(value):
    if isinstance(value, float):
        return value.is_integer()
    if isinstance(value, list):
        return any(pat_integral_float(v) for v in value)
    if isinstance(value, dict):
        return any(pat_integral_float(v) for v in value.values())
    return False


def pat_canon(value):
    return json.dumps(pat_norm(value), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


PAT_SCALARS = [None, True, False, 0, 1, -1, 2, 7, 0.5, -1.5, 2.5, '', 'a', 'b', 'A', 'é', ' x ', 'abc', 'item', '1', 'true', '0', 'false']


def pat_scalar(r):
    return r.choice(PAT_SCALARS)


def pat_value(r, depth=0):
    k = r.random()
    if depth < 2 and k < 0.15:
        return [pat_value(r, depth + 1) for _ in range(r.randint(0, 3))]
    if depth < 2 and k < 0.3:
        return {r.choice('abkn'): pat_value(r, depth + 1) for _ in range(r.randint(0, 3))}
    return pat_scalar(r)


def pat_mutate(r, request, p=0.3):
    if not isinstance(request, dict) or r.random() > p:
        return request
    request = dict(request)
    keys = list(request)
    c = r.random()
    if c < 0.3 and keys:
        del request[r.choice(keys)]
    elif c < 0.7 and keys:
        request[r.choice(keys)] = pat_value(r)
    else:
        request[r.choice(['x', 'extra', 'mode'])] = pat_value(r)
    return request


def pat_commands(r):
    kind = r.choice(['append', 'append', 'remove_last', 'replace', 'x'])
    if kind == 'append':
        return {'type': kind, 'value': r.choice([1, 'a', None])}
    if kind == 'replace':
        return {'type': kind, 'index': r.choice([0, 1, 2, 9, -1, True]), 'value': r.choice([1, 'a'])}
    return {'type': kind}


def pat_schema(r, depth=0):
    kind = r.choice(['null', 'boolean', 'integer', 'number', 'string', 'array', 'object'] if r.random() < 0.95 else ['x', 5])
    spec = {'type': kind}
    if kind == 'object' and depth < 2:
        if r.random() < 0.7:
            spec['properties'] = {k: pat_schema(r, depth + 1) for k in r.sample('abc', r.randint(0, 3))}
        if r.random() < 0.5:
            spec['required'] = r.sample('abc', r.randint(0, 2)) if r.random() < 0.9 else ['a', 'a']
        if r.random() < 0.4:
            spec['additional_properties'] = r.choice([True, False, 1])
    if kind == 'array' and depth < 2 and r.random() < 0.7:
        spec['items'] = pat_schema(r, depth + 1)
    if r.random() < 0.05:
        spec[r.choice(['items', 'properties', 'required', 'zzz'])] = r.choice([[], {}, 1])
    return spec


def pat_condition(r):
    op = r.choice(['equals', 'not_equals', 'greater_than', 'less_than', 'type', 'not_null', 'bogus'])
    condition = {'operator': op}
    if op in ('equals', 'not_equals', 'greater_than', 'less_than'):
        condition['value'] = r.choice([1, True, 'a', None, 2.5, [1], {'a': 1}, 0])
    elif op == 'type':
        condition['type'] = r.choice(['null', 'boolean', 'integer', 'number', 'string', 'array', 'object', 'x', 5])
    if r.random() < 0.05:
        condition['zzz'] = 1
    return condition


PAT_ASYNC = ('future', 'stream', 'concurrency', 'event_loop')
PAT_JS_VALUES = [None, True, False, 0, 1, -1, 2, 7, 0.5, -1.5, '', 'a', 'b', 'A', 'é', 'x y', '1', [], [1], {'a': 1}, {'a': 1, 'b': 2}, {'b': 2, 'a': 1}]


def pat_js_value(r):
    return r.choice(PAT_JS_VALUES)


def pat_js_task(r, top=1000, small=(0, 1, 2, 3, 5, 8, 13, 21)):
    task = {'value': pat_js_value(r)}
    if r.random() < 0.7:
        task['delay_ms'] = r.choice(list(small) * 3 + [None, -1, top + 1, 1.5, '3', True])
    if r.random() < 0.3:
        task['reject'] = r.choice(['boom', 'no', 'x y', 'boom', '', 5, None])
    if r.random() < 0.05:
        del task['value']
    if r.random() < 0.05:
        task['extra'] = 1
    return task


def pat_js_events(r, count=None, ordered=True):
    count = r.randint(0, 6) if count is None else count
    at, events = r.choice([0, 0, 5, -1]), []
    for _ in range(count):
        at += r.choice([0, 1, 5, 10, 20])
        events.append({'at_ms': at if ordered or r.random() < 0.9 else at - 30, 'value': r.choice([1, 2, 3, 'a', None, [1, 2], [3], 2.5, {'a': 1}])})
    if r.random() < 0.05 and events:
        events[0] = r.choice([{'at_ms': 1}, {'at_ms': 1, 'value': 1, 'x': 2}, 5, None, [], {'at_ms': 1.5, 'value': 1}, {'at_ms': 70000, 'value': 1}])
    return events


def pat_js_request(family, r):
    if family == 'future':
        mode = r.choice(['basic', 'chain', 'error', 'wait', 'any', 'timeout', 'bogus'])
        request = {'mode': mode}
        if mode in ('wait', 'any'):
            request['tasks'] = [pat_js_task(r) for _ in range(r.choice([0, 1, 2, 3, 4, 5, 33] if r.random() < 0.05 else [1, 2, 3, 4, 5]))]
        else:
            request['task'] = pat_js_task(r)
            if mode == 'chain':
                steps = []
                for _ in range(r.choice([0, 1, 2, 3, 4] if r.random() < 0.9 else [33])):
                    op = r.choice(['add', 'multiply', 'uppercase', 'add', 'multiply', 'x'])
                    step = {'op': op}
                    if op in ('add', 'multiply'):
                        step['by'] = r.choice([1, 2, -3, 0.5, '1', None, True])
                    if r.random() < 0.05:
                        step['extra'] = 1
                    steps.append(step)
                request['steps'] = steps
                if r.random() < 0.6:
                    request['task']['value'] = r.choice([1, 2, 3, 2.5, 'ab', 'é', None, True])
            elif mode == 'error' and r.random() < 0.85:
                request['fallback'] = pat_js_value(r)
            elif mode == 'timeout':
                request['timeout_ms'] = r.choice([1, 2, 3, 5, 8, 13, 21, 34, 0, 1001, 2.5, '5', None])
        return pat_mutate(r, request, 0.15) if r.random() < 0.95 else pat_js_value(r)
    if family == 'stream':
        mode = r.choice(['basic', 'controller', 'broadcast', 'transform', 'merge', 'debounce', 'throttle', 'buffer', 'window', 'bogus'])
        request = {'mode': mode}
        if mode == 'controller':
            commands = [r.choice([{'op': 'add', 'value': 1}, {'op': 'add', 'value': 'a'}, {'op': 'add'}, {'op': 'close'}, {'op': 'x'}, [1], 5, None, {'op': 'add', 'value': None}]) for _ in range(r.randint(0, 5))]
            if r.random() < 0.8:
                commands.append({'op': 'close'})
            request['commands'] = commands
        elif mode == 'merge':
            request['streams'] = [pat_js_events(r) for _ in range(r.choice([0, 1, 2, 3, 3] if r.random() < 0.9 else [17]))]
        else:
            request['events'] = pat_js_events(r, ordered=r.random() < 0.95)
        if mode == 'broadcast':
            request['subscribers'] = r.choice([1, 2, 3, 16, 17, 0, True, None])
        elif mode == 'transform':
            steps = []
            for _ in range(r.choice([0, 1, 2, 3] if r.random() < 0.9 else [17])):
                op = r.choice(['where_equals', 'expand', 'map_add', 'map_add', 'x'])
                step = {'op': op}
                if op in ('where_equals', 'map_add') and r.random() < 0.9:
                    step['value'] = r.choice([1, 2, 'a', None, [1, 2], 0.5, {'a': 1}])
                steps.append(step)
            if r.random() < 0.05:
                steps.append(r.choice([5, None, [1], []]))
            request['steps'] = steps
            if r.random() < 0.5:
                request['events'] = [{'at_ms': i * 3, 'value': r.choice([1, 2, 3, [1, 2], [2], 'a'])} for i in range(r.randint(0, 5))]
        elif mode in ('debounce', 'throttle'):
            request['duration_ms'] = r.choice([1, 5, 10, 20, 60000, 0, 60001, 2.5, '5', None])
        elif mode in ('buffer', 'window'):
            request['size'] = r.choice([1, 2, 3, 4, 1000, 0, 1001, '2', None])
            if mode == 'window' and r.random() < 0.7:
                request['step'] = r.choice([1, 2, 3, None, 0, 1001, 1.5])
        return pat_mutate(r, request, 0.1) if r.random() < 0.95 else pat_js_value(r)
    if family == 'concurrency':
        mode = r.choice(['work_queue', 'semaphore', 'mutex', 'cancelable', 'parallel_map', 'progress', 'bogus'])
        request = {'mode': mode}
        if mode == 'mutex':
            request['increments'] = [r.choice([1, 2, -3, 5, 2 ** 53 - 1, 2 ** 53, 1.5, '1']) for _ in range(r.choice([0, 1, 2, 3, 5, 33] if r.random() < 0.05 else [0, 1, 2, 3, 5]))]
        elif mode == 'cancelable':
            request['task'] = pat_js_task(r, 50, (0, 1, 5, 10, 50))
            request['task'].pop('reject', None)
            if r.random() < 0.9:
                request['cancel'] = r.choice([True, False, False, 1, None, 'x'])
        else:
            request['tasks'] = []
            for _ in range(r.choice([0, 1, 2, 3, 5, 33] if r.random() < 0.05 else [0, 1, 2, 3, 5])):
                task = pat_js_task(r, 50, (0, 1, 5, 10, 50))
                task.pop('reject', None)
                request['tasks'].append(task)
            if mode in ('semaphore', 'parallel_map') and r.random() < 0.9:
                request['concurrency'] = r.choice([1, 2, 3, 32, 33, 0, 1.5, '2', None])
        return pat_mutate(r, request, 0.1) if r.random() < 0.95 else pat_js_value(r)
    if family == 'event_loop':
        mode = r.choice(['reactive', 'event_loop', 'microtask', 'suspend_resume', 'async_generator', 'bogus'])
        values = [r.choice([1, 2, 3, 'a', None, [1], 2.5, {'a': 1}]) for _ in range(r.randint(0, 5))]
        if mode == 'reactive' and r.random() < 0.7:
            values = [r.choice([1, 2, 3, 0.5]) for _ in range(r.randint(0, 5))]
        request = {'mode': mode, 'values': values}
        if mode == 'reactive':
            request['steps'] = [r.choice([{'op': 'map_add', 'value': r.choice([1, 2, 0.5, 'x', None])}, {'op': 'where_equals', 'value': r.choice([1, 2, 3, 'a', None, [1], 2.5])}, {'op': 'x', 'value': 1}, {'op': 'map_add'}])
                                for _ in range(r.choice([0, 1, 2, 3] if r.random() < 0.9 else [17]))]
        elif mode == 'suspend_resume':
            request['pause_after'] = r.choice([0, 1, len(values), len(values) + 1, -1, 1.5, '1', None])
            if r.random() < 0.05:
                del request['pause_after']
        if r.random() < 0.05:
            request['values'] = r.choice([None, 'ab', {}, list(range(1001))])
        return pat_mutate(r, request, 0.12) if r.random() < 0.95 else pat_js_value(r)
    if r.random() < 0.4:                                                                                  # interaction: a debounce on a virtual clock
        at, calls = 0, []
        for _ in range(r.randint(0, 6)):
            at += r.choice([0, 1, 5, 19, 20, 21, 40])
            call = {'at_ms': at}
            if r.random() < 0.2:
                call['cancel'] = True
            else:
                call['value'] = r.choice([1, 'a', None, [1]])
            calls.append(call)
        request = {'operation': 'debounce', 'delay_ms': r.choice([0, 5, 20, 21]), 'calls': calls}
        return pat_mutate(r, request, 0.15) if r.random() < 0.95 else pat_js_value(r)
    request = {'operation': r.choice(['virtual_window'] * 6 + ['bogus']), 'count': r.choice([0, 1, 10, 100, 2.5, -1, '5', None]), 'itemHeight': r.choice([20, 1, 0, 0.5, 16, 33, -2]),
               'scrollTop': r.choice([0, 200, 55, 1000, 7, -1, 0.5, 9999]), 'viewportHeight': r.choice([0, 100, 640, 33, -5, 7.5])}
    if r.random() < 0.6:
        request['overscan'] = r.choice([0, 1, 2, 5, 1.5, -1, None, '2'])
    if r.random() < 0.05:
        request['extra'] = 1
    return pat_mutate(r, request, 0.1) if r.random() < 0.95 else pat_js_value(r)


PAT_SCREEN_TEXTS = ['', 'a', 'Screen 5', 'screen5', ' 7 ', 'Transformed Result List', 'ナビ', 'ＡＢＣ', 'İ', 'ǅ', '\u00a0x\u00a0', '\u3000検索\u3000', 'ß', 'A', 'api', 'NAVIGATION', 'drawer', '🍎',
                    'é', '\ufeffscreen', '\u200bx', 'x' * 40, 'Drawer', 'ui', 'Data', 'form', '15', 'LIST', '\t\n x \r', '\u0085y\u0085', 'ΑΣ']
PAT_SCREEN_LOCALES = ['eng', 'jpn', 'fra', 'spa', 'por', 'ara', 'zho', 'rus', 'ind', 'deu', 'swa', 'en', 'ja', 'in', ' JPN ', 'ENG', 'zz', 'ja-JP', '', None, 5, True, ['eng'], 'ＪＰＮ', '\u3000ara\u3000']
PAT_SCREEN_ARGS = ['n', 'title', 'v', 'screenDataId', 'value', 'query', 'route', 'x', '', 'urlParamCaseId', 'example']


def pat_screen_events(r, screen, count):
    """Events for a screen: mostly the ones its template has, some it does not, some malformed."""
    import web_ui
    row = web_ui.screen_row(screen)
    template = web_ui.screen_template(screen, row['templateOverride'])
    own = {'tab': {'type': 'tab', 'tab': r.choice(['usecase', 'ui', 'x'])}, 'input': {'type': 'input', 'value': r.choice(PAT_SCREEN_TEXTS)}, 'clear': {'type': 'clear'}, 'submit': {'type': 'submit'},
           'select': {'type': 'select', 'index': r.choice([0, 1, 2, 3, -1])}, 'open': {'type': 'open'}, 'close': {'type': 'close'}, 'start': {'type': 'start'}, 'tick': {'type': 'tick', 'ms': r.choice([0, 100, 250, 499, 500, 501, 60000, 60001, -1])},
           'toggle': {'type': 'toggle', 'value': r.choice([True, False, 1, None])}}
    useful = [kind for kind in own if kind in {'input', 'tab', 'clear'} or kind == {'form': 'submit', 'tabs': 'select', 'bottomNavigation': 'select', 'dialog': 'open', 'asyncState': 'start', 'settings': 'toggle'}.get(template)]
    useful += {'dialog': ['close'], 'asyncState': ['tick', 'tick']}.get(template, [])
    events = []
    for _ in range(count):
        c = r.random()
        if c < 0.75 and useful:
            events.append(dict(own[r.choice(useful)]))
        elif c < 0.9:
            events.append(dict(own[r.choice(list(own))]))
        else:
            events.append(r.choice([{'type': 'zoom'}, {'type': 5}, {}, [], 'tab', None, {'type': 'input', 'value': 5}, {'type': 'submit', 'extra': 1}, {'type': 'tick', 'ms': 'x'}, {'type': 'constructor'}, {'type': '__proto__'}]))
    return events


def pat_screen_request(r):
    import web_ui
    op = r.choice(['view', 'view', 'view', 'hub', 'search', 'text', 'route', 'links', 'bogus'])
    screen = r.choice([r.randint(1, 198), r.randint(1, 198), r.choice([6, 5, 91, 99, 103, 110, 136, 171, 198]), r.choice([0, 199, -1, 'a', None, True, 3.5])])
    request = {'operation': op}
    if op == 'view':
        request.update(screen=screen, locale=r.choice(PAT_SCREEN_LOCALES), events=pat_screen_events(r, screen, r.randint(0, 9)) if isinstance(screen, int) and 1 <= screen <= 198 and screen is not True else [])
        if screen == 6 and r.random() < 0.7:
            request['events'] = [{'type': 'input', 'value': r.choice(PAT_SCREEN_TEXTS)}] + ([{'type': 'clear'}] if r.random() < 0.3 else [])
        if r.random() < 0.15:
            del request['locale']
    elif op == 'hub':
        request.update(locale=r.choice(PAT_SCREEN_LOCALES), query=r.choice(PAT_SCREEN_TEXTS + [5, None]), mode=r.choice(['list', 'grid', 'grid', 'x', None]))
        for key in r.sample(['locale', 'query', 'mode'], r.randint(0, 2)):
            del request[key]
    elif op == 'search':
        request['query'] = r.choice(PAT_SCREEN_TEXTS + [5, None])
    elif op == 'text':
        keys = list(web_ui.SCREEN_TEXT_KEYS) + ['constructor', '__proto__', 'toString', '', 'nope', 5]
        request.update(key=r.choice(keys), locale=r.choice(PAT_SCREEN_LOCALES), arguments=[[r.choice(PAT_SCREEN_ARGS), r.choice([None, 'v', 5, -5, 0, 2 ** 53, -2 ** 53, '{n}', True, 0.5, [1]])] for _ in range(r.randint(0, 4))])
        if r.random() < 0.15:
            request['arguments'] = r.choice([[['n']], [5], 'n', [['n', 1, 2]], [[5, 1]], [['n', 1]] * 21])
    elif op == 'route':
        request['screen'] = screen
    elif op == 'links':
        request.update(screen=r.choice([r.randint(91, 99), r.choice([103, 104, 105, 107, 109, 110]), screen]), locale=r.choice(PAT_SCREEN_LOCALES))
    if r.random() < 0.12:
        request[r.choice(['x', 'extra', 'events'])] = r.choice([1, 'a', [], None])
    return request


def pat_native_request(r):
    import web_ui
    number = r.choice(web_ui.NATIVE_NUMBERS) if r.random() < 0.93 else r.choice([0, 1, 150, 164, 176, 5, 'a', None, True, 171.5])
    if number in (136, 137):
        values = r.choice([[1, 2, 3, 4, 5], [], [0], [-3, 4], [r.randint(-50, 50) for _ in range(r.randint(0, 8))], [94906265], [94906266], [94906265, 1], [0.5], [True], ['1'], None, 'x', [1] * 4097, [3] * 5000])
        request = {'pattern': number}
        if values is not None:
            request['values'] = values
        if r.random() < 0.6:
            request['engine'] = r.choice(['worker', 'fallback', 'fallback', 'x', None, 5])
        return request
    if number in web_ui.NATIVE_STATE:
        kind = web_ui.NATIVE_STATE[number][0]
        pool = ['left', 'right'] if kind in ('scope', 'model', 'atom') else ['increment', 'reset']
        actions = [r.choice(pool) if r.random() < 0.97 else r.choice(['increment', 'left', 'reset', 'x', '', 5, None, {'type': 'insert'}, ['increment']]) for _ in range(r.randint(0, 9))]
    elif number in web_ui.NATIVE_INTERACTIVE:
        names = ['A', 'B', 'C', 'A', 'B', 'C', 'N1', 'N2', 'N3', 'Z', '']
        index = lambda: r.randint(0, 3) if r.random() < 0.88 else r.choice([4, -1, 5, 0.5, 'a', None])
        makers = {'reorder': lambda: {'type': 'reorder', 'old': index(), 'new': index()}, 'swap': lambda: {'type': 'swap', 'a': r.choice(names + [5]), 'b': r.choice(names + [None])},
                  'insert': lambda: {'type': 'insert'}, 'remove': lambda: {'type': 'remove'}, 'select': lambda: {'type': 'select', 'item': r.choice(names), 'value': r.choice([True, False, False, 1, None])},
                  'delete_selected': lambda: {'type': 'delete_selected'}}
        own = {171: ['reorder'], 172: ['reorder'], 184: ['reorder'], 173: ['swap'], 174: ['insert'], 175: ['remove'], 183: ['select', 'select', 'delete_selected']}[number]
        actions = []
        for _ in range(r.randint(0, 9)):
            c = r.random()
            action = makers[r.choice(own)]() if c < 0.94 else makers[r.choice(list(makers))]() if c < 0.98 else r.choice([{}, {'type': 5}, 'insert', [], {'type': 'insert', 'x': 1}, {'type': 'reorder', 'old': 0}])
            actions.append(action)
    else:
        actions = []
    request = {'pattern': number, 'actions': actions}
    if r.random() < 0.08:
        request['x'] = 1
    if r.random() < 0.05:
        request['actions'] = r.choice([None, 'a', {}, [None] * 1001])
    return request


def pat_request(family, r):
    """A seeded request for ``family``: mostly well formed, some broken, none that JSON in a page would read differently from Python (no 1.0, no huge ints)."""
    if family in PAT_ASYNC or family == 'interaction':
        return pat_js_request(family, r)
    if family == 'screen':
        return pat_screen_request(r)
    if family == 'native':
        return pat_native_request(r)
    if family == 'query':
        op = r.choice(['stable_sort', 'custom_sort', 'group_by', 'facet', 'tag', 'range', 'geo', 'bogus'])
        n = r.randint(0, 6)
        request = {'operation': op}
        if op in ('stable_sort', 'custom_sort'):
            kind = r.choice(['int', 'str', 'float', 'mix'])
            value = lambda: {'int': r.randint(-3, 3), 'str': r.choice('abcde'), 'float': r.choice([0.5, 1.5, -2.5, 3.25]), 'mix': r.choice([1, 'a', 1.5])}[kind]
            request.update(items=[{'k': value(), 'i': i} for i in range(n)], key=r.choice(['k', 'k', 'k', 'z', '']))
            if op == 'stable_sort':
                request['descending'] = r.choice([True, False, False, 1])
            else:
                request['comparator'] = r.choice(['ascending', 'descending', 'x'])
                if r.random() < 0.2:
                    request['descending'] = r.choice([True, False])
        elif op == 'group_by':
            request.update(items=[{'g': r.choice(['a', 'b', 1, True, None, 2, [1], 0.5]), 'i': i} for i in range(n)], key='g')
        elif op in ('facet', 'tag'):
            rows = [{'c': r.choice(['a', 'b', 'c', 1, True]), 'i': i} for i in range(n)] if op == 'facet' else [{'c': r.sample(['x', 'y', 'z'], r.randint(0, 3)) if r.random() < 0.9 else 'x', 'i': i} for i in range(n)]
            request.update(items=rows, key='c', selected=[r.choice(['a', 'b', 'x', 'y', 1, True]) for _ in range(r.randint(0, 3))])
        elif op == 'range':
            request.update(items=[{'v': r.choice([r.randint(-3, 3), 0.5, 's', None]), 'i': i} for i in range(n)], key='v', minimum=r.choice([-2, 0, 0.5, 3]), maximum=r.choice([1, 2, 5, -1]))
        elif op == 'geo':
            request.update(items=[{'latitude': r.choice([35.5, 35.25, 0, 91, 'x', 40.75]), 'longitude': r.choice([139.5, 139.25, 0, 181, -74.5]), 'i': i} for i in range(n)],
                           latitude=r.choice([35.5, 35.1, 0, 95]), longitude=r.choice([139.5, 139.2, 0, 200]), radius_km=r.choice([0, 10, 100, 5000, -1, 55.5]))
        return pat_mutate(r, request) if r.random() < 0.9 else pat_value(r)
    if family == 'page':
        items = [r.choice([1, 'a', None, {'k': 1}, [1, 2], 0.5]) if r.random() < 0.3 else i for i in range(r.randint(0, 9))]
        op = r.choice(['offset', 'cursor', 'infinite', 'bogus'])
        request = {'operation': op, 'items': items, 'limit': r.choice([1, 2, 3, 5, 0, 1000, 1001, True, '2'])}
        if op == 'offset':
            if r.random() < 0.7:
                request['offset'] = r.choice([0, 1, 3, 9, 10, -1, True])
        elif op in ('cursor', 'infinite'):
            if r.random() < 0.5:
                import web_ui
                try:
                    cursor = web_ui.pattern_run('page', {'operation': op, 'items': items, 'limit': 2}).get('next_cursor')
                except ValueError:
                    cursor = None
                if cursor is not None:
                    request['cursor'] = cursor if r.random() < 0.8 else cursor[:-1] + r.choice('AB_-')
            elif r.random() < 0.2:
                request['cursor'] = r.choice([None, '', 'x', 5, 'e30'])
        return pat_mutate(r, request, 0.25) if r.random() < 0.95 else pat_value(r)
    if family == 'score':
        values = [r.choice([r.randint(-3, 5), 0.5, -1.5, 2]) for _ in range(r.randint(0, 7))]
        request = {'operation': 'minheap', 'values': values}
        if r.random() < 0.8:
            request['pops'] = r.choice([0, 1, 2, len(values), len(values) + 1, -1, True])
        return pat_mutate(r, request) if r.random() < 0.9 else pat_value(r)
    if family == 'reduce':
        actions = []
        for _ in range(r.randint(0, 6)):
            kind = r.choice(['set', 'decrement', 'reset', 'increment'] * 4 + ['x'])
            action = {'type': kind}
            if kind != 'reset':
                action['value'] = r.choice([0, 1, 5, -3, 7, 100, 10 ** 9] * 3 + [1.5, True, '1']) if r.random() < 0.97 else pat_value(r)
            elif r.random() < 0.1:
                action['value'] = 1
            actions.append(action)
        request = {'mode': r.choice(['event_state', 'redux'] * 6 + ['x']), 'initial': r.choice([0, 3, -2, 5, 10 ** 9] * 3 + [10 ** 9 + 1, 1.5, True]), 'actions': actions}
        return pat_mutate(r, request, 0.15) if r.random() < 0.97 else pat_value(r)
    if family == 'workflow':
        import web_ui
        op = r.choice(sorted(web_ui._PAT_WORKFLOW_OPS) + ['bogus'])
        values = [r.choice([1, 2, 3, 5, 8, 'a', 2.5]) for _ in range(r.randint(0, 5))]
        if op == 'insert_sorted' and r.random() < 0.7:
            values = sorted(r.randint(0, 9) for _ in range(r.randint(0, 5)))
        request = {'operation': op, 'values': values}
        if op in ('swap', 'position_swap'):
            request.update(a=r.choice([0, 1, 2, 9, -1, True]), b=r.choice([0, 1, 2, 9, -1]))
        elif op in ('move_top', 'move_bottom'):
            request['index'] = r.choice([0, 1, 2, 9, -1])
        elif op == 'insert_sorted':
            request['value'] = r.choice([0, 4, 10, 'a', 2.5])
        elif op in ('undo_redo', 'command', 'memento'):
            request['commands'] = [r.choice([{'type': 'undo'}, {'type': 'redo'}, pat_commands(r), pat_commands(r)]) for _ in range(r.randint(0, 6))]
        elif op in ('batch', 'worker', 'scheduler'):
            if r.random() < 0.7:
                request['batch_size'] = r.choice([1, 2, 3, 0, 1001, True])
            if op == 'scheduler' and r.random() < 0.7:
                request['schedule'] = [r.choice([0, 10, 60000, 60001, -1, 1.5]) for _ in range(r.randint(0, 3))]
        elif op in ('transaction', 'saga', 'pipeline'):
            request['commands'] = [pat_commands(r) for _ in range(r.randint(0, 5))]
            if r.random() < 0.6:
                request['fail_at'] = r.choice([None, 0, 1, 2, 5, -1, True])
        elif op in ('event_driven', 'pubsub', 'queue', 'outbox', 'event_sourcing', 'cqrs'):
            request['events'] = [r.choice([{'type': 'append', 'value': 1}, {'type': 'append', 'value': 'a'}, {'type': 'x', 'value': 1}, {'type': 'append'}]) for _ in range(r.randint(0, 4))]
            if op == 'pubsub' and r.random() < 0.7:
                request['subscribers'] = r.choice([1, 2, 16, 17, 0, True])
        elif op == 'checkpoint' and r.random() < 0.8:
            request['checkpoint'] = r.choice([0, 1, 3, 9, -1, True])
        return pat_mutate(r, request, 0.15) if r.random() < 0.95 else pat_value(r)
    if family == 'transform':
        op = r.choice(['schema_validation', 'constraint', 'pipeline', 'map_reduce', 'flatten', 'partition', 'zip', 'bogus'])
        request = {'operation': op, 'values': [r.choice([1, True, 'a', ' B ', None, 2.5, [1, [2]], {'a': 1}, {'a': 'x', 'b': 2}, {'a': [1]}, 0, -1]) for _ in range(r.randint(0, 5))]}
        if op == 'schema_validation':
            request['schema'] = pat_schema(r)
        elif op in ('constraint', 'partition'):
            request['condition'] = pat_condition(r)
        elif op == 'pipeline':
            steps = []
            for _ in range(r.randint(0, 3)):
                kind = r.choice(['strip', 'lower', 'upper', 'add', 'multiply', 'x'])
                step = {'operation': kind}
                if kind in ('add', 'multiply'):
                    step['value'] = r.choice([1, 2, 0.5, True, 'a'])
                steps.append(step)
            request['steps'] = steps
            if r.random() < 0.6:
                request['values'] = r.choice([[' a ', 'B'], [1, 2, 3.5], ['a', 1], []])
        elif op == 'map_reduce':
            request.update(values=[{'k': r.choice(['a', 'b', 1, True, None]), 'value': r.choice([1, 2.5, 'x', True])} if r.random() < 0.9 else r.choice([1, {}]) for _ in range(r.randint(0, 5))],
                           key=r.choice(['k', 'k', 'z', '']), reducer=r.choice(['count', 'sum', 'x']))
        elif op == 'flatten':
            request['values'] = [r.choice([1, [2, [3]], [], [[[4]]], 'a']) for _ in range(r.randint(0, 4))]
        elif op == 'zip':
            request['other'] = [r.choice([1, 'a', None]) for _ in range(r.randint(0, 5))]
            if r.random() < 0.6:
                request['strict'] = r.choice([True, False, 1])
        return pat_mutate(r, request, 0.15) if r.random() < 0.95 else pat_value(r)
    if family == 'select':
        values = [r.choice([1, True, 'a', None, [1], {'a': 1, 'b': 2}, {'b': 2, 'a': 1}, {'a': {'b': [1, 2]}}, [[1], [2]], 0.5]) for _ in range(r.randint(0, 6))]
        op = r.choice(['filter', 'filter', 'distinct', 'deduplicate_report', 'x'])
        request = {'values': values}
        if r.random() < 0.9:
            request['operation'] = op
        if op == 'filter':
            if r.random() < 0.4:
                request['equals'] = r.choice([1, True, 'a', None, [1], {'a': 1}, 0.5])
            else:
                request['conditions'] = [{'path': r.choice([[], ['a'], ['a', 'b', 1], [0], ['a', 5], ['a', -1], [True], [1.5]]), 'equals': r.choice([1, 2, 'a', None, [1, 2]])} for _ in range(r.randint(0, 3))]
                if r.random() < 0.6:
                    request['match'] = r.choice(['all', 'any', 'x'])
                if r.random() < 0.05:
                    request['equals'] = 1
        return pat_mutate(r, request, 0.15) if r.random() < 0.95 else pat_value(r)
    if family == 'order':
        import web_ui
        mode = r.choice(sorted(web_ui.PATTERN_ORDER_EXAMPLES) + ['bogus'])
        values = None
        if r.random() < 0.5:
            values = [r.choice([3, 1, 2, 2.5, True, 'a', None]) for _ in range(r.randint(0, 5))]
        if mode == 'multi' and r.random() < 0.7:
            values = [{'group': r.choice('ab'), 'score': r.choice([1, 2, 3, 2.5])} for _ in range(r.randint(0, 5))]
        if mode == 'priority' and r.random() < 0.7:
            values = [{'name': r.choice('xyz'), 'priority': r.choice([1, 2, 3, True])} for _ in range(r.randint(0, 5))]
        if mode in ('basic', 'reverse', 'sorted-set', 'top-n') and r.random() < 0.5:
            values = [r.choice([3, 1, 2, 2.5, 7, 0]) for _ in range(r.randint(0, 7))]
        request = {'mode': mode} if values is None else {'mode': mode, 'values': values}
        return pat_mutate(r, request, 0.1) if r.random() < 0.95 else pat_value(r)
    if family == 'text':
        return {'mode': r.choice(['search', 'tokens', 'text-index', 'inverted-index', 'bogus'])} if r.random() < 0.9 else pat_value(r)
    if family == 'structure':
        return {'mode': r.choice(['sticky', 'section', 'grouped', 'tree', 'flat', 'bogus'])} if r.random() < 0.9 else pat_value(r)
    if family == 'window':
        import web_ui
        commands = ['next', 'previous', 'load-more', 'prefetch', 'reset', 'page-size-3', 'offset-6', 'refresh', 'x']
        request = {'mode': r.choice(list(web_ui.PATTERN_WINDOW_MODES) + ['bogus']), 'commands': [r.choice(commands) for _ in range(r.randint(0, 6))]}
        return pat_mutate(r, request, 0.1) if r.random() < 0.95 else pat_value(r)
    if family == 'collection':
        import web_ui
        request = {'mode': r.choice(list(web_ui.PATTERN_COLLECTION_MODES) + ['bogus']),
                   'commands': [[r.choice(['select', 'toggle', 'delete', 'move-first', 'x']), r.choice(['a', 'b', 'c', 'e'])][:r.choice([1, 2, 2, 2])] for _ in range(r.randint(0, 5))]}
        return pat_mutate(r, request, 0.1) if r.random() < 0.95 else pat_value(r)
    raise AssertionError(family)


class PatternBrowserTests(PageCase):
    """The patterns page in a real browser: its twins give Python's answer to every request (the recorded original outputs, and seeded random requests, including the refusals and their
    text), the catalogue and its search agree, and the page works."""

    FAMILIES = ('collection', 'interaction', 'native', 'order', 'page', 'query', 'reduce', 'score', 'screen', 'select', 'structure', 'text', 'transform', 'window', 'workflow')

    def setUp(self):
        from web_ui import patterns_document
        self.server, self.origin = WorldBrowserTests.serve({'patterns.html': patterns_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        self.errors, self.external = [], []

    def page(self):
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        page.goto(self.origin + '/patterns.html')
        page.wait_for_selector('[data-patterns-ready]')
        return page

    START = """jobs => { window.__out = jobs.map(() => null); jobs.forEach(([family, request], i) => { try { Promise.resolve(webUiPatterns.patternRun(family, request)).then(ok => { window.__out[i] = {ok} },
        e => { window.__out[i] = {error: e.message} }) } catch (e) { window.__out[i] = {error: e.message} } }) }"""

    def clock_page(self):
        """The page with a clock that moves only when the test moves it: the promises and timers of future, stream, concurrency and event_loop run on virtual time."""
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        page.clock.install(time=0)
        page.clock.pause_at(10_000)
        page.goto(self.origin + '/patterns.html')
        page.wait_for_selector('[data-patterns-ready]')
        return page

    def run_virtual(self, page, jobs):
        page.evaluate(self.START, jobs)
        for _ in range(80):
            if page.evaluate('() => window.__out.every(x => x !== null)'):
                break
            page.clock.run_for(250)
        else:
            self.fail('requests never finished')
        return page.evaluate('() => window.__out')

    RUN = """jobs => jobs.map(([family, request]) => { try { return {ok: webUiPatterns.patternRun(family, request)} } catch (e) { return {error: e.message, kind: e.constructor.name} } })"""

    @staticmethod
    def python_outcome(family, request):
        import web_ui
        try:
            return {'ok': web_ui.pattern_run(family, request)}
        except ValueError as error:
            return {'error': str(error)}

    def same(self, family, request, python, browser):
        """The browser must give Python's result or Python's refusal text (a crash Python wraps as `invalid X request:` need only be a refusal here, as the wrapped text is CPython's)."""
        if 'ok' in python:
            self.assertEqual(('ok' in browser, pat_canon(browser.get('ok')) if 'ok' in browser else browser), (True, pat_canon(python['ok'])), (family, request))
        elif python['error'].startswith(f'invalid {family} request: '):
            self.assertIn('error', browser, (family, request))
        else:
            self.assertEqual(browser.get('error'), python['error'], (family, request))

    # --- the recorded outputs of the original oracles
    def test_the_recorded_original_outputs_are_reproduced_exactly(self):
        page = self.page()
        cases = [c for c in PATTERN_GOLDEN['cases'] if c['family'] in self.FAMILIES + PAT_ASYNC and not (c['family'] == 'score' and isinstance(c['request'], dict) and c['request'].get('operation') == 'tfidf')
                 and not pat_integral_float(c['request'])]
        assets = PATTERN_ASSETS['assets']
        self.assertGreaterEqual(len(cases), 550)
        got = page.evaluate(self.RUN, [[c['family'], c['request']] if c['family'] not in PAT_ASYNC else ['query', {}] for c in cases])
        timed = [i for i, c in enumerate(cases) if c['family'] in PAT_ASYNC]
        self.assertGreaterEqual(len(timed), 150)
        for i, outcome in zip(timed, self.run_virtual(self.clock_page(), [[cases[i]['family'], cases[i]['request']] for i in timed])):
            got[i] = outcome
        for case, outcome in zip(cases, got):
            if 'ok' in case:
                self.assertEqual(pat_canon(outcome.get('ok', outcome)), pat_canon(case['ok']), case)
            else:
                self.assertEqual(outcome.get('error'), case['error'], case)
        got = page.evaluate(self.RUN, [[a['family'], a['request']] for a in assets])
        for asset, outcome in zip(assets, got):
            self.assertEqual(pat_canon(outcome.get('ok', outcome)), pat_canon(asset['expected']), asset['asset'])

    # --- seeded random requests
    def test_random_requests_get_python_answers_and_refusals(self):
        page = self.page()
        for family in self.FAMILIES:
            rng = random.Random(f'patterns-{family}')
            jobs = []
            while len(jobs) < 1200:
                request = pat_request(family, rng)
                if not pat_integral_float(request):
                    jobs.append([family, request])
            got = page.evaluate(self.RUN, jobs)
            ok = 0
            for (name, request), outcome in zip(jobs, got):
                python = self.python_outcome(name, request)
                ok += 'ok' in python
                self.same(name, request, python, outcome)
            minimum = {'structure': 400, 'text': 400, 'native': 500, 'screen': 400}.get(family, 120)
            self.assertGreaterEqual(ok, minimum, (family, 'answers'))
            self.assertGreaterEqual(len(jobs) - ok, 20 if family not in ('structure', 'text') else 40, (family, 'refusals'))

    def test_random_requests_to_the_javascript_references_agree_on_a_virtual_clock(self):
        page = self.clock_page()
        for family in PAT_ASYNC:
            rng = random.Random(f'patterns-js-{family}')
            jobs = []
            while len(jobs) < 700:
                request = pat_request(family, rng)
                if not pat_integral_float(request):
                    jobs.append([family, request])
            ok = 0
            for (name, request), outcome in zip(jobs, self.run_virtual(page, jobs)):
                python = self.python_outcome(name, request)
                ok += 'ok' in python
                self.same(name, request, python, outcome)
            self.assertGreaterEqual(ok, 60, (family, 'answers'))
            self.assertGreaterEqual(len(jobs) - ok, 60, (family, 'refusals'))

    def test_a_task_of_zero_milliseconds_waits_one_and_ties_go_to_the_earlier(self):
        page = self.clock_page()
        jobs = [['future', {'mode': 'any', 'tasks': [{'value': 'one', 'delay_ms': 1}, {'value': 'zero'}]}], ['future', {'mode': 'any', 'tasks': [{'value': 'zero'}, {'value': 'one', 'delay_ms': 1}]}],
                ['future', {'mode': 'timeout', 'task': {'value': 1, 'delay_ms': 5}, 'timeout_ms': 5}], ['future', {'mode': 'timeout', 'task': {'value': 1, 'delay_ms': 6}, 'timeout_ms': 5}],
                ['future', {'mode': 'wait', 'tasks': [{'value': 1, 'reject': 'b', 'delay_ms': 9}, {'value': 2, 'reject': 'a', 'delay_ms': 3}, {'value': 3}]}]]
        for (name, request), outcome in zip(jobs, self.run_virtual(page, jobs)):
            self.same(name, request, self.python_outcome(name, request), outcome)
        self.assertEqual([o.get('ok', o).get('value', o.get('error')) for o in self.run_virtual(page, jobs)], ['one', 'zero', 1, 'timeout', 'a'])

    def test_every_limit_is_where_python_puts_it(self):
        """Each cap is tried at the value that is still allowed and the one that is not, in both languages."""
        ev = lambda n: [{'at_ms': i, 'value': i} for i in range(n)]
        one = {'type': 'append', 'value': 1}
        pairs = []
        for n in (1000, 1001):
            pairs += [('stream', {'mode': 'basic', 'events': ev(n)}), ('stream', {'mode': 'controller', 'commands': [{'op': 'add', 'value': 1}] * (n - 1) + [{'op': 'close'}]}),
                      ('event_loop', {'mode': 'async_generator', 'values': list(range(n))}), ('stream', {'mode': 'buffer', 'events': ev(3), 'size': n}),
                      ('stream', {'mode': 'window', 'events': ev(3), 'size': 2, 'step': n}), ('workflow', {'operation': 'undo_redo', 'values': [], 'commands': [one] * n}),
                      ('workflow', {'operation': 'swap', 'values': list(range(n)), 'a': 0, 'b': 1}), ('workflow', {'operation': 'batch', 'values': [1], 'batch_size': n}),
                      ('workflow', {'operation': 'scheduler', 'values': [], 'schedule': [0] * n}), ('workflow', {'operation': 'queue', 'values': [], 'events': [one] * n}),
                      ('workflow', {'operation': 'queue', 'values': [0], 'events': [one] * (n - 1)}), ('reduce', {'mode': 'redux', 'initial': 0, 'actions': [{'type': 'reset'}] * n}),
                      ('page', {'operation': 'offset', 'items': [1], 'limit': n}), ('window', {'mode': 'window', 'commands': ['next'] * n}), ('collection', {'mode': 'checklist', 'commands': [['toggle']] * n})]
        for n in (32, 33):
            pairs += [('future', {'mode': 'wait', 'tasks': [{'value': 1}] * n}), ('future', {'mode': 'chain', 'task': {'value': 1}, 'steps': [{'op': 'add', 'by': 1}] * n}),
                      ('concurrency', {'mode': 'work_queue', 'tasks': [{'value': 1}] * n}), ('concurrency', {'mode': 'mutex', 'increments': [1] * n}),
                      ('concurrency', {'mode': 'semaphore', 'tasks': [{'value': 1}], 'concurrency': n})]
        for n in (16, 17):
            pairs += [('stream', {'mode': 'merge', 'streams': [ev(1)] * n}), ('stream', {'mode': 'transform', 'events': ev(1), 'steps': [{'op': 'map_add', 'value': 1}] * n}),
                      ('stream', {'mode': 'broadcast', 'events': ev(1), 'subscribers': n}), ('event_loop', {'mode': 'reactive', 'values': [1], 'steps': [{'op': 'map_add', 'value': 1}] * n}),
                      ('workflow', {'operation': 'pubsub', 'values': [], 'events': [one], 'subscribers': n})]
        for n in (1000, 1001):
            pairs += [('future', {'mode': 'basic', 'task': {'value': 1, 'delay_ms': n}}), ('future', {'mode': 'timeout', 'task': {'value': 1}, 'timeout_ms': n})]
        for n in (50, 51):
            pairs += [('concurrency', {'mode': 'cancelable', 'task': {'value': 1, 'delay_ms': n}, 'cancel': False})]
        for n in (60000, 60001):
            pairs += [('stream', {'mode': 'debounce', 'events': ev(2), 'duration_ms': n}), ('interaction', {'operation': 'debounce', 'delay_ms': n, 'calls': [{'at_ms': 0, 'value': 1}]})]
        for n in (0, -1, 60000, 60001):
            pairs += [('stream', {'mode': 'basic', 'events': [{'at_ms': n, 'value': 1}]})]
        sync = [(f, r) for f, r in pairs if f not in PAT_ASYNC]
        timed = [(f, r) for f, r in pairs if f in PAT_ASYNC]
        outcomes = self.page().evaluate(self.RUN, [list(x) for x in sync]) + self.run_virtual(self.clock_page(), [list(x) for x in timed])
        answered = 0
        for (family, request), outcome in zip(sync + timed, outcomes):
            python = self.python_outcome(family, request)
            answered += 'ok' in python
            self.same(family, request, python, outcome)
        self.assertGreater(answered, 30)
        self.assertGreater(len(pairs) - answered, 25)

    def test_odd_shapes_get_python_refusals(self):
        """Requests that are almost right: a key swapped for another, a float where an int goes, the cursor of a keyset that is back at the start."""
        pairs = [('reduce', {'mode': 'redux', 'initial': 0, 'action': []}), ('reduce', {'mode': 'redux', 'initial': 0, 'actions': [{'type': 'set', 'values': 1}]}),
                 ('reduce', {'mode': 'redux', 'initial': 0, 'actions': [{'type': 'reset', 'values': 1}]}), ('reduce', {'mode': 'redux', 'initial': 1.5, 'actions': []}),
                 ('score', {'operation': 'minheap', 'values': [3, 1], 'pops': 1.5}), ('score', {'operation': 'minheap', 'values': [3, 1], 'pops': 2}), ('score', {'operation': 'minheap', 'values': [3, 1], 'pops': 3}),
                 ('page', {'operation': 'cursor', 'items': [1, 2], 'limit': 1, 'cursor': 'eyJ2IjoxLCJ4IjoxLCJoIjoiYSJ9'}), ('page', {'operation': 'cursor', 'items': [1, 2], 'limit': 1, 'cursor': 5}),
                 ('select', {'values': [[1, 2]], 'conditions': [{'path': [1.5], 'equals': 2}]}), ('select', {'values': [[1, 2]], 'conditions': [{'path': [2], 'equals': 2}]}),
                 ('select', {'values': [[1, 2]], 'conditions': [{'path': [1], 'equals': 2}]}), ('select', {'values': [{'a': 1}], 'conditions': [{'path': ['a'], 'equals': 1, 'x': 1}]}),
                 ('transform', {'operation': 'zip', 'values': [1], 'other': [1], 'strict': 'yes'}), ('transform', {'operation': 'flatten', 'values': [1], 'x': 1}),
                 ('workflow', {'operation': 'swap', 'values': [1, 2], 'a': 0, 'b': 1, 'index': 0}), ('workflow', {'operation': 'swap', 'values': [1, 2], 'a': 0}),
                 ('order', {'mode': 'basic', 'values': None}), ('order', {'mode': 'multi', 'values': [{'group': 'a', 'score': 1, 'name': 'x'}]}), ('order', {'mode': 'priority', 'values': [{'name': 'a', 'priority': 1.5}]}),
                 ('text', {'mode': 'inverted-index'}), ('structure', {'mode': 'flat'}), ('query', {'operation': 'range', 'items': [{'v': 1}], 'key': 'v', 'minimum': 1, 'maximum': 1}),
                 ('query', {'operation': 'range', 'items': [], 'key': 'v', 'minimum': 2, 'maximum': 1}), ('query', {'operation': 'geo', 'items': [{'latitude': 90, 'longitude': 180}], 'latitude': 90, 'longitude': 180, 'radius_km': 0}),
                 ('query', {'operation': 'geo', 'items': [{'latitude': 90, 'longitude': 180}], 'latitude': 91, 'longitude': 180, 'radius_km': 0}), ('query', {'operation': 'group_by', 'items': [], 'key': ''}),
                 ('query', {'operation': 'tag', 'items': [{'t': 'x'}], 'key': 't', 'selected': ['x']})]
        states = [{'mode': 'keyset', 'offset': 0, 'limit': 4, 'total': 0}, {'mode': 'keyset', 'offset': 0, 'limit': 4, 'total': 4}, {'mode': 'keyset', 'offset': 3, 'limit': 4, 'total': 12},
                  {'mode': 'keyset', 'offset': 0, 'limit': 1, 'total': 1}, {'mode': 'window', 'offset': 0, 'limit': 4, 'total': 0}, {'mode': 'window', 'offset': 5, 'limit': 3, 'total': 2}]
        import web_ui
        windows = [[state, command] for state in states for command in ('next', 'previous', 'page-size-3', 'offset-6', 'refresh', 'reset')]
        page = self.page()
        got = page.evaluate(self.RUN, [list(x) for x in pairs])
        for (family, request), outcome in zip(pairs, got):
            self.same(family, request, self.python_outcome(family, request), outcome)
        got = page.evaluate("""w => w.map(([s, cmd]) => { try { return {ok: webUiPatterns.patternWindowRender(webUiPatterns.patternWindowStep(s, cmd))} } catch (e) { return {error: e.message} } })""", windows)
        for (state, command), outcome in zip(windows, got):
            try:
                python = {'ok': web_ui.pattern_window_render(web_ui.pattern_window_step(state, command))}
            except ValueError as error:
                python = {'error': str(error)}
            self.same('window-state', [state, command], python, outcome)

    def test_the_event_loop_phases_are_the_real_ones(self):
        page = self.clock_page()
        got = self.run_virtual(page, [['event_loop', {'mode': 'microtask', 'values': []}], ['event_loop', {'mode': 'event_loop', 'values': ['x']}]])
        self.assertEqual(got[0]['ok']['result'], ['sync', 'microtask', 'promise', 'timer'])
        self.assertEqual([step['phase'] for step in got[1]['ok']['result']], ['sync', 'microtask', 'timer'])

    def test_the_debounce_function_takes_the_timers_it_is_given(self):
        got = self.page().evaluate("""() => { const calls = new Map(); let id = 0; const seen = [];
            const trigger = webUiPatterns.debounce(v => seen.push(v), 20, {setTimeoutFn: fn => { calls.set(++id, fn); return id }, clearTimeoutFn: key => calls.delete(key)});
            trigger('first'); trigger('last'); const size = calls.size; const [key, fn] = [...calls.entries()][0]; calls.delete(key); fn(); const afterFire = [...seen];
            trigger('cancelled'); trigger.cancel(); const errors = [];
            for (const args of [[null, 1], [() => {}, -1], [() => {}, NaN]]) { try { webUiPatterns.debounce(...args) } catch (e) { errors.push(e.constructor.name + ': ' + e.message) } }
            return {size, afterFire, left: calls.size, errors, window: webUiPatterns.virtualWindow({count: 100, itemHeight: 20, scrollTop: 200, viewportHeight: 100, overscan: 1})} }""")
        self.assertEqual(got, {'size': 1, 'afterFire': ['last'], 'left': 0, 'errors': ['TypeError: invalid debounce arguments'] * 3, 'window': {'start': 9, 'end': 16, 'topPadding': 180, 'bottomPadding': 1680}})

    def test_the_states_of_windows_and_collections_agree_on_every_command(self):
        import web_ui
        rng = random.Random('patterns-states')
        windows, collections = [], []
        for _ in range(800):
            state = {'mode': rng.choice(web_ui.PATTERN_WINDOW_MODES), 'offset': rng.choice([0, 3, 4, 20, -1, True, '1']), 'limit': rng.choice([4, 3, 0, True, 0.5]), 'total': rng.choice([12, 0, 5, -1])}
            if rng.random() < 0.2:
                state.pop(rng.choice(list(state)))
            windows.append([state, rng.choice(['next', 'previous', 'load-more', 'prefetch', 'reset', 'page-size-3', 'offset-6', 'refresh', 'x'])])
            collections.append([{'mode': rng.choice(web_ui.PATTERN_COLLECTION_MODES), 'items': rng.choice([['a', 'b'], ['a', 'a'], [], ['a', 1], ['a', 'b', 'c', 'd']]), 'selected': rng.choice([[], ['a'], ['z'], ['a', 'a']])},
                                rng.choice(['select', 'toggle', 'delete', 'move-first', 'x']), rng.choice(['a', 'b', 'z'])])
        page = self.page()
        got = page.evaluate("""([w, c]) => [w.map(([s, cmd]) => { try { return {ok: webUiPatterns.patternWindowRender(webUiPatterns.patternWindowStep(s, cmd))} } catch (e) { return {error: e.message} } }),
            c.map(([s, cmd, item]) => { try { return {ok: webUiPatterns.patternCollectionRender(webUiPatterns.patternCollectionStep(s, cmd, item))} } catch (e) { return {error: e.message} } })]""", [windows, collections])
        okay = 0
        for (state, command), outcome in zip(windows, got[0]):
            try:
                python = {'ok': web_ui.pattern_window_render(web_ui.pattern_window_step(state, command))}
            except (ValueError, TypeError) as error:
                python = {'error': str(error)}
            okay += 'ok' in python
            self.same('window-state', [state, command], python, outcome)
        for (state, command, item), outcome in zip(collections, got[1]):
            try:
                python = {'ok': web_ui.pattern_collection_render(web_ui.pattern_collection_step(state, command, item))}
            except (ValueError, TypeError) as error:
                python = {'error': str(error)}
            okay += 'ok' in python
            self.same('collection-state', [state, command, item], python, outcome)
        self.assertGreater(okay, 150)

    def test_text_search_helpers(self):
        import web_ui
        rng = random.Random('patterns-text')
        words = ['Flutter', 'portable', 'search', 'the', 'And', 'a', 'x_1', 'Ａ', 'cat', 'Dog', '123', 'indexes']
        queries = [' '.join(rng.choice(words) for _ in range(rng.randint(0, 4))) + rng.choice(['', '!', '  ']) for _ in range(400)]
        docs = [[{'id': rng.choice(['d1', 'd2', 'd3']), 'text': ' '.join(rng.choice(words) for _ in range(rng.randint(0, 5)))} for _ in range(rng.randint(0, 4))] for _ in range(400)]
        got = self.page().evaluate("""([queries, docs]) => queries.map((q, i) => [webUiPatterns.patternTokens(q), webUiPatterns.patternWithoutStopWords(webUiPatterns.patternTokens(q)), webUiPatterns.patternTextSearch(docs[i], q),
            webUiPatterns.patternInvertedIndex(docs[i])])""", [queries, docs])
        for query, documents, outcome in zip(queries, docs, got):
            tokens = web_ui.pattern_tokens(query)
            index = web_ui.pattern_inverted_index(documents)
            self.assertEqual(outcome, [tokens, web_ui.pattern_without_stop_words(tokens), web_ui.pattern_text_search(documents, query), [[t, ids] for t, ids in index.items()]], (query, documents))

    # --- the helpers the twins stand on
    def test_pyjson_writes_what_python_writes(self):
        rng = random.Random('patterns-json')
        alphabet = ['a', 'é', '日', '😀', chr(0xFFFF), chr(0x10000), chr(0), '\n', '"', '\\', chr(0x7F), chr(0x2028), ' ', chr(0x1F), 'z']
        def text():
            return ''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 5)))
        def number():
            return rng.choice([0, 1, -1, 12345, 2 ** 52, 0.5, -1.5, 1.5e-7, 1e-5, 0.0001, 0.00012, 123456.789, 1e-300, 5e-324, 4503599627370495.5, 0.1 + 0.2, 1 / 3, 1e15 + 0.5, 2.5e-5])
        def value(depth=0):
            kind = rng.random()
            if depth < 3 and kind < 0.15:
                return [value(depth + 1) for _ in range(rng.randint(0, 4))]
            if depth < 3 and kind < 0.3:
                return {text(): value(depth + 1) for _ in range(rng.randint(0, 4))}
            return rng.choice([None, True, False, text(), number(), number(), text()])
        values = [value() for _ in range(1500)]
        got = self.page().evaluate("values => values.map(v => webUiPatterns.pyJson(v))", values)
        for item, text_out in zip(values, got):
            self.assertEqual(text_out, pat_canon(item), item)

    def test_equality_and_ordering_of_strings_follow_python(self):
        rng = random.Random('patterns-eq')
        pool = [None, True, False, 0, 1, 2, 0.5, 2.5, '', 'a', '1', 'true', [], [1], [True], [1, 'a'], {}, {'a': 1}, {'a': True}, {'b': 1}, {'a': [1]}, {'a': [True]}, [[0]], [[False]]]
        pairs = [[rng.choice(pool), rng.choice(pool)] for _ in range(1500)]
        got = self.page().evaluate("pairs => pairs.map(([a, b]) => webUiPatterns.pyEq(a, b))", pairs)
        self.assertEqual(got, [a == b for a, b in pairs])
        alphabet = ['a', 'b', 'é', '日', '😀', chr(0xFFFF), chr(0x10000), chr(0xD7FF), chr(0xE000), 'Z']
        strings = [[''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 4))), ''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 4)))] for _ in range(1500)]
        got = self.page().evaluate("pairs => pairs.map(([a, b]) => webUiPatterns.cmpStr(a, b))", strings)
        self.assertEqual(got, [(a > b) - (a < b) for a, b in strings])

    def test_unknown_families_are_named_as_python_names_them(self):
        names = ['regex', "O'Reilly", 'say "hi"', 'a\\b', "both ' and \"", '', 'Query']
        got = self.page().evaluate(self.RUN, [[name, {}] for name in names])
        for name, outcome in zip(names, got):
            self.assertEqual(outcome['error'], self.python_outcome(name, {})['error'], name)
        for name in ('search', 'convert', 'validate'):
            self.assertEqual(self.page().evaluate(self.RUN, [[name, {}]])[0]['error'], f'{name} runs in Python only: python3 web_ui.py --pattern {name}')
        self.assertEqual(self.page().evaluate(self.RUN, [['score', {'operation': 'tfidf', 'documents': []}]])[0]['error'], 'tfidf runs in Python only')

    # --- the catalogue
    def test_the_catalogue_is_python_catalogue(self):
        import web_ui
        page = self.page()
        self.assertEqual(page.evaluate("webUiPatterns.patternCatalogue()"), web_ui.pattern_catalogue())
        numbers = list(range(-2, 203))
        got = page.evaluate("""n => n.map(x => { const out = [webUiPatterns.patternFamily(x), webUiPatterns.patternOwner(x)]; for (const c of ['navigation', 'api', 'ui', 'data']) { try { out.push(webUiPatterns.patternTheme(c, x)) } catch (e) { out.push(e.message) } } return out })""", numbers)
        for number, outcome in zip(numbers, got):
            themes = []
            for category in ('navigation', 'api', 'ui', 'data'):
                try:
                    themes.append(web_ui.pattern_theme(category, number))
                except ValueError as error:
                    themes.append(str(error))
            self.assertEqual(outcome, [web_ui.pattern_family(number), web_ui.pattern_owner(number), *themes], number)

    def test_searching_the_catalogue_agrees(self):
        import web_ui
        rng = random.Random('patterns-find')
        rows = web_ui.pattern_catalogue()
        words = ['filter', 'FILTER', 'ＦＩＬＴＥＲ', 'd003', 'push', 'pop', 'ページング', 'Navigation', ' ', 'theme', 'Cupertino', 'ａｐｉ', '001', 'フィルタ', 'Json', 'a', 'の', 'xyzzy', 'Material', 'ダーク']
        queries = [[' '.join(rng.choice(words) for _ in range(rng.randint(0, 3))), rng.choice(['', '', 'navigation', 'api', 'ui', 'data', 'nope']), rng.choice(['', '', '', 'select', 'workflow', 'query', 'nope'])]
                   for _ in range(600)]
        got = self.page().evaluate("""qs => { const rows = webUiPatterns.patternCatalogue(); return qs.map(([q, c, f]) => webUiPatterns.patternFind(rows, q, c, f).map(r => r.id)) }""", queries)
        counts = set()
        for (query, category, family), outcome in zip(queries, got):
            expected = [r['id'] for r in web_ui.pattern_find(rows, query, category, family)]
            self.assertEqual(outcome, expected, (query, category, family))
            counts.add(min(len(expected), 3))
        self.assertEqual(counts, {0, 1, 2, 3})

    # --- the page
    def test_the_page_lists_and_searches_the_catalogue(self):
        page = self.page()
        self.assertEqual(page.text_content('[data-patterns-count]'), '792 patterns')
        self.assertEqual(page.eval_on_selector_all('[data-patterns-list] li', 'els => els.length'), 48)
        self.assertEqual(page.get_attribute('[data-patterns-list] li', 'data-id'), 'A001')
        page.click('[data-patterns-more]')
        self.assertEqual(page.eval_on_selector_all('[data-patterns-list] li', 'els => els.length'), 96)
        self.assertEqual(page.get_attribute('#patterns', 'data-shown'), '96')
        page.fill('[data-patterns-query]', 'FilterNested')
        self.assertEqual(page.text_content('[data-patterns-count]'), '1 of 792 patterns')
        self.assertIn('D003', page.text_content('[data-patterns-list]'))
        self.assertIn('select', page.text_content('[data-patterns-list]'))
        self.assertTrue(page.is_hidden('[data-patterns-more]'))
        page.fill('[data-patterns-query]', '')
        page.select_option('[data-patterns-category]', 'data')
        page.select_option('[data-patterns-family]', 'select')
        self.assertEqual(page.text_content('[data-patterns-count]'), '6 of 792 patterns')
        page.select_option('[data-patterns-family]', '')
        page.fill('[data-patterns-query]', 'nothing matches this')
        self.assertEqual(page.text_content('[data-patterns-count]'), '0 of 792 patterns')

    def test_the_runner_runs_twins_here_and_shows_python_for_the_rest(self):
        import web_ui
        page = self.page()
        self.assertEqual((page.get_attribute('#patterns', 'data-engine'), page.get_attribute('#patterns', 'data-run'), page.get_attribute('#patterns', 'data-family')), ('browser', 'ok', 'query'))
        self.assertEqual(pat_canon(json.loads(page.text_content('[data-patterns-result]'))), pat_canon(web_ui.pattern_run('query', web_ui.PATTERN_EXAMPLES['query'])))
        for family in sorted(web_ui.PATTERN_RUNNERS):
            page.select_option('[data-patterns-run-family]', family)
            engine = 'browser' if family in web_ui.PATTERN_TWINS else 'python'
            if family in PAT_ASYNC:
                expect(page.locator('#patterns')).to_have_attribute('data-run', 'ok')
            self.assertEqual((page.get_attribute('#patterns', 'data-engine'), page.get_attribute('#patterns', 'data-run')), (engine, 'ok'), family)
            self.assertEqual(pat_canon(json.loads(page.text_content('[data-patterns-result]'))), pat_canon(web_ui.pattern_run(family, web_ui.PATTERN_EXAMPLES[family])), family)
        page.select_option('[data-patterns-run-family]', 'search')
        page.fill('[data-patterns-request]', '{"operation": "stem", "text": "walking it\'s"}')
        page.click('[data-patterns-run]')
        self.assertEqual(page.get_attribute('#patterns', 'data-run'), 'python')
        self.assertIn("python3 web_ui.py --pattern search", page.text_content('[data-patterns-status]'))
        self.assertIn("'\\''", page.text_content('[data-patterns-status]'), 'a quote in the request is escaped for the shell')
        page.select_option('[data-patterns-run-family]', 'order')
        page.fill('[data-patterns-request]', '{"mode": "shuffle"}')
        page.click('[data-patterns-run]')
        self.assertEqual((page.get_attribute('#patterns', 'data-run'), page.text_content('[data-patterns-status]'), page.text_content('[data-patterns-result]')), ('refused', 'Refused: unsupported ordering mode', ''))
        page.fill('[data-patterns-request]', '{"mode": ')
        page.click('[data-patterns-run]')
        self.assertEqual((page.get_attribute('#patterns', 'data-run'), page.text_content('[data-patterns-status]')), ('invalid', 'Not JSON.'))
        page.click('[data-patterns-example]')
        self.assertEqual(page.get_attribute('#patterns', 'data-run'), 'ok')
        page.select_option('[data-patterns-run-family]', 'score')
        page.fill('[data-patterns-request]', '{"operation": "tfidf", "documents": ["a b"]}')
        page.click('[data-patterns-run]')
        self.assertEqual((page.get_attribute('#patterns', 'data-engine'), page.get_attribute('#patterns', 'data-run')), ('python', 'python'))

    def test_the_page_fits_a_phone(self):
        page = self.page()
        page.set_viewport_size({'width': 320, 'height': 700})
        page.select_option('[data-patterns-run-family]', 'workflow')
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 320)
        self.assertLessEqual(page.evaluate('Math.max(...[...document.querySelectorAll("#patterns *")].map(e => e.getBoundingClientRect().right))'), 320)


STUDIO_GOLDEN = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'studio_golden.json').read_text(encoding='utf-8'))
STUDIO_CALL = """jobs => { const S = webUiImageStudio; S.useCanvasMetrics(false); const expand = v => Array.isArray(v) ? v.map(expand) : v && typeof v === 'object' ? ('__repeat' in v ? v.__repeat[0] + v.__repeat[1].repeat(v.__repeat[2]) : Object.fromEntries(Object.entries(v).map(([k, x]) => [k, expand(x)]))) : v;\n  return jobs.map(([fn, arg0]) => { const arg = expand(arg0); try { return {ok: (() => { switch (fn) {
  case 'jsnum': return String(arg); case 'jsjson': return JSON.stringify(arg); case 'heatColor': return S.heatColor(...arg); case 'matrix': return S.matrix(arg); case 'validate': return S.validate(arg);
  case 'mosaic': return [...S.mosaicRGBA(arg[0], ...arg.slice(1))]; case 'arrow': return S.arrowGeometry(...arg); case 'outputSize': return S.outputSize(...arg); case 'pngPayload': return S.pngPayload(arg);
  case 'textLayout': return S.textLayout(arg); case 'layerSVG': return S.layerSVG(arg); case 'svg': return S.svg(arg[0], undefined, arg[1]); case 'words': return S.words(arg); case 'graphemes': return S.graphemes(arg);
  case 'history': { let h; const states = []; for (const [op, scene] of arg) { if (op === 'new') h = new S.History(scene); else if (op === 'commit') h.commit(scene); else if (op === 'undo') h.undo(); else h.redo();
    states.push([h.index, h.items.length]) } return {states, items: h.items, workspace: S.workspaceText(h)} }
  case 'place': return S.place(arg[0], arg[1], arg[2], arg[3], arg[4]); case 'textLayer': return S.textLayer(...arg); case 'matrixLayer': return S.matrixLayer(...arg); case 'imageLayer': return S.imageLayer(...arg);
  case 'demo': return S.demoScene(); case 'stampDemo': return S.stampDemoScene(); case 'heatmapScene': return S.heatmapScene(arg); case 'blank': return S.blank();
  case 'sincos': return [S.sin(arg), S.cos(arg)];
  case 'textLayoutM': return S.textLayout(arg[0], t => Array.from(t).length * arg[1]);
  case 'historyRun': { const h = new S.History(arg[0]), seen = []; for (const [op, scene] of arg.slice(1)) { if (op === 'commit') h.commit(scene); else if (op === 'undo') h.undo(); else if (op === 'redo') h.redo(); else if (op === 'trim') { h.items = h.items.slice(-1); h.index = 0 } seen.push([h.index, h.items.length, JSON.stringify(h.current)]) } return seen }
  case 'workspace': { const h = new S.History(arg[0]); for (const s of arg.slice(1)) h.commit(s); return S.workspaceText(h) }
  default: throw new Error('unknown ' + fn) } })() } } catch (e) { return {error: e.message} } }) }"""
def studio_norm(value):
    if isinstance(value, float):
        return int(value) if value.is_integer() and abs(value) < 2 ** 53 else value
    if isinstance(value, (list, tuple)):
        return [studio_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: studio_norm(v) for k, v in value.items()}
    return value


def studio_canon(value):
    return json.dumps(studio_norm(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


STUDIO_TEXTS = ['hello world', "Hello, world! can't stop", 'a very long line of ordinary words that should wrap into several lines', 'supercalifragilisticexpialidocious_is_a_word', 'café naïve résumé',
                '3.14 e.g. a.b example.com', '<tag> & "quote" \'single\'', '한국어 텍스트 입니다', 'x\ny\n\nz', 'tab\there', '🌱 emoji 👍🏽 flag 🇯🇵', 'line one\r\nline two', '']


def studio_random_scene(r, wrap=True):
    import web_ui as w
    scene = w.studio_blank()
    scene.update(width=r.randint(64, 900), height=r.randint(64, 700), background=r.choice(['none', '#FFFFFF', '#18A7A1', '#f8f7f2']))
    number = lambda low, high: r.choice([r.randint(low, high), round(r.uniform(low, high), r.choice([1, 2, 3]))])
    for i in range(r.randint(0, 7)):
        kind = r.choice(['rect', 'ellipse', 'triangle', 'arrow', 'clock', 'text', 'text', 'heatmap', 'image'])
        lid = f'L{i}' + r.choice(['', 'é', '😀'])
        if kind == 'heatmap':
            cols = r.randint(1, 4)
            layer = w.studio_matrix_layer({'z': [[None if r.random() < 0.15 else r.choice([r.randint(-5, 9), round(r.uniform(-5, 9), 3)]) for _ in range(cols)] for _ in range(r.randint(1, 4))]}, lid)
            layer['levels'] = r.choice([0, 0, 2, 5, 256])
            layer['labels'] = r.choice([True, False])
        elif kind == 'image':
            layer = w.studio_image_layer('data:image/png;base64,' + base64.b64encode(w.studio_png_encode(2, 2, bytes(r.randrange(256) for _ in range(16)))).decode('ascii'), 2, 2, lid, scene['width'])
            layer.update(cell=r.choice([1, 2, 8]), levels=r.choice([256, 4]), sampling=r.choice(['pixelated', 'smooth']), mono=r.choice([True, False]), fill=r.choice(['#18a7a1', '#FFFFFF']))
        elif kind == 'text':
            layer = w.studio_place('text', lid, 0, 0, fill=r.choice(['#18a7a1', '#FFFFFF', 'none']), text=r.choice(STUDIO_TEXTS), font=r.choice(['sans', 'mono']), mono=r.choice([True, False]), wrap=wrap and r.choice([True, False]))
            layer.update(fontSize=number(6, 96), w=r.choice([40, 120, 300, 700]))
            if r.random() < 0.3:
                layer['bold'] = r.choice([True, False])
        else:
            layer = w.studio_place(kind, lid, 0, 0, outline=r.random() < 0.3, arrow_style=r.choice(['beginner', 'triangle']), arrow_placement=r.choice(['tip', 'middle']),
                                   clock_time=f'{r.randint(0, 23)}:{r.randint(0, 59):02d}', fill=r.choice(['#18a7a1', '#FFFFFF', 'none']))
            layer.update(strokeWidth=r.choice([0, 1, 3, 6, 64]))
            if kind == 'arrow':
                layer['headSize'] = r.choice([1, 28, 40, 512, 7.5])
        layer.update(x=number(-300, 1400), y=number(-300, 800), rotation=r.choice([0, 0, 15, -90, 33.5, 360, -360]), opacity=r.choice([1, 1, 0.5, 0.25, 0]))
        if kind != 'heatmap' and kind != 'image' and kind != 'text' or kind == 'text':
            layer.update(w=layer['w'] if kind == 'text' else number(8, 900), h=number(8, 600))
        else:
            layer.update(w=number(8, 900), h=number(8, 600))
        scene['layers'].append(layer)
    return scene


def studio_damage(r, scene):
    import web_ui as w
    scene = w.studio_clone(scene)
    bad = [None, 0, -1, 9999, 'x', True, [], {}, 1.5, '#12345g', '', 2 ** 40, 0.5, 100000, 'none', '#FFFFFF']
    layers = scene['layers']
    if not layers or r.random() < 0.3:
        scene[r.choice(['width', 'height', 'background', 'schema', 'layers'])] = r.choice(bad)
    elif r.random() < 0.9:
        layer = r.choice(layers)
        key = r.choice(list(layer))
        layer[key] = r.choice(bad)
        if r.random() < 0.3:
            del layer[key]
    else:
        layers.append(layers[0])
    return scene


def bridge_mutate(rng, value, depth=0):
    """A seeded random change of a JSON request: numbers, strings, flags, list members and keys; what the family then says (an answer or a refusal) is Python's to decide."""
    kind = rng.random()
    if isinstance(value, bool):
        return (not value) if kind < 0.3 else value
    if isinstance(value, (int, float)):
        return rng.choice([0, 1, -1, 2, 7, 100, 0.5, -2.5, 1e21, 2 ** 53, 2 ** 60, value, value, value]) if kind < 0.5 else value
    if isinstance(value, str):
        return rng.choice(['', 'a', 'É', 'ｱｲｳ', '😀', ' x ', 'abc', '{x}', '1', value, value, value]) if kind < 0.5 else value
    if isinstance(value, list):
        items = [bridge_mutate(rng, item, depth + 1) for item in value]
        if items and kind < 0.15:
            items.pop(rng.randrange(len(items)))
        elif items and kind < 0.3:
            items.append(items[rng.randrange(len(items))])
        elif kind < 0.35:
            items.append(rng.choice([None, 1, 'x', [], {}]))
        return items
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if kind < 0.1 and rng.random() < 0.3:
                continue
            out[key] = bridge_mutate(rng, item, depth + 1)
        if kind > 0.95:
            out['extra'] = 1
        return out
    return value


def bridge_expected(family, text):
    """What Python says to the request text, the way a page shows it: ``("ok", value)`` or ``("refused", message)``; numbers past 2**53 are doubles, as in the page."""
    import web_ui
    try:
        answer = web_ui.pattern_run(family, web_ui.pattern_parse(text))
        return 'ok', json.loads(json.dumps(answer, ensure_ascii=False, allow_nan=False), parse_int=lambda s: int(s) if abs(int(s)) <= 2 ** 53 else float(s))
    except ValueError as error:
        return 'refused', str(error)


class PatternBridgeBrowserTests(unittest.TestCase):
    """``web_ui.py --pattern-serve`` in a real browser: the patterns page it serves runs the families that stay in Python through the bridge and shows exactly Python's answer; the bridge
    does not answer a page of another origin, a form post, a rebinding host or a request that is not JSON."""

    def setUp(self):
        import web_ui
        self.web_ui = web_ui
        self.bridges = []
        self.server = self.start_bridge()
        self.port = self.server.server_address[1]
        self.origin = f'http://127.0.0.1:{self.port}'
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        self.errors, self.external, self.posts = [], [], []

    def start_bridge(self, allow=()):
        server = self.web_ui.pattern_bridge(0, allow)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.bridges.append(server)
        return server

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        for server in self.bridges:
            server.shutdown()
            server.server_close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

    def page(self, url=None, context=None):
        page = (context or self.context).new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.posts.append((request.method, request.url)) if request.method == 'POST' else None)
        own = (self.origin + '/', f'http://localhost:{self.port}/')
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(own) else None)
        page.goto(url or self.origin + '/')
        page.wait_for_selector('[data-patterns-ready]')
        self.settled(page)
        return page

    @staticmethod
    def settled(page, runs=None):
        page.wait_for_function('([n]) => { const d = document.querySelector("#patterns").dataset; return d.run !== "running" && (n === null || Number(d.runs) === n) }', arg=[runs])

    def send(self, page, family, text):
        """Choose the family, put the request text in the box and run it; the box's own example run (made by choosing the family) is finished first."""
        if page.input_value('[data-patterns-run-family]') != family:
            page.select_option('[data-patterns-run-family]', family)
            self.settled(page)
        page.fill('[data-patterns-request]', text)
        runs = int(page.get_attribute('#patterns', 'data-runs')) + 1
        page.click('[data-patterns-run]')
        self.settled(page, runs)
        return page.get_attribute('#patterns', 'data-run'), page.get_attribute('#patterns', 'data-engine'), page.text_content('[data-patterns-status]'), page.text_content('[data-patterns-result]')

    def test_the_families_that_stay_in_python_run_there_and_show_its_answer(self):
        web_ui = self.web_ui
        page = self.page()
        self.assertEqual(page.get_attribute('#patterns', 'data-patterns-bridge'), '/pattern/')
        self.assertIn('run in Python through the local bridge', page.text_content('[data-patterns-bridge-note]'))
        stays = sorted(set(web_ui.PATTERN_RUNNERS) - set(web_ui.PATTERN_TWINS))
        self.assertEqual(stays, ['contract', 'convert', 'search', 'validate'])
        for family in stays + ['score']:
            example = web_ui.PATTERN_EXAMPLES[family] if family != 'score' else {'operation': 'tfidf', 'documents': ['a b', 'b c']}
            before = len(self.posts)
            outcome, engine, status, result = self.send(page, family, json.dumps(example))
            self.assertEqual((outcome, engine, status), ('ok', 'bridge' if family in stays or family == 'score' else 'browser', 'Run by Python through the local bridge.'), family)
            kind, expected = bridge_expected(family, json.dumps(example))
            self.assertEqual((kind, pat_canon(json.loads(result))), ('ok', pat_canon(expected)), family)
            self.assertGreaterEqual(len(self.posts) - before, 1, family)
            self.assertTrue(all(url == self.origin + '/pattern/' + family for method, url in self.posts[before:]), self.posts[before:])

    def test_twins_still_run_in_the_page_and_ask_nobody(self):
        web_ui = self.web_ui
        page = self.page()
        before = len(self.posts)
        for family in ('query', 'page', 'screen', 'native', 'select'):
            outcome, engine, status, result = self.send(page, family, json.dumps(web_ui.PATTERN_EXAMPLES[family]))
            self.assertEqual((outcome, engine, status), ('ok', 'browser', 'Run in this page.'), family)
        self.assertEqual(len(self.posts), before, 'a family the page runs itself is not sent anywhere')
        # score is a twin except for tf-idf, which goes to Python
        outcome, engine, status, result = self.send(page, 'score', '{"operation": "minheap", "values": [3, 1, 2], "pops": 1}')
        self.assertEqual((outcome, engine), ('ok', 'browser'))
        self.assertEqual(len(self.posts), before)
        outcome, engine, status, result = self.send(page, 'score', '{"operation": "tfidf", "documents": ["a b", "b c"]}')
        self.assertEqual((outcome, engine), ('ok', 'bridge'))
        self.assertEqual(len(self.posts), before + 1)

    def test_random_requests_get_the_answer_or_the_refusal_python_gives(self):
        web_ui = self.web_ui
        rng = random.Random('bridge-page')
        page = self.page()
        bases = {family: web_ui.PATTERN_EXAMPLES[family] for family in ('contract', 'convert', 'search', 'validate')}
        bases['score'] = {'operation': 'tfidf', 'documents': ['the cat', 'the dog sat'], 'query': 'cat'}
        seen = {'ok': 0, 'refused': 0}
        for _ in range(25):
            for family, base in bases.items():
                text = json.dumps(bridge_mutate(rng, base), ensure_ascii=rng.random() < 0.5)
                kind, expected = bridge_expected(family, text)
                outcome, engine, status, result = self.send(page, family, text)
                seen[kind] += 1
                if kind == 'ok':
                    self.assertEqual((outcome, engine, pat_canon(json.loads(result))), ('ok', 'bridge', pat_canon(expected)), (family, text))
                elif family == 'score' and 'tfidf' not in text:
                    continue
                else:
                    self.assertEqual((outcome, engine, status, result), ('refused', 'bridge', 'Refused: ' + expected, ''), (family, text))
        self.assertGreaterEqual(min(seen.values()), 20, seen)

    def test_a_request_that_is_not_json_is_not_sent_and_a_big_one_is_told_why(self):
        page = self.page()
        page.select_option('[data-patterns-run-family]', 'search')
        self.settled(page)
        before = len(self.posts)
        outcome, engine, status, result = self.send(page, 'search', '{"operation": ')
        self.assertEqual((outcome, status), ('invalid', 'Not JSON.'))
        self.assertEqual(len(self.posts), before)
        big = json.dumps({'operation': 'stem', 'text': 'a' * 70000})
        outcome, engine, status, result = self.send(page, 'search', big)
        self.assertEqual((outcome, status), ('error', 'The bridge answered 413: request is larger than 65536 bytes.'))
        outcome, engine, status, result = self.send(page, 'search', json.dumps({'operation': 'stem', 'text': 'walking ' * 5000}))
        self.assertEqual(outcome, 'ok', 'a request of 40 KB is run')

    def test_without_the_bridge_the_page_says_how_to_start_it(self):
        page = self.page()
        page.select_option('[data-patterns-run-family]', 'search')
        self.settled(page)
        self.bridges[0].shutdown()
        self.bridges[0].server_close()
        outcome, engine, status, result = self.send(page, 'search', json.dumps(self.web_ui.PATTERN_EXAMPLES['search']))
        self.assertEqual((outcome, engine, result), ('unreachable', 'bridge', ''))
        self.assertEqual(status, 'The Python bridge cannot be reached; start it with: python3 web_ui.py --pattern-serve')
        outcome, engine, status, result = self.send(page, 'query', json.dumps(self.web_ui.PATTERN_EXAMPLES['query']))
        self.assertEqual((outcome, engine), ('ok', 'browser'), 'the page still runs what it can run itself')

    def test_a_later_answer_does_not_overwrite_a_newer_request(self):
        page = self.page()
        slow = threading.Event()
        original = self.web_ui.pattern_run

        def held(family, request):
            if family == 'search' and isinstance(request, dict) and request.get('operation') == 'stem' and request.get('text') == 'slow':
                slow.wait(10)
            return original(family, request)
        with mock.patch.object(self.web_ui, 'pattern_run', held):
            page.select_option('[data-patterns-run-family]', 'search')
            self.settled(page)
            page.fill('[data-patterns-request]', json.dumps({'operation': 'stem', 'text': 'slow'}))
            page.click('[data-patterns-run]')
            self.assertEqual(page.get_attribute('#patterns', 'data-run'), 'running')
            page.fill('[data-patterns-request]', json.dumps({'operation': 'stem', 'text': 'walking'}))
            page.click('[data-patterns-run]')
            page.wait_for_function('document.querySelector("#patterns").dataset.run === "ok"')
            fast = page.text_content('[data-patterns-result]')
            slow.set()
            page.wait_for_timeout(500)
            self.assertEqual(page.text_content('[data-patterns-result]'), fast, 'the first, slower answer arrived last and was dropped')
            self.assertIn('walk', fast)

    def test_the_request_is_sent_as_typed_not_as_the_page_reads_it(self):
        """JSON.parse reads 1e999 as Infinity and JSON.stringify would write it null; Python refuses the number, and the page must show that, not an answer to another request."""
        page = self.page()
        for text in ('{"operation": "stem", "text": "walking", "n": 1e999}', '[1e999]', '{"operation": "stem", "text": "walking", "n": -1e999}'):
            kind, expected = bridge_expected('search', text)
            self.assertEqual(kind, 'refused', text)
            outcome, engine, status, result = self.send(page, 'search', text)
            self.assertEqual((outcome, engine, status, result), ('refused', 'bridge', 'Refused: ' + expected, ''), text)
        self.assertEqual(expected, 'JSON number out of range')

    def test_the_request_carries_neither_cookies_nor_a_referrer(self):
        self.context.add_cookies([{'name': 'session', 'value': 'secret', 'url': self.origin}])
        sent = []
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('requestfinished', lambda request: sent.append(request) if request.method == 'POST' else None)
        page.goto(self.origin + '/')
        page.wait_for_selector('[data-patterns-ready]')
        self.settled(page)
        outcome, engine, status, result = self.send(page, 'search', json.dumps(self.web_ui.PATTERN_EXAMPLES['search']))
        self.assertEqual((outcome, engine), ('ok', 'bridge'))
        self.assertGreaterEqual(len(sent), 1)
        for request in sent:
            headers = {name.lower(): value for name, value in request.all_headers().items()}
            self.assertNotIn('cookie', headers)
            self.assertNotIn('referer', headers)
            self.assertEqual(headers['content-type'], 'application/json')

    def test_an_answer_that_is_null_is_an_answer_and_a_200_that_is_not_json_is_not(self):
        page = self.page()
        page.select_option('[data-patterns-run-family]', 'search')
        self.settled(page)
        with mock.patch.object(self.web_ui, 'pattern_run', return_value=None):
            outcome, engine, status, result = self.send(page, 'search', '{"operation": "stem", "text": "walking"}')
        self.assertEqual((outcome, engine, status, result), ('ok', 'bridge', 'Run by Python through the local bridge.', 'null'))
        page.route('**/pattern/search', lambda route: route.fulfill(status=200, content_type='text/html', body='<html>not the bridge</html>'))
        outcome, engine, status, result = self.send(page, 'search', '{"operation": "stem", "text": "walking"}')
        self.assertEqual((outcome, status, result), ('error', 'The bridge answered 200.', ''))
        page.unroute('**/pattern/search')

    def test_a_late_failure_does_not_overwrite_a_newer_answer(self):
        page = self.page()
        page.select_option('[data-patterns-run-family]', 'search')
        self.settled(page)
        held = []

        def route(r):
            if not held:
                held.append(r)
            else:
                r.continue_()
        page.route('**/pattern/search', route)
        page.fill('[data-patterns-request]', json.dumps({'operation': 'stem', 'text': 'first'}))
        page.click('[data-patterns-run]')
        page.wait_for_function('document.querySelector("#patterns").dataset.run === "running"')
        page.wait_for_function('([n]) => Number(document.querySelector("#patterns").dataset.runs) === n', arg=[int(page.get_attribute('#patterns', 'data-runs'))])
        deadline = 100
        while not held and deadline:
            page.wait_for_timeout(50)
            deadline -= 1
        self.assertEqual(len(held), 1)
        page.fill('[data-patterns-request]', json.dumps({'operation': 'stem', 'text': 'walking'}))
        page.click('[data-patterns-run]')
        page.wait_for_function('document.querySelector("#patterns").dataset.run === "ok"')
        newer = page.text_content('[data-patterns-result]')
        held[0].abort()
        page.wait_for_timeout(500)
        self.assertEqual((page.get_attribute('#patterns', 'data-run'), page.text_content('[data-patterns-result]'), page.text_content('[data-patterns-status]')), ('ok', newer, 'Run by Python through the local bridge.'))
        page.unroute('**/pattern/search')

    def other_origin(self, allow=()):
        """A second server, on another port: a page there is another origin as far as the browser is concerned."""
        server, origin = WorldBrowserTests.serve({'other.html': '<!doctype html><title>other</title><body>other</body>'})
        self.addCleanup(server.shutdown)
        return origin

    def foreign_fetch(self, page, url, **options):
        return page.evaluate('async ([url, options]) => { try { const r = await fetch(url, options); return {status: r.status, text: await r.text()} } catch (e) { return {error: e.name} } }', [url, options])

    def test_a_page_of_another_origin_cannot_run_anything(self):
        calls = []
        original = self.web_ui.pattern_run
        with mock.patch.object(self.web_ui, 'pattern_run', lambda *a: (calls.append(a), original(*a))[1]):
            origin = self.other_origin()
            page = self.context.new_page()
            page.goto(origin + '/other.html')
            url = self.origin + '/pattern/search'
            body = json.dumps(self.web_ui.PATTERN_EXAMPLES['search'])
            json_post = self.foreign_fetch(page, url, method='POST', headers={'Content-Type': 'application/json'}, body=body)
            self.assertEqual(json_post, {'error': 'TypeError'}, 'the preflight is refused, so the request is never sent')
            simple = self.foreign_fetch(page, url, method='POST', mode='no-cors', headers={'Content-Type': 'text/plain'}, body=body)
            self.assertIn(simple.get('status', 0), (0,), 'a "simple" request gets an opaque answer, if any')
            read = self.foreign_fetch(page, self.origin + '/pattern/', method='GET')
            self.assertEqual(read, {'error': 'TypeError'}, 'nor can it read the family list')
            page.evaluate('([url, body]) => { const f = document.createElement("form"); f.method = "post"; f.action = url; f.enctype = "text/plain"; f.target = "sink"; const i = document.createElement("input"); i.name = body; i.value = ""; f.append(i); const w = document.createElement("iframe"); w.name = "sink"; document.body.append(w, f); f.submit() }', [url, body])
            page.wait_for_timeout(500)
            self.assertEqual(calls, [], 'no reference was run for any of them')
            self.assertEqual(self.posts, [])

    def test_a_page_of_an_origin_that_was_asked_for_may_call_it(self):
        origin = self.other_origin()
        server = self.start_bridge([origin])
        url = f'http://127.0.0.1:{server.server_address[1]}/pattern/search'
        page = self.context.new_page()
        page.goto(origin + '/other.html')
        body = json.dumps(self.web_ui.PATTERN_EXAMPLES['search'])
        allowed = self.foreign_fetch(page, url, method='POST', headers={'Content-Type': 'application/json'}, body=body)
        self.assertEqual((allowed['status'], pat_canon(json.loads(allowed['text']))), (200, pat_canon(self.web_ui.pattern_run('search', self.web_ui.PATTERN_EXAMPLES['search']))))
        self.assertEqual(self.foreign_fetch(page, self.origin + '/pattern/search', method='POST', headers={'Content-Type': 'application/json'}, body=body), {'error': 'TypeError'},
                         'the first bridge was not told about this origin')

    def test_a_host_that_is_not_the_bound_address_is_refused_even_when_it_resolves_to_it(self):
        if os.environ.get('WEBUI_BROWSER', 'chromium') != 'chromium':
            self.skipTest('the name is mapped to loopback with a Chromium flag; Python tests send every other Host header')
        browser = self.playwright.chromium.launch(args=['--host-resolver-rules=MAP rebind.test 127.0.0.1'])
        try:
            context = browser.new_context()
            page = context.new_page()
            response = page.goto(f'http://rebind.test:{self.port}/')
            self.assertEqual((response.status, json.loads(page.text_content('body'))), (403, {'error': 'origin not allowed'}))
            result = page.evaluate('async port => { try { const r = await fetch("http://rebind.test:" + port + "/pattern/"); return r.status } catch (e) { return e.name } }', self.port)
            self.assertEqual(result, 403)
        finally:
            browser.close()

    def test_localhost_is_the_same_loopback_origin_as_127_0_0_1(self):
        page = self.page(f'http://localhost:{self.port}/')
        outcome, engine, status, result = self.send(page, 'search', json.dumps(self.web_ui.PATTERN_EXAMPLES['search']))
        self.assertEqual((outcome, engine), ('ok', 'bridge'))

    def test_the_page_lists_the_families_the_bridge_knows(self):
        page = self.page()
        options = page.eval_on_selector_all('[data-patterns-run-family] option', 'els => els.map(e => e.value)')
        answer = self.foreign_fetch(page, self.origin + '/pattern/', method='GET')
        self.assertEqual((answer['status'], json.loads(answer['text'])['families']), (200, options))


class ScreensBrowserTests(PageCase):
    """The screens page in a real browser: the Hub, every kind of screen in several languages, the native examples (a Web Worker, real mouse drags with a long press) and a phone-sized
    layout. What the page shows is what Python's `screen_*` and `native_*` say; the requests themselves are checked against Python in PatternBrowserTests."""

    def setUp(self):
        from web_ui import screens_document
        self.server, self.origin = WorldBrowserTests.serve({'screens.html': screens_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        self.errors, self.external = [], []

    def page(self, hash_='', init=None, context=None):
        page = (context or self.context).new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('console', lambda message: self.errors.append(message.text) if message.type == 'error' else None)
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        if init:
            page.add_init_script(init)
        page.goto(self.origin + '/screens.html' + hash_)
        page.wait_for_selector('[data-screens_ready]')
        return page

    def route(self, page, number, locale=None):
        if locale is not None:
            page.select_option('[data-screens-locale]', locale)
        page.evaluate('n => { location.hash = "screen" + n }', number)
        page.wait_for_function('n => document.querySelector("#screens").dataset.route === String(n)', arg=number)

    def test_the_hub_lists_searches_and_switches_between_list_and_grid(self):
        import web_ui
        page = self.page()
        self.assertEqual((page.text_content('[data-screens-count]'), page.get_attribute('#screens', 'data-count'), page.get_attribute('#screens', 'data-mode')), ('198 / 198', '198', 'grid'))
        self.assertEqual(page.eval_on_selector_all('[data-screens-items] a', 'els => els.map(e => e.getAttribute("href"))')[:3], ['#screen1', '#screen2', '#screen3'])
        self.assertEqual(page.text_content('[data-screens-title]'), web_ui.screen_text('eng', 'hub.title'))
        page.click('[data-screens-mode="list"]')
        self.assertEqual((page.get_attribute('#screens', 'data-mode'), page.get_attribute('[data-screens-mode="list"]', 'aria-pressed'), page.get_attribute('[data-screens-items]', 'data-mode')), ('list', 'true', 'list'))
        page.fill('[data-screens-query]', 'Transformed Result List')
        self.assertEqual((page.text_content('[data-screens-count]'), page.get_attribute('#screens', 'data-count')), ('1 / 198', '1'))
        page.click('[data-screens-mode="grid"]')
        self.assertEqual(page.input_value('[data-screens-query]'), 'Transformed Result List', 'the search survives a change of view')
        page.fill('[data-screens-query]', 'このような画面はありません')
        self.assertEqual((page.text_content('[data-screens-empty]'), page.is_visible('[data-screens-empty]')), (web_ui.screen_text('eng', 'hub.empty'), True))
        page.click('[data-screens-clear]')
        self.assertEqual((page.input_value('[data-screens-query]'), page.text_content('[data-screens-count]'), page.is_hidden('[data-screens-clear]')), ('', '198 / 198', True))
        page.fill('[data-screens-query]', '  SCREEN198 ')
        page.click('[data-screens-items] a')
        page.wait_for_function('document.querySelector("#screens").dataset.route === "198"')
        self.assertTrue(page.url.endswith('#screen198'))
        page.click('[data-screens-back]')
        page.wait_for_function('document.querySelector("#screens").dataset.route === ""')
        self.assertEqual(page.text_content('[data-screens-title]'), web_ui.screen_text('eng', 'hub.title'))
        self.assertEqual({page.get_attribute(f'a[href="./{name}.html"]', 'href') for name in ('mcp-lab', 'api-stub', 'index')}, {'./mcp-lab.html', './api-stub.html', './index.html'})

    def test_the_hub_speaks_every_language_and_arabic_runs_right_to_left(self):
        import web_ui
        page = self.page()
        for locale in web_ui.SCREEN_LOCALES:
            page.select_option('[data-screens-locale]', locale)
            hub = web_ui.screen_hub(locale)
            self.assertEqual((page.text_content('[data-screens-title]'), page.get_attribute('[data-screens-stage]', 'lang'), page.get_attribute('[data-screens-stage]', 'dir')), (hub['title'], hub['lang'], hub['dir']), locale)
            self.assertEqual(page.get_attribute('[data-screens-query]', 'placeholder'), hub['hint'], locale)
            self.assertEqual(page.get_attribute('[data-screens-mode="list"]', 'title') or page.text_content('[data-screens-mode="list"]'), hub['tooltips']['list'], locale)
        page.select_option('[data-screens-locale]', 'swa')
        self.assertEqual(page.get_attribute('[data-screens-stage]', 'dir'), 'ltr')
        page.select_option('[data-screens-locale]', 'ara')
        self.assertEqual((page.get_attribute('[data-screens-stage]', 'dir'), page.evaluate('getComputedStyle(document.querySelector("[data-screens-stage]")).direction')), ('rtl', 'rtl'))

    def test_screens_show_what_python_says_in_random_languages(self):
        import web_ui
        rng = random.Random('screens-page')
        page = self.page()
        generic = [n for n in range(1, 199) if web_ui.screen_route(n)['kind'] == 'generic']
        for _ in range(40):
            number, locale = rng.choice(generic), rng.choice(web_ui.SCREEN_LOCALES)
            self.route(page, number, locale)
            view = web_ui.screen_view(number, locale)
            self.assertEqual(page.text_content('[data-screens-title]'), view['title'], (number, locale))
            self.assertEqual(page.eval_on_selector('.ui-screens-headline', 'e => e.textContent'), view['headline'], (number, locale))
            self.assertEqual(page.text_content('[data-screens-back]'), '← ' + view['back'], (number, locale))
            self.assertEqual((page.get_attribute('[data-screens-stage]', 'lang'), page.get_attribute('[data-screens-stage]', 'dir')), (view['lang'], view['dir']))
            self.assertEqual(page.eval_on_selector_all('[data-screens-tabs="ctab"] [data-tab]', 'els => els.map(e => e.textContent)'), [tab['label'] for tab in view['tabs']] if view['tabs'] else [], (number, locale))
            if view['body']['template'] == 'tabs':
                self.assertEqual(page.eval_on_selector_all('[data-template="tabs"] [role="tab"]', 'els => els.map(e => e.textContent)'), view['body']['tabs'], (number, locale))
            chips = view['chips'] or (view['useCase'] or {}).get('chips') or []
            self.assertEqual(page.eval_on_selector_all('.ui-screens-chips > li', 'els => els.map(e => e.textContent)'), [f"{c['avatar']} {c['text']}" for c in chips], (number, locale))
        self.route(page, 3, 'jpn')
        view = web_ui.screen_view(3, 'jpn')
        self.assertEqual(page.eval_on_selector_all('.ui-screens-chips > li', 'els => els.map(e => e.textContent)'), [f"{c['avatar']} {c['text']}" for c in view['chips']])
        self.assertEqual((view['chips'][0]['text'].startswith('ナビゲーション: '), page.text_content('[data-screens-back]')), (True, '← ハブに戻る'))
        page.click('[data-screens-back]')
        page.wait_for_function('document.querySelector("#screens").dataset.route === ""')

    def test_each_template_reacts_to_real_clicks_and_typing(self):
        import web_ui
        page = self.page()
        # 22 screens carry a detail: their use case comes first and the template sits on the UI sample tab; every other number shows the template at once
        self.assertEqual(sorted(n for n in range(1, 199) if SCREENS_FIXTURE[n - 1].get('detail')), [1, 2, 19, 20, 37, 38, 55, 56, 73, 74, 91, 92, 109, 110, 127, 128, 145, 146, 163, 164, 181, 182])
        # a list and a detail
        self.route(page, 4)
        self.assertEqual(page.eval_on_selector_all('.ui-screens-list > li', 'els => els.length'), len(web_ui.screen_view(4, 'eng')['body']['items']))
        self.route(page, 21)
        self.assertEqual(page.text_content('[data-template="detail"] p.ui-muted'), web_ui.screen_text('eng', 'patternTemplate.screenIdLabel', (('screenDataId', 21),)))
        # a detail screen: use case first, the template after a click on the second tab, which keeps the focus
        self.route(page, 37)
        self.assertEqual((page.get_attribute('[data-tab="usecase"]', 'aria-selected'), page.is_visible('[data-screens-usecase]'), page.locator('[data-template="form"]').count()), ('true', True, 0))
        page.click('[data-tab="ui"]')
        self.assertEqual((page.evaluate('document.activeElement.dataset.tab'), page.locator('[data-screens-usecase]').count(), page.locator('[data-template="form"]').count()), ('ui', 0, 1))
        page.press('[data-tab="ui"]', 'ArrowLeft')
        self.assertEqual((page.get_attribute('[data-tab="usecase"]', 'aria-selected'), page.locator('[data-template="form"]').count()), ('true', 0), 'the arrow keys move between the two tabs')
        # a form, submitted by the button and by Enter
        self.route(page, 39)
        page.fill('[data-screens-input]', 'こんにちは')
        page.click('[data-screens-submit]')
        self.assertEqual(page.text_content('[data-screens-snackbar]'), web_ui.screen_text('eng', 'patternTemplate.submitted', (('value', 'こんにちは'),)))
        page.fill('[data-screens-input]', 'again')
        page.press('[data-screens-input]', 'Enter')
        self.assertEqual(page.text_content('[data-screens-snackbar]'), web_ui.screen_text('eng', 'patternTemplate.submitted', (('value', 'again'),)))
        self.assertEqual(page.input_value('[data-screens-input]'), 'again')
        # a search
        self.route(page, 57)
        self.assertEqual(page.text_content('[data-screens-result]'), web_ui.screen_text('eng', 'patternTemplate.typeToFilter'))
        page.fill('[data-screens-input]', 'abc')
        self.assertEqual(page.text_content('[data-screens-result]'), web_ui.screen_text('eng', 'patternTemplate.resultFor', (('query', 'abc'),)))
        page.fill('[data-screens-input]', '   ')
        self.assertEqual(page.text_content('[data-screens-result]'), web_ui.screen_text('eng', 'patternTemplate.resultFor', (('query', '   '),)), 'only the empty string is no query, as in the original')
        page.fill('[data-screens-input]', '')
        self.assertEqual(page.text_content('[data-screens-result]'), web_ui.screen_text('eng', 'patternTemplate.typeToFilter'))
        # tabs: click, arrow keys and End
        self.route(page, 75)
        views = web_ui.screen_view(75, 'eng')['body']
        page.click('[data-focus="tpl-2"]')
        self.assertEqual((page.get_attribute('[data-screens-panel]', 'data-screens-panel'), page.get_attribute('[data-focus="tpl-2"]', 'aria-selected')), ('2', 'true'))
        page.press('[data-focus="tpl-2"]', 'ArrowRight')
        self.assertEqual((page.get_attribute('[data-screens-panel]', 'data-screens-panel'), page.evaluate('document.activeElement.dataset.focus')), ('0', 'tpl-0'))
        page.press('[data-focus="tpl-0"]', 'End')
        self.assertEqual(page.get_attribute('[data-screens-panel]', 'data-screens-panel'), '2')
        page.press('[data-focus="tpl-2"]', 'Home')
        self.assertEqual(page.get_attribute('[data-screens-panel]', 'data-screens-panel'), '0')
        self.assertEqual(page.eval_on_selector_all('[role="tab"]', 'els => els.map(e => e.textContent)'), views['tabs'])
        # bottom navigation
        self.route(page, 100)
        page.click('[data-focus="nav-1"]')
        self.assertEqual((page.text_content('[data-screens-destination]').startswith('Destination 2'), page.get_attribute('[data-focus="nav-1"]', 'aria-current'), page.get_attribute('[data-focus="nav-0"]', 'aria-current')), (True, 'page', None))
        # a drawer and a grid
        self.route(page, 111)
        self.assertEqual(page.eval_on_selector_all('aside li', 'els => els.map(e => e.textContent)'), ['Home', 'Library', 'Settings'])
        self.route(page, 147)
        self.assertEqual(page.eval_on_selector_all('.ui-screens-grid > li', 'els => els.length'), 8)
        # a dialog: opens, takes the focus, closes by button and by Escape and gives the focus back
        self.route(page, 129)
        self.assertEqual(page.locator('[data-screens-dialog]').count(), 0)
        page.click('[data-screens-open]')
        self.assertEqual(page.locator('[data-screens-dialog]').count(), 1)
        self.assertEqual(page.evaluate('document.activeElement.hasAttribute("data-screens-close")'), True)
        page.click('[data-screens-close]')
        self.assertEqual((page.locator('[data-screens-dialog]').count(), page.evaluate('document.activeElement.hasAttribute("data-screens-open")')), (0, True))
        page.click('[data-screens-open]')
        page.keyboard.press('Escape')
        self.assertEqual((page.locator('[data-screens-dialog]').count(), page.evaluate('document.activeElement.hasAttribute("data-screens-open")')), (0, True))
        # an async screen shows its progress for half a second
        self.route(page, 165)
        page.click('[data-screens-start]')
        self.assertEqual((page.is_visible('[data-screens-progress]'), page.is_disabled('[data-screens-start]')), (True, True))
        page.wait_for_selector('[data-screens-progress]', state='detached', timeout=3000)
        self.assertTrue(page.is_enabled('[data-screens-start]'))
        # a settings switch starts on, as the view says
        self.route(page, 185)
        self.assertEqual(web_ui.screen_view(185, 'eng')['body']['enabled'], True)
        self.assertTrue(page.is_checked('[data-screens-switch]'))
        page.click('[data-screens-switch]')
        self.assertFalse(page.is_checked('[data-screens-switch]'))

    def test_screen_6_searches_the_real_catalogue_and_opens_a_route(self):
        import web_ui
        page = self.page()
        self.route(page, 6)
        self.assertEqual(page.text_content('[data-screens-count]'), '198 / 198')
        page.fill('[data-screens-input]', 'Transformed Result List')
        self.assertEqual((page.text_content('[data-screens-count]'), page.eval_on_selector_all('[data-screens-items] a', 'els => els.map(e => e.dataset.screen)')), ('1 / 198', ['5']))
        page.click('[data-screens-items] a')
        page.wait_for_function('document.querySelector("#screens").dataset.route === "5"')
        self.assertEqual(page.evaluate('document.querySelector("#screens").dataset.route'), '5')
        self.assertIn('Screen5Page', page.text_content('[data-screens-dedicated]'))
        self.route(page, 6, 'jpn')
        page.fill('[data-screens-input]', '存在しない検索語')
        self.assertEqual((page.text_content('[data-screens-count]'), page.text_content('[data-screens-empty]')), ('0 / 198', web_ui.screen_text('jpn', 'hub.empty')))
        page.click('[data-screens-clear]')
        self.assertEqual((page.text_content('[data-screens-count]'), page.input_value('[data-screens-input]'), page.evaluate('document.activeElement.hasAttribute("data-screens-input")')), ('198 / 198', '', True))

    def test_the_validation_and_conversion_screens_link_to_pinned_sources_and_request_nothing(self):
        import web_ui
        page = self.page()
        for number in (91, 99, 103, 110):
            self.route(page, number)
            view = web_ui.screen_links_view(number)
            self.assertEqual(page.text_content('[data-screens-title]'), view['title'])
            self.assertEqual(page.eval_on_selector_all('[data-screens-link]', 'els => els.map(e => e.href)'), [link['url'] for link in view['links']])
            self.assertEqual(page.eval_on_selector_all('[data-screens-link]', 'els => els.every(e => e.rel === "noopener noreferrer" && e.target === "_blank")'), True)
            self.assertEqual(page.text_content('[data-screens-limit]'), view['limitation'])
            self.assertIn('patterns.html', page.get_attribute('[data-screens-reference]', 'href'))

    def test_an_address_that_names_no_screen_shows_the_hub(self):
        for bad in ('#screen0', '#screen199', '#screenx', '#screen1e1', '#something'):
            page = self.page(bad)
            self.assertEqual((page.get_attribute('#screens', 'data-route'), page.get_attribute('[data-screens-stage]', 'data-kind')), ('', 'hub'), bad)
            page.close()
        page = self.page('#screen37')
        self.assertEqual((page.get_attribute('#screens', 'data-route'), page.get_attribute('[data-screens-stage]', 'data-kind')), ('37', 'generic'))

    # --- the native examples
    def card(self, page, number):
        return page.locator(f'[data-native="{number}"]')

    def test_the_counters_and_pairs_count_like_the_original_widgets(self):
        import web_ui
        page = self.page()
        self.assertEqual(page.get_attribute('[data-screens-native]', 'data-count'), '27')
        for number in (151, 156, 158, 159, 162, 163, 166, 167, 168, 169):
            card = self.card(page, number)
            self.assertEqual(card.locator('h4').text_content(), web_ui.native_view(number, web_ui.native_initial(number))['title'])
            self.assertIn('カウント: 0', card.text_content())
            card.locator('[data-native-action="increment"]').click()
            self.assertEqual((card.get_attribute('data-count'), 'カウント: 1' in card.text_content()), ('1', True), number)
            card.locator('[data-native-action="reset"]').click()
            self.assertIn('カウント: 0', card.text_content())
            self.assertEqual(card.locator('[data-native-run]').count(), 0)
        notified = lambda number: int(re.search(r'通知回数: (\d+)', self.card(page, number).text_content()).group(1))
        before = {number: notified(number) for number in (158, 159)}
        for number in (158, 159):
            self.card(page, number).locator('[data-native-action="reset"]').click()
        self.assertEqual(notified(159) - before[159], 0, 'a ValueNotifier does not notify for the value it has')
        self.assertEqual(notified(158) - before[158], 1, 'a ChangeNotifier notifies on every call')
        # two values: a scope or a model, an atom or a state: what each rebuilds, taken from Python's own steps
        for number in (157, 160, 161, 170):
            card, state = self.card(page, number), web_ui.native_initial(number)
            for action in ('left', 'right', 'left', 'left'):
                card.locator(f'[data-native-action="{action}"]').click()
                state = web_ui.native_step(number, state, action)
                self.assertEqual(card.get_attribute('data-order') or '', '')
                shown = card.text_content()
                for line in web_ui.native_view(number, state)['lines']:
                    self.assertIn(line, shown, (number, action))
        self.assertIn('再ビルド left: 3 / right: 1', self.card(page, 161).text_content(), 'a model rebuilds only the side that changed')
        self.assertIn('再ビルド left: 4 / right: 4', self.card(page, 160).text_content(), 'a scope rebuilds both sides every time')

    def test_a_sum_of_squares_runs_in_a_real_worker_and_says_so_only_then(self):
        page = self.page(init='window.__workers = 0; const W = window.Worker; window.Worker = function (...a) { window.__workers++; return new W(...a) }')
        for number, label in ((136, 'Web Worker（別スレッドで実行）'), (137, 'compute（Web Worker）')):
            card = self.card(page, number)
            self.assertEqual(card.locator('[data-native-status]').text_content(), '未実行')
            card.locator('[data-native-run]').click()
            expect(card).to_have_attribute('data-runs', '1')
            self.assertEqual((card.locator('[data-native-status]').text_content(), card.get_attribute('data-engine'), card.get_attribute('data-result')), (f'{label}: 55', 'worker', '55'))
        self.assertEqual(page.evaluate('window.__workers'), 2, 'one real worker per run')
        card = self.card(page, 136)
        card.locator('[data-native-values]').fill('3, -4, 12')
        card.locator('[data-native-run]').click()
        expect(card).to_have_attribute('data-runs', '2')
        self.assertEqual(card.get_attribute('data-result'), str(9 + 16 + 144))
        card.locator('[data-native-values]').fill('94906266')
        card.locator('[data-native-run]').click()
        self.assertEqual(card.locator('[data-native-status]').text_content(), '失敗: the sum of squares must not exceed 2**53')
        card.locator('[data-native-values]').fill('1.5')
        card.locator('[data-native-run]').click()
        self.assertEqual(card.locator('[data-native-status]').text_content(), '失敗: values must be integers separated by commas')
        self.assertEqual(page.evaluate('window.__workers'), 3, 'a refused request starts no worker')
        page.close()
        context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        page = self.page(init='delete window.Worker', context=context)
        card = self.card(page, 137)
        card.locator('[data-native-run]').click()
        expect(card).to_have_attribute('data-runs', '1')
        self.assertEqual((card.locator('[data-native-status]').text_content(), card.get_attribute('data-engine')), ('compute（同期フォールバック・別スレッド保証なし）: 55', 'fallback'), 'without a Worker the page does not claim one')
        context.close()

    def drag(self, page, source, target, hold=0, to=0.85, steps=20):
        source.evaluate('e => e.scrollIntoView({block: "center"})')
        a, b = source.bounding_box(), target.bounding_box()
        page.mouse.move(a['x'] + a['width'] / 2, a['y'] + a['height'] / 2)
        page.mouse.down()
        if hold:
            page.wait_for_timeout(hold)
        page.mouse.move(b['x'] + b['width'] / 2, b['y'] + b['height'] * to, steps=steps)
        page.mouse.up()

    def order(self, page, number):
        return self.card(page, number).get_attribute('data-order')

    def test_lists_reorder_by_a_real_mouse_drag_and_a_long_press_where_the_original_has_one(self):
        page = self.page()
        for number in (171, 172):
            card = self.card(page, number)
            self.assertEqual(self.order(page, number), 'A,B,C')
            self.drag(page, card.locator('[data-item="A"] [data-grip]'), card.locator('[data-item="C"]'))
            self.assertEqual(self.order(page, number), 'B,C,A', number)
            self.assertIn('順序: B, C, A', card.text_content())
            self.drag(page, card.locator('[data-item="C"] [data-grip]'), card.locator('[data-item="B"]'), to=0.1)
            self.assertEqual(self.order(page, number), 'C,B,A', number)
            self.drag(page, card.locator('[data-item="B"] [data-grip]'), card.locator('[data-item="B"]'))
            self.assertEqual(self.order(page, number), 'C,B,A', 'dropped on its own place')
        card = self.card(page, 184)
        self.drag(page, card.locator('[data-item="A"] [data-grip]'), card.locator('[data-item="C"]'))
        self.assertEqual(self.order(page, 184), 'A,B,C', 'a drag without the long press is not a reorder')
        self.drag(page, card.locator('[data-item="A"] [data-grip]'), card.locator('[data-item="C"]'), hold=700)
        self.assertEqual(self.order(page, 184), 'B,C,A')
        page.mouse.move(0, 0)
        grip = card.locator('[data-item="B"] [data-grip]').bounding_box()
        page.mouse.move(grip['x'] + 4, grip['y'] + 4)
        page.mouse.down()
        page.mouse.move(grip['x'] + 40, grip['y'] + 4, steps=4)
        page.wait_for_timeout(700)
        page.mouse.move(grip['x'] + 40, grip['y'] + 200, steps=4)
        page.mouse.up()
        self.assertEqual(self.order(page, 184), 'B,C,A', 'moving before the half second is up cancels the press')

    def test_pattern_173_swaps_two_cells_and_follows_the_item_not_the_slot(self):
        page = self.page()
        card = self.card(page, 173)
        self.drag(page, card.locator('[data-item="A"] [data-grip]'), card.locator('[data-item="B"]'))
        self.assertEqual(self.order(page, 173), 'A,B,C', 'no long press, no drag')
        self.drag(page, card.locator('[data-item="A"] [data-grip]'), card.locator('[data-item="B"]'), hold=700)
        self.assertEqual(self.order(page, 173), 'B,A,C')
        self.drag(page, card.locator('[data-item="A"] [data-grip]'), card.locator('[data-item="C"]'), hold=700)
        self.assertEqual(self.order(page, 173), 'B,C,A')
        self.assertIn('順序: B, C, A', card.text_content())
        self.drag(page, card.locator('[data-item="B"] [data-grip]'), card.locator('[data-item="B"]'), hold=700)
        self.assertEqual(self.order(page, 173), 'B,C,A', 'dropping on itself swaps nothing')
        self.assertEqual(card.locator('[data-over]').count() + card.locator('[data-dragging]').count(), 0, 'nothing is left marked after a drop')

    def test_every_drag_has_a_button_and_the_other_lists_work(self):
        page = self.page()
        card = self.card(page, 171)
        card.get_by_role('button', name='Move A down').click()
        self.assertEqual(self.order(page, 171), 'B,A,C')
        card.get_by_role('button', name='Move C up').click()
        self.assertEqual(self.order(page, 171), 'B,C,A')
        self.assertTrue(card.get_by_role('button', name='Move B up').is_disabled())
        self.assertTrue(card.get_by_role('button', name='Move A down').is_disabled())
        self.assertEqual(page.evaluate('document.activeElement.getAttribute("aria-label")'), 'Move C up', 'the focus stays on the button that was pressed')
        card = self.card(page, 173)
        card.get_by_role('button', name='Swap A with the next').click()
        card.get_by_role('button', name='Swap A with the next').click()
        self.assertEqual(self.order(page, 173), 'B,C,A')
        card = self.card(page, 174)
        card.locator('[data-native-action="insert"]').click()
        card.locator('[data-native-action="insert"]').click()
        self.assertEqual((self.order(page, 174), 'N2' in card.locator('[data-native-items] li').first.text_content()), ('N2,N1,A,B,C', True))
        self.assertEqual(card.locator('[data-native-items] li').first.get_attribute('data-new'), '')
        card = self.card(page, 175)
        for expected in ('B,C', 'C', ''):
            card.locator('[data-native-action="remove"]').click()
            self.assertEqual(self.order(page, 175), expected)
        self.assertTrue(card.locator('[data-native-action="remove"]').is_disabled())
        card = self.card(page, 183)
        self.assertTrue(card.locator('[data-native-action="delete_selected"]').is_disabled())
        card.locator('[data-native-select="A"]').check()
        card.locator('[data-native-select="C"]').check()
        self.assertIn('選択数: 2', card.text_content())
        card.locator('[data-native-select="C"]').uncheck()
        card.locator('[data-native-action="delete_selected"]').click()
        self.assertEqual((self.order(page, 183), card.get_attribute('data-selected')), ('B,C', ''))
        self.assertIn('選択数: 0', card.text_content())

    def test_a_native_route_opens_the_example_on_its_own(self):
        page = self.page('#screen174')
        self.assertEqual((page.get_attribute('[data-screens-stage]', 'data-kind'), page.locator('[data-screens-stage] [data-native="174"]').count(), page.locator('[data-screens-stage] [data-native="174"] h4').text_content()), ('native', 1, 'Pattern 174: InsertItem'))
        page.locator('[data-screens-stage] [data-native-action="insert"]').click()
        self.assertEqual(page.locator('[data-screens-stage] [data-native="174"]').get_attribute('data-order'), 'N1,A,B,C')
        page.click('[data-screens-back]')
        page.wait_for_function('document.querySelector("#screens").dataset.route === ""')
        page = self.page('#screen136')
        self.assertEqual(page.locator('[data-screens-stage] [data-native="136"] [data-native-status]').text_content(), '未実行')

    def test_the_page_fits_a_phone_and_a_desktop(self):
        for width, height in ((320, 700), (390, 844), (1280, 800)):
            page = self.page('#screen3')
            page.set_viewport_size({'width': width, 'height': height})
            for hash_ in ('', '#screen3', '#screen6', '#screen37', '#screen74', '#screen130', '#screen91', '#screen171'):
                page.evaluate('h => { location.hash = h }', hash_)
                page.wait_for_timeout(50)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width, (width, hash_))
                self.assertLessEqual(page.evaluate('Math.max(...[...document.querySelectorAll("#screens *")].filter(e => e.offsetParent !== null).map(e => e.getBoundingClientRect().right))'), width + 1, (width, hash_))
            page.evaluate('location.hash = ""')
            page.wait_for_timeout(50)
            gallery = page.evaluate('Math.max(...[...document.querySelectorAll("[data-screens-native] *")].map(e => e.getBoundingClientRect().right))')
            self.assertLessEqual(gallery, width + 1, (width, 'native gallery'))
            page.close()
        page = self.page()
        page.set_viewport_size({'width': 320, 'height': 700})
        page.evaluate('location.hash = "#screen171"')
        small = page.evaluate('[...document.querySelectorAll("#screens button, #screens select, #screens input:not([type=checkbox]), #screens a.ui-button, #screens .ui-screens-checks label")].filter(e => e.offsetParent !== null).map(e => Math.round(e.getBoundingClientRect().height))')
        self.assertTrue(small and all(h >= 40 for h in small), small)
        boxes = page.evaluate('[...document.querySelectorAll("#screens input[type=checkbox]")].map(e => Math.round(Math.min(e.getBoundingClientRect().width, e.getBoundingClientRect().height)))')
        self.assertTrue(boxes and all(h >= 24 for h in boxes), boxes)


    def test_a_native_card_has_an_address_the_page_scrolls_to(self):
        import web_ui
        for number in web_ui.NATIVE_NUMBERS:
            page = self.page('#native-' + str(number))
            page.set_viewport_size({'width': 390, 'height': 664})
            page.wait_for_timeout(50)
            page.evaluate('h => { location.hash = ""; location.hash = h }', 'native-' + str(number))
            page.wait_for_timeout(50)
            self.assertEqual(page.evaluate('n => document.querySelectorAll("#native-" + n).length', number), 1, number)
            top = page.evaluate('n => Math.round(document.getElementById("native-" + n).getBoundingClientRect().top)', number)
            at_end = page.evaluate('window.scrollY + innerHeight >= document.documentElement.scrollHeight - 1')
            self.assertTrue(abs(top) <= 2 or at_end, (number, top, 'a card near the end of the page cannot reach the top'))
            self.assertEqual(page.get_attribute('#screens', 'data-route'), '', 'the hub stays; a card address is not a screen route')
            page.close()
        page = self.page('#native-9999')
        self.assertEqual((page.evaluate('window.scrollY'), page.get_attribute('#screens', 'data-route')), (0, ''), 'an address of no card does nothing')

    def test_the_hub_search_stays_inside_the_stage_and_keeps_its_text_and_count_across_resizes(self):
        """The original's Screen6 specs (stays inside body at 390x500 and 1180x757 by mouse and by keyboard; preserves the search across a resize through the compact boundary) on this page's
        Hub: the same editor, still focused, with the same text and the count "1 / 198", after every crossing, with the search box and the count fully inside the stage."""
        query = 'Transformed Result List'
        for start in ((1180, 757), (1180, 500), (390, 500)):
            for how in ('keyboard', 'mouse'):
                page = self.page()
                page.set_viewport_size({'width': start[0], 'height': start[1]})
                stage, box, count = page.locator('[data-screens-stage]'), page.locator('[data-screens-query]'), page.locator('[data-screens-count]')

                def inside():
                    s, b, c = stage.bounding_box(), box.bounding_box(), count.bounding_box()
                    return all(x['height'] > 0 and x['x'] >= s['x'] - 1 and x['x'] + x['width'] <= s['x'] + s['width'] + 1 for x in (b, c))
                self.assertTrue(inside(), (start, how))
                if how == 'mouse':
                    page.mouse.move(start[0] / 2, start[1] / 2)
                    page.mouse.wheel(0, 350)
                    box.scroll_into_view_if_needed()
                    box.click()
                else:
                    box.focus()
                self.assertTrue(box.evaluate('el => el === document.activeElement'), (start, how))
                page.keyboard.type(query, delay=20)
                self.assertEqual((box.input_value(), count.text_content()), (query, '1 / 198'), (start, how))
                original = box.element_handle()
                typed = query
                for size in ((390, 500), (320, 700), (1180, 757), (1180, 500), (320, 500), (1280, 800)):
                    page.set_viewport_size({'width': size[0], 'height': size[1]})
                    page.wait_for_timeout(50)
                    self.assertTrue(box.evaluate('(el, o) => el === o', original), (start, how, size))
                    self.assertTrue(box.evaluate('el => el === document.activeElement'), (start, how, size))
                    page.keyboard.type('x')
                    typed += 'x'
                    self.assertEqual((box.input_value(), count.text_content(), page.get_attribute('#screens', 'data-count')), (typed, '0 / 198', '0'), (start, how, size))
                    page.keyboard.press('Backspace')
                    typed = typed[:-1]
                    self.assertEqual((box.input_value(), count.text_content()), (typed, '1 / 198'), (start, how, size))
                    self.assertTrue(inside(), (start, how, size))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), size[0], (start, how, size))
                page.close()


class ImageStudioBrowserTests(PageCase):
    """The image studio page in a real browser: its twin gives Python's answer (the recorded core.js outputs, and seeded random scenes, layers, histories and refusals with their text), and the
    editor places, moves, edits, imports, exports and restores layers."""

    def setUp(self):
        from web_ui import imagestudio_document
        self.server, self.origin = WorldBrowserTests.serve({'image-studio.html': imagestudio_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1400}, accept_downloads=True)
        self.errors, self.external = [], []

    def page(self, size=None, accept=True):
        page = self.context.new_page()
        if size:
            page.set_viewport_size(size)
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        page.on('dialog', lambda dialog: dialog.accept() if accept else dialog.dismiss())
        page.goto(self.origin + '/image-studio.html')
        page.wait_for_selector('[data-ui-imagestudio][data-ready]')
        return page

    # --- helpers ------------------------------------------------------------------------------------------------------------------------------
    def scene(self, page):
        return page.evaluate('() => webUiImageStudio.app.scene')

    def data(self, page, name):
        return page.get_attribute('#imagestudio', 'data-' + name)

    def status(self, page):
        return page.inner_text('[data-is="status"]')

    def painted(self, page):
        return int(self.data(page, 'painted'))

    def paint(self, page, action):
        """Run an action and wait until the board has been drawn again."""
        before = self.painted(page)
        action()
        page.wait_for_function('b => +document.querySelector("[data-ui-imagestudio]").dataset.painted > b', arg=before)

    def at(self, page, x, y):
        box = page.evaluate('() => { const r = document.querySelector("[data-is=board] svg").getBoundingClientRect(); return [r.x, r.y, r.width, r.height] }')
        scene = self.scene(page)
        return box[0] + x * box[2] / scene['width'], box[1] + y * box[3] / scene['height']

    def press(self, page, x, y):
        sx, sy = self.at(page, x, y)
        self.paint(page, lambda: page.mouse.click(sx, sy))

    def tool(self, page, name):
        page.check(f'input[name="is-tool"][value="{name}"]')

    def drag_handle(self, page, start, end):
        """Press the resize handle at ``start`` and release at ``end`` (scene coordinates) with events sent to the handle itself, so the engine's hit testing of a rotated corner is not part of the check."""
        (sx, sy), (ex, ey) = self.at(page, *start), self.at(page, *end)
        page.evaluate("""([sx, sy, ex, ey]) => { const board = document.querySelector('[data-is=board]'), handle = board.querySelector('[data-handle]');
            const make = (type, x, y) => new PointerEvent(type, {clientX: x, clientY: y, button: 0, bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse', isPrimary: true});
            handle.dispatchEvent(make('pointerdown', sx, sy)); board.dispatchEvent(make('pointermove', (sx + ex) / 2, (sy + ey) / 2)); board.dispatchEvent(make('pointermove', ex, ey)); board.dispatchEvent(make('pointerup', ex, ey)) }""", [sx, sy, ex, ey])

    def blank(self, page):
        self.paint(page, lambda: page.click('[data-is="blank"]'))
        self.assertEqual(self.data(page, 'layers'), '0')

    def call(self, page, jobs):
        return page.evaluate(STUDIO_CALL, jobs)

    def same(self, got, expect):
        return got == expect

    def pixels(self, data):
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.convert('RGBA')

    def download(self, page, selector):
        with page.expect_download() as download:
            page.click(selector)
        return download.value, open(download.value.path(), 'rb').read()

    # --- the twin gives Python's answer ----------------------------------------------------------------------------------------------------------
    def test_every_recorded_core_js_output_is_reproduced_in_the_page(self):
        page = self.page()
        cases = STUDIO_GOLDEN['cases']
        outcomes = self.call(page, [[c['fn'], c['arg']] for c in cases])
        bad = []
        for case, got in zip(cases, outcomes):
            if case['fn'] in ('demo', 'stampDemo') and 'ok' in got:
                for i, layer in enumerate(got['ok']['layers']):
                    layer['id'] = f'L{i}'
            if 'error' in case:
                ok = got.get('error') == case['error']
            else:
                ok = 'ok' in got and (got['ok'] == case['ok'] if isinstance(case['ok'], str) else studio_canon(got['ok']) == studio_canon(case['ok']))
            if not ok:
                bad.append((case['fn'], json.dumps(case['arg'], ensure_ascii=False)[:120], str(got)[:120]))
        self.assertEqual(bad[:5], [])
        self.assertGreaterEqual(len(cases), 500)

    def test_random_scenes_draw_the_same_svg_in_python_and_the_page(self):
        import web_ui as w
        page = self.page()
        r = random.Random('studio-svg')
        jobs, expect = [], []
        for _ in range(250):
            scene = studio_random_scene(r)
            scale = r.choice([1, 1, 2, 0.5, 4, 0.25])
            jobs.append(['svg', [scene, scale]])
            try:
                expect.append({'ok': w.studio_svg(scene, None, scale)})
            except w.StudioError as error:
                expect.append({'error': str(error)})
        for want, got, job in zip(expect, self.call(page, jobs), jobs):
            if 'error' in want:
                self.assertEqual(got.get('error'), want['error'])
            else:
                self.assertTrue('ok' in got and self.same(got['ok'], want['ok']), (job[1][0], got))
        self.assertGreater(sum('ok' in e for e in expect), 200, 'most random scenes are valid')

    def test_damaged_scenes_are_refused_with_the_same_text(self):
        import web_ui as w
        page = self.page()
        r = random.Random('studio-validate')
        jobs, expect = [], []
        for _ in range(400):
            scene = studio_damage(r, studio_random_scene(r))
            jobs.append(['validate', scene])
            try:
                expect.append({'ok': w.studio_validate(scene)})
            except w.StudioError as error:
                expect.append({'error': str(error)})
        for want, got, job in zip(expect, self.call(page, jobs), jobs):
            if 'error' in want:
                self.assertEqual(got.get('error'), want['error'], job[1])
            else:
                self.assertEqual(studio_canon(got.get('ok')), studio_canon(want['ok']), job[1])
        refused = sum('error' in e for e in expect)
        self.assertTrue(100 < refused < 390, refused)

    def test_wrapped_text_breaks_the_same_in_python_and_the_page_for_latin_and_hangul(self):
        import web_ui as w
        page = self.page()
        r = random.Random('studio-wrap')
        jobs, expect = [], []
        for _ in range(300):
            layer = w.studio_text_layer(r.choice(STUDIO_TEXTS), 't', 0, 0, wrap=True)
            layer.update(w=r.choice([40, 80, 120, 300, 700]), fontSize=r.choice([8, 16, 24, 48]), font=r.choice(['sans', 'mono']))
            jobs.append(['textLayout', layer])
            expect.append(w.studio_text_layout(layer))
        alphabet = list('abcAB 019.,;:\'_-\t"') + ['é', 'ñ', '́', '한', '국', '어', '😀', '👍', '‍', '️', '🇯', '🇵', '!', '(', '　', 'あ', 'ア', '漢']
        for _ in range(300):
            text = ''.join(r.choice(alphabet) for _ in range(r.randint(0, 14)))
            jobs.append(['words', text])
            expect.append(w.studio_words(text))
            jobs.append(['graphemes', text])
            expect.append(w.studio_graphemes(text))
        for _ in range(300):
            layer = w.studio_text_layer(r.choice(STUDIO_TEXTS + ['abcd efgh ij', 'abcdefghij', 'ab cd ef gh']), 't', 0, 0, wrap=True)
            per = r.choice([1, 5, 10])
            layer.update(w=per * r.choice([1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 20, 40]) + r.choice([0, 0, -1, 1]))
            jobs.append(['textLayoutM', [layer, per]])
            expect.append(w.studio_text_layout(layer, lambda text, per=per: len(text) * per))
        got = self.call(page, jobs)
        for job, want, out in zip(jobs, expect, got):
            self.assertEqual(out.get('ok'), want, job)

    def test_layers_demos_history_and_workspace_text_are_the_same(self):
        import web_ui as w
        page = self.page()
        r = random.Random('studio-factories')
        jobs, expect = [], []
        for _ in range(120):
            opts = dict(fill=r.choice(['#18a7a1', '#FFFFFF', 'none']), stroke=r.choice(['#183c42', '#000000']), outline=r.random() < 0.4, text=r.choice(STUDIO_TEXTS[:7] + ['🌱🌱🌱🌱🌱🌱🌱🌱', '']), font=r.choice(['sans', 'mono']),
                        arrow_style=r.choice(['beginner', 'triangle']), arrow_placement=r.choice(['tip', 'middle']), clock_time=f'{r.randint(0, 23)}:{r.randint(0, 59):02d}', mono=r.random() < 0.5, wrap=r.random() < 0.5)
            tool = r.choice(['rect', 'ellipse', 'triangle', 'text', 'stamp', 'arrow', 'clock'])
            x, y = r.choice([r.randint(-50, 900), round(r.uniform(-50, 900), 3)]), r.randint(0, 600)
            camel = {'arrowStyle': opts['arrow_style'], 'arrowPlacement': opts['arrow_placement'], 'clockTime': opts['clock_time'], **{k: v for k, v in opts.items() if k not in ('arrow_style', 'arrow_placement', 'clock_time')}}
            jobs.append(['place', [tool, f'id{_}', x, y, camel]])
            expect.append(w.studio_place(tool, f'id{_}', x, y, **opts))
        for tool in ('rect', 'ellipse', 'triangle', 'text', 'stamp', 'arrow', 'clock'):
            jobs.append(['place', [tool, 'd', 3, 4, {}]])
            expect.append(w.studio_place(tool, 'd', 3, 4))
            jobs.append(['place', [tool, 'p', 3, 4, {'fill': '#112233', 'text': 'x', 'outline': True}]])
            expect.append(w.studio_place(tool, 'p', 3, 4, fill='#112233', text='x', outline=True))
        jobs.append(['place', ['star', 'x', 0, 0, {}]])
        jobs += [['demo', None], ['stampDemo', None], ['blank', None], ['heatmapScene', [[1, None, 3]]], ['matrixLayer', [[[1, 2], [3, 4]], 'm', 640, 480]], ['matrixLayer', [{'data': [{'type': 'heatmap', 'z': [[0, 1]]}]}, 'm']],
                 ['imageLayer', ['data:image/png;base64,AAAA', 40, 30, 'i', 640]], ['imageLayer', ['data:image/png;base64,AAAA', 1, 3, 'i']], ['textLayer', ['hi\nthere', 't', 5, 6]]]
        expect += [None, w.studio_demo_scene(), w.studio_stamp_demo_scene(), w.studio_blank(), w.studio_heatmap_scene([[1, None, 3]]), w.studio_matrix_layer([[1, 2], [3, 4]], 'm', 640, 480),
                   w.studio_matrix_layer({'data': [{'type': 'heatmap', 'z': [[0, 1]]}]}, 'm'), w.studio_image_layer('data:image/png;base64,AAAA', 40, 30, 'i', 640), w.studio_image_layer('data:image/png;base64,AAAA', 1, 3, 'i'),
                   w.studio_text_layer('hi\nthere', 't', 5, 6)]
        for job, want, out in zip(jobs, expect, self.call(page, jobs)):
            if want is None:
                self.assertEqual(out, {'error': '道具が不正です'})
            else:
                self.assertEqual(out['ok'] if 'ok' in out else out, json.loads(w.js_json(want)), job[0])
                self.assertEqual(json.dumps(out['ok'], separators=(',', ':'), ensure_ascii=False), w.js_json(want), 'the key order is the same too')
        # histories and workspace files: the same text from the same edits
        h_jobs, h_expect = [], []
        for _ in range(40):
            base = studio_random_scene(r, wrap=False)
            steps = [studio_random_scene(r, wrap=False) for _ in range(r.randint(0, 4))]
            h_jobs.append(['workspace', [base, *steps]])
            history = w.StudioHistory(base)
            for step in steps:
                history.commit(step)
            h_expect.append(w.studio_workspace_text(history))
        for job, want, out in zip(h_jobs, h_expect, self.call(page, h_jobs)):
            self.assertTrue('ok' in out and self.same(out['ok'], want), out)

    def test_sin_and_cos_are_the_same_ports_in_python_and_the_page(self):
        import math
        import web_ui as w
        page = self.page()
        r = random.Random('studio-sincos')
        xs = [r.uniform(-8, 8) for _ in range(4000)] + [r.uniform(0, 0.8) for _ in range(300)] + [i * math.pi / 6 for i in range(-12, 13)] + [0, 1e-9, math.pi / 2, -math.pi / 2, math.pi, 2 * math.pi, 8, -8, 2.5, -2.5]
        got = page.evaluate('xs => xs.map(x => [webUiImageStudio.sin(x), webUiImageStudio.cos(x)])', xs)
        self.assertEqual([[w.studio_sin(x), w.studio_cos(x)] for x in xs], got)
        for x in (8.5, -9, 100, 1e6):
            self.assertEqual(page.evaluate('x => { try { webUiImageStudio.sin(x) } catch (e) { return e.message } }', x), '角度が大きすぎます')
            self.assertEqual(page.evaluate('x => { try { webUiImageStudio.cos(x) } catch (e) { return e.message } }', x), '角度が大きすぎます')
            with self.assertRaises(w.StudioError):
                w.studio_sin(x)

    def test_every_limit_is_exact_and_the_same_in_the_page(self):
        import web_ui as w
        page = self.page()
        blank = lambda **patch: {'schema': w.STUDIO_SCHEMA, 'width': 64, 'height': 64, 'background': 'none', 'layers': [], **patch}
        layer = lambda i=0, **patch: {**w.studio_base_layer('rect', f'r{i}'), 'fill': 'none', 'stroke': 'none', 'strokeWidth': 0, **patch}
        text = w.studio_text_layer('a', 't', 0, 0)
        image = lambda n, i=0, **patch: {**w.studio_image_layer('data:image/png;base64,' + 'A' * (n - 22), 1, 1, f'i{i}'), 'w': 1, 'h': 1, **patch}
        jobs = []
        for width, height in ((64, 64), (63, 64), (64, 63), (4096, 1024), (4096, 1025), (4097, 64), (2048, 2048), (2049, 2048), (64.5, 64), (64, '64')):
            jobs.append(['validate', blank(width=width, height=height)])
        for count in (0, 1, 99, 100, 101):
            jobs.append(['validate', blank(layers=[layer(i) for i in range(count)])])
        for size in (99, 100, 101):
            jobs.append(['validate', blank(layers=[layer(0, id='x' * size)])])
        for size in (49, 50, 51):
            jobs.append(['validate', blank(layers=[layer(0, id='😀' * size)])])
        for field, low, high in (('x', -8192, 8192), ('y', -8192, 8192), ('w', 1, 8192), ('h', 1, 8192), ('rotation', -360, 360), ('opacity', 0, 1), ('strokeWidth', 0, 64)):
            for value in (low, high, low - 1, high + 1, low - 0.001, high + 0.001):
                jobs.append(['validate', blank(layers=[layer(0, **{field: value})])])
        for size in (1999, 2000, 2001):
            jobs.append(['validate', blank(layers=[{**text, 'text': 'a' * size}])])
        for size in (999, 1000, 1001):
            jobs.append(['validate', blank(layers=[{**text, 'text': '😀' * size}])])
        for size in (4, 512, 3.9, 512.1, 3, 513):
            jobs.append(['validate', blank(layers=[{**text, 'fontSize': size}])])
        for patch in ({'mono': 1}, {'mono': 'x'}, {'wrap': 1}, {'bold': None}, {'font': 'serif'}, {'font': 'mono'}, {'mono': True, 'fill': 'red'}):
            jobs.append(['validate', blank(layers=[{**text, **patch}])])
        for n in (12000000, 12000001):
            jobs.append(['validate', blank(layers=[image(n)])])
        for a, b in ((10000000, 10000000), (10000000, 10000001), (100, 100), (12000000, 8000000), (12000000, 8000001)):
            jobs.append(['validate', blank(layers=[image(a, 0), image(b, 1)])])
        for field, low, high in (('cell', 1, 512), ('levels', 2, 256)):
            for value in (low, high, low - 1, high + 1, low + 0.5, '3', None):
                jobs.append(['validate', blank(layers=[image(100, 0, **{field: value})])])
        for sampling in ('pixelated', 'smooth', 'none', 5):
            jobs.append(['validate', blank(layers=[image(100, 0, sampling=sampling)])])
        for value in (2 ** 53 - 1, -(2 ** 53 - 1), 2 ** 53, 2.0 ** 60, 2 ** 54, 1e300):
            jobs.append(['matrix', [[value]]])
        jobs += [['matrix', {'z': [[1]], 'zmin': 2 ** 53}], ['matrix', {'z': [[1]], 'zmax': 2 ** 53 - 1}], ['matrix', [[None, None]]], ['matrix', [[1, 2], [3]]], ['matrix', {'z': [[1, 2]], 'x': ['a']}], ['matrix', {'z': [[1, 2]], 'y': ['a', 'b']}]]
        for args in (([0] * 4, 1, 1, 0), ([0] * 4, 1, 1, 513), ([0] * 4, 1, 1, 1, 1), ([0] * 4, 1, 1, 1, 257), ([0] * 4, 0, 1, 1), ([0] * 4, 1, 0, 1), ([0] * 3, 1, 1, 1), ([0] * 4, 1.5, 1, 1), ([0] * 4, 1, 1, 512, 2), ([0] * 4, 1, 1, 1, 256)):
            jobs.append(['mosaic', list(args)])
        for a in ((1, 1, 28, 'tip'), (0, 1, 28, 'tip'), (8192, 1, 28, 'middle'), (8193, 1, 28, 'tip'), (10, 10, 0, 'tip'), (10, 10, 512, 'tip'), (10, 10, 513, 'tip'), (10, 10, 28, 'end'), (3, 4, 28, 'middle')):
            jobs.append(['arrow', list(a)])
        for scale in (0.25, 8, 0.24, 8.1, 1, 0, -1):
            jobs.append(['outputSize', [blank(width=640, height=480), scale]])
        for width, height, scale in ((1000, 1000, 8), (1024, 1024, 8), (1025, 1025, 8), (4096, 4096, 2), (4096, 2048, 2), (2048, 2048, 4), (2049, 2048, 4)):
            jobs.append(['outputSize', [{'width': width, 'height': height}, scale]])
        expect = []
        for kind, arg in jobs:
            try:
                expect.append({'ok': {'validate': w.studio_validate, 'matrix': w.studio_matrix, 'mosaic': lambda a: list(w.studio_mosaic_rgba(bytes(a[0]), *a[1:])), 'arrow': lambda a: w.studio_arrow_geometry(*a),
                                      'outputSize': lambda a: w.studio_output_size(*a)}[kind](arg)})
            except w.StudioError as error:
                expect.append({'error': str(error)})
        def wire(value):
            if isinstance(value, str) and value.startswith('data:image/png;base64,A') and len(value) > 10000:
                return {'__repeat': ['data:image/png;base64,', 'A', len(value) - 22]}
            if isinstance(value, list):
                return [wire(v) for v in value]
            if isinstance(value, dict):
                return {k: wire(v) for k, v in value.items()}
            return value
        got = self.call(page, [wire(job) for job in jobs])
        for job, want, out in zip(jobs, expect, got):
            self.assertEqual('error' in want, 'error' in out, (job[0], str(job[1])[:200], want if 'error' in want else '', out))
            if 'error' in want:
                self.assertEqual(out['error'], want['error'], (job[0], str(job[1])[:200]))
            else:
                self.assertEqual(studio_canon(out['ok']), studio_canon(want['ok']), (job[0], str(job[1])[:200]))
        self.assertGreater(sum('error' in e for e in expect), 40)
        self.assertGreater(sum('ok' in e for e in expect), 40)
        # the sizes of the hand-off, the history and the workspace file, built in the page
        heavy = page.evaluate("""() => { const S = webUiImageStudio, limit = 32 * 1024 * 1024, out = {}, sig = [137, 80, 78, 71, 13, 10, 26, 10], tried = f => { try { return {ok: f()} } catch (e) { return {error: e.message} } };
            const png = n => { const a = new Uint8Array(n); a.set(sig); return a };
            out.payload = [limit, limit + 1, 8, 7].map(n => { const r = tried(() => S.pngPayload(n === 7 ? png(8).subarray(0, 7) : png(n))); return r.ok ? r.ok.bytes : r.error });
            const blank = {schema: S.SCHEMA, width: 64, height: 64, background: 'none', layers: []};
            const history = n => { const h = new S.History(blank); h.items = Array(n).fill(blank); return h };
            out.states = [1, 40, 41].map(n => { const r = tried(() => S.workspaceText(history(n))); return r.ok ? JSON.parse(r.ok).items.length : r.error });
            const record = n => JSON.stringify({schema: S.WORKSPACE_SCHEMA, items: Array(n).fill(blank), index: 0});
            out.read = [0, 1, 40, 41].map(n => { const r = tried(() => S.workspaceHistory(record(n))); return r.ok ? r.ok.items.length : r.error });
            const base = S.workspaceText(history(1)), pad = n => base + ' '.repeat(n - new TextEncoder().encode(base).length);
            out.bytes = [limit, limit + 1].map(n => { const r = tried(() => S.workspaceHistory(pad(n))); return r.ok ? 'ok' : r.error });
            const big = JSON.parse(base); big.items[0].source = '🌱'.repeat(8388608); const multibyte = JSON.stringify(big);
            out.utf8 = [multibyte.length < limit, new TextEncoder().encode(multibyte).length > limit, tried(() => S.workspaceHistory(multibyte)).error];
            const scene = {...blank, layers: [S.imageLayer('data:image/png;base64,' + 'A'.repeat(8000000 - 22), 1, 1, 'img', 64)]}; scene.layers[0].w = 1; scene.layers[0].h = 1;
            const h5 = new S.History(scene); h5.items = Array(5).fill(scene); h5.index = 2;
            out.repeated = [tried(() => S.workspaceText(h5)).error, h5.items.length, tried(() => S.workspaceText(new S.History(h5.current))).ok !== undefined];
            out.metrics = [S.useCanvasMetrics(true), S.useCanvasMetrics(false)];
            const emptyLength = new TextEncoder().encode(S.workspaceText(new S.History({...blank, source: ''}))).length;
            out.writer = [limit - emptyLength, limit - emptyLength + 1].map(n => { const r = tried(() => S.workspaceText(new S.History({...blank, source: 'x'.repeat(n)}))); return r.ok ? new TextEncoder().encode(r.ok).length : r.error });
            return out }""")
        self.assertEqual(heavy['states'], [1, 40, '作業履歴の形式が不正です'])
        self.assertEqual(heavy['read'], ['作業履歴の形式が不正です', 1, 40, '作業履歴の形式が不正です'])
        self.assertEqual(heavy['bytes'], ['ok', '作業履歴は32MiB以下にしてください。履歴を整理して再保存できます'])
        self.assertEqual(heavy['utf8'], [True, True, '作業履歴は32MiB以下にしてください。履歴を整理して再保存できます'])
        self.assertEqual(heavy['repeated'], ['作業履歴は32MiB以下にしてください。履歴を整理して再保存できます', 5, True])
        self.assertEqual(heavy['metrics'], [True, False])
        self.assertEqual(heavy['writer'], [32 * 1024 * 1024, '作業履歴は32MiB以下にしてください。履歴を整理して再保存できます'])
        self.assertEqual(heavy['payload'], [32 * 1024 * 1024, '32MiB以下のPNGが必要です', 8, '32MiB以下のPNGが必要です'])

    def test_random_histories_step_the_same_in_python_and_the_page(self):
        import web_ui as w
        page = self.page()
        r = random.Random('studio-history')
        jobs, expect = [], []
        for _ in range(120):
            scenes = [studio_random_scene(r, wrap=False) for _ in range(4)]
            ops = [['commit', r.choice(scenes)] if r.random() < 0.45 else [r.choice(['undo', 'redo', 'undo', 'redo', 'commit']), None] for _ in range(r.randint(1, 60))]
            ops = [[op, scene if op == 'commit' and scene is not None else r.choice(scenes)] if op == 'commit' else [op, None] for op, scene in ops]
            jobs.append(['historyRun', [scenes[0], *ops]])
            history, seen = w.StudioHistory(scenes[0]), []
            for op, scene in ops:
                if op == 'commit':
                    history.commit(scene)
                elif op == 'undo':
                    history.undo()
                else:
                    history.redo()
                seen.append([history.index, len(history.items), w.js_json(history.current)])
            expect.append(seen)
        # past the forty-state limit
        scenes = [dict(w.studio_blank(), width=64 + i) for i in range(70)]
        jobs.append(['historyRun', [scenes[0], *[['commit', s] for s in scenes[1:]], ['undo', None], ['commit', scenes[5]], ['redo', None]]])
        history, seen = w.StudioHistory(scenes[0]), []
        for op, scene in [*[('commit', s) for s in scenes[1:]], ('undo', None), ('commit', scenes[5]), ('redo', None)]:
            history.commit(scene) if op == 'commit' else history.undo() if op == 'undo' else history.redo()
            seen.append([history.index, len(history.items), w.js_json(history.current)])
        expect.append(seen)
        for job, want, out in zip(jobs, expect, self.call(page, jobs)):
            self.assertEqual(out.get('ok'), want)
        self.assertEqual([entry[:2] for entry in expect[-1][-4:]], [[39, 40], [38, 40], [39, 40], [39, 40]])

    def test_mosaic_and_png_payload_agree_on_random_input(self):
        import web_ui as w
        page = self.page()
        r = random.Random('studio-mosaic')
        jobs, expect = [], []
        for _ in range(150):
            width, height = r.randint(1, 12), r.randint(1, 12)
            data = [r.randrange(256) if r.random() < 0.7 else r.choice([0, 255]) for _ in range(width * height * 4)]
            for k in range(3, len(data), 4):
                if r.random() < 0.4:
                    data[k] = r.choice([0, 255, 128])
            cell, levels = r.choice([1, 2, 3, 4, 7, 512]), r.choice([256, 2, 3, 16, 255])
            jobs.append(['mosaic', [data, width, height, cell, levels]])
            expect.append(list(w.studio_mosaic_rgba(bytes(data), width, height, cell, levels)))
        for _ in range(20):
            payload = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + bytes(r.randrange(256) for _ in range(r.choice([0, 1, 50, 20000])))
            jobs.append(['pngPayload', list(payload)])
            expect.append(w.studio_png_payload(payload))
        for job, want, out in zip(jobs, expect, self.call(page, jobs)):
            self.assertEqual(out.get('ok'), want, job[0])
        self.assertEqual(self.call(page, [['pngPayload', [1, 2, 3]]])[0], {'error': '32MiB以下のPNGが必要です'})

    # --- the editor ----------------------------------------------------------------------------------------------------------------------------
    def test_the_page_starts_with_the_example_and_exports_the_python_svg(self):
        import web_ui as w
        page = self.page()
        self.assertEqual((self.data(page, 'layers'), self.data(page, 'tool'), self.data(page, 'metrics'), self.status(page)), ('8', 'select', 'canvas', 'Ready.'))
        self.assertEqual((page.input_value('[data-is="cell"]'), page.inner_text('[data-is="cellout"]'), page.input_value('[data-is="levels"]'), page.inner_text('[data-is="levelsout"]')), ('1', '1 px', '256', '256'), 'with nothing selected the sliders rest at their defaults')
        self.assertEqual(self.scene(page), json.loads(w.js_json(w.studio_demo_scene())))
        self.assertEqual(page.inner_text('[data-is="size"]'), '1280 × 720')
        for scale in (1, 2, 4):
            page.select_option('[data-is="scale"]', str(scale))
            download, data = self.download(page, '[data-is="svg"]')
            self.assertEqual(download.suggested_filename, 'ironmate-image.svg')
            self.assertEqual(data.decode('utf-8'), w.studio_svg(w.studio_demo_scene(), None, scale))
        self.assertEqual(self.status(page), 'Saved the SVG')
        page.select_option('[data-is="scale"]', '8')
        page.click('[data-is="svg"]')
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "出力は各辺8192px・合計16MP以下にしてください"')
        self.assertEqual(self.data(page, 'error'), '1', '1280 x 8 is wider than 8192 pixels')

    def test_each_tool_places_its_layer_where_the_canvas_was_pressed(self):
        import web_ui as w
        page = self.page()
        self.blank(page)
        page.fill('[data-is="fill"]', '#112233')
        page.fill('[data-is="stroke"]', '#445566')
        page.fill('[data-is="text"]', 'Hi there')
        page.fill('[data-is="clock"]', '03:45')
        cases = [('rect', 100, 80), ('ellipse', 300, 80), ('triangle', 500, 80), ('text', 100, 300), ('arrow', 400, 300), ('clock', 800, 300)]
        for tool, x, y in cases:
            self.tool(page, tool)
            self.press(page, x, y)
        scene = self.scene(page)
        self.assertEqual([l['kind'] for l in scene['layers']], ['rect', 'ellipse', 'triangle', 'text', 'arrow', 'clock'])
        for layer, (tool, x, y) in zip(scene['layers'], cases):
            self.assertAlmostEqual(layer['x'], x, delta=1.5)
            self.assertAlmostEqual(layer['y'], y, delta=1.5)
            expect = w.studio_place(tool, layer['id'], layer['x'], layer['y'], fill='#112233', stroke='#445566', text='Hi there', clock_time='03:45')
            self.assertEqual(layer, json.loads(w.js_json(expect)), tool)
        self.assertEqual(self.data(page, 'layers'), '6')
        self.assertEqual(self.data(page, 'selected'), scene['layers'][-1]['id'])
        self.assertEqual((scene['layers'][-1]['hour'], scene['layers'][-1]['minute']), (3, 45))
        self.tool(page, 'rect')
        page.check('[data-is="outline"]')
        self.press(page, 600, 500)
        self.assertEqual(self.scene(page)['layers'][-1]['fill'], 'none')

    def test_a_stamp_is_pressed_again_and_again_and_a_layer_can_become_the_stamp(self):
        page = self.page()
        self.blank(page)
        page.click('[data-stamp="🌱"]')
        self.assertEqual(self.data(page, 'tool'), 'stamp')
        self.assertIn('🌱', page.inner_text('[data-is="stampnote"]'))
        self.press(page, 200, 200)
        self.press(page, 400, 200)
        scene = self.scene(page)
        self.assertEqual([l['text'] for l in scene['layers']], ['🌱', '🌱'])
        self.assertTrue(all(l['mono'] for l in scene['layers']))
        page.click('[data-stamp="🔰"]')
        self.assertEqual(page.input_value('[data-is="fill"]'), '#000000', 'the learner mark is black')
        self.tool(page, 'rect')
        self.press(page, 600, 400)
        rect = self.scene(page)['layers'][-1]
        page.click('[data-is="custom"]')
        self.assertEqual(self.data(page, 'tool'), 'stamp')
        self.press(page, 900, 500)
        copy = self.scene(page)['layers'][-1]
        self.assertEqual((copy['kind'], copy['w'], copy['h'], copy['name']), ('rect', rect['w'], rect['h'], rect['name']))
        self.assertNotEqual(copy['id'], rect['id'])
        self.assertAlmostEqual(copy['x'] + copy['w'] / 2, 900, delta=1.5)

    def test_select_move_resize_and_undo(self):
        page = self.page()
        self.blank(page)
        self.tool(page, 'rect')
        self.press(page, 200, 200)
        rect = self.scene(page)['layers'][0]
        self.tool(page, 'select')
        self.paint(page, lambda: page.mouse.click(*self.at(page, 300, 260)))
        self.assertEqual(self.data(page, 'selected'), rect['id'])
        sx, sy = self.at(page, 300, 260)
        ex, ey = self.at(page, 420, 340)
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move((sx + ex) / 2, (sy + ey) / 2)
        page.mouse.move(ex, ey)
        page.mouse.up()
        page.wait_for_function('() => webUiImageStudio.app.history.index === 3')
        moved = self.scene(page)['layers'][0]
        self.assertAlmostEqual(moved['x'] - rect['x'], 120, delta=2)
        self.assertAlmostEqual(moved['y'] - rect['y'], 80, delta=2)
        self.assertEqual((moved['w'], moved['h']), (rect['w'], rect['h']))
        # the blue corner at the bottom right resizes
        hx, hy = self.at(page, moved['x'] + moved['w'], moved['y'] + moved['h'])
        page.mouse.move(hx, hy)
        page.mouse.down()
        page.mouse.move(hx + 40, hy + 24)
        page.mouse.move(hx + 80, hy + 48)
        page.mouse.up()
        page.wait_for_function('() => webUiImageStudio.app.history.index === 4')
        bigger = self.scene(page)['layers'][0]
        scale = self.at(page, 1, 0)[0] - self.at(page, 0, 0)[0]
        self.assertAlmostEqual(bigger['w'] - moved['w'], 80 / scale, delta=2)
        self.assertAlmostEqual(bigger['h'] - moved['h'], 48 / scale, delta=2)
        self.assertEqual((bigger['x'], bigger['y']), (moved['x'], moved['y']), 'an unrotated layer grows from its top left corner')
        self.paint(page, lambda: page.click('[data-is="undo"]'))
        self.assertEqual(self.scene(page)['layers'][0]['w'], moved['w'])
        self.paint(page, lambda: page.click('[data-is="redo"]'))
        self.assertEqual(self.scene(page)['layers'][0]['w'], bigger['w'])
        # pressing empty canvas deselects
        self.paint(page, lambda: page.mouse.click(*self.at(page, 1200, 40)))
        self.assertEqual(self.data(page, 'selected'), '')

    def test_resizing_a_rotated_layer_keeps_its_top_left_corner_and_a_text_layer_scales_its_font(self):
        import math
        page = self.page()
        self.blank(page)
        self.tool(page, 'rect')
        self.press(page, 300, 200)
        self.tool(page, 'select')
        for angle in (45, 90, -30):
            self.paint(page, lambda: page.fill('[data-is="rotation"]', str(angle)) or page.dispatch_event('[data-is="rotation"]', 'change'))
            layer = self.scene(page)['layers'][0]
            corner = lambda l: (l['x'] + l['w'] / 2 + math.cos(math.radians(l['rotation'])) * (-l['w'] / 2) - math.sin(math.radians(l['rotation'])) * (-l['h'] / 2),
                                l['y'] + l['h'] / 2 + math.sin(math.radians(l['rotation'])) * (-l['w'] / 2) + math.cos(math.radians(l['rotation'])) * (-l['h'] / 2))
            handle = (layer['w'], layer['h'])
            hx = layer['x'] + layer['w'] / 2 + math.cos(math.radians(angle)) * (handle[0] / 2) - math.sin(math.radians(angle)) * (handle[1] / 2)
            hy = layer['y'] + layer['h'] / 2 + math.sin(math.radians(angle)) * (handle[0] / 2) + math.cos(math.radians(angle)) * (handle[1] / 2)
            self.drag_handle(page, (hx, hy), (hx + 60, hy + 36))
            page.wait_for_function('l => webUiImageStudio.app.scene.layers[0].w !== l', arg=layer['w'])
            after = self.scene(page)['layers'][0]
            self.assertNotEqual((after['w'], after['h']), (layer['w'], layer['h']), angle)
            before_corner, after_corner = corner(layer), corner(after)
            self.assertAlmostEqual(before_corner[0], after_corner[0], delta=0.5, msg=angle)
            self.assertAlmostEqual(before_corner[1], after_corner[1], delta=0.5, msg=angle)
        self.blank(page)
        self.tool(page, 'text')
        page.fill('[data-is="text"]', 'Resize me')
        self.press(page, 200, 200)
        self.tool(page, 'select')
        text = self.scene(page)['layers'][0]
        self.drag_handle(page, (text['x'] + text['w'], text['y'] + text['h']), (text['x'] + text['w'] - 120, text['y'] + text['h'] - 60))
        page.wait_for_function('s => webUiImageStudio.app.scene.layers[0].fontSize !== s', arg=text['fontSize'])
        grown = self.scene(page)['layers'][0]
        ratio = min(grown['w'] / text['w'], grown['h'] / text['h'])
        self.assertAlmostEqual(grown['fontSize'], max(4, min(512, text['fontSize'] * ratio)), places=6)
        self.assertLess(grown['fontSize'], text['fontSize'])
        self.assertGreaterEqual(grown['fontSize'], 4)

    def test_a_cancelled_drag_puts_the_layer_back_and_the_list_shows_a_text_layer_in_the_box(self):
        page = self.page()
        self.blank(page)
        self.tool(page, 'rect')
        self.press(page, 200, 200)
        self.tool(page, 'select')
        start = self.scene(page)['layers'][0]
        before = page.evaluate('() => webUiImageStudio.app.history.items.length')
        sx, sy = self.at(page, 260, 250)
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + 40, sy + 30)
        page.mouse.move(sx + 80, sy + 60)
        page.wait_for_function('x => webUiImageStudio.app.scene.layers[0].x !== x', arg=start['x'])
        page.evaluate('() => document.querySelector("[data-is=board]").dispatchEvent(new PointerEvent("pointercancel", {bubbles: true}))')
        page.wait_for_function('x => webUiImageStudio.app.scene.layers[0].x === x', arg=start['x'])
        page.mouse.up()
        self.assertEqual((self.scene(page)['layers'][0]['x'], self.scene(page)['layers'][0]['y']), (start['x'], start['y']))
        self.assertEqual(page.evaluate('() => webUiImageStudio.app.history.items.length'), before, 'nothing was recorded')
        self.tool(page, 'text')
        page.fill('[data-is="text"]', 'First words')
        self.press(page, 500, 400)
        page.fill('[data-is="text"]', 'something else')
        ids = [l['id'] for l in self.scene(page)['layers']]
        self.paint(page, lambda: page.click(f'[data-is="layers"] button[data-layer-id="{ids[0]}"]'))
        self.assertEqual(page.input_value('[data-is="text"]'), 'something else', 'a layer without text leaves the box alone')
        self.paint(page, lambda: page.click(f'[data-is="layers"] button[data-layer-id="{ids[1]}"]'))
        self.assertEqual(page.input_value('[data-is="text"]'), 'First words', 'a text layer puts its text in the box')

    def test_keyboard_nudges_deletes_and_undoes(self):
        page = self.page()
        self.blank(page)
        self.tool(page, 'ellipse')
        self.press(page, 300, 300)
        start = self.scene(page)['layers'][0]
        page.focus('[data-is="board"]')
        self.tool(page, 'select')
        page.focus('[data-is="board"]')
        self.paint(page, lambda: page.keyboard.press('ArrowRight'))
        self.paint(page, lambda: page.keyboard.press('Shift+ArrowDown'))
        moved = self.scene(page)['layers'][0]
        self.assertEqual((moved['x'] - start['x'], moved['y'] - start['y']), (8, 1))
        self.paint(page, lambda: page.keyboard.press('Control+z'))
        self.assertEqual(self.scene(page)['layers'][0]['y'], start['y'])
        self.paint(page, lambda: page.keyboard.press('Control+Shift+z'))
        self.assertEqual(self.scene(page)['layers'][0]['y'], start['y'] + 1)
        self.assertEqual(self.data(page, 'selected'), '', 'undo and redo leave nothing selected')
        self.paint(page, lambda: page.click('[data-is="layers"] button'))
        page.focus('[data-is="board"]')
        self.paint(page, lambda: page.keyboard.press('Delete'))
        self.assertEqual(self.data(page, 'layers'), '0')
        self.paint(page, lambda: page.click('[data-is="undo"]'))
        self.assertEqual(self.data(page, 'layers'), '1')

    def test_layer_list_order_duplicate_delete_and_the_hundred_layer_limit(self):
        page = self.page()
        self.blank(page)
        for i, tool in enumerate(['rect', 'ellipse', 'triangle']):
            self.tool(page, tool)
            self.press(page, 100 + 100 * i, 100)
        names = lambda: [b.get_attribute('data-layer-id') for b in page.query_selector_all('[data-is="layers"] button')]
        ids = [l['id'] for l in self.scene(page)['layers']]
        self.assertEqual(names(), ids[::-1], 'the top layer is listed first')
        self.paint(page, lambda: page.click(f'[data-is="layers"] button[data-layer-id="{ids[0]}"]'))
        self.assertEqual(self.data(page, 'selected'), ids[0])
        self.assertEqual([b.get_attribute('aria-pressed') for b in page.query_selector_all('[data-is="layers"] button')], ['false', 'false', 'true'], 'the selected layer is the pressed button')
        self.paint(page, lambda: page.click('[data-is="front"]'))
        self.assertEqual([l['id'] for l in self.scene(page)['layers']], [ids[1], ids[0], ids[2]])
        self.paint(page, lambda: page.click('[data-is="back"]'))
        self.paint(page, lambda: page.click('[data-is="back"]'))
        self.assertEqual([l['id'] for l in self.scene(page)['layers']], [ids[0], ids[1], ids[2]])
        self.paint(page, lambda: page.click('[data-is="duplicate"]'))
        scene = self.scene(page)
        copy, original = scene['layers'][-1], scene['layers'][0]
        self.assertEqual((copy['x'] - original['x'], copy['y'] - original['y'], copy['kind']), (24, 24, original['kind']))
        self.assertEqual(len({l['id'] for l in scene['layers']}), 4)
        self.paint(page, lambda: page.click('[data-is="delete"]'))
        self.assertEqual(self.data(page, 'layers'), '3')
        page.evaluate('''async () => { const s = webUiImageStudio.blank(); for (let i = 0; i < 100; i++) s.layers.push(webUiImageStudio.place('rect', 'r' + i, i, i)); await webUiImageStudio.app.replaceScene(s) }''')
        self.assertEqual(self.data(page, 'layers'), '100')
        self.tool(page, 'rect')
        sx, sy = self.at(page, 10, 10)
        page.mouse.click(sx, sy)
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "レイヤーは100件までです"')
        self.assertEqual((self.data(page, 'layers'), self.data(page, 'error')), ('100', '1'))

    def test_the_inspector_edits_the_selected_layer_and_refuses_what_the_scene_refuses(self):
        page = self.page()
        self.blank(page)
        self.assertTrue(page.is_disabled('[data-is="x"]'))
        self.tool(page, 'text')
        page.fill('[data-is="text"]', 'Edit me')
        self.press(page, 100, 100)
        self.assertFalse(page.is_disabled('[data-is="x"]'))
        self.assertFalse(page.is_disabled('[data-is="fontsize"]'))
        for field, value in (('x', '120'), ('y', '-30'), ('rotation', '45'), ('opacity', '0.5'), ('fontsize', '24')):
            self.paint(page, lambda: page.fill(f'[data-is="{field}"]', value) or page.dispatch_event(f'[data-is="{field}"]', 'change'))
        layer = self.scene(page)['layers'][0]
        self.assertEqual((layer['x'], layer['y'], layer['rotation'], layer['opacity'], layer['fontSize']), (120, -30, 45, 0.5, 24))
        self.paint(page, lambda: page.select_option('[data-is="fontfamily"]', 'mono'))
        self.paint(page, lambda: page.uncheck('[data-is="mono"]'))
        self.assertEqual((self.scene(page)['layers'][0]['font'], self.scene(page)['layers'][0]['mono']), ('mono', False))
        page.fill('[data-is="text"]', 'Changed')
        page.fill('[data-is="fill"]', '#ff0000')
        self.paint(page, lambda: page.click('[data-is="apply"]'))
        self.assertEqual((self.scene(page)['layers'][0]['text'], self.scene(page)['layers'][0]['fill']), ('Changed', '#ff0000'))
        before = self.scene(page)
        page.fill('[data-is="w"]', '0')
        page.dispatch_event('[data-is="w"]', 'change')
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "サイズが不正です"')
        self.assertEqual((self.scene(page), self.data(page, 'error')), (before, '1'))
        page.fill('[data-is="rotation"]', '999')
        page.dispatch_event('[data-is="rotation"]', 'change')
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "角度または不透明度が不正です"')
        self.assertEqual(self.scene(page), before)

    def test_arrow_clock_and_heatmap_settings(self):
        page = self.page()
        self.blank(page)
        self.tool(page, 'arrow')
        self.press(page, 100, 100)
        self.assertEqual(page.input_value('[data-is="arrowstyle"]'), 'beginner')
        self.paint(page, lambda: page.select_option('[data-is="arrowstyle"]', 'triangle'))
        self.paint(page, lambda: page.select_option('[data-is="arrowplacement"]', 'middle'))
        arrow = self.scene(page)['layers'][0]
        self.assertEqual((arrow['headStyle'], arrow['headPlacement']), ('triangle', 'middle'))
        self.tool(page, 'clock')
        self.press(page, 500, 100)
        self.paint(page, lambda: page.fill('[data-is="clock"]', '07:20') or page.dispatch_event('[data-is="clock"]', 'change'))
        clock = self.scene(page)['layers'][-1]
        self.assertEqual((clock['hour'], clock['minute'], clock['kind']), (7, 20, 'clock'))
        self.paint(page, lambda: page.click('[data-is="heatmap"]'))
        heat = self.scene(page)['layers'][-1]
        self.assertEqual((heat['kind'], heat['z'], heat['levels'], heat['labels']), ('heatmap', [[0, 1, 2, 3], [3, 2, 1, 0], [1, None, 2, 3]], 0, True))
        self.assertEqual(page.inner_text('[data-is="levelsout"]'), 'continuous')
        self.assertEqual(page.input_value('[data-is="levels"]'), '256', 'a continuous heatmap shows the slider at its far end')
        page.evaluate('() => { const l = document.querySelector("[data-is=levels]"); l.value = 4; l.dispatchEvent(new Event("change")) }')
        page.wait_for_function('() => webUiImageStudio.app.scene.layers.at(-1).levels === 4')
        self.paint(page, lambda: page.uncheck('[data-is="labels"]'))
        self.assertFalse(self.scene(page)['layers'][-1]['labels'])
        self.paint(page, lambda: page.click('[data-is="continuous"]'))
        self.assertEqual(self.scene(page)['layers'][-1]['levels'], 0)
        for text, message in (('[[1,2],[3]]', '1〜4096セルの長方形の数値行列が必要です'), ('{"data": []}', 'heatmapトレースは1つにしてください')):
            page.fill('[data-is="matrix"]', text)
            page.click('[data-is="heatmap"]')
            page.wait_for_function('m => document.querySelector("[data-is=status]").textContent === m', arg=message)
        page.fill('[data-is="matrix"]', '{nope')
        page.click('[data-is="heatmap"]')
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1" && document.querySelector("[data-is=status]").textContent.includes("JSON")')

    def test_canvas_size_background_and_the_undo_history(self):
        page = self.page()
        self.paint(page, lambda: (page.fill('[data-is="width"]', '640'), page.fill('[data-is="height"]', '480'), page.click('[data-is="resize"]')))
        scene = self.scene(page)
        self.assertEqual((scene['width'], scene['height']), (640, 480))
        self.assertEqual(page.inner_text('[data-is="size"]'), '640 × 480')
        self.paint(page, lambda: page.check('[data-is="transparent"]'))
        self.assertEqual(self.scene(page)['background'], 'none')
        self.paint(page, lambda: page.uncheck('[data-is="transparent"]'))
        self.assertEqual(self.scene(page)['background'], '#f8f7f2')
        page.fill('[data-is="width"]', '10')
        page.click('[data-is="resize"]')
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
        self.assertEqual(self.scene(page)['width'], 640)
        page.click('details:has([data-is="history"]) > summary')
        items = page.query_selector_all('[data-is="history"] li button')
        self.assertEqual(len(items), 4)
        self.assertTrue(items[-1].inner_text().startswith('● State 4'))
        self.paint(page, lambda: items[0].click())
        self.assertEqual(self.scene(page)['width'], 1280)
        self.assertEqual(page.get_attribute('[data-is="history"] li button', 'aria-current'), 'step')
        self.assertTrue(page.is_disabled('[data-is="undo"]'))
        self.assertFalse(page.is_disabled('[data-is="redo"]'))

    def test_a_photo_is_added_kept_exactly_and_mosaicked_from_the_original(self):
        import web_ui as w
        page = self.page()
        self.blank(page)
        rng = random.Random(5)
        rgba = bytes(v for _ in range(16 * 12) for v in (rng.randrange(256), rng.randrange(256), rng.randrange(256), 255))
        png = w.studio_png_encode(16, 12, rgba)
        self.paint(page, lambda: page.set_input_files('[data-is="file"]', files=[{'name': 'photo.png', 'mimeType': 'image/png', 'buffer': png}]))
        layer = self.scene(page)['layers'][0]
        self.assertEqual((layer['kind'], layer['cell'], layer['levels'], layer['sampling'], layer['mono'], layer['name']), ('image', 1, 256, 'pixelated', False, 'photo.png'))
        self.assertAlmostEqual(layer['w'] / layer['h'], 16 / 12, places=5)
        self.assertEqual(layer['w'], 1280 * 0.65 if 1280 * 0.65 < 700 else 700)
        decoded = self.pixels(base64.b64decode(layer['src'].split(',', 1)[1]))
        self.assertEqual(decoded.tobytes(), rgba, 'the page keeps every pixel')
        for cell, levels in ((4, 256), (3, 4), (128, 2)):
            page.evaluate('([cell, levels]) => { for (const [name, v] of [["cell", cell], ["levels", levels]]) { const e = document.querySelector(`[data-is=${name}]`); e.value = v; e.dispatchEvent(new Event("change")) } }', [cell, levels])
            page.wait_for_function('([cell, levels]) => { const l = webUiImageStudio.app.scene.layers[0]; return l.cell === cell && l.levels === levels }', arg=[cell, levels])
            source = page.evaluate('async () => { const s = webUiImageStudio.app.scene; return (await webUiImageStudio.app.imageSource(s))(s.layers[0]) }')
            got = self.pixels(base64.b64decode(source.split(',', 1)[1])).tobytes()
            self.assertEqual(got, bytes(w.studio_mosaic_rgba(rgba, 16, 12, cell, levels)), (cell, levels))
            self.assertEqual(w.studio_png_decode(base64.b64decode(source.split(',', 1)[1]))[2], got, 'the Python decoder reads what the browser wrote')
        self.assertEqual(self.scene(page)['layers'][0]['src'], layer['src'], 'the original is never rewritten')
        plain = page.evaluate('async src => { const s = webUiImageStudio.app.scene; s.layers[0].cell = 1; s.layers[0].levels = 256; return (await webUiImageStudio.app.imageSource(s))(s.layers[0]) }', layer['src'])
        self.assertEqual(plain, layer['src'], 'a layer that keeps every pixel passes its own image through')
        self.paint(page, lambda: page.select_option('[data-is="sampling"]', 'smooth'))
        self.assertEqual(self.scene(page)['layers'][0]['sampling'], 'smooth')
        page.set_input_files('[data-is="file"]', files=[{'name': 'x.png', 'mimeType': 'image/png', 'buffer': b'not an image at all'}])
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
        self.assertEqual(self.status(page), '画像形式またはMIME宣言が実データと一致しません')
        page.set_input_files('[data-is="file"]', files=[{'name': 'y.png', 'mimeType': 'image/jpeg', 'buffer': png}])
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "画像形式またはMIME宣言が実データと一致しません"')
        self.assertEqual(self.data(page, 'layers'), '1')

    def test_base64_text_is_added_as_an_image_and_a_bad_one_is_refused(self):
        import web_ui as w
        page = self.page()
        self.blank(page)
        png = w.studio_png_encode(4, 4, bytes([200, 30, 60, 255]) * 16)
        text = base64.b64encode(png).decode('ascii')
        for value in ('data:image/png;base64,' + text, text, ' \n'.join([text[:20], text[20:]])):
            self.paint(page, lambda: (page.fill('[data-is="b64in"]', value), page.click('[data-is="b64import"]')))
        layers = self.scene(page)['layers']
        self.assertEqual([l['name'] for l in layers], ['Base64画像'] * 3)
        for bad in ('', 'hello', 'data:image/gif;base64,' + text, 'data:image/png;base64,' + base64.b64encode(b'GIF89a....').decode(), text[:-2]):
            page.fill('[data-is="b64in"]', bad)
            page.click('[data-is="b64import"]')
            page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
            self.assertTrue(self.status(page).startswith('Not a PNG, JPEG or WebP image in Base64 ('), bad[:20])
            page.fill('[data-is="b64in"]', text)
            self.paint(page, lambda: page.click('[data-is="b64import"]'))
            self.assertEqual(self.data(page, 'error'), '')
            self.paint(page, lambda: page.click('[data-is="undo"]'))
        self.assertEqual(self.data(page, 'layers'), '3')

    def test_pasting_an_image_from_the_clipboard(self):
        import web_ui as w
        page = self.page()
        self.blank(page)
        png = w.studio_png_encode(2, 2, bytes([1, 2, 3, 255]) * 4)
        page.evaluate('''text => { Object.defineProperty(navigator, "clipboard", {configurable: true, value: {readText: async () => text}}) }''', 'data:image/png;base64,' + base64.b64encode(png).decode())
        self.paint(page, lambda: page.click('[data-is="paste"]'))
        self.assertEqual(self.scene(page)['layers'][0]['name'], 'クリップボード画像')
        page.evaluate('''() => { Object.defineProperty(navigator, "clipboard", {configurable: true, value: {readText: async () => "just words"}}) }''')
        page.click('[data-is="paste"]')
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
        self.assertEqual(self.status(page), 'The clipboard has no PNG, JPEG or WebP image, or image text.')
        self.assertEqual(self.data(page, 'layers'), '1')

    def test_png_and_base64_exports_hold_what_the_board_shows(self):
        import web_ui as w
        page = self.page()
        scene = w.studio_blank()
        scene.update(width=128, height=96, background='#FFFFFF')
        scene['layers'] = [{**w.studio_base_layer('rect', 'red', 0, 0, 64, 48), 'fill': '#FF0000', 'stroke': 'none', 'strokeWidth': 0}, {**w.studio_base_layer('rect', 'blue', 64, 48, 64, 48), 'fill': '#0000FF', 'stroke': 'none', 'strokeWidth': 0}]
        page.evaluate('async s => { await webUiImageStudio.app.replaceScene(s) }', scene)
        near = lambda a, b: all(abs(x - y) <= 2 for x, y in zip(a, b))
        for scale in (1, 2, 4):
            page.select_option('[data-is="scale"]', str(scale))
            download, data = self.download(page, '[data-is="png"]')
            self.assertEqual(download.suggested_filename, 'ironmate-image.png')
            image = self.pixels(data)
            self.assertEqual(image.size, (128 * scale, 96 * scale))
            self.assertTrue(near(image.getpixel((16 * scale, 12 * scale)), (255, 0, 0, 255)))
            self.assertTrue(near(image.getpixel((100 * scale, 80 * scale)), (0, 0, 255, 255)))
            self.assertTrue(near(image.getpixel((100 * scale, 10 * scale)), (255, 255, 255, 255)))
        page.select_option('[data-is="scale"]', '2')
        scene['background'] = 'none'
        page.evaluate('async s => { await webUiImageStudio.app.replaceScene(s) }', scene)
        scene['background'] = '#FFFFFF'
        page.evaluate('async s => { await webUiImageStudio.app.replaceScene(s) }', scene)
        edge = self.pixels(self.download(page, '[data-is="png"]')[1])
        for point, colour in (((0, 0), (255, 0, 0, 255)), ((127, 95), (255, 0, 0, 255)), ((128, 95), (255, 255, 255, 255)), ((127, 96), (255, 255, 255, 255)), ((128, 96), (0, 0, 255, 255)),
                              ((255, 191), (0, 0, 255, 255)), ((254, 190), (0, 0, 255, 255)), ((255, 0), (255, 255, 255, 255)), ((0, 191), (255, 255, 255, 255))):
            self.assertTrue(near(edge.getpixel(point), colour), (point, edge.getpixel(point), colour))
        scene['background'] = 'none'
        page.evaluate('async s => { await webUiImageStudio.app.replaceScene(s) }', scene)
        self.assertEqual(self.pixels(self.download(page, '[data-is="png"]')[1]).getpixel((200, 20)), (0, 0, 0, 0), 'a transparent background stays transparent')
        page.click('[data-is="base64"]')
        page.wait_for_function('() => document.querySelector("[data-is=b64panel]").open')
        text = page.input_value('[data-is="b64text"]')
        self.assertTrue(text.startswith('data:image/png;base64,'))
        png = base64.b64decode(text.split(',', 1)[1])
        self.assertEqual(self.pixels(png).size, (256, 192))
        self.assertEqual(w.studio_png_payload(png)['dataUri'], text)
        self.assertIn(f'{len(png):,}', page.inner_text('[data-is="b64status"]'))
        page.select_option('[data-is="b64mode"]', 'base64')
        self.assertEqual(page.input_value('[data-is="b64text"]'), text.split(',', 1)[1])
        _, saved = self.download(page, '[data-is="b64save"]')
        self.assertEqual(saved.decode(), text.split(',', 1)[1])

    def test_json_and_workspace_files_round_trip_and_bad_files_change_nothing(self):
        import web_ui as w
        page = self.page()
        self.blank(page)
        for tool, x in (('rect', 100), ('ellipse', 300), ('text', 500)):
            self.tool(page, tool)
            self.press(page, x, 100)
        scene = self.scene(page)
        download, data = self.download(page, '[data-is="jsonsave"]')
        self.assertEqual(download.suggested_filename, 'ironmate-scene.json')
        self.assertEqual(data.decode('utf-8'), w.js_json(w.studio_validate(scene), 2), 'the same text as the command line')
        self.assertEqual(page.evaluate('() => webUiImageStudio.app.dirty'), False)
        _, workspace = self.download(page, '[data-is="wssave"]')
        restored = w.studio_workspace_history(workspace.decode('utf-8'))
        self.assertEqual((restored.index, len(restored.items), restored.current), (4, 5, scene))
        self.assertEqual(workspace.decode('utf-8'), w.studio_workspace_text(restored))
        # open a different scene, then bring the saved history back
        other = w.studio_demo_scene()
        self.paint(page, lambda: page.set_input_files('[data-is="jsonopen"]', files=[{'name': 's.json', 'mimeType': 'application/json', 'buffer': w.js_json(other).encode()}]))
        self.assertEqual(self.data(page, 'layers'), '8')
        self.paint(page, lambda: page.click('[data-is="undo"]'))
        self.assertEqual(self.scene(page), scene, 'opening a file is an edit that can be undone')
        self.paint(page, lambda: page.click('[data-is="redo"]'))
        history = w.StudioHistory(other)
        history.commit(scene)
        self.paint(page, lambda: page.set_input_files('[data-is="wsopen"]', files=[{'name': 'w.json', 'mimeType': 'application/json', 'buffer': w.studio_workspace_text(history).encode()}]))
        self.assertEqual((self.scene(page), page.evaluate('() => [webUiImageStudio.app.history.index, webUiImageStudio.app.history.items.length]')), (scene, [1, 2]))
        before = self.scene(page)
        for field, content, message in (('jsonopen', b'{"schema": "x"}', 'シーンの形式・サイズが不正です（最大100レイヤー、4MP）'), ('jsonopen', b'{nope', None), ('wsopen', b'{"schema": "ironmate-studio-workspace/1", "items": [], "index": 0}', '作業履歴の形式が不正です'),
                                        ('wsopen', b'not json', None)):
            page.evaluate('() => { document.querySelector("#imagestudio").dataset.error = "" }')
            page.set_input_files(f'[data-is="{field}"]', files=[{'name': 'bad.json', 'mimeType': 'application/json', 'buffer': content}])
            page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
            if message:
                self.assertEqual(self.status(page), message)
            self.assertEqual(self.scene(page), before)
        page.evaluate('() => { document.querySelector("#imagestudio").dataset.error = "" }')
        page.click('details:has([data-is="history"]) > summary')
        self.paint(page, lambda: page.click('[data-is="trim"]'))
        self.assertEqual(page.evaluate('() => webUiImageStudio.app.history.items.length'), 1)
        self.assertTrue(page.evaluate('() => webUiImageStudio.app.dirty'), 'trimming is an edit of the history')
        self.assertEqual(self.scene(page), before)

    def test_unsaved_work_is_flagged_for_leaving_the_page(self):
        page = self.page()
        self.assertFalse(page.evaluate('() => webUiImageStudio.app.dirty'))
        flagged = page.evaluate('() => { const e = new Event("beforeunload", {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented }')
        self.assertFalse(flagged)
        self.paint(page, lambda: page.click('[data-is="blank"]'))
        self.assertTrue(page.evaluate('() => webUiImageStudio.app.dirty'))
        flagged = page.evaluate('() => { const e = new Event("beforeunload", {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented }')
        self.assertTrue(flagged)

    def test_every_edit_marks_the_work_unsaved_and_saving_clears_it(self):
        page = self.page()
        dirty = lambda: page.evaluate('() => webUiImageStudio.app.dirty')
        self.assertFalse(dirty())
        self.blank(page)
        self.tool(page, 'rect')
        self.press(page, 200, 200)
        self.assertTrue(dirty())
        for action in ('undo', 'redo'):
            page.click('[data-is="jsonsave"]')
            self.assertFalse(dirty())
            self.paint(page, lambda: page.click(f'[data-is="{action}"]'))
            self.assertTrue(dirty(), action)
        page.click('[data-is="jsonsave"]')
        self.tool(page, 'select')
        self.paint(page, lambda: page.mouse.click(*self.at(page, 300, 260)))
        sx, sy = self.at(page, 300, 260)
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + 30, sy + 20)
        page.mouse.up()
        page.wait_for_function('() => webUiImageStudio.app.dirty')
        page.click('[data-is="jsonsave"]')
        self.assertFalse(dirty())
        page.click('details:has([data-is="history"]) > summary')
        self.paint(page, lambda: page.click('[data-is="history"] li button'))
        self.assertTrue(dirty(), 'going to an older state is an edit too')
        page.click('[data-is="jsonsave"]')
        page.evaluate('async s => { await webUiImageStudio.app.replaceScene(s) }', self.scene(page))
        self.assertTrue(dirty())

    def test_a_layer_moves_one_place_backward_and_forward(self):
        page = self.page()
        self.blank(page)
        for i, tool in enumerate(['rect', 'ellipse', 'triangle']):
            self.tool(page, tool)
            self.press(page, 100 + 100 * i, 100)
        ids = [l['id'] for l in self.scene(page)['layers']]
        order = lambda: [l['id'] for l in self.scene(page)['layers']]
        self.paint(page, lambda: page.click('[data-is="back"]'))
        self.assertEqual(order(), [ids[0], ids[2], ids[1]])
        self.paint(page, lambda: page.click('[data-is="back"]'))
        self.assertEqual(order(), [ids[2], ids[0], ids[1]])
        self.paint(page, lambda: page.click('[data-is="back"]'))
        self.assertEqual(order(), [ids[2], ids[0], ids[1]], 'the bottom layer stays at the bottom')
        self.paint(page, lambda: page.click('[data-is="front"]'))
        self.assertEqual(order(), [ids[0], ids[2], ids[1]])
        self.paint(page, lambda: page.click('[data-is="front"]'))
        self.paint(page, lambda: page.click('[data-is="front"]'))
        self.assertEqual(order(), [ids[0], ids[1], ids[2]], 'the top layer stays at the top')

    def test_an_image_that_is_too_large_to_draw_is_reported_in_the_status_line(self):
        import web_ui as w
        page = self.page()
        self.blank(page)
        def attempt(png, cell):
            src = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
            scene = w.studio_blank()
            scene['layers'] = [w.studio_image_layer(src, 1, 1, 'img', 1280)]
            page.evaluate('async s => { await webUiImageStudio.app.replaceScene(s) }', scene)
            self.paint(page, lambda: page.mouse.click(*self.at(page, 100, 100)))
            page.evaluate('() => { document.querySelector("#imagestudio").dataset.error = "" }')
            page.evaluate('c => { const e = document.querySelector("[data-is=cell]"); e.value = c; e.dispatchEvent(new Event("change")) }', cell)
        big = w.studio_png_encode(2049, 2048, bytes(2049 * 2048 * 4))
        attempt(big, 2)
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
        self.assertEqual(self.status(page), '画像は4MP以下にしてください')
        fits = w.studio_png_encode(2048, 2048, bytes(2048 * 2048 * 4))
        attempt(fits, 2)
        page.wait_for_function('() => webUiImageStudio.app.scene.layers[0].cell === 2')
        page.wait_for_timeout(300)
        self.assertEqual(self.data(page, 'error'), '', '4 MP exactly is drawn')

    def test_files_of_exactly_32_mib_are_read_and_one_byte_more_is_refused(self):
        import web_ui as w
        limit = 32 * 1024 * 1024
        page = self.page()
        self.blank(page)
        png = bytes([137, 80, 78, 71, 13, 10, 26, 10])
        page.set_input_files('[data-is="file"]', files=[{'name': 'big.png', 'mimeType': 'image/png', 'buffer': png + bytes(limit - 8)}])
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
        self.assertEqual(self.status(page), '画像を読み込めません', 'exactly 32 MiB is read, and then cannot be decoded')
        page.evaluate('() => { document.querySelector("#imagestudio").dataset.error = "" }')
        page.set_input_files('[data-is="file"]', files=[{'name': 'big.png', 'mimeType': 'image/png', 'buffer': png + bytes(limit - 7)}])
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "画像は32MiB以下にしてください"')
        page.evaluate('() => { document.querySelector("#imagestudio").dataset.error = "" }')
        page.evaluate('() => { document.querySelector("[data-is=status]").textContent = "" }')
        page.set_input_files('[data-is="file"]', files=[{'name': 'empty.png', 'mimeType': 'image/png', 'buffer': b''}])
        page.wait_for_function('() => document.querySelector("#imagestudio").dataset.error === "1"')
        self.assertEqual(self.status(page), '画像は32MiB以下にしてください', 'an empty file is refused with the same words')
        scene_text = w.js_json(w.studio_demo_scene())
        padded = scene_text + ' ' * (20000000 - len(scene_text.encode('utf-8')))
        self.paint(page, lambda: page.set_input_files('[data-is="jsonopen"]', files=[{'name': 's.json', 'mimeType': 'application/json', 'buffer': padded.encode('utf-8')}]))
        self.assertEqual(self.data(page, 'layers'), '8', 'a scene file of exactly 20,000,000 bytes is read')
        page.set_input_files('[data-is="jsonopen"]', files=[{'name': 's.json', 'mimeType': 'application/json', 'buffer': (padded + ' ').encode('utf-8')}])
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "JSONは20MB以下にしてください"')
        history = w.StudioHistory(w.studio_blank())
        text = w.studio_workspace_text(history)
        fits = text + ' ' * (limit - len(text.encode('utf-8')))
        self.paint(page, lambda: page.set_input_files('[data-is="wsopen"]', files=[{'name': 'w.json', 'mimeType': 'application/json', 'buffer': fits.encode('utf-8')}]))
        self.assertEqual(self.status(page), 'Restored the history')
        page.set_input_files('[data-is="wsopen"]', files=[{'name': 'w.json', 'mimeType': 'application/json', 'buffer': (fits + ' ').encode('utf-8')}])
        page.wait_for_function('() => document.querySelector("[data-is=status]").textContent === "作業履歴は32MiB以下にしてください"')

    def test_trimming_the_history_asks_first_and_the_heading_names_the_layer(self):
        page = self.page(accept=False)
        self.blank(page)
        self.assertEqual(page.inner_text('[data-is="selection"]'), 'Select a layer')
        self.assertTrue(page.is_checked('[data-is="labels"]') and page.is_disabled('[data-is="labels"]'))
        self.tool(page, 'rect')
        self.press(page, 200, 200)
        self.assertEqual(page.inner_text('[data-is="selection"]'), '四角')
        self.assertTrue(page.is_checked('[data-is="labels"]'), 'the number labels box stays ticked for a layer without labels')
        before = page.evaluate('() => webUiImageStudio.app.history.items.length')
        page.click('details:has([data-is="history"]) > summary')
        page.click('[data-is="trim"]')
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate('() => webUiImageStudio.app.history.items.length'), before, 'a dismissed question keeps the history')
        accepting = self.page()
        self.blank(accepting)
        accepting.click('details:has([data-is="history"]) > summary')
        self.paint(accepting, lambda: accepting.click('[data-is="trim"]'))
        self.assertEqual(accepting.evaluate('() => webUiImageStudio.app.history.items.length'), 1)

    def test_the_examples_and_text_measuring(self):
        import web_ui as w
        page = self.page()
        self.paint(page, lambda: page.click('[data-is="stampdemo"]'))
        scene = self.scene(page)
        self.assertEqual(scene, json.loads(w.js_json(w.studio_stamp_demo_scene())))
        self.assertEqual(page.evaluate('() => webUiImageStudio.app.history.items.length'), 2)
        download, data = self.download(page, '[data-is="svg"]')
        self.assertTrue(self.same(data.decode('utf-8'), w.studio_svg(w.studio_stamp_demo_scene())))
        # wrapped text is measured with the installed fonts in the page and with an estimate in Python: both fit the box
        layer = {**w.studio_text_layer('a very long line of ordinary words that should wrap', 't', 0, 0, wrap=True), 'w': 200, 'fontSize': 24}
        page.evaluate('() => webUiImageStudio.useCanvasMetrics(true)')
        lines = page.evaluate('l => webUiImageStudio.textLayout(l)[0]', layer)
        self.assertGreater(len(lines), 1)
        self.assertEqual(''.join(lines).replace(' ', ''), layer['text'].replace(' ', ''))
        self.assertTrue(all(page.evaluate('([t, l]) => webUiImageStudio.measureText(t, l)', [line, layer]) <= 200 for line in lines))

    def test_the_page_fits_a_phone(self):
        page = self.page({'width': 320, 'height': 700})
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 320)
        self.assertLessEqual(page.evaluate('Math.max(...[...document.querySelectorAll("#imagestudio *:not(svg):not(svg *)")].map(e => e.getBoundingClientRect().right))'), 320.5)
        self.assertEqual(page.evaluate('getComputedStyle(document.querySelector("[data-is=board]")).touchAction'), 'pan-y')
        self.tool(page, 'rect')
        self.assertEqual(page.evaluate('getComputedStyle(document.querySelector("[data-is=board]")).touchAction'), 'none', 'placing needs the touch for itself')


class MockAuthBrowserTests(unittest.TestCase):
    """Real same-origin fetches, public fixtures, no external authentication."""
    setUp = PatternBridgeBrowserTests.setUp
    start_bridge = PatternBridgeBrowserTests.start_bridge
    tearDown = PatternBridgeBrowserTests.tearDown

    def page(self):
        page = self.context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('request', lambda r: self.external.append(r.url) if r.url.startswith('http') and not r.url.startswith(self.origin + '/') else None)
        page.goto(self.origin + '/auth.html')
        page.wait_for_function('document.getElementById("auth-request").value.includes("demo-bearer-token")')
        return page

    def prepare(self, page, scenario):
        page.locator('#auth-scenario').select_option(scenario)
        page.locator('#auth-result').evaluate('(el) => el.textContent = ""')
        page.locator('#auth-prepare').click()
        page.wait_for_function('document.getElementById("auth-result").textContent === "Fresh public demo request prepared."')
        return json.loads(page.locator('#auth-request').input_value())

    def run_mock(self, page):
        page.locator('#auth-result').evaluate('(el) => el.textContent = ""')
        page.locator('#auth-run').click()
        page.wait_for_function('document.getElementById("auth-result").textContent.startsWith("{")')
        return json.loads(page.locator('#auth-result').inner_text())

    def test_all_demo_presets_and_actual_http_status_headers(self):
        page = self.page()
        statuses = dict(zip(self.web_ui.AUTH_SCENARIOS, [404,200,401,403,200,200,200,401,200,200,429]))
        for scenario, status in statuses.items():
            with self.subTest(scenario=scenario):
                self.prepare(page, scenario)
                result = self.run_mock(page)
                self.assertEqual(result['status'], status)
                if scenario == 'digestChallengeOnly':
                    self.assertEqual(result['headers']['www-authenticate'], self.web_ui.AUTH_DIGEST_CHALLENGE)
                if scenario == 'rateLimited':
                    self.assertEqual(result['headers']['retry-after'], '1')
                if scenario in ('digest', 'hmac'):
                    replay = self.run_mock(page)
                    self.assertEqual((replay['status'], replay['body']['reason']), (401, 'digest_replay' if scenario == 'digest' else 'replay'))

    def test_edits_fail_without_consuming_nonce_and_json_is_text(self):
        page = self.page()
        original = self.prepare(page, 'hmac')
        changed = {**original, 'body': '<img src=x onerror=alert(1)>'}
        page.locator('#auth-request').fill(json.dumps(changed))
        result = self.run_mock(page)
        self.assertEqual((result['status'],result['body']['reason']), (401,'invalid_signature'))
        page.locator('#auth-request').fill(json.dumps(original))
        self.assertEqual(self.run_mock(page)['status'],200)
        page.locator('#auth-request').fill('{')
        page.locator('#auth-run').click()
        page.wait_for_function('document.getElementById("auth-result").textContent.includes("SyntaxError")')
        self.assertEqual(page.locator('#auth-result img').count(),0)

    def test_controls_and_output_fit_320_pixels(self):
        page = self.page()
        page.set_viewport_size({'width':320,'height':900})
        self.prepare(page,'digest')
        self.assertEqual(self.run_mock(page)['status'],200)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320)
        for selector in ('#auth-scenario','#auth-prepare','#auth-request','#auth-run','#auth-result'):
            bounds=page.locator(selector).bounding_box()
            self.assertGreaterEqual(bounds['x'],-0.5)
            self.assertLessEqual(bounds['x']+bounds['width'],320.5)


if __name__ == '__main__':
    unittest.main()

