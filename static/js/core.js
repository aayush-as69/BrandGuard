/* API client, shared state and helpers, screen router */
let ME=null, USERS=[], TAB='content', CUR=null, DETAIL=null, KBDATA=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cls=s=>String(s??'').replace(/[^a-z_]/g,'');
const when=t=>{const d=new Date(t);return isNaN(d)?esc(t):esc(d.toLocaleString([],{dateStyle:'medium',timeStyle:'short'}))};
const label=s=>({in_review:'In review',changes_requested:'Changes requested',draft:'Draft',approved:'Approved',no_approved_source:'No approved source'}[s]||s);

async function api(path,opt={}){
  const o={credentials:'same-origin',...opt};
  if(o.json!==undefined){o.method=o.method||'POST';o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(o.json);delete o.json}
  const r=await fetch(path,o); const t=await r.text(); let d={}; try{d=JSON.parse(t)}catch(e){}
  if(r.status===401&&path!=='/api/login'&&path!=='/api/me'){signedOut('Your session ended. Pick a user to sign in again.')}
  if(!r.ok){const err=new Error(d.error||('Request failed ('+r.status+')'));err.data=d;throw err}
  return d;
}
function signedOut(msg){ME=null;CUR=null;DETAIL=null;$('#nav').classList.add('hidden');$('#who').value='';accountUI();
  landing(msg)}
function toast(msg,err){const t=$('#toast');t.setAttribute('role',err?'alert':'status');t.textContent=msg;t.className='toast'+(err?' err':'');clearTimeout(toast.h);toast.h=setTimeout(()=>t.className='toast hidden',4200)}
async function run(fn){try{await fn()}catch(e){toast(e.message,true)}}

let RID=0; // only the most recent render may draw, so a slow earlier request cannot overwrite a newer screen
function render(){
  const f=TAB==='kb'?renderKB:TAB==='insights'?renderInsights:TAB==='users'?renderUsers:renderContent;
  return Promise.resolve().then(f).catch(e=>{if(ME)$('#main').innerHTML='<div class="card" role="alert"><h2>Could not load this screen</h2><p class="muted">'+esc(e.message)+'</p><p><button class="btn" data-c="render">Try again</button></p></div>'})}

