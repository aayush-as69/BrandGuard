/* Benchmark screen (admin): how reliably the rules catch real problems and avoid false alarms */
let BM=null, BMSEL=null, BMRUN=null, BMCMP=null, BMTITLES={};
const pct=v=>v==null?'n/a':(Math.round(v*1000)/10)+'%';
const pts=d=>d==null?'n/a':(d>0?'+':d<0?'−':'±')+Math.abs(Math.round(d*1000)/10)+' points';
const trend=d=>d==null||d===0?'No change':d>0?'Better':'Worse';

async function renderBenchmark(){
  const rid=++RID;let data,kb;
  try{[data,kb]=await Promise.all([api('/api/benchmark'),api('/api/kb')])}
  catch(e){if(rid!==RID)return;$('#main').innerHTML=errorCard('We couldn’t load the benchmark',e.message);return}
  if(rid!==RID)return;
  BM=data;BMTITLES={};
  for(const g of kb.guidelines)for(const r of g.rules)BMTITLES[r.code]=r.title;
  for(const f of kb.facts)BMTITLES[f.code]=f.statement;
  BMKB=kb;
  const runs=data.runs;
  BMRUN=null;BMCMP=null;
  if(runs.length){
    const after=BMSEL&&runs.some(r=>r.id===BMSEL.after)?BMSEL.after:runs[0].id;
    const before=BMSEL&&runs.some(r=>r.id===BMSEL.before)?BMSEL.before:(runs.find(r=>r.id<after)||{}).id;
    try{
      BMRUN=await api('/api/benchmark/runs/'+after);
      if(before)BMCMP=await api(`/api/benchmark/compare?before=${before}&after=${after}`);
    }catch(e){if(rid!==RID)return;$('#main').innerHTML=errorCard('We couldn’t load that run',e.message);return}
    BMSEL={before:before||null,after};
  }
  if(rid!==RID)return;
  paintBenchmark();
}
let BMKB=null;
const rname=c=>BMTITLES[c]?`<b>${esc(c)}</b> <span class="muted">${esc(BMTITLES[c].length>60?BMTITLES[c].slice(0,57)+'…':BMTITLES[c])}</span>`:`<b>${esc(c)}</b>`;

