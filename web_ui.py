"""Dependency-free static HTML wrapper (Python 3.10+).

Text is escaped by default. HTML and CSS supplied explicitly are trusted source,
not sanitized user input. Rendering never fetches assets; fetch_plotly_js() is an
explicit download helper with bounded reads. JavaScript is omitted
by default; callers may opt in to local module script links. Node is wrapped
only as an explicit subprocess helper for pytest/CI one-liners.
"""
from __future__ import annotations

import argparse
import colorsys
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
import random
import re
import shutil
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request
import zlib
from urllib.parse import urlsplit

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



def catalog_document(spec: Any, *, theme: str = "modern") -> str:
    """Build a self-contained, script-free catalog from consumer-owned data.

    ``web-ui-catalog/1`` accepts title, optional description and items. Each
    item has id/title and optional summary/category/details/links. Links have
    label/href. Text is never HTML; links are relative paths or HTTPS URLs.
    File writing, data collection and publication remain consumer-owned.
    """
    def mapping(value: Any, required: set[str], optional: set[str], label: str) -> dict:
        if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
            raise ValueError(f"invalid {label} fields")
        return value

    def text(value: Any, label: str, *, limit: int = 4000, required: bool = False) -> str:
        if (not isinstance(value, str) or len(value) > limit
                or any(ord(c) < 32 and c not in "\n\t" for c in value)
                or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
                or required and not value.strip()):
            raise ValueError(f"invalid {label}")
        return value

    def href(value: Any) -> str:
        value = text(value, "link href", limit=2048, required=True)
        # Do not let browser URL preprocessing turn whitespace/backslashes into
        # an executable scheme or a protocol-relative external destination.
        if any(c.isspace() for c in value) or "\\" in value:
            raise ValueError("link href must not contain whitespace or backslashes")
        parsed = urlsplit(value)
        if parsed.scheme:
            if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("external links must be HTTPS without credentials")
            try:
                parsed.port
            except ValueError:
                raise ValueError("invalid HTTPS port") from None
        elif parsed.netloc or value.startswith("/") or ":" in parsed.path.split("/", 1)[0]:
            raise ValueError("local links must be relative to the generated page")
        return value

    mapping(spec, {"schema", "title", "items"}, {"description"}, "catalog")
    if spec["schema"] != "web-ui-catalog/1":
        raise ValueError("expected web-ui-catalog/1")
    title = text(spec["title"], "title", limit=200, required=True)
    description = text(spec.get("description", ""), "description")
    items = spec["items"]
    if not isinstance(items, list) or len(items) > 512:
        raise ValueError("items must be a list of at most 512 entries")
    seen, navigation, articles = set(), [], []
    for item in items:
        mapping(item, {"id", "title"}, {"summary", "category", "details", "links"}, "item")
        identity = _element_id(text(item["id"], "item id", limit=128, required=True))
        if identity in seen:
            raise ValueError("duplicate item id")
        seen.add(identity)
        heading = text(item["title"], "item title", limit=200, required=True)
        summary = text(item.get("summary", ""), "summary")
        category = text(item.get("category", ""), "category", limit=100)
        extra = text(item.get("details", ""), "details", limit=16000)
        links = item.get("links", [])
        if not isinstance(links, list) or len(links) > 32:
            raise ValueError("links must be a list of at most 32 entries")
        rendered_links = []
        for link in links:
            mapping(link, {"label", "href"}, set(), "link")
            label = text(link["label"], "link label", limit=200, required=True)
            target = href(link["href"])
            rendered_links.append(f'<li><a href="{escape(target, quote=True)}">{escape(label)}</a></li>')
        content = ((badge(category) if category else "") + f'<p>{escape(summary)}</p>'
                   + (details(heading, extra) if extra else "")
                   + ("<ul>" + "".join(rendered_links) + "</ul>" if rendered_links else ""))
        # Prefix consumer IDs so names like 'top' cannot collide with our index.
        articles.append(f'<section id="catalog-item-{identity}" tabindex="-1">'
                        + card(title=heading, trusted_html=content) + '</section>')
        navigation.append(f'<li><a href="#catalog-item-{identity}">{escape(heading)}</a></li>')
    body = (f'<main class="ui-page ui-catalog"><header><h1>{escape(title)}</h1>'
            f'<p>{escape(description)}</p></header>'
            f'<nav aria-label="{escape(title, quote=True)}"><ul>{"".join(navigation)}</ul></nav>'
            + "".join(articles) + '</main>')
    # Only the three shared core sheets and selected theme, not every feature's
    # CSS or JavaScript. No images, remote fonts, fetches or storage are needed.
    names = (*_CSS_CORE, f"themes/{theme}.css") if theme in THEMES else _CSS_CORE
    css = "@layer base,components,theme;" + "".join(css_source(name) for name in names)
    css += ".ui-catalog{overflow-wrap:anywhere}.ui-catalog section{scroll-margin-top:1rem}"
    return render_document(title=title, theme=theme, css=css, trusted_html=body)

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
        if not isinstance(board, dict) or set(board) - {"title", "items", "post", "offset_minutes"} or not isinstance(board.get("items"), list) \
                or not 1 <= len(board["items"]) <= 12 or not isinstance(board.get("post", False), bool):
            raise ValueError("a board has a title, 1..12 items and an optional post flag")
        items = []
        for item in board["items"]:
            if not isinstance(item, dict) or set(item) - {"text", "at"}:
                raise ValueError("a board item has text and an optional at")
            at = item.get("at")
            if at is not None and not (isinstance(at, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at)):
                raise ValueError("at must be HH:MM")
            items.append({"text": _world_text(item.get("text"), "text", 120), "at": at})
        board = {"title": _world_text(board.get("title", "INFO"), "title", 24), "items": items, "post": board.get("post", False),
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
        countdown = f' <span class="ui-board-min" data-at="{entry["at"]}"></span>' if entry["at"] else ""
        aria_hidden = ' aria-hidden="true"' if hidden else ""
        return f'<span class="ui-board-item"{aria_hidden}>{escape(entry["text"])}{countdown}</span>'
    chars = sum(len(e["text"]) + (10 if e["at"] else 0) for e in board["items"])
    run = "".join(item(e, False) for e in board["items"]) + "".join(item(e, True) for e in board["items"])
    form = ('<form class="ui-board-post"><input class="ui-input" name="message" maxlength="60" placeholder="Leave a line" '
            'aria-label="Leave a line on the board" autocomplete="off"><button class="ui-button" type="submit">Post</button></form>'
            if board["post"] else "")
    return (f'<div class="ui-board" aria-live="off" data-offset="{board["offset_minutes"] if board["offset_minutes"] is not None else ""}" data-chars="{chars}"><strong>{escape(board["title"])}</strong><span class="ui-board-clock" data-clock>--:--</span>'
            f'<div class="ui-board-track"><div class="ui-board-run" style="animation-duration:{board_seconds(chars)}s">{run}</div></div>{form}</div>')


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
    ".ui-board{display:flex;align-items:center;gap:8px;padding:4px 8px;border-bottom:1px solid var(--ui-border);background:var(--ui-panel);"
    "font-family:var(--ui-font-mono);font-size:.85rem;overflow:hidden}"
    ".ui-board-clock{flex:none;border:1px solid var(--ui-accent);padding:0 .5rem;border-radius:var(--ui-radius)}"
    ".ui-board-track{flex:1;min-width:0;overflow:hidden;white-space:nowrap}"
    ".ui-board-run{display:inline-flex;animation:ui-board-scroll 24s linear infinite}"
    ".ui-board-item{padding-right:3rem}"
    ".ui-board-post{display:flex;gap:4px;flex:none}.ui-board-post .ui-input{width:10rem;padding:.2rem .5rem}.ui-board-post .ui-button{padding:.2rem .6rem}"
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


WORLD_JS = WORLD_MOTION_JS + r"""/* web-ui world: one page, a camera. Shots: scroll marks light up (data-lit). Map: drag, wheel and pinch move a camera; spots open a sheet. No page changes. */
const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));
export function fitZoom(w,h,vw,vh){return Math.min(vw/w,vh/h)}
export function travelSeconds(x0,y0,x1,y1,speed){return Math.hypot(x1-x0,y1-y0)/speed}
export function minutesUntil(now,at){return Math.ceil(((at-now)%1440+1440)%1440)}
export function boardClock(now,offset){const seconds=((now+offset*60)%86400+86400)%86400,whole=Math.floor(seconds);return{clock:[Math.floor(whole/3600),Math.floor(whole/60)%60].map(v=>String(v).padStart(2,"0")).join(":"),minutes:seconds/60}}
export function boardSeconds(chars,cps=8){return Math.max(8,Math.round(chars/cps*10)/10)}
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
const board=el.querySelector(".ui-board"),tick=()=>{const d=new Date(),clock=boardClock(d.getTime()/1000,board.dataset.offset===""?-d.getTimezoneOffset():Number(board.dataset.offset)),now=clock.minutes,c=board.querySelector("[data-clock]");c.textContent=clock.clock;for(const m of board.querySelectorAll("[data-at]")){const[h,mm]=m.dataset.at.split(":").map(Number),left=minutesUntil(now,h*60+mm);m.textContent=left===0?"いま":"あと"+left+"分"}};
if(board){tick();const timer=setInterval(()=>{if(el.isConnected)tick();else clearInterval(timer)},1000);const form=board.querySelector(".ui-board-post");if(form){
const run=board.querySelector(".ui-board-run"),items=[...run.querySelectorAll(".ui-board-item")],base=items.slice(0,items.length/2).map(n=>n.cloneNode(true)),baseChars=Number(board.dataset.chars),notes=[];
form.addEventListener("submit",e=>{e.preventDefault();const input=form.elements.message,text=cleanMessage(input.value);if(!text)return;input.value="";notes.unshift(text);notes.splice(5);run.replaceChildren();
for(const hidden of [false,true]){for(const note of notes){const span=document.createElement("span");span.className="ui-board-item ui-board-note";if(hidden)span.setAttribute("aria-hidden","true");span.textContent=note;run.append(span)}for(const item of base){const copy=item.cloneNode(true);if(hidden)copy.setAttribute("aria-hidden","true");run.append(copy)}}
const chars=baseChars+notes.reduce((n,text)=>n+[...text].length,0);board.dataset.chars=chars;run.style.animationDuration=boardSeconds(chars)+"s";tick()})}}

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
globalThis.webUiWorld={fitZoom,clampFocus,travelSeconds,minutesUntil,boardClock,boardSeconds,cleanMessage,motionWalk,motionSample,bindWorlds};
bindWorlds();
"""


def world_document(spec: Any, *, theme: str = "modern") -> str:
    """A single-file page: bundled CSS, the world's CSS, the world's HTML and one inline module."""
    world = world_validate(spec)
    return render_document(trusted_html=world_html(world), title=world["title"], theme=theme,
                           css=bundled_css() + world_css(world), embedded_modules=("world.js",))


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

STUB_SCHEMA = "web-ui-stub/1"
# stub.js without its import line: it needs setText/prettyJson from ui.js, so an embedded module is ui.js + this.
EMBEDDED_STUB_JS = _JS["stub.js"].split("\n", 1)[1]
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


def _example_cards() -> str:
    return ('<section class="ui-grid"><article class="ui-card"><h2>Components</h2><p>Tokens, panels, cards, tags, controls and output surfaces.</p>'
            '<span class="ui-tag">modern</span> <span class="ui-tag">static</span></article>'
            '<article class="ui-card"><h2>Stub examples</h2><p><a href="./mcp-stub.html">MCP Stub</a> · <a href="./api-stub.html">API Stub</a></p></article>'
            '<article class="ui-card"><h2>Themes</h2><p><a href="./github-like.html">GitHub-like theme</a></p></article></section>')


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
                               {'text': 'Last entry', 'at': '17:30'}],
                     'post': True}}}


