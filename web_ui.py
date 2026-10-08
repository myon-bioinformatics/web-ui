"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. This module never fetches assets. JavaScript is omitted
by default; callers may opt in to local/HTTPS module script links. Node is wrapped
only as an explicit subprocess helper for pytest/CI one-liners.
"""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

THEMES = ("modern", "github-like")
SHARED_SCRIPT_NAMES = ("ui.js", "stub.js", "repository-diagnostics.js")


def text_panel(text: str, *, heading: str = "") -> str:
    """Render user-controlled content as text using the stable v1 classes."""
    title = f'<h1 class="ui-title">{escape(heading)}</h1>' if heading else ""
    return f'<main class="ui-page"><section class="ui-panel">{title}<pre class="ui-output">{escape(text)}</pre></section></main>'


def _require_local_or_https(value: str, *, label: str, allow_query: bool = True) -> None:
    parsed = urlsplit(value)
    if (parsed.scheme and parsed.scheme != "https") or parsed.netloc and not parsed.scheme:
        raise ValueError(f"{label} must use a local path or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain credentials")
    if not allow_query and (parsed.query or parsed.fragment):
        raise ValueError(f"{label} must not contain credentials, query or fragment")


def shared_stylesheets(asset_base: str, *, theme: str = "modern", stub: bool = False) -> tuple[str, ...]:
    """Return local/HTTPS asset links; consumers own copying or exact-SHA pinning."""
    if theme not in THEMES:
        raise ValueError("unknown theme")
    _require_local_or_https(asset_base, label="asset_base", allow_query=False)
    files = ["tokens.css", "base.css", "components.css"]
    if stub:
        files.append("stub.css")
    files.append(f"themes/{theme}.css")
    return tuple(f'{asset_base.rstrip("/")}/css/{name}' for name in files)


def shared_scripts(asset_base: str, *, names: tuple[str, ...] = ("ui.js",)) -> tuple[str, ...]:
    """Return opt-in local/HTTPS ES module links for first-party lightweight JS."""
    _require_local_or_https(asset_base, label="asset_base", allow_query=False)
    if not names:
        raise ValueError("names must not be empty")
    unknown = sorted(set(names) - set(SHARED_SCRIPT_NAMES))
    if unknown:
        raise ValueError(f"unknown shared script: {', '.join(unknown)}")
    return tuple(f'{asset_base.rstrip("/")}/js/{name}' for name in names)


def render_document(
    text: str = "",
    *,
    title: str = "web-ui",
    theme: str = "modern",
    css: str = "",
    stylesheets: tuple[str, ...] = (),
    scripts: tuple[str, ...] = (),
    trusted_html: str | None = None,
) -> str:
    """Wrap escaped text or trusted HTML with CSS; scripts are opt-in links only.

    CSS is caller-authored. Reject an HTML raw-text terminator rather than allow
    it to escape the style element. Stylesheet and script links allow only local
    or HTTPS paths. No inline script body is injected. This is an HTML emitter,
    not a general HTML/CSS/JS sanitizer.
    """
    if theme not in THEMES:
        raise ValueError("unknown theme")
    if re.search(r"</style(?=[\s/>])", css, re.IGNORECASE):
        raise ValueError("CSS must not contain a style end tag")
    links = []
    for href in stylesheets:
        _require_local_or_https(href, label="stylesheet")
        links.append(f'<link rel="stylesheet" href="{escape(href, quote=True)}">')
    style = f"<style>{css}</style>" if css else ""
    body = text_panel(text, heading=title) if trusted_html is None else trusted_html
    script_tags = []
    for src in scripts:
        _require_local_or_https(src, label="script")
        script_tags.append(f'<script type="module" src="{escape(src, quote=True)}"></script>')
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title>{"".join(links)}{style}</head>'
        f'<body data-ui-theme="{theme}">{body}{"".join(script_tags)}</body></html>\n'
    )


def run_node(*argv: str | Path, timeout: float | None = 30) -> subprocess.CompletedProcess[str]:
    """Wrap `node` for pytest/CI one-liners. Does not start a browser or fetch URLs."""
    node = shutil.which("node")
    if node is None:
        raise FileNotFoundError("node executable not found on PATH")
    return subprocess.run(
        [node, *[str(argument) for argument in argv]],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="web-ui")
    parser.add_argument("--theme", choices=THEMES, default="modern")
    parser.add_argument("--css", type=Path, help="trusted CSS file to embed")
    parser.add_argument("--asset-base", help="local or pinned HTTPS shared asset directory")
    parser.add_argument("--stub", action="store_true", help="include stub CSS with --asset-base")
    parser.add_argument(
        "--with-scripts",
        nargs="*",
        metavar="NAME",
        help="opt-in shared JS module names under js/ (requires --asset-base; default ui.js)",
    )
    parser.add_argument("--trusted-html", action="store_true", help="interpret stdin as authored HTML, not user text")
    args = parser.parse_args(argv)
    if args.stub and not args.asset_base:
        parser.error("--stub requires --asset-base")
    if args.with_scripts is not None and not args.asset_base:
        parser.error("--with-scripts requires --asset-base")
    try:
        content = sys.stdin.read()
        css = args.css.read_text(encoding="utf-8") if args.css else ""
        styles = shared_stylesheets(args.asset_base, theme=args.theme, stub=args.stub) if args.asset_base else ()
        if args.with_scripts is None:
            scripts: tuple[str, ...] = ()
        else:
            names = tuple(args.with_scripts) if args.with_scripts else ("ui.js",)
            scripts = shared_scripts(args.asset_base, names=names)
        result = render_document(
            content,
            title=args.title,
            theme=args.theme,
            css=css,
            stylesheets=styles,
            scripts=scripts,
            trusted_html=content if args.trusted_html else None,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
