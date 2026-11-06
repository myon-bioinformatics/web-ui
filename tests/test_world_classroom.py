"""School world: the walking grid oracle, validation, the classroom generator, the emitted HTML, and Node parity.

Browser behaviour (picker, keys, pad, taps, collisions) is in tests/integration/school_browser.py.
"""
import io
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys

import pytest
import web_ui as ui

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import record_demo  # noqa: E402  (the GIF recorder for the README demos)

GRID = ["00000",
        "01110",
        "00010",
        "01000",
        "00000"]


def classroom(**kw):
    return ui.world_validate({"schema": ui.WORLD_SCHEMA, "id": "school", "floors": [ui.classroom_floor(**kw)]})["floors"][0]


def test_path_is_shortest_and_avoids_solid_tiles():
    path = ui.world_path(GRID, [0, 0], [4, 4])
    assert path[0] == [0, 0] and path[-1] == [4, 4] and len(path) == 9
    assert all(GRID[y][x] == "0" for x, y in path)
    assert all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(path, path[1:]))
    assert ui.world_path(GRID, [3, 3], [3, 3]) == [[3, 3]]
    assert ui.world_path(GRID, [0, 0], [0, 0]) == [[0, 0]]


def test_solid_or_cut_off_or_outside_goal_ends_at_the_nearest_reachable_tile():
    assert ui.world_path(GRID, [0, 0], [2, 1])[-1] == [2, 0]                # solid goal: the first nearest tile in search order
    walled = ["0100", "0100", "0100"]
    assert ui.world_path(walled, [0, 0], [3, 1])[-1] == [0, 1]              # the other side is cut off: nearest on this side
    assert ui.world_path(GRID, [0, 0], [-9, 99])[-1] == [0, 4]              # outside clamps into the grid
    assert ui.world_path(["1"], [0, 0], [0, 0]) == [[0, 0]]                 # the start always counts as free


