"""Switchable layout presets: one JSON, CSS and radio controls that change layout live, and a sweep.

A preset is a named set of CSS custom properties. ``css()`` turns every preset into a
``body:has(input[name=ui-layout][value=ID]:checked)`` rule, so choosing a radio button
re-lays the page at once: no reload and no JavaScript, also from ``file://``.
``controls_html()`` renders the radios; given sweep results it labels each preset with the
widths where it held, without disabling any (a person may still prefer another one).

``sweep()`` (Playwright, imported lazily) opens a page at each width, clicks each preset's
radio like a person would, and checks the layout: no horizontal overflow, and the listed
items neither overlap nor leave the viewport. Several presets may pass; all passing presets
are candidates. js/layout-presets.cjs produces byte-identical CSS and controls for Node.

    python -S tool/layout_presets.py css examples/layout-presets.json
    python tool/layout_presets.py sweep viewer.html --presets examples/layout-presets.json \\
        --widths 320 384 768 1280 --items ".ui-matrix-tiles li" --out candidates.json
"""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re
import sys

SCHEMA = "web-ui-layout-presets/1"
CANDIDATES = "web-ui-layout-candidates/1"
_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")
_VAR = re.compile(r"--ui-[a-z][a-z0-9-]{0,47}")
_VALUE = re.compile(r"(?:0|\d{1,4}(?:\.\d{1,3})?(?:px|rem|em|%|vw|fr))")
MAX_PRESETS = 12


def validate(spec):
    """Checked ``{"default", "presets": [{"id", "label", "vars"}]}``; values are plain lengths only."""
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError(f"expected schema {SCHEMA}")
    presets = spec.get("presets")
    if not isinstance(presets, list) or not 1 <= len(presets) <= MAX_PRESETS:
        raise ValueError(f"presets must list 1..{MAX_PRESETS} entries")
    out, seen, names = [], set(), None
    for preset in presets:
        if not isinstance(preset, dict) or set(preset) - {"id", "label", "vars", "note"}:
            raise ValueError("a preset has id, label, vars and an optional note")
        pid, label, values = preset.get("id"), preset.get("label"), preset.get("vars")
        if not isinstance(pid, str) or not _ID.fullmatch(pid) or pid in seen:
            raise ValueError(f"preset id must be a unique lowercase token: {pid!r}")
        if not isinstance(label, str) or not label.strip() or len(label) > 60:
            raise ValueError(f"preset {pid}: label must be 1..60 characters")
        if not isinstance(values, dict) or not values:
            raise ValueError(f"preset {pid}: vars must be a nonempty object")
        for name, value in values.items():
            if not _VAR.fullmatch(name) or not isinstance(value, str) or not _VALUE.fullmatch(value):
                raise ValueError(f"preset {pid}: {name}: {value!r} is not a --ui-* length")
        if names is not None and set(values) != names:
            raise ValueError(f"preset {pid}: every preset must set the same variables")
        names = set(values)
        note = preset.get("note", "")
        if not isinstance(note, str) or len(note) > 120:
            raise ValueError(f"preset {pid}: note must be at most 120 characters")
        seen.add(pid)
        out.append({"id": pid, "label": label, "vars": dict(values), "note": note})
    default = spec.get("default", out[0]["id"])
    if default not in seen:
        raise ValueError(f"default preset {default!r} is not listed")
    return {"default": default, "presets": out}


def _decls(values):
    return ";".join(f"{name}:{value}" for name, value in values.items())


def css(spec):
    """CSS: the default preset on :root, then one rule per preset keyed on its checked radio."""
    data = validate(spec)
    default = next(p for p in data["presets"] if p["id"] == data["default"])
    rules = [":root{" + _decls(default["vars"]) + "}"]
    rules += [f'body:has(input[name="ui-layout"][value="{p["id"]}"]:checked){{{_decls(p["vars"])}}}'
              for p in data["presets"]]
    rules.append(".ui-layout-switch{display:flex;flex-wrap:wrap;gap:8px;border:1px solid var(--ui-border);"
                 "padding:8px;margin:16px 0}.ui-layout-switch label{display:inline-flex;gap:4px;align-items:center}"
                 ".ui-layout-switch small{color:var(--ui-muted)}")
    return "\n".join(rules) + "\n"


def _note(preset, candidates):
    if candidates is None:
        return preset["note"]
    row = candidates.get("presets", {}).get(preset["id"])
    if not row:
        return "not checked"
    passed, failed = row.get("passed", []), row.get("failed", [])
    parts = []
    if passed:
        parts.append("ok at " + ", ".join(f"{w}px" for w in passed))
    if failed:
        parts.append("check at " + ", ".join(f"{w}px" for w in failed))
    return "; ".join(parts)