function metricRow(label,s){return `<tr><th scope="row">${label}</th><td>${pct(s.precision)}</td><td>${pct(s.recall)}</td></tr>`}
function paintBenchmark(){
  const d=BM,head=pageHead('Accuracy','Benchmark','Test the checks against labelled examples to see how many real problems they catch and how often they raise a false alarm.',
    d.cases.length?`<button class="btn primary" type="button" id="bm-run" data-c="bmRun">Run benchmark</button>`:'');
  if(!d.cases.length){
    $('#main').innerHTML=head+`<div class="card empty-state"><div class="empty-icon" aria-hidden="true">◎</div><h2>No benchmark cases yet</h2>
      <p class="muted">A benchmark is a set of short texts where you have said which problems should be found. Running it shows how accurate your rules are. Load the demo set to see how it works, or add your own cases.</p>
      <div class="row"><button class="btn primary" type="button" data-c="bmSeed">Load demo cases</button><button class="btn" type="button" data-c="bmAddCase">Add a case</button></div></div>`;return}
  const run=BMRUN,cmp=BMCMP,s=run?run.summary:null;
  const runPanel=run?`<section class="card" aria-labelledby="acc-h"><div class="card-head"><div><h2 id="acc-h">Rule accuracy</h2>
      <p class="muted small">${esc(run.label||'Run '+run.id)} · ${when(run.created_at)} · ${plural(s.cases,'case')}</p></div></div>
    <div class="bm-metrics">
      <div class="bm-metric"><span class="kicker">Precision</span><b>${pct(s.precision)}</b><span class="small muted">When BrandGuard flags something, it is right this often. Lower means more false alarms.</span></div>
      <div class="bm-metric"><span class="kicker">Recall</span><b>${pct(s.recall)}</b><span class="small muted">Of the real problems, this many are caught. Lower means mistakes could go live.</span></div></div>
    <p class="small u-gap"><span class="chip success">${s.tp} caught</span> <span class="chip ${s.fn?'danger':''}">${s.fn} missed</span> <span class="chip ${s.fp?'warning':''}">${s.fp} false ${s.fp===1?'alarm':'alarms'}</span></p>
    ${cmp?compareBlock(cmp):'<p class="notice info u-gap">Run the benchmark again after changing the glossary or checks to see what improved.</p>'}</section>`:
    `<section class="card empty-state"><div class="empty-icon" aria-hidden="true">◎</div><h2>No runs yet</h2><p class="muted">You have ${plural(d.cases.length,'case')}. Run the benchmark to see accuracy.</p><button class="btn primary" type="button" data-c="bmRun">Run benchmark</button></section>`;
  $('#main').innerHTML=head+`<div id="bm-status" class="notice info hidden" role="status"><span class="spinner" aria-hidden="true"></span><span>Running the checks on ${plural(d.cases.length,'case')}. No text is sent to any AI service.</span></div>
   <div class="stack">${runPanel}${run?rulesCard(run,cmp):''}${run?fixCard(run):''}${runsCard(d)}${casesCard(d)}</div>`;
}
function compareBlock(c){
  const a=c.summary.before,b=c.summary.after,dl=c.summary.delta;
  const ch=c.changes,items=[];
  ch.glossary.added.forEach(x=>items.push(`Glossary term added: ${esc(x)}`));ch.glossary.removed.forEach(x=>items.push(`Glossary term removed: ${esc(x)}`));
  ch.facts.added.forEach(x=>items.push(`Fact added or changed: ${esc(x)}`));ch.facts.removed.forEach(x=>items.push(`Fact removed or changed: ${esc(x)}`));
  ch.checks.forEach(x=>items.push(`Check setting changed: ${esc(x.check)}`));
  ch.rule_versions.forEach(x=>items.push(`Rule ${esc(x.code)} wording changed: version ${x.from??'?'} to ${x.to??'?'} (the wording is shown as evidence and does not change what is detected)`));
  return `<div class="u-gap"><h3 id="cmp-h">Before and after</h3>
    <p class="meta">Comparing ${esc(c.before.label||'run '+c.before.id)} (${when(c.before.created_at)}) with ${esc(c.after.label||'run '+c.after.id)} (${when(c.after.created_at)}).</p>
    <table class="bm-table" aria-labelledby="cmp-h"><thead><tr><th scope="col"><span class="sr-only">Run</span></th><th scope="col">Precision</th><th scope="col">Recall</th></tr></thead><tbody>
      ${metricRow('Before change',a)}${metricRow('After change',b)}
      <tr class="bm-delta"><th scope="row">Change</th><td>${trend(dl.precision)} (${pts(dl.precision)})</td><td>${trend(dl.recall)} (${pts(dl.recall)})</td></tr></tbody></table>
    <div class="u-gap"><h3>What changed in your knowledge base</h3>
      ${items.length?`<ul class="timeline u-mt">${items.map(i=>`<li>${i}</li>`).join('')}</ul>`:'<p class="small muted">Nothing the checks depend on changed between these two runs.</p>'}</div>
    ${c.cases_changed.length?`<details class="u-gap"><summary>${plural(c.cases_changed.length,'case')} changed result</summary><ul class="timeline u-mt">${c.cases_changed.map(x=>`<li><b>${esc(x.title)}</b>: missed ${x.before.fn} → ${x.after.fn}, false alarms ${x.before.fp} → ${x.after.fp}</li>`).join('')}</ul></details>`:''}</div>`}
