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


boot();
