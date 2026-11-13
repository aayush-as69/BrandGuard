/* Content home, review workspace, findings, evidence, approval, comments */
let LISTN=50, LIST=[];
const cap=s=>s?s[0].toUpperCase()+s.slice(1):'';
const RISKY_CATEGORIES=['fact','claim'];
function moreContent(){LISTN+=50;render()}

/* ------------------------------------------------------------ home: what needs attention */
async function renderContent(){
  const rid=++RID;
  if(CUR){ // the workspace needs only its own content: no list request, and no blank flash when it refreshes after a decision
    if(!$('#detail')||$('.home'))$('#main').innerHTML='<div id="detail" class="stack">'+skeleton()+'</div>';
    await loadDetail(CUR,rid);return}
  const list=await api('/api/content?limit='+LISTN);
  if(rid!==RID)return;
  LIST=list;
  $('#main').innerHTML=`${pageHead('Content workspace','Review content with confidence','Check drafts against approved guidelines and facts, resolve issues, and keep an accountable record of every decision.',
      '<button class="btn primary" type="button" data-c="showNew">New review</button>')}
    <div class="home"><section class="card list-card" aria-labelledby="list-h"><div class="card-head"><h2 id="list-h">Your content</h2><button class="btn sm" type="button" data-c="showNew">New</button></div>
      <div id="list">${list.length?list.map(c=>`<div class="item" tabindex="0" role="button" data-kb="1" data-c="openContent" data-a='[${c.id}]'>
        <b>${esc(c.title)}</b><span class="meta">${esc(c.author)} · version ${c.current_version}</span>
        <span class="chips"><span class="chip ${cls(c.status)}">${label(c.status)}</span>${c.open_findings?`<span class="chip warning">${c.open_findings} open</span>`:`<span class="chip success">${c.total_findings?'All decided':'No findings'}</span>`}</span></div>`).join('')
        :'<p class="muted small">Nothing yet.</p>'}${list.length>=LISTN?'<p><button class="btn sm" type="button" data-c="moreContent">Show more</button></p>':''}</div></section>
      <div id="detail">${homePanel(list)}</div></div>`;
}
function homePanel(list){
  if(!list.length)return `<div class="card empty-state"><div class="empty-icon" aria-hidden="true">✦</div><h2>No reviews yet</h2><p class="muted">Create your first review to see findings, evidence and approval history here.</p><button class="btn primary" type="button" data-c="showNew">Start a review</button></div>`;
  const by=s=>list.filter(c=>c.status===s),inReview=by('in_review'),changes=by('changes_requested'),drafts=by('draft'),approved=by('approved');
  const openTotal=list.reduce((n,c)=>n+(c.status==='approved'?0:c.open_findings||0),0);
  const writer=ME&&ME.role==='creator';
  const attn=writer?[...changes.map(c=>[c,'Changes were requested. Resolve them and submit again.']),
      ...drafts.filter(c=>c.open_findings).map(c=>[c,plural(c.open_findings,'finding')+' to decide before submitting.'])]
    :inReview.map(c=>[c,c.open_findings?plural(c.open_findings,'finding')+' still need a decision before this can be approved.':'Every finding has a decision. Ready for approval.']);
  const tile=(n,l,alert)=>`<div class="tile${alert&&n?' alert':''}"><b>${n}</b><span>${l}</span></div>`;
  return `<section class="card" aria-labelledby="attn-h"><h2 id="attn-h">Needs your attention</h2>
    <p class="muted small">${writer?'Drafts you can move forward.':'Content waiting for a decision from you.'}</p>
    ${attn.length?`<ul class="attn">${attn.slice(0,6).map(([c,why])=>`<li><div><b>${esc(c.title)}</b><span class="why">${esc(c.author)} · ${esc(why)}</span></div>
      <button class="btn sm" type="button" data-c="openContent" data-a='[${c.id}]' aria-label="Open ${esc(c.title)}">${writer?'Resolve':'Review'}</button></li>`).join('')}</ul>`
      :`<div class="notice ok u-gap"><span aria-hidden="true">✓</span><span>Nothing needs your attention right now.</span></div>`}</section>
    <div class="tiles home-tiles" role="group" aria-label="Review summary">${tile(inReview.length,'awaiting approval',!writer)}${tile(changes.length,'changes requested',writer)}${tile(openTotal,'open findings',true)}${tile(approved.length,'approved')}</div>`;
}
async function openContent(id){CUR=id;SEL=null;await renderContent();focusMain()}
function closeContent(){CUR=null;DETAIL=null;SEL=null;clearTimeout(loadDetail.t);renderContent().then(focusMain)}