# Synthetic consumer data, not fetched research results or a second source of
# repository metadata. Consumers adapt their existing source of truth to this.
EXAMPLES.update({
    "catalog-report": {
        "schema": "web-ui-catalog/1", "title": "Analysis report",
        "description": "Synthetic example: compare observations and inspect their evidence.",
        "items": [
            {"id": "comparison", "title": "Output comparison", "category": "Verification",
             "summary": "The sample outputs match.", "details": "Fixture only; no performance claim.",
             "links": [{"label": "Comparison data", "href": "./evidence/comparison.json"}]},
            {"id": "timing", "title": "Installation time", "category": "Measurement",
             "summary": "Not measured.", "details": "Do not replace unknown values with zero.",
             "links": [{"label": "Method", "href": "./evidence/method.txt"}]},
        ],
    },
    "catalog-projects": {
        "schema": "web-ui-catalog/1", "title": "Project directory",
        "description": "Synthetic example: repository-owned metadata, shared presentation.",
        "items": [
            {"id": "viewer", "title": "資料ビューア 📚", "category": "Tools",
             "summary": "Browse local documents.", "details": "Python generates the page; no runtime server is required.",
             "links": [{"label": "Documentation", "href": "./guide.html"}]},
            {"id": "reports", "title": "Research reports", "category": "Research",
             "summary": "Inspect results and limitations.",
             "links": [{"label": "Reports", "href": "./reports/index.html"}]},
        ],
    },
})


