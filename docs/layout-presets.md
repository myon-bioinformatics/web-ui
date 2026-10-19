# Switchable layout presets

Pixel values in a layout are choices, not facts. web-ui keeps them as **presets**: named
sets of CSS custom properties in one JSON file (`web-ui-layout-presets/1`, for example
`examples/layout-presets.json`). Any preset may be the right one for a screen; the page
lets people switch, and tests try them all.

## Switch live, without reloading

```sh
python -S tool/layout_presets.py css examples/layout-presets.json   # or: node js/layout-presets.cjs css ...
python -S tool/layout_presets.py html examples/layout-presets.json  # radio buttons, default checked
```

`css` writes the default preset on `:root` and one
`body:has(input[name="ui-layout"][value="ID"]:checked){...}` rule per preset; `html` writes
the radio buttons. Choosing a radio changes the variables at once: no reload and no
JavaScript, also from `file://`. Python and Node produce byte-identical output from the
same JSON (checked by `tests/layout-presets.node.cjs`). Values are limited to `--ui-*`
lengths (`px`, `rem`, `em`, `%`, `vw`, `fr`), and every preset sets the same variables.

The 8 px grid is the default (`grid8`: 160px tiles, 8px spacing). Other presets are equal
citizens: `compact` (4px), `device` (195px, half of a 390px phone, 6px spacing) and `wide`.

## Sweep: every preset that holds is a candidate

```sh
python tool/layout_presets.py sweep viewer.html --presets examples/layout-presets.json \
  --items ".ui-matrix-tiles li" --widths 320 384 768 1280 --out candidates.json
```

For each width the sweep clicks each preset's radio like a person would, then checks the
layout: no horizontal overflow, and the `--items` boxes neither overlap nor leave the
viewport. The result (`web-ui-layout-candidates/1`) lists, per preset, the widths where it
held or needs a look, and per width every preset that held. Several passing presets are
expected; the command fails only when some width has no preset that holds.

Passing candidates go back into the page: `controls_html(spec, candidates)` (and
`capture_matrix.py --candidates`) label each radio with "ok at …" / "check at …". Nothing is
disabled: a person who prefers another preset, or sees the layout looking off, can switch
and judge for themselves. A machine (Playwright) can do the same by clicking the radios.

## In the capture viewer

`tool/capture_matrix.py` uses `examples/layout-presets.json` for its tile grid by default
(`--layouts` for another file, `--candidates` for sweep labels). `css/matrix.css` reads
`--ui-matrix-col`, `--ui-matrix-gap` and `--ui-matrix-pad`, falling back to the 8 px defaults.
