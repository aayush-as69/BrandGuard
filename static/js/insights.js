/* Insights screen */
/* ------------------------------------------------------------ insights */
async function renderInsights(){
  const rid=++RID;let d;
  try{d=await api('/api/insights')}catch(e){if(rid!==RID)return;$('#main').innerHTML=`<div class="card"><h2>Insights</h2><p class="muted">${esc(e.message)}</p></div>`;return}
  if(rid!==RID)return;
  const c=d.content,top=Math.max(1,...d.rules.map(r=>r.flagged));
  const tile=(n,l)=>`<div class="tile"><b>${esc(n)}</b><span class="muted small">${esc(l)}</span></div>`;
  const disputed=d.rules.filter(r=>r.often_disputed);
  $('#main').innerHTML=`<div class="page-head"><div><div class="eyebrow">DECISION INTELLIGENCE</div><h2>Insights</h2><p>See where content repeatedly needs attention and where your rules may need refinement.</p></div><span class="chip ai">Live from decisions</span></div><div class="stack">
   <div class="card"><div class="section-kicker">OVERVIEW</div><h2>Guideline insights</h2>
    <p class="muted small">What authors trip over and which rules people dispute, counted from real decisions. It never names a person.</p>
    <div class="tiles">${tile(c.total,'pieces of content')}${tile(c.approved,'approved')}${tile(c.in_review,'waiting for review')}
     ${tile(d.changes_requested,'changes requested')}${tile(d.avg_hours_to_approve==null?'n/a':d.avg_hours_to_approve+' h','average time to approval')}</div></div>
   <div class="card"><div class="section-kicker">PATTERNS</div><h2>Repeated mistakes</h2>
    <p class="muted small">How often each rule or fact flagged a first draft. Rules that keep repeating may need clearer wording or training.</p>
    ${d.rules.length?`<table>${d.rules.map(r=>`<tr><td><code>${esc(r.code)}</code></td><td><b>${esc(r.title)}</b></td>
      <td class="u-w35"><div class="meter" role="img" aria-label="${r.flagged} flags"><i data-w="${Math.round(100*r.flagged/top)}"></i></div></td>
      <td>${r.flagged}</td></tr>`).join('')}</table>`:'<p class="muted small">No findings yet. Review some content first.</p>'}</div>
   <div class="card"><div class="section-kicker">RULE HEALTH</div><h2>Often disputed</h2>
    <p class="muted small">Rules where at least half of the decisions were dismissals (with at least 2 decisions). Dismissing is allowed, but a pattern suggests the rule is unclear, outdated or too strict.</p>
    ${disputed.length?disputed.map(r=>`<div class="u-cursor-default item"><p><code>${esc(r.code)}</code> <b>${esc(r.title)}</b>
       <span class="chip medium">${Math.round(r.dismissal_rate*100)}% dismissed</span></p>
       <p class="small muted">${r.dismissed} dismissed, ${r.fixed} fixed. Rule text: ${esc(r.quote)}</p></div>`).join('')
     :'<p class="muted small">Nothing is being disputed often. Either the rules are clear, or there is not enough data yet.</p>'}</div>
   <div class="card"><div class="section-kicker">ASSISTED REVIEW</div><h2>AI suggestions</h2>
    <p class="small">${d.ai.suggested?`${d.ai.suggested} decided: ${d.ai.accepted} accepted or edited, ${d.ai.dismissed} dismissed.`:'No AI suggestions have been decided yet.'}</p></div></div>`}

