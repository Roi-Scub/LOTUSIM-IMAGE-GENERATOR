/* Local fixture tests: no Docker, Unity, network, or external dependencies. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ui=path.resolve(process.argv[2]||path.join(__dirname,'../tools/ops_dashboard_ui'));
const site=path.resolve(process.argv[3]||ui);
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

const html=fs.readFileSync(path.join(site,'index.html'),'utf8'),app=fs.readFileSync(path.join(site,'app.js'),'utf8'),script=fs.readFileSync(path.join(ui,'settings.js'),'utf8');
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
  insertAdjacentElement(position,node){assert.equal(position,'afterend');const siblings=this.parentElement.children;node.parentElement=this.parentElement;siblings.splice(siblings.indexOf(this)+1,0,node);}
  async dispatch(key){for(const fn of this.listeners[key]||[])await fn({target:this});}
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
const requests=[];let seq=0;
const fetch=async(url,options={})=>{
  requests.push({url,options});let data;
  if(url==='/api/engines')data={schema:'lotusim-engine-catalog-1',selectedEngine:catalog.engines[0],engines:catalog.engines};
  else if(url==='/api/settings/catalog')data=catalog;
  else if(url==='/api/settings/campaigns')data={campaigns:[{id:'saved-1',name:'Enregistrée'}]};
  else if(url==='/api/settings/campaigns/saved-1')data={campaign};
  else if(url.startsWith('/api/settings/')){
    const input=JSON.parse(options.body),stats=helpers.totals(input),valid=stats.totalImages===stats.allocatedImages;
    data={valid,campaign:valid?input:null,errors:valid?[]:[{path:'blocks',message:'La somme des images ne correspond pas au total.'}],warnings:[],summary:stats};
    if(url.endsWith('/save')||url.endsWith('/prepare'))data.id='saved-1';
    if(url.endsWith('/prepare')){data.downloadUrl='/api/settings/prepared/saved-1/campaign.json';data.manifestUrl='/api/settings/prepared/saved-1/manifest.json';}
  }else throw Error('Unexpected URL '+url);
    if(url==='/api/settings/prepare'&&JSON.parse(options.body).engine==='unreal'){
      data.bundleUrl='/api/settings/prepared/saved-1/bundle.zip';
      data.engineActions={engine:'unreal',preparationState:'prepared',runtimeDetected:false,nativeValidated:false,scenePath:'/Game/LOTUSim/MaritimePrepared',
        instructions:['Décompresser le bundle Unreal.','Ouvrir un projet Unreal, puis exécuter scene_unreal.py dans l’éditeur.'],
        files:[{name:'scene_unreal.py',label:'Script de scène Unreal',sha256:'a'.repeat(64)},{name:'scene-plan.json',label:'Plan contrôlé'},{name:'../unsafe.py',label:'Never include'}]};
      data.engineAgent={kind:'deterministic_role_pipeline',nativeValidated:false,traces:[{role:'planner',state:'completed',decisions:['Conserver les paramètres physiques déclarés.']},{role:'scene_script_builder',state:'completed',decisions:['Préparer le script Unreal sans l’exécuter.']},{role:'validator',state:'completed',decisions:['Vérifier les fichiers, pas le rendu natif.']}],limitations:['Mer plane ; aucune annotation ni connexion ROS2.','<img src=x onerror=alert(1)> est du texte, pas du HTML.',...Array.from({length:22},(_,i)=>'Limite '+i+' '+('x'.repeat(i===0?4500:1)))]};
    }
  return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(data))};
};
const windows={},location={hash:'#settings',origin:'http://127.0.0.1:8798'};
const sandbox={document:{body,getElementById:id=>ids[id]||null,createElement:tag=>new Element(tag),createTextNode:text=>{const node=new Element('text');node.textContent=text;return node;}},
  window:{confirm:()=>true,addEventListener:(name,fn)=>windows[name]=fn},location,fetch,URL,Blob,Intl,Date,console,Number,Array,Object,Set,Map,Math,String,JSON,crypto:{randomUUID:()=>String(++seq)},setTimeout:()=>1,
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
  // Baseline assertions above remain intact. Now make the preparation-only adapter
  // available without installing or pretending to execute an Unreal runtime.
  ids['settings-field-engine'].value='unity';await ids['settings-field-engine'].dispatch('change');
  ids['settings-field-name'].value='Brouillon à conserver';await ids['settings-field-name'].dispatch('input');
  ids['settings-field-seed'].value='123';await ids['settings-field-seed'].dispatch('input');
  ids['settings-field-block-3-images'].value='1';await ids['settings-field-block-3-images'].dispatch('input');
  ids['settings-field-total'].value='12';await ids['settings-field-total'].dispatch('input');
  const nameNode=ids['settings-field-name'],waveNode=ids['settings-field-block-0-waveHeightM'];
  catalog.engines[1]={id:'unreal',label:'Unreal Engine',available:false,preparationAvailable:true,runtimeDetected:false,nativeValidated:false,
    detail:'Aperçu RGB statique expérimental sur mer plane ; sans connexion ROS2/LOTUSim, sans annotations ni simulation de houle. Paramètres non appliqués : pluie, couverture nuageuse.',
    capabilities:{scenePreparation:true,neutralExport:true,rgbCapture:true,annotations:false,livePoses:false,waves:false}};
  catalog.scenes.push({id:'maritime_manual',engine:'unreal',label:'Mer contrôlée Unreal',path:'/Game/LOTUSim/MaritimePrepared'});
  await windows['lotusim-assets-updated']();await settle();
  check(ids['settings-field-name']===nameNode&&ids['settings-field-block-0-waveHeightM']===waveNode,'catalogue refresh preserves current field nodes');
  check(ids['settings-field-name'].value==='Brouillon à conserver'&&ids['settings-field-seed'].value==='123','catalogue refresh preserves unsaved identity values');
  ids['settings-field-engine'].value='unreal';await ids['settings-field-engine'].dispatch('change');
  check(!ids.settingsPrepare.disabled&&ids.settingsPrepare.textContent==='Préparer pour Unreal Engine','Unreal preparation enables without an installed runtime');
  check(ids['settings-field-scene'].value==='maritime_manual','shared scene id survives engine selection');
  check(ids['settings-field-scene'].children.length===1&&ids['settings-field-scene'].children[0].textContent==='Mer contrôlée Unreal','scene choices filter the selected engine only');
  check(ids['settings-field-name'].value==='Brouillon à conserver'&&ids['settings-field-seed'].value==='123'&&ids['settings-field-total'].value==='12','switching engine preserves user draft');
  check(ids.settingsBlocks.children.length===4&&ids['settings-field-block-0-object-0-pixels'].value==='50','switching engine preserves blocks and placement mode');
  check(ids.settingsEngineNote.textContent.includes('Moteur non détecté')&&ids.settingsEngineNote.textContent.includes('Exécution native non validée'),'Unreal preparation states disclose runtime and native validation limits');
  check(ids.settingsEngineNote.textContent.includes('RGB statique')&&ids.settingsEngineNote.textContent.includes('mer plane')&&ids.settingsEngineNote.textContent.includes('sans connexion ROS2/LOTUSim')&&ids.settingsEngineNote.textContent.includes('sans annotations ni simulation de houle'),'Unreal unsupported capabilities are visible before preparation');
  check(ids.settingsEngineNote.textContent.includes('Paramètres conservés, non appliqués')&&ids.settingsEngineNote.textContent.includes('trajectoires et vitesses')&&ids.settingsEngineNote.textContent.includes('pluie, couverture nuageuse'),'editable unsupported parameters are explicitly retained but not applied');
  check(!ids['settings-field-engine'].textContent.includes('non installé')&&ids['settings-field-engine'].textContent.includes('préparation sans moteur installé'),'engine choice distinguishes preparation from native engine installation');
  await ids.settingsPrepare.click();
  const unrealPayload=JSON.parse(requests.findLast(item=>item.url==='/api/settings/prepare').options.body);
  check(unrealPayload.engine==='unreal'&&unrealPayload.name==='Brouillon à conserver'&&unrealPayload.seed===123,'engine-specific preparation receives unchanged campaign values');
  check(ids.settingsPrepared.textContent.includes('Campagne préparée · Unreal Engine'),'prepared panel names the requested engine');
  check(ids.settingsPrepared.textContent.includes('scene_unreal.py')&&!ids.settingsPrepared.textContent.includes('Manual campaigns > Import prepared campaign'),'Unreal shows its own instructions, never Unity import steps');
  check(ids.settingsPrepared.textContent.includes('Exécution native non validée')&&ids.settingsPrepared.textContent.includes('aucune image ni exécution native validée'),'prepared bundle is not presented as native rendering proof');
  check(ids.settingsPrepared.querySelectorAll('a').some(link=>link.href==='/api/settings/prepared/saved-1/bundle.zip'),'prepared bundle ZIP is downloadable');
  check(ids.settingsPrepared.querySelectorAll('a').some(link=>link.href==='/api/settings/prepared/saved-1/scene_unreal.py'),'inventory links are scoped to the prepared campaign');
  check(!ids.settingsPrepared.textContent.includes('Never include')&&!ids.settingsPrepared.querySelectorAll('a').some(link=>link.href.includes('..')),'unsafe file inventory paths are never linked');
  check(ids.settingsPrepared.textContent.includes('SHA-256 aaaaaaaaaaaa'),'file integrity hashes are visible');
  check(ids.settingsPrepared.textContent.includes('planner')&&ids.settingsPrepared.textContent.includes('scene_script_builder')&&ids.settingsPrepared.textContent.includes('validator'),'deterministic engine-agent trace exposes all three roles');
  check(ids.settingsPrepared.textContent.includes('pas une preuve d’exécution du moteur'),'agent trace is not claimed to execute the engine');
  const limits=ids.settingsPrepared.querySelector('.settings-engine-limits');
  check(limits.children.length===20&&limits.children.every(item=>item.textContent.length<=4000),'adapter limitations list and text are bounded');
  check(limits.textContent.includes('Mer plane ; aucune annotation ni connexion ROS2.'),'native unsupported-feature limitations are shown in the prepared report');
  check(limits.textContent.includes('<img src=x onerror=alert(1)>')&&limits.querySelectorAll('img').length===0,'limitations are rendered as safe text, never HTML');
  check(ids.settingsDraftBadge.textContent==='Préparé pour Unreal Engine','prepared badge names the selected engine');
  ids['settings-field-engine'].value='unity';await ids['settings-field-engine'].dispatch('change');
  check(!ids.settingsPrepare.disabled&&ids['settings-field-name'].value==='Brouillon à conserver'&&ids['settings-field-scene'].value==='maritime_manual','returning to Unity preserves shared scenario and draft');
  check(ids.settingsPrepared.hidden,'changing engine hides stale prepared results');
  check(requests.every(item=>item.url.startsWith('/api/settings/')||item.url==='/api/engines'&&!item.options.method),'campaign requests remain settings-scoped; project registry reads use the exact local GET API');
  console.log(checks+' baseline and dual-engine campaign settings UI checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
function roundExpected(value){return Math.round(value*1e6)/1e6;}
