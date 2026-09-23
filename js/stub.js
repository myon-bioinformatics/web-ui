import{setText,prettyJson,copyText}from"./ui.js";

/** Convert a handler result into deterministic text output. */
export function formatStubValue(value){
  return typeof value==="string"?value:prettyJson(value);
}

/** Small, failure-tolerant localStorage history helper for generic Stub UIs. */
export function createHistoryStore(key,{limit=8,storage=globalThis.localStorage}={}){
  const read=()=>{
    if(!key||!storage)return[];
    try{
      const value=JSON.parse(storage.getItem(key)||"[]");
      return Array.isArray(value)?value.slice(0,limit):[];
    }catch{return[]}
  };
  const write=items=>{
    if(!key||!storage)return;
    try{storage.setItem(key,JSON.stringify(items.slice(0,limit)))}catch{}
  };
  return{
    read,
    push(entry){
      const next=[entry,...read().filter(item=>item?.input!==entry.input)];
      write(next);
      return next.slice(0,limit);
    },
    clear(){
      if(!key||!storage)return;
      try{storage.removeItem(key)}catch{}
    }
  };
}

/**
 * Bind a generic request/result Stub surface.
 *
 * The consumer-provided handler owns protocol semantics. web-ui only provides
 * browser interaction, text-safe output, optional copy/clear controls, and
 * optional local input history.
 */
export function bindStub({
  input="#query",
  run="#run",
  output="#output",
  form="#stub-form",
  status="#status",
  copy="#copy-output",
  clear="#clear-history",
  history="#history",
  historyKey,
  maxHistory=8,
  handler
}){
  const q=document.querySelector(input);
  const b=document.querySelector(run);
  const f=document.querySelector(form);
  const out=document.querySelector(output);
  const statusNode=document.querySelector(status);
  const copyButton=document.querySelector(copy);
  const clearButton=document.querySelector(clear);
  const historyNode=document.querySelector(history);
  if(!q||!b||typeof handler!=="function")return null;

  const store=createHistoryStore(historyKey,{limit:maxHistory});
  let lastText=out?.textContent??"";

  const renderHistory=()=>{
    if(!historyNode)return;
    historyNode.replaceChildren();
    const items=store.read();
    if(!items.length){
      const empty=document.createElement("p");
      empty.className="ui-muted";
      empty.textContent="No recent requests.";
      historyNode.appendChild(empty);
      return;
    }
    for(const item of items){
      const button=document.createElement("button");
      button.type="button";
      button.className="ui-button stub-history-item";
      button.textContent=item.input||"(empty)";
      button.addEventListener("click",()=>execute(item.input));
      historyNode.appendChild(button);
    }
  };

  const execute=async forcedInput=>{
    const value=forcedInput??q.value;
    if(forcedInput!==undefined)q.value=forcedInput;
    b.disabled=true;
    setText(statusNode,"Running…");
    try{
      const result=await handler(value);
      lastText=formatStubValue(result);
      setText(out,lastText);
      setText(statusNode,"Completed.");
      if(historyKey){
        store.push({input:value,at:new Date().toISOString()});
        renderHistory();
      }
      return result;
    }catch(error){
      lastText=`Error: ${error?.message??error}`;
      setText(out,lastText);
      setText(statusNode,"Failed.");
      throw error;
    }finally{
      b.disabled=false;
    }
  };

  const onExecute=event=>{
    event?.preventDefault();
    execute().catch(()=>{});
  };
  (f??b).addEventListener(f?"submit":"click",onExecute);

  copyButton?.addEventListener("click",()=>copyText(lastText));
  clearButton?.addEventListener("click",()=>{
    store.clear();
    renderHistory();
  });

  renderHistory();
  return{execute,readHistory:store.read,clearHistory:store.clear};
}
