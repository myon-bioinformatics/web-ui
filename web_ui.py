"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. Rendering never fetches assets; fetch_plotly_js() is an
explicit, integrity-checked download helper. JavaScript is omitted
by default; callers may opt in to local module script links. Node is wrapped
only as an explicit subprocess helper for pytest/CI one-liners.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import base64
from html import escape
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
# One distribution contract for external tags and explicit offline embedding.
# CDN and plotly.js-dist-min@4.1.1 bytes independently matched this SHA-256.
PLOTLY_JS_VERSION = "4.1.1"
PLOTLY_JS_URL = f"https://cdn.plot.ly/plotly-{PLOTLY_JS_VERSION}.min.js"
PLOTLY_JS_SHA256 = "3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f"
PLOTLY_JS_MAX_BYTES = 8 * 1024 * 1024
PLOTLY_JS_SRI = "sha256-" + base64.b64encode(bytes.fromhex(PLOTLY_JS_SHA256)).decode("ascii")
# Explicit HTTPS allowlist for opt-in remote classic scripts (not ES modules).
REMOTE_SCRIPT_NAMES: dict[str, str] = {
    "plotly.js": PLOTLY_JS_URL,
    "pptxgenjs": _PPTXGENJS_URL,
}
# Every remote allowlist entry has fixed bytes and Subresource Integrity.
REMOTE_SCRIPT_INTEGRITY: dict[str, str] = {
    PLOTLY_JS_URL: PLOTLY_JS_SRI,
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
    are emitted with Subresource Integrity and anonymous CORS.
    """
    if not names:
        raise ValueError("names must not be empty")
    unknown = sorted({name for name in names if name not in REMOTE_SCRIPT_NAMES})
    if unknown:
        raise ValueError(f"unknown remote script: {', '.join(unknown)}")
    return tuple(REMOTE_SCRIPT_NAMES[name] for name in names)


def verify_plotly_js(raw: bytes) -> bytes:
    """Return the pinned bytes or fail before any decoding, caching or execution."""
    if not isinstance(raw, bytes):
        raise TypeError("Plotly.js payload must be bytes")
    if not raw:
        raise RuntimeError("Plotly.js CDN returned an empty body")
    if len(raw) > PLOTLY_JS_MAX_BYTES:
        raise RuntimeError(f"Plotly.js exceeds {PLOTLY_JS_MAX_BYTES} byte limit")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != PLOTLY_JS_SHA256:
        raise RuntimeError(f"Plotly.js {PLOTLY_JS_VERSION} SHA-256 mismatch: {actual}")
    return raw


def fetch_plotly_js(*, timeout: float = 60.0) -> bytes:
    """Explicitly fetch the fixed CDN bundle; never accept alternate or partial bytes.

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
    can depend on them. Pinned allowlist entries include their integrity
    attribute and anonymous CORS. Callers own script contents, imports and
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
    from the documented CDN URL before this initializer runs.
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a mapping")
    data = spec.get("data", [])
    if not isinstance(data, list):
        raise ValueError("spec data must be a list")
    layout = dict(spec.get("layout") or {})
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
    parser.add_argument(
        "--with-remote-scripts",
        nargs="+",
        metavar="NAME",
        help="opt-in HTTPS classic scripts from the documented allowlist (e.g. plotly.js, pptxgenjs)",
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
