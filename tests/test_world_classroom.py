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
    assert set(record_demo.SCENES) >= {"pick", "avatar-text", "keys", "tap", "phone", "floors", "oneliner"}
    with pytest.raises(ValueError, match="unknown scene: nope"):
        record_demo.record(tmp_path, ["nope"])
    (tmp_path / "school-pick.gif").write_bytes(b"GIF89a")
    with pytest.raises(FileExistsError, match="--force"):
        record_demo.record(tmp_path, ["pick"])
    assert (tmp_path / "school-pick.gif").read_bytes() == b"GIF89a"
    with pytest.raises(SystemExit) as exit_info:
        record_demo.main([str(tmp_path), "--only", "pick"])
    assert exit_info.value.code == 1 and "refusing to overwrite" in capsys.readouterr().err
