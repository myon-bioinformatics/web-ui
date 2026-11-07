# School world: desks, chairs, an emoji and a walk

An extension of the existing `web-ui-world/1` map, not a new engine. A floor may carry a **tile grid**
and **props**; the world may offer **avatars**. Everything stays in `web_ui.py` (stdlib only, no server,
no storage, no new dependency). Worlds without these fields produce exactly the same HTML as before.

```python
import web_ui
spec = web_ui.example_data("school")        # a classroom floor plus an open schoolyard
open("school.html", "w").write(web_ui.world_document(spec))
```

## Data (all optional, additive)

| Field | Where | Meaning |
| --- | --- | --- |
| `tile` | floor | Tile size in map units: 16..128, a multiple of 8, dividing `width` and `height` |
| `props` | floor | Up to 512 `{kind, x, y, w, h}` rectangles, all on tiles and inside the floor |
| `kind` | prop | `desk`, `board`, `wall`, `shelf` are **solid**; `chair`, `rug` can be walked over (sit on a chair) |
| `avatars` | world | Up to 24 different labels offered first (emoji, short text such as `先生` or `A`, or both; 1..16 characters); the choice replaces every floor's player label |

| `classroom` | floor | `{rows, groups, per_group, tile}` (all optional) in place of `width`/`height`/`tile`/`props`: the floor is `classroom_floor(...)`. `id`, `label` and `spots`/`actors`/`player` may sit beside it and replace the generated ones |

