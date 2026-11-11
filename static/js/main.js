/* Click and key dispatch (no inline handlers, so the CSP can forbid inline script), then start */
/* One delegated listener replaces inline handlers, so the page can run under a CSP with no inline script. */
const ACTIONS={render,moreContent,tourStart,tourStep,tourDo,tourClose,act,addImgRow,comment,createContent,decide,decideDismiss,decideEdit,doImport,kbDel,kbEdit,loadDemo,openContent,removeRow,reqChanges,revise,seed,showNew,toggle};
function dispatch(t){
  const fn=ACTIONS[t.dataset.c];if(!fn)return;
  let args=[];try{args=t.dataset.a?JSON.parse(t.dataset.a):[]}catch(e){}
  fn(...(ELEMENT_ACTIONS.has(t.dataset.c)?[t]:args))}
const ELEMENT_ACTIONS=new Set(['removeRow','kbEdit','kbDel']);
document.addEventListener('click',e=>{const t=e.target.closest('[data-c]');if(t)dispatch(t)});
document.addEventListener('keydown',e=>{
  if(e.key!=='Enter'&&e.key!==' ')return;
  const t=e.target.closest('[data-kb]');if(t&&t===e.target){e.preventDefault();dispatch(t)}});


/* Values that come from data (meter widths, colour swatches) are set through the DOM, which a CSP without inline CSS allows. */
function applyDynamicStyles(root){
  root.querySelectorAll('[data-w]').forEach(el=>{el.style.width=Math.max(0,Math.min(100,+el.dataset.w||0))+'%'});
  root.querySelectorAll('[data-bg]').forEach(el=>{
    const ok=v=>/^#[0-9a-f]{3,8}$/i.test(v||'');
    if(ok(el.dataset.bg))el.style.background=el.dataset.bg;if(ok(el.dataset.fg))el.style.color=el.dataset.fg})}
new MutationObserver(()=>applyDynamicStyles(document.body)).observe(document.body,{childList:true,subtree:true});
boot();
