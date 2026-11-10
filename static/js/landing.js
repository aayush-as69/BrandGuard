/* Public BrandGuard experience. Keep demo and account actions connected to the existing app. */
function landing(note){
  const demo=AUTH!=='accounts';
  const cta=demo
    ? '<button class="btn primary" data-c="tourStart">Take the 2-minute tour <span aria-hidden="true">↗</span></button><button class="btn landing-secondary" data-c="focusSignin">Choose a demo role</button>'
    : '<button class="btn primary" data-c="focusSignin">Sign in to BrandGuard <span aria-hidden="true">↗</span></button>';
  $('#main').innerHTML=`<div class="landing">
    ${note?`<p class="landing-notice" role="status">${esc(note)}</p>`:''}
    <section class="landing-hero" aria-labelledby="landing-title">
      <div class="hero-copy">
        <div class="eyebrow"><span class="eyebrow-dot"></span> BRAND GOVERNANCE, BUILT FOR REAL WORK</div>
        <h2 id="landing-title" class="hero-h">Make every piece of content <span>feel unmistakably yours.</span></h2>
        <p class="hero-p">A clearer way to protect your brand. Review every draft against approved guidelines, trace decisions back to evidence, and keep people in control.</p>
        <div class="hero-actions">${cta}</div>
        <div class="hero-assurance"><span class="assurance-icon">✓</span> Evidence-backed reviews <i></i><span>Human approval stays final</span></div>
        ${demo?'<p class="demo-note">You are viewing a safe demo workspace with fictional Brewline Coffee content.</p>':''}
      </div>

      <div class="review-stage" aria-label="Illustration of a BrandGuard content review">
        <div class="stage-orbit orbit-one"></div><div class="stage-orbit orbit-two"></div>
        <div class="review-window">
          <div class="window-top"><div class="window-brand"><img src="/static/brandguard-mark.svg" alt="" width="22" height="22"><span>BRANDGUARD</span></div><span class="window-live"><b></b> REVIEW PREVIEW</span><span class="window-dots">•••</span></div>
          <div class="window-body">
            <div class="window-heading"><div><span class="window-kicker">CAMPAIGN / 024</span><h3>Summer launch email</h3><p>Draft review · Marketing team</p></div><span class="status-pill">Needs attention</span></div>
            <div class="preview-label">CONTENT PREVIEW <span>EMAIL COPY</span></div>
            <div class="draft-paper">
              <div class="paper-brand"><span class="paper-mark">b.</span> brewline <span class="paper-type">COFFEE CO.</span></div>
              <p class="paper-subject">A better kind of afternoon.</p>
              <p>Meet your new summer ritual. Our slow-steeped cold brew is here to make the everyday feel a little more extraordinary.</p>
              <p>It's <mark class="flagged-phrase">the best coffee in India</mark> — and it's waiting for you.</p>
              <div class="paper-footer">BREWED WITH INTENTION · EST. 2018</div>
            </div>
            <div class="finding-panel">
              <div class="finding-top"><span class="finding-symbol">!</span><div><b>Unsupported superlative</b><small>Brand voice · Claim substantiation</small></div><span class="finding-level">HIGH</span></div>
              <p>“Best coffee in India” has no approved supporting evidence.</p>
              <div class="evidence-line"><span>↳</span><span><b>Source rule</b> · Avoid unverified superiority claims.</span></div>
              <div class="suggestion"><span>Suggested alternative</span><b>“A cold brew worth slowing down for.”</b></div>
            </div>
            <div class="window-bottom"><span><b>01</b> finding identified</span><span>Evidence linked <b class="linked-check">✓</b></span></div>
          </div>
        </div>
        <div class="stage-float float-evidence"><span class="float-icon">⌁</span><span><b>Traceable by design</b><small>Every finding has a source</small></span></div>
        <div class="stage-float float-human"><span class="float-icon human-icon">✓</span><span><b>Human decision</b><small>Nothing auto-approves</small></span></div>
      </div>
      <div class="hero-index"><span>01</span><i></i> FROM FIRST DRAFT TO FINAL APPROVAL</div>
    </section>

    <section class="trust-strip" aria-label="BrandGuard principles">
      <span class="trust-intro">BUILT AROUND THE RIGHT PRINCIPLES</span>
      <div><b class="trust-check">✓</b><span>Approved sources</span></div><div><b class="trust-check">✓</b><span>Explainable findings</span></div><div><b class="trust-check">✓</b><span>Human accountability</span></div><div><b class="trust-check">✓</b><span>Role-aware access</span></div>
    </section>

    <section class="story-section" aria-labelledby="story-title">
      <div class="section-intro"><div class="eyebrow">A REVIEW PROCESS YOU CAN TRUST</div><h3 id="story-title">From “does this sound right?”<br><span>to “we know why it is right.”</span></h3><p>Brand consistency should not depend on who happens to review a draft. BrandGuard gives teams a shared, evidence-led process.</p></div>
      <div class="process-list">
        <article class="process-step"><span class="process-number">01</span><div><h4>Ground every review in your rules.</h4><p>Use an approved knowledge base of guidelines, facts, terminology and assets as the source of truth.</p></div><span class="process-arrow">↗</span></article>
        <article class="process-step"><span class="process-number">02</span><div><h4>See the issue and the evidence.</h4><p>Findings point to the source behind them, with context and practical suggestions for what to change.</p></div><span class="process-arrow">↗</span></article>
        <article class="process-step"><span class="process-number">03</span><div><h4>Keep the final call with people.</h4><p>Reviewers resolve decisions, managers approve work, and the audit trail records what happened.</p></div><span class="process-arrow">↗</span></article>
      </div>
    </section>

    <section class="capability-section" aria-labelledby="capability-title">
      <div class="capability-heading"><div><div class="eyebrow">MORE THAN A SPELLCHECK</div><h3 id="capability-title">Guardrails for the whole<br><span>content lifecycle.</span></h3></div><p>Built to make brand standards useful in daily work—not another document people forget to open.</p></div>
      <div class="capability-grid">
        <article class="capability-card capability-featured"><span class="capability-icon">⌕</span><span class="capability-label">01 / EVIDENCE</span><h4>Every finding has a reason.</h4><p>See the approved rule or fact behind a flag. No mystery scores or unsupported warnings.</p><span class="capability-motif">↗</span></article>
        <article class="capability-card"><span class="capability-icon">✳</span><span class="capability-label">02 / INTELLIGENCE</span><h4>Rules first. AI with boundaries.</h4><p>Deterministic checks handle clear rules. Optional AI assists with tone while respecting privacy controls.</p></article>
        <article class="capability-card"><span class="capability-icon">◎</span><span class="capability-label">03 / ACCOUNTABILITY</span><h4>People stay responsible.</h4><p>Role-based decisions and explicit approvals keep important brand calls in human hands.</p></article>
        <article class="capability-card"><span class="capability-icon">⌘</span><span class="capability-label">04 / CONTROL</span><h4>The right access, by design.</h4><p>Keep internal and confidential material limited to the people cleared to see it.</p></article>
      </div>
    </section>

    <section class="closing-panel"><div><div class="eyebrow">BETTER REVIEWS. STRONGER BRANDS.</div><h3>Give every draft<br><span>a standard to live up to.</span></h3><p>Bring your guidelines, content and people into one accountable review flow.</p></div><div class="closing-action">${demo?'<button class="btn primary" data-c="tourStart">Explore BrandGuard <span aria-hidden="true">↗</span></button>':'<button class="btn primary" data-c="focusSignin">Continue to sign in <span aria-hidden="true">↗</span></button>'}<span>Clear standards. Confident decisions.</span></div></section>
    <footer class="landing-footer"><span><img src="/static/brandguard-mark.svg" alt="" width="20" height="20"> BrandGuard</span><span>Brand integrity, made actionable.</span><span>BUILT FOR CLEARER DECISIONS</span></footer>
  </div>`;
}
function focusSignin(){const el=AUTH==='accounts'?$('#email'):$('#who');if(el){el.scrollIntoView({block:'nearest',behavior:'smooth'});el.focus()}}