A floor's `player` must start on a free tile. `classroom_floor(rows, groups, per_group=2, tile=32)` writes a whole classroom
floor (rows of desks, one chair under each, aisles, blackboard, teacher's desk, back shelves with a door gap) with every size a
multiple of the tile. A floor without `tile` keeps the old free walking.

## From another repository (one line)

A consuming repository keeps only JSON; Python (stdlib) makes the page, and Node reaches the same Python through `vendor/py_launch.cjs`.
`--world -` reads the spec from stdin (at most 2 MB), so no temporary file is needed:

```
echo '{"schema":"web-ui-world/1","avatars":["🙂","🐱","🦊"],"floors":[{"id":"room","label":"教室","classroom":{"rows":5,"groups":3}}]}' \
  | python -S web_ui.py --world - > school.html
python -S web_ui.py --example school | python -S web_ui.py --world - > school.html          # the bundled example, as is
node vendor/py_launch.cjs -- web_ui.py --world - < school.json > school.html                # Node: same bytes
python -S -c "import web_ui as u,sys;sys.stdout.write(u.world_document({'schema':u.WORLD_SCHEMA,'avatars':['🙂'],'floors':[{'classroom':{}}]}))"   # in-process
```

A bad spec exits with status 2 and one `error:` line on stderr (no traceback, nothing on stdout). Add `--theme NAME` for another theme.
Python, the CLI and `py_launch.cjs` return identical bytes; `tests/test_world_classroom.py` checks that.

## Who does what

* **Python** (`world_blocked`, `world_path`, `world_route_points`, `world_route`, `world_route_sample`) is the oracle: the
  walking grid, the shortest 4-neighbour path (breadth first, fixed neighbour order), and the chain of constant-speed segments.
* **The page** receives the grid as `data-blocked` (rows of `0`/`1`) and plays the same plan: `gridPath`, `gridRoute`,
  `motionRoute`, `routeSample`. Node tests compare them with Python on random cases.
* A goal that is solid, outside or cut off ends at the nearest reachable tile, so tapping a desk walks beside it.
  A tap on a reachable tile ends exactly where you tapped; keys and the pad move tile centre to tile centre.
* A route never leaves free tiles: between tile centres it stays inside two touching free tiles.

## Where things go (header, side, footer)

A grid world (or any world with `"shell": true`, or with `tools`) keeps the page short: nothing is stacked under the map, so a phone and a PC need no
vertical scrolling and nothing changes page. The screen is icons; the words are each button's `aria-label` and tooltip, in 11 languages (below).

* **Header** (the whole world): the info board, then 🏠 / ⭐ / ⚙️ and the emoji tools you add.
  * **🏠** home: first floor, everything in view, sheet and menus closed.
  * **⭐** favourites: a ☆ in the ☰ list stars a place; the ⭐ panel lists them (on any floor) and takes you there. They are a light cache: kept in this browser
    (`localStorage` key `ui-world:<id>`, only the starred places and the language) and restored on the next visit. No dialog, no per-floor favourites, no export.
  * **⚙️** settings: ⏸️ pause the motion, 🙂✏️ change the emoji, 🌐 pick the language (a `<select>` of native names).
* **Side** (this screen): 48px buttons that open a panel over the map (one menu open at a time; Escape, a tap on the map or choosing an item closes it).
  * **☰**: the places of this floor (and the category chips, if any). Each row has an arrow from you to the place (⬆️ ↗️ ➡️ ↘️ ⬇️ ↙️ ⬅️ ↖️, 📍 within one tile,
    🚪 when it is on another floor) that follows you as you walk; tap a row to go there and read its sheet. Works without JavaScript too (the rows are links).
  * **⋯**: 🚶 walk to X / Y and 🎯 find myself. Shown by the script.
* **Footer**: 🚪 the pulldown that moves between floors, each as it is, no door-to-door wiring needed. Without JavaScript the plain floor labels stand in for it.

Worlds without a tile grid keep the original layout and markup (floor chips on top, controls below) unless they ask for the shell.
A catalogue can too: `catalogue_world(items, shell=True)` turns a long list into floors you reach with the pulldown, with no scrolling.

### Your own icons: `tools` (an emoji is the key, the feature is the value)

```json
"tools": {
  "🗺️": {"label": "見どころ", "label_en": "Highlights", "spots": ["classroom-board", "flowers"]},
  "🏫": {"label": "学校", "body": "教室と校庭があります。"},
  "🛝": {"label": "校庭", "floor": "yard", "slot": "side"}
}
```

Each entry adds one icon with exactly one feature: `spots` (a panel listing those places, with arrows), `body` (a panel with a note) or `floor` (a shortcut
to that floor). `slot` is `head` (default) or `side`; `label` (ja) / `label_en` (en) / `labels` (`{"fr": "Carte", "de": "Karte"}`, any of the other nine codes) are the tooltip words. Up to 8; the page's own icons (🏠 ⭐ ⚙️ 🌐 ☰ ⋯ 🚪) are taken.
Adding an icon is adding a key: nothing else in the page changes, and the key is the emoji itself.

How flutter_navigation_basic's header maps here (so it can be archived): Home → 🏠; Favorite this page / Favorites → ☆ and ⭐ (session only); Menu → ☰ ⚙️;
Language → 🌐 (labels switch, the content stays yours); Door-to-Door selector → 🚪 in the footer; the page's own action row → the emoji `tools`. Not taken over:
the "leave this page?" confirmation (a world has no unsaved page to lose; 🏠 has its own small ask() dialog) and favouriting a whole floor.

### Languages (🌐)

The chrome speaks the 11 languages of flutter_navigation_basic: ja, en, fr, es, pt, ar, zh, ru, id, de, sw (`web_ui.WORLD_LANGS`, words in `WORLD_TEXT`, one tuple
per word in that order; a test checks every word in every language). Markup carries Japanese plus `data-t="<word>"`; 🌐 swaps `aria-label` and `title`, sets `lang`
on the world and remembers the choice. A tool of your own names itself with `label`, `label_en` and `labels`; a missing language falls back to English, then Japanese.
The content (spot labels, bodies, the board) is yours and is not translated. Arabic changes the words only: the map is not mirrored.

## Lands: other spaces from the same grid

A land is a floor made of terrain instead of furniture, so a world can be a Dragon Quest-style map of several lands (`EXAMPLES["overworld"]`,
six lands, a few lines of JSON) and the footer's 🚪 pulldown moves between them. Nothing links one land to another.

```json
{"schema": "web-ui-world/1", "id": "trip", "floors": [
  {"id": "north", "label": "北", "land": {"theme": "castle"}},
  {"id": "sea", "land": {"theme": "coast", "cols": 24, "rows": 16, "seed": 5, "tile": 32}}]}
```

* `theme`: `meadow 🌱`, `forest 🌲`, `mountain ⛰️`, `desert 🏜️`, `coast 🌊`, `castle 🏰` (`LAND_THEMES`: each swaps the ground, the edge, the scattered
  object, the pond, how many houses). The same arguments always give the same land; `seed` makes another. `cols` 12..48, `rows` 12..32, `tile` a multiple of 8.
* Each land has a road from the player's start to a village crossroads, and two spots (the town; a landmark on the nearest bank of the water, else the
  farthest tile) on tiles that can be walked to. `spots`, `actors` and `player` beside `land` replace the generated ones, like `classroom`.
* From Python: `web_ui.land_floor(theme, cols, rows, seed=, tile=, id=, label=)`; from another repository: `... | python -S web_ui.py --world - > lands.html`.

