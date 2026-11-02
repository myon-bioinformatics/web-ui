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
from web_ui import (EXAMPLE_STUBS, bundled_css, write_js, clean_message, minutes_until, travel_seconds, board_seconds, clamp_focus, contrast_ratio, fit_zoom, render_document, section_browser,
                    shared_scripts, stub_response, theme_wall_document, world_document)


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
                    expect(page.locator('[data-clock]')).to_have_text('10:00')
                    texts = page.locator('.ui-board-run [data-at]').all_text_contents()
                    expected = [f'あと{minutes_until(600, h * 60 + m)}分' for h, m in ((10, 30), (14, 0), (17, 30))] * 2
                    self.assertEqual(texts, expected)
                    cases = [(600, 630), (600, 600), (1430, 10), (0, 1439)]
                    self.assertEqual(page.evaluate('cases => cases.map(c => webUiWorld.minutesUntil(...c))', cases), [minutes_until(*c) for c in cases])
                    self.assertEqual(page.evaluate('[1, 64, 160, 400].map(n => webUiWorld.boardSeconds(n))'), [board_seconds(n) for n in (1, 64, 160, 400)])
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
                    self.assertEqual(notes, [clean_message(t) for t in reversed(lines[:3])] * 2)
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
                    halves = board.evaluate("""b => {const rows=[...b.querySelectorAll('.ui-board-item')].map(n=>n.textContent);return [rows.slice(0,rows.length/2),rows.slice(rows.length/2)]}""")
                    self.assertEqual(halves[0], halves[1])
                    self.assertEqual(halves[0][:5], ['7😀', '6😀', '5😀', '4😀', '3😀'])
                    self.assertEqual(board.locator('.ui-board-note').count(), 10)
                    self.assertEqual(int(board.get_attribute('data-chars')), base + 10)
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


if __name__ == '__main__':
    unittest.main()
