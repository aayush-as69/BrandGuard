/* Knowledge base screen: guidelines, approved facts, glossary and assets, with search */
let KBSEC='guidelines', KBQ='';
const KB_SECTIONS=[['guidelines','Guidelines'],['facts','Approved facts'],['glossary','Glossary'],['assets','Assets']];
const kbCount=(k,s)=>s==='guidelines'?k.guidelines.reduce((n,g)=>n+g.rules.length,0):k[s].length;

async function renderKB(){
  const rid=++RID;
  let k;
  try{k=await api('/api/kb')}catch(e){if(rid!==RID)return;$('#main').innerHTML=errorCard('We couldn’t load the knowledge base',e.message);return}
  if(rid!==RID)return;
  KBDATA=k;paintKB();
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
const kbBtns=(kind,key)=>`<div class="kb-actions"><button class="btn sm" type="button" data-k="${kind}" data-id="${esc(key)}" data-c="kbEdit" aria-label="Edit ${esc(key)}">Edit</button>
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
        +rows.map(r=>kbRow(r.code,esc(r.title),esc(r.text),'',admin?kbBtns('rules',r.code):'')).join('')}}
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
