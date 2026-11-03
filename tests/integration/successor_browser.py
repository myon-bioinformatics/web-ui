"""Real-browser successor acceptance checks. Audio is generated, not a human listening test."""
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import web_ui as u
from playwright.sync_api import sync_playwright, expect


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


class SuccessorBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        u.write_site(cls.tmp.name)
        assets=Path(os.environ.get('WEBUI_AUDIO_ASSETS',ROOT/'build/site/vendor'))
        if not (assets/'tone-studio.min.js').is_file():
            raise RuntimeError('Build the optional audio asset before this acceptance suite')
        shutil.copytree(assets,Path(cls.tmp.name)/'vendor',dirs_exist_ok=True)
        cls.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=cls.tmp.name))
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.origin=f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw=sync_playwright().start()
        options={'headless':True}
        if os.environ.get('WEBUI_CHROMIUM'):
            options.update(executable_path=os.environ['WEBUI_CHROMIUM'],args=['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        cls.browser=getattr(cls.pw,os.environ.get('WEBUI_BROWSER','chromium')).launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop();cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()

    def test_garden_rewards_replay_undo_and_irony_on_phones(self):
        for width in (320,390,1280):
            with self.subTest(width=width):
                page=self.browser.new_page(viewport={'width':width,'height':844})
                errors=[];external=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:external.append(r.url) if not r.url.startswith(self.origin) else None)
                page.goto(self.origin+'/examples/play-studio.html')
                for _ in range(20):page.locator('[data-delta="1"]').click()
                expect(page.locator('[data-value]')).to_contain_text('Count: 20')
                expect(page.locator('[data-rewards]')).to_contain_text('⭐ 🎵')
                page.locator('summary').click()
                page.locator('[data-export]').click();replay=page.locator('[data-replay]').input_value()
                expected=u.counter_garden(42,[1]*20)
                self.assertEqual(json.loads(replay)['actions'],expected['actions'])
                page.locator('[data-generated-export]').click()
                self.assertEqual(json.loads(page.locator('[data-generated]').inner_text())['specimen']['mask'],expected['mask'])
                reward_url=page.locator('[data-reward-links] a').first.get_attribute('href')
                before=page.locator('[data-garden]').inner_text()
                page.locator('[data-undo]').click();expect(page.locator('[data-value]')).to_contain_text('Count: 19')
                page.locator('[data-import]').click();self.assertEqual(page.locator('[data-garden]').inner_text(),before)
                for i in range(6):
                    card=u.irony_round(42,i)
                    choice=page.locator('[data-choices] button').nth(card['correct'])
                    # Center the real pointer target: headless Firefox's physical screen may be shorter than the emulated CSS viewport.
                    choice.evaluate("b=>b.scrollIntoView({block:'center',inline:'nearest'})")
                    page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    choice.click()
                    expect(page.locator('[data-score]')).to_have_text(f'{i+1} / {i+1}')
                    # Counter updates must not change an already answered quest card.
                    prompt=page.locator('[data-irony]').inner_text()
                    page.locator('[data-delta="-1"]').click()
                    self.assertEqual(page.locator('[data-irony]').inner_text(),prompt)
                    self.assertTrue(page.locator('[data-choices] button').first.is_disabled())
                    page.locator('[data-next]').click()
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                self.assertEqual(page.evaluate('localStorage.length+sessionStorage.length'),0)
                self.assertEqual(external,[]);self.assertEqual(errors,[])
                page.reload();expect(page.locator('[data-value]')).to_contain_text('Count: 0')
                page.goto(self.origin+'/examples/'+reward_url.removeprefix('./'))
                expect(page.locator('[data-ui-photo]')).to_have_attribute('data-armed','⭐')
                for index,glyph in enumerate(('👩\u200d💻','👨\u200d👩\u200d👧\u200d👦','🇯🇵','1️⃣')):
                    page.locator('[data-custom]').fill(glyph)
                    page.locator('[data-arm]').click()
                    expect(page.locator('[data-ui-photo]')).to_have_attribute('data-armed',glyph)
                    page.locator('[data-stage]').click(position={'x':40+index*45,'y':80})
                    self.assertEqual(page.locator('[data-ui-photo]').evaluate('b=>b.photo.studio.state.stamps.at(-1).emoji'),glyph)
                page.close()

    def test_timeline_local_entry_sorted_utc_and_dst_validation(self):
        page=self.browser.new_page(viewport={'width':320,'height':844},timezone_id='America/New_York')
        page.goto(self.origin+'/examples/timeline.html')
        form=page.locator('[data-add-event]')
        for title,wall,zone in [('Tokyo later','2026-11-03T12:00','Asia/Tokyo'),('UTC earlier','2026-11-03T01:00','UTC')]:
            form.locator('[name="title"]').fill(title);form.locator('[name="wall"]').fill(wall);form.locator('[name="zone"]').fill(zone);form.locator('button').click()
        self.assertTrue(page.locator('[data-event-list] li').first.inner_text().startswith('UTC earlier'))
        self.assertIn('Asia/Tokyo',page.locator('[data-event-list]').inner_text())
        self.assertEqual(page.locator('time').first.get_attribute('datetime'),'2026-11-03T01:00:00.000Z')
        form.locator('[name="title"]').fill('Ambiguous');form.locator('[name="wall"]').fill('2026-11-01T01:30');form.locator('[name="zone"]').fill('America/New_York');form.locator('button').click()
        expect(page.locator('[data-events-status]')).to_contain_text('occurs twice')
        form.locator('[name="fold"]').select_option('1');form.locator('button').click()
        self.assertEqual(page.locator('[data-event-list] li').count(),3)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320)
        page.close()

    def test_composition_notes_optional_audio_load_stop_and_real_signal(self):
        page=self.browser.new_page(viewport={'width':390,'height':844})
        errors=[];requests=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:print('audio console:',m.type,m.text) if m.type in ('warning','error') else None)
        page.on('request',lambda r:requests.append(r.url))
        page.goto(self.origin+'/examples/composition-studio.html')
        self.assertFalse(any('tone-studio.min.js' in r for r in requests))
        page.locator('[data-notes]').fill('not-a-note')
        page.locator('[data-audio-play]').click()
        expect(page.locator('[data-audio-status]')).to_have_text('Check notes: invalid note')
        self.assertFalse(any('tone-studio.min.js' in r for r in requests))
        page.locator('[data-progression-notes]').click()
        self.assertEqual(page.locator('[data-notes]').input_value().split(),u.progression_notes('C','I V vi IV'))
        page.locator('[data-audio-play]').click()
        expect(page.locator('[data-audio-status]')).to_have_text('Scheduled 12 notes',timeout=10000)
        page.locator('[data-audio-stop]').click();expect(page.locator('[data-audio-status]')).to_have_text('Stopped')
        # Real Web Audio signal: not just a mocked Synth call.
        page.evaluate('''async()=>{const tone=await import('/vendor/tone-studio.min.js'),button=document.createElement('button');button.dataset.signalProbe='';button.textContent='Measure audio signal';button.onclick=async()=>{try{await tone.start();const voice=new tone.Synth({volume:-18}).toDestination(),ctx=voice.context.rawContext,analyser=ctx.createAnalyser(),mute=ctx.createGain();analyser.fftSize=2048;mute.gain.value=0;voice.connect(analyser);analyser.connect(mute);mute.connect(ctx.destination);const start=tone.now()+0.05;voice.triggerAttackRelease('A4',0.5,start);let peak=0;const deadline=performance.now()+3000;while(performance.now()<deadline){await new Promise(r=>setTimeout(r,20));const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);for(const v of data)peak=Math.max(peak,Math.abs(v));if(peak>0.0001&&ctx.currentTime>start+0.1)break}voice.dispose();analyser.disconnect();mute.disconnect();window.audioSignal={peak,state:ctx.state,clock:ctx.currentTime,start}}catch(e){window.audioSignal={error:String(e)}}};document.body.append(button)}''')
        page.locator('[data-signal-probe]').click()
        page.wait_for_function('()=>window.audioSignal!==undefined',timeout=10000)
        signal=page.evaluate('window.audioSignal')
        self.assertNotIn('error',signal)
        self.assertGreater(signal['peak'],0.0001,signal)
        self.assertEqual(signal['state'],'running')
        self.assertFalse(any(r.startswith(('http://','https://')) and not r.startswith(self.origin) for r in requests))
        self.assertEqual(errors,[])
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
        page.close()


if __name__=='__main__':unittest.main()
