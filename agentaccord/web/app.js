'use strict';
const $ = id => document.getElementById(id);
let token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('agentaccord-token') || '';
if(token){sessionStorage.setItem('agentaccord-token',token);history.replaceState(null,'',location.pathname);}
let state, result, dirty=false, policyRevision=0;
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function notice(message,error=false){$('notice').textContent=message;$('notice').className=error?'error':'';}
async function api(path,body){const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'X-AgentAccord-Token':token,'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed');return data;}
function view(name){document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==name);document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===name));}
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));$('start').onclick=()=>view('policies');$('startQuick').onclick=()=>view('quick');
async function busy(button,action){button.disabled=true;try{await action();}catch(error){notice(error.message,true);}finally{button.disabled=false;}}

function markDirty(){
  dirty=true; policyRevision++;
  $('policyStatus').textContent='Unsaved changes. Preview their effect, then save.';
  $('scopePreview').replaceChildren(el('p','Scope changed. Preview again to see the current draft.','muted'));
}
function pathInput(label, value, field, hint){
  const wrapper=el('label',label,'path-field');
  const input=document.createElement('textarea');
  input.rows=3; input.value=(value||[]).join('\n'); input.dataset.field=field;
  input.setAttribute('aria-label',label); input.spellcheck=false;
  input.addEventListener('input',markDirty);
  wrapper.append(input,el('small',hint)); return wrapper;
}
function paths(input){return input.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);}
function renderPolicies(){
  const list=$('policyList'); list.replaceChildren();
  let lastLanguage='';
  Object.entries(state.rules).sort((a,b)=>a[1].language.localeCompare(b[1].language)).forEach(([id,rule])=>{
    if(rule.language!==lastLanguage){list.append(el('h2',rule.language+' rules'));lastLanguage=rule.language;}
    const saved=state.policy.rules[id]||{approved:false,enabled:true,severity:'error'};
    const row=el('div',undefined,'policy'); row.dataset.rule=id;
    const info=el('div');
    info.append(el('h3',rule.title),el('p',rule.guidance),el('small',id+' · '+rule.language));
    const controls=el('div',undefined,'policy-controls');
    const label=el('label'); const check=document.createElement('input');
    check.type='checkbox'; check.className='approval'; check.checked=saved.approved&&saved.enabled;
    check.setAttribute('aria-label','Approve '+rule.title); check.onchange=markDirty;
    label.append(check,document.createTextNode(' Approve'));
    const select=document.createElement('select'); select.className='rule-severity';
    select.setAttribute('aria-label',rule.title+' severity');
    ['error','warning'].forEach(v=>{const option=el('option',v==='error'?'Error':'Warning');option.value=v;select.append(option);});
    select.value=saved.severity; select.onchange=markDirty;
    controls.append(label,select);
    const details=el('details',undefined,'rule-scope'); details.append(el('summary','Paths and exceptions'));
    const grid=el('div',undefined,'path-grid');
    grid.append(pathInput('Include paths — '+rule.title,saved.include,'include','Empty means all supported paths. One glob per line.'),
      pathInput('Exclude paths — '+rule.title,saved.exclude,'exclude','Exclusion wins. Other rules can still check these files.'));
    details.append(grid);
    if(id==='spring.no-value'){
      const exception=el('label',undefined,'exception'); const checkbox=document.createElement('input');
      checkbox.type='checkbox'; checkbox.className='batch-exception'; checkbox.checked=!!saved.allow_job_parameters;
      checkbox.onchange=markDirty;
      exception.append(checkbox,document.createTextNode(' Allow literal Spring Batch jobParameters lookups'));
      details.append(exception);
    }
    row.append(info,controls,details); list.append(row);
  });
  const shared=$('sharedScope'); shared.replaceChildren();
  shared.append(pathInput('Exclude from every rule',state.policy.exclude,'global-exclude','Use sparingly: every rule skips these paths.'));
  const examples=state.policy.examples||{};
  shared.append(pathInput('Java teaching-example paths',examples.java,'java-examples','Java snippets in these paths receive warnings, even for error rules.'),
    pathInput('Intentional counter-example paths',examples.counter_examples,'counter-examples','Omitted only inside the Java teaching-example paths above.'));
}
function draftPolicy(){
  const rules={...state.policy.rules};
  document.querySelectorAll('.policy').forEach(row=>{
    const id=row.dataset.rule;
    rules[id]={...state.policy.rules[id],approved:row.querySelector('.approval').checked,enabled:true,
      severity:row.querySelector('.rule-severity').value,
      include:paths(row.querySelector('[data-field="include"]')),
      exclude:paths(row.querySelector('[data-field="exclude"]'))};
    const exception=row.querySelector('.batch-exception');
    if(exception)rules[id].allow_job_parameters=exception.checked;
  });
  return {...state.policy,version:1,rules,
    exclude:paths(document.querySelector('[data-field="global-exclude"]')),
    examples:{...state.policy.examples,
      java:paths(document.querySelector('[data-field="java-examples"]')),
      counter_examples:paths(document.querySelector('[data-field="counter-examples"]'))}};
}
$('previewScope').onclick=()=>busy($('previewScope'),async()=>{
  const revision=policyRevision;
  const preview=await api('preview',draftPolicy());
  if(revision!==policyRevision)return;
  notice('Draft preview complete. Nothing saved.');
  const container=$('scopePreview'); container.replaceChildren();
  container.append(el('p','Draft preview only — nothing saved.','preview-label'));
  if(!preview.approved_rules)container.append(el('p','No active approved rules. Select a rule to preview its coverage.','muted'));
  const counts={};
  preview.files.forEach(f=>counts[f.status]=(counts[f.status]||0)+1);
  const labels={'analyzed':'Checked','example':'Example (warning only)','counter-example':'Counter-example omitted',
    'excluded':'Globally excluded','out-of-scope':'Outside rule scopes','skipped':'Incomplete','covered-link':'Covered at target'};
  container.append(el('p',Object.entries(counts).map(([key,count])=>labels[key]+': '+count).join(' · ')||'No supported files found.'));
  const table=el('table'); const caption=el('caption','Affected files (first 200 of '+preview.files.length+')');table.append(caption);
  const head=el('tr'); ['File','Treatment','Applicable rules'].forEach(t=>head.append(el('th',t)));table.append(head);
  preview.files.slice(0,200).forEach(f=>{
    const row=el('tr'); row.append(el('td',f.path),el('td',f.reason||labels[f.status]),el('td',f.rules.join(', ')||'None'));table.append(row);
  });
  const scroll=el('div',undefined,'table-scroll');scroll.append(table);container.append(scroll);
});
async function refresh(){state=await api('state');$('appVersion').textContent='VERSION '+state.version;$('repoName').textContent=state.name;$('repoPath').textContent=state.repository;$('approved').textContent=Object.values(state.policy.rules).filter(p=>p.approved&&p.enabled).length;$('languages').textContent=Object.keys(state.discovery.languages).length;$('instructions').textContent=state.discovery.instructions.length;$('languageTags').replaceChildren(...Object.entries(state.discovery.languages).map(([name,count])=>el('span',name+' · '+count+' files')));$('instructionList').replaceChildren(...(state.discovery.instructions.length?state.discovery.instructions:['No recognized instruction files found']).map(p=>el('li',p)));$('guidanceText').textContent=state.guidance;renderPolicies();renderQuickRules();
if(state.workspace_mode==='quick'){
  view('quick'); document.querySelectorAll('[data-view]').forEach(b=>b.hidden=b.dataset.view!=='quick');
  document.querySelector('header .label').textContent='LOCAL TEXT WORKSPACE';
}}


