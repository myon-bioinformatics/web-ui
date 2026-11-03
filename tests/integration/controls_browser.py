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
import shutil
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
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


class PhotoPageBrowserTests(unittest.TestCase):
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

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        self.server.shutdown()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

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


class ClipboardBrowserTests(unittest.TestCase):
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

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        self.server.shutdown()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

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


def flutter_case(tid, sid, name, result='success', **done):
    return [{'type': 'testStart', 'test': {'id': tid, 'suiteID': sid, 'name': name}}, {'type': 'testDone', 'testID': tid, 'result': result, **done}]



class PlaygroundBrowserTests(unittest.TestCase):
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

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        self.server.shutdown()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

    def page(self, clock=False):
        page = self.context.new_page()
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('request', lambda request: self.external.append(request.url) if request.url.startswith('http') and not request.url.startswith(self.origin + '/') else None)
        if clock:
            page.clock.install()
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


class ReportBrowserTests(unittest.TestCase):
    """The test report in a real browser: SHA-256, the Flutter tally and conversion, JUnit reading and the failure history equal Python's on seeded fuzz, and the page works."""

    def setUp(self):
        from web_ui import report_document
        self.server, self.origin = WorldBrowserTests.serve({'report.html': report_document()})
        self.playwright_manager = sync_playwright()
        self.playwright = self.playwright_manager.__enter__()
        self.browser = photo_engine(self.playwright).launch()
        self.context = self.browser.new_context(viewport={'width': 900, 'height': 1200})
        self.errors, self.external = [], []

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        self.server.shutdown()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

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


class McpBrowserTests(unittest.TestCase):
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

    def tearDown(self):
        self.browser.close()
        self.playwright_manager.__exit__(None, None, None)
        self.server.shutdown()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

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


if __name__ == '__main__':
    unittest.main()
