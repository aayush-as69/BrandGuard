/* Public BrandGuard experience. Keep demo and account actions connected to the existing app. */
function landing(note){
  const demo=AUTH!=='accounts';
  const cta=demo
    ? '<div class="demo-login"><div class="demo-login-head"><span class="kicker">Demo workspace</span><span class="meta">Fictional Brewline Coffee content</span></div><div class="demo-login-row"><input id="demo-pass" type="password" class="demo-pass" placeholder="Demo passcode" aria-label="Demo passcode" autocomplete="off"><button class="btn primary" type="button" data-c="demoLogin">Enter demo</button></div><p class="demo-role-note">Starts as the brand manager. Use the role switch in the top bar to try writer, reviewer and admin views.</p></div>'
    : `<button class="btn primary" type="button" data-c="${DEMO.available?'demoFill':'goLogin'}">${DEMO.available?'Try demo':'Sign in'}</button>${DEMO.available?'<button class="btn" type="button" data-c="goLogin">Sign in</button>':''}`;
  const step=(t,d)=>`<li><b>${t}</b>${d}</li>`;
  const catches=(t,d,ex)=>`<article class="card"><h3>${t}</h3><p>${d}</p><p class="ex">${ex}</p></article>`;
  const trust=(t,d)=>`<article class="card"><h3>${t}</h3><p>${d}</p></article>`;
  $('#main').innerHTML=`<div class="landing">
    ${note?`<p class="notice info landing-notice" role="status">${esc(note)}</p>`:''}
    <section class="hero" aria-labelledby="landing-title">
      <div>
        <div class="kicker">Brand governance for content teams</div>
        <h1 id="landing-title">Check content before it goes live.</h1>
        <p class="hero-p">Review against approved brand guidelines, facts and assets, with evidence behind every finding. People make the final decision.</p>
        <div class="hero-actions">${cta}</div>
        <p class="hero-sub">For brand, marketing and agency teams who need every draft held to the same standard.</p>
      </div>
      <div class="preview" role="img" aria-label="Illustration: a draft email with one flagged claim, the guideline quoted as evidence, and a suggested fix.">
        <div class="preview-bar"><span>Summer launch email · Brewline Coffee (fictional)</span><span class="chip changes_requested">1 finding needs a decision</span></div>
        <div class="preview-body">
          <div class="paper"><b>A better kind of afternoon.</b>Meet your new summer ritual. It’s <span class="flag">the best coffee in India</span> and it’s waiting for you.</div>
          <div class="f-step"><span class="f-label">Finding</span><div class="row">${sev('high')}<span class="f-why">Unsupported claim</span></div></div>
          <div class="evidence"><div class="evidence-src"><span class="chip">Guideline G-04</span><span class="muted">Claims</span></div>
            <blockquote>Every comparative, superlative, ranking or numeric claim must match an approved fact in the fact sheet.</blockquote></div>
          <div class="diff"><div class="diff-row"><span class="diff-tag">Original</span><span><del>the best coffee in India</del></span></div>
            <div class="diff-row"><span class="diff-tag">Proposed</span><span><ins>a cold brew worth slowing down for</ins></span></div></div>
        </div>
      </div>
    </section>

    <section aria-labelledby="how-title">
      <div class="section-head"><div class="kicker">How it works</div><h2 id="how-title">From first draft to final approval, with the reasoning visible.</h2></div>
      <ol class="flow">
        ${step('Draft','Paste an email, post or page, with its images.')}
        ${step('Finding','Rules and approved facts flag the problem, with severity and confidence.')}
        ${step('Evidence','The exact guideline or fact is quoted beside the flagged text.')}
        ${step('Suggested fix','Compare the change. Nothing is applied until a person accepts it.')}
        ${step('Approval','A different person approves. Every step lands in the audit trail.')}
      </ol>
    </section>

    <section aria-labelledby="catch-title">
      <div class="section-head"><div class="kicker">What it prevents</div><h2 id="catch-title">The mistakes that slip through manual review.</h2><p>Checked against your own guidelines and approved facts. Examples below come from the fictional Brewline demo.</p></div>
      <div class="cards">
        ${catches('Unsupported claims','Rankings and superlatives with no approved source.','“India’s #1 coffee”')}
        ${catches('Wrong facts','Prices and dates that differ from the approved fact sheet.','₹399 on the page, ₹449 approved')}
        ${catches('Off-brand language','Banned terms, slang, hype and too many exclamation marks.','“cheap” becomes “affordable”')}
        ${catches('Inaccessible images','Missing alt text and low-contrast text on images.','Contrast 2.8:1, minimum 4.5:1')}
      </div>
    </section>

    <section aria-labelledby="trust-title">
      <div class="section-head"><div class="kicker">Why teams can trust it</div><h2 id="trust-title">Evidence first. Human control throughout.</h2></div>
      <div class="cards">
        ${trust('Every finding cites its source','The rule or approved fact behind a flag is quoted. No unexplained scores.')}
        ${trust('Rules first, AI optional','Deterministic checks run first. Optional AI review is masked, must quote a real rule, and is never applied automatically.')}
        ${trust('People decide','Authors accept, edit or dismiss each fix. Nobody approves their own work.')}
        ${trust('Access by role','Confidential facts stay hidden from outside agencies, and every decision is recorded.')}
      </div>
    </section>

    <section class="closing" aria-labelledby="close-title">
      <div><h2 id="close-title">See a review from start to finish.</h2><p class="muted">${demo?'Take the two-minute guided tour of the demo workspace.':'Sign in with the account your administrator created.'}</p></div>
      ${demo?'<button class="btn primary" type="button" data-c="tourStart">Take the guided tour</button>':'<button class="btn primary" type="button" data-c="focusSignin">Sign in</button>'}
    </section>
    <footer class="landing-footer"><span><img src="/static/brandguard-mark.svg" alt="" width="20" height="20"> BrandGuard</span><span>Evidence-backed brand governance with human control.</span></footer>
  </div>`;
}
async function demoLogin(){
  if(AUTH==='accounts'){goLogin();return}
  const pass=$('#demo-pass')?.value||'';
  try{ME=await api('/api/login',{json:{user_id:2,passcode:pass}});CUR=null;DETAIL=null;SEL=null;KBDATA=null;afterLogin().then(focusMain)}
  catch(e){toast(e.message,true);$('#demo-pass')?.focus()}
}
function focusSignin(){
  if(AUTH==='accounts'){goLogin();return}
  const el=$('#demo-pass');if(el){el.scrollIntoView({block:'center',behavior:'smooth'});el.focus()}
}
function demoFill(){
  if(!DEMO.available){toast('Demo login is not configured.',true);return}
  history.pushState({},'','/login');loginView();
  $('#email').value=DEMO.email;
  $('#password').value=DEMO.password;
  $('#email').focus();
}

