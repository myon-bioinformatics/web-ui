"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. Rendering never fetches assets; fetch_plotly_js() is an
explicit download helper with bounded reads. JavaScript is omitted
by default; callers may opt in to local module script links. Node is wrapped
only as an explicit subprocess helper for pytest/CI one-liners.
"""
from __future__ import annotations

import argparse
import bisect
import colorsys
import errno
import functools
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
import random
import re
import shutil
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request
import zlib
from urllib.parse import parse_qsl, urlsplit

THEMES = ("modern", "github-like")
# Token-only candidates: their values live in the Python tokens.css source; not in contract v1 yet.
CANDIDATE_THEMES = ("green", "red", "blue")
# The browser modules, as data: Python is the only source (there are no js/ files). write_js()/--site writes them under DIR/js/.
_JS = {
    "ui.js": r"""/** Set text-only content. User-controlled values are never interpreted as HTML. */
export function setText(target,value){const node=typeof target==="string"?document.querySelector(target):target;if(node)node.textContent=String(value)}
/** Serialize a value for human-readable text output. */
export function prettyJson(value){return JSON.stringify(value,null,2)}
/** Copy a value as text; falls back to a hidden textarea where the async clipboard is missing (plain http, old WebViews). */
export async function copyText(value){const text=String(value);try{await navigator.clipboard.writeText(text)}catch(error){const box=document.createElement("textarea");box.value=text;box.setAttribute("readonly","");box.style.cssText="position:fixed;opacity:0";try{document.body.append(box);box.select();if(typeof document.execCommand!=="function"||!document.execCommand("copy"))throw error}finally{box.remove()}}}
/** Switch data-ui-theme on <body> with no reload: controls are <select data-ui-theme-switch> or radios named ui-theme. The choice is remembered (localStorage, best effort). Returns the theme in effect. */
/** Buttons with data-ui-toggle flip aria-pressed on click (memory only: nothing is saved); data-label-on / data-label-off, when present, rename the button. */
export function bindToggles(root=document){return[...root.querySelectorAll("[data-ui-toggle]")].map(b=>{const sync=()=>{const label=b.getAttribute("aria-pressed")==="true"?b.dataset.labelOn:b.dataset.labelOff;if(label){b.setAttribute("aria-label",label);b.title=label}};b.addEventListener("click",()=>{b.setAttribute("aria-pressed",String(b.getAttribute("aria-pressed")!=="true"));sync()});sync();return b})}
export function bindTheme(root=document,{key="web-ui-theme"}={}){const body=document.body,controls=[...root.querySelectorAll("[data-ui-theme-switch],input[name=ui-theme]")];const known=name=>controls.some(c=>c.tagName==="SELECT"?[...c.options].some(o=>o.value===name):c.value===name);const sync=()=>{for(const c of controls){if(c.tagName==="SELECT")c.value=body.dataset.uiTheme;else c.checked=c.value===body.dataset.uiTheme}};let saved=null;try{saved=localStorage.getItem(key)}catch{}if(saved&&known(saved))body.dataset.uiTheme=saved;sync();for(const c of controls)c.addEventListener("change",()=>{if(!known(c.value))return;body.dataset.uiTheme=c.value;sync();try{localStorage.setItem(key,c.value)}catch{}});return body.dataset.uiTheme}
/** Mark on-screen elements with data-lit (IntersectionObserver); CSS decides what lit looks like. Without IntersectionObserver every element counts as lit. Returns a stop function. */
export function observeLit(targets,{threshold=0.4,root=null}={}){const nodes=typeof targets==="string"?[...document.querySelectorAll(targets)]:[...targets];if(typeof IntersectionObserver==="undefined"){for(const n of nodes)n.dataset.lit="";return()=>{}}const io=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting)e.target.dataset.lit="";else delete e.target.dataset.lit}},{threshold,root});for(const n of nodes)io.observe(n);return()=>io.disconnect()}
/** Click-to-enlarge for <a href="full.png"><img alt="..."></a> items inside [data-ui-lightbox]: one <dialog>; Esc, the backdrop and the close button shut it, arrows, buttons and a 48px swipe step through. Returns {open, close, dialog}, or null without items or <dialog>. */
export function bindLightbox(root=document){const items=[...root.querySelectorAll("[data-ui-lightbox] a[href]")];if(!items.length||typeof HTMLDialogElement==="undefined")return null;const dialog=document.createElement("dialog");dialog.className="ui-lightbox";dialog.setAttribute("aria-label","Image viewer");dialog.innerHTML='<img alt=""><p class="ui-muted"></p><div class="ui-lightbox-bar"><button class="ui-button" type="button" data-step="-1" aria-label="Previous">\u2190</button><button class="ui-button" type="button" data-step="1" aria-label="Next">\u2192</button><button class="ui-button" type="button" data-step="0" aria-label="Close">\u00d7</button></div>';const img=dialog.querySelector("img"),note=dialog.querySelector("p");let at=0,x=null;const show=i=>{at=(i+items.length)%items.length;const a=items[at],t=a.querySelector("img");img.src=a.href;img.alt=note.textContent=t?t.alt:""};const open=i=>{show(i);if(!dialog.open)dialog.showModal()};items.forEach((a,i)=>a.addEventListener("click",e=>{e.preventDefault();open(i)}));dialog.addEventListener("click",e=>{const b=e.target.closest("[data-step]");if(b){const s=Number(b.dataset.step);if(s)show(at+s);else dialog.close()}else if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close()}});dialog.addEventListener("keydown",e=>{if(e.key==="ArrowLeft")show(at-1);if(e.key==="ArrowRight")show(at+1)});dialog.addEventListener("pointerdown",e=>{x=e.clientX});dialog.addEventListener("pointerup",e=>{if(x!==null&&Math.abs(e.clientX-x)>=48)show(at+(e.clientX<x?1:-1));x=null});document.body.append(dialog);return{open,close:()=>dialog.close(),dialog}}
""",
    "stub.js": r"""import{setText,prettyJson}from"./ui.js";
/**
 * Bind one text input to an async or sync consumer handler.
 *
 * handler receives the input string and may return either text or any
 * JSON-serializable value. Protocol-specific validation and semantics belong
 * to the consuming repository, not web-ui.
 */
export function bindStub({input="#query",run="#run",output="#output",form="#stub-form",handler}){const q=document.querySelector(input),b=document.querySelector(run),f=document.querySelector(form);if(!q||!b)return;const execute=async event=>{event?.preventDefault();b.disabled=true;try{const result=await handler(q.value);setText(output,typeof result==="string"?result:prettyJson(result))}catch(error){setText(output,`Error: ${error?.message??error}`)}finally{b.disabled=false}};(f??b).addEventListener(f?"submit":"click",execute)}
""",
    "controls.js": r"""/* Provider-independent, text-only dropdown binding. No fetches or HTML input. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.webUiControls = api;
    if (typeof document !== "undefined") {
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => api.mount(document));
      else api.mount(document);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function bindSelect(select, output) {
    let entries = new Map(), fullText = "";
    function change() {
      output.textContent = entries.has(select.value) ? entries.get(select.value) : fullText;
    }
    select.addEventListener("change", change);
    return {
      update(items, text, fullLabel = "(full extract)") {
        const next = new Map();
        const options = [{value: "", label: fullLabel}];
        for (const item of items) {
          const value = String(item.value);
          if (!value || next.has(value)) throw new Error("section values must be nonempty and unique");
          next.set(value, String(item.body));
          options.push({value, label: String(item.label)});
        }
        const nodes = options.map(item => {
          const option = select.ownerDocument.createElement("option");
          option.value = item.value;
          option.textContent = item.label;
          return option;
        });
        entries = next;
        fullText = String(text);
        select.replaceChildren(...nodes);
        select.value = "";
        select.disabled = items.length === 0;
        change();
      },
      clear() { this.update([], ""); },
      destroy() { select.removeEventListener("change", change); }
    };
  }
  const mounted = new WeakSet();
  function mount(root) {
    root.querySelectorAll("[data-ui-section-browser]").forEach(panel => {
      if (mounted.has(panel)) return;
      const data = JSON.parse(panel.querySelector("[data-ui-section-data]").textContent);
      const control = bindSelect(panel.querySelector("select"), panel.querySelector("[data-ui-section-output]"));
      control.update(data.items, data.fullText, data.fullLabel);
      mounted.add(panel);
    });
  }
  return {bindSelect, mount};
});
""",
    "collection.js": r"""/* Portable, DOM-free collection filtering. Domain semantics stay with consumers. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WebUICollections = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function normalizeText(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
  }

  function matchesFacet(actual, expected) {
    if (Array.isArray(actual)) return actual.includes(expected);
    return actual === expected;
  }

  /**
   * Filter without modifying items or relying on DOM/network globals.
   *
   * text(item) may return a scalar or an array of searchable fields.
   * facets is an object of exact selected values. If an item's facet value
   * is an array, membership is tested. Omit inactive facets (no 'all' magic).
   * facetValues optionally maps facet names to item accessors.
   * predicates is an optional array of additional AND conditions.
   */
  function filterItems(items, options = {}) {
    if (!Array.isArray(items)) throw new TypeError('items must be an array');
    if (!options || typeof options !== 'object') throw new TypeError('options must be an object');
    const { query = '', text = item => item, facets = {}, facetValues = {}, predicates = [] } = options;
    if (typeof text !== 'function') throw new TypeError('text must be a function');
    if (!facets || typeof facets !== 'object' || Array.isArray(facets)) throw new TypeError('facets must be an object');
    if (!facetValues || typeof facetValues !== 'object' || Array.isArray(facetValues)) throw new TypeError('facetValues must be an object');
    if (!Array.isArray(predicates) || predicates.some(fn => typeof fn !== 'function')) throw new TypeError('predicates must be functions');
    const needle = normalizeText(query);
    const selected = Object.entries(facets).filter(([, value]) => value !== undefined);
    for (const [key] of selected) {
      if (Object.prototype.hasOwnProperty.call(facetValues, key) && typeof facetValues[key] !== 'function') {
        throw new TypeError('facetValues entries must be functions');
      }
    }
    return items.filter(item => {
      if (needle) {
        const raw = text(item);
        const fields = Array.isArray(raw) ? raw : [raw];
        if (!fields.some(field => normalizeText(field).includes(needle))) return false;
      }
      for (const [key, expected] of selected) {
        const actual = Object.prototype.hasOwnProperty.call(facetValues, key) ? facetValues[key](item) : item?.[key];
        if (!matchesFacet(actual, expected)) return false;
      }
      return predicates.every(predicate => predicate(item));
    });
  }

  return { filterItems, normalizeText };
});
""",
    "navigation.js": r"""/** Shared declarative source links and view switching; no fetch or storage.
 * UMD for legacy consumers, also usable as a side-effect ES module.
 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object' && module.exports) module.exports=api;
  else {root.webUiNavigation=api; if(root.document){const start=()=>api.bindNavigation(root);if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',start,{once:true});else start();}}
})(typeof globalThis==='undefined'?this:globalThis,function(){
  'use strict';
  function sourceURL(value){
    if(typeof value!=='string' || !/^https?:\/\//.test(value) || /[\s\\]/.test(value))throw Error('取得元は絶対HTTP(S) URLを指定してください。');
    const u=new URL(value);if(!u.hostname || u.username || u.password)throw Error('取得元URLに認証情報は指定できません。');
    return value;
  }
  function openExternalURL(value,win){
    const url=sourceURL(value);return win.open(url,'_blank','noopener,noreferrer');
  }
  const sourceBindings=new WeakMap(),viewBindings=new WeakMap();
  function bindSourceLink(input,link){
    if(!input || !link || link.tagName.toLowerCase()!=='a')throw Error('source link requires an input and anchor');
    if(sourceBindings.has(link))return sourceBindings.get(link);
    const update=()=>{
      link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';
      try{link.href=sourceURL(input.value.trim());link.hidden=false;link.removeAttribute('aria-disabled');}
      catch{link.removeAttribute('href');link.hidden=true;link.setAttribute('aria-disabled','true');}
    };
    const check=event=>{update();if(link.hidden)event.preventDefault();};
    input.addEventListener('input',update);input.addEventListener('change',update);link.addEventListener('click',check);
    const handle={update,destroy(){input.removeEventListener('input',update);input.removeEventListener('change',update);link.removeEventListener('click',check);sourceBindings.delete(link);}};
    sourceBindings.set(link,handle);update();return handle;
  }
  function viewFromLocation(hash,search,views,defaultView,queryAliases={}){
    const fragment=String(hash||'').replace(/^#/,'').split('?')[0];
    const query=new URLSearchParams(String(search||'')).get('view');
    // A declared legacy query alias may retain precedence over an old hash.
    if(query && Object.prototype.hasOwnProperty.call(queryAliases,query) && views.includes(queryAliases[query]))return queryAliases[query];
    return views.includes(fragment)?fragment:defaultView;
  }
  function bindViews(win,{viewAttribute='data-ui-view',navAttribute='data-ui-nav',defaultView='home',queryAliases={}}={}){
    const doc=win.document;
    if(!/^data-[a-z][a-z0-9-]*$/.test(viewAttribute) || !/^data-[a-z][a-z0-9-]*$/.test(navAttribute))throw Error('view attributes must be data-* names');
    if(viewBindings.has(doc))return viewBindings.get(doc);
    const panels=[...doc.querySelectorAll('['+viewAttribute+']')],navs=[...doc.querySelectorAll('['+navAttribute+']')];
    const views=panels.map(p=>p.getAttribute(viewAttribute));
    if(new Set(views).size!==views.length || !views.includes(defaultView))throw Error('views require unique names and an existing default');
    const sync=()=>{
      const view=viewFromLocation(win.location.hash,win.location.search,views,defaultView,queryAliases);
      panels.forEach(p=>p.hidden=p.getAttribute(viewAttribute)!==view);
      navs.forEach(n=>{if(n.getAttribute(navAttribute)===view)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});
      const params=new URLSearchParams(win.location.search),alias=params.get('view');
      if(alias && Object.prototype.hasOwnProperty.call(queryAliases,alias) && queryAliases[alias]===view && win.history?.replaceState){
        const url=new URL(win.location.href);url.hash=view;url.searchParams.delete('view');win.history.replaceState(null,'',url.pathname+url.search+url.hash);
      }
      return view;
    };
    win.addEventListener('hashchange',sync);win.addEventListener('popstate',sync);
    const handle={sync,destroy(){win.removeEventListener('hashchange',sync);win.removeEventListener('popstate',sync);viewBindings.delete(doc);}};
    viewBindings.set(doc,handle);sync();return handle;
  }
  // Route table: a visible identity (emoji or short name) -> app route, as in
  // browser-test-kit route_trail.py registries ({"/route": "\u{1F3E0}"}). Identity
  // drops U+FE0F, so both spellings of a heading emoji resolve to one route.
  const emojiIdentity=value=>String(value).replace(/️/g,'');
  function routeTable(registry){
    const rows=Array.isArray(registry)?registry:Object.entries(registry||{}).map(([route,key])=>({route,key}));
    const byKey=new Map(),routes=new Set(),entries=[];
    for(const row of rows){
      const route=row.route,key=row.key??row.emoji;
      if(typeof route!=='string' || !/^\/[^\s#?\\]*$/.test(route) || route.includes('//'))throw Error('route must be an absolute app path such as /map: '+route);
      if(typeof key!=='string' || !key.trim() || /\s/.test(key))throw Error('route key must be a nonempty token: '+route);
      const id=emojiIdentity(key);
      if(routes.has(route))throw Error('duplicate route: '+route);
      if(byKey.has(id))throw Error('route key names two routes: '+key);
      routes.add(route);byKey.set(id,route);entries.push({route,key,identity:id,label:typeof row.label==='string'?row.label:null});
    }
    if(!entries.length)throw Error('route table is empty');
    const lookup=value=>{const id=emojiIdentity(String(value??'').trim());return byKey.get(id)??(routes.has(id)?id:null);};
    return {entries,lookup};
  }
  function routeHref(route,{base='',routing='hash'}={}){
    if(routing!=='hash' && routing!=='path')throw Error('routing must be hash or path');
    return routing==='hash'?base+'#'+route:String(base).replace(/\/$/,'')+route;
  }
  const routeBindings=new WeakMap();
  function bindRouteTable(win,registry,{routing='hash',attribute='data-ui-go'}={}){
    const doc=win.document;
    if(routeBindings.has(doc))return routeBindings.get(doc);
    const table=routeTable(registry);
    const current=()=>routing==='hash'?(String(win.location.hash).replace(/^#/,'').split('?')[0]||'/'):win.location.pathname;
    const go=key=>{const route=table.lookup(key);if(route===null)throw Error('unknown route key: '+key);
      if(routing==='hash')win.location.hash=route;else win.location.assign(routeHref(route,{routing}));return route;};
    const controls=[...doc.querySelectorAll('['+attribute+']')];
    const sync=()=>{const here=current();for(const el of controls){const route=table.lookup(el.getAttribute(attribute));
      if(route===null){el.setAttribute('aria-disabled','true');continue;}
      if(el.tagName.toLowerCase()==='a')el.setAttribute('href',routeHref(route,{routing}));
      if(route===here)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');}
      return here;};
    const click=event=>{const el=event.target.closest?.('['+attribute+']');if(!el || el.tagName.toLowerCase()==='a')return;
      if(table.lookup(el.getAttribute(attribute))!==null){event.preventDefault();go(el.getAttribute(attribute));}};
    doc.addEventListener('click',click);win.addEventListener('hashchange',sync);win.addEventListener('popstate',sync);
    const handle={table,go,sync,current,destroy(){doc.removeEventListener('click',click);win.removeEventListener('hashchange',sync);win.removeEventListener('popstate',sync);routeBindings.delete(doc);}};
    routeBindings.set(doc,handle);sync();return handle;
  }
  function bindNavigation(win){
    const doc=win.document;
    const links=[...doc.querySelectorAll('[data-ui-source-for]')].map(link=>bindSourceLink(doc.getElementById(link.getAttribute('data-ui-source-for')),link));
    const views=doc.querySelectorAll('[data-ui-view]').length?bindViews(win,{defaultView:doc.querySelector('[data-ui-default-view]')?.getAttribute('data-ui-default-view')||'home'}):null;
    const tableScript=doc.getElementById('ui-route-table');
    const routes=tableScript?bindRouteTable(win,JSON.parse(tableScript.textContent),{routing:tableScript.getAttribute('data-ui-routing')||'hash'}):null;
    return {links,views,routes};
  }
  return {sourceURL,openExternalURL,bindSourceLink,viewFromLocation,bindViews,emojiIdentity,routeTable,routeHref,bindRouteTable,bindNavigation};
});
""",
    "repository-diagnostics.js": r"""(function (global) {
  "use strict";

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
    });
  }

  function bytes(value) {
    if (value === null || value === undefined) return "not measured";
    if (!Number.isInteger(value) || value < 0) throw new Error("invalid byte measurement");
    var units = ["B", "KiB", "MiB", "GiB"], n = value, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return (i === 0 ? String(n) : n.toFixed(2)) + " " + units[i];
  }

  function validate(record) {
    if (!record || record.schema_version !== "1.0") throw new Error("unsupported metadata schema");
    if (!record.head || !record.repository || !record.measurements) throw new Error("incomplete metadata");
    if (typeof record.repository.full_name !== "string" || !record.repository.full_name) throw new Error("invalid repository");
    if (record.head.short_sha !== record.head.sha.slice(0, 8)) throw new Error("invalid short sha");
    return record;
  }

  function commitLine(record) {
    validate(record);
    var h = record.head;
    return "Commit " + h.short_sha + " · " + h.branch + " · " + h.timestamp + " · " + h.subject;
  }

  function render(record) {
    validate(record);
    var m = record.measurements;
    return '<section class="repo-diagnostics" data-schema-version="' + esc(record.schema_version) + '">' +
      '<h2>Repository diagnostics</h2>' +
      '<p class="repo-diagnostics__repository">' + esc(record.repository.full_name) + '</p>' +
      '<p class="repo-diagnostics__commit">' + esc(commitLine(record)) + '</p>' +
      '<dl class="repo-diagnostics__measurements">' +
      '<dt>GitHub reported</dt><dd>' + esc(bytes(m.github_reported_size_bytes)) + '</dd>' +
      '<dt>Working tree</dt><dd>' + esc(bytes(m.working_tree_bytes)) + '</dd>' +
      '<dt>Release artifact</dt><dd>' + esc(bytes(m.release_artifact_bytes)) + '</dd>' +
      '</dl></section>';
  }

  var api = {validate: validate, formatBytes: bytes, commitLine: commitLine, render: render};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.RepositoryDiagnostics = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
""",
}
EMBEDDED_UI_JS = _JS["ui.js"]

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


# The stylesheets, as data: Python is the only source (there are no css/ files). Names are kept so the bundle order is stable.
_CSS = {
    "shell.css": (
        "@layer components{"
        ".ui-shell{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr) auto;height:100vh;height:100dvh;min-width:0;background:var(--ui-bg);color:var(--ui-fg)}"
        ".ui-shell-radio{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}"
        ".ui-shell-icons{position:absolute;width:0;height:0;overflow:hidden}"
        ".ui-shell svg{width:24px;height:24px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}"
        ".ui-shell-header{display:flex;align-items:center;gap:8px;min-height:56px;padding:0 8px;background:var(--ui-panel);border-bottom:1px solid var(--ui-border)}"
        ".ui-shell-title{flex:1;min-width:0;margin:0 8px;font-size:1.25rem;font-weight:400;line-height:1.25;overflow-wrap:anywhere}"
        ".ui-shell-actions{display:flex;align-items:center;gap:8px;flex:none}.ui-shell-actions .ui-input{padding:8px;max-width:128px}"
        ".ui-icon-button{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;padding:0;border-radius:50%;flex:none;cursor:pointer}"
        ".ui-icon-button[aria-pressed=true] svg{fill:currentColor}"
        ".ui-shell-body{display:flex;min-height:0}"
        ".ui-rail{display:none;flex-direction:column;gap:8px;width:80px;flex:none;padding:8px;border-right:1px solid var(--ui-border);background:var(--ui-panel);overflow:auto}"
        ".ui-rail-item,.ui-bottom-item{display:flex;align-items:center;gap:16px;min-height:48px;padding:0 16px;border-radius:var(--ui-radius);cursor:pointer}"
        ".ui-rail-label,.ui-bottom-label{font-size:.75rem}"
        ".ui-shell-main{flex:1;min-width:0;min-height:0;overflow-x:hidden;overflow-y:auto;padding:24px;overscroll-behavior:contain}"
        ".ui-shell-main h2{margin:0 0 16px;font-size:1.5rem;font-weight:400}"
        ".ui-shell-tags{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px}"
        ".ui-shell-cards{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(256px,1fr))}"
        ".ui-shell-card{display:flex;gap:16px;margin:0;min-width:0}.ui-shell-card h3{margin:0 0 8px;font-size:1rem;font-weight:400}.ui-shell-card p{margin:0;overflow-wrap:anywhere}"
        ".ui-shell-table{width:100%;border-collapse:collapse}.ui-shell-table th,.ui-shell-table td{padding:8px 16px;border-bottom:1px solid var(--ui-border);text-align:left}"
        ".ui-shell-scroll{overflow-x:auto}.ui-shell-controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}"
        ".ui-bottom-nav{display:flex;border-top:1px solid var(--ui-border);background:var(--ui-panel)}"
        ".ui-bottom-item{flex:1;flex-direction:column;justify-content:center;gap:0;min-height:64px;padding:8px 0;text-align:center}"
        "@media(min-width:900px){.ui-rail{display:flex}.ui-bottom-nav{display:none}.ui-rail-item{justify-content:center;padding:0}"
        ".ui-rail-label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}}"
        "@media(min-width:1200px){.ui-rail{width:256px}.ui-rail-item{justify-content:flex-start;padding:0 16px}"
        ".ui-rail-label{position:static;width:auto;height:auto;margin:0;overflow:visible;clip-path:none;white-space:normal}}"
        "@media(max-height:480px){.ui-shell{height:auto;min-height:100dvh}.ui-shell-body{min-height:240px}.ui-shell-main{overflow:visible}}"
        "@media(prefers-reduced-motion:reduce){.ui-shell-main{scroll-behavior:auto}}"
        "}"
    ),
    "tokens.css": r""":root{--ui-bg:#0d1117;--ui-panel:#101820;--ui-fg:#d1f7c4;--ui-muted:#8b949e;--ui-border:#58a6ff;--ui-accent:#7ee787;--ui-danger:#cf222e;--ui-radius:0;--ui-space:1rem;--ui-max:960px;--ui-font:Meiryo,メイリオ,sans-serif;--ui-font-mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}
""",
    "base.css": r"""@layer base{*{box-sizing:border-box}body{margin:0;background:var(--ui-bg);color:var(--ui-fg);font:16px/1.6 var(--ui-font)}pre,code,kbd,samp{font-family:var(--ui-font-mono)!important}.ui-page{max-width:var(--ui-max);margin:auto;padding:1.25rem}a{color:inherit}}""",
    "components.css": r"""@layer components{.ui-panel,.ui-card{background:var(--ui-panel);border:1px solid var(--ui-border);padding:1rem;margin:1rem 0;border-radius:var(--ui-radius)}.ui-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.75rem}.ui-tag{display:inline-block;border:1px solid var(--ui-border);padding:.1rem .4rem}.ui-button,.ui-input{font:inherit;background:var(--ui-panel);color:var(--ui-fg);border:1px solid var(--ui-border);padding:.6rem;border-radius:var(--ui-radius)}.ui-muted{color:var(--ui-muted)}.ui-output{font:inherit;white-space:pre-wrap;overflow:auto;background:#d8dee4;color:#161b22;border:1px solid #8c959f;border-radius:4px;padding:.75rem}pre code,.ui-output code{font-family:inherit;color:inherit}pre.ui-output code{background:transparent}@media(max-width:480px){.ui-page{padding:.75rem}.ui-grid{grid-template-columns:1fr}.ui-card,.ui-panel{margin:.75rem 0;padding:.75rem}}.ui-lightbox{border:1px solid var(--ui-border);background:var(--ui-panel);color:var(--ui-fg);padding:1rem;max-width:min(96vw,960px);max-height:96vh;border-radius:var(--ui-radius)}.ui-lightbox::backdrop{background:rgba(0,0,0,.72)}.ui-lightbox img{display:block;max-width:100%;max-height:calc(96vh - 8rem);margin:auto}.ui-lightbox-bar{display:flex;gap:.5rem;justify-content:space-between;margin-top:.75rem}body:has(.ui-lightbox[open]){overflow:hidden}}""",
    "matrix.css": r"""@layer components{.ui-matrix:has(>section:target)>section:not(:target){display:none}.ui-matrix>section{scroll-margin-top:16px}.ui-matrix-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--ui-matrix-col,160px),1fr));gap:var(--ui-matrix-gap,8px);padding:0;list-style:none}.ui-matrix-tiles li{border:1px solid var(--ui-border);padding:var(--ui-matrix-pad,8px);font-size:.8rem;overflow-wrap:anywhere}.ui-matrix-tiles img{display:block;width:100%;height:auto;margin:var(--ui-matrix-pad,8px) 0;background:#fff}.ui-matrix-tiles .is-missing{border-style:dashed;color:var(--ui-muted)}.ui-matrix-tiles .is-fail{outline:2px solid var(--ui-danger)}.ui-matrix-tiles .is-reference{outline:2px solid var(--ui-accent)}.ui-matrix-page>nav{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.ui-matrix-page>nav .ui-button{white-space:nowrap;text-decoration:none}.ui-matrix a{overflow-wrap:anywhere}}
""",
    "repository-diagnostics.css": r""".repo-diagnostics{box-sizing:border-box;border:1px solid var(--ui-border,#c9c9cf);border-radius:1rem;padding:1.25rem;background:var(--ui-surface,#fff);color:var(--ui-text,#222)}.repo-diagnostics h2{margin:0 0 .75rem;font-size:1.25rem}.repo-diagnostics__commit{overflow-wrap:anywhere}.repo-diagnostics__measurements{display:grid;grid-template-columns:minmax(8rem,1fr) 1fr;gap:.45rem 1rem;margin:1rem 0 0}.repo-diagnostics__measurements dt,.repo-diagnostics__measurements dd{margin:0}.repo-diagnostics__measurements dd{font-variant-numeric:tabular-nums}@media(max-width:30rem){.repo-diagnostics__measurements{grid-template-columns:1fr}.repo-diagnostics__measurements dd{margin-bottom:.35rem}}
""",
    "stub.css": r"""@layer components{
.stub-shell{display:grid;gap:1rem}
/* Keep title/description and metadata side-by-side when space permits; wrap rather than compress either region. */
.stub-header{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.stub-toolbar{display:flex;gap:.5rem;flex-wrap:wrap}
.stub-toolbar fieldset{display:flex;gap:.5rem;align-items:end;flex-wrap:wrap;width:100%;border:0;padding:0;margin:0}
.stub-toolbar label{display:block}
.stub-toolbar .ui-input{flex:1 1 16rem}
.stub-status{margin:.75rem 0 0}
.stub-meta{display:flex;gap:.5rem;flex-wrap:wrap;margin:.75rem 0}
/* Primary result pane + secondary evidence/history sidebar. */
.stub-workspace{display:grid;grid-template-columns:minmax(0,1fr) minmax(16rem,.45fr);gap:1rem}
.stub-result,.stub-evidence,.stub-history{min-width:0}
.stub-actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.75rem;padding-top:.75rem;border-top:1px solid var(--ui-border)}
.stub-endpoint{overflow-wrap:anywhere}
@media(max-width:720px){.stub-workspace{grid-template-columns:1fr}.stub-header{display:block}}
}""",
    "themes/github-like.css": r"""/* GitHub-like prioritizes familiar light GitHub visual cues while remaining a generic light theme. */
@layer theme{
body[data-ui-theme="github-like"]{
  --ui-bg:#ffffff;
  --ui-panel:#f6f8fa;
  --ui-fg:#1f2328;
  --ui-muted:#59636e;
  --ui-border:#d0d7de;
  --ui-accent:#0969da;
}
body[data-ui-theme="github-like"] .ui-panel,
body[data-ui-theme="github-like"] .ui-card{
  background:var(--ui-panel);
  border-radius:.375rem;
  box-shadow:none;
}
body[data-ui-theme="github-like"] .ui-button,
body[data-ui-theme="github-like"] .ui-input{
  background:#ffffff;
}
body[data-ui-theme="github-like"] .ui-title{
  border-bottom:1px solid var(--ui-border);
  padding-bottom:.5rem;
}
body[data-ui-theme="github-like"] .ui-tag{
  border-radius:999px;
  color:var(--ui-accent);
}
}
""",
    "themes/modern.css": r"""@layer theme{body[data-ui-theme="modern"]{color-scheme:dark}body[data-ui-theme="modern"] .ui-title::before,body[data-ui-theme="modern"] .ui-card>h2::before{content:"> ";color:var(--ui-accent)}body[data-ui-theme="modern"] .ui-panel,body[data-ui-theme="modern"] .ui-card{background:var(--ui-panel);box-shadow:4px 4px 0 rgba(88,166,255,.16)}body[data-ui-theme="modern"] .ui-tag::before{content:"#";color:var(--ui-accent)}}""",
}
_CSS_CORE = ("tokens.css", "base.css", "components.css")


def css_source(name: str) -> str:
    """One stylesheet source by name, e.g. ``tokens.css`` or ``themes/modern.css`` (raw text).

    ``tokens.css`` is the ``:root`` defaults plus one generated block per token-only theme (CANDIDATE_THEMES)."""
    try:
        text = _CSS[name]
    except KeyError:
        raise ValueError(f"unknown stylesheet: {name}") from None
    return text.rstrip("\n") + "\n" + _token_theme_css() if name == "tokens.css" else text


def bundled_css() -> str:
    """Every stylesheet as one string, built in memory (nothing is written, there are no css/ files).

    ``render_document(css=bundled_css())`` gives a single-file page that works under every
    ``data-ui-theme``, so switching themes needs no stylesheet swap and no reload. Order is part
    of the contract: tokens, base and components, then the other top-level sources by name, then
    the themes by name; the ``@layer`` line fixes layer order whichever source comes first.
    """
    order = [*_CSS_CORE, *(n for n in sorted(_CSS) if "/" not in n and n not in _CSS_CORE),
             *(n for n in sorted(_CSS) if n.startswith("themes/"))]
    parts = ["@layer base,components,theme;\n"]
    for name in order:
        parts.append(f"/* css/{name} */\n{css_source(name).replace(chr(13) + chr(10), chr(10)).strip(chr(10))}\n")
    return "".join(parts)


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
    if name not in ("ui.js", "world.js"):
        raise ValueError("unknown embedded module")
    return (EMBEDDED_UI_JS if name == "ui.js" else WORLD_JS).encode("utf-8"), "text/javascript; charset=utf-8"


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
    if theme not in THEMES + CANDIDATE_THEMES:
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


def adopt_document(page: str, *, asset_base: str | None = None, class_aliases: dict[str, str] | None = None,
                   remove_stylesheets: tuple[str, ...] = (), theme: str = "modern") -> str:
    """Apply shared presentation to an audited, double-quoted static export.

    Preserve IDs, routes, script bodies and report content. This is not a
    visitor-input sanitizer or a general HTML parser. Consumers keep original
    hashes and label the transformed publication separately. The shared CSS is
    embedded (bundled_css()); ``asset_base`` is accepted for old callers and unused.
    """
    if theme not in THEMES + CANDIDATE_THEMES:
        raise ValueError("unknown theme")
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
    style = '<style data-shared-ui="web-ui">' + bundled_css() + '</style>'
    if 'data-shared-ui="web-ui"' not in page:
        if '</head>' not in page:
            raise ValueError("shared presentation requires a document head")
        page = page.replace('</head>', style + '</head>', 1)
    return page


# Exact snapshot of the locked stdlib launcher for single-file distribution.
# Keep byte-for-byte parity with vendor/node_launch.py (covered by tests).
_EMBEDDED_NODE_LAUNCH_SOURCE = '"""Shared Python launcher for Node.js scripts (stdlib only, Python 3.9+).\n\nLibrary: ``run(target, *args, node=..., input=..., timeout=..., max_input_bytes=...,\nresponse_max_bytes=..., env=..., env_var=...)`` returns stdout/stderr as ``bytes``.\n``run_argv(argv, ...)`` prepends a resolved Node executable to ``argv``.\n\nNode resolution (first match that runs Node 26+): explicit ``node``,\n``os.environ[env_var]`` when set, then ``shutil.which("node")``. Explicit ``node`` or a\nset ``env_var`` value does not fall back to later candidates. Windows ``.cmd``/``.bat``\nshims are never spawned with ``shell=True``; explicit paths are rejected.\n\n``env`` merges over ``os.environ`` case-insensitively on Windows. Optional\n``max_input_bytes`` / ``response_max_bytes`` raise errors with stable ``code`` values:\n``EINPUTTOOLARGE``, ``ERESPONSETOOLARGE``, ``ELAUNCHFAILURE``, and\n``ELAUNCHSTDINCLOSED`` when stdin breaks (``EPIPE``) before the child finishes reading.\nStdout is read incrementally when ``response_max_bytes`` is set (cap plus\n``HOST_RESPONSE_MARGIN_BYTES``, matching ``py_launch.cjs`` ``maxBuffer`` / ``ENOBUFS``).\n"""\nfrom __future__ import annotations\n\nimport errno\nimport os\nimport re\nimport shutil\nimport subprocess\nimport sys\nimport threading\nfrom typing import Any, Mapping, Optional, Sequence, Union\n\nMIN_NODE_MAJOR = 26\nDEFAULT_ENV_VAR = "NODE"\nDEFAULT_PROBE_TIMEOUT = 5.0\nHOST_RESPONSE_MARGIN_BYTES = 512\n_NODE_VERSION = re.compile(r"(?:^|\\s)v?(?P<major>\\d+)(?:\\.\\d+)*", re.IGNORECASE)\n_NODE_PROBE_CACHE: dict[str, str] = {}\n\n\nclass NodeNotFoundError(FileNotFoundError):\n    """Raised when Node.js cannot be located or does not meet the minimum version."""\n\n\nclass LaunchError(RuntimeError):\n    """Raised when the Node child fails to start, exceeds caps, or exits unexpectedly."""\n\n    def __init__(\n        self,\n        message: str,\n        *,\n        code: str = "ELAUNCHFAILURE",\n        status: Optional[int] = None,\n        stdout: bytes = b"",\n        stderr: bytes = b"",\n        signal: Optional[int] = None,\n    ) -> None:\n        super().__init__(message)\n        self.code = code\n        self.status = status\n        self.stdout = stdout\n        self.stderr = stderr\n        self.signal = signal\n\n\ndef is_node_target(path: Union[str, os.PathLike[str]]) -> bool:\n    """True when ``path`` names a JavaScript entry file by extension."""\n    return os.path.splitext(os.fspath(path))[1].lower() in (".js", ".cjs", ".mjs")\n\n\ndef _env_key_fold(key: str) -> str:\n    return str(key).casefold()\n\n\ndef env_lookup(env: Mapping[str, str], name: str) -> Optional[str]:\n    """Case-insensitive environment lookup (primarily for Windows tests)."""\n    fold = _env_key_fold(name)\n    for key, value in env.items():\n        if _env_key_fold(key) == fold:\n            return value\n    return None\n\n\ndef build_child_env(overrides: Optional[Mapping[str, str]]) -> Optional[dict[str, str]]:\n    """Merge ``overrides`` onto ``os.environ``; Windows overrides replace folded keys."""\n    if overrides is None:\n        return None\n    if os.name != "nt":\n        merged = dict(os.environ)\n        merged.update(overrides)\n        return merged\n    env = dict(os.environ)\n    index: dict[str, str] = {_env_key_fold(key): key for key in env}\n    for override_key, value in overrides.items():\n        fold = _env_key_fold(override_key)\n        existing = index.get(fold)\n        if existing is not None:\n            del env[existing]\n        env[override_key] = value\n        index[fold] = override_key\n    return env\n\n\ndef _reject_windows_batch_wrapper(path: str) -> None:\n    lowered = path.lower()\n    if lowered.endswith(".cmd") or lowered.endswith(".bat"):\n        raise NodeNotFoundError(\n            "node_launch: node batch wrappers (.cmd/.bat) are not supported: " + path\n        )\n\n\ndef _decode(data: bytes) -> str:\n    if not data:\n        return ""\n    return data.decode("utf-8", errors="replace")\n\n\ndef _probe_node_once(path: str, probe_timeout: float) -> str:\n    cached = _NODE_PROBE_CACHE.get(path)\n    if cached is not None:\n        return cached\n    _reject_windows_batch_wrapper(path)\n    try:\n        completed = subprocess.run(\n            (path, "--version"),\n            capture_output=True,\n            timeout=probe_timeout,\n            shell=False,\n            check=False,\n        )\n    except FileNotFoundError as exc:\n        raise NodeNotFoundError("node_launch: node executable not found: " + path) from exc\n    except OSError as exc:\n        raise NodeNotFoundError("node_launch: node version probe failed: " + path) from exc\n    except subprocess.TimeoutExpired as exc:\n        raise NodeNotFoundError("node_launch: node version probe timed out: " + path) from exc\n    output = _decode(completed.stdout) + _decode(completed.stderr)\n    match = _NODE_VERSION.search(output)\n    if completed.returncode != 0 or match is None:\n        raise NodeNotFoundError("node_launch: node version probe failed: " + path)\n    major = int(match.group("major"))\n    if major < MIN_NODE_MAJOR:\n        raise NodeNotFoundError(\n            f"node_launch: node version must be {MIN_NODE_MAJOR} or newer (found {major}): "\n            + path\n        )\n    _NODE_PROBE_CACHE[path] = path\n    return path\n\n\ndef _node_executable(\n    node: Optional[Union[str, os.PathLike[str]]],\n    *,\n    env_var: str,\n    probe: bool,\n    probe_timeout: float,\n) -> str:\n    explicit = node is not None\n    if not explicit and env_var and env_var in os.environ:\n        node = os.environ[env_var]\n        explicit = True\n    if explicit:\n        path = os.fspath(node)\n        _reject_windows_batch_wrapper(path)\n        return _probe_node_once(path, probe_timeout) if probe else path\n\n    if not probe:\n        discovered = shutil.which("node")\n        path = discovered if discovered else "node"\n        _reject_windows_batch_wrapper(path)\n        return path\n\n    discovered = shutil.which("node")\n    if discovered:\n        try:\n            return _probe_node_once(discovered, probe_timeout)\n        except NodeNotFoundError:\n            pass\n    raise NodeNotFoundError("node_launch: node executable not found")\n\n\ndef resolve_node(\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    *,\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n) -> str:\n    """Locate a Node 26+ executable.\n\n    Explicit ``node`` or a set ``env_var`` environment value must work as given;\n    auto-discovery uses ``shutil.which(\'node\')`` on ``PATH``.\n    """\n    return _node_executable(\n        node, env_var=env_var, probe=probe, probe_timeout=probe_timeout\n    )\n\n\ndef node_command(\n    target: Union[str, os.PathLike[str]],\n    *args: Union[str, os.PathLike[str]],\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    node_flags: Sequence[Union[str, os.PathLike[str]]] = (),\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n) -> list[str]:\n    """Build ``[node, *node_flags, target, *args]`` without reinterpreting passthrough argv."""\n    executable = _node_executable(\n        node, env_var=env_var, probe=probe, probe_timeout=probe_timeout\n    )\n    flags = [os.fspath(value) for value in node_flags]\n    script = os.fspath(target)\n    trailing = [os.fspath(value) for value in args]\n    return [executable, *flags, script, *trailing]\n\n\ndef node_or_command(\n    argv: Sequence[Union[str, os.PathLike[str]]],\n    *,\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    node_flags: Sequence[Union[str, os.PathLike[str]]] = (),\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n) -> list[str]:\n    """Prepend Node when ``argv[0]`` names a ``.js`` / ``.cjs`` / ``.mjs`` file."""\n    tokens = [os.fspath(value) for value in argv]\n    if not tokens:\n        return tokens\n    if is_node_target(tokens[0]):\n        return node_command(\n            tokens[0],\n            *tokens[1:],\n            node=node,\n            node_flags=node_flags,\n            env_var=env_var,\n            probe=probe,\n            probe_timeout=probe_timeout,\n        )\n    return tokens\n\n\ndef _nonnegative_int(name: str, value: int) -> None:\n    if not isinstance(value, int) or value < 0:\n        raise ValueError(f"node_launch: {name} must be a nonnegative integer")\n\n\ndef _input_byte_length(input_data: Optional[Union[str, bytes]]) -> int:\n    if input_data is None:\n        return 0\n    if isinstance(input_data, str):\n        return len(input_data.encode("utf-8"))\n    return len(input_data)\n\n\ndef _normalize_input(input_data: Optional[Union[str, bytes]]) -> Optional[bytes]:\n    if input_data is None:\n        return None\n    if isinstance(input_data, str):\n        return input_data.encode("utf-8")\n    return input_data\n\n\ndef _response_cap_bytes(response_max_bytes: int) -> int:\n    _nonnegative_int("response_max_bytes", response_max_bytes)\n    return response_max_bytes + HOST_RESPONSE_MARGIN_BYTES\n\n\ndef _launch_failure_from_returncode(\n    returncode: int,\n    stdout: bytes,\n    stderr: bytes,\n) -> LaunchError:\n    if returncode < 0:\n        signum = -returncode\n        return LaunchError(\n            f"node_launch: Node process terminated by signal {signum}",\n            code="ELAUNCHFAILURE",\n            signal=signum,\n            stdout=stdout,\n            stderr=stderr,\n        )\n    message = _decode(stderr).strip() or "Node script failed"\n    return LaunchError(\n        message,\n        code="ELAUNCHFAILURE",\n        status=returncode,\n        stdout=stdout,\n        stderr=stderr,\n    )\n\n\ndef _exit_code_for_main(returncode: Optional[int]) -> None:\n    if returncode is None or returncode == 0:\n        return\n    if returncode < 0:\n        sys.exit(128 + (-returncode))\n    sys.exit(returncode)\n\n\ndef _stream_communicate(\n    proc: subprocess.Popen,\n    input_bytes: Optional[bytes],\n    timeout: Optional[float],\n    response_max_bytes: Optional[int],\n) -> tuple[bytes, bytes, int]:\n    hard_limit = None\n    cap: Optional[int] = None\n    if response_max_bytes is not None:\n        _nonnegative_int("response_max_bytes", response_max_bytes)\n        cap = response_max_bytes\n        hard_limit = _response_cap_bytes(response_max_bytes)\n\n    stdout_chunks: list[bytes] = []\n    stderr_chunks: list[bytes] = []\n    stdout_len = 0\n    exceeded = threading.Event()\n    read_lock = threading.Lock()\n    stdin_code: list[Optional[str]] = [None]\n    stdin_os_error: list[Optional[OSError]] = [None]\n\n    def read_stdout() -> None:\n        nonlocal stdout_len\n        stream = proc.stdout\n        if stream is None:\n            return\n        try:\n            while True:\n                chunk = stream.read(65536)\n                if not chunk:\n                    break\n                if hard_limit is not None:\n                    with read_lock:\n                        stdout_len += len(chunk)\n                        if stdout_len > hard_limit:\n                            exceeded.set()\n                            try:\n                                proc.kill()\n                            except OSError:\n                                pass\n                            break\n                stdout_chunks.append(chunk)\n        finally:\n            stream.close()\n\n    def read_stderr() -> None:\n        stream = proc.stderr\n        if stream is None:\n            return\n        try:\n            while True:\n                chunk = stream.read(65536)\n                if not chunk:\n                    break\n                stderr_chunks.append(chunk)\n        finally:\n            stream.close()\n\n    def write_stdin() -> None:\n        stream = proc.stdin\n        if stream is None:\n            return\n        if input_bytes is None:\n            try:\n                stream.close()\n            except OSError:\n                pass\n            return\n        try:\n            offset = 0\n            chunk_size = 65536\n            while offset < len(input_bytes):\n                stream.write(input_bytes[offset : offset + chunk_size])\n                offset += chunk_size\n            stream.flush()\n            stream.close()\n        except BrokenPipeError:\n            stdin_code[0] = "ELAUNCHSTDINCLOSED"\n            try:\n                stream.close()\n            except OSError:\n                pass\n        except OSError as exc:\n            if exc.errno == errno.EPIPE:\n                stdin_code[0] = "ELAUNCHSTDINCLOSED"\n                try:\n                    stream.close()\n                except OSError:\n                    pass\n            else:\n                stdin_os_error[0] = exc\n                try:\n                    stream.close()\n                except OSError:\n                    pass\n\n    stdout_thread = threading.Thread(target=read_stdout, name="node_launch_stdout", daemon=True)\n    stderr_thread = threading.Thread(target=read_stderr, name="node_launch_stderr", daemon=True)\n    stdin_thread = threading.Thread(target=write_stdin, name="node_launch_stdin", daemon=True)\n    stdout_thread.start()\n    stderr_thread.start()\n    stdin_thread.start()\n\n    timed_out = False\n    returncode: Optional[int]\n    try:\n        returncode = proc.wait(timeout=timeout)\n    except subprocess.TimeoutExpired:\n        timed_out = True\n        try:\n            proc.kill()\n        except OSError:\n            pass\n        proc.wait()\n        returncode = proc.returncode\n\n    stdin_thread.join()\n    stdout_thread.join()\n    stderr_thread.join()\n\n    stdout = b"".join(stdout_chunks)\n    stderr = b"".join(stderr_chunks)\n    if returncode is None:\n        returncode = proc.returncode if proc.returncode is not None else -1\n\n    if stdin_os_error[0] is not None:\n        exc = stdin_os_error[0]\n        raise LaunchError(\n            f"node_launch: Node process failed: {exc}",\n            code="ELAUNCHFAILURE",\n            stdout=stdout,\n            stderr=stderr,\n        ) from exc\n\n    if timed_out:\n        raise LaunchError(\n            "node_launch: Node process timed out",\n            code="ELAUNCHFAILURE",\n            stdout=stdout,\n            stderr=stderr,\n        )\n\n    if stdin_code[0] == "ELAUNCHSTDINCLOSED":\n        raise LaunchError(\n            "node_launch: Node stdin pipe closed unexpectedly",\n            code="ELAUNCHSTDINCLOSED",\n            status=returncode,\n            stdout=stdout,\n            stderr=stderr,\n        )\n\n    if exceeded.is_set() or (cap is not None and len(stdout) > cap):\n        raise LaunchError(\n            f"node_launch: response exceeds response_max_bytes ({cap})",\n            code="ERESPONSETOOLARGE",\n            status=returncode,\n            stdout=stdout,\n            stderr=stderr,\n        )\n\n    return stdout, stderr, returncode\n\n\ndef _communicate(\n    proc: subprocess.Popen,\n    input_bytes: Optional[bytes],\n    timeout: Optional[float],\n    response_max_bytes: Optional[int],\n) -> tuple[bytes, bytes, int]:\n    return _stream_communicate(proc, input_bytes, timeout, response_max_bytes)\n\n\ndef run_argv(\n    argv: Sequence[Union[str, os.PathLike[str]]],\n    *,\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n    input: Optional[Union[str, bytes]] = None,\n    timeout: Optional[float] = None,\n    max_input_bytes: Optional[int] = None,\n    response_max_bytes: Optional[int] = None,\n    env: Optional[Mapping[str, str]] = None,\n    check: bool = True,\n) -> subprocess.CompletedProcess:\n    """Run ``[resolved_node, *argv]`` with ``shell=False`` and byte stdout/stderr."""\n    executable = _node_executable(\n        node, env_var=env_var, probe=probe, probe_timeout=probe_timeout\n    )\n    _reject_windows_batch_wrapper(executable)\n    command = [executable, *[os.fspath(value) for value in argv]]\n\n    input_len = _input_byte_length(input)\n    if max_input_bytes is not None:\n        _nonnegative_int("max_input_bytes", max_input_bytes)\n        if input_len > max_input_bytes:\n            raise LaunchError(\n                f"node_launch: input exceeds max_input_bytes ({max_input_bytes}; got {input_len} bytes)",\n                code="EINPUTTOOLARGE",\n            )\n\n    child_env = build_child_env(env)\n    input_bytes = _normalize_input(input)\n\n    try:\n        proc = subprocess.Popen(\n            command,\n            stdin=subprocess.PIPE,\n            stdout=subprocess.PIPE,\n            stderr=subprocess.PIPE,\n            shell=False,\n            env=child_env,\n        )\n    except OSError as exc:\n        raise LaunchError(\n            f"node_launch: Node process failed: {exc}",\n            code="ELAUNCHFAILURE",\n        ) from exc\n\n    stdout, stderr, returncode = _communicate(\n        proc, input_bytes, timeout, response_max_bytes\n    )\n\n    if returncode != 0 and check:\n        raise _launch_failure_from_returncode(returncode, stdout, stderr)\n\n    return subprocess.CompletedProcess(command, returncode, stdout, stderr)\n\n\ndef run(\n    target: Union[str, os.PathLike[str]],\n    *args: Union[str, os.PathLike[str]],\n    node: Optional[Union[str, os.PathLike[str]]] = None,\n    node_flags: Sequence[Union[str, os.PathLike[str]]] = (),\n    env_var: str = DEFAULT_ENV_VAR,\n    probe: bool = True,\n    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,\n    input: Optional[Union[str, bytes]] = None,\n    timeout: Optional[float] = None,\n    max_input_bytes: Optional[int] = None,\n    response_max_bytes: Optional[int] = None,\n    env: Optional[Mapping[str, str]] = None,\n    check: bool = True,\n) -> subprocess.CompletedProcess:\n    """Run ``node_command(...)`` and return captured stdout/stderr as bytes."""\n    argv = node_command(\n        target,\n        *args,\n        node=node,\n        node_flags=node_flags,\n        env_var=env_var,\n        probe=probe,\n        probe_timeout=probe_timeout,\n    )\n    return run_argv(\n        argv[1:],\n        node=argv[0],\n        env_var=env_var,\n        probe=False,\n        input=input,\n        timeout=timeout,\n        max_input_bytes=max_input_bytes,\n        response_max_bytes=response_max_bytes,\n        env=env,\n        check=check,\n    )\n\n\ndef run_node(\n    target: Union[str, os.PathLike[str]],\n    *args: Union[str, os.PathLike[str]],\n    **kwargs: Any,\n) -> subprocess.CompletedProcess:\n    """Alias for :func:`run` matching the cli_args helper name."""\n    return run(target, *args, **kwargs)\n\n\ndef main(\n    script_path: Union[str, os.PathLike[str]],\n    opts: Optional[Mapping[str, Any]] = None,\n) -> None:\n    """Spawn a Node script with inherited stdio and forwarded exit code."""\n    options = dict(opts or {})\n    argv = options.pop("argv", None)\n    if argv is None:\n        argv = sys.argv[1:]\n    env_var = options.pop("env_var", DEFAULT_ENV_VAR)\n    node = options.pop("node", None)\n    node_flags = options.pop("node_flags", ())\n    probe_timeout = options.pop("probe_timeout", DEFAULT_PROBE_TIMEOUT)\n    child_env = build_child_env(options.pop("env", None))\n    try:\n        command = node_command(\n            script_path,\n            *argv,\n            node=node,\n            node_flags=node_flags,\n            env_var=env_var,\n            probe=True,\n            probe_timeout=probe_timeout,\n        )\n        _reject_windows_batch_wrapper(command[0])\n    except NodeNotFoundError as error:\n        sys.stderr.write(f"{error}\\n")\n        sys.exit(2)\n    try:\n        completed = subprocess.run(\n            command,\n            shell=False,\n            env=child_env,\n            check=False,\n        )\n    except OSError as error:\n        sys.stderr.write(f"node_launch: {error}\\n")\n        sys.exit(2)\n    if completed.returncode != 0:\n        _exit_code_for_main(completed.returncode)\n\n\ndef clear_probe_cache() -> None:\n    """Clear the version-probe cache (for tests)."""\n    _NODE_PROBE_CACHE.clear()\n'

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
    version = re.search(r"must be \d+ or newer \(found (\d+)\)", message)
    if version is not None:
        raise RuntimeError(
            f"node requires Node 26 or newer; found Node {version.group(1)}"
        ) from exc
    if node is None and "node executable not found" in message:
        discovered = shutil.which("node")
        if discovered:
            node_launch = _node_launch_module()
            try:
                node_launch._probe_node_once(discovered, node_launch.DEFAULT_PROBE_TIMEOUT)
            except node_launch.NodeNotFoundError as probe_exc:
                version = re.search(r"must be \d+ or newer \(found (\d+)\)", str(probe_exc))
                if version is not None:
                    raise RuntimeError(
                        f"node requires Node 26 or newer; found Node {version.group(1)}"
                    ) from exc
    raise RuntimeError("node requires Node 26 or newer; node executable not found on PATH") from exc


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
    """Wrap Node 26+ for pytest/CI one-liners. Does not start a browser or fetch URLs."""
    run_kwargs = dict(kwargs)
    run_kwargs.setdefault("check", False)
    return _web_ui_node_run(*argv, timeout=timeout, **run_kwargs)


# --- World: one page, a camera, no page changes (scrolling "shots" and a pan/zoom map) -----------------
# Everything is built here in memory: Python validates the data, does the arithmetic, and emits the HTML,
# the CSS and a thin JavaScript module. JS only applies state (data-lit, camera variables); CSS does the rest.

WORLD_SCHEMA = "web-ui-world/1"
_WORLD_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")  # the world itself: it prefixes element ids, so it starts with a letter
_WORLD_TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")  # floors, shots, spots, categories (1f is fine)
_WORLD_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio of two #rrggbb colors."""
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def ink_for(background: str) -> str:
    """Black or white text, whichever reads better on ``background``."""
    return "#0b0b0c" if contrast_ratio("#0b0b0c", background) >= contrast_ratio("#ffffff", background) else "#ffffff"


def fit_zoom(width: float, height: float, view_w: float, view_h: float) -> float:
    """Zoom at which a width x height map just fits a view_w x view_h view."""
    return min(view_w / width, view_h / height)


def clamp_focus(fx: float, fy: float, zoom: float, width: float, height: float,
                view_w: float, view_h: float) -> tuple[float, float]:
    """Keep the camera's focal point (map units) so the view never leaves the map; a map smaller than the view is centered."""
    half_w, half_h = view_w / (2 * zoom), view_h / (2 * zoom)
    return (min(max(fx, half_w), width - half_w) if width > 2 * half_w else width / 2,
            min(max(fy, half_h), height - half_h) if height > 2 * half_h else height / 2)


# Motion uses elapsed monotonic seconds; boards use Unix UTC seconds. All inputs
# are bounded so static documents cannot request unbounded plans or DOM nodes.
def _motion_number(value: Any, label: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{label} must be finite and from {low} to {high}")
    return float(value)


def world_walk(start: list[float], target: list[float], *, at: float = 0,
               speed: float = 40, width: float = 1024, height: float = 768) -> dict[str, Any]:
    """One constant-velocity segment. Targets clamp at map edges; no overshoot.

    For retarget/pause/resume first sample the old segment at the event's time,
    then start a new segment from that point. Never integrate per frame.
    """
    width = _motion_number(width, "width", 64, 4096)
    height = _motion_number(height, "height", 64, 4096)
    at = _motion_number(at, "at", 0, 1e9)
    speed = _motion_number(speed, "speed", 1, 480)
    points = []
    for point in (start, target):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("point must have two coordinates")
        points.append([min(bound, max(0., _motion_number(v, "coordinate", -1e6, 1e6)))
                       for v, bound in zip(point, (width, height))])
    a, b = points
    return {"at": at, "duration": math.hypot(b[0] - a[0], b[1] - a[1]) / speed, "from": a, "to": b}


def world_motion_sample(segment: dict[str, Any], elapsed: float) -> list[float]:
    """Project a validated/generated segment at absolute elapsed seconds; endpoints hold."""
    elapsed = _motion_number(elapsed, "elapsed", 0, 1e9)
    at = _motion_number(segment["at"], "at", 0, 1e9)
    duration = _motion_number(segment["duration"], "duration", 0, 1e6)
    points = [segment[key] for key in ("from", "to")]
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points):
        raise ValueError("point must have two coordinates")
    a, b = [[_motion_number(v, "coordinate", 0, 4096) for v in p] for p in points]
    fraction = (1. if elapsed >= at else 0.) if duration == 0 else min(1., max(0., (elapsed - at) / duration))
    return [a[i] + (b[i] - a[i]) * fraction for i in (0, 1)]


def travel_seconds(x0: float, y0: float, x1: float, y1: float, speed: float) -> float:
    """Seconds to walk in a straight line at constant ``speed`` (map units per second)."""
    x0, y0, x1, y1 = [_motion_number(v, "coordinate", -1e6, 1e6) for v in (x0, y0, x1, y1)]
    speed = _motion_number(speed, "speed", 1, 480)
    return math.hypot(x1 - x0, y1 - y0) / speed


def minutes_until(now: float, at: int) -> int:
    """Ceil minutes to the daily next occurrence; zero only at the exact target.

    ``now`` is fractional minutes since midnight, ``at`` is an HH:MM minute.
    Immediately after the target, the next occurrence is tomorrow (up to 1440).
    """
    now = _motion_number(now, "now (minutes since midnight)", 0, 1440)
    at = _world_int(at, "at (minutes since midnight)", 0, 1439)
    return math.ceil((at - now) % 1440)


def board_clock(now: float, offset_minutes: int) -> dict[str, Any]:
    """Injected Unix seconds + fixed UTC-offset minutes, independent of host TZ."""
    now = _motion_number(now, "now (Unix seconds)", 0, 253402214400)
    offset_minutes = _world_int(offset_minutes, "offset_minutes", -840, 840)
    seconds = (now + offset_minutes * 60) % 86400
    whole = math.floor(seconds)
    return {"clock": f"{whole // 3600:02d}:{whole // 60 % 60:02d}", "minutes": seconds / 60}


def board_seconds(chars: int, chars_per_second: float = 8.0) -> float:
    """Seconds for one lap of the scrolling board: constant speed, never quicker than 8 s."""
    return max(8.0, math.floor(chars / chars_per_second * 10 + 0.5) / 10)


# Gauge glyph pairs, ``(elapsed, remaining)``. An hourglass is only one of them; any two short symbols work (``glyphs: ["🔥", "🪵"]``).
GAUGE_GLYPHS: dict[str, tuple[str, str]] = {
    "hourglass": ("⌛", "⏳"), "moon": ("🌕", "🌑"), "heart": ("❤️", "🤍"), "square": ("🟩", "⬜"),
    "dot": ("●", "○"), "block": ("█", "░"), "star": ("⭐", "☆"),
}


def gauge_state(now: int, start: int, end: int, cells: int) -> tuple[int, int, str]:
    """``(filled cells, percent, phase)`` of a window ``start``..``end`` (minutes since midnight; ``end`` before ``start`` runs past midnight)
    at minute ``now``. Integer arithmetic only, so the page agrees exactly. Outside the window the nearer edge decides: ``before`` (empty)
    or ``after`` (full); a tie counts as ``before``."""
    span = (end - start) % 1440 or 1440
    elapsed = (now - start) % 1440
    if elapsed < span:
        return elapsed * cells // span, elapsed * 100 // span, "active"
    return (0, 0, "before") if (start - now) % 1440 <= (now - end) % 1440 else (cells, 100, "after")


def gauge_cells(filled: int, cells: int, glyphs: tuple[str, str] | list[str]) -> str:
    """The gauge as text: ``filled`` elapsed glyphs, then the remaining ones, ``cells`` in all."""
    return glyphs[0] * filled + glyphs[1] * (cells - filled)


def clock_label(minutes: int) -> str:
    """``HH:MM`` for minutes since midnight: the clock and the stamp on a visitor's line."""
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


ZONE_YEARS = (2020, 2040)   # the window a board's zone table covers, [start, end); outside it the nearest end's offset is kept


@functools.lru_cache(maxsize=None)
def zone_rows(tz: str) -> tuple[int, ...]:
    """Flat ``(utc_epoch_seconds, offset_minutes, ...)`` pairs: the offset in force from each instant on, from the start of ``ZONE_YEARS``.
    Built from the system IANA database with ``zoneinfo`` (no hand-written DST rules); the page only looks the table up.
    The scan and the bisection of each change to the second follow flutter_navigation_basic ``python/generate_zone_table.py``."""
    import datetime as dt
    import zoneinfo
    if not isinstance(tz, str) or not re.fullmatch(r"[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+){0,2}", tz):
        raise ValueError(f"not a time zone name: {tz!r}")
    try:
        zone = zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"time zone {tz!r} is unknown or the system has no time zone data (install tzdata)") from error
    utc = dt.timezone.utc
    offset = lambda at: int(at.astimezone(zone).utcoffset().total_seconds() // 60)
    start, end = dt.datetime(ZONE_YEARS[0], 1, 1, tzinfo=utc), dt.datetime(ZONE_YEARS[1], 1, 1, tzinfo=utc)
    now, here = start, offset(start)
    rows = [int(start.timestamp()), here]
    while now < end:
        nxt = min(now + dt.timedelta(hours=6), end)
        there = offset(nxt)
        if there != here and nxt < end:
            low, high = int(now.timestamp()), int(nxt.timestamp())
            while high - low > 1:                                   # the first second the new offset applies
                mid = (low + high) // 2
                low, high = (mid, high) if offset(dt.datetime.fromtimestamp(mid, utc)) == here else (low, mid)
            rows += [high, there]
            here = there
        now = nxt
    return tuple(rows)


def zone_offset(rows: tuple[int, ...] | list[int], utc_seconds: float) -> int:
    """Minutes east of UTC in force at ``utc_seconds`` according to ``zone_rows``; before the first row, the first row's offset."""
    return rows[2 * max(bisect.bisect_right(rows[0::2], utc_seconds) - 1, 0) + 1]


def utc_offset_label(offset_minutes: int) -> str:
    """The time zone the board may show beside its clock: ``UTC``, ``UTC+9``, ``UTC+5:30``, ``UTC-5``. The offset only, never a place name."""
    if offset_minutes == 0:
        return "UTC"
    hours, minutes = divmod(abs(offset_minutes), 60)
    return f"UTC{'+' if offset_minutes > 0 else '-'}{hours}" + (f":{minutes:02d}" if minutes else "")


# The spaces the board collapses (ASCII spaces, NBSP, the Unicode space separators, line/paragraph separators); the page uses the same set.
_MESSAGE_SPACE = frozenset(" \t\n\r\f\v\u00a0\u1680\u2028\u2029\u202f\u205f\u3000") | {chr(c) for c in range(0x2000, 0x200B)}


def clean_message(text: Any, limit: int = 60) -> str | None:
    """What the board shows for a visitor's line: control characters dropped (a zero-width joiner stays, so emoji sequences survive),
    whitespace collapsed, cut to ``limit`` characters;
    ``None`` when nothing is left. The page applies the same rule and puts the result in as text, never as HTML."""
    if not isinstance(text, str):
        return None
    kept = "".join(" " if c in _MESSAGE_SPACE else c for c in text if c in _MESSAGE_SPACE or c == "\u200d" or c.isprintable())
    kept = " ".join(word for word in kept.split(" ") if word)[:limit].rstrip()
    return kept or None


def villager_path(seed: int, width: int, height: int, *, speed: float = 48.0, margin: int = 32, stops: int = 4) -> dict[str, Any]:
    """A seeded loop for one villager: straight walks at constant ``speed`` to random points, a random pause at each (1..4 s),
    then a walk back to the start so the loop is seamless. Returns ``{"duration": seconds, "keys": [(percent, x, y), ...]}``;
    between keys the motion is linear, a pause is two keys at the same point."""
    seed = _world_int(seed, "seed", 0, 2**32 - 1)
    width = _world_int(width, "width", 64, 4096)
    height = _world_int(height, "height", 64, 4096)
    margin = _world_int(margin, "margin", 0, min(width, height) // 2)
    stops = _world_int(stops, "stops", 1, 64)
    speed = _motion_number(speed, "speed", 1, 480)
    rng = random.Random(seed)
    point = lambda: (round(margin + rng.random() * max(0, width - 2 * margin), 1), round(margin + rng.random() * max(0, height - 2 * margin), 1))
    start = point()
    here, clock, steps = start, 0.0, [(0.0, start)]
    for _ in range(stops):
        target = point()
        clock += travel_seconds(*here, *target, speed)
        steps.append((clock, target))
        clock += 1.0 + rng.random() * 3.0
        steps.append((clock, target))
        here = target
    clock += travel_seconds(*here, *start, speed)
    steps.append((clock, start))
    total = max(clock, 1.0)
    return {"duration": total, "keys": [((t / total) * 100, x, y) for t, (x, y) in steps]}


def _world_text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise ValueError(f"{label} must be {1 if required else 0}..{limit} characters")
    return value


def _world_id(value: Any, label: str, seen: set[str]) -> str:
    if not isinstance(value, str) or not _WORLD_TOKEN.fullmatch(value) or value in seen:
        raise ValueError(f"{label} must be a unique lowercase token: {value!r}")
    seen.add(value)
    return value


def _world_emoji(value: Any) -> str:
    """An emoji (or any short non-ASCII symbol string); plain ASCII is refused so text cannot pose as a character."""
    if not isinstance(value, str) or not 1 <= len(value) <= 16 or any(c.isascii() for c in value):
        raise ValueError("emoji must be 1..16 non-ASCII characters")
    return value


def _world_hhmm(value: Any, label: str) -> int:
    """Minutes since midnight for an ``HH:MM`` string."""
    if not (isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value)):
        raise ValueError(f"{label} must be HH:MM")
    return int(value[:2]) * 60 + int(value[3:])


def _gauge_glyph(value: Any) -> str:
    """One gauge cell: 1..8 visible characters (emoji sequences welcome); no spaces or control characters."""
    if not isinstance(value, str) or not 1 <= len(value) <= 8 or any(c.isspace() or not (c.isprintable() or c == "‍") for c in value):
        raise ValueError("a gauge glyph is 1..8 visible characters")
    return value


def _world_gauge(gauge: Any) -> dict[str, Any]:
    """Checked, normalized gauge: ``{"from", "to", "cells", "glyphs": [elapsed, remaining]}``; ``glyphs`` may name a ``GAUGE_GLYPHS`` preset."""
    if not isinstance(gauge, dict) or set(gauge) - {"from", "to", "cells", "glyphs"}:
        raise ValueError("a gauge has from, to, cells and glyphs")
    start, end = _world_hhmm(gauge.get("from"), "from"), _world_hhmm(gauge.get("to"), "to")
    if start == end:
        raise ValueError("a gauge needs a window: from and to differ")
    glyphs = gauge.get("glyphs", "hourglass")
    if isinstance(glyphs, str):
        if glyphs not in GAUGE_GLYPHS:
            raise ValueError(f"unknown glyph set {glyphs!r} (one of {', '.join(GAUGE_GLYPHS)})")
        glyphs = GAUGE_GLYPHS[glyphs]
    elif not isinstance(glyphs, (list, tuple)) or len(glyphs) != 2:
        raise ValueError("glyphs is a preset name or [elapsed, remaining]")
    return {"from": gauge["from"], "to": gauge["to"], "cells": _world_int(gauge.get("cells", 10), "cells", 3, 20),
            "glyphs": [_gauge_glyph(g) for g in glyphs]}


def _world_int(value: Any, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def world_validate(spec: Any) -> dict[str, Any]:
    """Checked copy of a ``web-ui-world/1`` spec: optional ``shots`` (scroll scenes) and ``floors`` (maps with spots)."""
    if not isinstance(spec, dict) or spec.get("schema") != WORLD_SCHEMA:
        raise ValueError(f"expected schema {WORLD_SCHEMA}")
    if set(spec) - {"schema", "id", "title", "shots", "floors", "zoom_max", "board"}:
        raise ValueError("a world has schema, id, title, shots, floors, zoom_max and board")
    world_id = spec.get("id", "world")
    if not isinstance(world_id, str) or not _WORLD_ID.fullmatch(world_id):
        raise ValueError("id must be a lowercase token")
    shots_in, floors_in = spec.get("shots", []), spec.get("floors", [])
    if not isinstance(shots_in, list) or not isinstance(floors_in, list) or not (shots_in or floors_in):
        raise ValueError("a world needs shots or floors")
    if len(shots_in) > 12 or len(floors_in) > 8:
        raise ValueError("at most 12 shots and 8 floors")
    zoom_max = spec.get("zoom_max", 4)
    if type(zoom_max) not in (int, float) or not 1 <= zoom_max <= 8:
        raise ValueError("zoom_max must be from 1 to 8")
    ids: set[str] = set()
    shots = []
    for shot in shots_in:
        if not isinstance(shot, dict) or set(shot) - {"id", "label", "title", "body", "bg"}:
            raise ValueError("a shot has id, label, title, body and an optional bg")
        bg = shot.get("bg")
        if bg is not None and not (isinstance(bg, str) and _WORLD_HEX.fullmatch(bg)):
            raise ValueError("bg must be #rrggbb")
        shots.append({"id": _world_id(shot.get("id"), "shot id", ids), "label": _world_text(shot.get("label"), "label", 40),
                      "title": _world_text(shot.get("title"), "title", 80),
                      "body": _world_text(shot.get("body", ""), "body", 400, required=False), "bg": bg})
    floors, spot_ids = [], set()
    for floor in floors_in:
        if not isinstance(floor, dict) or set(floor) - {"id", "label", "width", "height", "spots", "actors", "player"}:
            raise ValueError("a floor has id, label, width, height, spots, actors and player")
        width, height = _world_int(floor.get("width"), "width", 64, 4096), _world_int(floor.get("height"), "height", 64, 4096)
        spots_in = floor.get("spots")
        if not isinstance(spots_in, list) or not 1 <= len(spots_in) <= 64:
            raise ValueError("a floor lists 1..64 spots")
        spots = []
        for spot in spots_in:
            if not isinstance(spot, dict) or set(spot) - {"id", "x", "y", "label", "category", "body"}:
                raise ValueError("a spot has id, x, y, label, category and body")
            category = spot.get("category", "")
            if category != "" and not (isinstance(category, str) and _WORLD_TOKEN.fullmatch(category)):
                raise ValueError("category must be a lowercase token")
            spots.append({"id": _world_id(spot.get("id"), "spot id", spot_ids), "x": _world_int(spot.get("x"), "x", 0, width),
                          "y": _world_int(spot.get("y"), "y", 0, height), "label": _world_text(spot.get("label"), "label", 40),
                          "category": category, "body": _world_text(spot.get("body", ""), "body", 400, required=False)})
        actors = []
        actors_in = floor.get("actors", [])
        if not isinstance(actors_in, list) or len(actors_in) > 16:
            raise ValueError("a floor lists at most 16 actors")
        for actor in actors_in:
            if not isinstance(actor, dict) or set(actor) - {"id", "emoji", "label", "body", "seed", "speed"}:
                raise ValueError("an actor has id, emoji, label, body, seed and speed")
            seed = actor.get("seed")
            if seed is not None:
                _world_int(seed, "seed", 0, 2**31 - 1)
            speed = actor.get("speed", 48)
            if type(speed) not in (int, float) or not 8 <= speed <= 240:
                raise ValueError("speed must be from 8 to 240 (map units per second)")
            actors.append({"id": _world_id(actor.get("id"), "actor id", spot_ids), "emoji": _world_emoji(actor.get("emoji")),
                           "label": _world_text(actor.get("label"), "label", 40),
                           "body": _world_text(actor.get("body", ""), "body", 400, required=False), "seed": seed, "speed": speed})
        player = floor.get("player")
        if player is not None:
            if not isinstance(player, dict) or set(player) - {"emoji", "x", "y", "speed"}:
                raise ValueError("a player has emoji, x, y and speed")
            speed = player.get("speed", 96)
            if type(speed) not in (int, float) or not 8 <= speed <= 480:
                raise ValueError("speed must be from 8 to 480 (map units per second)")
            player = {"emoji": _world_emoji(player.get("emoji")), "x": _world_int(player.get("x"), "x", 0, width),
                      "y": _world_int(player.get("y"), "y", 0, height), "speed": speed}
        floors.append({"id": _world_id(floor.get("id"), "floor id", ids), "label": _world_text(floor.get("label"), "label", 40),
                       "width": width, "height": height, "spots": spots, "actors": actors, "player": player})
    board = spec.get("board")
    if board is not None:
        if not isinstance(board, dict) or set(board) - {"title", "items", "post", "offset_label", "offset_minutes", "zones", "shared_issue"} or not isinstance(board.get("items"), list) \
                or not 1 <= len(board["items"]) <= 12 or not isinstance(board.get("post", False), bool) \
                or not isinstance(board.get("offset_label", False), bool):
            raise ValueError("a board has a title, 1..12 items, and optional post, offset_label, offset_minutes, zones and shared_issue")
        shared_issue = board.get("shared_issue")
        if shared_issue is not None and (not isinstance(shared_issue, str) or (len(shared_issue.split("/")) == 3 and shared_issue.split("/")[1] in {".", ".."}) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}/[1-9][0-9]{0,8}", shared_issue)):
            raise ValueError("shared_issue must be owner/repository/positive-issue-number")
        zones, seen_zones = [], set()
        zones_in = board.get("zones", [])
        if not isinstance(zones_in, list) or len(zones_in) > 6:
            raise ValueError("zones is a list of up to 6 clocks")
        for entry in zones_in:
            if not isinstance(entry, dict) or set(entry) - {"id", "label", "tz"}:
                raise ValueError("a zone has id, label and tz")
            zone_rows(entry.get("tz"))                                                         # unknown names are refused here
            zones.append({"id": _world_id(entry.get("id"), "zone id", seen_zones), "label": _world_text(entry.get("label"), "label", 24),
                          "tz": entry["tz"]})
        items = []
        for item in board["items"]:
            if not isinstance(item, dict) or set(item) - {"text", "at", "gauge", "zone"}:
                raise ValueError("a board item has text and an optional at or gauge, and an optional zone")
            at, gauge = item.get("at"), item.get("gauge")
            if at is not None and gauge is not None:
                raise ValueError("a board item has either at or gauge, not both")
            if at is not None:
                _world_hhmm(at, "at")
            where = item.get("zone")
            if where is not None and (at is None and gauge is None or where not in seen_zones):
                raise ValueError("an item's zone names one of the board's zones and goes with at or gauge")
            items.append({"text": _world_text(item.get("text"), "text", 120), "at": at,
                          "gauge": None if gauge is None else _world_gauge(gauge), "zone": where})
        board = {"title": _world_text(board.get("title", "INFO"), "title", 24), "items": items, "post": board.get("post", False),
                 "offset_label": board.get("offset_label", False), "zones": zones, "shared_issue": shared_issue,
                 "offset_minutes": (_world_int(board["offset_minutes"], "offset_minutes", -840, 840)
                                    if board.get("offset_minutes") is not None else None)}
    return {"schema": WORLD_SCHEMA, "id": world_id, "title": _world_text(spec.get("title", "World"), "title", 80),
            "shots": shots, "floors": floors, "zoom_max": zoom_max, "board": board}


def _shots_html(world: dict[str, Any]) -> str:
    wid, shots = world["id"], world["shots"]
    articles = "".join(
        f'<article class="ui-shot" data-i="{i}"><p class="ui-shot-hud">{escape(s["label"])} / {len(shots):02d}</p>'
        f'<h3>{escape(s["title"])}</h3><p>{escape(s["body"])}</p></article>' for i, s in enumerate(shots))
    marks = "".join(f'<div class="ui-shot-mark" data-i="{i}" style="--i:{i}"></div>' for i in range(len(shots)))
    return (f'<section class="ui-world ui-world-shots" id="{wid}-shots" data-ui-world="shots" style="--shots:{len(shots)}" '
            f'aria-label="{escape(world["title"], quote=True)}"><div class="ui-shots-scroll"><div class="ui-shots-track">'
            f'<div class="ui-shots-stage">{articles}</div>{marks}</div></div></section>')


def _board_html(board: dict[str, Any] | None) -> str:
    """The info board: a clock and a constant-speed scrolling line; items with ``at`` get "in N min" from the page's clock."""
    if not board:
        return ""
    def item(entry: dict[str, Any], hidden: bool) -> str:
        extra, where = "", f' data-zone="{entry["zone"]}"' if entry["zone"] else ""
        if entry["at"]:
            extra = f' <span class="ui-board-min" data-at="{entry["at"]}"{where}></span>'
        elif entry["gauge"]:
            g = entry["gauge"]
            done, todo = (escape(glyph, quote=True) for glyph in g["glyphs"])
            extra = (f' <span class="ui-board-gauge" data-from="{g["from"]}" data-to="{g["to"]}" data-cells="{g["cells"]}"{where} '
                     f'data-done="{done}" data-todo="{todo}"><span class="ui-board-cells" aria-hidden="true">'
                     f'{escape(gauge_cells(0, g["cells"], g["glyphs"]))}</span> <span class="ui-board-pct">0%</span></span>')
        aria_hidden = ' aria-hidden="true"' if hidden else ""
        return f'<span class="ui-board-item"{aria_hidden}>{escape(entry["text"])}{extra}</span>'
    chars = sum(len(e["text"]) + (10 if e["at"] else 0) + (2 * e["gauge"]["cells"] + 5 if e["gauge"] else 0) for e in board["items"])
    run = "".join(item(e, False) for e in board["items"]) + "".join(item(e, True) for e in board["items"])
    form = ('<form class="ui-board-post"><input class="ui-input" name="message" maxlength="60" placeholder="Leave a line" '
            'aria-label="Leave a line on the board" autocomplete="off"><button class="ui-button" type="submit">Post</button></form>'
            if board["post"] else "")
    shared = ""
    if board.get("shared_issue"):
        owner, repo, number = board["shared_issue"].split("/")
        issue_url = f"https://github.com/{owner}/{repo}/issues/{number}"
        api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments?per_page=100"
        shared = (f'<details class="ui-board-shared" data-api="{escape(api_url, quote=True)}">'
                  '<summary>共有掲示板（GitHub公開コメント）</summary>'
                  '<p>投稿はGitHubへのログインが必要です。本文・アカウント名・投稿時刻はインターネットに公開されます。'
                  '個人情報や秘密の待ち合わせ情報は書かないでください。ページ内Postはこのページだけで、共有されません。</p>'
                  f'<a href="{escape(issue_url, quote=True)}#new_comment_field" target="_blank" rel="noopener noreferrer">GitHubで公開投稿（別タブ）</a> '
                  '<button type="button" data-shared-refresh>共有コメントを取得・更新</button>'
                  '<p role="status" data-shared-status>未取得。自動更新なし。更新間隔は最低120秒。</p>'
                  '<ul data-shared-comments></ul></details>')
    label = " data-offset-label" if board["offset_label"] else ""
    chips = "".join(f'<span class="ui-board-zone" data-zone-id="{z["id"]}" data-rows="{json.dumps(list(zone_rows(z["tz"])), separators=(",", ":"))}">'
                    f'{escape(z["label"])} <b data-zone-clock>--:--</b></span>' for z in board["zones"])
    chips = f'<span class="ui-board-zones">{chips}</span>' if chips else ""
    offset = board["offset_minutes"] if board["offset_minutes"] is not None else ""
    return (f'<div class="ui-board" aria-live="off" data-offset="{offset}" data-chars="{chars}"{label}><strong>{escape(board["title"])}</strong><span class="ui-board-clock" data-clock>--:--</span>{chips}'
            f'<div class="ui-board-track"><div class="ui-board-run" style="animation-duration:{board_seconds(chars)}s">{run}</div></div>{form}{shared}</div>')


def _map_html(world: dict[str, Any]) -> str:
    wid, floors = world["id"], world["floors"]
    radios = "".join(
        f'<input class="ui-world-radio" type="radio" name="{wid}-floor" id="{wid}-floor-{f["id"]}" value="{f["id"]}"'
        f'{" checked" if i == 0 else ""}>' for i, f in enumerate(floors))
    categories = sorted({s["category"] for f in floors for s in f["spots"] if s["category"]})
    cat_ids = [""] + categories
    radios += "".join(
        f'<input class="ui-world-radio" type="radio" name="{wid}-cat" id="{wid}-cat-{"value-" + c if c else "all"}" value="{c}"'
        f'{" checked" if not c else ""}>' for c in cat_ids)
    labels = "".join(f'<label for="{wid}-floor-{f["id"]}">{escape(f["label"])}</label>' for f in floors)
    if categories:
        labels += "".join(f'<label for="{wid}-cat-{"value-" + c if c else "all"}" data-cat="{c}">{escape(c or "all")}</label>' for c in cat_ids)
    stages, sheet = [], []
    for f in floors:
        spots = "".join(
            f'<a class="ui-spot" href="#{wid}-spot-{s["id"]}" data-x="{s["x"]}" data-y="{s["y"]}" data-category="{s["category"]}" '
            f'style="left:{s["x"]}px;top:{s["y"]}px">{escape(s["label"])}</a>' for s in f["spots"])
        actors = "".join(
            f'<a class="ui-actor" id="{wid}-actor-{a["id"]}" href="#{wid}-spot-{a["id"]}" aria-label="{escape(a["label"], quote=True)}">'
            f'<span>{escape(a["emoji"])}</span></a>' for a in f["actors"])
        pl = f["player"]
        player = (f'<span class="ui-player" data-x="{pl["x"]}" data-y="{pl["y"]}" data-speed="{pl["speed"]}" '
                  f'style="--px:{pl["x"]};--py:{pl["y"]}" role="img" aria-label="自分"><span>{escape(pl["emoji"])}</span></span>') if pl else ""
        stages.append(f'<div class="ui-floor" data-floor="{f["id"]}" data-w="{f["width"]}" data-h="{f["height"]}" '
                      f'style="width:{f["width"]}px;height:{f["height"]}px">{spots}{actors}{player}</div>')
        sheet.extend(
            f'<article class="ui-sheet-item" id="{wid}-spot-{s["id"]}"><h3>{escape(s["label"])}</h3><p>{escape(s["body"])}</p>'
            f'<a class="ui-sheet-close" href="#{wid}-map">Close</a></article>' for s in [*f["spots"], *f["actors"]])
    return (f'<section class="ui-world ui-world-map" id="{wid}-map" data-ui-world="map" data-zoom-max="{world["zoom_max"]}" '
            f'aria-label="{escape(world["title"], quote=True)}">{radios}<nav class="ui-world-bar">{labels}</nav>'
            f'{_board_html(world["board"])}<div class="ui-world-view" tabindex="0"><div class="ui-world-cam" style="--fx:0;--fy:0;--z:1">{"".join(stages)}</div></div>' +
            ('<div class="ui-world-motion-controls" hidden><button type="button" class="ui-world-pause" aria-pressed="false">動きを停止</button>'
             '<form class="ui-world-walk"><label>X <input name="x" type="number" min="0" step="any" required></label>'
             '<label>Y <input name="y" type="number" min="0" step="any" required></label><button>ここへ歩く</button></form></div>'
             if world["board"] or any(f["player"] or f["actors"] for f in floors) else "") +
            f'<aside class="ui-sheet" aria-live="polite">{"".join(sheet)}</aside></section>')


def world_html(spec: Any) -> str:
    """Semantic HTML for a world; every label and body is escaped. Works without JavaScript (scroll, :target, radios)."""
    world = world_validate(spec)
    return (_shots_html(world) if world["shots"] else "") + (_map_html(world) if world["floors"] else "")


_WORLD_CSS = (
    ".ui-world{--ui-world-h:min(70vh,560px);position:relative;margin:1rem 0;border:1px solid var(--ui-border);background:var(--ui-bg);"
    "color:var(--ui-fg);border-radius:var(--ui-radius);overflow:hidden}"
    ".ui-world-motion-controls{padding:8px}.ui-world-walk{display:flex;gap:8px;flex-wrap:wrap}.ui-world-walk input{width:6em}.ui-world-walk[hidden]{display:none}.ui-world[data-js] .ui-player{transition:none}.ui-world[data-motion-paused] .ui-actor,.ui-world[data-motion-paused] .ui-board-run{animation-play-state:paused!important}"
    ".ui-world-radio{position:absolute;opacity:0;pointer-events:none}"
    ".ui-world-bar{display:flex;flex-wrap:wrap;gap:8px;padding:8px;border-bottom:1px solid var(--ui-border)}"
    ".ui-world-bar label{border:1px solid var(--ui-border);padding:.35rem .75rem;cursor:pointer;background:var(--ui-panel);border-radius:var(--ui-radius)}"
    ".ui-world-view{position:relative;overflow:auto;height:var(--ui-world-h);container-type:size}"
    ".ui-world[data-js] .ui-world-view{overflow:hidden;touch-action:none;cursor:grab}"
    ".ui-world[data-js][data-drag] .ui-world-view{cursor:grabbing}"
    ".ui-world-cam{position:relative;transform-origin:0 0}"
    ".ui-world[data-js] .ui-world-cam{transform:translate(calc(50cqw - var(--fx,0) * var(--z,1) * 1px),calc(50cqh - var(--fy,0) * var(--z,1) * 1px)) "
    "scale(var(--z,1));transition:transform .24s ease-out}"
    ".ui-world[data-js][data-drag] .ui-world-cam{transition:none}"
    ".ui-floor{position:relative;display:none;background-color:var(--ui-panel);background-image:linear-gradient(var(--ui-border) 1px,transparent 1px),"
    "linear-gradient(90deg,var(--ui-border) 1px,transparent 1px);background-size:64px 64px}"
    ".ui-spot{position:absolute;transform:translate(-50%,-50%) scale(calc(1 / var(--z,1)));white-space:nowrap;border:1px solid var(--ui-accent);"
    "background:var(--ui-bg);color:var(--ui-fg);padding:.2rem .6rem;border-radius:999px;text-decoration:none;font-size:.85rem}"
    ".ui-sheet{position:absolute;left:8px;right:8px;bottom:8px;max-height:45%;overflow:auto;border:1px solid var(--ui-border);"
    "background:var(--ui-panel);border-radius:var(--ui-radius);padding:1rem}"
    ".ui-world:not([data-js]) .ui-sheet:not(:has(.ui-sheet-item:target)){display:none}"
    ".ui-world[data-js] .ui-sheet:not(:has(.ui-sheet-item[data-open])){display:none}"
    ".ui-sheet-item{display:none}.ui-world:not([data-js]) .ui-sheet-item:target,.ui-world[data-js] .ui-sheet-item[data-open]{display:block}.ui-sheet h3{margin:0 0 .5rem}"
    ".ui-shot{padding:1.5rem;transition:opacity .4s,transform .4s}"
    ".ui-shot-hud{font-family:var(--ui-font-mono);letter-spacing:.12em;margin:0 0 .5rem;font-size:.8rem}"
    ".ui-world[data-js] .ui-shots-scroll{height:var(--ui-world-h);overflow:auto;position:relative}"
    ".ui-world[data-js] .ui-shots-track{position:relative;height:calc(var(--shots) * var(--ui-world-h))}"
    ".ui-world[data-js] .ui-shots-stage{position:sticky;top:0;height:var(--ui-world-h);overflow:hidden;background:var(--ui-bg);transition:background .6s}"
    ".ui-world[data-js] .ui-shot{position:absolute;inset:0;opacity:0;transform:translateY(16px)}"
    ".ui-shot-mark{position:absolute;left:0;top:calc(var(--i) * var(--ui-world-h));width:1px;height:var(--ui-world-h);pointer-events:none}"
    ".ui-actor{position:absolute;left:0;top:0;text-decoration:none;color:inherit}"
    ".ui-actor span,.ui-player span{display:block;transform:translate(-50%,-50%) scale(calc(1 / var(--z,1)));font-size:1.5rem;line-height:1}"
    ".ui-player{position:absolute;left:0;top:0;pointer-events:none;transform:translate(calc(var(--px,0) * 1px),calc(var(--py,0) * 1px));"
    "transition:transform var(--walk,0s) linear}"
    ".ui-board{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:4px 8px;border-bottom:1px solid var(--ui-border);background:var(--ui-panel);"
    "font-family:var(--ui-font-mono);font-size:.85rem;overflow:hidden}"
    ".ui-board:has(.ui-board-shared){flex-wrap:wrap}.ui-board-shared{flex-basis:100%;white-space:normal;font-family:var(--ui-font);overflow-wrap:anywhere}.ui-board-shared ul{max-height:14rem;overflow:auto}"
    ".ui-board-clock{flex:none;white-space:nowrap;border:1px solid var(--ui-accent);padding:0 .5rem;border-radius:var(--ui-radius)}"
    ".ui-board-track{flex:4 1 14rem;min-width:0;overflow:hidden;white-space:nowrap}"
    ".ui-board-run{display:inline-flex;animation:ui-board-scroll 24s linear infinite}"
    ".ui-board-item{padding-right:3rem}"
    ".ui-board-zones{display:flex;flex-wrap:wrap;gap:0 12px}"
    ".ui-board-zone{flex:none;white-space:nowrap;color:var(--ui-muted)}.ui-board-zone b{color:var(--ui-fg);font-weight:400;font-variant-numeric:tabular-nums}"
    ".ui-board-stamp{margin-right:.25rem;color:var(--ui-muted);font-variant-numeric:tabular-nums}"
    ".ui-board-gauge{white-space:nowrap}.ui-board-cells{letter-spacing:.05em}.ui-board-pct{font-variant-numeric:tabular-nums}"
    ".ui-board-post{display:flex;gap:4px;flex:1 1 13rem}.ui-board-post .ui-input{flex:1;min-width:0;width:auto;padding:.2rem .5rem}.ui-board-post .ui-button{padding:.2rem .6rem}"
    "@keyframes ui-board-scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}"
    "@media(prefers-reduced-motion:reduce){.ui-world *{transition:none!important}.ui-actor,.ui-board-run{animation-play-state:paused!important}}"
)

_WALL_CSS = (
    ".ui-wall{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}"
    ".ui-wall-cell{border:1px solid var(--ui-border);padding:16px;border-radius:var(--ui-radius);background:var(--ui-bg);color:var(--ui-fg)}"
    ".ui-wall-cell h3{margin:0 0 8px}"
)


def world_css(spec: Any) -> str:
    """CSS for a world: fixed rules plus one rule per floor, category and shot (radios and data-lit drive them through :has)."""
    world = world_validate(spec)
    wid, rules = world["id"], [_WORLD_CSS]
    for f in world["floors"]:
        radio = f"#{wid}-floor-{f['id']}"
        rules.append(f'.ui-world:has({radio}:checked) .ui-floor[data-floor="{f["id"]}"]{{display:block}}')
        rules.append(f'.ui-world:has({radio}:checked) label[for="{wid}-floor-{f["id"]}"]{{background:var(--ui-accent);color:var(--ui-bg)}}')
    categories = sorted({s["category"] for f in world["floors"] for s in f["spots"] if s["category"]})
    for f in world["floors"]:
        for a in f["actors"]:
            path = villager_path(a["seed"] if a["seed"] is not None else zlib.crc32(f"{wid}:{a['id']}".encode()),
                                 f["width"], f["height"], speed=a["speed"])
            name = f"ui-walk-{wid}-{a['id']}"
            frames = "".join(f"{pct}%{{transform:translate({x}px,{y}px)}}" for pct, x, y in path["keys"])
            rules.append(f"@keyframes {name}{{{frames}}}#{wid}-actor-{a['id']}{{animation:{name} {path['duration']}s linear infinite}}")
    for c in categories:
        radio = f"#{wid}-cat-value-{c}"
        rules.append(f'.ui-world:has({radio}:checked) .ui-spot:not([data-category="{c}"]){{display:none}}')
    for c in [""] + categories if categories else []:
        rules.append(f'.ui-world:has(#{wid}-cat-{"value-" + c if c else "all"}:checked) label[for="{wid}-cat-{"value-" + c if c else "all"}"]'
                     f'{{background:var(--ui-accent);color:var(--ui-bg)}}')
    if world["shots"]:
        rules.append('.ui-world-shots[data-js]:not(:has(.ui-shot-mark[data-lit])) .ui-shot[data-i="0"]{opacity:1;transform:none}')
    for i, s in enumerate(world["shots"]):
        lit = f'#{wid}-shots:has(.ui-shot-mark[data-i="{i}"][data-lit])'
        rules.append(f'{lit} .ui-shot[data-i="{i}"]{{opacity:1;transform:none}}')
        if s["bg"]:
            rules.append(f'{lit} .ui-shots-stage{{background:{s["bg"]};color:{ink_for(s["bg"])}}}')
    return "@layer components{" + "".join(rules) + "}"


# Browser arithmetic is a projection of the Python oracle, not Python execution.
WORLD_MOTION_JS = r"""
export function motionSample(s,t){const f=s.duration===0?(t>=s.at?1:0):Math.min(1,Math.max(0,(t-s.at)/s.duration));return s.from.map((v,i)=>v+(s.to[i]-v)*f)}
export function motionWalk(a,b,t,speed,w,h){const point=p=>p.map((v,i)=>Math.min(i?h:w,Math.max(0,v)));a=point(a);b=point(b);return{at:t,duration:Math.hypot(b[0]-a[0],b[1]-a[1])/speed,from:a,to:b}}
function bindPlayer(el,floor){
 const controls=el.querySelector('.ui-world-motion-controls');if(!controls)return ()=>{};
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),states=new Map(),button=controls.querySelector('.ui-world-pause'),form=controls.querySelector('form');
 let paused=false,base=performance.now(),elapsed=0;
 const time=()=>Math.min(1e9,elapsed+(paused||reduced.matches?0:(performance.now()-base)/1000));
 const freeze=()=>{elapsed=time();base=performance.now()};
 for(const f of el.querySelectorAll('.ui-floor')){const player=f.querySelector('.ui-player');if(!player)continue;const w=+f.dataset.w,h=+f.dataset.h,speed=+player.dataset.speed,point=[+player.dataset.x,+player.dataset.y];states.set(f,{w,h,speed,player,own:motionWalk(point,point,0,speed,w,h)});}
 const place=(s,t)=>{const p=motionSample(s.own,t);s.player.style.setProperty('--px',p[0]);s.player.style.setProperty('--py',p[1]);};
 const walk=(x,y)=>{const s=states.get(floor());if(!s||![x,y].every(Number.isFinite))return;const t=time(),a=motionSample(s.own,t);s.own=motionWalk(a,[x,y],t,s.speed,s.w,s.h);if(reduced.matches)s.own=motionWalk(s.own.to,s.own.to,t,s.speed,s.w,s.h);s.player.style.setProperty('--walk',s.own.duration+'s');s.player.dataset.targetX=s.own.to[0];s.player.dataset.targetY=s.own.to[1];place(s,t);};
 button.addEventListener('click',()=>{freeze();paused=!paused;el.toggleAttribute('data-motion-paused',paused);button.setAttribute('aria-pressed',String(paused));button.textContent=paused?'動きを再開':'動きを停止';});
 let wasReduced=reduced.matches;
 reduced.addEventListener('change',()=>{if(!wasReduced&&!paused)elapsed=Math.min(1e9,elapsed+(performance.now()-base)/1000);base=performance.now();wasReduced=reduced.matches;for(const s of states.values())place(s,time());});
 form.addEventListener('submit',e=>{e.preventDefault();if(form.reportValidity())walk(+form.elements.x.value,+form.elements.y.value)});
 const tick=()=>{if(!el.isConnected)return;controls.hidden=false;const active=states.get(floor()),t=time();form.hidden=!active;
  if(active){form.elements.x.max=active.w;form.elements.y.max=active.h;place(active,t);}
  requestAnimationFrame(tick);
 };requestAnimationFrame(tick);return walk;
}
"""


WORLD_SHARED_JS = r"""
// GET only. No credentials, storage, Markdown rendering, or automatic polling.
export function sharedLines(comments){
 if(!Array.isArray(comments))throw new Error("Invalid comments response");
 return comments.slice(0,100).filter(c=>c&&typeof c.body==="string"&&typeof c.user?.login==="string")
 .slice(-5).reverse().map(c=>({text:cleanMessage(c.body),author:c.user.login.slice(0,100),
 time:typeof c.created_at==="string"?c.created_at.slice(0,30):""})).filter(line=>line.text);
}
export function sharedWait(response,now){
 const retry=response.headers.get("retry-after"),reset=response.headers.get("x-ratelimit-reset");
 return Math.max(now+120000, retry&&Number.isFinite(Number(retry))?now+Number(retry)*1000:0,
 response.headers.get("x-ratelimit-remaining")==="0"&&Number.isFinite(Number(reset))?Number(reset)*1000:0);
}
export function bindSharedBoard(board){
 const panel=board.querySelector(".ui-board-shared");if(!panel)return;
 const button=panel.querySelector("[data-shared-refresh]"),status=panel.querySelector("[data-shared-status]"),list=panel.querySelector("[data-shared-comments]");
 let next=0,busy=false;
 button.addEventListener("click",async()=>{
  if(busy)return;
  if(Date.now()<next){status.textContent="更新待機中。"+Math.ceil((next-Date.now())/1000)+"秒後に再試行できます。";return}
  busy=true;button.disabled=true;next=Date.now()+120000;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
  try{
   const response=await fetch(panel.dataset.api,{method:"GET",cache:"no-store",credentials:"omit",referrerPolicy:"no-referrer",headers:{Accept:"application/vnd.github+json"},signal:controller.signal});
   next=sharedWait(response,Date.now());
   if(!response.ok)throw new Error("HTTP "+response.status);
   const lines=sharedLines(await response.json());if(!panel.isConnected)return;
   const nodes=lines.map(line=>{const li=document.createElement("li");li.textContent=line.author+" · "+line.time+" — "+line.text;return li});
   list.replaceChildren(...nodes);
   status.textContent="取得済み（"+new Date().toLocaleTimeString()+"）。先頭100コメント内の末尾最大5件、本文60文字。"+(response.headers.get("link")?.includes('rel="next"')?"続きはGitHubで確認してください。":"");
  }catch(error){if(panel.isConnected)status.textContent="取得できませんでした（通信・API制限・公開設定を確認）。前回の表示を保持します。"}
  finally{clearTimeout(timeout);busy=false;button.disabled=false}
 });
}
"""

WORLD_JS = WORLD_MOTION_JS + WORLD_SHARED_JS + r"""/* web-ui world: one page, a camera. Shots: scroll marks light up (data-lit). Map: drag, wheel and pinch move a camera; spots open a sheet. No page changes. */
const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));
export function fitZoom(w,h,vw,vh){return Math.min(vw/w,vh/h)}
export function travelSeconds(x0,y0,x1,y1,speed){return Math.hypot(x1-x0,y1-y0)/speed}
export function minutesUntil(now,at){return Math.ceil(((at-now)%1440+1440)%1440)}
export function boardClock(now,offset){const seconds=((now+offset*60)%86400+86400)%86400,whole=Math.floor(seconds);return{clock:[Math.floor(whole/3600),Math.floor(whole/60)%60].map(v=>String(v).padStart(2,"0")).join(":"),minutes:seconds/60}}
export function boardSeconds(chars,cps=8){return Math.max(8,Math.round(chars/cps*10)/10)}
export function gaugeState(now,start,end,cells){const m=n=>((n%1440)+1440)%1440,span=m(end-start)||1440,el=m(now-start);if(el<span)return[Math.floor(el*cells/span),Math.floor(el*100/span),"active"];return m(start-now)<=m(now-end)?[0,0,"before"]:[cells,100,"after"]}
export function gaugeCells(filled,cells,done,todo){return done.repeat(filled)+todo.repeat(cells-filled)}
export function clockLabel(minutes){const h=Math.floor(minutes/60)%24,m=minutes%60;return String(h).padStart(2,"0")+":"+String(m).padStart(2,"0")}
export function zoneOffset(rows,t){let lo=0,hi=rows.length/2-1;while(lo<hi){const mid=(lo+hi+1)>>1;if(rows[2*mid]<=t)lo=mid;else hi=mid-1}return rows[2*lo+1]}
export function utcOffsetLabel(offset){if(offset===0)return"UTC";const a=Math.abs(offset),h=Math.floor(a/60),m=a%60;return"UTC"+(offset>0?"+":"-")+h+(m?":"+String(m).padStart(2,"0"):"")}
export function cleanMessage(text,limit=60){if(typeof text!=="string")return null;const kept=[...text].map(c=>/[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/.test(c)?" ":(c!=="\u200d"&&/[\p{Cc}\p{Cf}\p{Cn}\p{Co}\p{Cs}\p{Zs}\p{Zl}\p{Zp}]/u.test(c)?"":c)).join("").split(" ").filter(Boolean).join(" ");const cut=[...kept].slice(0,limit).join("").trimEnd();return cut||null}
export function clampFocus(fx,fy,z,w,h,vw,vh){const hw=vw/(2*z),hh=vh/(2*z);return[w>2*hw?clamp(fx,hw,w-hw):w/2,h>2*hh?clamp(fy,hh,h-hh):h/2]}
function bindShots(el){el.dataset.js="";const marks=[...el.querySelectorAll(".ui-shot-mark")];if(typeof IntersectionObserver==="undefined"){marks[0].dataset.lit="";return el}const io=new IntersectionObserver(es=>{for(const e of es){if(e.isIntersecting)e.target.dataset.lit="";else delete e.target.dataset.lit}},{root:el.querySelector(".ui-shots-scroll"),threshold:0.5});for(const m of marks)io.observe(m);return el}
function bindMap(el){el.dataset.js="";const view=el.querySelector(".ui-world-view"),cam=el.querySelector(".ui-world-cam"),zmax=Number(el.dataset.zoomMax||4),pts=new Map();let fx=0,fy=0,z=1,moved=0;
const floor=()=>{const r=el.querySelector('input[name$="-floor"]:checked');return(r&&el.querySelector(`.ui-floor[data-floor="${r.value}"]`))||el.querySelector(".ui-floor")};
const size=()=>{const f=floor();return[Number(f.dataset.w),Number(f.dataset.h),view.clientWidth,view.clientHeight]};
const apply=()=>{const[w,h,vw,vh]=size();if(!vw||!vh)return;z=clamp(z,fitZoom(w,h,vw,vh),zmax);[fx,fy]=clampFocus(fx,fy,z,w,h,vw,vh);cam.style.setProperty("--fx",fx);cam.style.setProperty("--fy",fy);cam.style.setProperty("--z",z)};
const go=(x,y,zoom)=>{fx=x;fy=y;z=zoom;apply()};
const home=()=>{const[w,h,vw,vh]=size();go(w/2,h/2,vw&&vh?fitZoom(w,h,vw,vh):1)};
const open=id=>{for(const i of el.querySelectorAll(".ui-sheet-item"))i.toggleAttribute("data-open",i.id===id)};
const walk=bindPlayer(el,floor);
const board=el.querySelector(".ui-board"),hm=t=>{const[h,m]=t.split(":").map(Number);return h*60+m},clockNow=()=>{const d=new Date(),off=board.dataset.offset===""?(-Math.round(d.getTimezoneOffset())||0):Number(board.dataset.offset);return{...boardClock(d.getTime()/1000,off),off}},chips=board?[...board.querySelectorAll("[data-zone-id]")].map(z=>({id:z.dataset.zoneId,rows:JSON.parse(z.dataset.rows),out:z.querySelector("[data-zone-clock]")})):[],tick=()=>{const clock=clockNow(),t=new Date().getTime()/1000,zones=new Map(chips.map(z=>{const c=boardClock(t,zoneOffset(z.rows,t));z.out.textContent=c.clock;return[z.id,c]})),at=m=>(m.dataset.zone?zones.get(m.dataset.zone):clock).minutes,c=board.querySelector("[data-clock]");c.textContent=clock.clock+(board.dataset.offsetLabel!==undefined?" "+utcOffsetLabel(clock.off):"");for(const m of board.querySelectorAll("[data-at]")){const left=minutesUntil(at(m),hm(m.dataset.at));m.textContent=left===0?"いま":"あと"+left+"分"}for(const g of board.querySelectorAll(".ui-board-gauge")){const cells=Number(g.dataset.cells),[filled,pct]=gaugeState(Math.floor(at(g)),hm(g.dataset.from),hm(g.dataset.to),cells);g.querySelector(".ui-board-cells").textContent=gaugeCells(filled,cells,g.dataset.done,g.dataset.todo);g.querySelector(".ui-board-pct").textContent=pct+"%"}};
if(board){bindSharedBoard(board);tick();const timer=setInterval(()=>{if(el.isConnected)tick();else clearInterval(timer)},1000);const form=board.querySelector(".ui-board-post");if(form){
const run=board.querySelector(".ui-board-run"),items=[...run.querySelectorAll(".ui-board-item")],base=items.slice(0,items.length/2).map(n=>n.cloneNode(true)),baseChars=Number(board.dataset.chars),notes=[];
form.addEventListener("submit",e=>{e.preventDefault();const input=form.elements.message,text=cleanMessage(input.value);if(!text)return;input.value="";notes.unshift({text,at:clockNow().clock});notes.splice(5);run.replaceChildren();
for(const hidden of [false,true]){for(const note of notes){const span=document.createElement("span");span.className="ui-board-item ui-board-note";if(hidden)span.setAttribute("aria-hidden","true");const stamp=document.createElement("span");stamp.className="ui-board-stamp";stamp.textContent=note.at;span.append(stamp,document.createTextNode(" "+note.text));run.append(span)}for(const item of base){const copy=item.cloneNode(true);if(hidden)copy.setAttribute("aria-hidden","true");run.append(copy)}}
const chars=baseChars+notes.reduce((n,note)=>n+[...note.text].length,0);board.dataset.chars=chars;run.style.animationDuration=boardSeconds(chars)+"s";tick()})}}

const close=()=>{open(null);if([...el.querySelectorAll(".ui-sheet-item")].some(i=>"#"+i.id===location.hash))history.replaceState(null,"",location.pathname+location.search)};
const focusSpot=a=>{const all=el.querySelector('input[name$="-cat"][value=""]');if(all)all.checked=true;const f=a.closest(".ui-floor"),r=el.querySelector(`input[name$="-floor"][value="${f.dataset.floor}"]`);if(r)r.checked=true;go(Number(a.dataset.x),Number(a.dataset.y),Math.max(z,2))};
view.addEventListener("pointerdown",e=>{if(e.button!==0)return;pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===1)moved=0;else moved=9;el.dataset.drag=""});
view.addEventListener("pointermove",e=>{const p=pts.get(e.pointerId);if(!p)return;if(pts.size===1){const dx=e.clientX-p[0],dy=e.clientY-p[1];moved+=Math.abs(dx)+Math.abs(dy);if(moved>8&&!view.hasPointerCapture(e.pointerId))view.setPointerCapture(e.pointerId);fx-=dx/z;fy-=dy/z;apply()}else if(pts.size===2){const q=[...pts].find(([id])=>id!==e.pointerId)[1],d0=Math.hypot(p[0]-q[0],p[1]-q[1]),d1=Math.hypot(e.clientX-q[0],e.clientY-q[1]);moved+=9;if(d0)z*=d1/d0;apply()}p[0]=e.clientX;p[1]=e.clientY});
const end=e=>{const tapping=pts.has(e.pointerId)&&pts.size===1&&moved<=8&&e.type==="pointerup"&&view.contains(e.target)&&!e.target.closest("a,button,input");pts.delete(e.pointerId);if(!pts.size)delete el.dataset.drag;if(tapping&&walk){const f=floor(),r=f.getBoundingClientRect();walk((e.clientX-r.left)*Number(f.dataset.w)/r.width,(e.clientY-r.top)*Number(f.dataset.h)/r.height)}};
addEventListener("pointerup",end);addEventListener("pointercancel",end);view.addEventListener("lostpointercapture",end);
view.addEventListener("wheel",e=>{e.preventDefault();z*=e.deltaY<0?1.1:1/1.1;apply()},{passive:false});
el.addEventListener("click",e=>{const a=e.target.closest(".ui-spot,.ui-actor");if(a){e.preventDefault();if(e.detail!==0&&moved>8){moved=0;return}const id=a.getAttribute("href").slice(1);open(id);history.replaceState(null,"","#"+id);if(a.dataset.x!==undefined){focusSpot(a);walk(Number(a.dataset.x),Number(a.dataset.y))}}else if(e.target.closest(".ui-sheet-close")){e.preventDefault();close()}});
el.addEventListener("keydown",e=>{if(e.key==="Escape")close()});
el.addEventListener("change",e=>{if(e.target.name&&e.target.name.endsWith("-floor"))home()});
if(typeof ResizeObserver!=="undefined")new ResizeObserver(apply).observe(view);
const fromHash=()=>{const hash=location.hash.slice(1),a=hash&&el.querySelector(`.ui-spot[href="#${CSS.escape(hash)}"],.ui-actor[href="#${CSS.escape(hash)}"]`);if(a){open(hash);if(a.dataset.x!==undefined)focusSpot(a)}else open(null)};
addEventListener("hashchange",fromHash);home();fromHash();
return el}
export function bindWorlds(root=document){return[...root.querySelectorAll("[data-ui-world]")].map(el=>el.hasAttribute("data-js")?el:el.dataset.uiWorld==="shots"?bindShots(el):bindMap(el))}
globalThis.webUiWorld={fitZoom,clampFocus,travelSeconds,minutesUntil,boardClock,boardSeconds,gaugeState,gaugeCells,clockLabel,utcOffsetLabel,zoneOffset,cleanMessage,motionWalk,motionSample,bindWorlds};
bindWorlds();
"""


def world_document(spec: Any, *, theme: str = "modern") -> str:
    """A single-file page: bundled CSS, the world's CSS, the world's HTML and one inline module."""
    world = world_validate(spec)
    return render_document(trusted_html=world_html(world), title=world["title"], theme=theme,
                           css=bundled_css() + world_css(world), embedded_modules=("world.js",))


def catalogue_world(items: Any, *, id: str = "catalogue", title: str = "Catalogue", columns: int = 8,
                    cell: tuple[int, int] = (160, 64), margin: int = 64) -> dict[str, Any]:
    """A ``web-ui-world/1`` map from a flat catalogue, one floor per ``group`` (more than 64 in a group continue on another floor).

    Each item is ``{"id", "label", "group"}`` plus optional ``"emoji"``, ``"category"`` (a filter chip) and ``"body"`` (the info sheet).
    The page never changes: tap a spot, read its sheet. Spots sit on a grid whose sizes default to multiples of 8. For a list of screens like
    flutter_navigation_basic's ``screens.json`` map the fields first, e.g. ``{"id": s["name"], "label": s["title"], "emoji": s["emoji"],
    "group": s["category"], "category": s["domainKey"], "body": s["description"]}``; the data itself stays with its owner."""
    if not isinstance(items, list) or not 1 <= len(items) <= 512:
        raise ValueError("a catalogue lists 1..512 items")
    if any(type(v) is not int or v <= 0 for v in (columns, margin, *cell)):
        raise ValueError("columns, cell and margin are positive integers")
    slug = lambda text: re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:28] or "x"
    groups: dict[str, list[dict[str, Any]]] = {}
    taken: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"id", "label", "group", "emoji", "category", "body"}:
            raise ValueError("an item has id, label, group, emoji, category and body")
        base = slug(item.get("id"))
        unique, n = base, 2
        while unique in taken:                                   # the same slug twice: Screen1 and screen-1 become screen1 and screen1-2
            unique, n = f"{base}-{n}", n + 1
        taken.add(unique)
        label = (f"{item.get('emoji')} " if item.get("emoji") else "") + _world_text(item.get("label"), "label", 80)
        category = slug(item["category"]) if item.get("category") not in (None, "") else ""
        groups.setdefault(_world_text(item.get("group"), "group", 80), []).append(
            {"id": unique, "label": label if len(label) <= 40 else label[:39] + "…", "category": category, "body": item.get("body", "")})
    floors = []
    for group, spots in groups.items():
        for part, start in enumerate(range(0, len(spots), 64)):
            chunk = spots[start:start + 64]
            rows = -(-len(chunk) // columns)
            floors.append({"id": f"f{len(floors) + 1}", "label": (group if part == 0 else f"{group} {part + 1}")[:40],
                           "width": 2 * margin + min(columns, len(chunk)) * cell[0], "height": 2 * margin + rows * cell[1],
                           "spots": [{"id": spot["id"], "label": spot["label"], "category": spot["category"], "body": spot["body"],
                                      "x": margin + (i % columns) * cell[0] + cell[0] // 2, "y": margin + (i // columns) * cell[1] + cell[1] // 2}
                                     for i, spot in enumerate(chunk)]})
    if len(floors) > 8:
        raise ValueError("a world has at most 8 floors: fewer groups, or fewer than 64 items in each")
    spec = {"schema": WORLD_SCHEMA, "id": id, "title": title, "floors": floors}
    return world_validate(spec)


# --- App shell showcase: a header, a rail (wide) or bottom bar (narrow), sections that switch with no reload and no script ------------
# Absorbs flutter_navigation_basic's UI Showcase layout (the HTML comparison experiment) as a theme-aware, data-driven component.

SHOWCASE_SCHEMA = "web-ui-showcase/1"
SHOWCASE_ICONS: dict[str, str] = {
    "star": "m12 3 2.8 6 6.5.8-4.8 4.5 1.3 6.5-5.8-3.3-5.8 3.3 1.3-6.5L2.7 9.8 9.2 9Z",
    "overview": "M3 3h7v9H3ZM14 3h7v5h-7ZM3 16h7v5H3ZM14 12h7v9h-7Z",
    "components": "M3 3h6v6H3ZM3 15h6v6H3ZM15 15h6v6h-6ZM17 2l5 5-5 5-5-5Z",
    "data": "M3 4h18v16H3ZM3 9h18M9 9v11M15 9v11",
    "media": "M3 4h18v16H3Zm2 13 5-6 4 4 2-2 3 4",
    "responsive": "M3 5h18v14H3ZM16 5v14M16 12h5",
    "tune": "M3 6h10m4 0h4M3 12h4m4 0h10M3 18h12m4 0h2M13 3v6M7 9v6M15 15v6",
    "layers": "m12 3 9 7-9 7-9-7Zm-9 12 9 7 9-7",
    "home": "m3 10 9-7 9 7M6 9v11h4v-7h4v7h4V9",
    "info": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 11v6M12 7.5v.5",
}


def showcase_validate(spec: Any) -> dict[str, Any]:
    """Checked copy of a ``web-ui-showcase/1`` spec: ``title``, optional ``emoji``, ``favorite`` and ``themes`` flags, and 2..6 sections, each with
    ``id``, ``label``, ``icon`` (a ``SHOWCASE_ICONS`` name), ``heading`` and any of ``lead``, ``tags``, ``cards``, ``table``, ``controls``."""
    if not isinstance(spec, dict) or spec.get("schema") != SHOWCASE_SCHEMA:
        raise ValueError(f"expected schema {SHOWCASE_SCHEMA}")
    if set(spec) - {"schema", "id", "title", "emoji", "favorite", "themes", "sections"}:
        raise ValueError("a showcase has schema, id, title, emoji, favorite, themes and sections")
    sid = spec.get("id", "showcase")
    if not isinstance(sid, str) or not _WORLD_ID.fullmatch(sid):
        raise ValueError("id must be a lowercase token")
    flags = {key: spec.get(key, False) for key in ("favorite", "themes")}
    if any(not isinstance(v, bool) for v in flags.values()):
        raise ValueError("favorite and themes are true or false")
    sections_in = spec.get("sections")
    if not isinstance(sections_in, list) or not 2 <= len(sections_in) <= 6:
        raise ValueError("a showcase has 2..6 sections")
    seen: set[str] = set()
    sections = []
    for sec in sections_in:
        if not isinstance(sec, dict) or set(sec) - {"id", "label", "icon", "heading", "lead", "tags", "cards", "table", "controls"}:
            raise ValueError("a section has id, label, icon, heading, lead, tags, cards, table and controls")
        icon = sec.get("icon", "info")
        if icon not in SHOWCASE_ICONS:
            raise ValueError(f"unknown icon {icon!r} (one of {', '.join(SHOWCASE_ICONS)})")
        tags = sec.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 8:
            raise ValueError("tags is a list of up to 8 strings")
        cards = sec.get("cards", [])
        if not isinstance(cards, list) or len(cards) > 8:
            raise ValueError("cards is a list of up to 8")
        table = sec.get("table")
        if table is not None:
            if not isinstance(table, dict) or set(table) - {"columns", "rows"} or not isinstance(table.get("columns"), list) \
                    or not 1 <= len(table["columns"]) <= 6 or not isinstance(table.get("rows"), list) or len(table["rows"]) > 16 \
                    or any(not isinstance(r, list) or len(r) != len(table["columns"]) for r in table["rows"]):
                raise ValueError("a table has 1..6 columns and up to 16 rows of the same width")
            table = {"columns": [_world_text(c, "column", 40) for c in table["columns"]],
                     "rows": [[_world_text(c, "cell", 80, required=False) for c in r] for r in table["rows"]]}
        if not isinstance(sec.get("controls", False), bool):
            raise ValueError("controls is true or false")
        out_cards = []
        for card in cards:
            if not isinstance(card, dict) or set(card) - {"icon", "title", "body"} or card.get("icon", "info") not in SHOWCASE_ICONS:
                raise ValueError("a card has an icon name, title and body")
            out_cards.append({"icon": card.get("icon", "info"), "title": _world_text(card.get("title"), "title", 60),
                              "body": _world_text(card.get("body"), "body", 240)})
        sections.append({"id": _world_id(sec.get("id"), "section id", seen), "label": _world_text(sec.get("label"), "label", 24), "icon": icon,
                         "heading": _world_text(sec.get("heading"), "heading", 80), "lead": _world_text(sec.get("lead", ""), "lead", 240, required=False),
                         "tags": [_world_text(t, "tag", 40) for t in tags], "cards": out_cards, "table": table, "controls": sec.get("controls", False)})
    return {"schema": SHOWCASE_SCHEMA, "id": sid, "title": _world_text(spec.get("title", "Showcase"), "title", 60),
            "emoji": _world_text(spec.get("emoji", ""), "emoji", 16, required=False), **flags, "sections": sections}


def showcase_css(spec: Any) -> str:
    """The rules that depend on the sections: which one shows, which control looks selected or focused. Plain CSS, no script."""
    show = showcase_validate(spec)
    sid, rules = show["id"], []
    for sec in show["sections"]:
        radio, label = f"#{sid}-sec-{sec['id']}", f"label[for=\"{sid}-sec-{sec['id']}\"]"
        rules.append(f'#{sid}:has({radio}:checked) .ui-shell-section:not([data-section="{sec["id"]}"]){{display:none}}')
        rules.append(f'#{sid}:has({radio}:checked) {label}{{background:var(--ui-accent);color:var(--ui-bg)}}')
        rules.append(f'#{sid}:has({radio}:focus-visible) {label}{{outline:2px solid var(--ui-fg);outline-offset:2px}}')
    return "@layer components{" + "".join(rules) + "}"


def showcase_html(spec: Any) -> str:
    """The shell as semantic HTML. Sections switch through radio buttons (rail and bottom bar share them), so there is no reload and no script;
    only the favorite button and the theme list use ``bindToggles`` / ``bindTheme`` from ui.js. Everything is escaped."""
    show = showcase_validate(spec)
    sid, sections = show["id"], show["sections"]
    used = sorted({s["icon"] for s in sections} | {c["icon"] for s in sections for c in s["cards"]} | ({"star"} if show["favorite"] else set()))
    sprite = "".join(f'<symbol id="{sid}-icon-{name}" viewBox="0 0 24 24"><path d="{SHOWCASE_ICONS[name]}"/></symbol>' for name in used)
    icon = lambda name: f'<svg aria-hidden="true"><use href="#{sid}-icon-{name}"/></svg>'
    radios = "".join(f'<input class="ui-shell-radio" type="radio" name="{sid}-section" id="{sid}-sec-{s["id"]}" value="{s["id"]}"{" checked" if i == 0 else ""}>'
                     for i, s in enumerate(sections))
    nav = lambda css, label_css: "".join(f'<label class="{css}" for="{sid}-sec-{s["id"]}">{icon(s["icon"])}<span class="{label_css}">{escape(s["label"])}</span></label>'
                                         for s in sections)
    favorite = ('<button class="ui-button ui-icon-button" type="button" data-ui-toggle aria-pressed="false" aria-label="Favorite this page" '
                f'title="Favorite this page" data-label-off="Favorite this page" data-label-on="Remove from favorites">{icon("star")}</button>' if show["favorite"] else "")
    themes = ('<select class="ui-input" data-ui-theme-switch aria-label="Theme">' + "".join(f'<option value="{t}">{t}</option>' for t in (*THEMES, *CANDIDATE_THEMES))
              + "</select>" if show["themes"] else "")

    def body(s: dict[str, Any]) -> str:
        out = [f'<h2 id="{sid}-h-{s["id"]}">{escape(s["heading"])}</h2>']
        if s["lead"]:
            out.append(f'<p class="ui-muted">{escape(s["lead"])}</p>')
        if s["tags"]:
            out.append('<div class="ui-shell-tags">' + "".join(f'<span class="ui-tag">{escape(t)}</span>' for t in s["tags"]) + "</div>")
        if s["cards"]:
            out.append('<div class="ui-shell-cards">' + "".join(
                f'<article class="ui-card ui-shell-card">{icon(c["icon"])}<div><h3>{escape(c["title"])}</h3><p>{escape(c["body"])}</p></div></article>'
                for c in s["cards"]) + "</div>")
        if s["table"]:
            head = "".join(f'<th scope="col">{escape(c)}</th>' for c in s["table"]["columns"])
            rows = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in s["table"]["rows"])
            out.append(f'<div class="ui-shell-scroll"><table class="ui-shell-table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
        if s["controls"]:
            out.append(f'<div class="ui-shell-controls"><label for="{sid}-demo-input">Input</label><input class="ui-input" id="{sid}-demo-input" value="shared semantic HTML"> '
                       '<button class="ui-button" type="button">Button</button><span class="ui-tag">tag</span></div>'
                       '<article class="ui-panel"><h3>Panel</h3><p class="ui-muted">Muted text on a panel, using the current theme.</p></article>')
        return "".join(out)

    main = "".join(f'<section class="ui-shell-section" data-section="{s["id"]}" aria-labelledby="{sid}-h-{s["id"]}">{body(s)}</section>' for s in sections)
    title = f'{escape(show["emoji"])} {escape(show["title"])}'.strip()
    return (f'<div class="ui-shell" id="{sid}"><svg class="ui-shell-icons" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">{sprite}</svg>{radios}'
            f'<header class="ui-shell-header"><h1 class="ui-shell-title">{title}</h1><div class="ui-shell-actions">{themes}{favorite}</div></header>'
            f'<div class="ui-shell-body"><nav class="ui-rail" aria-label="Sections">{nav("ui-rail-item", "ui-rail-label")}</nav>'
            f'<main class="ui-shell-main" tabindex="0" aria-label="Content, scrollable">{main}</main></div>'
            f'<nav class="ui-bottom-nav" aria-label="Sections (compact)">{nav("ui-bottom-item", "ui-bottom-label")}</nav></div>')


def showcase_document(spec: Any, *, theme: str = "modern") -> str:
    """A single-file page for a showcase: bundled CSS, its section rules, its HTML and the two ui.js helpers it uses."""
    show = showcase_validate(spec)
    return render_document(trusted_html=showcase_html(show) + module_script(EMBEDDED_UI_JS + "\nbindTheme();bindToggles();\n"),
                           title=show["title"], theme=theme, css=bundled_css() + showcase_css(show))


def random_theme(seed: int) -> dict[str, str]:
    """A seeded palette plus corner radius as ``--ui-*`` tokens; every text pair meets WCAG AA by construction."""
    rng = random.Random(seed)
    hue, dark, sat = rng.random(), rng.random() < 0.5, 0.15 + rng.random() * 0.35
    bg_l = 0.07 + rng.random() * 0.07 if dark else 0.92 + rng.random() * 0.06
    bg, panel = _hsl(hue, sat, bg_l), _hsl(hue, sat, min(1.0, bg_l + (0.05 if dark else 0.04)))
    grounds = (bg, panel)
    return {
        "--ui-bg": bg, "--ui-panel": panel,
        "--ui-fg": _readable(hue + (rng.random() - 0.5) * 0.1, 0.25, grounds, 7),
        "--ui-muted": _readable(hue, 0.12, grounds, 4.5),
        "--ui-border": _hsl(hue, 0.2, bg_l + (0.16 if dark else -0.16)),
        "--ui-accent": _readable(hue + 0.15 + rng.random() * 0.5, 0.55 + rng.random() * 0.3, grounds, 4.5),
        "--ui-danger": _readable(rng.random() * 0.03, 0.7, grounds, 4.5),
        "--ui-radius": ("0", ".25rem", ".5rem", "1rem")[int(rng.random() * 4)],
    }


def theme_palette(hue: float, *, dark: bool = False, sat: float = 0.3, radius: str = ".5rem") -> dict[str, str]:
    """A palette for one hue (0..1): not random, and every text pair meets WCAG AA by construction.

    The same recipe as random_theme(), with the choices fixed: any hue gives a theme, so red, blue or any other color
    needs no hand-tuning. ``dark`` flips the grounds."""
    bg_l = 0.1 if dark else 0.95
    bg, panel = _hsl(hue, sat, bg_l), _hsl(hue, sat, min(1.0, bg_l + (0.05 if dark else 0.04)))
    grounds = (bg, panel)
    return {"--ui-bg": bg, "--ui-panel": panel, "--ui-fg": _readable(hue, 0.25, grounds, 7),
            "--ui-muted": _readable(hue, 0.12, grounds, 4.5), "--ui-border": _hsl(hue, 0.2, bg_l + (0.16 if dark else -0.16)),
            "--ui-accent": _readable(hue, 0.6, grounds, 4.5), "--ui-danger": _readable(0.0, 0.7, grounds, 4.5),
            "--ui-radius": radius}


def theme_palettes() -> dict[str, dict[str, str]]:
    """The token-only themes by name. ``green`` is the one first built by hand in Ironmate's studio (measured against its
    palette); the others are theme_palette(hue). Add a theme by adding its name to CANDIDATE_THEMES and a line here."""
    return {
        "green": {"--ui-bg": "#edf0ec", "--ui-panel": "#ffffff", "--ui-fg": "#163b3b", "--ui-muted": "#546a61",
                  "--ui-border": "#ccdcd4", "--ui-accent": "#126d66", "--ui-danger": "#a73528", "--ui-radius": ".5rem"},
        "red": theme_palette(0.0), "blue": theme_palette(0.6),
    }


def _token_theme_css() -> str:
    blocks = ["/* Candidate themes, token-only: palettes, no theme files (see theme_palettes()). */"]
    for name in CANDIDATE_THEMES:
        tokens = theme_palettes()[name]
        scheme = "dark" if _luminance(tokens["--ui-bg"]) < 0.18 else "light"
        blocks.append(f'body[data-ui-theme="{name}"]{{' + ";".join(f"{k}:{v}" for k, v in tokens.items()) + f";color-scheme:{scheme}}}")
    return "\n".join(blocks) + "\n"


def _hsl(hue: float, sat: float, light: float) -> str:
    r, g, b = colorsys.hls_to_rgb(hue % 1.0, min(max(light, 0.0), 1.0), min(max(sat, 0.0), 1.0))
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _readable(hue: float, sat: float, grounds: tuple[str, ...], minimum: float) -> str:
    """Start at mid lightness and move away from the grounds until the color reads on all of them."""
    step = -0.02 if sum(_luminance(g) for g in grounds) / len(grounds) > 0.18 else 0.02
    light = 0.5
    for _ in range(50):
        color = _hsl(hue, sat, light)
        if all(contrast_ratio(color, g) >= minimum for g in grounds):
            return color
        light += step
    return "#000000" if step < 0 else "#ffffff"


def theme_wall(seeds: Any) -> str:
    """One block of cells, each under its own random theme (inline ``--ui-*`` tokens): themes side by side for review."""
    cells = []
    for seed in seeds:
        theme = random_theme(int(seed))
        style = ";".join(f"{name}:{value}" for name, value in theme.items())
        cells.append(
            f'<section class="ui-wall-cell" data-seed="{int(seed)}" style="{style}"><h3>seed {int(seed)}</h3>'
            '<p class="ui-muted">Muted text on the panel.</p><span class="ui-tag">tag</span> '
            '<button class="ui-button" type="button">Button</button> <a href="#" style="color:var(--ui-accent)">Accent</a> '
            '<span style="color:var(--ui-danger)">Danger</span><div class="ui-card">Card</div></section>')
    return f'<div class="ui-wall">{"".join(cells)}</div>'


def theme_wall_document(count: int) -> str:
    if type(count) is not int or count < 0:
        raise ValueError("theme wall count must be a nonnegative integer")
    return render_document(trusted_html=theme_wall(range(count)), title="Theme wall", css=bundled_css() + _WALL_CSS)


# --- Pages and examples as Python data: specs in, single-file pages out (no HTML files) ---------------
# MCP/API stubs and mocks are one function call. The mock is declarative: a JSON template whose "$input"
# is replaced by what was typed, evaluated the same way here (stub_response) and in the browser.

# --- Coordinates: validate and format a point, read it from a Maps URL, frame a tolerance area, find its XYZ tile --------------------
# Absorbs flutter_navigation_basic's coordinate tool (lib/features/coordinate_tool/domain/coordinate_formatter.dart). Its Dart tests and the shared golden
# vectors (tests/fixtures/coordinate_area_cases.json, python/fixtures/ at 39d659e) are the oracle. Python is the reference; ``coordinates.js`` must agree.
# Short-link expansion (maps.app.goo.gl) needs a network and stays out: paste the expanded URL. Hexadecimal numbers are refused (Dart's parser takes them).

EARTH_RADIUS_M = 6371008.8
_COORD_NUMBER = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_COORD_FULLWIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)} | {0x3000: 0x20, 0x2212: 0x2D}
_MAPS_PATTERNS = tuple(re.compile(pattern, flags) for pattern, flags in (
    (r"[?&#]ll=(-?[0-9]+(?:\.[0-9]+)?)[ \t\r\n\f\v]*,[ \t\r\n\f\v]*(-?[0-9]+(?:\.[0-9]+)?)", re.I | re.A),
    (r"[?&#](?:query|q)=(-?[0-9]+(?:\.[0-9]+)?)[ \t\r\n\f\v]*,[ \t\r\n\f\v]*(-?[0-9]+(?:\.[0-9]+)?)", re.I | re.A),
    (r"!3d(-?[0-9]+(?:\.[0-9]+)?)!4d(-?[0-9]+(?:\.[0-9]+)?)", 0),
    (r"@(-?[0-9]+(?:\.[0-9]+)?)[ \t\r\n\f\v]*,[ \t\r\n\f\v]*(-?[0-9]+(?:\.[0-9]+)?)(?:,|/|z|\?|#|\Z)", 0)))


def fixed(value: float, digits: int) -> str:
    """Like JavaScript's ``toFixed`` and Dart's ``toStringAsFixed``: the exact value rounded half away from zero (Python's ``%.2f`` rounds ties to even)."""
    import decimal
    if value == 0:
        value = 0.0                                              # no "-0.00" for negative zero
    return format(decimal.Decimal(value).quantize(decimal.Decimal(1).scaleb(-digits), rounding=decimal.ROUND_HALF_UP), "f")


def parse_coordinate(latitude: str, longitude: str) -> tuple[float, float]:
    """A checked ``(latitude, longitude)`` from two texts (full-width digits are fine); ``ValueError`` says what is wrong."""
    values = []
    for text in (latitude, longitude):
        text = _shelf_strip(str(text).translate(_COORD_FULLWIDTH))
        if text in ("NaN", "Infinity", "-Infinity", "+Infinity"):
            raise ValueError("Latitude and longitude must be finite numbers.")
        if not _COORD_NUMBER.fullmatch(text):
            raise ValueError("Latitude and longitude must be numbers.")
        values.append(float(text))
    lat, lon = values
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("Latitude and longitude must be finite numbers.")
    if not -90 <= lat <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= lon <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    return lat, lon


def _percent_decode(text: str) -> str:
    """Strict percent-decoding like Dart's ``Uri.decodeComponent`` and JavaScript's ``decodeURIComponent``: a bad escape or bad UTF-8 is a ``ValueError``."""
    out, i = bytearray(), 0
    while i < len(text):
        if text[i] == "%":
            if not re.fullmatch(r"[0-9a-fA-F]{2}", text[i + 1:i + 3]):
                raise ValueError("malformed percent escape")
            out.append(int(text[i + 1:i + 3], 16))
            i += 3
        else:
            out += text[i].encode("utf-8", "surrogatepass")
            i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("invalid UTF-8 in a percent escape") from error


def try_parse_maps_url(text: str) -> tuple[float, float] | None:
    """A point from a Google or Apple Maps URL or share text: ``ll=``, ``query=``/``q=``, a ``!3d..!4d..`` place pin (preferred over ``@``, often only the
    viewport centre), then ``@lat,lng``. Text is tried as written, decoded once, and decoded repeatedly (up to 8 times). ``None`` if nothing usable."""
    raw = _shelf_strip(text.translate(_COORD_FULLWIDTH))
    if not raw:
        return None
    plus = raw.replace("+", " ")
    candidates = [plus]
    try:
        candidates.append(_percent_decode(plus))
    except ValueError:
        pass
    again = plus
    for _ in range(8):
        try:
            following = _percent_decode(again)
        except ValueError:
            break
        if following == again:
            break
        again = following
    candidates.append(again)
    for candidate in candidates:
        for pattern in _MAPS_PATTERNS:
            match = pattern.search(candidate)
            if match:
                try:
                    return parse_coordinate(match.group(1), match.group(2))
                except ValueError:
                    continue
    return None


def to_dms(value: float, *, is_latitude: bool) -> str:
    """``35° 40′ 52.45″ N``: seconds rounded to two places with the carry into minutes and degrees (``179.999999999996`` is ``180° 00′ 00.00″ E``)."""
    absolute = abs(value)
    degrees = math.floor(absolute)
    minute_value = (absolute - degrees) * 60
    minutes = math.floor(minute_value)
    seconds = float(fixed((minute_value - minutes) * 60, 2))
    if seconds >= 60:
        seconds, minutes = 0.0, minutes + 1
        if minutes >= 60:
            minutes, degrees = 0, degrees + 1
    hemisphere = ("S" if value < 0 else "N") if is_latitude else ("W" if value < 0 else "E")
    return f"{degrees}° {minutes:02d}′ {fixed(seconds, 2).rjust(5, '0')}″ {hemisphere}"


def coordinate_text(lat: float, lon: float) -> str:
    return f"{fixed(lat, 6)}, {fixed(lon, 6)}"


def dms_text(lat: float, lon: float) -> str:
    return f"{to_dms(lat, is_latitude=True)}, {to_dms(lon, is_latitude=False)}"


def _normalize_longitude(value: float) -> float:
    while value < -180:
        value += 360
    while value > 180:
        value -= 360
    return value


def tolerance_area(lat: float, lon: float, radius_m: float) -> dict[str, Any]:
    """The box around a point that holds a circle of ``radius_m`` metres: ``south``, ``west``, ``north``, ``east`` and flags for a box that wraps the date line
    (``wraps``) or covers every longitude (``full_longitude``, near a pole). Apple Maps can only take a span (``apple_span``) when neither flag is set."""
    if not math.isfinite(radius_m) or radius_m <= 0:
        raise ValueError("Tolerance radius must be greater than zero.")
    angular = radius_m / EARTH_RADIUS_M
    lat_delta = angular * 180 / math.pi
    south, north = max(-90.0, lat - lat_delta), min(90.0, lat + lat_delta)
    cosine = abs(math.cos(lat * math.pi / 180))
    lon_delta = 180.0 if south <= -90 or north >= 90 or cosine < 1e-12 else min(180, angular / cosine * 180 / math.pi)
    raw_west, raw_east = lon - lon_delta, lon + lon_delta
    full = lon_delta >= 180
    west, east = (-180.0, 180.0) if full else (_normalize_longitude(raw_west), _normalize_longitude(raw_east))
    wraps = not full and (raw_west < -180 or raw_east > 180)
    span = 360.0 if full else (180 - west) + (east + 180) if wraps else abs(east - west)
    return {"lat": lat, "lon": lon, "radius_m": radius_m, "south": south, "west": west, "north": north, "east": east, "wraps": wraps,
            "full_longitude": full, "apple_span": not wraps and not full, "lat_span": abs(north - south), "lon_span": span}


def zoom_for_radius(radius_m: float, latitude: float = 0.0) -> int:
    """A Google Maps zoom (3..20) that roughly frames the radius, about four radii across the viewport at this latitude."""
    if not math.isfinite(radius_m) or radius_m <= 0:
        return 16
    cosine = min(max(abs(math.cos(latitude * math.pi / 180)), 1e-6), 1.0)
    return min(max(math.floor(math.log(40075016.686 * cosine / (radius_m * 4)) / math.log(2)), 3), 20)


def xyz_tile(lat: float, lon: float, zoom: int) -> dict[str, Any]:
    """The Web Mercator (slippy map) tile holding a point at ``zoom`` 0..22; latitudes are held to ±85.05112878."""
    if type(zoom) is not int or not 0 <= zoom <= 22:
        raise ValueError("XYZ tile zoom must be between 0 and 22.")
    lat = min(max(lat, -85.05112878), 85.05112878)
    n = 2.0 ** zoom
    x = min(max(math.floor((lon + 180) / 360 * n), 0), int(n) - 1)
    mercator = math.log(math.tan(math.pi / 4 + lat * math.pi / 180 / 2))
    y = min(max(math.floor((1 - mercator / math.pi) / 2 * n), 0), int(n) - 1)
    return {"zoom": zoom, "x": x, "y": y, "path": f"{zoom}/{x}/{y}"}


def _query(params: dict[str, str]) -> str:
    from urllib.parse import urlencode
    return urlencode(params)


def maps_urls(lat: float, lon: float) -> dict[str, str]:
    """Google, Apple and OpenStreetMap static-preview links for a point (Dart's ``Uri.https`` encoding: ``,`` is ``%2C``, a space is ``+``)."""
    point = coordinate_text(lat, lon).replace(" ", "")
    return {"google": "https://www.google.com/maps/search/?" + _query({"api": "1", "query": point}),
            "apple": "https://maps.apple.com/?" + _query({"ll": point, "q": "Coordinates"}),
            "osm_preview": "https://staticmap.openstreetmap.de/staticmap.php?" + _query(
                {"center": point, "zoom": "16", "size": "600x400", "maptype": "mapnik", "markers": point + ",lightblue1"})}


def _radius_text(value: float) -> str:
    return str(int(value)) if value == int(value) else fixed(value, 2)


def area_texts(area: dict[str, Any]) -> dict[str, str]:
    """What the tool offers to copy for a tolerance area: plain text, bounds, bbox, JSON, Google Maps and MapKit snippets, and the two viewport links."""
    lat, lon, f = area["lat"], area["lon"], lambda v: fixed(v, 6)
    radius = _radius_text(area["radius_m"])
    wraps = "true" if area["wraps"] else "false"
    zoom = zoom_for_radius(area["radius_m"], lat)
    apple = {"ll": f"{f(lat)},{f(lon)}", "q": "Tolerance area"}
    if area["apple_span"] and area["lat_span"] > 0 and area["lon_span"] > 0:
        apple["spn"] = f"{f(area['lat_span'])},{f(area['lon_span'])}"
    return {
        "center_radius": f"center: {f(lat)}, {f(lon)}\nradius_m: {radius}",
        "bounds": f"south: {f(area['south'])}\nwest: {f(area['west'])}\nnorth: {f(area['north'])}\neast: {f(area['east'])}\nwraps_antimeridian: {wraps}",
        "bbox": f"[{f(area['west'])}, {f(area['south'])}, {f(area['east'])}, {f(area['north'])}]",
        "json": ('{\n  "center": {\n    "latitude": ' + f(lat) + ',\n    "longitude": ' + f(lon) + '\n  },\n  "radius_m": ' + radius + ',\n  "bounds": {\n    "south": '
                 + f(area["south"]) + ',\n    "west": ' + f(area["west"]) + ',\n    "north": ' + f(area["north"]) + ',\n    "east": ' + f(area["east"])
                 + ',\n    "wraps_antimeridian": ' + wraps + '\n  }\n}'),
        "google_circle": "new google.maps.Circle({\n  center: {\n    lat: " + f(lat) + ",\n    lng: " + f(lon) + "\n  },\n  radius: " + radius + "\n});",
        "mapkit_circle": ("MKCircle(\n  center: CLLocationCoordinate2D(\n    latitude: " + f(lat) + ",\n    longitude: " + f(lon) + "\n  ),\n  radius: " + radius + "\n)"),
        "google_rectangle": ("new google.maps.Rectangle({\n  bounds: {\n    south: " + f(area["south"]) + ",\n    west: " + f(area["west"]) + ",\n    north: "
                             + f(area["north"]) + ",\n    east: " + f(area["east"]) + "\n  }\n});"),
        "mapkit_region": ("MKCoordinateRegion(\n  center: CLLocationCoordinate2D(\n    latitude: " + f(lat) + ",\n    longitude: " + f(lon) + "\n  ),\n  span: MKCoordinateSpan(\n"
                          "    latitudeDelta: " + f(area["lat_span"]) + ",\n    longitudeDelta: " + f(area["lon_span"]) + "\n  )\n)"),
        "google_area_url": f"https://www.google.com/maps/@{f(lat)},{f(lon)},{zoom}z",
        "apple_area_url": "https://maps.apple.com/?" + _query(apple),
    }


_CSS["coordinates.css"] = ("@layer components{.ui-coord label{display:block;margin:8px 0 4px}.ui-coord .ui-input{width:100%;box-sizing:border-box}"
                           ".ui-coord-bar{display:flex;flex-wrap:wrap;gap:8px 16px;margin:8px 0;padding:0;border:0}.ui-coord-bar label{display:inline-block;margin:0}"
                           ".ui-coord dt{margin:16px 0 4px}.ui-coord dd{margin:0}.ui-coord dd pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}")


def coordinates_html() -> str:
    """The coordinate tool as semantic HTML: a point (typed or read from a Maps URL), a tolerance radius, a tile zoom, and the results the page fills in."""
    presets = ((25, "Exact / GPS"), (100, "Building / facility"), (350, "Station / campus"), (1000, "Park / large facility"), (3000, "District / loose area"), ("custom", "Custom"))
    radios = "".join(f'<label><input type="radio" name="coord-preset" value="{v}"{" checked" if v == 100 else ""}> {label}{"" if v == "custom" else f" ({v} m)"}</label>' for v, label in presets)
    return ('<section class="ui-panel ui-coord" id="coord" data-ui-coord><h2>Coordinates</h2>'
            '<p class="ui-muted">Check a point, read it from a Google or Apple Maps URL, and frame a tolerance area around it. Everything is computed in this page; '
            'short links (maps.app.goo.gl) are not expanded: paste the full address.</p>'
            '<label for="coord-lat">Latitude</label><input class="ui-input" id="coord-lat" data-lat value="35.681236" inputmode="decimal" autocomplete="off">'
            '<label for="coord-lon">Longitude</label><input class="ui-input" id="coord-lon" data-lon value="139.767125" inputmode="decimal" autocomplete="off">'
            '<label for="coord-url">Or paste a Maps URL</label><input class="ui-input" id="coord-url" data-url autocomplete="off">'
            '<p><button class="ui-button" type="button" data-use-url>Use this URL</button></p>'
            '<p class="ui-muted" role="status" aria-live="polite" data-status></p>'
            f'<fieldset class="ui-coord-bar"><legend>Tolerance</legend>{radios}</fieldset>'
            '<label for="coord-radius">Custom radius (metres)</label><input class="ui-input" id="coord-radius" data-radius type="number" min="1" step="any" value="500">'
            '<label for="coord-zoom">Tile zoom (0 to 22)</label><input class="ui-input" id="coord-zoom" data-zoom type="number" min="0" max="22" step="1" value="16">'
            '<dl data-out></dl></section>')


def coordinates_document(*, theme: str = "modern") -> str:
    """A single-file page for the coordinate tool."""
    return render_document(trusted_html='<main class="ui-page">' + coordinates_html() + "</main>" + module_script(_JS["coordinates.js"]), title="Coordinates",
                           theme=theme, css=bundled_css())


# --- Photo studio: import rules, image format sniffing, EXIF orientation, frame and stamp geometry, undo history ------------------------------
# Absorbs flutter_navigation_basic's lib/features/photo_studio (data/image_format_sniff.dart, data/photo_import_limits.dart, data/photo_media_ports.dart,
# domain/*.dart, the geometry in presentation/photo_rect_canvas.dart and studio_canvas_capture.dart). Its Dart tests and test/fixtures/photo_studio/import_compat
# are the golden values. Python is the reference; ``photo.js`` must agree. Deliberate differences: the pixel budget is checked from the file header before any
# decode, EXIF orientation is neutralised in the bytes and applied by the page (so every engine draws the same upright pixels), numbers are plain finite
# floats, and rounding is half up in both languages.

PHOTO_MAX_BYTES = 32 * 1024 * 1024
PHOTO_MAX_PIXELS = 40_000_000
PHOTO_MAX_EDGE = 4096
PHOTO_DOWNSCALE = 2 / 3
PHOTO_MIN_SIZE = 0.04
PHOTO_HISTORY_LIMIT = 20
PHOTO_EXPORT_NAME = "photo-studio.png"
PHOTO_HEIC_BRANDS = ("heic", "heif", "mif1", "msf1", "heix")
PHOTO_LABELS = {"empty": "empty", "png": "PNG", "jpeg": "JPEG", "webp": "WebP", "gif": "GIF", "avif": "AVIF", "heic": "HEIC", "unknown": "unknown"}
PHOTO_STAMPS = ("⭐", "❤️", "😊", "🔥", "📷", "🌸", "✨", "🍀")
PHOTO_COLORS = (("Purple", "#7e57c2"), ("Red", "#e53935"), ("Green", "#43a047"), ("Blue", "#1e88e5"), ("Amber", "#fdd835"), ("White", "#ffffff"), ("Black", "#212121"))
PHOTO_SHAPES = ("rectangle", "circle", "triangle")
PHOTO_HANDLES = ("move", "topLeft", "topRight", "bottomLeft", "bottomRight", "left", "right", "top", "bottom")
PHOTO_OUTCOMES = ("supported", "rejected:empty", "rejected:tooLargeBytes", "rejected:tooManyPixels", "rejected:heicConversionFailed", "rejected:undecodable",
                  "unsupported_by_runtime", "not_verified")
PHOTO_MESSAGES = {
    "idle": "Select an image or paste here", "loading": "Loading image…", "success": "Image loaded", "cancelled": "No change.",
    "superseded": "A newer import replaced this load.", "noClipboardImage": "Clipboard has no photo to paste.",
    "clipboardUnavailable": "This browser did not allow clipboard image access. Use Import image, or paste again after allowing permission.",
    "pickFailed": "Could not decode this image.", "decodeFailed": "Could not decode this image.",
    "tooLarge": "That photo is too large. Choose a smaller image or screenshot.", "tooLargeBytes": "That photo is too large. Choose a smaller image or screenshot.",
    "tooManyPixels": "That photo has too many pixels. Choose a smaller image or screenshot.",
    "heicUnsupported": "This HEIC/HEIF photo cannot be decoded in this browser. Export it as JPEG or PNG first.",
    "unsupportedFormat": "That image format could not be decoded."}
_PHOTO_FAILURES = {"empty": "decodeFailed", "tooLargeBytes": "tooLargeBytes", "tooManyPixels": "tooManyPixels", "undecodable": "unsupportedFormat",
                   "heicConversionFailed": "heicUnsupported"}


def _photo_half_up(value: float) -> int:
    floor = math.floor(value)
    return floor + 1 if value - floor >= 0.5 else floor


def _photo_clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _photo_distance(dx: float, dy: float) -> float:
    return math.sqrt(dx * dx + dy * dy)                    # Dart's Offset.distance; JavaScript's Math.hypot can differ in the last bit


def photo_sniff(data: bytes) -> dict[str, Any]:
    """The format hint from the magic bytes, without decoding or reading GPS: ``kind``, ``label``, ``brand`` (HEIC/AVIF ``ftyp``), ``progressive`` (JPEG),
    ``orientation`` (JPEG EXIF 1-8 or ``None``), ``orientation_offset`` (where its two bytes sit in ``data``) and ``orientation_big_endian``."""
    info: dict[str, Any] = {"kind": "unknown", "brand": None, "progressive": None, "orientation": None, "orientation_offset": None, "orientation_big_endian": None}
    n = len(data)
    if n == 0:
        info["kind"] = "empty"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        info["kind"] = "png"
    elif n >= 3 and data[0] == 0xFF and data[1] == 0xD8 and data[2] == 0xFF:
        info["kind"] = "jpeg"
        info["progressive"] = _photo_jpeg_progressive(data)
        found = _photo_jpeg_orientation(data)
        if found:
            info["orientation"], info["orientation_offset"], info["orientation_big_endian"] = found
    elif n >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        info["kind"] = "webp"
    elif n >= 6 and data[:4] == b"GIF8" and data[4] in (0x39, 0x37) and data[5] == 0x61:
        info["kind"] = "gif"
    else:
        brand = _photo_ftyp_brand(data)
        if brand in PHOTO_HEIC_BRANDS:
            info["kind"], info["brand"] = "heic", brand
        elif brand in ("avif", "avis"):
            info["kind"], info["brand"] = "avif", brand
    info["label"] = PHOTO_LABELS[info["kind"]]
    return info


def _photo_ftyp_brand(data: bytes) -> str | None:
    if len(data) < 12 or data[4:8] != b"ftyp":
        return None
    return "".join(chr(b) for b in data[8:12])             # one code unit per byte, like Dart's String.fromCharCodes


def _photo_jpeg_progressive(data: bytes) -> bool:
    i, n = 2, len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            return False
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD9, 0xDA):
            return False
        if marker in (0xC2, 0xC6, 0xCA, 0xCE):
            return True
        if marker in (0xC0, 0xC1, 0xC3, 0xC9, 0xCB):
            return False
        if 0xD0 <= marker <= 0xD7 or marker in (0x00, 0x01):
            i += 2
            continue
        length = (data[i + 2] << 8) | data[i + 3]
        if length < 2:
            return False
        i += 2 + length
    return False


def _photo_jpeg_orientation(data: bytes) -> tuple[int, int, bool] | None:
    i, n = 2, len(data)
    while i + 8 < n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD9, 0xDA):
            return None
        length = (data[i + 2] << 8) | data[i + 3]
        if marker == 0xE1:
            if length < 8 or i + 2 + length > n:
                return None
            if length - 2 >= 6 and data[i + 4:i + 8] == b"Exif":                # an XMP APP1 may come first: keep scanning past it
                return _photo_exif_orientation(data, i + 4, i + 2 + length)
            i += 2 + length
            continue
        if 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if length < 2:
            return None
        i += 2 + length
    return None


def _photo_exif_orientation(data: bytes, start: int, end: int) -> tuple[int, int, bool] | None:
    segment = data[start:end]
    if len(segment) < 14 or segment[:6] != b"Exif\x00\x00":
        return None
    tiff = segment[6:]
    big = tiff[0] == 0x4D and tiff[1] == 0x4D
    if not (big or (tiff[0] == 0x49 and tiff[1] == 0x49)):
        return None

    def u16(offset: int) -> int:
        if offset + 1 >= len(tiff):
            return -1
        return (tiff[offset] << 8 | tiff[offset + 1]) if big else (tiff[offset] | tiff[offset + 1] << 8)

    def u32(offset: int) -> int:
        if offset + 3 >= len(tiff):
            return -1
        b = tiff[offset:offset + 4]
        return int.from_bytes(b, "big" if big else "little")

    ifd = u32(4)
    if ifd < 0 or ifd + 2 > len(tiff):
        return None
    count = u16(ifd)
    for entry_number in range(count):
        entry = ifd + 2 + entry_number * 12
        if entry + 12 > len(tiff):
            return None
        if u16(entry) != 0x0112:
            continue
        if u16(entry + 2) != 3 or u32(entry + 4) != 1:
            return None
        value = u16(entry + 8)
        return (value, start + 6 + entry + 8, big) if 1 <= value <= 8 else None
    return None


def photo_png_complete(data: bytes) -> bool:
    """Whether a PNG's chunks run unbroken from IHDR to IEND (lengths only; checksums are not verified). Engines differ on a cut-off PNG, strict ones refusing it and lenient ones
    drawing what they have, so the page decides this itself."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    i, n, first = 8, len(data), True
    while i + 12 <= n:
        length, kind = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
        if first and kind != b"IHDR":
            return False
        first = False
        if kind == b"IEND":
            return True
        if length > n:
            return False
        i += 12 + length
    return False


def photo_neutralize_orientation(data: bytes) -> bytes:
    """A copy of a JPEG with its EXIF Orientation set to 1, so no engine rotates it and the page applies the turn itself (anything else: ``data`` as is)."""
    info = photo_sniff(data)
    if info["orientation"] in (None, 1):
        return bytes(data)
    out = bytearray(data)
    at = info["orientation_offset"]
    out[at:at + 2] = b"\x00\x01" if info["orientation_big_endian"] else b"\x01\x00"
    return bytes(out)


def photo_header_size(data: bytes) -> tuple[int, int] | None:
    """The width and height a PNG, GIF, JPEG or WebP file declares in its header (read without decoding), or ``None`` (also for HEIC/AVIF and damaged headers)."""
    n = len(data)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if n >= 24 and data[12:16] == b"IHDR":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return None
    if n >= 10 and data[:4] == b"GIF8" and data[4] in (0x39, 0x37) and data[5] == 0x61:
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if n >= 3 and data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 3 < n:
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD9, 0xDA):
                return None
            if 0xD0 <= marker <= 0xD7 or marker in (0x00, 0x01):
                i += 2
                continue
            length = (data[i + 2] << 8) | data[i + 3]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if length < 8 or i + 9 > n:
                    return None
                return (data[i + 7] << 8) | data[i + 8], (data[i + 5] << 8) | data[i + 6]
            if length < 2:
                return None
            i += 2 + length
        return None
    if n >= 16 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 " and n >= 30 and data[23:26] == b"\x9d\x01\x2a":
            return (data[26] | data[27] << 8) & 0x3FFF, (data[28] | data[29] << 8) & 0x3FFF
        if chunk == b"VP8L" and n >= 25 and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8X" and n >= 30:
            return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    return None


_PHOTO_OPS = {2: ("flipX", 0, True, False), 3: ("rotate", 180, False, False), 4: ("flipY", 0, False, True), 5: ("transpose", 90, True, False),
              6: ("rotate", 90, False, False), 7: ("transverse", -90, True, False), 8: ("rotate", -90, False, False)}


def photo_orientation_op(orientation: int) -> dict[str, Any] | None:
    """What EXIF Orientation 2-8 asks for (the Android table the Dart tests keep as evidence); 1 and anything else: ``None``."""
    op = _PHOTO_OPS.get(orientation) if isinstance(orientation, int) and not isinstance(orientation, bool) else None
    return None if op is None else {"op": op[0], "degrees": op[1], "flip_x": op[2], "flip_y": op[3]}


def photo_oriented_size(width: int, height: int, orientation: int) -> tuple[int, int]:
    """The upright size of a ``width`` x ``height`` picture with this EXIF Orientation (5-8 swap the sides)."""
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def photo_orientation_matrix(orientation: int, width: int, height: int) -> tuple[int, int, int, int, int, int]:
    """The canvas ``setTransform(a, b, c, d, e, f)`` that draws a stored ``width`` x ``height`` picture upright for EXIF Orientation 1-8
    (x' = a*x + c*y + e, y' = b*x + d*y + f); anything else is treated as 1."""
    w, h = width, height
    return {2: (-1, 0, 0, 1, w, 0), 3: (-1, 0, 0, -1, w, h), 4: (1, 0, 0, -1, 0, h), 5: (0, 1, 1, 0, 0, 0), 6: (0, 1, -1, 0, h, 0),
            7: (0, -1, -1, 0, h, w), 8: (0, -1, 1, 0, 0, w)}.get(orientation, (1, 0, 0, 1, 0, 0))


def photo_reject_bytes(length: int) -> str | None:
    """``empty`` or ``tooLargeBytes`` for a raw file of this many bytes, else ``None``."""
    return "empty" if length <= 0 else "tooLargeBytes" if length > PHOTO_MAX_BYTES else None


def photo_reject_size(width: int, height: int) -> str | None:
    """``undecodable`` for a side that is not positive, ``tooManyPixels`` above 40 megapixels, else ``None``."""
    if width <= 0 or height <= 0:
        return "undecodable"
    return "tooManyPixels" if width * height > PHOTO_MAX_PIXELS else None


def photo_document_size(width: int, height: int) -> tuple[int, int]:
    """The size the studio keeps a ``width`` x ``height`` photo at: two thirds of each side, then the long side at most 4096 (what Flutter's web adapter does)."""
    tw = min(max(_photo_half_up(width * PHOTO_DOWNSCALE), 1), width)
    th = min(max(_photo_half_up(height * PHOTO_DOWNSCALE), 1), height)
    long_edge = max(tw, th)
    if long_edge > PHOTO_MAX_EDGE:
        fit = PHOTO_MAX_EDGE / long_edge
        tw = min(max(_photo_half_up(tw * fit), 1), width)
        th = min(max(_photo_half_up(th * fit), 1), height)
    return tw, th


def photo_failure(rejection: str) -> dict[str, str]:
    """A rejection (``empty``, ``tooLargeBytes``, ``tooManyPixels``, ``undecodable``, ``heicConversionFailed``) as its failure reason, outcome and message."""
    reason = _PHOTO_FAILURES[rejection]
    return {"rejection": rejection, "reason": reason, "outcome": "rejected:" + rejection, "message": PHOTO_MESSAGES[reason]}


def photo_decide(data: bytes, decode: Any = None, declared_mime: str | None = None) -> dict[str, Any]:
    """Whether ``data`` may become the studio photo, with Flutter's order of checks: a declared type that is not ``image/*``, then empty or over 32 MiB,
    then the pixel budget from the header, a PNG that stops short of IEND, then ``decode(data)`` (a ``(width, height)`` or ``None`` from the engine), then the budget on that size.
    ``{"ok": True, "format", "width", "height", "document", "message"}`` or ``{"ok": False, ...photo_failure(...)}``."""
    if declared_mime and not declared_mime.startswith("image/"):
        return {"ok": False, **photo_failure("undecodable")}
    rejection = photo_reject_bytes(len(data))
    if rejection:
        return {"ok": False, **photo_failure(rejection)}
    info = photo_sniff(data)
    header = photo_header_size(data)
    if header and header[0] > 0 and header[1] > 0 and (rejection := photo_reject_size(*header)):
        return {"ok": False, **photo_failure(rejection)}
    if info["kind"] == "png" and not photo_png_complete(data):
        return {"ok": False, **photo_failure("undecodable")}
    size = decode(data) if decode else None
    if size is None:
        return {"ok": False, **photo_failure("heicConversionFailed" if info["kind"] == "heic" else "undecodable")}
    width, height = size
    if rejection := photo_reject_size(width, height):
        return {"ok": False, **photo_failure(rejection)}
    label = info["label"] if info["kind"] != "unknown" else (declared_mime.split("/")[-1].upper() if declared_mime else "IMAGE")
    return {"ok": True, "outcome": "supported", "format": label, "width": width, "height": height, "document": photo_document_size(width, height),
            "message": PHOTO_MESSAGES["success"], "meta": f"{label} · {width} × {height}"}


def photo_png(width: int, height: int, rgba: bytes | None = None) -> bytes:
    """A PNG built in memory (8-bit RGBA, filter 0): ``rgba`` is ``width * height * 4`` bytes, or all transparent black."""
    rows = rgba if rgba is not None else bytes(width * height * 4)
    if len(rows) != width * height * 4:
        raise ValueError("rgba must hold width * height * 4 bytes")
    raw = b"".join(b"\x00" + rows[y * width * 4:(y + 1) * width * 4] for y in range(height))
    chunk = lambda kind, body: len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# Normalised rectangles are ``{"left", "top", "right", "bottom"}`` in 0..1 of the canvas.

def photo_rect(left: float, top: float, right: float, bottom: float) -> dict[str, float]:
    return {"left": left, "top": top, "right": right, "bottom": bottom}


PHOTO_INITIAL_RECT = photo_rect(0.2, 0.2, 0.8, 0.8)


def photo_rect_from_diagonal(x0: float, y0: float, x1: float, y1: float) -> dict[str, float]:
    """The rectangle two opposite corners span, clamped to 0..1, for a drag in any direction (the minimum size is not enforced)."""
    c = lambda v: _photo_clamp(v, 0.0, 1.0)
    return photo_rect(c(min(x0, x1)), c(min(y0, y1)), c(max(x0, x1)), c(max(y0, y1)))


def photo_rect_sanitized(rect: dict[str, float]) -> dict[str, float]:
    """Clamped to 0..1, ordered, and at least 0.04 wide and high."""
    l, t, r, b = (_photo_clamp(rect[k], 0.0, 1.0) for k in ("left", "top", "right", "bottom"))
    if r < l:
        l, r = r, l
    if b < t:
        t, b = b, t
    if r - l < PHOTO_MIN_SIZE:
        r = min(1.0, l + PHOTO_MIN_SIZE)
        l = max(0.0, r - PHOTO_MIN_SIZE)
    if b - t < PHOTO_MIN_SIZE:
        b = min(1.0, t + PHOTO_MIN_SIZE)
        t = max(0.0, b - PHOTO_MIN_SIZE)
    return photo_rect(l, t, r, b)


def photo_rect_translated(rect: dict[str, float], dx: float, dy: float) -> dict[str, float]:
    """Moved by ``dx``, ``dy`` and kept inside the unit square."""
    l, t, r, b = rect["left"] + dx, rect["top"] + dy, rect["right"] + dx, rect["bottom"] + dy
    if l < 0:
        r -= l
        l = 0
    if t < 0:
        b -= t
        t = 0
    if r > 1:
        l -= r - 1
        r = 1
    if b > 1:
        t -= b - 1
        b = 1
    return photo_rect_sanitized(photo_rect(l, t, r, b))


def photo_rect_resized(rect: dict[str, float], handle: str, dx: float, dy: float) -> dict[str, float]:
    """Dragged by ``handle`` (``move``, a corner or an edge) by ``dx``, ``dy``."""
    if handle == "move":
        return photo_rect_translated(rect, dx, dy)
    if handle not in PHOTO_HANDLES:
        raise ValueError("unknown handle")
    l, t, r, b = rect["left"], rect["top"], rect["right"], rect["bottom"]
    if handle in ("topLeft", "bottomLeft", "left"):
        l += dx
    if handle in ("topRight", "bottomRight", "right"):
        r += dx
    if handle in ("topLeft", "topRight", "top"):
        t += dy
    if handle in ("bottomLeft", "bottomRight", "bottom"):
        b += dy
    return photo_rect_sanitized(photo_rect(l, t, r, b))


def photo_rect_text(rect: dict[str, float]) -> str:
    return "\n".join(f"{k}: {fixed(rect[k], 4)}" for k in ("left", "top", "right", "bottom"))


def photo_rect_csv(rect: dict[str, float]) -> str:
    return ", ".join(fixed(rect[k], 4) for k in ("left", "top", "right", "bottom"))


def photo_midpoint(x0: float, y0: float, x1: float, y1: float) -> dict[str, float]:
    return {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2}


def photo_rect_edge_midpoints(rect: dict[str, float]) -> list[dict[str, float]]:
    """The midpoints of the top, right, bottom and left edges."""
    l, t, r, b = rect["left"], rect["top"], rect["right"], rect["bottom"]
    return [photo_midpoint(l, t, r, t), photo_midpoint(r, t, r, b), photo_midpoint(l, b, r, b), photo_midpoint(l, t, l, b)]


def photo_circle(rect: dict[str, float]) -> dict[str, float]:
    """The circle inscribed in the box: centre and radius."""
    return {"cx": (rect["left"] + rect["right"]) / 2, "cy": (rect["top"] + rect["bottom"]) / 2,
            "radius": min(rect["right"] - rect["left"], rect["bottom"] - rect["top"]) / 2}


def photo_triangle(rect: dict[str, float]) -> list[dict[str, float]]:
    """The triangle with its apex at the top centre and its base on the bottom edge: apex, right, left."""
    return [{"x": (rect["left"] + rect["right"]) / 2, "y": rect["top"]}, {"x": rect["right"], "y": rect["bottom"]}, {"x": rect["left"], "y": rect["bottom"]}]


def photo_triangle_midpoints(rect: dict[str, float]) -> list[dict[str, float]]:
    v = photo_triangle(rect)
    return [photo_midpoint(v[0]["x"], v[0]["y"], v[1]["x"], v[1]["y"]), photo_midpoint(v[1]["x"], v[1]["y"], v[2]["x"], v[2]["y"]),
            photo_midpoint(v[2]["x"], v[2]["y"], v[0]["x"], v[0]["y"])]


def _photo_in_triangle(px: float, py: float, ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
    v0x, v0y, v1x, v1y, v2x, v2y = cx - ax, cy - ay, bx - ax, by - ay, px - ax, py - ay
    d00, d01, d02 = v0x * v0x + v0y * v0y, v0x * v1x + v0y * v1y, v0x * v2x + v0y * v2y
    d11, d12 = v1x * v1x + v1y * v1y, v1x * v2x + v1y * v2y
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1e-12:
        return False
    u, v = (d11 * d02 - d01 * d12) / denominator, (d00 * d12 - d01 * d02) / denominator
    return u >= 0 and v >= 0 and u + v <= 1


def _photo_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    abx, aby = bx - ax, by - ay
    length2 = abx * abx + aby * aby
    if length2 < 1e-12:
        return _photo_distance(px - ax, py - ay)
    t = _photo_clamp(((px - ax) * abx + (py - ay) * aby) / length2, 0.0, 1.0)
    return _photo_distance(px - (ax + t * abx), py - (ay + t * aby))


def photo_shape_contains(rect: dict[str, float], shape: str, x: float, y: float, slop: float = 0) -> bool:
    """Whether the point is inside the shape drawn in ``rect``; ``slop`` widens the target. The empty corners of a circle or triangle do not count."""
    if shape == "rectangle":
        return rect["left"] - slop <= x <= rect["right"] + slop and rect["top"] - slop <= y <= rect["bottom"] + slop
    if shape == "circle":
        c = photo_circle(rect)
        r = c["radius"] + slop
        return (x - c["cx"]) * (x - c["cx"]) + (y - c["cy"]) * (y - c["cy"]) <= r * r
    if shape == "triangle":
        v = photo_triangle(rect)
        if _photo_in_triangle(x, y, v[0]["x"], v[0]["y"], v[1]["x"], v[1]["y"], v[2]["x"], v[2]["y"]):
            return True
        if slop <= 0:
            return False
        return any(_photo_segment_distance(x, y, v[i]["x"], v[i]["y"], v[(i + 1) % 3]["x"], v[(i + 1) % 3]["y"]) <= slop for i in range(3))
    raise ValueError("unknown shape")


def photo_segment_intersection(ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float) -> dict[str, float] | None:
    """Where segment AB crosses segment CD, or ``None`` when they are parallel or miss."""
    rx, ry, sx, sy = bx - ax, by - ay, dx - cx, dy - cy
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-12:
        return None
    t = ((cx - ax) * sy - (cy - ay) * sx) / denominator
    u = ((cx - ax) * ry - (cy - ay) * rx) / denominator
    if t < 0 or t > 1 or u < 0 or u > 1:
        return None
    return {"x": ax + t * rx, "y": ay + t * ry}


def photo_describe(rect: dict[str, float], shape: str) -> str:
    """The geometry panel's text for a frame (midpoints and derived points to four decimals)."""
    p = lambda point: f"{fixed(point['x'], 4)}, {fixed(point['y'], 4)}"
    if shape == "rectangle":
        m = photo_rect_edge_midpoints(rect)
        return "\n".join(["shape: rectangle", photo_rect_text(rect), *(f"mid.{name}: {p(point)}" for name, point in zip(("top", "right", "bottom", "left"), m))])
    if shape == "circle":
        c = photo_circle(rect)
        return f"shape: circle\ncx: {fixed(c['cx'], 4)}\ncy: {fixed(c['cy'], 4)}\nradius: {fixed(c['radius'], 4)}"
    if shape == "triangle":
        v, m = photo_triangle(rect), photo_triangle_midpoints(rect)
        return "\n".join(["shape: triangle", f"apex: {p(v[0])}", f"right: {p(v[1])}", f"left: {p(v[2])}",
                          f"mid.apexRight: {p(m[0])}", f"mid.base: {p(m[1])}", f"mid.apexLeft: {p(m[2])}"])
    raise ValueError("unknown shape")


PHOTO_HANDLE_SLOP = 18
PHOTO_STAMP_MIN_HIT = 18


def photo_hit_handle(rect: dict[str, float], width: float, height: float, x: float, y: float) -> str | None:
    """Which handle of a frame the canvas point (x, y) in a ``width`` x ``height`` canvas grabs: a corner within 18, an edge strip, else ``move`` inside the
    frame shrunk by 4, else ``None``."""
    l, t, r, b = rect["left"] * width, rect["top"] * height, rect["right"] * width, rect["bottom"] * height
    s = PHOTO_HANDLE_SLOP
    for name, cx, cy in (("topLeft", l, t), ("topRight", r, t), ("bottomLeft", l, b), ("bottomRight", r, b)):
        if _photo_distance(cx - x, cy - y) <= s:
            return name
    side, wide = max(0.0, (b - t) - s * 2), max(0.0, (r - l) - s * 2)
    for name, left, top, w, h in (("left", l - s / 2, t + s, s, side), ("right", r - s / 2, t + s, s, side), ("top", l + s, t - s / 2, wide, s), ("bottom", l + s, b - s / 2, wide, s)):
        if left <= x < left + w and top <= y < top + h:
            return name
    if l + 4 <= x < r - 4 and t + 4 <= y < b - 4:
        return "move"
    return None


def photo_hit_frame(frames: list[dict[str, Any]], width: float, height: float, x: float, y: float) -> dict[str, Any] | None:
    """The topmost frame (``{"id", "rect", "shape", ...}``) under the canvas point, shape-aware with a 4-pixel margin."""
    if width <= 0 or height <= 0:
        return None
    slop = 4 / min(width, height)
    for frame in reversed(frames):
        if photo_shape_contains(frame["rect"], frame["shape"], x / width, y / height, slop):
            return frame
    return None


def photo_hit_stamp(stamps: list[dict[str, Any]], width: float, height: float, x: float, y: float) -> dict[str, Any] | None:
    """The topmost stamp whose centre is within ``max(18, 0.05 * shorter side * scale)`` pixels of the point."""
    for stamp in reversed(stamps):
        radius = max(float(PHOTO_STAMP_MIN_HIT), min(width, height) * 0.05 * stamp["scale"])
        if _photo_distance(stamp["x"] * width - x, stamp["y"] * height - y) <= radius:
            return stamp
    return None


def photo_export_size(width: float, height: float, ratio: float = 2) -> tuple[int, int]:
    """The exported PNG's size for an on-screen canvas: each side times the pixel ratio, rounded, between 1 and 4096."""
    return min(max(_photo_half_up(width * ratio), 1), PHOTO_MAX_EDGE), min(max(_photo_half_up(height * ratio), 1), PHOTO_MAX_EDGE)


def photo_contain_rect(image_width: float, image_height: float, width: float, height: float) -> tuple[float, float, float, float]:
    """Where a picture is drawn in a canvas to fit whole and centred: ``(x, y, w, h)``."""
    if image_width / image_height > width / height:
        w, h = width, width / (image_width / image_height)
    else:
        w, h = height * (image_width / image_height), height
    return (width - w) / 2, (height - h) / 2, w, h


def photo_stamp_px(width: float, height: float, scale: float) -> float:
    """A stamp's font size in canvas pixels: a tenth of the shorter side times its scale kept between 0.4 and 3."""
    return min(width, height) * 0.1 * _photo_clamp(scale, 0.4, 3.0)


class PhotoHistory:
    """Bounded undo and redo of whole studio states (JSON-like dicts compared by value), with gestures as one step. At most 20 undo steps."""

    def __init__(self, limit: int = PHOTO_HISTORY_LIMIT):
        self.limit, self._undo, self._redo, self._pending = limit, [], [], None

    @property
    def depth(self) -> int:
        return len(self._undo)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def states(self) -> list[Any]:
        """Every state kept for undo and redo (the page keeps the photos these name)."""
        return [*self._undo, *self._redo]

    def begin_gesture(self, current: Any) -> None:
        if self._pending is None:
            self._pending = current

    def end_gesture(self, current: Any) -> bool:
        pending, self._pending = self._pending, None
        if pending is None or pending == current:
            return False
        self._push(pending)
        return True

    def record_change(self, before: Any, after: Any) -> bool:
        if before == after:
            return False
        self._push(before)
        return True

    def undo(self, current: Any) -> Any:
        self._pending = None
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current: Any) -> Any:
        self._pending = None
        if not self._redo:
            return None
        self._undo.append(current)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        return self._redo.pop()

    def clear_pending(self) -> None:
        self._pending = None

    def clear(self) -> None:
        self._pending, self._undo, self._redo = None, [], []

    def _push(self, state: Any) -> None:
        self._undo.append(state)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()



class PhotoStudio:
    """The studio editor without drawing or DOM: frames and stamps on a canvas of ``width`` x ``height`` pixels, driven by pointer events, with undo.

    ``state`` is ``{"image", "frames", "selected_frame", "draft_color", "draft_shape", "stamps", "selected_stamp", "stamp_scale"}`` (``image`` is whatever
    identifies the photo; a frame is ``{"id", "rect", "shape", "color"}``, a stamp ``{"id", "emoji", "x", "y", "scale"}``); it is replaced, never changed in
    place, so history can keep the old ones. This is flutter_navigation_basic's PhotoRectCanvas and the page's edit handlers as one state machine
    (as there, the stamp-size slider changes the document without an undo step)."""

    def __init__(self, width: float = 760, height: float = 280):
        self.width, self.height = width, height
        self.state: dict[str, Any] = {"image": None, "frames": [], "selected_frame": None, "draft_color": PHOTO_COLORS[0][1], "draft_shape": None,
                                      "stamps": [], "selected_stamp": None, "stamp_scale": 1}
        self.history = PhotoHistory()
        self.pending_emoji: str | None = None
        self._serial = 0
        self._active: Any = None
        self._reset_gesture()
        self._tap_down: tuple[float, float] | None = None

    def _reset_gesture(self) -> None:
        self._create_origin = self._creating = self._live = self._editing = self._handle = self._dragging_stamp = None
        self._gesture_stamps = self._last_spray = self._last = None
        self._spraying = self._started = self._placed = self._dragging = False

    def _set(self, **changes: Any) -> None:
        self.state = {**self.state, **changes}

    def _new_id(self, kind: str) -> str:
        self._serial += 1
        return f"{kind}-{self._serial}"

    def _frame(self, frame_id: str | None) -> dict[str, Any] | None:
        return next((f for f in self.state["frames"] if f["id"] == frame_id), None) if frame_id else None

    # --- what the canvas tells its owner (the page's handlers)
    def _frames_changed(self, frames: list[dict[str, Any]]) -> None:
        selected = self.state["selected_frame"]
        self._set(frames=frames, **({"selected_frame": None} if selected is not None and not any(f["id"] == selected for f in frames) else {}))

    def _select_frame(self, frame_id: str | None) -> None:
        self._set(selected_frame=frame_id)

    def _stamps_changed(self, stamps: list[dict[str, Any]]) -> None:
        known = {s["id"] for s in self.state["stamps"]}
        added = [s for s in stamps if s["id"] not in known]
        changes: dict[str, Any] = {"stamps": stamps}
        if added:
            changes.update(selected_stamp=added[-1]["id"], stamp_scale=added[-1]["scale"])
        elif self.state["selected_stamp"] is not None:
            match = [s for s in stamps if s["id"] == self.state["selected_stamp"]]
            if match:
                changes["stamp_scale"] = match[0]["scale"]
        self._set(**changes)

    def _select_stamp(self, stamp_id: str | None) -> None:
        changes: dict[str, Any] = {"selected_stamp": stamp_id}
        match = [s for s in self.state["stamps"] if s["id"] == stamp_id] if stamp_id is not None else []
        if match:
            changes["stamp_scale"] = match[0]["scale"]
        self._set(**changes)

    def _edit_start(self) -> None:
        if not self._started:
            self._started = True
            self.history.begin_gesture(self.state)

    # --- pointer events
    def pointer_down(self, pointer: Any, x: float, y: float) -> None:
        self._tap_down, self._placed, self._gesture_stamps = (x, y), False, list(self.state["stamps"])
        self._spraying, self._last_spray, self._active, self._dragging = False, None, pointer, False

    def pointer_move(self, pointer: Any, x: float, y: float) -> None:
        if self._active is None or self._active != pointer:
            return
        if not self._dragging:
            down = self._tap_down
            if down is None or _photo_distance(x - down[0], y - down[1]) < 4:
                return
            self._dragging = True
            self._pan_start(*down)
        self._pan_update(x, y)

    def pointer_up(self, pointer: Any) -> None:
        if self._active is not None and pointer != self._active:
            return
        local, was_dragging = self._tap_down, self._dragging
        self._active, self._dragging = None, False
        if was_dragging:
            self._finish()
        elif local is not None and not self._placed:
            self._tap(*local)
            if self._started or self._dragging_stamp is not None:
                self._finish()
        self._tap_down = None

    def pointer_cancel(self, pointer: Any) -> None:
        if self._active is not None and pointer != self._active:
            return
        self._tap_down, self._active = None, None
        if self._dragging or self._started or self._dragging_stamp is not None:
            self._dragging = False
            self._finish()
        else:
            self._gesture_stamps, self._spraying, self._last_spray, self._placed, self._dragging = None, False, None, False, False

    def _place_pending(self, x: float, y: float, repeated: bool = False) -> None:
        if not self.pending_emoji or (not repeated and self._placed):
            return
        self._edit_start()
        if not repeated:
            self._placed = True
        stamp_id = self._new_id("stamp")
        stamps = (self._gesture_stamps if self._gesture_stamps is not None else self.state["stamps"]) + [
            {"id": stamp_id, "emoji": self.pending_emoji, "x": _photo_clamp(x / self.width, 0.0, 1.0), "y": _photo_clamp(y / self.height, 0.0, 1.0), "scale": 1}]
        self._gesture_stamps = stamps
        self._stamps_changed(stamps)
        self._select_stamp(stamp_id)

    def _tap(self, x: float, y: float) -> None:
        stamp = photo_hit_stamp(self.state["stamps"], self.width, self.height, x, y)
        if stamp:
            self._select_stamp(stamp["id"])
        elif self.pending_emoji and not self._placed:
            self._place_pending(x, y)
        else:
            frame = photo_hit_frame(self.state["frames"], self.width, self.height, x, y)
            self._select_frame(frame["id"] if frame else None)

    def _pan_start(self, x: float, y: float) -> None:
        w, h = self.width, self.height
        stamp = photo_hit_stamp(self.state["stamps"], w, h, x, y)
        if stamp:
            self._edit_start()
            self._dragging_stamp, self._handle, self._create_origin, self._creating, self._live = stamp["id"], None, None, None, None
            self._select_stamp(stamp["id"])
            self._last = (x, y)
            return
        if self.pending_emoji:
            if not self._placed:
                self._place_pending(x, y)
            self._spraying, self._last_spray = True, (x, y)
            self._dragging_stamp = self._handle = self._create_origin = self._creating = self._live = None
            self._last = (x, y)
            return
        frame = photo_hit_frame(self.state["frames"], w, h, x, y)
        if frame:
            self._edit_start()
            self._select_frame(frame["id"])
            self._create_origin = self._creating = self._live = None
            self._editing, self._handle, self._last = frame["id"], photo_hit_handle(frame["rect"], w, h, x, y) or "move", (x, y)
            return
        selected = self._frame(self.state["selected_frame"])
        if selected:
            handle = photo_hit_handle(selected["rect"], w, h, x, y)
            if handle:
                self._edit_start()
                self._create_origin = self._creating = self._live = None
                self._editing, self._handle, self._last = selected["id"], handle, (x, y)
                return
        if self.state["draft_shape"]:
            self._edit_start()
            nx, ny = _photo_clamp(x / w, 0.0, 1.0), _photo_clamp(y / h, 0.0, 1.0)
            self._create_origin, self._handle = (nx, ny), None
            self._creating = self._new_id("frame")
            self._live = {"id": self._creating, "rect": photo_rect_from_diagonal(nx, ny, nx, ny), "shape": self.state["draft_shape"], "color": self.state["draft_color"]}
            self._frames_changed([*self.state["frames"], self._live])
            self._select_frame(self._creating)
            self._last = (x, y)
            return
        self._select_frame(None)
        self._handle = self._create_origin = self._creating = self._live = None
        self._last = (x, y)

    def _pan_update(self, x: float, y: float) -> None:
        w, h = self.width, self.height
        if w <= 0 or h <= 0:
            return
        if self._spraying and self.pending_emoji:
            last = self._last_spray
            if last is None or _photo_distance(x - last[0], y - last[1]) >= 28:
                self._place_pending(x, y, repeated=True)
                self._last_spray = (x, y)
            return
        if self._dragging_stamp is not None:
            nx, ny = _photo_clamp(x / w, 0.0, 1.0), _photo_clamp(y / h, 0.0, 1.0)
            self._stamps_changed([{**s, "x": nx, "y": ny} if s["id"] == self._dragging_stamp else s for s in self.state["stamps"]])
            return
        if self._create_origin is not None and self._creating is not None:
            nx, ny = _photo_clamp(x / w, 0.0, 1.0), _photo_clamp(y / h, 0.0, 1.0)
            live = self._live or {"id": self._creating, "rect": PHOTO_INITIAL_RECT, "shape": self.state["draft_shape"] or "rectangle", "color": self.state["draft_color"]}
            self._live = {**live, "rect": photo_rect_from_diagonal(self._create_origin[0], self._create_origin[1], nx, ny)}
            self._frames_changed([f for f in self.state["frames"] if f["id"] != self._creating] + [self._live])
            return
        editing = self._frame(self._editing) or self._frame(self.state["selected_frame"])
        if self._handle is None or self._last is None or editing is None:
            return
        dx, dy = (x - self._last[0]) / w, (y - self._last[1]) / h
        self._last = (x, y)
        self._replace_frame({**editing, "rect": photo_rect_resized(editing["rect"], self._handle, dx, dy)})

    def _replace_frame(self, updated: dict[str, Any]) -> None:
        self._frames_changed([updated if f["id"] == updated["id"] else f for f in self.state["frames"]])

    def _finish(self) -> None:
        if self._creating is not None and self._live is not None:
            self._frames_changed([f for f in self.state["frames"] if f["id"] != self._creating] + [{**self._live, "rect": photo_rect_sanitized(self._live["rect"])}])
        had_edit = self._started
        self._reset_gesture()
        if had_edit:
            self.history.end_gesture(self.state)

    # --- the page's other edit actions: each is one undo step when it changes the document
    def _change(self, **changes: Any) -> None:
        before = self.state
        self._set(**changes)
        self.history.record_change(before, self.state)

    def set_image(self, image: Any) -> None:
        self._change(image=image)

    def set_shape(self, shape: str | None) -> None:
        if shape is not None and shape not in PHOTO_SHAPES:
            raise ValueError("unknown shape")
        if self.state["draft_shape"] == shape and (shape is None or self.pending_emoji is None):
            return
        if shape is not None:
            self.pending_emoji = None
        self._change(draft_shape=shape)

    def set_color(self, color: str) -> None:
        selected = self._frame(self.state["selected_frame"])
        if self.state["draft_color"] == color and (selected is None or selected["color"] == color):
            return
        self._change(draft_color=color, frames=[{**f, "color": color} if f["id"] == self.state["selected_frame"] else f for f in self.state["frames"]])

    def arm_stamp(self, text: str | None) -> None:
        """Arm ``text`` for placing (arming the armed one disarms it); arming drops the frame tool."""
        text = (text or "").strip() or None
        if text is None:
            return
        self.pending_emoji = None if self.pending_emoji == text else text
        if self.pending_emoji is not None and self.state["draft_shape"] is not None:
            self._change(draft_shape=None)

    def set_stamp_scale(self, scale: float) -> None:
        scale = _photo_clamp(scale, 0.4, 3.0)
        selected = self.state["selected_stamp"]
        self._set(stamp_scale=scale, **({"stamps": [{**s, "scale": scale} if s["id"] == selected else s for s in self.state["stamps"]]} if selected is not None else {}))

    def reset_selected_frame(self) -> None:
        selected = self.state["selected_frame"]
        if self._frame(selected):
            self._change(frames=[{**f, "rect": dict(PHOTO_INITIAL_RECT)} if f["id"] == selected else f for f in self.state["frames"]])

    def delete_selected_frame(self) -> None:
        selected = self.state["selected_frame"]
        if selected is not None:
            self._change(frames=[f for f in self.state["frames"] if f["id"] != selected], selected_frame=None)

    def nudge(self, dx: float, dy: float) -> None:
        """Move the selected frame by ``dx``, ``dy`` (fractions of the canvas): one undo step (the keyboard's way to do what a drag does)."""
        frame = self._frame(self.state["selected_frame"])
        if frame:
            self._change(frames=[{**frame, "rect": photo_rect_translated(frame["rect"], dx, dy)} if f["id"] == frame["id"] else f for f in self.state["frames"]])

    def undo(self) -> bool:
        snapshot = self.history.undo(self.state)
        if snapshot is None:
            return False
        self.state = snapshot
        if snapshot["draft_shape"] is not None:
            self.pending_emoji = None
        return True

    def redo(self) -> bool:
        snapshot = self.history.redo(self.state)
        if snapshot is None:
            return False
        self.state = snapshot
        if snapshot["draft_shape"] is not None:
            self.pending_emoji = None
        return True


# What "Check this browser" decodes: tiny pictures, each a real file, as literals (a PNG built with zlib is not byte-stable across zlib builds, and a generated page must be).
# Most are flutter_navigation_basic's import_compat fixtures, copied unchanged (see tests/fixtures/photo_import_cases.json); the 2 x 2 PNG is photo_png(2, 2, ...) and the
# AVIF was made with Pillow for this page, because the fixture's AVIF is only a header.
_PHOTO_PROBE_DATA = {
 "png": "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP4z8DwHwyBNBAwNAAAR0sIeRPxYNAAAAAASUVORK5CYII=",
 "jpeg": "/9j//gAQTGF2YzYwLjMxLjEwMgD/2wBDAAgEBAQEBAUFBQUFBQYGBgYGBgYGBgYGBgYHBwcICAgHBwcGBgcHCAgICAkJCQgICAgJCQoKCgwMCwsODg4RERT/xABQAAEBAQEAAAAAAAAAAAAAAAAABwgGAQEBAQEAAAAAAAAAAAAAAAAABggHEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAAAAAAAAAAAAAAAAAA/8AAEQgAIABAAwESAAISAAMSAP/aAAwDAQACEQMRAD8A4sSg7+AAAAAAKUJYYVAAAAAAEGG0x1YAAAAAAbFGABVAAAAAAD//2Q==",
 "jpeg_exif_orientation_6": "/9j/4QAiRXhpZgAASUkqAAgAAAABABIBAwABAAAABgAAAAAAAAD//gAQTGF2YzYwLjMxLjEwMgD/2wBDAAgEBAQEBAUFBQUFBQYGBgYGBgYGBgYGBgYHBwcICAgHBwcGBgcHCAgICAkJCQgICAgJCQoKCgwMCwsODg4RERT/xABQAAEBAQEAAAAAAAAAAAAAAAAABwgGAQEBAQEAAAAAAAAAAAAAAAAABggHEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAAAAAAAAAAAAAAAAAA/8AAEQgAIABAAwESAAISAAMSAP/aAAwDAQACEQMRAD8A4sSg7+AAAAAAKUJYYVAAAAAAEGG0x1YAAAAAAbFGABVAAAAAAD//2Q==",
 "webp_lossy": "UklGRoIAAABXRUJQVlA4IHYAAABQBgCdASpAACAAPl0kjUWjoiEb9AA4BcSyAF2c4H8A/ADr9L1cR/CX9a+hV0C7S/rXnfYZlc/usKOFAAD+8UtI8Ke2U+JMqADr6gEMBX9RuhPomG0KLT/0TTbCl0eZGQ2Z4i+2j3+LaRJv+r4rtacAcZGAAAAA",
 "webp_lossless": "UklGRjgAAABXRUJQVlA4TCwAAAAvP8AHAB8gEEjaH3qN+RcQFPk/2vwHXySASIDEk570pIlMjej/BByLvoJDXw==",
 "webp_alpha": "UklGRjYAAABXRUJQVlA4TCkAAAAvB8AAEB8gEEjaH3oNAUGR/6PNv4Cg6LrlYjaRgkCAMGnSpI2I/kfELgA=",
 "gif": "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAEALAAAAAABAAEAAAIBRAA7",
 "heic": "AAAAHGZ0eXBoZWljAAAAAG1pZjFoZWljbWlhZgAAAX1tZXRhAAAAAAAAACFoZGxyAAAAAAAAAABwaWN0AAAAAAAAAAAAAAAAAAAAAA5waXRtAAAAAAABAAAAImlsb2MAAAAAREAAAQABAAAAAAGhAAEAAAAAAAAAYwAAACNpaW5mAAAAAAABAAAAFWluZmUCAAAAAAEAAGh2YzEAAAAA/WlwcnAAAADdaXBjbwAAAHZodmNDAQNwAAAAAAAAAAAAHvAA/P34+AAADwMgAAEAGEABDAH//wNwAAADAJAAAAMAAAMAHroCQCEAAQAqQgEBA3AAAAMAkAAAAwAAAwAeoCCBBZbq5Ka5uAhoMCAAAAMAIAAAAwAhIgABAAZEAcFzwIkAAAAUaXNwZQAAAAAAAABAAAAAQAAAAChjbGFwAAAAQAAAAAEAAAAgAAAAAQAAAAAAAAAC////4AAAAAIAAAATY29scm5jbHgAAQANAAaAAAAAEHBpeGkAAAAAAwgICAAAABhpcG1hAAAAAAAAAAEAAQWBAoMEBQAAAGttZGF0AAAAXygBr1j5E5Jf/841//lF8h7ByM+7/3QH8+3BLf4tTRXmYX7xhn64w/5IuhJ74fTz9+CxFd0dzjN9w2//kcWKjOncaAIv96SBBDuEQLmUsUYIAre12Xc9l0tF4HrCDd+A",
 "avif": "AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADrbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAAAAAAAOcGl0bQAAAAAAAQAAAB5pbG9jAAAAAEQAAAEAAQAAAAEAAAETAAAALgAAAChpaW5mAAAAAAABAAAAGmluZmUCAAAAAAEAAGF2MDFDb2xvcgAAAABqaXBycAAAAEtpcGNvAAAAFGlzcGUAAAAAAAAAEAAAAAgAAAAQcGl4aQAAAAADCAgIAAAADGF2MUOBAAwAAAAAE2NvbHJuY2x4AAEADQAGgAAAABdpcG1hAAAAAAAAAAEAAQQBAoMEAAAANm1kYXQSAAoIGAy/tEBDQaEyIBrHh4XhzDDDAoAAAOAgJZwnn85pHxi+mx2+nQE2llC5"
}
_PHOTO_PROBE_MIME = {"png": "image/png", "jpeg": "image/jpeg", "jpeg_exif_orientation_6": "image/jpeg", "webp_lossy": "image/webp", "webp_lossless": "image/webp",
                     "webp_alpha": "image/webp", "gif": "image/gif", "avif": "image/avif", "heic": "image/heic"}


def photo_probes() -> list[dict[str, str]]:
    """The pictures the page tries to decode, as ``{"id", "mime", "data"}`` (Base64), in a fixed order."""
    return [{"id": key, "mime": _PHOTO_PROBE_MIME[key], "data": _PHOTO_PROBE_DATA[key]} for key in _PHOTO_PROBE_MIME]


def photo_evidence(user_agent: str = "", outcomes: dict[str, str] | None = None, features: dict[str, Any] | None = None, verified_at: str = "",
                   exif_applied_by_engine: bool | None = None) -> dict[str, Any]:
    """What the page measured about a browser, shaped like flutter_navigation_basic's ``evidence/*.json`` (schema 2). Only the browser-canvas loader is
    measured; an outcome must come from the shared vocabulary."""
    outcomes = outcomes or {}
    for outcome in outcomes.values():
        if outcome not in PHOTO_OUTCOMES:
            raise ValueError(f"unknown outcome: {outcome!r}")
    return {"schemaVersion": 2, "environmentId": "web_ui_photo_studio", "runtime": "browser", "userAgent": user_agent, "verifiedAt": verified_at,
            "entryPoint": "loader_browser_canvas_adapter", "exifOrientationAppliedByEngine": exif_applied_by_engine,
            "notes": "Measured by the web-ui Photo Studio page (Check this browser). Only loader_browser_canvas_adapter is measured; every other entry point stays "
                     "not_verified. A browser emulation is not a device.",
            "outcomes": {key: {"loader_browser_canvas_adapter": value} for key, value in outcomes.items()}, "features": features or {}}


_CSS["photo.css"] = ("@layer components{.ui-photo h3{margin:24px 0 8px}.ui-photo-status{margin:8px 0 0;font-weight:600}.ui-photo-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:8px 0;padding:0;border:0}"
                     ".ui-photo-bar legend{padding:0 0 4px}.ui-photo-radio,.ui-photo-file{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}"
                     ".ui-photo-choice label{display:inline-flex;align-items:center;gap:8px;padding:4px 16px;border:1px solid var(--ui-border);border-radius:var(--ui-radius);cursor:pointer}.ui-photo-bar label.ui-button{cursor:pointer}"
                     ".ui-photo-radio:checked+label{background:var(--ui-accent);color:var(--ui-bg)}.ui-photo-radio:focus-visible+label,.ui-photo-file:focus-visible+label{outline:2px solid var(--ui-fg);outline-offset:2px}"
                     ".ui-photo-dot{display:inline-block;width:16px;height:16px;border:1px solid var(--ui-fg);border-radius:50%;background:var(--dot)}"
                     + "".join(f".ui-photo-c-{name.lower()}{{--dot:{value}}}" for name, value in PHOTO_COLORS) +
                     ".ui-photo-stagewrap{margin:16px 0}.ui-photo-stage{display:block;max-width:100%;border:1px solid var(--ui-border);border-radius:var(--ui-radius);touch-action:none;"
                     "-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;cursor:crosshair}.ui-photo-stage:focus-visible{outline:2px solid var(--ui-accent);outline-offset:2px}"
                     ".ui-photo-stamps{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:8px 0}.ui-photo-stamps .ui-input{flex:1 1 128px;min-width:0}"
                     ".ui-photo [aria-pressed=\"true\"]{background:var(--ui-accent);color:var(--ui-bg)}.ui-photo pre{white-space:pre-wrap;overflow-wrap:anywhere}"
                     ".ui-photo-live{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip-path:inset(50%)}.ui-photo details{margin:16px 0}.ui-photo summary{cursor:pointer;padding:8px 0}}") 


def photo_html() -> str:
    """The photo studio as semantic HTML: import, a canvas for frames and stamps, tools, history, geometry text, export and a check of what this browser can do."""
    probes = escape(json.dumps(photo_probes(), separators=(",", ":")), quote=True)
    choice = lambda name, value, label, checked=False, extra="": (
        f'<span class="ui-photo-choice"><input class="ui-photo-radio" type="radio" id="photo-{name}-{value}" name="photo-{name}" value="{value}"{" checked" if checked else ""}>'
        f'<label for="photo-{name}-{value}">{extra}{escape(label)}</label></span>')
    shapes = choice("shape", "none", "None", True) + "".join(choice("shape", s, s.capitalize()) for s in PHOTO_SHAPES)
    colors = "".join(choice("color", value, name, i == 0, f'<span class="ui-photo-dot ui-photo-c-{name.lower()}"></span>') for i, (name, value) in enumerate(PHOTO_COLORS))
    stamps = "".join(f'<button class="ui-button" type="button" data-stamp="{escape(s, quote=True)}" aria-pressed="false" aria-label="Stamp {escape(s)}">{escape(s)}</button>' for s in PHOTO_STAMPS)
    return (f'<section class="ui-panel ui-photo" id="photo" data-ui-photo data-probes="{probes}"><h2>Photo studio</h2>'
            '<p class="ui-muted">Frames and marks on a photo. The photo stays in this page: nothing is saved or sent. Export is PNG only.</p>'
            '<p class="ui-photo-status" role="status" aria-live="polite" data-status>Select an image or paste here</p><p class="ui-muted" data-meta></p>'
            '<div class="ui-photo-bar"><input class="ui-photo-file" type="file" id="photo-file" accept="image/*" data-file><label class="ui-button" for="photo-file">Import image</label>'
            '<button class="ui-button" type="button" data-paste>Paste photo</button><button class="ui-button" type="button" data-retry hidden>Retry</button>'
            '<button class="ui-button" type="button" data-clear disabled>Clear photo</button></div>'
            '<details class="ui-photo-help"><summary>How to edit</summary><p class="ui-muted">You can paste (Ctrl/Cmd+V) or drop an image anywhere on this panel. Choose a frame tool, then drag '
            'to make a frame. Drag inside a frame to move it; drag its corners or edges to resize. With the canvas focused: arrow keys move the selected frame (Shift for bigger steps), '
            'Delete removes it, Ctrl/Cmd+Z undoes.</p></details>'
            '<div class="ui-photo-stagewrap"><canvas class="ui-photo-stage" data-stage width="760" height="280" tabindex="0" role="img" aria-label="Photo canvas"></canvas></div>'
            f'<fieldset class="ui-photo-bar"><legend>Frame tool</legend>{shapes}</fieldset><fieldset class="ui-photo-bar"><legend>Frame colour</legend>{colors}</fieldset>'
            f'<h3>Stamps</h3><div class="ui-photo-stamps">{stamps}</div>'
            '<div class="ui-photo-stamps"><label for="photo-custom">Custom stamp</label><input class="ui-input" id="photo-custom" data-custom maxlength="12" placeholder="Emoji or short text" autocomplete="off">'
            '<button class="ui-button" type="button" data-arm aria-pressed="false">Arm stamp</button></div>'
            '<div class="ui-photo-stamps"><label for="photo-scale">Stamp size</label><input type="range" id="photo-scale" data-scale min="0.4" max="3" step="0.1" value="1"> <output data-scale-out>1.0</output></div>'
            '<div class="ui-photo-bar"><button class="ui-button" type="button" data-undo disabled>Undo</button><button class="ui-button" type="button" data-redo disabled>Redo</button>'
            '<button class="ui-button" type="button" data-next>Select next frame</button><button class="ui-button" type="button" data-reset disabled>Reset selected frame</button>'
            '<button class="ui-button" type="button" data-delete disabled>Delete frame</button></div>'
            '<h3>Geometry</h3><pre class="ui-output" data-geometry>No frame selected.</pre>'
            '<div class="ui-photo-bar"><button class="ui-button" type="button" data-copy-rect>Copy rectangle</button><button class="ui-button" type="button" data-copy-csv>Copy as CSV</button></div>'
            '<div class="ui-photo-bar"><button class="ui-button" type="button" data-export>Save PNG</button><button class="ui-button" type="button" data-share hidden>Share PNG</button></div>'
            '<p class="ui-photo-live" role="status" aria-live="polite" data-live></p>'
            '<details class="ui-photo-check"><summary>This browser</summary><p class="ui-muted">Tries to decode a few tiny pictures and reports what this browser can do, as JSON in the same shape as the Flutter app\'s import evidence. '
            'It measures this browser only; it is not a test of any other device.</p><button class="ui-button" type="button" data-check>Check this browser</button>'
            '<pre class="ui-output" data-check-out></pre></details></section>')


def photo_document(*, theme: str = "modern") -> str:
    """A single-file page for the photo studio."""
    return render_document(trusted_html='<main class="ui-page">' + photo_html() + "</main>" + module_script(_JS["photo.js"]), title="Photo studio", theme=theme, css=bundled_css())


# --- Platform adapters: where each page is checked on a real browser (browser-test-kit's btk-platform-adapter/1) --------------------------------
# browser-test-kit's platform_probe.py opens a page in an OS x browser x device environment, checks that its key elements fit the screen without overflow, overlap
# or clipping at several widths, and that a real click (a tap on touch profiles) changes one thing the page promises. The adapter says only what is app-owned:
# the selectors and that one postcondition. Written here from Python (nothing is committed as JSON); ``--btk-adapter ID --url URL`` prints one. Pages that only
# link elsewhere (the front page, the examples index) have no state to observe and no adapter.

BTK_ADAPTER_BASE = "http://127.0.0.1:8000/examples/"
BTK_ADAPTERS: dict[str, dict[str, Any]] = {
    "web-ui-showcase": {"page": "showcase.html", "elements": ["#showcase .ui-shell-title", "#showcase [data-ui-theme-switch]", "#showcase [data-ui-toggle]"],
                        "click": {"target": "#showcase [data-ui-toggle]", "observe": "#showcase [data-ui-toggle]", "attribute": "aria-label", "before": "Favorite this page", "after": "Remove from favorites"}},
    "web-ui-clipboard-shelf": {"page": "clipboard-shelf.html", "elements": ["#shelf h2", "#shelf-input", "#shelf [data-shelf-add]", "#shelf [data-shelf-status]"],
                               "click": {"target": "#shelf [data-shelf-add]", "observe": "#shelf [data-shelf-status]", "attribute": "textContent", "before": "Nothing on the shelf yet.", "after": "Nothing to add."}},
    "web-ui-door": {"page": "door.html", "elements": ["#door h2", "#door-select", "#door [data-door-draw]"],
                    "click": {"target": "#door [data-door-draw]", "observe": "#door", "attribute": "data-door-draws", "before": "0", "after": "1"}},
    "web-ui-composition-studio": {"page": "composition-studio.html", "elements": ["#studio h2", "#studio-bpm", "#studio [data-run]", "#studio [data-tap]"],
                                  "click": {"target": "#studio [data-run]", "observe": "#studio [data-run]", "attribute": "aria-pressed", "before": "false", "after": "true"}},
    "web-ui-coordinates": {"page": "coordinates.html", "elements": ["#coord h2", "#coord-lat", "#coord-lon", "#coord-url", "#coord [data-use-url]"],
                           "click": {"target": "#coord [data-use-url]", "observe": "#coord [data-status]", "attribute": "textContent", "before": "Valid.",
                                     "after": "Could not find latitude/longitude in that Maps URL."}},
    "web-ui-photo-studio": {"page": "photo-studio.html", "elements": ["#photo h2", "#photo [data-status]", "#photo label[for=\"photo-file\"]", "#photo [data-paste]", "#photo .ui-photo-help summary"],
                            "click": {"target": "#photo .ui-photo-help summary", "observe": "#photo .ui-photo-help", "attribute": "open", "before": None, "after": ""}},
}


def btk_adapter(adapter_id: str, url: str | None = None) -> dict[str, Any]:
    """The ``btk-platform-adapter/1`` for one of ``BTK_ADAPTERS``; ``url`` replaces the default local address (``BTK_ADAPTER_BASE`` + the page)."""
    try:
        spec = BTK_ADAPTERS[adapter_id]
    except KeyError:
        raise ValueError(f"unknown adapter: {adapter_id!r}; one of {', '.join(sorted(BTK_ADAPTERS))}") from None
    return {"schema": "btk-platform-adapter/1", "id": adapter_id, "url": url or BTK_ADAPTER_BASE + spec["page"], "elements": list(spec["elements"]), "click": dict(spec["click"])}


# --- Composition studio: chord theory, metronome timing, tap tempo, note sequences and a seeded song seed ---------------------------------
# Absorbs flutter_navigation_basic's lib/features/composition_generator/domain (chord_theory.dart, metronome_timing.dart, note_sequence.dart,
# song_seed_generator.dart) and lib/data/composer.dart. Its Dart tests are the golden values below. Python is the reference; ``composition.js`` must agree.
# Deliberate differences: separators are ASCII whitespace and commas only, rounding is floor(x + 0.5) in both languages, and the seed uses mulberry32.

FLAT_KEYS = ("C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B")
SHARP_KEYS = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
SELECTABLE_KEYS = ("C", "C♯", "D♭", "D", "D♯", "E♭", "E", "F", "F♯", "G♭", "G", "G♯", "A♭", "A", "A♯", "B♭", "B")
CHORD_MODIFIERS = ("triad", "6", "m6", "7", "maj7", "m7", "m7♭5", "sus2", "sus4", "add9", "add11", "dim", "aug")
_MAJOR_STEPS, _MINOR_STEPS = (0, 2, 4, 5, 7, 9, 11), (0, 2, 3, 5, 7, 8, 10)
_MAJOR_QUALITIES, _MINOR_QUALITIES = ("", "m", "m", "", "", "m", "dim"), ("m", "dim", "", "m", "m", "", "")
_LETTERS = "CDEFGAB"
_NATURALS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_CHORD_INTERVALS = {"triad": (0, 4, 7), "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
                    "m7♭5": (0, 3, 6, 10), "sus2": (0, 2, 7), "sus4": (0, 5, 7), "add9": (0, 4, 7, 14), "add11": (0, 4, 7, 17), "dim": (0, 3, 6), "aug": (0, 4, 8)}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}
METRONOME_MIN_BPM, METRONOME_MAX_BPM = 30, 300
SEED_KEYS = ("B♭", "B", "C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A")
SEED_MODES, SEED_TIMES = ("Major", "Minor"), ("4/4", "3/4", "6/8")
SEED_PROGRESSIONS = {"Major": ("I – V – vi – IV", "I – vi – IV – V", "ii – V – I – vi", "I – IV – V – IV"),
                     "Minor": ("i – VI – III – VII", "i – iv – VII – III", "i – VII – VI – VII", "i – iv – v – i")}


def pitch_class(note: str) -> int:
    """0..11 for a note name such as ``C``, ``F♯`` or ``B♭♭``; anything else is a ``ValueError``."""
    match = re.fullmatch(r"([A-G])([♯♭]*)", note) if isinstance(note, str) else None
    if not match:
        raise ValueError(f"unsupported note: {note!r}")
    return (_NATURALS[match.group(1)] + match.group(2).count("♯") - match.group(2).count("♭")) % 12


def prefers_sharps(key: str) -> bool:
    return "♯" in key or key in ("D", "E", "G", "A", "B")


def note_for_pitch_class(value: int, *, sharps: bool) -> str:
    return (SHARP_KEYS if sharps else FLAT_KEYS)[value % 12]


def transpose_key(key: str, semitones: int) -> str:
    return note_for_pitch_class(pitch_class(key) + semitones, sharps=prefers_sharps(key))


def fifth_neighbor(key: str, *, clockwise: bool) -> str:
    return transpose_key(key, 7 if clockwise else -7)


def _spell_pitch(letter: str, value: int) -> str:
    delta = (value % 12) - _NATURALS[letter]
    delta = delta - 12 if delta > 6 else delta + 12 if delta < -6 else delta
    if delta not in (-2, -1, 0, 1, 2):
        raise ValueError(f"cannot spell pitch {value % 12} on {letter}")
    return letter + {-2: "♭♭", -1: "♭", 0: "", 1: "♯", 2: "♯♯"}[delta]


def scale(key: str, *, minor: bool) -> list[str]:
    """The seven notes of the scale, one letter each (``F♯`` major ends ``E♯``, not ``F``)."""
    root, first = pitch_class(key), _LETTERS.find(key[:1])
    if first < 0:
        raise ValueError(f"unsupported root letter: {key!r}")
    steps = _MINOR_STEPS if minor else _MAJOR_STEPS
    return [_spell_pitch(_LETTERS[(first + degree) % 7], root + steps[degree]) for degree in range(7)]


def diatonic_chord(key: str, degree: int, *, minor: bool) -> str:
    if type(degree) is not int or not 1 <= degree <= 7:
        raise ValueError("degree must be 1 through 7")
    return scale(key, minor=minor)[degree - 1] + (_MINOR_QUALITIES if minor else _MAJOR_QUALITIES)[degree - 1]


def roman_degree(token: str) -> int | None:
    match = re.match(r"[ivIV]+", token.strip(" \t\r\n\f\v"))
    return _ROMAN.get(match.group(0).upper()) if match else None


def convert_roman_token(key: str, token: str, *, minor: bool) -> str:
    """A Roman-numeral chord (``vi``, ``IVsus2``, ``viiø7``) as a chord name in ``key``; anything not starting with a numeral is kept as written."""
    trimmed = token.strip(" \t\r\n\f\v")
    match = re.fullmatch(r"([ivIV]+)([\s\S]*)", trimmed)
    degree = roman_degree(trimmed) if match else None
    if not match or degree is None:
        return token
    root, base = scale(key, minor=minor)[degree - 1], diatonic_chord(key, degree, minor=minor)
    suffix = match.group(2).strip(" \t\r\n\f\v")
    if not suffix:
        return base
    if suffix in ("6", "7"):
        return base + suffix
    if suffix == "m6":
        return root + "m6"
    if suffix in ("maj7", "M7", "△7"):
        return root + "maj7"
    if suffix == "m7":
        return root + "m7"
    if suffix in ("m7♭5", "ø7"):
        return root + "m7♭5"
    if suffix in ("sus2", "sus4", "add9", "add11"):
        return root + suffix
    if suffix in ("dim", "°"):
        return root + "dim"
    if suffix in ("aug", "+"):
        return root + "aug"
    return base


def convert_progression(key: str, progression: str, *, minor: bool) -> list[str]:
    """``I V vi IV`` (separated by spaces, commas, dashes or bars) as chord names in ``key``."""
    for dash in "–—-|":
        progression = progression.replace(dash, " ")
    return [convert_roman_token(key, token, minor=minor) for token in re.split(r"[ \t\r\n\f\v,]+", progression) if token]


def apply_modifier(root: str, modifier: str) -> str:
    if modifier not in CHORD_MODIFIERS:
        raise ValueError(f"unsupported chord modifier: {modifier!r}")
    return root if modifier == "triad" else root + modifier


def chord_tones(root: str, modifier: str) -> list[str]:
    if modifier not in _CHORD_INTERVALS:
        raise ValueError(f"unsupported chord modifier: {modifier!r}")
    start, sharps = pitch_class(root), prefers_sharps(root)
    return [note_for_pitch_class(start + interval, sharps=sharps) for interval in _CHORD_INTERVALS[modifier]]


def normalized_inversion(modifier: str, inversion: int) -> int:
    """0..3 as the studio's four buttons; a triad has no third inversion, so that slot repeats the first."""
    if type(inversion) is not int or not 0 <= inversion <= 3:
        raise ValueError("inversion must be 0 through 3")
    count = len(_CHORD_INTERVALS[modifier])
    return inversion if inversion < count else 1 if count == 3 and inversion == 3 else inversion % count


def chord_with_inversion(root: str, modifier: str, inversion: int) -> str:
    chord, number = apply_modifier(root, modifier), normalized_inversion(modifier, inversion)
    return chord if number == 0 else f"{chord}/{chord_tones(root, modifier)[number]}"


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def beat_micros(bpm: int) -> int:
    """Microseconds in one beat; ``bpm`` is held to 30..300."""
    return _round_half_up(60_000_000 / min(max(bpm, METRONOME_MIN_BPM), METRONOME_MAX_BPM))


def subdivision_micros(bpm: int, per_beat: int) -> int:
    if per_beat <= 0:
        raise ValueError("subdivisions per beat must be positive")
    return _round_half_up(beat_micros(bpm) / per_beat)


def bar_micros(bpm: int, beats: int) -> int:
    if beats <= 0:
        raise ValueError("beats per bar must be positive")
    return beat_micros(bpm) * beats


def metronome_position(elapsed_micros: int, bpm: int, beats_per_bar: int, per_beat: int) -> tuple[int, int, float]:
    """``(beat index in the bar, subdivision index in the beat, phase 0..1 within the subdivision)`` from elapsed time, never from a frame count."""
    if beats_per_bar <= 0 or per_beat <= 0:
        raise ValueError("beats per bar and subdivisions must be positive")
    unit, elapsed = subdivision_micros(bpm, per_beat), max(elapsed_micros, 0)
    steps = elapsed // unit
    return (steps // per_beat) % beats_per_bar, steps % per_beat, (elapsed % unit) / unit


def duration_label(micros: int) -> str:
    """``500 ms`` below a second, ``2.00 s`` from a second on; rounded half up on integers, so every language prints the same."""
    if micros >= 1_000_000:
        hundredths = _round_half_up(micros / 10_000)
        return f"{hundredths // 100}.{hundredths % 100:02d} s"
    return f"{_round_half_up(micros / 1000)} ms"


def tap_tempo(taps: list[int], tap: int, *, reset_gap: int = 2_000_000, max_intervals: int = 5) -> tuple[list[int], int | None]:
    """Add a tap (microseconds) and give ``(taps kept, bpm or None)``: the average of the last intervals, 30..300; a gap over two seconds starts again."""
    kept = [] if taps and tap - taps[-1] > reset_gap else list(taps)
    kept.append(tap)
    if len(kept) > max_intervals + 1:
        kept.pop(0)
    if len(kept) < 2:
        return kept, None
    average = (kept[-1] - kept[0]) / (len(kept) - 1)
    if average <= 0:
        return kept, None
    return kept, min(max(_round_half_up(60_000_000 / average), METRONOME_MIN_BPM), METRONOME_MAX_BPM)


def parse_notes(text: str) -> list[str]:
    """Note tokens like ``C3 d3 F#3 Gb3`` (letter, optional # b ♯ ♭, one octave digit, separated by spaces or commas) as ``C3 D3 F♯3 G♭3``."""
    notes = []
    for token in re.split(r"[ \t\r\n\f\v,]+", text):
        if not token:
            continue
        match = re.fullmatch(r"([A-Ga-g])([#b♯♭]?)(-?[0-9])", token)
        if not match:
            raise ValueError(f"invalid note: {token}")
        notes.append(match.group(1).upper() + {"#": "♯", "b": "♭"}.get(match.group(2), match.group(2)) + match.group(3))
    return notes


def notes_per_bar(beats_per_bar: int, beat_unit: int, note_unit: int) -> int:
    if note_unit not in (4, 8):
        raise ValueError("only quarter and eighth notes are supported")
    value = beats_per_bar * note_unit / beat_unit
    if value != int(value) or value <= 0:
        raise ValueError("the selected note value does not divide this bar evenly")
    return int(value)


def note_bars(notes: list[str], beats_per_bar: int, beat_unit: int, note_unit: int) -> list[list[str]]:
    size = notes_per_bar(beats_per_bar, beat_unit, note_unit)
    return [notes[start:start + size] for start in range(0, len(notes), size)]


def song_seed(seed: int, avoid: dict[str, Any] | None = None) -> dict[str, Any]:
    """A reproducible song seed (``tonic``, ``mode``, ``bpm`` 80..160, ``time``, ``progression``) from ``mulberry32(seed)``; differs from ``avoid`` if it can in 8 tries."""
    rng = mulberry32(seed)
    pick = lambda options: options[math.floor(next(rng) * len(options))]
    for _ in range(8):
        mode = pick(SEED_MODES)
        result = {"tonic": pick(SEED_KEYS), "mode": mode, "bpm": 80 + math.floor(next(rng) * 81), "time": pick(SEED_TIMES),
                  "progression": pick(SEED_PROGRESSIONS[mode])}
        if avoid is None or result != avoid:
            break
    return result


def song_seed_text(seed: dict[str, Any]) -> str:
    return f"Key: {seed['tonic']} {seed['mode']} · BPM: {seed['bpm']} · Time: {seed['time']} · Progression: {seed['progression']}"


_CSS["studio.css"] = ("@layer components{.ui-studio h3{margin:24px 0 8px}.ui-studio label{display:inline-block;margin:8px 8px 4px 0}"
                      ".ui-studio-bar{display:flex;flex-wrap:wrap;gap:8px 16px;margin:8px 0;padding:0;border:0}.ui-studio-bar legend{padding:0 0 4px}"
                      ".ui-studio-bar label{margin:0}.ui-studio-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:8px 0}"
                      ".ui-studio-row .ui-input{flex:1 1 192px;min-width:0}.ui-studio textarea.ui-input{width:100%;box-sizing:border-box}"
                      ".ui-beats{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.ui-beat{display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;"
                      "border:1px solid var(--ui-border);border-radius:50%}.ui-beat[data-on]{background:var(--ui-accent);color:var(--ui-bg)}"
                      ".ui-studio-bars{margin:8px 0;padding-left:24px}.ui-studio-bars li[data-error]{color:var(--ui-danger)}"
                      ".ui-studio-chords{margin:8px 0;overflow-wrap:anywhere}.ui-studio-degrees{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}}")


def studio_html() -> str:
    """The composition studio as semantic HTML: metronome, chord theory (keys, circle of fifths, progressions, chord builder), note sequence, song seed."""
    radios = lambda name, values, checked, label=lambda v: v: "".join(
        f'<label><input type="radio" name="{name}" value="{escape(str(v), quote=True)}"{" checked" if v == checked else ""}> {escape(label(v))}</label>' for v in values)
    keys = "".join(f'<option value="{k}">{k}</option>' for k in SELECTABLE_KEYS)
    mods = "".join(f'<option value="{escape(m, quote=True)}">{escape(m)}</option>' for m in CHORD_MODIFIERS)
    degrees = "".join(f'<option value="{i}">Degree {i}</option>' for i in range(1, 8))
    return ('<section class="ui-panel ui-studio" id="studio" data-ui-studio><h2>Composition studio</h2>'
            '<p class="ui-muted">Theory is computed from music rules, not stored. Python is the reference and this page gives the same answers.</p>'
            '<h3>Metronome</h3><div class="ui-studio-row"><label for="studio-bpm">Tempo</label>'
            '<input type="range" id="studio-bpm" min="30" max="300" value="120" data-bpm> <output data-bpm-out>120 BPM</output></div>'
            f'<fieldset class="ui-studio-bar"><legend>Time signature</legend>{radios("studio-sig", SEED_TIMES, "4/4")}</fieldset>'
            '<div class="ui-beats" data-beats role="img" aria-label="Beat indicator"></div><p class="ui-muted" data-beat-info></p>'
            '<div class="ui-studio-row"><button class="ui-button" type="button" data-run aria-pressed="false">Start</button>'
            '<button class="ui-button" type="button" data-tap>Tap tempo</button></div>'
            '<h3>Chord theory</h3><div class="ui-studio-row"><label for="studio-key">Key</label>'
            f'<select class="ui-input" id="studio-key" data-key>{keys}</select>'
            '<button class="ui-button" type="button" data-semi-down>Semitone down</button><button class="ui-button" type="button" data-semi-up>Semitone up</button></div>'
            f'<fieldset class="ui-studio-bar"><legend>Mode</legend>{radios("studio-mode", ("Major", "Minor"), "Major")}</fieldset>'
            '<div class="ui-studio-row"><span>Circle of fifths</span><button class="ui-button" type="button" data-fifth-left></button>'
            '<button class="ui-button" type="button" data-fifth-right></button></div>'
            '<div class="ui-studio-degrees" data-degrees></div>'
            '<div class="ui-studio-row"><label for="studio-prog">Progression (Roman numerals)</label>'
            '<input class="ui-input" id="studio-prog" data-prog value="I V vi IV" autocomplete="off"></div><p class="ui-studio-chords" data-prog-out></p>'
            f'<div class="ui-studio-row"><label for="studio-degree">Chord builder</label><select class="ui-input" id="studio-degree" data-degree>{degrees}</select>'
            f'<select class="ui-input" id="studio-mod" aria-label="Quality or extension" data-mod>{mods}</select></div>'
            f'<fieldset class="ui-studio-bar"><legend>Inversion</legend>{radios("studio-inv", (0, 1, 2, 3), 0, lambda v: ("Root", "1st", "2nd", "3rd")[v])}</fieldset>'
            '<p class="ui-studio-chords" data-chord></p>'
            '<h3>Note sequence</h3><div class="ui-studio-row"><label for="studio-notes">Notes</label>'
            '<select class="ui-input" id="studio-note-unit" aria-label="Note value" data-note-unit><option value="4">Quarter notes</option><option value="8" selected>Eighth notes</option></select></div>'
            '<textarea class="ui-input" id="studio-notes" rows="2" data-notes>C3 D3 C3 D3 G3 A3 G3 C4</textarea><ol class="ui-studio-bars" data-bars></ol>'
            '<h3>Song seed</h3><div class="ui-studio-row"><button class="ui-button" type="button" data-new-seed>New song seed</button></div>'
            '<p class="ui-studio-chords" data-seed-out>Press the button for a key, tempo, time signature and progression.</p></section>')


def studio_document(*, theme: str = "modern") -> str:
    """A single-file page for the composition studio."""
    return render_document(trusted_html='<main class="ui-page">' + studio_html() + "</main>" + module_script(_JS["composition.js"]), title="Composition studio",
                           theme=theme, css=bundled_css())


# --- Door-to-Door and emoji transitions: one emoji per page, a go/return notation, a seeded draw, a pull-down ----------------------------
# Absorbs flutter_navigation_basic's page identities (python/generate_page_identities.py, docs/testing/page-identities.md), its "A -> B / A <-> B"
# transition notation, Home discovery (python/home_discovery.py) and the Door-to-Door selector (tool_door_selector.dart, HomeDoorCatalog).
# Python is the reference; the page's ``door.js`` must agree, including the seeded draw.

DOOR_SCHEMA = "web-ui-door/1"
_DOOR_DROP = "︎️ \t\n\v\f\r\x1c\x1d\x1e\x1f\x85\xa0                　"
_DOOR_DROP_RE = re.compile("[" + _DOOR_DROP + "]")


def emoji_key(emoji: str) -> str:
    """An emoji as the notation compares it: spaces and variation selectors (text or emoji presentation) removed, so ``🗺️`` and ``🗺`` are one page."""
    return _DOOR_DROP_RE.sub("", emoji)


def _door_href(value: Any) -> str:
    """A target the Door may open: a relative path or an http(s) address; never ``//host``, ``javascript:`` and the like."""
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in value):
        raise ValueError("href must be a path or an http(s) address without spaces or controls")
    parts = urlsplit(value)
    if parts.scheme not in ("", "http", "https") or (not parts.scheme and (parts.netloc or value.startswith("//"))) or (parts.scheme and not parts.netloc):
        raise ValueError(f"href must be a relative path or an http(s) address: {value!r}")
    return value


def door_validate(spec: Any) -> dict[str, Any]:
    """Checked copy of a ``web-ui-door/1`` spec: ``pages`` (``emoji``, ``label``, ``href``, ``group`` of ``stable`` or ``discover``), optional ``current`` href,
    ``k`` pages drawn from the discoverable ones and the draw ``seed``. Two pages may not share an emoji (variation selectors and spaces do not count),
    nor an href."""
    if not isinstance(spec, dict) or spec.get("schema") != DOOR_SCHEMA:
        raise ValueError(f"expected schema {DOOR_SCHEMA}")
    if set(spec) - {"schema", "pages", "current", "k", "seed"}:
        raise ValueError("a door has schema, pages, current, k and seed")
    pages_in = spec.get("pages")
    if not isinstance(pages_in, list) or not 1 <= len(pages_in) <= 512:
        raise ValueError("a door lists 1..512 pages")
    seen_emoji: set[str] = set()
    seen_href: set[str] = set()
    pages = []
    for page in pages_in:
        if not isinstance(page, dict) or set(page) - {"emoji", "label", "href", "group"}:
            raise ValueError("a page has emoji, label, href and group")
        emoji = _world_emoji(page.get("emoji"))
        key = emoji_key(emoji)
        group = page.get("group", "stable")
        if not key or group not in ("stable", "discover"):
            raise ValueError("a page needs an emoji and a group of stable or discover")
        href = _door_href(page.get("href"))
        if key in seen_emoji or href in seen_href:
            raise ValueError(f"two pages share {'an emoji' if key in seen_emoji else 'an href'}: {emoji!r} {href!r}")
        seen_emoji.add(key)
        seen_href.add(href)
        pages.append({"emoji": emoji, "label": _world_text(page.get("label"), "label", 40), "href": href, "group": group})
    if not any(p["group"] == "stable" for p in pages):
        raise ValueError("a door needs at least one stable page (the first is Home)")
    current = spec.get("current")
    if current is not None and current not in seen_href:
        raise ValueError("current must be the href of one of the pages")
    discoverable = sum(p["group"] == "discover" for p in pages)
    k = _world_int(spec.get("k", 3), "k", 0, 8)
    if k > discoverable:
        raise ValueError(f"k is {k} but only {discoverable} pages can be drawn")
    return {"schema": DOOR_SCHEMA, "pages": pages, "current": current, "k": k, "seed": _world_int(spec.get("seed", 0), "seed", 0, 2**32 - 1)}


def emoji_path(notation: str, pages: list[dict[str, Any]]) -> list[str]:
    """Hrefs visited by ``A → B`` (go) and ``A ↔ B`` (go and come back), left to right, from the pages' emoji. Spaces and variation selectors are
    ignored; an unknown emoji raises ``ValueError`` and nothing is returned. ``🏠 → 🗺️ → 🌍 ↔ 🕶️`` visits all four pages and returns to 🌍."""
    by_key = {emoji_key(p["emoji"]): p["href"] for p in pages}
    parts = re.split("([→↔])", emoji_key(notation))
    path = [parts[0]]
    for arrow, there in zip(parts[1::2], parts[2::2]):
        path.extend([there] if arrow == "→" else [there, path[-1]])
    try:
        return [by_key[key] for key in path]
    except KeyError as error:
        raise ValueError(f"unknown page emoji: {error.args[0]!r}") from None


def mulberry32(seed: int):
    """The seeded generator both languages share (32-bit integer arithmetic, floats in [0, 1)): a draw is the same in Python and in the page."""
    a, mask = seed & 0xFFFFFFFF, 0xFFFFFFFF
    while True:
        a = (a + 0x6D2B79F5) & mask
        t = ((a ^ (a >> 15)) * (a | 1)) & mask
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & mask)) & mask) ^ t
        yield ((t ^ (t >> 14)) & mask) / 4294967296


def door_draw(seed: int, count: int, k: int) -> list[int]:
    """``k`` distinct indices out of ``count``, chosen by a partial shuffle driven by ``mulberry32(seed)``; the same seed always gives the same draw."""
    if not 0 <= k <= count:
        raise ValueError("k must be from 0 to count")
    rng, order = mulberry32(seed), list(range(count))
    for i in range(k):
        j = i + math.floor(next(rng) * (count - i))
        order[i], order[j] = order[j], order[i]
    return order[:k]


def door_options(spec: Any, seed: int | None = None) -> list[dict[str, Any]]:
    """The pull-down in order: the first stable page (Home), the drawn discoveries, then the other stable pages, each marked ``current`` or not."""
    door = door_validate(spec)
    stable = [p for p in door["pages"] if p["group"] == "stable"]
    found = [p for p in door["pages"] if p["group"] == "discover"]
    drawn = [found[i] for i in door_draw(door["seed"] if seed is None else seed, len(found), door["k"])]
    return [{**p, "current": p["href"] == door["current"], "drawn": p in drawn} for p in [stable[0], *drawn, *stable[1:]]]


def door_html(spec: Any) -> str:
    """The Door-to-Door pull-down, a way to try the transition notation, and the data the page script needs (escaped)."""
    door = door_validate(spec)
    options = "".join(f'<option value="{escape(o["href"], quote=True)}"{" selected disabled" if o["current"] else ""}>{escape(o["emoji"])} {escape(o["label"])}'
                      f'{" (current)" if o["current"] else ""}</option>' for o in door_options(door))
    data = escape(json.dumps({"pages": door["pages"], "k": door["k"], "seed": door["seed"], "current": door["current"]}, ensure_ascii=False, separators=(",", ":")), quote=True)
    return ('<section class="ui-panel ui-door" id="door" data-ui-door data-door-draws="0" data-door="' + data + '"><h2>Door-to-Door</h2>'
            '<p class="ui-muted">Jump to another tool without going Home first. Some entries are drawn at random; the same seed draws the same ones in Python and here.</p>'
            f'<label for="door-select">Door-to-Door tools</label><div class="ui-door-row"><select class="ui-input" id="door-select" data-door-select>{options}</select> '
            '<button class="ui-button" type="button" data-door-draw>Draw again</button></div>'
            '<p class="ui-muted" role="status" aria-live="polite" data-door-status>Pick a destination.</p>'
            '<h3>Transitions by emoji</h3><p class="ui-muted"><code>A → B</code> goes, <code>A ↔ B</code> goes and comes back. Spaces and variation selectors are ignored.</p>'
            '<label for="door-notation">Notation</label><input class="ui-input" id="door-notation" data-door-notation value="🏠 ↔ 🧭" autocomplete="off">'
            '<ol class="ui-door-path" data-door-path></ol><p class="ui-muted" role="status" data-door-note></p></section>')


def door_document(spec: Any, *, theme: str = "modern") -> str:
    """A single-file page for a door."""
    return render_document(trusted_html='<main class="ui-page">' + door_html(spec) + "</main>" + module_script(_JS["door.js"]), title="Door-to-Door",
                           theme=theme, css=bundled_css())


# --- Clipboard shelf: classify what was pasted, read image text strictly, build a prompt or a bundle -----------------------------------
# Absorbs flutter_navigation_basic's Clipboard Shelf and prompt workbench (lib/shared/widgets/clipboard_shelf.dart, clipboard_prompt_workbench.dart,
# lib/shared/clipboard/base64_image_bridge.dart). The image rules are checked against Ironmate's 19 Base64 cases
# (tests/fixtures/base64_bridge_cases.json, Ironmate@56020aef). Python is the reference; the page's ``shelf.js`` must give identical results.
# Deliberate differences from the Dart code: line-based Markdown rules (Dart's \s could run across lines) and ASCII-only whitespace.

SHELF_MAX_IMAGE_BYTES = 32 * 1024 * 1024
SHELF_KINDS = ("text", "url", "markdown", "image")
_SHELF_WS = " \t\r\n\f\v"
_SHELF_B64 = re.compile(r"[A-Za-z0-9+/]*={0,2}")
_SHELF_DATA_URL = re.compile(r"data:([a-z0-9.+-]+/[a-z0-9.+-]+)?((?:;[a-z0-9.+-]+=[a-z0-9.+-]+)*);base64,", re.I | re.A)
_SHELF_LINE_MD = re.compile(r"[ \t]{0,3}(?:#{1,6}[ \t]|[-*+][ \t]|>[ \t]|```)")
_SHELF_LINK_MD = re.compile(r"\[[^\]]+\]\([^)]+\)")
_SHELF_URL = re.compile(r"https?://[^ \t\r\n\f\v<>\"]+", re.I | re.A)


def _shelf_strip(text: str) -> str:
    """Strip one leading BOM, then Unicode whitespace (what ``str.strip`` and JavaScript's ``trim`` share, plus U+0085 and the file separators)."""
    return (text[1:] if text.startswith("﻿") else text).strip(" \t\n\r\f\v\x1c\x1d\x1e\x1f\x85\xa0        "
                                                                  "        　")


def _shelf_lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    return text.replace("\r", "\n").split("\n")


def shelf_classify(text: str) -> str:
    """``url`` for one http(s) address, ``markdown`` when a line starts like Markdown (heading, list, quote, fence) or a link appears,
    otherwise ``text``."""
    trimmed = _shelf_strip(text)
    if _SHELF_URL.fullmatch(trimmed):
        return "url"
    if any(_SHELF_LINE_MD.match(line) for line in _shelf_lines(text)) or _SHELF_LINK_MD.search(text):
        return "markdown"
    return "text"


def markdown_plain(text: str) -> str:
    """Markdown as plain text: markers dropped line by line, links as ``text (url)``, inline code, bold and strikethrough unwrapped."""
    out = []
    for line in _shelf_lines(text):
        line = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", line)
        line = re.sub(r"^[ \t]{0,3}>[ \t]?", "", line)
        line = re.sub(r"^[ \t]*[-*+][ \t]+", "", line)
        line = re.sub(r"^[ \t]*\d+[.)][ \t]+", "", line)
        out.append("" if re.fullmatch(r"[ \t]*```[^\n]*", line) else line)
    text = "\n".join(out)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"~~([^~\n]+)~~", r"\1", text)
    return _shelf_strip(text)


def shelf_max_chars(max_bytes: int) -> int:
    """The most Base64 characters ``max_bytes`` decoded bytes can need, ``=`` padding included."""
    return 4 * ((max_bytes + 2) // 3)


def looks_like_image(text: str, min_chars: int = 80) -> bool:
    """Whether pasted text should be tried as an image: an ``image`` data URL (any letter case) or standard Base64, possibly wrapped."""
    text = _shelf_strip(text)
    if text[:11].lower() == "data:image/":
        return True
    compact = re.sub(r"[ \t\r\n\f\v]+", "", text)
    return len(compact) >= min_chars and len(compact) % 4 == 0 and _SHELF_B64.fullmatch(compact) is not None


def decode_image_text(text: str, max_bytes: int = SHELF_MAX_IMAGE_BYTES) -> dict[str, Any]:
    """Strictly read raw Base64 or a ``data:image/...;base64,`` URL as a PNG, JPEG or WebP.
    ``{"ok": True, "format", "mime", "bytes", "data"}`` or ``{"ok": False, "category"}`` with a category from: ``empty``, ``bad_data_uri``,
    ``unsupported_type`` (declared), ``too_large``, ``bad_base64`` (URL-safe, ``%3D`` and missing or extra padding are refused),
    ``unsupported_format`` (the bytes are not PNG/JPEG/WebP) and ``mismatch`` (declared type differs from the bytes)."""
    fail = lambda category: {"ok": False, "category": category}
    text = _shelf_strip(text)
    if not text:
        return fail("empty")
    declared = None
    match = _SHELF_DATA_URL.match(text)
    if match:
        declared = (match.group(1) or "").lower() or None
        declared = "image/jpeg" if declared == "image/jpg" else declared
        text = text[match.end():]
    elif text[:5].lower() == "data:":
        return fail("bad_data_uri")
    if declared is not None and declared not in ("image/png", "image/jpeg", "image/webp"):
        return fail("unsupported_type")
    encoded = re.sub(r"[ \t\r\n\f\v]+", "", text)
    if not encoded:
        return fail("empty")
    if len(encoded) > shelf_max_chars(max_bytes):
        return fail("too_large")
    if len(encoded) % 4 or _SHELF_B64.fullmatch(encoded) is None:
        return fail("bad_base64")
    raw = base64.b64decode(encoded, validate=True)
    if not raw:
        return fail("empty")
    if len(raw) > max_bytes:
        return fail("too_large")
    sniffed = ("image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if raw.startswith(b"\xff\xd8\xff")
               else "image/webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else None)
    if sniffed is None:
        return fail("unsupported_format")
    if declared is not None and declared != sniffed:
        return fail("mismatch")
    return {"ok": True, "format": sniffed[6:], "mime": sniffed, "bytes": len(raw), "data": encoded}


def build_prompt(fields: dict[str, str], image: dict[str, Any] | None = None) -> str:
    """The workbench's system-prompt draft: a title, then each filled field as a section (``goal``, ``context``, ``must``, ``avoid``, ``format``,
    ``raw``), then a note about an attached image (``{"mime", "bytes"}``)."""
    parts = ["# System Prompt Draft\n\n"]
    for key, title in (("goal", "Goal"), ("context", "Context / reference material"), ("must", "Must include"),
                       ("avoid", "Constraints / avoid"), ("format", "Output format"), ("raw", "Raw source")):
        value = _shelf_strip(str(fields.get(key, "")))
        if value:
            parts.append(f"## {title}\n{value}\n\n")
    if image:
        parts.append(f"## Visual reference\nAn image reference is attached in the workbench ({image.get('mime') or 'image'}, {image['bytes']} bytes).\n"
                     "Use its layout/content as visual context when the receiving system supports image input.\n\n")
    return "".join(parts).rstrip(_SHELF_WS)


def shelf_bundle(items: list[dict[str, Any]]) -> str:
    """Shelf items (``{"kind", "text"}`` or ``{"kind": "image", "mime", "data"}``) as one Markdown context bundle, in the order given."""
    labels = {"text": "Text", "url": "URL", "markdown": "Markdown", "image": "Image"}
    parts = ["# Context Bundle\n\n"]
    for number, item in enumerate(items, 1):
        body = f"data:{item['mime']};base64,{item['data']}" if item["kind"] == "image" else item.get("text", "")
        parts.append(f"## {number}. {labels[item['kind']]}\n{body}\n\n")
    return "".join(parts).rstrip(_SHELF_WS)


def _shelf_css() -> str:
    """Filter and order are radio buttons, so the rules are CSS: which kind shows, how items are ordered, which control looks selected."""
    rules = [".ui-shelf-radio{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}",
             ".ui-shelf-bar{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0;padding:0;border:0}.ui-shelf-bar legend{padding:0 0 4px}",
             ".ui-shelf-bar label{padding:4px 16px;border:1px solid var(--ui-border);border-radius:var(--ui-radius);cursor:pointer}",
             ".ui-shelf-actions{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.ui-shelf textarea{width:100%;box-sizing:border-box}",
             ".ui-shelf-items{display:flex;flex-direction:column;gap:8px;margin:16px 0 0;padding:0;list-style:none}",
             ".ui-shelf-item{order:calc(var(--n,0) * -1);display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:8px 16px;align-items:start;padding:16px;"
             "border:1px solid var(--ui-border);background:var(--ui-panel);border-radius:var(--ui-radius)}",
             ".ui-shelf-body{min-width:0}.ui-shelf-body pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}",
             ".ui-shelf-body a{overflow-wrap:anywhere}.ui-shelf-body img{display:block;max-width:100%;max-height:256px;height:auto}",
             ".ui-shelf-tools{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px}.ui-shelf-workbench{display:grid;gap:8px;margin-top:16px}",
             ".ui-shelf-workbench textarea{min-height:64px}",
             ".ui-shelf:has(#shelf-sort-oldest:checked) .ui-shelf-item{order:var(--n,0)}.ui-shelf:has(#shelf-sort-manual:checked) .ui-shelf-item{order:var(--pos,0)}"]
    for kind in SHELF_KINDS:
        rules.append(f'.ui-shelf:has(#shelf-kind-{kind}:checked) .ui-shelf-item:not([data-kind="{kind}"]){{display:none}}')
    for group, names in (("kind", ("all", *SHELF_KINDS)), ("sort", ("newest", "oldest", "manual"))):
        for name in names:
            rules.append(f'.ui-shelf:has(#shelf-{group}-{name}:checked) label[for="shelf-{group}-{name}"]{{background:var(--ui-accent);color:var(--ui-bg)}}')
            rules.append(f'.ui-shelf:has(#shelf-{group}-{name}:focus-visible) label[for="shelf-{group}-{name}"]{{outline:2px solid var(--ui-fg);outline-offset:2px}}')
    return "@layer components{" + "".join(rules) + "}"


_CSS["shelf.css"] = _shelf_css()
_CSS["door.css"] = ("@layer components{.ui-door label{display:block;margin:8px 0 4px}.ui-door-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px}"
                    ".ui-door-row .ui-input{flex:1 1 256px;min-width:0}.ui-door>.ui-input{width:100%;box-sizing:border-box}"
                    ".ui-door-path{margin:8px 0;padding-left:24px}.ui-door-path a{overflow-wrap:anywhere}}")


def shelf_html() -> str:
    """The shelf and prompt workbench as semantic HTML: one text box, radio filters and order, a list the page fills, a prompt preview."""
    radio = lambda group, name, label, checked=False: (f'<input class="ui-shelf-radio" type="radio" name="shelf-{group}" id="shelf-{group}-{name}" value="{name}"'
                                                       f'{" checked" if checked else ""}><label for="shelf-{group}-{name}">{label}</label>')
    kinds = radio("kind", "all", "All", True) + "".join(radio("kind", k, label) for k, label in zip(SHELF_KINDS, ("Text", "URL", "Markdown", "Image")))
    sorts = radio("sort", "newest", "Newest first", True) + radio("sort", "oldest", "Oldest first") + radio("sort", "manual", "Manual")
    fields = "".join(f'<label for="shelf-f-{k}">{label}</label><textarea class="ui-input" id="shelf-f-{k}" name="{k}" rows="2" data-shelf-field></textarea>'
                     for k, label in (("goal", "Goal"), ("context", "Context / reference material"), ("must", "Must include"),
                                      ("avoid", "Constraints / avoid"), ("format", "Output format"), ("raw", "Raw source")))
    return ('<section class="ui-panel ui-shelf" id="shelf" data-ui-shelf><h2>Clipboard shelf</h2>'
            '<p class="ui-muted">Paste text, a URL, Markdown or a Base64 image (PNG, JPEG, WebP). Everything stays in this page: nothing is saved or sent, '
            'and a reload empties the shelf.</p>'
            '<label for="shelf-input">Add to the shelf</label><textarea class="ui-input" id="shelf-input" rows="3" data-shelf-input></textarea>'
            '<div class="ui-shelf-actions"><button class="ui-button" type="button" data-shelf-add>Add</button>'
            '<button class="ui-button" type="button" data-shelf-paste>Paste from clipboard</button>'
            '<button class="ui-button" type="button" data-shelf-bundle>Copy bundle</button>'
            '<button class="ui-button" type="button" data-shelf-clear>Clear</button></div>'
            '<p class="ui-muted" role="status" aria-live="polite" data-shelf-status>Nothing on the shelf yet.</p>'
            f'<fieldset class="ui-shelf-bar"><legend>Show</legend>{kinds}</fieldset><fieldset class="ui-shelf-bar"><legend>Order</legend>{sorts}</fieldset>'
            '<ul class="ui-shelf-items" data-shelf-items></ul>'
            f'<details class="ui-shelf-workbench"><summary>Prompt workbench</summary>{fields}'
            '<div class="ui-shelf-actions"><button class="ui-button" type="button" data-shelf-attach>Attach an image from the shelf</button>'
            '<button class="ui-button" type="button" data-shelf-copy-prompt>Copy prompt</button></div>'
            '<pre class="ui-output" data-shelf-prompt aria-live="polite"></pre></details></section>')


def shelf_document(*, theme: str = "modern") -> str:
    """A single-file page for the clipboard shelf."""
    return render_document(trusted_html='<main class="ui-page">' + shelf_html() + "</main>" + module_script(_JS["shelf.js"]), title="Clipboard shelf",
                           theme=theme, css=bundled_css())


# --- curl import: the editor's curl subset, parsed without running curl or touching the network ---------------------------
# Ported from flutter_navigation_basic python/curl_request.py @39d659e (the Flutter editor's lexer and rules; tests/fixtures/curl_request_cases.json
# is its golden file). Python is the reference; the page's ``curl.js`` must give identical results.

CURL_MAX_BYTES, CURL_MAX_TOKENS = 65_536, 4_096
_CURL_PREFIX = "httpDraft.curl."
_CURL_ASCII = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)} | {0x3000: 0x20, 0x2212: 0x2D}   # full-width forms, ideographic space, minus
_CURL_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_CURL_OPTIONS = {"-X": "method", "--request": "method", "--url": "url", "-H": "header", "--header": "header", "-d": "data", "--data": "data",
                 "--data-raw": "data", "--data-binary": "data", "--data-urlencode": "urlencode", "-u": "user", "--user": "user",
                 "-A": "agent", "--user-agent": "agent", "-e": "referer", "--referer": "referer"}
_CURL_IGNORED = frozenset({"-s", "-S", "-i", "-v", "-k", "--silent", "--show-error", "--include", "--verbose", "--insecure"})
_CURL_SECRET_NAMES = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key", "x-auth-token",
                                "key", "sig", "sas"})
_CURL_SECRET_PARTS = ("api-key", "api_key", "token", "secret", "password", "signature", "credential", "access_key", "access-key",
                      "sharedaccesssignature")


class CurlParseError(ValueError):
    """A stable diagnostic code (``httpDraft.curl.error.*``); never contains the input, which may hold credentials."""


def _curl_fail(name: str) -> None:
    raise CurlParseError(_CURL_PREFIX + "error." + name)


def curl_tokenize(raw: str) -> list[str]:
    """Split like the editor's lexer: quotes group, ``\\`` before a newline continues the line, shell metacharacters are refused,
    nothing is expanded. (``shlex`` is not used: it eats unquoted backslashes that the editor keeps.)"""
    if not isinstance(raw, str):
        _curl_fail("inputType")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError:
        _curl_fail("encoding")
    if size > CURL_MAX_BYTES:
        _curl_fail("inputTooLarge")
    if "\x00" in raw:
        _curl_fail("nul")
    text = raw.translate(_CURL_ASCII).strip()
    if not text:
        _curl_fail("empty")
    text = re.sub(r"\\\r?\n", " ", text)
    tokens: list[str] = []
    buf: list[str] = []
    quote, started, index = "", False, 0

    def flush() -> None:
        nonlocal started
        if started:
            tokens.append("".join(buf))
            if len(tokens) > CURL_MAX_TOKENS:
                _curl_fail("tooManyTokens")
            buf.clear()
            started = False

    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
            elif quote == '"' and char == "\\" and index + 1 < len(text):
                index += 1
                following = text[index]
                if following not in '$`"\\\n':
                    buf.append("\\")
                buf.append(following)
            else:
                buf.append(char)
        elif char in "'\"":
            quote, started = char, True
        elif char in "`$|;<>":
            _curl_fail("shellMeta")
        elif char in " \t\r\n":
            flush()
        else:
            started = True
            buf.append(char)
        index += 1
    if quote:
        _curl_fail("unbalancedQuotes")
    flush()
    return tokens


def _curl_field(name: str, value: str, sensitive: bool = False) -> dict[str, Any]:
    return {"name": name, "value": value, "sensitive": sensitive}


def _curl_sensitive(name: str) -> bool:
    name = name.translate(_CURL_ASCII).strip().lower()
    return name in _CURL_SECRET_NAMES or name.endswith(("_key", "-key")) or any(part in name for part in _CURL_SECRET_PARTS)


def _curl_pairs(raw: str) -> list[dict[str, Any]]:
    # urllib would replace malformed UTF-8 and tolerate bad escapes; neither may silently change what the editor was given.
    if re.search(r"%(?![0-9a-fA-F]{2})", raw):
        _curl_fail("queryEncoding")
    try:
        return [_curl_field(name, value) for name, value in parse_qsl(raw, keep_blank_values=True, errors="strict", separator="&")]
    except UnicodeError:
        _curl_fail("queryEncoding")


def parse_curl(raw: str) -> dict[str, Any]:
    """``{"ok", "draft", "errors", "warnings"}`` for a curl command: method, url, headers, query, body mode and form fields.
    Fields carry ``sensitive`` (credentials by name or a masked ``***`` value); see ``mask_curl``. Nothing is sent."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        tokens = curl_tokenize(raw)
        if not tokens or tokens[0].lower() != "curl":
            _curl_fail("notCurl")
        method, explicit_method, url = "GET", False, None
        headers: list[dict[str, Any]] = []
        chunks: list[str] = []
        encoded: list[dict[str, Any]] = []
        use_get, index = False, 1
        while index < len(tokens):
            token = tokens[index]
            index += 1
            flag, sep, inline = token.partition("=") if token.startswith("--") else (token, "", "")
            kind = _CURL_OPTIONS.get(flag)
            if kind:
                if sep:
                    value = inline
                elif index < len(tokens):
                    value = tokens[index]
                    index += 1
                else:
                    errors.append(_CURL_PREFIX + "error.missingArg")
                    break
                if kind == "method":
                    candidate = value.strip().upper()
                    if candidate not in _CURL_METHODS:
                        errors.append(_CURL_PREFIX + "error.badMethod")
                    else:
                        method, explicit_method = candidate, True
                elif kind == "url":
                    url = value
                elif kind == "header":
                    name, colon, content = value.strip().partition(":")
                    name, content = name.strip(), content.strip()
                    if not colon or not name or any(c in name + content for c in "\r\n"):
                        errors.append(_CURL_PREFIX + "error.badHeader")
                    else:
                        headers.append(_curl_field(name, content, _curl_sensitive(name) or "***" in content))
                elif kind in ("data", "urlencode"):
                    at, eq = value.find("@"), value.find("=")
                    if value.startswith("@") or (kind == "urlencode" and at >= 0 and (eq < 0 or at < eq)):
                        errors.append(_CURL_PREFIX + "error.fileBody")
                    elif kind == "data":
                        chunks.append(value)
                    else:
                        name, _, content = value.partition("=")
                        encoded.append(_curl_field(name, content))
                elif kind == "user":
                    headers.append(_curl_field("Authorization", "Basic " + base64.b64encode(value.encode("utf-8")).decode("ascii"), True))
                    warnings.append(_CURL_PREFIX + "warn.basicAuthMapped")
                else:
                    headers.append(_curl_field("User-Agent" if kind == "agent" else "Referer", value))
            elif flag in ("-G", "--get"):
                use_get = True
            elif flag in ("-I", "--head"):
                method, explicit_method = "HEAD", True
            elif flag in ("-L", "--location"):
                warnings.append(_CURL_PREFIX + "warn.ignoredRedirect")
            elif flag in _CURL_IGNORED:
                warnings.append(_CURL_PREFIX + "warn.ignoredFlag")
            elif token.startswith("-") and len(token) > 1:
                errors.append(_CURL_PREFIX + "error.unsupportedFlag")
            elif url is not None:
                errors.append(_CURL_PREFIX + "error.extraPositional")
            else:
                url = token
        if errors:
            return {"ok": False, "draft": None, "errors": errors, "warnings": warnings}
        if url is None or not url.strip():
            _curl_fail("urlRequired")
        body_mode, raw_body, query, form = "none", "", [], []
        if encoded:
            if use_get:
                query = encoded
            else:
                body_mode, form = "formUrlEncoded", encoded
                method = method if explicit_method else "POST"
        elif chunks:
            joined = "&".join(chunks)
            if use_get:
                query = _curl_pairs(joined)
            else:
                method = method if explicit_method else "POST"
                content_type = next((h["value"].lower() for h in headers if h["name"].lower() == "content-type"), "")
                if "application/json" in content_type:
                    body_mode, raw_body = "json", joined
                elif "application/x-www-form-urlencoded" in content_type:
                    body_mode, form = "formUrlEncoded", _curl_pairs(joined)
                elif joined.lstrip().startswith(("{", "[")):
                    body_mode, raw_body = "json", joined
                elif "=" in joined:
                    body_mode, form = "formUrlEncoded", _curl_pairs(joined)
                else:
                    body_mode, raw_body = "raw", joined
        rows = lambda items: [item for item in items if item["name"] or item["value"]]
        return {"ok": True, "draft": {"method": method, "url": url.strip(), "headers": rows(headers), "query": rows(query),
                                      "bodyMode": body_mode, "rawBody": raw_body, "formFields": rows(form)},
                "errors": [], "warnings": warnings}
    except CurlParseError as error:
        return {"ok": False, "draft": None, "errors": [str(error)], "warnings": warnings}


def mask_curl(result: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``parse_curl``'s result with every ``sensitive`` field's value replaced by ``***``, safe to show or copy.
    The raw body is not inspected: it may hold secrets that nothing marks, so do not paste real credentials."""
    masked = json.loads(json.dumps(result))
    for group in ("headers", "query", "formFields"):
        for field in (masked["draft"] or {}).get(group, []):
            if field["sensitive"]:
                field["value"] = "***"
    return masked


STUB_SCHEMA = "web-ui-stub/1"
# stub.js without its import line: it needs setText/prettyJson from ui.js, so an embedded module is ui.js + this.
EMBEDDED_STUB_JS = _JS["stub.js"].split("\n", 1)[1]

_JS["coordinates.js"] = r"""/* web-ui coordinates: validate and format a point, read it from a Maps URL, frame a tolerance area, find its XYZ tile. Python (web_ui.parse_coordinate, tolerance_area, ...) is the reference. */
const SPACE="\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const strip=s=>(s.startsWith("﻿")?s.slice(1):s).replace(new RegExp("^["+SPACE+"]+|["+SPACE+"]+$","g"),"");
const ascii=s=>{let o="";for(const c of s){const n=c.codePointAt(0);o+=n>=0xFF01&&n<=0xFF5E?String.fromCodePoint(n-0xFEE0):n===0x3000?" ":n===0x2212?"-":c}return o};
const NUMBER=/^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/,WS="[ \\t\\r\\n\\f\\v]",N="(-?[0-9]+(?:\\.[0-9]+)?)";
const PATTERNS=[new RegExp("[?&#]ll="+N+WS+"*,"+WS+"*"+N,"i"),new RegExp("[?&#](?:query|q)="+N+WS+"*,"+WS+"*"+N,"i"),new RegExp("!3d"+N+"!4d"+N),new RegExp("@"+N+WS+"*,"+WS+"*"+N+"(?:,|/|z|\\?|#|$)")];
export const fixed=(v,n)=>v.toFixed(n);
export function parseCoordinate(latitude,longitude){const v=[];for(const raw of[latitude,longitude]){const t=strip(ascii(String(raw)));
  if(["NaN","Infinity","-Infinity","+Infinity"].includes(t))throw new Error("Latitude and longitude must be finite numbers.");
  if(!NUMBER.test(t))throw new Error("Latitude and longitude must be numbers.");v.push(Number(t))}
 const[lat,lon]=v;if(!Number.isFinite(lat)||!Number.isFinite(lon))throw new Error("Latitude and longitude must be finite numbers.");
 if(!(lat>=-90&&lat<=90))throw new Error("Latitude must be between -90 and 90.");if(!(lon>=-180&&lon<=180))throw new Error("Longitude must be between -180 and 180.");return[lat,lon]}
const decode=t=>{try{return decodeURIComponent(t)}catch(e){throw new Error("malformed percent escape")}};
export function tryParseMapsUrl(text){const raw=strip(ascii(text));if(!raw)return null;const plus=raw.split("+").join(" "),candidates=[plus];
 try{candidates.push(decode(plus))}catch(e){}
 let again=plus;for(let i=0;i<8;i++){let next;try{next=decode(again)}catch(e){break}if(next===again)break;again=next}candidates.push(again);
 for(const c of candidates)for(const p of PATTERNS){const m=p.exec(c);if(m){try{return parseCoordinate(m[1],m[2])}catch(e){}}}return null}
export function toDms(value,isLat){const abs=Math.abs(value);let degrees=Math.floor(abs);const mv=(abs-degrees)*60;let minutes=Math.floor(mv),seconds=Number(((mv-minutes)*60).toFixed(2));
 if(seconds>=60){seconds=0;minutes+=1;if(minutes>=60){minutes=0;degrees+=1}}
 const h=isLat?(value<0?"S":"N"):(value<0?"W":"E");return degrees+"° "+String(minutes).padStart(2,"0")+"′ "+seconds.toFixed(2).padStart(5,"0")+"″ "+h}
export const coordinateText=(lat,lon)=>fixed(lat,6)+", "+fixed(lon,6),dmsText=(lat,lon)=>toDms(lat,true)+", "+toDms(lon,false);
const normLon=v=>{while(v<-180)v+=360;while(v>180)v-=360;return v};
export function toleranceArea(lat,lon,radius){if(!Number.isFinite(radius)||radius<=0)throw new Error("Tolerance radius must be greater than zero.");
 const angular=radius/6371008.8,latDelta=angular*180/Math.PI,south=Math.max(-90,lat-latDelta),north=Math.min(90,lat+latDelta),cosine=Math.abs(Math.cos(lat*Math.PI/180));
 const lonDelta=south<=-90||north>=90||cosine<1e-12?180:Math.min(180,angular/cosine*180/Math.PI),rawWest=lon-lonDelta,rawEast=lon+lonDelta,full=lonDelta>=180;
 const west=full?-180:normLon(rawWest),east=full?180:normLon(rawEast),wraps=!full&&(rawWest<-180||rawEast>180),span=full?360:wraps?(180-west)+(east+180):Math.abs(east-west);
 return{lat,lon,radius_m:radius,south,west,north,east,wraps,full_longitude:full,apple_span:!wraps&&!full,lat_span:Math.abs(north-south),lon_span:span}}
export function zoomForRadius(radius,latitude=0){if(!Number.isFinite(radius)||radius<=0)return 16;const cosine=Math.min(Math.max(Math.abs(Math.cos(latitude*Math.PI/180)),1e-6),1);
 return Math.min(Math.max(Math.floor(Math.log(40075016.686*cosine/(radius*4))/Math.log(2)),3),20)}
export function xyzTile(lat,lon,zoom){if(!Number.isInteger(zoom)||zoom<0||zoom>22)throw new Error("XYZ tile zoom must be between 0 and 22.");lat=Math.min(Math.max(lat,-85.05112878),85.05112878);
 const n=2**zoom,x=Math.min(Math.max(Math.floor((lon+180)/360*n),0),n-1),mercator=Math.log(Math.tan(Math.PI/4+lat*Math.PI/180/2)),y=Math.min(Math.max(Math.floor((1-mercator/Math.PI)/2*n),0),n-1);
 return{zoom,x,y,path:zoom+"/"+x+"/"+y}}
const query=o=>new URLSearchParams(o).toString();
export function mapsUrls(lat,lon){const point=coordinateText(lat,lon).split(" ").join("");
 return{google:"https://www.google.com/maps/search/?"+query({api:"1",query:point}),apple:"https://maps.apple.com/?"+query({ll:point,q:"Coordinates"}),
  osm_preview:"https://staticmap.openstreetmap.de/staticmap.php?"+query({center:point,zoom:"16",size:"600x400",maptype:"mapnik",markers:point+",lightblue1"})}}
const radiusText=v=>Number.isInteger(v)?String(v):fixed(v,2);
export function areaTexts(a){const f=v=>fixed(v,6),lat=a.lat,lon=a.lon,radius=radiusText(a.radius_m),wraps=a.wraps?"true":"false",zoom=zoomForRadius(a.radius_m,lat),apple={ll:f(lat)+","+f(lon),q:"Tolerance area"};
 if(a.apple_span&&a.lat_span>0&&a.lon_span>0)apple.spn=f(a.lat_span)+","+f(a.lon_span);
 return{center_radius:"center: "+f(lat)+", "+f(lon)+"\nradius_m: "+radius,
  bounds:"south: "+f(a.south)+"\nwest: "+f(a.west)+"\nnorth: "+f(a.north)+"\neast: "+f(a.east)+"\nwraps_antimeridian: "+wraps,
  bbox:"["+f(a.west)+", "+f(a.south)+", "+f(a.east)+", "+f(a.north)+"]",
  json:'{\n  "center": {\n    "latitude": '+f(lat)+',\n    "longitude": '+f(lon)+'\n  },\n  "radius_m": '+radius+',\n  "bounds": {\n    "south": '+f(a.south)+',\n    "west": '+f(a.west)+',\n    "north": '+f(a.north)+',\n    "east": '+f(a.east)+',\n    "wraps_antimeridian": '+wraps+'\n  }\n}',
  google_circle:"new google.maps.Circle({\n  center: {\n    lat: "+f(lat)+",\n    lng: "+f(lon)+"\n  },\n  radius: "+radius+"\n});",
  mapkit_circle:"MKCircle(\n  center: CLLocationCoordinate2D(\n    latitude: "+f(lat)+",\n    longitude: "+f(lon)+"\n  ),\n  radius: "+radius+"\n)",
  google_rectangle:"new google.maps.Rectangle({\n  bounds: {\n    south: "+f(a.south)+",\n    west: "+f(a.west)+",\n    north: "+f(a.north)+",\n    east: "+f(a.east)+"\n  }\n});",
  mapkit_region:"MKCoordinateRegion(\n  center: CLLocationCoordinate2D(\n    latitude: "+f(lat)+",\n    longitude: "+f(lon)+"\n  ),\n  span: MKCoordinateSpan(\n    latitudeDelta: "+f(a.lat_span)+",\n    longitudeDelta: "+f(a.lon_span)+"\n  )\n)",
  google_area_url:"https://www.google.com/maps/@"+f(lat)+","+f(lon)+","+zoom+"z",apple_area_url:"https://maps.apple.com/?"+query(apple)}}
export function bindCoordinates(root=document){return[...root.querySelectorAll("[data-ui-coord]")].map(box=>{
 const $=s=>box.querySelector(s),lat=$("[data-lat]"),lon=$("[data-lon]"),url=$("[data-url]"),status=$("[data-status]"),out=$("[data-out]"),radius=$("[data-radius]"),zoom=$("[data-zoom]"),preset=()=>box.querySelector('input[name="coord-preset"]:checked').value;
 const add=(label,text)=>{const dt=document.createElement("dt"),dd=document.createElement("dd"),pre=document.createElement("pre");dt.textContent=label;pre.textContent=text;dd.append(pre);out.append(dt,dd)};
 const show=()=>{out.replaceChildren();try{const[la,lo]=parseCoordinate(lat.value,lon.value);status.textContent="Valid.";
   add("Decimal degrees",coordinateText(la,lo));add("Degrees, minutes, seconds",dmsText(la,lo));const u=mapsUrls(la,lo);add("Google Maps",u.google);add("Apple Maps",u.apple);add("OpenStreetMap static preview",u.osm_preview);
   const r=preset()==="custom"?Number(radius.value):Number(preset());try{const area=toleranceArea(la,lo,r),t=areaTexts(area);
    add("Tolerance: centre and radius",t.center_radius);add("Tolerance: bounds",t.bounds);add("Tolerance: bbox [west, south, east, north]",t.bbox);add("Tolerance: JSON",t.json);
    add("Google Maps circle",t.google_circle);add("MapKit circle",t.mapkit_circle);add("Google Maps rectangle",t.google_rectangle);add("MapKit region",t.mapkit_region);add("Google Maps area link",t.google_area_url);add("Apple Maps area link",t.apple_area_url)}
   catch(e){add("Tolerance",e.message)}
   try{const tile=xyzTile(la,lo,Number(zoom.value));add("XYZ tile",tile.path)}catch(e){add("XYZ tile",e.message)}
  }catch(e){status.textContent=e.message}};
 for(const el of[lat,lon,radius,zoom])el.addEventListener("input",show);for(const r of box.querySelectorAll('input[name="coord-preset"]'))r.addEventListener("change",show);
 $("[data-use-url]").addEventListener("click",()=>{const p=tryParseMapsUrl(url.value);if(!p){status.textContent="Could not find latitude/longitude in that Maps URL.";return}lat.value=String(p[0]);lon.value=String(p[1]);show()});
 show();return box})}
globalThis.webUiCoordinates={fixed,parseCoordinate,tryParseMapsUrl,toDms,coordinateText,dmsText,toleranceArea,zoomForRadius,xyzTile,mapsUrls,areaTexts,bindCoordinates};
if(typeof document!=="undefined")bindCoordinates();
"""

_JS["composition.js"] = r"""/* web-ui composition: chord theory, metronome timing, tap tempo, note sequences and a seeded song seed. Python (web_ui.chord_with_inversion, metronome_position, ...) is the reference. */
export const FLAT_KEYS=["C","D♭","D","E♭","E","F","G♭","G","A♭","A","B♭","B"],SHARP_KEYS=["C","C♯","D","D♯","E","F","F♯","G","G♯","A","A♯","B"];
export const SELECTABLE_KEYS=["C","C♯","D♭","D","D♯","E♭","E","F","F♯","G♭","G","G♯","A♭","A","A♯","B♭","B"];
export const CHORD_MODIFIERS=["triad","6","m6","7","maj7","m7","m7♭5","sus2","sus4","add9","add11","dim","aug"];
const MAJOR=[0,2,4,5,7,9,11],MINOR=[0,2,3,5,7,8,10],MAJOR_Q=["","m","m","","","m","dim"],MINOR_Q=["m","dim","","m","m","","" ],LETTERS="CDEFGAB",NAT={C:0,D:2,E:4,F:5,G:7,A:9,B:11};
const INTERVALS={triad:[0,4,7],"6":[0,4,7,9],m6:[0,3,7,9],"7":[0,4,7,10],maj7:[0,4,7,11],m7:[0,3,7,10],"m7♭5":[0,3,6,10],sus2:[0,2,7],sus4:[0,5,7],add9:[0,4,7,14],add11:[0,4,7,17],dim:[0,3,6],aug:[0,4,8]};
const ROMAN={I:1,II:2,III:3,IV:4,V:5,VI:6,VII:7},mod=(n,m)=>((n%m)+m)%m,trim=s=>s.replace(/^[ \t\r\n\f\v]+|[ \t\r\n\f\v]+$/g,"");
export function pitchClass(note){const m=typeof note==="string"?/^([A-G])([♯♭]*)$/.exec(note):null;if(!m)throw new Error("unsupported note: "+note);
 const sharps=(m[2].match(/♯/g)||[]).length,flats=(m[2].match(/♭/g)||[]).length;return mod(NAT[m[1]]+sharps-flats,12)}
export const prefersSharps=key=>key.includes("♯")||["D","E","G","A","B"].includes(key);
export const noteForPitchClass=(v,sharps)=>(sharps?SHARP_KEYS:FLAT_KEYS)[mod(v,12)];
export const transposeKey=(key,n)=>noteForPitchClass(pitchClass(key)+n,prefersSharps(key));
export const fifthNeighbor=(key,clockwise)=>transposeKey(key,clockwise?7:-7);
function spell(letter,v){let d=mod(v,12)-NAT[letter];d=d>6?d-12:d<-6?d+12:d;if(![-2,-1,0,1,2].includes(d))throw new Error("cannot spell pitch");return letter+({"-2":"♭♭","-1":"♭","0":"","1":"♯","2":"♯♯"})[d]}
export function scale(key,minor){const root=pitchClass(key),first=LETTERS.indexOf(key.slice(0,1));if(first<0)throw new Error("unsupported root letter");const steps=minor?MINOR:MAJOR;return steps.map((st,d)=>spell(LETTERS[(first+d)%7],root+st))}
export function diatonicChord(key,degree,minor){if(!Number.isInteger(degree)||degree<1||degree>7)throw new Error("degree must be 1 through 7");return scale(key,minor)[degree-1]+(minor?MINOR_Q:MAJOR_Q)[degree-1]}
export function romanDegree(token){const m=/^[ivIV]+/.exec(trim(token));return m&&ROMAN[m[0].toUpperCase()]||null}
export function convertRomanToken(key,token,minor){const t=trim(token),m=/^([ivIV]+)([\s\S]*)$/.exec(t),degree=m?romanDegree(t):null;if(!m||degree===null)return token;
 const root=scale(key,minor)[degree-1],base=diatonicChord(key,degree,minor),suffix=trim(m[2]);
 if(!suffix)return base;if(suffix==="6"||suffix==="7")return base+suffix;if(suffix==="m6")return root+"m6";if(["maj7","M7","△7"].includes(suffix))return root+"maj7";if(suffix==="m7")return root+"m7";
 if(["m7♭5","ø7"].includes(suffix))return root+"m7♭5";if(["sus2","sus4","add9","add11"].includes(suffix))return root+suffix;if(["dim","°"].includes(suffix))return root+"dim";if(["aug","+"].includes(suffix))return root+"aug";return base}
export function convertProgression(key,progression,minor){for(const d of "–—-|")progression=progression.split(d).join(" ");return progression.split(/[ \t\r\n\f\v,]+/).filter(Boolean).map(t=>convertRomanToken(key,t,minor))}
export function applyModifier(root,modifier){if(!CHORD_MODIFIERS.includes(modifier))throw new Error("unsupported chord modifier");return modifier==="triad"?root:root+modifier}
export function chordTones(root,modifier){if(!Object.hasOwn(INTERVALS,modifier))throw new Error("unsupported chord modifier");const start=pitchClass(root),sharps=prefersSharps(root);return INTERVALS[modifier].map(i=>noteForPitchClass(start+i,sharps))}
export function normalizedInversion(modifier,inversion){if(!Number.isInteger(inversion)||inversion<0||inversion>3)throw new Error("inversion must be 0 through 3");const n=INTERVALS[modifier].length;return inversion<n?inversion:n===3&&inversion===3?1:inversion%n}
export function chordWithInversion(root,modifier,inversion){const chord=applyModifier(root,modifier),n=normalizedInversion(modifier,inversion);return n===0?chord:chord+"/"+chordTones(root,modifier)[n]}
const half=v=>Math.floor(v+0.5);
export const beatMicros=bpm=>half(60000000/Math.min(Math.max(bpm,30),300));
export function subdivisionMicros(bpm,per){if(!(per>0))throw new Error("subdivisions per beat must be positive");return half(beatMicros(bpm)/per)}
export function barMicros(bpm,beats){if(!(beats>0))throw new Error("beats per bar must be positive");return beatMicros(bpm)*beats}
export function metronomePosition(elapsed,bpm,beats,per){if(!(beats>0&&per>0))throw new Error("beats per bar and subdivisions must be positive");const unit=subdivisionMicros(bpm,per),e=Math.max(elapsed,0),steps=Math.floor(e/unit);return[Math.floor(steps/per)%beats,steps%per,(e%unit)/unit]}
export function durationLabel(micros){if(micros>=1000000){const h=half(micros/10000);return Math.floor(h/100)+"."+String(h%100).padStart(2,"0")+" s"}return half(micros/1000)+" ms"}
export function tapTempo(taps,tap,resetGap=2000000,maxIntervals=5){const kept=taps.length&&tap-taps[taps.length-1]>resetGap?[]:[...taps];kept.push(tap);if(kept.length>maxIntervals+1)kept.shift();if(kept.length<2)return[kept,null];
 const avg=(kept[kept.length-1]-kept[0])/(kept.length-1);if(avg<=0)return[kept,null];return[kept,Math.min(Math.max(half(60000000/avg),30),300)]}
export function parseNotes(text){const out=[];for(const token of text.split(/[ \t\r\n\f\v,]+/)){if(!token)continue;const m=/^([A-Ga-g])([#b♯♭]?)(-?[0-9])$/.exec(token);if(!m)throw new Error("invalid note: "+token);out.push(m[1].toUpperCase()+({"#":"♯",b:"♭"}[m[2]]??m[2])+m[3])}return out}
export function notesPerBar(beats,unit,noteUnit){if(noteUnit!==4&&noteUnit!==8)throw new Error("only quarter and eighth notes are supported");const v=beats*noteUnit/unit;if(!Number.isInteger(v)||v<=0)throw new Error("the selected note value does not divide this bar evenly");return v}
export function noteBars(notes,beats,unit,noteUnit){const size=notesPerBar(beats,unit,noteUnit),out=[];for(let i=0;i<notes.length;i+=size)out.push(notes.slice(i,i+size));return out}
export function mulberry32(seed){let a=seed>>>0;return()=>{a=(a+0x6D2B79F5)>>>0;let t=Math.imul(a^a>>>15,a|1);t=((t+Math.imul(t^t>>>7,t|61))^t)>>>0;return((t^t>>>14)>>>0)/4294967296}}
export const SEED_KEYS=["B♭","B","C","D♭","D","E♭","E","F","G♭","G","A♭","A"],SEED_MODES=["Major","Minor"],SEED_TIMES=["4/4","3/4","6/8"];
export const SEED_PROGRESSIONS={Major:["I – V – vi – IV","I – vi – IV – V","ii – V – I – vi","I – IV – V – IV"],Minor:["i – VI – III – VII","i – iv – VII – III","i – VII – VI – VII","i – iv – v – i"]};
export function songSeed(seed,avoid=null){const rng=mulberry32(seed),pick=o=>o[Math.floor(rng()*o.length)];let result;
 for(let i=0;i<8;i++){const mode=pick(SEED_MODES);result={tonic:pick(SEED_KEYS),mode,bpm:80+Math.floor(rng()*81),time:pick(SEED_TIMES),progression:pick(SEED_PROGRESSIONS[mode])};
  if(avoid===null||JSON.stringify(result)!==JSON.stringify(avoid))break}return result}
export const songSeedText=s=>"Key: "+s.tonic+" "+s.mode+" · BPM: "+s.bpm+" · Time: "+s.time+" · Progression: "+s.progression;
export function bindStudio(root=document){return[...root.querySelectorAll("[data-ui-studio]")].map(box=>{
 const $=s=>box.querySelector(s),$$=s=>[...box.querySelectorAll(s)],checked=n=>box.querySelector('input[name="'+n+'"]:checked').value;
 const el={bpm:$("[data-bpm]"),bpmOut:$("[data-bpm-out]"),beats:$("[data-beats]"),info:$("[data-beat-info]"),run:$("[data-run]"),tap:$("[data-tap]"),key:$("[data-key]"),prog:$("[data-prog]"),progOut:$("[data-prog-out]"),
  degrees:$("[data-degrees]"),fifths:$("[data-fifths]"),degree:$("[data-degree]"),mod:$("[data-mod]"),chord:$("[data-chord]"),notes:$("[data-notes]"),noteUnit:$("[data-note-unit]"),bars:$("[data-bars]"),seed:$("[data-seed-out]")};
 const sig=()=>checked("studio-sig").split("/").map(Number),minor=()=>checked("studio-mode")==="Minor";let running=false,t0=0,taps=[],raf=0;
 const text=(n,t)=>{n.textContent=t};
 const drawBeats=()=>{const[b]=sig();el.beats.replaceChildren(...Array.from({length:b},(_,i)=>{const d=document.createElement("span");d.className="ui-beat";d.dataset.i=i;d.textContent=i+1;return d}))};
 const tick=()=>{const[b,u]=sig(),bpm=Number(el.bpm.value),[beat,sub,phase]=metronomePosition((performance.now()-t0)*1000,bpm,b,2);box.dataset.beat=beat;box.dataset.sub=sub;
  for(const d of el.beats.children)d.toggleAttribute("data-on",Number(d.dataset.i)===beat);
  text(el.info,"Beat "+(beat+1)+"/"+b+" · "+durationLabel(beatMicros(bpm))+" per beat · bar "+durationLabel(barMicros(bpm,b)));if(running)raf=requestAnimationFrame(tick)};
 const idle=()=>{const[b]=sig(),bpm=Number(el.bpm.value);text(el.bpmOut,bpm+" BPM");text(el.info,b+"/"+sig()[1]+" · beat "+durationLabel(beatMicros(bpm))+" · bar "+durationLabel(barMicros(bpm,b)))};
 const restart=()=>{if(running)t0=performance.now();idle()};
 el.bpm.addEventListener("input",restart);for(const r of $$('input[name="studio-sig"]'))r.addEventListener("change",()=>{drawBeats();restart();notes()});
 el.run.addEventListener("click",()=>{running=!running;el.run.setAttribute("aria-pressed",String(running));el.run.textContent=running?"Stop":"Start";if(running){t0=performance.now();raf=requestAnimationFrame(tick)}else{cancelAnimationFrame(raf);for(const d of el.beats.children)d.removeAttribute("data-on");delete box.dataset.beat;idle()}});
 el.tap.addEventListener("click",()=>{const[kept,bpm]=tapTempo(taps,Math.floor(performance.now()*1000));taps=kept;if(bpm!==null){el.bpm.value=bpm;restart();text(el.tap,"Tap tempo ("+bpm+")")}});
 const theory=()=>{const key=el.key.value,m=minor();text(el.progOut,convertProgression(key,el.prog.value,m).join("  "));
  el.degrees.replaceChildren(...Array.from({length:7},(_,i)=>{const s=document.createElement("span");s.className="ui-tag";s.textContent=(i+1)+" "+diatonicChord(key,i+1,m);return s}));
  const left=fifthNeighbor(key,false),right=fifthNeighbor(key,true);text($("[data-fifth-left]"),left);text($("[data-fifth-right]"),right);$("[data-fifth-left]").value=left;$("[data-fifth-right]").value=right;
  const degree=Number(el.degree.value),root=scale(key,m)[degree-1],inv=Number(checked("studio-inv")),modifier=el.mod.value;
  text(el.chord,chordWithInversion(root,modifier,inv)+"  ("+chordTones(root,modifier).join(" ")+")")};
 const setKey=k=>{if(![...el.key.options].some(o=>o.value===k))return;el.key.value=k;theory()};
 el.key.addEventListener("change",theory);el.prog.addEventListener("input",theory);el.degree.addEventListener("change",theory);el.mod.addEventListener("change",theory);
 for(const r of $$('input[name="studio-mode"],input[name="studio-inv"]'))r.addEventListener("change",theory);
 $("[data-semi-down]").addEventListener("click",()=>setKey(transposeKey(el.key.value,-1)));$("[data-semi-up]").addEventListener("click",()=>setKey(transposeKey(el.key.value,1)));
 for(const b of $$("[data-fifth-left],[data-fifth-right]"))b.addEventListener("click",()=>setKey(b.value));
 const notes=()=>{try{const[b,u]=sig(),n=parseNotes(el.notes.value),bars=noteBars(n,b,u,Number(el.noteUnit.value));el.bars.replaceChildren(...bars.map((bar,i)=>{const li=document.createElement("li");li.textContent=bar.join(" ");li.dataset.bar=i+1;return li}))}catch(e){el.bars.replaceChildren();const li=document.createElement("li");li.textContent=e.message;li.dataset.error="";el.bars.append(li)}};
 el.notes.addEventListener("input",notes);el.noteUnit.addEventListener("change",notes);
 $("[data-new-seed]").addEventListener("click",()=>{const seed=Math.floor(Math.random()*4294967296),r=songSeed(seed);text(el.seed,songSeedText(r)+" (seed "+seed+")");
  el.key.value=r.tonic;box.querySelector('input[name="studio-mode"][value="'+r.mode+'"]').checked=true;el.bpm.value=r.bpm;box.querySelector('input[name="studio-sig"][value="'+r.time+'"]').checked=true;el.prog.value=r.progression;drawBeats();restart();theory();notes()});
 drawBeats();idle();theory();notes();return box})}
globalThis.webUiStudio={pitchClass,transposeKey,fifthNeighbor,scale,diatonicChord,convertProgression,convertRomanToken,applyModifier,chordTones,normalizedInversion,chordWithInversion,beatMicros,subdivisionMicros,barMicros,metronomePosition,durationLabel,tapTempo,parseNotes,notesPerBar,noteBars,mulberry32,songSeed,songSeedText,bindStudio};
if(typeof document!=="undefined")bindStudio();
"""

_JS["door.js"] = r"""/* web-ui door: a Door-to-Door pull-down, emoji transitions ("A → B", "A ↔ B") and a seeded draw. Python (web_ui.door_options, emoji_path, door_draw) is the reference. */
const DROP="\\ufe0e\\ufe0f \\t\\n\\v\\f\\r\\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
export const emojiKey=e=>e.replace(new RegExp("["+DROP+"]","g"),"");
export function emojiPath(notation,pages){
 const by=new Map(pages.map(p=>[emojiKey(p.emoji),p.href])),parts=emojiKey(notation).split(/([→↔])/),path=[parts[0]];
 for(let i=1;i+1<parts.length;i+=2){const there=parts[i+1];if(parts[i]==="→")path.push(there);else path.push(there,path[path.length-1])}
 return path.map(k=>{if(!by.has(k))throw new Error("unknown page emoji: "+JSON.stringify(k));return by.get(k)})}
export function mulberry32(seed){let a=seed>>>0;return()=>{a=(a+0x6D2B79F5)>>>0;let t=Math.imul(a^a>>>15,a|1);t=((t+Math.imul(t^t>>>7,t|61))^t)>>>0;return((t^t>>>14)>>>0)/4294967296}}
export function doorDraw(seed,count,k){if(!(k>=0&&k<=count))throw new Error("k must be from 0 to count");const rng=mulberry32(seed),order=Array.from({length:count},(_,i)=>i);
 for(let i=0;i<k;i++){const j=i+Math.floor(rng()*(count-i));[order[i],order[j]]=[order[j],order[i]]}return order.slice(0,k)}
export function doorOptions(door,seed=door.seed){const stable=door.pages.filter(p=>p.group==="stable"),found=door.pages.filter(p=>p.group==="discover"),drawn=doorDraw(seed,found.length,door.k).map(i=>found[i]);
 return[stable[0],...drawn,...stable.slice(1)].map(p=>({...p,current:p.href===door.current,drawn:drawn.includes(p)}))}
const safe=href=>{try{const u=new URL(href,location.href);return u.protocol==="http:"||u.protocol==="https:"}catch(e){return false}};
export function bindDoor(root=document){return[...root.querySelectorAll("[data-ui-door]")].map(box=>{
 const door=JSON.parse(box.dataset.door),$=s=>box.querySelector(s),select=$("[data-door-select]"),status=$("[data-door-status]");let seed=door.seed;
 const fill=()=>{select.replaceChildren(...doorOptions(door,seed).map(o=>{const op=document.createElement("option");op.value=o.href;op.textContent=o.emoji+" "+o.label+(o.current?" (current)":"");if(o.current){op.selected=true;op.disabled=true}return op}))};
 select.addEventListener("change",()=>{const href=select.value,page=door.pages.find(p=>p.href===href);if(!page||href===door.current)return;
  const stay=!box.dispatchEvent(new CustomEvent("ui-door-leave",{cancelable:true,bubbles:true,detail:{href,emoji:page.emoji,label:page.label}}));
  if(stay){fill();status.textContent="Staying here.";return}
  if(!safe(href)){status.textContent="That destination is not allowed.";fill();return}
  status.textContent="Opening "+page.label+"…";box.dispatchEvent(new CustomEvent("ui-door-go",{bubbles:true,detail:{href}}));if(!box.hasAttribute("data-door-dry"))location.assign(href)});
 $("[data-door-draw]").addEventListener("click",()=>{seed=Math.floor(Math.random()*4294967296);fill();box.setAttribute("data-door-draws",String(Number(box.getAttribute("data-door-draws")||0)+1));status.textContent="Drew new entries (seed "+seed+")."});
 const input=$("[data-door-notation]"),path=$("[data-door-path]"),note=$("[data-door-note]");
 const show=()=>{try{const hrefs=emojiPath(input.value,door.pages);path.replaceChildren(...hrefs.map(h=>{const li=document.createElement("li"),a=document.createElement("a");a.textContent=h;if(safe(h))a.href=h;li.append(a);return li}));note.textContent=hrefs.length+" page(s)."}catch(e){path.replaceChildren();note.textContent=e.message}};
 input.addEventListener("input",show);fill();show();box.dataset.door_ready="";return box})}
globalThis.webUiDoor={emojiKey,emojiPath,mulberry32,doorDraw,doorOptions,bindDoor};
if(typeof document!=="undefined")bindDoor();
"""

_JS["shelf.js"] = r"""/* web-ui shelf: a clipboard shelf in the page (memory only). The rules are Python's (web_ui.shelf_classify, decode_image_text, ...); this must agree. */
const MAX_IMAGE=32*1024*1024;
const SPACE="\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
export const strip=s=>(s.startsWith("﻿")?s.slice(1):s).replace(new RegExp("^["+SPACE+"]+|["+SPACE+"]+$","g"),"");
const lines=t=>t.replace(/\r\n/g,"\n").replace(/\r/g,"\n").split("\n");
const URLRE=/^https?:\/\/[^ \t\r\n\f\v<>"]+$/i,LINE_MD=/^[ \t]{0,3}(?:#{1,6}[ \t]|[-*+][ \t]|>[ \t]|```)/,LINK_MD=/\[[^\]]+\]\([^)]+\)/;
const B64=/^[A-Za-z0-9+/]*={0,2}$/,DATA=/^data:([a-z0-9.+-]+\/[a-z0-9.+-]+)?((?:;[a-z0-9.+-]+=[a-z0-9.+-]+)*);base64,/i;
export function shelfClassify(text){if(URLRE.test(strip(text)))return"url";return lines(text).some(l=>LINE_MD.test(l))||LINK_MD.test(text)?"markdown":"text"}
export function markdownPlain(text){
 let out=lines(text).map(l=>{l=l.replace(/^[ \t]{0,3}#{1,6}[ \t]+/,"").replace(/^[ \t]{0,3}>[ \t]?/,"").replace(/^[ \t]*[-*+][ \t]+/,"").replace(/^[ \t]*\d+[.)][ \t]+/,"");return/^[ \t]*```[^\n]*$/.test(l)?"":l}).join("\n");
 out=out.replace(/\[([^\]]+)\]\(([^)]+)\)/g,"$1 ($2)").replace(/`([^`\n]+)`/g,"$1").replace(/\*\*([^*\n]+)\*\*/g,"$1").replace(/~~([^~\n]+)~~/g,"$1");
 return strip(out)}
export const shelfMaxChars=n=>4*Math.floor((n+2)/3);
export function looksLikeImage(text,minChars=80){text=strip(text);if(text.slice(0,11).toLowerCase()==="data:image/")return true;const c=text.replace(/[ \t\r\n\f\v]+/g,"");return c.length>=minChars&&c.length%4===0&&B64.test(c)}
export function decodeImageText(input,maxBytes=MAX_IMAGE){
 const fail=category=>({ok:false,category});let text=strip(input);if(!text)return fail("empty");
 let declared=null;const m=DATA.exec(text);
 if(m){declared=(m[1]||"").toLowerCase()||null;if(declared==="image/jpg")declared="image/jpeg";text=text.slice(m[0].length)}
 else if(text.slice(0,5).toLowerCase()==="data:")return fail("bad_data_uri");
 if(declared!==null&&!["image/png","image/jpeg","image/webp"].includes(declared))return fail("unsupported_type");
 const encoded=text.replace(/[ \t\r\n\f\v]+/g,"");if(!encoded)return fail("empty");
 if(encoded.length>shelfMaxChars(maxBytes))return fail("too_large");
 if(encoded.length%4||!B64.test(encoded))return fail("bad_base64");
 const pad=encoded.endsWith("==")?2:encoded.endsWith("=")?1:0,n=encoded.length/4*3-pad;
 if(n<=0)return fail("empty");if(n>maxBytes)return fail("too_large");
 const head=atob(encoded.slice(0,16)),at=i=>head.charCodeAt(i);
 const mime=head.length>=8&&[0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a].every((v,i)=>at(i)===v)?"image/png":head.length>=3&&at(0)===0xff&&at(1)===0xd8&&at(2)===0xff?"image/jpeg":head.length>=12&&head.slice(0,4)==="RIFF"&&head.slice(8,12)==="WEBP"?"image/webp":null;
 if(mime===null)return fail("unsupported_format");if(declared!==null&&declared!==mime)return fail("mismatch");
 return{ok:true,format:mime.slice(6),mime,bytes:n,data:encoded}}
export function buildPrompt(fields,image=null){
 let out="# System Prompt Draft\n\n";
 for(const[key,title]of[["goal","Goal"],["context","Context / reference material"],["must","Must include"],["avoid","Constraints / avoid"],["format","Output format"],["raw","Raw source"]]){const v=strip(String(fields[key]??""));if(v)out+="## "+title+"\n"+v+"\n\n"}
 if(image)out+="## Visual reference\nAn image reference is attached in the workbench ("+(image.mime||"image")+", "+image.bytes+" bytes).\nUse its layout/content as visual context when the receiving system supports image input.\n\n";
 return out.replace(/[ \t\r\n\f\v]+$/,"")}
export function shelfBundle(items){const labels={text:"Text",url:"URL",markdown:"Markdown",image:"Image"};let out="# Context Bundle\n\n";
 items.forEach((it,i)=>{out+="## "+(i+1)+". "+labels[it.kind]+"\n"+(it.kind==="image"?"data:"+it.mime+";base64,"+it.data:(it.text??""))+"\n\n"});return out.replace(/[ \t\r\n\f\v]+$/,"")}
export function bindShelf(root=document){return[...root.querySelectorAll("[data-ui-shelf]")].map(box=>{
 const $=s=>box.querySelector(s),input=$("[data-shelf-input]"),list=$("[data-shelf-items]"),status=$("[data-shelf-status]"),prompt=$("[data-shelf-prompt]");
 const items=[];let next=1,image=null,manual=[];const say=t=>{status.textContent=t};
 const checked=name=>box.querySelector('input[name="'+name+'"]:checked').value;
 const display=()=>{const kind=checked("shelf-kind"),sort=checked("shelf-sort");const vis=items.filter(i=>kind==="all"||i.kind===kind);
  return sort==="oldest"?[...vis].sort((a,b)=>a.n-b.n):sort==="manual"?[...vis].sort((a,b)=>manual.indexOf(a.id)-manual.indexOf(b.id)):[...vis].sort((a,b)=>b.n-a.n)};
 const draw=()=>{list.replaceChildren(...items.map(it=>{const li=document.createElement("li");li.className="ui-shelf-item";li.dataset.kind=it.kind;li.dataset.id=it.id;li.style.setProperty("--n",it.n);li.style.setProperty("--pos",manual.indexOf(it.id));
  const tag=document.createElement("span");tag.className="ui-tag";tag.textContent={text:"Text",url:"URL",markdown:"Markdown",image:"Image"}[it.kind];
  const pick=document.createElement("input");pick.type="checkbox";pick.checked=!!it.picked;pick.setAttribute("aria-label","Select item "+it.id);pick.addEventListener("change",()=>{it.picked=pick.checked});
  const body=document.createElement("div");body.className="ui-shelf-body";
  if(it.kind==="image"){const img=document.createElement("img");img.alt="Pasted "+it.format+" image, "+it.bytes+" bytes";img.src="data:"+it.mime+";base64,"+it.data;body.append(img)}
  else if(it.kind==="url"){const a=document.createElement("a");a.textContent=it.text;a.href=it.text;a.target="_blank";a.rel="noopener noreferrer";body.append(a)}
  else{const p=document.createElement("pre");p.textContent=it.text;body.append(p)}
  const tools=document.createElement("div");tools.className="ui-shelf-tools";
  const btn=(label,act)=>{const b=document.createElement("button");b.type="button";b.className="ui-button";b.textContent=label;b.dataset.act=act;tools.append(b)};
  btn("Copy","copy");if(it.kind==="markdown")btn("Copy plain","plain");btn("Up","up");btn("Down","down");btn("Remove","remove");
  li.append(pick,tag,body,tools);return li}));
  const none=items.length===0;if(none)say("Nothing on the shelf yet.")};
 const add=it=>{it.id=next;it.n=next++;items.unshift(it);manual.unshift(it.id);draw()};
 const addText=raw=>{const text=strip(raw);if(!text){say("Nothing to add.");return false}
  if(looksLikeImage(text)){const r=decodeImageText(text);if(r.ok){add({kind:"image",...r});say("Image added ("+r.format+", "+r.bytes+" bytes).");return true}
   add({kind:shelfClassify(text),text});say("Added as text: it looked like an image but was refused ("+r.category+").");return true}
  add({kind:shelfClassify(text),text});say("Added.");return true};
 const copy=async t=>{try{await navigator.clipboard.writeText(t);return true}catch(e){return false}};
 $("[data-shelf-add]").addEventListener("click",()=>{if(addText(input.value))input.value=""});
 $("[data-shelf-paste]").addEventListener("click",async()=>{let t="";try{t=await navigator.clipboard.readText()}catch(e){say("The browser did not allow reading the clipboard: paste into the box instead.");return}addText(t)});
 $("[data-shelf-clear]").addEventListener("click",()=>{items.length=0;manual=[];draw();say("Shelf cleared.")});
 $("[data-shelf-bundle]").addEventListener("click",async()=>{const picked=items.filter(i=>i.picked),shown=display(),use=picked.length?display().filter(i=>i.picked):shown;
  if(!items.length){say("The shelf is empty.");return}const text=shelfBundle(use);say(await copy(text)?"Copied a bundle of "+use.length+" item(s), "+text.length+" characters.":"The browser did not allow copying.")});
 list.addEventListener("click",async e=>{const b=e.target.closest("button[data-act]");if(!b)return;const id=Number(b.closest("li").dataset.id),it=items.find(i=>i.id===id);
  if(b.dataset.act==="remove"){items.splice(items.indexOf(it),1);manual=manual.filter(x=>x!==id);draw();say("Removed.")}
  else if(b.dataset.act==="copy"){say(await copy(it.kind==="image"?"data:"+it.mime+";base64,"+it.data:it.text)?"Copied.":"The browser did not allow copying.")}
  else if(b.dataset.act==="plain"){say(await copy(markdownPlain(it.text))?"Copied as plain text.":"The browser did not allow copying.")}
  else{const shown=display(),at=shown.indexOf(it),to=at+(b.dataset.act==="up"?-1:1);if(to<0||to>=shown.length)return;
   if(checked("shelf-sort")!=="manual"){manual=[...items].sort((a,c)=>checked("shelf-sort")==="oldest"?a.n-c.n:c.n-a.n).map(i=>i.id)}
   const a=manual.indexOf(id),c=manual.indexOf(shown[to].id);[manual[a],manual[c]]=[manual[c],manual[a]];box.querySelector("#shelf-sort-manual").checked=true;draw();say("Order is now manual.")}});
 const fields=()=>({goal:$("[name=goal]").value,context:$("[name=context]").value,must:$("[name=must]").value,avoid:$("[name=avoid]").value,format:$("[name=format]").value,raw:$("[name=raw]").value});
 const render=()=>{prompt.textContent=buildPrompt(fields(),image)};
 for(const f of box.querySelectorAll("[data-shelf-field]"))f.addEventListener("input",render);
 $("[data-shelf-attach]").addEventListener("click",()=>{const picked=items.find(i=>i.kind==="image"&&i.picked)||items.find(i=>i.kind==="image");image=picked?{mime:picked.mime,bytes:picked.bytes}:null;say(image?"Image attached to the prompt.":"No image on the shelf to attach.");render()});
 $("[data-shelf-copy-prompt]").addEventListener("click",async()=>{const t=buildPrompt(fields(),image);say(await copy(t)?"Copied the prompt ("+t.length+" characters).":"The browser did not allow copying.")});
 draw();render();return box})}
globalThis.webUiShelf={shelfClassify,markdownPlain,looksLikeImage,decodeImageText,buildPrompt,shelfBundle,shelfMaxChars,bindShelf};
if(typeof document!=="undefined")bindShelf();
"""

_JS["curl.js"] = r"""/* web-ui curl: the editor's curl subset, read in the page and never run or sent. Python (web_ui.parse_curl) is the reference; this must agree with it. */
const P="httpDraft.curl.",MAX_BYTES=65536,MAX_TOKENS=4096;
const fail=n=>{throw new Error(P+"error."+n)};
const OPTIONS=new Map(Object.entries({"-X":"method","--request":"method","--url":"url","-H":"header","--header":"header","-d":"data","--data":"data","--data-raw":"data","--data-binary":"data","--data-urlencode":"urlencode","-u":"user","--user":"user","-A":"agent","--user-agent":"agent","-e":"referer","--referer":"referer"}));
const IGNORED=new Set(["-s","-S","-i","-v","-k","--silent","--show-error","--include","--verbose","--insecure"]),METHODS=new Set(["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"]);
const SECRET_NAMES=new Set(["authorization","proxy-authorization","cookie","set-cookie","x-api-key","api-key","x-auth-token","key","sig","sas"]);
const SECRET_PARTS=["api-key","api_key","token","secret","password","signature","credential","access_key","access-key","sharedaccesssignature"];
const SPACE="\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const strip=s=>s.replace(new RegExp("^["+SPACE+"]+|["+SPACE+"]+$","g"),""),lstrip=s=>s.replace(new RegExp("^["+SPACE+"]+"),"");
const ascii=s=>{let o="";for(const c of s){const n=c.codePointAt(0);o+=n>=0xFF01&&n<=0xFF5E?String.fromCodePoint(n-0xFEE0):n===0x3000?" ":n===0x2212?"-":c}return o};
export function curlTokenize(raw){
 if(typeof raw!=="string")fail("inputType");
 if(!raw.isWellFormed())fail("encoding");
 if(new TextEncoder().encode(raw).length>MAX_BYTES)fail("inputTooLarge");
 if(raw.includes("\0"))fail("nul");
 let text=strip(ascii(raw));if(!text)fail("empty");
 text=text.replace(/\\\r?\n/g," ");
 const tokens=[];let buf="",quote="",started=false;
 const flush=()=>{if(started){tokens.push(buf);if(tokens.length>MAX_TOKENS)fail("tooManyTokens");buf="";started=false}};
 for(let i=0;i<text.length;i++){const c=text[i];
  if(quote){if(c===quote)quote="";else if(quote==='"'&&c==="\\"&&i+1<text.length){i++;const f=text[i];if(!'$`"\\\n'.includes(f))buf+="\\";buf+=f}else buf+=c}
  else if(c==="'"||c==='"'){quote=c;started=true}
  else if("`$|;<>".includes(c))fail("shellMeta");
  else if(" \t\r\n".includes(c))flush();
  else{started=true;buf+=c}}
 if(quote)fail("unbalancedQuotes");
 flush();return tokens}
const field=(name,value,sensitive=false)=>({name,value,sensitive});
const isSensitive=name=>{name=strip(ascii(name)).toLowerCase();return SECRET_NAMES.has(name)||name.endsWith("_key")||name.endsWith("-key")||SECRET_PARTS.some(p=>name.includes(p))};
const pairs=raw=>{if(/%(?![0-9a-fA-F]{2})/.test(raw))fail("queryEncoding");const out=[];
 for(const part of raw.split("&")){if(!part)continue;const i=part.indexOf("="),n=i<0?part:part.slice(0,i),v=i<0?"":part.slice(i+1);
  try{out.push(field(decodeURIComponent(n.replace(/\+/g," ")),decodeURIComponent(v.replace(/\+/g," "))))}catch(e){fail("queryEncoding")}}
 return out};
const base64=text=>{let b="";for(const x of new TextEncoder().encode(text))b+=String.fromCharCode(x);return btoa(b)};
export function parseCurl(raw){
 const errors=[],warnings=[];
 try{
  const tokens=curlTokenize(raw);if(!tokens.length||tokens[0].toLowerCase()!=="curl")fail("notCurl");
  let method="GET",explicit=false,url=null,useGet=false,index=1;const headers=[],chunks=[],encoded=[];
  while(index<tokens.length){const token=tokens[index++];
   let flag=token,sep=false,inline="";if(token.startsWith("--")){const i=token.indexOf("=");if(i>=0){flag=token.slice(0,i);sep=true;inline=token.slice(i+1)}}
   const kind=OPTIONS.get(flag);
   if(kind){let value;
    if(sep)value=inline;else if(index<tokens.length)value=tokens[index++];else{errors.push(P+"error.missingArg");break}
    if(kind==="method"){const m=strip(value).toUpperCase();if(!METHODS.has(m))errors.push(P+"error.badMethod");else{method=m;explicit=true}}
    else if(kind==="url")url=value;
    else if(kind==="header"){const v=strip(value),i=v.indexOf(":"),name=strip(i<0?v:v.slice(0,i)),content=strip(i<0?"":v.slice(i+1));
     if(i<0||!name||/[\r\n]/.test(name+content))errors.push(P+"error.badHeader");else headers.push(field(name,content,isSensitive(name)||content.includes("***")))}
    else if(kind==="data"||kind==="urlencode"){const at=value.indexOf("@"),eq=value.indexOf("=");
     if(value.startsWith("@")||(kind==="urlencode"&&at>=0&&(eq<0||at<eq)))errors.push(P+"error.fileBody");
     else if(kind==="data")chunks.push(value);
     else{const i=value.indexOf("=");encoded.push(field(i<0?value:value.slice(0,i),i<0?"":value.slice(i+1)))}}
    else if(kind==="user"){headers.push(field("Authorization","Basic "+base64(value),true));warnings.push(P+"warn.basicAuthMapped")}
    else headers.push(field(kind==="agent"?"User-Agent":"Referer",value))}
   else if(flag==="-G"||flag==="--get")useGet=true;
   else if(flag==="-I"||flag==="--head"){method="HEAD";explicit=true}
   else if(flag==="-L"||flag==="--location")warnings.push(P+"warn.ignoredRedirect");
   else if(IGNORED.has(flag))warnings.push(P+"warn.ignoredFlag");
   else if(token.startsWith("-")&&token.length>1)errors.push(P+"error.unsupportedFlag");
   else if(url!==null)errors.push(P+"error.extraPositional");
   else url=token}
  if(errors.length)return{ok:false,draft:null,errors,warnings};
  if(url===null||!strip(url))fail("urlRequired");
  let mode="none",rawBody="",query=[],form=[];
  if(encoded.length){if(useGet)query=encoded;else{mode="formUrlEncoded";form=encoded;if(!explicit)method="POST"}}
  else if(chunks.length){const joined=chunks.join("&");
   if(useGet)query=pairs(joined);
   else{if(!explicit)method="POST";const h=headers.find(h=>h.name.toLowerCase()==="content-type"),type=h?h.value.toLowerCase():"";
    if(type.includes("application/json")){mode="json";rawBody=joined}
    else if(type.includes("application/x-www-form-urlencoded")){mode="formUrlEncoded";form=pairs(joined)}
    else if(/^[{\[]/.test(lstrip(joined))){mode="json";rawBody=joined}
    else if(joined.includes("=")){mode="formUrlEncoded";form=pairs(joined)}
    else{mode="raw";rawBody=joined}}}
  const rows=items=>items.filter(i=>i.name||i.value);
  return{ok:true,draft:{method,url:strip(url),headers:rows(headers),query:rows(query),bodyMode:mode,rawBody,formFields:rows(form)},errors:[],warnings}
 }catch(e){if(e instanceof Error&&e.message.startsWith(P+"error."))return{ok:false,draft:null,errors:[e.message],warnings};throw e}}
export function maskCurl(result){const out=JSON.parse(JSON.stringify(result));for(const g of["headers","query","formFields"])for(const f of(out.draft||{})[g]||[])if(f.sensitive)f.value="***";return out}
export function bindCurl(root=document){return[...root.querySelectorAll("[data-ui-curl]")].map(box=>{
 const input=box.querySelector("[data-curl-input]"),output=box.querySelector("[data-curl-output]"),run=()=>{output.textContent=JSON.stringify(maskCurl(parseCurl(input.value)),null,2)};
 box.querySelector("[data-curl-run]").addEventListener("click",run);input.addEventListener("input",run);run();return box})}
globalThis.webUiCurl={curlTokenize,parseCurl,maskCurl,bindCurl};
if(typeof document!=="undefined")bindCurl();
"""
_STUB_FILL_JS = ('const fill=(t,q)=>typeof t==="string"?t.replaceAll("$input",()=>q):Array.isArray(t)?t.map(x=>fill(x,q)):'
                 't&&typeof t==="object"?Object.fromEntries(Object.entries(t).map(([k,v])=>[k,fill(v,q)])):t;\n')


def stub_response(template: Any, query: str) -> Any:
    """What the mock answers for ``query``: ``template`` with every "$input" replaced by the query (same rule as the page)."""
    if isinstance(template, str):
        return template.replace("$input", query)
    if isinstance(template, list):
        return [stub_response(item, query) for item in template]
    if isinstance(template, dict):
        return {key: stub_response(value, query) for key, value in template.items()}
    return template


def stub_validate(spec: Any) -> dict[str, Any]:
    """Checked ``web-ui-stub/1`` spec: id, title, heading, lead, tags, field, run, evidence, history and the mock template."""
    keys = {"schema", "id", "title", "heading", "lead", "tags", "field", "run", "evidence", "history", "mock"}
    if not isinstance(spec, dict) or spec.get("schema") != STUB_SCHEMA or set(spec) - keys:
        raise ValueError(f"expected schema {STUB_SCHEMA} with keys {sorted(keys)}")
    stub_id = spec.get("id", "stub")
    if not isinstance(stub_id, str) or not _WORLD_ID.fullmatch(stub_id):
        raise ValueError("id must be a lowercase token that starts with a letter")
    tags = spec.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 6:
        raise ValueError("tags must list at most 6 entries")
    field = spec.get("field")
    if not isinstance(field, dict) or set(field) - {"label", "placeholder", "value"} or "label" not in field:
        raise ValueError("field has a label and optionally a placeholder or a value")
    mock = spec.get("mock", {"status": "stub", "query": "$input"})
    try:
        encoded_mock = json.dumps(mock, allow_nan=False)
        mock = json.loads(encoded_mock)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("mock must be finite JSON data") from exc
    if len(encoded_mock) > 4000:
        raise ValueError("mock must be at most 4000 characters of JSON")
    return {"schema": STUB_SCHEMA, "id": stub_id, "title": _world_text(spec.get("title", "Stub"), "title", 80),
            "heading": _world_text(spec.get("heading", "Stub Explorer"), "heading", 80),
            "lead": _world_text(spec.get("lead", ""), "lead", 200, required=False),
            "tags": [_world_text(tag, "tag", 24) for tag in tags],
            "field": {"label": _world_text(field["label"], "field label", 40),
                      "placeholder": _world_text(field.get("placeholder", ""), "placeholder", 120, required=False),
                      "value": _world_text(field.get("value", ""), "value", 120, required=False)},
            "run": _world_text(spec.get("run", "Run"), "run", 24),
            "evidence": _world_text(spec.get("evidence", ""), "evidence", 200, required=False),
            "history": _world_text(spec.get("history", ""), "history", 200, required=False), "mock": mock}


def stub_html(spec: Any, *, heading_level: int = 1) -> str:
    """The stub workspace (request bar, result, evidence, history) with ids prefixed by the spec's id; text is escaped."""
    s = stub_validate(spec)
    level = heading_level if type(heading_level) is int and 1 <= heading_level <= 6 else 1
    sid, field = s["id"], s["field"]
    attrs = (f' placeholder="{escape(field["placeholder"], quote=True)}"' if field["placeholder"] else "") + \
            (f' value="{escape(field["value"], quote=True)}"' if field["value"] else "")
    tags = "".join(f'<span class="ui-tag">{escape(tag)}</span>' for tag in s["tags"])
    mock = json.dumps(s["mock"], ensure_ascii=False).replace("</", "<\\/")
    return (f'<div class="stub-shell" id="{sid}"><header class="stub-header"><div><h{level} class="ui-title">{escape(s["heading"])}</h{level}>'
            f'<p class="ui-muted">{escape(s["lead"])}</p></div><div class="stub-meta">{tags}</div></header>'
            f'<section class="ui-panel"><form class="stub-toolbar" id="{sid}-form"><fieldset><legend>Stub request</legend>'
            f'<label for="{sid}-query">{escape(field["label"])}</label><input class="ui-input" id="{sid}-query"{attrs}>'
            f'<button class="ui-button" id="{sid}-run" type="submit">{escape(s["run"])}</button></fieldset></form>'
            '<p class="stub-status ui-muted">Endpoint: <span class="stub-endpoint">consumer-owned</span></p></section>'
            f'<div class="stub-workspace"><section class="ui-panel stub-result"><h2>Result</h2>'
            f'<pre class="ui-output" id="{sid}-output" aria-live="polite">Ready.</pre></section>'
            '<aside aria-label="Supporting information"><section class="ui-card stub-evidence"><h2>Evidence</h2>'
            f'<p class="ui-muted">{escape(s["evidence"])}</p></section><section class="ui-card stub-history"><h2>History</h2>'
            f'<p class="ui-muted">{escape(s["history"])}</p><div class="stub-actions"><button class="ui-button" type="button">Export</button>'
            f'<button class="ui-button" type="button">Clear</button></div></section></aside></div>'
            f'<script type="application/json" id="{sid}-mock">{mock}</script></div>')


def stub_script(*specs: Any) -> str:
    """One inline module for any number of stubs on a page: ui.js, stub.js, the mock evaluator and one bind per stub."""
    binds = "".join(
        f'bindStub({{input:"#{s["id"]}-query",run:"#{s["id"]}-run",output:"#{s["id"]}-output",form:"#{s["id"]}-form",'
        f'handler:q=>fill(JSON.parse(document.getElementById("{s["id"]}-mock").textContent),q)}});\n'
        for s in (stub_validate(spec) for spec in specs))
    return EMBEDDED_UI_JS + EMBEDDED_STUB_JS + _STUB_FILL_JS + binds


def stub_document(spec: Any, *, theme: str = "modern") -> str:
    """A single-file page for one stub."""
    s = stub_validate(spec)
    return render_document(trusted_html='<main class="ui-page">' + stub_html(s) + "</main>"
                           + module_script(stub_script(s)), title=s["title"], theme=theme, css=bundled_css())


EXAMPLE_STUBS = {
    "mcp": {"schema": STUB_SCHEMA, "id": "mcp", "title": "MCP Stub", "heading": "MCP Stub Explorer",
            "lead": "Protocol behavior stays with the consumer; web-ui supplies presentation and generic interaction.",
            "tags": ["mcp", "ready"], "field": {"label": "Tool or filter", "placeholder": "tools/list"}, "run": "Run",
            "evidence": "Trace, source, SHA, or request metadata can be rendered here by the consumer.",
            "history": "Consumer-owned history/export controls.",
            "mock": {"kind": "mcp", "query": "$input", "status": "stub"}},
    "api": {"schema": STUB_SCHEMA, "id": "api", "title": "API Stub", "heading": "API Stub Explorer",
            "lead": "A generic request/result surface without API-specific logic in web-ui.",
            "tags": ["api", "ready"], "field": {"label": "Path", "value": "/api/example"}, "run": "Send",
            "evidence": "Status, headers, provenance, or timing metadata belongs here.",
            "history": "Consumer-owned request history and export actions.",
            "mock": {"method": "GET", "path": "$input", "status": 200, "body": {"stub": True}}},
}


_JS["photo.js"] = r"""/* web-ui photo: the photo studio in the page (memory only). Format hints, header sizes, EXIF orientation, import rules, frame and stamp geometry, undo history and the editing state machine.
   The rules are Python's (web_ui.photo_sniff, photo_decide, PhotoStudio, ...); this must agree. Nothing is stored or sent. */
const MAX_BYTES=32*1024*1024,MAX_PIXELS=40000000,MAX_EDGE=4096,DOWNSCALE=2/3,MIN_SIZE=0.04,HISTORY_LIMIT=20,HANDLE_SLOP=18,STAMP_MIN_HIT=18;
export const EXPORT_NAME="photo-studio.png";
export const LABELS={empty:"empty",png:"PNG",jpeg:"JPEG",webp:"WebP",gif:"GIF",avif:"AVIF",heic:"HEIC",unknown:"unknown"};
const HEIC=["heic","heif","mif1","msf1","heix"];
export const STAMPS=["⭐","❤️","😊","🔥","📷","🌸","✨","🍀"];
export const COLORS=[["Purple","#7e57c2"],["Red","#e53935"],["Green","#43a047"],["Blue","#1e88e5"],["Amber","#fdd835"],["White","#ffffff"],["Black","#212121"]];
export const SHAPES=["rectangle","circle","triangle"];
export const HANDLES=["move","topLeft","topRight","bottomLeft","bottomRight","left","right","top","bottom"];
export const OUTCOMES=["supported","rejected:empty","rejected:tooLargeBytes","rejected:tooManyPixels","rejected:heicConversionFailed","rejected:undecodable","unsupported_by_runtime","not_verified"];
export const MESSAGES={idle:"Select an image or paste here",loading:"Loading image…",success:"Image loaded",cancelled:"No change.",superseded:"A newer import replaced this load.",
 noClipboardImage:"Clipboard has no photo to paste.",clipboardUnavailable:"This browser did not allow clipboard image access. Use Import image, or paste again after allowing permission.",
 pickFailed:"Could not decode this image.",decodeFailed:"Could not decode this image.",tooLarge:"That photo is too large. Choose a smaller image or screenshot.",
 tooLargeBytes:"That photo is too large. Choose a smaller image or screenshot.",tooManyPixels:"That photo has too many pixels. Choose a smaller image or screenshot.",
 heicUnsupported:"This HEIC/HEIF photo cannot be decoded in this browser. Export it as JPEG or PNG first.",unsupportedFormat:"That image format could not be decoded."};
const FAILURES={empty:"decodeFailed",tooLargeBytes:"tooLargeBytes",tooManyPixels:"tooManyPixels",undecodable:"unsupportedFormat",heicConversionFailed:"heicUnsupported"};
const halfUp=v=>{const f=Math.floor(v);return v-f>=0.5?f+1:f},clamp=(v,lo,hi)=>Math.min(Math.max(v,lo),hi),dist=(dx,dy)=>Math.sqrt(dx*dx+dy*dy);
export const fixed=(v,n)=>v.toFixed(n);
const be32=(b,i)=>b[i]*16777216+(b[i+1]<<16|b[i+2]<<8|b[i+3]),le16=(b,i)=>b[i]|b[i+1]<<8;
const at=(b,i,s)=>{for(let k=0;k<s.length;k++)if(b[i+k]!==s.charCodeAt(k))return false;return true};
const brandAt=b=>b.length<12||!at(b,4,"ftyp")?null:String.fromCharCode(b[8],b[9],b[10],b[11]);
function jpegProgressive(b){let i=2;const n=b.length;while(i+3<n){if(b[i]!==0xFF)return false;const m=b[i+1];if(m===0xFF){i+=1;continue}
 if(m===0xD9||m===0xDA)return false;if(m===0xC2||m===0xC6||m===0xCA||m===0xCE)return true;if(m===0xC0||m===0xC1||m===0xC3||m===0xC9||m===0xCB)return false;
 if((m>=0xD0&&m<=0xD7)||m===0||m===1){i+=2;continue}const len=(b[i+2]<<8)|b[i+3];if(len<2)return false;i+=2+len}return false}
function exifOrientation(b,start,end){const seg=b.subarray(start,end);if(seg.length<14||!at(seg,0,"Exif")||seg[4]!==0||seg[5]!==0)return null;const t=seg.subarray(6);
 const big=t[0]===0x4D&&t[1]===0x4D;if(!(big||(t[0]===0x49&&t[1]===0x49)))return null;
 const u16=o=>o+1>=t.length?-1:big?(t[o]<<8|t[o+1]):(t[o]|t[o+1]<<8),u32=o=>o+3>=t.length?-1:big?t[o]*16777216+(t[o+1]<<16|t[o+2]<<8|t[o+3]):t[o+3]*16777216+(t[o+2]<<16|t[o+1]<<8|t[o]);
 const ifd=u32(4);if(ifd<0||ifd+2>t.length)return null;const count=u16(ifd);
 for(let e=0;e<count;e++){const entry=ifd+2+e*12;if(entry+12>t.length)return null;if(u16(entry)!==0x0112)continue;if(u16(entry+2)!==3||u32(entry+4)!==1)return null;
  const v=u16(entry+8);return v>=1&&v<=8?[v,start+6+entry+8,big]:null}return null}
function jpegOrientation(b){let i=2;const n=b.length;while(i+8<n){if(b[i]!==0xFF)return null;const m=b[i+1];if(m===0xFF){i+=1;continue}if(m===0xD9||m===0xDA)return null;
 const len=(b[i+2]<<8)|b[i+3];if(m===0xE1){if(len<8||i+2+len>n)return null;if(len-2>=6&&at(b,i+4,"Exif"))return exifOrientation(b,i+4,i+2+len);i+=2+len;continue}
 if(m>=0xD0&&m<=0xD7){i+=2;continue}if(len<2)return null;i+=2+len}return null}
export function sniff(b){const n=b.length,info={kind:"unknown",brand:null,progressive:null,orientation:null,orientation_offset:null,orientation_big_endian:null};
 if(n===0)info.kind="empty";else if(n>=8&&b[0]===0x89&&at(b,1,"PNG")&&b[4]===13&&b[5]===10&&b[6]===26&&b[7]===10)info.kind="png";
 else if(n>=3&&b[0]===0xFF&&b[1]===0xD8&&b[2]===0xFF){info.kind="jpeg";info.progressive=jpegProgressive(b);const f=jpegOrientation(b);if(f){info.orientation=f[0];info.orientation_offset=f[1];info.orientation_big_endian=f[2]}}
 else if(n>=12&&at(b,0,"RIFF")&&at(b,8,"WEBP"))info.kind="webp";else if(n>=6&&at(b,0,"GIF8")&&(b[4]===0x39||b[4]===0x37)&&b[5]===0x61)info.kind="gif";
 else{const brand=brandAt(b);if(HEIC.includes(brand)){info.kind="heic";info.brand=brand}else if(brand==="avif"||brand==="avis"){info.kind="avif";info.brand=brand}}
 info.label=LABELS[info.kind];return info}
export function pngComplete(b){if(!(b.length>=8&&b[0]===0x89&&at(b,1,"PNG")&&b[4]===13&&b[5]===10&&b[6]===26&&b[7]===10))return false;let i=8,first=true;const n=b.length;
 while(i+12<=n){const len=be32(b,i);if(first&&!at(b,i+4,"IHDR"))return false;first=false;if(at(b,i+4,"IEND"))return true;if(len>n)return false;i+=12+len}return false}
export function neutralizeOrientation(b){const info=sniff(b),out=new Uint8Array(b);if(info.orientation===null||info.orientation===1)return out;
 const o=info.orientation_offset;if(info.orientation_big_endian){out[o]=0;out[o+1]=1}else{out[o]=1;out[o+1]=0}return out}
export function headerSize(b){const n=b.length;
 if(n>=8&&b[0]===0x89&&at(b,1,"PNG")&&b[4]===13&&b[5]===10&&b[6]===26&&b[7]===10)return n>=24&&at(b,12,"IHDR")?[be32(b,16),be32(b,20)]:null;
 if(n>=10&&at(b,0,"GIF8")&&(b[4]===0x39||b[4]===0x37)&&b[5]===0x61)return[le16(b,6),le16(b,8)];
 if(n>=3&&b[0]===0xFF&&b[1]===0xD8&&b[2]===0xFF){let i=2;while(i+3<n){if(b[i]!==0xFF)return null;const m=b[i+1];if(m===0xFF){i+=1;continue}if(m===0xD9||m===0xDA)return null;
   if((m>=0xD0&&m<=0xD7)||m===0||m===1){i+=2;continue}const len=(b[i+2]<<8)|b[i+3];
   if([0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF].includes(m)){if(len<8||i+9>n)return null;return[(b[i+7]<<8)|b[i+8],(b[i+5]<<8)|b[i+6]]}
   if(len<2)return null;i+=2+len}return null}
 if(n>=16&&at(b,0,"RIFF")&&at(b,8,"WEBP")){if(at(b,12,"VP8 ")&&n>=30&&b[23]===0x9D&&b[24]===0x01&&b[25]===0x2A)return[le16(b,26)&0x3FFF,le16(b,28)&0x3FFF];
  if(at(b,12,"VP8L")&&n>=25&&b[20]===0x2F){const bits=(b[21]|b[22]<<8|b[23]<<16)+b[24]*16777216;return[(bits&0x3FFF)+1,(Math.floor(bits/16384)&0x3FFF)+1]}
  if(at(b,12,"VP8X")&&n>=30)return[(b[24]|b[25]<<8|b[26]<<16)+1,(b[27]|b[28]<<8|b[29]<<16)+1]}
 return null}
const OPS={2:["flipX",0,true,false],3:["rotate",180,false,false],4:["flipY",0,false,true],5:["transpose",90,true,false],6:["rotate",90,false,false],7:["transverse",-90,true,false],8:["rotate",-90,false,false]};
export const orientationOp=o=>{const op=Number.isInteger(o)&&typeof o==="number"?OPS[o]:undefined;return op?{op:op[0],degrees:op[1],flip_x:op[2],flip_y:op[3]}:null};
export const orientedSize=(w,h,o)=>o>=5&&o<=8?[h,w]:[w,h];
export const orientationMatrix=(o,w,h)=>({2:[-1,0,0,1,w,0],3:[-1,0,0,-1,w,h],4:[1,0,0,-1,0,h],5:[0,1,1,0,0,0],6:[0,1,-1,0,h,0],7:[0,-1,-1,0,h,w],8:[0,-1,1,0,0,w]})[o]||[1,0,0,1,0,0];
export const rejectBytes=n=>n<=0?"empty":n>MAX_BYTES?"tooLargeBytes":null;
export const rejectSize=(w,h)=>w<=0||h<=0?"undecodable":w*h>MAX_PIXELS?"tooManyPixels":null;
export function documentSize(w,h){let tw=Math.min(Math.max(halfUp(w*DOWNSCALE),1),w),th=Math.min(Math.max(halfUp(h*DOWNSCALE),1),h);const long=Math.max(tw,th);
 if(long>MAX_EDGE){const fit=MAX_EDGE/long;tw=Math.min(Math.max(halfUp(tw*fit),1),w);th=Math.min(Math.max(halfUp(th*fit),1),h)}return[tw,th]}
export const failure=r=>{const reason=FAILURES[r];return{rejection:r,reason,outcome:"rejected:"+r,message:MESSAGES[reason]}};
export async function decide(data,decode,declared){const fail=r=>({ok:false,...failure(r)});
 if(declared&&!declared.startsWith("image/"))return fail("undecodable");let r=rejectBytes(data.length);if(r)return fail(r);
 const info=sniff(data),h=headerSize(data);if(h&&h[0]>0&&h[1]>0&&(r=rejectSize(h[0],h[1])))return fail(r);
 if(info.kind==="png"&&!pngComplete(data))return fail("undecodable");
 const size=decode?await decode(data):null;if(!size)return fail(info.kind==="heic"?"heicConversionFailed":"undecodable");
 const[width,height]=size;if(r=rejectSize(width,height))return fail(r);
 const label=info.kind!=="unknown"?info.label:(declared?declared.split("/").pop().toUpperCase():"IMAGE");
 return{ok:true,outcome:"supported",format:label,width,height,document:documentSize(width,height),message:MESSAGES.success,meta:label+" · "+width+" × "+height}}
export const rect=(left,top,right,bottom)=>({left,top,right,bottom});
export const INITIAL_RECT=rect(0.2,0.2,0.8,0.8);
export const rectFromDiagonal=(x0,y0,x1,y1)=>{const c=v=>clamp(v,0,1);return rect(c(Math.min(x0,x1)),c(Math.min(y0,y1)),c(Math.max(x0,x1)),c(Math.max(y0,y1)))};
export function rectSanitized(q){let l=clamp(q.left,0,1),t=clamp(q.top,0,1),r=clamp(q.right,0,1),b=clamp(q.bottom,0,1);
 if(r<l)[l,r]=[r,l];if(b<t)[t,b]=[b,t];if(r-l<MIN_SIZE){r=Math.min(1,l+MIN_SIZE);l=Math.max(0,r-MIN_SIZE)}if(b-t<MIN_SIZE){b=Math.min(1,t+MIN_SIZE);t=Math.max(0,b-MIN_SIZE)}return rect(l,t,r,b)}
export function rectTranslated(q,dx,dy){let l=q.left+dx,t=q.top+dy,r=q.right+dx,b=q.bottom+dy;if(l<0){r-=l;l=0}if(t<0){b-=t;t=0}if(r>1){l-=r-1;r=1}if(b>1){t-=b-1;b=1}return rectSanitized(rect(l,t,r,b))}
export function rectResized(q,handle,dx,dy){if(handle==="move")return rectTranslated(q,dx,dy);if(!HANDLES.includes(handle))throw new Error("unknown handle");
 let l=q.left,t=q.top,r=q.right,b=q.bottom;if(["topLeft","bottomLeft","left"].includes(handle))l+=dx;if(["topRight","bottomRight","right"].includes(handle))r+=dx;
 if(["topLeft","topRight","top"].includes(handle))t+=dy;if(["bottomLeft","bottomRight","bottom"].includes(handle))b+=dy;return rectSanitized(rect(l,t,r,b))}
export const rectText=q=>["left","top","right","bottom"].map(k=>k+": "+fixed(q[k],4)).join("\n");
export const rectCsv=q=>["left","top","right","bottom"].map(k=>fixed(q[k],4)).join(", ");
export const midpoint=(x0,y0,x1,y1)=>({x:(x0+x1)/2,y:(y0+y1)/2});
export const rectEdgeMidpoints=q=>[midpoint(q.left,q.top,q.right,q.top),midpoint(q.right,q.top,q.right,q.bottom),midpoint(q.left,q.bottom,q.right,q.bottom),midpoint(q.left,q.top,q.left,q.bottom)];
export const circle=q=>({cx:(q.left+q.right)/2,cy:(q.top+q.bottom)/2,radius:Math.min(q.right-q.left,q.bottom-q.top)/2});
export const triangle=q=>[{x:(q.left+q.right)/2,y:q.top},{x:q.right,y:q.bottom},{x:q.left,y:q.bottom}];
export const triangleMidpoints=q=>{const v=triangle(q);return[midpoint(v[0].x,v[0].y,v[1].x,v[1].y),midpoint(v[1].x,v[1].y,v[2].x,v[2].y),midpoint(v[2].x,v[2].y,v[0].x,v[0].y)]};
function inTriangle(px,py,ax,ay,bx,by,cx,cy){const v0x=cx-ax,v0y=cy-ay,v1x=bx-ax,v1y=by-ay,v2x=px-ax,v2y=py-ay,d00=v0x*v0x+v0y*v0y,d01=v0x*v1x+v0y*v1y,d02=v0x*v2x+v0y*v2y,d11=v1x*v1x+v1y*v1y,d12=v1x*v2x+v1y*v2y;
 const den=d00*d11-d01*d01;if(Math.abs(den)<1e-12)return false;const u=(d11*d02-d01*d12)/den,v=(d00*d12-d01*d02)/den;return u>=0&&v>=0&&u+v<=1}
function segDistance(px,py,ax,ay,bx,by){const abx=bx-ax,aby=by-ay,l2=abx*abx+aby*aby;if(l2<1e-12)return dist(px-ax,py-ay);const t=clamp(((px-ax)*abx+(py-ay)*aby)/l2,0,1);return dist(px-(ax+t*abx),py-(ay+t*aby))}
export function shapeContains(q,shape,x,y,slop=0){
 if(shape==="rectangle")return q.left-slop<=x&&x<=q.right+slop&&q.top-slop<=y&&y<=q.bottom+slop;
 if(shape==="circle"){const c=circle(q),r=c.radius+slop;return(x-c.cx)*(x-c.cx)+(y-c.cy)*(y-c.cy)<=r*r}
 if(shape==="triangle"){const v=triangle(q);if(inTriangle(x,y,v[0].x,v[0].y,v[1].x,v[1].y,v[2].x,v[2].y))return true;if(slop<=0)return false;
  return[0,1,2].some(i=>segDistance(x,y,v[i].x,v[i].y,v[(i+1)%3].x,v[(i+1)%3].y)<=slop)}
 throw new Error("unknown shape")}
export function segmentIntersection(ax,ay,bx,by,cx,cy,dx,dy){const rx=bx-ax,ry=by-ay,sx=dx-cx,sy=dy-cy,den=rx*sy-ry*sx;if(Math.abs(den)<1e-12)return null;
 const t=((cx-ax)*sy-(cy-ay)*sx)/den,u=((cx-ax)*ry-(cy-ay)*rx)/den;if(t<0||t>1||u<0||u>1)return null;return{x:ax+t*rx,y:ay+t*ry}}
export function describe(q,shape){const p=o=>fixed(o.x,4)+", "+fixed(o.y,4);
 if(shape==="rectangle"){const m=rectEdgeMidpoints(q);return["shape: rectangle",rectText(q),...["top","right","bottom","left"].map((n,i)=>"mid."+n+": "+p(m[i]))].join("\n")}
 if(shape==="circle"){const c=circle(q);return"shape: circle\ncx: "+fixed(c.cx,4)+"\ncy: "+fixed(c.cy,4)+"\nradius: "+fixed(c.radius,4)}
 if(shape==="triangle"){const v=triangle(q),m=triangleMidpoints(q);return["shape: triangle","apex: "+p(v[0]),"right: "+p(v[1]),"left: "+p(v[2]),"mid.apexRight: "+p(m[0]),"mid.base: "+p(m[1]),"mid.apexLeft: "+p(m[2])].join("\n")}
 throw new Error("unknown shape")}
export function hitHandle(q,width,height,x,y){const l=q.left*width,t=q.top*height,r=q.right*width,b=q.bottom*height,s=HANDLE_SLOP;
 for(const[name,cx,cy]of[["topLeft",l,t],["topRight",r,t],["bottomLeft",l,b],["bottomRight",r,b]])if(dist(cx-x,cy-y)<=s)return name;
 const side=Math.max(0,(b-t)-s*2),wide=Math.max(0,(r-l)-s*2);
 for(const[name,left,top,w,h]of[["left",l-s/2,t+s,s,side],["right",r-s/2,t+s,s,side],["top",l+s,t-s/2,wide,s],["bottom",l+s,b-s/2,wide,s]])if(left<=x&&x<left+w&&top<=y&&y<top+h)return name;
 return l+4<=x&&x<r-4&&t+4<=y&&y<b-4?"move":null}
export function hitFrame(frames,width,height,x,y){if(width<=0||height<=0)return null;const slop=4/Math.min(width,height);
 for(let i=frames.length-1;i>=0;i--)if(shapeContains(frames[i].rect,frames[i].shape,x/width,y/height,slop))return frames[i];return null}
export function hitStamp(stamps,width,height,x,y){for(let i=stamps.length-1;i>=0;i--){const s=stamps[i],radius=Math.max(STAMP_MIN_HIT,Math.min(width,height)*0.05*s.scale);
  if(dist(s.x*width-x,s.y*height-y)<=radius)return s}return null}
export const exportSize=(w,h,ratio=2)=>[Math.min(Math.max(halfUp(w*ratio),1),MAX_EDGE),Math.min(Math.max(halfUp(h*ratio),1),MAX_EDGE)];
export function containRect(iw,ih,w,h){let dw,dh;if(iw/ih>w/h){dw=w;dh=w/(iw/ih)}else{dh=h;dw=h*(iw/ih)}return[(w-dw)/2,(h-dh)/2,dw,dh]}
export const stampPx=(w,h,scale)=>Math.min(w,h)*0.1*clamp(scale,0.4,3);
export const same=(a,b)=>{if(a===b)return true;if(typeof a!=="object"||typeof b!=="object"||a===null||b===null||Array.isArray(a)!==Array.isArray(b))return false;
 const ka=Object.keys(a);if(ka.length!==Object.keys(b).length)return false;return ka.every(k=>Object.prototype.hasOwnProperty.call(b,k)&&same(a[k],b[k]))};
export class PhotoHistory{constructor(limit=HISTORY_LIMIT){this.limit=limit;this._undo=[];this._redo=[];this._pending=null}
 get depth(){return this._undo.length}get canUndo(){return this._undo.length>0}get canRedo(){return this._redo.length>0}states(){return[...this._undo,...this._redo]}
 beginGesture(current){if(this._pending===null)this._pending=current}
 endGesture(current){const p=this._pending;this._pending=null;if(p===null||same(p,current))return false;this._push(p);return true}
 recordChange(before,after){if(same(before,after))return false;this._push(before);return true}
 undo(current){this._pending=null;if(!this._undo.length)return null;this._redo.push(current);return this._undo.pop()}
 redo(current){this._pending=null;if(!this._redo.length)return null;this._undo.push(current);if(this._undo.length>this.limit)this._undo.shift();return this._redo.pop()}
 clearPending(){this._pending=null}clear(){this._pending=null;this._undo=[];this._redo=[]}
 _push(s){this._undo.push(s);if(this._undo.length>this.limit)this._undo.shift();this._redo=[]}}
export class PhotoStudio{constructor(width=760,height=280){this.width=width;this.height=height;
  this.state={image:null,frames:[],selected_frame:null,draft_color:COLORS[0][1],draft_shape:null,stamps:[],selected_stamp:null,stamp_scale:1};
  this.history=new PhotoHistory();this.pendingEmoji=null;this._serial=0;this._active=null;this._tapDown=null;this._resetGesture()}
 _resetGesture(){this._createOrigin=this._creating=this._live=this._editing=this._handle=this._draggingStamp=null;this._gestureStamps=this._lastSpray=this._last=null;this._spraying=this._started=this._placed=this._dragging=false}
 _set(changes){this.state={...this.state,...changes}}
 _newId(kind){this._serial+=1;return kind+"-"+this._serial}
 _frame(id){return id?(this.state.frames.find(f=>f.id===id)||null):null}
 _framesChanged(frames){const sel=this.state.selected_frame;this._set({frames,...(sel!==null&&!frames.some(f=>f.id===sel)?{selected_frame:null}:{})})}
 _selectFrame(id){this._set({selected_frame:id})}
 _stampsChanged(stamps){const known=new Set(this.state.stamps.map(s=>s.id)),added=stamps.filter(s=>!known.has(s.id)),changes={stamps};
  if(added.length){const last=added[added.length-1];changes.selected_stamp=last.id;changes.stamp_scale=last.scale}
  else if(this.state.selected_stamp!==null){const m=stamps.filter(s=>s.id===this.state.selected_stamp);if(m.length)changes.stamp_scale=m[0].scale}this._set(changes)}
 _selectStamp(id){const changes={selected_stamp:id},m=id!==null?this.state.stamps.filter(s=>s.id===id):[];if(m.length)changes.stamp_scale=m[0].scale;this._set(changes)}
 _editStart(){if(!this._started){this._started=true;this.history.beginGesture(this.state)}}
 pointerDown(pointer,x,y){this._tapDown=[x,y];this._placed=false;this._gestureStamps=[...this.state.stamps];this._spraying=false;this._lastSpray=null;this._active=pointer;this._dragging=false}
 pointerMove(pointer,x,y){if(this._active===null||this._active!==pointer)return;
  if(!this._dragging){const d=this._tapDown;if(d===null||dist(x-d[0],y-d[1])<4)return;this._dragging=true;this._panStart(d[0],d[1])}this._panUpdate(x,y)}
 pointerUp(pointer){if(this._active!==null&&pointer!==this._active)return;const local=this._tapDown,was=this._dragging;this._active=null;this._dragging=false;
  if(was)this._finish();else if(local!==null&&!this._placed){this._tap(local[0],local[1]);if(this._started||this._draggingStamp!==null)this._finish()}this._tapDown=null}
 pointerCancel(pointer){if(this._active!==null&&pointer!==this._active)return;this._tapDown=null;this._active=null;
  if(this._dragging||this._started||this._draggingStamp!==null){this._dragging=false;this._finish()}else{this._gestureStamps=null;this._spraying=false;this._lastSpray=null;this._placed=false;this._dragging=false}}
 _placePending(x,y,repeated=false){if(!this.pendingEmoji||(!repeated&&this._placed))return;this._editStart();if(!repeated)this._placed=true;const id=this._newId("stamp");
  const stamps=[...(this._gestureStamps!==null?this._gestureStamps:this.state.stamps),{id,emoji:this.pendingEmoji,x:clamp(x/this.width,0,1),y:clamp(y/this.height,0,1),scale:1}];
  this._gestureStamps=stamps;this._stampsChanged(stamps);this._selectStamp(id)}
 _tap(x,y){const stamp=hitStamp(this.state.stamps,this.width,this.height,x,y);if(stamp)this._selectStamp(stamp.id);
  else if(this.pendingEmoji&&!this._placed)this._placePending(x,y);else{const f=hitFrame(this.state.frames,this.width,this.height,x,y);this._selectFrame(f?f.id:null)}}
 _panStart(x,y){const w=this.width,h=this.height,stamp=hitStamp(this.state.stamps,w,h,x,y);
  if(stamp){this._editStart();this._draggingStamp=stamp.id;this._handle=this._createOrigin=this._creating=this._live=null;this._selectStamp(stamp.id);this._last=[x,y];return}
  if(this.pendingEmoji){if(!this._placed)this._placePending(x,y);this._spraying=true;this._lastSpray=[x,y];this._draggingStamp=this._handle=this._createOrigin=this._creating=this._live=null;this._last=[x,y];return}
  const frame=hitFrame(this.state.frames,w,h,x,y);
  if(frame){this._editStart();this._selectFrame(frame.id);this._createOrigin=this._creating=this._live=null;this._editing=frame.id;this._handle=hitHandle(frame.rect,w,h,x,y)||"move";this._last=[x,y];return}
  const selected=this._frame(this.state.selected_frame);
  if(selected){const handle=hitHandle(selected.rect,w,h,x,y);if(handle){this._editStart();this._createOrigin=this._creating=this._live=null;this._editing=selected.id;this._handle=handle;this._last=[x,y];return}}
  if(this.state.draft_shape){this._editStart();const nx=clamp(x/w,0,1),ny=clamp(y/h,0,1);this._createOrigin=[nx,ny];this._handle=null;this._creating=this._newId("frame");
   this._live={id:this._creating,rect:rectFromDiagonal(nx,ny,nx,ny),shape:this.state.draft_shape,color:this.state.draft_color};this._framesChanged([...this.state.frames,this._live]);this._selectFrame(this._creating);this._last=[x,y];return}
  this._selectFrame(null);this._handle=this._createOrigin=this._creating=this._live=null;this._last=[x,y]}
 _panUpdate(x,y){const w=this.width,h=this.height;if(w<=0||h<=0)return;
  if(this._spraying&&this.pendingEmoji){const last=this._lastSpray;if(last===null||dist(x-last[0],y-last[1])>=28){this._placePending(x,y,true);this._lastSpray=[x,y]}return}
  if(this._draggingStamp!==null){const nx=clamp(x/w,0,1),ny=clamp(y/h,0,1);this._stampsChanged(this.state.stamps.map(s=>s.id===this._draggingStamp?{...s,x:nx,y:ny}:s));return}
  if(this._createOrigin!==null&&this._creating!==null){const nx=clamp(x/w,0,1),ny=clamp(y/h,0,1),live=this._live||{id:this._creating,rect:INITIAL_RECT,shape:this.state.draft_shape||"rectangle",color:this.state.draft_color};
   this._live={...live,rect:rectFromDiagonal(this._createOrigin[0],this._createOrigin[1],nx,ny)};this._framesChanged([...this.state.frames.filter(f=>f.id!==this._creating),this._live]);return}
  const editing=this._frame(this._editing)||this._frame(this.state.selected_frame);if(this._handle===null||this._last===null||editing===null)return;
  const dx=(x-this._last[0])/w,dy=(y-this._last[1])/h;this._last=[x,y];this._replaceFrame({...editing,rect:rectResized(editing.rect,this._handle,dx,dy)})}
 _replaceFrame(u){this._framesChanged(this.state.frames.map(f=>f.id===u.id?u:f))}
 _finish(){if(this._creating!==null&&this._live!==null)this._framesChanged([...this.state.frames.filter(f=>f.id!==this._creating),{...this._live,rect:rectSanitized(this._live.rect)}]);
  const had=this._started;this._resetGesture();if(had)this.history.endGesture(this.state)}
 _change(changes){const before=this.state;this._set(changes);this.history.recordChange(before,this.state)}
 setImage(image){this._change({image})}
 setShape(shape){if(shape!==null&&!SHAPES.includes(shape))throw new Error("unknown shape");if(this.state.draft_shape===shape&&(shape===null||this.pendingEmoji===null))return;if(shape!==null)this.pendingEmoji=null;this._change({draft_shape:shape})}
 setColor(color){const sel=this._frame(this.state.selected_frame);if(this.state.draft_color===color&&(sel===null||sel.color===color))return;
  this._change({draft_color:color,frames:this.state.frames.map(f=>f.id===this.state.selected_frame?{...f,color}:f)})}
 armStamp(text){text=(text||"").trim()||null;if(text===null)return;this.pendingEmoji=this.pendingEmoji===text?null:text;if(this.pendingEmoji!==null&&this.state.draft_shape!==null)this._change({draft_shape:null})}
 setStampScale(scale){scale=clamp(scale,0.4,3);const sel=this.state.selected_stamp;this._set({stamp_scale:scale,...(sel!==null?{stamps:this.state.stamps.map(s=>s.id===sel?{...s,scale}:s)}:{})})}
 resetSelectedFrame(){const sel=this.state.selected_frame;if(this._frame(sel))this._change({frames:this.state.frames.map(f=>f.id===sel?{...f,rect:{...INITIAL_RECT}}:f)})}
 deleteSelectedFrame(){const sel=this.state.selected_frame;if(sel!==null)this._change({frames:this.state.frames.filter(f=>f.id!==sel),selected_frame:null})}
 nudge(dx,dy){const frame=this._frame(this.state.selected_frame);if(frame)this._change({frames:this.state.frames.map(f=>f.id===frame.id?{...frame,rect:rectTranslated(frame.rect,dx,dy)}:f)})}
 undo(){const s=this.history.undo(this.state);if(s===null)return false;this.state=s;if(s.draft_shape!==null)this.pendingEmoji=null;return true}
 redo(){const s=this.history.redo(this.state);if(s===null)return false;this.state=s;if(s.draft_shape!==null)this.pendingEmoji=null;return true}}
const MIME={png:"image/png",jpeg:"image/jpeg",webp:"image/webp",gif:"image/gif",avif:"image/avif",heic:"image/heic"};
const fromB64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
/* Decode in the engine. The bytes go in with EXIF orientation set to 1 and the type the bytes show (not the one the file claims), so every engine returns the stored pixels and the page turns them. */
export function loadImage(bytes,{raw=false}={}){const info=sniff(bytes),blob=new Blob([raw?bytes:neutralizeOrientation(bytes)],{type:MIME[info.kind]||"application/octet-stream"}),url=URL.createObjectURL(blob),image=new Image();
 const release=()=>{image.onload=image.onerror=null;URL.revokeObjectURL(url)};
 return new Promise((resolve,reject)=>{image.onerror=()=>{release();reject(new Error("decode failed"))};
  image.onload=async()=>{try{if(image.decode)await image.decode()}catch(e){release();reject(new Error("decode failed"));return}
   if(!(image.naturalWidth>0&&image.naturalHeight>0)){release();reject(new Error("decode failed"));return}resolve({image,width:image.naturalWidth,height:image.naturalHeight,release})};
  image.src=url})}
export function evidence({userAgent="",outcomes={},features={},verifiedAt="",exifAppliedByEngine=null}={}){
 const out={};for(const id of Object.keys(outcomes))out[id]={loader_browser_canvas_adapter:outcomes[id]};
 return{schemaVersion:2,environmentId:"web_ui_photo_studio",runtime:"browser",userAgent,verifiedAt,entryPoint:"loader_browser_canvas_adapter",exifOrientationAppliedByEngine:exifAppliedByEngine,
  notes:"Measured by the web-ui Photo Studio page (Check this browser). Only loader_browser_canvas_adapter is measured; every other entry point stays not_verified. A browser emulation is not a device.",outcomes:out,features}}
const FAMILY='"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
function frameShape(g,shape,x0,y0,x1,y1){g.beginPath();
 if(shape==="rectangle")g.rect(x0,y0,x1-x0,y1-y0);else if(shape==="circle")g.arc((x0+x1)/2,(y0+y1)/2,Math.min(x1-x0,y1-y0)/2,0,Math.PI*2);
 else{g.moveTo((x0+x1)/2,y0);g.lineTo(x1,y1);g.lineTo(x0,y1);g.closePath()}}
/* One drawing for the screen and for the exported PNG: the photo fitted whole, then frames, then stamps. The screen adds the selection. */
export function paint(g,W,H,state,doc,{selection=false}={}){g.fillStyle="#2a2a2a";g.fillRect(0,0,W,H);
 if(doc){const[x,y,w,h]=containRect(doc.width,doc.height,W,H);g.imageSmoothingEnabled=true;g.imageSmoothingQuality="high";g.drawImage(doc.canvas,x,y,w,h)}
 else if(selection){g.fillStyle="#3a3a3a";for(let y=0;y<H;y+=16)for(let x=((y/16)%2)*16;x<W;x+=32)g.fillRect(x,y,16,16)}
 for(const f of state.frames){const r=f.rect,chosen=selection&&f.id===state.selected_frame;g.strokeStyle=f.color;g.lineWidth=selection?(chosen?2.5:2):3;g.lineJoin="round";frameShape(g,f.shape,r.left*W,r.top*H,r.right*W,r.bottom*H);g.stroke()}
 for(const s of state.stamps){g.font=stampPx(W,H,s.scale)+"px "+FAMILY;g.textAlign="center";g.textBaseline="middle";g.fillStyle="#000";g.fillText(s.emoji,s.x*W,s.y*H)}
 if(selection){const f=state.frames.find(q=>q.id===state.selected_frame);if(f){const r=f.rect,l=r.left*W,t=r.top*H,rr=r.right*W,b=r.bottom*H;g.save();g.setLineDash([5,4]);g.lineWidth=1;g.strokeStyle="#ffffff";g.strokeRect(l,t,rr-l,b-t);g.restore();
   g.fillStyle="#ffffff";g.strokeStyle="#000000";g.lineWidth=1;for(const[x,y]of[[l,t],[rr,t],[l,b],[rr,b],[(l+rr)/2,t],[(l+rr)/2,b],[l,(t+b)/2],[rr,(t+b)/2]]){g.fillRect(x-5,y-5,10,10);g.strokeRect(x-5,y-5,10,10)}}
  const st=state.stamps.find(q=>q.id===state.selected_stamp);if(st){g.save();g.setLineDash([4,3]);g.strokeStyle="#ffffff";g.lineWidth=1.5;g.beginPath();g.arc(st.x*W,st.y*H,Math.max(STAMP_MIN_HIT,Math.min(W,H)*0.05*st.scale),0,Math.PI*2);g.stroke();g.restore()}}}
export function bindPhoto(root=document){return[...root.querySelectorAll("[data-ui-photo]")].map(box=>{
 const $=s=>box.querySelector(s),$$=s=>[...box.querySelectorAll(s)],stage=$("[data-stage]"),g=stage.getContext("2d"),statusEl=$("[data-status]"),metaEl=$("[data-meta]"),liveEl=$("[data-live]"),
  file=$("[data-file]"),retry=$("[data-retry]"),undoB=$("[data-undo]"),redoB=$("[data-redo]"),delB=$("[data-delete]"),resetB=$("[data-reset]"),clearB=$("[data-clear]"),scaleIn=$("[data-scale]"),scaleOut=$("[data-scale-out]"),
  geo=$("[data-geometry]"),checkOut=$("[data-check-out]"),shareB=$("[data-share]"),custom=$("[data-custom]");
 const studio=new PhotoStudio(),docs=new Map();let serial=0,generation=0,busy=false,lastSource=null;
 const say=t=>{liveEl.textContent="";liveEl.textContent=t};
 const setStatus=(phase,text,meta="")=>{busy=phase==="loading";statusEl.textContent=text;metaEl.textContent=meta;box.dataset.photoPhase=phase};
 const doc=()=>docs.get(studio.state.image)||null;
 function fit(){const wrap=stage.parentElement,W=Math.max(120,Math.floor(wrap.clientWidth||760)),d=doc(),maxH=Math.max(160,Math.min(640,Math.floor((window.innerHeight||800)*0.7)));
  const H=d?Math.floor(clamp(W*d.height/d.width,120,maxH)):Math.floor(W*280/760);let ratio=Math.min(window.devicePixelRatio||1,3);while(W*H*ratio*ratio>16000000&&ratio>1)ratio-=0.5;
  stage.style.width=W+"px";stage.style.height=H+"px";stage.width=Math.max(1,Math.round(W*ratio));stage.height=Math.max(1,Math.round(H*ratio));studio.width=W;studio.height=H;g.setTransform(stage.width/W,0,0,stage.height/H,0,0);return[W,H]}
 function render(){paint(g,studio.width,studio.height,studio.state,doc(),{selection:true})}
 function prune(){const keep=new Set([studio.state.image,...studio.history.states().map(s=>s.image)]);for(const id of[...docs.keys()])if(!keep.has(id))docs.delete(id)}
 function sync(){const s=studio.state,sel=s.frames.find(f=>f.id===s.selected_frame)||null;
  undoB.disabled=!studio.history.canUndo;redoB.disabled=!studio.history.canRedo;delB.disabled=resetB.disabled=!sel;clearB.disabled=!s.image;
  for(const r of $$('input[name="photo-shape"]'))r.checked=r.value===(s.draft_shape||"none");for(const r of $$('input[name="photo-color"]'))r.checked=r.value===s.draft_color;
  for(const b of $$("[data-stamp]"))b.setAttribute("aria-pressed",String(studio.pendingEmoji===b.dataset.stamp));$("[data-arm]").setAttribute("aria-pressed",String(studio.pendingEmoji!==null&&studio.pendingEmoji===custom.value.trim()));
  scaleIn.value=String(s.stamp_scale);scaleOut.textContent=Number(s.stamp_scale).toFixed(1);
  geo.textContent=sel?describe(sel.rect,sel.shape):"No frame selected.";box.dataset.rect=sel?rectCsv(sel.rect):"";
  stage.setAttribute("aria-label","Photo canvas: "+s.frames.length+" frame"+(s.frames.length===1?"":"s")+", "+s.stamps.length+" stamp"+(s.stamps.length===1?"":"s")+(sel?", "+sel.shape+" selected":"")+(studio.pendingEmoji?", stamp "+studio.pendingEmoji+" armed":""));
  box.dataset.frames=String(s.frames.length);box.dataset.stamps=String(s.stamps.length);box.dataset.depth=String(studio.history.depth);box.dataset.armed=studio.pendingEmoji||""}
 const after=()=>{render();sync()};
 function invalidate(mark=true){const was=busy;generation+=1;if(mark&&was)setStatus("superseded",MESSAGES.superseded)}
 async function importBytes(bytes,declared,source){const mine=++generation;lastSource=source;box.dataset.source=source;retry.hidden=true;setStatus("loading",MESSAGES.loading);box.dataset.photoOutcome="";
  let loaded=null;const result=await decide(bytes,async data=>{try{loaded=await loadImage(data);return[loaded.width,loaded.height]}catch(e){return null}},declared);
  if(mine!==generation){if(loaded)loaded.release();return}
  if(!result.ok){if(loaded)loaded.release();setStatus("failure",result.message);box.dataset.photoOutcome=result.outcome;retry.hidden=!(source==="pick"||source==="paste");after();return}
  const info=sniff(bytes),o=info.orientation||1,[ow,oh]=orientedSize(result.width,result.height,o),[tw,th]=documentSize(ow,oh);
  const canvas=document.createElement("canvas");canvas.width=tw;canvas.height=th;const c=canvas.getContext("2d"),m=orientationMatrix(o,result.width,result.height),sx=tw/ow,sy=th/oh;
  c.imageSmoothingQuality="high";c.setTransform(m[0]*sx,m[1]*sy,m[2]*sx,m[3]*sy,m[4]*sx,m[5]*sy);c.drawImage(loaded.image,0,0);loaded.release();
  const id=++serial;docs.set(id,{canvas,width:tw,height:th});studio.setImage(id);studio.history.clearPending();prune();fit();setStatus("success",MESSAGES.success,result.meta);
  box.dataset.photoOutcome=result.outcome;box.dataset.photoSize=result.width+"x"+result.height;box.dataset.documentSize=tw+"x"+th;box.dataset.orientation=String(o);after()}
 async function importFile(f,source){if(!f)return;if(f.size>MAX_BYTES){generation+=1;const r=failure("tooLargeBytes");setStatus("failure",r.message);box.dataset.photoOutcome=r.outcome;retry.hidden=!(source==="pick"||source==="paste");return}
  setStatus("loading",MESSAGES.loading);let bytes;try{bytes=new Uint8Array(await f.arrayBuffer())}catch(e){const r=failure("undecodable");setStatus("failure",MESSAGES.decodeFailed);box.dataset.photoOutcome=r.outcome;return}
  await importBytes(bytes,f.type||"",source)}
 file.addEventListener("change",()=>{const f=file.files&&file.files[0];file.value="";importFile(f,"pick")});
 file.addEventListener("cancel",()=>{if(!busy)setStatus("cancelled",MESSAGES.cancelled)});
 retry.addEventListener("click",()=>{retry.hidden=true;if(lastSource==="paste")pasteButton();else file.click()});
 const imageOf=items=>{for(const it of items||[])if(it.kind==="file"&&/^image\//.test(it.type))return it.getAsFile();return null};
 document.addEventListener("paste",e=>{const t=e.target;if(t&&(t.tagName==="INPUT"||t.tagName==="TEXTAREA"||t.isContentEditable))return;const cd=e.clipboardData;if(!cd)return;
  const f=(cd.files&&[...cd.files].find(x=>/^image\//.test(x.type)))||imageOf(cd.items);if(!f){setStatus("failure",MESSAGES.noClipboardImage);box.dataset.photoOutcome="";return}e.preventDefault();importFile(f,"paste")});
 async function pasteButton(){if(!(navigator.clipboard&&navigator.clipboard.read)){setStatus("failure",MESSAGES.clipboardUnavailable);retry.hidden=false;return}
  try{const items=await navigator.clipboard.read();for(const item of items){const type=item.types.find(t=>/^image\//.test(t));if(type){const blob=await item.getType(type);await importFile(new File([blob],"clipboard",{type}),"paste");return}}
   setStatus("failure",MESSAGES.noClipboardImage)}catch(e){setStatus("failure",MESSAGES.clipboardUnavailable);retry.hidden=false}}
 $("[data-paste]").addEventListener("click",pasteButton);
 box.addEventListener("dragover",e=>{if(e.dataTransfer&&[...e.dataTransfer.types].includes("Files"))e.preventDefault()});
 box.addEventListener("drop",e=>{const f=e.dataTransfer&&[...e.dataTransfer.files].find(x=>/^image\//.test(x.type)||x.type==="");if(f){e.preventDefault();importFile(f,"insert")}});
 const pos=e=>{const r=stage.getBoundingClientRect();return[(e.clientX-r.left)*(studio.width/r.width),(e.clientY-r.top)*(studio.height/r.height)]};
 stage.addEventListener("pointerdown",e=>{if(e.pointerType==="mouse"&&e.button!==0)return;try{stage.setPointerCapture(e.pointerId)}catch(x){}stage.focus({preventScroll:true});const[x,y]=pos(e);studio.pointerDown(e.pointerId,x,y);after();e.preventDefault()});
 stage.addEventListener("pointermove",e=>{const[x,y]=pos(e);studio.pointerMove(e.pointerId,x,y);after()});
 stage.addEventListener("pointerup",e=>{studio.pointerUp(e.pointerId);after()});
 stage.addEventListener("pointercancel",e=>{studio.pointerCancel(e.pointerId);after()});
 stage.addEventListener("contextmenu",e=>e.preventDefault());
 stage.addEventListener("keydown",e=>{const mod=e.ctrlKey||e.metaKey,k=e.key;
  if(mod&&(k==="z"||k==="Z")){e.preventDefault();if(e.shiftKey)redo();else undo();return}if(mod&&(k==="y"||k==="Y")){e.preventDefault();redo();return}
  if(k==="Delete"||k==="Backspace"){if(studio.state.selected_frame!==null){e.preventDefault();studio.deleteSelectedFrame();after()}return}
  const step=e.shiftKey?0.05:0.01,d={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]}[k];if(d&&studio.state.selected_frame!==null){e.preventDefault();studio.nudge(d[0],d[1]);after()}});
 function undo(){invalidate();if(studio.undo()){prune();fit();say("Undid last change.");after()}}
 function redo(){invalidate();if(studio.redo()){prune();fit();say("Redid last change.");after()}}
 undoB.addEventListener("click",undo);redoB.addEventListener("click",redo);
 delB.addEventListener("click",()=>{studio.deleteSelectedFrame();after()});resetB.addEventListener("click",()=>{studio.resetSelectedFrame();after()});
 clearB.addEventListener("click",()=>{const was=busy;invalidate();studio.setImage(null);prune();fit();if(!was)setStatus("idle",MESSAGES.idle);say("Photo cleared; frames kept.");box.dataset.photoOutcome="";after()});
 $("[data-next]").addEventListener("click",()=>{const fs=studio.state.frames;if(!fs.length)return;const i=fs.findIndex(f=>f.id===studio.state.selected_frame);studio._selectFrame(fs[(i+1)%fs.length].id);after()});
 for(const r of $$('input[name="photo-shape"]'))r.addEventListener("change",()=>{if(r.checked){studio.setShape(r.value==="none"?null:r.value);after()}});
 for(const r of $$('input[name="photo-color"]'))r.addEventListener("change",()=>{if(r.checked){studio.setColor(r.value);after()}});
 for(const b of $$("[data-stamp]"))b.addEventListener("click",()=>{studio.armStamp(b.dataset.stamp);after()});
 $("[data-arm]").addEventListener("click",()=>{studio.armStamp(custom.value);after()});
 scaleIn.addEventListener("input",()=>{studio.setStampScale(Number(scaleIn.value));after()});
 const copyText=async t=>{try{await navigator.clipboard.writeText(t);return true}catch(e){const ta=document.createElement("textarea");ta.value=t;ta.style.position="fixed";ta.style.opacity="0";document.body.append(ta);ta.select();let ok=false;try{ok=document.execCommand("copy")}catch(x){}ta.remove();return ok}};
 const copyRect=async f=>{const sel=studio.state.frames.find(q=>q.id===studio.state.selected_frame);if(!sel){say("No frame selected.");return}say((await copyText(f(sel.rect)))?"Copied.":"Could not copy.")};
 $("[data-copy-rect]").addEventListener("click",()=>copyRect(rectText));$("[data-copy-csv]").addEventListener("click",()=>copyRect(rectCsv));
 async function exportBlob(){const[ew,eh]=exportSize(studio.width,studio.height,2),c=document.createElement("canvas");c.width=ew;c.height=eh;const x=c.getContext("2d");x.scale(ew/studio.width,eh/studio.height);
  paint(x,studio.width,studio.height,studio.state,doc(),{selection:false});const blob=await new Promise(r=>c.toBlob(r,"image/png"));box.dataset.exportSize=ew+"x"+eh;return blob}
 $("[data-export]").addEventListener("click",async()=>{try{const blob=await exportBlob();if(!blob){say("Could not save the photo.");return}box.dataset.exportBytes=String(blob.size);
   const url=URL.createObjectURL(blob),a=document.createElement("a");if(!("download" in a)){window.open(url,"_blank");say("Opened the PNG in a new tab: press and hold it to save.");return}
   a.href=url;a.download=EXPORT_NAME;a.hidden=true;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);say("Saved as PNG.")}catch(e){say("Could not save the photo.")}});
 try{const probe=new File([new Blob(["x"])],"x.png",{type:"image/png"});if(navigator.canShare&&navigator.canShare({files:[probe]})){shareB.hidden=false;
   shareB.addEventListener("click",async()=>{try{const blob=await exportBlob();await navigator.share({files:[new File([blob],EXPORT_NAME,{type:"image/png"})]})}catch(e){}})}}catch(e){}
 const PROBES=JSON.parse(box.dataset.probes||"[]");
 async function check(){checkOut.textContent="Checking…";const outcomes={};
  for(const p of PROBES){try{const r=await loadImage(fromB64(p.data));r.release();outcomes[p.id]="supported"}catch(e){outcomes[p.id]="unsupported_by_runtime"}}
  let applied=null;const exif=PROBES.find(p=>p.id==="jpeg_exif_orientation_6");if(exif){try{const r=await loadImage(fromB64(exif.data),{raw:true});applied=r.width<r.height;r.release()}catch(e){}}
  const features={};const tryDo=(k,f)=>{try{features[k]=f()}catch(e){features[k]=false}};
  tryDo("pointerEvents",()=>"PointerEvent" in window);tryDo("touchActionNone",()=>CSS.supports("touch-action","none"));tryDo("createImageBitmap",()=>typeof createImageBitmap==="function");
  tryDo("canvasToBlob",()=>typeof HTMLCanvasElement.prototype.toBlob==="function");tryDo("clipboardRead",()=>!!(navigator.clipboard&&navigator.clipboard.read));tryDo("clipboardWrite",()=>!!(navigator.clipboard&&navigator.clipboard.writeText));
  tryDo("webShareFiles",()=>!!navigator.canShare);tryDo("anchorDownload",()=>"download" in HTMLAnchorElement.prototype);tryDo("devicePixelRatio",()=>window.devicePixelRatio||1);
  tryDo("canvas4096",()=>{const c=document.createElement("canvas");c.width=c.height=4096;const x=c.getContext("2d");x.fillStyle="#f00";x.fillRect(4095,4095,1,1);return x.getImageData(4095,4095,1,1).data[3]===255});
  const ev=evidence({userAgent:navigator.userAgent,outcomes,features,verifiedAt:new Date().toISOString().slice(0,10),exifAppliedByEngine:applied});
  checkOut.textContent=JSON.stringify(ev,null,2);box.dataset.check=JSON.stringify(ev);return ev}
 $("[data-check]").addEventListener("click",check);
 if(typeof ResizeObserver==="function")new ResizeObserver(()=>{fit();render()}).observe(stage.parentElement);else window.addEventListener("resize",()=>{fit();render()});
 box.photo={studio,docs,importBytes,check,fit,render,sync};fit();setStatus("idle",MESSAGES.idle);after();return box})}
globalThis.webUiPhoto={fixed,sniff,pngComplete,neutralizeOrientation,headerSize,orientationOp,orientedSize,orientationMatrix,rejectBytes,rejectSize,documentSize,failure,decide,rect,rectFromDiagonal,rectSanitized,rectTranslated,rectResized,rectText,rectCsv,
 rectEdgeMidpoints,circle,triangle,triangleMidpoints,shapeContains,segmentIntersection,describe,hitHandle,hitFrame,hitStamp,exportSize,containRect,stampPx,same,PhotoHistory,PhotoStudio,loadImage,evidence,paint,bindPhoto,MESSAGES,OUTCOMES,STAMPS,COLORS};
if(typeof document!=="undefined")bindPhoto();
"""


def _example_cards() -> str:
    return ('<section class="ui-grid"><article class="ui-card"><h2>Components</h2><p>Tokens, panels, cards, tags, controls and output surfaces.</p>'
            '<span class="ui-tag">modern</span> <span class="ui-tag">static</span></article>'
            '<article class="ui-card"><h2>Stub examples</h2><p><a href="./mcp-stub.html">MCP Stub</a> · <a href="./api-stub.html">API Stub</a></p></article>'
            '<article class="ui-card"><h2>Themes</h2><p><a href="./github-like.html">GitHub-like theme</a></p></article>'
            '<article class="ui-card"><h2>App shell</h2><p><a href="./showcase.html">Showcase</a>: header, rail or bottom bar, sections.</p></article>'
            '<article class="ui-card"><h2>Clipboard shelf</h2><p><a href="./clipboard-shelf.html">Shelf and prompt workbench</a>: paste, filter, copy a bundle.</p></article>'
            '<article class="ui-card"><h2>Door-to-Door</h2><p><a href="./door.html">Pull-down and emoji transitions</a>: A → B, A ↔ B.</p></article>'
            '<article class="ui-card"><h2>Composition studio</h2><p><a href="./composition-studio.html">Metronome, chords, notes, song seed</a>.</p></article>'
            '<article class="ui-card"><h2>Coordinates</h2><p><a href="./coordinates.html">Check a point, read a Maps URL, frame an area</a>.</p></article>'
            '<article class="ui-card"><h2>Photo studio</h2><p><a href="./photo-studio.html">Frames and stamps on a photo, EXIF-safe import, PNG export</a>.</p></article></section>')


def example_pages() -> dict[str, str]:
    """The pages that used to be examples/*.html and contract/v1/example.html, plus the front page, built in memory (path -> HTML)."""
    css = bundled_css()
    page = lambda body, title, theme="modern": render_document(trusted_html=body, title=title, theme=theme, css=css)
    github_like = (
        '<main class="ui-page"><h1 class="ui-title">web-ui · GitHub-like</h1>'
        '<p class="ui-muted">The same semantic component contract with a different theme.</p><section class="ui-grid">'
        '<article class="ui-card"><h2>Repository card</h2><p>Theme files change presentation without changing semantic classes.</p>'
        '<span class="ui-tag">theme</span> <span class="ui-tag">contract-v1</span></article>'
        '<article class="ui-card"><h2>Controls</h2><label for="example-input">Example input</label>'
        '<input class="ui-input" id="example-input" value="shared semantic HTML"> <button class="ui-button" type="button">Example button</button></article>'
        '</section><section class="ui-panel"><h2>Output</h2><pre class="ui-output">ui-page / ui-panel / ui-card / ui-button / ui-input</pre></section></main>')
    contract = (
        '<main class="ui-page"><h1 class="ui-title">HTML contract v1</h1><p class="ui-muted">Canonical semantic fixture.</p>'
        '<section class="ui-panel"><div class="stub-toolbar"><label for="contract-query">Query</label>'
        '<input class="ui-input" id="contract-query" value="example"> <button class="ui-button" type="button">Run</button></div>'
        '<p class="stub-status ui-muted">Ready.</p><div class="stub-meta"><span class="ui-tag">contract-v1</span></div></section>'
        '<section class="ui-grid"><article class="ui-card"><h2>Card</h2><p>Consumer-owned content.</p></article></section>'
        '<pre class="ui-output">text-safe output</pre></main>')
    return {
        "examples/index.html": page('<main class="ui-page"><h1 class="ui-title">web-ui</h1><p class="ui-muted">Shared static UI contract for '
                                    'myon-bioinformatics projects.</p>' + _example_cards() + "</main>", "web-ui examples"),
        "examples/mcp-stub.html": stub_document(EXAMPLE_STUBS["mcp"]),
        "examples/api-stub.html": stub_document(EXAMPLE_STUBS["api"]),
        "examples/github-like.html": page(github_like, "web-ui GitHub-like theme", "github-like"),
        "examples/showcase.html": showcase_document(EXAMPLES["showcase"]),
        "examples/clipboard-shelf.html": shelf_document(),
        "examples/coordinates.html": coordinates_document(),
        "examples/photo-studio.html": photo_document(),
        "examples/composition-studio.html": studio_document(),
        "examples/door.html": door_document(EXAMPLES["door"]),
        "contract/v1/example.html": page(contract, "web-ui HTML contract v1 fixture"),
        "index.html": _index_page(),
    }


# --- Example data as Python (no examples/ files): specs the tools and pages use; `--example NAME` prints one as JSON ----------

EXAMPLES: dict[str, Any] = {'flutter-pages': {'schema': 'web-ui-flutter-pages/1',
                   'base_url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/',
                   'source': 'flutter_navigation_basic lib/shared/navigation/page_identities.g.dart',
                   'pages': [{'route': '/',
                              'key': '🏠',
                              'label': 'Home',
                              'adapter': 'flutter-home',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/'},
                             {'route': '/hub',
                              'key': '🗺️',
                              'label': 'Navigation Hub',
                              'adapter': 'flutter-hub',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/hub'},
                             {'route': '/core/clipboard-shelf',
                              'key': '📋',
                              'label': 'Clipboard Shelf',
                              'adapter': 'flutter-clipboard-shelf',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/core/clipboard-shelf'},
                             {'route': '/tools/time/now-timeline',
                              'key': '🕒',
                              'label': 'Now Timeline',
                              'adapter': 'flutter-now-timeline',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/tools/time/now-timeline'},
                             {'route': '/tools/media/photo-studio',
                              'key': '🖼️',
                              'label': 'Photo Studio',
                              'adapter': 'flutter-photo-studio',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/tools/media/photo-studio'},
                             {'route': '/tools/http/request-draft',
                              'key': '🌐',
                              'label': 'HTTP Request Draft',
                              'adapter': 'flutter-http-request-draft',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/tools/http/request-draft'},
                             {'route': '/examples/ui-showcase',
                              'key': '🎨',
                              'label': 'UI Showcase',
                              'adapter': 'flutter-ui-showcase',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/examples/ui-showcase'},
                             {'route': '/examples/counter-playground',
                              'key': '👾',
                              'label': 'Counter Playground',
                              'adapter': 'flutter-counter',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/examples/counter-playground'},
                             {'route': '/screen1',
                              'key': '🌍',
                              'label': 'Screen 1',
                              'adapter': 'flutter-screen1',
                              'url': 'https://myon-bioinformatics.github.io/flutter_navigation_basic/#/screen1'}]},
 'layout-presets': {'schema': 'web-ui-layout-presets/1',
                    'default': 'grid8',
                    'presets': [{'id': 'grid8',
                                 'label': '8px grid',
                                 'note': 'default: 160px tiles, 8px spacing',
                                 'vars': {'--ui-matrix-col': '160px',
                                          '--ui-matrix-gap': '8px',
                                          '--ui-matrix-pad': '8px'}},
                                {'id': 'compact',
                                 'label': 'Compact',
                                 'note': 'more tiles per row on small screens',
                                 'vars': {'--ui-matrix-col': '120px',
                                          '--ui-matrix-gap': '4px',
                                          '--ui-matrix-pad': '4px'}},
                                {'id': 'device',
                                 'label': 'Device width',
                                 'note': '195px = half an iPhone (390px)',
                                 'vars': {'--ui-matrix-col': '195px',
                                          '--ui-matrix-gap': '6px',
                                          '--ui-matrix-pad': '6px'}},
                                {'id': 'wide',
                                 'label': 'Wide',
                                 'note': 'larger tiles for detail',
                                 'vars': {'--ui-matrix-col': '240px',
                                          '--ui-matrix-gap': '16px',
                                          '--ui-matrix-pad': '8px'}}]},

 'door': {'schema': 'web-ui-door/1',
          'current': './door.html',
          'k': 3,
          'seed': 20261103,
          'pages': [{'emoji': '🏠', 'label': 'Home', 'href': '../index.html'},
                    {'emoji': '🧭', 'label': 'Examples', 'href': './index.html'},
                    {'emoji': '📋', 'label': 'Clipboard shelf', 'href': './clipboard-shelf.html'},
                    {'emoji': '🎨', 'label': 'App shell showcase', 'href': './showcase.html'},
                    {'emoji': '🕸️', 'label': 'MCP stub', 'href': './mcp-stub.html'},
                    {'emoji': '🌐', 'label': 'API stub', 'href': './api-stub.html'},
                    {'emoji': '🐙', 'label': 'GitHub-like theme', 'href': './github-like.html'},
                    {'emoji': '🚪', 'label': 'Door-to-Door', 'href': './door.html'},
                    {'emoji': '🗺️', 'label': 'World', 'href': '../index.html#world', 'group': 'discover'},
                    {'emoji': '🔗', 'label': 'Request draft', 'href': '../index.html#curl', 'group': 'discover'},
                    {'emoji': '🌈', 'label': 'Random themes', 'href': '../index.html#wall', 'group': 'discover'},
                    {'emoji': '🎛️', 'label': 'Try it', 'href': '../index.html#try', 'group': 'discover'},
                    {'emoji': '🧪', 'label': 'MCP on the front page', 'href': '../index.html#mcp', 'group': 'discover'},
                    {'emoji': '📡', 'label': 'API on the front page', 'href': '../index.html#api', 'group': 'discover'}]}, 'showcase': {'schema': 'web-ui-showcase/1',
              'id': 'showcase',
              'title': 'UI Showcase',
              'emoji': '🎨',
              'favorite': True,
              'themes': True,
              'sections': [{'id': 'overview',
                            'label': 'Overview',
                            'icon': 'overview',
                            'heading': 'One shell, any content',
                            'lead': 'Python builds this page from one spec. Pick a section on the rail (wide screens) or the bottom bar (narrow ones).',
                            'tags': ['Python builds it', 'No reload', 'No script to switch', 'Any theme'],
                            'cards': [{'icon': 'responsive',
                                       'title': 'Responsive navigation',
                                       'body': 'A rail on wide screens and a bottom bar on narrow ones; both choose the same section.'},
                                      {'icon': 'tune',
                                       'title': 'Data in, page out',
                                       'body': 'Labels, icons and sections come from data, so another repository only supplies its own spec.'},
                                      {'icon': 'layers',
                                       'title': 'Low coupling',
                                       'body': 'Plain ui-* classes and tokens only: every theme, including random ones, applies.'}]},
                           {'id': 'components',
                            'label': 'Components',
                            'icon': 'components',
                            'heading': 'Components',
                            'lead': 'The shared controls, as the current theme draws them.',
                            'controls': True},
                           {'id': 'data',
                            'label': 'Data',
                            'icon': 'data',
                            'heading': 'Data',
                            'table': {'columns': ['Piece', 'Written in', 'Checked by'],
                                      'rows': [['Rules', 'Python', 'unit tests'],
                                               ['Page script', 'JavaScript', 'Chromium, against Python'],
                                               ['Styles', 'CSS, from Python', 'contrast and layout sweeps']]}},
                           {'id': 'media',
                            'label': 'Media',
                            'icon': 'media',
                            'heading': 'Media',
                            'lead': 'Images are plain img elements with alt text; data-ui-lightbox opens them larger.',
                            'tags': ['img', 'alt text', 'lightbox']}]},
 'world': {'schema': 'web-ui-world/1',
           'id': 'demo',
           'title': 'web-ui world (prototype)',
           'zoom_max': 4,
           'shots': [{'id': 'gate',
                      'label': 'SHOT 01',
                      'title': 'Arrive',
                      'body': 'One page, no page changes. Scroll to move the camera through the shots.',
                      'bg': '#0d1f3a'},
                     {'id': 'hall',
                      'label': 'SHOT 02',
                      'title': 'Look around',
                      'body': 'Each shot is data: a label, a title, a text and a color. Python writes the HTML and '
                              'CSS.',
                      'bg': '#164a41'},
                     {'id': 'deck',
                      'label': 'SHOT 03',
                      'title': 'Zoom in',
                      'body': 'The only JavaScript marks what is on screen; CSS reacts to that mark.',
                      'bg': '#5a2a1a'},
                     {'id': 'exit',
                      'label': 'SHOT 04',
                      'title': 'Find it',
                      'body': 'Scrolling reaches the information you came for.',
                      'bg': '#2a2a5a'}],
           'floors': [{'id': '1f',
                       'label': '1F',
                       'width': 960,
                       'height': 640,
                       'spots': [{'id': 'gate',
                                  'x': 120,
                                  'y': 320,
                                  'label': 'Gate',
                                  'category': 'info',
                                  'body': 'Entrance and help desk.'},
                                 {'id': 'hall',
                                  'x': 480,
                                  'y': 320,
                                  'label': 'Hall',
                                  'category': 'info',
                                  'body': 'The central hall connects every area.'},
                                 {'id': 'cafe',
                                  'x': 800,
                                  'y': 160,
                                  'label': 'Cafe',
                                  'category': 'food',
                                  'body': 'Drinks and light meals.'},
                                 {'id': 'shop',
                                  'x': 800,
                                  'y': 480,
                                  'label': 'Shop',
                                  'category': 'food',
                                  'body': 'Snacks and souvenirs.'}],
                       'actors': [{'id': 'farmer',
                                   'emoji': '🧑\u200d🌾',
                                   'label': 'Farmer',
                                   'body': 'Walks at a steady pace and stops to look around. Tap to ask.'},
                                  {'id': 'cat',
                                   'emoji': '🐈',
                                   'label': 'Cat',
                                   'body': 'Wanders; no destination.',
                                   'speed': 64},
                                  {'id': 'duck',
                                   'emoji': '🦆',
                                   'label': 'Duck',
                                   'body': 'Slow and sure.',
                                   'speed': 32},
                                  {'id': 'robot',
                                   'emoji': '🤖',
                                   'label': 'Robot',
                                   'body': 'Moves in straight lines at constant speed.',
                                   'speed': 56}],
                       'player': {'emoji': '🧙', 'x': 120, 'y': 320}},
                      {'id': '2f',
                       'label': '2F',
                       'width': 960,
                       'height': 640,
                       'spots': [{'id': 'deck',
                                  'x': 240,
                                  'y': 160,
                                  'label': 'Deck',
                                  'category': 'info',
                                  'body': 'Open-air deck with a view of the hall.'},
                                 {'id': 'lab',
                                  'x': 720,
                                  'y': 400,
                                  'label': 'Lab',
                                  'category': 'info',
                                  'body': 'Hands-on corner for the curious.'}],
                       'actors': [{'id': 'owl',
                                   'emoji': '🦉',
                                   'label': 'Owl',
                                   'body': 'Keeps the deck company.',
                                   'speed': 40}]}],
           'board': {'title': 'INFO',
                     'items': [{'text': 'Gate: wait about 10 min'},
                               {'text': 'Show starts', 'at': '10:30'},
                               {'text': 'Guided walk', 'at': '14:00'},
                               {'text': 'Last entry', 'at': '17:30'},
                               {'text': 'London lunch', 'at': '12:00', 'zone': 'london'},
                               {'text': 'Open hours', 'gauge': {'from': '09:00', 'to': '18:00', 'cells': 10, 'glyphs': 'hourglass'}},
                               {'text': 'Daylight', 'gauge': {'from': '06:00', 'to': '22:00', 'cells': 8, 'glyphs': 'moon'}}],
                     'shared_issue': 'myon-bioinformatics/web-ui/110',
                     'post': True,
                     'offset_label': True,
                     'zones': [{'id': 'tokyo', 'label': 'Tokyo', 'tz': 'Asia/Tokyo'},
                               {'id': 'london', 'label': 'London', 'tz': 'Europe/London'},
                               {'id': 'ny', 'label': 'New York', 'tz': 'America/New_York'}]}}}


def example_data(name: str) -> Any:
    """A copy of one example spec: ``flutter-pages``, ``layout-presets``, ``world``, ``showcase`` or ``door``."""
    try:
        return json.loads(json.dumps(EXAMPLES[name]))
    except KeyError:
        raise ValueError(f"unknown example: {name} (one of {', '.join(EXAMPLES)})") from None


# Sweep result for the layout switch on the front page (python tool/layout_presets.py sweep ... --out candidates.json).
_INDEX_LAYOUT_CANDIDATES = {"schema": "web-ui-layout-candidates/1", "presets": {
    name: {"passed": [320, 384, 768, 1280], "failed": []} for name in ("grid8", "compact", "device", "wide")}}


def _index_page() -> str:
    """The front page (index.html): one self-contained page holding every example. Needs a checkout (tool/layout_presets.py)."""
    import importlib
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "tool"))
    try:
        layout_presets = importlib.import_module("layout_presets")
    finally:
        sys.path.pop(0)
    world, presets = example_data("world"), example_data("layout-presets")
    css = bundled_css() + layout_presets.css(presets) + world_css(world) + _WALL_CSS
    theme_radios = "".join(
        f'<label><input type="radio" name="ui-theme" value="{t}"{" checked" if t == "modern" else ""}> {t}</label>'
        for t in (*THEMES, *CANDIDATE_THEMES))
    cards = "".join(
        f'<article class="ui-card"><h2>{title}</h2><p>{text}</p><a href="#{anchor}">{link} →</a></article>'
        for title, text, anchor, link in (
            ("Try it", "Switch theme and layout live: no reload, no stylesheet swap.", "try", "Open the switches"),
            ("MCP workspace", "Reusable MCP-style result/evidence/history structure, with a declarative mock.", "mcp", "Open MCP stub"),
            ("API workspace", "Same semantic workspace with consumer-owned API behavior.", "api", "Open API stub"),
            ("World (prototype)", "One page, a camera: scroll the shots, pan and zoom the map.", "world", "Open the world"),
            ("Random themes", "Seeded palettes side by side; every text pair meets WCAG AA.", "wall", "Open the wall")))
    tiles = "".join(f"<li>tile {i}</li>" for i in range(1, 9))
    body = (
        '<main class="ui-page"><header class="stub-header"><div>'
        '<img src="./docs/brand/icon.png" width="80" height="80" alt="web-ui icon"><h1 class="ui-title">web-ui</h1>'
        '<p class="ui-muted">Shared static-first UI contract for myon-bioinformatics projects.</p></div>'
        '<div class="stub-meta"><span class="ui-tag">v1</span><span class="ui-tag">build-free</span></div></header>'
        f'<section class="ui-grid">{cards}</section>'
        '<section class="ui-panel" id="try"><h2>Try it</h2><p class="ui-muted">Both switches act at once: no reload. The theme is saved in '
        'this browser; the layout is plain CSS.</p>'
        f'<fieldset class="ui-layout-switch"><legend>Theme</legend>{theme_radios}</fieldset>'
        f'{layout_presets.controls_html(presets, _INDEX_LAYOUT_CANDIDATES)}<ul class="ui-matrix-tiles">{tiles}</ul></section>'
        f'<section>{stub_html(EXAMPLE_STUBS["mcp"], heading_level=2)}</section>'
        f'<section>{stub_html(EXAMPLE_STUBS["api"], heading_level=2)}</section>'
        '<section class="ui-panel" id="curl" data-ui-curl><h2>Request draft (curl)</h2><p class="ui-muted">Paste a curl command: it is read in this '
        'page and never run or sent. Credentials show as <code>***</code>; the body is shown as written, so do not paste real secrets. '
        'Python reads it the same way (<code>web_ui.parse_curl</code>).</p>'
        '<textarea class="ui-input" data-curl-input rows="4" aria-label="curl command">curl -X POST https://api.example.com/items -H '
        '"Authorization: Bearer abc" -H "Content-Type: application/json" -d \'{"name":"demo"}\'</textarea> '
        '<button class="ui-button" type="button" data-curl-run>Parse</button><pre class="ui-output" data-curl-output aria-live="polite"></pre></section>'
        '<section class="ui-panel" id="world"><h2>World (prototype)</h2><p class="ui-muted">One page, a camera, no page changes. Scroll the shots; '
        'drag, wheel or pinch the map and open a spot. Python writes this HTML, the CSS and the small script from '
        f'<code>EXAMPLES["world"]</code>.</p>{world_html(world)}</section>'
        '<section class="ui-panel" id="wall"><h2>Random themes, side by side</h2><p class="ui-muted">Twelve seeded palettes at once; every text '
        f'pair meets WCAG AA by construction.</p>{theme_wall(range(12))}</section></main>'
        + module_script(stub_script(EXAMPLE_STUBS["mcp"], EXAMPLE_STUBS["api"]) + "bindTheme();\n") + module_script(_JS["curl.js"]) + module_script(WORLD_JS))
    return ('<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n'
            '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '  <link rel="icon" type="image/png" href="./docs/brand/favicon.png">\n  <title>web-ui — static UI contract</title>\n'
            f'  <style>{css}</style>\n<link rel="apple-touch-icon" href="./docs/brand/icon.png"></head>\n'
            f'<body data-ui-theme="modern">\n{body}\n</body>\n</html>\n')


def js_modules() -> dict[str, str]:
    """Every browser module by file name (ui.js, stub.js, controls.js, collection.js, navigation.js, repository-diagnostics.js, curl.js, shelf.js, door.js, composition.js, coordinates.js, world.js)."""
    return {**_JS, "world.js": WORLD_JS}


def js_source(name: str) -> str:
    try:
        return js_modules()[name]
    except KeyError:
        raise ValueError(f"unknown module: {name}") from None


def write_js(directory: str | Path) -> list[str]:
    """Write the browser modules under ``directory/js/`` (for pages that link them, and for the Node tests); returns the paths."""
    written = []
    for name, source in js_modules().items():
        target = Path(directory) / "js" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source)
        written.append(f"js/{name}")
    return written


def write_examples(directory: str | Path) -> list[str]:
    """Write each example spec as ``directory/examples/NAME.json`` (for tools whose CLI takes a file path); returns the paths."""
    written = []
    for name in EXAMPLES:
        target = Path(directory) / "examples" / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(EXAMPLES[name], ensure_ascii=False, indent=2) + "\n")
        written.append(f"examples/{name}.json")
    return written


def write_site(directory: str | Path) -> list[str]:
    """Write example_pages() and the browser modules under ``directory`` (CI screenshots, local viewing, Node tests); returns the paths."""
    written = []
    for name, html in example_pages().items():
        target = Path(directory) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(html)
        written.append(name)
    # The generated front page references these local brand images.
    source_root = Path(__file__).resolve().parent
    for name in ("docs/brand/icon.png", "docs/brand/favicon.png"):
        source, target = source_root / name, Path(directory) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        written.append(name)
    return written + write_js(directory) + write_examples(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="web-ui")
    parser.add_argument("--theme", choices=THEMES + CANDIDATE_THEMES, default="modern")
    parser.add_argument("--css", type=Path, help="trusted CSS file to embed")
    parser.add_argument("--world", type=Path, metavar="FILE",
                        help="print a single-file page for a web-ui-world/1 JSON spec and exit")
    parser.add_argument("--example", metavar="NAME", help="print one example spec as JSON and exit (flutter-pages, layout-presets, world, showcase, door)")
    parser.add_argument("--btk-adapter", metavar="ID", help="print one browser-test-kit platform adapter (btk-platform-adapter/1) as JSON and exit; `list` names them")
    parser.add_argument("--url", metavar="URL", help="with --btk-adapter: the address of the page to check (default: the local example server)")
    parser.add_argument("--site", type=Path, metavar="DIR",
                        help="write the example pages, the front page (index.html), js/ and examples/*.json under DIR and exit")
    parser.add_argument("--theme-wall", type=int, metavar="N",
                        help="print a page showing N seeded random themes side by side and exit")
    parser.add_argument("--css-bundle", action="store_true",
                        help="embed every web-ui stylesheet and theme (see bundled_css) in the page")
    parser.add_argument("--asset-base", help="local or pinned HTTPS shared asset directory")
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
    if args.example:
        try:
            sys.stdout.write(json.dumps(example_data(args.example), ensure_ascii=False, indent=2) + "\n")
        except ValueError as exc:
            parser.error(str(exc))
        return 0
    if args.btk_adapter:
        try:
            sys.stdout.write("\n".join(sorted(BTK_ADAPTERS)) + "\n" if args.btk_adapter == "list"
                             else json.dumps(btk_adapter(args.btk_adapter, args.url), ensure_ascii=False, indent=2) + "\n")
        except ValueError as exc:
            parser.error(str(exc))
        return 0
    if args.site:
        try:
            for name in write_site(args.site):
                print(name)
        except OSError as exc:
            parser.error(str(exc))
        return 0
    if args.world or args.theme_wall is not None:
        try:
            sys.stdout.write(world_document(json.loads(args.world.read_text(encoding="utf-8")), theme=args.theme)
                             if args.world else theme_wall_document(args.theme_wall))
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        return 0
    if args.with_scripts is not None and not args.asset_base:
        parser.error("--with-scripts requires --asset-base")
    try:
        content = sys.stdin.read()
        css = (bundled_css() if args.css_bundle else "") + (args.css.read_text(encoding="utf-8") if args.css else "")
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