The representation changes by swapping objects, not code: the prop kinds of any floor can be mixed.

| Kind | Walk | Looks like |
|---|---|---|
| `grass` `sand` `road` `bridge` (ground) | yes, and they **open** the tiles under them (a road through trees, a bridge over water) | a colour |
| `water` `tree` `cactus` `mountain` `house` `castle` | blocked | 🌊 🌲 🌵 ⛰️ 🏠 🏰, one per tile (the castle once across its prop) |
| `fire` | free (decoration) | 🔥, one per tile |
| `desk` `board` `wall` `shelf` / `chair` `rug` | blocked / free, as before | the classroom's theme-coloured shapes |

`WORLD_PROPS` (blocks walking), `WORLD_GROUND` (opens) and `WORLD_LOOK` (colour, emoji, once) are the whole table; the CSS is written only for the kinds a
world uses. A new kind is one line in each.

## Places: real space in miniature

A `place` floor lays **real positions** (latitude and longitude) on the same grid, so a world can go on from a village to a real city in its other
form (`EXAMPLES["cities"]`): **Parallel Tokyo**, Tokyo Station with its six exits and the stations around it; **Reverse London**, the main termini, the stations
beside them, sights and famous places, the Thames and a wooden `nogard` sign (dragon, backwards) that turns into 🐉 when pressed; **Fake Paris**, the main stations,
the metro beside them and the Seine, with a 🔥 in each block. Nothing is drawn to look like the place: ground, roads, water and bridges are the same kinds as a land.

```json
{"schema": "web-ui-world/1", "id": "trip", "floors": [{"id": "tokyo", "label": "TOKYO", "place": {"meters": 32, "points": [
  {"id": "marunouchi-c", "label": "丸の内中央口", "lat": 35.68134, "lon": 139.7665, "category": "exit", "body": "…"},
  {"id": "yurakucho", "label": "有楽町", "maps": "https://www.google.com/maps/@35.6751,139.763,17z", "category": "station"}],
  "links": [["marunouchi-c", "yurakucho"]]}}]}
```

* `points`: 1..64, each with `id`, `label`, `category` and `body` (as a spot has) and **either** `lat` and `lon` **or** `maps`, a Google or Apple Maps URL read
  by the page's own coordinate tool (`try_parse_maps_url`). `flip` (a short text or emoji) is a second face: pressing the pill swaps it with the label, and again
  swaps back (a spot of any floor can have one; without script it stays a plain label).
* `sign`: `"led"` (amber on black, monospace: an electronic board) or `"wood"` (a wooden board). It is **a bold dot (●) until it is touched**, then the board shows its
  text; touched again it shows its `flip` face if it has one (nogard → 🐉), and then the dot again. On a spot of any floor it is only
  the look; on a place point it also puts the spot on the **nearest tile corner** (the four corners of a square are points of the grid too), so a sign takes no
  tile, sits between the stations, two signs never share a corner, and it must touch a tile that can be walked on (the player walks to the tile beside it).
  Signs make small notices: a direction board between the exits, a wooden sign with a `flip` (nogard ⇄ 🐉). A place needs at least one point that is not a sign
  (the player starts on it). A point is a spot on the tile its position falls on; `meters` (8..2000, default 64) is the ground
  one tile covers, and the north is up. The player starts at `start` (a point id, default the first point).
* The map is the points' box plus two tiles all round, or `area: {"center": [lat, lon], "radius": metres}`: the box `tolerance_area` gives (a point outside it
  is an error). The scale and the radius are the ones of the coordinates tool (`EARTH_RADIUS_M`, `parse_coordinate`); the projection is flat, good for a few kilometres.
* `links`: pairs of point ids joined by an L-shaped road. `rivers`: `{"line": [[lat, lon], ...], "width": tiles}` bands of water; **a road that crosses one is a
  bridge**, and a point that water cuts off from the start is an error naming it (add a link), so every spot can be walked to.
* `scatter`: `{"kind": "fire", "every": 8, "seed": 5}` cuts the map into blocks of `every` tiles and puts one `fire` (a decoration you walk over: `WORLD_PROPS`
  false, `WORLD_LOOK` 🔥) on a free tile of each, never on a road, the river or a spot; the same arguments give the same fires.
* Two points on one tile: the earlier keeps it and the other goes to the nearest free tile (never into water). Roads and water are merged into rectangles, so a
  place stays far below the 512-prop limit.
* The coordinates in `EXAMPLES["cities"]` are approximate (about 100 m, read off public maps): a miniature shows where things stand relative to each other, not exact positions.
  There are no facility names in TOKYO, only stations and exits, and no religious buildings in any of the three cities (`tests/test_world_places.py` keeps it so).
