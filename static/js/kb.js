/* Knowledge base screen: guidelines, approved facts, glossary and assets, with search */
let KBSEC='guidelines', KBQ='', KBRULE=null, RV=null, RVCMP=null;
const KB_SECTIONS=[['guidelines','Guidelines'],['facts','Approved facts'],['glossary','Glossary'],['assets','Assets']];
const kbCount=(k,s)=>s==='guidelines'?k.guidelines.reduce((n,g)=>n+g.rules.length,0):k[s].length;

async function renderKB(){
  const rid=++RID;
  let k;
  try{k=await api('/api/kb')}catch(e){if(rid!==RID)return;$('#main').innerHTML=errorCard('We couldn’t load the knowledge base',e.message);return}
  if(rid!==RID)return;
  KBDATA=k;
  if(KBRULE){try{RV=await api('/api/kb/rules/'+encodeURIComponent(KBRULE)+'/versions')}catch(e){KBRULE=null;toast(e.message,true)}}
  if(rid!==RID)return;
  KBRULE?paintRuleHistory():paintKB();
}
function paintKB(){
  const k=KBDATA,admin=ME.role==='admin',empty=KB_SECTIONS.every(([s])=>kbCount(k,s)===0);
  $('#main').innerHTML=`${pageHead('Source of truth','Knowledge base','Keep guidelines, approved facts, terminology and reusable assets in one controlled place.',admin?'<span class="chip approved">Admin controls</span>':'')}
   <div class="stack"><section class="card" aria-label="Knowledge base contents">
     <div class="kb-tabs" role="tablist" aria-label="Knowledge base sections">${KB_SECTIONS.map(([s,l])=>`<button type="button" role="tab" id="tab-${s}" data-c="kbTab" data-a='["${s}"]' aria-selected="${s===KBSEC}" aria-controls="kb-panel" tabindex="${s===KBSEC?0:-1}">${l}<span class="count">${kbCount(k,s)}</span></button>`).join('')}</div>
     <div id="kb-panel" role="tabpanel" aria-labelledby="tab-${KBSEC}">
       <div class="kb-tools"><label class="sr-only" for="kbq">Search ${esc(KB_SECTIONS.find(x=>x[0]===KBSEC)[1].toLowerCase())}</label>
         <input type="search" id="kbq" placeholder="Search this section" value="${esc(KBQ)}" autocomplete="off"><span class="meta" id="kb-n" role="status"></span></div>
       <div id="kb-list" class="kb-list"></div></div></section>
   ${admin?kbAdmin(empty):''}</div>`;
  paintKBList();
}
function kbAdmin(empty){
  return `<section class="card" aria-labelledby="imp-h"><h2 id="imp-h">Add approved material</h2><p class="muted small">Import a guideline document or a list of facts, glossary terms or assets. The server validates everything before it is saved.</p>
    <div class="import-grid"><div class="row"><div class="field"><label for="ik">What to import</label><select id="ik"><option value="guidelines">Guidelines (PDF, DOCX, TXT, MD)</option>
        <option value="facts">Approved facts (JSON)</option><option value="glossary">Glossary (JSON)</option><option value="assets">Asset list (JSON)</option></select></div>
      <div class="field"><label for="il">Access level</label><select id="il"><option>internal</option><option>confidential</option><option>public</option></select></div></div>
      <div class="field"><label for="ifile">File to import</label><input type="file" id="ifile"></div>
      <div class="field"><label for="itext">…or paste text or JSON</label><textarea id="itext" rows="3"></textarea></div>
      <div><button class="btn primary" type="button" data-c="doImport">Import</button></div></div></section>
    <section class="zone danger" aria-labelledby="dz-h"><h2 id="dz-h">Replace with the demo knowledge base</h2>
      <p class="small">Replaces the current guidelines, facts, glossary, assets and check settings with the fictional Brewline Coffee set. Existing content and its findings are kept.${empty?'':' <b>This overwrites what is here now.</b>'}</p>
      <div class="u-gap"><button class="btn bad" type="button" data-c="seed">Load Brewline demo knowledge base</button></div></section>`;
}
const kbBtns=(kind,key,history)=>`<div class="kb-actions">${history?`<button class="btn sm" type="button" data-id="${esc(key)}" data-c="ruleOpen" aria-label="Version history for ${esc(key)}">History</button>`:''}<button class="btn sm" type="button" data-k="${kind}" data-id="${esc(key)}" data-c="kbEdit" aria-label="Edit ${esc(key)}">Edit</button>
  <button class="btn sm bad" type="button" data-k="${kind}" data-id="${esc(key)}" data-c="kbDel" aria-label="Delete ${esc(key)}">Delete</button></div>`;
