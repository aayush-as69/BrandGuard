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
  if(!r.ok) throw new Error(d.error||('Request failed ('+r.status+')'));
  return d;
}
function signedOut(msg){ME=null;CUR=null;DETAIL=null;$('#nav').classList.add('hidden');$('#who').value='';accountUI();
  $('#main').innerHTML='<p class="muted">'+esc(msg)+'</p>'}
function toast(msg,err){const t=$('#toast');t.setAttribute('role',err?'alert':'status');t.textContent=msg;t.className='toast'+(err?' err':'');clearTimeout(toast.h);toast.h=setTimeout(()=>t.className='toast hidden',4200)}
async function run(fn){try{await fn()}catch(e){toast(e.message,true)}}

async function boot(){
  try{const cfg=await api('/api/config');AUTH=cfg.auth||'demo';AICFG=cfg.ai||AICFG;$('#pass').classList.toggle('hidden',!cfg.passcode_required)}catch(e){}
  if(AUTH==='accounts'){
    document.querySelectorAll('.tour-only').forEach(x=>x.classList.add('hidden'));
    $('#main').innerHTML='<div class="card"><h2>Welcome to BrandGuard</h2><p class="muted">Sign in with your work email to continue.</p></div>';
    try{ME=await api('/api/me');afterLogin()}catch(e){accountUI()}
    return}
  USERS=await api('/api/users');
  $('#who').innerHTML='<option value="">Choose…</option>'+USERS.map(u=>`<option value="${u.id}">${esc(u.name)} · ${u.role}${u.is_external?' (agency)':''}</option>`).join('');
  try{ME=await api('/api/me');$('#who').value=ME.id;afterLogin()}catch(e){}
}
$('#who').onchange=e=>run(async()=>{
  if(!e.target.value){await api('/api/logout',{json:{}});signedOut('Signed out. Pick a user to begin.');return}
  const prev=ME?ME.id:'';
  try{ME=await api('/api/login',{json:{user_id:+e.target.value,passcode:$('#pass').value}})}
  catch(err){e.target.value=prev;throw err}
  CUR=null;DETAIL=null;KBDATA=null;afterLogin()
});
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>{TAB=b.dataset.tab;
  document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x===b));render()});
function afterLogin(){
  $('#nav').classList.remove('hidden');
  // Agency users cannot browse brand material, so they get no Knowledge base tab.
  document.querySelector('#nav [data-tab=kb]').classList.toggle('hidden',!!ME.is_external);
  // Insights are about the guidelines, for the people who own them (not for authors).
  const noInsights=ME.role==='creator';
  document.querySelector('#nav [data-tab=insights]').classList.toggle('hidden',noInsights);
  if((ME.is_external&&TAB==='kb')||(noInsights&&TAB==='insights')||(TAB==='users'&&ME.role!=='admin'))TAB='content';
  document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x.dataset.tab===TAB));
  accountUI();return render()}
let AUTH='demo',AICFG={enabled:false};
const aiBox=id=>AICFG.enabled?`<label class="small" style="display:block;margin-top:8px"><input type="checkbox" id="${id}" checked> Use AI to judge tone <span class="muted">(sends this text to ${esc(AICFG.provider||'the AI provider')})</span></label><p class="small muted">${esc(AICFG.notice||'')}</p>`:'';
const useAI=id=>{const b=document.getElementById(id);return b?b.checked:true};
function accountUI(){
  const real=AUTH==='accounts';
  $('#who').classList.toggle('hidden',real);document.querySelector('label[for=who]').classList.toggle('hidden',real);
  $('#signin').classList.toggle('hidden',!(real&&!ME));$('#acct').classList.toggle('hidden',!(real&&ME));
  if(real&&ME)$('#acct-name').textContent=ME.name+' · '+ME.role+(ME.is_external?' (agency)':'');
  document.querySelector('#nav [data-tab=users]').classList.toggle('hidden',!(real&&ME&&ME.role==='admin'));
  $('#main').querySelectorAll('[data-tour-only]').forEach(x=>x.classList.toggle('hidden',real));
}
$('#signin').onsubmit=e=>{e.preventDefault();run(async()=>{
  ME=await api('/api/login',{json:{email:$('#email').value,password:$('#password').value}});
  $('#password').value='';CUR=null;DETAIL=null;KBDATA=null;afterLogin()})};
