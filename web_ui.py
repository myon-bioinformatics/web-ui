"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. This module never fetches assets or executes JavaScript.
"""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

THEMES = ("modern", "github-like")


def text_panel(text: str, *, heading: str = "") -> str:
    """Render user-controlled content as text using the stable v1 classes."""
    title = f'<h1 class="ui-title">{escape(heading)}</h1>' if heading else ""
    return f'<main class="ui-page"><section class="ui-panel">{title}<pre class="ui-output">{escape(text)}</pre></section></main>'


def shared_stylesheets(asset_base: str, *, theme: str = "modern", stub: bool = False) -> tuple[str, ...]:
    """Return local/HTTPS asset links; consumers own copying or exact-SHA pinning."""
    if theme not in THEMES:
        raise ValueError("unknown theme")
    base = urlsplit(asset_base)
    if (base.scheme and base.scheme != "https") or base.netloc and not base.scheme:
        raise ValueError("asset_base must be a local path or HTTPS URL")
    if base.query or base.fragment or base.username or base.password:
        raise ValueError("asset_base must not contain credentials, query or fragment")
    files = ["tokens.css", "base.css", "components.css"]
    if stub:
        files.append("stub.css")
    files.append(f"themes/{theme}.css")
    return tuple(f'{asset_base.rstrip("/")}/css/{name}' for name in files)


def render_document(text: str = "", *, title: str = "web-ui", theme: str = "modern",
                    css: str = "", stylesheets: tuple[str, ...] = (),
                    trusted_html: str | None = None) -> str:
    """Wrap escaped text or explicitly trusted HTML with CSS; no JS is injected.

    CSS is caller-authored. Reject an HTML raw-text terminator rather than allow
    it to escape the style element. Stylesheet links allow only local or HTTPS
    paths. This is an HTML emitter, not a general HTML/CSS sanitizer.
    """
    if theme not in THEMES:
        raise ValueError("unknown theme")
    if re.search(r"</style(?=[\s/>])", css, re.IGNORECASE):
        raise ValueError("CSS must not contain a style end tag")
    links = []
    for href in stylesheets:
        parsed = urlsplit(href)
        if (parsed.scheme and parsed.scheme != "https") or parsed.netloc and not parsed.scheme:
            raise ValueError("stylesheet must use a local path or HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("stylesheet must not contain credentials")
        links.append(f'<link rel="stylesheet" href="{escape(href, quote=True)}">')
    style = f'<style>{css}</style>' if css else ""
    body = text_panel(text, heading=title) if trusted_html is None else trusted_html
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title>{"".join(links)}{style}</head>'
            f'<body data-ui-theme="{theme}">{body}</body></html>\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="web-ui")
    parser.add_argument("--theme", choices=THEMES, default="modern")
    parser.add_argument("--css", type=Path, help="trusted CSS file to embed")
    parser.add_argument("--asset-base", help="local or pinned HTTPS shared asset directory")
    parser.add_argument("--stub", action="store_true", help="include stub CSS with --asset-base")
    parser.add_argument("--trusted-html", action="store_true", help="interpret stdin as authored HTML, not user text")
    args = parser.parse_args(argv)
    if args.stub and not args.asset_base:
        parser.error("--stub requires --asset-base")
    try:
        content = sys.stdin.read()
        css = args.css.read_text(encoding="utf-8") if args.css else ""
        styles = shared_stylesheets(args.asset_base, theme=args.theme, stub=args.stub) if args.asset_base else ()
        result = render_document(content, title=args.title, theme=args.theme, css=css,
                                 stylesheets=styles, trusted_html=content if args.trusted_html else None)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
