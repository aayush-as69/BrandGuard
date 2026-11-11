/* Content list, review detail, findings, comments */
/* ------------------------------------------------------------ content list + detail */
let LISTN=50;
function moreContent(){LISTN+=50;render()}
async function renderContent(){
  const rid=++RID;
  const list=await api('/api/content?limit='+LISTN);
  if(rid!==RID)return;
  $('#main').innerHTML=`<div class="page-head"><div><div class="eyebrow">CONTENT WORKSPACE</div><h2>Review content with confidence.</h2><p>Draft, inspect findings, resolve issues, and keep an accountable version history.</p></div><button class="btn primary" data-c="showNew">+ New review</button></div>
  <div class="grid"><div class="stack">
    <div class="card"><div class="u-between row"><div><h2 class="u-m0">Your content</h2><p class="small muted u-m8-0-0">Recent drafts and approvals</p></div><button class="btn" data-c="showNew">New</button></div><div class="u-mt12" id="list">
      ${list.length?list.map(c=>`<div class="item ${c.id===CUR?'on':''}" tabindex="0" role="button" data-kb="1" data-c="openContent" data-a='[${c.id}]'>
        <b>${esc(c.title)}</b><span class="small muted">${esc(c.author)} · v${c.current_version}</span><br>
        <span class="chip ${cls(c.status)}">${label(c.status)}</span>
        ${c.open_findings?`<span class="chip high">${c.open_findings} open</span>`:`<span class="chip approved">${c.total_findings?'all decided':'clean'}</span>`}
      </div>`).join(''):'<p class="muted small">Nothing yet. Choose New to submit a draft for review.</p>'}${list.length>=LISTN?'<p><button class="btn small" data-c="moreContent">Show more</button></p>':''}</div></div></div>
    <div id="detail">${CUR?'':'<div class="card empty-state"><div class="empty-icon">✦</div><h3>Select a draft to review</h3><p class="muted">Choose an item on the left, or start a new review. BrandGuard will show the finding, source, suggested fix and decision trail together.</p><button class="btn primary" data-c="showNew">Start a review</button></div>'}</div></div>`;
  if(CUR) await loadDetail(CUR,rid);
}
async function openContent(id){CUR=id;await renderContent()}

function imgRow(i={}){return `<div class="imgrow">
  <input type="text" placeholder="file name" aria-label="Image file name" value="${esc(i.name||'')}" data-k="name">
  <input type="text" placeholder="alt text" aria-label="Image alt text" value="${esc(i.alt||'')}" data-k="alt">
  <input type="text" placeholder="text colour #RRGGBB" aria-label="Text colour on the image" value="${esc(i.text_color||'')}" data-k="text_color">
  <input type="text" placeholder="background #RRGGBB" aria-label="Background colour behind the text" value="${esc(i.bg_color||'')}" data-k="bg_color">
  <label class="small muted">Read colours from a file <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-img="1" aria-label="Choose an image file to read its colours"></label>
  <button class="btn" type="button" aria-label="Remove this image" data-c="removeRow">×</button></div>`}
document.addEventListener('change',e=>{const t=e.target;if(!t.dataset||!t.dataset.img||!t.files[0])return;
  run(async()=>{const fd=new FormData();fd.append('image',t.files[0]);
    const r=await api('/api/image/analyze',{method:'POST',body:fd});const row=t.closest('.imgrow');
    const set=(k,v)=>{const i=row.querySelector(`[data-k=${k}]`);if(i&&v)i.value=v};
    if(!row.querySelector('[data-k=name]').value)set('name',t.files[0].name);
    set('bg_color',r.bg_color);set('text_color',r.text_color);toast(`${r.width}×${r.height}px. ${r.note}`)})});