$('#signout').onclick=()=>run(async()=>{await api('/api/logout',{json:{}});signedOut('Signed out.')});
$('#chpw').onclick=()=>run(async()=>{
  const cur=prompt('Current password');if(cur===null)return;
  const nw=prompt('New password (at least 10 characters)');if(nw===null)return;
  await api('/api/password',{json:{current:cur,new:nw}});toast('Password changed. Other devices were signed out.')});
async function renderUsers(){
  const rid=++RID;const list=await api('/api/users');if(rid!==RID)return;
  $('#main').innerHTML='<div class="card"><h2>Users</h2><p class="small muted">Accounts for your team and agencies. Deactivating an account or changing its password signs that person out at once.</p>'+
   '<table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>'+
   list.map(u=>`<tr><td>${esc(u.name)}${u.is_external?' <span class="small muted">(agency)</span>':''}</td><td>${esc(u.email||'')}</td><td>${esc(u.role)}</td><td>${u.active?'Active':'Deactivated'}</td>`+
    `<td><button class="btn" data-uact="toggle" data-uid="${u.id}" data-on="${u.active?1:0}">${u.active?'Deactivate':'Reactivate'}</button> `+
    `<button class="btn" data-uact="role" data-uid="${u.id}">Change role</button> <button class="btn" data-uact="pw" data-uid="${u.id}">Reset password</button></td></tr>`).join('')+
   '</tbody></table></div><div class="card"><h3>Add a user</h3><form id="newuser" class="row">'+
   '<input name="name" placeholder="Name" aria-label="Name" required><input name="email" type="email" placeholder="Email" aria-label="Email" required>'+
   '<select name="role" aria-label="Role"><option>creator</option><option>manager</option><option>reviewer</option><option>admin</option></select>'+
   '<label class="small"><input type="checkbox" name="ext" aria-label="Agency (external)"> Agency (external)</label>'+
   '<input name="password" type="password" placeholder="Temporary password (10+ chars)" aria-label="Temporary password" required minlength="10">'+
   '<button class="btn primary" type="submit">Add</button></form></div>';
  $('#newuser').onsubmit=e=>{e.preventDefault();const f=e.target;run(async()=>{
    await api('/api/users',{json:{name:f.name.value,email:f.email.value,role:f.role.value,is_external:f.ext.checked,password:f.password.value}});
    toast('User added.');renderUsers()})};
  $('#main').querySelectorAll('[data-uact]').forEach(b=>b.onclick=()=>run(async()=>{
    const id=b.dataset.uid,a=b.dataset.uact;
    if(a==='toggle')await api('/api/users/'+id,{method:'PATCH',json:{active:b.dataset.on!=='1'}});
    else if(a==='role'){const r=prompt('New role: creator, manager, reviewer or admin');if(!r)return;await api('/api/users/'+id,{method:'PATCH',json:{role:r.trim()}})}
    else{const p=prompt('New password (at least 10 characters)');if(!p)return;await api('/api/users/'+id,{method:'PATCH',json:{password:p}})}
    toast('Saved.');renderUsers()}))}
let RID=0; // only the most recent render may draw, so a slow earlier request cannot overwrite a newer screen
function render(){
  const f=TAB==='kb'?renderKB:TAB==='insights'?renderInsights:TAB==='users'?renderUsers:renderContent;
  return Promise.resolve().then(f).catch(e=>{if(ME)$('#main').innerHTML='<div class="card" role="alert"><h2>Could not load this screen</h2><p class="muted">'+esc(e.message)+'</p><p><button class="btn" data-c="render">Try again</button></p></div>'})}

