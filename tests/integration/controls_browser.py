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
from web_ui import bundled_css, render_document, section_browser, shared_scripts


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
            (root / 'js').mkdir()
            shutil.copyfile(ROOT / 'js/controls.js', root / 'js/controls.js')
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
            (root / 'js').mkdir()
            shutil.copyfile(ROOT / 'js/ui.js', root / 'js/ui.js')
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
                        self.assertEqual(copied, ['x<y&z', 0])
                        self.assertEqual(errors, [])
                        self.assertEqual(external, [])
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
