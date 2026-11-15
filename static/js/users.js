/* Users screen (admin): accounts, roles, passwords. Anything that signs someone out or changes access asks first. */
const ROLE_OPTIONS=[['creator','Creator: writes content'],['manager','Manager: approves content'],['reviewer','Reviewer: approves content and claims'],['admin','Admin: manages rules and people']];
async function renderUsers(){
  const rid=++RID;let list;
  try{list=await api('/api/users')}catch(e){if(rid!==RID)return;$('#main').innerHTML=errorCard('We couldn’t load users',e.message);return}
  if(rid!==RID)return;
  $('#main').innerHTML=`${pageHead('Access control','Users','Manage the people who can create, review, approve and administer brand work.','<span class="chip approved">Admin only</span>')}
   <div class="stack"><section class="card" aria-labelledby="acc-h"><h2 id="acc-h">Accounts</h2>
    <p class="muted small">Deactivating an account or resetting its password signs that person out at once.</p>
    <table class="stack-rows u-gap"><thead><tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>
    ${list.map(u=>`<tr><td data-label="Name"><b>${esc(u.name)}</b>${u.is_external?' <span class="chip">Agency</span>':''}</td><td data-label="Email">${esc(u.email||'')}</td><td data-label="Role">${esc(cap(u.role))}</td>
      <td data-label="Status"><span class="chip ${u.active?'success':''}">${u.active?'Active':'Deactivated'}</span></td>
      <td><div class="table-actions"><button class="btn sm" type="button" data-uact="role" data-uid="${u.id}" data-name="${esc(u.name)}" data-role="${esc(u.role)}" aria-label="Change role for ${esc(u.name)}">Change role</button>
       <button class="btn sm" type="button" data-uact="pw" data-uid="${u.id}" data-name="${esc(u.name)}" aria-label="Reset password for ${esc(u.name)}">Reset password</button>
       ${u.active?`<button class="btn sm bad" type="button" data-uact="off" data-uid="${u.id}" data-name="${esc(u.name)}" aria-label="Deactivate ${esc(u.name)}">Deactivate</button>`
         :`<button class="btn sm" type="button" data-uact="on" data-uid="${u.id}" data-name="${esc(u.name)}" aria-label="Reactivate ${esc(u.name)}">Reactivate</button>`}</div></td></tr>`).join('')}
    </tbody></table></section>
   <section class="card" aria-labelledby="add-h"><h2 id="add-h">Add a user</h2><p class="muted small">They can change their password after their first sign-in.</p>
    <form id="newuser" class="u-gap" novalidate>
     <div class="field"><label for="nu-name">Name</label><input id="nu-name" name="name" autocomplete="off"></div>
     <div class="field"><label for="nu-email">Email</label><input id="nu-email" name="email" type="email" autocomplete="off"></div>
     <div class="field"><label for="nu-role">Role</label><select id="nu-role" name="role"><option>creator</option><option>manager</option><option>reviewer</option><option>admin</option></select></div>
     <div class="field"><label for="nu-pass">Temporary password</label><input id="nu-pass" name="password" type="password" autocomplete="new-password" aria-describedby="nu-pass-h"><span class="field-hint" id="nu-pass-h">At least 10 characters.</span></div>
     <label class="nu-ext"><input type="checkbox" name="ext"> Agency (external): sees only their own content</label>
     <div><button class="btn primary" type="submit">Add user</button></div></form></section></div>`;
  $('#newuser').onsubmit=e=>{e.preventDefault();const f=e.target;run(async()=>{
    const need=!f.name.value.trim()?[f.name,'Enter a name.']:!f.email.value.trim()?[f.email,'Enter an email address.']:f.password.value.length<10?[f.password,'The temporary password needs at least 10 characters.']:null;
    if(need){need[0].setAttribute('aria-invalid','true');need[0].focus();throw new Error(need[1])}
    await api('/api/users',{json:{name:f.name.value,email:f.email.value,role:f.role.value,is_external:f.ext.checked,password:f.password.value}});
    toast('User added.');renderUsers()})};
  $('#main').querySelectorAll('[data-uact]').forEach(b=>b.onclick=()=>run(async()=>{
    const id=b.dataset.uid,a=b.dataset.uact,name=b.dataset.name,patch=json=>api('/api/users/'+id,{method:'PATCH',json});
    let ok=false,msg='Saved.';
    if(a==='on'){await patch({active:true});ok=true;msg=name+' can sign in again.'}
    else if(a==='off'){ok=await confirmDialog({title:'Deactivate '+name+'?',consequence:name+' is signed out immediately and cannot sign in until you reactivate the account. Their content and decisions are kept.',ok:'Deactivate account',danger:true,onSubmit:()=>patch({active:false})});msg=name+' was deactivated.'}
    else if(a==='role'){ok=await askDialog({title:'Change role for '+name,consequence:'The new role changes what '+name+' can see and do straight away.',ok:'Change role',
        fields:[{id:'role',label:'Role',type:'select',options:ROLE_OPTIONS,value:b.dataset.role}],onSubmit:v=>patch({role:v.role})});msg='Role updated for '+name+'.'}
    else{ok=await askDialog({title:'Reset password for '+name,consequence:name+' is signed out of every device and must use the new password.',ok:'Reset password',danger:true,
        fields:[{id:'pw',label:'New password',type:'password',ac:'new-password',hint:'At least 10 characters.'}],onSubmit:v=>{if(v.pw.length<10)throw new Error('Use at least 10 characters.');return patch({password:v.pw})}});msg='Password reset for '+name+'.'}
    if(ok){toast(msg);renderUsers()}}))}
