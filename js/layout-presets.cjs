"use strict";
// Node twin of tool/layout_presets.py: same validation, byte-identical CSS and controls.
const SCHEMA = "web-ui-layout-presets/1";
const CANDIDATES = "web-ui-layout-candidates/1";
const ID = /^[a-z][a-z0-9-]{0,31}$/;
const VAR = /^--ui-[a-z][a-z0-9-]{0,47}$/;
const VALUE = /^(?:0|\d{1,4}(?:\.\d{1,3})?(?:px|rem|em|%|vw|fr))$/;
const MAX_PRESETS = 12;
const ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;"};
const escape = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

function validate(spec) {
  if (!isObject(spec) || spec.schema !== SCHEMA) throw new Error(`expected schema ${SCHEMA}`);
  const presets = spec.presets;
  if (!Array.isArray(presets) || presets.length < 1 || presets.length > MAX_PRESETS)
    throw new Error(`presets must list 1..${MAX_PRESETS} entries`);
  const out = [], seen = new Set();
  let names = null;
  for (const preset of presets) {
    if (!isObject(preset) || Object.keys(preset).some((k) => !["id", "label", "vars", "note"].includes(k)))
      throw new Error("a preset has id, label, vars and an optional note");
    const {id, label, vars} = preset;
    if (typeof id !== "string" || !ID.test(id) || seen.has(id)) throw new Error(`preset id must be a unique lowercase token: ${id}`);
    if (typeof label !== "string" || !label.trim() || label.length > 60) throw new Error(`preset ${id}: label must be 1..60 characters`);
    if (!isObject(vars) || !Object.keys(vars).length) throw new Error(`preset ${id}: vars must be a nonempty object`);
    for (const [name, value] of Object.entries(vars))
      if (!VAR.test(name) || typeof value !== "string" || !VALUE.test(value)) throw new Error(`preset ${id}: ${name}: ${value} is not a --ui-* length`);
    const keys = new Set(Object.keys(vars));
    if (names && (keys.size !== names.size || [...keys].some((k) => !names.has(k))))
      throw new Error(`preset ${id}: every preset must set the same variables`);
    names = keys;
    const note = preset.note === undefined ? "" : preset.note;
    if (typeof note !== "string" || note.length > 120) throw new Error(`preset ${id}: note must be at most 120 characters`);
    seen.add(id);
    out.push({id, label, vars: {...vars}, note});
  }
  const def = spec.default === undefined ? out[0].id : spec.default;
  if (!seen.has(def)) throw new Error(`default preset ${def} is not listed`);
  return {default: def, presets: out};
}

const decls = (vars) => Object.entries(vars).map(([n, v]) => `${n}:${v}`).join(";");

function css(spec) {
  const data = validate(spec);
  const def = data.presets.find((p) => p.id === data.default);
  const rules = [":root{" + decls(def.vars) + "}"];
  for (const p of data.presets) rules.push(`body:has(input[name="ui-layout"][value="${p.id}"]:checked){${decls(p.vars)}}`);
  rules.push(".ui-layout-switch{display:flex;flex-wrap:wrap;gap:8px;border:1px solid var(--ui-border);" +
             "padding:8px;margin:16px 0}.ui-layout-switch label{display:inline-flex;gap:4px;align-items:center}" +
             ".ui-layout-switch small{color:var(--ui-muted)}");
  return rules.join("\n") + "\n";
}

function note(preset, candidates) {
  if (candidates === null || candidates === undefined) return preset.note;
  const row = (candidates.presets || {})[preset.id];
  if (!row) return "not checked";
  const parts = [];
  if ((row.passed || []).length) parts.push("ok at " + row.passed.map((w) => `${w}px`).join(", "));
  if ((row.failed || []).length) parts.push("check at " + row.failed.map((w) => `${w}px`).join(", "));
  return parts.join("; ");
}

function controlsHtml(spec, candidates = null, legend = "Layout") {
  const data = validate(spec);
  if (candidates !== null && (!isObject(candidates) || candidates.schema !== CANDIDATES)) throw new Error(`candidates must be ${CANDIDATES}`);
  const items = data.presets.map((p) => {
    const checked = p.id === data.default ? " checked" : "";
    const n = note(p, candidates);
    return `<label><input type="radio" name="ui-layout" value="${p.id}"${checked}> ${escape(p.label)}` +
           (n ? ` <small>${escape(n)}</small>` : "") + "</label>";
  });
  return `<fieldset class="ui-layout-switch"><legend>${escape(legend)}</legend>` + items.join("") + "</fieldset>";
}

module.exports = {SCHEMA, CANDIDATES, validate, css, controlsHtml};

if (require.main === module) {
  const [command, file, candidatesFile] = process.argv.slice(2);
  try {
    const fs = require("node:fs");
    const spec = JSON.parse(fs.readFileSync(file, "utf8"));
    if (command === "css") process.stdout.write(css(spec));
    else if (command === "html") process.stdout.write(controlsHtml(spec, candidatesFile ? JSON.parse(fs.readFileSync(candidatesFile, "utf8")) : null) + "\n");
    else throw new Error("usage: layout-presets.cjs css|html PRESETS.json [CANDIDATES.json]");
  } catch (error) {
    process.stderr.write(`layout presets: ${error.message}\n`);
    process.exitCode = 2;
  }
}
