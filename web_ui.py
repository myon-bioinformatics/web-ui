"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. This module never fetches assets. JavaScript is omitted
by default; callers may opt in to local module script links. Node is wrapped
only as an explicit subprocess helper for pytest/CI one-liners.
"""
from __future__ import annotations

import argparse
import hashlib
import base64
from html import escape
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

THEMES = ("modern", "github-like")
# Snapshot of js/ui.js; update together with the upstream source and regression test.
EMBEDDED_UI_JS = "/** Set text-only content. User-controlled values are never interpreted as HTML. */\nexport function setText(target,value){const node=typeof target===\"string\"?document.querySelector(target):target;if(node)node.textContent=String(value)}\n/** Serialize a value for human-readable text output. */\nexport function prettyJson(value){return JSON.stringify(value,null,2)}\n/** Copy a value to the browser clipboard as text. */\nexport async function copyText(value){await navigator.clipboard.writeText(String(value))}\n"

SHARED_SCRIPT_NAMES = ("ui.js", "stub.js", "repository-diagnostics.js", "navigation.js")


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


def _require_local_script_path(value: str, *, label: str) -> None:
    # Check before urlsplit, which strips some whitespace/control characters.
    # Browsers also treat backslashes as slashes in HTTP(S) URL references.
    if (not value or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or "\\" in value or "?" in value or "#" in value):
        raise ValueError(f"{label} must be a local path without whitespace, controls, backslashes, query or fragment")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        raise ValueError(f"{label} must be a local path; remote scripts are not supported")


def shared_scripts(asset_base: str, *, names: tuple[str, ...] = ("ui.js",)) -> tuple[str, ...]:
    """Link named local modules; callers own vendoring, exact pins and serving.

    This validates path syntax and known names, not file contents or provenance.
    """
    _require_local_script_path(asset_base, label="asset_base")
    if not names:
        raise ValueError("names must not be empty")
    unknown = sorted(set(names) - set(SHARED_SCRIPT_NAMES))
    if unknown:
        raise ValueError(f"unknown shared script: {', '.join(unknown)}")
    return tuple(f'{asset_base.rstrip("/")}/js/{name}' for name in names)



def module_asset(name: str = "ui.js") -> tuple[bytes, str]:
    """Return immutable bundled module bytes and the JavaScript MIME type."""
    if name != "ui.js":
        raise ValueError("unknown embedded module")
    return EMBEDDED_UI_JS.encode("utf-8"), "text/javascript; charset=utf-8"


def module_script(source: str, *, mode: str = "inline", nonce: str | None = None) -> str:
    """Emit trusted ES module source without fetching or evaluating it in Python.

    Inline mode requires CSP script-src nonce/hash/unsafe-inline authorization.
    Data mode requires script-src data: and does not support relative imports.
    """
    if mode not in ("inline", "data"):
        raise ValueError("unknown module mode")
    if nonce is not None and (not nonce or not re.fullmatch(r"[A-Za-z0-9+/_=-]+", nonce)):
        raise ValueError("invalid CSP nonce")
    if mode == "data":
        if nonce is not None:
            raise ValueError("nonce is only supported for inline mode")
        encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
        return f'<script type="module" src="data:text/javascript;base64,{encoded}"></script>'
    if re.search(r"</script(?=[\s/>])", source, re.IGNORECASE):
        raise ValueError("module contains HTML script end tag")
    attribute = f' nonce="{escape(nonce, quote=True)}"' if nonce else ""
    return f'<script type="module"{attribute}>{source}</script>'


def module_csp_hash(source: str) -> str:
    """CSP sha256 source expression for an inline module's exact UTF-8 body."""
    digest = base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def render_document(
    text: str = "",
    *,
    title: str = "web-ui",
    theme: str = "modern",
    css: str = "",
    stylesheets: tuple[str, ...] = (),
    scripts: tuple[str, ...] = (),
    embedded_modules: tuple[str, ...] = (),
    module_mode: str = "inline",
    module_nonce: str | None = None,
    trusted_html: str | None = None,
) -> str:
    """Wrap escaped text or trusted HTML with CSS; scripts are opt-in links only.

    CSS is caller-authored. Reject an HTML raw-text terminator rather than allow
    it to escape the style element. Stylesheets allow local or HTTPS paths;
    scripts allow only local paths, without query/fragment. Callers own script
    contents, exact version pins, imports and serving without remote redirects.
    trusted_html is verbatim and may bypass these link checks (including via a
    base element); it must only contain caller-audited HTML. This is an HTML
    emitter, not a general HTML/CSS/JS sanitizer or provenance verifier.
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
        _require_local_script_path(src, label="script")
        script_tags.append(f'<script type="module" src="{escape(src, quote=True)}"></script>')
    if len(set(embedded_modules)) != len(embedded_modules):
        raise ValueError("duplicate embedded module")
    for name in embedded_modules:
        data, _ = module_asset(name)
        script_tags.append(module_script(data.decode("utf-8"), mode=module_mode, nonce=module_nonce))
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title>{"".join(links)}{style}</head>'
        f'<body data-ui-theme="{theme}">{body}{"".join(script_tags)}</body></html>\n'
    )


def _element_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        raise ValueError("element id must be an ASCII identifier")
    return value


def source_link(input_id: str, *, link_id: str = "source-open", label: str = "取得元サイトを新しいタブで開く ↗") -> str:
    """Link to a visitor-selected HTTP(S) input. No request until clicked.

    Pair with opt-in pinned navigation.js; invalid/empty inputs stay hidden.
    """
    return (f'<a id="{_element_id(link_id)}" class="ui-button" '
            f'data-ui-source-for="{_element_id(input_id)}" target="_blank" '
            f'rel="noopener noreferrer" referrerpolicy="no-referrer" hidden>'
            f'{escape(label)}</a>')


def view_tabs(views: tuple[tuple[str, str], ...], *, default_view: str = "home") -> str:
    """Escaped hash navigation; pair with declared data-ui-view panels and navigation.js."""
    names = [_element_id(name) for name, _ in views]
    if len(set(names)) != len(names) or default_view not in names:
        raise ValueError("views require unique names and an existing default")
    return f'<nav aria-label="Views" data-ui-default-view="{_element_id(default_view)}">' + ' '.join(
        f'<a class="ui-button" href="#{escape(name)}" data-ui-nav="{escape(name)}">{escape(label)}</a>'
        for name, label in views) + '</nav>'


def adopt_document(page: str, *, asset_base: str, class_aliases: dict[str, str] | None = None,
                   remove_stylesheets: tuple[str, ...] = (), theme: str = "modern") -> str:
    """Apply shared presentation to an audited, double-quoted static export.

    Preserve IDs, routes, script bodies and report content. This is not a
    visitor-input sanitizer or a general HTML parser. Consumers keep original
    hashes and label the transformed publication separately.
    """
    styles = shared_stylesheets(asset_base, theme=theme)
    aliases = class_aliases or {}
    if any(not re.fullmatch(r"[A-Za-z_][\w-]*", key) or
           any(not re.fullmatch(r"[A-Za-z_][\w-]*", value) for value in values.split())
           for key, values in aliases.items()):
        raise ValueError("class aliases must be CSS class identifiers")
    for name in remove_stylesheets:
        page = re.sub(r'<link\b[^>]*href="' + re.escape(name) + r'(?:\?[^"]*)?"[^>]*>', '', page)
    # Code typography belongs to the chosen shared theme; other Markdown CSS stays.
    page = re.sub(r'(pre, code\s*\{)\s*font-family:[^;]*;\s*(\})', r'\1 font-family: inherit; \2', page)
    def transform(match):
        tag, attrs = match.group(1), match.group(2)
        classes = re.search(r'\s+class="([^"]*)"', attrs)
        names = []
        if classes:
            names = [part for name in classes[1].split() for part in aliases.get(name, name).split()]
            attrs = attrs[:classes.start()] + attrs[classes.end():]
        required = {"button": "ui-button", "input": "ui-input", "textarea": "ui-input",
                    "select": "ui-input", "pre": "ui-output"}.get(tag)
        if required and required not in names:
            names.append(required)
        if tag == "body":
            attrs = re.sub(r'\sdata-ui-theme="[^"]*"', '', attrs) + f' data-ui-theme="{theme}"'
        if names:
            attrs += ' class="' + ' '.join(dict.fromkeys(names)) + '"'
        return '<' + tag + attrs + '>'
    chunks = re.split(r'(<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>)', page, flags=re.S)
    for index in range(0, len(chunks), 2):
        chunks[index] = re.sub(r'<(body|main|header|div|section|span|p|h[1-6]|pre|input|select|textarea|button)\b([^>]*)>',
                               transform, chunks[index])
    page = ''.join(chunks)
    links = ''.join(f'<link rel="stylesheet" href="{escape(path, quote=True)}" data-shared-ui="web-ui">' for path in styles)
    if 'data-shared-ui="web-ui"' not in page:
        if '</head>' not in page:
            raise ValueError("shared presentation requires a document head")
        page = page.replace('</head>', links + '</head>', 1)
    return page


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
        help="opt-in shared JS module names under js/ (requires local --asset-base; default ui.js)",
    )
    parser.add_argument("--embed-ui", action="store_true", help="embed the built-in ui.js ES module")
    parser.add_argument("--module-mode", choices=("inline", "data"), default="inline")
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
            embedded_modules=("ui.js",) if args.embed_ui else (),
            module_mode=args.module_mode,
            trusted_html=content if args.trusted_html else None,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
