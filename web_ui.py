"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. Rendering never fetches assets; fetch_plotly_js() is an
explicit download helper with bounded reads. JavaScript is omitted
by default; callers may opt in to local module script links. Node is wrapped
only as an explicit subprocess helper for pytest/CI one-liners.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import http.client
import importlib.util
import json
import math
import base64
import os
from html import escape
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlsplit

THEMES = ("modern", "github-like")
# Snapshot of js/ui.js; update together with the upstream source and regression test.
EMBEDDED_UI_JS = "/** Set text-only content. User-controlled values are never interpreted as HTML. */\nexport function setText(target,value){const node=typeof target===\"string\"?document.querySelector(target):target;if(node)node.textContent=String(value)}\n/** Serialize a value for human-readable text output. */\nexport function prettyJson(value){return JSON.stringify(value,null,2)}\n/** Copy a value to the browser clipboard as text. */\nexport async function copyText(value){await navigator.clipboard.writeText(String(value))}\n"

SHARED_SCRIPT_NAMES = ("ui.js", "stub.js", "repository-diagnostics.js", "navigation.js", "controls.js")
# Pinned browser bundle for PptxGenJS 4.0.1, including its JSZip dependency.
# sha384 covers the exact bytes of that jsDelivr URL (immutable npm version).
_PPTXGENJS_URL = "https://cdn.jsdelivr.net/npm/pptxgenjs@4.0.1/dist/pptxgen.bundle.js"
_PPTXGENJS_SRI = "sha384-qb0Xhi7LLYpvW1HCK6oMrmDLSY9sy7vwm6ZlV6KjtrlL9yg30+YN4neTwnmX+Kp8"
# jsDelivr resolves plotly.js-dist-min to the latest npm release (not plotly-latest).
PLOTLY_JS_URL = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min/plotly.min.js"
PLOTLY_JS_MAX_BYTES = 8 * 1024 * 1024
# Explicit HTTPS allowlist for opt-in remote classic scripts (not ES modules).
REMOTE_SCRIPT_NAMES: dict[str, str] = {
    "plotly.js": PLOTLY_JS_URL,
    "pptxgenjs": _PPTXGENJS_URL,
}
# Pinned remote entries carry Subresource Integrity; unpinned plotly.js does not.
REMOTE_SCRIPT_INTEGRITY: dict[str, str] = {
    _PPTXGENJS_URL: _PPTXGENJS_SRI,
}
_PPTX_LAYOUTS = frozenset({"LAYOUT_4x3", "LAYOUT_16x9", "LAYOUT_16x10", "LAYOUT_WIDE"})
_PPTX_DASHES = frozenset({"solid", "dash", "dashDot", "lgDash", "lgDashDot", "lgDashDotDot", "sysDash", "sysDot"})
_PPTX_ALIGNS = frozenset({"left", "center", "right", "justify"})
_PPTX_VALIGNS = frozenset({"top", "middle", "bottom"})
_PPTX_ARROW_KEYS = frozenset({"beginArrowType", "endArrowType", "lineHead", "lineTail"})
_PPTX_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.pptx\Z")
_PPTX_SHAPE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,40}\Z")
_PPTX_HEX = re.compile(r"#?([0-9A-Fa-f]{6})\Z")
_PPTX_DEFAULT_COLOR = "000000"
# PptxGenJS writes one fontFace into the Latin, East Asian, and complex-script slots.
# Meiryo is that face; メイリオ is the same family. Callers may override fontFace.
_PPTX_DEFAULT_FONT = "Meiryo"
# Same stack as the --ui-font token in css/tokens.css (tests/test_font.py keeps them equal).
# Plotly cannot read CSS variables, so plotly_figure supplies it as the default layout font family.
UI_FONT = "Meiryo, メイリオ, sans-serif"
_PPTX_DEFAULT_LINE_WIDTH = 1.25
_PPTX_MIN_DISTANCE = 1e-6
_PPTX_DATA_IMAGE = re.compile(r"(?:data:)?(image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+)\Z")


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


def _allowed_remote_script_urls() -> frozenset[str]:
    return frozenset(REMOTE_SCRIPT_NAMES.values())


def _require_allowed_remote_script(value: str, *, label: str) -> None:
    _require_local_or_https(value, label=label, allow_query=False)
    if value not in _allowed_remote_script_urls():
        raise ValueError(f"{label} must be an opt-in remote script from remote_scripts()")


def remote_script_tag(src: str) -> str:
    _require_allowed_remote_script(src, label="remote script")
    attributes = f' src="{escape(src, quote=True)}"'
    integrity = REMOTE_SCRIPT_INTEGRITY.get(src)
    if integrity:
        attributes += f' integrity="{escape(integrity, quote=True)}" crossorigin="anonymous"'
    return f"<script{attributes}></script>"


def remote_scripts(*names: str) -> tuple[str, ...]:
    """Return HTTPS script URLs from an explicit, documented allowlist.

    These are classic (non-module) scripts loaded from a remote origin. They are
    intentionally separate from ``shared_scripts()`` so remote execution stays an
    explicit consumer choice. Callers own network access and CSP. Pinned entries
    (for example pptxgenjs) are emitted with Subresource Integrity and anonymous
    CORS; plotly.js is unpinned and has no integrity attribute.
    """
    if not names:
        raise ValueError("names must not be empty")
    unknown = sorted({name for name in names if name not in REMOTE_SCRIPT_NAMES})
    if unknown:
        raise ValueError(f"unknown remote script: {', '.join(unknown)}")
    return tuple(REMOTE_SCRIPT_NAMES[name] for name in names)


_INTEGRITY = re.compile(r"(sha256|sha384|sha512)-([A-Za-z0-9+/]+={0,2})\Z")
_ALGORITHM_NAMES = {"sha256": "SHA-256", "sha384": "SHA-384", "sha512": "SHA-512"}


def sri(raw: bytes, algorithm: str = "sha384") -> str:
    """Subresource Integrity value (``sha384-...``) for exact bytes, for pinning a new asset."""
    if not isinstance(raw, bytes):
        raise TypeError("payload must be bytes")
    if algorithm not in _ALGORITHM_NAMES:
        raise ValueError("algorithm must be sha256, sha384 or sha512")
    return f"{algorithm}-" + base64.b64encode(hashlib.new(algorithm, raw).digest()).decode("ascii")


def _parse_integrity(integrity: str) -> tuple[str, bytes]:
    if isinstance(integrity, str) and re.fullmatch(r"[0-9a-f]{64}", integrity):
        return "sha256", bytes.fromhex(integrity)
    match = _INTEGRITY.match(integrity) if isinstance(integrity, str) else None
    if not match:
        raise ValueError("integrity must be 64 lowercase hex (SHA-256) or sha256-/sha384-/sha512- SRI")
    digest = base64.b64decode(match.group(2), validate=True)
    if len(digest) != hashlib.new(match.group(1)).digest_size:
        raise ValueError("integrity digest has the wrong length")
    return match.group(1), digest


def verify_pinned_asset(raw: bytes, integrity: str, *, max_bytes: int = PLOTLY_JS_MAX_BYTES,
                        label: str = "asset") -> bytes:
    """Return ``raw`` only if it matches ``integrity``; fail before any decoding, caching or execution.

    ``integrity`` is a 64-hex SHA-256 or an SRI value (``sha256-``/``sha384-``/``sha512-``),
    so the same pin serves the ``<script integrity>`` attribute and offline embedding.
    """
    algorithm, expected = _parse_integrity(integrity)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if not isinstance(raw, bytes):
        raise TypeError(f"{label} payload must be bytes")
    if not raw:
        raise RuntimeError(f"{label}: empty body")
    if len(raw) > max_bytes:
        raise RuntimeError(f"{label} exceeds {max_bytes} byte limit")
    actual = hashlib.new(algorithm, raw).digest()
    if not hmac.compare_digest(actual, expected):
        shown = actual.hex() if algorithm == "sha256" else base64.b64encode(actual).decode("ascii")
        raise RuntimeError(f"{label} {_ALGORITHM_NAMES[algorithm]} mismatch: {shown}")
    return raw


