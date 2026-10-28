'use strict';

(() => {
  const SCHEMA = 'lotusim-campaign-settings-1';
  const KNOT = 1852 / 3600;
  const isNumber = value => typeof value === 'number' && Number.isFinite(value);
  const array = value => Array.isArray(value) ? value : [];
  const clone = value => JSON.parse(JSON.stringify(value));
  const round = (value, digits = 3) => Math.round(value * 10 ** digits) / 10 ** digits;

  // Geometric estimate using horizontal range, not slant distance. It does not
  // predict occlusion, orientation, recognizability or a measured detector score.
  function projectedHeight(camera, asset, distanceM) {
    if (!isNumber(camera?.height) || !isNumber(camera?.verticalFovDeg) || camera.verticalFovDeg <= 0
      || camera.verticalFovDeg >= 180 || !isNumber(asset?.heightM) || asset.heightM <= 0
      || !isNumber(distanceM) || distanceM <= 0) return null;
    return camera.height * asset.heightM / (2 * Math.tan(camera.verticalFovDeg * Math.PI / 360) * distanceM);
  }
  function distanceForPixels(camera, asset, pixels) {
    if (!isNumber(pixels) || pixels <= 0) return null;
    const scale = projectedHeight(camera, asset, 1);
    return scale === null ? null : scale / pixels;
  }
  function totals(campaign) {
    const blocks = array(campaign?.blocks);
    const allocatedImages = blocks.reduce((sum, block) => sum + (isNumber(block.images) ? block.images : 0), 0);
    const objectImageCounts = {};
    for (const block of blocks) for (const object of array(block.objects)) {
      if (typeof object.model !== 'string') continue;
      const count = isNumber(object.count) && isNumber(block.images) ? object.count * block.images : 0;
      objectImageCounts[object.model] = (objectImageCounts[object.model] || 0) + count;
    }
    return {totalImages:campaign?.totalImages, allocatedImages, blocks:blocks.length, objectImageCounts};
  }
  function speedPresentation(asset) {
    return asset?.domain === 'air' ? {unit:'km/h', factor:1 / 3.6} : {unit:'nœuds', factor:KNOT};
  }
  function displaySpeed(speedMps, maximumMps, factor) {
    if(!isNumber(speedMps))return null;
    const displayed=round(speedMps/factor,3);
    return isNumber(maximumMps)&&speedMps<=maximumMps ? Math.min(displayed,maximumMps/factor) : displayed;
  }
  function defaultObject(asset, id) {
    const range = array(asset?.rangeM), altitude = array(asset?.altitudeM);
    const distance = range.length === 2 && range.every(isNumber) ? (range[0] + range[1]) / 2 : 100;
    const defaultAltitude = asset?.domain === 'air' && altitude.length === 2 && altitude.every(isNumber)
      ? (altitude[0] + altitude[1]) / 2 : 0;
    const catalogueSpeed = isNumber(asset?.speedMin) ? asset.speedMin : 0;
    const speedFactor = asset?.speedUnit === 'kmh' ? 1 / 3.6 : asset?.speedUnit === 'kn' ? KNOT : 1;
    const maximum = isNumber(asset?.maxSpeedMps) ? asset.maxSpeedMps : 0;
    return {id, model:asset?.model || '', count:1, distanceM:round(distance), bearingDeg:0, spreadDeg:10,
      altitudeM:round(defaultAltitude), speedMps:round(Math.max(0, Math.min(maximum, catalogueSpeed * speedFactor))),
      headingDeg:0, distanceMode:'metres'};
  }

  function captureCadence(durationSeconds,capture){
    if(typeof durationSeconds!=='number'||!Number.isFinite(durationSeconds)||durationSeconds<4||durationSeconds>600)throw Error('La durée doit être comprise entre 4 et 600 secondes simulées.');
    if(!capture||capture.mode==='legacy')return {mode:'legacy',capture:null,count:null};
    const fraction=value=>{const parts=String(value).toLowerCase().split('e'),mantissa=parts[0],decimals=(mantissa.split('.')[1]||'').length,scale=decimals-Number(parts[1]||0),digits=BigInt(mantissa.replace('.',''));return scale<0?{n:digits*10n**BigInt(-scale),d:1n}:{n:digits,d:10n**BigInt(scale)};};
    const duration=fraction(durationSeconds),fps=30,simulationFrames=Math.ceil(durationSeconds*fps);
    let count,interval=null;
    if(capture.mode==='count'){count=capture.count;if(!Number.isInteger(count)||count<1||count>2000||count>simulationFrames)throw Error('Choisir de 1 à 2 000 images, sans dépasser le nombre de frames moteur disponibles.');}
    else if(capture.mode==='interval'){if(typeof capture.intervalSeconds!=='number'||!Number.isFinite(capture.intervalSeconds)||capture.intervalSeconds<1/30)throw Error('L’intervalle minimum est 1/30 seconde simulée (0,033333… s).');interval=fraction(capture.intervalSeconds);const numerator=duration.n*interval.d,denominator=duration.d*interval.n;count=Number((numerator+denominator-1n)/denominator);if(count>2001)throw Error('Cette cadence dépasse la limite de 2 000 photos ; augmenter l’intervalle ou réduire la durée.');}
    else throw Error('Mode de capture non pris en charge.');
    const frames=[],requestedTimesSeconds=[],effectiveTimesSeconds=[];let maxQuantizationErrorSeconds=0,discardedAtOrAfterEndCount=0;
    for(let index=0;index<count;index++){const numerator=interval?BigInt(index)*interval.n:BigInt(index)*duration.n,denominator=interval?interval.d:duration.d*BigInt(count),frame=Number((2n*numerator*30n+denominator)/(2n*denominator));if(frame>=simulationFrames){discardedAtOrAfterEndCount++;continue;}if(frames.at(-1)===frame)throw Error('Plusieurs prises se confondent sur la grille de 30 images/s : réduire le nombre demandé.');const requested=Number(numerator)/Number(denominator),effective=frame/fps;frames.push(frame);requestedTimesSeconds.push(requested);effectiveTimesSeconds.push(effective);maxQuantizationErrorSeconds=Math.max(maxQuantizationErrorSeconds,Math.abs(effective-requested));}
    if(capture.mode==='count'&&frames.length!==count)throw Error('Ce nombre de prises ne tient pas sur la grille temporelle ; choisir un nombre inférieur.');
    if(frames.length>2000)throw Error('Cette cadence dépasse la limite de 2 000 photos ; augmenter l’intervalle ou réduire la durée.');
    return {mode:capture.mode,capture:{...capture},count:frames.length,fps,simulationFrames,frames,requestedTimesSeconds,effectiveTimesSeconds,maxQuantizationErrorSeconds,discardedAtOrAfterEndCount};
  }
  const math = {SCHEMA,KNOT,projectedHeight,distanceForPixels,totals,speedPresentation,displaySpeed,defaultObject,captureCadence};
  if (typeof module !== 'undefined' && module.exports) module.exports = math;
  if (typeof document === 'undefined') return;

  const $ = id => document.getElementById(id);
  const fmt = (value, digits = 1) => isNumber(value) ? new Intl.NumberFormat('fr-FR', {maximumFractionDigits:digits}).format(value) : '—';
  let catalog = null, draft = null, loaded = false, loading = false, busy = false;
  let dirty = false, revision = 0, currentId = null, lastValidation = null;
  let refreshingCatalog = false;
  let engineRegistry = null, engineProfileLoading = false, engineProfileSaving = false;
  let uidCounter = 0;
  const uid = prefix => prefix + '_' + (globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + '_' + (++uidCounter));
  const savedDisabled = new Map();
  const expandedContext = new Map();
  const palette = ['#65d9bf','#8db9ec','#b7a2e6','#efba6e','#62d5e4','#da9cb7'];
  let trafficCountBlock=null,trafficCountEdited=false;

  function element(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== null && text !== undefined) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  }
  function button(text, callback, className = 'secondary-button') {
    const result = element('button', text, className); result.type = 'button';
    result.addEventListener('click', callback); return result;
  }
  function choice(value, text) { const result = element('option', text); result.value = value; return result; }
  function contextDetails(key, label, count) {
    const details=element('details',null,'context-details');
    details.open=expandedContext.get(key)===true;
    details.addEventListener('toggle',()=>expandedContext.set(key,details.open));
    details.append(element('summary',label+' · '+count+' point'+(count>1?'s':'')));
    return details;
  }
  function assetFor(model) { return array(catalog?.assets).find(asset => asset.model === model); }
  function modelLabel(model) { const asset = assetFor(model); return asset?.label || asset?.model || model || 'Modèle non défini'; }
  function engineFor(id) { return array(catalog?.engines).find(engine => engine.id === id) || array(engineRegistry?.engines).find(engine=>engine.id===id); }
  function canPrepare(engine) { return engine?.preparationAvailable === true || engine?.available === true; }
  function engineLabel(id) { return engineFor(id)?.label || id || 'Moteur'; }
  function contractOnly(engine) { return engine?.mode === 'neutral_contract_only'; }
  function engineChoiceLabel(engine) {
    if (contractOnly(engine)) return engine.label + ' · contrat neutre uniquement';
    if (!canPrepare(engine)) return engine.label + ' · export JSON uniquement';
    if (engine.nativeValidated === true) return engine.label + ' · chaîne native validée';
    if (engine.runtimeDetected === false) return engine.label + ' · préparation sans moteur installé';
    return engine.label + ' · préparation disponible';
  }
  function scenesFor(engine) { return array(catalog?.scenes).filter(scene => scene.engine === engine); }
  function renderEngineNote() {
    const engine = engineFor(draft?.engine), target = $('settingsEngineNote');
    const prepared = canPrepare(engine), runtime = engine?.runtimeDetected, validated = engine?.nativeValidated === true;
    target.replaceChildren(element('strong', engineLabel(draft?.engine)));
    const states=element('span',null,'settings-engine-states');
    states.append(element('span',contractOnly(engine)?'Contrat neutre uniquement':prepared?'Préparation disponible':'Export JSON uniquement',contractOnly(engine)?'warning':prepared?'complete':'warning'),
      element('span',runtime===true?'Moteur détecté':runtime===false?'Moteur non détecté':'Présence du moteur non vérifiée',runtime===true?'complete':'neutral'),
      element('span',validated?'Chaîne native validée':'Exécution native non validée',validated?'complete':'warning'));
    target.append(states);
    const text=typeof engine?.detail==='string'?engine.detail.slice(0,4000):!prepared?'Enregistrement et export possibles ; aucun adaptateur de préparation actif pour ce moteur.' :
      contractOnly(engine)?'Export d’un contrat de scène indépendant du moteur. Aucun SDK, importeur natif, capture ou intégration temps réel n’est fourni par ce profil.' :
      'La préparation produit les fichiers de campagne pour le moteur choisi ; leur présence ne garantit pas un rendu natif valide.';
    const unsupported=[];
    if(!contractOnly(engine)&&engine?.capabilities){
      if(engine.capabilities.waves!==true)unsupported.push('houle');
      if(engine.capabilities.livePoses!==true)unsupported.push('poses temps réel, trajectoires et vitesses');
      if(engine.capabilities.annotations!==true)unsupported.push('annotations');
    }
    const details=contextDetails('campaign-engine-'+(draft?.engine||'unknown'),'Capacités et limites du moteur',
      1+(engine?.capabilities&&typeof engine.capabilities==='object'?6:0)+(!prepared?1:0)+(contractOnly(engine)||unsupported.length?1:0));
    details.append(element('p',text+' Aucun moteur, Play ou scénario ne démarre automatiquement.'));
    if(!prepared)details.append(element('p','Enregistrement et export JSON possibles ; aucun adaptateur de préparation actif pour ce moteur.'));
    renderCapabilities(engine,details,false);
    if(contractOnly(engine))details.append(element('p','Tous les paramètres ci-dessous sont conservés dans le contrat, pas appliqués dans un moteur. Un adaptateur natif reste à développer et à valider avant toute image ou annotation.','settings-engine-warning'));
    else if(engine?.capabilities){
      if(unsupported.length)details.append(element('p','Paramètres conservés, non appliqués par cet adaptateur : '+unsupported.join(' ; ')+'. Les autres limites sont indiquées dans le bundle préparé.','settings-engine-warning'));
    }
    target.append(details);
  }
  function renderCapabilities(engine,target,fold=true){
    const capabilities=engine?.capabilities;if(!capabilities||typeof capabilities!=='object')return;
    const grid=element('dl',null,'settings-engine-capabilities');
    for(const [key,label] of [['scenePreparation','Préparation de scène'],['neutralExport','Contrat neutre'],['rgbCapture','Capture RGB'],['annotations','Annotations'],['livePoses','Poses temps réel'],['waves','Houle']]){
      const available=capabilities[key]===true;
      grid.append(element('dt',label),element('dd',available?'Capacité déclarée':capabilities[key]===false?'Non implémenté':'Non renseigné',available?'available':'unavailable'));
    }
    if(fold){const details=contextDetails('profile-capabilities-'+(engine.id||'unknown'),'Capacités déclarées',6);details.append(grid);target.append(details);}
    else target.append(grid);
  }
  function profileNotice(message,kind=''){
    const target=$('engineProfileNotice');if(!target)return;target.className='notice settings-notice'+(kind?' '+kind:'');
    if(typeof window.LotusimAlerts?.notify==='function')return window.LotusimAlerts.notify(target,message,kind,{source:'Paramétrage',route:'settings',label:'Profil moteur'});
    target.textContent=message;target.hidden=!message;
  }
  function updateProfileChoice(){
    const select=$('engineProfileChoice'),custom=select?.value==='custom';
    if(!select)return;$('engineProfileCustomField').hidden=!custom;$('engineProfileCustomName').required=custom;
    const descriptor=array(engineRegistry?.engines).find(engine=>engine.id===select.value);
    const detail=$('engineProfileChoiceDetail');detail.replaceChildren();
    if(custom)detail.append(element('p','Créer un profil nommé et un contrat neutre uniquement. Un nom ne rend aucun moteur, SDK ni adaptateur disponible.'));
    else if(descriptor){detail.append(element('p',descriptor.detail||'Consulter les capacités déclarées de ce profil.'));renderCapabilities(descriptor,detail);}
    $('engineProfileApply').disabled=busy||engineProfileSaving||!engineRegistry;
  }
  function renderEngineProfile(){
    if(!engineRegistry)return;
    const selected=engineRegistry.selectedEngine,select=$('engineProfileChoice'),previous=select.value;
    select.replaceChildren(...array(engineRegistry.engines).map(engine=>choice(engine.id,engineChoiceLabel(engine))),choice('custom','Autre moteur · profil nommé'));
    select.value=previous==='custom'||array(engineRegistry.engines).some(engine=>engine.id===previous)?previous:selected?.id||'';
    $('engineProfileCurrent').textContent=selected?.label||'Non défini';
    $('engineProfileMode').textContent=contractOnly(selected)?'Contrat neutre uniquement':selected?.nativeValidated===true?'Chaîne native validée':'Profil enregistré · exécution non validée';
    $('engineProfileMode').className='badge '+(contractOnly(selected)?'warning':'neutral');
    $('engineProfileApply').disabled=engineProfileSaving;select.disabled=engineProfileSaving;
    updateProfileChoice();
  }
  async function loadEngineProfile(){
    if(engineProfileLoading||engineProfileSaving||!$('engineProfileChoice'))return;
    engineProfileLoading=true;
    try{
      const result=await getJSON('/api/engines');
      if(!result||!Array.isArray(result.engines)||!result.selectedEngine?.id)throw Error('Registre des moteurs incomplet.');
      engineRegistry=result;renderEngineProfile();profileNotice('');
    }catch(error){profileNotice('Profil moteur non actualisé : '+error.message,'error');}
    finally{engineProfileLoading=false;}
  }
  async function applyEngineProfile(event){
    event.preventDefault();if(engineProfileSaving||!engineRegistry)return;
    if(busy){profileNotice('Attendre la fin de l’opération sur la campagne avant de changer le profil du projet.','error');return;}
    const selected=$('engineProfileChoice').value,payload={engine:selected};
    if(selected==='custom'){
      const name=$('engineProfileCustomName').value.trim().replace(/\s+/g,' ');
      if(!/^[\p{L}\p{N} ._-]{1,64}$/u.test(name)||!/[\p{L}\p{N}]/u.test(name)){profileNotice('Nom du profil : 1 à 64 caractères, lettres/chiffres, espaces, point, tiret ou soulignement. Aucun HTML ni chemin.','error');return;}
      payload.name=name;
    }
    engineProfileSaving=true;$('engineProfileApply').disabled=true;$('engineProfileChoice').disabled=true;profileNotice('Enregistrement du profil local…');
    try{
      const response=await fetch('/api/engines/select',{method:'POST',headers:{'Content-Type':'application/json','X-LOTUSim-Engines':'1'},body:JSON.stringify(payload)});
      const result=await response.json();if(!response.ok)throw Error(result.error||result.message||'Le profil n’a pas pu être enregistré.');
      if(!result?.selectedEngine?.id||!Array.isArray(result.engines))throw Error('Réponse du registre moteur incompatible.');
      engineRegistry=result;$('engineProfileChoice').value=result.selectedEngine.id;renderEngineProfile();
      profileNotice('Profil de projet enregistré : '+result.selectedEngine.label+'. Le moteur et les paramètres du brouillon de campagne sont conservés. Aucun moteur lancé.','success');
      window.dispatchEvent(new CustomEvent('lotusim-engine-profile-updated',{detail:result.selectedEngine}));
      await refreshCatalog();
    }catch(error){profileNotice(error.message||'Registre local inaccessible.','error');}
    finally{engineProfileSaving=false;$('engineProfileChoice').disabled=false;updateProfileChoice();}
  }
  function safeLink(value) {
    if (typeof value !== 'string' || !value || value.includes('\\')) return null;
    try { const url = new URL(value, location.origin); return url.origin === location.origin
      && ['http:', 'https:'].includes(url.protocol) ? url.pathname + url.search + url.hash : null; }
    catch (_) { return null; }
  }
  function notice(text, kind = '') {
    const target=$('settingsNotice');target.className='notice settings-notice'+(kind?' '+kind:'');
    if(typeof window.LotusimAlerts?.notify==='function')return window.LotusimAlerts.notify(target,text,kind,{source:'Paramétrage',route:'settings',label:'Configuration de campagne'});
    target.textContent=text;target.hidden=!text;
  }
  function markDirty() {
    dirty = true; revision++; lastValidation = null;
    $('settingsDraftBadge').textContent = 'Modifications non enregistrées';
    $('settingsDraftBadge').className = 'badge warning';
    $('settingsValidation').replaceChildren(); $('settingsPrepared').hidden = true;
    updateSummary();renderTrafficBlocks();
  }
  function field(container, title, value, change, options = {}) {
    const label = element(options.range ? 'div' : 'label', null, 'settings-field' + (options.range ? ' settings-speed-field' : '') + (options.wide ? ' wide' : ''));
    const titleNode = element(options.range ? 'label' : 'span', title); label.append(titleNode);
    const control = element(options.choices ? 'select' : 'input');
    control.id = 'settings-field-' + (options.key || uid('value')).replace(/[^a-zA-Z0-9_-]/g, '-');
    if(options.range)titleNode.htmlFor=control.id;
    if (options.choices) {
      for (const item of options.choices) control.append(choice(String(item.value), item.label));
      if (value !== null && value !== undefined && !options.choices.some(item => String(item.value) === String(value))) {
        control.append(choice(String(value), String(value) + ' · non disponible'));
      }
    } else {
      control.type = options.text ? 'text' : 'number';
      if (!options.text) {
        control.step = options.integer ? '1' : 'any';
        if (isNumber(options.min)) control.min = String(options.min);
        if (isNumber(options.max)) control.max = String(options.max);
      }
      if (options.required !== false) control.required = true;
      if (options.maxLength) control.maxLength = options.maxLength;
    }
    control.value = value === null || value === undefined ? '' : String(value);
    if (options.readOnly) control.readOnly = true;
    if (options.disabled) control.disabled = true;
    if (options.path) control.dataset.configPath = options.path;
    let range=null;
    const applyInput=()=>{
      const next = options.choices || options.text ? control.value : control.value.trim() === '' ? null : Number(control.value);
      change(next, control); markDirty();
      if(range)range.value=String(isNumber(next)?Math.max(options.min||0,Math.min(options.max||0,next)):0);
    };
    control.addEventListener(options.choices ? 'change' : 'input', applyInput);
    if (options.onCommit) control.addEventListener('change', options.onCommit);
    label.append(control);
    if(options.range){
      range=element('input');range.type='range';range.id=control.id+'-range';range.min=String(options.min??0);range.max=String(options.max??0);range.step='any';
      range.value=String(isNumber(value)?Math.max(options.min||0,Math.min(options.max||0,value)):0);
      range.disabled=!isNumber(options.max)||options.max<=0;
      range.setAttribute('aria-label',(options.rangeLabel||title)+' — curseur');
      range.addEventListener('input',()=>{
        const next=round(Number(range.value),3);control.value=String(Math.max(options.min||0,Math.min(options.max||0,next)));applyInput();
      });
      label.append(range);
      const scale=element('div',null,'settings-slider-scale');scale.append(element('span','0'),element('span',fmt(options.max,1)+(options.rangeUnit?' '+options.rangeUnit:'')));label.append(scale);
    }
    if (options.help) label.append(element('small', options.help));
    container.append(label); return control;
  }
  function setBusy(next) {
    busy = next;
    const controls = $('settingsEditor').querySelectorAll('button,input,select');
    if (next) for (const control of controls) { savedDisabled.set(control, control.disabled); control.disabled = true; }
    else { for (const [control, previous] of savedDisabled) control.disabled = previous; savedDisabled.clear(); }
    $('settingsImport').disabled = next; $('settingsExport').disabled = next || !draft;
    if($('engineProfileApply'))$('engineProfileApply').disabled=next||engineProfileSaving||!engineRegistry;
    if (!next) updateActionState();
  }
  function updateActionState() {
    const engine = engineFor(draft?.engine);
    $('settingsPrepare').disabled = busy || !draft || !canPrepare(engine);
    $('settingsPrepare').textContent = canPrepare(engine) ? (contractOnly(engine)?'Exporter le contrat · ':'Préparer pour ')+engineLabel(draft?.engine) : 'Préparation non disponible';
    $('settingsLoad').disabled = busy || !$('settingsSaved').value;
    $('settingsGenerateTraffic').disabled=busy||!draft;
  }
  function renderTrafficBlocks(){
    const select=$('settingsTrafficBlock');if(!select||!draft)return;const previous=select.value;
    select.replaceChildren(choice('','Choisir explicitement un bloc…'),...array(draft.blocks).map(block=>choice(block.id,(block.name||block.id)+' · '+array(block.objects).reduce((sum,item)=>sum+(isNumber(item.count)?item.count:0),0)+' objets · '+block.images+' images demandées')));
    select.value=array(draft.blocks).some(block=>block.id===previous)?previous:draft.blocks.length===1?draft.blocks[0].id:'';
    renderTrafficCapture();
  }
  function renderTrafficCapture(){
    const block=array(draft?.blocks).find(value=>value.id===$('settingsTrafficBlock').value),mode=$('settingsTrafficCaptureMode');if(!['count','interval'].includes(mode.value))mode.value='count';
    if((block?.id||null)!==trafficCountBlock){trafficCountBlock=block?.id||null;trafficCountEdited=false;}
    if(block&&!trafficCountEdited)$('settingsTrafficCaptureCount').value=String(block.images);
    if(!$('settingsTrafficCaptureInterval').value)$('settingsTrafficCaptureInterval').value='2';
    $('settingsTrafficCaptureCountField').hidden=mode.value!=='count';$('settingsTrafficCaptureIntervalField').hidden=mode.value!=='interval';
    $('settingsTrafficCaptureCount').disabled=busy||mode.value!=='count';$('settingsTrafficCaptureInterval').disabled=busy||mode.value!=='interval';
    const target=$('settingsTrafficCapturePreview');target.className='traffic-help traffic-capture-preview';if(!block){target.textContent='Choisir un bloc pour calculer le calendrier de photos de cet épisode continu.';return;}
    try{const schedule=captureCadence(Number($('settingsTrafficDuration').value),settingsTrafficCapture());target.textContent=fmt(schedule.count,0)+' photos prévues · de 0 à '+fmt(schedule.effectiveTimesSeconds.at(-1),6)+' s simulées (fin de l’épisode exclue). Grille moteur : 30 images/s.'+(schedule.maxQuantizationErrorSeconds>1e-9?' Écart maximal de quantification : '+fmt(schedule.maxQuantizationErrorSeconds,6)+' s.':' Aucun décalage de quantification.')+(schedule.discardedAtOrAfterEndCount?' '+schedule.discardedAtOrAfterEndCount+' prise hors grille finale exclue.':'');}catch(error){target.textContent=error.message;target.className+=' error';}
  }
  function settingsTrafficCapture(){return $('settingsTrafficCaptureMode').value==='interval'?{mode:'interval',intervalSeconds:Number($('settingsTrafficCaptureInterval').value)}:{mode:'count',count:Number($('settingsTrafficCaptureCount').value)};}
  function hydrate(source) {
    if (!source || typeof source !== 'object' || Array.isArray(source) || source.schema !== SCHEMA) {
      throw Error('Format de campagne incompatible : schéma ' + SCHEMA + ' attendu.');
    }
    if(source.sensors && (source.sensors.rgb === false || source.sensors.thermal === true || source.sensors.nightVision === true)) {
      throw Error('Cet éditeur prépare uniquement du RGB : utiliser rgb:true, thermal:false et nightVision:false.');
    }
    if(array(source.blocks).length>50 || array(source.blocks).some(block=>array(block?.objects).length>40)) {
      throw Error('La configuration dépasse les limites de l’éditeur : 50 blocs, 40 lignes d’objets par bloc.');
    }
    // Imports are treated as data. The server remains the authoritative validator.
    const fallback = catalog?.defaults || {};
    const result = {...clone(fallback), ...clone(source)};
    result.camera = {...clone(fallback.camera || {}), ...source.camera};
    result.observer = {...clone(fallback.observer || {}), ...source.observer};
    result.sensors = {...clone(fallback.sensors || {}), ...source.sensors};
    result.blocks = array(source.blocks).map(block => ({...block, environment:{...block.environment}, objects:array(block.objects).map(object => ({...object}))}));
    return result;
  }
  async function getJSON(url) {
    const response = await fetch(url, {cache:'no-store'});
    if (!response.ok) throw Error('Le serveur local répond HTTP ' + response.status + '.');
    return response.json();
  }
  async function open() {
    if (loaded) {await refreshCatalog();return;}
    if (loading) return;
    loading = true; $('settingsLoading').hidden = false; $('settingsRetry').hidden = true;
    try {
      const result = await getJSON('/api/settings/catalog');
      if (!result || !Array.isArray(result.assets) || !result.defaults) throw Error('Catalogue local incomplet.');
      catalog = result; draft = hydrate(result.defaults); loaded = true; dirty = false;
      renderAll(); renderSaved(result.campaigns); notice('');
      $('settingsLoading').hidden = true; $('settingsEditor').hidden = false; $('settingsExport').disabled = false;
    } catch (error) {
      $('settingsLoading').querySelector('strong').textContent = 'Catalogue indisponible';
      $('settingsLoading').querySelector('p').textContent = 'Le brouillon ne peut pas être construit sans les scènes et les limites du catalogue local.';
      $('settingsRetry').hidden = false; notice(error.message, 'error');
    } finally { loading = false; }
  }
  function catalogSignature(value) {
    return JSON.stringify({assets:array(value?.assets),engines:array(value?.engines),scenes:array(value?.scenes)});
  }
  function catalogUpdate(message,warning=false){
    let panel=$('settingsCatalogUpdate');
    if(!panel){panel=element('p',null,'settings-catalog-update');panel.id='settingsCatalogUpdate';panel.setAttribute('role','status');$('settingsEngineNote').insertAdjacentElement('afterend',panel);}
    panel.textContent=message;panel.classList.toggle('warning',warning);panel.hidden=!message;
  }
  function updateModelChoices(){
    // Update options in place. Re-rendering the editor here would destroy a
    // partially typed number, its focus/caret, and the user's unsaved draft.
    for(const select of $('settingsBlocks').querySelectorAll('select[data-config-path$=".model"]')){
      if(document.activeElement===select)continue;
      const previous=select.value;
      select.replaceChildren(...array(catalog.assets).map(asset=>choice(asset.model,asset.label||asset.model)));
      if(!array(catalog.assets).some(asset=>asset.model===previous))select.append(choice(previous,modelLabel(previous)+' · non disponible'));
      select.value=previous;
    }
  }
  async function refreshCatalog(){
    if(!loaded||loading||busy||refreshingCatalog)return;
    refreshingCatalog=true;
    try{
      const next=await getJSON('/api/settings/catalog');
      if(!next||!Array.isArray(next.assets)||!next.defaults)throw Error('Catalogue local incomplet.');
      const changed=catalogSignature(next)!==catalogSignature(catalog);
      catalog=next;
      if(changed){
        updateModelChoices();updateActionState();updateSummary();renderEngineNote();
        const engineSelect=$('settings-field-engine');
        if(engineSelect&&document.activeElement!==engineSelect){
          const previous=engineSelect.value;engineSelect.replaceChildren(...array(catalog.engines).map(engine=>choice(engine.id,engineChoiceLabel(engine))));engineSelect.value=previous;
        }
        catalogUpdate('Catalogue actualisé : '+fmt(next.assets.length,0)+' modèles prêts. Le brouillon et ses modifications sont conservés.');
      }else if($('settingsCatalogUpdate')?.classList.contains('warning'))catalogUpdate('Catalogue local à jour. Le brouillon est conservé.');
    }catch(_){catalogUpdate('Catalogue non actualisé : les dernières informations restent affichées. Vérifier la liaison avant de préparer la campagne.',true);}
    finally{refreshingCatalog=false;}
  }
  function renderSaved(values) {
    const select = $('settingsSaved'), previous = select.value;
    select.replaceChildren(choice('', 'Choisir une configuration…'));
    for (const item of array(values)) if (item && typeof item.id === 'string') select.append(choice(item.id, item.name || item.id));
    if (currentId && array(values).some(item => item.id === currentId)) select.value = currentId;
    else if (array(values).some(item => item.id === previous)) select.value = previous;
    updateActionState();
  }
  async function refreshSaved() {
    try { const value = await getJSON('/api/settings/campaigns'); renderSaved(Array.isArray(value) ? value : value.campaigns); }
    catch (_) { /* A successful save remains successful if refreshing the list fails. */ }
  }
  function renderIdentity() {
    const target = $('settingsIdentityFields'); target.replaceChildren();
    field(target, 'Nom de la campagne', draft.name, value => draft.name = value, {text:true, maxLength:120, key:'name', path:'name'});
    field(target, 'Moteur pour cette campagne', draft.engine, value => {
      draft.engine = value;
      const allowed = scenesFor(value);
      if (!allowed.some(scene => scene.id === draft.scene)) draft.scene = allowed[0]?.id || '';
      renderIdentity(); updateActionState();
    }, {key:'engine', choices:array(catalog.engines).map(engine => ({value:engine.id,label:engineChoiceLabel(engine)}))});
    field(target, 'Profil de scène · '+engineLabel(draft.engine), draft.scene, value => draft.scene = value, {key:'scene', path:'scene',
      choices:scenesFor(draft.engine).map(scene => ({value:scene.id,label:scene.label || scene.id}))});
    field(target, 'Nombre total d’images', draft.totalImages, value => draft.totalImages = value, {min:1, max:2000, integer:true, key:'total', path:'totalImages',help:'Pilote limité à 2 000 images par campagne.'});
    field(target, 'Graine aléatoire', draft.seed, value => draft.seed = value, {min:0, max:2147483647, integer:true, key:'seed', path:'seed',help:'Même graine + même configuration : positions reproductibles.'});
    renderEngineNote();
  }
  function renderCamera() {
    const target = $('settingsCameraFields'); target.replaceChildren();
    const camera = draft.camera;
    const commit = () => { syncPixelDistances(); renderBlocks(); updateSummary(); };
    for (const [key,title,min,max,step,help] of [
      ['width','Largeur (px)',64,4096,1,null], ['height','Hauteur (px)',64,4096,1,null],
      ['verticalFovDeg','FOV vertical (°)',30,90,.1,'Plus étroit = objets plus grands à distance égale.'],
      ['farClipM','Portée de rendu (m)',5000,100000,100,null],
      ['viewHeadingDeg','Vue / axe du bateau (°)',0,360,.1,'0° vers l’avant, 90° vers tribord.'],
      ['viewDownPitchDeg','Inclinaison vers le bas (°)',-10,15,.1,null],
    ]) field(target, title, camera[key], value => camera[key] = value, {min,max,step,help,integer:['width','height'].includes(key),key:'camera-'+key,path:'camera.'+key,onCommit:commit});
    const observer = draft.observer, body = $('settingsObserverFields'); body.replaceChildren();
    field(body,'Vitesse observateur (nœuds)', displaySpeed(observer.speedMps,13.89,KNOT),
      value => observer.speedMps = isNumber(value) ? value*KNOT : null, {min:0,max:13.89/KNOT,step:'any',range:true,rangeUnit:'nœuds',rangeLabel:'Vitesse du bateau observateur en nœuds',key:'observer-speed',path:'observer.speedMps'});
    field(body,'Cap observateur (°)',observer.headingDeg,value => observer.headingDeg=value,{min:0,max:360,step:.1,key:'observer-heading',path:'observer.headingDeg'});
    field(body,'Roulis maximal (°)',observer.rollMaxDeg,value => observer.rollMaxDeg=value,{min:0,max:12,step:.1,key:'observer-roll',path:'observer.rollMaxDeg'});
    field(body,'Tangage maximal (°)',observer.pitchMaxDeg,value => observer.pitchMaxDeg=value,{min:0,max:8,step:.1,key:'observer-pitch',path:'observer.pitchMaxDeg'});
    const sensors = $('settingsSensors'); sensors.replaceChildren();
    for (const [key,title] of [['rgb','RGB · mode de cette campagne'],['thermal','Thermique · indisponible dans cet éditeur'],['nightVision','Vision nocturne · indisponible dans cet éditeur']]) {
      const label = element('label',null,'settings-sensor-label'), input = element('input'); input.type='checkbox'; input.checked=draft.sensors[key]===true;
      input.disabled = true;
      input.title = key === 'rgb' ? 'Le RGB est requis pour ce pilote de campagne manuelle.' : 'Utilisez un autre pipeline pour cette modalité.';
      label.append(input,element('span',title)); sensors.append(label);
    }
  }
  function syncPixelDistances() {
    for (const block of array(draft.blocks)) for (const object of array(block.objects)) {
      if (object.distanceMode !== 'pixel_height') continue;
      const distance = distanceForPixels(draft.camera, assetFor(object.model), object.targetHeightPx);
      if (isNumber(distance)) object.distanceM=round(distance,6);
    }
  }
  function renderBlocks() {
    const target = $('settingsBlocks'); target.replaceChildren();
    if (!draft.blocks.length) target.append(element('div','Aucun bloc. Ajoutez un premier groupe d’images pour définir ses conditions et ses objets.','settings-empty-objects'));
    draft.blocks.forEach((block,index)=>{
      const card = element('article',null,'settings-block'); card.id='settings-block-'+index;
      const header=element('div',null,'settings-block-head'); header.append(element('span',String(index+1).padStart(2,'0'),'settings-block-number'));
      field(header,'Nom du bloc',block.name,value=>{block.name=value;},{text:true,maxLength:100,key:'block-'+index+'-name',path:`blocks.${index}.name`});
      field(header,'Images',block.images,value=>block.images=value,{min:1,max:2000,integer:true,key:'block-'+index+'-images',path:`blocks.${index}.images`});
      const commands=element('div',null,'settings-block-commands');
      commands.append(button('Dupliquer',()=>{const copy=clone(block);copy.id=uid('block');copy.name=(block.name||'Bloc')+' · copie';copy.objects.forEach(object=>object.id=uid('object'));draft.blocks.splice(index+1,0,copy);markDirty();renderBlocks();}),
        button('Supprimer le bloc',()=>{draft.blocks.splice(index,1);markDirty();renderBlocks();},'danger-button'));
      header.append(commands);card.append(header);
      const body=element('div',null,'settings-block-body');body.append(element('h3','Conditions de la scène'));
      const env=element('div',null,'settings-grid settings-environment'), environment=block.environment;
      field(env,'Moment de la journée',environment.timeOfDay,value=>environment.timeOfDay=value,{key:'block-'+index+'-time',choices:[{value:'day',label:'Jour'},{value:'dusk',label:'Crépuscule'},{value:'night',label:'Nuit'}]});
      for(const [key,title,min,max,step,scale] of [
        ['cloudCover','Couverture nuageuse (%)',0,100,1,100],['rainIntensity','Pluie (%)',0,100,1,100],
        ['waveHeightM','Houle cible (m, proxy)',0,8,.1,1],['waveDirectionDeg','Direction de houle (°)',0,360,1,1],
        ['windMps','Vent (m/s)',0,30,.1,1],
      ]) field(env,title,isNumber(environment[key])?round(environment[key]*scale,3):null,value=>environment[key]=isNumber(value)?value/scale:null,
        {min,max,step,key:'block-'+index+'-'+key,path:`blocks.${index}.environment.${key}`});
      body.append(env);
      const objectsHeading=element('div',null,'settings-objects-heading');objectsHeading.append(element('h3','Objets dans les images'),button('+ Ajouter un objet',()=>{
        const asset=array(catalog.assets)[0]; if(!asset)return;block.objects.push(defaultObject(asset,uid('object')));markDirty();renderBlocks();
      }));body.append(objectsHeading);
      if(!block.objects.length)body.append(element('div','Image de fond seule : aucun objet cible dans ce bloc.','settings-empty-objects'));
      block.objects.forEach((object,rowIndex)=>body.append(renderObject(block,object,index,rowIndex)));
      card.append(body);target.append(card);
    });
  }
  function renderObject(block,object,blockIndex,rowIndex) {
    const prefix=`blocks.${blockIndex}.objects.${rowIndex}`, key=`block-${blockIndex}-object-${rowIndex}`;
    const asset=assetFor(object.model), speed=speedPresentation(asset);
    const card=element('div',null,'settings-object'), head=element('div',null,'settings-object-head');
    field(head,'Modèle 3D',object.model,value=>{
      object.model=value;const next=assetFor(value), replacement=defaultObject(next,object.id);
      object.altitudeM=replacement.altitudeM;object.speedMps=replacement.speedMps;
      if(object.distanceMode==='pixel_height') {const distance=distanceForPixels(draft.camera,next,object.targetHeightPx);if(isNumber(distance))object.distanceM=round(distance,6);}
      renderBlocks();
    },{key:key+'-model',path:prefix+'.model',choices:array(catalog.assets).map(item=>({value:item.model,label:item.label||item.model}))});
    field(head,'Quantité',object.count,value=>object.count=value,{min:1,max:12,integer:true,key:key+'-count',path:prefix+'.count'});
    head.append(button('Retirer',()=>{block.objects.splice(rowIndex,1);markDirty();renderBlocks();},'danger-button'));card.append(head);
    const fields=element('div',null,'settings-grid settings-object-fields');
    field(fields,'Placement par',object.distanceMode||'metres',value=>{
      object.distanceMode=value;
      if(value==='pixel_height'&&!isNumber(object.targetHeightPx))object.targetHeightPx=round(projectedHeight(draft.camera,asset,object.distanceM)||32,2);
      syncPixelDistances();renderBlocks();
    },{key:key+'-mode',choices:[{value:'metres',label:'Distance horizontale'},{value:'pixel_height',label:'Hauteur cible en pixels'}]});
    if(object.distanceMode==='pixel_height') field(fields,'Hauteur cible (px)',object.targetHeightPx,value=>{
      object.targetHeightPx=value;const distance=distanceForPixels(draft.camera,asset,value);if(isNumber(distance))object.distanceM=round(distance,6);updateEstimate();
    },{min:.1,max:draft.camera.height,step:.1,key:key+'-pixels',path:prefix+'.targetHeightPx',help:'Calcule la distance, sans redimensionner le modèle.'});
    else field(fields,'Distance horizontale (m)',object.distanceM,value=>{object.distanceM=value;updateEstimate();},{min:5,max:60000,step:1,key:key+'-distance',path:prefix+'.distanceM'});
    field(fields,'Relèvement / observateur (°)',object.bearingDeg,value=>object.bearingDeg=value,{min:-180,max:180,step:.1,key:key+'-bearing',path:prefix+'.bearingDeg',help:'0° devant, +90° à tribord, −90° à bâbord.'});
    field(fields,'Dispersion angulaire (°)',object.spreadDeg,value=>object.spreadDeg=value,{min:0,max:180,step:.1,key:key+'-spread',path:prefix+'.spreadDeg'});
    const airborne=asset?.domain==='air', maxAltitude=airborne&&isNumber(asset.maxAltitudeM)?asset.maxAltitudeM:0;
    field(fields,'Altitude (m)',object.altitudeM,value=>object.altitudeM=value,{min:0,max:maxAltitude,step:1,key:key+'-altitude',path:prefix+'.altitudeM',help:airborne?'Maximum catalogue : '+fmt(maxAltitude,0)+' m.':'Objet marin : altitude de référence 0 m.'});
    const maximum=isNumber(asset?.maxSpeedMps)?asset.maxSpeedMps:0;
    field(fields,'Vitesse ('+speed.unit+')',displaySpeed(object.speedMps,maximum,speed.factor),
      value=>object.speedMps=isNumber(value)?value*speed.factor:null,{min:0,max:maximum/speed.factor,step:'any',range:true,rangeUnit:speed.unit,
        rangeLabel:'Vitesse de '+modelLabel(object.model)+', bloc '+(blockIndex+1)+', objet '+(rowIndex+1)+' en '+speed.unit,key:key+'-speed',path:prefix+'.speedMps',
        help:'Limite catalogue : '+fmt(maximum/speed.factor,1)+' '+speed.unit+' (hypothèse, non certifiée).'});
    field(fields,'Cap de déplacement (°)',object.headingDeg,value=>object.headingDeg=value,{min:0,max:360,step:.1,key:key+'-heading',path:prefix+'.headingDeg',help:'Cap absolu : 0° nord, 90° est.'});
    card.append(fields);
    const estimate=element('div',null,'settings-size-estimate'), label=element('div',null,'estimate-label');
    label.append(element('span','Hauteur apparente théorique'),element('small','Objet entier, orienté de face · hors occultation, houle et contraste'));
    const value=element('strong');estimate.append(label,value);card.append(estimate);
    function updateEstimate() {
      const pixels=projectedHeight(draft.camera,assetFor(object.model),object.distanceM);
      value.textContent=isNumber(pixels)?'≈ '+fmt(pixels,1)+' px':'Dimensions non disponibles';
      let note='Projection pinhole : hauteur image × hauteur modèle / (2 × tan(FOV vertical / 2) × distance).';
      if(object.distanceMode==='pixel_height')note+=' Distance calculée : '+fmt(object.distanceM,1)+' m.';
      estimate.title=note;
      if(object.distanceMode==='pixel_height') label.querySelector('small').textContent='Distance calculée : '+fmt(object.distanceM,1)+' m · aucune mise à l’échelle';
    }
    updateEstimate();return card;
  }
  function updateSummary() {
    if(!draft)return;
    const summary=totals(draft), expected=draft.totalImages, validTotal=isNumber(expected)&&expected>0;
    $('settingsAllocated').textContent=fmt(summary.allocatedImages,0);
    $('settingsTotalExpected').textContent='/ '+fmt(expected,0)+' images';
    const delta=validTotal?expected-summary.allocatedImages:null;
    $('settingsAllocationDetail').textContent=delta===0?'Répartition exacte. '+summary.blocks+' bloc'+(summary.blocks>1?'s':'')+' d’images indépendantes.':
      delta===null?'Définir le nombre total d’images.':delta>0?fmt(delta,0)+' image'+(delta>1?'s':'')+' reste'+(delta>1?'nt':'')+' à répartir.':fmt(-delta,0)+' image'+(-delta>1?'s':'')+' en trop : ajuster les blocs ou le total.';
    $('settingsAllocationFill').style.width=validTotal?Math.min(100,Math.max(0,summary.allocatedImages/expected*100))+'%':'0%';
    $('settingsAllocationFill').parentElement.classList.toggle('over',isNumber(delta)&&delta<0);
    $('settingsTotalBadge').textContent=delta===0?'Total réparti':'Total à ajuster';
    $('settingsTotalBadge').className='badge '+(delta===0?'complete':'warning');
    const legend=$('settingsBlockLegend');legend.replaceChildren();
    draft.blocks.forEach((block,index)=>{const row=element('div',null,'settings-legend-row'), label=element('span',(block.name||'Bloc '+(index+1)));label.style.color=palette[index%palette.length];row.append(label,element('strong',fmt(block.images,0)+' images'));legend.append(row);});
    const counts=$('settingsObjectTotals');counts.replaceChildren();
    for(const [model,count] of Object.entries(summary.objectImageCounts))counts.append(element('dt',modelLabel(model)),element('dd',fmt(count,0)+' présences prévues'));
    if(!Object.keys(summary.objectImageCounts).length)counts.append(element('dt','Aucun objet cible'),element('dd','Fonds seuls'));
  }
  function renderAll() {
    renderIdentity();renderCamera();renderBlocks();updateSummary();updateActionState();renderTrafficBlocks();
    $('settingsDraftBadge').textContent=dirty?'Modifications non enregistrées':'Brouillon chargé';
    $('settingsDraftBadge').className='badge '+(dirty?'warning':'neutral');
    $('settingsSavedId').textContent=currentId?'ID local : '+currentId:'';
    if(busy)for(const control of $('settingsEditor').querySelectorAll('button,input,select')){
      if(!savedDisabled.has(control))savedDisabled.set(control,control.disabled);
      control.disabled=true;
    }
  }
  function renderValidation(result) {
    const target=$('settingsValidation');target.replaceChildren(element('h3',result.valid?'Configuration valide':'Configuration à corriger'));
    const rows=element('ul');
    if(result.valid)rows.append(element('li','Les paramètres ont été acceptés par le validateur local. La visibilité effective dépendra du rendu.','success'));
    for(const issue of array(result.errors)){
      const row=element('li',null,'error');
      if(issue.path)row.append(element('strong',issue.path));
      row.append(document.createTextNode(issue.message||'Paramètre non validé.'));rows.append(row);
    }
    target.append(rows);
    const warnings=array(result.warnings);
    if(warnings.length){
      const details=contextDetails('validation-warnings','Points de vigilance',warnings.length),items=element('ul');
      for(const issue of warnings){const row=element('li',null,'warning');if(issue.path)row.append(element('strong',issue.path));row.append(document.createTextNode(issue.message||'Paramètre à vérifier.'));items.append(row);}
      details.append(items);target.append(details);
    }
  }
  function renderPrepared(result) {
    const actions=result.engineActions||{}, engine=actions.engine||draft.engine, title=engineLabel(engine);
    const target=$('settingsPrepared');target.replaceChildren(element('h3','Campagne préparée · '+title));
    const status=element('div',null,'settings-prepared-status');
    status.append(element('span','Fichiers préparés','complete'),element('span',actions.runtimeDetected===true?'Moteur détecté':actions.runtimeDetected===false?'Moteur non détecté':'Moteur non vérifié','neutral'),
      element('span',actions.nativeValidated===true?'Chaîne native validée':'Exécution native non validée',actions.nativeValidated===true?'complete':'warning'));
    target.append(status,element('p',contractOnly(engineFor(engine))?'Contrat de scène uniquement : aucun script natif, SDK, rendu, annotation ou connexion temps réel n’est mis en service. Télécharger le ZIP conserve le contrat et les exigences d’adaptation ensemble.':'Fichiers préparés, aucune image ni exécution native validée par cette opération. Téléchargez le ZIP, ou conservez la campagne et le manifeste dans le même dossier. Aucun lancement automatique.'));
    for(const [value,title] of [[result.bundleUrl,'Télécharger le bundle ZIP'],[result.downloadUrl,'Télécharger campaign.json'],[result.manifestUrl,'Télécharger manifest.json']]) {
      const href=safeLink(value);if(!href)continue;const link=element('a',title);link.href=href;link.download='';target.append(link);
    }
    const localPath=typeof result.importFile==='string'?result.importFile:typeof result.manifestFile==='string'?result.manifestFile:
      result.id?'artifacts/campaign-settings/prepared/'+result.id+'/manifest.json':null;
    if(localPath)target.append(element('code',localPath));
    const instructions=array(actions.instructions).filter(item=>typeof item==='string').slice(0,20);
    if(instructions.length){const steps=element('ol',null,'settings-engine-instructions');for(const text of instructions)steps.append(element('li',text));target.append(steps);}
    else target.append(element('p',engine==='unity'?'Dans Unity : LOTUSim > Dataset > Manual campaigns > Import prepared campaign. Sélectionner manifest.json, avec campaign.json dans le même dossier. Lancez ensuite la campagne depuis Unity.':'Décompresser le bundle, conserver tous ses fichiers et suivre les instructions du moteur choisi. Un contrat neutre nécessite un adaptateur avant toute exécution native.'));
    if(typeof actions.scenePath==='string'&&actions.scenePath)target.append(element('p','Scène cible : '+actions.scenePath));
    if(typeof result.id==='string'&&/^[a-zA-Z0-9_-]{1,120}$/.test(result.id)){
      const files=element('ul',null,'settings-engine-files');
      for(const file of array(actions.files).slice(0,40)){
        if(typeof file?.name!=='string'||!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}$/.test(file.name))continue;
        const row=element('li'),link=element('a',file.label||file.name);link.href='/api/settings/prepared/'+encodeURIComponent(result.id)+'/'+encodeURIComponent(file.name);link.download='';row.append(link);
        if(typeof file.sha256==='string'&&/^[a-f0-9]{64}$/i.test(file.sha256)){const hash=element('code','SHA-256 '+file.sha256.slice(0,12)+'…');hash.title=file.sha256;row.append(hash);}files.append(row);
      }
      if(files.children.length){target.append(element('h4','Fichiers et traçabilité'),files);}
    }
    renderEngineAgent(result.engineAgent,target);
    target.hidden=false;
  }
  function renderEngineAgent(agent,target){
    if(!agent||typeof agent!=='object')return;
    const panel=element('section',null,'settings-engine-agent');panel.append(element('h4','Agent de préparation · trace locale'));
    for(const [key,label] of [['role','Rôle'],['status','État'],['message','Détail']])if(typeof agent[key]==='string')panel.append(element('p',label+' : '+agent[key]));
    const trace=array(agent.traces||agent.steps||agent.roles||agent.trace).slice(0,20);
    if(trace.length){const rows=element('ol');for(const item of trace){
      const role=item&&typeof item==='object'?item.role||item.name:null;
      const roles={planner:'Planification (planner)',scene_script_builder:'Construction du script (scene_script_builder)',validator:'Vérification (validator)'};
      const state=item&&typeof item==='object'?item.state||item.status:null;
      const text=typeof item==='string'?item:item&&typeof item==='object'?[roles[role]||role,state==='completed'?'Terminé':state,item.message||item.detail,...array(item.decisions).filter(value=>typeof value==='string').slice(0,6)].filter(value=>typeof value==='string').join(' · '):'';
      if(text)rows.append(element('li',text));
    }panel.append(rows);}
    const limitations=array(agent.limitations).filter(value=>typeof value==='string').slice(0,20);
    if(limitations.length){const details=contextDetails('prepared-agent-limitations-'+(draft?.engine||'unknown'),'Limites de cet adaptateur',limitations.length),rows=element('ul',null,'settings-engine-limits');for(const text of limitations)rows.append(element('li',text.slice(0,4000)));details.append(rows);panel.append(details);}
    panel.append(element('small','Trace d’orchestration déterministe, pas une preuve d’exécution du moteur.'));target.append(panel);
  }
  function validFields() {
    const controls=$('settingsEditor').querySelectorAll('input,select');
    for(const control of controls)if(control.dataset.trafficControl!=='true'&&!control.disabled&&typeof control.checkValidity==='function'&&!control.checkValidity()){
      control.reportValidity();notice('Corrigez le champ signalé avant de poursuivre.','error');return false;
    }
    return true;
  }
  async function generateTrafficScenario(){
    if(busy||!draft||!validFields())return;
    const blockId=$('settingsTrafficBlock').value,durationSeconds=Number($('settingsTrafficDuration').value),actionProfile=$('settingsTrafficProfile').value,speedPolicy=$('settingsTrafficSpeedPolicy').value;
    if(!array(draft.blocks).some(block=>block.id===blockId)){notice('Choisir le bloc à transformer en scénario continu. Les blocs d’images ne sont pas fusionnés.','error');$('settingsTrafficBlock').focus();return;}
    if(!Number.isFinite(durationSeconds)||durationSeconds<4||durationSeconds>600||!['open_water','crossing','parallel'].includes(actionProfile)||!['catalogue','requested'].includes(speedPolicy)){notice('Vérifier la durée de 4 à 600 secondes et les politiques du scénario coopératif.','error');return;}
    if(typeof draft.name!=='string'||!draft.name.trim()||draft.name.trim().length>80){notice('Le nom utilisé pour ce scénario doit contenir de 1 à 80 caractères. Ajuster le nom de la campagne avant de générer.','error');return;}
    let capture;try{renderTrafficCapture();capture=captureCadence(durationSeconds,settingsTrafficCapture()).capture;}catch(error){notice(error.message,'error');return;}
    syncPixelDistances();const payload=clone(draft);setBusy(true);notice('Validation de la configuration courante avant planification coopérative…');
    try{
      const checked=await fetch('/api/settings/validate',{method:'POST',headers:{'Content-Type':'application/json','X-LOTUSim-Settings':'1'},body:JSON.stringify(payload)}),validation=await checked.json();
      if(typeof validation?.valid!=='boolean')throw Error('Réponse du validateur incompatible.');renderValidation(validation);
      if(!checked.ok||!validation.valid){notice('La configuration doit être valide avant de générer le scénario coopératif. Le brouillon reste intact.','error');return;}
      const campaign=validation.campaign||payload;
      notice('Génération des trajectoires du bloc sélectionné et contrôles coopératifs limités…');
      const response=await fetch('/api/traffic/generate',{method:'POST',headers:{'Content-Type':'application/json','X-LOTUSim-Traffic':'1'},body:JSON.stringify({name:campaign.name.trim(),seed:campaign.seed,durationSeconds,actionProfile,speedPolicy,headingPolicy:'profile',blockId,campaign,capture})}),result=await response.json();
      if(!response.ok)throw Error(result.message||result.error||array(result.errors).slice(0,5).map(issue=>[issue.path,issue.message].filter(value=>typeof value==='string').join(' : ')).join(' ; ')||'Le planificateur a refusé ces contraintes.');
      const planId=result.planId||result.id;if(typeof planId!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(planId)||result.applied!==false)throw Error('Réponse de scénario incompatible. Aucun lancement autorisé.');
      notice('Scénario coopératif enregistré en bibliothèque. La campagne d’images indépendante et son brouillon n’ont pas été remplacés.','success');
      window.dispatchEvent(new CustomEvent('lotusim-traffic-plan-selected',{detail:{planId}}));location.hash='#traffic';
    }catch(error){notice(error.message||'Génération coopérative indisponible. Le brouillon est conservé.','error');}
    finally{setBusy(false);}
  }
  async function action(kind) {
    if(busy||!draft||!validFields())return;
    if(kind==='prepare'&&!canPrepare(engineFor(draft.engine))){
      notice('Ce moteur ne dispose pas d’un adaptateur de préparation actif. Vous pouvez enregistrer ou exporter le JSON.','error');return;
    }
    syncPixelDistances();const payload=clone(draft), version=revision;setBusy(true);notice('Vérification locale en cours…');
    try {
      const response=await fetch('/api/settings/'+kind,{method:'POST',headers:{'Content-Type':'application/json','X-LOTUSim-Settings':'1'},body:JSON.stringify(payload)});
      const result=await response.json();
      if(!result||typeof result.valid!=='boolean')throw Error('Réponse du validateur local incompatible.');
      renderValidation(result);lastValidation=result;
      if(!result.valid){notice('La campagne n’a pas été '+(kind==='prepare'?'préparée':kind==='save'?'enregistrée':'validée')+'. Consultez les paramètres à corriger.','error');return;}
      if(!response.ok)throw Error('Le serveur local n’a pas pu terminer cette opération (HTTP '+response.status+').');
      if(revision===version&&result.campaign){draft=hydrate(result.campaign);renderAll();renderValidation(result);}
      if(kind==='validate')notice('Configuration vérifiée. Vous pouvez l’enregistrer ou la préparer pour '+engineLabel(draft.engine)+'.','success');
      if(kind==='save'){
        currentId=result.id||currentId;dirty=false;renderAll();renderValidation(result);
        $('settingsDraftBadge').textContent='Enregistré localement';$('settingsDraftBadge').className='badge complete';
        notice('Configuration enregistrée sur ce Mac. Aucune simulation modifiée.','success');
        await refreshSaved();
      }
      if(kind==='prepare'){
        $('settingsDraftBadge').textContent='Préparé pour '+engineLabel(draft.engine);$('settingsDraftBadge').className='badge complete';
        notice('Fichiers préparés pour '+engineLabel(draft.engine)+'. Aucun moteur ni scénario lancé ; suivre les instructions du bundle.','success');renderPrepared(result);
      }
    } catch(error){notice(error.message||'Impossible de joindre le serveur local.','error');}
    finally{setBusy(false);}
  }
  async function loadSelected() {
    const id=$('settingsSaved').value;if(!id||busy)return;
    if(dirty&&!window.confirm('Remplacer le brouillon et ses modifications non enregistrées ?'))return;
    setBusy(true);
    try{
      const response=await getJSON('/api/settings/campaigns/'+encodeURIComponent(id));
      draft=hydrate(response.campaign||response);currentId=id;dirty=false;revision++;
      $('settingsValidation').replaceChildren();$('settingsPrepared').hidden=true;renderAll();notice('Configuration locale chargée.','success');
    }catch(error){notice(error.message,'error');}finally{setBusy(false);}
  }
  function exportJSON() {
    if(!draft||busy)return;syncPixelDistances();
    const blob=new Blob([JSON.stringify(draft,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),link=element('a');
    link.href=url;link.download=(String(draft.name||'campaign').replace(/[^a-zA-Z0-9_-]/g,'_').slice(0,80)||'campaign')+'.json';
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    notice('Brouillon JSON exporté. Une exportation ne remplace pas la validation locale.');
  }
  async function importJSON(event) {
    const file=event.target.files?.[0];if(!file)return;
    try{
      if(!loaded)await open();if(!loaded)throw Error('Le catalogue local est nécessaire avant l’import.');
      if(file.size>1024*1024)throw Error('Le fichier JSON dépasse la limite de 1 Mo.');
      const next=hydrate(JSON.parse(await file.text()));
      if(dirty&&!window.confirm('Remplacer le brouillon et ses modifications non enregistrées ?'))return;
      draft=next;currentId=null;dirty=true;revision++;$('settingsPrepared').hidden=true;$('settingsValidation').replaceChildren();renderAll();
      notice('JSON importé comme brouillon. Vérifiez les modèles et les paramètres avant de le préparer.');
    }catch(error){notice(error instanceof SyntaxError?'Le fichier sélectionné n’est pas un JSON valide.':error.message,'error');}
    finally{event.target.value='';}
  }

  $('settingsRetry').addEventListener('click',open);
  $('settingsImport').addEventListener('click',()=>$('settingsImportFile').click());
  $('settingsImportFile').addEventListener('change',importJSON);
  $('settingsExport').addEventListener('click',exportJSON);
  $('settingsSaved').addEventListener('change',updateActionState);
  $('settingsLoad').addEventListener('click',loadSelected);
  $('settingsValidate').addEventListener('click',()=>action('validate'));
  $('settingsSave').addEventListener('click',()=>action('save'));
  $('settingsPrepare').addEventListener('click',()=>action('prepare'));
  $('settingsGenerateTraffic').addEventListener('click',generateTrafficScenario);
  for(const id of ['settingsTrafficBlock','settingsTrafficCaptureMode'])$(id).addEventListener('change',renderTrafficCapture);
  for(const id of ['settingsTrafficDuration','settingsTrafficCaptureInterval'])$(id).addEventListener('input',renderTrafficCapture);
  $('settingsTrafficCaptureCount').addEventListener('input',()=>{trafficCountEdited=true;renderTrafficCapture();});
  $('settingsAddBlock').addEventListener('click',()=>{
    const remaining=isNumber(draft.totalImages)?draft.totalImages-totals(draft).allocatedImages:0;
    draft.blocks.push({id:uid('block'),name:'Bloc '+(draft.blocks.length+1),images:remaining>0?remaining:10,
      environment:{timeOfDay:'day',cloudCover:.2,rainIntensity:0,waveHeightM:1.8,waveDirectionDeg:45,windMps:6},objects:[]});
    markDirty();renderBlocks();$('settingsBlocks').lastElementChild?.querySelector('input')?.focus();
  });
  $('engineProfileChoice')?.addEventListener('change',updateProfileChoice);
  $('engineProfileForm')?.addEventListener('submit',applyEngineProfile);
  $('engineProfileReload')?.addEventListener('click',loadEngineProfile);
  const enter=()=>{if(location.hash==='#settings'){open();loadEngineProfile();}};
  window.addEventListener('hashchange',enter);
  window.addEventListener('lotusim-assets-updated',()=>{if(loaded)refreshCatalog();});
  // A model may become ready while the user is editing this page and Unity's
  // watcher finishes in the background. Only the catalogue/options are changed.
  setInterval(()=>{if(location.hash==='#settings'&&!document.hidden)refreshCatalog();},10000);
  $('settingsBlocks').addEventListener('focusout',event=>{
    if(event.target.matches('select[data-config-path$=".model"]'))queueMicrotask(updateModelChoices);
  });
  enter();
})();