/* ------------------------------------------------------------ new review */
function imgRow(i={}){return `<div class="imgrow">
  <input type="text" placeholder="file name" aria-label="Image file name" value="${esc(i.name||'')}" data-k="name">
  <input type="text" placeholder="alt text" aria-label="Image alt text" value="${esc(i.alt||'')}" data-k="alt">
  <input type="text" placeholder="text colour #RRGGBB" aria-label="Text colour on the image" value="${esc(i.text_color||'')}" data-k="text_color">
  <input type="text" placeholder="background #RRGGBB" aria-label="Background colour behind the text" value="${esc(i.bg_color||'')}" data-k="bg_color">
  <button class="btn" type="button" aria-label="Remove this image" data-c="removeRow">Remove</button>
  <label>Read colours from a file <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-img="1" aria-label="Choose an image file to read its colours"></label></div>`}
document.addEventListener('change',e=>{const t=e.target;if(!t.dataset||!t.dataset.img||!t.files[0])return;
  run(async()=>{const fd=new FormData();fd.append('image',t.files[0]);
    const r=await api('/api/image/analyze',{method:'POST',body:fd});const row=t.closest('.imgrow');
    const set=(k,v)=>{const i=row.querySelector(`[data-k=${k}]`);if(i&&v)i.value=v};
    if(!row.querySelector('[data-k=name]').value)set('name',t.files[0].name);
    set('bg_color',r.bg_color);set('text_color',r.text_color);toast(`${r.width}×${r.height}px. ${r.note}`)})});
function readImgs(){return [...document.querySelectorAll('#imgs .imgrow')].map(r=>{const o={};r.querySelectorAll('input[data-k]').forEach(i=>o[i.dataset.k]=i.value);return o}).filter(o=>o.name)}
async function showNew(){
  if(CUR!==null||!$('#detail')){CUR=null;DETAIL=null;SEL=null;await renderContent()}
  $('#detail').innerHTML=`<section class="card new-review stack" aria-labelledby="nr-h"><div><div class="kicker">New review</div><h2 id="nr-h">Submit content for review</h2>
    <p class="muted small">Paste the draft you want to check. Every finding is traced back to your approved guidelines and facts.</p></div>
   <div class="field"><label for="nt">Title</label><input type="text" id="nt" maxlength="200"></div>
   <div class="field"><label for="nb">Text (paste an email, post or page)</label><textarea id="nb" rows="12" maxlength="50000"></textarea></div>
   <div class="field" role="group" aria-labelledby="imgs-l"><span class="f-label" id="imgs-l">Images (checked for alt text and text contrast)</span><div id="imgs"></div>
     <div><button class="btn sm" type="button" data-c="addImgRow">Add image</button></div></div>
   ${aiBox('nai')}
   <div class="notice info hidden" id="rv-status" role="status"><span class="spinner" aria-hidden="true"></span><span>Checking your content against the guidelines and approved facts. This usually takes a few seconds. Your text is saved.</span></div>
   <div class="row"><button class="btn primary" type="button" id="rv-go" data-c="createContent">Review now</button>
     <button class="btn" type="button" data-c="loadDemo">Load demo email</button>
     <button class="btn ghost" type="button" data-c="closeContent">Cancel</button></div></section>`;
  $('#nt').focus();
}
async function loadDemo(){run(async()=>{const d=await api('/api/demo');$('#nt').value=d.title;$('#nb').value=d.body;
  $('#imgs').innerHTML=d.images.map(imgRow).join('')})}
async function createContent(){
  if(!$('#nb').value.trim()){toast('Paste the text you want reviewed first.',true);$('#nb').focus();return}
  const go=$('#rv-go'),st=$('#rv-status');go.disabled=true;st.classList.remove('hidden');
  try{const r=await api('/api/content',{json:{title:$('#nt').value,body:$('#nb').value,images:readImgs(),use_ai:useAI('nai')}});
    CUR=r.id;SEL=null;toast('Review complete. Findings are listed with their sources.');await renderContent();focusMain()}
  catch(e){toast(e.message,true);const g=$('#rv-go');if(g){g.disabled=false;$('#rv-status').classList.add('hidden')}}}

/* ------------------------------------------------------------ review workspace */
const sigOf=d=>JSON.stringify([(d.review_meta||{}).llm_status,d.findings.map(f=>[f.id,f.decision])]);
async function loadDetail(id,rid){
  const fresh=await api('/api/content/'+id);
  if(rid!==undefined&&rid!==RID)return;
  const same=DETAIL&&DETAIL.content.id===id&&sigOf(DETAIL)===sigOf(fresh)&&rid===undefined; // a quiet poll that found nothing new does not redraw
  DETAIL=fresh;
  // The AI tone check can finish after the rule findings: look again every 2 s (at most a minute) until it does.
  clearTimeout(loadDetail.t);
  if(String((fresh.review_meta||{}).llm_status||'').startsWith('pending')&&(loadDetail.n=(loadDetail.n||0)+1)<=30)
    loadDetail.t=setTimeout(()=>{if(CUR===id)loadDetail(id).catch(()=>{})},2000);
  else loadDetail.n=0;
  if(SEL===null||!fresh.findings.some(f=>f.id===SEL)){const first=fresh.findings.find(f=>f.decision==='open')||fresh.findings[0];SEL=first?first.id:null}
  if(!same){paintDetail();loadRewrites(id,fresh)}
}
function keepInputs(draw){ // redrawing for a selection change must not lose what someone is typing
  const get=s=>{const e=$(s);return e?e.value:null};
  const kept={rb:get('#rb'),cm:get('#cm'),open:!!document.querySelector('#revise[open]')};
  draw();
  if(kept.rb!==null&&$('#rb'))$('#rb').value=kept.rb;if(kept.cm!==null&&$('#cm'))$('#cm').value=kept.cm;
  if(kept.open&&$('#revise'))$('#revise').open=true}
