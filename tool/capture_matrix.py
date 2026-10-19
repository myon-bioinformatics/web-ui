"""Static viewer for multi-browser captures of representative pages: one section per page, opened by emoji.

Inputs are JSON produced elsewhere; this tool only presents them with web-ui styles:

- ``--pages``: ``web-ui-flutter-pages/1`` (``examples/flutter-pages.json``): route, emoji key,
  label, published URL and the browser-test-kit adapter id of each representative page;
- ``--report``: Ironmate ``ironmate-browser-matrix/1`` (tiles and differences per page x environment);
- ``--dataset`` (optional): browser-test-kit ``btk-platform-matrix/1``, for pass/fail and the
  deployed build commit each environment saw.

The page links are a web-ui route table (``#/hub`` style), so the viewer works from
``file://`` and needs no JavaScript: CSS ``:target`` shows the chosen page.

    python -S tool/capture_matrix.py --pages examples/flutter-pages.json --report matrix/report.json \
        [--dataset app-matrix/dataset.json] --embed-css > matrix/viewer.html
"""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import web_ui  # noqa: E402  (route table rules shared with navigation.js)
sys.path.insert(0, str(ROOT / "tool"))
import layout_presets  # noqa: E402  (switchable layouts, same rules as js/layout-presets.cjs)

DEFAULT_LAYOUTS = ROOT / "examples" / "layout-presets.json"

MAX_INPUT = 8 * 1024 * 1024
THEMES = ("modern", "github-like")
ASSETS = ("css/tokens.css", "css/base.css", "css/components.css", "css/matrix.css")


def _load(path, schema):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_INPUT:
        raise ValueError(f"{path}: larger than {MAX_INPUT} bytes")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != schema:
        raise ValueError(f"{path}: expected schema {schema}")
    return data


def _https(url):
    if not isinstance(url, str) or not url.startswith("https://") or any(c in url for c in '"<> \n\r'):
        raise ValueError(f"page url must be https: {url!r}")
    return url


def _verdicts(dataset):
    """{(adapter, env id): (verdict, build)} from a btk dataset (records may lack a target)."""
    out = {}
    for record in (dataset or {}).get("records", []):
        target, env = record.get("target") or {}, record.get("env") or {}
        if target.get("adapter") and env.get("id"):
            build = (target.get("provenance") or {}).get("value")
            out[target["adapter"], env["id"]] = (record.get("verdict"), build if isinstance(build, str) else None)
    return out


def _tile(report, cells, verdicts, adapter, env, tiles_base):
    cell = cells.get((adapter, env))
    verdict, build = verdicts.get((adapter, env), (None, None))
    classes = []
    if cell is None:
        classes.append("is-missing")
    if verdict == "fail":
        classes.append("is-fail")
    if env == report["reference"]:
        classes.append("is-reference")
    lines = [f"<strong>{escape(env)}</strong>"]
    if cell is None:
        lines.append("no screenshot")
    else:
        src = f"{tiles_base.rstrip('/')}/tiles/{adapter}/{env}.png"
        lines.append(f'<img src="{escape(src, quote=True)}" alt="{escape(adapter)} on {escape(env)}" loading="lazy">')
        diff = cell.get("difference")
        lines.append("reference" if env == report["reference"] else
                     "no reference" if not diff else f"MAE {diff['rgb_mae']:.1f}")
    if verdict:
        lines.append(escape(verdict) + (f" · build {escape(build[:12])}" if build else ""))
    attr = f' class="{" ".join(classes)}"' if classes else ""
    return f"<li{attr}>" + "<br>".join(lines) + "</li>"