* Evidence: `tests/integration/school_browser.py` (`CitiesTests`) walks to every spot of the three cities on a phone and a desktop, touches every sign, and checks the
  tools, keys, categories, favourites, six widths, eleven languages and the page without JavaScript. With `WEB_UI_SHOTS=DIR` it also keeps a WebP of each check with
  a `manifest.json` and an `index.html`; the reviewed set lives under `docs/evidence/cities-<date>/`. The three `cities-*.gif` demos are the same operations in motion.
* From Python: `web_ui.place_floor(points, meters=, tile=, links=, rivers=, area=, start=, id=, label=)`; from another repository: `--world -` with `place` as above.
  At the page's first view the whole floor is shown, so crowded places overlap their names until you zoom (wheel, pinch, or ⭐ and ☰ to go to one).

## Real × virtual (🖼️📷)

`"real": true` on a floor (also beside a `land` or `classroom`) lets the visitor put **a photo they choose or their camera** behind that floor's props, spots and
player. It is shown in the page and nothing else: a photo is an object URL on an `<img>`, the camera a stream on a `<video>`; neither is drawn, read back,
recorded, stored (not even in the ⭐/🌐 cache) or sent, and the guard test in `tests/test_python_wrapper.py` pins that. The camera is released by 🧹, by
leaving the floor, or by closing the page; a refused or missing camera says ⚠️ and the floor stays plain.

* On a real floor the ⋯ menu has one button, 🖼️📷. It opens the shared dialog (below) with 📷 camera, 🖼️ photo, 🧹 clear (only once something is shown) and ✖️.
* Props are drawn over the picture, so a props-free floor (`EXAMPLES["overworld"]` ends with one) shows the picture whole, and a floor with a few solid props
  (a house, a tree) puts them on top of the room. The walk grid is the same grid either way.
* Words: `backdrop`, `camera`, `photo`, `clear`, `unavailable` in the same 11 languages as the rest of the chrome.

### `ask()`: the one dialog for choosing or confirming

`el.ask(glyph, choices, t?)` (`el` is the world element `bindWorlds()` returns) shows icons and resolves with the chosen value, or `null` for ✖️, Esc or a tap outside:

```js
const answer = await world.ask('🖼️📷', [{glyph: '📷', t: 'camera', value: 'camera'}, {glyph: '🖼️', t: 'photo', value: 'photo'}], 'backdrop');
```

