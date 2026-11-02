# Shared world board prototype

Opt in with `board.shared_issue = "OWNER/REPOSITORY/NUMBER"` in an existing
`web-ui-world/1` spec. Omit it to keep the old board. Runtime stays in
`web_ui.py`, using Python stdlib and generated browser JavaScript. No server,
secret token, OAuth handler, network POST, or new runtime dependency is added.
The default example has **no shared destination** and sends no API requests.

The board includes an expandable shared section and a separate-tab GitHub link.
The current world, villagers, player, clock, countdown and local Post stay open.
Without JavaScript the GitHub link still works. Users enter their shared message
on GitHub itself; local Post is never silently copied or submitted to GitHub.

| Action/data | Scope and lifetime |
| --- | --- |
| Existing Post | Current page DOM only, maximum 5 notes; disappears on reload |
| Shared display | Public GitHub comment body (60 code points, whitespace normalized), login and creation timestamp; kept in DOM until refresh/reload |
| GitHub posting | Login required, subject to issue lock, account and repository interaction restrictions; final submission happens on GitHub |
| Published comment | Full original text, username and timestamp publicly accessible on GitHub, potentially indexed/copied; persists until deleted on GitHub |
| Browser storage | No app localStorage, IndexedDB, service worker, token or persistent draft; fetch uses no-store and credentials omitted |

Do not post private rendezvous details, contact information or secrets. This is
public asynchronous messaging, not private chat, instant delivery or a presence
system. The app does not manage GitHub's own login cookies or drafts. Public read
requests disclose the requesting IP to GitHub. GitHub links suppress referrers.
HTML/Markdown in comments is displayed as plain text; images and links are not
rendered. The full original remains available through the GitHub issue.

## API and refresh bounds

A click makes one anonymous GET to
`https://api.github.com/repos/OWNER/REPOSITORY/issues/NUMBER/comments?per_page=100`.
There is no initial fetch, polling, pagination traversal or background request.
The first 100 comments are considered, the last up to five valid comments from
that page displayed newest first. **After 100 comments this is not the newest
five in the issue**; a pagination notice directs readers to GitHub. This small
prototype deliberately bounds response/page work rather than claiming a live feed.
For long-lived use, pagination/latest-feed support is a follow-up before rollout.

Clicks are throttled for at least 120 seconds per mounted board, including errors.
Concurrent requests are ignored, timeout is 10 seconds. Retry-After (seconds) and
X-RateLimit-Reset when remaining is zero extend the wait. Failed requests retain
previous text and announce failure. Reloads and multiple tabs do not coordinate
budgets; a shared NAT/IP can exhaust its budget even at this cadence.

GitHub documents anonymous REST access as 60 requests per hour **per originating
IP**, shared with other anonymous requests. No token is embedded to raise it.
Reading public comments needs no login; private targets fail anonymously.

Primary references (checked 2026-11-03):
- https://docs.github.com/en/rest/issues/comments#list-issue-comments
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api
- https://docs.github.com/en/communities/moderating-comments-and-conversations

## Verification and activation

`PYTHONPATH=. python -m pytest -q tests/test_world_shared.py tests/test_world_motion.py`
checks validation, opt-in compatibility, Node 26 projection and interaction,
text-only comments, malformed API payloads, cooldown and failure retention.
`NODE_PATH=build/shared/node_modules node tests/world_shared.browser.cjs` uses
Playwright Chromium at 390 and 1280 px, with mocked API responses only. It checks
no automatic fetch, anonymous GET, HTML injection, posting link, local notes,
rate limit failures, retained shared display and reload cleanup. The dedicated
Shared world board workflow provisions Node 26 and runs both commands.

Local verification: 72 tests passed (plus one subtest) on Node 26.13.0,
including the existing copied single-file Node launcher tests, motion numerical
parity and both DOM harnesses. The official Node archive SHA-256 was checked.
Chromium download returned invalid/truncated archives locally; real-browser QA
must be checked in CI. No real comment was posted.

Activation requires explicit approval: create one public issue in
`myon-bioinformatics/web-ui`, title **World 共有電光掲示板（公開）**, with a body
stating public visibility, login requirement, no personal/secret information,
GitHub moderation/deletion and non-realtime updates; then set its returned number
in the desired world's `board.shared_issue`. Neither creation nor activation nor
repository visibility changes are performed by this PR. The example `/123` is
only an intercepted test fixture, never a destination configured in shipped pages.
