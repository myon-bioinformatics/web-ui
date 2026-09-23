# web-ui HTML contract v1

Status: **stable**

This directory is the normative compatibility surface for consumers such as
Ironmate and future HTML emitters in `markdown.py` / `ascii_artist`.

## Stability rule

Within v1, a stable class or required theme attribute MUST NOT be removed or
repurposed. Additive classes and new themes are allowed. A removal or semantic
repurpose requires a v2 contract.

## Required theme contract

A themed page SHOULD place `data-ui-theme` on `<body>`.

Stable v1 theme values:

- `modern` (default)
- `github-like`

Theme CSS MAY change presentation. It MUST NOT require consumers to rewrite the
semantic component structure.

## Stable semantic classes

Shared:

- `ui-page`
- `ui-panel`
- `ui-card`
- `ui-grid`
- `ui-button`
- `ui-input`
- `ui-tag`
- `ui-muted`
- `ui-title`
- `ui-output`

Stub-specific:

- `stub-toolbar`
- `stub-status`
- `stub-meta`

These names and their broad semantic purpose are stable for v1.

## Consumer ownership

Consumers MUST keep protocol/domain semantics outside web-ui. In particular,
MCP methods, API authorization, validation rules, repository search semantics,
and business-specific result interpretation remain consumer-owned.

User-controlled values MUST be rendered as text, not interpreted as HTML.

Consumers MAY add their own classes and `data-*` attributes. New `ui-*` or
`stub-*` classes may be added by web-ui without breaking v1.

## Not part of the v1 compatibility promise

Exact colors, spacing values, shadows, border radii, grid sizing constants,
theme-internal selectors, and most concrete DOM tag choices remain
implementation details.

The machine-readable source of truth is [contract.json](./contract.json).
[example.html](./example.html) is the canonical structural fixture used by CI.
