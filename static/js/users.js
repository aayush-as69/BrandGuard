/* Users screen (admin) */
async function renderUsers(){
  const rid=++RID;const list=await api('/api/users');if(rid!==RID)return;
  $('#main').innerHTML='<div class="card"><h2>Users</h2><p class="small muted">Accounts for your team and agencies. Deactivating an account or changing its password signs that person out at once.</p>'+
   '<table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>'+
   list.map(u=>`<tr><td>${esc(u.name)}${u.is_external?' <span class="small muted">(agency)</span>':''}</td><td>${esc(u.email||'')}</td><td>${esc(u.role)}</td><td>${u.active?'Active':'Deactivated'}</td>`+
    `<td><button class="btn" data-uact="toggle" data-uid="${u.id}" data-on="${u.active?1:0}">${u.active?'Deactivate':'Reactivate'}</button> `+
    `<button class="btn" data-uact="role" data-uid="${u.id}">Change role</button> <button class="btn" data-uact="pw" data-uid="${u.id}">Reset password</button></td></tr>`).join('')+
   '</tbody></table></div><div class="card"><h3>Add a user</h3><form id="newuser" class="row">'+
   '<input name="name" placeholder="Name" aria-label="Name" required><input name="email" type="email" placeholder="Email" aria-label="Email" required>'+
   '<select name="role" aria-label="Role"><option>creator</option><option>manager</option><option>reviewer</option><option>admin</option></select>'+
   '<label class="small"><input type="checkbox" name="ext" aria-label="Agency (external)"> Agency (external)</label>'+
   '<input name="password" type="password" placeholder="Temporary password (10+ chars)" aria-label="Temporary password" required minlength="10">'+
   '<button class="btn primary" type="submit">Add</button></form></div>';
  $('#newuser').onsubmit=e=>{e.preventDefault();const f=e.target;run(async()=>{
    await api('/api/users',{json:{name:f.name.value,email:f.email.value,role:f.role.value,is_external:f.ext.checked,password:f.password.value}});
    toast('User added.');renderUsers()})};
  $('#main').querySelectorAll('[data-uact]').forEach(b=>b.onclick=()=>run(async()=>{
    const id=b.dataset.uid,a=b.dataset.uact;
    if(a==='toggle')await api('/api/users/'+id,{method:'PATCH',json:{active:b.dataset.on!=='1'}});
    else if(a==='role'){const r=prompt('New role: creator, manager, reviewer or admin');if(!r)return;await api('/api/users/'+id,{method:'PATCH',json:{role:r.trim()}})}
    else{const p=prompt('New password (at least 10 characters)');if(!p)return;await api('/api/users/'+id,{method:'PATCH',json:{password:p}})}
    toast('Saved.');renderUsers()}))}
