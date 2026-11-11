/* Knowledge base screen */
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