A choice is `{glyph, t, value}`; `t` names a catalogue word (so the label is the aria-label and tooltip in the visitor's language) and the optional third
argument labels the dialog. The look is the emoji picker's (one CSS rule set), keys do not walk the player while it is open, and opening another replaces it. 🏠 uses it too: it asks
first (🏠 goes, ✖️ stays), because home resets the floor, the filter and the sheet: `ask('🏠❓', [{glyph: '🏠', t: 'home', value: true}], 'home')`.

A second direction is not built: depth instead of one flat plane, layers at different depths (parallax) so the space reads as more than two axes. It would be additive on the same props and spots.

## Direction arrows (two positions, one arrow)

`world_point(rect, at)` takes the centre (`center`), the middle of an edge (`left` `right` `top` `bottom`) or a corner (`top-left` ...) of an object;
a spot or a person is a rect with no size. `world_direction(a, b, eps=8)` returns the arrow from `a` towards `b` (screen y grows downward, so a target above and to
the right is ↗️), or 📍 when both axes are within `eps`. It uses an integer slope (5/12, about 22.6°) instead of trigonometry, so Python and the page's `direction`
agree on every input (a Node test compares them on random points). `world_arrow_anchor("↘️")` goes the other way: an arrow, plain or emoji form (`↘`, `⬅`, `←`),
names an anchor (`bottom-right`); `🎯` and `📍` mean the centre. The recorder's `cam.zoom("↘️")` uses the same table.

## Moving (phone and PC)

* **Tap / click** a blank place or a spot: walk there around the furniture.
* **Arrow keys or WASD**: one tile at a time; hold to keep walking (the map must have focus; typing in a field never moves you).
  On a floor without a grid the keys are left to the page.
* **On-screen pad** (▲◀▶▼, 48px buttons, over the map's lower left): press and hold to keep walking; keyboard activation (Enter / Space) steps once.
* **🎯 自分の場所** (⋯ menu): zoom to yourself and keep the camera on you. Dragging the map stops the following.
* **X / Y form** (🚶, ⋯ menu) and the stop button (⏸️, ⚙️ menu) from the base world remain.

## The emoji comes first

With `avatars`, the world opens with a picker (a plain `div` in the map, shown by the script, not a modal): choose one of the
listed characters or type your own: an emoji, a short text such as an initial or a name, or both (`🐱たろう`), 1..16 characters.
In `avatars` and the `player` the same rule holds: control and line-separator characters, bidirectional overrides and spaces at either end are
refused; the label is set as text, never as markup. (`actors` and catalog pages keep the stricter emoji-only rule.) The player stays hidden until then. **🙂✏️** (⚙️ menu) reopens it. The emoji and the board messages are never stored; a reload
asks again. Without JavaScript the picker, the pad and the player controls stay hidden and the static map and spots still work.

## Not included

## Demos

Each GIF (`<world>-<scene>.gif`) is a real run of the generated page in Chrome, recorded by `tool/record_demo.py` (Playwright keeps a screenshot with its real
time whenever a scene waits; Pillow writes one shared palette and delta frames). They are regenerated, never edited by hand:

```sh
WEB_UI_CHROME=/path/to/chrome python tool/record_demo.py docs/demo --force            # all scenes
python tool/record_demo.py docs/demo --only keys tap --force --width 400               # some, smaller
```

| File | Shows |
|---|---|
| `school-pick.gif` | the picker comes first; choosing 🦊 puts it in the room |
| `school-avatar-text.gif` | **🙂✏️** (in ⚙️), then typing text and an emoji (`先生🍎`) as the character |
| `school-keys.gif` | arrow keys and WASD, a held key repeating, desks stopping the walk |
| `school-tap.gif` | tapping a chair (the path goes around the desks) and tapping a desk (nearest free tile) |
| `school-phone.gif` | a phone-sized screen: tap a character, the on-screen pad, drag the map away, **🎯** (in ⋯) |
| `school-menu.gif` | the ☰ list with its arrows; tap **黒板** and the arrow turns into 📍 as you arrive |
| `school-header.gif` | the header: ⭐ stars on two floors and their list, the 🗺️ tool, 🌐 the language, 🏠 home |
| `school-floors.gif` | the footer pulldown to the schoolyard, a spot's sheet, back to the classroom, the board spot |
| `overworld-lands.gif` | six lands by the 🚪 pulldown (forest, mountain, desert, coast, castle), then walking to the castle town from the ☰ list |
| `overworld-real.gif` | the real floor: ⋯ → 🖼️📷 → 🖼️ choose a photo, walk over it, then 🧹 (the photo is drawn by the recorder) |
| `cities-tokyo.gif` | Parallel Tokyo: the 🚉 tool (the six exits of Tokyo Station), Marunouchi to Yaesu through the concourse, the electronic board's dot and text, on to Kanda by ☰ |
| `cities-london.gif` | Reverse London: 🎡 in the header, King's Cross to Waterloo over the Thames bridge, the wooden **nogard** board: dot, text, 🐉, dot |
| `cities-paris.gif` | Fake Paris: 🥖 in the header, a 🔥 in each block, Gare du Nord to the **rive gauche** board by the Seine, then the Eiffel Tower |
| `school-oneliner.gif` | the one command from another repository; the byte count and time shown are that run's real output |

A scene may end with `cam.zoom((x, y))` (or an anchor name or arrow emoji such as `cam.zoom("↘️")`): a smooth zoom toward that point that stays (the easing of Ironmate's `png_zoom_gif.py`, taken into this
tool and written by the same encoder rather than kept as a second tool), because the README shows the GIFs small.
The frames are cropped to the world, not the whole page. A new operation is one `@scene` function in the tool. `tests/integration/school_browser.py` records every scene, so a UI change that breaks a demo
fails the browser job instead of leaving a stale GIF. The page asks for Meiryo first; these were recorded on Linux, where it is absent, so the fallback
face shows (record on Windows to get Meiryo).

Other people's avatars. Showing several visitors at once needs a server or peer connection, which this static layer
deliberately does not have. The shared GitHub board (`docs/world-shared-board.md`) remains the only shared channel.

## Verification

```
PYTHONPATH=. python -m pytest -q tests/test_world_classroom.py          # oracle, validation, generator, HTML, Node 26 parity
PYTHONPATH=. python -m pytest -q tests/test_world_places.py             # projection, bridges, nudging, scatter, flip, the three cities
WEB_UI_CHROME=/path/to/chrome python tests/integration/school_browser.py -v   # real browser: picker, keys, pad, taps, no desk crossing, 320..1280px
```
