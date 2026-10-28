/* Local browser QA: stage UI, explicit state fixtures, GET-only production reads. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),assert=require('node:assert/strict');
const origin='http://127.0.0.1:8766',root=path.resolve(__dirname,'..'),ui=path.join(root,'tools','ops_dashboard_ui');
const output=path.join(root,'qa','operations-ux');fs.mkdirSync(output,{recursive:true});
const profile=fs.mkdtempSync('/private/tmp/lotusim-operations-ux-'),pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const pending=new Map(),events=[],blockedWrites=[],interceptionErrors=[],screenshots=[];
let browser,connection,sequence=0,checks=0;
const check=(value,message)=>{assert.ok(value,message);checks++;};
async function send(method,params={}){const id=++sequence;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});connection.send(JSON.stringify({id,method,params}));setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(Error('CDP timeout: '+method));}},15000).unref();});}
async function evaluate(expression){const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result?.value;}
async function waitFor(expression,ms=20000){const stop=Date.now()+ms;while(Date.now()<stop){if(await evaluate(expression))return;await pause(100);}throw Error('Timed out: '+expression);}
async function click(id){await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);}
async function set(id,value,event='change'){await evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));})()`);}
async function shot(name){const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});const file=path.join(output,name);fs.writeFileSync(file,Buffer.from(result.data,'base64'));screenshots.push(file);}
async function get(route){const response=await fetch(origin+route);assert.ok(response.ok,'GET '+route);return response.json();}
const initialTime=Date.now();
const baseEvents=Array.from({length:20},(_,index)=>({id:'fixture-'+index,at:new Date(initialTime-index*1000).toISOString(),source:index%2?'vision-fixture':'planification-fixture',level:index===1?'error':index===2?'warning':'info',message:'Fixture locale — événement '+index,historical:index>14,privateExtra:'NOT_EXPORTED'}));
const fixture={schema:'lotusim-ops-fixture-1',generatedAt:new Date().toISOString(),health:{state:'degraded',error:'Exemple de diagnostic collecteur à examiner.',warnings:[...Array.from({length:7},(_,i)=>'Avertissement de démonstration '+(i+1)), 'Avertissement de démonstration 1']},
  services:[{id:'docker',label:'Docker · fixture',state:'running',detail:'État fictif pour QA'},{id:'ros',label:'ROS · fixture',state:'error',detail:'Exemple de liaison à contrôler'}],
  renderer:{engineId:'unity',label:'Unity',state:'idle',fresh:true,isPlaying:false,isCompiling:false},
  capture:{state:'capturing',status:'capturing',captured:2,expected:10,historical:false,live:true,updatedAt:new Date().toISOString(),outputName:'Campagne de démonstration'},
  vision:{state:'failed',status:'failed',historical:true,detail:'ARCHIVED_FAILURE_MUST_NOT_ALERT',updatedAt:new Date().toISOString()},
  agents:[],events:baseEvents,campaigns:[],reports:[],preview:null,scene:null};
async function emit(state){await evaluate(`window.__opsFixtureEmit(${JSON.stringify(state)})`);}
async function intercepted(item){
  const request=item.params.request,requestId=item.params.requestId,url=new URL(request.url);
  const fulfill=(body,type='application/json')=>send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:type}],body:Buffer.from(typeof body==='string'?body:JSON.stringify(body)).toString('base64')});
  if(!['GET','HEAD'].includes(request.method)){blockedWrites.push({method:request.method,path:url.pathname});return send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});}
  if(url.origin!==origin)return send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});
  if(url.pathname==='/')return fulfill(fs.readFileSync(path.join(ui,'index.html'),'utf8'),'text/html');
  const name=url.pathname.slice(1);
  if(/^[a-z0-9-]+\.(js|css)$/.test(name)&&fs.existsSync(path.join(ui,name)))return fulfill(fs.readFileSync(path.join(ui,name),'utf8'),name.endsWith('.js')?'text/javascript':'text/css');
  if(url.pathname==='/api/state')return fulfill({...fixture,generatedAt:new Date().toISOString()});
  return send('Fetch.continueRequest',{requestId});
}
(async()=>{
  const plansBefore=await get('/api/traffic/plans'),enginesBefore=await get('/api/engines');
  browser=cp.spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--disable-extensions','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:'ignore'});
  const active=path.join(profile,'DevToolsActivePort');for(let i=0;i<100&&!fs.existsSync(active);i++)await pause(100);check(fs.existsSync(active),'owned isolated Chrome starts');
  const port=Number(fs.readFileSync(active,'utf8').split('\n')[0]),targets=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();connection=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{connection.addEventListener('open',resolve,{once:true});connection.addEventListener('error',reject,{once:true});});
  connection.addEventListener('message',message=>{const item=JSON.parse(message.data);if(item.id&&pending.has(item.id)){const task=pending.get(item.id);pending.delete(item.id);item.error?task.reject(Error(JSON.stringify(item.error))):task.resolve(item.result);}else{events.push(item);if(item.method==='Fetch.requestPaused')intercepted(item).catch(error=>interceptionErrors.push(error.stack));}});
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');await send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`
    window.__opsFixtureStreams=[];window.__opsFixtureState=null;window.__opsLastExport=null;
    window.EventSource=class{constructor(url){this.url=url;this.listeners={};window.__opsFixtureStreams.push(this);setTimeout(()=>{for(const fn of this.listeners.open||[])fn({});},0);}addEventListener(key,fn){(this.listeners[key]||=[]).push(fn);}close(){this.closed=true;}};
    window.__opsFixtureEmit=state=>{window.__opsFixtureState=state;const value={...state,generatedAt:new Date().toISOString()};for(const stream of window.__opsFixtureStreams)if(!stream.closed)for(const fn of stream.listeners.state||[])fn({data:JSON.stringify(value)});};
    setInterval(()=>{if(window.__opsFixtureState)window.__opsFixtureEmit(window.__opsFixtureState);},2000);
    const blobs=new Map(),make=URL.createObjectURL.bind(URL);URL.createObjectURL=blob=>{const url=make(blob);blobs.set(url,blob);return url;};
    const original=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if(this.download&&blobs.has(this.href)){window.__opsLastExport=blobs.get(this.href).text().then(text=>({name:this.download,data:JSON.parse(text)}));return;}return original.call(this);};
  `});
  await send('Emulation.setDeviceMetricsOverride',{width:1660,height:1200,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url:origin+'/#journal'});
  await waitFor("window.LotusimAlerts&&document.getElementById('eventCount').textContent==='20 événements'");await emit(fixture);
  check(await evaluate("document.getElementById('alertCount').textContent==='9'"),'seven unique warnings plus two errors are counted without the duplicate');
  check(await evaluate("document.getElementById('globalNotice').hidden"),'global warning wall is replaced by the compact alert control');
  check(await evaluate("!document.getElementById('alertItems').textContent.includes('ARCHIVED_FAILURE_MUST_NOT_ALERT')"),'an archived failed job never becomes a fresh incident');
  await click('alertToggle');check(await evaluate("document.getElementById('alertCenter').open"),'native alert disclosure opens');
  for(let i=1;i<=7;i++)check(await evaluate(`document.getElementById('alertItems').textContent.includes('Avertissement de démonstration ${i}')`),'warning '+i+' remains accessible beyond the old three-warning limit');
  check(await evaluate("document.querySelectorAll('#alertItems .alert-group').length===3"),'points are grouped by collector, diagnostic and services');
  await evaluate("window.__opsHeldGroup=document.querySelector('#alertItems details');window.__opsHeldGroup.open=false");await emit(fixture);
  check(await evaluate("window.__opsHeldGroup===document.querySelector('#alertItems details')&&!window.__opsHeldGroup.open&&document.getElementById('alertCenter').open"),'unchanged state does not rebuild or reopen the disclosure');
  await set('alertFilter','error');check(await evaluate("document.querySelectorAll('#alertItems .alert-entry').length===2"),'severity filter isolates both errors');await set('alertFilter','all');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
  check(await evaluate("!document.getElementById('alertCenter').open&&document.activeElement.id==='alertToggle'"),'Escape closes the panel and restores keyboard focus');
  await click('alertToggle');await click('alertJournal');check(await evaluate("location.hash==='#journal'&&!document.getElementById('alertCenter').open"),'journal shortcut closes the alert disclosure');
  const dangerous='<img src=x onerror="window.__opsXss=true"> '+('Détail métier conservé. '.repeat(12));
  await evaluate(`window.LotusimAlerts.notify(document.getElementById('settingsNotice'),${JSON.stringify(dangerous)},'error',{source:'Paramétrage',route:'settings',label:'Action refusée'})`);
  check(await evaluate("document.getElementById('alertCount').textContent==='10'"),'an explicit action failure joins the same alert center');
  check(await evaluate("!document.querySelector('#settingsNotice details').open&&document.querySelector('#settingsNotice .feedback-excerpt').textContent.length<=155"),'long failure remains summarized with expandable details');
  check(await evaluate("document.querySelector('#settingsNotice strong').textContent.includes('Action refusée')&&document.querySelector('#settingsNotice strong').textContent.includes('Erreur')&&document.querySelectorAll('#settingsNotice img').length===0&&!window.__opsXss"),'blocking action label and severity stay visible and message markup cannot execute');
  await evaluate("document.querySelector('#settingsNotice summary').click()");check(await evaluate("document.querySelector('#settingsNotice details').open&&document.querySelector('#settingsNotice p').textContent.length>200"),'full error remains available on demand');
  await evaluate("window.LotusimAlerts.notify(document.getElementById('settingsNotice'),'Action terminée','success',{source:'Paramétrage',route:'settings'})");check(await evaluate("document.getElementById('alertCount').textContent==='9'"),'success clears the corresponding stale action alert');
  await evaluate("document.getElementById('journalRows').scrollTop=100;window.__opsFrozenScroll=document.getElementById('journalRows').scrollTop;window.__opsFrozenFirst=document.getElementById('journalRows').firstElementChild;window.__opsFrozenText=document.getElementById('journalRows').textContent");
  await click('journalPause');const recent={id:'fixture-new',at:new Date().toISOString(),source:'vision-fixture',level:'info',message:'Nouvelle observation pendant la lecture',historical:false};
  const updated={...fixture,events:[recent,...baseEvents.map((e,i)=>({...e,id:'rekey-'+i}))],capture:{...fixture.capture,captured:3}};await emit(updated);
  await waitFor("document.getElementById('captureKpi').textContent==='3/ 10'");
  check(await evaluate("document.getElementById('journalRows').textContent===window.__opsFrozenText&&document.getElementById('journalRows').firstElementChild===window.__opsFrozenFirst&&document.getElementById('journalRows').scrollTop===window.__opsFrozenScroll"),'freeze preserves content, row identity and scroll while new data arrives');
  check(await evaluate("document.getElementById('journalPending').textContent.startsWith('1 nouvel événement')"),'pending counter uses stable observation keys instead of reindexed producer IDs');
  check(await evaluate("document.getElementById('journalSnapshot').textContent.includes('collecte et indicateurs non suspendus')&&document.getElementById('journalPause').getAttribute('aria-pressed')==='true'"),'freeze scope is explicit and never pauses collection or the simulation');
  await set('eventLevel','error');check(await evaluate("document.getElementById('eventCount').textContent==='1 événement'"),'existing filters continue to operate on the frozen snapshot');await click('journalExport');
  const exported=await evaluate('window.__opsLastExport');check(exported.data.events.length===1&&exported.data.provenance.displayFrozen===true&&exported.data.filters.level==='error','local export contains only filtered frozen observations');
  check(exported.data.provenance.maximumSnapshotEvents===80&&exported.data.provenance.exhaustiveHistory===false&&exported.data.displayTimeZone==='Europe/Paris','export has bounded, non-exhaustive provenance and Paris display time');
  check(!JSON.stringify(exported.data).includes('NOT_EXPORTED')&&!('capture'in exported.data)&&!('preview'in exported.data),'export includes neither private extra fields nor images/full service state');
  await set('eventLevel','all');await shot('journal-frozen-desktop.png');await click('journalResume');
  check(await evaluate("document.getElementById('journalRows').textContent.includes('Nouvelle observation pendant la lecture')&&document.getElementById('journalPause').getAttribute('aria-pressed')==='false'"),'resume displays the latest available snapshot');
  await evaluate("document.querySelector('[data-route=settings]').click()");await waitFor("!document.getElementById('settingsEditor').hidden");
  check(await evaluate("!!document.querySelector('#settingsEngineNote details.context-details')&&!document.querySelector('#settingsEngineNote details.context-details').open"),'engine capabilities and limitations are initially folded');
  check(await evaluate("document.querySelectorAll('#settingsEngineNote .settings-engine-states>span').length===3"),'short engine status badges remain visible');await evaluate("document.getElementById('settingsEngineNote').scrollIntoView({block:'center'})");await shot('settings-context-desktop.png');
  await evaluate("document.querySelector('[data-route=traffic]').click()");await waitFor("!document.getElementById('trafficWorkspace').hidden");
  const ready=plansBefore.plans.find(p=>p.ready);if(ready){await set('trafficPlanChoice',ready.id);await waitFor(`document.getElementById('trafficPlanChoice').value==='${ready.id}'&&!document.getElementById('trafficPlanChoice').disabled`);check(await evaluate("!document.getElementById('trafficAuditDetails').hidden&&!document.getElementById('trafficAuditDetails').open"),'approved limited audit is available without an expanded warning wall');}
  check(await evaluate("getComputedStyle(document.getElementById('trafficNotice')).backgroundColor==='rgb(16, 38, 51)'"),'informational traffic notice uses a neutral background instead of warning orange');
  await evaluate("document.getElementById('trafficSource').scrollIntoView({block:'center'})");await shot('traffic-context-desktop.png');
  await evaluate("document.querySelector('[data-route=journal]').click();window.scrollTo(0,0)");await click('alertToggle');await shot('alerts-open-desktop.png');
  await send('Emulation.setDeviceMetricsOverride',{width:430,height:1050,deviceScaleFactor:1,mobile:true});await evaluate('window.scrollTo(0,0)');
  await waitFor("document.querySelector('.alerts-panel').getBoundingClientRect().top>=document.getElementById('alertToggle').getBoundingClientRect().bottom");
  check(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile journal and alert panel have no horizontal overflow');
  check(await evaluate("(()=>{const r=document.querySelector('.alerts-panel').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})()"),'mobile alert panel remains inside the viewport');await shot('alerts-open-mobile.png');
  check(await evaluate("(()=>{const panel=document.querySelector('.alerts-panel').getBoundingClientRect(),toggle=document.getElementById('alertToggle').getBoundingClientRect();return panel.top>=toggle.bottom&&panel.bottom<=innerHeight;})()"),'mobile alert panel starts below its control and remains bounded by the viewport');
  await click('alertClose');await shot('journal-mobile.png');
  const plansAfter=await get('/api/traffic/plans'),enginesAfter=await get('/api/engines');
  check(JSON.stringify(plansAfter.plans.map(p=>[p.id,p.planSha256]))===JSON.stringify(plansBefore.plans.map(p=>[p.id,p.planSha256])),'production library records remain unchanged');
  check(enginesAfter.selectedEngine.id===enginesBefore.selectedEngine.id,'production engine selection remains unchanged');
  check(blockedWrites.length===0,'the tested journey attempts no server mutation');
  const errors=events.filter(e=>e.method==='Runtime.exceptionThrown').map(e=>e.params.exceptionDetails?.exception?.description||e.params.exceptionDetails?.text);
  check(errors.length===0&&interceptionErrors.length===0,'no browser JavaScript or interception errors');
  const result={passed:true,checks,evidence:'Explicit browser-only state/EventSource fixtures; stage UI resources; production reads limited to GET. No Unity, ROS, simulation, generation or real server mutation.',realServerMutations:0,blockedWrites,errors,screenshots};fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
})().catch(error=>{const result={passed:false,checks,error:error.stack,interceptionErrors,screenshots};fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));console.error(JSON.stringify(result,null,2));process.exitCode=1;}).finally(async()=>{if(connection){try{await send('Browser.close');}catch(_){}connection.close();}if(browser&&!browser.killed)browser.kill('SIGTERM');});