function aiLine(meta){
  const s=String(meta.llm_status||'not used'),rej=(meta.rejected||[]).length;
  const extra=rej?` ${plural(rej,'unverifiable AI suggestion')} discarded.`:'';
  if(s.startsWith('pending'))return `<div class="notice info" role="status"><span class="spinner" aria-hidden="true"></span><span><b>AI tone check running.</b> Rule-based findings are ready now; more may appear shortly.</span></div>`;
  if(s.startsWith('failed')||s.startsWith('interrupted'))return `<div class="notice warn"><span aria-hidden="true">!</span><span><b>The AI tone check did not finish.</b> Rule-based findings are complete. Re-run the review to try again.${extra}</span></div>`;
  if(s==='not used'||s.startsWith('skipped'))return `<p class="meta">AI tone check was not used for this review.${extra}</p>`;
  return `<p class="meta">AI tone check: ${esc(s)}${extra}</p>`}
function paintDetail(){keepInputs(()=>{
  const d=DETAIL,c=d.content,p=d.permissions,meta=d.review_meta||{};
  const open=d.findings.filter(f=>f.decision==='open').length;
  const state=c.status==='approved'?`Approved${c.approved_by?' by '+esc(c.approved_by):''}. This version is locked.`
    :open?`${plural(open,'finding')} still need${open===1?'s':''} a decision. Nothing changes until a person accepts, edits or dismisses it.`
    :(d.findings.length?'Every finding has a decision.':'No findings in this version.');
  $('#detail').innerHTML=`<div class="row"><button class="btn ghost" type="button" data-c="closeContent">← All content</button></div>
   <div class="card ws-head"><div class="ws-title"><div><div class="kicker">Review</div><h1 id="page-title" tabindex="-1">${esc(c.title)}</h1>
       <p class="meta">by ${esc(c.author)} · version ${c.current_version}</p></div>
     <div class="row"><span class="chip ${cls(c.status)}">${label(c.status)}</span><a class="btn" href="/api/content/${+c.id}/record" target="_blank" rel="noopener">Approval record</a></div></div>
     <p class="small">${state}${c.status!=='approved'?' <button class="btn ghost sm" type="button" data-c="toDecision">Go to decision</button>':''}</p>
     ${(meta.warnings||[]).map(w=>`<div class="notice warn"><span aria-hidden="true">!</span><span>${esc(w)}</span></div>`).join('')}
     ${aiLine(meta)}</div>
   <div class="ws-grid">
     <section class="card ws-doc" aria-labelledby="doc-h"><h2 id="doc-h">Submitted content</h2>
       <p class="meta u-pb">Highlighted text has an open finding. Select it, or pick a finding, to see the evidence.</p>
       <div class="body" id="body">${highlight(d)}</div>
       ${p.can_revise?`<details id="revise" class="u-mt"><summary>Edit the text myself</summary>
         <div class="stack"><textarea id="rb" rows="8" aria-label="Edit the content text">${esc(d.body)}</textarea>
         ${aiBox('rai')}<div><button class="btn" type="button" data-c="revise">Save as new version</button></div></div></details>`:''}</section>
     ${d.images.length?imagesCard(d):''}
     <div class="ws-side">${findingsCard(d)}${rewriteCard(d)}${approvalCard(d)}</div>
     ${claimsCard(d)}${discussionCard(d)}${versionsCard(d)}
   </div>`})}

function highlight(d){
  const spans=d.findings.filter(f=>f.target==='body'&&f.span_start>=0&&f.decision==='open').sort((a,b)=>a.span_start-b.span_start);
  // The server counts characters (code points); JavaScript strings count UTF-16 units, so an emoji
  // would shift every highlight after it. Slice by code point instead.
  const chars=Array.from(d.body),sl=(a,b)=>chars.slice(a,b).join('');
  let out='',pos=0;
  for(const f of spans){ if(f.span_start<pos)continue;
    out+=esc(sl(pos,f.span_start))+`<mark id="m${f.id}" class="${cls(f.severity)}${f.id===SEL?' sel':''}" tabindex="0" role="button" data-kb="1" data-c="pick" data-a='[${f.id},"mark"]' aria-label="${esc(cap(f.severity))} severity finding: ${esc(f.issue)}. Select to see the evidence.">${esc(sl(f.span_start,f.span_end))}</mark>`;pos=f.span_end}
  return out+esc(sl(pos));
}