/* ------------------------------------------------------------ guided tour */
const TOUR=[
 {h:'The idea',t:'BrandGuard checks content against your approved guidelines and facts, shows exactly which rule each problem breaks, and leaves every decision to a person. This tour takes about two minutes.'},
 {h:'1. The brand team loads its rules',t:'The admin imports guidelines, approved facts and a glossary. Press the button to sign in as Ira (admin) and load the synthetic Brewline Coffee knowledge base. If a passcode is required, type the admin passcode first.',who:4,act:async()=>{await tourAs(4);await api('/api/kb/seed',{json:{}});TAB='kb';afterLogin();toast('Demo knowledge base loaded.')}},
 {h:'2. An agency writer drafts an email',t:'Neha works at an outside agency. She sees only her own content and cannot browse confidential facts. Press the button to sign in as Neha and fill in a demo email that has deliberate mistakes. Then press Review now.',who:1,act:async()=>{await tourAs(1);TAB='content';await afterLogin();showNew();await loadDemo()}},
 {h:'3. Every finding cites its source',t:'Each highlight names the guideline or fact it breaks, quotes it, and shows a suggested fix. Nothing changes until a person clicks Accept fix, Edit or Dismiss (a reason is required). Prices, dates and rankings are checked against the approved facts; the claim check lists what is supported, contradicted or has no source.'},
 {h:'4. Decide, then submit',t:'Accept or edit the fixes, then press Submit for approval. Submitting needs every finding decided, so nothing is silently ignored. The launch date is embargoed, so Neha sees that it conflicts but not the approved date (🔒): she rewrites around it, or the brand team applies the fix.'},
 {h:'5. A manager approves',t:'Approval needs a manager or reviewer who is not the author. Press the button to sign in as Arjun (manager), open the content and approve or request changes. Approved content is locked, and every step is in the audit trail.',who:2,act:async()=>{await tourAs(2);TAB='content';afterLogin()}},
 {h:'6. The guidelines improve',t:'Insights show which rules authors repeatedly break and which ones people keep dismissing, so the brand team can fix unclear rules.',who:2,act:async()=>{await tourAs(2);TAB='insights';afterLogin()}},
];
let TI=0;
async function tourAs(id){if(ME&&ME.id===id)return;
  ME=await api('/api/login',{json:{user_id:id,passcode:$('#pass').value}});$('#who').value=id;CUR=null;DETAIL=null;KBDATA=null}
function tourStart(){TI=0;tourShow()}
function tourClose(){$('#tour').classList.add('hidden');document.body.style.paddingBottom=''}
function tourStep(d){TI=Math.max(0,Math.min(TOUR.length-1,TI+d));tourShow()}
function tourShow(){const st=TOUR[TI];$('#tour').classList.remove('hidden');
  $('#tour-n').textContent='Step '+(TI+1)+' of '+TOUR.length;$('#tour-h').textContent=st.h;$('#tour-t').textContent=st.t;
  $('#tour-b').disabled=TI===0;$('#tour-nx').disabled=TI===TOUR.length-1;$('#tour-do').classList.toggle('hidden',!st.act);
  // keep the page scrollable past the panel, so it never hides a button the person needs to press
  document.body.style.paddingBottom=($('#tour').offsetHeight+24)+'px'}
function tourDo(){run(async()=>{const b=$('#tour-do');b.disabled=true;try{await TOUR[TI].act()}finally{b.disabled=false}})}

/* ------------------------------------------------------------ insights */
async function renderInsights(){
  const rid=++RID;let d;
  try{d=await api('/api/insights')}catch(e){if(rid!==RID)return;$('#main').innerHTML=`<div class="card"><h2>Insights</h2><p class="muted">${esc(e.message)}</p></div>`;return}
  if(rid!==RID)return;
  const c=d.content,top=Math.max(1,...d.rules.map(r=>r.flagged));
  const tile=(n,l)=>`<div class="tile"><b>${esc(n)}</b><span class="muted small">${esc(l)}</span></div>`;
  const disputed=d.rules.filter(r=>r.often_disputed);
  $('#main').innerHTML=`<div class="stack">
   <div class="card"><h2>Guideline insights</h2>
    <p class="muted small">What authors trip over and which rules people dispute, counted from real decisions. It never names a person.</p>
    <div class="tiles">${tile(c.total,'pieces of content')}${tile(c.approved,'approved')}${tile(c.in_review,'waiting for review')}
     ${tile(d.changes_requested,'changes requested')}${tile(d.avg_hours_to_approve==null?'n/a':d.avg_hours_to_approve+' h','average time to approval')}</div></div>
   <div class="card"><h2>Repeated mistakes</h2>
    <p class="muted small">How often each rule or fact flagged a first draft. Rules that keep repeating may need clearer wording or training.</p>
    ${d.rules.length?`<table>${d.rules.map(r=>`<tr><td><code>${esc(r.code)}</code></td><td><b>${esc(r.title)}</b></td>
      <td style="width:35%"><div class="meter" role="img" aria-label="${r.flagged} flags"><i style="width:${Math.round(100*r.flagged/top)}%"></i></div></td>
      <td>${r.flagged}</td></tr>`).join('')}</table>`:'<p class="muted small">No findings yet. Review some content first.</p>'}</div>
   <div class="card"><h2>Often disputed</h2>
    <p class="muted small">Rules where at least half of the decisions were dismissals (with at least 2 decisions). Dismissing is allowed, but a pattern suggests the rule is unclear, outdated or too strict.</p>
    ${disputed.length?disputed.map(r=>`<div class="item" style="cursor:default"><p><code>${esc(r.code)}</code> <b>${esc(r.title)}</b>
       <span class="chip medium">${Math.round(r.dismissal_rate*100)}% dismissed</span></p>
       <p class="small muted">${r.dismissed} dismissed, ${r.fixed} fixed. Rule text: ${esc(r.quote)}</p></div>`).join('')
     :'<p class="muted small">Nothing is being disputed often. Either the rules are clear, or there is not enough data yet.</p>'}</div>
   <div class="card"><h2>AI suggestions</h2>
    <p class="small">${d.ai.suggested?`${d.ai.suggested} decided: ${d.ai.accepted} accepted or edited, ${d.ai.dismissed} dismissed.`:'No AI suggestions have been decided yet.'}</p></div></div>`}

