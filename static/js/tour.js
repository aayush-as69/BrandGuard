/* Guided tour */
/* ------------------------------------------------------------ guided tour */
const TOUR=[
 {h:'The idea',t:'BrandGuard checks content against your approved guidelines and facts, shows exactly which rule each problem breaks, and leaves every decision to a person. This tour takes about two minutes.'},
 {h:'1. The brand team loads its rules',t:'The admin imports guidelines, approved facts and a glossary. Press the button to sign in as Ira (admin) and load the synthetic Brewline Coffee knowledge base. If a passcode is required, type the admin passcode first.',who:4,act:async()=>{await tourAs(4);await api('/api/kb/seed',{json:{}});TAB='kb';afterLogin();toast('Demo knowledge base loaded.')}},
 {h:'2. An agency writer drafts an email',t:'Neha works at an outside agency. She sees only her own content and cannot browse confidential facts. Press the button to sign in as Neha and fill in a demo email that has deliberate mistakes. Then press Review now.',who:1,act:async()=>{await tourAs(1);TAB='content';await afterLogin();showNew();await loadDemo()}},
 {h:'3. Every finding cites its source',t:'Each highlight names the guideline or fact it breaks, quotes it, and shows a suggested fix. Nothing changes until a person clicks Accept fix, Edit or Dismiss (a reason is required). Prices, dates and rankings are checked against the approved facts; the claim check lists what is supported, contradicted or has no source.'},
 {h:'4. Decide, then submit',t:'Accept or edit the fixes, then press Submit for approval. Submitting needs every finding decided, so nothing is silently ignored. The launch date is embargoed, so Neha sees that it conflicts but not the approved date (🔒): she rewrites around it, or the brand team applies the fix.'},
 {h:'5. A manager approves',t:'Approval needs a manager or reviewer who is not the author. Press the button to sign in as Arjun (manager), open the content and approve or request changes. Approved content is locked, and every step is in the audit trail.',who:2,act:async()=>{await tourAs(2);TAB='content';afterLogin()}},
 {h:'6. The guidelines improve',t:'Insights show which rules authors repeatedly break and which ones people keep dismissing, so the brand team can fix unclear rules.',who:2,act:async()=>{await tourAs(2);TAB='insights';afterLogin()}},
];
let TI=0;
async function tourAs(id){if(ME&&ME.id===id)return;
  ME=await api('/api/login',{json:{user_id:id,passcode:$('#pass').value}});$('#who').value=id;CUR=null;DETAIL=null;KBDATA=null}
function tourStart(){TI=0;tourShow()}
function tourClose(){$('#tour').classList.add('hidden');document.body.style.paddingBottom=''}
function tourStep(d){TI=Math.max(0,Math.min(TOUR.length-1,TI+d));tourShow()}
function tourShow(){const st=TOUR[TI];$('#tour').classList.remove('hidden');
  $('#tour-n').textContent='Step '+(TI+1)+' of '+TOUR.length;$('#tour-h').textContent=st.h;$('#tour-t').textContent=st.t;
  $('#tour-b').disabled=TI===0;$('#tour-nx').disabled=TI===TOUR.length-1;$('#tour-do').classList.toggle('hidden',!st.act);
  // keep the page scrollable past the panel, so it never hides a button the person needs to press
  document.body.style.paddingBottom=($('#tour').offsetHeight+24)+'px'}
function tourDo(){run(async()=>{const b=$('#tour-do');b.disabled=true;try{await TOUR[TI].act()}finally{b.disabled=false}})}

