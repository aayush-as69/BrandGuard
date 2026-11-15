/* Quality screen: how accurate the checks are (labelled benchmark) and what the guidelines could learn from decisions */
const pct=x=>x==null?'n/a':Math.round(x*100)+'%';
const signed=x=>x==null||x===0?'no change':(x>0?'+':'')+Math.round(x*1000)/10+' points';
let QP=null;
async function renderQuality(){
  const rid=++RID;let d;
  try{d=await api('/api/quality')}catch(e){if(rid!==RID)return;$('#main').innerHTML=`<div class="card"><h2>Quality</h2><p class="muted">${esc(e.message)}</p></div>`;return}
  if(rid!==RID)return;QP=d;
  if(ME&&ME.role==='admin'){
    try{d.ops=await api('/api/ops/metrics')}catch(_){d.ops=null}
  }
  drawQuality(d);
  clearTimeout(renderQuality.t);
  if(d.pending)renderQuality.t=setTimeout(()=>{if(TAB==='quality')renderQuality()},3000)}
function drawQuality(d){
  const admin=ME&&ME.role==='admin',run=d.benchmark,r=run?run.result:null,o=r?r.overall:null;
  const tile=(n,l)=>`<div class="tile"><b>${esc(n)}</b><span class="muted small">${esc(l)}</span></div>`;
  const tag={narrow:'Narrow',example:'Add an example',review:'Review'};
  const sug=d.suggestions.map((s,i)=>`<div class="item u-cursor-default"><p><span class="chip ${s.type==='review'?'high':s.type==='narrow'?'medium':'ai'}">${esc(tag[s.type]||s.type)}</span> <code>${esc(s.code)}</code> <b>${esc(s.title)}</b></p>
     <p class="small muted">${esc(s.why)}</p>
     ${s.type==='review'&&s.evidence.examples.length?`<p class="small">False alarms: ${s.evidence.examples.map(x=>`<code>${esc(x.text)}</code> <span class="muted">(${esc(x.case)})</span>`).join(', ')}</p>`:''}
     ${s.apply&&s.apply.kind==='rule_note'?`<label class="small muted" for="qn${i}">Example to add (you can edit it)</label><input type="text" id="qn${i}" maxlength="300" value="${esc(s.apply.note)}">`:''}
     ${s.apply?(admin?`<p class="u-mt8"><button class="btn primary" data-c="qualityApply" data-a='[${JSON.stringify(s.id)},${i}]'>Apply this change</button> <span class="small muted">The benchmark runs before and after, and you can undo it.</span></p>`
        :'<p class="small muted">An admin can apply this with one click.</p>'):'<p class="small muted">Needs a person to decide. Nothing is applied automatically.</p>'}</div>`).join('');
  const hist=d.changes.map(c=>`<div class="item u-cursor-default"><p><b>${esc(c.summary)}</b> <span class="small muted">${when(c.created_at)}</span>${c.reverted_at?' <span class="chip draft">undone</span>':''}</p>
     ${c.compare?`<p class="small">Precision ${pct(c.compare.precision_before)} → ${pct(c.compare.precision_after)} (${signed(c.compare.precision_change)}), recall ${pct(c.compare.recall_before)} → ${pct(c.compare.recall_after)} (${signed(c.compare.recall_change)})</p>`:''}
     ${admin&&!c.reverted_at?`<button class="btn small" data-c="qualityUndo" data-a='[${+c.id}]'>Undo</button>`:''}</div>`).join('');
  $('#main').innerHTML=`<div class="page-head"><div><div class="eyebrow">MEASURED QUALITY</div><h2>Quality</h2><p>How often the checks are right, measured on drafts where every real mistake was labelled by a person. Synthetic data only.</p></div>
     ${admin?`<div class="row"><button class="btn" data-c="qualityRun" data-a='[false]'>Run again</button>
      <button class="btn" data-c="qualityRun" data-a='[true]' ${d.ai_available&&!d.pending?'':'disabled'} title="${d.ai_available?'Sends masked synthetic drafts to your AI provider':'No AI provider is configured on this server'}">Run with AI judge</button></div>`:''}</div>
   <div class="stack">
    <div class="card"><div class="section-kicker">RESULT</div><h2>Overall accuracy</h2>
     ${d.pending?'<p class="small muted" role="status">The AI judge run is in progress. This page refreshes by itself.</p>':''}
     ${d.failed?`<p class="u-warn-m6 small">⚠ The last AI run failed: ${esc(d.failed)}</p>`:''}
     ${r?`<div class="tiles">${tile(pct(o.precision),'precision: alarms that were right')}${tile(pct(o.recall),'recall: mistakes that were found')}${tile(r.drafts,'labelled drafts')}${tile(r.labels,'labelled mistakes')}</div>
      <p class="small muted u-mt10">Run ${when(run.created_at)}. ${o.tp} found correctly, ${o.fp} false alarm${o.fp===1?'':'s'}, ${o.fn} missed. Results are for the rule-based checks${r.ai?'; the AI judge is shown separately':''}.</p>`:'<p class="muted small">No run yet.</p>'}
     ${r&&r.ai?`<div class="item u-cursor-default"><p><b>AI judge</b> <span class="chip ai">tried on ${r.ai.drafts} drafts</span></p><p class="small">Precision ${pct(r.ai.precision)}, recall ${pct(r.ai.recall)} (${r.ai.tp} right, ${r.ai.fp} false alarm${r.ai.fp===1?'':'s'}, ${r.ai.fn} missed). It only judges wording that no rule covers.</p></div>`:''}</div>
    ${r?`<div class="card"><div class="section-kicker">BY RULE</div><h2>Accuracy for each rule and fact</h2>
     <table><thead><tr><th>Rule</th><th>What it says</th><th>Precision</th><th>Recall</th><th>Right / false alarms / missed</th><th></th></tr></thead><tbody>${r.rules.map(x=>`<tr><td><code>${esc(x.code)}</code></td><td>${esc(String(x.title).slice(0,70))}</td>
      <td class="u-w35"><div class="meter" role="img" aria-label="precision ${pct(x.precision)}"><i data-w="${Math.round(100*(x.precision||0))}"></i></div> ${pct(x.precision)}</td><td>${pct(x.recall)}</td>
      <td>${x.tp} / ${x.fp} / ${x.fn}</td><td>${x.review?'<span class="chip high">review</span>':''}</td></tr>`).join('')}</tbody></table></div>
     ${r.notes.length?`<div class="card"><div class="section-kicker">WHAT WENT WRONG</div><h2>False alarms and misses</h2><p class="small muted">Every case where the checks and the labels disagree${r.notes_total>r.notes.length?` (first ${r.notes.length} of ${r.notes_total})`:''}.</p>
      <table>${r.notes.map(n=>`<tr><td><span class="chip ${n.kind==='missed'?'medium':'high'}">${n.kind==='missed'?'missed':'false alarm'}</span></td><td><code>${esc(n.code)}</code></td><td>${esc(n.text)}</td><td class="muted">${esc(n.case)} · ${esc(n.title)}</td></tr>`).join('')}</table></div>`:''}`:''}
    <div class="card"><div class="section-kicker">LEARNING LOOP</div><h2>Suggested changes to the guidelines</h2>
     <p class="small muted">Built from real review decisions (what people dismiss, what keeps repeating) and from the benchmark. It never names a person.</p>
     ${sug||'<p class="small muted">Nothing to suggest right now. Suggestions appear when the same rule is dismissed repeatedly, a mistake keeps repeating, or a rule has too many false alarms.</p>'}</div>
    <div class="card"><div class="section-kicker">HISTORY</div><h2>Changes made from suggestions</h2>${hist||'<p class="small muted">No changes yet.</p>'}</div></div>`}
function qualityRun(ai){run(async()=>{const d=await api('/api/benchmark/run',{json:{use_ai:ai}});
  toast(ai?'AI benchmark started.':'Benchmark finished.');QP=d;drawQuality(d);if(d.pending)setTimeout(()=>{if(TAB==='quality')renderQuality()},3000)})}
function qualityApply(id,i){run(async()=>{const noteEl=document.getElementById('qn'+i);
  const out=await api('/api/learning/apply',{json:{suggestion:id,note:noteEl?noteEl.value:undefined}});
  const c=out.compare;toast(`${out.summary}. Precision ${pct(c.precision_before)} → ${pct(c.precision_after)}, recall ${pct(c.recall_before)} → ${pct(c.recall_after)}.`);
  QP=out;drawQuality(out)})}
function qualityUndo(id){run(async()=>{const out=await api('/api/learning/undo',{json:{change_id:id}});
  toast('Undone: '+out.summary);QP=out;drawQuality(out)})}
