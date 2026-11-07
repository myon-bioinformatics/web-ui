const assert=require('node:assert/strict');
const fs=require('fs'),path=require('path');
// The browser modules are Python data: unless WEB_UI_JS_DIR names a folder, ask web_ui.py to write them to a temp folder.
const jsDir = process.env.WEB_UI_JS_DIR || (() => {
  const {mkdtempSync} = fs, {join} = path, {tmpdir} = require("os");
  const out = mkdtempSync(join(tmpdir(), "web-ui-js-"));
  const done = require("child_process").spawnSync(process.env.PYTHON || "python3", ["-S", join(__dirname, "..", "web_ui.py"), "--site", out], {encoding: "utf8"});
  if (done.status !== 0) throw new Error("web_ui.py --site failed: " + done.stderr);
  return join(out, "js");
})();
const ui=require(path.join(jsDir,'source.js'));
const read=n=>fs.readFileSync(path.join(__dirname,'fixtures','source',n),'utf8');
const cases=JSON.parse(read('cases.json'));

// Same cases as tests/test_source_panel.py: identical Markdown, or the identical error text.
for(const c of cases.extract){
  if('markdown' in c)assert.equal(ui.sourceMarkdown(ui.sourceExtract(c.spec,c.source)),c.markdown,c.name);
  else assert.throws(()=>ui.sourceExtract(c.spec,c.source),e=>e.message===c.error,c.name);
}
const n=cases.names;
for(const [text,want] of n.valid)assert.equal(ui.sourceName(n.spec,text),want,JSON.stringify(text));
for(const text of n.invalid)assert.equal(ui.sourceName(n.spec,text),'',JSON.stringify(text));
for(const [text,want] of n.urls)assert.equal(ui.sourceUrl(n.spec,text),want,text);

// The Pokémon spec reproduces the Markdown mcp-toolcall-lab writes for the same JSON, byte for byte.
const pokemon=JSON.parse(read('pokeapi.spec.json')),ditto=read('ditto.json');
assert.equal(ui.sourceMarkdown(ui.sourceExtract(pokemon,ditto)),read('ditto.md'));
assert.equal(ui.sourceMarkdown(ui.sourceExtract(pokemon,JSON.parse(ditto))),read('ditto.md'));
assert.equal(ui.sourceUrl(pokemon,' Ditto '),'https://pokeapi.co/api/v2/pokemon/ditto');
assert.equal(ui.sourceUrl(pokemon,'../x'),'');
assert.throws(()=>ui.sourceExtract(pokemon,'x'.repeat(2*1024*1024+1)),e=>/exceeds/.test(e.message));
assert.throws(()=>ui.sourceExtract(pokemon,'{"name":"x","id":1}'),e=>e.message===pokemon.error);

