/** Set text-only content. User-controlled values are never interpreted as HTML. */
export function setText(target,value){const node=typeof target==="string"?document.querySelector(target):target;if(node)node.textContent=String(value)}
/** Serialize a value for human-readable text output. */
export function prettyJson(value){return JSON.stringify(value,null,2)}
/** Copy a value to the browser clipboard as text. */
export async function copyText(value){await navigator.clipboard.writeText(String(value))}
