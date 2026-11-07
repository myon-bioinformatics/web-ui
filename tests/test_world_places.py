"""Real places in miniature: the ``place`` floor turns latitude/longitude points into a tile grid (``web_ui.place_floor``), and the ``cities`` example
(Parallel Tokyo, Reverse London and Fake Paris) is built from it. The coordinates are approximate, so the checks are about relative positions and walking, not metres."""
import copy, importlib.util, json, math, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("web_ui_places", ROOT / "web_ui.py")
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)


def pt(id, lat, lon, **over):
    return {"id": id, "label": id.upper(), "lat": lat, "lon": lon, **over}


# Two points 1 km apart on a meridian (about 0.00899 degrees of latitude), at 100 m per tile.
NORTH, SOUTH = pt("a", 35.0090, 139.0), pt("b", 35.0000, 139.0)


def cell(floor, spot_id):
    spot = next(s for s in floor["spots"] if s["id"] == f"{floor['id']}-{spot_id}")
    return spot["x"] // floor["tile"], spot["y"] // floor["tile"]


def walkable(floor):
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    start = (floor["player"]["x"] // floor["tile"], floor["player"]["y"] // floor["tile"])
    return ui.world_reach(blocked, start)


def test_points_land_on_tiles_from_their_distance():
    floor = ui.place_floor([NORTH, SOUTH], meters=100)
    (ax, ay), (bx, by) = cell(floor, "a"), cell(floor, "b")
    assert ax == bx
    assert by - ay == 10                                         # 1 km at 100 m per tile; north is up
    assert floor["width"] % floor["tile"] == 0 and floor["height"] % floor["tile"] == 0
    assert floor["spots"][0]["x"] == int((ax + .5) * floor["tile"])   # a spot stands in the middle of its tile


def test_east_is_right_and_longitude_shrinks_with_latitude():
    equator = ui.place_floor([pt("w", 0.0, 10.0), pt("e", 0.0, 10.0090)], meters=100)
    north = ui.place_floor([pt("w", 60.0, 10.0), pt("e", 60.0, 10.0090)], meters=100)
    assert cell(equator, "e")[0] - cell(equator, "w")[0] == 10   # 0.009 degrees of longitude is about 1 km at the equator ...
    assert cell(north, "e")[0] - cell(north, "w")[0] == 5        # ... and half of that at 60 degrees north


def test_same_arguments_give_the_same_floor_and_it_validates():
    one = ui.place_floor([NORTH, SOUTH], meters=100, links=[["a", "b"]], id="p", label="P")
    assert one == ui.place_floor([NORTH, SOUTH], meters=100, links=[["a", "b"]], id="p", label="P")
    ui.world_validate({"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [one]})


def test_two_points_on_one_tile_take_two_tiles_and_the_earlier_one_keeps_its_own():
    a, b = pt("a", 35.0, 139.0), pt("b", 35.00001, 139.00001)                                  # a few metres apart: the same tile at 500 m
    far = pt("far", 35.1, 139.0)
    one, other = ui.place_floor([a, b, far], meters=500), ui.place_floor([b, a, far], meters=500)
    assert cell(one, "a") == cell(other, "b")                                                 # whoever comes first keeps the tile
    assert cell(one, "b") != cell(one, "a") and cell(other, "a") != cell(other, "b")
    assert max(abs(cell(one, "a")[i] - cell(one, "b")[i]) for i in (0, 1)) == 1                # and the other is one tile away
    assert len({cell(one, k) for k in ("a", "b", "far")}) == 3


def test_a_maps_url_is_a_point_like_any_other():
    a = ui.place_floor([pt("a", 35.0090, 139.0), pt("b", 35.0, 139.0)], meters=100)
    b = ui.place_floor([{"id": "a", "label": "A", "maps": "https://www.google.com/maps/@35.0090,139.0,17z"}, pt("b", 35.0, 139.0)], meters=100)
    assert a["spots"] == b["spots"]
    with pytest.raises(ValueError, match="no coordinates"):
        ui.place_floor([{"id": "a", "label": "A", "maps": "https://example.test/"}], meters=100)


def test_an_area_is_the_box_tolerance_area_gives():
    centre = (35.0, 139.0)
    floor = ui.place_floor([pt("c", *centre)], meters=100, area={"center": list(centre), "radius": 1000})
    box = ui.tolerance_area(*centre, 1000)
    height_m = (box["north"] - box["south"]) * math.pi / 180 * ui.EARTH_RADIUS_M
    assert floor["height"] // floor["tile"] == int(height_m // 100) + 1          # the map is the box, with no margin
    assert abs(cell(floor, "c")[1] - floor["height"] // floor["tile"] // 2) <= 1  # the centre is in the middle
    with pytest.raises(ValueError, match="outside the area"):
        ui.place_floor([pt("far", 36.0, 139.0)], meters=100, area={"center": list(centre), "radius": 1000})
    with pytest.raises(ValueError, match="date line"):
        ui.place_floor([pt("x", 0.0, 179.9999)], meters=100, area={"center": [0.0, 179.9999], "radius": 50000})


RIVER = {"line": [[35.0045, 138.99], [35.0045, 139.01]], "width": 2}         # between a (north) and b (south), all the way across


def test_a_river_cuts_the_place_until_a_link_makes_a_bridge():
    with pytest.raises(ValueError, match="cut off by water from a: b"):
        ui.place_floor([NORTH, SOUTH], meters=100, rivers=[RIVER])
    floor = ui.place_floor([NORTH, SOUTH], meters=100, rivers=[RIVER], links=[["a", "b"]])
    kinds = {p["kind"] for p in floor["props"]}
    assert {"water", "bridge", "road"} <= kinds
    assert cell(floor, "b") in walkable(floor)
    bridge = next(p for p in floor["props"] if p["kind"] == "bridge")
    tile = floor["tile"]
    assert all(floor["props"].index(bridge) > floor["props"].index(w) for w in floor["props"] if w["kind"] == "water")   # laid after the water
    assert bridge["w"] % tile == 0 and bridge["h"] % tile == 0


def test_no_spot_stands_in_the_water():
    floor = ui.place_floor([pt("a", 35.0045, 139.0), pt("b", 35.0090, 139.0)], meters=100, rivers=[RIVER], links=[["a", "b"]])   # a is on the river
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    for spot in floor["spots"]:
        x, y = spot["x"] // floor["tile"], spot["y"] // floor["tile"]
        assert blocked[y][x] == "0"


def test_roads_are_few_props_not_one_per_tile():
    pts = [pt("a", 35.0090, 139.0), pt("b", 35.0, 139.0), pt("c", 35.0, 139.0090)]
    floor = ui.place_floor(pts, meters=50, links=[["a", "b"], ["b", "c"]])
    assert len(floor["props"]) <= 4                              # grass, and the two roads (the corner is shared)


def test_mistakes_say_what_is_wrong():
    ok = [NORTH, SOUTH]
    for bad, message in [
        (dict(points=[]), "1..64 points"),
        (dict(points=[NORTH, NORTH]), "unique"),
        (dict(points=[pt("A", 1, 1)]), "unique lowercase token"),
        (dict(points=[pt("a", 91, 0)]), "between -90 and 90"),
        (dict(points=[{"id": "a", "label": "A", "lat": 1}]), "either lat and lon or maps"),
        (dict(points=[pt("a", 1, 1, color="red")]), "a point has"),
        (dict(points=[pt("a", 1, 1, flip="")]), "flip must"),
        (dict(points=[pt("a", 1, 1, sign="neon")]), "sign is one of led, wood"),
        (dict(points=[pt("a", 1, 1, sign="led")]), "needs a point that is not a sign"),
        (dict(points=[NORTH, pt("s", 35.0045, 139.0, sign="led")], start="s"), "start is the id"),
        (dict(points=[NORTH, pt("s", 35.0045, 139.0, sign="led")], links=[["a", "s"]]), "two different point ids"),
        (dict(points=ok, scatter={"kind": "tree", "every": 4, "seed": 1}), "scatter is"),
        (dict(points=ok, scatter={"kind": "road", "every": 4, "seed": 1}), "scatter is"),
        (dict(points=ok, scatter={"kind": "fire", "every": 1, "seed": 1}), "every must be an integer from 2 to 64"),
        (dict(points=ok, scatter={"kind": "fire", "every": 4}), "scatter is"),
        (dict(points=[pt("a", 1, 1, category="Big")]), "lowercase token"),
        (dict(points=ok, links=[["a", "zzz"]]), "two different point ids"),
        (dict(points=ok, links=[["a", "a"]]), "two different point ids"),
        (dict(points=ok, start="zzz"), "start is the id"),
        (dict(points=ok, rivers=[{"line": [[1, 1]], "width": 1}]), "a river is"),
        (dict(points=ok, rivers=[{"line": [[35, 139], [35.1, 139]], "width": 9}]), "width must be an integer from 1 to 8"),
        (dict(points=ok, meters=7), "meters must be an integer from 8 to 2000"),
        (dict(points=ok, meters=8), "4096 units"),
        (dict(points=ok, tile=20), "multiple of 8"),
    ]:
        with pytest.raises(ValueError, match=message):
            ui.place_floor(**bad)


def test_scatter_puts_one_decoration_in_each_block_on_a_free_tile_and_is_repeatable():
    pts = [pt("a", 35.0090, 139.0), pt("b", 35.0, 139.0)]
    scatter = {"kind": "fire", "every": 4, "seed": 7}
    floor = ui.place_floor(pts, meters=100, rivers=[RIVER], links=[["a", "b"]], scatter=scatter)
    assert floor == ui.place_floor(pts, meters=100, rivers=[RIVER], links=[["a", "b"]], scatter=scatter)
    assert floor != ui.place_floor(pts, meters=100, rivers=[RIVER], links=[["a", "b"]], scatter={**scatter, "seed": 8})
    tile = floor["tile"]
    fires = [(p["x"] // tile, p["y"] // tile) for p in floor["props"] if p["kind"] == "fire"]
    assert all(p["w"] == p["h"] == tile for p in floor["props"] if p["kind"] == "fire")
    cols, rows = floor["width"] // tile, floor["height"] // tile
    blocks = {(x // 4, y // 4) for x, y in fires}
    assert len(blocks) == len(fires)                                              # at most one in a block ...
    assert len(fires) >= (cols // 4) * (rows // 4) - 2                           # ... and nearly every block has one (a block may be all water)
    others = {(p["x"] // tile + i, p["y"] // tile + j) for p in floor["props"] if p["kind"] in ("water", "road", "bridge")
              for i in range(p["w"] // tile) for j in range(p["h"] // tile)}
    spots = {(s["x"] // tile, s["y"] // tile) for s in floor["spots"]}
    assert not set(fires) & (others | spots)                                      # never on a road, the river or a spot
    assert cell(floor, "b") in walkable(floor)                                    # and a fire is only a decoration


def test_a_flip_is_kept_through_validation_and_written_as_a_second_face():
    floor = ui.place_floor([pt("a", 35.0, 139.0, flip="🐉"), pt("b", 35.1, 139.0)], meters=500, id="p")
    assert [s.get("flip") for s in floor["spots"]] == ["🐉", None]
    world = ui.world_validate({"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [floor]})
    assert world["floors"][0]["spots"][0]["flip"] == "🐉" and "flip" not in world["floors"][0]["spots"][1]
    html = ui.world_html({"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [floor]})
    assert 'data-flip="🐉"' in html and html.count("data-flip=") == 1


def test_a_sign_is_a_small_board_on_the_nearest_tile_corner_and_takes_no_tile():
    floor = ui.place_floor([NORTH, SOUTH, pt("board", 35.0045, 139.0, category="sign", sign="led", label="◀ A | B ▶")], meters=100, id="p")
    tile = floor["tile"]
    board = next(s for s in floor["spots"] if s["id"] == "p-board")
    assert board["sign"] == "led" and board["x"] % tile == 0 and board["y"] % tile == 0
    (ax, ay), (bx, by) = cell(floor, "a"), cell(floor, "b")
    assert ay < board["y"] // tile <= by and abs(board["y"] // tile - (ay + by + 1) / 2) <= 1          # half way between the two stations
    assert [s["id"] for s in floor["spots"]] == ["p-a", "p-b", "p-board"]                                  # tile points first, then the corners
    taken = {(s["x"] // tile, s["y"] // tile) for s in floor["spots"] if "sign" not in s}
    assert len(taken) == 2                                                                                  # a sign does not use up a tile
    one = ui.place_floor([NORTH, pt("s1", 35.0045, 139.0, sign="led"), pt("s2", 35.0045, 139.0, sign="wood")], meters=100)
    corners = {(s["x"], s["y"]) for s in one["spots"] if "sign" in s}
    assert len(corners) == 2                                                                                # two signs never share a corner


def test_a_sign_in_the_middle_of_a_river_moves_to_the_bank_and_is_walkable():
    wide = {"line": [[35.0045, 138.99], [35.0045, 139.01]], "width": 4}
    floor = ui.place_floor([NORTH, SOUTH, pt("s", 35.0045, 139.0, sign="wood")], meters=100, rivers=[wide], links=[["a", "b"]])
    tile = floor["tile"]
    sign = next(s for s in floor["spots"] if "sign" in s)
    blocked = ui.world_blocked(floor["width"], floor["height"], tile, floor["props"])
    around = [(sign["x"] // tile + dx, sign["y"] // tile + dy) for dx in (-1, 0) for dy in (-1, 0)]
    assert any(blocked[y][x] == "0" for x, y in around)                                                     # it touches dry land


def test_any_spot_may_be_a_sign_and_the_page_draws_it_as_a_board_on_a_dot():
    def world(sign):
        return {"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [{"id": "f", "label": "F", "width": 128, "height": 128,
                "spots": [{"id": "s", "x": 64, "y": 64, "label": "◀ 出口", "sign": sign}]}]}
    html = ui.world_html(world("led"))
    assert 'data-sign="led"' in html and "ui-spot[data-sign=led]" in ui.world_css(world("led")) + ui.bundled_css()
    assert 'data-sign="wood"' in ui.world_html(world("wood"))
    with pytest.raises(ValueError, match="sign is one of led, wood"):
        ui.world_validate(world("neon"))


def test_json_alone_asks_for_a_place_and_unknown_keys_are_refused():
    spec = {"schema": ui.WORLD_SCHEMA, "id": "w", "floors": [{"id": "here", "label": "Here", "place": {"points": [NORTH, SOUTH], "meters": 100}}]}
    world = ui.world_validate(spec)
    assert world["floors"][0]["spots"][0]["id"] == "here-a"
    bad = copy.deepcopy(spec)
    bad["floors"][0]["place"]["zoom"] = 3
    with pytest.raises(ValueError, match="a place floor has"):
        ui.world_validate(bad)


# --- the two cities ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cities():
    world = ui.world_validate(ui.example_data("cities"))
    return {f["id"]: f for f in world["floors"]}


def by_id(floor):
    return {s["id"].split("-", 1)[1]: s for s in floor["spots"]}


def test_the_cities_are_three_floors_with_every_spot_walkable(cities):
    assert list(cities) == ["tokyo", "london", "paris"]
    for floor in cities.values():
        reach = walkable(floor)
        assert len(floor["props"]) <= 512 and len(floor["spots"]) <= 64
        tile = floor["tile"]
        for spot in floor["spots"]:
            if "sign" in spot:                                                                   # a sign sits on a corner: it touches four tiles
                assert spot["x"] % tile == 0 and spot["y"] % tile == 0, spot["id"]
                around = [(spot["x"] // tile + dx, spot["y"] // tile + dy) for dx in (-1, 0) for dy in (-1, 0)]
                assert any(c in reach for c in around), spot["id"]
            else:
                assert (spot["x"] // tile, spot["y"] // tile) in reach, spot["id"]
        assert len({(s["x"], s["y"]) for s in floor["spots"]}) == len(floor["spots"])          # no two spots on one tile or corner


def test_tokyo_station_has_six_exits_laid_out_like_the_building(cities):
    spots = by_id(cities["tokyo"])
    exits = {k: v for k, v in spots.items() if v["category"] == "exit"}
    assert sorted(exits) == ["marunouchi-c", "marunouchi-n", "marunouchi-s", "yaesu-c", "yaesu-n", "yaesu-s"]
    for side in ("marunouchi", "yaesu"):
        assert exits[f"{side}-n"]["y"] < exits[f"{side}-c"]["y"] < exits[f"{side}-s"]["y"]     # north above south
    for part in "ncs":
        assert exits[f"marunouchi-{part}"]["x"] < exits[f"yaesu-{part}"]["x"]                   # Marunouchi is the west side
    assert cities["tokyo"]["player"]["x"] // 32 == exits["marunouchi-c"]["x"] // 32


def test_tokyo_has_no_facility_names_and_the_stations_are_where_they_are(cities):
    spots = by_id(cities["tokyo"])
    assert {v["category"] for v in spots.values()} == {"exit", "station", "sign"}
    stations = {k: v for k, v in spots.items() if v["category"] == "station"}
    assert len(stations) == 13
    centre = spots["marunouchi-c"]
    tile = cities["tokyo"]["tile"]
    for key, spot in stations.items():                           # every one is within two kilometres of the station (the floor is 32 m a tile)
        metres = math.hypot(spot["x"] - centre["x"], spot["y"] - centre["y"]) / tile * 32
        assert metres < 2000, key
    assert stations["shimbashi"]["y"] > stations["yurakucho"]["y"] > stations["otemachi"]["y"]   # Shimbashi is south of Yurakucho, south of Otemachi
    assert stations["kanda"]["y"] < stations["otemachi"]["y"]                                      # Kanda is north of Otemachi
    assert stations["nihombashi"]["x"] > centre["x"] > stations["nijubashimae"]["x"]               # east of the station, and west of it


def test_london_has_the_main_termini_the_stations_beside_them_and_famous_places(cities):
    floor = cities["london"]
    spots = by_id(floor)
    kinds = {}
    for key, spot in spots.items():
        kinds.setdefault(spot["category"], []).append(key)
    assert sorted(kinds) == ["famous", "sight", "sign", "station", "terminus"]
    assert len(kinds["terminus"]) == 13
    for key in ("kings-cross", "paddington", "waterloo", "victoria", "liverpool-street", "london-bridge", "euston", "charing-cross"):
        assert key in kinds["terminus"]
    assert {"downing-street", "bank-of-england", "old-bailey"} <= set(kinds["famous"])          # well known, not for the tourists
    assert spots["paddington"]["x"] < spots["kings-cross"]["x"] < spots["liverpool-street"]["x"]   # west to east
    assert spots["waterloo"]["y"] > spots["charing-cross"]["y"]                                    # south of the river
    assert spots["london-bridge"]["y"] > spots["cannon-street"]["y"]


def test_the_thames_is_between_waterloo_and_charing_cross_with_a_bridge(cities):
    floor = cities["london"]
    kinds = {p["kind"] for p in floor["props"]}
    assert {"water", "bridge"} <= kinds
    blocked = ui.world_blocked(floor["width"], floor["height"], floor["tile"], floor["props"])
    spots = by_id(floor)
    tile = floor["tile"]
    (x0, x1), (y0, y1) = (sorted(spots[k]["x"] // tile for k in ("waterloo", "charing-cross")), sorted(spots[k]["y"] // tile for k in ("waterloo", "charing-cross")))
    assert any(blocked[y][x] == "1" for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)), "water lies between them"
    assert cell(floor, "charing-cross") in walkable(floor) and cell(floor, "waterloo") in walkable(floor)    # and a bridge joins them


def test_fake_paris_has_its_stations_a_seine_with_bridges_and_a_fire_in_each_block(cities):
    floor = cities["paris"]
    spots = by_id(floor)
    kinds = {}
    for key, spot in spots.items():
        kinds.setdefault(spot["category"], []).append(key)
    assert sorted(kinds) == ["famous", "sight", "sign", "station", "terminus"] and len(kinds["terminus"]) == 6
    assert spots["gare-du-nord"]["y"] < spots["gare-de-lyon"]["y"] < spots["montparnasse"]["y"] + 1              # north to south
    assert spots["saint-lazare"]["x"] < spots["gare-du-nord"]["x"] < spots["gare-de-lyon"]["x"]                  # west to east
    assert spots["eiffel"]["x"] < spots["notre-dame"]["x"] < spots["bastille"]["x"]
    assert {"water", "bridge", "fire"} <= {p["kind"] for p in floor["props"]}
    fires = [p for p in floor["props"] if p["kind"] == "fire"]
    assert 20 <= len(fires) <= 40
    tile = floor["tile"]
    assert len({(p["x"] // tile // 8, p["y"] // tile // 8) for p in fires}) == len(fires)                         # one per block of eight tiles


def test_the_nogard_sign_stands_by_a_station_and_turns_into_a_dragon(cities):
    floor = cities["london"]
    sign = by_id(floor)["nogard"]
    assert (sign["label"], sign["flip"], sign["category"], sign["sign"]) == ("nogard", "🐉", "sign", "wood")
    assert sign["label"][::-1] == "dragon"                                                                        # dragon, backwards
    stations = [s for s in floor["spots"] if s["category"] in ("terminus", "station")]            # the stations, not the other signs
    tile = floor["tile"]
    nearest = min(math.hypot(s["x"] - sign["x"], s["y"] - sign["y"]) for s in stations) / tile
    assert nearest <= 3                                                                                           # within three tiles (450 m)
    assert len([s for s in floor["spots"] if "flip" in s]) == 1
    assert sign["x"] % tile == 0 and sign["y"] % tile == 0                                                        # on a corner of the grid


def test_the_front_page_and_the_cli_carry_the_cities():
    page = ui.example_pages()["index.html"]
    for text in ('id="cities"', "丸の内中央口", "リバースロンドン", "Fake Paris", "Parallel Tokyo", 'data-category="exit"', 'data-category="terminus"',
                 'data-flip="🐉"'):
        assert text in page
    spec = subprocess.run([sys.executable, str(ROOT / "web_ui.py"), "--example", "cities"], capture_output=True, text=True, check=True, encoding="utf-8").stdout
    assert json.loads(spec)["floors"][0]["place"]["points"][0]["id"] == "marunouchi-c"
    html = subprocess.run([sys.executable, str(ROOT / "web_ui.py"), "--world", "-"], input=spec, capture_output=True, text=True, check=True, encoding="utf-8").stdout
    assert "八重洲北口" in html and "タワー・ブリッジ" in html and "エッフェル塔" in html
