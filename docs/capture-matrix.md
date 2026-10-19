# Representative Flutter pages and the multi-browser viewer

## Page table (`examples/flutter-pages.json`)

`web-ui-flutter-pages/1` lists the representative flutter_navigation_basic pages that
browser-test-kit captures (`adapters/flutter-*.json`): route, emoji key, label, the
published URL and the browser-test-kit adapter id. Routes and emojis follow
flutter_navigation_basic's generated page identities. The `pages` rows are a web-ui
route table, so `web_ui.route_table` / `navigation.js` `routeTable` validate them and
`go("🗺️")` resolves by emoji. The adapter ids are the join key with the captures; the
set is checked against browser-test-kit's list by fixture, not by import.

## Viewer (`tool/capture_matrix.py`)

```sh
# browser-test-kit platform-apps artifacts -> Ironmate sheet -> web-ui viewer
python -S ../Ironmate/browser_matrix.py app-results --out matrix
python -S tool/capture_matrix.py --pages examples/flutter-pages.json \
  --report matrix/report.json [--dataset app-matrix/dataset.json] --embed-css > matrix/viewer.html
```

One section per page, opened from emoji links (`#/hub`). CSS `:target` shows the chosen
page and all pages are shown without a fragment, so the viewer needs no JavaScript and
works from `file://`. Each page shows one tile per environment (Ironmate's
`tiles/<page>/<env>.png`, relative to `--tiles-base`), the tile difference from the
reference environment, and, with a browser-test-kit dataset, pass/fail and the deployed
build commit that environment saw. Missing captures are marked, failures outlined.

Differences are tile-level hints from Ironmate, not pixel-exact gates. Mobile profiles are
emulation. Inputs are trusted JSON from those tools; text is escaped, page URLs must be
HTTPS and asset/tile bases must be local paths.