def fetch_pinned_asset(url: str, integrity: str, *, max_bytes: int = PLOTLY_JS_MAX_BYTES,
                       timeout: float = 60.0, label: str | None = None) -> bytes:
    """Explicitly fetch fixed HTTPS bytes and verify them; never accept alternate or partial bytes.

    Rendering helpers do not call this. Consumers own caching of verified bytes and can
    re-check cached or local copies with verify_pinned_asset().
    """
    label = label or url
    _parse_integrity(integrity)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if urlsplit(url).scheme != "https":
        raise ValueError("url must be https")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    request = urllib.request.Request(url, headers={"User-Agent": "web-ui/1.0 (verified asset)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status if hasattr(response, "status") else response.getcode()
            if status != 200:
                raise RuntimeError(f"{label} returned HTTP {status} for {url}")
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{label} request failed: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{label} request failed: {exc.reason}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise RuntimeError(f"{label} request failed: {exc}") from exc
    return verify_pinned_asset(raw, integrity, max_bytes=max_bytes, label=label)


def verify_remote_script(name: str, raw: bytes) -> bytes:
    """Verify local bytes of an allowlisted remote script (e.g. ``pptxgenjs``) against its pinned SRI."""
    if name not in REMOTE_SCRIPT_NAMES:
        raise ValueError(f"unknown remote script: {name}")
    url = REMOTE_SCRIPT_NAMES[name]
    if url not in REMOTE_SCRIPT_INTEGRITY:
        raise ValueError(f"remote script is not pinned: {name}")
    return verify_pinned_asset(raw, REMOTE_SCRIPT_INTEGRITY[url], label=name)


def verify_plotly_js(raw: bytes) -> bytes:
    """Return CDN bytes or fail before any decoding, caching or execution."""
    if not isinstance(raw, bytes):
        raise TypeError("Plotly.js payload must be bytes")
    if not raw:
        raise RuntimeError("Plotly.js CDN returned an empty body")
    if len(raw) > PLOTLY_JS_MAX_BYTES:
        raise RuntimeError(f"Plotly.js exceeds {PLOTLY_JS_MAX_BYTES} byte limit")
    return raw


def fetch_plotly_js(*, timeout: float = 60.0) -> bytes:
    """Explicitly fetch the allowlisted jsDelivr bundle with a bounded read.

    Rendering helpers do not call this function. Consumers own successful-byte
    caching; cached/local bytes can be checked with verify_plotly_js().
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    request = urllib.request.Request(
        PLOTLY_JS_URL, headers={"User-Agent": "web-ui/1.0 (verified Plotly embed)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status if hasattr(response, "status") else response.getcode()
            if status != 200:
                raise RuntimeError(f"Plotly.js CDN returned HTTP {status} for {PLOTLY_JS_URL}")
            raw = response.read(PLOTLY_JS_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Plotly.js CDN request failed: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Plotly.js CDN request failed: {exc.reason}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise RuntimeError(f"Plotly.js CDN request failed: {exc}") from exc
    return verify_plotly_js(raw)


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


def classic_script(source: str, *, nonce: str | None = None) -> str:
    """Emit trusted classic JavaScript without fetching or evaluating it in Python.

    Inline bodies require CSP script-src nonce/hash/unsafe-inline authorization.
    """
    if nonce is not None and (not nonce or not re.fullmatch(r"[A-Za-z0-9+/_=-]+", nonce)):
        raise ValueError("invalid CSP nonce")
    if re.search(r"</script(?=[\s/>])", source, re.IGNORECASE):
        raise ValueError("script contains HTML script end tag")
    attribute = f' nonce="{escape(nonce, quote=True)}"' if nonce else ""
    return f"<script{attribute}>{source}</script>"


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
    remote_scripts: tuple[str, ...] = (),
    embedded_modules: tuple[str, ...] = (),
    module_mode: str = "inline",
    module_nonce: str | None = None,
    trusted_html: str | None = None,
) -> str:
    """Wrap escaped text or trusted HTML with CSS; scripts are opt-in links only.

    CSS is caller-authored. Reject an HTML raw-text terminator rather than allow
    it to escape the style element. Stylesheets allow local or HTTPS paths;
    scripts allow only local paths, without query/fragment. ``remote_scripts``
    accepts only URLs returned by ``remote_scripts()`` (explicit HTTPS allowlist).
    Remote classic scripts are emitted in ``<head>`` so body inline initializers
    can depend on them. Pinned allowlist entries include integrity and anonymous
    CORS; plotly.js is unpinned without integrity. Callers own script contents,
    imports and
    serving without remote redirects.
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
    head_remote_scripts = [remote_script_tag(src) for src in remote_scripts]
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
        f'<title>{escape(title)}</title>{"".join(links)}{style}{"".join(head_remote_scripts)}</head>'
        f'<body data-ui-theme="{theme}">{body}{"".join(script_tags)}</body></html>\n'
    )


def _element_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        raise ValueError("element id must be an ASCII identifier")
    return value


def badge(text: str) -> str:
    """Escaped badge/tag using the stable v1 .ui-tag class."""
    return f'<span class="ui-tag">{escape(text)}</span>'


def card(
    text: str = "", *, title: str | None = None, trusted_html: str | None = None, heading_level: int = 2
) -> str:
    """Escaped text or trusted HTML container using the stable v1 .ui-card class.

    ``heading_level`` (1-6) sets the title element so the card fits the page outline.
    Pass either ``text`` or ``trusted_html``, not both.
    """
    if type(heading_level) is not int or not 1 <= heading_level <= 6:
        raise ValueError("heading_level must be an integer from 1 to 6")
    if trusted_html is not None and text:
        raise ValueError("pass either text or trusted_html, not both")
    heading = f"<h{heading_level}>{escape(title)}</h{heading_level}>" if title else ""
    body = escape(text) if trusted_html is None else trusted_html
    return f'<article class="ui-card">{heading}{body}</article>'


def button(label: str, *, id: str | None = None, type: str = "button", disabled: bool = False) -> str:
    """An escaped native button; custom actions remain consumer-owned."""
    if type not in ("button", "submit", "reset"):
        raise ValueError("unknown button type")
    identity = f' id="{_element_id(id)}"' if id is not None else ""
    return f'<button class="ui-button" type="{type}"{identity}{" disabled" if disabled else ""}>{escape(label)}</button>'


def select(options: tuple[tuple[str, str], ...], *, id: str, label: str,
           selected: str | None = None, disabled: bool = False) -> str:
    """Labeled native dropdown. Values must be unique; labels stay plain text."""
    identity = _element_id(id)
    values = [value for value, _ in options]
    if len(set(values)) != len(values) or (selected is not None and selected not in values):
        raise ValueError("options require unique values and an existing selection")
    items = ''.join(f'<option value="{escape(value, quote=True)}"{" selected" if value == selected else ""}>{escape(text)}</option>'
                    for value, text in options)
    return (f'<label for="{identity}">{escape(label)}</label> '
            f'<select class="ui-input" id="{identity}" name="{identity}"{" disabled" if disabled else ""}>{items}</select>')


def input_field(*, id: str, label: str, value: str = "", type: str = "text",
                required: bool = False) -> str:
    """Labeled native text/search/email/URL/number/date/password input."""
    if type not in ("text", "search", "email", "url", "number", "date", "password"):
        raise ValueError("unknown input type")
    identity = _element_id(id)
    return (f'<label for="{identity}">{escape(label)}</label> '
            f'<input class="ui-input" id="{identity}" name="{identity}" type="{type}" '
            f'value="{escape(value, quote=True)}"{" required" if required else ""}>')


def textarea(*, id: str, label: str, value: str = "", rows: int = 8) -> str:
    """Labeled, escaped multiline input."""
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        raise ValueError("rows must be a positive integer")
    identity = _element_id(id)
    return (f'<label for="{identity}">{escape(label)}</label> '
            f'<textarea class="ui-input" id="{identity}" name="{identity}" rows="{rows}">{escape(value)}</textarea>')


def checkbox(label: str, *, id: str, checked: bool = False) -> str:
    """Native checkbox with an associated text label."""
    identity = _element_id(id)
    return (f'<label for="{identity}"><input type="checkbox" id="{identity}" name="{identity}"'
            f'{" checked" if checked else ""}> {escape(label)}</label>')


def details(summary: str, text: str = "", *, open: bool = False, trusted_html: str | None = None) -> str:
    """Native disclosure, without JS. Pass renderer output via trusted_html explicitly."""
    body = f'<pre class="ui-output">{escape(text)}</pre>' if trusted_html is None else trusted_html
    return f'<details class="ui-panel"{" open" if open else ""}><summary>{escape(summary)}</summary>{body}</details>'


def plotly_figure(
    spec: dict,
    *,
    div_id: str = "plot",
    height: int | None = 400,
    width: int | None = None,
    nonce: str | None = None,
) -> str:
    """Trusted HTML: a Plotly graph container plus an inline ``Plotly.newPlot`` call.

    Pass a Plotly figure JSON object ``{"data": [...], "layout": {...}, "config": {...}}``.
    Pair with ``remote_scripts("plotly.js")`` in ``render_document`` so plotly.js loads
    from the documented CDN URL before this initializer runs. ``layout.font.family`` defaults
    to ``UI_FONT`` (Meiryo first); any font keys the figure sets itself are kept.
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a mapping")
    data = spec.get("data", [])
    if not isinstance(data, list):
        raise ValueError("spec data must be a list")
    layout = dict(spec.get("layout") or {})
    font = layout.get("font") or {}
    if not isinstance(font, dict):
        raise ValueError("spec layout font must be a mapping")
    layout["font"] = {"family": UI_FONT, **font}  # the figure's own font keys win
    config = dict(spec.get("config") or {})
    if height is not None:
        if isinstance(height, bool) or not isinstance(height, int) or height < 1:
            raise ValueError("height must be a positive integer")
        layout["height"] = height
    if width is not None:
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise ValueError("width must be a positive integer")
        layout["width"] = width
    identity = _element_id(div_id)
    payload = json.dumps({"data": data, "layout": layout, "config": config}, ensure_ascii=True)
    initializer = (
        f'(function(){{var s={payload};var el=document.getElementById("{identity}");'
        f'if(el&&window.Plotly){{window.Plotly.newPlot(el,s.data,s.layout,s.config);}}}})();'
    )
    return f'<div id="{identity}" class="ui-panel"></div>{classic_script(initializer, nonce=nonce)}'


def _pptx_round(value: float) -> float:
    return round(float(value), 6)


def _pptx_number(value, *, label: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum}")
    return number


def _pptx_positive(value, *, label: str) -> float:
    number = _pptx_number(value, label=label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _pptx_text(value, *, label: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{label} must be a string of at most {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t\r" or ord(char) == 127 for char in value):
        raise ValueError(f"{label} must be plain text")
    return value


def _pptx_color(value, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a hex color")
    match = _PPTX_HEX.fullmatch(value.strip())
    if not match:
        raise ValueError(f"{label} must be a 6-digit hex color")
    return match.group(1).upper()


def _pptx_unknown(mapping: dict, allowed: set[str], *, label: str) -> None:
    extra = sorted(set(mapping) - allowed)
    if extra:
        raise ValueError(f"unknown {label}: {', '.join(extra)}")


def _pptx_reject_arrow_keys(value, *, label: str) -> None:
    if isinstance(value, dict):
        found = sorted(_PPTX_ARROW_KEYS.intersection(value))
        if found:
            raise ValueError(f"{label} cannot set built-in line arrow keys; use pptx_connector()")
        for item in value.values():
            _pptx_reject_arrow_keys(item, label=label)
    elif isinstance(value, list):
        for item in value:
            _pptx_reject_arrow_keys(item, label=label)


def _pptx_fill(value, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    _pptx_unknown(value, {"color", "transparency"}, label=label)
    fill = {"color": _pptx_color(value.get("color"), label=f"{label} color")}
    if "transparency" in value:
        fill["transparency"] = _pptx_number(value["transparency"], label=f"{label} transparency", minimum=0, maximum=100)
    return fill


def _pptx_font_face(value, *, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise ValueError(f"{label} must be a font name")
    if any(ord(char) < 32 or ord(char) == 127 or char in "<>" for char in value):
        raise ValueError(f"{label} must be a font name")
    return value


def _pptx_no_fill() -> dict:
    return {"type": "none"}


def _pptx_default_line() -> dict:
    return {"type": "solid", "color": _PPTX_DEFAULT_COLOR, "width": _PPTX_DEFAULT_LINE_WIDTH}


def _pptx_line_style(value, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    _pptx_reject_arrow_keys(value, label=label)
    _pptx_unknown(value, {"type", "color", "width", "dashType"}, label=label)
    style = _pptx_default_line()
    if "type" in value:
        if value["type"] not in ("none", "solid"):
            raise ValueError(f"{label} type must be none or solid")
        style["type"] = value["type"]
    if "color" in value:
        style["color"] = _pptx_color(value["color"], label=f"{label} color")
    if "width" in value:
        style["width"] = _pptx_positive(value["width"], label=f"{label} width")
    if "dashType" in value:
        if value["dashType"] not in _PPTX_DASHES:
            raise ValueError(f"{label} dashType is not supported")
        style["dashType"] = value["dashType"]
    return style


def _pptx_bool(value, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _pptx_line_box(x1: float, y1: float, x2: float, y2: float, *, color: str, width: float) -> dict:
    """Straight line as a non-negative box plus flip, with no arrow styling."""
    main_diagonal = (x1 <= x2 and y1 <= y2) or (x1 >= x2 and y1 >= y2)
    return {
        "x": _pptx_round(min(x1, x2)),
        "y": _pptx_round(min(y1, y2)),
        "w": _pptx_round(abs(x2 - x1)),
        "h": _pptx_round(abs(y2 - y1)),
        "flipH": not main_diagonal,
        "flipV": False,
        "line": {"type": "solid", "color": color, "width": width},
    }


def _pptx_box(item: dict, *, label: str, require_height: bool = True) -> dict:
    box = {
        "x": _pptx_number(item.get("x"), label=f"{label} x"),
        "y": _pptx_number(item.get("y"), label=f"{label} y"),
        "w": _pptx_positive(item.get("w"), label=f"{label} w"),
    }
    if require_height or "h" in item:
        box["h"] = _pptx_positive(item.get("h"), label=f"{label} h")
    return box


def _pptx_text_options(raw, position: dict) -> dict:
    options = dict(position)
    options["color"] = _PPTX_DEFAULT_COLOR
    options["fontFace"] = _PPTX_DEFAULT_FONT
    options["fill"] = _pptx_no_fill()
    options["line"] = _pptx_default_line()
    if not raw:
        return options
    if not isinstance(raw, dict):
        raise ValueError("text options must be a mapping")
    _pptx_reject_arrow_keys(raw, label="text options")
    _pptx_unknown(raw, {"fontSize", "fontFace", "bold", "italic", "color", "align", "valign", "fill", "line", "shape", "margin"},
                  label="text options")
    if "fontSize" in raw:
        options["fontSize"] = _pptx_number(raw["fontSize"], label="fontSize", minimum=1, maximum=256)
    if "fontFace" in raw:
        options["fontFace"] = _pptx_font_face(raw["fontFace"], label="fontFace")
    if "bold" in raw:
        options["bold"] = _pptx_bool(raw["bold"], label="bold")
    if "italic" in raw:
        options["italic"] = _pptx_bool(raw["italic"], label="italic")
    if "color" in raw:
        options["color"] = _pptx_color(raw["color"], label="text color")
    if "align" in raw:
        if raw["align"] not in _PPTX_ALIGNS:
            raise ValueError("align must be left, center, right, or justify")
        options["align"] = raw["align"]
    if "valign" in raw:
        if raw["valign"] not in _PPTX_VALIGNS:
            raise ValueError("valign must be top, middle, or bottom")
        options["valign"] = raw["valign"]
    if "fill" in raw:
        options["fill"] = _pptx_fill(raw["fill"], label="text fill")
    if "line" in raw:
        options["line"] = _pptx_line_style(raw["line"], label="text line")
    if "shape" in raw:
        if not isinstance(raw["shape"], str) or not _PPTX_SHAPE.fullmatch(raw["shape"]):
            raise ValueError("text shape must be a shape name")
        options["shape"] = raw["shape"]
    if "margin" in raw:
        options["margin"] = _pptx_number(raw["margin"], label="margin", minimum=0, maximum=5)
    return options


def _pptx_shape_options(raw, position: dict) -> dict:
    options = dict(position)
    options["fill"] = _pptx_no_fill()
    options["line"] = _pptx_default_line()
    if not raw:
        return options
    if not isinstance(raw, dict):
        raise ValueError("shape options must be a mapping")
    _pptx_reject_arrow_keys(raw, label="shape options")
    _pptx_unknown(raw, {"fill", "line", "rectRadius", "rotate"}, label="shape options")
    if "fill" in raw:
        options["fill"] = _pptx_fill(raw["fill"], label="shape fill")
    if "line" in raw:
        options["line"] = _pptx_line_style(raw["line"], label="shape line")
    if "rectRadius" in raw:
        options["rectRadius"] = _pptx_number(raw["rectRadius"], label="rectRadius", minimum=0, maximum=1)
    if "rotate" in raw:
        options["rotate"] = _pptx_number(raw["rotate"], label="rotate", minimum=-360, maximum=360)
    return options


def _pptx_cell(cell, *, label: str, color: str, font_face: str, fill: dict) -> dict:
    options = {"color": color, "fontFace": font_face, "fill": dict(fill)}
    if isinstance(cell, str):
        return {"text": _pptx_text(cell, label=label, limit=2000), "options": options}
    if not isinstance(cell, dict):
        raise ValueError(f"{label} must be a string or a cell mapping")
    _pptx_unknown(cell, {"text", "options"}, label=label)
    result = {"text": _pptx_text(cell.get("text"), label=label, limit=2000), "options": options}
    raw = cell.get("options") or {}
    if not raw:
        return result
    if not isinstance(raw, dict):
        raise ValueError(f"{label} options must be a mapping")
    _pptx_unknown(raw, {"bold", "color", "align", "fontSize", "fontFace", "fill"}, label=f"{label} options")
    if "bold" in raw:
        options["bold"] = _pptx_bool(raw["bold"], label="bold")
    if "color" in raw:
        options["color"] = _pptx_color(raw["color"], label="cell color")
    if "align" in raw:
        if raw["align"] not in _PPTX_ALIGNS:
            raise ValueError("align must be left, center, right, or justify")
        options["align"] = raw["align"]
    if "fontSize" in raw:
        options["fontSize"] = _pptx_number(raw["fontSize"], label="fontSize", minimum=1, maximum=256)
    if "fontFace" in raw:
        options["fontFace"] = _pptx_font_face(raw["fontFace"], label="fontFace")
    if "fill" in raw:
        options["fill"] = _pptx_fill(raw["fill"], label="cell fill")
    return result


def _pptx_table_options(raw, position: dict, *, columns: int) -> dict:
    options = dict(position)
    options["color"] = _PPTX_DEFAULT_COLOR
    options["fontFace"] = _PPTX_DEFAULT_FONT
    options["fill"] = _pptx_no_fill()
    options["border"] = {"color": _PPTX_DEFAULT_COLOR, "pt": _PPTX_DEFAULT_LINE_WIDTH}
    if not raw:
        return options
    if not isinstance(raw, dict):
        raise ValueError("table options must be a mapping")
    _pptx_unknown(raw, {"colW", "border", "fill", "fontSize", "fontFace", "color", "align", "valign", "bold", "margin"},
                  label="table options")
    if "colW" in raw:
        widths = raw["colW"]
        if isinstance(widths, bool) or isinstance(widths, (int, float)):
            options["colW"] = _pptx_positive(widths, label="colW")
        elif isinstance(widths, list):
            if len(widths) != columns:
                raise ValueError("colW must match the column count")
            options["colW"] = [_pptx_positive(width, label="colW") for width in widths]
        else:
            raise ValueError("colW must be a number or a list of numbers")
    if "border" in raw:
        border = raw["border"]
        if not isinstance(border, dict):
            raise ValueError("border must be a mapping")
        _pptx_unknown(border, {"color", "pt"}, label="border")
        if "color" in border:
            options["border"]["color"] = _pptx_color(border["color"], label="border color")
        if "pt" in border:
            options["border"]["pt"] = _pptx_positive(border["pt"], label="border pt")
    if "fill" in raw:
        options["fill"] = _pptx_fill(raw["fill"], label="table fill")
    if "fontFace" in raw:
        options["fontFace"] = _pptx_font_face(raw["fontFace"], label="fontFace")
    if "fontSize" in raw:
        options["fontSize"] = _pptx_number(raw["fontSize"], label="fontSize", minimum=1, maximum=256)
    if "color" in raw:
        options["color"] = _pptx_color(raw["color"], label="table color")
    if "align" in raw:
        if raw["align"] not in _PPTX_ALIGNS:
            raise ValueError("align must be left, center, right, or justify")
        options["align"] = raw["align"]
    if "valign" in raw:
        if raw["valign"] not in _PPTX_VALIGNS:
            raise ValueError("valign must be top, middle, or bottom")
        options["valign"] = raw["valign"]
    if "bold" in raw:
        options["bold"] = _pptx_bool(raw["bold"], label="bold")
    if "margin" in raw:
        options["margin"] = _pptx_number(raw["margin"], label="margin", minimum=0, maximum=5)
    return options


def _pptx_https_url(value, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an HTTPS URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{label} must be an HTTPS URL without credentials")
    return value


def _pptx_center(box: dict) -> tuple[float, float]:
    return (box["x"] + box["w"] / 2.0, box["y"] + box["h"] / 2.0)


def _pptx_boundary_toward(box: dict, toward: tuple[float, float]) -> tuple[float, float]:
    """Point where the ray from this box's center toward another point exits the box."""
    center_x, center_y = _pptx_center(box)
    delta_x = toward[0] - center_x
    delta_y = toward[1] - center_y
    if delta_x == 0 and delta_y == 0:
        raise ValueError("connector objects share a center")
    scale_x = (box["w"] / 2.0) / abs(delta_x) if delta_x else math.inf
    scale_y = (box["h"] / 2.0) / abs(delta_y) if delta_y else math.inf
    scale = min(scale_x, scale_y)
    return (center_x + delta_x * scale, center_y + delta_y * scale)


def pptx_arrow_geometry(
    source: dict,
    target: dict,
    *,
    mode: str = "edge",
    color: str = _PPTX_DEFAULT_COLOR,
    width: float = _PPTX_DEFAULT_LINE_WIDTH,
    head: float = 0.18,
) -> dict:
    """Line plus triangle arrowhead between two positioned boxes, in inches.

    ``mode="edge"`` joins the box edges crossed by the center-to-center ray
    (side-by-side boxes meet right-edge to left-edge; a box below another meets
    bottom to top). Overlapping, touching, and zero-length gaps raise
    ``ValueError``. ``mode="center"`` joins the centers and rejects a shared
    center. The arrowhead is an unfilled triangle centered on the midpoint,
    rotated to the line angle, with a separate black (or ``color``) stroke.
    This is not a PptxGenJS line arrow or connector shape.
    """
    if mode not in ("edge", "center"):
        raise ValueError("connector mode must be edge or center")
    for label, box in (("source", source), ("target", target)):
        if not isinstance(box, dict):
            raise ValueError(f"connector {label} must be a positioned object")
        for key in ("x", "y", "w", "h"):
            if key not in box:
                raise ValueError(f"connector {label} needs x, y, w, and h")
    source_box = _pptx_box(source, label="connector source")
    target_box = _pptx_box(target, label="connector target")
    source_center = _pptx_center(source_box)
    target_center = _pptx_center(target_box)
    direction_x = target_center[0] - source_center[0]
    direction_y = target_center[1] - source_center[1]
    if math.hypot(direction_x, direction_y) <= _PPTX_MIN_DISTANCE:
        raise ValueError("connector objects share a center")
    if mode == "center":
        x1, y1 = source_center
        x2, y2 = target_center
    else:
        x1, y1 = _pptx_boundary_toward(source_box, target_center)
        x2, y2 = _pptx_boundary_toward(target_box, source_center)
        gap_x, gap_y = x2 - x1, y2 - y1
        if gap_x * direction_x + gap_y * direction_y <= 0:
            raise ValueError("connector objects overlap or touch; edge mode needs a gap between the facing edges")
    if math.hypot(x2 - x1, y2 - y1) <= _PPTX_MIN_DISTANCE:
        raise ValueError("connector length must be positive")
    ink = _pptx_color(color, label="connector color")
    stroke = _pptx_positive(width, label="connector width")
    head_size = _pptx_positive(head, label="connector head")
    rotate = round((math.degrees(math.atan2(y2 - y1, x2 - x1)) + 90.0) % 360.0, 4)
    midpoint = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    return {
        "mode": mode,
        "x1": _pptx_round(x1),
        "y1": _pptx_round(y1),
        "x2": _pptx_round(x2),
        "y2": _pptx_round(y2),
        "midpoint": {"x": _pptx_round(midpoint[0]), "y": _pptx_round(midpoint[1])},
        "distance": _pptx_round(math.hypot(x2 - x1, y2 - y1)),
        "rotate": rotate,
        "line": {
            "op": "line",
            "options": _pptx_line_box(x1, y1, x2, y2, color=ink, width=stroke),
        },
        "head": {
            "op": "shape",
            "shape": "triangle",
            "options": {
                "x": _pptx_round(midpoint[0] - head_size / 2.0),
                "y": _pptx_round(midpoint[1] - head_size / 2.0),
                "w": _pptx_round(head_size),
                "h": _pptx_round(head_size),
                "rotate": rotate,
                "fill": _pptx_no_fill(),
                "line": {"type": "solid", "color": ink, "width": stroke},
            },
        },
    }


def pptx_connector(
    source: str,
    target: str,
    *,
    mode: str = "edge",
    color: str = _PPTX_DEFAULT_COLOR,
    width: float = _PPTX_DEFAULT_LINE_WIDTH,
    head: float = 0.18,
) -> dict:
    """Connector item for a JSON slide spec.

    Resolves to a straight black line plus an unfilled triangle arrowhead.
    ``color`` overrides the line color. Center mode is normalized to the start
    of the slide's ordered item list so the connector paints behind later
    objects. Edge mode stays at its list position and rejects overlap.
    """
    if mode not in ("edge", "center"):
        raise ValueError("connector mode must be edge or center")
    _element_id(source)
    _element_id(target)
    if source == target:
        raise ValueError("connector source and target must differ")
    _pptx_color(color, label="connector color")
    _pptx_positive(width, label="connector width")
    _pptx_positive(head, label="connector head")
    return {
        "kind": "connector",
        "from": source,
        "to": target,
        "mode": mode,
        "color": color,
        "width": width,
        "head": head,
    }


def _pptx_item_id(item: dict) -> str | None:
    if "id" not in item:
        return None
    return _element_id(item["id"])


def _pptx_convert_item(item: dict) -> tuple[dict, dict | None]:
    if not isinstance(item, dict):
        raise ValueError("slide item must be a mapping")
    kind = item.get("kind")
    if kind == "text":
        _pptx_unknown(item, {"id", "kind", "text", "x", "y", "w", "h", "options"}, label="text item")
        position = _pptx_box(item, label="text")
        return {"op": "text", "text": _pptx_text(item.get("text"), label="text", limit=8000),
                "options": _pptx_text_options(item.get("options"), position)}, position
    if kind == "shape":
        _pptx_unknown(item, {"id", "kind", "shape", "x", "y", "w", "h", "options"}, label="shape item")
        if not isinstance(item.get("shape"), str) or not _PPTX_SHAPE.fullmatch(item["shape"]):
            raise ValueError("shape must be a shape name")
        position = _pptx_box(item, label="shape")
        return {"op": "shape", "shape": item["shape"],
                "options": _pptx_shape_options(item.get("options"), position)}, position
    if kind == "line":
        _pptx_unknown(item, {"id", "kind", "x", "y", "w", "h", "options"}, label="line item")
        _pptx_reject_arrow_keys(item.get("options") or {}, label="line options")
        raw_options = item.get("options") or {}
        if raw_options and not isinstance(raw_options, dict):
            raise ValueError("line options must be a mapping")
        _pptx_unknown(raw_options, {"line"}, label="line options")
        style = _pptx_line_style(raw_options["line"], label="line") if "line" in raw_options else _pptx_default_line()
        x = _pptx_number(item.get("x"), label="line x")
        y = _pptx_number(item.get("y"), label="line y")
        span_w = _pptx_number(item.get("w"), label="line w")
        span_h = _pptx_number(item.get("h"), label="line h")
        if span_w == 0 and span_h == 0:
            raise ValueError("line length must be positive")
        options = _pptx_line_box(
            x, y, x + span_w, y + span_h,
            color=style.get("color", _PPTX_DEFAULT_COLOR),
            width=style.get("width", _PPTX_DEFAULT_LINE_WIDTH),
        )
        options["line"] = style
        return {"op": "line", "options": options}, None
    if kind == "table":
        _pptx_unknown(item, {"id", "kind", "rows", "x", "y", "w", "h", "options"}, label="table item")
        rows = item.get("rows")
        if not isinstance(rows, list) or not rows or not all(isinstance(row, list) and row for row in rows):
            raise ValueError("table rows must be a non-empty list of non-empty rows")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("table rows must have equal length")
        position = _pptx_box(item, label="table", require_height="h" in item)
        options = _pptx_table_options(item.get("options"), position, columns=width)
        encoded = [[_pptx_cell(cell, label=f"cell {row_index}:{column}", color=options["color"],
                               font_face=options["fontFace"], fill=options["fill"])
                    for column, cell in enumerate(row)]
                   for row_index, row in enumerate(rows)]
        return {"op": "table", "rows": encoded, "options": options}, position if "h" in position else None
    if kind == "image":
        _pptx_unknown(item, {"id", "kind", "path", "data", "x", "y", "w", "h", "altText"}, label="image item")
        if ("path" in item) == ("data" in item):
            raise ValueError("image requires path or data")
        position = _pptx_box(item, label="image")
        options = dict(position)
        if "path" in item:
            options["path"] = _pptx_https_url(item["path"], label="image path")
        else:
            if not isinstance(item["data"], str):
                raise ValueError("image data must be a base64 image string")
            match = _PPTX_DATA_IMAGE.fullmatch(item["data"])
            if not match:
                raise ValueError("image data must be an image/*;base64 payload")
            options["data"] = match.group(1)
        if "altText" in item:
            options["altText"] = _pptx_text(item["altText"], label="altText", limit=200)
        return {"op": "image", "options": options}, position
    raise ValueError(f"unknown slide item: {kind}")


def _resolve_pptx_spec(spec: dict, *, filename: str | None, auto: bool) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("spec must be a mapping")
    _pptx_unknown(spec, {"fileName", "filename", "layout", "author", "title", "slides"}, label="presentation keys")
    if "fileName" in spec and "filename" in spec:
        raise ValueError("use one of fileName or filename")
    chosen = filename if filename is not None else spec.get("fileName", spec.get("filename", "presentation.pptx"))
    if not isinstance(chosen, str) or not _PPTX_FILENAME.fullmatch(chosen):
        raise ValueError("fileName must be a plain .pptx filename")
    layout = spec.get("layout")
    if layout is not None and layout not in _PPTX_LAYOUTS:
        raise ValueError("layout must be a built-in PptxGenJS layout name")
    resolved = {"fileName": chosen, "slides": []}
    if layout is not None:
        resolved["layout"] = layout
    if "author" in spec:
        resolved["author"] = _pptx_text(spec["author"], label="author", limit=200)
    if "title" in spec:
        resolved["title"] = _pptx_text(spec["title"], label="title", limit=200)
    if auto:
        resolved["auto"] = True
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("slides must be a non-empty list")
    for slide in slides:
        if not isinstance(slide, dict):
            raise ValueError("slide must be a mapping")
        _pptx_unknown(slide, {"background", "items"}, label="slide keys")
        items = slide.get("items", [])
        if not isinstance(items, list):
            raise ValueError("slide items must be a list")
        encoded = {"items": []}
        if "background" in slide:
            background = slide["background"]
            if not isinstance(background, dict):
                raise ValueError("slide background must be a mapping")
            _pptx_unknown(background, {"color"}, label="background")
            encoded["background"] = {"color": _pptx_color(background.get("color"), label="background color")}
        boxes: dict[str, dict] = {}
        seen_ids: set[str] = set()
        pending: list[tuple[str, dict]] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("slide item must be a mapping")
            identity = _pptx_item_id(item)
            if identity is not None:
                if identity in seen_ids:
                    raise ValueError(f"duplicate slide item id: {identity}")
                seen_ids.add(identity)
            if item.get("kind") == "connector":
                _pptx_unknown(item, {"kind", "from", "to", "mode", "color", "width", "head"}, label="connector")
                pending.append(("connector", item))
                continue
            operation, box = _pptx_convert_item(item)
            if identity is not None and box is not None:
                boxes[identity] = box
            pending.append(("item", operation))
        # Paint order matches PptxGenJS and OOXML: earlier items are behind.
        # Center-mode connectors are normalized to the start of that list.
        behind: list[dict] = []
        ordered: list[dict] = []
        for tag, payload in pending:
            if tag == "item":
                ordered.append(payload)
                continue
            source_id = payload.get("from")
            target_id = payload.get("to")
            if not isinstance(source_id, str) or source_id not in boxes:
                raise ValueError("connector source must be a positioned object on the same slide")
            if not isinstance(target_id, str) or target_id not in boxes:
                raise ValueError("connector target must be a positioned object on the same slide")
            geometry = pptx_arrow_geometry(
                boxes[source_id],
                boxes[target_id],
                mode=payload.get("mode", "edge"),
                color=payload.get("color", _PPTX_DEFAULT_COLOR),
                width=payload.get("width", _PPTX_DEFAULT_LINE_WIDTH),
                head=payload.get("head", 0.18),
            )
            pair = [geometry["line"], geometry["head"]]
            if geometry["mode"] == "center":
                behind.extend(pair)
            else:
                ordered.extend(pair)
        encoded["items"] = behind + ordered
        resolved["slides"].append(encoded)
    return resolved


def _pptx_json(value) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return (payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _pptx_runtime(element_id: str) -> str:
    return (
        "(function(){"
        f'var specEl=document.getElementById("{element_id}-spec");'
        f'var button=document.getElementById("{element_id}");'
        "if(!specEl)return;"
        "var spec=JSON.parse(specEl.textContent);"
        "function draw(slide,item){"
        'if(item.op==="text")slide.addText(item.text,item.options||{});'
        'else if(item.op==="shape")slide.addShape(item.shape,item.options||{});'
        'else if(item.op==="line")slide.addShape("line",item.options||{});'
        'else if(item.op==="table")slide.addTable(item.rows,item.options||{});'
        'else if(item.op==="image")slide.addImage(item.options||{});'
        "}"
        "function build(){"
        "if(!window.PptxGenJS)return;"
        "var pptx=new window.PptxGenJS();"
        "if(spec.layout)pptx.layout=spec.layout;"
        "if(spec.author)pptx.author=spec.author;"
        "if(spec.title)pptx.title=spec.title;"
        "(spec.slides||[]).forEach(function(slideSpec){"
        "var slide=pptx.addSlide();"
        "if(slideSpec.background)slide.background=slideSpec.background;"
        "(slideSpec.items||[]).forEach(function(item){draw(slide,item);});"
        "});"
        'return pptx.writeFile({fileName:spec.fileName||"presentation.pptx"});'
        "}"
        'if(button)button.addEventListener("click",function(){build();});'
        "if(spec.auto)build();"
        "})();"
    )


def pptx_presentation(
    spec: dict,
    *,
    button_id: str = "download-pptx",
    label: str = "Download PowerPoint",
    filename: str | None = None,
    auto: bool = False,
    nonce: str | None = None,
) -> str:
    """Trusted HTML: a download button that builds a .pptx from a JSON slide spec.

    The browser loads PptxGenJS from ``remote_scripts("pptxgenjs")`` and calls
    ``writeFile``. Python only validates the spec and expands ``pptx_connector``
    items into a line plus an unfilled triangle. Generated objects default to
    black text and borders, no fill, and fontFace Meiryo; spec values override
    those properties. It does not assemble or patch Office XML. Slide layouts
    and diagram styling stay in the consumer's spec.
    """
    if not isinstance(auto, bool):
        raise ValueError("auto must be a boolean")
    identity = _element_id(button_id)
    payload = _pptx_json(_resolve_pptx_spec(spec, filename=filename, auto=auto))
    return (
        f'<div class="ui-panel" data-pptx-download="{identity}">{button(label, id=identity)}'
        f'<script type="application/json" id="{identity}-spec">{payload}</script>'
        f'{classic_script(_pptx_runtime(identity), nonce=nonce)}</div>'
    )


def section_browser(sections: tuple[tuple[str, str], ...], *, id: str = "sections",
                    label: str = "Heading", full_text: str = "", full_label: str = "(full extract)") -> str:
    """Text-only section dropdown; opt in to controls.js to enable switching.

    Sections are (label, body) pairs, so duplicate titles keep distinct values.
    No Markdown parsing or provider grammar lives in this presentation helper.
    Without JavaScript the full text is still visible and the select is disabled.
    """
    identity = _element_id(id)
    items = [{"value": str(index), "label": title, "body": body}
             for index, (title, body) in enumerate(sections)]
    payload = json.dumps({"items": items, "fullText": full_text, "fullLabel": full_label}, ensure_ascii=True)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    control = select((("", full_label),), id=identity, label=label, disabled=True)
    return (f'<section class="ui-panel" data-ui-section-browser>{control}'
            f'<pre class="ui-output" data-ui-section-output aria-live="polite">{escape(full_text)}</pre>'
            f'<script type="application/json" data-ui-section-data>{payload}</script></section>')


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


_ROUTE_PATH = re.compile(r"/[^\s#?\\]*\Z")


def route_table(registry) -> list[dict]:
    """Validate a route table: ``{"/route": key}`` or ``[{"route", "key"|"emoji", "label"?}]``.

    Same rules as ``navigation.js`` ``routeTable`` (and browser-test-kit
    ``route_trail.py`` registries): routes are absolute app paths, keys are
    nonempty tokens, the identity drops U+FE0F, and a key naming two routes or a
    repeated route is an error. Returns rows with ``route``, ``key``, ``identity``, ``label``.
    """
    rows = registry if isinstance(registry, list) else [{"route": r, "key": k} for r, k in dict(registry).items()]
    seen_routes, seen_keys, out = set(), {}, []
    for row in rows:
        route, key = row.get("route"), row.get("key", row.get("emoji"))
        if not isinstance(route, str) or not _ROUTE_PATH.match(route) or "//" in route:
            raise ValueError(f"route must be an absolute app path such as /map: {route!r}")
        if not isinstance(key, str) or not key.strip() or any(c.isspace() for c in key):
            raise ValueError(f"route key must be a nonempty token: {route}")
        identity = key.replace("\ufe0f", "")
        if route in seen_routes:
            raise ValueError(f"duplicate route: {route}")
        if identity in seen_keys:
            raise ValueError(f"route key names two routes: {key}")
        seen_routes.add(route)
        seen_keys[identity] = route
        label = row.get("label")
        out.append({"route": route, "key": key, "identity": identity, "label": label if isinstance(label, str) else None})
    if not out:
        raise ValueError("route table is empty")
    return out


def route_links(registry, *, routing: str = "hash", label: str = "Pages") -> str:
    """Escaped links for a route table plus the table as inert JSON for ``navigation.js``.

    ``routing="hash"`` (``#/route``) works from ``file://`` and static hosting;
    ``"path"`` needs a server that serves each path. Each link carries
    ``data-ui-go`` with its key, so ``webUiNavigation.bindRouteTable`` (bound
    automatically by ``bindNavigation``) marks the current page and
    ``go("<key>")`` navigates by emoji or name. Without JavaScript the
    ``href`` still navigates.
    """
    if routing not in ("hash", "path"):
        raise ValueError("routing must be hash or path")
    rows = route_table(registry)
    payload = json.dumps([{k: r[k] for k in ("route", "key", "label") if r[k] is not None} for r in rows],
                         ensure_ascii=False).replace("<", "\\u003c")
    links = " ".join(
        f'<a class="ui-button" href="{escape(("#" if routing == "hash" else "") + r["route"])}" '
        f'data-ui-go="{escape(r["key"])}">{escape(r["key"] + (" " + r["label"] if r["label"] else ""))}</a>'
        for r in rows)
    return (f'<nav aria-label="{escape(label)}">{links}</nav>'
            f'<script type="application/json" id="ui-route-table" data-ui-routing="{routing}">{payload}</script>')


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
    for index in range(1, len(chunks), 2):
        if chunks[index].startswith('<style'):
            chunks[index] = re.sub(r'(pre, code\s*\{)\s*font-family:[^;]*;\s*(\})', r'\1 font-family: inherit; \2', chunks[index])
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


# Exact snapshot of the locked stdlib launcher for single-file distribution.
# Keep byte-for-byte parity with vendor/node_launch.py (covered by tests).
_EMBEDDED_NODE_LAUNCH_SOURCE = '"""Shared Python launcher for Node.js scripts (stdlib only, Python 3.9+).\n\nLibrary: ``run(target, *args, node=..., input=..., timeout=..., max_input_bytes=...,\nresponse_max_bytes=..., env=..., env_var=...)`` returns stdout/stderr as ``bytes``.\n``run_argv(argv, ...)`` prepends a resolved Node executable to ``argv``.\n\nNode resolution (first match that runs Node 24+): explicit ``node``,\n``os.environ[env_var]`` when set, then ``shutil.which("node")``. Explicit ``node`` or a\nset ``env_var`` value does not fall back to later candidates. Windows ``.cmd``/``.bat``\nshims are never spawned with ``shell=True``; explicit paths are rejected.\n\n``env`` merges over ``os.environ`` case-insensitively on Windows. Optional\n``max_input_bytes`` / ``response_max_bytes`` raise errors with stable ``code`` values:\n``EINPUTTOOLARGE``, ``ERESPONSETOOLARGE``, ``ELAUNCHFAILURE``, and\n``ELAUNCHSTDINCLOSED`` when stdin breaks (``EPIPE``) before the child finishes reading.\nStdout is read incrementally when ``response_max_bytes`` is set (cap plus\n``HOST_RESPONSE_MARGIN_BYTES``, matching ``py_launch.cjs`` ``maxBuffer`` / ``ENOBUFS``).\n"""\nfrom __future__ import annotations\n\nimport errno\nimport os\nimport re\nimport shutil\nimport subprocess\nimport sys\nimport threading\nfrom typing import Any, Mapping, Optional, Sequence, Union\n\nMIN_NODE_MAJOR = 24\nDEFAULT_ENV_VAR = "NODE"\nDEFAULT_PROBE_TIMEOUT = 5.0\nHOST_RESPONSE_MARGIN_BYTES = 512\n_NODE_VERSION = re.compile(r"(?:^|\\s)v?(?P<major>\\d+)(?:\\.\\d+)*", re.IGNORECASE)\n_NODE_PROBE_CACHE: dict[str, str] = {}\n\n\nclass NodeNotFoundError(FileNotFoundError):\n    """Raised when Node.js cannot be located or does not meet the minimum version."""\n\n\nclass LaunchError(RuntimeError):\n    """Raised when the Node child fails to start, exceeds caps, or exits unexpectedly."""\n\n    def __init__(\n        self,\n        message: str,\n        *,\n        code: str = "ELAUNCHFAILURE",\n        status: Optional[int] = None,\n        stdout: bytes = b"",\n        stderr: bytes = b"",\n        signal: Optional[int] = None,\n    ) -> None:\n        super().__init__(message)\n        self.code = code\n        self.status = status\n        self.stdout = stdout\n        self.stderr = stderr\n        self.signal = signal\n\n\ndef is_node_target(path: Union[str, os.PathLike[str]]) -> bool:\n    """True when ``path`` names a JavaScript entry file by extension."""\n    return os.path.splitext(os.fspath(path))[1].lower() in (".js", ".cjs", ".mjs")\n\n\ndef _env_key_fold(key: str) -> str:\n    return str(key).casefold()\n\n\ndef env_lookup(env: Mapping[str, str], name: str) -> Optional[str]:\n    """Case-insensitive environment lookup (primarily for Windows tests)."""\n    fold = _env_key_fold(name)\n    for key, value in env.items():\n        if _env_key_fold(key) == fold:\n            return value\n    return None\n\n\ndef build_child_env(overrides: Optional[Mapping[str, str]]) -> Optional[dict[str, str]]:\n    """Merge ``overrides`` onto ``os.environ``; Windows overrides replace folded keys."""\n    if overrides is None:\n        return None\n    if os.name != "nt":\n        merged = dict(os.environ)\n        merged.update(overrides)\n        return merged\n    env = dict(os.environ)\n    index: dict[str, str] = {_env_key_fold(key): key for key in env}\n    for override_key, value in overrides.items():\n        fold = _env_key_fold(override_key)\n        existing = index.get(fold)\n        if existing is not None:\n            del env[existing]\n        env[override_key] = value\n        index[fold] = override_key\n    return env\n\n\ndef _reject_windows_batch_wrapper(path: str) -> None:\n    lowered = path.lower()\n    if lowered.endswith(".cmd") or lowered.endswith(".bat"):\n        raise NodeNotFoundError(\n            "node_launch: node batch wrappers (.cmd/.bat) are not supported: " + path\n        )\n\n\ndef _decode(data: bytes) -> str:\n    if not data:\n        return ""\n    return data.decode("utf-8", errors="replace")\n\n\ndef _probe_node_once(path: str, probe_timeout: float) -> str:\n    cached = _NODE_PROBE_CACHE.get(path)\n    if cached is not None:\n        return cached\n    _reject_windows_batch_wrapper(path)\n    try:\n        completed = subprocess.run(\n            (path, "--version"),\n            capture_output=True,\n            timeout=probe_timeout,\n            shell=False,\n            check=False,\n        )\n    except FileNotFoundError as exc:\n        raise NodeNotFoundError("node_launch: node executable not found: " + path) from exc\n    except OSError as exc:\n        raise NodeNotFoundError("node_launch: node version probe failed: " + path) from exc\n    except subprocess.TimeoutExpired as exc:\n        raise NodeNotFoundError("node_launch: node version probe timed out: " + path) from exc\n    output = _decode(completed.stdout) + _decode(completed.stderr)\n    match = _NODE_VERSION.search(output)\n    if completed.returncode != 0 or match is None:\n        raise NodeNotFoundError("node_launch: node version probe failed: " + path)\n    major = int(match.group("major"))\n    if major < MIN_NODE_MAJOR:\n        raise NodeNotFoundError(\n            f"node_launch: node version must be {MIN_NODE_MAJOR} or newer (found {major}): "\n            + path\n        )\n    _NODE_PROBE_CACHE[path] = path\n    return path\n\n\ndef _node_executable(\n    node: Optional[Union[str, os.PathLike[str]]],\n    *,\n    env_var: str,\n    probe: bool,\n    probe_timeout: float,\n) -> str:\n    explicit = node is not None\n    if not explicit and env_var and env_var in os.environ:\n        node = os.environ[env_var]\n        explicit = True\n    if explicit:\n        path = os.fspath(node)\n        _reject_windows_batch_wrapper(path)\n        return _probe_node_once(path, probe_timeout) if probe else path\n\n    if not probe:\n        discovered = shutil.which("node")\n        path = discovered if discovered else "node"\n        _reject_windows_batch_wrapper(path)\n        return path\n\n    discovered = shutil.which("node")\n    if discovered:\n        try:\n            return _probe_node_once(discovered, probe_timeout)\n        except NodeNotFoundError:\n            pass\n    raise NodeNotFoundError("node_launch: node executable not found")\n\n\ndef resolve_node(\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    *,\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n) -> str:\n    """Locate a Node 24+ executable.\n\n    Explicit ``node`` or a set ``env_var`` environment value must work as given;\n    auto-discovery uses ``shutil.which(\'node\')`` on ``PATH``.\n    """\n    return _node_executable(\n        node, env_var=env_var, probe=probe, probe_timeout=probe_timeout\n    )\n\n\ndef node_command(\n    target: Union[str, os.PathLike[str]],\n    *args: Union[str, os.PathLike[str]],\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    node_flags: Sequence[Union[str, os.PathLike[str]]] = (),\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n) -> list[str]:\n    """Build ``[node, *node_flags, target, *args]`` without reinterpreting passthrough argv."""\n    executable = _node_executable(\n        node, env_var=env_var, probe=probe, probe_timeout=probe_timeout\n    )\n    flags = [os.fspath(value) for value in node_flags]\n    script = os.fspath(target)\n    trailing = [os.fspath(value) for value in args]\n    return [executable, *flags, script, *trailing]\n\n\ndef node_or_command(\n    argv: Sequence[Union[str, os.PathLike[str]]],\n    *,\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    node_flags: Sequence[Union[str, os.PathLike[str]]] = (),\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n) -> list[str]:\n    """Prepend Node when ``argv[0]`` names a ``.js`` / ``.cjs`` / ``.mjs`` file."""\n    tokens = [os.fspath(value) for value in argv]\n    if not tokens:\n        return tokens\n    if is_node_target(tokens[0]):\n        return node_command(\n            tokens[0],\n            *tokens[1:],\n            node=node,\n            node_flags=node_flags,\n            env_var=env_var,\n            probe=probe,\n            probe_timeout=probe_timeout,\n        )\n    return tokens\n\n\ndef _nonnegative_int(name: str, value: int) -> None:\n    if not isinstance(value, int) or value < 0:\n        raise ValueError(f"node_launch: {name} must be a nonnegative integer")\n\n\ndef _input_byte_length(input_data: Optional[Union[str, bytes]]) -> int:\n    if input_data is None:\n        return 0\n    if isinstance(input_data, str):\n        return len(input_data.encode("utf-8"))\n    return len(input_data)\n\n\ndef _normalize_input(input_data: Optional[Union[str, bytes]]) -> Optional[bytes]:\n    if input_data is None:\n        return None\n    if isinstance(input_data, str):\n        return input_data.encode("utf-8")\n    return input_data\n\n\ndef _response_cap_bytes(response_max_bytes: int) -> int:\n    _nonnegative_int("response_max_bytes", response_max_bytes)\n    return response_max_bytes + HOST_RESPONSE_MARGIN_BYTES\n\n\ndef _launch_failure_from_returncode(\n    returncode: int,\n    stdout: bytes,\n    stderr: bytes,\n) -> LaunchError:\n    if returncode < 0:\n        signum = -returncode\n        return LaunchError(\n            f"node_launch: Node process terminated by signal {signum}",\n            code="ELAUNCHFAILURE",\n            signal=signum,\n            stdout=stdout,\n            stderr=stderr,\n        )\n    message = _decode(stderr).strip() or "Node script failed"\n    return LaunchError(\n        message,\n        code="ELAUNCHFAILURE",\n        status=returncode,\n        stdout=stdout,\n        stderr=stderr,\n    )\n\n\ndef _exit_code_for_main(returncode: Optional[int]) -> None:\n    if returncode is None or returncode == 0:\n        return\n    if returncode < 0:\n        sys.exit(128 + (-returncode))\n    sys.exit(returncode)\n\n\ndef _stream_communicate(\n    proc: subprocess.Popen,\n    input_bytes: Optional[bytes],\n    timeout: Optional[float],\n    response_max_bytes: Optional[int],\n) -> tuple[bytes, bytes, int]:\n    hard_limit = None\n    cap: Optional[int] = None\n    if response_max_bytes is not None:\n        _nonnegative_int("response_max_bytes", response_max_bytes)\n        cap = response_max_bytes\n        hard_limit = _response_cap_bytes(response_max_bytes)\n\n    stdout_chunks: list[bytes] = []\n    stderr_chunks: list[bytes] = []\n    stdout_len = 0\n    exceeded = threading.Event()\n    read_lock = threading.Lock()\n    stdin_code: list[Optional[str]] = [None]\n    stdin_os_error: list[Optional[OSError]] = [None]\n\n    def read_stdout() -> None:\n        nonlocal stdout_len\n        stream = proc.stdout\n        if stream is None:\n            return\n        try:\n            while True:\n                chunk = stream.read(65536)\n                if not chunk:\n                    break\n                if hard_limit is not None:\n                    with read_lock:\n                        stdout_len += len(chunk)\n                        if stdout_len > hard_limit:\n                            exceeded.set()\n                            try:\n                                proc.kill()\n                            except OSError:\n                                pass\n                            break\n                stdout_chunks.append(chunk)\n        finally:\n            stream.close()\n\n    def read_stderr() -> None:\n        stream = proc.stderr\n        if stream is None:\n            return\n        try:\n            while True:\n                chunk = stream.read(65536)\n                if not chunk:\n                    break\n                stderr_chunks.append(chunk)\n        finally:\n            stream.close()\n\n    def write_stdin() -> None:\n        stream = proc.stdin\n        if stream is None:\n            return\n        if input_bytes is None:\n            try:\n                stream.close()\n            except OSError:\n                pass\n            return\n        try:\n            offset = 0\n            chunk_size = 65536\n            while offset < len(input_bytes):\n                stream.write(input_bytes[offset : offset + chunk_size])\n                offset += chunk_size\n            stream.flush()\n            stream.close()\n        except BrokenPipeError:\n            stdin_code[0] = "ELAUNCHSTDINCLOSED"\n            try:\n                stream.close()\n            except OSError:\n                pass\n        except OSError as exc:\n            if exc.errno == errno.EPIPE:\n                stdin_code[0] = "ELAUNCHSTDINCLOSED"\n                try:\n                    stream.close()\n                except OSError:\n                    pass\n            else:\n                stdin_os_error[0] = exc\n                try:\n                    stream.close()\n                except OSError:\n                    pass\n\n    stdout_thread = threading.Thread(target=read_stdout, name="node_launch_stdout", daemon=True)\n    stderr_thread = threading.Thread(target=read_stderr, name="node_launch_stderr", daemon=True)\n    stdin_thread = threading.Thread(target=write_stdin, name="node_launch_stdin", daemon=True)\n    stdout_thread.start()\n    stderr_thread.start()\n    stdin_thread.start()\n\n    timed_out = False\n    returncode: Optional[int]\n    try:\n        returncode = proc.wait(timeout=timeout)\n    except subprocess.TimeoutExpired:\n        timed_out = True\n        try:\n            proc.kill()\n        except OSError:\n            pass\n        proc.wait()\n        returncode = proc.returncode\n\n    stdin_thread.join()\n    stdout_thread.join()\n    stderr_thread.join()\n\n    stdout = b"".join(stdout_chunks)\n    stderr = b"".join(stderr_chunks)\n    if returncode is None:\n        returncode = proc.returncode if proc.returncode is not None else -1\n\n    if stdin_os_error[0] is not None:\n        exc = stdin_os_error[0]\n        raise LaunchError(\n            f"node_launch: Node process failed: {exc}",\n            code="ELAUNCHFAILURE",\n            stdout=stdout,\n            stderr=stderr,\n        ) from exc\n\n    if timed_out:\n        raise LaunchError(\n            "node_launch: Node process timed out",\n            code="ELAUNCHFAILURE",\n            stdout=stdout,\n            stderr=stderr,\n        )\n\n    if stdin_code[0] == "ELAUNCHSTDINCLOSED":\n        raise LaunchError(\n            "node_launch: Node stdin pipe closed unexpectedly",\n            code="ELAUNCHSTDINCLOSED",\n            status=returncode,\n            stdout=stdout,\n            stderr=stderr,\n        )\n\n    if exceeded.is_set() or (cap is not None and len(stdout) > cap):\n        raise LaunchError(\n            f"node_launch: response exceeds response_max_bytes ({cap})",\n            code="ERESPONSETOOLARGE",\n            status=returncode,\n            stdout=stdout,\n            stderr=stderr,\n        )\n\n    return stdout, stderr, returncode\n\n\ndef _communicate(\n    proc: subprocess.Popen,\n    input_bytes: Optional[bytes],\n    timeout: Optional[float],\n    response_max_bytes: Optional[int],\n) -> tuple[bytes, bytes, int]:\n    return _stream_communicate(proc, input_bytes, timeout, response_max_bytes)\n\n\ndef run_argv(\n    argv: Sequence[Union[str, os.PathLike[str]]],\n    *,\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n    input: Optional[Union[str, bytes]] = None,\n    timeout: Optional[float] = None,\n    max_input_bytes: Optional[int] = None,\n    response_max_bytes: Optional[int] = None,\n    env: Optional[Mapping[str, str]] = None,\n    check: bool = True,\n) -> subprocess.CompletedProcess:\n    """Run ``[resolved_node, *argv]`` with ``shell=False`` and byte stdout/stderr."""\n    executable = _node_executable(\n        node, env_var=env_var, probe=probe, probe_timeout=probe_timeout\n    )\n    _reject_windows_batch_wrapper(executable)\n    command = [executable, *[os.fspath(value) for value in argv]]\n\n    input_len = _input_byte_length(input)\n    if max_input_bytes is not None:\n        _nonnegative_int("max_input_bytes", max_input_bytes)\n        if input_len > max_input_bytes:\n            raise LaunchError(\n                f"node_launch: input exceeds max_input_bytes ({max_input_bytes}; got {input_len} bytes)",\n                code="EINPUTTOOLARGE",\n            )\n\n    child_env = build_child_env(env)\n    input_bytes = _normalize_input(input)\n\n    try:\n        proc = subprocess.Popen(\n            command,\n            stdin=subprocess.PIPE,\n            stdout=subprocess.PIPE,\n            stderr=subprocess.PIPE,\n            shell=False,\n            env=child_env,\n        )\n    except OSError as exc:\n        raise LaunchError(\n            f"node_launch: Node process failed: {exc}",\n            code="ELAUNCHFAILURE",\n        ) from exc\n\n    stdout, stderr, returncode = _communicate(\n        proc, input_bytes, timeout, response_max_bytes\n    )\n\n    if returncode != 0 and check:\n        raise _launch_failure_from_returncode(returncode, stdout, stderr)\n\n    return subprocess.CompletedProcess(command, returncode, stdout, stderr)\n\n\ndef run(\n    target: Union[str, os.PathLike[str]],\n    *args: Union[str, os.PathLike[str]],\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    node_flags: Sequence[Union[str, os.PathLike[str]]] = (),\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n    input: Optional[Union[str, bytes]] = None,\n    timeout: Optional[float] = None,\n    max_input_bytes: Optional[int] = None,\n    response_max_bytes: Optional[int] = None,\n    env: Optional[Mapping[str, str]] = None,\n    check: bool = True,\n) -> subprocess.CompletedProcess:\n    """Run ``node_command(...)`` and return captured stdout/stderr as bytes."""\n    argv = node_command(\n        target,\n        *args,\n        node=node,\n        node_flags=node_flags,\n        env_var=env_var,\n        probe=probe,\n        probe_timeout=probe_timeout,\n    )\n    return run_argv(\n        argv[1:],\n        node=argv[0],\n        env_var=env_var,\n        probe=False,\n        input=input,\n        timeout=timeout,\n        max_input_bytes=max_input_bytes,\n        response_max_bytes=response_max_bytes,\n        env=env,\n        check=check,\n    )\n\n\ndef run_node(\n    target: Union[str, os.PathLike[str]],\n    *args: Union[str, os.PathLike[str]],\n    **kwargs: Any,\n) -> subprocess.CompletedProcess:\n    """Alias for :func:`run` matching the cli_args helper name."""\n    return run(target, *args, **kwargs)\n\n\ndef main(\n    script_path: Union[str, os.PathLike[str]],\n    opts: Optional[Mapping[str, Any]] = None,\n) -> None:\n    """Spawn a Node script with inherited stdio and forwarded exit code."""\n    options = dict(opts or {})\n    argv = options.pop("argv", None)\n    if argv is None:\n        argv = sys.argv[1:]\n    env_var = options.pop("env_var", DEFAULT_ENV_VAR)\n    node = options.pop("node", None)\n    node_flags = options.pop("node_flags", ())\n    probe_timeout = options.pop("probe_timeout", DEFAULT_PROBE_TIMEOUT)\n    child_env = build_child_env(options.pop("env", None))\n    try:\n        command = node_command(\n            script_path,\n            *argv,\n            node=node,\n            node_flags=node_flags,\n            env_var=env_var,\n            probe=True,\n            probe_timeout=probe_timeout,\n        )\n        _reject_windows_batch_wrapper(command[0])\n    except NodeNotFoundError as error:\n        sys.stderr.write(f"{error}\\n")\n        sys.exit(2)\n    try:\n        completed = subprocess.run(\n            command,\n            shell=False,\n            env=child_env,\n            check=False,\n        )\n    except OSError as error:\n        sys.stderr.write(f"node_launch: {error}\\n")\n        sys.exit(2)\n    if completed.returncode != 0:\n        _exit_code_for_main(completed.returncode)\n\n\ndef clear_probe_cache() -> None:\n    """Clear the version-probe cache (for tests)."""\n    _NODE_PROBE_CACHE.clear()\n'

_NODE_LAUNCH: Any = None


def _node_launch_module() -> Any:
    global _NODE_LAUNCH
    if _NODE_LAUNCH is None:
        path = Path(__file__).resolve().parent / "vendor" / "node_launch.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("_vendored_node_launch", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            import types
            module = types.ModuleType("_embedded_node_launch")
            exec(compile(_EMBEDDED_NODE_LAUNCH_SOURCE, "<embedded node_launch>", "exec"), module.__dict__)
        _NODE_LAUNCH = module
    return _NODE_LAUNCH


def _decode_node_process_bytes(data: Any) -> str:
    if isinstance(data, str):
        text = data
    elif not data:
        return ""
    else:
        text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _text_completed(
    proc: subprocess.CompletedProcess[bytes],
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        _decode_node_process_bytes(proc.stdout),
        _decode_node_process_bytes(proc.stderr),
    )


def _raise_node_not_found(exc: BaseException, node: str | os.PathLike[str] | None) -> None:
    message = str(exc)
    if node is not None and "node executable not found: " in message:
        path = os.fspath(node)
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path) from exc
    version = re.search(r"must be 24 or newer \(found (\d+)\)", message)
    if version is not None:
        raise RuntimeError(
            f"node requires Node 24 or newer; found Node {version.group(1)}"
        ) from exc
    if node is None and "node executable not found" in message:
        discovered = shutil.which("node")
        if discovered:
            node_launch = _node_launch_module()
            try:
                node_launch._probe_node_once(discovered, node_launch.DEFAULT_PROBE_TIMEOUT)
            except node_launch.NodeNotFoundError as probe_exc:
                version = re.search(r"must be 24 or newer \(found (\d+)\)", str(probe_exc))
                if version is not None:
                    raise RuntimeError(
                        f"node requires Node 24 or newer; found Node {version.group(1)}"
                    ) from exc
    raise RuntimeError("node requires Node 24 or newer; node executable not found on PATH") from exc


def _map_node_launch_error(
    exc: Any,
    command: list[str],
    timeout: float | None,
) -> subprocess.CompletedProcess[str]:
    if exc.code == "ELAUNCHSTDINCLOSED":
        status = exc.status if exc.status is not None else -1
        return _text_completed(
            subprocess.CompletedProcess(command, status, exc.stdout, exc.stderr)
        )
    if exc.code == "ELAUNCHFAILURE" and "timed out" in str(exc):
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=timeout,
            output=exc.stdout,
            stderr=exc.stderr,
        ) from exc
    raise exc


