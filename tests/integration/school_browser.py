"""Required Chromium contract for the school world: python tests/integration/school_browser.py -v.

The emoji picker comes first, then the player walks by tap, arrow keys / WASD and the on-screen pad.
Solid props (desks, board, shelves) are never entered, whichever way the player moves.
Invoked explicitly by the browser CI job; missing Playwright/browser is an error. WEB_UI_CHROME may name a local Chrome.
"""
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
        """Reverse London's nogard sign swaps with 🐉 when pressed (and back); Fake Paris draws its scattered fires as tile emoji."""
        path = Path(self.tmp.name) / "cities.html"
        path.write_text(web_ui.world_document(web_ui.example_data("cities")), encoding="utf-8")
        page = self.open(path=path)
        self.start(page, "🧳")
        self.assertEqual(page.eval_on_selector_all(".ui-world-goto option", "els => els.map(e => e.value)"), ["tokyo", "london", "paris"])
        page.select_option(".ui-world-goto", "london")
        sign = '.ui-floor[data-floor="london"] .ui-spot[data-category="mark"]'
        self.assertEqual(page.inner_text(sign), "nogard")
        page.eval_on_selector(sign, "e => e.click()")
        self.assertEqual(page.inner_text(sign), "🐉")
        page.eval_on_selector(sign, "e => e.click()")
        self.assertEqual(page.inner_text(sign), "nogard")                                          # pressed again, it turns back
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


if __name__ == "__main__":
    unittest.main()
