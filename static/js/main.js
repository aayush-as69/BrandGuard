/* Click and key dispatch (no inline handlers, so the CSP can forbid inline script), then start */
/* One delegated listener replaces inline handlers, so the page can run under a CSP with no inline script. */
const ACTIONS={searchOpen,searchClose,searchRun,render,focusSignin,demoLogin,demoFill,jump,goLogin,goHome,moreContent,tourStart,tourStep,tourDo,tourClose,act,addImgRow,comment,createContent,decide,decideDismiss,decideEdit,doImport,kbDel,kbEdit,loadDemo,openContent,removeRow,reqChanges,revise,seed,showNew,toggle,qualityRun,qualityApply,qualityUndo,rewriteOpen,rewriteUse,sampleBanner};
function dispatch(t){
  const fn=ACTIONS[t.dataset.c];if(!fn)return;
  let args=[];try{args=t.dataset.a?JSON.parse(t.dataset.a):[]}catch(e){}
  fn(...(ELEMENT_ACTIONS.has(t.dataset.c)?[t]:args))}
const ELEMENT_ACTIONS=new Set(['removeRow','kbEdit','kbDel']);
document.addEventListener('click',e=>{const t=e.target.closest('[data-c]');
  if(t){if(t.tagName==='A'&&!(e.metaKey||e.ctrlKey||e.shiftKey||e.button))e.preventDefault();dispatch(t)}});
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


async function searchOpen(){
  if(!ME)return;
  const m=$('#search-modal');m.classList.remove('hidden');const i=$('#search-input');i.value='';$('#search-results').innerHTML='<p class="muted">Type at least two characters.</p>';i.focus();
}
function searchClose(){$('#search-modal')?.classList.add('hidden')}
async function searchRun(){
  const q=$('#search-input').value.trim();const box=$('#search-results');
  if(q.length<2){box.innerHTML='<p class="muted">Type at least two characters.</p>';return}
  box.innerHTML='<p class="muted">Searching…</p>';
  try{
    const d=await api('/api/search?q='+encodeURIComponent(q));
    if(!d.results.length){box.innerHTML='<p class="muted">No matches.</p>';return}
    box.innerHTML=d.results.map(r=>'<button class="card search-result" type="button" data-c="searchResult" data-a='+esc(JSON.stringify([r.kind,r.id]))+'><div><span class="section-kicker">'+esc(r.kind.toUpperCase())+'</span><h3>'+esc(r.title)+'</h3><p class="small muted">'+esc(r.snippet||r.status||'')+'</p></div></button>').join('');
  }catch(e){box.innerHTML='<p class="muted">'+esc(e.message)+'</p>'}
}
async function searchResult(kind,id){
  searchClose();
  if(kind==='content'){TAB='content';await render();return openContent(+id)}
  if(kind==='rule'||kind==='fact'){TAB='kb';await render()}
}
document.addEventListener('input',e=>{if(e.target?.id==='search-input'){clearTimeout(searchRun.t);searchRun.t=setTimeout(searchRun,180)}});
document.addEventListener('keydown',e=>{if(e.key==='Escape')searchClose();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();searchOpen()}});
