/* Click and key dispatch (no inline handlers, so the CSP can forbid inline script), then start */
/* One delegated listener replaces inline handlers, so the page can run under a CSP with no inline script. */
const ACTIONS={render,focusSignin,demoLogin,demoFill,pick,goLogin,goHome,brandHome,togglePw,goTab,moreContent,tourStart,tourStep,tourDo,tourClose,act,approve,addImgRow,comment,createContent,decide,decideDismiss,decideEdit,doImport,kbDel,kbEdit,kbTab,kbClear,loadDemo,openContent,closeContent,removeRow,reqChanges,revise,seed,showNew,toggle,toDecision};
const ELEMENT_ACTIONS=new Set(['removeRow','kbEdit','kbDel']);
function dispatch(t){
  const fn=ACTIONS[t.dataset.c];if(!fn)return;
  // A control that is already working ignores a second click, so nothing is submitted twice.
  if(t.getAttribute('aria-busy')==='true')return;
  let args=[];try{args=t.dataset.a?JSON.parse(t.dataset.a):[]}catch(e){}
  const r=fn(...(ELEMENT_ACTIONS.has(t.dataset.c)?[t]:args));
  if(r&&typeof r.then==='function'&&t.tagName==='BUTTON'){
    t.setAttribute('aria-busy','true');
    const done=()=>t.removeAttribute('aria-busy');r.then(done,done)}}
document.addEventListener('click',e=>{const t=e.target.closest('[data-c]');
  if(t){if(t.tagName==='A'&&!(e.metaKey||e.ctrlKey||e.shiftKey||e.button))e.preventDefault();dispatch(t)}});
document.addEventListener('keydown',e=>{
  if(e.key!=='Enter'&&e.key!==' ')return;
  const t=e.target.closest('[data-kb]');if(t&&t===e.target){e.preventDefault();dispatch(t)}});

/* Values that come from data (meter widths, colour swatches) are set through the DOM, which a CSP without inline CSS allows.
   Only the main screen is watched, and a burst of changes is applied once per frame. */
function applyDynamicStyles(root){
  root.querySelectorAll('[data-w]').forEach(el=>{el.style.width=Math.max(0,Math.min(100,+el.dataset.w||0))+'%'});
  root.querySelectorAll('[data-bg]').forEach(el=>{
    const ok=v=>/^#[0-9a-f]{3,8}$/i.test(v||'');
    if(ok(el.dataset.bg))el.style.background=el.dataset.bg})}
let paintQueued=false;
new MutationObserver(()=>{if(paintQueued)return;paintQueued=true;requestAnimationFrame(()=>{paintQueued=false;applyDynamicStyles($('#main'))})})
  .observe($('#main'),{childList:true,subtree:true});
boot();