def controls_html(spec, candidates=None, *, legend="Layout"):
    """Radio buttons, one per preset, the default checked; notes come from sweep candidates if given."""
    data = validate(spec)
    if candidates is not None and (not isinstance(candidates, dict) or candidates.get("schema") != CANDIDATES):
        raise ValueError(f"candidates must be {CANDIDATES}")
    items = []
    for p in data["presets"]:
        checked = " checked" if p["id"] == data["default"] else ""
        note = _note(p, candidates)
        items.append(f'<label><input type="radio" name="ui-layout" value="{p["id"]}"{checked}> '
                     f'{escape(p["label"])}' + (f" <small>{escape(note)}</small>" if note else "") + "</label>")
    return (f'<fieldset class="ui-layout-switch"><legend>{escape(legend)}</legend>' + "".join(items) + "</fieldset>")


_CHECK_JS = r"""items => {
  const failed = [], de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 0.5) failed.push('horizontal_overflow');
  const boxes = [...document.querySelectorAll(items)].filter(e => e.getClientRects().length)
    .map(e => e.getBoundingClientRect());
  boxes.forEach((r, i) => { if (r.left < -0.5 || r.right > innerWidth + 0.5) failed.push('outside:' + i); });
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 &&
        Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5) failed.push('overlap:' + i + ':' + j);
  }
  return {failed: failed.slice(0, 20), items: boxes.length};
}"""


def sweep(url, spec, widths, *, items, height=800, browser=None):
    """Try every preset at every width with a real click; all passing presets are candidates."""
    data = validate(spec)
    if not widths or any(type(w) is not int or not 240 <= w <= 3840 for w in widths):
        raise ValueError("widths must be integers from 240 to 3840")
    if not isinstance(items, str) or not items.strip():
        raise ValueError("items must be a CSS selector")
    from playwright.sync_api import sync_playwright
    rows = []
    with sync_playwright() as pw:
        engine = browser or pw.chromium.launch()
        try:
            for width in widths:
                page = engine.new_page(viewport={"width": width, "height": height})
                page.goto(url)
                for preset in data["presets"]:
                    page.locator(f'input[name="ui-layout"][value="{preset["id"]}"]').click()
                    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                    result = page.evaluate(_CHECK_JS, items)
                    rows.append({"preset": preset["id"], "width": width, "ok": not result["failed"],
                                 "failed": result["failed"], "items": result["items"]})
                page.close()
        finally:
            if browser is None:
                engine.close()
    return candidates(data, rows)


def candidates(data, rows):
    """``web-ui-layout-candidates/1``: per preset, the widths that passed and failed; per width, the passing presets."""
    presets = {p["id"]: {"passed": [], "failed": []} for p in data["presets"]}
    by_width = {}
    for row in rows:
        presets[row["preset"]]["passed" if row["ok"] else "failed"].append(row["width"])
        by_width.setdefault(str(row["width"]), [])
        if row["ok"]:
            by_width[str(row["width"])].append(row["preset"])
    return {"schema": CANDIDATES, "default": data["default"], "presets": presets, "by_width": by_width,
            "every_width_has_a_candidate": all(by_width.values()), "observations": rows}


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("css").add_argument("presets")
    h = sub.add_parser("html")
    h.add_argument("presets")
    h.add_argument("--candidates")
    s = sub.add_parser("sweep")
    s.add_argument("url", help="http(s) URL or a local HTML file")
    s.add_argument("--presets", required=True)
    s.add_argument("--widths", nargs="+", type=int, default=[320, 384, 768, 1280])
    s.add_argument("--items", required=True, help="CSS selector of the boxes that must not overlap")
    s.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if args.command == "css":
            sys.stdout.write(css(_load(args.presets)))
        elif args.command == "html":
            sys.stdout.write(controls_html(_load(args.presets), _load(args.candidates) if args.candidates else None)
                             + "\n")
        else:
            url = args.url if re.match(r"https?://", args.url) else Path(args.url).resolve().as_uri()
            result = sweep(url, _load(args.presets), args.widths, items=args.items)
            text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            for width, ids in result["by_width"].items():
                print(f"{width}px: {', '.join(ids) or 'no preset holds'}")
            return 0 if result["every_width_has_a_candidate"] else 1
    except (OSError, ValueError, UnicodeError) as exc:
        parser.exit(2, f"layout presets: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
