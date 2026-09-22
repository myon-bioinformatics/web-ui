import{setText,prettyJson}from"./ui.js";
/**
 * Bind one text input to an async or sync consumer handler.
 *
 * handler receives the input string and may return either text or any
 * JSON-serializable value. Protocol-specific validation and semantics belong
 * to the consuming repository, not web-ui.
 */
export function bindStub({input="#query",run="#run",output="#output",handler}){const q=document.querySelector(input),b=document.querySelector(run);if(!q||!b)return;b.addEventListener("click",async()=>{b.disabled=true;try{const result=await handler(q.value);setText(output,typeof result==="string"?result:prettyJson(result))}catch(error){setText(output,`Error: ${error?.message??error}`)}finally{b.disabled=false}})}