/* ------------------------------------------------------------ content list + detail */
let LISTN=50;
function moreContent(){LISTN+=50;render()}
async function renderContent(){
  const rid=++RID;
  const list=await api('/api/content?limit='+LISTN);
  if(rid!==RID)return;
  $('#main').innerHTML=`<div class="grid"><div class="stack">
    <div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Content</h2>
      <button class="btn primary" data-c="showNew">New</button></div><div style="margin-top:12px" id="list">
      ${list.length?list.map(c=>`<div class="item ${c.id===CUR?'on':''}" tabindex="0" role="button" data-kb="1" data-c="openContent" data-a='[${c.id}]'>
        <b>${esc(c.title)}</b><span class="small muted">${esc(c.author)} · v${c.current_version}</span><br>
        <span class="chip ${cls(c.status)}">${label(c.status)}</span>
        ${c.open_findings?`<span class="chip high">${c.open_findings} open</span>`:`<span class="chip approved">${c.total_findings?'all decided':'clean'}</span>`}
      </div>`).join(''):'<p class="muted small">Nothing yet. Choose New to submit a draft for review.</p>'}${list.length>=LISTN?'<p><button class="btn small" data-c="moreContent">Show more</button></p>':''}</div></div></div>
    <div id="detail">${CUR?'':'<div class="card muted">Select content, or create new content to see findings with cited sources.</div>'}</div></div>`;
  if(CUR) await loadDetail(CUR,rid);
}
async function openContent(id){CUR=id;await renderContent()}

function imgRow(i={}){return `<div class="imgrow">
  <input type="text" placeholder="file name" aria-label="Image file name" value="${esc(i.name||'')}" data-k="name">
  <input type="text" placeholder="alt text" aria-label="Image alt text" value="${esc(i.alt||'')}" data-k="alt">
  <input type="text" placeholder="text colour #RRGGBB" aria-label="Text colour on the image" value="${esc(i.text_color||'')}" data-k="text_color">
  <input type="text" placeholder="background #RRGGBB" aria-label="Background colour behind the text" value="${esc(i.bg_color||'')}" data-k="bg_color">
  <button class="btn" type="button" aria-label="Remove this image" data-c="removeRow">×</button></div>`}
function readImgs(){return [...document.querySelectorAll('#imgs .imgrow')].map(r=>{const o={};r.querySelectorAll('input').forEach(i=>o[i.dataset.k]=i.value);return o}).filter(o=>o.name)}
function showNew(){
  CUR=null;DETAIL=null;
  $('#detail').innerHTML=`<div class="card stack"><h2>Submit content for review</h2>
   <div><label class="small muted" for="nt">Title</label><input type="text" id="nt" maxlength="200"></div>
   <div><label class="small muted" for="nb">Text (paste an email, post or page)</label><textarea id="nb" rows="12" maxlength="50000"></textarea></div>
   <div><label class="small muted">Images (checked for alt text and text contrast)</label><div id="imgs"></div>
     <button class="btn small" type="button" data-c="addImgRow">Add image</button></div>
   ${aiBox('nai')}
   <div class="row"><button class="btn primary" data-c="createContent">Review now</button>
     <button class="btn" data-c="loadDemo">Load demo email</button></div></div>`;
}
async function loadDemo(){run(async()=>{const d=await api('/api/demo');$('#nt').value=d.title;$('#nb').value=d.body;
  $('#imgs').innerHTML=d.images.map(imgRow).join('')})}
async function createContent(){run(async()=>{
  const r=await api('/api/content',{json:{title:$('#nt').value,body:$('#nb').value,images:readImgs(),use_ai:useAI('nai')}});
  CUR=r.id;toast('Reviewed. Findings are listed with their sources.');await renderContent()})}