function rulesCard(run,cmp){
  const rows=Object.entries(run.per_rule),was=cmp?cmp.rules:{};
  const cell=(v,old)=>`${pct(v)}${cmp&&old&&old.before?`<span class="meta"> was ${pct(old.before[old.k])}</span>`:''}`;
  return `<section class="card" aria-labelledby="pr-h"><h2 id="pr-h">Accuracy by rule</h2><p class="muted small">Which rules or facts the misses and false alarms come from.</p>
    <table class="stack-rows bm-table u-gap"><thead><tr><th scope="col">Rule or fact</th><th scope="col">Precision</th><th scope="col">Recall</th><th scope="col">Caught</th><th scope="col">Missed</th><th scope="col">False alarms</th></tr></thead><tbody>
    ${rows.map(([code,v])=>{const w=was[code];return `<tr><td data-label="Rule or fact">${rname(code)}</td>
      <td data-label="Precision">${cell(v.precision,w&&{before:w.before,k:'precision'})}</td><td data-label="Recall">${cell(v.recall,w&&{before:w.before,k:'recall'})}</td>
      <td data-label="Caught">${v.tp}</td><td data-label="Missed">${v.fn?`<span class="chip danger">${v.fn}</span>`:0}</td><td data-label="False alarms">${v.fp?`<span class="chip warning">${v.fp}</span>`:0}</td></tr>`}).join('')}
    </tbody></table></section>`;
}
function fixCard(run){
  const have=new Set((BMKB.glossary||[]).map(g=>g.term.toLowerCase()));
  const items=run.per_case.filter(c=>c.fn||c.fp);
  if(!items.length)return `<section class="card" aria-labelledby="fx-h"><h2 id="fx-h">What to improve</h2><div class="notice ok u-gap"><span aria-hidden="true">✓</span><span>Every case matched what you expected.</span></div></section>`;
  const rule=code=>/^G-/.test(code);
  return `<section class="card" aria-labelledby="fx-h"><h2 id="fx-h">What to improve</h2>
    <p class="muted small">Cases where the result did not match what you expected. Add a glossary term for a missed word, then run the benchmark again.</p>
    <ul class="flist u-gap">${items.map(c=>`<li class="insight"><div class="insight-head"><h3>${esc(c.title)}</h3></div>
      ${c.missed.map(m=>`<div class="bm-issue"><span class="chip danger">Missed</span> <span>${rname(m.source_id)}${m.text?` · “${esc(m.text)}”`:''}</span>
        ${rule(m.source_id)&&m.text&&!have.has(m.text.toLowerCase())&&BMKB.glossary.some(g=>g.rule_code===m.source_id)?`<button class="btn sm" type="button" data-c="bmAddTerm" data-a='${esc(JSON.stringify([m.source_id,m.text]))}' aria-label="Add ${esc(m.text)} to the glossary">Add to glossary</button>`:''}</div>`).join('')}
      ${c.extra.map(x=>`<div class="bm-issue"><span class="chip warning">False alarm</span> <span>${rname(x.source_id)} flagged “${esc(x.text)}”, which you did not expect.</span></div>`).join('')}</li>`).join('')}</ul></section>`;
}
function runsCard(d){
  if(d.runs.length<2)return d.runs.length?`<section class="card" aria-labelledby="rh-h"><h2 id="rh-h">Run history</h2><p class="muted small">Run the benchmark again to compare results.</p></section>`:'';
  const opt=(sel)=>d.runs.map(r=>`<option value="${r.id}"${r.id===sel?' selected':''}>${esc(r.label||'Run '+r.id)} · ${when(r.created_at)} · P ${pct(r.summary.precision)} R ${pct(r.summary.recall)}</option>`).join('');
  return `<section class="card" aria-labelledby="rh-h"><h2 id="rh-h">Compare runs</h2>
    <form id="bm-pick" class="row u-gap"><div class="field"><label for="bm-before">Before</label><select id="bm-before">${opt(BMSEL.before)}</select></div>
      <div class="field"><label for="bm-after">After</label><select id="bm-after">${opt(BMSEL.after)}</select></div>
      <button class="btn" type="submit">Compare</button></form></section>`;
}
function casesCard(d){
  return `<section class="card" aria-labelledby="cs-h"><div class="card-head"><h2 id="cs-h">Benchmark cases (${d.cases.length})</h2><button class="btn sm" type="button" data-c="bmAddCase">Add a case</button></div>
    <p class="muted small">Each case lists the problems that should be found. A case with none expects clean text.</p>
    <div class="kb-list u-gap">${d.cases.map(c=>`<div class="kb-row"><div></div><div><h3>${esc(c.title)}</h3><p class="small muted bm-body">${esc(c.body.length>160?c.body.slice(0,157)+'…':c.body)}</p>
      <div class="kb-meta">${c.expected.length?c.expected.map(e=>`<span class="chip">${esc(e.source_id)}${e.text?' · '+esc(e.text):''}</span>`).join(''):'<span class="chip success">Expect no findings</span>'}${c.images.length?`<span class="chip">${plural(c.images.length,'image')}</span>`:''}</div></div>
      <div class="kb-actions"><button class="btn sm bad" type="button" data-id="${c.id}" data-t="${esc(c.title)}" data-c="bmDelCase" aria-label="Delete case ${esc(c.title)}">Delete</button></div></div>`).join('')}</div></section>`;
}
document.addEventListener('submit',e=>{
  if(e.target.id!=='bm-pick')return;e.preventDefault();
  const b=+$('#bm-before').value,a=+$('#bm-after').value;
  if(b===a){toast('Choose two different runs to compare.',true);return}
  BMSEL={before:b,after:a};run(renderBenchmark)});