def example_data(name: str) -> Any:
    """A deep copy of a named EXAMPLES spec, including the two consumer catalogs."""
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
        '<section class="ui-panel" id="world"><h2>World (prototype)</h2><p class="ui-muted">One page, a camera, no page changes. Scroll the shots; '
        'drag, wheel or pinch the map and open a spot. Python writes this HTML, the CSS and the small script from '
        f'<code>EXAMPLES["world"]</code>.</p>{world_html(world)}</section>'
        '<section class="ui-panel" id="wall"><h2>Random themes, side by side</h2><p class="ui-muted">Twelve seeded palettes at once; every text '
        f'pair meets WCAG AA by construction.</p>{theme_wall(range(12))}</section></main>'
        + module_script(stub_script(EXAMPLE_STUBS["mcp"], EXAMPLE_STUBS["api"]) + "bindTheme();\n") + module_script(WORLD_JS))
    return ('<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n'
            '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '  <link rel="icon" type="image/png" href="./docs/brand/favicon.png">\n  <title>web-ui — static UI contract</title>\n'
            f'  <style>{css}</style>\n<link rel="apple-touch-icon" href="./docs/brand/icon.png"></head>\n'
            f'<body data-ui-theme="modern">\n{body}\n</body>\n</html>\n')


def js_modules() -> dict[str, str]:
    """Every browser module by file name (ui.js, stub.js, controls.js, collection.js, navigation.js, repository-diagnostics.js, world.js)."""
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
    parser.add_argument("--catalog", type=Path, metavar="FILE",
                        help="print a script-free page for a web-ui-catalog/1 JSON spec and exit")
    parser.add_argument("--world", type=Path, metavar="FILE",
                        help="print a single-file page for a web-ui-world/1 JSON spec and exit")
    parser.add_argument("--example", metavar="NAME", help="print one example spec as JSON and exit (including catalog-report, catalog-projects)")
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
    if args.site:
        try:
            for name in write_site(args.site):
                print(name)
        except OSError as exc:
            parser.error(str(exc))
        return 0
    if args.catalog:
        try:
            result = catalog_document(json.loads(args.catalog.read_text(encoding="utf-8")), theme=args.theme)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(result.encode("utf-8"))
        else:
            sys.stdout.write(result)
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