async function loadDetail(id,rid){
  const fresh=await api('/api/content/'+id);
  if(rid!==undefined&&rid!==RID)return;
  DETAIL=fresh;
  const d=DETAIL,c=d.content,p=d.permissions,open=d.findings.filter(f=>f.decision==='open').length;
  const meta=d.review_meta||{};
  $('#detail').innerHTML=`<div class="stack">
   <div class="card"><div class="row" style="justify-content:space-between">
     <div><h2 style="margin:0;font-size:18px">${esc(c.title)}</h2>
       <span class="small muted">by ${esc(c.author)} · version ${c.current_version}</span></div>
     <div class="row"><span class="chip ${cls(c.status)}">${label(c.status)}</span>
       ${p.can_submit?`<button class="btn primary" data-c="act" data-a='["submit"]'>Submit for approval</button>`:''}
       ${p.can_approve?`<button class="btn good" data-c="act" data-a='["approve"]'>Approve</button>`:''}
       ${p.can_request_changes?`<button class="btn warn" data-c="reqChanges">Request changes</button>`:''}
       ${p.can_rerun&&c.status!=='approved'?`<button class="btn" data-c="act" data-a='["review"]'>Re-run review</button>`:''}
       <a class="btn" style="text-decoration:none;color:inherit" href="/api/content/${+c.id}/record" target="_blank" rel="noopener">Approval record</a></div></div>
     <p class="small muted" style="margin:8px 0 0">${c.status==='approved'
       ?`Approved${c.approved_by?' by '+esc(c.approved_by):''}. This version is locked.`
       :`${open?`${open} finding${open>1?'s':''} still need a decision.`:(d.findings.length?'Every finding has a decision.':'No findings.')} Nothing is applied until a person clicks.`}</p>
     ${(meta.warnings||[]).map(w=>`<p class="small" style="color:var(--amber);margin:6px 0 0">⚠ ${esc(w)}</p>`).join('')}
     <p class="small muted" style="margin:6px 0 0">AI judge: ${esc(meta.llm_status||'not used')}${(meta.rejected||[]).length?` · ${(meta.rejected).length} unverifiable suggestion(s) discarded`:''}</p></div>
   <div class="grid2">
     <div class="stack"><div class="card"><h3>Content</h3>
        <div class="body" id="body">${highlight(d)}</div>
        ${d.images.length?`<h3 style="margin-top:14px">Images</h3><table>${d.images.map(i=>`<tr><td><b>${esc(i.name)}</b></td>
          <td>alt: ${i.alt?esc(i.alt):'<span class="st-contradicted">missing</span>'}</td>
          <td>${i.text_color&&i.bg_color?`<span style="background:${esc(i.bg_color)};color:${esc(i.text_color)};padding:1px 8px;border-radius:4px">Aa</span> ${esc(i.text_color)} on ${esc(i.bg_color)}`:''}</td></tr>`).join('')}</table>`:''}
        ${p.can_revise?`<details style="margin-top:12px"><summary>Edit the text myself</summary>
          <textarea id="rb" rows="8" aria-label="Edit the content text" style="margin:8px 0">${esc(d.body)}</textarea>
          ${aiBox('rai')}<button class="btn" data-c="revise">Save as new version</button></details>`:''}</div>
        <div class="card"><h3>Claim check</h3>${d.claims.length?groupClaims(d.claims).map(g=>`<div class="claim">
          <div class="small">${esc(g.text)}</div><div class="tags">${g.tags.map(t=>`<span class="st-${cls(t.status)}">${label(t.status)}${t.source_id?' · '+esc(t.source_id):''}</span>`).join('')}</div></div>`).join('')
          :'<p class="small muted">No promotional claims detected.</p>'}
          <p class="small muted" style="margin:8px 0 0">Claims are matched to approved facts. “No approved source” is never filled in by guessing.</p></div>
        <div class="card"><h3>Discussion</h3>${d.comments.map(m=>`<div class="cmt"><b>${esc(m.author)}</b> <span class="chip">${esc(m.role)}</span>
          <span class="small muted">${when(m.created_at)}</span><br>${esc(m.body)}</div>`).join('')||'<p class="small muted">No comments yet.</p>'}
          <div class="row" style="margin-top:10px"><input type="text" id="cm" placeholder="Add a comment…" aria-label="Add a comment" maxlength="2000"><button class="btn" data-c="comment">Post</button></div></div>
        <div class="card"><h3>Versions</h3>${d.versions.map(v=>`<div class="small"><b>v${v.version}</b> ${esc(v.author)} · ${esc(v.note)} <span class="muted">${when(v.created_at)}</span></div>`).join('')}
          ${d.audit.length?`<details style="margin-top:10px"><summary>Audit log (${d.audit.length})</summary>${d.audit.map(a=>`<div class="small muted">${when(a.created_at)} · ${esc(a.who||'system')} · <b>${esc(a.action)}</b> ${esc(a.detail)}</div>`).join('')}</details>`:''}</div></div>
     <div class="card"><h3>Findings (${d.findings.length})</h3>
        ${d.findings.map(f=>findingCard(f,p,c)).join('')||'<p class="muted small">Nothing to fix in this version.</p>'}
        ${d.history.length?`<details><summary>Resolved in earlier versions (${d.history.length})</summary>${d.history.map(h=>`<div class="small" style="padding:6px 0">
          <b>${esc(h.source_id)}</b> ${esc(h.span_text)} → <b>${esc(h.decision_text)}</b> <span class="muted">${esc(h.decision)} by ${esc(h.decided_by_name||'')}</span></div>`).join('')}</details>`:''}</div>
   </div></div>`;
}
function groupClaims(claims){ // one row per sentence, with every status found in it
  const map=new Map();
  for(const c of claims){ if(!map.has(c.text))map.set(c.text,{text:c.text,tags:[]});
    const g=map.get(c.text); if(!g.tags.some(t=>t.status===c.status&&t.source_id===c.source_id))g.tags.push(c) }
  return [...map.values()];
}
function highlight(d){
  const spans=d.findings.filter(f=>f.target==='body'&&f.span_start>=0&&f.decision==='open').sort((a,b)=>a.span_start-b.span_start);
  // The server counts characters (code points); JavaScript strings count UTF-16 units, so an emoji
  // would shift every highlight after it. Slice by code point instead.
  const chars=Array.from(d.body),sl=(a,b)=>chars.slice(a,b).join('');
  let out='',pos=0;
  for(const f of spans){ if(f.span_start<pos)continue;
    out+=esc(sl(pos,f.span_start))+`<mark class="${cls(f.severity)}" tabindex="0" role="button" data-kb="1" data-c="jump" data-a='[${f.id}]' title="${esc(f.issue)}">${esc(sl(f.span_start,f.span_end))}</mark>`;pos=f.span_end}
  return out+esc(sl(pos));
}
function jump(id){const el=document.getElementById('f'+id);if(!el)return;el.scrollIntoView({behavior:'smooth',block:'center'});
  el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),1400)}
