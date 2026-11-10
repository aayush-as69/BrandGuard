/* The public front page: what BrandGuard is, how a review goes, and where to sign in. */
function landing(note){
  const demo=AUTH!=='accounts';
  const cta=demo
    ?'<button class="btn primary" data-c="tourStart">Take the 2-minute tour</button><button class="btn" data-c="focusSignin">Pick a demo user</button>'
    :'<button class="btn primary" data-c="focusSignin">Sign in</button>';
  $('#main').innerHTML=`<div class="landing">
  ${note?`<p class="small muted" role="status">${esc(note)}</p>`:''}
  <section class="hero">
    <div>
      <h2 class="hero-h">Catch brand mistakes before they go live.</h2>
      <p class="hero-p">BrandGuard checks a draft against your approved guidelines. Every finding quotes the rule it comes from, and a person makes the final call.</p>
      <p class="row">${cta}</p>
      ${demo?'<p class="small muted">The demo uses synthetic data for a fictional brand, Brewline Coffee.</p>':''}
    </div>
    <figure class="sample" aria-label="Example of a reviewed draft">
      <figcaption class="small muted">Example</figcaption>
      <p class="proof">Meet our new cold brew: <mark class="high">guaranteed the best coffee in India</mark>, now at a price you'll love.</p>
      <div class="found high">
        <span class="chip high">High</span> <b>Unsupported claim</b>
        <p class="small">"Guaranteed the best" cannot be proven.</p>
        <p class="small muted">From the guideline: "Do not make superlative claims we cannot back up."</p>
        <p class="small row"><span class="chip">Suggested fix</span> <span>"a cold brew we're proud of"</span></p>
      </div>
    </figure>
  </section>
  <section aria-labelledby="how-h">
    <h3 id="how-h" class="sec-h">How a review goes</h3>
    <ol class="steps">
      <li><b>Write or paste a draft</b><span class="muted">Add the text and any images, then run the review.</span></li>
      <li><b>See what needs a look</b><span class="muted">Findings are marked in the text, each with the guideline it came from.</span></li>
      <li><b>Decide, then approve</b><span class="muted">Accept, edit or dismiss each finding. A manager or reviewer approves. Every step is recorded.</span></li>
    </ol>
  </section>
  <section class="feats" aria-label="What you get">
    <div class="card"><h3>Evidence for every finding</h3><p class="muted small">A finding without a source rule is not shown. You can always see which guideline or fact it rests on.</p></div>
    <div class="card"><h3>Rules first, AI second</h3><p class="muted small">Clear rules run on their own. The optional AI check only looks at tone, sees masked text, and is verified against the rules before it appears.</p></div>
    <div class="card"><h3>People stay in charge</h3><p class="muted small">Nothing is approved automatically. Risky dismissals need a reviewer, and the audit trail shows who decided what.</p></div>
    <div class="card"><h3>Access by role</h3><p class="muted small">Public, internal and confidential material is shown only to people cleared for it. Agency writers see only their own work.</p></div>
  </section>
  </div>`}
function focusSignin(){const el=AUTH==='accounts'?$('#email'):$('#who');if(el){el.scrollIntoView({block:'nearest'});el.focus()}}