function kbRow(code,title,body,meta,actions){
  return `<div class="kb-row"><div>${code?`<code>${esc(code)}</code>`:''}</div><div><h2>${title}</h2>${body?`<p>${body}</p>`:''}${meta?`<div class="kb-meta">${meta}</div>`:''}</div>${actions||''}</div>`}
const lvl=a=>`<span class="chip${a==='confidential'?' danger':''}">${esc(cap(a))}</span>`;
function kbEmpty(sec,admin){
  const m={guidelines:['No guidelines yet','Guidelines are the rules BrandGuard cites when it flags content.'],facts:['No approved facts visible','Approved facts are the verified claims BrandGuard checks prices, dates and claims against. Confidential facts are only visible to managers, reviewers and admins.'],
    glossary:['No glossary terms yet','Glossary terms set the preferred wording and the rule they belong to.'],assets:['No assets yet','Assets list approved names, references and supporting materials.']}[sec];
  return `<div class="empty-state"><div class="empty-icon" aria-hidden="true">▤</div><h2>${m[0]}</h2><p class="muted">${m[1]}${admin?' Import material or load the demo knowledge base below.':''}</p></div>`}
function paintKBList(){
  const k=KBDATA,admin=ME.role==='admin',q=KBQ.trim().toLowerCase(),box=$('#kb-list');if(!box)return;
  const hit=(...v)=>!q||v.join(' ').toLowerCase().includes(q);
  let html='',shown=0;const total=kbCount(k,KBSEC);
  if(KBSEC==='guidelines'){
    for(const g of k.guidelines){
      const rows=g.rules.filter(r=>hit(r.code,r.title,r.text));if(!rows.length)continue;shown+=rows.length;
      html+=`<p class="kb-group">${esc(g.title)} ${lvl(g.access_level)} <span class="meta">Imported ${when(g.imported_at)}</span></p>`
        +rows.map(r=>kbRow(r.code,esc(r.title),esc(r.text),'',admin?kbBtns('rules',r.code,true):'')).join('')}}
  else if(KBSEC==='facts'){
    const rows=k.facts.filter(f=>hit(f.code,f.kind,f.statement,f.source));shown=rows.length;
    html=rows.map(f=>kbRow(f.code,esc(f.statement),'',`<span class="chip">${esc(cap(f.kind))}</span>${lvl(f.access_level)}<span class="meta">Source: ${esc(f.source||'not recorded')}</span>`,admin?kbBtns('facts',f.code):'')).join('')}
  else if(KBSEC==='glossary'){
    const rows=k.glossary.filter(g=>hit(g.term,g.preferred,g.rule_code,g.kind));shown=rows.length;
    html=rows.map(g=>kbRow(g.rule_code,`${esc(g.term)} → <b>${esc(g.preferred)}</b>`,'',`<span class="chip">${esc(cap(g.kind))} term</span>${g.note?`<span class="meta">${esc(g.note)}</span>`:''}`,admin?kbBtns('glossary',g.id):'')).join('')}
  else{
    const rows=k.assets.filter(a=>hit(a.name,a.kind,a.note));shown=rows.length;
    html=rows.map(a=>kbRow('',esc(a.name),esc(a.note),`<span class="chip">${esc(cap(a.kind))}</span>${lvl(a.access_level)}`,admin?kbBtns('assets',a.id):'')).join('')}
  if(!total)html=kbEmpty(KBSEC,admin);
  else if(!shown)html=`<div class="empty-state"><div class="empty-icon" aria-hidden="true">⌕</div><h2>No matches</h2><p class="muted">Nothing in this section matches “${esc(KBQ)}”. Try a different word.</p><button class="btn" type="button" data-c="kbClear">Clear search</button></div>`;
  box.innerHTML=html;
  const n=$('#kb-n');if(n)n.textContent=total?(q?`${shown} of ${total} shown`:`${total} ${total===1?'item':'items'}`):'';
}
const kbTab=s=>{KBSEC=s;KBQ='';paintKB();const t=document.getElementById('tab-'+s);if(t)t.focus()};
const kbClear=()=>{KBQ='';const i=$('#kbq');if(i){i.value='';i.focus()}paintKBList()};
document.addEventListener('input',e=>{if(e.target.id==='kbq'){KBQ=e.target.value;paintKBList()}});
document.addEventListener('keydown',e=>{ // tabs: arrow keys move between sections
  const t=e.target.closest&&e.target.closest('[role=tab]');if(!t||(e.key!=='ArrowRight'&&e.key!=='ArrowLeft'))return;
  const ids=KB_SECTIONS.map(x=>x[0]),i=ids.indexOf(t.id.replace('tab-',''));
  e.preventDefault();kbTab(ids[(i+(e.key==='ArrowRight'?1:ids.length-1))%ids.length])});