function findingCard(f,p,c){
  const done=f.decision!=='open', fix=f.suggested_fix;
  const diff=f.target==='body'
    ? `<div class="diff"><del>${esc(f.span_text)}</del>${fix?` → <ins>${esc(fix)}</ins>`:' → <span class="muted">(no automatic suggestion)</span>'}</div>`
    : (fix?`<div class="diff"><ins>${esc(fix)}</ins> <span class="muted">${esc(f.fix_note)}</span></div>`:`<div class="small muted">${esc(f.fix_note)}</div>`);
  return `<div class="finding ${cls(f.severity)} ${done?'done':''}" id="f${f.id}">
    <div class="row"><span class="chip">${esc(f.category)}</span><span class="chip ${cls(f.severity)}">${esc(f.severity)} severity</span>
      <span class="chip">${esc(f.confidence)} confidence</span>${f.ai_generated?'<span class="chip ai">AI-generated</span>':''}
      ${f.needs_reviewer?'<span class="chip high">needs reviewer</span>':''}${f.restricted?'<span class="chip draft" title="Only the brand team can see this fact">🔒 restricted fact</span>':''}</div>
    <p style="margin:8px 0 4px"><b>${esc(f.issue)}</b></p>
    <div class="quote"><b>${f.source_type==='fact'?'Approved fact':'Guideline'} ${esc(f.source_id)}:</b> ${esc(f.source_quote)}</div>
    ${f.target==='body'?'<div class="small muted">Flagged text</div>':''}${diff}
    ${done?`<p class="small" style="margin:6px 0 0"><b>${esc(f.decision)}</b> by ${esc(f.decided_by_name||'')}${f.decision_reason?': '+esc(f.decision_reason):''}</p>`
    :(p.can_decide?`<div class="row" style="margin-top:8px">
        <button class="btn good" ${fix?'':`disabled title="${f.restricted?'Restricted fact: ask the brand team, or use Edit.':'No suggested fix. Use Edit.'}"`} data-c="decide" data-a='[${f.id},"accept"]'>Accept fix</button>
        <button class="btn" data-c="toggle" data-a='["e${f.id}"]'>Edit</button>
        <button class="btn bad" data-c="toggle" data-a='["d${f.id}"]'>Dismiss</button></div>
      <div id="e${f.id}" class="hidden row" style="margin-top:8px"><input type="text" id="et${f.id}" aria-label="Replacement text" value="${esc(fix||(f.target==='body'?f.span_text:''))}" style="flex:1">
        <button class="btn primary" data-c="decideEdit" data-a='[${f.id}]'>Apply my edit</button></div>
      <div id="d${f.id}" class="hidden row" style="margin-top:8px"><input type="text" id="dr${f.id}" placeholder="Reason (required)" aria-label="Reason for dismissing" maxlength="500" style="flex:1">
        <button class="btn bad" data-c="decideDismiss" data-a='[${f.id}]'>Dismiss with reason</button></div>`:'')}
  </div>`;
}
const toggle=id=>document.getElementById(id).classList.toggle('hidden');
function removeRow(el){el.parentElement.remove()}
function addImgRow(){document.getElementById('imgs').insertAdjacentHTML('beforeend',imgRow())}
function decideEdit(id){decide(id,'edit',document.getElementById('et'+id).value)}
function decideDismiss(id){decide(id,'dismiss',null,document.getElementById('dr'+id).value)}
function decide(id,action,text,reason){run(async()=>{
  const r=await api('/api/findings/'+id+'/decide',{json:{action,text,reason}});
  toast(action==='dismiss'?'Dismissed.':'Applied as version '+r.new_version+'. Content was re-reviewed.');await renderContent()})}