function readImgs(){return [...document.querySelectorAll('#imgs .imgrow')].map(r=>{const o={};r.querySelectorAll('input').forEach(i=>o[i.dataset.k]=i.value);return o}).filter(o=>o.name)}
function showNew(){
  CUR=null;DETAIL=null;
  $('#detail').innerHTML=`<div class="card stack"><div class="section-kicker">NEW REVIEW</div><h2>Submit content for review</h2><p class="muted small">Paste the draft you want to check. Findings are tied back to the approved knowledge base.</p>
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
  // The AI tone check can finish after the rule findings: look again every 2 s (at most a minute) until it does.
  clearTimeout(loadDetail.t);
  if(String((fresh.review_meta||{}).llm_status||'').startsWith('pending')&&(loadDetail.n=(loadDetail.n||0)+1)<=30)
    loadDetail.t=setTimeout(()=>{if(CUR===id)loadDetail(id).catch(()=>{})},2000);
  else loadDetail.n=0;
  const d=DETAIL,c=d.content,p=d.permissions,open=d.findings.filter(f=>f.decision==='open').length;
  const meta=d.review_meta||{};
  $('#detail').innerHTML=`<div class="stack">
   <div class="card"><div class="u-between row">
     <div><h2 class="u-title">${esc(c.title)}</h2>
       <span class="small muted">by ${esc(c.author)} · version ${c.current_version}</span></div>
     <div class="row"><span class="chip ${cls(c.status)}">${label(c.status)}</span>
       ${p.can_submit?`<button class="btn primary" data-c="act" data-a='["submit"]'>Submit for approval</button>`:''}
       ${p.can_approve?`<button class="btn good" data-c="act" data-a='["approve"]'>Approve</button>`:''}
       ${p.can_request_changes?`<button class="btn warn" data-c="reqChanges">Request changes</button>`:''}
       ${p.can_rerun&&c.status!=='approved'?`<button class="btn" data-c="act" data-a='["review"]'>Re-run review</button>`:''}
       <a class="u-plain btn" href="/api/content/${+c.id}/record" target="_blank" rel="noopener">Approval record</a></div></div>
     <p class="u-m8-0-0 small muted">${c.status==='approved'
       ?`Approved${c.approved_by?' by '+esc(c.approved_by):''}. This version is locked.`
       :`${open?`${open} finding${open>1?'s':''} still need a decision.`:(d.findings.length?'Every finding has a decision.':'No findings.')} Nothing is applied until a person clicks.`}</p>
     ${(meta.warnings||[]).map(w=>`<p class="u-warn-m6 small">⚠ ${esc(w)}</p>`).join('')}
     <p class="u-m6-0-0 small muted">AI judge: ${esc(meta.llm_status||'not used')}${(meta.rejected||[]).length?` · ${(meta.rejected).length} unverifiable suggestion(s) discarded`:''}</p></div>
   <div class="grid2">
     <div class="stack"><div class="card"><h3>Content</h3>
        <div class="body" id="body">${highlight(d)}</div>
        ${d.images.length?`<h3 class="u-mt14">Images</h3><table>${d.images.map(i=>`<tr><td><b>${esc(i.name)}</b></td>
          <td>alt: ${i.alt?esc(i.alt):'<span class="st-contradicted">missing</span>'}</td>
          <td>${i.text_color&&i.bg_color?`<span class="swatch" data-bg="${esc(i.bg_color)}" data-fg="${esc(i.text_color)}">Aa</span> ${esc(i.text_color)} on ${esc(i.bg_color)}`:''}</td></tr>`).join('')}</table>`:''}
        ${p.can_revise?`<details class="u-mt12"><summary>Edit the text myself</summary>
          <textarea class="u-my8" id="rb" rows="8" aria-label="Edit the content text">${esc(d.body)}</textarea>
          ${aiBox('rai')}<button class="btn" data-c="revise">Save as new version</button></details>`:''}</div>
        <div class="card"><h3>Claim check</h3>${d.claims.length?groupClaims(d.claims).map(g=>`<div class="claim">
          <div class="small">${esc(g.text)}</div><div class="tags">${g.tags.map(t=>`<span class="st-${cls(t.status)}">${label(t.status)}${t.source_id?' · '+esc(t.source_id):''}</span>`).join('')}</div></div>`).join('')
          :'<p class="small muted">No promotional claims detected.</p>'}
          <p class="u-m8-0-0 small muted">Claims are matched to approved facts. “No approved source” is never filled in by guessing.</p></div>
        <div class="card"><h3>Discussion</h3>${d.comments.map(m=>`<div class="cmt"><b>${esc(m.author)}</b> <span class="chip">${esc(m.role)}</span>
          <span class="small muted">${when(m.created_at)}</span><br>${esc(m.body)}</div>`).join('')||'<p class="small muted">No comments yet.</p>'}
          <div class="u-mt10 row"><input type="text" id="cm" placeholder="Add a comment…" aria-label="Add a comment" maxlength="2000"><button class="btn" data-c="comment">Post</button></div></div>
        <div class="card"><h3>Versions</h3>${d.versions.map(v=>`<div class="small"><b>v${v.version}</b> ${esc(v.author)} · ${esc(v.note)} <span class="muted">${when(v.created_at)}</span></div>`).join('')}
          ${d.audit.length?`<details class="u-mt10"><summary>Audit log (${d.audit.length})</summary>${d.audit.map(a=>`<div class="small muted">${when(a.created_at)} · ${esc(a.who||'system')} · <b>${esc(a.action)}</b> ${esc(a.detail)}</div>`).join('')}</details>`:''}</div></div>
     <div class="card"><h3>Findings (${d.findings.length})</h3>
        ${d.findings.map(f=>findingCard(f,p,c)).join('')||'<p class="muted small">Nothing to fix in this version.</p>'}
        ${d.history.length?`<details><summary>Resolved in earlier versions (${d.history.length})</summary>${d.history.map(h=>`<div class="u-py6 small">
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
    <p class="u-m8-0-4"><b>${esc(f.issue)}</b></p>
    <div class="quote"><b>${f.source_type==='fact'?'Approved fact':'Guideline'} ${esc(f.source_id)}:</b> ${esc(f.source_quote)}</div>
    ${f.target==='body'?'<div class="small muted">Flagged text</div>':''}${diff}
    ${done?`<p class="u-m6-0-0 small"><b>${esc(f.decision)}</b> by ${esc(f.decided_by_name||'')}${f.decision_reason?': '+esc(f.decision_reason):''}</p>`
    :(p.can_decide?`<div class="u-mt8 row">
        <button class="btn good" ${fix?'':`disabled title="${f.restricted?'Restricted fact: ask the brand team, or use Edit.':'No suggested fix. Use Edit.'}"`} data-c="decide" data-a='[${f.id},"accept"]'>Accept fix</button>
        <button class="btn" data-c="toggle" data-a='["e${f.id}"]'>Edit</button>
        <button class="btn bad" data-c="toggle" data-a='["d${f.id}"]'>Dismiss</button></div>
      <div id="e${f.id}" class="u-mt8 hidden row"><input class="u-flex1" type="text" id="et${f.id}" aria-label="Replacement text" value="${esc(fix||(f.target==='body'?f.span_text:''))}">
        <button class="btn primary" data-c="decideEdit" data-a='[${f.id}]'>Apply my edit</button></div>
      <div id="d${f.id}" class="u-mt8 hidden row"><input class="u-flex1" type="text" id="dr${f.id}" placeholder="Reason (required)" aria-label="Reason for dismissing" maxlength="500">
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