function findingsCard(d){
  const f=d.findings,done=f.filter(x=>x.decision!=='open').length,pct=f.length?Math.round(100*done/f.length):100;
  const counts=['high','medium','low'].map(s=>[s,f.filter(x=>x.decision==='open'&&cls(x.severity)===s).length]).filter(x=>x[1]);
  return `<section class="card" aria-labelledby="fl-h"><div class="card-head"><h2 id="fl-h">Findings (${f.length})</h2><span class="chip ${done===f.length?'success':'warning'}">${done} of ${f.length} decided</span></div>
    ${f.length?`<div class="meter" role="progressbar" aria-label="Findings decided" aria-valuemin="0" aria-valuemax="${f.length}" aria-valuenow="${done}"><i data-w="${pct}"></i></div>
    ${counts.length?`<div class="fl-summary" aria-label="Open findings by severity">${counts.map(([s,n])=>`<span class="sev ${s}"><span aria-hidden="true">${SEV[s][0]}</span>${n} ${SEV[s][1]}</span>`).join('')}</div>`:''}
    <ul class="flist">${f.map(x=>findingItem(x,d.permissions)).join('')}</ul>`
    :`<div class="empty-state u-compact"><div class="empty-icon" aria-hidden="true">✓</div><h3>Nothing to fix in this version</h3><p class="muted small">No guideline, fact or claim issues were found.</p></div>`}
    ${d.history.length?`<details class="u-mt"><summary>Resolved in earlier versions (${d.history.length})</summary><ul class="timeline">${d.history.map(h=>`<li><b>${esc(h.source_id)}</b> ${esc(h.span_text)} → <b>${esc(h.decision_text)}</b> <span class="muted">${esc(h.decision)} by ${esc(h.decided_by_name||'')}</span></li>`).join('')}</ul></details>`:''}</section>`;
}
function findingItem(f,p){
  const sel=f.id===SEL,done=f.decision!=='open';
  const stateCls=f.decision==='open'?'warning':(f.decision==='dismissed'?'':'success');
  return `<li class="finding ${cls(f.severity)}${done?' done':''}${sel?' sel':''}" id="f${f.id}">
    <button class="f-btn" type="button" data-c="pick" data-a='[${f.id},"row"]' aria-expanded="${sel}" aria-controls="fd${f.id}">
      ${sev(f.severity)}<span class="f-title">${esc(f.issue)}</span><span class="chip ${stateCls}">${label(f.decision)}</span></button>
    ${sel?findingDetail(f,p):''}</li>`;
}
function findingDetail(f,p){
  const done=f.decision!=='open',fix=f.suggested_fix,risky=RISKY_CATEGORIES.includes(f.category)||f.needs_reviewer;
  const row=(tag,html)=>`<div class="diff-row"><span class="diff-tag">${tag}</span><span>${html}</span></div>`;
  const diff=f.target==='body'
    ? `<div class="diff">${row('Original',`<del>${esc(f.span_text)}</del>`)}${row('Proposed',fix?`<ins>${esc(fix)}</ins>`:'<span class="diff-none">No automatic suggestion. Use Edit to write your own.</span>')}</div>`
    : (fix?`<div class="diff">${row('Proposed',`<ins>${esc(fix)}</ins>`)}</div>${f.fix_note?`<p class="small muted">${esc(f.fix_note)}</p>`:''}`:`<p class="small muted">${esc(f.fix_note||'No automatic suggestion.')}</p>`);
  const noFixWhy=f.restricted?'Restricted fact: ask the brand team, or use Edit.':'No suggested fix. Use Edit.';
  const actions=done
    ?`<p class="decided"><span class="chip ${f.decision==='dismissed'?'':'success'}">${label(f.decision)}</span> by ${esc(f.decided_by_name||'')}${f.decision_reason?': '+esc(f.decision_reason):''}</p>`
    :(p.can_decide?`<div class="decide"><button class="btn good" type="button" ${fix?'':'disabled aria-describedby="nofix'+f.id+'"'} data-c="decide" data-a='[${f.id},"accept"]'>Accept fix</button>
        <button class="btn" type="button" data-c="toggle" data-a='["e${f.id}"]'>Edit</button>
        <button class="btn bad" type="button" data-c="toggle" data-a='["d${f.id}"]'>Dismiss</button></div>
      ${fix?'':`<span class="field-hint" id="nofix${f.id}">${noFixWhy}</span>`}
      <div id="e${f.id}" class="inline-form hidden"><label class="sr-only" for="et${f.id}">Replacement text</label><input type="text" id="et${f.id}" value="${esc(fix||(f.target==='body'?f.span_text:''))}">
        <button class="btn primary" type="button" data-c="decideEdit" data-a='[${f.id}]'>Apply my edit</button></div>
      <div id="d${f.id}" class="hidden"><div class="inline-form"><label class="sr-only" for="dr${f.id}">Reason for dismissing</label><input type="text" id="dr${f.id}" placeholder="Reason (required)" maxlength="500" aria-describedby="dh${f.id}">
        <button class="btn bad" type="button" data-c="decideDismiss" data-a='[${f.id}]'>Dismiss with reason</button></div>
        ${risky?`<span class="field-hint" id="dh${f.id}">Dismissing this means a reviewer must approve the content.</span>`:`<span class="field-hint" id="dh${f.id}">The reason is kept in the audit trail.</span>`}</div>`:'<p class="small muted">You can read this finding but not decide it.</p>');
  return `<div class="f-detail" id="fd${f.id}">
    <div class="f-meta"><span class="chip">${esc(cap(f.category))}</span><span class="chip">${esc(cap(f.confidence))} confidence</span>${f.ai_generated?'<span class="chip ai">AI-generated</span>':''}${f.needs_reviewer?'<span class="chip danger">Needs a reviewer</span>':''}${f.restricted?'<span class="chip" title="Only the brand team can see this fact">🔒 Restricted fact</span>':''}</div>
    <div class="f-step"><span class="f-label">Why this was flagged</span><p class="f-why">${esc(f.issue)}</p></div>
    <div class="f-step"><span class="f-label">Approved source</span><div class="evidence"><div class="evidence-src"><span class="chip">${f.source_type==='fact'?'Approved fact':'Guideline'} ${esc(f.source_id)}</span></div>
      <blockquote>${esc(f.source_quote)}</blockquote>
      ${f.target==='body'&&f.span_text?`<p class="evidence-match">Matched text in the draft: <q>${esc(f.span_text)}</q></p>`:''}</div></div>
    <div class="f-step"><span class="f-label">Suggested correction</span>${diff}</div>
    <div class="f-step"><span class="f-label">Your decision</span>${actions}</div></div>`;
}