(async()=>{
  // loadSource: one request, headers fixed, every failure is a value (never a throw).
  const calls=[];
  const reply=(status,body)=>(url,opts)=>{calls.push([url,opts]);return Promise.resolve({status,ok:status>=200&&status<300,text:()=>Promise.resolve(body)});};
  let r=await ui.loadSource(pokemon,'Ditto',reply(200,ditto));
  assert.equal(r.ok,true);assert.equal(ui.sourceMarkdown(r.extract),read('ditto.md'));
  assert.equal(calls.length,1);assert.equal(calls[0][0],'https://pokeapi.co/api/v2/pokemon/ditto');
  assert.equal(calls[0][1].headers.Accept,'application/json');assert.equal(calls[0][1].redirect,'error');assert.equal(calls[0][1].credentials,'omit');
  r=await ui.loadSource(pokemon,'zzz',reply(404,'Not Found'));assert.deepEqual(r,{ok:false,error:'not found: zzz'});
  r=await ui.loadSource(pokemon,'zzz',reply(500,''));assert.deepEqual(r,{ok:false,error:'HTTP 500'});
  r=await ui.loadSource(pokemon,'zzz',reply(200,'<html>'));assert.deepEqual(r,{ok:false,error:'source is not JSON'});
  r=await ui.loadSource(pokemon,'zzz',reply(200,'{"a":1}'));assert.deepEqual(r,{ok:false,error:pokemon.error});
  r=await ui.loadSource(pokemon,'zzz',()=>Promise.reject(new TypeError('Failed to fetch')));
  assert.equal(r.ok,false);assert.match(r.error,/could not fetch \(Failed to fetch\)\. Open the JSON/);
  const before=calls.length;r=await ui.loadSource(pokemon,'bad name!',reply(200,ditto));
  assert.equal(r.ok,false);assert.equal(r.error,pokemon.missing);assert.equal(calls.length,before);

  // bindSource on a fake panel: Extract reads pasted JSON with no request, Fetch asks once, Open shows the address in a new tab.
  const fake=(nameValue)=>{
    const listeners={};
    const el=(k,extra={})=>({k,hidden:false,textContent:'',value:'',disabled:false,addEventListener(n,f){listeners[k+':'+n]=f;},...extra});
    const parts={name:el('name',{value:nameValue}),fetch:el('fetch'),open:el('open'),text:el('text'),extract:el('extract'),status:el('status'),error:el('error',{hidden:true}),output:el('output',{hidden:true})};
    const panel={getAttribute:n=>n==='data-source-spec'?JSON.stringify(pokemon):null,querySelector:s=>parts[s.replace('[data-source-','').replace(']','')]};
    return {listeners,parts,panel};
  };
  const {listeners,parts,panel}=fake('Ditto');
  const opened=[],fetched=[];
  const win={open:(...a)=>opened.push(a)};
  const handle=ui.bindSource(panel,{window:win,fetch:(u,o)=>{fetched.push(u);return Promise.resolve({status:200,ok:true,text:()=>Promise.resolve(ditto)});}});
  assert.equal(ui.bindSource(panel,{window:win}),handle,'binding twice returns the same handle');
  listeners['extract:click']();assert.equal(parts.error.hidden,false);assert.equal(parts.error.textContent,'Paste the JSON first.');assert.equal(parts.output.hidden,true);
  parts.text.value=ditto;listeners['extract:click']();
  assert.equal(parts.error.hidden,true);assert.equal(parts.output.hidden,false);assert.equal(parts.output.textContent,read('ditto.md'));
  assert.match(parts.status.textContent,/ditto \(#132\) — from pasted JSON/);assert.equal(fetched.length,0);
  parts.text.value='nope';listeners['extract:click']();assert.equal(parts.error.textContent,'source is not JSON');assert.equal(parts.output.hidden,true);assert.equal(parts.output.textContent,'');
  listeners['open:click']();assert.deepEqual(opened,[['https://pokeapi.co/api/v2/pokemon/ditto','_blank','noopener,noreferrer']]);
  parts.name.value='no way!';listeners['open:click']();assert.equal(opened.length,1);assert.equal(parts.error.textContent,pokemon.missing);
  parts.name.value='ditto';
  const pending=listeners['fetch:click']();assert.equal(parts.fetch.disabled,true);assert.equal(listeners['fetch:click'](),null,'a second press while one is in flight sends nothing');
  await pending;assert.equal(fetched.length,1);assert.equal(parts.fetch.disabled,false);assert.equal(parts.output.textContent,read('ditto.md'));assert.match(parts.status.textContent,/— fetched$/);

  // No fetch at all (no fetch option, no window.fetch): Fetch says so, and the paste path still works.
  const bare=fake('ditto');ui.bindSource(bare.panel,{window:{open(){}}});
  bare.listeners['fetch:click']();assert.equal(bare.parts.error.hidden,false);assert.match(bare.parts.error.textContent,/fetch is not available/);
  bare.parts.text.value=ditto;bare.listeners['extract:click']();assert.equal(bare.parts.output.textContent,read('ditto.md'));
  console.log('source.js ok');
})().catch(e=>{console.error(e);process.exit(1);});
