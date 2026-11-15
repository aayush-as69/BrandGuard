/* Insights screen: what the decisions say about the rules, and what to do about it */
const goTab=t=>{TAB=t;CUR=null;DETAIL=null;SEL=null;markNav();render().then(focusMain)};
function ruleAdvice(r){
  const pct=Math.round(r.dismissal_rate*100);
  if(r.dismissal_rate>=.65)return `Most people dismiss this rule (${pct}%). Consider narrowing it, or adding a clearer example of what is and is not allowed.`;
  return `About half of the decisions on this rule are dismissals. Check that its wording is clear and current, and add an example if it is not.`}
async function renderInsights(){
  const rid=++RID;let d;
  try{d=await api('/api/insights')}catch(e){if(rid!==RID)return;$('#main').innerHTML=errorCard('We couldn’t load insights',e.message);return}
  if(rid!==RID)return;
  const c=d.content,top=Math.max(1,...d.rules.map(r=>r.flagged));
  const tile=(n,l,alert)=>`<div class="tile${alert&&n?' alert':''}"><b>${esc(n)}</b><span>${esc(l)}</span></div>`;
  const disputed=d.rules.filter(r=>r.often_disputed);
  const ranked=[...d.rules].sort((a,b)=>b.flagged-a.flagged);
  const lead=ranked[0];
  const head=pageHead('Decision intelligence','Insights','See where content repeatedly needs attention and where your rules may need refinement.','<span class="chip">Counted from real decisions</span>');
  if(!c.total){
    $('#main').innerHTML=head+`<div class="card empty-state"><div class="empty-icon" aria-hidden="true">▤</div><h2>No insights yet</h2><p class="muted">Insights appear once content has been reviewed and findings have been decided. Review a draft to start.</p><button class="btn primary" type="button" data-c="goTab" data-a='["content"]'>Go to content</button></div>`;return}
  $('#main').innerHTML=head+`<div class="stack">
   <section class="card" aria-labelledby="ov-h"><h2 id="ov-h">Overview</h2><p class="muted small">Counted from real decisions. It never names a person.</p>
    <div class="tiles u-gap">${tile(c.total,'pieces of content')}${tile(c.approved,'approved')}${tile(c.in_review,'waiting for review',true)}
     ${tile(d.changes_requested,'changes requested',true)}${tile(d.avg_hours_to_approve==null?'n/a':d.avg_hours_to_approve+' h','average time to approval')}</div></section>
   <section class="card" aria-labelledby="rh-h"><h2 id="rh-h">Rules to refine</h2>
    <p class="muted small">Rules where at least half of the decisions were dismissals, with at least two decisions. Dismissing is allowed, but a pattern suggests the rule is unclear, outdated or too strict.</p>
    <div class="stack u-gap">${disputed.length?disputed.map(r=>`<article class="insight"><div class="insight-head"><code>${esc(r.code)}</code><h3>${esc(r.title)}</h3></div>
       <div class="insight-stats"><span>Triggered <b>${r.flagged}</b> times</span><span>Dismissed <b>${r.dismissed}</b> times</span><span>Fixed <b>${r.fixed}</b> times</span><span>Dismiss rate <b>${Math.round(r.dismissal_rate*100)}%</b></span></div>
       <div class="evidence"><div class="evidence-src">Rule text</div><blockquote>${esc(r.quote)}</blockquote></div>
       <div class="insight-rec"><b>Recommendation.</b> ${ruleAdvice(r)}</div></article>`).join('')
     :`<div class="notice ok"><span aria-hidden="true">✓</span><span>No rule is being disputed often. Either the rules are clear, or there are not enough decisions yet.</span></div>`}</div></section>
   <section class="card" aria-labelledby="rm-h"><h2 id="rm-h">Repeated mistakes</h2>
    <p class="muted small">How often each rule or fact flagged a first draft.${lead&&lead.flagged?` The most repeated is <b>${esc(lead.title)}</b> (${esc(lead.code)}), flagged ${lead.flagged} times. Clearer examples or a short briefing for authors may help.`:''}</p>
    ${d.rules.length?`<div class="u-gap">${ranked.map(r=>`<div class="rule-bar"><code>${esc(r.code)}</code><span><b>${esc(r.title)}</b></span>
      <div class="meter" role="img" aria-label="${r.flagged} flags"><i data-w="${Math.round(100*r.flagged/top)}"></i></div><span class="small">${r.flagged} flagged · ${r.fixed} fixed · ${r.dismissed} dismissed</span></div>`).join('')}</div>`
      :'<p class="muted small">No findings yet. Review some content first.</p>'}</section>
   <section class="card" aria-labelledby="ai-h"><h2 id="ai-h">AI suggestions</h2>
    <p class="small u-gap">${d.ai.suggested?`${d.ai.suggested} decided: ${d.ai.accepted} accepted or edited, ${d.ai.dismissed} dismissed.`:'No AI suggestions have been decided yet.'}</p></section></div>`}