/* ------------------------------------------------------------ approval: what is left, then the decision */
function approvalCard(d){
  const c=d.content,p=d.permissions,f=d.findings;
  const open=f.filter(x=>x.decision==='open').length;
  const fixed=f.filter(x=>x.decision==='accepted'||x.decision==='edited').length,dismissed=f.filter(x=>x.decision==='dismissed').length;
  const risky=f.some(x=>x.decision==='dismissed'&&(RISKY_CATEGORIES.includes(x.category)||x.needs_reviewer));
  const groups=groupClaims(d.claims),has=s=>groups.filter(g=>g.tags.some(t=>t.status===s)).length;
  const needsReviewer=risky&&ME&&ME.role!=='reviewer';
  const blockers=[];
  if(open)blockers.push(`${plural(open,'finding')} still require${open===1?'s':''} a decision before approval.`);
  if(needsReviewer)blockers.push('A claim or low-confidence finding was dismissed, so a reviewer must approve this content.');
  const li=(kind,text)=>`<li><span class="mk ${kind}" aria-hidden="true">${kind==='ok'?'✓':kind==='block'?'✕':'•'}</span><span><span class="sr-only">${kind==='ok'?'Done: ':kind==='block'?'Blocking: ':'Info: '}</span>${text}</span></li>`;
  const last=d.audit[0];
  const list=`<ul class="readiness">
    ${open?li('block',`${plural(open,'finding')} still need${open===1?'s':''} a decision.`):li('ok',f.length?'Every finding has a decision.':'No findings in this version.')}
    ${groups.length?li(has('contradicted')?'block':'info',`Claim check: ${has('supported')} supported, ${has('contradicted')} contradicted, ${has('no_approved_source')} with no approved source.`):li('info','Claim check: no promotional claims detected.')}
    ${li('info',`Changes: ${fixed} fix${fixed===1?'':'es'} accepted or edited, ${dismissed} dismissed. Version ${c.current_version}.`)}
    ${li('info',`${plural(d.comments.length,'comment')}.`)}
    ${last?li('info',`Last activity: ${esc(last.action)} by ${esc(last.who||'system')}, ${when(last.created_at)}.`):''}</ul>`;
  let actions='';
  if(c.status==='approved')actions=`<div class="notice ok"><span aria-hidden="true">✓</span><span>Approved${c.approved_by?' by '+esc(c.approved_by):''}${c.approved_at?', '+when(c.approved_at):''}. This version is locked.</span></div>`;
  else{
    const btns=[];
    if(p.can_submit)btns.push(`<button class="btn primary" type="button" data-c="act" data-a='["submit"]'>Submit for approval</button>`);
    if(p.can_approve)btns.push(`<button class="btn good" type="button" data-c="approve"${blockers.length?' disabled aria-describedby="blocked-why"':''}>Approve review</button>`);
    if(p.can_request_changes)btns.push(`<button class="btn warn" type="button" data-c="reqChanges">Request changes</button>`);
    if(p.can_rerun)btns.push(`<button class="btn" type="button" data-c="act" data-a='["review"]'>Re-run review</button>`);
    actions=(btns.length?`<div class="approval-actions">${btns.join('')}</div>`:'')
      +(p.can_approve&&blockers.length?`<div class="notice warn blocked" id="blocked-why"><span aria-hidden="true">!</span><span><b>Approval is blocked.</b> ${blockers.map(esc).join(' ')}</span></div>`:'')
      +(p.can_submit&&open?`<div class="notice warn blocked"><span aria-hidden="true">!</span><span>${plural(open,'finding')} still need${open===1?'s':''} a decision. You can submit now, but approval stays blocked until each has one.</span></div>`:'')
      +(!p.can_submit&&!p.can_approve?`<p class="small muted blocked">${c.status==='in_review'?'In review. A manager or reviewer who did not write this content decides next.':'Only the author can submit this content for approval.'}</p>`:'');
  }
  return `<section class="card" id="decision" tabindex="-1" aria-labelledby="dec-h"><h2 id="dec-h">Decision</h2><p class="muted small">Check what is left, then decide.</p>${list}${actions}</section>`;
}
function toDecision(){const e=$('#decision');if(e){e.scrollIntoView({behavior:'smooth',block:'start'});e.focus({preventScroll:true})}}

