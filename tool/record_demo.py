"""Record the school world's (and the overworld's) operations as demo GIFs (for the README).

    python tool/record_demo.py docs/demo [--only pick keys ...] [--chrome PATH] [--width 480] [--force]

Playwright drives a real Chrome through each scene. The ``Camera`` keeps a screenshot with its real timestamp whenever a scene waits,
so a GIF plays at the speed the page really moved. Encoding follows Ironmate's ``png_zoom_gif.py``: one shared palette (no dither,
so frames never flicker), delays in 10 ms units (never below 20 ms, which browsers stretch), the animation loops, and an existing
output is refused unless ``--force``. Unlike that zoom (every pixel changes), a walking player changes few pixels, so frames are
written as deltas (``optimize=True``): about a third of the size, decoding to exactly the same pictures. The zoom step
(``cam.zoom``) is Ironmate's smooth zoom-in, kept to what the demos need and run through this same encoder, not a second copy of
that tool; this repository is the canonical home of both. Needs Playwright and Pillow, like the browser tests. Scenes are ordinary functions, so a new
operation is one ``@scene`` below; ``tests/integration/school_browser.py`` records every scene to keep them from rotting.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import web_ui  # noqa: E402

FRAME_MS = 80                                   # at most one screenshot per 80 ms while a scene waits
MIN_MS, MAX_MS, TAIL_MS = 20, 2000, 1500        # delay limits, and how long the last frame stays
SPEC = web_ui.example_data("school")
FLOOR = web_ui.world_validate(SPEC)["floors"][0]
W, H, T = FLOOR["width"], FLOOR["height"], FLOOR["tile"]
CLASSROOM = f'.ui-floor[data-floor="{FLOOR["id"]}"]'
PICKED = "() => !document.querySelector('.ui-world').hasAttribute('data-pick')"
SETTLED = ("() => { const f = [...document.querySelectorAll('.ui-floor')].find(f => getComputedStyle(f).display !== 'none'), p = f.querySelector('.ui-player'), s = p.style;"
           "return Math.abs(parseFloat(s.getPropertyValue('--px')) - +p.dataset.targetX) < .01 && Math.abs(parseFloat(s.getPropertyValue('--py')) - +p.dataset.targetY) < .01 }")   # the shown floor's player has arrived
PLAYER = (0.48, 0.69)                           # where a character standing at the door is on screen: a zoom target
WORLDS = {"school": SPEC, "overworld": web_ui.example_data("overworld")}       # the specs a scene can open; a GIF is <world>-<scene>.gif


class Scene(NamedTuple):
    width: int
    height: int
    touch: bool
    crop: str | None
    fn: Callable
    world: str


SCENES: dict[str, Scene] = {}


class Camera:
    """Screenshots with their real times; scenes call hold/until where the GIF should show time passing."""

    def __init__(self, page, crop=None):
        self.page, self.crop, self.shots = page, crop, []

    def png(self):
        """One screenshot; with ``crop`` (a selector) only that element's box, so the GIF is the world and not the empty page around it."""
        if not self.crop:
            return self.page.screenshot(type="png")
        box = self.page.eval_on_selector(self.crop, "e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height} }")
        return self.page.screenshot(type="png", clip={k: round(v) for k, v in box.items()})

    def snap(self):
        self.shots.append((time.monotonic(), self.png()))

    def hold(self, ms):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            began = time.monotonic()
            self.snap()
            self.page.wait_for_timeout(max(0, FRAME_MS - (time.monotonic() - began) * 1000))

    def zoom(self, anchor=(0.5, 0.5), factor=2.5, steps=6, hold_ms=1500):
        """Zoom into what is on screen toward ``anchor`` and stay there: the demos are shown small in the README.
        ``anchor`` is (x, y) from 0 to 1, an anchor name (``"bottom-right"``) or an arrow emoji (``↘️``, ``⬅``, ``🎯`` for the centre), the
        same table web_ui uses for directions. Every pixel changes in a zoom, so it costs a few frames of GIF size; it does not zoom back."""
        from PIL import Image
        if isinstance(anchor, str):
            anchor = web_ui.WORLD_ANCHORS[anchor if anchor in web_ui.WORLD_ANCHORS else web_ui.world_arrow_anchor(anchor)]
        source = Image.open(io.BytesIO(self.png())).convert("RGB")
        width, height = source.size
        forward = []
        for i in range(1, steps + 1):
            t = i / steps
            scale = 1 + (factor - 1) * t * t * (3 - 2 * t)          # smoothstep, as in png_zoom_gif
            w, h = max(1, round(width / scale)), max(1, round(height / scale))
            left, top = round((width - w) * anchor[0]), round((height - h) * anchor[1])
            forward.append(source.crop((left, top, left + w, top + h)).resize(source.size, Image.Resampling.LANCZOS))
        path = [(f, 60) for f in forward[:-1]] + [(forward[-1], hold_ms)]
        t = time.monotonic()
        for frame, ms in path:
            png = io.BytesIO()
            frame.save(png, format="PNG")
            self.shots.append((t, png.getvalue()))
            t += ms / 1000
        time.sleep(max(0, t - time.monotonic()))                  # the clock catches up with the frames just added

    def until(self, script, ms=20000):
        end = time.monotonic() + ms / 1000
        while not self.page.evaluate(script):
            if time.monotonic() > end:
                raise TimeoutError(script)
            self.hold(FRAME_MS)
        self.snap()


