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
$('#demo-role').onchange=e=>run(async()=>{
  closeAcct();
  try{ME=await api('/api/demo/switch-role',{json:{role:e.target.value}})}
  catch(err){accountUI();throw err}
  ME=await api('/api/me');CUR=null;DETAIL=null;KBDATA=null;TAB='content';afterLogin()});
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
  if(!(real&&ME))closeAcct();
  document.querySelector('#nav [data-tab=users]').classList.toggle('hidden',!(real&&ME&&ME.role==='admin'));
  const demoUser=!!(real&&ME&&DEMO.available&&String(ME.email||'').endsWith('@brewline.demo'));
  $('#acct-role-row').classList.toggle('hidden',!demoUser);
  $('#chpw').classList.toggle('hidden',demoUser);$('#mfa').classList.toggle('hidden',demoUser);  // shared demo accounts: nothing to lock others out with
  if(demoUser)$('#demo-role').value=({rahul:'creator',arjun:'manager',meera:'reviewer',neha:'agency'})[ME.email.split('@')[0]]||'manager';
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
/* Account menu: one button in the header, everything else tucked inside. */
function closeAcct(){const m=$('#acct-menu');if(!m)return;m.classList.add('hidden');$('#acct-btn').setAttribute('aria-expanded','false')}
$('#acct-btn').onclick=()=>{const m=$('#acct-menu'),open=m.classList.contains('hidden');
  m.classList.toggle('hidden',!open);$('#acct-btn').setAttribute('aria-expanded',String(open));
  if(open)(m.querySelector('select:not(.hidden)')||m.querySelector('button')).focus()};
document.addEventListener('click',e=>{if(!e.target.closest('#acct'))closeAcct()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#acct-menu').classList.contains('hidden')){closeAcct();$('#acct-btn').focus()}});
$('#acct-menu').addEventListener('click',e=>{if(e.target.closest('button'))closeAcct()});

/* A small in-page dialog instead of the browser's prompt() boxes. onSubmit may throw to show its message and stay open. */
function askDialog({title,note='',secret='',fields=[],ok='Save',onSubmit}){
  return new Promise(resolve=>{
    const d=document.createElement('dialog');d.className='dlg';
    d.innerHTML=`<form class="dlg-f" novalidate><h3>${esc(title)}</h3>${note?`<p class="small muted">${esc(note)}</p>`:''}
      ${secret?`<p class="dlg-secret"><code>${esc(secret)}</code><button type="button" class="btn" data-copy>Copy</button></p>`:''}
      ${fields.map(f=>`<label for="dlg-${f.id}">${esc(f.label)}</label><input id="dlg-${f.id}" type="${f.type||'text'}" autocomplete="${f.ac||'off'}"${f.inputmode?` inputmode="${f.inputmode}"`:''}>`).join('')}
      <p class="dlg-err small" role="alert"></p>
      <div class="row"><button class="btn primary" type="submit">${esc(ok)}</button><button class="btn" type="button" data-cancel>Cancel</button></div></form>`;
    document.body.appendChild(d);
    const err=d.querySelector('.dlg-err');
    d.addEventListener('close',()=>{d.remove();resolve(d.returnValue==='ok')});
    d.querySelector('[data-cancel]').onclick=()=>d.close('cancel');
    const cp=d.querySelector('[data-copy]');
    if(cp)cp.onclick=async()=>{try{await navigator.clipboard.writeText(secret);cp.textContent='Copied'}catch(e){cp.textContent='Select and copy'}};
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();err.textContent='';
      const v={};for(const f of fields)v[f.id]=d.querySelector('#dlg-'+f.id).value;
      if(fields.some(f=>!v[f.id].trim())){err.textContent='Fill in every field.';return}
      const b=d.querySelector('[type=submit]');b.disabled=true;
      try{if(onSubmit)await onSubmit(v);d.close('ok')}catch(ex){err.textContent=ex.message}finally{b.disabled=false}};
    d.showModal();const first=d.querySelector('input');if(first)first.focus()})}
$('#signout').onclick=()=>run(async()=>{await api('/api/logout',{json:{}});signedOut('Signed out.')});
$('#mfa').onclick=()=>run(async()=>{
  if(ME.mfa){
    const done=await askDialog({title:'Turn off two-step sign-in',note:'Enter your password and a current 6-digit code.',ok:'Turn off',
      fields:[{id:'pw',label:'Password',type:'password',ac:'current-password'},{id:'code',label:'6-digit code',inputmode:'numeric',ac:'one-time-code'}],
      onSubmit:v=>api('/api/mfa/disable',{json:{password:v.pw,code:v.code}})});
    if(done){ME.mfa=false;toast('Two-step sign-in is off.')}return}
  const s=await api('/api/mfa/setup',{json:{}});
  const done=await askDialog({title:'Turn on two-step sign-in',note:'Add this key to your authenticator app (Google Authenticator, Authy, 1Password), then enter the 6-digit code it shows.',
    secret:s.secret,ok:'Turn on',fields:[{id:'code',label:'6-digit code',inputmode:'numeric',ac:'one-time-code'}],
    onSubmit:v=>api('/api/mfa/enable',{json:{code:v.code}})});
  if(done){ME.mfa=true;toast('Two-step sign-in is on.')}});
$('#chpw').onclick=()=>run(async()=>{
  const done=await askDialog({title:'Change password',note:'At least 10 characters. Your other devices will be signed out.',ok:'Change password',
    fields:[{id:'cur',label:'Current password',type:'password',ac:'current-password'},{id:'nw',label:'New password',type:'password',ac:'new-password'},{id:'again',label:'New password again',type:'password',ac:'new-password'}],
    onSubmit:async v=>{if(v.nw!==v.again)throw new Error('The two new passwords do not match.');await api('/api/password',{json:{current:v.cur,new:v.nw}})}});
  if(done)toast('Password changed. Other devices were signed out.')});
