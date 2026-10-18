# Static flow diagrams (optional, no JavaScript)

Additive web-ui diagram component: JSON → HTML/CSS or Mermaid Markdown. No changes to frozen contract/v1.

Run from repository root:

```sh
python -S -m tool.flow_diagram --format mermaid < examples/pr-flow.json > flow.md
python -S -m tool.flow_diagram --format html --asset-base . < examples/pr-flow.json > flow.html
python -S -m tool.flow_diagram --format html --embed-css < examples/pr-flow.json > flow-self-contained.html
python -S -m unittest discover -s tests -p 'test_flow_diagram.py' -v
```

The HTML variant uses existing web-ui themes and `css/flow.css`. The standalone HTML output embeds the local CSS. A fragment can be embedded in an existing consumer page using `--format fragment`.

Mermaid Markdown renders on GitHub; it is source code, not an SVG/PNG renderer. Ironmate can consume Mermaid source through its existing opt-in `mermaid_svg.py` + mmdc workflow. Image Studio PNG and Base64 integration are separate follow-up work.

User labels are escaped as HTML text and encoded for Mermaid labels. The input is intentionally bounded (256KiB, at most eight sources and eight steps). It is a linear merge-style flow, not a general graph editor. Use `examples/pr-flow.json` as a sample. Do not load remote scripts or send input to a server.
