/* Local fixture tests: no Docker, Unity, network, or external dependencies. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ui=path.resolve(process.argv[2]||path.join(__dirname,'../tools/ops_dashboard_ui'));
const helpers=require(path.join(ui,'settings.js'));
let checks=0;
const check=(condition,message)=>{assert.ok(condition,message);checks++;};
const approx=(value,expected,message)=>check(Math.abs(value-expected)<1e-6,message);
const camera={width:1920,height:1080,verticalFovDeg:60,farClipM:60000,station:'bridge',viewHeadingDeg:0,viewDownPitchDeg:0};
const buoy={model:'buoy',label:'Bouée',domain:'moored',heightM:3,maxSpeedMps:0,rangeM:[20,100],altitudeM:[0,0],speedUnit:'kn',speedMin:0};
const drone={model:'small_drone',label:'Petit drone',domain:'air',heightM:.3,maxSpeedMps:15,maxAltitudeM:120,rangeM:[50,200],altitudeM:[40,80],speedUnit:'mps',speedMin:3};
approx(helpers.projectedHeight(camera,buoy,100),28.059223082615814,'pinhole apparent height uses vertical FOV');
approx(helpers.distanceForPixels(camera,buoy,28.059223082615814),100,'pixel-height mode computes distance, no rescaling');
check(helpers.projectedHeight(camera,buoy,0)===null,'zero range is not projected');
check(helpers.projectedHeight({...camera,verticalFovDeg:180},buoy,100)===null,'invalid FOV is rejected');
check(helpers.projectedHeight(camera,{heightM:null},100)===null,'missing model height is not invented');
check(helpers.distanceForPixels(camera,buoy,0)===null,'zero pixels has no computed range');
approx(helpers.projectedHeight({...camera,height:2160},buoy,100),2*helpers.projectedHeight(camera,buoy,100),'higher image resolution doubles apparent height');
check(helpers.defaultObject(buoy,'fixture').speedMps===0,'moored objects remain stationary');
check(helpers.defaultObject(drone,'fixture').altitudeM===60,'airborne default altitude uses catalogue range');
check(helpers.defaultObject({...drone,speedMin:500,speedUnit:'kmh'},'fixture').speedMps===15,'default speed cannot exceed catalogue hypothesis');
check(helpers.speedPresentation(drone).unit==='km/h'&&helpers.speedPresentation(buoy).unit==='nœuds','air and sea speed units are explicit');
check(helpers.displaySpeed(7,7,helpers.KNOT)<=7/helpers.KNOT,'unit display rounding never exceeds the exact speed ceiling');
const environment={timeOfDay:'day',cloudCover:.2,rainIntensity:0,waveHeightM:2,waveDirectionDeg:45,windMps:6};
const object={id:'object1',model:'buoy',count:2,distanceM:100,bearingDeg:0,spreadDeg:5,altitudeM:0,speedMps:0,headingDeg:0,distanceMode:'metres'};
const campaign={schema:helpers.SCHEMA,name:'Fixture contrôlée',engine:'unity',scene:'maritime_manual',seed:42,totalImages:10,camera,
  observer:{speedMps:5,headingDeg:0,rollMaxDeg:3,pitchMaxDeg:2},sensors:{rgb:true,thermal:false,nightVision:false},
  blocks:[{id:'day',name:'Jour',images:3,environment,objects:[object]},
    {id:'night',name:'Nuit',images:5,environment:{...environment,timeOfDay:'night'},objects:[]},
    {id:'dusk',name:'Crépuscule',images:2,environment:{...environment,timeOfDay:'dusk'},objects:[{...object,id:'object2',count:1}]}]};
const sum=helpers.totals(campaign);
check(sum.allocatedImages===10&&sum.blocks===3,'image budget sums blocks exactly');
check(sum.objectImageCounts.buoy===8,'object-image counts are not mistaken for guaranteed detections');
check(helpers.totals(null).allocatedImages===0,'empty configuration is handled');

const html=fs.readFileSync(path.join(ui,'index.html'),'utf8'),app=fs.readFileSync(path.join(ui,'app.js'),'utf8'),script=fs.readFileSync(path.join(ui,'settings.js'),'utf8');
check(html.includes('data-route="settings"')&&html.includes('id="page-settings"'),'fifth navigation section exists');
check(/settings:\s*\[/.test(app),'settings participates in existing real route navigation');
check(!/method\s*:\s*['"]POST/.test(app),'monitoring app remains read-only');
check(script.includes("'X-LOTUSim-Settings':'1'"),'settings writes carry the local CSRF header');
check(!script.includes('innerHTML')&&!script.includes('eval('),'untrusted imports are not rendered as HTML/code');
check(script.includes("fetch('/api/settings/'+kind"),'writes remain scoped to settings API');

const ids={};
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.parentElement=null;this.dataset={};this.style={};this.attributes={};this.listeners={};this.hidden=false;this.disabled=false;this.checked=false;this._value='';this._text='';this._class='';
    this.classList={contains:name=>this._class.split(' ').includes(name),toggle:(name,on)=>{const set=new Set(this._class.split(' ').filter(Boolean));if(on===undefined)on=!set.has(name);on?set.add(name):set.delete(name);this._class=[...set].join(' ');},add:(name)=>{this._class+=' '+name;},remove:(name)=>{this._class=this._class.split(' ').filter(x=>x!==name).join(' ');}};}
  set id(value){this._id=value;ids[value]=this;}get id(){return this._id;}
  set className(value){this._class=value;}get className(){return this._class;}
  set textContent(value){this._text=String(value);this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent||'').join('');}
  set value(value){this._value=String(value);}get value(){return this._value;}
  append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this._text='';this.children=[];this.append(...children);}
  querySelectorAll(selector){const selectors=selector.split(',').map(x=>x.trim());const match=node=>selectors.some(item=>item==='select[data-config-path$=".model"]'?node.tagName==='SELECT'&&node.dataset.configPath?.endsWith('.model'):item.startsWith('.')?node.className.split(' ').includes(item.slice(1)):item.startsWith('#')?node.id===item.slice(1):node.tagName===item.toUpperCase());const results=[];const visit=node=>{for(const child of node.children){if(match(child))results.push(child);visit(child);}};visit(this);return results;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  addEventListener(key,fn){(this.listeners[key]||=[]).push(fn);}
  setAttribute(key,value){this.attributes[key]=String(value);}
  async dispatch(key){for(const fn of this.listeners[key]||[])await fn({target:this,preventDefault(){}});}
  insertAdjacentElement(position,node){assert.equal(position,'afterend');const siblings=this.parentElement.children;node.parentElement=this.parentElement;siblings.splice(siblings.indexOf(this)+1,0,node);}
  click(){if(!this.disabled)return this.dispatch('click');}
  focus(){this.focused=true;}remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);}
  checkValidity(){return true;}reportValidity(){return true;}
  get lastElementChild(){return this.children[this.children.length-1];}
}
for(const item of html.matchAll(/id="([^"]+)"/g)){const node=new Element();node.id=item[1];}
const body=new Element('body'),editor=ids.settingsEditor;
for(const node of Object.values(ids))body.append(node);
for(const id of ['settingsIdentityFields','settingsCameraFields','settingsObserverFields','settingsSensors','settingsBlocks','settingsValidate','settingsSave','settingsPrepare','settingsLoad','settingsSaved'])editor.append(ids[id]);
ids.settingsLoading.append(new Element('strong'),new Element('p'));
const allocationParent=new Element();allocationParent.append(ids.settingsAllocationFill);
const catalog={schema:'fixture-catalog',engines:[{id:'unity',label:'Unity',available:true,detail:'Connecteur local'},{id:'unreal',label:'Unreal',available:false,detail:'Non installé'}],
  scenes:[{id:'maritime_manual',engine:'unity',label:'Mer contrôlée',path:'fixture.unity'}],assets:[buoy,drone],defaults:campaign,campaigns:[{id:'saved-1',name:'Enregistrée'}]};
const generic=(id,label)=>({id,label,available:true,preparationAvailable:true,runtimeDetected:false,nativeValidated:false,mode:'neutral_contract_only',detail:'Contrat de scène uniquement ; aucun SDK ni moteur intégré.',capabilities:{scenePreparation:false,neutralExport:true,rgbCapture:false,annotations:false,livePoses:false,waves:false}});
const registry={schema:'lotusim-engine-catalog-1',selectedEngine:catalog.engines[0],engines:[...catalog.engines,generic('godot','Godot'),generic('blender','Blender'),generic('o3de','O3DE')]};
const requests=[],dispatched=[];let seq=0,trafficRefused=false;
const fetch=async(url,options={})=>{
  requests.push({url,options});let data;
  if(url==='/api/traffic/generate'){
    if(trafficRefused)return {ok:false,status:400,json:async()=>({errors:[{path:'blockId',message:'Contraintes coopératives incompatibles.'}]})};
    data={id:'00000000-0000-4000-8000-000000000099',planId:'00000000-0000-4000-8000-000000000099',record:{ready:true,auditStatus:'approved'},preview:{applied:false},applied:false};
  }
  else if(url==='/api/engines')data=registry;
  else if(url==='/api/engines/select'){
    const selection=JSON.parse(options.body);let selected=registry.engines.find(engine=>engine.id===selection.engine);
    if(selection.engine==='custom'){selected=generic('custom-aabbccddeeff1122',selection.name);registry.engines.push(selected);}
    registry.selectedEngine=selected;catalog.engines=registry.engines;catalog.selectedEngine=selected;catalog.defaults={...catalog.defaults,engine:selected.id};
    catalog.scenes=registry.engines.map(engine=>({id:'maritime_manual',engine:engine.id,label:'Profil · '+engine.label}));data=registry;
  }
  else if(url==='/api/settings/catalog')data=catalog;
  else if(url==='/api/settings/campaigns')data={campaigns:[{id:'saved-1',name:'Enregistrée'}]};
  else if(url==='/api/settings/campaigns/saved-1')data={campaign};
  else if(url.startsWith('/api/settings/')){
    const input=JSON.parse(options.body),stats=helpers.totals(input),valid=stats.totalImages===stats.allocatedImages;
    data={valid,campaign:valid?input:null,errors:valid?[]:[{path:'blocks',message:'La somme des images ne correspond pas au total.'}],warnings:[],summary:stats};
    if(url.endsWith('/save')||url.endsWith('/prepare'))data.id='saved-1';
    if(url.endsWith('/prepare')){data.downloadUrl='/api/settings/prepared/saved-1/campaign.json';data.manifestUrl='/api/settings/prepared/saved-1/manifest.json';
      if(input.engine!=='unity'&&input.engine!=='unreal'){data.bundleUrl='/api/settings/prepared/saved-1/bundle.zip';data.engineActions={engine:input.engine,nativeValidated:false,runtimeDetected:false,instructions:['Contrat neutre : développer et valider un adaptateur avant toute capture.'],files:[{name:'scene-contract.json',label:'Contrat de scène'},{name:'adapter-requirements.json',label:'Exigences d’adaptation'},{name:'engine-instructions.txt',label:'Instructions moteur'}]};}
    }
  }else throw Error('Unexpected URL '+url);
  return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(data))};
};
const windows={},location={hash:'#settings',origin:'http://127.0.0.1:8798'};
const sandbox={document:{body,getElementById:id=>ids[id]||null,createElement:tag=>new Element(tag),createTextNode:text=>{const node=new Element('text');node.textContent=text;return node;}},
  window:{confirm:()=>true,addEventListener:(name,fn)=>windows[name]=fn,dispatchEvent:event=>{dispatched.push(event);return windows[event.type]?.(event);}},CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail;}},location,fetch,URL,Blob,Intl,Date,console,Number,Array,Object,Set,Map,Math,String,JSON,crypto:{randomUUID:()=>String(++seq)},setTimeout:()=>1,
  // Browser catalogue polling is registered, not run by this deterministic fixture.
  setInterval:()=>1};
const settle=()=>new Promise(setImmediate);
(async()=>{
  vm.runInNewContext(script,sandbox,{filename:'settings.js'});await settle();
  check(requests[0].url==='/api/settings/catalog','opens by loading the local catalogue');
  check(!ids.settingsEditor.hidden&&ids.settingsBlocks.children.length===3,'three control blocks render');
  check(ids.settingsAllocated.textContent==='10','initial budget uses actual configuration');
  check(ids['settings-field-camera-height'].value==='1080','camera resolution loaded');
  check(!ids.settingsPrepare.disabled,'available Unity adapter can prepare');
  check(ids['settings-field-block-0-object-0-speed-range'].disabled&&ids['settings-field-block-0-object-0-speed-range'].max==='0','moored model has a disabled zero-speed slider');
  const observerRange=ids['settings-field-observer-speed-range'];observerRange.value='10';await observerRange.dispatch('input');
  check(ids['settings-field-observer-speed'].value==='10','observer speed slider updates precise number field');
  ids['settings-field-observer-speed'].value='8.25';await ids['settings-field-observer-speed'].dispatch('input');
  check(ids['settings-field-observer-speed-range'].value==='8.25','precise number edit synchronizes speed slider');
  check(observerRange.attributes['aria-label'].includes('observateur'),'speed slider has explicit accessible label');
  check(ids.settingsSensors.querySelectorAll('input').every(input=>input.disabled),'manual campaign sensor availability is explicit');
  ids['settings-field-block-0-images'].value='4';await ids['settings-field-block-0-images'].dispatch('input');
  check(ids.settingsAllocated.textContent==='11'&&ids.settingsAllocationDetail.textContent.includes('en trop'),'editing a block updates exact image budget');
  await ids.settingsValidate.click();
  check(ids.settingsValidation.textContent.includes('ne correspond pas'),'validator errors remain visible');
  ids['settings-field-total'].value='11';await ids['settings-field-total'].dispatch('input');
  await ids.settingsSave.click();
  const saved=requests.find(item=>item.url==='/api/settings/save');
  check(saved.options.headers['X-LOTUSim-Settings']==='1'&&saved.options.headers['Content-Type']==='application/json','settings CSRF and JSON headers are sent');
  check(JSON.parse(saved.options.body).totalImages===11,'campaign is direct JSON body, not nested envelope');
  check(ids.settingsDraftBadge.textContent==='Enregistré localement','save acknowledges local persistence');
  ids['settings-field-block-0-object-0-model'].value='small_drone';await ids['settings-field-block-0-object-0-model'].dispatch('change');
  const droneRange=ids['settings-field-block-0-object-0-speed-range'];
  check(!droneRange.disabled&&droneRange.max==='54','vehicle speed slider uses exact catalogue ceiling in km/h');
  droneRange.value='36';await droneRange.dispatch('input');
  check(ids['settings-field-block-0-object-0-speed'].value==='36','vehicle slider updates number field');
  await ids.settingsValidate.click();
  const speedPayload=JSON.parse(requests.findLast(item=>item.url==='/api/settings/validate').options.body);
  check(speedPayload.blocks[0].objects[0].speedMps===10,'slider value converts km/h to stored m/s');
  ids['settings-field-block-0-object-0-model'].value='buoy';await ids['settings-field-block-0-object-0-model'].dispatch('change');
  check(ids['settings-field-block-0-object-0-speed'].value==='0'&&ids['settings-field-block-0-object-0-speed-range'].disabled,'switching back to moored model resets speed to zero');
  const mode=ids['settings-field-block-0-object-0-mode'];mode.value='pixel_height';await mode.dispatch('change');
  const pixels=ids['settings-field-block-0-object-0-pixels'];pixels.value='50';await pixels.dispatch('input');
  check(ids.settingsBlocks.textContent.includes('Distance calculée'),'pixel-height mode explains its computed distance');
  await ids.settingsPrepare.click();
  const prepared=requests.findLast(item=>item.url==='/api/settings/prepare'),payload=JSON.parse(prepared.options.body);
  approx(payload.blocks[0].objects[0].distanceM,roundExpected(helpers.distanceForPixels(camera,buoy,50)),'prepared pixel mode adjusts distance only');
  check(payload.blocks[0].objects[0].model==='buoy'&&!('scale' in payload.blocks[0].objects[0]),'pixel mode never adds model rescaling');
  check(!ids.settingsPrepared.hidden&&ids.settingsPrepared.querySelectorAll('a').length===2,'prepared campaign and manifest are separately downloadable');
  check(ids.settingsPrepared.textContent.includes('Manual campaigns > Import prepared campaign'),'prepared instructions specify Unity import menu');
  check(ids.settingsPrepared.textContent.includes('Sélectionner manifest.json')&&!ids.settingsPrepared.textContent.includes('Sélectionner campaign.json'),'Unity import instructions select the manifest, never campaign.json');
  ids['settings-field-engine'].value='unreal';await ids['settings-field-engine'].dispatch('change');
  check(ids.settingsPrepare.disabled&&ids.settingsEngineNote.textContent.includes('aucun adaptateur'),'Unreal unavailability is honest and prevents prepare');
  check(!ids.settingsExport.disabled,'Unreal JSON export stays available');
  await ids.settingsAddBlock.click();
  check(ids.settingsBlocks.children.length===4,'adding a new block works');
  check(requests.every(item=>item.url.startsWith('/api/settings/')||item.url==='/api/engines'&&!item.options.method),'campaign and read-only profile requests stay within their exact local APIs');
  check(ids.engineProfileCurrent.textContent==='Unity','persisted project profile is displayed independently');
  check(ids.engineProfileChoice.children.some(option=>option.value==='godot')&&ids.engineProfileChoice.children.some(option=>option.value==='custom'),'registry built-ins and named profile creation are available');
  ids['settings-field-engine'].value='unity';await ids['settings-field-engine'].dispatch('change');
  ids['settings-field-name'].value='Brouillon indépendant';await ids['settings-field-name'].dispatch('input');
  ids['settings-field-seed'].value='2468';await ids['settings-field-seed'].dispatch('input');
  const savedName=ids['settings-field-name'],savedWave=ids['settings-field-block-0-waveHeightM'];
  ids.engineProfileChoice.value='godot';await ids.engineProfileChoice.dispatch('change');
  check(ids.engineProfileCurrent.textContent==='Unity'&&!requests.some(item=>item.url==='/api/engines/select'),'choosing a profile does not persist it before explicit apply');
  await ids.engineProfileForm.dispatch('submit');
  const selected=requests.findLast(item=>item.url==='/api/engines/select');
  check(JSON.stringify(JSON.parse(selected.options.body))==='{"engine":"godot"}'&&selected.options.headers['X-LOTUSim-Engines']==='1','profile apply uses exact local payload and intent header');
  check(ids.engineProfileCurrent.textContent==='Godot'&&ids.engineProfileMode.textContent==='Contrat neutre uniquement','applied profile is persisted and clearly contract-only');
  check(ids['settings-field-engine'].value==='unity'&&ids['settings-field-name']===savedName&&ids['settings-field-block-0-waveHeightM']===savedWave,'profile apply never changes campaign engine or destroys current edit nodes');
  check(ids['settings-field-name'].value==='Brouillon indépendant'&&ids['settings-field-seed'].value==='2468'&&ids.settingsBlocks.children.length===4,'profile apply preserves all dirty campaign values and blocks');
  check(ids.engineProfileNotice.textContent.includes('Le moteur et les paramètres du brouillon de campagne sont conservés'),'profile notice explicitly distinguishes project profile and campaign');
  await ids.engineProfileReload.click();
  check(ids.engineProfileCurrent.textContent==='Godot'&&ids['settings-field-engine'].value==='unity','profile reload shows persisted choice without changing current campaign');
  ids.engineProfileChoice.value='custom';await ids.engineProfileChoice.dispatch('change');
  check(!ids.engineProfileCustomField.hidden&&ids.engineProfileCustomName.required,'named engine input is shown only for custom selection');
  const requestsBefore=requests.length;ids.engineProfileCustomName.value='<img src=x onerror=alert(1)>';await ids.engineProfileForm.dispatch('submit');
  check(requests.length===requestsBefore&&ids.engineProfileNotice.textContent.includes('Aucun HTML ni chemin'),'HTML-like custom names are rejected before any write');
  ids.engineProfileCustomName.value='  Mon    moteur 3D  ';await ids.engineProfileForm.dispatch('submit');
  const customRequest=JSON.parse(requests.findLast(item=>item.url==='/api/engines/select').options.body);
  check(customRequest.engine==='custom'&&customRequest.name==='Mon moteur 3D','custom name is normalized without interpreting executable text');
  check(ids.engineProfileCurrent.textContent==='Mon moteur 3D'&&ids['settings-field-engine'].value==='unity','named profile is stored independently of the existing Unity draft');
  ids['settings-field-engine'].value='custom-aabbccddeeff1122';await ids['settings-field-engine'].dispatch('change');
  check(ids.settingsPrepare.textContent==='Exporter le contrat · Mon moteur 3D'&&!ids.settingsPrepare.disabled,'new registry engine requires no new UI code branch to export a contract');
  check(ids.settingsEngineNote.textContent.includes('Contrat neutre uniquement')&&ids.settingsEngineNote.textContent.includes('pas appliqués dans un moteur')&&ids.settingsEngineNote.textContent.includes('Non implémenté'),'no-SDK engine capabilities and unapplied settings are disclosed');
  ids['settings-field-block-3-images'].value='1';await ids['settings-field-block-3-images'].dispatch('input');ids['settings-field-total'].value='12';await ids['settings-field-total'].dispatch('input');
  await ids.settingsPrepare.click();
  check(ids.settingsPrepared.textContent.includes('Contrat de scène uniquement')&&ids.settingsPrepared.textContent.includes('Exigences d’adaptation'),'generic preparation displays contract and adapter requirements');
  check(!ids.settingsPrepared.textContent.includes('Unreal Editor')&&!ids.settingsPrepared.textContent.includes('Manual campaigns > Import prepared campaign'),'generic contract never shows another engine import menu');
  check(requests.filter(item=>item.options.method).every(item=>item.url.startsWith('/api/settings/')||item.url==='/api/engines/select'&&item.options.headers['X-LOTUSim-Engines']==='1'),'all writes remain intent-scoped to campaign settings or explicit profile selection');
  check(html.includes('Bloc à transformer en scénario continu')&&html.includes('value="catalogue"')&&html.includes('value="requested"'),'continuous generation is a separate explicit block/speed-policy workflow');
  ids.settingsTrafficBlock.value='';ids.settingsTrafficDuration.value='60';ids.settingsTrafficProfile.value='crossing';ids.settingsTrafficSpeedPolicy.value='requested';
  const beforeGenerate=requests.length;await ids.settingsGenerateTraffic.click();
  check(requests.length===beforeGenerate&&ids.settingsNotice.textContent.includes('Choisir le bloc'),'multiple image blocks are never silently merged into a traffic plan');
  ids.settingsTrafficBlock.value='day';ids.settingsTrafficDuration.value='0';await ids.settingsGenerateTraffic.click();check(requests.length===beforeGenerate&&ids.settingsNotice.textContent.includes('4 à 600'),'traffic duration has independent validated limits');
  ids.settingsTrafficDuration.value='60';ids['settings-field-total'].value='13';await ids['settings-field-total'].dispatch('input');
  await ids.settingsGenerateTraffic.click();check(!requests.some(item=>item.url==='/api/traffic/generate')&&ids.settingsNotice.textContent.includes('doit être valide'),'invalid current image configuration is rejected before cooperative planning');
  ids['settings-field-total'].value='12';await ids['settings-field-total'].dispatch('input');
  const rgbPrepareCount=requests.filter(item=>item.url==='/api/settings/prepare').length,nameNode=ids['settings-field-name'],waveNode=ids['settings-field-block-0-waveHeightM'];
  await ids.settingsGenerateTraffic.click();const generated=requests.findLast(item=>item.url==='/api/traffic/generate'),input=JSON.parse(generated.options.body);
  check(requests.at(-2).url==='/api/settings/validate'&&generated.url==='/api/traffic/generate','current campaign is validated immediately before scenario generation');
  check(generated.options.headers['X-LOTUSim-Traffic']==='1'&&input.blockId==='day'&&input.actionProfile==='crossing'&&input.durationSeconds===60,'scenario generation is explicit and pins the selected block and temporal profile');
  check(input.speedPolicy==='requested'&&input.headingPolicy==='profile'&&input.campaign.blocks.length===4,'speed zero preservation is explicit while headings are delegated to the selected profile');
  check(input.name==='Brouillon indépendant'&&input.seed===2468&&input.campaign.engine==='custom-aabbccddeeff1122','scenario uses the actual current validated campaign, not project defaults');
  check(input.capture.mode==='count'&&input.capture.count===input.campaign.blocks.find(block=>block.id===input.blockId).images,'default continuous count comes from the chosen block without changing the campaign');
  check(requests.filter(item=>item.url==='/api/settings/prepare').length===rgbPrepareCount,'cooperative generation does not prepare or launch the independent-image campaign');
  check(ids['settings-field-name']===nameNode&&ids['settings-field-block-0-waveHeightM']===waveNode&&nameNode.value==='Brouillon indépendant','successful generation preserves current image draft and input nodes');
  check(location.hash==='#traffic'&&dispatched.findLast(event=>event.type==='lotusim-traffic-plan-selected').detail.planId==='00000000-0000-4000-8000-000000000099','success navigates to traffic with the new persisted plan ID');
  location.hash='#settings';trafficRefused=true;await ids.settingsGenerateTraffic.click();
  check(location.hash==='#settings'&&ids.settingsNotice.textContent.includes('Contraintes coopératives incompatibles')&&ids['settings-field-name']===nameNode,'unsafe constraints are refused without replacing the image draft or navigating to a fake plan');
  check(!ids.settingsGenerateTraffic.disabled,'generation control becomes usable again after a planner refusal');
  trafficRefused=false;ids.settingsTrafficCaptureMode.value='interval';await ids.settingsTrafficCaptureMode.dispatch('change');ids.settingsTrafficCaptureInterval.value='2';await ids.settingsTrafficCaptureInterval.dispatch('input');
  check(ids.settingsTrafficCapturePreview.textContent.includes('30 photos prévues')&&ids.settingsTrafficCapturePreview.textContent.includes('58 s simulées')&&ids.settingsTrafficCaptureCount.disabled&&!ids.settingsTrafficCaptureInterval.disabled,'interval mode previews an endpoint-exclusive schedule and ignores its inactive count input');
  const beforeInterval=JSON.stringify(input.campaign);await ids.settingsGenerateTraffic.click();const intervalInput=JSON.parse(requests.findLast(item=>item.url==='/api/traffic/generate').options.body);
  check(intervalInput.capture.mode==='interval'&&intervalInput.capture.intervalSeconds===2&&Object.keys(intervalInput.capture).length===2,'only the selected interval policy is sent to the continuous planner');
  check(JSON.stringify(intervalInput.campaign)===beforeInterval,'interval capture never rewrites independent image counts, scene conditions or object quantities');
  ids.settingsTrafficCaptureInterval.value='.01';await ids.settingsTrafficCaptureInterval.dispatch('input');const beforeInvalid=requests.length;await ids.settingsGenerateTraffic.click();check(requests.length===beforeInvalid&&ids.settingsNotice.textContent.includes('intervalle minimum'),'invalid high-rate continuous capture is refused before server requests');
  await ids.settingsValidate.click();check(requests.at(-1).url==='/api/settings/validate'&&ids.settingsNotice.textContent.includes('Configuration vérifiée'),'invalid continuous cadence does not block the independent image validator');
  console.log(checks+' settings-to-cooperative-traffic UI checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
function roundExpected(value){return Math.round(value*1e6)/1e6;}