/* ------------------------------------------------------------ supporting cards */
function imagesCard(d){
  return `<section class="card ws-images" aria-labelledby="img-h"><h2 id="img-h">Images</h2>${d.images.map(i=>{
    const r=i.text_color&&i.bg_color?ratio(i.text_color,i.bg_color):null,ok=r!==null&&r>=4.5;
    return `<div class="img-item">${r!==null?`<span class="swatch" data-bg="${esc(i.bg_color)}" aria-hidden="true"><i data-bg="${esc(i.text_color)}"></i></span>`:'<span class="swatch" aria-hidden="true">▢</span>'}
      <div class="img-checks"><span class="img-name">${esc(i.name)}</span>
        <span>Alt text: ${i.alt?`<span class="st-supported">✓ present</span> <span class="muted">“${esc(i.alt)}”</span>`:'<span class="st-contradicted">✕ missing</span>'}</span>
        ${r!==null?`<span>Text contrast: <b>measured ${r.toFixed(1)}:1</b>, required 4.5:1 ${ok?'<span class="st-supported">✓ passes</span>':'<span class="st-contradicted">✕ fails</span>'} <span class="muted">(${esc(i.text_color)} on ${esc(i.bg_color)})</span></span>`:'<span class="muted">No text colours supplied, so contrast was not measured.</span>'}</div></div>`}).join('')}
    <p class="meta u-pt">Images are checked from the details you provide; the image file itself is not stored.</p></section>`;
}
function groupClaims(claims){ // one row per sentence, with every status found in it
  const map=new Map();
  for(const c of claims){ if(!map.has(c.text))map.set(c.text,{text:c.text,tags:[]});
    const g=map.get(c.text); if(!g.tags.some(t=>t.status===c.status&&t.source_id===c.source_id))g.tags.push(c) }
  return [...map.values()];
}
const CLAIM_MARK={supported:'✓',contradicted:'✕',no_approved_source:'?'};
function claimsCard(d){
  return `<section class="card ws-claims" aria-labelledby="cl-h"><h2 id="cl-h">Claim check</h2>${d.claims.length?groupClaims(d.claims).map(g=>`<div class="claim">
    <div class="small">${esc(g.text)}</div><div class="tags">${g.tags.map(t=>`<span class="st-${cls(t.status)}"><span aria-hidden="true">${CLAIM_MARK[t.status]||''}</span> ${label(t.status)}${t.source_id?' · '+esc(t.source_id):''}</span>`).join('')}</div></div>`).join('')
    :'<p class="small muted">No promotional claims detected.</p>'}
    <p class="meta u-pt">Claims are matched to approved facts. “No approved source” is never filled in by guessing.</p></section>`;
}
function discussionCard(d){
  return `<section class="card ws-disc" aria-labelledby="dc-h"><h2 id="dc-h">Discussion</h2>${d.comments.map(m=>`<div class="cmt"><div class="cmt-head"><b>${esc(m.author)}</b> <span class="chip">${esc(m.role)}</span> <span class="meta">${when(m.created_at)}</span></div>${esc(m.body)}</div>`).join('')||'<p class="small muted">No comments yet.</p>'}
    <div class="inline-form u-mt"><label class="sr-only" for="cm">Add a comment</label><input type="text" id="cm" placeholder="Add a comment…" maxlength="2000"><button class="btn" type="button" data-c="comment">Post comment</button></div></section>`;
}
function versionsCard(d){
  return `<section class="card ws-vers" aria-labelledby="vs-h"><h2 id="vs-h">Version history and audit trail</h2><ul class="timeline">${d.versions.map(v=>`<li><b>Version ${v.version}</b> ${esc(v.author)} · ${esc(v.note)} <span class="muted">${when(v.created_at)}</span></li>`).join('')}</ul>
    ${d.audit.length?`<details class="u-mt"><summary>Audit trail (${d.audit.length})</summary><ul class="timeline">${d.audit.map(a=>`<li><span class="muted">${when(a.created_at)}</span> · ${esc(a.who||'system')} · <b>${esc(a.action)}</b> ${esc(a.detail)}</li>`).join('')}</ul></details>`:''}</section>`;
}

