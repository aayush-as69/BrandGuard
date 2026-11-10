/* Sign-in, accounts menu, two-step sign-in, passwords, app start-up helpers */
async function boot(){
  let cfg2={};
  try{const cfg=cfg2=await api('/api/config');AUTH=cfg.auth||'demo';AICFG=cfg.ai||AICFG;DEMO={available:!!cfg.demo_available,email:cfg.demo_email||'',password:cfg.demo_password||''};$('#pass').classList.toggle('hidden',!cfg.passcode_required)}catch(e){}
  if(AUTH==='accounts'){
    document.querySelectorAll('.tour-only').forEach(x=>x.classList.add('hidden'));
    try{ME=await api('/api/me')}catch(e){ME=null}
    if(ME){history.replaceState({},'','/');afterLogin();return}
    if(cfg2.sso){try{ME=await api('/api/sso/login',{json:{}});history.replaceState({},'','/');afterLogin();return}catch(e2){}}
    accountUI();showPublic();return}
  USERS=await api('/api/users');
  $('#who').innerHTML=AUTH==='demo'
  ? '<option value="">Switch role…</option>'+USERS.map(u=>`<option value="${u.role}">${esc(u.role[0].toUpperCase()+u.role.slice(1))} · ${esc(u.name)}${u.is_external?' · agency':''}</option>`).join('')
  : '<option value="">Switch role…</option>'+USERS.map(u=>`<option value="${u.id}">${esc(u.role[0].toUpperCase()+u.role.slice(1))} · ${esc(u.name)}${u.is_external?' · agency':''}</option>`).join('');
  try{ME=await api('/api/me');$('#who').value=AUTH==='demo'?ME.role:ME.id;afterLogin()}catch(e){landing()}
}
$('#who').onchange=e=>run(async()=>{
  if(!e.target.value){await api('/api/logout',{json:{}});signedOut('Signed out. Pick a user to begin.');return}
  const prev=ME?ME.role:'';
  try{
    if(AUTH==='demo' && ME) ME=await api('/api/demo/switch-role',{json:{role:e.target.value}});
    else ME=await api('/api/login',{json:{user_id:+e.target.value,passcode:$('#pass').value}});
  }catch(err){e.target.value=prev;throw err}
  CUR=null;DETAIL=null;KBDATA=null;afterLogin()
});
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>{TAB=b.dataset.tab;
  document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x===b));render()});
function afterLogin(){
  $('#nav').classList.remove('hidden');
  // Agency users cannot browse brand material, so they get no Knowledge base tab.
  document.querySelector('#nav [data-tab=kb]').classList.toggle('hidden',!!ME.is_external);
  // Insights are about the guidelines, for the people who own them (not for authors).
  const noInsights=ME.role==='creator';
  document.querySelector('#nav [data-tab=insights]').classList.toggle('hidden',noInsights);
  if((ME.is_external&&TAB==='kb')||(noInsights&&TAB==='insights')||(TAB==='users'&&ME.role!=='admin'))TAB='content';
  document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x.dataset.tab===TAB));
  accountUI();return render()}
let AUTH='demo',AICFG={enabled:false},DEMO={available:false,email:'',password:''};
const aiBox=id=>AICFG.enabled?`<label class="u-blk-m8 small"><input type="checkbox" id="${id}" checked> Use AI to judge tone <span class="muted">(sends this text to ${esc(AICFG.provider||'the AI provider')})</span></label><p class="small muted">${esc(AICFG.notice||'')}</p>`:'';
const useAI=id=>{const b=document.getElementById(id);return b?b.checked:true};
function accountUI(){
  const real=AUTH==='accounts';
  $('#who').classList.toggle('hidden',real);document.querySelector('label[for=who]').classList.toggle('hidden',real);
  $('#pass').classList.toggle('hidden',real || !!ME);
  $('#hdr-signin').classList.toggle('hidden',!(real&&!ME));$('#acct').classList.toggle('hidden',!(real&&ME));
  if(real&&ME)$('#acct-name').textContent=ME.name+' · '+ME.role+(ME.is_external?' (agency)':'');
  document.querySelector('#nav [data-tab=users]').classList.toggle('hidden',!(real&&ME&&ME.role==='admin'));
  $('#main').querySelectorAll('[data-tour-only]').forEach(x=>x.classList.toggle('hidden',real));
}
document.addEventListener('submit',e=>{
  if(e.target.id!=='signin')return;e.preventDefault();
  const err=$('#login-err'),btn=e.target.querySelector('button[type=submit]');err.textContent='';btn.disabled=true;
  (async()=>{
    try{ME=await api('/api/login',{json:{email:$('#email').value,password:$('#password').value,code:$('#code').value}})}
    catch(ex){
      ME=null;
      if(ex.data&&ex.data.mfa_required){$('#code-row').classList.remove('hidden');$('#code').focus()}
      err.textContent=ex.message;return}
    finally{btn.disabled=false}
    history.replaceState({},'','/');document.title='BrandGuard';
    CUR=null;DETAIL=null;KBDATA=null;afterLogin()})()});
$('#signout').onclick=()=>run(async()=>{await api('/api/logout',{json:{}});signedOut('Signed out.')});
$('#mfa').onclick=()=>run(async()=>{
  if(ME.mfa){const pw=prompt('To turn two-step sign-in off, enter your password');if(pw===null)return;
    const code=prompt('and a current 6-digit code');if(code===null)return;
    await api('/api/mfa/disable',{json:{password:pw,code}});ME.mfa=false;toast('Two-step sign-in is off.');return}
  const s=await api('/api/mfa/setup',{json:{}});
  const code=prompt('Add this key to your authenticator app (Google Authenticator, Authy, 1Password...):\n\n'+s.secret+'\n\nThen enter the 6-digit code it shows');
  if(code===null)return;await api('/api/mfa/enable',{json:{code}});ME.mfa=true;toast('Two-step sign-in is on.')});
$('#chpw').onclick=()=>run(async()=>{
  const cur=prompt('Current password');if(cur===null)return;
  const nw=prompt('New password (at least 10 characters)');if(nw===null)return;
  await api('/api/password',{json:{current:cur,new:nw}});toast('Password changed. Other devices were signed out.')});
