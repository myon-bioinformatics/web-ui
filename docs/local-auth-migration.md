# Local fixture authentication migration

Source: `flutter_navigation_basic@ce66ae7198dbe74ed62f70180fbff260e4acd14d`.
Compared with the inventory's previous `ae3c4cb`, one commit changes Python
header/metadata/pattern contracts and adds optimized-mode tests. The three Dart
authentication files are unchanged.

The existing MCP lab inspects demo JWT payloads and models MCP transport; it does
not implement this opaque-token Basic/Digest/HMAC matrix. The existing pattern
bridge supplies loopback binding, Host/Origin checks, JSON parsing, the 64 KiB
body limit, timeout and no-store responses. Those checks are reused.

Run `python -S web_ui.py --pattern-serve`, then open
`http://127.0.0.1:8765/auth.html`. No third-party runtime dependencies are needed.
The page prepares public demo requests, permits edits, and displays the actual
HTTP status, challenge or Retry-After header, and JSON body. Repeat a signed
Digest/HMAC request to demonstrate replay rejection; prepare again for a fresh
fixture nonce. These credentials are intentional public fixtures.

`POST /mock-auth` receives a simulated request as JSON:

```json
{"method":"GET","path":"/auth/bearer","headers":{"Authorization":"Bearer demo-bearer-token"},"query":{},"body":""}
```

It returns the mock's actual HTTP status/body/headers (including 401, 403 and
429). Routing paths are simulated data; no HTTP client is called. The original
standalone server's direct `/auth/*` routes are not mounted. `/health` is outside
MockAuthHandler, as in Dart, and returns 404 here. `POST /mock-auth/prepare`
accepts `{"scenario":"digest"}` (or another preset) and returns a fresh fixture
request. `auth_matrix` retains Dart's unsigned Digest/HMAC presets;
`auth_prepare` explicitly completes them for this demonstration.

Optional `query_pairs` is an ordered list of `[name,value]` pairs, preserving
repeated keys and Dart-compatible form encoding. The separate `query` map is
what the source API-key handler reads. Optional `request_target` models the raw
incoming Digest target. Without it, the target is derived from path and pairs
(or the query map). HMAC signs uppercase method, actual path including a trailing
slash, encoded query, body, raw timestamp and nonce, separated by newlines.
Digest retains Dart's method casing.

Replay state belongs to one bridge instance, is locked across HTTP threads, and
disappears on restart. Failed signatures never consume a nonce/count. Like the
source fixture, accepted nonces/counts remain in memory for the handler's
lifetime; use bounded demo sessions. This is not a live authentication backend,
JWT verifier, or production Digest implementation. No external service is used.

## Coverage and reproduction

- `python -S -m unittest discover -s tests -p test_mock_auth.py -v`
- Repeat with `python -S -O -m unittest ...`.
- `python -S tool/auth_parity.py /path/to/flutter_navigation_basic` copies the
  unmodified, hash-checked Dart handler/helper into a temporary Dart-only
  project, pins crypto 3.0.7, and compares complete responses for 84 requests
  plus 20 helper vectors. Requires Dart >=3.12 and pub access, without Flutter.
  The automatic Local auth contract workflow runs this comparison.
- Browser regression: `python -m unittest -v tests.integration.controls_browser.MockAuthBrowserTests`.
  Existing Platform matrix desktop lanes run it in Chromium, Firefox and WebKit.
  It covers eleven presets, actual status/headers, signed success and replay,
  edited-body failure/recovery, malformed JSON, and layout at 320px.

Authoring environment: 16 new stdlib tests pass normally and with `-O`.
74 selected existing bridge/contract/native/screen tests pass (one optional
Flutter-checkout check skips). OpenSSL also agrees with the fixed HMAC vector.
Dart is unavailable locally, but automatic PR CI passed the complete Dart/Python
comparison: 84 requests and 20 helper vectors, Dart 3.13.7 / crypto 3.0.7,
[run 41977145216](https://github.com/myon-bioinformatics/web-ui/actions/runs/41977145216).
This caught and corrected Basic authentication padding rejection: Dart rejects
unpadded Base64. Browser download returned a truncated archive locally; browser
execution remains pending the existing Platform matrix CI. An attempted wider wrapper suite was
blocked by missing Pillow, binary image fixtures, index.html and brand assets in
the connector-only source snapshot; it was not a full-suite pass.

## Inventory and remaining work

`digest_nc.dart` and `mock_auth.dart` now have tested Python successors.
`auth_matrix.dart` is partial: all eleven fixture presets are represented, but
Flutter RequestDraft sensitive-field metadata and its draft UI are not migrated.
The inventory source moves to `ce66ae7` and refreshes hashes for the three changed
Python contract files. The generator uses the same dispositions.

`archive_ready` stays false. Outside catalogue groups, 14 entries are unreviewed
and 64 are proposed for retirement; catalogue groups remain partial. Remaining
behavior includes native camera/clipboard/share/HEIC, stored entries and
notifications, external HTTP transport, per-pattern Flutter UI behavior, and
explicit retirement/archive approval. No archive action is performed.