/* ------------------------------------------------------------ actions */
function pick(id,from){
  SEL=id;paintDetail();
  const row=document.querySelector('#f'+id+' .f-btn');if(row){row.focus({preventScroll:true});
    const target=from==='mark'?document.getElementById('f'+id):document.getElementById('m'+id);
    if(target)target.scrollIntoView({block:'nearest',behavior:'smooth'})}
}
function toggle(id){const el=document.getElementById(id);el.classList.toggle('hidden');
  if(!el.classList.contains('hidden')){const i=el.querySelector('input');if(i)i.focus()}}
function removeRow(el){el.closest('.imgrow').remove()}
function addImgRow(){document.getElementById('imgs').insertAdjacentHTML('beforeend',imgRow())}
function decideEdit(id){decide(id,'edit',document.getElementById('et'+id).value)}
function decideDismiss(id){
  const r=document.getElementById('dr'+id);
  if(!r.value.trim()){r.setAttribute('aria-invalid','true');toast('Add a reason so the decision can be audited.',true);r.focus();return}
  decide(id,'dismiss',null,r.value)}
function decide(id,action,text,reason){return run(async()=>{
  const r=await api('/api/findings/'+id+'/decide',{json:{action,text,reason}});
  toast(action==='dismiss'?'Finding dismissed.':(action==='edit'?'Edit applied':'Fix accepted')+'. Saved as version '+r.new_version+' and re-reviewed.');
  SEL=null;await renderContent();const b=document.querySelector('#f'+SEL+' .f-btn');if(b)b.focus()})}
const act=a=>run(async()=>{await api('/api/content/'+CUR+'/'+a,{method:'POST',json:{}});
  toast({submit:'Review submitted for approval.',review:'Review re-run.'}[a]);await renderContent()});
const approve=()=>run(async()=>{
  const c=DETAIL.content;
  const ok=await confirmDialog({title:'Approve this version?',note:`Version ${c.current_version} of “${c.title}” will be approved.`,
    consequence:'Approved content is locked and cannot be edited. Your approval is recorded in the audit trail.',ok:'Approve review',
    onSubmit:()=>api('/api/content/'+CUR+'/approve',{method:'POST',json:{}})});
  if(ok){toast('Approved. This version is now locked.');await renderContent()}});
const reqChanges=()=>run(async()=>{
  const ok=await askDialog({title:'Request changes',note:'The author will see your note in the discussion and can resolve it and submit again.',ok:'Request changes',
    fields:[{id:'note',label:'What needs to change?',type:'textarea',hint:'Be specific so the author knows what to fix.'}],
    onSubmit:v=>api('/api/content/'+CUR+'/request-changes',{json:{note:v.note}})});
  if(ok){toast('Changes requested. The author has been notified in the discussion.');await renderContent()}});
const comment=()=>run(async()=>{const b=$('#cm').value;
  if(!b.trim()){toast('Write a comment first.',true);$('#cm').focus();return}
  await api('/api/content/'+CUR+'/comments',{json:{body:b}});toast('Comment posted.');await renderContent();const n=$('#cm');if(n)n.focus()});
const revise=()=>run(async()=>{await api('/api/content/'+CUR+'/revise',{json:{body:$('#rb').value,images:DETAIL.images,use_ai:useAI('rai')}});
  toast('Saved as a new version and re-reviewed.');SEL=null;await renderContent()});


/* ------------------------------------------------------------ rewrite options: three strengths, each checked before it is shown */
let RW=null; // {id, version, data, sel, view}
const RW_VIEWS=[['original','Original'],['proposed','Proposed'],['diff','Changes']];
function loadRewrites(id,d){
  const open=d.findings.some(f=>f.decision==='open');
  if(!d.permissions.can_decide||d.content.status==='approved'||!open){RW=null;return}
  api('/api/content/'+id+'/rewrites').then(data=>{
    if(CUR!==id||!DETAIL||DETAIL.content.current_version!==data.version)return;
    const keep=RW&&RW.id===id&&RW.version===data.version?RW:null;
    const first=data.options.find(o=>o.status==='ok');
    RW={id,version:data.version,data,sel:keep&&data.options.some(o=>o.strength===keep.sel&&o.status==='ok')?keep.sel:(first?first.strength:null),view:keep?keep.view:'proposed'};
    paintDetail()}).catch(()=>{RW=null})}