def _web_ui_node_run(
    *argv: str | Path,
    timeout: float | None = 30,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run vendored ``node_launch`` for pytest/CI helpers with subprocess-shaped errors."""
    node_launch = _node_launch_module()
    run_kwargs = dict(kwargs)
    node = run_kwargs.pop("node", None)
    env_var = run_kwargs.pop("env_var", None)
    run_kwargs.pop("probe", None)
    run_kwargs["timeout"] = timeout
    try:
        executable = node_launch.resolve_node(node=node, env_var=env_var)
    except node_launch.NodeNotFoundError as exc:
        _raise_node_not_found(exc, node)
    trailing = [os.fspath(value) for value in argv]
    if trailing:
        command = node_launch.node_command(
            trailing[0], *trailing[1:], node=executable, probe=False, env_var=env_var
        )
        try:
            completed = node_launch.run(
                trailing[0],
                *trailing[1:],
                node=executable,
                probe=False,
                env_var=env_var,
                **run_kwargs,
            )
        except node_launch.NodeNotFoundError as exc:
            _raise_node_not_found(exc, node)
        except node_launch.LaunchError as exc:
            return _map_node_launch_error(exc, command, timeout)
        return _text_completed(completed)
    command = [executable]
    try:
        completed = node_launch.run_argv(
            [],
            node=executable,
            probe=False,
            env_var=env_var,
            **run_kwargs,
        )
    except node_launch.NodeNotFoundError as exc:
        _raise_node_not_found(exc, node)
    except node_launch.LaunchError as exc:
        return _map_node_launch_error(exc, command, timeout)
    return _text_completed(completed)


def run_node(*argv: str | Path, timeout: float | None = 30, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Wrap Node 24+ for pytest/CI one-liners. Does not start a browser or fetch URLs."""
    run_kwargs = dict(kwargs)
    run_kwargs.setdefault("check", False)
    return _web_ui_node_run(*argv, timeout=timeout, **run_kwargs)


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
    parser.add_argument(
        "--with-remote-scripts",
        nargs="+",
        metavar="NAME",
        help="opt-in HTTPS classic scripts from the documented allowlist (e.g. plotly.js, pptxgenjs)",
    )
    parser.add_argument("--embed-ui", action="store_true", help="embed the built-in ui.js ES module")
    parser.add_argument("--module-mode", choices=("inline", "data"), default="inline")
    parser.add_argument("--trusted-html", action="store_true", help="interpret stdin as authored HTML, not user text")
    parser.add_argument("--sri", type=Path, metavar="FILE",
                        help="print the sha384 SRI and SHA-256 hex of FILE (for pinning a new asset) and exit")
    args = parser.parse_args(argv)
    if args.sri:
        try:
            raw = args.sri.read_bytes()
        except OSError as exc:
            parser.error(str(exc))
        sys.stdout.write(f"{sri(raw)}\nsha256 {hashlib.sha256(raw).hexdigest()}\n")
        return 0
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
        remote = remote_scripts(*args.with_remote_scripts) if args.with_remote_scripts else ()
        result = render_document(
            content,
            title=args.title,
            theme=args.theme,
            css=css,
            stylesheets=styles,
            scripts=scripts,
            remote_scripts=remote,
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