$('savePolicies').onclick=()=>busy($('savePolicies'),async()=>{
  const policy=draftPolicy(); $('policyEditor').disabled=true;
  try{
    await api('policy',policy); dirty=false; result=null; await refresh();
    $('policyStatus').textContent='Saved to .agentaccord.yml';
    $('lastCheck').textContent='Run again';
    $('resultSummary').textContent='Policy changed. Run checks to refresh findings.';
    $('findingList').replaceChildren(); $('visibleCount').textContent='';
    $('coverageContent').textContent='Run a check to inspect coverage.';
    notice('Policy saved. Only active approved rules will be enforced.');
  }finally{$('policyEditor').disabled=false;}
});
$('writeGuidance').onclick=()=>busy($('writeGuidance'),async()=>{if(dirty)throw new Error('Save policy changes before updating guidance.');const response=await api('guidance',{});result=null;$('lastCheck').textContent='Run again';$('resultSummary').textContent='Guidance changed. Run checks to refresh findings.';$('findingList').replaceChildren();$('visibleCount').textContent='';await refresh();notice(response.changed?'Updated the managed section of AGENTS.md. Handwritten sections were preserved.':'Guidance is already up to date.');});

function renderFindings(){
  if(!result)return;
  const active=result.report.findings.filter(f=>!f.baselined);
  const filtered=active.filter(f=>($('severity').value==='all'||f.severity===$('severity').value)
    &&($('kind').value==='all'||f.kind===$('kind').value)
    &&[f.path,f.rule,f.message,f.remediation,f.source_line].join(' ').toLowerCase().includes($('search').value.toLowerCase()));
  $('visibleCount').textContent=filtered.length+' of '+active.length+' findings shown';
  const list=$('findingList'); list.replaceChildren();
  for(const f of filtered){
    const card=el('article',undefined,'finding'),header=el('div',undefined,'finding-head');
    header.append(el('span',f.severity,'badge '+f.severity),el('span','Team-policy conflict','muted'));
    const policy=f.policy||{},rule=state.rules[f.rule]||{};
    card.append(header,el('h3',f.message),el('code',f.path+':'+f.line+':'+f.column,'location'));
    card.append(el('h4','Matched evidence'),el('pre',f.source_line||f.evidence||'No source excerpt available.','evidence'));
    card.append(el('h4','Approved policy'),el('p',policy.guidance||rule.guidance||f.rule),
      el('code',f.rule+' · configured severity: '+(policy.severity||f.severity)));
    const include=policy.include||[],exclude=policy.exclude||[];
    card.append(el('p','Scope: '+(include.length?'included by '+include.join(', '):'all supported paths')
      +(exclude.length?'; exclusions: '+exclude.join(', '):'; no per-rule exclusions')+'.','muted'));
    const explanation=f.confidence==='example'
      ? 'Heuristic example match. Names may lack imports; this is a non-blocking warning for review.'
      : f.confidence==='pattern'
      ? 'A supported affirmative instruction pattern conflicts with this rule. Arbitrary prose and instruction precedence are not interpreted.'
      : f.path.endsWith('.java')
      ? 'A parsed Java annotation resolves to a type prohibited by this rule. This is a team convention, not proof of a bug.'
      : 'Parsed syntax matches this rule. This check does not establish runtime correctness.';
    card.append(el('h4','Why it applies'),el('p',explanation),el('h4','Suggested fix'),el('p',f.remediation,'fix'));
    list.append(card);
  }
  if(!filtered.length)list.append(el('div',active.length?'No findings match these filters.':result.exit_code===2
    ?'Analysis needs attention. Review coverage below.':'No policy conflicts found for the approved, supported checks.','empty'));
}
$('runCheck').onclick=()=>busy($('runCheck'),async()=>{if(dirty)throw new Error('Save policy changes before running checks.');notice('Checking source files and agent instructions…');result=await api('check',{});const r=result.report;const active=r.findings.filter(f=>!f.baselined);const errors=active.filter(f=>f.severity==='error').length;const conflicts=active.filter(f=>f.kind==='instruction').length;$('lastCheck').textContent=result.exit_code===2?'Incomplete':errors?'Review needed':'Passed';const plural=(n,word)=>`${n} ${word}${n===1?'':'s'}`;$('resultSummary').textContent=[plural(errors,'error'),plural(active.length-errors,'warning'),plural(conflicts,'instruction conflict'),plural(r.analyzed_files,'analyzed file'),...(r.excluded_files?[`${r.excluded_files} excluded by policy`]:[]),...(r.baseline&&r.baseline.accepted?[`${r.baseline.accepted} accepted by baseline`]:[]),plural(r.approved_rules,'approved rule')].join(' · ');$('resultSummary').className='summary'+(result.exit_code?' error':'');$('coverageContent').replaceChildren();const ul=el('ul');[...r.skipped.map(s=>s.path+': '+s.reason),...r.limitations,...(!r.approved_rules?['No approved rules. Approve policies before checking compliance.']:[])].forEach(t=>ul.append(el('li',t)));$('coverageContent').append(ul);renderFindings();notice(result.exit_code===2?'Analysis incomplete. Review approved policies and skipped files.':'Check complete. Findings reflect the current saved policy.',result.exit_code===2);});
['search','severity','kind'].forEach(id=>$(id).addEventListener('input',renderFindings));
document.querySelectorAll('[data-export]').forEach(button=>button.onclick=()=>busy(button,async()=>{if(dirty)throw new Error('Save policy changes before exporting.');const data=await api('export',{format:button.dataset.export});const url=URL.createObjectURL(new Blob([data.content],{type:data.format==='html'?'text/html':'application/json'}));const a=document.createElement('a');a.href=url;a.download='agentaccord-report.'+data.format;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('Report downloaded from a fresh scan.');}));
refresh().catch(error=>notice(error.message+' Open the complete URL printed by agentaccord serve.',true));

