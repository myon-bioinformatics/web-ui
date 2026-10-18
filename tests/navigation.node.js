const assert=require('node:assert/strict');
const ui=require('../js/navigation.js');
assert.equal(ui.sourceURL('https://example.test/a'),'https://example.test/a');
for(const value of ['javascript:alert(1)','data:text/html,x','ftp://example.test/','https://u:p@example.test/','https://example.test/ bad','https://example.test\\bad','//example.test/',''])assert.throws(()=>ui.sourceURL(value));
let opened;const win={open:(...args)=>opened=args};ui.openExternalURL('https://example.test/',win);assert.deepEqual(opened,['https://example.test/','_blank','noopener,noreferrer']);
const views=['home','wiki','pixiv'];
assert.equal(ui.viewFromLocation('#pixiv','',views,'home'),'pixiv');
assert.equal(ui.viewFromLocation('#wiki?title=A','',views,'home'),'wiki');
assert.equal(ui.viewFromLocation('#bad','',views,'home'),'home');
assert.equal(ui.viewFromLocation('#pixiv','?view=wiki',views,'home',{wiki:'wiki'}),'wiki');
assert.equal(ui.viewFromLocation('#pixiv','?view=unlisted',views,'home',{wiki:'wiki'}),'pixiv');

// Route table: shared cases with web_ui.route_table (tests/fixtures/route_table_cases.json).
const cases=require('./fixtures/route_table_cases.json');
for(const c of cases.valid){const t=ui.routeTable(c.registry);for(const [k,v] of Object.entries(c.lookups))assert.equal(t.lookup(k),v,c.name+': '+k);}
for(const c of cases.invalid)assert.throws(()=>ui.routeTable(c.registry),undefined,c.name);
assert.equal(ui.routeHref('/map'),'#/map');
assert.equal(ui.routeHref('/map',{base:'https://example.test/app/',routing:'path'}),'https://example.test/app/map');
assert.throws(()=>ui.routeHref('/map',{routing:'query'}));
{ // fake window: links get hrefs, the current page is marked, go() and buttons navigate, destroy unbinds.
  const listeners={},docListeners={};
  const el=(tag,key)=>({tagName:tag,attrs:{'data-ui-go':key},getAttribute(n){return this.attrs[n]??null;},setAttribute(n,v){this.attrs[n]=v;},removeAttribute(n){delete this.attrs[n];},closest(){return this;}});
  const home=el('A','\u{1F3E0}'),map=el('A','\u{1F5FA}'),shades=el('BUTTON','\u{1F576}'),bad=el('A','zz');
  const win={location:{hash:'',pathname:'/'},addEventListener:(n,f)=>listeners[n]=f,removeEventListener:n=>delete listeners[n],
    document:{querySelectorAll:()=>[home,map,shades,bad],addEventListener:(n,f)=>docListeners[n]=f,removeEventListener:n=>delete docListeners[n]}};
  const h=ui.bindRouteTable(win,{'/':'\u{1F3E0}','/map':'\u{1F5FA}\uFE0F','/shades':'\u{1F576}'});
  assert.equal(ui.bindRouteTable(win,{}),h);
  assert.equal(home.attrs.href,'#/');assert.equal(map.attrs.href,'#/map');assert.equal(home.attrs['aria-current'],'page');
  assert.equal(bad.attrs['aria-disabled'],'true');
  assert.equal(h.go('\u{1F5FA}\uFE0F'),'/map');assert.equal(win.location.hash,'/map');
  listeners.hashchange();assert.equal(map.attrs['aria-current'],'page');assert.equal(home.attrs['aria-current'],undefined);
  let prevented=false;docListeners.click({target:shades,preventDefault(){prevented=true;}});
  assert.ok(prevented);assert.equal(win.location.hash,'/shades');
  assert.throws(()=>h.go('nope'));
  h.destroy();assert.equal(listeners.hashchange,undefined);assert.equal(docListeners.click,undefined);
}