def encode(shots, *, width=None, tail_ms=TAIL_MS):
    """One GIF from (time, png) shots: shared palette, 10 ms delays, looping forever."""
    from PIL import Image
    frames = [Image.open(io.BytesIO(png)).convert("RGB") for _, png in shots]
    if width and width != frames[0].width:
        frames = [f.resize((width, round(f.height * width / f.width)), Image.Resampling.LANCZOS) for f in frames]
    sample = frames[::max(1, len(frames) // 16)]                # the palette comes from frames across the whole scene
    sheet = Image.new("RGB", (sample[0].width, sample[0].height * len(sample)))
    for i, frame in enumerate(sample):
        sheet.paste(frame, (0, i * frame.height))
    palette = sheet.quantize(colors=255)                        # one slot stays free for Pillow's "unchanged pixel" transparency
    encoded = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    times = [t for t, _ in shots]
    delays = [min(MAX_MS, max(MIN_MS, round((b - a) * 100) * 10)) for a, b in zip(times, times[1:])] + [tail_ms]
    out = io.BytesIO()
    # optimize=True writes each frame as a delta: unchanged pixels become transparent, so a walking player costs a few KiB, not a screenful
    encoded[0].save(out, format="GIF", save_all=True, append_images=encoded[1:], duration=delays, loop=0, optimize=True)
    return out.getvalue()


def scene(name, width=560, height=720, touch=False, crop=".ui-world", world="school"):
    def add(fn):
        SCENES[name] = Scene(width, height, touch, crop, fn, world)
        return fn
    return add


def choose(page, emoji):
    page.click(f'[data-emoji="{emoji}"]')
    page.wait_for_function(PICKED)
    page.wait_for_timeout(500)                  # the camera finishes its short glide


def at(page, x, y):
    """Page coordinates of the middle of tile (x, y) of the classroom, wherever the camera has put it."""
    left, top, width, height = page.eval_on_selector(CLASSROOM, "e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height] }")
    return left + (x * T + T / 2) * width / W, top + (y * T + T / 2) * height / H


def tap(page, cam, x, y):
    page.mouse.click(*at(page, x, y))
    cam.until(SETTLED)
    cam.hold(500)


def key(page, cam, name, repeat_ms=0):
    """A key press; with repeat_ms the key is held and the browser repeats it."""
    end = time.monotonic() + repeat_ms / 1000
    page.keyboard.down(name)
    while time.monotonic() < end:
        cam.hold(FRAME_MS)
        page.keyboard.down(name)                # a repeating keydown
    page.keyboard.up(name)
    cam.hold(300)


def pad(page, cam, step, ms):
    """The on-screen pad: press and hold one arrow button."""
    page.dispatch_event(f'[data-step="{step}"]', "pointerdown")
    cam.hold(ms)
    page.dispatch_event(f'[data-step="{step}"]', "pointerup")
    cam.hold(300)


def more(page, cam, name="more", ms=700):
    """Open a menu: ``settings`` is the header's ⚙️ (pause, change emoji, language), ``favorites`` the header's ⭐, ``spots`` the side's ☰
    list of places and ``more`` the side's ⋯ (walk to X/Y, find myself)."""
    page.click(f'.ui-world-menu[data-menu="{name}"] summary')
    cam.hold(ms)


@scene("pick")
def _pick(page, cam, tmp):
    """The picker comes first; choosing a character puts it in the room."""
    cam.hold(1200)
    page.click('[data-emoji="🦊"]')
    cam.until(PICKED)
    cam.hold(600)
    cam.zoom(PLAYER)


@scene("avatar-text")
def _avatar_text(page, cam, tmp):
    """Change the character later: type any text, an emoji or both."""
    choose(page, "🙂")
    cam.hold(600)
    more(page, cam, "settings")
    page.click("[data-pick-open]")
    cam.hold(900)
    page.click(".ui-world-pick-form input")
    for char in "先生🍎":                          # typed one character at a time so the GIF shows it
        page.keyboard.type(char)
        cam.hold(400)
    page.keyboard.press("Enter")
    cam.until(PICKED)
    cam.hold(600)
    cam.zoom(PLAYER)


@scene("keys")
def _keys(page, cam, tmp):
    """Arrow keys and WASD, one tile per press, held keys repeat; desks stop the walk."""
    choose(page, "🐱")
    cam.hold(600)
    key(page, cam, "ArrowUp", 1400)            # straight into a desk row: the cat stops
    key(page, cam, "ArrowLeft")                 # sideways into the aisle
    key(page, cam, "ArrowUp", 3200)             # along the aisle to the teacher's desk
    for name in "ddd":
        key(page, cam, name)
    for name in "sss":
        key(page, cam, name)
    key(page, cam, "a")
    cam.hold(900)


@scene("tap")
def _tap(page, cam, tmp):
    """Tap a chair and the player walks around the desks to it; a desk itself ends on the nearest free tile."""
    choose(page, "😎")
    cam.hold(600)
    tap(page, cam, 2, 8)
    tap(page, cam, 9, 6)
    tap(page, cam, 5, 11)                       # a desk: the nearest free tile
    cam.hold(600)


@scene("phone", width=360, height=640, touch=True)
def _phone(page, cam, tmp):
    """A phone: tap a character, walk with the on-screen pad, drag the map away and come back with 自分の場所."""
    cam.hold(900)
    page.tap('[data-emoji="🐶"]')
    cam.until(PICKED)
    cam.hold(700)
    pad(page, cam, "0,-1", 1400)
    pad(page, cam, "-1,0", 400)
    pad(page, cam, "0,-1", 2400)
    pad(page, cam, "1,0", 700)
    left, top, width, height = page.eval_on_selector(".ui-world-view", "e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height] }")
    page.mouse.move(left + width / 2, top + height / 2)
    page.mouse.down()
    for i in range(1, 9):                       # drag: the camera stops following
        page.mouse.move(left + width / 2 - 12 * i, top + height / 2 + 24 * i)
        cam.hold(FRAME_MS)
    page.mouse.up()
    cam.hold(700)
    more(page, cam)
    page.click("[data-me]")
    cam.hold(1400)


@scene("menu")
def _menu(page, cam, tmp):
    """The side menu: the ☰ list shows an arrow from you to each place; tap one and the arrow turns to 📍 as you arrive."""
    choose(page, "🐱")
    cam.hold(500)
    pad(page, cam, "0,-1", 900)
    more(page, cam, "spots", 1800)
    page.click('.ui-world-spots a[href="#school-spot-classroom-board"]')
    cam.until(SETTLED)
    cam.hold(800)
    page.click(".ui-sheet-close:visible")
    cam.hold(600)
    more(page, cam, "spots", 1600)


@scene("header")
def _header(page, cam, tmp):
    """The header: ⭐ star two places (one on another floor), see them in the ⭐ list, 🗺️ an emoji tool, 🌐 the language, 🏠 back home."""
    choose(page, "🦊")
    cam.hold(500)
    more(page, cam, "spots", 900)
    page.click('.ui-world-spots[data-floor="classroom"] li:nth-child(1) .ui-world-star')
    cam.hold(700)
    page.keyboard.press("Escape")
    page.select_option(".ui-world-goto", "yard")
    cam.hold(700)
    more(page, cam, "spots", 600)
    page.click('.ui-world-spots[data-floor="yard"] li:nth-child(2) .ui-world-star')
    cam.hold(700)
    page.keyboard.press("Escape")
    page.click('.ui-world-head .ui-world-menu[data-menu="favorites"] summary')
    cam.hold(1500)
    page.click('.ui-world-head .ui-world-menu[data-menu="tool"]:has(summary:text("🗺️")) summary')
    cam.hold(1500)
    more(page, cam, "settings", 800)
    page.select_option(".ui-world-head [data-lang]", "fr")
    cam.hold(900)
    page.select_option(".ui-world-head [data-lang]", "ja")
    cam.hold(600)
    page.keyboard.press("Escape")
    page.click(".ui-world-head .ui-world-home")
    cam.hold(1000)


@scene("floors")
def _floors(page, cam, tmp):
    """Floors and spots: go to the schoolyard, tap a spot, read it, come back to the classroom."""
    choose(page, "🐸")
    cam.hold(500)
    page.select_option(".ui-world-goto", "yard")
    cam.hold(1200)
    page.click('a.ui-spot[href="#school-spot-flowers"]')
    cam.hold(1600)
    page.click(".ui-sheet-close:visible")
    cam.hold(600)
    page.select_option(".ui-world-goto", "classroom")
    cam.hold(900)
    page.click('a.ui-spot[href="#school-spot-classroom-board"]')
    cam.hold(1600)
    page.click(".ui-sheet-close:visible")
    cam.hold(600)


@scene("lands", world="overworld")
def _lands(page, cam, tmp):
    """Lands side by side: the 🚪 pulldown travels from land to land (swapped objects, nothing else), then walk to the castle town by its ☰ row."""
    choose(page, "🧙")
    cam.hold(900)
    for land in ("forest", "mountain", "desert", "coast", "castle"):
        page.select_option(".ui-world-goto", land)
        cam.hold(1000)
    more(page, cam, "spots", 900)
    page.click('.ui-world-spots[data-floor="castle"] a[href="#overworld-spot-castle-town"]')
    cam.until(SETTLED)
    cam.hold(900)


@scene("real", world="overworld")
def _real(page, cam, tmp):
    """Real x virtual: choose a photo (a camera feed is chosen the same way) and it sits behind the floor; walk over it, then 🧹. The photo is drawn here."""
    from PIL import Image, ImageDraw
    room = Image.new("RGB", (640, 480), (214, 226, 232))
    draw = ImageDraw.Draw(room)
    draw.rectangle((0, 336, 640, 480), fill=(176, 132, 96))
    draw.rectangle((88, 64, 296, 232), fill=(150, 200, 240), outline=(96, 96, 104), width=8)
    draw.rectangle((408, 144, 552, 336), fill=(120, 92, 72))
    room.save(tmp / "room.png")
    choose(page, "🧙")
    page.select_option(".ui-world-goto", "real")
    cam.hold(1000)
    more(page, cam, "more", 800)
    page.click("[data-real]")
    cam.hold(1000)
    with page.expect_file_chooser() as chooser:
        page.click('.ui-world-ask button[data-t="photo"]')
    chooser.value.set_files(str(tmp / "room.png"))
    page.wait_for_function("() => document.querySelector('.ui-real')?.complete")
    cam.hold(1000)
    more(page, cam, "spots", 700)
    page.click('.ui-world-spots[data-floor="real"] a[href="#overworld-spot-real-gate"]')
    cam.until(SETTLED)
    cam.hold(800)
    page.click(".ui-sheet-close:visible")
    more(page, cam, "more", 600)
    page.click("[data-real]")
    cam.hold(700)
    page.click('.ui-world-ask button[data-t="clear"]')
    cam.hold(900)


TERMINAL = ('<meta charset="utf-8"><body style="margin:0;background:#0d1117;color:#d1f7c4;font:20px/1.6 Meiryo,メイリオ,monospace">'
            '<pre style="margin:0;padding:24px;white-space:pre-wrap;word-break:break-all"></pre>')


@scene("oneliner", crop=None)
def _oneliner(page, cam, tmp):
    """From another repository: one command writes the school page. The output shown is the real output of that run."""
    spec = '{"schema":"web-ui-world/1","avatars":["🙂","先生"],"floors":[{"classroom":{"rows":5,"groups":3}}]}'
    command = f"echo '{spec}' | python -S web_ui.py --world - > school.html"
    began = time.monotonic()
    done = subprocess.run([sys.executable, "-S", str(ROOT / "web_ui.py"), "--world", "-"], input=spec, text=True, capture_output=True,
                          check=True, encoding="utf-8")
    seconds = time.monotonic() - began
    (tmp / "oneliner.html").write_text(done.stdout, encoding="utf-8")
    page.set_content(TERMINAL)
    show = lambda text: page.evaluate("t => { document.querySelector('pre').textContent = t }", text)  # noqa: E731
    shell = "$ "
    show(shell)
    cam.hold(600)
    for end in range(8, len(command) + 8, 8):
        show(shell + command[:end])
        cam.snap()
        page.wait_for_timeout(FRAME_MS)
    shell = f"$ {command}\n$ wc -c school.html\n"
    show(shell)
    cam.hold(500)
    show(f"{shell}{len(done.stdout.encode('utf-8'))} school.html   ({seconds:.2f} s)\n$ open school.html")
    cam.hold(1600)
    page.goto((tmp / "oneliner.html").as_uri())
    cam.hold(900)
    choose(page, "先生")
    cam.hold(1400)


def launch(pw, chrome=None):
    chrome = chrome or os.environ.get("WEB_UI_CHROME")
    return pw.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else pw.chromium.launch()


def record(out, names=None, *, chrome=None, width=None, force=False, browser=None):
    """Record the named scenes (all by default) into out/<world>-<name>.gif (school-keys.gif, overworld-lands.gif); returns the written paths.

    ``browser`` is an already running Playwright Chromium (the browser tests share theirs); otherwise one is launched and closed here.
    """
    names = list(names or SCENES)
    unknown = [n for n in names if n not in SCENES]
    if unknown:
        raise ValueError("unknown scene: " + ", ".join(unknown) + " (have " + ", ".join(SCENES) + ")")
    out = Path(out)
    targets = {n: out / f"{SCENES[n].world}-{n}.gif" for n in names}
    if not force and any(p.exists() for p in targets.values()):
        raise FileExistsError("refusing to overwrite " + ", ".join(str(p) for p in targets.values() if p.exists()) + " (use --force)")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_name, contextlib.ExitStack() as stack:
        tmp = Path(tmp_name)
        for world in {SCENES[n].world for n in names}:
            (tmp / f"{world}.html").write_text(web_ui.world_document(WORLDS[world]), encoding="utf-8")
        if browser is None:
            from playwright.sync_api import sync_playwright
            browser = launch(stack.enter_context(sync_playwright()), chrome)
            stack.callback(browser.close)
        for name in names:
            sc = SCENES[name]
            context = browser.new_context(viewport={"width": sc.width, "height": sc.height}, has_touch=sc.touch, is_mobile=sc.touch)
            try:
                page = context.new_page()
                page.goto((tmp / f"{sc.world}.html").as_uri())
                cam = Camera(page, sc.crop)
                sc.fn(page, cam, tmp)
                targets[name].write_bytes(encode(cam.shots, width=width))
            finally:
                context.close()
    return list(targets.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, help="directory for <world>-<scene>.gif")
    parser.add_argument("--only", nargs="+", metavar="SCENE", help="scenes to record: " + ", ".join(SCENES))
    parser.add_argument("--chrome", help="Chrome/Chromium executable (default: WEB_UI_CHROME or Playwright's)")
    parser.add_argument("--width", type=int, help="shrink every GIF to this width in pixels")
    parser.add_argument("--force", action="store_true", help="replace existing GIFs")
    args = parser.parse_args(argv)
    try:
        for path in record(args.out, args.only, chrome=args.chrome, width=args.width, force=args.force):
            print(f"🎞️ {path}  📦 {path.stat().st_size // 1024} KiB")
    except (ValueError, OSError, ImportError, TimeoutError) as exc:
        parser.exit(1, f"⛔ {exc}\n")


if __name__ == "__main__":
    main()