const act=(a)=>run(async()=>{await api('/api/content/'+CUR+'/'+a,{method:'POST',json:{}});
  toast({submit:'Submitted for approval.',approve:'Approved. This version is now locked.',review:'Review re-run.'}[a]);await renderContent()});
const reqChanges=()=>{const note=prompt('What needs to change?');if(note)run(async()=>{await api('/api/content/'+CUR+'/request-changes',{json:{note}});toast('Changes requested.');await renderContent()})};
const comment=()=>run(async()=>{const b=$('#cm').value;await api('/api/content/'+CUR+'/comments',{json:{body:b}});await renderContent()});
const revise=()=>run(async()=>{await api('/api/content/'+CUR+'/revise',{json:{body:$('#rb').value,images:DETAIL.images,use_ai:useAI('rai')}});
  toast('Saved as a new version and re-reviewed.');await renderContent()});

/* ------------------------------------------------------------------ knowledge base */
async function renderKB(){
  const rid=++RID;
  let k;
  try{k=await api('/api/kb')}catch(e){if(rid!==RID)return;$('#main').innerHTML=`<div class="card"><h2>Knowledge base</h2><p class="muted">${esc(e.message)}</p></div>`;return}
  if(rid!==RID)return;
  KBDATA=k;
  const admin=ME.role==='admin';
  $('#main').innerHTML=`<div class="stack">
   ${admin?`<div class="card stack"><h2>Import (admin)</h2>
     <div class="row"><button class="btn primary" data-c="seed">Load Brewline demo knowledge base</button>
       <span class="small muted">Replaces the current knowledge base with synthetic demo data.</span></div>
     <div class="row"><select id="ik" aria-label="What to import" style="width:auto"><option value="guidelines">Guidelines (PDF, DOCX, TXT, MD)</option>
        <option value="facts">Approved facts (JSON)</option><option value="glossary">Glossary (JSON)</option>
        <option value="assets">Asset list (JSON)</option></select>
       <select id="il" aria-label="Access level" style="width:auto"><option>internal</option><option>confidential</option><option>public</option></select>
       <input type="file" id="ifile" aria-label="File to import"></div>
     <textarea id="itext" rows="3" aria-label="Pasted text or JSON" placeholder="…or paste text / JSON here"></textarea>
     <div><button class="btn" data-c="doImport">Import</button></div></div>`:''}
   <div class="card"><h2>Guidelines</h2>${k.guidelines.map(g=>`<p><b>${esc(g.title)}</b> <span class="chip">${esc(g.access_level)}</span></p>
     <table>${g.rules.map(r=>`<tr><td><code>${esc(r.code)}</code></td><td><b>${esc(r.title)}</b><div>${esc(r.text)}</div></td>${admin?`<td class="nowrap">${kbBtns('rules',r.code)}</td>`:''}</tr>`).join('')}</table>`).join('')||'<p class="muted small">None visible to you.</p>'}</div>
   <div class="card"><h2>Approved facts</h2>${k.facts.length?`<table>${k.facts.map(f=>`<tr><td><code>${esc(f.code)}</code></td><td>${esc(f.kind)}</td><td>${esc(f.statement)}<div class="muted small">${esc(f.source)} · ${esc(f.access_level)}</div></td>${admin?`<td class="nowrap">${kbBtns('facts',f.code)}</td>`:''}</tr>`).join('')}</table>`:'<p class="muted small">None visible to you. Facts are confidential, so only managers, reviewers and admins can browse them.</p>'}</div>
   <div class="card"><h2>Glossary</h2><table>${k.glossary.map(g=>`<tr><td>${esc(g.kind)}</td><td>${esc(g.term)} → <b>${esc(g.preferred)}</b></td><td><code>${esc(g.rule_code)}</code></td>${admin?`<td class="nowrap">${kbBtns('glossary',g.id)}</td>`:''}</tr>`).join('')}</table></div>
   <div class="card"><h2>Reusable assets</h2><table>${k.assets.map(a=>`<tr><td><b>${esc(a.name)}</b></td><td>${esc(a.kind)}</td><td class="muted">${esc(a.note)}</td>${admin?`<td class="nowrap">${kbBtns('assets',a.id)}</td>`:''}</tr>`).join('')}</table></div></div>`;
}
/* admin: change or remove one item (prompt/confirm keep this small; the server validates everything) */
const kbBtns=(kind,key)=>`<button class="btn" data-k="${kind}" data-id="${esc(key)}" data-c="kbEdit" aria-label="Edit ${esc(key)}">Edit</button>
  <button class="btn" data-k="${kind}" data-id="${esc(key)}" data-c="kbDel" aria-label="Delete ${esc(key)}">Delete</button>`;