def test_route_points_end_at_the_target_when_reachable_and_at_a_tile_centre_otherwise():
    blocked = ["00000", "01110", "00000"]
    points = ui.world_route_points(blocked, 32, [16, 16], [144, 80])        # reachable: ends exactly at the tapped point
    assert points[0] == [16, 16] and points[-1] == [144, 80]
    assert points[1] in ([48, 16], [16, 48])                                # around the block, through tile centres
    assert all(blocked[int(y // 32)][int(x // 32)] == "0" for x, y in points)
    points = ui.world_route_points(blocked, 32, [16, 16], [80, 48])         # a solid tile: ends at a free neighbour's centre
    assert points[-1] in ([80, 16], [80, 80]) and blocked[int(points[-1][1] // 32)][int(points[-1][0] // 32)] == "0"
    assert ui.world_route_points(blocked, 32, [20, 20], [20, 20]) == [[20, 20], [20, 20]]


def test_route_is_constant_speed_and_stays_on_free_tiles():
    floor = classroom()
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    rng = random.Random(7)
    free = [(x, y) for y, row in enumerate(blocked) for x, v in enumerate(row) if v == "0"]
    for _ in range(60):
        (ax, ay), (bx, by) = rng.sample(free, 2)
        a = [ax * 32 + rng.uniform(1, 31), ay * 32 + rng.uniform(1, 31)]
        b = [bx * 32 + rng.uniform(1, 31), by * 32 + rng.uniform(1, 31)]
        points = ui.world_route_points(blocked, 32, a, b)
        route = ui.world_route(points, at=2, speed=96, width=floor["width"], height=floor["height"])
        length = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
        end = route[-1]["at"] + route[-1]["duration"]
        assert end - 2 == pytest.approx(length / 96)
        assert ui.world_route_sample(route, 2) == pytest.approx(a)
        assert ui.world_route_sample(route, 1e9) == pytest.approx(b)
        for i in range(int((end - 2) / .05) + 1):
            x, y = ui.world_route_sample(route, 2 + i * .05)
            assert blocked[int(y // 32)][int(x // 32)] == "0", (a, b, x, y)
        # retargeting samples the old route first, then starts a new one from there
        here = ui.world_route_sample(route, 2 + (end - 2) / 2)
        assert ui.world_route(ui.world_route_points(blocked, 32, here, a), at=5, speed=96)[0]["from"] == pytest.approx(here)


def test_a_route_with_nowhere_to_go_is_one_still_segment():
    route = ui.world_route([[10, 20]], at=3, speed=50)
    assert len(route) == 1 and route[0]["duration"] == 0
    assert ui.world_route_sample(route, 0) == [10, 20] and ui.world_route_sample(route, 9) == [10, 20]


@pytest.mark.parametrize("rows,groups,per_group,tile", [(1, 1, 1, 16), (4, 3, 2, 32), (8, 6, 4, 32), (3, 2, 3, 64), (5, 4, 1, 128)])
def test_classroom_generator_is_valid_aligned_and_fully_walkable(rows, groups, per_group, tile):
    floor = classroom(rows=rows, groups=groups, per_group=per_group, tile=tile)
    blocked = ui.world_blocked(floor["width"], floor["height"], tile, floor["props"])
    assert floor["width"] % tile == 0 and floor["height"] % tile == 0 and tile % 8 == 0
    desks = [p for p in floor["props"] if p["kind"] == "desk"]
    chairs = [p for p in floor["props"] if p["kind"] == "chair"]
    assert len(chairs) == rows * groups * per_group and len(desks) == len(chairs) + 1   # one chair per student desk, plus the teacher's desk
    start = [floor["player"]["x"] // tile, floor["player"]["y"] // tile]
    seen = {tuple(start)}
    frontier = [tuple(start)]
    for x, y in frontier:                                                    # every free tile can be reached from the door
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if 0 <= n[0] < len(blocked[0]) and 0 <= n[1] < len(blocked) and blocked[n[1]][n[0]] == "0" and n not in seen:
                seen.add(n)
                frontier.append(n)
    free = {(x, y) for y, row in enumerate(blocked) for x, v in enumerate(row) if v == "0"}
    assert seen == free
    assert all((c["x"] // tile, c["y"] // tile) in free for c in chairs)


def test_default_classroom_sizes_are_multiples_of_eight():
    floor = classroom()
    numbers = [floor["width"], floor["height"], floor["tile"], floor["player"]["x"] - 16, floor["player"]["y"] - 16]
    for p in floor["props"]:
        numbers += [p["x"], p["y"], p["w"], p["h"]]
    assert all(n % 8 == 0 for n in numbers)


def test_the_old_world_is_unchanged_by_the_new_fields():
    value = ui.world_validate(ui.example_data("world"))
    assert "avatars" not in value and all("tile" not in f and "props" not in f for f in value["floors"])
    html = ui.world_html(ui.example_data("world"))
    for marker in ("ui-prop", "data-blocked", "data-grid", "ui-world-pick", "data-step", "data-me", "ui-world-grid-only"):
        assert marker not in html


def test_school_html_has_props_grid_pad_and_picker_and_escapes_text():
    school = ui.example_data("school")
    school["floors"][0]["spots"][0]["label"] = "<b>黒板</b>"
    html = ui.world_html(school)
    assert html.count('class="ui-prop"') == len(ui.world_validate(school)["floors"][0]["props"])
    assert 'data-grid' in html and html.count('data-step="') == 4 and 'data-me' in html and 'data-pick-open' in html
    assert html.count('data-emoji="') == len(school["avatars"]) and 'name="emoji"' in html and 'maxlength="32"' in html
    assert "<b>黒板</b>" not in html and "&lt;b&gt;" in html
    rows = html.split('data-blocked="')[1].split('"')[0].split(",")
    floor = ui.world_validate(school)["floors"][0]
    assert len(rows) == floor["height"] // floor["tile"] and all(len(r) == floor["width"] // floor["tile"] for r in rows)
    assert set("".join(rows)) <= {"0", "1"}
    assert 'hidden' in html.split('class="ui-world-pick"')[1].split(">")[0]       # opened by the script only
    assert "[data-kind=desk]" in ui.world_css(school) and "[data-kind=desk]" not in ui.world_css(school, base=False)


@pytest.mark.parametrize("change", [
    lambda f: f.update(tile=12),                                              # not a multiple of 8
    lambda f: f.update(tile=7),
    lambda f: f.update(tile=48),                                              # does not divide the floor
    lambda f: f.update(tile=True),
    lambda f: f["props"].append({"kind": "sofa", "x": 0, "y": 0, "w": 32, "h": 32}),
    lambda f: f["props"].append({"kind": "desk", "x": 8, "y": 0, "w": 32, "h": 32}),   # off the tiles
    lambda f: f["props"].append({"kind": "desk", "x": 352, "y": 0, "w": 64, "h": 32}),  # outside the floor
    lambda f: f["props"].append({"kind": "desk", "x": 0, "y": 0, "w": 0, "h": 32}),
    lambda f: f["props"].append({"kind": "desk", "x": 0, "y": 0, "w": 32}),
    lambda f: f["props"].append({"kind": ["desk"], "x": 0, "y": 0, "w": 32, "h": 32}),
    lambda f: f.update(props=f["props"] * 11),                                 # too many
    lambda f: f["player"].update(x=80, y=176),                                # starts on a desk
    lambda f: f.update(extra=1),
])
def test_floor_validation_refuses(change):
    floor = ui.classroom_floor()
    change(floor)
    with pytest.raises(ValueError):
        ui.world_validate({"schema": ui.WORLD_SCHEMA, "floors": [floor]})


def test_props_need_a_tile_grid_and_avatars_are_bounded():
    floor = ui.classroom_floor()
    del floor["tile"]
    with pytest.raises(ValueError):
        ui.world_validate({"schema": ui.WORLD_SCHEMA, "floors": [floor]})
    base = {"schema": ui.WORLD_SCHEMA, "floors": [ui.classroom_floor()]}
    for bad in (["🙂", "🙂"], ["a", "a"], [f"{chr(0x1f600 + i)}" for i in range(25)], "🙂", [1], [""], ["x" * 17], [" a"], ["a "], ["a\nb"],
                ["a\u202eb"], ["a\u2028b"], ["\u3000a"]):
        with pytest.raises(ValueError):
            ui.world_validate({**base, "avatars": bad})
    mixed = ["🙂", "A", "先生", "🐱たろう", "a b", "👨‍👩‍👧‍👦", "x" * 16, "<b>"]       # emoji, text or both: any one label
    assert ui.world_validate({**base, "avatars": mixed})["avatars"] == mixed
    html = ui.world_html({**base, "avatars": mixed})
    assert 'data-emoji="先生"' in html and 'data-emoji="&lt;b&gt;"' in html and 'data-emoji="<b>"' not in html
    floor = ui.classroom_floor()
    floor["player"] = {**floor["player"], "emoji": "ねこ"}
    assert ui.world_validate({**base, "floors": [floor]})["floors"][0]["player"]["emoji"] == "ねこ"
    for bad in ({"rows": 0}, {"groups": 7}, {"per_group": 5}, {"tile": 12}, {"tile": 8}):
        with pytest.raises(ValueError):
            ui.classroom_floor(**bad)


def test_validation_is_idempotent_for_the_school_example():
    once = ui.world_validate(ui.example_data("school"))
    assert ui.world_validate(once) == once


def _node26():
    node = shutil.which('node')
    if not node or int(subprocess.check_output([node, '--version'], text=True).lstrip('v').split('.')[0]) < 26:
        pytest.skip('existing Node 26+ required; no installation')
    return node


def test_node26_grid_route_matches_python_oracle(tmp_path):
    node = _node26()
    floor = classroom()
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    rng = random.Random(11)
    routes = [[[rng.uniform(-40, 420), rng.uniform(-40, 560)], [rng.uniform(-40, 420), rng.uniform(-40, 560)]] for _ in range(150)]
    routes += [[[16, 16], [16, 16]], [[176, 496], [80, 176]], [[176, 496], [80, 272]], [[0, 0], [383.9, 511.9]]]
    cases = [[GRID, 32, [10, 10], [140, 140]], [GRID, 32, [10, 10], [80, 48]], [["1"], 32, [5, 5], [20, 20]]]
    cases += [[blocked, 32, a, b] for a, b in routes]
    glyphs = ["🐱", " 🦖x ", "先生", "A", "", "   ", "x" * 16, "x" * 17, "a\nb", "a\u202eb", "a\u2028b", "🐱たろう", "👨‍👩‍👧‍👦", "a b", "\u3000a\u3000"]
    module = tmp_path / 'grid.mjs'
    module.write_text(ui.WORLD_JS.removesuffix('bindWorlds();\n') + '\nconst cases=' + json.dumps(cases) + ';const times=[0,0.4,1,2.5,7,1e6];'
                      'console.log(JSON.stringify({routes:cases.map(([r,t,a,b])=>gridRoute(r,t,a,b)),'
                      'samples:cases.map(([r,t,a,b])=>{const route=motionRoute(gridRoute(r,t,a,b),2,96,384,512);return times.map(x=>routeSample(route,2+x))}),'
                      'glyphs:' + json.dumps(glyphs) + '.map(cleanAvatar)}))\n')
    result = json.loads(subprocess.check_output([node, str(module)], text=True))
    for (rows, tile, a, b), actual, samples in zip(cases, result['routes'], result['samples']):
        expected = ui.world_route_points(rows, tile, a, b)
        assert len(actual) == len(expected)
        for got, want in zip(actual, expected):
            assert got == pytest.approx(want, abs=1e-9)
        route = ui.world_route(expected, at=2, speed=96, width=384, height=512)
        for t, point in zip([0, 0.4, 1, 2.5, 7, 1e6], samples):
            assert point == pytest.approx(ui.world_route_sample(route, 2 + t), abs=1e-9)
    assert result['glyphs'] == ['🐱', '🦖x', '先生', 'A', None, None, 'x' * 16, None, None, None, None, '🐱たろう', '👨‍👩‍👧‍👦', 'a b', 'a']
    for text in glyphs:                                                  # the page and the oracle accept the same labels
        try:
            ui._world_avatar(text.strip())
            ok = True
        except ValueError:
            ok = False
        assert ok == (result['glyphs'][glyphs.index(text)] is not None), text


def test_direction_is_the_arrow_from_the_first_point_to_the_second():
    here = [100, 100]
    assert [ui.world_direction(here, p) for p in ([200, 100], [200, 200], [100, 200], [0, 200], [0, 100], [0, 0], [100, 0], [200, 0])] == \
        ["➡️", "↘️", "⬇️", "↙️", "⬅️", "↖️", "⬆️", "↗️"]                         # screen y grows downward: a target below is ⬇️
    assert ui.world_direction(here, [104, 96]) == ui.WORLD_HERE == "📍"       # both axes within eps (8)
    assert ui.world_direction(here, [104, 96], eps=0) == "↗️" and ui.world_direction(here, [100, 100], eps=0) == "📍"
    assert ui.world_direction([0, 0], [240, 99]) == "➡️" and ui.world_direction([0, 0], [240, 101]) == "↘️"      # the 5/12 slope edge
    assert ui.world_direction([5, 5], [5, 5]) == "📍"
    for a, b in ((here, [180, 7]), (here, [3, 250]), ([9, 8], [90, 100])):    # swapping the points turns the arrow around
        turned = {"➡️": "⬅️", "↘️": "↖️", "⬇️": "⬆️", "↙️": "↗️", "⬅️": "➡️", "↖️": "↘️", "⬆️": "⬇️", "↗️": "↙️"}
        assert ui.world_direction(b, a) == turned[ui.world_direction(a, b)]


def test_points_come_from_the_centre_or_an_edge_of_each_object():
    desk = {"x": 64, "y": 32, "w": 96, "h": 32}
    assert ui.world_point(desk) == (112, 48) and ui.world_point(desk, "center") == (112, 48)
    assert [ui.world_point(desk, at) for at in ("left", "right", "top", "bottom")] == [(64, 48), (160, 48), (112, 32), (112, 64)]
    assert [ui.world_point((0, 0, 8, 8), at) for at in ("top-left", "top-right", "bottom-left", "bottom-right")] == [(0, 0), (8, 0), (0, 8), (8, 8)]
    assert ui.world_point((50, 60, 0, 0)) == (50, 60)                          # a spot or a person: a rect with no size
    with pytest.raises(ValueError):
        ui.world_point(desk, "middle")
    # a chair centred under the desk: its top edge meets the desk's bottom edge (here), and from the chair's centre the desk is straight up
    chair = (96, 64, 32, 32)
    assert ui.world_direction(ui.world_point(chair, "top"), ui.world_point(desk, "bottom"), eps=0) == "📍"
    assert ui.world_direction(ui.world_point(chair), ui.world_point(desk)) == "⬆️"


def test_arrow_names_an_anchor_in_any_form():
    assert [ui.world_arrow_anchor(a) for a in ("↘️", "↘", "↘\ufe0e", "⬅", "⬅️", "←", "→", "➡️", "↑", "⬆️", "↓", "⬇", "↖", "↗️", "↙", "🎯", "📍")] == \
        ["bottom-right"] * 3 + ["left"] * 3 + ["right"] * 2 + ["top"] * 2 + ["bottom"] * 2 + ["top-left", "top-right", "bottom-left", "center", "center"]
    assert all(ui.world_arrow_anchor(a) in ui.WORLD_ANCHORS for a in "←→↑↓↖↗↙↘🎯")
    for bad in ("", "x", "➕", "↘️↘️"):
        with pytest.raises(ValueError):
            ui.world_arrow_anchor(bad)


def test_node26_direction_matches_python_oracle(tmp_path):
    node = _node26()
    rng = random.Random(23)
    cases = [[[rng.randint(-300, 300), rng.randint(-300, 300)], [rng.randint(-300, 300), rng.randint(-300, 300)], rng.choice([0, 8, 16, 32])] for _ in range(400)]
    cases += [[[rng.uniform(-300, 300), rng.uniform(-300, 300)], [rng.uniform(-300, 300), rng.uniform(-300, 300)], rng.choice([0.5, 8, 24])] for _ in range(400)]
    cases += [[[0, 0], [240, 99], 8], [[0, 0], [240, 101], 8], [[0, 0], [99, 240], 8], [[0, 0], [101, 240], 8], [[3, 3], [3, 3], 0], [[0, 0], [8, 8], 8], [[0, 0], [9, 8], 8]]
    module = tmp_path / 'direction.mjs'
    module.write_text(ui.WORLD_JS.removesuffix('bindWorlds();\n') + '\nconst cases=' + json.dumps(cases) + ';console.log(JSON.stringify(cases.map(([a,b,e])=>direction(a,b,e))))\n')
    got = json.loads(subprocess.check_output([node, str(module)], text=True))
    assert got == [ui.world_direction(a, b, e) for a, b, e in cases]
    assert {"➡️", "↘️", "⬇️", "↙️", "⬅️", "↖️", "⬆️", "↗️", "📍"} == set(got)


def _world(**extra):
    spec = ui.example_data("school")
    spec.pop("tools", None)
    return {**spec, **extra}


def test_tools_map_an_emoji_to_one_feature_and_are_checked():
    world = ui.world_validate(_world(tools={"🏫": {"label": "学校", "body": "ここは学校です。"}, "🛝": {"floor": "yard", "slot": "side"},
                                            "🗺️": {"label": "地図", "label_en": "Map", "spots": ["classroom-board", "flowers"]}}))
    assert list(world["tools"]) == ["🏫", "🛝", "🗺️"]
    assert world["tools"]["🛝"] == {"label": "🛝", "label_en": "🛝", "slot": "side", "floor": "yard"}       # the emoji is the default name
    assert world["tools"]["🗺️"]["spots"] == ["classroom-board", "flowers"] and world["tools"]["🏫"]["slot"] == "head"
    assert ui.world_validate(world) == world                                                              # the expanded form is ordinary data
    assert "tools" not in ui.world_validate(_world())
    bad = [{"🏠": {"body": "x"}}, {"⚙️": {"body": "x"}}, {"🌐": {"body": "x"}}, {"a": {"body": "x"}},                # the page's own icons; plain ASCII
           {"🏫": {}}, {"🏫": {"body": "x", "floor": "yard"}}, {"🏫": {"floor": "roof"}}, {"🏫": {"spots": []}}, {"🏫": {"spots": ["nope"]}},
           {"🏫": {"body": "x", "slot": "top"}}, {"🏫": {"body": "x", "icon": "y"}}, {"🏫": "x"}, {f"{chr(0x1F600 + i)}": {"body": "x"} for i in range(9)}]
    for tools in bad:
        with pytest.raises(ValueError):
            ui.world_validate(_world(tools=tools))
    with pytest.raises(ValueError):
        ui.world_validate({"schema": ui.WORLD_SCHEMA, "shots": [{"id": "a", "label": "a", "title": "a"}], "tools": {"🏫": {"body": "x"}}})
    with pytest.raises(ValueError):
        ui.world_validate(_world(shell="yes"))


def test_a_shell_world_is_icons_in_a_header_a_side_and_a_footer():
    html = ui.world_html(_world(tools={"🗺️": {"label": "地図", "label_en": "Map", "spots": ["classroom-board", "flowers"]},
                                       "🏫": {"label": "学校", "body": "ここは学校です。"}, "🛝": {"label": "校庭", "floor": "yard", "slot": "side"}}))
    head = html[html.index('<header class="ui-world-head">'):html.index("</header>")]
    side = html[html.index('<div class="ui-world-side">'):html.index('<footer class="ui-world-foot">')]
    assert [m for m in ("🏠", "🗺️", "🏫", "⭐", "⚙️") if m in head] == ["🏠", "🗺️", "🏫", "⭐", "⚙️"] and head.index("🏠") < head.index("🗺️") < head.index("⭐") < head.index("⚙️")
    assert "☰" in side and "⋯" in side and "🛝" in side and 'for="school-floor-yard"' in side and "🚪" in html[html.index("<footer"):]
    assert 'aria-label="ホーム" title="ホーム" data-t="home"' in head and 'aria-label="地図" title="地図" data-labels="{&quot;ja&quot;:&quot;地図&quot;,&quot;en&quot;:&quot;Map&quot;}"' in head
    assert "<select data-lang" in head and head.count("<option ") == 11 and "data-pick-open" in head and "data-pick-open" in head and 'class="ui-world-pause"' in head and " data-me " in side         # global in the header, local in the side
    assert 'class="ui-world-pause"' not in side and "data-pick-open" not in side
    assert '<a href="#school-spot-flowers" data-x="480" data-y="96" data-floor="yard">' in html                                  # a place on another floor shows 🚪, not an arrow
    assert html.count("ui-world-star") >= 5 and 'class="ui-world-rows ui-world-favs"' in head
    assert "✖️" in html   and ">Close<" not in html and "ほかの絵文字・文字 <input" not in html                                   # icons, with the words in aria-label
    assert 'data-grid data-shell' in html and ' data-shell' in html
    old = ui.world_html({"schema": ui.WORLD_SCHEMA, "floors": [{"id": "a", "label": "A", "width": 128, "height": 128, "spots": [{"id": "s", "x": 8, "y": 8, "label": "S"}]}]})
    assert "ui-world-head" not in old and "data-shell" not in old and ">Close<" in old                          # worlds without a grid keep their layout and markup


def test_any_world_may_ask_for_the_shell_and_a_catalogue_can_too():
    cat = ui.catalogue_world([{"id": "a", "label": "A", "group": "g1", "emoji": "🌍"}, {"id": "b", "label": "B", "group": "g2"}], shell=True,
                             tools={"💡": {"label": "ヒント", "body": "押すと詳しく出ます。"}})
    html = ui.world_html(cat)
    assert " data-shell" in html and "data-grid" not in html and "ui-world-dpad" not in html and " data-me " not in html and "💡" in html
    assert 'class="ui-world-goto"' in html and 'data-floor="f1"' in html and 'data-floor="f2"' in html
    plain = ui.world_html(ui.catalogue_world([{"id": "a", "label": "A", "group": "g1"}]))
    assert "data-shell" not in plain and "ui-world-head" not in plain
    css = ui.world_css(cat)
    assert '.ui-world-spots[data-floor="f1"]{display:block}' in css and '.ui-world-spots[data-floor' not in ui.world_css(ui.catalogue_world([{"id": "a", "label": "A", "group": "g1"}]))


def test_a_floor_can_ask_for_a_classroom_in_plain_json():
    params = {"rows": 3, "groups": 2, "per_group": 3, "tile": 32}
    world = {"schema": ui.WORLD_SCHEMA, "avatars": ["🙂"], "floors": [{"id": "room", "label": "教室A", "classroom": params}]}
    floor = ui.world_validate(world)["floors"][0]
    built = ui.world_validate({"schema": ui.WORLD_SCHEMA, "floors": [ui.classroom_floor(**params, id="room", label="教室A")]})["floors"][0]
    assert floor == built and "classroom" not in floor
    assert ui.world_validate(ui.world_validate(world)) == ui.world_validate(world)            # the expanded form is ordinary data
    default = ui.world_validate({"schema": ui.WORLD_SCHEMA, "floors": [{"classroom": {}}]})["floors"][0]
    assert default["id"] == "classroom" and default["label"] == "教室" and default["tile"] == 32


def test_classroom_floor_keeps_what_is_given_beside_it_and_mixes_with_ordinary_floors():
    spot = {"id": "clock", "x": 192, "y": 64, "label": "時計", "body": "あと5分"}
    mixed = {"schema": ui.WORLD_SCHEMA, "floors": [
        {"id": "room", "label": "教室", "classroom": {}, "spots": [spot], "player": {"emoji": "🐱", "x": 176, "y": 496, "speed": 64}},
        {"id": "yard", "label": "校庭", "width": 128, "height": 128, "spots": [{"id": "bar", "x": 64, "y": 64, "label": "鉄棒", "body": "-"}]}]}
    room, yard = ui.world_validate(mixed)["floors"]
    assert [s["id"] for s in room["spots"]] == ["clock"] and room["player"]["emoji"] == "🐱" and room["player"]["speed"] == 64
    assert room["props"] and "tile" not in yard and "props" not in yard


@pytest.mark.parametrize("floor", [
    {"id": "r", "label": "x", "classroom": {"rows": 0}},
    {"id": "r", "label": "x", "classroom": {"tile": 12}},
    {"id": "r", "label": "x", "classroom": {"depth": 3}},
    {"id": "r", "label": "x", "classroom": "big"},
    {"id": "r", "label": "x", "classroom": [4, 3]},
    {"id": "r", "label": "x", "classroom": {}, "width": 640},                 # sizes come from the generator
    {"id": "r", "label": "x", "classroom": {}, "props": []},
    {"id": 7, "label": "x", "classroom": {}},
    {"id": "R!", "label": "x", "classroom": {}},
    {"id": "r", "label": ["x"], "classroom": {}},
    {"id": "r", "label": "x", "classroom": {"rows": True}},
])
def test_classroom_directive_refuses_bad_data(floor):
    with pytest.raises(ValueError):
        ui.world_validate({"schema": ui.WORLD_SCHEMA, "floors": [floor]})


ONE_LINER = {"schema": ui.WORLD_SCHEMA, "avatars": ["🙂", "🐱"], "floors": [{"id": "room", "label": "教室", "classroom": {"rows": 5, "groups": 3}}]}


def _cli(*args, stdin, command=None):
    import os
    import sys
    cmd = command or [sys.executable, "-S", "web_ui.py"]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.run([*cmd, *args], input=stdin.encode("utf-8"), capture_output=True, cwd=root, timeout=60)


def test_world_page_from_stdin_equals_the_page_from_a_file(tmp_path):
    expected = ui.world_document(ONE_LINER)
    result = _cli("--world", "-", stdin=json.dumps(ONE_LINER, ensure_ascii=False))
    assert result.returncode == 0 and result.stdout.decode("utf-8") == expected
    (tmp_path / "w.json").write_text(json.dumps(ONE_LINER, ensure_ascii=False), encoding="utf-8")
    assert _cli("--world", str(tmp_path / "w.json"), stdin="").stdout.decode("utf-8") == expected
    piped = _cli("--world", "-", stdin=_cli("--example", "school", stdin="").stdout.decode("utf-8"))   # the pipe in one line
    assert piped.returncode == 0 and piped.stdout.decode("utf-8") == ui.world_document(ui.example_data("school"))


@pytest.mark.parametrize("bad", ["not json", "", "[]", json.dumps({**ONE_LINER, "floors": [{"id": "r", "label": "x", "classroom": {"rows": 99}}]})])
def test_world_from_stdin_reports_bad_specs_without_a_traceback(bad):
    result = _cli("--world", "-", stdin=bad)
    assert result.returncode == 2 and result.stdout == b"" and b"Traceback" not in result.stderr and b"error" in result.stderr


def test_world_from_stdin_is_bounded():
    result = _cli("--world", "-", stdin=" " * (ui.PATTERN_MAX_INPUT + 10))
    assert result.returncode == 2 and b"larger than" in result.stderr


def test_node26_reaches_the_same_page_through_py_launch():
    node = _node26()
    expected = ui.world_document(ONE_LINER)
    result = _cli("--", "web_ui.py", "--world", "-", stdin=json.dumps(ONE_LINER, ensure_ascii=False), command=[node, "vendor/py_launch.cjs"])
    assert result.returncode == 0 and result.stdout.decode("utf-8") == expected


def _png(color, mark=None, size=(64, 48)):
    from PIL import Image
    image = Image.new("RGB", size, color)
    if mark:
        image.paste(mark, (8, 8, 24, 24))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_demo_gif_keeps_real_timing_and_decodes_to_the_same_pictures():
    pytest.importorskip("PIL")
    from PIL import Image, ImageChops
    shots = [(10.0, _png((13, 17, 23))), (10.003, _png((13, 17, 23), (255, 0, 0))), (10.5, _png((13, 17, 23), (0, 255, 0))), (11.0, _png((0, 0, 255)))]
    gif = record_demo.encode(shots, tail_ms=700)
    image = Image.open(io.BytesIO(gif))
    assert gif[:6] == b"GIF89a" and image.n_frames == 4 and image.info["loop"] == 0
    delays = []
    for index in range(image.n_frames):
        image.seek(index)
        delays.append(image.info["duration"])
    assert delays == [20, 500, 500, 700]                       # 3 ms is lifted to 20 ms; real gaps round to 10 ms; the tail is the last frame
    for index, (_, png) in enumerate(shots):                   # delta frames still show exactly what was on screen
        image.seek(index)
        assert ImageChops.difference(image.convert("RGB"), Image.open(io.BytesIO(png)).convert("RGB")).getbbox() is None


def test_demo_gif_merges_still_frames_and_can_shrink():
    pytest.importorskip("PIL")
    from PIL import Image
    shots = [(0.0, _png("black")), (0.1, _png("black")), (0.2, _png("black")), (0.3, _png("white"))]
    image = Image.open(io.BytesIO(record_demo.encode(shots, width=32)))
    assert image.size == (32, 24) and image.n_frames == 2


def test_demo_recorder_refuses_before_it_opens_a_browser(tmp_path, capsys):
    assert set(record_demo.SCENES) >= {"pick", "avatar-text", "keys", "tap", "phone", "menu", "header", "floors", "oneliner", "lands", "real"}
    assert record_demo.SCENES["lands"].world == "overworld" and record_demo.SCENES["real"].world == "overworld" and record_demo.SCENES["keys"].world == "school"
    with pytest.raises(ValueError, match="unknown scene: nope"):
        record_demo.record(tmp_path, ["nope"])
    (tmp_path / "school-pick.gif").write_bytes(b"GIF89a")
    with pytest.raises(FileExistsError, match="--force"):
        record_demo.record(tmp_path, ["pick"])
    assert (tmp_path / "school-pick.gif").read_bytes() == b"GIF89a"
    with pytest.raises(SystemExit) as exit_info:
        record_demo.main([str(tmp_path), "--only", "pick"])
    assert exit_info.value.code == 1 and "refusing to overwrite" in capsys.readouterr().err


def test_demo_zoom_goes_in_toward_the_anchor_and_stays_on_the_real_clock():
    pytest.importorskip("PIL")
    from PIL import Image

    class Page:                                                 # a screenshot of a red corner (bottom left) on blue
        def screenshot(self, type):
            image = Image.new("RGB", (40, 40), (0, 0, 255))
            image.paste((255, 0, 0), (0, 20, 20, 40))
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue()

    camera = record_demo.Camera(Page())
    camera.zoom(anchor=(0, 1), factor=2, steps=4, hold_ms=300)
    assert len(camera.shots) == 4                               # three steps in, then the peak
    times = [t for t, _ in camera.shots]
    assert times == sorted(times) and round((times[-1] - times[-2]) * 1000) == 60 and round((times[1] - times[0]) * 1000) == 60
    frames = [Image.open(io.BytesIO(png)).convert("RGB") for _, png in camera.shots]
    assert frames[3].getpixel((20, 20)) == (255, 0, 0)          # at the peak the bottom-left corner fills the picture
    assert record_demo.time.monotonic() >= times[-1] + 0.3      # the real clock was let catch up (the peak is held 300 ms)
    for anchor in ("↙️", "↙", "bottom-left", (0, 1)):          # an arrow emoji, an anchor name or a fraction: the same corner
        camera = record_demo.Camera(Page())
        camera.zoom(anchor=anchor, factor=2, steps=2, hold_ms=20)
        assert Image.open(io.BytesIO(camera.shots[-1][1])).convert("RGB").getpixel((20, 20)) == (255, 0, 0), anchor
    with pytest.raises(ValueError):
        record_demo.Camera(Page()).zoom(anchor="x")


def test_the_chrome_speaks_the_eleven_languages_of_flutter_navigation_basic():
    codes = [code for code, _ in ui.WORLD_LANGS]
    assert codes == ["ja", "en", "fr", "es", "pt", "ar", "zh", "ru", "id", "de", "sw"]
    for key, words in ui.WORLD_TEXT.items():                                   # every word in every language, none left as a stand-in
        assert len(words) == 11 and all(w.strip() for w in words), key
        assert len(set(words)) >= 6, key                                       # a few are the same word in several languages (Hotel-like), not all
    runtime = ("invalid", "camera", "photo", "clear", "unavailable")           # said by the script (a validity message, the ask() choices), not in the markup
    assert all(f'data-t="{k}"' in ui.world_html(ui.EXAMPLES["overworld"]) or k in runtime for k in ui.WORLD_TEXT)
    assert all(f"'{k}'" in ui.WORLD_JS for k in runtime[1:])
    assert ui.WORLD_JS.startswith(ui.WORLD_MOTION_JS + ui.WORLD_SHARED_JS + ui.WORLD_TEXT_JS)
    catalogue = json.loads(ui.WORLD_TEXT_JS.split("WORLD_TEXT=")[1].rstrip(";\n"))
    assert catalogue == {k: list(v) for k, v in ui.WORLD_TEXT.items()}
    assert 'lang="ar">العربية</option>' in ui.world_html(_world())


def test_a_tool_can_name_itself_in_the_other_languages():
    world = ui.world_validate(_world(tools={"🗺️": {"label": "地図", "label_en": "Map", "labels": {"fr": "Carte", "de": "Karte"}, "spots": ["flowers"]}}))
    assert world["tools"]["🗺️"]["labels"] == {"fr": "Carte", "de": "Karte"}
    html = ui.world_html(world)
    assert "&quot;fr&quot;:&quot;Carte&quot;" in html and "&quot;de&quot;:&quot;Karte&quot;" in html
    assert "labels" not in ui.world_validate(_world(tools={"🗺️": {"spots": ["flowers"]}}))["tools"]["🗺️"]
    for bad in ({"ja": "x"}, {"en": "x"}, {"xx": "x"}, {"fr": ""}, {"fr": "x" * 25}, ["fr"], "fr"):
        with pytest.raises(ValueError):
            ui.world_validate(_world(tools={"🗺️": {"labels": bad, "spots": ["flowers"]}}))


# ---- lands: the same grid, other objects --------------------------------------------------------------------------------------------

def _reach(floor):
    """Tiles the player can walk to, and the walking grid they were found on."""
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    return set(ui.world_reach(blocked, (floor["player"]["x"] // floor["tile"], floor["player"]["y"] // floor["tile"]))), blocked


@pytest.mark.parametrize("theme", sorted(ui.LAND_THEMES))
@pytest.mark.parametrize("size", [(24, 16, 32), (12, 12, 32), (48, 32, 64), (30, 20, 16)])
def test_every_land_is_valid_and_its_town_and_landmark_can_be_walked_to(theme, size):
    cols, rows, tile = size
    for seed in (0, 1, 7, 12345):
        floor = ui.land_floor(theme, cols, rows, seed=seed, tile=tile, id=theme)
        checked = ui.world_validate({"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [floor]})["floors"][0]
        assert checked["props"] == floor["props"] and checked["player"] == floor["player"] and len(floor["props"]) <= 512 and floor["width"] == cols * tile and floor["height"] == rows * tile
        assert all(v % 8 == 0 for q in floor["props"] for v in (q["x"], q["y"], q["w"], q["h"]))
        reach, blocked = _reach(floor)
        for spot in floor["spots"]:
            cell = (spot["x"] // tile, spot["y"] // tile)
            assert cell in reach and blocked[cell[1]][cell[0]] == "0", (theme, seed, spot["id"])
        assert [s["id"] for s in floor["spots"]] == [f"{theme}-town", f"{theme}-landmark"]


def test_a_land_is_the_same_every_time_and_the_seed_makes_another():
    assert ui.land_floor("forest", seed=4) == ui.land_floor("forest", seed=4)
    assert ui.land_floor("forest", seed=4) != ui.land_floor("forest", seed=5)
    assert ui.land_floor("meadow", seed=4)["props"] != ui.land_floor("forest", seed=4)["props"]
    assert ui.land_floor("meadow")["label"] == ui.LAND_THEMES["meadow"]["label"] and ui.land_floor("meadow", label="北")["label"] == "北"
    for bad in (dict(theme="moon"), dict(cols=11), dict(rows=11), dict(cols=49), dict(tile=20), dict(tile=128, cols=40), dict(seed=-1), dict(seed=2**31)):
        with pytest.raises(ValueError):
            ui.land_floor(**bad)


def test_ground_opens_the_tiles_it_covers_and_the_other_kinds_only_block():
    props = [{"kind": "water", "x": 0, "y": 0, "w": 128, "h": 32}, {"kind": "bridge", "x": 32, "y": 0, "w": 32, "h": 32},
             {"kind": "tree", "x": 0, "y": 32, "w": 64, "h": 32}, {"kind": "road", "x": 0, "y": 32, "w": 32, "h": 32}]
    assert ui.world_blocked(128, 64, 32, props) == ["1011", "0100"]                 # a bridge through water, a road through trees
    desk_then_rug = [{"kind": "desk", "x": 0, "y": 0, "w": 32, "h": 32}, {"kind": "rug", "x": 0, "y": 0, "w": 32, "h": 32}]
    assert ui.world_blocked(32, 32, 32, desk_then_rug) == ["1"]                     # chairs and rugs never open anything: the classroom is as it was
    assert set(ui.WORLD_GROUND) == {"grass", "sand", "road", "bridge"} and all(k in ui.WORLD_PROPS for k in ui.WORLD_LOOK)


def test_a_land_is_one_line_of_json_and_the_school_is_untouched():
    spec = {"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [{"id": "n", "label": "北", "land": {"theme": "coast", "seed": 3}}]}
    floor = ui.world_validate(spec)["floors"][0]
    assert {k: v for k, v in floor.items() if k != "spots"} == {k: v for k, v in ui.land_floor("coast", seed=3, id="n", label="北").items() if k != "spots"}
    assert [(s["id"], s["x"], s["y"]) for s in floor["spots"]] == [(s["id"], s["x"], s["y"]) for s in ui.land_floor("coast", seed=3, id="n")["spots"]]
    own = ui.world_validate({**spec, "floors": [{"id": "n", "land": {"theme": "desert"}, "spots": [{"id": "x", "x": 64, "y": 64, "label": "x"}]}]})["floors"][0]
    assert [s["id"] for s in own["spots"]] == ["x"] and own["props"] == ui.land_floor("desert", id="n")["props"]
    for bad in ({"land": {"theme": "meadow", "color": "red"}}, {"land": "meadow"}, {"land": {}, "classroom": {}}, {"land": {}, "width": 64}):
        with pytest.raises(ValueError):
            ui.world_validate({**spec, "floors": [{"id": "n", **bad}]})
    school = ui.world_css(ui.example_data("school"))
    assert "data-kind=water" not in school and "svg+xml" not in school                # no land rule leaks into a world without lands


def test_the_overworld_example_swaps_objects_and_ships_only_the_kinds_it_uses():
    spec = ui.example_data("overworld")
    world = ui.world_validate(spec)
    assert [f["id"] for f in world["floors"]] == ["meadow", "forest", "mountain", "desert", "coast", "castle", "real"] and ui.world_validate(world) == world
    css = ui.world_css(spec, base=False)                                             # only this world's rules, not the fixed ones
    for kind in ("grass", "sand", "road", "water", "tree", "cactus", "mountain", "house", "castle"):
        assert f".ui-prop[data-kind={kind}]" in css, kind
    assert ".ui-prop[data-kind=bridge]" not in css and ".ui-prop[data-kind=desk]" not in css
    assert "center/contain no-repeat" in css and css.count("0 0/var(--tile) var(--tile)") >= 5       # the castle once, the rest once per tile
    html = ui.world_html(spec)
    assert html.count('class="ui-floor"') == 7 and 'data-real style="width:384px;height:384px' in html and world["floors"][-1]["real"] is True and "ui-world-goto" in html and "🧭" in html and 'data-t="home"' in html
    assert ui.world_document(spec) == ui.world_document(ui.example_data("overworld"))
    assert ui.example_data("overworld") == json.loads(json.dumps(ui.EXAMPLES["overworld"]))


def test_a_real_floor_asks_for_a_photo_or_camera_and_other_worlds_do_not():
    floor = {"id": "r", "label": "R", "width": 128, "height": 128, "tile": 32, "real": True, "player": {"emoji": "🙂", "x": 48, "y": 48},
             "spots": [{"id": "a", "label": "A", "x": 64, "y": 64, "body": "b"}]}
    spec = {"schema": "web-ui-world/1", "id": "w", "floors": [floor]}
    world = ui.world_validate(spec)
    assert world["floors"][0]["real"] is True and ui.world_validate(world) == world
    assert "real" not in ui.world_validate({**spec, "floors": [{k: v for k, v in floor.items() if k != "real"}]})["floors"][0]
    html = ui.world_html(spec)
    assert 'data-real style="width:128px' in html and 'class="ui-world-real" data-real hidden' in html and 'data-t="backdrop"' in html
    plain = ui.world_html({**spec, "floors": [{k: v for k, v in floor.items() if k != "real"}]})
    assert 'data-real style=' not in plain and 'class="ui-world-real"' not in plain                 # no button where no floor is real
    land = ui.world_validate({"schema": "web-ui-world/1", "id": "l", "floors": [{"id": "x", "land": {"theme": "meadow"}, "real": True}]})
    assert land["floors"][0]["real"] is True and land["floors"][0]["props"]                          # a land can be real too: props over the picture
    for bad in ("yes", 1, None, []):
        with pytest.raises(ValueError):
            ui.world_validate({**spec, "floors": [{**floor, "real": bad}]})


def test_node26_walks_a_land_like_python(tmp_path):
    node = _node26()
    floor = ui.land_floor("forest", seed=9)
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    cases = [[blocked, floor["tile"], [floor["player"]["x"], floor["player"]["y"]], [s["x"], s["y"]]] for s in floor["spots"]]
    cases.append([blocked, floor["tile"], [floor["player"]["x"], floor["player"]["y"]], [48, 48]])
    module = tmp_path / "land.mjs"
    module.write_text(ui.WORLD_JS.removesuffix("bindWorlds();\n") + "\nconst cases=" + json.dumps(cases) + ";console.log(JSON.stringify(cases.map(([r,t,a,b])=>gridRoute(r,t,a,b))))\n")
    for (rows, tile, a, b), actual in zip(cases, json.loads(subprocess.check_output([node, str(module)], text=True))):
        want = ui.world_route_points(rows, tile, a, b)
        assert len(actual) == len(want) and all(g == pytest.approx(w, abs=1e-9) for g, w in zip(actual, want))
