// Compile-only check (tsc --noEmit): the declarations accept real calls and reject wrong ones.
import flow = require("../js/flow.cjs");
import patch = require("../js/flow-patch.cjs");
import layout = require("../js/layout-presets.cjs");
const spec: flow.FlowSpec = {title: "t", sources: [{title: "a"}], steps: [{title: "b", note: "n"}]};
const html: string = flow.flowHtml(spec) + flow.flowMermaid(spec) + flow.flowDocument(spec, "modern");
const patched: flow.ValidFlow = patch.patchFlow(spec, [{path: "/steps/0/title", value: "c"}]);
const presets: layout.LayoutPresets = {schema: layout.SCHEMA, presets: [{id: "grid8", label: "8 px", vars: {"--ui-matrix-gap": "8px"}}]};
const controls: string = layout.css(presets) + layout.controlsHtml(presets, null, "Layout");
// @ts-expect-error unknown theme
flow.flowDocument(spec, "dark");
// @ts-expect-error unsupported patch path
patch.patchFlow(spec, [{path: "/steps/0/colour", value: "c"}]);
void [html, patched, controls];