/* admin: change or remove one item, in an in-page dialog (the server validates everything) */
function kbFind(kind,key){const k=KBDATA||{};
  if(kind==='rules')return k.guidelines.flatMap(g=>g.rules).find(r=>r.code===key);
  if(kind==='facts')return k.facts.find(f=>f.code===key);
  return k[kind].find(x=>String(x.id)===String(key))}
const kbEdit=b=>run(async()=>{
  const kind=b.dataset.k,key=b.dataset.id,cur=kbFind(kind,key);if(!cur)return;
  const send=patch=>api('/api/kb/'+kind+'/'+encodeURIComponent(key),{method:'PATCH',json:patch});
  let cfg;
  if(kind==='rules')cfg={title:'Edit rule '+key,fields:[{id:'text',label:'Rule text',type:'textarea',value:cur.text,rows:5}],submit:v=>send({text:v.text})};
  else if(kind==='facts')cfg={title:'Edit approved fact '+key,fields:[{id:'statement',label:'Approved statement',type:'textarea',value:cur.statement,rows:3},
      {id:'data',label:'Checking data (JSON)',type:'textarea',value:JSON.stringify(cur.data||{}),rows:3,hint:'Drives the automatic checks, for example the approved price or date.'}],
    submit:v=>{let data;try{data=JSON.parse(v.data)}catch(e){throw new Error('The checking data is not valid JSON.')}return send({statement:v.statement,data})}};
  else if(kind==='glossary')cfg={title:'Edit glossary term “'+cur.term+'”',fields:[{id:'preferred',label:'Preferred wording',value:cur.preferred}],submit:v=>send({preferred:v.preferred})};
  else cfg={title:'Edit asset “'+cur.name+'”',fields:[{id:'note',label:'Note',type:'textarea',value:cur.note||'',rows:3,optional:true}],submit:v=>send({note:v.note})};
  const ok=await askDialog({title:cfg.title,fields:cfg.fields,ok:'Save changes',onSubmit:cfg.submit});
  if(ok){toast('Saved.');renderKB()}});
const kbDel=b=>run(async()=>{
  const ok=await confirmDialog({title:'Delete '+b.dataset.id+'?',consequence:'Findings already made keep their quoted text, but new reviews will no longer use this item. This cannot be undone.',ok:'Delete',danger:true,
    onSubmit:()=>api('/api/kb/'+b.dataset.k+'/'+encodeURIComponent(b.dataset.id),{method:'DELETE'})});
  if(ok){toast('Deleted.');renderKB()}});
const seed=()=>run(async()=>{
  const k=KBDATA||{guidelines:[],facts:[],glossary:[],assets:[]};
  const hasData=KB_SECTIONS.some(([s])=>kbCount(k,s)>0);
  const go=async()=>{const r=await api('/api/kb/seed',{json:{}});toast('Demo knowledge base loaded: '+r.guidelines.rules+' rules, '+r.facts+' facts.');KBSEC='guidelines';renderKB()};
  if(!hasData){await go();return}
  await confirmDialog({title:'Replace the knowledge base?',note:'This loads the fictional Brewline Coffee demo set.',
    consequence:'It replaces the current guidelines, facts, glossary, assets and check settings. Existing content and its findings are kept.',ok:'Replace with demo data',danger:true,
    onSubmit:async()=>{await go()}})});
