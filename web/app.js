const $ = selector => document.querySelector(selector);
const token = $('meta[name="pairing-token"]').content;
const nativeBridge=window.webkit?.messageHandlers?.dreamsTime;
let snapshot, view = 'tracking', refreshing = false, stopped = false, busy = false, connectionLost = false;
const make = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
const secondsLabel = seconds => { const s = Math.max(0, Math.round(seconds)); return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2,'0')}s` : `${Math.floor(s/3600)}h ${String(Math.floor(s%3600/60)).padStart(2,'0')}m`; };
const timerLabel = seconds => { const s=Math.max(0,Math.floor(seconds)); return [Math.floor(s/3600),Math.floor(s%3600/60),s%60].map(n=>String(n).padStart(2,'0')).join(':'); };
const clock = value => new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Madrid'}).format(value*1000);
function message(text,error=false){$('#notice').hidden=false;$('#notice').classList.toggle('error',error);$('#notice-text').textContent=text;}
async function api(path,body){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),path.startsWith('/api/dreams/')?120000:8000);
  try{const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:`Bearer ${token}`,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:controller.signal});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not complete this action.');return data;}finally{clearTimeout(timeout);}
}
async function act(fn){try{await fn();}catch(e){message(e.message,true);}}
function navigate(next){
  if(!['tracking','projects','settings'].includes(next))next='tracking';
  view=next;location.hash=next;
  document.querySelectorAll('.view').forEach(node=>node.hidden=node.id!==`view-${next}`);
  document.querySelectorAll('[data-view]').forEach(button=>{if(button.dataset.view===next)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  if(snapshot)render(snapshot);
}
function projectSelect(project){const select=make('select');select.setAttribute('aria-label','Assign activity to project');const option=make('option','Choose a project…');option.value='';select.append(option);(snapshot?.projects||[]).forEach(p=>{const o=make('option',p.name);o.value=p.id;select.append(o);});select.value=project||'';return select;}
function assignment(context,project,recommendation,segmentId){
  const generic=!context.identity&&(!context.title||['chatgpt','figma','google chrome','new tab','untitled'].includes(context.title.toLowerCase()));
  const controls=make('div',undefined,'assignment'),select=projectSelect(project),save=make('button',generic?'Assign this activity':context.identity?'Remember file or chat':'Remember document');
  if(!project&&recommendation?.candidates?.length===1)select.value=recommendation.candidates[0].project;
  save.addEventListener('click',()=>act(async()=>{
    if(!select.value)throw new Error('Choose a project first.');
    if(generic)await api('/api/activity/assign',{id:segmentId,project:select.value});
    else await api('/api/rules',{kind:context.identity?'identity':'title',value:context.identity||context.title,app:context.identity?'':context.app,project:select.value});
    message(generic?'Activity assigned. A generic app title cannot identify future conversations.':'Project saved. Matching recorded activity has been assigned.');await refresh();
  }));controls.append(select);if(!generic||segmentId)controls.append(save);
  if(context.app&&context.source==='window'){
    const session=make('button','Use for 30 minutes');session.addEventListener('click',()=>act(async()=>{
      if(!select.value)throw new Error('Choose a project first.');
      await api('/api/session',{project:select.value,app:context.app,title:context.title});message('This app and document are assigned for the next 30 minutes.');await refresh();
    }));controls.append(session);
  }
  return controls;
}
const stateCopy={
  permission_required:{title:'Project detection needs access',text:'App time is recorded, but macOS is blocking document context. Your unassigned time is kept.',action:'Pause tracking'},
  recording:{title:'Tracking is on',text:'Your active time is being saved.',action:'Pause tracking'},
  paused:{title:'Tracking is paused',text:'Your saved time is kept. Resume when you are ready.',action:'Resume tracking'},
  off:{title:'Tracking is off',text:'No new time is being recorded.',action:'Start tracking'},
  starting:{title:'Starting tracking…',text:'Waiting for your Mac to report its first activity.',action:'Starting…'},
  failed:{title:'Tracking is not working',text:'The tracker could not read activity from your Mac.',action:'Restart tracking'},
  stale:{title:'Tracking stopped responding',text:'No recent activity has been received. Your saved time is kept.',action:'Restart tracking'},
  browser_unavailable:{title:'Tracking is on',text:'Desktop app time is recorded. This browser is not included yet.',action:'Pause tracking'},
  idle:{title:'Waiting for you to return',text:'You are idle, so no extra time is being added.',action:'Pause tracking'},
  locked:{title:'Your Mac is inactive',text:'Tracking will continue when you return to your Mac.',action:'Pause tracking'},
  excluded:{title:'This activity is not tracked',text:'Private or excluded activity does not add time.',action:'Pause tracking'}
};
function automaticStatus(d){
  if(!d.connected)return d.connecting?'Finish the one-time sign-in in your browser. Tracking continues.':'Connect Dreams once to enable automatic saving.';
  if(d.automatic===false||d.weekly===false)return 'Automatic saving is paused in Settings. Your activity is kept on this Mac.';
  if(d.action_required==='sign-in')return 'Dreams authorization expired. Reconnect once in Settings; your recorded hours are safe.';
  if(d.error||d.pending)return 'Hours are safe on this Mac. Saving will retry automatically.';
  if(d.context_access==='denied')return 'Project detection is limited until Mac access is repaired. Activity remains available for a later correction.';
  if(d.publication?.state==='waiting_for_hour')return `${secondsLabel(d.publication.retained_seconds)} assigned so far. Dreams publishes completed hours per project and week; partial time stays on this Mac.`;
  if(d.publication?.state==='unassigned')return 'No project hours are ready to publish. Unassigned activity is preserved.';
  if(d.last?.verification!=='dreamstime/published/v1')return 'Automatic saving is on. Published hours have not been verified yet.';
  const saved=d.last?.at?` ${d.last.published_hours} whole hours verified in Dreams at ${new Date(d.last.at*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}.`:'';
  return `Automatic saving is on. Completed project hours are checked every five minutes.${saved}`;
}
function render(data){
  snapshot=data;
  const r=data.recording||{state:'off',today_seconds:0,sample_count:0,last_sample_age_seconds:null},copy=stateCopy[r.state]||stateCopy.failed;
  $('#tracker').dataset.state=r.state;$('#tracking-title').textContent=copy.title;$('#tracking-description').textContent=copy.text;
  $('#today-timer').textContent=timerLabel(r.today_seconds);$('#tracking-toggle').textContent=copy.action;$('#tracking-toggle').disabled=busy||r.state==='starting';
  $('#save-note').textContent=r.state==='browser_unavailable'?'Use a desktop work app for a few seconds to see this number increase.':r.state==='recording'?'This number increases as work is recorded.':'This is saved time. It will increase when activity is recorded.';
  $('#last-update').textContent=['failed','stale','off'].includes(r.state)?'No new time is being recorded.':r.state==='paused'?'Tracking stays paused until you resume.':r.last_sample_age_seconds===null?'No activity received yet.':r.last_sample_age_seconds<=4?'Activity updated just now.':`Last activity received ${Math.round(r.last_sample_age_seconds)} seconds ago.`;
  $('#live-check').hidden=['failed','stale','off','paused','starting','permission_required'].includes(r.state);
  const screen=data.health.collector||{};
  $('#screen-permission').hidden=!data.desktop_context_enabled||screen.screen_capture_permission!==false;
  const screenSetup=data.desktop_context_enabled&&screen.screen_capture_permission===false;
  if(screenSetup)$('#tracking-description').textContent='App time is recorded. Allow Screen Recording once to identify projects from the active work window.';
  $('#window-permission').hidden=!(['recording','permission_required'].includes(r.state)&&!data.health.accessibility&&screen.screen_capture_permission!==true&&!screenSetup);
  const current=data.current?.context,projects=Object.fromEntries(data.projects.map(p=>[p.id,p.name]));
  $('#current-label').textContent=r.state==='recording'?'Currently using':'Last detected app';
  $('#current-app').textContent=current?.app_name||'Nothing detected yet';
  $('#current-document').textContent=current?.title||((current?.source==='browser context missing')?'Browser tracking is not connected.':'Document name not available.');
  $('#current-project').textContent=projects[data.current?.project]||(r.state==='permission_required'?'Needs document access':'Unassigned');
  $('#project-evidence').textContent=data.current?.project?(data.recommendation?.reason||data.current.reason):(data.recommendation?.candidates?.length?`Daily review will check ${data.recommendation.candidates.map(c=>c.name).join(', ')}.`:(r.state==='permission_required'?'Project review needs document context. This time remains unassigned.':'Activity is preserved for project review; uncertain time stays unassigned.'));
  $('#automatic-status').textContent=automaticStatus(data.dreams||{});
  $('#recent-list').replaceChildren();
  data.report.segments.slice(-4).reverse().forEach(segment=>{
    const row=make('div',undefined,'recent-row'),body=make('div');
    body.append(make('strong',segment.context.app_name),make('p',segment.context.title||'App activity'));
    row.append(body,make('time',secondsLabel(segment.seconds)));$('#recent-list').append(row);
  });
  if(!data.report.segments.length)$('#recent-list').append(make('p','No time recorded yet. Use a work app for a few seconds, then return.','empty'));
  renderCheck(data);
  $('#version').textContent=`Dreams Time ${data.version||'0.4'}`;
  if(view==='projects')renderProjects(data,projects);
  if(view==='settings')renderSettings(data,projects);
}
function renderProjects(data,names){
  $('#week').value=data.report.week;$('#weekly-total').textContent=`${secondsLabel(data.report.total_seconds)} recorded`;
  if(!document.activeElement?.matches('.assignment select')){
    $('#activities').replaceChildren();
    data.report.segments.slice(-50).reverse().forEach(s=>{
      const card=make('article',undefined,'activity'),heading=make('div',undefined,'activity-heading'),text=make('div');
      text.append(make('h2',s.context.title||s.context.app_name),make('p',`${s.context.app_name} · ${clock(s.start)}–${clock(s.end)}`));heading.append(text,make('time',secondsLabel(s.seconds)));
      const reason=s.project?`Assigned to ${names[s.project]||'project'} · ${s.reason}`:s.recognition?.candidates?.length?`Suggested: ${s.recognition.candidates.map(c=>c.name).join(', ')} · ${s.recognition.reason}. Confirm or choose another project.`:'Not assigned to a project yet';
      card.append(heading,assignment(s.context,s.project,s.recognition,s.id),make('p',reason,'reason'));$('#activities').append(card);
    });
    if(!data.report.segments.length)$('#activities').append(make('p','Recorded activities will appear here for assignment.','empty'));
    $('#conversation-list').replaceChildren();data.conversations.forEach(c=>{
      const card=make('article',undefined,'conversation');card.append(make('h3',c.title));
      if(c.prompts.length)card.append(make('blockquote',c.prompts.at(-1)));
      card.append(assignment({identity:c.identity,title:c.title},data.rules.find(r=>r.kind==='identity'&&r.value===c.identity)?.project));$('#conversation-list').append(card);
    });
  }
  $('#review-status').textContent=data.report.reviewed?'Hours reviewed. Ready to prepare an update.':data.report.total_seconds?`${secondsLabel(data.report.totals.unassigned||0)} still needs a project. Check the assignments above.`:'Record some activity first.';
  $('#review').disabled=!data.report.total_seconds||data.report.reviewed;$('#export').disabled=!data.report.reviewed;
  $('#project-totals').replaceChildren();
  Object.entries(data.report.totals).forEach(([id,seconds])=>{
    const row=make('div',undefined,'recent-row');row.append(make('span',id==='unassigned'?'Needs a project':names[id]||id),make('time',secondsLabel(seconds)));$('#project-totals').append(row);
  });
  const d=data.dreams||{},assigned=data.report.total_seconds-(data.report.totals.unassigned||0);
  $('#sync').disabled=!d.connected||(!assigned&&!d.weeks?.includes(data.report.week)&&!d.pending)||busy;$('#connect-projects').hidden=!!d.connected;
  $('#sync-status').textContent=automaticStatus(d);
}
function renderSettings(data,names){
  const screen=data.health.collector||{};
  $('#accessibility-status').textContent=screen.screen_capture_permission===true?`Screen capture allowed. ${screen.screen_capture_count||0} windows read this session. Capture: ${screen.screen_capture_state||'waiting'}. Images and full OCR text are discarded.`:data.health.accessibility?'Document access is allowed. Screen Recording is needed for screenshot context.':'Document access and screen context are unavailable. Allow Screen Recording on the tracking screen.';
  $('#desktop-optin').checked=!!data.desktop_context_enabled;
  const dreams=data.dreams||{};
  $('#dreams-status').textContent=automaticStatus(dreams);
  $('#connect').textContent=dreams.connected?'Sign in again':'Enable saving in Dreams';
  $('#refresh-projects').hidden=$('#disconnect').hidden=!dreams.connected;
  $('#weekly-sync').checked=!!dreams.weekly;$('#weekly-sync').disabled=!dreams.connected;
  $('#sensor-details').textContent=data.sensor_error||`${data.recording?.sample_count||0} activity samples. Last update: ${data.recording?.last_sample_age_seconds??'none'} seconds ago.`;
  $('#desktop-text').textContent=data.desktop_context?.text||'No desktop conversation context received.';
  $('#rule-list').replaceChildren();data.rules.forEach(rule=>{
    const row=make('div',undefined,'saved-rule'),remove=make('button','Remove');row.append(make('span',`${rule.value} → ${names[rule.project]||rule.project}`),remove);
    remove.addEventListener('click',()=>act(async()=>{await api('/api/rules/delete',{id:rule.id});await refresh();}));$('#rule-list').append(row);
  });if(!data.rules.length)$('#rule-list').append(make('p','No saved associations yet.','empty'));
}
function renderCheck(data){
  const q=data.quickcheck,canCheck=!['failed','stale','off','paused','starting','permission_required'].includes(data.recording?.state);$('#live-check-result').hidden=!q?.started||!canCheck;
  if(!q?.started||!canCheck)return;
  const result=$('#live-check-result');result.replaceChildren();
  if(q.status==='passed'){
    result.append(make('h2','It is working.'),make('p','Your Mac reported app changes and a document name. The time counter shows what has been saved.'));
    $('#live-check').textContent='Check again';return;
  }
  result.append(make('h2',q.status==='needs_attention'?'Tracking is not confirmed yet.':'Switch apps, then come back.'),make('p',data.health.accessibility?'Use ChatGPT or Figma for a few seconds. This result updates automatically.':'Allow window access in Settings, then use another work app briefly.'));
  const list=make('div',undefined,'check-list'),labels=['Activity received','App change detected','Document detected'];
  q.checks.forEach((c,i)=>list.append(make('span',`${c.passed?'✓':'○'} ${labels[i]}`,c.passed?'passed':'')));result.append(list);
  if(!data.health.accessibility){const button=make('button','Allow window access','secondary');button.addEventListener('click',()=>act(openPermission));result.append(button);}
  $('#live-check').textContent=q.status==='running'?`Checking… ${Math.max(0,30-q.elapsed_seconds)}s`:'Try check again';
}
async function refresh(){
  if(refreshing||stopped)return;refreshing=true;
  try{const week=view==='projects'?$('#week').value:'';const data=await api('/api/snapshot'+(week?`?week=${week}`:''));connectionLost=false;render(data);}
  catch(e){connectionLost=true;$('#tracker').dataset.state='failed';$('#tracking-title').textContent='Tracker is offline';$('#tracking-description').textContent='Open Dreams Time.app to start it again. Your saved time is kept.';$('#tracking-toggle').textContent='Try reconnecting';$('#tracking-toggle').disabled=false;$('#last-update').textContent='The page is not receiving updates.';}
  finally{refreshing=false;}
}
async function toggleTracking(){
  if(!snapshot||connectionLost)return refresh();busy=true;$('#tracking-toggle').disabled=true;
  try{const state=snapshot.recording?.state;
    if(snapshot.paused)await api('/api/pause',{paused:false});
    else if(state==='off')await api('/api/capture/start',{});
    else if(['failed','stale'].includes(state))await api('/api/sensor/restart',{});
    else await api('/api/pause',{paused:true});
  }finally{busy=false;await refresh();}
}
function download(name,data){if(nativeBridge){nativeBridge.postMessage({type:'download',name,content:JSON.stringify(data,null,2)});return;}const anchor=make('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function importFile(event,path,key,text){const file=event.target.files[0];if(!file)return;if(file.size>30*1024*1024)throw new Error('Choose a JSON file smaller than 30 MB.');const result=await api(path,{[key]:JSON.parse(await file.text())});event.target.value='';message(text(result));await refresh();}
$('#allow-screen').addEventListener('click',()=>{if(nativeBridge)nativeBridge.postMessage({type:'screen-access'});else message('Open the installed Dreams Time app to allow Screen Recording.',true);});
async function openPermission(){if(nativeBridge){nativeBridge.postMessage({type:'repair-access'});return;}await api('/api/settings/accessibility',{});}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.view)));
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));
$('#dismiss-notice').addEventListener('click',()=>$('#notice').hidden=true);
$('#tracking-toggle').addEventListener('click',()=>act(toggleTracking));
$('#assign-project').addEventListener('click',()=>navigate('projects'));
$('#live-check').addEventListener('click',()=>act(async()=>{await api('/api/quickcheck',{});navigate('tracking');await refresh();}));
$('#allow-windows').addEventListener('click',()=>act(openPermission));$('#permission').addEventListener('click',()=>act(openPermission));
$('#week').addEventListener('change',()=>act(refresh));
$('#project-form').addEventListener('submit',event=>{event.preventDefault();act(async()=>{await api('/api/projects',{name:$('#project-name').value});$('#project-name').value='';message('Project added. Choose it for the activities below.');await refresh();});});
$('#review').addEventListener('click',()=>act(async()=>{await api('/api/review',{week:snapshot.report.week,digest:snapshot.report.digest});message('Hours reviewed. New activity or changes will need another review.');await refresh();}));
$('#export').addEventListener('click',()=>act(async()=>{const data=await api('/api/dreams/export',{week:snapshot.report.week});download(`dreams-time-${snapshot.report.week}.json`,data);message('Update prepared. Apply it through the Dreams connector.');}));
async function connectDreams(){message('Opening authorization to save your hours in Dreams…');const result=await api('/api/dreams/connect',{native:!!nativeBridge});if(nativeBridge)nativeBridge.postMessage({type:'open-url',url:result.url});else location.assign(result.url);}
$('#connect').addEventListener('click',()=>act(connectDreams));$('#connect-projects').addEventListener('click',()=>act(connectDreams));
$('#refresh-projects').addEventListener('click',()=>act(async()=>{const result=await api('/api/dreams/refresh',{});message(`${result.projects} Dreams projects loaded. Existing activity was checked for matches.`);await refresh();}));
$('#disconnect').addEventListener('click',()=>act(async()=>{await api('/api/dreams/disconnect',{});message('Dreams disconnected. Your recorded hours are kept.');await refresh();}));
$('#weekly-sync').addEventListener('change',e=>act(async()=>{await api('/api/dreams/automatic',{enabled:e.target.checked});message(e.target.checked?'Project matching and saving will run automatically.':'Automatic saving is paused.');await refresh();}));
$('#sync').addEventListener('click',()=>act(async()=>{
  busy=true;$('#sync').disabled=true;$('#sync').textContent='Sending…';
  try{const result=await api('/api/dreams/sync',{week:snapshot.report.week});message(result.skipped?`${secondsLabel(result.retained_seconds)} assigned; waiting for a completed hour per project. Partial time stays on this Mac.`:result.unchanged?'Dreams already has these verified whole-hour totals.':`${result.published_hours} whole hours verified in Dreams for week of ${result.week}. ${secondsLabel(result.retained_seconds)} stays on this Mac; ${secondsLabel(result.unassigned_seconds)} remains unassigned.`);}
  finally{busy=false;$('#sync').textContent='Save now';await refresh();}
}));
$('#dreams-file').addEventListener('change',e=>act(()=>importFile(e,'/api/dreams/import','map',r=>`${r.projects} Dreams projects connected.`)));
$('#chatgpt-file').addEventListener('change',e=>act(()=>importFile(e,'/api/chatgpt/import','conversations',r=>`${r.conversations} conversations imported as context. No time was added.`)));
$('#desktop-optin').addEventListener('change',e=>act(async()=>{await api('/api/settings/desktop-context',{enabled:e.target.checked});message('Conversation context setting saved.');await refresh();}));
$('#pair').addEventListener('click',()=>act(async()=>{if(nativeBridge)nativeBridge.postMessage({type:'copy',text:token});else await navigator.clipboard.writeText(token);message('Token copied. Paste it into the browser companion settings.');}));
$('#diagnostics').addEventListener('click',()=>act(async()=>download('dreams-time-diagnostics.json',await api('/api/diagnostics'))));
$('#restart').addEventListener('click',()=>act(async()=>{if(nativeBridge){nativeBridge.postMessage({type:'restart-collector'});return;}await api('/api/sensor/restart',{});await refresh();message('Capture restarted. Return to Tracking to see its status.');}));
$('#run-selftest').addEventListener('click',()=>act(async()=>{
  const button=$('#run-selftest');button.disabled=true;button.textContent='Testing…';
  try{const result=await api('/api/selftest'),box=$('#selftest-result');box.hidden=false;box.replaceChildren(make('h2',result.passed?'Time calculations passed.':'Time calculations need attention.'),make('p',`8 fictional hours tested in ${result.elapsed_ms} ms. This does not verify Mac capture.`));result.checks.forEach(c=>box.append(make('div',`${c.passed?'✓':'✕'} ${c.name}`,'test-check')));}
  finally{button.disabled=false;button.textContent='Run simulated workday';}
}));
$('#quit').addEventListener('click',()=>act(async()=>{await api('/api/quit',{});stopped=true;if(nativeBridge)nativeBridge.postMessage({type:'quit'});navigate('tracking');$('#tracker').dataset.state='off';$('#tracking-title').textContent='Dreams Time is closed';$('#tracking-description').textContent='Open the app whenever you want to track again.';$('#tracking-toggle').disabled=true;}));
setInterval(refresh,2000);
navigate(location.hash.slice(1)||'tracking');refresh();
