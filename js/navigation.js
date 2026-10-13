/** Shared declarative source links and view switching; no fetch or storage.
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
  function bindNavigation(win){
    const doc=win.document;
    const links=[...doc.querySelectorAll('[data-ui-source-for]')].map(link=>bindSourceLink(doc.getElementById(link.getAttribute('data-ui-source-for')),link));
    const views=doc.querySelectorAll('[data-ui-view]').length?bindViews(win,{defaultView:doc.querySelector('[data-ui-default-view]')?.getAttribute('data-ui-default-view')||'home'}):null;
    return {links,views};
  }
  return {sourceURL,openExternalURL,bindSourceLink,viewFromLocation,bindViews,bindNavigation};
});