function renderQuickRules(){
  const chosen=new Set([...document.querySelectorAll('#quickRules input:checked')].map(n=>n.value));
  const container=$('quickRules');container.replaceChildren();
  const groups={};
  Object.entries(state.rules).filter(([id])=>!id.startsWith('custom.')).forEach(([id,rule])=>{
    if(!groups[rule.language]){const group=el('fieldset');group.append(el('legend',rule.language));groups[rule.language]=group;container.append(group);}
    const label=el('label',undefined,'quick-rule');const input=document.createElement('input');input.type='checkbox';input.value=id;input.checked=chosen.has(id);
    input.onchange=invalidateQuick;label.append(input,el('span',rule.title+' — '+rule.guidance));groups[rule.language].append(label);
  });
}
function invalidateQuick(){ $('quickResults').replaceChildren(el('p','Input changed. Run the check to see current results.','muted')); }
$('quickFiles').onchange=()=>{$('quickFileNames').textContent=[...$('quickFiles').files].map(f=>f.name).join(', ')||'No files selected.';invalidateQuick();};
$('quickText').oninput=invalidateQuick;$('quickName').oninput=invalidateQuick;
$('quickDemo').onclick=()=>{
  $('quickFiles').value='';$('quickFileNames').textContent='No files selected.';$('quickName').value='SKILL.md';
  $('quickText').value='# Configuration example\n\n```java\nclass Client {\n    @Value("${client.url}") String url;\n}\n```\n';
  invalidateQuick();notice('Example loaded. Select Typed configuration below, then run the check.');
};
$('quickRun').onclick=()=>busy($('quickRun'),async()=>{
  const rules=[...document.querySelectorAll('#quickRules input:checked')].map(n=>n.value);
  if(!rules.length)throw new Error('Choose at least one rule for this check.');
  const selected=[...$('quickFiles').files];const text=$('quickText').value;const name=$('quickName').value;
  if(selected.length+(text.trim()?1:0)>20)throw new Error('Choose at most 20 files, including pasted text.');
  if(selected.some(f=>f.size>100000)||selected.reduce((n,f)=>n+f.size,0)+new Blob([text]).size>400000)throw new Error('Use files up to 100 KB each and 400 KB total.');
  // Snapshot input and hide stale results. Editing while a request runs invalidates its result.
  const revision=JSON.stringify([rules,selected.map(f=>[f.name,f.size,f.lastModified]),text,name]);
  $('quickResults').replaceChildren(el('p','Checking selected text…'));
  const files=await Promise.all(selected.map(async f=>({name:f.name,content:new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer())})));
  if(text.trim())files.push({name,content:text});if(!files.length)throw new Error('Choose a file or paste text first.');
  const data=await api('quick-check',{files,rules});
  const current=JSON.stringify([[...document.querySelectorAll('#quickRules input:checked')].map(n=>n.value),[...$('quickFiles').files].map(f=>[f.name,f.size,f.lastModified]),$('quickText').value,$('quickName').value]);
  if(revision!==current){invalidateQuick();return;}
  const box=$('quickResults');box.replaceChildren();const r=data.report;
  const count=(n,word)=>n+' '+word+(n===1?'':'s');
  box.append(el('h2','3. Review the result'),el('p',(data.exit_code===2?'Incomplete coverage':data.exit_code===1?'Review findings':'Check complete')+' · '+count(r.analyzed_files,'file')+' checked · '+count(r.findings.length,'finding')+' · '+r.skipped.length+' skipped','summary'));
  r.findings.forEach(f=>{const card=el('article',undefined,'finding');card.append(el('span',f.severity,'badge '+f.severity),el('h3',f.message),el('code',f.path+':'+f.line+':'+f.column),el('pre',f.source_line||f.evidence,'evidence'),el('p',f.remediation,'fix'));box.append(card);});
  if(!r.findings.length)box.append(el('p',data.exit_code===2?'No findings does not mean a pass: review the skipped files.':'No conflicts found within these selected checks.'));
  r.skipped.forEach(f=>box.append(el('p',f.path+': '+f.reason,'summary error')));
  const details=el('details');details.append(el('summary','What was checked and limitations'));const list=el('ul');r.limitations.forEach(t=>list.append(el('li',t)));details.append(list);box.append(details);
  notice('Local text check finished. Project policy and files were not changed.');
});