function rwBody(o,view){
  const wrap=(label,html)=>`<div class="rw-text" tabindex="0" role="region" aria-label="${label}">${html}</div>`;
  if(view==='original')return wrap('Original text',esc(DETAIL.body));
  if(view==='diff')return wrap('Changes shown in the text',o.diff.map(x=>x.op==='same'?esc(x.text):x.op==='removed'?`<del>${esc(x.text)}</del>`:`<ins>${esc(x.text)}</ins>`).join(''));
  return wrap('Proposed text',esc(o.body))}
function rewriteCard(d){
  if(!RW||RW.id!==d.content.id||RW.version!==d.content.current_version)return '';
  const opts=RW.data.options,ok=opts.filter(o=>o.status==='ok'),hidden=opts.filter(o=>o.status==='hidden').length;
  if(!ok.length&&!hidden)return '';
  const head=`<div class="card-head"><h2 id="rw-h">Rewrite options</h2></div>`;
  if(!ok.length)return `<section class="card" aria-labelledby="rw-h">${head}<div class="notice info"><span aria-hidden="true">i</span><span>${plural(hidden,'rewrite option')} did not pass the safety checks and ${hidden===1?'is':'are'} not offered. Decide each finding yourself below.</span></div></section>`;
  const o=ok.find(x=>x.strength===RW.sel)||ok[0],p=d.permissions;
  const tabs=ok.map(x=>`<button type="button" role="tab" id="rwt-${x.strength}" aria-selected="${x===o}" aria-controls="rwp" data-c="rwTab" data-a='["${x.strength}"]'>${esc(x.label)}${x.same_as?'':` <span class="muted">${x.changes.length}</span>`}</button>`).join('');
  const views=RW_VIEWS.map(([k,l])=>`<button type="button" class="btn sm${RW.view===k?' on':''}" aria-pressed="${RW.view===k}" data-c="rwView" data-a='["${k}"]'>${l}</button>`).join('');
  const checks=o.checks.map(c=>`<li class="chip ${c.ok?'success':'danger'}"><span aria-hidden="true">${c.ok?'✓':'✕'}</span> ${esc(c.label)}</li>`).join('');
  const changes=o.changes.map(c=>`<li><b>${esc(c.source_id)}</b> <del>${esc(c.from)}</del> → <ins>${esc(c.to)}</ins></li>`).join('');
  const same=o.same_as?`<p class="small muted">Same changes as ${esc(cap(o.same_as))}. Nothing extra is added at this strength.</p>`:'';
  return `<section class="card" aria-labelledby="rw-h">${head}
    <p class="small muted">Each option applies fixes BrandGuard already proposed. It is checked again against the approved facts before you see it. Nothing changes until you apply one.</p>
    <div class="rw-tabs" role="tablist" aria-label="Rewrite strength">${tabs}</div>
    <div id="rwp" role="tabpanel" aria-labelledby="rwt-${o.strength}"><p class="small">${esc(o.summary)} <b>${plural(o.changes.length,'change')}.</b></p>${same}
      <div class="rw-views" role="group" aria-label="View">${views}</div>${rwBody(o,RW.view)}
      <details class="u-mt"><summary>What changes (${o.changes.length})</summary><ul class="timeline">${changes}</ul></details>
      <div class="f-step"><span class="f-label">Safety checks</span><ul class="rw-checks">${checks}</ul></div>
      ${p.can_decide?`<div class="decide"><button class="btn good" type="button" data-c="rwApply" data-a='["${o.strength}"]'>Apply ${esc(o.label.toLowerCase())} rewrite</button></div>`:''}</div>
    ${hidden?`<p class="small muted u-mt">${plural(hidden,'other option')} did not pass the safety checks and ${hidden===1?'is':'are'} not offered.</p>`:''}</section>`}
function rwTab(k){RW.sel=k;paintDetail();const t=document.getElementById('rwt-'+k);if(t)t.focus()}
function rwView(k){RW.view=k;paintDetail()}
function rwApply(k){const o=RW.data.options.find(x=>x.strength===k);
  return askDialog({title:`Apply the ${o.label.toLowerCase()} rewrite?`,note:'This creates a new version of the content with these changes.',
    consequence:`${plural(o.changes.length,'fix','fixes')} will be applied and marked accepted. You can still edit the new version, and the earlier version stays in the history.`,ok:'Apply rewrite',
    onSubmit:async()=>{await api('/api/content/'+CUR+'/rewrites/'+k+'/apply',{method:'POST',json:{}})}})
    .then(async done=>{if(done){toast('Rewrite applied as a new version.');RW=null;await loadDetail(CUR,RID)}})}
