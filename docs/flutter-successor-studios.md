# Flutter successor studios

This implementation is a reviewable successor, not permission to archive Flutter.
Its parent is PR #109; do not merge this branch ahead of that PR. Runtime Python
remains stdlib-only and Node tooling requires 26+. No messages or input data are
sent by these tools. Browser state is in memory and is lost on reload. Users can
explicitly export/import replay JSON as text.

## Source inventory and archive gate

`flutter-migration-inventory.json` pins flutter_navigation_basic at
`ae3c4cb78cfc9aed15871dfce750d8320a19d1e6`. Reproduce it against a clean checkout, or check that the file on disk is what the tool writes:

```sh
python -S tool/flutter_migration_inventory.py /path/to/flutter_navigation_basic --output docs/flutter-migration-inventory.json
python -S tool/flutter_migration_inventory.py /path/to/flutter_navigation_basic --output docs/flutter-migration-inventory.json --check
```

The inventory lists SHA-256 and a disposition for 178 non-catalogue Dart files, for the 56 Python tools, 8 Dart build tools and
18 workflows, and per group for the four catalogues (2,578 further Dart files; for each kind of file, how many distinct shapes it has once comments,
plain string values, numeric literals and whitespace are ignored, and Pattern-number identifiers are normalized.
Single/double/triple and raw strings are recognized; interpolation expressions are retained as nested shapes.
These are heuristic groups, not proof of equivalent behavior or completed migration. All 594 navigation, API and UI `view.dart` files share one shape). A status says what web-ui did, not that the original was
reviewed line by line: `successor`, `partial`, `not_absorbed` (with the reason), `pending` (asked for, not done), `proposed_retirement` (Flutter runtime with no counterpart on the web; needs the
owner's approval) and `unreviewed`. Outside the catalogues: 9 not_absorbed, 96 partial, 3 pending, 64 proposed_retirement, 74 successor, 14 unreviewed. `archive_ready` stays false while anything is pending, unreviewed or an unapproved retirement.
`tests/test_successor_tools.py` checks the file's invariants, that every function it names exists, and (with `FLUTTER_NAVIGATION_BASIC_CHECKOUT` set) that the tool writes exactly this file.
The generator rejects modified tracked files of the directories it reads and performs no download or repository mutation.

| Source | Successor | Remaining / deliberate difference |
|---|---|---|
| `features/photo_studio`, `shared/clipboard/base64_image_bridge.dart` | `photo_document`, `PhotoStudio` | Native camera, clipboard, HEIC, real-device share/export remain platform-specific |
| `features/composition_generator`, `data/composer.dart` | `studio_document`, `progression_notes`, `studio_audio_plan` | Same music rules; versioned seeded generator intentionally differs from Dart Random |
| `features/now_timeline` | Board zone clocks; `timeline_events`, `timeline_wall_to_utc`, `timeline_document` | Dated events added; stored SharedPreferences entries, recurrence, notifications and actual booking not migrated |
| `features/counter_playground` | `counter_garden`, `play_document` | +/-1/5/10, clamp +/-100, 8-value history; new seeded garden/reward model; native hold-repeat not copied |
| `features/irony_generator`, `data/ironies.dart` | `irony_round`, Play studio | New six-card authored quiz, without copying the old text corpus |
| `features/coordinate_tool` | Coordinates page | Network short-link expansion intentionally excluded |
| Clipboard / HTTP draft | Existing shelf / curl parser | Real HTTP execution/authentication and native clipboard need explicit disposition |
| MCP (`lib/shared/mcp`, mock routes) | MCP lab | Digest/HMAC auth matrix mock (`mock_auth`, `auth_matrix`, `digest_nc`) is pending |
| 198 screens, Hub, locales, native patterns 136-137 / 151-175 / 183-184 | `examples/screens.html`: `screen_*`, `native_*` | Widgets are semantic HTML; screen 5's dedicated controller is not absorbed |
| `metadata_contracts`, `header_contracts`, `gesture_paint`, `validation_http` | `pattern_run("contract")`, `--pattern-serve` | `oracle_selection`, `dart_contracts`, `android_size.dart` and the Flutter-only workflows are proposed for retirement |
| Slides / PPTX and pixel-art tools | Not yet | Asked for; after the Digest/HMAC mock |
| Everything else | No claim of equivalence | Review, retain elsewhere, or explicitly retire with approval |

Archiving remains blocked on file/group dispositions, successor merge/publication,
retention/export decisions for stored data, device checks, and explicit approval.

## Dated events

`examples/timeline.html` accepts a title, local date/time, IANA zone, and (when
needed) an earlier/later choice. Events use explicit integer `utc_ms`, sorted
stably by that value, and show the zone next to the local date. An import/export
panel preserves those instants. Clock-only board windows remain separate from
one-off appointments. Supported UTC window: 2020 inclusive through 2040 exclusive.

A missing local wall time is rejected; a repeated time requires a choice.
Python uses system `zoneinfo`; the browser uses `Intl`. Thus two machines with
different tzdata revisions can disagree about future legislation. Tests compare
fixed golden instants and transition boundaries. This is not an appointment
server, recurrence engine, notification service, or persistent calendar.

## Play, rewards and reproducibility

`examples/play-studio.html` has Counter garden and Irony quest. Seed is uint32;
`web-ui-play/1` fixes xorshift32, palettes, action rules and quiz cards. Changing
these semantics requires a new schema/version. Zero seed has a defined nonzero
initial state. +/- steps are logged; saturating steps are no-ops. Undo removes the
last logged step; Reset empties the counter action list. Neither resets the quiz.

Every accepted counter change plants a reproducible glyph on an 8x8 board. Every
8 unique cells unlocks a reusable emoji stamp; links arm that stamp in Photo
studio. Repeated placement in an existing cell does not increase coverage. The
64-bit occupancy mask is a fixed-width **hex string**, avoiding JSON integer
precision loss. Export generated test input gives both replay and the resulting
mask/cells/history, usable as seeded test specimens. It is not cryptographic
randomness, an unbiased sampler, money, or a remotely verified reward.

Irony quest shuffles six cards per deck, prevents adjacent repeats at deck
boundaries, and awards one point for identifying the contradiction. Exported
answers reconstruct the score; importing starts at the next unanswered card.
Correct choices are public client data: this is a learning game, not an anti-cheat
system. Original CounterBattleEffect's damage/heal strip and native timing have
not been claimed equivalent.

## Optional composition audio

The existing key/mode/progression is converted to explicit arpeggiated notes by
**Use progression as notes**. **Play notes** uses the current notes, BPM and note
value. A bounded plan (1..256 notes, MIDI 0..127) has integer microsecond timing;
Python and JS agree. Stop disposes the voice and cancels a pending asynchronous
load. Tone owns its standardized audio context (native contexts are not injected). Context startup waits are bounded and Stop cancels pending playback immediately. Stop suspends the context; pagehide disposes it. Next playback and pagehide also dispose the voice. No autoplay or remote samples.

Tone.js is **optional** and loaded locally only after Play. Build-free pages and
all pure calculations need neither npm nor Tone. Build and serve an audio-enabled
site explicitly:

```sh
python -S web_ui.py --site build/site
npm ci --prefix tool/studio-audio --ignore-scripts
node tool/studio-audio/build.mjs build/site/vendor
python -m http.server 8000 --directory build/site
```

Node 26, Tone 15.1.22, esbuild 0.25.12 and npm's lockfile are fixed. The build
exports `Synth`, `start`, `now`, `getContext`; it emits `tone-studio.min.js`, all bundled-package
licenses, and a JSON measurement/hash receipt. No build output is checked into
source or added to default Python dependencies. The audio build is an optional
browser artifact, not a second canonical JS source tree. Tone's internal
context/synthesis dependencies remain: this is a measured subset, not a proof of
an absolute smallest possible synthesizer.

Two identical builds on Linux x86_64 / Node 26.13.0 produced the same bytes:

| Tone 15.1.22 artifact | Bytes | gzip bytes |
|---|---:|---:|
| Upstream full UMD build | 345,500 | 79,843 |
| Minified ESM subset | 237,137 | 61,383 |

These are artifact sizes, not startup-time or memory measurements. The full UMD
is already minified upstream; ESM and UMD formats differ, so the comparison is a
practical delivery comparison rather than a controlled tree-shaking benchmark.
Raw reduction 31.4%, gzip reduction 23.1%. Licenses and build report are additional
files and excluded from these JS-only sizes. The subset's dependencies are tone,
standardized-audio-context, automation-events, @babel/runtime, and tslib.

Official API: https://github.com/Tonejs/Tone.js#starting-audio and
https://github.com/Tonejs/Tone.js#synth (user gesture, context start, scheduling).
The real-signal acceptance test measures a Web Audio waveform, not subjective
sound quality or iOS speaker output.

## Verification

`tests/test_successor_tools.py`: golden values, seeded Python/JS parity, invalid
replay rejection, reward/no-op boundaries, quest decks, audio plan/progression,
stop-during-load race, UTC ordering, ambiguous and missing wall times.

`tests/integration/successor_browser.py`: 320/390/1280px garden, rewards, export,
undo/replay, score stability, reward-to-photo handoff, local appointment input,
UTC ordering, repeated-hour choice, optional audio request timing, current
progression-to-notes, real waveform generation, Stop, no external HTTP requests.

`Successor studios` CI locks build inputs, compares two builds, then runs the
acceptance suite in Chromium, Firefox and WebKit with generated audio and preserves the measurement artifacts.
Existing Python, Node, shared-board, UI, DOM and platform-matrix workflows remain.
Phone widths are browser emulation; native iOS/Android behavior is not certified.

Headless Firefox also requires an actual clocked audio output. CI starts a
PulseAudio null sink (no speakers) before the real-signal tests, with an explicit loopback-only server address passed to the browser. This is test
infrastructure, not a runtime dependency of the static site; autoplay blocking
is not disabled. A bare AudioContext stayed suspended in the no-device probe,
so that condition is distinguished from a Tone.js failure.

A sporadic existing WebKit ResizeObserver loop during EXIF imports was also
observed. Photo studio now observes a zero-height width probe rather than the
canvas parent whose height changes during imports; existing orientation/resize
acceptance tests cover this behavior without filtering browser errors.

The lexical shape repair changes only data-processing group counts at the pinned source:
`service.dart` 2 → 1 and `view.dart` 23 → 22. Whitespace and comment placement no longer create extra groups.
Original file/tree hashes, file counts and migration dispositions are unchanged. This scanner is not a Dart parser;
it rejects unterminated delimiters but does not validate all Dart syntax. Numeric/string values are intentionally ignored,
so distinct runtime behavior can still share a shape.
