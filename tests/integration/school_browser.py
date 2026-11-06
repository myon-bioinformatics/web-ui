"""Required Chromium contract for the school world: python tests/integration/school_browser.py -v.

The emoji picker comes first, then the player walks by tap, arrow keys / WASD and the on-screen pad.
Solid props (desks, board, shelves) are never entered, whichever way the player moves.
Invoked explicitly by the browser CI job; missing Playwright/browser is an error. WEB_UI_CHROME may name a local Chrome.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tool"))
import record_demo  # noqa: E402
import web_ui  # noqa: E402

SPEC = web_ui.example_data("school")
CLASSROOM = '.ui-floor[data-floor="classroom"]'
POS = f"() => {{ const s = document.querySelector('{CLASSROOM} .ui-player').style; return [parseFloat(s.getPropertyValue('--px')), parseFloat(s.getPropertyValue('--py'))]; }}"
WALL = "() => document.querySelector('.ui-floor[data-floor=\"classroom\"]').dataset.blocked.split(',')"


def launch(pw):
    chrome = os.environ.get("WEB_UI_CHROME")
    return pw.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else pw.chromium.launch()


class SchoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.page_path = Path(cls.tmp.name) / "school.html"
        cls.page_path.write_text(web_ui.world_document(SPEC), encoding="utf-8")
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, width=1280, height=800, touch=False, js=True):
        context = self.browser.new_context(viewport={"width": width, "height": height}, has_touch=touch, is_mobile=touch,
                                           java_script_enabled=js)
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(self.page_path.as_uri())
        return page

    def start(self, page, emoji="🐱"):
        page.click(f'[data-emoji="{emoji}"]')
        page.wait_for_function("() => !document.querySelector('.ui-world').hasAttribute('data-pick')")
        page.wait_for_timeout(400)                                          # the camera finishes its short glide

    def cell(self, page):
        x, y = page.evaluate(POS)
        tile = int(page.get_attribute(CLASSROOM, "data-tile"))
        return int(x // tile), int(y // tile)

    def assert_free(self, page, point):
        tile = int(page.get_attribute(CLASSROOM, "data-tile"))
        rows = page.evaluate(WALL)
        self.assertEqual(rows[int(point[1] // tile)][int(point[0] // tile)], "0", f"inside a solid tile at {point}")

    def settle(self, page, timeout=15000):
        """Wait until the player stands still at its target."""
        page.wait_for_function(
            f"() => {{ const p = document.querySelector('{CLASSROOM} .ui-player'), s = p.style;"
            "return Math.abs(parseFloat(s.getPropertyValue('--px')) - +p.dataset.targetX) < .01 && Math.abs(parseFloat(s.getPropertyValue('--py')) - +p.dataset.targetY) < .01 }",
            timeout=timeout)

    def tap_map(self, page, x, y):
        box = page.evaluate(f"() => {{ const r = document.querySelector('{CLASSROOM}').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }}")
        page.mouse.click(box[0] + x * box[2] / 384, box[1] + y * box[3] / 512)

    def test_picker_comes_first_and_changes_every_player(self):
        page = self.open()
        self.assertTrue(page.is_visible(".ui-world-pick"))
        self.assertEqual(page.eval_on_selector(f"{CLASSROOM} .ui-player", "e => getComputedStyle(e).visibility"), "hidden")
        page.fill('.ui-world-pick-form input', "x" * 17)                    # too long for one label
        page.press('.ui-world-pick-form input', "Enter")
        self.assertTrue(page.is_visible(".ui-world-pick"))
        page.fill('.ui-world-pick-form input', "   ")
        page.press('.ui-world-pick-form input', "Enter")
        self.assertTrue(page.is_visible(".ui-world-pick"))
        page.fill('.ui-world-pick-form input', "ねこ🐱")                    # text, or emoji and text, is a character too
        page.press('.ui-world-pick-form input', "Enter")
        self.assertFalse(page.is_visible(".ui-world-pick"))
        self.assertEqual(page.eval_on_selector_all(".ui-player span", "els => els.map(e => e.textContent)"), ["ねこ🐱", "ねこ🐱"])
        page.click("[data-pick-open]")
        page.fill('.ui-world-pick-form input', "🦖")
        page.press('.ui-world-pick-form input', "Enter")
        self.assertFalse(page.is_visible(".ui-world-pick"))
        self.assertEqual(page.eval_on_selector_all(".ui-player span", "els => els.map(e => e.textContent)"), ["🦖", "🦖"])
        page.click("[data-pick-open]")
        self.assertTrue(page.is_visible(".ui-world-pick"))
        self.assertEqual(self.errors, [])

    def test_every_demo_scene_records_a_gif(self):
        """The README demos (tool/record_demo.py) are real operations; a UI change that breaks one fails here, not in the next README."""
        with tempfile.TemporaryDirectory() as out:
            paths = record_demo.record(out, browser=self.browser)
            self.assertEqual({p.name for p in paths}, {f"school-{name}.gif" for name in record_demo.SCENES})
            for path in paths:
                data = path.read_bytes()
                self.assertEqual(data[:6], b"GIF89a", path.name)
                self.assertGreater(len(data), 20_000, path.name)               # something moved
                self.assertLess(len(data), 3 * 1024 * 1024, path.name)         # and the README stays light

    def test_without_javascript_the_static_map_stays_and_nothing_interactive_shows(self):
        page = self.open(js=False)
        self.assertFalse(page.is_visible(".ui-world-pick"))
        self.assertFalse(page.is_visible(".ui-world-dpad"))
        self.assertTrue(page.is_visible(f"{CLASSROOM} .ui-spot"))

    def test_arrow_keys_wasd_and_walls(self):
        page = self.open()
        self.start(page)
        start = self.cell(page)
        page.keyboard.press("ArrowLeft")                                    # the shelf beside the door
        page.wait_for_timeout(300)
        self.assertEqual(self.cell(page), start)
        page.keyboard.press("ArrowDown")                                    # the edge of the floor
        page.wait_for_timeout(300)
        self.assertEqual(self.cell(page), start)
        page.keyboard.press("w")
        self.settle(page)
        self.assertEqual(self.cell(page), (start[0], start[1] - 1))
        page.keyboard.press("ArrowRight")
        self.settle(page)
        self.assertEqual(self.cell(page), (start[0] + 1, start[1] - 1))
        page.keyboard.press("a")
        self.settle(page)
        self.assertEqual(self.cell(page), (start[0], start[1] - 1))
        self.assertEqual(self.errors, [])

    def test_holding_a_key_walks_on_and_stops_at_a_desk(self):
        page = self.open()
        self.start(page)
        for _ in range(60):                                                 # straight up from the door, key repeating, into a desk row
            page.keyboard.down("ArrowUp")
            page.wait_for_timeout(40)
            self.assert_free(page, page.evaluate(POS))
        page.keyboard.up("ArrowUp")
        self.settle(page)
        self.assertEqual(self.cell(page), (5, 12))                          # the chair tile just below the first desk
        self.assert_free(page, page.evaluate(POS))

    def test_tap_walks_around_desks_and_never_cuts_through_them(self):
        page = self.open()
        self.start(page)
        self.tap_map(page, 80, 272)                                         # a chair behind two desk rows: a straight line crosses desks
        seen = []
        for _ in range(600):
            seen.append(page.evaluate(POS))
            if abs(seen[-1][0] - 80) < .01 and abs(seen[-1][1] - 272) < .01:
                break
            page.wait_for_timeout(30)
        for point in seen:
            self.assert_free(page, point)
        self.assertEqual(self.cell(page), (2, 8))
        self.assertGreater(len({tuple(p) for p in seen}), 20)

    def test_tap_on_a_desk_ends_on_the_nearest_free_tile(self):
        page = self.open()
        self.start(page)
        self.tap_map(page, 80, 176)                                         # on a desk (tile 2,5)
        self.settle(page)
        self.assert_free(page, page.evaluate(POS))
        x, y = page.evaluate(POS)
        self.assertLess(abs(x - 80) + abs(y - 176), 64)

    def test_on_screen_pad_on_a_phone(self):
        page = self.open(390, 844, touch=True)
        self.start(page)
        self.assertTrue(page.is_visible(".ui-world-dpad"))
        start = self.cell(page)
        page.dispatch_event('[data-step="0,-1"]', "pointerdown")             # press and hold the up button
        page.wait_for_timeout(700)
        page.dispatch_event('[data-step="0,-1"]', "pointerup")
        self.settle(page)
        self.assertLessEqual(self.cell(page)[1], start[1] - 2)
        self.assert_free(page, page.evaluate(POS))
        before = self.cell(page)
        page.dispatch_event('[data-step="-1,0"]', "pointerdown")
        page.dispatch_event('[data-step="-1,0"]', "pointerup")
        self.settle(page)
        self.assertNotEqual(self.cell(page), before)
        self.assertEqual(self.errors, [])

    def test_open_floor_has_no_grid_pad_and_keeps_free_walking(self):
        page = self.open()
        self.start(page)
        page.click('label[for="school-floor-yard"]')
        page.wait_for_selector(".ui-world-dpad", state="hidden")
        page.keyboard.press("ArrowUp")                                      # no grid here: the key is left to the page
        self.assertEqual(self.errors, [])

    def test_layout_fits_at_phone_and_desktop_widths(self):
        for width, height, touch in ((320, 640, True), (390, 844, True), (768, 1024, False), (1280, 800, False)):
            page = self.open(width, height, touch)
            self.start(page)
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - innerWidth"), 0, f"overflow at {width}")
            self.assertTrue(page.is_visible(".ui-world-dpad"), f"pad at {width}")
            box = page.evaluate(f"() => {{ const r = document.querySelector('{CLASSROOM} .ui-player').getBoundingClientRect(); return [r.left, r.right]; }}")
            self.assertGreaterEqual(box[0], 0)
            self.assertLessEqual(box[1], width)


if __name__ == "__main__":
    unittest.main()
