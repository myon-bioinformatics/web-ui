export function setText(target,value){const node=typeof target==="string"?document.querySelector(target):target;if(node)node.textContent=String(value)}
export function prettyJson(value){return JSON.stringify(value,null,2)}
export async function copyText(value){await navigator.clipboard.writeText(String(value))}
