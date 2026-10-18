# Static flow diagrams and optional image export

Additive web-ui diagram component: JSON → HTML/CSS or Mermaid Markdown. No changes to frozen contract/v1.

Run from repository root:

```sh
python -S -m tool.flow_diagram --format mermaid < examples/pr-flow.json > flow.md
python -S -m tool.flow_diagram --format html --asset-base . < examples/pr-flow.json > flow.html
python -S -m tool.flow_diagram --format html --embed-css < examples/pr-flow.json > flow-self-contained.html
python -S -m unittest discover -s tests -p 'test_flow_diagram.py' -v
```

The HTML variant uses existing web-ui themes and `css/flow.css`. The standalone HTML output embeds the local CSS. A fragment can be embedded in an existing consumer page using `--format fragment`.

Mermaid Markdown renders on GitHub; it is source code, not an SVG/PNG renderer. Ironmate connects this JSON contract to its existing `mermaid_svg.py` + mmdc and Image Studio raster output. The adapter provides Mermaid Markdown, SVG, PNG, standard padded Base64 and PNG data URI through CLI, Python and a thin Node-to-Python wrapper. See [Ironmate flow export](https://github.com/myon-bioinformatics/Ironmate/blob/main/docs/flow-export.md) for requirements and examples.

User labels are escaped as HTML text and encoded for Mermaid labels. The input is intentionally bounded (256KiB, at most eight sources and eight steps). It is a linear merge-style flow, not a general graph editor. Use `examples/pr-flow.json` as a sample. Do not load remote scripts or send input to a server.

## Contract ownership and image consumers

web-ui remains the source of JSON validation, HTML escaping and Mermaid generation.
Image consumers should lock exact upstream generator, LICENSE and fixture bytes
through the parent vendor registry rather than copy and modify the layout logic.
Ironmate uses the Python generator for both its Python and Node entry points;
web-ui's native Node generator remains available independently.

Image rendering is optional and local. Mermaid source needs no browser; Ironmate
SVG needs installed Mermaid CLI and its browser. PNG/Base64/data URI also need
Node.js 22+ and installed Chrome/Chromium. No tool is downloaded automatically,
and a missing renderer fails explicitly. Transparent is the default image canvas;
opaque `#RRGGBB` and scaled output are optional. Host fonts and browser versions
can affect vector text rasterization.