const doImport=()=>run(async()=>{
  const fd=new FormData();fd.append('kind',$('#ik').value);fd.append('access_level',$('#il').value);fd.append('text',$('#itext').value);
  const f=$('#ifile').files[0];if(f)fd.append('file',f);
  if(!f&&!$('#itext').value.trim()){toast('Choose a file or paste some text to import.',true);return}
  const r=await api('/api/kb/import',{method:'POST',body:fd});
  const parts=Object.entries(r).filter(([,v])=>typeof v==='number').map(([n,v])=>v+' '+n.replace(/_/g,' '));
  toast('Imported'+(parts.length?': '+parts.join(', '):'.'));KBSEC=$('#ik')?{guidelines:'guidelines',facts:'facts',glossary:'glossary',assets:'assets'}[$('#ik').value]||KBSEC:KBSEC;renderKB()});

/* ------------------------------------------------------------ rule version history (admin) */
const vChip=st=>`<span class="chip ${st==='published'?'success':st==='draft'?'warning':''}">${st==='published'?'Published':st==='draft'?'Draft':'Previous'}</span>`;
const ruleOpen=b=>{KBRULE=b.dataset.id;RVCMP=null;return render().then(()=>{focusMain()})};
const ruleBack=()=>{KBRULE=null;RV=null;RVCMP=null;return render().then(()=>{focusMain()})};
function diffHtml(c){
  if(c.identical)return '<p class="notice info">These two versions are identical.</p>';
  const seg=c.segments.map(x=>x.op==='removed'?`<del>${esc(x.text)}</del>`:x.op==='added'?`<ins>${esc(x.text)}</ins>`:esc(x.text)).join('');
  return `<p class="meta">Comparing version ${c.from.version} (${esc(c.from.status)}) with version ${c.to.version} (${esc(c.to.status)}). <del>Removed</del> <ins>Added</ins> unchanged</p>
    ${c.title_changed?`<p class="small">Title: <del>${esc(c.from.title)}</del> <ins>${esc(c.to.title)}</ins></p>`:''}<div class="rule-diff" tabindex="0" aria-label="Changes between the two versions">${seg}</div>`}