def viewer(pages, report, dataset=None, *, tiles_base=".", theme="github-like", asset_base=".", embed_css=False,
           layouts=None, candidates=None):
    if theme not in THEMES:
        raise ValueError("unknown theme")
    if report.get("schema") != "ironmate-browser-matrix/1":
        raise ValueError("report must be ironmate-browser-matrix/1")
    for value in (tiles_base, asset_base):
        if not isinstance(value, str) or not value or ":" in value or value.startswith("//") or any(
                c in value for c in '<>"\'\\?#\n\r'):
            raise ValueError("tiles_base and asset_base must be local paths")
    rows = pages.get("pages")
    if not isinstance(rows, list):
        raise ValueError("pages must list the representative pages")
    table = web_ui.route_table(rows)  # same rules as navigation.js: unique routes and emoji keys
    adapters = [row.get("adapter") for row in rows]
    if any(not isinstance(a, str) or not a for a in adapters) or len(set(adapters)) != len(adapters):
        raise ValueError("each page needs a distinct adapter id")
    cells = {(c["page"], c["env"]): c for c in report.get("cells", [])}
    verdicts = _verdicts(dataset)
    envs = report.get("envs", [])
    sections = []
    for row, entry, adapter in zip(rows, table, adapters):
        url = _https(row.get("url"))
        tiles = "".join(_tile(report, cells, verdicts, adapter, env, tiles_base) for env in envs)
        sections.append(
            f'<section id="{escape(entry["route"], quote=True)}" class="ui-panel">'
            f'<h2>{escape(entry["key"])} {escape(entry["label"] or adapter)}</h2>'
            f'<p class="ui-muted"><a href="{escape(url, quote=True)}">{escape(url)}</a> · adapter {escape(adapter)}</p>'
            f'<ul class="ui-matrix-tiles">{tiles}</ul></section>')
    unknown = sorted(set(report.get("pages", [])) - set(adapters))
    if embed_css:
        styles = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in (*ASSETS, f"css/themes/{theme}.css"))
        if "</style" in styles.lower():
            raise ValueError("unsafe stylesheet")
        css = "<style>" + styles + "</style>"
    else:
        prefix = asset_base.rstrip("/")
        css = "".join(f'<link rel="stylesheet" href="{escape(prefix + "/" + name, quote=True)}">'
                      for name in (*ASSETS, f"css/themes/{theme}.css"))
    # Layout presets switch the tile grid live (radio + CSS :has); the presets' own CSS is
    # generated from validated lengths, so it is inlined even when the shared CSS is linked.
    layouts = layouts if layouts is not None else json.loads(DEFAULT_LAYOUTS.read_text(encoding="utf-8"))
    css += "<style>" + layout_presets.css(layouts) + "</style>"
    switch = layout_presets.controls_html(layouts, candidates, legend="Tile layout")
    note = (f'<p class="ui-muted">Reference: {escape(report["reference"])}. '
            "Differences are tile-level hints, not pixel-exact gates. Mobile profiles are emulation.</p>")
    if unknown:
        note += f'<p class="ui-muted">Not in the page table: {escape(", ".join(unknown))}</p>'
    return ('<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Browser matrix</title>' + css + '</head>'
            f'<body data-ui-theme="{theme}"><main class="ui-page ui-matrix-page"><h1>Browser matrix</h1>' + note
            + web_ui.route_links([{k: r[k] for k in ("route", "key", "label") if r.get(k)} for r in rows],
                                 label="Pages")
            + switch + '<div class="ui-matrix">' + "".join(sections) + "</div></main></body></html>\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--dataset")
    parser.add_argument("--tiles-base", default=".", help="directory holding Ironmate's tiles/, relative to the output")
    parser.add_argument("--theme", choices=THEMES, default="github-like")
    parser.add_argument("--asset-base", default=".")
    parser.add_argument("--embed-css", action="store_true")
    parser.add_argument("--layouts", help="web-ui-layout-presets/1 (default examples/layout-presets.json)")
    parser.add_argument("--candidates", help="web-ui-layout-candidates/1 from layout_presets.py sweep, to label presets")
    args = parser.parse_args(argv)
    try:
        output = viewer(_load(args.pages, "web-ui-flutter-pages/1"), _load(args.report, "ironmate-browser-matrix/1"),
                        _load(args.dataset, "btk-platform-matrix/1") if args.dataset else None,
                        tiles_base=args.tiles_base, theme=args.theme, asset_base=args.asset_base,
                        embed_css=args.embed_css,
                        layouts=_load(args.layouts, "web-ui-layout-presets/1") if args.layouts else None,
                        candidates=_load(args.candidates, "web-ui-layout-candidates/1") if args.candidates else None)
    except (UnicodeError, ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"capture matrix: {exc}\n")
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
