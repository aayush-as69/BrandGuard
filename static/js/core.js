/* API client, shared state and helpers, dialogs, screen router */
let ME=null, USERS=[], TAB='content', CUR=null, DETAIL=null, KBDATA=null, SEL=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cls=s=>String(s??'').replace(/[^a-z_]/g,'');
const when=t=>{const d=new Date(t);return isNaN(d)?esc(t):esc(d.toLocaleString([],{dateStyle:'medium',timeStyle:'short'}))};
const label=s=>({in_review:'In review',changes_requested:'Changes requested',draft:'Draft',approved:'Approved',no_approved_source:'No approved source',
  open:'Needs a decision',accepted:'Fix accepted',edited:'Edited',dismissed:'Dismissed'}[s]||s);
const plural=(n,one,many)=>n+' '+(n===1?one:(many||one+'s'));

/* Severity is shown with a label and a shape as well as a colour. */
const SEV={high:['▲','High'],medium:['◆','Medium'],low:['●','Low']};
const sev=s=>{const k=cls(s),v=SEV[k]||['●',esc(s)];return `<span class="sev ${k}"><span aria-hidden="true">${v[0]}</span>${v[1]}</span>`};

/* WCAG contrast, so an image's colour pair can be shown as "measured" against "required". */
function lum(h){const m=/^#?([0-9a-f]{6})$/i.exec(h||'');if(!m)return null;
  const c=[0,2,4].map(i=>parseInt(m[1].slice(i,i+2),16)/255).map(v=>v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4));
  return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function ratio(a,b){const x=lum(a),y=lum(b);if(x==null||y==null)return null;return ((x>y?x:y)+.05)/((x>y?y:x)+.05)}

async function api(path,opt={}){
  const o={credentials:'same-origin',...opt};
  if(o.json!==undefined){o.method=o.method||'POST';o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(o.json);delete o.json}
  let r,t;
  try{r=await fetch(path,o);t=await r.text()}
  catch(e){const err=new Error('We could not reach BrandGuard. Check your connection and try again. Nothing was lost.');err.offline=true;throw err}
  let d={}; try{d=JSON.parse(t)}catch(e){}
  if(r.status===401&&path!=='/api/login'&&path!=='/api/me'){signedOut('Your session ended. Please sign in again.')}
  if(!r.ok){
    // Server errors never reach the screen as raw text; validation messages (4xx) are written for people.
    const msg=r.status>=500?'Something went wrong on our side. Your work is saved. Please try again in a moment.':(d.error||('That did not work ('+r.status+').'));
    const err=new Error(msg);err.data=d;throw err}
  return d;
}
function signedOut(msg){ME=null;CUR=null;DETAIL=null;SEL=null;LASTTAB=null;$('#nav').classList.add('hidden');$('#who').value='';accountUI();
  if(AUTH==='accounts'){history.replaceState({},'','/')}document.title='BrandGuard';landing(msg)}
function toast(msg,err){const t=$('#toast');t.setAttribute('role',err?'alert':'status');t.textContent=msg;t.className='toast'+(err?' err':'');
  clearTimeout(toast.h);toast.h=setTimeout(()=>t.className='toast hidden',err?8000:4200)}
async function run(fn){try{await fn()}catch(e){toast(e.message,true)}}

/* Shared screen states */
const skeleton=()=>`<div class="card" role="status"><span class="sr-only">Loading…</span><div class="skeleton" aria-hidden="true"><i class="w40"></i><i class="tall"></i><i></i><i class="w60"></i></div></div>`;
const errorCard=(title,msg,retry='render')=>`<div class="card empty-state" role="alert"><div class="empty-icon" aria-hidden="true">!</div><h2>${esc(title)}</h2><p class="muted">${esc(msg)}</p><button class="btn primary" type="button" data-c="${retry}">Try again</button></div>`;
const pageHead=(kicker,title,sub,extra='')=>`<div class="page-head"><div><div class="kicker">${esc(kicker)}</div><h1 id="page-title" tabindex="-1">${esc(title)}</h1><p>${esc(sub)}</p></div>${extra}</div>`;
const PAGE_NAMES={content:'Content',kb:'Knowledge base',insights:'Insights',users:'Users'};
function focusMain(){const h=$('#page-title');if(h)h.focus({preventScroll:true})}

