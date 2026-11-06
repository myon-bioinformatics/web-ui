// Deterministic DOM/clock harness, NOT a real-browser rendering test.
import assert from 'node:assert/strict';
let now=0, frame, globalEvents={};
globalThis.performance={now:()=>now*1000};
let wall=1800000000000;
const RealDate=Date;globalThis.Date=class extends RealDate{constructor(...args){super(...(args.length?args:[wall+now*1000]))}getTimezoneOffset(){return 0}};
globalThis.setInterval=()=>0;globalThis.clearInterval=()=>{};
globalThis.requestAnimationFrame=f=>{frame=f};
globalThis.addEventListener=(name,f)=>{globalEvents[name]=f};
globalThis.location={hash:'',pathname:'/',search:''};
globalThis.history={replaceState(){}};
const reduced={matches:false,addEventListener(name,f){this.change=f}};
globalThis.matchMedia=()=>reduced;
function node(){return {dataset:{},style:{setProperty(k,v){this[k]=String(v)}},events:{},addEventListener(n,f){this.events[n]=f},setAttribute(n,v){this[n]=v},toggleAttribute(n,v){this[n]=v}}}
const actor=node(), avatar=node(), button=node(), board=node(), form=node();
form.elements={x:{value:'100'},y:{value:'32'}};form.reportValidity=()=>true;
const controls=node();controls.querySelector=s=>s==='form'?form:s==='output'?board:button;
avatar.dataset={x:'64',y:'32',speed:'10'};
const clock=node(), countdown=node();countdown.dataset.at='10:30';board.dataset.offset='0';
board.querySelector=s=>s==='[data-clock]'?clock:null;board.querySelectorAll=s=>s==='[data-at]'?[countdown]:[];   // the board also has gauges now: answer by selector
const f=node();f.dataset={w:'128',h:'64',floor:'one'};f.querySelector=()=>avatar;f.getBoundingClientRect=()=>({left:0,top:0,width:128,height:64});
const other=node();other.dataset={w:'128',h:'64',floor:'two'};other.querySelector=()=>null;other.getBoundingClientRect=f.getBoundingClientRect;
const radio={value:'one'}, view=node(),cam=node();view.clientWidth=128;view.clientHeight=64;view.contains=t=>t===view;view.closest=()=>null;view.hasPointerCapture=()=>false;view.setPointerCapture=()=>{};
const el=node();el.isConnected=true;el.dataset.zoomMax=4;
el.querySelector=s=>s==='.ui-world-pause'?button:s==='.ui-world-view'?view:s==='.ui-world-cam'?cam:s==='.ui-world-motion-controls'?controls:s==='.ui-board'?board:s.includes('input[name$="-floor"]')?radio:s.includes('data-floor="two"')?other:s==='.ui-floor'||s.includes('data-floor="one"')?f:null;
el.querySelectorAll=s=>s==='.ui-floor'?[f,other]:[];
bindMap(el);
const tick=t=>{now=t;const cb=frame;frame=null;cb()};
const pos=()=>[parseFloat(avatar.style['--px']),parseFloat(avatar.style['--py'])];
const event=(id,x,y,type='pointerup')=>({button:0,pointerId:id,clientX:x,clientY:y,target:view,type});
const tap=(x,y)=>{view.events.pointerdown(event(1,x,y,'pointerdown'));globalEvents.pointerup(event(1,x,y))};
tick(0);assert.deepEqual(pos(),[64,32]);assert.equal(countdown.textContent.includes('あと'),true);
tap(104,32);tick(2);assert.deepEqual(pos(),[84,32]);
tap(84,52);tick(3);assert.deepEqual(pos(),[84,42]);
button.events.click();tick(8);assert.deepEqual(pos(),[84,42]);assert.equal(button['aria-pressed'],'true');
button.events.click();tick(9);assert.deepEqual(pos(),[84,52]);
// Drags, a motionless pinch, and cancellation must never create a destination.
view.events.pointerdown(event(1,10,10));view.events.pointermove(event(1,50,10));globalEvents.pointerup(event(1,50,10));tick(10);assert.deepEqual(pos(),[84,52]);
view.events.pointerdown(event(1,10,10));view.events.pointerdown(event(2,20,20));globalEvents.pointerup(event(2,20,20));globalEvents.pointerup(event(1,10,10));tick(11);assert.deepEqual(pos(),[84,52]);
view.events.pointerdown(event(1,10,10));globalEvents.pointercancel(event(1,10,10,'pointercancel'));tick(12);assert.deepEqual(pos(),[84,52]);
// Keyboard form uses exactly the same destination path.
form.elements.x.value='104';form.elements.y.value='52';form.events.submit({preventDefault(){}});tick(13);assert.deepEqual(pos(),[94,52]);
reduced.matches=true;reduced.change();tick(20);assert.deepEqual(pos(),[94,52]);
form.elements.x.value='12';form.elements.y.value='10';form.events.submit({preventDefault(){}});assert.deepEqual(pos(),[12,10]);
reduced.matches=false;reduced.change();tick(21);assert.deepEqual(pos(),[12,10]);
// No board/form leakage into a floor without motion; return keeps avatar state.
radio.value='two';el.events.change({target:{name:'demo-floor'}});tick(22);assert.equal(form.hidden,true);tap(1,1);
radio.value='one';el.events.change({target:{name:'demo-floor'}});tick(23);assert.equal(form.hidden,false);assert.deepEqual(pos(),[12,10]);
// Wall clock can jump without changing monotonic motion.
wall=0;tick(23);assert.deepEqual(pos(),[12,10]);
el.isConnected=false;tick(24);assert.equal(frame,null);
console.log('motion interaction harness passed');