function paintRuleHistory(){
  const d=RV,pub=d.published,dr=d.draft,rule=kbFind('rules',d.code)||{title:pub.title};
  $('#main').innerHTML=`<div class="crumbs"><button class="btn ghost" type="button" data-c="ruleBack">← Knowledge base</button></div>
   ${pageHead('Guideline history',d.code+' · '+(pub?pub.title:rule.title),'Changes are drafted first, compared, then published. Reviews only ever use the published version.',
     `<span class="chip success">Published: version ${pub.version}</span>${dr?`<span class="chip warning">Draft: version ${dr.version}</span>`:''}`)}
   <div class="stack">
   <section class="card" aria-labelledby="pub-h"><h2 id="pub-h">Published version ${pub.version}</h2><p class="meta">Live now · ${esc(pub.note||'')} ${pub.published_at?'· '+when(pub.published_at):''}</p>
     <div class="evidence u-gap"><div class="evidence-src">${esc(pub.title)}</div><blockquote>${esc(pub.text)}</blockquote></div></section>
   <section class="card" aria-labelledby="dr-h"><h2 id="dr-h">${dr?'Draft version '+dr.version:'Create a new version'}</h2>
     <p class="muted small">${dr?'Not used by any review until you publish it.':'Write the new wording as a draft. The published rule stays as it is.'}</p>
     <form id="rv-form" class="stack u-gap" novalidate>
       <div class="field"><label for="rv-title">Title</label><input id="rv-title" type="text" maxlength="200" value="${esc(dr?dr.title:pub.title)}"></div>
       <div class="field"><label for="rv-text">Rule text</label><textarea id="rv-text" rows="6" maxlength="4000" aria-describedby="rv-err">${esc(dr?dr.text:pub.text)}</textarea></div>
       <div class="field"><label for="rv-note">What changed and why (optional)</label><input id="rv-note" type="text" maxlength="300" value="${esc(dr?dr.note:'')}"></div>
       <p class="dlg-err" id="rv-err" role="alert"></p>
       <div class="row"><button class="btn primary" type="submit">Save draft</button>
         ${dr?`<button class="btn" type="button" data-c="ruleCompare" data-a='[${pub.version},${dr.version}]'>Preview changes</button>
         <button class="btn good" type="button" data-c="rulePublish">Publish version ${dr.version}</button>
         <button class="btn bad" type="button" data-c="ruleDiscard">Discard draft</button>`:''}</div></form>
     ${RVCMP?`<div class="u-gap" id="rv-cmp" tabindex="-1">${diffHtml(RVCMP)}</div>`:''}</section>
   <section class="card" aria-labelledby="hist-h"><h2 id="hist-h">All versions (${d.versions.length})</h2>
     <ul class="timeline u-gap">${d.versions.map(v=>`<li class="rv-row"><div><b>Version ${v.version}</b> ${vChip(v.status)} <span class="meta">${esc(v.author||'System')} · ${when(v.published_at||v.created_at)}</span>
       ${v.note?`<div class="meta">${esc(v.note)}</div>`:''}<div class="small rv-text">${esc(v.text)}</div></div>
       <div class="kb-actions">${v.status!=='published'?`<button class="btn sm" type="button" data-c="ruleCompare" data-a='[${v.version},${pub.version}]' aria-label="Compare version ${v.version} with the published version">Compare</button>`:''}
         ${v.status==='archived'?`<button class="btn sm warn" type="button" data-c="ruleRollback" data-a='[${v.version}]' aria-label="Roll back to version ${v.version}">Roll back</button>`:''}</div></li>`).join('')}</ul></section></div>`;
  $('#rv-form').onsubmit=e=>{e.preventDefault();run(ruleSaveDraft)};
  if(RVCMP&&RVCMP._focus){delete RVCMP._focus;const c=$('#rv-cmp');if(c){c.scrollIntoView({block:'nearest'});c.focus({preventScroll:true})}}
}
async function ruleSaveDraft(){
  const err=$('#rv-err');err.textContent='';
  const text=$('#rv-text').value;
  if(!text.trim()){$('#rv-text').setAttribute('aria-invalid','true');err.textContent='Write the rule text first.';$('#rv-text').focus();return}
  try{await api('/api/kb/rules/'+encodeURIComponent(KBRULE)+'/draft',{json:{text,title:$('#rv-title').value,note:$('#rv-note').value}})}
  catch(e){err.textContent=e.message;return}
  RVCMP=null;toast('Draft saved. It is not live until you publish it.');await render();$('#dr-h')&&$('#dr-h').scrollIntoView({block:'nearest'})}
const ruleCompare=(a,b)=>run(async()=>{
  RVCMP=await api(`/api/kb/rules/${encodeURIComponent(KBRULE)}/compare?from=${a}&to=${b}`);RVCMP._focus=true;paintRuleHistory()});
const rulePublish=()=>run(async()=>{
  const dr=RV.draft;
  const ok=await confirmDialog({title:`Publish version ${dr.version} of ${KBRULE}?`,note:'This becomes the rule every new review is checked against.',
    consequence:'It takes effect immediately. Reviews already made keep the text they quoted. You can roll back later; the history is kept.',ok:'Publish version '+dr.version,
    onSubmit:()=>api('/api/kb/rules/'+encodeURIComponent(KBRULE)+'/publish',{method:'POST',json:{}})});
  if(ok){RVCMP=null;toast(`Version ${dr.version} is now live.`);await render()}});
const ruleDiscard=()=>run(async()=>{
  const ok=await confirmDialog({title:'Discard this draft?',consequence:'The draft text is deleted. The published version is not affected.',ok:'Discard draft',danger:true,
    onSubmit:()=>api('/api/kb/rules/'+encodeURIComponent(KBRULE)+'/draft',{method:'DELETE'})});
  if(ok){RVCMP=null;toast('Draft discarded.');await render()}});
const ruleRollback=v=>run(async()=>{
  const ok=await confirmDialog({title:`Roll back ${KBRULE} to version ${v}?`,note:`Version ${v} will be published again as a new version.`,
    consequence:'The current version stays in the history. New reviews use the restored wording straight away.',ok:'Roll back to version '+v,danger:true,
    onSubmit:()=>api('/api/kb/rules/'+encodeURIComponent(KBRULE)+'/rollback',{json:{version:v}})});
  if(ok){RVCMP=null;toast(`Rolled back. Version ${v} is live again.`);await render()}});
