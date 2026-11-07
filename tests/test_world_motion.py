"""Python oracle and emitted browser projection: no browser/Python runtime dependency."""
import json
import math
import subprocess

import pytest
from support import node26
import web_ui as ui


def test_walk_constant_velocity_clamp_and_hold():
    s = ui.world_walk([10, 20], [70, 100], speed=10, at=5)
    assert s['duration'] == 10
    assert ui.world_motion_sample(s, 0) == [10, 20]
    assert ui.world_motion_sample(s, 10) == [40, 60]
    assert ui.world_motion_sample(s, 1e9) == [70, 100]
    assert ui.world_walk([0, 0], [-20, 2000], width=64, height=128)['to'] == [0, 128]
    still = ui.world_walk([3, 4], [3, 4])
    assert ui.world_motion_sample(still, 0) == [3, 4]


def test_retarget_pause_resume_and_frame_rate_independence():
    original = ui.world_walk([0, 0], [100, 0], speed=10)
    point = ui.world_motion_sample(original, 3)
    retarget = ui.world_walk(point, [30, 100], at=3, speed=10)
    assert ui.world_motion_sample(retarget, 3) == point
    # A pause is a frozen simulation clock. Resume uses elapsed, not wall time.
    for _ in range(60):
        assert ui.world_motion_sample(retarget, 3) == point
    assert ui.world_motion_sample(retarget, 5) == [30, 20]
    for fps in (24, 60, 144):
        for i in range(fps * 5):
            ui.world_motion_sample(retarget, i / fps)
        assert ui.world_motion_sample(retarget, 8) == [30, 50]


def test_seeded_villagers_continuous_bounded_and_exact_speed():
    for seed in range(20):
        path = ui.villager_path(seed, 128, 64, speed=17, stops=64)
        assert path == ui.villager_path(seed, 128, 64, speed=17, stops=64)
        assert path['keys'][0][1:] == path['keys'][-1][1:]
        assert len(path['keys']) == 130
        for a, b in zip(path['keys'], path['keys'][1:]):
            assert 0 <= b[1] <= 128 and 0 <= b[2] <= 64
            distance = math.dist(a[1:], b[1:])
            if distance:
                duration = (b[0] - a[0]) / 100 * path['duration']
                assert distance / duration == pytest.approx(17, abs=1e-9)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 10**1000, True, '3', None])
def test_nonfinite_or_non_numeric_inputs(bad):
    for call in (lambda: ui.world_walk([bad, 0], [1, 2]),
                 lambda: ui.world_walk([0, 0], [1, 2], speed=bad),
                 lambda: ui.world_motion_sample(ui.world_walk([0, 0], [1, 2]), bad),
                 lambda: ui.board_clock(bad, 0),
                 lambda: ui.travel_seconds(0, 0, 10, 10, bad)):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize('kwargs', [{'stops': 65}, {'seed': -1}, {'speed': 0}, {'width': 4097}, {'margin': 100}])
def test_plan_resource_bounds(kwargs):
    with pytest.raises(ValueError):
        ui.villager_path(**{'seed': 1, 'width': 128, 'height': 64, **kwargs})


@pytest.mark.parametrize('now,at,expected', [(600,630,30),(600.1,630,30), (629.999,630,1), (630,630,0), (630.001,630,1440), (1439.5,0,1)])
def test_daily_countdown_seconds_ceil_exact_target_and_tomorrow(now, at, expected):
    assert ui.minutes_until(now, at) == expected


@pytest.mark.parametrize('now,offset,clock,minutes', [(0,0,'00:00',0), (0,-60,'23:00',1380), (86399,540,'08:59',539+59/60)])
def test_clock_explicit_seconds_offset_and_day_rollover(now, offset, clock, minutes):
    result = ui.board_clock(now, offset)
    assert result['clock'] == clock
    assert result['minutes'] == pytest.approx(minutes)


def test_html_safe_accessible_and_offset_opt_in():
    value = ui.example_data('world')
    value['board']['offset_minutes'] = 540
    html = ui.world_html(value)
    assert 'data-offset="540"' in html and 'aria-live="off"' in html
    assert 'aria-label="自分"' in html
    assert 'type="number"' in html and 'ここへ歩く' in html and 'aria-pressed="false"' in html
    assert ui.world_validate(ui.world_validate(value)) == ui.world_validate(value)
    assert 'animation-play-state:paused' in ui.world_css(value)


def test_node26_projection_matches_python_oracle(tmp_path):
    node = node26() or pytest.skip('existing Node 26+ required; no installation')
    segments = [ui.world_walk([i, i*2], [100-i, 70-i], at=i/3, speed=10+i) for i in range(20)]
    segments += [ui.world_walk([0, 0], [0, 0], at=2)]
    cases = [[s, t] for s in segments for t in (0, s['at'], s['at'] + s['duration']/2, s['at']+s['duration'], 1e9)]
    boards = [[0,-60], [86399.9,540], [1800000001,0]]
    countdowns = [[600,630], [629.999,630], [630,630], [630.001,630], [1439.5,0]]
    module = tmp_path / 'motion.mjs'
    module.write_text(ui.WORLD_JS.removesuffix('bindWorlds();\n') + '\nconsole.log(JSON.stringify({samples:' + json.dumps(cases) + '.map(([s,t])=>motionSample(s,t)),boards:' + json.dumps(boards) + '.map(([n,o])=>boardClock(n,o)),countdowns:' + json.dumps(countdowns) + '.map(([n,a])=>minutesUntil(n,a)),walk:motionWalk([10,20],[70,100],5,10,1024,768)}));')
    result = json.loads(subprocess.check_output([node, str(module)], text=True))
    for actual, (s, t) in zip(result['samples'], cases):
        assert actual == pytest.approx(ui.world_motion_sample(s, t), abs=1e-10)
    for actual, (n,o) in zip(result['boards'], boards):
        expected = ui.board_clock(n,o)
        assert actual['clock'] == expected['clock']
        assert actual['minutes'] == pytest.approx(expected['minutes'])
    assert result['countdowns'] == [ui.minutes_until(n,a) for n,a in countdowns]
    assert result['walk'] == ui.world_walk([10,20], [70,100], at=5, speed=10)


def test_node26_interaction_harness(tmp_path):
    from pathlib import Path
    node = node26() or pytest.skip('existing Node 26+ required; no installation')
    module = tmp_path / 'interaction.mjs'
    source = ui.WORLD_JS.removesuffix('bindWorlds();\n')
    module.write_text(source + (Path(__file__).parent / 'fixtures/world_motion_harness.js').read_text())
    output = subprocess.check_output([node, str(module)], text=True, stderr=subprocess.STDOUT)
    assert 'motion interaction harness passed' in output
