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

A grid world keeps the page short: nothing is stacked under the map, so a phone and a PC need no vertical scrolling.

* **Header**: only what does not fit the side: the info board (clock, announcements, the shared board).
* **Side**: this screen's own controls, two 48px buttons that open a panel over the map (one at a time; Escape, a tap on the map or choosing an item closes it).
  * **☰ 行き先**: the spots of the current floor (and the category chips, if any). Each row shows an arrow from you to the spot (⬆️ ↗️ ➡️ ↘️ ⬇️ ↙️ ⬅️ ↖️,
    📍 within one tile) that follows you as you walk; tap a row to walk there and read its sheet. Works without JavaScript too (the rows are links).
  * **⋯**: 動きを停止, the X / Y form (ここへ歩く), 自分の場所, 絵文字を変える. Shown by the script.
* **Footer**: the door-to-door pulldown 🚪 that moves between floors. Without JavaScript the plain floor labels stand in for it.

Worlds without a tile grid keep the original layout and markup (floor chips on top, controls below).

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
* **自分の場所** (⋯ menu): zoom to yourself and keep the camera on you. Dragging the map stops the following.
* **X / Y form** and the stop button from the base world remain (⋯ menu).

## The emoji comes first

With `avatars`, the world opens with a picker (a plain `div` in the map, shown by the script, not a modal): choose one of the
listed characters or type your own: an emoji, a short text such as an initial or a name, or both (`🐱たろう`), 1..16 characters.
In `avatars` and the `player` the same rule holds: control and line-separator characters, bidirectional overrides and spaces at either end are
refused; the label is set as text, never as markup. (`actors` and catalog pages keep the stricter emoji-only rule.) The player stays hidden until then. **絵文字を変える** (⋯ menu) reopens it. Nothing is stored; a reload
asks again. Without JavaScript the picker, the pad and the player controls stay hidden and the static map and spots still work.

## Not included

## Demos

Each GIF is a real run of the generated page in Chrome, recorded by `tool/record_demo.py` (Playwright keeps a screenshot with its real
time whenever a scene waits; Pillow writes one shared palette and delta frames). They are regenerated, never edited by hand:

```sh
WEB_UI_CHROME=/path/to/chrome python tool/record_demo.py docs/demo --force            # all scenes
python tool/record_demo.py docs/demo --only keys tap --force --width 400               # some, smaller
```

| File | Shows |
|---|---|
| `school-pick.gif` | the picker comes first; choosing 🦊 puts it in the room |
| `school-avatar-text.gif` | **絵文字を変える** (in ⋯), then typing text and an emoji (`先生🍎`) as the character |
| `school-keys.gif` | arrow keys and WASD, a held key repeating, desks stopping the walk |
| `school-tap.gif` | tapping a chair (the path goes around the desks) and tapping a desk (nearest free tile) |
| `school-phone.gif` | a phone-sized screen: tap a character, the on-screen pad, drag the map away, **自分の場所** (in ⋯) |
| `school-menu.gif` | the ☰ list with its arrows; tap **黒板** and the arrow turns into 📍 as you arrive |
| `school-floors.gif` | the footer pulldown to the schoolyard, a spot's sheet, back to the classroom, the board spot |
| `school-oneliner.gif` | the one command from another repository; the byte count and time shown are that run's real output |

A scene may end with `cam.zoom((x, y))` (or an anchor name or arrow emoji such as `cam.zoom("↘️")`): a smooth zoom toward that point that stays (the easing of Ironmate's `png_zoom_gif.py`, taken into this
tool and written by the same encoder rather than kept as a second tool), because the README shows the GIFs small.
The frames are cropped to the world, not the whole page. A new operation is one `@scene` function in the tool. `tests/integration/school_browser.py` records every scene, so a UI change that breaks a demo
fails the browser job instead of leaving a stale GIF. The page asks for Meiryo first; these were recorded on Linux, where it is absent, so the fallback
face shows (record on Windows to get Meiryo).

Other people's avatars. Showing several visitors at once needs a server or peer connection, which this static, no-storage layer
deliberately does not have. The shared GitHub board (`docs/world-shared-board.md`) remains the only shared channel.

## Verification

```
PYTHONPATH=. python -m pytest -q tests/test_world_classroom.py          # oracle, validation, generator, HTML, Node 26 parity
WEB_UI_CHROME=/path/to/chrome python tests/integration/school_browser.py -v   # real browser: picker, keys, pad, taps, no desk crossing, 320..1280px
```
