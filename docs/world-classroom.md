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
| `avatars` | world | Up to 24 different emoji offered first; the choice replaces every floor's player emoji |

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

## Moving (phone and PC)

* **Tap / click** a blank place or a spot: walk there around the furniture.
* **Arrow keys or WASD**: one tile at a time; hold to keep walking (the map must have focus; typing in a field never moves you).
  On a floor without a grid the keys are left to the page.
* **On-screen pad** (▲◀▶▼, 48px buttons): press and hold to keep walking; keyboard activation (Enter / Space) steps once.
* **自分の場所**: zoom to yourself and keep the camera on you. Dragging the map stops the following.
* **X / Y form** and the stop button from the base world remain.

## The emoji comes first

With `avatars`, the world opens with a picker (a plain `div` in the map, shown by the script, not a modal): choose one of the
emoji or type any other single emoji. The player stays hidden until then. **絵文字を変える** reopens it. Nothing is stored; a reload
asks again. Without JavaScript the picker, the pad and the player controls stay hidden and the static map and spots still work.

## Not included

Other people's avatars. Showing several visitors at once needs a server or peer connection, which this static, no-storage layer
deliberately does not have. The shared GitHub board (`docs/world-shared-board.md`) remains the only shared channel.

## Verification

```
PYTHONPATH=. python -m pytest -q tests/test_world_classroom.py          # oracle, validation, generator, HTML, Node 26 parity
WEB_UI_CHROME=/path/to/chrome python tests/integration/school_browser.py -v   # real browser: picker, keys, pad, taps, no desk crossing, 320..1280px
```
