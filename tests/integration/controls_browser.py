"""Required Chromium contract: python tests/integration/controls_browser.py -v.

Invoked explicitly by the browser CI job; missing Playwright/browser is an error.
The ordinary dependency-light unit suite does not discover this module.
"""
import functools
import http.server
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from web_ui import (EXAMPLE_STUBS, bundled_css, write_js, board_clock, clean_message, clock_label, gauge_cells, gauge_state, minutes_until, travel_seconds, board_seconds,
                    clamp_focus, contrast_ratio, fit_zoom, render_document, section_browser, shared_scripts, stub_response, theme_wall_document, utc_offset_label,
                    world_document, zone_offset, zone_rows)


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
        server, origin = self.serve({'index.html': world_document(spec)})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for width in (320, 390, 800):
                        with self.subTest(width=width):
                            page = browser.new_page(viewport={'width': width, 'height': 700})
                            page.goto(origin + '/index.html')
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
                    self.assertEqual(int(board.get_attribute('data-chars')), base + 10)
                    self.assertEqual(len(set(board.locator('.ui-board-note .ui-board-stamp').all_text_contents())), 1)   # each line carries its HH:MM stamp
                    expect(board.locator('.ui-board-run')).to_have_css('animation-duration', f'{board_seconds(base + 10):g}s')
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


if __name__ == '__main__':
    unittest.main()