/* ------------------------------------------------------------ actions */
const bmRun=()=>run(async()=>{
  const st=$('#bm-status'),b=$('#bm-run');if(st)st.classList.remove('hidden');if(b)b.disabled=true;
  try{const r=await api('/api/benchmark/run',{json:{}});BMSEL=null;
    toast(`Benchmark completed. Precision ${pct(r.summary.precision)}, recall ${pct(r.summary.recall)}.`);await renderBenchmark();focusMain()}
  finally{const b2=$('#bm-run');if(b2)b2.disabled=false;const s2=$('#bm-status');if(s2)s2.classList.add('hidden')}});
const bmSeed=()=>run(async()=>{const r=await api('/api/benchmark/seed',{json:{}});toast(r.added?`Loaded ${r.added} demo cases.`:'The demo cases are already loaded.');await renderBenchmark()});
const bmDelCase=b=>run(async()=>{
  const ok=await confirmDialog({title:'Delete this case?',note:b.dataset.t,consequence:'Past runs keep their results. Future runs will no longer include this case.',ok:'Delete case',danger:true,
    onSubmit:()=>api('/api/benchmark/cases/'+b.dataset.id,{method:'DELETE'})});
  if(ok){toast('Case deleted.');await renderBenchmark()}});
function parseExpected(text){
  return text.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>{const [id,...rest]=l.split('|');return {source_id:id.trim(),text:rest.join('|').trim()}})}
const bmAddCase=()=>run(async()=>{
  const ok=await askDialog({title:'Add a benchmark case',note:'Paste a short text and list the problems that should be found in it.',ok:'Add case',
    fields:[{id:'title',label:'Case name'},{id:'body',label:'Text to check',type:'textarea',rows:4},
      {id:'exp',label:'Expected findings (optional)',type:'textarea',rows:3,optional:true,hint:'One per line, as RULE | text. For example: G-03 | cheap. Leave empty if the text should be clean.'}],
    onSubmit:v=>api('/api/benchmark/cases',{json:{cases:[{title:v.title,body:v.body,images:[],expected:parseExpected(v.exp)}]}})});
  if(ok){toast('Case added. Run the benchmark to include it.');await renderBenchmark()}});
const bmAddTerm=(code,text)=>run(async()=>{
  const ok=await askDialog({title:'Add a glossary term',note:`BrandGuard missed “${text}”. Adding it makes the checks flag it under rule ${code}.`,
    consequence:'This changes the live checks for every review, not just the benchmark. Run the benchmark again to see the effect.',ok:'Add term',
    fields:[{id:'term',label:'Term to flag',value:text},{id:'preferred',label:'Preferred wording',hint:'What authors should write instead.'},
      {id:'kind',label:'Type',type:'select',value:'slang',options:[['slang','Slang'],['banned','Banned word']]}],
    onSubmit:async v=>{const fd=new FormData();fd.append('kind','glossary');
      fd.append('text',JSON.stringify([{term:v.term.trim(),preferred:v.preferred.trim(),kind:v.kind,rule_code:code}]));
      await api('/api/kb/import',{method:'POST',body:fd})}});
  if(ok){toast('Term added. Run the benchmark again to see the effect.');await renderBenchmark()}});
