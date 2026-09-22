import{setText,prettyJson}from"./ui.js";
/**
 * Bind one text input to an async or sync consumer handler.
 *
 * handler receives the input string and may return either text or any
 * JSON-serializable value. Protocol-specific validation and semantics belong
 * to the consuming repository, not web-ui.
 */
export function bindStub({input="#query",run="#run",output="#output",form="#stub-form",handler}){const q=document.querySelector(input),b=document.querySelector(run),f=document.querySelector(form);if(!q||!b)return;const execute=async event=>{event?.preventDefault();b.disabled=true;try{const result=await handler(q.value);setText(output,typeof result==="string"?result:prettyJson(result))}catch(error){setText(output,`Error: ${error?.message??error}`)}finally{b.disabled=false}};(f??b).addEventListener(f?"submit":"click",execute)}