/* Public screens in accounts mode: the front page at "/" and a separate sign-in page at "/login". */
function showPublic(note){
  if(AUTH==='accounts'&&location.pathname==='/login')loginView(note);
  else{if(location.pathname!=='/')history.replaceState({},'','/');document.title='BrandGuard';landing(note)}}
function goLogin(){
  if(AUTH!=='accounts'){focusSignin();return}
  history.pushState({},'','/login');loginView()}
function goHome(){history.pushState({},'','/');document.title='BrandGuard';landing()}
/* The brand mark in the header always means "back to my starting point". */
function brandHome(){
  if(ME){TAB='content';CUR=null;DETAIL=null;SEL=null;markNav();render().then(focusMain);return}
  if(AUTH==='accounts')goHome();else landing()}
function togglePw(){
  const i=$('#password'),b=$('#pw-toggle'),show=i.type==='password';
  i.type=show?'text':'password';b.textContent=show?'Hide':'Show';b.setAttribute('aria-pressed',String(show));
  b.setAttribute('aria-label',show?'Hide password':'Show password')}
function loginView(note){
  document.title='Sign in · BrandGuard';
  $('#main').innerHTML=`<div class="login-wrap"><section class="login-card" aria-labelledby="login-h">
    <div class="login-brand"><img src="/static/brandguard-mark.svg" width="36" height="36" alt=""><span class="kicker">BrandGuard</span></div>
    <h1 id="login-h">Sign in to BrandGuard</h1>
    <p class="muted small">Use the work email and password your administrator gave you.</p>
    ${note?`<p class="notice info" role="status">${esc(note)}</p>`:''}
    <form id="signin" autocomplete="on" novalidate>
      <label for="email">Email</label>
      <input type="email" id="email" autocomplete="username" aria-describedby="login-err">
      <label for="password">Password</label>
      <div class="pw-wrap"><input type="password" id="password" autocomplete="current-password" aria-describedby="login-err">
        <button class="btn" type="button" id="pw-toggle" data-c="togglePw" aria-pressed="false" aria-label="Show password">Show</button></div>
      <div id="code-row" class="hidden"><label for="code">6-digit code from your authenticator app</label>
        <input type="text" id="code" inputmode="numeric" pattern="[0-9 ]*" autocomplete="one-time-code" aria-describedby="login-err"></div>
      <p id="login-err" class="login-err" role="alert"></p>
      <button class="btn primary login-go" type="submit">Sign in</button>
    </form>
    <p class="login-aside"><a href="/" data-c="goHome" class="login-back">Back to the home page</a></p>
  </section></div>`;
  if(DEMO.available){
    $('#signin').insertAdjacentHTML('beforebegin','<button type="button" class="btn demo-fill" data-c="demoFill">Use demo account</button>');
  }
  $('#email').focus()}
window.addEventListener('popstate',()=>{if(!ME&&AUTH==='accounts')showPublic()});