let RID=0, LASTTAB=null; // only the most recent render may draw, so a slow earlier request cannot overwrite a newer screen
function render(){
  const f=TAB==='kb'?renderKB:TAB==='insights'?renderInsights:TAB==='users'?renderUsers:renderContent;
  // Show a skeleton when the person moves to another screen; refreshing the same screen never blanks it.
  if(LASTTAB!==TAB){$('#main').innerHTML=skeleton();LASTTAB=TAB}
  if(ME)document.title=(PAGE_NAMES[TAB]||'BrandGuard')+' · BrandGuard';
  return Promise.resolve().then(f).catch(e=>{if(ME)$('#main').innerHTML=errorCard('We couldn’t load this page',e.message)})}

/* In-page dialog (never the browser's prompt/confirm). onSubmit may throw: its message is shown inside the dialog, which stays open.
   Fields: {id,label,type:'text'|'password'|'textarea'|'select',options:[[value,label]],value,hint,ac,inputmode,optional}. */
function fieldHtml(f){
  const id='dlg-'+f.id,common=`id="${id}" aria-describedby="dlg-err${f.hint?' '+id+'-h':''}"`;
  const input=f.type==='textarea'?`<textarea ${common} rows="${f.rows||4}">${esc(f.value||'')}</textarea>`
    :f.type==='select'?`<select ${common}>${(f.options||[]).map(o=>`<option value="${esc(o[0])}"${o[0]===f.value?' selected':''}>${esc(o[1])}</option>`).join('')}</select>`
    :`<input ${common} type="${f.type||'text'}" value="${esc(f.value||'')}" autocomplete="${f.ac||'off'}"${f.inputmode?` inputmode="${f.inputmode}"`:''}>`;
  return `<label for="${id}">${esc(f.label)}</label>${input}${f.hint?`<span class="field-hint" id="${id}-h">${esc(f.hint)}</span>`:''}`}
function askDialog({title,note='',consequence='',secret='',fields=[],ok='Save',danger=false,onSubmit}){
  return new Promise(resolve=>{
    const opener=document.activeElement;
    const d=document.createElement('dialog');d.className='dlg';d.setAttribute('aria-labelledby','dlg-title');
    d.innerHTML=`<form class="dlg-f" novalidate><h2 id="dlg-title">${esc(title)}</h2>${note?`<p class="small muted">${esc(note)}</p>`:''}
      ${consequence?`<p class="dlg-consequence" role="note">${esc(consequence)}</p>`:''}
      ${secret?`<p class="dlg-secret"><code>${esc(secret)}</code><button type="button" class="btn" data-copy>Copy</button></p>`:''}
      ${fields.map(fieldHtml).join('')}
      <p class="dlg-err" id="dlg-err" role="alert"></p>
      <div class="row"><button class="btn" type="button" data-cancel>Cancel</button><button class="btn ${danger?'bad':'primary'}" type="submit">${esc(ok)}</button></div></form>`;
    document.body.appendChild(d);
    const err=d.querySelector('.dlg-err');
    d.addEventListener('close',()=>{const done=d.returnValue==='ok';d.remove();
      if(opener&&document.contains(opener)&&opener.focus)opener.focus();resolve(done)});
    d.querySelector('[data-cancel]').onclick=()=>d.close('cancel');
    const cp=d.querySelector('[data-copy]');
    if(cp)cp.onclick=async()=>{try{await navigator.clipboard.writeText(secret);cp.textContent='Copied'}catch(e){cp.textContent='Select and copy'}};
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();err.textContent='';
      const v={};for(const f of fields)v[f.id]=d.querySelector('#dlg-'+f.id).value;
      const missing=fields.find(f=>!f.optional&&!v[f.id].trim());
      d.querySelectorAll('[aria-invalid]').forEach(x=>x.removeAttribute('aria-invalid'));
      if(missing){const el=d.querySelector('#dlg-'+missing.id);el.setAttribute('aria-invalid','true');err.textContent=fields.length>1?'Fill in '+missing.label.toLowerCase()+'.':'This cannot be empty.';el.focus();return}
      const b=d.querySelector('[type=submit]');b.disabled=true;b.setAttribute('aria-busy','true');
      try{if(onSubmit)await onSubmit(v);d.close('ok')}catch(ex){err.textContent=ex.message}finally{b.disabled=false;b.removeAttribute('aria-busy')}};
    d.showModal();
    const first=d.querySelector('input,textarea,select')||d.querySelector(danger?'[data-cancel]':'[type=submit]');if(first)first.focus()})}
const confirmDialog=o=>askDialog({fields:[],ok:'Confirm',...o});
