"""Golden behavior and cross-runtime checks for the Flutter successor tools."""
import datetime as dt
import json
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import web_ui as u


def js_call(module, expression, payload):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('play.js', 'studio-audio.js', 'composition.js', 'timeline.js'):
            (root / name.replace('.js', '.mjs')).write_text(u.js_modules()[name], encoding='utf-8')
        script = ('await import(' + json.dumps((root / 'composition.mjs').as_uri()) + ');'
                  'const m=await import(' + json.dumps((root / module.replace('.js', '.mjs')).as_uri()) + ');'
                  'let text="";for await(const c of process.stdin)text+=c;const data=JSON.parse(text);'
                  'console.log(JSON.stringify(' + expression + '));')
        result = subprocess.run([node, '--input-type=module', '-e', script], input=json.dumps(payload),
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


def test_garden_golden_rewards_noop_and_replay():
    assert u.play_random(42) == 11355432
    r = u.counter_garden(42, [1] * 20)
    assert r['mask'] == '21040318072b0018'
    assert r['rewards'] == ['⭐', '🎵']
    assert r['value'] == 20 and len(r['cells']) == 16
    assert u.counter_garden(42, [10] * 10) == {**u.counter_garden(42, [10] * 11), 'actions': [10] * 10}
    assert u.counter_garden(42, [1, -1])['value'] == 0
    assert u.counter_garden(42, [])['mask'] == '0000000000000000'
    for seed, actions in [(True, []), (2**32, []), (1, [True]), (1, [2]), (1, [1]*4097), (1, None)]:
        with pytest.raises(ValueError):
            u.counter_garden(seed, actions)


def test_garden_and_quest_cross_runtime():
    rng = random.Random(20261103)
    cases = [[rng.randrange(2**32), [rng.choice([-10,-5,-1,1,5,10]) for _ in range(rng.randrange(150))]] for _ in range(250)]
    assert js_call('play.js', 'data.map(c=>m.counterGarden(...c))', cases) == [u.counter_garden(*c) for c in cases]
    rounds = [[seed, i] for seed in (0, 1, 42, 2**32-1) for i in range(36)]
    assert js_call('play.js', 'data.map(c=>m.ironyRound(...c))', rounds) == [u.irony_round(*c) for c in rounds]
    for seed in (0, 1, 42):
        cards = [u.irony_round(seed, i)['card'] for i in range(60)]
        assert all(a != b for a,b in zip(cards,cards[1:]))
        assert all(len(set(cards[i:i+6])) == 6 for i in range(0,60,6))


def test_quest_replay_rejects_modified_shape():
    cases = [None, {}, {'schema': u.PLAY_SCHEMA, 'seed': 42, 'actions': [], 'answers': [3]},
             {'schema': u.PLAY_SCHEMA, 'seed': 42, 'actions': [True], 'answers': []},
             {'schema': u.PLAY_SCHEMA, 'seed': 42, 'actions': [], 'answers': [], 'reward': 999}]
    assert js_call('play.js', 'data.map(c=>{try{m.validateReplay(c);return false}catch{return true}})', cases) == [True]*len(cases)


def test_audio_score_golden_and_bounds():
    assert u.studio_audio_plan('A4 C5',120,8) == [
        {'note':'A4','midi':69,'start_us':0,'duration_us':250000},
        {'note':'C5','midi':72,'start_us':250000,'duration_us':250000}]
    assert u.progression_notes('C','I V vi IV') == ['C4','E4','G4','G4','B4','D5','A4','C5','E5','F4','A4','C5']
    for text,bpm,unit in [('',120,8),('C4',True,8),('C4',120,True),('C-1',300,4),('G#9',120,8),('C4 '*257,120,8)]:
        if text == 'C-1':
            assert u.studio_audio_plan(text,bpm,unit)[0]['midi'] == 0
        else:
            with pytest.raises(ValueError):
                u.studio_audio_plan(text,bpm,unit)
    with pytest.raises(ValueError):
        u.progression_notes('C','not-a-chord')


def test_audio_cross_runtime_and_player_stop_race():
    rng=random.Random(73)
    cases=[[' '.join(rng.choice(['C3','d4','F#4','Gb5','A4','C-1']) for _ in range(8)),rng.randrange(30,301),rng.choice([4,8])] for _ in range(300)]
    assert js_call('studio-audio.js','data.map(c=>m.audioPlan(...c))',cases) == [u.studio_audio_plan(*c) for c in cases]
    cases=[[key,prog,minor,4] for key in u.SEED_KEYS for minor in (False,True) for prog in ('I V vi IV','ii7 V7 Imaj7','i iv v i')]
    assert js_call('studio-audio.js','data.map(c=>m.progressionNotes(...c))',cases) == [u.progression_notes(k,p,minor=mi,octave=o) for k,p,mi,o in cases]
    expression='''await (async()=>{let resolve,voices=0,disposed=0,calls=[];const tone={start:async()=>{},now:()=>10,Synth:class{constructor(){voices++}toDestination(){return this}triggerAttackRelease(...a){calls.push(a)}dispose(){disposed++}}};const p=m.createAudioPlayer(()=>new Promise(r=>resolve=r));const pending=p.play(data);p.stop();resolve(tone);await pending;const q=m.createAudioPlayer(async()=>tone);await q.play(data);q.stop();return{voices,disposed,calls}})()'''
    result=js_call('studio-audio.js',expression,u.studio_audio_plan('A4 C5'))
    assert result['voices']==result['disposed']==1
    assert result['calls'][0] == ['A4',0.2125,10.05]


def test_timeline_is_utc_ordered_even_across_local_dates():
    rows=[{'id':'ny','title':'NY','zone':'America/New_York','utc_ms':1793512800000},
          {'id':'jp','title':'JP','zone':'Asia/Tokyo','utc_ms':1793509200000}]
    expected=u.timeline_events(rows)
    assert [r['id'] for r in expected]==['jp','ny']
    assert [r['id'] for r in js_call('timeline.js','m.timelineEvents(data)',rows)]==['jp','ny']
    assert u.timeline_wall_to_utc('2026-11-03T12:00','Asia/Tokyo')==1793674800000
    assert u.timeline_wall_to_utc('2026-11-01T01:30','America/New_York',fold=1)-u.timeline_wall_to_utc('2026-11-01T01:30','America/New_York',fold=0)==3600000
    for wall,zone in [('2026-03-08T02:30','America/New_York'),('2026-11-01T01:30','America/New_York'),('2026-02-30T12:00','Asia/Tokyo')]:
        with pytest.raises(ValueError):u.timeline_wall_to_utc(wall,zone)
    cases=[[wall,zone,fold] for wall,zone in [('2026-11-03T12:00','Asia/Tokyo'),('2026-11-01T01:30','America/New_York'),('2026-04-05T01:45','Australia/Lord_Howe')] for fold in (0,1)]
    assert js_call('timeline.js','data.map(c=>m.wallToUtc(...c))',cases)==[u.timeline_wall_to_utc(w,z,fold=f) for w,z,f in cases]
    for rows in [[{'id':'x','title':'x','zone':'../UTC','utc_ms':1793674800000}],[{'id':'x','title':'x','zone':'UTC','utc_ms':True}]]:
        with pytest.raises(ValueError):u.timeline_events(rows)


def test_optional_audio_not_in_default_shared_modules_and_no_runtime_network_in_games():
    assert not any('tone-studio.min.js' in path for path in u.example_pages())
    assert 'tone-studio.min.js' not in u.play_document()
    for name in ('play.js','timeline.js'):
        for forbidden in ('fetch(', 'localStorage', 'sessionStorage', 'XMLHttpRequest'):
            assert forbidden not in u.js_modules()[name]
