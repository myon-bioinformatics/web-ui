"""Required Chromium contract for the school world: python tests/integration/school_browser.py -v.

The emoji picker comes first, then the player walks by tap, arrow keys / WASD and the on-screen pad.
Solid props (desks, board, shelves) are never entered, whichever way the player moves.
Invoked explicitly by the browser CI job; missing Playwright/browser is an error. WEB_UI_CHROME may name a local Chrome.
``CitiesTests`` sweeps the three cities (every spot, sign, tool, width and language); with WEB_UI_SHOTS=DIR it also keeps a
screenshot of each check, a manifest.json and one index.html in DIR (Pillow writes them as WebP).
"""
import copy
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tool"))
import record_demo  # noqa: E402
import web_ui  # noqa: E402

SPEC = web_ui.example_data("school")
CLASSROOM = '.ui-floor[data-floor="classroom"]'
POS = f"() => {{ const s = document.querySelector('{CLASSROOM} .ui-player').style; return [parseFloat(s.getPropertyValue('--px')), parseFloat(s.getPropertyValue('--py'))]; }}"
WALL = "() => document.querySelector('.ui-floor[data-floor=\"classroom\"]').dataset.blocked.split(',')"


class SchoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.page_path = Path(cls.tmp.name) / "school.html"
        cls.page_path.write_text(web_ui.world_document(SPEC), encoding="utf-8")
        cls.pw = sync_playwright().start()
        cls.browser = record_demo.launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, width=1280, height=800, touch=False, js=True, path=None):
        context = self.browser.new_context(viewport={"width": width, "height": height}, has_touch=touch, is_mobile=touch,
                                           java_script_enabled=js)
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto((path or self.page_path).as_uri())
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

    def menu(self, page, name):
        """Open (or close) one of the side or header menus: ``spots`` ☰, ``more`` ⋯, ``favorites`` ⭐, ``settings`` ⚙️."""
        page.click(f'.ui-world-menu[data-menu="{name}"] summary')

    def settle(self, page, timeout=15000):
        """Wait until the player of the shown floor stands still at its target."""
        page.wait_for_function(record_demo.SETTLED, timeout=timeout)

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
        self.menu(page, "settings")        # the ⚙️ menu (header) holds the picker button
        page.click("[data-pick-open]")
        page.fill('.ui-world-pick-form input', "🦖")
        page.press('.ui-world-pick-form input', "Enter")
        self.assertFalse(page.is_visible(".ui-world-pick"))
        self.assertEqual(page.eval_on_selector_all(".ui-player span", "els => els.map(e => e.textContent)"), ["🦖", "🦖"])
        self.menu(page, "settings")        # the ⚙️ menu (header) holds the picker button
        page.click("[data-pick-open]")
        self.assertTrue(page.is_visible(".ui-world-pick"))
        self.assertEqual(self.errors, [])

    def test_every_demo_scene_records_a_gif(self):
        """The README demos (tool/record_demo.py) are real operations; a UI change that breaks one fails here, not in the next README."""
        with tempfile.TemporaryDirectory() as out:
            paths = record_demo.record(out, browser=self.browser)
            self.assertEqual({p.name for p in paths}, {f"{sc.world}-{name}.gif" for name, sc in record_demo.SCENES.items()})
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

    def test_side_menus_footer_pulldown_and_arrows(self):
        """Header: the board. Side: ☰ places with arrows, ⋯ settings. Footer: the door-to-door pulldown. The page never grows taller."""
        page = self.open(390, 844, True)
        self.start(page)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollHeight - innerHeight"), 0)
        self.assertFalse(page.is_visible(".ui-world-panel"))
        self.assertFalse(page.is_visible(".ui-world-foot .ui-world-bar"))              # the pulldown replaces the floor labels
        spots, more = '.ui-world-menu[data-menu="spots"]', '.ui-world-menu[data-menu="more"]'
        arrows = lambda floor: page.eval_on_selector_all(f'.ui-world-spots[data-floor="{floor}"] .ui-world-arrow', "els => els.map(e => e.textContent)")
        page.click(f"{spots} summary")
        self.assertTrue(page.is_visible('.ui-world-spots[data-floor="classroom"]'))
        self.assertFalse(page.is_visible('.ui-world-spots[data-floor="yard"]'))
        page.wait_for_function("() => document.querySelector('.ui-world-arrow').textContent !== '📍'")
        self.assertEqual(arrows("classroom"), ["⬆️", "⬆️", "⬆️"])                      # standing at the door: all three are ahead
        page.click(f"{more} summary")                                                  # one menu at a time
        page.wait_for_function(f"() => !document.querySelector('{spots}').open")      # (the toggle event is queued)
        page.keyboard.press("Escape")
        self.assertFalse(page.evaluate(f"document.querySelector('{more}').open"))
        page.click(f"{spots} summary")
        page.click('.ui-world-spots a[href="#school-spot-classroom-board"]')          # a place in the list: walk there and read it
        self.assertFalse(page.evaluate(f"document.querySelector('{spots}').open"))
        page.wait_for_function("() => { const p = document.querySelector('.ui-floor[data-floor=\"classroom\"] .ui-player'); const s = p.style;"
                               " return Math.abs(parseFloat(s.getPropertyValue('--py')) - +p.dataset.targetY) < .01 }")
        self.assertTrue(page.is_visible("#school-spot-classroom-board"))
        page.click(".ui-sheet-close:visible")
        page.click(f"{spots} summary")
        page.wait_for_function("() => document.querySelector('.ui-world-arrow').textContent === '📍'")   # arrived: within a tile
        player = page.evaluate(POS)                                                    # the page's arrows are the oracle's, point for point
        want = [web_ui.world_direction(player, [x, y], 32) for x, y in ((192, 16), (192, 112), (192, 432))]
        self.assertEqual(arrows("classroom"), want)
        self.assertEqual(want[0], "📍")
        page.keyboard.press("Escape")
        page.select_option(".ui-world-goto", "yard")                                   # door to door: the footer pulldown
        page.click(f"{spots} summary")
        self.assertTrue(page.is_visible('.ui-world-spots[data-floor="yard"]'))
        self.assertFalse(page.is_visible('.ui-world-spots[data-floor="classroom"]'))
        page.click('.ui-world-spots a[href="#school-spot-flowers"]')
        self.assertEqual(page.input_value(".ui-world-goto"), "yard")
        self.assertTrue(page.is_visible("#school-spot-flowers"))
        self.assertEqual(self.errors, [])

    def test_header_home_favorites_settings_language_and_emoji_tools(self):
        """The header holds what is global: 🏠 ⭐ ⚙️ and the emoji tools; every button is an icon whose words are its aria-label."""
        page = self.open(390, 844, True)
        self.start(page)
        head = ".ui-world-head"
        menu = lambda name: f'{head} .ui-world-menu[data-menu="{name}"]'
        label = lambda sel: page.get_attribute(sel, "aria-label")
        self.assertEqual(self.errors, [])
        self.assertEqual([label(sel) for sel in (f"{head} .ui-world-home", f'{menu("favorites")} summary', f'{menu("settings")} summary')],
                         ["ホーム", "お気に入り", "全体設定"])
        # ⭐: star places on two floors (session only), jump to one from the panel, remove it
        self.menu(page, "spots")
        page.click('.ui-world-spots[data-floor="classroom"] li:nth-child(1) .ui-world-star')
        page.select_option(".ui-world-goto", "yard")
        page.click('.ui-world-spots[data-floor="yard"] li:nth-child(2) .ui-world-star')
        self.assertEqual(page.eval_on_selector_all(".ui-world-spots .ui-world-star[aria-pressed=true]", "els => els.map(e => e.textContent)"), ["★", "★"])
        page.keyboard.press("Escape")
        page.click(f'{menu("favorites")} summary')
        self.assertFalse(page.is_visible(f"{head} .ui-world-empty"))
        self.assertEqual(page.eval_on_selector_all(f"{head} .ui-world-favs a", "els => els.map(e => e.lastChild.textContent)"), ["黒板", "花だん"])
        page.click(f'{head} .ui-world-favs a[href="#school-spot-classroom-board"]')    # a favourite on the other floor: go there
        self.assertEqual(page.input_value(".ui-world-goto"), "classroom")
        self.assertTrue(page.is_visible("#school-spot-classroom-board"))
        self.assertFalse(page.evaluate(f"document.querySelector('{menu('favorites')}').open"))
        page.click(f'{menu("favorites")} summary')
        page.click(f'{head} .ui-world-favs li:nth-child(1) .ui-world-star')           # un-star from the panel
        self.assertEqual(page.eval_on_selector_all(f"{head} .ui-world-favs a", "els => els.length"), 1)
        # 🏠: first floor in view, sheet and menus closed, categories cleared
        page.select_option(".ui-world-goto", "yard")
        page.click(f"{head} .ui-world-home")                                              # 🏠 asks first: ✖️ stays where it is, 🏠 goes
        self.assertEqual(page.get_attribute(".ui-world-ask [role=dialog]", "aria-label"), "ホーム")
        page.click('.ui-world-ask button[data-t="close"]')
        self.assertEqual(page.input_value(".ui-world-goto"), "yard")
        page.click(f"{head} .ui-world-home")
        page.click('.ui-world-ask button[data-t="home"]')
        self.assertEqual(page.input_value(".ui-world-goto"), "classroom")
        self.assertFalse(page.is_visible(".ui-sheet-item[data-open]"))
        self.assertEqual(page.evaluate("location.hash"), "")
        # ⚙️: pause is an icon that flips, 🌐 turns every label into English and back
        page.click(f'{menu("settings")} summary')
        page.click(f"{head} .ui-world-pause")
        self.assertEqual(page.text_content(f"{head} .ui-world-pause"), "▶️")
        self.assertEqual(page.get_attribute(f"{head} .ui-world-pause", "aria-pressed"), "true")
        self.assertTrue(page.evaluate("document.querySelector('.ui-world').hasAttribute('data-motion-paused')"))
        page.click(f"{head} .ui-world-pause")
        self.assertEqual(page.text_content(f"{head} .ui-world-pause"), "⏸️")
        page.select_option(f"{head} [data-lang]", "fr")
        self.assertEqual([label(f"{head} .ui-world-home"), label(f'{menu("favorites")} summary'), label('.ui-world-dpad [data-step="0,-1"]'), label(".ui-world-goto")],
                         ["Accueil", "Favoris", "Haut", "Aller à l'étage"])
        self.assertEqual(page.get_attribute(f"{head} .ui-world-home", "title"), "Accueil")
        self.assertEqual(page.evaluate("document.querySelector('.ui-world').lang"), "fr")
        page.select_option(f"{head} [data-lang]", "ar")
        self.assertEqual(label(f"{head} .ui-world-home"), "الرئيسية")
        page.select_option(f"{head} [data-lang]", "en")
        self.assertEqual([label(f"{head} .ui-world-home"), label(f'{menu("favorites")} summary'), label('.ui-world-dpad [data-step="0,-1"]'), label(".ui-world-goto")],
                         ["Home", "Favorites", "Up", "Go to floor"])
        page.select_option(f"{head} [data-lang]", "ja")
        self.assertEqual(label(f"{head} .ui-world-home"), "ホーム")
        # the emoji tools of the school example: 🗺️ lists places with arrows, 🏫 shows a note; one menu at a time
        page.keyboard.press("Escape")
        page.click(f'{menu("tool")}:has(summary:text("🗺️")) summary')
        self.assertTrue(page.is_visible(f'{head} .ui-world-rows:not(.ui-world-favs) a[href="#school-spot-flowers"]'))
        page.wait_for_function("() => document.querySelector('.ui-world-head .ui-world-rows:not(.ui-world-favs) a .ui-world-arrow').textContent !== '📍'")
        self.assertEqual(page.eval_on_selector_all(f"{head} .ui-world-rows:not(.ui-world-favs) .ui-world-arrow", "els => els.map(e => e.textContent)"), ["⬆️", "🚪"])
        page.click(f'{menu("tool")}:has(summary:text("🏫")) summary')
        page.wait_for_function("() => document.querySelectorAll('.ui-world-menu[open]').length === 1")
        self.assertIn("教室と校庭", page.inner_text(f'{menu("tool")}[open]'))
        self.assertEqual(self.errors, [])

    def test_favorites_and_language_come_back_from_the_cache_and_nothing_else_does(self):
        posting = Path(self.tmp.name) / "posting.html"                                     # the same school with the board's message box on
        posting.write_text(web_ui.world_document({**SPEC, "board": {**SPEC["board"], "post": True}}), encoding="utf-8")
        page = self.open(path=posting)
        head = ".ui-world-head"
        self.start(page, "🦊")
        self.menu(page, "spots")
        page.click('.ui-world-spots[data-floor="classroom"] li:nth-child(1) .ui-world-star')
        page.keyboard.press("Escape")
        self.menu(page, "settings")
        page.select_option(f"{head} [data-lang]", "de")
        page.keyboard.press("Escape")
        page.fill(".ui-board-post input", "hallo")                                          # a board message is only in the page
        page.press(".ui-board-post input", "Enter")
        self.assertIn("hallo", page.inner_text(".ui-board-run"))
        stored = page.evaluate("Object.fromEntries(Object.entries(localStorage))")
        self.assertEqual(list(stored), ["ui-world:school-map"])
        self.assertEqual(sorted(__import__("json").loads(stored["ui-world:school-map"])), ["fav", "lang"])
        self.assertNotIn("🦊", stored["ui-world:school-map"])
        self.assertNotIn("hallo", stored["ui-world:school-map"])
        page.reload()                                                                        # a visit later: starred place and language are back, the picker is asked again
        self.assertEqual(page.get_attribute(f"{head} .ui-world-home", "aria-label"), "Startseite")
        self.assertEqual(page.eval_on_selector_all(".ui-world-spots .ui-world-star[aria-pressed=true]", "els => els.length"), 1)
        self.assertEqual(page.input_value(f"{head} [data-lang]"), "de")
        self.assertTrue(page.is_visible(".ui-world-pick"))
        page.evaluate("localStorage.setItem('ui-world:school-map', '{\"fav\":[\"#nope\",7],\"lang\":\"xx\"}')")      # damaged or foreign cache is ignored
        page.reload()
        self.assertEqual(page.get_attribute(f"{head} .ui-world-home", "aria-label"), "ホーム")
        self.assertEqual(page.eval_on_selector_all(".ui-world-spots .ui-world-star[aria-pressed=true]", "els => els.length"), 0)
        page.evaluate("localStorage.setItem('ui-world:school-map', 'not json')")
        page.reload()
        self.assertEqual(self.errors, [])

    def test_overworld_lands_are_swapped_by_the_pulldown_and_walked_across(self):
        """Six lands from one line of JSON each: terrain is CSS (colour and an emoji per tile), the walk is the same grid."""
        path = Path(self.tmp.name) / "overworld.html"
        path.write_text(web_ui.world_document(web_ui.example_data("overworld")), encoding="utf-8")
        page = self.open(path=path)
        self.start(page, "🧙")
        self.assertEqual(page.eval_on_selector_all(".ui-world-goto option", "els => els.map(e => e.value)"),
                         ["meadow", "forest", "mountain", "desert", "coast", "castle", "real"])
        for land, kind in (("meadow", "water"), ("forest", "tree"), ("mountain", "mountain"), ("desert", "cactus"), ("coast", "water"), ("castle", "castle")):
            page.select_option(".ui-world-goto", land)
            page.wait_for_function(f"() => getComputedStyle(document.querySelector('.ui-floor[data-floor=\"{land}\"]')).display !== 'none'")
            style = page.eval_on_selector(f'.ui-floor[data-floor="{land}"] .ui-prop[data-kind="{kind}"]',
                                          "e => { const c = getComputedStyle(e); return [c.backgroundImage, c.backgroundSize, c.borderTopWidth] }")
            self.assertIn("data:image/svg+xml", style[0], land)
            self.assertEqual(style[2], "0px")
            self.assertTrue(page.is_visible(f'.ui-floor[data-floor="{land}"] .ui-player'))
        self.assertIn("contain", style[1])                                           # the castle is drawn once; the trees below once per tile
        page.select_option(".ui-world-goto", "forest")
        self.assertEqual(page.eval_on_selector('.ui-floor[data-floor="forest"] .ui-prop[data-kind="tree"]', "e => getComputedStyle(e).backgroundSize").split(",")[0], "32px 32px")
        spot = next(s for f in web_ui.world_validate(web_ui.example_data("overworld"))["floors"] if f["id"] == "forest" for s in f["spots"] if s["id"] == "forest-town")
        self.menu(page, "spots")
        page.click('.ui-world-spots[data-floor="forest"] a[href="#overworld-spot-forest-town"]')
        page.wait_for_function(record_demo.SETTLED, timeout=20000)
        x, y = page.evaluate("() => { const s = document.querySelector('.ui-floor[data-floor=\"forest\"] .ui-player').style; return [parseFloat(s.getPropertyValue('--px')), parseFloat(s.getPropertyValue('--py'))]; }")
        self.assertAlmostEqual(x, spot["x"], delta=1)
        self.assertAlmostEqual(y, spot["y"], delta=1)
        self.assertEqual(self.errors, [])

    def test_the_cities_flip_a_sign_into_a_dragon_and_burn_one_fire_per_block(self):
        """Signs are a dot until touched (Reverse London's wooden nogard: dot, text, 🐉, dot; Tokyo's electronic boards: dot, text); Tokyo has electronic boards; Fake Paris draws its fires as tile emoji."""
        path = Path(self.tmp.name) / "cities.html"
        path.write_text(web_ui.world_document(web_ui.example_data("cities")), encoding="utf-8")
        page = self.open(path=path)
        self.start(page, "🧳")
        self.assertEqual(page.eval_on_selector_all(".ui-world-goto option", "els => els.map(e => e.value)"), ["tokyo", "london", "paris"])
        page.select_option(".ui-world-goto", "london")
        sign = '.ui-floor[data-floor="london"] .ui-spot[data-flip]'
        face = lambda: page.eval_on_selector(sign, "e => [e.textContent, e.dataset.show || '', getComputedStyle(e).fontSize]")    # noqa: E731
        self.assertEqual(page.get_attribute(sign, "data-sign"), "wood")
        style = page.eval_on_selector(sign, "e => { const c = getComputedStyle(e), b = getComputedStyle(e, '::before'); return [c.backgroundColor, b.content] }")
        self.assertEqual(style, ["rgb(139, 90, 43)", '"●"'])                                          # a wooden board: a bold dot until it is touched
        self.assertEqual(face(), ["nogard", "", "0px"])
        page.eval_on_selector(sign, "e => e.click()")
        self.assertEqual(face(), ["nogard", "label", "11.2px"])                                      # the board shows its text
        page.eval_on_selector(sign, "e => e.click()")
        self.assertEqual(face(), ["🐉", "flip", "11.2px"])                                           # then its second face
        page.eval_on_selector(sign, "e => e.click()")
        self.assertEqual(face(), ["nogard", "", "0px"])                                              # and the dot again
        led = '.ui-floor[data-floor="tokyo"] .ui-spot[data-sign=led]'
        self.assertEqual(page.eval_on_selector(led, "e => [getComputedStyle(e).color, getComputedStyle(e).fontSize]"), ["rgb(255, 176, 0)", "0px"])
        page.eval_on_selector(led, "e => e.click()")
        self.assertEqual(page.eval_on_selector(led, "e => getComputedStyle(e).fontSize"), "11.2px")
        page.eval_on_selector(led, "e => e.click()")
        self.assertEqual(page.eval_on_selector(led, "e => getComputedStyle(e).fontSize"), "0px")    # two faces only: dot and text
        page.select_option(".ui-world-goto", "paris")
        page.wait_for_function("() => getComputedStyle(document.querySelector('.ui-floor[data-floor=\"paris\"]')).display !== 'none'")
        fires = page.eval_on_selector_all('.ui-floor[data-floor="paris"] .ui-prop[data-kind="fire"]', "els => els.map(e => getComputedStyle(e).backgroundImage)")
        self.assertGreaterEqual(len(fires), 20)
        self.assertTrue(all("data:image/svg+xml" in image for image in fires))
        self.assertEqual(self.errors, [])

    def test_real_floor_shows_a_chosen_photo_or_the_camera_only_in_the_page(self):
        """🖼️📷 on the real floor: ask() offers camera or photo; the picture sits behind the props, is released by 🧹 or by leaving (camera), and is never stored or sent."""
        from tool.image_support.png import rgb_png
        path = Path(self.tmp.name) / "overworld.html"
        path.write_text(web_ui.world_document(web_ui.example_data("overworld")), encoding="utf-8")
        photo = Path(self.tmp.name) / "room.png"
        photo.write_bytes(rgb_png(64, 48, (200, 80, 40)))
        browser = record_demo.launch(self.pw, extra=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        self.addCleanup(browser.close)
        context = browser.new_context(viewport={"width": 1280, "height": 800}, permissions=["camera"])
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.goto(path.as_uri())
        page.click('[data-emoji="🧙"]')
        page.wait_for_function("() => !document.querySelector('.ui-world').hasAttribute('data-pick')")
        real = '.ui-floor[data-floor="real"]'
        floor_shown = lambda name: page.wait_for_function(f"() => getComputedStyle(document.querySelector('.ui-floor[data-floor=\"{name}\"]')).display !== 'none'")
        hint = lambda: page.evaluate(f"() => getComputedStyle(document.querySelector('{real}'), '::after').content")
        self.menu(page, "more")
        self.assertFalse(page.is_visible("[data-real]"))                           # a land has no backdrop
        self.menu(page, "more")
        page.select_option(".ui-world-goto", "real")
        floor_shown("real")
        self.assertIn("🖼️📷", hint())                                              # until one is chosen, the floor says what it can show
        self.menu(page, "more")
        page.click("[data-real]")
        self.assertEqual(page.eval_on_selector_all(".ui-world-ask button", "els => els.map(e => [e.textContent, e.getAttribute('aria-label')])"),
                         [["📷", "カメラ"], ["🖼️", "写真をえらぶ"], ["✖️", "閉じる"]])           # nothing to clear yet
        self.assertEqual(page.get_attribute(".ui-world-ask [role=dialog]", "aria-label"), "写真かカメラをうしろに映す")
        page.keyboard.press("Escape")
        self.assertEqual(page.locator(".ui-world-ask").count(), 0)
        self.assertEqual(page.locator(f"{real} .ui-real").count(), 0)
        # a photo
        self.menu(page, "more")
        page.click("[data-real]")
        with page.expect_file_chooser() as chooser:
            page.click('.ui-world-ask button[data-t="photo"]')
        chooser.value.set_files(str(photo))
        page.wait_for_function(f"() => document.querySelector('{real} img.ui-real')?.complete")
        info = page.evaluate(f"() => {{ const i = document.querySelector('{real} img.ui-real'), f = document.querySelector('{real}'); "
                             "return [i.src.slice(0, 5), i.naturalWidth, i.offsetWidth, i.offsetHeight, getComputedStyle(i).pointerEvents, f.firstElementChild === i, f.hasAttribute('data-backdrop')]; }")
        self.assertEqual(info, ["blob:", 64, 384, 384, "none", True, True])      # behind the props, the size of the floor, taps pass through
        self.assertEqual(hint(), "none")
        self.assertTrue(page.is_visible(f"{real} .ui-player") and page.is_visible(f"{real} .ui-spot"))
        # 🧹 lets it go
        self.menu(page, "more")
        page.click("[data-real]")
        self.assertEqual(page.eval_on_selector_all(".ui-world-ask button", "els => els.map(e => e.textContent)"), ["📷", "🖼️", "🧹", "✖️"])
        page.click('.ui-world-ask button[data-t="clear"]')
        self.assertEqual(page.locator(f"{real} .ui-real").count(), 0)
        self.assertIn("🖼️📷", hint())
        # the camera: a stream on a <video>, stopped on leaving the floor
        self.menu(page, "more")
        page.click("[data-real]")
        page.click('.ui-world-ask button[data-t="camera"]')
        page.wait_for_function(f"() => {{ const v = document.querySelector('{real} video.ui-real'); return v && v.videoWidth > 0 && v.srcObject; }}")
        page.evaluate(f"() => {{ window.__stream = document.querySelector('{real} video.ui-real').srcObject; }}")
        self.assertTrue(page.evaluate("() => window.__stream.getTracks().every(t => t.readyState === 'live')"))
        page.select_option(".ui-world-goto", "meadow")
        floor_shown("meadow")
        self.assertEqual(page.locator("video").count(), 0)
        self.assertTrue(page.evaluate("() => window.__stream.getTracks().every(t => t.readyState === 'ended')"))
        # nothing is stored or sent: no request but the page itself, and the cache holds no picture
        self.assertTrue(all(u.startswith(("file:", "blob:", "data:")) for u in requests), requests)
        self.assertNotIn("blob:", page.evaluate("() => JSON.stringify({...localStorage})"))
        # the language of the words in the dialog follows 🌐; ask() is callable from the page that embeds the world
        self.menu(page, "settings")
        page.select_option("[data-lang]", "en")
        self.menu(page, "settings")
        page.evaluate("() => { document.querySelector('.ui-world').ask('❓', [{glyph: '✅', t: 'ok', value: 'yes'}], 'floor').then(v => { window.__answer = v; }); }")
        self.assertEqual(page.eval_on_selector_all(".ui-world-ask button", "els => els.map(e => e.getAttribute('aria-label'))"), ["Use this", "Close"])
        page.click('.ui-world-ask button[data-t="ok"]')
        page.wait_for_function("() => window.__answer === 'yes'")
        page.evaluate("() => { document.querySelector('.ui-world').ask('❓', []).then(v => { window.__answer = v; }); }")
        page.click(".ui-world-ask", position={"x": 4, "y": 4})                           # a tap outside the card cancels
        page.wait_for_function("() => window.__answer === null")
        self.assertEqual(errors, [])

    def test_camera_that_cannot_open_says_so_and_keeps_the_floor_plain(self):
        path = Path(self.tmp.name) / "overworld.html"
        path.write_text(web_ui.world_document(web_ui.example_data("overworld")), encoding="utf-8")
        page = self.open(path=path)
        self.start(page, "🧙")
        page.evaluate("() => { Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: () => Promise.reject(new DOMException('no', 'NotAllowedError'))}}); }")
        page.select_option(".ui-world-goto", "real")
        page.wait_for_function("() => getComputedStyle(document.querySelector('.ui-floor[data-floor=\"real\"]')).display !== 'none'")
        self.menu(page, "more")
        page.click("[data-real]")
        page.click('.ui-world-ask button[data-t="camera"]')
        page.wait_for_selector('.ui-world-ask [data-t="unavailable"]')
        self.assertIn("つかえません", page.get_attribute('.ui-world-ask [data-t="unavailable"]', "aria-label"))
        self.assertEqual(page.locator("video, img.ui-real").count(), 0)
        page.click('.ui-world-ask button[data-t="close"]')
        self.assertEqual(page.locator(".ui-world-ask").count(), 0)
        self.assertEqual(self.errors, [])

    def test_without_javascript_the_footer_keeps_plain_floor_labels(self):
        page = self.open(js=False)
        self.assertTrue(page.is_visible(".ui-world-foot .ui-world-bar"))
        self.assertFalse(page.is_visible(".ui-world-goto"))
        self.assertFalse(page.is_visible('.ui-world-menu[data-menu="more"]'))           # needs JS
        self.menu(page, "spots")
        self.assertTrue(page.is_visible('.ui-world-spots[data-floor="classroom"]'))
        page.click('label[for="school-floor-yard"]')
        self.assertTrue(page.is_visible('.ui-world-spots[data-floor="yard"]'))
        self.assertFalse(page.is_visible('.ui-world-spots[data-floor="classroom"]'))

    def test_open_floor_has_no_grid_pad_and_keeps_free_walking(self):
        page = self.open()
        self.start(page)
        page.select_option(".ui-world-goto", "yard")                        # the footer pulldown moves to the other floor
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


# --- The three cities: every spot, sign, tool, width and language, with an optional screenshot per check ---
CITIES = web_ui.world_validate(web_ui.example_data("cities"))
FAST = copy.deepcopy(CITIES)                     # the same floors, grid and routes; the player walks at the top speed so a sweep takes minutes
for _floor in FAST["floors"]:
    _floor["player"]["speed"] = 480
SIZES = {"phone": (390, 844, True), "desktop": (1280, 800, False)}
WIDTHS = {"phone-320": (320, 640, True), "phone": (390, 844, True), "phone-landscape": (844, 390, True),
          "tablet": (768, 1024, False), "desktop": (1280, 800, False), "wide": (1920, 1080, False)}
SHOTS = os.environ.get("WEB_UI_SHOTS")           # a folder: each check also keeps a screenshot, listed in manifest.json and index.html
CITY_FLOOR = '.ui-floor[data-floor="{}"]'
CITY_POS = "fl => { const s = document.querySelector(`.ui-floor[data-floor=\"${fl}\"] .ui-player`).style; return [parseFloat(s.getPropertyValue('--px')), parseFloat(s.getPropertyValue('--py'))]; }"
CITY_TARGET = "fl => { const p = document.querySelector(`.ui-floor[data-floor=\"${fl}\"] .ui-player`); return [+p.dataset.targetX, +p.dataset.targetY]; }"
CITY_WALK = ("fl => new Promise(done => { const p = document.querySelector(`.ui-floor[data-floor=\"${fl}\"] .ui-player`), seen = [], t0 = performance.now();"
             " const step = () => { const s = p.style, x = parseFloat(s.getPropertyValue('--px')), y = parseFloat(s.getPropertyValue('--py')); seen.push([x, y]);"
             " if ((Math.abs(x - +p.dataset.targetX) < .01 && Math.abs(y - +p.dataset.targetY) < .01) || performance.now() - t0 > 30000) done(seen);"
             " else requestAnimationFrame(step) }; requestAnimationFrame(step) })")      # every frame of the walk, until the player stands at its target
CITY_TOP = ("sel => { const a = document.querySelector(sel), r = a.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2,"
            " e = document.elementFromPoint(x, y); return {self: !!e && (e === a || a.contains(e)), sheet: !!e?.closest('.ui-sheet'),"
            " what: (e?.closest('.ui-spot,.ui-sheet-item,.ui-world-dpad,.ui-world-side,.ui-player')?.textContent || e?.className || '').trim().slice(0, 24), x, y} }")


def city_cell(point, tile):
    return int(point[0] // tile), int(point[1] // tile)


def write_city_gallery(out, records, meta):
    """manifest.json and a one-page index.html (no JavaScript, opens from file://) beside the shots/ written by the sweep."""
    ok = sum(1 for r in records if not r["notes"])
    (out / "manifest.json").write_text(json.dumps({"schema": "web-ui-cities-evidence/1", **meta, "shots": len(records), "clean": ok,
                                                   "noted": len(records) - ok, "records": records}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sections = {}
    for r in records:
        sections.setdefault((r["kind"], r["viewport"], r["floor"]), []).append(r)
    css = ("body{font-family:Meiryo,'Hiragino Sans','Noto Sans JP',sans-serif;margin:16px;background:#0c1018;color:#e6edf3}"
           "a{color:#8fd694}h2{margin:32px 0 8px;font-size:16px}nav a{margin-right:8px;white-space:nowrap}"
           ".g{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(var(--w),1fr))}.phone{--w:192px}.desktop,.wide,.tablet{--w:320px}"
           "figure{margin:0;padding:8px;border:1px solid #30363d;border-radius:8px}figure.n{border-color:#d29922}img{width:100%;height:auto;display:block}"
           "figcaption{font-size:12px;line-height:16px;margin-top:8px}.note{color:#d29922}")
    names = {"overview": "🗺️", "sheet": "📄", "map": "📍", "sign": "🪧", "tool": "🧰", "width": "📐", "lang": "🌐", "nojs": "🚫", "pick": "🙂", "favorite": "⭐", "fire": "🔥", "key": "⌨️", "category": "🏷️"}
    parts = [f"<!doctype html><html lang=ja><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>🗼🎡🥖 cities evidence</title><style>{css}</style><h1>🗼🎡🥖 cities evidence</h1>"
             f"<p>✅ {ok} · ⚠️ {len(records) - ok} · 📸 {len(records)} · {escape(meta['browser'])} · {escape(meta['date'])} · {escape(meta['commit'][:12])}</p><nav>"]
    keys = list(sections)
    parts += [f"<a href='#s{i}'>{names.get(k[0], k[0])} {escape(k[1])} {escape(k[2])} ({len(sections[k])})</a>" for i, k in enumerate(keys)]
    parts.append("</nav>")
    for i, key in enumerate(keys):
        kind, viewport, floor = key
        parts.append(f"<h2 id='s{i}'>{names.get(kind, kind)} {escape(kind)} · {escape(viewport)} · {escape(floor)}</h2><div class='g {escape(viewport.split('-')[0])}'>")
        for r in sections[key]:
            notes = "".join(f"<br><span class=note>{escape(n)}</span>" for n in r["notes"])
            parts.append(f"<figure class='{'n' if r['notes'] else ''}'><a href='shots/{escape(r['file'])}'><img src='shots/{escape(r['file'])}' loading=lazy "
                         f"alt='{escape(r['label'], quote=True)}'></a><figcaption>{'⚠️' if r['notes'] else '✅'} {escape(r['label'])}{notes}</figcaption></figure>")
        parts.append("</div>")
    (out / "index.html").write_text("".join(parts) + "\n", encoding="utf-8")


class CitiesTests(unittest.TestCase):
    """Parallel Tokyo, Reverse London and Fake Paris end to end: every spot from the ☰ list (walked to, never through water, the sheet tells its text,
    the arrows agree with Python's world_direction and the target with world_route_points), every sign's faces, the tools, keys, categories,
    favourites, widths, languages and the page without JavaScript. What works but looks wrong (a sheet over the destination, a label over a label)
    is kept as a note next to the screenshot instead of failing."""
    records = []

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.page_path, cls.fast_path = Path(cls.tmp.name) / "cities.html", Path(cls.tmp.name) / "fast.html"
        cls.page_path.write_text(web_ui.world_document(CITIES), encoding="utf-8")
        cls.fast_path.write_text(web_ui.world_document(FAST), encoding="utf-8")
        cls.pw = sync_playwright().start()
        cls.browser = record_demo.launch(cls.pw)
        cls.out = Path(SHOTS) if SHOTS else None
        if cls.out:
            (cls.out / "shots").mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        version = cls.browser.version
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()
        if cls.out and cls.records:
            from importlib.metadata import version as package_version
            commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or "unknown"
            write_city_gallery(cls.out, sorted(cls.records, key=lambda r: r["order"]), {
                "browser": f"Chromium {version} (Playwright {package_version('playwright')})", "commit": commit,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "player_speed": "480 (FAST) for the sweeps; 96 for keys, pad and reduced motion"})

    def open(self, size, path=None, js=True, reduced=False):
        width, height, touch = WIDTHS[size]
        context = self.browser.new_context(viewport={"width": width, "height": height}, has_touch=touch, is_mobile=touch, java_script_enabled=js,
                                           reduced_motion="reduce" if reduced else "no-preference")
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        page.goto((path or self.fast_path).as_uri())
        page.size, page.touch = size, touch
        return page

    def start(self, page, emoji="🧳"):
        page.click(f'[data-emoji="{emoji}"]')
        page.wait_for_function(record_demo.PICKED)
        page.wait_for_timeout(300)

    def show(self, page, floor):
        page.select_option(".ui-world-goto", floor)
        page.wait_for_function(f"() => getComputedStyle(document.querySelector('{CITY_FLOOR.format(floor)}')).display !== 'none'")
        page.wait_for_timeout(150)

    def menu(self, page, name):
        page.click(f'.ui-world-menu[data-menu="{name}"] > summary')

    def tap(self, page, x, y):
        """A finger (phone) or the mouse (desktop) on a point of the map."""
        if page.touch:
            page.touchscreen.tap(x, y)
        else:
            page.mouse.click(x, y)

    def press(self, page, selector):
        """A finger or the mouse on an element (Playwright's own tap/click: it scrolls the element into view and refuses one that is covered).
        Returns the notes: empty when the real press worked, one line when it was covered and a script click stood in."""
        target = page.locator(selector)
        try:
            (target.tap if page.touch else target.click)(timeout=3000)
            return []
        except PlaywrightTimeoutError:
            top = page.evaluate(CITY_TOP, selector)
            target.evaluate("e => e.click()")
            return [f"⚠️ 目印の上に「{top['what']}」が重なり押せない（スクリプトで代用）"]

    def shot(self, page, kind, floor, ident, label, notes=()):
        """One screenshot of the world (the page around it is cut off), kept only with WEB_UI_SHOTS."""
        if not self.out:
            return
        from PIL import Image
        import io
        box = page.eval_on_selector(".ui-world", "e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: Math.min(r.height, innerHeight - r.y)} }")
        png = page.screenshot(type="png", clip={k: round(v) for k, v in box.items()})
        name = f"{page.size}-{floor}-{kind}-{ident}".replace("/", "_") + ".webp"
        Image.open(io.BytesIO(png)).convert("RGB").save(self.out / "shots" / name, "WEBP", quality=80, method=6)
        type(self).records.append({"order": len(self.records), "file": name, "viewport": page.size, "floor": floor, "kind": kind, "id": ident,
                                   "label": label, "notes": list(notes)})

    def arrows(self, page, floor):
        return page.eval_on_selector_all(f'.ui-world-spots[data-floor="{floor}"] a', "els => els.map(a => [a.getAttribute('href'), a.querySelector('.ui-world-arrow').textContent])")

    def sweep(self, size):
        """Every spot of every city, one after another, from the ☰ list; then a real tap on its marker."""
        page = self.open(size)
        self.start(page)
        for f in CITIES["floors"]:
            fl, tile = f["id"], f["tile"]
            blocked = web_ui.world_blocked(f["width"], f["height"], tile, f["props"])
            self.show(page, fl)
            self.shot(page, "overview", fl, "fit", f["label"])
            for s in f["spots"]:
                with self.subTest(size=size, spot=s["id"]):
                    href, sheet = f"#cities-spot-{s['id']}", f"#cities-spot-{s['id']}"
                    marker = f'{CITY_FLOOR.format(fl)} .ui-spot[href="{href}"]'
                    here = page.evaluate(CITY_POS, fl)
                    self.menu(page, "spots")
                    want = [[f"#cities-spot-{t['id']}", web_ui.world_direction(here, [t["x"], t["y"]], tile)] for t in f["spots"]]
                    try:
                        page.wait_for_function("([fl, want]) => JSON.stringify([...document.querySelectorAll(`.ui-world-spots[data-floor=\"${fl}\"] a`)].map(a => "
                                               "[a.getAttribute('href'), a.querySelector('.ui-world-arrow').textContent])) === JSON.stringify(want)", arg=[fl, want], timeout=3000)
                    except Exception:
                        pass
                    self.assertEqual(self.arrows(page, fl), want)                                   # the ☰ arrows from where the player stands
                    goal = web_ui.world_route_points(blocked, tile, here, [s["x"], s["y"]])[-1]
                    page.click(f'.ui-world-spots[data-floor="{fl}"] a[href="{href}"]')
                    seen = page.evaluate(CITY_WALK, fl)
                    self.assertEqual([p for p in seen if blocked[city_cell(p, tile)[1]][city_cell(p, tile)[0]] == "1"], [], "walked into water")
                    target = page.evaluate(CITY_TARGET, fl)
                    self.assertAlmostEqual(target[0], goal[0], delta=.01)
                    self.assertAlmostEqual(target[1], goal[1], delta=.01)
                    end = page.evaluate(CITY_POS, fl)
                    self.assertLess(abs(end[0] - target[0]) + abs(end[1] - target[1]), .05)
                    self.assertEqual(page.evaluate("location.hash"), sheet)
                    self.assertTrue(page.is_visible(sheet))
                    self.assertEqual([page.text_content(f"{sheet} h3"), page.text_content(f"{sheet} p")], [s["label"], s["body"]])
                    self.assertEqual(page.input_value(".ui-world-goto"), fl)
                    self.assertGreaterEqual(float(page.evaluate("document.querySelector('.ui-world-cam').style.getPropertyValue('--z')")), 2 - 1e-9)
                    notes = []
                    if page.evaluate(CITY_TOP, marker)["sheet"]:
                        notes.append("⚠️ シートが行き先の目印を隠す")
                    if page.evaluate(CITY_TOP, f"{CITY_FLOOR.format(fl)} .ui-player")["sheet"]:
                        notes.append("⚠️ シートが🧳を隠す")
                    self.shot(page, "sheet", fl, s["id"], s["label"], notes)
                    page.click(".ui-sheet-close:visible")
                    notes = []
                    if not s.get("sign"):                                                           # signs are pressed by test_every_sign_shows_its_faces
                        notes = self.press(page, marker)
                        page.wait_for_selector(sheet, state="visible", timeout=3000)
                        page.click(".ui-sheet-close:visible")
                    self.shot(page, "map", fl, s["id"], s["label"], notes)
        self.assertEqual(self.errors, [])

    def test_every_spot_on_a_phone(self):
        self.sweep("phone")

    def test_every_spot_on_a_desktop(self):
        self.sweep("desktop")

    def test_every_sign_shows_its_faces(self):
        """A sign is a dot until touched; then its text; then its second face if it has one (nogard 🐉); then the dot again."""
        for size in SIZES:
            page = self.open(size)
            self.start(page)
            for f in CITIES["floors"]:
                self.show(page, f["id"])
                for s in (s for s in f["spots"] if s.get("sign")):
                    with self.subTest(size=size, sign=s["id"]):
                        marker = f'{CITY_FLOOR.format(f["id"])} .ui-spot[href="#cities-spot-{s["id"]}"]'
                        self.menu(page, "spots")
                        page.click(f'.ui-world-spots a[href="#cities-spot-{s["id"]}"]')                 # the list walks there without turning the board
                        page.evaluate(CITY_WALK, f["id"])
                        page.click(".ui-sheet-close:visible")
                        faces = ["", "label", "flip", ""] if s.get("flip") else ["", "label", ""]
                        for i, face in enumerate(faces):
                            notes = []
                            if i:
                                notes = self.press(page, marker)
                                page.wait_for_selector(f"#cities-spot-{s['id']}", state="visible", timeout=3000)
                                page.click(".ui-sheet-close:visible")
                            state = page.eval_on_selector(marker, "e => { const c = getComputedStyle(e); return [e.textContent, e.dataset.show || '', c.fontSize, c.color,"
                                                          " c.backgroundColor, getComputedStyle(e, '::before').content] }")
                            self.assertEqual(state[:2], [s["flip"] if face == "flip" else s["label"], face])
                            self.assertEqual(state[2] == "0px", face == "")                              # the dot hides the text
                            self.assertIn("●", state[5])
                            self.assertEqual(state[4], {"led": "rgb(17, 17, 17)", "wood": "rgb(139, 90, 43)"}[s["sign"]])
                            if s["sign"] == "led":
                                self.assertEqual(state[3], "rgb(255, 176, 0)")
                            self.shot(page, "sign", f["id"], f"{s['id']}-{i}-{face or 'dot'}", f"{s['label']} · {face or 'dot'}", notes)
            self.assertEqual(self.errors, [])

    def test_city_tools_and_tokyo_station(self):
        """🗼🎡🥖 open their city; 🚉 lists Tokyo Station's six exits (🚪 from another city), walks to each, and its arrows agree with Python."""
        tool = CITIES["tools"]["🚉"]
        tokyo = next(f for f in CITIES["floors"] if f["id"] == "tokyo")
        exits = [next(s for s in tokyo["spots"] if s["id"] == i) for i in tool["spots"]]
        panel = '.ui-world-head .ui-world-menu[data-menu="tool"] .ui-world-rows'        # 🚉 is the only tool menu of the cities (🗼🎡🥖 are floor labels)
        rows = panel + ' a'
        for size in SIZES:
            page = self.open(size)
            self.start(page)
            for emoji, fl in (("🎡", "london"), ("🥖", "paris"), ("🗼", "tokyo")):
                page.click(f'.ui-world-tools label[for="cities-floor-{fl}"]')
                page.wait_for_function(f"() => getComputedStyle(document.querySelector('{CITY_FLOOR.format(fl)}')).display !== 'none'")
                page.wait_for_function(f"() => document.querySelector('.ui-world-goto').value === '{fl}'")      # the pulldown follows within a frame
                self.assertEqual(page.text_content(f'.ui-world-tools label[for="cities-floor-{fl}"]'), emoji)
                page.wait_for_timeout(150)
                self.shot(page, "tool", fl, emoji, f"{emoji} {next(f['label'] for f in CITIES['floors'] if f['id'] == fl)}")
            self.show(page, "london")
            page.click('.ui-world-head .ui-world-menu[data-menu="tool"] > summary')
            self.assertEqual(page.eval_on_selector_all(rows, "els => els.map(a => a.querySelector('.ui-world-arrow').textContent)"), ["🚪"] * 6)
            self.shot(page, "tool", "london", "station-door", "🚉 from London: 🚪 ×6")
            page.keyboard.press("Escape")
            for s in exits:
                with self.subTest(size=size, exit=s["id"]):
                    page.click('.ui-world-head .ui-world-menu[data-menu="tool"] > summary')
                    page.click(f'{panel} a[href="#cities-spot-{s["id"]}"]')
                    page.evaluate(CITY_WALK, "tokyo")
                    self.assertEqual(page.input_value(".ui-world-goto"), "tokyo")
                    self.assertEqual(page.text_content(f"#cities-spot-{s['id']} h3"), s["label"])
                    here = page.evaluate(CITY_POS, "tokyo")
                    self.assertLess(abs(here[0] - s["x"]) + abs(here[1] - s["y"]), .05)          # Tokyo has no water: every exit is reached exactly
                    page.click(".ui-sheet-close:visible")
                    page.click('.ui-world-head .ui-world-menu[data-menu="tool"] > summary')
                    want = [web_ui.world_direction(here, [e["x"], e["y"]], tokyo["tile"]) for e in exits]
                    page.wait_for_function("([sel, want]) => JSON.stringify([...document.querySelectorAll(sel)].map(a => a.querySelector('.ui-world-arrow').textContent)) === JSON.stringify(want)",
                                           arg=[rows, want], timeout=3000)
                    self.shot(page, "tool", "tokyo", f"station-{s['id']}", f"🚉 at {s['label']}")
                    page.keyboard.press("Escape")
            self.assertEqual(self.errors, [])

    def test_keys_pad_and_water_at_the_real_speed(self):
        """Arrow keys (desktop) and the pad (phone) step one tile; a step into the Thames or the Seine is refused. Normal speed, no FAST."""
        for size in SIZES:
            page = self.open(size, path=self.page_path)
            self.start(page)
            for f in CITIES["floors"]:
                fl, tile = f["id"], f["tile"]
                blocked = web_ui.world_blocked(f["width"], f["height"], tile, f["props"])
                self.show(page, fl)
                steps = [((0, -1), "ArrowUp"), ((1, 0), "ArrowRight"), ((0, 1), "ArrowDown"), ((-1, 0), "ArrowLeft")]
                for (dx, dy), key in steps:
                    with self.subTest(size=size, floor=fl, key=key):
                        cx, cy = city_cell(page.evaluate(CITY_POS, fl), tile)
                        n = (cx + dx, cy + dy)
                        free = 0 <= n[0] < len(blocked[0]) and 0 <= n[1] < len(blocked) and blocked[n[1]][n[0]] == "0"
                        if page.touch:
                            page.dispatch_event(f'[data-step="{dx},{dy}"]', "pointerdown")
                            page.dispatch_event(f'[data-step="{dx},{dy}"]', "pointerup")
                        else:
                            page.keyboard.press(key)
                        page.wait_for_timeout(100)
                        page.evaluate(CITY_WALK, fl)
                        self.assertEqual(city_cell(page.evaluate(CITY_POS, fl), tile), n if free else (cx, cy))
                water = [c for c in web_ui.world_reach(blocked, city_cell([f["player"]["x"], f["player"]["y"]], tile))
                         if c[1] + 1 < len(blocked) and blocked[c[1] + 1][c[0]] == "1"]                  # a free tile with water just below it
                if not water:
                    continue                                                                         # Tokyo has no water
                with self.subTest(size=size, floor=fl, shore=water[0]):
                    shore = water[len(water) // 2]
                    box = page.evaluate(f"() => {{ const r = document.querySelector('{CITY_FLOOR.format(fl)}').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }}")
                    self.tap(page, box[0] + (shore[0] + .5) * tile * box[2] / f["width"], box[1] + (shore[1] + .5) * tile * box[3] / f["height"])
                    page.wait_for_timeout(100)
                    seen = page.evaluate(CITY_WALK, fl)
                    self.assertEqual([p for p in seen if blocked[city_cell(p, tile)[1]][city_cell(p, tile)[0]] == "1"], [])
                    at = city_cell(page.evaluate(CITY_POS, fl), tile)
                    if blocked[at[1] + 1][at[0]] == "1":                                             # the tap landed on that shore: step into the river
                        if page.touch:
                            page.dispatch_event('[data-step="0,1"]', "pointerdown")
                            page.dispatch_event('[data-step="0,1"]', "pointerup")
                        else:
                            page.keyboard.press("ArrowDown")
                        page.wait_for_timeout(400)
                        self.assertEqual(city_cell(page.evaluate(CITY_POS, fl), tile), at)
                    self.shot(page, "key", fl, "shore", f"{f['label']}: 🌊 refused at {at}")
            self.assertEqual(self.errors, [])

    def test_categories_filter_the_list_and_the_map(self):
        for size in SIZES:
            page = self.open(size)
            self.start(page)
            for f in CITIES["floors"]:
                fl = f["id"]
                self.show(page, fl)
                for cat in ["", *sorted({s["category"] for s in f["spots"]})]:
                    with self.subTest(size=size, floor=fl, category=cat or "all"):
                        self.menu(page, "spots")
                        page.click(f'.ui-world-menu[data-menu="spots"] label[data-cat="{cat}"]')
                        want = sorted(s["id"] for s in f["spots"] if cat in ("", s["category"]))
                        rows = page.eval_on_selector_all(f'.ui-world-spots[data-floor="{fl}"] li', "els => els.filter(e => e.offsetParent).map(e => e.querySelector('a').getAttribute('href'))")
                        marks = page.eval_on_selector_all(f"{CITY_FLOOR.format(fl)} .ui-spot", "els => els.filter(e => getComputedStyle(e).display !== 'none').map(e => e.getAttribute('href'))")
                        self.assertEqual(sorted(h.split("-spot-")[1] for h in rows), want)
                        self.assertEqual(sorted(h.split("-spot-")[1] for h in marks), want)
                        self.shot(page, "category", fl, cat or "all", f"🏷️ {cat or 'all'} ({len(want)})")
                        page.keyboard.press("Escape")
                self.menu(page, "spots")
                page.click('.ui-world-menu[data-menu="spots"] label[data-cat=""]')
                page.keyboard.press("Escape")
            self.assertEqual(self.errors, [])

    def test_favorites_across_the_cities_and_home(self):
        page = self.open("phone")
        self.start(page)
        first = {f["id"]: f["spots"][0] for f in CITIES["floors"]}
        for fl, s in first.items():
            self.show(page, fl)
            self.menu(page, "spots")
            page.click(f'.ui-world-spots[data-floor="{fl}"] li:has(a[href="#cities-spot-{s["id"]}"]) .ui-world-star')
            page.keyboard.press("Escape")
        self.menu(page, "favorites")
        self.assertEqual(page.eval_on_selector_all(".ui-world-favs a", "els => els.map(e => e.lastChild.textContent)"), [s["label"] for s in first.values()])
        self.shot(page, "favorite", "paris", "panel", "⭐ ×3")
        page.click(f'.ui-world-favs a[href="#cities-spot-{first["london"]["id"]}"]')       # from Paris to London in one tap
        self.assertEqual(page.input_value(".ui-world-goto"), "london")
        self.assertTrue(page.is_visible(f"#cities-spot-{first['london']['id']}"))
        page.click(".ui-world-home")
        page.click('.ui-world-ask button[data-t="home"]')
        self.assertEqual(page.input_value(".ui-world-goto"), "tokyo")
        self.shot(page, "favorite", "tokyo", "home", "🏠 → Parallel Tokyo")
        self.assertEqual(self.errors, [])

    def test_every_width_fits_each_city(self):
        for size, (width, height, touch) in WIDTHS.items():
            page = self.open(size)
            self.start(page)
            for f in CITIES["floors"]:
                with self.subTest(size=size, floor=f["id"]):
                    self.show(page, f["id"])
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - innerWidth"), 0)
                    self.assertTrue(page.is_visible(f"{CITY_FLOOR.format(f['id'])} .ui-player"))
                    self.assertTrue(page.is_visible(".ui-world-dpad"))                                # every city is a grid
                    notes = []
                    tall = page.evaluate("document.documentElement.scrollHeight - innerHeight")
                    if tall > 0:
                        notes.append(f"⚠️ 縦に {tall}px はみ出す")
                    cut = page.evaluate("() => [...document.querySelectorAll('.ui-world-head .ui-board > strong, .ui-world-head .ui-board-clock')].filter(e => e.scrollWidth > e.clientWidth + 1 || e.getBoundingClientRect().right > e.closest('.ui-board').getBoundingClientRect().right + 1).map(e => e.textContent)")
                    if cut:
                        notes.append("⚠️ ヘッダーで切れる: " + " / ".join(cut))
                    out = page.evaluate("() => [...document.querySelectorAll('.ui-world-head .ui-world-tools > *, .ui-world-side summary, .ui-world-goto')].filter(e => { const r = e.getBoundingClientRect(); return r.width && (r.left < 0 || r.right > innerWidth + .5) }).map(e => e.textContent.trim().slice(0, 4))")
                    self.assertEqual(out, [], "a control sticks out of the window")
                    self.shot(page, "width", f["id"], f"{width}x{height}", f"{f['label']} {width}×{height}", notes)
            self.assertEqual(self.errors, [])

    def test_every_language_labels_the_city_tools(self):
        page = self.open("phone")
        self.start(page)
        codes = [code for code, _ in web_ui.WORLD_LANGS]
        for code in codes:
            with self.subTest(lang=code):
                self.menu(page, "settings")
                page.select_option(".ui-world-head [data-lang]", code)
                self.assertEqual(page.evaluate("document.querySelector('.ui-world').lang"), code)
                labels = page.eval_on_selector_all(".ui-world-head .ui-world-home, .ui-world-tools label, .ui-world-head summary", "els => els.map(e => e.getAttribute('aria-label'))")
                self.assertTrue(all(labels), labels)
                if code == "en":
                    self.assertEqual(labels[1:4], ["Parallel Tokyo", "Reverse London", "Fake Paris"])
                if code != "ja":
                    self.assertNotEqual(labels[0], "ホーム")
                self.shot(page, "lang", "tokyo", code, f"🌐 {code}: {' · '.join(labels[:4])}")
                page.keyboard.press("Escape")
        self.assertEqual(self.errors, [])

    def test_without_javascript_each_city_is_a_static_map(self):
        for size in SIZES:
            page = self.open(size, js=False)
            for f in CITIES["floors"]:
                with self.subTest(size=size, floor=f["id"]):
                    page.click(f'.ui-world-foot label[for="cities-floor-{f["id"]}"]')
                    self.assertTrue(page.is_visible(CITY_FLOOR.format(f["id"])))
                    self.assertEqual(page.eval_on_selector_all(f"{CITY_FLOOR.format(f['id'])} .ui-spot", "els => els.length"), len(f["spots"]))
                    self.assertFalse(page.is_visible(".ui-world-pick"))
                    s = f["spots"][0]
                    page.evaluate(f"location.hash = '#cities-spot-{s['id']}'")                     # a spot link without JS: the sheet is a :target
                    self.assertTrue(page.is_visible(f"#cities-spot-{s['id']}"))
                    self.shot(page, "nojs", f["id"], "static", f"🚫JS {f['label']} · {s['label']}")

    def test_the_picker_offers_every_avatar(self):
        page = self.open("phone")
        self.shot(page, "pick", "tokyo", "picker", "🙂 picker")
        self.start(page, CITIES["avatars"][0])
        for emoji in CITIES["avatars"][1:]:
            with self.subTest(avatar=emoji):
                self.menu(page, "settings")
                page.click("[data-pick-open]")
                page.click(f'[data-emoji="{emoji}"]')
                page.wait_for_function(record_demo.PICKED)
                self.assertEqual(page.eval_on_selector_all(".ui-player span", "els => [...new Set(els.map(e => e.textContent))]"), [emoji])
        self.shot(page, "pick", "tokyo", "last", f"🙂 → {CITIES['avatars'][-1]}")
        self.assertEqual(self.errors, [])

    def test_reduced_motion_jumps_to_the_spot(self):
        page = self.open("desktop", path=self.page_path, reduced=True)
        self.start(page)
        for f in CITIES["floors"]:
            with self.subTest(floor=f["id"]):
                self.show(page, f["id"])
                s = max(f["spots"], key=lambda s: abs(s["x"] - f["player"]["x"]) + abs(s["y"] - f["player"]["y"]))   # the farthest spot
                self.menu(page, "spots")
                page.click(f'.ui-world-spots a[href="#cities-spot-{s["id"]}"]')
                page.wait_for_timeout(100)
                self.assertTrue(page.evaluate(record_demo.SETTLED))                                  # no walk to wait for
                self.shot(page, "map", f["id"], f"reduced-{s['id']}", f"🐢→⚡ reduced motion: {s['label']}")
                page.click(".ui-sheet-close:visible")
        self.assertEqual(self.errors, [])

    def test_fires_rivers_and_bridges_are_drawn(self):
        page = self.open("desktop")
        self.start(page)
        for f in CITIES["floors"]:
            self.show(page, f["id"])
            blocked = web_ui.world_blocked(f["width"], f["height"], f["tile"], f["props"])
            for kind in ("fire", "water", "bridge"):
                props = [p for p in f["props"] if p["kind"] == kind]
                with self.subTest(floor=f["id"], kind=kind):
                    images = page.eval_on_selector_all(f'{CITY_FLOOR.format(f["id"])} .ui-prop[data-kind="{kind}"]', "els => els.map(e => getComputedStyle(e).backgroundImage)")
                    self.assertEqual(len(images), len(props))
                    if kind != "bridge":
                        self.assertTrue(all("data:image/svg+xml" in i for i in images))
                    if kind == "fire":                                                                # a decoration: it stands on a free tile
                        self.assertEqual([p for p in props if blocked[p["y"] // f["tile"]][p["x"] // f["tile"]] == "1"], [])
            if f["id"] != "tokyo":
                self.shot(page, "fire", f["id"], "fit", f"{f['label']}: 🔥{sum(p['kind'] == 'fire' for p in f['props'])} 🌊{sum(p['kind'] == 'water' for p in f['props'])} 🌉{sum(p['kind'] == 'bridge' for p in f['props'])}")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
