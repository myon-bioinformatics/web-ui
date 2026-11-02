# World motion and clock ownership

All runtime source remains in `web_ui.py` (stdlib only). The existing
`web-ui-world/1` `actors`, `player`, and `board` fields remain supported.
No Rust/C, browser Python interpreter, new server, dependency or persistent
storage is added.

## Python and static Pages

Python validates and generates the seeded villager CSS keyframes. Each villager
walks in straight lines at constant speed, rests for seeded random 1–4 second
intervals, and walks back to its initial position before the cycle repeats.
The cycle is continuous, with no endpoint teleport. Bounds: 16 actors per floor,
eight floors; the direct `villager_path` helper accepts 1–64 stops, map dimensions
64–4096, finite speeds 1–480, bounded seed and margin. Keyframe timestamps retain
precision so rounding does not change segment speed.

`world_walk` builds a bounded segment and `world_motion_sample` computes position
at injected elapsed seconds. They are the Python oracle for the emitted browser
projection. Retargeting samples the current segment first, not its old destination.
Elapsed **monotonic** time, not frame deltas, controls player motion; arrivals
clamp without overshoot. Pause/resume freezes this elapsed clock without catching
up the paused interval. Background-tab time catches up to the correct position,
never beyond the destination. Wall-clock changes do not affect movement.

**Static Pages does not execute Python.** CSS runs the Python-generated villager
plans. The minimal generated JavaScript adapter computes the interactive player
projection and new tap destinations locally, and updates the board from browser
time. Numeric parity is tested against Python in Node. Exported JavaScript
projection helpers assume validated inputs; they are not public validators.
Literal Python execution after each tap would require an additional runtime or
server, intentionally not introduced here.

## Interaction and accessibility

Blank-map taps walk to the tapped point on the active floor. Spot activation
still opens its sheet and requests walking. Drag, pinch, cancellation, and
clicking an actor do not accidentally request a blank-space walk. Each floor
retains its own player state. The labeled X/Y form is a keyboard alternative.
The stop/resume button exposes `aria-pressed` and pauses villagers and board
scrolling as well as player motion.

Reduced-motion holds animations rather than restarting their paths. Player
motion freezes at its sampled position; new destinations are immediate while
reduced-motion is enabled. Returning to normal does not jump forward in time.
The avatar is labeled “自分”. The clock/countdown is not a live announcement
every second. Without JavaScript the existing static map and spot links work;
interactive player controls are hidden.

## Daily board time: seconds, offsets, and rounding

The author’s `HH:MM` items refer to the **next daily occurrence**, not an absolute
deadline. `board_clock(now, offset_minutes)` accepts Unix **seconds** plus an
explicit fixed UTC offset in minutes (−840…840), independent of the Python host
timezone. It returns the clock label and fractional minutes since midnight.
`minutes_until(now, at)` accepts those fractional minutes and the integer target
minute. It computes `ceil((at - now) % 1440)` and returns 0…1440:

- 10:29:59 → 10:30 is “あと1分”.
- Exactly 10:30:00 → 10:30 is “いま”.
- 10:30:01 → 10:30 means tomorrow, “あと1440分”.
- Midnight wraps explicitly; this is not an expired deadline clamped to zero.

An optional `board.offset_minutes` fixes the browser's offset, e.g. `540` for
UTC+09:00. Omit it (or use `None`) to retain the author’s browser-local timezone;
the browser passes its current offset explicitly to the same arithmetic helper.
A fixed offset does not infer daylight-saving transitions or named timezones.

The existing opt-in visitor note form remains **this-page-only DOM text**. It is
not shared messaging: no network write, backend, localStorage or reload persistence.
Its bounded-list repair is retained unchanged.

## Verification

`PYTHONPATH=. python -m pytest tests/test_world_motion.py` covers finite limits,
constant speed, seeded continuous loops, retarget/pause/arrival, daily boundaries,
UTC offsets, Node numerical parity, and a deterministic DOM/clock event harness.
The harness covers tap, drag/pinch/cancel, keyboard form, floor switching,
reduced-motion and removal cleanup. **It is not Chromium/browser rendering QA.**
The Node tests use an existing Node 26+, otherwise explicitly skip; no installer
runs. Existing browser integration assertions retain travel duration/destination
and board text checks; those must run in the authorized hosted browser CI lane.