function kbFind(kind,key){const k=KBDATA||{};
  if(kind==='rules')return k.guidelines.flatMap(g=>g.rules).find(r=>r.code===key);
  if(kind==='facts')return k.facts.find(f=>f.code===key);
  return k[kind].find(x=>String(x.id)===String(key))}
const kbEdit=b=>run(async()=>{const kind=b.dataset.k,key=b.dataset.id,cur=kbFind(kind,key);if(!cur)return;let patch={};
  if(kind==='rules'){const t=prompt('Rule text',cur.text);if(t===null)return;patch={text:t}}
  else if(kind==='facts'){const t=prompt('Approved statement',cur.statement);if(t===null)return;
    const d=prompt('Checking data (JSON): this drives the automatic checks, e.g. the approved price or date',JSON.stringify(cur.data||{}));if(d===null)return;
    let data;try{data=JSON.parse(d)}catch(e){throw new Error('That data is not valid JSON')}patch={statement:t,data}}
  else if(kind==='glossary'){const t=prompt('Preferred wording for "'+cur.term+'"',cur.preferred);if(t===null)return;patch={preferred:t}}
  else{const t=prompt('Note',cur.note||'');if(t===null)return;patch={note:t}}
  await api('/api/kb/'+kind+'/'+encodeURIComponent(key),{method:'PATCH',json:patch});toast('Saved.');renderKB()});
const kbDel=b=>run(async()=>{if(!confirm('Delete '+b.dataset.id+'? Findings already made keep their quoted text, but new reviews will not use it.'))return;
  await api('/api/kb/'+b.dataset.k+'/'+encodeURIComponent(b.dataset.id),{method:'DELETE'});toast('Deleted.');renderKB()});
const seed=()=>run(async()=>{if(!confirm('This replaces the current knowledge base (guidelines, facts, glossary, assets and check settings) with the demo one. Existing content and its findings are kept. Continue?'))return;const r=await api('/api/kb/seed',{json:{}});toast('Demo knowledge base loaded: '+r.guidelines.rules+' rules, '+r.facts+' facts.');renderKB()});
const doImport=()=>run(async()=>{
  const fd=new FormData();fd.append('kind',$('#ik').value);fd.append('access_level',$('#il').value);fd.append('text',$('#itext').value);
  const f=$('#ifile').files[0];if(f)fd.append('file',f);
  const r=await api('/api/kb/import',{method:'POST',body:fd});toast('Imported: '+JSON.stringify(r));renderKB()});

boot();

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
